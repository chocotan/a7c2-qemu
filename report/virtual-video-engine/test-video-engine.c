#include "video-engine.h"

#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include <libavcodec/avcodec.h>
#include <libavutil/error.h>
#include <libavutil/log.h>

static int sends_before_failure = -1;
int __real_avcodec_send_frame(AVCodecContext *context, const AVFrame *frame);
int __wrap_avcodec_send_frame(AVCodecContext *context, const AVFrame *frame);

int __wrap_avcodec_send_frame(AVCodecContext *context, const AVFrame *frame)
{
    if (sends_before_failure == 0) {
        sends_before_failure = -1;
        return AVERROR_EXTERNAL;
    }
    if (sends_before_failure > 0) {
        --sends_before_failure;
    }
    return __real_avcodec_send_frame(context, frame);
}

#define WIDTH 32u
#define HEIGHT 24u
#define COUNT 3u
#define CAPACITY 65536u
#define GUARD 16u

static uint8_t pixels[COUNT][HEIGHT * (WIDTH * 3 + 7)];
static struct video_engine_rgb frames[COUNT];
static uint8_t data[CAPACITY + 2 * GUARD];
static uint8_t config[4096 + 2 * GUARD];
static struct video_engine_packet packets[COUNT];

static struct video_engine_result encode(size_t capacity, size_t packet_capacity,
                                         size_t config_capacity)
{
    return video_engine_encode_rgb888(frames, COUNT, WIDTH, HEIGHT, 25,
        data + GUARD, capacity, packets, packet_capacity,
        config + GUARD, config_capacity);
}

static void unchanged(const uint8_t *bytes, size_t count, uint8_t value)
{
    for (size_t i = 0; i < count; ++i) {
        assert(bytes[i] == value);
    }
}

static void empty_error(struct video_engine_result result,
                        enum video_engine_status status)
{
    if (result.status != status) {
        fprintf(stderr, "expected status %d, got %d, libav %d, required %zu\n",
                (int)status, (int)result.status, result.codec_error, result.required);
    }
    assert(result.status == status);
    assert(result.used == 0 && result.packet_count == 0 && result.config_used == 0);
}

static void setup(void)
{
    memset(pixels, 0xDA, sizeof(pixels));
    for (size_t i = 0; i < COUNT; ++i) {
        frames[i] = (struct video_engine_rgb){pixels[i],
            (HEIGHT - 1) * (WIDTH * 3 + 7) + WIDTH * 3, WIDTH * 3 + 7};
        for (size_t y = 0; y < HEIGHT; ++y) {
            for (size_t x = 0; x < WIDTH; ++x) {
                uint8_t *const p = pixels[i] + y * frames[i].stride + x * 3;
                p[0] = (uint8_t)(20 + x * 4 + i * 20);
                p[1] = (uint8_t)(30 + y * 5 + i * 10);
                p[2] = (uint8_t)(60 + i * 30);
            }
        }
    }
    memset(data, 0xA5, sizeof(data));
    memset(config, 0xA5, sizeof(config));
}

static void arguments(void)
{
    struct video_engine_result result;
    empty_error(video_engine_encode_rgb888(NULL, COUNT, WIDTH, HEIGHT, 25,
        NULL, 0, NULL, 0, NULL, 0), VIDEO_ENGINE_INVALID_ARGUMENT);
    const size_t widths[] = {0, 1, 3, VIDEO_ENGINE_MAX_WIDTH + 2u, SIZE_MAX};
    for (size_t i = 0; i < sizeof(widths) / sizeof(widths[0]); ++i) {
        empty_error(video_engine_encode_rgb888(frames, COUNT, widths[i], HEIGHT,
            25, NULL, 0, NULL, 0, NULL, 0), VIDEO_ENGINE_INVALID_ARGUMENT);
    }
    empty_error(video_engine_encode_rgb888(frames, 0, WIDTH, HEIGHT, 25,
        NULL, 0, NULL, 0, NULL, 0), VIDEO_ENGINE_INVALID_ARGUMENT);
    empty_error(video_engine_encode_rgb888(frames, VIDEO_ENGINE_MAX_FRAMES + 1u,
        WIDTH, HEIGHT, 25, NULL, 0, NULL, 0, NULL, 0), VIDEO_ENGINE_INVALID_ARGUMENT);
    empty_error(video_engine_encode_rgb888(frames, COUNT, WIDTH, 3, 25,
        NULL, 0, NULL, 0, NULL, 0), VIDEO_ENGINE_INVALID_ARGUMENT);
    empty_error(video_engine_encode_rgb888(frames, COUNT, WIDTH, HEIGHT, 0,
        NULL, 0, NULL, 0, NULL, 0), VIDEO_ENGINE_INVALID_ARGUMENT);
    empty_error(video_engine_encode_rgb888(frames, COUNT, WIDTH, HEIGHT,
        VIDEO_ENGINE_MAX_FPS + 1u, NULL, 0, NULL, 0, NULL, 0),
        VIDEO_ENGINE_INVALID_ARGUMENT);
    struct video_engine_rgb saved = frames[0];
    frames[0].stride = WIDTH * 3 - 1;
    empty_error(encode(CAPACITY, COUNT, 4096), VIDEO_ENGINE_INVALID_ARGUMENT);
    frames[0] = saved;
    --frames[0].size;
    empty_error(encode(CAPACITY, COUNT, 4096), VIDEO_ENGINE_INPUT_TOO_SMALL);
    frames[0] = saved;
    frames[0].data = NULL;
    empty_error(encode(CAPACITY, COUNT, 4096), VIDEO_ENGINE_INVALID_ARGUMENT);
    frames[0] = saved;
    frames[0].stride = SIZE_MAX;
    empty_error(encode(CAPACITY, COUNT, 4096), VIDEO_ENGINE_SIZE_OVERFLOW);
    frames[0] = saved;
    frames[0].size = SIZE_MAX;
    empty_error(encode(CAPACITY, COUNT, 4096), VIDEO_ENGINE_SIZE_OVERFLOW);
    frames[0] = saved;
    result = video_engine_encode_rgb888(frames, COUNT, WIDTH, HEIGHT, 25,
        (uint8_t *)(UINTPTR_MAX - 3u), 8, NULL, 0, NULL, 0);
    empty_error(result, VIDEO_ENGINE_SIZE_OVERFLOW);
    empty_error(encode(CAPACITY, SIZE_MAX, 4096), VIDEO_ENGINE_SIZE_OVERFLOW);
    empty_error(video_engine_encode_rgb888(frames, COUNT, WIDTH, HEIGHT, 25,
        NULL, 1, NULL, 0, NULL, 0), VIDEO_ENGINE_INVALID_ARGUMENT);
    unchanged(data, sizeof(data), 0xA5);
}

static void aliases(void)
{
    empty_error(video_engine_encode_rgb888(frames, COUNT, WIDTH, HEIGHT, 25,
        pixels[0], 20, packets, COUNT, config + GUARD, 4096), VIDEO_ENGINE_OVERLAP);
    empty_error(video_engine_encode_rgb888(frames, COUNT, WIDTH, HEIGHT, 25,
        (uint8_t *)frames, sizeof(frames), packets, COUNT, config + GUARD, 4096),
        VIDEO_ENGINE_OVERLAP);
    empty_error(video_engine_encode_rgb888(frames, COUNT, WIDTH, HEIGHT, 25,
        data + GUARD, CAPACITY, packets, COUNT, data + GUARD + 1, 30),
        VIDEO_ENGINE_OVERLAP);
    empty_error(video_engine_encode_rgb888(frames, COUNT, WIDTH, HEIGHT, 25,
        (uint8_t *)packets, sizeof(packets), packets, COUNT, config + GUARD, 4096),
        VIDEO_ENGINE_OVERLAP);
}

static void encode_and_capacities(void)
{
    uint8_t snapshot[sizeof(pixels)];
    memcpy(snapshot, pixels, sizeof(pixels));
    const struct video_engine_result query = encode(0, 0, 0);
    empty_error(query, VIDEO_ENGINE_OUTPUT_TOO_SMALL);
    assert(query.required > 0 && query.packets_required == COUNT);
    assert(query.config_required > 0 && query.frames_consumed == COUNT);
    assert(query.packets_flushed == 0);
    const size_t capacities[][3] = {
        {query.required - 1, COUNT, query.config_required},
        {query.required, COUNT - 1, query.config_required},
        {query.required, COUNT, query.config_required - 1}
    };
    for (size_t i = 0; i < 3; ++i) {
        empty_error(encode(capacities[i][0], capacities[i][1], capacities[i][2]),
                    VIDEO_ENGINE_OUTPUT_TOO_SMALL);
        unchanged(data, sizeof(data), 0xA5);
        unchanged(config, sizeof(config), 0xA5);
    }
    const struct video_engine_result result = encode(query.required, COUNT,
                                                      query.config_required);
    assert(result.status == VIDEO_ENGINE_OK && result.codec_error == 0);
    assert(result.used == query.required && result.packet_count == COUNT);
    assert(result.frames_consumed == COUNT && result.packets_flushed == 0);
    assert(memcmp(snapshot, pixels, sizeof(pixels)) == 0);
    unchanged(data, GUARD, 0xA5);
    unchanged(data + GUARD + result.used, sizeof(data) - GUARD - result.used, 0xA5);
    unchanged(config, GUARD, 0xA5);
    unchanged(config + GUARD + result.config_used,
              sizeof(config) - GUARD - result.config_used, 0xA5);
    size_t offset = 0;
    for (size_t i = 0; i < COUNT; ++i) {
        assert(packets[i].offset == offset && packets[i].size > 0);
        assert(packets[i].pts == (int64_t)i && packets[i].dts == (int64_t)i);
        assert(packets[i].duration == 1);
        offset += packets[i].size;
    }
    assert(offset == result.used && packets[0].keyframe == 1);
}

static void padding_and_eos(void)
{
    struct video_engine_result first = encode(CAPACITY, COUNT, 4096);
    assert(first.status == VIDEO_ENGINE_OK);
    uint8_t *const snapshot = malloc(first.used);
    assert(snapshot != NULL);
    memcpy(snapshot, data + GUARD, first.used);
    for (size_t i = 0; i < COUNT; ++i) {
        for (size_t y = 0; y < HEIGHT - 1; ++y) {
            memset(pixels[i] + y * frames[i].stride + WIDTH * 3, 0x12, 7);
        }
    }
    struct video_engine_result second = encode(CAPACITY, COUNT, 4096);
    assert(second.status == VIDEO_ENGINE_OK && second.used == first.used);
    assert(memcmp(snapshot, data + GUARD, first.used) == 0);
    free(snapshot);
    const struct video_engine_rgb saved = frames[0];
    uint8_t *const tight = malloc(saved.size);
    assert(tight != NULL);
    memcpy(tight, saved.data, saved.size);
    frames[0].data = tight;
    struct video_engine_result single = video_engine_encode_rgb888(frames, 1,
        WIDTH, HEIGHT, 1, data + GUARD, CAPACITY, packets, COUNT,
        config + GUARD, 4096);
    assert(single.status == VIDEO_ENGINE_OK && single.frames_consumed == 1);
    assert(single.packet_count == 1 && single.packets_flushed == 0);
    assert(memcmp(tight, saved.data, saved.size) == 0);
    frames[0] = saved;
    free(tight);
}

static void mux_and_failures(void)
{
    const struct video_engine_result encoded = encode(CAPACITY, COUNT, 4096);
    assert(encoded.status == VIDEO_ENGINE_OK);
    struct video_engine_result query = video_engine_mux_mp4(data + GUARD,
        encoded.used, packets, COUNT, config + GUARD, encoded.config_used,
        WIDTH, HEIGHT, 25, NULL, 0);
    empty_error(query, VIDEO_ENGINE_OUTPUT_TOO_SMALL);
    assert(query.required > encoded.used);
    uint8_t *const output = malloc(query.required + 2 * GUARD);
    assert(output != NULL);
    memset(output, 0x5A, query.required + 2 * GUARD);
    struct video_engine_result short_output = video_engine_mux_mp4(data + GUARD,
        encoded.used, packets, COUNT, config + GUARD, encoded.config_used,
        WIDTH, HEIGHT, 25, output + GUARD, query.required - 1);
    empty_error(short_output, VIDEO_ENGINE_OUTPUT_TOO_SMALL);
    assert(short_output.required == query.required);
    unchanged(output, query.required + 2 * GUARD, 0x5A);
    struct video_engine_result result = video_engine_mux_mp4(data + GUARD,
        encoded.used, packets, COUNT, config + GUARD, encoded.config_used,
        WIDTH, HEIGHT, 25, output + GUARD, query.required);
    assert(result.status == VIDEO_ENGINE_OK && result.used == query.required);
    assert(memcmp(output + GUARD + 4, "ftyp", 4) == 0);
    unchanged(output, GUARD, 0x5A);
    unchanged(output + GUARD + query.required, GUARD, 0x5A);
    free(output);
    empty_error(video_engine_mux_mp4(data + GUARD, encoded.used - 1, packets,
        COUNT, config + GUARD, encoded.config_used, WIDTH, HEIGHT, 25, NULL, 0),
        VIDEO_ENGINE_INVALID_ARGUMENT);
    empty_error(video_engine_mux_mp4(data + GUARD, encoded.used, packets,
        COUNT, config + GUARD, encoded.config_used, WIDTH, HEIGHT, 25,
        data + GUARD, encoded.used), VIDEO_ENGINE_OVERLAP);
    packets[1].pts = 0;
    empty_error(video_engine_mux_mp4(data + GUARD, encoded.used, packets,
        COUNT, config + GUARD, encoded.config_used, WIDTH, HEIGHT, 25, NULL, 0),
        VIDEO_ENGINE_INVALID_ARGUMENT);
    packets[1].pts = 1;
    const uint8_t bad_config[] = {0, 0, 0, 1, 0x68, 0x11, 0x22, 0x33};
    result = video_engine_mux_mp4(data + GUARD, encoded.used, packets, COUNT,
        bad_config, sizeof(bad_config), WIDTH, HEIGHT, 25, NULL, 0);
    empty_error(result, VIDEO_ENGINE_INVALID_ARGUMENT);
    assert(result.codec_error == 0);
}

static void codec_failures(void)
{
    memset(data, 0xA5, sizeof(data));
    memset(config, 0xA5, sizeof(config));
    for (int fail_after = 1; fail_after <= (int)COUNT; ++fail_after) {
        sends_before_failure = fail_after;
        struct video_engine_result result = encode(CAPACITY, COUNT, 4096);
        empty_error(result, VIDEO_ENGINE_CODEC_ERROR);
        assert(result.codec_error == AVERROR_EXTERNAL);
        assert(result.frames_consumed == (size_t)fail_after);
        assert(result.required == 0 && result.packets_required == 0);
        unchanged(data, sizeof(data), 0xA5);
        unchanged(config, sizeof(config), 0xA5);
    }
    assert(encode(CAPACITY, COUNT, 4096).status == VIDEO_ENGINE_OK);
}

int main(void)
{
    av_log_set_level(AV_LOG_ERROR);
    setup();
    arguments();
    aliases();
    encode_and_capacities();
    padding_and_eos();
    mux_and_failures();
    codec_failures();
    puts("6 C self-test groups passed");
    return 0;
}
