/* SPDX-License-Identifier: MIT */
/* Host-only streaming H.264/MP4 virtual camera recorder backed by report/virtual-video-engine.
 * Encodes live 640x480 RGB24 frames in memory and produces a complete MP4 container without temp files.
 */
#include "../../report/virtual-video-engine/video-engine.h"

#include <errno.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>

#include <libavcodec/avcodec.h>
#include <libavformat/avformat.h>
#include <libavutil/log.h>
#include <libavutil/mem.h>

#define VVH_MAX_MP4_BYTES (64u * 1024u * 1024u)

struct vvh_pkt {
    size_t offset;
    size_t size;
    int64_t pts;
    int64_t dts;
    int64_t duration;
    int keyframe;
};

struct vvh_mem_io {
    uint8_t *buf;
    size_t cap;
    size_t pos;
    size_t used;
    int oom;
};

struct vvh_recorder {
    struct video_engine_stream *stream;
    uint32_t width;
    uint32_t height;
    uint32_t fps;
    uint8_t *es_buf;
    size_t es_len;
    size_t es_cap;
    struct vvh_pkt *pkts;
    size_t pkt_count;
    size_t pkt_cap;
    uint8_t *mp4_buf;
    size_t mp4_len;
    uint64_t mp4_fnv1a64;
    size_t frames_fed;
    int finished;
    int failed;
};

static uint64_t vvh_fnv1a64(const uint8_t *p, size_t n) {
    uint64_t h = UINT64_C(0xcbf29ce484222325);
    for (size_t i = 0; i < n; ++i) {
        h ^= (uint64_t)p[i];
        h *= UINT64_C(0x100000001b3);
    }
    return h;
}

static size_t vvh_start_code(const uint8_t *data, size_t size) {
    if (size >= 3u && data[0] == 0u && data[1] == 0u && data[2] == 1u) return 3u;
    if (size >= 4u && data[0] == 0u && data[1] == 0u && data[2] == 0u && data[3] == 1u) return 4u;
    return 0u;
}

static int vvh_collect_packet(const struct video_engine_stream_packet *pkt, void *opaque) {
    struct vvh_recorder *const r = opaque;
    if (!r || !pkt || !pkt->data || pkt->size == 0u) return -EINVAL;
    if (pkt->size > VVH_MAX_MP4_BYTES - r->es_len) return -EFBIG;
    if (r->pkt_count == r->pkt_cap) {
        size_t next = r->pkt_cap ? r->pkt_cap * 2u : 256u;
        struct vvh_pkt *np = realloc(r->pkts, next * sizeof(*np));
        if (!np) return -ENOMEM;
        r->pkts = np;
        r->pkt_cap = next;
    }
    if (r->es_len + pkt->size > r->es_cap) {
        size_t next = r->es_cap ? r->es_cap : (256u * 1024u);
        while (next < r->es_len + pkt->size) {
            if (next > VVH_MAX_MP4_BYTES / 2u) {
                next = VVH_MAX_MP4_BYTES;
                break;
            }
            next *= 2u;
        }
        if (next < r->es_len + pkt->size) return -EFBIG;
        uint8_t *nb = realloc(r->es_buf, next);
        if (!nb) return -ENOMEM;
        r->es_buf = nb;
        r->es_cap = next;
    }
    size_t off = r->es_len;
    memcpy(r->es_buf + off, pkt->data, pkt->size);
    r->es_len += pkt->size;
    r->pkts[r->pkt_count++] = (struct vvh_pkt){
        .offset = off,
        .size = pkt->size,
        .pts = pkt->pts,
        .dts = pkt->dts,
        .duration = pkt->duration,
        .keyframe = pkt->keyframe ? 1 : 0,
    };
    return 0;
}

static int vvh_extract_extradata(const uint8_t *au, size_t au_size,
                                 uint8_t **out_buf, size_t *out_size) {
    uint8_t *extra = NULL;
    size_t extra_len = 0u;
    unsigned seen = 0u;
    size_t pos = 0u;
    while (pos < au_size) {
        size_t sc = vvh_start_code(au + pos, au_size - pos);
        if (sc == 0u || pos + sc >= au_size) break;
        size_t nal_hdr = pos + sc;
        size_t end = nal_hdr + 1u;
        while (end < au_size && vvh_start_code(au + end, au_size - end) == 0u) ++end;
        unsigned nalu_type = au[nal_hdr] & 0x1fu;
        if (nalu_type == 7u || nalu_type == 8u) {
            size_t body = end - nal_hdr;
            uint8_t *nb = realloc(extra, extra_len + 4u + body);
            if (!nb) {
                free(extra);
                return -ENOMEM;
            }
            extra = nb;
            extra[extra_len + 0u] = 0u;
            extra[extra_len + 1u] = 0u;
            extra[extra_len + 2u] = 0u;
            extra[extra_len + 3u] = 1u;
            memcpy(extra + extra_len + 4u, au + nal_hdr, body);
            extra_len += 4u + body;
            seen |= (nalu_type == 7u) ? 1u : 2u;
        }
        pos = end;
    }
    if (seen != 3u) {
        free(extra);
        return -EINVAL;
    }
    *out_buf = extra;
    *out_size = extra_len;
    return 0;
}

static int vvh_mem_write(void *opaque, const uint8_t *bytes, int size) {
    struct vvh_mem_io *const io = opaque;
    if (size < 0 || (size_t)size > VVH_MAX_MP4_BYTES - io->pos) {
        io->oom = 1;
        return AVERROR(EOVERFLOW);
    }
    size_t end = io->pos + (size_t)size;
    if (end > io->cap) {
        size_t next = io->cap ? io->cap : (64u * 1024u);
        while (next < end) {
            if (next >= VVH_MAX_MP4_BYTES / 2u) {
                next = VVH_MAX_MP4_BYTES;
                break;
            }
            next *= 2u;
        }
        if (next < end) {
            io->oom = 1;
            return AVERROR(ENOSPC);
        }
        uint8_t *nb = realloc(io->buf, next);
        if (!nb) {
            io->oom = 1;
            return AVERROR(ENOMEM);
        }
        io->buf = nb;
        io->cap = next;
    }
    if (io->pos > io->used) memset(io->buf + io->used, 0, io->pos - io->used);
    if (size > 0) memcpy(io->buf + io->pos, bytes, (size_t)size);
    io->pos = end;
    if (end > io->used) io->used = end;
    return size;
}

static int64_t vvh_mem_seek(void *opaque, int64_t offset, int whence) {
    struct vvh_mem_io *const io = opaque;
    if (whence == AVSEEK_SIZE) return (int64_t)io->used;
    whence &= ~AVSEEK_FORCE;
    int64_t base;
    switch (whence) {
    case SEEK_SET: base = 0; break;
    case SEEK_CUR: base = (int64_t)io->pos; break;
    case SEEK_END: base = (int64_t)io->used; break;
    default: return AVERROR(EINVAL);
    }
    if (offset < -base || offset > (int64_t)VVH_MAX_MP4_BYTES - base) return AVERROR(EOVERFLOW);
    io->pos = (size_t)(base + offset);
    return (int64_t)io->pos;
}

static int vvh_mux_mp4_dynamic(const struct vvh_recorder *r,
                               const uint8_t *extradata, size_t extradata_size,
                               uint8_t **mp4_out, size_t *mp4_len_out) {
    AVFormatContext *fmt = NULL;
    AVIOContext *avio = NULL;
    AVPacket *pkt = NULL;
    struct vvh_mem_io io = {0};
    int err = avformat_alloc_output_context2(&fmt, NULL, "mp4", NULL);
    if (err < 0) return err;

    uint8_t *avio_buf = av_malloc(8192u);
    if (!avio_buf) {
        avformat_free_context(fmt);
        return AVERROR(ENOMEM);
    }
    avio = avio_alloc_context(avio_buf, 8192, 1, &io, NULL, vvh_mem_write, vvh_mem_seek);
    if (!avio) {
        av_free(avio_buf);
        avformat_free_context(fmt);
        return AVERROR(ENOMEM);
    }
    fmt->pb = avio;
    fmt->flags |= AVFMT_FLAG_CUSTOM_IO;

    AVStream *st = avformat_new_stream(fmt, NULL);
    pkt = av_packet_alloc();
    if (!st || !pkt) {
        err = AVERROR(ENOMEM);
        goto done;
    }
    st->time_base = (AVRational){1, (int)r->fps};
    st->avg_frame_rate = (AVRational){(int)r->fps, 1};

    AVCodecParameters *par = st->codecpar;
    par->codec_type = AVMEDIA_TYPE_VIDEO;
    par->codec_id = AV_CODEC_ID_H264;
    par->profile = AV_PROFILE_H264_CONSTRAINED_BASELINE;
    par->width = (int)r->width;
    par->height = (int)r->height;
    par->format = AV_PIX_FMT_YUV420P;
    par->color_range = AVCOL_RANGE_MPEG;
    par->color_space = AVCOL_SPC_BT709;
    par->color_primaries = AVCOL_PRI_BT709;
    par->color_trc = AVCOL_TRC_BT709;
    par->extradata = av_mallocz(extradata_size + AV_INPUT_BUFFER_PADDING_SIZE);
    if (!par->extradata) {
        err = AVERROR(ENOMEM);
        goto done;
    }
    memcpy(par->extradata, extradata, extradata_size);
    par->extradata_size = (int)extradata_size;

    err = avformat_write_header(fmt, NULL);
    if (err < 0) goto done;

    for (size_t i = 0; i < r->pkt_count; ++i) {
        const struct vvh_pkt *src = &r->pkts[i];
        err = av_new_packet(pkt, (int)src->size);
        if (err < 0) goto done;
        memcpy(pkt->data, r->es_buf + src->offset, src->size);
        pkt->pts = src->pts;
        pkt->dts = src->dts;
        pkt->duration = src->duration;
        pkt->stream_index = st->index;
        pkt->flags = src->keyframe ? AV_PKT_FLAG_KEY : 0;
        av_packet_rescale_ts(pkt, (AVRational){1, (int)r->fps}, st->time_base);
        err = av_write_frame(fmt, pkt);
        av_packet_unref(pkt);
        if (err < 0) goto done;
    }
    err = av_write_trailer(fmt);
    avio_flush(avio);
    if (err >= 0 && (avio->error < 0 || io.oom)) {
        err = avio->error < 0 ? avio->error : AVERROR(ENOMEM);
    }

done:
    av_packet_free(&pkt);
    if (fmt) fmt->pb = NULL;
    avformat_free_context(fmt);
    if (avio) {
        av_freep(&avio->buffer);
        avio_context_free(&avio);
    }
    if (err < 0) {
        free(io.buf);
        return err;
    }
    *mp4_out = io.buf;
    *mp4_len_out = io.used;
    return 0;
}

struct vvh_recorder *vvh_recorder_create(uint32_t width, uint32_t height, uint32_t fps) {
    av_log_set_level(AV_LOG_ERROR);
    struct vvh_recorder *r = calloc(1, sizeof(*r));
    if (!r) return NULL;
    r->stream = video_engine_stream_create();
    if (!r->stream) {
        free(r);
        return NULL;
    }
    r->width = width;
    r->height = height;
    r->fps = fps;
    enum video_engine_status st = video_engine_stream_begin(
        r->stream, width, height, fps, 16u * 1024u * 1024u, vvh_collect_packet, r);
    if (st != VIDEO_ENGINE_OK) {
        video_engine_stream_destroy(r->stream);
        free(r);
        return NULL;
    }
    return r;
}

int vvh_recorder_feed_rgb24(struct vvh_recorder *rec, const uint8_t *rgb24,
                              size_t size, int64_t pts, int64_t duration) {
    if (!rec || !rgb24 || rec->finished || rec->failed) return -EINVAL;
    if (size < (size_t)rec->width * rec->height * 3u) return -EINVAL;
    const struct video_engine_rgb frame = {rgb24, size, (size_t)rec->width * 3u};
    enum video_engine_status st =
        (pts == 0) ? video_engine_stream_feed_idr_rgb888(rec->stream, &frame, pts, duration)
                   : video_engine_stream_feed_rgb888(rec->stream, &frame, pts, duration);
    if (st != VIDEO_ENGINE_OK) {
        rec->failed = 1;
        return -EIO;
    }
    ++rec->frames_fed;
    return 0;
}

size_t vvh_recorder_frame_count(const struct vvh_recorder *rec) {
    return rec ? rec->frames_fed : 0u;
}

int vvh_recorder_finish_mp4(struct vvh_recorder *rec, const uint8_t **mp4_out,
                            size_t *mp4_len_out, uint64_t *fnv_out) {
    if (!rec || !mp4_out || !mp4_len_out) return -EINVAL;
    if (rec->failed) return -EIO;
    if (!rec->finished) {
        enum video_engine_status st = video_engine_stream_finish(rec->stream);
        if (st != VIDEO_ENGINE_OK || rec->pkt_count == 0u) {
            rec->failed = 1;
            return rec->pkt_count == 0u ? -ENODATA : -EIO;
        }
        uint8_t *extra = NULL;
        size_t extra_len = 0u;
        int rc = vvh_extract_extradata(rec->es_buf + rec->pkts[0].offset,
                                       rec->pkts[0].size, &extra, &extra_len);
        if (rc != 0) {
            rec->failed = 1;
            return rc;
        }
        uint8_t *mp4 = NULL;
        size_t mp4_len = 0u;
        rc = vvh_mux_mp4_dynamic(rec, extra, extra_len, &mp4, &mp4_len);
        free(extra);
        if (rc != 0) {
            rec->failed = 1;
            return rc;
        }
        rec->mp4_buf = mp4;
        rec->mp4_len = mp4_len;
        rec->mp4_fnv1a64 = vvh_fnv1a64(mp4, mp4_len);
        rec->finished = 1;
    }
    *mp4_out = rec->mp4_buf;
    *mp4_len_out = rec->mp4_len;
    if (fnv_out) *fnv_out = rec->mp4_fnv1a64;
    return 0;
}

void vvh_recorder_destroy(struct vvh_recorder *rec) {
    if (!rec) return;
    if (rec->stream) video_engine_stream_destroy(rec->stream);
    free(rec->es_buf);
    free(rec->pkts);
    free(rec->mp4_buf);
    free(rec);
}
