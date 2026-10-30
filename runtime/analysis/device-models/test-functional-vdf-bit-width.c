/* SPDX-License-Identifier: MIT */
#ifndef HOST_TEST
#error HOST_TEST real Core plus guest-owner component fixture only
#endif
#include "functional-vdf-path.h"
#include "../../../report/functional-camera-core/functional-camera-core.h"
#include "../../../report/virtual-optical-frame-owner/optical-frame-owner.h"
#include <assert.h>
#include <pthread.h>
#include <stddef.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

struct message { void *next; unsigned int flags, source, size, reserved; unsigned char body[]; };
_Static_assert(offsetof(struct message, body) == 24, "public OSAL envelope");
_Static_assert(FCAM_OP_VDF_BIT_WIDTH == 12 && FCAM_BIT_WIDTH_INPUT_BYTES == 8 &&
    FCAM_BIT_WIDTH_RESULT_BYTES == 168 && FCAM_BIT_WIDTH_R_CONFIG == 160 &&
    FCAM_BIT_WIDTH_CLASS == 7, "bit-width wire contract");
static const uint64_t instance = UINT64_C(0x9a1701);
static const unsigned char bit_request[10] = {0x0d,0x20,0x5e,1,10,0,1,0x80,0,0};
static const unsigned char bit_ack[12] = {0x0d,0x20,0x5e,0x11,12,0,1,0x80,0,0,0x59,0};
static struct fcam_model *model;
static const char *scenario;
static struct {
    void *request, *ack, *queued, *received;
    struct message *pool;
    unsigned int caller, command, bytes, op, input_bytes, output_bytes;
    unsigned int phase, held, init_calls, calls, bit_calls, allocations, sends;
    unsigned int request_free_calls, request_frees, ack_free_calls, ack_frees, callbacks;
    unsigned int reuse, pool_live, same_address, order;
    uint64_t ticket, previous_ticket;
    uintptr_t request_address;
    unsigned char wire[40], input[32], route[16], expected_ack[12], authentic_result[168];
} c;

static uint32_t u32(const unsigned char *p) {
    return p[0] | (uint32_t)p[1] << 8 | (uint32_t)p[2] << 16 | (uint32_t)p[3] << 24;
}
static uint64_t u64(const unsigned char *p) { return u32(p) | (uint64_t)u32(p + 4) << 32; }
static uint64_t fnv(const void *pointer, size_t bytes) {
    const unsigned char *p = pointer; uint64_t h = UINT64_C(14695981039346656037);
    for (size_t i = 0; i < bytes; ++i) h = (h ^ p[i]) * UINT64_C(1099511628211);
    return h;
}
static int is(const char *name) { return !strcmp(scenario, name); }
static struct functional_vdf_path_snapshot owner(void) {
    struct functional_vdf_path_snapshot s; functional_vdf_path_snapshot(&s);
    assert(s.initialized && s.owner_pid == getpid() && s.functional_model);
    assert(!s.capture_verified && !s.physical_asic_verified && !s.physical_cp_rtos_verified &&
        !s.original_cp_fifo_verified && !s.original_selector_verified);
    return s;
}
static void callback(void) { (void)owner(); ++c.callbacks; }
static struct message *envelope(void *p) { return (struct message *)((unsigned char *)p - 24); }
static void *message(unsigned int bytes, unsigned int source) {
    struct message *m;
    if (c.reuse && c.command == 0x015e) {
        assert(!c.pool_live);
        if (!c.pool) c.pool = malloc(sizeof *m + 40);
        m = c.pool; c.pool_live = 1;
    } else m = malloc(sizeof *m + bytes);
    assert(m); memset(m, 0, sizeof *m + bytes); m->size = bytes; m->source = source;
    return m->body;
}
static void destroy_message(void *p) {
    if (envelope(p) == c.pool) { assert(c.pool_live); c.pool_live = 0; } /* shortcut: retain malloc storage for deterministic OSAL lease reuse; real allocator behavior needs guest tests. */
    else free(envelope(p));
}
static unsigned int size(void *p) { callback(); return envelope(p)->size; }
static unsigned int source(void *p) { callback(); return envelope(p)->source; }
static void set_source(void *p, unsigned int src) { callback(); envelope(p)->source = src; }
static void record(const char *tag, const char *detail) { callback(); assert(tag && detail); }
static struct fcam_frame_proof proof(void) {
    struct fcam_frame_proof p; assert(!fcam_model_proof_snapshot(model, &p, sizeof p));
    assert(p.version == 1 && p.struct_bytes == sizeof p && p.model_instance == instance);
    return p;
}
static void core_state(unsigned char out[128]) {
    struct fcam_exec_result r = {0};
    assert(!fcam_model_request(model, FCAM_OP_STATE, NULL, 0, out, 128, &r));
    assert(r.used == 128 && !r.token && !r.total && !r.offset);
}
static void hex(const void *pointer, size_t bytes) {
    const unsigned char *p = pointer;
    for (size_t i = 0; i < bytes; ++i) printf("%02x", p[i]);
}
#define P(field) printf(" " #field "=%llu", (unsigned long long)p->field)
static void print_proof(const struct fcam_frame_proof *p) {
    printf("proof");
    P(version); P(struct_bytes); P(serial); P(model_instance); P(model_lifetime); P(owner_pid);
    P(opcode); P(consumer_kind); P(config_generation); P(frame_generation); P(lease_generation);
    P(packet_generation); P(width); P(height); P(stride); P(active_bytes); P(source_fnv1a64);
    P(consumer_before_fnv1a64); P(consumer_after_fnv1a64); P(render_observed); P(consumer_entered);
    P(consumer_returned); P(encoder_consumed); P(retired); P(source_state); P(consumer_before_state);
    P(consumer_after_state); P(final_state); P(render_status); P(consumer_status); P(retire_status);
    P(operation_status); P(before.rendered); P(before.consumed); P(before.jpeg_encoded);
    P(before.video_encoded); P(before.retired); P(after.rendered); P(after.consumed);
    P(after.jpeg_encoded); P(after.video_encoded); P(after.retired); P(encoded_bytes);
    P(encoded_fnv1a64); P(result_bytes); P(result_fnv1a64); P(result_token); putchar('\n');
}
#undef P
static void verify_core(const unsigned char before[128], const struct fcam_frame_proof *previous,
    const unsigned char result[168]) {
    unsigned char after[128]; core_state(after); const struct fcam_frame_proof p = proof(), again = proof();
    assert(!memcmp(&p, &again, sizeof p) && p.serial == previous->serial + 1);
    assert(p.opcode == FCAM_OP_VDF_BIT_WIDTH && p.consumer_kind == FCAM_PROOF_VDF);
    assert(p.model_lifetime && p.model_lifetime == previous->model_lifetime && p.owner_pid == (uint64_t)getpid());
    assert(!memcmp(before + 8, after + 8, 48) && !memcmp(before + 80, after + 80, 32));
    assert(p.config_generation == u64(before + 56) + 1 && p.config_generation == u64(after + 56));
    assert(p.frame_generation == u64(before + 112) + 1 && p.frame_generation == u64(after + 112));
    assert(!memcmp(&p.before, &previous->after, sizeof p.before));
    assert(p.after.rendered == p.before.rendered + 1 && p.after.consumed == p.before.consumed + 1 &&
        p.after.retired == p.before.retired + 1 && p.after.jpeg_encoded == p.before.jpeg_encoded &&
        p.after.video_encoded == p.before.video_encoded && p.packet_generation == previous->packet_generation);
    assert(p.render_observed && p.consumer_entered && p.consumer_returned && p.retired &&
        !p.encoder_consumed && !p.encoded_bytes && !p.result_token && !p.operation_status &&
        !p.render_status && !p.consumer_status && !p.retire_status && p.final_state == OPTICAL_FRAME_IDLE);
    assert(p.source_state == OPTICAL_FRAME_RENDERED && p.consumer_before_state == OPTICAL_FRAME_READING &&
        p.consumer_after_state == OPTICAL_FRAME_READING && p.lease_generation > previous->lease_generation);
    assert(p.width == 640 && p.height == 480 && p.stride == 1920 && p.active_bytes == 921600);
    assert(p.source_fnv1a64 && p.source_fnv1a64 == p.consumer_before_fnv1a64 &&
        p.source_fnv1a64 == p.consumer_after_fnv1a64 && p.result_bytes == 168 && p.result_fnv1a64 == fnv(result, 168));
    assert(u32(result) == 1 && u32(result + 4) == 168 && u64(result + 8) == instance);
    assert(u32(result + 96) == 7 && !memcmp(result + 128, c.route, 16));
    assert(!memcmp(result + 160, (unsigned char[8]){0}, 8));
    printf("core input8="); hex(c.input, 8); printf(" result168="); hex(result, 168);
    printf(" before128="); hex(before, 128); printf(" after128="); hex(after, 128);
    printf(" typed_fnv=%016llx previous_serial=%llu previous_lease=%llu previous_packet=%llu core_committed=1\n",
        (unsigned long long)fnv(result, 168),
        (unsigned long long)previous->serial, (unsigned long long)previous->lease_generation,
        (unsigned long long)previous->packet_generation);
    print_proof(&p);
}
/* shortcut: host direct transport only; actual mailbox/RSP acceptance needs separate tests. */
int fcam_bridge_call(const struct fcam_native_origin *origin, uint32_t op, const void *input,
    size_t bytes, void *output, size_t capacity, struct fcam_bridge_result *result) {
    callback(); assert(c.held && c.request && origin && result && output);
    assert(origin->source == c.caller && origin->destination == FUNCTIONAL_VDF_PATH_SID &&
        origin->command == c.command && origin->bytes == c.bytes && origin->wire_fnv1a64 == fnv(c.wire, c.bytes));
    if (op == FCAM_OP_INIT) {
        assert(++c.init_calls == 1 && c.command == 0x0138 && !input && !bytes && capacity == 128);
        assert(!proof().serial);
    } else {
        ++c.calls; assert(op == c.op && bytes == c.input_bytes && capacity == c.output_bytes);
        assert(!memcmp(input, c.input, bytes));
    }
    unsigned char before[128]; core_state(before); const struct fcam_frame_proof previous = proof();
    struct fcam_exec_result actual = {0};
    const int rc = fcam_model_request(model, op, input, bytes, output, capacity, &actual);
    assert(!rc && actual.used == capacity && !actual.token && !actual.total && !actual.offset);
    *result = (struct fcam_bridge_result){actual.used, actual.used,
        u64((const unsigned char *)output + (op == FCAM_OP_INIT ? 48 : 8)), actual.token};
    assert(result->model_instance == instance);
    if (op == FCAM_OP_INIT) {
        const struct fcam_frame_proof p = proof();
        assert(p.serial == 1 && p.after.rendered == 1 && p.after.retired == 1 && !p.after.consumed);
    }
    if (op == FCAM_OP_VDF_BIT_WIDTH) {
        ++c.bit_calls; verify_core(before, &previous, output); memcpy(c.authentic_result, output, 168);
        printf("bridge used=%zu required=%zu instance=%016llx token=%llu\n", result->used, result->required,
            (unsigned long long)result->model_instance, (unsigned long long)result->result_token);
        unsigned char *out = output;
        if (is("corrupt-class")) out[96] ^= 1;
        else if (is("corrupt-sink")) out[56] ^= 1;
        else if (is("corrupt-input")) out[40] ^= 1;
        else if (is("corrupt-tail")) out[167] ^= 1;
        else if (is("corrupt-instance")) result->model_instance ^= 1;
        else if (is("corrupt-used")) --result->used;
        else if (is("corrupt-error")) return -EIO;
    }
    return rc;
}
int fcam_bridge_bb_startup_config(const struct fcam_native_origin *origin, const unsigned char input[32],
    unsigned char output[192], struct fcam_bridge_result *result) {
    return fcam_bridge_call(origin, FCAM_OP_BB_STARTUP_CONFIG, input, 32, output, 192, result);
}
static int allocate(unsigned int destination, void **out, unsigned int bytes, unsigned int option) {
    const struct functional_vdf_path_snapshot s = owner(); callback();
    assert(destination == c.caller && bytes == 12 && option == 1 && !c.ack && s.model_complete);
    if (c.command == 0x0138 || c.command == 0x0153) assert(c.request && !c.phase);
    else {
        assert(!c.request && c.phase == 1 && s.leases[0].freed && !s.leases[0].pointer && !s.leases[0].free_rc);
        assert(c.request_frees == c.allocations + 1); c.order = 1;
    }
    *out = c.ack = message(bytes, 0); ++c.allocations;
    c.same_address = c.request_address == (uintptr_t)c.ack;
    if (c.reuse) assert(c.same_address);
    else if (c.command == 0x0138 || c.command == 0x0153) assert(!c.same_address);
    return 0;
}
static int release(unsigned int destination, void *pointer) {
    const struct functional_vdf_path_snapshot s = owner(); callback();
    assert(s.model_complete && !s.ap_consumed);
    if (pointer == c.request) {
        ++c.request_free_calls;
        assert(destination == FUNCTIONAL_VDF_PATH_SID && !c.phase && envelope(pointer)->source == c.caller &&
            envelope(pointer)->size == c.bytes && !memcmp(pointer, c.wire, c.bytes) && s.leases[0].releasing);
        if (c.command != 0x0138 && c.command != 0x0153) assert(!c.ack);
        if (c.command == 0x015e && is("request-free-fail")) return -EIO;
        c.request = NULL; ++c.request_frees; c.phase = 1;
    } else {
        ++c.ack_free_calls;
        assert(pointer == c.ack && pointer == c.received && c.phase == 3 && destination == c.caller);
        assert(s.ack_received && s.leases[0].freed && !s.leases[0].pointer && s.leases[1].releasing);
        assert(s.leases[1].sender_tid == s.leases[1].receiver_tid && !memcmp(pointer, c.expected_ack, 12));
        if (c.command == 0x015e && is("ack-free-fail")) return -EIO;
        c.ack = c.received = NULL; ++c.ack_frees; c.phase = 4;
    }
    destroy_message(pointer); return 0;
}
static int consume(void) {
    assert(c.queued && c.queued == c.ack && !c.received);
    c.received = c.queued; c.queued = NULL; c.phase = 3;
    uint64_t ticket = 0;
    assert(functional_vdf_path_observe_receive_cycle(c.caller, c.received,
        source(c.received), size(c.received), &ticket) == 1);
    assert(ticket == owner().cycle && ticket > c.previous_ticket); c.ticket = ticket;
    const struct functional_vdf_path_snapshot before = owner();
    if (c.command == 0x015e && (is("stale-ticket") || is("address-reuse"))) {
        int stale_rc = 999;
        assert(functional_vdf_path_release_cycle(c.caller, c.received, c.previous_ticket, release, record, &stale_rc) == 1);
        assert(stale_rc == -ESTALE); const struct functional_vdf_path_snapshot after = owner();
        assert(!memcmp(&before, &after, sizeof before));
        puts("ticket stale_rejected=1 snapshot_unchanged=1");
    }
    assert(before.ack_received && !before.ap_consumed);
    int rc = 999;
    assert(functional_vdf_path_release_cycle(c.caller, c.received, ticket, release, record, &rc) == 1);
    if (!rc) c.previous_ticket = ticket;
    return rc;
}
static int send(unsigned int destination, void *pointer) {
    const struct functional_vdf_path_snapshot s = owner(); callback();
    assert(destination == c.caller && pointer == c.ack && c.phase == 1 && !c.request && !c.queued);
    assert(envelope(pointer)->source == FUNCTIONAL_VDF_PATH_SID && envelope(pointer)->size == 12 &&
        !memcmp(pointer, c.expected_ack, 12) && s.leases[0].freed && s.leases[1].send_inflight && !s.ap_consumed);
    ++c.sends; c.phase = 2; c.queued = pointer;
    if (c.command == 0x015e && (is("inline") || is("inline-send-fail"))) {
        assert(!consume() && !owner().ap_consumed && owner().leases[1].freed);
        puts("inline real_receive_free=1 consumed_before_send_return=0");
    }
    return c.command == 0x015e && (is("send-fail") || is("inline-send-fail")) ? -EIO : 0;
}
static int reserve(void) { callback(); assert(!c.held); c.held = 1; return 0; }
static void unlock(void) { callback(); assert(c.held); c.held = 0; }
static int ready(void) { callback(); assert(c.held); return 1; }
static const struct full_imaging_io io = {allocate, release, set_source, send, size, source, record};
static const struct native_cp_state_publication_guard guard = {reserve, unlock, ready};

static void prepare(unsigned int command, unsigned int active, unsigned int sender, unsigned int variant) {
    assert(!c.request && !c.ack && !c.queued && !c.received);
    c.command = command; c.caller = sender; c.phase = 0; c.order = 0; c.same_address = 0; c.ticket = 0;
    memset(c.wire, 0, sizeof c.wire); memset(c.input, 0, sizeof c.input);
    c.wire[0] = 0x0d; c.wire[1] = 0x20; c.wire[2] = (unsigned char)command; c.wire[3] = 1;
    c.wire[6] = 1; c.wire[7] = 0x80;
    if (command == 0x0138) {
        c.bytes = 24; c.op = FCAM_OP_VDF_PATH; c.input_bytes = 16; c.output_bytes = 160;
        c.wire[8] = (unsigned char)active; c.wire[9] = c.wire[10] = active ? 5 : 1;
        c.wire[11] = (unsigned char)(0xab + variant); c.wire[12] = 2;
        for (size_t i = 13; i < 21; ++i) c.wire[i] = (unsigned char)(0xa0 + i + variant);
        c.wire[21] = 0x91; c.wire[22] = 0x92; c.wire[23] = 0x93;
        memcpy(c.route, c.wire + 8, 16); memset(c.route + 13, 0, 3); memcpy(c.input, c.route, 16);
    } else if (command == 0x0153) {
        c.bytes = 14; c.op = FCAM_OP_VDF_ZEBRA; c.input_bytes = 8; c.output_bytes = 168;
        memcpy(c.wire + 8, (unsigned char[6]){3,0,0x20,0x4b,0x41,0x99}, 6); memcpy(c.input, c.wire + 8, 5);
    } else if (command == 0x0111) {
        c.bytes = 36; c.op = FCAM_OP_BB_STARTUP_CONFIG; c.input_bytes = 32; c.output_bytes = 192;
        c.wire[10] = 15; c.wire[11] = 2;
        memcpy(c.input, (unsigned char[4]){0x11,1,28,0}, 4); memcpy(c.input + 4, c.wire + 8, 28);
    } else {
        assert(command == 0x015e); c.bytes = 10; c.op = FCAM_OP_VDF_BIT_WIDTH;
        c.input_bytes = 8; c.output_bytes = 168;
    }
    c.wire[4] = (unsigned char)c.bytes;
    memcpy(c.expected_ack, (unsigned char[12]){0x0d,0x20,(unsigned char)command,0x11,12,0,1,0x80,0,0,0,0}, 12);
    if (command == 0x0138 || command == 0x015e) c.expected_ack[10] = 0x59;
    c.request = message(c.bytes, sender); memcpy(c.request, c.wire, c.bytes); c.request_address = (uintptr_t)c.request;
}
static void complete_legacy(unsigned int command, unsigned int active, unsigned int sender, unsigned int variant) {
    prepare(command, active, sender, variant); int rc = 999;
    assert(functional_vdf_path_dispatch(FUNCTIONAL_VDF_PATH_SID, c.request, &io, &guard, 1, &rc) == 1 && !rc);
    assert(!consume() && owner().ap_consumed && !owner().faults && !c.held);
}
static void unchanged_core(const unsigned char before[128], const struct fcam_frame_proof *previous) {
    unsigned char after[128]; core_state(after); const struct fcam_frame_proof p = proof();
    assert(!memcmp(before, after, 128) && !memcmp(previous, &p, sizeof p));
}
static void blocked_retry(void) {
    const struct functional_vdf_path_snapshot before = owner();
    unsigned char state[128]; core_state(state); const struct fcam_frame_proof p = proof();
    const unsigned int calls = c.calls, allocations = c.allocations, sends = c.sends;
    void *request = message(10, UINT32_C(0x81cf8888)); memcpy(request, bit_request, 10); int rc = 999;
    assert(functional_vdf_path_dispatch(FUNCTIONAL_VDF_PATH_SID, request, &io, &guard, 1, &rc) == 1 && rc < 0);
    const struct functional_vdf_path_snapshot after = owner();
    assert(!memcmp(&before, &after, sizeof before) && c.calls == calls && c.allocations == allocations && c.sends == sends);
    unchanged_core(state, &p); destroy_message(request);
    puts("sticky retry_bridge_delta=0 retry_frame_delta=0 snapshot_unchanged=1 implicit_retry=0");
}
static void preflight(void) {
    prepare(0x015e, 1, UINT32_C(0x81cf5e12), 0);
    int enabled = 1;
    if (!strncmp(scenario, "selector", 8)) ((unsigned char *)c.request)[8] = (unsigned char)(scenario[8] - '0');
    else if (is("byte9")) ((unsigned char *)c.request)[9] = 1;
    else if (is("header")) ((unsigned char *)c.request)[6] = 2;
    else if (is("short") || is("long")) {
        destroy_message(c.request); c.bytes = is("short") ? 9 : 11; c.request = message(c.bytes, c.caller);
        memcpy(c.request, bit_request, c.bytes < 10 ? c.bytes : 10);
    } else if (is("unknown-source")) envelope(c.request)->source = UINT32_C(0x80940012);
    else if (is("default-off")) enabled = 0;
    unsigned char request_before[40] = {0}; memcpy(request_before, c.request, c.bytes);
    unsigned char state[128]; core_state(state); const struct fcam_frame_proof p = proof();
    const struct functional_vdf_path_snapshot before = owner();
    const unsigned int calls = c.calls, inits = c.init_calls, allocations = c.allocations, sends = c.sends;
    int rc = 999; const int handled = functional_vdf_path_dispatch(FUNCTIONAL_VDF_PATH_SID, c.request, &io, &guard, enabled, &rc);
    assert(is("default-off") ? !handled && rc == 999 : handled == 1 && rc == -ENOTSUP);
    const struct functional_vdf_path_snapshot after = owner();
    assert(!memcmp(&before, &after, sizeof before) && !memcmp(request_before, c.request, c.bytes));
    assert(c.calls == calls && c.init_calls == inits && c.allocations == allocations && c.sends == sends);
    unchanged_core(state, &p);
    printf("preflight handled=%d rc=%d bridge_delta=0 init_delta=0 frame_delta=0 ownership_delta=0 output_delta=0 owner_unchanged=1 caller_owns=1 request_wire=", handled, rc);
    hex(c.request, c.bytes); putchar('\n'); destroy_message(c.request); c.request = NULL;
}
static void *wrong_thread(void *unused) {
    (void)unused; uint64_t ticket = 0;
    assert(functional_vdf_path_observe_receive_cycle(c.caller, c.queued, source(c.queued), size(c.queued), &ticket) == -EPROTO && !ticket);
    return NULL;
}
static void bit_cycle(void) {
    const struct functional_vdf_path_snapshot old = owner();
    const unsigned int allocations = c.allocations, sends = c.sends, rf = c.request_frees, af = c.ack_frees;
    const unsigned int rfc = c.request_free_calls, afc = c.ack_free_calls;
    prepare(0x015e, 1, UINT32_C(0x81cf5e00) + c.bit_calls, 0);
    int rc = 999;
    assert(functional_vdf_path_dispatch(FUNCTIONAL_VDF_PATH_SID, c.request, &io, &guard, 1, &rc) == 1);
    struct functional_vdf_path_snapshot s = owner();
    assert(!c.held && !s.busy && !s.guard_held && c.init_calls == 1);
    assert(!memcmp(s.canonical_config, old.canonical_config, 16) && !memcmp(s.canonical_zebra8, old.canonical_zebra8, 8) &&
        !memcmp(s.canonical_layout32, old.canonical_layout32, 32) && !memcmp(s.canonical_display16, old.canonical_display16, 16) &&
        !memcmp(s.canonical_bb32, old.canonical_bb32, 32) && !memcmp(s.canonical_bit_width8, (unsigned char[8]){0}, 8));
    if (!strncmp(scenario, "corrupt-", 8)) {
        assert(rc == (is("corrupt-error") ? -EIO : -EPROTO));
        assert(s.faults && !s.model_complete && !s.request_owned && !s.ap_consumed && c.request);
        assert(!memcmp(c.request, bit_request, 10) && c.allocations == allocations && c.sends == sends && c.request_frees == rf);
        assert(s.requests == old.requests && s.completed_cycles == old.completed_cycles);
        assert(is("corrupt-error") ? s.bridge_rc == -EIO : !s.bridge_rc && s.validation_rc == -EPROTO);
        printf("refused rc=%d bridge_rc=%d validation_rc=%d caller_owns=1 core_committed=1 frame_delta=1 ack_delta=0 request_free_delta=0\n", rc, s.bridge_rc, s.validation_rc);
        blocked_retry(); destroy_message(c.request); c.request = NULL; return;
    }
    assert(!rc && s.model_complete && s.request_owned);
    assert(s.model_result_bytes == 168 && s.model_instance == instance && !memcmp(s.original_wire, bit_request, 10));
    assert(!memcmp(s.model_result, c.authentic_result, 168) &&
        !memcmp(s.model_result + 168, (unsigned char[24]){0}, sizeof s.model_result - 168));
    if (is("no-ticket")) {
        const struct functional_vdf_path_snapshot before = owner(); int free_rc = 999;
        assert(functional_vdf_path_release_cycle(c.caller, c.ack, 0, release, record, &free_rc) == 1 && free_rc == -ESTALE);
        const struct functional_vdf_path_snapshot after = owner(); assert(!memcmp(&before, &after, sizeof before));
        puts("ticket missing_rejected=1 snapshot_unchanged=1");
    }
    if (is("wrong-thread")) {
        pthread_t worker; assert(!pthread_create(&worker, NULL, wrong_thread, NULL)); assert(!pthread_join(worker, NULL));
    } else if (!is("request-free-fail") && !is("send-fail") && !is("inline") && !is("inline-send-fail")) {
        const int free_rc = consume(); assert(free_rc == (is("ack-free-fail") ? -EIO : 0));
    }
    s = owner();
    const int failed = is("request-free-fail") || is("send-fail") || is("ack-free-fail") || is("inline-send-fail") || is("wrong-thread");
    assert(s.ap_consumed == (unsigned int)!failed && s.faults == (unsigned int)failed);
    assert(s.phase == (failed ? FUNCTIONAL_VDF_PATH_FAULT : FUNCTIONAL_VDF_PATH_AP_CONSUMED));
    assert(s.requests == old.requests + 1 && s.completed_cycles == old.completed_cycles + (unsigned int)!failed);
    assert(c.request_free_calls == rfc + 1 && c.ack_free_calls <= afc + 1);
    assert(c.allocations == allocations + (unsigned int)!is("request-free-fail") &&
        c.sends == sends + (unsigned int)!is("request-free-fail"));
    assert(c.request_frees == rf + (unsigned int)!is("request-free-fail"));
    if (is("request-free-fail")) assert(s.leases[0].pointer == c.request && s.leases[0].free_rc == -EIO);
    else assert(s.leases[0].freed && !s.leases[0].pointer && c.order);
    if (is("send-fail")) assert(s.leases[1].pointer == c.ack && s.leases[1].send_rc == -EIO);
    if (is("ack-free-fail")) assert(s.leases[1].pointer == c.ack && s.leases[1].free_rc == -EIO && s.ack_received);
    if (is("wrong-thread")) assert(s.leases[1].pointer == c.ack && !s.ack_received && !s.leases[1].freed);
    if (!failed || is("inline-send-fail")) {
        assert(c.ack_frees == af + 1 && s.leases[1].freed && !s.leases[1].pointer);
        assert(s.leases[1].sender_tid == s.leases[1].receiver_tid && s.leases[1].receiver_tid == s.leases[1].free_tid);
    }
    printf("lifecycle cycle=%llu source=%08x destination=%08x request_bytes=10 ack_bytes=12 ack_wire=",
        (unsigned long long)s.cycle, s.origin.source, s.origin.destination); hex(bit_ack, 12);
    printf(" request_wire="); hex(s.original_wire, 10);
    printf(" consumed=%u faults=%u phase=%u free_before_alloc=%u same_address=%u request_frees=%u ack_frees=%u "
        "request_free_calls=%u ack_free_calls=%u sender_tid=%ld receiver_tid=%ld free_tid=%ld retained=%u config=%llu frame=%llu\n",
        s.ap_consumed, s.faults, s.phase, c.order, c.same_address, c.request_frees - rf, c.ack_frees - af,
        c.request_free_calls - rfc, c.ack_free_calls - afc, s.leases[1].sender_tid, s.leases[1].receiver_tid,
        s.leases[1].free_tid, (unsigned int)(s.leases[0].pointer != NULL) + (unsigned int)(s.leases[1].pointer != NULL),
        (unsigned long long)s.config_generation, (unsigned long long)s.frame_generation);
    if (failed) blocked_retry();
}
int main(int argc, char **argv) {
    assert(argc == 2); scenario = argv[1]; setvbuf(stdout, NULL, _IONBF, 0);
    assert(!functional_vdf_path_owner_init()); model = fcam_model_create(instance); assert(model && !proof().serial);
    const int pre = !strncmp(scenario, "selector", 8) || is("byte9") || is("header") || is("short") || is("long") ||
        is("unknown-source") || is("default-off") || is("disabled") || is("no-active");
    if (!is("no-active") && !is("default-off")) complete_legacy(0x0138, 1, UINT32_C(0x81cf0123), 0);
    if (is("disabled")) complete_legacy(0x0138, 0, UINT32_C(0x81cf4567), 0);
    if (pre) preflight();
    else {
        if (is("mixed-route")) {
            complete_legacy(0x0153, 1, UINT32_C(0x81cf0153), 0);
            complete_legacy(0x0111, 1, UINT32_C(0x81cf0111), 0);
        }
        c.reuse = (unsigned int)is("address-reuse"); bit_cycle();
        if (is("repeat") || is("address-reuse")) bit_cycle();
        if (is("mixed-route")) {
            complete_legacy(0x0138, 1, UINT32_C(0x81cf4567), 1); bit_cycle();
        }
    }
    const struct functional_vdf_path_snapshot before_cleanup = owner(); unsigned int retained = 0;
    if (c.request) { destroy_message(c.request); c.request = NULL; ++retained; }
    if (c.ack) { destroy_message(c.ack); c.ack = c.queued = c.received = NULL; ++retained; }
    const struct functional_vdf_path_snapshot after_cleanup = owner();
    assert(!memcmp(&before_cleanup, &after_cleanup, sizeof before_cleanup) && !c.pool_live);
    free(c.pool); fcam_model_destroy(model);
    printf("scope scenario=%s init_calls=%u bit_calls=%u callbacks=%u retained_explicitly_destroyed=%u "
        "owner_cleanup_unchanged=1 functional_rgb888_only=true capture_verified=false original_ap_verified=false "
        "vm_verified=false physical_asic_verified=false physical_cp_rtos_verified=false original_cp_fifo_verified=false original_selector_verified=false "
        "media_disk_writes=0\n", scenario, c.init_calls, c.bit_calls, c.callbacks, retained);
    return 0;
}
