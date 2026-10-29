#include "jpeg-engine.h"

#include <assert.h>
#include <limits.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include <jpeglib.h>

#define CAPACITY 65536u
#define GUARD 16u

static void expect_error(struct jpeg_engine_result result,
                         enum jpeg_engine_status status)
{
    assert(result.status == status);
    assert(result.used == 0);
}

static void scene(uint8_t *pixels, size_t width, size_t height, size_t stride)
{
    for (size_t y = 0; y < height; ++y) {
        for (size_t x = 0; x < width; ++x) {
            const unsigned checker = ((x / 4 + y / 4) & 1) ? 24 : 0;
            uint8_t *p = pixels + y * stride + x * 3;
            p[0] = (uint8_t)(32 + 160 * x / width + checker);
            p[1] = (uint8_t)(32 + 160 * y / height + checker);
            p[2] = (uint8_t)(48 + 100 * (x + y) / (width + height) + checker);
        }
    }
}

static void decode_and_compare(const uint8_t *data, size_t length,
                               const uint8_t *input, size_t width,
                               size_t height, size_t stride)
{
    struct jpeg_decompress_struct codec;
    struct jpeg_error_mgr error;
    codec.err = jpeg_std_error(&error);
    assert(length <= ULONG_MAX);
    jpeg_create_decompress(&codec);
    jpeg_mem_src(&codec, data, (unsigned long)length);
    assert(jpeg_read_header(&codec, TRUE) == JPEG_HEADER_OK);
    assert(!codec.progressive_mode && codec.data_precision == 8);
    codec.out_color_space = JCS_RGB;
    assert(jpeg_start_decompress(&codec));
    assert(codec.output_width == width && codec.output_height == height);
    assert(codec.output_components == 3);
    uint8_t *row = malloc(width * 3);
    assert(row != NULL);
    size_t total_error = 0;
    while (codec.output_scanline < codec.output_height) {
        const size_t y = codec.output_scanline;
        JSAMPROW rows[] = {row};
        assert(jpeg_read_scanlines(&codec, rows, 1) == 1);
        for (size_t i = 0; i < width * 3; ++i) {
            const int delta = abs((int)row[i] - input[y * stride + i]);
            assert(delta <= 35);
            total_error += (size_t)delta;
        }
    }
    assert(total_error < width * height * 3 * 9);
    assert(jpeg_finish_decompress(&codec));
    jpeg_destroy_decompress(&codec);
    free(row);
}

static void test_roundtrips(void)
{
    const size_t sizes[][2] = {{1, 1}, {3, 5}, {17, 19}, {31, 9}, {64, 33}};
    uint8_t output[CAPACITY];
    for (size_t i = 0; i < sizeof(sizes) / sizeof(sizes[0]); ++i) {
        const size_t w = sizes[i][0], h = sizes[i][1], stride = w * 3 + 7;
        const size_t extent = (h - 1) * stride + w * 3;
        uint8_t *input = malloc(extent);
        uint8_t *snapshot = malloc(extent);
        assert(input != NULL && snapshot != NULL);
        memset(input, 0xa6, extent);
        scene(input, w, h, stride);
        memcpy(snapshot, input, extent);
        struct jpeg_engine_result r = jpeg_engine_encode_rgb888(
            input, extent, w, h, stride, 95, output, sizeof(output));
        assert(r.status == JPEG_ENGINE_OK && r.used > 4);
        assert(output[0] == 0xff && output[1] == 0xd8);
        assert(output[r.used - 2] == 0xff && output[r.used - 1] == 0xd9);
        assert(memcmp(input, snapshot, extent) == 0);
        decode_and_compare(output, r.used, input, w, h, stride);
        free(snapshot);
        free(input);
    }
}

static void test_output_bounds(void)
{
    uint8_t input[33 * 17 * 3], reference[CAPACITY];
    uint8_t guarded[CAPACITY + 2 * GUARD];
    scene(input, 33, 17, 33 * 3);
    struct jpeg_engine_result full = jpeg_engine_encode_rgb888(
        input, sizeof(input), 33, 17, 33 * 3, 95, reference, sizeof(reference));
    assert(full.status == JPEG_ENGINE_OK);
    const size_t capacities[] = {0, 1, 2, 16, 127, 512,
                                full.used - 1, full.used, full.used + 1};
    for (size_t i = 0; i < sizeof(capacities) / sizeof(capacities[0]); ++i) {
        const size_t capacity = capacities[i];
        memset(guarded, 0xa5, sizeof(guarded));
        struct jpeg_engine_result r = jpeg_engine_encode_rgb888(
            input, sizeof(input), 33, 17, 33 * 3, 95,
            guarded + GUARD, capacity);
        if (capacity < full.used) {
            expect_error(r, JPEG_ENGINE_OUTPUT_TOO_SMALL);
        } else {
            assert(r.status == JPEG_ENGINE_OK && r.used == full.used);
            assert(memcmp(guarded + GUARD, reference, r.used) == 0);
        }
        for (size_t j = 0; j < GUARD; ++j) {
            assert(guarded[j] == 0xa5);
        }
        for (size_t j = GUARD + capacity; j < sizeof(guarded); ++j) {
            assert(guarded[j] == 0xa5);
        }
    }
}

static void test_validation(void)
{
    uint8_t input[64] = {0}, output[4096];
#define ENCODE(p, n, w, h, s, q, o, c) \
    jpeg_engine_encode_rgb888(p, n, w, h, s, q, o, c)
#define BAD(w, h, s, q) \
    expect_error(ENCODE(input, sizeof(input), w, h, s, q, output, \
                        sizeof(output)), JPEG_ENGINE_INVALID_ARGUMENT)
    BAD(0, 3, 8, 90);
    BAD(2, 0, 8, 90);
    BAD((size_t)JPEG_MAX_DIMENSION + 1, 3, 8, 90);
    BAD(2, (size_t)JPEG_MAX_DIMENSION + 1, 8, 90);
    BAD(SIZE_MAX, 3, 8, 90);
    BAD(2, SIZE_MAX, 8, 90);
    BAD(2, 3, 5, 90);
    BAD(2, 3, 8, 0);
    BAD(2, 3, 8, 101);
    BAD(2, 3, 8, -1);
    expect_error(ENCODE(NULL, 64, 2, 3, 8, 90, output, sizeof(output)),
                 JPEG_ENGINE_INVALID_ARGUMENT);
    expect_error(ENCODE(input, 64, 2, 3, 8, 90, NULL, sizeof(output)),
                 JPEG_ENGINE_INVALID_ARGUMENT);
    expect_error(ENCODE(input, 21, 2, 3, 8, 90, output, sizeof(output)),
                 JPEG_ENGINE_INPUT_TOO_SMALL);
    expect_error(ENCODE(input, 64, 2, 3, SIZE_MAX, 90, output, sizeof(output)),
                 JPEG_ENGINE_SIZE_OVERFLOW);
    expect_error(ENCODE(input, SIZE_MAX, 2, 3, 8, 90, output, sizeof(output)),
                 JPEG_ENGINE_SIZE_OVERFLOW);
    expect_error(ENCODE(input, 64, 2, 3, 8, 90, output, SIZE_MAX),
                 JPEG_ENGINE_SIZE_OVERFLOW);
    expect_error(ENCODE(input, 64, 2, 3, 8, 90, input, 32),
                 JPEG_ENGINE_OVERLAP);
    expect_error(ENCODE(input, 64, 2, 3, 8, 90, input + 22, 32),
                 JPEG_ENGINE_OVERLAP);
    expect_error(ENCODE(input + 8, 32, 2, 3, 8, 90, input, 16),
                 JPEG_ENGINE_OVERLAP);
    for (size_t i = 0; i < sizeof(input); ++i) {
        assert(input[i] == 0);
    }
    expect_error(ENCODE(input, 64, JPEG_MAX_DIMENSION, 1,
                        (size_t)JPEG_MAX_DIMENSION * 3, 90,
                        output, sizeof(output)), JPEG_ENGINE_INPUT_TOO_SMALL);
    expect_error(ENCODE(input, 64, 1, JPEG_MAX_DIMENSION, 3, 90,
                        output, sizeof(output)), JPEG_ENGINE_INPUT_TOO_SMALL);
#undef BAD
#undef ENCODE
}

static void test_padding_and_last_row(void)
{
    enum { WIDTH = 17, HEIGHT = 13, STRIDE = WIDTH * 3 + 11,
           EXTENT = (HEIGHT - 1) * STRIDE + WIDTH * 3 };
    uint8_t a[EXTENT], b[EXTENT], out_a[CAPACITY], out_b[CAPACITY];
    memset(a, 0x12, sizeof(a));
    memset(b, 0xef, sizeof(b));
    scene(a, WIDTH, HEIGHT, STRIDE);
    scene(b, WIDTH, HEIGHT, STRIDE);
    struct jpeg_engine_result ra = jpeg_engine_encode_rgb888(
        a, sizeof(a), WIDTH, HEIGHT, STRIDE, 95, out_a, sizeof(out_a));
    struct jpeg_engine_result rb = jpeg_engine_encode_rgb888(
        b, sizeof(b), WIDTH, HEIGHT, STRIDE, 95, out_b, sizeof(out_b));
    assert(ra.status == JPEG_ENGINE_OK && rb.status == JPEG_ENGINE_OK);
    assert(ra.used == rb.used && memcmp(out_a, out_b, ra.used) == 0);
    ra = jpeg_engine_encode_rgb888(a, 3, 1, 1, SIZE_MAX, 95,
                                   out_a, sizeof(out_a));
    assert(ra.status == JPEG_ENGINE_OK);
}

static void test_adjacent_spans(void)
{
    uint8_t memory[4099];
    memset(memory, 96, sizeof(memory));
    struct jpeg_engine_result r = jpeg_engine_encode_rgb888(
        memory, 3, 1, 1, 3, 95, memory + 3, 4096);
    assert(r.status == JPEG_ENGINE_OK);
    assert(memory[0] == 96 && memory[1] == 96 && memory[2] == 96);
    r = jpeg_engine_encode_rgb888(memory + 4096, 3, 1, 1, 3, 95, memory, 4096);
    assert(r.status == JPEG_ENGINE_OK);
    assert(memory[4096] == 96 && memory[4097] == 96 && memory[4098] == 96);
}

static void test_recovery_and_quality_limits(void)
{
    uint8_t input[17 * 19 * 3], output[4096];
    scene(input, 17, 19, 17 * 3);
    for (unsigned i = 0; i < 64; ++i) {
        expect_error(jpeg_engine_encode_rgb888(
            input, sizeof(input), 17, 19, 17 * 3, 95, output, 1),
            JPEG_ENGINE_OUTPUT_TOO_SMALL);
        struct jpeg_engine_result r = jpeg_engine_encode_rgb888(
            input, sizeof(input), 17, 19, 17 * 3, 95, output, sizeof(output));
        assert(r.status == JPEG_ENGINE_OK);
    }
    const int qualities[] = {1, 100};
    for (size_t i = 0; i < sizeof(qualities) / sizeof(qualities[0]); ++i) {
        struct jpeg_engine_result r = jpeg_engine_encode_rgb888(
            input, sizeof(input), 17, 19, 17 * 3, qualities[i], output,
            sizeof(output));
        assert(r.status == JPEG_ENGINE_OK && r.used != 0);
    }
}

int main(void)
{
    test_roundtrips();
    test_output_bounds();
    test_validation();
    test_padding_and_last_row();
    test_adjacent_spans();
    test_recovery_and_quality_limits();
    puts("jpeg-engine: 6 C self-test groups passed (host memory only)");
    return 0;
}
