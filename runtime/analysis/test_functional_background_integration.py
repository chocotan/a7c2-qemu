# SPDX-License-Identifier: MIT
"""Real Core + background guest owner, using HOST_TEST transport/OSAL only.

The predecessor guard is a host fixture whose readiness follows a real malloc
allocation's free0. It does not prove native all13, trusted SDK caller binding,
mailbox/RSP transport, original AP execution, ASIC/CP history, or capture.
Each build freezes actual sources privately; no production artifact is built.
"""
from pathlib import Path
import hashlib
import json
import os
import re
import shlex
import struct
import subprocess

import pytest

HERE = Path(__file__).resolve().parent
NATIVE = HERE.parents[1]
CORE_SOURCES = (
    "functional-camera-core/functional-camera-core.c",
    "virtual-optics/optics.c",
    "virtual-optical-frame-owner/optical-frame-owner.c",
    "virtual-jpeg-hardware/jpeg-hardware.c",
    "virtual-jpeg-hardware/jpeg-hardware-codec.c",
    "virtual-jpeg-sos/jpeg-sos.c",
    "virtual-video-engine/video-engine.c",
    "virtual-camera-pipeline/camera-pipeline.c",
)
OWNER_SOURCES = (
    "functional-background-start.c", "functional-camera-control.c",
    "cp-full-state-snapshot.c", "cp-state-snapshot.c",
)
HARNESS = r'''
#ifndef HOST_TEST
#error Component-only fixture
#endif
#define _GNU_SOURCE
#include "runtime/analysis/device-models/functional-background-start.h"
#include "runtime/analysis/device-models/functional-camera-control.h"
#include "report/functional-camera-core/functional-camera-core.h"
#include "report/virtual-optical-frame-owner/optical-frame-owner.h"
#include <assert.h>
#include <math.h>
#include <stddef.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/syscall.h>
#include <unistd.h>

struct message { void *next; unsigned int flags, source, size, reserved; unsigned char body[]; };
_Static_assert(offsetof(struct message, body) == 24, "actual OSAL metadata head");
static struct fcam_model *model;
static const char *scenario;
static void *request_pointer, *reply_pointer, *queued, *received, *last13;
static unsigned int source_id = UINT32_C(0x810261c4), mode, held;
static unsigned int allocations, frees, reserves, unlocks, callback_snapshots, last13_frees;
static unsigned int background_inits, background_states, external_inits, control_inits;
static unsigned int request_frees, reply_frees, reply_free_attempts, sends;
static unsigned char request_wire[24], expected_reply[16], authentic[2][128];
static struct fcam_native_origin external_origin;
static unsigned int reply_bytes = 12;
static uint64_t ticket;
static long sender_tid;
static long tid(void) { return syscall(SYS_gettid); }
static uint32_t u32(const unsigned char *p) {
    return p[0] | (uint32_t)p[1] << 8 | (uint32_t)p[2] << 16 | (uint32_t)p[3] << 24;
}
static uint64_t u64(const unsigned char *p) { return u32(p) | (uint64_t)u32(p + 4) << 32; }
static void put32(unsigned char *p, uint32_t value) {
    for (unsigned int i = 0; i < 4; i++) p[i] = (unsigned char)(value >> (8 * i));
}
static void put64(unsigned char *p, uint64_t value) {
    put32(p, (uint32_t)value); put32(p + 4, (uint32_t)(value >> 32));
}
static uint64_t fnv(const void *pointer, size_t bytes) {
    const unsigned char *p = pointer; uint64_t h = UINT64_C(14695981039346656037);
    for (size_t i = 0; i < bytes; i++) h = (h ^ p[i]) * UINT64_C(1099511628211);
    return h;
}
static void hex(const void *pointer, size_t bytes) {
    const unsigned char *p = pointer;
    for (size_t i = 0; i < bytes; i++) printf("%02x", p[i]);
}
static struct functional_background_start_snapshot snapshot(void) {
    struct functional_background_start_snapshot s; functional_background_start_snapshot(&s);
    assert(s.initialized && s.owner_pid == getpid() && s.functional_model);
    assert(!s.source_physical_verified && !s.original_cp_rtos_verified && !s.cp_modules_verified &&
        !s.original_masks_verified && !s.business_published && !s.hardware_ready && !s.image_ready && !s.capture_verified);
    return s;
}
/* Every external callback reenters snapshots, so a held private lock times out. */
static void outside_lock(void) {
    (void)snapshot();
    struct native_functional_camera_control_snapshot c; native_functional_camera_control_snapshot(&c);
    assert(c.initialized && !c.original_cp && !c.physical_asic_verified && !c.ee && !c.frame && !c.capture);
    callback_snapshots++;
}
static struct message *envelope(void *p) {
    return (struct message *)((unsigned char *)p - offsetof(struct message, body));
}
static void *message(unsigned int bytes, unsigned int source) {
    struct message *m = calloc(1, sizeof *m + bytes); assert(m);
    m->size = bytes; m->source = source; allocations++; return m->body;
}
static void destroy(void *p) { assert(p); free(envelope(p)); frees++; }
static unsigned int size(void *p) { outside_lock(); return envelope(p)->size; }
static unsigned int source(void *p) { outside_lock(); return envelope(p)->source; }
static void set_source(void *p, unsigned int value) { outside_lock(); envelope(p)->source = value; }
static void logger(const char *tag, const char *text) {
    outside_lock(); assert(tag && text); printf("%s%s\n", tag, text);
}
/* shortcut: host predecessor lease only; the parent's native all13 proof remains separate. */
static int predecessor_ready(void) {
    outside_lock(); return last13_frees == 1 && last13 == NULL;
}
static int reserve(void) {
    outside_lock(); assert(!held && predecessor_ready() == 1); held = 1; reserves++; return 0;
}
static void release_guard(void) { outside_lock(); assert(held); held = 0; unlocks++; }
static const struct native_cp_state_publication_guard guard = {reserve, release_guard, predecessor_ready};
static void free_last13(void) {
    outside_lock(); assert(last13 && !last13_frees && !held && !background_inits);
    assert(envelope(last13)->size == 12 && envelope(last13)->source == UINT32_C(0x8102d013));
    static const unsigned char original[12] = {1,0,0x13,0x30,0x6a,0x79,0x2c,0x17,0,0xf0,0,0};
    assert(!memcmp(last13, original, sizeof original));
    destroy(last13); last13 = NULL; last13_frees++;
}
static int allocate(unsigned int destination, void **out, unsigned int bytes, unsigned int option) {
    outside_lock(); assert(destination == source_id && bytes == reply_bytes && option == 1 && !reply_pointer && held);
    if (!mode) {
        const struct functional_background_start_snapshot s = snapshot();
        assert(!request_pointer && s.original_request_freed && s.model_complete && s.readback_verified && !s.ap_consumed);
    } else assert(mode == 2 && request_pointer);
    *out = reply_pointer = message(bytes, 0); return 0;
}
static int real_free(unsigned int destination, void *p) {
    outside_lock(); assert(p && tid() == sender_tid);
    if (p == request_pointer) {
        assert(destination == UINT32_C(0x90030001) && size(p) == 24 && source(p) == source_id &&
            !memcmp(p, request_wire, sizeof request_wire));
        if (!mode) {
            const struct functional_background_start_snapshot s = snapshot();
            assert(s.leases[0].releasing && s.model_complete && s.readback_verified && !reply_pointer);
        }
        request_pointer = NULL; request_frees++;
    } else {
        assert(p == reply_pointer && p == received && destination == source_id && source(p) == UINT32_C(0x90030001) &&
            size(p) == reply_bytes && !memcmp(p, expected_reply, reply_bytes));
        reply_free_attempts++;
        if (!mode) {
            const struct functional_background_start_snapshot s = snapshot();
            assert(s.reply_received && s.leases[1].releasing && !s.ap_consumed && s.receiver_tid == sender_tid);
            if (!strcmp(scenario, "reply-free-failure")) return -EIO;
        }
        reply_pointer = received = queued = NULL; reply_frees++;
    }
    destroy(p); return 0;
}
static int send(unsigned int destination, void *p) {
    outside_lock(); assert(destination == source_id && p == reply_pointer && !queued && held &&
        source(p) == UINT32_C(0x90030001) && size(p) == reply_bytes && !memcmp(p, expected_reply, reply_bytes));
    if (!mode) {
        const struct functional_background_start_snapshot s = snapshot();
        assert(!request_pointer && s.original_request_freed && s.leases[1].send_inflight && !s.ap_consumed);
    }
    queued = p; sends++; return 0;
}
static const struct full_imaging_io io = {allocate, real_free, set_source, send, size, source, logger};
static struct fcam_frame_proof proof(void) {
    struct fcam_frame_proof p; assert(!fcam_model_proof_snapshot(model, &p, sizeof p));
    assert(p.version == FCAM_PROOF_VERSION && p.struct_bytes == sizeof p && p.owner_pid == (uint64_t)getpid());
    return p;
}
static void core_state(unsigned int opcode, const unsigned char *input, size_t bytes, unsigned char out[128]) {
    struct fcam_exec_result result = {0};
    assert(!fcam_model_request(model, opcode, input, bytes, out, 128, &result));
    assert(result.used == 128 && !result.token && !result.total && !result.offset);
}
/* shortcut: direct synchronous HOST_TEST bridge; no mailbox, broker or RSP evidence. */
int fcam_bridge_call(const struct fcam_native_origin *origin, uint32_t opcode, const void *input, size_t input_bytes,
    void *out, size_t capacity, struct fcam_bridge_result *result) {
    outside_lock(); assert(origin && out && result && !input && !input_bytes && capacity == 128);
    assert(opcode == FCAM_OP_INIT || opcode == FCAM_OP_STATE);
    if (mode == 1) { assert(!memcmp(origin, &external_origin, sizeof *origin)); external_inits++; }
    else {
        assert(held && request_pointer && origin->source == source_id && origin->destination == UINT32_C(0x90030001) &&
            origin->bytes == 24 && origin->wire_fnv1a64 == fnv(request_pointer, 24));
        if (!mode) {
            const struct functional_background_start_snapshot s = snapshot();
            assert(origin->command == 0x3006 && s.working && s.guard_held && s.producer_tid == tid());
            if (opcode == FCAM_OP_INIT) background_inits++; else background_states++;
        } else { assert(mode == 2 && opcode == FCAM_OP_INIT && origin->command == 0x3003); control_inits++; }
    }
    struct fcam_exec_result actual = {0};
    const int rc = fcam_model_request(model, opcode, NULL, 0, out, capacity, &actual);
    assert(rc == ((!mode && !strcmp(scenario, "core-busy")) ? -EBUSY : 0));
    assert(!actual.token && !actual.total && !actual.offset && actual.used == (rc ? 0u : 128u));
    *result = (struct fcam_bridge_result){actual.used, actual.used, proof().model_instance, actual.token};
    if (!mode) memcpy(authentic[opcode == FCAM_OP_STATE], out, 128);
    if (!mode && opcode == FCAM_OP_STATE) {
        if (!strcmp(scenario, "state-byte")) ((unsigned char *)out)[FCAM_S_FPS] ^= 1;
        if (!strcmp(scenario, "state-instance")) ((unsigned char *)out)[FCAM_S_INSTANCE] ^= 1;
        if (!strcmp(scenario, "state-metadata")) result->model_instance ^= 1;
    }
    printf("bridge mode=%u opcode=%u rc=%d instance=%016llx actual128=", mode, opcode, rc,
        (unsigned long long)proof().model_instance);
    if (!mode) hex(authentic[opcode == FCAM_OP_STATE], 128); else hex(out, 128);
    printf(" delivered128="); hex(out, 128); putchar('\n'); return rc;
}
static void config(unsigned char out[48]) {
    memset(out, 0, 48); put32(out, 640); put32(out + 4, 480); put32(out + 8, 50);
    put32(out + 12, 82); put32(out + 16, 800); put32(out + 20, 200);
    put64(out + 24, 2500); put64(out + 32, UINT64_MAX);
}
static void prepare(unsigned int command) {
    assert(!request_pointer && !reply_pointer && !queued && !received);
    for (unsigned int i = 0; i < sizeof request_wire; i++) request_wire[i] = (unsigned char)(0x91 + i * 7);
    request_wire[0] = 0; request_wire[2] = (unsigned char)command; request_wire[3] = (unsigned char)(command >> 8);
    if (mode == 2) memset(request_wire + 8, 0, 16);
    request_pointer = message(24, source_id); memcpy(request_pointer, request_wire, sizeof request_wire);
    memset(expected_reply, 0, sizeof expected_reply); expected_reply[0] = 1;
    expected_reply[2] = request_wire[2]; expected_reply[3] = request_wire[3];
    memcpy(expected_reply + 4, request_wire + 4, 4); expected_reply[9] = 0xf0;
}
static void retain_fault(void) {
    const struct functional_background_start_snapshot before = snapshot();
    assert(before.faults && before.pending && !before.ap_consumed && !before.transport_complete &&
        !before.working && !before.guard_held && before.error < 0 && !held);
    const unsigned int old_inits = background_inits, old_states = background_states, old_sends = sends;
    const unsigned int old_frees = request_frees + reply_free_attempts;
    assert(functional_background_start_progress() == before.error);
    const struct functional_background_start_snapshot after = snapshot();
    assert(!memcmp(&before, &after, sizeof before) && old_inits == background_inits && old_states == background_states &&
        old_sends == sends && old_frees == request_frees + reply_free_attempts);
    printf("retained original=%u reply=%u live=%u error=%d retries=0 AP_consumed=0\n",
        request_pointer != NULL, reply_pointer != NULL, before.live_leases, before.error);
    if (request_pointer) { assert(before.leases[0].pointer == request_pointer); destroy(request_pointer); request_pointer = NULL; }
    if (reply_pointer) { assert(before.leases[1].pointer == reply_pointer); destroy(reply_pointer); reply_pointer = queued = received = NULL; }
    const struct functional_background_start_snapshot cleaned = snapshot();
    assert(!memcmp(&before, &cleaned, sizeof before));
    puts("cleanup explicit_fixture_cleanup=1 owner_unchanged=1");
}
static void preinitialize(void) {
    unsigned char out[128], c[48], wire[24] = {0x0d,0x20,0x38,1,24,0,1,0x80,1,5,5,0,2};
    external_origin = (struct fcam_native_origin){UINT32_C(0x81cf0012),UINT32_C(0x92840747),0x0138,24,fnv(wire,24)};
    struct fcam_bridge_result result = {0}; mode = 1;
    assert(!fcam_bridge_call(&external_origin, FCAM_OP_INIT, NULL, 0, out, 128, &result));
    config(c); core_state(FCAM_OP_CONFIGURE, c, sizeof c, out);
    unsigned char path[16] = {1,5,5,0,2}, receipt[160]; struct fcam_exec_result applied = {0};
    assert(!fcam_model_request(model, FCAM_OP_VDF_PATH, path, sizeof path, receipt, sizeof receipt, &applied));
    assert(applied.used == sizeof receipt && !applied.token && !applied.total && !applied.offset);
    const struct fcam_frame_proof p = proof();
    assert(p.opcode == FCAM_OP_VDF_PATH && p.consumer_entered && p.consumer_returned && p.retired &&
        p.active_bytes == UINT64_C(921600) && p.source_fnv1a64 && p.source_fnv1a64 == p.consumer_after_fnv1a64 &&
        u64(receipt + 48) == p.source_fnv1a64 && u64(receipt + 56) == p.consumer_after_fnv1a64);
    printf("preinitialized source=%08x instance=%016llx rendered=%llu consumed=%llu source_fnv=%016llx sink_fnv=%016llx\n",
        external_origin.source, (unsigned long long)p.model_instance, (unsigned long long)p.after.rendered,
        (unsigned long long)p.after.consumed, (unsigned long long)p.source_fnv1a64, (unsigned long long)p.consumer_after_fnv1a64);
    mode = 0;
}
static void verify_model(const unsigned char before[128], const struct fcam_frame_proof *previous) {
    const struct functional_background_start_snapshot s = snapshot(); unsigned char current[128];
    core_state(FCAM_OP_STATE, NULL, 0, current);
    assert(s.model_complete && s.readback_verified && s.state_copied && s.functional_core_initialized &&
        !memcmp(current, authentic[0], 128) && !memcmp(current, authentic[1], 128) &&
        !memcmp(current, s.init_state, 128) && !memcmp(current, s.actual_state, 128) &&
        !memcmp(current, s.model_state, 128) && !memcmp(current, s.copied_readback, 128));
    assert(s.init_fnv1a64 == fnv(current, 128) && s.state_fnv1a64 == s.init_fnv1a64 &&
        s.cache_fnv1a64 == s.init_fnv1a64 && s.readback_fnv1a64 == s.init_fnv1a64 &&
        s.model_instance == u64(current + 48) && s.model_instance == proof().model_instance);
    assert(s.config_generation == u64(current + 56) && s.frame_generation == u64(current + 112) &&
        s.rendered == u64(current + 64) && s.consumed == u64(current + 72) &&
        !s.jpeg_encoded && !s.video_encoded && !s.result_bytes_read);
    const struct fcam_frame_proof p = proof();
    if (!strcmp(scenario, "preinitialized")) {
        assert(!memcmp(&p, previous, sizeof p) && !memcmp(before, current, 128));
        assert(u32(current + 16) == 50 && u32(current + 28) == 200 && s.rendered == 2 && s.consumed == 1);
    } else {
        assert(p.opcode == FCAM_OP_INIT && p.render_observed && p.retired && !p.consumer_entered &&
            !p.consumer_returned && !p.encoder_consumed && p.after.rendered == previous->after.rendered + 1 &&
            p.after.retired == previous->after.retired + 1 && p.after.consumed == previous->after.consumed &&
            p.width == 640 && p.height == 480 && p.stride == 1920 && p.active_bytes == UINT64_C(921600) &&
            p.source_fnv1a64 && p.final_state == OPTICAL_FRAME_IDLE && !p.render_status && !p.retire_status);
    }
    printf("model instance=%016llx config=%llu frame=%llu rendered=%llu consumed=%llu retired=%llu active_bytes=%llu "
        "source_fnv=%016llx full_fnv=%016llx state128=", (unsigned long long)s.model_instance,
        (unsigned long long)s.config_generation, (unsigned long long)s.frame_generation, (unsigned long long)s.rendered,
        (unsigned long long)s.consumed, (unsigned long long)p.after.retired, (unsigned long long)p.active_bytes,
        (unsigned long long)p.source_fnv1a64, (unsigned long long)s.state_fnv1a64);
    hex(current, 128); printf(" cache128="); hex(s.model_state, 128); printf(" readback128="); hex(s.copied_readback, 128); putchar('\n');
}
static void later_control(void) {
    unsigned char before[128], after[128]; core_state(FCAM_OP_STATE, NULL, 0, before);
    const struct fcam_frame_proof old_proof = proof();
    const struct functional_background_start_snapshot background = snapshot();
    struct native_functional_camera_control_snapshot empty; native_functional_camera_control_snapshot(&empty);
    assert(!empty.model_initialized && !empty.start_requests && !empty.probe_attempts);
    mode = 2; source_id = FUNCTIONAL_CAMERA_CONTROL_AP; reply_bytes = 16; prepare(0x3003); int rc = 999;
    assert(native_functional_camera_control_dispatch(FUNCTIONAL_CAMERA_CONTROL_SID, request_pointer, &io, &guard, 1, &rc) == 1 && !rc);
    struct native_functional_camera_control_snapshot c; native_functional_camera_control_snapshot(&c);
    assert(c.model_initialized && c.business_ready && !c.start_complete && !c.faults && !request_pointer && queued);
    assert(c.model_instance == u64(before + 48) && !memcmp(c.model_state, before, 128) && c.last_origin.source == source_id &&
        c.last_origin.command == 0x3003 && c.probe_attempts == 1 && c.probe_successes == 1);
    received = queued;
    assert(native_functional_camera_control_observe_receive(source_id, received, source(received), size(received)) == 1);
    assert(native_functional_camera_control_release(source_id, received, real_free, logger, &rc) == 1 && !rc);
    native_functional_camera_control_snapshot(&c); assert(c.start_complete && !c.faults);
    core_state(FCAM_OP_STATE, NULL, 0, after); const struct fcam_frame_proof new_proof = proof();
    const struct functional_background_start_snapshot unchanged = snapshot();
    assert(!memcmp(before, after, 128) && !memcmp(&old_proof, &new_proof, sizeof old_proof) &&
        !memcmp(&background, &unchanged, sizeof background));
    puts("control original_command=3003 original_source=80020002 actual_owner=1 same_instance=1 all_state_preserved=1 proof_preserved=1 background_preserved=1 start_ACK_free0=1");
}
int main(int argc, char **argv) {
    assert(argc == 2); scenario = argv[1]; setvbuf(stdout, NULL, _IONBF, 0); sender_tid = tid();
    assert(!functional_background_start_owner_init() && !native_functional_camera_control_owner_init());
    if (!strcmp(scenario, "preinitialized")) source_id = UINT32_C(0x8102a9f3);
    assert(!functional_background_start_bind_source_once(source_id));
    model = fcam_model_create(UINT64_C(0x9a17013006)); assert(model);
    if (!strcmp(scenario, "preinitialized")) preinitialize();
    if (!strcmp(scenario, "core-busy")) {
        unsigned char c[48], out[128]; config(c); core_state(FCAM_OP_VIDEO_BEGIN, c, 48, out);
    }
    unsigned char before[128]; core_state(FCAM_OP_STATE, NULL, 0, before); const struct fcam_frame_proof previous = proof();
    prepare(0x3006);
    last13 = message(12, UINT32_C(0x8102d013));
    static const unsigned char final_reply[12] = {1,0,0x13,0x30,0x6a,0x79,0x2c,0x17,0,0xf0,0,0};
    memcpy(last13, final_reply, 12); int rc = 999;
    assert(functional_background_start_dispatch(FUNCTIONAL_BACKGROUND_START_SID, request_pointer, &io, &guard, 1, &rc) == 1 && !rc);
    struct functional_background_start_snapshot s = snapshot();
    assert(s.pending && s.live_leases == 1 && s.leases[0].pointer == request_pointer && !s.model_complete &&
        !s.functional_core_initialized && !s.reply_queued && !s.ap_consumed && !background_inits && !background_states &&
        !reserves && !request_frees && !sends && !held && !memcmp(request_pointer, request_wire, 24));
    unsigned char pending_state[128]; core_state(FCAM_OP_STATE, NULL, 0, pending_state); const struct fcam_frame_proof pending_proof = proof();
    assert(!memcmp(before, pending_state, 128) && !memcmp(&previous, &pending_proof, sizeof previous));
    assert(!functional_background_start_progress() && !background_inits && !reserves);
    printf("pending init_calls=0 state_calls=0 reserves=0 ACKs=0 request_frees=0 model_unchanged=1 state128="); hex(pending_state, 128); putchar('\n');
    free_last13(); rc = functional_background_start_progress(); s = snapshot();
    assert(!held && reserves == unlocks && reserves == 1 && background_inits == 1);
    if (!strcmp(scenario, "core-busy") || !strncmp(scenario, "state-", 6)) {
        assert(rc < 0 && s.faults && !s.model_complete && !s.readback_verified && !s.original_request_freed &&
            request_pointer && !reply_pointer && !sends && !request_frees && !reply_free_attempts);
        assert(!memcmp(request_pointer, request_wire, 24));
        if (!strcmp(scenario, "core-busy")) {
            assert(rc == -EBUSY && s.init_rc == -EBUSY && !background_states && !s.probe_successes);
            unsigned char unchanged[128]; core_state(FCAM_OP_STATE, NULL, 0, unchanged);
            assert(!memcmp(before, unchanged, 128));
        } else {
            assert(rc == -ESTALE && !s.init_rc && !s.state_rc && background_states == 1 && s.probe_successes == 1 &&
                !memcmp(authentic[0], authentic[1], 128));
            if (!strcmp(scenario, "state-byte") || !strcmp(scenario, "state-instance")) assert(s.init_fnv1a64 != s.state_fnv1a64);
            else assert(s.init_fnv1a64 == s.state_fnv1a64 && s.init_result.model_instance != s.state_result.model_instance);
        }
        retain_fault(); goto done;
    }
    assert(rc == 1 && background_states == 1); verify_model(before, &previous); s = snapshot();
    assert(s.reply_queued && !s.reply_received && !s.ap_consumed && !s.transport_complete && s.pending &&
        s.live_leases == 1 && s.original_request_freed && !request_pointer && request_frees == 1 && sends == 1 &&
        reply_pointer == queued && !s.leases[1].send_rc && !reply_free_attempts && s.sender_tid == sender_tid);
    printf("queued send_rc=0 request_free_rc=0 ACKs=1 AP_consumed=0 source=%08x request24=", source_id);
    hex(request_wire, 24); printf(" reply12="); hex(reply_pointer, 12); putchar('\n');
    if (!strcmp(scenario, "free-before-receive")) {
        assert(functional_background_start_release_cycle(source_id, reply_pointer, s.cycle, real_free, logger, &rc) == 1 && rc == -EPROTO);
        assert(!reply_free_attempts); retain_fault(); goto done;
    }
    received = queued;
    assert(functional_background_start_observe_receive_cycle(source_id, received, source(received), size(received), &ticket) == 1);
    s = snapshot(); assert(ticket == s.cycle && s.reply_received && !s.ap_consumed && !s.transport_complete && !reply_free_attempts);
    printf("received ticket=%llu AP_consumed=0 free_calls=0\n", (unsigned long long)ticket);
    assert(functional_background_start_release_cycle(source_id, received, ticket, real_free, logger, &rc) == 1);
    if (!strcmp(scenario, "reply-free-failure")) {
        assert(rc == -EIO && reply_free_attempts == 1 && !reply_frees); retain_fault(); goto done;
    }
    assert(!rc); s = snapshot();
    assert(s.ap_consumed && s.transport_complete && s.completed_cycles == 1 && !s.pending && !s.live_leases &&
        s.leases[1].consumed && s.leases[1].freed && s.leases[1].sender_tid == sender_tid &&
        s.leases[1].receiver_tid == sender_tid && s.leases[1].free_tid == sender_tid && reply_frees == 1);
    puts("completed ticket_from_receive=1 actual_sender_free0=1 AP_consumed=1 transport_complete=1 same_sender_receive_free=1");
    later_control();
done:
    assert(!request_pointer && !reply_pointer && !queued && !received && !last13 && !held &&
        allocations == frees && reserves == unlocks && callback_snapshots > 10);
    fcam_model_destroy(model);
    printf("result scenario=%s background_init=%u background_state=%u external_init=%u control_init=%u "
        "allocations=%u frees=%u request_frees=%u reply_frees=%u reply_free_attempts=%u callbacks=%u "
        "host_predecessor_free0=%u native_predecessors_verified=false physical_asic_verified=false "
        "original_ap_verified=false original_cp_rtos_verified=false CP_modules_verified=false image_ready=false capture_verified=false\n",
        scenario, background_inits, background_states, external_inits, control_inits, allocations, frees,
        request_frees, reply_frees, reply_free_attempts, callback_snapshots, last13_frees);
    return 0;
}
'''


def sha(data):
    return hashlib.sha256(data).hexdigest()


def save(path, data):
    path.write_text(json.dumps(data, indent=2) + "\n")


@pytest.fixture(scope="module", params=("strict", "asan-ubsan"))
def background_integration_binary(tmp_path_factory, request):
    directory = tmp_path_factory.mktemp("functional-bg-realcore-" + request.param)
    snapshot = directory / "sources"
    source_paths = [HERE / "device-models" / name for name in OWNER_SOURCES]
    source_paths += [NATIVE / "report" / name for name in CORE_SOURCES]
    pending = [*source_paths, HERE / "device-models/functional-background-start.h",
               HERE / "device-models/functional-camera-control.h"]
    frozen = {}
    while pending:
        path = pending.pop().resolve()
        if path in frozen:
            continue
        relative = path.relative_to(NATIVE)
        raw = path.read_bytes()
        frozen[path] = raw
        target = snapshot / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(raw)
        pending += [path.parent / name.decode("ascii") for name in re.findall(
            rb'^\s*#\s*include\s*"([^"]+)"', raw, flags=re.MULTILINE)]
    inputs = {str(path.relative_to(NATIVE)): sha(raw) for path, raw in sorted(frozen.items())}
    artifacts = [HERE / "functional-camera-model.so", HERE / "functional-camera-model-build.json"]
    artifacts = {str(path): sha(path.read_bytes()) for path in artifacts if path.exists()}
    harness = directory / "integration.c"
    harness.write_text(HARNESS)
    save(directory / "inputs.json", {"sources": inputs, "harness_sha256": sha(harness.read_bytes()),
                                     "production_artifacts_read_only": artifacts, "capture_verified": False})
    libraries = subprocess.check_output([
        "pkg-config", "--cflags", "--libs", "libjpeg", "libavcodec", "libavformat",
        "libavutil", "libswscale"], text=True, timeout=15)
    flags = ["-fsanitize=address,undefined", "-fno-sanitize-recover=all"] if request.param == "asan-ubsan" else []
    binary = directory / "integration"
    command = [*shlex.split(os.environ.get("CC", "cc")), "-DHOST_TEST", "-std=c11", "-Wall", "-Wextra",
               "-Werror", "-pedantic", "-O1", "-g", "-fno-omit-frame-pointer", "-fno-pie", "-no-pie", "-pthread",
               *flags, "-I", str(snapshot), str(harness),
               *(str(snapshot / path.relative_to(NATIVE)) for path in source_paths),
               *shlex.split(libraries), "-lm", "-o", str(binary)]
    result = subprocess.run(command, cwd=directory, capture_output=True, text=True, timeout=90)
    (directory / "compile.log").write_text(result.stdout + result.stderr)
    save(directory / "compile.json", {"command": command, "returncode": result.returncode,
                                       "pkg_config": libraries, "log_sha256": sha((directory / "compile.log").read_bytes())})
    assert result.returncode == 0, result.stdout + result.stderr
    assert all(path.read_bytes() == raw for path, raw in frozen.items()), "source changed while freezing/building"
    save(directory / "build.json", {"binary_sha256": sha(binary.read_bytes()), "mode": request.param,
                                     "source_snapshot": inputs})
    yield binary
    assert all(sha(Path(path).read_bytes()) == value for path, value in artifacts.items()), "production artifact changed"


def run(binary, scenario):
    env = {**os.environ, "ASAN_OPTIONS": "detect_leaks=1:halt_on_error=1:abort_on_error=1",
           "UBSAN_OPTIONS": "halt_on_error=1:print_stacktrace=1"}
    command = [str(binary), scenario]
    try:
        result = subprocess.run(command, cwd=binary.parent, env=env, capture_output=True, text=True, timeout=30)
    except subprocess.TimeoutExpired as error:
        (binary.parent / (scenario + ".stdout.log")).write_bytes(error.stdout or b"")
        (binary.parent / (scenario + ".stderr.log")).write_bytes(error.stderr or b"")
        save(binary.parent / (scenario + ".json"), {"command": command, "timeout": 30, "capture_verified": False})
        raise
    stdout = binary.parent / (scenario + ".stdout.log")
    stderr = binary.parent / (scenario + ".stderr.log")
    stdout.write_text(result.stdout)
    stderr.write_text(result.stderr)
    save(binary.parent / (scenario + ".json"), {"command": command, "returncode": result.returncode,
         "stdout_sha256": sha(stdout.read_bytes()), "stderr_sha256": sha(stderr.read_bytes()), "capture_verified": False})
    assert result.returncode == 0, f"{scenario}\n{result.stdout}\n{result.stderr}"
    assert "Sanitizer" not in result.stderr and "runtime error:" not in result.stderr
    result_row, = rows(result.stdout, "result")
    assert result_row["allocations"] == result_row["frees"]
    assert int(result_row["callbacks"]) > 10 and result_row["host_predecessor_free0"] == "1"
    assert all(result_row[key] == "false" for key in (
        "native_predecessors_verified", "physical_asic_verified", "original_ap_verified",
        "original_cp_rtos_verified", "CP_modules_verified", "image_ready", "capture_verified"))
    pending, = rows(result.stdout, "pending")
    assert all(pending[key] == "0" for key in ("init_calls", "state_calls", "reserves", "ACKs", "request_frees"))
    assert pending["model_unchanged"] == "1"
    return result.stdout, result_row, bytes.fromhex(pending["state128"])


def rows(stdout, prefix):
    return [dict(item.split("=", 1) for item in line.split()[1:])
            for line in stdout.splitlines() if line.startswith(prefix + " ")]


def fnv(data):
    result = 14695981039346656037
    for byte in data:
        result = ((result ^ byte) * 1099511628211) & 0xffffffffffffffff
    return result


def check_successful_probe(stdout, pending, *, preinitialized=False):
    receipt, = rows(stdout, "model")
    state = bytes.fromhex(receipt["state128"])
    assert len(state) == 128 and bytes.fromhex(receipt["cache128"]) == state == bytes.fromhex(receipt["readback128"])
    assert receipt["full_fnv"] == f"{fnv(state):016x}"
    abi, caps, width, height, fps, quality, aperture, iso = struct.unpack_from("<8I", state)
    assert (abi, caps, width, height) == (1, 15, 640, 480)
    assert (fps, quality, aperture, iso) == ((50, 82, 800, 200) if preinitialized else (30, 90, 400, 100))
    assert int(receipt["active_bytes"]) == 921600 and int(receipt["source_fnv"], 16)
    assert state[120:] == bytes(8) and state[80:112] == bytes(32)
    assert struct.unpack_from("<Q", state, 48)[0] == int(receipt["instance"], 16)
    generation, rendered, consumed = struct.unpack_from("<3Q", state, 56)
    assert (generation, rendered, consumed) == ((3, 2, 1) if preinitialized else (1, 1, 0))
    assert int(receipt["config"]) == generation and int(receipt["rendered"]) == rendered and int(receipt["consumed"]) == consumed
    assert int(receipt["retired"]) == rendered and int(receipt["frame"]) == struct.unpack_from("<Q", state, 112)[0] == rendered
    if preinitialized:
        assert pending == state
    else:
        assert struct.unpack_from("<2Q", pending, 64) == (0, 0) and struct.unpack_from("<Q", pending, 112) == (0,)
    probes = [row for row in rows(stdout, "bridge") if row["mode"] == "0"]
    assert len(probes) == 2 and all(bytes.fromhex(row["actual128"]) == state == bytes.fromhex(row["delivered128"]) for row in probes)
    queued, = rows(stdout, "queued")
    request = bytes.fromhex(queued["request24"])
    expected = b"\x01\x00\x06\x30" + request[4:8] + b"\x00\xf0\x00\x00"
    assert len(request) == 24 and request[:4] == bytes.fromhex("00980630")
    assert bytes.fromhex(queued["reply12"]) == expected
    assert queued["send_rc"] == queued["request_free_rc"] == queued["AP_consumed"] == "0"
    return state


def test_real_background_deferred_probe_and_ap_lease(background_integration_binary):
    for scenario in ("early", "reply-free-failure", "free-before-receive"):
        stdout, result, pending = run(background_integration_binary, scenario)
        check_successful_probe(stdout, pending)
        assert result["background_init"] == result["background_state"] == "1"
        assert result["request_frees"] == str(2 if scenario == "early" else 1)
        if scenario == "early":
            assert len(rows(stdout, "completed")) == 1 and result["control_init"] == "1"
            assert "same_sender_receive_free=1" in stdout
            assert "actual_owner=1 same_instance=1 all_state_preserved=1 proof_preserved=1" in stdout
        else:
            retained, = rows(stdout, "retained")
            assert retained["original"] == "0" and retained["reply"] == retained["live"] == "1"
            assert result["reply_frees"] == "0" and result["control_init"] == "0"
            assert result["reply_free_attempts"] == str(int(scenario == "reply-free-failure"))
            assert not rows(stdout, "completed")
        if scenario != "free-before-receive":
            received, = rows(stdout, "received")
            assert received["ticket"] == "1" and received["AP_consumed"] == received["free_calls"] == "0"


def test_real_background_reuses_other_origin_core_without_poisoning_control(background_integration_binary):
    stdout, result, pending = run(background_integration_binary, "preinitialized")
    check_successful_probe(stdout, pending, preinitialized=True)
    assert result["external_init"] == result["background_init"] == result["background_state"] == result["control_init"] == "1"
    original, = rows(stdout, "preinitialized")
    assert original["source"] == "81cf0012" and original["source_fnv"] == original["sink_fnv"]
    queued, = rows(stdout, "queued")
    assert queued["source"] == "8102a9f3"
    assert "control original_command=3003 original_source=80020002 actual_owner=1 same_instance=1" in stdout
    assert "proof_preserved=1 background_preserved=1 start_ACK_free0=1" in stdout


def test_real_background_rejects_actual_core_failure_or_mutated_reply(background_integration_binary):
    for scenario in ("core-busy", "state-byte", "state-instance", "state-metadata"):
        stdout, result, _ = run(background_integration_binary, scenario)
        retained, = rows(stdout, "retained")
        assert retained["original"] == retained["live"] == "1" and retained["reply"] == "0"
        assert retained["AP_consumed"] == "0" and retained["retries"] == "0"
        assert result["request_frees"] == result["reply_frees"] == result["control_init"] == "0"
        assert not rows(stdout, "queued") and not rows(stdout, "completed")
        probes = rows(stdout, "bridge")
        if scenario == "core-busy":
            assert len(probes) == 1 and int(probes[0]["rc"]) < 0 and result["background_state"] == "0"
        else:
            assert len(probes) == 2 and all(row["rc"] == "0" for row in probes)
            actual = bytes.fromhex(probes[1]["actual128"])
            delivered = bytes.fromhex(probes[1]["delivered128"])
            assert len(actual) == len(delivered) == 128 and actual == bytes.fromhex(probes[0]["actual128"])
            changed = [offset for offset, (a, b) in enumerate(zip(actual, delivered)) if a != b]
            assert changed == {"state-byte": [16], "state-instance": [48], "state-metadata": []}[scenario]
            if changed:
                assert fnv(actual) != fnv(delivered)
        assert "cleanup explicit_fixture_cleanup=1 owner_unchanged=1" in stdout
