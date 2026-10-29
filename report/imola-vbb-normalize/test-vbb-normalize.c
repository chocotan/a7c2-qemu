#include "vbb-normalize.h"

#include <assert.h>
#include <errno.h>
#include <stdio.h>
#include <string.h>

#define N NVBB_SUBRECORD_BYTES
#define COUNT(a) (sizeof(a) / sizeof((a)[0]))

static uint32_t get32(const unsigned char *p)
{
    return (uint32_t)p[0] | (uint32_t)p[1] << 8 |
           (uint32_t)p[2] << 16 | (uint32_t)p[3] << 24;
}

static void put32(unsigned char *p, uint32_t v)
{
    size_t i;
    for (i = 0; i < 4; ++i)
        p[i] = (unsigned char)(v >> (8 * i));
}

static int checked(uint32_t base, uint8_t mode, uint8_t aux,
                   const unsigned char *src, size_t sn,
                   unsigned char *out, size_t on)
{
    int rc;
    errno = 731;
    rc = nvbb_normalize_subrecord(base, mode, aux, src, sn, out, on);
    assert(errno == 731);
    return rc;
}

static void filled(const unsigned char *p, size_t n, unsigned char byte)
{
    size_t i;
    for (i = 0; i < n; ++i)
        assert(p[i] == byte);
}

static void fixture(unsigned char *p, size_t n, uint32_t x, uint32_t y, uint32_t z)
{
    memset(p, 0xd3, n);
    put32(p, x);
    put32(p + 4, y);
    put32(p + 8, z);
}

/* Literal expectations: identity, right shift, multiply-high, alignment, left shift. */
static const struct vector {
    uint32_t x;
    uint32_t expected[5];
} vectors[] = {
    { 0x00000000u, { 0x00000000u, 0x00000000u, 0x00000000u, 0x00000000u, 0x00000000u } },
    { 0x00000001u, { 0x00000001u, 0x00000000u, 0x00000000u, 0x00000000u, 0x00000002u } },
    { 0x00000002u, { 0x00000002u, 0x00000001u, 0x00000000u, 0x00000000u, 0x00000004u } },
    { 0x00000003u, { 0x00000003u, 0x00000001u, 0x00000002u, 0x00000200u, 0x00000006u } },
    { 0x0000017fu, { 0x0000017fu, 0x000000bfu, 0x000000feu, 0x00000200u, 0x000002feu } },
    { 0x00000180u, { 0x00000180u, 0x000000c0u, 0x00000100u, 0x00000200u, 0x00000300u } },
    { 0x00000182u, { 0x00000182u, 0x000000c1u, 0x00000100u, 0x00000200u, 0x00000304u } },
    { 0x00000183u, { 0x00000183u, 0x000000c1u, 0x00000102u, 0x00000400u, 0x00000306u } },
    { 0x000005ffu, { 0x000005ffu, 0x000002ffu, 0x000003feu, 0x00000800u, 0x00000bfeu } },
    { 0x00000600u, { 0x00000600u, 0x00000300u, 0x00000400u, 0x00000800u, 0x00000c00u } },
    { 0x00000601u, { 0x00000601u, 0x00000300u, 0x00000400u, 0x00000800u, 0x00000c02u } },
    { 0x7fffffffu, { 0x7fffffffu, 0x3fffffffu, 0x55555554u, 0xaaaaac00u, 0xfffffffeu } },
    { 0x80000000u, { 0x80000000u, 0x40000000u, 0x55555554u, 0xaaaaac00u, 0x00000000u } },
    { 0xbfffffffu, { 0xbfffffffu, 0x5fffffffu, 0x7ffffffeu, 0x00000000u, 0x7ffffffeu } },
    { 0xc0000000u, { 0xc0000000u, 0x60000000u, 0x80000000u, 0x00000000u, 0x80000000u } },
    { 0xfffffffdu, { 0xfffffffdu, 0x7ffffffeu, 0xaaaaaaa8u, 0x55555600u, 0xfffffffau } },
    { 0xfffffffeu, { 0xfffffffeu, 0x7fffffffu, 0xaaaaaaa8u, 0x55555600u, 0xfffffffcu } },
    { 0xffffffffu, { 0xffffffffu, 0x7fffffffu, 0xaaaaaaaau, 0x55555600u, 0xfffffffeu } }
};

static void test_vectors(void)
{
    static const struct { uint8_t mode, column; } modes[] = {
        {0, 0}, {1, 0}, {9, 0}, {2, 1}, {3, 2}, {4, 3},
        {5, 3}, {0xd, 3}, {6, 4}, {7, 4}, {0xf, 4}
    };
    static const uint32_t bases[] = {0, 0x12345678u, 0xffffffffu};
    unsigned char src[N + 11], before[sizeof(src)], out[N + 13];
    size_t b, m, v;
    for (b = 0; b < COUNT(bases); ++b)
        for (m = 0; m < COUNT(modes); ++m)
            for (v = 0; v < COUNT(vectors); ++v) {
                size_t w = (v + 1) % COUNT(vectors);
                unsigned int c = modes[m].column;
                fixture(src, sizeof(src), bases[b] + vectors[v].x,
                        bases[b] + vectors[w].x, 0xfedcba99u);
                memcpy(before, src, sizeof(src));
                memset(out, 0x5a, sizeof(out));
                assert(checked(bases[b], modes[m].mode, 2, src, sizeof(src),
                               out, sizeof(out)) == 0);
                assert(get32(out) == vectors[v].expected[c]);
                assert(get32(out + 4) == vectors[w].expected[c]);
                assert(get32(out + 8) == 0x7f6e5d4cu);
                assert(memcmp(out + 12, src + 12, N - 12) == 0);
                filled(out + N, sizeof(out) - N, 0x5a);
                assert(memcmp(src, before, sizeof(src)) == 0);
            }
}

static void test_matrix(void)
{
    static const uint32_t x[256] = {
        [0] = 3, [1] = 3, [9] = 3, [2] = 1, [3] = 2,
        [4] = 512, [5] = 512, [0xd] = 512, [6] = 6, [7] = 6, [0xf] = 6
    };
    static const uint32_t y[256] = {
        [0] = 1536, [1] = 1536, [9] = 1536, [2] = 768, [3] = 1024,
        [4] = 2048, [5] = 2048, [0xd] = 2048, [6] = 3072, [7] = 3072, [0xf] = 3072
    };
    unsigned char src[N + 7], before[sizeof(src)], out[N + 9], old[sizeof(out)];
    unsigned int a, u, nonzero;
    for (nonzero = 0; nonzero < 2; ++nonzero) {
        fixture(src, sizeof(src), 0x1234567bu, 0x12345c78u,
                nonzero ? 0xffffffffu : 0);
        memcpy(before, src, sizeof(src));
        for (a = 0; a < 256; ++a)
            for (u = 0; u < 256; ++u) {
                int supported = a == 0 || a == 1 || a == 2 || a == 3 ||
                    a == 4 || a == 5 || a == 6 || a == 7 || a == 9 || a == 13 || a == 15;
                int accepted = supported && (!nonzero || u == 1 || u == 2);
                memset(out, 0x5a, sizeof(out));
                memcpy(old, out, sizeof(out));
                assert(checked(0x12345678u, (uint8_t)a, (uint8_t)u,
                               src, sizeof(src), out, sizeof(out)) ==
                       (accepted ? 0 : -ENOTSUP));
                if (accepted) {
                    assert(get32(out) == x[a] && get32(out + 4) == y[a]);
                    assert(get32(out + 8) == (!nonzero ? 0u :
                           (u == 2 ? 0x7fffffffu : 0xffffffffu)));
                    assert(memcmp(out + 12, src + 12, N - 12) == 0);
                    filled(out + N, sizeof(out) - N, 0x5a);
                } else {
                    assert(memcmp(out, old, sizeof(out)) == 0);
                }
                assert(memcmp(src, before, sizeof(src)) == 0);
            }
    }
}

static void test_arguments(void)
{
    unsigned char src[N + 3], before[sizeof(src)], out[N + 5], old[sizeof(out)];
    const unsigned char *wrap_src = (const unsigned char *)(UINTPTR_MAX - N / 2);
    unsigned char *wrap_out = (unsigned char *)(UINTPTR_MAX - N / 2);
    fixture(src, sizeof(src), 7, 9, 11);
    memcpy(before, src, sizeof(src));
    memset(out, 0x5a, sizeof(out));
    memcpy(old, out, sizeof(out));
    assert(checked(5, 2, 1, NULL, N, out, sizeof(out)) == -EINVAL);
    assert(checked(5, 2, 1, src, sizeof(src), NULL, N) == -EINVAL);
    assert(checked(5, 2, 1, NULL, 0, NULL, 0) == -EINVAL);
    assert(checked(5, 2, 1, src, N - 1, out, sizeof(out)) == -EMSGSIZE);
    assert(checked(5, 2, 1, src, 0, out, sizeof(out)) == -EMSGSIZE);
    assert(checked(5, 2, 1, src, sizeof(src), out, N - 1) == -EMSGSIZE);
    assert(checked(5, 2, 1, src, sizeof(src), out, 0) == -EMSGSIZE);
    assert(checked(5, 2, 1, wrap_src, N, out, sizeof(out)) == -EOVERFLOW);
    assert(checked(5, 2, 1, src, sizeof(src), wrap_out, N) == -EOVERFLOW);
    assert(checked(5, 2, 1, src, SIZE_MAX, out, sizeof(out)) == -EOVERFLOW);
    assert(checked(5, 2, 1, src, sizeof(src), out, SIZE_MAX) == -EOVERFLOW);
    assert(checked(5, 2, 1, (const unsigned char *)(uintptr_t)1, N - 1,
                   out, sizeof(out)) == -EMSGSIZE);
    assert(checked(5, 8, 1, src, sizeof(src), out, sizeof(out)) == -ENOTSUP);
    assert(checked(5, 2, 0, src, sizeof(src), out, sizeof(out)) == -ENOTSUP);
    assert(memcmp(out, old, sizeof(out)) == 0);
    assert(memcmp(src, before, sizeof(src)) == 0);
}

static void test_alias(void)
{
    unsigned char arena[N * 4 + 40], old[sizeof(arena)];
    unsigned char *s, *d;
    size_t direction;
    fixture(arena, sizeof(arena), 3, 1536, 0);
    memcpy(old, arena, sizeof(arena));
    assert(checked(0, 0, 255, arena, N, arena, N) == -EINVAL);
    assert(checked(0, 0, 255, arena, N, arena + 1, N) == -EINVAL);
    assert(checked(0, 0, 255, arena + 1, N, arena, N) == -EINVAL);
    assert(checked(0, 0, 255, arena, N + 9, arena + N + 8, N) == -EINVAL);
    assert(checked(0, 0, 255, arena + N + 8, N, arena, N + 9) == -EINVAL);
    assert(memcmp(arena, old, sizeof(arena)) == 0);
    for (direction = 0; direction < 2; ++direction) {
        size_t offset;
        memset(arena, 0x5a, sizeof(arena));
        s = arena + 8 + (direction ? N + 7 : 0);
        d = arena + 8 + (direction ? 0 : N + 7);
        fixture(s, N + (direction ? 9 : 7), 3, 1536, 0);
        memcpy(old, arena, sizeof(arena));
        assert(checked(0, 3, 255, s, N + (direction ? 9 : 7),
                       d, N + (direction ? 7 : 9)) == 0);
        assert(get32(d) == 2 && get32(d + 4) == 1024 && get32(d + 8) == 0);
        assert(memcmp(d + 12, s + 12, N - 12) == 0);
        offset = (size_t)(d - arena);
        assert(memcmp(arena, old, offset) == 0);
        assert(memcmp(d + N, old + offset + N, sizeof(arena) - offset - N) == 0);
    }
}

static void test_unaligned(void)
{
    unsigned char src[N + 32], before[sizeof(src)], out[N + 32], old[sizeof(out)];
    size_t s, d;
    for (s = 0; s < 4; ++s)
        for (d = 0; d < 4; ++d) {
            memset(src, 0xc7, sizeof(src));
            fixture(src + s, N + 9, 0x80000001u, 1, 3);
            memcpy(before, src, sizeof(src));
            memset(out, 0x5a, sizeof(out));
            memcpy(old, out, sizeof(out));
            assert(checked(2, 6, 2, src + s, N + 9, out + d, N + 11) == 0);
            assert(get32(out + d) == 0xfffffffeu);
            assert(get32(out + d + 4) == 0xfffffffeu && get32(out + d + 8) == 1);
            assert(memcmp(out + d + 12, src + s + 12, N - 12) == 0);
            assert(memcmp(out, old, d) == 0);
            assert(memcmp(out + d + N, old + d + N, sizeof(out) - d - N) == 0);
            assert(memcmp(src, before, sizeof(src)) == 0);
        }
}

static void test_composed(void)
{
    unsigned char src[N * 2], before[sizeof(src)], out[N * 2];
    /* Static laboratory numbers in poisoned records, without a hardware format. */
    static const unsigned char first[12] = {3, 0, 0, 0, 0, 6, 0, 0, 9, 0, 0, 0};
    static const unsigned char second[12] = {0, 0, 0, 0, 1, 0, 0, 0, 0, 0, 0, 0};
    memset(src, 0xd3, N);
    memset(src + N, 0xb7, N);
    memcpy(src, first, sizeof(first));
    memcpy(src + N, second, sizeof(second));
    memcpy(before, src, sizeof(src));
    memset(out, 0x5a, sizeof(out));
    assert(checked(0, 3, 2, src, N, out, N) == 0);
    filled(out + N, N, 0x5a);
    assert(checked(1, 4, 255, src + N, N, out + N, N) == 0);
    assert(get32(out) == 2 && get32(out + 4) == 1024 && get32(out + 8) == 4);
    assert(get32(out + N) == 0x55555600u);
    assert(get32(out + N + 4) == 0 && get32(out + N + 8) == 0);
    assert(memcmp(out + 12, src + 12, N - 12) == 0);
    assert(memcmp(out + N + 12, src + N + 12, N - 12) == 0);
    assert(memcmp(src, before, sizeof(src)) == 0);
}

int main(int argc, char **argv)
{
    assert(argc == 2);
    if (strcmp(argv[1], "vectors") == 0) test_vectors();
    else if (strcmp(argv[1], "matrix") == 0) test_matrix();
    else if (strcmp(argv[1], "arguments") == 0) test_arguments();
    else if (strcmp(argv[1], "alias") == 0) test_alias();
    else if (strcmp(argv[1], "unaligned") == 0) test_unaligned();
    else if (strcmp(argv[1], "composed") == 0) test_composed();
    else assert(!"unknown HOST_TEST scenario");
    puts("HOST_TEST owned VBB numeric normalization passed");
    return 0;
}
