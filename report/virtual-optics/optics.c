/* SPDX-License-Identifier: MIT */
#include "optics.h"
#include "../virtual-sensor/sensor-core.h"
#include <math.h>
#include <stdlib.h>
#include <string.h>

/* Virtual CMOS is the default at supported sizes; legacy-checker is an A/B option. */
static int sensor_blur(uint8_t *rgb, size_t width, size_t height,
                       const double radii[2])
{
    unsigned radius[2] = {(unsigned)ceil(radii[0]), (unsigned)ceil(radii[1])};
    if (!radius[0] && !radius[1]) return 0;
    uint8_t *scratch = malloc(width * height * 3u);
    if (!scratch) return -1;
    for (unsigned layer = 0; layer < 2; ++layer) {
        size_t first = layer ? width / 2 : 0;
        size_t end = layer ? width : width / 2;
        size_t r = radius[layer];
        for (size_t y = 0; y < height; ++y) {
            for (size_t c = 0; c < 3; ++c) {
                unsigned sum = 0, count = 0;
                for (size_t x = first; x < end && x <= first + r; ++x) {
                    sum += rgb[(y * width + x) * 3u + c];
                    ++count;
                }
                for (size_t x = first; x < end; ++x) {
                    scratch[(y * width + x) * 3u + c] = (uint8_t)((sum + count / 2u) / count);
                    if (x >= first + r) {
                        sum -= rgb[(y * width + x - r) * 3u + c];
                        --count;
                    }
                    if (x + r + 1u < end) {
                        sum += rgb[(y * width + x + r + 1u) * 3u + c];
                        ++count;
                    }
                }
            }
        }
        for (size_t x = first; x < end; ++x) {
            for (size_t c = 0; c < 3; ++c) {
                unsigned sum = 0, count = 0;
                for (size_t y = 0; y < height && y <= r; ++y) {
                    sum += scratch[(y * width + x) * 3u + c];
                    ++count;
                }
                for (size_t y = 0; y < height; ++y) {
                    rgb[(y * width + x) * 3u + c] = (uint8_t)((sum + count / 2u) / count);
                    if (y >= r) {
                        sum -= scratch[((y - r) * width + x) * 3u + c];
                        --count;
                    }
                    if (y + r + 1u < height) {
                        sum += scratch[((y + r + 1u) * width + x) * 3u + c];
                        ++count;
                    }
                }
            }
        }
    }
    free(scratch);
    return 0;
}

/* Mean of a four-pixel square wave through a bounded box kernel. */
static double wave(double p, int radius)
{
    double sum = 0;
    for (int k = -radius; k <= radius; ++k)
        sum += fmod(floor((p + k) / 4.0), 2.0) == 0 ? 1.0 : -1.0;
    return sum / (2 * radius + 1);
}

static double checker(size_t x, size_t y, double radius)
{
    int r = (int)floor(radius);
    double fraction = radius - r;
    double a = wave((double)x, r) * wave((double)y, r);
    if (fraction == 0) return a;
    double b = wave((double)x, r + 1) * wave((double)y, r + 1);
    return a + fraction * (b - a);
}

int optics_render(const optics_params *p, size_t width, size_t height,
                  size_t stride, unsigned char *dst, size_t capacity,
                  uint64_t frame_number, optics_metadata *metadata,
                  optics_stats *stats)
{
    if (!p || !dst || !metadata || !stats || !width || !height ||
        width > SIZE_MAX / 3 || stride < width * 3 ||
        height > SIZE_MAX / stride || capacity < stride * height ||
        stats->completed_frames == UINT64_MAX)
        return -1;
    if ((p->f_number != 4 && p->f_number != 8 && p->f_number != 16) ||
        isnan(p->focus_m) || p->focus_m < 0.1 ||
        !isfinite(p->shutter_s) || p->shutter_s <= 0 ||
        !isfinite(p->iso) || p->iso <= 0)
        return -1;
    double gain = p->shutter_s * p->iso * (64.0 / (p->f_number * p->f_number));
    if (!isfinite(gain)) return -1;
    const char *profile = getenv("A7C2_VIRTUAL_CMOS_PROFILE");
    if (profile && strcmp(profile, "virtual-cmos-v1") && strcmp(profile, "legacy-checker"))
        return -1;

    optics_metadata result = {0};
    result.frame_number = frame_number;
    result.pixel_fnv1a = UINT64_C(14695981039346656037);
    double focus_d = isinf(p->focus_m) ? 0 : 1.0 / p->focus_m;
    for (int layer = 0; layer < 2; ++layer) {
        double scene_d = layer == 0 ? 1.0 : 0.25;
        /* Thin-lens CoC radius in metres, then 36 mm sensor pixel scale. */
        double radius = (0.035 * 0.035 * fabs(scene_d - focus_d)) /
                        (2 * p->f_number * (1 - 0.035 * focus_d));
        result.blur_radius_px[layer] = fmin(16.0, radius * ((double)width / 0.036));
    }
    const int virtual_cmos = (!profile || strcmp(profile, "legacy-checker")) &&
        ((width == 640 && height == 480) || (width == 7008 && height == 4672));
    if (!virtual_cmos) {
        for (size_t y = 0; y < height; ++y) {
            unsigned char *row = dst + y * stride;
            for (size_t x = 0; x < width; ++x) {
                int layer = x < width / 2 ? 0 : 1;
                double luminance = 0.35 + 0.25 * checker(x, y, result.blur_radius_px[layer]);
                for (size_t c = 0; c < 3; ++c) {
                    double colour = c == 0 ? 1.0 : (c == 1 ? 0.8 : 0.6);
                    double value = fmin(1.0, luminance * colour * gain);
                    unsigned char byte = (unsigned char)floor(value * 255.0 + 0.5);
                    row[x * 3 + c] = byte;
                    result.pixel_fnv1a ^= byte;
                    result.pixel_fnv1a *= UINT64_C(1099511628211);
                }
            }
        }
    } else {
        /* Virtual CMOS photosites: one demosaiced RGB frame under the token
         * guard, copied row by row so caller stride/padding is honoured; gain
         * keeps the original exposure semantics for downstream consumers. */
        sensor_config sensor;
        const char *profile_name = width == 640 ? NULL : SENSOR_PROFILE_FULL;
        if (sensor_config_parse(profile_name, &sensor) != 0) return -1;
        uint64_t index = frame_number & UINT64_C(0xffffffff);
        if (!index) index = 1;
        uint8_t *rgb = sensor_frame_rgb(&sensor, ((uint64_t)sensor.generation << 32) | index);
        if (!rgb) return -1;
        if (sensor_blur(rgb, width, height, result.blur_radius_px)) {
            free(rgb);
            return -1;
        }
        for (size_t y = 0; y < height; ++y) {
            unsigned char *row = dst + y * stride;
            const uint8_t *source = rgb + y * width * 3u;
            for (size_t x = 0; x < width; ++x) {
                for (size_t c = 0; c < 3; ++c) {
                    double value = fmin(1.0, (source[x * 3u + c] / 255.0) * gain);
                    unsigned char byte = (unsigned char)floor(value * 255.0 + 0.5);
                    row[x * 3 + c] = byte;
                    result.pixel_fnv1a ^= byte;
                    result.pixel_fnv1a *= UINT64_C(1099511628211);
                }
            }
        }
        free(rgb);
    }
    *metadata = result;
    ++stats->completed_frames;
    return 0;
}
