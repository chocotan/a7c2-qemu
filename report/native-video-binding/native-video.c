#include "native-video.h"

#include <limits.h>
#include <stdlib.h>
#include <string.h>

static uint16_t get16(const uint8_t *p)
{
    return (uint16_t)((uint16_t)p[0] | (uint16_t)((uint16_t)p[1] << 8));
}
static uint32_t get32(const uint8_t *p)
{
    return (uint32_t)p[0] | (uint32_t)p[1] << 8 |
           (uint32_t)p[2] << 16 | (uint32_t)p[3] << 24;
}
static uint64_t get64(const uint8_t *p)
{
    return (uint64_t)get32(p) | (uint64_t)get32(p + 4) << 32;
}
static void put32(uint8_t *p, uint32_t v)
{
    for (unsigned i = 0; i != 4; ++i) p[i] = (uint8_t)(v >> (8 * i));
}
static void put64(uint8_t *p, uint64_t v)
{
    put32(p, (uint32_t)v);
    put32(p + 4, (uint32_t)(v >> 32));
}
static int valid_span(const void *p, size_t n)
{
    return p && n && n <= UINTPTR_MAX - (uintptr_t)p;
}
/* Only called after validating both complete numerical spans. */
static int overlaps(const void *a, size_t an, const void *b, size_t bn)
{
    return (uintptr_t)a < (uintptr_t)b + bn &&
        (uintptr_t)b < (uintptr_t)a + an;
}
static int sample_type(unsigned type)
{
    return type <= 3 || type == 9;
}

enum nvideo_status nvideo_parse_mpr_request(uint32_t sid,
    const uint8_t *wire, size_t wire_size, size_t parameter_size,
    struct nvideo_request *out)
{
    struct nvideo_request r = {0};
    size_t required;
    if (!out || wire_size != NVIDEO_MPR_BYTES || !valid_span(wire, wire_size))
        return NVIDEO_INVALID;
    if (sid != NVIDEO_MPR_SID || get32(wire + 0x24) != 0x210)
        return NVIDEO_UNSUPPORTED;
    r.command = get16(wire + 2);
    switch (r.command) {
    case 0: required = NVIDEO_ENCOPEN_BYTES; break;
    case 1: required = 0x80; break;
    case 2: required = 4; break;
    case 3: required = 0x10; break;
    default: return NVIDEO_UNSUPPORTED;
    }
    r.payload_size = get32(wire + 0x10);
    if (r.payload_size != required || parameter_size != required)
        return NVIDEO_INVALID;
    r.codec = wire[0x18]; r.second_codec = wire[0x19];
    r.view = get16(wire + 0x1a);
    r.file_format = wire[0x1c]; r.second_file_format = wire[0x1e];
    /* shortcut: only single-unit EncOpen; extend with a proved second form. */
    if (!r.command && (r.second_codec || r.second_file_format))
        return NVIDEO_UNSUPPORTED;
    r.fixed_area = get64(wire + 8);
    r.parameter_address = get64(wire + 0x28);
    if (!r.parameter_address || r.parameter_address > UINT64_MAX - required)
        return NVIDEO_RANGE;
    *out = r;
    return NVIDEO_OK;
}

enum nvideo_status nvideo_parse_encopen_parameters(uint32_t sid,
    const uint8_t *wire, size_t wire_size, uint64_t mapped_base,
    const uint8_t *parameters, size_t parameter_size,
    struct nvideo_encopen_parameters *out, size_t out_capacity)
{
    struct nvideo_encopen_parameters r = {0};
    enum nvideo_status status;
    if (wire_size != NVIDEO_MPR_BYTES ||
        !valid_span(wire, wire_size) || !valid_span(parameters, parameter_size) ||
        !valid_span(out, out_capacity) || out_capacity < sizeof(*out) ||
        (uintptr_t)out % _Alignof(struct nvideo_encopen_parameters) ||
        overlaps(out, out_capacity, wire, wire_size) ||
        overlaps(out, out_capacity, parameters, parameter_size))
        return NVIDEO_INVALID;
    status = nvideo_parse_mpr_request(sid, wire, wire_size, parameter_size, &r.request);
    if (status != NVIDEO_OK) return status;
    if (r.request.command != 0) return NVIDEO_UNSUPPORTED;
    if (mapped_base != r.request.parameter_address) return NVIDEO_RANGE;
    r.main_es_base = get64(parameters);
    r.main_es_capacity = get32(parameters + 8);
    r.secondary_es_base = get64(parameters + 0x10);
    r.secondary_es_capacity = get32(parameters + 0x18);
    r.auxiliary_base = get64(parameters + 0x20);
    r.auxiliary_capacity = get16(parameters + 0x28);
    r.video_info_base = get64(parameters + 0x30);
    r.video_info_count = get16(parameters + 0x38);
    r.read_control_base = get64(parameters + 0x50);
    r.write_control_base = get64(parameters + 0x58);
    r.read_control_declared_bytes = 0x294;
    r.write_control_declared_bytes = 0x330;
    r.selection_byte = parameters[0x88];
    if (r.main_es_capacity > UINT64_MAX - r.main_es_base ||
        r.secondary_es_capacity > UINT64_MAX - r.secondary_es_base ||
        (uint64_t)r.video_info_count * NVIDEO_INFO_BYTES > UINT64_MAX - r.video_info_base ||
        r.read_control_declared_bytes > UINT64_MAX - r.read_control_base ||
        r.write_control_declared_bytes > UINT64_MAX - r.write_control_base)
        return NVIDEO_RANGE;
    memcpy(out, &r, sizeof(r));
    return NVIDEO_OK;
}

unsigned nvideo_native_gaps(void) { return NVIDEO_NATIVE_GAPS; }
enum nvideo_status nvideo_native_request(uint32_t sid,
    const uint8_t *wire, size_t wire_size, size_t parameter_size, unsigned *gaps)
{
    struct nvideo_request request;
    enum nvideo_status status = nvideo_parse_mpr_request(
        sid, wire, wire_size, parameter_size, &request);
    if (gaps) *gaps = NVIDEO_NATIVE_GAPS;
    return status == NVIDEO_OK ? NVIDEO_UNSUPPORTED : status;
}

enum nvideo_status nvideo_parse_info(const uint8_t *wire, size_t size,
    uint64_t es_base, size_t es_capacity, struct nvideo_info *out)
{
    struct nvideo_info r;
    if (!out || size != NVIDEO_INFO_BYTES || !valid_span(wire, size))
        return NVIDEO_INVALID;
    if (!sample_type(wire[0])) return NVIDEO_UNSUPPORTED;
    memset(&r, 0, sizeof(r));
    r.type = wire[0]; r.parameter_set_changes = wire[1] & 7;
    r.padding = wire[2]; r.unit = wire[3] & 1;
    r.address = get64(wire + 8); r.length = get32(wire + 0x10);
    r.pts = get64(wire + 0x18); r.dts = get64(wire + 0x20);
    r.vps_size = get16(wire + 0x28); r.vps_count = wire[0x2a]; r.vps_id = wire[0x2b];
    r.sps_size = get16(wire + 0x2c); r.sps_count = wire[0x2e]; r.sps_id = wire[0x2f];
    r.pps_size = get16(wire + 0x30); r.pps_count = wire[0x32]; r.pps_id = wire[0x33];
    r.keyframe = r.type == 0;
    if (!r.length) return NVIDEO_INVALID;
    if (!es_capacity || es_capacity > UINT64_MAX - es_base || r.address < es_base ||
        r.address - es_base > es_capacity ||
        r.length > es_capacity - (r.address - es_base)) return NVIDEO_RANGE;
    *out = r;
    return NVIDEO_OK;
}

enum nvideo_status nvideo_build_sample64(const struct nvideo_info *info,
    uint64_t file_offset, int last_sample, uint8_t *wire, size_t size)
{
    uint8_t result[NVIDEO_SAMPLE64_BYTES] = {0};
    if (!info || size != sizeof(result) || !valid_span(wire, size) ||
        (last_sample != 0 && last_sample != 1) || !info->length)
        return NVIDEO_INVALID;
    if (!sample_type(info->type)) return NVIDEO_UNSUPPORTED;
    if (info->length > UINT64_MAX - file_offset) return NVIDEO_RANGE;
    /* Original M118540..584 permutes the low/high PTS/DTS words. */
    put32(result, (uint32_t)info->pts);
    put32(result + 4, (uint32_t)info->dts);
    put32(result + 8, (uint32_t)(info->pts >> 32));
    put32(result + 0xc, (uint32_t)(info->dts >> 32));
    put32(result + 0x10, info->length);
    put64(result + 0x18, file_offset);
    result[0x20] = info->type == 0;
    result[0x21] = (uint8_t)last_sample;
    memcpy(wire, result, sizeof(result));
    return NVIDEO_OK;
}

enum nvideo_status nvideo_blob_copy(const uint8_t *descriptor, size_t size,
    uint64_t mapped_base, uint8_t *mapped, size_t mapped_capacity,
    const uint8_t *source, size_t source_size)
{
    uint64_t base;
    uint32_t capacity;
    if (size != 16 || !valid_span(descriptor, size) ||
        !valid_span(mapped, mapped_capacity) || !valid_span(source, source_size))
        return NVIDEO_INVALID;
    if (source_size != 0x40 && source_size != 0x1c0 &&
        source_size != 0x300 && source_size != 0x80) return NVIDEO_UNSUPPORTED;
    base = get64(descriptor); capacity = get32(descriptor + 8);
    if (!base || base != mapped_base || capacity > mapped_capacity ||
        capacity > UINT64_MAX - base || source_size > capacity) return NVIDEO_RANGE;
    memmove(mapped, source, source_size);
    return NVIDEO_OK;
}

struct nvideo_binding {
    struct video_engine_stream *stream;
    struct nvideo_ops ops;
    void *context;
    uint64_t owner, sequence, destination;
    size_t capacity;
    int active, busy, have_sequence, have_packet, error;
    enum nvideo_status fault;
    struct nvideo_component_completion pending;
};

static int same_key(const struct nvideo_frame_key *a, const struct nvideo_frame_key *b)
{
    return a->owner == b->owner && a->sequence == b->sequence &&
        a->sds.type == b->sds.type && a->sds.handle == b->sds.handle &&
        a->sds.offset == b->sds.offset;
}
static enum nvideo_status codec_fault(struct nvideo_binding *b)
{
    if (b->fault == NVIDEO_OK) b->fault = NVIDEO_CODEC_ERROR;
    return b->fault;
}
static int packet_sink(const struct video_engine_stream_packet *p, void *context)
{
    struct nvideo_binding *b = context;
    uint8_t check[4096];
    size_t offset = 0;
    if (!b->busy || b->have_packet || !p->size || p->size > b->capacity ||
        p->pts != b->pending.pts || p->dts != p->pts ||
        p->duration != b->pending.duration) {
        b->fault = NVIDEO_RANGE;
        return -1;
    }
    b->error = b->ops.write(b->context, b->destination, p->data, p->size);
    if (b->error) { b->fault = NVIDEO_DMA_ERROR; return b->error; }
    while (offset < p->size) {
        size_t n = p->size - offset;
        if (n > sizeof(check)) n = sizeof(check);
        b->error = b->ops.read(b->context, b->destination + offset, check, n);
        if (b->error) { b->fault = NVIDEO_DMA_ERROR; return b->error; }
        if (memcmp(check, p->data + offset, n)) {
            b->fault = NVIDEO_DMA_ERROR;
            return -1;
        }
        offset += n;
    }
    b->pending.address = b->destination;
    b->pending.length = p->size;
    b->pending.dts = p->dts;
    b->pending.keyframe = p->keyframe;
    b->have_packet = 1;
    return 0;
}

struct nvideo_binding *nvideo_component_create(struct video_engine_stream *stream,
    const struct nvideo_ops *ops, void *context)
{
    struct nvideo_binding *b;
    if (!stream || !ops || !ops->acquire || !ops->release || !ops->write ||
        !ops->read || !ops->publish) return NULL;
    b = calloc(1, sizeof(*b));
    if (b) { b->stream = stream; b->ops = *ops; b->context = context; }
    return b;
}
void nvideo_component_destroy(struct nvideo_binding *b)
{
    if (!b || b->busy) return;
    if (b->active || b->fault != NVIDEO_OK)
        (void)video_engine_stream_cancel(b->stream);
    free(b);
}

enum nvideo_status nvideo_component_begin(struct nvideo_binding *b,
    size_t width, size_t height, unsigned fps, size_t max_packet_bytes, uint64_t owner)
{
    enum video_engine_status status;
    if (!b || !owner) return NVIDEO_INVALID;
    if (b->busy || b->active || b->fault != NVIDEO_OK) return NVIDEO_STATE;
    status = video_engine_stream_begin(b->stream, width, height, fps,
        max_packet_bytes, packet_sink, b);
    if (status != VIDEO_ENGINE_OK) {
        if (status == VIDEO_ENGINE_INVALID_ARGUMENT) return NVIDEO_INVALID;
        if (status == VIDEO_ENGINE_INVALID_STATE) return NVIDEO_STATE;
        return codec_fault(b);
    }
    b->owner = owner; b->have_sequence = 0; b->error = 0; b->active = 1;
    return NVIDEO_OK;
}

enum nvideo_status nvideo_component_frame(struct nvideo_binding *b,
    const struct nvideo_frame_key *key, uint64_t destination,
    size_t destination_capacity, int64_t pts, int64_t duration)
{
    struct nvideo_source source;
    struct nvideo_frame_key requested;
    enum video_engine_status encoded;
    int released;
    if (!b || !key || !destination || !destination_capacity ||
        destination_capacity > UINT64_MAX - destination || pts < 0 || duration <= 0 ||
        pts > INT64_MAX - duration) return NVIDEO_INVALID;
    if (b->busy || !b->active) return NVIDEO_STATE;
    if (b->fault != NVIDEO_OK) return b->fault;
    if (key->owner != b->owner || (b->have_sequence && key->sequence <= b->sequence))
        return NVIDEO_STALE;
    requested = *key;
    memset(&source, 0, sizeof(source));
    b->busy = 1; b->have_packet = 0;
    b->error = b->ops.acquire(b->context, &requested, &source);
    if (b->error) { b->busy = 0; return NVIDEO_SOURCE_ERROR; }
    b->pending.key = requested; b->pending.pts = pts; b->pending.duration = duration;
    b->destination = destination; b->capacity = destination_capacity;
    if (!same_key(&requested, &source.key)) b->fault = NVIDEO_STALE;
    else if (source.layout != NVIDEO_HOST_RGB888) b->fault = NVIDEO_UNSUPPORTED;
    if (b->fault == NVIDEO_OK) {
        encoded = video_engine_stream_feed_rgb888(b->stream, &source.rgb, pts, duration);
        if (encoded != VIDEO_ENGINE_OK || !b->have_packet) (void)codec_fault(b);
    }
    released = b->ops.release(b->context, &source);
    if (released) {
        if (!b->error) b->error = released;
        if (b->fault == NVIDEO_OK) b->fault = NVIDEO_SOURCE_ERROR;
    }
    if (b->fault == NVIDEO_OK) {
        b->sequence = requested.sequence; b->have_sequence = 1;
        b->ops.publish(b->context, &b->pending);
    } else {
        (void)video_engine_stream_cancel(b->stream);
    }
    b->busy = 0;
    return b->fault;
}

enum nvideo_status nvideo_component_finish(struct nvideo_binding *b)
{
    enum video_engine_status status;
    if (!b) return NVIDEO_INVALID;
    if (b->busy || !b->active) return NVIDEO_STATE;
    if (b->fault != NVIDEO_OK) return b->fault;
    b->busy = 1;
    status = video_engine_stream_finish(b->stream);
    b->busy = 0;
    if (status != VIDEO_ENGINE_OK) return codec_fault(b);
    b->active = 0;
    return NVIDEO_OK;
}
enum nvideo_status nvideo_component_cancel(struct nvideo_binding *b)
{
    if (!b) return NVIDEO_INVALID;
    if (b->busy) return NVIDEO_STATE;
    if (b->active || b->fault != NVIDEO_OK)
        (void)video_engine_stream_cancel(b->stream);
    b->active = 0; b->fault = NVIDEO_OK;
    return NVIDEO_OK;
}
int nvideo_component_error(const struct nvideo_binding *b)
{
    return b ? b->error : 0;
}
