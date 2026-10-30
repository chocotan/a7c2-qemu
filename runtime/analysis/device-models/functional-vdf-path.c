/* SPDX-License-Identifier: MIT */
#define _GNU_SOURCE
#include "functional-vdf-path.h"
#include <limits.h>
#include <pthread.h>
#include <stdatomic.h>
#include <stdio.h>
#include <string.h>
#include <sys/syscall.h>
#include <unistd.h>

/* Stable parent-owned bridge API; this owner never implements the transport. */
extern int fcam_bridge_bb_startup_config(const struct fcam_native_origin *, const unsigned char[32],
    unsigned char[192], struct fcam_bridge_result *);

static pthread_mutex_t mutex = PTHREAD_MUTEX_INITIALIZER;
static _Atomic int owner_pid;
static _Thread_local unsigned int dispatching;
static struct functional_vdf_path_snapshot state;
static struct full_imaging_io transport;
static void *ack_address;
static unsigned int send_started;
static const unsigned char path_ack[FUNCTIONAL_VDF_PATH_ACK_BYTES] = {
    0x0d, 0x20, 0x38, 0x11, 0x0c, 0, 1, 0x80, 0, 0, 0x59, 0
};
static const unsigned char zebra_ack[FUNCTIONAL_VDF_PATH_ACK_BYTES] = {
    0x0d, 0x20, 0x53, 0x11, 0x0c, 0, 1, 0x80, 0, 0, 0, 0
};
static const unsigned char layout_ack[FUNCTIONAL_VDF_PATH_ACK_BYTES] = {
    0x0d, 0x20, 0x4c, 0x11, 0x0c, 0, 1, 0x80, 0, 0, 0x59, 0
};
static const unsigned char bit_width_ack[FUNCTIONAL_VDF_PATH_ACK_BYTES] = {
    0x0d, 0x20, 0x5e, 0x11, 0x0c, 0, 1, 0x80, 0, 0, 0x59, 0
};
static const unsigned char peaking_ack[FUNCTIONAL_VDF_PATH_ACK_BYTES] = {
    0x0d, 0x20, 0x52, 0x11, 0x0c, 0, 1, 0x80, 0, 0, 0x59, 0
};
static const unsigned char flag_ack[FUNCTIONAL_VDF_PATH_ACK_BYTES] = {
    0x0d, 0x20, 0x62, 0x11, 0x0c, 0, 1, 0x80, 0, 0, 0x59, 0
};
static const unsigned char refresh_ack[FUNCTIONAL_VDF_PATH_ACK_BYTES] = {
    0x0d, 0x20, 0x41, 0x11, 0x0c, 0, 1, 0x80, 0, 0, 0x59, 0
};
static const unsigned char bb_ack[FCAM_BB_FEATURES][FUNCTIONAL_VDF_PATH_ACK_BYTES] = {
    {0x0d, 0x20, 0x11, 0x11, 0x0c, 0, 1, 0x80, 0, 0, 0, 0},
    {0x0d, 0x20, 0x66, 0x11, 0x0c, 0, 1, 0x80, 0, 0, 0, 0},
    {0x0d, 0x20, 0x67, 0x11, 0x0c, 0, 1, 0x80, 0, 0, 0, 0},
    {0x0d, 0x20, 0x5f, 0x11, 0x0c, 0, 1, 0x80, 0, 0, 0, 0},
    {0x0d, 0x20, 0x28, 0x11, 0x0c, 0, 1, 0x80, 0, 0, 0, 0}
};
static unsigned int bb_body_bytes(unsigned int command) {
    switch (command) {
    case FCAM_BB_CMD_0111: case FCAM_BB_CMD_0166: return 28;
    case FCAM_BB_CMD_0167: return 2;
    case FCAM_BB_CMD_015F: return 4;
    case FCAM_BB_CMD_0128: return 12;
    default: return 0;
    }
}
static const unsigned char peaking_palettes[4][3] = {
    {81, 90, 240}, {210, 16, 146}, {29, 255, 83}, {235, 128, 128}
};
/* Software case0 policy is declared in the shared ABI, not physical ASIC format. */
static const unsigned char initial_layout32[FCAM_LAYOUT_INPUT_BYTES] = {
    7, 1, 1, 0, 0, 0, 0, 0, 0x80, 2, 0xe0, 1,
    0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 3, 0, 0, 0, 0, 0, 0, 0
};
static const unsigned char *ack_wire_for(unsigned int command) {
    switch (command) {
    case FCAM_BB_CMD_0111: return bb_ack[0];
    case FCAM_BB_CMD_0166: return bb_ack[1];
    case FCAM_BB_CMD_0167: return bb_ack[2];
    case FCAM_BB_CMD_015F: return bb_ack[3];
    case FCAM_BB_CMD_0128: return bb_ack[4];
    default: break;
    }
    return command == 0x015e ? bit_width_ack : command == 0x0141 ? refresh_ack : command == 0x0152 ? peaking_ack : command == 0x0162 ? flag_ack :
        command == 0x014c ? layout_ack : command == 0x0153 ? zebra_ack : path_ack;
}
static int display_body_valid(unsigned int command, const unsigned char *body) {
    if (command == 0x0141) return 1;
    if (command == 0x0162) return !body[0] && !body[1];
    if (command != 0x0152 || body[0] != 3 || body[1] || body[2] > 2 ||
        (body[3] != 0 && body[3] != 10 && body[3] != 40) || body[4]) return 0;
    for (size_t i = 0; i < sizeof peaking_palettes / sizeof *peaking_palettes; i++)
        if (!memcmp(body + 5, peaking_palettes[i], 3)) return 1;
    return 0;
}
static void display_input(unsigned char *out, unsigned int command, const unsigned char *body) {
    const unsigned int bytes = command == 0x0152 ? 8u : command == 0x0162 ? 2u : 0u;
    memset(out, 0, FCAM_DISPLAY_INPUT_BYTES);
    out[0] = (unsigned char)command; out[1] = (unsigned char)(command >> 8);
    out[4] = (unsigned char)bytes; memcpy(out + 8, body, bytes);
}

static long tid(void) { return syscall(SYS_gettid); }
static int inherited(void) { int p = atomic_load(&owner_pid); return p && p != getpid(); }
static uint32_t u32(const unsigned char *p) {
    return p[0] | (uint32_t)p[1] << 8 | (uint32_t)p[2] << 16 | (uint32_t)p[3] << 24;
}
static int bb_body_valid(unsigned int command, const unsigned char *body) {
    const unsigned int bytes = bb_body_bytes(command);
    unsigned int zero_from;
    switch (command) {
    case FCAM_BB_CMD_0111:
        if (body[0] || body[1] || body[2] != 15 || body[3] != 2) return 0;
        zero_from = 4; break;
    case FCAM_BB_CMD_0166:
        return fcam_bb_0166_body_valid(body);
    case FCAM_BB_CMD_0167:
        if (body[0] > 1) return 0;
        zero_from = 1; break;
    case FCAM_BB_CMD_015F: zero_from = 0; break;
    case FCAM_BB_CMD_0128: {
        const uint32_t period = u32(body + 4);
        if (body[0] || body[1] != 1 || body[2] || body[3] ||
            !((period >= 1 && period <= 10) || period == 20 || period == 30 ||
              period == 40 || period == 50 || period == 60)) return 0;
        zero_from = 8; break;
    }
    default: return 0;
    }
    for (unsigned int i = zero_from; i < bytes; i++) if (body[i]) return 0;
    return 1;
}
static void bb_input(unsigned char *out, unsigned int command, const unsigned char *body) {
    const unsigned int bytes = bb_body_bytes(command);
    memset(out, 0, FCAM_BB_INPUT_BYTES);
    out[0] = (unsigned char)command; out[1] = (unsigned char)(command >> 8);
    out[2] = (unsigned char)bytes; memcpy(out + FCAM_BB_I_BODY, body, bytes);
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
static void fault(unsigned int index) {
    state.faults = 1; state.leases[index].faults = 1; state.phase = FUNCTIONAL_VDF_PATH_FAULT;
}
static void refresh(void) {
    struct native_cp_state_publication_lease *ack = &state.leases[FUNCTIONAL_VDF_PATH_ACK];
    ack->consumed = ack->queued && ack->received && ack->freed && !ack->releasing &&
        !ack->send_inflight && !ack->send_rc && !ack->free_rc && !ack->faults &&
        ack->free_tid == ack->receiver_tid && ack->receiver_tid == ack->sender_tid;
    state.ack_queued = ack->queued; state.ack_received = ack->received;
    const unsigned int consumed = state.model_complete && state.leases[FUNCTIONAL_VDF_PATH_REQUEST].freed &&
        ack->consumed && !state.busy && !state.faults;
    if (consumed && !state.ap_consumed) state.completed_cycles++;
    state.ap_consumed = consumed;
    if (state.faults) state.phase = FUNCTIONAL_VDF_PATH_FAULT;
    else if (consumed) state.phase = FUNCTIONAL_VDF_PATH_AP_CONSUMED;
    else if (ack->received) state.phase = FUNCTIONAL_VDF_PATH_ACK_RECEIVED;
    else if (ack->queued) state.phase = FUNCTIONAL_VDF_PATH_ACK_QUEUED;
    else if (state.model_complete) state.phase = FUNCTIONAL_VDF_PATH_MODEL_COMPLETE;
}
int functional_vdf_path_owner_init(void) {
    int p = getpid(), expected = 0;
    atomic_compare_exchange_strong(&owner_pid, &expected, p);
    if (atomic_load(&owner_pid) != p) return -EXDEV;
    pthread_mutex_lock(&mutex);
    if (state.initialized) { pthread_mutex_unlock(&mutex); return -EALREADY; }
    state.owner_pid = p; state.initialized = state.functional_model = 1;
    state.canonical_config[1] = state.canonical_config[2] = 1;
    pthread_mutex_unlock(&mutex); return 0;
}
int functional_vdf_path_bind_refresh_queue(unsigned int source) {
    if (inherited()) return -EXDEV;
    if (!source || source == UINT_MAX || source == FUNCTIONAL_VDF_PATH_SID) return -EINVAL;
    pthread_mutex_lock(&mutex);
    int rc = 0;
    if (!state.initialized) rc = -ENODEV;
    else if (state.faults) rc = -EPROTO;
    else if (state.busy || (state.requests && !state.ap_consumed)) rc = -EBUSY;
    else if (state.refresh_queue_bound && state.refresh_queue_source != source) rc = -ESTALE;
    else { state.refresh_queue_bound = 1; state.refresh_queue_source = source; }
    pthread_mutex_unlock(&mutex); return rc;
}
void functional_vdf_path_snapshot(struct functional_vdf_path_snapshot *out) {
    if (!out) return;
    if (inherited()) {
        *out = (struct functional_vdf_path_snapshot){.owner_pid = atomic_load(&owner_pid),
            .faults = 1, .functional_model = 1, .phase = FUNCTIONAL_VDF_PATH_FAULT};
        return;
    }
    pthread_mutex_lock(&mutex); *out = state; pthread_mutex_unlock(&mutex);
}
static void hex_bytes(char *out, const unsigned char *p, size_t bytes) {
    static const char hex[] = "0123456789abcdef";
    for (size_t i = 0; i < bytes; i++) { out[2 * i] = hex[p[i] >> 4]; out[2 * i + 1] = hex[p[i] & 15]; }
    out[2 * bytes] = 0;
}
static void record(void (*logger)(const char *, const char *), const char *event) {
    if (!logger) return;
    struct functional_vdf_path_snapshot s; functional_vdf_path_snapshot(&s);
    char tag[96], text[3000], raw[FUNCTIONAL_VDF_MAX_REQUEST_BYTES * 2 + 1];
    char ack[25], canonical[33], zebra[17], layout[FCAM_LAYOUT_INPUT_BYTES * 2 + 1];
    char display[FCAM_DISPLAY_INPUT_BYTES * 2 + 1], bb[FCAM_BB_INPUT_BYTES * 2 + 1];
    char bit_width[FCAM_BIT_WIDTH_INPUT_BYTES * 2 + 1];
    char model_hex[FCAM_VDF_RESULT_MAX_BYTES * 2 + 1];
    hex_bytes(raw, s.original_wire, s.origin.bytes);
    hex_bytes(ack, ack_wire_for(s.origin.command), FUNCTIONAL_VDF_PATH_ACK_BYTES);
    hex_bytes(canonical, s.canonical_config, sizeof s.canonical_config);
    hex_bytes(zebra, s.canonical_zebra8, sizeof s.canonical_zebra8);
    hex_bytes(layout, s.canonical_layout32, sizeof s.canonical_layout32);
    hex_bytes(display, s.canonical_display16, sizeof s.canonical_display16);
    hex_bytes(bb, s.canonical_bb32, sizeof s.canonical_bb32);
    hex_bytes(bit_width, s.canonical_bit_width8, sizeof s.canonical_bit_width8);
    hex_bytes(model_hex, s.model_result, s.model_result_bytes);
    snprintf(tag, sizeof tag, "FUNCTIONAL_VDF_PATH_%s ", event);
    snprintf(text, sizeof text,
        "pid=%d tid=%ld phase=%u cycle=%llu requests=%u completed_cycles=%u busy=%u guard=%u faults=%u "
        "source=%#x destination=%#x command=%#x bytes=%u original_fnv1a=%016llx "
        "refresh_queue_bound=%u refresh_queue_source=%#x "
        "model_instance=%llu config_generation=%llu before_config_generation=%llu frame_generation=%llu "
        "before_frame_generation=%llu lease_generation=%llu init_rc=%d bridge_rc=%d validation_rc=%d "
        "request_owned=%u request_retained=%p request_freed=%u ack_retained=%p queued=%u received=%u "
        "AP_consumed=%u send_inflight=%u releasing=%u sender_tid=%ld receiver_tid=%ld free_tid=%ld "
        "allocate_rc=%d allocation_returned=%p allocation_alias=%u request_free_rc=%d "
        "send_rc=%d free_rc=%d model_complete=%u functional_model=1 "
        "original_CP_FIFO_verified=0 physical_CP_RTOS_verified=0 original_selector_verified=0 "
        "physical_ASIC_verified=0 capture_verified=0 raw=%s ack_wire=%s canonical_config=%s "
        "canonical_zebra8=%s canonical_layout32=%s canonical_display16=%s canonical_bb32=%s canonical_bit_width8=%s model_result_bytes=%u realresultbytes=%u "
        "model_result_fnv1a64=%016llx model_result_hex=%s",
        s.owner_pid, tid(), s.phase, (unsigned long long)s.cycle, s.requests, s.completed_cycles,
        s.busy, s.guard_held, s.faults, s.origin.source, s.origin.destination, s.origin.command,
        s.origin.bytes, (unsigned long long)s.origin.wire_fnv1a64, s.refresh_queue_bound, s.refresh_queue_source,
        (unsigned long long)s.model_instance,
        (unsigned long long)s.config_generation, (unsigned long long)s.before_config_generation,
        (unsigned long long)s.frame_generation, (unsigned long long)s.before_frame_generation,
        (unsigned long long)s.lease_generation, s.init_rc, s.bridge_rc, s.validation_rc,
        s.request_owned, s.leases[0].pointer, s.leases[0].freed, s.leases[1].pointer,
        s.ack_queued, s.ack_received, s.ap_consumed, s.leases[1].send_inflight,
        s.leases[1].releasing, s.leases[1].sender_tid, s.leases[1].receiver_tid,
        s.leases[1].free_tid, s.leases[1].allocate_rc, s.allocation_returned, s.allocation_alias,
        s.leases[0].free_rc, s.leases[1].send_rc,
        s.leases[1].free_rc, s.model_complete, raw, ack, canonical, zebra, layout, display, bb, bit_width,
        s.model_result_bytes, s.model_result_bytes,
        (unsigned long long)fnv(s.model_result, s.model_result_bytes), model_hex);
    logger(tag, text);
}
/* The caller pins its lease with releasing before invoking any accessor. */
static int wire_valid(const struct full_imaging_io *io, void *p, unsigned int bytes,
                      unsigned int source, const unsigned char *wire) {
    return io->size(p) == bytes && io->source(p) == source && !memcmp(p, wire, bytes);
}
static int same_lease(unsigned int index, void *pointer, uint64_t cycle) {
    return state.cycle == cycle && state.leases[index].pointer == pointer && state.leases[index].releasing;
}
int functional_vdf_path_observe_receive_cycle(unsigned int destination, void *pointer,
    unsigned int source, unsigned int bytes, uint64_t *ticket) {
    if (inherited()) return -EXDEV;
    if (!pointer) return 0;
    pthread_mutex_lock(&mutex);
    struct native_cp_state_publication_lease *ack = &state.leases[1];
    if (pointer != ack->pointer) {
        pthread_mutex_unlock(&mutex); return 0;
    }
    const struct native_cp_state_publication_lease saved = *ack;
    const struct full_imaging_io io = transport;
    const uint64_t cycle = state.cycle;
    const unsigned char *ack_wire = ack_wire_for(state.origin.command);
    if (!ticket || !send_started || (!ack->queued && !ack->send_inflight) ||
        destination != ack->destination || source != ack->source || bytes != ack->bytes ||
        tid() != ack->sender_tid || ack->releasing || ack->received || state.faults) {
        fault(1); pthread_mutex_unlock(&mutex); return -EPROTO;
    }
    ack->releasing = 1; pthread_mutex_unlock(&mutex);
    const int valid = wire_valid(&io, pointer, saved.bytes, saved.source, ack_wire);
    pthread_mutex_lock(&mutex);
    if (!same_lease(1, pointer, cycle)) {
        fault(1); pthread_mutex_unlock(&mutex); return -ESTALE;
    }
    ack->releasing = 0;
    if (!valid || state.faults) { fault(1); pthread_mutex_unlock(&mutex); return -EPROTO; }
    ack->received = 1; ack->receiver_tid = tid(); *ticket = cycle;
    refresh(); pthread_mutex_unlock(&mutex); record(io.record, "RECEIVE"); return 1;
}
static int release_owned(unsigned int destination, void *pointer, uint64_t ticket,
    int (*real_free)(unsigned int, void *), void (*logger)(const char *, const char *),
    int *result, int internal) {
    if (!pointer || !result) return 0;
    if (inherited()) { *result = -EXDEV; return 1; }
    pthread_mutex_lock(&mutex);
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
    const uint64_t cycle = state.cycle;
    const struct full_imaging_io io = transport;
    unsigned char wire[FUNCTIONAL_VDF_MAX_REQUEST_BYTES];
    memcpy(wire, internal ? state.original_wire : ack_wire_for(state.origin.command), saved.bytes);
    lease->releasing = 1; pthread_mutex_unlock(&mutex);
    const int valid = wire_valid(&io, pointer, saved.bytes, saved.source, wire);
    const int rc = valid ? real_free(destination, pointer) : -EPROTO;
    pthread_mutex_lock(&mutex);
    if (!same_lease(index, pointer, cycle)) {
        fault(index); pthread_mutex_unlock(&mutex); *result = -ESTALE; return 1;
    }
    lease->releasing = 0; lease->free_rc = rc;
    if (rc) fault(index);
    else { lease->pointer = NULL; lease->freed = 1; lease->free_tid = tid(); }
    refresh(); pthread_mutex_unlock(&mutex);
    record(logger, internal ? "REQUEST_FREE" : "AP_FREE"); *result = rc; return 1;
}
int functional_vdf_path_release_cycle(unsigned int destination, void *pointer, uint64_t ticket,
    int (*real_free)(unsigned int, void *), void (*logger)(const char *, const char *), int *result) {
    return release_owned(destination, pointer, ticket, real_free, logger, result, 0);
}
static int result_shape(const unsigned char *p, const struct fcam_bridge_result *r, size_t bytes) {
    return r->used == bytes && r->required == bytes && !r->result_token && r->model_instance &&
        u32(p) == FCAM_ABI_VERSION;
}
static int init_model(const struct fcam_native_origin *origin) {
    pthread_mutex_lock(&mutex);
    if (state.init_attempted) {
        const int ready = state.model_initialized;
        const int rc = state.init_rc;
        pthread_mutex_unlock(&mutex); return ready ? 0 : rc ? rc : -EPROTO;
    }
    state.init_attempted = 1; pthread_mutex_unlock(&mutex);
    struct { unsigned char before[16], data[FCAM_STATE_BYTES], after[16]; } out;
    memset(&out, 0xa5, sizeof out); memset(out.data, 0, sizeof out.data);
    struct fcam_bridge_result r = {0};
    int rc = fcam_bridge_call(origin, FCAM_OP_INIT, NULL, 0, out.data, sizeof out.data, &r);
    if (rc > 0) rc = -EPROTO;
    for (size_t i = 0; i < sizeof out.before; i++)
        if (out.before[i] != 0xa5 || out.after[i] != 0xa5) rc = -EOVERFLOW;
    if (!rc && (!result_shape(out.data, &r, sizeof out.data) ||
        u32(out.data + FCAM_S_CAPS) != FCAM_CAPABILITIES ||
        u64(out.data + FCAM_S_INSTANCE) != r.model_instance || !u64(out.data + FCAM_S_GENERATION) ||
        u64(out.data + FCAM_S_CONSUMED) > u64(out.data + FCAM_S_RENDERED) ||
        u32(out.data + FCAM_S_PENDING_RESULTS) || u32(out.data + FCAM_S_STREAM_STATE) || u64(out.data + 120))) rc = -EPROTO;
    pthread_mutex_lock(&mutex);
    memcpy(state.init_state, out.data, sizeof out.data); state.init_rc = rc;
    if (rc) fault(0);
    else {
        state.model_initialized = 1; state.model_instance = r.model_instance;
        state.config_generation = u64(out.data + FCAM_S_GENERATION);
        state.frame_generation = u64(out.data + FCAM_S_FRAME_GENERATION);
    }
    pthread_mutex_unlock(&mutex); return rc;
}
static int validate_path(const unsigned char *p, const struct fcam_bridge_result *r,
    const struct functional_vdf_path_snapshot *before) {
    unsigned char canonical[FCAM_VDF_INPUT_BYTES];
    const int zebra = before->origin.command == 0x0153;
    const int layout = before->origin.command == 0x014c;
    const int display = before->origin.command == 0x0141 || before->origin.command == 0x0152 || before->origin.command == 0x0162;
    const int bit_width = before->origin.command == 0x015e;
    const int bb = bb_body_bytes(before->origin.command) != 0;
    const size_t result_bytes = bit_width ? FCAM_BIT_WIDTH_RESULT_BYTES : bb ? FCAM_BB_RESULT_BYTES : display ? FCAM_DISPLAY_RESULT_BYTES :
        layout ? FCAM_LAYOUT_RESULT_BYTES : zebra ? FCAM_ZEBRA_RESULT_BYTES : FCAM_VDF_RESULT_BYTES;
    const unsigned char *input = before->canonical_config;
    size_t input_bytes = FCAM_VDF_INPUT_BYTES;
    if (bit_width) {
        const unsigned char saved_width[FCAM_BIT_WIDTH_INPUT_BYTES] = {0};
        if (before->original_wire[8] || before->original_wire[9] ||
            memcmp(before->canonical_bit_width8, saved_width, sizeof saved_width) ||
            memcmp(p + FCAM_BIT_WIDTH_R_CONFIG, saved_width, sizeof saved_width)) return -EPROTO;
        memcpy(canonical, before->canonical_config, sizeof canonical);
        input = before->canonical_bit_width8; input_bytes = FCAM_BIT_WIDTH_INPUT_BYTES;
    } else if (bb) {
        unsigned char saved_bb[FCAM_BB_INPUT_BYTES];
        bb_input(saved_bb, before->origin.command, before->original_wire + 8);
        if (!bb_body_valid(before->origin.command, before->original_wire + 8) ||
            memcmp(saved_bb, before->canonical_bb32, sizeof saved_bb) ||
            memcmp(p + FCAM_BB_R_CONFIG, saved_bb, sizeof saved_bb)) return -EPROTO;
        memcpy(canonical, before->canonical_config, sizeof canonical);
        input = before->canonical_bb32; input_bytes = FCAM_BB_INPUT_BYTES;
    } else if (display) {
        unsigned char saved_display[FCAM_DISPLAY_INPUT_BYTES];
        display_input(saved_display, before->origin.command, before->original_wire + 8);
        if (!display_body_valid(before->origin.command, before->original_wire + 8) ||
            memcmp(saved_display, before->canonical_display16, sizeof saved_display) ||
            memcmp(p + FCAM_DISPLAY_R_CONFIG, saved_display, sizeof saved_display)) return -EPROTO;
        memcpy(canonical, before->canonical_config, sizeof canonical);
        input = before->canonical_display16; input_bytes = FCAM_DISPLAY_INPUT_BYTES;
    } else if (layout) {
        if (memcmp(before->original_wire + 8, initial_layout32, FCAM_LAYOUT_INPUT_BYTES) ||
            memcmp(before->canonical_layout32, initial_layout32, FCAM_LAYOUT_INPUT_BYTES) ||
            memcmp(p + FCAM_LAYOUT_R_CONFIG, before->canonical_layout32, FCAM_LAYOUT_INPUT_BYTES)) return -EPROTO;
        memcpy(canonical, before->canonical_config, sizeof canonical);
        input = before->canonical_layout32; input_bytes = FCAM_LAYOUT_INPUT_BYTES;
    } else if (zebra) {
        unsigned char saved_zebra[FCAM_ZEBRA_INPUT_BYTES] = {0};
        memcpy(saved_zebra, before->original_wire + 8, 5);
        if (memcmp(saved_zebra, before->canonical_zebra8, sizeof saved_zebra) || saved_zebra[1] ||
            memcmp(p + FCAM_ZEBRA_R_CONFIG, saved_zebra, sizeof saved_zebra)) return -EPROTO;
        memcpy(canonical, before->canonical_config, sizeof canonical);
        input = before->canonical_zebra8; input_bytes = FCAM_ZEBRA_INPUT_BYTES;
    } else {
        memcpy(canonical, before->original_wire + 8, sizeof canonical); memset(canonical + 13, 0, 3);
        if (memcmp(canonical, before->canonical_config, sizeof canonical)) return -EPROTO;
    }
    const unsigned int active = canonical[0];
    if (active > 1 || canonical[4] > 2 || canonical[13] || canonical[14] || canonical[15] ||
        (active ? canonical[1] != 5 || canonical[2] != 5 : canonical[1] != 1 || canonical[2] != 1)) return -EPROTO;
    const uint64_t config_before = u64(p + FCAM_VDF_R_BEFORE_CONFIG_GENERATION);
    const uint64_t frame_before = u64(p + FCAM_VDF_R_BEFORE_FRAME_GENERATION);
    const uint64_t generation = u64(p + FCAM_VDF_R_CONFIG_GENERATION);
    const uint64_t frame = u64(p + FCAM_VDF_R_FRAME_GENERATION);
    const uint64_t lease = u64(p + FCAM_VDF_R_LEASE_GENERATION);
    if (!result_shape(p, r, result_bytes) || u32(p + FCAM_VDF_R_BYTES) != result_bytes ||
        r->model_instance != before->model_instance || u64(p + FCAM_VDF_R_INSTANCE) != before->model_instance ||
        u64(p + FCAM_VDF_R_INPUT_FNV) != fnv(input, input_bytes) ||
        memcmp(p + FCAM_VDF_R_CONFIG, canonical, FCAM_VDF_INPUT_BYTES) ||
        u32(p + FCAM_VDF_R_ENDPOINT) != FCAM_VDF_ENDPOINT ||
        u32(p + FCAM_VDF_R_SELECTED_MASK) != FCAM_VDF_MASK ||
        u32(p + FCAM_VDF_R_COMPLETED_MASK) != FCAM_VDF_MASK ||
        u32(p + FCAM_VDF_R_CLASS) != (bit_width ? FCAM_BIT_WIDTH_CLASS : bb ? FCAM_BB_CLASS : active) || u32(p + FCAM_VDF_R_ENABLED) != active ||
        u32(p + FCAM_VDF_R_CONFIG_READBACK) != 1 || u32(p + FCAM_VDF_R_COMMITTED) != 1 ||
        u32(p + FCAM_VDF_R_STATUS) || u32(p + FCAM_VDF_R_RESERVED)) return -EPROTO;
    if (config_before < before->config_generation || frame_before < before->frame_generation ||
        config_before == UINT64_MAX || generation != config_before + 1) return -ESTALE;
    const uint32_t width = u32(p + FCAM_VDF_R_WIDTH), height = u32(p + FCAM_VDF_R_HEIGHT);
    if (!width || width > FCAM_MAX_STILL_WIDTH || !height || height > FCAM_MAX_STILL_HEIGHT ||
        u32(p + FCAM_VDF_R_STRIDE) != width * 3u) return -ERANGE;
    if (display && active != 1) return -ERANGE;
    if ((layout || bb || bit_width) && (active != 1 || width != 640 || height != 480)) return -ERANGE;
    if (active) {
        if (u32(p + FCAM_VDF_R_FRAME_CONSUMED) != 1 || u32(p + FCAM_VDF_R_RETIRED) != 1 ||
            u64(p + FCAM_VDF_R_ACTIVE_BYTES) != (uint64_t)width * height * 3u ||
            !u64(p + FCAM_VDF_R_SOURCE_FNV) ||
            u64(p + FCAM_VDF_R_SOURCE_FNV) != u64(p + FCAM_VDF_R_SINK_FNV) ||
            frame_before == UINT64_MAX || frame != frame_before + 1 || !lease ||
            (before->lease_generation && lease <= before->lease_generation)) return -EPROTO;
    } else if (u32(p + FCAM_VDF_R_FRAME_CONSUMED) || u32(p + FCAM_VDF_R_RETIRED) ||
        u64(p + FCAM_VDF_R_ACTIVE_BYTES) || u64(p + FCAM_VDF_R_SOURCE_FNV) ||
        u64(p + FCAM_VDF_R_SINK_FNV) || frame != frame_before || lease) return -EPROTO;
    return 0;
}
static int call_path(const struct fcam_native_origin *origin) {
    struct functional_vdf_path_snapshot before; functional_vdf_path_snapshot(&before);
    struct { unsigned char before[16], data[FCAM_VDF_RESULT_MAX_BYTES], after[16]; } out;
    const int zebra = origin->command == 0x0153;
    const int layout = origin->command == 0x014c;
    const int display = origin->command == 0x0141 || origin->command == 0x0152 || origin->command == 0x0162;
    const int bit_width = origin->command == 0x015e;
    const int bb = bb_body_bytes(origin->command) != 0;
    const size_t bytes = bit_width ? FCAM_BIT_WIDTH_RESULT_BYTES : bb ? FCAM_BB_RESULT_BYTES : display ? FCAM_DISPLAY_RESULT_BYTES :
        layout ? FCAM_LAYOUT_RESULT_BYTES : zebra ? FCAM_ZEBRA_RESULT_BYTES : FCAM_VDF_RESULT_BYTES;
    memset(&out, 0xa5, sizeof out); memset(out.data, 0, bytes);
    struct fcam_bridge_result r = {0};
    const int bridge_rc = bb ? fcam_bridge_bb_startup_config(origin, before.canonical_bb32, out.data, &r) :
        fcam_bridge_call(origin,
        bit_width ? FCAM_OP_VDF_BIT_WIDTH : display ? FCAM_OP_VDF_DISPLAY_CONFIG : layout ? FCAM_OP_VDF_LAYOUT : zebra ? FCAM_OP_VDF_ZEBRA : FCAM_OP_VDF_PATH,
        bit_width ? before.canonical_bit_width8 : display ? before.canonical_display16 : layout ? before.canonical_layout32 : zebra ? before.canonical_zebra8 : before.canonical_config,
        bit_width ? FCAM_BIT_WIDTH_INPUT_BYTES : display ? FCAM_DISPLAY_INPUT_BYTES : layout ? FCAM_LAYOUT_INPUT_BYTES : zebra ? FCAM_ZEBRA_INPUT_BYTES : FCAM_VDF_INPUT_BYTES,
        out.data, bytes, &r);
    int rc = bridge_rc > 0 ? -EPROTO : bridge_rc;
    for (size_t i = 0; i < sizeof out.before; i++)
        if (out.before[i] != 0xa5 || out.after[i] != 0xa5) rc = -EOVERFLOW;
    for (size_t i = bytes; i < sizeof out.data; i++)
        if (out.data[i] != 0xa5) rc = -EOVERFLOW;
    if (!rc) rc = validate_path(out.data, &r, &before);
    pthread_mutex_lock(&mutex);
    state.bridge_rc = bridge_rc; state.validation_rc = rc;
    state.model_result_bytes = (unsigned int)(r.used < bytes ? r.used : bytes);
    memcpy(state.model_result, out.data, state.model_result_bytes);
    if (rc) fault(0);
    else {
        state.model_complete = 1;
        state.config_generation = u64(out.data + FCAM_VDF_R_CONFIG_GENERATION);
        state.frame_generation = u64(out.data + FCAM_VDF_R_FRAME_GENERATION);
        state.lease_generation = u64(out.data + FCAM_VDF_R_LEASE_GENERATION);
        state.before_config_generation = u64(out.data + FCAM_VDF_R_BEFORE_CONFIG_GENERATION);
        state.before_frame_generation = u64(out.data + FCAM_VDF_R_BEFORE_FRAME_GENERATION);
        refresh();
    }
    pthread_mutex_unlock(&mutex); return rc;
}
static void finish(const struct native_cp_state_publication_guard *guard) {
    pthread_mutex_lock(&mutex); const unsigned int held = state.guard_held;
    state.guard_held = 0; pthread_mutex_unlock(&mutex);
    if (held) guard->release();
    pthread_mutex_lock(&mutex); state.busy = 0; refresh(); pthread_mutex_unlock(&mutex);
}
static int allocate_ack(const struct full_imaging_io *io) {
    const unsigned char *ack_wire = ack_wire_for(state.origin.command);
    const size_t bytes = FUNCTIONAL_VDF_PATH_ACK_BYTES;
    void *p = NULL; const int rc = io->allocate(state.origin.source, &p, bytes, 1);
    const int alias = p && span(p, bytes) &&
        ((state.leases[0].pointer && overlap(p, bytes, state.leases[0].pointer, state.leases[0].bytes)) ||
         overlap(p, bytes, &state, sizeof state) || overlap(p, bytes, path_ack, sizeof path_ack) ||
         overlap(p, bytes, zebra_ack, sizeof zebra_ack) || overlap(p, bytes, layout_ack, sizeof layout_ack) ||
         overlap(p, bytes, bit_width_ack, sizeof bit_width_ack) ||
         overlap(p, bytes, peaking_ack, sizeof peaking_ack) || overlap(p, bytes, flag_ack, sizeof flag_ack) ||
         overlap(p, bytes, refresh_ack, sizeof refresh_ack) || overlap(p, bytes, bb_ack, sizeof bb_ack) ||
         overlap(p, bytes, peaking_palettes, sizeof peaking_palettes) ||
         overlap(p, bytes, initial_layout32, sizeof initial_layout32));
    int valid = !rc && span(p, bytes) && !alias;
    pthread_mutex_lock(&mutex);
    struct native_cp_state_publication_lease *ack = &state.leases[1];
    ack->allocate_rc = rc; state.allocation_returned = p; state.allocation_alias = (unsigned int)alias;
    if (p && !alias) { ack->pointer = p; ack_address = p; }
    ack->releasing = (unsigned int)valid;
    if (!valid) fault(1);
    pthread_mutex_unlock(&mutex);
    if (valid) {
        valid = io->size(p) == bytes;
        if (valid) {
            memcpy(p, ack_wire, bytes); io->set_source(p, FUNCTIONAL_VDF_PATH_SID);
            valid = wire_valid(io, p, bytes, FUNCTIONAL_VDF_PATH_SID, ack_wire);
        }
        pthread_mutex_lock(&mutex); ack->releasing = 0; if (!valid) fault(1); pthread_mutex_unlock(&mutex);
    }
    return valid ? 0 : rc ? rc : -EPROTO;
}
static int send_ack(const struct full_imaging_io *io) {
    pthread_mutex_lock(&mutex);
    struct native_cp_state_publication_lease *ack = &state.leases[1];
    const struct native_cp_state_publication_lease saved = *ack;
    const uint64_t cycle = state.cycle;
    const unsigned char *ack_wire = ack_wire_for(state.origin.command);
    if (!ack->pointer || ack->releasing || state.faults || !state.leases[0].freed) {
        fault(1); pthread_mutex_unlock(&mutex); return -EPROTO;
    }
    ack->releasing = 1; pthread_mutex_unlock(&mutex);
    int valid = wire_valid(io, saved.pointer, saved.bytes, saved.source, ack_wire);
    pthread_mutex_lock(&mutex);
    valid = valid && same_lease(1, saved.pointer, cycle) && !state.faults;
    ack->releasing = 0;
    if (valid) { send_started = 1; ack->send_inflight = 1; }
    else fault(1);
    pthread_mutex_unlock(&mutex); if (!valid) return -EPROTO;
    const int rc = io->send(saved.destination, saved.pointer);
    /* Inline rcv/free may already have destroyed the envelope. Do not touch it. */
    pthread_mutex_lock(&mutex);
    if (state.cycle != cycle || !ack->send_inflight || (ack->pointer != saved.pointer && !ack->freed)) {
        fault(1); pthread_mutex_unlock(&mutex); return -ESTALE;
    }
    ack->send_inflight = 0; ack->send_rc = rc;
    if (rc) fault(1); else ack->queued = 1;
    refresh(); pthread_mutex_unlock(&mutex); record(io->record, "SEND"); return rc;
}
static int dispatch(unsigned int destination, void *request, const struct full_imaging_io *io,
    const struct native_cp_state_publication_guard *guard, int *result) {
    const unsigned int bytes = io->size(request);
    if (bytes < 4 || !span(request, bytes)) return 0;
    const unsigned char *p = request;
    if (p[0] != 0x0d || p[1] != 0x20 || p[3] != 1 ||
        (p[2] != 0x38 && p[2] != 0x53 && p[2] != 0x4c && p[2] != 0x52 && p[2] != 0x62 && p[2] != 0x41 && p[2] != 0x5e &&
         !bb_body_bytes(0x0100u | p[2]))) return 0;
    const unsigned int command = 0x0100u | p[2];
    const int zebra = command == 0x0153, layout = command == 0x014c;
    const int display = command == 0x0141 || command == 0x0152 || command == 0x0162;
    const int bit_width = command == 0x015e;
    const unsigned int bb_bytes = bb_body_bytes(command);
    const unsigned int expected_bytes = bit_width ? FUNCTIONAL_VDF_BIT_WIDTH_REQUEST_BYTES : bb_bytes ? bb_bytes + 8u : command == 0x0141 ? FUNCTIONAL_VDF_REFRESH_REQUEST_BYTES :
        command == 0x0152 ? FUNCTIONAL_VDF_PEAKING_REQUEST_BYTES :
        command == 0x0162 ? FUNCTIONAL_VDF_FLAG_REQUEST_BYTES : layout ? FUNCTIONAL_VDF_LAYOUT_REQUEST_BYTES :
        zebra ? FUNCTIONAL_VDF_ZEBRA_REQUEST_BYTES : FUNCTIONAL_VDF_PATH_REQUEST_BYTES;
    *result = bit_width ? -ENOTSUP : FUNCTIONAL_VDF_PATH_BLOCKED;
    if (bytes != expected_bytes || p[4] != expected_bytes || p[5] || p[6] != 1 || p[7] != 0x80 ||
        !io->source || !io->allocate || !io->release || !io->send || !io->set_source ||
        !guard || !guard->reserve || !guard->release || !guard->predecessor_ready) return 1;
    if (bit_width ? p[8] || p[9] : bb_bytes ? !bb_body_valid(command, p + 8) : display ? !display_body_valid(command, p + 8) :
        layout ? memcmp(p + 8, initial_layout32, FCAM_LAYOUT_INPUT_BYTES) != 0 : zebra ? p[9] != 0 :
        !((p[8] == 1 && p[9] == 5 && p[10] == 5) || (p[8] == 0 && p[9] == 1 && p[10] == 1)) || p[12] > 2) {
        *result = bit_width ? -ENOTSUP : -EINVAL; return 1;
    }
    const unsigned int caller = io->source(request);
    if (command != 0x0141 && (caller & UINT32_C(0xffff0000)) != UINT32_C(0x81cf0000)) return 1;
    unsigned char saved[FUNCTIONAL_VDF_MAX_REQUEST_BYTES] = {0}; memcpy(saved, request, bytes);
    pthread_mutex_lock(&mutex);
    if (!state.initialized || state.faults || (command == 0x0141 &&
        (!state.refresh_queue_bound || !caller || caller != state.refresh_queue_source))) {
        pthread_mutex_unlock(&mutex); return 1;
    }
    if (state.busy || (state.requests && !state.ap_consumed)) {
        pthread_mutex_unlock(&mutex); *result = -EBUSY; return 1;
    }
    if ((layout || display || bb_bytes || bit_width) && (state.canonical_config[0] != 1 || !state.model_complete)) {
        pthread_mutex_unlock(&mutex); return 1;
    }
    if (state.cycle == UINT64_MAX || state.requests == UINT_MAX || state.completed_cycles == UINT_MAX) {
        pthread_mutex_unlock(&mutex); *result = -EOVERFLOW; return 1;
    }
    state.busy = 1; pthread_mutex_unlock(&mutex);
    int rc = guard->reserve();
    if (rc) { finish(guard); *result = rc < 0 ? rc : -EPROTO; return 1; }
    pthread_mutex_lock(&mutex); state.guard_held = 1; pthread_mutex_unlock(&mutex);
    if (guard->predecessor_ready() != 1) { finish(guard); return 1; }
    const struct fcam_native_origin origin = {caller, destination, command, bytes, fnv(saved, bytes)};
    const unsigned char *ack_wire = ack_wire_for(origin.command);
    pthread_mutex_lock(&mutex);
    state.cycle++; state.origin = origin; state.phase = FUNCTIONAL_VDF_PATH_PROBING;
    state.ap_consumed = state.model_complete = state.ack_queued = state.ack_received = state.request_owned = 0;
    memset(state.leases, 0, sizeof state.leases); send_started = 0;
    state.allocation_returned = NULL; state.allocation_alias = 0;
    memcpy(state.original_wire, saved, sizeof saved);
    if (bit_width) {
        memset(state.canonical_bit_width8, 0, sizeof state.canonical_bit_width8);
    } else if (bb_bytes) {
        bb_input(state.canonical_bb32, command, saved + 8);
    } else if (display) {
        display_input(state.canonical_display16, command, saved + 8);
    } else if (layout) {
        memcpy(state.canonical_layout32, saved + 8, sizeof state.canonical_layout32);
    } else if (zebra) {
        memset(state.canonical_zebra8, 0, sizeof state.canonical_zebra8);
        memcpy(state.canonical_zebra8, saved + 8, 5);
    } else {
        memcpy(state.canonical_config, saved + 8, FCAM_VDF_INPUT_BYTES);
        memset(state.canonical_config + 13, 0, 3);
    }
    memset(state.model_result, 0, sizeof state.model_result); state.model_result_bytes = 0;
    transport = *io;
    pthread_mutex_unlock(&mutex);
    rc = init_model(&origin);
    if (!rc) rc = call_path(&origin);
    if (!rc && (guard->predecessor_ready() != 1 || !wire_valid(io, request, bytes, caller, saved))) {
        rc = -ESTALE; pthread_mutex_lock(&mutex); state.validation_rc = rc; fault(0); pthread_mutex_unlock(&mutex);
    }
    if (rc) { finish(guard); record(io->record, "REFUSED"); *result = rc; return 1; }
    pthread_mutex_lock(&mutex);
    state.requests++; state.request_owned = 1;
    state.leases[0] = (struct native_cp_state_publication_lease){.role = 1, .bytes = bytes,
        .destination = destination, .source = caller, .pointer = request, .sender_tid = tid(),
        .wire_fnv1a64 = origin.wire_fnv1a64};
    state.leases[1] = (struct native_cp_state_publication_lease){.role = 2, .bytes = FUNCTIONAL_VDF_PATH_ACK_BYTES,
        .destination = caller, .source = FUNCTIONAL_VDF_PATH_SID, .sender_tid = tid(),
        .wire_fnv1a64 = fnv(ack_wire, FUNCTIONAL_VDF_PATH_ACK_BYTES)};
    pthread_mutex_unlock(&mutex);
    if (layout || display || bb_bytes || bit_width) {
        int free_rc = -EPROTO;
        release_owned(destination, request, 0, io->release, io->record, &free_rc, 1); rc = free_rc;
        if (!rc) rc = allocate_ack(io);
    } else {
        rc = allocate_ack(io);
        if (!rc) {
            int free_rc = -EPROTO;
            release_owned(destination, request, 0, io->release, io->record, &free_rc, 1); rc = free_rc;
        }
    }
    if (!rc) rc = send_ack(io);
    finish(guard); record(io->record, rc ? "FAULT" : "COMPLETE"); *result = 0; return 1;
}
int functional_vdf_path_dispatch(unsigned int destination, void *request, const struct full_imaging_io *io,
    const struct native_cp_state_publication_guard *guard, int enabled, int *result) {
    if (enabled != 1 || destination != FUNCTIONAL_VDF_PATH_SID || !request || !io || !io->size || !result) return 0;
    if (inherited()) { *result = -EXDEV; return 1; }
    if (dispatching) { *result = -EBUSY; return 1; }
    dispatching = 1; int handled = dispatch(destination, request, io, guard, result); dispatching = 0; return handled;
}
#ifdef HOST_TEST
void functional_vdf_path_test_hold_lock(void) { pthread_mutex_lock(&mutex); }
void functional_vdf_path_test_drop_lock(void) { pthread_mutex_unlock(&mutex); }
void *functional_vdf_path_test_snapshot_address(void) { return &state; }
const void *functional_vdf_path_test_constant_address(unsigned int index) {
    return index == 1 ? initial_layout32 : index == 2 ? &peaking_palettes[0][0] : ack_wire_for(state.origin.command);
}
#endif
