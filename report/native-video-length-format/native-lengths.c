#include "native-lengths.h"
#include "../native-video-au-contract/native-au.h"

#include <errno.h>

/* Only called on the exact, nonempty ordered spans returned by nau_resolve. */
static uint8_t read_byte(const struct nau *au, size_t *span, size_t *offset)
{
    if (*offset == au->spans[*span].length) {
        ++*span;
        *offset = 0;
    }
    /* Volatile prevents removal of reads of uninterpreted NAL body bytes. */
    return ((const volatile uint8_t *)au->spans[*span].data)[(*offset)++];
}

/* All exclusive host ends are checked before this comparison. */
static int overlaps(const void *a, size_t na, const void *b, size_t nb)
{
    return (uintptr_t)a < (uintptr_t)b + nb &&
        (uintptr_t)b < (uintptr_t)a + na;
}

int nlength_validate(const uint8_t *info96, size_t info_size,
    uint64_t address_correction, uint64_t es_base,
    const uint8_t *es, size_t es_capacity, uint32_t container_type,
    size_t *out_count)
{
    struct nau au;
    size_t span = 0, offset = 0, count = 0, remaining;
    int rc;

    if (!out_count || (uintptr_t)out_count % _Alignof(size_t))
        return -EINVAL;
    if (sizeof(*out_count) > UINTPTR_MAX - (uintptr_t)out_count)
        return -EOVERFLOW;
    if (container_type != NLENGTH_AVC1 && container_type != NLENGTH_HVC1)
        return -ENOTSUP;

    rc = nau_resolve(info96, info_size, address_correction, es_base,
        es, es_capacity, &au, sizeof(au));
    if (rc)
        return rc;
    if (overlaps(out_count, sizeof(*out_count), info96, info_size) ||
        overlaps(out_count, sizeof(*out_count), es, es_capacity))
        return -EINVAL;

    remaining = au.total_length;
    while (remaining) {
        uint32_t length = 0;
        if (remaining < 4)
            return -ENODATA;
        for (size_t i = 0; i < 4; ++i)
            length = (length << 8) | read_byte(&au, &span, &offset);
        remaining -= 4;
        if (!length)
            return -EINVAL;
        /* Subtraction avoids an overflowing length+prefix/end calculation. */
        if (length > remaining)
            return -ENODATA;
        if (container_type == NLENGTH_HVC1 && length < 2)
            return -EINVAL;

        for (size_t i = 0; i < length; ++i) {
            uint8_t byte = read_byte(&au, &span, &offset);
            if (i == 0 && (byte & 0x80))
                return -EINVAL;
            if (container_type == NLENGTH_HVC1 && i == 1 && !(byte & 7))
                return -EINVAL;
        }
        remaining -= length;
        ++count; /* At least five consumed bytes per NAL bound the count. */
    }
    *out_count = count;
    return 0;
}
