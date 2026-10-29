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
 *   - row 0 starts with a little-endian frame index and FNV-1a checksum; the
 *     checksum covers the index, pixels and padding with only its own 8 bytes
 *     zeroed;
 *   - fill generates and publishes one leased frame. A second fill or a
 *     reconfiguration is refused until retire matches that buffer and index;
 *   - frame indices are strictly increasing, including after retirement;
 *   - short capacity and corrupt frames are refused instead of being accepted.
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
    uint64_t frames;            /* frames fully written and published */
    uint64_t pixels;            /* pixels written across all frames */
    uint64_t bytes;             /* bytes written across all frames */
    uint64_t refused;           /* operations rejected before writing/changing state */
    uint64_t retired;           /* leases explicitly retired */
    uint64_t last_frame_index;  /* last published generation */
    int last_error;             /* negative errno-style code, 0 when healthy */
    int lease_active;           /* exactly 0 or 1; this source has one lease slot */
};

int cmos_source_init(const struct cmos_spec *spec);
int cmos_source_frame_bytes(uint32_t *out);          /* stride*height */
int cmos_source_fill(void *dst, size_t capacity, uint64_t frame_index);
int cmos_source_retire(const void *dst, uint64_t frame_index);
int cmos_source_stats(struct cmos_stats *out);
/* Verify one complete stride*height frame and return its identity on success. */
int cmos_frame_probe(const void *frame, size_t capacity, uint32_t stride,
                     uint64_t *frame_index, uint64_t *payload_checksum);

#endif
