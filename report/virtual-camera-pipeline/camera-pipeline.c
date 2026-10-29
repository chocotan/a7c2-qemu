/* SPDX-License-Identifier: MIT */
#include "camera-pipeline.h"

#include <errno.h>
#include <stdlib.h>
#include <string.h>

#define SOURCE_ADDRESS UINT64_C(0x100000000)
#define OUTPUT_ADDRESS UINT64_C(0x200000000)
#define SINK_BYTES (-1001)
#define SINK_INDEX (-1002)
#define SINK_CONFIG (-1003)
#define SINK_VERIFY (-1004)

struct span { const void *data; size_t size; };
struct vcam_pipeline {
    struct vcam_info info;
    struct vcam_frame_proof proof;
    optical_frame_owner owner;
    optical_frame_lease lease;
    uint8_t *pool;
    size_t pool_capacity;
    struct vjpeg_hw *jpeg;
    struct video_engine_stream *video;
    struct vcam_callbacks callbacks;
    const optical_frame_view *borrowed;
    uint8_t prefix[VJPEG_PREFIX_SIZE];
    uint8_t *jpeg_output;
    size_t jpeg_capacity;
    uint32_t read_crc;
    struct vcam_record_buffers buffers;
    size_t record_width, record_height;
    unsigned fps;
    uint32_t data_crc, config_crc;
    int video_frame, cancel_requested, jpeg_released;
    enum vjpeg_result jpeg_result;
    enum video_engine_status video_result;
};

static int valid_span(struct span s)
{
    return (!s.size || s.data) && s.size <= UINTPTR_MAX - (uintptr_t)s.data;
}
static int overlaps(struct span a, struct span b)
{
    return a.size && b.size && (uintptr_t)a.data < (uintptr_t)b.data + b.size &&
           (uintptr_t)b.data < (uintptr_t)a.data + a.size;
}
static uint32_t crc_update(uint32_t crc, const uint8_t *data, size_t size)
{
    for (size_t i = 0; i < size; ++i) {
        crc ^= data[i];
        for (unsigned bit = 0; bit < 8; ++bit)
            crc = (crc >> 1) ^ (UINT32_C(0xedb88320) & (0u - (crc & 1u)));
    }
    return crc;
}
static uint32_t crc32(const uint8_t *data, size_t size)
{
    return ~crc_update(UINT32_MAX, data, size);
}
static uint64_t fnv_update(uint64_t hash, const uint8_t *data, size_t size)
{
    for (size_t i = 0; i < size; ++i)
        hash = (hash ^ data[i]) * UINT64_C(1099511628211);
    return hash;
}
static uint64_t active_hash(const uint8_t *pixels, size_t width, size_t height, size_t stride)
{
    uint64_t hash = UINT64_C(14695981039346656037);
    for (size_t y = 0; y < height; ++y)
        hash = fnv_update(hash, pixels + y * stride, width * 3u);
    return hash;
}
static enum vcam_status status(struct vcam_pipeline *p, enum vcam_status s)
{
    if (p->info.state == VCAM_FAULT && (s == VCAM_STATE || s == VCAM_BUSY)) return s;
    p->info.status = s;
    if (s != VCAM_OK && s != VCAM_CANCELLED) p->info.last_failure = s;
    return s;
}
static enum vcam_status independent(const struct vcam_pipeline *p,
                                    const struct span *spans, size_t count)
{
    const struct span private_spans[] = {{p, sizeof(*p)}, {p->pool, p->pool_capacity}};
    const struct span active[] = {{p->buffers.data, p->buffers.data_capacity},
        {p->buffers.packets, p->buffers.packet_capacity * sizeof(*p->buffers.packets)},
        {p->buffers.config, p->buffers.config_capacity}};
    for (size_t i = 0; i < count; ++i) {
        if (!valid_span(spans[i])) return VCAM_INVALID;
        for (size_t j = 0; j < 2; ++j)
            if (overlaps(spans[i], private_spans[j])) return VCAM_OVERLAP;
        for (size_t j = 0; j < i; ++j)
            if (overlaps(spans[i], spans[j])) return VCAM_OVERLAP;
        if (p->info.state != VCAM_IDLE)
            for (size_t j = 0; j < 3; ++j)
                if (overlaps(spans[i], active[j])) return VCAM_OVERLAP;
    }
    return VCAM_OK;
}
static int source_range(const struct vcam_pipeline *p, uint64_t address, size_t size)
{
    return p->borrowed && address >= SOURCE_ADDRESS &&
        address - SOURCE_ADDRESS <= p->borrowed->size &&
        size <= p->borrowed->size - (size_t)(address - SOURCE_ADDRESS);
}
static int output_range(const struct vcam_pipeline *p, uint64_t address, size_t size)
{
    return p->jpeg_output && address >= OUTPUT_ADDRESS &&
        address - OUTPUT_ADDRESS <= p->jpeg_capacity - VJPEG_PREFIX_SIZE &&
        size <= p->jpeg_capacity - VJPEG_PREFIX_SIZE - (size_t)(address - OUTPUT_ADDRESS);
}
static int jpeg_probe(void *opaque, uint64_t address, size_t size, unsigned access,
                       struct vjpeg_mapping *mapping)
{
    struct vcam_pipeline *p = opaque;
    if (!size || !mapping) return -1;
    if (access == VJPEG_READ && source_range(p, address, size)) {
        *mapping = (struct vjpeg_mapping){1, address - SOURCE_ADDRESS};
        return 0;
    }
    if (access == (VJPEG_READ | VJPEG_WRITE) && output_range(p, address, size)) {
        /* IDs name exactly the disjoint pool/output allocations. No aliases or
         * alternate mappings are exposed by this component address space. */
        *mapping = (struct vjpeg_mapping){2, VJPEG_PREFIX_SIZE + address - OUTPUT_ADDRESS};
        return 0;
    }
    return -1;
}
static int jpeg_read(void *opaque, uint64_t address, void *destination, size_t size)
{
    struct vcam_pipeline *p = opaque;
    if (!destination || !size) return -1;
    if (source_range(p, address, size)) {
        memcpy(destination, p->borrowed->pixels + (size_t)(address - SOURCE_ADDRESS), size);
        return 0;
    }
    if (!output_range(p, address, size) || address - OUTPUT_ADDRESS != p->info.jpeg_readback ||
        size > p->info.jpeg_written - p->info.jpeg_readback ||
        memcmp(p->prefix, p->jpeg_output, VJPEG_PREFIX_SIZE)) return -1;
    const uint8_t *bytes = p->jpeg_output + VJPEG_PREFIX_SIZE + p->info.jpeg_readback;
    memcpy(destination, bytes, size);
    p->read_crc = crc_update(p->read_crc, destination, size);
    p->info.jpeg_readback += size;
    if (p->info.jpeg_readback == p->info.jpeg_written) {
        p->info.jpeg_readback_crc32 = ~p->read_crc;
    }
    return 0;
}
static int jpeg_write(void *opaque, uint64_t address, const void *source, size_t size)
{
    struct vcam_pipeline *p = opaque;
    if (!source || !size || address != OUTPUT_ADDRESS || !output_range(p, address, size) ||
        p->info.jpeg_written) return -1;
    p->proof.encoded_bytes = size;
    p->proof.encoded_fnv1a64 = fnv_update(UINT64_C(14695981039346656037), source, size);
    memcpy(p->jpeg_output + VJPEG_PREFIX_SIZE, source, size);
    p->info.jpeg_written = size;
    ++p->info.counts.encoded;
    return 0;
}
static int jpeg_acquire(void *opaque, uint64_t address, size_t size,
                         struct vjpeg_frame *frame)
{
    struct vcam_pipeline *p = opaque;
    optical_frame_info optical;
    if (!frame || !p->info.lease_live || !p->borrowed || address != SOURCE_ADDRESS ||
        p->borrowed->format != OPTICAL_FRAME_VIRTUAL_RGB888 || p->borrowed->pixels != p->pool ||
        size != p->borrowed->size || size > p->pool_capacity || p->lease.owner != &p->owner ||
        p->lease.buffer != p->pool || p->lease.capacity != p->pool_capacity ||
        optical_frame_snapshot(&p->owner, &optical) != OPTICAL_FRAME_OK ||
        optical.state != OPTICAL_FRAME_READING || p->lease.generation != optical.generation ||
        p->borrowed->generation != p->lease.generation) return -1;
    p->proof.consumer_entered = 1;
    p->proof.consumer_before_state = optical.state;
    p->proof.consumer_before_fnv1a64 = active_hash(p->borrowed->pixels,
        p->borrowed->width, p->borrowed->height, p->borrowed->stride);
    *frame = (struct vjpeg_frame){VJPEG_RGB888, p->borrowed->pixels, size,
        p->borrowed->width, p->borrowed->height, p->borrowed->stride, &p->lease};
    return 0;
}
static void jpeg_release(void *opaque, void *lease, int consumed)
{
    struct vcam_pipeline *p = opaque;
    if (lease != &p->lease || !p->borrowed || p->info.jpeg_release_pending ||
        p->lease.owner != &p->owner || p->lease.buffer != p->pool ||
        p->lease.capacity != p->pool_capacity || p->lease.generation != p->borrowed->generation) {
        p->info.optical_status = OPTICAL_FRAME_STALE;
        return;
    }
    if (consumed) ++p->info.counts.encoder_consumed;
    p->proof.encoder_consumed = consumed != 0;
    /* Core release occurs inside optical_frame_consumer_read: retiring here
     * would invalidate its borrowed pixels/state. The outer owner retires. */
    p->info.jpeg_release_pending = 1;
    p->jpeg_released = 1;
}
static void jpeg_irq(void *opaque, unsigned external_input, int level)
{
    struct vcam_pipeline *p = opaque;
    if (level) {
        ++p->info.irq_assertions;
        ++p->info.counts.output_readback;
    }
    if (p->callbacks.jpeg_irq)
        p->callbacks.jpeg_irq(p->callbacks.context, external_input, level);
}

struct vcam_pipeline *vcam_create(uint8_t *pool, size_t capacity,
                                   const struct vcam_callbacks *callbacks)
{
    if (!capacity || !valid_span((struct span){pool, capacity})) return NULL;
    if (callbacks && (!valid_span((struct span){callbacks, sizeof(*callbacks)}) ||
        overlaps((struct span){callbacks, sizeof(*callbacks)}, (struct span){pool, capacity})))
        return NULL;
    struct vcam_pipeline *p = calloc(1, sizeof(*p));
    if (!p) return NULL;
    p->pool = pool;
    p->pool_capacity = capacity;
    if (callbacks) p->callbacks = *callbacks;
    const struct vjpeg_callbacks cb = {jpeg_probe, jpeg_read, jpeg_write,
                                      jpeg_acquire, jpeg_release, jpeg_irq};
    p->jpeg = vjpeg_hw_create(&cb, p);
    p->video = video_engine_stream_create();
    if (!p->jpeg || !p->video || optical_frame_init(&p->owner) != OPTICAL_FRAME_OK) {
        vjpeg_hw_destroy(p->jpeg);
        video_engine_stream_destroy(p->video);
        free(p);
        return NULL;
    }
    return p;
}
enum vcam_status vcam_destroy(struct vcam_pipeline *p)
{
    if (!p) return VCAM_OK;
    if (p->info.busy || p->info.lease_live) return VCAM_BUSY;
    p->info.busy = 1;
    vjpeg_hw_destroy(p->jpeg);
    video_engine_stream_destroy(p->video);
    free(p);
    return VCAM_OK;
}
struct vcam_info vcam_snapshot(const struct vcam_pipeline *p)
{
    if (!p) {
        struct vcam_info result = {.status = VCAM_INVALID, .last_failure = VCAM_INVALID};
        return result;
    }
    struct vcam_info result = p->info;
    (void)optical_frame_snapshot(&p->owner, &result.optical);
    result.jpeg = vjpeg_hw_snapshot(p->jpeg);
    result.video = video_engine_stream_snapshot(p->video);
    result.counts.rendered = result.optical.counts.rendered;
    result.counts.source_read = result.optical.counts.read;
    result.counts.retired = result.optical.counts.retired;
    return result;
}
struct vcam_frame_proof vcam_frame_proof_snapshot(const struct vcam_pipeline *p)
{
    return p ? p->proof : (struct vcam_frame_proof){0};
}
enum vcam_status vcam_configure(struct vcam_pipeline *p, const optical_frame_config *config)
{
    if (!p || !config) return VCAM_INVALID;
    if (p->info.busy || p->info.lease_live) return VCAM_BUSY;
    if (p->info.state != VCAM_IDLE && p->info.state != VCAM_RECORDING) return status(p, VCAM_STATE);
    enum vcam_status s = independent(p, (struct span[]){{config, sizeof(*config)}}, 1);
    if (s != VCAM_OK) return status(p, s);
    if (!config->width || !config->height || config->width > VCAM_MAX_STILL_WIDTH ||
        config->height > VCAM_MAX_STILL_HEIGHT || config->stride < config->width * 3 ||
        config->stride > p->pool_capacity / config->height) return status(p, VCAM_BOUNDS);
    if (p->info.state == VCAM_RECORDING && (config->width != p->record_width ||
        config->height != p->record_height)) return status(p, VCAM_BUSY);
    p->info.optical_status = optical_frame_configure(&p->owner, config);
    return status(p, p->info.optical_status == OPTICAL_FRAME_OK ? VCAM_OK : VCAM_OPTICAL);
}
enum vcam_status vcam_autofocus(struct vcam_pipeline *p,
    const optical_frame_af_request *request, optical_frame_af_result *result)
{
    if (!p || !request || !result) return VCAM_INVALID;
    if (p->info.busy || p->info.lease_live) return VCAM_BUSY;
    if (p->info.state != VCAM_IDLE && p->info.state != VCAM_RECORDING) return status(p, VCAM_STATE);
    enum vcam_status s = independent(p, (struct span[]){{request, sizeof(*request)},
                                    {result, sizeof(*result)}}, 2);
    if (s != VCAM_OK) return status(p, s);
    p->info.busy = 1;
    p->info.optical_status = optical_frame_autofocus(&p->owner, request, p->pool,
                                                    p->pool_capacity, result);
    p->info.busy = 0;
    return status(p, p->info.optical_status == OPTICAL_FRAME_OK ? VCAM_OK : VCAM_OPTICAL);
}

static int borrowed_consume(const optical_frame_view *view, void *opaque)
{
    struct vcam_pipeline *p = opaque;
    p->borrowed = view;
    if (p->video_frame) {
        p->proof.consumer_entered = 1;
        p->proof.consumer_before_state = p->owner.info.state;
        p->proof.consumer_before_fnv1a64 = active_hash(view->pixels,
            view->width, view->height, view->stride);
        const struct video_engine_rgb rgb = {view->pixels, view->size, view->stride};
        const struct video_engine_stream_info before = video_engine_stream_snapshot(p->video);
        p->video_result = video_engine_stream_feed_rgb888(p->video, &rgb,
                                                         (int64_t)before.frames_consumed, 1);
        const struct video_engine_stream_info after = video_engine_stream_snapshot(p->video);
        p->info.counts.encoder_consumed += after.frames_consumed - before.frames_consumed;
        p->info.counts.encoded += after.packets_received - before.packets_received;
        p->proof.encoder_consumed = after.frames_consumed - before.frames_consumed;
        p->proof.consumer_status = p->video_result;
    } else {
        p->jpeg_result = vjpeg_hw_execute(p->jpeg);
        p->proof.consumer_status = p->jpeg_result;
    }
    p->proof.consumer_returned = 1;
    p->proof.consumer_after_state = p->owner.info.state;
    p->proof.consumer_after_fnv1a64 = active_hash(view->pixels,
        view->width, view->height, view->stride);
    p->borrowed = NULL;
    return p->video_frame ? p->video_result != VIDEO_ENGINE_OK : p->jpeg_result != VJPEG_OK;
}
static enum vcam_status run_frame(struct vcam_pipeline *p, struct vcam_frame_result *result)
{
    if (p->proof.serial == UINT64_MAX) return VCAM_BOUNDS;
    const uint64_t serial = p->proof.serial + 1;
    p->proof = (struct vcam_frame_proof){.serial = serial,
        .render_status = -ENODATA, .consumer_status = -ENODATA, .retire_status = -ENODATA,
        .encoded_fnv1a64 = UINT64_C(14695981039346656037),
        .before = vcam_snapshot(p).counts};
    p->info.optical_status = optical_frame_acquire(&p->owner, p->pool, p->pool_capacity, &p->lease);
    if (p->info.optical_status != OPTICAL_FRAME_OK) {
        p->proof.final_state = p->owner.info.state;
        p->proof.after = vcam_snapshot(p).counts;
        return VCAM_OPTICAL;
    }
    p->info.lease_live = 1;
    p->info.optical_status = optical_frame_render(&p->owner, &p->lease);
    p->proof.render_status = p->info.optical_status;
    enum vcam_status s = VCAM_OPTICAL;
    if (p->info.optical_status == OPTICAL_FRAME_OK) {
        optical_frame_info optical;
        (void)optical_frame_snapshot(&p->owner, &optical);
        p->proof.lease_generation = p->lease.generation;
        p->proof.width = optical.config.width;
        p->proof.height = optical.config.height;
        p->proof.stride = optical.config.stride;
        p->proof.active_bytes = optical.config.width * optical.config.height * 3u;
        p->proof.source_fnv1a64 = active_hash(p->pool, optical.config.width,
            optical.config.height, optical.config.stride);
        p->proof.render_observed = 1;
        p->proof.source_state = optical.state;
        *result = (struct vcam_frame_result){optical.generation, optical.metadata,
            p->video_frame ? (int64_t)video_engine_stream_snapshot(p->video).frames_consumed : 0};
        p->info.optical_status = optical_frame_consumer_read(&p->owner, &p->lease,
                                                            borrowed_consume, p);
        if (p->info.optical_status == OPTICAL_FRAME_OK) s = VCAM_OK;
        else if (p->info.optical_status == OPTICAL_FRAME_CONSUMER_FAILED)
            s = p->video_frame ? VCAM_VIDEO : VCAM_JPEG;
    }
    const optical_frame_status retired = optical_frame_retire(&p->owner, &p->lease);
    p->proof.retire_status = retired;
    p->proof.retired = retired == OPTICAL_FRAME_OK;
    p->proof.final_state = p->owner.info.state;
    p->proof.after = vcam_snapshot(p).counts;
    if (retired == OPTICAL_FRAME_OK) {
        p->info.lease_live = 0;
        p->info.jpeg_release_pending = 0;
    } else { p->info.optical_status = retired; s = VCAM_OPTICAL; }
    if (s == VCAM_OPTICAL) p->info.state = VCAM_FAULT;
    return s;
}
static void jpeg_reset(struct vcam_pipeline *p)
{
    struct vjpeg_snapshot snapshot = vjpeg_hw_snapshot(p->jpeg);
    if (snapshot.state == VJPEG_ARMED) {
        (void)vjpeg_hw_cancel(p->jpeg);
        snapshot = vjpeg_hw_snapshot(p->jpeg);
    }
    if (snapshot.fifo_count) (void)vjpeg_hw_mmio_write(p->jpeg, 0x40, 4, 1);
    (void)vjpeg_hw_ack(p->jpeg, snapshot.events);
}
enum vcam_status vcam_capture_still(struct vcam_pipeline *p,
    const struct vjpeg_coding *coding, uint8_t *output, size_t capacity,
    struct vcam_still_result *result)
{
    if (!p || !coding || !result) return VCAM_INVALID;
    if (p->info.busy || p->info.lease_live) return VCAM_BUSY;
    if (p->info.state != VCAM_IDLE) return status(p, VCAM_BUSY);
    const struct span spans[] = {{coding, sizeof(*coding)}, {output, capacity}, {result, sizeof(*result)}};
    enum vcam_status s = independent(p, spans, 3);
    if (s != VCAM_OK) return status(p, s);
    if (!p->owner.info.configured) return status(p, VCAM_STATE);
    if (capacity <= VJPEG_PREFIX_SIZE || capacity - VJPEG_PREFIX_SIZE > UINT32_MAX)
        return status(p, VCAM_BOUNDS);
    p->info.busy = 1;
    p->cancel_requested = 0;
    jpeg_reset(p);
    p->info.jpeg_release_pending = 0;
    p->jpeg_released = 0;
    p->info.jpeg_written = p->info.jpeg_readback = 0;
    p->info.jpeg_readback_crc32 = 0;
    p->read_crc = UINT32_MAX;
    const optical_frame_config *config = &p->owner.info.config;
    struct vjpeg_job job = {SOURCE_ADDRESS, config->stride * config->height,
        OUTPUT_ADDRESS, capacity - VJPEG_PREFIX_SIZE, VJPEG_RGB888, *coding};
    p->jpeg_result = vjpeg_hw_prepare(p->jpeg, &job);
    if (p->jpeg_result != VJPEG_OK) s = VCAM_JPEG;
    else if (coding->width != config->width || coding->height != config->height) {
        (void)vjpeg_hw_cancel(p->jpeg);
        s = VCAM_INVALID;
    } else {
        (void)vjpeg_source_prefix(coding, p->prefix);
        memcpy(output, p->prefix, VJPEG_PREFIX_SIZE);
        p->jpeg_output = output;
        p->jpeg_capacity = capacity;
        p->video_frame = 0;
        struct vcam_still_result value = {0};
        s = run_frame(p, &value.frame);
        if (s == VCAM_OK) {
            const size_t length = vjpeg_hw_snapshot(p->jpeg).output_length;
            if (!p->jpeg_released || length != p->info.jpeg_readback ||
                length != p->info.jpeg_written) s = VCAM_JPEG;
            else {
                value.prefix_length = VJPEG_PREFIX_SIZE;
                value.suffix_length = length;
                value.jpeg_length = VJPEG_PREFIX_SIZE + length;
                value.prefix_crc32 = crc32(output, VJPEG_PREFIX_SIZE);
                value.suffix_crc32 = p->info.jpeg_readback_crc32;
                value.jpeg_crc32 = crc32(output, value.jpeg_length);
                if (!p->cancel_requested) *result = value;
            }
        }
        p->jpeg_output = NULL;
        p->jpeg_capacity = 0;
    }
    p->info.busy = 0;
    if (p->cancel_requested && (s == VCAM_OK ||
        (s == VCAM_JPEG && p->jpeg_result == VJPEG_CANCELLED))) s = VCAM_CANCELLED;
    return status(p, s);
}

static size_t start_code(const uint8_t *data, size_t size)
{
    if (size >= 3 && data[0] == 0 && data[1] == 0 && data[2] == 1) return 3;
    if (size >= 4 && data[0] == 0 && data[1] == 0 && data[2] == 0 && data[3] == 1) return 4;
    return 0;
}
/* Extract bytes from actual access units, never synthesize AVC extradata. */
static size_t parameter_sets(const uint8_t *data, size_t size, uint8_t *output)
{
    size_t offset = 0, used = 0;
    unsigned seen = 0;
    while (offset < size) {
        const size_t prefix = start_code(data + offset, size - offset);
        if (!prefix || prefix == size - offset) return 0;
        const size_t begin = offset;
        offset += prefix;
        const unsigned type = data[offset] & 31u;
        if (data[offset] & 0x80u) return 0;
        while (offset < size && !start_code(data + offset, size - offset)) ++offset;
        if (type == 7 || type == 8) {
            const unsigned bit = type == 7 ? 1u : 2u;
            if (!(seen & bit)) {
                if (output) memcpy(output + used, data + begin, offset - begin);
                used += offset - begin;
                seen |= bit;
            }
        }
    }
    return seen == 3 ? used : 0;
}
static int packet_sink(const struct video_engine_stream_packet *packet, void *opaque)
{
    struct vcam_pipeline *p = opaque;
    if (p->info.busy && p->video_frame && packet && packet->data && packet->size) {
        p->proof.encoded_bytes += packet->size;
        p->proof.encoded_fnv1a64 = fnv_update(p->proof.encoded_fnv1a64, packet->data, packet->size);
    }
    if (p->info.packet_count >= p->buffers.packet_capacity) return SINK_INDEX;
    if (packet->size > p->buffers.data_capacity - p->info.packet_bytes) return SINK_BYTES;
    size_t config_size = p->info.config_bytes;
    if (p->info.packet_count && crc32(p->buffers.config, config_size) != p->config_crc)
        return SINK_VERIFY;
    if (!p->info.packet_count) {
        config_size = parameter_sets(packet->data, packet->size, NULL);
        p->info.config_required = config_size;
        if (!packet->keyframe || !config_size) return SINK_VERIFY;
        if (config_size > p->buffers.config_capacity) return SINK_CONFIG;
    }
    if (packet->pts != (int64_t)p->info.packet_count || packet->dts != packet->pts ||
        packet->duration != 1) return SINK_VERIFY;
    uint8_t *destination = p->buffers.data + p->info.packet_bytes;
    memcpy(destination, packet->data, packet->size);
    if (memcmp(destination, packet->data, packet->size)) return SINK_VERIFY;
    ++p->info.counts.output_readback;
    if (!p->info.packet_count)
        (void)parameter_sets(packet->data, packet->size, p->buffers.config);
    const uint32_t config_crc = crc32(p->buffers.config, config_size);
    if (p->callbacks.packet) {
        const int error = p->callbacks.packet(packet, p->callbacks.context);
        if (error) return error;
    }
    if (memcmp(destination, packet->data, packet->size) ||
        crc32(p->buffers.config, config_size) != config_crc) return SINK_VERIFY;
    p->buffers.packets[p->info.packet_count] = (struct video_engine_packet){
        p->info.packet_bytes, packet->size, packet->pts, packet->dts,
        packet->duration, packet->keyframe};
    p->info.packet_bytes += packet->size;
    ++p->info.packet_count;
    p->info.config_bytes = config_size;
    p->data_crc = crc_update(p->data_crc, packet->data, packet->size);
    p->config_crc = config_crc;
    return 0;
}
enum vcam_status vcam_record_begin(struct vcam_pipeline *p, unsigned fps,
                                  const struct vcam_record_buffers *buffers)
{
    if (!p || !buffers) return VCAM_INVALID;
    if (p->info.busy || p->info.lease_live) return VCAM_BUSY;
    if (p->info.state != VCAM_IDLE) return status(p, VCAM_BUSY);
    enum vcam_status s = independent(p, (struct span[]){{buffers, sizeof(*buffers)}}, 1);
    if (s != VCAM_OK) return status(p, s);
    if (!buffers->packet_capacity || buffers->packet_capacity > VIDEO_ENGINE_MAX_FRAMES ||
        !buffers->data_capacity || buffers->data_capacity > VIDEO_ENGINE_MAX_BYTES ||
        !buffers->config_capacity || buffers->config_capacity > 1024u * 1024u)
        return status(p, VCAM_BOUNDS);
    const struct span spans[] = {{buffers, sizeof(*buffers)},
        {buffers->data, buffers->data_capacity},
        {buffers->packets, buffers->packet_capacity * sizeof(*buffers->packets)},
        {buffers->config, buffers->config_capacity}};
    s = independent(p, spans, 4);
    if (s != VCAM_OK) return status(p, s);
    if (!p->owner.info.configured) return status(p, VCAM_STATE);
    const optical_frame_config *config = &p->owner.info.config;
    p->video_result = video_engine_stream_begin(p->video, config->width, config->height,
        fps, buffers->data_capacity, packet_sink, p);
    if (p->video_result != VIDEO_ENGINE_OK) return status(p, VCAM_VIDEO);
    p->buffers = *buffers;
    p->record_width = config->width;
    p->record_height = config->height;
    p->fps = fps;
    p->data_crc = UINT32_MAX;
    p->config_crc = 0;
    p->info.packet_bytes = p->info.packet_count = p->info.config_bytes = 0;
    p->info.config_required = 0;
    p->cancel_requested = 0;
    p->info.state = VCAM_RECORDING;
    return status(p, VCAM_OK);
}
static enum vcam_status video_failure(struct vcam_pipeline *p)
{
    const struct video_engine_stream_info video = video_engine_stream_snapshot(p->video);
    p->info.state = VCAM_FAULT;
    if (video.sink_error == SINK_BYTES || video.sink_error == SINK_INDEX ||
        video.sink_error == SINK_CONFIG || p->video_result == VIDEO_ENGINE_OUTPUT_TOO_SMALL)
        return VCAM_BOUNDS;
    return video.sink_error ? VCAM_SINK : VCAM_VIDEO;
}
enum vcam_status vcam_record_frame(struct vcam_pipeline *p, struct vcam_frame_result *result)
{
    if (!p || !result) return VCAM_INVALID;
    if (p->info.busy || p->info.lease_live) return VCAM_BUSY;
    if (p->info.state != VCAM_RECORDING) return status(p, VCAM_STATE);
    enum vcam_status s = independent(p, (struct span[]){{result, sizeof(*result)}}, 1);
    if (s != VCAM_OK) return status(p, s);
    if (video_engine_stream_snapshot(p->video).frames_consumed >= VIDEO_ENGINE_MAX_FRAMES)
        return status(p, VCAM_BOUNDS);
    p->info.busy = 1;
    p->video_frame = 1;
    struct vcam_frame_result value;
    s = run_frame(p, &value);
    if (s == VCAM_VIDEO) s = video_failure(p);
    p->info.busy = 0;
    if (p->cancel_requested) {
        (void)video_engine_stream_cancel(p->video);
        if (s == VCAM_OK) { p->info.state = VCAM_IDLE; s = VCAM_CANCELLED; }
    }
    if (s == VCAM_OK) *result = value;
    return status(p, s);
}
enum vcam_status vcam_record_end(struct vcam_pipeline *p, uint8_t *output,
                                size_t capacity, struct video_engine_result *result)
{
    if (!p || !result) return VCAM_INVALID;
    if (p->info.busy || p->info.lease_live) return VCAM_BUSY;
    if (p->info.state != VCAM_RECORDING && p->info.state != VCAM_DRAINED)
        return status(p, VCAM_STATE);
    enum vcam_status s = independent(p, (struct span[]){{output, capacity},
                                                       {result, sizeof(*result)}}, 2);
    if (s != VCAM_OK) return status(p, s);
    if (!video_engine_stream_snapshot(p->video).frames_consumed) return status(p, VCAM_STATE);
    p->info.busy = 1;
    if (p->info.state == VCAM_RECORDING) {
        const struct video_engine_stream_info before = video_engine_stream_snapshot(p->video);
        p->video_result = video_engine_stream_drain(p->video);
        if (p->video_result == VIDEO_ENGINE_OK) p->video_result = video_engine_stream_finish(p->video);
        const struct video_engine_stream_info after = video_engine_stream_snapshot(p->video);
        p->info.counts.encoded += after.packets_received - before.packets_received;
        if (p->video_result != VIDEO_ENGINE_OK) s = video_failure(p);
        else if (p->cancel_requested) {
            (void)video_engine_stream_cancel(p->video);
            p->info.state = VCAM_IDLE;
            s = VCAM_CANCELLED;
        } else p->info.state = VCAM_DRAINED;
    }
    if (s == VCAM_OK) {
        if (crc32(p->buffers.data, p->info.packet_bytes) != ~p->data_crc ||
            crc32(p->buffers.config, p->info.config_bytes) != p->config_crc) {
            p->info.state = VCAM_FAULT;
            s = VCAM_SINK;
        } else {
            *result = video_engine_mux_mp4(p->buffers.data, p->info.packet_bytes,
                p->buffers.packets, p->info.packet_count, p->buffers.config, p->info.config_bytes,
                p->record_width, p->record_height, p->fps, output, capacity);
            if (result->status == VIDEO_ENGINE_OK) p->info.state = VCAM_IDLE;
            else if (result->status == VIDEO_ENGINE_OUTPUT_TOO_SMALL) s = VCAM_BOUNDS;
            else { p->info.state = VCAM_FAULT; s = VCAM_VIDEO; }
        }
    }
    p->info.busy = 0;
    return status(p, s);
}
enum vcam_status vcam_cancel(struct vcam_pipeline *p)
{
    if (!p) return VCAM_INVALID;
    if (p->info.busy) {
        p->cancel_requested = 1;
        const enum vjpeg_state jpeg_state = vjpeg_hw_snapshot(p->jpeg).state;
        if (jpeg_state == VJPEG_RUNNING || jpeg_state == VJPEG_ARMED)
            (void)vjpeg_hw_cancel(p->jpeg);
        return VCAM_OK;
    }
    if (p->info.lease_live) {
        p->info.optical_status = optical_frame_retire(&p->owner, &p->lease);
        if (p->info.optical_status != OPTICAL_FRAME_OK) return status(p, VCAM_OPTICAL);
        p->info.lease_live = 0;
    }
    (void)video_engine_stream_cancel(p->video);
    if (vjpeg_hw_snapshot(p->jpeg).state == VJPEG_ARMED) (void)vjpeg_hw_cancel(p->jpeg);
    p->info.jpeg_release_pending = 0;
    p->info.state = VCAM_IDLE;
    p->cancel_requested = 0;
    return status(p, VCAM_CANCELLED);
}
