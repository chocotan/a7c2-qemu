/* SPDX-License-Identifier: MIT */
#ifndef HOST_TEST
#error Host component fixture only; no original AP, VM or native predecessor proof.
#endif
#define _GNU_SOURCE
#include "functional-background-start.h"
#include "../../../report/functional-camera-core/functional-camera-core.h"
#include "../../../report/virtual-optical-frame-owner/optical-frame-owner.h"
#include <assert.h>
#include <pthread.h>
#include <stddef.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/syscall.h>
#include <sys/wait.h>
#include <unistd.h>

struct message { void *next; unsigned int flags, source, size, reserved; unsigned char body[]; };
_Static_assert(offsetof(struct message, body) == 24, "actual OSAL public envelope");
static struct fcam_model *model;
static const uint64_t instance = UINT64_C(0x9a17013006);
static unsigned int caller = UINT32_C(0x810261c4);
static const char *scenario;
static void *original, *ack, *queued;
static struct message *pool;
static unsigned int ready_value, ready_calls, held, reservations, releases;
static unsigned int inits, states, allocations, sends, original_frees, reply_frees, logs;
static unsigned int original_free_attempts, reply_free_attempts, fail_stage, corrupt_stage;
static unsigned int reuse, reuse_hits, reentrant, block_bridge;
static int corrupt_byte = -1, request_corrupt_byte = -1;
static uint64_t receive_ticket;
static long reservation_tid;
static unsigned char wire[24], actual_init[128], actual_state[128];
static struct fcam_frame_proof before_proof;
static pthread_mutex_t barrier_mutex = PTHREAD_MUTEX_INITIALIZER;
static pthread_cond_t barrier = PTHREAD_COND_INITIALIZER;
static unsigned int bridge_entered, bridge_continue;

static long tid(void) { return syscall(SYS_gettid); }
static uint32_t u32(const unsigned char *p) {
    return p[0] | (uint32_t)p[1] << 8 | (uint32_t)p[2] << 16 | (uint32_t)p[3] << 24;
}
static uint64_t u64(const unsigned char *p) { return u32(p) | (uint64_t)u32(p + 4) << 32; }
static void put32(unsigned char *p, uint32_t v) {
    for (unsigned int i = 0; i < 4; i++) p[i] = (unsigned char)(v >> (8 * i));
}
static void put64(unsigned char *p, uint64_t v) { put32(p, (uint32_t)v); put32(p + 4, (uint32_t)(v >> 32)); }
static uint64_t fnv(const void *pointer, size_t bytes) {
    const unsigned char *p = pointer; uint64_t h = UINT64_C(14695981039346656037);
    for (size_t i = 0; i < bytes; i++) h = (h ^ p[i]) * UINT64_C(1099511628211);
    return h;
}
static struct message *envelope(void *p) { return (struct message *)((unsigned char *)p - offsetof(struct message, body)); }
static struct functional_background_start_snapshot owner(void) {
    struct functional_background_start_snapshot s; functional_background_start_snapshot(&s);
    assert(s.owner_pid == getpid() && s.initialized && s.functional_model);
    assert(!s.source_physical_verified && !s.original_cp_rtos_verified && !s.cp_modules_verified &&
        !s.original_masks_verified && !s.business_published && !s.hardware_ready && !s.image_ready && !s.capture_verified);
    return s;
}
static void *message(unsigned int bytes, unsigned int source) {
    struct message *m = pool;
    if (m) { pool = NULL; reuse_hits++; }
    else { m = malloc(sizeof *m + 64); assert(m); }
    memset(m, 0, sizeof *m + 64); m->source = source; m->size = bytes; return m->body;
}
static void destroy(void *p) { free(envelope(p)); }
static void fixture_release(void *p) {
    if (reuse) { assert(!pool); pool = envelope(p); }
    else destroy(p);
}
static void log_line(const char *tag, const char *text) {
    const struct functional_background_start_snapshot s = owner();
    assert(!strncmp(tag, "FUNCTIONAL_BACKGROUND_START_", 28));
    if (!strcmp(scenario, "probe-callback-fault") && strstr(tag, "_INIT ")) {
        int rc = 999;
        assert(functional_background_start_release_cycle(FUNCTIONAL_BACKGROUND_START_SID, original,
            s.cycle, NULL, NULL, &rc) == 1 && rc == -EPROTO);
    }
    assert(strlen(text) < 2048 && strlen(tag) + strlen(text) + 6 < 4096);
    if (strstr(text, "raw24=")) assert(strstr(text, "capture_verified=0"));
    logs++;
}
static unsigned int size(void *p) { (void)owner(); return envelope(p)->size; }
static unsigned int source(void *p) { (void)owner(); return envelope(p)->source; }
static void set_source(void *p, unsigned int src) {
    (void)owner();
    if (!strcmp(scenario, "set-source-fail")) return;
    envelope(p)->source = src;
    if (!strcmp(scenario, "write-readback-fail")) ((unsigned char *)p)[4] ^= 1;
}
static int reserve(void) {
    const struct functional_background_start_snapshot s = owner();
    assert(s.working && !held && ready_value == 1 && !s.guard_held);
    reservations++;
    if (!strcmp(scenario, "reserve-fail")) return -EBUSY;
    if (!strcmp(scenario, "reserve-positive")) return 3;
    held = 1; reservation_tid = tid();
    if (!strcmp(scenario, "reserve-callback-fault")) {
        int rc = 999;
        assert(functional_background_start_release_cycle(FUNCTIONAL_BACKGROUND_START_SID, original,
            s.cycle, NULL, NULL, &rc) == 1 && rc == -EPROTO);
    }
    return 0;
}
static void release_guard(void) {
    (void)owner(); assert(held && tid() == reservation_tid);
    held = 0; releases++;
}
static int ready(void) {
    (void)owner(); ready_calls++;
    if (!strcmp(scenario, "ready-error")) return -EIO;
    if (!strcmp(scenario, "ready-no-data")) return -ENODATA;
    if (!strcmp(scenario, "ready-invalid")) return 2;
    if (!strcmp(scenario, "ready-regressed") && held) return 0;
    return (int)ready_value;
}
static int real_free(unsigned int destination, void *p) {
    const struct functional_background_start_snapshot s = owner();
    assert(s.model_complete && s.readback_verified && !s.ap_consumed);
    if (p == original) {
        original_free_attempts++;
        assert(destination == FUNCTIONAL_BACKGROUND_START_SID && held && tid() == s.producer_tid &&
            s.leases[0].releasing && !s.leases[0].freed && source(p) == caller && size(p) == 24 &&
            !memcmp(p, wire, sizeof wire) && allocations == original_frees);
        if (!strcmp(scenario, "request-free-fail")) return -EIO;
        if (!strcmp(scenario, "request-free-reentry")) {
            int rc = 999;
            assert(functional_background_start_release_cycle(destination, p, s.cycle, real_free, log_line, &rc) == 1 && rc == -EPROTO);
            assert(original_free_attempts == 1);
        }
        original = NULL; original_frees++;
    } else {
        assert(p == ack && destination == caller && s.reply_received && s.leases[1].releasing &&
            tid() == s.sender_tid && tid() == s.receiver_tid && s.original_request_freed &&
            source(p) == FUNCTIONAL_BACKGROUND_START_SID && size(p) == 12 && !memcmp(p, s.reply_wire, 12));
        reply_free_attempts++;
        if (!strcmp(scenario, "reply-free-fail")) return -EIO;
        if (!strcmp(scenario, "free-reentry")) {
            int rc = 999;
            assert(functional_background_start_release_cycle(caller, p, receive_ticket, real_free, log_line, &rc) == 1);
            assert(rc == -EPROTO && reply_free_attempts == 1);
        }
        ack = queued = NULL; reply_frees++;
    }
    fixture_release(p); return 0;
}
static int allocate(unsigned int destination, void **out, unsigned int bytes, unsigned int option) {
    const struct functional_background_start_snapshot s = owner();
    assert(destination == caller && bytes == 12 && option == 1 && !original && s.original_request_freed &&
        s.model_complete && s.readback_verified && held && !s.ap_consumed && !ack);
    allocations++;
    if (!strcmp(scenario, "allocate-fail")) return -ENOMEM;
    if (!strcmp(scenario, "allocate-null")) return 0;
    if (!strcmp(scenario, "allocate-private-alias")) {
        *out = functional_background_start_test_snapshot_address(); return 0;
    }
    *out = ack = message(12, 0);
    if (!strcmp(scenario, "allocate-with-error")) return -ENOMEM;
    if (!strcmp(scenario, "allocate-length")) envelope(ack)->size = 11;
    return 0;
}
static void receive_and_free(void) {
    const struct functional_background_start_snapshot before = owner();
    assert(ack && !before.ap_consumed);
    uint64_t ticket = 0;
    assert(functional_background_start_observe_receive_cycle(caller, ack, source(ack), size(ack), &ticket) == 1);
    assert(ticket && ticket == owner().cycle); receive_ticket = ticket;
    int rc = 999;
    assert(functional_background_start_release_cycle(caller, ack, ticket, real_free, log_line, &rc) == 1 && !rc);
}
static int send(unsigned int destination, void *p) {
    const struct functional_background_start_snapshot s = owner();
    assert(p == ack && destination == caller && !queued && !original && s.original_request_freed &&
        held && s.leases[1].send_inflight && !s.ap_consumed && !s.reply_queued);
    const unsigned char *b = p;
    assert(size(p) == 12 && source(p) == FUNCTIONAL_BACKGROUND_START_SID &&
        b[0] == 1 && !b[1] && b[2] == 6 && b[3] == 0x30 && !memcmp(b + 4, wire + 4, 4) &&
        u32(b + 8) == 0xf000 && !memcmp(b, s.reply_wire, 12));
    queued = p; sends++;
    if (!strcmp(scenario, "inline") || !strcmp(scenario, "inline-send-fail")) {
        receive_and_free(); assert(!owner().ap_consumed && !owner().transport_complete);
    }
    return !strcmp(scenario, "send-fail") || !strcmp(scenario, "inline-send-fail") ? -EIO : 0;
}
static const struct full_imaging_io io = {allocate, real_free, set_source, send, size, source, log_line};
static const struct native_cp_state_publication_guard guard = {reserve, release_guard, ready};

/* shortcut: HOST_TEST replaces only bridge transport; mailbox/RSP and native all13 are parent integration scope. */
int fcam_bridge_call(const struct fcam_native_origin *origin, uint32_t op, const void *input, size_t input_bytes,
    void *output, size_t capacity, struct fcam_bridge_result *result) {
    const struct functional_background_start_snapshot s = owner();
    assert(original && held && tid() == reservation_tid && s.guard_held && s.working &&
        s.producer_tid == tid() && !input && !input_bytes && capacity == 128 && origin && result &&
        origin->source == caller && origin->destination == FUNCTIONAL_BACKGROUND_START_SID &&
        origin->command == 0x3006 && origin->bytes == 24 && origin->wire_fnv1a64 == fnv(wire, sizeof wire));
    assert(!memcmp(original, wire, sizeof wire) && !memcmp(&s.origin, origin, sizeof *origin));
    if (op == FCAM_OP_INIT) inits++; else { assert(op == FCAM_OP_STATE); states++; }
    if (reentrant) {
        assert(!functional_background_start_progress());
        int rc = 999;
        assert(functional_background_start_dispatch(FUNCTIONAL_BACKGROUND_START_SID, original, &io, &guard, 1, &rc) == 1);
        assert(rc == -EBUSY || rc == -EDEADLK);
    }
    if (block_bridge && op == FCAM_OP_INIT) {
        pthread_mutex_lock(&barrier_mutex); bridge_entered = 1; pthread_cond_broadcast(&barrier);
        while (!bridge_continue) pthread_cond_wait(&barrier, &barrier_mutex);
        pthread_mutex_unlock(&barrier_mutex);
    }
    struct fcam_exec_result r = {0};
    assert(!fcam_model_request(model, op, NULL, 0, output, capacity, &r));
    assert(r.used == 128 && !r.token && !r.total && !r.offset);
    memcpy(op == FCAM_OP_INIT ? actual_init : actual_state, output, 128);
    *result = (struct fcam_bridge_result){r.used, r.used, instance, 0};
    const unsigned int stage = op == FCAM_OP_INIT ? 1u : 2u;
    if (fail_stage == stage) return !strcmp(scenario, "bridge-positive") ? 7 : -EIO;
    if (corrupt_stage == stage) {
        if (corrupt_byte >= 0) ((unsigned char *)output)[corrupt_byte] ^= 1;
        else if (strstr(scenario, "used")) result->used--;
        else if (strstr(scenario, "required")) result->required++;
        else if (strstr(scenario, "nonce")) result->model_instance ^= 1;
        else if (strstr(scenario, "token")) result->result_token = 1;
        else if (strstr(scenario, "overrun")) ((unsigned char *)output)[128] ^= 1;
        else assert(0);
    }
    return 0;
}
static void core_call(unsigned int op, const unsigned char *input, size_t bytes, unsigned char out[128]) {
    struct fcam_exec_result r = {0};
    assert(!fcam_model_request(model, op, input, bytes, out, 128, &r));
    assert(r.used == 128 && !r.token && !r.total && !r.offset);
}
static struct fcam_frame_proof proof(void) {
    struct fcam_frame_proof p; assert(!fcam_model_proof_snapshot(model, &p, sizeof p)); return p;
}
static void prepare(void) {
    assert(!original && !ack && !queued);
    original = message(24, caller);
    for (unsigned int i = 0; i < sizeof wire; i++) wire[i] = (unsigned char)(0xa7 + i);
    wire[0] = 0; wire[2] = 6; wire[3] = 0x30;
    if (!strcmp(scenario, "cookie-zero")) memset(wire + 4, 0, 4);
    if (!strcmp(scenario, "cookie-max")) memset(wire + 4, 0xff, 4);
    memcpy(original, wire, sizeof wire);
}
static void accept(void) {
    int rc = 999;
    assert(functional_background_start_dispatch(FUNCTIONAL_BACKGROUND_START_SID, original, &io, &guard, 1, &rc) == 1 && !rc);
}
static void *progress_thread(void *out) { *(int *)out = functional_background_start_progress(); return NULL; }
static void run_progress_thread(void) {
    int rc = 999; pthread_t worker;
    assert(!pthread_create(&worker, NULL, progress_thread, &rc));
    if (block_bridge) {
        pthread_mutex_lock(&barrier_mutex);
        while (!bridge_entered) pthread_cond_wait(&barrier, &barrier_mutex);
        pthread_mutex_unlock(&barrier_mutex);
        const struct functional_background_start_snapshot before = owner();
        assert(!functional_background_start_progress());
        int busy_rc = 999;
        assert(functional_background_start_dispatch(FUNCTIONAL_BACKGROUND_START_SID, original, &io, &guard, 1, &busy_rc) == 1 && busy_rc == -EBUSY);
        const struct functional_background_start_snapshot after = owner();
        assert(!memcmp(&before, &after, sizeof before));
        pthread_mutex_lock(&barrier_mutex); bridge_continue = 1; pthread_cond_broadcast(&barrier);
        pthread_mutex_unlock(&barrier_mutex);
    }
    assert(!pthread_join(worker, NULL) && rc == 1);
    assert(owner().producer_tid != owner().sender_tid && !held);
}
static void check_model(void) {
    const struct functional_background_start_snapshot s = owner();
    unsigned char current[128]; core_call(FCAM_OP_STATE, NULL, 0, current);
    assert(s.functional_core_initialized && s.model_complete && s.state_copied && s.readback_verified &&
        s.model_instance == instance && !memcmp(current, s.init_state, 128) &&
        !memcmp(current, s.actual_state, 128) && !memcmp(current, s.model_state, 128) &&
        !memcmp(current, s.copied_readback, 128) && s.init_fnv1a64 == fnv(current, 128) &&
        s.init_fnv1a64 == s.state_fnv1a64 && s.state_fnv1a64 == s.cache_fnv1a64 &&
        s.cache_fnv1a64 == s.readback_fnv1a64 && s.init_result.model_instance == instance &&
        s.state_result.model_instance == instance && s.init_result.used == 128 && s.state_result.used == 128);
    assert(s.config_generation == u64(current + 56) && s.rendered == u64(current + 64) &&
        s.consumed == u64(current + 72) && s.frame_generation == u64(current + 112));
    const struct fcam_frame_proof p = proof();
    if (!strcmp(scenario, "preinitialized")) {
        assert(!memcmp(&before_proof, &p, sizeof p) && p.opcode == FCAM_OP_VDF_PATH &&
            p.after.rendered == 2 && p.after.consumed == 1 && p.after.retired == 2);
    } else assert(p.version == FCAM_PROOF_VERSION && p.model_instance == instance && p.owner_pid == (uint64_t)getpid() &&
        p.opcode == FCAM_OP_INIT && p.render_observed && p.retired && !p.consumer_entered &&
        !p.consumer_returned && !p.encoder_consumed && p.after.rendered == p.before.rendered + 1 &&
        p.after.retired == p.before.retired + 1 && p.after.consumed == p.before.consumed &&
        p.final_state == OPTICAL_FRAME_IDLE && !p.render_status && !p.retire_status &&
        p.active_bytes == UINT64_C(640) * 480 * 3 && p.source_fnv1a64);
    assert(s.rendered >= 1 && s.frame_generation >= 1 && !s.jpeg_encoded && !s.video_encoded);
}
static void fault_sticky(unsigned int expect_original, unsigned int expect_reply) {
    const struct functional_background_start_snapshot before = owner();
    assert(before.faults && before.error < 0 && before.pending && !before.working && !before.guard_held &&
        !before.transport_complete && !before.ap_consumed && before.live_leases == expect_original + expect_reply &&
        !!before.leases[0].pointer == expect_original && !!before.leases[1].pointer == expect_reply);
    const unsigned int old_inits = inits, old_states = states, old_allocs = allocations, old_sends = sends;
    const unsigned int old_original = original_free_attempts, old_reply = reply_free_attempts;
    assert(functional_background_start_progress() == before.error);
    if (ack) {
        int rc = 999;
        assert(functional_background_start_release_cycle(caller, ack, before.cycle, real_free, log_line, &rc) == 1 && rc < 0);
    }
    assert(old_inits == inits && old_states == states && old_allocs == allocations && old_sends == sends &&
        old_original == original_free_attempts && old_reply == reply_free_attempts && !held);
    if (original) { destroy(original); original = NULL; }
    if (ack) { destroy(ack); ack = queued = NULL; }
    const struct functional_background_start_snapshot after = owner();
    assert(after.faults && after.pending && !after.ap_consumed && after.live_leases == expect_original + expect_reply);
    printf("fault error=%d pending=1 retained_original=%u retained_reply=%u retries=0 caller_cleanup_explicit=1\n",
        before.error, expect_original, expect_reply);
}
static void *wrong_receive_thread(void *out) {
    uint64_t ticket = 0;
    *(int *)out = functional_background_start_observe_receive_cycle(caller, ack,
        FUNCTIONAL_BACKGROUND_START_SID, 12, &ticket);
    assert(!ticket); return NULL;
}
static void *wrong_free_thread(void *out) {
    int rc = 999;
    assert(functional_background_start_release_cycle(caller, ack, receive_ticket, real_free, log_line, &rc) == 1);
    *(int *)out = rc; return NULL;
}
static void test_fork(void) {
    functional_background_start_test_hold_lock();
    const pid_t child = fork(); assert(child >= 0);
    if (!child) {
        struct functional_background_start_snapshot s; functional_background_start_snapshot(&s);
        assert(s.faults && s.error == -EXDEV && s.pending && !s.ap_consumed);
        assert(functional_background_start_owner_init() == -EXDEV);
        assert(functional_background_start_bind_source_once(caller) == -EXDEV);
        assert(functional_background_start_progress() == -EXDEV);
        int rc = 999; uint64_t ticket = 0;
        assert(functional_background_start_dispatch(FUNCTIONAL_BACKGROUND_START_SID, original, &io, &guard, 1, &rc) == 1 && rc == -EXDEV);
        assert(functional_background_start_observe_receive_cycle(caller, original, 0, 0, &ticket) == -EXDEV);
        rc = 999;
        assert(functional_background_start_release_cycle(caller, original, 1, real_free, log_line, &rc) == 1 && rc == -EXDEV);
        _exit(0);
    }
    int status = 0; assert(waitpid(child, &status, 0) == child && WIFEXITED(status) && !WEXITSTATUS(status));
    functional_background_start_test_drop_lock(); destroy(original); original = NULL;
    assert(!owner().requests && !inits && !allocations && !reservations);
}
static void test_declines(void) {
    const struct functional_background_start_snapshot before = owner(); int rc = 999;
    assert(!functional_background_start_dispatch(FUNCTIONAL_BACKGROUND_START_SID, original, &io, &guard, 0, &rc) && rc == 999);
    assert(!functional_background_start_dispatch(0x90040193, original, &io, &guard, 1, &rc) && rc == 999);
    ((unsigned char *)original)[2] = 7;
    assert(!functional_background_start_dispatch(FUNCTIONAL_BACKGROUND_START_SID, original, &io, &guard, 1, &rc));
    ((unsigned char *)original)[2] = 6;
    ((unsigned char *)original)[0] = 5;
    assert(functional_background_start_dispatch(FUNCTIONAL_BACKGROUND_START_SID, original, &io, &guard, 1, &rc) == 1 && rc < 0);
    ((unsigned char *)original)[0] = 0;
    for (unsigned int i = 4; i <= 25; i++) if (i != 24) {
        envelope(original)->size = i; rc = 999;
        assert(functional_background_start_dispatch(FUNCTIONAL_BACKGROUND_START_SID, original, &io, &guard, 1, &rc) == 1 && rc < 0);
    }
    envelope(original)->size = 24; envelope(original)->source ^= 1;
    assert(functional_background_start_dispatch(FUNCTIONAL_BACKGROUND_START_SID, original, &io, &guard, 1, &rc) == 1 && rc < 0);
    envelope(original)->source = caller;
    struct full_imaging_io bad_io = io; bad_io.send = NULL;
    assert(functional_background_start_dispatch(FUNCTIONAL_BACKGROUND_START_SID, original, &bad_io, &guard, 1, &rc) == 1 && rc < 0);
    const struct functional_background_start_snapshot after = owner();
    assert(!memcmp(&before, &after, sizeof before) && !inits && !allocations && !reservations &&
        !memcmp(original, wire, sizeof wire));
    destroy(original); original = NULL;
}
static void inspect_stale_and_unrelated(void) {
    const struct functional_background_start_snapshot before = owner();
    int rc = 999;
    assert(functional_background_start_release_cycle(caller, ack, before.cycle + 1, real_free, log_line, &rc) == 1 && rc == -ESTALE);
    assert(functional_background_start_release_cycle(caller, ack, 0, real_free, log_line, &rc) == 1 && rc == -ESTALE);
    void *unrelated = message(12, 0x80020002); uint64_t ticket = 0;
    assert(!functional_background_start_observe_receive_cycle(caller, unrelated, source(unrelated), size(unrelated), &ticket) && !ticket);
    rc = 999;
    assert(!functional_background_start_release_cycle(caller, unrelated, 0, real_free, log_line, &rc) && rc == 999);
    destroy(unrelated);
    const struct functional_background_start_snapshot after = owner(); assert(!memcmp(&before, &after, sizeof before));
}
static void retired_address(void *retired, uint64_t old_ticket) {
    uint64_t ticket = 0; int rc = 999;
    /* No dereference of retired storage: the owner must decline solely by its current lease. */
    assert(!functional_background_start_observe_receive_cycle(caller, retired, 0x80020002, 12, &ticket) && !ticket);
    assert(!functional_background_start_release_cycle(caller, retired, 0, real_free, log_line, &rc) && rc == 999);
    assert(functional_background_start_release_cycle(caller, retired, old_ticket, real_free, log_line, &rc) == 1 && rc == -ESTALE);
}
static void completed(void) {
    const struct functional_background_start_snapshot s = owner();
    assert(s.ap_consumed && s.transport_complete && !s.pending && !s.working && !s.guard_held && !s.faults &&
        s.requests == s.completed_cycles && !s.live_leases && !s.reply_retained && !original && !ack && !queued &&
        s.leases[0].freed && s.leases[1].freed && s.leases[1].consumed &&
        s.leases[1].sender_tid == s.leases[1].receiver_tid && s.leases[1].receiver_tid == s.leases[1].free_tid &&
        s.leases[0].free_tid == s.producer_tid && s.sender_tid == tid() &&
        s.leases[0].wire_fnv1a64 == fnv(wire, sizeof wire) && s.leases[1].wire_fnv1a64 == fnv(s.reply_wire, 12));
    printf("complete cycles=%u init_calls=%u state_calls=%u actual_request_frees=%u actual_reply_frees=%u "
        "instance=%016llx config=%llu rendered=%llu consumed=%llu frame=%llu fnv=%016llx source=%08x "
        "producer_separate=%u same_sender_receive_free=1 state128=",
        s.completed_cycles, inits, states, original_frees, reply_frees, (unsigned long long)s.model_instance,
        (unsigned long long)s.config_generation, (unsigned long long)s.rendered, (unsigned long long)s.consumed,
        (unsigned long long)s.frame_generation, (unsigned long long)s.state_fnv1a64, s.bound_source,
        s.producer_tid != s.sender_tid);
    for (size_t i = 0; i < sizeof s.actual_state; i++) printf("%02x", s.actual_state[i]);
    printf(" reply12="); for (size_t i = 0; i < sizeof s.reply_wire; i++) printf("%02x", s.reply_wire[i]); putchar('\n');
}
int main(int argc, char **argv) {
    assert(argc >= 2); scenario = argv[1];
    if (!strcmp(scenario, "dynamic-source")) caller = UINT32_C(0x8102a1b7);
    if (!strcmp(scenario, "address-reuse")) reuse = 1;
    if (!strcmp(scenario, "reentry")) reentrant = 1;
    if (!strcmp(scenario, "parallel-progress")) block_bridge = 1;
    if (!strcmp(scenario, "request-byte")) {
        assert(argc == 3); request_corrupt_byte = atoi(argv[2]); assert(request_corrupt_byte >= 0 && request_corrupt_byte < 24);
    }
    if (!strcmp(scenario, "corrupt-init-byte") || !strcmp(scenario, "corrupt-state-byte")) {
        assert(argc == 3); corrupt_byte = atoi(argv[2]); assert(corrupt_byte >= 0 && corrupt_byte < 128);
        corrupt_stage = !strcmp(scenario, "corrupt-init-byte") ? 1 : 2;
    } else if (!strncmp(scenario, "init-", 5)) corrupt_stage = 1;
    else if (!strncmp(scenario, "state-", 6)) corrupt_stage = 2;
    if (!strcmp(scenario, "bridge-init-fail") || !strcmp(scenario, "bridge-positive")) fail_stage = 1;
    if (!strcmp(scenario, "bridge-state-fail")) fail_stage = 2;
    assert(!functional_background_start_progress());
    assert(functional_background_start_bind_source_once(caller) == -ENODEV);
    assert(!functional_background_start_owner_init());
    assert(functional_background_start_owner_init() == -EALREADY);
    model = fcam_model_create(instance); assert(model);
    if (!strcmp(scenario, "unbound")) {
        prepare(); const struct functional_background_start_snapshot before = owner(); int rc = 999;
        assert(functional_background_start_dispatch(FUNCTIONAL_BACKGROUND_START_SID, original, &io, &guard, 1, &rc) == 1 && rc < 0);
        const struct functional_background_start_snapshot after = owner();
        assert(!memcmp(&before, &after, sizeof before) && !inits && !reservations && !allocations);
        destroy(original); original = NULL; goto done;
    }
    assert(functional_background_start_bind_source_once(0) == -EINVAL);
    assert(functional_background_start_bind_source_once(UINT32_MAX) == -EINVAL);
    assert(functional_background_start_bind_source_once(FUNCTIONAL_BACKGROUND_START_SID) == -EINVAL);
    assert(!functional_background_start_bind_source_once(caller));
    assert(!functional_background_start_bind_source_once(caller));
    assert(functional_background_start_bind_source_once(caller ^ 0x100) == -ESTALE);
    prepare();
    if (!strcmp(scenario, "fork-before-mutex")) { test_fork(); goto done; }
    if (!strcmp(scenario, "declines")) { test_declines(); goto done; }
    if (!strcmp(scenario, "preinitialized")) {
        unsigned char initial[128], config[48] = {0}; core_call(FCAM_OP_INIT, NULL, 0, initial);
        put32(config, 96); put32(config + 4, 64); put32(config + 8, 25); put32(config + 12, 82);
        put32(config + 16, 800); put32(config + 20, 200); put64(config + 24, 2500); put64(config + 32, UINT64_MAX);
        core_call(FCAM_OP_CONFIGURE, config, sizeof config, initial);
        unsigned char path[16] = {1, 5, 5, 0, 2}, path_result[160]; struct fcam_exec_result executed = {0};
        assert(!fcam_model_request(model, FCAM_OP_VDF_PATH, path, sizeof path, path_result, sizeof path_result, &executed));
        assert(executed.used == 160 && !executed.token && !executed.total && !executed.offset);
        before_proof = proof(); ready_value = 1; accept();
        assert(owner().config_generation == 3 && owner().rendered == 2 && owner().consumed == 1 && u32(owner().model_state + 8) == 96);
        const struct fcam_frame_proof after = proof(); assert(!memcmp(&before_proof, &after, sizeof after));
    } else if (!strcmp(scenario, "immediate") || !strcmp(scenario, "inline") || !strcmp(scenario, "inline-send-fail")) {
        ready_value = 1; accept();
    } else {
        accept();
        if (!strcmp(scenario, "ready-error") || !strcmp(scenario, "ready-invalid")) { fault_sticky(1, 0); goto done; }
        const struct functional_background_start_snapshot pending = owner();
        assert(pending.pending && !pending.working && !pending.model_complete && !pending.functional_core_initialized &&
            pending.live_leases == 1 && pending.leases[0].pointer == original && !inits && !states &&
            !allocations && !sends && !original_frees && !reservations && !held);
        assert(!functional_background_start_progress() && !reservations && !inits);
        if (!strcmp(scenario, "ready-no-data")) {
            assert(owner().pending && !owner().faults); destroy(original); original = NULL;
            puts("pending no_mailbox=1 reservations=0 bridge_calls=0 no_ACK=1 host_fixture_cleanup=1"); goto done;
        }
        if (!strcmp(scenario, "busy")) {
            void *other = message(24, caller); memcpy(other, wire, sizeof wire); int rc = 999;
            assert(functional_background_start_dispatch(FUNCTIONAL_BACKGROUND_START_SID, other, &io, &guard, 1, &rc) == 1 && rc == -EBUSY);
            assert(!memcmp(other, wire, sizeof wire)); destroy(other);
        }
        if (!strcmp(scenario, "request-external-free")) {
            int rc = 999;
            assert(functional_background_start_release_cycle(FUNCTIONAL_BACKGROUND_START_SID, original,
                pending.cycle, real_free, log_line, &rc) == 1 && rc == -EPROTO);
            assert(!original_free_attempts && !reservations && !inits);
            fault_sticky(1, 0); goto done;
        }
        if (request_corrupt_byte >= 0) ((unsigned char *)original)[request_corrupt_byte] ^= 1;
        if (!strcmp(scenario, "request-source")) envelope(original)->source ^= 1;
        if (!strcmp(scenario, "request-length")) envelope(original)->size--;
        ready_value = 1;
        if (!strcmp(scenario, "deferred-thread") || block_bridge || reentrant) run_progress_thread();
        else (void)functional_background_start_progress();
    }
    if (owner().faults) {
        const struct functional_background_start_snapshot s = owner();
        if (fail_stage || corrupt_stage || !strncmp(scenario, "reserve-", 8)) assert(!s.model_complete && original && !allocations && !sends);
        if (request_corrupt_byte >= 0 || !strcmp(scenario, "request-source") || !strcmp(scenario, "request-length"))
            assert(!reservations && !inits && !allocations && !sends && !s.model_complete);
        if (!strcmp(scenario, "ready-regressed")) assert(!inits && !states && !allocations && reservations == releases);
        if (!strcmp(scenario, "probe-callback-fault")) assert(inits == 1 && !states && !allocations);
        if (!strcmp(scenario, "reserve-callback-fault")) assert(!inits && !states && !allocations);
        fault_sticky(original != NULL, ack != NULL); goto done;
    }
    check_model();
    if (!strcmp(scenario, "inline")) { completed(); goto done; }
    assert(ack && queued == ack && owner().reply_queued && !owner().ap_consumed && !owner().transport_complete && owner().pending);
    inspect_stale_and_unrelated();
    if (!strcmp(scenario, "no-receive")) {
        assert(!functional_background_start_progress() && !owner().ap_consumed && !reply_free_attempts);
        destroy(ack); ack = queued = NULL; puts("pending queued_not_consumed=1 explicit_fixture_cleanup=1"); goto done;
    }
    if (!strcmp(scenario, "free-before-receive")) {
        int rc = 999;
        assert(functional_background_start_release_cycle(caller, ack, owner().cycle, real_free, log_line, &rc) == 1 && rc == -EPROTO);
        fault_sticky(0, 1); goto done;
    }
    if (!strcmp(scenario, "wrong-receive-tid")) {
        pthread_t worker; int rc = 999;
        assert(!pthread_create(&worker, NULL, wrong_receive_thread, &rc) && !pthread_join(worker, NULL) && rc == -EPROTO);
        fault_sticky(0, 1); goto done;
    }
    if (!strcmp(scenario, "receive-missing-ticket") || !strcmp(scenario, "receive-duplicate")) {
        uint64_t ticket = 0;
        if (!strcmp(scenario, "receive-duplicate"))
            assert(functional_background_start_observe_receive_cycle(caller, ack, source(ack), size(ack), &ticket) == 1);
        assert(functional_background_start_observe_receive_cycle(caller, ack, source(ack), size(ack),
            !strcmp(scenario, "receive-missing-ticket") ? NULL : &ticket) == -EPROTO);
        fault_sticky(0, 1); goto done;
    }
    if (!strncmp(scenario, "receive-", 8)) {
        unsigned int destination = caller, src = FUNCTIONAL_BACKGROUND_START_SID, bytes = 12;
        if (!strcmp(scenario, "receive-destination")) destination ^= 1;
        else if (!strcmp(scenario, "receive-source")) src ^= 1;
        else if (!strcmp(scenario, "receive-length")) bytes--;
        else if (!strcmp(scenario, "receive-wire")) ((unsigned char *)ack)[4] ^= 1;
        else if (!strcmp(scenario, "receive-envelope-source")) envelope(ack)->source ^= 1;
        else if (!strcmp(scenario, "receive-envelope-length")) envelope(ack)->size--;
        else assert(0);
        uint64_t ticket = 0;
        assert(functional_background_start_observe_receive_cycle(destination, ack, src, bytes, &ticket) == -EPROTO && !ticket);
        fault_sticky(0, 1); goto done;
    }
    if (!strcmp(scenario, "wrong-free-tid") || !strncmp(scenario, "free-", 5) || !strcmp(scenario, "reply-free-fail")) {
        receive_ticket = 0;
        assert(functional_background_start_observe_receive_cycle(caller, ack, source(ack), size(ack), &receive_ticket) == 1);
        assert(receive_ticket == owner().cycle);
        int rc = 999;
        if (!strcmp(scenario, "wrong-free-tid")) {
            pthread_t worker; assert(!pthread_create(&worker, NULL, wrong_free_thread, &rc) && !pthread_join(worker, NULL));
        } else {
            if (!strcmp(scenario, "free-source")) envelope(ack)->source ^= 1;
            if (!strcmp(scenario, "free-length")) envelope(ack)->size--;
            if (!strcmp(scenario, "free-wire")) ((unsigned char *)ack)[8] ^= 1;
            assert(functional_background_start_release_cycle(caller, ack, receive_ticket,
                !strcmp(scenario, "free-missing-callback") ? NULL : real_free, log_line, &rc) == 1);
        }
        assert(rc < 0 || !strcmp(scenario, "free-reentry"));
        fault_sticky(0, ack != NULL); goto done;
    }
    void *old_ack = ack; receive_and_free(); completed(); retired_address(old_ack, receive_ticket);
    if (reuse || !strcmp(scenario, "preinitialized") || !strcmp(scenario, "retired-source")) {
        unsigned char previous[128], current[128]; core_call(FCAM_OP_STATE, NULL, 0, previous);
        const struct fcam_frame_proof old_proof = proof(); const uint64_t old_ticket = receive_ticket;
        if (!strcmp(scenario, "retired-source")) {
            caller = UINT32_C(0x8102a1b7);
            assert(!functional_background_start_bind_source_once(caller));
        }
        if (reuse) ready_value = 0;
        prepare();
        if (reuse) retired_address(original, old_ticket);
        accept();
        if (reuse) {
            assert(owner().pending && original == old_ack && owner().cycle == old_ticket + 1);
            const struct functional_background_start_snapshot pending = owner(); int stale = 999;
            assert(functional_background_start_release_cycle(FUNCTIONAL_BACKGROUND_START_SID, original,
                old_ticket, real_free, log_line, &stale) == 1 && stale == -ESTALE);
            const struct functional_background_start_snapshot still_pending = owner();
            assert(!memcmp(&pending, &still_pending, sizeof pending));
            ready_value = 1; assert(functional_background_start_progress() == 1);
        }
        assert(owner().reply_queued && !owner().ap_consumed && owner().cycle == old_ticket + 1);
        if (reuse) assert(ack == old_ack && reuse_hits >= 3);
        const struct functional_background_start_snapshot before = owner(); int rc = 999;
        assert(functional_background_start_release_cycle(caller, ack, old_ticket, real_free, log_line, &rc) == 1 && rc == -ESTALE);
        const struct functional_background_start_snapshot after = owner(); assert(!memcmp(&before, &after, sizeof before));
        core_call(FCAM_OP_STATE, NULL, 0, current); assert(!memcmp(previous, current, 128));
        const struct fcam_frame_proof new_proof = proof(); assert(!memcmp(&old_proof, &new_proof, sizeof old_proof));
        receive_and_free(); completed(); puts("repeat INIT_preserved_all_state=1 frame_counts_preserved=1 stale_ticket_rejected=1");
    }
done:
    assert(!original && !ack && !queued && !held && reservations == releases +
        (unsigned int)(!strcmp(scenario, "reserve-fail") || !strcmp(scenario, "reserve-positive")));
    free(pool); fcam_model_destroy(model);
    printf("HOSTTEST scenario=%s init_calls=%u state_calls=%u allocations=%u sends=%u original_free_calls=%u reply_free_calls=%u "
        "logs=%u reuse_hits=%u native_predecessors_verified=false physical_asic_verified=false original_ap_verified=false capture_verified=false\n",
        scenario, inits, states, allocations, sends, original_free_attempts, reply_free_attempts, logs, reuse_hits);
    return 0;
}
