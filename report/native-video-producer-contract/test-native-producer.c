#include "native-producer.h"
#include "../native-video-au-contract/native-au.h"
#include "../native-video-paramsets/native-paramsets.h"
#include "../native-video-ring-contract/native-ring.h"
#include "../native-video-length-format/native-lengths.h"

#include <assert.h>
#include <errno.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

struct fixture { uint8_t source[128], baseline[128]; };
struct guarded_record { struct nproducer_record value; uint8_t tail[32]; };
struct guarded_plan { struct nproducer_publish_plan value; uint8_t tail[32]; };

static void putle(uint8_t *p, uint64_t v, size_t n)
{
    for (size_t i = 0; i < n; ++i) p[i] = (uint8_t)(v >> (8 * i));
}
static unsigned nibble(char c)
{
    assert((c >= '0' && c <= '9') || (c >= 'a' && c <= 'f'));
    return c <= '9' ? (unsigned)(c - '0') : (unsigned)(c - 'a' + 10);
}
static void unhex(uint8_t *out, size_t n, const char *s)
{
    assert(strlen(s) == 2 * n);
    for (size_t i = 0; i < n; ++i)
        out[i] = (uint8_t)((nibble(s[2 * i]) << 4) | nibble(s[2 * i + 1]));
}
static void init(struct fixture *f)
{
    for (size_t i = 0; i < sizeof(f->source); ++i) f->source[i] = (uint8_t)(i + 1);
    memset(f->baseline, 0xa5, sizeof(f->baseline));
}
static struct nproducer_record converted(struct fixture *f, uint8_t U,
    uint8_t G, uint8_t present, uint32_t next)
{
    struct guarded_record out, before;
    struct fixture original = *f;
    memset(&out, 0xd3, sizeof(out));
    memcpy(&before, &out, sizeof(out));
    errno = EDOM;
    assert(!nproducer_convert(f->source, 88, U, G, present, next,
        f->baseline, 96, &out.value, sizeof(out)));
    assert(errno == EDOM && !memcmp(f, &original, sizeof(*f)));
    assert(!memcmp(out.tail, before.tail, sizeof(out.tail)));
    return out.value;
}
static void mapping(void)
{
    struct fixture f;
    struct nproducer_record r;
    uint8_t wire[96], mask[96];
    init(&f);
    r = converted(&f, 0x80, 0, 1, UINT32_C(0xabcdef12));
    unhex(wire, 96,
        "04a30da4a5a5a5a50102030405060708"
        "090a0b0ca5a5a5a51112131415161718"
        "191a1b1c1d1e1f203b3c3534393a0113"
        "3738323151525354446484a4a5a5a5a5"
        "a5a5a5a5a7a5a5a5494a4b4c4d4e4f50"
        "3d3e3f404142434400a5ffffa5a5a5a5");
    unhex(mask, 96,
        "ff07ff0100000000ffffffffffffffff"
        "ffffffff00000000ffffffffffffffff"
        "ffffffffffffffffffffffffffffffff"
        "ffffffffffffffffffffffff00000000"
        "0000000003000000ffffffffffffffff"
        "ffffffffffffffffff00ffff00000000");
    assert(!memcmp(r.wire, wire, 96));
    assert(!memcmp(r.semantic_written_bits, mask, 96));
    for (size_t i = 0x3c; i < 0x44; ++i) assert(r.wire[i] == 0xa5);
    f.source[0x0e] = 0;
    f.baseline[3] = 0x2f;
    r = converted(&f, 0x80, 0x80, 1, UINT32_C(0x12340059));
    assert(r.wire[3] == 0xae && r.semantic_written_bits[3] == 1);
    assert(r.wire[2] == 0xa5 && r.semantic_written_bits[2] == 0);
    assert(r.wire[0x5a] == 0x59 && !r.wire[0x5b]);
    r = converted(&f, 0xff, 0, 1, UINT32_C(0x1234ffff));
    assert(r.wire[3] == 0xff && r.wire[0x5a] == 0xff && r.wire[0x5b] == 0xff);
    /* This is a distinct, explicit caller clear, as proved at K160664..70. */
    memset(f.baseline, 0, 96);
    r = converted(&f, 0, 0, 0, UINT32_MAX);
    for (size_t i = 0; i < 96; ++i)
        if (!r.semantic_written_bits[i]) assert(!r.wire[i]);
    f.source[0x35] = 0x40;
    r = converted(&f, 0, 0, 0, 0);
    assert(r.wire[0] == 0xff);
}
static void matrix(void)
{
    static const uint8_t types[8] = {0,0,1,1,9,2,3,3};
    static const uint8_t changes[8] = {0,4,2,6,1,5,3,7};
    static const uint8_t baselines[] = {0,0x2f,0xa5,0xff};
    struct fixture f;
    struct nproducer_record r;
    init(&f);
    for (unsigned a = 0; a < 256; ++a) {
        for (unsigned b = 0; b < 256; ++b) {
            f.source[0x0e] = (uint8_t)a;
            f.source[0x35] = (uint8_t)b;
            assert(!nproducer_convert(f.source, 88, (uint8_t)(a ^ b),
                (uint8_t)a, 1, UINT32_C(0x12345678), f.baseline, 96, &r, sizeof(r)));
            assert(r.wire[0] == ((a & 2) ? 4 : (b & 0x40) ? 0xff : types[(b >> 3) & 7]));
            assert(r.wire[1] == (0xa0 | changes[b & 7]));
            assert(r.wire[2] == ((a & 1) ? f.source[0xc] : 0xa5));
            assert(r.semantic_written_bits[2] == ((a & 1) ? 0xff : 0));
            assert(r.wire[0x58] == (b >= 128));
            assert(r.wire[0x5a] == ((a & 2) ? 0xff : 0x78));
            assert(r.wire[0x5b] == ((a & 2) ? 0xff : 0x56));
            assert(r.wire[0x34] == (a == 0 ? 0x51 : 0));
        }
    }
    for (size_t b = 0; b < sizeof(baselines); ++b) {
        f.baseline[3] = baselines[b];
        for (unsigned u = 0; u < 256; ++u) {
            r = converted(&f, (uint8_t)u, (uint8_t)u, 0, u);
            assert(r.wire[3] == ((baselines[b] & 0xfe) | u));
            assert(r.semantic_written_bits[3] == 1);
            for (size_t i = 0; i < 4; ++i)
                assert(r.wire[0x34 + i] == (u ? 0 : (uint8_t)(0x51 + i)));
        }
    }
}
static void convert_failure(const uint8_t *source, size_t size, uint8_t present,
    const uint8_t *baseline, size_t baseline_size, size_t capacity, int expected)
{
    struct guarded_record out, before;
    memset(&out, 0xa5, sizeof(out));
    memcpy(&before, &out, sizeof(out));
    errno = EDOM;
    assert(nproducer_convert(source, size, 0, 0, present, 0, baseline,
        baseline_size, &out.value, capacity) == expected);
    assert(errno == EDOM && !memcmp(&out, &before, sizeof(out)));
}
static void arguments(void)
{
    struct fixture f, original;
    struct nproducer_record r;
    init(&f);
    original = f;
    for (size_t n = 0; n < 88; ++n)
        convert_failure(f.source, n, 0, f.baseline, 96, sizeof(r), -ENODATA);
    for (size_t n = 0; n < 96; ++n)
        convert_failure(f.source, 88, 0, f.baseline, n, sizeof(r), -ENODATA);
    for (size_t n = 0; n < sizeof(r); ++n)
        convert_failure(f.source, 88, 0, f.baseline, 96, n, -ENOSPC);
    convert_failure(NULL, 88, 0, f.baseline, 96, sizeof(r), -EINVAL);
    convert_failure(f.source, 88, 0, NULL, 96, sizeof(r), -EINVAL);
    convert_failure(f.source, 89, 0, f.baseline, 96, sizeof(r), -EINVAL);
    convert_failure(f.source, 88, 0, f.baseline, 97, sizeof(r), -EINVAL);
    convert_failure(f.source, 88, 2, f.baseline, 96, sizeof(r), -EINVAL);
    convert_failure(f.source, 88, 255, f.baseline, 96, sizeof(r), -EINVAL);
    convert_failure((const uint8_t *)(uintptr_t)(UINTPTR_MAX - 40), 88,
        0, f.baseline, 96, sizeof(r), -EOVERFLOW);
    convert_failure(f.source, 88, 0,
        (const uint8_t *)(uintptr_t)(UINTPTR_MAX - 40), 96, sizeof(r), -EOVERFLOW);
    convert_failure(f.source, 88, 0, f.baseline, 96, SIZE_MAX, -EOVERFLOW);
    assert(nproducer_convert(f.source, 88, 0, 0, 0, 0, f.baseline,
        96, NULL, sizeof(r)) == -EINVAL);
    assert(!memcmp(&f, &original, sizeof(f)));
}
static void alias(void)
{
    uint8_t arena[640], before[640], source[88], baseline[96];
    struct nproducer_record *out = (struct nproducer_record *)(void *)arena;
    memset(arena, 0xa5, sizeof(arena));
    memset(source, 0x21, sizeof(source));
    memset(baseline, 0x43, sizeof(baseline));
    memcpy(before, arena, sizeof(arena));
    assert(nproducer_convert(arena, 88, 0, 0, 0, 0, baseline, 96,
        out, sizeof(*out)) == -EINVAL);
    assert(nproducer_convert(source, 88, 0, 0, 0, 0, arena + 100, 96,
        out, sizeof(*out)) == -EINVAL);
    assert(nproducer_convert(arena + 200, 88, 0, 0, 0, 0, baseline, 96,
        out, 400) == -EINVAL);
    assert(nproducer_convert(source, 88, 0, 0, 0, 0, arena + 200, 96,
        out, 400) == -EINVAL);
    assert(!memcmp(arena, before, sizeof(arena)));
    /* Adjacent spans, read/read overlap, and alignment-1 output are valid. */
    assert(!nproducer_convert(arena + 193, 88, 0, 0, 0, 0, arena + 193, 96,
        (struct nproducer_record *)(void *)(arena + 1), 192));
    assert(!memcmp(arena + 193, before + 193, sizeof(arena) - 193));
}
static struct nproducer_publish_plan plan_ok(uint64_t base, uint32_t count,
    uint64_t control, uint32_t current, uint32_t N, uint32_t occupied)
{
    struct guarded_plan out, before;
    memset(&out, 0xa5, sizeof(out));
    memcpy(&before, &out, sizeof(out));
    errno = EDOM;
    assert(!nproducer_plan_publish(base, count, control, current, N,
        occupied, &out.value, sizeof(out)));
    assert(errno == EDOM && !memcmp(out.tail, before.tail, sizeof(out.tail)));
    return out.value;
}
static void plan_failure(uint64_t base, uint32_t count, uint64_t control,
    uint32_t current, uint32_t N, uint32_t occupied, size_t capacity, int expected)
{
    struct guarded_plan out, before;
    memset(&out, 0xa5, sizeof(out));
    memcpy(&before, &out, sizeof(out));
    errno = EDOM;
    assert(nproducer_plan_publish(base, count, control, current, N, occupied,
        &out.value, capacity) == expected);
    assert(errno == EDOM && !memcmp(&out, &before, sizeof(out)));
}
static void plan(void)
{
    struct nproducer_publish_plan r;
    const uint32_t limit = UINT32_MAX / 96;
    _Alignas(struct nproducer_publish_plan) uint8_t unaligned[sizeof(r) + 1], before[sizeof(r) + 1];
    for (uint32_t N = 1; N <= 8; ++N) {
        for (uint32_t c = 0; c < N; ++c) {
            for (uint32_t used = 0; used <= N; ++used) {
                uint32_t j = c == N - 1 ? 0 : c + 1;
                r = plan_ok(0x1000, N + 2, 0x2000, c, N, used);
                assert(r.index == j && r.slot_address == 0x1000 + (uint64_t)j * 96);
                assert(r.control_index_address == 0x2004 && r.record_size == 96);
                assert(r.source_result == (used == N));
                assert(r.post_publication_queue_full == (used == N));
                assert(r.current_after == (used == N ? c : j));
                assert(r.occupied_after == (used == N ? N : used + 1));
            }
        }
    }
    r = plan_ok(0, 2, 0, 0, 7, 1); /* count != N, computed j still fits. */
    assert(r.index == 1 && r.slot_address == 96 && r.occupied_after == 2);
    r = plan_ok(0, 1, UINT64_MAX - 8, UINT32_MAX - 1, UINT32_MAX, UINT32_MAX - 1);
    assert(!r.index && r.occupied_after == UINT32_MAX && !r.source_result);
    r = plan_ok(0, 1, 0, UINT32_MAX - 1, UINT32_MAX, UINT32_MAX);
    assert(!r.index && r.source_result == 1 && r.current_after == UINT32_MAX - 1);
    r = plan_ok(0, limit + 1, 0, limit - 1, limit + 2, 0);
    assert(r.slot_address == (uint64_t)limit * 96);
    r = plan_ok(UINT64_MAX - 96, 1, 0, 0, 1, 0);
    assert(r.slot_address == UINT64_MAX - 96);
    plan_failure(0, 0, 0, 0, 1, 0, sizeof(r), -EINVAL);
    plan_failure(0, 1, 0, 0, 0, 0, sizeof(r), -EINVAL);
    plan_failure(0, 1, 0, 1, 1, 0, sizeof(r), -ERANGE);
    plan_failure(0, 1, 0, 0, 1, 2, sizeof(r), -ERANGE);
    plan_failure(0, 1, 0, 0, 7, 0, sizeof(r), -ERANGE);
    plan_failure(0, limit + 2, 0, limit, limit + 3, 0, sizeof(r), -EOVERFLOW);
    plan_failure(UINT64_MAX - 95, 1, 0, 0, 1, 0, sizeof(r), -EOVERFLOW);
    plan_failure(UINT64_MAX - 96, 2, 0, 1, 2, 0, sizeof(r), -EOVERFLOW);
    plan_failure(0, 1, UINT64_MAX - 7, 0, 1, 0, sizeof(r), -EOVERFLOW);
    plan_failure(0, 1, UINT64_MAX - 3, 0, 1, 0, sizeof(r), -EOVERFLOW);
    plan_failure(0, 1, UINT64_MAX, 0, 1, 0, sizeof(r), -EOVERFLOW);
    plan_failure(0, 1, 0, 0, 1, 0, SIZE_MAX, -EOVERFLOW);
    for (size_t cap = 0; cap < sizeof(r); ++cap)
        plan_failure(0, 1, 0, 0, 1, 0, cap, -ENOSPC);
    assert(nproducer_plan_publish(0, 1, 0, 0, 1, 0, NULL, sizeof(r)) == -EINVAL);
    memset(unaligned, 0xa5, sizeof(unaligned));
    memcpy(before, unaligned, sizeof(before));
    assert(nproducer_plan_publish(0, 1, 0, 0, 1, 0,
        (struct nproducer_publish_plan *)(void *)(unaligned + 1), sizeof(r)) == -EINVAL);
    assert(!memcmp(before, unaligned, sizeof(before)));
    assert(nproducer_plan_publish(0, 1, 0, 0, 1, 0,
        (struct nproducer_publish_plan *)(uintptr_t)(UINTPTR_MAX -
        (_Alignof(struct nproducer_publish_plan) - 1)), sizeof(r)) == -EOVERFLOW);
}
static void existing(void)
{
    static const uint8_t gvalues[] = {0,0x10,0x28,0x30,0x20};
    static const uint8_t types[] = {0,1,2,3,9};
    const uint64_t base = UINT64_C(0x100000000);
    struct fixture f;
    struct nproducer_record r;
    struct nvideo_info info;
    struct nau au;
    struct nparamsets sets;
    uint8_t es[64];
    init(&f);
    memset(f.baseline, 0, 96); /* Explicit source-caller baseline. */
    for (size_t i = 0; i < sizeof(es); ++i) es[i] = (uint8_t)(0xf3 ^ i);
    putle(f.source, base + 7, 8);
    putle(f.source + 8, 13, 4);
    putle(f.source + 0x10, UINT64_C(0xfedcba9876543210), 8);
    putle(f.source + 0x18, UINT64_C(0x8877665544332211), 8);
    f.source[0x0e] = 0;
    for (size_t t = 0; t < sizeof(types); ++t) {
        f.source[0x35] = gvalues[t];
        r = converted(&f, 0x80, 0, 0, 0);
        assert(nvideo_parse_info(r.wire, 96, base, sizeof(es), &info) == NVIDEO_OK);
        assert(info.type == types[t] && info.length == 13 && info.address == base + 7);
        assert(info.pts == UINT64_C(0xfedcba9876543210));
        assert(info.dts == UINT64_C(0x8877665544332211));
        assert(!nau_resolve(r.wire, 96, 0, base, es, sizeof(es), &au, sizeof(au)));
        assert(au.span_count == 1 && au.total_length == 13 && au.spans[0].data == es + 7);
        assert(!memcmp(au.spans[0].data, es + 7, 13));
    }
    f.source[0x35] = 0x40;
    r = converted(&f, 0, 0, 0, 0);
    assert(r.wire[0] == 0xff);
    assert(nvideo_parse_info(r.wire, 96, base, sizeof(es), &info) == NVIDEO_UNSUPPORTED);
    assert(nau_resolve(r.wire, 96, 0, base, es, sizeof(es), &au, sizeof(au)) == -ENOTSUP);
    /* Structural HOST parameter bytes, no claim of native encoding/decoding. */
    memset(es, 0, sizeof(es));
    es[10] = 2; es[11] = 0x67; es[12] = 0x42; /* BE32(2)+SPS at offset 7. */
    es[16] = 2; es[17] = 0x68; es[18] = 0xce; /* BE32(2)+PPS at offset 13. */
    f.source[0x0e] = 2;
    f.source[0x35] = 3; /* Source bit1 SPS and bit0 PPS become V1 bits1/2. */
    putle(f.source + 0x3a, 0, 2); f.source[0x34] = 0; f.source[0x33] = 0xf1;
    putle(f.source + 0x38, 6, 2); f.source[0x32] = 0x25;
    putle(f.source + 0x36, 6, 2); f.source[0x31] = 1; f.source[0x30] = 6;
    r = converted(&f, 0, 0, 1, 0x12345678);
    assert(r.wire[0] == 4 && r.wire[1] == 6);
    assert(nvideo_parse_info(r.wire, 96, base, sizeof(es), &info) == NVIDEO_UNSUPPORTED);
    assert(!nparamsets_parse(r.wire, 96, NPARAMSETS_AVC1, 0, base, es,
        sizeof(es), &sets, sizeof(sets)));
    assert(sets.sps.nal == es + 11 && sets.sps.nal_size == 2 && sets.sps.source_id == 5);
    assert(sets.pps.nal == es + 17 && sets.pps.nal_size == 2 && sets.pps.source_id == 6);
    assert(sets.sps.changed && sets.pps.changed && !sets.vps.changed);
    assert(nvideo_native_gaps() == 63);
}
static void composed(void)
{
    /* Structural HOST fixture; these bytes do not assert an original encoder. */
    static const uint8_t payload[] = {0,0,0,4,0x65,0,0x80,0xff};
    const uint64_t es_base = UINT64_C(0x100000000), slot_base = 0x9000;
    struct fixture f;
    struct nproducer_record record;
    struct nproducer_publish_plan publish;
    struct nring_user user = {7,1,1};
    struct nring_advance release;
    struct nau au;
    uint8_t ring[2 * 96], read_list[96], es[64], consumed[sizeof(payload)];
    size_t borrowed = 0, nal_count = 0, consumed_bytes = 0;
    uint32_t published_index;
    init(&f);
    memset(f.baseline, 0, 96); /* Actual caller clear is a separate input event. */
    memset(ring, 0xa5, sizeof(ring));
    memset(es, 0xd3, sizeof(es));
    for (size_t i = 0; i < sizeof(payload); ++i) es[(62 + i) % sizeof(es)] = payload[i];
    putle(f.source, es_base + 62, 8);
    putle(f.source + 8, sizeof(payload), 4);
    putle(f.source + 0x10, UINT64_C(0xfedcba9876543210), 8);
    putle(f.source + 0x18, UINT64_C(0x8877665544332211), 8);
    f.source[0x0e] = 1; f.source[0x35] = 0; f.source[0x0c] = 0xa3;
    record = converted(&f, 0x80, 0, 1, 0x12340059);
    publish = plan_ok(slot_base, 2, 0xa000, 1, 2, 0);
    assert(publish.index == 0 && publish.slot_address == slot_base);
    assert(!publish.source_result && publish.occupied_after == 1);
    /* Software-test copy/index only; no native DSB, ACK, or ES lease claim. */
    memcpy(ring + (size_t)(publish.slot_address - slot_base), record.wire, publish.record_size);
    published_index = publish.index;
    assert(!nring_copy_read_list(ring, sizeof(ring), 2, published_index,
        user.read_index, read_list, sizeof(read_list), &borrowed));
    assert(borrowed == 1 && !memcmp(read_list, record.wire, 96));
    assert(!nau_resolve(read_list, 96, 0, es_base, es, sizeof(es), &au, sizeof(au)));
    assert(au.span_count == 2 && au.info.address == es_base + 62);
    assert(au.info.type == 0 && au.info.keyframe && au.info.padding == 0xa3 && !au.info.unit);
    assert(au.info.pts == UINT64_C(0xfedcba9876543210));
    assert(au.info.dts == UINT64_C(0x8877665544332211));
    assert(!memcmp(au.raw_info, record.wire, 96));
    assert(!nlength_validate(read_list, 96, 0, es_base, es, sizeof(es),
        NLENGTH_AVC1, &nal_count));
    assert(nal_count == 1);
    for (size_t i = 0; i < au.span_count; ++i) {
        assert(au.spans[i].length <= sizeof(consumed) - consumed_bytes);
        memcpy(consumed + consumed_bytes, au.spans[i].data, au.spans[i].length);
        consumed_bytes += au.spans[i].length;
    }
    assert(consumed_bytes == sizeof(payload) && !memcmp(consumed, payload, sizeof(payload)));
    assert(!nring_advance_read(&user, 1, user.id, borrowed, borrowed, 2,
        published_index, user.read_index, &release));
    assert(!release.user_read_index && !release.shared_read_index && release.delta == 1);
    assert(user.read_index == 1 && !memcmp(ring, record.wire, 96));
    assert(nvideo_native_gaps() == 63);
}
int main(int argc, char **argv)
{
    assert(argc == 2);
    if (!strcmp(argv[1], "mapping")) mapping();
    else if (!strcmp(argv[1], "matrix")) matrix();
    else if (!strcmp(argv[1], "arguments")) arguments();
    else if (!strcmp(argv[1], "alias")) alias();
    else if (!strcmp(argv[1], "plan")) plan();
    else if (!strcmp(argv[1], "existing")) existing();
    else if (!strcmp(argv[1], "composed")) composed();
    else abort();
    puts("HOST_TEST producer metadata and pure publication plan passed");
    return 0;
}
