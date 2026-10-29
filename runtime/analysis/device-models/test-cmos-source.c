/* SPDX-License-Identifier: MIT */
/* Host assertions for the synthetic imager source. No guest, no sensor. */
#include "cmos-source.h"

#include <assert.h>
#include <limits.h>
#include <stdint.h>
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

    /* Geometry validation happens in wide arithmetic before conversion. */
    struct cmos_spec bad = {.width = 0, .height = 4, .bytes_per_pixel = 2, .stride = 0};
    assert(cmos_source_init(&bad) == -22);
    bad = (struct cmos_spec){.width = 8, .height = 4, .bytes_per_pixel = 2, .stride = 4};
    assert(cmos_source_init(&bad) == -22);        /* stride below width*bpp */
    bad = (struct cmos_spec){.width = 8, .height = 4, .bytes_per_pixel = 1, .stride = 8};
    assert(cmos_source_init(&bad) == -22);        /* identity header does not fit */
    bad = (struct cmos_spec){.width = UINT32_MAX, .height = 1, .bytes_per_pixel = 2, .stride = 0};
    assert(cmos_source_init(&bad) == -22);        /* default stride exceeds uint32 */
    bad = (struct cmos_spec){.width = UINT32_MAX, .height = 2, .bytes_per_pixel = 1, .stride = 0};
    assert(cmos_source_init(&bad) == -22);        /* fill result must fit int */

    struct cmos_spec spec = {.width = 64, .height = 8, .bytes_per_pixel = 2, .stride = 0};
    /* Reconfiguring without a lease starts a fresh counter set. */
    assert(cmos_source_init(&spec) == 0);
    assert(cmos_source_stats(&stats) == 0 && stats.frames == 0 && stats.refused == 0);
    assert(cmos_source_frame_bytes(&bytes) == 0 && bytes == 64 * 8 * 2);
    spec.stride = 136;
    assert(cmos_source_init(&spec) == 0);
    assert(cmos_source_frame_bytes(&bytes) == 0 && bytes == 136 * 8);

    /* Short capacity is refused without writing. */
    size_t total = bytes;
    unsigned char *frame = malloc(total);
    assert(frame != NULL);
    memset(frame, 0x5a, total);
    assert(cmos_source_fill(frame, total - 1, 0) == -28);
    for (size_t i = 0; i < total; ++i) assert(frame[i] == 0x5a);
    assert(cmos_source_stats(&stats) == 0 && stats.frames == 0 && stats.refused == 1);

    /* A frame remains published until its exact buffer and generation retire. */
    assert(cmos_source_fill(frame, total, 7) == (int)total);
    uint64_t index = 0, payload = 0;
    assert(cmos_frame_probe(frame, total, spec.stride, &index, &payload) == 0 && index == 7);
    assert(cmos_frame_probe(frame, total - 1, spec.stride, &index, &payload) == -22);
    unsigned char *first = malloc(total);
    assert(first != NULL);
    memcpy(first, frame, total);
    assert(cmos_source_fill(frame, total, 8) == -16);
    assert(memcmp(first, frame, total) == 0);
    assert(cmos_source_retire(frame, 8) == -22);
    assert(cmos_source_retire(first, 7) == -22); /* pointer and generation must both match */
    assert(cmos_source_stats(&stats) == 0 && stats.lease_active == 1);
    assert(cmos_source_retire(frame, 7) == 0);
    assert(cmos_source_retire(frame, 7) == -19);
    assert(cmos_source_fill(frame, total, 7) == -22); /* generations never go backwards */
    assert(memcmp(first, frame, total) == 0);

    /* A later generation differs and is independently identifiable. */
    assert(cmos_source_fill(frame, total, 8) == (int)total);
    uint64_t index8 = 0, payload8 = 0;
    assert(cmos_frame_probe(frame, total, spec.stride, &index8, &payload8) == 0 && index8 == 8);
    assert(memcmp(first, frame, total) != 0);
    assert(payload != payload8);
    struct cmos_spec other = {.width = 9, .height = 6, .bytes_per_pixel = 2, .stride = 24};
    assert(cmos_source_init(&other) == -16);       /* cannot orphan a live lease */
    assert(cmos_source_frame_bytes(&bytes) == 0 && bytes == total);

    /* Actual padding bytes beyond width*bpp are zero on every row. */
    for (uint32_t row = 0; row < spec.height; ++row) {
        const unsigned char *line = frame + (size_t)row * spec.stride;
        for (size_t pad = spec.width * spec.bytes_per_pixel; pad < spec.stride; ++pad)
            assert(line[pad] == 0);
    }
    assert(cmos_source_retire(frame, 8) == 0);
    assert(cmos_source_stats(&stats) == 0 && stats.frames == 2 && stats.retired == 2);
    assert(stats.bytes == 2 * total && stats.pixels == 2u * 64u * 8u);
    assert(stats.last_frame_index == 8 && stats.lease_active == 0);

    free(first);
    free(frame);
    printf("PASS: cmos-source geometry/lease/generation/identity/padding assertions\n");
    return 0;
}
