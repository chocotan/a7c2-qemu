#ifndef VIRTUAL_VIDEO_ENGINE_H
#define VIRTUAL_VIDEO_ENGINE_H

#include <stddef.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

/* Host component policy, not Sony hardware limits. */
#define VIDEO_ENGINE_MAX_WIDTH 1920u
#define VIDEO_ENGINE_MAX_HEIGHT 1080u
#define VIDEO_ENGINE_MAX_FPS 120u
#define VIDEO_ENGINE_MAX_FRAMES 600u
#define VIDEO_ENGINE_MAX_BYTES (64u * 1024u * 1024u)

enum video_engine_status {
    VIDEO_ENGINE_OK = 0,
    VIDEO_ENGINE_INVALID_ARGUMENT,
    VIDEO_ENGINE_INPUT_TOO_SMALL,
    VIDEO_ENGINE_OUTPUT_TOO_SMALL,
    VIDEO_ENGINE_SIZE_OVERFLOW,
    VIDEO_ENGINE_OVERLAP,
    VIDEO_ENGINE_NO_MEMORY,
    VIDEO_ENGINE_CODEC_ERROR,
    VIDEO_ENGINE_INVALID_STATE,
    VIDEO_ENGINE_SINK_ERROR
};

struct video_engine_rgb {
    const uint8_t *data;
    size_t size;
    size_t stride;
};

struct video_engine_packet {
    size_t offset;
    size_t size;
    int64_t pts;
    int64_t dts;
    int64_t duration;
    int keyframe;
};

struct video_engine_result {
    enum video_engine_status status;
    int codec_error; /* Actual negative libav error; zero for argument errors. */
    size_t used;
    size_t required;
    size_t packet_count;
    size_t packets_required;
    size_t config_used;
    size_t config_required;
    size_t frames_consumed;
    size_t packets_flushed;
};

/* Opaque, synchronous host encoder. Serialize all access externally; callback
 * reentry may snapshot but must not mutate/destroy this stream. No threads/I/O,
 * Sony AVCC layout, guest DMA/IRQ, AP-ready, MPR/Fsys, or capture claims.
 */
struct video_engine_stream;

enum video_engine_stream_state {
    VIDEO_ENGINE_STREAM_IDLE = 0,
    VIDEO_ENGINE_STREAM_ACTIVE,
    VIDEO_ENGINE_STREAM_FINISHED,
    VIDEO_ENGINE_STREAM_CANCELLED,
    VIDEO_ENGINE_STREAM_FAULT
};

struct video_engine_stream_packet {
    const uint8_t *data; /* Immutable borrowed bytes, valid ONLY in callback. */
    size_t size;
    int64_t pts;
    int64_t dts;
    int64_t duration;
    int keyframe;
};

/* Return zero only after consuming/copying the entire packet. Nonzero means
 * this packet was NOT published, even if the sink made partial side effects.
 * It aborts the stream without retry; the exact return is saved as sink_error.
 */
typedef int (*video_engine_packet_sink)(
    const struct video_engine_stream_packet *packet, void *context);

struct video_engine_stream_info {
    enum video_engine_stream_state state;
    enum video_engine_status status; /* Fault evidence; cancel preserves it. */
    int codec_error; /* Original negative libav error, otherwise zero. */
    int sink_error;  /* Original nonzero callback return, otherwise zero. */
    uint64_t frames_consumed; /* Actual avcodec_send_frame acceptances. */
    uint64_t packets_received; /* Actual compressed packets, even if rejected. */
    uint64_t packets_published; /* Only callbacks that returned zero. */
    uint64_t bytes_published;
    uint64_t packets_flushed; /* Actual packets received after accepted EOS. */
};

struct video_engine_stream *video_engine_stream_create(void);
void video_engine_stream_destroy(struct video_engine_stream *stream);

/* Same explicit virtual RGB8/libx264 format/settings as the one-shot API.
 * begin accepts IDLE/FINISHED/CANCELLED; FAULT requires cancel first.
 * max_packet_bytes is 1..MAX_BYTES, a hard bound on each delivered access unit,
 * not a clip limit. The encoder retains only bounded frame/codec workspace and
 * one compressed packet, never a clip or an upstream frame pointer. The first
 * keyframe contains actual Annex-B SPS/PPS; no separate config callback exists.
 * Invalid arguments/state do not change the stream. Codec/sink faults are
 * sticky: feed/drain/finish return the same fault until cancel; no retry/drop
 * followed by success. cancel discards pending work, preserves counters/error
 * evidence, and permits begin to reset them for a new session. destroy(NULL)
 * is harmless; destroy from this stream's sink is ignored.
 */
enum video_engine_status video_engine_stream_begin(
    struct video_engine_stream *stream, size_t width, size_t height,
    unsigned fps, size_t max_packet_bytes,
    video_engine_packet_sink sink, void *sink_context);

/* pts/duration use time base 1/fps: pts >= 0, duration > 0, pts+duration must
 * fit int64_t, and pts >= prior pts+duration (gaps are allowed, overlaps are not).
 * Every accepted frame's visible RGB is copied/converted into owned workspace
 * before return; input is never retained or changed, including on failure.
 * Success requires actual codec acceptance. Output is drained immediately for
 * zerolatency per-frame progress, with pts=dts and the supplied duration.
 * At most one accepted frame can await output; if this known zerolatency model
 * has not emitted it, another feed returns INVALID_STATE without consumption;
 * use drain/finish. RGB descriptor/data may not overlap this stream's storage.
 */
enum video_engine_status video_engine_stream_feed_rgb888(
    struct video_engine_stream *stream, const struct video_engine_rgb *frame,
    int64_t pts, int64_t duration);
/* drain receives available actual packets without sending EOS. finish sends
 * EOS exactly once and drains to EOF; success becomes FINISHED, repeat finish
 * is harmless. Empty finish is valid. cancel is idempotent and never flushes.
 */
enum video_engine_status video_engine_stream_drain(struct video_engine_stream *stream);
enum video_engine_status video_engine_stream_finish(struct video_engine_stream *stream);
enum video_engine_status video_engine_stream_cancel(struct video_engine_stream *stream);
/* Snapshot is also permitted inside a sink, before that callback is published.
 * NULL yields INVALID_ARGUMENT in the returned status, with zero counters.
 */
struct video_engine_stream_info video_engine_stream_snapshot(
    const struct video_engine_stream *stream);

/*
 * Synchronous, one-shot bounded clip: RGB888, top row first, even dimensions
 * 2..MAX_WIDTH/HEIGHT, integer fps 1..MAX_FPS, count 1..MAX_FRAMES.
 * Each view needs stride >= width*3 and size >= (height-1)*stride+width*3;
 * row padding is ignored. All declared spans must be real objects, nonwrapping.
 * Input views may overlap each other. Output/config/packet spans must be
 * mutually disjoint and disjoint from the views array and all input spans.
 * Caller owns every span through return; input is never modified or retained.
 *
 * Installed libx264 only: software 8-bit constrained-baseline, YUV420P,
 * explicit full RGB -> limited BT.709 conversion, no B-frames. Output contains
 * real Annex-B access units (SPS/PPS repeated at keyframes); config is the
 * encoder's Annex-B extradata. Packet offsets name independent copied bytes,
 * with time base 1/fps, pts=dts=frame index, duration=1. EOS is sent and drained.
 * At most MAX_BYTES of compressed packets are retained temporarily; this
 * one-shot API does not retain all raw frames or implement a live recorder.
 *
 * On every failure used/packet_count/config_used are zero. After a successful
 * encode, including OUTPUT_TOO_SMALL, required/packets_required/config_required
 * are exact; output spans remain untouched on any encode failure. NULL with
 * capacity zero is a sizing query (it still encodes). Nonzero NULL spans fail.
 * No frame is counted as consumed until avcodec_send_frame accepts it.
 * packets_flushed counts actual packets received after sending EOS, possibly 0.
 * No guest AP/DMA/IRQ, leases, codec-ready, MPR/Fsys, or capture claims.
 */
struct video_engine_result video_engine_encode_rgb888(
    const struct video_engine_rgb *frames, size_t count,
    size_t width, size_t height, unsigned fps,
    uint8_t *output, size_t output_capacity,
    struct video_engine_packet *packets, size_t packet_capacity,
    uint8_t *config, size_t config_capacity);

/*
 * Component-only video MP4 mux of the encoder's actual bytes/config/metadata.
 * Same fixed-rate policy. Packets must cover data exactly, in order, with
 * pts=dts=index, duration=1, first keyframe set, and Annex-B start codes.
 * Config must contain SPS and PPS NALs. This is structural validation, not an
 * H.264 authenticity checker; the independent decode tests validate content.
 * Inputs and output may not overlap.
 * Custom seekable bounded-memory AVIO writes header, packets, and trailer.
 * A counting pass determines exact required bytes; NULL/0 is a sizing query.
 * On failure used is zero; an I/O failure in the writing pass can leave partial
 * output. No files, audio, CLI backend, or original firmware storage calls.
 */
struct video_engine_result video_engine_mux_mp4(
    const uint8_t *data, size_t data_size,
    const struct video_engine_packet *packets, size_t packet_count,
    const uint8_t *config, size_t config_size,
    size_t width, size_t height, unsigned fps,
    uint8_t *output, size_t output_capacity);

#ifdef __cplusplus
}
#endif
#endif
