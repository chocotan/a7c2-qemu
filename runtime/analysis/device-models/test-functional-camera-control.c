/* SPDX-License-Identifier: MIT */
#define _GNU_SOURCE
#ifndef HOST_TEST
#error This fixture supplies a mock bridge and must never be linked into production.
#endif
#include "functional-camera-control.h"
#include "../functional-camera-events.h"
#include <assert.h>
#include <pthread.h>
#include <stddef.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/syscall.h>
#include <sys/wait.h>
#include <unistd.h>

/* Mock State128 exercises the owner; no host render, native CP or AP capture evidence. */
/* Public libosal_uipc: 24-byte header, source at payload-12, size at payload-8. */
struct message { void *next; unsigned int flags, source, size, reserved; unsigned char body[]; };
_Static_assert(offsetof(struct message, body) == 24, "original OSAL header");
static struct message *live[64];
static const char *scenario;
static unsigned int allocations, sends, frees, reservations, unlocks, bridge_calls, prior_calls, records;
static unsigned int reentry, nested_frees, bridge_op[16];
static void *active_request, *ack_pointer, *notice_pointer, *reentrant_request, *allocated_ack;
static unsigned char host_state[FCAM_STATE_BYTES], last_probe_state[FCAM_STATE_BYTES];
static char latest_record[2560];
static unsigned int send_sizes[16];
static struct message *recycled[2];
static void *retired_ack, *retired_notice;
static uint64_t ack_cycle, notice_cycle;
static unsigned char retired_wire[CP_STATE_SNAPSHOT_BYTES];
static int dispatch(void *, int, int *);
static int repeat_case(void) { return !strncmp(scenario, "repeat-", 7); }
static int native_case(void) { return !strncmp(scenario, "native-ack-", 11); }
static int native_send(unsigned int, void *, unsigned int, uint64_t);

static const struct full_imaging_io io;
static const struct native_cp_state_publication_guard guard;
static int is(const char *name) { return !strcmp(scenario, name); }
static struct message *envelope(void *p) { return (struct message *)((unsigned char *)p - offsetof(struct message, body)); }
static uint32_t read32(const unsigned char *p) { return p[0] | (uint32_t)p[1] << 8 | (uint32_t)p[2] << 16 | (uint32_t)p[3] << 24; }
static uint64_t read64(const unsigned char *p) { return read32(p) | (uint64_t)read32(p + 4) << 32; }
static void write32(unsigned char *p, uint32_t v) { for (unsigned int i = 0; i < 4; i++) p[i] = (unsigned char)(v >> (8u * i)); }
static void write64(unsigned char *p, uint64_t v) { write32(p, (uint32_t)v); write32(p + 4, (uint32_t)(v >> 32)); }
static uint64_t fnv(const void *p, size_t n) {
    const unsigned char *b = p; uint64_t h = UINT64_C(14695981039346656037);
    for (size_t i = 0; i < n; i++) h = (h ^ b[i]) * UINT64_C(1099511628211);
    return h;
}
static void *message(unsigned int size, unsigned int source) {
    unsigned int slot = size == CP_STATE_SNAPSHOT_BYTES ? 1 : 0;
    struct message *m = NULL;
    if (!source && (is("repeat-address-reuse") || is("native-ack-address-reuse")) && (size == 12 || size == CP_STATE_SNAPSHOT_BYTES)) {
        m = recycled[slot]; recycled[slot] = NULL;
    }
    if (!m) m = malloc(sizeof *m + size);
    assert(m);
    m->size = size; m->source = source; memset(m->body, 0, size);
    for (size_t i = 0; i < sizeof live / sizeof *live; i++) if (!live[i]) { live[i] = m; return m->body; }
    assert(0); return NULL;
}
static void dispose(void *p) {
    struct message *m = envelope(p);
    for (size_t i = 0; i < sizeof live / sizeof *live; i++) if (live[i] == m) {
        live[i] = NULL;
        if ((is("repeat-address-reuse") || is("native-ack-address-reuse")) && m->source == FUNCTIONAL_CAMERA_CONTROL_SID &&
            (m->size == 12 || m->size == CP_STATE_SNAPSHOT_BYTES)) {
            unsigned int slot = m->size == CP_STATE_SNAPSHOT_BYTES ? 1 : 0;
            assert(!recycled[slot]); recycled[slot] = m;
        } else free(m);
        return;
    }
    assert(0);
}
static void cleanup(void) {
    for (size_t i = 0; i < sizeof live / sizeof *live; i++) if (live[i]) { free(live[i]); live[i] = NULL; }
    for (size_t i = 0; i < 2; i++) { free(recycled[i]); recycled[i] = NULL; }
}
static void inspect(void) {
    struct native_functional_camera_control_snapshot s;
    native_functional_camera_control_snapshot(&s);
    assert(s.owner_pid == getpid() && s.functional_model == 1 && !s.original_cp && !s.physical_asic_verified);
    assert(!s.ee && !s.frame && !s.capture && !s.start_original_known_mask && !s.full_original_source_known);
    if (is("reentrant-dispatch") && reentrant_request && !reentry) {
        int rc = 987; reentry = 1;
        assert(native_functional_camera_control_dispatch(FUNCTIONAL_CAMERA_CONTROL_SID, reentrant_request,
            &io, &guard, 1, &rc) == 1 && rc < 0);
        reentry = 0;
    }
}
static int allocate(unsigned int destination, void **p, unsigned int size, unsigned int option) {
    inspect(); assert(destination == FUNCTIONAL_CAMERA_CONTROL_AP && option == 1); allocations++;
    if ((is("alloc-start-fail") && allocations == 1) || (is("alloc-mode-fail") && allocations == 2) ||
        (is("alloc-notice-fail") && allocations == 3)) { *p = NULL; return -ENOMEM; }
    if (is("alloc-alias-request") && allocations == 1) { *p = (unsigned char *)active_request + 2; return 0; }
    if (is("alloc-alias-ack") && allocations == 3) { *p = allocated_ack; return 0; }
    *p = message(size, 0); if (size == 12 || size == 16) allocated_ack = *p;
    if (is("alloc-short") || is("alloc-long")) { memset(*p, 0xcc, size); envelope(*p)->size = is("alloc-short") ? size - 1 : size + 1; }
    if (is("alloc-dirty-failure")) return -ENOMEM;
    return 0;
}
static int release(unsigned int destination, void *p) {
    inspect(); assert(destination == FUNCTIONAL_CAMERA_CONTROL_AP || destination == FUNCTIONAL_CAMERA_CONTROL_SID);
    frees++;
    if (is("repeat-free-inflight") && envelope(p)->size == CP_STATE_SNAPSHOT_BYTES) {
        void *again = message(12, FUNCTIONAL_CAMERA_CONTROL_AP); unsigned char *b = again;
        b[0] = 5; b[2] = 0x73; b[3] = 0x40; b[8] = 1;
        int rc = 123; unsigned int calls = bridge_calls;
        assert(dispatch(again, 1, &rc) == 1 && rc == -EBUSY && bridge_calls == calls);
        dispose(again);
    }
    if (is("alloc-short") || is("alloc-long")) {
        assert(!envelope(p)->source);
        for (size_t i = 0; i < 16; i++) assert(((unsigned char *)p)[i] == 0xcc);
    }
    if ((is("request-free-fail") && destination == FUNCTIONAL_CAMERA_CONTROL_SID) ||
        (is("ack-free-fail") && envelope(p)->body[0] == 1) ||
        (is("native-ack-free-fail") && envelope(p)->body[0] == 1) ||
        (is("notice-free-fail") && envelope(p)->size == CP_STATE_SNAPSHOT_BYTES)) return -EIO;
    if (is("reentrant-free") && destination == FUNCTIONAL_CAMERA_CONTROL_AP && envelope(p)->body[0] == 1 && !nested_frees) {
        int rc = 444; nested_frees++;
        assert(native_functional_camera_control_release(destination, p, release, NULL, &rc) == 1 && rc == -EPROTO);
    }
    dispose(p); return 0;
}
static unsigned int size(void *p) { inspect(); return envelope(p)->size; }
static unsigned int source(void *p) { inspect(); return envelope(p)->source; }
static void set_source(void *p, unsigned int value) { inspect(); envelope(p)->source = value; }
static void logger(const char *tag, const char *text) {
    inspect(); records++;
    assert(strstr(tag, "FUNCTIONAL_CAMERA_CONTROL_") && strstr(text, "functional_model=1 original_CP=0 physical_ASIC_verified=0"));
    if (!strcmp(tag, "FUNCTIONAL_CAMERA_CONTROL_RECEIVE ")) {
        assert(strstr(text, "reason=") && strstr(text, "event_cycle=") && strstr(text, "lease_cycle="));
        assert(strstr(text, "send_inflight=") && strstr(text, "wire_checked=") && strstr(text, "expected_fnv1a="));
        if (native_case() && strstr(text, "index=1 ") && strstr(text, "reason=accepted "))
            assert(strstr(text, "ack_wire=010003302700008000f0000000000000 ") && strstr(text, "wire_fnv1a=7ef188e66a84bb78 "));
        return;
    }
    assert(strstr(text, "fixed_optics_policy=integrated-noneLIF LIF_tuple=0,0,0 cache4=0"));
    struct native_functional_camera_control_snapshot s; native_functional_camera_control_snapshot(&s);
    char xsync[192];
    int n = snprintf(xsync, sizeof xsync,
        "xsync_defined=%u xsync_source_fps=%u xsync_word=%u xsync_half=%u xsync_source_generation=%llu ",
        s.xsync_defined, s.xsync_source_fps, s.xsync_word, s.xsync_half, (unsigned long long)s.xsync_source_generation);
    assert(n > 0 && (size_t)n < sizeof xsync && strstr(text, xsync));
    assert(strstr(text, "original_getters_executed=0 original_source_proof=0 EE=0 frame=0 capture=0"));
    assert(strlen(text) < sizeof latest_record); strcpy(latest_record, text);
}
static int send(unsigned int destination, void *p) {
    inspect(); assert(destination == FUNCTIONAL_CAMERA_CONTROL_AP && sends < 16);
    send_sizes[sends++] = envelope(p)->size;
    int notice = envelope(p)->size == CP_STATE_SNAPSHOT_BYTES;
    struct native_functional_camera_control_snapshot sending; native_functional_camera_control_snapshot(&sending);
    if (notice) { notice_pointer = p; notice_cycle = sending.lease_cycle_id[4]; }
    else { ack_pointer = p; ack_cycle = sending.lease_cycle_id[sending.leases[1].pointer == p ? 1 : 3]; }
    if (native_case()) return native_send(destination, p, notice ? 4u : sends == 1 ? 1u : 3u, notice ? notice_cycle : ack_cycle);
    if ((is("repeat-send-inflight") && notice) || (is("repeat-post-send-failure") && bridge_calls == 3)) {
        int rc = 123;
        if (notice) assert(native_functional_camera_control_observe_receive_cycle(destination, p, FUNCTIONAL_CAMERA_CONTROL_SID, CP_STATE_SNAPSHOT_BYTES, notice_cycle) == 1);
        assert(native_functional_camera_control_release_cycle(destination, p, release, logger, &rc, notice ? notice_cycle : ack_cycle) == 1 && !rc);
        if (notice) notice_pointer = NULL; else ack_pointer = NULL;
        struct native_functional_camera_control_snapshot s; native_functional_camera_control_snapshot(&s);
        assert(s.busy && !s.mode1_complete);
        if (notice) {
            assert(s.leases[4].send_inflight && !s.leases[4].queued && s.leases[4].received && s.leases[4].freed);
            assert(!s.leases[4].pointer && !s.leases[4].consumed && !s.notification_ap_consumed);
            /* The inline receive/free precedes the send callback's successful return. */
            assert(s.full_notifications_queued == (bridge_calls == 2 ? 0u : 1u));
            assert(s.full_notifications_consumed == (bridge_calls == 2 ? 0u : 1u));
            assert(s.shadow_generation == (bridge_calls == 2 ? 0u : 1u));
            void *again = message(12, FUNCTIONAL_CAMERA_CONTROL_AP); unsigned char *b = again;
            b[0] = 5; b[2] = 0x73; b[3] = 0x40; b[8] = 1;
            unsigned int calls = bridge_calls;
            assert(dispatch(again, 1, &rc) == 1 && rc == -EBUSY && bridge_calls == calls); dispose(again);
            if (is("repeat-post-send-failure")) return -EPIPE;
        }
    }
    if (is("repeat-address-reuse") && notice && bridge_calls == 4) {
        unsigned char current[CP_STATE_SNAPSHOT_BYTES]; memcpy(current, p, sizeof current);
        memcpy(p, retired_wire, sizeof current);
        assert(native_functional_camera_control_observe_receive_cycle(destination, p, FUNCTIONAL_CAMERA_CONTROL_SID, CP_STATE_SNAPSHOT_BYTES, notice_cycle) == -EPROTO);
        memcpy(p, current, sizeof current);
    }
    if (is("inline-free") || is("inline-send-fail")) {
        int rc = 123;
        if (notice) assert(native_functional_camera_control_observe_receive_cycle(destination, p, FUNCTIONAL_CAMERA_CONTROL_SID, CP_STATE_SNAPSHOT_BYTES, notice_cycle) == 1);
        assert(native_functional_camera_control_release_cycle(destination, p, release, logger, &rc, notice ? notice_cycle : ack_cycle) == 1 && !rc);
        if (notice) notice_pointer = NULL; else ack_pointer = NULL;
    }
    if ((is("send-start-fail") && sends == 1) || (is("send-mode-fail") && sends == 2) ||
        (is("send-notice-fail") && sends == 3) || is("inline-send-fail")) return -EPIPE;
    return 0;
}
static int reserve(void) { inspect(); reservations++; return is("guard-fail") ? -EBUSY : 0; }
static void unlock(void) { inspect(); unlocks++; }
static int prior(void) {
    inspect(); prior_calls++;
    return is("predecessor-fail") || (is("predecessor-lost") && prior_calls == 2) ||
        (is("repeat-lost-predecessor") && prior_calls == 6) ? 0 : 1;
}
static const struct full_imaging_io io = {allocate, release, set_source, send, size, source, logger};
static const struct native_cp_state_publication_guard guard = {reserve, unlock, prior};
static void seed(void) {
    write32(host_state + FCAM_S_ABI, FCAM_ABI_VERSION); write32(host_state + FCAM_S_CAPS, FCAM_CAPABILITIES);
    write32(host_state + FCAM_S_WIDTH, 640); write32(host_state + FCAM_S_HEIGHT, 480);
    write32(host_state + FCAM_S_FPS, 30); write32(host_state + FCAM_S_QUALITY, 90);
    write32(host_state + FCAM_S_FNUMBER, 400); write32(host_state + FCAM_S_ISO, 100);
    write64(host_state + FCAM_S_SHUTTER, 16667); write64(host_state + FCAM_S_FOCUS, 3000000);
    write64(host_state + FCAM_S_INSTANCE, UINT64_C(0x123456789abcdef)); write64(host_state + FCAM_S_GENERATION, repeat_case() ? (is("repeat-backward-generation") ? 2 : 1) : 7);
    write64(host_state + FCAM_S_RENDERED, is("state-counter-regression") ? 3 : 1);
    write64(host_state + FCAM_S_FRAME_GENERATION, is("state-counter-regression") ? 3 : 1);
}
int fcam_bridge_call(const struct fcam_native_origin *origin, uint32_t opcode, const void *input, size_t input_bytes,
                     void *output, size_t capacity, struct fcam_bridge_result *result) {
    inspect(); assert(active_request && origin && result && !input && !input_bytes && output && capacity == FCAM_STATE_BYTES);
    assert(bridge_calls < 16); bridge_op[bridge_calls++] = opcode;
    const unsigned char *native = active_request;
    assert(origin->source == FUNCTIONAL_CAMERA_CONTROL_AP && origin->destination == FUNCTIONAL_CAMERA_CONTROL_SID);
    assert(origin->command == (unsigned int)(native[2] | native[3] << 8) && origin->bytes == envelope(active_request)->size);
    assert(origin->wire_fnv1a64 == fnv(active_request, origin->bytes));
    assert(opcode == (native[0] == 0 ? FCAM_OP_INIT : FCAM_OP_STATE));
    if (is("missing-broker")) return -ENODEV;
    if (is("bridge-error")) { memset(output, 0x55, capacity); return -EIO; }
    if (is("checksum-error")) return -EBADMSG;
    unsigned char bytes[FCAM_STATE_BYTES]; memcpy(bytes, host_state, sizeof bytes);
    if (bridge_calls == 3) {
        if (is("repeat-bridge-failure")) return -ENODEV;
        if (is("repeat-backward-generation")) write64(bytes + FCAM_S_GENERATION, 1);
        if (is("repeat-wrong-instance")) write64(bytes + FCAM_S_INSTANCE, read64(bytes + FCAM_S_INSTANCE) + 1);
        if (is("repeat-lost-capability")) write32(bytes + FCAM_S_CAPS, FCAM_CAPABILITIES & ~FCAM_CAP_FIXED_OPTICS);
        if (is("repeat-lost-source")) envelope(active_request)->source++;
    }
    if (is("wrong-abi")) write32(bytes + FCAM_S_ABI, 2);
    if (is("missing-cap")) write32(bytes + FCAM_S_CAPS, FCAM_CAPABILITIES & ~FCAM_CAP_H264);
    if (is("unknown-cap")) write32(bytes + FCAM_S_CAPS, FCAM_CAPABILITIES | 16u);
    if (is("zero-instance")) write64(bytes + FCAM_S_INSTANCE, 0);
    if (is("zero-generation")) write64(bytes + FCAM_S_GENERATION, 0);
    if (is("wide-generation")) write64(bytes + FCAM_S_GENERATION, UINT64_C(0x100000000));
    if (is("zero-width")) write32(bytes + FCAM_S_WIDTH, 0);
    if (is("wide-width")) write32(bytes + FCAM_S_WIDTH, FCAM_MAX_STILL_WIDTH + 1);
    if (is("zero-height")) write32(bytes + FCAM_S_HEIGHT, 0);
    if (is("wide-height")) write32(bytes + FCAM_S_HEIGHT, FCAM_MAX_STILL_HEIGHT + 1);
    if (is("bad-fps")) write32(bytes + FCAM_S_FPS, 121);
    if (is("bad-quality")) write32(bytes + FCAM_S_QUALITY, 101);
    if (is("bad-aperture")) write32(bytes + FCAM_S_FNUMBER, 401);
    if (is("zero-iso")) write32(bytes + FCAM_S_ISO, 0);
    if (is("zero-shutter")) write64(bytes + FCAM_S_SHUTTER, 0);
    if (is("bad-focus")) write64(bytes + FCAM_S_FOCUS, 99999);
    if (is("reserved-state")) bytes[127] = 1;
    if (is("no-render")) write64(bytes + FCAM_S_RENDERED, 0);
    if (is("no-frame")) write64(bytes + FCAM_S_FRAME_GENERATION, 0);
    if (is("bad-counter")) write64(bytes + FCAM_S_CONSUMED, 2);
    if (is("model-busy")) write32(bytes + FCAM_S_PENDING_RESULTS, 1);
    if (is("model-streaming")) write32(bytes + FCAM_S_STREAM_STATE, 1);
    if (is("model-fault")) write32(bytes + FCAM_S_STREAM_STATE, 3);
    if (opcode == FCAM_OP_STATE) {
        if (is("state-instance")) write64(bytes + FCAM_S_INSTANCE, read64(bytes + FCAM_S_INSTANCE) + 1);
        if (is("state-regression")) write64(bytes + FCAM_S_GENERATION, 6);
        if (is("state-changed-same-generation")) write32(bytes + FCAM_S_WIDTH, 1280);
        if (is("state-counter-regression")) write64(bytes + FCAM_S_RENDERED, 2);
        if (is("state-advanced")) {
            write64(bytes + FCAM_S_GENERATION, 9); write32(bytes + FCAM_S_WIDTH, 1280);
            write32(bytes + FCAM_S_FNUMBER, 800);
        }
        if (is("state-checksum-error")) return -EBADMSG;
    }
    memcpy(output, bytes, sizeof bytes); memcpy(last_probe_state, bytes, sizeof bytes);
    *result = (struct fcam_bridge_result){FCAM_STATE_BYTES, FCAM_STATE_BYTES, read64(bytes + FCAM_S_INSTANCE), 0};
    if (is("instance-metadata")) result->model_instance++;
    if (is("short-result")) result->used--;
    if (is("long-result")) result->used++;
    if (is("long-required")) result->required++;
    if (is("token-state")) result->result_token = 1;
    if (is("output-guard")) ((unsigned char *)output)[capacity] = 0;
    if (is("mutated-request")) ((unsigned char *)active_request)[23] = 1;
    return 0;
}
static void *request(int mode) {
    unsigned char *p = message(mode ? 12 : 24, FUNCTIONAL_CAMERA_CONTROL_AP);
    p[0] = mode ? 5 : 0; p[1] = 1; p[2] = mode ? 0x73 : is("start-3000") ? 0 : 3; p[3] = mode ? 0x40 : 0x30;
    p[4] = 0x78; p[5] = 0x56; p[6] = 0x34; p[7] = 0x12; if (mode) p[8] = 1;
    if (native_case()) { p[1] = 0; write32(p + 4, 0x80000027); }
    return p;
}
static int dispatch(void *p, int enabled, int *result) {
    void *previous = active_request; active_request = p;
    int handled = native_functional_camera_control_dispatch(FUNCTIONAL_CAMERA_CONTROL_SID, p, &io, &guard, enabled, result);
    active_request = previous; return handled;
}
static void free_ack(void) {
    if (!ack_pointer) return;
    int rc = 999;
    if(is("repeat-events-adapter")){
        assert(functional_camera_events_observe_receive(FUNCTIONAL_CAMERA_CONTROL_AP,ack_pointer,
            FUNCTIONAL_CAMERA_CONTROL_SID,envelope(ack_pointer)->size)==1);
        assert(functional_camera_events_release(FUNCTIONAL_CAMERA_CONTROL_AP,ack_pointer,release,logger,&rc)==1 && !rc);
    }else assert(native_functional_camera_control_release_cycle(FUNCTIONAL_CAMERA_CONTROL_AP, ack_pointer, release, logger, &rc, ack_cycle) == 1 && !rc);
    ack_pointer = NULL;
}
static void *bad_ack_thread(void *unused) {
    (void)unused; int rc = 123;
    assert(native_functional_camera_control_release_cycle(FUNCTIONAL_CAMERA_CONTROL_AP, ack_pointer, release, logger, &rc, ack_cycle) == 1 && rc == -EPROTO);
    return NULL;
}
static void *receive_thread(void *unused) {
    (void)unused;
    if(is("repeat-events-adapter")){
        assert(functional_camera_events_observe_receive(FUNCTIONAL_CAMERA_CONTROL_AP,notice_pointer,
            FUNCTIONAL_CAMERA_CONTROL_SID,CP_STATE_SNAPSHOT_BYTES)==1);
        int rc=123;
        assert(functional_camera_events_release(FUNCTIONAL_CAMERA_CONTROL_AP,notice_pointer,release,logger,&rc)==1 && !rc);
    }else{
        assert(native_functional_camera_control_observe_receive_cycle(FUNCTIONAL_CAMERA_CONTROL_AP, notice_pointer,
            FUNCTIONAL_CAMERA_CONTROL_SID, CP_STATE_SNAPSHOT_BYTES, notice_cycle) == 1);
        int rc = 123;
        assert(native_functional_camera_control_release_cycle(FUNCTIONAL_CAMERA_CONTROL_AP, notice_pointer, release, logger, &rc, notice_cycle) == 1 && !rc);
    }
    notice_pointer = NULL; return NULL;
}
static void *bad_notice_thread(void *unused) {
    (void)unused; int rc = 123;
    assert(native_functional_camera_control_release(FUNCTIONAL_CAMERA_CONTROL_AP, notice_pointer, release, logger, &rc) == 1 && rc == -EPROTO);
    return NULL;
}
static void run_thread(void *(*fn)(void *)) { pthread_t thread; assert(!pthread_create(&thread, NULL, fn, NULL)); assert(!pthread_join(thread, NULL)); }
static void check_full(unsigned int aperture, unsigned int generation, unsigned int shadow) {
    const unsigned char *p = notice_pointer;
    assert(p && envelope(notice_pointer)->size == CP_STATE_SNAPSHOT_BYTES && envelope(notice_pointer)->source == FUNCTIONAL_CAMERA_CONTROL_SID);
    unsigned char expected[CP_STATE_SNAPSHOT_BYTES] = {6, 0, 0x40, 0x20}, known[CP_STATE_SNAPSHOT_BYTES];
    struct native_functional_camera_control_snapshot s; native_functional_camera_control_snapshot(&s);
    const unsigned int fps = read32(s.model_state + FCAM_S_FPS);
    assert(s.xsync_defined == 1 && s.xsync_source_fps == fps && s.xsync_word == fps && s.xsync_half == 1);
    assert(s.xsync_source_generation == generation && s.config_generation == generation);
    assert(s.projected_blocks == 3 && s.zero_policy_blocks == 72);
    memset(known, 1, sizeof known);
    for (size_t i = 0; i < CP_FULL_STATE_SNAPSHOT_BLOCKS; i++) {
        const struct cp_full_state_snapshot_block b = cp_full_state_snapshot_blocks[i];
        unsigned char *q = expected + b.offset; q[0] = 6; q[2] = (unsigned char)b.command; q[3] = (unsigned char)(b.command >> 8);
        assert(p[b.offset] == 6 && read32(p + b.offset + 4) == 0);
        if (b.command == 0x2012) q[10] = 0x77;
        if (b.command == 0x201b) { q[8] = (unsigned char)aperture; q[9] = (unsigned char)(aperture >> 8); }
        if (b.command == 0x20a6) {
            assert(b.offset == 0x664 && b.bytes == 16 && s.block_projected[i] == 1);
            write32(q + 8, fps); q[12] = 1;
        }
        if (b.command == 0x2044) {
            q[8] = 1; q[0x18] = q[0x20] = q[0x28] = q[0x30] = 10;
            q[0x24] = 0x40; q[0x2c] = 0x60; q[0x2d] = 1;
            memcpy(q + 0x34, "Virtual functional fixed optics", 32);
        }
    }
    assert(!memcmp(p, expected, sizeof expected));
    const struct cp_state_snapshot_input input = {p, known, sizeof expected, sizeof known,
        {CP_STATE_SNAPSHOT_PUBLISHED_BYTES, generation, generation, shadow}};
    struct cp_state_snapshot copied;
    assert(!cp_full_state_snapshot_copy(&input, &copied));
    assert(copied.aperture_words[0] == aperture && copied.lens_wire_state == 1);
    for (size_t i = 1; i < 5; i++) assert(!copied.aperture_words[i]);
    assert(!memcmp(copied.bytes + 0x14c, "\x06\x00\x12\x20\x00\x00\x00\x00\x00\x00\x77\x00", 12));
    assert(!memcmp(copied.bytes + 0x664, expected + 0x664, 16));
    for (size_t i = 0; i < sizeof copied.known; i++) assert(copied.known[i] == 1);
    assert(copied.generation.mutable_generation == generation && copied.generation.published_generation == generation &&
        copied.generation.shadow_generation == shadow);
}
static int early_case(void *p) {
    int rc = 123, handled;
    if (is("fork-held-lock")) {
        native_functional_camera_control_test_hold_lock();
        pid_t child = fork(); assert(child >= 0);
        if (!child) {
            struct native_functional_camera_control_snapshot s;
            assert(native_functional_camera_control_owner_init() == -EXDEV);
            assert(dispatch(p, 1, &rc) == 1 && rc == -EXDEV);
            assert(native_functional_camera_control_release(FUNCTIONAL_CAMERA_CONTROL_AP, p, release, logger, &rc) == 1 && rc == -EXDEV);
            assert(native_functional_camera_control_observe_receive(FUNCTIONAL_CAMERA_CONTROL_AP, p, FUNCTIONAL_CAMERA_CONTROL_SID, 24) == -EXDEV);
            native_functional_camera_control_snapshot(&s); assert(s.faults && !s.business_ready && !s.capture);
            _exit(0);
        }
        native_functional_camera_control_test_drop_lock();
        int status; assert(waitpid(child, &status, 0) == child && WIFEXITED(status) && !WEXITSTATUS(status)); return 1;
    }
    if (is("disabled")) { assert(!dispatch(p, 0, &rc) && rc == 123); return 1; }
    if (is("unrelated")) { ((unsigned char *)p)[2] = 0x12; assert(!dispatch(p, 1, &rc) && rc == 123); return 1; }
    if (is("wrong-type")) { ((unsigned char *)p)[0] = 9; assert(!dispatch(p, 1, &rc) && rc == 123); return 1; }
    if (is("wrong-destination")) {
        assert(!native_functional_camera_control_dispatch(FUNCTIONAL_CAMERA_CONTROL_AP, p, &io, &guard, 1, &rc) && rc == 123); return 1;
    }
    if (is("mode0") || is("mode2") || is("unknown-mode") || is("mode-wide-value") || is("mode-before-start")) {
        dispose(p); p = request(1); ((unsigned char *)p)[8] = is("mode0") ? 0 : is("mode2") ? 2 : is("unknown-mode") ? 7 : 1;
        if (is("mode-wide-value")) ((unsigned char *)p)[9] = 1;
        handled = dispatch(p, 1, &rc);
        assert(is("mode-before-start") ? handled == 1 && rc < 0 : !handled && rc == 123); return 1;
    }
    if (is("short-mode") || is("long-mode")) {
        dispose(p); p = message(is("short-mode") ? 11 : 13, FUNCTIONAL_CAMERA_CONTROL_AP);
        ((unsigned char *)p)[0] = 5; ((unsigned char *)p)[2] = 0x73; ((unsigned char *)p)[3] = 0x40; ((unsigned char *)p)[8] = 1;
        assert(dispatch(p, 1, &rc) == 1 && rc < 0); return 1;
    }
    if (is("short-start")) envelope(p)->size--;
    else if (is("long-start")) { dispose(p); p = message(25, FUNCTIONAL_CAMERA_CONTROL_AP); ((unsigned char *)p)[2] = 3; ((unsigned char *)p)[3] = 0x30; }
    else if (is("start-tail")) ((unsigned char *)p)[23] = 1;
    else if (is("bad-source")) envelope(p)->source++;
    else if (is("missing-callback")) {
        struct full_imaging_io incomplete = io; incomplete.send = NULL;
        assert(native_functional_camera_control_dispatch(FUNCTIONAL_CAMERA_CONTROL_SID, p, &incomplete, &guard, 1, &rc) == 1 && rc < 0); return 1;
    } else if (is("missing-guard")) {
        assert(native_functional_camera_control_dispatch(FUNCTIONAL_CAMERA_CONTROL_SID, p, &io, NULL, 1, &rc) == 1 && rc < 0); return 1;
    } else return 0;
    assert(dispatch(p, 1, &rc) == 1 && rc < 0); return 1;
}
static int init_refusal(void) {
    static const char *const cases[] = {"missing-broker", "bridge-error", "checksum-error", "wrong-abi", "missing-cap", "unknown-cap",
        "zero-instance", "instance-metadata", "zero-generation", "wide-generation", "zero-width", "wide-width", "zero-height", "wide-height",
        "bad-fps", "bad-quality", "bad-aperture", "zero-iso", "zero-shutter", "bad-focus", "reserved-state", "no-render", "no-frame",
        "bad-counter", "model-busy", "model-streaming", "model-fault", "short-result", "long-result", "long-required", "token-state",
        "output-guard", "guard-fail", "predecessor-fail", "predecessor-lost", "mutated-request"};
    for (size_t i = 0; i < sizeof cases / sizeof *cases; i++) if (is(cases[i])) return 1;
    return 0;
}
static int strict_refusal(void *context, struct cp_start_state_data *out, struct cp_start_state_guard *source_guard) {
    assert(!context); (void)out; (void)source_guard; return -ENODATA;
}
static void assert_busy_repeat(void) {
    void *again = request(1); int rc = 123;
    unsigned int calls = bridge_calls, allocated = allocations, sent = sends;
    assert(dispatch(again, 1, &rc) == 1 && rc == -EBUSY);
    assert(bridge_calls == calls && allocations == allocated && sends == sent); dispose(again);
}
static void assert_start_preserved(const struct native_functional_camera_control_snapshot *initial,
                                   const struct native_functional_camera_control_snapshot *s) {
    assert(s->owner_pid == initial->owner_pid && s->init_run_id == initial->init_run_id && s->start_requests == 1);
    assert(s->model_instance == initial->model_instance && s->start_defined_mask == initial->start_defined_mask);
    assert(!memcmp(s->leases, initial->leases, 2 * sizeof s->leases[0]));
    assert(!s->original_cp && !s->physical_asic_verified && !s->ee && !s->frame && !s->capture);
}
static void repeat_scenarios(const struct native_functional_camera_control_snapshot *initial) {
    struct native_functional_camera_control_snapshot s, previous;
    int rc = 123; void *p = request(1);
    assert(dispatch(p, 1, &rc) == 1 && !rc);
    native_functional_camera_control_snapshot(&s);
    unsigned int first_generation = is("repeat-backward-generation") ? 2 : 1;
    assert(s.mode1_requests == 1 && s.mode1_cycle_id == 1 && !s.mode1_ack_only && s.notification_mode == 1);
    assert(s.full_notifications_queued == 1);
    if (is("repeat-send-inflight")) {
        /* send rc0 commits the already observed receive/free before dispatch returns. */
        assert(s.full_notifications_consumed == 1 && s.shadow_generation == first_generation);
        assert(s.leases[4].queued && s.leases[4].received && s.leases[4].freed && s.leases[4].consumed);
        assert(!s.leases[4].send_inflight && !s.leases[4].pointer && !s.faults);
        assert(!s.mode1_complete && !s.mode1_cycles_completed && ack_pointer && !notice_pointer);
        assert_busy_repeat();
    } else assert(!s.full_notifications_consumed && !s.shadow_generation);
    retired_ack = ack_pointer; retired_notice = notice_pointer;
    if (notice_pointer) { check_full(400, first_generation, 0); memcpy(retired_wire, notice_pointer, sizeof retired_wire); }
    if (is("repeat-busy-ack")) {
        run_thread(receive_thread); assert_busy_repeat(); free_ack();
    } else {
        free_ack();
        if (is("repeat-busy-notice")) assert_busy_repeat();
        if (notice_pointer) run_thread(receive_thread);
    }
    native_functional_camera_control_snapshot(&s);
    assert(s.mode1_complete && s.start_complete && s.shadow_generation == first_generation);
    assert(s.mode1_cycles_completed == 1 && s.full_notifications_consumed == 1 && !s.mode1_ack_only_requests);
    assert_start_preserved(initial, &s);
    if (is("repeat-busy-ack") || is("repeat-busy-notice") || is("repeat-free-inflight") || is("repeat-send-inflight")) return;
    previous = s;
    if (is("repeat-backward-generation") || is("repeat-bridge-failure") || is("repeat-wrong-instance") ||
        is("repeat-lost-capability") || is("repeat-lost-predecessor") || is("repeat-lost-source")) {
        p = request(1); unsigned int allocated = allocations, sent = sends, released = frees;
        assert(dispatch(p, 1, &rc) == 1 && rc < 0);
        native_functional_camera_control_snapshot(&s);
        assert(bridge_calls == 3 && bridge_op[2] == FCAM_OP_STATE);
        assert(allocations == allocated && sends == sent && frees == released);
        assert(!s.faults && s.mode1_complete && s.mode1_cycle_id == previous.mode1_cycle_id);
        assert(s.mode1_requests == 1 && s.mode1_cycles_completed == 1 && s.shadow_generation == first_generation);
        assert(s.notification_ap_consumed && s.full_notifications_queued == 1 && s.full_notifications_consumed == 1);
        assert(!memcmp(s.leases + 2, previous.leases + 2, 3 * sizeof s.leases[0]));
        if (is("repeat-backward-generation") || is("repeat-wrong-instance")) assert(rc == -ESTALE);
        if (is("repeat-bridge-failure")) assert(rc == -ENODEV && s.bridge_rc == -ENODEV);
        if (is("repeat-lost-capability")) assert(rc == -ENOTSUP);
        assert_start_preserved(initial, &s); assert(reservations == unlocks); dispose(p); return;
    }
    if (is("repeat-generation") || is("repeat-address-reuse") || is("repeat-post-send-failure")) {
        write64(host_state + FCAM_S_GENERATION, 2); write32(host_state + FCAM_S_FNUMBER, 800);
        write64(host_state + FCAM_S_RENDERED, 2); write64(host_state + FCAM_S_FRAME_GENERATION, 2);
        p = request(1); ((unsigned char *)p)[4]++; assert(dispatch(p, 1, &rc) == 1 && !rc);
        native_functional_camera_control_snapshot(&s);
        assert(s.config_generation == 2 && s.mode1_cycle_generation == 2 && s.published_generation == 2 && s.shadow_generation == 1);
        assert(s.mode1_requests == 2 && s.mode1_cycle_id == 2 && !s.mode1_ack_only && !s.mode1_complete);
        if (is("repeat-post-send-failure")) {
            assert(s.faults && s.leases[2].pointer == p && s.leases[4].freed && !s.leases[4].consumed);
            assert(!s.notification_ap_consumed && s.full_notifications_queued == 1 && s.full_notifications_consumed == 1);
            assert_busy_repeat(); assert_start_preserved(initial, &s); return;
        }
        assert(!s.faults && s.full_notifications_queued == 2 && s.full_notifications_consumed == 1);
        if (is("repeat-address-reuse")) {
            assert(ack_pointer == retired_ack && notice_pointer == retired_notice);
            unsigned int released = frees;
            assert(native_functional_camera_control_observe_receive_cycle(FUNCTIONAL_CAMERA_CONTROL_AP, retired_notice,
                FUNCTIONAL_CAMERA_CONTROL_SID, CP_STATE_SNAPSHOT_BYTES, 1) == -ESTALE);
            assert(native_functional_camera_control_release_cycle(FUNCTIONAL_CAMERA_CONTROL_AP, retired_ack, release, logger, &rc, 1) == 1 && rc == -ESTALE);
            assert(native_functional_camera_control_release_cycle(FUNCTIONAL_CAMERA_CONTROL_AP, retired_notice, release, logger, &rc, 1) == 1 && rc == -ESTALE);
            assert(native_functional_camera_control_observe_receive(FUNCTIONAL_CAMERA_CONTROL_AP, notice_pointer,
                FUNCTIONAL_CAMERA_CONTROL_SID, CP_STATE_SNAPSHOT_BYTES) == -ESTALE);
            assert(native_functional_camera_control_release(FUNCTIONAL_CAMERA_CONTROL_AP, ack_pointer, release, logger, &rc) == 1 && rc == -ESTALE);
            native_functional_camera_control_snapshot(&s);
            assert(!s.faults && !s.leases[4].received && s.leases[4].pointer == retired_notice && frees == released);
        }
        check_full(800, 2, 1); free_ack(); assert_busy_repeat(); run_thread(receive_thread);
        native_functional_camera_control_snapshot(&s);
        assert(s.shadow_generation == 2 && s.mode1_complete && s.full_notifications_consumed == 2 && s.mode1_cycles_completed == 2);
        if (is("repeat-address-reuse")) {
            write64(host_state + FCAM_S_GENERATION, 3); write32(host_state + FCAM_S_FNUMBER, 1600);
            p = request(1); assert(dispatch(p, 1, &rc) == 1 && !rc);
            native_functional_camera_control_snapshot(&s);
            assert(s.faults && s.leases[4].pointer == retired_notice && !s.leases[4].received && !s.leases[4].consumed);
            unsigned int released = frees;
            assert(native_functional_camera_control_release_cycle(FUNCTIONAL_CAMERA_CONTROL_AP, retired_notice, release, logger, &rc, notice_cycle) == 1 && rc == -EPROTO);
            native_functional_camera_control_snapshot(&s);
            assert(s.leases[4].pointer == retired_notice && frees == released && s.shadow_generation == 2);
            assert(s.full_notifications_consumed == 2 && s.mode1_cycles_completed == 2); assert_start_preserved(initial, &s); return;
        }
        previous = s;
    }
    unsigned int cycles = is("repeat-unchanged") || is("repeat-events-adapter") ? 2 : 1;
    for (unsigned int i = 0; i < cycles; i++) {
        unsigned int allocated = allocations, sent = sends, calls = bridge_calls;
        p = request(1); assert(dispatch(p, 1, &rc) == 1 && !rc);
        native_functional_camera_control_snapshot(&s);
        assert(allocations == allocated + 1 && sends == sent + 1 && bridge_calls == calls + 1);
        assert(bridge_op[calls] == FCAM_OP_STATE && send_sizes[sent] == 12);
        assert(s.notification_mode == 1 && s.mode1_ack_only && !s.mode1_complete && s.mode1_cycle_generation == s.shadow_generation);
        assert(s.notification_ap_consumed && s.notification_received && s.notification_queued && !s.leases[4].pointer);
        assert(!memcmp(&s.leases[4], &previous.leases[4], sizeof s.leases[4]));
        assert(s.full_notifications_queued == previous.full_notifications_queued && s.full_notifications_consumed == previous.full_notifications_consumed);
        assert(s.mode1_ack_only_requests == previous.mode1_ack_only_requests + i + 1 && s.mode1_ack_only_completed == previous.mode1_ack_only_completed + i);
        assert(!native_functional_camera_control_observe_receive(FUNCTIONAL_CAMERA_CONTROL_AP, retired_notice, FUNCTIONAL_CAMERA_CONTROL_SID, CP_STATE_SNAPSHOT_BYTES));
        rc = 123; assert(!native_functional_camera_control_release(FUNCTIONAL_CAMERA_CONTROL_AP, retired_notice, release, logger, &rc) && rc == 123);
        if (is("repeat-foreign-ack")) {
            run_thread(bad_ack_thread); native_functional_camera_control_snapshot(&s);
            assert(s.faults && !s.mode1_complete && s.leases[3].pointer == ack_pointer && !s.mode1_ack_only_completed);
            assert(s.notification_ap_consumed && s.full_notifications_consumed == 1); assert_start_preserved(initial, &s); return;
        }
        assert_busy_repeat(); free_ack(); native_functional_camera_control_snapshot(&s);
        assert(!s.faults && s.mode1_complete && s.mode1_cycles_completed == previous.mode1_cycles_completed + i + 1);
        assert(s.mode1_ack_only_completed == previous.mode1_ack_only_completed + i + 1);
        assert(s.phase == FUNCTIONAL_CAMERA_CONTROL_MODE_ACK_CONSUMED && s.shadow_generation == previous.shadow_generation);
        assert_start_preserved(initial, &s);
    }
    assert(reservations == unlocks && !s.busy && !s.guard_held);
}
/* Model the original imaging receiver's pointer-to-promise handoff. The queue
 * receiver is persistent; only the requesting thread copies and frees ACKs. */
static struct {
    pthread_mutex_t mutex;
    pthread_cond_t condition;
    void *pointer, *reply;
    unsigned int index, posted, observed, defer, stop;
    uint64_t cycle;
    long receiver_tid;
    int result;
} native_queue = {.mutex = PTHREAD_MUTEX_INITIALIZER, .condition = PTHREAD_COND_INITIALIZER};
static void *native_receiver(void *unused) {
    (void)unused;
    assert(!pthread_mutex_lock(&native_queue.mutex));
    native_queue.receiver_tid = syscall(SYS_gettid);
    for (;;) {
        while ((!native_queue.pointer || native_queue.defer) && !native_queue.stop)
            assert(!pthread_cond_wait(&native_queue.condition, &native_queue.mutex));
        if (native_queue.stop) break;
        void *p = native_queue.pointer;
        const unsigned int index = native_queue.index;
        const uint64_t cycle = native_queue.cycle;
        assert(!pthread_mutex_unlock(&native_queue.mutex));
        struct native_functional_camera_control_snapshot s;
        native_functional_camera_control_snapshot(&s);
        const struct native_cp_state_publication_lease before = s.leases[index];
        assert(before.pointer == p && before.sender_tid != syscall(SYS_gettid));
        assert(s.lease_cycle_id[index] == cycle && !before.received && !before.freed && !before.consumed);
        assert(before.send_inflight == !(is("native-ack-after-send") && index == 1));
        unsigned int actual_bytes, actual_source;
        memcpy(&actual_bytes, (unsigned char *)p - 8, sizeof actual_bytes);
        memcpy(&actual_source, (unsigned char *)p - 12, sizeof actual_source);
        assert(actual_bytes == before.bytes && actual_source == before.source);
        if (index == 1) {
            static const unsigned char wire[16] = {1, 0, 3, 0x30, 0x27, 0, 0, 0x80, 0, 0xf0};
            assert(!memcmp(p, wire, sizeof wire) && fnv(p, 16) == UINT64_C(0x7ef188e66a84bb78));
            if (is("native-ack-corrupt")) ((unsigned char *)p)[15] ^= 1;
            if (is("native-ack-wrong-source")) envelope(p)->source ^= 1;
            if (is("native-ack-wrong-size")) envelope(p)->size--;
        }
        int observed = functional_camera_events_observe_receive(FUNCTIONAL_CAMERA_CONTROL_AP, p, source(p), size(p));
        const int rejected = index == 1 && (is("native-ack-corrupt") || is("native-ack-wrong-source") || is("native-ack-wrong-size"));
        if (observed != (rejected ? -EPROTO : 1))
            fprintf(stderr, "native ACK receive: result=%d destination=%#x source=%#x bytes=%u tid=%ld sender_tid=%ld cycle=%llu send_inflight=%u wire_fnv1a=%016llx\n",
                observed, FUNCTIONAL_CAMERA_CONTROL_AP, source(p), size(p), syscall(SYS_gettid), before.sender_tid,
                (unsigned long long)cycle, before.send_inflight, (unsigned long long)fnv(p, before.bytes));
        assert(observed == (rejected ? -EPROTO : 1));
        native_functional_camera_control_snapshot(&s);
        assert(!s.leases[index].consumed && !s.leases[index].freed && s.leases[index].pointer == p);
        if (!rejected) {
            assert(!s.faults && s.leases[index].received && s.leases[index].receiver_tid == syscall(SYS_gettid));
            if (is("native-ack-duplicate"))
                assert(functional_camera_events_observe_receive(FUNCTIONAL_CAMERA_CONTROL_AP, p, source(p), size(p)) == -EALREADY);
        }
        if (index == 4 || (index == 1 && is("native-ack-receiver-free"))) {
            int rc = 123; const unsigned int released = frees;
            assert(functional_camera_events_release(FUNCTIONAL_CAMERA_CONTROL_AP, p, release, logger, &rc) == 1);
            if (index == 1) assert(rc == -EPROTO && frees == released);
            else {
                assert(!rc && frees == released + 1);
                native_functional_camera_control_snapshot(&s);
                assert(s.leases[4].received && s.leases[4].freed && !s.leases[4].pointer);
                assert(!s.leases[4].consumed && !s.notification_ap_consumed && !s.faults);
                assert(s.leases[4].send_inflight && !s.leases[4].queued);
                notice_pointer = NULL;
            }
        }
        assert(!pthread_mutex_lock(&native_queue.mutex));
        if (index != 4) { assert(!native_queue.reply); native_queue.reply = p; }
        native_queue.result = observed; native_queue.pointer = NULL; native_queue.observed++;
        assert(!pthread_cond_broadcast(&native_queue.condition));
    }
    assert(!pthread_mutex_unlock(&native_queue.mutex)); return NULL;
}
static int native_send(unsigned int destination, void *p, unsigned int index, uint64_t cycle) {
    assert(destination == FUNCTIONAL_CAMERA_CONTROL_AP);
    assert(!pthread_mutex_lock(&native_queue.mutex)); assert(!native_queue.pointer);
    native_queue.pointer = p; native_queue.index = index; native_queue.cycle = cycle; native_queue.posted++;
    native_queue.defer = is("native-ack-after-send") && index == 1;
    assert(!pthread_cond_broadcast(&native_queue.condition));
    while (native_queue.observed != native_queue.posted && !native_queue.defer)
        assert(!pthread_cond_wait(&native_queue.condition, &native_queue.mutex));
    assert(!pthread_mutex_unlock(&native_queue.mutex));
    return is("native-ack-send-fail") ? -EPIPE : 0;
}
static void *native_reply(void) {
    assert(!pthread_mutex_lock(&native_queue.mutex));
    while (!native_queue.reply) assert(!pthread_cond_wait(&native_queue.condition, &native_queue.mutex));
    void *p = native_queue.reply; native_queue.reply = NULL;
    assert(!pthread_mutex_unlock(&native_queue.mutex)); return p;
}
static void native_scenarios(void) {
    write64(host_state + FCAM_S_INSTANCE, UINT64_C(0x11de333f5bfdd824));
    write64(host_state + FCAM_S_GENERATION, 1);
    pthread_t receiver; assert(!pthread_create(&receiver, NULL, native_receiver, NULL));
    void *p = request(0); int rc = 123;
    assert(fnv(p, 24) == UINT64_C(0x855a2708cad3e099));
    assert(dispatch(p, 1, &rc) == 1 && !rc);
    if (is("native-ack-after-send")) {
        assert(!pthread_mutex_lock(&native_queue.mutex)); native_queue.defer = 0;
        assert(!pthread_cond_broadcast(&native_queue.condition));
        while (native_queue.observed != native_queue.posted)
            assert(!pthread_cond_wait(&native_queue.condition, &native_queue.mutex));
        assert(!pthread_mutex_unlock(&native_queue.mutex));
    }
    struct native_functional_camera_control_snapshot s;
    native_functional_camera_control_snapshot(&s);
    if (is("native-ack-send-fail")) {
        assert(s.faults && !s.start_complete && s.leases[0].pointer == p);
        assert(s.leases[1].received && s.leases[1].freed && !s.leases[1].queued && !s.leases[1].consumed);
    } else {
        assert(s.leases[0].freed && !s.leases[0].pointer && s.leases[1].queued && !s.leases[1].send_inflight);
        assert(!s.start_complete && !s.leases[1].freed && !s.leases[1].consumed);
        void *reply = native_reply(); unsigned char copied[16];
        assert(reply == ack_pointer); memcpy(copied, reply, sizeof copied);
        assert(read32(copied + 4) == 0x80000027 && read32(copied + 8) == 0xf000);
        assert((fnv(copied, sizeof copied) == UINT64_C(0x7ef188e66a84bb78)) == !is("native-ack-corrupt"));
        const unsigned int released = frees;
        assert(functional_camera_events_release(FUNCTIONAL_CAMERA_CONTROL_AP, reply, release, logger, &rc) == 1);
        const int refused = is("native-ack-corrupt") || is("native-ack-wrong-source") || is("native-ack-wrong-size") || is("native-ack-free-fail");
        assert(refused ? rc < 0 : rc == 0);
        assert(frees == released + (refused && !is("native-ack-free-fail") ? 0u : 1u));
        native_functional_camera_control_snapshot(&s);
        if (refused || is("native-ack-receiver-free")) {
            assert(s.faults && !s.start_complete && !s.leases[1].consumed && !s.business_ready);
        } else {
            assert(!s.faults && s.start_complete && s.leases[1].consumed);
            assert(s.leases[1].receiver_tid == native_queue.receiver_tid);
            assert(s.leases[1].free_tid == s.leases[1].sender_tid && s.leases[1].free_tid != s.leases[1].receiver_tid);
            ack_pointer = NULL;
            for (unsigned int cycle = 1; cycle <= 3; cycle++) {
                void *retired = retired_ack; const uint64_t old_cycle = ack_cycle;
                p = request(1); assert(dispatch(p, 1, &rc) == 1 && !rc);
                native_functional_camera_control_snapshot(&s);
                assert(!s.faults && s.mode1_cycle_id == cycle && !s.mode1_complete);
                assert(s.leases[3].received && !s.leases[3].freed && !s.leases[3].consumed);
                assert(s.leases[3].receiver_tid == native_queue.receiver_tid && s.leases[3].sender_tid == syscall(SYS_gettid));
                assert(s.shadow_generation == 1 && s.notification_ap_consumed && s.full_notifications_consumed == 1);
                if (cycle > 1 && is("native-ack-address-reuse")) {
                    assert(ack_pointer == retired);
                    const unsigned int attempts = frees;
                    assert(native_functional_camera_control_observe_receive_cycle(FUNCTIONAL_CAMERA_CONTROL_AP,
                        retired, FUNCTIONAL_CAMERA_CONTROL_SID, 12, old_cycle) == -ESTALE);
                    assert(native_functional_camera_control_release_cycle(FUNCTIONAL_CAMERA_CONTROL_AP,
                        retired, release, logger, &rc, old_cycle) == 1 && rc == -ESTALE && frees == attempts);
                }
                retired_ack = ack_pointer;
                reply = native_reply(); assert(reply == ack_pointer); memcpy(copied, reply, 12);
                assert(read32(copied) == 0x40730001 && read32(copied + 4) == 0x80000027 && read32(copied + 8) == 0xf000);
                assert(functional_camera_events_release(FUNCTIONAL_CAMERA_CONTROL_AP, reply, release, logger, &rc) == 1 && !rc);
                ack_pointer = NULL; native_functional_camera_control_snapshot(&s);
                assert(!s.faults && s.mode1_complete && s.mode1_cycles_completed == cycle);
                assert(s.full_notifications_queued == 1 && s.full_notifications_consumed == 1 && s.shadow_generation == 1);
                assert(s.mode1_ack_only_completed == cycle - 1);
            }
        }
    }
    native_functional_camera_control_snapshot(&s);
    assert(!s.original_cp && !s.physical_asic_verified && !s.ee && !s.frame && !s.capture);
    assert(!pthread_mutex_lock(&native_queue.mutex)); native_queue.stop = 1;
    assert(!pthread_cond_broadcast(&native_queue.condition)); assert(!pthread_mutex_unlock(&native_queue.mutex));
    assert(!pthread_join(receiver, NULL));
}
static void same_xsync(const struct native_functional_camera_control_snapshot *a,
                       const struct native_functional_camera_control_snapshot *b) {
    assert(a->xsync_defined == b->xsync_defined && a->xsync_source_fps == b->xsync_source_fps &&
        a->xsync_word == b->xsync_word && a->xsync_half == b->xsync_half &&
        a->xsync_source_generation == b->xsync_source_generation);
}
static void hex_output(const unsigned char *p, size_t bytes) {
    for (size_t i = 0; i < bytes; i++) printf("%02x", p[i]);
}
static void xsync_output(int result) {
    struct native_functional_camera_control_snapshot s; native_functional_camera_control_snapshot(&s);
    printf("{\"result\":%d,\"probe_rc\":%d,\"bridge_rc\":%d,\"xsync_defined\":%u,\"xsync_source_fps\":%u,"
        "\"xsync_word\":%u,\"xsync_half\":%u,\"xsync_source_generation\":%llu,\"config_generation\":%llu,"
        "\"published_generation\":%u,\"shadow_generation\":%u,\"projected_blocks\":%u,\"zero_policy_blocks\":%u,"
        "\"mode1_requests\":%u,\"mode1_cycle_id\":%llu,\"model_state\":\"",
        result, s.probe_rc, s.bridge_rc, s.xsync_defined, s.xsync_source_fps, s.xsync_word, s.xsync_half,
        (unsigned long long)s.xsync_source_generation, (unsigned long long)s.config_generation,
        s.published_generation, s.shadow_generation, s.projected_blocks, s.zero_policy_blocks,
        s.mode1_requests, (unsigned long long)s.mode1_cycle_id);
    hex_output(s.model_state, sizeof s.model_state); printf("\",\"probe_state\":\"");
    hex_output(last_probe_state, sizeof last_probe_state); printf("\",\"wire\":\"");
    if (notice_pointer) hex_output(notice_pointer, CP_STATE_SNAPSHOT_BYTES);
    printf("\",\"record\":\"%s\"}\n", latest_record);
}
static void xsync_scenarios(void) {
    struct native_functional_camera_control_snapshot before, s;
    native_functional_camera_control_snapshot(&before);
    unsigned int fps = 30; char trailing;
    const int domain_case = !strncmp(scenario, "xsync-fps-", 10);
    if (domain_case) {
        assert(sscanf(scenario, "xsync-fps-%u%c", &fps, &trailing) == 1);
        write32(host_state + FCAM_S_FPS, fps); write64(host_state + FCAM_S_GENERATION, 8);
    }
    if (is("xsync-zero-shutter-state")) write64(host_state + FCAM_S_SHUTTER, 0);
    if (is("xsync-same-generation-fps")) write32(host_state + FCAM_S_FPS, 25);
    int rc = 123; void *p = request(1);
    const unsigned int allocated = allocations, sent = sends, released = frees;
    assert(dispatch(p, 1, &rc) == 1); native_functional_camera_control_snapshot(&s);
    if (rc) {
        assert(domain_case || is("xsync-zero-shutter-state") || is("xsync-same-generation-fps"));
        assert(!s.publication_copied && !s.published_generation && !s.shadow_generation && !s.mode1_requests);
        assert(!s.leases[2].pointer && !s.leases[3].pointer && !s.leases[4].pointer && !s.faults);
        assert(allocations == allocated && sends == sent && frees == released && !ack_pointer && !notice_pointer);
        same_xsync(&before, &s);
        if (domain_case) assert(rc == (fps && fps <= 120 ? -ENOTSUP : -ERANGE));
        else assert(rc == (is("xsync-zero-shutter-state") ? -ERANGE : -ESTALE));
        assert(s.probe_rc == rc && reservations == unlocks); xsync_output(rc); dispose(p); return;
    }
    assert(!is("xsync-zero-shutter-state") && !is("xsync-same-generation-fps"));
    check_full(400, domain_case ? 8 : 7, 0); xsync_output(0);
    free_ack(); run_thread(receive_thread); native_functional_camera_control_snapshot(&s);
    assert(s.mode1_complete && s.notification_ap_consumed && s.shadow_generation == s.xsync_source_generation);
    if (domain_case) return;
    before = s;
    if (!strncmp(scenario, "xsync-refuse-after-full-", 24)) {
        assert(sscanf(scenario, "xsync-refuse-after-full-%u%c", &fps, &trailing) == 1);
        write32(host_state + FCAM_S_FPS, fps); write64(host_state + FCAM_S_GENERATION, 8);
        unsigned int previous_allocations = allocations, previous_sends = sends, previous_frees = frees;
        p = request(1); assert(dispatch(p, 1, &rc) == 1 && rc == -ENOTSUP);
        native_functional_camera_control_snapshot(&s); same_xsync(&before, &s);
        assert(!s.faults && !s.busy && !s.guard_held && s.mode1_complete && s.mode1_cycle_id == before.mode1_cycle_id);
        assert(s.config_generation == 8 && s.shadow_generation == 7 && s.published_generation == 7);
        assert(s.mode1_requests == before.mode1_requests && s.full_notifications_queued == before.full_notifications_queued &&
            s.full_notifications_consumed == before.full_notifications_consumed && s.notification_ap_consumed);
        assert(allocations == previous_allocations && sends == previous_sends && frees == previous_frees);
        assert(!memcmp(s.leases, before.leases, sizeof s.leases));
        assert(s.publication_copied == before.publication_copied && !memcmp(s.block_defined, before.block_defined, sizeof s.block_defined) &&
            !memcmp(s.block_projected, before.block_projected, sizeof s.block_projected));
        xsync_output(rc); assert(reservations == unlocks); dispose(p); return;
    }
    assert(is("xsync-generation") || is("xsync-exposure"));
    for (unsigned int step = 0; step < 2; step++) {
        fps = is("xsync-generation") ? (step ? 60 : 25) : 30;
        const unsigned int generation = 8 + step;
        write32(host_state + FCAM_S_FPS, fps); write64(host_state + FCAM_S_GENERATION, generation);
        write64(host_state + FCAM_S_SHUTTER, step ? 500000 : 1); write32(host_state + FCAM_S_ISO, step ? 3200 : 50);
        p = request(1); assert(dispatch(p, 1, &rc) == 1 && !rc);
        native_functional_camera_control_snapshot(&s); check_full(400, generation, generation - 1); xsync_output(0);
        assert(s.xsync_source_generation == generation && s.xsync_source_fps == fps && s.xsync_word == fps && s.xsync_half == 1);
        assert(!s.ee && !s.frame && !s.capture && !s.physical_asic_verified);
        free_ack(); run_thread(receive_thread); native_functional_camera_control_snapshot(&before);
        assert(before.mode1_complete && before.shadow_generation == generation);
        const unsigned int previous_allocations = allocations, previous_sends = sends;
        p = request(1); assert(dispatch(p, 1, &rc) == 1 && !rc);
        native_functional_camera_control_snapshot(&s); same_xsync(&before, &s);
        assert(s.mode1_ack_only && allocations == previous_allocations + 1 && sends == previous_sends + 1 && !notice_pointer);
        assert(!memcmp(&s.leases[4], &before.leases[4], sizeof s.leases[4]));
        assert(s.full_notifications_queued == before.full_notifications_queued && s.full_notifications_consumed == before.full_notifications_consumed);
        free_ack(); native_functional_camera_control_snapshot(&s); same_xsync(&before, &s);
        assert(s.mode1_complete && s.shadow_generation == generation && s.mode1_ack_only_completed == step + 1);
    }
    assert(reservations == unlocks);
}
int main(int argc, char **argv) {
    assert(argc == 2); scenario = argv[1]; seed();
    assert(!native_functional_camera_control_owner_init() && native_functional_camera_control_owner_init() == -EALREADY);
    struct native_functional_camera_control_snapshot s; native_functional_camera_control_snapshot(&s);
    assert(s.initialized && !s.model_initialized && !s.business_ready && s.phase == FUNCTIONAL_CAMERA_CONTROL_UNKNOWN && !bridge_calls);
    assert(!s.xsync_defined && !s.xsync_source_fps && !s.xsync_word && !s.xsync_half && !s.xsync_source_generation);
    if (native_case()) { native_scenarios(); cleanup(); return 0; }
    void *p = request(0); int result = 123;
    if (is("reentrant-dispatch")) reentrant_request = request(0);
    if (early_case(p)) { assert(!bridge_calls && !allocations && !sends); cleanup(); return 0; }
    assert(dispatch(p, 1, &result) == 1); native_functional_camera_control_snapshot(&s);
    if (init_refusal()) {
        assert(result < 0 && !allocations && !sends && !s.leases[0].pointer && !s.start_requests && !s.start_complete);
        assert(!s.notification_queued && !s.shadow_generation && !s.capture);
        assert(reservations == 1 && unlocks == (is("guard-fail") ? 0u : 1u));
        if (is("missing-broker")) assert(result == -ENODEV && s.bridge_rc == -ENODEV);
        if (is("checksum-error")) assert(result == -EBADMSG && s.bridge_rc == -EBADMSG);
        if (is("output-guard")) assert(result == -EOVERFLOW && s.faults && !s.business_ready);
        cleanup(); return 0;
    }
    if (is("alloc-start-fail") || is("alloc-dirty-failure") || is("alloc-short") || is("alloc-long") || is("alloc-alias-request")) {
        assert(result < 0 && !sends && s.faults && !s.leases[0].pointer && !s.start_requests);
        if (is("alloc-short")) assert(((unsigned char *)p)[0] == 0);
        cleanup(); return 0;
    }
    assert(!result && s.model_initialized && s.init_run_id == 1 && s.model_instance == UINT64_C(0x123456789abcdef));
    assert(s.probe_attempts == 1 && s.probe_successes == 1 && bridge_calls == 1 && bridge_op[0] == FCAM_OP_INIT);
    if (is("send-start-fail") || is("request-free-fail") || is("inline-send-fail")) {
        assert(s.faults && s.leases[0].pointer == p && !s.start_complete && !s.business_ready);
        assert(!s.leases[1].consumed && !s.shadow_generation);
        if (is("inline-send-fail")) assert(s.leases[1].freed && !s.leases[1].queued);
        cleanup(); return 0;
    }
    assert(s.start_defined_mask == 15 && s.business_ready);
    if (ack_pointer) {
        unsigned char expected[16] = {1, 0, 3, 0x30, 0x78, 0x56, 0x34, 0x12, 0, 0xf0};
        if (is("start-3000")) expected[2] = 0;
        assert(envelope(ack_pointer)->size == 16 && !memcmp(ack_pointer, expected, sizeof expected));
        assert(s.leases[1].queued && !s.leases[1].consumed && !s.start_complete && !s.leases[0].pointer);
    }
    if (is("pending-start-ack")) {
        void *mode = request(1); int rc = 987; assert(dispatch(mode, 1, &rc) == 1 && rc < 0);
        assert(bridge_calls == 1 && allocations == 1 && sends == 1); free_ack(); cleanup(); return 0;
    }
    if (is("bad-ack-tid")) {
        run_thread(bad_ack_thread); native_functional_camera_control_snapshot(&s);
        assert(s.faults && s.leases[1].pointer == ack_pointer && !s.start_complete); free_ack(); cleanup(); return 0;
    }
    if (is("ack-free-fail") || is("corrupt-ack")) {
        if (is("corrupt-ack")) ((unsigned char *)ack_pointer)[15] ^= 1;
        unsigned int before = frees; int rc = 987;
        assert(native_functional_camera_control_release(FUNCTIONAL_CAMERA_CONTROL_AP, ack_pointer, release, logger, &rc) == 1 && rc < 0);
        native_functional_camera_control_snapshot(&s); assert(s.faults && !s.start_complete && s.leases[1].pointer == ack_pointer);
        assert(frees == before + (is("ack-free-fail") ? 1u : 0u)); cleanup(); return 0;
    }
    free_ack(); native_functional_camera_control_snapshot(&s);
    if (is("reentrant-free")) { assert(nested_frees == 1 && s.faults && !s.start_complete && !s.business_ready); cleanup(); return 0; }
    assert(s.start_complete && !s.shadow_generation && s.leases[1].free_tid == s.leases[1].sender_tid);
    assert(!s.xsync_defined && !s.xsync_source_fps && !s.xsync_word && !s.xsync_half && !s.xsync_source_generation);
    if (!strncmp(scenario, "xsync-", 6)) { xsync_scenarios(); cleanup(); return 0; }
    if (is("strict-owner-unchanged")) {
        assert(!native_cp_state_publication_owner_init());
        const struct native_cp_state_publication_providers providers = {NULL, strict_refusal, NULL};
        void *strict_request = request(0); result = 987;
        assert(native_cp_state_publication_dispatch(FUNCTIONAL_CAMERA_CONTROL_SID, strict_request, &io, &guard, &providers, 1, &result) == 1 && result == -ENODATA);
        struct native_cp_state_publication_snapshot strict; native_cp_state_publication_snapshot(&strict);
        assert(!strict.start_requests && !strict.start_complete && !strict.start_data_known_mask && !strict.leases[0].pointer);
        assert(!strict.original_cp && !strict.capture && !strict.faults && bridge_calls == 1 && allocations == 1 && sends == 1);
        cleanup(); return 0;
    }
    if (repeat_case()) { repeat_scenarios(&s); cleanup(); return 0; }
    p = request(1); result = 987; assert(dispatch(p, 1, &result) == 1);
    native_functional_camera_control_snapshot(&s);
    if ((!strncmp(scenario, "state-", 6) && !is("state-advanced")) || is("alloc-mode-fail") || is("alloc-notice-fail") || is("alloc-alias-ack")) {
        assert(result < 0 && !s.mode1_requests && !s.leases[2].pointer && !s.shadow_generation && !s.notification_queued);
        assert(bridge_calls == 2 && bridge_op[1] == FCAM_OP_STATE);
        if (!strncmp(scenario, "state-", 6)) assert(allocations == 1 && sends == 1 && !s.business_ready);
        cleanup(); return 0;
    }
    assert(!result && bridge_calls == 2 && bridge_op[1] == FCAM_OP_STATE && s.state_run_id == 2);
    if (is("send-mode-fail") || is("send-notice-fail")) {
        assert(s.faults && !s.mode1_complete && !s.shadow_generation && s.leases[2].pointer == p);
        assert(!s.notification_ap_consumed); cleanup(); return 0;
    }
    if (ack_pointer) {
        static const unsigned char expected[12] = {1, 0, 0x73, 0x40, 0x78, 0x56, 0x34, 0x12, 0, 0xf0, 0, 0};
        assert(envelope(ack_pointer)->size == 12 && !memcmp(ack_pointer, expected, sizeof expected));
    }
    free_ack(); native_functional_camera_control_snapshot(&s);
    assert(s.full_layout_copied && s.full_model_defined && s.publication_copied && s.defined_blocks == 76);
    assert(s.projected_blocks == 3 && s.zero_policy_blocks == 72 && !s.full_original_source_known);
    for (size_t i = 0; i < CP_FULL_STATE_SNAPSHOT_BLOCKS; i++) {
        unsigned int command = cp_full_state_snapshot_blocks[i].command;
        assert(s.block_defined[i] == 1 && s.block_projected[i] == (command == 0x201b || command == 0x2044 || command == 0x20a6));
    }
    assert(send_sizes[0] == 16 && send_sizes[1] == 12 && send_sizes[2] == CP_STATE_SNAPSHOT_BYTES);
    if (!is("inline-free")) {
        assert(s.notification_queued && !s.notification_received && !s.notification_ap_consumed && !s.shadow_generation && !s.mode1_complete);
        check_full(is("state-advanced") ? 800 : 400, is("state-advanced") ? 9 : 7, 0);
        if (is("free-before-receive")) {
            int rc = 987; assert(native_functional_camera_control_release(FUNCTIONAL_CAMERA_CONTROL_AP, notice_pointer, release, logger, &rc) == 1 && rc == -EPROTO);
        } else if (is("receive-wrong-source") || is("receive-wrong-destination") || is("receive-wrong-length") ||
                   is("receive-metadata-source") || is("receive-metadata-size") || is("corrupt-before-receive")) {
            if (is("corrupt-before-receive")) ((unsigned char *)notice_pointer)[CP_STATE_SNAPSHOT_BYTES - 1] ^= 1;
            if (is("receive-metadata-source")) envelope(notice_pointer)->source = FUNCTIONAL_CAMERA_CONTROL_AP;
            if (is("receive-metadata-size")) envelope(notice_pointer)->size--;
            assert(native_functional_camera_control_observe_receive(is("receive-wrong-destination") ? FUNCTIONAL_CAMERA_CONTROL_SID : FUNCTIONAL_CAMERA_CONTROL_AP,
                notice_pointer, is("receive-wrong-source") ? FUNCTIONAL_CAMERA_CONTROL_AP : FUNCTIONAL_CAMERA_CONTROL_SID,
                is("receive-wrong-length") ? CP_STATE_SNAPSHOT_BYTES - 1 : CP_STATE_SNAPSHOT_BYTES) == -EPROTO);
        } else if (is("corrupt-before-free") || is("notice-free-fail") || is("bad-notice-tid") ||
                   is("free-metadata-source") || is("free-metadata-size") || is("duplicate-receive")) {
            assert(native_functional_camera_control_observe_receive(FUNCTIONAL_CAMERA_CONTROL_AP, notice_pointer, FUNCTIONAL_CAMERA_CONTROL_SID, CP_STATE_SNAPSHOT_BYTES) == 1);
            native_functional_camera_control_snapshot(&s); assert(s.notification_received && !s.shadow_generation && !s.notification_ap_consumed);
            if (is("bad-notice-tid")) run_thread(bad_notice_thread);
            else if (is("duplicate-receive")) assert(native_functional_camera_control_observe_receive(FUNCTIONAL_CAMERA_CONTROL_AP, notice_pointer, FUNCTIONAL_CAMERA_CONTROL_SID, CP_STATE_SNAPSHOT_BYTES) == -EPROTO);
            else {
                unsigned int before = frees; int rc = 987;
                if (is("corrupt-before-free")) ((unsigned char *)notice_pointer)[CP_STATE_SNAPSHOT_BYTES - 1] ^= 1;
                if (is("free-metadata-source")) envelope(notice_pointer)->source = FUNCTIONAL_CAMERA_CONTROL_AP;
                if (is("free-metadata-size")) envelope(notice_pointer)->size--;
                assert(native_functional_camera_control_release(FUNCTIONAL_CAMERA_CONTROL_AP, notice_pointer, release, logger, &rc) == 1 && rc < 0);
                assert(frees == before + (is("notice-free-fail") ? 1u : 0u));
            }
        } else {
            if (is("receive-wrong-pointer")) {
                void *wrong = message(CP_STATE_SNAPSHOT_BYTES, FUNCTIONAL_CAMERA_CONTROL_SID); memcpy(wrong, notice_pointer, CP_STATE_SNAPSHOT_BYTES);
                assert(!native_functional_camera_control_observe_receive(FUNCTIONAL_CAMERA_CONTROL_AP, wrong, FUNCTIONAL_CAMERA_CONTROL_SID, CP_STATE_SNAPSHOT_BYTES));
                native_functional_camera_control_snapshot(&s); assert(!s.faults && !s.notification_received);
            }
            run_thread(receive_thread);
        }
    }
    native_functional_camera_control_snapshot(&s);
    if (s.faults) {
        assert(!s.mode1_complete && !s.shadow_generation && !s.notification_ap_consumed && !s.business_ready);
        assert(s.leases[4].pointer == notice_pointer); cleanup(); return 0;
    }
    assert(s.mode1_complete && s.notification_ap_consumed && s.notification_received && s.leases[4].consumed);
    assert(s.shadow_generation == (is("state-advanced") ? 9u : 7u) && s.published_generation == s.config_generation);
    assert(s.phase == FUNCTIONAL_CAMERA_CONTROL_NOTICE_CONSUMED && !s.leases[4].pointer && s.business_ready);
    assert(s.leases[4].receiver_tid == s.leases[4].free_tid);
    if (!is("inline-free")) assert(s.leases[4].receiver_tid != s.leases[4].sender_tid);
    assert(reservations == unlocks && !s.guard_held && !s.busy && records);
    void *again = request(1); result = 123;
    assert(dispatch(again, 1, &result) == 1 && !result && bridge_calls == 3 && sends == 4);
    native_functional_camera_control_snapshot(&s);
    assert(s.mode1_ack_only && s.mode1_requests == 2 && s.full_notifications_queued == 1 && s.full_notifications_consumed == 1);
    free_ack(); native_functional_camera_control_snapshot(&s);
    assert(s.mode1_complete && s.mode1_cycles_completed == 2 && s.mode1_ack_only_completed == 1 && s.notification_ap_consumed);
    assert(!s.original_cp && !s.physical_asic_verified && !s.frame && !s.capture);
    cleanup(); puts("PASS functional model control mock; original CP/ASIC/AP capture remain unverified"); return 0;
}
