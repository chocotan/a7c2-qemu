/* SPDX-License-Identifier: MIT */
#define _GNU_SOURCE
#include <assert.h>
#include <inttypes.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>
#include <sys/wait.h>
#include "dmm-service.h"
/* Test-only access to the private lock/counter; DMM is separately linked. */
#include "functional-face-registry.c"

static struct functional_face_dmm_registry callbacks;
static unsigned int requests_freed, replies_freed, sent;
struct message { unsigned int source, size, request; unsigned char wire[40]; };
static void *pending_reply;
static unsigned int pending_destination;

static void put(unsigned char *p, uint64_t value, unsigned int n) {
    for (unsigned int i = 0; i < n; ++i) p[i] = (unsigned char)(value >> (8 * i));
}
static unsigned int get(const unsigned char *p, unsigned int n) {
    unsigned int value = 0;
    for (unsigned int i = 0; i < n; ++i) value |= (unsigned int)p[i] << (8 * i);
    return value;
}
static uint64_t hash(const void *data, size_t n) {
    const unsigned char *p = data;
    uint64_t result = UINT64_C(14695981039346656037);
    for (size_t i = 0; i < n; ++i) result = (result ^ p[i]) * UINT64_C(1099511628211);
    return result;
}
static struct message *message(void *p) {
    return (struct message *)((unsigned char *)p - offsetof(struct message, wire));
}
static int allocate(unsigned int destination, void **out, unsigned int bytes, unsigned int wait) {
    assert(destination == 0x81cf6101u && bytes == 40 && wait == 1);
    struct message *m = calloc(1, sizeof *m); assert(m);
    m->size = bytes; *out = m->wire; return 0;
}
static int release(unsigned int destination, void *p) {
    struct message *m = message(p);
    assert(destination == (m->request ? FUNCTIONAL_FACE_DMM_CP : 0x81cf6101u));
    if (m->request) ++requests_freed; else ++replies_freed;
    free(m); return 0;
}
static void set_source(void *p, unsigned int source) { message(p)->source = source; }
static unsigned int size(void *p) { return message(p)->size; }
static unsigned int source(void *p) { return message(p)->source; }
static int send(unsigned int destination, void *p) {
    assert(!pending_reply && message(p)->source == FUNCTIONAL_FACE_DMM_CP);
    pending_reply = p; pending_destination = destination; ++sent; return 0;
}
static struct functional_face_dmm_descriptor creator(unsigned int index) {
    struct functional_face_dmm_descriptor d = {
        .domain = 1, .unit = 0x1d9u + index, .owner = UINT64_C(0xfacec001) + index
    };
    return d;
}
static void setup(void) {
    assert(!functional_face_registry_callbacks(&callbacks));
    assert(!functional_face_dmm_enable(&callbacks));
}
/* Independent original mode-zero bodies from verified golden-op40.json. */
static const struct { unsigned int op; const char *hex; } request_goldens[] = {
    {0x20, "20000000d901000000000000ffffffff000000000000000000000000000000000000000000000000"},
    {0x21, "21000000d90100000284000000000000000000000000000000000000000000000000000000000000"},
    {0x23, "23000000000000000284000000000000000000003412000000000000000000000000000000000000"},
    {0x24, "240000000000000002840000ffffffff000000000000000000000000000000000000000000000000"},
    {0x25, "25000000000000000284000000000000000000000000000000000000000000000000000000000000"},
};
static struct functional_face_dmm_ticket operation(unsigned int op,
    const struct functional_face_dmm_descriptor *binding, int status) {
    const struct full_imaging_io io = {allocate, release, set_source, send, size, source, NULL};
    struct message *q = calloc(1, sizeof *q); assert(q);
    q->request = 1; q->source = 0x81cf6101u; q->size = 40;
    size_t index = 0;
    while (index < sizeof request_goldens / sizeof *request_goldens && request_goldens[index].op != op) ++index;
    assert(index < sizeof request_goldens / sizeof *request_goldens && strlen(request_goldens[index].hex) == 80);
    for (unsigned int i = 0; i < 40; ++i) {
        unsigned int byte;
        assert(sscanf(request_goldens[index].hex + i * 2, "%2x", &byte) == 1);
        q->wire[i] = (unsigned char)byte;
    }
    if (op == 0x20 || op == 0x21) put(q->wire + 0x04, binding->unit, 4);
    if (op != 0x20) put(q->wire + 0x08, binding->handle, 4);
    unsigned int body_token = op == 0x23 ? source(q->wire) & 0xffffu : 0;
    if (op == 0x23) put(q->wire + 0x14, body_token, 2);
    int rc = 7;
    assert(functional_face_dmm_dispatch(FUNCTIONAL_FACE_DMM_CP, q->wire, &io, 1, binding, &rc) == 1 && !rc);
    assert(pending_reply && pending_destination == 0x81cf6101u);
    struct functional_face_dmm_ticket ticket;
    assert(!functional_face_dmm_receive(pending_destination, pending_reply, &ticket));
    assert(get(ticket.wire, 2) == (op | 0x8000u));
    assert((int16_t)get(ticket.wire + 2, 2) == status && get(ticket.wire + 6, 2) == body_token);
    assert(functional_face_dmm_release_reply(pending_destination, pending_reply, &ticket, release, &rc) == 1 && !rc);
    pending_reply = NULL; return ticket;
}
static struct functional_face_registry_inspection inspect(const struct functional_face_dmm_descriptor *d) {
    struct functional_face_registry_inspection out;
    assert(!functional_face_registry_inspect_span(d, &out)); return out;
}
static void units_test(void) {
    struct dmm_service speech = {.physical = DMM_TEST_PHYSICAL};
    speech.memory = malloc(DMM_TEST_SIZE); assert(speech.memory);
    unsigned char q[40] = {0x20}, r[40]; put(q + 4, 0x63a, 4); put(q + 22, 1, 2);
    uint64_t speech_logical[2], speech_bytes[2];
    for (unsigned int i = 0; i < 2; ++i) {
        assert(!dmm_service_reply(&speech, q, 40, r));
        speech_logical[i] = get(r + 24, 4); speech_bytes[i] = get(r + 32, 4);
        assert(speech_logical[i] == UINT64_C(0x1e000000) + i * UINT64_C(0x80000) && speech_bytes[i] == 0x80000);
        speech.slots[i].creator_kind = DMM_CREATOR_SPEECH_INITIAL;
        assert(speech.slots[i].handle == 0x8400u + i && speech.slots[i].open_count == 1 &&
            speech.slots[i].allocation_epoch == i + 1);
    }
    for (size_t j = 0; j < DMM_TEST_SIZE; ++j) speech.memory[j] = (unsigned char)(j ^ (j >> 11) ^ 0x5a);
    struct dmm_service saved; memcpy(&saved, &speech, sizeof saved);
    unsigned char *saved_bytes = malloc(DMM_TEST_SIZE); assert(saved_bytes);
    memcpy(saved_bytes, speech.memory, DMM_TEST_SIZE);
    setup();
    struct functional_face_dmm_descriptor owners[3];
    for (unsigned int i = 0; i < 3; ++i) {
        struct functional_face_dmm_descriptor c = creator(i);
        owners[i] = operation(0x20, &c, 0).span;
        assert(owners[i].handle == 0x8402u + i && owners[i].epoch == i + 1);
        assert(owners[i].bytes == face_registry_sizes[i]);
        assert(owners[i].logical == FUNCTIONAL_FACE_REGISTRY_IOVA + i * FUNCTIONAL_FACE_REGISTRY_WINDOW);
        assert(owners[i].registration == i + 1 && owners[i].logical != owners[i].host_view);
        for (unsigned int j = 0; j < 2; ++j)
            assert(!face_registry_overlap(owners[i].logical, owners[i].mapped_bytes, speech_logical[j], speech_bytes[j]));
        assert(!face_registry_overlap(owners[i].logical, FUNCTIONAL_FACE_REGISTRY_WINDOW,
            UINT64_C(0x1e000000), UINT64_C(0xa00000)));
        assert(!face_registry_overlap(owners[i].logical, FUNCTIONAL_FACE_REGISTRY_WINDOW,
            UINT64_C(0x41e000000), UINT64_C(0xa00000)));
        for (unsigned int j = 0; j < i; ++j)
            assert(!face_registry_overlap(owners[i].logical, FUNCTIONAL_FACE_REGISTRY_WINDOW,
                owners[j].logical, FUNCTIONAL_FACE_REGISTRY_WINDOW));
        struct functional_face_registry_inspection view = inspect(&owners[i]);
        assert(!view.original.logical && !view.original.registration && !view.original.reference);
        struct functional_face_dmm_descriptor original = owners[i]; original.logical = 0; original.registration = 0;
        assert(face_registry_equal(&view.original, &original));
        assert(face_registry_equal(&view.current, &owners[i]));
        for (unsigned int j = 0; j < i; ++j)
            assert(!face_registry_overlap(owners[i].host_view, owners[i].mapped_bytes,
                owners[j].host_view, owners[j].mapped_bytes));
    }
    for (unsigned int i = 0; i < 3; ++i) {
        struct functional_face_dmm_descriptor owner = owners[i];
        struct functional_face_dmm_descriptor opened = operation(0x24, &owner, 0).span;
        struct functional_face_dmm_descriptor shared = operation(0x21, &owner, 0).span;
        assert(shared.reference && shared.reference != opened.reference);
        unsigned char *pattern = malloc(owner.bytes), *copy = malloc(owner.bytes); assert(pattern && copy);
        for (size_t j = 0; j < owner.bytes; ++j) pattern[j] = (unsigned char)((j * 29 + i * 97 + 23) ^ (j >> 7));
        struct functional_face_dmm_borrow writer, reader;
        struct functional_face_dmm_readback out;
        assert(!functional_face_dmm_borrowed_span(&opened, 0, owner.bytes,
            FUNCTIONAL_FACE_DMM_WRITE | FUNCTIONAL_FACE_DMM_TRANSFER, &writer));
        assert(writer.host_view == owner.host_view && writer.logical == owner.logical);
        assert(!functional_face_dmm_write(&writer, 0, pattern, owner.bytes, &out));
        assert(out.verified_bytes == owner.bytes && out.after_digest == hash(pattern, owner.bytes));
        assert(!functional_face_dmm_release_borrow(&writer, &out) && out.verified_bytes == owner.bytes);
        assert(!functional_face_dmm_borrowed_span(&opened, 0, owner.bytes, FUNCTIONAL_FACE_DMM_READ, &reader));
        assert(!functional_face_dmm_read(&reader, 0, copy, owner.bytes, &out));
        assert(out.verified_bytes == owner.bytes && out.after_digest == hash(pattern, owner.bytes));
        assert(!memcmp(pattern, copy, owner.bytes));
        printf("BYTES unit=%x bytes=%zu digest=%016" PRIx64 "\n", owner.unit, owner.bytes, out.after_digest);
        (void)operation(0x25, &opened, 0);
        (void)operation(0x25, &shared, 0);
        assert(functional_face_dmm_read(&reader, 0, copy, 1, &out) == -ESTALE);
        (void)operation(0x23, &owner, -1);
        assert(!callbacks.validate_span(callbacks.context, &owner));
        assert(functional_face_dmm_shutdown() == -EBUSY);
        assert(!functional_face_dmm_release_borrow(&reader, &out));
        struct functional_face_dmm_snapshot snapshot; assert(!functional_face_dmm_snapshot(&snapshot));
        assert(snapshot.units[i].verified_read_bytes == owner.bytes &&
            snapshot.units[i].verified_write_bytes == owner.bytes && !snapshot.units[i].borrows);
        (void)operation(0x23, &owner, 0);
        assert(callbacks.validate_span(callbacks.context, &owner) == -ESTALE);
        free(pattern); free(copy);
    }
    struct functional_face_dmm_snapshot snapshot; assert(!functional_face_dmm_snapshot(&snapshot));
    assert(snapshot.queued == 21 && snapshot.received == 21 && snapshot.request_freed == 21 &&
        snapshot.reply_freed == 21 && snapshot.ap_consumed == 18 && !snapshot.faults &&
        !snapshot.live_requests && !snapshot.live_replies);
    assert(!functional_face_dmm_shutdown());
    assert(!memcmp(&speech, &saved, sizeof speech) && !memcmp(speech.memory, saved_bytes, DMM_TEST_SIZE));
    assert(requests_freed == 21 && replies_freed == 21 && sent == 21);
    free(saved_bytes); free(speech.memory);
    puts("COUNTS units=3 write=514304 read=514304 requests=21 replies=21 received=21 consumed=18 speech_unchanged=1");
}
static struct functional_face_dmm_descriptor manual(unsigned int index) {
    struct functional_face_dmm_descriptor d = creator(index);
    d.handle = 0x8402u + index; d.epoch = 1; d.bytes = face_registry_sizes[index];
    d.mapped_bytes = (d.bytes + 4095) / 4096 * 4096;
    void *p = mmap(NULL, d.mapped_bytes, PROT_READ | PROT_WRITE, MAP_PRIVATE | MAP_ANONYMOUS, -1, 0);
    assert(p != MAP_FAILED); d.host_view = (uintptr_t)p; return d;
}
static void drop(const struct functional_face_dmm_descriptor *d) {
    assert(!munmap((void *)d->host_view, d->mapped_bytes));
}
static void reject_register(struct functional_face_dmm_descriptor d, int expected) {
    struct functional_face_dmm_descriptor before = d;
    assert(callbacks.register_span(callbacks.context, &d) == expected);
    assert(!memcmp(&before, &d, sizeof d));
}
static void shape_test(void) {
    assert(!functional_face_registry_callbacks(&callbacks));
    struct functional_face_dmm_descriptor d = manual(0), bad;
#define BAD(field, value, error) do { bad = d; bad.field = (value); reject_register(bad, (error)); } while (0)
    BAD(domain, 0, -EINVAL); BAD(unit, 0x1d8, -EINVAL); BAD(unit, 0x1dc, -EINVAL);
    BAD(handle, 0x8400, -EINVAL); BAD(handle, 0x8403, -EINVAL); BAD(handle, 0x8002, -EINVAL);
    BAD(handle, 0x18402, -EINVAL); BAD(handle, 0, -EINVAL);
    BAD(epoch, 0, -EINVAL); BAD(owner, 0, -EINVAL); BAD(reference, 1, -EINVAL);
    BAD(host_view, 0, -EINVAL); BAD(host_view, d.host_view + 1, -EINVAL);
    BAD(bytes, 0, -EMSGSIZE); BAD(bytes, d.bytes + 1, -EMSGSIZE); BAD(bytes, SIZE_MAX, -EMSGSIZE);
    BAD(mapped_bytes, 0, -EMSGSIZE); BAD(mapped_bytes, d.mapped_bytes - 4096, -EMSGSIZE);
    BAD(mapped_bytes, d.mapped_bytes + 4096, -EMSGSIZE); BAD(mapped_bytes, SIZE_MAX, -EMSGSIZE);
    BAD(logical, FUNCTIONAL_FACE_REGISTRY_IOVA, -EINVAL); BAD(logical, UINT64_MAX, -EINVAL);
    BAD(registration, 1, -EINVAL); BAD(host_view, UINTPTR_MAX - 4095, -EOVERFLOW);
    BAD(host_view, UINT64_C(0x1e000000), -EADDRINUSE);
    BAD(host_view, UINT64_C(0x1e080000), -EADDRINUSE);
    BAD(host_view, UINT64_C(0x1e9ff000), -EADDRINUSE);
    BAD(host_view, UINT64_C(0x41e080000), -EADDRINUSE);
    BAD(host_view, UINT64_C(0x41e9ff000), -EADDRINUSE);
    BAD(host_view, FUNCTIONAL_FACE_REGISTRY_IOVA, -EADDRINUSE);
    BAD(host_view, FUNCTIONAL_FACE_REGISTRY_IOVA - FUNCTIONAL_FACE_DMM_PAGE, -EADDRINUSE);
    BAD(host_view, UINT64_C(0x1dfff000), -EADDRINUSE);
    for (unsigned int i = 0; i < 3; ++i)
        BAD(host_view, FUNCTIONAL_FACE_REGISTRY_IOVA + i * FUNCTIONAL_FACE_REGISTRY_WINDOW, -EADDRINUSE);
#undef BAD
    assert(callbacks.register_span(callbacks.context, NULL) == -EINVAL);
    assert(callbacks.register_span(NULL, &d) == -EINVAL);
    assert(!callbacks.register_span(callbacks.context, &d));
    assert(!callbacks.validate_span(callbacks.context, &d));
    assert(!callbacks.unregister_span(callbacks.context, &d)); drop(&d);
}
static void identity_test(void) {
    assert(functional_face_registry_callbacks(NULL) == -EINVAL);
    assert(!functional_face_registry_callbacks(&callbacks));
    struct functional_face_dmm_descriptor d = manual(1), original = d;
    assert(!callbacks.register_span(callbacks.context, &d));
    struct functional_face_registry_inspection view = inspect(&d);
    assert(face_registry_equal(&view.original, &original) && face_registry_equal(&view.current, &d));
    assert(callbacks.validate_span(NULL, &d) == -EINVAL && callbacks.unregister_span(NULL, &d) == -EINVAL);
    assert(callbacks.validate_span(callbacks.context, NULL) == -ESTALE);
    assert(callbacks.unregister_span(callbacks.context, NULL) == -ESTALE);
    assert(functional_face_registry_inspect_span(&d, NULL) == -EINVAL);
    struct functional_face_registry_inspection unchanged; memset(&unchanged, 0x5a, sizeof unchanged);
    struct functional_face_registry_inspection out; memcpy(&out, &unchanged, sizeof out);
#define FORGE(field, value) do { \
    struct functional_face_dmm_descriptor forged = d; forged.field = (value); \
    assert(callbacks.validate_span(callbacks.context, &forged) == -ESTALE); \
    assert(callbacks.unregister_span(callbacks.context, &forged) == -ESTALE); \
    assert(functional_face_registry_inspect_span(&forged, &out) == -ESTALE); \
    assert(!memcmp(&out, &unchanged, sizeof out)); \
    assert(!callbacks.validate_span(callbacks.context, &d)); \
} while (0)
    FORGE(domain, 2); FORGE(unit, 0x1d9); FORGE(handle, d.handle ^ 0x400);
    FORGE(epoch, 2); FORGE(owner, d.owner + 1); FORGE(reference, 1);
    FORGE(logical, d.logical + 4096); FORGE(registration, d.registration + 1);
    FORGE(host_view, d.host_view + 4096); FORGE(bytes, d.bytes - 1); FORGE(mapped_bytes, d.mapped_bytes + 4096);
#undef FORGE
    assert(functional_face_registry_inspect_span(NULL, &out) == -ESTALE);
    assert(!memcmp(&out, &unchanged, sizeof out));
    reject_register(original, -EEXIST);
    struct functional_face_dmm_registry again;
    assert(!functional_face_registry_callbacks(&again) && again.context == callbacks.context);
    assert(!callbacks.validate_span(callbacks.context, &d));
    assert(!callbacks.unregister_span(callbacks.context, &d));
    assert(callbacks.unregister_span(callbacks.context, &d) == -ESTALE);
    assert(callbacks.validate_span(callbacks.context, &d) == -ESTALE);
    reject_register(original, -ESTALE);
    struct functional_face_dmm_descriptor fresh = original; ++fresh.epoch;
    assert(!callbacks.register_span(callbacks.context, &fresh));
    assert(fresh.registration > d.registration && fresh.logical == d.logical);
    assert(callbacks.validate_span(callbacks.context, &d) == -ESTALE);
    assert(!callbacks.unregister_span(callbacks.context, &fresh)); drop(&d);
}
static void overlap_test(void) {
    assert(!functional_face_registry_callbacks(&callbacks));
    struct functional_face_dmm_descriptor a = manual(0), b = manual(1);
    assert(!callbacks.register_span(callbacks.context, &a));
    struct functional_face_dmm_descriptor alias = b; alias.host_view = a.host_view;
    reject_register(alias, -EADDRINUSE);
    alias.host_view = a.host_view + a.mapped_bytes - 4096; reject_register(alias, -EADDRINUSE);
    alias = b; alias.logical = a.logical; reject_register(alias, -EINVAL);
    assert(!callbacks.register_span(callbacks.context, &b));
    assert(!callbacks.unregister_span(callbacks.context, &b));
    assert(!callbacks.unregister_span(callbacks.context, &a)); drop(&b); drop(&a);
}
static void generation_test(void) {
    setup(); struct functional_face_dmm_descriptor old = {0};
    struct functional_face_dmm_borrow old_borrow = {0};
    for (unsigned int i = 0; i < 32; ++i) {
        struct functional_face_dmm_descriptor c = creator(2);
        struct functional_face_dmm_descriptor d = operation(0x20, &c, 0).span;
        assert(d.epoch == i + 1 && d.handle == (0x8004u | ((i % 31 + 1) << 10)));
        if (!i) {
            old = d;
            assert(!functional_face_dmm_borrowed_span(&old, 0, 1, FUNCTIONAL_FACE_DMM_READ, &old_borrow));
            struct functional_face_dmm_readback out; assert(!functional_face_dmm_release_borrow(&old_borrow, &out));
        }
        if (i == 31) {
            assert(d.handle == old.handle && d.logical == old.logical && d.registration != old.registration);
            assert(callbacks.validate_span(callbacks.context, &old) == -ESTALE);
            struct functional_face_registry_inspection view;
            assert(functional_face_registry_inspect_span(&old, &view) == -ESTALE);
            struct functional_face_dmm_borrow borrow;
            assert(functional_face_dmm_borrowed_span(&old, 0, 1, FUNCTIONAL_FACE_DMM_READ, &borrow) == -ESTALE);
            struct functional_face_dmm_readback out; unsigned char byte = 0x5a;
            assert(functional_face_dmm_read(&old_borrow, 0, &byte, 1, &out) == -ESTALE && byte == 0x5a);
            (void)operation(0x24, &old, -5);
        }
        (void)operation(0x23, &d, 0);
    }
    assert(face_registry_registration == 32 && !functional_face_dmm_shutdown());
}
static void ranges_test(void) {
    setup(); struct functional_face_dmm_descriptor c = creator(2);
    struct functional_face_dmm_descriptor d = operation(0x20, &c, 0).span;
    struct functional_face_dmm_borrow borrow, before; memset(&before, 0x5a, sizeof before);
    memcpy(&borrow, &before, sizeof borrow);
    assert(functional_face_dmm_borrowed_span(&d, 0, 0, FUNCTIONAL_FACE_DMM_READ, &borrow) == -EINVAL);
    assert(functional_face_dmm_borrowed_span(&d, d.bytes, 1, FUNCTIONAL_FACE_DMM_READ, &borrow) == -ERANGE);
    assert(functional_face_dmm_borrowed_span(&d, 1, SIZE_MAX, FUNCTIONAL_FACE_DMM_READ, &borrow) == -ERANGE);
    assert(functional_face_dmm_borrowed_span(&d, SIZE_MAX, 1, FUNCTIONAL_FACE_DMM_READ, &borrow) == -ERANGE);
    assert(functional_face_dmm_borrowed_span(&d, 0, 1, 0, &borrow) == -EINVAL);
    assert(!memcmp(&borrow, &before, sizeof borrow));
    struct functional_face_dmm_readback out; unsigned char byte = 0xa9, read = 0;
    assert(!functional_face_dmm_borrowed_span(&d, d.bytes - 1, 1, FUNCTIONAL_FACE_DMM_WRITE, &borrow));
    assert(borrow.logical == d.logical + d.bytes - 1 && borrow.host_view == d.host_view + d.bytes - 1);
    assert(functional_face_dmm_write(&borrow, 0, &byte, 0, &out) == -EINVAL);
    assert(functional_face_dmm_write(&borrow, 1, &byte, 1, &out) == -ERANGE);
    assert(functional_face_dmm_write(&borrow, 0, &byte, SIZE_MAX, &out) == -ERANGE);
    assert(!functional_face_dmm_write(&borrow, 0, &byte, 1, &out));
    assert(!functional_face_dmm_release_borrow(&borrow, &out));
    assert(!functional_face_dmm_borrowed_span(&d, d.bytes - 1, 1, FUNCTIONAL_FACE_DMM_READ, &borrow));
    assert(!functional_face_dmm_read(&borrow, 0, &read, 1, &out) && read == byte);
    assert(!functional_face_dmm_release_borrow(&borrow, &out));
    (void)operation(0x23, &d, 0); assert(!functional_face_dmm_shutdown());
}
static void overflow_test(void) {
    assert(!functional_face_registry_callbacks(&callbacks));
    struct functional_face_dmm_descriptor a = manual(0), b = manual(1);
    face_registry_registration = UINT64_MAX - 1;
    assert(!callbacks.register_span(callbacks.context, &a) && a.registration == UINT64_MAX);
    reject_register(b, -EOVERFLOW);
    assert(!callbacks.unregister_span(callbacks.context, &a));
    assert(!functional_face_registry_callbacks(&callbacks));
    reject_register(b, -EOVERFLOW);
    assert(face_registry_registration == UINT64_MAX);
    drop(&a); drop(&b);
}
static void assert_busy(const struct functional_face_dmm_descriptor *d, int error) {
    struct functional_face_dmm_registry out, before; memset(&before, 0x5a, sizeof before); memcpy(&out, &before, sizeof out);
    assert(functional_face_registry_callbacks(&out) == error && !memcmp(&out, &before, sizeof out));
    struct functional_face_dmm_descriptor value = *d;
    assert(callbacks.register_span(callbacks.context, &value) == error && !memcmp(&value, d, sizeof value));
    assert(callbacks.validate_span(callbacks.context, d) == error);
    assert(callbacks.unregister_span(callbacks.context, d) == error);
    struct functional_face_registry_inspection inspection, saved;
    memset(&saved, 0x5a, sizeof saved); memcpy(&inspection, &saved, sizeof inspection);
    assert(functional_face_registry_inspect_span(d, &inspection) == error && !memcmp(&inspection, &saved, sizeof saved));
}
static void *contending(void *arg) { assert_busy(arg, -EBUSY); return NULL; }
static void concurrency_test(int child) {
    assert(!functional_face_registry_callbacks(&callbacks));
    struct functional_face_dmm_descriptor d = manual(0);
    assert(!REGISTRY_LOCK());
    assert_busy(&d, -EBUSY);
    if (child) {
        pid_t pid = fork(); assert(pid >= 0);
        if (!pid) { assert_busy(&d, -ECHILD); _exit(0); }
        int status; assert(waitpid(pid, &status, 0) == pid && WIFEXITED(status) && !WEXITSTATUS(status));
    } else {
        pthread_t thread; assert(!pthread_create(&thread, NULL, contending, &d));
        assert(!pthread_join(thread, NULL));
    }
    REGISTRY_UNLOCK();
    assert(!callbacks.register_span(callbacks.context, &d));
    assert(!callbacks.validate_span(callbacks.context, &d));
    assert(!callbacks.unregister_span(callbacks.context, &d)); drop(&d);
}
int main(int argc, char **argv) {
    assert(argc == 2);
    for (unsigned int i = 0; i < 3; ++i) {
        assert(!face_registry_entries[i].spans.current.registration && !face_registry_entries[i].last_epoch);
    }
    if (!strcmp(argv[1], "units")) units_test();
    else if (!strcmp(argv[1], "shape")) shape_test();
    else if (!strcmp(argv[1], "identity")) identity_test();
    else if (!strcmp(argv[1], "overlap")) overlap_test();
    else if (!strcmp(argv[1], "generation")) generation_test();
    else if (!strcmp(argv[1], "ranges")) ranges_test();
    else if (!strcmp(argv[1], "overflow")) overflow_test();
    else if (!strcmp(argv[1], "threads")) concurrency_test(0);
    else if (!strcmp(argv[1], "fork")) concurrency_test(1);
    else assert(0);
    printf("FACE_REGISTRY_PASS mode=%s\n", argv[1]); return 0;
}
