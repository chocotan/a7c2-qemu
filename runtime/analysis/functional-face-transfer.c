/* SPDX-License-Identifier: MIT */
#include "functional-face-transfer.h"
#include <errno.h>
#ifdef FULL_IMAGING_GUEST
extern int getpid(void);
#else
#include <unistd.h>
#endif

static uint64_t face_transfer_le(const unsigned char *p, size_t n) {
    uint64_t value = 0;
    for (size_t i = 0; i < n; ++i) value |= (uint64_t)p[i] << (i * 8);
    return value;
}
int functional_face_transfer_decode_sdk48(const void *request, size_t bytes,
    long (*reader)(void *, uintptr_t, void *, size_t), void *context, struct functional_face_sdk_request *out) {
    if (!request || bytes != 48 || !reader || !out) return -EINVAL;
    const unsigned char *p = request;
    struct functional_face_sdk_request value = {0};
    uint64_t source = face_transfer_le(p, 8), destination = face_transfer_le(p + 8, 8);
    uint64_t callback = face_transfer_le(p + 24, 8), callback_context = face_transfer_le(p + 32, 8);
    if (!source || !destination || source > UINTPTR_MAX - 8 || destination > UINTPTR_MAX - 8 ||
        !callback || callback > UINTPTR_MAX || !callback_context || callback_context > UINTPTR_MAX ||
        face_transfer_le(p + 20, 4) != 1) return -ENOTSUP;
    unsigned char first[16], second[16];
    long a = reader(context, (uintptr_t)source, first, 8);
    long b = reader(context, (uintptr_t)destination, first + 8, 8);
    long c = reader(context, (uintptr_t)source, second, 8);
    long d = reader(context, (uintptr_t)destination, second + 8, 8);
    if (a != 8 || b != 8 || c != 8 || d != 8) return -EIO;
    for (size_t i = 0; i < sizeof first; ++i) if (first[i] != second[i]) return -ESTALE;
    value.input.source_handle = (uint32_t)face_transfer_le(first, 4);
    value.input.source_offset = (uint32_t)face_transfer_le(first + 4, 4);
    value.input.destination_handle = (uint32_t)face_transfer_le(first + 8, 4);
    value.input.destination_offset = (uint32_t)face_transfer_le(first + 12, 4);
    value.input.bytes = (uint32_t)face_transfer_le(p + 16, 4);
    uint32_t sh = value.input.source_handle, dh = value.input.destination_handle, index = dh & 0x3ffu;
    static const uint32_t sizes[3] = {0x64000, 0xc800, 0xd100};
    if (!sh || sh > 0x7fffu || !((sh >> 10) & 31u) || dh > 0xffffu || !(dh & 0x8000u) ||
        !((dh >> 10) & 31u) || index < 2 || index > 4 || value.input.source_offset ||
        value.input.destination_offset || value.input.bytes != sizes[index - 2]) return -ENOTSUP;
    value.source_descriptor = (uintptr_t)source; value.destination_descriptor = (uintptr_t)destination;
    value.callback = (uintptr_t)callback; value.callback_context = (uintptr_t)callback_context;
    value.submission_result_before = (uint32_t)face_transfer_le(p + 40, 4);
    value.opaque_padding = (uint32_t)face_transfer_le(p + 44, 4);
    *out = value;
    return 0;
}
int functional_face_transfer_decode_api40(const void *request, size_t bytes,
    long (*reader)(void *, uintptr_t, void *, size_t), void *context, struct functional_face_api_request *out) {
    if (!request || bytes != 40 || !reader || !out) return -EINVAL;
    unsigned char message[48] = {0};
    for (size_t i = 0; i < 40; ++i) message[i] = ((const unsigned char *)request)[i];
    struct functional_face_sdk_request decoded = {0};
    int rc = functional_face_transfer_decode_sdk48(message, sizeof message, reader, context, &decoded);
    if (rc) return rc;
    *out = (struct functional_face_api_request){.input = decoded.input,
        .source_descriptor = decoded.source_descriptor, .destination_descriptor = decoded.destination_descriptor,
        .callback = decoded.callback, .callback_context = decoded.callback_context};
    return 0;
}
static int face_ap_equal(const struct functional_face_ap_span *a, const struct functional_face_ap_span *b) {
    return a->domain == b->domain && a->unit == b->unit && a->handle == b->handle &&
        a->epoch == b->epoch && a->owner == b->owner && a->bytes == b->bytes;
}
static uint64_t face_transfer_digest(uint64_t value, const unsigned char *p, size_t n) {
    for (size_t i = 0; i < n; ++i) value = (value ^ p[i]) * UINT64_C(1099511628211);
    return value;
}
int functional_face_transfer_init(struct functional_face_transfer *s, const struct functional_face_ap_provider *p) {
    if (!s || !p || !p->acquire || !p->read || !p->check_disjoint || !p->release) return -EINVAL;
    if (s->initialized && s->owner_pid != getpid()) return -ECHILD;
    if (s->initialized || atomic_load_explicit(&s->busy, memory_order_acquire)) return -EALREADY;
    s->provider = *p; s->owner_pid = getpid(); s->initialized = 1;
    return 0;
}
static int face_transfer_shape(uint64_t owner, const struct functional_face_ap_span *a,
    const struct functional_face_dmm_descriptor *d, const struct functional_face_transfer_input *q) {
    static const size_t sizes[3] = {0x64000, 0xc800, 0xd100};
    if (!owner || !a || !d || !q || a->unit < 0x1d9 || a->unit > 0x1db) return -EINVAL;
    size_t bytes = sizes[a->unit - 0x1d9];
    if (a->domain || !a->epoch || !a->owner || !a->handle || (a->handle & 0x8000u) ||
        !((a->handle >> 10) & 31u) || a->handle > 0x7fffu || a->bytes != bytes ||
        d->domain != FUNCTIONAL_FACE_DMM_DOMAIN || d->unit != a->unit || d->owner != owner ||
        !d->epoch || d->reference || d->bytes != bytes || q->source_handle != a->handle ||
        q->destination_handle != d->handle || q->source_offset || q->destination_offset || q->bytes != bytes)
        return -ESTALE;
    return 0;
}
static int face_transfer_release_destination(struct functional_face_transfer *s, int verify_digest) {
    if (!s->destination_live) return 0;
    if (s->destination_release_attempted) return s->last.destination_release_result ? s->last.destination_release_result : -EIO;
    s->destination_release_attempted = 1;
    struct functional_face_dmm_readback rb = {0};
    int rc = functional_face_dmm_release_borrow(&s->destination, &rb);
    s->last.destination_release_result = rc;
    if (!rc) {
        s->destination_live = 0;
        size_t verified = s->destination.access & FUNCTIONAL_FACE_DMM_WRITE ? rb.verified_bytes : s->last.readback;
        if (verify_digest && (verified != s->source.bytes || rb.after_digest != s->last.source_digest))
            return -EBADMSG;
    }
    return rc;
}
int functional_face_transfer_copy(struct functional_face_transfer *s, uint64_t owner,
    const struct functional_face_ap_span *a, const struct functional_face_dmm_descriptor *d,
    const struct functional_face_transfer_input *q) {
    if (!s || !s->initialized) return -ENODATA;
    if (s->owner_pid != getpid()) return -ECHILD;
    unsigned int expected = 0;
    if (!atomic_compare_exchange_strong_explicit(&s->busy, &expected, 1, memory_order_acq_rel, memory_order_acquire))
        return -EBUSY;
    if (s->faulted) { atomic_store_explicit(&s->busy, 0, memory_order_release); return -EIO; }
    s->last = (struct functional_face_transfer_receipt){0};
    int rc = face_transfer_shape(owner, a, d, q);
    if (!rc) {
        s->source = (struct functional_face_ap_borrow){0};
        rc = s->provider.acquire(s->provider.context, a, 0, q->bytes, &s->source);
        if (rc > 0) rc = -EPROTO;
        if (!rc) {
            s->source_live = 1; s->last.source_acquired = 1;
            if (!face_ap_equal(a, &s->source.span) || !s->source.nonce || s->source.offset || s->source.bytes != q->bytes)
                rc = -ESTALE;
        }
    }
    if (!rc) {
        rc = s->provider.check_disjoint(s->provider.context, &s->source, d);
        if (rc > 0) rc = -EPROTO;
    }
    if (!rc) {
        rc = functional_face_runtime_borrow_destination(owner, d->unit, q->destination_handle, d,
            0, q->bytes, FUNCTIONAL_FACE_DMM_WRITE | FUNCTIONAL_FACE_DMM_TRANSFER, &s->destination);
        if (!rc) {
            s->destination_live = 1; s->destination_release_attempted = 0;
            ++s->last.destination_acquired;
        }
    }
    unsigned char buffer[4096];
    s->last.source_digest = UINT64_C(14695981039346656037);
    for (size_t offset = 0; !rc && offset < q->bytes;) {
        size_t n = q->bytes - offset; if (n > sizeof buffer) n = sizeof buffer;
        long got = s->provider.read(s->provider.context, &s->source, offset, buffer, n);
        if (got != (long)n) { rc = got < 0 && got >= -4095 ? (int)got : -EIO; break; }
        struct functional_face_dmm_readback rb = {0};
        rc = functional_face_dmm_write(&s->destination, offset, buffer, n, &rb);
        if (!rc && rb.verified_bytes != n) rc = -EBADMSG;
        if (!rc) {
            s->last.source_digest = face_transfer_digest(s->last.source_digest, buffer, n);
            s->last.written += n; offset += n;
        }
    }
    if (!rc) rc = face_transfer_release_destination(s, 1);
    if (!rc) {
        rc = functional_face_runtime_borrow_destination(owner, d->unit, q->destination_handle, d,
            0, q->bytes, FUNCTIONAL_FACE_DMM_READ | FUNCTIONAL_FACE_DMM_TRANSFER, &s->destination);
        if (!rc) {
            s->destination_live = 1; s->destination_release_attempted = 0;
            ++s->last.destination_acquired;
        }
    }
    s->last.destination_digest = UINT64_C(14695981039346656037);
    for (size_t offset = 0; !rc && offset < q->bytes;) {
        size_t n = q->bytes - offset; if (n > sizeof buffer) n = sizeof buffer;
        struct functional_face_dmm_readback rb = {0};
        rc = functional_face_dmm_read(&s->destination, offset, buffer, n, &rb);
        if (!rc && rb.verified_bytes != n) rc = -EBADMSG;
        if (!rc) {
            s->last.destination_digest = face_transfer_digest(s->last.destination_digest, buffer, n);
            s->last.readback += n; offset += n;
        }
    }
    if (!rc && s->last.source_digest != s->last.destination_digest) rc = -EBADMSG;
    s->last.operation_result = rc;
    /* One release attempt per acquired lease, including partial-copy failures. */
    int release_rc = face_transfer_release_destination(s, !rc);
    if (!rc && release_rc) rc = release_rc;
    if (!s->destination_live && s->last.destination_acquired) s->last.destination_released = 1;
    if (s->source_live) {
        int result = s->provider.release(s->provider.context, &s->source);
        if (result > 0) result = -EPROTO;
        s->last.source_release_result = result;
        if (!result) { s->source_live = 0; s->last.source_released = 1; }
        if (!rc && result) rc = result;
    }
    if (s->source_live || s->destination_live) { s->faulted = 1; rc = -EIO; }
    if (!rc) s->last.content_complete = 1;
    atomic_store_explicit(&s->busy, 0, memory_order_release);
    return rc;
}
