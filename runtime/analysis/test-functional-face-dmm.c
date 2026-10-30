/* SPDX-License-Identifier: MIT */
#define _GNU_SOURCE
#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/wait.h>
#include "dmm-service.h"
/* Includes the independent module to test a fork with its private lock held. */
#include "functional-face-dmm.c"

#define MAX_MESSAGES 256u
struct message { unsigned int source, size, request; unsigned char wire[40]; };
static struct message *messages[MAX_MESSAGES];
static struct functional_face_dmm_descriptor registrations[3];
static struct functional_face_dmm_descriptor current_binding;
static struct full_imaging_io io;
static void *last_reply, *current_request;
static unsigned int allocations, request_releases, reply_releases, register_calls, validate_calls, unregister_calls;
static unsigned int source_sequence = 1, inline_reply, reentry, callback_depth;
static int allocate_error, null_reply, short_reply, bad_source, send_error, alloc_alias;
static int request_free_error, reply_free_error, register_error, validate_error, unregister_error, bad_logical;
static unsigned int cross_thread, foreign_rejections;

static uint32_t tget(const unsigned char *p, unsigned int n) {
    uint32_t v = 0;
    for (unsigned int i = 0; i < n; ++i) v |= (uint32_t)p[i] << (8 * i);
    return v;
}
static void tput(unsigned char *p, uint64_t v, unsigned int n) {
    for (unsigned int i = 0; i < n; ++i) p[i] = (unsigned char)(v >> (8 * i));
}
static uint64_t thash(const void *p, size_t n) {
    const unsigned char *v = p;
    uint64_t result = UINT64_C(14695981039346656037);
    for (size_t i = 0; i < n; ++i) result = (result ^ v[i]) * UINT64_C(1099511628211);
    return result;
}
static struct message *message_find(void *p) {
    for (unsigned int i = 0; i < MAX_MESSAGES; ++i)
        if (messages[i] && messages[i]->wire == p) return messages[i];
    return NULL;
}
static struct message *message_new(unsigned int source, unsigned int size, unsigned int request) {
    struct message *m = calloc(1, sizeof *m);
    assert(m);
    m->source = source; m->size = size; m->request = request;
    for (unsigned int i = 0; i < MAX_MESSAGES; ++i) if (!messages[i]) { messages[i] = m; return m; }
    abort();
}
static void message_drop(void *p) {
    for (unsigned int i = 0; i < MAX_MESSAGES; ++i) if (messages[i] && messages[i]->wire == p) {
        free(messages[i]); messages[i] = NULL; return;
    }
    abort();
}
static struct functional_face_dmm_descriptor creator(unsigned int index) {
    struct functional_face_dmm_descriptor d = {0};
    d.domain = FUNCTIONAL_FACE_DMM_DOMAIN; d.unit = 0x1d9 + index; d.owner = UINT64_C(0xface0001) + index;
    return d;
}
/* Independent original mode-zero bodies from verified golden-op40.json. */
static const struct { unsigned int op; const char *hex; } request_goldens[] = {
    {0x20, "20000000d901000000000000ffffffff000000000000000000000000000000000000000000000000"},
    {0x21, "21000000d90100000284000000000000000000000000000000000000000000000000000000000000"},
    {0x23, "23000000000000000284000000000000000000003412000000000000000000000000000000000000"},
    {0x24, "240000000000000002840000ffffffff000000000000000000000000000000000000000000000000"},
    {0x25, "25000000000000000284000000000000000000000000000000000000000000000000000000000000"},
};
static struct message *request_new(unsigned int op, const struct functional_face_dmm_descriptor *b) {
    size_t index = 0;
    while (index < sizeof request_goldens / sizeof *request_goldens && request_goldens[index].op != op) ++index;
    assert(index < sizeof request_goldens / sizeof *request_goldens && strlen(request_goldens[index].hex) == 80);
    struct message *m = message_new(0x81cf6100u | ((source_sequence++ % 255) + 1), 40, 1);
    for (unsigned int i = 0; i < 40; ++i) {
        unsigned int byte;
        assert(sscanf(request_goldens[index].hex + i * 2, "%2x", &byte) == 1);
        m->wire[i] = (unsigned char)byte;
    }
    if (op == 0x20 || op == 0x21) tput(m->wire + 0x04, b->unit, 4);
    if (op != 0x20) tput(m->wire + 0x08, b->handle, 4);
    if (op == 0x23) tput(m->wire + 0x14, m->source & 0xffffu, 2);
    return m;
}
static void callback_check(void) {
    if (!reentry || callback_depth) return;
    ++callback_depth;
    struct functional_face_dmm_snapshot snapshot;
    assert(functional_face_dmm_snapshot(&snapshot) == -EBUSY);
    struct functional_face_dmm_descriptor b = creator(2);
    struct message *q = request_new(0x20, &b);
    int rc = 7;
    assert(functional_face_dmm_dispatch(FUNCTIONAL_FACE_DMM_CP, q->wire, &io, 1, &b, &rc) == 1);
    assert(rc == -EBUSY && message_find(q->wire));
    message_drop(q->wire);
    --callback_depth;
}
static int transport_allocate(unsigned int destination, void **out, unsigned int bytes, unsigned int wait) {
    assert(destination >> 28 == 8 && bytes == 40 && wait == 1);
    ++allocations; callback_check();
    if (alloc_alias) { *out = alloc_alias == 1 ? current_request : last_reply; return allocate_error; }
    if (null_reply) { *out = NULL; return allocate_error; }
    *out = message_new(0, short_reply ? 39 : 40, 0)->wire;
    return allocate_error;
}
static unsigned int transport_size(void *p) {
    callback_check(); struct message *m = message_find(p); assert(m); return m->size;
}
static unsigned int transport_source(void *p) {
    callback_check(); struct message *m = message_find(p); assert(m); return m->source;
}
static void transport_set_source(void *p, unsigned int source) {
    callback_check(); struct message *m = message_find(p); assert(m);
    m->source = bad_source ? 0x1234 : source;
}
static int transport_release(unsigned int destination, void *p) {
    callback_check(); struct message *m = message_find(p); assert(m);
    if (m->request) {
        assert(destination == FUNCTIONAL_FACE_DMM_CP); ++request_releases;
        if (request_free_error) return request_free_error;
    } else {
        assert(destination >> 28 == 8); ++reply_releases;
        if (reply_free_error) return reply_free_error;
    }
    message_drop(p); return 0;
}
struct foreign_args { unsigned int destination; void *reply; struct functional_face_dmm_ticket ticket; };
static void *foreign_consume(void *arg) {
    struct foreign_args *a = arg;
    struct functional_face_dmm_ticket out;
    assert(functional_face_dmm_receive(a->destination, a->reply, &out) == -ESTALE);
    int rc = 0;
    assert(functional_face_dmm_release_reply(a->destination, a->reply, &a->ticket, transport_release, &rc) == 1);
    assert(rc == -ESTALE); ++foreign_rejections;
    return NULL;
}
static int transport_send(unsigned int destination, void *p) {
    callback_check(); struct message *m = message_find(p); assert(m && !m->request);
    assert(m->source == FUNCTIONAL_FACE_DMM_CP && m->size == 40);
    assert(p != current_request && !tget(m->wire + 4, 2));
    last_reply = p;
    if (inline_reply) {
        struct functional_face_dmm_ticket ticket;
        assert(!functional_face_dmm_receive(destination, p, &ticket));
        if (cross_thread) {
            struct foreign_args args = {destination, p, ticket}; pthread_t t;
            assert(!pthread_create(&t, NULL, foreign_consume, &args)); assert(!pthread_join(t, NULL));
        }
        int rc = 9;
        assert(functional_face_dmm_release_reply(destination, p, &ticket, transport_release, &rc) == 1 && !rc);
    }
    return send_error;
}
static int registry_register(void *context, struct functional_face_dmm_descriptor *d) {
    assert(context == registrations); ++register_calls; callback_check();
    if (register_error) return register_error;
    int index = (int)d->unit - 0x1d9;
    assert(index >= 0 && index < 3 && !registrations[index].host_view);
    assert(d->host_view && d->host_view % 4096 == 0 && d->mapped_bytes % 4096 == 0);
    assert(d->bytes == capacities[index] && !d->logical && !d->registration && !d->reference);
    for (size_t i = 0; i < d->mapped_bytes; ++i) assert(!((unsigned char *)d->host_view)[i]);
    d->logical = bad_logical ? (uint64_t)d->host_view : UINT64_C(0x123430000000) + (unsigned int)index * 0x100000u;
    d->registration = UINT64_C(0xd0000000) + register_calls;
    registrations[index] = *d;
    return 0;
}
static int registry_validate(void *context, const struct functional_face_dmm_descriptor *d) {
    assert(context == registrations); ++validate_calls; callback_check();
    if (validate_error) return validate_error;
    int index = (int)d->unit - 0x1d9;
    assert(index >= 0 && index < 3);
    if (!same_descriptor(d, &registrations[index])) return -ESTALE;
    const volatile unsigned char *p = (void *)d->host_view;
    (void)p[0]; (void)p[d->bytes - 1];
    return 0;
}
static int registry_unregister(void *context, const struct functional_face_dmm_descriptor *d) {
    assert(context == registrations); ++unregister_calls; callback_check();
    if (unregister_error) return unregister_error;
    int index = (int)d->unit - 0x1d9;
    assert(index >= 0 && index < 3 && same_descriptor(d, &registrations[index]));
    memset(&registrations[index], 0, sizeof registrations[index]);
    return 0;
}
static void setup(void) {
    io = (struct full_imaging_io){transport_allocate, transport_release, transport_set_source,
        transport_send, transport_size, transport_source, NULL};
    struct functional_face_dmm_registry r = {registrations, registry_register, registry_validate, registry_unregister};
    assert(!functional_face_dmm_enable(&r));
}
static struct functional_face_dmm_snapshot snap(void) {
    struct functional_face_dmm_snapshot s;
    assert(!functional_face_dmm_snapshot(&s)); return s;
}
static int dispatch(unsigned int op, const struct functional_face_dmm_descriptor *b, void **caller_request) {
    struct message *q = request_new(op, b); current_request = q->wire; current_binding = *b;
    void *pointer = q->wire;
    int rc = 19;
    assert(functional_face_dmm_dispatch(FUNCTIONAL_FACE_DMM_CP, pointer, &io, 1, b, &rc) == 1);
    if (caller_request) *caller_request = pointer;
    current_request = NULL;
    return rc;
}
static struct functional_face_dmm_ticket consume(void *reply) {
    struct message *m = message_find(reply); assert(m);
    unsigned int destination = 0;
    for (unsigned int i = 0; i < TX_COUNT; ++i)
        if (transactions[i].active && transactions[i].reply == reply) destination = transactions[i].ticket.destination;
    assert(destination);
    struct functional_face_dmm_ticket ticket;
    assert(!functional_face_dmm_receive(destination, reply, &ticket));
    assert(!memcmp(ticket.wire, m->wire, 40));
    int rc = 19;
    assert(functional_face_dmm_release_reply(destination, reply, &ticket, transport_release, &rc) == 1 && !rc);
    return ticket;
}
static struct functional_face_dmm_ticket operation(unsigned int op,
    const struct functional_face_dmm_descriptor *b, int status) {
    assert(!dispatch(op, b, NULL));
    struct functional_face_dmm_ticket ticket = consume(last_reply);
    assert(tget(ticket.wire, 2) == (op | 0x8000) && (int16_t)tget(ticket.wire + 2, 2) == status);
    assert(tget(ticket.wire + 6, 2) == (op == 0x23 ? ticket.destination & 0xffffu : 0) &&
        !tget(ticket.wire + 4, 2));
    return ticket;
}
static struct functional_face_dmm_descriptor create(unsigned int index) {
    struct functional_face_dmm_descriptor b = creator(index);
    struct functional_face_dmm_ticket t = operation(0x20, &b, 0);
    assert(t.span.handle == (0x8400u | (index + 2)) && t.span.epoch && !t.span.reference);
    assert(tget(t.wire + 16, 4) == b.unit && !tget(t.wire + 24, 4) && !tget(t.wire + 32, 4));
    return t.span;
}
static void successful_units(void) {
    struct dmm_service speech = {.physical = DMM_TEST_PHYSICAL};
    speech.memory = malloc(DMM_TEST_SIZE); assert(speech.memory);
    unsigned char q[40] = {0x20}, r[40]; tput(q + 4, 0x63a, 4); tput(q + 22, 1, 2);
    for (unsigned int i = 0; i < 2; ++i) {
        assert(!dmm_service_reply(&speech, q, 40, r));
        speech.slots[i].creator_kind = DMM_CREATOR_SPEECH_INITIAL;
        assert(speech.slots[i].handle == 0x8400 + i && speech.slots[i].open_count == 1 &&
            speech.slots[i].allocation_epoch == i + 1);
    }
    struct dmm_service saved; memcpy(&saved, &speech, sizeof saved);
    unsigned char *speech_saved = malloc(DMM_TEST_SIZE); assert(speech_saved);
    memcpy(speech_saved, speech.memory, DMM_TEST_SIZE);
    setup();
    struct functional_face_dmm_descriptor owners[3];
    for (unsigned int i = 0; i < 3; ++i) owners[i] = create(i);
    for (unsigned int i = 0; i < 3; ++i) for (unsigned int j = 0; j < i; ++j) {
        assert(!overlap(owners[i].host_view, owners[i].mapped_bytes, owners[j].host_view, owners[j].mapped_bytes));
        assert(owners[i].logical != owners[j].logical && owners[i].registration != owners[j].registration);
    }
    for (unsigned int i = 0; i < 3; ++i) {
        struct functional_face_dmm_descriptor owner = owners[i];
        assert(owner.logical != (uint64_t)owner.host_view && owner.bytes == capacities[i]);
        struct functional_face_dmm_snapshot s = snap();
        assert(s.units[i].allocated && !s.units[i].opens && !s.units[i].shares);
        unsigned char *pattern = malloc(owner.bytes), *copy = malloc(owner.bytes); assert(pattern && copy);
        for (size_t j = 0; j < owner.bytes; ++j) pattern[j] = (unsigned char)((j * 37 + i * 73 + 11) ^ (j >> 9));
        struct functional_face_dmm_ticket opened = operation(0x24, &owner, 0);
        struct functional_face_dmm_borrow writer;
        assert(!functional_face_dmm_borrowed_span(&opened.span, 0, owner.bytes,
            FUNCTIONAL_FACE_DMM_WRITE | FUNCTIONAL_FACE_DMM_TRANSFER, &writer));
        struct functional_face_dmm_readback readback;
        assert(!functional_face_dmm_write(&writer, 0, pattern, owner.bytes, &readback));
        assert(readback.verified_bytes == owner.bytes && readback.after_digest == thash(pattern, owner.bytes));
        assert(!memcmp((void *)writer.host_view, pattern, owner.bytes));
        assert(functional_face_dmm_read(&writer, 0, copy, owner.bytes, &readback) == -EACCES);
        struct functional_face_dmm_borrow denied;
        assert(functional_face_dmm_borrowed_span(&owner, 0, 1, FUNCTIONAL_FACE_DMM_READ, &denied) == -EBUSY);
        assert(functional_face_dmm_write(&writer, owner.bytes, pattern, 1, &readback) == -ERANGE);
        struct functional_face_dmm_borrow forged = writer;
        ++forged.nonce;
        assert(functional_face_dmm_write(&forged, 0, pattern, 1, &readback) == -ESTALE);
        forged = writer; ++forged.span.epoch;
        assert(functional_face_dmm_release_borrow(&forged, &readback) == -ESTALE);
        assert(!functional_face_dmm_release_borrow(&writer, &readback));
        assert(readback.verified_bytes == owner.bytes && readback.before_digest != readback.after_digest);
        assert(functional_face_dmm_release_borrow(&writer, &readback) == -ESTALE);
        assert(opened.span.reference && tget(opened.wire + 24, 4) == (uint32_t)owner.logical &&
            tget(opened.wire + 28, 4) == (uint32_t)(owner.logical >> 32) && tget(opened.wire + 32, 4) == owner.bytes);
        struct functional_face_dmm_ticket shared = operation(0x21, &owner, 0);
        assert(shared.span.reference != opened.span.reference && shared.span.reference);
        struct functional_face_dmm_borrow reader;
        assert(!functional_face_dmm_borrowed_span(&opened.span, 0, owner.bytes, FUNCTIONAL_FACE_DMM_READ, &reader));
        assert(!functional_face_dmm_read(&reader, 0, copy, owner.bytes, &readback));
        assert(readback.verified_bytes == owner.bytes && readback.after_digest == thash(pattern, owner.bytes));
        assert(!memcmp(pattern, copy, owner.bytes));
        assert(functional_face_dmm_read(&reader, 0, (void *)owner.host_view, 1, &readback) == -EINVAL);
        (void)operation(0x23, &owner, -1);
        (void)operation(0x25, &opened.span, 0);
        assert(functional_face_dmm_read(&reader, 0, copy, 1, &readback) == -ESTALE);
        (void)operation(0x25, &shared.span, 0);
        (void)operation(0x23, &owner, -1);
        assert(!functional_face_dmm_release_borrow(&reader, &readback));
        assert(functional_face_dmm_borrowed_span(&opened.span, 0, 1, FUNCTIONAL_FACE_DMM_READ, &reader) == -ESTALE);
        assert(functional_face_dmm_borrowed_span(&owner, owner.bytes, 1, FUNCTIONAL_FACE_DMM_READ, &reader) == -ERANGE);
        assert(functional_face_dmm_borrowed_span(&owner, 1, SIZE_MAX, FUNCTIONAL_FACE_DMM_READ, &reader) == -ERANGE);
        assert(functional_face_dmm_borrowed_span(&owner, 0, 0, FUNCTIONAL_FACE_DMM_READ, &reader) == -EINVAL);
        assert(functional_face_dmm_borrowed_span(&owner, 0, 1,
            FUNCTIONAL_FACE_DMM_READ | FUNCTIONAL_FACE_DMM_WRITE, &reader) == -EINVAL);
        assert(!functional_face_dmm_borrowed_span(&owner, owner.bytes - 1, 1, FUNCTIONAL_FACE_DMM_READ, &reader));
        unsigned char last_byte = 0;
        assert(!functional_face_dmm_read(&reader, 0, &last_byte, 1, &readback) && last_byte == pattern[owner.bytes - 1]);
        assert(!functional_face_dmm_release_borrow(&reader, &readback));
        for (unsigned int field = 0; field < 7; ++field) {
            struct functional_face_dmm_descriptor bad = owner;
            if (field == 0) ++bad.epoch;
            if (field == 1) ++bad.domain;
            if (field == 2) ++bad.owner;
            if (field == 3) ++bad.reference;
            if (field == 4) ++bad.logical;
            if (field == 5) ++bad.host_view;
            if (field == 6) ++bad.registration;
            assert(functional_face_dmm_borrowed_span(&bad, 0, 1, FUNCTIONAL_FACE_DMM_READ, &reader) == -ESTALE);
        }
        s = snap();
        assert(!s.units[i].opens && !s.units[i].shares && !s.units[i].borrows && !s.units[i].transfers);
        assert(s.units[i].verified_write_bytes == owner.bytes && s.units[i].verified_read_bytes == owner.bytes + 1);
        assert(s.units[i].digest == thash(pattern, owner.bytes));
        printf("UNIT=%x bytes=%zu host=%llx logical=%llx digest=%016llx verified=%zu\n", owner.unit,
            owner.bytes, (unsigned long long)owner.host_view, (unsigned long long)owner.logical,
            (unsigned long long)s.units[i].digest, owner.bytes);
        (void)operation(0x23, &owner, 0);
        assert(!registrations[i].host_view && !snap().units[i].span.host_view);
        assert(!memcmp(&saved, &speech, sizeof saved) && !memcmp(speech_saved, speech.memory, DMM_TEST_SIZE));
        free(pattern); free(copy);
    }
    struct functional_face_dmm_snapshot s = snap();
    assert(s.epochs == 3 && s.queued == 24 && s.request_freed == 24 && s.reply_freed == 24 &&
        s.received == 24 && s.ap_consumed == 18 && !s.live_requests && !s.live_replies && !s.faults);
    assert(register_calls == 3 && unregister_calls == 3);
    assert(!functional_face_dmm_shutdown());
    free(speech_saved); free(speech.memory);
    puts("COUNTS units=3 bytes=514304 queued=24 request_freed=24 reply_freed=24 received=24 ap_consumed=18 speech_unchanged=1");
}
static void generation_test(void) {
    setup();
    struct functional_face_dmm_descriptor old = {0};
    struct functional_face_dmm_borrow old_borrow = {0};
    for (unsigned int i = 0; i < 63; ++i) {
        struct functional_face_dmm_descriptor b = creator(0);
        struct functional_face_dmm_ticket t = operation(0x20, &b, 0);
        assert(t.span.handle == (0x8002u | ((i % 31 + 1) << 10)) && t.span.epoch == i + 1);
        if (!i) {
            old = t.span;
            assert(!functional_face_dmm_borrowed_span(&old, 0, 1, FUNCTIONAL_FACE_DMM_READ, &old_borrow));
            struct functional_face_dmm_readback out;
            assert(!functional_face_dmm_release_borrow(&old_borrow, &out));
        }
        if (i == 31 || i == 62) {
            assert(old.handle == t.span.handle && old.epoch != t.span.epoch);
            struct functional_face_dmm_borrow borrow;
            assert(functional_face_dmm_borrowed_span(&old, 0, 1, FUNCTIONAL_FACE_DMM_READ, &borrow) == -ESTALE);
            (void)operation(0x24, &old, -5);
            struct functional_face_dmm_readback out;
            unsigned char byte = 0x5a;
            assert(functional_face_dmm_read(&old_borrow, 0, &byte, 1, &out) == -ESTALE && byte == 0x5a);
            assert(functional_face_dmm_release_borrow(&old_borrow, &out) == -ESTALE);
        }
        (void)operation(0x23, &t.span, 0);
    }
    assert(snap().epochs == 63 && !functional_face_dmm_shutdown());
}
static void capacity_test(void) {
    setup(); struct functional_face_dmm_descriptor owner = create(2);
    struct functional_face_dmm_descriptor refs[REF_COUNT];
    for (unsigned int i = 0; i < REF_COUNT; ++i) refs[i] = operation(0x24, &owner, 0).span;
    (void)operation(0x24, &owner, -1);
    assert(snap().units[2].opens == REF_COUNT);
    for (unsigned int i = 0; i < REF_COUNT; ++i) (void)operation(0x25, &refs[i], 0);
    struct functional_face_dmm_borrow leases[BORROW_COUNT], denied;
    for (unsigned int i = 0; i < BORROW_COUNT; ++i)
        assert(!functional_face_dmm_borrowed_span(&owner, i, 1, FUNCTIONAL_FACE_DMM_READ, &leases[i]));
    assert(functional_face_dmm_borrowed_span(&owner, 0, 1, FUNCTIONAL_FACE_DMM_READ, &denied) == -ENOSPC);
    struct functional_face_dmm_readback out;
    for (unsigned int i = 0; i < BORROW_COUNT; ++i) assert(!functional_face_dmm_release_borrow(&leases[i], &out));
    (void)operation(0x23, &owner, 0); assert(!functional_face_dmm_shutdown());
}
static void rollback_test(void) {
    setup(); struct functional_face_dmm_descriptor b = creator(0);
    void *q = NULL; send_error = -88;
    assert(dispatch(0x20, &b, &q) == -88 && message_find(q));
    struct functional_face_dmm_snapshot s = snap();
    assert(!s.units[0].allocated && !s.units[0].span.host_view && !s.live_requests && !s.live_replies && !s.faults);
    assert(register_calls == 1 && unregister_calls == 1 && !request_releases && reply_releases == 1);
    message_drop(q); send_error = 0;
    struct functional_face_dmm_descriptor owner = operation(0x20, &b, 0).span;
    const unsigned int ops[] = {0x24, 0x21, 0x23};
    for (unsigned int i = 0; i < 3; ++i) {
        s = snap(); send_error = -88;
        assert(dispatch(ops[i], &owner, &q) == -88 && message_find(q)); message_drop(q);
        send_error = 0;
        struct functional_face_dmm_snapshot after = snap();
        assert(!memcmp(&s.units[0], &after.units[0], sizeof s.units[0]));
    }
    struct functional_face_dmm_descriptor opened = operation(0x24, &owner, 0).span;
    s = snap(); send_error = -88;
    assert(dispatch(0x25, &opened, &q) == -88); message_drop(q); send_error = 0;
    assert(snap().units[0].opens == s.units[0].opens);
    (void)operation(0x25, &opened, 0); (void)operation(0x23, &owner, 0);
    assert(!functional_face_dmm_shutdown());
}
static void allocation_failure(const char *mode) {
    setup(); struct functional_face_dmm_descriptor b = creator(0);
    if (!strcmp(mode, "alloc-error")) allocate_error = -77;
    if (!strcmp(mode, "alloc-null")) null_reply = 1;
    if (!strcmp(mode, "short-reply")) short_reply = 1;
    if (!strcmp(mode, "source-error")) bad_source = 1;
    void *q = NULL;
    int expected = allocate_error ? allocate_error : null_reply ? -ENOMEM : short_reply ? -EMSGSIZE : -EPROTO;
    assert(dispatch(0x20, &b, &q) == expected && message_find(q));
    struct functional_face_dmm_snapshot s = snap();
    assert(!s.units[0].allocated && !s.live_requests && !s.live_replies && !s.faults && !request_releases);
    assert(reply_releases == (unsigned int)!null_reply);
    message_drop(q); assert(!functional_face_dmm_shutdown());
}
static void registry_failure(const char *mode) {
    setup();
    if (!strcmp(mode, "register-error")) register_error = -EIO;
    if (!strcmp(mode, "validate-error")) validate_error = -ESTALE;
    if (!strcmp(mode, "logical-alias")) bad_logical = 1;
    struct functional_face_dmm_descriptor b = creator(1);
    (void)operation(0x20, &b, validate_error ? -5 : -1);
    struct functional_face_dmm_snapshot s = snap();
    assert(!s.units[1].allocated && !s.units[1].span.host_view && !s.faults);
    assert(!s.ap_consumed && unregister_calls == (unsigned int)!register_error);
    assert(!functional_face_dmm_shutdown());
}
static void retention_test(const char *mode) {
    setup(); struct functional_face_dmm_descriptor b = creator(0);
    if (!strcmp(mode, "request-free-error")) request_free_error = -97;
    if (!strcmp(mode, "reply-free-error")) reply_free_error = -99;
    if (!strcmp(mode, "cleanup-error")) { allocate_error = -77; reply_free_error = -99; }
    if (!strcmp(mode, "send-observed-error")) { inline_reply = 1; send_error = -88; }
    if (!strcmp(mode, "request-alias")) alloc_alias = 1;
    if (!strcmp(mode, "live-alias")) {
        assert(!dispatch(0x20, &b, NULL)); alloc_alias = 2; b = creator(1);
    }
    void *q = NULL;
    int rc = dispatch(0x20, &b, &q);
    if (allocate_error || alloc_alias || send_error) {
        assert(rc == (allocate_error ? -77 : send_error ? -88 : -EALREADY));
        assert(message_find(q)); message_drop(q);
    } else {
        assert(!rc);
        if (request_free_error) assert(message_find(q));
        struct functional_face_dmm_ticket ticket;
        unsigned int destination = transactions[0].ticket.destination;
        assert(!functional_face_dmm_receive(destination, last_reply, &ticket));
        int freed = 123;
        assert(functional_face_dmm_release_reply(destination, last_reply, &ticket, transport_release, &freed) == 1);
        assert(freed == reply_free_error);
    }
    struct functional_face_dmm_snapshot s = snap(); assert(s.faults && !s.ap_consumed);
    if (request_free_error) assert(s.live_requests == 1 && !s.live_replies);
    if (reply_free_error) assert(s.live_replies == 1);
    if (allocate_error) assert(s.retained_cleanup == 1);
    unsigned int frees = request_releases + reply_releases;
    assert(functional_face_dmm_shutdown() == -EIO);
    (void)snap(); (void)snap();
    assert(frees == request_releases + reply_releases);
}
static void unregister_failure(void) {
    setup(); struct functional_face_dmm_descriptor owner = create(0);
    unregister_error = -EIO;
    (void)operation(0x23, &owner, 0);
    struct functional_face_dmm_snapshot s = snap();
    assert(s.faults == 1 && s.retained_cleanup == 1 && !s.units[0].allocated && s.units[0].span.host_view);
    assert(registrations[0].host_view && unregister_calls == 1);
    assert(functional_face_dmm_shutdown() == -EIO && unregister_calls == 1);
}
static void malformed_test(void) {
    setup(); struct functional_face_dmm_descriptor b = creator(0);
    struct message *q = request_new(0x20, &b);
    unsigned char saved[40]; memcpy(saved, q->wire, 40);
    int result = 198;
    for (unsigned int i = 0; i < 40; ++i) {
        if (i < 2 || (i >= 4 && i < 16) || (i >= 20 && i < 22)) continue;
        q->wire[i] = 1;
        assert(!functional_face_dmm_dispatch(FUNCTIONAL_FACE_DMM_CP, q->wire, &io, 1, &b, &result));
        assert(result == 198); memcpy(q->wire, saved, 40);
    }
    const unsigned int bad_sizes[] = {0, 39, 41};
    for (unsigned int i = 0; i < 3; ++i) {
        q->size = bad_sizes[i];
        assert(!functional_face_dmm_dispatch(FUNCTIONAL_FACE_DMM_CP, q->wire, &io, 1, &b, &result));
    }
    q->size = 40;
    const unsigned int bad_sources[] = {0, 0x80000000, FUNCTIONAL_FACE_DMM_CP, 1};
    for (unsigned int i = 0; i < 4; ++i) {
        q->source = bad_sources[i];
        assert(!functional_face_dmm_dispatch(FUNCTIONAL_FACE_DMM_CP, q->wire, &io, 1, &b, &result));
    }
    q->source = 0x81cf61c6;
    tput(q->wire + 4, 0x1dc, 4);
    assert(!functional_face_dmm_dispatch(FUNCTIONAL_FACE_DMM_CP, q->wire, &io, 1, &b, &result));
    memcpy(q->wire, saved, 40);
    assert(!functional_face_dmm_dispatch(0x0061003c, q->wire, &io, 1, &b, &result));
    assert(!functional_face_dmm_dispatch(FUNCTIONAL_FACE_DMM_CP, q->wire, &io, 0, &b, &result));
    b.domain = 0;
    assert(!functional_face_dmm_dispatch(FUNCTIONAL_FACE_DMM_CP, q->wire, &io, 1, &b, &result));
    b.domain = 1;
    q->wire[0] = 0x22;
    assert(!functional_face_dmm_dispatch(FUNCTIONAL_FACE_DMM_CP, q->wire, &io, 1, &b, &result));
    assert(!allocations && !request_releases && result == 198);
    message_drop(q->wire); assert(!functional_face_dmm_shutdown());
}
static void assert_declined_unchanged(struct message *q,
    const struct functional_face_dmm_descriptor *binding) {
    struct functional_face_dmm_snapshot before = snap();
    struct unit saved_units[FUNCTIONAL_FACE_DMM_UNITS];
    struct borrow saved_borrows[BORROW_COUNT];
    struct transaction saved_transactions[TX_COUNT];
    struct functional_face_dmm_descriptor saved_registrations[3];
    struct message saved_request = *q;
    unsigned char *backing[FUNCTIONAL_FACE_DMM_UNITS] = {0};
    unsigned int callbacks[] = {allocations, request_releases, reply_releases,
        register_calls, validate_calls, unregister_calls};
    uint64_t nonce = next_nonce;
    memcpy(saved_units, units, sizeof units);
    memcpy(saved_borrows, borrows, sizeof borrows);
    memcpy(saved_transactions, transactions, sizeof transactions);
    memcpy(saved_registrations, registrations, sizeof registrations);
    for (unsigned int i = 0; i < FUNCTIONAL_FACE_DMM_UNITS; ++i) {
        const struct functional_face_dmm_descriptor *d = &before.units[i].span;
        if (!d->host_view) continue;
        backing[i] = malloc(d->mapped_bytes); assert(backing[i]);
        memcpy(backing[i], (void *)d->host_view, d->mapped_bytes);
    }
    int result = 198;
    assert(!functional_face_dmm_dispatch(FUNCTIONAL_FACE_DMM_CP, q->wire, &io, 1, binding, &result));
    assert(result == 198 && message_find(q->wire) == q && !memcmp(q, &saved_request, sizeof *q));
    struct functional_face_dmm_snapshot after = snap();
    assert(!memcmp(&before, &after, sizeof before) && next_nonce == nonce);
    assert(!memcmp(saved_units, units, sizeof units) && !memcmp(saved_borrows, borrows, sizeof borrows));
    assert(!memcmp(saved_transactions, transactions, sizeof transactions));
    assert(!memcmp(saved_registrations, registrations, sizeof registrations));
    unsigned int after_callbacks[] = {allocations, request_releases, reply_releases,
        register_calls, validate_calls, unregister_calls};
    assert(!memcmp(callbacks, after_callbacks, sizeof callbacks));
    for (unsigned int i = 0; i < FUNCTIONAL_FACE_DMM_UNITS; ++i) if (backing[i]) {
        const struct functional_face_dmm_descriptor *d = &before.units[i].span;
        assert(!memcmp(backing[i], (void *)d->host_view, d->mapped_bytes));
        free(backing[i]);
    }
}
static void wire_test(unsigned int op) {
    setup();
    struct functional_face_dmm_descriptor guard = create(2);
    memset((void *)guard.host_view, 0x67, guard.mapped_bytes);
    struct functional_face_dmm_descriptor owner = op == 0x20 ? creator(0) : create(0);
    struct functional_face_dmm_descriptor binding = op == 0x25 ? operation(0x24, &owner, 0).span : owner;
    struct message *q = request_new(op, &binding);
    q->source = 0x8abc1234;
    if (op == 0x23) tput(q->wire + 0x14, 0x1234, 2);
    unsigned char saved[40]; memcpy(saved, q->wire, 40);
    unsigned int fixed_mutations = 0, explicit_negatives = 0;
    for (unsigned int i = 0; i < 40; ++i) {
        if (((op == 0x20 || op == 0x21) && i >= 0x04 && i < 0x08) ||
            (op != 0x20 && i >= 0x08 && i < 0x0c)) continue;
        q->wire[i] ^= 0x80;
        assert_declined_unchanged(q, &binding); ++fixed_mutations;
        memcpy(q->wire, saved, 40);
    }
    /* Reject both the old all-FF template and the opposite create/open value. */
    tput(q->wire + 0x0c, op == 0x20 || op == 0x24 ? 0 : UINT32_MAX, 4);
    assert_declined_unchanged(q, &binding); ++explicit_negatives;
    memcpy(q->wire, saved, 40);
    tput(q->wire + 0x14, op == 0x23 ? 0 : 0x1234, 2);
    assert_declined_unchanged(q, &binding); ++explicit_negatives;
    memcpy(q->wire, saved, 40);
    if (op == 0x23) {
        q->source ^= 1;
        assert_declined_unchanged(q, &binding); ++explicit_negatives;
        q->source ^= 1;
    }
    if (op == 0x20 || op == 0x23) {
        tput(q->wire + 0x16, op == 0x20 ? 1 : 2, 2);
        assert_declined_unchanged(q, &binding); ++explicit_negatives;
        memcpy(q->wire, saved, 40);
    }
    if (op == 0x20 || op == 0x21) {
        tput(q->wire + 0x04, binding.unit + 1, 4);
        assert_declined_unchanged(q, &binding); ++explicit_negatives;
        memcpy(q->wire, saved, 40);
    }
    if (op != 0x20) {
        tput(q->wire + 0x08, binding.handle ^ 1, 4);
        assert_declined_unchanged(q, &binding); ++explicit_negatives;
        memcpy(q->wire, saved, 40);
    }
    const unsigned int bad_sizes[] = {0, 39, 41};
    for (unsigned int i = 0; i < 3; ++i) {
        q->size = bad_sizes[i];
        assert_declined_unchanged(q, &binding); ++explicit_negatives;
    }
    q->size = 40;
    const unsigned int bad_sources[] = {0, 0x80000000, FUNCTIONAL_FACE_DMM_CP, 1};
    for (unsigned int i = 0; i < 4; ++i) {
        q->source = bad_sources[i];
        assert_declined_unchanged(q, &binding); ++explicit_negatives;
    }
    q->source = 0x8abc1234;
    struct functional_face_dmm_descriptor bad_binding = binding;
    bad_binding.domain = 0;
    assert_declined_unchanged(q, &bad_binding); ++explicit_negatives;
    assert_declined_unchanged(q, NULL); ++explicit_negatives;
    tput(q->wire, 0x2a, 2);
    assert_declined_unchanged(q, &binding); ++explicit_negatives;
    memcpy(q->wire, saved, 40);
    int result = 198;
    current_request = q->wire;
    assert(functional_face_dmm_dispatch(FUNCTIONAL_FACE_DMM_CP, q->wire, &io, 1, &binding, &result) == 1);
    current_request = NULL;
    assert(!result);
    struct functional_face_dmm_ticket ticket = consume(last_reply);
    assert(ticket.destination == 0x8abc1234 && tget(ticket.wire, 2) == (op | 0x8000u));
    assert(!tget(ticket.wire + 2, 2) && tget(ticket.wire + 6, 2) == (op == 0x23 ? 0x1234u : 0));
    if (op == 0x20) owner = ticket.span;
    if (op == 0x21 || op == 0x24) (void)operation(0x25, &ticket.span, 0);
    if (op != 0x23) (void)operation(0x23, &owner, 0);
    (void)operation(0x23, &guard, 0);
    assert(!functional_face_dmm_shutdown());
    printf("WIRE op=%02x golden_positive=1 fixed_byte_mutations=%u explicit_negatives=%u unchanged_on_decline=1\n",
        op, fixed_mutations, explicit_negatives);
}
static void ticket_test(void) {
    setup(); struct functional_face_dmm_descriptor b = creator(0);
    assert(!dispatch(0x20, &b, NULL));
    struct transaction *tx = &transactions[0];
    unsigned int destination = tx->ticket.destination;
    struct message *m = message_find(last_reply); assert(m);
    const unsigned int offsets[] = {2, 6, 12, 24, 32};
    for (unsigned int i = 0; i < sizeof offsets / sizeof *offsets; ++i) {
        struct functional_face_dmm_ticket unchanged, out;
        memset(&out, 0x5a, sizeof out); unchanged = out;
        m->wire[offsets[i]] ^= 1;
        assert(functional_face_dmm_receive(destination, last_reply, &out) == -EPROTO);
        assert(!memcmp(&out, &unchanged, sizeof out) && !snap().received);
        m->wire[offsets[i]] ^= 1;
    }
    struct functional_face_dmm_ticket ticket;
    assert(!functional_face_dmm_receive(destination, last_reply, &ticket));
    assert(functional_face_dmm_receive(destination, last_reply, &ticket) == -ESTALE);
    for (unsigned int i = 0; i < 4; ++i) {
        struct functional_face_dmm_ticket bad = ticket;
        if (!i) ++bad.nonce;
        if (i == 1) ++bad.destination;
        if (i == 2) ++bad.span.epoch;
        if (i == 3) bad.wire[6] ^= 1;
        int rc = 99;
        assert(functional_face_dmm_release_reply(destination, last_reply, &bad, transport_release, &rc) == 1 && rc == -ESTALE);
    }
    struct foreign_args args = {destination, last_reply, ticket}; pthread_t t;
    assert(!pthread_create(&t, NULL, foreign_consume, &args)); assert(!pthread_join(t, NULL));
    int rc = 99;
    assert(functional_face_dmm_release_reply(destination, last_reply, &ticket, transport_release, &rc) == 1 && !rc);
    assert(!functional_face_dmm_release_reply(destination, last_reply, &ticket, transport_release, &rc));
    assert(snap().ap_consumed == 1 && foreign_rejections == 1);
    (void)operation(0x23, &ticket.span, 0); assert(!functional_face_dmm_shutdown());
}
static void *thread_operation(void *arg) {
    (void)arg;
    struct functional_face_dmm_descriptor owner = create(1);
    (void)operation(0x23, &owner, 0);
    return NULL;
}
static void inline_test(int threads) {
    setup(); inline_reply = 1; reentry = 1; cross_thread = (unsigned int)threads;
    struct functional_face_dmm_descriptor b = creator(0);
    assert(!dispatch(0x20, &b, NULL));
    struct functional_face_dmm_snapshot s = snap();
    assert(s.queued == 1 && s.request_freed == 1 && s.reply_freed == 1 && s.ap_consumed == 1);
    struct functional_face_dmm_descriptor owner = s.units[0].span;
    assert(!dispatch(0x23, &owner, NULL));
    assert(!snap().units[0].span.host_view && !snap().faults);
    inline_reply = reentry = cross_thread = 0;
    if (threads) {
        pthread_t t; assert(!pthread_create(&t, NULL, thread_operation, NULL)); assert(!pthread_join(t, NULL));
        assert(foreign_rejections == 2);
    }
    assert(!functional_face_dmm_shutdown());
}
static void fork_test(void) {
    setup(); struct functional_face_dmm_descriptor owner = create(0);
    LOCK(); pid_t pid = fork(); assert(pid >= 0);
    if (!pid) {
        struct functional_face_dmm_snapshot s;
        assert(functional_face_dmm_snapshot(&s) == -ECHILD);
        assert(functional_face_dmm_shutdown() == -ECHILD);
        struct functional_face_dmm_borrow b;
        assert(functional_face_dmm_borrowed_span(&owner, 0, 1, FUNCTIONAL_FACE_DMM_READ, &b) == -ECHILD);
        struct message *q = request_new(0x24, &owner); int rc = 0;
        assert(functional_face_dmm_dispatch(FUNCTIONAL_FACE_DMM_CP, q->wire, &io, 1, &owner, &rc) == 1 && rc == -ECHILD);
        _exit(0);
    }
    UNLOCK(); int status; assert(waitpid(pid, &status, 0) == pid && WIFEXITED(status) && !WEXITSTATUS(status));
    (void)operation(0x23, &owner, 0); assert(!functional_face_dmm_shutdown());
}
static void transport_guard_test(void) {
    setup();
    struct functional_face_dmm_descriptor b = creator(0);
    assert(!dispatch(0x20, &b, NULL));
    void *original_reply = last_reply;
    /* Negative fixture knows the pending producer but has not consumed it. */
    struct functional_face_dmm_descriptor pending = transactions[0].ticket.span;
    (void)operation(0x23, &pending, -1);
    struct functional_face_dmm_snapshot s = snap();
    assert(s.units[0].allocated && s.live_replies == 1 && s.ap_consumed == 0 && !unregister_calls);
    struct functional_face_dmm_ticket original = consume(original_reply);
    (void)operation(0x23, &original.span, 0);
    assert(snap().ap_consumed == 2 && !functional_face_dmm_shutdown());
}
static void overflow_test(void) {
    setup();
    struct functional_face_dmm_descriptor b = creator(0);
    uint64_t saved = next_nonce;
    next_nonce = UINT64_MAX;
    void *q = NULL;
    assert(dispatch(0x20, &b, &q) == -EOVERFLOW && message_find(q));
    assert(!allocations && !snap().live_requests); message_drop(q);
    next_nonce = saved;
    counters.epochs = UINT64_MAX;
    (void)operation(0x20, &b, -1);
    assert(snap().epochs == UINT64_MAX && !register_calls && !snap().units[0].allocated);
    assert(!functional_face_dmm_shutdown());
}
static void missing_test(void) {
    assert(functional_face_dmm_enable(NULL) == -ENODATA);
    struct functional_face_dmm_registry r = {0};
    r.register_span = registry_register;
    assert(functional_face_dmm_enable(&r) == -ENODATA);
    r.validate_span = registry_validate;
    assert(functional_face_dmm_enable(&r) == -ENODATA);
    assert(!snap().enabled);
}
int main(int argc, char **argv) {
    assert(argc == 2);
    const char *mode = argv[1];
    if (!strcmp(mode, "units")) successful_units();
    else if (!strcmp(mode, "generation")) generation_test();
    else if (!strcmp(mode, "capacity")) capacity_test();
    else if (!strcmp(mode, "rollback")) rollback_test();
    else if (!strcmp(mode, "alloc-error") || !strcmp(mode, "alloc-null") || !strcmp(mode, "short-reply") || !strcmp(mode, "source-error")) allocation_failure(mode);
    else if (!strcmp(mode, "register-error") || !strcmp(mode, "validate-error") || !strcmp(mode, "logical-alias")) registry_failure(mode);
    else if (!strcmp(mode, "request-free-error") || !strcmp(mode, "reply-free-error") || !strcmp(mode, "cleanup-error") ||
        !strcmp(mode, "request-alias") || !strcmp(mode, "live-alias") || !strcmp(mode, "send-observed-error")) retention_test(mode);
    else if (!strcmp(mode, "unregister-error")) unregister_failure();
    else if (!strcmp(mode, "malformed")) malformed_test();
    else if (!strcmp(mode, "wire-20")) wire_test(0x20);
    else if (!strcmp(mode, "wire-21")) wire_test(0x21);
    else if (!strcmp(mode, "wire-23")) wire_test(0x23);
    else if (!strcmp(mode, "wire-24")) wire_test(0x24);
    else if (!strcmp(mode, "wire-25")) wire_test(0x25);
    else if (!strcmp(mode, "ticket")) ticket_test();
    else if (!strcmp(mode, "inline")) inline_test(0);
    else if (!strcmp(mode, "threads")) inline_test(1);
    else if (!strcmp(mode, "fork")) fork_test();
    else if (!strcmp(mode, "missing")) missing_test();
    else if (!strcmp(mode, "overflow")) overflow_test();
    else if (!strcmp(mode, "transport-guard")) transport_guard_test();
    else abort();
    /* Fault modes deliberately retain model resources until process exit. This
     * host fixture drops only its message heap after all retention assertions. */
    for (unsigned int i = 0; i < MAX_MESSAGES; ++i) if (messages[i]) { free(messages[i]); messages[i] = NULL; }
    printf("FACE_DMM_PASS mode=%s physical_asic_verified=0 original_cp_verified=0 ap_capture_verified=0\n", mode);
    return 0;
}
