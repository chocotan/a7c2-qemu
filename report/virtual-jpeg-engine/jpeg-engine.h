#ifndef VIRTUAL_JPEG_ENGINE_H
#define VIRTUAL_JPEG_ENGINE_H

#include <stddef.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

enum jpeg_engine_status {
    JPEG_ENGINE_OK = 0,
    JPEG_ENGINE_INVALID_ARGUMENT,
    JPEG_ENGINE_INPUT_TOO_SMALL,
    JPEG_ENGINE_OUTPUT_TOO_SMALL,
    JPEG_ENGINE_SIZE_OVERFLOW,
    JPEG_ENGINE_OVERLAP,
    JPEG_ENGINE_NO_MEMORY,
    JPEG_ENGINE_CODEC_ERROR
};

struct jpeg_engine_result {
    enum jpeg_engine_status status;
    size_t used;
};

/*
 * Synchronous host component: virtual RGB888 (R, G, B bytes), top row first.
 * width/height: 1..installed libjpeg JPEG_MAX_DIMENSION; quality: 1..100.
 * stride >= width*3; input_size >= (height-1)*stride + width*3.
 * Row padding is ignored; the last row needs no trailing padding.
 * Non-NULL input/output must name actual readable/writable objects of their
 * declared sizes. Their entire declared spans must not overlap or wrap.
 * The caller owns both buffers for the whole call; input is never modified.
 * On success output[0..used) is a complete baseline JPEG (default 4:2:0).
 * On every error used is zero; output may contain an invalid partial stream.
 * No whole-frame copy or growing output allocation; libjpeg allocates internal
 * scanline/MCU workspace. All state is per call; disjoint calls are thread-safe.
 * No guest DMA, MMIO, Sony pixel-layout, interrupt, or storage semantics.
 */
struct jpeg_engine_result jpeg_engine_encode_rgb888(
    const uint8_t *input, size_t input_size,
    size_t width, size_t height, size_t stride, int quality,
    uint8_t *output, size_t output_capacity);

#ifdef __cplusplus
}
#endif

#endif
