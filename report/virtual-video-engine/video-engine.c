#include "video-engine.h"

#include <errno.h>
#include <limits.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include <libavcodec/avcodec.h>
#include <libavformat/avformat.h>
#include <libavutil/error.h>
#include <libavutil/mem.h>
#include <libavutil/opt.h>
#include <libswscale/swscale.h>

struct span {
    const void *data;
    size_t size;
};

static enum video_engine_status valid_span(struct span span)
{
    if (span.data == NULL && span.size != 0) {
        return VIDEO_ENGINE_INVALID_ARGUMENT;
    }
    if (span.size > UINTPTR_MAX - (uintptr_t)span.data) {
        return VIDEO_ENGINE_SIZE_OVERFLOW;
    }
    return VIDEO_ENGINE_OK;
}

static int overlaps(struct span a, struct span b)
{
    return a.size != 0 && b.size != 0 &&
           (uintptr_t)a.data < (uintptr_t)b.data + b.size &&
           (uintptr_t)b.data < (uintptr_t)a.data + a.size;
}

static int valid_format(size_t width, size_t height, unsigned fps)
{
    return width >= 2 && width <= VIDEO_ENGINE_MAX_WIDTH &&
           height >= 2 && height <= VIDEO_ENGINE_MAX_HEIGHT &&
           (width & 1u) == 0 && (height & 1u) == 0 &&
           fps >= 1 && fps <= VIDEO_ENGINE_MAX_FPS;
}

static void codec_failure(struct video_engine_result *result, int error)
{
    result->status = error == AVERROR(ENOMEM) ? VIDEO_ENGINE_NO_MEMORY :
                     error == AVERROR(EOVERFLOW) ? VIDEO_ENGINE_SIZE_OVERFLOW :
                     VIDEO_ENGINE_CODEC_ERROR;
    result->codec_error = error;
    result->used = result->required = 0;
    result->packet_count = result->packets_required = 0;
    result->config_used = result->config_required = 0;
}

static enum video_engine_status valid_rgb(const struct video_engine_rgb *frame,
                                          size_t width, size_t height)
{
    enum video_engine_status status = valid_span(
        (struct span){frame->data, frame->size});
    if (status != VIDEO_ENGINE_OK) {
        return status;
    }
    const size_t row_bytes = width * 3;
    if (frame->data == NULL || frame->stride < row_bytes) {
        return VIDEO_ENGINE_INVALID_ARGUMENT;
    }
    if (height - 1 > (SIZE_MAX - row_bytes) / frame->stride) {
        return VIDEO_ENGINE_SIZE_OVERFLOW;
    }
    return frame->size < (height - 1) * frame->stride + row_bytes ?
           VIDEO_ENGINE_INPUT_TOO_SMALL : VIDEO_ENGINE_OK;
}

struct encoding {
    AVCodecContext *codec;
    AVFrame *rgb;
    AVFrame *yuv;
    struct SwsContext *scaler;
    AVPacket *scratch;
};

static void encoding_free(struct encoding *encoding)
{
    av_packet_free(&encoding->scratch);
    av_frame_free(&encoding->rgb);
    av_frame_free(&encoding->yuv);
    sws_freeContext(encoding->scaler);
    avcodec_free_context(&encoding->codec);
    memset(encoding, 0, sizeof(*encoding));
}

static int encoding_open(struct encoding *encoding, size_t width,
                         size_t height, unsigned fps)
{
    const AVCodec *const codec = avcodec_find_encoder_by_name("libx264");
    if (codec == NULL) {
        return AVERROR_ENCODER_NOT_FOUND;
    }
    encoding->codec = avcodec_alloc_context3(codec);
    encoding->rgb = av_frame_alloc();
    encoding->yuv = av_frame_alloc();
    encoding->scratch = av_packet_alloc();
    if (encoding->codec == NULL || encoding->rgb == NULL ||
        encoding->yuv == NULL || encoding->scratch == NULL) {
        return AVERROR(ENOMEM);
    }
    AVCodecContext *const context = encoding->codec;
    context->width = (int)width;
    context->height = (int)height;
    context->pix_fmt = AV_PIX_FMT_YUV420P;
    context->time_base = (AVRational){1, (int)fps};
    context->framerate = (AVRational){(int)fps, 1};
    context->max_b_frames = 0;
    context->gop_size = (int)fps * 2;
    context->thread_count = 1;
    context->profile = AV_PROFILE_H264_BASELINE;
    context->flags |= AV_CODEC_FLAG_GLOBAL_HEADER;
    context->color_range = AVCOL_RANGE_MPEG;
    context->colorspace = AVCOL_SPC_BT709;
    context->color_primaries = AVCOL_PRI_BT709;
    context->color_trc = AVCOL_TRC_BT709;
    const char *const names[] = {"preset", "tune", "profile", "crf",
                                "x264-params"};
    const char *const values[] = {"veryfast", "zerolatency", "baseline", "18",
                                 "annexb=1:repeat-headers=1"};
    for (size_t i = 0; i < sizeof(names) / sizeof(names[0]); ++i) {
        const int error = av_opt_set(context->priv_data, names[i], values[i], 0);
        if (error < 0) {
            return error;
        }
    }
    int error = avcodec_open2(context, codec, NULL);
    if (error < 0) {
        return error;
    }
    encoding->rgb->format = AV_PIX_FMT_RGB24;
    encoding->yuv->format = AV_PIX_FMT_YUV420P;
    encoding->rgb->width = encoding->yuv->width = (int)width;
    encoding->rgb->height = encoding->yuv->height = (int)height;
    encoding->yuv->color_range = context->color_range;
    encoding->yuv->colorspace = context->colorspace;
    encoding->yuv->color_primaries = context->color_primaries;
    encoding->yuv->color_trc = context->color_trc;
    error = av_frame_get_buffer(encoding->rgb, 32);
    if (error < 0) {
        return error;
    }
    error = av_frame_get_buffer(encoding->yuv, 32);
    if (error < 0) {
        return error;
    }
    encoding->scaler = sws_getContext((int)width, (int)height, AV_PIX_FMT_RGB24,
        (int)width, (int)height, AV_PIX_FMT_YUV420P, SWS_BILINEAR,
        NULL, NULL, NULL);
    if (encoding->scaler == NULL) {
        return AVERROR(ENOMEM);
    }
    const int *const coefficients = sws_getCoefficients(SWS_CS_ITU709);
    return sws_setColorspaceDetails(encoding->scaler, coefficients, 1,
                                    coefficients, 0, 0, 1 << 16, 1 << 16);
}

struct video_engine_stream {
    struct encoding encoding;
    struct video_engine_stream_info info;
    video_engine_packet_sink sink;
    void *sink_context;
    size_t width, height, max_packet_bytes;
    /* shortcut: one pending frame fits zerolatency; add a bounded queue for delayed encoders. */
    int64_t pending_pts, pending_duration, next_pts;
    int pending, in_callback;
};

static int annexb_start(const uint8_t *data, size_t size);

static enum video_engine_status stream_fault(struct video_engine_stream *stream,
    enum video_engine_status status, int codec_error, int sink_error)
{
    stream->info.state = VIDEO_ENGINE_STREAM_FAULT;
    stream->info.status = status;
    stream->info.codec_error = codec_error;
    stream->info.sink_error = sink_error;
    if (stream->encoding.scratch != NULL) {
        av_packet_unref(stream->encoding.scratch);
    }
    return status;
}

static enum video_engine_status stream_codec_fault(
    struct video_engine_stream *stream, int error)
{
    struct video_engine_result result = {0};
    codec_failure(&result, error);
    return stream_fault(stream, result.status, error, 0);
}

static enum video_engine_status stream_active(struct video_engine_stream *stream)
{
    if (stream == NULL) {
        return VIDEO_ENGINE_INVALID_ARGUMENT;
    }
    if (stream->in_callback) {
        return VIDEO_ENGINE_INVALID_STATE;
    }
    if (stream->info.state == VIDEO_ENGINE_STREAM_FAULT) {
        return stream->info.status;
    }
    return stream->info.state == VIDEO_ENGINE_STREAM_ACTIVE ? VIDEO_ENGINE_OK :
           VIDEO_ENGINE_INVALID_STATE;
}

struct video_engine_stream *video_engine_stream_create(void)
{
    return calloc(1, sizeof(struct video_engine_stream));
}

void video_engine_stream_destroy(struct video_engine_stream *stream)
{
    if (stream != NULL && !stream->in_callback) {
        encoding_free(&stream->encoding);
        free(stream);
    }
}

enum video_engine_status video_engine_stream_begin(
    struct video_engine_stream *stream, size_t width, size_t height,
    unsigned fps, size_t max_packet_bytes,
    video_engine_packet_sink sink, void *sink_context)
{
    if (stream == NULL || !valid_format(width, height, fps) || sink == NULL ||
        max_packet_bytes == 0 || max_packet_bytes > VIDEO_ENGINE_MAX_BYTES) {
        return VIDEO_ENGINE_INVALID_ARGUMENT;
    }
    if (stream->in_callback || stream->info.state == VIDEO_ENGINE_STREAM_ACTIVE ||
        stream->info.state == VIDEO_ENGINE_STREAM_FAULT) {
        return VIDEO_ENGINE_INVALID_STATE;
    }
    encoding_free(&stream->encoding);
    stream->info = (struct video_engine_stream_info){
        .state = VIDEO_ENGINE_STREAM_ACTIVE, .status = VIDEO_ENGINE_OK};
    stream->sink = sink;
    stream->sink_context = sink_context;
    stream->width = width;
    stream->height = height;
    stream->max_packet_bytes = max_packet_bytes;
    stream->pending = 0;
    stream->next_pts = 0;
    const int error = encoding_open(&stream->encoding, width, height, fps);
    if (error < 0) {
        return stream_codec_fault(stream, error);
    }
    return VIDEO_ENGINE_OK;
}

static enum video_engine_status receive_packets(struct video_engine_stream *stream,
                                                int flushing)
{
    for (;;) {
        if (stream->info.packets_received == UINT64_MAX) {
            return stream_fault(stream, VIDEO_ENGINE_SIZE_OVERFLOW, 0, 0);
        }
        AVPacket *const packet = stream->encoding.scratch;
        const int error = avcodec_receive_packet(stream->encoding.codec, packet);
        if (error == AVERROR(EAGAIN) && !flushing) {
            return VIDEO_ENGINE_OK;
        }
        if (error == AVERROR_EOF && flushing) {
            return VIDEO_ENGINE_OK;
        }
        if (error < 0) {
            return stream_codec_fault(stream, error);
        }
        ++stream->info.packets_received;
        stream->info.packets_flushed += flushing != 0;
        if (!stream->pending || packet->size <= 0 ||
            packet->pts != stream->pending_pts || packet->dts != packet->pts ||
            (packet->duration != 0 && packet->duration != stream->pending_duration) ||
            !annexb_start(packet->data, (size_t)packet->size)) {
            return stream_codec_fault(stream, AVERROR_INVALIDDATA);
        }
        if ((size_t)packet->size > stream->max_packet_bytes) {
            return stream_fault(stream, VIDEO_ENGINE_OUTPUT_TOO_SMALL, 0, 0);
        }
        if ((uint64_t)packet->size > UINT64_MAX - stream->info.bytes_published) {
            return stream_fault(stream, VIDEO_ENGINE_SIZE_OVERFLOW, 0, 0);
        }
        const struct video_engine_stream_packet view = {
            packet->data, (size_t)packet->size, packet->pts, packet->dts,
            stream->pending_duration, (packet->flags & AV_PKT_FLAG_KEY) != 0};
        stream->in_callback = 1;
        const int sink_error = stream->sink(&view, stream->sink_context);
        stream->in_callback = 0;
        if (sink_error != 0) {
            return stream_fault(stream, VIDEO_ENGINE_SINK_ERROR, 0, sink_error);
        }
        ++stream->info.packets_published;
        stream->info.bytes_published += view.size;
        stream->pending = 0;
        av_packet_unref(packet);
    }
}

enum video_engine_status video_engine_stream_drain(struct video_engine_stream *stream)
{
    const enum video_engine_status status = stream_active(stream);
    return status == VIDEO_ENGINE_OK ? receive_packets(stream, 0) : status;
}

enum video_engine_status video_engine_stream_feed_rgb888(
    struct video_engine_stream *stream, const struct video_engine_rgb *frame,
    int64_t pts, int64_t duration)
{
    enum video_engine_status status = stream_active(stream);
    if (status != VIDEO_ENGINE_OK) {
        return status;
    }
    const struct span descriptor = {frame, sizeof(*frame)};
    status = valid_span(descriptor);
    if (status != VIDEO_ENGINE_OK) {
        return status;
    }
    if (overlaps(descriptor, (struct span){stream, sizeof(*stream)})) {
        return VIDEO_ENGINE_OVERLAP;
    }
    status = valid_rgb(frame, stream->width, stream->height);
    if (status != VIDEO_ENGINE_OK) {
        return status;
    }
    if (overlaps((struct span){frame->data, frame->size},
                 (struct span){stream, sizeof(*stream)})) {
        return VIDEO_ENGINE_OVERLAP;
    }
    if (pts < stream->next_pts || duration <= 0 || pts > INT64_MAX - duration) {
        return VIDEO_ENGINE_INVALID_ARGUMENT;
    }
    if (stream->pending) {
        return VIDEO_ENGINE_INVALID_STATE;
    }
    if (stream->info.frames_consumed == UINT64_MAX) {
        return stream_fault(stream, VIDEO_ENGINE_SIZE_OVERFLOW, 0, 0);
    }
    struct encoding *const encoding = &stream->encoding;
    int error = av_frame_make_writable(encoding->yuv);
    if (error < 0) {
        return stream_codec_fault(stream, error);
    }
    /* Padded workspace keeps swscale SIMD reads within owned memory. */
    for (size_t y = 0; y < stream->height; ++y) {
        memcpy(encoding->rgb->data[0] + y * (size_t)encoding->rgb->linesize[0],
               frame->data + y * frame->stride, stream->width * 3);
    }
    error = sws_scale(encoding->scaler,
        (const uint8_t *const *)encoding->rgb->data, encoding->rgb->linesize,
        0, (int)stream->height, encoding->yuv->data, encoding->yuv->linesize);
    if (error != (int)stream->height) {
        return stream_codec_fault(stream, error < 0 ? error : AVERROR_INVALIDDATA);
    }
    encoding->yuv->pts = pts;
    encoding->yuv->duration = duration;
    error = avcodec_send_frame(encoding->codec, encoding->yuv);
    if (error < 0) {
        return stream_codec_fault(stream, error);
    }
    ++stream->info.frames_consumed;
    stream->pending = 1;
    stream->pending_pts = pts;
    stream->pending_duration = duration;
    stream->next_pts = pts + duration;
    return receive_packets(stream, 0);
}

enum video_engine_status video_engine_stream_finish(struct video_engine_stream *stream)
{
    if (stream != NULL && !stream->in_callback &&
        stream->info.state == VIDEO_ENGINE_STREAM_FINISHED) {
        return VIDEO_ENGINE_OK;
    }
    enum video_engine_status status = stream_active(stream);
    if (status != VIDEO_ENGINE_OK) {
        return status;
    }
    const int error = avcodec_send_frame(stream->encoding.codec, NULL);
    if (error < 0) {
        return stream_codec_fault(stream, error);
    }
    status = receive_packets(stream, 1);
    if (status != VIDEO_ENGINE_OK) {
        return status;
    }
    if (stream->pending ||
        stream->info.frames_consumed != stream->info.packets_published) {
        return stream_codec_fault(stream, AVERROR_INVALIDDATA);
    }
    stream->info.state = VIDEO_ENGINE_STREAM_FINISHED;
    return VIDEO_ENGINE_OK;
}

enum video_engine_status video_engine_stream_cancel(struct video_engine_stream *stream)
{
    if (stream == NULL) {
        return VIDEO_ENGINE_INVALID_ARGUMENT;
    }
    if (stream->in_callback) {
        return VIDEO_ENGINE_INVALID_STATE;
    }
    encoding_free(&stream->encoding);
    stream->pending = 0;
    stream->info.state = VIDEO_ENGINE_STREAM_CANCELLED;
    return VIDEO_ENGINE_OK;
}

struct video_engine_stream_info video_engine_stream_snapshot(
    const struct video_engine_stream *stream)
{
    return stream == NULL ? (struct video_engine_stream_info){
        .status = VIDEO_ENGINE_INVALID_ARGUMENT} : stream->info;
}

struct clip {
    AVPacket *held[VIDEO_ENGINE_MAX_FRAMES];
    size_t count, bytes;
};

static int collect_packet(const struct video_engine_stream_packet *view, void *opaque)
{
    struct clip *const clip = opaque;
    if (clip->count >= VIDEO_ENGINE_MAX_FRAMES ||
        view->size > VIDEO_ENGINE_MAX_BYTES - clip->bytes) {
        return AVERROR(EOVERFLOW);
    }
    AVPacket *packet = av_packet_alloc();
    if (packet == NULL) {
        return AVERROR(ENOMEM);
    }
    const int error = av_new_packet(packet, (int)view->size);
    if (error < 0) {
        av_packet_free(&packet);
        return error;
    }
    memcpy(packet->data, view->data, view->size);
    packet->pts = view->pts;
    packet->dts = view->dts;
    packet->duration = view->duration;
    packet->flags = view->keyframe ? AV_PKT_FLAG_KEY : 0;
    clip->held[clip->count++] = packet;
    clip->bytes += view->size;
    return 0;
}

struct video_engine_result video_engine_encode_rgb888(
    const struct video_engine_rgb *frames, size_t count,
    size_t width, size_t height, unsigned fps,
    uint8_t *output, size_t output_capacity,
    struct video_engine_packet *packets, size_t packet_capacity,
    uint8_t *config, size_t config_capacity)
{
    struct video_engine_result result = {.status = VIDEO_ENGINE_INVALID_ARGUMENT};
    if (frames == NULL || count == 0 || count > VIDEO_ENGINE_MAX_FRAMES ||
        !valid_format(width, height, fps)) {
        return result;
    }
    if (packet_capacity > SIZE_MAX / sizeof(*packets)) {
        result.status = VIDEO_ENGINE_SIZE_OVERFLOW;
        return result;
    }
    const struct span inputs = {frames, count * sizeof(*frames)};
    const struct span outputs[] = {{output, output_capacity},
        {packets, packet_capacity * sizeof(*packets)}, {config, config_capacity}};
    result.status = valid_span(inputs);
    if (result.status != VIDEO_ENGINE_OK) {
        return result;
    }
    for (size_t i = 0; i < 3; ++i) {
        result.status = valid_span(outputs[i]);
        if (result.status != VIDEO_ENGINE_OK) {
            return result;
        }
        if (overlaps(outputs[i], inputs)) {
            result.status = VIDEO_ENGINE_OVERLAP;
            return result;
        }
        for (size_t j = 0; j < i; ++j) {
            if (overlaps(outputs[i], outputs[j])) {
                result.status = VIDEO_ENGINE_OVERLAP;
                return result;
            }
        }
    }
    for (size_t i = 0; i < count; ++i) {
        result.status = valid_rgb(&frames[i], width, height);
        if (result.status != VIDEO_ENGINE_OK) {
            return result;
        }
        for (size_t j = 0; j < 3; ++j) {
            if (overlaps(outputs[j],
                         (struct span){frames[i].data, frames[i].size})) {
                result.status = VIDEO_ENGINE_OVERLAP;
                return result;
            }
        }
    }

    struct clip clip = {0};
    struct video_engine_stream stream = {0};
    result.status = video_engine_stream_begin(&stream, width, height, fps,
        VIDEO_ENGINE_MAX_BYTES, collect_packet, &clip);
    if (result.status != VIDEO_ENGINE_OK) {
        goto done;
    }
    for (size_t i = 0; i < count; ++i) {
        result.status = video_engine_stream_feed_rgb888(&stream, &frames[i],
                                                       (int64_t)i, 1);
        if (result.status != VIDEO_ENGINE_OK) {
            goto done;
        }
    }
    result.status = video_engine_stream_finish(&stream);
    if (result.status != VIDEO_ENGINE_OK) {
        goto done;
    }
    const AVCodecContext *const codec = stream.encoding.codec;
    if (clip.count != count || codec->extradata_size <= 0 || codec->extradata == NULL) {
        stream_codec_fault(&stream, AVERROR_INVALIDDATA);
        goto done;
    }
    result.required = clip.bytes;
    result.packets_required = clip.count;
    result.config_required = (size_t)codec->extradata_size;
    if (output_capacity < result.required || packet_capacity < clip.count ||
        config_capacity < result.config_required) {
        result.status = VIDEO_ENGINE_OUTPUT_TOO_SMALL;
        goto done;
    }
    size_t offset = 0;
    for (size_t i = 0; i < clip.count; ++i) {
        const AVPacket *const packet = clip.held[i];
        packets[i] = (struct video_engine_packet){offset, (size_t)packet->size,
            packet->pts, packet->dts, packet->duration,
            (packet->flags & AV_PKT_FLAG_KEY) != 0};
        memcpy(output + offset, packet->data, (size_t)packet->size);
        offset += (size_t)packet->size;
    }
    memcpy(config, codec->extradata, result.config_required);
    result.status = VIDEO_ENGINE_OK;
    result.used = result.required;
    result.packet_count = result.packets_required;
    result.config_used = result.config_required;

done:
    result.frames_consumed = (size_t)stream.info.frames_consumed;
    result.packets_flushed = (size_t)stream.info.packets_flushed;
    if (stream.info.state == VIDEO_ENGINE_STREAM_FAULT) {
        if (stream.info.codec_error != 0 || stream.info.sink_error != 0) {
            codec_failure(&result, stream.info.codec_error != 0 ?
                          stream.info.codec_error : stream.info.sink_error);
        } else {
            result.status = stream.info.status;
        }
    }
    encoding_free(&stream.encoding);
    for (size_t i = 0; i < clip.count; ++i) {
        av_packet_free(&clip.held[i]);
    }
    return result;
}

struct memory_io {
    uint8_t *output;
    size_t capacity;
    size_t position;
    size_t used;
};

static int memory_write(void *opaque, const uint8_t *bytes, int size)
{
    struct memory_io *const io = opaque;
    if (size < 0 || (size_t)size > VIDEO_ENGINE_MAX_BYTES - io->position) {
        return AVERROR(EOVERFLOW);
    }
    const size_t end = io->position + (size_t)size;
    if (io->output != NULL) {
        if (end > io->capacity) {
            return AVERROR(ENOSPC);
        }
        if (io->position > io->used) {
            memset(io->output + io->used, 0, io->position - io->used);
        }
        memcpy(io->output + io->position, bytes, (size_t)size);
    }
    io->position = end;
    if (end > io->used) {
        io->used = end;
    }
    return size;
}

static int64_t memory_seek(void *opaque, int64_t offset, int whence)
{
    struct memory_io *const io = opaque;
    if (whence == AVSEEK_SIZE) {
        return (int64_t)io->used;
    }
    whence &= ~AVSEEK_FORCE;
    int64_t base;
    switch (whence) {
    case SEEK_SET: base = 0; break;
    case SEEK_CUR: base = (int64_t)io->position; break;
    case SEEK_END: base = (int64_t)io->used; break;
    default: return AVERROR(EINVAL);
    }
    if (offset < -base || offset > (int64_t)VIDEO_ENGINE_MAX_BYTES - base) {
        return AVERROR(EOVERFLOW);
    }
    io->position = (size_t)(base + offset);
    return (int64_t)io->position;
}

static int mux_pass(const uint8_t *data,
    const struct video_engine_packet *packets, size_t packet_count,
    const uint8_t *config, size_t config_size,
    size_t width, size_t height, unsigned fps, struct memory_io *io)
{
    AVFormatContext *format = NULL;
    AVIOContext *avio = NULL;
    AVPacket *packet = NULL;
    int error = avformat_alloc_output_context2(&format, NULL, "mp4", NULL);
    if (error < 0) {
        return error;
    }
    uint8_t *const buffer = av_malloc(4096);
    if (buffer == NULL) {
        error = AVERROR(ENOMEM);
        goto done;
    }
    avio = avio_alloc_context(buffer, 4096, 1, io, NULL,
                              memory_write, memory_seek);
    if (avio == NULL) {
        av_free(buffer);
        error = AVERROR(ENOMEM);
        goto done;
    }
    format->pb = avio;
    format->flags |= AVFMT_FLAG_CUSTOM_IO;
    AVStream *const stream = avformat_new_stream(format, NULL);
    packet = av_packet_alloc();
    if (stream == NULL || packet == NULL) {
        error = AVERROR(ENOMEM);
        goto done;
    }
    stream->time_base = (AVRational){1, (int)fps};
    stream->avg_frame_rate = (AVRational){(int)fps, 1};
    AVCodecParameters *const parameters = stream->codecpar;
    parameters->codec_type = AVMEDIA_TYPE_VIDEO;
    parameters->codec_id = AV_CODEC_ID_H264;
    parameters->profile = AV_PROFILE_H264_CONSTRAINED_BASELINE;
    parameters->width = (int)width;
    parameters->height = (int)height;
    parameters->format = AV_PIX_FMT_YUV420P;
    parameters->color_range = AVCOL_RANGE_MPEG;
    parameters->color_space = AVCOL_SPC_BT709;
    parameters->color_primaries = AVCOL_PRI_BT709;
    parameters->color_trc = AVCOL_TRC_BT709;
    parameters->extradata = av_mallocz(config_size + AV_INPUT_BUFFER_PADDING_SIZE);
    if (parameters->extradata == NULL) {
        error = AVERROR(ENOMEM);
        goto done;
    }
    memcpy(parameters->extradata, config, config_size);
    parameters->extradata_size = (int)config_size;
    error = avformat_write_header(format, NULL);
    if (error < 0) {
        goto done;
    }
    for (size_t i = 0; i < packet_count; ++i) {
        error = av_new_packet(packet, (int)packets[i].size);
        if (error < 0) {
            goto done;
        }
        memcpy(packet->data, data + packets[i].offset, packets[i].size);
        packet->pts = packets[i].pts;
        packet->dts = packets[i].dts;
        packet->duration = packets[i].duration;
        packet->stream_index = stream->index;
        packet->flags = packets[i].keyframe ? AV_PKT_FLAG_KEY : 0;
        av_packet_rescale_ts(packet, (AVRational){1, (int)fps}, stream->time_base);
        error = av_write_frame(format, packet);
        av_packet_unref(packet);
        if (error < 0) {
            goto done;
        }
    }
    error = av_write_trailer(format);
    avio_flush(avio);
    if (error >= 0 && avio->error < 0) {
        error = avio->error;
    }

done:
    av_packet_free(&packet);
    if (format != NULL) {
        format->pb = NULL;
    }
    avformat_free_context(format);
    if (avio != NULL) {
        av_freep(&avio->buffer);
        avio_context_free(&avio);
    }
    return error;
}

static size_t start_code(const uint8_t *data, size_t size)
{
    if (size >= 3 && data[0] == 0 && data[1] == 0 && data[2] == 1) {
        return 3;
    }
    if (size >= 4 && data[0] == 0 && data[1] == 0 &&
        data[2] == 0 && data[3] == 1) {
        return 4;
    }
    return 0;
}

static int annexb_start(const uint8_t *data, size_t size)
{
    const size_t prefix = start_code(data, size);
    return prefix != 0 && prefix < size && (data[prefix] & 0x80) == 0;
}

static int has_parameter_sets(const uint8_t *data, size_t size)
{
    unsigned seen = 0;
    size_t position = 0;
    while (position < size) {
        const size_t prefix = start_code(data + position, size - position);
        if (prefix == 0 || prefix == size - position) {
            return 0;
        }
        position += prefix;
        const size_t begin = position;
        while (position < size && start_code(data + position, size - position) == 0) {
            ++position;
        }
        if ((data[begin] & 0x80) != 0) {
            return 0;
        }
        const unsigned type = data[begin] & 31u;
        if (type == 7) {
            if (position - begin < 4) {
                return 0;
            }
            seen |= 1u;
        } else if (type == 8) {
            if (position - begin < 2) {
                return 0;
            }
            seen |= 2u;
        }
    }
    return seen == 3u;
}

struct video_engine_result video_engine_mux_mp4(
    const uint8_t *data, size_t data_size,
    const struct video_engine_packet *packets, size_t packet_count,
    const uint8_t *config, size_t config_size,
    size_t width, size_t height, unsigned fps,
    uint8_t *output, size_t output_capacity)
{
    struct video_engine_result result = {.status = VIDEO_ENGINE_INVALID_ARGUMENT};
    if (data == NULL || packets == NULL || config == NULL || data_size == 0 ||
        data_size > VIDEO_ENGINE_MAX_BYTES || config_size < 5 ||
        config_size > 1024u * 1024u || packet_count == 0 ||
        packet_count > VIDEO_ENGINE_MAX_FRAMES || !valid_format(width, height, fps)) {
        return result;
    }
    const struct span inputs[] = {{data, data_size},
        {packets, packet_count * sizeof(*packets)}, {config, config_size}};
    const struct span destination = {output, output_capacity};
    result.status = valid_span(destination);
    if (result.status != VIDEO_ENGINE_OK) {
        return result;
    }
    for (size_t i = 0; i < 3; ++i) {
        result.status = valid_span(inputs[i]);
        if (result.status != VIDEO_ENGINE_OK) {
            return result;
        }
        if (overlaps(inputs[i], destination)) {
            result.status = VIDEO_ENGINE_OVERLAP;
            return result;
        }
    }
    result.status = VIDEO_ENGINE_INVALID_ARGUMENT;
    if (!has_parameter_sets(config, config_size) || packets[0].keyframe != 1) {
        return result;
    }
    size_t offset = 0;
    for (size_t i = 0; i < packet_count; ++i) {
        if (packets[i].offset != offset || packets[i].size == 0 ||
            packets[i].size > data_size - offset ||
            packets[i].pts != (int64_t)i || packets[i].dts != (int64_t)i ||
            packets[i].duration != 1 ||
            (packets[i].keyframe != 0 && packets[i].keyframe != 1) ||
            !annexb_start(data + offset, packets[i].size)) {
            return result;
        }
        offset += packets[i].size;
    }
    if (offset != data_size) {
        return result;
    }
    struct memory_io counting = {0};
    int error = mux_pass(data, packets, packet_count, config, config_size,
                         width, height, fps, &counting);
    if (error < 0) {
        codec_failure(&result, error);
        return result;
    }
    result.required = counting.used;
    result.packets_required = packet_count;
    if (output_capacity < counting.used) {
        result.status = VIDEO_ENGINE_OUTPUT_TOO_SMALL;
        return result;
    }
    struct memory_io writing = {.output = output, .capacity = output_capacity};
    error = mux_pass(data, packets, packet_count, config, config_size,
                     width, height, fps, &writing);
    if (error < 0 || writing.used != counting.used) {
        codec_failure(&result, error < 0 ? error : AVERROR_INVALIDDATA);
        return result;
    }
    result.status = VIDEO_ENGINE_OK;
    result.used = writing.used;
    result.packet_count = packet_count;
    return result;
}
