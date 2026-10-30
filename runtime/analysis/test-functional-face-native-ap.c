/* SPDX-License-Identifier: MIT */
/* HOST semantics only: reuse the real CP model/registry/runtime, not a native IO backend. */
#define main fixture_original_main
#include "test-functional-face-runtime.c"
#undef main
#include <limits.h>
#include <sys/mman.h>
#include "functional-face-native-ap.h"

struct native_model {
    struct functional_face_ap_observer observer;
    struct functional_face_native_ap_reference birth, current;
    struct functional_face_native_ap_operation dropped;
    struct functional_face_native_ap context;
    struct functional_face_ap_provider provider;
    struct functional_face_ap_borrow token;
    unsigned char *data, *expected, *sdk_pages, *mailer_pages;
    uint32_t sdk_count, cp_pages;
    int scatter, set_target, set_error, scatter_alias, mapping_mutation, cp_mutation;
    uint64_t writer_lease, writer_sequence, address, physical;
    size_t actual_read;
    unsigned int calls[4], writer_calls, mapping_calls, physical_calls, freed, producer_frees, end_calls;
    int fail_op, fail_status, uncertain_op, callback_error, corrupt_ticket, map_error, alias, extent_error;
    int mutate, read_error, drop_on_read, reentry, writer_missing;
    long read_value;
};
static uint64_t model_next_lease = 1000;
static unsigned int cp_writer_releases, cp_reader_releases;
int __real_functional_face_dmm_release_borrow(const struct functional_face_dmm_borrow *, struct functional_face_dmm_readback *);
int __wrap_functional_face_dmm_release_borrow(const struct functional_face_dmm_borrow *b, struct functional_face_dmm_readback *r) {
    int rc = __real_functional_face_dmm_release_borrow(b, r);
    if (!rc) { if (b->access & FUNCTIONAL_FACE_DMM_WRITE) ++cp_writer_releases; else ++cp_reader_releases; }
    return rc;
}
static void model_wire(unsigned char *q, unsigned int op, uint32_t unit, uint32_t handle) {
    size_t i = 0;
    while (i < sizeof request_goldens / sizeof *request_goldens && request_goldens[i].op != op) ++i;
    assert(i < sizeof request_goldens / sizeof *request_goldens);
    for (size_t j = 0; j < 40; ++j) {
        unsigned int byte; assert(sscanf(request_goldens[i].hex + 2 * j, "%2x", &byte) == 1);
        q[j] = (unsigned char)byte;
    }
    if (op == 0x20 || op == 0x21) put(q + 4, unit, 4);
    if (op != 0x20) put(q + 8, handle, 4);
    if (op == 0x23) put(q + 20, QUEUE & 0xffffu, 2);
}
static void model_transaction(struct native_model *m, unsigned int op, struct functional_face_native_ap_operation *out) {
    unsigned char *q = malloc(40), *r = calloc(1, 40); assert(q && r);
    model_wire(q, op, m->birth.span.unit, m->birth.span.handle);
    out->before = m->current;
    int status = 0;
    if (m->fail_op == (int)op) status = m->fail_status ? m->fail_status : -0x3301;
    else if (op == 0x21) { assert(m->current.owners && m->current.owners < 255); ++m->current.owners; }
    else if (op == 0x24) { assert(m->current.opens < 255); ++m->current.opens; m->current.state = 2; }
    else if (op == 0x25) { assert(m->current.opens); if (!--m->current.opens) m->current.state = 1; }
    else if (op == 0x23) {
        assert(m->current.owners);
        if (--m->current.owners == 0) {
            if (m->current.state == 2 || m->current.state == 3) status = 3;
            m->current.state = m->current.opens = m->current.shares = 0;
            m->current.extent_identity = 0;
            assert(m->data && !m->freed); free(m->data); m->data = NULL; ++m->freed;
        }
    }
    put(r, op | 0x8000u, 2); put(r + 2, (uint16_t)status, 2); put(r + 12, m->birth.span.handle, 4);
    if (op == 0x21) { put(r + 24, UINT64_MAX, 8); put(r + 32, 1, 4); }
    if (op == 0x24) {
        put(r + 8, 1, 2); put(r + 24, m->address, 8); put(r + 32, m->birth.span.bytes, 4);
        if (m->extent_error == 1) put(r + 8, 2, 2);
        if (m->extent_error == 2) put(r + 12, m->birth.span.handle ^ 1u, 4);
        if (m->extent_error == 3) put(r + 32, m->birth.span.bytes - 1, 4);
        if (m->extent_error == 4) put(r + 24, UINT64_MAX - 8, 8);
        if (m->extent_error == 5) put(r + 8, 0, 2);
    }
    assert(functional_face_ap_begin(&m->observer, 1, 1, THREAD_ID(), FUNCTIONAL_FACE_AP_DMM, QUEUE, q, 40, NULL) == 1);
    functional_face_ap_sent(&m->observer, THREAD_ID(), m->uncertain_op == (int)op ? -ETIMEDOUT : 0, NULL);
    functional_face_ap_received(&m->observer, THREAD_ID(), QUEUE, FUNCTIONAL_FACE_AP_DMM, r, 40, 0, NULL);
    functional_face_ap_freed(&m->observer, THREAD_ID(), QUEUE, r, 0, NULL);
    out->observed = m->observer; out->after = m->current;
    free(q); free(r);
}
static int model_operation(void *p, uint32_t op, const struct functional_face_native_ap_input *input,
    struct functional_face_native_ap_operation *out) {
    struct native_model *m = p;
    assert(input->unit == m->birth.span.unit && !input->chip && input->handle == m->birth.span.handle);
    size_t i = op == 0x21 ? 0 : op == 0x24 ? 1 : op == 0x25 ? 2 : 3;
    assert(op == 0x21 || op == 0x24 || op == 0x25 || op == 0x23); ++m->calls[i];
    if (op == 0x23) assert(!m->context.open_live);
    model_transaction(m, op, out);
    if (m->corrupt_ticket && op == 0x21) {
        switch (m->corrupt_ticket) {
            case 1: out->observed.reply_source ^= 1; break;
            case 2: out->observed.request_wire[22] = 1; break;
            case 3: out->observed.reply_wire[2] = 1; break;
            case 4: out->observed.received = 0; break;
            case 5: out->observed.free_result = -EIO; break;
            case 6: out->observed.reply_bytes = 39; break;
            case 7: out->observed.sender_tid++; break;
            case 8: out->observed.sequence = m->birth.birth_sequence; break;
            case 9: out->observed.request_wire[4] ^= 1; break;
            case 10: out->observed.request_wire[8] ^= 1; break;
            case 11: out->observed.free_attempts = 2; break;
            case 12: out->observed.send_result = 1; break;
            case 13: out->observed.reply_wire[0] ^= 1; break;
            case 14: out->observed.owner_pid++; break;
            case 15: out->observed.births[m->birth.span.unit - 0x1d9].ambiguous = 1; break;
            case 16: out->observed.births[m->birth.span.unit - 0x1d9].observation_sequence++; break;
            case 17: out->after.owners++; break;
            case 18: out->after.allocation_sequence++; break;
            case 19: out->after.owners = 0; break;
            default: abort();
        }
    }
    return m->callback_error && op == 0x21 ? m->callback_error : 0;
}
static int model_writer(void *p, enum functional_face_native_ap_writer_action action,
    const struct functional_face_ap_birth *birth, const struct functional_face_native_ap_reference *saved,
    const struct functional_face_native_ap_writer *prior, struct functional_face_native_ap_writer *out) {
    struct native_model *m = p; ++m->writer_calls;
    assert(birth->observation_sequence == m->birth.birth_sequence && saved->span.epoch == m->birth.span.epoch);
    if (m->writer_missing) return -ENODATA;
    if (action == FACE_NATIVE_AP_WRITER_BEGIN) assert(!prior);
    else assert(prior && prior->lease == m->writer_lease);
    *out = (struct functional_face_native_ap_writer){.current = m->current, .lease = m->writer_lease,
        .writer_identity = 0x35150c4, .completion_identity = 0x3514c88,
        .writer_sequence = m->writer_sequence, .completed_sequence = m->writer_sequence,
        .producer_drop = m->dropped};
    if (action == FACE_NATIVE_AP_WRITER_END) ++m->end_calls;
    return 0;
}
static struct functional_face_native_ap_range model_range(uint64_t offset, uint64_t n) {
    return (struct functional_face_native_ap_range){1, offset, n};
}
static struct functional_face_native_ap_range_set model_single(struct functional_face_native_ap_range r) {
    return (struct functional_face_native_ap_range_set){.count = 1, .ranges = {r}};
}
static void model_scatter(struct functional_face_native_ap_range_set *s, uint32_t count, uint64_t base) {
    assert(count && count <= FUNCTIONAL_FACE_NATIVE_AP_MAX_RANGES);
    s->count = count;
    for (uint32_t i = 0; i < count; ++i) s->ranges[i] = model_range(base + i * 8192u, 4096);
}
static void model_bad_set(struct functional_face_native_ap_range_set *s, int error) {
    struct functional_face_native_ap_range *last = &s->ranges[s->count - 1];
    switch (error) {
        case 1: s->count = 0; break;
        case 2: s->count = FUNCTIONAL_FACE_NATIVE_AP_MAX_RANGES + 1; break;
        case 3: last->bytes = 0; break;
        case 4: last->backing = 0; break;
        case 5: last->offset = UINT64_MAX - 1; break;
        case 6: *last = s->ranges[0]; break;
        case 7: *last = s->ranges[0]; last->offset += 2048; break;
        case 8:
            s->count = 2; s->ranges[0] = (struct functional_face_native_ap_range){2, 0, UINT64_MAX - 4095};
            s->ranges[1] = (struct functional_face_native_ap_range){3, 0, 8192}; break;
        case 9: --s->count; break;
        case 10: s->ranges[s->count++] = model_range(last->offset + 8192, 4096); break;
        case 11: --last->bytes; break;
        case 12: ++last->offset; break;
        case 13: ++s->ranges[0].bytes; --last->bytes; break;
        case 14: last->bytes = 0x100; break;
        default: abort();
    }
}
static int model_mapping(void *p, const struct functional_face_native_ap_reference *ref, uint64_t address,
    size_t bytes, const struct functional_face_dmm_descriptor *d, struct functional_face_native_ap_mapping_proof *out) {
    struct native_model *m = p; ++m->mapping_calls;
    assert(ref->span.epoch == m->birth.span.epoch && address == m->address && bytes == m->birth.span.bytes);
    if (m->map_error) return m->map_error;
    /* HOST canonical storage only, never Sony PFNs: scatter offsets label each
     * actually owned SDK/mailer page and EVERY registry mmap page in VA order. */
    out->mapping = (struct functional_face_native_ap_mapping){.lease = m->writer_lease, .address = address,
        .physical = m->physical, .source = model_range((uintptr_t)m->data, bytes),
        .sdk = model_single(model_range((uintptr_t)&m->birth, sizeof m->birth)),
        .mailer = model_single(model_range((uintptr_t)&m->observer, sizeof m->observer))};
    if (m->scatter) {
        assert(m->sdk_pages && m->mailer_pages);
        out->mapping.source.offset = 0x10000000;
        model_scatter(&out->mapping.sdk, m->sdk_count, 0x20000000);
        model_scatter(&out->mapping.mailer, 16, 0x30000000);
        if (m->scatter == 4) model_scatter(&out->mapping.sdk, m->sdk_count, 0x40001000);
        if (m->scatter == 5) model_scatter(&out->mapping.mailer, 16, 0x20001000);
        if (m->scatter == 6) out->mapping.sdk.ranges[m->sdk_count - 1].offset = UINT64_MAX - 4096;
    }
    if (m->alias == 2) out->mapping.sdk = model_single(out->mapping.source);
    if (m->alias == 3) out->mapping.mailer = model_single(out->mapping.source);
    if (m->alias == 4) out->mapping.source.offset = UINT64_MAX - 1;
    struct functional_face_native_ap_range_set *sdk = &out->mapping.sdk, *mailer = &out->mapping.mailer;
    if (m->scatter_alias == 1) sdk->ranges[sdk->count - 1] = out->mapping.source;
    if (m->scatter_alias == 2) mailer->ranges[mailer->count - 1] = out->mapping.source;
    if (m->scatter_alias == 3) mailer->ranges[mailer->count - 1] = sdk->ranges[sdk->count - 1];
    if (m->mapping_mutation) {
        struct functional_face_native_ap_range_set *changed = m->mapping_mutation <= 5 ? sdk : mailer;
        struct functional_face_native_ap_range *last = &changed->ranges[changed->count - 1];
        switch ((m->mapping_mutation - 1) % 5) {
            case 0: last->offset += 65536; break;
            case 1: --changed->count; break;
            case 2: { struct functional_face_native_ap_range first = changed->ranges[0];
                changed->ranges[0] = *last; *last = first; break; }
            case 3: ++last->backing; break;
            case 4: --last->bytes; break;
            default: abort();
        }
    }
    if (m->set_error && m->set_target < 2) model_bad_set(m->set_target ? mailer : sdk, m->set_error);
    if (d) {
        out->destination = *d; out->cp = model_single(model_range(d->host_view, d->mapped_bytes));
        if (m->scatter) {
            assert(!(d->host_view & 4095u) && !(d->mapped_bytes & 4095u));
            model_scatter(&out->cp, (uint32_t)(d->mapped_bytes / 4096), 0x40000000);
            if (m->scatter == 2) {
                /* This model assigns consecutive canonical pages to VA pages 0/1. */
                out->cp.ranges[0].bytes = 8192;
                for (uint32_t i = 1; i + 1 < out->cp.count; ++i) out->cp.ranges[i] = out->cp.ranges[i + 1];
                --out->cp.count;
            }
            if (m->scatter == 3) for (uint32_t i = 0; i < out->cp.count; ++i) {
                out->cp.ranges[i].backing = 1u + (i & 1u);
                out->cp.ranges[i].offset = 0x40000000 + (i / 2u) * 8192u;
            }
        }
        if (m->cp_mutation == 1) out->cp.ranges[out->cp.count - 1].offset += 65536;
        if (m->cp_mutation == 2) ++out->cp.ranges[out->cp.count - 1].backing;
        if (m->cp_mutation == 3) {
            struct functional_face_native_ap_range first = out->cp.ranges[0];
            out->cp.ranges[0] = out->cp.ranges[out->cp.count - 1]; out->cp.ranges[out->cp.count - 1] = first;
        }
        if (m->cp_mutation == 4) { out->cp.ranges[0].bytes += 4096; --out->cp.count; }
        struct functional_face_native_ap_range *last = &out->cp.ranges[out->cp.count - 1];
        if (m->alias == 1 || m->scatter_alias == 4)
            last->offset = (out->mapping.source.offset + bytes - 1) & ~UINT64_C(4095);
        if (m->alias == 5) ++out->destination.registration;
        if (m->scatter_alias == 5) *last = sdk->ranges[sdk->count - 1];
        if (m->scatter_alias == 6) *last = mailer->ranges[mailer->count - 1];
        if (m->set_error && m->set_target == 2) model_bad_set(&out->cp, m->set_error);
        m->cp_pages = out->cp.count;
    }
    return 0;
}
static long model_read(void *p, const struct functional_face_native_ap_mapping *mapping,
    uint64_t physical, void *out, size_t bytes) {
    struct native_model *m = p; ++m->physical_calls;
    assert(m->data && m->current.owners && m->context.owner_live && m->context.open_live);
    assert(mapping->physical == m->physical && physical >= m->physical);
    assert(physical - m->physical <= m->birth.span.bytes && bytes <= m->birth.span.bytes - (physical - m->physical));
    assert(bytes <= 4096 - (physical & 4095u));
    if (m->reentry) {
        struct functional_face_ap_borrow b = {0};
        assert(m->provider.acquire(m->provider.context, &m->birth.span, 0, m->birth.span.bytes, &b) == -EBUSY);
        assert(m->provider.release(m->provider.context, &m->token) == -EBUSY);
    }
    if (m->read_error) {
        if (m->read_value > 0 && (unsigned long)m->read_value <= bytes) {
            memcpy(out, m->data + physical - m->physical, (size_t)m->read_value);
            m->actual_read += (size_t)m->read_value;
        }
        return m->read_value;
    }
    memcpy(out, m->data + physical - m->physical, bytes); m->actual_read += bytes;
    if (m->drop_on_read && !m->producer_frees) {
        assert(m->current.owners == 2);
        model_transaction(m, 0x23, &m->dropped); ++m->producer_frees;
        assert(m->current.owners == 1 && m->data && !m->freed && !get(m->dropped.observed.reply_wire + 2, 2));
    }
    if (m->mutate == 1) ++m->current.generation;
    if (m->mutate == 2) ++m->writer_sequence;
    if (m->mutate == 3) ++m->current.allocation_sequence;
    if (m->mutate == 4) --m->current.owners; /* No actual original drop receipt. */
    return (long)bytes;
}
static const struct functional_face_native_ap_ops model_ops = {model_operation, model_read, model_mapping, model_writer};
static void model_setup(struct native_model *m, unsigned int index) {
    memset(m, 0, sizeof *m);
    size_t bytes = index == 0 ? 0x64000u : index == 1 ? 0xc800u : 0xd100u;
    m->data = malloc(bytes); m->expected = malloc(bytes); assert(m->data && m->expected);
    for (size_t i = 0; i < bytes; ++i) m->data[i] = (unsigned char)((i * 37 + index * 53 + 11) ^ (i >> 7));
    memcpy(m->expected, m->data, bytes);
    m->writer_lease = ++model_next_lease; m->writer_sequence = 0x12345;
    m->address = UINT64_C(0x8d0012345678000); m->physical = UINT64_C(0x22000ff1);
    unsigned char q[40], r[40] = {0}; model_wire(q, 0x20, 0x1d9 + index, 0);
    put(r, 0x8020, 2); put(r + 12, 0x400u + index, 4);
    assert(functional_face_ap_begin(&m->observer, 1, 1, THREAD_ID(), FUNCTIONAL_FACE_AP_DMM, QUEUE, q, 40, NULL) == 1);
    functional_face_ap_sent(&m->observer, THREAD_ID(), 0, NULL);
    functional_face_ap_received(&m->observer, THREAD_ID(), QUEUE, FUNCTIONAL_FACE_AP_DMM, r, 40, 0, NULL);
    functional_face_ap_freed(&m->observer, THREAD_ID(), QUEUE, r, 0, NULL);
    m->birth = (struct functional_face_native_ap_reference){
        .span = {0, 0x1d9 + index, 0x400u + index, 0x9000u + index, OWNER ^ 0x55aa, bytes},
        .birth_sequence = m->observer.sequence, .unit_identity = 0x120000 + index * 128,
        .extent_identity = 0x180000 + index * 128, .allocation_sequence = 0x101 + index,
        .generation = 1, .state = 1, .owners = 1};
    m->current = m->birth;
}
static void model_bind(struct native_model *m) {
    assert(!functional_face_native_ap_init(&m->context, &model_ops, m, &m->observer, &m->birth, &m->provider));
}
static int model_acquire(struct native_model *m) {
    return m->provider.acquire(m->provider.context, &m->birth.span, 0, m->birth.span.bytes, &m->token);
}
static void model_enable_scatter(struct native_model *m) {
    m->scatter = 1; m->sdk_count = 3;
    m->sdk_pages = mmap(NULL, FUNCTIONAL_FACE_NATIVE_AP_MAX_RANGES * 4096u, PROT_READ | PROT_WRITE,
        MAP_PRIVATE | MAP_ANONYMOUS, -1, 0);
    m->mailer_pages = mmap(NULL, 16 * 4096, PROT_READ | PROT_WRITE, MAP_PRIVATE | MAP_ANONYMOUS, -1, 0);
    assert(m->sdk_pages != MAP_FAILED && m->mailer_pages != MAP_FAILED);
    memset(m->sdk_pages, 0x5a, FUNCTIONAL_FACE_NATIVE_AP_MAX_RANGES * 4096u);
    memset(m->mailer_pages, 0xa5, 16 * 4096);
}
static void model_destroy(struct native_model *m) {
    free(m->data); free(m->expected);
    if (m->sdk_pages) assert(!munmap(m->sdk_pages, FUNCTIONAL_FACE_NATIVE_AP_MAX_RANGES * 4096u));
    if (m->mailer_pages) assert(!munmap(m->mailer_pages, 16 * 4096));
}
static void assert_sticky(struct native_model *m) {
    unsigned int before[4]; memcpy(before, m->calls, sizeof before);
    unsigned int writers = m->writer_calls, maps = m->mapping_calls, reads = m->physical_calls;
    struct functional_face_ap_borrow b; memset(&b, 0xa5, sizeof b); struct functional_face_ap_borrow saved = b;
    assert(m->context.faulted && m->context.source_live);
    assert(m->provider.acquire(m->provider.context, &m->birth.span, 0, m->birth.span.bytes, &b) == -EIO);
    assert(!memcmp(&b, &saved, sizeof b));
    assert(m->provider.release(m->provider.context, &m->token) == -EIO);
    assert(!memcmp(before, m->calls, sizeof before));
    assert(writers == m->writer_calls && maps == m->mapping_calls && reads == m->physical_calls);
}
static void native_positive(int scatter) {
    struct dmm_service speech = {.physical = DMM_TEST_PHYSICAL};
    speech.memory = malloc(DMM_TEST_SIZE); assert(speech.memory);
    for (size_t i = 0; i < DMM_TEST_SIZE; ++i) speech.memory[i] = (unsigned char)(i ^ (i >> 9) ^ 0x95);
    unsigned char q[40] = {0x20}, r[40]; put(q + 4, 0x63a, 4); put(q + 22, 1, 2);
    for (unsigned int i = 0; i < 2; ++i) {
        assert(!dmm_service_reply(&speech, q, 40, r)); speech.slots[i].creator_kind = DMM_CREATOR_SPEECH_INITIAL;
        assert(speech.slots[i].handle == 0x8400u + i && speech.slots[i].open_count == 1);
    }
    struct dmm_service saved_speech = speech; uint64_t speech_digest = hash(speech.memory, DMM_TEST_SIZE);
    setup(); size_t total = 0;
    for (unsigned int i = 0; i < 3; ++i) {
        struct functional_face_dmm_descriptor d = create(0x1d9 + i);
        struct native_model m; model_setup(&m, i);
        if (scatter) model_enable_scatter(&m);
        model_bind(&m); m.drop_on_read = 1;
        struct functional_face_transfer s = {0}; assert(!functional_face_transfer_init(&s, &m.provider));
        struct functional_face_transfer_input input = {m.birth.span.handle, 0, d.handle, 0, (uint32_t)d.bytes};
        unsigned int old_writes = cp_writer_releases, old_reads = cp_reader_releases;
        assert(!functional_face_transfer_copy(&s, OWNER, &m.birth.span, &d, &input));
        assert(s.last.content_complete && s.last.destination_acquired == 2 && s.last.source_released && s.last.destination_released);
        assert(s.last.written == d.bytes && s.last.readback == d.bytes && m.actual_read == d.bytes);
        assert(s.last.source_digest == hash(m.expected, d.bytes) && s.last.destination_digest == s.last.source_digest);
        assert(cp_writer_releases == old_writes + 1 && cp_reader_releases == old_reads + 1);
        assert(m.calls[0] == 1 && m.calls[1] == 1 && m.calls[2] == 1 && m.calls[3] == 1);
        assert(m.producer_frees == 1 && m.freed == 1 && !m.data && m.context.producer_dropped);
        assert(!m.context.source_live && !m.context.owner_live && !m.context.open_live && !m.context.writer_live && !m.context.faulted);
        struct functional_face_dmm_borrow b; struct functional_face_dmm_readback rb;
        assert(!functional_face_runtime_borrow_destination(OWNER, d.unit, d.handle, &d, 0, d.bytes, FUNCTIONAL_FACE_DMM_READ, &b));
        unsigned char *actual = malloc(d.bytes); assert(actual);
        assert(!functional_face_dmm_read(&b, 0, actual, d.bytes, &rb));
        assert(rb.verified_bytes == d.bytes && !memcmp(actual, m.expected, d.bytes));
        assert(!__real_functional_face_dmm_release_borrow(&b, &rb)); free(actual);
        printf("NATIVE_HOST_BYTES unit=%x bytes=%zu digest=%016" PRIx64 " owner=1:2:1:0 physical_calls=%u\n",
            d.unit, d.bytes, hash(m.expected, d.bytes), m.physical_calls);
        total += d.bytes;
        if (scatter) {
            assert(m.cp_pages == d.mapped_bytes / 4096 && m.context.mapping.sdk.count == 3 && m.context.mapping.mailer.count == 16);
            printf("NATIVE_HOST_SCATTER unit=%x cp_pages=%u mapped_bytes=%zu sdk_ranges=3 mailer_ranges=16 host_canonical_only=1\n",
                d.unit, m.cp_pages, d.mapped_bytes);
        } else assert(m.cp_pages == 1 && m.context.mapping.sdk.count == 1 && m.context.mapping.mailer.count == 1);
        (void)operation(0x23, d.unit, d.handle, 0, 0); model_destroy(&m);
    }
    assert(total == 514304 && cp_writer_releases == 3 && cp_reader_releases == 3);
    assert(!functional_face_runtime_snapshot(&diagnostic));
    assert(!diagnostic.live_creators && !diagnostic.faults && !diagnostic.retained && !diagnostic.opens && !diagnostic.shares);
    assert(diagnostic.actual_receive == 6 && diagnostic.actual_request_free == 6 && diagnostic.actual_reply_free == 6);
    assert(!memcmp(&speech, &saved_speech, sizeof speech) && hash(speech.memory, DMM_TEST_SIZE) == speech_digest);
    assert(!functional_face_dmm_shutdown()); free(speech.memory);
    puts("NATIVE_HOST_COUNTS units=3 source_read=514304 cp_write=514304 cp_internal_read=514304 independent_read=514304 write_leases=3 read_leases=3 extra_owner=3 open=3 close=3 balance=3 producer_free=3 backing_free=3 cp_receive=6 cp_request_free=6 cp_reply_free=6 speech_bytes=1048576 speech_unchanged=1 native_io_bound=0");
}
static void native_owner_life(void) {
    struct native_model m; model_setup(&m, 1); model_bind(&m); assert(!model_acquire(&m));
    assert(m.current.owners == 2 && m.current.opens == 1 && !m.freed);
    m.drop_on_read = 1; unsigned char out[4096];
    assert(m.provider.read(&m.context, &m.token, 0, out, sizeof out) == (long)sizeof out);
    assert(m.current.owners == 1 && m.data && !m.freed && m.context.producer_dropped);
    assert(!memcmp(out, m.expected, sizeof out));
    assert(!m.provider.release(&m.context, &m.token)); assert(m.freed == 1 && !m.current.owners && !m.data);
    assert(m.calls[2] == 1 && m.calls[3] == 1 && m.end_calls == 1); model_destroy(&m);
    /* A retained ordinary original open makes last Free return literal 3.
     * The extra owner still protects bytes until our own close/balance. */
    model_setup(&m, 1); m.current.opens = 1; m.current.state = 2; model_bind(&m);
    assert(!model_acquire(&m)); m.drop_on_read = 1;
    assert(m.provider.read(&m.context, &m.token, 0, out, sizeof out) == (long)sizeof out);
    assert(!m.provider.release(&m.context, &m.token) && m.freed == 1);
    assert(get(m.context.operations[3].observed.reply_wire + 2, 2) == 3);
    assert(!m.context.faulted && !m.context.source_live); model_destroy(&m);
}
static void native_birth_rejections(void) {
    for (unsigned int i = 0; i < 13; ++i) {
        struct native_model m; model_setup(&m, 0);
        if (i == 0) ++m.birth.span.handle;
        if (i == 1) ++m.birth.span.unit;
        if (i == 2) ++m.birth.generation;
        if (i == 3) m.birth.span.owner = 0;
        if (i == 4) m.birth.span.epoch = 0;
        if (i == 5) ++m.birth.birth_sequence;
        if (i == 6) m.birth.owners = 0;
        if (i == 7) m.birth.owners = 255;
        if (i == 8) m.birth.allocation_sequence = 0;
        if (i == 9) m.observer.births[0].ambiguous = 1;
        if (i == 10) m.observer.births[0].any_free_observed = 1;
        if (i == 11) m.observer.births[0].observations = 2;
        if (i == 12) m.birth.span.bytes++;
        struct functional_face_ap_provider out; memset(&out, 0xa5, sizeof out); struct functional_face_ap_provider old = out;
        assert(functional_face_native_ap_init(&m.context, &model_ops, &m, &m.observer, &m.birth, &out) < 0);
        assert(!memcmp(&out, &old, sizeof out) && !m.calls[0] && !m.writer_calls); model_destroy(&m);
    }
    for (unsigned int i = 0; i < 4; ++i) {
        struct native_model m; model_setup(&m, 1); model_bind(&m);
        struct functional_face_ap_span wrong = m.birth.span;
        if (i == 0) ++wrong.owner;
        if (i == 1) ++wrong.epoch;
        if (i == 2) ++wrong.unit;
        if (i == 3) ++wrong.handle;
        assert(m.provider.acquire(&m.context, &wrong, 0, wrong.bytes, &m.token) == -ESTALE);
        assert(!m.calls[0] && !m.writer_calls); model_destroy(&m);
    }
    for (unsigned int i = 0; i < 2; ++i) {
        struct native_model m; model_setup(&m, 1); model_bind(&m); m.current.owners = i ? 255 : 0;
        assert(model_acquire(&m) == -ESTALE && !m.calls[0] && !m.calls[3]);
        assert(m.context.faulted && m.context.writer_live && !m.context.source_live); model_destroy(&m);
    }
}
static void native_missing(void) {
    for (unsigned int i = 0; i < 5; ++i) {
        struct native_model m; model_setup(&m, 1); struct functional_face_native_ap_ops ops = model_ops;
        if (i == 0) ops.original_native_operation = NULL;
        if (i == 1) ops.read_physical = NULL;
        if (i == 2) ops.prove_mapping_and_disjoint = NULL;
        if (i == 3) ops.source_writer_serial = NULL;
        if (i < 4) assert(functional_face_native_ap_init(&m.context, &ops, &m, &m.observer, &m.birth, &m.provider) == -ENODATA);
        else { model_bind(&m); m.writer_missing = 1; assert(model_acquire(&m) == -ENODATA); }
        assert(!m.calls[0] && !m.context.candidate_capability && !m.context.source_live); model_destroy(&m);
    }
}
static void native_tickets(void) {
    for (int i = 1; i <= 19; ++i) {
        struct native_model m; model_setup(&m, 1); model_bind(&m); m.corrupt_ticket = i;
        struct functional_face_ap_borrow out; memset(&out, 0xa5, sizeof out); struct functional_face_ap_borrow old = out;
        assert(m.provider.acquire(&m.context, &m.birth.span, 0, m.birth.span.bytes, &out) < 0);
        assert(!memcmp(&out, &old, sizeof out)); assert_sticky(&m);
        assert(m.current.owners == 2 && m.calls[0] == 1 && !m.calls[1] && !m.calls[3] && m.context.uncertain);
        model_destroy(&m);
    }
}
static void native_transport(void) {
    for (int i = 0; i < 4; ++i) {
        struct native_model m; model_setup(&m, 1); model_bind(&m);
        if (i < 2) m.uncertain_op = i ? 0x24 : 0x21;
        else m.callback_error = i == 2 ? -ETIMEDOUT : 1;
        assert(model_acquire(&m) < 0); assert_sticky(&m);
        assert(m.current.owners == 2 && m.calls[0] == 1 && !m.calls[2] && !m.calls[3]); model_destroy(&m);
    }
}
static void native_balanced_failure(int query) {
    struct native_model m; model_setup(&m, 1); model_bind(&m);
    if (query) m.fail_op = 0x24; else m.map_error = -ENODATA;
    assert(model_acquire(&m) == (query ? -EREMOTEIO : -ENODATA));
    assert(!m.context.source_live && !m.context.faulted && !m.context.writer_live);
    assert(m.calls[0] == 1 && m.calls[1] == 1 && m.calls[2] == (unsigned int)!query && m.calls[3] == 1);
    assert(m.current.owners == 1 && !m.current.opens && m.data && !m.freed && m.end_calls == 1);
    assert(model_acquire(&m) == -EALREADY && m.calls[0] == 1); model_destroy(&m);
    if (!query) {
        model_setup(&m, 1); model_bind(&m); m.map_error = -ENODATA; m.fail_op = 0x25;
        struct functional_face_ap_borrow out; memset(&out, 0xa5, sizeof out);
        struct functional_face_ap_borrow old = out;
        assert(m.provider.acquire(&m.context, &m.birth.span, 0, m.birth.span.bytes, &out) == -ENODATA);
        assert(!memcmp(&out, &old, sizeof out) && m.context.cleanup_error < 0);
        assert_sticky(&m); assert(m.calls[2] == 1 && !m.calls[3] && m.current.owners == 2); model_destroy(&m);
    }
}
static void native_release_failure(int close) {
    const int statuses[] = {-0x3301, 1, 3};
    for (size_t i = 0; i < sizeof statuses / sizeof *statuses; ++i) {
        struct native_model m; model_setup(&m, 1); model_bind(&m); assert(!model_acquire(&m));
        m.fail_op = close ? 0x25 : 0x23; m.fail_status = statuses[i];
        assert(m.provider.release(&m.context, &m.token) < 0); assert_sticky(&m);
        assert(m.current.owners == 2 && m.data && !m.freed && m.context.mapping.lease && m.context.writer_live);
        assert(m.calls[2] == 1 && m.calls[3] == (unsigned int)!close && !m.end_calls);
        assert(m.context.open_live == (unsigned int)close && m.context.owner_live); model_destroy(&m);
    }
}
static void native_consistency(void) {
    for (int i = 1; i <= 4; ++i) {
        struct native_model m; model_setup(&m, 1); model_bind(&m); assert(!model_acquire(&m)); m.mutate = i;
        unsigned char out[32]; assert(m.provider.read(&m.context, &m.token, 0, out, sizeof out) == -ESTALE);
        assert_sticky(&m); assert(!m.calls[2] && !m.calls[3] && m.data && m.context.mapping.lease); model_destroy(&m);
    }
}
static void native_alias(void) {
    for (int i = 1; i <= 5; ++i) {
        struct native_model m; model_setup(&m, 1); model_bind(&m);
        if (i >= 2 && i <= 4) {
            m.alias = i; assert(model_acquire(&m) < 0);
            assert(!m.context.source_live && m.calls[2] == 1 && m.calls[3] == 1);
        } else {
            assert(!model_acquire(&m)); m.alias = i;
            struct functional_face_dmm_descriptor d = {.domain = 1, .unit = m.birth.span.unit, .handle = 0x8403,
                .epoch = 1, .owner = OWNER, .logical = 0x70000000, .registration = 12,
                .host_view = (uintptr_t)m.expected, .bytes = m.birth.span.bytes,
                .mapped_bytes = (m.birth.span.bytes + 4095u) / 4096 * 4096};
            assert(m.provider.check_disjoint(&m.context, &m.token, &d) == (i == 1 ? -EADDRINUSE : -ESTALE));
            assert(!m.provider.release(&m.context, &m.token));
        }
        assert(!m.physical_calls); model_destroy(&m);
    }
}
static void native_scatter_maps(void) {
    setup(); struct functional_face_dmm_descriptor d = create(0x1db);
    for (int mode = 2; mode <= 7; ++mode) {
        struct native_model m; model_setup(&m, 2); model_enable_scatter(&m);
        m.scatter = mode == 7 ? 1 : mode;
        if (mode == 7) m.sdk_count = FUNCTIONAL_FACE_NATIVE_AP_MAX_RANGES;
        model_bind(&m); assert(!model_acquire(&m));
        assert(!m.provider.check_disjoint(&m.context, &m.token, &d));
        assert(m.cp_pages == d.mapped_bytes / 4096 - (mode == 2));
        unsigned char out[32]; assert(m.provider.read(&m.context, &m.token, 0, out, sizeof out) == (long)sizeof out);
        assert(!memcmp(out, m.expected, sizeof out));
        assert(!m.provider.release(&m.context, &m.token) && !m.context.faulted);
        assert(m.calls[0] == 1 && m.calls[1] == 1 && m.calls[2] == 1 && m.calls[3] == 1 && m.end_calls == 1);
        model_destroy(&m);
    }
    (void)operation(0x23, d.unit, d.handle, 0, 0); assert(!functional_face_dmm_shutdown());
    puts("NATIVE_HOST_SCATTER_MAPS coalesced=1 distinct_backings=1 cp_holes=1 mailer_holes=1 endpoint=1 max128=1");
}
static void native_scatter_invalid(void) {
    setup(); struct functional_face_dmm_descriptor d = create(0x1db), saved = d;
    uint64_t digest = hash((const void *)d.host_view, d.mapped_bytes);
    unsigned int rejected = 0;
    for (int target = 0; target < 3; ++target) for (int error = 1; error <= (target == 2 ? 14 : 8); ++error) {
        struct native_model m; model_setup(&m, 2); model_enable_scatter(&m); model_bind(&m);
        m.set_target = target;
        if (target < 2) {
            m.set_error = error;
            struct functional_face_ap_borrow out; memset(&out, 0xa5, sizeof out); struct functional_face_ap_borrow old = out;
            assert(m.provider.acquire(&m.context, &m.birth.span, 0, m.birth.span.bytes, &out) == -ENODATA);
            assert(!memcmp(&out, &old, sizeof out));
        } else {
            assert(!model_acquire(&m)); m.set_error = error;
            struct functional_face_ap_borrow old = m.token;
            assert(m.provider.check_disjoint(&m.context, &m.token, &d) == -ESTALE);
            assert(!memcmp(&m.token, &old, sizeof old) && !memcmp(&d, &saved, sizeof d));
            assert(!m.provider.release(&m.context, &m.token));
        }
        assert(!m.physical_calls && !m.context.faulted && !m.context.source_live && !m.context.writer_live);
        assert(m.calls[2] == 1 && m.calls[3] == 1 && m.end_calls == 1);
        model_destroy(&m); ++rejected;
    }
    assert(rejected == 30 && hash((const void *)d.host_view, d.mapped_bytes) == digest);
    (void)operation(0x23, d.unit, d.handle, 0, 0); assert(!functional_face_dmm_shutdown());
    printf("NATIVE_HOST_SCATTER_INVALID rejected=%u caller_unchanged=1 cp_unchanged=1\n", rejected);
}
static void native_scatter_alias(void) {
    setup(); struct functional_face_dmm_descriptor d = create(0x1db);
    for (int pair = 1; pair <= 6; ++pair) {
        struct native_model m; model_setup(&m, 2); model_enable_scatter(&m); model_bind(&m);
        if (pair <= 3) {
            m.scatter_alias = pair;
            struct functional_face_ap_borrow out; memset(&out, 0xa5, sizeof out); struct functional_face_ap_borrow old = out;
            assert(m.provider.acquire(&m.context, &m.birth.span, 0, m.birth.span.bytes, &out) == -EADDRINUSE);
            assert(!memcmp(&out, &old, sizeof out));
        } else {
            assert(!model_acquire(&m)); m.scatter_alias = pair;
            assert(m.provider.check_disjoint(&m.context, &m.token, &d) == -EADDRINUSE);
            assert(m.cp_pages == 14); /* Alias is solely in the final rounded CP page. */
            assert(!m.provider.release(&m.context, &m.token));
        }
        assert(!m.physical_calls && !m.context.faulted && !m.context.source_live);
        assert(m.calls[2] == 1 && m.calls[3] == 1 && m.end_calls == 1); model_destroy(&m);
    }
    (void)operation(0x23, d.unit, d.handle, 0, 0); assert(!functional_face_dmm_shutdown());
    puts("NATIVE_HOST_SCATTER_ALIAS pairs=6 nonfirst=1 final_rounded_cp_page=1");
}
static void native_scatter_change(void) {
    setup(); struct functional_face_dmm_descriptor d = create(0x1db), original = d;
    for (int path = 0; path < 2; ++path) for (int mutation = 1; mutation <= 14; ++mutation) {
        struct native_model m; model_setup(&m, 2); model_enable_scatter(&m); model_bind(&m); assert(!model_acquire(&m));
        struct functional_face_native_ap_mapping saved = m.context.mapping;
        struct functional_face_ap_borrow token = m.token;
        if (mutation <= 10) m.mapping_mutation = mutation;
        else { m.set_target = mutation >= 13; m.set_error = 1 + ((mutation - 11) & 1); }
        unsigned char out[32], old[32]; memset(out, 0xa5, sizeof out); memcpy(old, out, sizeof out);
        if (path) assert(m.provider.check_disjoint(&m.context, &m.token, &d) == -ESTALE);
        else assert(m.provider.read(&m.context, &m.token, 0, out, sizeof out) == -ESTALE);
        assert(!memcmp(out, old, sizeof out) && !memcmp(&saved, &m.context.mapping, sizeof saved));
        assert(!memcmp(&d, &original, sizeof d) && !memcmp(&m.token, &token, sizeof token));
        assert(!m.physical_calls && !m.context.bytes_read && !m.calls[2] && !m.calls[3]);
        assert_sticky(&m); model_destroy(&m);
    }
    for (int path = 0; path < 2; ++path) for (int mutation = 1; mutation <= 18; ++mutation) {
        struct native_model m; model_setup(&m, 2); model_enable_scatter(&m); model_bind(&m); assert(!model_acquire(&m));
        assert(!m.provider.check_disjoint(&m.context, &m.token, &d));
        struct functional_face_native_ap_range_set saved = m.context.cp;
        struct functional_face_ap_borrow token = m.token;
        if (mutation <= 4) m.cp_mutation = mutation;
        else { m.set_target = 2; m.set_error = mutation - 4; }
        unsigned char out[32], old[32]; memset(out, 0xa5, sizeof out); memcpy(old, out, sizeof out);
        if (path) assert(m.provider.check_disjoint(&m.context, &m.token, &d) == -ESTALE);
        else assert(m.provider.read(&m.context, &m.token, 0, out, sizeof out) == -ESTALE);
        assert(!memcmp(out, old, sizeof out) && !memcmp(&saved, &m.context.cp, sizeof saved));
        assert(!memcmp(&d, &original, sizeof d) && !memcmp(&m.token, &token, sizeof token));
        assert(!m.physical_calls && !m.context.bytes_read && !m.calls[2] && !m.calls[3]);
        assert_sticky(&m); model_destroy(&m);
    }
    (void)operation(0x23, d.unit, d.handle, 0, 0); assert(!functional_face_dmm_shutdown());
    puts("NATIVE_HOST_SCATTER_CHANGE mutations=14 paths=2 cp_mutations=18 cp_paths=2 ordered_identity=1 no_retry=1 caller_unchanged=1");
}
static void native_extents(void) {
    for (int i = 1; i <= 5; ++i) {
        struct native_model m; model_setup(&m, 1); model_bind(&m); m.extent_error = i;
        assert(model_acquire(&m) == -EPROTO);
        assert(!m.context.faulted && !m.context.source_live && m.calls[2] == 1 && m.calls[3] == 1 && !m.physical_calls);
        model_destroy(&m);
    }
}
static void native_reads(void) {
    const long values[] = {0, 14, -EIO, -EINTR, LONG_MIN, LONG_MAX};
    for (size_t i = 0; i < sizeof values / sizeof *values; ++i) {
        struct native_model m; model_setup(&m, 1); model_bind(&m); assert(!model_acquire(&m));
        m.read_error = 1; m.read_value = values[i]; unsigned char out[32];
        long rc = m.provider.read(&m.context, &m.token, 0, out, sizeof out);
        assert(rc == (values[i] < -4095 || values[i] > 15 ? -EIO : values[i]));
        assert(!m.provider.release(&m.context, &m.token) && m.calls[2] == 1 && m.calls[3] == 1); model_destroy(&m);
    }
}
static void native_tokens(void) {
    struct native_model m; model_setup(&m, 1); model_bind(&m); assert(!model_acquire(&m));
    unsigned int checks = m.writer_calls;
    for (unsigned int i = 0; i < 6; ++i) {
        struct functional_face_ap_borrow bad = m.token;
        if (i == 0) ++bad.nonce;
        if (i == 1) ++bad.span.epoch;
        if (i == 2) ++bad.span.owner;
        if (i == 3) ++bad.span.unit;
        if (i == 4) ++bad.offset;
        if (i == 5) --bad.bytes;
        unsigned char out[32]; assert(m.provider.read(&m.context, &bad, 0, out, sizeof out) == -ESTALE);
        assert(m.provider.release(&m.context, &bad) == -ESTALE);
    }
    assert(m.writer_calls == checks && !m.physical_calls && !m.calls[2]);
    assert(!m.provider.release(&m.context, &m.token));
    assert(m.provider.release(&m.context, &m.token) == -ESTALE && m.calls[2] == 1 && m.calls[3] == 1); model_destroy(&m);
}
static void native_reentry(void) {
    struct native_model m; model_setup(&m, 1); model_bind(&m); assert(!model_acquire(&m)); m.reentry = 1;
    unsigned char out[8192]; assert(m.provider.read(&m.context, &m.token, 0, out, sizeof out) == (long)sizeof out);
    assert(m.physical_calls == 3 && !memcmp(out, m.expected, sizeof out));
    assert(!m.provider.release(&m.context, &m.token)); model_destroy(&m);
}
static void *native_wrong_thread(void *p) {
    struct native_model *m = p; struct functional_face_ap_borrow b = {0};
    assert(m->provider.acquire(&m->context, &m->birth.span, 0, m->birth.span.bytes, &b) == -ECHILD);
    assert(m->provider.release(&m->context, &m->token) == -ECHILD); return NULL;
}
static void native_fork_thread(void) {
    struct native_model m; model_setup(&m, 1); model_bind(&m); assert(!model_acquire(&m));
    pthread_t thread; assert(!pthread_create(&thread, NULL, native_wrong_thread, &m)); assert(!pthread_join(thread, NULL));
    atomic_store(&m.context.busy, 1);
    pid_t child = fork(); assert(child >= 0);
    if (!child) {
        struct functional_face_ap_provider p;
        assert(functional_face_native_ap_init(&m.context, &model_ops, &m, &m.observer, &m.birth, &p) == -ECHILD);
        native_wrong_thread(&m); unsigned char out[32];
        assert(m.provider.read(&m.context, &m.token, 0, out, sizeof out) == -ECHILD); _exit(0);
    }
    int status; assert(waitpid(child, &status, 0) == child && WIFEXITED(status) && !WEXITSTATUS(status));
    atomic_store(&m.context.busy, 0); assert(m.calls[0] == 1 && !m.calls[2]);
    assert(!m.provider.release(&m.context, &m.token)); model_destroy(&m);
}
static void native_observation(void) {
    struct native_model m; model_setup(&m, 1);
    struct functional_face_ap_birth fact;
    assert(!functional_face_ap_observed_birth(&m.observer, THREAD_ID(), m.birth.span.unit, m.birth.span.handle, &fact));
    assert(m.current.owners == 1 && !m.calls[0] && !m.context.owner_live);
    model_bind(&m); m.observer.active = 1;
    assert(model_acquire(&m) == -EBUSY && !m.calls[0] && !m.writer_calls);
    m.observer.active = 0; m.observer.births[1].any_free_observed = 1;
    assert(model_acquire(&m) == -ESTALE && !m.calls[0] && !m.writer_calls);
    assert(!m.context.source_live && !m.context.candidate_capability); model_destroy(&m);
}
int main(int argc, char **argv) {
    assert(argc == 2); const char *mode = argv[1];
    if (!strcmp(mode, "positive")) native_positive(0);
    else if (!strcmp(mode, "scatter")) native_positive(1);
    else if (!strcmp(mode, "scatter-maps")) native_scatter_maps();
    else if (!strcmp(mode, "scatter-invalid")) native_scatter_invalid();
    else if (!strcmp(mode, "scatter-alias")) native_scatter_alias();
    else if (!strcmp(mode, "scatter-change")) native_scatter_change();
    else if (!strcmp(mode, "owner-life")) native_owner_life();
    else if (!strcmp(mode, "birth")) native_birth_rejections();
    else if (!strcmp(mode, "missing")) native_missing();
    else if (!strcmp(mode, "ticket")) native_tickets();
    else if (!strcmp(mode, "transport")) native_transport();
    else if (!strcmp(mode, "query-fail")) native_balanced_failure(1);
    else if (!strcmp(mode, "mapping-fail")) native_balanced_failure(0);
    else if (!strcmp(mode, "close-fail")) native_release_failure(1);
    else if (!strcmp(mode, "free-fail")) native_release_failure(0);
    else if (!strcmp(mode, "consistency")) native_consistency();
    else if (!strcmp(mode, "alias")) native_alias();
    else if (!strcmp(mode, "extent")) native_extents();
    else if (!strcmp(mode, "reads")) native_reads();
    else if (!strcmp(mode, "tokens")) native_tokens();
    else if (!strcmp(mode, "reentry")) native_reentry();
    else if (!strcmp(mode, "fork-thread")) native_fork_thread();
    else if (!strcmp(mode, "observation")) native_observation();
    else abort();
    printf("FACE_NATIVE_AP_HOST_PASS mode=%s native_io_bound=0\n", mode); return 0;
}
