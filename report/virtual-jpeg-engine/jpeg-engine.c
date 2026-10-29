#include "jpeg-engine.h"

#include <setjmp.h>
#include <stdio.h>
#include <stdlib.h>

#include <jpeglib.h>
#include <jerror.h>

struct engine_error {
    struct jpeg_error_mgr pub;
    jmp_buf jump;
    enum jpeg_engine_status status;
};

struct bounded_destination {
    struct jpeg_destination_mgr pub;
    uint8_t *output;
    size_t capacity;
    JOCTET probe;
    int probing;
};

struct engine_context {
    struct jpeg_compress_struct codec;
    struct engine_error error;
    struct bounded_destination destination;
};

static void engine_error_exit(j_common_ptr codec)
{
    struct engine_error *error = (struct engine_error *)codec->err;
    if (error->status == JPEG_ENGINE_OK) {
        error->status = error->pub.msg_code == JERR_OUT_OF_MEMORY
                            ? JPEG_ENGINE_NO_MEMORY : JPEG_ENGINE_CODEC_ERROR;
    }
    longjmp(error->jump, 1);
}

static void destination_init(j_compress_ptr codec)
{
    struct bounded_destination *dest =
        (struct bounded_destination *)codec->dest;
    dest->pub.next_output_byte = dest->output;
    dest->pub.free_in_buffer = dest->capacity;
    dest->probing = 0;
}

static void destination_full(j_compress_ptr codec)
{
    struct engine_error *error = (struct engine_error *)codec->err;
    error->status = JPEG_ENGINE_OUTPUT_TOO_SMALL;
    ERREXIT(codec, JERR_BUFFER_SIZE);
}

static boolean destination_empty(j_compress_ptr codec)
{
    struct bounded_destination *dest =
        (struct bounded_destination *)codec->dest;
    if (dest->probing) {
        destination_full(codec);
        return FALSE;
    }
    /* libjpeg calls empty even when the final byte exactly fills the span. */
    dest->probing = 1;
    dest->pub.next_output_byte = &dest->probe;
    dest->pub.free_in_buffer = 1;
    return TRUE;
}

static void destination_finish(j_compress_ptr codec)
{
    struct bounded_destination *dest =
        (struct bounded_destination *)codec->dest;
    if (dest->probing && dest->pub.free_in_buffer != 1) {
        destination_full(codec);
    }
}

struct jpeg_engine_result jpeg_engine_encode_rgb888(
    const uint8_t *input, size_t input_size,
    size_t width, size_t height, size_t stride, int quality,
    uint8_t *output, size_t output_capacity)
{
    struct jpeg_engine_result result = {JPEG_ENGINE_INVALID_ARGUMENT, 0};
    if (input == NULL || output == NULL || width == 0 || height == 0 ||
        width > JPEG_MAX_DIMENSION || height > JPEG_MAX_DIMENSION ||
        quality < 1 || quality > 100) {
        return result;
    }
    if (width > SIZE_MAX / 3) {
        return (struct jpeg_engine_result){JPEG_ENGINE_SIZE_OVERFLOW, 0};
    }
    const size_t row_bytes = width * 3;
    if (stride < row_bytes) {
        return result;
    }
    if (height - 1 > (SIZE_MAX - row_bytes) / stride ||
        input_size > UINTPTR_MAX - (uintptr_t)input ||
        output_capacity > UINTPTR_MAX - (uintptr_t)output) {
        return (struct jpeg_engine_result){JPEG_ENGINE_SIZE_OVERFLOW, 0};
    }
    const size_t extent = (height - 1) * stride + row_bytes;
    if (input_size < extent) {
        return (struct jpeg_engine_result){JPEG_ENGINE_INPUT_TOO_SMALL, 0};
    }
    if (output_capacity == 0) {
        return (struct jpeg_engine_result){JPEG_ENGINE_OUTPUT_TOO_SMALL, 0};
    }
    if ((uintptr_t)input < (uintptr_t)output + output_capacity &&
        (uintptr_t)output < (uintptr_t)input + input_size) {
        return (struct jpeg_engine_result){JPEG_ENGINE_OVERLAP, 0};
    }

    /* Heap state remains defined after longjmp, unlike modified stack locals. */
    struct engine_context *const ctx = calloc(1, sizeof(*ctx));
    if (ctx == NULL) {
        return (struct jpeg_engine_result){JPEG_ENGINE_NO_MEMORY, 0};
    }
    ctx->codec.err = jpeg_std_error(&ctx->error.pub);
    ctx->error.pub.error_exit = engine_error_exit;
    if (setjmp(ctx->error.jump) != 0) {
        result.status = ctx->error.status;
        jpeg_destroy_compress(&ctx->codec);
        free(ctx);
        return result;
    }
    jpeg_create_compress(&ctx->codec);
    ctx->destination.output = output;
    ctx->destination.capacity = output_capacity;
    ctx->destination.pub.init_destination = destination_init;
    ctx->destination.pub.empty_output_buffer = destination_empty;
    ctx->destination.pub.term_destination = destination_finish;
    ctx->codec.dest = &ctx->destination.pub;
    ctx->codec.image_width = (JDIMENSION)width;
    ctx->codec.image_height = (JDIMENSION)height;
    ctx->codec.input_components = 3;
    ctx->codec.in_color_space = JCS_RGB;
    jpeg_set_defaults(&ctx->codec);
    jpeg_set_quality(&ctx->codec, quality, TRUE);
    ctx->codec.optimize_coding = FALSE;
    jpeg_start_compress(&ctx->codec, TRUE);
    while (ctx->codec.next_scanline < ctx->codec.image_height) {
        JSAMPROW row = (JSAMPROW)(input +
            (size_t)ctx->codec.next_scanline * stride);
        if (jpeg_write_scanlines(&ctx->codec, &row, 1) != 1) {
            ERREXIT(&ctx->codec, JERR_CANT_SUSPEND);
        }
    }
    jpeg_finish_compress(&ctx->codec);
    result.status = JPEG_ENGINE_OK;
    result.used = ctx->destination.probing ? output_capacity :
                  output_capacity - ctx->destination.pub.free_in_buffer;
    jpeg_destroy_compress(&ctx->codec);
    free(ctx);
    return result;
}
