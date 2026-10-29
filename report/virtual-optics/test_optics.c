/* SPDX-License-Identifier: MIT */
#include "optics.h"
#include <assert.h>
#include <float.h>
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

enum { W = 1024, H = 64, STRIDE = W * 3 + 13, BYTES = STRIDE * H };
static optics_params standard = {4, 1, 0.001, 100};

static void render(optics_params p, unsigned char *buffer, optics_metadata *m)
{
    optics_stats s = {0};
    assert(optics_render(&p, W, H, STRIDE, buffer, BYTES, 42, m, &s) == 0);
    assert(s.completed_frames == 1);
}

static double mean(const unsigned char *buffer)
{
    double total = 0;
    for (size_t y = 0; y < H; ++y)
        for (size_t x = 8; x < W / 2 - 8; ++x)
            total += buffer[y * STRIDE + x * 3];
    return total / (H * (W / 2 - 16));
}

static double gradient(const unsigned char *buffer, int layer)
{
    double total = 0;
    size_t start = (size_t)layer * (W / 2) + 20;
    size_t end = start + W / 2 - 40;
    for (size_t y = 16; y < H - 16; ++y)
        for (size_t x = start; x < end; ++x) {
            size_t i = y * STRIDE + x * 3;
            total += abs((int)buffer[i + 3] - buffer[i]);
            total += abs((int)buffer[i + STRIDE] - buffer[i]);
        }
    return total / ((H - 32) * (W / 2 - 40) * 2);
}

static void rejection(optics_params p, size_t w, size_t h, size_t stride,
                      size_t capacity)
{
    unsigned char dst[32], saved[32];
    optics_metadata m, old;
    optics_stats s = {7};
    memset(dst, 0xa5, sizeof dst);
    memcpy(saved, dst, sizeof dst);
    memset(&m, 0x5a, sizeof m);
    memcpy(&old, &m, sizeof m);
    assert(optics_render(&p, w, h, stride, dst, capacity, 9, &m, &s) == -1);
    assert(memcmp(dst, saved, sizeof dst) == 0);
    assert(memcmp(&m, &old, sizeof m) == 0);
    assert(s.completed_frames == 7);
}

static void independent_boundaries(void)
{
    unsigned char guarded[35];
    optics_metadata m, saved;
    optics_stats stats = {0};
    memset(guarded, 0xa5, sizeof guarded);
    assert(optics_render(&standard, 3, 3, 11, guarded + 1, 33,
                         4242, &m, &stats) == 0);
    assert(guarded[0] == 0xa5 && guarded[34] == 0xa5);
    for (size_t y = 0; y < 3; ++y)
        assert(guarded[1 + y * 11 + 9] == 0xa5 &&
               guarded[1 + y * 11 + 10] == 0xa5);
    memcpy(&saved, &m, sizeof m);
    memset(guarded, 0xa5, sizeof guarded);
    assert(optics_render(NULL, 3, 3, 11, guarded + 1, 33, 0, &m, &stats) == -1);
    assert(optics_render(&standard, 3, 3, 11, NULL, 33, 0, &m, &stats) == -1);
    assert(optics_render(&standard, 3, 3, 11, guarded + 1, 33, 0, NULL, &stats) == -1);
    assert(optics_render(&standard, 3, 3, 11, guarded + 1, 33, 0, &m, NULL) == -1);
    assert(memcmp(&saved, &m, sizeof m) == 0 && stats.completed_frames == 1);
    for (size_t i = 0; i < sizeof guarded; ++i) assert(guarded[i] == 0xa5);

    unsigned char line[1024 * 3];
    optics_metadata full, half, stopped_down;
    optics_params p = standard;
    assert(optics_render(&p, 1024, 1, 3072, line, sizeof line, 0, &full, &stats) == 0);
    assert(optics_render(&p, 512, 1, 1536, line, sizeof line, 0, &half, &stats) == 0);
    p.f_number = 8;
    assert(optics_render(&p, 1024, 1, 3072, line, sizeof line, 0,
                         &stopped_down, &stats) == 0);
    assert(full.blur_radius_px[1] > 0 && full.blur_radius_px[1] < 16);
    assert(fabs(full.blur_radius_px[1] - 2 * half.blur_radius_px[1]) < 1e-9);
    assert(fabs(full.blur_radius_px[1] - 2 * stopped_down.blur_radius_px[1]) < 1e-9);
}

int main(void)
{
    unsigned char *a = malloc(BYTES), *b = malloc(BYTES);
    assert(a && b);
    memset(a, 0xa5, BYTES);
    memset(b, 0xa5, BYTES);
    optics_metadata ma, mb;
    render(standard, a, &ma);
    render(standard, b, &mb);
    assert(memcmp(a, b, BYTES) == 0);
    assert(ma.frame_number == 42 && ma.pixel_fnv1a == mb.pixel_fnv1a);
    uint64_t hash = UINT64_C(14695981039346656037);
    for (size_t y = 0; y < H; ++y) {
        for (size_t x = 0; x < W * 3; ++x)
            hash = (hash ^ a[y * STRIDE + x]) * UINT64_C(1099511628211);
        for (size_t x = W * 3; x < STRIDE; ++x)
            assert(a[y * STRIDE + x] == 0xa5);
    }
    assert(hash == ma.pixel_fnv1a);
    /* Identity belongs only to metadata; no special image row. */
    optics_stats stats = {0};
    assert(optics_render(&standard, W, H, STRIDE, b, BYTES, 99, &mb, &stats) == 0);
    assert(mb.frame_number == 99 && memcmp(a, b, BYTES) == 0);
    assert(memcmp(a, a + 8 * STRIDE, W * 3) == 0);

    optics_params p = standard;
    double base = mean(a);
    p.shutter_s *= 2;
    render(p, b, &mb);
    double shutter_ratio = mean(b) / base;
    assert(fabs(shutter_ratio - 2) < 0.04);
    p = standard;
    p.f_number = 8;
    render(p, b, &mb);
    double aperture_ratio = mean(b) / base;
    assert(fabs(aperture_ratio - 0.25) < 0.02);
    p = standard;
    p.iso *= 2;
    render(p, b, &mb);
    assert(fabs(mean(b) / base - 2) < 0.04);

    double near_sharp = gradient(a, 0), far_blur = gradient(a, 1);
    p = standard;
    p.focus_m = 4;
    render(p, b, &mb);
    double near_blur = gradient(b, 0), far_sharp = gradient(b, 1);
    assert(near_sharp > near_blur * 2 && far_sharp > far_blur * 2);
    assert(fabs(near_sharp - far_sharp) < 1);
    printf("shutter=%.6f aperture=%.6f; gradients near %.3f/%.3f far %.3f/%.3f\n",
           shutter_ratio, aperture_ratio, near_sharp, near_blur, far_blur, far_sharp);

    p.focus_m = INFINITY;
    render(p, b, &mb);
    assert(isfinite(mb.blur_radius_px[0]) && mean(b) > 0);
    p.focus_m = 0.1;
    render(p, b, &mb);
    assert(mb.blur_radius_px[0] == 16 && mb.blur_radius_px[1] == 16);
    p = standard;
    p.f_number = 16;
    render(p, b, &mb);
    assert(mean(b) > 0);
    p.shutter_s = 100;
    render(p, b, &mb);
    for (size_t y = 0; y < H; ++y) {
        for (size_t x = 0; x < W * 3; ++x) assert(b[y * STRIDE + x] == 255);
        for (size_t x = W * 3; x < STRIDE; ++x)
            assert(b[y * STRIDE + x] == 0xa5);
    }

    rejection(standard, 2, 2, 7, 13);
    rejection(standard, SIZE_MAX / 3 + 1, 1, SIZE_MAX, 32);
    rejection(standard, 1, SIZE_MAX, 3, SIZE_MAX);
    rejection(standard, 0, 2, 7, 32);
    rejection(standard, 2, 0, 7, 32);
    rejection(standard, 2, 2, 5, 32);
    rejection(standard, 1, 1, 0, 32);
    const double bad[] = {NAN, INFINITY, -INFINITY, 0, -1};
    for (size_t i = 0; i < sizeof bad / sizeof bad[0]; ++i) {
        p = standard; p.shutter_s = bad[i]; rejection(p, 2, 2, 7, 32);
        p = standard; p.iso = bad[i]; rejection(p, 2, 2, 7, 32);
        p = standard; p.f_number = bad[i]; rejection(p, 2, 2, 7, 32);
        if (bad[i] != INFINITY) {
            p = standard; p.focus_m = bad[i]; rejection(p, 2, 2, 7, 32);
        }
    }
    p = standard; p.focus_m = 0.035; rejection(p, 2, 2, 7, 32);
    p = standard; p.f_number = 5.6; rejection(p, 2, 2, 7, 32);
    p = standard; p.iso = DBL_MAX; p.shutter_s = DBL_MAX;
    rejection(p, 2, 2, 7, 32);
    unsigned char tiny[3] = {0};
    stats.completed_frames = UINT64_MAX;
    assert(optics_render(&standard, 1, 1, 3, tiny, 3, 0, &mb, &stats) == -1);
    assert(tiny[0] == 0 && stats.completed_frames == UINT64_MAX);
    stats.completed_frames = 0;
    assert(optics_render(&standard, 1, 1, 3, tiny, 3, 0, &mb, &stats) == 0);
    assert(stats.completed_frames == 1);
    independent_boundaries();
    free(a); free(b);
    puts("PASS: RGB bytes, physics ratios, focus exchange, rejection atomicity, padding");
    return 0;
}
