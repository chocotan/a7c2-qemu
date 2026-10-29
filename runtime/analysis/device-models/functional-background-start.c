/* SPDX-License-Identifier: MIT */
#define _GNU_SOURCE
#include "functional-background-start.h"
#include <limits.h>
#include <pthread.h>
#include <stdatomic.h>
#include <stdio.h>
#include <string.h>
#include <sys/syscall.h>
#include <unistd.h>

static pthread_mutex_t mutex = PTHREAD_MUTEX_INITIALIZER;
static _Atomic int owner_pid;
static _Thread_local unsigned int dispatching;
static struct functional_background_start_snapshot state;
static struct full_imaging_io transport;
static struct native_cp_state_publication_guard reservation;
static void *reply_address;

static long tid(void) { return syscall(SYS_gettid); }
static int inherited(void) { int p = atomic_load(&owner_pid); return p && p != getpid(); }
static int error_code(int rc) { return rc < 0 ? rc : -EPROTO; }
static uint32_t u32(const unsigned char *p) {
    return p[0] | (uint32_t)p[1] << 8 | (uint32_t)p[2] << 16 | (uint32_t)p[3] << 24;
}
static uint64_t u64(const unsigned char *p) { return u32(p) | (uint64_t)u32(p + 4) << 32; }
static uint64_t fnv(const void *pointer, size_t bytes) {
    const unsigned char *p = pointer; uint64_t h = UINT64_C(14695981039346656037);
    for (size_t i = 0; i < bytes; i++) h = (h ^ p[i]) * UINT64_C(1099511628211);
    return h;
}
static int span(const void *p, size_t bytes) { return p && bytes <= UINTPTR_MAX - (uintptr_t)p; }
static int overlap(const void *a, size_t an, const void *b, size_t bn) {
    return (uintptr_t)a < (uintptr_t)b + bn && (uintptr_t)b < (uintptr_t)a + an;
}
static int private_alias(const void *p, size_t bytes) {
    return overlap(p, bytes, &state, sizeof state) || overlap(p, bytes, &transport, sizeof transport) ||
        overlap(p, bytes, &reservation, sizeof reservation) || overlap(p, bytes, &mutex, sizeof mutex) ||
        overlap(p, bytes, &owner_pid, sizeof owner_pid) || overlap(p, bytes, &reply_address, sizeof reply_address);
}
static void fault(unsigned int index, int rc) {
    state.faults = 1; state.leases[index].faults = 1;
    if (!state.error) state.error = error_code(rc);
    state.phase = FUNCTIONAL_BACKGROUND_START_FAULT;
}
static void refresh(void) {
    struct native_cp_state_publication_lease *r = &state.leases[1];
    r->consumed = r->queued && r->received && r->freed && !r->send_inflight && !r->releasing &&
        !r->send_rc && !r->free_rc && !r->faults && r->sender_tid == r->receiver_tid &&
        r->receiver_tid == r->free_tid;
    state.original_request_freed = state.leases[0].freed;
    state.reply_queued = r->queued; state.reply_received = r->received;
    state.reply_retained = r->pointer != NULL;
    state.live_leases = (state.leases[0].pointer != NULL) + (r->pointer != NULL);
    const unsigned int complete = state.model_complete && state.readback_verified &&
        state.original_request_freed && r->consumed && !state.working && !state.guard_held && !state.faults;
    if (complete && !state.ap_consumed) state.completed_cycles++;
    state.ap_consumed = state.transport_complete = complete;
    state.pending = state.requests && !complete;
    if (state.faults) state.phase = FUNCTIONAL_BACKGROUND_START_FAULT;
    else if (complete) state.phase = FUNCTIONAL_BACKGROUND_START_AP_CONSUMED;
    else if (r->received) state.phase = FUNCTIONAL_BACKGROUND_START_REPLY_RECEIVED;
    else if (r->queued) state.phase = FUNCTIONAL_BACKGROUND_START_REPLY_QUEUED;
    else if (state.model_complete) state.phase = FUNCTIONAL_BACKGROUND_START_MODEL_COMPLETE;
    else if (state.working) state.phase = FUNCTIONAL_BACKGROUND_START_PROBING;
    else if (state.pending) state.phase = FUNCTIONAL_BACKGROUND_START_PENDING;
}
int functional_background_start_owner_init(void) {
    int p = getpid(), expected = 0;
    atomic_compare_exchange_strong(&owner_pid, &expected, p);
    if (atomic_load(&owner_pid) != p) return -EXDEV;
    pthread_mutex_lock(&mutex);
    if (state.initialized) { pthread_mutex_unlock(&mutex); return -EALREADY; }
    state.owner_pid = p; state.initialized = state.functional_model = 1;
    pthread_mutex_unlock(&mutex); return 0;
}
int functional_background_start_bind_source_once(unsigned int source) {
    if (inherited()) return -EXDEV;
    if (!source || source == UINT_MAX || source == FUNCTIONAL_BACKGROUND_START_SID) return -EINVAL;
    pthread_mutex_lock(&mutex);
    int rc = 0;
    if (!state.initialized) rc = -ENODEV;
    else if (state.bound && state.bound_source != source &&
        (state.phase != FUNCTIONAL_BACKGROUND_START_AP_CONSUMED || state.pending ||
         state.working || state.guard_held || state.live_leases)) rc = -ESTALE;
    else if (state.faults) rc = -EPROTO;
    else if (state.working) rc = -EBUSY;
    else { state.bound = 1; state.bound_source = source; }
    pthread_mutex_unlock(&mutex); return rc;
}
void functional_background_start_snapshot(struct functional_background_start_snapshot *out) {
    if (!out) return;
    if (inherited()) {
        *out = (struct functional_background_start_snapshot){.owner_pid = atomic_load(&owner_pid),
            .functional_model = 1, .faults = 1, .pending = 1,
            .error = -EXDEV, .phase = FUNCTIONAL_BACKGROUND_START_FAULT};
        return;
    }
    pthread_mutex_lock(&mutex); *out = state; pthread_mutex_unlock(&mutex);
}
static void hex_bytes(char *out, const unsigned char *p, size_t bytes) {
    static const char hex[] = "0123456789abcdef";
    for (size_t i = 0; i < bytes; i++) { out[2 * i] = hex[p[i] >> 4]; out[2 * i + 1] = hex[p[i] & 15]; }
    out[2 * bytes] = 0;
}
static uint64_t record_sequence;
static uint64_t record_snapshot(struct functional_background_start_snapshot *out) {
    if (inherited()) { functional_background_start_snapshot(out); return 0; }
    pthread_mutex_lock(&mutex);
    if (record_sequence == UINT64_MAX) fault(0, -EOVERFLOW);
    else record_sequence++;
    *out = state;
    const uint64_t sequence = record_sequence;
    pthread_mutex_unlock(&mutex); return sequence;
}
static void record(void (*logger)(const char *, const char *), const char *event) {
    if (!logger) return;
    struct functional_background_start_snapshot s; const uint64_t snapshot = record_snapshot(&s);
    char tag[96], text[1536], raw[49], reply[25];
    hex_bytes(raw, s.original_wire, sizeof s.original_wire); hex_bytes(reply, s.reply_wire, sizeof s.reply_wire);
    snprintf(tag, sizeof tag, "FUNCTIONAL_BACKGROUND_START_%s ", event);
    snprintf(text, sizeof text,
        "pid=%d tid=%ld snapshot_id=%llu cycle=%llu phase=%u bound=%u source=%#x requests=%u pending=%u working=%u guard=%u faults=%u "
        "error=%d reserve_rc=%d predecessor_rc=%d sender_tid=%ld producer_tid=%ld receiver_tid=%ld "
        "init_calls=%u state_calls=%u receive_ticket=%llu free_ticket=%llu "
        "model_complete=%u functional_core_initialized=%u state_copied=%u readback=%u "
        "request_freed=%u reply_queued=%u reply_received=%u reply_retained=%u live=%u transport_complete=%u AP_consumed=%u "
        "destination=%#x command=%#x bytes=%u wire_fnv=%016llx raw24=%s reply12=%s "
        "source_physical_verified=0 CP_modules_verified=0 original_masks_verified=0 original_CP_RTOS_verified=0 "
        "business_published=0 hardware_ready=0 image_ready=0 capture_verified=0",
        s.owner_pid, tid(), (unsigned long long)snapshot, (unsigned long long)s.cycle, s.phase, s.bound, s.bound_source, s.requests, s.pending,
        s.working, s.guard_held, s.faults, s.error, s.reserve_rc, s.predecessor_rc,
        s.sender_tid, s.producer_tid, s.receiver_tid, s.init_called, s.state_called,
        (unsigned long long)s.receive_ticket, (unsigned long long)s.free_ticket,
        s.model_complete, s.functional_core_initialized,
        s.state_copied, s.readback_verified, s.original_request_freed, s.reply_queued, s.reply_received,
        s.reply_retained, s.live_leases, s.transport_complete, s.ap_consumed,
        s.origin.destination, s.origin.command, s.origin.bytes, (unsigned long long)s.origin.wire_fnv1a64, raw, reply);
    logger(tag, text);
    for (unsigned int i = 0; i < 2; i++) {
        const struct native_cp_state_publication_lease *l = &s.leases[i];
        snprintf(text, sizeof text,
            "pid=%d snapshot_id=%llu cycle=%llu lease=%u pointer=%p source=%#x destination=%#x bytes=%u fnv=%016llx "
            "queued=%u received=%u freed=%u consumed=%u inflight=%u releasing=%u faults=%u "
            "sender_tid=%ld receiver_tid=%ld free_tid=%ld allocate_rc=%d send_rc=%d free_rc=%d "
            "allocation_returned=%p allocation_alias=%u",
            s.owner_pid, (unsigned long long)snapshot, (unsigned long long)s.cycle, i, l->pointer, l->source, l->destination, l->bytes,
            (unsigned long long)l->wire_fnv1a64, l->queued, l->received, l->freed, l->consumed,
            l->send_inflight, l->releasing, l->faults, l->sender_tid, l->receiver_tid, l->free_tid,
            l->allocate_rc, l->send_rc, l->free_rc, s.allocation_returned, s.allocation_alias);
        logger("FUNCTIONAL_BACKGROUND_START_LEASE ", text);
    }
}
static void record_probe(void (*logger)(const char *, const char *), int init, const char *event) {
    if (!logger) return;
    struct functional_background_start_snapshot s; const uint64_t snapshot = record_snapshot(&s);
    const struct fcam_bridge_result r = init ? s.init_result : s.state_result;
    char tag[96], text[2048], raw[FCAM_STATE_BYTES * 2 + 1];
    char cached[FCAM_STATE_BYTES * 2 + 1], readback[FCAM_STATE_BYTES * 2 + 1];
    hex_bytes(cached, s.model_state, FCAM_STATE_BYTES); hex_bytes(readback, s.copied_readback, FCAM_STATE_BYTES);
    snprintf(tag, sizeof tag, "FUNCTIONAL_BACKGROUND_START_%s ", event);
    hex_bytes(raw, init ? s.init_state : s.actual_state, FCAM_STATE_BYTES);
    snprintf(text, sizeof text,
        "pid=%d snapshot_id=%llu cycle=%llu stage=%s calls=%u bridge_rc=%d validation_rc=%d used=%zu required=%zu "
        "instance=%llu result_token=%llu full_state_fnv=%016llx cache_fnv=%016llx readback_fnv=%016llx "
        "config_generation=%llu frame_generation=%llu rendered=%llu consumed=%llu jpeg_encoded=%llu "
        "video_encoded=%llu result_bytes_read=%llu actual_state128=%s cached_state128=%s readback_state128=%s",
        s.owner_pid, (unsigned long long)snapshot, (unsigned long long)s.cycle, event, init ? s.init_called : s.state_called,
        init ? s.init_rc : s.state_rc, s.validation_rc, r.used, r.required,
        (unsigned long long)r.model_instance, (unsigned long long)r.result_token,
        (unsigned long long)(init ? s.init_fnv1a64 : s.state_fnv1a64),
        (unsigned long long)s.cache_fnv1a64, (unsigned long long)s.readback_fnv1a64,
        (unsigned long long)s.config_generation, (unsigned long long)s.frame_generation,
        (unsigned long long)s.rendered, (unsigned long long)s.consumed,
        (unsigned long long)s.jpeg_encoded, (unsigned long long)s.video_encoded,
        (unsigned long long)s.result_bytes_read, raw, cached, readback);
    logger(tag, text);
}
static int wire_valid(const struct full_imaging_io *io, void *p, unsigned int bytes,
    unsigned int source, const unsigned char *wire) {
    return io->size(p) == bytes && io->source(p) == source && !memcmp(p, wire, bytes);
}
static int validate_state(const unsigned char *p, const struct fcam_bridge_result *r) {
    if (r->used != FCAM_STATE_BYTES || r->required != FCAM_STATE_BYTES || r->result_token ||
        u32(p + FCAM_S_ABI) != FCAM_ABI_VERSION || u32(p + FCAM_S_CAPS) != FCAM_CAPABILITIES || u64(p + 120))
        return -EPROTO;
    if (!r->model_instance || u64(p + FCAM_S_INSTANCE) != r->model_instance) return -ESTALE;
    if (!u64(p + FCAM_S_GENERATION)) return -ENODATA;
    const uint32_t aperture = u32(p + FCAM_S_FNUMBER);
    if (!u32(p + FCAM_S_WIDTH) || u32(p + FCAM_S_WIDTH) > FCAM_MAX_STILL_WIDTH ||
        !u32(p + FCAM_S_HEIGHT) || u32(p + FCAM_S_HEIGHT) > FCAM_MAX_STILL_HEIGHT ||
        !u32(p + FCAM_S_FPS) || u32(p + FCAM_S_FPS) > 120 ||
        !u32(p + FCAM_S_QUALITY) || u32(p + FCAM_S_QUALITY) > 100 ||
        (aperture != 400 && aperture != 800 && aperture != 1600) || !u32(p + FCAM_S_ISO) ||
        !u64(p + FCAM_S_SHUTTER) || (u64(p + FCAM_S_FOCUS) != UINT64_MAX && u64(p + FCAM_S_FOCUS) < 100000))
        return -ERANGE;
    const uint64_t rendered = u64(p + FCAM_S_RENDERED), consumed = u64(p + FCAM_S_CONSUMED);
    if (!rendered || !u64(p + FCAM_S_FRAME_GENERATION)) return -ENODATA;
    if (consumed > rendered || u64(p + FCAM_S_JPEG_ENCODED) > consumed ||
        u64(p + FCAM_S_VIDEO_ENCODED) > consumed - u64(p + FCAM_S_JPEG_ENCODED)) return -EPROTO;
    if (u32(p + FCAM_S_STREAM_STATE) == 3) return -EIO;
    if (u32(p + FCAM_S_PENDING_RESULTS) || u32(p + FCAM_S_STREAM_STATE)) return -EBUSY;
    return 0;
}
static int probe(const struct fcam_native_origin *origin, int init) {
    struct { unsigned char before[16], bytes[FCAM_STATE_BYTES], after[16]; } out;
    memset(&out, 0xa5, sizeof out); memset(out.bytes, 0, sizeof out.bytes);
    struct fcam_bridge_result r = {0};
    pthread_mutex_lock(&mutex);
    if (state.faults) { const int error = state.error; pthread_mutex_unlock(&mutex); return error; }
    if (init) state.init_called++; else state.state_called++;
    pthread_mutex_unlock(&mutex);
    record(transport.record, init ? "INIT_BEGIN" : "STATE_BEGIN");
    const int bridge_rc = fcam_bridge_call(origin, init ? FCAM_OP_INIT : FCAM_OP_STATE,
        NULL, 0, out.bytes, sizeof out.bytes, &r);
    int rc = bridge_rc ? error_code(bridge_rc) : validate_state(out.bytes, &r);
    for (size_t i = 0; i < sizeof out.before; i++)
        if (out.before[i] != 0xa5 || out.after[i] != 0xa5) rc = -EOVERFLOW;
    pthread_mutex_lock(&mutex);
    if (init) {
        memcpy(state.init_state, out.bytes, sizeof out.bytes);
        state.init_result = r; state.init_rc = bridge_rc; state.init_fnv1a64 = fnv(out.bytes, sizeof out.bytes);
    } else {
        memcpy(state.actual_state, out.bytes, sizeof out.bytes);
        state.state_result = r; state.state_rc = bridge_rc; state.state_fnv1a64 = fnv(out.bytes, sizeof out.bytes);
        if (!rc && (state.init_result.model_instance != r.model_instance ||
            memcmp(state.init_state, out.bytes, sizeof out.bytes))) rc = -ESTALE;
    }
    if (!rc && state.faults) rc = state.error;
    state.validation_rc = rc;
    if (rc) fault(0, rc);
    else state.probe_successes++;
    pthread_mutex_unlock(&mutex);
    record_probe(transport.record, init, init ? "INIT" : "STATE"); return rc;
}
static int cache_state(void) {
    pthread_mutex_lock(&mutex);
    if (state.faults) { const int rc = state.error; pthread_mutex_unlock(&mutex); return rc; }
    memcpy(state.model_state, state.actual_state, FCAM_STATE_BYTES); state.state_copied = 1;
    state.cache_fnv1a64 = fnv(state.model_state, FCAM_STATE_BYTES);
    memcpy(state.copied_readback, state.model_state, FCAM_STATE_BYTES);
    state.readback_fnv1a64 = fnv(state.copied_readback, FCAM_STATE_BYTES);
    const int valid = !memcmp(state.copied_readback, state.actual_state, FCAM_STATE_BYTES) &&
        state.cache_fnv1a64 == state.state_fnv1a64 && state.readback_fnv1a64 == state.state_fnv1a64;
    if (!valid) fault(0, -EIO);
    else {
        state.readback_verified = state.functional_core_initialized = state.model_complete = 1;
        state.model_instance = u64(state.model_state + FCAM_S_INSTANCE);
        state.config_generation = u64(state.model_state + FCAM_S_GENERATION);
        state.frame_generation = u64(state.model_state + FCAM_S_FRAME_GENERATION);
        state.rendered = u64(state.model_state + FCAM_S_RENDERED);
        state.consumed = u64(state.model_state + FCAM_S_CONSUMED);
        state.jpeg_encoded = u64(state.model_state + FCAM_S_JPEG_ENCODED);
        state.video_encoded = u64(state.model_state + FCAM_S_VIDEO_ENCODED);
        state.result_bytes_read = u64(state.model_state + FCAM_S_RESULT_READ);
    }
    refresh(); pthread_mutex_unlock(&mutex); record_probe(transport.record, 0, "READBACK");
    return valid ? 0 : -EIO;
}
static int original_unchanged(void) {
    pthread_mutex_lock(&mutex);
    struct native_cp_state_publication_lease *l = &state.leases[0];
    const struct native_cp_state_publication_lease saved = *l;
    unsigned char wire[FUNCTIONAL_BACKGROUND_START_REQUEST_BYTES]; memcpy(wire, state.original_wire, sizeof wire);
    if (!l->pointer || l->releasing || state.faults) {
        fault(0, -EPROTO); pthread_mutex_unlock(&mutex); return -EPROTO;
    }
    l->releasing = 1; pthread_mutex_unlock(&mutex);
    const int valid = wire_valid(&transport, saved.pointer, saved.bytes, saved.source, wire);
    pthread_mutex_lock(&mutex); l->releasing = 0;
    if (!valid) fault(0, -EPROTO);
    const int rc = state.faults ? state.error : 0;
    pthread_mutex_unlock(&mutex); return rc;
}
static int release_original(void) {
    pthread_mutex_lock(&mutex);
    struct native_cp_state_publication_lease *l = &state.leases[0];
    if (state.faults || !state.model_complete || !l->pointer || l->releasing || state.producer_tid != tid()) {
        fault(0, -EPROTO); pthread_mutex_unlock(&mutex); return -EPROTO;
    }
    const struct native_cp_state_publication_lease saved = *l;
    unsigned char wire[FUNCTIONAL_BACKGROUND_START_REQUEST_BYTES]; memcpy(wire, state.original_wire, sizeof wire);
    l->releasing = 1; l->receiver_tid = tid(); pthread_mutex_unlock(&mutex);
    const int valid = wire_valid(&transport, saved.pointer, saved.bytes, saved.source, wire);
    const int rc = valid ? transport.release(saved.destination, saved.pointer) : -EPROTO;
    pthread_mutex_lock(&mutex);
    l->releasing = 0; l->free_rc = rc;
    if (valid) l->free_tid = tid();
    if (rc) fault(0, rc);
    else { l->pointer = NULL; l->freed = 1; }
    refresh(); const int result = state.faults ? state.error : 0;
    pthread_mutex_unlock(&mutex); record(transport.record, "REQUEST_FREE"); return result;
}
static int allocate_reply(void) {
    void *p = NULL;
    const int rc = transport.allocate(state.origin.source, &p, FUNCTIONAL_BACKGROUND_START_REPLY_BYTES, 1);
    pthread_mutex_lock(&mutex);
    struct native_cp_state_publication_lease *l = &state.leases[1];
    const int valid_span = span(p, FUNCTIONAL_BACKGROUND_START_REPLY_BYTES);
    const int alias = valid_span && (private_alias(p, FUNCTIONAL_BACKGROUND_START_REPLY_BYTES) ||
        (state.leases[0].pointer && overlap(p, FUNCTIONAL_BACKGROUND_START_REPLY_BYTES,
            state.leases[0].pointer, state.leases[0].bytes)));
    state.allocation_returned = p; state.allocation_alias = (unsigned int)alias; l->allocate_rc = rc;
    if (valid_span && !alias) { l->pointer = p; reply_address = p; }
    int valid = !rc && valid_span && !alias && !state.faults;
    if (valid) l->releasing = 1; else fault(1, rc ? rc : -EPROTO);
    pthread_mutex_unlock(&mutex);
    if (valid) {
        valid = transport.size(p) == FUNCTIONAL_BACKGROUND_START_REPLY_BYTES;
        if (valid) {
            memcpy(p, state.reply_wire, FUNCTIONAL_BACKGROUND_START_REPLY_BYTES);
            transport.set_source(p, FUNCTIONAL_BACKGROUND_START_SID);
            valid = wire_valid(&transport, p, FUNCTIONAL_BACKGROUND_START_REPLY_BYTES,
                FUNCTIONAL_BACKGROUND_START_SID, state.reply_wire);
        }
        pthread_mutex_lock(&mutex); l->releasing = 0;
        if (!valid) fault(1, -EPROTO);
        valid = valid && !state.faults;
        pthread_mutex_unlock(&mutex);
    }
    pthread_mutex_lock(&mutex); refresh(); const int result = valid ? 0 : state.error;
    pthread_mutex_unlock(&mutex); record(transport.record, "ALLOCATE"); return result;
}
static int send_reply(void) {
    pthread_mutex_lock(&mutex);
    struct native_cp_state_publication_lease *l = &state.leases[1];
    const struct native_cp_state_publication_lease saved = *l;
    if (state.faults || !l->pointer || l->releasing || !state.leases[0].freed) {
        fault(1, -EPROTO); pthread_mutex_unlock(&mutex); return -EPROTO;
    }
    l->releasing = 1; pthread_mutex_unlock(&mutex);
    const int valid = wire_valid(&transport, saved.pointer, saved.bytes, saved.source, state.reply_wire);
    pthread_mutex_lock(&mutex); l->releasing = 0;
    if (!valid || state.faults) { fault(1, -EPROTO); pthread_mutex_unlock(&mutex); return -EPROTO; }
    l->send_inflight = 1; pthread_mutex_unlock(&mutex);
    const int rc = transport.send(saved.destination, saved.pointer);
    /* Actual receive/free can run inline and destroy the envelope before send returns. */
    pthread_mutex_lock(&mutex);
    l->send_inflight = 0; l->send_rc = rc;
    if (rc) fault(1, rc); else l->queued = 1;
    refresh(); const int result = state.faults ? state.error : 0;
    pthread_mutex_unlock(&mutex); record(transport.record, "SEND"); return result;
}
static int finish(int rc) {
    pthread_mutex_lock(&mutex);
    const unsigned int held = state.guard_held;
    state.guard_held = 0;
    pthread_mutex_unlock(&mutex);
    if (held) reservation.release();
    pthread_mutex_lock(&mutex);
    state.working = 0;
    if (rc) fault(0, rc);
    refresh(); const int result = state.faults ? state.error : rc;
    pthread_mutex_unlock(&mutex); record(transport.record, result ? "FAULT" : "PROGRESS"); return result;
}
int functional_background_start_progress(void) {
    if (inherited()) return -EXDEV;
    pthread_mutex_lock(&mutex);
    if (!state.initialized || !state.pending || state.working || state.model_complete) {
        const int rc = state.faults ? state.error : 0;
        pthread_mutex_unlock(&mutex); return rc;
    }
    if (state.faults) { const int rc = state.error; pthread_mutex_unlock(&mutex); return rc; }
    state.working = 1;
    const struct fcam_native_origin origin = state.origin;
    pthread_mutex_unlock(&mutex);
    int rc = reservation.predecessor_ready();
    pthread_mutex_lock(&mutex); state.predecessor_rc = rc; pthread_mutex_unlock(&mutex);
    if (!rc || rc == -ENODATA) return finish(0);
    if (rc != 1) return finish(error_code(rc));
    rc = original_unchanged();
    if (rc) return finish(rc);
    rc = reservation.reserve();
    pthread_mutex_lock(&mutex);
    state.reserve_rc = rc;
    if (!rc) state.guard_held = 1;
    pthread_mutex_unlock(&mutex);
    if (rc) return finish(error_code(rc));
    rc = reservation.predecessor_ready();
    pthread_mutex_lock(&mutex); state.predecessor_rc = rc; pthread_mutex_unlock(&mutex);
    if (!rc || rc == -ENODATA) return finish(-ESTALE);
    if (rc != 1) return finish(error_code(rc));
    pthread_mutex_lock(&mutex); state.producer_tid = tid(); refresh(); pthread_mutex_unlock(&mutex);
    rc = probe(&origin, 1);
    if (!rc) rc = probe(&origin, 0);
    if (!rc) rc = cache_state();
    if (!rc) rc = release_original();
    if (!rc) rc = allocate_reply();
    if (!rc) rc = send_reply();
    const int result = finish(rc); return result ? result : 1;
}
static int dispatch(unsigned int destination, void *request, const struct full_imaging_io *io,
    const struct native_cp_state_publication_guard *guard, int *result) {
    const unsigned int bytes = io->size(request);
    if (bytes < 4 || !span(request, bytes)) return 0;
    const unsigned char *p = request;
    if (p[2] != 6 || p[3] != 0x30) return 0;
    *result = FUNCTIONAL_BACKGROUND_START_BLOCKED;
    if (bytes != FUNCTIONAL_BACKGROUND_START_REQUEST_BYTES || p[0] != 0 ||
        !io->allocate || !io->release || !io->set_source || !io->send || !io->source ||
        !guard || !guard->reserve || !guard->release || !guard->predecessor_ready) return 1;
    const unsigned int source = io->source(request);
    unsigned char wire[FUNCTIONAL_BACKGROUND_START_REQUEST_BYTES]; memcpy(wire, request, sizeof wire);
    pthread_mutex_lock(&mutex);
    if (!state.initialized || !state.bound || source != state.bound_source) {
        pthread_mutex_unlock(&mutex); return 1;
    }
    if (state.faults) { pthread_mutex_unlock(&mutex); *result = -EPROTO; return 1; }
    if (state.pending || state.working) { pthread_mutex_unlock(&mutex); *result = -EBUSY; return 1; }
    if (private_alias(request, bytes)) { pthread_mutex_unlock(&mutex); *result = -EINVAL; return 1; }
    if (state.cycle == UINT64_MAX || state.requests == UINT_MAX || state.completed_cycles == UINT_MAX ||
        state.init_called == UINT_MAX || state.state_called == UINT_MAX || state.probe_successes > UINT_MAX - 2) {
        pthread_mutex_unlock(&mutex); *result = -EOVERFLOW; return 1;
    }
    state = (struct functional_background_start_snapshot){
        .owner_pid = state.owner_pid, .initialized = 1, .functional_model = 1,
        .bound = 1, .bound_source = source, .requests = state.requests + 1,
        .completed_cycles = state.completed_cycles, .cycle = state.cycle + 1,
        .init_called = state.init_called, .state_called = state.state_called, .probe_successes = state.probe_successes,
        .pending = 1, .phase = FUNCTIONAL_BACKGROUND_START_PENDING, .sender_tid = tid(),
        .origin = {source, destination, 0x3006, bytes, fnv(wire, bytes)}};
    memcpy(state.original_wire, wire, sizeof wire);
    state.reply_wire[0] = 1; state.reply_wire[2] = 6; state.reply_wire[3] = 0x30;
    memcpy(state.reply_wire + 4, wire + 4, 4); state.reply_wire[9] = 0xf0;
    state.leases[0] = (struct native_cp_state_publication_lease){.role = 0, .bytes = bytes,
        .destination = destination, .source = source, .sender_tid = tid(), .pointer = request,
        .wire_fnv1a64 = state.origin.wire_fnv1a64, .send_rc = -ENODATA, .free_rc = -ENODATA};
    state.leases[1] = (struct native_cp_state_publication_lease){.role = 1,
        .bytes = FUNCTIONAL_BACKGROUND_START_REPLY_BYTES, .destination = source,
        .source = FUNCTIONAL_BACKGROUND_START_SID, .sender_tid = tid(),
        .wire_fnv1a64 = fnv(state.reply_wire, sizeof state.reply_wire),
        .allocate_rc = -ENODATA, .send_rc = -ENODATA, .free_rc = -ENODATA};
    transport = *io; reservation = *guard; refresh(); pthread_mutex_unlock(&mutex);
    record(io->record, "ACCEPT"); (void)functional_background_start_progress();
    *result = 0; return 1;
}
int functional_background_start_dispatch(unsigned int destination, void *request, const struct full_imaging_io *io,
    const struct native_cp_state_publication_guard *guard, int enabled, int *result) {
    if (enabled != 1 || destination != FUNCTIONAL_BACKGROUND_START_SID || !request || !io || !io->size || !result) return 0;
    if (inherited()) { *result = -EXDEV; return 1; }
    if (dispatching) { *result = -EDEADLK; return 1; }
    dispatching = 1; const int handled = dispatch(destination, request, io, guard, result);
    dispatching = 0; return handled;
}
int functional_background_start_observe_receive_cycle(unsigned int destination, void *pointer,
    unsigned int source, unsigned int bytes, uint64_t *ticket) {
    if (inherited()) return -EXDEV;
    if (!pointer) return 0;
    pthread_mutex_lock(&mutex);
    struct native_cp_state_publication_lease *l = &state.leases[1];
    if (l->pointer != pointer) { pthread_mutex_unlock(&mutex); return 0; }
    if (!ticket || state.faults || (!l->queued && !l->send_inflight) || l->releasing || l->received ||
        destination != l->destination || source != l->source || bytes != l->bytes || tid() != l->sender_tid) {
        fault(1, -EPROTO); pthread_mutex_unlock(&mutex); return -EPROTO;
    }
    const struct native_cp_state_publication_lease saved = *l;
    l->releasing = 1; pthread_mutex_unlock(&mutex);
    const int valid = wire_valid(&transport, pointer, saved.bytes, saved.source, state.reply_wire);
    pthread_mutex_lock(&mutex); l->releasing = 0;
    if (!valid || state.faults) { fault(1, -EPROTO); pthread_mutex_unlock(&mutex); return -EPROTO; }
    l->received = 1; l->receiver_tid = state.receiver_tid = tid();
    state.receive_ticket = *ticket = state.cycle;
    refresh(); pthread_mutex_unlock(&mutex); record(transport.record, "RECEIVE"); return 1;
}
int functional_background_start_release_cycle(unsigned int destination, void *pointer, uint64_t ticket,
    int (*real_free)(unsigned int, void *), void (*logger)(const char *, const char *), int *result) {
    if (!pointer || !result) return 0;
    if (inherited()) { *result = -EXDEV; return 1; }
    pthread_mutex_lock(&mutex);
    struct native_cp_state_publication_lease *l = &state.leases[1];
    if (pointer != l->pointer) {
        if (pointer == state.leases[0].pointer) {
            if (ticket && ticket != state.cycle) {
                pthread_mutex_unlock(&mutex); *result = -ESTALE; return 1;
            }
            fault(0, -EPROTO); pthread_mutex_unlock(&mutex); *result = -EPROTO; return 1;
        }
        const int stale = ticket && pointer == reply_address;
        pthread_mutex_unlock(&mutex); if (stale) *result = -ESTALE; return stale;
    }
    if (!ticket || ticket != state.cycle) { pthread_mutex_unlock(&mutex); *result = -ESTALE; return 1; }
    if (state.faults || !real_free || destination != l->destination || l->releasing || !l->received ||
        tid() != l->sender_tid || tid() != l->receiver_tid) {
        fault(1, -EPROTO); pthread_mutex_unlock(&mutex); *result = -EPROTO; return 1;
    }
    const struct native_cp_state_publication_lease saved = *l;
    state.free_ticket = ticket;
    l->releasing = 1; pthread_mutex_unlock(&mutex);
    const int valid = wire_valid(&transport, pointer, saved.bytes, saved.source, state.reply_wire);
    const int rc = valid ? real_free(destination, pointer) : -EPROTO;
    pthread_mutex_lock(&mutex); l->releasing = 0; l->free_rc = rc;
    if (valid) l->free_tid = tid();
    if (rc) fault(1, rc);
    else { l->pointer = NULL; l->freed = 1; }
    refresh(); pthread_mutex_unlock(&mutex); record(logger, "AP_FREE"); *result = rc; return 1;
}
#ifdef HOST_TEST
void functional_background_start_test_hold_lock(void) { pthread_mutex_lock(&mutex); }
void functional_background_start_test_drop_lock(void) { pthread_mutex_unlock(&mutex); }
void *functional_background_start_test_snapshot_address(void) { return &state; }
#endif
