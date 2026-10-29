#include "native-lengths.h"
#include "../native-video-au-contract/native-au.h"

#include <assert.h>
#include <errno.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define BASE UINT64_C(0x2000)
#define CORRECTION UINT64_C(0x1000)
static const uint8_t one[] = {0, 0, 0, 1, 0x65};
static const uint8_t multi[] = {
    0,0,0,2,0x67,1, 0,0,0,2,0x68,2, 0,0,0,3,6,3,4,
    0,0,0,2,9,0xf0, 0,0,0,5,0x65,0,0x80,0xff,1,
    0,0,0,1,0, 0,0,0,2,0x1f,0x80
};

static void put32(uint8_t *p, uint32_t n)
{
    for (size_t i = 0; i < 4; ++i) p[i] = (uint8_t)(n >> (i * 8));
}

static void put64(uint8_t *p, uint64_t n)
{
    for (size_t i = 0; i < 8; ++i) p[i] = (uint8_t)(n >> (i * 8));
}

static void info(uint8_t *wire, uint8_t type, uint64_t raw, size_t length)
{
    assert(length <= UINT32_MAX);
    memset(wire, 0xa5, 96);
    wire[0] = type; wire[1] = 0xff; wire[2] = 0xff; wire[3] = 0xff;
    put64(wire + 8, raw); put32(wire + 0x10, (uint32_t)length);
}

static void place(uint8_t *wire, uint8_t *es, size_t capacity, size_t start,
    const uint8_t *bytes, size_t length, uint8_t type)
{
    assert(start < capacity && length <= capacity);
    memset(es, 0xa5, capacity);
    for (size_t i = 0; i < length; ++i) es[(start + i) % capacity] = bytes[i];
    info(wire, type, BASE - CORRECTION + start, length);
}

static int call(const uint8_t *wire, size_t size, uint64_t correction,
    uint64_t base, const uint8_t *es, size_t capacity, uint32_t codec,
    size_t *count)
{
    int rc;
    errno = EDOM;
    rc = nlength_validate(wire, size, correction, base, es, capacity, codec, count);
    assert(errno == EDOM);
    return rc;
}

static void sample(const uint8_t *bytes, size_t length, uint32_t codec,
    size_t tail, int expected_rc, size_t expected_count)
{
    uint8_t wire[96], wire_before[96], es[1024], es_before[1024];
    struct { size_t count; uint8_t tail[24]; } out, before;
    size_t capacity = length + 16, start = tail ? capacity - tail : 0;
    assert(capacity <= sizeof(es) && tail <= length);
    memset(es, 0, sizeof(es));
    place(wire, es, capacity, start, bytes, length, 1);
    memcpy(wire_before, wire, sizeof(wire));
    memcpy(es_before, es, sizeof(es));
    memset(&out, 0xa7, sizeof(out));
    memcpy(&before, &out, sizeof(out));
    assert(call(wire, 96, CORRECTION, BASE, es, capacity, codec, &out.count) == expected_rc);
    if (expected_rc) assert(!memcmp(&out, &before, sizeof(out)));
    else {
        assert(out.count == expected_count);
        assert(!memcmp(out.tail, before.tail, sizeof(out.tail)));
    }
    assert(!memcmp(wire, wire_before, sizeof(wire)));
    assert(!memcmp(es, es_before, sizeof(es)));
}

static void avc(void)
{
    uint8_t nal[] = {0, 0, 0, 1, 0};
    const uint8_t headers[] = {0, 1, 5, 6, 7, 8, 9, 24, 31, 0x7f};
    sample(multi, sizeof(multi), NLENGTH_AVC1, 0, 0, 7);
    for (size_t i = 0; i < sizeof(headers); ++i) {
        nal[4] = headers[i]; sample(nal, sizeof(nal), NLENGTH_AVC1, 0, 0, 1);
    }
    nal[4] = 0x80; sample(nal, sizeof(nal), NLENGTH_AVC1, 0, -EINVAL, 0);
    nal[4] = 0xff; sample(nal, sizeof(nal), NLENGTH_AVC1, 0, -EINVAL, 0);
    /* 00 00 00 01 65 is also a valid explicit BE32 length-one AU. */
    sample(one, sizeof(one), NLENGTH_AVC1, 0, 0, 1);
}

static void hevc(void)
{
    const uint8_t all[] = {
        0,0,0,2,0x40,1, 0,0,0,2,0x42,1, 0,0,0,2,0x44,1,
        0,0,0,2,0x4e,1, 0,0,0,2,0x46,1, 0,0,0,3,0x7f,0xff,0x80
    };
    uint8_t nal[] = {0,0,0,2,0x40,1};
    sample(all, sizeof(all), NLENGTH_HVC1, 0, 0, 6);
    sample(all, sizeof(all), NLENGTH_HVC1, 5, 0, 6);
    sample(one, sizeof(one), NLENGTH_HVC1, 0, -EINVAL, 0);
    nal[5] = 0; sample(nal, sizeof(nal), NLENGTH_HVC1, 0, -EINVAL, 0);
    nal[5] = 0xf8; sample(nal, sizeof(nal), NLENGTH_HVC1, 5, -EINVAL, 0);
    nal[5] = 7; nal[4] = 0xc0;
    sample(nal, sizeof(nal), NLENGTH_HVC1, 0, -EINVAL, 0);
    nal[4] = 0x7f; nal[5] = 0xff;
    sample(nal, sizeof(nal), NLENGTH_HVC1, 5, 0, 1);
}

static void wrap(void)
{
    uint8_t large[261] = {0,0,1,1,0x65};
    for (size_t i = 5; i < sizeof(large); ++i) large[i] = (uint8_t)i;
    for (size_t tail = 1; tail <= sizeof(multi); ++tail)
        sample(multi, sizeof(multi), NLENGTH_AVC1, tail, 0, 7);
    for (size_t tail = 1; tail <= 6; ++tail)
        sample(large, sizeof(large), NLENGTH_AVC1, tail, 0, 1);
    /* Both fields exactly ending at the ring end remain valid. */
    sample(one, sizeof(one), NLENGTH_AVC1, sizeof(one), 0, 1);
}

static void framing(void)
{
    uint8_t bad[16] = {0,0,0,0};
    sample(bad, 0, NLENGTH_AVC1, 0, -EINVAL, 0);
    for (size_t n = 1; n <= 3; ++n)
        sample(bad, n, NLENGTH_AVC1, 0, -ENODATA, 0);
    sample(bad, 4, NLENGTH_AVC1, 0, -EINVAL, 0);
    bad[3] = 3; bad[4] = 0x65;
    sample(bad, 6, NLENGTH_AVC1, 0, -ENODATA, 0);
    memset(bad, 0xff, 4);
    sample(bad, 8, NLENGTH_AVC1, 2, -ENODATA, 0);
    bad[0] = 1; bad[1] = bad[2] = bad[3] = 0;
    sample(bad, 8, NLENGTH_AVC1, 3, -ENODATA, 0);
    /* No padding stripping, including after an already valid NAL. */
    memcpy(bad, one, sizeof(one)); memset(bad + sizeof(one), 0, 4);
    for (size_t n = 1; n <= 3; ++n)
        sample(bad, sizeof(one) + n, NLENGTH_AVC1, 4, -ENODATA, 0);
    sample(bad, sizeof(one) + 4, NLENGTH_AVC1, 0, -EINVAL, 0);
    bad[8] = 2; bad[9] = 0x80; bad[10] = 1;
    sample(bad, 11, NLENGTH_AVC1, 0, -EINVAL, 0);
    /* A three-byte start-code stream is rejected for its actual BE32 size. */
    bad[0] = 0; bad[1] = 0; bad[2] = 1; bad[3] = 0x65;
    sample(bad, 8, NLENGTH_AVC1, 1, -ENODATA, 0);
}

static void arguments(void)
{
    uint8_t wire[96], es[64];
    _Alignas(size_t) uint8_t misaligned[sizeof(size_t) + 1], before[sizeof(misaligned)];
    size_t count = SIZE_MAX;
    place(wire, es, sizeof(es), 0, one, sizeof(one), 1);
    assert(call(NULL, 96, CORRECTION, BASE, es, 64, NLENGTH_AVC1, &count) == -EINVAL);
    assert(call(wire, 95, CORRECTION, BASE, es, 64, NLENGTH_AVC1, &count) == -ENODATA);
    assert(call(wire, 97, CORRECTION, BASE, es, 64, NLENGTH_AVC1, &count) == -EINVAL);
    assert(call(wire, 96, CORRECTION, BASE, NULL, 64, NLENGTH_AVC1, &count) == -EINVAL);
    assert(call(wire, 96, CORRECTION, BASE, es, 0, NLENGTH_AVC1, &count) == -EINVAL);
    assert(call(wire, 96, CORRECTION, BASE, es, 64, NLENGTH_AVC1, NULL) == -EINVAL);
    memset(misaligned, 0xa7, sizeof(misaligned));
    memcpy(before, misaligned, sizeof(before));
    assert(call(wire, 96, CORRECTION, BASE, es, 64, NLENGTH_AVC1,
        (size_t *)(void *)(misaligned + 1)) == -EINVAL);
    assert(!memcmp(misaligned, before, sizeof(before)));
    const uint32_t unknown[] = {0, 1, 2, 0x31637661, 0x68766332};
    for (size_t i = 0; i < sizeof(unknown) / sizeof(unknown[0]); ++i)
        assert(call(wire, 96, CORRECTION, BASE, es, 64, unknown[i], &count) == -ENOTSUP);
    assert(count == SIZE_MAX);
}

static void arithmetic(void)
{
    uint8_t wire[96], es[64];
    size_t count = SIZE_MAX;
    const uint8_t *bad = (const uint8_t *)(UINTPTR_MAX - 31);
    size_t *badout = (size_t *)(UINTPTR_MAX - (_Alignof(size_t) - 1));
    place(wire, es, 64, 0, one, sizeof(one), 1);
    /* Every artificial pointer is rejected before any memory access to it. */
    assert(call(bad, 96, CORRECTION, BASE, es, 64, NLENGTH_AVC1, &count) == -EOVERFLOW);
    assert(call(wire, 96, CORRECTION, BASE, bad, 64, NLENGTH_AVC1, &count) == -EOVERFLOW);
    assert(call(wire, 96, CORRECTION, BASE, es, 64, NLENGTH_AVC1, badout) == -EOVERFLOW);
    info(wire, 1, UINT64_MAX - 1, sizeof(one));
    assert(call(wire, 96, 0, BASE, es, 64, NLENGTH_AVC1, &count) == -EOVERFLOW);
    info(wire, 1, 1, sizeof(one));
    assert(call(wire, 96, UINT64_MAX, BASE, es, 64, NLENGTH_AVC1, &count) == -EOVERFLOW);
    assert(call(wire, 96, UINT64_MAX - 2, BASE, es, 64, NLENGTH_AVC1, &count) == -EOVERFLOW);
    assert(call(wire, 96, 0, UINT64_MAX - 63, es, 64, NLENGTH_AVC1, &count) == -EOVERFLOW);
    info(wire, 1, BASE - CORRECTION - 1, sizeof(one));
    assert(call(wire, 96, CORRECTION, BASE, es, 64, NLENGTH_AVC1, &count) == -ERANGE);
    info(wire, 1, BASE - CORRECTION + 64, sizeof(one));
    assert(call(wire, 96, CORRECTION, BASE, es, 64, NLENGTH_AVC1, &count) == -ERANGE);
    info(wire, 1, BASE - CORRECTION, 65);
    assert(call(wire, 96, CORRECTION, BASE, es, 64, NLENGTH_AVC1, &count) == -ERANGE);
    info(wire, 1, BASE - CORRECTION, UINT32_MAX);
    assert(call(wire, 96, CORRECTION, BASE, es, 64, NLENGTH_AVC1, &count) == -ERANGE);
    assert(count == SIZE_MAX);
}

static void aliases(void)
{
    _Alignas(size_t) uint8_t wire[128], arena[160], before[160];
    uint8_t wire_before[128];
    size_t count = SIZE_MAX;
    const size_t offsets[] = {0, 32, 120};
    memset(wire, 0, sizeof(wire));
    place(wire, arena, 128, 0, one, sizeof(one), 1);
    memset(arena + 128, 0xa7, sizeof(arena) - 128);
    memcpy(before, arena, sizeof(arena));
    for (size_t i = 0; i < sizeof(offsets) / sizeof(offsets[0]); ++i) {
        assert(call(wire, 96, CORRECTION, BASE, arena, 128, NLENGTH_AVC1,
            (size_t *)(void *)(arena + offsets[i])) == -EINVAL);
        assert(!memcmp(arena, before, sizeof(arena)));
    }
    /* The output overlaps the declared capacity tail but not the AU bytes. */
    assert(call(wire, 96, CORRECTION, BASE, arena, 125, NLENGTH_AVC1,
        (size_t *)(void *)(arena + 120)) == -EINVAL);
    assert(!memcmp(arena, before, sizeof(arena)));
    memcpy(wire_before, wire, sizeof(wire));
    assert(call(wire, 96, CORRECTION, BASE, arena, 128, NLENGTH_AVC1,
        (size_t *)(void *)(wire + 88)) == -EINVAL);
    assert(!memcmp(wire, wire_before, sizeof(wire)));
    /* Count just after the mapping is disjoint and only its bytes change. */
    assert(call(wire, 96, CORRECTION, BASE, arena, 128, NLENGTH_AVC1,
        (size_t *)(void *)(arena + 128)) == 0);
    memcpy(&count, arena + 128, sizeof(count)); assert(count == 1);
    assert(!memcmp(arena, before, 128));
    assert(!memcmp(arena + 128 + sizeof(count), before + 128 + sizeof(count),
        sizeof(arena) - 128 - sizeof(count)));
    /* Partial overlap at the mapping's beginning is rejected. */
    place(wire, arena + sizeof(size_t) - 1, 64, 0, one, sizeof(one), 1);
    memcpy(before, arena, sizeof(arena));
    assert(call(wire, 96, CORRECTION, BASE, arena + sizeof(size_t) - 1, 64,
        NLENGTH_AVC1, (size_t *)(void *)arena) == -EINVAL);
    assert(!memcmp(arena, before, sizeof(arena)));
    /* Adjacent output before the mapping, and after the descriptor, is valid. */
    place(wire, arena + sizeof(size_t), 64, 0, one, sizeof(one), 1);
    assert(call(wire, 96, CORRECTION, BASE, arena + sizeof(size_t), 64,
        NLENGTH_AVC1, (size_t *)(void *)arena) == 0);
    assert(call(wire, 96, CORRECTION, BASE, arena + sizeof(size_t), 64,
        NLENGTH_AVC1, (size_t *)(void *)(wire + 96)) == 0);
    /* Descriptor and ES are allowed to overlap each other. */
    info(wire, 1, BASE - CORRECTION + 64, sizeof(one));
    memcpy(wire + 64, one, sizeof(one));
    assert(call(wire, 96, CORRECTION, BASE, wire, 96, NLENGTH_AVC1, &count) == 0);
    assert(count == 1);
}

static void metadata(void)
{
    const uint8_t types[] = {0, 1, 2, 3, 9};
    const uint8_t unsupported[] = {4, 5, 8, 10, 0xff};
    uint8_t wire[96], es[64];
    size_t count = SIZE_MAX;
    assert(NVIDEO_NATIVE_GAPS == 63);
    for (size_t i = 0; i < sizeof(types); ++i) {
        place(wire, es, 64, 62, multi, sizeof(multi), types[i]);
        assert(call(wire, 96, CORRECTION, BASE, es, 64, NLENGTH_AVC1, &count) == 0);
        assert(count == 7);
    }
    for (size_t i = 0; i < sizeof(unsupported); ++i) {
        wire[0] = unsupported[i];
        assert(call(wire, 96, CORRECTION, BASE, es, 64, NLENGTH_AVC1, &count) == -ENOTSUP);
        assert(count == 7);
    }
    place(wire, es, 64, 0, one, sizeof(one), 1);
    put64(wire + 8, BASE);
    assert(call(wire, 96, 0, BASE, es, 64, NLENGTH_AVC1, &count) == 0);
    assert(count == 1);
    /* One full traversal with no invented padding/prefix subtraction. */
    place(wire, es, sizeof(multi), 3, multi, sizeof(multi), 9);
    assert(call(wire, 96, CORRECTION, BASE, es, sizeof(multi), NLENGTH_AVC1, &count) == 0);
    assert(count == 7);
}

static void fixture(size_t expected, size_t tail)
{
    static uint8_t bytes[65536], es[65552];
    uint8_t wire[96];
    size_t n = fread(bytes, 1, sizeof(bytes), stdin), count = SIZE_MAX;
    assert(!ferror(stdin) && feof(stdin) && n && n < sizeof(bytes));
    assert(tail <= n);
    place(wire, es, n + 16, tail ? n + 16 - tail : 0, bytes, n, 1);
    assert(call(wire, 96, CORRECTION, BASE, es, n + 16, NLENGTH_AVC1, &count) == 0);
    assert(count == expected);
}

int main(int argc, char **argv)
{
    assert(argc >= 2);
    if (!strcmp(argv[1], "avc")) avc();
    else if (!strcmp(argv[1], "hevc")) hevc();
    else if (!strcmp(argv[1], "wrap")) wrap();
    else if (!strcmp(argv[1], "framing")) framing();
    else if (!strcmp(argv[1], "arguments")) arguments();
    else if (!strcmp(argv[1], "arithmetic")) arithmetic();
    else if (!strcmp(argv[1], "aliases")) aliases();
    else if (!strcmp(argv[1], "metadata")) metadata();
    else {
        assert(argc == 4 && !strcmp(argv[1], "fixture"));
        fixture((size_t)strtoul(argv[2], NULL, 10), (size_t)strtoul(argv[3], NULL, 10));
    }
    puts("HOST_TEST strict BE32 lengths passed");
    return 0;
}
