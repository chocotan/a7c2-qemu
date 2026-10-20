/* SPDX-License-Identifier: MIT */
#define _GNU_SOURCE
#include "cmos-source.h"

#include <pthread.h>
#include <string.h>

#define CMOS_ENOTREADY (-19)   /* ENODEV-style: nothing configured yet */
#define CMOS_EINVAL   (-22)
#define CMOS_ENOSPC   (-28)

static pthread_mutex_t mutex = PTHREAD_MUTEX_INITIALIZER;
static struct cmos_spec spec;
static struct cmos_stats stats;
static int configured;

static uint64_t fnv1a(const uint8_t *data, size_t n)
{
    uint64_t hash = 0xcbf29ce484222325ULL;
    for (size_t i = 0; i < n; ++i) {
        hash ^= data[i];
        hash *= 0x100000001b3ULL;
    }
    return hash;
}

static uint32_t row_stride(const struct cmos_spec *s)
{
    return s->stride ? s->stride : s->width * s->bytes_per_pixel;
}

int cmos_source_init(const struct cmos_spec *in)
{
    if (in == NULL) return CMOS_EINVAL;
    if (in->width == 0 || in->height == 0) return CMOS_EINVAL;
    if (in->bytes_per_pixel == 0 || in->bytes_per_pixel > 8) return CMOS_EINVAL;
    const uint64_t minimum = (uint64_t)in->width * in->bytes_per_pixel;
    if (in->stride != 0 && in->stride < minimum) return CMOS_EINVAL;
    const uint64_t total = (uint64_t)row_stride(in) * in->height;
    if (total > (uint64_t)1 << 32) return CMOS_EINVAL;

    pthread_mutex_lock(&mutex);
    spec = *in;
    stats = (struct cmos_stats){0};
    configured = 1;
    pthread_mutex_unlock(&mutex);
    return 0;
}

int cmos_source_frame_bytes(uint32_t *out)
{
    if (out == NULL) return CMOS_EINVAL;
    pthread_mutex_lock(&mutex);
    if (!configured) {
        pthread_mutex_unlock(&mutex);
        return CMOS_ENOTREADY;
    }
    *out = row_stride(&spec) * spec.height;
    pthread_mutex_unlock(&mutex);
    return 0;
}

/* Writes one deterministic test frame.
 *
 * Layout of row 0, little endian, only when the row is wide enough:
 *   [0..8)   frame index
 *   [8..16)  checksum of the whole frame with these 16 bytes zeroed
 * Remaining bytes: a per-pixel gradient that depends on the frame index, so a
 * stale buffer cannot be mistaken for a fresh frame.
 */
int cmos_source_fill(void *dst, size_t capacity, uint64_t frame_index)
{
    if (dst == NULL) return CMOS_EINVAL;

    pthread_mutex_lock(&mutex);
    if (!configured) {
        stats.refused++;
        stats.last_error = CMOS_ENOTREADY;
        pthread_mutex_unlock(&mutex);
        return CMOS_ENOTREADY;
    }
    const struct cmos_spec local = spec;
    const uint32_t stride = row_stride(&local);
    const uint64_t total = (uint64_t)stride * local.height;
    if (capacity < total) {
        stats.refused++;
        stats.last_error = CMOS_ENOSPC;
        pthread_mutex_unlock(&mutex);
        return CMOS_ENOSPC;
    }

    uint8_t *out = dst;
    for (uint32_t row = 0; row < local.height; ++row) {
        uint8_t *line = out + (size_t)row * stride;
        for (uint32_t column = 0; column < local.width; ++column) {
            const uint64_t v = (uint64_t)(column + row * 3u) + frame_index * 0x9e3779b9ULL;
            uint8_t *pixel = line + (size_t)column * local.bytes_per_pixel;
            for (uint32_t byte = 0; byte < local.bytes_per_pixel; ++byte) {
                pixel[byte] = (uint8_t)(v >> (8u * (byte % 8u)));
            }
        }
        for (uint32_t pad = local.width * local.bytes_per_pixel; pad < stride; ++pad) {
            line[pad] = 0;
        }
    }
    if (stride >= 16) {
        memset(out, 0, 16);
        for (unsigned i = 0; i < 8; ++i) {
            out[i] = (uint8_t)(frame_index >> (8u * i));
        }
        const uint64_t sum = fnv1a(out, (size_t)total);
        for (unsigned i = 0; i < 8; ++i) {
            out[8 + i] = (uint8_t)(sum >> (8u * i));
        }
    }

    stats.frames++;
    stats.pixels += (uint64_t)local.width * local.height;
    stats.bytes += total;
    stats.last_error = 0;
    pthread_mutex_unlock(&mutex);
    return (int)total;
}

int cmos_source_stats(struct cmos_stats *out)
{
    if (out == NULL) return CMOS_EINVAL;
    pthread_mutex_lock(&mutex);
    *out = stats;
    pthread_mutex_unlock(&mutex);
    return 0;
}

int cmos_frame_probe(const void *frame, size_t capacity, uint32_t stride,
                     uint64_t *frame_index, uint64_t *payload_checksum)
{
    if (frame == NULL || frame_index == NULL || payload_checksum == NULL) return CMOS_EINVAL;
    if (stride < 16 || capacity < 16) return CMOS_EINVAL;
    const uint8_t *bytes = frame;
    uint64_t index = 0;
    for (unsigned i = 0; i < 8; ++i) index |= (uint64_t)bytes[i] << (8u * i);

    /* Recompute over a copy with the identity bytes zeroed, exactly as the
       producer hashed them. */
    uint8_t head[16] = {0};
    uint64_t hash = fnv1a(head, sizeof head);
    const size_t rest_begin = sizeof head < capacity ? sizeof head : capacity;
    const uint8_t *rest = bytes + rest_begin;
    for (size_t i = 0; i < capacity - rest_begin; ++i) {
        hash ^= rest[i];
        hash *= 0x100000001b3ULL;
    }
    *frame_index = index;
    *payload_checksum = hash;
    return 0;
}
