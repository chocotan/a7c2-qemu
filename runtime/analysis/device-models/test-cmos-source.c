/* SPDX-License-Identifier: MIT */
/* Host assertions for the synthetic imager source. No guest, no sensor. */
#include "cmos-source.h"

#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

int main(void)
{
    uint32_t bytes = 0;
    struct cmos_stats stats;

    /* Unconfigured: refuse, count the refusal, do not touch the buffer. */
    assert(cmos_source_frame_bytes(&bytes) == -19);
    unsigned char canary[64];
    memset(canary, 0xa5, sizeof canary);
    assert(cmos_source_fill(canary, sizeof canary, 0) == -19);
    for (size_t i = 0; i < sizeof canary; ++i) assert(canary[i] == 0xa5);
    assert(cmos_source_stats(&stats) == 0 && stats.frames == 0 && stats.refused == 1);

    /* Geometry validation. */
    struct cmos_spec bad = {.width = 0, .height = 4, .bytes_per_pixel = 2, .stride = 0};
    assert(cmos_source_init(&bad) == -22);
    bad = (struct cmos_spec){.width = 8, .height = 4, .bytes_per_pixel = 2, .stride = 4};
    assert(cmos_source_init(&bad) == -22);        /* stride below width*bpp */
    struct cmos_spec spec = {.width = 64, .height = 8, .bytes_per_pixel = 2, .stride = 0};
    /* Reconfiguring starts a fresh counter set, so earlier refusals are dropped. */
    assert(cmos_source_init(&spec) == 0);
    assert(cmos_source_stats(&stats) == 0 && stats.frames == 0 && stats.refused == 0);
    assert(cmos_source_frame_bytes(&bytes) == 0 && bytes == 64 * 8 * 2);

    /* Short capacity is refused without writing. */
    size_t total = bytes;
    unsigned char *frame = malloc(total);
    assert(frame != NULL);
    memset(frame, 0x5a, total);
    assert(cmos_source_fill(frame, total - 1, 0) == -28);
    for (size_t i = 0; i < total; ++i) assert(frame[i] == 0x5a);
    assert(cmos_source_stats(&stats) == 0 && stats.frames == 0 && stats.refused == 1);

    /* Frames are written, counted, and identifiable. */
    assert(cmos_source_fill(frame, total, 7) == (int)total);
    uint64_t index = 0, payload = 0;
    assert(cmos_frame_probe(frame, total, 128, &index, &payload) == 0 && index == 7);
    assert(cmos_source_stats(&stats) == 0 && stats.frames == 1 && stats.bytes == total);
    assert(stats.pixels == 64u * 8u);

    /* Two different frames must not look alike (no stale-buffer confusion). */
    unsigned char *first = malloc(total);
    assert(first != NULL);
    memcpy(first, frame, total);
    assert(cmos_source_fill(frame, total, 8) == (int)total);
    uint64_t index8 = 0, payload8 = 0;
    assert(cmos_frame_probe(frame, total, 128, &index8, &payload8) == 0 && index8 == 8);
    assert(memcmp(first, frame, total) != 0);
    assert(payload != payload8);

    /* Padding bytes beyond width*bpp stay zero so a consumer cannot read stale data. */
    for (uint32_t row = 0; row < spec.height; ++row) {
        const unsigned char *line = frame + (size_t)row * 128;
        for (size_t pad = spec.width * spec.bytes_per_pixel; pad < 128; ++pad) assert(line[pad] == 0);
    }

    free(first);
    free(frame);
    printf("PASS: cmos-source init/refusal/pattern/identity/padding assertions\n");
    return 0;
}
