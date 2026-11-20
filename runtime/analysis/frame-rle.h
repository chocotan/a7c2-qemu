/* SPDX-License-Identifier: MIT */
#ifndef FCAM_FRAME_RLE_H
#define FCAM_FRAME_RLE_H

#include <errno.h>
#include <stddef.h>
#include <stdint.h>
#include <string.h>

/* RGB888_RLE16: LE tag, count=(tag&0x7fff)+1, high bit selects one repeated RGB. */
static inline size_t fcam_rgb_pack(const uint8_t *src, size_t pixels,
                                   uint8_t *dst, size_t capacity)
{
    if (!src || !dst || !pixels || pixels > SIZE_MAX / 3u) return 0;
    size_t at = 0, used = 0;
    while (at < pixels) {
        size_t count = 1;
        while (count < 32768u && count < pixels - at &&
               !memcmp(src + at * 3u, src + (at + count) * 3u, 3u)) ++count;
        const int repeat = count >= 3u;
        if (!repeat) {
            count = 1;
            while (count < 32768u && count < pixels - at) {
                const size_t next = at + count;
                if (pixels - next >= 3u &&
                    !memcmp(src + next * 3u, src + (next + 1u) * 3u, 3u) &&
                    !memcmp(src + next * 3u, src + (next + 2u) * 3u, 3u)) break;
                ++count;
            }
        }
        const size_t bytes = repeat ? 3u : count * 3u;
        if (capacity - used < 2u || capacity - used - 2u < bytes) return 0;
        const uint16_t tag = (uint16_t)((count - 1u) | (repeat ? 0x8000u : 0u));
        dst[used++] = (uint8_t)tag;
        dst[used++] = (uint8_t)(tag >> 8);
        memcpy(dst + used, src + at * 3u, bytes);
        used += bytes;
        at += count;
    }
    return used;
}

static inline int fcam_rgb_unpack(const uint8_t *src, size_t bytes,
                                   uint8_t *dst, size_t pixels)
{
    if (!src || !dst || !pixels || pixels > SIZE_MAX / 3u) return -EINVAL;
    size_t at = 0, used = 0;
    while (used < bytes) {
        if (bytes - used < 2u) return -EBADMSG;
        const uint16_t tag = (uint16_t)((uint16_t)src[used] | (uint16_t)src[used + 1u] << 8);
        used += 2u;
        const size_t count = (tag & 0x7fffu) + 1u;
        const int repeat = (tag & 0x8000u) != 0;
        const size_t payload = repeat ? 3u : count * 3u;
        if (count > pixels - at || payload > bytes - used) return -EBADMSG;
        if (repeat) {
            for (size_t i = 0; i < count; ++i)
                memcpy(dst + (at + i) * 3u, src + used, 3u);
        } else memcpy(dst + at * 3u, src + used, payload);
        used += payload;
        at += count;
    }
    return at == pixels ? 0 : -EBADMSG;
}
#endif
