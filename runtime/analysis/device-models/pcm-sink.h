/* SPDX-License-Identifier: MIT */
/* Host-side PCM sink: turn audio data delivered by the original firmware into a
 * real WAV file on the host, with counters a test can verify.
 *
 * Scope and honesty:
 *   - it records what the device model receives; it does not invent audio and
 *     does not claim the firmware played anything;
 *   - writes are refused before open, and a hard byte cap stops a runaway
 *     stream instead of filling the disk;
 *   - the peak amplitude is tracked so "silence" cannot be mistaken for audio.
 */
#ifndef PCM_SINK_H
#define PCM_SINK_H

#include <stddef.h>
#include <stdint.h>

struct pcm_sink_stats {
    uint64_t bytes;        /* PCM bytes written */
    uint64_t frames;       /* sample frames written */
    uint32_t peak;         /* max |sample| observed, in sample units */
    uint64_t refused;      /* writes rejected (closed, invalid or over cap) */
};

int pcm_sink_open(const char *path, uint32_t sample_rate, uint16_t channels,
                  uint16_t bits_per_sample, uint64_t cap_bytes);
int pcm_sink_write(const void *data, size_t bytes);
int pcm_sink_close(void);
int pcm_sink_stats(struct pcm_sink_stats *out);

#endif
