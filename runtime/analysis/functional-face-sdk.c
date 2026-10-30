/* SPDX-License-Identifier: MIT */
#ifndef _GNU_SOURCE
#define _GNU_SOURCE
#endif
#include "functional-face-sdk.h"
#include <errno.h>
#ifdef FULL_IMAGING_GUEST
extern int getpid(void);
extern long syscall(long, ...);
#define SDK_TID() syscall(178L)
#else
#include <sys/syscall.h>
#include <unistd.h>
#define SDK_TID() syscall(SYS_gettid)
#endif

static int sdk_guard(const struct functional_face_sdk_binding *b) {
    if (b->owner_pid != getpid() || b->owner_tid != SDK_TID()) return -ECHILD;
    return 0;
}
int functional_face_sdk_init(struct functional_face_sdk *s, const struct functional_face_sdk_binding *b) {
    if (!s) return -EINVAL;
    if (s->initialized && sdk_guard(&s->binding)) return -ECHILD;
    if (!b) return -ENODATA;
    if (sdk_guard(b)) return -ECHILD;
    if (s->initialized || atomic_load_explicit(&s->busy, memory_order_acquire)) return -EALREADY;
    if (!b->producer_owner || !b->provider.acquire || !b->provider.read || !b->provider.check_disjoint ||
        !b->provider.release || !b->read_descriptor || !b->invoke_callback) return -ENODATA;
    int rc = functional_face_transfer_init(&s->transfer, &b->provider);
    if (rc) return rc;
    s->binding = *b; s->initialized = 1;
    return 0;
}
static int sdk_bind_destination(struct functional_face_sdk *s) {
    struct functional_face_sdk_transaction *t = &s->last;
    const struct functional_face_ap_span *a = &t->saved_source;
    const struct functional_face_transfer_input *q = &t->request.input;
    static const size_t sizes[3] = {0x64000, 0xc800, 0xd100};
    if (a->unit < 0x1d9 || a->unit > 0x1db) return -ESTALE;
    size_t bytes = sizes[a->unit - 0x1d9];
    if (a->domain || !a->epoch || !a->owner || a->bytes != bytes || q->source_handle != a->handle ||
        q->source_offset || q->destination_offset || q->bytes != bytes ||
        (q->destination_handle & 0x3ffu) != a->unit - 0x1d9 + 2) return -ESTALE;
    int rc = functional_face_runtime_lookup_creator(s->binding.producer_owner, a->unit, &t->destination);
    if (rc) return rc;
    const struct functional_face_dmm_descriptor *d = &t->destination;
    if (d->domain != FUNCTIONAL_FACE_DMM_DOMAIN || d->unit != a->unit || d->handle != q->destination_handle ||
        !d->epoch || d->owner != s->binding.producer_owner || d->reference || d->bytes != bytes ||
        !d->registration || !d->host_view || !d->logical || d->mapped_bytes < bytes) return -ESTALE;
    struct functional_face_registry_inspection inspected;
    return functional_face_registry_inspect_span(d, &inspected);
}
static int sdk_content_complete(const struct functional_face_transfer *s, size_t bytes) {
    const struct functional_face_transfer_receipt *r = &s->last;
    return r->content_complete == 1 && r->source_acquired == 1 && r->destination_acquired == 2 &&
        r->source_released == 1 && r->destination_released == 1 && !s->source_live && !s->destination_live &&
        !s->faulted && !r->operation_result && !r->source_release_result && !r->destination_release_result &&
        r->written == bytes && r->readback == bytes && r->source_digest == r->destination_digest;
}
int functional_face_sdk_submit(struct functional_face_sdk *s, const void *api40, size_t bytes,
    int caller_bound, int original_sender_started, struct functional_face_sdk_transaction *out) {
    if (!s) return -EINVAL;
    if (!s->initialized) return -ENODATA;
    if (sdk_guard(&s->binding)) return -ECHILD;
    if (!out) return -EINVAL;
    unsigned int expected = 0;
    if (!atomic_compare_exchange_strong_explicit(&s->busy, &expected, 1, memory_order_acq_rel, memory_order_acquire))
        return -EBUSY;
    if (s->submitted) { atomic_store_explicit(&s->busy, 0, memory_order_release); return -EALREADY; }
    s->submitted = 1;
    s->last = (struct functional_face_sdk_transaction){.saved_source = s->binding.saved_source};
    struct functional_face_sdk_transaction *t = &s->last;
    int rc = caller_bound == 1 && original_sender_started == 0 ? 0 : -EPERM;
    if (!rc && (!api40 || bytes != sizeof t->api40)) rc = -EINVAL;
    if (!rc) {
        for (size_t i = 0; i < sizeof t->api40; ++i) t->api40[i] = ((const unsigned char *)api40)[i];
        for (size_t i = 0; i < 4; ++i) t->class_id |= (uint32_t)t->api40[20 + i] << (8 * i);
        rc = functional_face_transfer_decode_api40(t->api40, sizeof t->api40,
            s->binding.read_descriptor, s->binding.reader_context, &t->request);
        if (!rc) { t->decoded = 1; rc = sdk_bind_destination(s); }
    }
    if (!rc) {
        /* acquire can retain native resources even when it returns no lease. */
        t->claimed = t->started = 1;
        rc = functional_face_transfer_copy(&s->transfer, s->binding.producer_owner,
            &t->saved_source, &t->destination, &t->request.input);
        t->copy_result = rc; t->copy = s->transfer.last;
        t->source_lease = s->transfer.source; t->destination_lease = s->transfer.destination;
        t->source_live = s->transfer.source_live; t->destination_live = s->transfer.destination_live;
        t->transfer_faulted = s->transfer.faulted;
        if (!rc && !sdk_content_complete(&s->transfer, t->request.input.bytes)) rc = -EIO;
        if (rc) {
            t->pending_fault = 1;
            t->provider_may_retain = !t->copy.source_acquired || t->source_live;
        } else {
            t->callback_attempted = 1;
            rc = s->binding.invoke_callback(s->binding.callback_context, t->request.callback,
                INT32_C(0), t->request.callback_context);
            t->callback_returned = 1; t->callback_result = rc;
            if (rc) t->callback_uncertain = t->pending_fault = 1;
        }
    }
    t->result = rc; *out = *t;
    atomic_store_explicit(&s->busy, 0, memory_order_release);
    return rc;
}
