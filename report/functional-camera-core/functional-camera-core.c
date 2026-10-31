/* SPDX-License-Identifier: MIT */
#include "functional-camera-core.h"
#include "../virtual-camera-pipeline/camera-pipeline.h"

#include <errno.h>
#include <limits.h>
#include <math.h>
#include <stdatomic.h>
#include <setjmp.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <jpeglib.h>
#include <jerror.h>

#define FRAME_CAPACITY ((size_t)FCAM_MAX_STILL_WIDTH * FCAM_MAX_STILL_HEIGHT * 3u)
#define CONFIG_LIMIT (1024u * 1024u)
#define FNV_OFFSET UINT64_C(14695981039346656037)
#define FNV_PRIME UINT64_C(1099511628211)

struct config {
    uint32_t width, height, fps, quality, fnumber, iso;
    uint64_t shutter, focus;
};
static const struct config defaults = {FCAM_DEFAULT_WIDTH, FCAM_DEFAULT_HEIGHT,
    FCAM_DEFAULT_FPS, FCAM_DEFAULT_QUALITY, 400, 100, 16667, 3000000};
/* shortcut: only original014c case0 is defined here; extend with a specified software layout policy. */
static const uint8_t layout_case0[FCAM_LAYOUT_INPUT_BYTES] = {
    7, 1, 1, 0, 0, 0, 0, 0, 0x80, 0x02, 0xe0, 0x01, [24] = 3};
struct bb_policy {
    uint32_t sq_mode, sq_rate, sq_aux12, sq_aux16, sq_aux20, sq_aux24;
    uint32_t look[8], input_tag, gain_tag;
    uint32_t interval_enabled, interval_mode, interval_period, delay_enabled, delay_tag;
};
struct quant_context {
    struct jpeg_compress_struct codec;
    struct jpeg_error_mgr error;
    jmp_buf jump;
    int failure, live;
};
struct fcam_model {
    uint64_t instance, generation, frame_generation;
    uint64_t lifetime, owner_pid, retired;
    struct fcam_frame_proof proof;
    uint64_t rendered, consumed, jpeg_encoded, video_encoded, result_read;
    uint64_t next_token, token, result_hash, packet_generation;
    uint32_t caps, stream_state;
    struct config config;
    uint8_t *pool, *result_data, *video_config;
    size_t result_size, result_cursor, video_config_size, last_packet;
    struct vcam_pipeline *still;
    optical_frame_owner owner;
    struct video_engine_stream *video;
    struct quant_context quant;
    enum video_engine_status video_status;
    int busy, sensor_initialized;
    uint8_t vdf_staged[FCAM_VDF_INPUT_BYTES], vdf_config[FCAM_VDF_INPUT_BYTES];
    uint8_t zebra_staged[5], zebra_config[5];
    uint8_t layout_staged[FCAM_LAYOUT_INPUT_BYTES], layout_config[FCAM_LAYOUT_INPUT_BYTES];
    int layout_valid;
    uint8_t display_staged[3][FCAM_DISPLAY_INPUT_BYTES], display_config[3][FCAM_DISPLAY_INPUT_BYTES];
    uint8_t bb_staged[FCAM_BB_FEATURES][FCAM_BB_INPUT_BYTES];
    uint8_t bb_config[FCAM_BB_FEATURES][FCAM_BB_INPUT_BYTES], bb_valid[FCAM_BB_FEATURES];
    struct bb_policy bb_staged_policy, bb_applied;
    uint8_t bb_result[FCAM_BB_RESULT_BYTES];
    uint8_t hist_staged[FCAM_HIST_INPUT_BYTES], hist_config[FCAM_HIST_INPUT_BYTES];
    uint8_t hist_result[FCAM_HIST_RESULT_BYTES];
    int hist_valid;
    uint8_t bit_width_staged[FCAM_BIT_WIDTH_INPUT_BYTES], bit_width_config[FCAM_BIT_WIDTH_INPUT_BYTES];
    int bit_width_valid;
    uint8_t still_format_staged[FCAM_STILL_FORMAT_INPUT_BYTES], still_format_config[FCAM_STILL_FORMAT_INPUT_BYTES];
    int still_format_valid;
    uint8_t startup_staged[2][FCAM_STARTUP_CONTROL_INPUT_BYTES];
    uint8_t mode_bank32[FCAM_STARTUP_CONTROL_INPUT_BYTES], setting_bank32[FCAM_STARTUP_CONTROL_INPUT_BYTES];
    int mode_valid, setting_valid;
    size_t startup_slot;
    uint64_t startup_saved_generation[2], startup_saved_seal[2];
    uint8_t settings_staged40[FCAM_STARTUP_CONTROL_CONFIG_BYTES];
    uint8_t settings_snapshot40[FCAM_STARTUP_CONTROL_CONFIG_BYTES];
    uint8_t *vdf_sink;
    size_t vdf_capacity, vdf_copied;
    uint32_t vdf_class;
    int vdf_busy;
};
static _Atomic uint64_t model_lifetimes;
_Static_assert(sizeof(struct fcam_frame_proof) == 47u * sizeof(uint64_t), "proof POD layout");
struct span { const void *data; size_t size; };

static uint16_t get16(const uint8_t *p)
{
    return (uint16_t)((uint16_t)p[0] | (uint16_t)p[1] << 8);
}
static uint32_t get32(const uint8_t *p)
{
    return (uint32_t)p[0] | (uint32_t)p[1] << 8 |
           (uint32_t)p[2] << 16 | (uint32_t)p[3] << 24;
}
static uint64_t get64(const uint8_t *p)
{
    return get32(p) | (uint64_t)get32(p + 4) << 32;
}
static void put32(uint8_t *p, uint32_t v)
{
    for (unsigned i = 0; i < 4; ++i) p[i] = (uint8_t)(v >> (8u * i));
}
static void put64(uint8_t *p, uint64_t v)
{
    for (unsigned i = 0; i < 8; ++i) p[i] = (uint8_t)(v >> (8u * i));
}
static uint64_t fnv_update(uint64_t hash, const uint8_t *p, size_t size)
{
    for (size_t i = 0; i < size; ++i) hash = (hash ^ p[i]) * FNV_PRIME;
    return hash;
}
static uint64_t fnv(const uint8_t *p, size_t size)
{
    return fnv_update(FNV_OFFSET, p, size);
}
static uint64_t active_hash(const uint8_t *pixels, size_t width, size_t height, size_t stride)
{
    uint64_t hash = FNV_OFFSET;
    for (size_t y = 0; y < height; ++y)
        hash = fnv_update(hash, pixels + y * stride, width * 3u);
    return hash;
}
static struct fcam_proof_counts proof_counts(const struct fcam_model *m)
{
    return (struct fcam_proof_counts){m->rendered, m->consumed, m->jpeg_encoded,
        m->video_encoded, m->retired};
}
static void proof_begin(struct fcam_model *m, uint32_t op)
{
    const uint64_t serial = m->proof.serial + 1;
    m->proof = (struct fcam_frame_proof){.version = FCAM_PROOF_VERSION,
        .struct_bytes = sizeof(m->proof), .serial = serial, .model_instance = m->instance,
        .model_lifetime = m->lifetime, .owner_pid = m->owner_pid, .opcode = op,
        .consumer_kind = op == FCAM_OP_STILL ? FCAM_PROOF_JPEG :
            op == FCAM_OP_VIDEO_FRAME ? FCAM_PROOF_H264 :
            op == FCAM_OP_VIDEO_END ? FCAM_PROOF_DRAIN :
            op == FCAM_OP_BB_STARTUP_CONFIG ? FCAM_PROOF_BB_STARTUP :
            op == FCAM_OP_HISTOGRAM ? FCAM_PROOF_HISTOGRAM :
            (op == FCAM_OP_VDF_PATH || op == FCAM_OP_VDF_ZEBRA ||
             op == FCAM_OP_VDF_LAYOUT || op == FCAM_OP_VDF_DISPLAY_CONFIG ||
             op == FCAM_OP_VDF_BIT_WIDTH || op == FCAM_OP_STILL_FORMAT ||
             op == FCAM_OP_STARTUP_CONTROL) ? FCAM_PROOF_VDF : FCAM_PROOF_PROBE,
        .config_generation = m->generation, .frame_generation = m->frame_generation,
        .packet_generation = m->packet_generation, .render_status = -ENODATA,
        .consumer_status = -ENODATA, .retire_status = -ENODATA,
        .operation_status = -EINPROGRESS, .before = proof_counts(m), .after = proof_counts(m),
        .encoded_fnv1a64 = FNV_OFFSET, .result_fnv1a64 = FNV_OFFSET};
}
static void proof_source(struct fcam_model *m, const optical_frame_lease *lease)
{
    const optical_frame_info *info = &m->owner.info;
    m->proof.config_generation = m->generation;
    m->proof.frame_generation = m->frame_generation;
    m->proof.lease_generation = lease->generation;
    m->proof.packet_generation = m->packet_generation;
    m->proof.width = info->config.width;
    m->proof.height = info->config.height;
    m->proof.stride = info->config.stride;
    m->proof.active_bytes = info->config.width * info->config.height * 3u;
    m->proof.source_fnv1a64 = active_hash(m->pool, info->config.width,
        info->config.height, info->config.stride);
    m->proof.render_observed = 1;
    m->proof.source_state = info->state;
}
static void proof_result(struct fcam_model *m)
{
    if (m->result_data && m->result_size <= FCAM_MAX_RESULT_BYTES) {
        m->proof.result_bytes = m->result_size;
        m->proof.result_fnv1a64 = fnv(m->result_data, m->result_size);
    }
}
static void proof_finish(struct fcam_model *m, int error)
{
    proof_result(m);
    m->proof.result_token = m->token;
    m->proof.operation_status = error;
    m->proof.after = proof_counts(m);
}
static int valid_span(struct span s)
{
    return (!s.size || s.data) && s.size <= UINTPTR_MAX - (uintptr_t)s.data;
}
static int overlap(struct span a, struct span b)
{
    return a.size && b.size && (uintptr_t)a.data < (uintptr_t)b.data + b.size &&
           (uintptr_t)b.data < (uintptr_t)a.data + a.size;
}
static int arguments(struct fcam_model *m, const uint8_t *input, size_t in_size,
                     uint8_t *out, size_t capacity, struct fcam_exec_result *r)
{
    if (!m || !r || !valid_span((struct span){m, sizeof(*m)})) return -EINVAL;
    const struct span spans[] = {{input, in_size}, {out, capacity}, {r, sizeof(*r)}};
    const struct span private_spans[] = {{m, sizeof(*m)}, {m->pool, FRAME_CAPACITY},
        {m->result_data, m->result_data ? FCAM_MAX_RESULT_BYTES : 0},
        {m->video_config, m->video_config_size}, {m->vdf_sink, m->vdf_capacity}};
    for (size_t i = 0; i < 3; ++i) {
        if (!valid_span(spans[i])) return -EINVAL;
        for (size_t j = 0; j < i; ++j)
            if (overlap(spans[i], spans[j])) return -EINVAL;
        for (size_t j = 0; j < sizeof(private_spans) / sizeof(private_spans[0]); ++j)
            if (overlap(spans[i], private_spans[j])) return -EINVAL;
    }
    if (in_size > FCAM_DATA_BYTES || capacity > FCAM_DATA_BYTES) return -E2BIG;
    if (m->owner_pid != (uint64_t)getpid()) return -ECHILD;
    return m->busy ? -EBUSY : 0;
}
static int config_parse(const uint8_t *p, struct config *c, int video)
{
    *c = (struct config){get32(p), get32(p + 4), get32(p + 8), get32(p + 12),
        get32(p + 16), get32(p + 20), get64(p + 24), get64(p + 32)};
    if (get32(p + 40) || get32(p + 44)) return -EINVAL;
    if (!c->width || c->width > FCAM_MAX_STILL_WIDTH || !c->height ||
        c->height > FCAM_MAX_STILL_HEIGHT || !c->fps || c->fps > 120 ||
        !c->quality || c->quality > 100 || !c->iso || !c->shutter ||
        (c->fnumber != 400 && c->fnumber != 800 && c->fnumber != 1600) ||
        (c->focus != UINT64_MAX && c->focus < 100000)) return -ERANGE;
    if (video && (c->width < 2 || c->height < 2 ||
        c->width > FCAM_MAX_VIDEO_WIDTH || c->height > FCAM_MAX_VIDEO_HEIGHT ||
        (c->width & 1u) || (c->height & 1u))) return -ERANGE;
    return 0;
}
static optical_frame_config optical_config(const struct config *c)
{
    const optical_frame_config result = {{(double)c->fnumber / 100.0,
        c->focus == UINT64_MAX ? INFINITY : (double)c->focus / 1000000.0,
        (double)c->shutter / 1000000.0, c->iso}, c->width, c->height,
        (size_t)c->width * 3u};
    return result;
}
static int fault(struct fcam_model *m, int error)
{
    m->stream_state = 3;
    return error;
}
static int configure(struct fcam_model *m, const struct config *c)
{
    const optical_frame_config optical = optical_config(c);
    if (vcam_configure(m->still, &optical) != VCAM_OK ||
        optical_frame_configure(&m->owner, &optical) != OPTICAL_FRAME_OK)
        return fault(m, -EIO);
    m->config = *c;
    ++m->generation;
    return 0;
}
static int sensor_probe(struct fcam_model *m)
{
    if (m->sensor_initialized) return 0;
    if (m->rendered == UINT64_MAX || m->frame_generation == UINT64_MAX) return -EOVERFLOW;
    proof_begin(m, FCAM_OP_INIT);
    const optical_frame_config probe = optical_config(&defaults);
    const optical_frame_config configured = optical_config(&m->config);
    if (optical_frame_configure(&m->owner, &probe) != OPTICAL_FRAME_OK) return fault(m, -EIO);
    optical_frame_lease lease;
    optical_frame_status s = optical_frame_acquire(&m->owner, m->pool, FRAME_CAPACITY, &lease);
    optical_frame_status retired = OPTICAL_FRAME_OK;
    if (s == OPTICAL_FRAME_OK) {
        s = optical_frame_render(&m->owner, &lease);
        m->proof.render_status = s;
        if (s == OPTICAL_FRAME_OK) {
            ++m->rendered;
            ++m->frame_generation;
            proof_source(m, &lease);
        }
        retired = optical_frame_retire(&m->owner, &lease);
        m->proof.retire_status = retired;
        m->proof.retired = retired == OPTICAL_FRAME_OK;
        if (retired == OPTICAL_FRAME_OK) ++m->retired;
    }
    m->proof.final_state = m->owner.info.state;
    const optical_frame_status restored = optical_frame_configure(&m->owner, &configured);
    if (s != OPTICAL_FRAME_OK || retired != OPTICAL_FRAME_OK || restored != OPTICAL_FRAME_OK)
        return fault(m, -EIO);
    m->sensor_initialized = 1;
    return 0;
}
static void config40(const struct config *c, uint8_t out[FCAM_STARTUP_CONTROL_CONFIG_BYTES])
{
    put32(out, c->width); put32(out + 4, c->height);
    put32(out + 8, c->fps); put32(out + 12, c->quality);
    put32(out + 16, c->fnumber); put32(out + 20, c->iso);
    put64(out + 24, c->shutter); put64(out + 32, c->focus);
}
static void state(const struct fcam_model *m, uint8_t out[FCAM_STATE_BYTES])
{
    memset(out, 0, FCAM_STATE_BYTES);
    put32(out + FCAM_S_ABI, FCAM_ABI_VERSION);
    put32(out + FCAM_S_CAPS, m->caps);
    config40(&m->config, out + FCAM_STARTUP_CONTROL_STATE_CONFIG_OFFSET);
    put64(out + FCAM_S_INSTANCE, m->instance);
    put64(out + FCAM_S_GENERATION, m->generation);
    put64(out + FCAM_S_RENDERED, m->rendered);
    put64(out + FCAM_S_CONSUMED, m->consumed);
    put64(out + FCAM_S_JPEG_ENCODED, m->jpeg_encoded);
    put64(out + FCAM_S_VIDEO_ENCODED, m->video_encoded);
    put64(out + FCAM_S_RESULT_READ, m->result_read);
    put32(out + FCAM_S_PENDING_RESULTS, m->token != 0);
    put32(out + FCAM_S_STREAM_STATE, m->stream_state);
    put64(out + FCAM_S_FRAME_GENERATION, m->frame_generation);
}
static void quant_error(j_common_ptr codec)
{
    struct quant_context *q = (struct quant_context *)(void *)codec;
    q->failure = codec->err->msg_code == JERR_OUT_OF_MEMORY ? -ENOMEM : -EIO;
    longjmp(q->jump, 1);
}
static int quant_init(struct quant_context *q)
{
    q->codec.err = jpeg_std_error(&q->error);
    q->error.error_exit = quant_error;
    if (setjmp(q->jump)) return q->failure;
    jpeg_create_compress(&q->codec);
    q->live = 1;
    q->codec.input_components = 3;
    q->codec.in_color_space = JCS_RGB;
    jpeg_set_defaults(&q->codec);
    return 0;
}
static int quant_tables(struct quant_context *q, unsigned quality, uint8_t tables[2][64])
{
    static const uint8_t zigzag[64] = {
        0,1,8,16,9,2,3,10,17,24,32,25,18,11,4,5,
        12,19,26,33,40,48,41,34,27,20,13,6,7,14,21,28,
        35,42,49,56,57,50,43,36,29,22,15,23,30,37,44,51,
        58,59,52,45,38,31,39,46,53,60,61,54,47,55,62,63};
    if (setjmp(q->jump)) return q->failure;
    jpeg_set_quality(&q->codec, (int)quality, TRUE);
    for (size_t t = 0; t < 2; ++t)
        for (size_t z = 0; z < 64; ++z)
            tables[t][z] = (uint8_t)q->codec.quant_tbl_ptrs[t]->quantval[zigzag[z]];
    return 0;
}
static void discard(struct fcam_model *m)
{
    free(m->result_data);
    m->result_data = NULL;
    m->result_size = m->result_cursor = 0;
    m->token = m->result_hash = 0;
}
static int stage(struct fcam_model *m)
{
    m->result_data = malloc(FCAM_MAX_RESULT_BYTES);
    if (!m->result_data) return -ENOMEM;
    m->result_size = m->result_cursor = m->last_packet = 0;
    return 0;
}
static int publish(struct fcam_model *m, uint8_t *out, size_t capacity,
                   struct fcam_exec_result *r)
{
    if (!m->result_size || m->result_size > FCAM_MAX_RESULT_BYTES) {
        discard(m);
        return fault(m, -EIO);
    }
    const size_t used = capacity < m->result_size ? capacity : m->result_size;
    m->token = ++m->next_token;
    m->result_hash = fnv(m->result_data, m->result_size);
    memcpy(out, m->result_data, used);
    m->result_cursor = used;
    m->result_read += used;
    *r = (struct fcam_exec_result){m->token, m->result_size, 0, used};
    return 0;
}
static size_t start_code(const uint8_t *p, size_t size)
{
    if (size >= 3 && p[0] == 0 && p[1] == 0 && p[2] == 1) return 3;
    if (size >= 4 && p[0] == 0 && p[1] == 0 && p[2] == 0 && p[3] == 1) return 4;
    return 0;
}
static size_t parameter_sets(const uint8_t *p, size_t size, uint8_t *out)
{
    size_t offset = 0, used = 0;
    unsigned seen = 0;
    while (offset < size) {
        const size_t prefix = start_code(p + offset, size - offset), begin = offset;
        if (!prefix || prefix == size - offset) return 0;
        offset += prefix;
        if (p[offset] & 0x80u) return 0;
        const unsigned type = p[offset] & 31u;
        while (offset < size && !start_code(p + offset, size - offset)) ++offset;
        if (type == 7 || type == 8) {
            const unsigned bit = type == 7 ? 1u : 2u;
            if (!(seen & bit)) {
                if (out) memcpy(out + used, p + begin, offset - begin);
                used += offset - begin;
                seen |= bit;
            }
        }
    }
    return seen == 3 ? used : 0;
}
static void packet_header(const struct fcam_model *m, uint8_t *out,
                           const struct video_engine_stream_packet *packet)
{
    memset(out, 0, FCAM_PACKET_HEADER_BYTES);
    put32(out, m->config.width);
    put32(out + 4, m->config.height);
    put64(out + 8, (uint64_t)packet->pts);
    put64(out + 16, (uint64_t)packet->dts);
    put64(out + 24, (uint64_t)packet->duration);
    put32(out + 32, 1);
    put32(out + 36, m->config.fps);
    put32(out + 40, packet->keyframe != 0);
    put64(out + 48, packet->size);
    put64(out + 56, m->packet_generation);
    put32(out + 64, (uint32_t)m->video_config_size);
    put32(out + 68, FCAM_CODEC_AVC1);
}
static int packet_sink(const struct video_engine_stream_packet *packet, void *opaque)
{
    struct fcam_model *m = opaque;
    if (packet && packet->data && packet->size && m->proof.serial &&
        (m->proof.consumer_kind == FCAM_PROOF_H264 || m->proof.consumer_kind == FCAM_PROOF_DRAIN)) {
        if (packet->size > UINT64_MAX - m->proof.encoded_bytes) return -EOVERFLOW;
        m->proof.encoded_bytes += packet->size;
        m->proof.encoded_fnv1a64 = fnv_update(m->proof.encoded_fnv1a64, packet->data, packet->size);
        m->proof.packet_generation = m->packet_generation;
    }
    if (!m->result_data || !packet || !packet->size || !packet->data ||
        !start_code(packet->data, packet->size)) return -EIO;
    if (!m->video_config_size) {
        const size_t size = parameter_sets(packet->data, packet->size, NULL);
        if (!packet->keyframe || !size || size > CONFIG_LIMIT) return -EIO;
        uint8_t *copy = malloc(size);
        if (!copy) return -ENOMEM;
        (void)parameter_sets(packet->data, packet->size, copy);
        m->video_config = copy;
        m->video_config_size = size;
    }
    const size_t header = FCAM_PACKET_HEADER_BYTES + m->video_config_size;
    if (header > FCAM_MAX_RESULT_BYTES - m->result_size ||
        packet->size > FCAM_MAX_RESULT_BYTES - m->result_size - header) return -E2BIG;
    uint8_t *out = m->result_data + m->result_size;
    packet_header(m, out, packet);
    memcpy(out + FCAM_PACKET_HEADER_BYTES, m->video_config, m->video_config_size);
    memcpy(out + header, packet->data, packet->size);
    if (memcmp(out + header, packet->data, packet->size)) return -EIO;
    m->last_packet = m->result_size;
    m->result_size += header + packet->size;
    return 0;
}
static int startup_input_current(const struct fcam_model *m, const uint8_t *input)
{
    uint8_t current[FCAM_STARTUP_CONTROL_CONFIG_BYTES];
    config40(&m->config, current);
    return fcam_startup_control_validate_basic(input) &&
        get64(input + FCAM_STARTUP_CONTROL_I_CONFIG_FNV) == fnv(current, sizeof current);
}
static uint64_t startup_seal(const struct fcam_model *m, size_t slot, const uint8_t *bank, uint64_t generation)
{
    uint8_t binding[24];
    put64(binding, m->instance); put64(binding + 8, m->lifetime); put64(binding + 16, generation);
    uint64_t hash = fnv_update(fnv(bank, FCAM_STARTUP_CONTROL_INPUT_BYTES), binding, sizeof binding);
    if (slot) hash = fnv_update(hash, m->settings_snapshot40, sizeof m->settings_snapshot40);
    return hash;
}
static int startup_domain(const struct fcam_model *m)
{
    static const uint8_t zero[FCAM_STARTUP_CONTROL_CONFIG_BYTES] = {0};
    for (size_t slot = 0; slot < 2; ++slot) {
        const uint8_t *bank = slot ? m->setting_bank32 : m->mode_bank32;
        const int valid = slot ? m->setting_valid : m->mode_valid;
        const uint64_t generation = m->startup_saved_generation[slot];
        if (!valid) {
            if (memcmp(bank, zero, FCAM_STARTUP_CONTROL_INPUT_BYTES) || generation ||
                m->startup_saved_seal[slot] || (slot && memcmp(m->settings_snapshot40, zero, sizeof zero))) return 0;
        } else if (valid != 1 || !fcam_startup_control_validate_basic(bank) ||
            get16(bank) != (slot ? FCAM_STARTUP_CONTROL_CMD_SETTINGS : FCAM_STARTUP_CONTROL_CMD_MODE) ||
            !generation || generation > m->generation ||
            m->startup_saved_seal[slot] != startup_seal(m, slot, bank, generation) ||
            (slot && fnv(m->settings_snapshot40, sizeof m->settings_snapshot40) !=
                get64(bank + FCAM_STARTUP_CONTROL_I_CONFIG_FNV))) return 0;
    }
    return 1;
}
static int still_format_domain(const struct fcam_model *m)
{
    static const uint8_t unset[FCAM_STILL_FORMAT_INPUT_BYTES] = {0};
    if (!m->still_format_valid)
        return !memcmp(m->still_format_config, unset, sizeof unset);
    return m->still_format_valid == 1 && fcam_still_format_input_valid(m->still_format_config);
}
static int consume_frame(const optical_frame_view *view, void *opaque)
{
    struct fcam_model *m = opaque;
    if (!startup_domain(m) || !still_format_domain(m) || view->format != OPTICAL_FRAME_VIRTUAL_RGB888 || view->pixels != m->pool ||
        view->generation != m->owner.info.generation) return -EIO;
    const struct video_engine_rgb rgb = {view->pixels, view->size, view->stride};
    m->proof.consumer_entered = 1;
    m->proof.consumer_before_state = m->owner.info.state;
    m->proof.consumer_before_fnv1a64 = active_hash(rgb.data, view->width, view->height, rgb.stride);
    const struct video_engine_stream_info before = video_engine_stream_snapshot(m->video);
    m->video_status = video_engine_stream_feed_rgb888(m->video, &rgb,
                                                     (int64_t)before.frames_consumed, 1);
    const struct video_engine_stream_info after = video_engine_stream_snapshot(m->video);
    m->proof.consumer_returned = 1;
    m->proof.consumer_status = m->video_status;
    m->proof.consumer_after_state = m->owner.info.state;
    m->proof.consumer_after_fnv1a64 = active_hash(rgb.data, view->width, view->height, rgb.stride);
    m->proof.encoder_consumed = after.frames_consumed - before.frames_consumed;
    m->consumed += after.frames_consumed - before.frames_consumed;
    m->video_encoded += after.packets_received - before.packets_received;
    return m->video_status == VIDEO_ENGINE_OK ? 0 : -EIO;
}
static int video_frame(struct fcam_model *m)
{
    optical_frame_lease lease;
    optical_frame_status s = optical_frame_acquire(&m->owner, m->pool, FRAME_CAPACITY, &lease);
    if (s != OPTICAL_FRAME_OK) {
        m->proof.final_state = m->owner.info.state;
        return fault(m, -EIO);
    }
    s = optical_frame_render(&m->owner, &lease);
    m->proof.render_status = s;
    if (s == OPTICAL_FRAME_OK) {
        ++m->rendered;
        m->packet_generation = ++m->frame_generation;
        proof_source(m, &lease);
        s = optical_frame_consumer_read(&m->owner, &lease, consume_frame, m);
    }
    const optical_frame_status retired = optical_frame_retire(&m->owner, &lease);
    m->proof.retire_status = retired;
    m->proof.retired = retired == OPTICAL_FRAME_OK;
    m->proof.final_state = m->owner.info.state;
    if (retired == OPTICAL_FRAME_OK) ++m->retired;
    if (s != OPTICAL_FRAME_OK || retired != OPTICAL_FRAME_OK) return fault(m, -EIO);
    return 0;
}
static int bb_slot(uint16_t command)
{
    switch (command) {
    case FCAM_BB_CMD_0111: return 0;
    case FCAM_BB_CMD_0166: return 1;
    case FCAM_BB_CMD_0167: return 2;
    case FCAM_BB_CMD_015F: return 3;
    case FCAM_BB_CMD_0128: return 4;
    default: return -1;
    }
}
static int bb_period(uint32_t period)
{
    static const uint32_t periods[] = {60,50,40,30,20,10,9,8,7,6,5,4,3,2,1};
    for (size_t i = 0; i < sizeof(periods) / sizeof(periods[0]); ++i)
        if (period == periods[i]) return 1;
    return 0;
}
static int bb_validate(const uint8_t *in)
{
    static const uint16_t body_bytes[FCAM_BB_FEATURES] = {28,28,2,4,12};
    const int slot = bb_slot(get16(in));
    if (slot < 0) return -ENOTSUP;
    const size_t bytes = body_bytes[slot];
    if (get16(in + 2) != bytes) return -EINVAL;
    const uint8_t *body = in + FCAM_BB_I_BODY;
    for (size_t i = bytes; i < 28; ++i) if (body[i]) return -EINVAL;
    /* shortcut: only the declared idle/identity policies exist; extend after an explicit nonneutral model. */
    switch (slot) {
    case 0:
        if (body[0] || body[1] || body[2] != 15 || body[3] != 2) return -ENOTSUP;
        for (size_t i = 4; i < 28; ++i) if (body[i]) return -ENOTSUP;
        break;
    case 1:
        if (!fcam_bb_0166_body_valid(body)) return -ENOTSUP;
        break;
    case 2:
        if (get16(body) > 1) return -ENOTSUP;
        break;
    case 3:
        if (get32(body)) return -ENOTSUP;
        break;
    case 4:
        if (body[0] || body[1] != 1 || body[2] || body[3] || !bb_period(get32(body + 4)) ||
            get32(body + 8)) return -ENOTSUP;
        break;
    default: return -ENOTSUP;
    }
    return 0;
}
static struct bb_policy bb_apply(const struct bb_policy *current, int slot, const uint8_t *input)
{
    struct bb_policy applied = *current;
    const uint8_t *body = input + FCAM_BB_I_BODY;
    switch (slot) {
    case 0:
        applied.sq_mode = body[4]; applied.sq_rate = get32(body + 8);
        applied.sq_aux12 = body[12]; applied.sq_aux16 = get32(body + 16);
        applied.sq_aux20 = get32(body + 20); applied.sq_aux24 = body[24];
        break;
    case 1:
        applied.look[0] = body[0]; applied.look[1] = body[1];
        for (size_t i = 0; i < 6; ++i) applied.look[i + 2] = get32(body + 4 + i * 4u);
        break;
    case 2: applied.input_tag = body[0]; break;
    case 3:
        /* Source015f zero means keep-current, independently of Config48 ISO. */
        if (get32(body)) applied.gain_tag = get32(body);
        break;
    case 4:
        applied.interval_enabled = body[0]; applied.interval_mode = body[1];
        applied.interval_period = get32(body + 4);
        applied.delay_enabled = body[8]; applied.delay_tag = body[9];
        break;
    }
    return applied;
}
static int bb_identity(const struct bb_policy *policy)
{
    if (policy->sq_mode || policy->sq_rate || policy->sq_aux12 || policy->sq_aux16 ||
        policy->sq_aux20 || policy->sq_aux24 || policy->look[0] || policy->look[1] > 1 ||
        policy->input_tag > 1 || policy->gain_tag || policy->interval_enabled ||
        policy->interval_mode > 1 || policy->delay_enabled || policy->delay_tag ||
        (policy->interval_period && !bb_period(policy->interval_period))) return 0;
    static const uint32_t unset_look[8] = {0};
    if (memcmp(policy->look, unset_look, sizeof unset_look) && !fcam_bb_0166_identity(policy->look)) return 0;
    /* The exact initial look and both opaque input tags select RGB identity; interval/SQ are idle. */
    return 1;
}
static int vdf_copy(const optical_frame_view *view, void *opaque)
{
    struct fcam_model *m = opaque;
    const optical_frame_config *c = &m->owner.info.config;
    if (!view || view->format != OPTICAL_FRAME_VIRTUAL_RGB888 || view->pixels != m->pool ||
        !view->generation || view->generation != m->owner.info.generation ||
        m->owner.info.state != OPTICAL_FRAME_READING ||
        !view->width || view->width > SIZE_MAX / 3u || !view->height ||
        view->stride < view->width * 3u || view->height > SIZE_MAX / view->stride ||
        view->size != view->stride * view->height || view->size > FRAME_CAPACITY ||
        view->width != c->width || view->height != c->height || view->stride != c->stride ||
        !m->vdf_sink || m->vdf_capacity > FRAME_CAPACITY || m->vdf_copied ||
        !valid_span((struct span){m->vdf_sink, m->vdf_capacity}) ||
        overlap((struct span){m->vdf_sink, m->vdf_capacity}, (struct span){m->pool, FRAME_CAPACITY}) ||
        overlap((struct span){m->vdf_sink, m->vdf_capacity}, (struct span){m, sizeof(*m)})) return -EINVAL;
    if (!startup_domain(m) ||
        (m->proof.opcode == FCAM_OP_STARTUP_CONTROL &&
         (m->startup_slot > 1 || !startup_input_current(m, m->startup_staged[m->startup_slot]) ||
          (m->startup_slot && fnv(m->settings_staged40, sizeof m->settings_staged40) !=
              get64(m->startup_staged[1] + FCAM_STARTUP_CONTROL_I_CONFIG_FNV))))) return -EINVAL;
    if (!still_format_domain(m) ||
        (m->proof.opcode == FCAM_OP_STILL_FORMAT &&
         !fcam_still_format_input_valid(m->still_format_staged))) return -EINVAL;
    /* The saved software bus domain constrains every subsequent actual VDF consumer. */
    if ((m->bit_width_valid && !fcam_bit_width_input_valid(m->bit_width_config)) ||
        (m->proof.opcode == FCAM_OP_VDF_BIT_WIDTH &&
         !fcam_bit_width_input_valid(m->bit_width_staged))) return -EINVAL;
    if ((m->proof.opcode == FCAM_OP_BB_STARTUP_CONFIG && !bb_identity(&m->bb_staged_policy)) ||
        (m->proof.opcode == FCAM_OP_HISTOGRAM && !bb_identity(&m->bb_applied))) return -EINVAL;
    if (m->proof.opcode == FCAM_OP_VDF_LAYOUT &&
        (memcmp(m->layout_staged, layout_case0, sizeof(layout_case0)) ||
         view->width != get16(m->layout_staged + 8) ||
         view->height != get16(m->layout_staged + 10))) return -EINVAL;
    m->proof.consumer_entered = 1;
    m->proof.consumer_before_state = m->owner.info.state;
    m->proof.consumer_before_fnv1a64 = active_hash(view->pixels, view->width, view->height, view->stride);
    const size_t row = view->width * 3u;
    int error = 0;
    for (size_t y = 0; y < view->height; ++y) {
        if (row > m->vdf_capacity - m->vdf_copied) { error = -ENOSPC; break; }
        memcpy(m->vdf_sink + m->vdf_copied, view->pixels + y * view->stride, row);
        m->vdf_copied += row;
        if (memcmp(m->vdf_sink + y * row, view->pixels + y * view->stride, row)) {
            error = -EIO;
            break;
        }
    }
    m->proof.consumer_after_fnv1a64 = fnv(m->vdf_sink, m->vdf_copied);
    m->proof.consumer_after_state = m->owner.info.state;
    m->proof.consumer_returned = 1;
    return error;
}
static int vdf_frame(struct fcam_model *m)
{
    optical_frame_lease lease;
    optical_frame_status s = optical_frame_acquire(&m->owner, m->pool, FRAME_CAPACITY, &lease);
    if (s != OPTICAL_FRAME_OK) {
        m->proof.final_state = m->owner.info.state;
        return fault(m, -EIO);
    }
    m->proof.lease_generation = lease.generation;
    s = optical_frame_render(&m->owner, &lease);
    m->proof.render_status = s;
    int copied = 0;
    if (s == OPTICAL_FRAME_OK) {
        ++m->rendered;
        if (m->proof.opcode != FCAM_OP_VDF_LAYOUT &&
            m->proof.opcode != FCAM_OP_VDF_DISPLAY_CONFIG &&
            m->proof.opcode != FCAM_OP_VDF_BIT_WIDTH &&
            m->proof.opcode != FCAM_OP_STILL_FORMAT &&
            m->proof.opcode != FCAM_OP_STARTUP_CONTROL &&
            m->proof.opcode != FCAM_OP_BB_STARTUP_CONFIG &&
            m->proof.opcode != FCAM_OP_HISTOGRAM) ++m->frame_generation;
        proof_source(m, &lease);
        m->vdf_copied = 0;
        s = optical_frame_consumer_read(&m->owner, &lease, vdf_copy, m);
        m->proof.consumer_status = s;
        if (m->vdf_copied) m->proof.consumer_after_fnv1a64 = fnv(m->vdf_sink, m->vdf_copied);
        copied = s == OPTICAL_FRAME_OK && lease.generation && m->proof.active_bytes &&
            m->proof.consumer_entered && m->proof.consumer_returned &&
            m->vdf_copied == m->proof.active_bytes &&
            m->proof.source_fnv1a64 == m->proof.consumer_before_fnv1a64 &&
            m->proof.source_fnv1a64 == m->proof.consumer_after_fnv1a64;
        const size_t row = m->owner.info.config.width * 3u;
        for (size_t y = 0; copied && y < m->owner.info.config.height; ++y)
            if (memcmp(m->pool + y * m->owner.info.config.stride, m->vdf_sink + y * row, row)) copied = 0;
        if (copied) ++m->consumed;
    }
    const optical_frame_status retired = optical_frame_retire(&m->owner, &lease);
    m->proof.retire_status = retired;
    m->proof.retired = retired == OPTICAL_FRAME_OK;
    m->proof.final_state = m->owner.info.state;
    if (retired == OPTICAL_FRAME_OK) ++m->retired;
    return s == OPTICAL_FRAME_OK && copied && retired == OPTICAL_FRAME_OK &&
        m->owner.info.state == OPTICAL_FRAME_IDLE ? 0 : fault(m, -EIO);
}
static void vdf_receipt(const struct fcam_model *m, uint8_t *response, size_t response_bytes,
                         const uint8_t *canonical, size_t input_bytes, int enabled,
                         uint32_t receipt_class, uint64_t before_frame, uint64_t before_config)
{
    put32(response + FCAM_VDF_R_ABI, FCAM_ABI_VERSION);
    put32(response + FCAM_VDF_R_BYTES, (uint32_t)response_bytes);
    put64(response + FCAM_VDF_R_INSTANCE, m->instance);
    put64(response + FCAM_VDF_R_CONFIG_GENERATION, m->generation);
    put64(response + FCAM_VDF_R_FRAME_GENERATION, m->frame_generation);
    put64(response + FCAM_VDF_R_LEASE_GENERATION, enabled ? m->owner.info.generation : 0);
    put64(response + FCAM_VDF_R_INPUT_FNV, fnv(canonical, input_bytes));
    put64(response + FCAM_VDF_R_SOURCE_FNV, m->proof.source_fnv1a64);
    put64(response + FCAM_VDF_R_SINK_FNV, m->proof.consumer_after_fnv1a64);
    put64(response + FCAM_VDF_R_ACTIVE_BYTES, m->proof.active_bytes);
    put32(response + FCAM_VDF_R_WIDTH, m->config.width);
    put32(response + FCAM_VDF_R_HEIGHT, m->config.height);
    put32(response + FCAM_VDF_R_STRIDE, m->config.width * 3u);
    put32(response + FCAM_VDF_R_ENDPOINT, FCAM_VDF_ENDPOINT);
    put32(response + FCAM_VDF_R_SELECTED_MASK, FCAM_VDF_MASK);
    put32(response + FCAM_VDF_R_COMPLETED_MASK, FCAM_VDF_MASK);
    put32(response + FCAM_VDF_R_CLASS, receipt_class);
    put32(response + FCAM_VDF_R_ENABLED, (uint32_t)enabled);
    put32(response + FCAM_VDF_R_CONFIG_READBACK, 1);
    put32(response + FCAM_VDF_R_COMMITTED, 1);
    put32(response + FCAM_VDF_R_FRAME_CONSUMED, (uint32_t)enabled);
    put32(response + FCAM_VDF_R_RETIRED, (uint32_t)enabled);
    memcpy(response + FCAM_VDF_R_CONFIG, m->vdf_config, sizeof(m->vdf_config));
    put64(response + FCAM_VDF_R_BEFORE_FRAME_GENERATION, before_frame);
    put64(response + FCAM_VDF_R_BEFORE_CONFIG_GENERATION, before_config);
}
static int histogram(const uint8_t *rgb, size_t bytes, uint8_t bins[FCAM_HIST_BINS_BYTES])
{
    if (!rgb || !bytes || bytes % 3u || bytes > FRAME_CAPACITY) return -EINVAL;
    uint64_t counts[4][FCAM_HIST_CHANNEL_BINS] = {{0}};
    for (size_t i = 0; i < bytes; i += 3) {
        const unsigned r = rgb[i], g = rgb[i + 1], b = rgb[i + 2];
        const unsigned y = (77u * r + 150u * g + 29u * b + 128u) >> 8;
        ++counts[0][y]; ++counts[1][r]; ++counts[2][g]; ++counts[3][b];
    }
    for (size_t channel = 0; channel < 4; ++channel) {
        uint64_t peak = 0;
        for (size_t i = 0; i < FCAM_HIST_CHANNEL_BINS; ++i)
            if (counts[channel][i] > peak) peak = counts[channel][i];
        if (!peak) return -ENODATA;
        for (size_t i = 0; i < FCAM_HIST_CHANNEL_BINS; ++i)
            bins[channel * FCAM_HIST_CHANNEL_BINS + i] =
                (uint8_t)((counts[channel][i] * 255u + peak / 2u) / peak);
    }
    return 0;
}
static int bb_transaction(struct fcam_model *m, uint32_t op, const uint8_t *input, uint8_t *out,
                           struct fcam_exec_result *result)
{
    const int hist = op == FCAM_OP_HISTOGRAM;
    const int slot = hist ? 0 : bb_slot(get16(input));
    const size_t input_bytes = hist ? FCAM_HIST_INPUT_BYTES : FCAM_BB_INPUT_BYTES;
    const size_t response_bytes = hist ? FCAM_HIST_RESULT_BYTES : FCAM_BB_RESULT_BYTES;
    uint8_t *staged = hist ? m->hist_staged : m->bb_staged[slot];
    uint8_t *committed = hist ? m->hist_config : m->bb_config[slot];
    uint8_t *cache = hist ? m->hist_result : m->bb_result;
    uint8_t canonical[FCAM_BB_INPUT_BYTES] = {0}, previous[FCAM_BB_INPUT_BYTES] = {0};
    uint8_t response[FCAM_HIST_RESULT_BYTES] = {0}, readback[FCAM_HIST_RESULT_BYTES];
    uint8_t previous_result[FCAM_HIST_RESULT_BYTES];
    memcpy(canonical, input, input_bytes);
    memcpy(previous, committed, input_bytes);
    memcpy(previous_result, cache, response_bytes);
    const struct bb_policy applied = hist ? m->bb_applied : bb_apply(&m->bb_applied, slot, canonical);
    const uint64_t before_frame = m->frame_generation, before_config = m->generation;
    const size_t bytes = (size_t)m->config.width * m->config.height * 3u;
    if (bytes > m->vdf_capacity) {
        uint8_t *sink = malloc(bytes);
        if (!sink) return -ENOMEM;
        free(m->vdf_sink);
        m->vdf_sink = sink;
        m->vdf_capacity = bytes;
    }
    proof_begin(m, op);
    m->vdf_busy = 1;
    m->vdf_copied = 0;
    memcpy(staged, canonical, input_bytes);
    memcpy(readback, staged, input_bytes);
    if (memcmp(readback, canonical, input_bytes)) return fault(m, -EIO);
    if (!hist) m->bb_staged_policy = applied;
    const optical_frame_config optical = optical_config(&m->config);
    optical_frame_info actual;
    if (optical_frame_configure(&m->owner, &optical) != OPTICAL_FRAME_OK ||
        optical_frame_snapshot(&m->owner, &actual) != OPTICAL_FRAME_OK || !actual.configured ||
        actual.config.width != optical.width || actual.config.height != optical.height ||
        actual.config.stride != optical.stride ||
        actual.config.params.f_number != optical.params.f_number ||
        actual.config.params.focus_m != optical.params.focus_m ||
        actual.config.params.shutter_s != optical.params.shutter_s ||
        actual.config.params.iso != optical.params.iso) return fault(m, -EIO);
    const int error = vdf_frame(m);
    if (error) {
        if (hist) m->bb_applied = applied;
        return error;
    }
    m->proof.consumer_after_fnv1a64 = fnv(m->vdf_sink, m->vdf_copied);
    if (m->vdf_copied != bytes || bytes != m->proof.active_bytes ||
        m->proof.consumer_after_fnv1a64 != m->proof.source_fnv1a64 || memcmp(m->pool, m->vdf_sink, bytes) ||
        memcmp(staged, canonical, input_bytes) ||
        memcmp(hist ? &m->bb_applied : &m->bb_staged_policy, &applied, sizeof(applied))) {
        if (hist) m->bb_applied = applied;
        return fault(m, -EIO);
    }
    vdf_receipt(m, response, response_bytes, canonical, input_bytes, 1,
                hist ? FCAM_HIST_CLASS : FCAM_BB_CLASS, before_frame, before_config);
    put64(response + FCAM_VDF_R_CONFIG_GENERATION, before_config + 1);
    put64(response + FCAM_VDF_R_FRAME_GENERATION, before_frame + 1);
    memcpy(response + FCAM_BB_R_CONFIG, canonical, input_bytes);
    if (hist && histogram(m->vdf_sink, bytes, response + FCAM_HIST_R_BINS)) return fault(m, -EIO);
    if (fnv(m->vdf_sink, bytes) != m->proof.source_fnv1a64) return fault(m, -EIO);
    memcpy(committed, staged, input_bytes);
    memcpy(readback, committed, input_bytes);
    if (memcmp(readback, canonical, input_bytes)) {
        memcpy(committed, previous, input_bytes);
        return fault(m, -EIO);
    }
    memcpy(cache, response, response_bytes);
    memcpy(readback, cache, response_bytes);
    if (memcmp(readback, response, response_bytes)) {
        memcpy(committed, previous, input_bytes);
        memcpy(cache, previous_result, response_bytes);
        return fault(m, -EIO);
    }
    if (hist) m->hist_valid = 1;
    else { m->bb_applied = applied; m->bb_valid[slot] = 1; }
    m->proof.config_generation = ++m->generation;
    m->proof.frame_generation = ++m->frame_generation;
    m->proof.result_bytes = response_bytes;
    m->proof.result_fnv1a64 = fnv(readback, response_bytes);
    m->vdf_busy = 0;
    memcpy(out, readback, response_bytes);
    *result = (struct fcam_exec_result){0, 0, 0, response_bytes};
    return 0;
}
static int vdf_transaction(struct fcam_model *m, uint32_t op, const uint8_t *input, uint8_t *out,
                            struct fcam_exec_result *result)
{
    const int zebra = op == FCAM_OP_VDF_ZEBRA, layout = op == FCAM_OP_VDF_LAYOUT;
    const int display = op == FCAM_OP_VDF_DISPLAY_CONFIG, bit_width = op == FCAM_OP_VDF_BIT_WIDTH;
    const int still_format = op == FCAM_OP_STILL_FORMAT, startup = op == FCAM_OP_STARTUP_CONTROL;
    const size_t slot = startup ? (size_t)(get16(input) == FCAM_STARTUP_CONTROL_CMD_SETTINGS) :
        display ? get32(input) == 0x0141u ? 2u : (size_t)(get32(input) == 0x0162u) : 0u;
    const size_t input_bytes = startup ? FCAM_STARTUP_CONTROL_INPUT_BYTES : still_format ? FCAM_STILL_FORMAT_INPUT_BYTES : bit_width ? FCAM_BIT_WIDTH_INPUT_BYTES :
        layout ? FCAM_LAYOUT_INPUT_BYTES : zebra ? FCAM_ZEBRA_INPUT_BYTES : display ? FCAM_DISPLAY_INPUT_BYTES : FCAM_VDF_INPUT_BYTES;
    const size_t saved_bytes = startup ? FCAM_STARTUP_CONTROL_INPUT_BYTES : still_format ? sizeof(m->still_format_config) : bit_width ? sizeof(m->bit_width_config) :
        layout ? sizeof(m->layout_config) : zebra ? sizeof(m->zebra_config) :
        display ? sizeof(m->display_config[slot]) : sizeof(m->vdf_config);
    const size_t response_bytes = startup ? FCAM_STARTUP_CONTROL_RESULT_BYTES : still_format ? FCAM_STILL_FORMAT_RESULT_BYTES : bit_width ? FCAM_BIT_WIDTH_RESULT_BYTES :
        layout ? FCAM_LAYOUT_RESULT_BYTES : zebra ? FCAM_ZEBRA_RESULT_BYTES :
        display ? FCAM_DISPLAY_RESULT_BYTES : FCAM_VDF_RESULT_BYTES;
    uint8_t *staged = startup ? m->startup_staged[slot] : still_format ? m->still_format_staged : bit_width ? m->bit_width_staged :
        layout ? m->layout_staged : zebra ? m->zebra_staged : display ? m->display_staged[slot] : m->vdf_staged;
    uint8_t *committed = startup ? (slot ? m->setting_bank32 : m->mode_bank32) : still_format ? m->still_format_config : bit_width ? m->bit_width_config :
        layout ? m->layout_config : zebra ? m->zebra_config : display ? m->display_config[slot] : m->vdf_config;
    uint8_t canonical[FCAM_LAYOUT_INPUT_BYTES] = {0}, readback[FCAM_LAYOUT_INPUT_BYTES] = {0};
    uint8_t previous[FCAM_LAYOUT_INPUT_BYTES];
    uint8_t checkpoint[FCAM_STARTUP_CONTROL_CONFIG_BYTES], checkpoint_readback[FCAM_STARTUP_CONTROL_CONFIG_BYTES];
    if (startup && slot) config40(&m->config, checkpoint);
    memcpy(canonical, input, input_bytes);
    memcpy(previous, committed, saved_bytes);
    const int enabled = startup || still_format || bit_width || layout || display || (zebra ? m->vdf_class != 0 : canonical[0] == 1);
    const uint64_t before_frame = m->frame_generation, before_config = m->generation;
    if (enabled) {
        const size_t bytes = (size_t)m->config.width * m->config.height * 3u;
        if (bytes > m->vdf_capacity) {
            uint8_t *sink = malloc(bytes);
            if (!sink) return -ENOMEM;
            free(m->vdf_sink);
            m->vdf_sink = sink;
            m->vdf_capacity = bytes;
        }
    }
    proof_begin(m, op);
    m->vdf_busy = 1;
    m->vdf_copied = 0;
    m->proof.final_state = m->owner.info.state;
    if (startup) m->startup_slot = slot;
    memcpy(staged, canonical, saved_bytes);
    memcpy(readback, staged, saved_bytes);
    if (memcmp(readback, canonical, input_bytes)) return fault(m, -EIO);
    if (startup && slot) {
        memcpy(m->settings_staged40, checkpoint, sizeof checkpoint);
        memcpy(checkpoint_readback, m->settings_staged40, sizeof checkpoint_readback);
        if (memcmp(checkpoint_readback, checkpoint, sizeof checkpoint) ||
            fnv(checkpoint_readback, sizeof checkpoint_readback) != get64(canonical + FCAM_STARTUP_CONTROL_I_CONFIG_FNV))
            return fault(m, -EIO);
    }
    if (enabled) {
        const optical_frame_config optical = optical_config(&m->config);
        optical_frame_info actual;
        if (optical_frame_configure(&m->owner, &optical) != OPTICAL_FRAME_OK ||
            optical_frame_snapshot(&m->owner, &actual) != OPTICAL_FRAME_OK || !actual.configured ||
            actual.config.width != optical.width || actual.config.height != optical.height ||
            actual.config.stride != optical.stride ||
            actual.config.params.f_number != optical.params.f_number ||
            actual.config.params.focus_m != optical.params.focus_m ||
            actual.config.params.shutter_s != optical.params.shutter_s ||
            actual.config.params.iso != optical.params.iso) return fault(m, -EIO);
        const int error = vdf_frame(m);
        if (error) return error;
    }
    if (bit_width || still_format || startup) {
        const size_t bytes = (size_t)m->config.width * m->config.height * 3u;
        m->proof.consumer_after_fnv1a64 = fnv(m->vdf_sink, m->vdf_copied);
        if (m->vdf_copied != bytes || bytes != m->proof.active_bytes ||
            m->proof.consumer_after_fnv1a64 != m->proof.source_fnv1a64 ||
            memcmp(m->pool, m->vdf_sink, bytes)) return fault(m, -EIO);
    }
    if (memcmp(staged, canonical, saved_bytes)) return fault(m, -EIO);
    if (startup && slot) {
        if (memcmp(m->settings_staged40, checkpoint, sizeof checkpoint)) return fault(m, -EIO);
        memcpy(m->settings_snapshot40, m->settings_staged40, sizeof m->settings_snapshot40);
        memcpy(checkpoint_readback, m->settings_snapshot40, sizeof checkpoint_readback);
        if (memcmp(checkpoint_readback, checkpoint, sizeof checkpoint) ||
            fnv(checkpoint_readback, sizeof checkpoint_readback) != get64(canonical + FCAM_STARTUP_CONTROL_I_CONFIG_FNV))
            return fault(m, -EIO);
    }
    memcpy(committed, staged, saved_bytes);
    memcpy(readback, committed, saved_bytes);
    if (memcmp(readback, canonical, input_bytes) ||
        (startup && fnv(readback, input_bytes) != fnv(canonical, input_bytes))) {
        memcpy(committed, previous, saved_bytes);
        return fault(m, -EIO);
    }
    if (layout || display || bit_width || still_format || startup) {
        if (startup) {
            if (slot) m->setting_valid = 1; else m->mode_valid = 1;
            m->startup_saved_generation[slot] = before_config + 1;
            m->startup_saved_seal[slot] = startup_seal(m, slot, committed, before_config + 1);
        }
        if (layout) m->layout_valid = 1;
        if (bit_width) m->bit_width_valid = 1;
        if (still_format) m->still_format_valid = 1;
        m->proof.frame_generation = ++m->frame_generation;
    } else if (!zebra) m->vdf_class = (uint32_t)enabled;
    m->vdf_busy = 0;
    ++m->generation;
    m->proof.config_generation = m->generation;
    uint8_t response[FCAM_VDF_RESULT_MAX_BYTES] = {0};
    vdf_receipt(m, response, response_bytes, canonical, input_bytes, enabled,
                startup ? FCAM_STARTUP_CONTROL_CLASS : still_format ? FCAM_STILL_FORMAT_CLASS : bit_width ? FCAM_BIT_WIDTH_CLASS : m->vdf_class,
                before_frame, before_config);
    if (zebra) memcpy(response + FCAM_ZEBRA_R_CONFIG, readback, FCAM_ZEBRA_INPUT_BYTES);
    if (layout) memcpy(response + FCAM_LAYOUT_R_CONFIG, readback, FCAM_LAYOUT_INPUT_BYTES);
    if (display) memcpy(response + FCAM_DISPLAY_R_CONFIG, readback, FCAM_DISPLAY_INPUT_BYTES);
    if (bit_width || still_format || startup) {
        memcpy(response + FCAM_STILL_FORMAT_R_CONFIG, readback, input_bytes);
        m->proof.result_bytes = response_bytes;
        m->proof.result_fnv1a64 = fnv(response, response_bytes);
    }
    memcpy(out, response, response_bytes);
    *result = (struct fcam_exec_result){0, 0, 0, response_bytes};
    return 0;
}
static int still_frame(struct fcam_model *m, const uint8_t *input)
{
    if (!startup_domain(m) || !still_format_domain(m)) return fault(m, -EIO);
    const uint32_t flags = get32(input);
    struct vjpeg_coding coding = {VJPEG_SOURCE_HEADER_422,
                                 get32(input + 4), get32(input + 8), {{0}}};
    if (flags & FCAM_STILL_HAS_QUANT) memcpy(coding.quant_zigzag, input + 16, 128);
    else {
        const int error = quant_tables(&m->quant, get32(input + 12), coding.quant_zigzag);
        if (error) return fault(m, error);
    }
    optical_frame_config optical = optical_config(&m->config);
    optical.width = coding.width;
    optical.height = coding.height;
    optical.stride = (size_t)coding.width * 3u;
    if (vcam_configure(m->still, &optical) != VCAM_OK) return fault(m, -EIO);
    const struct vcam_info before = vcam_snapshot(m->still);
    const uint64_t previous_proof = vcam_frame_proof_snapshot(m->still).serial;
    struct vcam_still_result captured;
    const enum vcam_status captured_status = vcam_capture_still(m->still, &coding,
        m->result_data, FCAM_MAX_RESULT_BYTES, &captured);
    const struct vcam_info after = vcam_snapshot(m->still);
    const uint64_t rendered = after.counts.rendered - before.counts.rendered;
    m->rendered += rendered;
    m->frame_generation += rendered;
    m->consumed += after.counts.encoder_consumed - before.counts.encoder_consumed;
    m->jpeg_encoded += after.counts.output_readback - before.counts.output_readback;
    m->retired += after.counts.retired - before.counts.retired;
    const struct vcam_frame_proof observed = vcam_frame_proof_snapshot(m->still);
    if (observed.serial != previous_proof) {
        m->proof.frame_generation = m->frame_generation;
        m->proof.lease_generation = observed.lease_generation;
        m->proof.width = observed.width;
        m->proof.height = observed.height;
        m->proof.stride = observed.stride;
        m->proof.active_bytes = observed.active_bytes;
        m->proof.source_fnv1a64 = observed.source_fnv1a64;
        m->proof.consumer_before_fnv1a64 = observed.consumer_before_fnv1a64;
        m->proof.consumer_after_fnv1a64 = observed.consumer_after_fnv1a64;
        m->proof.render_observed = observed.render_observed;
        m->proof.consumer_entered = observed.consumer_entered;
        m->proof.consumer_returned = observed.consumer_returned;
        m->proof.encoder_consumed = observed.encoder_consumed;
        m->proof.retired = observed.retired;
        m->proof.source_state = observed.source_state;
        m->proof.consumer_before_state = observed.consumer_before_state;
        m->proof.consumer_after_state = observed.consumer_after_state;
        m->proof.final_state = observed.final_state;
        m->proof.render_status = observed.render_status;
        m->proof.consumer_status = observed.consumer_status;
        m->proof.retire_status = observed.retire_status;
        m->proof.encoded_bytes = observed.encoded_bytes;
        m->proof.encoded_fnv1a64 = observed.encoded_fnv1a64;
    }
    optical = optical_config(&m->config);
    const enum vcam_status restored = vcam_configure(m->still, &optical);
    if (captured_status != VCAM_OK || restored != VCAM_OK) return fault(m, -EIO);
    if (flags & FCAM_STILL_SCAN_ONLY) {
        memmove(m->result_data, m->result_data + captured.prefix_length, captured.suffix_length);
        m->result_size = captured.suffix_length;
    } else m->result_size = captured.jpeg_length;
    return 0;
}
struct fcam_model *fcam_model_create(uint64_t instance)
{
    if (!instance) { errno = EINVAL; return NULL; }
    struct fcam_model *m = calloc(1, sizeof(*m));
    if (!m) return NULL;
    m->instance = instance;
    /* Explicit software endpoint initial route, independent of original CP RAM. */
    m->vdf_config[1] = m->vdf_config[2] = 1;
    memcpy(m->vdf_staged, m->vdf_config, sizeof(m->vdf_staged));
    uint64_t lifetime = atomic_load(&model_lifetimes);
    do {
        if (lifetime == UINT64_MAX) { free(m); errno = EOVERFLOW; return NULL; }
    } while (!atomic_compare_exchange_weak(&model_lifetimes, &lifetime, lifetime + 1));
    m->lifetime = lifetime + 1;
    m->owner_pid = (uint64_t)getpid();
    m->proof = (struct fcam_frame_proof){.version = FCAM_PROOF_VERSION,
        .struct_bytes = sizeof(m->proof), .model_instance = instance,
        .model_lifetime = m->lifetime, .owner_pid = m->owner_pid,
        .encoded_fnv1a64 = FNV_OFFSET, .result_fnv1a64 = FNV_OFFSET};
    m->pool = malloc(FRAME_CAPACITY);
    if (m->pool) m->still = vcam_create(m->pool, FRAME_CAPACITY, NULL);
    m->video = video_engine_stream_create();
    int error = -ENOMEM;
    if (!m->pool || !m->still || !m->video) goto failed;
    error = quant_init(&m->quant);
    if (error) goto failed;
    if (optical_frame_init(&m->owner) != OPTICAL_FRAME_OK) { error = -EIO; goto failed; }
    error = configure(m, &defaults);
    if (error) goto failed;
    m->caps = FCAM_CAP_STILL | FCAM_CAP_AF | FCAM_CAP_FIXED_OPTICS;
    if (video_engine_stream_begin(m->video, defaults.width, defaults.height,
        defaults.fps, FCAM_MAX_RESULT_BYTES - FCAM_PACKET_HEADER_BYTES - CONFIG_LIMIT,
        packet_sink, m) == VIDEO_ENGINE_OK) m->caps |= FCAM_CAP_H264;
    (void)video_engine_stream_cancel(m->video);
    return m;
failed:
    fcam_model_destroy(m);
    errno = -error;
    return NULL;
}
void fcam_model_destroy(struct fcam_model *m)
{
    if (!m || m->busy) return;
    video_engine_stream_destroy(m->video);
    if (m->still) { (void)vcam_cancel(m->still); (void)vcam_destroy(m->still); }
    if (m->quant.live || m->quant.codec.mem) jpeg_destroy_compress(&m->quant.codec);
    free(m->pool);
    free(m->result_data);
    free(m->video_config);
    free(m->vdf_sink);
    free(m);
}
static int display_validate(const uint8_t *in)
{
    const uint32_t command = get32(in), bytes = get32(in + 4);
    const uint8_t *body = in + 8;
    if (command == 0x0141u) {
        if (bytes) return -EINVAL;
        for (size_t i = 0; i < 8; ++i) if (body[i]) return -EINVAL;
        return 0;
    }
    if (command == 0x0152u) {
        static const uint8_t palettes[][3] = {{81, 90, 240}, {210, 16, 146},
                                             {29, 255, 83}, {235, 128, 128}};
        if (bytes != 8) return -EINVAL;
        /* shortcut: the enabled peaking spatial operator is unknown; require a specified policy first. */
        if (body[0] != 3 || body[1] || body[2] > 2 ||
            (body[3] != 0 && body[3] != 10 && body[3] != 40) || body[4]) return -ENOTSUP;
        for (size_t i = 0; i < sizeof(palettes) / sizeof(palettes[0]); ++i)
            if (!memcmp(body + 5, palettes[i], sizeof(palettes[i]))) return 0;
        return -ENOTSUP;
    }
    if (command == 0x0162u) {
        if (bytes != 2) return -EINVAL;
        for (size_t i = 2; i < 8; ++i) if (body[i]) return -EINVAL;
        return body[0] || body[1] ? -ENOTSUP : 0;
    }
    return -ENOTSUP;
}
static int validate_request(const struct fcam_model *m, uint32_t op,
                            const uint8_t *in, size_t size, size_t capacity)
{
    if (m->token && op != FCAM_OP_STATE && op != FCAM_OP_READ_RESULT &&
        op != FCAM_OP_RELEASE_RESULT && op != FCAM_OP_CANCEL) return -EBUSY;
    switch (op) {
    case FCAM_OP_INIT:
        if (size && size != FCAM_CONFIG_BYTES) return -EINVAL;
        break;
    case FCAM_OP_STATE: case FCAM_OP_VIDEO_FRAME: case FCAM_OP_VIDEO_END: case FCAM_OP_CANCEL:
        if (size) return -EINVAL;
        break;
    case FCAM_OP_CONFIGURE: case FCAM_OP_VIDEO_BEGIN:
        if (size != FCAM_CONFIG_BYTES) return -EINVAL;
        break;
    case FCAM_OP_VDF_PATH:
        if (size != FCAM_VDF_INPUT_BYTES || in[4] > 2 || in[13] || in[14] || in[15] ||
            !((in[0] == 1 && in[1] == 5 && in[2] == 5) ||
              (in[0] == 0 && in[1] == 1 && in[2] == 1))) return -EINVAL;
        break;
    case FCAM_OP_VDF_ZEBRA:
        if (size != FCAM_ZEBRA_INPUT_BYTES || in[5] || in[6] || in[7]) return -EINVAL;
        /* shortcut: enabled Zebra units/rendering are unknown; implement after a specified profile. */
        if (in[1]) return -ENOTSUP;
        break;
    case FCAM_OP_VDF_LAYOUT:
        if (size != FCAM_LAYOUT_INPUT_BYTES) return -EINVAL;
        if (memcmp(in, layout_case0, sizeof(layout_case0))) return -ENOTSUP;
        if (m->vdf_class != 1 || m->vdf_config[0] != 1 ||
            m->vdf_config[1] != 5 || m->vdf_config[2] != 5) return -ENODATA;
        if (m->config.width != 640 || m->config.height != 480) return -ENOTSUP;
        break;
    case FCAM_OP_VDF_DISPLAY_CONFIG: {
        if (size != FCAM_DISPLAY_INPUT_BYTES) return -EINVAL;
        const int error = display_validate(in);
        if (error) return error;
        if (m->vdf_class != 1 || m->vdf_config[0] != 1 ||
            m->vdf_config[1] != 5 || m->vdf_config[2] != 5) return -ENODATA;
        break;
    }
    case FCAM_OP_VDF_BIT_WIDTH:
        if (size != FCAM_BIT_WIDTH_INPUT_BYTES) return -EINVAL;
        for (size_t i = 1; i < FCAM_BIT_WIDTH_INPUT_BYTES; ++i) if (in[i]) return -EINVAL;
        if (in[0] != FCAM_BIT_WIDTH_SOFTWARE_RGB888_SELECTOR) return -ENOTSUP;
        if (!m->sensor_initialized || m->vdf_class != 1 || m->vdf_config[0] != 1 ||
            m->vdf_config[1] != 5 || m->vdf_config[2] != 5) return -ENODATA;
        if (m->config.width != 640 || m->config.height != 480) return -ENOTSUP;
        break;
    case FCAM_OP_STILL_FORMAT:
        if (size != FCAM_STILL_FORMAT_INPUT_BYTES) return -EINVAL;
        if (!fcam_still_format_input_valid(in)) return -ENOTSUP;
        if (!m->sensor_initialized || m->vdf_class != 1 || m->vdf_config[0] != 1 ||
            m->vdf_config[1] != 5 || m->vdf_config[2] != 5) return -ENODATA;
        if (m->config.width != 640 || m->config.height != 480) return -ENOTSUP;
        break;
    case FCAM_OP_STARTUP_CONTROL:
        if (size != FCAM_STARTUP_CONTROL_INPUT_BYTES) return -EINVAL;
        if (!fcam_startup_control_validate_basic(in)) return -ENOTSUP;
        if (!m->sensor_initialized || m->vdf_class != 1 || m->vdf_config[0] != 1 ||
            m->vdf_config[1] != 5 || m->vdf_config[2] != 5) return -ENODATA;
        if (m->config.width != 640 || m->config.height != 480) return -ENOTSUP;
        if (!startup_input_current(m, in)) return -ESTALE;
        break;
    case FCAM_OP_BB_STARTUP_CONFIG:
    case FCAM_OP_HISTOGRAM: {
        if (op == FCAM_OP_BB_STARTUP_CONFIG) {
            if (size != FCAM_BB_INPUT_BYTES) return -EINVAL;
            const int error = bb_validate(in);
            if (error) return error;
        } else {
            if (size != FCAM_HIST_INPUT_BYTES || get16(in + 2) != 4 || in[7]) return -EINVAL;
            if (get16(in) != FCAM_HIST_COMMAND || in[4] != 1 || in[5] != 1 || in[6]) return -ENOTSUP;
        }
        if (m->vdf_class != 1 || m->vdf_config[0] != 1 ||
            m->vdf_config[1] != 5 || m->vdf_config[2] != 5) return -ENODATA;
        if (m->config.width != 640 || m->config.height != 480) return -ENOTSUP;
        break;
    }
    case FCAM_OP_AUTOFOCUS:
        if (size != FCAM_AF_BYTES) return -EINVAL;
        break;
    case FCAM_OP_STILL: {
        if (size != 16 && size != 144) return -EINVAL;
        const uint32_t flags = get32(in), kind = flags & 3u;
        if ((flags & ~7u) || (kind != FCAM_STILL_FULL_JPEG && kind != FCAM_STILL_SCAN_ONLY) ||
            size != ((flags & FCAM_STILL_HAS_QUANT) ? 144u : 16u)) return -EINVAL;
        if (!get32(in + 4) || get32(in + 4) > FCAM_MAX_STILL_WIDTH ||
            !get32(in + 8) || get32(in + 8) > FCAM_MAX_STILL_HEIGHT ||
            !get32(in + 12) || get32(in + 12) > 100) return -ERANGE;
        if (flags & FCAM_STILL_HAS_QUANT)
            for (size_t i = 16; i < 144; ++i) if (!in[i]) return -EINVAL;
        break;
    }
    case FCAM_OP_READ_RESULT:
        if (size != 24 || get32(in + 20) || !get32(in + 16)) return -EINVAL;
        if (!m->token || get64(in) != m->token) return -ESTALE;
        if (get64(in + 8) != m->result_cursor) return -ESPIPE;
        if (m->result_cursor == m->result_size) return -ENODATA;
        if (get32(in + 16) > capacity) return -ENOSPC;
        break;
    case FCAM_OP_RELEASE_RESULT:
        if (size != 16) return -EINVAL;
        if (!m->token || get64(in) != m->token) return -ESTALE;
        if (m->result_cursor != m->result_size) return -EBUSY;
        if (get64(in + 8) != m->result_hash) return -EBADMSG;
        return 0;
    default: return -ENOTSUP;
    }
    if (op == FCAM_OP_INIT || op == FCAM_OP_STATE || op == FCAM_OP_CONFIGURE ||
        op == FCAM_OP_VIDEO_BEGIN || op == FCAM_OP_CANCEL) {
        if (capacity < FCAM_STATE_BYTES) return -ENOSPC;
    } else if (op == FCAM_OP_VDF_PATH || op == FCAM_OP_VDF_ZEBRA ||
               op == FCAM_OP_VDF_LAYOUT || op == FCAM_OP_VDF_DISPLAY_CONFIG ||
               op == FCAM_OP_VDF_BIT_WIDTH || op == FCAM_OP_STILL_FORMAT || op == FCAM_OP_STARTUP_CONTROL) {
        const size_t required = op == FCAM_OP_STARTUP_CONTROL ? FCAM_STARTUP_CONTROL_RESULT_BYTES :
            op == FCAM_OP_STILL_FORMAT ? FCAM_STILL_FORMAT_RESULT_BYTES :
            op == FCAM_OP_VDF_BIT_WIDTH ? FCAM_BIT_WIDTH_RESULT_BYTES :
            op == FCAM_OP_VDF_LAYOUT ? FCAM_LAYOUT_RESULT_BYTES :
            op == FCAM_OP_VDF_ZEBRA ? FCAM_ZEBRA_RESULT_BYTES :
            op == FCAM_OP_VDF_DISPLAY_CONFIG ? FCAM_DISPLAY_RESULT_BYTES : FCAM_VDF_RESULT_BYTES;
        if (capacity < required) return -ENOSPC;
    } else if (op == FCAM_OP_AUTOFOCUS) {
        if (capacity < FCAM_AF_BYTES) return -ENOSPC;
    } else if (op == FCAM_OP_BB_STARTUP_CONFIG || op == FCAM_OP_HISTOGRAM) {
        if (capacity < (op == FCAM_OP_HISTOGRAM ? FCAM_HIST_RESULT_BYTES : FCAM_BB_RESULT_BYTES))
            return -ENOSPC;
    } else if (!capacity) return -ENOSPC;
    if (op == FCAM_OP_STATE || op == FCAM_OP_READ_RESULT || op == FCAM_OP_CANCEL) return 0;
    if (m->stream_state == 3) return -EIO;
    if ((op == FCAM_OP_STILL || op == FCAM_OP_VIDEO_FRAME || op == FCAM_OP_VIDEO_END ||
         op == FCAM_OP_VDF_PATH || op == FCAM_OP_VDF_ZEBRA || op == FCAM_OP_VDF_LAYOUT ||
         op == FCAM_OP_VDF_DISPLAY_CONFIG || op == FCAM_OP_BB_STARTUP_CONFIG ||
         op == FCAM_OP_HISTOGRAM || op == FCAM_OP_VDF_BIT_WIDTH || op == FCAM_OP_STILL_FORMAT ||
         op == FCAM_OP_STARTUP_CONTROL ||
         (op == FCAM_OP_INIT && !m->sensor_initialized)) &&
        m->proof.serial == UINT64_MAX)
        return -EOVERFLOW;
    if (op == FCAM_OP_INIT && !m->sensor_initialized &&
        (m->rendered == UINT64_MAX || m->frame_generation == UINT64_MAX || m->retired == UINT64_MAX))
        return -EOVERFLOW;
    if (op == FCAM_OP_VIDEO_FRAME || op == FCAM_OP_VIDEO_END) {
        if (m->stream_state != 1) return -EPIPE;
    } else if (m->stream_state == 1) return -EBUSY;
    if (op == FCAM_OP_VDF_PATH || op == FCAM_OP_VDF_ZEBRA ||
        op == FCAM_OP_VDF_LAYOUT || op == FCAM_OP_VDF_DISPLAY_CONFIG ||
        op == FCAM_OP_BB_STARTUP_CONFIG || op == FCAM_OP_HISTOGRAM ||
        op == FCAM_OP_VDF_BIT_WIDTH || op == FCAM_OP_STILL_FORMAT || op == FCAM_OP_STARTUP_CONTROL) {
        if (m->vdf_busy || m->owner.info.state != OPTICAL_FRAME_IDLE) return -EBUSY;
        if (m->generation == UINT64_MAX) return -EOVERFLOW;
        const int active = op == FCAM_OP_VDF_LAYOUT || op == FCAM_OP_VDF_DISPLAY_CONFIG ||
            op == FCAM_OP_BB_STARTUP_CONFIG || op == FCAM_OP_HISTOGRAM ||
            op == FCAM_OP_VDF_BIT_WIDTH || op == FCAM_OP_STILL_FORMAT || op == FCAM_OP_STARTUP_CONTROL ||
            (op == FCAM_OP_VDF_ZEBRA ? m->vdf_class != 0 : in[0] != 0);
        if (active && (m->rendered == UINT64_MAX || m->consumed == UINT64_MAX ||
            m->retired == UINT64_MAX || m->frame_generation == UINT64_MAX ||
            m->owner.info.generation == UINT64_MAX || m->owner.info.counts.staged == UINT64_MAX ||
            m->owner.info.counts.rendered == UINT64_MAX || m->owner.info.counts.read == UINT64_MAX ||
            m->owner.info.counts.retired == UINT64_MAX)) return -EOVERFLOW;
    }
    if (op == FCAM_OP_VIDEO_BEGIN &&
        (m->bb_applied.sq_mode || m->bb_applied.sq_rate || m->bb_applied.sq_aux12 ||
         m->bb_applied.sq_aux16 || m->bb_applied.sq_aux20 || m->bb_applied.sq_aux24)) return -ENOTSUP;
    if ((op == FCAM_OP_CONFIGURE || op == FCAM_OP_VIDEO_BEGIN ||
         (op == FCAM_OP_INIT && size)) && m->generation == UINT64_MAX) return -EOVERFLOW;
    if (op == FCAM_OP_AUTOFOCUS && m->generation == UINT64_MAX) return -EOVERFLOW;
    if (op == FCAM_OP_STILL || op == FCAM_OP_VIDEO_FRAME || op == FCAM_OP_VIDEO_END) {
        if (m->next_token == UINT64_MAX || m->result_read > UINT64_MAX - FCAM_MAX_RESULT_BYTES ||
            m->rendered == UINT64_MAX || m->consumed == UINT64_MAX ||
            m->jpeg_encoded == UINT64_MAX || m->video_encoded == UINT64_MAX ||
            m->frame_generation == UINT64_MAX || m->retired == UINT64_MAX) return -EOVERFLOW;
    }
    return 0;
}
static int execute(struct fcam_model *m, uint32_t op, const uint8_t *in, size_t size,
                   uint8_t *out, size_t capacity, struct fcam_exec_result *r)
{
    struct fcam_exec_result value = {0};
    int error = 0;
    if (op == FCAM_OP_VDF_PATH || op == FCAM_OP_VDF_ZEBRA ||
        op == FCAM_OP_VDF_LAYOUT || op == FCAM_OP_VDF_DISPLAY_CONFIG ||
        op == FCAM_OP_VDF_BIT_WIDTH || op == FCAM_OP_STILL_FORMAT || op == FCAM_OP_STARTUP_CONTROL)
        return vdf_transaction(m, op, in, out, r);
    if (op == FCAM_OP_BB_STARTUP_CONFIG || op == FCAM_OP_HISTOGRAM)
        return bb_transaction(m, op, in, out, r);
    if (op == FCAM_OP_READ_RESULT) {
        size_t used = get32(in + 16);
        if (used > m->result_size - m->result_cursor) used = m->result_size - m->result_cursor;
        value = (struct fcam_exec_result){m->token, m->result_size, m->result_cursor, used};
        memcpy(out, m->result_data + m->result_cursor, used);
        m->result_cursor += used;
        m->result_read += used;
        *r = value;
        return 0;
    }
    if (op == FCAM_OP_RELEASE_RESULT) {
        if (fnv(m->result_data, m->result_size) != m->result_hash) return fault(m, -EIO);
        discard(m);
        *r = value;
        return 0;
    }
    if (op == FCAM_OP_CANCEL) {
        const uint64_t retired_before = vcam_snapshot(m->still).counts.retired;
        const int cancelled = video_engine_stream_cancel(m->video) == VIDEO_ENGINE_OK &&
            vcam_cancel(m->still) == VCAM_CANCELLED;
        const uint64_t retired = vcam_snapshot(m->still).counts.retired - retired_before;
        if (retired > UINT64_MAX - m->retired) return fault(m, -EOVERFLOW);
        m->retired += retired;
        if (!cancelled) return fault(m, -EIO);
        optical_frame_info optical;
        if (optical_frame_snapshot(&m->owner, &optical) != OPTICAL_FRAME_OK ||
            optical.state != OPTICAL_FRAME_IDLE) return fault(m, -EIO);
        discard(m);
        m->stream_state = 0;
        m->vdf_busy = 0;
    } else if (op == FCAM_OP_CONFIGURE || op == FCAM_OP_VIDEO_BEGIN ||
               (op == FCAM_OP_INIT && size)) {
        struct config config;
        error = config_parse(in, &config, op == FCAM_OP_VIDEO_BEGIN);
        if (error) return error;
        if (op == FCAM_OP_VIDEO_BEGIN) {
            if (!(m->caps & FCAM_CAP_H264)) return -ENOTSUP;
            m->video_status = video_engine_stream_begin(m->video, config.width, config.height,
                config.fps, FCAM_MAX_RESULT_BYTES - FCAM_PACKET_HEADER_BYTES - CONFIG_LIMIT,
                packet_sink, m);
            if (m->video_status != VIDEO_ENGINE_OK) return fault(m, -EIO);
        }
        error = configure(m, &config);
        if (error) return error;
        if (op == FCAM_OP_VIDEO_BEGIN) {
            free(m->video_config);
            m->video_config = NULL;
            m->video_config_size = 0;
            m->stream_state = 1;
            m->packet_generation = m->frame_generation;
        }
    } else if (op == FCAM_OP_AUTOFOCUS) {
        const optical_frame_af_request request = {get32(in), get32(in + 4),
            get32(in + 8), get32(in + 12), (double)get64(in + 16) / 1000000.0,
            get64(in + 24) == UINT64_MAX ? INFINITY : (double)get64(in + 24) / 1000000.0};
        optical_frame_af_result focused;
        const enum vcam_status status = vcam_autofocus(m->still, &request, &focused);
        if (status != VCAM_OK) {
            const struct vcam_info info = vcam_snapshot(m->still);
            return info.optical_status == OPTICAL_FRAME_NO_CONTRAST ? -ENODATA : -EINVAL;
        }
        struct config config = m->config;
        config.focus = isinf(focused.focus_m) || focused.focus_m >= (double)UINT64_MAX / 1000000.0 ?
            UINT64_MAX : (uint64_t)floor(focused.focus_m * 1000000.0 + 0.5);
        error = configure(m, &config);
        if (error) return error;
        uint8_t response[FCAM_AF_BYTES] = {0};
        put64(response, config.focus);
        put64(response + 8, (uint64_t)floor(focused.score * 65536.0 + 0.5));
        put32(response + 16, (uint32_t)focused.coarse_samples);
        put32(response + 20, (uint32_t)focused.refinement_samples);
        memcpy(out, response, sizeof(response));
        value.used = sizeof(response);
        *r = value;
        return 0;
    } else if (op == FCAM_OP_STILL || op == FCAM_OP_VIDEO_FRAME || op == FCAM_OP_VIDEO_END) {
        if (op == FCAM_OP_STILL && !(m->caps & FCAM_CAP_STILL)) return -ENOTSUP;
        if (op == FCAM_OP_VIDEO_FRAME) {
            const struct video_engine_stream_info info = video_engine_stream_snapshot(m->video);
            if (info.frames_consumed != info.packets_published) return -EAGAIN;
            if (info.frames_consumed >= INT64_MAX) return -EOVERFLOW;
        }
        proof_begin(m, op);
        error = stage(m);
        if (error) return error;
        if (op == FCAM_OP_STILL) error = still_frame(m, in);
        else if (op == FCAM_OP_VIDEO_FRAME) error = video_frame(m);
        else if (!startup_domain(m)) error = fault(m, -EIO);
        else {
            const struct video_engine_stream_info before = video_engine_stream_snapshot(m->video);
            m->proof.consumer_entered = 1;
            m->video_status = video_engine_stream_drain(m->video);
            if (m->video_status == VIDEO_ENGINE_OK) m->video_status = video_engine_stream_finish(m->video);
            const struct video_engine_stream_info after = video_engine_stream_snapshot(m->video);
            m->proof.consumer_returned = 1;
            m->proof.consumer_status = m->video_status;
            m->video_encoded += after.packets_received - before.packets_received;
            if (m->video_status != VIDEO_ENGINE_OK) error = fault(m, -EIO);
            else {
                m->stream_state = 2;
                if (!m->result_size) {
                    const struct video_engine_stream_packet eos = {NULL, 0,
                        (int64_t)after.frames_consumed, (int64_t)after.frames_consumed, 0, 0};
                    packet_header(m, m->result_data, &eos);
                    put32(m->result_data + 64, 0);
                    m->result_size = FCAM_PACKET_HEADER_BYTES;
                }
                put32(m->result_data + m->last_packet + 44, FCAM_PACKET_EOS);
            }
        }
        if (error) { proof_result(m); discard(m); return error; }
        if (!m->result_size) { discard(m); *r = value; return 0; }
        return publish(m, out, capacity, r);
    }
    if (op == FCAM_OP_INIT) {
        error = sensor_probe(m);
        if (error) return error;
    }
    state(m, out);
    value.used = FCAM_STATE_BYTES;
    *r = value;
    return 0;
}
int fcam_model_request(struct fcam_model *m, uint32_t op, const uint8_t *input, size_t in_size,
                       uint8_t *out, size_t capacity, struct fcam_exec_result *result)
{
    int error = arguments(m, input, in_size, out, capacity, result);
    if (error) return error;
    error = validate_request(m, op, input, in_size, capacity);
    if (error) return error;
    m->busy = 1;
    const uint64_t previous_proof = m->proof.serial;
    error = execute(m, op, input, in_size, out, capacity, result);
    if (m->proof.serial != previous_proof) proof_finish(m, error);
    m->busy = 0;
    return error;
}
int fcam_model_proof_snapshot(const struct fcam_model *m,
                              struct fcam_frame_proof *proof, size_t proof_size)
{
    if (!m || !proof || proof_size != sizeof(*proof) ||
        !valid_span((struct span){m, sizeof(*m)}) ||
        !valid_span((struct span){proof, proof_size})) return -EINVAL;
    const struct span private_spans[] = {{m, sizeof(*m)}, {m->pool, FRAME_CAPACITY},
        {m->result_data, m->result_data ? FCAM_MAX_RESULT_BYTES : 0},
        {m->video_config, m->video_config_size}, {m->vdf_sink, m->vdf_capacity}};
    for (size_t i = 0; i < sizeof(private_spans) / sizeof(private_spans[0]); ++i)
        if (overlap((struct span){proof, proof_size}, private_spans[i])) return -EINVAL;
    if (m->busy) return -EBUSY;
    if (m->owner_pid != (uint64_t)getpid()) return -ECHILD;
    *proof = m->proof;
    return 0;
}
