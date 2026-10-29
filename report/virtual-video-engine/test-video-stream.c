#include "video-engine.h"

#include <assert.h>
#include <errno.h>
#include <limits.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include <libavcodec/avcodec.h>
#include <libavutil/error.h>
#include <libavutil/log.h>

#define WIDTH 32u
#define HEIGHT 24u
#define STRIDE (WIDTH * 3 + 7)
#define GUARD 16u
#define CAPACITY 65536u

static int send_error, receive_error, writable_error, open_error, defer_receive;
static unsigned eos_calls;
int __real_avcodec_send_frame(AVCodecContext *context, const AVFrame *frame);
int __wrap_avcodec_send_frame(AVCodecContext *context, const AVFrame *frame);
int __real_avcodec_receive_packet(AVCodecContext *context, AVPacket *packet);
int __wrap_avcodec_receive_packet(AVCodecContext *context, AVPacket *packet);
int __real_av_frame_make_writable(AVFrame *frame);
int __wrap_av_frame_make_writable(AVFrame *frame);
int __real_avcodec_open2(AVCodecContext *context, const AVCodec *codec,
                       AVDictionary **options);
int __wrap_avcodec_open2(AVCodecContext *context, const AVCodec *codec,
                       AVDictionary **options);

int __wrap_avcodec_send_frame(AVCodecContext *context, const AVFrame *frame)
{
    eos_calls += frame == NULL;
    if (send_error != 0) {
        const int error = send_error;
        send_error = 0;
        return error;
    }
    return __real_avcodec_send_frame(context, frame);
}

int __wrap_avcodec_receive_packet(AVCodecContext *context, AVPacket *packet)
{
    if (receive_error != 0) {
        const int error = receive_error;
        receive_error = 0;
        return error;
    }
    if (defer_receive != 0) {
        --defer_receive;
        return AVERROR(EAGAIN);
    }
    return __real_avcodec_receive_packet(context, packet);
}

int __wrap_av_frame_make_writable(AVFrame *frame)
{
    if (writable_error != 0) {
        const int error = writable_error;
        writable_error = 0;
        return error;
    }
    return __real_av_frame_make_writable(frame);
}

int __wrap_avcodec_open2(AVCodecContext *context, const AVCodec *codec,
                       AVDictionary **options)
{
    if (open_error != 0) {
        const int error = open_error;
        open_error = 0;
        return error;
    }
    return __real_avcodec_open2(context, codec, options);
}

struct sink {
    struct video_engine_stream *stream;
    uint8_t data[CAPACITY + 2 * GUARD];
    struct video_engine_packet packets[8];
    size_t used, count, attempts;
    size_t fail_at;
    int fail_code, reenter;
};

static uint8_t pixels[HEIGHT * STRIDE];
static struct video_engine_rgb frame = {pixels,
    (HEIGHT - 1) * STRIDE + WIDTH * 3, STRIDE};

static void unchanged(const uint8_t *bytes, size_t count, uint8_t value)
{
    for (size_t i = 0; i < count; ++i) {
        assert(bytes[i] == value);
    }
}

static void pattern(unsigned number)
{
    memset(pixels, 0xD3, sizeof(pixels));
    for (size_t y = 0; y < HEIGHT; ++y) {
        for (size_t x = 0; x < WIDTH; ++x) {
            uint8_t *p = pixels + y * STRIDE + 3 * x;
            p[0] = (uint8_t)(20 + 4 * x + 15 * number);
            p[1] = (uint8_t)(30 + 5 * y + 10 * number);
            p[2] = (uint8_t)(60 + 20 * number);
        }
    }
}

static int sink_packet(const struct video_engine_stream_packet *packet, void *opaque)
{
    struct sink *const sink = opaque;
    const struct video_engine_stream_info info = video_engine_stream_snapshot(sink->stream);
    assert(info.state == VIDEO_ENGINE_STREAM_ACTIVE && info.status == VIDEO_ENGINE_OK);
    assert(info.packets_received == sink->attempts + 1);
    assert(info.packets_published == sink->count);
    assert(info.bytes_published == sink->used);
    assert(packet->data != NULL && packet->size > 4 && packet->pts == packet->dts);
    assert(packet->data[0] == 0 && packet->data[1] == 0);
    if (sink->reenter) {
        uint8_t *const before = malloc(packet->size);
        assert(before != NULL);
        memcpy(before, packet->data, packet->size);
        assert(video_engine_stream_begin(sink->stream, WIDTH, HEIGHT, 25,
            CAPACITY, sink_packet, sink) == VIDEO_ENGINE_INVALID_STATE);
        assert(video_engine_stream_feed_rgb888(sink->stream, &frame, 100, 1) ==
               VIDEO_ENGINE_INVALID_STATE);
        assert(video_engine_stream_drain(sink->stream) == VIDEO_ENGINE_INVALID_STATE);
        assert(video_engine_stream_finish(sink->stream) == VIDEO_ENGINE_INVALID_STATE);
        assert(video_engine_stream_cancel(sink->stream) == VIDEO_ENGINE_INVALID_STATE);
        video_engine_stream_destroy(sink->stream);
        assert(memcmp(before, packet->data, packet->size) == 0);
        free(before);
    }
    ++sink->attempts;
    if (sink->fail_code != 0 && sink->attempts == sink->fail_at) {
        return sink->fail_code;
    }
    assert(sink->count < 8 && packet->size <= CAPACITY - sink->used);
    sink->packets[sink->count++] = (struct video_engine_packet){
        sink->used, packet->size, packet->pts, packet->dts,
        packet->duration, packet->keyframe};
    memcpy(sink->data + GUARD + sink->used, packet->data, packet->size);
    sink->used += packet->size;
    return 0;
}

static void setup(struct sink *sink)
{
    *sink = (struct sink){0};
    memset(sink->data, 0xA5, sizeof(sink->data));
    sink->stream = video_engine_stream_create();
    assert(sink->stream != NULL);
    pattern(0);
}

static void begin(struct sink *sink, size_t bound)
{
    sink->used = sink->count = sink->attempts = 0;
    memset(sink->data, 0xA5, sizeof(sink->data));
    assert(video_engine_stream_begin(sink->stream, WIDTH, HEIGHT, 25,
                                    bound, sink_packet, sink) == VIDEO_ENGINE_OK);
}

static void counts(struct sink *sink, uint64_t consumed, uint64_t received,
                   uint64_t published, uint64_t flushed)
{
    struct video_engine_stream_info info = video_engine_stream_snapshot(sink->stream);
    assert(info.frames_consumed == consumed && info.packets_received == received);
    assert(info.packets_published == published && info.packets_flushed == flushed);
    assert(info.bytes_published == sink->used);
    unchanged(sink->data, GUARD, 0xA5);
    unchanged(sink->data + GUARD + sink->used,
              sizeof(sink->data) - GUARD - sink->used, 0xA5);
}

static void lifecycle(void)
{
    struct sink sink;
    setup(&sink);
    assert(video_engine_stream_snapshot(NULL).status == VIDEO_ENGINE_INVALID_ARGUMENT);
    assert(video_engine_stream_snapshot(sink.stream).state == VIDEO_ENGINE_STREAM_IDLE);
    assert(video_engine_stream_begin(NULL, WIDTH, HEIGHT, 25, CAPACITY,
                                    sink_packet, &sink) == VIDEO_ENGINE_INVALID_ARGUMENT);
    assert(video_engine_stream_feed_rgb888(NULL, &frame, 0, 1) == VIDEO_ENGINE_INVALID_ARGUMENT);
    assert(video_engine_stream_drain(NULL) == VIDEO_ENGINE_INVALID_ARGUMENT);
    assert(video_engine_stream_finish(NULL) == VIDEO_ENGINE_INVALID_ARGUMENT);
    assert(video_engine_stream_cancel(NULL) == VIDEO_ENGINE_INVALID_ARGUMENT);
    assert(video_engine_stream_feed_rgb888(sink.stream, &frame, 0, 1) == VIDEO_ENGINE_INVALID_STATE);
    assert(video_engine_stream_drain(sink.stream) == VIDEO_ENGINE_INVALID_STATE);
    assert(video_engine_stream_finish(sink.stream) == VIDEO_ENGINE_INVALID_STATE);
    begin(&sink, CAPACITY);
    assert(video_engine_stream_drain(sink.stream) == VIDEO_ENGINE_OK);
    unsigned before = eos_calls;
    assert(video_engine_stream_finish(sink.stream) == VIDEO_ENGINE_OK);
    assert(video_engine_stream_finish(sink.stream) == VIDEO_ENGINE_OK);
    assert(eos_calls == before + 1);
    assert(video_engine_stream_snapshot(sink.stream).state == VIDEO_ENGINE_STREAM_FINISHED);
    assert(video_engine_stream_feed_rgb888(sink.stream, &frame, 0, 1) == VIDEO_ENGINE_INVALID_STATE);
    assert(video_engine_stream_drain(sink.stream) == VIDEO_ENGINE_INVALID_STATE);
    counts(&sink, 0, 0, 0, 0);
    begin(&sink, CAPACITY);
    assert(video_engine_stream_cancel(sink.stream) == VIDEO_ENGINE_OK);
    assert(video_engine_stream_cancel(sink.stream) == VIDEO_ENGINE_OK);
    assert(video_engine_stream_snapshot(sink.stream).state == VIDEO_ENGINE_STREAM_CANCELLED);
    assert(video_engine_stream_finish(sink.stream) == VIDEO_ENGINE_INVALID_STATE);
    begin(&sink, CAPACITY);
    video_engine_stream_destroy(sink.stream);
    video_engine_stream_destroy(NULL);
}

static void arguments(void)
{
    struct sink sink;
    setup(&sink);
    const size_t widths[] = {0, 1, 3, VIDEO_ENGINE_MAX_WIDTH + 2u, SIZE_MAX};
    for (size_t i = 0; i < sizeof(widths) / sizeof(widths[0]); ++i) {
        assert(video_engine_stream_begin(sink.stream, widths[i], HEIGHT, 25,
            CAPACITY, sink_packet, &sink) == VIDEO_ENGINE_INVALID_ARGUMENT);
    }
    assert(video_engine_stream_begin(sink.stream, WIDTH, 1, 25, CAPACITY,
                                    sink_packet, &sink) == VIDEO_ENGINE_INVALID_ARGUMENT);
    assert(video_engine_stream_begin(sink.stream, WIDTH, HEIGHT, 0, CAPACITY,
                                    sink_packet, &sink) == VIDEO_ENGINE_INVALID_ARGUMENT);
    assert(video_engine_stream_begin(sink.stream, WIDTH, HEIGHT, 121, CAPACITY,
                                    sink_packet, &sink) == VIDEO_ENGINE_INVALID_ARGUMENT);
    assert(video_engine_stream_begin(sink.stream, WIDTH, HEIGHT, 25, 0,
                                    sink_packet, &sink) == VIDEO_ENGINE_INVALID_ARGUMENT);
    assert(video_engine_stream_begin(sink.stream, WIDTH, HEIGHT, 25,
        VIDEO_ENGINE_MAX_BYTES + 1u, sink_packet, &sink) == VIDEO_ENGINE_INVALID_ARGUMENT);
    assert(video_engine_stream_begin(sink.stream, WIDTH, HEIGHT, 25, CAPACITY,
                                    NULL, &sink) == VIDEO_ENGINE_INVALID_ARGUMENT);
    assert(video_engine_stream_snapshot(sink.stream).state == VIDEO_ENGINE_STREAM_IDLE);
    begin(&sink, CAPACITY);
    assert(video_engine_stream_feed_rgb888(sink.stream, NULL, 0, 1) == VIDEO_ENGINE_INVALID_ARGUMENT);
    struct video_engine_rgb bad = frame;
    bad.stride = WIDTH * 3 - 1;
    assert(video_engine_stream_feed_rgb888(sink.stream, &bad, 0, 1) == VIDEO_ENGINE_INVALID_ARGUMENT);
    bad = frame;
    --bad.size;
    assert(video_engine_stream_feed_rgb888(sink.stream, &bad, 0, 1) == VIDEO_ENGINE_INPUT_TOO_SMALL);
    bad = frame;
    bad.data = NULL;
    assert(video_engine_stream_feed_rgb888(sink.stream, &bad, 0, 1) == VIDEO_ENGINE_INVALID_ARGUMENT);
    bad = frame;
    bad.stride = SIZE_MAX;
    assert(video_engine_stream_feed_rgb888(sink.stream, &bad, 0, 1) == VIDEO_ENGINE_SIZE_OVERFLOW);
    bad = frame;
    bad.data = (uint8_t *)(UINTPTR_MAX - 3u);
    assert(video_engine_stream_feed_rgb888(sink.stream, &bad, 0, 1) == VIDEO_ENGINE_SIZE_OVERFLOW);
    assert(video_engine_stream_feed_rgb888(sink.stream,
        (const struct video_engine_rgb *)(UINTPTR_MAX - 3u), 0, 1) == VIDEO_ENGINE_SIZE_OVERFLOW);
    assert(video_engine_stream_feed_rgb888(sink.stream,
        (const struct video_engine_rgb *)sink.stream, 0, 1) == VIDEO_ENGINE_OVERLAP);
    bad = frame;
    bad.data = (const uint8_t *)sink.stream;
    assert(video_engine_stream_feed_rgb888(sink.stream, &bad, 0, 1) == VIDEO_ENGINE_OVERLAP);
    const int64_t times[][2] = {{-1, 1}, {0, 0}, {0, -1},
                               {INT64_MAX, 1}, {INT64_MAX - 1, 2}};
    for (size_t i = 0; i < sizeof(times) / sizeof(times[0]); ++i) {
        assert(video_engine_stream_feed_rgb888(sink.stream, &frame,
            times[i][0], times[i][1]) == VIDEO_ENGINE_INVALID_ARGUMENT);
    }
    counts(&sink, 0, 0, 0, 0);
    assert(video_engine_stream_feed_rgb888(sink.stream, &frame, 3, 2) == VIDEO_ENGINE_OK);
    assert(video_engine_stream_feed_rgb888(sink.stream, &frame, 4, 1) == VIDEO_ENGINE_INVALID_ARGUMENT);
    assert(video_engine_stream_feed_rgb888(sink.stream, &frame, 3, 1) == VIDEO_ENGINE_INVALID_ARGUMENT);
    assert(video_engine_stream_feed_rgb888(sink.stream, &frame, 5, 3) == VIDEO_ENGINE_OK);
    assert(sink.packets[0].pts == 3 && sink.packets[0].duration == 2);
    assert(sink.packets[1].pts == 5 && sink.packets[1].duration == 3);
    assert(video_engine_stream_finish(sink.stream) == VIDEO_ENGINE_OK);
    counts(&sink, 2, 2, 2, 0);
    begin(&sink, CAPACITY);
    assert(video_engine_stream_feed_rgb888(sink.stream, &frame, INT64_MAX - 1, 1) == VIDEO_ENGINE_OK);
    assert(video_engine_stream_feed_rgb888(sink.stream, &frame, INT64_MAX, 1) == VIDEO_ENGINE_INVALID_ARGUMENT);
    assert(video_engine_stream_finish(sink.stream) == VIDEO_ENGINE_OK);
    counts(&sink, 1, 1, 1, 0);
    video_engine_stream_destroy(sink.stream);
}

static void progress_and_reentry(void)
{
    struct sink sink;
    setup(&sink);
    begin(&sink, CAPACITY);
    sink.reenter = 1;
    const int64_t pts[] = {0, 2, 7, 8, 12, 18};
    const int64_t duration[] = {1, 3, 1, 2, 4, 1};
    for (size_t i = 0; i < 6; ++i) {
        pattern((unsigned)i);
        uint8_t before[sizeof(pixels)];
        memcpy(before, pixels, sizeof(pixels));
        assert(video_engine_stream_feed_rgb888(sink.stream, &frame, pts[i], duration[i]) ==
               VIDEO_ENGINE_OK);
        assert(memcmp(before, pixels, sizeof(pixels)) == 0);
        memset(pixels, 0x42, sizeof(pixels));
        counts(&sink, i + 1, i + 1, i + 1, 0);
        assert(sink.packets[i].pts == pts[i] && sink.packets[i].dts == pts[i]);
        assert(sink.packets[i].duration == duration[i]);
        assert(video_engine_stream_drain(sink.stream) == VIDEO_ENGINE_OK);
    }
    assert(video_engine_stream_finish(sink.stream) == VIDEO_ENGINE_OK);
    counts(&sink, 6, 6, 6, 0);
    assert(sink.packets[0].keyframe);
    video_engine_stream_destroy(sink.stream);
}

static void sticky(struct sink *sink, enum video_engine_status status,
                   int codec_error, int sink_error)
{
    const struct video_engine_stream_info before = video_engine_stream_snapshot(sink->stream);
    const size_t attempts = sink->attempts;
    assert(before.state == VIDEO_ENGINE_STREAM_FAULT && before.status == status);
    assert(before.codec_error == codec_error && before.sink_error == sink_error);
    assert(video_engine_stream_feed_rgb888(sink->stream, &frame, 100, 1) == status);
    assert(video_engine_stream_drain(sink->stream) == status);
    assert(video_engine_stream_finish(sink->stream) == status);
    assert(video_engine_stream_begin(sink->stream, WIDTH, HEIGHT, 25, CAPACITY,
                                    sink_packet, sink) == VIDEO_ENGINE_INVALID_STATE);
    assert(sink->attempts == attempts);
    const struct video_engine_stream_info after = video_engine_stream_snapshot(sink->stream);
    assert(after.frames_consumed == before.frames_consumed);
    assert(after.packets_received == before.packets_received);
    assert(after.packets_published == before.packets_published);
    assert(video_engine_stream_cancel(sink->stream) == VIDEO_ENGINE_OK);
    const struct video_engine_stream_info cancelled = video_engine_stream_snapshot(sink->stream);
    assert(cancelled.status == status && cancelled.codec_error == codec_error);
    assert(cancelled.sink_error == sink_error && cancelled.frames_consumed == before.frames_consumed);
}

static void sink_failures(void)
{
    const int errors[] = {17, -77};
    for (size_t i = 0; i < 2; ++i) {
        struct sink sink;
        setup(&sink);
        begin(&sink, CAPACITY);
        sink.fail_at = i + 1;
        sink.fail_code = errors[i];
        for (size_t j = 0; j < i; ++j) {
            assert(video_engine_stream_feed_rgb888(sink.stream, &frame, (int64_t)j, 1) == VIDEO_ENGINE_OK);
        }
        assert(video_engine_stream_feed_rgb888(sink.stream, &frame, (int64_t)i, 1) == VIDEO_ENGINE_SINK_ERROR);
        counts(&sink, i + 1, i + 1, i, 0);
        sticky(&sink, VIDEO_ENGINE_SINK_ERROR, 0, errors[i]);
        sink.fail_code = 0;
        begin(&sink, CAPACITY);
        assert(video_engine_stream_snapshot(sink.stream).sink_error == 0);
        assert(video_engine_stream_feed_rgb888(sink.stream, &frame, 0, 1) == VIDEO_ENGINE_OK);
        assert(video_engine_stream_finish(sink.stream) == VIDEO_ENGINE_OK);
        counts(&sink, 1, 1, 1, 0);
        video_engine_stream_destroy(sink.stream);
    }
}

static void packet_bounds(void)
{
    struct sink sink;
    setup(&sink);
    begin(&sink, CAPACITY);
    assert(video_engine_stream_feed_rgb888(sink.stream, &frame, 0, 1) == VIDEO_ENGINE_OK);
    const size_t exact = sink.used;
    assert(exact > 1);
    assert(video_engine_stream_cancel(sink.stream) == VIDEO_ENGINE_OK);
    begin(&sink, exact);
    assert(video_engine_stream_feed_rgb888(sink.stream, &frame, 0, 1) == VIDEO_ENGINE_OK);
    assert(sink.used == exact);
    assert(video_engine_stream_cancel(sink.stream) == VIDEO_ENGINE_OK);
    memset(sink.data, 0xA5, sizeof(sink.data));
    begin(&sink, exact - 1);
    assert(video_engine_stream_feed_rgb888(sink.stream, &frame, 0, 1) == VIDEO_ENGINE_OUTPUT_TOO_SMALL);
    counts(&sink, 1, 1, 0, 0);
    assert(sink.attempts == 0);
    sticky(&sink, VIDEO_ENGINE_OUTPUT_TOO_SMALL, 0, 0);
    begin(&sink, 1);
    assert(video_engine_stream_feed_rgb888(sink.stream, &frame, 0, 1) == VIDEO_ENGINE_OUTPUT_TOO_SMALL);
    counts(&sink, 1, 1, 0, 0);
    video_engine_stream_destroy(sink.stream);
}

static void codec_failures(void)
{
    struct sink sink;
    setup(&sink);
    open_error = AVERROR_EXTERNAL;
    assert(video_engine_stream_begin(sink.stream, WIDTH, HEIGHT, 25, CAPACITY,
                                    sink_packet, &sink) == VIDEO_ENGINE_CODEC_ERROR);
    sticky(&sink, VIDEO_ENGINE_CODEC_ERROR, AVERROR_EXTERNAL, 0);
    begin(&sink, CAPACITY);
    writable_error = AVERROR(ENOMEM);
    assert(video_engine_stream_feed_rgb888(sink.stream, &frame, 0, 1) == VIDEO_ENGINE_NO_MEMORY);
    counts(&sink, 0, 0, 0, 0);
    sticky(&sink, VIDEO_ENGINE_NO_MEMORY, AVERROR(ENOMEM), 0);
    begin(&sink, CAPACITY);
    send_error = AVERROR(EAGAIN);
    assert(video_engine_stream_feed_rgb888(sink.stream, &frame, 0, 1) == VIDEO_ENGINE_CODEC_ERROR);
    counts(&sink, 0, 0, 0, 0);
    sticky(&sink, VIDEO_ENGINE_CODEC_ERROR, AVERROR(EAGAIN), 0);
    begin(&sink, CAPACITY);
    receive_error = AVERROR_EXTERNAL;
    assert(video_engine_stream_feed_rgb888(sink.stream, &frame, 0, 1) == VIDEO_ENGINE_CODEC_ERROR);
    counts(&sink, 1, 0, 0, 0);
    sticky(&sink, VIDEO_ENGINE_CODEC_ERROR, AVERROR_EXTERNAL, 0);
    begin(&sink, CAPACITY);
    assert(video_engine_stream_feed_rgb888(sink.stream, &frame, 0, 1) == VIDEO_ENGINE_OK);
    send_error = AVERROR_EXTERNAL;
    assert(video_engine_stream_feed_rgb888(sink.stream, &frame, 1, 1) == VIDEO_ENGINE_CODEC_ERROR);
    counts(&sink, 1, 1, 1, 0);
    sticky(&sink, VIDEO_ENGINE_CODEC_ERROR, AVERROR_EXTERNAL, 0);
    begin(&sink, CAPACITY);
    assert(video_engine_stream_feed_rgb888(sink.stream, &frame, 0, 1) == VIDEO_ENGINE_OK);
    send_error = AVERROR_EXTERNAL;
    assert(video_engine_stream_finish(sink.stream) == VIDEO_ENGINE_CODEC_ERROR);
    counts(&sink, 1, 1, 1, 0);
    sticky(&sink, VIDEO_ENGINE_CODEC_ERROR, AVERROR_EXTERNAL, 0);
    begin(&sink, CAPACITY);
    assert(video_engine_stream_finish(sink.stream) == VIDEO_ENGINE_OK);
    video_engine_stream_destroy(sink.stream);
}

static void pending_and_eos(void)
{
    struct sink sink;
    setup(&sink);
    begin(&sink, CAPACITY);
    defer_receive = 1;
    assert(video_engine_stream_feed_rgb888(sink.stream, &frame, 5, 2) == VIDEO_ENGINE_OK);
    memset(pixels, 0x44, sizeof(pixels));
    counts(&sink, 1, 0, 0, 0);
    assert(video_engine_stream_feed_rgb888(sink.stream, &frame, 7, 1) == VIDEO_ENGINE_INVALID_STATE);
    assert(video_engine_stream_drain(sink.stream) == VIDEO_ENGINE_OK);
    counts(&sink, 1, 1, 1, 0);
    assert(sink.packets[0].pts == 5 && sink.packets[0].duration == 2);
    assert(video_engine_stream_finish(sink.stream) == VIDEO_ENGINE_OK);
    begin(&sink, CAPACITY);
    defer_receive = 1;
    assert(video_engine_stream_feed_rgb888(sink.stream, &frame, 7, 3) == VIDEO_ENGINE_OK);
    assert(video_engine_stream_finish(sink.stream) == VIDEO_ENGINE_OK);
    counts(&sink, 1, 1, 1, 1);
    assert(sink.packets[0].pts == 7 && sink.packets[0].duration == 3);
    assert(video_engine_stream_finish(sink.stream) == VIDEO_ENGINE_OK);
    assert(video_engine_stream_cancel(sink.stream) == VIDEO_ENGINE_OK);
    begin(&sink, CAPACITY);
    defer_receive = 1;
    assert(video_engine_stream_feed_rgb888(sink.stream, &frame, 0, 1) == VIDEO_ENGINE_OK);
    const unsigned before = eos_calls;
    assert(video_engine_stream_cancel(sink.stream) == VIDEO_ENGINE_OK);
    counts(&sink, 1, 0, 0, 0);
    assert(eos_calls == before);
    video_engine_stream_destroy(sink.stream);
}

static int discard_packet(const struct video_engine_stream_packet *packet, void *opaque)
{
    uint64_t *const count = opaque;
    assert(packet->data != NULL && packet->size > 0 && packet->pts == (int64_t)*count);
    assert(packet->dts == packet->pts && packet->duration == 1);
    ++*count;
    return 0;
}

static void long_stream(void)
{
    struct video_engine_stream *const stream = video_engine_stream_create();
    assert(stream != NULL);
    uint64_t count = 0;
    uint8_t tight[] = {80, 120, 160, 80, 120, 160, 80, 120, 160, 80, 120, 160};
    const struct video_engine_rgb tiny = {tight, sizeof(tight), 6};
    assert(video_engine_stream_begin(stream, 2, 2, 120, CAPACITY,
                                    discard_packet, &count) == VIDEO_ENGINE_OK);
    for (size_t i = 0; i < VIDEO_ENGINE_MAX_FRAMES + 1; ++i) {
        assert(video_engine_stream_feed_rgb888(stream, &tiny, (int64_t)i, 1) == VIDEO_ENGINE_OK);
        tight[0] ^= 1;
    }
    assert(video_engine_stream_finish(stream) == VIDEO_ENGINE_OK);
    struct video_engine_stream_info info = video_engine_stream_snapshot(stream);
    assert(info.frames_consumed == VIDEO_ENGINE_MAX_FRAMES + 1);
    assert(info.frames_consumed == info.packets_published && count == info.frames_consumed);
    assert(video_engine_stream_begin(stream, VIDEO_ENGINE_MAX_WIDTH,
        VIDEO_ENGINE_MAX_HEIGHT, 1, VIDEO_ENGINE_MAX_BYTES, discard_packet, &count) == VIDEO_ENGINE_OK);
    assert(video_engine_stream_finish(stream) == VIDEO_ENGINE_OK);
    video_engine_stream_destroy(stream);
}

int main(void)
{
    av_log_set_level(AV_LOG_ERROR);
    lifecycle();
    arguments();
    progress_and_reentry();
    sink_failures();
    packet_bounds();
    codec_failures();
    pending_and_eos();
    long_stream();
    puts("8 streaming C self-test groups passed");
    return 0;
}
