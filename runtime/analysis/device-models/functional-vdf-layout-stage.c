/* SPDX-License-Identifier: MIT */
#define _GNU_SOURCE
#include "functional-vdf-layout-stage.h"
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
static struct functional_vdf_layout_stage_snapshot state;
static struct full_imaging_io transport;
static void *ack_address;
static unsigned int send_started;
static const unsigned char request_header[8] = {0x0d, 0x20, 0x4c, 1, 40, 0, 1, 0x80};
static const unsigned char initial_bank[32] = {
    7, 1, 1, 0, 0, 0, 0, 0, 0x80, 2, 0xe0, 1,
    0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 3, 0, 0, 0, 0, 0, 0, 0
};
static const unsigned char ack_wire[12] = {0x0d, 0x20, 0x4c, 0x11, 12, 0, 1, 0x80, 0, 0, 0x59, 0};
#ifdef HOST_TEST
static unsigned int corrupt_offset = 32;
#endif
static long tid(void) { return syscall(SYS_gettid); }
static int inherited(void) { const int p = atomic_load(&owner_pid); return p && p != getpid(); }
static int lock_owner(void) {
    if (inherited()) return 0;
    pthread_mutex_lock(&mutex); return 1;
}
static uint64_t fnv(const void *pointer, size_t bytes) {
    const unsigned char *p = pointer; uint64_t h = UINT64_C(14695981039346656037);
    for (size_t i = 0; i < bytes; i++) h = (h ^ p[i]) * UINT64_C(1099511628211);
    return h;
}
static uint32_t u32(const unsigned char *p) {
    return p[0] | (uint32_t)p[1] << 8 | (uint32_t)p[2] << 16 | (uint32_t)p[3] << 24;
}
static uint64_t u64(const unsigned char *p) { return u32(p) | (uint64_t)u32(p + 4) << 32; }
static int span(const void *p, size_t n) { return p && n <= UINTPTR_MAX - (uintptr_t)p; }
static int overlap(const void *a, size_t an, const void *b, size_t bn) {
    return (uintptr_t)a < (uintptr_t)b + bn && (uintptr_t)b < (uintptr_t)a + an;
}
static int private_alias(const void *p, size_t n) {
#define ALIAS(object) overlap(p, n, &(object), sizeof(object))
    return ALIAS(state) || ALIAS(transport) || ALIAS(mutex) || ALIAS(owner_pid) ||
        ALIAS(ack_address) || ALIAS(send_started) || ALIAS(dispatching) ||
        ALIAS(request_header) || ALIAS(initial_bank) || ALIAS(ack_wire)
#ifdef HOST_TEST
        || ALIAS(corrupt_offset)
#endif
        ;
#undef ALIAS
}
static void fault(unsigned int index) { state.faults = 1; state.leases[index].faults = 1; }
static int bank_valid(void) {
    return state.bank_written && state.readback_verified &&
        !memcmp(state.bank32, state.original_wire + 8, 32) &&
        !memcmp(state.bank32, state.copied_readback32, 32) &&
        fnv(state.bank32, 32) == state.bank_fnv1a64 &&
        fnv(state.copied_readback32, 32) == state.readback_fnv1a64 &&
        state.bank_fnv1a64 == state.readback_fnv1a64;
}
static void refresh(void) {
    struct native_cp_state_publication_lease *ack = &state.leases[1];
    ack->consumed = ack->queued && ack->received && ack->freed && !ack->releasing &&
        !ack->send_inflight && !ack->send_rc && !ack->free_rc && !ack->faults &&
        ack->sender_tid == ack->receiver_tid && ack->receiver_tid == ack->free_tid;
    state.ack_queued = ack->queued; state.ack_received = ack->received;
    const unsigned int consumed = bank_valid() && state.leases[0].freed && ack->consumed &&
        !state.busy && !state.faults;
    if (consumed && !state.ap_consumed) state.completed_cycles++;
    state.ap_consumed = consumed;
}
int functional_vdf_layout_stage_owner_init(void) {
    const int p = getpid(); int expected = 0;
    atomic_compare_exchange_strong(&owner_pid, &expected, p);
    if (!lock_owner()) return -EXDEV;
    if (state.initialized) { pthread_mutex_unlock(&mutex); return -EALREADY; }
    state.owner_pid = p; state.initialized = state.stage_only = 1;
    pthread_mutex_unlock(&mutex); return 0;
}
void functional_vdf_layout_stage_snapshot(struct functional_vdf_layout_stage_snapshot *out) {
    if (!span(out, sizeof *out) || private_alias(out, sizeof *out)) return;
    if (!lock_owner()) {
        *out = (struct functional_vdf_layout_stage_snapshot){.owner_pid = atomic_load(&owner_pid),
            .faults = 1, .stage_only = 1}; return;
    }
    *out = state; pthread_mutex_unlock(&mutex);
}
static void hex_bytes(char *out, const unsigned char *p, size_t bytes) {
    static const char hex[] = "0123456789abcdef";
    for (size_t i = 0; i < bytes; i++) { out[2 * i] = hex[p[i] >> 4]; out[2 * i + 1] = hex[p[i] & 15]; }
    out[2 * bytes] = 0;
}
static void record(void (*logger)(const char *, const char *), const char *event) {
    if (!logger || inherited()) return;
    struct functional_vdf_layout_stage_snapshot s; functional_vdf_layout_stage_snapshot(&s);
    char tag[80], text[2100], wire[81], bank[65], readback[65];
    hex_bytes(wire, s.original_wire, sizeof s.original_wire);
    hex_bytes(bank, s.bank32, sizeof s.bank32); hex_bytes(readback, s.copied_readback32, sizeof s.copied_readback32);
    snprintf(tag, sizeof tag, "FUNCTIONAL_LAYOUT_STAGE_%s ", event);
    snprintf(text, sizeof text,
        "pid=%d tid=%ld cycle=%llu stage_generation=%llu requests=%u completed_cycles=%u busy=%u faults=%u "
        "source=%#x destination=%#x command=%#x bytes=%u original_fnv1a64=%016llx "
        "bank_written=%u readback_verified=%u bank_fnv1a64=%016llx readback_fnv1a64=%016llx "
        "request_owned=%u request_retained=%p request_freed=%u request_free_rc=%d "
        "ack_retained=%p queued=%u received=%u AP_consumed=%u sender_tid=%ld receiver_tid=%ld free_tid=%ld "
        "send_inflight=%u releasing=%u allocate_rc=%d send_rc=%d free_rc=%d validation_rc=%d "
        "allocation_returned=%p allocation_alias=%u stage_only=1 semantic_applied=0 frame_consumed=0 "
        "hardware_ready=0 capture_verified=0 physical_ASIC_verified=0 original_CP_FIFO_verified=0 "
        "physical_CP_RTOS_verified=0 applied_receipt_verified=%u applied_stage_generation=%llu "
        "applied_model_instance=%llu applied_config_generation=%llu applied_frame_generation=%llu "
        "applied_result_fnv1a64=%016llx raw=%s bank32=%s copied_readback32=%s ack_wire=0d204c110c00018000005900",
        s.owner_pid, tid(), (unsigned long long)s.cycle, (unsigned long long)s.stage_generation,
        s.requests, s.completed_cycles, s.busy, s.faults, s.origin.source, s.origin.destination,
        s.origin.command, s.origin.bytes, (unsigned long long)s.origin.wire_fnv1a64,
        s.bank_written, s.readback_verified, (unsigned long long)s.bank_fnv1a64,
        (unsigned long long)s.readback_fnv1a64, s.request_owned, s.leases[0].pointer,
        s.leases[0].freed, s.leases[0].free_rc, s.leases[1].pointer, s.ack_queued,
        s.ack_received, s.ap_consumed, s.leases[1].sender_tid, s.leases[1].receiver_tid,
        s.leases[1].free_tid, s.leases[1].send_inflight, s.leases[1].releasing,
        s.leases[1].allocate_rc, s.leases[1].send_rc, s.leases[1].free_rc, s.validation_rc,
        s.allocation_returned, s.allocation_alias, s.applied.verified,
        (unsigned long long)s.applied.stage_generation, (unsigned long long)s.applied.model_instance,
        (unsigned long long)s.applied.config_generation, (unsigned long long)s.applied.frame_generation,
        (unsigned long long)s.applied.result_fnv1a64, wire, bank, readback);
    logger(tag, text);
}
static int wire_valid(const struct full_imaging_io *io, void *p, unsigned int bytes,
    unsigned int source, const unsigned char *wire) {
    return io->size(p) == bytes && io->source(p) == source && !memcmp(p, wire, bytes);
}
static int same_lease(unsigned int index, void *p, uint64_t cycle) {
    return state.cycle == cycle && state.leases[index].pointer == p && state.leases[index].releasing;
}
int functional_vdf_layout_stage_observe_receive_cycle(unsigned int destination, void *pointer,
    unsigned int source, unsigned int bytes, uint64_t *ticket) {
    if (inherited()) return -EXDEV;
    if (!pointer) return 0;
    if (!lock_owner()) return -EXDEV;
    struct native_cp_state_publication_lease *ack = &state.leases[1];
    if (pointer != ack->pointer) { pthread_mutex_unlock(&mutex); return 0; }
    const struct native_cp_state_publication_lease saved = *ack;
    const struct full_imaging_io io = transport; const uint64_t cycle = state.cycle;
    if (!span(ticket, sizeof *ticket) || private_alias(ticket, sizeof *ticket) ||
        overlap(ticket, sizeof *ticket, pointer, saved.bytes) || !send_started ||
        (!ack->queued && !ack->send_inflight) || destination != ack->destination ||
        source != ack->source || bytes != ack->bytes || tid() != ack->sender_tid ||
        ack->received || ack->releasing || state.faults) {
        fault(1); pthread_mutex_unlock(&mutex); return -EPROTO;
    }
    ack->releasing = 1; pthread_mutex_unlock(&mutex);
    const int valid = wire_valid(&io, pointer, saved.bytes, saved.source, ack_wire);
    if (!lock_owner()) return -EXDEV;
    if (!same_lease(1, pointer, cycle)) { fault(1); pthread_mutex_unlock(&mutex); return -ESTALE; }
    ack->releasing = 0;
    if (!valid || state.faults) { fault(1); pthread_mutex_unlock(&mutex); return -EPROTO; }
    ack->received = 1; ack->receiver_tid = tid(); *ticket = cycle;
    refresh(); pthread_mutex_unlock(&mutex); record(io.record, "RECEIVE"); return 1;
}
static int release_owned(unsigned int destination, void *pointer, uint64_t ticket,
    int (*real_free)(unsigned int, void *), void (*logger)(const char *, const char *),
    int *result, int internal) {
    if (inherited()) { if (result) *result = -EXDEV; return 1; }
    if (!pointer || !result) return 0;
    if (!lock_owner()) { *result = -EXDEV; return 1; }
    const unsigned int index = internal ? 0u : 1u;
    struct native_cp_state_publication_lease *lease = &state.leases[index];
    if (pointer != lease->pointer) {
        const int stale = !internal && ticket && pointer == ack_address;
        pthread_mutex_unlock(&mutex); if (stale) *result = -ESTALE; return stale;
    }
    if (!internal && (!ticket || ticket != state.cycle)) {
        pthread_mutex_unlock(&mutex); *result = -ESTALE; return 1;
    }
    if (!real_free || destination != lease->destination || lease->releasing ||
        tid() != lease->sender_tid || (!internal && (!lease->received || lease->receiver_tid != tid()))) {
        fault(index); pthread_mutex_unlock(&mutex); *result = -EPROTO; return 1;
    }
    const struct native_cp_state_publication_lease saved = *lease;
    const struct full_imaging_io io = transport; const uint64_t cycle = state.cycle;
    unsigned char wire[40]; memcpy(wire, internal ? state.original_wire : ack_wire, saved.bytes);
    lease->releasing = 1; pthread_mutex_unlock(&mutex);
    const int valid = wire_valid(&io, pointer, saved.bytes, saved.source, wire);
    const int rc = valid ? real_free(destination, pointer) : -EPROTO;
    if (!lock_owner()) { *result = -EXDEV; return 1; }
    if (!same_lease(index, pointer, cycle)) { fault(index); pthread_mutex_unlock(&mutex); *result = -ESTALE; return 1; }
    lease->releasing = 0; lease->free_rc = rc;
    if (rc) fault(index);
    else { lease->pointer = NULL; lease->freed = 1; lease->free_tid = tid(); }
    refresh(); pthread_mutex_unlock(&mutex);
    record(logger, internal ? "REQUEST_FREE" : "AP_FREE"); *result = rc; return 1;
}
int functional_vdf_layout_stage_release_cycle(unsigned int destination, void *pointer, uint64_t ticket,
    int (*real_free)(unsigned int, void *), void (*logger)(const char *, const char *), int *result) {
    return release_owned(destination, pointer, ticket, real_free, logger, result, 0);
}
static int allocate_ack(const struct full_imaging_io *io) {
    if (!lock_owner()) return -EXDEV;
    const unsigned int destination = state.origin.source;
    void *request = state.leases[0].pointer; pthread_mutex_unlock(&mutex);
    void *p = NULL; const int rc = io->allocate(destination, &p, 12, 1);
    const int valid_span = span(p, 12);
    const int alias = valid_span && (private_alias(p, 12) ||
        (request && overlap(p, 12, request, 40)) || overlap(p, 12, io, sizeof *io));
    int valid = !rc && valid_span && !alias;
    if (!lock_owner()) return -EXDEV;
    struct native_cp_state_publication_lease *ack = &state.leases[1];
    ack->allocate_rc = rc; state.allocation_returned = p; state.allocation_alias = (unsigned int)alias;
    if (valid_span && !alias) { ack->pointer = p; ack_address = p; }
    ack->releasing = (unsigned int)valid;
    if (!valid) fault(1);
    pthread_mutex_unlock(&mutex);
    if (valid) {
        valid = io->size(p) == 12;
        if (valid) {
            memcpy(p, ack_wire, 12); io->set_source(p, FUNCTIONAL_LAYOUT_STAGE_SID);
            valid = wire_valid(io, p, 12, FUNCTIONAL_LAYOUT_STAGE_SID, ack_wire);
        }
        if (!lock_owner()) return -EXDEV;
        ack->releasing = 0; if (!valid || state.faults) { fault(1); valid = 0; }
        pthread_mutex_unlock(&mutex);
    }
    return valid ? 0 : rc ? rc : -EPROTO;
}
static int send_ack(const struct full_imaging_io *io) {
    if (!lock_owner()) return -EXDEV;
    struct native_cp_state_publication_lease *ack = &state.leases[1];
    const struct native_cp_state_publication_lease saved = *ack; const uint64_t cycle = state.cycle;
    if (!ack->pointer || ack->releasing || state.faults || !state.leases[0].freed || !bank_valid()) {
        fault(1); pthread_mutex_unlock(&mutex); return -EPROTO;
    }
    ack->releasing = 1; pthread_mutex_unlock(&mutex);
    int valid = wire_valid(io, saved.pointer, saved.bytes, saved.source, ack_wire);
    if (!lock_owner()) return -EXDEV;
    valid = valid && same_lease(1, saved.pointer, cycle) && !state.faults && bank_valid();
    ack->releasing = 0;
    if (valid) { send_started = 1; ack->send_inflight = 1; } else fault(1);
    pthread_mutex_unlock(&mutex); if (!valid) return -EPROTO;
    const int rc = io->send(saved.destination, saved.pointer);
    /* Inline original receive/free can destroy the envelope before send returns. */
    if (!lock_owner()) return -EXDEV;
    if (state.cycle != cycle || !ack->send_inflight || (ack->pointer != saved.pointer && !ack->freed)) {
        fault(1); pthread_mutex_unlock(&mutex); return -ESTALE;
    }
    ack->send_inflight = 0; ack->send_rc = rc;
    if (rc) fault(1); else ack->queued = 1;
    refresh(); pthread_mutex_unlock(&mutex); record(io->record, "SEND"); return rc;
}
static int dispatch(unsigned int destination, void *request, const struct full_imaging_io *io, int *result) {
    if (!span(request, 4) || private_alias(request, 4)) { *result = -EINVAL; return 1; }
    const unsigned int bytes = io->size(request);
    if (bytes < 4 || !span(request, bytes)) { *result = -EINVAL; return 1; }
    const unsigned char *p = request;
    if (memcmp(p, request_header, 4)) return 0;
    *result = -ENODATA;
    if (bytes != 40 || private_alias(request, bytes) || memcmp(p, request_header, 8) ||
        !io->source || !io->allocate || !io->release || !io->send || !io->set_source) return 1;
    if (memcmp(p + 8, initial_bank, 32)) { *result = -EINVAL; return 1; }
    const unsigned int caller = io->source(request);
    if ((caller & UINT32_C(0xffff0000)) != UINT32_C(0x81cf0000)) return 1;
    unsigned char saved[40]; memcpy(saved, request, sizeof saved);
    if (memcmp(saved, request_header, 8) || memcmp(saved + 8, initial_bank, 32) ||
        !wire_valid(io, request, bytes, caller, saved)) { *result = -ESTALE; return 1; }
    if (!lock_owner()) { *result = -EXDEV; return 1; }
    if (!state.initialized || state.faults) { pthread_mutex_unlock(&mutex); return 1; }
    if (state.busy || (state.requests && !state.ap_consumed)) {
        pthread_mutex_unlock(&mutex); *result = -EBUSY; return 1;
    }
    if (state.cycle == UINT64_MAX || state.stage_generation == UINT64_MAX ||
        state.requests == UINT_MAX || state.completed_cycles == UINT_MAX) {
        pthread_mutex_unlock(&mutex); *result = -EOVERFLOW; return 1;
    }
    state.busy = 1; state.cycle++; state.stage_generation++; state.requests++;
    state.origin = (struct fcam_native_origin){caller, destination, 0x014c, bytes, fnv(saved, bytes)};
    state.ap_consumed = state.bank_written = state.readback_verified = state.ack_queued = state.ack_received = 0;
    state.request_owned = 1; state.validation_rc = 0; state.allocation_returned = NULL; state.allocation_alias = 0;
    memset(state.leases, 0, sizeof state.leases); send_started = 0;
    memcpy(state.original_wire, saved, 40); transport = *io;
    state.leases[0] = (struct native_cp_state_publication_lease){.role = 1, .bytes = 40,
        .destination = destination, .source = caller, .pointer = request, .sender_tid = tid(),
        .wire_fnv1a64 = state.origin.wire_fnv1a64};
    state.leases[1] = (struct native_cp_state_publication_lease){.role = 2, .bytes = 12,
        .destination = caller, .source = FUNCTIONAL_LAYOUT_STAGE_SID, .sender_tid = tid(),
        .wire_fnv1a64 = fnv(ack_wire, 12)};
    memcpy(state.bank32, saved + 8, 32); state.bank_written = 1;
    state.bank_fnv1a64 = fnv(state.bank32, 32);
    memcpy(state.copied_readback32, state.bank32, 32);
#ifdef HOST_TEST
    if (corrupt_offset < 32) state.copied_readback32[corrupt_offset] ^= 1;
#endif
    state.readback_fnv1a64 = fnv(state.copied_readback32, 32);
    state.readback_verified = !memcmp(state.bank32, state.copied_readback32, 32) &&
        state.bank_fnv1a64 == state.readback_fnv1a64;
    int rc = state.readback_verified ? 0 : -EIO;
    if (rc) { state.validation_rc = rc; fault(0); }
    pthread_mutex_unlock(&mutex); record(io->record, "READBACK");
    if (!rc) rc = allocate_ack(io);
    if (!rc) {
        int free_rc = -EPROTO;
        release_owned(destination, request, 0, io->release, io->record, &free_rc, 1); rc = free_rc;
    }
    if (!rc) rc = send_ack(io);
    if (!lock_owner()) { *result = 0; return 1; }
    state.busy = 0; refresh(); pthread_mutex_unlock(&mutex);
    record(io->record, rc ? "FAULT" : "COMPLETE"); *result = 0; return 1;
}
int functional_vdf_layout_stage_dispatch(unsigned int destination, void *request,
    const struct full_imaging_io *io, int enabled, int route_ready, int *result) {
    if (enabled != 1 || route_ready != 0 || destination != FUNCTIONAL_LAYOUT_STAGE_SID ||
        !request || !io || !io->size || !result) return 0;
    if (inherited()) { *result = -EXDEV; return 1; }
    if (dispatching) { *result = -EBUSY; return 1; }
    dispatching = 1; const int handled = dispatch(destination, request, io, result);
    dispatching = 0; return handled;
}
int functional_vdf_layout_stage_read_bank(uint64_t generation, void *out, size_t bytes, uint64_t *digest) {
    if (inherited()) return -EXDEV;
    if (bytes != 32 || !span(out, bytes) || !span(digest, sizeof *digest) ||
        private_alias(out, bytes) || private_alias(digest, sizeof *digest) ||
        overlap(out, bytes, digest, sizeof *digest)) return -EINVAL;
    if (!lock_owner()) return -EXDEV;
    int rc = !state.initialized || !state.ap_consumed || state.busy || state.faults ? -ENODATA :
        generation != state.stage_generation ? -ESTALE : !bank_valid() ? -EIO : 0;
    if (!rc) { memcpy(out, state.bank32, bytes); *digest = fnv(out, bytes); }
    pthread_mutex_unlock(&mutex); return rc;
}
int functional_vdf_layout_stage_bind_applied(uint64_t generation, int model_owner_pid, uint64_t instance,
    const void *model192, size_t bytes, const struct fcam_bridge_result *metadata) {
    if (inherited() || model_owner_pid != getpid()) return -EXDEV;
    if (bytes != FCAM_LAYOUT_RESULT_BYTES || !span(model192, bytes) || !span(metadata, sizeof *metadata) ||
        private_alias(model192, bytes) || private_alias(metadata, sizeof *metadata)) return -EINVAL;
    unsigned char p[FCAM_LAYOUT_RESULT_BYTES]; memcpy(p, model192, bytes);
    const struct fcam_bridge_result r = *metadata;
    if (!instance || r.model_instance != instance || r.used != bytes || r.required != bytes || r.result_token ||
        u32(p) != FCAM_ABI_VERSION || u32(p + FCAM_VDF_R_BYTES) != bytes ||
        u64(p + FCAM_VDF_R_INSTANCE) != instance ||
        u32(p + FCAM_VDF_R_ENDPOINT) != FCAM_VDF_ENDPOINT ||
        u32(p + FCAM_VDF_R_SELECTED_MASK) != 1 || u32(p + FCAM_VDF_R_COMPLETED_MASK) != 1 ||
        u32(p + FCAM_VDF_R_CLASS) != 1 || u32(p + FCAM_VDF_R_ENABLED) != 1 ||
        u32(p + FCAM_VDF_R_CONFIG_READBACK) != 1 || u32(p + FCAM_VDF_R_COMMITTED) != 1 ||
        u32(p + FCAM_VDF_R_FRAME_CONSUMED) != 1 || u32(p + FCAM_VDF_R_RETIRED) != 1 ||
        u32(p + FCAM_VDF_R_STATUS) || u32(p + FCAM_VDF_R_RESERVED) ||
        u32(p + FCAM_VDF_R_WIDTH) != 640 || u32(p + FCAM_VDF_R_HEIGHT) != 480 ||
        u32(p + FCAM_VDF_R_STRIDE) != 640 * 3 || u64(p + FCAM_VDF_R_ACTIVE_BYTES) != 640 * 480 * 3 ||
        !u64(p + FCAM_VDF_R_SOURCE_FNV) || u64(p + FCAM_VDF_R_SOURCE_FNV) != u64(p + FCAM_VDF_R_SINK_FNV) ||
        !u64(p + FCAM_VDF_R_LEASE_GENERATION) || p[128] != 1 || p[129] != 5 || p[130] != 5 ||
        p[132] > 2 || p[141] || p[142] || p[143]) return -EPROTO;
    const uint64_t config = u64(p + FCAM_VDF_R_CONFIG_GENERATION), frame = u64(p + FCAM_VDF_R_FRAME_GENERATION);
    if (!config || !frame || u64(p + FCAM_VDF_R_BEFORE_CONFIG_GENERATION) == UINT64_MAX ||
        config != u64(p + FCAM_VDF_R_BEFORE_CONFIG_GENERATION) + 1 ||
        u64(p + FCAM_VDF_R_BEFORE_FRAME_GENERATION) == UINT64_MAX ||
        frame != u64(p + FCAM_VDF_R_BEFORE_FRAME_GENERATION) + 1) return -ESTALE;
    if (!lock_owner()) return -EXDEV;
    int rc = !state.ap_consumed || state.busy || state.faults || !bank_valid() ? -ENODATA :
        generation != state.stage_generation ? -ESTALE :
        memcmp(p + FCAM_LAYOUT_R_CONFIG, state.bank32, 32) ||
        u64(p + FCAM_VDF_R_INPUT_FNV) != state.readback_fnv1a64 ? -EPROTO :
        state.applied.verified && (instance != state.applied.model_instance ||
            config <= state.applied.config_generation || frame <= state.applied.frame_generation ||
            u64(p + FCAM_VDF_R_LEASE_GENERATION) <= state.applied.lease_generation) ? -ESTALE : 0;
    if (!rc) state.applied = (struct functional_vdf_layout_stage_applied){
        .owner_pid = getpid(), .verified = 1, .semantic_applied = 1, .frame_consumed = 1,
        .stage_generation = generation, .model_instance = instance, .config_generation = config,
        .frame_generation = frame, .lease_generation = u64(p + FCAM_VDF_R_LEASE_GENERATION),
        .result_fnv1a64 = fnv(p, bytes)};
    void (*logger)(const char *, const char *) = transport.record;
    pthread_mutex_unlock(&mutex); if (!rc) record(logger, "APPLIED_RECEIPT"); return rc;
}
#ifdef HOST_TEST
void functional_vdf_layout_stage_test_hold_lock(void) { if (!inherited()) pthread_mutex_lock(&mutex); }
void functional_vdf_layout_stage_test_drop_lock(void) { if (!inherited()) pthread_mutex_unlock(&mutex); }
void *functional_vdf_layout_stage_test_private_address(unsigned int index) {
    return index == 0 ? (void *)&state : index == 1 ? (void *)&transport : index == 2 ? (void *)&mutex :
        index == 3 ? (void *)(uintptr_t)initial_bank : (void *)(uintptr_t)ack_wire;
}
void functional_vdf_layout_stage_test_corrupt_readback(unsigned int offset) {
    if (!lock_owner()) return;
    corrupt_offset = offset; pthread_mutex_unlock(&mutex);
}
#endif
