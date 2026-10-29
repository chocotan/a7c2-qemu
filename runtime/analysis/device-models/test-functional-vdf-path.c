/* SPDX-License-Identifier: MIT */
#define _GNU_SOURCE
#ifndef HOST_TEST
#error HOST_TEST mock bridge: owner-only evidence, never production or CMOS proof.
#endif
#include "functional-vdf-path.h"
#include <assert.h>
#include <limits.h>
#include <pthread.h>
#include <stddef.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/wait.h>
#include <unistd.h>

/* Public OSAL payload header layout; these are real independent host allocations. */
struct message { void *next; unsigned int flags, source, size, reserved; unsigned char body[]; };
_Static_assert(offsetof(struct message, body) == 24, "OSAL public 24B envelope");
static struct message *live[32], *recycled;
static union { max_align_t alignment; unsigned char storage[24 + FUNCTIONAL_VDF_MAX_REQUEST_BYTES]; } arena;
static unsigned int arena_live, arena_allocations, arena_frees, use_arena, fresh_request_lease;
extern const void *functional_vdf_path_test_constant_address(unsigned int);
static const char *scenario;
static unsigned int allocations, sends, frees, request_frees, ack_frees, reservations, unlocks, ready_calls;
static unsigned int init_calls, path_calls, logs, reentry;
static uint64_t model_config = 7, model_frame = 2, model_lease = 2, receive_ticket;
static void *active_request, *ack_pointer, *reentrant_request;
static unsigned char saved_wire[FUNCTIONAL_VDF_MAX_REQUEST_BYTES], model_route[FCAM_VDF_INPUT_BYTES] = {0, 1, 1};
static unsigned int saved_bytes = 24, saved_source = UINT32_C(0x81cf61c4);
static unsigned int refresh_source = UINT32_C(0x80946189);
static const unsigned int bb_commands[FCAM_BB_FEATURES] = {0x0111, 0x0166, 0x0167, 0x015f, 0x0128};
static const unsigned int bb_bodies[FCAM_BB_FEATURES] = {28, 28, 2, 4, 12};
static unsigned char model_bb[FCAM_BB_FEATURES][FCAM_BB_INPUT_BYTES];
static unsigned int model_bb_valid[FCAM_BB_FEATURES];
static int observed_initial;
static const unsigned char bb_success[FCAM_BB_FEATURES][12] = {
    {0x0d, 0x20, 0x11, 0x11, 12, 0, 1, 0x80, 0, 0, 0, 0},
    {0x0d, 0x20, 0x66, 0x11, 12, 0, 1, 0x80, 0, 0, 0, 0},
    {0x0d, 0x20, 0x67, 0x11, 12, 0, 1, 0x80, 0, 0, 0, 0},
    {0x0d, 0x20, 0x5f, 0x11, 12, 0, 1, 0x80, 0, 0, 0, 0},
    {0x0d, 0x20, 0x28, 0x11, 12, 0, 1, 0x80, 0, 0, 0, 0}
};
static int bb_index(unsigned int command) {
    for (unsigned int i = 0; i < FCAM_BB_FEATURES; i++) if (bb_commands[i] == command) return (int)i;
    return -1;
}
static const unsigned char path_success[12] = {0x0d, 0x20, 0x38, 0x11, 12, 0, 1, 0x80, 0, 0, 0x59, 0};
static const unsigned char zebra_success[12] = {0x0d, 0x20, 0x53, 0x11, 12, 0, 1, 0x80, 0, 0, 0, 0};
static const unsigned char layout_success[12] = {0x0d, 0x20, 0x4c, 0x11, 12, 0, 1, 0x80, 0, 0, 0x59, 0};
static const unsigned char peaking_success[12] = {0x0d, 0x20, 0x52, 0x11, 12, 0, 1, 0x80, 0, 0, 0x59, 0};
static const unsigned char flag_success[12] = {0x0d, 0x20, 0x62, 0x11, 12, 0, 1, 0x80, 0, 0, 0x59, 0};
static const unsigned char refresh_success[12] = {0x0d, 0x20, 0x41, 0x11, 12, 0, 1, 0x80, 0, 0, 0x59, 0};
#define success_wire (bb_index(0x0100u | saved_wire[2]) >= 0 ? bb_success[bb_index(0x0100u | saved_wire[2])] : \
    saved_wire[2] == 0x41 ? refresh_success : saved_wire[2] == 0x52 ? peaking_success : saved_wire[2] == 0x62 ? flag_success : \
    saved_wire[2] == 0x4c ? layout_success : saved_wire[2] == 0x53 ? zebra_success : path_success)
static const struct full_imaging_io io;
static const struct native_cp_state_publication_guard guard;
static int is(const char *s) { return !strcmp(scenario, s); }
static int starts(const char *s) { return !strncmp(scenario, s, strlen(s)); }
static struct message *envelope(void *p) { return (struct message *)((unsigned char *)p - offsetof(struct message, body)); }
static uint32_t u32(const unsigned char *p) { return p[0] | (uint32_t)p[1] << 8 | (uint32_t)p[2] << 16 | (uint32_t)p[3] << 24; }
static uint64_t u64(const unsigned char *p) { return u32(p) | (uint64_t)u32(p + 4) << 32; }
static void put32(unsigned char *p, uint32_t v) { for (unsigned int i = 0; i < 4; i++) p[i] = (unsigned char)(v >> (i * 8)); }
static void put64(unsigned char *p, uint64_t v) { put32(p, (uint32_t)v); put32(p + 4, (uint32_t)(v >> 32)); }
static uint64_t fnv(const void *pointer, size_t bytes) {
    const unsigned char *p = pointer; uint64_t h = UINT64_C(14695981039346656037);
    for (size_t i = 0; i < bytes; i++) h = (h ^ p[i]) * UINT64_C(1099511628211);
    return h;
}
static struct functional_vdf_path_snapshot snapshot(void) {
    struct functional_vdf_path_snapshot s; functional_vdf_path_snapshot(&s);
    assert(s.owner_pid == getpid() && s.initialized && s.functional_model);
    assert(!s.capture_verified && !s.physical_asic_verified && !s.physical_cp_rtos_verified &&
        !s.original_cp_fifo_verified && !s.original_selector_verified);
    return s;
}
static void inspect(void) {
    const struct functional_vdf_path_snapshot s = snapshot();
    if (starts("bind-busy") && s.busy) {
        assert(functional_vdf_path_bind_refresh_queue(UINT32_C(0x80946189)) == -EBUSY);
        const struct functional_vdf_path_snapshot after = snapshot();
        assert(!memcmp(&s, &after, sizeof s));
    }
    if (is("reentrant-dispatch") && !reentry && reentrant_request && (s.busy || (s.requests && !s.ap_consumed))) {
        int rc = 321; reentry = 1;
        assert(functional_vdf_path_dispatch(FUNCTIONAL_VDF_PATH_SID, reentrant_request, &io, &guard, 1, &rc) == 1);
        assert(rc == -EBUSY); reentry = 0;
    }
}
static void *message(unsigned int bytes, unsigned int source) {
    struct message *m = NULL;
    if (!source && bytes == 12 && is("address-reuse")) { m = recycled; recycled = NULL; }
    if (use_arena && (!arena_allocations || (fresh_request_lease && !source && bytes == 12 && arena_allocations == 1))) {
        assert(!m && !arena_live && arena_frees == arena_allocations);
        if (arena_allocations) {
            const struct functional_vdf_path_snapshot s = snapshot();
            assert(s.leases[0].freed && !s.leases[0].pointer && !s.leases[0].free_rc);
            assert(!s.leases[1].pointer && request_frees == path_calls);
        }
        m = (struct message *)arena.storage; arena_live = 1; arena_allocations++;
    }
    if (!m) m = malloc(sizeof *m + bytes);
    assert(m); memset(m, 0, sizeof *m + bytes); m->source = source; m->size = bytes;
    for (size_t i = 0; i < sizeof live / sizeof *live; i++) if (!live[i]) { live[i] = m; return m->body; }
    assert(0); return NULL;
}
static void dispose(void *p) {
    struct message *m = envelope(p);
    for (size_t i = 0; i < sizeof live / sizeof *live; i++) if (live[i] == m) {
        live[i] = NULL;
        if (m == (struct message *)arena.storage) {
            assert(arena_live && arena_allocations == arena_frees + 1);
            arena_live = 0; arena_frees++; return;
        }
        if ((is("address-reuse") || is("foreign-reuse")) && m->source == FUNCTIONAL_VDF_PATH_SID && m->size == 12) {
            assert(!recycled); recycled = m;
        } else free(m);
        return;
    }
    assert(0);
}
static void cleanup(void) {
    for (size_t i = 0; i < sizeof live / sizeof *live; i++) {
        if (live[i] != (struct message *)arena.storage) free(live[i]);
        live[i] = NULL;
    }
    free(recycled); recycled = NULL;
}
static unsigned int size(void *p) {
    inspect();
    if (use_arena && is("alloc-alias-interior") && p == (unsigned char *)active_request + 1) return saved_bytes;
    return envelope(p)->size;
}
static unsigned int source(void *p) { inspect(); return envelope(p)->source; }
static void set_source(void *p, unsigned int src) {
    inspect(); envelope(p)->source = src;
    if (is("set-source-fail")) envelope(p)->source++;
    if (is("ack-write-corrupt")) ((unsigned char *)p)[11] = 1;
}
static int allocate(unsigned int dst, void **pointer, unsigned int bytes, unsigned int option) {
    inspect(); assert(dst == saved_source && bytes == 12 && option == 1); allocations++;
    if (saved_bytes == FUNCTIONAL_VDF_LAYOUT_REQUEST_BYTES || saved_wire[2] == 0x52 || saved_wire[2] == 0x62 ||
        saved_wire[2] == 0x41 || bb_index(0x0100u | saved_wire[2]) >= 0)
        assert(snapshot().leases[0].freed && request_frees == path_calls);
    if (is("alloc-fail")) { *pointer = NULL; return -ENOMEM; }
    if (is("alloc-alias") || is("alloc-alias-interior")) {
        if (use_arena) assert(!arena_live && arena_allocations == 1 && arena_frees == 1);
        *pointer = (unsigned char *)active_request + (is("alloc-alias-interior") ? 1 : 0); return 0;
    }
    if (starts("alloc-constant-")) {
        unsigned int index = 3; assert(sscanf(scenario, "alloc-constant-%u", &index) == 1 && index < 3);
        *pointer = (void *)(uintptr_t)functional_vdf_path_test_constant_address(index); return 0;
    }
    if (is("alloc-max-span")) { *pointer = (void *)(UINTPTR_MAX - 5); return 0; }
    if (is("alloc-display-tail")) {
        *pointer = (unsigned char *)functional_vdf_path_test_snapshot_address() +
            offsetof(struct functional_vdf_path_snapshot, canonical_display16) + FCAM_DISPLAY_INPUT_BYTES - 1;
        return 0;
    }
    if (is("alloc-bb-tail")) {
        *pointer = (unsigned char *)functional_vdf_path_test_snapshot_address() +
            offsetof(struct functional_vdf_path_snapshot, canonical_bb32) + FCAM_BB_INPUT_BYTES - 1;
        return 0;
    }
    if (is("alloc-snapshot-tail")) {
        *pointer = (unsigned char *)functional_vdf_path_test_snapshot_address() +
            offsetof(struct functional_vdf_path_snapshot, model_result) + FCAM_VDF_RESULT_MAX_BYTES - 1;
        return 0;
    }
    *pointer = message(bytes, 0);
    if (is("alloc-short") || is("alloc-long")) {
        memset(*pointer, 0xcc, bytes); envelope(*pointer)->size = is("alloc-short") ? 11 : 13;
    }
    if (is("alloc-dirty-fail")) return -ENOMEM;
    return 0;
}
static int real_free(unsigned int dst, void *p) {
    inspect(); frees++;
    if (dst == FUNCTIONAL_VDF_PATH_SID) {
        assert(p == active_request && !memcmp(p, saved_wire, saved_bytes)); request_frees++;
        if (is("request-free-fail")) return -EIO;
    } else {
        assert(dst == saved_source && !memcmp(p, success_wire, 12)); ack_frees++;
        if (is("ack-free-fail") && ack_frees == (saved_bytes == 24 ? 1u : 2u)) return -EIO;
        if (is("reentrant-free") && !reentry) {
            int rc = 5; reentry = 1;
            assert(functional_vdf_path_release_cycle(dst, p, receive_ticket, real_free, NULL, &rc) == 1 && rc == -EPROTO);
            reentry = 0;
        }
    }
    dispose(p); return 0;
}
static void check_hex(const char *text, const char *key, const unsigned char *expected, size_t bytes) {
    const char *p = strstr(text, key); assert(p); p += strlen(key);
    for (size_t i = 0; i < bytes; i++) {
        unsigned int value = 256; assert(sscanf(p + 2 * i, "%2x", &value) == 1 && value == expected[i]);
    }
    assert(p[2 * bytes] == 0 || p[2 * bytes] == ' ');
}
static void logger(const char *tag, const char *text) {
    inspect(); logs++;
    assert(strstr(tag, "FUNCTIONAL_VDF_PATH_") && strstr(text, "original_CP_FIFO_verified=0") &&
        strstr(text, "physical_CP_RTOS_verified=0") && strstr(text, "capture_verified=0"));
    assert(strlen(text) < 3000 && strstr(text, " raw=") &&
        strstr(text, " canonical_config=") && strstr(text, " canonical_zebra8=") &&
        strstr(text, " canonical_layout32=") && strstr(text, " canonical_display16=") && strstr(text, " canonical_bb32=") &&
        strstr(text, " realresultbytes=") &&
        strstr(text, " model_result_bytes=") && strstr(text, " model_result_fnv1a64=") && strstr(text, " model_result_hex="));
    const struct functional_vdf_path_snapshot s = snapshot();
    unsigned int bound = 2, bound_source = 0;
    const char *queue = strstr(text, " refresh_queue_bound="); assert(queue);
    assert(sscanf(queue, " refresh_queue_bound=%u refresh_queue_source=%x", &bound, &bound_source) == 2 &&
        bound == s.refresh_queue_bound && bound_source == s.refresh_queue_source);
    check_hex(text, " raw=", s.original_wire, s.origin.bytes);
    check_hex(text, " ack_wire=", success_wire, 12);
    check_hex(text, " canonical_config=", s.canonical_config, sizeof s.canonical_config);
    check_hex(text, " canonical_zebra8=", s.canonical_zebra8, sizeof s.canonical_zebra8);
    check_hex(text, " canonical_layout32=", s.canonical_layout32, sizeof s.canonical_layout32);
    check_hex(text, " canonical_display16=", s.canonical_display16, sizeof s.canonical_display16);
    check_hex(text, " canonical_bb32=", s.canonical_bb32, sizeof s.canonical_bb32);
    unsigned int actual_bytes = FCAM_VDF_RESULT_MAX_BYTES + 1;
    const char *bytes = strstr(text, " realresultbytes=");
    assert(sscanf(bytes, " realresultbytes=%u", &actual_bytes) == 1 && actual_bytes == s.model_result_bytes);
    check_hex(text, " model_result_hex=", s.model_result, s.model_result_bytes);
    const char *digest = strstr(text, " model_result_fnv1a64="); unsigned long long actual = 0;
    assert(sscanf(digest, " model_result_fnv1a64=%llx", &actual) == 1 && actual == fnv(s.model_result, s.model_result_bytes));
}
static int send(unsigned int dst, void *p) {
    inspect(); sends++;
    assert(request_frees == path_calls && dst == saved_source);
    assert(envelope(p)->size == 12 && envelope(p)->source == FUNCTIONAL_VDF_PATH_SID);
    assert(!memcmp(p, success_wire, 12)); ack_pointer = p;
    struct functional_vdf_path_snapshot s = snapshot();
    assert(s.leases[0].freed && s.leases[1].send_inflight && !s.ack_queued);
    if (is("inline-free") || is("inline-send-fail")) {
        int rc = 5;
        assert(functional_vdf_path_observe_receive_cycle(dst, p, FUNCTIONAL_VDF_PATH_SID, 12, &receive_ticket) == 1);
        assert(functional_vdf_path_release_cycle(dst, p, receive_ticket, real_free, logger, &rc) == 1 && !rc);
        s = snapshot();
        assert(s.leases[1].freed && s.leases[1].send_inflight && !s.ap_consumed && s.busy);
        void *again = message(saved_bytes, saved_source); memcpy(again, saved_wire, saved_bytes);
        assert(functional_vdf_path_dispatch(FUNCTIONAL_VDF_PATH_SID, again, &io, &guard, 1, &rc) == 1 && rc == -EBUSY);
        dispose(again);
    }
    return is("send-fail") || is("inline-send-fail") ? -EPIPE : 0;
}
static int reserve(void) { inspect(); reservations++; return is("guard-fail") ? -EBUSY : 0; }
static void unlock(void) { inspect(); unlocks++; assert(snapshot().busy && !snapshot().guard_held); }
static int ready(void) {
    inspect(); ready_calls++;
    return is("guard-miss") || (is("guard-lost") && ready_calls == 2) ? 0 : 1;
}
static const struct full_imaging_io io = {allocate, real_free, set_source, send, size, source, logger};
static const struct native_cp_state_publication_guard guard = {reserve, unlock, ready};

struct mutation { const char *name; unsigned int offset; uint64_t value; unsigned int bytes; };
static const struct mutation mutations[] = {
    {"abi", FCAM_VDF_R_ABI, 2, 4}, {"length", FCAM_VDF_R_BYTES, 159, 4},
    {"instance", FCAM_VDF_R_INSTANCE, 99, 8}, {"zero-instance", FCAM_VDF_R_INSTANCE, 0, 8},
    {"config-generation", FCAM_VDF_R_CONFIG_GENERATION, 7, 8},
    {"before-config", FCAM_VDF_R_BEFORE_CONFIG_GENERATION, 6, 8},
    {"config-overflow", FCAM_VDF_R_BEFORE_CONFIG_GENERATION, UINT64_MAX, 8},
    {"frame-generation", FCAM_VDF_R_FRAME_GENERATION, 2, 8},
    {"before-frame", FCAM_VDF_R_BEFORE_FRAME_GENERATION, 1, 8},
    {"frame-overflow", FCAM_VDF_R_BEFORE_FRAME_GENERATION, UINT64_MAX, 8},
    {"lease-generation", FCAM_VDF_R_LEASE_GENERATION, 0, 8},
    {"input-hash", FCAM_VDF_R_INPUT_FNV, 0, 8}, {"source-hash", FCAM_VDF_R_SOURCE_FNV, 0, 8},
    {"sink-hash", FCAM_VDF_R_SINK_FNV, 99, 8}, {"active-bytes", FCAM_VDF_R_ACTIVE_BYTES, 1, 8},
    {"width", FCAM_VDF_R_WIDTH, 0, 4}, {"height", FCAM_VDF_R_HEIGHT, 0, 4},
    {"stride", FCAM_VDF_R_STRIDE, 1, 4}, {"endpoint", FCAM_VDF_R_ENDPOINT, UINT32_C(0x9059081a), 4},
    {"selected-mask", FCAM_VDF_R_SELECTED_MASK, 9, 4}, {"completed-mask", FCAM_VDF_R_COMPLETED_MASK, 0, 4},
    {"class", FCAM_VDF_R_CLASS, 5, 4}, {"enabled", FCAM_VDF_R_ENABLED, 2, 4},
    {"readback", FCAM_VDF_R_CONFIG_READBACK, 0, 4}, {"commit", FCAM_VDF_R_COMMITTED, 0, 4},
    {"consumed", FCAM_VDF_R_FRAME_CONSUMED, 0, 4}, {"retired", FCAM_VDF_R_RETIRED, 0, 4},
    {"status", FCAM_VDF_R_STATUS, 1, 4}, {"reserved", FCAM_VDF_R_RESERVED, 1, 4}
};
int fcam_bridge_call(const struct fcam_native_origin *origin, uint32_t op, const void *input, size_t input_bytes,
    void *output, size_t capacity, struct fcam_bridge_result *result) {
    inspect();
    assert(origin && output && result && active_request);
    assert(origin->source == saved_source && origin->destination == FUNCTIONAL_VDF_PATH_SID &&
        origin->command == ((unsigned int)saved_wire[2] | (unsigned int)saved_wire[3] << 8) &&
        origin->bytes == saved_bytes && origin->wire_fnv1a64 == fnv(saved_wire, saved_bytes));
    unsigned char *out = output; memset(out, 0, capacity);
    *result = (struct fcam_bridge_result){.used = capacity, .required = capacity, .model_instance = 55};
    if (op == FCAM_OP_INIT) {
        init_calls++; assert(init_calls == 1 && !input && !input_bytes && capacity == FCAM_STATE_BYTES);
        put32(out + FCAM_S_ABI, FCAM_ABI_VERSION); put32(out + FCAM_S_CAPS, FCAM_CAPABILITIES);
        put64(out + FCAM_S_INSTANCE, 55); put64(out + FCAM_S_GENERATION, model_config);
        put64(out + FCAM_S_FRAME_GENERATION, model_frame); put64(out + FCAM_S_RENDERED, model_frame);
        if (is("init-error")) return -ENODEV;
        if (is("init-short")) result->used--;
        if (is("init-instance")) put64(out + FCAM_S_INSTANCE, 56);
        if (is("init-abi")) put32(out + FCAM_S_ABI, 2);
        if (is("init-token")) result->result_token = 1;
        if (is("init-reserved")) out[127] = 1;
        return 0;
    }
    const int zebra = op == FCAM_OP_VDF_ZEBRA, layout = op == FCAM_OP_VDF_LAYOUT;
    const int display = op == FCAM_OP_VDF_DISPLAY_CONFIG, bb = op == FCAM_OP_BB_STARTUP_CONFIG;
    assert((bb || display || layout || zebra || op == FCAM_OP_VDF_PATH) && input &&
        input_bytes == (bb || layout ? 32u : zebra ? 8u : 16u) &&
        capacity == (bb || layout ? 192u : display ? 176u : zebra ? 168u : 160u)); path_calls++;
    unsigned char config[16], zebra_config[8] = {0};
    if (bb) {
        unsigned char expected[FCAM_BB_INPUT_BYTES] = {0};
        unsigned char before_banks[FCAM_BB_FEATURES][FCAM_BB_INPUT_BYTES];
        memcpy(before_banks, model_bb, sizeof before_banks);
        const int index = bb_index(origin->command); assert(index >= 0);
        expected[0] = (unsigned char)origin->command; expected[1] = 1;
        expected[2] = (unsigned char)bb_bodies[index];
        memcpy(expected + 4, saved_wire + 8, bb_bodies[index]);
        assert(!memcmp(input, expected, sizeof expected));
        memcpy(model_bb[index], input, FCAM_BB_INPUT_BYTES); model_bb_valid[index] = 1;
        for (unsigned int i = 0; i < FCAM_BB_FEATURES; i++)
            if (i != (unsigned int)index) assert(!memcmp(model_bb[i], before_banks[i], FCAM_BB_INPUT_BYTES));
        memcpy(config, model_route, sizeof config);
    } else if (display) {
        unsigned char expected[FCAM_DISPLAY_INPUT_BYTES] = {0};
        const unsigned int body_bytes = saved_wire[2] == 0x41 ? 0u : saved_wire[2] == 0x52 ? 8u : 2u;
        put32(expected, origin->command); put32(expected + 4, body_bytes);
        memcpy(expected + 8, saved_wire + 8, body_bytes);
        assert(!memcmp(input, expected, sizeof expected));
        memcpy(config, model_route, sizeof config);
    } else if (layout) {
        memcpy(config, model_route, sizeof config);
        assert(!memcmp(input, saved_wire + 8, FCAM_LAYOUT_INPUT_BYTES));
    } else if (zebra) {
        memcpy(config, model_route, sizeof config); memcpy(zebra_config, saved_wire + 8, 5);
        assert(!memcmp(zebra_config, input, sizeof zebra_config));
    } else {
        memcpy(config, saved_wire + 8, sizeof config); memset(config + 13, 0, 3);
        assert(!memcmp(config, input, sizeof config)); memcpy(model_route, config, sizeof model_route);
    }
    assert(!memcmp(active_request, saved_wire, saved_bytes));
    if (is("generation-gap")) { model_config += 3; model_frame += 2; }
    const unsigned int active = config[0];
    put32(out + FCAM_VDF_R_ABI, FCAM_ABI_VERSION); put32(out + FCAM_VDF_R_BYTES, (uint32_t)capacity);
    put64(out + FCAM_VDF_R_INSTANCE, 55);
    put64(out + FCAM_VDF_R_BEFORE_CONFIG_GENERATION, model_config);
    put64(out + FCAM_VDF_R_BEFORE_FRAME_GENERATION, model_frame);
    model_config++; if (active) { model_frame++; model_lease++; }
    put64(out + FCAM_VDF_R_CONFIG_GENERATION, model_config);
    put64(out + FCAM_VDF_R_FRAME_GENERATION, model_frame); put64(out + FCAM_VDF_R_LEASE_GENERATION, active ? model_lease : 0);
    put64(out + FCAM_VDF_R_INPUT_FNV, fnv(input, input_bytes));
    if (active) {
        put64(out + FCAM_VDF_R_SOURCE_FNV, 987); put64(out + FCAM_VDF_R_SINK_FNV, 987);
        put64(out + FCAM_VDF_R_ACTIVE_BYTES, 640 * 480 * 3);
    }
    put32(out + FCAM_VDF_R_WIDTH, 640); put32(out + FCAM_VDF_R_HEIGHT, 480); put32(out + FCAM_VDF_R_STRIDE, 1920);
    put32(out + FCAM_VDF_R_ENDPOINT, FCAM_VDF_ENDPOINT); put32(out + FCAM_VDF_R_SELECTED_MASK, 1);
    put32(out + FCAM_VDF_R_COMPLETED_MASK, 1); put32(out + FCAM_VDF_R_CLASS, bb ? FCAM_BB_CLASS : active); put32(out + FCAM_VDF_R_ENABLED, active);
    put32(out + FCAM_VDF_R_CONFIG_READBACK, 1); put32(out + FCAM_VDF_R_COMMITTED, 1);
    put32(out + FCAM_VDF_R_FRAME_CONSUMED, active); put32(out + FCAM_VDF_R_RETIRED, active);
    memcpy(out + FCAM_VDF_R_CONFIG, config, sizeof config);
    if (bb || display || layout || zebra) {
        const size_t tail_bytes = bb ? FCAM_BB_INPUT_BYTES : display ? FCAM_DISPLAY_INPUT_BYTES : layout ? FCAM_LAYOUT_INPUT_BYTES : FCAM_ZEBRA_INPUT_BYTES;
        memcpy(out + FCAM_LAYOUT_R_CONFIG, bb ? model_bb[bb_index(origin->command)] : display || layout ? input : zebra_config, tail_bytes);
        if (bb && starts("result-borrowed-bank-")) {
            unsigned int index = FCAM_BB_FEATURES;
            assert(sscanf(scenario, "result-borrowed-bank-%u", &index) == 1 && index < FCAM_BB_FEATURES &&
                model_bb_valid[index] && bb_commands[index] != origin->command);
            memcpy(out + FCAM_BB_R_CONFIG, model_bb[index], FCAM_BB_INPUT_BYTES);
        }
        if (starts("result-tail-")) {
            unsigned int offset = (unsigned int)tail_bytes;
            assert(sscanf(scenario, "result-tail-%u", &offset) == 1 && offset < tail_bytes);
            out[FCAM_LAYOUT_R_CONFIG + offset] ^= 1;
        }
        if (is("result-path-fnv")) put64(out + FCAM_VDF_R_INPUT_FNV, fnv(config, sizeof config));
        if (is("result-old-length")) put32(out + FCAM_VDF_R_BYTES, FCAM_VDF_RESULT_BYTES);
        if (is("result-old-used")) result->used = result->required = FCAM_VDF_RESULT_BYTES;
        if (is("result-route-class")) {
            out[FCAM_VDF_R_CONFIG] = 0; put32(out + FCAM_VDF_R_CLASS, 0); put32(out + FCAM_VDF_R_ENABLED, 0);
        }
        if (is("result-stale-lease")) put64(out + FCAM_VDF_R_LEASE_GENERATION, model_lease - 1);
        if (is("result-zebra-length")) put32(out + FCAM_VDF_R_BYTES, FCAM_ZEBRA_RESULT_BYTES);
        if (is("result-zebra-used")) result->used = result->required = FCAM_ZEBRA_RESULT_BYTES;
        if (is("result-layout-length")) put32(out + FCAM_VDF_R_BYTES, FCAM_LAYOUT_RESULT_BYTES);
        if (is("result-layout-used")) result->used = result->required = FCAM_LAYOUT_RESULT_BYTES;
        if (is("result-original-body-fnv")) put64(out + FCAM_VDF_R_INPUT_FNV, fnv(saved_wire + 8, saved_bytes - 8));
        if (is("result-other-display-command")) out[FCAM_DISPLAY_R_CONFIG] = saved_wire[2] == 0x52 ? 0x62 : 0x52;
        if (is("result-inactive-receipt")) {
            memset(out + FCAM_VDF_R_CONFIG, 0, FCAM_VDF_INPUT_BYTES);
            out[FCAM_VDF_R_CONFIG + 1] = out[FCAM_VDF_R_CONFIG + 2] = 1;
            put32(out + FCAM_VDF_R_CLASS, 0); put32(out + FCAM_VDF_R_ENABLED, 0);
            put32(out + FCAM_VDF_R_FRAME_CONSUMED, 0); put32(out + FCAM_VDF_R_RETIRED, 0);
            memset(out + FCAM_VDF_R_SOURCE_FNV, 0, 24);
            put64(out + FCAM_VDF_R_FRAME_GENERATION, model_frame - 1);
            put64(out + FCAM_VDF_R_LEASE_GENERATION, 0);
        }
        if (is("result-wrong-geometry")) {
            put32(out + FCAM_VDF_R_WIDTH, 800); put32(out + FCAM_VDF_R_STRIDE, 2400);
            put64(out + FCAM_VDF_R_ACTIVE_BYTES, 800 * 480 * 3);
        }
        if (is("result-wrong-height")) {
            put32(out + FCAM_VDF_R_HEIGHT, 479); put64(out + FCAM_VDF_R_ACTIVE_BYTES, 640 * 479 * 3);
        }
    }
    if (starts("result-")) {
        for (size_t i = 0; i < sizeof mutations / sizeof *mutations; i++) if (!strcmp(scenario + 7, mutations[i].name)) {
            if (mutations[i].bytes == 4) put32(out + mutations[i].offset,
                bb && !strcmp(mutations[i].name, "class") ? 1u : (uint32_t)mutations[i].value);
            else put64(out + mutations[i].offset, mutations[i].value);
        }
        if (is("result-config")) out[FCAM_VDF_R_CONFIG + 5] ^= 1;
        if (is("result-canonical-tail")) out[FCAM_VDF_R_CONFIG + 15] = 1;
        if (is("result-short")) result->used--;
        if (is("result-long")) result->used++;
        if (is("result-required")) result->required++;
        if (is("result-token")) result->result_token = 1;
        if (is("result-metadata-instance")) result->model_instance++;
        if (is("result-canary")) out[capacity] = 1;
        if (is("result-mutated-input")) ((unsigned char *)(uintptr_t)input)[5] ^= 1;
        if (bb && starts("result-input-tail-")) {
            unsigned int offset = FCAM_BB_INPUT_BYTES;
            assert(sscanf(scenario, "result-input-tail-%u", &offset) == 1 && offset >= 4 + saved_bytes - 8 && offset < FCAM_BB_INPUT_BYTES);
            ((unsigned char *)(uintptr_t)input)[offset] = 1;
            out[FCAM_BB_R_CONFIG + offset] = 1;
            put64(out + FCAM_VDF_R_INPUT_FNV, fnv(input, input_bytes));
        }
        if (bb && is("result-full-wire-fnv")) put64(out + FCAM_VDF_R_INPUT_FNV, fnv(saved_wire, saved_bytes));
    }
    if (is("disable-forged-frame")) put64(out + FCAM_VDF_R_FRAME_GENERATION, model_frame + 1);
    if (is("disable-forged-consumed")) put32(out + FCAM_VDF_R_FRAME_CONSUMED, 1);
    if (is("disable-forged-hash")) put64(out + FCAM_VDF_R_SINK_FNV, 987);
    if (is("disable-forged-bytes")) put64(out + FCAM_VDF_R_ACTIVE_BYTES, 921600);
    if (is("disable-forged-lease") && path_calls == 2) put64(out + FCAM_VDF_R_LEASE_GENERATION, model_lease + 1);
    if (is("repeat-old-lease") && path_calls == 2) put64(out + FCAM_VDF_R_LEASE_GENERATION, model_lease - 1);
    if (is("result-duplicate-generation")) {
        put64(out + FCAM_VDF_R_BEFORE_CONFIG_GENERATION, model_config - 2);
        put64(out + FCAM_VDF_R_CONFIG_GENERATION, model_config - 1);
    }
    if (is("mutated-request")) ((unsigned char *)active_request)[saved_bytes == 8 ? 0 : saved_bytes - 1] ^= 1;
    if (is("mutated-padding")) ((unsigned char *)active_request)[30] ^= 1;
    if (is("mutated-source")) envelope(active_request)->source++;
    if (is("mutated-size")) envelope(active_request)->size--;
    if (is("bridge-error")) return -EIO;
    if (is("bridge-positive")) return 1;
    return 0;
}
int fcam_bridge_bb_startup_config(const struct fcam_native_origin *origin, const unsigned char input[32],
    unsigned char output[192], struct fcam_bridge_result *result) {
    return fcam_bridge_call(origin, FCAM_OP_BB_STARTUP_CONFIG, input, FCAM_BB_INPUT_BYTES,
        output, FCAM_BB_RESULT_BYTES, result);
}
static void *request(unsigned int active) {
    unsigned char *p = message(24, UINT32_C(0x81cf61c4));
    static const unsigned char header[8] = {0x0d, 0x20, 0x38, 1, 24, 0, 1, 0x80};
    memcpy(p, header, sizeof header); p[8] = (unsigned char)active; p[9] = p[10] = active ? 5 : 1;
    if (is("opaque")) {
        for (unsigned int i = 11; i < 24; i++) p[i] = (unsigned char)(0xa0 + i);
        p[12] = 2;
    }
    active_request = p; saved_bytes = 24; saved_source = envelope(p)->source;
    memset(saved_wire, 0, sizeof saved_wire); memcpy(saved_wire, p, saved_bytes); return p;
}
static int dispatch(void *p, int enabled, const struct full_imaging_io *callbacks,
    const struct native_cp_state_publication_guard *g, int *rc) {
    return functional_vdf_path_dispatch(FUNCTIONAL_VDF_PATH_SID, p, callbacks, g, enabled, rc);
}
static void accept(void *p) {
    int rc = 123;
    assert(dispatch(p, 1, &io, &guard, &rc) == 1 && !rc);
    assert(snapshot().request_owned && snapshot().model_complete);
}
static uint64_t observe(void *p) {
    uint64_t ticket = 0;
    assert(functional_vdf_path_observe_receive_cycle(saved_source, p, FUNCTIONAL_VDF_PATH_SID, 12, &ticket) == 1);
    assert(ticket && ticket == snapshot().cycle); return ticket;
}
static void consume(void *p, uint64_t ticket) {
    int rc = 8; receive_ticket = ticket;
    assert(functional_vdf_path_release_cycle(saved_source, p, ticket, real_free, logger, &rc) == 1 && !rc);
}
struct foreign { void *p; uint64_t ticket; int receive; };
static void *foreign(void *arg) {
    struct foreign *f = arg; uint64_t ticket = UINT64_C(0xcafe); int rc = 999;
    if (f->receive) {
        assert(functional_vdf_path_observe_receive_cycle(saved_source, f->p, FUNCTIONAL_VDF_PATH_SID, 12, &ticket) == -EPROTO);
        assert(ticket == UINT64_C(0xcafe));
    } else assert(functional_vdf_path_release_cycle(saved_source, f->p, f->ticket, real_free, logger, &rc) == 1 && rc == -EPROTO);
    return NULL;
}
static int run_receive_failure(void) {
    if (!starts("receive-") && !is("foreign-receive")) return 0;
    const unsigned int previous_frees = ack_frees;
    if (is("foreign-receive")) {
        pthread_t thread; struct foreign f = {ack_pointer, 0, 1};
        assert(!pthread_create(&thread, NULL, foreign, &f) && !pthread_join(thread, NULL));
    } else {
        uint64_t ticket = UINT64_C(0xcafe); unsigned int src = FUNCTIONAL_VDF_PATH_SID, bytes = 12, dst = saved_source;
        if (is("receive-source")) src++;
        if (is("receive-size")) bytes--;
        if (is("receive-destination")) dst++;
        if (is("receive-meta-source")) envelope(ack_pointer)->source++;
        if (is("receive-meta-size")) envelope(ack_pointer)->size--;
        if (is("receive-wire")) ((unsigned char *)ack_pointer)[10] ^= 1;
        assert(functional_vdf_path_observe_receive_cycle(dst, ack_pointer, src, bytes, &ticket) == -EPROTO);
        assert(ticket == UINT64_C(0xcafe));
    }
    struct functional_vdf_path_snapshot s = snapshot();
    assert(s.faults && !s.ap_consumed && s.leases[1].pointer == ack_pointer && !s.ack_received && ack_frees == previous_frees); return 1;
}
static void *zebra_request(void) {
    static const unsigned char wire[14] = {0x0d, 0x20, 0x53, 1, 14, 0, 1, 0x80, 3, 0, 0x20, 75, 65, 0};
    saved_bytes = 14; saved_source = is("dynamic-source") ? UINT32_C(0x81cfcafe) : UINT32_C(0x81cf61c5);
    unsigned char *p = message(saved_bytes, saved_source); memcpy(p, wire, sizeof wire);
    if (is("opaque")) { p[8] = 0xe3; p[10] = 0xda; p[11] = 0xff; p[12] = 0xb7; }
    if (is("padding") || is("opaque")) p[13] = 0xe7;
    memset(saved_wire, 0, sizeof saved_wire); memcpy(saved_wire, p, saved_bytes);
    active_request = p; return p;
}
static void *layout_request(void) {
    static const unsigned char wire[FUNCTIONAL_VDF_LAYOUT_REQUEST_BYTES] = {
        0x0d, 0x20, 0x4c, 1, 40, 0, 1, 0x80,
        7, 1, 1, 0, 0, 0, 0, 0, 0x80, 2, 0xe0, 1,
        0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 3, 0, 0, 0, 0, 0, 0, 0
    };
    saved_bytes = FUNCTIONAL_VDF_LAYOUT_REQUEST_BYTES;
    saved_source = is("dynamic-source") ? UINT32_C(0x81cfa74c) : UINT32_C(0x81cf61c6);
    unsigned char *p = message(saved_bytes, saved_source); memcpy(p, wire, sizeof wire);
    memcpy(saved_wire, wire, sizeof wire); active_request = p; return p;
}
static void *display_request(int flag) {
    static const unsigned char wire[FUNCTIONAL_VDF_PEAKING_REQUEST_BYTES] = {
        0x0d, 0x20, 0x52, 1, 16, 0, 1, 0x80, 3, 0, 1, 0, 0, 235, 128, 128
    };
    static const unsigned char palettes[4][3] = {{81, 90, 240}, {210, 16, 146}, {29, 255, 83}, {235, 128, 128}};
    saved_bytes = flag == 2 ? FUNCTIONAL_VDF_REFRESH_REQUEST_BYTES :
        flag ? FUNCTIONAL_VDF_FLAG_REQUEST_BYTES : FUNCTIONAL_VDF_PEAKING_REQUEST_BYTES;
    saved_source = flag == 2 ? refresh_source :
        is("dynamic-source") ? UINT32_C(0x81cfa752) : UINT32_C(0x81cf61c5);
    unsigned char *p = message(saved_bytes, saved_source); memcpy(p, wire, saved_bytes);
    if (flag == 2) { p[2] = 0x41; p[4] = 8; }
    else if (flag) { p[2] = 0x62; p[4] = 10; p[8] = p[9] = 0; }
    if (!flag && starts("palette-")) {
        unsigned int index = 4; assert(sscanf(scenario, "palette-%u", &index) == 1 && index < 4);
        memcpy(p + 13, palettes[index], 3);
    }
    if (!flag && starts("level-")) {
        unsigned int level = 3; assert(sscanf(scenario, "level-%u", &level) == 1 && level < 3); p[10] = (unsigned char)level;
    }
    if (!flag && starts("magnification-")) {
        unsigned int index = 3; const unsigned char values[3] = {0, 10, 40};
        assert(sscanf(scenario, "magnification-%u", &index) == 1 && index < 3); p[11] = values[index];
    }
    memset(saved_wire, 0, sizeof saved_wire); memcpy(saved_wire, p, saved_bytes);
    active_request = p; return p;
}
static void *bb_request(unsigned int index) {
    assert(index < FCAM_BB_FEATURES);
    saved_bytes = 8 + bb_bodies[index];
    saved_source = is("dynamic-source") ? UINT32_C(0x81cfab00) + index : UINT32_C(0x81cf6100) + index;
    unsigned char *p = message(saved_bytes, saved_source);
    p[0] = 0x0d; p[1] = 0x20; p[2] = (unsigned char)bb_commands[index]; p[3] = 1;
    p[4] = (unsigned char)saved_bytes; p[6] = 1; p[7] = 0x80;
    if (!index) { p[10] = 15; p[11] = 2; }
    if (index == 1 || index == 4) p[9] = 1;
    if (index == 1 && observed_initial) {
        static const unsigned char initial_body[28] = {[1]=1,[12]=8,[16]=7,[20]=1,[24]=1};
        memcpy(p + 8, initial_body, sizeof initial_body);
    }
    if (index == 2 && is("gamut1")) p[8] = 1;
    if (index == 4) {
        unsigned int period = 60;
        if (starts("period-")) assert(sscanf(scenario, "period-%u", &period) == 1);
        put32(p + 12, period);
    }
    memset(saved_wire, 0, sizeof saved_wire); memcpy(saved_wire, p, saved_bytes);
    active_request = p; return p;
}
static void finish_cycle(void) { receive_ticket = observe(ack_pointer); consume(ack_pointer, receive_ticket); }
static int run_config(int kind) {
    const int layout = kind == 1, display = kind >= 2 && kind <= 4, bb = kind >= 5;
    const int flag = kind == 3, refresh = kind == 4, configured = layout || display || bb;
    const unsigned int bb_kind = bb ? (unsigned int)(kind - 5) : 0;
    static const char *const bb_prefixes[FCAM_BB_FEATURES] = {"bb0111-", "bb0166-", "bb0167-", "bb015f-", "bb0128-"};
    const int display_kind = refresh ? 2 : flag;
    const char *prefix = bb ? (observed_initial ? "bb0166-initial-" : bb_prefixes[bb_kind]) : refresh ? "refresh-" : flag ? "flag-" : display ? "peaking-" : layout ? "layout-" : "zebra-";
    const char *test = scenario + strlen(prefix);
    const int legacy_refresh = refresh && !strcmp(test, "legacy-source-repeat");
    const int mixed_reuse = configured && !strcmp(test, "mixed-address-reuse");
    scenario = !strcmp(test, "address-reuse") || mixed_reuse ? "address-reuse" :
        !strcmp(test, "route-opaque") ? "opaque" : "success";
    uint64_t previous_ticket = 0;
    if (strcmp(test, "cold-inactive")) {
        accept(request(!strncmp(test, "inactive", 8) ? 0 : 1)); finish_cycle();
        previous_ticket = receive_ticket;
    }
    if (bb && !strncmp(test, "result-borrowed-bank-", 21)) {
        for (unsigned int i = 0; i < FCAM_BB_FEATURES; i++) if (i != bb_kind) { accept(bb_request(i)); finish_cycle(); }
    }
    const int forced_fresh = !strncmp(test, "fresh-request-lease", 19);
    scenario = mixed_reuse ? "address-reuse" : legacy_refresh ? "repeat" : forced_fresh ? (test[19] ? test + 20 : "success") :
        !strncmp(test, "inactive-", 9) ? test + 9 : test;
    fresh_request_lease = (unsigned int)forced_fresh;
    use_arena = configured && (forced_fresh || is("alloc-alias") || is("alloc-alias-interior"));
    if (refresh) {
        refresh_source = legacy_refresh ? UINT32_C(0x81cf0012) : UINT32_C(0x80946189);
        assert(!functional_vdf_path_bind_refresh_queue(refresh_source));
    }
    const struct functional_vdf_path_snapshot before = snapshot();
    const unsigned int calls = path_calls, allocated = allocations, released = frees, sent = sends;
    void *p = bb ? bb_request(bb_kind) : display ? display_request(display_kind) : layout ? layout_request() : zebra_request(); int rc = 999;
    if (bb && starts("invalid-body-")) {
        unsigned int offset = bb_bodies[bb_kind];
        assert(sscanf(scenario, "invalid-body-%u", &offset) == 1 && offset < bb_bodies[bb_kind]);
        ((unsigned char *)p)[8 + offset] ^= (bb_kind == 2 && !offset ? 2u : 1u);
    }
    if (bb && is("invalid-period")) put32((unsigned char *)p + 12, 11);
    if (bb && is("invalid-period-high")) put32((unsigned char *)p + 12, UINT32_MAX);
    if (layout && starts("invalid-body-")) {
        unsigned int offset = 32; assert(sscanf(scenario, "invalid-body-%u", &offset) == 1 && offset < 32);
        ((unsigned char *)p)[8 + offset] ^= 1;
    }
    if (is("invalid-enable")) ((unsigned char *)p)[9] = 1;
    if (is("invalid-enable255")) ((unsigned char *)p)[9] = 255;
    if (is("invalid-command-shape")) ((unsigned char *)p)[2] = flag ? 0x52 : 0x62;
    if (is("invalid-selector")) ((unsigned char *)p)[8] = 7;
    if (is("invalid-level")) ((unsigned char *)p)[10] = 3;
    if (is("invalid-magnification")) ((unsigned char *)p)[11] = 1;
    if (is("invalid-color-type")) ((unsigned char *)p)[12] = 1;
    if (is("invalid-palette-y")) ((unsigned char *)p)[13] ^= 1;
    if (is("invalid-palette-cb")) ((unsigned char *)p)[14] ^= 1;
    if (is("invalid-palette-cr")) ((unsigned char *)p)[15] ^= 1;
    if (is("invalid-opaque")) ((unsigned char *)p)[8] = 255;
    if (is("invalid-off")) ((unsigned char *)p)[8] = 1;
    if (is("invalid-padding")) ((unsigned char *)p)[9] = 1;
    if (is("invalid-flags")) ((unsigned char *)p)[6] = 0;
    if (is("invalid-header-size")) ((unsigned char *)p)[4] = 24;
    if (is("invalid-header-high")) ((unsigned char *)p)[5] = 1;
    if (is("short-request")) envelope(p)->size = saved_bytes - 1;
    if (is("long-request")) envelope(p)->size = saved_bytes + 1;
    if (is("bad-source")) envelope(p)->source = FUNCTIONAL_VDF_PATH_SID;
    if (bb && is("source-zero")) envelope(p)->source = 0;
    if (bb && is("source-other-domain")) envelope(p)->source = UINT32_C(0x81ce6100);
    if (bb && is("bound-global-source")) {
        assert(!functional_vdf_path_bind_refresh_queue(UINT32_C(0x80946189)));
        envelope(p)->source = UINT32_C(0x80946189);
    }
    if (is("reentrant-dispatch")) {
        reentrant_request = message(saved_bytes, saved_source); memcpy(reentrant_request, saved_wire, saved_bytes);
    }
    if (is("default-off") || is("enabled-two") || is("unrelated") || is("wrong-type") || is("wrong-native") || is("wrong-destination")) {
        if (is("unrelated")) ((unsigned char *)p)[2] = 0x7f;
        if (is("wrong-type")) ((unsigned char *)p)[0]++;
        if (is("wrong-native")) ((unsigned char *)p)[3] = 2;
        const int handled = is("wrong-destination") ? functional_vdf_path_dispatch(1, p, &io, &guard, 1, &rc) :
            dispatch(p, is("default-off") ? 0 : is("enabled-two") ? 2 : 1, &io, &guard, &rc);
        assert(!handled && rc == 999 && path_calls == calls && frees == released && allocations == allocated);
        cleanup(); return 0;
    }
    if (bb && is("guard-lost")) ready_calls = 0;
    struct full_imaging_io callbacks = io;
    struct native_cp_state_publication_guard g = guard;
    if (is("missing-callback")) callbacks.source = NULL;
    if (is("missing-guard")) g.predecessor_ready = NULL;
    assert(dispatch(p, 1, &callbacks, &g, &rc) == 1);
    struct functional_vdf_path_snapshot s = snapshot();
    if (starts("invalid-") || is("short-request") || is("long-request") || is("bad-source") || is("bound-global-source") ||
        is("source-zero") || is("source-other-domain") || is("missing-callback") || is("missing-guard") ||
        is("guard-fail") || is("guard-miss") || (configured && (is("inactive") || is("cold-inactive")))) {
        assert(rc < 0 && !s.faults && path_calls == calls && allocations == allocated && frees == released && sends == sent);
        assert(s.cycle == before.cycle && s.completed_cycles == before.completed_cycles); cleanup(); return 0;
    }
    assert(s.origin.command == (bb ? bb_commands[bb_kind] : refresh ? 0x0141u : display ? flag ? 0x0162u : 0x0152u : layout ? 0x014cu : 0x0153u) &&
        s.origin.bytes == saved_bytes && s.origin.source == saved_source);
    assert(s.origin.wire_fnv1a64 == fnv(saved_wire, saved_bytes) && !memcmp(s.original_wire, saved_wire, saved_bytes));
    assert(!memcmp(s.canonical_config, before.canonical_config, sizeof s.canonical_config));
    if (bb) {
        assert(s.canonical_bb32[0] == (unsigned char)bb_commands[bb_kind] && s.canonical_bb32[1] == 1 &&
            s.canonical_bb32[2] == bb_bodies[bb_kind] && !s.canonical_bb32[3]);
        assert(!memcmp(s.canonical_bb32 + 4, saved_wire + 8, bb_bodies[bb_kind]));
        for (unsigned int i = 4 + bb_bodies[bb_kind]; i < FCAM_BB_INPUT_BYTES; i++) assert(!s.canonical_bb32[i]);
        assert(!memcmp(s.canonical_display16, before.canonical_display16, sizeof s.canonical_display16));
        assert(!memcmp(s.canonical_layout32, before.canonical_layout32, sizeof s.canonical_layout32));
        assert(!memcmp(s.canonical_zebra8, before.canonical_zebra8, sizeof s.canonical_zebra8));
    } else if (display) {
        assert(u32(s.canonical_display16) == s.origin.command && u32(s.canonical_display16 + 4) == saved_bytes - 8);
        assert(!memcmp(s.canonical_display16 + 8, saved_wire + 8, saved_bytes - 8));
        for (unsigned int i = saved_bytes; i < FCAM_DISPLAY_INPUT_BYTES; i++) assert(!s.canonical_display16[i]);
        assert(!memcmp(s.canonical_layout32, before.canonical_layout32, sizeof s.canonical_layout32));
        assert(!memcmp(s.canonical_zebra8, before.canonical_zebra8, sizeof s.canonical_zebra8));
    } else if (layout) {
        assert(!memcmp(s.canonical_layout32, saved_wire + 8, sizeof s.canonical_layout32));
        assert(!memcmp(s.canonical_zebra8, before.canonical_zebra8, sizeof s.canonical_zebra8));
    } else {
        assert(!memcmp(s.canonical_zebra8, saved_wire + 8, 5));
        assert(!s.canonical_zebra8[5] && !s.canonical_zebra8[6] && !s.canonical_zebra8[7]);
    }
    assert(!s.busy && !s.guard_held && reservations == unlocks && init_calls == 1 && path_calls == calls + 1);
    if (starts("result-") || starts("mutated-") || starts("bridge-") || starts("disable-forged-") || is("guard-lost")) {
        assert(rc < 0 && s.faults && !s.request_owned && !s.ap_consumed);
        assert(allocations == allocated && frees == released && sends == sent && s.completed_cycles == before.completed_cycles);
        cleanup(); return 0;
    }
    assert(!rc && s.model_complete && s.request_owned && s.model_result_bytes == (bb || layout ? 192u : display ? 176u : 168u));
    assert(!memcmp(s.model_result + FCAM_LAYOUT_R_CONFIG,
        bb ? s.canonical_bb32 : display ? s.canonical_display16 : layout ? s.canonical_layout32 : s.canonical_zebra8,
        bb || layout ? 32u : display ? 16u : 8u));
    if (starts("alloc-") || is("set-source-fail") || is("ack-write-corrupt") || is("request-free-fail") || is("send-fail")) {
        assert(s.faults && !s.ap_consumed);
        assert(s.leases[0].pointer == ((configured && !is("request-free-fail")) || is("send-fail") ? NULL : p));
        if ((!configured && (is("alloc-alias") || is("alloc-alias-interior"))) ||
            is("alloc-snapshot-tail") || is("alloc-display-tail") || is("alloc-bb-tail") || starts("alloc-constant-"))
            assert(s.allocation_alias && !s.leases[1].pointer);
        else if (is("alloc-alias") || is("alloc-alias-interior")) {
            assert(!s.allocation_alias && s.leases[0].freed && !s.leases[0].pointer);
            assert(s.leases[1].pointer == (unsigned char *)p + (is("alloc-alias-interior") ? 1 : 0));
            assert(size(s.leases[1].pointer) == saved_bytes);
            assert(arena_allocations == 1 && arena_frees == 1 && !arena_live);
            assert(!memcmp(p, saved_wire, saved_bytes));
        } else if (configured && is("request-free-fail")) assert(!s.leases[1].pointer && allocations == allocated);
        else if (!is("alloc-fail")) assert(s.leases[1].pointer);
        assert(sends == (is("send-fail") ? calls + 1 : calls));
        if (forced_fresh) {
            assert(!s.allocation_alias && s.allocation_returned == p && s.leases[1].pointer == p);
            assert(!s.leases[0].pointer && s.leases[0].freed && !s.leases[1].freed);
            assert(arena_allocations == 2 && arena_frees == 1 && arena_live);
            assert(allocations == allocated + 1 && frees == released + 1 && request_frees == calls + 1 && ack_frees == calls);
        }
        const unsigned int faults_before = s.faults, calls_before = path_calls, frees_before = frees;
        void *again = bb ? bb_request(bb_kind) : display ? display_request(display_kind) : layout ? layout_request() : zebra_request();
        assert(dispatch(again, 1, &io, &guard, &rc) == 1 && rc < 0);
        assert(snapshot().faults == faults_before && path_calls == calls_before && frees == frees_before);
        cleanup(); return 0;
    }
    if (forced_fresh) {
        assert(!s.allocation_alias && s.allocation_returned == p && ack_pointer == p);
        assert(s.leases[0].freed && !s.leases[0].pointer);
        assert(arena_allocations == 2 && allocations == allocated + 1 && request_frees == calls + 1);
        assert(arena_frees == (s.leases[1].freed ? 2u : 1u) && arena_live == !s.leases[1].freed);
    }
    if (is("inline-free") || is("inline-send-fail")) {
        assert(s.leases[1].freed && s.ack_received && s.ap_consumed == (unsigned int)is("inline-free"));
        assert(s.faults == (unsigned int)is("inline-send-fail")); cleanup(); return 0;
    }
    if (run_receive_failure()) { cleanup(); return 0; }
    if (is("free-before-receive")) {
        assert(functional_vdf_path_release_cycle(saved_source, ack_pointer, s.cycle, real_free, logger, &rc) == 1 && rc == -EPROTO);
        assert(snapshot().faults && frees == released + 1); cleanup(); return 0;
    }
    if (is("repeat-busy")) {
        void *again = bb_request((bb_kind + 1) % FCAM_BB_FEATURES); const unsigned int calls_before = path_calls;
        assert(dispatch(again, 1, &io, &guard, &rc) == 1 && rc == -EBUSY && path_calls == calls_before);
        dispose(again);
        saved_bytes = s.origin.bytes; saved_source = s.origin.source;
        memcpy(saved_wire, s.original_wire, sizeof saved_wire); active_request = p;
    }
    if (previous_ticket) {
        const unsigned int count = frees;
        assert(functional_vdf_path_release_cycle(saved_source, ack_pointer, previous_ticket, real_free, logger, &rc) == 1 && rc == -ESTALE);
        assert(frees == count && !snapshot().faults && snapshot().cycle > previous_ticket);
    }
    receive_ticket = observe(ack_pointer);
    if (is("foreign-free")) {
        pthread_t thread; struct foreign f = {ack_pointer, receive_ticket, 0};
        assert(!pthread_create(&thread, NULL, foreign, &f) && !pthread_join(thread, NULL));
        assert(snapshot().faults && snapshot().leases[1].pointer); cleanup(); return 0;
    }
    if (is("duplicate-receive")) {
        uint64_t ticket = 999;
        assert(functional_vdf_path_observe_receive_cycle(saved_source, ack_pointer, FUNCTIONAL_VDF_PATH_SID, 12, &ticket) == -EPROTO);
        assert(ticket == 999 && snapshot().faults); cleanup(); return 0;
    }
    if (is("ack-path-wire") || is("ack-zebra-wire") || is("ack-other-display") || is("ack-other-bb") || is("free-wire")) {
        memcpy(ack_pointer, is("ack-other-bb") ? bb_success[(bb_kind + 1) % FCAM_BB_FEATURES] :
            is("ack-other-display") ? (flag ? peaking_success : flag_success) :
            is("ack-zebra-wire") ? zebra_success : path_success, 12);
        assert(functional_vdf_path_release_cycle(saved_source, ack_pointer, receive_ticket, real_free, logger, &rc) == 1 && rc == -EPROTO);
        assert(snapshot().faults && snapshot().leases[1].pointer); cleanup(); return 0;
    }
    if (is("no-ticket") || is("old-ticket")) {
        const unsigned int count = frees;
        assert(functional_vdf_path_release_cycle(saved_source, ack_pointer, is("no-ticket") ? 0 : receive_ticket - 1,
            real_free, logger, &rc) == 1 && rc == -ESTALE);
        assert(frees == count && !snapshot().faults);
    }
    if (starts("free-meta-")) {
        if (is("free-meta-source")) envelope(ack_pointer)->source++;
        else envelope(ack_pointer)->size--;
        assert(functional_vdf_path_release_cycle(saved_source, ack_pointer, receive_ticket, real_free, logger, &rc) == 1 && rc == -EPROTO);
        assert(snapshot().faults && snapshot().leases[1].pointer); cleanup(); return 0;
    }
    if (is("ack-free-fail")) {
        assert(functional_vdf_path_release_cycle(saved_source, ack_pointer, receive_ticket, real_free, logger, &rc) == 1 && rc == -EIO);
        assert(snapshot().leases[1].pointer && snapshot().faults); consume(ack_pointer, receive_ticket);
        assert(snapshot().leases[1].freed && !snapshot().ap_consumed && snapshot().faults);
        if (forced_fresh) assert(arena_allocations == 2 && arena_frees == 2 && !arena_live && request_frees == calls + 1 && ack_frees == calls + 2);
        cleanup(); return 0;
    }
    consume(ack_pointer, receive_ticket); s = snapshot();
    if (is("reentrant-free")) { assert(s.faults && !s.ap_consumed); cleanup(); return 0; }
    assert(s.ap_consumed && !s.faults && s.completed_cycles == before.completed_cycles + 1);
    if (forced_fresh) assert(arena_allocations == 2 && arena_frees == 2 && !arena_live &&
        request_frees == calls + 1 && ack_frees == calls + 1 && frees == released + 2);
    assert(s.config_generation >= before.config_generation + 1);
    const unsigned int active = s.canonical_config[0];
    assert(s.frame_generation == s.before_frame_generation + active);
    assert(u32(s.model_result + FCAM_VDF_R_FRAME_CONSUMED) == active);
    if (!active) assert(!s.lease_generation && !u64(s.model_result + FCAM_VDF_R_ACTIVE_BYTES));
    if (bb && (is("mixed") || mixed_reuse || is("banks-mixed"))) {
        const uint64_t old_ticket = receive_ticket;
        void *old_address = ack_pointer;
        scenario = mixed_reuse ? "address-reuse" : "success";
        for (unsigned int i = 0; i < FCAM_BB_FEATURES * 2; i++) {
            accept(bb_request(i % FCAM_BB_FEATURES));
            if (mixed_reuse) assert(ack_pointer == old_address);
            const unsigned int count = frees;
            assert(functional_vdf_path_release_cycle(saved_source, ack_pointer, old_ticket, real_free, logger, &rc) == 1 && rc == -ESTALE);
            assert(frees == count && !snapshot().faults); finish_cycle();
        }
        for (unsigned int i = 0; i < FCAM_BB_FEATURES; i++) assert(model_bb_valid[i]);
        assert(snapshot().completed_cycles == before.completed_cycles + 11 && init_calls == 1);
    } else if (display && (is("mixed") || mixed_reuse)) {
        void *old_address = ack_pointer; const uint64_t old_ticket = receive_ticket;
        scenario = mixed_reuse ? "address-reuse" : "success";
        for (unsigned int step = 0; step < 7; step++) {
            if (step == 0 || step == 2) accept(request(step == 2));
            else if (step == 1) {
                void *off = display_request(1); const unsigned int calls_before = path_calls, freed_before = frees;
                assert(dispatch(off, 1, &io, &guard, &rc) == 1 && rc < 0);
                assert(!snapshot().faults && path_calls == calls_before && frees == freed_before); dispose(off); continue;
            } else if (step == 3) accept(layout_request());
            else if (step == 4) accept(zebra_request());
            else accept(display_request(step == 6));
            assert(snapshot().model_result_bytes == (step < 3 ? 160u : step == 3 ? 192u : step == 4 ? 168u : 176u));
            if (mixed_reuse) assert(ack_pointer == old_address);
            const unsigned int count = frees;
            assert(functional_vdf_path_release_cycle(saved_source, ack_pointer, old_ticket, real_free, logger, &rc) == 1 && rc == -ESTALE);
            assert(!snapshot().faults && frees == count); finish_cycle();
        }
        assert(snapshot().completed_cycles == before.completed_cycles + 7 && init_calls == 1);
    } else if (layout && (is("mixed") || mixed_reuse)) {
        void *old_address = ack_pointer; const uint64_t old_ticket = receive_ticket;
        scenario = mixed_reuse ? "address-reuse" : "success";
        for (unsigned int step = 0; step < 4; step++) {
            if (step == 0 || step == 2) accept(request(step == 2));
            else if (step == 1) accept(zebra_request());
            else accept(layout_request());
            struct functional_vdf_path_snapshot current = snapshot();
            assert(current.model_result_bytes == (step == 3 ? 192u : step == 1 ? 168u : 160u));
            if (mixed_reuse) assert(ack_pointer == old_address);
            const unsigned int count = frees;
            assert(functional_vdf_path_release_cycle(saved_source, ack_pointer, old_ticket, real_free, logger, &rc) == 1 && rc == -ESTALE);
            assert(!snapshot().faults && frees == count); finish_cycle();
        }
        assert(snapshot().completed_cycles == before.completed_cycles + 5 && init_calls == 1);
    } else if (is("repeat") || is("mixed") || is("address-reuse")) {
        const uint64_t old_ticket = receive_ticket;
        if (is("mixed")) {
            accept(request(0)); assert(snapshot().model_result_bytes == 160); finish_cycle();
        }
        accept(bb ? bb_request(bb_kind) : display ? display_request(display_kind) : layout ? layout_request() : zebra_request());
        assert(snapshot().model_result_bytes == (bb || layout ? 192u : display ? 176u : 168u));
        const unsigned int count = frees;
        assert(functional_vdf_path_release_cycle(saved_source, ack_pointer, old_ticket, real_free, logger, &rc) == 1 && rc == -ESTALE);
        assert(frees == count && !snapshot().faults); finish_cycle();
        if (is("mixed")) { accept(request(1)); assert(snapshot().model_result_bytes == 160); finish_cycle(); }
        assert(init_calls == 1 && snapshot().ap_consumed && !snapshot().faults);
    }
    assert(reservations == unlocks && logs); cleanup(); return 0;
}
static void check_bind(unsigned int source_id, int expected) {
    const struct functional_vdf_path_snapshot before = snapshot();
    assert(functional_vdf_path_bind_refresh_queue(source_id) == expected);
    struct functional_vdf_path_snapshot after = snapshot();
    if (!expected) {
        assert(after.refresh_queue_bound && after.refresh_queue_source == source_id);
        after.refresh_queue_bound = before.refresh_queue_bound;
        after.refresh_queue_source = before.refresh_queue_source;
    }
    assert(!memcmp(&before, &after, sizeof before));
}
static int run_bind(void) {
    const unsigned int global_source = UINT32_C(0x80946189);
    if (is("bind-invalid") || is("bind-once")) {
        if (is("bind-invalid")) {
            check_bind(0, -EINVAL); check_bind(UINT_MAX, -EINVAL); check_bind(FUNCTIONAL_VDF_PATH_SID, -EINVAL);
        }
        check_bind(global_source, 0); check_bind(global_source, 0);
        check_bind(global_source + 1, -ESTALE);
        check_bind(UINT32_C(0x81cf0012), -ESTALE);
        check_bind(0, -EINVAL); check_bind(UINT_MAX, -EINVAL); check_bind(FUNCTIONAL_VDF_PATH_SID, -EINVAL);
        assert(!init_calls && !path_calls && !allocations && !frees); return 0;
    }
    if (is("bind-busy-bound")) check_bind(global_source, 0);
    if (is("bind-retired")) scenario = "foreign-reuse";
    accept(request(1));
    if (is("bind-pending") || starts("bind-busy") || is("bind-fault")) {
        if (is("bind-fault")) {
            uint64_t ticket = 0;
            assert(functional_vdf_path_observe_receive_cycle(saved_source, ack_pointer,
                FUNCTIONAL_VDF_PATH_SID + 1, 12, &ticket) == -EPROTO && !ticket);
        }
        const int expected = is("bind-fault") ? -EPROTO : -EBUSY;
        check_bind(global_source, expected); check_bind(global_source + 1, expected);
        if (!is("bind-fault")) { finish_cycle(); check_bind(global_source, 0); }
        cleanup(); return 0;
    }
    void *retired = ack_pointer; finish_cycle();
    if (is("foreign-reuse")) {
        check_bind(global_source, 0);
        struct message *m = recycled; assert(m && retired == m->body && !live[0]);
        recycled = NULL; live[0] = m; m->source = global_source; memset(m->body, 0x9a, 12);
        uint64_t ticket = 99; int rc = 321; const unsigned int count = frees;
        assert(!functional_vdf_path_observe_receive_cycle(global_source, m->body, global_source, 12, &ticket) && ticket == 99);
        assert(!functional_vdf_path_release_cycle(global_source, m->body, 0, real_free, logger, &rc) && rc == 321 && frees == count);
        dispose(m->body); cleanup(); return 0;
    }
    const int other_command = starts("bind-domain-");
    if (other_command || is("bind-wrong-source") || is("bind-wrong-81cf") || is("bind-source-zero")) check_bind(global_source, 0);
    void *p;
    if (is("bind-domain-0138")) p = request(1);
    else if (is("bind-domain-0153")) p = zebra_request();
    else if (is("bind-domain-014c")) p = layout_request();
    else if (is("bind-domain-0152")) p = display_request(0);
    else if (is("bind-domain-0162")) p = display_request(1);
    else p = display_request(2);
    envelope(p)->source = is("bind-source-zero") ? 0 :
        is("bind-wrong-source") ? global_source + 1 :
        is("bind-unbound-81cf") || is("bind-wrong-81cf") ? UINT32_C(0x81cf0012) : global_source;
    const unsigned int original_source = envelope(p)->source;
    const struct functional_vdf_path_snapshot before = snapshot();
    const unsigned int calls = path_calls, allocated = allocations, released = frees, sent = sends, reserved = reservations;
    int rc = 999;
    assert(dispatch(p, 1, &io, &guard, &rc) == 1 && rc == FUNCTIONAL_VDF_PATH_BLOCKED);
    const struct functional_vdf_path_snapshot after = snapshot();
    assert(!memcmp(&before, &after, sizeof before) && !memcmp(p, saved_wire, saved_bytes));
    assert(envelope(p)->size == saved_bytes && envelope(p)->source == original_source && active_request == p);
    assert(path_calls == calls && allocations == allocated && frees == released && sends == sent && reservations == reserved);
    dispose(p); cleanup(); return 0;
}
int main(int argc, char **argv) {
    assert(argc == 2); scenario = argv[1];
    if (is("bind-before-init")) {
        struct functional_vdf_path_snapshot before, after;
        functional_vdf_path_snapshot(&before);
        assert(functional_vdf_path_bind_refresh_queue(UINT32_C(0x80946189)) == -ENODEV);
        functional_vdf_path_snapshot(&after); assert(!memcmp(&before, &after, sizeof before)); return 0;
    }
    assert(!functional_vdf_path_owner_init() && functional_vdf_path_owner_init() == -EALREADY);
    if (starts("bb0166-initial-")) observed_initial = 1;
    if (starts("bb0111-")) return run_config(5);
    if (starts("bb0166-")) return run_config(6);
    if (starts("bb0167-")) return run_config(7);
    if (starts("bb015f-")) return run_config(8);
    if (starts("bb0128-")) return run_config(9);
    if (starts("bind-")) return run_bind();
    if (starts("refresh-")) return run_config(4);
    if (starts("zebra-")) return run_config(0);
    if (starts("layout-")) return run_config(1);
    if (starts("peaking-")) return run_config(2);
    if (starts("flag-")) return run_config(3);
    unsigned int active = is("disable") || starts("disable-forged-") ? 0u : 1u;
    void *p = request(active); int rc = 999, handled;
    if (is("reentrant-dispatch")) {
        reentrant_request = message(24, UINT32_C(0x81cf61c4)); memcpy(reentrant_request, saved_wire, saved_bytes);
    }
    if (is("fork-held-lock")) {
        functional_vdf_path_test_hold_lock(); pid_t child = fork(); assert(child >= 0);
        if (!child) {
            struct functional_vdf_path_snapshot s; uint64_t ticket = 4;
            functional_vdf_path_snapshot(&s); assert(s.faults && s.owner_pid != getpid());
            assert(functional_vdf_path_owner_init() == -EXDEV);
            assert(functional_vdf_path_bind_refresh_queue(UINT32_C(0x80946189)) == -EXDEV);
            assert(dispatch(p, 1, &io, &guard, &rc) == 1 && rc == -EXDEV);
            assert(functional_vdf_path_observe_receive_cycle(1, p, 1, 12, &ticket) == -EXDEV);
            assert(functional_vdf_path_release_cycle(1, p, 1, real_free, logger, &rc) == 1 && rc == -EXDEV);
            _exit(0);
        }
        int status; assert(waitpid(child, &status, 0) == child && WIFEXITED(status) && !WEXITSTATUS(status));
        functional_vdf_path_test_drop_lock(); cleanup(); return 0;
    }
    struct full_imaging_io callbacks = io;
    struct native_cp_state_publication_guard g = guard;
    if (is("default-off") || is("enabled-two") || is("unrelated") || is("wrong-type") || is("wrong-destination")) {
        if (is("unrelated")) ((unsigned char *)p)[2]++;
        if (is("wrong-type")) ((unsigned char *)p)[0]++;
        if (is("wrong-destination")) handled = functional_vdf_path_dispatch(1, p, &io, &guard, 1, &rc);
        else handled = dispatch(p, is("default-off") ? 0 : is("enabled-two") ? 2 : 1, &io, &guard, &rc);
        assert(!handled && rc == 999 && !allocations && !sends && !init_calls && !reservations); cleanup(); return 0;
    }
    if (is("invalid-path")) ((unsigned char *)p)[8] = 2;
    if (is("invalid-pins")) ((unsigned char *)p)[9] = 6;
    if (is("invalid-body4")) ((unsigned char *)p)[12] = 3;
    if (is("invalid-flags")) ((unsigned char *)p)[6] = 0;
    if (is("invalid-header-size")) ((unsigned char *)p)[4] = 23;
    if (is("short-request")) envelope(p)->size = 23;
    if (is("long-request")) envelope(p)->size = 25;
    if (is("bad-source")) envelope(p)->source = UINT32_C(0x928407b9);
    if (is("missing-callback")) callbacks.source = NULL;
    if (is("missing-guard")) g.predecessor_ready = NULL;
    handled = dispatch(p, 1, &callbacks, &g, &rc);
    assert(handled == 1);
    if (starts("invalid-") || is("short-request") || is("long-request") || is("bad-source") ||
        is("missing-callback") || is("missing-guard") || is("guard-fail") || is("guard-miss")) {
        assert(rc < 0 && !init_calls && !path_calls && !allocations && !sends && !frees);
        assert(!snapshot().faults && !snapshot().busy && !snapshot().guard_held);
        assert(unlocks == (is("guard-miss") ? 1u : 0u)); cleanup(); return 0;
    }
    if (starts("init-") || starts("result-") || is("bridge-error") || is("bridge-positive") ||
        starts("mutated-") || is("guard-lost") || (starts("disable-forged-") && !is("disable-forged-lease"))) {
        struct functional_vdf_path_snapshot s = snapshot();
        assert(rc < 0 && s.faults && !s.request_owned && !allocations && !sends && !frees && !s.ap_consumed);
        assert(!s.busy && !s.guard_held && unlocks == 1);
        if (starts("init-")) assert(!path_calls && !s.model_initialized);
        else assert(init_calls == 1 && path_calls == 1);
        cleanup(); return 0;
    }
    assert(!rc && snapshot().model_complete && snapshot().model_result_bytes == FCAM_VDF_RESULT_BYTES &&
        init_calls == 1 && path_calls == 1);
    if (starts("alloc-") || is("set-source-fail") || is("ack-write-corrupt") || is("request-free-fail") || is("send-fail")) {
        struct functional_vdf_path_snapshot s = snapshot();
        assert(s.faults && s.request_owned && !s.ap_consumed);
        assert(s.leases[0].pointer == (is("send-fail") ? NULL : p));
        if (is("alloc-alias") || is("alloc-alias-interior") || starts("alloc-constant-")) {
            assert(s.allocation_alias);
            if (!starts("alloc-constant-")) assert(s.allocation_returned == (unsigned char *)p + (is("alloc-alias-interior") ? 1 : 0));
            assert(!s.leases[1].pointer && !memcmp(p, saved_wire, saved_bytes));
        } else if (!is("alloc-fail")) assert(s.leases[1].pointer);
        if (is("alloc-short") || is("alloc-long")) {
            const unsigned char *b = s.leases[1].pointer;
            for (size_t i = 0; i < 12; i++) assert(b[i] == 0xcc);
        }
        assert(sends == (is("send-fail") ? 1u : 0u)); cleanup(); return 0;
    }
    if (is("inline-free") || is("inline-send-fail")) {
        struct functional_vdf_path_snapshot s = snapshot();
        assert(s.leases[1].freed && !s.leases[1].pointer && s.ack_received && !s.leases[1].send_inflight);
        assert(s.ap_consumed == (unsigned int)is("inline-free") && s.faults == (unsigned int)is("inline-send-fail"));
        cleanup(); return 0;
    }
    assert(snapshot().ack_queued && !snapshot().ack_received && !snapshot().ap_consumed);
    if (run_receive_failure()) { cleanup(); return 0; }
    if (is("free-before-receive")) {
        assert(functional_vdf_path_release_cycle(UINT32_C(0x81cf61c4), ack_pointer, snapshot().cycle, real_free, logger, &rc) == 1 && rc == -EPROTO);
        assert(!ack_frees && snapshot().faults && snapshot().leases[1].pointer); cleanup(); return 0;
    }
    if (is("repeat-busy")) {
        void *again = request(1); const unsigned int calls = path_calls;
        assert(dispatch(again, 1, &io, &guard, &rc) == 1 && rc == -EBUSY && path_calls == calls);
        dispose(again);
    }
    receive_ticket = observe(ack_pointer);
    if (is("no-ticket") || is("old-ticket")) {
        const unsigned int count = frees;
        assert(functional_vdf_path_release_cycle(UINT32_C(0x81cf61c4), ack_pointer,
            is("no-ticket") ? 0 : receive_ticket + 99, real_free, logger, &rc) == 1 && rc == -ESTALE);
        assert(frees == count && !snapshot().faults && snapshot().leases[1].pointer);
    }
    if (is("foreign-free")) {
        pthread_t thread; struct foreign f = {ack_pointer, receive_ticket, 0};
        assert(!pthread_create(&thread, NULL, foreign, &f) && !pthread_join(thread, NULL));
        assert(!ack_frees && snapshot().faults); cleanup(); return 0;
    }
    if (is("duplicate-receive")) {
        uint64_t ticket = 987;
        assert(functional_vdf_path_observe_receive_cycle(UINT32_C(0x81cf61c4), ack_pointer,
            FUNCTIONAL_VDF_PATH_SID, 12, &ticket) == -EPROTO && ticket == 987);
        assert(snapshot().faults && !snapshot().ap_consumed); cleanup(); return 0;
    }
    if (starts("free-meta-") || is("free-wire")) {
        if (is("free-meta-source")) envelope(ack_pointer)->source++;
        if (is("free-meta-size")) envelope(ack_pointer)->size--;
        if (is("free-wire")) ((unsigned char *)ack_pointer)[10] ^= 1;
        assert(functional_vdf_path_release_cycle(UINT32_C(0x81cf61c4), ack_pointer, receive_ticket,
            real_free, logger, &rc) == 1 && rc == -EPROTO);
        assert(!ack_frees && snapshot().faults && snapshot().leases[1].pointer); cleanup(); return 0;
    }
    if (is("ack-free-fail")) {
        assert(functional_vdf_path_release_cycle(UINT32_C(0x81cf61c4), ack_pointer, receive_ticket,
            real_free, logger, &rc) == 1 && rc == -EIO);
        assert(snapshot().leases[1].pointer == ack_pointer && snapshot().ack_received && snapshot().faults);
        consume(ack_pointer, receive_ticket);
        assert(snapshot().leases[1].freed && !snapshot().ap_consumed && snapshot().faults); cleanup(); return 0;
    }
    void *first_ack = ack_pointer; const uint64_t first_ticket = receive_ticket;
    consume(ack_pointer, receive_ticket);
    if (is("reentrant-free")) { assert(snapshot().faults && !snapshot().ap_consumed); cleanup(); return 0; }
    struct functional_vdf_path_snapshot first = snapshot();
    assert(first.ap_consumed && first.completed_cycles == 1 && !first.faults && first.requests == 1);
    assert(!first.leases[0].pointer && !first.leases[1].pointer && first.phase == FUNCTIONAL_VDF_PATH_AP_CONSUMED);
    if (!first.leases[0].pointer && !first.leases[1].pointer && is("foreign-reuse")) {
        struct message *foreign = recycled; assert(foreign && first_ack == foreign->body && !live[0]);
        recycled = NULL; live[0] = foreign; foreign->source = UINT32_C(0x90030001);
        memset(foreign->body, 0x9a, 12);
        uint64_t unrelated_ticket = UINT64_C(0x12345678); unsigned int count = frees; rc = 321;
        assert(!functional_vdf_path_observe_receive_cycle(UINT32_C(0x80020002), foreign->body,
            foreign->source, 12, &unrelated_ticket) && unrelated_ticket == UINT64_C(0x12345678));
        assert(!functional_vdf_path_release_cycle(UINT32_C(0x80020002), foreign->body, 0,
            real_free, logger, &rc) && rc == 321 && frees == count);
        assert(functional_vdf_path_release_cycle(UINT32_C(0x81cf61c4), foreign->body, first_ticket,
            real_free, logger, &rc) == 1 && rc == -ESTALE && frees == count && !snapshot().faults);
        dispose(foreign->body); cleanup(); return 0;
    }
    if (is("disable")) {
        assert(first.frame_generation == 2 && first.config_generation == 8);
        assert(!u32(first.model_result + FCAM_VDF_R_FRAME_CONSUMED) && !u64(first.model_result + FCAM_VDF_R_ACTIVE_BYTES));
    }
    if (is("opaque")) {
        assert(!memcmp(first.original_wire, saved_wire, saved_bytes));
        assert(!memcmp(first.canonical_config, saved_wire + 8, 13));
        assert(!first.canonical_config[13] && !first.canonical_config[14] && !first.canonical_config[15]);
    }
    if (is("repeat") || is("repeat-disable") || is("address-reuse") || is("repeat-old-lease") || is("disable-forged-lease")) {
        const unsigned int enabled = is("repeat-disable") || is("disable-forged-lease") ? 0u : 1u;
        void *again = request(enabled);
        if (is("repeat-old-lease") || is("disable-forged-lease")) {
            assert(dispatch(again, 1, &io, &guard, &rc) == 1 && rc < 0);
            assert(snapshot().faults && !snapshot().request_owned && path_calls == 2 && init_calls == 1);
            cleanup(); return 0;
        }
        accept(again); assert(path_calls == 2 && init_calls == 1 && !snapshot().ap_consumed);
        if (is("address-reuse")) assert(first_ack == ack_pointer);
        unsigned int count = frees;
        assert(functional_vdf_path_release_cycle(UINT32_C(0x81cf61c4), ack_pointer, first_ticket,
            real_free, logger, &rc) == 1 && rc == -ESTALE && frees == count && !snapshot().faults);
        receive_ticket = observe(ack_pointer); assert(receive_ticket > first_ticket);
        assert(functional_vdf_path_release_cycle(UINT32_C(0x81cf61c4), ack_pointer, first_ticket,
            real_free, logger, &rc) == 1 && rc == -ESTALE && frees == count);
        consume(ack_pointer, receive_ticket);
        struct functional_vdf_path_snapshot last = snapshot();
        assert(last.completed_cycles == 2 && last.ap_consumed && last.config_generation == 9 && !last.faults);
        assert(last.frame_generation == first.frame_generation + enabled);
    }
    assert(reservations == unlocks && !snapshot().busy && !snapshot().guard_held && logs);
    cleanup(); puts("HOST_TEST VDF transport owner only; CMOS/CP FIFO/RTOS/capture unverified"); return 0;
}
