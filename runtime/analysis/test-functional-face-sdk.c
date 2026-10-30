/* SPDX-License-Identifier: MIT */
/* The generated include only renames the unchanged native fixture's main. */
#define __wrap_functional_face_dmm_release_borrow fixture_cp_release
#include "sdk-native-fixture.inc"
#undef __wrap_functional_face_dmm_release_borrow
#include "functional-face-sdk.h"

struct sdk_fixture {
    struct native_model native;
    struct functional_face_sdk sdk;
    struct functional_face_sdk_binding binding;
    struct functional_face_sdk_transaction out;
    struct functional_face_dmm_descriptor destination;
    unsigned char source8[8], destination8[8], context[32];
    unsigned char saved_source8[8], saved_destination8[8], saved_context[32], saved_api40[40];
    unsigned char *api;
    unsigned int descriptor_reads, invokes, typed_calls, unstable, short_read, fault, reentry;
    unsigned int reentered[3], old_write_releases, old_read_releases;
    uint64_t old_cp_write, old_cp_read;
    int invoke_result;
};
static struct sdk_fixture *active_sdk;
int __real_functional_face_dmm_write(const struct functional_face_dmm_borrow *, size_t,
    const void *, size_t, struct functional_face_dmm_readback *);
int __real_functional_face_dmm_read(const struct functional_face_dmm_borrow *, size_t,
    void *, size_t, struct functional_face_dmm_readback *);
int __wrap_functional_face_dmm_write(const struct functional_face_dmm_borrow *b, size_t off,
    const void *p, size_t n, struct functional_face_dmm_readback *r) {
    struct functional_face_dmm_borrow actual = *b;
    if (active_sdk && active_sdk->fault == 1) ++actual.span.registration;
    return __real_functional_face_dmm_write(&actual, off, p, n, r);
}
int __wrap_functional_face_dmm_read(const struct functional_face_dmm_borrow *b, size_t off,
    void *p, size_t n, struct functional_face_dmm_readback *r) {
    struct functional_face_dmm_borrow actual = *b;
    if (active_sdk && active_sdk->fault == 2) ++actual.nonce;
    return __real_functional_face_dmm_read(&actual, off, p, n, r);
}
int __wrap_functional_face_dmm_release_borrow(const struct functional_face_dmm_borrow *b,
    struct functional_face_dmm_readback *r) {
    struct functional_face_dmm_borrow actual = *b;
    if (active_sdk && active_sdk->fault == 3) ++actual.nonce;
    return fixture_cp_release(&actual, r);
}
static void sdk_reenter(struct sdk_fixture *f, unsigned int stage) {
    if (!f->reentry || f->reentered[stage]) return;
    ++f->reentered[stage];
    struct functional_face_sdk_transaction out, saved, last = f->sdk.last;
    memset(&out, 0xa7, sizeof out); saved = out;
    assert(functional_face_sdk_submit(&f->sdk, (void *)(uintptr_t)1, 40, 1, 0, &out) == -EBUSY);
    assert(!memcmp(&out, &saved, sizeof out) && !memcmp(&last, &f->sdk.last, sizeof last));
}
static long sdk_physical_read(void *p, const struct functional_face_native_ap_mapping *mapping,
    uint64_t address, void *out, size_t bytes) {
    struct sdk_fixture *f = p; /* native is the first member, same pointer value. */
    sdk_reenter(f, 1);
    return model_read(&f->native, mapping, address, out, bytes);
}
static long sdk_descriptor_read(void *p, uintptr_t address, void *out, size_t bytes) {
    struct sdk_fixture *f = p;
    assert(bytes == 8);
    assert(address == (uintptr_t)((f->descriptor_reads & 1u) ? f->destination8 : f->source8));
    ++f->descriptor_reads; sdk_reenter(f, 0);
    memcpy(out, (void *)address, bytes);
    if (f->unstable && f->descriptor_reads == 3) ((unsigned char *)out)[0] ^= 1;
    return f->short_read ? 7 : (long)bytes;
}
static void sdk_typed_callback(int32_t status, void *context) {
    struct sdk_fixture *f = active_sdk; assert(f);
    assert(status == 0 && context == f->context);
    assert(f->sdk.last.callback_attempted && !f->sdk.last.callback_returned);
    assert(f->sdk.last.copy.content_complete && f->sdk.last.copy.source_released && f->sdk.last.copy.destination_released);
    assert(f->sdk.last.copy.written == f->destination.bytes && f->sdk.last.copy.readback == f->destination.bytes);
    assert(!f->sdk.transfer.source_live && !f->sdk.transfer.destination_live && !f->sdk.transfer.faulted);
    assert(!atomic_load(&f->sdk.transfer.busy));
    assert(!f->native.context.source_live && !f->native.context.owner_live && !f->native.context.open_live &&
        !f->native.context.writer_live && !f->native.context.faulted);
    assert(f->native.calls[0] == 1 && f->native.calls[1] == 1 && f->native.calls[2] == 1 && f->native.calls[3] == 1);
    assert(f->native.end_calls == 1 && f->native.current.owners == (f->native.drop_on_read ? 0u : 1u));
    assert(f->native.actual_read == f->destination.bytes);
    assert(cp_writer_releases == f->old_write_releases + 1 && cp_reader_releases == f->old_read_releases + 1);
    struct functional_face_dmm_snapshot cp; assert(!functional_face_dmm_snapshot(&cp));
    const struct functional_face_dmm_unit_snapshot *u = &cp.units[f->destination.unit - 0x1d9];
    assert(!u->borrows && !u->transfers && u->verified_write_bytes - f->old_cp_write == f->destination.bytes &&
        u->verified_read_bytes - f->old_cp_read == f->destination.bytes);
    assert(f->sdk.last.copy.source_digest == hash(f->native.expected, f->destination.bytes));
    assert(f->sdk.last.copy.source_digest == f->sdk.last.copy.destination_digest);
    ++f->typed_calls;
}
static int sdk_invoke(void *p, uintptr_t callback, int32_t status, uintptr_t context) {
    struct sdk_fixture *f = p; ++f->invokes;
    assert(callback == (uintptr_t)0x3514c88 && context == (uintptr_t)f->context && active_sdk == f);
    sdk_reenter(f, 2);
    void (*original)(int32_t, void *) = sdk_typed_callback;
    original(status, (void *)context);
    return f->invoke_result;
}
static void sdk_save_inputs(struct sdk_fixture *f) {
    memcpy(f->saved_api40, f->api, 40); memcpy(f->saved_source8, f->source8, 8);
    memcpy(f->saved_destination8, f->destination8, 8); memcpy(f->saved_context, f->context, 32);
}
static void sdk_unchanged(const struct sdk_fixture *f) {
    assert(!memcmp(f->api, f->saved_api40, 40) && !memcmp(f->source8, f->saved_source8, 8));
    assert(!memcmp(f->destination8, f->saved_destination8, 8) && !memcmp(f->context, f->saved_context, 32));
}
static void sdk_prepare(struct sdk_fixture *f, unsigned int index, struct functional_face_dmm_descriptor d) {
    memset(f, 0, sizeof *f); model_setup(&f->native, index); model_bind(&f->native);
    f->native.context.ops.read_physical = sdk_physical_read;
    f->destination = d; f->api = malloc(40); assert(f->api); memset(f->api, 0, 40);
    put(f->source8, f->native.birth.span.handle, 4); put(f->destination8, d.handle, 4);
    for (unsigned int i = 0; i < sizeof f->context; ++i) f->context[i] = (unsigned char)(i * 17 + 9);
    put(f->context, f->native.birth.span.handle, 4);
    put(f->api, (uintptr_t)f->source8, 8); put(f->api + 8, (uintptr_t)f->destination8, 8);
    put(f->api + 16, d.bytes, 4); put(f->api + 20, 1, 4);
    put(f->api + 24, 0x3514c88, 8); put(f->api + 32, (uintptr_t)f->context, 8);
    f->binding = (struct functional_face_sdk_binding){.saved_source = f->native.birth.span,
        .provider = f->native.provider, .producer_owner = OWNER, .owner_pid = getpid(), .owner_tid = THREAD_ID(),
        .read_descriptor = sdk_descriptor_read, .reader_context = f,
        .invoke_callback = sdk_invoke, .callback_context = f};
    f->old_write_releases = cp_writer_releases; f->old_read_releases = cp_reader_releases;
    struct functional_face_dmm_snapshot cp; assert(!functional_face_dmm_snapshot(&cp));
    f->old_cp_write = cp.units[index].verified_write_bytes; f->old_cp_read = cp.units[index].verified_read_bytes;
    sdk_save_inputs(f);
}
static void sdk_initialize(struct sdk_fixture *f) {
    assert(!functional_face_sdk_init(&f->sdk, &f->binding));
    assert(!f->native.writer_calls && !f->native.calls[0] && !f->native.physical_calls && !f->descriptor_reads);
    assert(f->sdk.binding.saved_source.epoch == f->binding.saved_source.epoch);
}
static int sdk_run(struct sdk_fixture *f, const void *api, size_t bytes, int bound, int sender) {
    assert(!active_sdk); active_sdk = f;
    int rc = functional_face_sdk_submit(&f->sdk, api, bytes, bound, sender, &f->out);
    active_sdk = NULL; sdk_unchanged(f);
    assert(!memcmp(&f->out, &f->sdk.last, sizeof f->out));
    printf("SDK_CASE rc=%d claimed=%u started=%u acquire=%u written=%zu readback=%zu content=%u source_live=%u destination_live=%u provider_may_retain=%u callback=%u uncertain=%u\n",
        rc, f->out.claimed, f->out.started, f->out.copy.source_acquired, f->out.copy.written,
        f->out.copy.readback, f->out.copy.content_complete, f->out.source_live, f->out.destination_live,
        f->out.provider_may_retain, f->out.callback_attempted, f->out.callback_uncertain);
    return rc;
}
static void sdk_no_completion(const struct sdk_fixture *f, int claimed) {
    assert(f->out.claimed == (unsigned int)claimed && f->out.started == (unsigned int)claimed);
    assert(!f->invokes && !f->typed_calls && !f->out.callback_attempted && !f->out.callback_returned);
    if (!claimed) assert(!f->native.writer_calls && !f->native.calls[0] && !f->native.physical_calls);
}
static void sdk_no_retry(struct sdk_fixture *f) {
    struct functional_face_sdk_transaction out, saved, last = f->sdk.last;
    unsigned int calls[4]; memcpy(calls, f->native.calls, sizeof calls);
    memset(&out, 0xa9, sizeof out); saved = out;
    assert(functional_face_sdk_submit(&f->sdk, f->api, 40, 1, 0, &out) == -EALREADY);
    assert(!memcmp(&out, &saved, sizeof out) && !memcmp(&last, &f->sdk.last, sizeof last));
    assert(!memcmp(calls, f->native.calls, sizeof calls));
}
static void sdk_destroy(struct sdk_fixture *f) {
    /* Test-only process teardown after retained evidence assertions. Production
     * must keep contexts/resources; the frontend has no cleanup/retry API. */
    if (f->sdk.transfer.destination_live) {
        struct functional_face_dmm_readback rb;
        assert(!__real_functional_face_dmm_release_borrow(&f->sdk.transfer.destination, &rb));
    }
    model_destroy(&f->native); free(f->api);
}
static void sdk_cp_finish(struct functional_face_dmm_descriptor d) {
    (void)operation(0x23, d.unit, d.handle, 0, 0);
    assert(!functional_face_dmm_shutdown());
}
static void sdk_missing(void) {
    setup(); struct functional_face_dmm_descriptor d = create(0x1da);
    struct sdk_fixture f; sdk_prepare(&f, 1, d);
    assert(functional_face_sdk_init(NULL, &f.binding) == -EINVAL);
    assert(functional_face_sdk_init(&f.sdk, NULL) == -ENODATA);
    for (unsigned int i = 0; i < 7; ++i) {
        struct functional_face_sdk_binding b = f.binding;
        if (i == 0) b.provider.acquire = NULL;
        if (i == 1) b.provider.read = NULL;
        if (i == 2) b.provider.check_disjoint = NULL;
        if (i == 3) b.provider.release = NULL;
        if (i == 4) b.read_descriptor = NULL;
        if (i == 5) b.invoke_callback = NULL;
        if (i == 6) b.producer_owner = 0;
        struct functional_face_sdk before = f.sdk;
        assert(functional_face_sdk_init(&f.sdk, &b) == -ENODATA && !memcmp(&before, &f.sdk, sizeof before));
    }
    assert(functional_face_sdk_submit(&f.sdk, f.api, 40, 1, 0, &f.out) == -ENODATA);
    sdk_initialize(&f);
    assert(functional_face_sdk_submit(&f.sdk, f.api, 40, 1, 0, NULL) == -EINVAL && !f.sdk.submitted);
    assert(functional_face_sdk_init(&f.sdk, &f.binding) == -EALREADY);
    assert(!f.native.calls[0] && !f.native.writer_calls && !f.descriptor_reads && !f.invokes);
    sdk_unchanged(&f); sdk_destroy(&f); sdk_cp_finish(d);
}
static void sdk_api_extent(void) {
    setup(); struct functional_face_dmm_descriptor d = create(0x1da);
    for (unsigned int i = 0; i < 8; ++i) {
        struct sdk_fixture f; sdk_prepare(&f, 1, d);
        size_t bytes = i == 0 ? 39 : i == 1 ? 41 : 40;
        if (i == 3) put(f.api + 20, 2, 4);
        if (i == 4) put(f.api + 24, 0, 8);
        if (i == 5) put(f.api + 32, 0, 8);
        if (i == 6) put(f.api, 0, 8);
        if (i == 7) put(f.api + 8, UINT64_MAX - 1, 8);
        sdk_save_inputs(&f); sdk_initialize(&f);
        assert(sdk_run(&f, i == 2 ? NULL : f.api, bytes, 1, 0) < 0);
        sdk_no_completion(&f, 0); assert(!f.descriptor_reads); sdk_no_retry(&f); sdk_destroy(&f);
    }
    struct sdk_fixture f; sdk_prepare(&f, 1, d);
    f.native.current.opens = 1; f.native.current.state = 2;
    sdk_initialize(&f);
    /* malloc's ACTUAL 40B extent: ASan catches any attempt to consume byte40. */
    assert(!sdk_run(&f, f.api, 40, 1, 0) && f.descriptor_reads == 4);
    assert(f.native.current.opens == 1 && f.native.current.state == 2 && f.native.current.owners == 1);
    assert(f.out.decoded && f.out.class_id == 1 && !memcmp(f.out.api40, f.api, 40));
    assert(f.out.request.callback == 0x3514c88 && f.out.request.callback_context == (uintptr_t)f.context);
    sdk_no_retry(&f); sdk_destroy(&f); sdk_cp_finish(d);
}
static void sdk_descriptors(void) {
    setup(); struct functional_face_dmm_descriptor d = create(0x1da);
    for (unsigned int i = 0; i < 7; ++i) {
        struct sdk_fixture f; sdk_prepare(&f, 1, d);
        if (i == 0) f.unstable = 1;
        if (i == 1) f.short_read = 1;
        if (i == 2) put(f.source8 + 4, 1, 4);
        if (i == 3) put(f.destination8 + 4, 1, 4);
        if (i == 4) put(f.api + 16, d.bytes - 1, 4);
        if (i == 5) put(f.source8, 0x8403, 4);
        if (i == 6) put(f.destination8, 0x403, 4);
        sdk_save_inputs(&f); sdk_initialize(&f);
        assert(sdk_run(&f, f.api, 40, 1, 0) == (i == 0 ? -ESTALE : i == 1 ? -EIO : -ENOTSUP));
        assert(f.descriptor_reads == 4); sdk_no_completion(&f, 0); sdk_destroy(&f);
    }
    sdk_cp_finish(d);
}
static void sdk_source_binding(void) {
    setup(); struct functional_face_dmm_descriptor d = create(0x1da);
    for (unsigned int i = 0; i < 7; ++i) {
        struct sdk_fixture f; sdk_prepare(&f, 1, d);
        if (i == 0) f.binding.saved_source.epoch = 0;
        if (i == 1) f.binding.saved_source.unit = 0x1dc;
        if (i == 2) ++f.binding.saved_source.handle;
        if (i == 3) --f.binding.saved_source.bytes;
        if (i == 4) f.binding.saved_source.domain = 1;
        if (i == 5) f.binding.saved_source.owner = 0;
        if (i == 6) f.binding.saved_source.unit = 0x1d9;
        sdk_initialize(&f); assert(sdk_run(&f, f.api, 40, 1, 0) == -ESTALE);
        sdk_no_completion(&f, 0); assert(f.out.saved_source.epoch == f.binding.saved_source.epoch); sdk_destroy(&f);
    }
    sdk_cp_finish(d);
}
static void sdk_destination_stale(void) {
    setup(); struct functional_face_dmm_descriptor d = create(0x1da);
    for (unsigned int i = 0; i < 10; ++i) {
        struct sdk_fixture f; sdk_prepare(&f, 1, d);
        if (i == 0) put(f.destination8, d.handle + 0x400u, 4);
        if (i == 1) put(f.destination8, d.handle + 1, 4);
        if (i == 2) ++f.binding.producer_owner;
        struct functional_face_dmm_descriptor saved = state.units[1].creator;
        if (i == 3) ++state.units[1].creator.registration;
        if (i == 4) ++state.units[1].creator.epoch;
        if (i == 5) ++state.units[1].creator.host_view;
        if (i == 6) --state.units[1].creator.bytes;
        if (i == 7) state.units[1].creator.reference = 1;
        if (i == 8) ++state.units[1].creator.logical;
        if (i == 9) --state.units[1].creator.mapped_bytes;
        sdk_save_inputs(&f); sdk_initialize(&f); assert(sdk_run(&f, f.api, 40, 1, 0) < 0);
        sdk_no_completion(&f, 0); state.units[1].creator = saved; sdk_destroy(&f);
    }
    (void)operation(0x23, d.unit, d.handle, 0, 0);
    struct sdk_fixture f; sdk_prepare(&f, 1, d); sdk_initialize(&f);
    assert(sdk_run(&f, f.api, 40, 1, 0) == -ENODATA); sdk_no_completion(&f, 0); sdk_destroy(&f);
    assert(!functional_face_dmm_shutdown());
}
static void sdk_three_units(void) {
    struct dmm_service speech = {.physical = DMM_TEST_PHYSICAL};
    speech.memory = malloc(DMM_TEST_SIZE); assert(speech.memory);
    for (size_t i = 0; i < DMM_TEST_SIZE; ++i) speech.memory[i] = (unsigned char)(i ^ (i >> 9) ^ 0x95);
    unsigned char q[40] = {0x20}, r[40]; put(q + 4, 0x63a, 4); put(q + 22, 1, 2);
    for (unsigned int i = 0; i < 2; ++i) {
        assert(!dmm_service_reply(&speech, q, 40, r)); speech.slots[i].creator_kind = DMM_CREATOR_SPEECH_INITIAL;
    }
    struct dmm_service saved = speech; uint64_t digest = hash(speech.memory, DMM_TEST_SIZE);
    setup(); size_t total = 0;
    for (unsigned int i = 0; i < 3; ++i) {
        struct functional_face_dmm_descriptor d = create(0x1d9 + i);
        struct sdk_fixture f; sdk_prepare(&f, i, d); f.native.drop_on_read = 1; sdk_initialize(&f);
        assert(!sdk_run(&f, f.api, 40, 1, 0));
        assert(f.out.claimed && f.out.started && f.out.callback_attempted && f.out.callback_returned);
        assert(!f.out.callback_result && !f.out.callback_uncertain && !f.out.pending_fault);
        assert(f.invokes == 1 && f.typed_calls == 1 && f.descriptor_reads == 4);
        assert(f.native.freed == 1 && !f.native.data && f.native.producer_frees == 1);
        struct functional_face_dmm_borrow b; struct functional_face_dmm_readback rb;
        assert(!functional_face_runtime_borrow_destination(OWNER, d.unit, d.handle, &d, 0, d.bytes, FUNCTIONAL_FACE_DMM_READ, &b));
        unsigned char *actual = malloc(d.bytes); assert(actual);
        assert(!functional_face_dmm_read(&b, 0, actual, d.bytes, &rb));
        assert(rb.verified_bytes == d.bytes && !memcmp(actual, f.native.expected, d.bytes));
        assert(!__real_functional_face_dmm_release_borrow(&b, &rb)); free(actual);
        printf("SDK_HOST_BYTES unit=%x bytes=%zu digest=%016" PRIx64 " status=0 original_context=1 callback_order=1 source_balance=0 cp_leases=0\n",
            d.unit, d.bytes, f.out.copy.source_digest);
        total += d.bytes; sdk_no_retry(&f); sdk_destroy(&f); (void)operation(0x23, d.unit, d.handle, 0, 0);
    }
    assert(total == 514304 && cp_writer_releases == 3 && cp_reader_releases == 3);
    assert(!functional_face_runtime_snapshot(&diagnostic));
    assert(!diagnostic.live_creators && !diagnostic.faults && !diagnostic.retained && !diagnostic.opens && !diagnostic.shares);
    assert(diagnostic.actual_receive == 6 && diagnostic.actual_request_free == 6 && diagnostic.actual_reply_free == 6);
    assert(!memcmp(&speech, &saved, sizeof speech) && hash(speech.memory, DMM_TEST_SIZE) == digest);
    assert(!functional_face_dmm_shutdown()); free(speech.memory);
    puts("SDK_HOST_COUNTS units=3 source_read=514304 cp_write=514304 cp_internal_read=514304 independent_read=514304 write_leases=3 read_leases=3 extra_owner=3 open=3 close=3 balance=3 typed_callback=3 speech_bytes=1048576 speech_unchanged=1 native_io_bound=0");
}
static void sdk_source_failures(void) {
    setup(); struct functional_face_dmm_descriptor d = create(0x1da);
    for (unsigned int i = 0; i < 6; ++i) {
        struct sdk_fixture f; sdk_prepare(&f, 1, d);
        if (i == 0 || i == 5) { f.native.read_error = 1; f.native.read_value = i == 0 ? -EIO : 0; }
        if (i == 1) f.native.writer_missing = 1;
        if (i == 2) f.native.uncertain_op = 0x21;
        if (i == 3) ++f.binding.saved_source.epoch;
        if (i == 4) ++f.binding.saved_source.owner;
        sdk_initialize(&f); assert(sdk_run(&f, f.api, 40, 1, 0) < 0); sdk_no_completion(&f, 1);
        assert(f.out.pending_fault && f.sdk.transfer.provider.context == &f.native.context);
        if (i == 2) {
            assert(f.out.provider_may_retain && !f.out.copy.source_acquired && !f.out.source_live);
            /* An uncertain Share retained actual ownership without proving it
             * to the provider: owner_live must stay false, not be invented. */
            assert(f.native.context.faulted && f.native.context.uncertain && f.native.context.source_live &&
                f.native.context.writer_live && !f.native.context.owner_live);
            assert(f.native.current.owners == 2 && !f.native.calls[2] && !f.native.calls[3]);
        }
        sdk_no_retry(&f); sdk_destroy(&f);
    }
    sdk_cp_finish(d);
}
static void sdk_cp_faults(void) {
    setup(); struct functional_face_dmm_descriptor d = create(0x1da);
    for (unsigned int i = 1; i <= 3; ++i) {
        struct sdk_fixture f; sdk_prepare(&f, 1, d); f.fault = i; sdk_initialize(&f);
        assert(sdk_run(&f, f.api, 40, 1, 0) < 0); sdk_no_completion(&f, 1);
        assert(f.out.copy.source_acquired && f.out.copy.source_released && f.out.pending_fault && f.native.physical_calls);
        if (i == 1) assert(!f.out.copy.written && f.out.copy.destination_acquired == 1);
        if (i == 2) assert(f.out.copy.written == d.bytes && !f.out.copy.readback && f.out.copy.destination_acquired == 2);
        if (i == 3) assert(f.out.destination_live && f.out.transfer_faulted && f.out.copy.destination_release_result < 0);
        sdk_no_retry(&f); sdk_destroy(&f);
    }
    sdk_cp_finish(d);
}
static void sdk_source_release(void) {
    setup(); struct functional_face_dmm_descriptor d = create(0x1da);
    for (unsigned int i = 0; i < 2; ++i) {
        struct sdk_fixture f; sdk_prepare(&f, 1, d); f.native.fail_op = i ? 0x23 : 0x25;
        sdk_initialize(&f); assert(sdk_run(&f, f.api, 40, 1, 0) == -EIO); sdk_no_completion(&f, 1);
        assert(f.out.copy.written == d.bytes && f.out.copy.readback == d.bytes && !f.out.copy.content_complete);
        assert(f.out.source_live && f.out.transfer_faulted && f.out.provider_may_retain && f.out.pending_fault);
        assert(f.native.context.source_live && f.native.context.owner_live && f.native.context.writer_live);
        assert(f.native.current.owners == 2 && f.native.calls[2] == 1 && f.native.calls[3] == i);
        sdk_no_retry(&f); sdk_destroy(&f);
    }
    sdk_cp_finish(d);
}
static void sdk_callback_failure(void) {
    setup(); struct functional_face_dmm_descriptor d = create(0x1da);
    for (unsigned int i = 0; i < 2; ++i) {
        struct sdk_fixture f; sdk_prepare(&f, 1, d); f.invoke_result = i ? 37 : -ETIMEDOUT;
        sdk_initialize(&f); assert(sdk_run(&f, f.api, 40, 1, 0) == f.invoke_result);
        assert(f.invokes == 1 && f.typed_calls == 1 && f.out.callback_attempted && f.out.callback_returned);
        assert(f.out.callback_uncertain && f.out.pending_fault && f.out.copy.content_complete);
        assert(f.out.callback_result == f.invoke_result && !f.out.copy_result && !f.out.provider_may_retain);
        sdk_no_retry(&f); assert(f.invokes == 1 && f.typed_calls == 1); sdk_destroy(&f);
    }
    sdk_cp_finish(d);
}
static void sdk_caller_sender(void) {
    setup(); struct functional_face_dmm_descriptor d = create(0x1da);
    for (unsigned int i = 0; i < 4; ++i) {
        struct sdk_fixture f; sdk_prepare(&f, 1, d); sdk_initialize(&f);
        assert(sdk_run(&f, f.api, 40, i < 2 ? (int)i * 2 : 1, i < 2 ? 0 : i == 2 ? 1 : -1) == -EPERM);
        sdk_no_completion(&f, 0); assert(!f.descriptor_reads && !f.out.decoded); sdk_destroy(&f);
    }
    sdk_cp_finish(d);
}
static void *sdk_wrong_thread(void *p) {
    struct sdk_fixture *f = p; struct functional_face_sdk_transaction out, saved;
    memset(&out, 0x96, sizeof out); saved = out;
    assert(functional_face_sdk_init(&f->sdk, &f->binding) == -ECHILD);
    assert(functional_face_sdk_submit(&f->sdk, (void *)(uintptr_t)1, 40, 1, 0, &out) == -ECHILD);
    assert(!memcmp(&out, &saved, sizeof out)); return NULL;
}
static void sdk_thread_reentry(void) {
    setup(); struct functional_face_dmm_descriptor d = create(0x1da);
    struct sdk_fixture f; sdk_prepare(&f, 1, d);
    struct functional_face_sdk_binding bad = f.binding;
    ++bad.owner_pid; atomic_store(&f.sdk.busy, 1);
    assert(functional_face_sdk_init(&f.sdk, &bad) == -ECHILD);
    bad = f.binding; ++bad.owner_tid;
    assert(functional_face_sdk_init(&f.sdk, &bad) == -ECHILD);
    atomic_store(&f.sdk.busy, 0); sdk_initialize(&f); atomic_store(&f.sdk.busy, 1);
    pthread_t thread; assert(!pthread_create(&thread, NULL, sdk_wrong_thread, &f)); assert(!pthread_join(thread, NULL));
    pid_t child = fork(); assert(child >= 0);
    if (!child) { sdk_wrong_thread(&f); _exit(0); }
    int status; assert(waitpid(child, &status, 0) == child && WIFEXITED(status) && !WEXITSTATUS(status));
    assert(!f.sdk.submitted && !f.descriptor_reads && !f.native.writer_calls);
    atomic_store(&f.sdk.busy, 0); f.reentry = 1;
    assert(!sdk_run(&f, f.api, 40, 1, 0));
    assert(f.reentered[0] == 1 && f.reentered[1] == 1 && f.reentered[2] == 1);
    sdk_no_retry(&f); sdk_destroy(&f); sdk_cp_finish(d);
}
int main(int argc, char **argv) {
    assert(argc == 2); const char *mode = argv[1];
    if (!strcmp(mode, "missing")) sdk_missing();
    else if (!strcmp(mode, "api40")) sdk_api_extent();
    else if (!strcmp(mode, "descriptors")) sdk_descriptors();
    else if (!strcmp(mode, "source-binding")) sdk_source_binding();
    else if (!strcmp(mode, "destination-stale")) sdk_destination_stale();
    else if (!strcmp(mode, "three-units")) sdk_three_units();
    else if (!strcmp(mode, "source-failures")) sdk_source_failures();
    else if (!strcmp(mode, "cp-faults")) sdk_cp_faults();
    else if (!strcmp(mode, "source-release")) sdk_source_release();
    else if (!strcmp(mode, "callback-failure")) sdk_callback_failure();
    else if (!strcmp(mode, "caller-sender")) sdk_caller_sender();
    else if (!strcmp(mode, "thread-reentry")) sdk_thread_reentry();
    else abort();
    printf("FACE_SDK_HOST_PASS mode=%s native_io_bound=0 physical_verified=0 capture_verified=0\n", mode);
    return 0;
}
