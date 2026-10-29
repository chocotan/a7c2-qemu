/* SPDX-License-Identifier: MIT */
#include "optics.h"
#include <math.h>

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
    *metadata = result;
    ++stats->completed_frames;
    return 0;
}
