#include "native-fill.h"

#include <errno.h>
#include <string.h>

static int span(const void *p, size_t n)
{
    if (!p) return -EINVAL;
    return n > UINTPTR_MAX - (uintptr_t)p ? -EOVERFLOW : 0;
}

static int overlaps(const void *a, size_t an, const void *b, size_t bn)
{
    return an && bn && (uintptr_t)a < (uintptr_t)b + bn &&
        (uintptr_t)b < (uintptr_t)a + an;
}

static uint64_t getle(const uint8_t *p, unsigned n)
{
    uint64_t v = 0;
    for (unsigned i = 0; i < n; ++i) v |= (uint64_t)p[i] << (8 * i);
    return v;
}

static void putle(uint8_t *p, uint64_t v, unsigned n)
{
    for (unsigned i = 0; i < n; ++i) p[i] = (uint8_t)(v >> (8 * i));
}

static uint64_t pair32(const uint8_t *p)
{
    return (getle(p, 4) << 32) | getle(p + 4, 4);
}

int nfill_assemble(const uint8_t *workE90, size_t work_size,
    uint32_t first_segment_index, uint32_t last_segment_index,
    const uint8_t *nodeA, size_t node_size,
    const uint8_t *baseline88, size_t baseline_size,
    struct nfill_record *out, size_t out_capacity)
{
    struct nfill_record r;
    const uint8_t *last, *d;
    uint64_t p, signed_value;
    uint32_t length = 0;
    uint16_t q;
    uint8_t f, g;
    int rc, saved_errno = errno;
    if ((rc = span(workE90, work_size)) || (rc = span(nodeA, node_size)) ||
        (rc = span(baseline88, baseline_size)) || (rc = span(out, out_capacity)))
        return rc;
    if (overlaps(workE90, work_size, out, out_capacity) ||
        overlaps(nodeA, node_size, out, out_capacity) ||
        overlaps(baseline88, baseline_size, out, out_capacity)) return -EINVAL;
    if (work_size < NFILL_WORK_BYTES || node_size < NFILL_NODE_BYTES ||
        baseline_size < NFILL_RECORD_BYTES) return -ENODATA;
    if (work_size != NFILL_WORK_BYTES || node_size != NFILL_NODE_BYTES ||
        baseline_size != NFILL_RECORD_BYTES) return -EINVAL;
    if (out_capacity < sizeof(*out)) return -ENOSPC;
    if (first_segment_index > last_segment_index ||
        last_segment_index >= NFILL_SEGMENT_COUNT) return -ERANGE;
    for (uint32_t j = first_segment_index; j <= last_segment_index; ++j) {
        const uint8_t *l = workE90 + 0x620 + j * 0x10;
        uint32_t part = (uint32_t)getle(l + 8, 4);
        if (l[0x0d] >= 2 || (j < last_segment_index && l[0x0c]) ||
            (j == last_segment_index && !l[0x0c])) return -ERANGE;
        if (!part) return -ENODATA;
        if (part > UINT32_MAX - length) return -EOVERFLOW;
        length += part;
    }
    p = getle(workE90 + 0xbc0 + first_segment_index * 8, 8);
    if (length > UINT64_MAX - p) return -EOVERFLOW;
    last = workE90 + 0x620 + last_segment_index * 0x10;
    d = workE90 + 0x5b0 + last[0x0d] * 0x34;
    q = (uint16_t)getle(d + 0x28, 2);
    f = (uint8_t)((q >> 6) & 0x0f);
    g = (uint8_t)((q & 3) | ((q >> 8) & 4) | ((q & 0x3c) << 1) |
        ((workE90[8] == 2) << 7));
    memcpy(r.wire, baseline88, sizeof(r.wire));
    memset(r.semantic_written_bits, 0xff, 0x54);
    memset(r.semantic_written_bits + 0x54, 0, 4);
    putle(r.wire, p, 8);
    putle(r.wire + 8, length, 4);
    putle(r.wire + 0x0c, 0, 2);
    r.wire[0x0e] = f;
    r.wire[0x0f] = 1;
    putle(r.wire + 0x10, pair32(d), 8);
    putle(r.wire + 0x18, pair32(d + 8), 8);
    signed_value = getle(d + 0x10, 4);
    if (signed_value & UINT64_C(0x80000000)) signed_value |= UINT64_C(0xffffffff00000000);
    putle(r.wire + 0x20, signed_value, 8);
    putle(r.wire + 0x28, pair32(d + 0x14), 8);
    r.wire[0x30] = d[0x24];
    r.wire[0x31] = d[0x25];
    r.wire[0x32] = (uint8_t)((d[0x20] & 0x1f) | ((d[0x21] & 7) << 5));
    r.wire[0x33] = d[0x1c];
    r.wire[0x34] = d[0x1d];
    r.wire[0x35] = g;
    memcpy(r.wire + 0x36, d + 0x26, 2);
    memcpy(r.wire + 0x38, d + 0x22, 2);
    memcpy(r.wire + 0x3a, d + 0x1e, 2);
    memcpy(r.wire + 0x3c, workE90 + 0x618, 8);
    memcpy(r.wire + 0x44, nodeA + 8, 12);
    putle(r.wire + 0x50, f & 2 ? 0 : getle(nodeA + 0x14, 4), 4);
    memcpy(out, &r, sizeof(r));
    errno = saved_errno;
    return 0;
}

int nfill_plan_notify(uint32_t index, uint32_t N, uint32_t cid,
    uint32_t unit, uint32_t primary_id, uint32_t secondary_id,
    uint64_t record_base, struct nfill_notify_plan *out, size_t out_capacity)
{
    static const uint8_t header[8] = {0x03,0x21,0x1c,0x01,0x18,0,0,0};
    struct nfill_notify_plan r;
    uint64_t ring_bytes = (uint64_t)N * NFILL_RECORD_BYTES;
    int rc, saved_errno = errno;
    if (!out || (uintptr_t)out % _Alignof(struct nfill_notify_plan) || !N)
        return -EINVAL;
    if ((rc = span(out, out_capacity))) return rc;
    if (out_capacity < sizeof(*out)) return -ENOSPC;
    if (index >= N) return -ERANGE;
    if (ring_bytes > UINT64_MAX - record_base) return -EOVERFLOW;
    memset(&r, 0, sizeof(r));
    r.record_address = record_base + (uint64_t)index * NFILL_RECORD_BYTES;
    r.index = index;
    r.next_index = index + 1 >= N ? 0 : index + 1;
    r.destination = cid;
    memcpy(r.wire, header, sizeof(header));
    putle(r.wire + 8, unit, 4);
    putle(r.wire + 0x0c, index, 4);
    putle(r.wire + 0x10, primary_id, 4);
    putle(r.wire + 0x14, secondary_id, 4);
    memcpy(out, &r, sizeof(r));
    errno = saved_errno;
    return 0;
}
