/* SPDX-License-Identifier: MIT */
/* Host assertions for the PCM sink. No guest, no audio hardware. */
#define _GNU_SOURCE
#include "pcm-sink.h"

#include <assert.h>
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static unsigned long rd32(const unsigned char *p)
{
    return (unsigned long)p[0] | (unsigned long)p[1] << 8 |
           (unsigned long)p[2] << 16 | (unsigned long)p[3] << 24;
}

int main(void)
{
    struct pcm_sink_stats stats;

    /* Order and argument errors are refused without touching a file. */
    assert(pcm_sink_write("x", 1) == -30);
    assert(pcm_sink_stats(&stats) == 0 && stats.refused == 1 && stats.bytes == 0);
    assert(pcm_sink_open("none.wav", 48000, 0, 16, 1024) == -22);
    assert(pcm_sink_open("none.wav", 48000, 1, 12, 1024) == -22);
    assert(pcm_sink_open("none.wav", 48000, 1, 16, 0) == -22);

    const char *path = "sink.wav";
    /* open() starts a fresh counter set, so the earlier refusal is dropped. */
    assert(pcm_sink_open(path, 48000, 1, 16, 4096) == 0);
    assert(pcm_sink_stats(&stats) == 0 && stats.refused == 0);

    /* A real tone: 1000 frames of 1 kHz at 48 kHz, 16-bit mono. */
    enum { FRAMES = 1000 };
    short tone[FRAMES];
    for (int i = 0; i < FRAMES; ++i)
        tone[i] = (short)lrint(30000.0 * sin(2.0 * M_PI * 1000.0 * i / 48000.0));
    assert(pcm_sink_write(tone, sizeof tone) == 0);
    assert(pcm_sink_stats(&stats) == 0);
    assert(stats.bytes == sizeof tone && stats.frames == FRAMES);
    assert(stats.peak > 29000 && stats.peak <= 32767);

    /* Partial frames and over-cap writes are refused and not counted. */
    assert(pcm_sink_write(tone, 3) == -22);
    assert(pcm_sink_write(tone, 4096) == -28);
    struct pcm_sink_stats after;
    assert(pcm_sink_stats(&after) == 0 && after.bytes == stats.bytes && after.refused == 2);

    assert(pcm_sink_close() == 0);
    assert(pcm_sink_write(tone, 2) == -30);
    assert(pcm_sink_close() == -30);

    /* The file must be a valid PCM WAV carrying exactly what we handed over. */
    FILE *f = fopen(path, "rb");
    assert(f != NULL);
    unsigned char hdr[44];
    assert(fread(hdr, 1, sizeof hdr, f) == sizeof hdr);
    assert(memcmp(hdr, "RIFF", 4) == 0 && memcmp(hdr + 8, "WAVEfmt ", 8) == 0);
    assert(memcmp(hdr + 36, "data", 4) == 0);
    assert(rd32(hdr + 4) == 36 + sizeof tone);
    assert(rd32(hdr + 40) == sizeof tone);
    assert(hdr[20] == 1 && hdr[22] == 1 && rd32(hdr + 24) == 48000 && hdr[34] == 16);
    unsigned char *data = malloc(sizeof tone);
    assert(data != NULL && fread(data, 1, sizeof tone, f) == sizeof tone);
    assert(memcmp(data, tone, sizeof tone) == 0);
    fclose(f);
    free(data);
    remove(path);

    printf("PASS: pcm-sink order/validation/tone/cap/wav-roundtrip assertions\n");
    return 0;
}
