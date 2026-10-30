/* SPDX-License-Identifier: MIT */
#define _GNU_SOURCE
#include <assert.h>
#include <inttypes.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/wait.h>
#include "dmm-service.h"
/* Test-only lock access for fork-under-held-mutex; actual DMM/registry linked. */
#include "functional-face-runtime.c"

#define OWNER UINT64_C(0xfacedead1001)
#define QUEUE UINT32_C(0x81cf1234)
struct message { unsigned int source, size, request; unsigned char wire[40]; };
static struct message *messages[128];
static struct full_imaging_io io;
static void *pending;
static unsigned int pending_queue, request_frees, reply_frees, sends, receives;
static int inline_receive, send_failure, request_failure, reply_failure, reenter, busy_probe;
static unsigned int records, callback_snapshots, model_busy_snapshots;
static uint64_t last_log_id;
static struct functional_face_runtime_ticket inline_ticket;
static struct functional_face_runtime_snapshot diagnostic;

/* Independent FINAL mode-zero request goldens, not the former all-op FF body. */
static const struct { unsigned int op; const char *hex; } request_goldens[] = {
    {0x20, "20000000d901000000000000ffffffff000000000000000000000000000000000000000000000000"},
    {0x21, "21000000d90100000284000000000000000000000000000000000000000000000000000000000000"},
    {0x23, "23000000000000000284000000000000000000003412000000000000000000000000000000000000"},
    {0x24, "240000000000000002840000ffffffff000000000000000000000000000000000000000000000000"},
    {0x25, "25000000000000000284000000000000000000000000000000000000000000000000000000000000"},
};
static void put(unsigned char *p, uint64_t value, unsigned int n) {
    for (unsigned int i = 0; i < n; ++i) p[i] = (unsigned char)(value >> (8 * i));
}
static uint64_t hash(const void *p, size_t n) {
    const unsigned char *s = p;
    uint64_t h = UINT64_C(14695981039346656037);
    for (size_t i = 0; i < n; ++i) h = (h ^ s[i]) * UINT64_C(1099511628211);
    return h;
}
static struct message *envelope(void *p) {
    return (struct message *)((unsigned char *)p - offsetof(struct message, wire));
}
static struct message *new_message(void) {
    struct message *m = malloc(sizeof *m); assert(m); memset(m, 0, sizeof *m);
    for (unsigned int i = 0; i < 128; ++i) if (!messages[i]) { messages[i] = m; return m; }
    abort();
}
static void destroy(struct message *m) {
    for (unsigned int i = 0; i < 128; ++i) if (messages[i] == m) { messages[i] = NULL; free(m); return; }
    abort();
}
static struct functional_face_runtime_caller caller(uint32_t unit) {
    return (struct functional_face_runtime_caller){OWNER, unit, FUNCTIONAL_FACE_RUNTIME_ACCEPTED,
        FUNCTIONAL_FACE_RUNTIME_UNIQUE_REFERENCE};
}
static struct message *request(unsigned int op, uint32_t unit, uint32_t handle) {
    struct message *m = new_message();
    m->source = QUEUE; m->size = 40; m->request = 1;
    unsigned int k = 0;
    while (k < sizeof request_goldens / sizeof *request_goldens && request_goldens[k].op != op) ++k;
    assert(k < sizeof request_goldens / sizeof *request_goldens);
    const char *hex = request_goldens[k].hex;
    assert(strlen(hex) == 80);
    for (unsigned int i = 0; i < 40; ++i) {
        unsigned int byte; assert(sscanf(hex + i * 2, "%2x", &byte) == 1); m->wire[i] = (unsigned char)byte;
    }
    if (op == 0x20 || op == 0x21) put(m->wire + 4, unit, 4);
    if (op != 0x20) put(m->wire + 8, handle, 4);
    if (op == 0x23) put(m->wire + 0x14, m->source & 0xffffu, 2);
    return m;
}
static void snapshot_callback(void) {
    if (!reenter) return;
    assert(!functional_face_runtime_snapshot(&diagnostic));
    ++callback_snapshots;
    assert(diagnostic.model_snapshot_result == 0 || diagnostic.model_snapshot_result == -EBUSY);
    if (diagnostic.model_snapshot_result == -EBUSY) ++model_busy_snapshots;
}
static void record(const char *prefix, const struct functional_face_runtime_snapshot *s) {
    assert(!strncmp(prefix, "FUNCTIONAL_FACE_DMM_", 20));
    assert(s->snapshot_id > last_log_id); last_log_id = s->snapshot_id; ++records;
    assert(s->producer_owner == OWNER && s->owner_pid == getpid());
    assert(!s->physical_verified && !s->original_cp_verified && !s->native_capture_verified);
    assert(io_equal(&s->io_identity, &io));
    if (reenter) {
        uint64_t id = s->snapshot_id;
        assert(!functional_face_runtime_snapshot(&diagnostic));
        assert(diagnostic.snapshot_id > id);
    }
}
static int allocate(unsigned int queue, void **out, unsigned int bytes, unsigned int wait) {
    assert(queue == QUEUE && bytes == 40 && wait == 1);
    snapshot_callback();
    if (busy_probe) {
        struct message *m = request(0x20, 0x1da, 0);
        struct functional_face_runtime_caller c = caller(0x1da);
        int result = 71;
        assert(functional_face_runtime_dispatch(FUNCTIONAL_FACE_DMM_CP, m->wire, &io, 1, &c, &result) == 1);
        assert(result == -EBUSY); destroy(m);
        m = request(0x20, 0x1da, 0); put(m->wire, 0x2a, 2); result = 71;
        assert(!functional_face_runtime_dispatch(FUNCTIONAL_FACE_DMM_CP, m->wire, &io, 1, &c, &result) && result == 71);
        destroy(m);
    }
    struct message *m = new_message(); m->size = bytes; *out = m->wire; return 0;
}
static int release(unsigned int queue, void *p) {
    struct message *m = envelope(p);
    snapshot_callback();
    assert(queue == (m->request ? FUNCTIONAL_FACE_DMM_CP : QUEUE));
    if (m->request && request_failure) return -73;
    if (!m->request && reply_failure) return -74;
    if (m->request) ++request_frees; else ++reply_frees;
    if (pending == p) pending = NULL;
    destroy(m); return 0;
}
static int other_release(unsigned int queue, void *p) { return release(queue, p); }
static unsigned int size(void *p) { snapshot_callback(); return envelope(p)->size; }
static unsigned int source(void *p) { snapshot_callback(); return envelope(p)->source; }
static void set_source(void *p, unsigned int src) { snapshot_callback(); envelope(p)->source = src; }
static int original_receive(unsigned int queue, void **out) {
    assert(queue == pending_queue && pending && out);
    ++receives; *out = pending; return 0;
}
static int send(unsigned int queue, void *p) {
    snapshot_callback();
    assert(!pending && queue == QUEUE && envelope(p)->source == FUNCTIONAL_FACE_DMM_CP);
    pending = p; pending_queue = queue; ++sends;
    if (inline_receive) {
        assert(!functional_face_runtime_snapshot(&diagnostic));
        uint64_t before_commit = diagnostic.ledger_commit;
        uint32_t before_creators = diagnostic.live_creators;
        void *actual = NULL; int received = original_receive(queue, &actual);
        assert(functional_face_runtime_observe(OWNER, queue, actual, received, &inline_ticket) == 1);
        assert(inline_ticket.actual.reply == (uintptr_t)p && inline_ticket.actual.nonce);
        struct functional_face_dmm_descriptor d;
        assert(functional_face_runtime_lookup_creator(OWNER, 0x1d9, &d) == -EBUSY);
        assert(!functional_face_runtime_snapshot(&diagnostic));
        assert(diagnostic.live_creators == before_creators && diagnostic.ledger_commit == before_commit);
        int rc = 61;
        assert(functional_face_runtime_release(OWNER, queue, p, &inline_ticket, release, &rc) == 1 && !rc);
        assert(!functional_face_runtime_snapshot(&diagnostic));
        assert(diagnostic.live_creators == before_creators && diagnostic.ledger_commit == before_commit);
    }
    return send_failure ? -77 : 0;
}
static void setup(void) {
    io = (struct full_imaging_io){allocate, release, set_source, send, size, source, NULL};
    assert(!functional_face_runtime_prepare(1, OWNER, &io, record));
    assert(!functional_face_runtime_prepare(1, OWNER, &io, record));
}
static int dispatch_request(struct message *m, struct functional_face_runtime_caller c) {
    int result = 91;
    assert(functional_face_runtime_dispatch(FUNCTIONAL_FACE_DMM_CP, m->wire, &io, 1, &c, &result) == 1);
    return result;
}
static void queue_request(unsigned int op, uint32_t unit, uint32_t handle,
                          enum functional_face_runtime_reference_kind kind) {
    struct functional_face_runtime_caller c = caller(unit); c.close_kind = kind;
    assert(!dispatch_request(request(op, unit, handle), c));
    assert(pending && pending_queue == QUEUE);
}
static struct functional_face_runtime_ticket observe(void) {
    void *p = NULL;
    struct functional_face_runtime_ticket t;
    int rc = original_receive(QUEUE, &p);
    assert(functional_face_runtime_observe(OWNER, QUEUE, p, rc, &t) == 1);
    assert(t.producer_owner == OWNER && t.sender_tid == THREAD_ID() && t.transaction && t.actual.nonce);
    assert(t.request_source == QUEUE && t.actual.destination == QUEUE && t.actual.reply == (uintptr_t)p);
    assert(hash(t.actual.wire, 40) == hash(p, 40));
    return t;
}
static void release_ticket(const struct functional_face_runtime_ticket *t) {
    int rc = 43;
    assert(functional_face_runtime_release(OWNER, QUEUE, pending, t, release, &rc) == 1 && !rc);
    assert(!pending);
}
static struct functional_face_runtime_ticket operation(unsigned int op, uint32_t unit, uint32_t handle,
    enum functional_face_runtime_reference_kind kind, int expected_status) {
    queue_request(op, unit, handle, kind);
    struct functional_face_runtime_ticket t = observe();
    assert(get(t.actual.wire, 2) == (op | 0x8000u));
    assert((int16_t)get(t.actual.wire + 2, 2) == expected_status);
    assert(get(t.actual.wire + 6, 2) == (op == 0x23 ? QUEUE & 0xffffu : 0));
    unsigned char expected[40] = {0};
    put(expected, op | 0x8000u, 2);
    put(expected + 2, (unsigned int)expected_status, 2);
    put(expected + 6, op == 0x23 ? QUEUE & 0xffffu : 0, 2);
    put(expected + 10, (unsigned int)expected_status, 2);
    put(expected + 12, expected_status ? (op == 0x20 ? UINT32_MAX : handle) : t.actual.span.handle, 4);
    if (!expected_status && op == 0x20) put(expected + 16, unit, 4);
    if (!expected_status && (op == 0x21 || op == 0x24)) {
        put(expected + 8, 1, 2); put(expected + 24, t.actual.span.logical, 8);
        put(expected + 32, t.actual.span.bytes, 4);
    }
    assert(!memcmp(expected, t.actual.wire, 40) && hash(expected, 40) == hash(t.actual.wire, 40));
    release_ticket(&t); return t;
}
static struct functional_face_dmm_descriptor create(uint32_t unit) {
    struct functional_face_runtime_ticket t = operation(0x20, unit, 0, 0, 0);
    struct functional_face_dmm_descriptor d;
    assert(!functional_face_runtime_lookup_creator(OWNER, unit, &d));
    assert(same_span(&d, &t.actual.span) && !d.reference);
    assert(!functional_face_runtime_snapshot(&diagnostic));
    assert(!memcmp(&diagnostic.units[unit - 0x1d9].receipt, &t, sizeof t));
    return d;
}
static void reject(struct message *m, struct functional_face_runtime_caller c, int error) {
    struct message before = *m;
    unsigned int old_sends = sends, old_requests = request_frees, old_replies = reply_frees;
    assert(dispatch_request(m, c) == error);
    assert(!memcmp(m, &before, sizeof *m));
    assert(sends == old_sends && request_frees == old_requests && reply_frees == old_replies);
    destroy(m);
}
static void units_test(void) {
    struct dmm_service speech = {.physical = DMM_TEST_PHYSICAL};
    speech.memory = malloc(DMM_TEST_SIZE); assert(speech.memory);
    unsigned char q[40] = {0x20}, r[40]; put(q + 4, 0x63a, 4); put(q + 22, 1, 2);
    for (unsigned int i = 0; i < 2; ++i) {
        assert(!dmm_service_reply(&speech, q, 40, r));
        speech.slots[i].creator_kind = DMM_CREATOR_SPEECH_INITIAL;
        assert(speech.slots[i].handle == 0x8400u + i && speech.slots[i].open_count == 1);
    }
    for (size_t i = 0; i < DMM_TEST_SIZE; ++i) speech.memory[i] = (unsigned char)(i ^ (i >> 9) ^ 0x95);
    struct dmm_service saved; memcpy(&saved, &speech, sizeof saved);
    unsigned char *saved_bytes = malloc(DMM_TEST_SIZE); assert(saved_bytes);
    memcpy(saved_bytes, speech.memory, DMM_TEST_SIZE);
    setup();
    uint64_t verified_write = 0, verified_read = 0;
    for (uint32_t i = 0; i < 3; ++i) {
        uint32_t unit = 0x1d9 + i;
        struct functional_face_dmm_descriptor d = create(unit);
        assert(d.owner == OWNER && d.handle == 0x8402u + i && d.epoch == i + 1);
        assert(d.bytes == (i == 0 ? 409600u : i == 1 ? 51200u : 53504u));
        assert(d.logical == FUNCTIONAL_FACE_REGISTRY_IOVA + i * FUNCTIONAL_FACE_REGISTRY_WINDOW);
        struct functional_face_runtime_ticket opened = operation(0x24, unit, d.handle, 0, 0);
        struct functional_face_runtime_ticket shared = operation(0x21, unit, d.handle, 0, 0);
        assert(opened.actual.span.reference && shared.actual.span.reference &&
            opened.actual.span.reference != shared.actual.span.reference);
        assert(!functional_face_runtime_snapshot(&diagnostic));
        const struct functional_face_runtime_unit *u = &diagnostic.units[i];
        assert(u->references[0].kind == 0x24 && u->references[1].kind == 0x21 &&
            u->references[0].sender_tid == THREAD_ID() && u->references[1].sender_tid == THREAD_ID());
        (void)operation(0x25, unit, d.handle, FUNCTIONAL_FACE_RUNTIME_OPEN, 0);
        (void)operation(0x25, unit, d.handle, FUNCTIONAL_FACE_RUNTIME_SHARE, 0);
        unsigned char *pattern = malloc(d.bytes), *copy = malloc(d.bytes); assert(pattern && copy);
        for (size_t j = 0; j < d.bytes; ++j) pattern[j] = (unsigned char)((j * 29 + i * 97 + 23) ^ (j >> 7));
        struct functional_face_dmm_borrow writer, reader;
        struct functional_face_dmm_readback result;
        assert(!functional_face_runtime_borrow_destination(OWNER, unit, d.handle, &d, 0, d.bytes,
            FUNCTIONAL_FACE_DMM_WRITE | FUNCTIONAL_FACE_DMM_TRANSFER, &writer));
        assert(!functional_face_dmm_write(&writer, 0, pattern, d.bytes, &result));
        assert(result.verified_bytes == d.bytes && result.after_digest == hash(pattern, d.bytes));
        assert(!functional_face_dmm_release_borrow(&writer, &result) && result.verified_bytes == d.bytes);
        assert(!functional_face_runtime_borrow_destination(OWNER, unit, d.handle, &d, 0, d.bytes,
            FUNCTIONAL_FACE_DMM_READ, &reader));
        assert(!functional_face_dmm_read(&reader, 0, copy, d.bytes, &result));
        assert(result.verified_bytes == d.bytes && !memcmp(pattern, copy, d.bytes));
        (void)operation(0x23, unit, d.handle, 0, -1);
        assert(!functional_face_runtime_snapshot(&diagnostic));
        assert(diagnostic.units[i].live_creator && !diagnostic.units[i].retired);
        assert(diagnostic.model.units[i].borrows == 1 && diagnostic.model.units[i].allocated);
        assert(!functional_face_dmm_release_borrow(&reader, &result));
        assert(!functional_face_runtime_snapshot(&diagnostic) && !diagnostic.model_snapshot_result);
        verified_write += diagnostic.model.units[i].verified_write_bytes;
        verified_read += diagnostic.model.units[i].verified_read_bytes;
        printf("BYTES unit=%x bytes=%zu digest=%016" PRIx64 "\n", unit, d.bytes, hash(copy, d.bytes));
        (void)operation(0x23, unit, d.handle, 0, 0);
        assert(!functional_face_runtime_snapshot(&diagnostic));
        assert(!diagnostic.units[i].live_creator && diagnostic.units[i].retired &&
            diagnostic.units[i].retirement.actual.span.epoch == d.epoch);
        assert(!diagnostic.model.units[i].allocated && !diagnostic.model.units[i].span.host_view);
        reject(request(0x20, unit, 0), caller(unit), -ESTALE);
        free(pattern); free(copy);
    }
    assert(!functional_face_runtime_snapshot(&diagnostic) && !diagnostic.model_snapshot_result);
    assert(verified_write == 514304 && verified_read == 514304);
    assert(!diagnostic.live_creators && !diagnostic.opens && !diagnostic.shares && !diagnostic.tickets &&
        !diagnostic.retained && !diagnostic.faults && diagnostic.ledger_commit == 18);
    assert(diagnostic.actual_receive == 21 && diagnostic.actual_request_free == 21 && diagnostic.actual_reply_free == 21);
    assert(diagnostic.model.queued == 21 && diagnostic.model.ap_consumed == 18);
    assert(request_frees == 21 && reply_frees == 21 && sends == 21 && receives == 21);
    assert(!memcmp(&speech, &saved, sizeof speech) && !memcmp(speech.memory, saved_bytes, DMM_TEST_SIZE));
    assert(!functional_face_dmm_shutdown());
    free(saved_bytes); free(speech.memory);
    puts("COUNTS units=3 write=514304 read=514304 actual_receive=21 request_free=21 reply_free=21 ledger_commit=18 speech_unchanged=1");
}
static void queued_test(void) {
    setup(); queue_request(0x20, 0x1d9, 0, 0);
    struct functional_face_dmm_descriptor d, unchanged; memset(&d, 0xa5, sizeof d); unchanged = d;
    assert(functional_face_runtime_lookup_creator(OWNER, 0x1d9, &d) == -ENODATA && !memcmp(&d, &unchanged, sizeof d));
    assert(!functional_face_runtime_snapshot(&diagnostic));
    assert(diagnostic.model.units[0].allocated && !diagnostic.live_creators && !diagnostic.ledger_commit);
    reject(request(0x24, 0x1d9, 0x8402), caller(0x1d9), -ENODATA);
    struct functional_face_runtime_ticket t = observe();
    assert(functional_face_runtime_lookup_creator(OWNER, 0x1d9, &d) == -ENODATA);
    assert(!functional_face_runtime_snapshot(&diagnostic) && diagnostic.tickets == 1 && !diagnostic.ledger_commit);
    release_ticket(&t);
    assert(!functional_face_runtime_lookup_creator(OWNER, 0x1d9, &d));
    assert(same_span(&d, &t.actual.span));
    (void)operation(0x23, 0x1d9, d.handle, 0, 0);
}
static void ticket_test(const char *mode) {
    setup(); queue_request(0x20, 0x1d9, 0, 0);
    int rc = 55;
    struct functional_face_runtime_ticket t, untouched; memset(&t, 0xa9, sizeof t); untouched = t;
    if (!strcmp(mode, "receive-failure")) {
        assert(functional_face_runtime_observe(OWNER, QUEUE, pending, -91, &t) == -EIO);
        assert(!memcmp(&t, &untouched, sizeof t));
        assert(!functional_face_runtime_snapshot(&diagnostic) && !diagnostic.actual_receive && !diagnostic.ledger_commit);
    }
    assert(functional_face_runtime_release(OWNER, QUEUE, pending, NULL, release, &rc) == 1 && rc == -ESTALE);
    assert(!reply_frees);
    assert(functional_face_runtime_observe(OWNER + 1, QUEUE, pending, 0, &t) == -EPERM);
    assert(!memcmp(&t, &untouched, sizeof t));
    assert(functional_face_runtime_observe(OWNER, QUEUE + 1, pending, 0, &t) == -ESTALE);
    if (!strcmp(mode, "reply-source")) {
        envelope(pending)->source ^= 1;
        assert(functional_face_runtime_observe(OWNER, QUEUE, pending, 0, &t) == -EPROTO);
        assert(!memcmp(&t, &untouched, sizeof t));
        envelope(pending)->source = FUNCTIONAL_FACE_DMM_CP;
    }
    if (!strcmp(mode, "reply-wire")) {
        ((unsigned char *)pending)[35] ^= 1;
        assert(functional_face_runtime_observe(OWNER, QUEUE, pending, 0, &t) == -EPROTO);
        assert(!memcmp(&t, &untouched, sizeof t)); ((unsigned char *)pending)[35] ^= 1;
    }
    t = observe();
    struct functional_face_runtime_ticket bad = t;
#define BAD_TICKET(field, value) do { bad = t; bad.field = (value); \
    assert(functional_face_runtime_release(OWNER, QUEUE, pending, &bad, release, &rc) == 1 && rc == -ESTALE); } while (0)
    BAD_TICKET(actual.nonce, t.actual.nonce + 1); BAD_TICKET(actual.span.epoch, t.actual.span.epoch + 1);
    BAD_TICKET(actual.span.owner, OWNER + 1); BAD_TICKET(sender_tid, t.sender_tid + 1);
    BAD_TICKET(request_source, QUEUE + 1); BAD_TICKET(producer_owner, OWNER + 1);
    BAD_TICKET(op, 0x24); BAD_TICKET(actual.destination, QUEUE + 1); BAD_TICKET(actual.reply, t.actual.reply + 1);
#undef BAD_TICKET
    assert(functional_face_runtime_release(OWNER, QUEUE + 1, pending, &t, release, &rc) == 1 && rc == -ESTALE);
    assert(functional_face_runtime_release(OWNER + 1, QUEUE, pending, &t, release, &rc) == 1 && rc == -EPERM);
    assert(functional_face_runtime_release(OWNER, QUEUE, pending, &t, other_release, &rc) == 1 && rc == -ESTALE);
    assert(!reply_frees);
    release_ticket(&t);
    struct functional_face_dmm_descriptor d; assert(!functional_face_runtime_lookup_creator(OWNER, 0x1d9, &d));
    (void)operation(0x23, 0x1d9, d.handle, 0, 0);
}
static void failure_test(const char *mode) {
    setup();
    if (!strcmp(mode, "request-free-failure")) request_failure = 1;
    if (!strcmp(mode, "reply-free-failure")) reply_failure = 1;
    if (!strcmp(mode, "send-failure") || !strcmp(mode, "send-after-inline")) send_failure = 1;
    if (!strcmp(mode, "send-after-inline")) inline_receive = 1;
    struct message *m = request(0x20, 0x1d9, 0);
    int rc = dispatch_request(m, caller(0x1d9));
    if (!strcmp(mode, "send-failure")) {
        assert(rc == -77 && !pending && !request_frees && reply_frees == 1);
        assert(!functional_face_runtime_snapshot(&diagnostic));
        assert(!diagnostic.faults && !diagnostic.live_creators && !diagnostic.model.units[0].span.host_view);
        destroy(m); send_failure = 0;
        struct functional_face_dmm_descriptor d = create(0x1d9);
        (void)operation(0x23, 0x1d9, d.handle, 0, 0); return;
    }
    if (reply_failure) {
        assert(!rc && pending);
        struct functional_face_runtime_ticket t = observe();
        assert(functional_face_runtime_release(OWNER, QUEUE, pending, &t, release, &rc) == 1 && rc == -74);
        assert(!reply_frees);
        reply_failure = 0;
        assert(functional_face_runtime_release(OWNER, QUEUE, pending, &t, release, &rc) == 1 && rc == -EIO);
        assert(!reply_frees);
    } else assert(rc == (inline_receive ? -77 : -EIO));
    assert(!functional_face_runtime_snapshot(&diagnostic) && !diagnostic.model_snapshot_result);
    assert(diagnostic.faults && diagnostic.retained == 1 && !diagnostic.live_creators && !diagnostic.ledger_commit);
    assert(diagnostic.model.faults && diagnostic.model.units[0].span.host_view);
    if (inline_receive) {
        assert(diagnostic.actual_receive == 1 && diagnostic.actual_reply_free == 1 && !diagnostic.actual_request_free);
        assert(diagnostic.transactions[0].dispatch_result == -77 && diagnostic.transactions[0].observed);
    }
    if (request_failure) {
        assert(diagnostic.transactions[0].request_free_result == -73 && diagnostic.model.live_requests);
        request_failure = 0;
        assert(functional_face_runtime_release(OWNER, FUNCTIONAL_FACE_DMM_CP, m->wire, NULL, release, &rc) == 1 && rc == -EIO);
        assert(!request_frees);
    }
    struct message *unrelated = request(0x20, 0x1da, 0); put(unrelated->wire, 0x2a, 2);
    struct functional_face_runtime_caller c = caller(0x1da);
    int unchanged = 81;
    assert(!functional_face_runtime_dispatch(FUNCTIONAL_FACE_DMM_CP, unrelated->wire, &io, 1, &c, &unchanged) && unchanged == 81);
    destroy(unrelated);
    reject(request(0x20, 0x1da, 0), caller(0x1da), -EIO);
    struct functional_face_dmm_descriptor d;
    assert(functional_face_runtime_lookup_creator(OWNER, 0x1d9, &d) == -EIO);
}
static void inline_test(void) {
    setup(); inline_receive = 1;
    assert(!dispatch_request(request(0x20, 0x1d9, 0), caller(0x1d9)) && !pending);
    struct functional_face_dmm_descriptor d;
    assert(!functional_face_runtime_lookup_creator(OWNER, 0x1d9, &d) && same_span(&d, &inline_ticket.actual.span));
    assert(!functional_face_runtime_snapshot(&diagnostic));
    assert(diagnostic.live_creators == 1 && diagnostic.ledger_commit == 1 && !diagnostic.faults && !diagnostic.tickets);
    inline_receive = 0; (void)operation(0x23, 0x1d9, d.handle, 0, 0);
}
static void delayed_test(const char *mode) {
    setup(); struct functional_face_dmm_descriptor d = create(0x1d9);
    unsigned int op = !strcmp(mode, "open-queued") ? 0x24 : !strcmp(mode, "share-queued") ? 0x21 :
        !strcmp(mode, "close-queued") ? 0x25 : 0x23;
    if (op == 0x25) (void)operation(0x24, d.unit, d.handle, 0, 0);
    assert(!functional_face_runtime_snapshot(&diagnostic));
    uint64_t commits = diagnostic.ledger_commit;
    uint32_t opens = diagnostic.opens, shares = diagnostic.shares;
    queue_request(op, d.unit, d.handle, 0);
    assert(!functional_face_runtime_snapshot(&diagnostic));
    assert(diagnostic.ledger_commit == commits && diagnostic.opens == opens && diagnostic.shares == shares &&
        diagnostic.live_creators == 1);
    struct functional_face_runtime_ticket t = observe();
    assert(!functional_face_runtime_snapshot(&diagnostic) && diagnostic.ledger_commit == commits &&
        diagnostic.opens == opens && diagnostic.shares == shares && diagnostic.live_creators == 1);
    release_ticket(&t);
    assert(!functional_face_runtime_snapshot(&diagnostic) && diagnostic.ledger_commit == commits + 1);
    if (op == 0x24 || op == 0x21) (void)operation(0x25, d.unit, d.handle, 0, 0);
    if (op != 0x23) (void)operation(0x23, d.unit, d.handle, 0, 0);
}
static void inline_operations_test(void) {
    setup(); struct functional_face_dmm_descriptor d = create(0x1d9);
    const unsigned int ops[] = {0x24, 0x21, 0x25, 0x25, 0x23};
    inline_receive = 1;
    for (unsigned int i = 0; i < sizeof ops / sizeof *ops; ++i) {
        struct functional_face_runtime_caller c = caller(d.unit);
        if (i == 2) c.close_kind = FUNCTIONAL_FACE_RUNTIME_OPEN;
        assert(!dispatch_request(request(ops[i], d.unit, d.handle), c) && !pending);
    }
    assert(!functional_face_runtime_snapshot(&diagnostic));
    assert(!diagnostic.live_creators && !diagnostic.opens && !diagnostic.shares && diagnostic.ledger_commit == 6 &&
        diagnostic.actual_receive == 6 && diagnostic.actual_request_free == 6 && diagnostic.actual_reply_free == 6);
}
static void metadata_test(void) {
    setup();
    assert(functional_face_runtime_prepare(0, OWNER, &io, record) == -ENODEV);
    assert(functional_face_runtime_prepare(1, 0, &io, record) == -EINVAL);
    assert(functional_face_runtime_prepare(1, OWNER + 1, &io, record) == -EPERM);
    struct functional_face_runtime_caller c = caller(0x1d9);
    struct message *m = request(0x20, 0x1d9, 0), before = *m;
    int rc = 71;
    c.trust = FUNCTIONAL_FACE_RUNTIME_UNTRUSTED;
    assert(!functional_face_runtime_dispatch(FUNCTIONAL_FACE_DMM_CP, m->wire, &io, 1, &c, &rc) && rc == 71);
    c.trust = FUNCTIONAL_FACE_RUNTIME_ACCEPTED;
    assert(!functional_face_runtime_dispatch(FUNCTIONAL_FACE_DMM_CP, m->wire, &io, 0, &c, &rc) && rc == 71);
    assert(!functional_face_runtime_dispatch(0x0061003c, m->wire, &io, 1, &c, &rc) && rc == 71);
    put(m->wire, 0x2a, 2);
    assert(!functional_face_runtime_dispatch(FUNCTIONAL_FACE_DMM_CP, m->wire, &io, 1, &c, &rc) && rc == 71);
    *m = before; c.trust = FUNCTIONAL_FACE_RUNTIME_REJECTED; reject(m, c, -EPROTO);
    c = caller(0x1d9); c.producer_owner++;
    reject(request(0x20, 0x1d9, 0), c, -EPERM);
    c = caller(0x1da); reject(request(0x20, 0x1d9, 0), c, -EPROTO);
    m = request(0x20, 0x1d9, 0); m->size = 39; reject(m, caller(0x1d9), -EMSGSIZE);
    m = request(0x20, 0x1d9, 0); m->source = 0x02821234; reject(m, caller(0x1d9), -EPROTO);
    struct full_imaging_io other = io; other.release = other_release;
    m = request(0x20, 0x1d9, 0); c = caller(0x1d9);
    assert(functional_face_runtime_dispatch(FUNCTIONAL_FACE_DMM_CP, m->wire, &other, 1, &c, &rc) == 1 && rc == -EPERM);
    destroy(m);
    struct functional_face_dmm_descriptor d = create(0x1d9);
    reject(request(0x24, 0x1d9, d.handle ^ 1), caller(0x1d9), -ESTALE);
    reject(request(0x21, 0x1da, d.handle), caller(0x1da), -ENODATA);
    struct functional_face_dmm_borrow b, untouched; memset(&b, 0xa7, sizeof b); untouched = b;
    struct functional_face_dmm_descriptor bad = d;
#define BAD_SPAN(field, value) do { bad = d; bad.field = (value); \
    assert(functional_face_runtime_borrow_destination(OWNER, d.unit, d.handle, &bad, 0, 1, 1, &b) == -ESTALE); \
    assert(!memcmp(&b, &untouched, sizeof b)); } while (0)
    BAD_SPAN(epoch, d.epoch + 1); BAD_SPAN(owner, OWNER + 1); BAD_SPAN(domain, 0);
    BAD_SPAN(registration, d.registration + 1); BAD_SPAN(host_view, d.host_view + 1);
    BAD_SPAN(logical, d.logical + 1); BAD_SPAN(bytes, d.bytes - 1); BAD_SPAN(reference, 1);
#undef BAD_SPAN
    assert(functional_face_runtime_borrow_destination(OWNER + 1, d.unit, d.handle, &d, 0, 1, 1, &b) == -EPERM);
    assert(functional_face_runtime_borrow_destination(OWNER, 0x1da, d.handle, &d, 0, 1, 1, &b) == -ENODATA);
    assert(functional_face_runtime_borrow_destination(OWNER, d.unit, d.handle + 1, &d, 0, 1, 1, &b) == -ESTALE);
    (void)operation(0x23, d.unit, d.handle, 0, 0);
    assert(functional_face_runtime_borrow_destination(OWNER, d.unit, d.handle, &d, 0, 1, 1, &b) == -ENODATA);
    reject(request(0x20, d.unit, 0), caller(d.unit), -ESTALE);
}
static void ambiguity_test(void) {
    setup(); struct functional_face_dmm_descriptor d = create(0x1d9);
    (void)operation(0x24, d.unit, d.handle, 0, 0);
    (void)operation(0x21, d.unit, d.handle, 0, 0);
    reject(request(0x25, d.unit, d.handle), caller(d.unit), -ENODATA);
    (void)operation(0x25, d.unit, d.handle, FUNCTIONAL_FACE_RUNTIME_OPEN, 0);
    (void)operation(0x25, d.unit, d.handle, 0, 0);
    (void)operation(0x24, d.unit, d.handle, 0, 0);
    (void)operation(0x24, d.unit, d.handle, 0, 0);
    struct functional_face_runtime_caller c = caller(d.unit); c.close_kind = FUNCTIONAL_FACE_RUNTIME_OPEN;
    reject(request(0x25, d.unit, d.handle), c, -ENODATA);
    assert(!functional_face_runtime_snapshot(&diagnostic));
    assert(diagnostic.opens == 2 && !diagnostic.shares && diagnostic.model.units[0].opens == 2);
}
static pthread_mutex_t rendezvous = PTHREAD_MUTEX_INITIALIZER;
static pthread_cond_t condition = PTHREAD_COND_INITIALIZER;
static int stage;
static struct functional_face_dmm_descriptor thread_creator;
static void *open_thread(void *unused) {
    (void)unused;
    (void)operation(0x24, thread_creator.unit, thread_creator.handle, 0, 0);
    reject(request(0x23, thread_creator.unit, thread_creator.handle), caller(thread_creator.unit), -EPERM);
    assert(!pthread_mutex_lock(&rendezvous)); stage = 1; assert(!pthread_cond_signal(&condition));
    while (stage != 2) assert(!pthread_cond_wait(&condition, &rendezvous));
    assert(!pthread_mutex_unlock(&rendezvous));
    (void)operation(0x25, thread_creator.unit, thread_creator.handle, 0, 0);
    return NULL;
}
static void threads_test(void) {
    setup(); thread_creator = create(0x1d9);
    pthread_t thread; assert(!pthread_create(&thread, NULL, open_thread, NULL));
    assert(!pthread_mutex_lock(&rendezvous));
    while (stage != 1) assert(!pthread_cond_wait(&condition, &rendezvous));
    reject(request(0x25, thread_creator.unit, thread_creator.handle), caller(thread_creator.unit), -ENODATA);
    (void)operation(0x23, thread_creator.unit, thread_creator.handle, 0, -1);
    stage = 2; assert(!pthread_cond_signal(&condition)); assert(!pthread_mutex_unlock(&rendezvous));
    assert(!pthread_join(thread, NULL));
    (void)operation(0x23, thread_creator.unit, thread_creator.handle, 0, 0);
}
static void *wrong_tid(void *unused) {
    (void)unused;
    struct functional_face_runtime_ticket t;
    assert(functional_face_runtime_observe(OWNER, QUEUE, pending, 0, &t) == -ESTALE);
    int rc = 91;
    assert(functional_face_runtime_release(OWNER, QUEUE, pending, &inline_ticket, release, &rc) == 1 && rc == -ESTALE);
    return NULL;
}
static void tid_test(void) {
    setup(); queue_request(0x20, 0x1d9, 0, 0);
    pthread_t thread; assert(!pthread_create(&thread, NULL, wrong_tid, NULL)); assert(!pthread_join(thread, NULL));
    inline_ticket = observe();
    assert(!pthread_create(&thread, NULL, wrong_tid, NULL)); assert(!pthread_join(thread, NULL));
    release_ticket(&inline_ticket);
    struct functional_face_dmm_descriptor d;
    assert(!functional_face_runtime_lookup_creator(OWNER, 0x1d9, &d));
    (void)operation(0x23, d.unit, d.handle, 0, 0);
}
static void fork_test(void) {
    setup(); struct functional_face_dmm_descriptor d = create(0x1d9);
    struct functional_face_runtime_caller c = caller(d.unit);
    struct message *m = request(0x24, d.unit, d.handle);
    assert(!pthread_mutex_lock(&runtime_mutex));
    pid_t child = fork(); assert(child >= 0);
    if (!child) {
        alarm(3);
        struct functional_face_runtime_snapshot *s = malloc(sizeof *s); assert(s);
        struct functional_face_dmm_borrow b;
        struct functional_face_runtime_ticket t;
        int rc = 71;
        assert(functional_face_runtime_prepare(1, OWNER, &io, record) == -ECHILD);
        assert(functional_face_runtime_dispatch(FUNCTIONAL_FACE_DMM_CP, m->wire, &io, 1, &c, &rc) == 1 && rc == -ECHILD);
        assert(functional_face_runtime_snapshot(s) == -ECHILD);
        assert(functional_face_runtime_lookup_creator(OWNER, d.unit, &d) == -ECHILD);
        assert(functional_face_runtime_borrow_destination(OWNER, d.unit, d.handle, &d, 0, 1, 1, &b) == -ECHILD);
        assert(functional_face_runtime_observe(OWNER, QUEUE, m->wire, 0, &t) == -ECHILD);
        assert(functional_face_runtime_release(OWNER, QUEUE, m->wire, &t, release, &rc) == 1 && rc == -ECHILD);
        free(s); _exit(0);
    }
    int status; assert(waitpid(child, &status, 0) == child && WIFEXITED(status) && WEXITSTATUS(status) == 0);
    assert(!pthread_mutex_unlock(&runtime_mutex)); destroy(m);
    (void)operation(0x23, d.unit, d.handle, 0, 0);
}
static void pointer_test(void) {
    setup(); queue_request(0x20, 0x1d9, 0, 0);
    struct functional_face_runtime_ticket old = observe();
    uintptr_t retired = (uintptr_t)pending; release_ticket(&old);
    /* Tests disable ASan quarantine for this mode so real malloc/free reuse
     * the retired reply address for a fresh, unrelated 40-byte message. */
    struct message *fresh = new_message(); fresh->size = 40; fresh->source = 0x81234567;
    assert((uintptr_t)fresh->wire == retired);
    struct functional_face_runtime_ticket t; memset(&t, 0xa1, sizeof t);
    struct functional_face_runtime_ticket unchanged = t;
    assert(!functional_face_runtime_observe(OWNER, QUEUE, fresh->wire, 0, &t));
    assert(!memcmp(&t, &unchanged, sizeof t));
    int rc = 72;
    assert(!functional_face_runtime_release(OWNER, QUEUE, fresh->wire, &old, release, &rc) && rc == 72);
    destroy(fresh);
    puts("POINTER real_malloc_reuse=1 fresh_message_unclaimed=1");
    struct functional_face_dmm_descriptor d;
    assert(!functional_face_runtime_lookup_creator(OWNER, 0x1d9, &d));
    (void)operation(0x23, d.unit, d.handle, 0, 0);
}
static void reentry_test(void) {
    reenter = busy_probe = 1; setup();
    struct functional_face_dmm_descriptor d = create(0x1d9);
    (void)operation(0x23, d.unit, d.handle, 0, 0);
    assert(records >= 7 && callback_snapshots > 10 && model_busy_snapshots > 10);
    printf("REENTRY logs=%u callback_snapshots=%u real_model_busy=%u\n", records, callback_snapshots, model_busy_snapshots);
}
static void wire_test(void) {
    setup(); struct functional_face_dmm_descriptor d = create(0x1d9);
    unsigned int mutations = 0;
    for (unsigned int k = 0; k < sizeof request_goldens / sizeof *request_goldens; ++k) {
        unsigned int op = request_goldens[k].op;
        for (unsigned int byte = 2; byte < 40; ++byte) {
            if (byte >= 4 && byte < 12) continue;
            struct message *m = request(op, d.unit, d.handle), saved;
            m->wire[byte] ^= 1; saved = *m;
            unsigned int old_sends = sends;
            int rc = dispatch_request(m, caller(d.unit));
            assert(rc < 0 && sends == old_sends && !memcmp(m, &saved, sizeof *m));
            destroy(m); ++mutations;
        }
    }
    (void)operation(0x23, d.unit, d.handle, 0, 0);
    printf("WIRE fixed_mutations=%u exact40=1 free_source_low16=1\n", mutations);
}
int main(int argc, char **argv) {
    assert(argc == 2);
    const char *mode = argv[1];
    if (!strcmp(mode, "units")) units_test();
    else if (!strcmp(mode, "queued")) queued_test();
    else if (!strcmp(mode, "ticket") || !strcmp(mode, "receive-failure") ||
             !strcmp(mode, "reply-source") || !strcmp(mode, "reply-wire")) ticket_test(mode);
    else if (!strcmp(mode, "request-free-failure") || !strcmp(mode, "reply-free-failure") ||
             !strcmp(mode, "send-failure") || !strcmp(mode, "send-after-inline")) failure_test(mode);
    else if (!strcmp(mode, "inline")) inline_test();
    else if (!strcmp(mode, "inline-operations")) inline_operations_test();
    else if (!strcmp(mode, "open-queued") || !strcmp(mode, "share-queued") ||
             !strcmp(mode, "close-queued") || !strcmp(mode, "free-queued")) delayed_test(mode);
    else if (!strcmp(mode, "metadata")) metadata_test();
    else if (!strcmp(mode, "ambiguity")) ambiguity_test();
    else if (!strcmp(mode, "threads")) threads_test();
    else if (!strcmp(mode, "tid")) tid_test();
    else if (!strcmp(mode, "fork")) fork_test();
    else if (!strcmp(mode, "pointer")) pointer_test();
    else if (!strcmp(mode, "reentry")) reentry_test();
    else if (!strcmp(mode, "wire")) wire_test();
    else abort();
    /* Fault tests deliberately preserve the modeled lease; process teardown
     * reclaims backing. Free fake transport allocations only after assertions. */
    for (unsigned int i = 0; i < 128; ++i) if (messages[i]) destroy(messages[i]);
    printf("FACE_RUNTIME_PASS mode=%s\n", mode); return 0;
}
