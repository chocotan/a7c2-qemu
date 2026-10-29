#include "native-paramsets.h"

#include <assert.h>
#include <errno.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define ES_BASE UINT64_C(0x100000000)
#define CORRECTION UINT64_C(0x4000)
#define FIRST_OFFSET 17u

/* Structural HOST fixtures; only the separate FFmpeg test proves decoding. */
static const uint8_t avc_sps[] = {0x67, 0x42, 0x00, 0x0a, 0xf4, 0x4b, 0x20};
static const uint8_t avc_pps[] = {0x68, 0xce, 0x0f, 0xc8};
static const uint8_t hevc_vps[] = {0x40, 0x01, 0xac, 0x00};
static const uint8_t hevc_sps[] = {0x42, 0x01, 0x01, 0x60, 0x00};
static const uint8_t hevc_pps[] = {0x44, 0x01, 0xc0};

struct fixture {
    uint8_t info[NPARAMSETS_INFO_BYTES], es[256];
    uint32_t codec;
};
struct guarded {
    struct nparamsets value;
    uint8_t tail[32];
};

static void putle(uint8_t *p, uint64_t v, size_t n)
{
    for (size_t i = 0; i < n; ++i) p[i] = (uint8_t)(v >> (8 * i));
}
static void putbe(uint8_t *p, uint32_t v)
{
    for (unsigned i = 0; i < 4; ++i) p[i] = (uint8_t)(v >> (24 - 8 * i));
}
static size_t add_group(struct fixture *f, size_t position, size_t field,
    const uint8_t *nal, size_t n, uint8_t id)
{
    putbe(f->es + position, (uint32_t)n);
    memcpy(f->es + position + 4, nal, n);
    putle(f->info + field, 4 + n, 2);
    f->info[field + 2] = 1;
    f->info[field + 3] = id;
    return position + 4 + n;
}
static void init(struct fixture *f, uint32_t codec)
{
    size_t position = FIRST_OFFSET;
    memset(f, 0xd3, sizeof(*f));
    f->codec = codec;
    f->info[0] = 4;
    f->info[1] = 0xe7;
    putle(f->info + 8, ES_BASE + FIRST_OFFSET - CORRECTION, 8);
    putle(f->info + 0x10, 0, 4);
    putle(f->info + 0x28, 0, 2);
    f->info[0x2a] = 0;
    f->info[0x2b] = 0xf1;
    if (codec == NPARAMSETS_HVC1)
        position = add_group(f, position, 0x28, hevc_vps, sizeof(hevc_vps), 0xf1);
    position = add_group(f, position, 0x2c,
        codec == NPARAMSETS_AVC1 ? avc_sps : hevc_sps,
        codec == NPARAMSETS_AVC1 ? sizeof(avc_sps) : sizeof(hevc_sps), 0xf2);
    (void)add_group(f, position, 0x30,
        codec == NPARAMSETS_AVC1 ? avc_pps : hevc_pps,
        codec == NPARAMSETS_AVC1 ? sizeof(avc_pps) : sizeof(hevc_pps), 0xf3);
}
static int parse(const struct fixture *f, struct nparamsets *out, size_t cap)
{
    return nparamsets_parse(f->info, sizeof(f->info), f->codec, CORRECTION,
        ES_BASE, f->es, sizeof(f->es), out, cap);
}
static struct nparamsets success(const struct fixture *f)
{
    struct guarded out, before;
    struct fixture original = *f;
    memset(&out, 0xa5, sizeof(out));
    memcpy(&before, &out, sizeof(out));
    assert(parse(f, &out.value, sizeof(out)) == 0);
    assert(!memcmp(out.tail, before.tail, sizeof(out.tail)));
    assert(!memcmp(f, &original, sizeof(*f)));
    return out.value;
}
static void failure(const struct fixture *f, int expected)
{
    struct guarded out, before;
    struct fixture original = *f;
    memset(&out, 0xa5, sizeof(out));
    memcpy(&before, &out, sizeof(out));
    assert(parse(f, &out.value, sizeof(out)) == expected);
    assert(!memcmp(&out, &before, sizeof(out)));
    assert(!memcmp(f, &original, sizeof(*f)));
}
static void check_group(const struct nparamsets_group *g, const struct fixture *f,
    size_t offset, const uint8_t *nal, size_t n, uint8_t id)
{
    assert(g->nal == f->es + offset + 4 && g->nal_size == n);
    assert(g->es_offset == offset && g->span == 4 + n);
    assert(g->count == 1 && g->source_id == id && g->changed == 1);
    assert(!memcmp(g->nal, nal, n));
}
static void avc(void)
{
    struct fixture f;
    struct nparamsets r;
    init(&f, NPARAMSETS_AVC1);
    r = success(&f);
    assert(r.container_type == f.codec && r.info_type == 4);
    assert(r.change_flags == 0xe7 && r.declared_length == 0);
    assert(r.wire_address == ES_BASE + FIRST_OFFSET - CORRECTION);
    assert(r.address_correction == CORRECTION);
    assert(r.corrected_address == ES_BASE + FIRST_OFFSET);
    assert(r.es_base == ES_BASE && r.es_capacity == sizeof(f.es));
    assert(r.group_bytes == 8 + sizeof(avc_sps) + sizeof(avc_pps));
    assert(!r.vps.nal && !r.vps.nal_size && !r.vps.span && !r.vps.count);
    assert(r.vps.es_offset == FIRST_OFFSET && r.vps.source_id == 0xf1);
    assert(r.vps.changed == 1);
    check_group(&r.sps, &f, FIRST_OFFSET, avc_sps, sizeof(avc_sps), 0xf2);
    check_group(&r.pps, &f, FIRST_OFFSET + 4 + sizeof(avc_sps),
        avc_pps, sizeof(avc_pps), 0xf3);
}
static void hevc(void)
{
    struct fixture f;
    struct nparamsets r;
    init(&f, NPARAMSETS_HVC1);
    r = success(&f);
    assert(r.group_bytes == 12 + sizeof(hevc_vps) + sizeof(hevc_sps) + sizeof(hevc_pps));
    check_group(&r.vps, &f, FIRST_OFFSET, hevc_vps, sizeof(hevc_vps), 0xf1);
    check_group(&r.sps, &f, FIRST_OFFSET + 4 + sizeof(hevc_vps),
        hevc_sps, sizeof(hevc_sps), 0xf2);
    check_group(&r.pps, &f, FIRST_OFFSET + 8 + sizeof(hevc_vps) + sizeof(hevc_sps),
        hevc_pps, sizeof(hevc_pps), 0xf3);
}
static void changes(void)
{
    struct fixture f;
    struct nparamsets r;
    init(&f, NPARAMSETS_HVC1);
    for (unsigned flags = 0; flags < 256; ++flags) {
        f.info[1] = (uint8_t)flags;
        r = success(&f);
        assert(r.change_flags == flags);
        assert(r.vps.changed == ((flags >> 0) & 1));
        assert(r.sps.changed == ((flags >> 1) & 1));
        assert(r.pps.changed == ((flags >> 2) & 1));
        assert(r.sps.es_offset == FIRST_OFFSET + 4 + sizeof(hevc_vps));
        assert(r.pps.es_offset == FIRST_OFFSET + 8 + sizeof(hevc_vps) + sizeof(hevc_sps));
        assert(!memcmp(r.pps.nal, hevc_pps, sizeof(hevc_pps)));
    }
    /* An unchanged group must still be bounded and structurally valid. */
    f.info[1] = 0;
    f.es[FIRST_OFFSET + 4] |= 0x80;
    failure(&f, -EINVAL);
}
static void opaque(void)
{
    struct fixture f;
    struct nparamsets r;
    init(&f, NPARAMSETS_AVC1);
    for (unsigned id = 0; id < 256; ++id) {
        f.info[0x2b] = (uint8_t)id;
        f.info[0x2f] = (uint8_t)(255 - id);
        f.info[0x33] = (uint8_t)id;
        r = success(&f);
        assert(r.vps.source_id == id && r.pps.source_id == id);
        assert(r.sps.source_id == 255 - id);
        assert(!memcmp(r.sps.nal, avc_sps, sizeof(avc_sps)));
    }
    /* Opaque/reserved bytes need not be zero or match NAL/RBSP identities. */
    memset(f.info + 0x34, 0xff, sizeof(f.info) - 0x34);
    (void)success(&f);
}
static void declared(void)
{
    const uint32_t values[] = {0, 1, 19, UINT32_MAX};
    struct fixture f;
    init(&f, NPARAMSETS_AVC1);
    for (size_t i = 0; i < sizeof(values) / sizeof(values[0]); ++i) {
        struct nparamsets r;
        putle(f.info + 0x10, values[i], 4);
        r = success(&f);
        assert(r.declared_length == values[i]);
        assert(r.group_bytes == 8 + sizeof(avc_sps) + sizeof(avc_pps));
    }
}
static void types(void)
{
    struct fixture f;
    init(&f, NPARAMSETS_AVC1);
    for (unsigned type = 0; type < 256; ++type) {
        if (type == 4) continue;
        f.info[0] = (uint8_t)type;
        failure(&f, -ENOTSUP);
    }
    f.info[0] = 4;
    f.codec = 1; failure(&f, -ENOTSUP);
    f.codec = UINT32_C(0x31637661); failure(&f, -ENOTSUP);
    f.codec = UINT32_C(0x68657631); failure(&f, -ENOTSUP);
    f.codec = 0; failure(&f, -ENOTSUP);
}
static void missing(void)
{
    struct fixture f;
    const size_t fields[] = {0x28, 0x2c, 0x30};
    for (size_t i = 0; i < 3; ++i) {
        init(&f, NPARAMSETS_HVC1);
        f.info[fields[i] + 2] = 0;
        failure(&f, -ENODATA);
        init(&f, NPARAMSETS_HVC1);
        putle(f.info + fields[i], 0, 2);
        failure(&f, -ENODATA);
    }
    init(&f, NPARAMSETS_AVC1);
    f.info[0x2e] = 0; failure(&f, -ENODATA);
    init(&f, NPARAMSETS_AVC1);
    f.info[0x32] = 0; failure(&f, -ENODATA);
}
static void counts(void)
{
    struct fixture f;
    for (unsigned count = 2; count < 256; ++count) {
        const size_t fields[] = {0x2a, 0x2e, 0x32};
        for (size_t i = 0; i < 3; ++i) {
            init(&f, NPARAMSETS_HVC1);
            f.info[fields[i]] = (uint8_t)count;
            failure(&f, -ENOTSUP);
        }
    }
    init(&f, NPARAMSETS_AVC1);
    f.info[0x32] = 2; failure(&f, -ENOTSUP);
    init(&f, NPARAMSETS_AVC1);
    f.info[0x2a] = 1; failure(&f, -ENOTSUP);
    init(&f, NPARAMSETS_AVC1);
    f.info[0x28] = 1; failure(&f, -ENOTSUP);
}
static void spans(void)
{
    struct fixture f;
    for (unsigned span = 1; span < 4; ++span) {
        init(&f, NPARAMSETS_AVC1);
        putle(f.info + 0x2c, span, 2);
        failure(&f, -ENODATA);
    }
    init(&f, NPARAMSETS_AVC1);
    putle(f.info + 0x2c, 5 + sizeof(avc_sps), 2);
    failure(&f, -EINVAL); /* Unknown extra byte inside a single-NAL span. */
    init(&f, NPARAMSETS_AVC1);
    putle(f.info + 0x2c, 3 + sizeof(avc_sps), 2);
    failure(&f, -ENODATA);
    init(&f, NPARAMSETS_HVC1);
    putle(f.info + 0x28, UINT16_MAX, 2);
    putle(f.info + 0x2c, UINT16_MAX, 2);
    putle(f.info + 0x30, UINT16_MAX, 2);
    failure(&f, -ERANGE);
}
static void lengths(void)
{
    struct fixture f;
    struct nparamsets r;
    const uint32_t values[] = {0, 1, 8, UINT32_MAX};
    const int statuses[] = {-ENODATA, -EINVAL, -ENODATA, -ENODATA};
    for (size_t i = 0; i < sizeof(values) / sizeof(values[0]); ++i) {
        init(&f, NPARAMSETS_AVC1);
        putbe(f.es + FIRST_OFFSET, values[i]);
        failure(&f, statuses[i]);
    }
    init(&f, NPARAMSETS_AVC1);
    /* LE32 and lengths including the four-byte word are rejected. */
    putle(f.es + FIRST_OFFSET, sizeof(avc_sps), 4);
    failure(&f, -ENODATA);
    init(&f, NPARAMSETS_AVC1);
    putbe(f.es + FIRST_OFFSET, 4 + sizeof(avc_sps));
    failure(&f, -ENODATA);
    init(&f, NPARAMSETS_AVC1);
    r = success(&f);
    putbe(f.es + r.pps.es_offset, 0);
    failure(&f, -ENODATA); /* Failure in the last group leaves no partial output. */
}
static void headers(void)
{
    struct fixture f;
    struct nparamsets r;
    init(&f, NPARAMSETS_AVC1);
    f.es[FIRST_OFFSET + 4] |= 0x80; failure(&f, -EINVAL);
    init(&f, NPARAMSETS_AVC1);
    f.es[FIRST_OFFSET + 4] = 0x68; failure(&f, -EINVAL);
    init(&f, NPARAMSETS_AVC1);
    r = success(&f);
    f.es[r.pps.es_offset + 4] = 0x67; failure(&f, -EINVAL);
    init(&f, NPARAMSETS_AVC1);
    memcpy(f.es + FIRST_OFFSET + 4, "\x00\x00\x00\x01", 4);
    failure(&f, -EINVAL);
    init(&f, NPARAMSETS_HVC1);
    f.es[FIRST_OFFSET + 4] |= 0x80; failure(&f, -EINVAL);
    init(&f, NPARAMSETS_HVC1);
    f.es[FIRST_OFFSET + 5] = 0; failure(&f, -EINVAL);
    init(&f, NPARAMSETS_HVC1);
    f.es[FIRST_OFFSET + 4] = 0x42; failure(&f, -EINVAL);
    init(&f, NPARAMSETS_HVC1);
    putle(f.info + 0x28, 5, 2);
    putbe(f.es + FIRST_OFFSET, 1);
    failure(&f, -ENODATA);
    /* Layer ID is not guessed to be zero; nonzero temporal-id-plus-one works. */
    init(&f, NPARAMSETS_HVC1);
    f.es[FIRST_OFFSET + 4] |= 1;
    f.es[FIRST_OFFSET + 5] = 0xff;
    (void)success(&f);
}
static void ranges(void)
{
    struct fixture f;
    struct nparamsets out, before;
    int rc;
    init(&f, NPARAMSETS_AVC1);
    putle(f.info + 8, UINT64_MAX, 8);
    failure(&f, -EOVERFLOW);
    init(&f, NPARAMSETS_AVC1);
    putle(f.info + 8, UINT64_MAX - CORRECTION - 1, 8);
    failure(&f, -EOVERFLOW);
    init(&f, NPARAMSETS_AVC1);
    putle(f.info + 8, ES_BASE - CORRECTION - 1, 8);
    failure(&f, -ERANGE);
    init(&f, NPARAMSETS_AVC1);
    putle(f.info + 8, ES_BASE + sizeof(f.es) - CORRECTION, 8);
    failure(&f, -ERANGE);
    init(&f, NPARAMSETS_AVC1);
    memset(&out, 0xa5, sizeof(out));
    memcpy(&before, &out, sizeof(out));
    rc = nparamsets_parse(f.info, sizeof(f.info), f.codec, CORRECTION,
        UINT64_MAX - 1, f.es, sizeof(f.es), &out, sizeof(out));
    assert(rc == -EOVERFLOW && !memcmp(&out, &before, sizeof(out)));
    rc = nparamsets_parse(f.info, sizeof(f.info), f.codec, CORRECTION,
        ES_BASE, f.es, FIRST_OFFSET + 18, &out, sizeof(out));
    assert(rc == -ERANGE && !memcmp(&out, &before, sizeof(out)));
    /* An explicitly known zero correction is legal; a wire address isn't a host pointer. */
    putle(f.info + 8, ES_BASE + FIRST_OFFSET, 8);
    rc = nparamsets_parse(f.info, sizeof(f.info), f.codec, 0,
        ES_BASE, f.es, sizeof(f.es), &out, sizeof(out));
    assert(!rc && out.address_correction == 0 && out.wire_address == out.corrected_address);
}
static void capacity(void)
{
    struct fixture f;
    struct guarded out, before;
    init(&f, NPARAMSETS_AVC1);
    memset(&out, 0xa5, sizeof(out));
    memcpy(&before, &out, sizeof(out));
    for (size_t n = 0; n < sizeof(out.value); ++n) {
        assert(parse(&f, &out.value, n) == -ENOSPC);
        assert(!memcmp(&out, &before, sizeof(out)));
    }
    (void)success(&f);
    assert(parse(&f, &out.value, SIZE_MAX) == -EOVERFLOW);
    assert(!memcmp(&out, &before, sizeof(out)));
}
static void alias(void)
{
    union arena {
        max_align_t align;
        uint8_t bytes[2048];
    } a, original;
    struct fixture f;
    uint8_t *info = a.bytes + 1024, *es = a.bytes + 1536;
    struct nparamsets *out = (struct nparamsets *)(void *)a.bytes;
    int rc;
    init(&f, NPARAMSETS_AVC1);
    memset(&a, 0xa5, sizeof(a));
    memcpy(info, f.info, sizeof(f.info));
    memcpy(es, f.es, sizeof(f.es));
    memcpy(&original, &a, sizeof(a));
    /* Only the output's unused capacity tail overlaps the immutable input. */
    rc = nparamsets_parse(info, sizeof(f.info), f.codec, CORRECTION,
        ES_BASE, es, sizeof(f.es), out, 1025);
    assert(rc == -EINVAL && !memcmp(&a, &original, sizeof(a)));
    rc = nparamsets_parse(f.info, sizeof(f.info), f.codec, CORRECTION,
        ES_BASE, es, sizeof(f.es), out, 1537);
    assert(rc == -EINVAL && !memcmp(&a, &original, sizeof(a)));
    rc = nparamsets_parse(info, sizeof(f.info), f.codec, CORRECTION,
        ES_BASE, es, sizeof(f.es), (struct nparamsets *)(void *)es, sizeof(*out));
    assert(rc == -EINVAL && !memcmp(&a, &original, sizeof(a)));
    rc = nparamsets_parse(info, sizeof(f.info), f.codec, CORRECTION,
        ES_BASE, es, sizeof(f.es), (struct nparamsets *)(void *)(a.bytes + 1), sizeof(*out));
    assert(rc == -EINVAL && !memcmp(&a, &original, sizeof(a)));
    /* Input info and ES may alias: both are immutable, and all reads precede output. */
    init(&f, NPARAMSETS_AVC1);
    memcpy(a.bytes + 512, f.info, sizeof(f.info));
    memcpy(a.bytes + 512 + 128, f.es + FIRST_OFFSET,
        8 + sizeof(avc_sps) + sizeof(avc_pps));
    putle(a.bytes + 512 + 8, ES_BASE + 128 - CORRECTION, 8);
    rc = nparamsets_parse(a.bytes + 512, sizeof(f.info), f.codec, CORRECTION,
        ES_BASE, a.bytes + 512, 256, out, sizeof(*out));
    assert(!rc && out->sps.nal == a.bytes + 512 + 132);
}
static void arguments(void)
{
    struct fixture f;
    struct nparamsets out, before;
    init(&f, NPARAMSETS_AVC1);
    memset(&out, 0xa5, sizeof(out));
    memcpy(&before, &out, sizeof(out));
    for (size_t n = 0; n < NPARAMSETS_INFO_BYTES; ++n) {
        assert(nparamsets_parse(f.info, n, f.codec, CORRECTION,
            ES_BASE, f.es, sizeof(f.es), &out, sizeof(out)) == -ENODATA);
        assert(!memcmp(&out, &before, sizeof(out)));
    }
    assert(nparamsets_parse(f.info, sizeof(f.info) + 1, f.codec, CORRECTION,
        ES_BASE, f.es, sizeof(f.es), &out, sizeof(out)) == -EINVAL);
    assert(nparamsets_parse(NULL, sizeof(f.info), f.codec, CORRECTION,
        ES_BASE, f.es, sizeof(f.es), &out, sizeof(out)) == -EINVAL);
    assert(nparamsets_parse(f.info, sizeof(f.info), f.codec, CORRECTION,
        ES_BASE, NULL, sizeof(f.es), &out, sizeof(out)) == -EINVAL);
    assert(nparamsets_parse(f.info, sizeof(f.info), f.codec, CORRECTION,
        ES_BASE, f.es, 0, &out, sizeof(out)) == -ENODATA);
    assert(parse(&f, NULL, sizeof(out)) == -EINVAL);
    assert(!memcmp(&out, &before, sizeof(out)));
}
static void pointer_wrap(void)
{
    struct fixture f;
    struct nparamsets out, before;
    const uint8_t *bad = (const uint8_t *)(uintptr_t)(UINTPTR_MAX - 1);
    init(&f, NPARAMSETS_AVC1);
    memset(&out, 0xa5, sizeof(out));
    memcpy(&before, &out, sizeof(out));
    /* Never dereference these numerical probes, including under sanitizers. */
    assert(nparamsets_parse(bad, sizeof(f.info), f.codec, CORRECTION,
        ES_BASE, f.es, sizeof(f.es), &out, sizeof(out)) == -EOVERFLOW);
    assert(nparamsets_parse(f.info, sizeof(f.info), f.codec, CORRECTION,
        ES_BASE, bad, sizeof(f.es), &out, sizeof(out)) == -EOVERFLOW);
    assert(nparamsets_parse(f.info, sizeof(f.info), f.codec, CORRECTION,
        ES_BASE, f.es, sizeof(f.es), (struct nparamsets *)(uintptr_t)(UINTPTR_MAX - 1),
        sizeof(out)) == -EOVERFLOW);
    assert(!memcmp(&out, &before, sizeof(out)));
}
static void exact_bounds(void)
{
    struct fixture f;
    struct nparamsets out;
    uint8_t *info, *es;
    const size_t total = 8 + sizeof(avc_sps) + sizeof(avc_pps);
    int rc;
    init(&f, NPARAMSETS_AVC1);
    info = malloc(sizeof(f.info)); es = malloc(total);
    assert(info && es);
    memcpy(info, f.info, sizeof(f.info));
    memcpy(es, f.es + FIRST_OFFSET, total);
    putle(info + 8, ES_BASE - CORRECTION, 8);
    rc = nparamsets_parse(info, sizeof(f.info), f.codec, CORRECTION,
        ES_BASE, es, total, &out, sizeof(out));
    assert(!rc && out.pps.nal + out.pps.nal_size == es + total);
    /* The mapping truly ends here; no inferred circular/segmented continuation. */
    rc = nparamsets_parse(info, sizeof(f.info), f.codec, CORRECTION,
        ES_BASE, es, total - 1, &out, sizeof(out));
    assert(rc == -ERANGE);
    free(es); free(info);
}
static int host_roundtrip(void)
{
    uint8_t info[NPARAMSETS_INFO_BYTES];
    uint8_t es[3 * 65535 + 256], prefix[4];
    size_t n;
    struct nparamsets r;
    assert(fread(info, 1, sizeof(info), stdin) == sizeof(info));
    n = fread(es, 1, sizeof(es), stdin);
    assert(!ferror(stdin) && feof(stdin));
    assert(nparamsets_parse(info, sizeof(info), NPARAMSETS_AVC1, CORRECTION,
        ES_BASE, es, n, &r, sizeof(r)) == 0);
    assert(r.vps.count == 0 && r.sps.count == 1 && r.pps.count == 1);
    assert(r.corrected_address == ES_BASE + FIRST_OFFSET);
    assert(r.declared_length == 0 && r.change_flags == 0xe6);
    assert(r.sps.source_id == 0xf2 && r.pps.source_id == 0xf3);
    assert(r.sps.changed && r.pps.changed);
    /* HOST_TEST framing only, so Python can compare both pure NALs separately. */
    putbe(prefix, (uint32_t)r.sps.nal_size);
    assert(fwrite(prefix, 1, 4, stdout) == 4);
    assert(fwrite(r.sps.nal, 1, r.sps.nal_size, stdout) == r.sps.nal_size);
    putbe(prefix, (uint32_t)r.pps.nal_size);
    assert(fwrite(prefix, 1, 4, stdout) == 4);
    assert(fwrite(r.pps.nal, 1, r.pps.nal_size, stdout) == r.pps.nal_size);
    return fflush(stdout) ? 1 : 0;
}
int main(int argc, char **argv)
{
    assert(argc == 2);
    if (!strcmp(argv[1], "host-roundtrip")) return host_roundtrip();
    if (!strcmp(argv[1], "avc")) avc();
    else if (!strcmp(argv[1], "hevc")) hevc();
    else if (!strcmp(argv[1], "changes")) changes();
    else if (!strcmp(argv[1], "opaque")) opaque();
    else if (!strcmp(argv[1], "declared")) declared();
    else if (!strcmp(argv[1], "types")) types();
    else if (!strcmp(argv[1], "missing")) missing();
    else if (!strcmp(argv[1], "counts")) counts();
    else if (!strcmp(argv[1], "spans")) spans();
    else if (!strcmp(argv[1], "lengths")) lengths();
    else if (!strcmp(argv[1], "headers")) headers();
    else if (!strcmp(argv[1], "ranges")) ranges();
    else if (!strcmp(argv[1], "capacity")) capacity();
    else if (!strcmp(argv[1], "alias")) alias();
    else if (!strcmp(argv[1], "arguments")) arguments();
    else if (!strcmp(argv[1], "pointer-wrap")) pointer_wrap();
    else if (!strcmp(argv[1], "exact-bounds")) exact_bounds();
    else return 2;
    return 0;
}
