/* SPDX-License-Identifier: MIT */
#define _GNU_SOURCE
#ifndef HOST_TEST
#error HOST_TEST transport fixtures provide no native AP or frame evidence.
#endif
#include "functional-vdf-layout-stage.h"
#include <assert.h>
#include <pthread.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/wait.h>
#include <unistd.h>

struct message { unsigned int source, bytes; unsigned char data[40]; };
static const unsigned char wire[40] = {
    0x0d, 0x20, 0x4c, 1, 40, 0, 1, 0x80, 7, 1, 1, 0, 0, 0, 0, 0, 0x80, 2, 0xe0, 1,
    0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 3, 0, 0, 0, 0, 0, 0, 0
};
static const unsigned char ack_wire[12] = {0x0d, 0x20, 0x4c, 0x11, 12, 0, 1, 0x80, 0, 0, 0x59, 0};
static const struct full_imaging_io io;
static const char *scenario;
static struct message original, recycled;
static struct message *heap_ack;
static void *ack_pointer;
static unsigned int source_id = UINT32_C(0x81cf61c6), allocations, sends, request_frees, ack_frees, logs;
static uint64_t ticket;
static int request_live, ack_live, reenter;
static int is(const char *s) { return !strcmp(scenario, s); }
static uint64_t fnv(const void *pointer, size_t bytes) {
    const unsigned char *p = pointer; uint64_t h = UINT64_C(14695981039346656037);
    for (size_t i = 0; i < bytes; i++) h = (h ^ p[i]) * UINT64_C(1099511628211);
    return h;
}
static struct message *message(void *p) { return (struct message *)((unsigned char *)p - offsetof(struct message, data)); }
static struct functional_vdf_layout_stage_snapshot snapshot(void) {
    struct functional_vdf_layout_stage_snapshot s; functional_vdf_layout_stage_snapshot(&s);
    assert(s.owner_pid == getpid() && s.initialized && s.stage_only == 1);
    assert(!s.semantic_applied && !s.frame_consumed && !s.hardware_ready && !s.capture_verified &&
        !s.physical_asic_verified && !s.original_cp_fifo_verified && !s.physical_cp_rtos_verified);
    return s;
}
static void inspect(void) {
    const struct functional_vdf_layout_stage_snapshot s = snapshot();
    if (is("reentry") && s.busy && !reenter) {
        reenter = 1; int rc = 123;
        assert(functional_vdf_layout_stage_dispatch(FUNCTIONAL_LAYOUT_STAGE_SID, original.data, &io, 1, 0, &rc) == 1);
        assert(rc == -EBUSY); reenter = 0;
    }
}
static unsigned int size_of(void *p) { inspect(); return message(p)->bytes; }
static unsigned int source_of(void *p) {
    inspect();
    if (is("source-mutation") && p == original.data) original.data[39] = 1;
    return message(p)->source;
}
static void set_source(void *p, unsigned int source) {
    inspect(); message(p)->source = source;
    if (is("ack-mutation")) ((unsigned char *)p)[11] ^= 1;
}
static int allocate(unsigned int destination, void **p, unsigned int bytes, unsigned int option) {
    inspect(); allocations++;
    assert(destination == source_id && bytes == 12 && option == 1 && request_live);
    const struct functional_vdf_layout_stage_snapshot s = snapshot();
    assert(s.readback_verified && !memcmp(s.bank32, wire + 8, 32) &&
        !memcmp(s.copied_readback32, wire + 8, 32) && s.bank_fnv1a64 == fnv(wire + 8, 32));
    if (is("alloc-fail")) { *p = NULL; return -ENOMEM; }
    if (is("live-alias")) { *p = original.data + 1; return 0; }
    if (!strncmp(scenario, "private-alias-", 14)) {
        unsigned int index = 99; assert(sscanf(scenario, "private-alias-%u", &index) == 1 && index < 5);
        *p = functional_vdf_layout_stage_test_private_address(index);
        if (!index) *p = (unsigned char *)*p + sizeof s - 1;
        return 0;
    }
    if (is("span")) { *p = (void *)(UINTPTR_MAX - 5); return 0; }
    if (is("inline-free") || is("inline-send-fail")) {
        assert(!heap_ack); heap_ack = malloc(sizeof *heap_ack); assert(heap_ack);
        memset(heap_ack, 0, sizeof *heap_ack); *p = heap_ack->data;
    } else { memset(&recycled, 0, sizeof recycled); *p = recycled.data; }
    message(*p)->bytes = 12; ack_live = 1;
    if (is("request-mutation")) original.data[39] ^= 1;
    return 0;
}
static int real_free(unsigned int destination, void *p) {
    inspect();
    if (destination == FUNCTIONAL_LAYOUT_STAGE_SID) {
        assert(request_live && p == original.data && !memcmp(p, wire, 40)); request_frees++;
        if (is("request-free-fail")) return -EIO;
        request_live = 0;
    } else {
        assert(ack_live && destination == source_id && !memcmp(p, ack_wire, 12)); ack_frees++;
        if (is("ack-free-fail") && ack_frees == 1) return -EIO;
        if (is("reentrant-free") && !reenter) {
            reenter = 1; int rc = 123;
            assert(functional_vdf_layout_stage_release_cycle(destination, p, ticket, real_free, NULL, &rc) == 1);
            assert(rc == -EPROTO); reenter = 0;
        }
        ack_live = 0; if (heap_ack) { free(heap_ack); heap_ack = NULL; }
    }
    return 0;
}
static void logger(const char *tag, const char *text) {
    inspect(); logs++;
    assert(!strncmp(tag, "FUNCTIONAL_LAYOUT_STAGE_", 24));
    assert(!strstr(tag, "FUNCTIONAL_VDF_PATH_") && strstr(text, "stage_only=1 semantic_applied=0 frame_consumed=0"));
    assert(strstr(text, "hardware_ready=0 capture_verified=0") && strstr(text, " raw=") &&
        strstr(text, " bank32=") && strstr(text, " copied_readback32=") && strlen(text) < 2100);
}
static int send(unsigned int destination, void *p) {
    inspect(); sends++;
    assert(!request_live && request_frees == sends && destination == source_id && ack_live);
    assert(message(p)->source == FUNCTIONAL_LAYOUT_STAGE_SID && message(p)->bytes == 12 && !memcmp(p, ack_wire, 12));
    ack_pointer = p;
    const struct functional_vdf_layout_stage_snapshot s = snapshot();
    assert(s.leases[0].freed && s.leases[1].send_inflight && !s.ap_consumed);
    if (is("inline-free") || is("inline-send-fail")) {
        int rc = 123;
        assert(functional_vdf_layout_stage_observe_receive_cycle(destination, p, FUNCTIONAL_LAYOUT_STAGE_SID, 12, &ticket) == 1);
        assert(functional_vdf_layout_stage_release_cycle(destination, p, ticket, real_free, logger, &rc) == 1 && !rc);
        assert(!snapshot().ap_consumed);
    }
    return is("send-fail") || is("inline-send-fail") ? -EPIPE : 0;
}
static const struct full_imaging_io io = {allocate, real_free, set_source, send, size_of, source_of, logger};
static void prepare(void) {
    assert(!request_live && !ack_live);
    memset(&original, 0, sizeof original); memcpy(original.data, wire, 40);
    original.source = source_id; original.bytes = 40; request_live = 1;
}
static int dispatch(void) {
    int rc = 123;
    assert(functional_vdf_layout_stage_dispatch(FUNCTIONAL_LAYOUT_STAGE_SID, original.data, &io, 1, 0, &rc) == 1);
    return rc;
}
static void consume(void) {
    int rc = 123;
    assert(functional_vdf_layout_stage_observe_receive_cycle(source_id, ack_pointer, FUNCTIONAL_LAYOUT_STAGE_SID, 12, &ticket) == 1);
    assert(ticket == snapshot().cycle);
    assert(functional_vdf_layout_stage_release_cycle(source_id, ack_pointer, ticket, real_free, logger, &rc) == 1 && !rc);
}
static void put32(unsigned char *p, uint32_t v) { for (unsigned int i = 0; i < 4; i++) p[i] = (unsigned char)(v >> (8 * i)); }
static void put64(unsigned char *p, uint64_t v) { put32(p, (uint32_t)v); put32(p + 4, (uint32_t)(v >> 32)); }
static void late_bind(void) {
    unsigned char bank[32], p[192] = {0}; uint64_t digest = 0;
    const uint64_t generation = snapshot().stage_generation;
    assert(functional_vdf_layout_stage_read_bank(generation, bank, 31, &digest) == -EINVAL);
    assert(functional_vdf_layout_stage_read_bank(generation - 1, bank, 32, &digest) == -ESTALE);
    assert(functional_vdf_layout_stage_read_bank(generation, bank, 32, &digest) == 0);
    assert(!memcmp(bank, wire + 8, 32) && digest == fnv(bank, 32));
    bank[31] = 1; assert(!snapshot().bank32[31]); bank[31] = 0;
    put32(p, FCAM_ABI_VERSION); put32(p + 4, 192); put64(p + 8, 55);
    put64(p + 16, 8); put64(p + 24, 3); put64(p + 32, 9); put64(p + 40, digest);
    put64(p + 48, 1234); put64(p + 56, 1234); put64(p + 64, 640 * 480 * 3);
    put32(p + 72, 640); put32(p + 76, 480); put32(p + 80, 1920); put32(p + 84, FCAM_VDF_ENDPOINT);
    for (size_t i = 88; i <= 116; i += 4) put32(p + i, 1);
    p[128] = 1; p[129] = p[130] = 5; put64(p + 144, 2); put64(p + 152, 7); memcpy(p + 160, bank, 32);
    struct fcam_bridge_result r = {.used = 192, .required = 192, .model_instance = 55};
    assert(functional_vdf_layout_stage_bind_applied(generation, getpid() + 1, 55, p, 192, &r) == -EXDEV);
    assert(functional_vdf_layout_stage_bind_applied(generation - 1, getpid(), 55, p, 192, &r) == -ESTALE);
    assert(functional_vdf_layout_stage_bind_applied(generation, getpid(), 56, p, 192, &r) == -EPROTO);
    for (size_t i = 160; i < 192; i++) {
        p[i] ^= 1;
        assert(functional_vdf_layout_stage_bind_applied(generation, getpid(), 55, p, 192, &r) == -EPROTO);
        p[i] ^= 1;
    }
    const size_t offsets[] = {40, 56, 64, 80, 104, 108, 112, 116, 120, 124, 141, 144, 152};
    for (size_t i = 0; i < sizeof offsets / sizeof *offsets; i++) {
        p[offsets[i]] ^= 1;
        assert(functional_vdf_layout_stage_bind_applied(generation, getpid(), 55, p, 192, &r) < 0);
        p[offsets[i]] ^= 1;
    }
    assert(!snapshot().applied.verified);
    assert(functional_vdf_layout_stage_bind_applied(generation, getpid(), 55, p, 192, &r) == 0);
    struct functional_vdf_layout_stage_snapshot s = snapshot();
    assert(s.applied.verified && s.applied.semantic_applied && s.applied.frame_consumed &&
        s.applied.owner_pid == getpid() && s.applied.stage_generation == generation &&
        s.applied.model_instance == 55 && s.applied.config_generation == 8 &&
        s.applied.frame_generation == 3 && s.applied.lease_generation == 9 && s.applied.result_fnv1a64 == fnv(p, 192));
    assert(functional_vdf_layout_stage_bind_applied(generation, getpid(), 55, p, 192, &r) == -ESTALE);
}
static void *foreign_thread(void *arg) {
    (void)arg;
    if (is("foreign-receive")) {
        uint64_t other = 0;
        assert(functional_vdf_layout_stage_observe_receive_cycle(source_id, ack_pointer, FUNCTIONAL_LAYOUT_STAGE_SID, 12, &other) == -EPROTO);
        assert(!other);
    } else {
        int rc = 123;
        assert(functional_vdf_layout_stage_release_cycle(source_id, ack_pointer, ticket, real_free, NULL, &rc) == 1 && rc == -EPROTO);
    }
    return NULL;
}
int main(int argc, char **argv) {
    assert(argc == 2); scenario = argv[1];
    assert(functional_vdf_layout_stage_owner_init() == 0);
    assert(functional_vdf_layout_stage_owner_init() == -EALREADY); prepare();
    if (is("fork")) {
        functional_vdf_layout_stage_test_hold_lock(); const pid_t child = fork(); assert(child >= 0);
        if (!child) {
            alarm(3); int rc = 123; uint64_t t = 0; unsigned char out[32];
            assert(functional_vdf_layout_stage_owner_init() == -EXDEV);
            assert(functional_vdf_layout_stage_dispatch(FUNCTIONAL_LAYOUT_STAGE_SID, original.data, &io, 1, 0, &rc) == 1 && rc == -EXDEV);
            assert(functional_vdf_layout_stage_observe_receive_cycle(source_id, original.data, FUNCTIONAL_LAYOUT_STAGE_SID, 12, &t) == -EXDEV);
            assert(functional_vdf_layout_stage_release_cycle(source_id, original.data, 1, real_free, logger, &rc) == 1 && rc == -EXDEV);
            assert(functional_vdf_layout_stage_read_bank(1, out, 32, &t) == -EXDEV);
            assert(functional_vdf_layout_stage_bind_applied(1, getpid(), 55, NULL, 0, NULL) == -EXDEV);
            struct functional_vdf_layout_stage_snapshot s; functional_vdf_layout_stage_snapshot(&s);
            assert(s.faults && s.owner_pid == getppid()); _exit(0);
        }
        int status = 0; assert(waitpid(child, &status, 0) == child && WIFEXITED(status) && !WEXITSTATUS(status));
        functional_vdf_layout_stage_test_drop_lock(); return 0;
    }
    if (is("profile")) {
        int rc = 123;
        for (int enabled = 0; enabled < 3; enabled++)
            for (int ready = -1; ready < 3; ready++) if (enabled != 1 || ready != 0)
                assert(functional_vdf_layout_stage_dispatch(FUNCTIONAL_LAYOUT_STAGE_SID, original.data, &io, enabled, ready, &rc) == 0);
        assert(rc == 123 && !logs && !allocations && !snapshot().requests); return 0;
    }
    if (is("shape")) {
        int rc = 123;
        for (size_t i = 4; i < 40; i++) {
            original.data[i] ^= 1; assert(dispatch() < 0); original.data[i] ^= 1;
        }
        original.bytes = 39; assert(dispatch() < 0); original.bytes = 41; assert(dispatch() < 0); original.bytes = 40;
        original.source = UINT32_C(0x81ce61c6); assert(dispatch() < 0); original.source = source_id;
        original.data[2] = 0x38;
        assert(functional_vdf_layout_stage_dispatch(FUNCTIONAL_LAYOUT_STAGE_SID, original.data, &io, 1, 0, &rc) == 0);
        assert(!snapshot().requests && request_live && !allocations); return 0;
    }
    if (is("source-mutation")) {
        assert(dispatch() == -ESTALE && request_live && !snapshot().requests && !allocations); return 0;
    }
    if (is("readback-fault")) functional_vdf_layout_stage_test_corrupt_readback(31);
    assert(dispatch() == 0); struct functional_vdf_layout_stage_snapshot s = snapshot();
    assert(s.request_owned && s.requests == 1 && s.stage_generation == 1 &&
        s.origin.source == source_id && s.origin.wire_fnv1a64 == fnv(wire, 40));
    if (is("inline-free") || is("inline-send-fail")) {
        assert(!heap_ack && !ack_live && s.leases[1].freed);
        assert(is("inline-free") ? s.ap_consumed && s.completed_cycles == 1 : s.faults && !s.ap_consumed);
        return 0;
    }
    if (is("send-fail")) { assert(s.faults && !s.ap_consumed && s.leases[1].pointer && !request_live); return 0; }
    if (s.faults) {
        assert(!s.ap_consumed && !s.completed_cycles && !sends);
        assert(s.leases[0].pointer == original.data && request_live);
        if (is("request-free-fail")) assert(s.leases[0].free_rc == -EIO && request_frees == 1 && s.leases[1].pointer);
        if (is("readback-fault")) assert(!s.readback_verified && s.bank_fnv1a64 != s.readback_fnv1a64 && !allocations);
        if (is("live-alias") || !strncmp(scenario, "private-alias-", 14)) assert(s.allocation_alias && !s.leases[1].pointer);
        assert(dispatch() < 0 && snapshot().requests == 1); free(heap_ack); return 0;
    }
    unsigned char bank[32]; uint64_t digest = 0;
    assert(functional_vdf_layout_stage_read_bank(1, bank, 32, &digest) == -ENODATA);
    if (is("receive-source") || is("receive-size") || is("receive-wire")) {
        if (is("receive-wire")) ((unsigned char *)ack_pointer)[11] ^= 1;
        assert(functional_vdf_layout_stage_observe_receive_cycle(source_id, ack_pointer,
            FUNCTIONAL_LAYOUT_STAGE_SID + (unsigned int)is("receive-source"), 12u + (unsigned int)is("receive-size"), &ticket) == -EPROTO);
        assert(!snapshot().ap_consumed && !ack_frees); return 0;
    }
    if (is("foreign-receive") || is("foreign-free")) {
        if (is("foreign-free")) assert(functional_vdf_layout_stage_observe_receive_cycle(source_id, ack_pointer, FUNCTIONAL_LAYOUT_STAGE_SID, 12, &ticket) == 1);
        pthread_t thread; assert(!pthread_create(&thread, NULL, foreign_thread, NULL)); assert(!pthread_join(thread, NULL));
        assert(snapshot().faults && !snapshot().ap_consumed && !ack_frees); return 0;
    }
    if (is("ack-free-fail") || is("reentrant-free")) {
        int rc = 123;
        assert(functional_vdf_layout_stage_observe_receive_cycle(source_id, ack_pointer, FUNCTIONAL_LAYOUT_STAGE_SID, 12, &ticket) == 1);
        assert(functional_vdf_layout_stage_release_cycle(source_id, ack_pointer, ticket, real_free, logger, &rc) == 1);
        assert(snapshot().faults && !snapshot().ap_consumed);
        if (is("ack-free-fail")) {
            assert(rc == -EIO && snapshot().leases[1].pointer == ack_pointer && ack_live);
            assert(functional_vdf_layout_stage_release_cycle(source_id, ack_pointer, ticket, real_free, logger, &rc) == 1 && !rc);
            assert(!snapshot().ap_consumed && snapshot().faults);
        }
        return 0;
    }
    consume(); assert(snapshot().ap_consumed && snapshot().completed_cycles == 1);
    if (is("late-bind")) { late_bind(); return 0; }
    if (is("repeat") || is("stale-ticket-reuse")) {
        const uint64_t old_ticket = ticket; void *old_pointer = ack_pointer;
        for (unsigned int cycle = 2; cycle <= 3; cycle++) {
            prepare(); assert(dispatch() == 0 && ack_pointer == old_pointer && snapshot().cycle == cycle);
            int rc = 123;
            assert(functional_vdf_layout_stage_release_cycle(source_id, ack_pointer, old_ticket, real_free, logger, &rc) == 1 && rc == -ESTALE);
            assert(ack_live && !snapshot().faults);
            assert(dispatch() == -EBUSY); consume();
            assert(snapshot().completed_cycles == cycle && snapshot().stage_generation == cycle && snapshot().ap_consumed);
        }
        assert(request_frees == 3 && ack_frees == 3 && allocations == 3 && sends == 3);
    }
    assert(logs); return 0;
}
