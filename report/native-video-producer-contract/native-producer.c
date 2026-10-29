#include "native-producer.h"

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

int nproducer_convert(const uint8_t *source88, size_t source_size,
    uint8_t U, uint8_t G, uint8_t aux_present, uint32_t aux_next,
    const uint8_t *baseline96, size_t baseline_size,
    struct nproducer_record *out, size_t out_capacity)
{
    static const uint8_t semantic[96] = {
        0xff,0x07,0xff,0x01,0,0,0,0,0xff,0xff,0xff,0xff,0xff,0xff,0xff,0xff,
        0xff,0xff,0xff,0xff,0,0,0,0,0xff,0xff,0xff,0xff,0xff,0xff,0xff,0xff,
        0xff,0xff,0xff,0xff,0xff,0xff,0xff,0xff,0xff,0xff,0xff,0xff,0xff,0xff,0xff,0xff,
        0xff,0xff,0xff,0xff,0xff,0xff,0xff,0xff,0xff,0xff,0xff,0xff,0,0,0,0,
        0,0,0,0,0x03,0,0,0,0xff,0xff,0xff,0xff,0xff,0xff,0xff,0xff,
        0xff,0xff,0xff,0xff,0xff,0xff,0xff,0xff,0xff,0,0xff,0xff,0,0,0,0
    };
    struct nproducer_record r;
    uint8_t f, g, type;
    int rc, saved_errno = errno;
    if (aux_present > 1) return -EINVAL;
    if ((rc = span(source88, source_size)) ||
        (rc = span(baseline96, baseline_size)) ||
        (rc = span(out, out_capacity))) return rc;
    if (overlaps(source88, source_size, out, out_capacity) ||
        overlaps(baseline96, baseline_size, out, out_capacity)) return -EINVAL;
    if (source_size < NPRODUCER_SOURCE_BYTES || baseline_size < NPRODUCER_INFO_BYTES)
        return -ENODATA;
    if (source_size != NPRODUCER_SOURCE_BYTES || baseline_size != NPRODUCER_INFO_BYTES)
        return -EINVAL;
    if (out_capacity < sizeof(*out)) return -ENOSPC;
    f = source88[0x0e];
    g = source88[0x35];
    if (f & 2) type = 4;
    else if (g & 0x40) type = 0xff;
    else {
        type = (g >> 4) & 3;
        if (type == 2 && !(g & 8)) type = 9;
    }
    memcpy(r.wire, baseline96, sizeof(r.wire));
    memcpy(r.semantic_written_bits, semantic, sizeof(semantic));
    r.wire[0] = type;
    r.wire[1] = (uint8_t)((r.wire[1] & 0xf8) | ((g & 4) >> 2) |
        (g & 2) | ((g & 1) << 2));
    if (f & 1) r.wire[2] = source88[0x0c];
    else r.semantic_written_bits[2] = 0;
    /* The source ORs FULL U; the semantic bit mask is not a raw patch mask. */
    r.wire[3] = (uint8_t)((r.wire[3] & 0xfe) | U);
    memcpy(r.wire + 8, source88, 12);
    memcpy(r.wire + 0x18, source88 + 0x10, 16);
    memcpy(r.wire + 0x28, source88 + 0x3a, 2);
    r.wire[0x2a] = source88[0x34];
    r.wire[0x2b] = source88[0x33];
    memcpy(r.wire + 0x2c, source88 + 0x38, 2);
    r.wire[0x2e] = source88[0x32] >> 5;
    r.wire[0x2f] = source88[0x32] & 0x1f;
    memcpy(r.wire + 0x30, source88 + 0x36, 2);
    r.wire[0x32] = source88[0x31];
    r.wire[0x33] = source88[0x30];
    putle(r.wire + 0x34, G == 0 ? getle(source88 + 0x50, 4) : 0, 4);
    putle(r.wire + 0x38, (uint32_t)(getle(source88 + 0x20, 8) >> 3), 4);
    r.wire[0x44] = (uint8_t)((r.wire[0x44] & 0xfc) |
        (getle(source88 + 0x44, 2) & 1) |
        ((getle(source88 + 0x46, 2) & 1) << 1));
    memcpy(r.wire + 0x48, source88 + 0x48, 8);
    memcpy(r.wire + 0x50, source88 + 0x3c, 8);
    r.wire[0x58] = g >> 7;
    putle(r.wire + 0x5a, aux_present && !(f & 2) ? (uint16_t)aux_next : 0xffff, 2);
    memcpy(out, &r, sizeof(r));
    errno = saved_errno;
    return 0;
}

int nproducer_plan_publish(uint64_t slot_base, uint32_t supplied_slot_count,
    uint64_t control_base, uint32_t current, uint32_t internal_N,
    uint32_t occupied, struct nproducer_publish_plan *out, size_t out_capacity)
{
    struct nproducer_publish_plan r = {0};
    uint64_t ring_bytes = (uint64_t)supplied_slot_count * NPRODUCER_INFO_BYTES;
    uint32_t j, offset;
    int rc, saved_errno = errno;
    if (!out || (uintptr_t)out % _Alignof(struct nproducer_publish_plan) ||
        !supplied_slot_count || !internal_N) return -EINVAL;
    if ((rc = span(out, out_capacity))) return rc;
    if (out_capacity < sizeof(*out)) return -ENOSPC;
    if (current >= internal_N || occupied > internal_N) return -ERANGE;
    j = current + 1;
    if (j == internal_N) j = 0;
    if (j >= supplied_slot_count) return -ERANGE;
    if (j > UINT32_MAX / NPRODUCER_INFO_BYTES ||
        ring_bytes > UINT64_MAX - slot_base || control_base > UINT64_MAX - 8)
        return -EOVERFLOW;
    offset = j * NPRODUCER_INFO_BYTES;
    r.slot_address = slot_base + offset;
    r.control_index_address = control_base + 4;
    r.record_size = NPRODUCER_INFO_BYTES;
    r.index = j;
    r.post_publication_queue_full = occupied == internal_N;
    r.source_result = r.post_publication_queue_full;
    r.current_after = r.post_publication_queue_full ? current : j;
    r.occupied_after = r.post_publication_queue_full ? occupied : occupied + 1;
    memcpy(out, &r, sizeof(r));
    errno = saved_errno;
    return 0;
}
