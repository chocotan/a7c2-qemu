/* SPDX-License-Identifier: MIT */
/* HOST ONLY: actual CP registry/runtime/SDK, synthetic pagemap and native IO. */
#define main snapshot_runtime_fixture_main
#include "test-functional-face-runtime.c"
#undef main
#include "functional-face-source-snapshot.h"
#include "functional-face-sdk.h"
#include <pthread.h>
#include <sys/mman.h>

struct snapshot_fixture {
    struct functional_face_source_snapshot context;
    struct functional_face_source_snapshot_config config;
    struct functional_face_ap_provider provider;
    struct functional_face_ap_observer observer;
    struct functional_face_proc_unit current_metadata;
    struct functional_face_ap_borrow token;
    struct functional_face_sdk sdk;
    unsigned char *source_data, *frame_mapping;
    size_t frame_mapping_bytes, actual_snapshot_bytes;
    unsigned int owners, opens, calls[4], pagemap_reads, bridge_calls, callbacks, reentry;
    int ticket_fault, fail_op, helper_error, page_fault, page_drift, bridge_fault;
    unsigned int metadata_fault, metadata_fault_at;
};
static const size_t snapshot_sizes[3] = {0x64000, 0xc800, 0xd100};
static uint64_t snapshot_u64(const unsigned char *p) {
    uint64_t value = 0;
    for (unsigned int i = 0; i < 8; ++i) value |= (uint64_t)p[i] << (8 * i);
    return value;
}
/* Uninjected production fallback must never execute in this HOST fixture. */
int fcam_bridge_call(const struct fcam_native_origin *o, uint32_t op, const void *p, size_t n,
    void *out, size_t cap, struct fcam_bridge_result *r) {
    (void)o; (void)op; (void)p; (void)n; (void)out; (void)cap; (void)r; abort();
}
static void snapshot_reenter(struct snapshot_fixture *f) {
    if (!f->reentry) return;
    struct functional_face_ap_borrow out, before;
    memset(&out, 0xac, sizeof out); before = out;
    assert(f->provider.acquire(f, &f->config.saved_source, 0, f->config.saved_source.bytes, &out) == -EBUSY);
    assert(!memcmp(&out, &before, sizeof out));
}
static int snapshot_command(void *p, unsigned int op, unsigned int unit, unsigned int handle,
    struct functional_face_ap_observer *out) {
    struct snapshot_fixture *f = p;
    assert(unit == f->config.saved_source.unit && handle == f->config.saved_source.handle);
    unsigned int index = op == 0x21 ? 0 : op == 0x24 ? 1 : op == 0x25 ? 2 : 3;
    assert(op == 0x21 || op == 0x24 || op == 0x25 || op == 0x23); ++f->calls[index];
    snapshot_reenter(f);
    unsigned char *q = calloc(1, 40), *r = calloc(1, 40); assert(q && r);
    put(q, op, 2); if (op == 0x21) put(q + 4, unit, 4); put(q + 8, handle, 4);
    if (op == 0x24) put(q + 12, UINT32_MAX, 4);
    if (op == 0x23) put(q + 20, QUEUE & 0xffffu, 2);
    int status = f->fail_op == (int)op ? -7 : 0;
    if (!status) {
        if (op == 0x21) ++f->owners;
        if (op == 0x24) ++f->opens;
        if (op == 0x25) { assert(f->opens); --f->opens; }
        if (op == 0x23) { assert(f->owners); --f->owners; }
    }
    f->current_metadata.owners = f->owners; f->current_metadata.opens = f->opens;
    f->current_metadata.state = f->opens ? 2 : 1;
    put(r, op | 0x8000u, 2); put(r + 2, (uint16_t)status, 2); put(r + 12, handle, 4);
    if (op == 0x24) {
        put(r + 8, 1, 2); put(r + 24, UINT64_C(0x410300000), 8); put(r + 32, f->config.saved_source.bytes, 4);
    }
    assert(functional_face_ap_begin(&f->observer, 1, 1, THREAD_ID(), FUNCTIONAL_FACE_AP_DMM, QUEUE, q, 40, NULL) == 1);
    functional_face_ap_sent(&f->observer, THREAD_ID(), 0, NULL);
    functional_face_ap_received(&f->observer, THREAD_ID(), QUEUE, FUNCTIONAL_FACE_AP_DMM, r, 40, 0, NULL);
    functional_face_ap_freed(&f->observer, THREAD_ID(), QUEUE, r, 0, NULL);
    *out = f->observer; free(q); free(r);
    if (op == 0x21 && f->ticket_fault && f->ticket_fault <= 22) {
        switch (f->ticket_fault) {
        case 1: ++out->owner_pid; break;
        case 2: ++out->sender_tid; break;
        case 3: out->sequence = f->config.birth.observation_sequence; break;
        case 4: out->active = 1; break;
        case 5: out->dropped = 1; break;
        case 6: out->send_seen = 0; break;
        case 7: out->send_result = -EIO; break;
        case 8: out->received = 0; break;
        case 9: out->free_attempts = 0; break;
        case 10: out->free_attempts = 2; break;
        case 11: out->free_result = -EIO; break;
        case 12: out->reply_source ^= 1; break;
        case 13: out->reply_bytes = 39; break;
        case 14: out->reply_bytes = 41; break;
        case 15: out->request = 0; break;
        case 16: out->reply = 0; break;
        case 17: out->request_wire[4] ^= 1; break;
        case 18: out->request_wire[8] ^= 1; break;
        case 19: out->request_wire[39] = 1; break;
        case 20: out->reply_wire[0] ^= 1; break;
        case 21: out->births[unit - 0x1d9].ambiguous = 1; break;
        case 22: out->births[unit - 0x1d9].any_free_observed = 1; break;
        default: abort();
        }
    }
    if (op == 0x24 && f->ticket_fault >= 30) {
        switch (f->ticket_fault) {
        case 30: put(out->reply_wire + 8, 2, 2); break;
        case 31: put(out->reply_wire + 12, handle ^ 1u, 4); break;
        case 32: put(out->reply_wire + 32, f->config.saved_source.bytes - 1, 4); break;
        case 33: put(out->reply_wire + 24, UINT64_MAX - 10, 8); break;
        case 34: out->request_wire[12] = 0; break;
        default: abort();
        }
    }
    if (op == 0x23 && f->ticket_fault == 40) out->free_result = -EIO;
    if (op == 0x23 && f->ticket_fault == 41) out->request_wire[20] ^= 1;
    return f->helper_error ? -EIO : 0;
}
static int snapshot_metadata(void *p, unsigned int unit, unsigned int handle, struct functional_face_proc_unit *out) {
    struct snapshot_fixture *f = p;
    assert(unit == f->config.saved_source.unit && handle == f->config.saved_source.handle);
    struct functional_face_proc_unit *m = &f->current_metadata;
    if (f->metadata_fault && f->metadata_fault_at == f->context.metadata_calls) {
        switch (f->metadata_fault) {
        case 1: ++m->unit; break;
        case 2: ++m->handle; break;
        case 3: ++m->generation; break;
        case 4: ++m->relation; break;
        case 5: ++m->extent_id; break;
        case 6: m->address += 4096; break;
        case 7: --m->bytes; break;
        case 8: ++m->segments; break;
        case 9: ++m->owners; break;
        case 10: ++m->opens; break;
        case 11: ++m->shares; break;
        case 12: m->state = 7; break;
        case 13: return -ENODATA;
        default: abort();
        }
    }
    /* Actual typed HOST object, changed by original-operation fixture above;
     * never reconstruct a current identity from a handle or the saved birth. */
    *out = *m; return 0;
}
static long snapshot_pagemap(void *p, uintptr_t page, uint64_t *entry) {
    struct snapshot_fixture *f = p; ++f->pagemap_reads;
    uintptr_t cp = f->config.destination.host_view, sdk = f->config.frame & ~(uintptr_t)4095;
    uint64_t physical;
    if (page >= cp && page < cp + f->config.destination.mapped_bytes)
        physical = UINT64_C(0x420000000) + ((page - cp) / 4096) * 8192;
    else {
        assert(page >= sdk && page < sdk + 8192);
        physical = UINT64_C(0x430000000) + ((page - sdk) / 4096) * 8192;
    }
    if (f->page_drift && page == cp) physical += 4096;
    *entry = (UINT64_C(1) << 63) | (physical / 4096);
    switch (f->page_fault) {
    case 0: break;
    case 1: return -EACCES;
    case 2: return 7;
    case 3: *entry &= ~(UINT64_C(1) << 63); break;
    case 4: *entry |= UINT64_C(1) << 62; break;
    case 5: *entry = UINT64_C(1) << 63; break;
    case 6: if (f->pagemap_reads & 1u) *entry ^= 1; break;
    case 7:
        if (page == cp + f->config.destination.mapped_bytes - 4096)
            *entry = (UINT64_C(1) << 63) | (UINT64_C(0x420000000) / 4096);
        break;
    case 8: if (page == sdk + 4096) *entry = (UINT64_C(1) << 63) | (UINT64_C(0x420000000) / 4096); break;
    case 9: *entry = (UINT64_C(1) << 63) | ((UINT64_C(1) << 55) - 1); break;
    case 10: return -EINTR;
    case 11: if (f->pagemap_reads <= 2) return -EINTR; break;
    default: abort();
    }
    return 8;
}
static int snapshot_bridge(void *p, const struct fcam_native_origin *o, uint32_t op,
    const void *data, size_t n, void *output, size_t capacity, struct fcam_bridge_result *out) {
    struct snapshot_fixture *f = p; const unsigned char *q = data; ++f->bridge_calls;
    assert(f->owners == 2 && f->opens == f->context.baseline_opens + 1 && op == FCAM_OP_AP_SOURCE_SNAPSHOT);
    assert(o->source == f->config.saved_source.handle && o->destination == f->config.destination.handle &&
        o->command == FCAM_FACE_SNAPSHOT_COMMAND && o->bytes == 40 && o->wire_fnv1a64 == hash(f->config.raw_api40, 40));
    assert(get(q, 4) == 1 && get(q + 4, 4) == f->config.saved_source.unit);
    assert(get(q + 8, 4) == o->source && get(q + 12, 4) == o->destination && get(q + 16, 4) == capacity);
    assert(n == 360 + 8 * (get(q + 20, 4) + get(q + 24, 4)) && get(q + 28, 4) == 3);
    assert(snapshot_u64(q + 32) == f->config.saved_source.epoch && snapshot_u64(q + 40) == f->config.destination.epoch);
    assert(snapshot_u64(q + 48) == f->config.destination.registration && snapshot_u64(q + 56) == OWNER);
    assert(snapshot_u64(q + 64) == UINT64_C(0x410300000) && snapshot_u64(q + 72) == o->wire_fnv1a64);
    assert(snapshot_u64(q + 80) == f->config.birth.observation_sequence &&
        snapshot_u64(q + 88) == f->context.operations[0].sequence && snapshot_u64(q + 96) == f->context.operations[1].sequence);
    assert(get(q + 104, 4) == f->config.relation && get(q + 108, 4) == f->config.generation &&
        get(q + 112, 4) == f->config.extent_id && get(q + 116, 4) == (uint32_t)getpid() && get(q + 120, 4) == (uint32_t)THREAD_ID());
    assert(!get(q + 124, 4) && !memcmp(q + 128, f->context.operations[0].request_wire, 40) &&
        !memcmp(q + 168, f->context.operations[0].reply_wire, 40) &&
        !memcmp(q + 208, f->context.operations[1].request_wire, 40) && !memcmp(q + 248, f->context.operations[1].reply_wire, 40));
    assert(snapshot_u64(q + 288) == f->config.frame && snapshot_u64(q + 296) == f->config.api_pointer &&
        !memcmp(q + 304, f->config.raw_api40, 40) && !memcmp(q + 344, f->config.ap_descriptor, 8) &&
        !memcmp(q + 352, f->config.cp_descriptor, 8));
    assert(output == f->context.owned_snapshot && output != f->source_data &&
        output != (void *)f->config.destination.host_view && capacity == f->config.saved_source.bytes);
    snapshot_reenter(f);
    if (f->bridge_fault == 1) return -EBADMSG;
    if (f->bridge_fault == 2) return -EINVAL;
    if (f->bridge_fault == 3) return -ETIMEDOUT;
    memcpy(output, f->source_data, capacity); f->actual_snapshot_bytes += capacity;
    *out = (struct fcam_bridge_result){capacity, capacity, UINT64_C(0x1234567788), UINT64_C(0x7a0000) + f->config.saved_source.unit};
    if (f->bridge_fault == 4) --out->used;
    if (f->bridge_fault == 5) ++out->required;
    if (f->bridge_fault == 6) out->result_token = 0;
    if (f->bridge_fault == 7) out->model_instance = 0;
    return 0;
}
static void snapshot_setup(struct snapshot_fixture *f, struct functional_face_dmm_descriptor d, int cross) {
    memset(f, 0, sizeof *f); f->owners = 1;
    f->source_data = malloc(d.bytes); assert(f->source_data);
    for (size_t i = 0; i < d.bytes; ++i)
        f->source_data[i] = (unsigned char)((i * 37 + (d.unit - 0x1d9) * 53 + 11) ^ (i >> 7));
    f->frame_mapping_bytes = 8192;
    f->frame_mapping = mmap(NULL, f->frame_mapping_bytes, PROT_READ | PROT_WRITE, MAP_PRIVATE | MAP_ANONYMOUS, -1, 0);
    assert(f->frame_mapping != MAP_FAILED);
    uintptr_t frame = (uintptr_t)f->frame_mapping + (cross ? 0xfc0 : 16);
    uint32_t handle = 0x92a + d.unit - 0x1d9;
    unsigned char q[40] = {0}, r[40] = {0}; put(q, 0x20, 2); put(q + 4, d.unit, 4);
    put(q + 12, UINT32_MAX, 4); put(r, 0x8020, 2); put(r + 12, handle, 4);
    assert(functional_face_ap_begin(&f->observer, 1, 1, THREAD_ID(), FUNCTIONAL_FACE_AP_DMM, QUEUE, q, 40, NULL) == 1);
    functional_face_ap_sent(&f->observer, THREAD_ID(), 0, NULL);
    functional_face_ap_received(&f->observer, THREAD_ID(), QUEUE, FUNCTIONAL_FACE_AP_DMM, r, 40, 0, NULL);
    functional_face_ap_freed(&f->observer, THREAD_ID(), QUEUE, r, 0, NULL);
    f->config = (struct functional_face_source_snapshot_config){
        .saved_source = {0, d.unit, handle, UINT64_C(0x110000) + d.unit, OWNER ^ 0x55aa, d.bytes},
        .observer = &f->observer, .relation = 0x123, .generation = handle >> 10, .extent_id = 0x456,
        .read_current_metadata = snapshot_metadata, .metadata_context = f,
        .destination = d, .producer_owner = OWNER, .owner_pid = getpid(), .owner_tid = THREAD_ID(),
        .frame = frame, .api_pointer = frame + 0xb8, .original_caller_verified = 1,
        .original_command = snapshot_command, .command_context = f,
        .read_pagemap = snapshot_pagemap, .bridge_call = snapshot_bridge, .test_context = f};
    f->current_metadata = (struct functional_face_proc_unit){.handle = handle, .unit = d.unit, .state = 1,
        .owners = 1, .generation = handle >> 10, .relation = 0x123, .extent_id = 0x456, .segments = 1,
        .address = UINT64_C(0x410300000), .bytes = d.bytes, .row_offset = 128, .row_bytes = 138};
    f->config.born = f->current_metadata;
    assert(!functional_face_ap_observed_birth(&f->observer, THREAD_ID(), d.unit, handle, &f->config.birth));
    put(f->config.raw_api40, frame + 0x68, 8); put(f->config.raw_api40 + 8, frame + 0x70, 8);
    put(f->config.raw_api40 + 16, d.bytes, 4); put(f->config.raw_api40 + 20, 1, 4);
    put(f->config.raw_api40 + 24, 0x3514c88, 8); put(f->config.raw_api40 + 32, frame + 0x60, 8);
    put(f->config.ap_descriptor, handle, 4); put(f->config.cp_descriptor, d.handle, 4);
    memcpy((void *)(frame + 0x68), f->config.ap_descriptor, 8);
    memcpy((void *)(frame + 0x70), f->config.cp_descriptor, 8);
    memcpy((void *)f->config.api_pointer, f->config.raw_api40, 40);
}
static void snapshot_bind(struct snapshot_fixture *f) {
    assert(!functional_face_source_snapshot_init(&f->context, &f->config, &f->provider));
    assert(f->provider.context == &f->context && !f->pagemap_reads && !f->bridge_calls && !f->calls[0]);
}
static int snapshot_acquire(struct snapshot_fixture *f) {
    memset(&f->token, 0xad, sizeof f->token); struct functional_face_ap_borrow before = f->token;
    errno = ENOTTY;
    int rc = f->provider.acquire(f->provider.context, &f->config.saved_source, 0, f->config.saved_source.bytes, &f->token);
    assert(errno == ENOTTY);
    if (rc) assert(!memcmp(&f->token, &before, sizeof before));
    return rc;
}
static void snapshot_no_retry(struct snapshot_fixture *f) {
    unsigned int calls[4]; memcpy(calls, f->calls, sizeof calls); unsigned int bridge = f->bridge_calls;
    struct functional_face_ap_borrow out, before; memset(&out, 0xcc, sizeof out); before = out;
    assert(f->provider.acquire(f->provider.context, &f->config.saved_source, 0, f->config.saved_source.bytes, &out) < 0);
    assert(!memcmp(&out, &before, sizeof out) && !memcmp(calls, f->calls, sizeof calls) && bridge == f->bridge_calls);
}
static void snapshot_destroy(struct snapshot_fixture *f) {
    /* HOST fixture teardown only, after retained context assertions. No such
     * forced cleanup entry point exists in the production provider. */
    free(f->context.owned_snapshot); free(f->source_data);
    assert(!munmap(f->frame_mapping, f->frame_mapping_bytes));
}
static long snapshot_descriptor(void *p, uintptr_t address, void *out, size_t bytes) {
    struct snapshot_fixture *f = p;
    assert(bytes == 8 && (address == f->config.frame + 0x68 || address == f->config.frame + 0x70));
    memcpy(out, (void *)address, bytes); return 8;
}
static int snapshot_sdk_callback(void *p, uintptr_t callback, int32_t status, uintptr_t context) {
    struct snapshot_fixture *f = p;
    assert(callback == 0x3514c88 && !status && context == f->config.frame + 0x60);
    assert(f->owners == 1 && !f->opens && !f->context.owner_live && !f->context.open_live &&
        !f->context.owned_snapshot && !f->context.snapshot_live && !f->context.uncertain);
    assert(!f->sdk.transfer.source_live && !f->sdk.transfer.destination_live && f->sdk.transfer.last.content_complete);
    for (unsigned int i = 0; i < 4; ++i) assert(f->calls[i] == 1);
    struct functional_face_dmm_snapshot cp; assert(!functional_face_dmm_snapshot(&cp));
    assert(!cp.units[f->config.destination.unit - 0x1d9].borrows && !cp.units[f->config.destination.unit - 0x1d9].transfers);
    ++f->callbacks; return 0;
}
static void snapshot_three_units(void) {
    setup(); size_t total = 0;
    unsigned char *speech = malloc(DMM_TEST_SIZE); assert(speech);
    for (size_t i = 0; i < DMM_TEST_SIZE; ++i) speech[i] = (unsigned char)(i ^ (i >> 9) ^ 0x95);
    uint64_t speech_before = hash(speech, DMM_TEST_SIZE);
    for (unsigned int i = 0; i < 3; ++i) {
        struct functional_face_dmm_descriptor d = create(0x1d9 + i);
        struct snapshot_fixture f; snapshot_setup(&f, d, i != 1); snapshot_bind(&f);
        struct functional_face_sdk_binding b = {.saved_source = f.config.saved_source, .provider = f.provider,
            .producer_owner = OWNER, .owner_pid = getpid(), .owner_tid = THREAD_ID(),
            .read_descriptor = snapshot_descriptor, .reader_context = &f, .invoke_callback = snapshot_sdk_callback, .callback_context = &f};
        assert(!functional_face_sdk_init(&f.sdk, &b));
        struct functional_face_sdk_transaction out;
        assert(!functional_face_sdk_submit(&f.sdk, (void *)f.config.api_pointer, 40, 1, 0, &out));
        assert(f.callbacks == 1 && f.actual_snapshot_bytes == snapshot_sizes[i] && out.copy.written == d.bytes && out.copy.readback == d.bytes);
        assert(f.context.cp_count == (d.mapped_bytes / 4096) && f.context.sdk_count == (i == 1 ? 1u : 2u));
        assert(!f.context.original_global_writer_verified && !f.context.kernel_atomic_snapshot_verified && !f.context.physical_asic_verified);
        struct functional_face_dmm_borrow borrow; struct functional_face_dmm_readback rb;
        assert(!functional_face_runtime_borrow_destination(OWNER, d.unit, d.handle, &d, 0, d.bytes, FUNCTIONAL_FACE_DMM_READ, &borrow));
        unsigned char *actual = malloc(d.bytes); assert(actual);
        assert(!functional_face_dmm_read(&borrow, 0, actual, d.bytes, &rb));
        assert(rb.verified_bytes == d.bytes && !memcmp(actual, f.source_data, d.bytes));
        assert(!functional_face_dmm_release_borrow(&borrow, &rb)); free(actual);
        printf("SNAPSHOT_HOST_BYTES unit=%x bytes=%zu digest=%016" PRIx64 " cp_pages=%u sdk_pages=%u original_owner=1 callback_leases=0\n",
            d.unit, d.bytes, out.copy.source_digest, f.context.cp_count, f.context.sdk_count);
        total += d.bytes; snapshot_no_retry(&f); snapshot_destroy(&f); (void)operation(0x23, d.unit, d.handle, 0, 0);
    }
    assert(total == 514304 && speech_before == hash(speech, DMM_TEST_SIZE)); free(speech);
    assert(!functional_face_dmm_shutdown());
    puts("SNAPSHOT_HOST_COUNTS units=3 snapshot=514304 cp_write=514304 cp_readback=514304 independent_read=514304 callbacks=3 speech_bytes=1048576 speech_unchanged=1 synthetic_pfn=1 native_verified=0");
}
static void snapshot_init_errors(void) {
    setup(); struct functional_face_dmm_descriptor d = create(0x1da);
    for (unsigned int i = 0; i < 23; ++i) {
        struct snapshot_fixture f; snapshot_setup(&f, d, 1);
        if (i == 0) f.config.birth.ambiguous = 1;
        if (i == 1) f.config.birth.any_free_observed = 1;
        if (i == 2) ++f.config.birth.observation_sequence;
        if (i == 3) ++f.config.owner_pid;
        if (i == 4) ++f.config.owner_tid;
        if (i == 5) f.config.saved_source.epoch = 0;
        if (i == 6) f.config.relation = 0;
        if (i == 7) ++f.config.generation;
        if (i == 8) f.config.extent_id = 0;
        if (i == 9) f.config.destination.mapped_bytes -= 4096;
        if (i == 10) ++f.config.destination.host_view;
        if (i == 11) f.config.original_command = NULL;
        if (i == 12) f.config.original_caller_verified = 0;
        if (i == 13) ++f.config.frame;
        if (i == 14) ++f.config.api_pointer;
        if (i == 15) f.config.raw_api40[20] = 0;
        if (i == 16) f.config.ap_descriptor[4] = 1;
        if (i == 17) f.config.cp_descriptor[4] = 1;
        if (i == 18) --f.config.saved_source.bytes;
        if (i == 19) f.config.birth.observations = 2;
        if (i == 20) f.config.read_current_metadata = NULL;
        if (i == 21) f.config.born.address = UINT64_MAX - 3;
        if (i == 22) ++f.config.born.owners;
        struct functional_face_source_snapshot before = f.context;
        memset(&f.provider, 0x9a, sizeof f.provider); struct functional_face_ap_provider out = f.provider;
        assert(functional_face_source_snapshot_init(&f.context, &f.config, &f.provider) < 0);
        assert(!memcmp(&before, &f.context, sizeof before) && !memcmp(&out, &f.provider, sizeof out));
        assert(!f.calls[0] && !f.pagemap_reads && !f.bridge_calls); snapshot_destroy(&f);
    }
    (void)operation(0x23, d.unit, d.handle, 0, 0); assert(!functional_face_dmm_shutdown());
}
static void snapshot_ticket_errors(void) {
    setup(); struct functional_face_dmm_descriptor d = create(0x1da);
    for (int i = 1; i <= 24; ++i) {
        struct snapshot_fixture f; snapshot_setup(&f, d, 1); snapshot_bind(&f);
        if (i <= 22) f.ticket_fault = i;
        if (i == 23) f.fail_op = 0x21;
        if (i == 24) f.helper_error = 1;
        assert(snapshot_acquire(&f) < 0);
        assert(f.context.claimed && f.context.faulted && f.context.uncertain && f.context.provider_may_retain);
        assert(f.calls[0] == 1 && !f.calls[1] && !f.calls[2] && !f.calls[3] && !f.bridge_calls);
        if (i == 23) assert((int16_t)get(f.context.operations[0].reply_wire + 2, 2) == -7);
        snapshot_no_retry(&f); snapshot_destroy(&f);
    }
    for (int i = 30; i <= 34; ++i) {
        struct snapshot_fixture f; snapshot_setup(&f, d, 1); snapshot_bind(&f); f.ticket_fault = i;
        assert(snapshot_acquire(&f) < 0 && f.context.uncertain && f.calls[1] == 1 && !f.calls[2] && !f.calls[3]);
        snapshot_no_retry(&f); snapshot_destroy(&f);
    }
    struct snapshot_fixture f; snapshot_setup(&f, d, 1); snapshot_bind(&f); f.fail_op = 0x24;
    assert(snapshot_acquire(&f) == -EREMOTEIO);
    assert(f.calls[0] == 1 && f.calls[1] == 1 && !f.calls[2] && f.calls[3] == 1 && f.owners == 1 && !f.opens);
    assert(f.context.faulted && !f.context.uncertain && !f.context.provider_may_retain);
    snapshot_no_retry(&f); snapshot_destroy(&f); (void)operation(0x23, d.unit, d.handle, 0, 0); assert(!functional_face_dmm_shutdown());
}
static void snapshot_page_errors(void) {
    setup(); struct functional_face_dmm_descriptor d = create(0x1da);
    for (int i = 1; i <= 11; ++i) {
        struct snapshot_fixture f; snapshot_setup(&f, d, 1); snapshot_bind(&f); f.page_fault = i;
        if (i == 11) {
            assert(!snapshot_acquire(&f));
            unsigned char *out = malloc(d.bytes); assert(out);
            assert(f.provider.read(f.provider.context, &f.token, 0, out, d.bytes) == (long)d.bytes);
            assert(!f.provider.release(f.provider.context, &f.token)); free(out);
        } else {
            assert(snapshot_acquire(&f) < 0 && f.context.faulted && !f.context.uncertain);
            assert(!f.calls[0] && !f.bridge_calls && !f.context.provider_may_retain);
        }
        snapshot_no_retry(&f); snapshot_destroy(&f);
    }
    (void)operation(0x23, d.unit, d.handle, 0, 0); assert(!functional_face_dmm_shutdown());
}
static void snapshot_bridge_errors(void) {
    setup(); struct functional_face_dmm_descriptor d = create(0x1da);
    for (int i = 1; i <= 7; ++i) {
        struct snapshot_fixture f; snapshot_setup(&f, d, 1); snapshot_bind(&f); f.bridge_fault = i;
        assert(snapshot_acquire(&f) < 0 && f.context.faulted && f.bridge_calls == 1);
        assert(f.context.uncertain && f.context.provider_may_retain && f.context.owned_snapshot && !f.calls[2] && !f.calls[3]);
        snapshot_no_retry(&f); snapshot_destroy(&f);
    }
    (void)operation(0x23, d.unit, d.handle, 0, 0); assert(!functional_face_dmm_shutdown());
}
static void snapshot_tokens(void) {
    setup(); struct functional_face_dmm_descriptor d = create(0x1da);
    struct snapshot_fixture f; snapshot_setup(&f, d, 1); snapshot_bind(&f); f.reentry = 1;
    f.opens = 1; f.current_metadata.opens = 1; f.current_metadata.state = 2;
    assert(!snapshot_acquire(&f) && f.context.baseline_opens == 1 && f.opens == 2);
    unsigned char *out = malloc(d.bytes); assert(out); memset(out, 0xab, d.bytes);
    struct functional_face_ap_borrow stale = f.token; ++stale.nonce;
    assert(f.provider.read(f.provider.context, &stale, 0, out, d.bytes) == -ESTALE && out[0] == 0xab);
    stale = f.token; ++stale.span.epoch;
    assert(f.provider.release(f.provider.context, &stale) == -ESTALE && !f.calls[2]);
    assert(f.provider.read(f.provider.context, &f.token, 1, out, d.bytes - 1) == -ESTALE && out[0] == 0xab);
    assert(!f.provider.check_disjoint(f.provider.context, &f.token, &d));
    unsigned char original = f.source_data[0]; f.source_data[0] ^= 0xff;
    assert(f.provider.read(f.provider.context, &f.token, 0, out, d.bytes) == (long)d.bytes && out[0] == original);
    assert(!f.provider.release(f.provider.context, &f.token) && f.owners == 1 && f.opens == 1);
    puts("SNAPSHOT_ORIGINAL_OPEN baseline=1 after=1 original_owner=1 provider_open=0 provider_owner=0");
    assert(f.provider.read(f.provider.context, &f.token, 0, out, 1) == -ESTALE);
    assert(f.provider.release(f.provider.context, &f.token) == -ESTALE);
    snapshot_no_retry(&f); snapshot_destroy(&f); free(out);
    (void)operation(0x23, d.unit, d.handle, 0, 0); assert(!functional_face_dmm_shutdown());
}
static void snapshot_drift_release(void) {
    setup(); struct functional_face_dmm_descriptor d = create(0x1da);
    for (unsigned int i = 0; i < 8; ++i) {
        struct snapshot_fixture f; snapshot_setup(&f, d, 1); snapshot_bind(&f); assert(!snapshot_acquire(&f));
        unsigned char *out = malloc(d.bytes); assert(out);
        if (i < 2) {
            if (i == 0) f.page_drift = 1;
            struct functional_face_dmm_descriptor changed = d; if (i == 1) ++changed.registration;
            assert(f.provider.check_disjoint(f.provider.context, &f.token, &changed) == -ESTALE);
            assert(!f.calls[2] && !f.calls[3]);
        } else if (i == 2) assert(f.provider.release(f.provider.context, &f.token) == -ENODATA);
        else {
            assert(f.provider.read(f.provider.context, &f.token, 0, out, d.bytes) == (long)d.bytes);
            if (i == 3) f.fail_op = 0x25;
            if (i == 4) f.fail_op = 0x23;
            if (i == 5) f.helper_error = 1;
            if (i == 6) f.ticket_fault = 40;
            if (i == 7) f.ticket_fault = 41;
            assert(f.provider.release(f.provider.context, &f.token) < 0);
            assert(f.calls[2] == 1 && f.calls[3] == (i == 4 || i >= 6));
        }
        assert(f.context.faulted && f.context.provider_may_retain && f.context.owned_snapshot);
        snapshot_no_retry(&f); snapshot_destroy(&f); free(out);
    }
    (void)operation(0x23, d.unit, d.handle, 0, 0); assert(!functional_face_dmm_shutdown());
}
static void snapshot_identity_errors(void) {
    setup(); struct functional_face_dmm_descriptor d = create(0x1da);
    for (unsigned int i = 0; i < 14; ++i) {
        struct snapshot_fixture f; snapshot_setup(&f, d, 1); snapshot_bind(&f);
        struct functional_face_dmm_descriptor *current = &state.units[1].creator;
        struct functional_face_dmm_descriptor saved = *current;
        if (i == 0) ++current->epoch;
        if (i == 1) ++current->owner;
        if (i == 2) ++current->reference;
        if (i == 3) ++current->logical;
        if (i == 4) ++current->registration;
        if (i == 5) current->host_view += 4096;
        if (i == 6) --current->bytes;
        if (i == 7) current->mapped_bytes += 4096;
        if (i == 8) ++current->unit;
        if (i == 9) ++current->handle;
        if (i == 10) ++current->domain;
        if (i == 11) f.observer.births[1].any_free_observed = 1;
        if (i == 12) f.observer.births[1].ambiguous = 1;
        if (i == 13) ++f.observer.births[1].observation_sequence;
        assert(snapshot_acquire(&f) < 0 && f.context.claimed && f.context.faulted);
        assert(!f.calls[0] && !f.bridge_calls && !f.context.provider_may_retain);
        *current = saved; snapshot_no_retry(&f); snapshot_destroy(&f);
    }
    struct snapshot_fixture f; snapshot_setup(&f, d, 1); snapshot_bind(&f); assert(!snapshot_acquire(&f));
    unsigned char byte = 0xa9; f.context.owned_snapshot[0] ^= 1;
    assert(f.provider.read(f.provider.context, &f.token, 0, &byte, 1) == -EBADMSG && byte == 0xa9);
    assert(f.context.faulted && f.context.provider_may_retain && !f.calls[2]);
    snapshot_no_retry(&f); snapshot_destroy(&f);
    (void)operation(0x23, d.unit, d.handle, 0, 0); assert(!functional_face_dmm_shutdown());
}
static void snapshot_metadata_errors(void) {
    setup(); struct functional_face_dmm_descriptor d = create(0x1da);
    for (unsigned int stage = 1; stage <= 6; ++stage) {
        for (unsigned int error = 1; error <= 13; ++error) {
            struct snapshot_fixture f; snapshot_setup(&f, d, 1); snapshot_bind(&f);
            f.metadata_fault = error; f.metadata_fault_at = stage;
            int rc = snapshot_acquire(&f);
            if (stage <= 3) {
                assert(rc < 0 && !f.bridge_calls);
                assert(f.calls[0] == (stage > 1) && f.calls[1] == (stage > 2));
                assert(f.context.provider_may_retain == (stage > 1));
            } else {
                assert(!rc && f.context.snapshot_live);
                unsigned char *out = malloc(d.bytes); assert(out);
                assert(f.provider.read(f.provider.context, &f.token, 0, out, d.bytes) == (long)d.bytes);
                assert(f.provider.release(f.provider.context, &f.token) < 0); free(out);
                assert(f.context.owned_snapshot && f.context.provider_may_retain && f.context.uncertain);
                assert(f.calls[2] == (stage > 4) && f.calls[3] == (stage > 5));
            }
            assert(f.context.claimed && f.context.faulted && f.context.metadata_calls == stage);
            snapshot_no_retry(&f); snapshot_destroy(&f);
        }
    }
    (void)operation(0x23, d.unit, d.handle, 0, 0); assert(!functional_face_dmm_shutdown());
}
static void *snapshot_wrong_thread(void *p) {
    struct snapshot_fixture *f = p; struct functional_face_ap_borrow out;
    assert(f->provider.acquire(f->provider.context, &f->config.saved_source, 0, f->config.saved_source.bytes, &out) == -ECHILD);
    assert(functional_face_source_snapshot_init(&f->context, &f->config, &f->provider) == -ECHILD); return NULL;
}
static void snapshot_fork_thread(void) {
    setup(); struct functional_face_dmm_descriptor d = create(0x1da);
    struct snapshot_fixture f; snapshot_setup(&f, d, 1); snapshot_bind(&f); atomic_store(&f.context.busy, 1);
    pthread_t t; assert(!pthread_create(&t, NULL, snapshot_wrong_thread, &f)); assert(!pthread_join(t, NULL));
    pid_t child = fork(); assert(child >= 0); if (!child) { snapshot_wrong_thread(&f); _exit(0); }
    int status; assert(waitpid(child, &status, 0) == child && WIFEXITED(status) && !WEXITSTATUS(status));
    assert(!f.context.attempted && !f.calls[0]); atomic_store(&f.context.busy, 0); snapshot_destroy(&f);
    (void)operation(0x23, d.unit, d.handle, 0, 0); assert(!functional_face_dmm_shutdown());
}
int main(int argc, char **argv) {
    assert(argc == 2);
    if (!strcmp(argv[1], "three-units")) snapshot_three_units();
    else if (!strcmp(argv[1], "init")) snapshot_init_errors();
    else if (!strcmp(argv[1], "ticket")) snapshot_ticket_errors();
    else if (!strcmp(argv[1], "pagemap")) snapshot_page_errors();
    else if (!strcmp(argv[1], "bridge")) snapshot_bridge_errors();
    else if (!strcmp(argv[1], "tokens")) snapshot_tokens();
    else if (!strcmp(argv[1], "drift-release")) snapshot_drift_release();
    else if (!strcmp(argv[1], "identity")) snapshot_identity_errors();
    else if (!strcmp(argv[1], "metadata")) snapshot_metadata_errors();
    else if (!strcmp(argv[1], "fork-thread")) snapshot_fork_thread();
    else abort();
    printf("FACE_SOURCE_SNAPSHOT_GUEST_HOST_PASS mode=%s synthetic_pfn=1 native_verified=0 capture_verified=0\n", argv[1]);
    return 0;
}
