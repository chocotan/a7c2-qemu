#include "functional-face-proc.h"

#include <errno.h>

#define PROC_MAX_BYTES ((size_t)2 * 1024 * 1024)
#define PROC_MAX_LINE ((size_t)2048)
#define PROC_MAX_ANCESTORS 32u

struct proc_cursor {
    const unsigned char *at;
    const unsigned char *end;
};

static int literal(struct proc_cursor *c, const char *text)
{
    while (*text != '\0') {
        if (c->at == c->end || *c->at != (unsigned char)*text)
            return 0;
        ++c->at;
        ++text;
    }
    return 1;
}

static int repeated(struct proc_cursor *c, unsigned char ch, size_t count)
{
    while (count-- != 0) {
        if (c->at == c->end || *c->at != ch)
            return 0;
        ++c->at;
    }
    return 1;
}

static int hex(struct proc_cursor *c, size_t width, uint64_t maximum,
               uint64_t *result)
{
    const unsigned char *start = c->at;
    uint64_t value = 0;

    while (c->at != c->end) {
        unsigned char ch = *c->at;
        uint64_t digit;
        if (ch >= '0' && ch <= '9')
            digit = (uint64_t)(ch - '0');
        else if (ch >= 'a' && ch <= 'f')
            digit = (uint64_t)(ch - 'a') + 10;
        else
            break;
        if (value > (maximum - digit) / 16)
            return 0;
        value = value * 16 + digit;
        ++c->at;
    }
    if ((size_t)(c->at - start) < width ||
        ((size_t)(c->at - start) > width && *start == '0'))
        return 0;
    *result = value;
    return 1;
}

static int prefix(struct proc_cursor *c, struct functional_face_proc_unit *row)
{
    static const size_t widths[] = {4, 8, 4, 2, 2, 2, 2, 8};
    static const size_t spaces[] = {5, 2, 4, 5, 4, 4, 6, 2};
    static const uint64_t maxima[] = {
        0x7fff, UINT32_MAX, 0xffff, 0xff, 0xff, 0xff, 0x1f, UINT32_MAX
    };
    uint64_t v[8];
    size_t i;

    for (i = 0; i < 8; ++i) {
        if (!hex(c, widths[i], maxima[i], &v[i]) ||
            !repeated(c, ' ', spaces[i]))
            return 0;
    }
    row->handle = (uint32_t)v[0];
    row->unit = (uint32_t)v[1];
    row->state = (uint32_t)v[2];
    row->owners = (uint32_t)v[3];
    row->opens = (uint32_t)v[4];
    row->shares = (uint32_t)v[5];
    row->generation = (uint32_t)v[6];
    row->relation = (uint32_t)v[7];
    return row->state != 0 && (row->handle & 0x3ffu) != 0x3ffu;
}

static int extent(struct proc_cursor *c, struct functional_face_proc_unit *row)
{
    uint64_t address, bytes, id;
    unsigned ancestors = 0;

    if (!hex(c, 9, UINT64_MAX, &address) || !literal(c, "  ") ||
        !hex(c, 8, UINT32_MAX, &bytes) || !literal(c, "  ") ||
        !hex(c, 4, 0xffff, &id) || bytes > SIZE_MAX ||
        address > UINT64_MAX - bytes)
        return 0;
    row->extent_id = (uint32_t)id;
    while (c->at != c->end) {
        if (++ancestors > PROC_MAX_ANCESTORS || !literal(c, " < ") ||
            !hex(c, 4, 0xffff, &id))
            return 0;
    }
    row->address = address;
    row->bytes = (size_t)bytes;
    /* Ancestor IDs describe E+0x28 links, not additional segments. */
    return 1;
}

int functional_face_proc_unit_parse(const void *raw, size_t raw_bytes,
                                   uint32_t unit, uint32_t full_handle,
                                   struct functional_face_proc_unit *out)
{
    struct proc_cursor doc;
    struct functional_face_proc_unit found = {0};
    size_t i, line_bytes = 0;
    unsigned rows = 0, matches = 0;
    int previous_extent = 0, previous_target = 0, stale = 0;

    if (raw == NULL || out == NULL || unit < 0x1d9u || unit > 0x1dcu ||
        full_handle > 0x7fffu || (full_handle >> 10) == 0 ||
        (full_handle & 0x3ffu) == 0x3ffu)
        return -EINVAL;
    if (raw_bytes > PROC_MAX_BYTES)
        return -E2BIG;
    if (raw_bytes == 0)
        return -EPROTO;
    doc.at = raw;
    doc.end = doc.at + raw_bytes;
    for (i = 0; i < raw_bytes; ++i) {
        unsigned char ch = ((const unsigned char *)raw)[i];
        if (ch == '\n')
            line_bytes = 0;
        else if (ch < ' ' || ch > '~')
            return -EPROTO;
        else if (++line_bytes > PROC_MAX_LINE)
            return -E2BIG;
    }
    if (doc.end[-1] != '\n')
        return -EPROTO;
    if (*doc.at == 'N') {
        if (literal(&doc, "No unit information.\n") && doc.at == doc.end)
            return -ENODATA;
        return -EPROTO;
    }
    if (!literal(&doc, "Information on Units.\n") ||
        !literal(&doc, "handle   type      status  alloc  open  rdv  serial  "
                      "relation   address    size      extent\n") ||
        !repeated(&doc, '-', 138) || !literal(&doc, "\n"))
        return -EPROTO;

    while (doc.at != doc.end) {
        struct proc_cursor line;
        struct functional_face_proc_unit row = {0};
        const unsigned char *row_start = doc.at;
        int target;

        line.at = doc.at;
        while (*doc.at != '\n')
            ++doc.at;
        line.end = doc.at++;
        if (line.at == line.end)
            return -EPROTO;
        if (*line.at == ' ') {
            if (!previous_extent || !repeated(&line, ' ', 64) ||
                !extent(&line, &row))
                return -EPROTO;
            if (previous_target)
                ++found.segments;
            continue;
        }
        if (!prefix(&line, &row))
            return -EPROTO;
        ++rows;
        target = row.handle == full_handle;
        if ((row.handle >> 10) != row.generation) {
            if (!target)
                return -EPROTO;
            stale = 1;
        }
        previous_extent = line.at != line.end;
        if (previous_extent) {
            if (!extent(&line, &row))
                return -EPROTO;
            row.segments = 1;
        }
        previous_target = target;
        if (target) {
            row.row_offset = (size_t)(row_start - (const unsigned char *)raw);
            row.row_bytes = (size_t)(line.end - row_start);
            if (++matches != 1)
                return -EPROTO;
            if (row.unit != unit)
                stale = 1;
            found = row;
        }
    }
    if (rows == 0)
        return -EPROTO;
    if (matches == 0)
        return -ENODATA;
    if (stale)
        return -ESTALE;
    if (found.segments > 1)
        return -ENOTSUP;
    if (found.segments != 1 || found.state > 7 || found.relation == 0 ||
        found.bytes == 0 ||
        (unit == 0x1d9u && found.bytes != 0x64000u) ||
        (unit == 0x1dau && found.bytes != 0xc800u) ||
        (unit == 0x1dbu && found.bytes != 0xd100u))
        return -EPROTO;
    *out = found;
    return 0;
}
