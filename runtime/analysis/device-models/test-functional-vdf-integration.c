/* SPDX-License-Identifier: MIT */
#ifndef HOST_TEST
#error Component-only real-core/real-owner fixture; never an original AP or VM.
#endif
#define _GNU_SOURCE
#include "functional-vdf-path.h"
#include "functional-histogram.h"
#include "functional-vdf-layout-stage.h"
#include "../../../report/functional-camera-core/functional-camera-core.h"
#include "../../../report/virtual-optical-frame-owner/optical-frame-owner.h"
#include <assert.h>
#include <math.h>
#include <pthread.h>
#include <stddef.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/syscall.h>
#include <unistd.h>

struct message { void *next; unsigned int flags, source, size, reserved; unsigned char body[]; };
_Static_assert(offsetof(struct message, body) == 24, "OSAL public envelope");
_Static_assert(sizeof(struct fcam_frame_proof) == 376, "real proof ABI");
static const uint64_t instance = UINT64_C(0x9a1701);
static const unsigned char ack_wire[11][12] = {
    {0x0d, 0x20, 0x38, 0x11, 12, 0, 1, 0x80, 0, 0, 0x59, 0},
    {0x0d, 0x20, 0x53, 0x11, 12, 0, 1, 0x80, 0, 0, 0, 0},
    {0x0d, 0x20, 0x4c, 0x11, 12, 0, 1, 0x80, 0, 0, 0x59, 0},
    {0x0d, 0x20, 0x52, 0x11, 12, 0, 1, 0x80, 0, 0, 0x59, 0},
    {0x0d, 0x20, 0x62, 0x11, 12, 0, 1, 0x80, 0, 0, 0x59, 0},
    {0x0d, 0x20, 0x41, 0x11, 12, 0, 1, 0x80, 0, 0, 0x59, 0},
    {0x0d, 0x20, 0x11, 0x11, 12, 0, 1, 0x80, 0, 0, 0, 0},
    {0x0d, 0x20, 0x66, 0x11, 12, 0, 1, 0x80, 0, 0, 0, 0},
    {0x0d, 0x20, 0x67, 0x11, 12, 0, 1, 0x80, 0, 0, 0, 0},
    {0x0d, 0x20, 0x5f, 0x11, 12, 0, 1, 0x80, 0, 0, 0, 0},
    {0x0d, 0x20, 0x28, 0x11, 12, 0, 1, 0x80, 0, 0, 0, 0}
};
/* Explicit virtual x,y,w,h=0,0,640,480; zero output means full RGB pass-through. */
static const unsigned char layout_wire[40] = {
    0x0d, 0x20, 0x4c, 1, 40, 0, 1, 0x80,
    7, 1, 1, 0, 0, 0, 0, 0, 0x80, 2, 0xe0, 1,
    0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 3, 0, 0, 0, 0, 0, 0, 0
};
_Static_assert(FCAM_OP_VDF_LAYOUT == 7 && FCAM_LAYOUT_INPUT_BYTES == 32 &&
    FCAM_LAYOUT_RESULT_BYTES == 192 && FCAM_LAYOUT_R_CONFIG == 160 &&
    FCAM_VDF_RESULT_MAX_BYTES == 192 && FUNCTIONAL_VDF_LAYOUT_REQUEST_BYTES == 40 &&
    FUNCTIONAL_VDF_MAX_REQUEST_BYTES == 40, "layout component contract");
_Static_assert(FCAM_OP_VDF_DISPLAY_CONFIG == 8 && FCAM_DISPLAY_INPUT_BYTES == 16 &&
    FCAM_DISPLAY_RESULT_BYTES == 176 && FCAM_DISPLAY_R_CONFIG == 160 && FCAM_PROOF_VDF == 4 &&
    FUNCTIONAL_VDF_PEAKING_REQUEST_BYTES == 16 && FUNCTIONAL_VDF_FLAG_REQUEST_BYTES == 10,
    "typed display component contract");
_Static_assert(FCAM_OP_BB_STARTUP_CONFIG == 9 && FCAM_BB_INPUT_BYTES == 32 &&
    FCAM_BB_RESULT_BYTES == 192 && FCAM_BB_CLASS == 5 && FCAM_PROOF_BB_STARTUP == 5 &&
    FCAM_OP_HISTOGRAM == 10 && FCAM_HIST_INPUT_BYTES == 8 && FCAM_HIST_RESULT_BYTES == 1192 &&
    FCAM_HIST_R_CONFIG == 160 && FCAM_HIST_R_BINS == 168 && FCAM_PROOF_HISTOGRAM == 6,
    "BB and histogram component contract");
static const unsigned int bb_commands[5] = {0x0111, 0x0166, 0x0167, 0x015f, 0x0128};
static const unsigned int bb_request_bytes[5] = {36, 36, 10, 12, 20};
static const unsigned char bb_requests[5][36] = {
    {0x0d,0x20,0x11,1,36,0,1,0x80,0,0,15,2},
    {0x0d,0x20,0x66,1,36,0,1,0x80,0,1},
    {0x0d,0x20,0x67,1,10,0,1,0x80,1,0},
    {0x0d,0x20,0x5f,1,12,0,1,0x80,0,0,0,0},
    {0x0d,0x20,0x28,1,20,0,1,0x80,0,1,0,0,60,0,0,0,0,0,0,0}
};
static const unsigned char bb_inputs[5][32] = {
    {0x11,1,28,0,0,0,15,2}, {0x66,1,28,0,0,1}, {0x67,1,2,0,1,0},
    {0x5f,1,4,0,0,0,0,0}, {0x28,1,12,0,0,1,0,0,60,0,0,0,0,0,0,0}
};
static const unsigned char hist_request_wire[12] = {0x0d,0x20,0x48,1,12,0,1,0x80,1,1,0,0};
static const unsigned char hist_ack_wire[12] = {0x0d,0x20,0x48,0x11,12,0,1,0x80,0,0,0x59,0};
static const unsigned char hist_input[8] = {0x48,1,4,0,1,1,0,0};
static const unsigned char hist_header[10] = {0x0d,0x20,0x0c,0x21,0x0a,4,1,0x80,1,0};
static unsigned int bb, bb_variant, bb_observed_initial;
static unsigned char canonical_bb[FCAM_BB_INPUT_BYTES];
static struct {
    void *pointer[3], *queued[3];
    uintptr_t address[3];
    unsigned int source, allocations, sends, free_calls[3], freed[3], calls, reuse, arena_live;
    unsigned int fail_free, no_notification_free;
    uint64_t tickets[3];
    unsigned char result[FCAM_HIST_RESULT_BYTES], notification[FUNCTIONAL_HISTOGRAM_NOTIFICATION_BYTES];
    unsigned char expected_bins[FCAM_HIST_BINS_BYTES];
    struct fcam_bridge_result metadata;
    struct fcam_frame_proof core_proof;
    union { max_align_t alignment; unsigned char storage[24 + 12]; } arena;
} hist;
static struct fcam_model *model;
static void *original, *allocated_ack, *queued_ack, *received_ack;
static struct message *recycled_ack;
static union { max_align_t alignment; unsigned char storage[24 + FUNCTIONAL_VDF_MAX_REQUEST_BYTES]; } arena;
static unsigned int arena_live, arena_allocations, arena_frees, retired_request_reuses;
static int fresh_request_lease;
static unsigned char original_wire[FUNCTIONAL_VDF_MAX_REQUEST_BYTES], canonical[16], canonical_zebra[8];
static unsigned char canonical_layout[FCAM_LAYOUT_INPUT_BYTES], authentic_result[FCAM_VDF_RESULT_MAX_BYTES];
static unsigned char canonical_display[FCAM_DISPLAY_INPUT_BYTES], previous_display[FCAM_DISPLAY_INPUT_BYTES];
static const unsigned char palettes[4][3] = {{81, 90, 240}, {210, 16, 146}, {29, 255, 83}, {235, 128, 128}};
static unsigned int caller, stage, held, init_calls, path_calls, allocations, sends, request_frees, ack_frees;
static unsigned int request_bytes, result_bytes, corrupt_tail;
static uint64_t previous_ticket;
static uintptr_t request_address, previous_ack_address;
static int corrupt_result, zebra, layout, display, reuse_ack, expected_core_rc;
static unsigned int palette = 3, level = 1, magnification;
static struct fcam_bridge_result authentic_metadata;
static int early_stage_case;
static const unsigned int early_caller = UINT32_C(0x81cf0012);
static struct {
    void *request, *ack, *queued, *received;
    unsigned int allocations, sends, request_frees, ack_frees, phase;
    uint64_t ticket;
} early;

static uint32_t u32(const unsigned char *p) {
    return p[0] | (uint32_t)p[1] << 8 | (uint32_t)p[2] << 16 | (uint32_t)p[3] << 24;
}
static uint64_t u64(const unsigned char *p) { return u32(p) | (uint64_t)u32(p + 4) << 32; }
static void put32(unsigned char *p, uint32_t v) {
    for (unsigned int i = 0; i < 4; i++) p[i] = (unsigned char)(v >> (i * 8));
}
static void put64(unsigned char *p, uint64_t v) {
    put32(p, (uint32_t)v); put32(p + 4, (uint32_t)(v >> 32));
}
static uint64_t fnv(const void *pointer, size_t bytes) {
    const unsigned char *p = pointer; uint64_t h = UINT64_C(14695981039346656037);
    for (size_t i = 0; i < bytes; i++) h = (h ^ p[i]) * UINT64_C(1099511628211);
    return h;
}
static struct message *envelope(void *p) {
    return (struct message *)((unsigned char *)p - offsetof(struct message, body));
}
static void *message(unsigned int bytes, unsigned int source) {
    struct message *m;
    if (fresh_request_lease && (layout || display || bb)) {
        assert(!arena_live && arena_allocations == arena_frees);
        m = (struct message *)arena.storage; arena_live = 1; arena_allocations++;
        memset(m, 0, sizeof *m + bytes);
    } else if (reuse_ack && bytes == 12 && !source && recycled_ack) {
        m = recycled_ack; recycled_ack = NULL; memset(m, 0, sizeof *m + bytes);
    } else { m = malloc(sizeof *m + bytes); assert(m); memset(m, 0, sizeof *m + bytes); }
    assert(m);
    m->source = source; m->size = bytes; return m->body;
}
static unsigned int size(void *p) { return envelope(p)->size; }
static unsigned int source(void *p) { return envelope(p)->source; }
static void set_source(void *p, unsigned int src) { envelope(p)->source = src; }
static struct functional_vdf_path_snapshot owner(void) {
    struct functional_vdf_path_snapshot s; functional_vdf_path_snapshot(&s);
    assert(s.initialized && s.owner_pid == getpid() && s.functional_model);
    assert(!s.capture_verified && !s.physical_asic_verified && !s.physical_cp_rtos_verified &&
        !s.original_cp_fifo_verified && !s.original_selector_verified);
    return s;
}
static struct fcam_frame_proof proof(void) {
    struct fcam_frame_proof p;
    assert(!fcam_model_proof_snapshot(model, &p, sizeof p));
    assert(p.version == FCAM_PROOF_VERSION && p.struct_bytes == sizeof p &&
        p.model_instance == instance && p.owner_pid == (uint64_t)getpid());
    return p;
}
static void state_request(uint32_t op, const unsigned char *input, size_t bytes, unsigned char out[128]) {
    struct fcam_exec_result r = {0};
    assert(!fcam_model_request(model, op, input, bytes, out, 128, &r));
    assert(r.used == 128 && !r.token && !r.total && !r.offset);
}
static void repeated_init(void) {
    unsigned char before[128], after[128]; state_request(FCAM_OP_STATE, NULL, 0, before);
    const struct fcam_frame_proof first = proof();
    /* Empty INIT is the core operation used by a later CP3003; no CP transport is claimed. */
    state_request(FCAM_OP_INIT, NULL, 0, after);
    const struct fcam_frame_proof last = proof();
    assert(!memcmp(before, after, sizeof before) && !memcmp(&first, &last, sizeof first));
}
static void configure(unsigned int width, unsigned int height) {
    unsigned char config[48] = {0}, before[128], after[128];
    state_request(FCAM_OP_STATE, NULL, 0, before);
    put32(config, width); put32(config + 4, height); put32(config + 8, 25); put32(config + 12, 90);
    put32(config + 16, 400); put32(config + 20, 100); put64(config + 24, 2500); put64(config + 32, 1000000);
    state_request(FCAM_OP_CONFIGURE, config, sizeof config, after);
    assert(u64(after + FCAM_S_GENERATION) == u64(before + FCAM_S_GENERATION) + 1);
    assert(!memcmp(before + FCAM_S_RENDERED, after + FCAM_S_RENDERED, 64));
}
static unsigned int ack_index(void) { return bb ? 5u + bb : display ? 2u + (unsigned int)display : layout ? 2u : (unsigned int)zebra; }
static int allocate(unsigned int destination, void **out, unsigned int bytes, unsigned int option) {
    assert(!allocated_ack && destination == caller && bytes == 12 && option == 1);
    assert(layout || display || bb ? !original && stage == 1 : original && !stage);
    const struct functional_vdf_path_snapshot s = owner();
    assert(!s.leases[1].pointer && allocations == ack_frees);
    if (layout || display || bb) assert(s.leases[0].freed && !s.leases[0].pointer && !s.leases[0].free_rc && request_frees == allocations + 1);
    else assert(s.leases[0].pointer == original && !s.leases[0].freed && request_frees == allocations);
    *out = allocated_ack = message(bytes, 0); allocations++;
    const uintptr_t a = request_address, b = (uintptr_t)*out;
    if (!layout && !display && !bb) assert(a + request_bytes <= b || b + bytes <= a);
    else if (a == b) {
        assert(size(*out) == 12 && !source(*out) && s.leases[0].freed && !s.leases[0].pointer);
        retired_request_reuses++;
    }
    if (fresh_request_lease && (layout || display || bb)) assert(a == b && arena_allocations == arena_frees + 1);
    if (reuse_ack && previous_ack_address) assert(b == previous_ack_address);
    return 0;
}
static int release(unsigned int destination, void *p) {
    const struct functional_vdf_path_snapshot s = owner();
    assert(s.model_complete && !s.ap_consumed);
    if (p == original) {
        assert(!stage && destination == FUNCTIONAL_VDF_PATH_SID && source(p) == caller && size(p) == request_bytes);
        assert(!memcmp(p, original_wire, request_bytes));
        assert(layout || display || bb ? !allocated_ack : allocated_ack != NULL);
        original = NULL; request_frees++; stage = 1;
    } else {
        assert(p == allocated_ack && p == received_ack && stage == 3 && destination == caller);
        assert(source(p) == FUNCTIONAL_VDF_PATH_SID && size(p) == 12 &&
            !memcmp(p, ack_wire[ack_index()], sizeof ack_wire[0]));
        assert(s.ack_received && s.leases[1].releasing && !s.leases[1].freed);
        assert(s.leases[0].freed && !s.leases[0].pointer && request_frees == ack_frees + 1);
        assert(s.leases[1].sender_tid == s.leases[1].receiver_tid);
        previous_ack_address = (uintptr_t)p;
        allocated_ack = received_ack = NULL; ack_frees++; stage = 4;
        if (reuse_ack) { assert(!recycled_ack); recycled_ack = envelope(p); return 0; }
    }
    if (p == ((struct message *)arena.storage)->body) {
        assert(arena_live && arena_allocations == arena_frees + 1);
        arena_live = 0; arena_frees++; return 0;
    }
    free(envelope(p)); return 0;
}
static int send(unsigned int destination, void *p) {
    const struct functional_vdf_path_snapshot s = owner();
    assert(stage == 1 && !original && p == allocated_ack && !queued_ack && destination == caller);
    assert(source(p) == FUNCTIONAL_VDF_PATH_SID && size(p) == 12 &&
        !memcmp(p, ack_wire[ack_index()], sizeof ack_wire[0]));
    assert(s.leases[0].freed && s.leases[1].send_inflight && !s.ap_consumed);
    queued_ack = p; stage = 2; sends++; return 0;
}
static int reserve(void) { assert(!held); held = 1; return 0; }
static void unlock(void) { assert(held); held = 0; }
static int ready(void) { assert(held); return 1; }
static const struct full_imaging_io io = {allocate, release, set_source, send, size, source, NULL};
static const struct native_cp_state_publication_guard guard = {reserve, unlock, ready};

static struct functional_vdf_layout_stage_snapshot early_snapshot(void) {
    struct functional_vdf_layout_stage_snapshot s; functional_vdf_layout_stage_snapshot(&s);
    assert(s.initialized && s.owner_pid == getpid() && s.stage_only == 1);
    assert(!s.semantic_applied && !s.frame_consumed && !s.hardware_ready && !s.capture_verified &&
        !s.physical_asic_verified && !s.original_cp_fifo_verified && !s.physical_cp_rtos_verified);
    return s;
}
static int early_allocate(unsigned int destination, void **out, unsigned int bytes, unsigned int option) {
    const struct functional_vdf_layout_stage_snapshot s = early_snapshot();
    assert(destination == early_caller && bytes == 12 && option == 1 && early.request && !early.ack && !early.phase);
    assert(s.busy && s.bank_written && s.readback_verified && !s.applied.verified &&
        s.leases[0].pointer == early.request && !s.leases[0].freed && !s.leases[1].pointer);
    assert(early.allocations == early.ack_frees && !memcmp(s.bank32, layout_wire + 8, 32) &&
        !memcmp(s.copied_readback32, layout_wire + 8, 32) && s.bank_fnv1a64 == fnv(layout_wire + 8, 32));
    *out = early.ack = message(bytes, 0); early.allocations++;
    const uintptr_t a = (uintptr_t)early.request, b = (uintptr_t)*out;
    assert(a + 40 <= b || b + bytes <= a);
    return 0;
}
static int early_release(unsigned int destination, void *p) {
    const struct functional_vdf_layout_stage_snapshot s = early_snapshot();
    assert(!s.ap_consumed && !s.applied.verified);
    if (p == early.request) {
        assert(destination == FUNCTIONAL_LAYOUT_STAGE_SID && !early.phase && early.ack &&
            source(p) == early_caller && size(p) == 40 && !memcmp(p, layout_wire, 40));
        assert(s.leases[0].releasing && !s.leases[0].freed && !s.ack_queued);
        early.request = NULL; early.request_frees++; early.phase = 1;
    } else {
        assert(destination == early_caller && p == early.ack && p == early.received && early.phase == 3 &&
            source(p) == FUNCTIONAL_LAYOUT_STAGE_SID && size(p) == 12 && !memcmp(p, ack_wire[2], 12));
        assert(s.ack_received && s.leases[0].freed && !s.leases[0].pointer &&
            s.leases[1].releasing && !s.leases[1].freed &&
            s.leases[1].sender_tid == s.leases[1].receiver_tid);
        early.ack = early.received = NULL; early.ack_frees++; early.phase = 4;
    }
    free(envelope(p)); return 0;
}
static int early_send(unsigned int destination, void *p) {
    const struct functional_vdf_layout_stage_snapshot s = early_snapshot();
    assert(destination == early_caller && early.phase == 1 && !early.request && p == early.ack && !early.queued);
    assert(source(p) == FUNCTIONAL_LAYOUT_STAGE_SID && size(p) == 12 && !memcmp(p, ack_wire[2], 12));
    assert(s.leases[0].freed && !s.leases[0].pointer && s.leases[1].send_inflight && !s.ap_consumed);
    early.queued = p; early.sends++; early.phase = 2; return 0;
}
static const struct full_imaging_io stage_io = {early_allocate, early_release, set_source, early_send, size, source, NULL};

static uint32_t opcode(void) {
    return bb ? FCAM_OP_BB_STARTUP_CONFIG : display ? FCAM_OP_VDF_DISPLAY_CONFIG : layout ? FCAM_OP_VDF_LAYOUT : zebra ? FCAM_OP_VDF_ZEBRA : FCAM_OP_VDF_PATH;
}
static unsigned int command(void) { return bb ? bb_commands[bb - 1] : display ? display == 1 ? 0x0152 : display == 2 ? 0x0162 : 0x0141 : layout ? 0x014c : zebra ? 0x0153 : 0x0138; }
static const unsigned char *operation_input(void) {
    return bb ? canonical_bb : display ? canonical_display : layout ? canonical_layout : zebra ? canonical_zebra : canonical;
}
static size_t operation_input_bytes(void) {
    return bb ? sizeof canonical_bb : display ? sizeof canonical_display : layout ? sizeof canonical_layout : zebra ? sizeof canonical_zebra : sizeof canonical;
}
static size_t corruption_offset(void) {
    if (corrupt_result == 9) return FCAM_VDF_R_CLASS;
    if (corrupt_result == 2) return (display ? FCAM_DISPLAY_R_CONFIG : FCAM_LAYOUT_R_CONFIG) + corrupt_tail;
    if (corrupt_result == 4) return FCAM_VDF_R_INSTANCE;
    if (corrupt_result == 6) return FCAM_VDF_R_BYTES;
    if (corrupt_result == 7) return FCAM_VDF_R_INPUT_FNV;
    return zebra ? FCAM_ZEBRA_R_CONFIG + 4 : FCAM_VDF_R_CONFIG + 5;
}
/* shortcut: direct HOST_TEST transport, use separate mailbox/RSP tests for bridge evidence. */
int fcam_bridge_call(const struct fcam_native_origin *origin, uint32_t op, const void *input, size_t input_bytes,
    void *output, size_t capacity, struct fcam_bridge_result *result) {
    assert(origin && output && result && held);
    if (op == FCAM_OP_HISTOGRAM) {
        assert(hist.pointer[0] && origin->source == hist.source &&
            origin->destination == FUNCTIONAL_HISTOGRAM_SID && origin->command == 0x0148 &&
            origin->bytes == 12 && origin->wire_fnv1a64 == fnv(hist_request_wire, 12));
        assert(input_bytes == 8 && capacity == 1192 && !memcmp(input, hist_input, 8));
        struct fcam_exec_result actual = {0};
        const int rc = fcam_model_request(model, op, input, input_bytes, output, capacity, &actual);
        assert(rc == expected_core_rc && actual.used == (rc ? 0 : capacity) &&
            !actual.token && !actual.total && !actual.offset);
        *result = (struct fcam_bridge_result){actual.used, actual.used, instance, 0};
        memcpy(hist.result, output, sizeof hist.result); hist.metadata = *result;
        hist.core_proof = proof(); hist.calls++;
        if (!rc && corrupt_result) {
            assert(corrupt_result == 2 || corrupt_result == 9);
            ((unsigned char *)output)[corrupt_result == 2 ? 167 : FCAM_VDF_R_CLASS] ^= 1;
        }
        return rc;
    }
    assert(original);
    assert(origin->source == caller && origin->destination == FUNCTIONAL_VDF_PATH_SID &&
        origin->command == command() && origin->bytes == request_bytes &&
        origin->wire_fnv1a64 == fnv(original_wire, request_bytes));
    if (op == FCAM_OP_INIT) {
        init_calls++; assert(init_calls == 1 && !input && !input_bytes && capacity == 128);
    } else {
        assert(op == opcode() && input_bytes == operation_input_bytes() && capacity == result_bytes);
        assert(!memcmp(input, operation_input(), input_bytes)); path_calls++;
    }
    struct fcam_exec_result actual = {0};
    const int rc = fcam_model_request(model, op, input, input_bytes, output, capacity, &actual);
    assert(rc == (op == FCAM_OP_INIT ? 0 : expected_core_rc));
    assert(actual.used == (rc ? 0 : capacity) && !actual.token && !actual.total && !actual.offset);
    *result = (struct fcam_bridge_result){actual.used, actual.used, instance, actual.token};
    if (op == opcode()) {
        memset(authentic_result, 0, sizeof authentic_result);
        memcpy(authentic_result, output, result_bytes);
        authentic_metadata = *result;
        if (corrupt_result == 3) result->used--;
        else if (corrupt_result == 5) result->model_instance ^= 1;
        else if (corrupt_result == 8) {
            assert(display == 2 && u32(previous_display) == 0x0152);
            memcpy((unsigned char *)output + FCAM_DISPLAY_R_CONFIG, previous_display, sizeof previous_display);
            put64((unsigned char *)output + FCAM_VDF_R_INPUT_FNV, fnv(previous_display, sizeof previous_display));
        } else if (corrupt_result) ((unsigned char *)output)[corruption_offset()] ^= 1;
    }
    return rc;
}
int fcam_bridge_bb_startup_config(const struct fcam_native_origin *origin, const unsigned char input[32],
    unsigned char output[192], struct fcam_bridge_result *result) {
    return fcam_bridge_call(origin, FCAM_OP_BB_STARTUP_CONFIG, input, 32, output, 192, result);
}
int fcam_bridge_histogram(const struct fcam_native_origin *origin, const unsigned char input[8],
    unsigned char output[1192], struct fcam_bridge_result *result) {
    return fcam_bridge_call(origin, FCAM_OP_HISTOGRAM, input, 8, output, 1192, result);
}
static void check_fixed_core(const unsigned char before[128], const struct fcam_frame_proof *previous,
    uint32_t op, const unsigned char *input, size_t input_bytes, const unsigned char *actual,
    size_t bytes, uint32_t receipt_class) {
    unsigned char after[128], expected[FCAM_HIST_RESULT_BYTES] = {0};
    state_request(FCAM_OP_STATE, NULL, 0, after);
    const struct fcam_frame_proof p = proof(), second = proof();
    assert(!memcmp(&p, &second, sizeof p) && p.serial == previous->serial + 1 &&
        p.model_lifetime == previous->model_lifetime && p.opcode == op && p.consumer_kind == receipt_class);
    assert(!memcmp(&p.before, &previous->after, sizeof p.before));
    assert(p.after.rendered == p.before.rendered + 1 && p.after.consumed == p.before.consumed + 1 &&
        p.after.retired == p.before.retired + 1 && p.after.jpeg_encoded == p.before.jpeg_encoded &&
        p.after.video_encoded == p.before.video_encoded && p.packet_generation == previous->packet_generation);
    assert(p.render_observed && p.consumer_entered && p.consumer_returned && p.retired &&
        !p.encoder_consumed && !p.encoded_bytes && !p.result_token && !p.operation_status &&
        !p.render_status && !p.consumer_status && !p.retire_status && p.final_state == OPTICAL_FRAME_IDLE);
    assert(p.source_state == OPTICAL_FRAME_RENDERED && p.consumer_before_state == OPTICAL_FRAME_READING &&
        p.consumer_after_state == OPTICAL_FRAME_READING && p.lease_generation > previous->lease_generation);
    assert(p.width == 640 && p.height == 480 && p.stride == 1920 && p.active_bytes == UINT64_C(921600));
    assert(p.source_fnv1a64 && p.source_fnv1a64 == p.consumer_before_fnv1a64 &&
        p.source_fnv1a64 == p.consumer_after_fnv1a64 && p.result_bytes == bytes &&
        p.result_fnv1a64 == fnv(actual, bytes));
    assert(!memcmp(before + 8, after + 8, 48) && !memcmp(before + 80, after + 80, 32));
    assert(p.config_generation == u64(before + 56) + 1 && u64(after + 56) == p.config_generation &&
        p.frame_generation == u64(before + 112) + 1 && u64(after + 112) == p.frame_generation);
    assert(u64(after + 64) == p.after.rendered && u64(after + 72) == p.after.consumed);
    /* Literal offsets independently check the complete shared wire schema. */
    put32(expected, FCAM_ABI_VERSION); put32(expected + 4, (uint32_t)bytes); put64(expected + 8, instance);
    put64(expected + 16, p.config_generation); put64(expected + 24, p.frame_generation);
    put64(expected + 32, p.lease_generation); put64(expected + 40, fnv(input, input_bytes));
    put64(expected + 48, p.source_fnv1a64); put64(expected + 56, p.consumer_after_fnv1a64);
    put64(expected + 64, 921600); put32(expected + 72, 640); put32(expected + 76, 480);
    put32(expected + 80, 1920); put32(expected + 84, UINT32_C(0x90590819));
    put32(expected + 88, 1); put32(expected + 92, 1); put32(expected + 96, receipt_class);
    for (size_t offset = 100; offset <= 116; offset += 4) put32(expected + offset, 1);
    memcpy(expected + 128, canonical, 16); put64(expected + 144, u64(before + 112));
    put64(expected + 152, u64(before + 56)); memcpy(expected + 160, input, input_bytes);
    if (op == FCAM_OP_HISTOGRAM) memcpy(expected + 168, hist.expected_bins, 1024);
    assert(!memcmp(actual, expected, bytes));
}
static void check_core(const unsigned char before[128], const struct fcam_frame_proof *previous, unsigned int active) {
    const unsigned char *r = authentic_result;
    unsigned char after[128]; state_request(FCAM_OP_STATE, NULL, 0, after);
    const struct fcam_frame_proof p = proof(), second = proof();
    assert(!memcmp(&p, &second, sizeof p));
    assert(p.serial == previous->serial + 1 && p.model_lifetime && p.model_lifetime == previous->model_lifetime);
    assert(p.opcode == opcode() && p.consumer_kind == (bb ? FCAM_PROOF_BB_STARTUP : FCAM_PROOF_VDF) && !p.operation_status);
    assert(p.packet_generation == previous->packet_generation && p.frame_generation == u64(after + FCAM_S_FRAME_GENERATION));
    assert(!memcmp(&p.before, &previous->after, sizeof p.before));
    assert(!memcmp(before + FCAM_S_WIDTH, after + FCAM_S_WIDTH, FCAM_S_INSTANCE - FCAM_S_WIDTH));
    assert(u32(r + FCAM_VDF_R_BYTES) == result_bytes);
    assert(u64(r + FCAM_VDF_R_INSTANCE) == instance && !memcmp(r + FCAM_VDF_R_CONFIG, canonical, sizeof canonical));
    assert(u64(r + FCAM_VDF_R_INPUT_FNV) == fnv(operation_input(), operation_input_bytes()));
    if (display) assert(!memcmp(r + FCAM_DISPLAY_R_CONFIG, canonical_display, sizeof canonical_display));
    if (layout) assert(!memcmp(r + FCAM_LAYOUT_R_CONFIG, canonical_layout, sizeof canonical_layout));
    if (zebra) assert(!memcmp(r + FCAM_ZEBRA_R_CONFIG, canonical_zebra, sizeof canonical_zebra));
    assert(u32(r + FCAM_VDF_R_CONFIG_READBACK) == 1 && u32(r + FCAM_VDF_R_COMMITTED) == 1);
    assert(u64(r + FCAM_VDF_R_BEFORE_CONFIG_GENERATION) == u64(before + FCAM_S_GENERATION));
    assert(u64(r + FCAM_VDF_R_BEFORE_FRAME_GENERATION) == u64(before + FCAM_S_FRAME_GENERATION));
    assert(p.config_generation == u64(after + FCAM_S_GENERATION) &&
        p.config_generation == u64(before + FCAM_S_GENERATION) + 1);
    assert(u64(r + FCAM_VDF_R_CONFIG_GENERATION) == p.config_generation);
    assert(u64(r + FCAM_VDF_R_FRAME_GENERATION) == u64(after + FCAM_S_FRAME_GENERATION));
    assert(u64(after + FCAM_S_FRAME_GENERATION) == u64(before + FCAM_S_FRAME_GENERATION) + active);
    assert(p.before.rendered == u64(before + FCAM_S_RENDERED) && p.after.rendered == p.before.rendered + active);
    assert(p.before.consumed == u64(before + FCAM_S_CONSUMED) && p.after.consumed == p.before.consumed + active);
    assert(p.before.retired == previous->after.retired && p.after.retired == p.before.retired + active);
    assert(u64(after + FCAM_S_RENDERED) == p.after.rendered && u64(after + FCAM_S_CONSUMED) == p.after.consumed);
    assert(p.before.jpeg_encoded == u64(before + FCAM_S_JPEG_ENCODED) && p.before.jpeg_encoded == p.after.jpeg_encoded);
    assert(p.before.video_encoded == u64(before + FCAM_S_VIDEO_ENCODED) && p.before.video_encoded == p.after.video_encoded);
    assert(!memcmp(before + FCAM_S_JPEG_ENCODED, after + FCAM_S_JPEG_ENCODED, 24));
    assert(!u32(after + FCAM_S_PENDING_RESULTS) && !u32(after + FCAM_S_STREAM_STATE));
    assert(!p.encoder_consumed && !p.encoded_bytes && !p.result_token);
    if (bb) {
        assert(!memcmp(r + FCAM_BB_R_CONFIG, canonical_bb, sizeof canonical_bb));
        check_fixed_core(before, previous, opcode(), canonical_bb, 32, r, 192, 5);
    } else assert(!p.result_bytes);
    assert(u32(r + FCAM_VDF_R_CLASS) == (bb ? FCAM_BB_CLASS : active) && u32(r + FCAM_VDF_R_ENABLED) == active);
    assert(u64(r + FCAM_VDF_R_LEASE_GENERATION) == p.lease_generation);
    assert(p.final_state == OPTICAL_FRAME_IDLE && p.render_observed == active &&
        p.consumer_entered == active && p.consumer_returned == active && p.retired == active);
    if (active) {
        assert(p.width == u32(before + FCAM_S_WIDTH) && p.height == u32(before + FCAM_S_HEIGHT));
        assert(p.stride == p.width * 3 && p.active_bytes == p.width * p.height * 3);
        assert(p.lease_generation > previous->lease_generation && p.frame_generation == u64(after + FCAM_S_FRAME_GENERATION));
        assert(p.source_fnv1a64 && p.source_fnv1a64 == p.consumer_before_fnv1a64 &&
            p.source_fnv1a64 == p.consumer_after_fnv1a64);
        assert(p.source_fnv1a64 == u64(r + FCAM_VDF_R_SOURCE_FNV) &&
            p.consumer_after_fnv1a64 == u64(r + FCAM_VDF_R_SINK_FNV));
        assert(p.active_bytes == u64(r + FCAM_VDF_R_ACTIVE_BYTES));
        assert(!p.render_status && !p.consumer_status && !p.retire_status);
        assert(p.source_state == OPTICAL_FRAME_RENDERED && p.consumer_before_state == OPTICAL_FRAME_READING &&
            p.consumer_after_state == OPTICAL_FRAME_READING);
    } else {
        assert(!p.active_bytes && !p.lease_generation && !p.source_fnv1a64 && !p.consumer_after_fnv1a64);
        assert(!u64(r + FCAM_VDF_R_ACTIVE_BYTES) && !u64(r + FCAM_VDF_R_SOURCE_FNV) && !u64(r + FCAM_VDF_R_SINK_FNV));
        assert(!u32(r + FCAM_VDF_R_FRAME_CONSUMED) && !u32(r + FCAM_VDF_R_RETIRED));
        assert(p.render_status == -ENODATA && p.consumer_status == -ENODATA && p.retire_status == -ENODATA);
    }
}
static void prepare_request(unsigned int active, unsigned int sender) {
    caller = sender; stage = 0; assert(!original && !allocated_ack && !queued_ack && !received_ack);
    request_bytes = bb ? bb_request_bytes[bb - 1] : display ? display == 1 ? FUNCTIONAL_VDF_PEAKING_REQUEST_BYTES :
        display == 2 ? FUNCTIONAL_VDF_FLAG_REQUEST_BYTES : FUNCTIONAL_VDF_REFRESH_REQUEST_BYTES :
        layout ? FUNCTIONAL_VDF_LAYOUT_REQUEST_BYTES : zebra ? FUNCTIONAL_VDF_ZEBRA_REQUEST_BYTES : FUNCTIONAL_VDF_PATH_REQUEST_BYTES;
    result_bytes = bb ? FCAM_BB_RESULT_BYTES : display ? FCAM_DISPLAY_RESULT_BYTES : layout ? FCAM_LAYOUT_RESULT_BYTES : zebra ? FCAM_ZEBRA_RESULT_BYTES : FCAM_VDF_RESULT_BYTES;
    unsigned char *p = original = message(request_bytes, caller); request_address = (uintptr_t)p;
    if (bb) {
        assert(bb <= 5); memcpy(p, bb_requests[bb - 1], request_bytes);
        memcpy(canonical_bb, bb_inputs[bb - 1], sizeof canonical_bb);
        if (bb_observed_initial && bb == 2) {
            static const unsigned char body[28] = {0,1,0,0,0,0,0,0,0,0,0,0,8,0,0,0,7,0,0,0,1,0,0,0,1,0,0,0};
            memcpy(p + 8, body, sizeof body); memcpy(canonical_bb + 4, body, sizeof body);
        }
        if (bb_variant && bb == 3) p[8] = canonical_bb[4] = 0;
        if (bb_variant && bb == 5) { p[12] = 9; canonical_bb[8] = 9; }
    } else if (display) {
        static const unsigned char peaking[16] = {0x0d, 0x20, 0x52, 1, 16, 0, 1, 0x80, 3, 0, 1, 0, 0, 235, 128, 128};
        static const unsigned char flag[10] = {0x0d, 0x20, 0x62, 1, 10, 0, 1, 0x80, 0, 0};
        static const unsigned char refresh[8] = {0x0d, 0x20, 0x41, 1, 8, 0, 1, 0x80};
        memcpy(p, display == 1 ? peaking : display == 2 ? flag : refresh, request_bytes);
        if (display == 1) {
            assert(palette < 4 && level <= 2);
            p[10] = (unsigned char)level; p[11] = (unsigned char)magnification;
            memcpy(p + 13, palettes[palette], 3);
        }
        memset(canonical_display, 0, sizeof canonical_display);
        put32(canonical_display, command()); put32(canonical_display + 4, request_bytes - 8);
        memcpy(canonical_display + 8, p + 8, request_bytes - 8);
    } else if (layout) {
        memcpy(p, layout_wire, sizeof layout_wire); memcpy(canonical_layout, p + 8, sizeof canonical_layout);
    } else if (zebra) {
        static const unsigned char raw[14] = {0x0d, 0x20, 0x53, 1, 14, 0, 1, 0x80, 3, 0, 0x20, 0x4b, 0x41, 0};
        memcpy(p, raw, sizeof raw); memset(canonical_zebra, 0, sizeof canonical_zebra);
        memcpy(canonical_zebra, p + 8, 5);
    } else {
        static const unsigned char header[8] = {0x0d, 0x20, 0x38, 1, 24, 0, 1, 0x80};
        memcpy(p, header, sizeof header); p[8] = (unsigned char)active; p[9] = p[10] = active ? 5 : 1;
        for (unsigned int i = 11; i < 24; i++) p[i] = (unsigned char)(0xa0 + i + path_calls);
        p[12] = 2;
        memcpy(canonical, p + 8, sizeof canonical); memset(canonical + 13, 0, 3);
    }
    memset(original_wire, 0, sizeof original_wire); memcpy(original_wire, p, request_bytes);
}
static void cycle(unsigned int active, unsigned int sender) {
    unsigned char before[128]; state_request(FCAM_OP_STATE, NULL, 0, before);
    const struct fcam_frame_proof previous = proof();
    const unsigned int old_allocations = allocations, old_sends = sends, old_frees = request_frees;
    prepare_request(active, sender);
    int rc = 999;
    assert(functional_vdf_path_dispatch(FUNCTIONAL_VDF_PATH_SID, original, &io, &guard, 1, &rc) == 1);
    check_core(before, &previous, active);
    struct functional_vdf_path_snapshot s = owner();
    assert(!held && !s.busy && !s.guard_held && init_calls == 1);
    if (corrupt_result) {
        assert(rc < 0 && s.faults && !s.model_complete && !s.ap_consumed && !s.request_owned);
        assert(!s.bridge_rc && s.validation_rc < 0 && allocations == old_allocations &&
            sends == old_sends && request_frees == old_frees && !allocated_ack);
        unsigned char changed[FCAM_VDF_RESULT_MAX_BYTES]; memcpy(changed, authentic_result, sizeof changed);
        if (corrupt_result == 3) changed[result_bytes - 1] = 0;
        else if (corrupt_result == 8) {
            memcpy(changed + FCAM_DISPLAY_R_CONFIG, previous_display, sizeof previous_display);
            put64(changed + FCAM_VDF_R_INPUT_FNV, fnv(previous_display, sizeof previous_display));
        } else if (corrupt_result != 5) changed[corruption_offset()] ^= 1;
        assert(s.model_result_bytes == result_bytes - (corrupt_result == 3) &&
            !memcmp(s.model_result, changed, sizeof changed));
        assert(!memcmp(original, original_wire, request_bytes) && s.completed_cycles == old_sends &&
            s.requests == old_sends && ack_frees == old_sends && s.cycle == previous_ticket + 1);
        if (layout || display || bb) {
            assert(rc == -EPROTO && s.validation_rc == -EPROTO);
            printf("%s reply rejected corruption=%d tail_byte=%u core_bytes=%u guest_rc=%d ack_delta=0\n",
                bb ? "bb" : display ? "display" : "layout", corrupt_result, corrupt_tail, result_bytes, rc);
        }
        free(envelope(original)); original = NULL; repeated_init(); return;
    }
    if (rc) {
        assert(s.faults && !s.model_complete && !s.ap_consumed && !s.request_owned);
        assert(original && !allocated_ack && sends == old_sends && request_frees == old_frees);
        fprintf(stderr, "real core/guest mismatch: command=%04x path=%u core_status=%lld guest_rc=%d validation_rc=%d lease=%llu before_frame=%llu frame=%llu sends=%u\nreal_reply=",
            command(), active, (long long)proof().operation_status, rc, s.validation_rc,
            (unsigned long long)u64(authentic_result + FCAM_VDF_R_LEASE_GENERATION),
            (unsigned long long)u64(authentic_result + FCAM_VDF_R_BEFORE_FRAME_GENERATION),
            (unsigned long long)u64(authentic_result + FCAM_VDF_R_FRAME_GENERATION), sends);
        for (size_t i = 0; i < result_bytes; i++) fprintf(stderr, "%02x", authentic_result[i]);
        fputc('\n', stderr);
    }
    if (s.allocation_alias) fprintf(stderr,
        "retired-request alias: command=%04x allocate_rc=%d request_freed=%u request_null=%u same_address=%u ack_size=%u request_frees=%u allocations=%u sends=%u\n",
        command(), s.leases[1].allocate_rc, s.leases[0].freed, !s.leases[0].pointer,
        (uintptr_t)allocated_ack == request_address, size(allocated_ack), request_frees, allocations, sends);
    assert(!rc && !s.faults && s.model_complete && s.request_owned);
    assert(!memcmp(s.model_result, authentic_result, sizeof authentic_result) && !memcmp(s.canonical_config, canonical, sizeof canonical));
    assert(s.model_result_bytes == result_bytes && s.model_instance == instance);
    if (bb) assert(!memcmp(s.canonical_bb32, canonical_bb, 32) &&
        !memcmp(s.model_result + 160, canonical_bb, 32));
    if (layout) assert(!memcmp(s.canonical_layout32, canonical_layout, sizeof canonical_layout) &&
        !memcmp(s.model_result + FCAM_LAYOUT_R_CONFIG, canonical_layout, sizeof canonical_layout));
    if (zebra) assert(!memcmp(s.canonical_zebra8, canonical_zebra, sizeof canonical_zebra));
    if (display) assert(!memcmp(s.canonical_display16, canonical_display, sizeof canonical_display) &&
        !memcmp(s.canonical_layout32, canonical_layout, sizeof canonical_layout) &&
        !memcmp(s.canonical_zebra8, canonical_zebra, sizeof canonical_zebra));
    assert(s.config_generation == proof().config_generation && s.frame_generation == proof().frame_generation &&
        s.lease_generation == proof().lease_generation);
    assert(s.leases[0].wire_fnv1a64 == fnv(original_wire, request_bytes) &&
        s.leases[1].wire_fnv1a64 == fnv(ack_wire[ack_index()], sizeof ack_wire[0]));
    assert(!memcmp(s.original_wire, original_wire, sizeof original_wire) && s.origin.source == caller);
    assert(s.ack_queued && !s.ack_received && !s.ap_consumed && s.leases[0].freed && !original);
    assert(sends == old_sends + 1 && request_frees == old_frees + 1 && allocations == old_allocations + 1);
    assert(s.leases[1].source == FUNCTIONAL_VDF_PATH_SID && s.leases[1].destination == caller);
    assert(stage == 2 && queued_ack && queued_ack == allocated_ack && !received_ack);
    if (display == 3) {
        repeated_init();
        assert(owner().ack_queued && !owner().ack_received && !owner().ap_consumed && stage == 2);
    }
    received_ack = queued_ack; queued_ack = NULL; stage = 3;
    if (early_stage_case && layout) {
        const struct functional_vdf_layout_stage_snapshot before_stage = early_snapshot();
        uint64_t foreign_ticket = 0; int foreign_rc = 999;
        assert(functional_vdf_layout_stage_observe_receive_cycle(caller, received_ack,
            source(received_ack), size(received_ack), &foreign_ticket) == 0 && !foreign_ticket);
        const int handled = functional_vdf_layout_stage_release_cycle(caller, received_ack, early.ticket,
            early_release, NULL, &foreign_rc);
        assert((!handled && foreign_rc == 999) || (handled == 1 && foreign_rc == -ESTALE));
        const struct functional_vdf_layout_stage_snapshot after_stage = early_snapshot();
        assert(!memcmp(&before_stage, &after_stage, sizeof after_stage) && !after_stage.applied.verified &&
            early.ack_frees == 3 && ack_frees == old_sends && received_ack);
        puts("early_stage layout_ack_stage_matches=0 staged_bank_unchanged=1 applied_before_bind=0");
    }
    int stale_rc = 999;
    if (previous_ticket) {
        const struct functional_vdf_path_snapshot before_stale = owner();
        assert(functional_vdf_path_release_cycle(caller, received_ack, previous_ticket, release, NULL, &stale_rc) == 1 &&
            stale_rc == -ESTALE && ack_frees == old_sends);
        s = owner(); assert(!memcmp(&s, &before_stale, sizeof s));
    }
    uint64_t ticket = 0;
    assert(functional_vdf_path_observe_receive_cycle(caller, received_ack, source(received_ack), size(received_ack), &ticket) == 1);
    assert(ticket == previous_ticket + 1 && ticket == owner().cycle); previous_ticket = ticket;
    s = owner(); assert(s.ack_received && !s.ap_consumed && !s.leases[1].freed);
    if (previous_ticket > 1) {
        const struct functional_vdf_path_snapshot before_stale = s;
        assert(functional_vdf_path_release_cycle(caller, received_ack, ticket - 1, release, NULL, &stale_rc) == 1 &&
            stale_rc == -ESTALE && ack_frees == old_sends);
        s = owner(); assert(!memcmp(&s, &before_stale, sizeof s));
    }
    rc = 999;
    assert(functional_vdf_path_release_cycle(caller, received_ack, ticket, release, NULL, &rc) == 1 && !rc);
    s = owner();
    assert(stage == 4 && !allocated_ack && !received_ack && s.ap_consumed && !s.faults);
    assert(s.completed_cycles == path_calls && s.requests == path_calls && ack_frees == path_calls);
    assert(s.phase == FUNCTIONAL_VDF_PATH_AP_CONSUMED && s.leases[1].freed && s.leases[1].consumed);
    assert(s.leases[1].sender_tid == s.leases[1].receiver_tid && s.leases[1].receiver_tid == s.leases[1].free_tid);
    if (display) {
        assert(ticket > 1 && s.leases[1].free_tid && s.origin.command == command());
        printf("display176 command=%04x input_fnv=%016llx canonical_display16=", command(),
            (unsigned long long)u64(authentic_result + FCAM_VDF_R_INPUT_FNV));
        for (size_t i = 0; i < sizeof canonical_display; i++) printf("%02x", s.canonical_display16[i]);
        printf(" ack_wire=");
        for (size_t i = 0; i < sizeof ack_wire[0]; i++) printf("%02x", ack_wire[ack_index()][i]);
        printf(" source_fnv=%016llx sink_fnv=%016llx active_bytes=%llu same_tid=1 actual_free=1 stale_ticket_rejected=1 "
            "origin_source=%08x refresh_queue_bound=%u refresh_queue_source=%08x\n",
            (unsigned long long)proof().source_fnv1a64, (unsigned long long)proof().consumer_after_fnv1a64,
            (unsigned long long)proof().active_bytes, s.origin.source, s.refresh_queue_bound, s.refresh_queue_source);
        memcpy(previous_display, canonical_display, sizeof previous_display);
    }
    if (bb) {
        printf("bb192 command=%04x cycle=%llu input_fnv=%016llx config=%llu frame=%llu proof_serial=%llu "
            "proof_kind=%llu class=5 active_bytes=%llu origin_source=%08x actual_request_free=1 actual_ack_free=1 "
            "same_tid=1 independent_lease=1 full_result_verified=1 request_wire=", command(),
            (unsigned long long)ticket, (unsigned long long)u64(authentic_result + 40),
            (unsigned long long)proof().config_generation, (unsigned long long)proof().frame_generation,
            (unsigned long long)proof().serial, (unsigned long long)proof().consumer_kind,
            (unsigned long long)proof().active_bytes, caller);
        for (size_t i = 0; i < request_bytes; i++) printf("%02x", original_wire[i]);
        printf(" canonical32="); for (size_t i = 0; i < 32; i++) printf("%02x", canonical_bb[i]);
        printf(" ack_wire="); for (size_t i = 0; i < 12; i++) printf("%02x", ack_wire[ack_index()][i]);
        printf(" result192="); for (size_t i = 0; i < 192; i++) printf("%02x", authentic_result[i]);
        putchar('\n');
    }
    repeated_init();
}
static void reject_layout(int body_byte, int core_rc, int guest_rc, int reaches_core) {
    unsigned char before[128], after[128], out[FCAM_LAYOUT_RESULT_BYTES], untouched[sizeof out];
    state_request(FCAM_OP_STATE, NULL, 0, before);
    const struct fcam_frame_proof previous = proof();
    const struct functional_vdf_path_snapshot old_owner = owner();
    const unsigned int calls = path_calls, inits = init_calls, allocated = allocations, sent = sends;
    const unsigned int freed = request_frees, ack_released = ack_frees;
    layout = 1; zebra = 0; prepare_request(1, UINT32_C(0x81cfa74c));
    if (body_byte >= 0) {
        assert(body_byte < 32); ((unsigned char *)original)[8 + body_byte] ^= 1;
        memcpy(original_wire, original, request_bytes);
    }
    memset(out, 0xa5, sizeof out); memcpy(untouched, out, sizeof out);
    struct fcam_exec_result result = {91, 92, 93, 94}, saved_result = result;
    assert(fcam_model_request(model, FCAM_OP_VDF_LAYOUT, (unsigned char *)original + 8,
        FCAM_LAYOUT_INPUT_BYTES, out, sizeof out, &result) == core_rc);
    assert(!memcmp(out, untouched, sizeof out) && !memcmp(&result, &saved_result, sizeof result));
    expected_core_rc = reaches_core ? core_rc : 0;
    int rc = 999;
    assert(functional_vdf_path_dispatch(FUNCTIONAL_VDF_PATH_SID, original, &io, &guard, 1, &rc) == 1 && rc == guest_rc);
    expected_core_rc = 0;
    struct functional_vdf_path_snapshot s = owner();
    assert(!held && !s.busy && !s.guard_held && original && !memcmp(original, original_wire, request_bytes));
    assert(allocations == allocated && sends == sent && request_frees == freed && ack_frees == ack_released &&
        !allocated_ack && !queued_ack && !received_ack && init_calls == inits && path_calls == calls + reaches_core);
    if (reaches_core) {
        assert(s.faults && !s.model_complete && !s.request_owned && !s.ap_consumed &&
            s.bridge_rc == core_rc && s.validation_rc == core_rc && !s.model_result_bytes &&
            s.requests == old_owner.requests && s.completed_cycles == old_owner.completed_cycles);
    } else assert(!memcmp(&s, &old_owner, sizeof s));
    state_request(FCAM_OP_STATE, NULL, 0, after);
    const struct fcam_frame_proof last = proof();
    assert(!memcmp(before, after, sizeof before) && !memcmp(&previous, &last, sizeof last));
    printf("layout rejected body_byte=%d core_rc=%d guest_rc=%d core_state_unchanged=1 proof_unchanged=1 "
        "ack_delta=0 guest_unchanged=%d\n", body_byte, core_rc, guest_rc, !reaches_core);
    free(envelope(original)); original = NULL; repeated_init();
}
static void layout_sequence(const char *scenario) {
    assert(!functional_vdf_path_owner_init());
    if (!strcmp(scenario, "layout-no-route")) { reject_layout(-1, -ENODATA, -ENODATA, 0); return; }
    if (!strcmp(scenario, "layout-disabled")) {
        cycle(0, UINT32_C(0x81cf0123)); reject_layout(-1, -ENODATA, -ENODATA, 0); return;
    }
    cycle(1, UINT32_C(0x81cf0123));
    if (!strcmp(scenario, "layout-geometry-width") || !strcmp(scenario, "layout-geometry-height")) {
        configure(!strcmp(scenario, "layout-geometry-width") ? 96 : 640,
            !strcmp(scenario, "layout-geometry-height") ? 64 : 480);
        reject_layout(-1, -ENOTSUP, -ENOTSUP, 1); return;
    }
    if (!strncmp(scenario, "layout-body-", 12)) {
        unsigned int offset = 32;
        assert(sscanf(scenario, "layout-body-%u", &offset) == 1 && offset < 32);
        reject_layout((int)offset, -ENOTSUP, -EINVAL, 0); return;
    }
    zebra = 1; cycle(1, UINT32_C(0x81cf4567)); zebra = 0; layout = 1;
    if (!strncmp(scenario, "layout-tail-", 12)) {
        assert(sscanf(scenario, "layout-tail-%u", &corrupt_tail) == 1 && corrupt_tail < 32); corrupt_result = 2;
    } else if (!strcmp(scenario, "layout-result-used")) corrupt_result = 3;
    else if (!strcmp(scenario, "layout-result-instance")) corrupt_result = 4;
    else if (!strcmp(scenario, "layout-result-metadata-instance")) corrupt_result = 5;
    else if (!strcmp(scenario, "layout-result-length")) corrupt_result = 6;
    else if (!strcmp(scenario, "layout-result-input-fnv")) corrupt_result = 7;
    else assert(!strcmp(scenario, "layout-mixed") || !strcmp(scenario, "layout-mixed-address-reuse") ||
        !strcmp(scenario, "layout-fresh-request-lease"));
    cycle(1, UINT32_C(0x81cf89ab));
    unsigned char final[128]; state_request(FCAM_OP_STATE, NULL, 0, final);
    const struct fcam_frame_proof p = proof();
    assert(u32(final + FCAM_S_WIDTH) == 640 && u32(final + FCAM_S_HEIGHT) == 480 &&
        u64(final + FCAM_S_GENERATION) == 4 && u64(final + FCAM_S_FRAME_GENERATION) == 4 &&
        u64(final + FCAM_S_RENDERED) == 4 && u64(final + FCAM_S_CONSUMED) == 3 &&
        p.serial == 4 && p.after.retired == 4 && !p.after.jpeg_encoded && !p.after.video_encoded);
    const struct functional_vdf_path_snapshot before_init = owner();
    repeated_init(); const struct functional_vdf_path_snapshot after_init = owner();
    assert(!memcmp(&before_init, &after_init, sizeof after_init) && init_calls == 1 && path_calls == 3);
    if (!corrupt_result) assert(after_init.requests == 3 && after_init.completed_cycles == 3 && after_init.ap_consumed);
    printf("layout192 config=4 frame=4 rendered=4 consumed=3 retired=4 init_calls=1 requests=%u completed_cycles=%u "
        "input_fnv=%016llx source_fnv=%016llx sink_fnv=%016llx same_ack_address=%d capture_verified=false\n",
        after_init.requests, after_init.completed_cycles,
        (unsigned long long)u64(authentic_result + FCAM_VDF_R_INPUT_FNV),
        (unsigned long long)p.source_fnv1a64, (unsigned long long)p.consumer_after_fnv1a64, reuse_ack);
}
static void reject_display_input(const unsigned char *input, size_t bytes, size_t capacity, int expected) {
    unsigned char before[128], after[128], out[FCAM_DISPLAY_RESULT_BYTES], untouched[sizeof out];
    state_request(FCAM_OP_STATE, NULL, 0, before);
    const struct fcam_frame_proof first = proof();
    const struct functional_vdf_path_snapshot old_owner = owner();
    memset(out, 0xa5, sizeof out); memcpy(untouched, out, sizeof out);
    struct fcam_exec_result result = {91, 92, 93, 94}, saved = result;
    assert(fcam_model_request(model, FCAM_OP_VDF_DISPLAY_CONFIG, input, bytes, out, capacity, &result) == expected);
    assert(!memcmp(out, untouched, sizeof out) && !memcmp(&result, &saved, sizeof saved));
    state_request(FCAM_OP_STATE, NULL, 0, after);
    const struct fcam_frame_proof last = proof();
    const struct functional_vdf_path_snapshot current = owner();
    assert(!memcmp(before, after, sizeof before) && !memcmp(&first, &last, sizeof first) &&
        !memcmp(&old_owner, &current, sizeof current));
}
static void reject_display(int mutation) {
    const struct functional_vdf_path_snapshot old_owner = owner();
    const unsigned int calls = path_calls, inits = init_calls, allocated = allocations, sent = sends;
    const unsigned int freed = request_frees, ack_released = ack_frees;
    unsigned char before[128], after[128]; state_request(FCAM_OP_STATE, NULL, 0, before);
    const struct fcam_frame_proof first = proof();
    prepare_request(1, UINT32_C(0x81cf0152));
    unsigned char input[FCAM_DISPLAY_INPUT_BYTES]; memcpy(input, canonical_display, sizeof input);
    int core_rc = -ENODATA, guest_rc = -ENODATA;
    if (mutation == 1) {
        const unsigned int offset = display == 1 ? 1 : 0;
        ((unsigned char *)original)[8 + offset] = input[8 + offset] = 1;
        core_rc = -ENOTSUP; guest_rc = -EINVAL;
    } else if (mutation == 2) {
        ((unsigned char *)original)[4] ^= 1; input[4] ^= 1; core_rc = -EINVAL;
    }
    memcpy(original_wire, original, request_bytes);
    reject_display_input(input, sizeof input, FCAM_DISPLAY_RESULT_BYTES, core_rc);
    int rc = 999;
    assert(functional_vdf_path_dispatch(FUNCTIONAL_VDF_PATH_SID, original, &io, &guard, 1, &rc) == 1 && rc == guest_rc);
    const struct functional_vdf_path_snapshot s = owner();
    state_request(FCAM_OP_STATE, NULL, 0, after); const struct fcam_frame_proof last = proof();
    assert(!held && !memcmp(&s, &old_owner, sizeof s) && !memcmp(before, after, sizeof before) &&
        !memcmp(&first, &last, sizeof first) && !memcmp(original, original_wire, request_bytes));
    assert(path_calls == calls && init_calls == inits && allocations == allocated && sends == sent &&
        request_frees == freed && ack_frees == ack_released && !allocated_ack && !queued_ack && !received_ack);
    printf("display rejected command=%04x mutation=%d core_rc=%d guest_rc=%d core_state_unchanged=1 proof_unchanged=1 "
        "guest_unchanged=1 ack_delta=0\n", command(), mutation, core_rc, guest_rc);
    free(envelope(original)); original = NULL; repeated_init();
}
static void display_sequence(const char *scenario) {
    assert(!functional_vdf_path_owner_init());
    if (!strcmp(scenario, "display-no-active") || !strcmp(scenario, "display-disabled")) {
        if (!strcmp(scenario, "display-disabled")) cycle(0, UINT32_C(0x81cf0123));
        for (display = 1; display <= 2; display++) reject_display(0);
        return;
    }
    cycle(1, UINT32_C(0x81cf0123));
    zebra = 1; cycle(1, UINT32_C(0x81cf4567)); zebra = 0;
    layout = 1; cycle(1, UINT32_C(0x81cf89ab)); layout = 0;
    if (!strcmp(scenario, "display-unsupported") || !strcmp(scenario, "display-malformed-envelope")) {
        const int malformed = !strcmp(scenario, "display-malformed-envelope");
        for (display = 1; display <= 2; display++) reject_display(malformed ? 2 : 1);
        if (malformed) {
            unsigned char input[FCAM_DISPLAY_INPUT_BYTES + 1] = {0};
            put32(input, 0x0152); put32(input + 4, 8); memcpy(input + 8, "\003\000\001\000\000\353\200\200", 8);
            reject_display_input(input, 15, FCAM_DISPLAY_RESULT_BYTES, -EINVAL);
            reject_display_input(input, sizeof input, FCAM_DISPLAY_RESULT_BYTES, -EINVAL);
            reject_display_input(input, 16, FCAM_DISPLAY_RESULT_BYTES - 1, -ENOSPC);
            put32(input, 0x10152); reject_display_input(input, 16, FCAM_DISPLAY_RESULT_BYTES, -ENOTSUP);
            memset(input, 0, sizeof input); put32(input, 0x0162); put32(input + 4, 2); input[15] = 1;
            reject_display_input(input, 16, FCAM_DISPLAY_RESULT_BYTES, -EINVAL);
            puts("display typed_envelope_rejections=5 core_state_unchanged=1 proof_unchanged=1 ack_delta=0");
        }
        return;
    }
    const int small = !strcmp(scenario, "display-small-frame");
    if (small) configure(96, 64);
    display = 1;
    if (!strcmp(scenario, "display-peaking-result-tail")) { corrupt_result = 2; corrupt_tail = 15; }
    else if (!strcmp(scenario, "display-peaking-result-input-fnv")) corrupt_result = 7;
    cycle(1, UINT32_C(0x81cf0152));
    if (!corrupt_result) {
        display = 2;
        if (!strcmp(scenario, "display-flag-result-tail")) { corrupt_result = 2; corrupt_tail = 10; }
        else if (!strcmp(scenario, "display-flag-result-input-fnv")) corrupt_result = 7;
        else if (!strcmp(scenario, "display-flag-result-length")) corrupt_result = 6;
        else if (!strcmp(scenario, "display-flag-result-borrowed")) corrupt_result = 8;
        cycle(1, UINT32_C(0x81cf0162));
    }
    if (corrupt_result) {
        unsigned char state[128]; state_request(FCAM_OP_STATE, NULL, 0, state);
        const struct fcam_frame_proof p = proof();
        const unsigned int commits = display == 1 ? 4 : 5;
        assert(u64(state + FCAM_S_GENERATION) == commits + 1 && u64(state + FCAM_S_FRAME_GENERATION) == commits + 1 &&
            u64(state + FCAM_S_RENDERED) == commits + 1 && u64(state + FCAM_S_CONSUMED) == commits &&
            p.serial == commits + 1 && p.after.retired == commits + 1 && path_calls == commits &&
            sends == commits - 1 && owner().completed_cycles == commits - 1);
        printf("display rejected receipt core_commits=1 extra_config=0 extra_frame=0 extra_proof=0 config=%u frame=%u ack_delta=0\n",
            commits + 1, commits + 1);
        return;
    }
    unsigned int extra = 0;
    if (!strcmp(scenario, "display-palette-variants")) {
        static const unsigned int magnifications[3] = {0, 10, 40};
        display = 1;
        for (palette = 0; palette < 3; palette++) {
            level = palette; magnification = magnifications[palette];
            cycle(1, UINT32_C(0x81cf0152)); extra++;
        }
    }
    unsigned char final[128]; state_request(FCAM_OP_STATE, NULL, 0, final);
    const struct fcam_frame_proof p = proof();
    const unsigned int frames = 6 + extra, configs = frames + (unsigned int)small;
    assert(u32(final + FCAM_S_WIDTH) == (small ? 96u : 640u) && u32(final + FCAM_S_HEIGHT) == (small ? 64u : 480u) &&
        u64(final + FCAM_S_GENERATION) == configs && u64(final + FCAM_S_FRAME_GENERATION) == frames &&
        u64(final + FCAM_S_RENDERED) == frames && u64(final + FCAM_S_CONSUMED) == frames - 1 &&
        p.serial == frames && p.after.retired == frames && !p.after.jpeg_encoded && !p.after.video_encoded);
    const struct functional_vdf_path_snapshot before_init = owner(); repeated_init();
    const struct functional_vdf_path_snapshot after_init = owner();
    assert(!memcmp(&before_init, &after_init, sizeof after_init) && init_calls == 1 && path_calls == 5 + extra &&
        after_init.requests == path_calls && after_init.completed_cycles == path_calls && after_init.ap_consumed);
    printf("display_sequence config=%u frame=%u rendered=%u consumed=%u retired=%u proof_serial=%u init_calls=1 "
        "requests=%u completed_cycles=%u width=%llu height=%llu same_ack_address=%d stale_across_commands=1 "
        "instance=%016llx lifetime=%016llx capture_verified=false physical_asic_verified=false original_ap_verified=false\n",
        configs, frames, frames, frames - 1, frames, frames, after_init.requests, after_init.completed_cycles,
        (unsigned long long)p.width, (unsigned long long)p.height, reuse_ack,
        (unsigned long long)p.model_instance, (unsigned long long)p.model_lifetime);
}
static void early_stage_sequence(void) {
    unsigned char before[128], after[128]; state_request(FCAM_OP_STATE, NULL, 0, before);
    const struct fcam_frame_proof first = proof();
    struct functional_vdf_path_snapshot untouched_owner; functional_vdf_path_snapshot(&untouched_owner);
    assert(!untouched_owner.initialized && !init_calls && !path_calls && !allocations && !request_frees && !ack_frees);
    assert(!functional_vdf_layout_stage_owner_init());
    for (unsigned int generation = 1; generation <= 3; generation++) {
        assert(!early.request && !early.ack && !early.queued && !early.received);
        early.phase = 0; early.request = message(40, early_caller); memcpy(early.request, layout_wire, 40);
        int rc = 999;
        assert(functional_vdf_layout_stage_dispatch(FUNCTIONAL_LAYOUT_STAGE_SID, early.request,
            &stage_io, 1, 0, &rc) == 1 && !rc);
        struct functional_vdf_layout_stage_snapshot s = early_snapshot();
        assert(!s.busy && !s.faults && !s.validation_rc && s.request_owned && s.bank_written && s.readback_verified &&
            s.requests == generation && s.completed_cycles == generation - 1 && s.cycle == generation &&
            s.stage_generation == generation && s.ack_queued && !s.ack_received && !s.ap_consumed && !s.applied.verified);
        assert(s.origin.source == early_caller && s.origin.destination == FUNCTIONAL_LAYOUT_STAGE_SID &&
            s.origin.command == 0x014c && s.origin.bytes == 40 && s.origin.wire_fnv1a64 == fnv(layout_wire, 40) &&
            !memcmp(s.original_wire, layout_wire, 40) && !memcmp(s.bank32, layout_wire + 8, 32) &&
            !memcmp(s.copied_readback32, layout_wire + 8, 32) && s.bank_fnv1a64 == s.readback_fnv1a64 &&
            s.bank_fnv1a64 == fnv(layout_wire + 8, 32));
        assert(!early.request && early.queued == early.ack && early.phase == 2);
        early.received = early.queued; early.queued = NULL; early.phase = 3;
        if (early.ticket) {
            assert(functional_vdf_layout_stage_release_cycle(early_caller, early.received, early.ticket,
                early_release, NULL, &rc) == 1 && rc == -ESTALE);
            const struct functional_vdf_layout_stage_snapshot stale = early_snapshot();
            assert(!memcmp(&s, &stale, sizeof s) && early.ack_frees == generation - 1);
        }
        uint64_t ticket = 0;
        assert(functional_vdf_layout_stage_observe_receive_cycle(early_caller, early.received,
            source(early.received), size(early.received), &ticket) == 1 && ticket == generation && ticket == early.ticket + 1);
        early.ticket = ticket;
        assert(functional_vdf_layout_stage_release_cycle(early_caller, early.received, ticket,
            early_release, NULL, &rc) == 1 && !rc);
        s = early_snapshot();
        assert(s.ap_consumed && s.completed_cycles == generation && !s.faults && !s.applied.verified &&
            s.leases[0].freed && !s.leases[0].pointer && s.leases[1].freed && !s.leases[1].pointer &&
            s.leases[1].consumed && s.leases[1].sender_tid &&
            s.leases[1].sender_tid == s.leases[1].receiver_tid && s.leases[1].receiver_tid == s.leases[1].free_tid);
        state_request(FCAM_OP_STATE, NULL, 0, after); const struct fcam_frame_proof last = proof();
        struct functional_vdf_path_snapshot current_owner; functional_vdf_path_snapshot(&current_owner);
        assert(!memcmp(before, after, sizeof before) && !memcmp(&first, &last, sizeof first) &&
            !memcmp(&untouched_owner, &current_owner, sizeof current_owner));
        assert(!init_calls && !path_calls && !allocations && !sends && !request_frees && !ack_frees &&
            early.allocations == generation && early.sends == generation && early.request_frees == generation &&
            early.ack_frees == generation && early.phase == 4);
        printf("early_stage generation=%u source=%08x bank_fnv=%016llx readback_fnv=%016llx stage_only=1 "
            "semantic_applied=0 frame_consumed=0 core_state_unchanged=1 proof_unchanged=1 bridge_calls=0 "
            "same_tid=1 actual_request_free=1 actual_ack_free=1\n", generation, early_caller,
            (unsigned long long)s.bank_fnv1a64, (unsigned long long)s.readback_fnv1a64);
    }
    const struct functional_vdf_layout_stage_snapshot staged = early_snapshot();
    assert(!functional_vdf_path_owner_init());
    cycle(1, early_caller); layout = 1; cycle(1, early_caller);
    const struct functional_vdf_path_snapshot applied_owner = owner();
    const struct fcam_frame_proof actual = proof();
    assert(init_calls == 1 && path_calls == 2 && applied_owner.requests == 2 && applied_owner.completed_cycles == 2 &&
        applied_owner.ap_consumed && applied_owner.model_result_bytes == 192 &&
        !memcmp(applied_owner.original_wire, layout_wire, 40) &&
        !memcmp(applied_owner.model_result, authentic_result, 192));
    struct functional_vdf_layout_stage_snapshot current = early_snapshot();
    assert(!memcmp(&staged, &current, sizeof current));
    unsigned char bank[32]; uint64_t digest = 0;
    assert(!functional_vdf_layout_stage_read_bank(staged.stage_generation, bank, sizeof bank, &digest));
    assert(!memcmp(bank, layout_wire + 8, sizeof bank) && !memcmp(bank, canonical_layout, sizeof bank) &&
        !memcmp(bank, authentic_result + FCAM_LAYOUT_R_CONFIG, sizeof bank) &&
        digest == fnv(bank, sizeof bank) && digest == staged.readback_fnv1a64 &&
        digest == u64(authentic_result + FCAM_VDF_R_INPUT_FNV));
    assert(authentic_metadata.used == 192 && authentic_metadata.required == 192 &&
        authentic_metadata.model_instance == actual.model_instance && !authentic_metadata.result_token);
    state_request(FCAM_OP_STATE, NULL, 0, before);
    for (unsigned int mismatch = 0; mismatch < 4; mismatch++) {
        unsigned char changed[192]; memcpy(changed, authentic_result, sizeof changed);
        struct fcam_bridge_result metadata = authentic_metadata;
        if (mismatch == 2) changed[FCAM_LAYOUT_R_CONFIG + 31] ^= 1;
        if (mismatch == 3) metadata.required--;
        const int rc = functional_vdf_layout_stage_bind_applied(staged.stage_generation - (mismatch == 1),
            getpid() + (mismatch == 0), instance, changed, sizeof changed, &metadata);
        assert(rc == (mismatch == 0 ? -EXDEV : mismatch == 1 ? -ESTALE : -EPROTO));
        current = early_snapshot(); assert(!memcmp(&staged, &current, sizeof current));
    }
    assert(!functional_vdf_layout_stage_bind_applied(staged.stage_generation, getpid(), instance,
        authentic_result, applied_owner.model_result_bytes, &authentic_metadata));
    current = early_snapshot();
    assert(current.applied.verified && current.applied.semantic_applied && current.applied.frame_consumed &&
        current.applied.owner_pid == getpid() && current.applied.stage_generation == 3 &&
        current.applied.model_instance == instance && current.applied.config_generation == actual.config_generation &&
        current.applied.frame_generation == actual.frame_generation && current.applied.lease_generation == actual.lease_generation &&
        current.applied.result_fnv1a64 == fnv(authentic_result, 192));
    printf("early_stage_applied stage_generation=3 instance=%016llx config=%llu frame=%llu lease=%llu "
        "input_fnv=%016llx result_fnv=%016llx source_fnv=%016llx sink_fnv=%016llx active_bytes=%llu "
        "stage_only=1 semantic_applied=0 frame_consumed=0 applied_verified=1 applied_semantic=1 applied_frame=1 "
        "bind_rejections=4 staged_bank_unchanged=1 init_calls=1 path_calls=2 capture_verified=false result192=",
        (unsigned long long)current.applied.model_instance, (unsigned long long)current.applied.config_generation,
        (unsigned long long)current.applied.frame_generation, (unsigned long long)current.applied.lease_generation,
        (unsigned long long)digest, (unsigned long long)current.applied.result_fnv1a64,
        (unsigned long long)actual.source_fnv1a64, (unsigned long long)actual.consumer_after_fnv1a64,
        (unsigned long long)actual.active_bytes);
    for (size_t i = 0; i < 192; i++) printf("%02x", authentic_result[i]);
    putchar('\n');
    current.applied = staged.applied; assert(!memcmp(&staged, &current, sizeof current));
    state_request(FCAM_OP_STATE, NULL, 0, after); const struct fcam_frame_proof last = proof();
    assert(!memcmp(before, after, sizeof before) && !memcmp(&actual, &last, sizeof last));
    assert(!early.request && !early.ack && !early.queued && !early.received &&
        early.allocations == 3 && early.sends == 3 && early.request_frees == 3 && early.ack_frees == 3);
}
static void reject_refresh_source(unsigned int source_id) {
    unsigned char before[128], after[128]; state_request(FCAM_OP_STATE, NULL, 0, before);
    const struct fcam_frame_proof previous = proof();
    const struct functional_vdf_path_snapshot old_owner = owner();
    const unsigned int calls = path_calls, inits = init_calls, allocated = allocations, sent = sends;
    const unsigned int requests_freed = request_frees, acks_freed = ack_frees;
    prepare_request(1, source_id); int rc = 999;
    assert(functional_vdf_path_dispatch(FUNCTIONAL_VDF_PATH_SID, original, &io, &guard, 1, &rc) == 1 &&
        rc == FUNCTIONAL_VDF_PATH_BLOCKED);
    const struct functional_vdf_path_snapshot current = owner();
    state_request(FCAM_OP_STATE, NULL, 0, after); const struct fcam_frame_proof last = proof();
    assert(!memcmp(&old_owner, &current, sizeof current) && !memcmp(before, after, sizeof before) &&
        !memcmp(&previous, &last, sizeof last));
    assert(path_calls == calls && init_calls == inits && allocations == allocated && sends == sent &&
        request_frees == requests_freed && ack_frees == acks_freed && !held && !allocated_ack && !queued_ack);
    assert(original && source(original) == source_id && size(original) == 8 && !memcmp(original, original_wire, 8));
    free(envelope(original)); original = NULL;
}
static void print_hex(const void *pointer, size_t bytes) {
    const unsigned char *p = pointer;
    for (size_t i = 0; i < bytes; i++) printf("%02x", p[i]);
}
static void reject_fixed_input(uint32_t op, const unsigned char *input, size_t bytes, size_t capacity, int expected) {
    unsigned char before[128], after[128], out[1192], saved[1192];
    state_request(FCAM_OP_STATE, NULL, 0, before); const struct fcam_frame_proof previous = proof();
    memset(out, 0xa5, sizeof out); memcpy(saved, out, sizeof out);
    struct fcam_exec_result r = {91, 92, 93, 94}, saved_result = r;
    assert(fcam_model_request(model, op, input, bytes, out, capacity, &r) == expected);
    assert(!memcmp(out, saved, sizeof out) && !memcmp(&r, &saved_result, sizeof r));
    state_request(FCAM_OP_STATE, NULL, 0, after); const struct fcam_frame_proof last = proof();
    assert(!memcmp(before, after, sizeof before) && !memcmp(&previous, &last, sizeof last));
}
static void reject_bb(int body_offset, unsigned char value, unsigned int sender,
    int core_rc, int guest_rc, unsigned int reaches_core) {
    unsigned char before[128], after[128]; state_request(FCAM_OP_STATE, NULL, 0, before);
    const struct fcam_frame_proof previous = proof(); const struct functional_vdf_path_snapshot old = owner();
    const unsigned int calls = path_calls, old_allocations = allocations, old_sends = sends;
    prepare_request(1, sender);
    if (body_offset >= 0) {
        assert((unsigned int)body_offset < request_bytes - 8);
        ((unsigned char *)original)[8 + body_offset] = value; canonical_bb[4 + body_offset] = value;
        memcpy(original_wire, original, request_bytes);
    }
    if (core_rc) reject_fixed_input(FCAM_OP_BB_STARTUP_CONFIG, canonical_bb, 32, 192, core_rc);
    expected_core_rc = reaches_core ? core_rc : 0; int rc = 999;
    assert(functional_vdf_path_dispatch(FUNCTIONAL_VDF_PATH_SID, original, &io, &guard, 1, &rc) == 1 && rc == guest_rc);
    expected_core_rc = 0; const struct functional_vdf_path_snapshot s = owner();
    assert(!held && !s.busy && !s.guard_held && original && !memcmp(original, original_wire, request_bytes));
    assert(path_calls == calls + reaches_core && allocations == old_allocations && sends == old_sends &&
        request_frees == old_sends && ack_frees == old_sends && !allocated_ack && !queued_ack && !received_ack);
    if (reaches_core) assert(s.faults && !s.model_complete && !s.request_owned && !s.ap_consumed &&
        s.bridge_rc == core_rc && s.validation_rc == core_rc && !s.leases[0].pointer && !s.leases[1].pointer);
    else assert(!memcmp(&s, &old, sizeof s));
    state_request(FCAM_OP_STATE, NULL, 0, after); const struct fcam_frame_proof last = proof();
    assert(!memcmp(before, after, sizeof before) && !memcmp(&previous, &last, sizeof last));
    printf("bb_refused command=%04x core_rc=%d guest_rc=%d reached_core=%u core_state_unchanged=1 proof_unchanged=1 "
        "guest_unchanged=%u ack_delta=0 lease_delta=0 AP_consumed=0\n", command(), core_rc, guest_rc, reaches_core, !reaches_core);
    free(envelope(original)); original = NULL;
}
static struct functional_histogram_snapshot histogram_owner(void) {
    struct functional_histogram_snapshot s = {0}; functional_histogram_snapshot(&s);
    assert(s.initialized && s.owner_pid == getpid() && s.functional_model && !s.ui_applied &&
        !s.continuous_histogram && !s.capture_verified && !s.physical_asic_verified &&
        !s.original_cp_fifo_verified && !s.physical_cp_rtos_verified);
    return s;
}
static void *histogram_message(unsigned int role, unsigned int bytes, unsigned int source_id) {
    struct message *m;
    if (hist.reuse && role < 2) {
        assert(!hist.arena_live); hist.arena_live = 1; m = (struct message *)hist.arena.storage;
        memset(m, 0, sizeof *m + bytes);
    } else { m = malloc(sizeof *m + bytes); assert(m); memset(m, 0, sizeof *m + bytes); }
    m->size = bytes; m->source = source_id; hist.pointer[role] = m->body;
    hist.address[role] = (uintptr_t)m->body; return m->body;
}
static int histogram_allocate(unsigned int destination, void **out, unsigned int bytes, unsigned int option) {
    const unsigned int role = ++hist.allocations; const struct functional_histogram_snapshot s = histogram_owner();
    assert(role <= 2 && destination == hist.source && option == 1 && s.leases[0].freed &&
        !s.leases[0].pointer && hist.freed[0] && !hist.pointer[0] && !s.ap_consumed);
    assert(bytes == (role == 1 ? 12u : 1034u) && !s.leases[role].pointer);
    *out = histogram_message(role, bytes, 0);
    if (hist.reuse && role == 1) assert(hist.address[0] == hist.address[1]);
    if (role == 2) {
        const uintptr_t a = hist.address[1], b = hist.address[2];
        assert(a + 12 <= b || b + 1034 <= a);
    }
    return 0;
}
static int histogram_release(unsigned int destination, void *pointer) {
    unsigned int role = 0;
    while (role < 3 && hist.pointer[role] != pointer) role++;
    assert(role < 3 && !hist.freed[role]);
    const struct functional_histogram_snapshot s = histogram_owner();
    assert(s.model_complete && !s.ap_consumed && s.leases[role].releasing && !s.leases[role].freed &&
        destination == (role ? hist.source : FUNCTIONAL_HISTOGRAM_SID));
    const unsigned int bytes = role == 2 ? 1034 : 12;
    const unsigned char *wire = role == 0 ? hist_request_wire : role == 1 ? hist_ack_wire : hist.notification;
    assert(size(pointer) == bytes && source(pointer) == (role ? FUNCTIONAL_HISTOGRAM_SID : hist.source) &&
        !memcmp(pointer, wire, bytes) && s.leases[role].wire_fnv1a64 == fnv(wire, bytes));
    hist.free_calls[role]++; assert(hist.free_calls[role] == 1);
    if (hist.fail_free == role + 1) return -EIO;
    if (hist.reuse && role < 2) { assert(hist.arena_live); hist.arena_live = 0; }
    else free(envelope(pointer));
    hist.pointer[role] = NULL; hist.freed[role] = 1; return 0;
}
static int histogram_send(unsigned int destination, void *pointer) {
    const unsigned int role = ++hist.sends; const struct functional_histogram_snapshot s = histogram_owner();
    assert(role <= 2 && destination == hist.source && pointer == hist.pointer[role] && !hist.queued[role]);
    assert(s.leases[0].freed && s.leases[role].send_inflight && !s.leases[role].queued && !s.ap_consumed);
    assert(source(pointer) == FUNCTIONAL_HISTOGRAM_SID && size(pointer) == (role == 1 ? 12u : 1034u));
    if (role == 1) assert(!memcmp(pointer, hist_ack_wire, 12));
    else {
        assert(s.leases[1].queued && !memcmp(pointer, hist.notification, 1034) &&
            !memcmp((unsigned char *)pointer + 10, hist.result + 168, 1024));
    }
    hist.queued[role] = pointer; return 0;
}
static const struct full_imaging_io histogram_io = {
    histogram_allocate, histogram_release, set_source, histogram_send, size, source, NULL
};
static int histogram_receive(unsigned int role, void **pointer) {
    assert(role == 1 || role == 2);
    assert(hist.queued[role] && hist.queued[role] == hist.pointer[role]);
    *pointer = hist.queued[role]; hist.queued[role] = NULL; return 0;
}
static void *histogram_receiver(void *argument) {
    const unsigned int role = *(const unsigned int *)argument; void *pointer = NULL;
    assert(!histogram_receive(role, &pointer));
    assert(functional_histogram_observe_receive_cycle(hist.source, pointer, source(pointer), size(pointer),
        &hist.tickets[role]) == 1 && hist.tickets[role] == 1);
    if (role == 2 && !hist.no_notification_free) {
        int rc = 999;
        assert(functional_histogram_release_cycle(hist.source, pointer, hist.tickets[role], histogram_release,
            NULL, &rc) == 1 && rc == (hist.fail_free == 3 ? -EIO : 0));
    }
    return NULL;
}
static uint64_t reference_histogram(const unsigned char state[128], uint64_t frame_number) {
    const size_t bytes = (size_t)u32(state + 8) * u32(state + 12) * 3;
    assert(bytes == 921600); unsigned char *rgb = malloc(bytes); assert(rgb);
    const optics_params parameters = {(double)u32(state + 24) / 100.0,
        u64(state + 40) == UINT64_MAX ? INFINITY : (double)u64(state + 40) / 1000000.0,
        (double)u64(state + 32) / 1000000.0, u32(state + 28)};
    optics_metadata metadata = {0}; optics_stats stats = {0};
    assert(!optics_render(&parameters, 640, 480, 1920, rgb, bytes, frame_number, &metadata, &stats) && stats.completed_frames == 1);
    assert(metadata.pixel_fnv1a == fnv(rgb, bytes));
    /* Independent channel-major reference, tied to the actual Core source proof hash. */
    for (unsigned int channel = 0; channel < 4; channel++) {
        unsigned int counts[256] = {0}, peak = 0;
        for (size_t pixel = 0; pixel < bytes; pixel += 3) {
            const unsigned int value = channel ? rgb[pixel + channel - 1] :
                (77u * rgb[pixel] + 150u * rgb[pixel + 1] + 29u * rgb[pixel + 2] + 128u) / 256u;
            counts[value]++; if (counts[value] > peak) peak = counts[value];
        }
        assert(peak);
        for (size_t bin = 0; bin < 256; bin++)
            hist.expected_bins[channel * 256 + bin] = (unsigned char)((counts[bin] * 255u + peak / 2u) / peak);
    }
    const uint64_t hash = metadata.pixel_fnv1a; free(rgb); return hash;
}
static void histogram_finish(void) {
    const struct functional_histogram_snapshot s = histogram_owner();
    unsigned int retained = 0, cleaned = 0;
    for (unsigned int role = 0; role < 3; role++) {
        assert(s.leases[role].pointer == hist.pointer[role]);
        if (s.leases[role].pointer) { retained++; assert(!s.leases[role].freed); }
        assert(!hist.free_calls[role] || hist.free_calls[role] == 1);
    }
    printf("histogram_lifetimes allocations=%u sends=%u request_free_calls=%u ack_free_calls=%u notification_free_calls=%u "
        "request_freed=%u ack_freed=%u notification_freed=%u retained_leases=%u AP_consumed=%u faults=%u "
        "ticket_ack=%llu ticket_notification=%llu request_ack_same_address=%u\n",
        hist.allocations, hist.sends, hist.free_calls[0], hist.free_calls[1], hist.free_calls[2],
        s.leases[0].freed, s.leases[1].freed, s.leases[2].freed, retained, s.ap_consumed, s.faults,
        (unsigned long long)hist.tickets[1], (unsigned long long)hist.tickets[2],
        hist.address[0] && hist.address[0] == hist.address[1]);
    for (unsigned int role = 0; role < 3; role++) if (hist.pointer[role]) {
        if (hist.reuse && role < 2) { assert(hist.arena_live); hist.arena_live = 0; }
        else free(envelope(hist.pointer[role]));
        hist.pointer[role] = hist.queued[role] = NULL; cleaned++;
    }
    assert(cleaned == retained && !hist.arena_live);
    printf("histogram_cleanup retained_allocations_explicitly_destroyed=%u owner_consumption_unchanged=%u\n", cleaned, s.ap_consumed);
}
static void histogram_flow(const char *scenario) {
    const int no_queue = !strcmp(scenario, "hist-no-queue"), wrong_source = !strcmp(scenario, "hist-wrong-source");
    const int no_route = !strcmp(scenario, "hist-no-route"), busy = !strcmp(scenario, "hist-core-busy");
    hist.source = !strcmp(scenario, "hist-arbitrary-queue") ? UINT32_C(0x7351a2b7) : UINT32_C(0x8094a2b7);
    hist.reuse = !strcmp(scenario, "hist-address-reuse");
    hist.fail_free = !strcmp(scenario, "hist-request-free-fail") ? 1u : !strcmp(scenario, "hist-ack-free-fail") ? 2u :
        !strcmp(scenario, "hist-notification-free-fail") ? 3u : 0u;
    hist.no_notification_free = !strcmp(scenario, "hist-no-notification-free");
    assert(!functional_histogram_owner_init());
    const struct functional_vdf_path_snapshot vdf_before = owner();
    unsigned char before_bind[128], after_bind[128]; state_request(FCAM_OP_STATE, NULL, 0, before_bind);
    const struct fcam_frame_proof bind_proof = proof();
    if (!no_queue) {
        assert(!functional_histogram_bind_queue(hist.source) && !functional_histogram_bind_queue(hist.source));
        assert(functional_histogram_bind_queue(hist.source + 1) == -ESTALE);
    }
    state_request(FCAM_OP_STATE, NULL, 0, after_bind); const struct fcam_frame_proof bound_proof = proof();
    assert(!memcmp(before_bind, after_bind, 128) && !memcmp(&bind_proof, &bound_proof, sizeof bind_proof));
    const struct functional_histogram_snapshot before_owner = histogram_owner();
    unsigned char *request = histogram_message(0, 12, hist.source + wrong_source);
    memcpy(request, hist_request_wire, 12);
    const int mode0 = !strcmp(scenario, "hist-mode0"), disabled = !strcmp(scenario, "hist-disable");
    if (mode0) request[9] = 0;
    if (disabled) request[8] = 0;
    unsigned char before[128], after[128]; state_request(FCAM_OP_STATE, NULL, 0, before);
    const struct fcam_frame_proof previous = proof();
    const unsigned int typed_refusal = no_queue || wrong_source || mode0 || disabled;
    uint64_t reference_hash = 0;
    if (!no_route && !busy && !typed_refusal) reference_hash = reference_histogram(before, previous.lease_generation + 1);
    memcpy(hist.notification, hist_header, 10); memcpy(hist.notification + 10, hist.expected_bins, 1024);
    if (!strcmp(scenario, "hist-small-capacity")) {
        reject_fixed_input(FCAM_OP_HISTOGRAM, hist_input, 8, 1191, -ENOSPC);
        const struct functional_histogram_snapshot unchanged = histogram_owner();
        assert(!memcmp(&before_owner, &unchanged, sizeof unchanged));
        printf("histogram_refused reason=capacity core_rc=%d core_state_unchanged=1 proof_unchanged=1 ack_delta=0 AP_consumed=0\n", -ENOSPC);
        free(envelope(hist.pointer[0])); hist.pointer[0] = NULL; hist.address[0] = 0; return;
    }
    if (!strcmp(scenario, "hist-result-canonical")) corrupt_result = 2;
    if (!strcmp(scenario, "hist-result-class")) corrupt_result = 9;
    expected_core_rc = no_route ? -ENODATA : busy ? -EBUSY : 0;
    if (expected_core_rc) reject_fixed_input(FCAM_OP_HISTOGRAM, hist_input, 8, 1192, expected_core_rc);
    int rc = 999;
    assert(functional_histogram_dispatch(FUNCTIONAL_HISTOGRAM_SID, request, &histogram_io, &guard, 1, &rc) == 1);
    expected_core_rc = 0;
    struct functional_histogram_snapshot s = histogram_owner();
    assert(!held && !s.busy && !s.guard_held && !s.ap_consumed);
    if (typed_refusal || no_route || busy) {
        assert(rc == (no_queue ? -ENODATA : wrong_source ? -EPERM : mode0 || disabled ? -ENOTSUP : no_route ? -ENODATA : -EBUSY));
        assert(!hist.allocations && !hist.sends && !hist.free_calls[0] && !s.request_owned && !s.requests && !s.model_complete);
        assert(!s.leases[0].pointer && !s.leases[1].pointer && !s.leases[2].pointer);
        if (typed_refusal) assert(!hist.calls && !memcmp(&s, &before_owner, sizeof s));
        else assert(hist.calls == 1 && s.faults && s.bridge_rc == rc && s.validation_rc == rc);
        state_request(FCAM_OP_STATE, NULL, 0, after); const struct fcam_frame_proof last = proof();
        assert(!memcmp(before, after, 128) && !memcmp(&previous, &last, sizeof last));
        assert(size(request) == 12 && source(request) == hist.source + wrong_source);
        printf("histogram_refused reason=%s guest_rc=%d reached_core=%u core_state_unchanged=1 proof_unchanged=1 "
            "ack_delta=0 lease_delta=0 AP_consumed=0\n", scenario, rc, hist.calls);
        free(envelope(request)); hist.pointer[0] = NULL; return;
    }
    assert(hist.calls == 1 && hist.metadata.used == 1192 && hist.metadata.required == 1192 &&
        hist.metadata.model_instance == instance && !hist.metadata.result_token && hist.core_proof.source_fnv1a64 == reference_hash);
    check_fixed_core(before, &previous, FCAM_OP_HISTOGRAM, hist_input, 8, hist.result, 1192, 6);
    if (corrupt_result) {
        unsigned char changed[1192]; memcpy(changed, hist.result, 1192);
        changed[corrupt_result == 2 ? 167 : 96] ^= 1;
        assert(rc == -EPROTO && s.validation_rc == -EPROTO && !s.bridge_rc && s.faults && !s.model_complete &&
            !s.request_owned && !s.requests && !hist.allocations && !hist.sends && !hist.free_calls[0] &&
            !memcmp(s.model_result, changed, 1192) && !s.leases[0].pointer && !s.leases[1].pointer && !s.leases[2].pointer);
        printf("histogram_refused reason=%s guest_rc=%d real_core_commits=1 real_core_frame_consumed=1 "
            "ack_delta=0 lease_delta=0 AP_consumed=0\n", scenario, rc);
        free(envelope(request)); hist.pointer[0] = NULL; return;
    }
    assert(!rc && s.model_complete && s.request_owned && s.requests == 1 && s.cycle == 1 &&
        !memcmp(s.model_result, hist.result, 1192) && s.model_result_fnv1a64 == fnv(hist.result, 1192) &&
        !memcmp(s.original_wire, hist_request_wire, 12) && !memcmp(s.canonical8, hist_input, 8) &&
        s.origin.source == hist.source && s.origin.command == 0x0148 && s.origin.bytes == 12 &&
        s.origin.wire_fnv1a64 == fnv(hist_request_wire, 12) && s.queue_bound && s.queue_source == hist.source &&
        s.model_instance == instance && s.config_generation == hist.core_proof.config_generation &&
        s.frame_generation == hist.core_proof.frame_generation && s.lease_generation == hist.core_proof.lease_generation);
    assert(s.notification_selector == 1 && !memcmp(s.notification_wire, hist.notification, 1034) &&
        s.notification_fnv1a64 == fnv(hist.notification, 1034));
    for (unsigned int channel = 0; channel < 4; channel++)
        assert(s.channel_fnv1a64[channel] == fnv(hist.expected_bins + channel * 256, 256));
    const struct functional_vdf_path_snapshot vdf_after = owner();
    assert(!memcmp(&vdf_before, &vdf_after, sizeof vdf_before));
    printf("histogram1192 config=%llu frame=%llu proof_serial=%llu proof_kind=6 class=6 active_bytes=%llu "
        "rendered=%llu consumed=%llu retired=%llu "
        "source_fnv=%016llx sink_fnv=%016llx reference_fnv=%016llx result_fnv=%016llx notification_fnv=%016llx "
        "Y_fnv=%016llx R_fnv=%016llx G_fnv=%016llx B_fnv=%016llx selector=1 queue_source=%08x "
        "full_result_verified=1 full_notification_verified=1 request_wire=",
        (unsigned long long)s.config_generation, (unsigned long long)s.frame_generation,
        (unsigned long long)hist.core_proof.serial, (unsigned long long)hist.core_proof.active_bytes,
        (unsigned long long)hist.core_proof.after.rendered, (unsigned long long)hist.core_proof.after.consumed,
        (unsigned long long)hist.core_proof.after.retired,
        (unsigned long long)hist.core_proof.source_fnv1a64, (unsigned long long)hist.core_proof.consumer_after_fnv1a64,
        (unsigned long long)reference_hash, (unsigned long long)s.model_result_fnv1a64,
        (unsigned long long)s.notification_fnv1a64, (unsigned long long)s.channel_fnv1a64[0],
        (unsigned long long)s.channel_fnv1a64[1], (unsigned long long)s.channel_fnv1a64[2],
        (unsigned long long)s.channel_fnv1a64[3], hist.source);
    print_hex(hist_request_wire, 12); printf(" canonical8="); print_hex(hist_input, 8);
    printf(" ack_wire="); print_hex(hist_ack_wire, 12); printf(" result1192="); print_hex(hist.result, 1192);
    printf(" notification1034="); print_hex(hist.notification, 1034); putchar('\n');
    if (hist.fail_free == 1) {
        assert(s.faults && !hist.allocations && !hist.sends && hist.pointer[0] && !s.leases[0].freed);
        int again = 999;
        assert(functional_histogram_release_cycle(FUNCTIONAL_HISTOGRAM_SID, hist.pointer[0], 1,
            histogram_release, NULL, &again) == 1 && again == -EIO && hist.free_calls[0] == 1);
        histogram_finish(); return;
    }
    assert(!s.faults && hist.allocations == 2 && hist.sends == 2 && hist.freed[0] &&
        !hist.pointer[0] && !s.leases[1].received && !s.leases[2].received);
    if (!strcmp(scenario, "hist-no-receive") || !strcmp(scenario, "hist-free-before-receive")) {
        if (!strcmp(scenario, "hist-free-before-receive")) {
            int free_rc = 999;
            assert(functional_histogram_release_cycle(hist.source, hist.pointer[1], 1, histogram_release,
                NULL, &free_rc) == 1 && free_rc == -EPROTO && !hist.free_calls[1]);
        }
        histogram_finish(); return;
    }
    pthread_t receivers[2]; unsigned int roles[2] = {1, 2};
    assert(!pthread_create(&receivers[0], NULL, histogram_receiver, &roles[0]));
    if (hist.fail_free == 3) assert(!pthread_join(receivers[0], NULL));
    assert(!pthread_create(&receivers[1], NULL, histogram_receiver, &roles[1]));
    if (hist.fail_free != 3) assert(!pthread_join(receivers[0], NULL));
    assert(!pthread_join(receivers[1], NULL));
    s = histogram_owner(); assert(hist.tickets[1] == 1 && hist.tickets[2] == 1 && !s.ap_consumed);
    assert(s.leases[1].receiver_tid != s.leases[1].sender_tid && s.leases[1].sender_tid == syscall(SYS_gettid));
    if (hist.fail_free == 3) {
        assert(s.faults && hist.free_calls[2] == 1 && s.leases[2].pointer && !s.notification_consumed);
        histogram_finish(); return;
    }
    int free_rc = 999;
    assert(functional_histogram_release_cycle(hist.source, hist.pointer[1], hist.tickets[1] + 1,
        histogram_release, NULL, &free_rc) == 1 && free_rc == -ESTALE && !hist.free_calls[1]);
    const uintptr_t ack_address = hist.address[1];
    assert(functional_histogram_release_cycle(hist.source, hist.pointer[1], hist.tickets[1], histogram_release,
        NULL, &free_rc) == 1 && free_rc == (hist.fail_free == 2 ? -EIO : 0));
    s = histogram_owner();
    assert(s.ap_consumed == (unsigned int)(!hist.fail_free && !hist.no_notification_free));
    assert(s.leases[1].free_tid == s.leases[1].sender_tid && s.leases[1].free_tid != s.leases[1].receiver_tid);
    if (!hist.no_notification_free) assert(s.leases[2].free_tid == s.leases[2].receiver_tid &&
        s.leases[2].receiver_tid != s.leases[2].sender_tid && s.notification_consumed);
    if (hist.fail_free == 2) {
        assert(s.faults && s.leases[1].pointer && !s.ack_consumed);
        assert(functional_histogram_release_cycle(hist.source, hist.pointer[1], hist.tickets[1], histogram_release,
            NULL, &free_rc) == 1 && free_rc == -EIO && hist.free_calls[1] == 1);
    } else {
        free_rc = 999;
        assert(!functional_histogram_release_cycle(hist.source, (void *)ack_address, hist.tickets[1],
            histogram_release, NULL, &free_rc) && free_rc == 999 && hist.free_calls[1] == 1);
    }
    printf("histogram_threads immutable_cycle=1 ACK_receive_foreign=1 ACK_free_original_sender=1 "
        "notification_free_actual_receiver=%u no_snapshot_ticket_lookup=1 stale_ticket_rejected=1\n", !hist.no_notification_free);
    if (!strcmp(scenario, "hist-reenable")) {
        assert(s.ap_consumed);
        unsigned char state_before[128], state_after[128]; state_request(FCAM_OP_STATE, NULL, 0, state_before);
        const struct fcam_frame_proof old_proof = proof();
        for (unsigned int mutation = 0; mutation < 3; mutation++) {
            void *next = message(12, hist.source); memcpy(next, hist_request_wire, 12);
            if (mutation == 1) ((unsigned char *)next)[8] = 0;
            if (mutation == 2) ((unsigned char *)next)[9] = 0;
            int next_rc = 999;
            assert(functional_histogram_dispatch(FUNCTIONAL_HISTOGRAM_SID, next, &histogram_io, &guard, 1,
                &next_rc) == 1 && next_rc == (mutation ? -ENOTSUP : -EALREADY));
            free(envelope(next));
        }
        state_request(FCAM_OP_STATE, NULL, 0, state_after); const struct fcam_frame_proof new_proof = proof();
        const struct functional_histogram_snapshot unchanged = histogram_owner();
        assert(!memcmp(state_before, state_after, 128) && !memcmp(&old_proof, &new_proof, sizeof old_proof) &&
            !memcmp(&s, &unchanged, sizeof s) && hist.calls == 1 && hist.allocations == 2 && hist.sends == 2);
        puts("histogram_second_request reenable_disable_mode0_rejections=3 core_state_unchanged=1 proof_unchanged=1 extra_ACK=0");
    }
    histogram_finish();
}
static void mixed_startup(void) {
    assert(!functional_vdf_path_owner_init()); cycle(1, UINT32_C(0x81cf0123));
    zebra = 1; cycle(1, UINT32_C(0x81cf4567)); zebra = 0;
    layout = 1; cycle(1, UINT32_C(0x81cf89ab)); layout = 0;
    display = 1; cycle(1, UINT32_C(0x81cf0152)); display = 2; cycle(1, UINT32_C(0x81cf0162));
    assert(!functional_vdf_path_bind_refresh_queue(UINT32_C(0x8094a2b7)));
    display = 3; cycle(1, UINT32_C(0x8094a2b7)); display = 0;
    for (bb = 1; bb <= 5; bb++) cycle(1, UINT32_C(0x81cf1200) + bb);
    bb = 0;
}
static void bb_hist_sequence(const char *scenario) {
    const int histogram_case = !strncmp(scenario, "hist-", 5);
    if (!strcmp(scenario, "bb-no-route") || !strcmp(scenario, "hist-no-route")) {
        assert(!functional_vdf_path_owner_init());
        if (histogram_case) histogram_flow(scenario);
        else { bb = 1; reject_bb(-1, 0, UINT32_C(0x81cf0111), -ENODATA, -ENODATA, 0); }
        return;
    }
    mixed_startup();
    if (histogram_case) { histogram_flow(scenario); return; }
    if (!strcmp(scenario, "bb-repeated-banks")) {
        bb_variant = 1;
        for (bb = 1; bb <= 5; bb++) cycle(1, UINT32_C(0x81cf2200) + bb);
        bb_variant = 0; bb = 0;
    } else if (!strcmp(scenario, "bb-sq-enabled")) {
        bb = 1; reject_bb(4, 1, UINT32_C(0x81cf0111), -ENOTSUP, -EINVAL, 0);
    } else if (!strcmp(scenario, "bb-look-nonneutral")) {
        bb = 2; reject_bb(2, 1, UINT32_C(0x81cf0166), -ENOTSUP, -EINVAL, 0);
    } else if (!strcmp(scenario, "bb-input-domain")) {
        bb = 3; reject_bb(0, 2, UINT32_C(0x81cf0167), -ENOTSUP, -EINVAL, 0);
    } else if (!strcmp(scenario, "bb-gain-nonzero")) {
        bb = 4; reject_bb(0, 1, UINT32_C(0x81cf015f), -ENOTSUP, -EINVAL, 0);
    } else if (!strcmp(scenario, "bb-interval-enabled")) {
        bb = 5; reject_bb(0, 1, UINT32_C(0x81cf0128), -ENOTSUP, -EINVAL, 0);
    } else if (!strcmp(scenario, "bb-wrong-source")) {
        bb = 1; reject_bb(-1, 0, UINT32_C(0x8094a2b7), 0, -ENODATA, 0);
    } else if (!strcmp(scenario, "bb-small-capacity")) {
        reject_fixed_input(FCAM_OP_BB_STARTUP_CONFIG, bb_inputs[0], 32, 191, -ENOSPC);
        puts("bb_refused reason=capacity core_state_unchanged=1 proof_unchanged=1 ack_delta=0 lease_delta=0 AP_consumed=0");
    } else if (!strcmp(scenario, "bb-no-frame")) {
        configure(96, 64); bb = 1; reject_bb(-1, 0, UINT32_C(0x81cf0111), -ENOTSUP, -ENOTSUP, 1);
    } else if (!strcmp(scenario, "bb-result-canonical") || !strcmp(scenario, "bb-result-class")) {
        bb = 1; corrupt_result = !strcmp(scenario, "bb-result-class") ? 9 : 2; corrupt_tail = 31;
        cycle(1, UINT32_C(0x81cf0111));
    } else if (!strcmp(scenario, "bb-pending-jpeg") || !strcmp(scenario, "bb-active-video")) {
        const int jpeg = !strcmp(scenario, "bb-pending-jpeg");
        unsigned char out[128], input[48] = {0}; struct fcam_exec_result r = {0};
        if (jpeg) {
            put32(input, FCAM_STILL_FULL_JPEG); put32(input + 4, 96); put32(input + 8, 64); put32(input + 12, 90);
            assert(!fcam_model_request(model, FCAM_OP_STILL, input, 16, out, sizeof out, &r) && r.token && r.total > r.used);
        } else {
            unsigned char state[128]; state_request(FCAM_OP_STATE, NULL, 0, state);
            memcpy(input, state + 8, 40);
            assert(!fcam_model_request(model, FCAM_OP_VIDEO_BEGIN, input, 48, out, sizeof out, &r) && r.used == 128);
        }
        bb = 1; reject_bb(-1, 0, UINT32_C(0x81cf0111), -EBUSY, -EBUSY, 1); bb = 0;
        histogram_flow("hist-core-busy");
        state_request(FCAM_OP_CANCEL, NULL, 0, out);
        printf("pipeline_busy reason=%s BB_and_histogram_refused=1 pending_work_preserved=1 media_disk_writes=0\n", scenario);
    } else assert(!strcmp(scenario, "bb-observed-initial") || !strcmp(scenario, "bb-mixed") || !strcmp(scenario, "bb-mixed-address-reuse") ||
        !strcmp(scenario, "bb-fresh-request-lease"));
    unsigned char final[128]; state_request(FCAM_OP_STATE, NULL, 0, final);
    printf("bb_sequence config=%llu frame=%llu rendered=%llu consumed=%llu retired=%llu proof_serial=%llu "
        "requests=%u completed_cycles=%u model_instance=%016llx capture_verified=false\n",
        (unsigned long long)u64(final + 56), (unsigned long long)u64(final + 112),
        (unsigned long long)u64(final + 64), (unsigned long long)u64(final + 72),
        (unsigned long long)proof().after.retired, (unsigned long long)proof().serial,
        owner().requests, owner().completed_cycles, (unsigned long long)proof().model_instance);
}
int main(int argc, char **argv) {
    assert(argc == 2);
    const int sequence = !strcmp(argv[1], "disable-enable");
    const int mixed = !strcmp(argv[1], "zebra-mixed"), bad_zebra = !strcmp(argv[1], "corrupt-zebra");
    corrupt_result = !strcmp(argv[1], "corrupt-result");
    const int layout_case = !strncmp(argv[1], "layout-", 7), display_case = !strncmp(argv[1], "display-", 8);
    const int refresh_case = !strcmp(argv[1], "refresh-global-queue") || !strcmp(argv[1], "refresh-legacy-queue");
    early_stage_case = !strcmp(argv[1], "early-stage-real-layout");
    const int bb_hist_case = !strncmp(argv[1], "bb-", 3) || !strncmp(argv[1], "hist-", 5);
    bb_observed_initial = !strcmp(argv[1], "bb-observed-initial");
    reuse_ack = !strcmp(argv[1], "layout-mixed-address-reuse") || !strcmp(argv[1], "display-mixed-address-reuse") ||
        !strcmp(argv[1], "bb-mixed-address-reuse");
    fresh_request_lease = !strcmp(argv[1], "layout-fresh-request-lease") || !strcmp(argv[1], "display-fresh-request-lease") ||
        !strcmp(argv[1], "bb-fresh-request-lease");
    assert(sequence || mixed || bad_zebra || corrupt_result || layout_case || display_case || refresh_case || early_stage_case || bb_hist_case || !strcmp(argv[1], "enabled-opaque"));
    model = fcam_model_create(instance); assert(model);
    assert(!proof().serial);
    unsigned char initial[128]; state_request(FCAM_OP_INIT, NULL, 0, initial);
    assert(u64(initial + FCAM_S_RENDERED) == 1 && u64(initial + FCAM_S_FRAME_GENERATION) == 1);
    assert(!u64(initial + FCAM_S_CONSUMED) && proof().serial == 1 && proof().after.retired == 1);
    if (bb_hist_case) { bb_hist_sequence(argv[1]); goto done; }
    if (early_stage_case) { early_stage_sequence(); goto done; }
    if (layout_case) { layout_sequence(argv[1]); goto done; }
    if (display_case) { display_sequence(argv[1]); goto done; }
    if (refresh_case) {
        const unsigned int global_source = !strcmp(argv[1], "refresh-global-queue") ?
            UINT32_C(0x80946189) : UINT32_C(0x81cf0012);
        assert(!functional_vdf_path_owner_init());
        cycle(1, UINT32_C(0x81cf0123)); display = 3;
        reject_refresh_source(UINT32_C(0x80946189)); reject_refresh_source(UINT32_C(0x81cf0012));
        unsigned char before_bind[128], after_bind[128]; state_request(FCAM_OP_STATE, NULL, 0, before_bind);
        const struct fcam_frame_proof before_proof = proof();
        const struct functional_vdf_path_snapshot before_owner = owner();
        /* Trusted fixture identity only; production call-site/global reads are the parent's contract. */
        assert(!functional_vdf_path_bind_refresh_queue(global_source));
        assert(!functional_vdf_path_bind_refresh_queue(global_source));
        assert(functional_vdf_path_bind_refresh_queue(global_source + 1) == -ESTALE);
        struct functional_vdf_path_snapshot bound_owner = owner();
        assert(bound_owner.refresh_queue_bound && bound_owner.refresh_queue_source == global_source);
        bound_owner.refresh_queue_bound = before_owner.refresh_queue_bound;
        bound_owner.refresh_queue_source = before_owner.refresh_queue_source;
        assert(!memcmp(&before_owner, &bound_owner, sizeof bound_owner));
        state_request(FCAM_OP_STATE, NULL, 0, after_bind); const struct fcam_frame_proof after_proof = proof();
        assert(!memcmp(before_bind, after_bind, sizeof before_bind) && !memcmp(&before_proof, &after_proof, sizeof before_proof));
        reject_refresh_source(0); reject_refresh_source(global_source + 1);
        reject_refresh_source(global_source == UINT32_C(0x80946189) ? UINT32_C(0x81cf0012) : UINT32_C(0x80946189));
        cycle(1, global_source); cycle(1, global_source);
        unsigned char final[128]; state_request(FCAM_OP_STATE, NULL, 0, final);
        assert(u64(final + FCAM_S_GENERATION) == 4 && u64(final + FCAM_S_RENDERED) == 4 &&
            u64(final + FCAM_S_FRAME_GENERATION) == 4 && u64(final + FCAM_S_CONSUMED) == 3);
        printf("refresh global_D_reused=1 paired_wait_delayed_by_INIT=1 config=4 rendered=4 consumed=3 "
            "refresh_queue_bound=1 refresh_queue_source=%08x unbound_rejections=2 bound_source_rejections=3 "
            "bind_core_state_unchanged=1 bind_proof_unchanged=1\n", global_source);
        repeated_init(); goto done;
    }
    configure(128, 64); repeated_init();
    assert(!functional_vdf_path_owner_init());
    cycle(1, UINT32_C(0x81cf0123));
    if (mixed || bad_zebra) {
        zebra = 1; corrupt_result = bad_zebra; cycle(1, UINT32_C(0x81cf4567));
        if (mixed) {
            zebra = 0; cycle(0, UINT32_C(0x81cf89ab));
            zebra = 1; cycle(0, UINT32_C(0x81cf0123));
            zebra = 0; cycle(1, UINT32_C(0x81cf4567));
            zebra = 1; cycle(1, UINT32_C(0x81cf89ab)); cycle(1, UINT32_C(0x81cf0123));
        }
    } else if (sequence) {
        /* An independent operation may advance config generation between owner cycles. */
        configure(96, 64);
        cycle(0, UINT32_C(0x81cf4567));
        cycle(1, UINT32_C(0x81cf89ab));
    } else if (!corrupt_result) {
        configure(96, 64);
        cycle(1, UINT32_C(0x81cf89ab));
    }
done:
    assert(!original && !allocated_ack && !queued_ack && !received_ack);
    assert(allocations == sends && request_frees == allocations && ack_frees == allocations);
    assert(!arena_live && arena_allocations == arena_frees);
    if (fresh_request_lease) assert(retired_request_reuses >= (bb_hist_case ? 9u : display_case ? 3u : 1u) &&
        arena_allocations == (bb_hist_case ? 18u : display_case ? 6u : 2u));
    printf("allocation_lifetimes allocations=%u request_frees=%u ack_frees=%u retired_request_reuses=%u arena_allocations=%u arena_frees=%u\n",
        allocations, request_frees, ack_frees, retired_request_reuses, arena_allocations, arena_frees);
    free(recycled_ack); recycled_ack = NULL;
    fcam_model_destroy(model);
    puts("component-only real core + guest owner; capture_verified=false; original AP/VM/mailbox/RSP unverified");
    return 0;
}
