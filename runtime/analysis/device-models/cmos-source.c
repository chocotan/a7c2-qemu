/* SPDX-License-Identifier: MIT */
#define _GNU_SOURCE
#include "cmos-source.h"

#include <limits.h>
#include <pthread.h>
#include <string.h>

#define CMOS_EBUSY    (-16)
#define CMOS_ENOTREADY (-19)
#define CMOS_EINVAL   (-22)
#define CMOS_ENOSPC   (-28)
#define CMOS_EILSEQ   (-84)

static pthread_mutex_t mutex = PTHREAD_MUTEX_INITIALIZER;
static struct cmos_spec spec;
static struct cmos_stats stats;
static int configured;
static int have_generation;
static void *lease_dst;
static uint64_t lease_index;

static uint64_t fnv1a(const uint8_t *data, size_t n)
{
    uint64_t hash = 0xcbf29ce484222325ULL;
    for (size_t i = 0; i < n; ++i) {
        hash ^= data[i];
        hash *= 0x100000001b3ULL;
    }
    return hash;
}

static uint64_t row_stride(const struct cmos_spec *s)
{
    return s->stride ? s->stride : (uint64_t)s->width * s->bytes_per_pixel;
}

int cmos_source_init(const struct cmos_spec *in)
{
    if (in == NULL) return CMOS_EINVAL;
    if (in->width == 0 || in->height == 0) return CMOS_EINVAL;
    if (in->bytes_per_pixel == 0 || in->bytes_per_pixel > 8) return CMOS_EINVAL;
    const uint64_t minimum = (uint64_t)in->width * in->bytes_per_pixel;
    if (in->stride != 0 && in->stride < minimum) return CMOS_EINVAL;
    const uint64_t stride = row_stride(in);
    const uint64_t total = stride * in->height;
    if (stride < 16 || stride > UINT32_MAX || total > INT_MAX) return CMOS_EINVAL;

    pthread_mutex_lock(&mutex);
    if (stats.lease_active) {
        stats.refused++;
        stats.last_error = CMOS_EBUSY;
        pthread_mutex_unlock(&mutex);
        return CMOS_EBUSY;
    }
    spec = *in;
    stats = (struct cmos_stats){0};
    configured = 1;
    have_generation = 0;
    lease_dst = NULL;
    lease_index = 0;
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
    *out = (uint32_t)(row_stride(&spec) * spec.height);
    pthread_mutex_unlock(&mutex);
    return 0;
}

/* Generate and publish one frame. The source deliberately has only one lease
 * slot: no second destination can be written while an earlier frame is live. */
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
    if (stats.lease_active) {
        stats.refused++;
        stats.last_error = CMOS_EBUSY;
        pthread_mutex_unlock(&mutex);
        return CMOS_EBUSY;
    }
    if (have_generation && frame_index <= stats.last_frame_index) {
        stats.refused++;
        stats.last_error = CMOS_EINVAL;
        pthread_mutex_unlock(&mutex);
        return CMOS_EINVAL;
    }
    const struct cmos_spec local = spec;
    const uint32_t stride = (uint32_t)row_stride(&local);
    const size_t row_bytes = (size_t)local.width * local.bytes_per_pixel;
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
            const uint64_t base = (uint64_t)column + (uint64_t)row * 3u +
                                  frame_index * 0x9e3779b9ULL;
            uint8_t *pixel = line + (size_t)column * local.bytes_per_pixel;
            for (uint32_t byte = 0; byte < local.bytes_per_pixel; ++byte) {
                pixel[byte] = (uint8_t)((base >> (8u * (byte % 8u))) +
                                        (uint64_t)byte * 53u);
            }
        }
        memset(line + row_bytes, 0, stride - row_bytes);
    }

    /* The generation is authenticated too: only the checksum field is zero. */
    memset(out, 0, 16);
    for (unsigned i = 0; i < 8; ++i) out[i] = (uint8_t)(frame_index >> (8u * i));
    const uint64_t sum = fnv1a(out, (size_t)total);
    for (unsigned i = 0; i < 8; ++i) out[8 + i] = (uint8_t)(sum >> (8u * i));

    lease_dst = dst;
    lease_index = frame_index;
    have_generation = 1;
    stats.lease_active = 1;
    stats.frames++;
    stats.pixels += (uint64_t)local.width * local.height;
    stats.bytes += total;
    stats.last_frame_index = frame_index;
    stats.last_error = 0;
    pthread_mutex_unlock(&mutex);
    return (int)total;
}

int cmos_source_retire(const void *dst, uint64_t frame_index)
{
    if (dst == NULL) return CMOS_EINVAL;
    pthread_mutex_lock(&mutex);
    if (!configured || !stats.lease_active) {
        stats.refused++;
        stats.last_error = CMOS_ENOTREADY;
        pthread_mutex_unlock(&mutex);
        return CMOS_ENOTREADY;
    }
    if (lease_dst != dst || lease_index != frame_index) {
        stats.refused++;
        stats.last_error = CMOS_EINVAL;
        pthread_mutex_unlock(&mutex);
        return CMOS_EINVAL;
    }
    lease_dst = NULL;
    stats.lease_active = 0;
    stats.retired++;
    stats.last_error = 0;
    pthread_mutex_unlock(&mutex);
    return 0;
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
    if (stride < 16 || capacity < stride || capacity % stride != 0) return CMOS_EINVAL;
    const uint8_t *bytes = frame;
    uint64_t index = 0, stored = 0;
    for (unsigned i = 0; i < 8; ++i) {
        index |= (uint64_t)bytes[i] << (8u * i);
        stored |= (uint64_t)bytes[8 + i] << (8u * i);
    }

    uint8_t head[16];
    memcpy(head, bytes, sizeof head);
    memset(head + 8, 0, 8);
    uint64_t hash = fnv1a(head, sizeof head);
    for (size_t i = sizeof head; i < capacity; ++i) {
        hash ^= bytes[i];
        hash *= 0x100000001b3ULL;
    }
    if (hash != stored) return CMOS_EILSEQ;
    *frame_index = index;
    *payload_checksum = hash;
    return 0;
}
