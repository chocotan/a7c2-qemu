/* SPDX-License-Identifier: MIT */
#include "optics.h"
#include "jpeg-engine.h"
#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

enum { GUARD = 16 };

static void untouched(const unsigned char *bytes, size_t count)
{
    for (size_t i = 0; i < count; ++i) assert(bytes[i] == 0xa5);
}

static void frame(const char *name, size_t width, size_t height,
                  optics_params params, uint64_t number)
{
    const size_t stride = width * 3 + 13;
    const size_t size = stride * height, capacity = size + 4096;
    unsigned char *raw = malloc(size + 2 * GUARD);
    unsigned char *saved = malloc(size + 2 * GUARD);
    unsigned char *output = malloc(capacity + 2 * GUARD);
    assert(raw && saved && output);
    memset(raw, 0xa5, size + 2 * GUARD);
    optics_metadata metadata, previous;
    memset(&metadata, 0x5a, sizeof metadata);
    memcpy(&previous, &metadata, sizeof metadata);
    optics_stats stats = {7};
    assert(optics_render(&params, width, height, stride, raw + GUARD,
                         size - 1, number, &metadata, &stats) == -1);
    untouched(raw, size + 2 * GUARD);
    assert(memcmp(&metadata, &previous, sizeof metadata) == 0);
    assert(stats.completed_frames == 7);
    assert(optics_render(&params, width, height, stride, raw + GUARD,
                         size, number, &metadata, &stats) == 0);
    assert(metadata.frame_number == number && stats.completed_frames == 8);
    untouched(raw, GUARD);
    untouched(raw + GUARD + size, GUARD);
    for (size_t y = 0; y < height; ++y)
        untouched(raw + GUARD + y * stride + width * 3, 13);
    memcpy(saved, raw, size + 2 * GUARD);

    memset(output, 0xa5, capacity + 2 * GUARD);
    struct jpeg_engine_result result = jpeg_engine_encode_rgb888(
        raw + GUARD, size, width, height, stride, 95, output + GUARD, capacity);
    assert(result.status == JPEG_ENGINE_OK && result.used > 32);
    assert(result.used <= capacity);
    untouched(output, GUARD);
    untouched(output + GUARD + capacity, GUARD);
    assert(memcmp(raw, saved, size + 2 * GUARD) == 0);
    const size_t used = result.used;
    unsigned char *reference = malloc(used);
    assert(reference);
    memcpy(reference, output + GUARD, used);

    const size_t limits[] = {0, 31, used - 1, used};
    for (size_t i = 0; i < sizeof limits / sizeof limits[0]; ++i) {
        const size_t limit = limits[i];
        memset(output, 0xa5, capacity + 2 * GUARD);
        result = jpeg_engine_encode_rgb888(raw + GUARD, size, width, height,
                                           stride, 95, output + GUARD, limit);
        assert(result.used <= limit);
        untouched(output, GUARD);
        untouched(output + GUARD + limit, capacity - limit + GUARD);
        assert(memcmp(raw, saved, size + 2 * GUARD) == 0);
        if (limit < used) {
            assert(result.status == JPEG_ENGINE_OUTPUT_TOO_SMALL);
            assert(result.used == 0);
        } else {
            assert(result.status == JPEG_ENGINE_OK && result.used == used);
            assert(memcmp(output + GUARD, reference, used) == 0);
        }
    }
    assert(printf("%s %zu %zu %zu %zu\n", name, width, height, stride, used) > 0);
    assert(fwrite(raw + GUARD, 1, size, stdout) == size);
    assert(fwrite(output + GUARD, 1, used, stdout) == used);
    free(reference);
    free(output);
    free(saved);
    free(raw);
}

int main(void)
{
    /* Same two-depth scene and unsaturated exposure as test_optics.c. */
    const optics_params base = {4, 1, 0.001, 100};
    optics_params stopped = base, far = base;
    stopped.f_number = 8;
    far.focus_m = 4;
    frame("base", 1024, 64, base, 42);
    frame("stopped", 1024, 64, stopped, 43);
    frame("far", 1024, 64, far, 44);
    frame("odd", 1025, 65, base, 45);
    assert(fflush(stdout) == 0);
    return 0;
}
