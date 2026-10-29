/* Synthetic HOST_TEST bytes only; no native producer/framing claim. */
#include "native-au.h"

#include <assert.h>
#include <errno.h>
#include <stdio.h>
#include <string.h>

#define BASE UINT64_C(0x400002000)
#define CORRECTION UINT64_C(0x200000000)

struct output_box { struct nau value; uint8_t tail[128]; };

static void put_le(uint8_t *p, uint64_t v, size_t n)
{
    for (size_t i = 0; i < n; ++i) p[i] = (uint8_t)(v >> (8 * i));
}

static void make_info(uint8_t *p, unsigned type, uint64_t address, uint32_t length)
{
    for (size_t i = 0; i < NVIDEO_INFO_BYTES; ++i) p[i] = (uint8_t)(i * 37 + 19);
    p[0] = (uint8_t)type; p[1] = 0xfd; p[2] = 0xe3; p[3] = 0xfe;
    put_le(p + 8, address, 8); put_le(p + 0x10, length, 4);
    put_le(p + 0x18, UINT64_C(0xfedcba9876543210), 8);
    put_le(p + 0x20, UINT64_C(0x87654321fedcba98), 8);
    put_le(p + 0x28, 0xf123, 2); p[0x2a] = 0x92; p[0x2b] = 0xd1;
    put_le(p + 0x2c, 0xe234, 2); p[0x2e] = 0xa3; p[0x2f] = 0xc2;
    put_le(p + 0x30, 0xd345, 2); p[0x32] = 0xb4; p[0x33] = 0xb3;
}

static void unchanged_error(const uint8_t *wire, size_t size,
    uint64_t correction, uint64_t base, const uint8_t *es, size_t capacity,
    size_t out_capacity, int expected)
{
    struct output_box box, before;
    memset(&box, 0xa5, sizeof(box));
    memcpy(&before, &box, sizeof(box));
    errno = EINTR;
    assert(nau_resolve(wire, size, correction, base, es, capacity,
        &box.value, out_capacity) == expected);
    assert(errno == EINTR);
    assert(!memcmp(&box, &before, sizeof(box)));
}

static struct nau resolve_ok(const uint8_t *wire, uint64_t correction,
    uint64_t base, const uint8_t *es, size_t capacity)
{
    struct output_box box;
    memset(&box, 0xa5, sizeof(box));
    errno = EDOM;
    assert(!nau_resolve(wire, NVIDEO_INFO_BYTES, correction, base, es,
        capacity, &box.value, sizeof(box)));
    assert(errno == EDOM);
    for (size_t i = 0; i < sizeof(box.tail); ++i) assert(box.tail[i] == 0xa5);
    assert(!memcmp(box.value.raw_info, wire, NVIDEO_INFO_BYTES));
    return box.value;
}

static void metadata(void)
{
    static const uint8_t types[] = {0, 1, 2, 3, 9};
    uint8_t wire[96], es[64], before[96];
    memset(es, 0xab, sizeof(es));
    for (size_t i = 0; i < sizeof(types); ++i) {
        for (unsigned flags = 0; flags < 256; ++flags) {
            struct nvideo_info old;
            struct nau r;
            make_info(wire, types[i], BASE - CORRECTION + 7, 17);
            wire[1] = (uint8_t)flags; wire[3] = (uint8_t)(255 - flags);
            memcpy(before, wire, sizeof(wire));
            r = resolve_ok(wire, CORRECTION, BASE, es, sizeof(es));
            assert(nvideo_parse_info(wire, 96, BASE - CORRECTION + 7,
                17, &old) == NVIDEO_OK);
            assert(!memcmp(&old, &r.info, sizeof(old)));
            assert(r.info.type == types[i] && r.info.keyframe == (types[i] == 0));
            assert(r.info.parameter_set_changes == (flags & 7));
            assert(r.info.unit == ((255 - flags) & 1) && r.info.padding == 0xe3);
            assert(r.info.address == BASE - CORRECTION + 7 && r.info.length == 17);
            assert(r.info.pts == UINT64_C(0xfedcba9876543210));
            assert(r.info.dts == UINT64_C(0x87654321fedcba98));
            assert(r.info.vps_size == 0xf123 && r.info.vps_count == 0x92 && r.info.vps_id == 0xd1);
            assert(r.info.sps_size == 0xe234 && r.info.sps_count == 0xa3 && r.info.sps_id == 0xc2);
            assert(r.info.pps_size == 0xd345 && r.info.pps_count == 0xb4 && r.info.pps_id == 0xb3);
            assert(r.corrected_address == BASE + 7 && r.address_correction == CORRECTION);
            assert(r.es_base == BASE && r.es_capacity == sizeof(es));
            assert(r.total_length == 17 && r.span_count == 1);
            assert(r.spans[0].data == es + 7 && r.spans[0].length == 17);
            assert(r.spans[0].logical_address == BASE + 7 && r.spans[0].es_offset == 7);
            assert(!r.spans[1].data && !r.spans[1].length &&
                !r.spans[1].logical_address && !r.spans[1].es_offset);
            assert(!memcmp(wire, before, sizeof(wire)));
            memset(wire, 0, sizeof(wire));
            assert(!memcmp(r.raw_info, before, sizeof(before)));
        }
    }
    assert(nvideo_native_gaps() == 63);
}

static void check_spans(const uint8_t *es, size_t cap, size_t offset, size_t length,
    const struct nau *r)
{
    size_t consumed = 0;
    uint8_t joined[256], expected[256];
    assert(length <= sizeof(joined));
    for (size_t i = 0; i < length; ++i) expected[i] = es[(offset + i) % cap];
    assert(r->span_count == (length <= cap - offset ? 1u : 2u));
    assert(r->total_length == length);
    for (size_t i = 0; i < r->span_count; ++i) {
        const struct nau_span *s = &r->spans[i];
        assert(s->length && s->es_offset < cap && s->length <= cap - s->es_offset);
        assert(s->data == es + s->es_offset);
        assert(s->logical_address == r->es_base + s->es_offset);
        assert(s->es_offset == (i ? 0 : offset));
        assert(s->length <= length - consumed);
        memcpy(joined + consumed, s->data, s->length);
        consumed += s->length;
    }
    assert(consumed == length && !memcmp(joined, expected, length));
}

static void opaque(void)
{
    uint8_t wire[96], es[256], before[256];
    struct nau r;
    for (size_t i = 0; i < sizeof(es); ++i) es[i] = (uint8_t)i;
    /* Deliberately mixed/malformed patterns: all bytes must survive verbatim. */
    memcpy(es + 3, "\0\0\0\1\x67\xff\0\0\1\x65", 10);
    memcpy(es + 245, "\0\0\0\x05\xff\0\0\x80\xff\xff\0", 11);
    memcpy(before, es, sizeof(es));
    make_info(wire, 2, BASE + 3, 31);
    r = resolve_ok(wire, 0, BASE, es, sizeof(es));
    check_spans(es, sizeof(es), 3, 31, &r);
    make_info(wire, 9, BASE - CORRECTION + 245, 40);
    r = resolve_ok(wire, CORRECTION, BASE, es, sizeof(es));
    check_spans(es, sizeof(es), 245, 40, &r);
    assert(r.spans[0].length == 11 && r.spans[1].length == 29);
    assert(!memcmp(es, before, sizeof(es)));
}

static void ring(void)
{
    uint8_t wire[96], es[16];
    for (size_t i = 0; i < sizeof(es); ++i) es[i] = (uint8_t)(255 - i);
    for (size_t cap = 1; cap <= sizeof(es); ++cap) {
        for (size_t offset = 0; offset < cap; ++offset) {
            for (size_t length = 1; length <= cap; ++length) {
                struct nau r;
                make_info(wire, 1, BASE + offset, (uint32_t)length);
                r = resolve_ok(wire, 0, BASE, es, cap);
                check_spans(es, cap, offset, length, &r);
                if (length == cap - offset) assert(r.span_count == 1);
            }
        }
        make_info(wire, 0, BASE, (uint32_t)(cap + 1));
        unchanged_error(wire, 96, 0, BASE, es, cap, sizeof(struct output_box), -ERANGE);
        make_info(wire, 0, BASE - 1, 1);
        unchanged_error(wire, 96, 0, BASE, es, cap, sizeof(struct output_box), -ERANGE);
        make_info(wire, 0, BASE + cap, 1);
        unchanged_error(wire, 96, 0, BASE, es, cap, sizeof(struct output_box), -ERANGE);
    }
    make_info(wire, 0, 0, 1);
    {
        struct nau r = resolve_ok(wire, 0, 0, es, 1);
        assert(r.corrected_address == 0 && r.spans[0].length == 1);
    }
    make_info(wire, 0, UINT64_MAX - 4, 4);
    {
        struct nau r = resolve_ok(wire, 0, UINT64_MAX - 8, es, 8);
        assert(r.spans[0].length == 4 && r.span_count == 1);
    }
}

static void arguments(void)
{
    uint8_t wire[96], es[64];
    make_info(wire, 0, BASE, 1);
    unchanged_error(NULL, 96, 0, BASE, es, 64, sizeof(struct output_box), -EINVAL);
    unchanged_error(wire, 96, 0, BASE, NULL, 64, sizeof(struct output_box), -EINVAL);
    unchanged_error(wire, 96, 0, BASE, es, 0, sizeof(struct output_box), -EINVAL);
    for (size_t size = 0; size < 96; ++size)
        unchanged_error(wire, size, 0, BASE, es, 64, sizeof(struct output_box), -ENODATA);
    unchanged_error(wire, 97, 0, BASE, es, 64, sizeof(struct output_box), -EINVAL);
    unchanged_error(wire, SIZE_MAX, 0, BASE, es, 64, sizeof(struct output_box), -EINVAL);
    for (size_t size = 0; size < sizeof(struct nau); ++size)
        unchanged_error(wire, 96, 0, BASE, es, 64, size, -ENOSPC);
    errno = E2BIG;
    assert(nau_resolve(wire, 96, 0, BASE, es, 64, NULL, sizeof(struct nau)) == -EINVAL);
    assert(errno == E2BIG);
    for (unsigned type = 0; type < 256; ++type) {
        wire[0] = (uint8_t)type;
        if (type <= 3 || type == 9) continue;
        unchanged_error(wire, 96, 0, BASE, es, 64, sizeof(struct output_box), -ENOTSUP);
    }
    make_info(wire, 0, BASE, 0);
    unchanged_error(wire, 96, 0, BASE, es, 64, sizeof(struct output_box), -EINVAL);
    make_info(wire, 0, BASE, UINT32_MAX);
    unchanged_error(wire, 96, 0, BASE, es, 64, sizeof(struct output_box), -ERANGE);
}

static void arithmetic(void)
{
    uint8_t wire[96], es[64];
    make_info(wire, 0, BASE, 1);
    unchanged_error((const uint8_t *)(uintptr_t)(UINTPTR_MAX - 47), 96,
        0, BASE, es, 64, sizeof(struct output_box), -EOVERFLOW);
    unchanged_error(wire, 96, 0, BASE,
        (const uint8_t *)(uintptr_t)(UINTPTR_MAX - 31), 64,
        sizeof(struct output_box), -EOVERFLOW);
    unchanged_error(wire, 96, 0, BASE, es, SIZE_MAX, sizeof(struct output_box), -EOVERFLOW);
    unchanged_error(wire, 96, 0, BASE, es, 64, SIZE_MAX, -EOVERFLOW);
    errno = E2BIG;
    assert(nau_resolve(wire, 96, 0, BASE, es, 64,
        (struct nau *)(uintptr_t)(UINTPTR_MAX - (_Alignof(struct nau) - 1)),
        sizeof(struct nau)) == -EOVERFLOW);
    assert(errno == E2BIG);
    unchanged_error(wire, 96, UINT64_MAX, BASE, es, 64, sizeof(struct output_box), -EOVERFLOW);
    unchanged_error(wire, 96, 0, UINT64_MAX - 63, es, 64,
        sizeof(struct output_box), -EOVERFLOW);
    make_info(wire, 0, UINT64_MAX - 3, 4);
    unchanged_error(wire, 96, 0, BASE, es, 64, sizeof(struct output_box), -EOVERFLOW);
    make_info(wire, 0, UINT64_MAX - 8, 8);
    unchanged_error(wire, 96, 4, UINT64_MAX - 63, es, 63,
        sizeof(struct output_box), -EOVERFLOW);
}

static void alias(void)
{
    uint8_t wire[96], es[64];
    _Alignas(struct nau) uint8_t arena[sizeof(struct nau) + 256];
    uint8_t before[sizeof(arena)];
    make_info(wire, 0, BASE, 1);
    memset(arena, 0x5a, sizeof(arena));
    memcpy(before, arena, sizeof(arena));
    errno = E2BIG;
    assert(nau_resolve(wire, 96, 0, BASE, es, 64,
        (struct nau *)(void *)(arena + 1), sizeof(struct nau)) == -EINVAL);
    assert(errno == E2BIG && !memcmp(arena, before, sizeof(arena)));
    for (unsigned which = 0; which < 4; ++which) {
        const uint8_t *input = wire, *mapping = es;
        memset(arena, 0x5a, sizeof(arena));
        if (which == 0) { input = arena; memcpy(arena, wire, 96); }
        if (which == 1) mapping = arena;
        if (which == 2) {
            input = arena + sizeof(struct nau) + 16;
            memcpy((uint8_t *)input, wire, 96);
        }
        if (which == 3) mapping = arena + sizeof(struct nau) + 16;
        memcpy(before, arena, sizeof(arena));
        errno = EINTR;
        assert(nau_resolve(input, 96, 0, BASE, mapping, 64,
            (struct nau *)(void *)arena, sizeof(arena)) == -EINVAL);
        assert(errno == EINTR && !memcmp(arena, before, sizeof(arena)));
    }
    /* Adjacent inputs are legal when the declared output ends before them. */
    memcpy(arena + sizeof(struct nau), wire, 96);
    memcpy(before, arena, sizeof(arena));
    assert(!nau_resolve(arena + sizeof(struct nau), 96, 0, BASE, es, 64,
        (struct nau *)(void *)arena, sizeof(struct nau)));
    assert(!memcmp(arena + sizeof(struct nau), before + sizeof(struct nau), 256));
    memcpy(before, arena, sizeof(arena));
    assert(!nau_resolve(wire, 96, 0, BASE, arena + sizeof(struct nau), 64,
        (struct nau *)(void *)arena, sizeof(struct nau)));
    assert(!memcmp(arena + sizeof(struct nau), before + sizeof(struct nau), 256));
    /* Immutable info and ES may be the same mapping. */
    {
        struct nau r = resolve_ok(wire, 0, BASE, wire, sizeof(wire));
        assert(r.spans[0].data == wire && r.spans[0].length == 1);
    }
}

static void existing(void)
{
    uint8_t wire[96];
    struct nvideo_info r, before;
    memset(&r, 0xa5, sizeof(r));
    memcpy(&before, &r, sizeof(r));
    make_info(wire, 0, BASE + 63, 2);
    assert(nvideo_parse_info(wire, 96, BASE, 64, &r) == NVIDEO_RANGE);
    assert(!memcmp(&r, &before, sizeof(r)));
    for (size_t size = 0; size < 96; ++size) {
        assert(nvideo_parse_info(wire, size, BASE, 64, &r) == NVIDEO_INVALID);
        assert(!memcmp(&r, &before, sizeof(r)));
    }
    wire[0] = 4;
    assert(nvideo_parse_info(wire, 96, BASE, 64, &r) == NVIDEO_UNSUPPORTED);
    assert(!memcmp(&r, &before, sizeof(r)));
    make_info(wire, 9, BASE + 63, 1);
    assert(nvideo_parse_info(wire, 96, BASE, 64, &r) == NVIDEO_OK);
    assert(r.type == 9 && !r.keyframe && r.address == BASE + 63 && r.length == 1);
    make_info(wire, 0, BASE, 64);
    assert(nvideo_parse_info(wire, 96, BASE, 64, &r) == NVIDEO_OK);
    assert(r.keyframe && r.length == 64);
    assert(nvideo_native_gaps() == 63);
}

int main(int argc, char **argv)
{
    assert(argc == 2);
    if (!strcmp(argv[1], "metadata")) metadata();
    else if (!strcmp(argv[1], "opaque")) opaque();
    else if (!strcmp(argv[1], "ring")) ring();
    else if (!strcmp(argv[1], "arguments")) arguments();
    else if (!strcmp(argv[1], "arithmetic")) arithmetic();
    else if (!strcmp(argv[1], "alias")) alias();
    else if (!strcmp(argv[1], "existing")) existing();
    else assert(0);
    puts("HOST_TEST opaque AU contract passed");
    return 0;
}
