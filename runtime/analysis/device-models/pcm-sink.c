/* SPDX-License-Identifier: MIT */
#define _GNU_SOURCE
#include "pcm-sink.h"

#include <errno.h>
#include <fcntl.h>
#include <pthread.h>
#include <string.h>
#include <sys/stat.h>
#include <unistd.h>

#define PCM_EINVAL (-22)
#define PCM_EORDER (-30)   /* write before open / after close */
#define PCM_ENOSPC (-28)

static pthread_mutex_t mutex = PTHREAD_MUTEX_INITIALIZER;
static int descriptor = -1;
static uint32_t rate;
static uint16_t channels;
static uint16_t bits;
static uint64_t cap, written;
static struct pcm_sink_stats stats;

static void put16(uint8_t *p, unsigned v) { p[0] = (uint8_t)v; p[1] = (uint8_t)(v >> 8); }
static void put32(uint8_t *p, unsigned long v)
{
    for (unsigned i = 0; i < 4; ++i) p[i] = (uint8_t)(v >> (8 * i));
}

static uint32_t frame_bytes(void) { return (uint32_t)channels * (bits / 8u); }

static void header(uint8_t out[44], uint64_t data_bytes)
{
    memcpy(out, "RIFF", 4);
    put32(out + 4, (unsigned long)(36 + data_bytes));
    memcpy(out + 8, "WAVEfmt ", 8);
    put32(out + 16, 16);
    put16(out + 20, 1);                       /* PCM */
    put16(out + 22, channels);
    put32(out + 24, rate);
    put32(out + 28, rate * frame_bytes());
    put16(out + 32, (uint16_t)frame_bytes());
    put16(out + 34, bits);
    memcpy(out + 36, "data", 4);
    put32(out + 40, (unsigned long)data_bytes);
}

int pcm_sink_open(const char *path, uint32_t sample_rate, uint16_t channel_count,
                  uint16_t bits_per_sample, uint64_t cap_bytes)
{
    if (path == NULL || sample_rate < 8000 || sample_rate > 192000) return PCM_EINVAL;
    if (channel_count == 0 || channel_count > 8) return PCM_EINVAL;
    if (bits_per_sample != 8 && bits_per_sample != 16 && bits_per_sample != 24 &&
        bits_per_sample != 32) return PCM_EINVAL;
    if (cap_bytes == 0) return PCM_EINVAL;

    pthread_mutex_lock(&mutex);
    if (descriptor >= 0) {
        pthread_mutex_unlock(&mutex);
        return PCM_EINVAL;                     /* one sink at a time */
    }
    int fd = open(path, O_CREAT | O_TRUNC | O_WRONLY | O_CLOEXEC, 0644);
    if (fd < 0) {
        const int saved = errno;
        pthread_mutex_unlock(&mutex);
        return -saved;
    }
    rate = sample_rate;
    channels = channel_count;
    bits = bits_per_sample;
    cap = cap_bytes;
    written = 0;
    stats = (struct pcm_sink_stats){0};
    uint8_t zero[44] = {0};
    if (write(fd, zero, sizeof zero) != (ssize_t)sizeof zero) {
        close(fd);
        pthread_mutex_unlock(&mutex);
        return -EIO;
    }
    descriptor = fd;
    pthread_mutex_unlock(&mutex);
    return 0;
}

int pcm_sink_write(const void *data, size_t bytes)
{
    if (data == NULL && bytes != 0) return PCM_EINVAL;

    pthread_mutex_lock(&mutex);
    if (descriptor < 0) {
        stats.refused++;
        pthread_mutex_unlock(&mutex);
        return PCM_EORDER;
    }
    if (bytes == 0 || bytes % frame_bytes() != 0) {
        stats.refused++;
        pthread_mutex_unlock(&mutex);
        return PCM_EINVAL;
    }
    if (written + bytes > cap) {                 /* never fill the host disk */
        stats.refused++;
        pthread_mutex_unlock(&mutex);
        return PCM_ENOSPC;
    }
    const uint8_t *pcm = data;
    const ssize_t put = write(descriptor, pcm, bytes);
    if (put != (ssize_t)bytes) {
        stats.refused++;
        pthread_mutex_unlock(&mutex);
        return -EIO;
    }
    written += bytes;
    stats.bytes += bytes;
    stats.frames += bytes / frame_bytes();

    const unsigned step = bits / 8u;
    for (size_t offset = 0; offset + step <= bytes; offset += step) {
        uint32_t magnitude;
        if (bits == 8) {
            magnitude = (uint32_t)(pcm[offset] > 128 ? pcm[offset] - 128 : 128 - pcm[offset]);
        } else if (bits == 16) {
            const int16_t sample = (int16_t)(pcm[offset] | (pcm[offset + 1] << 8));
            magnitude = (uint32_t)(sample < 0 ? -sample : sample);
        } else {
            magnitude = 0;                       /* peak tracked for 8/16-bit only */
        }
        if (magnitude > stats.peak) stats.peak = magnitude;
    }
    pthread_mutex_unlock(&mutex);
    return 0;
}

int pcm_sink_close(void)
{
    pthread_mutex_lock(&mutex);
    if (descriptor < 0) {
        pthread_mutex_unlock(&mutex);
        return PCM_EORDER;
    }
    uint8_t hdr[44];
    header(hdr, written);
    int rc = 0;
    if (lseek(descriptor, 0, SEEK_SET) != 0 || write(descriptor, hdr, sizeof hdr) != (ssize_t)sizeof hdr)
        rc = -EIO;
    if (close(descriptor) != 0) rc = -EIO;
    descriptor = -1;
    pthread_mutex_unlock(&mutex);
    return rc;
}

int pcm_sink_stats(struct pcm_sink_stats *out)
{
    if (out == NULL) return PCM_EINVAL;
    pthread_mutex_lock(&mutex);
    *out = stats;
    pthread_mutex_unlock(&mutex);
    return 0;
}
