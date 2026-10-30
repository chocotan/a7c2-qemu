#include "functional-face-proc.h"

#include <assert.h>
#include <errno.h>
#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

struct document {
    char text[8192];
    size_t used;
};

static unsigned parser_calls;

static void append(struct document *d, const char *format, ...)
{
    va_list args;
    int n;
    va_start(args, format);
    n = vsnprintf(d->text + d->used, sizeof(d->text) - d->used, format, args);
    va_end(args);
    assert(n >= 0 && (size_t)n < sizeof(d->text) - d->used);
    d->used += (size_t)n;
}

static void start(struct document *d)
{
    unsigned i;
    d->used = 0;
    append(d, "Information on Units.\n");
    append(d, "handle   type      status  alloc  open  rdv  serial  relation   "
              "address    size      extent\n");
    for (i = 0; i < 138; ++i)
        append(d, "-");
    append(d, "\n");
}

static void row(struct document *d, unsigned handle, unsigned unit,
                unsigned state, unsigned owners, unsigned opens,
                unsigned shares, unsigned generation, unsigned relation,
                unsigned long long address, unsigned bytes, unsigned id,
                int has_extent)
{
    append(d, "%04x     %08x  %04x    %02x     %02x    %02x    %02x      %08x  ",
           handle, unit, state, owners, opens, shares, generation, relation);
    if (has_extent)
        append(d, "%09llx  %08x  %04x", address, bytes, id);
    append(d, "\n");
}

static void normal(struct document *d)
{
    start(d);
    row(d, 0x42d, 0x1d9, 2, 1, 0, 0, 1, 0x89abcdef,
        0x100004000ULL, 0x64000, 0xf1, 1);
}

static void replace(struct document *d, const char *old, const char *value)
{
    char *at = strstr(d->text, old);
    size_t n = strlen(old), replacement = strlen(value), offset;
    assert(at != NULL);
    offset = (size_t)(at - d->text);
    assert(d->used - n + replacement < sizeof(d->text));
    memmove(at + replacement, at + n, d->used - offset - n + 1);
    memcpy(at, value, replacement);
    d->used = d->used - n + replacement;
}

static void failure(const void *raw, size_t bytes, uint32_t unit, uint32_t h,
                    int expected)
{
    struct functional_face_proc_unit out;
    unsigned char saved[sizeof(out)];
    int rc;
    memset(&out, 0xa5, sizeof(out));
    memcpy(saved, &out, sizeof(out));
    ++parser_calls;
    rc = functional_face_proc_unit_parse(raw, bytes, unit, h, &out);
    if (rc != expected) {
        fprintf(stderr, "failure expected %d, got %d; input bytes=%zu\n",
                expected, rc, bytes);
        abort();
    }
    /* Byte comparison here verifies failure preservation, not semantic equality. */
    assert(memcmp(&out, saved, sizeof(out)) == 0);
}

static struct functional_face_proc_unit success(const struct document *d,
                                               uint32_t unit, uint32_t h)
{
    struct functional_face_proc_unit out;
    ++parser_calls;
    assert(functional_face_proc_unit_parse(d->text, d->used, unit, h, &out) == 0);
    assert(out.row_offset < d->used && out.row_bytes <= 2048);
    assert(out.row_bytes < d->used - out.row_offset);
    assert(d->text[out.row_offset + out.row_bytes] == '\n');
    return out;
}

static int same_fields(const struct functional_face_proc_unit *a,
                       const struct functional_face_proc_unit *b)
{
    return a->handle == b->handle && a->unit == b->unit && a->state == b->state &&
           a->owners == b->owners && a->opens == b->opens &&
           a->shares == b->shares && a->generation == b->generation &&
           a->relation == b->relation && a->extent_id == b->extent_id &&
           a->segments == b->segments && a->address == b->address &&
           a->bytes == b->bytes;
}

static void four_units(void)
{
    static const unsigned sizes[] = {0x64000, 0xc800, 0xd100, 0xe220};
    struct document d;
    unsigned i;
    start(&d);
    for (i = 0; i < 4; ++i)
        row(&d, 0x42d + i, 0x1d9 + i, 2, 1, 2, 3, 1, 0x89abcdef + i,
            0x100004000ULL + i * 0x100000ULL, sizes[i], 0xf1 + i, 1);
    for (i = 0; i < 4; ++i) {
        struct functional_face_proc_unit out = success(&d, 0x1d9 + i, 0x42d + i);
        assert(out.handle == 0x42d + i && out.unit == 0x1d9 + i);
        assert(out.state == 2 && out.owners == 1 && out.opens == 2);
        assert(out.shares == 3 && out.generation == 1);
        assert(out.relation == 0x89abcdef + i && out.extent_id == 0xf1 + i);
        assert(out.address == 0x100004000ULL + i * 0x100000ULL);
        assert(out.bytes == sizes[i] && out.segments == 1);
    }
}

static void counter_lifecycle(void)
{
    static const unsigned owners[] = {1, 2, 2, 2, 1};
    static const unsigned opens[] = {0, 0, 1, 0, 0};
    struct document d;
    struct functional_face_proc_unit saved = {0}, original = {0};
    unsigned i;
    for (i = 0; i < 5; ++i) {
        struct functional_face_proc_unit current;
        start(&d);
        row(&d, 0x42d, 0x1d9, i == 0 ? 1 : 2, owners[i], opens[i], 0, 1,
            0x89abcdef, 0x100004000ULL, 0x64000, 0xf1, 1);
        current = success(&d, 0x1d9, 0x42d);
        assert(current.owners == owners[i] && current.opens == opens[i]);
        assert(current.state == (i == 0 ? 1u : 2u));
        if (i == 0) {
            saved = current;
            original = current;
        }
        assert(same_fields(&saved, &original));
        assert(saved.state == 1 && saved.owners == 1 && saved.opens == 0);
    }
}

static void positions_and_unrelated_rows(void)
{
    struct document a, b;
    struct functional_face_proc_unit first, later;
    size_t target_start;
    normal(&a);
    first = success(&a, 0x1d9, 0x42d);
    start(&b);
    row(&b, 0x42c, 0x1d9, 2, 0, 0, 0, 1, 0, 0, 0, 0, 0);
    row(&b, 0x421, 0x123, 2, 1, 0, 0, 1, 1, 1, 1, 2, 1);
    append(&b, "%64s000000002  00000001  0003 < 0004\n", "");
    target_start = b.used;
    row(&b, 0x42d, 0x1d9, 2, 1, 0, 0, 1, 0x89abcdef,
        0x100004000ULL, 0x64000, 0xf1, 1);
    row(&b, 0x422, 0xffffffff, 1, 0xff, 0xff, 0xff, 1, 0, 0, 0, 0, 0);
    later = success(&b, 0x1d9, 0x42d);
    assert(same_fields(&first, &later));
    assert(first.row_offset != later.row_offset && later.row_offset == target_start);
    assert(first.row_bytes == later.row_bytes);
    assert(memcmp(a.text + first.row_offset, b.text + later.row_offset,
                  first.row_bytes) == 0);
    b.used = target_start + later.row_bytes + 1;
    b.text[b.used] = '\0';
    (void)success(&b, 0x1d9, 0x42d);
}

static void missing_target(void)
{
    struct document d;
    static const char none[] = "No unit information.\n";
    normal(&d);
    failure(d.text, d.used, 0x1da, 0x42e, -ENODATA);
    failure(none, sizeof(none) - 1, 0x1d9, 0x42d, -ENODATA);
    d.used = 0;
    append(&d, "%s\n", none);
    failure(d.text, d.used, 0x1d9, 0x42d, -EPROTO);
}

static void arguments(void)
{
    struct document d;
    normal(&d);
    failure(NULL, d.used, 0x1d9, 0x42d, -EINVAL);
    failure(d.text, d.used, 0x1d8, 0x42d, -EINVAL);
    failure(d.text, d.used, 0x1dd, 0x42d, -EINVAL);
    failure(d.text, d.used, 0x1d9, 0, -EINVAL);
    failure(d.text, d.used, 0x1d9, 0x2d, -EINVAL);
    failure(d.text, d.used, 0x1d9, 0x8000, -EINVAL);
    failure(d.text, d.used, 0x1d9, UINT32_MAX, -EINVAL);
    failure(d.text, d.used, 0x1d9, 0x7ff, -EINVAL);
    failure(d.text, 0, 0x1d9, 0x42d, -EPROTO);
    ++parser_calls;
    assert(functional_face_proc_unit_parse(d.text, d.used, 0x1d9, 0x42d,
                                           NULL) == -EINVAL);
}

static void exact_format(void)
{
    static const char *const old[] = {
        "Information", "handle   type", "----------", "042d     ",
        "000001d9", "89abcdef", "100004000", "  00064000"
    };
    static const char *const bad[] = {
        "information", "handle  type", "---------", "042d    ",
        "00001d9", "89ABCDEF", "0100004000", "\t00064000"
    };
    struct document d;
    size_t i;
    for (i = 0; i < sizeof(old) / sizeof(old[0]); ++i) {
        normal(&d);
        replace(&d, old[i], bad[i]);
        failure(d.text, d.used, 0x1d9, 0x42d, -EPROTO);
    }
    start(&d);
    failure(d.text, d.used, 0x1d9, 0x42d, -EPROTO);
}

static void truncation(void)
{
    struct document d;
    size_t i;
    normal(&d);
    for (i = 0; i < d.used; ++i)
        failure(d.text, i, 0x1d9, 0x42d, -EPROTO);
}

static void duplicates(void)
{
    struct document d;
    normal(&d);
    row(&d, 0x42d, 0x1d9, 2, 1, 0, 0, 1, 0x89abcdef,
        0x100004000ULL, 0x64000, 0xf1, 1);
    failure(d.text, d.used, 0x1d9, 0x42d, -EPROTO);
    normal(&d);
    row(&d, 0x42e, 0x1da, 1, 1, 0, 0, 1, 2, 2, 0xc800, 2, 1);
    row(&d, 0x42d, 0x1da, 1, 2, 1, 0, 1, 3, 3, 0xc800, 3, 1);
    failure(d.text, d.used, 0x1d9, 0x42d, -EPROTO);
}

static void wrong_unit_and_generation(void)
{
    struct document d;
    normal(&d);
    replace(&d, "000001d9", "000001da");
    failure(d.text, d.used, 0x1d9, 0x42d, -ESTALE);
    normal(&d);
    replace(&d, "00    01      ", "00    02      ");
    failure(d.text, d.used, 0x1d9, 0x42d, -ESTALE);
    normal(&d);
    replace(&d, "00    01      ", "00    00      ");
    failure(d.text, d.used, 0x1d9, 0x42d, -ESTALE);
    normal(&d);
    replace(&d, "042d", "082d");
    failure(d.text, d.used, 0x1d9, 0x42d, -EPROTO);
}

static void handle_boundaries(void)
{
    struct document d;
    struct functional_face_proc_unit out;
    start(&d);
    row(&d, 0x7c2d, 0x1d9, 2, 0xff, 0xff, 0xff, 31, UINT32_MAX,
        0x100004000ULL, 0x64000, 0xffff, 1);
    out = success(&d, 0x1d9, 0x7c2d);
    assert(out.generation == 31 && out.relation == UINT32_MAX);
    failure(d.text, d.used, 0x1d9, 0x7fff, -EINVAL);
    normal(&d);
    replace(&d, "042d", "8000");
    failure(d.text, d.used, 0x1d9, 0x42d, -EPROTO);
    normal(&d);
    replace(&d, "042d", "07ff");
    failure(d.text, d.used, 0x1d9, 0x42d, -EPROTO);
}

static void metadata_ranges(void)
{
    static const char *const old[] = {
        "000001d9", "89abcdef", "0002    ", "01     00",
        "00    00    01", "00    01      ", "01      ",
        "00f1", "89abcdef", "042d", "00064000"
    };
    static const char *const bad[] = {
        "1000001d9", "100000000", "10000    ", "100     00",
        "100    00    01", "100    01      ", "20      ",
        "10000", "00000000", "10000042d", "100064000"
    };
    struct document d;
    size_t i;
    for (i = 0; i < sizeof(old) / sizeof(old[0]); ++i) {
        normal(&d);
        replace(&d, old[i], bad[i]);
        failure(d.text, d.used, 0x1d9, 0x42d, -EPROTO);
    }
}

static void address_ranges(void)
{
    struct document d;
    struct functional_face_proc_unit out;
    normal(&d);
    replace(&d, "100004000", "10000000000000000");
    failure(d.text, d.used, 0x1d9, 0x42d, -EPROTO);
    start(&d);
    row(&d, 0x42d, 0x1d9, 2, 1, 0, 0, 1, 1,
        (unsigned long long)(UINT64_MAX - 0x64000 + 1), 0x64000, 0xf1, 1);
    failure(d.text, d.used, 0x1d9, 0x42d, -EPROTO);
    start(&d);
    row(&d, 0x42d, 0x1d9, 2, 1, 0, 0, 1, 1,
        (unsigned long long)(UINT64_MAX - 0x64000), 0x64000, 0xf1, 1);
    out = success(&d, 0x1d9, 0x42d);
    assert(out.address + out.bytes == UINT64_MAX);
    normal(&d);
    replace(&d, "100004000", "00004000");
    failure(d.text, d.used, 0x1d9, 0x42d, -EPROTO);
}

static void nonhex_and_nul(void)
{
    static const char *const bad[] = {"10000g000", "+00004000", "0x0004000"};
    struct document d;
    size_t i;
    for (i = 0; i < sizeof(bad) / sizeof(bad[0]); ++i) {
        normal(&d);
        replace(&d, "100004000", bad[i]);
        failure(d.text, d.used, 0x1d9, 0x42d, -EPROTO);
    }
    normal(&d);
    for (i = 0; i < d.used; ++i) {
        char saved = d.text[i];
        d.text[i] = '\0';
        failure(d.text, d.used, 0x1d9, 0x42d, -EPROTO);
        d.text[i] = saved;
    }
    d.text[d.used - 1] = '\r';
    failure(d.text, d.used, 0x1d9, 0x42d, -EPROTO);
    d.text[d.used - 1] = (char)0xff;
    failure(d.text, d.used, 0x1d9, 0x42d, -EPROTO);
    normal(&d);
    failure(d.text, d.used + 1, 0x1d9, 0x42d, -EPROTO);
}

static void state_ranges(void)
{
    struct document d;
    unsigned state;
    for (state = 0; state <= 8; ++state) {
        start(&d);
        row(&d, 0x42d, 0x1d9, state, 1, 0, 0, 1, 1,
            0x100004000ULL, 0x64000, 0xf1, 1);
        if (state == 0 || state == 8)
            failure(d.text, d.used, 0x1d9, 0x42d, -EPROTO);
        else
            assert(success(&d, 0x1d9, 0x42d).state == state);
    }
}

static void capacities(void)
{
    static const unsigned sizes[] = {0x64000, 0xc800, 0xd100};
    struct document d;
    unsigned i, j;
    for (i = 0; i < 3; ++i) {
        for (j = 0; j < 3; ++j) {
            unsigned bytes = j == 0 ? 0 : (j == 1 ? sizes[i] - 1 : sizes[i] + 1);
            start(&d);
            row(&d, 0x42d + i, 0x1d9 + i, 2, 1, 0, 0, 1, 1,
                0x100004000ULL, bytes, 0xf1, 1);
            failure(d.text, d.used, 0x1d9 + i, 0x42d + i, -EPROTO);
        }
    }
    start(&d);
    row(&d, 0x430, 0x1dc, 2, 1, 0, 0, 1, 1, 1, 1, 0xf1, 1);
    assert(success(&d, 0x1dc, 0x430).bytes == 1);
    replace(&d, "00000001  00f1", "00000000  00f1");
    failure(d.text, d.used, 0x1dc, 0x430, -EPROTO);
    start(&d);
    row(&d, 0x42d, 0x1d9, 2, 1, 0, 0, 1, 1, 0, 0, 0, 0);
    failure(d.text, d.used, 0x1d9, 0x42d, -EPROTO);
}

static void multiple_segments(void)
{
    struct document d;
    normal(&d);
    append(&d, "%64s100104000  00000001  00f2 < 00f3\n", "");
    failure(d.text, d.used, 0x1d9, 0x42d, -ENOTSUP);
    append(&d, "%64s100204000  00000001  00f4\n", "");
    failure(d.text, d.used, 0x1d9, 0x42d, -ENOTSUP);
    normal(&d);
    append(&d, "%63s100104000  00000001  00f2\n", "");
    failure(d.text, d.used, 0x1d9, 0x42d, -EPROTO);
    normal(&d);
    append(&d, "%65s100104000  00000001  00f2\n", "");
    failure(d.text, d.used, 0x1d9, 0x42d, -EPROTO);
    start(&d);
    append(&d, "%64s100104000  00000001  00f2\n", "");
    failure(d.text, d.used, 0x1d9, 0x42d, -EPROTO);
    start(&d);
    row(&d, 0x42d, 0x1d9, 2, 1, 0, 0, 1, 1, 0, 0, 0, 0);
    append(&d, "%64s100104000  00000001  00f2\n", "");
    failure(d.text, d.used, 0x1d9, 0x42d, -EPROTO);
}

static void ancestors(void)
{
    struct document d;
    struct functional_face_proc_unit out;
    size_t offset, i;
    normal(&d);
    offset = success(&d, 0x1d9, 0x42d).row_offset;
    --d.used;
    for (i = 0; i < 32; ++i)
        append(&d, " < %04x", (unsigned)i);
    append(&d, "\n");
    out = success(&d, 0x1d9, 0x42d);
    assert(out.extent_id == 0xf1 && out.segments == 1);
    assert(out.row_offset == offset && out.row_bytes == d.used - offset - 1);
    assert(memcmp(d.text + out.row_offset + out.row_bytes - 7, " < 001f", 7) == 0);
    --d.used;
    append(&d, " < 0020\n");
    failure(d.text, d.used, 0x1d9, 0x42d, -EPROTO);
    normal(&d);
    --d.used;
    append(&d, " < 10000\n");
    failure(d.text, d.used, 0x1d9, 0x42d, -EPROTO);
    normal(&d);
    --d.used;
    append(&d, " < 00f1 < 00f1\n");
    out = success(&d, 0x1d9, 0x42d);
    assert(out.extent_id == 0xf1 && out.segments == 1);
    normal(&d);
    --d.used;
    append(&d, " < \n");
    failure(d.text, d.used, 0x1d9, 0x42d, -EPROTO);
}

static void garbage_limits_and_caller_eof(void)
{
    struct document d;
    struct functional_face_proc_unit out;
    char *raw;
    size_t limit = (size_t)2 * 1024 * 1024;
    normal(&d);
    append(&d, "garbage\n");
    failure(d.text, d.used, 0x1d9, 0x42d, -EPROTO);
    normal(&d);
    append(&d, "\n");
    failure(d.text, d.used, 0x1d9, 0x42d, -EPROTO);
    start(&d);
    memset(d.text + d.used, 'x', 2049);
    d.used += 2049;
    append(&d, "\n");
    failure(d.text, d.used, 0x1d9, 0x42d, -E2BIG);
    start(&d);
    memset(d.text + d.used, 'x', 2048);
    d.used += 2048;
    append(&d, "\n");
    failure(d.text, d.used, 0x1d9, 0x42d, -EPROTO);
    raw = malloc(limit + 1);
    assert(raw != NULL);
    memset(raw, '\n', limit + 1);
    failure(raw, limit, 0x1d9, 0x42d, -EPROTO);
    failure(raw, limit + 1, 0x1d9, 0x42d, -E2BIG);
    free(raw);
    normal(&d);
    raw = malloc(d.used);
    assert(raw != NULL);
    memcpy(raw, d.text, d.used);
    ++parser_calls;
    assert(functional_face_proc_unit_parse(raw, d.used, 0x1d9, 0x42d, &out) == 0);
    free(raw);
    /* The same complete-looking bytes cannot reveal a withheld later row/EOF. */
    (void)success(&d, 0x1d9, 0x42d);
}

int main(void)
{
    static const struct {
        const char *name;
        void (*run)(void);
    } scenarios[] = {
        {"four_units", four_units},
        {"counter_lifecycle_saved_birth", counter_lifecycle},
        {"positions_raw_slice_unrelated_rows", positions_and_unrelated_rows},
        {"missing_target_no_information", missing_target},
        {"invalid_arguments", arguments},
        {"exact_header_width_spacing", exact_format},
        {"truncation_every_byte", truncation},
        {"duplicate_target", duplicates},
        {"wrong_unit_generation", wrong_unit_and_generation},
        {"generation31_slot3ff", handle_boundaries},
        {"metadata_ranges_overflow", metadata_ranges},
        {"address_width_u64_overflow", address_ranges},
        {"nonhex_ascii_embedded_nul", nonhex_and_nul},
        {"source_state_zero_ranges", state_ranges},
        {"exact_capacities_temp_nonzero", capacities},
        {"multiple_segments_continuations", multiple_segments},
        {"ancestor_chain_raw_slice", ancestors},
        {"garbage_bounds_caller_eof", garbage_limits_and_caller_eof}
    };
    size_t i;
    for (i = 0; i < sizeof(scenarios) / sizeof(scenarios[0]); ++i) {
        scenarios[i].run();
        printf("PASS %s\n", scenarios[i].name);
    }
    printf("functional-face-proc: 18 scenarios PASS; parser_calls=%u; "
           "HOST synthetic; native flags false\n", parser_calls);
    return 0;
}
