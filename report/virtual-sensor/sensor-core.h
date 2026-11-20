/* SPDX-License-Identifier: MIT */
/* Virtual A7C2 sensor core: synthetic test pattern in Bayer GRBG 14-bit,
 * full-size RGB demosaic output and integer box downsampler for viewfinder.
 * Component only. Never represents physical sensor silicon. */
#ifndef SENSOR_CORE_H
#define SENSOR_CORE_H

#include <stddef.h>
#include <stdint.h>

/* Two accepted profiles only. Anything else is rejected, no silent default. */
#define SENSOR_PROFILE_DEFAULT_PREFIX "640x480"
#define SENSOR_PROFILE_FULL "7008x4672"

typedef struct {
    unsigned width;
    unsigned height;
    uint32_t generation; /* bumped by every successful configure */
} sensor_config;

/* A frame token is (generation << 32) | frame_index, frame_index >= 1.
 * Guard rule: samples are only produced for a token whose generation equals
 * cfg->generation, so a reconfigure cannot hand out buffers for the old size. */
typedef uint64_t sensor_frame_token;

/* Profile string -> config. NULL selects the default 640x480 profile.
 * "7008x4672" is only reachable when the string is given explicitly.
 * Returns 0 on success, -22 (EINVAL) on unknown profile. */
int sensor_config_parse(const char *profile, sensor_config *out);

/* Default 640x480 config with generation 1. */
sensor_config sensor_config_default(void);

/* Build the next token for a config: first frame of a generation gets index 1,
 * an in-generation increment keeps the generation. Invalid configuration or
 * exhausted frame index returns 0; advance configuration generation to resume. */
sensor_frame_token sensor_token_next(const sensor_config *cfg,
                                    sensor_frame_token previous);
int sensor_token_valid(const sensor_config *cfg, sensor_frame_token token);

/* Deterministic test pattern sample at (x, y) for a width x height frame,
 * already reduced to 14 bits (0..16383). Pure integer math, recomputable from
 * coordinates alone:
 *   base    : horizontal gradient, x*(16383)/(width-1)
 *   corners : four 1/8 blocks -> TL 16383, TR 0, BL 8192, BR 4095
 *   stripes : every 16th row carries its row index: (y/16)*1024 & 0x3fff
 * Corner blocks win over the gradient; the stripe row wins over both. */
uint16_t sensor_test_value(unsigned x, unsigned y, unsigned width,
                           unsigned height);

/* CFA phase of sample (x, y) in GRBG: returns 0=R 1=G 2=B. */
int sensor_cfa_color(unsigned x, unsigned y);

/* Frame as packed Bayer: width*height u16, sample stored as value << 2
 * (14 bits left-aligned in a virtual 16-bit container, not a verified Sony ABI).
 * Caller frees. */
uint16_t *sensor_frame_bayer(const sensor_config *cfg, sensor_frame_token token);

/* Same data into a caller buffer. Returns 0, -22 on guard failure, -28 (ENOSPC)
 * when capacity < width*height. */
int sensor_frame_bayer_into(const sensor_config *cfg, sensor_frame_token token,
                            uint16_t *dst, size_t capacity);

/* Decode one packed u16 back to 14 bits. */
uint16_t sensor_bayer_unpack(uint16_t packed);

/* Full-size RGB24 demosaic of a packed Bayer frame: width*height*3, caller
 * frees. Every 3x3 window of a Bayer mosaic holds R, G and B, so the mean of
 * the same-colour neighbours in that window is well defined at the borders too.
 * Returns NULL on bad arguments. */
int sensor_demosaic_rgb(const uint16_t *bayer, unsigned width, unsigned height,
                        uint8_t *rgb);

/* Configured frame as RGB24 (convenience: bayer + demosaic). Caller frees. */
uint8_t *sensor_frame_rgb(const sensor_config *cfg, sensor_frame_token token);

/* Integer box downsampler for the viewfinder path. factor 1 copies.
 * Output is ceil(width/factor) x ceil(height/factor) RGB24, caller frees;
 * out_width/out_height may be NULL. Returns NULL on bad arguments. */
uint8_t *sensor_downsample(const uint8_t *rgb, unsigned width, unsigned height,
                           unsigned factor, unsigned *out_width,
                           unsigned *out_height);

#endif /* SENSOR_CORE_H */
