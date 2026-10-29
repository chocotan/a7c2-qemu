/* SPDX-License-Identifier: MIT */
#ifndef VIRTUAL_OPTICS_H
#define VIRTUAL_OPTICS_H
#include <stddef.h>
#include <stdint.h>

/* Internal linear RGB888 only; no Sony pixel/plane/lease contract. */
typedef struct {
    double f_number;       /* Exactly 4, 8 or 16; fixed 35 mm focal length. */
    double focus_m;        /* >= 0.1 m, or positive INFINITY. */
    double shutter_s;
    double iso;
} optics_params;

typedef struct {
    uint64_t frame_number;
    uint64_t pixel_fnv1a;  /* Active RGB bytes in row order, excludes padding. */
    double blur_radius_px[2]; /* 1 m / 4 m planes, capped at 16 px. */
} optics_metadata;

typedef struct { uint64_t completed_frames; } optics_stats;

/* Returns 0 on success, -1 on invalid input/capacity/overflow.
 * Failure leaves dst, metadata and stats unchanged. Padding is never written.
 * Requires capacity >= stride * height. Objects must not overlap; caller owns
 * valid storage for dst[capacity], params, metadata and stats. No allocations.
 */
int optics_render(const optics_params *params, size_t width, size_t height,
                  size_t stride, unsigned char *dst, size_t capacity,
                  uint64_t frame_number, optics_metadata *metadata,
                  optics_stats *stats);
#endif
