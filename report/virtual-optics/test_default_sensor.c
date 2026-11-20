/* SPDX-License-Identifier: MIT */
#define _POSIX_C_SOURCE 200809L
#include "optics.h"
#include "../virtual-sensor/sensor-core.h"
#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

enum { W = 640, H = 480, STRIDE = W * 3 + 13, BYTES = STRIDE * H };

static uint64_t active_hash(const uint8_t *pixels)
{
    uint64_t hash = UINT64_C(14695981039346656037);
    for (size_t y = 0; y < H; ++y) {
        for (size_t x = 0; x < W * 3u; ++x)
            hash = (hash ^ pixels[y * STRIDE + x]) * UINT64_C(1099511628211);
        for (size_t x = W * 3u; x < STRIDE; ++x)
            assert(pixels[y * STRIDE + x] == 0xa5);
    }
    return hash;
}

static double gradient(const uint8_t *pixels, unsigned layer)
{
    double sum = 0;
    for (size_t y = 80; y < 400; ++y)
        for (size_t x = layer * (W / 2u) + 20; x < layer * (W / 2u) + 300; ++x) {
            size_t i = y * STRIDE + x * 3u;
            sum += abs((int)pixels[i] - pixels[i + STRIDE]);
            sum += abs((int)pixels[i] - pixels[i + 3]);
        }
    return sum;
}

int main(void)
{
    assert(unsetenv("A7C2_VIRTUAL_CMOS_PROFILE") == 0);
    sensor_config config = sensor_config_default();
    uint8_t *source = sensor_frame_rgb(&config, sensor_token_next(&config, 0));
    uint8_t *near = malloc(BYTES), *far = malloc(BYTES), *saved = malloc(BYTES);
    assert(source && near && far && saved);
    memset(near, 0xa5, BYTES);
    memset(far, 0xa5, BYTES);
    optics_params p = {4, 1, 0.0025, 100}; /* Unit exposure gain. */
    optics_metadata a, b;
    optics_stats stats = {0};
    assert(optics_render(&p, W, H, STRIDE, near, BYTES, 1, &a, &stats) == 0);
    assert(stats.completed_frames == 1 && a.frame_number == 1);
    assert(a.blur_radius_px[0] == 0 && active_hash(near) == a.pixel_fnv1a);
    /* The in-focus plane must contain the actual demosaiced sensor samples. */
    for (size_t y = 0; y < H; ++y)
        assert(memcmp(near + y * STRIDE, source + y * W * 3u, W / 2u * 3u) == 0);
    p.focus_m = 4;
    assert(optics_render(&p, W, H, STRIDE, far, BYTES, 2, &b, &stats) == 0);
    assert(b.blur_radius_px[1] == 0 && active_hash(far) == b.pixel_fnv1a);
    for (size_t y = 0; y < H; ++y)
        assert(memcmp(far + y * STRIDE + W / 2u * 3u,
                      source + y * W * 3u + W / 2u * 3u, W / 2u * 3u) == 0);
    assert(gradient(near, 0) > gradient(far, 0) * 1.2);
    assert(gradient(far, 1) > gradient(near, 1) * 1.2);
    p.focus_m = 1;
    p.shutter_s /= 2;
    assert(optics_render(&p, W, H, STRIDE, far, BYTES, 3, &b, &stats) == 0);
    assert(far[20 * STRIDE + 20 * 3] == 128);
    memcpy(saved, far, BYTES);
    optics_metadata old = b;
    uint64_t count = stats.completed_frames;
    assert(setenv("A7C2_VIRTUAL_CMOS_PROFILE", "unknown", 1) == 0);
    assert(optics_render(&p, W, H, STRIDE, far, BYTES, 4, &b, &stats) == -1);
    assert(memcmp(saved, far, BYTES) == 0 && memcmp(&old, &b, sizeof b) == 0);
    assert(stats.completed_frames == count);
    assert(setenv("A7C2_VIRTUAL_CMOS_PROFILE", "legacy-checker", 1) == 0);
    p.shutter_s *= 2;
    assert(optics_render(&p, W, H, STRIDE, far, BYTES, 5, &b, &stats) == 0);
    assert(far[20 * STRIDE + 20 * 3] == 153);
    assert(memcmp(near, far, BYTES) != 0);
    assert(unsetenv("A7C2_VIRTUAL_CMOS_PROFILE") == 0);
    assert(optics_render(&p, W, H, STRIDE, far, BYTES, 6, &b, &stats) == 0);
    assert(memcmp(near, far, BYTES) == 0 && a.pixel_fnv1a == b.pixel_fnv1a);
    free(saved);
    free(far);
    free(near);
    free(source);
    puts("DEFAULT_CMOS_OPTICS_PASS");
    return 0;
}
