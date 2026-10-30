/* SPDX-License-Identifier: MIT */
/* Reuse the actual typed CP transport fixture and saved-creator ledger. */
#define main fixture_original_main
#include "test-functional-face-runtime.c"
#undef main
#include <limits.h>
#include "functional-face-transfer.h"

struct ap_memory {
    unsigned char *data;
    struct functional_face_ap_span saved;
    struct functional_face_ap_borrow lease;
    uint64_t next_nonce, digest;
    size_t bytes_read;
    unsigned int acquisitions, releases, reads, disjoint_checks, live;
    int acquire_error, release_error, disjoint_error, malformed, read_error, probe;
    size_t fail_offset;
    long read_result;
    struct functional_face_transfer *transfer;
    struct functional_face_dmm_descriptor destination;
    struct functional_face_transfer_input input;
};
static unsigned int write_calls, read_calls, write_releases, read_releases;
static size_t write_bytes, read_bytes, released_verified;
static int invalidate_release;
static struct functional_face_dmm_borrow retained_destination;
static void probe_during_copy(struct ap_memory *);

int __real_functional_face_dmm_write(const struct functional_face_dmm_borrow *, size_t,
    const void *, size_t, struct functional_face_dmm_readback *);
int __real_functional_face_dmm_read(const struct functional_face_dmm_borrow *, size_t,
    void *, size_t, struct functional_face_dmm_readback *);
int __real_functional_face_dmm_release_borrow(const struct functional_face_dmm_borrow *,
    struct functional_face_dmm_readback *);
int __wrap_functional_face_dmm_write(const struct functional_face_dmm_borrow *b, size_t off,
    const void *data, size_t n, struct functional_face_dmm_readback *rb) {
    assert(n && n <= 4096 && off == write_bytes);
    assert(b->access == (FUNCTIONAL_FACE_DMM_WRITE | FUNCTIONAL_FACE_DMM_TRANSFER));
    int rc = __real_functional_face_dmm_write(b, off, data, n, rb);
    ++write_calls;
    if (!rc) { assert(rb->verified_bytes == n); write_bytes += n; }
    return rc;
}
int __wrap_functional_face_dmm_read(const struct functional_face_dmm_borrow *b, size_t off,
    void *data, size_t n, struct functional_face_dmm_readback *rb) {
    assert(n && n <= 4096 && off == read_bytes);
    assert(b->access == (FUNCTIONAL_FACE_DMM_READ | FUNCTIONAL_FACE_DMM_TRANSFER));
    int rc = __real_functional_face_dmm_read(b, off, data, n, rb);
    ++read_calls;
    if (!rc) { assert(rb->verified_bytes == n); read_bytes += n; }
    return rc;
}
int __wrap_functional_face_dmm_release_borrow(const struct functional_face_dmm_borrow *b,
    struct functional_face_dmm_readback *rb) {
    if (b->access & FUNCTIONAL_FACE_DMM_WRITE) ++write_releases; else ++read_releases;
    /* A changed submitted nonce exercises the real backend's stale-token error. */
    struct functional_face_dmm_borrow submitted = *b;
    if (invalidate_release == (int)(write_releases + read_releases)) {
        retained_destination = *b; ++submitted.nonce;
    }
    int rc = __real_functional_face_dmm_release_borrow(&submitted, rb);
    if (!rc && (b->access & FUNCTIONAL_FACE_DMM_WRITE)) released_verified += rb->verified_bytes;
    return rc;
}
static void reset_counts(void) {
    write_calls = read_calls = write_releases = read_releases = 0;
    write_bytes = read_bytes = released_verified = 0;
    invalidate_release = 0;
}
static int ap_span_equal(const struct functional_face_ap_span *a, const struct functional_face_ap_span *b) {
    return a->domain == b->domain && a->unit == b->unit && a->handle == b->handle &&
        a->epoch == b->epoch && a->owner == b->owner && a->bytes == b->bytes;
}
static int ap_lease_equal(const struct functional_face_ap_borrow *a, const struct functional_face_ap_borrow *b) {
    return ap_span_equal(&a->span, &b->span) && a->nonce == b->nonce && a->offset == b->offset && a->bytes == b->bytes;
}
static int ap_acquire(void *context, const struct functional_face_ap_span *saved,
    size_t offset, size_t bytes, struct functional_face_ap_borrow *out) {
    struct ap_memory *a = context; ++a->acquisitions;
    if (a->acquire_error) return a->acquire_error;
    if (!ap_span_equal(saved, &a->saved) || offset || bytes != a->saved.bytes || a->live) return -ESTALE;
    a->lease = (struct functional_face_ap_borrow){a->saved, ++a->next_nonce, offset, bytes};
    if (a->malformed == 1) a->lease.nonce = 0;
    if (a->malformed == 2) ++a->lease.span.epoch;
    if (a->malformed == 3) a->lease.offset = 1;
    if (a->malformed == 4) --a->lease.bytes;
    a->live = 1; *out = a->lease; return 0;
}
static long ap_read(void *context, const struct functional_face_ap_borrow *b,
    size_t off, void *out, size_t n) {
    struct ap_memory *a = context; ++a->reads;
    assert(n && n <= 4096 && off == a->bytes_read);
    if (!a->live || !ap_lease_equal(b, &a->lease)) return -ESTALE;
    if (!off && a->probe) probe_during_copy(a);
    if (a->read_error && off >= a->fail_offset) return a->read_result;
    assert(off <= b->bytes && n <= b->bytes - off);
    memcpy(out, a->data + b->offset + off, n); a->bytes_read += n;
    return (long)n;
}
static int ap_disjoint(void *context, const struct functional_face_ap_borrow *b,
    const struct functional_face_dmm_descriptor *d) {
    struct ap_memory *a = context; ++a->disjoint_checks;
    assert(a->live && ap_lease_equal(b, &a->lease));
    uintptr_t source_start = (uintptr_t)a->data + b->offset;
    assert(b->bytes <= UINTPTR_MAX - source_start && d->mapped_bytes <= UINTPTR_MAX - d->host_view);
    if (!(source_start + b->bytes <= d->host_view || d->host_view + d->mapped_bytes <= source_start))
        return -EADDRINUSE;
    return a->disjoint_error;
}
static int ap_release(void *context, const struct functional_face_ap_borrow *b) {
    struct ap_memory *a = context; ++a->releases;
    assert(a->live && ap_lease_equal(b, &a->lease));
    assert(hash(a->data, a->saved.bytes) == a->digest);
    if (a->release_error) return a->release_error;
    a->live = 0; return 0;
}
static struct functional_face_ap_provider provider(struct ap_memory *a) {
    return (struct functional_face_ap_provider){a, ap_acquire, ap_read, ap_disjoint, ap_release};
}
static void ap_setup(struct ap_memory *a, const struct functional_face_dmm_descriptor *d, unsigned int seed) {
    memset(a, 0, sizeof *a); a->data = malloc(d->bytes); assert(a->data);
    for (size_t i = 0; i < d->bytes; ++i) a->data[i] = (unsigned char)((i * 37 + seed * 53 + 11) ^ (i >> 7));
    a->saved = (struct functional_face_ap_span){0, d->unit, 0x400u + (d->unit - 0x1d9),
        UINT64_C(0x100000) + seed, OWNER ^ UINT64_C(0x55aa), d->bytes};
    a->digest = hash(a->data, d->bytes); a->destination = *d;
    a->input = (struct functional_face_transfer_input){a->saved.handle, 0, d->handle, 0, (uint32_t)d->bytes};
}
static void transfer_setup(struct functional_face_transfer *s, struct ap_memory *a) {
    memset(s, 0, sizeof *s); struct functional_face_ap_provider p = provider(a);
    assert(!functional_face_transfer_init(s, &p)); a->transfer = s;
}
static int copy(struct functional_face_transfer *s, struct ap_memory *a) {
    return functional_face_transfer_copy(s, OWNER, &a->saved, &a->destination, &a->input);
}
static void assert_idle(const struct functional_face_transfer *s) {
    assert(!atomic_load(&s->busy));
    assert(!s->faulted && !s->source_live && !s->destination_live);
}
static void verify_cp(const struct ap_memory *a, size_t prefix) {
    struct functional_face_dmm_borrow b; struct functional_face_dmm_readback rb;
    assert(!functional_face_runtime_borrow_destination(OWNER, a->destination.unit, a->destination.handle,
        &a->destination, 0, a->destination.bytes, FUNCTIONAL_FACE_DMM_READ, &b));
    unsigned char *actual = malloc(b.bytes); assert(actual);
    assert(!__real_functional_face_dmm_read(&b, 0, actual, b.bytes, &rb));
    assert(rb.verified_bytes == b.bytes && !memcmp(actual, a->data, prefix));
    for (size_t i = prefix; i < b.bytes; ++i) assert(!actual[i]);
    const unsigned char *backing = (const unsigned char *)a->destination.host_view;
    for (size_t i = b.bytes; i < a->destination.mapped_bytes; ++i) assert(!backing[i]);
    assert(hash(a->data, a->saved.bytes) == a->digest);
    assert(!__real_functional_face_dmm_release_borrow(&b, &rb)); free(actual);
}
static void finish(struct ap_memory *a) {
    assert(!a->live); (void)operation(0x23, a->destination.unit, a->destination.handle, 0, 0);
    free(a->data); assert(!functional_face_dmm_shutdown());
}
static void positive_test(void) {
    struct dmm_service speech = {.physical = DMM_TEST_PHYSICAL};
    speech.memory = malloc(DMM_TEST_SIZE); assert(speech.memory);
    unsigned char q[40] = {0x20}, r[40]; put(q + 4, 0x63a, 4); put(q + 22, 1, 2);
    for (unsigned int i = 0; i < 2; ++i) {
        assert(!dmm_service_reply(&speech, q, 40, r));
        speech.slots[i].creator_kind = DMM_CREATOR_SPEECH_INITIAL;
        assert(speech.slots[i].handle == 0x8400u + i && speech.slots[i].open_count == 1);
    }
    for (size_t i = 0; i < DMM_TEST_SIZE; ++i) speech.memory[i] = (unsigned char)(i ^ (i >> 9) ^ 0x95);
    struct dmm_service saved = speech;
    unsigned char *saved_bytes = malloc(DMM_TEST_SIZE); assert(saved_bytes); memcpy(saved_bytes, speech.memory, DMM_TEST_SIZE);
    setup(); size_t total = 0; unsigned int failures = 0;
    for (unsigned int i = 0; i < 3; ++i) {
        struct functional_face_dmm_descriptor d = create(0x1d9 + i);
        assert(d.logical == UINT64_C(0x70000000) + i * UINT64_C(0x100000));
        struct ap_memory a; ap_setup(&a, &d, i + 1);
        struct functional_face_transfer s; transfer_setup(&s, &a); reset_counts();
        int rc = copy(&s, &a);
        printf("POSITIVE unit=%x result=%d operation=%d write=%zu read=%zu source_digest=%016" PRIx64
            " destination_digest=%016" PRIx64 " releases=%u/%u complete=%u\n", d.unit, rc, s.last.operation_result,
            s.last.written, s.last.readback, s.last.source_digest, s.last.destination_digest,
            write_releases, read_releases, s.last.content_complete); fflush(stdout);
        if (rc) ++failures;
        assert_idle(&s);
        assert(s.last.written == d.bytes && s.last.readback == d.bytes);
        assert(s.last.content_complete == (unsigned int)!rc);
        assert(s.last.source_digest == a.digest && s.last.destination_digest == a.digest);
        assert(s.last.source_acquired == 1 && s.last.destination_acquired == 2);
        assert(s.last.source_released == 1 && s.last.destination_released == 1);
        assert(!s.last.operation_result && !s.last.source_release_result && !s.last.destination_release_result);
        assert(a.bytes_read == d.bytes && a.acquisitions == 1 && a.releases == 1 && a.disjoint_checks == 1);
        assert(write_bytes == d.bytes && read_bytes == d.bytes && released_verified == d.bytes);
        assert(write_calls == (d.bytes + 4095) / 4096 && read_calls == write_calls);
        assert(write_releases == 1 && read_releases == 1); verify_cp(&a, d.bytes); total += d.bytes;
        (void)operation(0x23, d.unit, d.handle, 0, 0); free(a.data);
    }
    assert(total == 514304); assert(!functional_face_runtime_snapshot(&diagnostic));
    assert(!diagnostic.faults && !diagnostic.retained && !diagnostic.live_creators);
    assert(diagnostic.actual_receive == 6 && diagnostic.actual_request_free == 6 && diagnostic.actual_reply_free == 6);
    assert(diagnostic.ledger_commit == 6 && request_frees == 6 && reply_frees == 6 && receives == 6);
    assert(!memcmp(&speech, &saved, sizeof speech) && !memcmp(speech.memory, saved_bytes, DMM_TEST_SIZE));
    assert(!functional_face_dmm_shutdown()); free(saved_bytes); free(speech.memory);
    puts("COUNTS units=3 source_read=514304 write=514304 internal_readback=514304 independent_read=514304 full_verified=514304 write_release=3 read_release=3 source_release=3 actual_receive=6 request_free=6 reply_free=6 ledger_commit=6 speech_bytes=1048576 speech_unchanged=1");
    printf("RECEIPTS content_complete=%u incomplete=%u\n", 3 - failures, failures); fflush(stdout);
    assert(!failures);
}
static void probe_during_copy(struct ap_memory *a) {
    if (a->probe == 1) {
        /* This is a real reentrant call while the outer consumer owns busy. */
        assert(copy(a->transfer, a) == -EBUSY);
        assert(a->acquisitions == 1 && a->reads == 1);
    } else if (a->probe == 2) {
        pid_t child = fork(); assert(child >= 0);
        if (!child) {
            assert(atomic_load(&a->transfer->busy) == 1);
            struct functional_face_ap_provider p = provider(a);
            assert(functional_face_transfer_init(a->transfer, &p) == -ECHILD);
            assert(copy(a->transfer, a) == -ECHILD); _exit(0);
        }
        int status; assert(waitpid(child, &status, 0) == child);
        assert(WIFEXITED(status) && WEXITSTATUS(status) == 0);
    } else {
        assert(a->probe == 3);
        assert(!functional_face_runtime_snapshot(&diagnostic));
        uint64_t commits = diagnostic.ledger_commit;
        assert(diagnostic.model.units[a->destination.unit - 0x1d9].borrows == 1);
        assert(diagnostic.model.units[a->destination.unit - 0x1d9].transfers == 1);
        (void)operation(0x23, a->destination.unit, a->destination.handle, 0, -1);
        /* A real open/close completes without revoking the creator's borrow. */
        (void)operation(0x24, a->destination.unit, a->destination.handle, 0, 0);
        (void)operation(0x25, a->destination.unit, a->destination.handle, 0, 0);
        assert(!functional_face_runtime_snapshot(&diagnostic));
        assert(diagnostic.ledger_commit == commits + 2 && diagnostic.units[a->destination.unit - 0x1d9].live_creator);
        assert(diagnostic.model.units[a->destination.unit - 0x1d9].borrows == 1);
        assert(!diagnostic.opens && !diagnostic.shares && !diagnostic.faults);
    }
}
static void one_setup(struct ap_memory *a, struct functional_face_transfer *s) {
    setup(); struct functional_face_dmm_descriptor d = create(0x1da);
    ap_setup(a, &d, 13); transfer_setup(s, a); reset_counts();
}
static void assert_failure(const struct functional_face_transfer *s, const struct ap_memory *a,
    int operation_error, unsigned int destinations) {
    assert_idle(s);
    assert(s->last.operation_result == operation_error && !s->last.content_complete);
    assert(s->last.source_acquired == 1 && s->last.source_released == 1 && !a->live);
    assert(s->last.destination_acquired == destinations && s->last.destination_released == !!destinations);
    assert(!s->last.source_release_result && !s->last.destination_release_result);
}
static void init_test(void) {
    struct ap_memory a = {0}; struct functional_face_ap_provider p = provider(&a);
    struct functional_face_transfer s = {0}, before = s;
    assert(functional_face_transfer_init(NULL, &p) == -EINVAL);
    assert(functional_face_transfer_init(&s, NULL) == -EINVAL && !memcmp(&s, &before, sizeof s));
    for (unsigned int i = 0; i < 4; ++i) {
        struct functional_face_ap_provider bad = p;
        if (i == 0) bad.acquire = NULL;
        if (i == 1) bad.read = NULL;
        if (i == 2) bad.check_disjoint = NULL;
        if (i == 3) bad.release = NULL;
        assert(functional_face_transfer_init(&s, &bad) == -EINVAL && !memcmp(&s, &before, sizeof s));
    }
    assert(functional_face_transfer_copy(&s, OWNER, NULL, NULL, NULL) == -ENODATA);
    assert(!functional_face_transfer_init(&s, &p));
    assert(functional_face_transfer_init(&s, &p) == -EALREADY);
    assert(!a.acquisitions && !a.releases && !a.reads);
}
static unsigned int binding_cases;
static void reject_binding(struct functional_face_transfer *s, struct ap_memory *a, uint64_t owner,
    const struct functional_face_ap_span *ap, const struct functional_face_dmm_descriptor *d,
    const struct functional_face_transfer_input *q, int error) {
    struct functional_face_ap_span saved_ap = *ap;
    struct functional_face_dmm_descriptor saved_d = *d;
    struct functional_face_transfer_input saved_q = *q;
    assert(functional_face_transfer_copy(s, owner, ap, d, q) == error);
    assert(s->last.operation_result == error && !s->last.content_complete);
    assert(!memcmp(ap, &saved_ap, sizeof saved_ap) && !memcmp(d, &saved_d, sizeof saved_d));
    assert(!memcmp(q, &saved_q, sizeof saved_q)); assert_idle(s);
    assert(!a->acquisitions && !a->releases && !write_calls && !read_calls);
    assert(!s->last.source_acquired && !s->last.destination_acquired && !s->last.destination_released);
    ++binding_cases;
}
static void binding_test(void) {
    struct ap_memory a; struct functional_face_transfer s; one_setup(&a, &s);
    struct functional_face_ap_span ap;
    struct functional_face_dmm_descriptor d;
    struct functional_face_transfer_input q;
#define BAD_AP(field, value, error) do { ap = a.saved; ap.field = (value); \
    reject_binding(&s, &a, OWNER, &ap, &a.destination, &a.input, error); } while (0)
    BAD_AP(domain, 1, -ESTALE); BAD_AP(unit, 0x1d8, -EINVAL); BAD_AP(unit, 0x1dc, -EINVAL);
    BAD_AP(unit, 0x1d9, -ESTALE); BAD_AP(handle, 0, -ESTALE); BAD_AP(handle, 1, -ESTALE);
    BAD_AP(handle, a.saved.handle | 0x8000u, -ESTALE); BAD_AP(handle, 0x10000, -ESTALE);
    BAD_AP(epoch, 0, -ESTALE); BAD_AP(owner, 0, -ESTALE); BAD_AP(bytes, 0, -ESTALE);
    BAD_AP(bytes, a.saved.bytes - 1, -ESTALE); BAD_AP(bytes, a.saved.bytes + 1, -ESTALE);
    BAD_AP(bytes, SIZE_MAX, -ESTALE);
#undef BAD_AP
#define BAD_D(field, value) do { d = a.destination; d.field = (value); \
    reject_binding(&s, &a, OWNER, &a.saved, &d, &a.input, -ESTALE); } while (0)
    BAD_D(domain, 0); BAD_D(unit, 0x1d9); BAD_D(owner, OWNER + 1); BAD_D(epoch, 0);
    BAD_D(reference, 1); BAD_D(bytes, 0); BAD_D(bytes, a.destination.bytes - 1);
    BAD_D(bytes, a.destination.bytes + 1); BAD_D(bytes, SIZE_MAX);
#undef BAD_D
#define BAD_Q(field, value) do { q = a.input; q.field = (value); \
    reject_binding(&s, &a, OWNER, &a.saved, &a.destination, &q, -ESTALE); } while (0)
    BAD_Q(source_handle, a.input.source_handle + 1); BAD_Q(destination_handle, a.input.destination_handle + 1);
    BAD_Q(source_offset, 1); BAD_Q(destination_offset, 1); BAD_Q(source_offset, UINT32_MAX);
    BAD_Q(destination_offset, UINT32_MAX); BAD_Q(bytes, 0); BAD_Q(bytes, a.input.bytes - 1);
    BAD_Q(bytes, a.input.bytes + 1); BAD_Q(bytes, UINT32_MAX);
#undef BAD_Q
    reject_binding(&s, &a, 0, &a.saved, &a.destination, &a.input, -EINVAL);
    verify_cp(&a, 0); printf("BINDING rejected=%u acquired=0 unchanged=1\n", binding_cases); finish(&a);
}
static void acquire_test(void) {
    struct ap_memory a; struct functional_face_transfer s; one_setup(&a, &s);
    a.acquire_error = -EACCES; assert(copy(&s, &a) == -EACCES); assert_idle(&s);
    assert(a.acquisitions == 1 && !a.live && !a.reads && !a.releases && !a.disjoint_checks);
    assert(s.last.operation_result == -EACCES && !s.last.source_acquired && !s.last.destination_acquired);
    assert(!s.last.destination_released && !s.last.content_complete);
    a.acquire_error = 1; assert(copy(&s, &a) == -EPROTO); assert_idle(&s);
    assert(a.acquisitions == 2 && !a.releases && !a.live && !s.last.destination_released);
    verify_cp(&a, 0); finish(&a);
}
static void malformed_test(void) {
    struct ap_memory a; struct functional_face_transfer s; one_setup(&a, &s);
    for (int i = 1; i <= 4; ++i) {
        struct functional_face_ap_provider p = provider(&a);
        a.malformed = i; a.acquisitions = a.releases = a.disjoint_checks = 0;
        s = (struct functional_face_transfer){0}; assert(!functional_face_transfer_init(&s, &p));
        assert(copy(&s, &a) == -ESTALE); assert_failure(&s, &a, -ESTALE, 0);
        assert(!a.disjoint_checks && !write_calls && !read_calls && !a.reads);
        assert(ap_lease_equal(&s.source, &a.lease) && a.releases == 1);
    }
    verify_cp(&a, 0); finish(&a);
}
static void disjoint_test(void) {
    struct ap_memory a; struct functional_face_transfer s; one_setup(&a, &s);
    a.disjoint_error = -EADDRINUSE;
    assert(copy(&s, &a) == -EADDRINUSE); assert_failure(&s, &a, -EADDRINUSE, 0);
    assert(a.disjoint_checks == 1 && !a.reads && !write_calls && !read_calls);
    a.disjoint_error = 1;
    assert(copy(&s, &a) == -EPROTO); assert_failure(&s, &a, -EPROTO, 0);
    unsigned char *owned = a.data; uint64_t original_digest = a.digest;
    a.data = (unsigned char *)a.destination.host_view; a.digest = hash(a.data, a.saved.bytes);
    a.disjoint_error = 0; assert(a.saved.domain != a.destination.domain);
    assert(copy(&s, &a) == -EADDRINUSE); assert_failure(&s, &a, -EADDRINUSE, 0);
    assert(a.disjoint_checks == 3 && !write_calls && !read_calls);
    a.data = owned; a.digest = original_digest; verify_cp(&a, 0); finish(&a);
}
static void read_failure_test(const char *mode) {
    struct ap_memory a; struct functional_face_transfer s; one_setup(&a, &s);
    const long normal[] = {0, 4095, -EREMOTEIO, -EINTR, LONG_MAX};
    const long wide[] = {LONG_MIN + 1, LONG_MIN, (long)INT_MIN - 1};
    const long stale[] = {-ESTALE};
    const long *values = !strcmp(mode, "long-errors") ? wide : !strcmp(mode, "stale-source") ? stale : normal;
    size_t count = values == wide ? sizeof wide / sizeof *wide : values == stale ? 1 : sizeof normal / sizeof *normal;
    for (size_t i = 0; i < count; ++i) {
        struct functional_face_ap_provider p = provider(&a);
        s = (struct functional_face_transfer){0}; assert(!functional_face_transfer_init(&s, &p));
        a.read_error = 1; a.read_result = values[i]; a.acquisitions = a.releases = a.reads = 0;
        reset_counts(); int rc = copy(&s, &a);
        printf("SOURCE_FAILURE value=%ld result=%d operation=%d written=%zu readback=%zu complete=%u\n",
            values[i], rc, s.last.operation_result, s.last.written, s.last.readback, s.last.content_complete); fflush(stdout);
        if (values[i] < INT_MIN) assert(rc == -EIO && s.last.operation_result == -EIO);
        else assert(rc == (values[i] < 0 ? (int)values[i] : -EIO));
        assert_failure(&s, &a, rc, 1);
        assert(!s.last.written && !s.last.readback && !write_calls && !read_calls);
        assert(a.reads == 1 && a.releases == 1 && write_releases == 1 && !read_releases);
        verify_cp(&a, 0);
    }
    finish(&a);
}
static void destination_blocked_test(void) {
    struct ap_memory a; struct functional_face_transfer s; one_setup(&a, &s);
    struct functional_face_dmm_borrow blocker; struct functional_face_dmm_readback rb;
    assert(!functional_face_runtime_borrow_destination(OWNER, a.destination.unit, a.destination.handle,
        &a.destination, 0, a.destination.bytes, FUNCTIONAL_FACE_DMM_READ, &blocker));
    assert(copy(&s, &a) == -EBUSY); assert_failure(&s, &a, -EBUSY, 0);
    assert(!a.reads && !write_calls && !read_calls && !write_releases && !read_releases);
    assert(!__real_functional_face_dmm_release_borrow(&blocker, &rb)); verify_cp(&a, 0); finish(&a);
}
static void stale_creator_test(void) {
    struct ap_memory a; struct functional_face_transfer s; one_setup(&a, &s);
    struct functional_face_dmm_descriptor original = a.destination;
    for (unsigned int i = 0; i < 7; ++i) {
        a.destination = original;
        if (i == 0) ++a.destination.epoch;
        if (i == 1) ++a.destination.registration;
        if (i == 2) ++a.destination.host_view;
        if (i == 3) ++a.destination.logical;
        if (i == 4) ++a.destination.mapped_bytes;
        if (i == 5) ++a.destination.handle;
        if (i == 6) ++a.destination.owner;
        a.input.destination_handle = a.destination.handle;
        struct functional_face_dmm_descriptor before = a.destination;
        int rc = functional_face_transfer_copy(&s, i == 6 ? OWNER + 1 : OWNER, &a.saved, &a.destination, &a.input);
        assert(rc == (i == 6 ? -EPERM : -ESTALE)); assert_failure(&s, &a, rc, 0);
        assert(!memcmp(&before, &a.destination, sizeof before) && !a.reads && !write_calls && !read_calls);
    }
    a.destination = original; a.input.destination_handle = original.handle; verify_cp(&a, 0); finish(&a);
}
static void partial_test(void) {
    struct ap_memory a; struct functional_face_transfer s; one_setup(&a, &s);
    a.read_error = 1; a.fail_offset = 8192; a.read_result = -EREMOTEIO; a.probe = 3;
    assert(copy(&s, &a) == -EREMOTEIO); assert_failure(&s, &a, -EREMOTEIO, 1);
    assert(s.last.written == 8192 && !s.last.readback && write_bytes == 8192 && !read_bytes);
    assert(a.bytes_read == 8192 && a.reads == 3 && write_calls == 2 && write_releases == 1 && !read_releases);
    assert(released_verified == 8192); verify_cp(&a, 8192); finish(&a);
    puts("PARTIAL source_read=8192 write=8192 full_verified=8192 suffix_untouched=1 actual_free_busy=1 actual_open_close=1");
}
static void probe_test(int probe) {
    struct ap_memory a; struct functional_face_transfer s; one_setup(&a, &s); a.probe = probe;
    int rc = copy(&s, &a); printf("PROBE kind=%d result=%d written=%zu readback=%zu\n", probe, rc, s.last.written, s.last.readback);
    fflush(stdout);
    assert(!rc); assert_idle(&s); assert(a.acquisitions == 1 && a.releases == 1 && s.last.content_complete);
    assert(write_releases == 1 && read_releases == 1); verify_cp(&a, a.saved.bytes); finish(&a);
}
static void repeat_test(void) {
    struct ap_memory first; struct functional_face_transfer s; one_setup(&first, &s);
    int first_result = copy(&s, &first); assert_idle(&s);
    struct functional_face_ap_borrow old = s.source;
    unsigned char *old_bytes = first.data; uint64_t old_digest = first.digest;
    struct ap_memory second; ap_setup(&second, &first.destination, 29);
    second.next_nonce = first.next_nonce; second.saved.handle = 0x7fffu;
    second.input.source_handle = second.saved.handle;
    /* The same provider context now owns a fresh immutable allocation. */
    first = second;
    reset_counts(); int second_result = copy(&s, &first); assert_idle(&s);
    assert(s.source.nonce != old.nonce && s.source.span.epoch != old.span.epoch);
    assert(first.digest != old_digest && s.last.source_digest == first.digest && s.last.destination_digest == first.digest);
    assert(hash(old_bytes, old.span.bytes) == old_digest);
    assert(write_bytes == first.saved.bytes && read_bytes == first.saved.bytes && s.last.destination_acquired == 2);
    assert(write_releases == 1 && read_releases == 1 && first.acquisitions == 1 && first.releases == 1);
    verify_cp(&first, first.saved.bytes); free(old_bytes); finish(&first);
    printf("REPEAT copies=2 fresh_allocation=1 fresh_epoch=1 fresh_nonce=1 original_source_unchanged=1 results=%d/%d\n",
        first_result, second_result); fflush(stdout);
    assert(!first_result && !second_result && s.last.content_complete);
}
static void source_release_test(int partial) {
    static struct ap_memory a; static struct functional_face_transfer s;
    one_setup(&a, &s); a.release_error = -EREMOTEIO;
    if (partial) { a.read_error = 1; a.fail_offset = 4096; a.read_result = -EPIPE; }
    assert(copy(&s, &a) == -EIO && s.faulted && s.source_live && !s.destination_live);
    assert(!atomic_load(&s.busy) && ap_lease_equal(&s.source, &a.lease) && a.live);
    assert(s.last.source_release_result == -EREMOTEIO && !s.last.source_released && !s.last.content_complete);
    assert(s.last.operation_result == (partial ? -EPIPE : 0));
    assert(!s.last.destination_release_result && s.last.destination_released);
    assert(s.last.written == (partial ? 4096 : a.saved.bytes) && s.last.readback == (partial ? 0 : a.saved.bytes));
    struct functional_face_transfer_receipt last = s.last; struct functional_face_ap_borrow retained = s.source;
    a.release_error = 0; assert(copy(&s, &a) == -EIO);
    assert(a.releases == 1 && ap_lease_equal(&s.source, &retained) && !memcmp(&s.last, &last, sizeof last));
    verify_cp(&a, partial ? 4096 : a.saved.bytes);
    /* No production retry API: process teardown owns the retained source. */
    (void)operation(0x23, a.destination.unit, a.destination.handle, 0, 0); assert(!functional_face_dmm_shutdown());
    assert(a.live && a.data && ap_lease_equal(&s.source, &a.lease));
    printf("SOURCE_RELEASE attempts=1 retained_full_token=1 sticky_fault=1 retry_callbacks=0 backing_retained=1 operation=%d cleanup=%d\n",
        s.last.operation_result, s.last.source_release_result);
}
static void destination_release_test(int phase) {
    struct ap_memory a; struct functional_face_transfer s; one_setup(&a, &s); invalidate_release = phase;
    int rc = copy(&s, &a); assert(rc == -EIO && s.faulted && s.destination_live && !s.source_live);
    assert(!atomic_load(&s.busy) && !memcmp(&s.destination, &retained_destination, sizeof retained_destination));
    assert(s.last.destination_release_result == -ESTALE && !s.last.destination_released && !s.last.content_complete);
    assert(s.last.destination_acquired == (unsigned int)phase && s.last.source_released && a.releases == 1);
    assert(s.last.operation_result == (phase == 1 ? -ESTALE : 0));
    assert(write_releases == 1 && read_releases == (unsigned int)(phase - 1));
    assert(s.last.written == a.saved.bytes && s.last.readback == (phase == 1 ? 0 : a.saved.bytes));
    assert(!functional_face_runtime_snapshot(&diagnostic));
    assert(diagnostic.model.units[1].borrows == 1 && diagnostic.model.units[1].transfers == 1);
    struct functional_face_transfer_receipt last = s.last;
    assert(copy(&s, &a) == -EIO && !memcmp(&last, &s.last, sizeof last));
    assert(write_releases == 1 && read_releases == (unsigned int)(phase - 1) && a.releases == 1);
    (void)operation(0x23, a.destination.unit, a.destination.handle, 0, -1);
    assert(!memcmp((void *)a.destination.host_view, a.data, a.saved.bytes));
    assert(hash(a.data, a.saved.bytes) == a.digest);
    printf("DESTINATION_RELEASE phase=%d actual_stale_rejections=1 retained_full_token=1 live_borrow=1 retry_calls=0\n", phase);
    /* Keep the real CP mmap/borrow intact; the test process owns teardown. */
    free(a.data);
}
struct descriptor_memory {
    unsigned char source_bytes[8], destination_bytes[8];
    uintptr_t addresses[4];
    unsigned int reads, mutation_at, fail_at;
    long fail_result;
};
static long descriptor_read(void *context, uintptr_t address, void *out, size_t n) {
    struct descriptor_memory *d = context;
    assert(n == 8 && d->reads < 4); d->addresses[d->reads++] = address;
    if (d->reads == d->fail_at) return d->fail_result;
    if (address != (uintptr_t)d->source_bytes && address != (uintptr_t)d->destination_bytes) return -EFAULT;
    unsigned char *actual = address == (uintptr_t)d->source_bytes ? d->source_bytes : d->destination_bytes;
    if (d->reads == d->mutation_at) actual[0] ^= 1;
    memcpy(out, actual, n); return (long)n;
}
static void sdk_golden(unsigned char *wire, struct descriptor_memory *d, unsigned int index) {
    static const unsigned char golden_tail[32] = {
        0x00, 0x40, 0x06, 0x00, 1, 0, 0, 0,
        0x78, 0x56, 0x34, 0x12, 0, 0, 0, 0,
        0x00, 0xef, 0xcd, 0xab, 0, 0, 0, 0,
        0xd8, 0xc7, 0xb6, 0xa5, 0x44, 0x33, 0x22, 0x11
    };
    static const unsigned char length_bytes[3][4] = {
        {0x00, 0x40, 0x06, 0x00}, {0x00, 0xc8, 0, 0}, {0x00, 0xd1, 0, 0}
    };
    memset(d, 0, sizeof *d); memset(wire, 0, 48);
    put(d->source_bytes, 0x400u + index, 4); put(d->destination_bytes, 0x8402u + index, 4);
    put(wire, (uintptr_t)d->source_bytes, 8); put(wire + 8, (uintptr_t)d->destination_bytes, 8);
    memcpy(wire + 16, golden_tail, sizeof golden_tail); memcpy(wire + 16, length_bytes[index], 4);
}
static unsigned int parser_rejections;
static void reject_sdk(unsigned char *wire, size_t bytes, struct descriptor_memory *d, int error,
    unsigned int reads) {
    unsigned char before[48]; memcpy(before, wire, sizeof before);
    struct functional_face_sdk_request out; memset(&out, 0xa7, sizeof out);
    struct functional_face_sdk_request untouched = out;
    assert(functional_face_transfer_decode_sdk48(wire, bytes, descriptor_read, d, &out) == error);
    assert(!memcmp(&out, &untouched, sizeof out) && !memcmp(wire, before, sizeof before));
    assert(d->reads == reads); ++parser_rejections;
}
static void sdk48_test(void) {
    unsigned char wire[48], before[48]; struct descriptor_memory d;
    struct functional_face_sdk_request out;
    for (unsigned int i = 0; i < 3; ++i) {
        sdk_golden(wire, &d, i); memcpy(before, wire, sizeof wire);
        assert(!functional_face_transfer_decode_sdk48(wire, sizeof wire, descriptor_read, &d, &out));
        assert(d.reads == 4 && d.addresses[0] == (uintptr_t)d.source_bytes && d.addresses[1] == (uintptr_t)d.destination_bytes);
        assert(d.addresses[2] == d.addresses[0] && d.addresses[3] == d.addresses[1]);
        assert(out.input.source_handle == 0x400u + i && out.input.destination_handle == 0x8402u + i);
        assert(!out.input.source_offset && !out.input.destination_offset);
        assert(out.input.bytes == (i == 0 ? 409600u : i == 1 ? 51200u : 53504u));
        assert(out.source_descriptor == (uintptr_t)d.source_bytes && out.destination_descriptor == (uintptr_t)d.destination_bytes);
        assert(out.callback == 0x12345678u && out.callback_context == 0xabcdef00u);
        assert(out.submission_result_before == 0xa5b6c7d8u && out.opaque_padding == 0x11223344u);
        assert(!memcmp(before, wire, sizeof wire));
    }
    sdk_golden(wire, &d, 0); reject_sdk(wire, 47, &d, -EINVAL, 0);
    sdk_golden(wire, &d, 0); reject_sdk(wire, 49, &d, -EINVAL, 0);
    assert(functional_face_transfer_decode_sdk48(NULL, 48, descriptor_read, &d, &out) == -EINVAL);
    assert(functional_face_transfer_decode_sdk48(wire, 48, NULL, &d, &out) == -EINVAL);
    assert(functional_face_transfer_decode_sdk48(wire, 48, descriptor_read, &d, NULL) == -EINVAL);
#define BAD_WIRE(offset, value, width, error, reads) do { sdk_golden(wire, &d, 0); \
    put(wire + (offset), (value), (width)); reject_sdk(wire, 48, &d, error, reads); } while (0)
    BAD_WIRE(20, 0, 4, -ENOTSUP, 0); BAD_WIRE(20, 2, 4, -ENOTSUP, 0);
    BAD_WIRE(0, 0, 8, -ENOTSUP, 0); BAD_WIRE(8, 0, 8, -ENOTSUP, 0);
    BAD_WIRE(24, 0, 8, -ENOTSUP, 0); BAD_WIRE(32, 0, 8, -ENOTSUP, 0);
    BAD_WIRE(0, UINTPTR_MAX - 3, 8, -ENOTSUP, 0); BAD_WIRE(8, UINTPTR_MAX - 3, 8, -ENOTSUP, 0);
    BAD_WIRE(0, UINT64_C(0x800000000000), 8, -EIO, 4);
    BAD_WIRE(16, 0, 4, -ENOTSUP, 4); BAD_WIRE(16, 409599, 4, -ENOTSUP, 4);
    BAD_WIRE(16, 409601, 4, -ENOTSUP, 4); BAD_WIRE(16, UINT32_MAX, 4, -ENOTSUP, 4);
#undef BAD_WIRE
#define BAD_DESCRIPTOR(destination, offset, value) do { sdk_golden(wire, &d, 0); \
    put((destination) ? d.destination_bytes + (offset) : d.source_bytes + (offset), (value), 4); \
    reject_sdk(wire, 48, &d, -ENOTSUP, 4); } while (0)
    BAD_DESCRIPTOR(0, 0, 0x8400); BAD_DESCRIPTOR(0, 0, 0x3ff); BAD_DESCRIPTOR(0, 0, 0x10000);
    BAD_DESCRIPTOR(1, 0, 0x8002); BAD_DESCRIPTOR(1, 0, 0x402); BAD_DESCRIPTOR(1, 0, 0x8401);
    BAD_DESCRIPTOR(1, 0, 0x8405); BAD_DESCRIPTOR(1, 0, 0x18402);
    BAD_DESCRIPTOR(0, 4, 1); BAD_DESCRIPTOR(1, 4, 1);
#undef BAD_DESCRIPTOR
    const long failures[] = {7, -EFAULT, LONG_MIN, LONG_MAX};
    for (size_t i = 0; i < sizeof failures / sizeof *failures; ++i) {
        sdk_golden(wire, &d, 0); d.fail_at = 1; d.fail_result = failures[i];
        reject_sdk(wire, 48, &d, -EIO, 4);
    }
    for (unsigned int i = 3; i <= 4; ++i) {
        sdk_golden(wire, &d, 0); d.mutation_at = i; reject_sdk(wire, 48, &d, -ESTALE, 4);
    }
    printf("SDK48 goldens=3 reads_per_decode=4 rejected=%u exact48=1 stable_descriptors=1 output_unchanged=1 wire_unchanged=1 tail_preserved=1 callbacks=0\n",
        parser_rejections);
}
static void api40_test(void) {
    unsigned char wire[48], before[40];struct descriptor_memory d;
    unsigned char *api=malloc(40);assert(api);
    struct functional_face_api_request out,saved;
    for(unsigned int i=0;i<3;i++) {
        sdk_golden(wire,&d,i);memcpy(api,wire,40);memcpy(before,api,40);
        assert(!functional_face_transfer_decode_api40(api,40,descriptor_read,&d,&out));
        assert(d.reads==4 && out.input.source_handle==0x400u+i && out.input.destination_handle==0x8402u+i);
        assert(out.input.bytes==(i==0?409600u:i==1?51200u:53504u));
        assert(out.callback==0x12345678u && out.callback_context==0xabcdef00u);
        assert(out.source_descriptor==(uintptr_t)d.source_bytes && out.destination_descriptor==(uintptr_t)d.destination_bytes);
        assert(!memcmp(api,before,40));
    }
    memcpy(&saved,&out,sizeof saved);
    sdk_golden(wire,&d,0);memcpy(api,wire,40);
    assert(functional_face_transfer_decode_api40(api,39,descriptor_read,&d,&out)==-EINVAL && !d.reads);
    assert(!memcmp(&out,&saved,sizeof out));
    assert(functional_face_transfer_decode_api40(api,41,descriptor_read,&d,&out)==-EINVAL && !d.reads);
    assert(functional_face_transfer_decode_api40(NULL,40,descriptor_read,&d,&out)==-EINVAL && !d.reads);
    api[20]=2;assert(functional_face_transfer_decode_api40(api,40,descriptor_read,&d,&out)==-ENOTSUP && !d.reads);
    assert(!memcmp(&out,&saved,sizeof out));api[20]=1;memcpy(before,api,40);d.mutation_at=3;
    assert(functional_face_transfer_decode_api40(api,40,descriptor_read,&d,&out)==-ESTALE && d.reads==4);
    assert(!memcmp(&out,&saved,sizeof out) && !memcmp(api,before,40));
    free(api);puts("API40 goldens=3 exact_heap_extent=40 descriptor_double_reads=1 original_unchanged=1 no_result_or_padding=1 callbacks=0");
}
int main(int argc, char **argv) {
    assert(argc == 2); const char *mode = argv[1];
    if (!strcmp(mode, "positive")) positive_test();
    else if (!strcmp(mode, "repeat")) repeat_test();
    else if (!strcmp(mode, "sdk48")) sdk48_test();
    else if (!strcmp(mode, "api40")) api40_test();
    else if (!strcmp(mode, "init")) init_test();
    else if (!strcmp(mode, "binding")) binding_test();
    else if (!strcmp(mode, "acquire")) acquire_test();
    else if (!strcmp(mode, "malformed")) malformed_test();
    else if (!strcmp(mode, "disjoint")) disjoint_test();
    else if (!strcmp(mode, "source-read") || !strcmp(mode, "long-errors") || !strcmp(mode, "stale-source")) read_failure_test(mode);
    else if (!strcmp(mode, "destination-blocked")) destination_blocked_test();
    else if (!strcmp(mode, "stale-creator")) stale_creator_test();
    else if (!strcmp(mode, "partial")) partial_test();
    else if (!strcmp(mode, "reentry")) probe_test(1);
    else if (!strcmp(mode, "fork")) probe_test(2);
    else if (!strcmp(mode, "source-release")) source_release_test(0);
    else if (!strcmp(mode, "partial-source-release")) source_release_test(1);
    else if (!strcmp(mode, "destination-write-release")) destination_release_test(1);
    else if (!strcmp(mode, "destination-read-release")) destination_release_test(2);
    else abort();
    for (unsigned int i = 0; i < 128; ++i) if (messages[i]) destroy(messages[i]);
    printf("FACE_TRANSFER_PASS mode=%s\n", mode); return 0;
}
