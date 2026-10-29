#include "native-au.h"

#include <errno.h>
#include <string.h>

static uint32_t le32(const uint8_t *p)
{
    return (uint32_t)p[0] | (uint32_t)p[1] << 8 |
        (uint32_t)p[2] << 16 | (uint32_t)p[3] << 24;
}

static uint64_t le64(const uint8_t *p)
{
    return (uint64_t)le32(p) | (uint64_t)le32(p + 4) << 32;
}

static int wraps(const void *p, size_t n)
{
    return n > UINTPTR_MAX - (uintptr_t)p;
}

/* Called only after both exclusive ends have been checked. */
static int overlaps(const void *a, size_t na, const void *b, size_t nb)
{
    return (uintptr_t)a < (uintptr_t)b + nb &&
        (uintptr_t)b < (uintptr_t)a + na;
}

int nau_resolve(const uint8_t *info96, size_t info_size,
    uint64_t address_correction, uint64_t es_base,
    const uint8_t *es, size_t es_capacity,
    struct nau *out, size_t out_capacity)
{
    struct nau r;
    uint64_t raw_address, corrected;
    uint32_t length;
    size_t offset, first;
    enum nvideo_status status;

    if (!info96 || !es || !es_capacity || !out ||
        (uintptr_t)out % _Alignof(struct nau)) return -EINVAL;
    if (info_size < NVIDEO_INFO_BYTES) return -ENODATA;
    if (info_size != NVIDEO_INFO_BYTES) return -EINVAL;
    if (out_capacity < sizeof(*out)) return -ENOSPC;
    if (wraps(info96, info_size) || wraps(es, es_capacity) ||
        wraps(out, out_capacity)) return -EOVERFLOW;
    if (overlaps(out, out_capacity, info96, info_size) ||
        overlaps(out, out_capacity, es, es_capacity)) return -EINVAL;

    memset(&r, 0, sizeof(r));
    memcpy(r.raw_info, info96, NVIDEO_INFO_BYTES);
    raw_address = le64(r.raw_info + 8);
    length = le32(r.raw_info + 0x10);
    if (raw_address > UINT64_MAX - length ||
        address_correction > UINT64_MAX - raw_address ||
        es_capacity > UINT64_MAX - es_base) return -EOVERFLOW;
    corrected = raw_address + address_correction;
    if (length > UINT64_MAX - corrected) return -EOVERFLOW;

    /* Abstract full-AU extent checks metadata only, never a claimed ES lease. */
    status = nvideo_parse_info(r.raw_info, NVIDEO_INFO_BYTES,
        raw_address, length, &r.info);
    switch (status) {
    case NVIDEO_OK: break;
    case NVIDEO_INVALID: return -EINVAL;
    case NVIDEO_UNSUPPORTED: return -ENOTSUP;
    case NVIDEO_RANGE: return -ERANGE;
    default: return -EINVAL;
    }
    if (corrected < es_base || corrected - es_base >= es_capacity ||
        length > es_capacity) return -ERANGE;

    offset = (size_t)(corrected - es_base);
    first = es_capacity - offset;
    if (first > length) first = length;
    r.address_correction = address_correction;
    r.corrected_address = corrected;
    r.es_base = es_base;
    r.es_capacity = es_capacity;
    r.total_length = length;
    r.span_count = 1;
    r.spans[0].data = es + offset;
    r.spans[0].length = first;
    r.spans[0].logical_address = corrected;
    r.spans[0].es_offset = offset;
    if (first < length) {
        r.span_count = 2;
        r.spans[1].data = es;
        r.spans[1].length = length - first;
        r.spans[1].logical_address = es_base;
        r.spans[1].es_offset = 0;
    }
    memcpy(out, &r, sizeof(r));
    return 0;
}
