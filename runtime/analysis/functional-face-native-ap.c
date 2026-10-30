/* SPDX-License-Identifier: MIT */
#define _GNU_SOURCE
#include "functional-face-native-ap.h"
#include <errno.h>
#include <limits.h>
#ifdef FULL_IMAGING_GUEST
extern int getpid(void);
extern long syscall(long, ...);
extern int memcmp(const void *, const void *, size_t);
#define NATIVE_TID() syscall(178L)
#else
#include <string.h>
#include <sys/syscall.h>
#include <unistd.h>
#define NATIVE_TID() syscall(SYS_gettid)
#endif

static uint64_t native_le(const unsigned char *p, size_t n) {
    uint64_t v = 0;
    for (size_t i = 0; i < n; ++i) v |= (uint64_t)p[i] << (8 * i);
    return v;
}
static void native_put(unsigned char *p, uint64_t v, size_t n) {
    for (size_t i = 0; i < n; ++i) p[i] = (unsigned char)(v >> (8 * i));
}
static int native_span_equal(const struct functional_face_ap_span *a, const struct functional_face_ap_span *b) {
    return a->domain == b->domain && a->unit == b->unit && a->handle == b->handle &&
        a->epoch == b->epoch && a->owner == b->owner && a->bytes == b->bytes;
}
static int native_identity(const struct functional_face_native_ap_reference *a,
    const struct functional_face_native_ap_reference *b) {
    return native_span_equal(&a->span, &b->span) && a->birth_sequence == b->birth_sequence &&
        a->unit_identity == b->unit_identity && a->extent_identity == b->extent_identity &&
        a->allocation_sequence == b->allocation_sequence && a->generation == b->generation;
}
static int native_reference_equal(const struct functional_face_native_ap_reference *a,
    const struct functional_face_native_ap_reference *b) {
    return native_identity(a, b) && a->state == b->state && a->owners == b->owners &&
        a->opens == b->opens && a->shares == b->shares;
}
static int native_birth_equal(const struct functional_face_ap_birth *a, const struct functional_face_ap_birth *b) {
    return a->unit == b->unit && a->handle == b->handle && a->observations == b->observations &&
        a->ambiguous == b->ambiguous && a->any_free_observed == b->any_free_observed &&
        a->reply_source == b->reply_source && a->observation_sequence == b->observation_sequence;
}
static int native_shape(const struct functional_face_native_ap_reference *r) {
    static const size_t sizes[3] = {0x64000, 0xc800, 0xd100};
    const struct functional_face_ap_span *a = &r->span;
    return !a->domain && a->unit >= 0x1d9 && a->unit <= 0x1db && a->handle <= 0x7fff &&
        (a->handle & 0x3ffu) != 0x3ffu && ((a->handle >> 10) & 31u) &&
        r->generation == ((a->handle >> 10) & 31u) && a->epoch && a->owner &&
        a->bytes == sizes[a->unit - 0x1d9] && r->birth_sequence && r->unit_identity &&
        r->extent_identity && r->allocation_sequence && r->owners == 1 && !r->opens && !r->shares && r->state == 1;
}
static int native_enter(struct functional_face_native_ap *s) {
    if (!s || !s->initialized) return -ENODATA;
    if (s->owner_pid != getpid() || s->owner_tid != NATIVE_TID()) return -ECHILD;
    unsigned int expected = 0;
    if (!atomic_compare_exchange_strong_explicit(&s->busy, &expected, 1, memory_order_acq_rel, memory_order_acquire))
        return -EBUSY;
    if (s->faulted) { atomic_store_explicit(&s->busy, 0, memory_order_release); return -EIO; }
    return 0;
}
static int native_leave(struct functional_face_native_ap *s, int rc) {
    s->last_error = rc;
    atomic_store_explicit(&s->busy, 0, memory_order_release);
    return rc;
}
static int native_fault(struct functional_face_native_ap *s, int rc, int uncertain) {
    s->faulted = 1; s->uncertain |= (unsigned int)uncertain; s->candidate_capability = 0;
    return rc;
}
static int native_ticket(struct functional_face_native_ap *s, uint32_t op,
    const struct functional_face_ap_observer *o, int *status) {
    unsigned char expected[40] = {0};
    uint32_t unit = op == 0x21 ? s->native_birth.span.unit : 0;
    native_put(expected, op, 2); native_put(expected + 4, unit, 4);
    native_put(expected + 8, s->native_birth.span.handle, 4);
    if (op == 0x24) native_put(expected + 12, UINT32_MAX, 4);
    if (op == 0x23) native_put(expected + 20, o->source & 0xffffu, 2);
    if (o->owner_pid != s->owner_pid || o->sender_tid != s->owner_tid || !o->sequence ||
        o->sequence <= s->last_sequence || o->active || o->dropped || o->op != op || o->unit != unit ||
        o->handle != s->native_birth.span.handle || !o->source || o->source == UINT32_MAX ||
        o->source == FUNCTIONAL_FACE_AP_DMM || !o->request || !o->reply || o->send_seen != 1 ||
        o->send_result || o->received != 1 || o->free_attempts != 1 || o->free_result ||
        o->reply_source != FUNCTIONAL_FACE_AP_DMM || o->reply_bytes != 40 ||
        memcmp(o->request_wire, expected, 40) || native_le(o->reply_wire, 2) != (op | 0x8000u)) return -EPROTO;
    struct functional_face_ap_birth fact = {0};
    if (functional_face_ap_observed_birth(o, s->owner_tid, s->birth.unit, s->birth.handle, &fact) ||
        (fact.any_free_observed && op != 0x23 && !s->producer_dropped)) return -ESTALE;
    fact.any_free_observed = s->birth.any_free_observed;
    if (!native_birth_equal(&fact, &s->birth)) return -ESTALE;
    *status = (int)(int16_t)native_le(o->reply_wire + 2, 2);
    s->last_sequence = o->sequence;
    return 0;
}
static int native_transition(struct functional_face_native_ap *s, uint32_t op,
    const struct functional_face_native_ap_operation *p, int status) {
    if (!native_reference_equal(&p->before, &s->reference)) return -ESTALE;
    struct functional_face_native_ap_reference want = p->before;
    if (op == 0x21) {
        if (status || !want.owners || want.owners >= 255) return -EPROTO;
        ++want.owners;
    } else if (op == 0x24) {
        if (status) return native_reference_equal(&p->after, &want) ? -EREMOTEIO : -ESTALE;
        if (want.opens >= 255 || (want.state != 1 && want.state != 2)) return -EPROTO;
        ++want.opens; want.state = 2;
    } else if (op == 0x25) {
        if (status || !want.opens || (want.state != 2 && want.state != 3)) return -EPROTO;
        --want.opens; if (!want.opens) want.state = 1;
    } else {
        if (!want.owners || (status && !(status == 3 && want.owners == 1))) return -EPROTO;
        --want.owners;
        if (!want.owners) {
            want.state = want.opens = want.shares = 0;
            /* The retired extent pointer may be cleared; never accept a new one. */
            if (!p->after.extent_identity) want.extent_identity = 0;
        }
    }
    return native_reference_equal(&p->after, &want) ? 0 : -ESTALE;
}
static int native_operation(struct functional_face_native_ap *s, uint32_t op) {
    size_t index = op == 0x21 ? 0 : op == 0x24 ? 1 : op == 0x25 ? 2 : 3;
    struct functional_face_native_ap_operation *p = &s->operations[index];
    struct functional_face_native_ap_input input = {s->native_birth.span.unit, 0, s->native_birth.span.handle};
    int rc = s->ops.original_native_operation(s->io_context, op, &input, p), status = 0;
    if (!rc) rc = native_ticket(s, op, &p->observed, &status);
    if (!rc) rc = native_transition(s, op, p, status);
    if (rc) {
        if (op == 0x24 && rc == -EREMOTEIO) return rc;
        return native_fault(s, rc < 0 ? rc : -EPROTO, 1);
    }
    s->reference = p->after;
    return 0;
}
static int native_writer(struct functional_face_native_ap *s, enum functional_face_native_ap_writer_action action) {
    struct functional_face_native_ap_writer *w = &s->last_writer;
    *w = (struct functional_face_native_ap_writer){0};
    int rc = s->ops.source_writer_serial(s->io_context, action, &s->birth, &s->native_birth,
        action == FACE_NATIVE_AP_WRITER_BEGIN ? NULL : &s->writer, w);
    if (rc) {
        if (action != FACE_NATIVE_AP_WRITER_BEGIN || w->lease) {
            if (w->lease) s->writer_live = 1;
            return native_fault(s, rc < 0 ? rc : -EPROTO, 0);
        }
        return rc < 0 ? rc : -EPROTO;
    }
    if (action == FACE_NATIVE_AP_WRITER_BEGIN) s->writer_live = 1;
    if (!w->lease || !w->writer_identity || !w->completion_identity || !w->writer_sequence ||
        w->writer_sequence != w->completed_sequence) return native_fault(s, -ENODATA, 0);
    if (action == FACE_NATIVE_AP_WRITER_BEGIN) {
        if (!native_identity(&w->current, &s->native_birth) || w->current.owners != 1 || w->current.shares ||
            w->current.opens >= 255 || w->current.state != (w->current.opens ? 2u : 1u))
            return native_fault(s, -ESTALE, 0);
        s->writer = *w; s->reference = w->current;
        return 0;
    }
    if (w->lease != s->writer.lease || w->writer_identity != s->writer.writer_identity ||
        w->completion_identity != s->writer.completion_identity || w->writer_sequence != s->writer.writer_sequence ||
        w->completed_sequence != s->writer.completed_sequence) return native_fault(s, -ESTALE, 0);
    if (!native_reference_equal(&w->current, &s->reference)) {
        struct functional_face_native_ap_reference expected = s->reference;
        if (action != FACE_NATIVE_AP_WRITER_CHECK || !s->owner_live || s->producer_dropped || expected.owners != 2)
            return native_fault(s, -ESTALE, 0);
        --expected.owners;
        int status = 0;
        if (!native_reference_equal(&w->current, &expected) ||
            native_ticket(s, 0x23, &w->producer_drop.observed, &status) || status ||
            native_transition(s, 0x23, &w->producer_drop, status) ||
            !native_reference_equal(&w->producer_drop.after, &w->current)) return native_fault(s, -ESTALE, 0);
        s->producer_drop = w->producer_drop; s->producer_dropped = 1; s->reference = w->current;
    }
    if (action == FACE_NATIVE_AP_WRITER_END) s->writer_live = 0;
    return 0;
}
static int native_range_valid(const struct functional_face_native_ap_range *r) {
    return r->backing && r->bytes && r->bytes <= UINT64_MAX - r->offset;
}
static int native_range_equal(const struct functional_face_native_ap_range *a,
    const struct functional_face_native_ap_range *b) {
    return a->backing == b->backing && a->offset == b->offset && a->bytes == b->bytes;
}
static int native_disjoint(const struct functional_face_native_ap_range *a,
    const struct functional_face_native_ap_range *b) {
    return a->backing != b->backing || a->offset + a->bytes <= b->offset || b->offset + b->bytes <= a->offset;
}
static int native_range_set_valid(const struct functional_face_native_ap_range_set *s, uint64_t *bytes) {
    if (!s->count || s->count > FUNCTIONAL_FACE_NATIVE_AP_MAX_RANGES) return 0;
    uint64_t total = 0;
    for (uint32_t i = 0; i < s->count; ++i) {
        if (!native_range_valid(&s->ranges[i]) || s->ranges[i].bytes > UINT64_MAX - total) return 0;
        for (uint32_t j = 0; j < i; ++j)
            if (!native_disjoint(&s->ranges[i], &s->ranges[j])) return 0;
        total += s->ranges[i].bytes;
    }
    if (bytes) *bytes = total;
    return 1;
}
static int native_range_set_equal(const struct functional_face_native_ap_range_set *a,
    const struct functional_face_native_ap_range_set *b) {
    if (!a->count || a->count > FUNCTIONAL_FACE_NATIVE_AP_MAX_RANGES || a->count != b->count) return 0;
    for (uint32_t i = 0; i < a->count; ++i)
        if (!native_range_equal(&a->ranges[i], &b->ranges[i])) return 0;
    return 1;
}
static int native_range_set_disjoint(const struct functional_face_native_ap_range *a, uint32_t na,
    const struct functional_face_native_ap_range *b, uint32_t nb) {
    for (uint32_t i = 0; i < na; ++i)
        for (uint32_t j = 0; j < nb; ++j)
            if (!native_disjoint(&a[i], &b[j])) return 0;
    return 1;
}
static int native_mapping_equal(const struct functional_face_native_ap_mapping *a,
    const struct functional_face_native_ap_mapping *b) {
    return a->lease == b->lease && a->address == b->address && a->physical == b->physical &&
        native_range_equal(&a->source, &b->source) && native_range_set_equal(&a->sdk, &b->sdk) &&
        native_range_set_equal(&a->mailer, &b->mailer);
}
static int native_cp_equal(const struct functional_face_dmm_descriptor *a,
    const struct functional_face_dmm_descriptor *b) {
    return a->domain == b->domain && a->unit == b->unit && a->handle == b->handle && a->epoch == b->epoch &&
        a->owner == b->owner && a->reference == b->reference && a->logical == b->logical &&
        a->registration == b->registration && a->host_view == b->host_view && a->bytes == b->bytes &&
        a->mapped_bytes == b->mapped_bytes;
}
static int native_mapping(struct functional_face_native_ap *s, const struct functional_face_dmm_descriptor *d) {
    struct functional_face_native_ap_mapping_proof *p = &s->last_mapping;
    *p = (struct functional_face_native_ap_mapping_proof){0};
    int rc = s->ops.prove_mapping_and_disjoint(s->io_context, &s->reference, s->native_address,
        s->native_birth.span.bytes, d, p);
    if (rc) return rc < 0 ? rc : -EPROTO;
    const struct functional_face_native_ap_mapping *m = &p->mapping;
    if (s->mapping.lease && !native_mapping_equal(m, &s->mapping)) return native_fault(s, -ESTALE, 0);
    if (!m->lease || m->lease != s->writer.lease || m->address != s->native_address || m->source.bytes != s->native_birth.span.bytes ||
        m->source.bytes > UINT64_MAX - m->physical || !native_range_valid(&m->source) ||
        !native_range_set_valid(&m->sdk, NULL) || !native_range_set_valid(&m->mailer, NULL)) return -ENODATA;
    if (!native_range_set_disjoint(&m->source, 1, m->sdk.ranges, m->sdk.count) ||
        !native_range_set_disjoint(&m->source, 1, m->mailer.ranges, m->mailer.count) ||
        !native_range_set_disjoint(m->sdk.ranges, m->sdk.count, m->mailer.ranges, m->mailer.count)) return -EADDRINUSE;
    if (d) {
        if (s->cp.count && (!native_cp_equal(&s->destination, d) || !native_range_set_equal(&s->cp, &p->cp)))
            return native_fault(s, -ESTALE, 0);
        uint64_t covered = 0;
        if (!native_cp_equal(&p->destination, d) || !d->registration || !d->host_view ||
            d->domain != FUNCTIONAL_FACE_DMM_DOMAIN || d->unit != s->native_birth.span.unit ||
            d->reference || !d->owner || !d->epoch || d->bytes != s->native_birth.span.bytes ||
            d->mapped_bytes < d->bytes || d->mapped_bytes > UINTPTR_MAX - d->host_view ||
            !native_range_set_valid(&p->cp, &covered) || covered != d->mapped_bytes) return -ESTALE;
        for (uint32_t i = 0; i < p->cp.count; ++i)
            if ((p->cp.ranges[i].offset | p->cp.ranges[i].bytes) & (FUNCTIONAL_FACE_DMM_PAGE - 1u)) return -ESTALE;
        if (!native_range_set_disjoint(&m->source, 1, p->cp.ranges, p->cp.count) ||
            !native_range_set_disjoint(m->sdk.ranges, m->sdk.count, p->cp.ranges, p->cp.count) ||
            !native_range_set_disjoint(m->mailer.ranges, m->mailer.count, p->cp.ranges, p->cp.count)) return -EADDRINUSE;
        if (!s->cp.count) { s->destination = *d; s->cp = p->cp; }
    }
    if (!s->mapping.lease) s->mapping = *m;
    return 0;
}
static int native_balance(struct functional_face_native_ap *s) {
    int rc = native_writer(s, FACE_NATIVE_AP_WRITER_CHECK);
    if (!rc && s->open_live) {
        if (s->close_attempted) rc = -EIO;
        else { s->close_attempted = 1; rc = native_operation(s, 0x25); if (!rc) s->open_live = 0; }
    }
    if (!rc && s->owner_live) {
        if (s->free_attempted) rc = -EIO;
        else { s->free_attempted = 1; rc = native_operation(s, 0x23); if (!rc) s->owner_live = 0; }
    }
    if (!rc) rc = native_writer(s, FACE_NATIVE_AP_WRITER_END);
    s->cleanup_error = rc;
    if (rc) return native_fault(s, rc, s->uncertain);
    s->source_live = s->candidate_capability = 0;
    return 0;
}
static int native_token(struct functional_face_native_ap *s, const struct functional_face_ap_borrow *b) {
    return b && s->source_live && s->owner_live && s->open_live && s->writer_live &&
        native_span_equal(&b->span, &s->token.span) && b->nonce && b->nonce == s->token.nonce &&
        b->offset == s->token.offset && b->bytes == s->token.bytes;
}
static int native_acquire(void *context, const struct functional_face_ap_span *a, size_t offset, size_t bytes,
    struct functional_face_ap_borrow *out) {
    struct functional_face_native_ap *s = context;
    int rc = native_enter(s);
    if (rc) return rc;
    if (!a || !out || offset || bytes != s->native_birth.span.bytes || !native_span_equal(a, &s->native_birth.span))
        return native_leave(s, -ESTALE);
    if (s->attempted) return native_leave(s, -EALREADY);
    if (s->observer->active) return native_leave(s, -EBUSY);
    struct functional_face_ap_birth current = {0};
    rc = functional_face_ap_observed_birth(s->observer, s->owner_tid, a->unit, a->handle, &current);
    if (!rc && (!native_birth_equal(&current, &s->birth) || current.any_free_observed)) rc = -ESTALE;
    if (rc) return native_leave(s, rc);
    s->attempted = 1;
    rc = native_writer(s, FACE_NATIVE_AP_WRITER_BEGIN);
    if (rc) return native_leave(s, rc);
    rc = native_operation(s, 0x21);
    if (rc) { s->source_live = 1; return native_leave(s, rc); }
    s->owner_live = s->source_live = 1;
    rc = native_operation(s, 0x24);
    if (!rc) {
        s->open_live = 1;
        const unsigned char *p = s->operations[1].observed.reply_wire;
        uint64_t address = native_le(p + 24, 8);
        if (native_le(p + 8, 2) != 1 || native_le(p + 12, 4) != a->handle ||
            native_le(p + 32, 4) != bytes || bytes > UINT64_MAX - address) rc = -EPROTO;
        else { s->native_address = address; rc = native_mapping(s, NULL); }
    }
    if (!rc) rc = native_writer(s, FACE_NATIVE_AP_WRITER_CHECK);
    if (rc) {
        if (!s->faulted) (void)native_balance(s);
        return native_leave(s, rc);
    }
    s->token = (struct functional_face_ap_borrow){.span = *a, .nonce = s->writer.lease, .offset = 0, .bytes = bytes};
    s->candidate_capability = 1; *out = s->token;
    return native_leave(s, 0);
}
static long native_read(void *context, const struct functional_face_ap_borrow *b, size_t offset, void *out, size_t bytes) {
    struct functional_face_native_ap *s = context;
    int rc = native_enter(s);
    if (rc) return rc;
    if (!native_token(s, b) || !out || !bytes || bytes > LONG_MAX || offset != s->bytes_read ||
        offset > b->bytes || bytes > b->bytes - offset) return native_leave(s, -ESTALE);
    size_t done = 0;
    while (done < bytes) {
        rc = native_writer(s, FACE_NATIVE_AP_WRITER_CHECK);
        if (!rc) rc = native_mapping(s, s->cp.count ? &s->destination : NULL);
        if (rc) return native_leave(s, rc);
        uint64_t physical = s->mapping.physical + offset + done;
        size_t n = 4096 - (size_t)(physical & 4095u);
        if (n > bytes - done) n = bytes - done;
        long got = s->ops.read_physical(s->io_context, &s->mapping, physical, (unsigned char *)out + done, n);
        rc = native_writer(s, FACE_NATIVE_AP_WRITER_CHECK);
        if (rc) return native_leave(s, rc);
        if (got < 0 || (unsigned long)got > n) return native_leave(s, got < 0 && got >= -4095 ? (int)got : -EIO);
        done += (size_t)got; s->bytes_read += (size_t)got;
        if ((size_t)got != n) { native_leave(s, 0); return (long)done; }
    }
    native_leave(s, 0); return (long)done;
}
static int native_check_disjoint(void *context, const struct functional_face_ap_borrow *b,
    const struct functional_face_dmm_descriptor *d) {
    struct functional_face_native_ap *s = context;
    int rc = native_enter(s);
    if (rc) return rc;
    if (!native_token(s, b) || !d) return native_leave(s, -ESTALE);
    rc = native_writer(s, FACE_NATIVE_AP_WRITER_CHECK);
    if (!rc) rc = native_mapping(s, d);
    return native_leave(s, rc);
}
static int native_release(void *context, const struct functional_face_ap_borrow *b) {
    struct functional_face_native_ap *s = context;
    int rc = native_enter(s);
    if (rc) return rc;
    if (!native_token(s, b)) return native_leave(s, -ESTALE);
    rc = native_balance(s);
    return native_leave(s, rc);
}
int functional_face_native_ap_init(struct functional_face_native_ap *s, const struct functional_face_native_ap_ops *ops,
    void *context, const struct functional_face_ap_observer *observer,
    const struct functional_face_native_ap_reference *birth, struct functional_face_ap_provider *out) {
    if (!s || !birth || !out) return -EINVAL;
    if (s->initialized && (s->owner_pid != getpid() || s->owner_tid != NATIVE_TID())) return -ECHILD;
    if (s->initialized || atomic_load_explicit(&s->busy, memory_order_acquire)) return -EALREADY;
    if (!ops || !observer || !ops->original_native_operation || !ops->read_physical ||
        !ops->prove_mapping_and_disjoint || !ops->source_writer_serial) return -ENODATA;
    if (!native_shape(birth)) return -ESTALE;
    struct functional_face_ap_birth fact = {0};
    int64_t tid = NATIVE_TID();
    int rc = functional_face_ap_observed_birth(observer, tid, birth->span.unit, birth->span.handle, &fact);
    if (rc) return rc;
    if (fact.any_free_observed || observer->active || !fact.observation_sequence ||
        observer->sequence < fact.observation_sequence || fact.observation_sequence != birth->birth_sequence)
        return -ESTALE;
    s->owner_pid = getpid(); s->owner_tid = tid; s->observer = observer; s->birth = fact;
    s->native_birth = s->reference = *birth; s->last_sequence = observer->sequence;
    s->ops = *ops; s->io_context = context; s->initialized = 1;
    *out = (struct functional_face_ap_provider){s, native_acquire, native_read, native_check_disjoint, native_release};
    return 0;
}
