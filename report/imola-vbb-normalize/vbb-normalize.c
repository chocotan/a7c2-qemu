#include "vbb-normalize.h"

#include <errno.h>
#include <string.h>

static uint32_t load_le32(const unsigned char *p)
{
    return (uint32_t)p[0] | (uint32_t)p[1] << 8 |
           (uint32_t)p[2] << 16 | (uint32_t)p[3] << 24;
}

static void store_le32(unsigned char *p, uint32_t x)
{
    p[0] = (unsigned char)x;
    p[1] = (unsigned char)(x >> 8);
    p[2] = (unsigned char)(x >> 16);
    p[3] = (unsigned char)(x >> 24);
}

static int normalize_word(uint8_t mode, uint32_t *word)
{
    uint32_t x = *word;

    switch (mode) {
    case 0: case 1: case 9:
        break;
    case 2:
        x >>= 1;
        break;
    case 3:
        x = (uint32_t)(((uint64_t)x * UINT32_C(0xaaaaaaab)) >> 32) &
            UINT32_C(0xfffffffe);
        break;
    case 4: case 5: case 0xd:
        x = (x / 3u * 4u + 0x1ffu) & UINT32_C(0xfffffe00);
        break;
    case 6: case 7: case 0xf:
        x <<= 1;
        break;
    default:
        return -ENOTSUP;
    }
    *word = x;
    return 0;
}

int nvbb_normalize_subrecord(uint32_t base, uint8_t address_mode,
                             uint8_t auxiliary_mode, const unsigned char *src,
                             size_t src_bytes, unsigned char *out,
                             size_t out_bytes)
{
    uintptr_t s = (uintptr_t)src, d = (uintptr_t)out;
    uint32_t x, y, z;
    int rc;

    if (src == NULL || out == NULL)
        return -EINVAL;
    if (src_bytes > UINTPTR_MAX - s || out_bytes > UINTPTR_MAX - d)
        return -EOVERFLOW;
    if (src_bytes < NVBB_SUBRECORD_BYTES || out_bytes < NVBB_SUBRECORD_BYTES)
        return -EMSGSIZE;
    if (s < d + out_bytes && d < s + src_bytes)
        return -EINVAL;

    x = load_le32(src) - base;
    y = load_le32(src + 4) - base;
    z = load_le32(src + 8);
    rc = normalize_word(address_mode, &x);
    if (rc != 0)
        return rc;
    rc = normalize_word(address_mode, &y);
    if (rc != 0)
        return rc;
    if (z != 0) {
        if (auxiliary_mode == 2)
            z >>= 1;
        else if (auxiliary_mode != 1)
            return -ENOTSUP;
    }

    /* Commit only after both original normalizers' consumed modes are valid. */
    memcpy(out, src, NVBB_SUBRECORD_BYTES);
    store_le32(out, x);
    store_le32(out + 4, y);
    store_le32(out + 8, z);
    return 0;
}
