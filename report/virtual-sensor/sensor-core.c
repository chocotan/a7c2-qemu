/* SPDX-License-Identifier: MIT */
#include "sensor-core.h"

#include <stdlib.h>
#include <string.h>

#define EINVAL_ (-22)
#define ENOPSPACE (-28)

static int profile_equal(const char *a, const char *b)
{
    return a && b && !strcmp(a, b);
}

int sensor_config_parse(const char *profile, sensor_config *out)
{
    if (!out)
        return EINVAL_;
    out->generation = 1;
    if (!profile || profile_equal(profile, SENSOR_PROFILE_DEFAULT_PREFIX)) {
        out->width = 640;
        out->height = 480;
        return 0;
    }
    if (profile_equal(profile, SENSOR_PROFILE_FULL)) {
        out->width = 7008;
        out->height = 4672;
        return 0;
    }
    out->width = 0;
    out->height = 0;
    return EINVAL_;
}

sensor_config sensor_config_default(void)
{
    sensor_config cfg;
    cfg.width = 640;
    cfg.height = 480;
    cfg.generation = 1;
    return cfg;
}

sensor_frame_token sensor_token_next(const sensor_config *cfg,
                                    sensor_frame_token previous)
{
    if (!cfg || !cfg->generation || !cfg->width || !cfg->height)
        return 0;
    uint32_t generation = cfg->generation;
    uint32_t index = (uint32_t)(previous & 0xffffffffu);
    if ((uint32_t)(previous >> 32) != generation)
        index = 0;
    if (index == UINT32_MAX)
        return 0;
    return ((sensor_frame_token)generation << 32) | (sensor_frame_token)(index + 1);
}

int sensor_token_valid(const sensor_config *cfg, sensor_frame_token token)
{
    if (!cfg || !cfg->generation || !cfg->width || !cfg->height)
        return 0;
    if ((uint32_t)(token >> 32) != cfg->generation)
        return 0;
    return (uint32_t)(token & 0xffffffffu) != 0;
}

int sensor_cfa_color(unsigned x, unsigned y)
{
    /* GRBG: row even -> G R, row odd -> B G */
    if (!(y & 1u))
        return (x & 1u) ? 0 : 1;
    return (x & 1u) ? 1 : 2;
}

uint16_t sensor_test_value(unsigned x, unsigned y, unsigned width,
                           unsigned height)
{
    /* Original synthetic colours, not a measured commercial reference chart. */
    static const uint8_t patches[4][6][3] = {
        {{255,255,255}, {255,224,32}, {32,224,224},
         {32,192,64}, {224,48,192}, {224,48,32}},
        {{48,80,224}, {240,144,32}, {128,64,192},
         {32,144,128}, {240,144,176}, {128,80,48}},
        {{176,112,80}, {96,144,192}, {112,160,80},
         {192,160,208}, {64,96,128}, {208,192,128}},
        {{255,255,255}, {204,204,204}, {153,153,153},
         {102,102,102}, {51,51,51}, {0,0,0}}
    };
    unsigned sx, sy, col, row;
    uint32_t value;

    if (!width || !height || x >= width || y >= height)
        return 0;
    sx = (unsigned)((uint64_t)x * 640u / width);
    sy = (unsigned)((uint64_t)y * 480u / height);
    col = sx * 6u / 640u;
    row = sy / 120u;
    value = patches[row][col][sensor_cfa_color(x, y)];
    /* Four reference-pixel gutters separate the patches at either size. */
    if (sx % 320u < 4u || sx * 6u % 640u < 24u || sy % 120u < 4u)
        value = 16u;
    /* Line pairs on both depth planes retain a real-pixel focus target. */
    if (((sy >= 324u && sy < 356u) || (sy >= 420u && sy < 476u)) &&
        sx >= 8u && sx < 632u)
        value = ((sx / 4u + sy / 4u) & 1u) ? 32u : 224u;
    return (uint16_t)(value * 16383u / 255u);
}

uint16_t sensor_bayer_unpack(uint16_t packed)
{
    return (uint16_t)(packed >> 2);
}

static int frame_samples(unsigned width, unsigned height, size_t *samples)
{
    if (!width || !height)
        return EINVAL_;
    if ((uint64_t)width * height > (uint64_t)SIZE_MAX / 3u)
        return EINVAL_;
    *samples = (size_t)width * height;
    return 0;
}

int sensor_frame_bayer_into(const sensor_config *cfg, sensor_frame_token token,
                            uint16_t *dst, size_t capacity)
{
    size_t samples;
    unsigned x, y;

    if (!sensor_token_valid(cfg, token) || !dst)
        return EINVAL_;
    if (frame_samples(cfg->width, cfg->height, &samples))
        return EINVAL_;
    if (capacity < samples)
        return ENOPSPACE;
    for (y = 0; y < cfg->height; ++y)
        for (x = 0; x < cfg->width; ++x)
            dst[(size_t)y * cfg->width + x] =
                (uint16_t)(sensor_test_value(x, y, cfg->width, cfg->height) << 2);
    return 0;
}

uint16_t *sensor_frame_bayer(const sensor_config *cfg, sensor_frame_token token)
{
    size_t samples;
    uint16_t *bayer;

    if (!sensor_token_valid(cfg, token))
        return NULL;
    if (frame_samples(cfg->width, cfg->height, &samples))
        return NULL;
    bayer = malloc(samples * sizeof(*bayer));
    if (!bayer)
        return NULL;
    if (sensor_frame_bayer_into(cfg, token, bayer, samples)) {
        free(bayer);
        return NULL;
    }
    return bayer;
}

static uint16_t sample_at(const uint16_t *bayer, unsigned width, unsigned height,
                          unsigned x, unsigned y)
{
    if (x >= width)
        x = width - 1;
    if (y >= height)
        y = height - 1;
    return sensor_bayer_unpack(bayer[(size_t)y * width + x]);
}

int sensor_demosaic_rgb(const uint16_t *bayer, unsigned width, unsigned height,
                        uint8_t *rgb)
{
    unsigned x, y;

    if (!bayer || !rgb || !width || !height)
        return EINVAL_;
    for (y = 0; y < height; ++y) {
        for (x = 0; x < width; ++x) {
            uint32_t sum[3] = { 0, 0, 0 };
            uint32_t n[3] = { 0, 0, 0 };
            int dx, dy, c;

            for (dy = -1; dy <= 1; ++dy) {
                for (dx = -1; dx <= 1; ++dx) {
                    int px = (int)x + dx;
                    int py = (int)y + dy;
                    if (px < 0 || py < 0 || px >= (int)width || py >= (int)height)
                        continue;
                    c = sensor_cfa_color((unsigned)px, (unsigned)py);
                    sum[c] += sample_at(bayer, width, height, (unsigned)px,
                                        (unsigned)py);
                    ++n[c];
                }
            }
            for (c = 0; c < 3; ++c) {
                uint32_t value;
                if (!n[c])
                    return EINVAL_;
                value = (sum[c] / n[c] * 255u) / 16383u;
                rgb[((size_t)y * width + x) * 3 + (size_t)c] = (uint8_t)value;
            }
        }
    }
    return 0;
}

uint8_t *sensor_frame_rgb(const sensor_config *cfg, sensor_frame_token token)
{
    size_t samples, bytes;
    uint16_t *bayer;
    uint8_t *rgb;

    if (!sensor_token_valid(cfg, token))
        return NULL;
    if (frame_samples(cfg->width, cfg->height, &samples))
        return NULL;
    bytes = samples * 3u;
    bayer = sensor_frame_bayer(cfg, token);
    if (!bayer)
        return NULL;
    rgb = malloc(bytes);
    if (!rgb) {
        free(bayer);
        return NULL;
    }
    if (sensor_demosaic_rgb(bayer, cfg->width, cfg->height, rgb)) {
        free(bayer);
        free(rgb);
        return NULL;
    }
    free(bayer);
    return rgb;
}

uint8_t *sensor_downsample(const uint8_t *rgb, unsigned width, unsigned height,
                           unsigned factor, unsigned *out_width,
                           unsigned *out_height)
{
    unsigned ow, oh, x, y;
    uint8_t *out;

    if (!rgb || !width || !height || !factor)
        return NULL;
    ow = (width + factor - 1) / factor;
    oh = (height + factor - 1) / factor;
    if ((uint64_t)ow * oh > (uint64_t)SIZE_MAX / 3u)
        return NULL;
    out = malloc((size_t)ow * oh * 3u);
    if (!out)
        return NULL;

    for (y = 0; y < oh; ++y) {
        for (x = 0; x < ow; ++x) {
            unsigned sy, sx, n = 0, c;
            uint32_t sum[3] = { 0, 0, 0 };
            for (sy = y * factor; sy < (y + 1) * factor && sy < height; ++sy) {
                for (sx = x * factor; sx < (x + 1) * factor && sx < width; ++sx) {
                    const uint8_t *p = rgb + ((size_t)sy * width + sx) * 3u;
                    for (c = 0; c < 3; ++c)
                        sum[c] += p[c];
                    ++n;
                }
            }
            if (!n) {
                free(out);
                return NULL;
            }
            for (c = 0; c < 3; ++c)
                out[((size_t)y * ow + x) * 3u + c] =
                    (uint8_t)(sum[c] / n);
        }
    }
    if (out_width)
        *out_width = ow;
    if (out_height)
        *out_height = oh;
    return out;
}
