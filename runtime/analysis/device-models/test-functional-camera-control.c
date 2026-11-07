/* SPDX-License-Identifier: MIT */
#ifdef FCAM_OU_CRANK_CONTROL_TEST
#define _GNU_SOURCE
#ifndef HOST_TEST
#error Component fixture only
#endif
#include "functional-camera-control.c"
#include "cp-ee-controls-diagnostic.h"
#include "../../../report/functional-camera-core/functional-camera-core.h"
#include "../functional-still-format-abi.h"
#include <assert.h>
#include <stdlib.h>
#include <sys/wait.h>
#include <libavutil/log.h>

/* Real Native predecessors/Core; transport/guard fixtures never claim AP proof. */
struct ou_packet { unsigned int source, bytes, capacity, live; unsigned char body[]; };
static struct ou_packet *ou_packets[128];
static struct fcam_model *ou_model;
static const char *ou_case;
static void *ou_active, *ou_ack, *ou_notice;
static unsigned int ou_testing, ou_held, ou_states, ou_models, ou_frees, ou_reads, ou_ready_calls, ou_core_commits;
static unsigned int ou_drift, ou_reentered, ou_fail_free;
static uint64_t ou_ticket;
static struct native_functional_camera_ou_crank_context ou_context;
static struct native_cp_ee_controls_diagnostic_snapshot ou_strict;
static const struct full_imaging_io ou_io;
static const struct native_cp_state_publication_guard ou_guard;
static const uint64_t ou_instance = UINT64_C(0x40722390030001);
static int ou_is(const char *s) { return !strcmp(ou_case, s); }
static int ou_index(const char *prefix) {
    size_t n = strlen(prefix); return !strncmp(ou_case, prefix, n) ? (int)strtoul(ou_case+n, NULL, 10) : -1;
}
static struct native_functional_camera_ou_crank_snapshot ou_view(void) {
    struct native_functional_camera_ou_crank_snapshot s; native_functional_camera_ou_crank_snapshot(&s); return s;
}
static struct ou_packet *ou_packet(void *p) {
    for (unsigned int i = 0; i < 128; i++) if (ou_packets[i] && ou_packets[i]->body == p) return ou_packets[i];
    assert(0); return NULL;
}
static void *ou_message(unsigned int bytes, unsigned int source) {
    struct ou_packet *p = calloc(1, sizeof *p+bytes+32); assert(p);
    p->source = source; p->bytes = bytes; p->capacity = bytes+32; p->live = 1;
    for (unsigned int i = 0; i < 128; i++) if (!ou_packets[i]) { ou_packets[i] = p; return p->body; }
    assert(0); return NULL;
}
static void *ou_request(unsigned int command, unsigned int bytes, uint32_t cookie) {
    unsigned char *p = ou_message(bytes, FUNCTIONAL_CAMERA_CONTROL_AP);
    p[0] = 5; put16(p+2, command); put32(p+4, cookie); return p;
}
static void ou_drop(void *p) { struct ou_packet *q = ou_packet(p); assert(q->live); q->live = 0; }
static void ou_reenter(void) {
    if (ou_reentered) return;
    ou_reentered = 1; void *p = ou_request(0x4072, 12, 7); int rc = 123;
    unsigned int states = ou_states, models = ou_models;
    assert(native_functional_camera_ou_crank_dispatch(FUNCTIONAL_CAMERA_CONTROL_SID, p, &ou_io, &ou_guard, &ou_context, 1, &rc) == 1 && rc == -EBUSY);
    assert(ou_states == states && ou_models == models); ou_drop(p);
}
static unsigned int ou_size(void *p) {
    (void)ou_view();
    if (ou_testing) { ou_reads++; if (ou_is("reentrant-metadata")) ou_reenter(); }
    struct ou_packet *q = ou_packet(p); assert(q->live); return q->bytes;
}
static unsigned int ou_source(void *p) {
    (void)ou_view(); if (ou_testing) ou_reads++;
    struct ou_packet *q = ou_packet(p); assert(q->live); return q->source;
}
static int ou_allocate(unsigned int destination, void **out, unsigned int bytes, unsigned int count) {
    (void)ou_view(); assert(!ou_testing); assert(destination == FUNCTIONAL_CAMERA_CONTROL_AP && count == 1);
    *out = ou_message(bytes, 0); return 0;
}
static void ou_set_source(void *p, unsigned int source) { (void)ou_view(); assert(!ou_testing); ou_packet(p)->source = source; }
static int ou_send(unsigned int destination, void *p) {
    (void)ou_view(); assert(!ou_testing); assert(destination == FUNCTIONAL_CAMERA_CONTROL_AP);
    if (ou_size(p) == CP_STATE_SNAPSHOT_BYTES) ou_notice = p; else { assert(!ou_ack); ou_ack = p; } return 0;
}
static void ou_log(const char *tag, const char *text) {
    struct native_functional_camera_ou_crank_snapshot s = ou_view();
    if (strncmp(tag, "FUNCTIONAL_CP_OU_CRANK_CONTROL_", sizeof "FUNCTIONAL_CP_OU_CRANK_CONTROL_"-1)) return;
    assert(strlen(text) < 8191 && strstr(text, "capture_verified=0")); printf("%s%s\n", tag, text);
    if (strstr(text, "event=VERIFIED ")) {
        assert(s.verified && s.owned && s.retained_request == ou_active); ou_ticket = s.transaction;
        if (ou_is("post-verified-wire")) ((unsigned char *)ou_active)[1] ^= 1;
        if (ou_is("reentrant-early-free")) {
            int rc = 123;
            assert(native_functional_camera_ou_crank_release(FUNCTIONAL_CAMERA_CONTROL_SID, ou_active, ou_io.release, NULL, &rc, ou_ticket) == 1 && rc == -EBUSY);
        }
    }
    if (ou_is("reentrant-logger") && strstr(text, "event=BEGIN ")) ou_reenter();
}
static int ou_real_free(unsigned int destination, void *p) {
    const struct native_functional_camera_ou_crank_snapshot s = ou_view();
    if (ou_testing) {
        assert(destination == FUNCTIONAL_CAMERA_CONTROL_SID && p == ou_active && s.verified && s.owned && s.releasing && s.retained_request == p);
        assert(s.transaction == ou_ticket); /* Main captures this same ticket before actual free. */
        if (ou_is("reentrant-free")) {
            int rc = 123;
            assert(native_functional_camera_ou_crank_release(destination, p, ou_real_free, NULL, &rc, ou_ticket) == 1 && rc == -EBUSY);
        }
        if (ou_fail_free) return ou_is("free-positive") ? 7 : -EIO;
        ou_frees++;
    }
    ou_drop(p); return 0;
}
static int ou_reserve(void) {
    (void)ou_view(); assert(!ou_held);
    if (ou_testing && ou_is("guard-fail")) return -EBUSY;
    ou_held = 1;
    if (ou_testing) {
        ou_drift = 1;
        if (ou_is("bank-drift-reserved")) parameter_state.bank_generation++;
        if (ou_is("crank-drift-reserved")) crank_state.reply_freed = 0;
        if (ou_is("movie-drift-reserved")) movie_format_state.movie_generation++;
    }
    return 0;
}
static void ou_unreserve(void) {
    (void)ou_view(); assert(ou_held);
    if (ou_testing && ou_is("guard-release-reentry")) ou_reenter();
    ou_held = 0;
}
static int ou_predecessors(void) {
    (void)ou_view(); assert(ou_held);
    if (!ou_testing) return 1;
    ou_ready_calls++;
    struct native_cp_ee_controls_diagnostic_snapshot strict; native_cp_ee_controls_diagnostic_snapshot(&strict);
    assert(!memcmp(&strict, &ou_strict, sizeof strict));
    assert(strict.leases[1].opcode == 0x4072 && strict.leases[1].attempts == 1 && strict.leases[1].requests == 1 &&
        strict.leases[1].oneway_consumed && strict.leases[1].clean_completion && strict.leases[1].request_freed &&
        !strict.leases[1].reply_freed && !strict.leases[1].ap_consumed);
    if (ou_is("predecessor-fail") || (ou_is("c0-posterror-retained") && ou_ready_calls == 5)) return 0;
    int n = ou_index("predecessor-lost-"); return n < 0 || ou_ready_calls != (unsigned int)n;
}
static const struct full_imaging_io ou_io = {ou_allocate, ou_real_free, ou_set_source, ou_send, ou_size, ou_source, ou_log};
static const struct native_cp_state_publication_guard ou_guard = {ou_reserve, ou_unreserve, ou_predecessors};
/* Linker wrap mutates only a copy of the real 4057 snapshot for negative cases. */
void __real_functional_startup_control_snapshot(struct functional_startup_control_snapshot *);
void __wrap_functional_startup_control_snapshot(struct functional_startup_control_snapshot *s) {
    __real_functional_startup_control_snapshot(s);
    if (!ou_testing) return;
    if (ou_is("startup-live") || (ou_is("startup-live-reserved") && ou_drift)) { s->leases[1].pointer = ou_active; s->leases[1].freed = 0; }
    if (ou_is("startup-unreceived")) s->leases[1].received = 0;
    if (ou_is("startup-request-unfreed")) s->leases[0].freed = 0;
    if (ou_is("startup-foreign-free")) s->leases[1].free_tid++;
    if (ou_is("startup-fault")) s->faults = 1;
    if (ou_is("startup-seal")) s->result_fnv ^= 1;
    if (ou_is("startup-result")) s->model_result[161] ^= 1;
    if (ou_is("startup-config-seal")) s->current_config40_fnv ^= 1;
    if (ou_is("startup-generation")) s->config_generation++;
    if (ou_is("startup-command")) s->command = 0x4014;
}
int fcam_bridge_call(const struct fcam_native_origin *origin, uint32_t opcode, const void *input, size_t input_bytes,
    void *output, size_t capacity, struct fcam_bridge_result *result) {
    (void)ou_view(); assert(ou_held && ou_model && ou_active && origin->source == FUNCTIONAL_CAMERA_CONTROL_AP && origin->destination == FUNCTIONAL_CAMERA_CONTROL_SID);
    assert(origin->wire_fnv1a64 == hash(ou_active, origin->bytes));
    unsigned int state_call = 0;
    if (ou_testing) {
        assert(origin->command == 0x4072 && origin->bytes == 12 && (opcode == FCAM_OP_STATE || opcode == FCAM_OP_CP_OU_CRANK_CONTROL));
        if (opcode == FCAM_OP_STATE) {
            state_call = ++ou_states; assert(!input && !input_bytes && capacity == 128);
            if ((state_call == 1 && ou_is("before-error")) || (state_call == 2 && ou_is("after-error"))) return -EIO;
        } else {
            ou_models++; assert(input_bytes == 12 && capacity == 224 && !memcmp(input, ou_active, 12));
            if (ou_is("model-error")) return -EIO;
            if (ou_is("reentrant-bridge")) ou_reenter();
        }
    }
    struct fcam_frame_proof before, after; assert(!fcam_model_proof_snapshot(ou_model, &before, sizeof before));
    struct fcam_exec_result actual = {0}; int rc = fcam_model_request(ou_model, opcode, input, input_bytes, output, capacity, &actual);
    if (rc) return rc;
    assert(actual.used == capacity && !actual.token && !actual.total && !actual.offset);
    assert(!fcam_model_proof_snapshot(ou_model, &after, sizeof after));
    *result = (struct fcam_bridge_result){actual.used, actual.used, ou_instance, 0};
    if (!ou_testing) return 0;
    assert(!memcmp(&before, &after, sizeof before));
    unsigned char *p = output;
    if (opcode == FCAM_OP_CP_OU_CRANK_CONTROL) {
        ou_core_commits++;
        unsigned char getter[224]; uint64_t generation = u64(p+FCAM_CP_OU_CRANK_R_OU_GENERATION);
        const uint64_t bank = u64(p+FCAM_CP_OU_CRANK_R_BANK_GENERATION), crank = u64(p+FCAM_CP_OU_CRANK_R_CRANK_GENERATION);
        const uint64_t movie = u64(p+FCAM_CP_OU_CRANK_R_MOVIE_GENERATION);
        assert(!fcam_model_cp_ou_crank_snapshot(ou_model, generation, bank, crank, movie, getter, sizeof getter));
        assert(!memcmp(getter, p, sizeof getter));
        assert(fcam_model_cp_ou_crank_snapshot(ou_model, generation, bank, crank, movie+1, getter, sizeof getter) == -ESTALE);
        int i = ou_index("receipt-byte-"); if (i >= 0) { assert(i < 224); p[i] ^= 1; }
        if (ou_is("c0-bad-receipt")) p[220] ^= 1;
        if (ou_is("model-overrun")) p[capacity] ^= 1;
        if (ou_is("result-used")) result->used--;
        if (ou_is("result-required")) result->required++;
        if (ou_is("result-token")) result->result_token = 1;
        if (ou_is("result-instance")) result->model_instance++;
        if (ou_is("model-origin")) ((struct fcam_native_origin *)origin)->wire_fnv1a64 ^= 1;
        if (ou_is("model-input")) ((unsigned char *)input)[1] ^= 1;
        if (ou_is("model-native-drift")) movie_format_state.reply_freed = 0;
        if (ou_is("model-positive")) return 1;
    } else {
        int i = ou_index(state_call == 1 ? "before-byte-" : "after-byte-"); if (i >= 0) { assert(i < 128); p[i] ^= 1; }
        i = state_call == 1 ? ou_index("request-byte-") : -1; if (i >= 0) { assert(i < 12); ((unsigned char *)ou_active)[i] ^= 1; }
        if ((state_call == 1 && ou_is("before-overrun")) || (state_call == 2 && ou_is("after-overrun"))) p[capacity] ^= 1;
        if (state_call == 1 && ou_is("context-mutation")) ou_context.movie_generation++;
        if (state_call == 1 && ou_is("before-generation-overflow")) memset(p+FCAM_S_GENERATION, 0xff, 8);
    }
    return 0;
}
static void ou_control(unsigned int start) {
    unsigned char *p = ou_request(start ? 0x3003 : 0x4073, start ? 24 : 12, 0x80000026); p[0] = start ? 0 : 5;
    if (!start) put32(p+8, 1);
    ou_active = p; int rc = 123;
    assert(native_functional_camera_control_dispatch(FUNCTIONAL_CAMERA_CONTROL_SID, p, &ou_io, &ou_guard, 1, &rc) == 1 && !rc);
    struct native_functional_camera_control_snapshot s; native_functional_camera_control_snapshot(&s);
    const uint64_t cycle = s.lease_cycle_id[start ? START_ACK : MODE_ACK];
    assert(native_functional_camera_control_observe_receive_cycle(FUNCTIONAL_CAMERA_CONTROL_AP, ou_ack, FUNCTIONAL_CAMERA_CONTROL_SID, start ? 16 : 12, cycle) == 1);
    assert(native_functional_camera_control_release_cycle(FUNCTIONAL_CAMERA_CONTROL_AP, ou_ack, ou_real_free, ou_log, &rc, cycle) == 1 && !rc); ou_ack = NULL;
    if (!start) {
        assert(native_functional_camera_control_observe_receive_cycle(FUNCTIONAL_CAMERA_CONTROL_AP, ou_notice, FUNCTIONAL_CAMERA_CONTROL_SID, CP_STATE_SNAPSHOT_BYTES, cycle) == 1);
        assert(native_functional_camera_control_release_cycle(FUNCTIONAL_CAMERA_CONTROL_AP, ou_notice, ou_real_free, ou_log, &rc, cycle) == 1 && !rc); ou_notice = NULL;
    }
}
static void ou_startup(unsigned int command) {
    ou_active = ou_request(command, command == 0x4014 ? 24 : 12, 0x80000060);
    if (command == 0x4014) memcpy((unsigned char *)ou_active+8, fcam_startup_control_mode_body, 16);
    int rc = 123;
    assert(functional_startup_control_dispatch(FUNCTIONAL_CAMERA_CONTROL_SID, ou_active, &ou_io, &ou_guard, 1, &rc) == 1 && !rc);
    struct functional_startup_control_snapshot s; functional_startup_control_snapshot(&s);
    assert(functional_startup_control_observe_receive_cycle(FUNCTIONAL_CAMERA_CONTROL_AP, ou_ack, FUNCTIONAL_CAMERA_CONTROL_SID, 12, s.cycle) == 1);
    assert(functional_startup_control_release_cycle(FUNCTIONAL_CAMERA_CONTROL_AP, ou_ack, ou_real_free, ou_log, &rc, s.cycle) == 1 && !rc);
    functional_startup_control_snapshot(&s); assert(s.ap_consumed && s.model_complete && s.leases[0].freed && s.leases[1].consumed && !s.retained && !s.faults);
    ou_ack = NULL;
}
static void ou_commit_tuple(uint32_t fps) {
    assert(!ou_testing); int rc = 123;
    unsigned char *p = ou_request(0x4063, FCAM_CP_PARAMETER_BANK_BYTES, 0x80000060);
    for (unsigned int i = 0; i < CP_PARAMETER_BATCH_SLOTS; i++) {
        const struct cp_parameter_batch_slot s = cp_parameter_batch_slots[i];
        p[s.offset] = 5; p[s.offset+1] = (unsigned char)i; put16(p+s.offset+2, s.opcode); put32(p+s.offset+4, i);
        for (unsigned int j = 8; j < s.size; j++) p[s.offset+j] = (unsigned char)(i+j);
    }
    put32(p+FCAM_CP_PARAMETER_FPS_AT, fps); ou_active = p;
    assert(native_functional_camera_parameter_dispatch(FUNCTIONAL_CAMERA_CONTROL_SID, p, &ou_io, &ou_guard, 1, &rc) == 1 && !rc);
    ou_active = ou_request(0x409d, 12, 0x80000060);
    assert(native_functional_camera_crank_dispatch(FUNCTIONAL_CAMERA_CONTROL_SID, ou_active, &ou_io, &ou_guard, 1, &rc) == 1 && !rc);
    struct native_functional_camera_crank_snapshot k; native_functional_camera_crank_snapshot(&k);
    const struct native_functional_camera_crank_receive event = {FUNCTIONAL_CAMERA_CONTROL_SID, 12};
    assert(native_functional_camera_crank_release(FUNCTIONAL_CAMERA_CONTROL_AP, ou_ack, NULL, ou_log, &rc, k.transaction, &event) == 1 && !rc);
    assert(native_functional_camera_crank_release(FUNCTIONAL_CAMERA_CONTROL_AP, ou_ack, ou_real_free, ou_log, &rc, k.transaction, NULL) == 1 && !rc); ou_ack = NULL;
    native_functional_camera_crank_snapshot(&k); assert(k.complete);
    const struct native_functional_camera_movie_format_context context = {k.model_instance, k.bank_generation, k.crank_generation};
    p = ou_request(0x4000, 20, 0x80000061); p[8] = 5; p[9] = p[18] = 1; ou_active = p;
    assert(native_functional_camera_movie_format_dispatch(FUNCTIONAL_CAMERA_CONTROL_SID, p, &ou_io, &ou_guard, &context, 1, &rc) == 1 && !rc);
    struct native_functional_camera_movie_format_snapshot m; native_functional_camera_movie_format_snapshot(&m);
    const struct native_functional_camera_movie_format_receive receive = {FUNCTIONAL_CAMERA_CONTROL_SID, 12};
    assert(native_functional_camera_movie_format_release(FUNCTIONAL_CAMERA_CONTROL_AP, ou_ack, NULL, ou_log, &rc, m.transaction, &receive) == 1 && !rc);
    assert(native_functional_camera_movie_format_release(FUNCTIONAL_CAMERA_CONTROL_AP, ou_ack, ou_real_free, ou_log, &rc, m.transaction, NULL) == 1 && !rc); ou_ack = NULL;
    native_functional_camera_movie_format_snapshot(&m); assert(m.complete);
    ou_context = (struct native_functional_camera_ou_crank_context){m.model_instance, m.bank_generation, m.crank_generation, m.movie_generation};
    unsigned char route[16] = {1, 5, 5}, output[192]; struct fcam_exec_result result = {0};
    assert(!fcam_model_request(ou_model, FCAM_OP_VDF_PATH, route, sizeof route, output, 160, &result));
    assert(!fcam_model_request(ou_model, FCAM_OP_STILL_FORMAT, fcam_still_format_initial, 16, output, 176, &result));
    ou_startup(0x4014); ou_startup(0x4057);
}
static void ou_finish(void) {
    assert(!ou_held); fcam_model_destroy(ou_model);
    for (unsigned int i = 0; i < 128; i++) free(ou_packets[i]);
}
static void *ou_foreign_free(void *p) {
    int rc = 123;
    assert(native_functional_camera_ou_crank_release(FUNCTIONAL_CAMERA_CONTROL_SID, p, ou_real_free, ou_log, &rc, ou_ticket) == 1 && rc == -EPERM); return NULL;
}
static int ou_dispatch(void *p, const struct full_imaging_io *io, const struct native_cp_state_publication_guard *guard, int enabled, int *rc) {
    ou_active = p;
    return native_functional_camera_ou_crank_dispatch(FUNCTIONAL_CAMERA_CONTROL_SID, p, io, guard,
        ou_is("missing-context") ? NULL : &ou_context, enabled, rc);
}
static void ou_assert_complete(const unsigned char original[12]) {
    const struct native_functional_camera_ou_crank_snapshot s = ou_view();
    assert(s.complete && s.verified && s.owned && s.model_called && s.model_committed && s.request_freed && !s.faults && !s.guard_fault && !s.error);
    assert(!s.busy && !s.guard_held && !s.retained_request && !s.releasing && !s.free_rc && !s.before_rc && !s.model_rc && !s.after_rc && !s.validation_rc);
    assert(s.sender_tid > 0 && s.sender_tid == s.free_tid && s.transaction == ou_ticket && s.requests == s.commits && s.commits == s.verified_commits && s.commits == s.completions && s.commits == s.released);
    assert(s.model_instance == ou_context.model_instance && s.bank_generation == ou_context.bank_generation && s.crank_generation == ou_context.crank_generation && s.movie_generation == ou_context.movie_generation);
    assert(s.last_bank_generation == s.bank_generation && s.last_crank_generation == s.crank_generation && s.last_movie_generation == s.movie_generation && s.last_ou_generation == s.ou_generation);
    assert(s.before_config_generation == s.startup_config_generation && s.config_generation == s.before_config_generation+1 && s.frame_generation == s.startup_frame_generation && !s.mode && s.fps == u32(s.before_state+FCAM_S_FPS));
    assert(!memcmp(s.request, original, 12) && !memcmp(s.receipt+208, original, 12) && !memcmp(s.receipt+80, s.after_state, 128));
    unsigned char expected[128]; memcpy(expected, s.before_state, sizeof expected);
    const uint64_t generation = s.before_config_generation+1;
    for (unsigned int i = 0; i < 8; i++) expected[FCAM_S_GENERATION+i] = (unsigned char)(generation >> (8*i));
    assert(!memcmp(expected, s.after_state, 128) && s.origin.wire_fnv1a64 == hash(original, 12) && s.receipt_fnv1a64 == hash(s.receipt, 224));
    assert(!ou_crank_validate_receipt(&s, s.ou_generation-1));
    unsigned int reads = ou_reads, frees = ou_frees; int rc = 123;
    assert(native_functional_camera_ou_crank_release(FUNCTIONAL_CAMERA_CONTROL_SID, s.request_pointer, ou_real_free, ou_log, &rc, s.transaction) == 1 && rc == -ESTALE);
    assert(ou_reads == reads && ou_frees == frees);
}
int main(int argc, char **argv) {
    assert(argc == 2); ou_case = argv[1]; av_log_set_level(AV_LOG_ERROR);
    assert(!native_functional_camera_control_owner_init()); assert(!native_functional_camera_parameter_owner_init());
    assert(!native_functional_camera_crank_owner_init()); assert(!native_functional_camera_movie_format_owner_init());
    assert(!functional_startup_control_owner_init()); assert(!native_cp_ee_controls_diagnostic_owner_init());
    assert(!native_functional_camera_ou_crank_owner_init()); assert(native_functional_camera_ou_crank_owner_init() == -EALREADY);
    const struct native_cp_ee_controls_diagnostic_guard strict_guard = {ou_reserve, ou_unreserve, ou_predecessors};
    int rc = 123; void *q = ou_request(0x409d, 12, 0x80000026);
    assert(native_cp_ee_controls_diagnostic_dispatch(FUNCTIONAL_CAMERA_CONTROL_SID, q, &ou_io, &strict_guard, 1, &rc) == 1 && !rc);
    assert(native_cp_ee_controls_diagnostic_release_reply(FUNCTIONAL_CAMERA_CONTROL_AP, ou_ack, ou_real_free, ou_log, &rc) == 1 && !rc); ou_ack = NULL;
    q = ou_request(0x4072, 12, 0x80000027);
    assert(native_cp_ee_controls_diagnostic_dispatch(FUNCTIONAL_CAMERA_CONTROL_SID, q, &ou_io, &strict_guard, 1, &rc) == 1 && !rc && !ou_ack);
    native_cp_ee_controls_diagnostic_snapshot(&ou_strict); assert(ou_strict.leases[1].oneway_consumed);
    ou_model = fcam_model_create(ou_instance); assert(ou_model); ou_control(1); ou_control(0);
    if (!ou_is("cold")) ou_commit_tuple(30);
    unsigned char *p = ou_request(0x4072, 12, ou_is("cookie-zero") ? 0 : ou_is("cookie-max") ? UINT32_MAX : 0x80000061);
    if (ou_is("opaque-byte1")) p[1] = 0xa5;
    unsigned char original[12]; memcpy(original, p, 12);
    struct full_imaging_io io = ou_io; const struct native_cp_state_publication_guard *guard = &ou_guard;
    if (ou_is("oneway-only-io")) { io.allocate = NULL; io.set_source = NULL; io.send = NULL; }
    if (ou_is("missing-source")) io.source = NULL;
    if (ou_is("missing-size")) io.size = NULL;
    if (ou_is("missing-release")) io.release = NULL;
    if (ou_is("missing-record")) io.record = NULL;
    if (ou_is("missing-guard")) guard = NULL;
    if (ou_is("wrong-source")) ou_packet(p)->source++;
    if (ou_is("short")) ou_packet(p)->bytes--;
    if (ou_is("long")) ou_packet(p)->bytes++;
    if (ou_is("wrong-type")) p[0] = 0;
    if (ou_is("unrelated")) p[2]++;
    int body = ou_index("body-byte-"); if (body >= 0) { assert(body >= 8 && body < 12); p[body] = 1; }
    if (ou_is("context-instance")) ou_context.model_instance++;
    if (ou_is("context-bank")) ou_context.bank_generation++;
    if (ou_is("context-crank")) ou_context.crank_generation++;
    if (ou_is("context-movie")) ou_context.movie_generation++;
    if (ou_is("bank-unfreed")) parameter_state.request_freed = 0;
    if (ou_is("bank-seal")) parameter_state.receipt[200] ^= 1;
    if (ou_is("crank-unreceived")) crank_state.reply_received = 0;
    if (ou_is("crank-unfreed")) crank_state.reply_freed = 0;
    if (ou_is("crank-foreign-free")) crank_state.reply_free_tid++;
    if (ou_is("crank-seal")) crank_state.receipt_fnv1a64 ^= 1;
    if (ou_is("movie-unreceived")) movie_format_state.reply_received = 0;
    if (ou_is("movie-unfreed")) movie_format_state.reply_freed = 0;
    if (ou_is("movie-foreign-free")) movie_format_state.reply_free_tid++;
    if (ou_is("movie-seal")) movie_format_state.receipt_fnv1a64 ^= 1;
    if (ou_is("movie-lineage")) movie_format_state.crank_transaction++;
    if (ou_is("current-mode-live")) state.mode_complete = 0;
    if (ou_is("transaction-overflow")) ou_crank_state.transaction = UINT64_MAX;
    if (ou_is("counter-overflow")) ou_crank_state.released = UINT64_MAX;
    if (ou_is("ou-generation-overflow")) ou_crank_state.last_ou_generation = UINT64_MAX;
    if (ou_is("stale-live-config")) {
        unsigned char live[128], config[48] = {0}; struct fcam_exec_result result = {0};
        assert(!fcam_model_request(ou_model, FCAM_OP_STATE, NULL, 0, live, sizeof live, &result)); memcpy(config, live+8, 40); put32(config+12, 73);
        assert(!fcam_model_request(ou_model, FCAM_OP_CONFIGURE, config, sizeof config, live, sizeof live, &result));
    }
    struct ou_crank_predecessors old; ou_crank_read_predecessors(&old);
    const struct native_functional_camera_ou_crank_context operation = ou_context;
    ou_testing = 1; ou_fail_free = ou_is("free-fail") || ou_is("free-positive") || ou_is("foreign-free");
    if (ou_is("fork-held-lock")) {
        pthread_mutex_lock(&mutex); pthread_mutex_lock(&parameter_mutex); pthread_mutex_lock(&crank_mutex); pthread_mutex_lock(&movie_format_mutex);
        functional_startup_control_test_hold_lock(); pthread_mutex_lock(&ou_crank_mutex);
        pid_t child = fork(); assert(child >= 0);
        if (!child) {
            assert(native_functional_camera_ou_crank_owner_init() == -EXDEV);
            assert(ou_dispatch(p, &io, guard, 1, &rc) == 1 && rc == -EXDEV);
            assert(native_functional_camera_ou_crank_release(FUNCTIONAL_CAMERA_CONTROL_SID, p, ou_real_free, NULL, &rc, 1) == 1 && rc == -EXDEV);
            assert(ou_view().faults); _exit(0);
        }
        pthread_mutex_unlock(&ou_crank_mutex); functional_startup_control_test_drop_lock(); pthread_mutex_unlock(&movie_format_mutex);
        pthread_mutex_unlock(&crank_mutex); pthread_mutex_unlock(&parameter_mutex); pthread_mutex_unlock(&mutex);
        int status; assert(waitpid(child, &status, 0) == child && WIFEXITED(status) && !WEXITSTATUS(status)); ou_finish(); return 0;
    }
    if (ou_index("alias-") >= 0) {
        void *aliases[] = {&state, &parameter_state, &crank_state, &movie_format_state, &ou_crank_state};
        int i = ou_index("alias-"); assert(i >= 0 && i < 5); unsigned int reads = ou_reads;
        assert(!ou_dispatch(aliases[i], &io, guard, 1, &rc) && ou_reads == reads); ou_finish(); return 0;
    }
    rc = 123;
    int handled = ou_is("wrong-destination") ? native_functional_camera_ou_crank_dispatch(FUNCTIONAL_CAMERA_CONTROL_SID+1, p, &io, guard, &ou_context, 1, &rc) :
        ou_dispatch(p, &io, guard, !ou_is("disabled"), &rc);
    if (ou_is("context-mutation")) { assert(ou_context.movie_generation == operation.movie_generation+1); ou_context = operation; }
    struct native_functional_camera_ou_crank_snapshot s = ou_view(); assert(!s.busy && !s.guard_held && !ou_held);
    const int must_own = ou_is("success") || ou_is("oneway-only-io") || ou_is("opaque-byte1") || ou_is("cookie-zero") || ou_is("cookie-max") ||
        ou_is("context-mutation") || ou_is("duplicate-tuple") || ou_is("repeat-new-tuple") || ou_is("completed-reuse") ||
        ou_is("post-verified-wire") || ou_is("free-fail") || ou_is("free-positive") || ou_is("foreign-free") ||
        ou_is("reentrant-metadata") || ou_is("reentrant-logger") || ou_is("reentrant-bridge") || ou_is("reentrant-free") ||
        ou_is("reentrant-early-free") || ou_is("guard-release-reentry") || ou_is("c0-posterror-retained");
    if (must_own) assert(handled == 1 && !rc && s.owned && s.verified && s.model_committed);
    else if (handled) assert(rc < 0 && !s.owned);
    struct native_cp_ee_controls_diagnostic_snapshot strict; native_cp_ee_controls_diagnostic_snapshot(&strict); assert(!memcmp(&strict, &ou_strict, sizeof strict));
    if (!handled) {
        assert(ou_is("cold") || ou_is("disabled") || ou_is("wrong-type") || ou_is("wrong-destination") || ou_is("unrelated") || ou_is("missing-size"));
        assert(rc == 123 && !ou_states && !ou_models && !ou_frees); ou_finish(); return 0;
    }
    if (!s.owned) {
        assert(rc < 0 && !s.retained_request && !s.request_freed && !ou_frees && ou_packet(p)->live);
        if (ou_is("bank-drift-reserved") || ou_is("crank-drift-reserved") || ou_is("movie-drift-reserved") || ou_is("startup-live-reserved"))
            assert(!ou_states && !ou_models && ou_ready_calls == 1);
        if (s.model_called) {
            assert(s.faults && s.model_committed == (s.model_rc == 0));
            unsigned int models = ou_models, states = ou_states;
            q = ou_request(0x4072, 12, 1); int retry = 123; assert(ou_dispatch(q, &ou_io, &ou_guard, 1, &retry) == 1 && retry < 0);
            assert(ou_models == models && ou_states == states); ou_drop(q);
        }
        if (ou_core_commits && !ou_is("model-positive")) assert(s.model_rc == 0 && s.model_committed && s.commits == 1 && s.validation_rc < 0);
        ou_finish(); return 0;
    }
    assert(!rc && s.verified && s.model_committed && ou_models == 1 && ou_core_commits == 1 && ou_states == 2);
    if (s.faults) {
        assert(s.retained_request == p && !s.request_freed && !s.complete && !ou_frees);
        if (ou_is("c0-posterror-retained")) assert(s.model_rc == 0 && s.model_committed && s.commits == 1 && s.validation_rc < 0 && s.guard_fault);
        unsigned int reads = ou_reads; int freed = 123;
        assert(native_functional_camera_ou_crank_release(FUNCTIONAL_CAMERA_CONTROL_SID, p, ou_real_free, ou_log, &freed, ou_ticket+1) == 1 && freed == -ESTALE);
        assert(native_functional_camera_ou_crank_release(FUNCTIONAL_CAMERA_CONTROL_SID, p, ou_real_free, ou_log, &freed, 0) == 1 && freed == -ESTALE && ou_reads == reads);
        if (ou_is("foreign-free")) { pthread_t t; assert(!pthread_create(&t, NULL, ou_foreign_free, p)); assert(!pthread_join(t, NULL)); }
        ou_fail_free = 0; memcpy(p, original, 12);
        assert(native_functional_camera_ou_crank_release(FUNCTIONAL_CAMERA_CONTROL_SID, p, ou_real_free, ou_log, &freed, ou_ticket) == 1 && !freed);
        assert(ou_view().faults && ou_view().request_freed && !ou_view().retained_request && !ou_view().complete);
        reads = ou_reads;
        assert(native_functional_camera_ou_crank_release(FUNCTIONAL_CAMERA_CONTROL_SID, p, ou_real_free, ou_log, &freed, ou_ticket) == 1 && freed == -ESTALE && ou_reads == reads);
        ou_finish(); return 0;
    }
    ou_assert_complete(original);
    struct ou_crank_predecessors after; ou_crank_read_predecessors(&after); assert(!memcmp(&old, &after, sizeof old));
    if (ou_is("duplicate-tuple") || ou_is("repeat-new-tuple") || ou_is("completed-reuse")) {
        unsigned int states = ou_states, models = ou_models; uint64_t old_ticket = ou_ticket; void *old_pointer = s.request_pointer;
        q = ou_request(0x4072, 12, 0x80000061); int retry = 123;
        assert(ou_dispatch(q, &ou_io, &ou_guard, 1, &retry) == 1 && retry == -ESTALE && ou_states == states && ou_models == models); ou_drop(q);
        if (ou_is("completed-reuse")) {
            struct ou_packet *packet = ou_packet(old_pointer); assert(!packet->live && packet->capacity >= 12);
            packet->live = 1; packet->source = FUNCTIONAL_CAMERA_CONTROL_AP; packet->bytes = 12; memset(packet->body, 0x81, 12);
            unsigned int reads = ou_reads; int freed = 123;
            assert(native_functional_camera_ou_crank_release(FUNCTIONAL_CAMERA_CONTROL_SID, old_pointer, ou_real_free, ou_log, &freed, old_ticket) == 1 && freed == -ESTALE && ou_reads == reads);
            assert(!native_functional_camera_ou_crank_release(FUNCTIONAL_CAMERA_CONTROL_SID, old_pointer, ou_real_free, ou_log, &freed, 0)); ou_drop(old_pointer);
        }
        if (ou_is("repeat-new-tuple")) {
            ou_testing = 0; ou_commit_tuple(60); ou_testing = 1;
            q = ou_request(0x4072, 12, 0x80000061); memcpy(original, q, 12);
            assert(ou_dispatch(q, &ou_io, &ou_guard, 1, &retry) == 1 && !retry); ou_assert_complete(original);
            unsigned int reads = ou_reads; int freed = 123;
            assert(native_functional_camera_ou_crank_release(FUNCTIONAL_CAMERA_CONTROL_SID, old_pointer, ou_real_free, ou_log, &freed, old_ticket) == 1 && freed == -ESTALE && ou_reads == reads);
            assert(ou_view().ou_generation == 2 && ou_view().completions == 2 && ou_view().fps == 60);
        }
    }
    ou_finish(); puts("PASS OU real-Core component; original AP/physical/capture unverified"); return 0;
}
#else
#define _GNU_SOURCE
#include "functional-startup-control.h"
/* Old standalone fixtures do not run OU or link the separate startup owner. */
void functional_startup_control_snapshot(struct functional_startup_control_snapshot *out) {
    *out = (struct functional_startup_control_snapshot){0};
}
/* SPDX-License-Identifier: MIT */
#ifdef FCAM_MOVIE_FORMAT_TEST
#define _GNU_SOURCE
#ifndef HOST_TEST
#error Component fixture only
#endif
#include "functional-camera-control.c"
#include "cp-ee-controls-diagnostic.h"
#include "cp-movie-format-diagnostic.h"
#include "../../../report/functional-camera-core/functional-camera-core.h"
#include <assert.h>
#include <stdlib.h>
#include <sys/wait.h>
#include <libavutil/log.h>

/* Real Core, fixture bridge/OSAL/guard. Kept allocations detect duplicate real
 * frees deterministically and allow deliberate successful allocation reuse. */
struct mf_packet { unsigned int source, bytes, capacity, live; unsigned char body[]; };
static struct mf_packet *mf_packets[96];
static struct fcam_model *mf_model;
static const char *mf_case;
static void *mf_active, *mf_ack, *mf_notice, *mf_reply, *mf_saved_bank_pointer;
static uint64_t mf_ticket, mf_request_ticket;
static unsigned int mf_states, mf_models, mf_allocations, mf_sends, mf_frees, mf_ready_calls;
static int mf_held, mf_testing, mf_strict_setup, mf_reentered, mf_fail_request, mf_fail_reply;
static struct native_cp_ee_controls_diagnostic_snapshot mf_strict_saved;
static struct native_cp_movie_format_diagnostic_snapshot mf_strict_movie;
static struct native_functional_camera_movie_format_context mf_context;
static const struct full_imaging_io mf_io;
static const struct native_cp_state_publication_guard mf_guard;
static const uint64_t mf_instance = UINT64_C(0x123456789abcde);
static int mf_is(const char *s) { return !strcmp(mf_case, s); }
static int mf_index(const char *prefix) {
    size_t n = strlen(prefix); return !strncmp(mf_case, prefix, n) ? (int)strtoul(mf_case+n, NULL, 10) : -1;
}
static struct mf_packet *mf_packet(void *p) {
    for (unsigned int i = 0; i < 96; i++) if (mf_packets[i] && mf_packets[i]->body == p) return mf_packets[i];
    assert(0); return NULL;
}
static void *mf_message(unsigned int bytes, unsigned int source) {
    struct mf_packet *p = calloc(1, sizeof *p + bytes + 16); assert(p);
    p->source = source; p->bytes = bytes; p->capacity = bytes + 16; p->live = 1;
    for (unsigned int i = 0; i < 96; i++) if (!mf_packets[i]) { mf_packets[i] = p; return p->body; }
    assert(0); return NULL;
}
static void *mf_reuse(void *pointer, unsigned int bytes, unsigned int source) {
    struct mf_packet *p = mf_packet(pointer); assert(!p->live && p->capacity >= bytes);
    p->live = 1; p->source = source; p->bytes = bytes; memset(p->body, 0, bytes); return p->body;
}
static void mf_drop(void *p) { struct mf_packet *s = mf_packet(p); assert(s->live); s->live = 0; }
static void *mf_request(uint32_t cookie) {
    unsigned char *p = mf_message(20, FUNCTIONAL_CAMERA_CONTROL_AP);
    p[0] = 5; put16(p+2, 0x4000); put32(p+4, cookie); p[8] = 5; p[9] = p[18] = 1; return p;
}
static void *mf_crank_request(void) {
    unsigned char *p = mf_message(12, FUNCTIONAL_CAMERA_CONTROL_AP);
    p[0] = 5; put16(p+2, 0x409d); put32(p+4, 0x80000060); return p;
}
static void *mf_bank_request(uint32_t cookie, uint32_t fps) {
    unsigned char *p = mf_message(FCAM_CP_PARAMETER_BANK_BYTES, FUNCTIONAL_CAMERA_CONTROL_AP);
    p[0] = 5; put16(p+2, 0x4063); put32(p+4, cookie);
    for (unsigned int i = 0; i < CP_PARAMETER_BATCH_SLOTS; i++) {
        struct cp_parameter_batch_slot s = cp_parameter_batch_slots[i];
        p[s.offset] = 5; p[s.offset+1] = (unsigned char)i; put16(p+s.offset+2, s.opcode); put32(p+s.offset+4, i);
        for (unsigned int j = 8; j < s.size; j++) p[s.offset+j] = (unsigned char)(i+j);
    }
    put32(p+FCAM_CP_PARAMETER_FPS_AT, fps); return p;
}
static struct native_functional_camera_movie_format_snapshot mf_view(void) {
    struct native_functional_camera_movie_format_snapshot s; native_functional_camera_movie_format_snapshot(&s); return s;
}
static void mf_reenter(void) {
    if (mf_reentered) return;
    mf_reentered = 1; void *p = mf_request(7); int rc = 123;
    unsigned int states = mf_states, models = mf_models;
    assert(native_functional_camera_movie_format_dispatch(FUNCTIONAL_CAMERA_CONTROL_SID, p, &mf_io, &mf_guard, &mf_context, 1, &rc) == 1 && rc < 0);
    assert(mf_states == states && mf_models == models); mf_drop(p);
}
static unsigned int mf_size(void *p) {
    (void)mf_view();
    if (mf_testing && mf_is("reentrant-metadata")) mf_reenter();
    struct mf_packet *s = mf_packet(p); assert(s->live); return s->bytes;
}
static unsigned int mf_source(void *p) { struct mf_packet *s = mf_packet(p); assert(s->live); return s->source; }
static void mf_set_source(void *p, unsigned int source) {
    (void)mf_view(); mf_packet(p)->source = source + (mf_testing && mf_is("reply-source-set"));
}
static void mf_log(const char *tag, const char *text) {
    (void)mf_view();
    if (strncmp(tag, "FUNCTIONAL_CP_MOVIE_FORMAT_", sizeof "FUNCTIONAL_CP_MOVIE_FORMAT_"-1)) return;
    assert(strlen(text) < 4607 && strstr(text, "capture_verified=0")); printf("%s%s\n", tag, text);
    if (strstr(text, "event=VERIFIED ")) mf_ticket = mf_request_ticket = mf_view().transaction;
    if (strstr(text, "event=SENT ") && mf_active) {
        if (mf_is("request-free-wire")) ((unsigned char *)mf_active)[19] ^= 1;
        if (mf_is("request-free-source")) mf_packet(mf_active)->source++;
        if (mf_is("request-free-size")) mf_packet(mf_active)->bytes--;
    }
}
/* Captured send ticket shared unchanged across the actual receive thread. */
struct mf_transport_event { void *pointer; uint64_t transaction; };
static void *mf_transport_receive(void *value) {
    const struct mf_transport_event *ticket = value;
    const struct native_functional_camera_movie_format_receive receive = {FUNCTIONAL_CAMERA_CONTROL_SID, 12};
    int rc = 123;
    assert(native_functional_camera_movie_format_release(FUNCTIONAL_CAMERA_CONTROL_AP, ticket->pointer, NULL, mf_log, &rc,
        ticket->transaction, &receive) == 1 && !rc);
    struct native_functional_camera_movie_format_snapshot s = mf_view();
    assert(s.reply_received && s.receiver_tid == tid() && s.receiver_tid > 0 && s.receiver_tid != s.sender_tid && !s.faults);
    return NULL;
}
static void mf_transport_deliver(void *pointer, uint64_t transaction) {
    struct mf_transport_event ticket = {pointer, transaction}; pthread_t thread;
    assert(!pthread_create(&thread, NULL, mf_transport_receive, &ticket)); assert(!pthread_join(thread, NULL));
}
static int mf_release(unsigned int destination, void *p) {
    assert(destination == FUNCTIONAL_CAMERA_CONTROL_AP || destination == FUNCTIONAL_CAMERA_CONTROL_SID);
    (void)mf_view();
    if (mf_testing && p == mf_active && mf_is("transport-during-request-free")) {
        assert(mf_view().request_releasing && mf_reply); mf_transport_deliver(mf_reply, mf_ticket);
    }
    if (mf_testing && mf_is("reentrant-free")) {
        int rc = 123;
        assert(native_functional_camera_movie_format_release(destination, p, mf_release, NULL, &rc, mf_ticket, NULL) == 1 && rc == -EBUSY);
    }
    if (mf_testing && ((p == mf_active && mf_fail_request) || (p == mf_reply && mf_fail_reply))) return -EIO;
    mf_frees++; mf_drop(p); return 0;
}
static int mf_allocate(unsigned int destination, void **out, unsigned int bytes, unsigned int count) {
    assert(destination == FUNCTIONAL_CAMERA_CONTROL_AP && count == 1); (void)mf_view();
    if (mf_testing) {
        mf_allocations++; assert(bytes == 12 && mf_view().verified && mf_view().model_committed);
        if (mf_is("reentrant-request-early")) {
            int rc = 123; unsigned int frees = mf_frees;
            assert(native_functional_camera_movie_format_release(FUNCTIONAL_CAMERA_CONTROL_SID, mf_active, mf_release, NULL,
                &rc, mf_request_ticket, NULL) == 1 && rc == -EBUSY && mf_frees == frees && !mf_view().faults);
        }
        if (mf_is("allocation-fail")) return -ENOMEM;
        if (mf_is("allocation-alias")) { *out = mf_active; return 0; }
        if (mf_is("allocation-alias-offset")) { *out = (unsigned char *)mf_active+4; return 0; }
        if (mf_is("allocation-alias-tail")) { *out = (unsigned char *)mf_active+16; return 0; }
        if (mf_is("allocation-alias-owner")) { *out = &movie_format_state; return 0; }
        if (mf_is("allocation-alias-crank")) { *out = &crank_state; return 0; }
        if (mf_is("allocation-param-reuse")) {
            *out = mf_reuse(mf_saved_bank_pointer, 12, 0);
            int rc = 123;
            assert(!native_functional_camera_parameter_release(FUNCTIONAL_CAMERA_CONTROL_SID, *out, mf_release, NULL, &rc, 0) && rc == 123);
            return 0;
        }
    }
    *out = mf_message(bytes, 0);
    if (mf_testing && mf_is("allocation-dirty-fail")) return -EIO;
    if (mf_testing && mf_is("allocation-short")) mf_packet(*out)->bytes--;
    if (mf_testing && mf_is("allocation-long")) mf_packet(*out)->bytes++;
    return 0;
}
static void mf_retire_reply(void *p, uint64_t ticket) {
    int rc = 123;
    const struct native_functional_camera_movie_format_receive receive = {FUNCTIONAL_CAMERA_CONTROL_SID, 12};
    assert(native_functional_camera_movie_format_release(FUNCTIONAL_CAMERA_CONTROL_AP, p, NULL, mf_log, &rc, ticket, &receive) == 1 && !rc);
    assert(native_functional_camera_movie_format_release(FUNCTIONAL_CAMERA_CONTROL_AP, p, mf_release, mf_log, &rc, ticket, NULL) == 1 && !rc);
}
static int mf_send(unsigned int destination, void *p) {
    assert(destination == FUNCTIONAL_CAMERA_CONTROL_AP); (void)mf_view();
    if (!mf_testing) { if (mf_size(p) == CP_STATE_SNAPSHOT_BYTES) mf_notice = p; else mf_ack = p; return 0; }
    mf_sends++; mf_reply = p;
    assert(mf_ticket && mf_ticket == mf_view().transaction && mf_view().send_inflight);
    if (mf_is("inline-free") || mf_is("inline-send-fail")) mf_retire_reply(p, mf_ticket);
    if (mf_is("transport-inline-receive")) {
        mf_transport_deliver(p, mf_ticket); int rc = 123;
        assert(native_functional_camera_movie_format_release(FUNCTIONAL_CAMERA_CONTROL_AP, p, mf_release, mf_log, &rc, mf_ticket, NULL) == 1 && !rc);
    }
    return mf_is("send-fail") || mf_is("inline-send-fail") ? -EIO : 0;
}
static int mf_reserve(void) {
    (void)mf_view(); assert(!mf_held);
    if (mf_testing && mf_is("guard-fail")) return -EBUSY;
    mf_held = 1;
    if (mf_testing && mf_is("crank-stale-reserved")) crank_state.crank_generation++;
    if (mf_testing && mf_is("crank-retirement-lost-reserved")) crank_state.reply_freed = 0;
    return 0;
}
static void mf_unreserve(void) {
    (void)mf_view(); assert(mf_held);
    if (mf_testing && mf_is("guard-release-reentry")) mf_reenter();
    mf_held = 0;
}
static int mf_predecessors(void) {
    (void)mf_view(); assert(mf_held);
    if (!mf_testing) return 1;
    mf_ready_calls++;
    struct native_cp_ee_controls_diagnostic_snapshot strict;
    native_cp_ee_controls_diagnostic_snapshot(&strict); assert(!memcmp(&strict, &mf_strict_saved, sizeof strict));
    assert(strict.leases[0].attempts == 1 && strict.leases[0].requests == 1 && strict.leases[0].clean_completion);
    struct native_cp_movie_format_diagnostic_snapshot movie; native_cp_movie_format_diagnostic_snapshot(&movie);
    assert(!memcmp(&movie, &mf_strict_movie, sizeof movie));
    assert(movie.attempts == 1 && movie.requests == 1 && movie.clean_completion && movie.sender_tid == strict.leases[0].sender_tid);
    if (mf_is("predecessor-fail")) return 0;
    int lost = mf_index("predecessor-lost-"); return lost < 0 || mf_ready_calls != (unsigned int)lost;
}
static const struct full_imaging_io mf_io = {mf_allocate, mf_release, mf_set_source, mf_send, mf_size, mf_source, mf_log};
static const struct native_cp_state_publication_guard mf_guard = {mf_reserve, mf_unreserve, mf_predecessors};
int fcam_bridge_call(const struct fcam_native_origin *origin, uint32_t opcode, const void *input, size_t input_bytes,
    void *output, size_t capacity, struct fcam_bridge_result *result) {
    assert(mf_held && mf_model && mf_active && origin->source == FUNCTIONAL_CAMERA_CONTROL_AP && origin->destination == FUNCTIONAL_CAMERA_CONTROL_SID);
    assert(origin->wire_fnv1a64 == hash(mf_active, origin->bytes));
    unsigned int state_call = 0;
    if (mf_testing) {
        assert(origin->command == 0x4000 && origin->bytes == 20);
        assert(opcode == FCAM_OP_STATE || opcode == FCAM_OP_CP_MOVIE_FORMAT);
        if (opcode == FCAM_OP_STATE) {
            state_call = ++mf_states; assert(!input && !input_bytes && capacity == 128);
            if ((state_call == 1 && (mf_is("before-error") || mf_is("before-error-retry"))) || (state_call == 2 && mf_is("after-error"))) return -EIO;
        } else {
            mf_models++; assert(input_bytes == 20 && capacity == 240 && !memcmp(input, mf_active, 20));
            if (mf_is("model-error")) return -EIO;
            if (mf_is("reentrant-dispatch")) mf_reenter();
        }
    }
    struct fcam_frame_proof before, after;
    assert(!fcam_model_proof_snapshot(mf_model, &before, sizeof before));
    struct fcam_exec_result actual = {0}; int rc = fcam_model_request(mf_model, opcode, input, input_bytes, output, capacity, &actual);
    if (rc) return rc;
    assert(!actual.token && !actual.total && !actual.offset && actual.used == capacity);
    assert(!fcam_model_proof_snapshot(mf_model, &after, sizeof after));
    if (opcode == FCAM_OP_STATE || opcode == FCAM_OP_CP_MOVIE_FORMAT || opcode == FCAM_OP_CP_PARAMETER_BANK)
        assert(!memcmp(&before, &after, sizeof before));
    *result = (struct fcam_bridge_result){actual.used, actual.used, mf_instance, 0};
    if (opcode == FCAM_OP_CP_PARAMETER_BANK) {
        unsigned char query[FCAM_CP_PARAMETER_BANK_RESULT_BYTES];
        assert(!fcam_model_cp_parameter_bank_snapshot(mf_model, u64((unsigned char *)output+16), query, sizeof query));
        assert(!memcmp(query, output, sizeof query));
    }
    if (opcode == FCAM_OP_CP_MOVIE_FORMAT) {
        unsigned char query[240];
        assert(!fcam_model_cp_movie_format_snapshot(mf_model, u64((unsigned char *)output+16),
            mf_context.bank_generation, mf_context.crank_generation, query, sizeof query));
        assert(!memcmp(query, output, sizeof query));
        assert(fcam_model_cp_movie_format_snapshot(mf_model, u64((unsigned char *)output+16),
            mf_context.bank_generation+1, mf_context.crank_generation, query, sizeof query) == -ESTALE);
    }
    if (!mf_testing) return 0;
    unsigned char *p = output;
    if (opcode == FCAM_OP_CP_MOVIE_FORMAT) {
        int i = mf_index("receipt-byte-"); if (i >= 0) { assert(i < 240); p[i] ^= 1; }
        i = mf_index("request-byte-"); if (i >= 0) { assert(i < 20); ((unsigned char *)mf_active)[i] ^= 1; }
        if (mf_is("post-c0-badproof")) p[80+FCAM_S_VIDEO_ENCODED] ^= 1;
        if (mf_is("model-overrun")) p[capacity] ^= 1;
        if (mf_is("result-short")) result->used--;
        if (mf_is("result-required")) result->required--;
        if (mf_is("result-token")) result->result_token = 1;
        if (mf_is("result-instance")) result->model_instance++;
        if (mf_is("model-positive")) return 1;
        if (mf_is("model-origin-mutation")) ((struct fcam_native_origin *)origin)->wire_fnv1a64 ^= 1;
        if (mf_is("model-input-mutation")) ((unsigned char *)input)[1] ^= 1;
        if (mf_is("model-bank-change")) { pthread_mutex_lock(&parameter_mutex); parameter_state.bank_generation++; pthread_mutex_unlock(&parameter_mutex); }
        if (mf_is("model-crank-change")) { pthread_mutex_lock(&crank_mutex); crank_state.crank_generation++; pthread_mutex_unlock(&crank_mutex); }
        if (mf_is("context-mutation")) mf_context.bank_generation++;
    } else {
        int i = mf_index(state_call == 1 ? "before-byte-" : "after-byte-");
        if (i >= 0) { assert(i < 128); p[i] ^= 1; }
        if ((state_call == 1 && mf_is("before-overrun")) || (state_call == 2 && mf_is("after-overrun"))) p[capacity] ^= 1;
        if (state_call == 1 && mf_is("before-result-instance")) result->model_instance++;
        if (state_call == 1 && mf_is("before-request-mutation")) ((unsigned char *)mf_active)[1] ^= 1;
        if (state_call == 1 && mf_is("before-generation-overflow")) memset(p+FCAM_S_GENERATION, 0xff, 8);
        if (state_call == 2 && mf_is("after-result-token")) result->result_token = 1;
    }
    return 0;
}
static void *mf_strict_boot(void *unused) {
    (void)unused; mf_strict_setup = 1; void *p = mf_crank_request(); int rc = 123;
    const struct native_cp_ee_controls_diagnostic_guard guard = {mf_reserve, mf_unreserve, mf_predecessors};
    assert(native_cp_ee_controls_diagnostic_dispatch(FUNCTIONAL_CAMERA_CONTROL_SID, p, &mf_io, &guard, 1, &rc) == 1 && !rc);
    assert(mf_ack && native_cp_ee_controls_diagnostic_release_reply(FUNCTIONAL_CAMERA_CONTROL_AP, mf_ack, mf_release, mf_log, &rc) == 1 && !rc);
    mf_ack = NULL;
    p = mf_request(0x80000027);
    const struct native_cp_movie_format_diagnostic_guard movie_guard = {mf_reserve, mf_unreserve, mf_predecessors};
    assert(native_cp_movie_format_diagnostic_dispatch(FUNCTIONAL_CAMERA_CONTROL_SID, p, &mf_io, &movie_guard, 1, &rc) == 1 && !rc);
    assert(native_cp_movie_format_diagnostic_release_reply(FUNCTIONAL_CAMERA_CONTROL_AP, mf_ack, mf_release, mf_log, &rc) == 1 && !rc);
    mf_ack = NULL; mf_strict_setup = 0; return NULL;
}
static void mf_control_request(int start) {
    unsigned char *p = mf_message(start ? 24 : 12, FUNCTIONAL_CAMERA_CONTROL_AP);
    p[0] = start ? 0 : 5; put16(p+2, start ? 0x3003 : 0x4073); put32(p+4, 0x80000026); if (!start) put32(p+8, 1);
    mf_active = p; int rc = 123;
    assert(native_functional_camera_control_dispatch(FUNCTIONAL_CAMERA_CONTROL_SID, p, &mf_io, &mf_guard, 1, &rc) == 1 && !rc);
    struct native_functional_camera_control_snapshot s; native_functional_camera_control_snapshot(&s);
    unsigned int index = start ? START_ACK : MODE_ACK; uint64_t cycle = s.lease_cycle_id[index];
    assert(native_functional_camera_control_observe_receive_cycle(FUNCTIONAL_CAMERA_CONTROL_AP, mf_ack, FUNCTIONAL_CAMERA_CONTROL_SID,
        start ? 16 : 12, cycle) == 1);
    assert(native_functional_camera_control_release_cycle(FUNCTIONAL_CAMERA_CONTROL_AP, mf_ack, mf_release, mf_log, &rc, cycle) == 1 && !rc); mf_ack = NULL;
    if (!start) {
        assert(native_functional_camera_control_observe_receive_cycle(FUNCTIONAL_CAMERA_CONTROL_AP, mf_notice, FUNCTIONAL_CAMERA_CONTROL_SID,
            CP_STATE_SNAPSHOT_BYTES, cycle) == 1);
        assert(native_functional_camera_control_release_cycle(FUNCTIONAL_CAMERA_CONTROL_AP, mf_notice, mf_release, mf_log, &rc, cycle) == 1 && !rc); mf_notice = NULL;
    }
    mf_active = NULL;
}
static void mf_commit_bank(uint32_t fps) {
    int testing = mf_testing; mf_testing = 0;
    mf_active = mf_bank_request(0x80000060, fps); mf_saved_bank_pointer = mf_active; int rc = 123;
    assert(native_functional_camera_parameter_dispatch(FUNCTIONAL_CAMERA_CONTROL_SID, mf_active, &mf_io, &mf_guard, 1, &rc) == 1 && !rc);
    struct native_functional_camera_parameter_snapshot bank; native_functional_camera_parameter_snapshot(&bank);
    assert(bank.model_committed && bank.verified && bank.request_freed && !bank.faults && bank.bank_generation);
    mf_active = mf_crank_request();
    assert(native_functional_camera_crank_dispatch(FUNCTIONAL_CAMERA_CONTROL_SID, mf_active, &mf_io, &mf_guard, 1, &rc) == 1 && !rc);
    struct native_functional_camera_crank_snapshot crank; native_functional_camera_crank_snapshot(&crank);
    const struct native_functional_camera_crank_receive event = {FUNCTIONAL_CAMERA_CONTROL_SID, 12};
    assert(native_functional_camera_crank_release(FUNCTIONAL_CAMERA_CONTROL_AP, mf_ack, NULL, mf_log, &rc, crank.transaction, &event) == 1 && !rc);
    assert(native_functional_camera_crank_release(FUNCTIONAL_CAMERA_CONTROL_AP, mf_ack, mf_release, mf_log, &rc, crank.transaction, NULL) == 1 && !rc);
    native_functional_camera_crank_snapshot(&crank); assert(crank.complete && !crank.faults && crank.request_freed && crank.reply_consumed);
    mf_context = (struct native_functional_camera_movie_format_context){crank.model_instance, crank.bank_generation, crank.crank_generation};
    mf_active = mf_ack = NULL; mf_testing = testing;
}
static int mf_dispatch(void *p, const struct full_imaging_io *io, const struct native_cp_state_publication_guard *guard, int enabled, int *rc) {
    void *saved = mf_active; mf_active = p;
    int handled = native_functional_camera_movie_format_dispatch(FUNCTIONAL_CAMERA_CONTROL_SID, p, io, guard,
        mf_is("missing-context") ? NULL : &mf_context, enabled, rc);
    mf_active = saved; return handled;
}
static void mf_assert_complete(const unsigned char original[20], uint64_t bank, uint64_t movie) {
    struct native_functional_camera_movie_format_snapshot s = mf_view();
    assert(s.owned && s.verified && s.complete && s.model_called && s.model_committed && !s.faults && !s.error);
    assert(!s.busy && !s.guard_held && !s.retained_request && !s.retained_reply && s.request_freed && s.reply_freed && s.reply_received && s.reply_consumed);
    assert(s.bank_generation == bank && s.crank_generation == mf_context.crank_generation && s.last_bank_generation == bank && s.last_crank_generation == mf_context.crank_generation && s.movie_generation == movie && s.last_movie_generation == movie);
    assert(s.receiver_tid > 0 && s.sender_tid == s.reply_free_tid && s.sender_tid == s.request_free_tid);
    if (!strncmp(mf_case, "transport-", 10)) assert(s.receiver_tid != s.sender_tid);
    assert(s.sender_tid != mf_strict_saved.leases[0].sender_tid);
    assert(s.config_generation == s.before_config_generation+1 && s.fps == u32(s.before_state+FCAM_S_FPS) && !s.validation_rc && s.software_format == 5 && !s.software_rate_index && s.software_codec == 1);
    assert(!memcmp(s.request, original, 20) && !memcmp(s.receipt+208, original, 20) && !memcmp(s.receipt+80, s.after_state, 128));
    unsigned char expected[128]; memcpy(expected, s.before_state, 128);
    uint64_t generation = s.before_config_generation+1;
    for (unsigned int i = 0; i < 8; i++) expected[FCAM_S_GENERATION+i] = (unsigned char)(generation >> (8*i));
    assert(!memcmp(expected, s.after_state, 128));
    unsigned char reply[12] = {1,0,0,0x40,0,0,0,0,0,0xf0,0,0}; memcpy(reply+4, original+4, 4);
    assert(!memcmp(reply, s.reply, 12) && s.reply_fnv1a64 == hash(reply, 12));
    assert(s.origin.wire_fnv1a64 == hash(original, 20) && s.receipt_fnv1a64 == hash(s.receipt, 240));
    assert(s.reply_pointer == s.allocation_pointer && s.request_pointer && s.reply_pointer);
    unsigned int frees = mf_frees; int rc = 123;
    assert(native_functional_camera_movie_format_release(FUNCTIONAL_CAMERA_CONTROL_SID, s.request_pointer, mf_release, mf_log, &rc, mf_request_ticket, NULL) == 1 && rc == -ESTALE);
    assert(native_functional_camera_movie_format_release(FUNCTIONAL_CAMERA_CONTROL_AP, s.reply_pointer, mf_release, mf_log, &rc, mf_ticket, NULL) == 1 && rc == -ESTALE && mf_frees == frees);
    void *old_route = mf_request(0x80000060);
    const struct native_cp_movie_format_diagnostic_guard guard = {mf_reserve, mf_unreserve, mf_predecessors};
    assert(native_cp_movie_format_diagnostic_dispatch(FUNCTIONAL_CAMERA_CONTROL_SID, old_route, &mf_io, &guard, 1, &rc) == 1 && rc == CP_MOVIE_FORMAT_SOURCE_BLOCKED);
    struct native_cp_ee_controls_diagnostic_snapshot strict; native_cp_ee_controls_diagnostic_snapshot(&strict);
    assert(!memcmp(&strict, &mf_strict_saved, sizeof strict)); mf_drop(old_route);
}
static void *mf_foreign_free(void *p) {
    int rc = 123;
    assert(native_functional_camera_movie_format_release(FUNCTIONAL_CAMERA_CONTROL_AP, p, mf_release, mf_log, &rc, mf_ticket, NULL) == 1 && rc == -EPERM); return NULL;
}
static void *mf_new_sender(void *p) {
    unsigned char original[20]; memcpy(original, p, 20); int rc = 123;
    assert(mf_dispatch(p, &mf_io, &mf_guard, 1, &rc) == 1 && !rc); mf_retire_reply(mf_reply, mf_ticket); mf_assert_complete(original, 1, 1); return NULL;
}
static void mf_finish(void) {
    assert(!mf_held); fcam_model_destroy(mf_model);
    for (unsigned int i = 0; i < 96; i++) free(mf_packets[i]);
}
int main(int argc, char **argv) {
    assert(argc == 2); mf_case = argv[1]; av_log_set_level(AV_LOG_ERROR);
    assert(!native_functional_camera_control_owner_init()); assert(!native_functional_camera_parameter_owner_init());
    assert(!native_functional_camera_crank_owner_init());
    assert(!native_functional_camera_movie_format_owner_init()); assert(native_functional_camera_movie_format_owner_init() == -EALREADY);
    assert(!native_cp_ee_controls_diagnostic_owner_init()); assert(!native_cp_movie_format_diagnostic_owner_init());
    pthread_t thread; assert(!pthread_create(&thread, NULL, mf_strict_boot, NULL)); assert(!pthread_join(thread, NULL));
    native_cp_ee_controls_diagnostic_snapshot(&mf_strict_saved);
    native_cp_movie_format_diagnostic_snapshot(&mf_strict_movie);
    assert(mf_strict_saved.leases[0].attempts == 1 && mf_strict_saved.leases[0].requests == 1 && mf_strict_saved.leases[0].clean_completion);
    mf_model = fcam_model_create(mf_instance); assert(mf_model);
    mf_control_request(1); mf_control_request(0);
    if (!mf_is("cold")) mf_commit_bank(30);
    struct native_functional_camera_control_snapshot control; native_functional_camera_control_snapshot(&control);
    struct native_functional_camera_parameter_snapshot bank; native_functional_camera_parameter_snapshot(&bank);
    struct native_functional_camera_crank_snapshot saved_crank; native_functional_camera_crank_snapshot(&saved_crank);
    void *p = mf_request(mf_is("cookie-zero") ? 0 : mf_is("cookie-max") ? UINT32_MAX : UINT32_C(0x80000060));
    if (mf_is("opaque-byte1") || mf_is("opaque-all")) ((unsigned char *)p)[1] = 0xa5;
    if (mf_is("opaque-byte11") || mf_is("opaque-all")) ((unsigned char *)p)[11] = 0xe7;
    if (mf_is("opaque-byte19") || mf_is("opaque-all")) ((unsigned char *)p)[19] = 0x93;
    if (mf_is("context-instance")) mf_context.model_instance++;
    if (mf_is("context-bank")) mf_context.bank_generation++;
    if (mf_is("context-crank")) mf_context.crank_generation++;
    unsigned char original[20]; memcpy(original, p, 20);
    struct full_imaging_io io = mf_io; const struct native_cp_state_publication_guard *guard = &mf_guard;
    if (mf_is("missing-release")) io.release = NULL;
    if (mf_is("missing-allocate")) io.allocate = NULL;
    if (mf_is("missing-send")) io.send = NULL;
    if (mf_is("missing-guard")) guard = NULL;
    if (mf_is("missing-source")) io.source = NULL;
    if (mf_is("missing-set-source")) io.set_source = NULL;
    if (mf_is("missing-record")) io.record = NULL;
    int selector = mf_index("selector-byte-");
    if (selector >= 0) { assert(selector >= 8 && selector < 19 && selector != 11); ((unsigned char *)p)[selector] ^= 1; }
    if (mf_is("crank-retained")) crank_state.retained_reply = p;
    if (mf_is("crank-fault")) crank_state.faults = 1;
    if (mf_is("crank-unreceived")) crank_state.reply_received = 0;
    if (mf_is("crank-unfreed")) crank_state.reply_freed = 0;
    if (mf_is("crank-foreign-free")) crank_state.reply_free_tid++;
    if (mf_is("crank-receipt-mutation")) crank_state.receipt[200] ^= 1;
    if (mf_is("crank-lineage")) crank_state.bank_transaction++;
    if (mf_is("wrong-source")) mf_packet(p)->source++;
    if (mf_is("short")) mf_packet(p)->bytes--;
    if (mf_is("long")) mf_packet(p)->bytes++;
    if (mf_is("wrong-type")) ((unsigned char *)p)[0] = 0;
    if (mf_is("unrelated")) ((unsigned char *)p)[2] ^= 1;
    if (mf_is("mode1")) put32((unsigned char *)p+8, 1);
    if (mf_is("mode-wide")) put32((unsigned char *)p+8, UINT32_MAX);
    if (mf_is("bank-retained")) parameter_state.retained_request = p;
    if (mf_is("bank-not-freed")) parameter_state.request_freed = 0;
    if (mf_is("bank-fault")) parameter_state.faults = 1;
    if (mf_is("bank-not-verified")) parameter_state.verified = 0;
    if (mf_is("bank-wrong-instance")) parameter_state.model_instance++;
    if (mf_is("bank-receipt-mutation")) parameter_state.receipt[200] ^= 1;
    if (mf_is("current-mode-live")) state.mode_complete = 0;
    if (mf_is("transaction-overflow")) movie_format_state.transaction = UINT64_MAX;
    if (mf_is("movie-generation-overflow")) movie_format_state.last_movie_generation = UINT64_MAX;
    if (mf_is("live-config-newer")) {
        unsigned char live[128], config[48] = {0}; struct fcam_exec_result actual = {0};
        assert(!fcam_model_request(mf_model, FCAM_OP_STATE, NULL, 0, live, sizeof live, &actual));
        memcpy(config, live+8, 40); put32(config+12, 73);
        const uint64_t previous = u64(live+FCAM_S_GENERATION);
        assert(!fcam_model_request(mf_model, FCAM_OP_CONFIGURE, config, sizeof config, live, sizeof live, &actual));
        assert(u64(live+FCAM_S_GENERATION) == previous+1 && u32(live+FCAM_S_QUALITY) == 73);
    }
    const struct native_functional_camera_movie_format_context operation_context = mf_context;
    mf_testing = 1; mf_fail_request = mf_is("request-free-fail"); mf_fail_reply = mf_is("reply-free-fail");
    if (mf_is("fork-held-lock")) {
        pthread_mutex_lock(&mutex); pthread_mutex_lock(&parameter_mutex); pthread_mutex_lock(&crank_mutex); pthread_mutex_lock(&movie_format_mutex); pid_t child = fork(); assert(child >= 0);
        if (!child) {
            int rc = 123; assert(native_functional_camera_movie_format_owner_init() == -EXDEV);
            assert(mf_dispatch(p, &io, guard, 1, &rc) == 1 && rc == -EXDEV);
            assert(native_functional_camera_movie_format_release(FUNCTIONAL_CAMERA_CONTROL_SID, p, mf_release, NULL, &rc, 1, NULL) == 1 && rc == -EXDEV);
            assert(mf_view().faults); _exit(0);
        }
        pthread_mutex_unlock(&movie_format_mutex); pthread_mutex_unlock(&crank_mutex); pthread_mutex_unlock(&parameter_mutex); pthread_mutex_unlock(&mutex);
        int status; assert(waitpid(child, &status, 0) == child && WIFEXITED(status) && !WEXITSTATUS(status)); mf_finish(); return 0;
    }
    if (mf_is("new-sender")) {
        assert(!pthread_create(&thread, NULL, mf_new_sender, p)); assert(!pthread_join(thread, NULL)); mf_finish(); return 0;
    }
    int rc = 123;
    if (mf_is("before-error-retry")) {
        assert(mf_dispatch(p, &io, guard, 1, &rc) == 1 && rc == -EIO && !mf_models && !mf_view().faults && !mf_view().owned);
        rc = 123;
    }
    int handled = mf_is("wrong-destination") ? native_functional_camera_movie_format_dispatch(FUNCTIONAL_CAMERA_CONTROL_SID+1, p, &io, guard, &mf_context, 1, &rc) :
        mf_dispatch(p, &io, guard, !mf_is("disabled"), &rc);
    struct native_functional_camera_movie_format_snapshot s = mf_view();
    if (mf_is("context-mutation")) {
        assert(mf_context.bank_generation == operation_context.bank_generation+1 && s.bank_generation == operation_context.bank_generation);
        mf_context = operation_context;
    }
    assert(!s.busy && !s.guard_held && !mf_held);
    struct native_cp_movie_format_diagnostic_snapshot strict_movie; native_cp_movie_format_diagnostic_snapshot(&strict_movie);
    assert(!memcmp(&strict_movie, &mf_strict_movie, sizeof strict_movie));
    struct native_cp_ee_controls_diagnostic_snapshot strict; native_cp_ee_controls_diagnostic_snapshot(&strict);
    assert(!memcmp(&strict, &mf_strict_saved, sizeof strict));
    struct native_functional_camera_control_snapshot after_control; native_functional_camera_control_snapshot(&after_control);
    if (!mf_is("current-mode-live")) assert(!memcmp(&control, &after_control, sizeof control));
    struct native_functional_camera_parameter_snapshot after_bank; native_functional_camera_parameter_snapshot(&after_bank);
    if (strncmp(mf_case, "bank-", 5) && !mf_is("model-bank-change")) assert(!memcmp(&bank, &after_bank, sizeof bank));
    struct native_functional_camera_crank_snapshot after_crank; native_functional_camera_crank_snapshot(&after_crank);
    if (strncmp(mf_case, "crank-", 6) && !mf_is("model-crank-change")) assert(!memcmp(&saved_crank, &after_crank, sizeof saved_crank));
    if (mf_is("crank-stale-reserved") || mf_is("crank-retirement-lost-reserved"))
        assert(handled == 1 && rc < 0 && mf_ready_calls == 1 && !mf_states && !mf_models && !s.model_called && !s.model_committed && !s.owned);
    int must_own = mf_is("success") || mf_is("opaque-byte1") || mf_is("opaque-byte11") || mf_is("opaque-byte19") || mf_is("opaque-all") || mf_is("context-mutation") || mf_is("live-config-newer") || mf_is("cookie-zero") || mf_is("cookie-max") ||
        mf_is("inline-free") || mf_is("allocation-param-reuse") || mf_is("completed-reuse") || mf_is("completed-reply-reuse") || mf_is("duplicate-bank") || mf_is("repeat-new-bank") ||
        mf_is("reentrant-dispatch") || mf_is("reentrant-metadata") || mf_is("reentrant-free") || mf_is("reentrant-request-early") || mf_is("guard-release-reentry") || mf_is("before-error-retry") ||
        !strncmp(mf_case, "allocation-", 11) || mf_is("reply-source-set") || mf_is("send-fail") || mf_is("inline-send-fail") ||
        !strncmp(mf_case, "request-free-", 13) || !strncmp(mf_case, "reply-free-", 11) || !strncmp(mf_case, "receive-", 8) ||
        mf_is("stale-receive") || mf_is("stale-free") || mf_is("foreign-pointer") || mf_is("foreign-free") || !strncmp(mf_case, "transport-", 10) ||
        mf_is("free-before-receive") || mf_is("duplicate-receive") || mf_is("predecessor-lost-5") || mf_is("predecessor-lost-6");
    if (must_own) assert(handled == 1 && !rc && s.owned && s.verified && s.model_committed);
    if (mf_index("receipt-byte-") >= 0 || mf_index("request-byte-") >= 0 || mf_is("post-c0-badproof"))
        assert(handled == 1 && rc < 0 && mf_models == 1 && s.model_committed && s.model_rc == 0 && s.validation_rc < 0 && s.commits == 1 && s.faults && !s.verified && !s.owned);
    if (mf_index("before-byte-") >= 0) assert(handled == 1 && rc < 0 && !s.owned);
    if (mf_index("after-byte-") >= 0) assert(handled == 1 && rc < 0 && mf_states == 2 && mf_models == 1 && s.model_committed && s.model_rc == 0 && s.faults && !s.owned);
    if (!handled) {
        assert(mf_is("cold") || mf_is("disabled") || mf_is("wrong-type") || mf_is("wrong-destination") || mf_is("unrelated"));
        assert(rc == 123 && !mf_states && !mf_models && !mf_allocations && !mf_sends); mf_finish(); return 0;
    }
    if (!s.owned) {
        assert(rc < 0 && !s.retained_request && !s.retained_reply && !s.request_freed && !mf_allocations && !mf_sends);
        if (mf_models) {
            assert(s.model_called && s.faults);
            assert(s.model_committed == (s.model_rc == 0));
            assert(!s.reply[0] && !s.reply_fnv1a64);
            unsigned int calls = mf_models, states = mf_states; int retry = 123;
            void *q = mf_request(8); assert(mf_dispatch(q, &mf_io, &mf_guard, 1, &retry) == 1 && retry < 0);
            assert(mf_models == calls && mf_states == states); mf_drop(q);
        }
        mf_finish(); return 0;
    }
    assert(!rc && s.model_committed && s.verified && s.commits == 1 && s.verified_commits == 1 && mf_models == 1);
    assert(mf_states == (mf_is("before-error-retry") ? 3u : 2u));
    unsigned int zero_frees = mf_frees; int zero_rc = 123;
    if (s.retained_request) assert(native_functional_camera_movie_format_release(FUNCTIONAL_CAMERA_CONTROL_SID, s.retained_request,
        mf_release, mf_log, &zero_rc, 0, NULL) == 1 && zero_rc == -ESTALE);
    if (s.retained_reply) assert(native_functional_camera_movie_format_release(FUNCTIONAL_CAMERA_CONTROL_AP, s.retained_reply,
        mf_release, mf_log, &zero_rc, 0, NULL) == 1 && zero_rc == -ESTALE);
    assert(mf_frees == zero_frees);
    if (s.faults) {
        assert(!s.complete && !s.reply_consumed && (s.retained_request || s.retained_reply || s.reply_alias || s.reply_freed));
        assert(s.model_rc == 0);
        if (mf_is("request-free-fail") || mf_is("request-free-wire") || mf_is("request-free-source") || mf_is("request-free-size")) {
            unsigned int frees = mf_frees; int freed = 123;
            assert(native_functional_camera_movie_format_release(FUNCTIONAL_CAMERA_CONTROL_SID, p, mf_release, mf_log, &freed, mf_request_ticket+1, NULL) == 1 && freed == -ESTALE && mf_frees == frees);
            mf_fail_request = 0; mf_packet(p)->bytes = 20; mf_packet(p)->source = FUNCTIONAL_CAMERA_CONTROL_AP; memcpy(p, original, 20);
            assert(native_functional_camera_movie_format_release(FUNCTIONAL_CAMERA_CONTROL_SID, p, mf_release, mf_log, &freed, mf_request_ticket, NULL) == 1 && !freed);
            assert(mf_view().request_freed && mf_view().faults && !mf_view().complete);
        }
        if (s.retained_reply && !s.reply_send_started) {
            int freed = 123; assert(native_functional_camera_movie_format_release(FUNCTIONAL_CAMERA_CONTROL_AP, s.retained_reply, mf_release, mf_log, &freed, mf_ticket, NULL) == 1 && !freed);
            assert(mf_view().reply_cleanup_freed && !mf_view().reply_freed && !mf_view().reply_consumed && mf_view().faults);
        }
        mf_finish(); return 0;
    }
    if (mf_is("stale-receive") || mf_is("stale-free") || mf_is("foreign-pointer")) {
        unsigned int frees = mf_frees; int observed = 123;
        const struct native_functional_camera_movie_format_receive event = {FUNCTIONAL_CAMERA_CONTROL_SID, 12};
        void *q = mf_is("foreign-pointer") ? mf_request(0) : mf_reply;
        uint64_t ticket = mf_is("foreign-pointer") ? mf_ticket : mf_ticket+1;
        assert(native_functional_camera_movie_format_release(FUNCTIONAL_CAMERA_CONTROL_AP, q, mf_release, mf_log, &observed,
            ticket, mf_is("stale-free") || mf_is("foreign-pointer") ? NULL : &event) == 1 && observed < 0 && mf_frees == frees);
        if (mf_is("foreign-pointer")) mf_drop(q);
    }
    if (mf_is("receive-wrong-source") || mf_is("receive-wrong-size") || mf_is("receive-wrong-destination") || mf_is("receive-wire") ||
        mf_is("receive-metadata-source") || mf_is("receive-metadata-size") || mf_is("free-before-receive")) {
        int observed = 123; struct native_functional_camera_movie_format_receive event = {FUNCTIONAL_CAMERA_CONTROL_SID, 12};
        if (mf_is("receive-wrong-source")) event.source++;
        if (mf_is("receive-wrong-size")) event.bytes--;
        if (mf_is("receive-wire")) ((unsigned char *)mf_reply)[1] ^= 1;
        if (mf_is("receive-metadata-source")) mf_packet(mf_reply)->source++;
        if (mf_is("receive-metadata-size")) mf_packet(mf_reply)->bytes--;
        assert(native_functional_camera_movie_format_release(FUNCTIONAL_CAMERA_CONTROL_AP+(unsigned int)mf_is("receive-wrong-destination"), mf_reply,
            mf_release, mf_log, &observed, mf_ticket, mf_is("free-before-receive") ? NULL : &event) == 1 && observed < 0);
        assert(mf_view().faults && mf_view().retained_reply == mf_reply && !mf_view().reply_freed && !mf_view().complete); mf_finish(); return 0;
    }
    if (mf_is("transport-receive-sender-free") || mf_is("transport-receive-foreign-free")) mf_transport_deliver(mf_reply, mf_ticket);
    if (mf_is("transport-receive-foreign-free")) {
        assert(!pthread_create(&thread, NULL, mf_foreign_free, mf_reply)); assert(!pthread_join(thread, NULL));
        assert(mf_view().receiver_tid > 0 && mf_view().receiver_tid != mf_view().sender_tid && mf_view().faults &&
            mf_view().retained_reply == mf_reply && !mf_view().reply_freed && !mf_view().reply_consumed && !mf_view().complete);
        mf_finish(); return 0;
    }
    if (!s.reply_freed) {
        if (mf_is("duplicate-receive") || mf_is("foreign-free") || mf_is("reply-free-fail") || mf_is("reply-free-wire")) {
            int observed = 123; const struct native_functional_camera_movie_format_receive event = {FUNCTIONAL_CAMERA_CONTROL_SID, 12};
            assert(native_functional_camera_movie_format_release(FUNCTIONAL_CAMERA_CONTROL_AP, mf_reply, NULL, mf_log, &observed, mf_ticket, &event) == 1 && !observed);
            if (mf_is("duplicate-receive")) assert(native_functional_camera_movie_format_release(FUNCTIONAL_CAMERA_CONTROL_AP, mf_reply, NULL, mf_log, &observed, mf_ticket, &event) == 1 && observed < 0);
            else if (mf_is("foreign-free")) { assert(!pthread_create(&thread, NULL, mf_foreign_free, mf_reply)); assert(!pthread_join(thread, NULL)); }
            else {
                if (mf_is("reply-free-wire")) ((unsigned char *)mf_reply)[1] ^= 1;
                assert(native_functional_camera_movie_format_release(FUNCTIONAL_CAMERA_CONTROL_AP, mf_reply, mf_release, mf_log, &observed, mf_ticket, NULL) == 1 && observed < 0);
                assert(mf_view().retained_reply == mf_reply && !mf_view().reply_freed);
                mf_fail_reply = 0; memcpy(mf_reply, mf_view().reply, 12);
                assert(native_functional_camera_movie_format_release(FUNCTIONAL_CAMERA_CONTROL_AP, mf_reply, mf_release, mf_log, &observed, mf_ticket, NULL) == 1 && !observed);
            }
            assert(mf_view().faults && !mf_view().reply_consumed && !mf_view().complete); mf_finish(); return 0;
        }
        if (mf_is("transport-receive-sender-free") || mf_is("transport-during-request-free")) {
            int freed = 123; assert(mf_view().reply_received && mf_view().receiver_tid != mf_view().sender_tid);
            assert(native_functional_camera_movie_format_release(FUNCTIONAL_CAMERA_CONTROL_AP, mf_reply, mf_release, mf_log, &freed, mf_ticket, NULL) == 1 && !freed);
        } else mf_retire_reply(mf_reply, mf_ticket);
    }
    mf_assert_complete(original, 1, 1);
    if (mf_is("completed-reuse") || mf_is("completed-reply-reuse")) {
        s = mf_view(); unsigned int destination = mf_is("completed-reuse") ? FUNCTIONAL_CAMERA_CONTROL_SID : FUNCTIONAL_CAMERA_CONTROL_AP;
        void *q = mf_reuse(mf_is("completed-reuse") ? s.request_pointer : s.reply_pointer, 12, FUNCTIONAL_CAMERA_CONTROL_AP); int freed = 123;
        assert(native_functional_camera_movie_format_release(destination, q, mf_release, mf_log, &freed, mf_request_ticket, NULL) == 1 && freed == -ESTALE);
        assert(!native_functional_camera_movie_format_release(destination, q, mf_release, mf_log, &freed, 0, NULL));
        assert(!mf_release(destination, q));
    }
    if (mf_is("duplicate-bank") || mf_is("repeat-new-bank")) {
        unsigned int calls = mf_models, states = mf_states; void *q = mf_request(0x80000060); int retry = 123;
        assert(mf_dispatch(q, &mf_io, &mf_guard, 1, &retry) == 1 && retry == -ESTALE && mf_models == calls && mf_states == states); mf_drop(q);
        if (mf_is("repeat-new-bank")) {
            uint64_t old_ticket = mf_ticket; void *old_pointer = mf_view().reply_pointer;
            mf_commit_bank(60); q = mf_request(0x80000060); memcpy(original, q, 20);
            assert(mf_dispatch(q, &mf_io, &mf_guard, 1, &retry) == 1 && !retry);
            int stale = 123; assert(native_functional_camera_movie_format_release(FUNCTIONAL_CAMERA_CONTROL_AP, old_pointer, mf_release, mf_log, &stale, old_ticket, NULL) == 1 && stale == -ESTALE);
            mf_retire_reply(mf_reply, mf_ticket); mf_assert_complete(original, 2, 2);
            assert(mf_view().commits == 2 && mf_view().completions == 2 && mf_view().fps == 60);
        }
    }
    native_cp_ee_controls_diagnostic_snapshot(&strict); assert(!memcmp(&strict, &mf_strict_saved, sizeof strict));
    native_cp_movie_format_diagnostic_snapshot(&strict_movie); assert(!memcmp(&strict_movie, &mf_strict_movie, sizeof strict_movie));
    assert(!mf_strict_setup); mf_finish(); puts("PASS movie-format real-Core component; original AP/physical/capture unverified"); return 0;
}
#else
/* SPDX-License-Identifier: MIT */
#ifdef FCAM_CRANK_CONTROL_TEST
#define _GNU_SOURCE
#ifndef HOST_TEST
#error Component fixture only
#endif
#include "functional-camera-control.c"
#include "cp-ee-controls-diagnostic.h"
#include "../../../report/functional-camera-core/functional-camera-core.h"
#include <assert.h>
#include <stdlib.h>
#include <sys/wait.h>
#include <libavutil/log.h>

/* Real Core, fixture bridge/OSAL/guard. Kept allocations detect duplicate real
 * frees deterministically and allow deliberate successful allocation reuse. */
struct kr_packet { unsigned int source, bytes, capacity, live; unsigned char body[]; };
static struct kr_packet *kr_packets[96];
static struct fcam_model *kr_model;
static const char *kr_case;
static void *kr_active, *kr_ack, *kr_notice, *kr_reply, *kr_saved_bank_pointer;
static uint64_t kr_ticket, kr_request_ticket;
static unsigned int kr_states, kr_models, kr_allocations, kr_sends, kr_frees, kr_ready_calls;
static int kr_held, kr_testing, kr_strict_setup, kr_reentered, kr_fail_request, kr_fail_reply;
static struct native_cp_ee_controls_diagnostic_snapshot kr_strict_saved;
static const struct full_imaging_io kr_io;
static const struct native_cp_state_publication_guard kr_guard;
static const uint64_t kr_instance = UINT64_C(0x123456789abcde);
static int kr_is(const char *s) { return !strcmp(kr_case, s); }
static int kr_index(const char *prefix) {
    size_t n = strlen(prefix); return !strncmp(kr_case, prefix, n) ? (int)strtoul(kr_case+n, NULL, 10) : -1;
}
static struct kr_packet *kr_packet(void *p) {
    for (unsigned int i = 0; i < 96; i++) if (kr_packets[i] && kr_packets[i]->body == p) return kr_packets[i];
    assert(0); return NULL;
}
static void *kr_message(unsigned int bytes, unsigned int source) {
    struct kr_packet *p = calloc(1, sizeof *p + bytes + 16); assert(p);
    p->source = source; p->bytes = bytes; p->capacity = bytes + 16; p->live = 1;
    for (unsigned int i = 0; i < 96; i++) if (!kr_packets[i]) { kr_packets[i] = p; return p->body; }
    assert(0); return NULL;
}
static void *kr_reuse(void *pointer, unsigned int bytes, unsigned int source) {
    struct kr_packet *p = kr_packet(pointer); assert(!p->live && p->capacity >= bytes);
    p->live = 1; p->source = source; p->bytes = bytes; memset(p->body, 0, bytes); return p->body;
}
static void kr_drop(void *p) { struct kr_packet *s = kr_packet(p); assert(s->live); s->live = 0; }
static void *kr_request(uint32_t cookie) {
    unsigned char *p = kr_message(12, FUNCTIONAL_CAMERA_CONTROL_AP);
    p[0] = 5; put16(p+2, 0x409d); put32(p+4, cookie); return p;
}
static void *kr_bank_request(uint32_t cookie, uint32_t fps) {
    unsigned char *p = kr_message(FCAM_CP_PARAMETER_BANK_BYTES, FUNCTIONAL_CAMERA_CONTROL_AP);
    p[0] = 5; put16(p+2, 0x4063); put32(p+4, cookie);
    for (unsigned int i = 0; i < CP_PARAMETER_BATCH_SLOTS; i++) {
        struct cp_parameter_batch_slot s = cp_parameter_batch_slots[i];
        p[s.offset] = 5; p[s.offset+1] = (unsigned char)i; put16(p+s.offset+2, s.opcode); put32(p+s.offset+4, i);
        for (unsigned int j = 8; j < s.size; j++) p[s.offset+j] = (unsigned char)(i+j);
    }
    put32(p+FCAM_CP_PARAMETER_FPS_AT, fps); return p;
}
static struct native_functional_camera_crank_snapshot kr_view(void) {
    struct native_functional_camera_crank_snapshot s; native_functional_camera_crank_snapshot(&s); return s;
}
static void kr_reenter(void) {
    if (kr_reentered) return;
    kr_reentered = 1; void *p = kr_request(7); int rc = 123;
    unsigned int states = kr_states, models = kr_models;
    assert(native_functional_camera_crank_dispatch(FUNCTIONAL_CAMERA_CONTROL_SID, p, &kr_io, &kr_guard, 1, &rc) == 1 && rc < 0);
    assert(kr_states == states && kr_models == models); kr_drop(p);
}
static unsigned int kr_size(void *p) {
    (void)kr_view();
    if (kr_testing && kr_is("reentrant-metadata")) kr_reenter();
    struct kr_packet *s = kr_packet(p); assert(s->live); return s->bytes;
}
static unsigned int kr_source(void *p) { struct kr_packet *s = kr_packet(p); assert(s->live); return s->source; }
static void kr_set_source(void *p, unsigned int source) {
    (void)kr_view(); kr_packet(p)->source = source + (kr_testing && kr_is("reply-source-set"));
}
static void kr_log(const char *tag, const char *text) {
    (void)kr_view();
    if (strncmp(tag, "FUNCTIONAL_CP_CRANK_CONTROL_", sizeof "FUNCTIONAL_CP_CRANK_CONTROL_"-1)) return;
    assert(strlen(text) < 4095 && strstr(text, "capture_verified=0")); printf("%s%s\n", tag, text);
    if (strstr(text, "event=VERIFIED ")) kr_ticket = kr_request_ticket = kr_view().transaction;
    if (strstr(text, "event=SENT ") && kr_active) {
        if (kr_is("request-free-wire")) ((unsigned char *)kr_active)[1] ^= 1;
        if (kr_is("request-free-source")) kr_packet(kr_active)->source++;
        if (kr_is("request-free-size")) kr_packet(kr_active)->bytes--;
    }
}
/* Captured send ticket shared unchanged across the actual receive thread. */
struct kr_transport_event { void *pointer; uint64_t transaction; };
static void *kr_transport_receive(void *value) {
    const struct kr_transport_event *ticket = value;
    const struct native_functional_camera_crank_receive receive = {FUNCTIONAL_CAMERA_CONTROL_SID, 12};
    int rc = 123;
    assert(native_functional_camera_crank_release(FUNCTIONAL_CAMERA_CONTROL_AP, ticket->pointer, NULL, kr_log, &rc,
        ticket->transaction, &receive) == 1 && !rc);
    struct native_functional_camera_crank_snapshot s = kr_view();
    assert(s.reply_received && s.receiver_tid == tid() && s.receiver_tid > 0 && s.receiver_tid != s.sender_tid && !s.faults);
    return NULL;
}
static void kr_transport_deliver(void *pointer, uint64_t transaction) {
    struct kr_transport_event ticket = {pointer, transaction}; pthread_t thread;
    assert(!pthread_create(&thread, NULL, kr_transport_receive, &ticket)); assert(!pthread_join(thread, NULL));
}
static int kr_release(unsigned int destination, void *p) {
    assert(destination == FUNCTIONAL_CAMERA_CONTROL_AP || destination == FUNCTIONAL_CAMERA_CONTROL_SID);
    (void)kr_view();
    if (kr_testing && p == kr_active && kr_is("transport-during-request-free")) {
        assert(kr_view().request_releasing && kr_reply); kr_transport_deliver(kr_reply, kr_ticket);
    }
    if (kr_testing && kr_is("reentrant-free")) {
        int rc = 123;
        assert(native_functional_camera_crank_release(destination, p, kr_release, NULL, &rc, kr_ticket, NULL) == 1 && rc == -EBUSY);
    }
    if (kr_testing && ((p == kr_active && kr_fail_request) || (p == kr_reply && kr_fail_reply))) return -EIO;
    kr_frees++; kr_drop(p); return 0;
}
static int kr_allocate(unsigned int destination, void **out, unsigned int bytes, unsigned int count) {
    assert(destination == FUNCTIONAL_CAMERA_CONTROL_AP && count == 1); (void)kr_view();
    if (kr_testing) {
        kr_allocations++; assert(bytes == 12 && kr_view().verified && kr_view().model_committed);
        if (kr_is("reentrant-request-early")) {
            int rc = 123; unsigned int frees = kr_frees;
            assert(native_functional_camera_crank_release(FUNCTIONAL_CAMERA_CONTROL_SID, kr_active, kr_release, NULL,
                &rc, kr_request_ticket, NULL) == 1 && rc == -EBUSY && kr_frees == frees && !kr_view().faults);
        }
        if (kr_is("allocation-fail")) return -ENOMEM;
        if (kr_is("allocation-alias")) { *out = kr_active; return 0; }
        if (kr_is("allocation-alias-offset")) { *out = (unsigned char *)kr_active+4; return 0; }
        if (kr_is("allocation-param-reuse")) {
            *out = kr_reuse(kr_saved_bank_pointer, 12, 0);
            int rc = 123;
            assert(!native_functional_camera_parameter_release(FUNCTIONAL_CAMERA_CONTROL_SID, *out, kr_release, NULL, &rc, 0) && rc == 123);
            return 0;
        }
    }
    *out = kr_message(bytes, 0);
    if (kr_testing && kr_is("allocation-dirty-fail")) return -EIO;
    if (kr_testing && kr_is("allocation-short")) kr_packet(*out)->bytes--;
    if (kr_testing && kr_is("allocation-long")) kr_packet(*out)->bytes++;
    return 0;
}
static void kr_retire_reply(void *p, uint64_t ticket) {
    int rc = 123;
    const struct native_functional_camera_crank_receive receive = {FUNCTIONAL_CAMERA_CONTROL_SID, 12};
    assert(native_functional_camera_crank_release(FUNCTIONAL_CAMERA_CONTROL_AP, p, NULL, kr_log, &rc, ticket, &receive) == 1 && !rc);
    assert(native_functional_camera_crank_release(FUNCTIONAL_CAMERA_CONTROL_AP, p, kr_release, kr_log, &rc, ticket, NULL) == 1 && !rc);
}
static int kr_send(unsigned int destination, void *p) {
    assert(destination == FUNCTIONAL_CAMERA_CONTROL_AP); (void)kr_view();
    if (!kr_testing) { if (kr_size(p) == CP_STATE_SNAPSHOT_BYTES) kr_notice = p; else kr_ack = p; return 0; }
    kr_sends++; kr_reply = p;
    assert(kr_ticket && kr_ticket == kr_view().transaction && kr_view().send_inflight);
    if (kr_is("inline-free") || kr_is("inline-send-fail")) kr_retire_reply(p, kr_ticket);
    if (kr_is("transport-inline-receive")) {
        kr_transport_deliver(p, kr_ticket); int rc = 123;
        assert(native_functional_camera_crank_release(FUNCTIONAL_CAMERA_CONTROL_AP, p, kr_release, kr_log, &rc, kr_ticket, NULL) == 1 && !rc);
    }
    return kr_is("send-fail") || kr_is("inline-send-fail") ? -EIO : 0;
}
static int kr_reserve(void) {
    (void)kr_view(); assert(!kr_held);
    if (kr_testing && kr_is("guard-fail")) return -EBUSY;
    kr_held = 1; return 0;
}
static void kr_unreserve(void) {
    (void)kr_view(); assert(kr_held);
    if (kr_testing && kr_is("guard-release-reentry")) kr_reenter();
    kr_held = 0;
}
static int kr_predecessors(void) {
    (void)kr_view(); assert(kr_held);
    if (!kr_testing) return 1;
    kr_ready_calls++;
    struct native_cp_ee_controls_diagnostic_snapshot strict;
    native_cp_ee_controls_diagnostic_snapshot(&strict); assert(!memcmp(&strict, &kr_strict_saved, sizeof strict));
    assert(strict.leases[0].attempts == 1 && strict.leases[0].requests == 1 && strict.leases[0].clean_completion);
    if (kr_is("predecessor-fail")) return 0;
    int lost = kr_index("predecessor-lost-"); return lost < 0 || kr_ready_calls != (unsigned int)lost;
}
static const struct full_imaging_io kr_io = {kr_allocate, kr_release, kr_set_source, kr_send, kr_size, kr_source, kr_log};
static const struct native_cp_state_publication_guard kr_guard = {kr_reserve, kr_unreserve, kr_predecessors};
int fcam_bridge_call(const struct fcam_native_origin *origin, uint32_t opcode, const void *input, size_t input_bytes,
    void *output, size_t capacity, struct fcam_bridge_result *result) {
    assert(kr_held && kr_model && kr_active && origin->source == FUNCTIONAL_CAMERA_CONTROL_AP && origin->destination == FUNCTIONAL_CAMERA_CONTROL_SID);
    assert(origin->wire_fnv1a64 == hash(kr_active, origin->bytes));
    unsigned int state_call = 0;
    if (kr_testing) {
        assert(origin->command == 0x409d && origin->bytes == 12);
        assert(opcode == FCAM_OP_STATE || opcode == FCAM_OP_CP_CRANK_CONTROL);
        if (opcode == FCAM_OP_STATE) {
            state_call = ++kr_states; assert(!input && !input_bytes && capacity == 128);
            if ((state_call == 1 && (kr_is("before-error") || kr_is("before-error-retry"))) || (state_call == 2 && kr_is("after-error"))) return -EIO;
        } else {
            kr_models++; assert(input_bytes == 12 && capacity == 208 && !memcmp(input, kr_active, 12));
            if (kr_is("model-error")) return -EIO;
            if (kr_is("reentrant-dispatch")) kr_reenter();
        }
    }
    struct fcam_frame_proof before, after;
    assert(!fcam_model_proof_snapshot(kr_model, &before, sizeof before));
    struct fcam_exec_result actual = {0}; int rc = fcam_model_request(kr_model, opcode, input, input_bytes, output, capacity, &actual);
    if (rc) return rc;
    assert(!actual.token && !actual.total && !actual.offset && actual.used == capacity);
    assert(!fcam_model_proof_snapshot(kr_model, &after, sizeof after));
    if (opcode == FCAM_OP_STATE || opcode == FCAM_OP_CP_CRANK_CONTROL || opcode == FCAM_OP_CP_PARAMETER_BANK)
        assert(!memcmp(&before, &after, sizeof before));
    *result = (struct fcam_bridge_result){actual.used, actual.used, kr_instance, 0};
    if (opcode == FCAM_OP_CP_PARAMETER_BANK) {
        unsigned char query[FCAM_CP_PARAMETER_BANK_RESULT_BYTES];
        assert(!fcam_model_cp_parameter_bank_snapshot(kr_model, u64((unsigned char *)output+16), query, sizeof query));
        assert(!memcmp(query, output, sizeof query));
    }
    if (!kr_testing) return 0;
    unsigned char *p = output;
    if (opcode == FCAM_OP_CP_CRANK_CONTROL) {
        int i = kr_index("receipt-byte-"); if (i >= 0) { assert(i < 208); p[i] ^= 1; }
        i = kr_index("request-byte-"); if (i >= 0) { assert(i < 12); ((unsigned char *)kr_active)[i] ^= 1; }
        if (kr_is("model-overrun")) p[capacity] ^= 1;
        if (kr_is("result-short")) result->used--;
        if (kr_is("result-required")) result->required--;
        if (kr_is("result-token")) result->result_token = 1;
        if (kr_is("result-instance")) result->model_instance++;
        if (kr_is("model-positive")) return 1;
        if (kr_is("model-origin-mutation")) ((struct fcam_native_origin *)origin)->wire_fnv1a64 ^= 1;
        if (kr_is("model-input-mutation")) ((unsigned char *)input)[1] ^= 1;
        if (kr_is("model-bank-change")) { pthread_mutex_lock(&parameter_mutex); parameter_state.bank_generation++; pthread_mutex_unlock(&parameter_mutex); }
    } else {
        int i = kr_index(state_call == 1 ? "before-byte-" : "after-byte-");
        if (i >= 0) { assert(i < 128); p[i] ^= 1; }
        if ((state_call == 1 && kr_is("before-overrun")) || (state_call == 2 && kr_is("after-overrun"))) p[capacity] ^= 1;
        if (state_call == 1 && kr_is("before-result-instance")) result->model_instance++;
        if (state_call == 1 && kr_is("before-request-mutation")) ((unsigned char *)kr_active)[1] ^= 1;
        if (state_call == 1 && kr_is("before-generation-overflow")) memset(p+FCAM_S_GENERATION, 0xff, 8);
        if (state_call == 2 && kr_is("after-result-token")) result->result_token = 1;
    }
    return 0;
}
static void *kr_strict_boot(void *unused) {
    (void)unused; kr_strict_setup = 1; void *p = kr_request(0x80000027); int rc = 123;
    const struct native_cp_ee_controls_diagnostic_guard guard = {kr_reserve, kr_unreserve, kr_predecessors};
    assert(native_cp_ee_controls_diagnostic_dispatch(FUNCTIONAL_CAMERA_CONTROL_SID, p, &kr_io, &guard, 1, &rc) == 1 && !rc);
    assert(kr_ack && native_cp_ee_controls_diagnostic_release_reply(FUNCTIONAL_CAMERA_CONTROL_AP, kr_ack, kr_release, kr_log, &rc) == 1 && !rc);
    kr_ack = NULL; kr_strict_setup = 0; return NULL;
}
static void kr_control_request(int start) {
    unsigned char *p = kr_message(start ? 24 : 12, FUNCTIONAL_CAMERA_CONTROL_AP);
    p[0] = start ? 0 : 5; put16(p+2, start ? 0x3003 : 0x4073); put32(p+4, 0x80000026); if (!start) put32(p+8, 1);
    kr_active = p; int rc = 123;
    assert(native_functional_camera_control_dispatch(FUNCTIONAL_CAMERA_CONTROL_SID, p, &kr_io, &kr_guard, 1, &rc) == 1 && !rc);
    struct native_functional_camera_control_snapshot s; native_functional_camera_control_snapshot(&s);
    unsigned int index = start ? START_ACK : MODE_ACK; uint64_t cycle = s.lease_cycle_id[index];
    assert(native_functional_camera_control_observe_receive_cycle(FUNCTIONAL_CAMERA_CONTROL_AP, kr_ack, FUNCTIONAL_CAMERA_CONTROL_SID,
        start ? 16 : 12, cycle) == 1);
    assert(native_functional_camera_control_release_cycle(FUNCTIONAL_CAMERA_CONTROL_AP, kr_ack, kr_release, kr_log, &rc, cycle) == 1 && !rc); kr_ack = NULL;
    if (!start) {
        assert(native_functional_camera_control_observe_receive_cycle(FUNCTIONAL_CAMERA_CONTROL_AP, kr_notice, FUNCTIONAL_CAMERA_CONTROL_SID,
            CP_STATE_SNAPSHOT_BYTES, cycle) == 1);
        assert(native_functional_camera_control_release_cycle(FUNCTIONAL_CAMERA_CONTROL_AP, kr_notice, kr_release, kr_log, &rc, cycle) == 1 && !rc); kr_notice = NULL;
    }
    kr_active = NULL;
}
static void kr_commit_bank(uint32_t fps) {
    int testing = kr_testing; kr_testing = 0;
    kr_active = kr_bank_request(0x80000060, fps); kr_saved_bank_pointer = kr_active; int rc = 123;
    assert(native_functional_camera_parameter_dispatch(FUNCTIONAL_CAMERA_CONTROL_SID, kr_active, &kr_io, &kr_guard, 1, &rc) == 1 && !rc);
    struct native_functional_camera_parameter_snapshot bank; native_functional_camera_parameter_snapshot(&bank);
    assert(bank.model_committed && bank.verified && bank.request_freed && !bank.faults && bank.bank_generation);
    kr_active = NULL; kr_testing = testing;
}
static int kr_dispatch(void *p, const struct full_imaging_io *io, const struct native_cp_state_publication_guard *guard, int enabled, int *rc) {
    void *saved = kr_active; kr_active = p;
    int handled = native_functional_camera_crank_dispatch(FUNCTIONAL_CAMERA_CONTROL_SID, p, io, guard, enabled, rc);
    kr_active = saved; return handled;
}
static void kr_assert_complete(const unsigned char original[12], uint64_t bank, uint64_t crank) {
    struct native_functional_camera_crank_snapshot s = kr_view();
    assert(s.owned && s.verified && s.complete && s.model_called && s.model_committed && !s.faults && !s.error);
    assert(!s.busy && !s.guard_held && !s.retained_request && !s.retained_reply && s.request_freed && s.reply_freed && s.reply_received && s.reply_consumed);
    assert(s.bank_generation == bank && s.crank_generation == crank && s.last_bank_generation == bank && s.last_crank_generation == crank);
    assert(s.receiver_tid > 0 && s.sender_tid == s.reply_free_tid && s.sender_tid == s.request_free_tid);
    if (!strncmp(kr_case, "transport-", 10)) assert(s.receiver_tid != s.sender_tid);
    assert(s.sender_tid != kr_strict_saved.leases[0].sender_tid);
    assert(s.config_generation == s.before_config_generation+1 && s.fps == u32(s.before_state+FCAM_S_FPS));
    assert(!memcmp(s.request, original, 12) && !memcmp(s.receipt+192, original, 12) && !memcmp(s.receipt+64, s.after_state, 128));
    unsigned char expected[128]; memcpy(expected, s.before_state, 128);
    uint64_t generation = s.before_config_generation+1;
    for (unsigned int i = 0; i < 8; i++) expected[FCAM_S_GENERATION+i] = (unsigned char)(generation >> (8*i));
    assert(!memcmp(expected, s.after_state, 128));
    unsigned char reply[12] = {1,0,0x9d,0x40,0,0,0,0,0,0xf0,0,0}; memcpy(reply+4, original+4, 4);
    assert(!memcmp(reply, s.reply, 12) && s.reply_fnv1a64 == hash(reply, 12));
    assert(s.origin.wire_fnv1a64 == hash(original, 12) && s.receipt_fnv1a64 == hash(s.receipt, 208));
    assert(s.reply_pointer == s.allocation_pointer && s.request_pointer && s.reply_pointer);
    unsigned int frees = kr_frees; int rc = 123;
    assert(native_functional_camera_crank_release(FUNCTIONAL_CAMERA_CONTROL_SID, s.request_pointer, kr_release, kr_log, &rc, kr_request_ticket, NULL) == 1 && rc == -ESTALE);
    assert(native_functional_camera_crank_release(FUNCTIONAL_CAMERA_CONTROL_AP, s.reply_pointer, kr_release, kr_log, &rc, kr_ticket, NULL) == 1 && rc == -ESTALE && kr_frees == frees);
    void *old_route = kr_request(0x80000060);
    const struct native_cp_ee_controls_diagnostic_guard guard = {kr_reserve, kr_unreserve, kr_predecessors};
    assert(native_cp_ee_controls_diagnostic_dispatch(FUNCTIONAL_CAMERA_CONTROL_SID, old_route, &kr_io, &guard, 1, &rc) == 1 && rc == CP_EE_CONTROLS_SOURCE_BLOCKED);
    struct native_cp_ee_controls_diagnostic_snapshot strict; native_cp_ee_controls_diagnostic_snapshot(&strict);
    assert(!memcmp(&strict, &kr_strict_saved, sizeof strict)); kr_drop(old_route);
}
static void *kr_foreign_free(void *p) {
    int rc = 123;
    assert(native_functional_camera_crank_release(FUNCTIONAL_CAMERA_CONTROL_AP, p, kr_release, kr_log, &rc, kr_ticket, NULL) == 1 && rc == -EPERM); return NULL;
}
static void *kr_new_sender(void *p) {
    unsigned char original[12]; memcpy(original, p, 12); int rc = 123;
    assert(kr_dispatch(p, &kr_io, &kr_guard, 1, &rc) == 1 && !rc); kr_retire_reply(kr_reply, kr_ticket); kr_assert_complete(original, 1, 1); return NULL;
}
static void kr_finish(void) {
    assert(!kr_held); fcam_model_destroy(kr_model);
    for (unsigned int i = 0; i < 96; i++) free(kr_packets[i]);
}
int main(int argc, char **argv) {
    assert(argc == 2); kr_case = argv[1]; av_log_set_level(AV_LOG_ERROR);
    assert(!native_functional_camera_control_owner_init()); assert(!native_functional_camera_parameter_owner_init());
    assert(!native_functional_camera_crank_owner_init()); assert(native_functional_camera_crank_owner_init() == -EALREADY);
    assert(!native_cp_ee_controls_diagnostic_owner_init());
    pthread_t thread; assert(!pthread_create(&thread, NULL, kr_strict_boot, NULL)); assert(!pthread_join(thread, NULL));
    native_cp_ee_controls_diagnostic_snapshot(&kr_strict_saved);
    assert(kr_strict_saved.leases[0].attempts == 1 && kr_strict_saved.leases[0].requests == 1 && kr_strict_saved.leases[0].clean_completion);
    kr_model = fcam_model_create(kr_instance); assert(kr_model);
    kr_control_request(1); kr_control_request(0);
    if (!kr_is("cold")) kr_commit_bank(30);
    struct native_functional_camera_control_snapshot control; native_functional_camera_control_snapshot(&control);
    struct native_functional_camera_parameter_snapshot bank; native_functional_camera_parameter_snapshot(&bank);
    void *p = kr_request(kr_is("cookie-zero") ? 0 : kr_is("cookie-max") ? UINT32_MAX : UINT32_C(0x80000060));
    if (kr_is("opaque-byte1")) ((unsigned char *)p)[1] = 0xa5;
    unsigned char original[12]; memcpy(original, p, 12);
    struct full_imaging_io io = kr_io; const struct native_cp_state_publication_guard *guard = &kr_guard;
    if (kr_is("missing-release")) io.release = NULL;
    if (kr_is("missing-allocate")) io.allocate = NULL;
    if (kr_is("missing-send")) io.send = NULL;
    if (kr_is("missing-guard")) guard = NULL;
    if (kr_is("wrong-source")) kr_packet(p)->source++;
    if (kr_is("short")) kr_packet(p)->bytes--;
    if (kr_is("long")) kr_packet(p)->bytes++;
    if (kr_is("wrong-type")) ((unsigned char *)p)[0] = 0;
    if (kr_is("unrelated")) ((unsigned char *)p)[2] ^= 1;
    if (kr_is("mode1")) put32((unsigned char *)p+8, 1);
    if (kr_is("mode-wide")) put32((unsigned char *)p+8, UINT32_MAX);
    if (kr_is("bank-retained")) parameter_state.retained_request = p;
    if (kr_is("bank-not-freed")) parameter_state.request_freed = 0;
    if (kr_is("bank-fault")) parameter_state.faults = 1;
    if (kr_is("bank-not-verified")) parameter_state.verified = 0;
    if (kr_is("bank-wrong-instance")) parameter_state.model_instance++;
    if (kr_is("bank-receipt-mutation")) parameter_state.receipt[200] ^= 1;
    if (kr_is("current-mode-live")) state.mode_complete = 0;
    if (kr_is("transaction-overflow")) crank_state.transaction = UINT64_MAX;
    if (kr_is("crank-generation-overflow")) crank_state.last_crank_generation = UINT64_MAX;
    kr_testing = 1; kr_fail_request = kr_is("request-free-fail"); kr_fail_reply = kr_is("reply-free-fail");
    if (kr_is("fork-held-lock")) {
        pthread_mutex_lock(&mutex); pthread_mutex_lock(&parameter_mutex); pthread_mutex_lock(&crank_mutex); pid_t child = fork(); assert(child >= 0);
        if (!child) { int rc = 123; assert(kr_dispatch(p, &io, guard, 1, &rc) == 1 && rc == -EXDEV); _exit(0); }
        pthread_mutex_unlock(&crank_mutex); pthread_mutex_unlock(&parameter_mutex); pthread_mutex_unlock(&mutex);
        int status; assert(waitpid(child, &status, 0) == child && WIFEXITED(status) && !WEXITSTATUS(status)); kr_finish(); return 0;
    }
    if (kr_is("new-sender")) {
        assert(!pthread_create(&thread, NULL, kr_new_sender, p)); assert(!pthread_join(thread, NULL)); kr_finish(); return 0;
    }
    int rc = 123;
    if (kr_is("before-error-retry")) {
        assert(kr_dispatch(p, &io, guard, 1, &rc) == 1 && rc == -EIO && !kr_models && !kr_view().faults && !kr_view().owned);
        rc = 123;
    }
    int handled = kr_is("wrong-destination") ? native_functional_camera_crank_dispatch(FUNCTIONAL_CAMERA_CONTROL_SID+1, p, &io, guard, 1, &rc) :
        kr_dispatch(p, &io, guard, !kr_is("disabled"), &rc);
    struct native_functional_camera_crank_snapshot s = kr_view();
    assert(!s.busy && !s.guard_held && !kr_held);
    struct native_cp_ee_controls_diagnostic_snapshot strict; native_cp_ee_controls_diagnostic_snapshot(&strict);
    assert(!memcmp(&strict, &kr_strict_saved, sizeof strict));
    struct native_functional_camera_control_snapshot after_control; native_functional_camera_control_snapshot(&after_control);
    if (!kr_is("current-mode-live")) assert(!memcmp(&control, &after_control, sizeof control));
    struct native_functional_camera_parameter_snapshot after_bank; native_functional_camera_parameter_snapshot(&after_bank);
    if (strncmp(kr_case, "bank-", 5) && !kr_is("model-bank-change")) assert(!memcmp(&bank, &after_bank, sizeof bank));
    int must_own = kr_is("success") || kr_is("opaque-byte1") || kr_is("cookie-zero") || kr_is("cookie-max") ||
        kr_is("inline-free") || kr_is("allocation-param-reuse") || kr_is("completed-reuse") || kr_is("completed-reply-reuse") || kr_is("duplicate-bank") || kr_is("repeat-new-bank") ||
        kr_is("reentrant-dispatch") || kr_is("reentrant-metadata") || kr_is("reentrant-free") || kr_is("reentrant-request-early") || kr_is("guard-release-reentry") || kr_is("before-error-retry") ||
        !strncmp(kr_case, "allocation-", 11) || kr_is("reply-source-set") || kr_is("send-fail") || kr_is("inline-send-fail") ||
        !strncmp(kr_case, "request-free-", 13) || !strncmp(kr_case, "reply-free-", 11) || !strncmp(kr_case, "receive-", 8) ||
        kr_is("stale-receive") || kr_is("stale-free") || kr_is("foreign-pointer") || kr_is("foreign-free") || !strncmp(kr_case, "transport-", 10) ||
        kr_is("free-before-receive") || kr_is("duplicate-receive") || kr_is("predecessor-lost-5") || kr_is("predecessor-lost-6");
    if (must_own) assert(handled == 1 && !rc && s.owned && s.verified && s.model_committed);
    if (kr_index("receipt-byte-") >= 0 || kr_index("request-byte-") >= 0)
        assert(handled == 1 && rc < 0 && kr_models == 1 && s.model_committed && s.model_rc == 0 && s.faults && !s.verified && !s.owned);
    if (kr_index("before-byte-") >= 0) assert(handled == 1 && rc < 0 && kr_states == 1 && !kr_models && !s.owned);
    if (kr_index("after-byte-") >= 0) assert(handled == 1 && rc < 0 && kr_states == 2 && kr_models == 1 && s.model_committed && s.model_rc == 0 && s.faults && !s.owned);
    if (!handled) {
        assert(kr_is("cold") || kr_is("disabled") || kr_is("wrong-type") || kr_is("wrong-destination") || kr_is("unrelated"));
        assert(rc == 123 && !kr_states && !kr_models && !kr_allocations && !kr_sends); kr_finish(); return 0;
    }
    if (!s.owned) {
        assert(rc < 0 && !s.retained_request && !s.retained_reply && !s.request_freed && !kr_allocations && !kr_sends);
        if (kr_models) {
            assert(s.model_called && s.faults);
            assert(s.model_committed == (s.model_rc == 0));
            assert(!s.reply[0] && !s.reply_fnv1a64);
            unsigned int calls = kr_models, states = kr_states; int retry = 123;
            void *q = kr_request(8); assert(kr_dispatch(q, &kr_io, &kr_guard, 1, &retry) == 1 && retry < 0);
            assert(kr_models == calls && kr_states == states); kr_drop(q);
        }
        kr_finish(); return 0;
    }
    assert(!rc && s.model_committed && s.verified && s.commits == 1 && s.verified_commits == 1 && kr_models == 1);
    assert(kr_states == (kr_is("before-error-retry") ? 3u : 2u));
    unsigned int zero_frees = kr_frees; int zero_rc = 123;
    if (s.retained_request) assert(native_functional_camera_crank_release(FUNCTIONAL_CAMERA_CONTROL_SID, s.retained_request,
        kr_release, kr_log, &zero_rc, 0, NULL) == 1 && zero_rc == -ESTALE);
    if (s.retained_reply) assert(native_functional_camera_crank_release(FUNCTIONAL_CAMERA_CONTROL_AP, s.retained_reply,
        kr_release, kr_log, &zero_rc, 0, NULL) == 1 && zero_rc == -ESTALE);
    assert(kr_frees == zero_frees);
    if (s.faults) {
        assert(!s.complete && !s.reply_consumed && (s.retained_request || s.retained_reply || s.reply_alias || s.reply_freed));
        assert(s.model_rc == 0);
        if (kr_is("request-free-fail") || kr_is("request-free-wire") || kr_is("request-free-source") || kr_is("request-free-size")) {
            unsigned int frees = kr_frees; int freed = 123;
            assert(native_functional_camera_crank_release(FUNCTIONAL_CAMERA_CONTROL_SID, p, kr_release, kr_log, &freed, kr_request_ticket+1, NULL) == 1 && freed == -ESTALE && kr_frees == frees);
            kr_fail_request = 0; kr_packet(p)->bytes = 12; kr_packet(p)->source = FUNCTIONAL_CAMERA_CONTROL_AP; memcpy(p, original, 12);
            assert(native_functional_camera_crank_release(FUNCTIONAL_CAMERA_CONTROL_SID, p, kr_release, kr_log, &freed, kr_request_ticket, NULL) == 1 && !freed);
            assert(kr_view().request_freed && kr_view().faults && !kr_view().complete);
        }
        if (s.retained_reply && !s.reply_send_started) {
            int freed = 123; assert(native_functional_camera_crank_release(FUNCTIONAL_CAMERA_CONTROL_AP, s.retained_reply, kr_release, kr_log, &freed, kr_ticket, NULL) == 1 && !freed);
            assert(kr_view().reply_cleanup_freed && !kr_view().reply_freed && !kr_view().reply_consumed && kr_view().faults);
        }
        kr_finish(); return 0;
    }
    if (kr_is("stale-receive") || kr_is("stale-free") || kr_is("foreign-pointer")) {
        unsigned int frees = kr_frees; int observed = 123;
        const struct native_functional_camera_crank_receive event = {FUNCTIONAL_CAMERA_CONTROL_SID, 12};
        void *q = kr_is("foreign-pointer") ? kr_request(0) : kr_reply;
        uint64_t ticket = kr_is("foreign-pointer") ? kr_ticket : kr_ticket+1;
        assert(native_functional_camera_crank_release(FUNCTIONAL_CAMERA_CONTROL_AP, q, kr_release, kr_log, &observed,
            ticket, kr_is("stale-free") || kr_is("foreign-pointer") ? NULL : &event) == 1 && observed < 0 && kr_frees == frees);
        if (kr_is("foreign-pointer")) kr_drop(q);
    }
    if (kr_is("receive-wrong-source") || kr_is("receive-wrong-size") || kr_is("receive-wrong-destination") || kr_is("receive-wire") ||
        kr_is("receive-metadata-source") || kr_is("receive-metadata-size") || kr_is("free-before-receive")) {
        int observed = 123; struct native_functional_camera_crank_receive event = {FUNCTIONAL_CAMERA_CONTROL_SID, 12};
        if (kr_is("receive-wrong-source")) event.source++;
        if (kr_is("receive-wrong-size")) event.bytes--;
        if (kr_is("receive-wire")) ((unsigned char *)kr_reply)[1] ^= 1;
        if (kr_is("receive-metadata-source")) kr_packet(kr_reply)->source++;
        if (kr_is("receive-metadata-size")) kr_packet(kr_reply)->bytes--;
        assert(native_functional_camera_crank_release(FUNCTIONAL_CAMERA_CONTROL_AP+(unsigned int)kr_is("receive-wrong-destination"), kr_reply,
            kr_release, kr_log, &observed, kr_ticket, kr_is("free-before-receive") ? NULL : &event) == 1 && observed < 0);
        assert(kr_view().faults && kr_view().retained_reply == kr_reply && !kr_view().reply_freed && !kr_view().complete); kr_finish(); return 0;
    }
    if (kr_is("transport-receive-sender-free") || kr_is("transport-receive-foreign-free")) kr_transport_deliver(kr_reply, kr_ticket);
    if (kr_is("transport-receive-foreign-free")) {
        assert(!pthread_create(&thread, NULL, kr_foreign_free, kr_reply)); assert(!pthread_join(thread, NULL));
        assert(kr_view().receiver_tid > 0 && kr_view().receiver_tid != kr_view().sender_tid && kr_view().faults &&
            kr_view().retained_reply == kr_reply && !kr_view().reply_freed && !kr_view().reply_consumed && !kr_view().complete);
        kr_finish(); return 0;
    }
    if (!s.reply_freed) {
        if (kr_is("duplicate-receive") || kr_is("foreign-free") || kr_is("reply-free-fail") || kr_is("reply-free-wire")) {
            int observed = 123; const struct native_functional_camera_crank_receive event = {FUNCTIONAL_CAMERA_CONTROL_SID, 12};
            assert(native_functional_camera_crank_release(FUNCTIONAL_CAMERA_CONTROL_AP, kr_reply, NULL, kr_log, &observed, kr_ticket, &event) == 1 && !observed);
            if (kr_is("duplicate-receive")) assert(native_functional_camera_crank_release(FUNCTIONAL_CAMERA_CONTROL_AP, kr_reply, NULL, kr_log, &observed, kr_ticket, &event) == 1 && observed < 0);
            else if (kr_is("foreign-free")) { assert(!pthread_create(&thread, NULL, kr_foreign_free, kr_reply)); assert(!pthread_join(thread, NULL)); }
            else {
                if (kr_is("reply-free-wire")) ((unsigned char *)kr_reply)[1] ^= 1;
                assert(native_functional_camera_crank_release(FUNCTIONAL_CAMERA_CONTROL_AP, kr_reply, kr_release, kr_log, &observed, kr_ticket, NULL) == 1 && observed < 0);
                assert(kr_view().retained_reply == kr_reply && !kr_view().reply_freed);
                kr_fail_reply = 0; memcpy(kr_reply, kr_view().reply, 12);
                assert(native_functional_camera_crank_release(FUNCTIONAL_CAMERA_CONTROL_AP, kr_reply, kr_release, kr_log, &observed, kr_ticket, NULL) == 1 && !observed);
            }
            assert(kr_view().faults && !kr_view().reply_consumed && !kr_view().complete); kr_finish(); return 0;
        }
        if (kr_is("transport-receive-sender-free") || kr_is("transport-during-request-free")) {
            int freed = 123; assert(kr_view().reply_received && kr_view().receiver_tid != kr_view().sender_tid);
            assert(native_functional_camera_crank_release(FUNCTIONAL_CAMERA_CONTROL_AP, kr_reply, kr_release, kr_log, &freed, kr_ticket, NULL) == 1 && !freed);
        } else kr_retire_reply(kr_reply, kr_ticket);
    }
    kr_assert_complete(original, 1, 1);
    if (kr_is("completed-reuse") || kr_is("completed-reply-reuse")) {
        s = kr_view(); unsigned int destination = kr_is("completed-reuse") ? FUNCTIONAL_CAMERA_CONTROL_SID : FUNCTIONAL_CAMERA_CONTROL_AP;
        void *q = kr_reuse(kr_is("completed-reuse") ? s.request_pointer : s.reply_pointer, 12, FUNCTIONAL_CAMERA_CONTROL_AP); int freed = 123;
        assert(native_functional_camera_crank_release(destination, q, kr_release, kr_log, &freed, kr_request_ticket, NULL) == 1 && freed == -ESTALE);
        assert(!native_functional_camera_crank_release(destination, q, kr_release, kr_log, &freed, 0, NULL));
        assert(!kr_release(destination, q));
    }
    if (kr_is("duplicate-bank") || kr_is("repeat-new-bank")) {
        unsigned int calls = kr_models, states = kr_states; void *q = kr_request(0x80000060); int retry = 123;
        assert(kr_dispatch(q, &kr_io, &kr_guard, 1, &retry) == 1 && retry == -ESTALE && kr_models == calls && kr_states == states); kr_drop(q);
        if (kr_is("repeat-new-bank")) {
            uint64_t old_ticket = kr_ticket; void *old_pointer = kr_view().reply_pointer;
            kr_commit_bank(60); q = kr_request(0x80000060); memcpy(original, q, 12);
            assert(kr_dispatch(q, &kr_io, &kr_guard, 1, &retry) == 1 && !retry);
            int stale = 123; assert(native_functional_camera_crank_release(FUNCTIONAL_CAMERA_CONTROL_AP, old_pointer, kr_release, kr_log, &stale, old_ticket, NULL) == 1 && stale == -ESTALE);
            kr_retire_reply(kr_reply, kr_ticket); kr_assert_complete(original, 2, 2);
            assert(kr_view().commits == 2 && kr_view().completions == 2 && kr_view().fps == 60);
        }
    }
    native_cp_ee_controls_diagnostic_snapshot(&strict); assert(!memcmp(&strict, &kr_strict_saved, sizeof strict));
    assert(!kr_strict_setup); kr_finish(); puts("PASS crank real-Core component; original AP/physical/capture unverified"); return 0;
}
#elif defined(FCAM_PARAMETER_BANK_TEST)
#define _GNU_SOURCE
#ifndef HOST_TEST
#error Component fixture only
#endif
#include "functional-camera-control.c"
#include "../../../report/functional-camera-core/functional-camera-core.h"
#include <assert.h>
#include <stdlib.h>
#include <sys/wait.h>
#include <libavutil/log.h>

/* Actual Core OP20 and State128; OSAL/guard/bridge are host fixtures. */
struct pb_packet { void *next; unsigned int flags, source, bytes, reserved; unsigned char body[]; };
_Static_assert(offsetof(struct pb_packet, body) == 24, "original OSAL metadata");
static struct pb_packet *pb_live[16];
static struct fcam_model *pb_model;
static const char *pb_case;
static void *pb_active, *pb_ack, *pb_notice;
static unsigned int pb_allocations, pb_sends, pb_frees, pb_states, pb_banks, pb_ready_calls;
static int pb_held, pb_testing, pb_reentered, pb_fail_free, pb_mutated_at_free;
static const uint64_t pb_instance = UINT64_C(0x123456789abcde);
static const struct full_imaging_io pb_io;
static const struct native_cp_state_publication_guard pb_guard;
static int pb_is(const char *name) { return !strcmp(pb_case, name); }
static void pb_put64(unsigned char *p, uint64_t value) { put32(p, (uint32_t)value); put32(p+4, (uint32_t)(value >> 32)); }
static struct pb_packet *pb_envelope(void *p) { return (struct pb_packet *)((unsigned char *)p - offsetof(struct pb_packet, body)); }
static void *pb_message(unsigned int bytes, unsigned int source) {
    struct pb_packet *p = calloc(1, sizeof *p + bytes); assert(p); p->source = source; p->bytes = bytes;
    for (unsigned int i = 0; i < 16; i++) if (!pb_live[i]) { pb_live[i] = p; return p->body; }
    assert(0); return NULL;
}
static void pb_drop(void *body) {
    for (unsigned int i = 0; i < 16; i++) if (pb_live[i] && pb_live[i]->body == body) { free(pb_live[i]); pb_live[i] = NULL; return; }
    assert(0);
}
static void *pb_request(uint32_t cookie, uint32_t fps) {
    unsigned char *p = pb_message(FCAM_CP_PARAMETER_BANK_BYTES, FUNCTIONAL_CAMERA_CONTROL_AP);
    p[0] = 5; put16(p+2, 0x4063); put32(p+4, cookie);
    for (unsigned int i = 0; i < CP_PARAMETER_BATCH_SLOTS; i++) {
        const struct cp_parameter_batch_slot s = cp_parameter_batch_slots[i];
        p[s.offset] = 5; put16(p+s.offset+2, s.opcode); put32(p+s.offset+4, UINT32_C(0x80000000) + i);
        for (unsigned int j = 8; j < s.size; j++) p[s.offset+j] = (unsigned char)(i+j);
    }
    put32(p+0x86c, fps); return p;
}
static unsigned int pb_size(void *p) { struct native_functional_camera_parameter_snapshot s; native_functional_camera_parameter_snapshot(&s); return pb_envelope(p)->bytes; }
static unsigned int pb_source(void *p) { return pb_envelope(p)->source; }
static void pb_set_source(void *p, unsigned int source) { pb_envelope(p)->source = source; }
static void pb_reenter(void) {
    if (pb_reentered) return;
    pb_reentered = 1; void *again = pb_request(7, 30); int rc = 123;
    unsigned int banks = pb_banks, states = pb_states;
    assert(native_functional_camera_parameter_dispatch(FUNCTIONAL_CAMERA_CONTROL_SID, again, &pb_io, &pb_guard, 1, &rc) == 1 && rc < 0);
    assert(pb_banks == banks && pb_states == states); pb_drop(again);
}
static int pb_release(unsigned int destination, void *p) {
    assert(destination == FUNCTIONAL_CAMERA_CONTROL_SID || destination == FUNCTIONAL_CAMERA_CONTROL_AP);
    if (pb_testing && pb_is("reentrant-free")) {
        struct native_functional_camera_parameter_snapshot s; native_functional_camera_parameter_snapshot(&s);
        int rc = 123;
        assert(native_functional_camera_parameter_release(destination, p, pb_release, NULL, &rc, s.transaction) == 1 && rc == -EBUSY);
    }
    if (pb_testing && pb_fail_free) return -EIO;
    pb_frees++; pb_drop(p); return 0;
}
static int pb_allocate(unsigned int destination, void **p, unsigned int bytes, unsigned int option) {
    assert(destination == FUNCTIONAL_CAMERA_CONTROL_AP && option == 1); pb_allocations++;
    *p = pb_message(bytes, 0); return 0;
}
static int pb_send(unsigned int destination, void *p) {
    assert(destination == FUNCTIONAL_CAMERA_CONTROL_AP); pb_sends++;
    if (pb_size(p) == CP_STATE_SNAPSHOT_BYTES) pb_notice = p; else pb_ack = p;
    return 0;
}
static void pb_log(const char *tag, const char *text) {
    if (strncmp(tag, "FUNCTIONAL_CP_PARAMETER_BANK_", sizeof "FUNCTIONAL_CP_PARAMETER_BANK_" - 1)) return;
    printf("%s%s\n", tag, text);
    if (pb_testing && strstr(text, "event=VERIFIED ") &&
        (pb_is("free-metadata-mutation") || pb_is("free-wire-mutation"))) {
        pb_mutated_at_free = 1;
        if (pb_is("free-metadata-mutation")) pb_envelope(pb_active)->bytes--;
        else ((unsigned char *)pb_active)[FCAM_CP_PARAMETER_BANK_BYTES-1] ^= 1;
    }
}
static int pb_reserve(void) { assert(!pb_held); if (pb_testing && pb_is("guard-fail")) return -EBUSY; pb_held = 1; return 0; }
static void pb_unreserve(void) {
    assert(pb_held);
    if (pb_testing && (pb_is("guard-release-reentry") || pb_is("commit-error-reentry"))) pb_reenter();
    pb_held = 0;
}
static int pb_predecessors(void) {
    assert(pb_held); if (!pb_testing) return 1; pb_ready_calls++;
    return !pb_is("predecessor-fail") && !(pb_is("predecessor-lost-before") && pb_ready_calls >= 2) &&
        !(pb_is("predecessor-lost-after") && pb_ready_calls >= 3);
}
static const struct full_imaging_io pb_io = {pb_allocate, pb_release, pb_set_source, pb_send, pb_size, pb_source, pb_log};
static const struct native_cp_state_publication_guard pb_guard = {pb_reserve, pb_unreserve, pb_predecessors};
int fcam_bridge_call(const struct fcam_native_origin *origin, uint32_t opcode,
    const void *input, size_t input_bytes, void *output, size_t capacity, struct fcam_bridge_result *result) {
    assert(pb_held && pb_model && origin && pb_active);
    assert(origin->source == FUNCTIONAL_CAMERA_CONTROL_AP && origin->destination == FUNCTIONAL_CAMERA_CONTROL_SID);
    assert(origin->bytes == pb_size(pb_active) && origin->command == u16((unsigned char *)pb_active+2));
    assert(origin->wire_fnv1a64 == hash(pb_active, origin->bytes));
    unsigned int state_call = 0;
    if (pb_testing) {
        assert(origin->command == 0x4063 && origin->bytes == FCAM_CP_PARAMETER_BANK_BYTES);
        assert(opcode == FCAM_OP_STATE || opcode == FCAM_OP_CP_PARAMETER_BANK);
        if (opcode == FCAM_OP_STATE) {
            state_call = ++pb_states;
            if (((pb_is("before-error") || pb_is("before-error-retry")) && state_call == 1) ||
                (pb_is("after-error") && state_call == 2)) return -EIO;
            assert(!input && !input_bytes && capacity == FCAM_STATE_BYTES);
        } else {
            pb_banks++; assert(input_bytes == FCAM_CP_PARAMETER_BANK_BYTES && capacity == FCAM_CP_PARAMETER_BANK_RESULT_BYTES);
            assert(!memcmp(input, pb_active, input_bytes) && hash(input, input_bytes) == origin->wire_fnv1a64);
            if (pb_is("bank-error")) return -EIO;
            if (pb_is("reentrant-dispatch")) pb_reenter();
        }
    }
    struct fcam_exec_result actual = {0};
    struct fcam_frame_proof before, after;
    assert(!fcam_model_proof_snapshot(pb_model, &before, sizeof before));
    int rc = fcam_model_request(pb_model, opcode, input, input_bytes, output, capacity, &actual);
    if (rc) return rc;
    assert(!actual.token && !actual.total && !actual.offset && actual.used == capacity);
    assert(!fcam_model_proof_snapshot(pb_model, &after, sizeof after));
    if (opcode == FCAM_OP_STATE) assert(!memcmp(&before, &after, sizeof before));
    *result = (struct fcam_bridge_result){actual.used, actual.used, pb_instance, 0};
    unsigned char *p = output;
    if (!pb_testing) return 0;
    if (opcode == FCAM_OP_CP_PARAMETER_BANK) {
        if (pb_is("commit-error") || pb_is("commit-error-reentry")) return -EIO;
        if (pb_is("bank-positive-error")) return 1;
        if (pb_is("bank-overrun")) p[capacity] ^= 1;
        if (pb_is("result-short")) result->used--;
        if (pb_is("result-required")) result->required--;
        if (pb_is("result-token")) result->result_token = 1;
        if (pb_is("result-instance")) result->model_instance++;
        if (pb_is("result-version")) p[0] ^= 1;
        if (pb_is("result-size")) p[4] ^= 1;
        if (pb_is("result-bank-generation")) p[16] ^= 1;
        if (pb_is("result-before-generation")) p[24] ^= 1;
        if (pb_is("result-generation")) p[32] ^= 1;
        if (pb_is("result-input-fnv")) p[40] ^= 1;
        if (pb_is("result-fps")) p[48] ^= 1;
        if (pb_is("result-slots")) p[52] ^= 1;
        if (pb_is("result-input-size")) p[56] ^= 1;
        if (pb_is("result-reserved")) p[60] = 1;
        if (pb_is("result-frame")) p[FCAM_CP_PARAMETER_BANK_STATE_OFFSET+FCAM_S_FRAME_GENERATION] ^= 1;
        if (pb_is("result-embedded-config")) p[FCAM_CP_PARAMETER_BANK_STATE_OFFSET+FCAM_S_QUALITY] ^= 1;
        if (pb_is("result-cookie")) p[FCAM_CP_PARAMETER_BANK_READBACK_OFFSET+4] ^= 1;
        if (pb_is("result-tail")) p[capacity-1] ^= 1;
        if (pb_is("input-mutation")) ((unsigned char *)input)[input_bytes-1] ^= 1;
        if (pb_is("origin-mutation")) ((struct fcam_native_origin *)origin)->wire_fnv1a64 ^= 1;
        if (pb_is("bank-request-mutation")) ((unsigned char *)pb_active)[FCAM_CP_PARAMETER_BANK_BYTES-1] ^= 1;
    } else if (state_call == 1) {
        if (pb_is("before-overrun")) p[capacity] ^= 1;
        if (pb_is("before-instance")) p[FCAM_S_INSTANCE] ^= 1;
        if (pb_is("before-abi")) p[FCAM_S_ABI] ^= 1;
        if (pb_is("before-capabilities")) p[FCAM_S_CAPS] ^= 1;
        if (pb_is("before-pending")) put32(p+FCAM_S_PENDING_RESULTS, 1);
        if (pb_is("before-streaming")) put32(p+FCAM_S_STREAM_STATE, 1);
        if (pb_is("before-generation-overflow")) pb_put64(p+FCAM_S_GENERATION, UINT64_MAX);
        if (pb_is("before-request-mutation")) ((unsigned char *)pb_active)[FCAM_CP_PARAMETER_BANK_BYTES-1] ^= 1;
        if (pb_is("before-source-mutation")) pb_envelope(pb_active)->source++;
    } else {
        if (pb_is("after-overrun")) p[capacity] ^= 1;
        if (pb_is("after-instance")) p[FCAM_S_INSTANCE] ^= 1;
        if (pb_is("after-generation")) p[FCAM_S_GENERATION] ^= 1;
        if (pb_is("after-fps")) p[FCAM_S_FPS] ^= 1;
        if (pb_is("after-counter")) p[FCAM_S_RESULT_READ] ^= 1;
    }
    return 0;
}
static void pb_retire_ack(void) {
    struct native_functional_camera_control_snapshot s; native_functional_camera_control_snapshot(&s);
    unsigned int index = pb_size(pb_ack) == 16 ? START_ACK : MODE_ACK;
    uint64_t cycle = s.lease_cycle_id[index]; int rc = 123;
    assert(native_functional_camera_control_observe_receive_cycle(FUNCTIONAL_CAMERA_CONTROL_AP, pb_ack,
        FUNCTIONAL_CAMERA_CONTROL_SID, pb_size(pb_ack), cycle) == 1);
    assert(native_functional_camera_control_release_cycle(FUNCTIONAL_CAMERA_CONTROL_AP, pb_ack, pb_release, pb_log, &rc, cycle) == 1 && !rc);
    pb_ack = NULL;
}
static void pb_retire_notice(void) {
    struct native_functional_camera_control_snapshot s; native_functional_camera_control_snapshot(&s); int rc = 123;
    assert(native_functional_camera_control_observe_receive_cycle(FUNCTIONAL_CAMERA_CONTROL_AP, pb_notice,
        FUNCTIONAL_CAMERA_CONTROL_SID, CP_STATE_SNAPSHOT_BYTES, s.lease_cycle_id[FULL_NOTICE]) == 1);
    assert(native_functional_camera_control_release_cycle(FUNCTIONAL_CAMERA_CONTROL_AP, pb_notice, pb_release, pb_log, &rc,
        s.lease_cycle_id[FULL_NOTICE]) == 1 && !rc); pb_notice = NULL;
}
static void pb_control_request(int start, unsigned int selector) {
    unsigned char *p = pb_message(start ? 24 : 12, FUNCTIONAL_CAMERA_CONTROL_AP);
    p[0] = start ? 0 : 5; put16(p+2, start ? 0x3003 : 0x4073); put32(p+4, 0x80000026);
    if (!start) put32(p+8, selector);
    pb_active = p; int rc = 123;
    assert(native_functional_camera_control_dispatch(FUNCTIONAL_CAMERA_CONTROL_SID, p, &pb_io, &pb_guard, 1, &rc) == 1 && !rc);
    pb_active = NULL;
}
static void pb_advance(void) {
    unsigned char bytes[128], config[48] = {0}; struct fcam_exec_result r;
    assert(!fcam_model_request(pb_model, FCAM_OP_STATE, NULL, 0, bytes, sizeof bytes, &r));
    memcpy(config, bytes+8, 40); put32(config+8, 60);
    assert(!fcam_model_request(pb_model, FCAM_OP_CONFIGURE, config, sizeof config, bytes, sizeof bytes, &r));
}
static int pb_dispatch(void *p, const struct full_imaging_io *io, const struct native_cp_state_publication_guard *guard, int enabled, int *rc) {
    pb_active = p; int handled = native_functional_camera_parameter_dispatch(FUNCTIONAL_CAMERA_CONTROL_SID, p, io, guard, enabled, rc);
    pb_active = NULL; return handled;
}
static void *pb_foreign_thread(void *p) { int rc = 123; assert(pb_dispatch(p, &pb_io, &pb_guard, 1, &rc) == 1 && rc < 0); return NULL; }
static void pb_finish(void) { assert(!pb_held); fcam_model_destroy(pb_model); for (unsigned int i = 0; i < 16; i++) free(pb_live[i]); }
int main(int argc, char **argv) {
    assert(argc == 2); pb_case = argv[1]; av_log_set_level(AV_LOG_ERROR);
    assert(!native_functional_camera_control_owner_init()); assert(!native_functional_camera_parameter_owner_init());
    assert(native_functional_camera_parameter_owner_init() == -EALREADY);
    struct cp_parameter_batch initial, saved_initial;
    assert(!cp_parameter_batch_init(&initial, true));
    void *boot = pb_request(0x80000026, 60);
    assert(cp_parameter_batch_stage(&initial, FUNCTIONAL_CAMERA_CONTROL_AP, FUNCTIONAL_CAMERA_CONTROL_SID, boot,
        FCAM_CP_PARAMETER_BANK_BYTES) == CP_PARAMETER_BATCH_STAGED); saved_initial = initial; pb_drop(boot);
    pb_model = fcam_model_create(pb_instance); assert(pb_model);
    if (!pb_is("cold")) {
        pb_control_request(1, 0);
        if (!pb_is("pending-start")) pb_retire_ack();
        if (!pb_is("pending-start") && !pb_is("before-mode1")) {
            pb_control_request(0, 1);
            if (!pb_is("pending-ack")) pb_retire_ack();
            if (!pb_is("pending-notice")) pb_retire_notice();
        }
        if (pb_is("notice-before-zero-ack")) {
            pb_advance(); pb_control_request(0, 0); pb_retire_notice();
            struct native_functional_camera_control_snapshot s; native_functional_camera_control_snapshot(&s);
            assert(s.mode1_complete && !s.mode_complete && s.notification_ap_consumed && pb_ack);
        }
        if (pb_is("live-state22")) {
            for (unsigned int i = 0; i < 20; i++) pb_advance();
            pb_control_request(0, 1); pb_retire_ack(); pb_retire_notice();
            pb_advance();
        }
    }
    struct native_functional_camera_control_snapshot control_before = {0}, control_after = {0};
    native_functional_camera_control_snapshot(&control_before);
    if (pb_is("live-state22")) assert(control_before.config_generation == 21);
    void *p = pb_request(pb_is("cookie-wrap") ? UINT32_MAX : UINT32_C(0x80000061), 30);
    unsigned char original[FCAM_CP_PARAMETER_BANK_BYTES]; memcpy(original, p, sizeof original);
    int rc = 123; unsigned int allocations = pb_allocations, sends = pb_sends, frees = pb_frees;
    if (pb_is("fork-held-lock")) {
        pthread_mutex_lock(&mutex); pthread_mutex_lock(&parameter_mutex); pid_t child = fork(); assert(child >= 0);
        if (!child) { assert(pb_dispatch(p, &pb_io, &pb_guard, 1, &rc) == 1 && rc == -EXDEV); _exit(0); }
        pthread_mutex_unlock(&parameter_mutex); pthread_mutex_unlock(&mutex); int status;
        assert(waitpid(child, &status, 0) == child && WIFEXITED(status) && !WEXITSTATUS(status)); pb_finish(); return 0;
    }
    if (pb_is("foreign-sender")) {
        pthread_t thread; assert(!pthread_create(&thread, NULL, pb_foreign_thread, p)); assert(!pthread_join(thread, NULL));
        assert(!pb_banks && !pb_states); pb_finish(); return 0;
    }
    struct full_imaging_io io = pb_io; const struct native_cp_state_publication_guard *guard = &pb_guard;
    if (pb_is("missing-release")) io.release = NULL;
    if (pb_is("oneway-only-io")) { io.allocate = NULL; io.set_source = NULL; io.send = NULL; }
    if (pb_is("missing-guard")) guard = NULL;
    if (pb_is("wrong-source")) pb_envelope(p)->source++;
    if (pb_is("short")) pb_envelope(p)->bytes--;
    if (pb_is("long")) pb_envelope(p)->bytes++;
    if (pb_is("wrong-type")) ((unsigned char *)p)[0] = 0;
    if (pb_is("unrelated")) ((unsigned char *)p)[2] ^= 1;
    if (!strncmp(pb_case, "bad-slot-", 9)) {
        unsigned long index = strtoul(pb_case+9, NULL, 10); assert(index < CP_PARAMETER_BATCH_SLOTS);
        ((unsigned char *)p)[cp_parameter_batch_slots[index].offset+2] ^= 1;
    }
    if (pb_is("fps-zero")) put32((unsigned char *)p+0x86c, 0);
    if (pb_is("fps-wide")) put32((unsigned char *)p+0x86c, 121);
    if (pb_is("opaque-headers")) {
        ((unsigned char *)p)[1] = 0xa5;
        for (unsigned int i = 0; i < CP_PARAMETER_BATCH_SLOTS; i++) ((unsigned char *)p)[cp_parameter_batch_slots[i].offset+1] = (unsigned char)i;
        memcpy(original, p, sizeof original);
    }
    if (pb_is("transaction-overflow")) parameter_state.transaction = UINT64_MAX;
    if (pb_is("bank-generation-overflow")) parameter_state.last_bank_generation = UINT64_MAX;
    pb_fail_free = pb_is("free-fail"); pb_testing = 1;
    if (pb_is("before-error-retry")) {
        assert(pb_dispatch(p, &io, guard, 1, &rc) == 1 && rc == -EIO && !pb_banks);
        struct native_functional_camera_parameter_snapshot refused; native_functional_camera_parameter_snapshot(&refused);
        assert(refused.transaction == 1 && !refused.faults && !refused.owned && !refused.model_called);
        rc = 123;
    }
    int handled = pb_is("wrong-destination") ? native_functional_camera_parameter_dispatch(FUNCTIONAL_CAMERA_CONTROL_SID+1, p,
        &io, guard, 1, &rc) : pb_dispatch(p, &io, guard, !pb_is("disabled"), &rc);
    struct native_functional_camera_parameter_snapshot after; native_functional_camera_parameter_snapshot(&after);
    assert(!pb_held && !after.busy && !after.guard_held && pb_allocations == allocations && pb_sends == sends);
    native_functional_camera_control_snapshot(&control_after); assert(!memcmp(&control_before, &control_after, sizeof control_after));
    assert(!memcmp(&initial, &saved_initial, sizeof initial));
    assert(cp_parameter_batch_stage(&initial, FUNCTIONAL_CAMERA_CONTROL_AP, FUNCTIONAL_CAMERA_CONTROL_SID, original,
        sizeof original) == -EBUSY && !memcmp(&initial, &saved_initial, sizeof initial));
    int success = pb_is("success") || pb_is("oneway-only-io") || pb_is("live-state22") || pb_is("before-error-retry") || pb_is("repeat") || pb_is("repeat-same") ||
        pb_is("cookie-wrap") || pb_is("opaque-headers") || pb_is("reentrant-dispatch") || pb_is("reentrant-free") || pb_is("guard-release-reentry");
    if (!handled) {
        assert(pb_is("cold") || pb_is("disabled") || pb_is("wrong-type") || pb_is("unrelated") || pb_is("wrong-destination"));
        assert(rc == 123 && !pb_states && !pb_banks && pb_frees == frees); pb_finish(); return 0;
    }
    if (!success && !pb_fail_free && !pb_mutated_at_free) {
        assert(rc < 0 && !after.owned && !after.retained_request && !after.request_freed && pb_frees == frees);
        if (pb_banks) {
            assert(after.model_called && after.faults);
            if (pb_is("after-error")) assert(after.model_committed && after.model_rc == -EIO);
            else assert(after.model_committed == (after.model_rc == 0));
            unsigned int banks = pb_banks, states = pb_states; int retried = 123;
            void *again = pb_request(7, 30); assert(pb_dispatch(again, &pb_io, &pb_guard, 1, &retried) == 1 && retried < 0);
            assert(pb_banks == banks && pb_states == states); pb_drop(again);
        }
        pb_finish(); return 0;
    }
    assert(handled == 1 && !rc && after.owned && after.verified && after.model_committed && after.commits == 1 && pb_banks == 1);
    assert(pb_states == (pb_is("before-error-retry") ? 3u : 2u));
    assert(after.transaction == (pb_is("before-error-retry") ? 2u : 1u));
    assert(after.before_config_generation == (pb_is("live-state22") ? 22u : 1u));
    assert(after.config_generation == after.before_config_generation+1 && after.bank_generation == 1);
    assert(!memcmp(after.request, original, sizeof original));
    assert(!memcmp(after.receipt+FCAM_CP_PARAMETER_BANK_READBACK_OFFSET, original, sizeof original));
    assert(!memcmp(after.receipt+FCAM_CP_PARAMETER_BANK_STATE_OFFSET, after.after_state, FCAM_STATE_BYTES));
    assert(u64(after.before_state+FCAM_S_FRAME_GENERATION) == u64(after.after_state+FCAM_S_FRAME_GENERATION));
    if (pb_fail_free || pb_mutated_at_free) {
        assert(after.faults && after.retained_request == p && !after.request_freed && pb_frees == frees);
        int freed = 123; unsigned int count = pb_frees;
        assert(native_functional_camera_parameter_release(FUNCTIONAL_CAMERA_CONTROL_SID, p, pb_release, pb_log, &freed, after.transaction+1) == 1 && freed == -ESTALE);
        assert(native_functional_camera_parameter_release(FUNCTIONAL_CAMERA_CONTROL_SID, p, pb_release, pb_log, &freed, after.transaction-1) == 1 && freed == -ESTALE);
        assert(pb_frees == count); pb_fail_free = 0;
        if (pb_mutated_at_free) { pb_envelope(p)->bytes = sizeof original; memcpy(p, original, sizeof original); }
        assert(native_functional_camera_parameter_release(FUNCTIONAL_CAMERA_CONTROL_SID, p, pb_release, pb_log, &freed, after.transaction) == 1 && !freed);
        native_functional_camera_parameter_snapshot(&after);
        assert(after.faults && !after.retained_request && after.request_freed && after.released == 1);
        count = pb_frees; freed = 123;
        assert(native_functional_camera_parameter_release(FUNCTIONAL_CAMERA_CONTROL_SID, p, pb_release, pb_log,
            &freed, after.transaction) == 1 && freed == -ESTALE && pb_frees == count);
        pb_finish(); return 0;
    }
    assert(!after.faults && after.request_freed && !after.retained_request && pb_frees == frees+1);
    assert(after.request_pointer == p);
    int duplicate = 123; const unsigned int freed_before_duplicate = pb_frees;
    assert(native_functional_camera_parameter_release(FUNCTIONAL_CAMERA_CONTROL_SID, p, pb_release, pb_log,
        &duplicate, after.transaction) == 1 && duplicate == -ESTALE && pb_frees == freed_before_duplicate);
    if (pb_is("repeat") || pb_is("repeat-same") || pb_is("cookie-wrap")) {
        uint64_t generation = after.config_generation;
        for (unsigned int i = 0; i < 2; i++) {
            p = pb_request(pb_is("repeat-same") ? UINT32_C(0x80000061) : i, pb_is("repeat-same") ? 30 : 60);
            if (!pb_is("repeat-same")) ((unsigned char *)p)[FCAM_CP_PARAMETER_BANK_BYTES-1] ^= (unsigned char)(i+1);
            memcpy(original, p, sizeof original); rc = 123; assert(pb_dispatch(p, &pb_io, &pb_guard, 1, &rc) == 1 && !rc);
            native_functional_camera_parameter_snapshot(&after);
            assert(!after.faults && after.request_freed && after.transaction == i+2 && after.bank_generation == i+2 && after.commits == i+2);
            assert(after.before_config_generation == generation && after.config_generation == generation+1); generation++;
            assert(!memcmp(after.request, original, sizeof original) && !memcmp(after.receipt+FCAM_CP_PARAMETER_BANK_READBACK_OFFSET, original, sizeof original));
        }
        assert(pb_states == 6 && pb_banks == 3 && pb_frees == frees+3);
    }
    native_functional_camera_control_snapshot(&control_after); assert(!memcmp(&control_before, &control_after, sizeof control_after));
    pb_finish(); puts("PASS real Core bank; native AP and capture remain unverified"); return 0;
}
#elif defined(FCAM_SELECTOR0_TEST)
/* SPDX-License-Identifier: MIT */
#define _GNU_SOURCE
#ifndef HOST_TEST
#error This source-only fixture must never be linked into production.
#endif
/* Include the candidate owner once; link the unchanged real Core and shared
 * snapshot/publication sources. Do not also link functional-camera-control.c. */
#include "functional-camera-control.c"
#include "../functional-camera-events.h"
#include "../../../report/functional-camera-core/functional-camera-core.h"
#include <assert.h>
#include <stdlib.h>
#include <sys/wait.h>
#include <libavutil/log.h>

/* Real Core STATE/INIT, fixture OSAL/guard/bridge: no VM, original AP, physical
 * ASIC or capture claim. Private owner mutations below only inject failures. */
struct packet { void *next; unsigned int flags, source, bytes, reserved; unsigned char body[]; };
_Static_assert(offsetof(struct packet, body) == 24, "original OSAL header");
static struct packet *packets[16], *recycled[2];
static struct fcam_model *model;
static const char *scenario;
static void *active_request, *ack, *notice;
static unsigned int allocated, sent, freed, state_calls, init_calls, bridge_calls;
static int held, fail_guard, prior_ready = 1, fail_probe, mutate_request, corrupt_selector, fail_send, fail_notice_free;
static int reenter_send;
static unsigned char actual_state[FCAM_STATE_BYTES];
static char last_record[3000];
static const uint64_t instance = UINT64_C(0x123456789abcdef);
static const unsigned char zero_wire[12] = {5, 0, 0x73, 0x40, 0x60, 0, 0, 0x80, 0, 0, 0, 0};
static const struct full_imaging_io io;
static const struct native_cp_state_publication_guard guard;
static int dispatch_request(void *, int *);
static void *new_request(int, unsigned int);
static struct packet *packet(void *p) { return (struct packet *)((unsigned char *)p - offsetof(struct packet, body)); }
static struct native_functional_camera_control_snapshot control(void) {
    struct native_functional_camera_control_snapshot s;
    native_functional_camera_control_snapshot(&s);
    assert(s.owner_pid == getpid() && s.initialized && s.functional_model);
    assert(!s.original_cp && !s.physical_asic_verified && !s.ee && !s.frame && !s.capture);
    return s;
}
static int is(const char *name) { return !strcmp(scenario, name); }
static void *new_packet(unsigned int bytes, unsigned int source_id) {
    unsigned int slot = bytes == CP_STATE_SNAPSHOT_BYTES;
    struct packet *p = NULL;
    if (!source_id && (bytes == 12 || bytes == CP_STATE_SNAPSHOT_BYTES)) {
        p = recycled[slot]; recycled[slot] = NULL;
    }
    if (!p) p = malloc(sizeof *p + bytes);
    assert(p);
    p->source = source_id; p->bytes = bytes; memset(p->body, 0, bytes);
    for (unsigned int i = 0; i < 16; ++i) if (!packets[i]) { packets[i] = p; return p->body; }
    assert(0); return NULL;
}
static void drop(void *body) {
    struct packet *p = packet(body);
    for (unsigned int i = 0; i < 16; ++i) if (packets[i] == p) {
        packets[i] = NULL;
        if (p->source == FUNCTIONAL_CAMERA_CONTROL_SID && (p->bytes == 12 || p->bytes == CP_STATE_SNAPSHOT_BYTES)) {
            unsigned int slot = p->bytes == CP_STATE_SNAPSHOT_BYTES;
            assert(!recycled[slot]); recycled[slot] = p;
        } else free(p);
        return;
    }
    assert(0);
}
static unsigned int message_bytes(void *p) { (void)control(); return packet(p)->bytes; }
static unsigned int message_source(void *p) { (void)control(); return packet(p)->source; }
static void set_message_source(void *p, unsigned int value) { (void)control(); packet(p)->source = value; }
static int allocate_packet(unsigned int destination, void **p, unsigned int bytes, unsigned int option) {
    (void)control(); assert(destination == FUNCTIONAL_CAMERA_CONTROL_AP && option == 1);
    ++allocated; *p = new_packet(bytes, 0);
    if (corrupt_selector) {
        pthread_mutex_lock(&mutex); state.mode_selector ^= 1; pthread_mutex_unlock(&mutex);
        corrupt_selector = 0;
    }
    return 0;
}
static int release_packet(unsigned int destination, void *p) {
    (void)control(); assert(destination == FUNCTIONAL_CAMERA_CONTROL_AP || destination == FUNCTIONAL_CAMERA_CONTROL_SID);
    if (fail_notice_free && packet(p)->bytes == CP_STATE_SNAPSHOT_BYTES) return -EIO;
    ++freed; drop(p); return 0;
}
static int send_packet(unsigned int destination, void *p) {
    struct native_functional_camera_control_snapshot s = control();
    assert(destination == FUNCTIONAL_CAMERA_CONTROL_AP && packet(p)->source == FUNCTIONAL_CAMERA_CONTROL_SID);
    ++sent;
    if (packet(p)->bytes == CP_STATE_SNAPSHOT_BYTES) notice = p; else ack = p;
    if (reenter_send && s.mode_selector == 0) {
        reenter_send = 0;
        void *again = new_request(0, 1); int rc = 123;
        unsigned int probes = bridge_calls, allocations = allocated;
        assert(dispatch_request(again, &rc) == 1 && rc == -EBUSY);
        assert(bridge_calls == probes && allocated == allocations); drop(again);
    }
    return fail_send ? -EPIPE : 0;
}
static void log_record(const char *tag, const char *text) {
    (void)control(); assert(strstr(tag, "FUNCTIONAL_CAMERA_CONTROL_"));
    assert(strlen(text) < sizeof last_record); strcpy(last_record, text);
}
static int reserve_guard(void) {
    (void)control(); assert(!held);
    if (fail_guard) return -EBUSY;
    held = 1; return 0;
}
static void release_guard(void) { (void)control(); assert(held); held = 0; }
static int predecessors(void) { (void)control(); assert(held); return prior_ready; }
static const struct full_imaging_io io = {allocate_packet, release_packet, set_message_source,
    send_packet, message_bytes, message_source, log_record};
static const struct native_cp_state_publication_guard guard = {reserve_guard, release_guard, predecessors};

int fcam_bridge_call(const struct fcam_native_origin *origin, uint32_t opcode,
    const void *input, size_t input_bytes, void *output, size_t capacity, struct fcam_bridge_result *result) {
    assert(held && model && origin && active_request && !input && !input_bytes && capacity == FCAM_STATE_BYTES);
    assert(origin->source == FUNCTIONAL_CAMERA_CONTROL_AP && origin->destination == FUNCTIONAL_CAMERA_CONTROL_SID);
    assert(origin->bytes == packet(active_request)->bytes && origin->command == u16((unsigned char *)active_request + 2));
    assert(origin->wire_fnv1a64 == hash(active_request, origin->bytes));
    assert(opcode == (((unsigned char *)active_request)[0] ? FCAM_OP_STATE : FCAM_OP_INIT));
    ++bridge_calls;
    if (fail_probe) return -EIO;
    struct fcam_frame_proof before, after;
    assert(!fcam_model_proof_snapshot(model, &before, sizeof before));
    struct fcam_exec_result actual = {0};
    int rc = fcam_model_request(model, opcode, NULL, 0, output, capacity, &actual);
    if (rc) return rc;
    assert(!actual.token && !actual.total && !actual.offset && actual.used == FCAM_STATE_BYTES);
    assert(u64((unsigned char *)output + FCAM_S_INSTANCE) == instance);
    assert(!fcam_model_proof_snapshot(model, &after, sizeof after));
    if (opcode == FCAM_OP_STATE) { ++state_calls; assert(!memcmp(&before, &after, sizeof before)); }
    else ++init_calls;
    memcpy(actual_state, output, sizeof actual_state);
    *result = (struct fcam_bridge_result){actual.used, actual.used, instance, 0};
    if (mutate_request) ((unsigned char *)active_request)[4] ^= 1;
    return 0;
}
static void *new_request(int start, unsigned int selector) {
    unsigned char *p = new_packet(start ? 24 : 12, FUNCTIONAL_CAMERA_CONTROL_AP);
    if (!start && !selector) memcpy(p, zero_wire, sizeof zero_wire);
    else {
        p[0] = start ? 0 : 5; p[2] = start ? 3 : 0x73; p[3] = start ? 0x30 : 0x40;
        put32(p + 4, UINT32_C(0x80000027)); if (!start) put32(p + 8, selector);
    }
    return p;
}
static int dispatch_request(void *p, int *result) {
    void *prior = active_request; active_request = p;
    int handled = native_functional_camera_control_dispatch(FUNCTIONAL_CAMERA_CONTROL_SID, p, &io, &guard, 1, result);
    active_request = prior; return handled;
}
static void *observe_ack(void *p) {
    assert(functional_camera_events_observe_receive(FUNCTIONAL_CAMERA_CONTROL_AP, p,
        FUNCTIONAL_CAMERA_CONTROL_SID, packet(p)->bytes) == 1);
    return NULL;
}
static void *consume_notice(void *p) {
    assert(functional_camera_events_observe_receive(FUNCTIONAL_CAMERA_CONTROL_AP, p,
        FUNCTIONAL_CAMERA_CONTROL_SID, CP_STATE_SNAPSHOT_BYTES) == 1);
    int rc = 123;
    assert(functional_camera_events_release(FUNCTIONAL_CAMERA_CONTROL_AP, p, release_packet, log_record, &rc) == 1);
    assert(rc == (fail_notice_free ? -EIO : 0));
    return NULL;
}
static void on_receiver(void *(*fn)(void *), void *p) {
    pthread_t thread; assert(!pthread_create(&thread, NULL, fn, p)); assert(!pthread_join(thread, NULL));
}
static void free_ack(void) {
    assert(ack); on_receiver(observe_ack, ack);
    int rc = 123;
    assert(functional_camera_events_release(FUNCTIONAL_CAMERA_CONTROL_AP, ack, release_packet, log_record, &rc) == 1 && !rc);
    ack = NULL;
}
static void check_full(unsigned int shadow) {
    assert(notice && packet(notice)->bytes == CP_STATE_SNAPSHOT_BYTES);
    unsigned char expected[CP_STATE_SNAPSHOT_BYTES] = {6, 0, 0x40, 0x20}, known[CP_STATE_SNAPSHOT_BYTES];
    const unsigned int aperture = u32(actual_state + FCAM_S_FNUMBER), fps = u32(actual_state + FCAM_S_FPS);
    const unsigned int generation = (unsigned int)u64(actual_state + FCAM_S_GENERATION);
    memset(known, 1, sizeof known);
    for (unsigned int i = 0; i < CP_FULL_STATE_SNAPSHOT_BLOCKS; ++i) {
        const struct cp_full_state_snapshot_block b = cp_full_state_snapshot_blocks[i];
        unsigned char *p = expected + b.offset; p[0] = 6; put16(p + 2, b.command);
        if (b.command == 0x2012) p[10] = 0x77;
        else if (b.command == 0x201b) put16(p + 8, aperture);
        else if (b.command == 0x20a6) { put32(p + 8, fps); put16(p + 12, 1); }
        else if (b.command == 0x2044) {
            p[8] = 1; put32(p + 0x18, 10); put32(p + 0x20, 10);
            put32(p + 0x24, 0x40); put32(p + 0x28, 10); put32(p + 0x2c, 0x160); put32(p + 0x30, 10);
            memcpy(p + 0x34, "Virtual functional fixed optics", 32);
        }
    }
    assert(!memcmp(notice, expected, sizeof expected));
    const struct cp_state_snapshot_input input = {notice, known, sizeof expected, sizeof known,
        {CP_STATE_SNAPSHOT_PUBLISHED_BYTES, generation, generation, shadow}};
    struct cp_state_snapshot copied;
    assert(!cp_full_state_snapshot_copy(&input, &copied));
    assert(copied.aperture_words[0] == aperture && copied.lens_wire_state == 1);
}
static void start_owner(void) {
    void *p = new_request(1, 0); int rc = 123;
    assert(dispatch_request(p, &rc) == 1 && !rc && init_calls == 1);
    free_ack(); assert(control().start_complete);
}
static void first_mode1(void) {
    void *p = new_request(0, 1); int rc = 123;
    assert(dispatch_request(p, &rc) == 1 && !rc);
    if (is("pending-mode1")) return;
    check_full(0); free_ack(); on_receiver(consume_notice, notice); notice = NULL;
    struct native_functional_camera_control_snapshot s = control();
    assert(s.mode1_complete && s.mode_complete && s.mode_cycle_id == 1 && s.mode1_cycle_id == 1);
    assert(s.mode1_requests == 1 && s.mode1_cycles_completed == 1 && !s.mode0_requests && !s.mode0_complete);
}
static void advance_model(void) {
    unsigned char bytes[128], config[48] = {0}; struct fcam_exec_result result;
    assert(!fcam_model_request(model, FCAM_OP_STATE, NULL, 0, bytes, sizeof bytes, &result));
    memcpy(config, bytes + FCAM_S_WIDTH, 40); put32(config + 16, 800);
    assert(!fcam_model_request(model, FCAM_OP_CONFIGURE, config, sizeof config, bytes, sizeof bytes, &result));
}
static void same_mode1(const struct native_functional_camera_control_snapshot *before,
                       const struct native_functional_camera_control_snapshot *after) {
    assert(after->mode1_requests == before->mode1_requests && after->mode1_cycles_completed == before->mode1_cycles_completed);
    assert(after->mode1_cycle_id == before->mode1_cycle_id && after->mode1_cycle_generation == before->mode1_cycle_generation);
    assert(after->mode1_ack_only == before->mode1_ack_only && after->mode1_ack_only_requests == before->mode1_ack_only_requests &&
        after->mode1_ack_only_completed == before->mode1_ack_only_completed);
    assert(after->mode1_complete == (after->faults ? 0u : before->mode1_complete));
}
static void replay_old_ticket(void *p, unsigned int bytes, uint64_t epoch) {
    unsigned char saved[CP_STATE_SNAPSHOT_BYTES]; memcpy(saved, p, bytes);
    unsigned int free_count = freed; int rc = 123;
    assert(native_functional_camera_control_observe_receive_cycle(FUNCTIONAL_CAMERA_CONTROL_AP, p,
        FUNCTIONAL_CAMERA_CONTROL_SID, bytes, epoch) == -ESTALE);
    assert(native_functional_camera_control_release_cycle(FUNCTIONAL_CAMERA_CONTROL_AP, p,
        release_packet, log_record, &rc, epoch) == 1 && rc == -ESTALE);
    assert(freed == free_count && !memcmp(saved, p, bytes) && !control().faults);
}
static void fixture_finish(void) {
    assert(!held);
    fcam_model_destroy(model);
    for (unsigned int i = 0; i < 16; ++i) free(packets[i]);
    for (unsigned int i = 0; i < 2; ++i) free(recycled[i]);
}
int main(int argc, char **argv) {
    assert(argc == 2); scenario = argv[1]; av_log_set_level(AV_LOG_ERROR);
    static const char *const cases[] = {"cold0", "strict", "before-mode1", "pending-mode1", "success", "notice-first",
        "wrong-owner", "wrong-source", "probe-failure", "pending-result", "same-generation", "unknown", "guard-failure",
        "predecessor-failure", "request-mutation", "selector-readback-failure", "epoch-overflow", "counter-overflow",
        "send-failure", "notice-free-failure"};
    unsigned int known = 0;
    for (unsigned int i = 0; i < sizeof cases / sizeof *cases; ++i) known |= is(cases[i]);
    assert(known);
    assert(!native_functional_camera_control_owner_init());
    void *p = new_request(0, 0); int rc = 123;
    if (is("cold0")) {
        assert(!dispatch_request(p, &rc) && rc == 123 && !bridge_calls && !allocated && !sent);
        drop(p); fixture_finish(); return 0;
    }
    if (is("strict")) {
        assert(!native_cp_state_publication_owner_init());
        assert(!native_cp_state_publication_dispatch(FUNCTIONAL_CAMERA_CONTROL_SID, p, &io, &guard, NULL, 1, &rc) && rc == 123);
        assert(!bridge_calls && !allocated && !sent); drop(p); fixture_finish(); return 0;
    }
    drop(p); model = fcam_model_create(instance); assert(model); start_owner();
    if (is("before-mode1")) {
        p = new_request(0, 0); unsigned int calls = bridge_calls;
        assert(dispatch_request(p, &rc) == 1 && rc == FUNCTIONAL_CAMERA_CONTROL_BLOCKED && bridge_calls == calls);
        assert(!control().mode1_requests && !control().mode0_requests); drop(p); fixture_finish(); return 0;
    }
    first_mode1();
    struct native_functional_camera_control_snapshot before = control();
    void *old_ack = recycled[0] ? recycled[0]->body : NULL, *old_notice = recycled[1] ? recycled[1]->body : NULL;
    if (!is("same-generation") && !is("pending-mode1")) advance_model();
    p = new_request(0, 0); assert(!memcmp(p, zero_wire, sizeof zero_wire));
    unsigned int probes_before = bridge_calls, states_before = state_calls, allocations_before = allocated, sends_before = sent;
    uint64_t pending_token = 0, pending_total = 0;
    if (is("wrong-owner")) {
        native_functional_camera_control_test_hold_lock(); pid_t child = fork(); assert(child >= 0);
        if (!child) { assert(dispatch_request(p, &rc) == 1 && rc == -EXDEV); _exit(0); }
        native_functional_camera_control_test_drop_lock(); int status;
        assert(waitpid(child, &status, 0) == child && WIFEXITED(status) && !WEXITSTATUS(status));
        assert(bridge_calls == probes_before); drop(p); fixture_finish(); return 0;
    }
    if (is("wrong-source")) packet(p)->source++;
    if (is("unknown")) { put32((unsigned char *)p + 8, 2); rc = 123; }
    fail_probe = is("probe-failure"); fail_guard = is("guard-failure"); prior_ready = !is("predecessor-failure");
    mutate_request = is("request-mutation"); corrupt_selector = is("selector-readback-failure");
    fail_send = is("send-failure"); fail_notice_free = is("notice-free-failure"); reenter_send = is("success");
    if (is("epoch-overflow") || is("counter-overflow")) {
        pthread_mutex_lock(&mutex);
        if (is("epoch-overflow")) state.mode_cycle_id = UINT64_MAX; else state.mode0_requests = UINT_MAX;
        pthread_mutex_unlock(&mutex);
    }
    if (is("pending-result")) {
        unsigned char still[16] = {0}, byte; struct fcam_exec_result result;
        put32(still, FCAM_STILL_FULL_JPEG); put32(still + 4, 128); put32(still + 8, 64); put32(still + 12, 90);
        assert(!fcam_model_request(model, FCAM_OP_STILL, still, sizeof still, &byte, 1, &result));
        pending_token = result.token; pending_total = result.total; assert(pending_token && pending_total > 1);
    }
    int handled = dispatch_request(p, &rc);
    struct native_functional_camera_control_snapshot after = control();
    if (is("unknown") || is("pending-mode1") || is("wrong-source") || is("probe-failure") ||
        is("pending-result") || is("same-generation") || is("guard-failure") || is("predecessor-failure") ||
        is("request-mutation") || is("epoch-overflow") || is("counter-overflow")) {
        int expected = is("unknown") ? 123 : is("pending-mode1") || is("pending-result") || is("guard-failure") ? -EBUSY :
            is("probe-failure") ? -EIO : is("same-generation") ? -ESTALE :
            is("epoch-overflow") || is("counter-overflow") ? -EOVERFLOW : FUNCTIONAL_CAMERA_CONTROL_BLOCKED;
        assert(handled == (is("unknown") ? 0 : 1) && rc == expected && allocated == allocations_before && sent == sends_before);
        same_mode1(&before, &after); assert(!after.mode0_complete && !after.faults);
        if (is("same-generation") || is("pending-result") || is("request-mutation")) assert(state_calls == states_before + 1);
        else assert(state_calls == states_before);
        if (is("pending-result")) {
            unsigned char request[24] = {0}, byte, cancelled[128]; struct fcam_exec_result result;
            put32(request, (uint32_t)pending_token); put32(request + 4, (uint32_t)(pending_token >> 32));
            put32(request + 8, 1); put32(request + 16, 1);
            assert(!fcam_model_request(model, FCAM_OP_READ_RESULT, request, sizeof request, &byte, 1, &result));
            assert(result.token == pending_token && result.total == pending_total && result.offset == 1 && result.used == 1);
            assert(!fcam_model_request(model, FCAM_OP_CANCEL, NULL, 0, cancelled, sizeof cancelled, &result));
        }
        drop(p); fixture_finish(); return 0;
    }
    assert(handled == 1 && !rc && state_calls == states_before + 1 && bridge_calls == probes_before + 1);
    if (is("selector-readback-failure") || is("send-failure")) {
        assert(after.faults && !after.mode_complete && !after.mode0_complete && !after.mode1_complete);
        assert(after.leases[MODE_REQUEST].pointer == p && after.shadow_generation == before.shadow_generation);
        same_mode1(&before, &after); fixture_finish(); return 0;
    }
    assert(after.mode_cycle_id == 2 && after.mode_selector == 0 && after.mode0_requests == 1 && !after.mode0_complete && !after.mode_complete);
    assert(after.mode_cycle_generation == u64(actual_state + FCAM_S_GENERATION));
    assert(after.leases[MODE_REQUEST].freed && !after.leases[MODE_REQUEST].pointer);
    assert(ack == old_ack && notice == old_notice && after.lease_cycle_id[MODE_ACK] == 2 && after.lease_cycle_id[FULL_NOTICE] == 2);
    same_mode1(&before, &after); check_full(before.shadow_generation);
    const unsigned char expected_ack[12] = {1, 0, 0x73, 0x40, 0x60, 0, 0, 0x80, 0, 0xf0, 0, 0};
    assert(packet(ack)->bytes == 12 && !memcmp(ack, expected_ack, sizeof expected_ack));
    replay_old_ticket(ack, 12, 1); replay_old_ticket(notice, CP_STATE_SNAPSHOT_BYTES, 1);
    if (is("notice-first")) {
        on_receiver(consume_notice, notice); notice = NULL;
        after = control(); same_mode1(&before, &after);
        assert(after.notification_ap_consumed && after.mode1_complete && !after.mode_complete && !after.mode0_complete);
        void *again = new_request(0, 1); unsigned int probes = bridge_calls;
        assert(dispatch_request(again, &rc) == 1 && rc == -EBUSY && bridge_calls == probes); drop(again);
        free_ack();
    } else {
        free_ack(); assert(!control().mode0_complete && !control().mode_complete);
        on_receiver(consume_notice, notice);
    }
    after = control(); same_mode1(&before, &after);
    if (is("notice-free-failure")) {
        assert(after.faults && !after.mode0_complete && !after.mode_complete && after.leases[FULL_NOTICE].pointer == notice);
        assert(after.shadow_generation == before.shadow_generation); fixture_finish(); return 0;
    }
    notice = NULL;
    assert(after.mode0_complete && after.mode_complete && after.mode0_cycles_completed == 1 && after.notification_ap_consumed);
    assert(after.mode1_complete && after.mode1_requests == 1 && after.mode1_cycle_id == 1 && after.notification_mode == 1);
    assert(after.shadow_generation == after.mode_cycle_generation && after.full_notifications_consumed == before.full_notifications_consumed + 1);
    assert(strstr(last_record, "cycle_id=2 ") && strstr(last_record, "mode_selector=0 ") && strstr(last_record, "mode1_cycle_id=1 "));
    p = new_request(0, 1); assert(dispatch_request(p, &rc) == 1 && !rc && !notice);
    after = control(); assert(after.mode_cycle_id == 3 && after.mode1_cycle_id == 3 && after.mode1_requests == 2 && after.mode1_ack_only);
    free_ack(); after = control();
    assert(after.mode_complete && after.mode1_complete && after.mode1_cycles_completed == 2 && after.mode1_ack_only_completed == 1);
    assert(after.mode0_requests == 1 && after.mode0_complete && after.mode0_cycles_completed == 1);
    assert(init_calls == 1 && state_calls == 3 && !after.faults);
    fixture_finish(); puts("PASS real Core STATE fixture; original AP/CP/ASIC/capture remain unverified"); return 0;
}

#else
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

#endif

#endif /* FCAM_MOVIE_FORMAT_TEST */
#endif /* FCAM_OU_CRANK_CONTROL_TEST */
