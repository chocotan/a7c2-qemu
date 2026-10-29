#include "native-fill.h"
#include "../native-video-producer-contract/native-producer.h"
#include "../native-video-au-contract/native-au.h"
#include "../native-video-paramsets/native-paramsets.h"
#include "../native-video-ring-contract/native-ring.h"
#include "../native-video-length-format/native-lengths.h"

#include <assert.h>
#include <errno.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

struct fixture {
    uint8_t work[NFILL_WORK_BYTES + 1];
    uint8_t node[NFILL_NODE_BYTES + 1];
    uint8_t baseline[NFILL_RECORD_BYTES + 1];
};

static void putle(uint8_t *p, uint64_t v, unsigned n)
{
    for (unsigned i = 0; i < n; ++i) p[i] = (uint8_t)(v >> (8 * i));
}

static uint64_t getle(const uint8_t *p, unsigned n)
{
    uint64_t v = 0;
    for (unsigned i = 0; i < n; ++i) v |= (uint64_t)p[i] << (8 * i);
    return v;
}

static uint8_t *segment(struct fixture *f, uint32_t j)
{
    assert(j < NFILL_SEGMENT_COUNT);
    return f->work + 0x620 + j * 0x10;
}

static void init(struct fixture *f)
{
    for (size_t i = 0; i < sizeof(f->work); ++i) f->work[i] = (uint8_t)(1 + i % 251);
    for (size_t i = 0; i < sizeof(f->node); ++i) f->node[i] = (uint8_t)(0x91 + i);
    for (size_t i = 0; i < sizeof(f->baseline); ++i) f->baseline[i] = (uint8_t)(0xa0 + i);
    for (size_t i = 0; i < 0x34; ++i) {
        f->work[0x5b0 + i] = (uint8_t)(0x11 + i);
        f->work[0x5e4 + i] = (uint8_t)(0x41 + i);
    }
    f->work[8] = 2;
    putle(f->work + 6, 0xbeef, 2); /* Opaque source lookup key, no guessed node key. */
    segment(f, 7)[0x0c] = 0; segment(f, 7)[0x0d] = 0;
    segment(f, 8)[0x0c] = 0xff; segment(f, 8)[0x0d] = 1;
    putle(segment(f, 7) + 8, 5, 4);
    putle(segment(f, 8) + 8, 7, 4);
    putle(f->work + 0xbc0 + 7 * 8, UINT64_C(0x123456789abcdef0), 8);
    putle(f->work + 0xbc0 + 8 * 8, UINT64_C(0x7777666655554444), 8);
    putle(f->work + 0x5e4 + 0x28, 0x0425, 2);
    putle(f->work + 0x5e4 + 0x10, UINT32_C(0x80000000), 4);
}

static struct nfill_record assembled(const struct fixture *f, uint32_t first, uint32_t last)
{
    struct nfill_record r;
    errno = 731;
    assert(!nfill_assemble(f->work, NFILL_WORK_BYTES, first, last,
        f->node, NFILL_NODE_BYTES, f->baseline, NFILL_RECORD_BYTES, &r, sizeof(r)));
    assert(errno == 731);
    return r;
}

static void mapping(void)
{
    struct fixture f, before;
    struct { struct nfill_record r; uint8_t tail[19]; } out;
    static const uint8_t expected[] = {
        0xf0,0xde,0xbc,0x9a,0x78,0x56,0x34,0x12,0x0c,0,0,0,0,0,0,1,
        0x45,0x46,0x47,0x48,0x41,0x42,0x43,0x44,
        0x4d,0x4e,0x4f,0x50,0x49,0x4a,0x4b,0x4c,
        0,0,0,0x80,0xff,0xff,0xff,0xff,
        0x59,0x5a,0x5b,0x5c,0x55,0x56,0x57,0x58,
        0x65,0x66,0x41,0x5d,0x5e,0xcd,0x67,0x68,0x63,0x64,0x5f,0x60,
        0x37,0x38,0x39,0x3a,0x3b,0x3c,0x3d,0x3e,
        0x99,0x9a,0x9b,0x9c,0x9d,0x9e,0x9f,0xa0,0xa1,0xa2,0xa3,0xa4,
        0xa5,0xa6,0xa7,0xa8,0xf4,0xf5,0xf6,0xf7
    };
    _Static_assert(sizeof(expected) == NFILL_RECORD_BYTES, "literal wire length");
    _Static_assert(sizeof(struct nfill_record) == 176, "two byte arrays only");
    _Static_assert(_Alignof(struct nfill_record) == 1, "unaligned byte output");
    init(&f); before = f;
    memset(&out, 0x5a, sizeof(out));
    assert(!nfill_assemble(f.work, NFILL_WORK_BYTES, 7, 8, f.node, NFILL_NODE_BYTES,
        f.baseline, NFILL_RECORD_BYTES, &out.r, sizeof(out)));
    assert(!memcmp(out.r.wire, expected, sizeof(expected)));
    for (size_t i = 0; i < 88; ++i)
        assert(out.r.semantic_written_bits[i] == (i < 0x54 ? 0xff : 0));
    for (size_t i = 0; i < sizeof(out.tail); ++i) assert(out.tail[i] == 0x5a);
    assert(!memcmp(&f, &before, sizeof(f)));
    /* Either metadata item is actual input; the unused item's bytes have no effect. */
    segment(&f, 8)[0x0d] = 0;
    out.r = assembled(&f, 7, 8);
    assert(getle(out.r.wire + 0x10, 8) == UINT64_C(0x1413121118171615));
    assert(out.r.wire[0x30] == 0x35 && out.r.wire[0x31] == 0x36);
}

static void matrix(void)
{
    static const uint8_t b8[] = {0,1,2,3,255};
    static const uint32_t signed_words[] = {0,1,0x7fffffff,0x80000000,0xffffffff};
    static const uint64_t signed_results[] = {0,1,UINT64_C(0x7fffffff),
        UINT64_C(0xffffffff80000000),UINT64_MAX};
    struct fixture f;
    struct nfill_record r;
    init(&f);
    for (size_t k = 0; k < sizeof(b8); ++k) {
        f.work[8] = b8[k];
        for (unsigned q = 0; q <= 0xffff; ++q) {
            unsigned expected_f = (q / 64) % 16;
            unsigned expected_g = (q & 3) | ((q & 0x400) ? 4 : 0) |
                ((q & 0x3c) * 2) | (b8[k] == 2 ? 128 : 0);
            putle(f.work + 0x5e4 + 0x28, q, 2);
            r = assembled(&f, 7, 8);
            assert(r.wire[0x0e] == expected_f && r.wire[0x35] == expected_g);
            assert(getle(r.wire + 0x0c, 2) == 0 && r.wire[0x0f] == 1);
            assert(getle(r.wire + 0x50, 4) == (expected_f & 2 ? 0 : UINT32_C(0xa8a7a6a5)));
        }
    }
    for (size_t i = 0; i < sizeof(signed_words) / sizeof(signed_words[0]); ++i) {
        putle(f.work + 0x5e4 + 0x10, signed_words[i], 4);
        r = assembled(&f, 7, 8);
        assert(getle(r.wire + 0x20, 8) == signed_results[i]);
    }
    /* Final writer overwrites helper g7 even if q would have set that bit. */
    putle(f.work + 0x5e4 + 0x28, 0xffff, 2);
    f.work[8] = 255; r = assembled(&f, 7, 8); assert(!(r.wire[0x35] & 0x80));
    f.work[8] = 2; r = assembled(&f, 7, 8); assert(r.wire[0x35] & 0x80);
}

static void failure(const struct fixture *f, uint32_t first, uint32_t last,
    size_t ws, size_t ns, size_t bs, size_t cap, int expected)
{
    struct fixture before = *f;
    struct { struct nfill_record r; uint8_t tail[16]; } out, old;
    memset(&out, 0x5a, sizeof(out)); old = out;
    errno = 731;
    assert(nfill_assemble(f->work, ws, first, last, f->node, ns,
        f->baseline, bs, &out.r, cap) == expected);
    assert(errno == 731 && !memcmp(&out, &old, sizeof(out)));
    assert(!memcmp(f, &before, sizeof(before)));
}

#define FAIL(FIRST, LAST, CODE) failure(&f, FIRST, LAST, NFILL_WORK_BYTES, \
    NFILL_NODE_BYTES, NFILL_RECORD_BYTES, sizeof(struct nfill_record) + 16, CODE)

static void arguments(void)
{
    struct fixture f;
    struct nfill_record r;
    init(&f);
    for (size_t n = 0; n < sizeof(r); ++n)
        failure(&f, 7, 8, NFILL_WORK_BYTES, 24, 88, n, -ENOSPC);
    failure(&f, 7, 8, NFILL_WORK_BYTES - 1, 24, 88, sizeof(r), -ENODATA);
    failure(&f, 7, 8, NFILL_WORK_BYTES + 1, 24, 88, sizeof(r), -EINVAL);
    failure(&f, 7, 8, NFILL_WORK_BYTES, 23, 88, sizeof(r), -ENODATA);
    failure(&f, 7, 8, NFILL_WORK_BYTES, 25, 88, sizeof(r), -EINVAL);
    failure(&f, 7, 8, NFILL_WORK_BYTES, 24, 87, sizeof(r), -ENODATA);
    failure(&f, 7, 8, NFILL_WORK_BYTES, 24, 89, sizeof(r), -EINVAL);
    failure(&f, 7, 8, SIZE_MAX, 24, 88, sizeof(r), -EOVERFLOW);
    failure(&f, 7, 8, NFILL_WORK_BYTES, 24, 88, SIZE_MAX, -EOVERFLOW);
    FAIL(8, 7, -ERANGE); FAIL(0, 90, -ERANGE); FAIL(90, 90, -ERANGE);
    FAIL(UINT32_MAX, UINT32_MAX, -ERANGE);
    segment(&f, 7)[0x0c] = 1; FAIL(7, 8, -ERANGE);
    init(&f); segment(&f, 8)[0x0c] = 0; FAIL(7, 8, -ERANGE);
    init(&f); segment(&f, 8)[0x0d] = 2; FAIL(7, 8, -ERANGE);
    init(&f); segment(&f, 7)[0x0d] = 255; FAIL(7, 8, -ERANGE);
    init(&f); putle(segment(&f, 7) + 8, 0, 4); FAIL(7, 8, -ENODATA);
    init(&f); putle(segment(&f, 8) + 8, 0, 4); FAIL(7, 8, -ENODATA);
    init(&f); putle(segment(&f, 7) + 8, UINT32_MAX, 4); FAIL(7, 8, -EOVERFLOW);
    init(&f); putle(f.work + 0xbc0 + 7 * 8, UINT64_MAX - 11, 8);
    FAIL(7, 8, -EOVERFLOW);
    putle(f.work + 0xbc0 + 7 * 8, UINT64_MAX - 12, 8);
    r = assembled(&f, 7, 8); assert(getle(r.wire, 8) == UINT64_MAX - 12);
    init(&f); putle(segment(&f, 8) + 8, UINT32_MAX - 5, 4);
    r = assembled(&f, 7, 8); assert(getle(r.wire + 8, 4) == UINT32_MAX);
    init(&f);
    for (uint32_t j = 0; j < 90; ++j) {
        putle(segment(&f, j) + 8, j + 1, 4);
        segment(&f, j)[0x0c] = j == 89 ? 128 : 0;
        segment(&f, j)[0x0d] = (uint8_t)(j & 1);
    }
    putle(f.work + 0xbc0, 0, 8); r = assembled(&f, 0, 89);
    assert(getle(r.wire + 8, 4) == 4095 && getle(r.wire, 8) == 0);
    r = assembled(&f, 89, 89); assert(getle(r.wire + 8, 4) == 90);
    memset(&r, 0xa5, sizeof(r));
    errno = 731;
    assert(nfill_assemble(NULL, NFILL_WORK_BYTES, 7, 8, f.node, 24,
        f.baseline, 88, &r, sizeof(r)) == -EINVAL);
    assert(nfill_assemble(f.work, NFILL_WORK_BYTES, 7, 8, NULL, 24,
        f.baseline, 88, &r, sizeof(r)) == -EINVAL);
    assert(nfill_assemble(f.work, NFILL_WORK_BYTES, 7, 8, f.node, 24,
        NULL, 88, &r, sizeof(r)) == -EINVAL);
    assert(nfill_assemble(f.work, NFILL_WORK_BYTES, 7, 8, f.node, 24,
        f.baseline, 88, NULL, sizeof(r)) == -EINVAL);
    assert(nfill_assemble((const uint8_t *)(uintptr_t)(UINTPTR_MAX - 3),
        NFILL_WORK_BYTES, 7, 8, f.node, 24, f.baseline, 88, &r, sizeof(r)) == -EOVERFLOW);
    assert(errno == 731);
    for (size_t i = 0; i < sizeof(r); ++i) assert(((uint8_t *)&r)[i] == 0xa5);
}

static void alias(void)
{
    struct fixture f;
    uint8_t arena[NFILL_WORK_BYTES + 512], old[sizeof(arena)];
    struct nfill_record reference;
    const uint8_t *inputs[3];
    init(&f); reference = assembled(&f, 7, 8);
    for (unsigned which = 0; which < 3; ++which) {
        memset(arena, 0x5a, sizeof(arena));
        inputs[0] = f.work; inputs[1] = f.node; inputs[2] = f.baseline;
        inputs[which] = arena + sizeof(reference); /* Only capacity tail aliases. */
        memcpy(old, arena, sizeof(old)); errno = 731;
        assert(nfill_assemble(inputs[0], NFILL_WORK_BYTES, 7, 8, inputs[1], 24,
            inputs[2], 88, (struct nfill_record *)(void *)arena,
            sizeof(reference) + 16) == -EINVAL);
        assert(errno == 731 && !memcmp(arena, old, sizeof(old)));
    }
    memcpy(arena, f.work, NFILL_WORK_BYTES); memcpy(old, arena, sizeof(old));
    /* Output hits known whole-work bytes beyond the last actually read cursor. */
    assert(nfill_assemble(arena, NFILL_WORK_BYTES, 7, 8, f.node, 24,
        f.baseline, 88, (struct nfill_record *)(void *)(arena + 0xd50),
        sizeof(reference)) == -EINVAL);
    assert(!memcmp(arena, old, sizeof(old)));
    memset(arena, 0x5a, sizeof(arena));
    assert(!nfill_assemble(f.work, NFILL_WORK_BYTES, 7, 8, f.node, 24,
        f.baseline, 88, (struct nfill_record *)(void *)(arena + 1), sizeof(reference) + 16));
    assert(arena[0] == 0x5a && !memcmp(arena + 1, &reference, sizeof(reference)));
    for (size_t i = 1 + sizeof(reference); i < sizeof(arena); ++i) assert(arena[i] == 0x5a);
    /* Input-input overlap is allowed; these remain explicit full snapshots. */
    assert(!nfill_assemble(f.work, NFILL_WORK_BYTES, 7, 8, f.work + 0x40, 24,
        f.work + 0x100, 88, (struct nfill_record *)(void *)arena, sizeof(reference)));
    assert(!memcmp(arena + 0x54, f.work + 0x154, 4));
}

static void plan_failure(uint32_t index, uint32_t n, uint64_t base,
    size_t cap, int expected)
{
    struct { struct nfill_notify_plan plan; uint8_t tail[16]; } out, before;
    memset(&out, 0x5a, sizeof(out)); before = out; errno = 731;
    assert(nfill_plan_notify(index, n, 0x1234, 0x5678, 0x9abc, UINT32_MAX,
        base, &out.plan, cap) == expected);
    assert(errno == 731 && !memcmp(&out, &before, sizeof(out)));
}

static void plan(void)
{
    struct { struct nfill_notify_plan plan; uint8_t tail[16]; } out;
    static const uint8_t wire[] = {0x03,0x21,0x1c,0x01,0x18,0,0,0,
        0x78,0x56,0x34,0x12,0x02,0,0,0,0x98,0xba,0xdc,0xfe,0xff,0xff,0xff,0xff};
    _Alignas(struct nfill_notify_plan) uint8_t unaligned[sizeof(out) + 1], old[sizeof(out) + 1];
    memset(&out, 0x5a, sizeof(out)); errno = 731;
    assert(!nfill_plan_notify(2, 3, 0x76543210, 0x12345678, 0xfedcba98,
        UINT32_MAX, UINT64_C(0x100000000), &out.plan, sizeof(out)));
    assert(errno == 731 && out.plan.record_address == UINT64_C(0x1000000b0));
    assert(out.plan.index == 2 && !out.plan.next_index && out.plan.destination == 0x76543210);
    assert(!memcmp(out.plan.wire, wire, sizeof(wire)));
    for (size_t i = 0; i < sizeof(out.tail); ++i) assert(out.tail[i] == 0x5a);
    assert(!nfill_plan_notify(0, 1, 0, UINT32_MAX, 0, 0x11223344, 0,
        &out.plan, sizeof(out)));
    assert(!out.plan.next_index && getle(out.plan.wire + 0x14, 4) == 0x11223344);
    /* Original UMADDL preserves products exceeding W32. */
    assert(!nfill_plan_notify(UINT32_MAX - 1, UINT32_MAX, UINT32_MAX, 0, 0, 0,
        0, &out.plan, sizeof(out)));
    assert(out.plan.record_address == (uint64_t)(UINT32_MAX - 1) * 88);
    assert(!out.plan.next_index && getle(out.plan.wire + 0x0c, 4) == UINT32_MAX - 1);
    assert(!nfill_plan_notify(0, 1, 0, 0, 0, 0, UINT64_MAX - 88,
        &out.plan, sizeof(out)));
    for (size_t cap = 0; cap < sizeof(out.plan); ++cap)
        plan_failure(0, 1, 0, cap, -ENOSPC);
    plan_failure(0, 0, 0, sizeof(out), -EINVAL);
    plan_failure(1, 1, 0, sizeof(out), -ERANGE);
    plan_failure(UINT32_MAX, UINT32_MAX, 0, sizeof(out), -ERANGE);
    plan_failure(0, 1, UINT64_MAX - 87, sizeof(out), -EOVERFLOW);
    plan_failure(0, 2, UINT64_MAX - 88, sizeof(out), -EOVERFLOW);
    plan_failure(0, 1, 0, SIZE_MAX, -EOVERFLOW);
    memset(unaligned, 0x5a, sizeof(unaligned)); memcpy(old, unaligned, sizeof(old));
    assert(nfill_plan_notify(0, 1, 0, 0, 0, 0, 0,
        (struct nfill_notify_plan *)(void *)(unaligned + 1), sizeof(out.plan)) == -EINVAL);
    assert(!memcmp(unaligned, old, sizeof(old)));
    assert(nfill_plan_notify(0, 1, 0, 0, 0, 0, 0, NULL, sizeof(out.plan)) == -EINVAL);
    assert(nfill_plan_notify(0, 1, 0, 0, 0, 0, 0,
        (struct nfill_notify_plan *)(uintptr_t)(UINTPTR_MAX -
        (_Alignof(struct nfill_notify_plan) - 1)), sizeof(out.plan)) == -EOVERFLOW);
    assert(errno == 731);
}

static void paramsets(void)
{
    static const uint8_t es[12] = {0,0,0,2,0x67,0x42,0,0,0,2,0x68,0xce};
    struct fixture f;
    struct nfill_record fill;
    struct nproducer_record converted;
    struct nparamsets sets;
    uint8_t zero96[96] = {0}, *d;
    init(&f); d = f.work + 0x5e4;
    putle(f.work + 0xbc0 + 7 * 8, 0x1000, 8);
    putle(d + 0x28, 0x0083, 2); /* f=2 and g low bits mark SPS/PPS. */
    putle(d + 0x1e, 0, 2); d[0x1d] = 0; d[0x1c] = 0xf1;
    putle(d + 0x22, 6, 2); d[0x20] = 5; d[0x21] = 1;
    putle(d + 0x26, 6, 2); d[0x25] = 1; d[0x24] = 6;
    fill = assembled(&f, 7, 8);
    assert(!nproducer_convert(fill.wire, 88, 0, 0, 1, 0x12345678,
        zero96, 96, &converted, sizeof(converted)));
    assert(converted.wire[0] == 4 && converted.wire[1] == 6);
    assert(!nparamsets_parse(converted.wire, 96, NPARAMSETS_AVC1, 0, 0x1000,
        es, sizeof(es), &sets, sizeof(sets)));
    assert(sets.sps.nal == es + 4 && sets.sps.nal_size == 2 && sets.sps.source_id == 5);
    assert(sets.pps.nal == es + 10 && sets.pps.nal_size == 2 && sets.pps.source_id == 6);
    assert(sets.sps.changed && sets.pps.changed && !sets.vps.changed);
    assert(!getle(fill.wire + 0x50, 4) && getle(converted.wire + 0x5a, 2) == 0xffff);
    assert(nvideo_native_gaps() == 63);
}

static void composed(void)
{
    /* Explicit structural AVC1 bytes; no claim of decoding/native encoding. */
    static const uint8_t payload[] = {0,0,0,4,0x65,0,0x80,0xff};
    const uint64_t base = UINT64_C(0x100000000);
    struct fixture f, before;
    struct nfill_record fill;
    struct nfill_notify_plan notify;
    struct nproducer_record converted;
    struct nproducer_publish_plan publish;
    struct nring_user user = {7,1,1};
    struct nring_advance release;
    struct nau au;
    struct nvideo_info info;
    uint8_t zero96[96] = {0}, es[64], ring[192], read_list[96], consumed[8];
    size_t borrowed = 0, nal_count = 0, used = 0;
    init(&f); f.work[8] = 2;
    putle(segment(&f, 7) + 8, 3, 4); putle(segment(&f, 8) + 8, 5, 4);
    putle(f.work + 0xbc0 + 7 * 8, base + 62, 8);
    putle(f.work + 0x5e4 + 0x28, 0x0040, 2); /* f=1, type zero, g7 from B8. */
    before = f; fill = assembled(&f, 7, 8);
    assert(!nfill_plan_notify(1, 2, 0x76543210, 0x12345678,
        (uint32_t)getle(f.node + 4, 4), UINT32_MAX, 0x8000, &notify, sizeof(notify)));
    assert(notify.index == 1 && !notify.next_index && notify.record_address == 0x8058);
    assert(getle(notify.wire + 0x0c, 4) == 1); /* Original index, not next. */
    assert(!nproducer_convert(fill.wire, 88, 0x81, 0, 1, 0x12340059,
        zero96, 96, &converted, sizeof(converted)));
    /* Abstract raw extent for metadata only; nau checks the actual ES ring. */
    assert(!nvideo_parse_info(converted.wire, 96, base + 62, sizeof(payload), &info));
    assert(info.address == base + 62 && info.length == sizeof(payload));
    assert(info.pts == UINT64_C(0x4443424148474645));
    assert(info.dts == UINT64_C(0x4c4b4a49504f4e4d));
    assert(info.unit == 1 && !info.padding && info.keyframe);
    assert(converted.wire[3] == 0x81 && converted.wire[0x58] == 1);
    memset(es, 0xd3, sizeof(es)); memset(ring, 0xa5, sizeof(ring));
    for (size_t i = 0; i < sizeof(payload); ++i) es[(62 + i) % sizeof(es)] = payload[i];
    assert(!nproducer_plan_publish(0x9000, 2, 0xa000, 1, 2, 0, &publish, sizeof(publish)));
    assert(!publish.index && publish.record_size == 96 && publish.occupied_after == 1);
    /* HOST copy only: the actual source DSB, queue and sends are not executed. */
    memcpy(ring + (size_t)(publish.slot_address - 0x9000), converted.wire, 96);
    assert(!nring_copy_read_list(ring, sizeof(ring), 2, publish.index, user.read_index,
        read_list, sizeof(read_list), &borrowed));
    assert(borrowed == 1 && !memcmp(read_list, converted.wire, 96));
    assert(!nau_resolve(read_list, 96, 0, base, es, sizeof(es), &au, sizeof(au)));
    assert(au.span_count == 2 && au.total_length == sizeof(payload));
    assert(!nlength_validate(read_list, 96, 0, base, es, sizeof(es), NLENGTH_AVC1, &nal_count));
    assert(nal_count == 1);
    for (size_t i = 0; i < au.span_count; ++i) {
        assert(au.spans[i].length <= sizeof(consumed) - used);
        memcpy(consumed + used, au.spans[i].data, au.spans[i].length);
        used += au.spans[i].length;
    }
    assert(used == sizeof(payload) && !memcmp(consumed, payload, sizeof(payload)));
    assert(!nring_advance_read(&user, 1, user.id, borrowed, borrowed, 2,
        publish.index, user.read_index, &release));
    assert(!release.user_read_index && !release.shared_read_index && release.delta == 1);
    assert(!memcmp(&f, &before, sizeof(f)) && nvideo_native_gaps() == 63);
}

int main(int argc, char **argv)
{
    assert(argc == 2);
    if (!strcmp(argv[1], "mapping")) mapping();
    else if (!strcmp(argv[1], "matrix")) matrix();
    else if (!strcmp(argv[1], "arguments")) arguments();
    else if (!strcmp(argv[1], "alias")) alias();
    else if (!strcmp(argv[1], "plan")) plan();
    else if (!strcmp(argv[1], "paramsets")) paramsets();
    else if (!strcmp(argv[1], "composed")) composed();
    else abort();
    puts("HOST_TEST actual S88 fill and pure original 011c plan passed");
    return 0;
}
