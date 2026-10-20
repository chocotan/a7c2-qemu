/* SPDX-License-Identifier: MIT */
/* Synthetic imager frame source for the virtual camera.
 *
 * This is explicitly a TEST PATTERN generator, not sensor data. It exists so a
 * downstream pin/buffer consumer can be exercised with real bytes, a real lease
 * length and a frame identity that a reader can verify. It must never be
 * described as CMOS pixels from the lens, and it does not by itself make the
 * original firmware consider the imager ready.
 *
 * Contract:
 *   - every frame carries its index and a 64-bit checksum of its own payload in
 *     the first row, so a consumer can prove which frame it read;
 *   - a short capacity is refused instead of overrunning the buffer;
 *   - counters only advance when bytes were actually written.
 */
#ifndef CMOS_SOURCE_H
#define CMOS_SOURCE_H

#include <stddef.h>
#include <stdint.h>

struct cmos_spec {
    uint32_t width;
    uint32_t height;
    uint32_t bytes_per_pixel;
    uint32_t stride;            /* bytes per row; 0 means width*bytes_per_pixel */
};

struct cmos_stats {
    uint64_t frames;            /* frames fully written */
    uint64_t pixels;            /* pixels written across all frames */
    uint64_t bytes;             /* bytes written across all frames */
    uint64_t refused;           /* calls rejected before writing anything */
    int last_error;             /* negative errno-style code, 0 when healthy */
};

int cmos_source_init(const struct cmos_spec *spec);
int cmos_source_frame_bytes(uint32_t *out);          /* stride*height */
int cmos_source_fill(void *dst, size_t capacity, uint64_t frame_index);
int cmos_source_stats(struct cmos_stats *out);
/* Frame identity helpers, shared by producers and verifiers. */
int cmos_frame_probe(const void *frame, size_t capacity, uint32_t stride,
                     uint64_t *frame_index, uint64_t *payload_checksum);

#endif
