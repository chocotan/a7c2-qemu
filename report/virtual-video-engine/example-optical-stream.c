/* Testable caller example: one live optical lease -> synchronous stream feed.
 * stdout is a test wire over a pipe, never a media file or firmware recorder.
 */
#define _POSIX_C_SOURCE 200809L
#include "video-engine.h"
#include "../virtual-optical-frame-owner/optical-frame-owner.h"

#include <assert.h>
#include <errno.h>
#include <inttypes.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

#include <libavutil/log.h>

#define WIDTH 64u
#define HEIGHT 48u
#define STRIDE (WIDTH * 3u + 7u)
#define GUARD 16u
#define PACKET_CAPACITY 65536u

struct adapter {
    struct video_engine_stream *stream;
    int64_t pts;
    enum video_engine_status status;
};

static int publish_packet(const struct video_engine_stream_packet *packet, void *opaque)
{
    (void)opaque;
    /* Copy during the callback: neither pointer survives this return. */
    uint8_t copy[PACKET_CAPACITY];
    if (packet->size > sizeof(copy)) {
        return -ENOSPC;
    }
    memcpy(copy, packet->data, packet->size);
    if (printf("H264 %zu %" PRId64 " %" PRId64 " %" PRId64 " %d\n",
               packet->size, packet->pts, packet->dts, packet->duration,
               packet->keyframe) < 0 ||
        fwrite(copy, 1, packet->size, stdout) != packet->size || fflush(stdout) != 0) {
        return -EIO;
    }
    return 0;
}

static int feed_borrowed(const optical_frame_view *view, void *opaque)
{
    struct adapter *const adapter = opaque;
    if (view->format != OPTICAL_FRAME_VIRTUAL_RGB888 ||
        view->width != WIDTH || view->height != HEIGHT) {
        adapter->status = VIDEO_ENGINE_INVALID_ARGUMENT;
        return -1;
    }
    /* Test oracle only: send the current source down the pipe before reuse. */
    if (printf("RGB %zu %zu %zu %zu\n", view->size, view->width,
               view->height, view->stride) < 0 ||
        fwrite(view->pixels, 1, view->size, stdout) != view->size) {
        return -1;
    }
    const struct video_engine_rgb rgb = {view->pixels, view->size, view->stride};
    adapter->status = video_engine_stream_feed_rgb888(adapter->stream, &rgb,
                                                     adapter->pts, 1);
    return adapter->status == VIDEO_ENGINE_OK ? 0 : -1;
}

int main(int argc, char **argv)
{
    av_log_set_level(AV_LOG_ERROR);
    const size_t count = argc == 2 && strcmp(argv[1], "2") == 0 ? 2u : 6u;
    assert(argc == 2 && (strcmp(argv[1], "2") == 0 || strcmp(argv[1], "6") == 0));
    optical_frame_owner owner = {0};
    assert(optical_frame_init(&owner) == OPTICAL_FRAME_OK);
    struct adapter adapter = {.stream = video_engine_stream_create()};
    assert(adapter.stream != NULL);
    assert(video_engine_stream_begin(adapter.stream, WIDTH, HEIGHT, 25,
        PACKET_CAPACITY, publish_packet, NULL) == VIDEO_ENGINE_OK);
    uint8_t storage[STRIDE * HEIGHT + GUARD * 2];
    memset(storage, 0xA5, sizeof(storage));
    for (size_t i = 0; i < count; ++i) {
        optical_frame_config config = {{4, 1.0 + (double)i / 2.0,
            (0.55 + (double)i * 0.12) / 400.0, 100}, WIDTH, HEIGHT, STRIDE};
        assert(optical_frame_configure(&owner, &config) == OPTICAL_FRAME_OK);
        optical_frame_lease lease;
        assert(optical_frame_acquire(&owner, storage + GUARD, STRIDE * HEIGHT,
                                    &lease) == OPTICAL_FRAME_OK);
        assert(optical_frame_render(&owner, &lease) == OPTICAL_FRAME_OK);
        adapter.pts = (int64_t)i;
        assert(optical_frame_consumer_read(&owner, &lease, feed_borrowed,
                                          &adapter) == OPTICAL_FRAME_OK);
        assert(adapter.status == VIDEO_ENGINE_OK);
        const struct video_engine_stream_info progress = video_engine_stream_snapshot(adapter.stream);
        assert(progress.frames_consumed == i + 1 && progress.packets_published == i + 1);
        assert(optical_frame_retire(&owner, &lease) == OPTICAL_FRAME_OK);
        memset(storage + GUARD, 0xCC, STRIDE * HEIGHT);
        for (size_t j = 0; j < GUARD; ++j) {
            assert(storage[j] == 0xA5 && storage[GUARD + STRIDE * HEIGHT + j] == 0xA5);
        }
        struct timespec remaining = {0, 40000000};
        while (nanosleep(&remaining, &remaining) != 0) {
            assert(errno == EINTR);
        }
    }
    assert(video_engine_stream_finish(adapter.stream) == VIDEO_ENGINE_OK);
    const struct video_engine_stream_info finished = video_engine_stream_snapshot(adapter.stream);
    optical_frame_info optical;
    assert(optical_frame_snapshot(&owner, &optical) == OPTICAL_FRAME_OK);
    assert(optical.counts.copied == 0 && optical.counts.read == count);
    assert(optical.counts.retired == count && finished.frames_consumed == count);
    assert(finished.packets_received == count && finished.packets_published == count);
    assert(printf("DONE %" PRIu64 " %" PRIu64 " %" PRIu64 " %" PRIu64 "\n",
                  finished.frames_consumed, finished.packets_received,
                  finished.packets_published, optical.counts.retired) > 0);
    assert(fflush(stdout) == 0);
    video_engine_stream_destroy(adapter.stream);
    return 0;
}
