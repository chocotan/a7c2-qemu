/* SPDX-License-Identifier: MIT */
#define _GNU_SOURCE
#include "functional-still-format.h"
#include <limits.h>
#include <pthread.h>
#include <stdatomic.h>
#include <stdio.h>
#include <string.h>
#include <sys/syscall.h>
#include <unistd.h>

static pthread_mutex_t mutex = PTHREAD_MUTEX_INITIALIZER;
static _Atomic int owner_pid;
static _Thread_local unsigned int inspecting;
static struct functional_still_format_snapshot state;
static struct full_imaging_io transport;
static long tid(void) { return syscall(SYS_gettid); }
static int inherited(void) { int p = atomic_load(&owner_pid); return p && p != getpid(); }
static uint32_t u32(const unsigned char *p) {
    return p[0] | (uint32_t)p[1] << 8 | (uint32_t)p[2] << 16 | (uint32_t)p[3] << 24;
}
static uint64_t u64(const unsigned char *p) { return u32(p) | (uint64_t)u32(p + 4) << 32; }
static int span(const void *p, size_t n) { return p && n <= UINTPTR_MAX - (uintptr_t)p; }
static int overlap(const void *a, size_t an, const void *b, size_t bn) {
    return (uintptr_t)a < (uintptr_t)b + bn && (uintptr_t)b < (uintptr_t)a + an;
}
static uint64_t hash(const void *p, size_t n) {
    const unsigned char *b = p; uint64_t h = UINT64_C(14695981039346656037);
    for (size_t i = 0; i < n; i++) h = (h ^ b[i]) * UINT64_C(1099511628211);
    return h;
}
static int private_alias(const void *p, size_t n) {
    return overlap(p, n, &state, sizeof state) || overlap(p, n, &transport, sizeof transport) ||
        overlap(p, n, &owner_pid, sizeof owner_pid) || overlap(p, n, &mutex, sizeof mutex) ||
        overlap(p, n, fcam_still_format_initial, sizeof fcam_still_format_initial);
}
static void fault(unsigned int index) { state.faults = state.leases[index].faults = 1; }
static void refresh(void) {
    struct native_cp_state_publication_lease *r = &state.leases[0], *a = &state.leases[1];
    state.retained = (r->pointer != NULL) + (unsigned int)(a->pointer != NULL);
    a->consumed = a->queued && a->received && a->freed && a->free_tid == a->sender_tid &&
        !a->send_inflight && !a->releasing && !a->send_rc && !a->free_rc && !a->faults;
    const unsigned int done = state.request_owned && state.model_complete && r->freed && a->consumed &&
        !state.faults && !state.busy && !state.guard_held && !state.retained && !r->releasing;
    if (done && !state.ap_consumed) state.completed_cycles++;
    state.ap_consumed = done;
}
int functional_still_format_owner_init(void) {
    int pid = getpid(), expected = 0;
    atomic_compare_exchange_strong(&owner_pid, &expected, pid);
    if (atomic_load(&owner_pid) != pid) return -EXDEV;
    pthread_mutex_lock(&mutex);
    if (state.initialized) { pthread_mutex_unlock(&mutex); return -EALREADY; }
    state.owner_pid = pid; state.initialized = state.functional_only = 1;
    pthread_mutex_unlock(&mutex); return 0;
}
void functional_still_format_snapshot(struct functional_still_format_snapshot *out) {
    if (!span(out, sizeof *out) || private_alias(out, sizeof *out)) return;
    if (inherited()) {
        *out = (struct functional_still_format_snapshot){.owner_pid = atomic_load(&owner_pid), .faults = 1, .functional_only = 1};
        return;
    }
    pthread_mutex_lock(&mutex); *out = state; pthread_mutex_unlock(&mutex);
}
static void record(void (*logger)(const char *, const char *), const char *event) {
    if (!logger) return;
    struct functional_still_format_snapshot s; functional_still_format_snapshot(&s);
    char text[1536];
    snprintf(text, sizeof text,
        "event=%s pid=%d tid=%ld cycle=%llu requests=%u completed=%u busy=%u guard=%u faults=%u retained=%u "
        "model_instance=%llu before_cfg=%llu cfg=%llu before_frame=%llu frame=%llu lease=%llu "
        "state_rc=%d state_validation_rc=%d bridge_rc=%d validation_rc=%d transport_rc=%d attempted=%u model_complete=%u "
        "origin_fnv=%016llx result_fnv=%016llx used=%zu required=%zu token=%llu "
        "request=%p reply=%p req_free_rc=%d alloc_rc=%d send_rc=%d reply_free_rc=%d "
        "queued=%u received=%u freed=%u send_inflight=%u sender_tid=%ld receiver_tid=%ld free_tid=%ld AP_consumed=%u "
        "functional_only=1 original_AP_verified=0 original_CP=0 physical_ASIC_verified=0 physical_CP_RTOS_verified=0 capture_verified=0",
        event, s.owner_pid, tid(), (unsigned long long)s.cycle, s.requests, s.completed_cycles, s.busy, s.guard_held, s.faults, s.retained,
        (unsigned long long)s.model_instance, (unsigned long long)s.before_config_generation, (unsigned long long)s.config_generation,
        (unsigned long long)s.before_frame_generation, (unsigned long long)s.frame_generation, (unsigned long long)s.lease_generation,
        s.state_bridge_rc, s.state_validation_rc, s.bridge_rc, s.validation_rc, s.transport_rc, s.operation_attempted, s.model_complete,
        (unsigned long long)s.actual_origin_fnv, (unsigned long long)s.result_fnv, s.format_response.used, s.format_response.required,
        (unsigned long long)s.format_response.result_token, s.leases[0].pointer, s.leases[1].pointer, s.leases[0].free_rc,
        s.leases[1].allocate_rc, s.leases[1].send_rc, s.leases[1].free_rc, s.leases[1].queued, s.leases[1].received,
        s.leases[1].freed, s.leases[1].send_inflight, s.leases[1].sender_tid, s.leases[1].receiver_tid, s.leases[1].free_tid, s.ap_consumed);
    logger("FUNCTIONAL_STILL_FORMAT ", text);
}
static int envelope(const struct full_imaging_io *io, void *p, unsigned int bytes, unsigned int src, const unsigned char *wire) {
    return io->size(p) == bytes && io->source(p) == src && !memcmp(p, wire, bytes) &&
        io->size(p) == bytes && io->source(p) == src && !memcmp(p, wire, bytes);
}
static int same(unsigned int index, const struct native_cp_state_publication_lease *l, uint64_t cycle) {
    const struct native_cp_state_publication_lease *a = &state.leases[index];
    return state.cycle == cycle && a->pointer == l->pointer && a->wire_fnv1a64 == l->wire_fnv1a64 && a->role == l->role;
}
static int release_owned(unsigned int dst, void *p, int (*real_free)(unsigned int, void *),
    void (*logger)(const char *, const char *), int *result, uint64_t ticket, int internal, int qualified) {
    if (!p || !real_free || !span(result, sizeof *result) || !span(p, 12) ||
        private_alias(result, sizeof *result) || overlap(p, 12, result, sizeof *result)) return 0;
    if (inherited()) { *result = -EXDEV; return 1; }
    pthread_mutex_lock(&mutex);
    unsigned int index = state.leases[0].pointer == p ? 0 : 1;
    if (state.leases[index].pointer != p) { pthread_mutex_unlock(&mutex); return 0; }
    if (!internal && ((qualified && !ticket) || (ticket ? ticket != state.cycle : state.cycle != 1))) {
        pthread_mutex_unlock(&mutex); *result = -ESTALE; return 1;
    }
    const struct native_cp_state_publication_lease l = state.leases[index];
    if (overlap(p, l.bytes, result, sizeof *result)) { pthread_mutex_unlock(&mutex); return 0; }
    const struct full_imaging_io io = transport; const uint64_t cycle = state.cycle;
    unsigned char wire[24]; memcpy(wire, index ? state.reply_wire : state.original_wire, l.bytes);
    int valid = !state.faults && !l.releasing && dst == l.destination && tid() == l.sender_tid &&
        (internal ? index == 0 : index == 1 && l.received && (l.queued || l.send_inflight));
    if (!valid) { fault(index); pthread_mutex_unlock(&mutex); *result = -EPROTO; return 1; }
    state.leases[index].releasing = 1; pthread_mutex_unlock(&mutex);
    valid = envelope(&io, p, l.bytes, l.source, wire);
    pthread_mutex_lock(&mutex); valid = valid && same(index, &l, cycle) && !state.faults; pthread_mutex_unlock(&mutex);
    int rc = valid ? real_free(dst, p) : -EPROTO;
    pthread_mutex_lock(&mutex);
    if (!same(index, &l, cycle) || !state.leases[index].releasing) rc = -ESTALE;
    state.leases[index].releasing = 0; state.leases[index].free_rc = rc;
    if (rc) fault(index);
    else { state.leases[index].pointer = NULL; state.leases[index].freed = 1; state.leases[index].free_tid = tid(); }
    refresh(); pthread_mutex_unlock(&mutex); record(logger, internal ? "REQUEST_FREE" : "SENDER_FREE");
    *result = rc; return 1;
}
int functional_still_format_release_cycle(unsigned int dst, void *p, int (*real_free)(unsigned int, void *),
    void (*logger)(const char *, const char *), int *result, uint64_t ticket) {
    return release_owned(dst, p, real_free, logger, result, ticket, 0, 1);
}
int functional_still_format_release(unsigned int dst, void *p, int (*real_free)(unsigned int, void *),
    void (*logger)(const char *, const char *), int *result) {
    return release_owned(dst, p, real_free, logger, result, 0, 0, 0);
}
static int receive(unsigned int dst, void *p, unsigned int src, unsigned int bytes, uint64_t ticket, int qualified) {
    if (inherited()) return -EXDEV;
    pthread_mutex_lock(&mutex); const struct native_cp_state_publication_lease l = state.leases[1];
    if (!p || p != l.pointer) { pthread_mutex_unlock(&mutex); return 0; }
    if ((qualified && !ticket) || (ticket ? ticket != state.cycle : state.cycle != 1)) { pthread_mutex_unlock(&mutex); return -ESTALE; }
    const struct full_imaging_io io = transport; const uint64_t cycle = state.cycle;
    unsigned char wire[12]; memcpy(wire, state.reply_wire, 12);
    int valid = !state.faults && !l.releasing && !l.received && (l.queued || l.send_inflight) &&
        dst == l.destination && src == l.source && bytes == 12;
    if (!valid) { fault(1); pthread_mutex_unlock(&mutex); return -EPROTO; }
    state.leases[1].releasing = 1; pthread_mutex_unlock(&mutex);
    valid = envelope(&io, p, bytes, src, wire);
    pthread_mutex_lock(&mutex);
    valid = valid && same(1, &l, cycle) && state.leases[1].releasing && !state.faults;
    state.leases[1].releasing = 0;
    /* Original CP receive resolves an asynchronous promise on another thread. */
    if (valid) { state.leases[1].received = 1; state.leases[1].receiver_tid = tid(); }
    else fault(1);
    refresh(); pthread_mutex_unlock(&mutex); record(io.record, "RECEIVE"); return valid ? 1 : -EPROTO;
}
int functional_still_format_observe_receive_cycle(unsigned int dst, void *p, unsigned int src, unsigned int bytes, uint64_t ticket) {
    return receive(dst, p, src, bytes, ticket, 1);
}
int functional_still_format_observe_receive(unsigned int dst, void *p, unsigned int src, unsigned int bytes) {
    return receive(dst, p, src, bytes, 0, 0);
}
static int shape(const unsigned char *p, const struct fcam_bridge_result *r, size_t n) {
    return r->used == n && r->required == n && !r->result_token && u32(p) == FCAM_ABI_VERSION;
}
static int validate_state(const unsigned char *p, const struct fcam_bridge_result *r,
    const struct functional_still_format_snapshot *old) {
    if (!shape(p, r, 128) || u32(p + 4) != FCAM_CAPABILITIES || !r->model_instance ||
        u64(p + 48) != r->model_instance || u64(p + 120)) return -EPROTO;
    if (old->model_instance && old->model_instance != r->model_instance) return -ESTALE;
    if (u32(p + 8) != 640 || u32(p + 12) != 480) return -ENOTSUP;
    if (!u32(p + 16) || u32(p + 16) > 120 || !u32(p + 20) || u32(p + 20) > 100 ||
        (u32(p + 24) != 400 && u32(p + 24) != 800 && u32(p + 24) != 1600) || !u32(p + 28) ||
        !u64(p + 32) || (u64(p + 40) != UINT64_MAX && u64(p + 40) < 100000)) return -EPROTO;
    if (u32(p + 104) || u32(p + 108)) return -EBUSY;
    if (!u64(p + 56) || !u64(p + 64) || !u64(p + 112)) return -ENODATA;
    if (u64(p + 72) > u64(p + 64) || u64(p + 80) > u64(p + 72) || u64(p + 88) > u64(p + 72)) return -EPROTO;
    if (u64(p + 56) == UINT64_MAX || u64(p + 112) == UINT64_MAX || u64(p + 64) == UINT64_MAX || u64(p + 72) == UINT64_MAX) return -EOVERFLOW;
    if (u64(p + 56) < old->config_generation || u64(p + 112) < old->frame_generation) return -ESTALE;
    return 0;
}
static int validate_format(const unsigned char *p, const struct fcam_bridge_result *r,
    const struct functional_still_format_snapshot *s) {
    const unsigned char *route = p + 128;
    if (!shape(p, r, 176) || u32(p + 4) != 176 || r->model_instance != s->model_instance ||
        u64(p + 8) != s->model_instance || u64(p + 40) != hash(s->canonical16, 16) ||
        memcmp(p + 160, s->canonical16, 16) || route[0] != 1 || route[1] != 5 || route[2] != 5 ||
        route[4] > 2 || route[13] || route[14] || route[15]) return -EPROTO;
    if (u64(p + 144) != s->before_frame_generation || u64(p + 152) != s->before_config_generation ||
        u64(p + 16) != s->before_config_generation + 1 || u64(p + 24) != s->before_frame_generation + 1 ||
        !u64(p + 32) || u64(p + 32) < u64(s->model_state + FCAM_S_RENDERED) + 1 ||
        u64(p + 32) < u64(p + 24) || u64(p + 32) <= s->before_lease_generation) return -EPROTO;
    if (!u64(p + 48) || u64(p + 48) != u64(p + 56) || u64(p + 64) != UINT64_C(921600) ||
        u32(p + 72) != 640 || u32(p + 76) != 480 || u32(p + 80) != 1920 ||
        u32(p + 84) != FCAM_VDF_ENDPOINT || u32(p + 88) != 1 || u32(p + 92) != 1 ||
        u32(p + 96) != FCAM_STILL_FORMAT_CLASS || u32(p + 100) != 1 || u32(p + 104) != 1 ||
        u32(p + 108) != 1 || u32(p + 112) != 1 || u32(p + 116) != 1 || u32(p + 120) || u32(p + 124)) return -EPROTO;
    return 0;
}
static int call_model(const struct fcam_native_origin *origin, const unsigned char saved[24]) {
    struct functional_still_format_snapshot old; functional_still_format_snapshot(&old);
    pthread_mutex_lock(&mutex);
    state.cycle++; state.state_valid = state.operation_attempted = state.model_complete = state.ap_consumed = state.request_owned = 0;
    state.before_config_generation = state.before_frame_generation = 0; state.before_lease_generation = old.lease_generation;
    memset(state.leases, 0, sizeof state.leases); memset(state.reply_wire, 0, sizeof state.reply_wire);
    state.origin = *origin; state.actual_origin_fnv = origin->wire_fnv1a64;
    memcpy(state.original_wire, saved, 24); memcpy(state.canonical16, saved + 8, 14); memset(state.canonical16 + 14, 0, 2);
    memset(&state.format_response, 0, sizeof state.format_response); memset(state.model_result, 0, sizeof state.model_result);
    state.result_fnv = 0; state.bridge_rc = state.validation_rc = state.transport_rc = 0;
    pthread_mutex_unlock(&mutex);
    struct { unsigned char before[16], data[176], after[16]; } out;
    struct fcam_bridge_result r = {0}; memset(&out, 0xa5, sizeof out); memset(out.data, 0, 128);
    int actual = fcam_bridge_call(origin, FCAM_OP_STATE, NULL, 0, out.data, 128, &r);
    int rc = actual > 0 ? -EPROTO : actual;
    for (size_t i = 0; i < 16; i++) if (out.before[i] != 0xa5 || out.after[i] != 0xa5) rc = -EOVERFLOW;
    for (size_t i = 128; i < 176; i++) if (out.data[i] != 0xa5) rc = -EOVERFLOW;
    if (!rc) rc = validate_state(out.data, &r, &old);
    pthread_mutex_lock(&mutex); state.state_bridge_rc = actual; state.state_validation_rc = rc; state.state_response = r;
    memcpy(state.model_state, out.data, 128);
    if (!rc) {
        state.state_valid = 1; state.model_instance = r.model_instance;
        state.before_config_generation = u64(out.data + 56); state.before_frame_generation = u64(out.data + 112);
    } else fault(0);
    pthread_mutex_unlock(&mutex); return rc;
}
static int apply_model(void) {
    struct functional_still_format_snapshot s; functional_still_format_snapshot(&s);
    struct { unsigned char before[16], data[176], after[16]; } out;
    memset(&out, 0xa5, sizeof out); memset(out.data, 0, 176);
    struct fcam_bridge_result r = {0};
    pthread_mutex_lock(&mutex); state.operation_attempted = 1; pthread_mutex_unlock(&mutex);
    const int actual = fcam_bridge_call(&s.origin, FCAM_OP_STILL_FORMAT, s.canonical16, 16, out.data, 176, &r);
    int rc = actual > 0 ? -EPROTO : actual;
    for (size_t i = 0; i < 16; i++) if (out.before[i] != 0xa5 || out.after[i] != 0xa5) rc = -EOVERFLOW;
    if (!rc) rc = validate_format(out.data, &r, &s);
    pthread_mutex_lock(&mutex); state.bridge_rc = actual; state.validation_rc = rc; state.format_response = r;
    memcpy(state.model_result, out.data, 176); state.result_fnv = hash(out.data, 176);
    state.config_generation = u64(out.data + 16); state.frame_generation = u64(out.data + 24); state.lease_generation = u64(out.data + 32);
    if (rc) fault(0); else state.model_complete = 1;
    pthread_mutex_unlock(&mutex); return rc;
}
static void finish(const struct native_cp_state_publication_guard *guard) {
    pthread_mutex_lock(&mutex); unsigned int held = state.guard_held; pthread_mutex_unlock(&mutex);
    if (held) guard->release();
    pthread_mutex_lock(&mutex); state.guard_held = state.busy = 0; refresh(); pthread_mutex_unlock(&mutex);
    inspecting = 0;
}
static int allocate_send(const struct full_imaging_io *io, const struct native_cp_state_publication_guard *guard, int *result) {
    void *p = NULL; int rc = io->allocate(FUNCTIONAL_STILL_FORMAT_AP, &p, 12, 1);
    const int alias = span(p, 12) && (private_alias(p, 12) || overlap(p, 12, io, sizeof *io) ||
        overlap(p, 12, guard, sizeof *guard) || overlap(p, 12, result, sizeof *result));
    pthread_mutex_lock(&mutex);
    struct native_cp_state_publication_lease *a = &state.leases[1];
    *a = (struct native_cp_state_publication_lease){.role = 2, .bytes = 12, .destination = FUNCTIONAL_STILL_FORMAT_AP,
        .source = FUNCTIONAL_STILL_FORMAT_SID, .sender_tid = tid(), .allocate_rc = rc, .wire_fnv1a64 = hash(state.reply_wire, 12)};
    if (p && !alias) a->pointer = p;
    int valid = !rc && span(p, 12) && !alias && !state.faults;
    unsigned char wire[12]; memcpy(wire, state.reply_wire, 12);
    if (!valid) fault(1);
    refresh(); pthread_mutex_unlock(&mutex);
    if (!valid) return rc ? rc : -EPROTO;
    valid = io->size(p) == 12;
    if (valid) { memcpy(p, wire, 12); io->set_source(p, FUNCTIONAL_STILL_FORMAT_SID); valid = envelope(io, p, 12, FUNCTIONAL_STILL_FORMAT_SID, wire); }
    pthread_mutex_lock(&mutex);
    valid = valid && !state.faults && state.leases[1].pointer == p;
    if (valid) state.leases[1].send_inflight = 1; else fault(1);
    const uint64_t cycle = state.cycle; pthread_mutex_unlock(&mutex);
    if (!valid) return -EPROTO;
    rc = io->send(FUNCTIONAL_STILL_FORMAT_AP, p);
    pthread_mutex_lock(&mutex);
    if (state.cycle != cycle || !state.leases[1].send_inflight || (state.leases[1].pointer != p && !state.leases[1].freed)) fault(1);
    state.leases[1].send_inflight = 0; state.leases[1].send_rc = rc;
    if (rc) fault(1); else state.leases[1].queued = 1;
    refresh(); pthread_mutex_unlock(&mutex); return rc;
}
int functional_still_format_dispatch(unsigned int dst, void *request, const struct full_imaging_io *provided,
    const struct native_cp_state_publication_guard *provided_guard, int enabled, int *result) {
    if (enabled != 1 || dst != FUNCTIONAL_STILL_FORMAT_SID || !provided || !span(request, 4) ||
        !span(result, sizeof *result) || private_alias(result, sizeof *result) || private_alias(request, 4) ||
        overlap(request, 4, result, sizeof *result)) return 0;
    if (inherited() || inspecting) { *result = inherited() ? -EXDEV : -EBUSY; return 1; }
    const struct full_imaging_io io = *provided;
    const struct native_cp_state_publication_guard guard = provided_guard ? *provided_guard : (struct native_cp_state_publication_guard){0};
    if (!io.size) return 0;
    inspecting = 1; unsigned int bytes = io.size(request);
    if (!span(request, bytes) || private_alias(request, bytes) || bytes < 4 || ((unsigned char *)request)[0] != 5 ||
        ((unsigned char *)request)[2] != 0x2d || ((unsigned char *)request)[3] != 0x40) { inspecting = 0; return 0; }
    if (overlap(request, bytes, result, sizeof *result) || overlap(request, bytes, provided, sizeof *provided) ||
        (provided_guard && overlap(request, bytes, provided_guard, sizeof *provided_guard)) || overlap(result, sizeof *result, provided, sizeof *provided) ||
        (provided_guard && overlap(result, sizeof *result, provided_guard, sizeof *provided_guard))) { inspecting = 0; return 0; }
    *result = FUNCTIONAL_STILL_FORMAT_BLOCKED;
    if (bytes != 24 || !io.source || !io.allocate || !io.set_source || !io.send || !io.release ||
        !guard.reserve || !guard.release || !guard.predecessor_ready || io.source(request) != FUNCTIONAL_STILL_FORMAT_AP) { inspecting = 0; return 1; }
    unsigned char saved[24], canonical[16] = {0}; memcpy(saved, request, 24); memcpy(canonical, saved + 8, 14);
    if (!fcam_still_format_input_valid(canonical)) { inspecting = 0; return 1; }
    pthread_mutex_lock(&mutex);
    int ready = state.initialized && !state.busy && !state.guard_held && !state.faults && !state.retained &&
        (!state.requests || state.ap_consumed) && !state.leases[1].releasing && !state.leases[1].send_inflight;
    if (ready && (state.cycle == UINT64_MAX || state.requests == UINT_MAX || state.completed_cycles == UINT_MAX)) {
        pthread_mutex_unlock(&mutex); inspecting = 0; *result = -EOVERFLOW; return 1;
    }
    if (ready) state.busy = 1;
    pthread_mutex_unlock(&mutex);
    if (!ready) { inspecting = 0; *result = -EBUSY; return 1; }
    int rc = guard.reserve();
    if (!rc) { pthread_mutex_lock(&mutex); state.guard_held = 1; pthread_mutex_unlock(&mutex); }
    if (rc || guard.predecessor_ready() != 1 || !envelope(&io, request, 24, FUNCTIONAL_STILL_FORMAT_AP, saved)) {
        finish(&guard); if (rc) *result = rc; return 1;
    }
    const struct fcam_native_origin origin = {FUNCTIONAL_STILL_FORMAT_AP, dst, 0x402d, 24, hash(saved, 24)};
    rc = call_model(&origin, saved);
    if (!rc && (guard.predecessor_ready() != 1 || !envelope(&io, request, 24, origin.source, saved))) rc = -ESTALE;
    if (!rc) rc = apply_model();
    if (!rc && (guard.predecessor_ready() != 1 || !envelope(&io, request, 24, origin.source, saved))) rc = -ESTALE;
    pthread_mutex_lock(&mutex);
    if (!rc && state.faults) rc = -EPROTO;
    if (rc) { fault(0); state.validation_rc = rc; }
    if (!rc) {
        transport = io; state.requests++; state.request_owned = 1;
        state.leases[0] = (struct native_cp_state_publication_lease){.role = 1, .bytes = 24, .destination = dst,
            .source = origin.source, .pointer = request, .sender_tid = tid(), .wire_fnv1a64 = origin.wire_fnv1a64};
        memcpy(state.reply_wire, (unsigned char[12]){1,0,0x2d,0x40,0,0,0,0,0,0xf0,0,0}, 12);
        memcpy(state.reply_wire + 4, saved + 4, 4); refresh();
    }
    pthread_mutex_unlock(&mutex);
    if (rc) { record(io.record, "REFUSED"); finish(&guard); *result = rc; return 1; }
    int freed = -EPROTO; release_owned(dst, request, io.release, io.record, &freed, 0, 1, 0);
    if (!freed) freed = allocate_send(&io, &guard, result);
    pthread_mutex_lock(&mutex); state.transport_rc = freed; pthread_mutex_unlock(&mutex);
    finish(&guard); record(io.record, "CYCLE"); *result = 0; return 1;
}
#ifdef HOST_TEST
void functional_still_format_test_hold_lock(void) { pthread_mutex_lock(&mutex); }
void functional_still_format_test_drop_lock(void) { pthread_mutex_unlock(&mutex); }
#endif
