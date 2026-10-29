/* SPDX-License-Identifier: MIT */
/* Test-only wrappers inject faults into the real owner/copy/retire boundaries. */
#include "../virtual-optical-frame-owner/optical-frame-owner.h"
#include <assert.h>
static optical_frame_status checked_configure(optical_frame_owner *, const optical_frame_config *);
static optical_frame_status checked_read(optical_frame_owner *, const optical_frame_lease *,
                                          optical_frame_consumer, void *);
static optical_frame_status checked_retire(optical_frame_owner *, const optical_frame_lease *);
#define optical_frame_configure checked_configure
#define optical_frame_consumer_read checked_read
#define optical_frame_retire checked_retire
#include "functional-camera-core.c"
#undef optical_frame_configure
#undef optical_frame_consumer_read
#undef optical_frame_retire
#include <libavutil/log.h>

enum injection { NONE, CONFIG_FAIL, SOURCE_BEFORE, SOURCE_AFTER, PARTIAL_COPY,
                 SINK_CHANGED, STALE_RETIRE, CONFIG_CHANGED, ZERO_LEASE, WRONG_LEASE,
                 NO_CONSUMER };
static enum injection inject;
static struct fcam_model *subject;
static optical_frame_status injected_status;
static size_t display_fault_slot;

static optical_frame_status checked_configure(optical_frame_owner *owner, const optical_frame_config *config)
{
    if (inject == CONFIG_FAIL) {
        optical_frame_config invalid = *config;
        invalid.params.f_number = 0;
        injected_status = optical_frame_configure(owner, &invalid);
        assert(injected_status == OPTICAL_FRAME_INVALID);
        return injected_status;
    }
    return optical_frame_configure(owner, config);
}
static int mutate_source(const optical_frame_view *view, void *context)
{
    const int error = vdf_copy(view, context);
    subject->pool[0] ^= 1u;
    return error;
}
static optical_frame_status checked_read(optical_frame_owner *owner, const optical_frame_lease *lease,
                                          optical_frame_consumer consumer, void *context)
{
    if (inject == SOURCE_BEFORE) subject->pool[0] ^= 1u;
    if (inject == ZERO_LEASE || inject == WRONG_LEASE) {
        optical_frame_lease wrong = *lease;
        if (inject == ZERO_LEASE) wrong.generation = 0;
        else wrong.buffer = subject->vdf_sink;
        injected_status = optical_frame_consumer_read(owner, &wrong, consumer, context);
        assert(injected_status == OPTICAL_FRAME_STALE);
        return injected_status;
    }
    if (inject == NO_CONSUMER) return OPTICAL_FRAME_OK;
    const size_t capacity = subject ? subject->vdf_capacity : 0;
    if (inject == PARTIAL_COPY) --subject->vdf_capacity;
    const optical_frame_status status = optical_frame_consumer_read(owner, lease,
        inject == SOURCE_AFTER ? mutate_source : consumer, context);
    if (inject == PARTIAL_COPY) subject->vdf_capacity = capacity;
    if (inject == SINK_CHANGED) subject->vdf_sink[0] ^= 1u;
    if (inject == CONFIG_CHANGED) {
        if (subject->proof.opcode == FCAM_OP_VDF_LAYOUT) subject->layout_staged[23] ^= 1u;
        else if (subject->proof.opcode == FCAM_OP_VDF_DISPLAY_CONFIG)
            subject->display_staged[display_fault_slot][15] ^= 1u;
        else if (subject->proof.opcode == FCAM_OP_VDF_ZEBRA) subject->zebra_staged[3] ^= 1u;
        else subject->vdf_staged[3] ^= 1u;
    }
    injected_status = status;
    return status;
}
static optical_frame_status checked_retire(optical_frame_owner *owner, const optical_frame_lease *lease)
{
    if (inject == STALE_RETIRE) {
        optical_frame_lease stale = *lease;
        --stale.generation;
        injected_status = optical_frame_retire(owner, &stale);
        assert(injected_status == OPTICAL_FRAME_STALE);
        return injected_status;
    }
    return optical_frame_retire(owner, lease);
}
static const uint8_t enabled[16] = {1, 5, 5};
static const uint8_t disabled[16] = {0, 1, 1};
static struct fcam_model *model(void)
{
    struct fcam_model *m = fcam_model_create(77);
    assert(m);
    uint8_t config[FCAM_CONFIG_BYTES] = {0}, response[FCAM_STATE_BYTES];
    struct fcam_exec_result result;
    put32(config, 128); put32(config + 4, 64); put32(config + 8, 25);
    put32(config + 12, 90); put32(config + 16, 400); put32(config + 20, 100);
    put64(config + 24, 2500); put64(config + 32, 1000000);
    assert(fcam_model_request(m, FCAM_OP_CONFIGURE, config, sizeof(config), response,
                              sizeof(response), &result) == 0);
    return m;
}
static void path(struct fcam_model *m, const uint8_t input[16], uint8_t response[160])
{
    struct fcam_exec_result result;
    assert(fcam_model_request(m, FCAM_OP_VDF_PATH, input, 16, response, 160, &result) == 0);
    assert(result.used == 160 && !result.token && !result.total && !result.offset);
}
static void reject(struct fcam_model *m, uint32_t opcode, const uint8_t *input,
                    size_t size, size_t capacity, int expected)
{
    uint8_t saved[sizeof(*m)], out[FCAM_VDF_RESULT_MAX_BYTES + 1];
    struct fcam_exec_result result, old;
    memcpy(saved, m, sizeof(saved));
    memset(out, 0xa5, sizeof(out)); memset(&result, 0x59, sizeof(result));
    memcpy(&old, &result, sizeof(old));
    assert(capacity <= sizeof(out));
    assert(fcam_model_request(m, opcode, input, size, out, capacity, &result) == expected);
    assert(!memcmp(saved, m, sizeof(saved)) && !memcmp(&result, &old, sizeof(old)));
    for (size_t i = 0; i < sizeof(out); ++i) assert(out[i] == 0xa5);
}
static void emit(const char *name, const uint8_t *data, size_t size)
{
    assert(printf("BLOB %s %zu\n", name, size) > 0);
    assert(fwrite(data, 1, size, stdout) == size);
}
static void success(void)
{
    struct fcam_model *m = model();
    uint8_t input[16], response[160], original[16];
    memcpy(input, enabled, 16);
    input[3] = 0xa5; input[4] = 2;
    for (size_t i = 5; i <= 12; ++i) input[i] = (uint8_t)(i * 17);
    memcpy(original, input, 16);
    const uint64_t generation = m->generation;
    path(m, input, response);
    assert(m->generation == generation + 1 && m->frame_generation == 1 &&
           m->rendered == 1 && m->consumed == 1 && m->retired == 1 &&
           !m->jpeg_encoded && !m->video_encoded && !m->packet_generation && !m->result_read &&
           !m->result_data && !m->token && !m->vdf_busy && m->vdf_class == 1);
    assert(m->vdf_sink != m->pool && m->vdf_copied == 128u * 64u * 3u &&
           !memcmp(m->vdf_sink, m->pool, m->vdf_copied));
    assert(m->owner.info.counts.staged == 1 && m->owner.info.counts.read == 1 &&
           m->owner.info.counts.rendered == 1 && m->owner.info.counts.retired == 1 &&
           m->owner.info.state == OPTICAL_FRAME_IDLE);
    assert(!memcmp(m->vdf_staged, original, 16) && !memcmp(m->vdf_config, original, 16));
    struct fcam_frame_proof proof;
    assert(fcam_model_proof_snapshot(m, &proof, sizeof(proof)) == 0);
    assert(sizeof(proof) == 376 && proof.consumer_kind == FCAM_PROOF_VDF &&
           proof.opcode == FCAM_OP_VDF_PATH && proof.serial == 1 &&
           proof.render_observed && proof.consumer_entered && proof.consumer_returned && proof.retired &&
           !proof.encoder_consumed && !proof.encoded_bytes && !proof.result_bytes && !proof.result_token &&
           !proof.operation_status && proof.consumer_status == OPTICAL_FRAME_OK &&
           proof.source_fnv1a64 == proof.consumer_before_fnv1a64 &&
           proof.source_fnv1a64 == proof.consumer_after_fnv1a64 &&
           proof.after.consumed == proof.before.consumed + 1 &&
           proof.config_generation == generation + 1 && proof.frame_generation == 1 && proof.lease_generation == 1);
    emit("INPUT", input, 16); emit("ENABLED", response, 160);
    emit("SOURCE", m->pool, m->vdf_copied); emit("SINK", m->vdf_sink, m->vdf_copied);
    memset(input, 0xff, sizeof(input));
    assert(!memcmp(m->vdf_config, original, 16));
    path(m, original, response);
    assert(m->generation == generation + 2 && m->frame_generation == 2 &&
           m->owner.info.generation == 2 && m->rendered == 2 && m->consumed == 2 && m->retired == 2);
    emit("REPEAT", response, 160);
    const optical_frame_info before = m->owner.info;
    path(m, disabled, response);
    assert(m->generation == generation + 3 && m->frame_generation == 2 &&
           m->rendered == 2 && m->consumed == 2 && m->retired == 2 && !m->vdf_class &&
           !memcmp(&before, &m->owner.info, sizeof(before)) && !memcmp(m->vdf_config, disabled, 16));
    assert(!get64(response + FCAM_VDF_R_LEASE_GENERATION) &&
           !get64(response + FCAM_VDF_R_SOURCE_FNV) && !get64(response + FCAM_VDF_R_SINK_FNV) &&
           !get64(response + FCAM_VDF_R_ACTIVE_BYTES));
    assert(fcam_model_proof_snapshot(m, &proof, sizeof(proof)) == 0);
    assert(proof.serial == 3 && proof.consumer_kind == FCAM_PROOF_VDF && !proof.render_observed &&
           !proof.consumer_entered && !proof.retired && !proof.encoder_consumed &&
           !memcmp(&proof.before, &proof.after, sizeof(proof.before)));
    emit("DISABLED", response, 160);
    for (unsigned value = 0; value <= 2; ++value) {
        uint8_t off[16]; memcpy(off, disabled, 16); off[4] = (uint8_t)value;
        off[3] = 0x9d; memset(off + 5, 0x7b, 8);
        path(m, off, response);
        assert(!memcmp(response + FCAM_VDF_R_CONFIG, off, 16) && m->frame_generation == 2);
    }
    fcam_model_destroy(m);
}
static void validation(void)
{
    struct fcam_model *m = model();
    uint8_t input[17] = {1, 5, 5}, out[160];
    for (size_t capacity = 0; capacity < 160; ++capacity)
        reject(m, FCAM_OP_VDF_PATH, input, 16, capacity, -ENOSPC);
    reject(m, FCAM_OP_VDF_PATH, NULL, 0, 160, -EINVAL);
    reject(m, FCAM_OP_VDF_PATH, input, 15, 160, -EINVAL);
    reject(m, FCAM_OP_VDF_PATH, input, 17, 160, -EINVAL);
    for (size_t offset = 0; offset < 16; ++offset) {
        if (offset == 3 || (offset >= 5 && offset <= 12)) continue;
        const uint8_t old = input[offset];
        input[offset] = 0xff;
        reject(m, FCAM_OP_VDF_PATH, input, 16, 160, -EINVAL);
        input[offset] = old;
    }
    for (uint8_t value = 3; value <= 9; ++value) {
        input[4] = value;
        reject(m, FCAM_OP_VDF_PATH, input, 16, 160, -EINVAL);
    }
    input[4] = 0;
    reject(m, UINT32_MAX, input, 16, 160, -ENOTSUP);
    uint64_t *counters[] = {&m->generation, &m->proof.serial, &m->frame_generation,
        &m->rendered, &m->consumed, &m->retired, &m->owner.info.generation,
        &m->owner.info.counts.staged, &m->owner.info.counts.rendered,
        &m->owner.info.counts.read, &m->owner.info.counts.retired};
    for (size_t i = 0; i < sizeof(counters) / sizeof(counters[0]); ++i) {
        const uint64_t old = *counters[i]; *counters[i] = UINT64_MAX;
        reject(m, FCAM_OP_VDF_PATH, enabled, 16, 160, -EOVERFLOW);
        *counters[i] = old;
    }
    m->busy = 1; reject(m, FCAM_OP_VDF_PATH, enabled, 16, 160, -EBUSY); m->busy = 0;
    m->vdf_busy = 1; reject(m, FCAM_OP_VDF_PATH, enabled, 16, 160, -EBUSY); m->vdf_busy = 0;
    struct fcam_exec_result result;
    assert(fcam_model_request(m, FCAM_OP_VDF_PATH, NULL, 16, out, 160, &result) == -EINVAL);
    assert(fcam_model_request(m, FCAM_OP_VDF_PATH, enabled, 16, NULL, 160, &result) == -EINVAL);
    assert(fcam_model_request(m, FCAM_OP_VDF_PATH, enabled, 16, m->pool, 160, &result) == -EINVAL);
    assert(fcam_model_request(m, FCAM_OP_VDF_PATH, (const uint8_t *)(UINTPTR_MAX - 3u), 16,
                              out, 160, &result) == -EINVAL);
    optical_frame_lease live;
    assert(optical_frame_acquire(&m->owner, m->pool, FRAME_CAPACITY, &live) == OPTICAL_FRAME_OK);
    reject(m, FCAM_OP_VDF_PATH, disabled, 16, 160, -EBUSY);
    assert(optical_frame_retire(&m->owner, &live) == OPTICAL_FRAME_OK);
    path(m, enabled, out);
    assert(fcam_model_request(m, FCAM_OP_VDF_PATH, enabled, 16, m->vdf_sink, 160, &result) == -EINVAL);
    assert(fcam_model_request(m, FCAM_OP_VDF_PATH, m->vdf_sink, 16, out, 160, &result) == -EINVAL);
    struct fcam_frame_proof proof;
    assert(fcam_model_proof_snapshot(m, (struct fcam_frame_proof *)(void *)m->vdf_sink, sizeof(proof)) == -EINVAL);
    fcam_model_destroy(m);
}
static void pending(void)
{
    struct fcam_model *m = model();
    uint8_t still[16] = {0}, out[160], config[48] = {0};
    put32(still, FCAM_STILL_FULL_JPEG); put32(still + 4, 128);
    put32(still + 8, 64); put32(still + 12, 90);
    struct fcam_exec_result result;
    assert(fcam_model_request(m, FCAM_OP_STILL, still, 16, out, 1, &result) == 0);
    const uint64_t hash = fnv(m->result_data, m->result_size), token = m->token;
    reject(m, FCAM_OP_VDF_PATH, enabled, 16, 160, -EBUSY);
    reject(m, FCAM_OP_VDF_PATH, disabled, 16, 160, -EBUSY);
    assert(m->token == token && fnv(m->result_data, m->result_size) == hash);
    assert(fcam_model_request(m, FCAM_OP_CANCEL, NULL, 0, out, 128, &result) == 0);
    put32(config, 128); put32(config + 4, 64); put32(config + 8, 25);
    put32(config + 12, 90); put32(config + 16, 400); put32(config + 20, 100);
    put64(config + 24, 2500); put64(config + 32, 1000000);
    assert(fcam_model_request(m, FCAM_OP_VIDEO_BEGIN, config, 48, out, 128, &result) == 0);
    struct video_engine_stream_info before = video_engine_stream_snapshot(m->video);
    reject(m, FCAM_OP_VDF_PATH, enabled, 16, 160, -EBUSY);
    struct video_engine_stream_info after = video_engine_stream_snapshot(m->video);
    assert(before.state == after.state && before.frames_consumed == after.frames_consumed &&
           before.packets_received == after.packets_received);
    assert(fcam_model_request(m, FCAM_OP_VIDEO_FRAME, NULL, 0, out, 1, &result) == 0 && result.token);
    const uint64_t video_hash = fnv(m->result_data, m->result_size);
    reject(m, FCAM_OP_VDF_PATH, enabled, 16, 160, -EBUSY);
    assert(fnv(m->result_data, m->result_size) == video_hash);
    assert(fcam_model_request(m, FCAM_OP_CANCEL, NULL, 0, out, 128, &result) == 0);
    path(m, enabled, out);
    assert(m->jpeg_encoded == 1 && m->video_encoded == 1 && m->consumed == 3);
    fcam_model_destroy(m);
}
static void failures(void)
{
    for (enum injection test = CONFIG_FAIL; test <= CONFIG_CHANGED; ++test) {
        struct fcam_model *m = model();
        uint8_t out[160], old[160], previous[16];
        path(m, disabled, out); memcpy(previous, m->vdf_config, 16);
        const uint64_t generation = m->generation;
        struct fcam_exec_result result, saved;
        memset(out, 0xa5, sizeof(out)); memcpy(old, out, sizeof(old));
        memset(&result, 0x59, sizeof(result)); memcpy(&saved, &result, sizeof(saved));
        inject = test; subject = m;
        assert(fcam_model_request(m, FCAM_OP_VDF_PATH, enabled, 16, out, 160, &result) == -EIO);
        inject = NONE; subject = NULL;
        assert(!memcmp(out, old, sizeof(out)) && !memcmp(&result, &saved, sizeof(saved)) &&
               !memcmp(m->vdf_config, previous, 16) && m->generation == generation &&
               m->stream_state == 3 && m->vdf_busy && !m->vdf_class &&
               !m->jpeg_encoded && !m->video_encoded && !m->token && !m->result_data);
        struct fcam_frame_proof proof;
        assert(fcam_model_proof_snapshot(m, &proof, sizeof(proof)) == 0);
        assert(proof.consumer_kind == FCAM_PROOF_VDF && proof.operation_status == -EIO &&
               !proof.encoder_consumed && !proof.encoded_bytes && !proof.result_bytes);
        if (test == CONFIG_FAIL) assert(!m->rendered && !m->consumed && !m->retired);
        else {
            assert(m->rendered == 1 && m->frame_generation == 1 && proof.render_observed);
            if (test == STALE_RETIRE || test == CONFIG_CHANGED) assert(m->consumed == 1);
            else assert(!m->consumed);
            if (test == STALE_RETIRE) {
                assert(!m->retired && proof.retire_status == OPTICAL_FRAME_STALE &&
                       m->owner.info.state == OPTICAL_FRAME_RENDERED);
                optical_frame_lease lease = {&m->owner, m->owner.info.generation, m->pool, FRAME_CAPACITY};
                assert(optical_frame_retire(&m->owner, &lease) == OPTICAL_FRAME_OK);
            } else assert(m->retired == 1 && proof.retired);
            if (test == SOURCE_BEFORE) assert(!proof.consumer_entered && injected_status == OPTICAL_FRAME_CHANGED);
            if (test == SOURCE_AFTER) assert(proof.consumer_returned && injected_status == OPTICAL_FRAME_CHANGED);
            if (test == PARTIAL_COPY) assert(m->vdf_copied == 128u * 63u * 3u &&
                proof.consumer_status == OPTICAL_FRAME_CONSUMER_FAILED);
            if (test == SINK_CHANGED) assert(proof.source_fnv1a64 != proof.consumer_after_fnv1a64);
        }
        reject(m, FCAM_OP_VDF_PATH, enabled, 16, 160, -EIO);
        assert(fcam_model_request(m, FCAM_OP_CANCEL, NULL, 0, out, 128, &result) == 0);
        assert(!m->vdf_busy && !m->stream_state);
        fcam_model_destroy(m);
    }
}
static const uint8_t zebra_disabled[FCAM_ZEBRA_INPUT_BYTES] = {3, 0, 0x20, 75, 65};
static void zebra(struct fcam_model *m, const uint8_t input[FCAM_ZEBRA_INPUT_BYTES],
                   uint8_t response[FCAM_ZEBRA_RESULT_BYTES])
{
    const struct config config = m->config;
    uint8_t route[FCAM_VDF_INPUT_BYTES]; memcpy(route, m->vdf_config, sizeof(route));
    const uint64_t before_generation = m->generation, before_frame = m->frame_generation;
    const struct fcam_proof_counts before = proof_counts(m);
    const optical_frame_info owner = m->owner.info;
    const int active = m->vdf_class != 0;
    struct fcam_exec_result result;
    assert(fcam_model_request(m, FCAM_OP_VDF_ZEBRA, input, FCAM_ZEBRA_INPUT_BYTES,
                              response, FCAM_ZEBRA_RESULT_BYTES, &result) == 0);
    assert(result.used == FCAM_ZEBRA_RESULT_BYTES && !result.token && !result.total && !result.offset);
    assert(!memcmp(&m->config, &config, sizeof(config)) && !memcmp(m->vdf_config, route, sizeof(route)) &&
           !memcmp(m->zebra_staged, input, 5) && !memcmp(m->zebra_config, input, 5) &&
           !memcmp(response + FCAM_ZEBRA_R_CONFIG, input, FCAM_ZEBRA_INPUT_BYTES) &&
           m->generation == before_generation + 1 && m->frame_generation == before_frame + (unsigned)active &&
           m->rendered == before.rendered + (unsigned)active &&
           m->consumed == before.consumed + (unsigned)active && m->retired == before.retired + (unsigned)active &&
           m->jpeg_encoded == before.jpeg_encoded && m->video_encoded == before.video_encoded);
    struct fcam_frame_proof proof;
    assert(fcam_model_proof_snapshot(m, &proof, sizeof(proof)) == 0 && sizeof(proof) == 376);
    assert(proof.consumer_kind == FCAM_PROOF_VDF && proof.opcode == FCAM_OP_VDF_ZEBRA &&
           proof.config_generation == m->generation && !proof.operation_status &&
           !proof.encoder_consumed && !proof.encoded_bytes && !proof.result_bytes && !proof.result_token);
    assert(get32(response + FCAM_VDF_R_CLASS) == (unsigned)active &&
           get32(response + FCAM_VDF_R_ENABLED) == (unsigned)active &&
           get32(response + FCAM_VDF_R_FRAME_CONSUMED) == (unsigned)active &&
           get32(response + FCAM_VDF_R_RETIRED) == (unsigned)active);
    if (active) {
        assert(m->vdf_sink != m->pool && m->vdf_copied == 128u * 64u * 3u &&
               !memcmp(m->vdf_sink, m->pool, m->vdf_copied) &&
               proof.source_fnv1a64 == fnv(m->pool, m->vdf_copied) &&
               proof.consumer_after_fnv1a64 == fnv(m->vdf_sink, m->vdf_copied) &&
               proof.source_fnv1a64 == proof.consumer_before_fnv1a64 &&
               proof.source_fnv1a64 == proof.consumer_after_fnv1a64 && proof.consumer_entered &&
               proof.consumer_returned && proof.retired && proof.consumer_status == OPTICAL_FRAME_OK &&
               proof.final_state == OPTICAL_FRAME_IDLE);
    } else {
        assert(!memcmp(&owner, &m->owner.info, sizeof(owner)) && !m->vdf_copied &&
               !proof.lease_generation && !proof.source_fnv1a64 && !proof.consumer_after_fnv1a64 &&
               !proof.render_observed && !proof.consumer_entered && !proof.retired &&
               !get64(response + FCAM_VDF_R_LEASE_GENERATION) &&
               !memcmp(&proof.before, &proof.after, sizeof(proof.before)));
    }
}
static void zebra_success(void)
{
    struct fcam_model *m = model();
    uint8_t response[FCAM_ZEBRA_RESULT_BYTES], route[FCAM_VDF_INPUT_BYTES];
    assert(!m->vdf_class && !memcmp(m->vdf_config, disabled, sizeof(disabled)));
    emit("ZEBRA_INPUT", zebra_disabled, sizeof(zebra_disabled));
    zebra(m, zebra_disabled, response); emit("ZEBRA_INITIAL", response, sizeof(response));
    zebra(m, zebra_disabled, response); emit("ZEBRA_INITIAL_REPEAT", response, sizeof(response));
    assert(!m->rendered && !m->consumed && !m->retired && !m->sensor_initialized && !m->vdf_sink);
    struct fcam_exec_result result;
    assert(fcam_model_request(m, FCAM_OP_INIT, NULL, 0, response, 128, &result) == 0);
    struct fcam_model snapshot = *m;
    assert(fcam_model_request(m, FCAM_OP_INIT, NULL, 0, response, 128, &result) == 0);
    assert(!memcmp(m, &snapshot, sizeof(snapshot)) && !memcmp(m->zebra_config, zebra_disabled, 5));
    memcpy(route, enabled, sizeof(route)); route[3] = 0xa9; route[4] = 2; route[8] = 0x67;
    path(m, route, response); emit("ZEBRA_ROUTE_ACTIVE", route, sizeof(route));
    zebra(m, zebra_disabled, response); emit("ZEBRA_ACTIVE", response, sizeof(response));
    emit("ZEBRA_SOURCE", m->pool, m->vdf_copied); emit("ZEBRA_SINK", m->vdf_sink, m->vdf_copied);
    zebra(m, zebra_disabled, response); emit("ZEBRA_REPEAT", response, sizeof(response));
    memcpy(route, disabled, sizeof(route)); route[3] = 0x79; route[4] = 1; route[12] = 0x53;
    path(m, route, response); emit("ZEBRA_ROUTE_INACTIVE", route, sizeof(route));
    zebra(m, zebra_disabled, response); emit("ZEBRA_INACTIVE", response, sizeof(response));
    for (unsigned value = 0; value < 256; ++value) {
        uint8_t opaque[8] = {(uint8_t)value, 0, (uint8_t)(255u - value),
                             (uint8_t)(value ^ 0xa5u), (uint8_t)(value ^ 0x53u)};
        zebra(m, opaque, response);
        memset(opaque, 0, sizeof(opaque));
        assert(m->zebra_config[0] == value && m->zebra_config[2] == 255u - value);
    }
    assert(!m->jpeg_encoded && !m->video_encoded && !m->packet_generation && !m->result_read &&
           !m->token && !m->result_data && m->frame_generation == 4);
    fcam_model_destroy(m);
}
static void zebra_validation(void)
{
    struct fcam_model *m = model();
    uint8_t input[9], out[FCAM_ZEBRA_RESULT_BYTES]; memcpy(input, zebra_disabled, 8); input[8] = 0;
    for (size_t capacity = 0; capacity < sizeof(out); ++capacity)
        reject(m, FCAM_OP_VDF_ZEBRA, input, 8, capacity, -ENOSPC);
    for (size_t size = 0; size < 8; ++size) reject(m, FCAM_OP_VDF_ZEBRA, input, size, 168, -EINVAL);
    reject(m, FCAM_OP_VDF_ZEBRA, input, 9, 168, -EINVAL);
    for (unsigned value = 1; value < 256; ++value) {
        input[1] = (uint8_t)value;
        reject(m, FCAM_OP_VDF_ZEBRA, input, 8, 168, -ENOTSUP);
    }
    input[1] = 0;
    for (size_t offset = 5; offset < 8; ++offset) {
        input[offset] = 0xff; reject(m, FCAM_OP_VDF_ZEBRA, input, 8, 168, -EINVAL); input[offset] = 0;
    }
    struct fcam_exec_result result;
    assert(fcam_model_request(m, FCAM_OP_VDF_ZEBRA, NULL, 8, out, 168, &result) == -EINVAL);
    assert(fcam_model_request(m, FCAM_OP_VDF_ZEBRA, input, 8, NULL, 168, &result) == -EINVAL);
    assert(fcam_model_request(m, FCAM_OP_VDF_ZEBRA, out, 8, out, 168, &result) == -EINVAL);
    assert(fcam_model_request(m, FCAM_OP_VDF_ZEBRA, input, 8, (uint8_t *)&result, 168, &result) == -EINVAL);
    assert(fcam_model_request(m, FCAM_OP_VDF_ZEBRA, (const uint8_t *)m->zebra_config, 8,
                              out, 168, &result) == -EINVAL);
    assert(fcam_model_request(m, FCAM_OP_VDF_ZEBRA, (const uint8_t *)(UINTPTR_MAX - 3u), 8,
                              out, 168, &result) == -EINVAL);
    assert(fcam_model_request(m, FCAM_OP_VDF_ZEBRA, input, 8,
                              (uint8_t *)(UINTPTR_MAX - 3u), 168, &result) == -EINVAL);
    assert(fcam_model_request(m, FCAM_OP_VDF_ZEBRA, input, 8, m->pool, 168, &result) == -EINVAL);
    m->busy = 1; reject(m, FCAM_OP_VDF_ZEBRA, input, 8, 168, -EBUSY); m->busy = 0;
    m->vdf_busy = 1; reject(m, FCAM_OP_VDF_ZEBRA, input, 8, 168, -EBUSY); m->vdf_busy = 0;
    optical_frame_lease live;
    assert(optical_frame_acquire(&m->owner, m->pool, FRAME_CAPACITY, &live) == OPTICAL_FRAME_OK);
    reject(m, FCAM_OP_VDF_ZEBRA, input, 8, 168, -EBUSY);
    assert(optical_frame_retire(&m->owner, &live) == OPTICAL_FRAME_OK);
    uint64_t *counters[] = {&m->generation, &m->proof.serial, &m->frame_generation, &m->rendered,
        &m->consumed, &m->retired, &m->owner.info.generation, &m->owner.info.counts.staged,
        &m->owner.info.counts.rendered, &m->owner.info.counts.read, &m->owner.info.counts.retired};
    for (size_t i = 0; i < 2; ++i) {
        const uint64_t old = *counters[i]; *counters[i] = UINT64_MAX;
        reject(m, FCAM_OP_VDF_ZEBRA, input, 8, 168, -EOVERFLOW); *counters[i] = old;
    }
    m->frame_generation = UINT64_MAX;
    zebra(m, input, out); m->frame_generation = 0;
    path(m, enabled, out);
    for (size_t i = 0; i < sizeof(counters) / sizeof(counters[0]); ++i) {
        const uint64_t old = *counters[i]; *counters[i] = UINT64_MAX;
        reject(m, FCAM_OP_VDF_ZEBRA, input, 8, 168, -EOVERFLOW); *counters[i] = old;
    }
    reject(m, FCAM_OP_VDF_ZEBRA, input, 8, 167, -ENOSPC);
    assert(fcam_model_request(m, FCAM_OP_VDF_ZEBRA, input, 8, m->vdf_sink, 168, &result) == -EINVAL);
    assert(fcam_model_request(m, FCAM_OP_VDF_ZEBRA, m->vdf_sink, 8, out, 168, &result) == -EINVAL);
    fcam_model_destroy(m);
}
static void zebra_pending(void)
{
    struct fcam_model *m = model();
    uint8_t still[16] = {0}, config[48] = {0}, out[FCAM_ZEBRA_RESULT_BYTES];
    put32(still, FCAM_STILL_FULL_JPEG); put32(still + 4, 128);
    put32(still + 8, 64); put32(still + 12, 90);
    struct fcam_exec_result result;
    assert(fcam_model_request(m, FCAM_OP_STILL, still, 16, out, 1, &result) == 0);
    const uint64_t hash = fnv(m->result_data, m->result_size), token = m->token;
    reject(m, FCAM_OP_VDF_ZEBRA, zebra_disabled, 8, 168, -EBUSY);
    assert(m->token == token && fnv(m->result_data, m->result_size) == hash);
    assert(fcam_model_request(m, FCAM_OP_CANCEL, NULL, 0, out, 128, &result) == 0);
    put32(config, 128); put32(config + 4, 64); put32(config + 8, 25);
    put32(config + 12, 90); put32(config + 16, 400); put32(config + 20, 100);
    put64(config + 24, 2500); put64(config + 32, 1000000);
    assert(fcam_model_request(m, FCAM_OP_VIDEO_BEGIN, config, 48, out, 128, &result) == 0);
    const struct video_engine_stream_info before = video_engine_stream_snapshot(m->video);
    reject(m, FCAM_OP_VDF_ZEBRA, zebra_disabled, 8, 168, -EBUSY);
    const struct video_engine_stream_info after = video_engine_stream_snapshot(m->video);
    assert(before.frames_consumed == after.frames_consumed && before.packets_received == after.packets_received);
    assert(fcam_model_request(m, FCAM_OP_VIDEO_FRAME, NULL, 0, out, 1, &result) == 0 && result.token);
    const uint64_t video_hash = fnv(m->result_data, m->result_size);
    reject(m, FCAM_OP_VDF_ZEBRA, zebra_disabled, 8, 168, -EBUSY);
    assert(fnv(m->result_data, m->result_size) == video_hash);
    assert(fcam_model_request(m, FCAM_OP_CANCEL, NULL, 0, out, 128, &result) == 0);
    path(m, enabled, out); zebra(m, zebra_disabled, out);
    assert(m->jpeg_encoded == 1 && m->video_encoded == 1 && m->consumed == 4);
    fcam_model_destroy(m);
}
static void zebra_failures(void)
{
    for (enum injection test = CONFIG_FAIL; test <= CONFIG_CHANGED; ++test) {
        struct fcam_model *m = model();
        uint8_t out[FCAM_ZEBRA_RESULT_BYTES], old[FCAM_ZEBRA_RESULT_BYTES], previous[5], route[16];
        zebra(m, zebra_disabled, out); memcpy(previous, m->zebra_config, sizeof(previous));
        path(m, enabled, out); memcpy(route, m->vdf_config, sizeof(route));
        const struct config config = m->config;
        const uint64_t generation = m->generation;
        uint8_t changed[8] = {0xf1, 0, 0x92, 0x73, 0xb4};
        struct fcam_exec_result result, saved;
        memset(out, 0xa5, sizeof(out)); memcpy(old, out, sizeof(old));
        memset(&result, 0x59, sizeof(result)); memcpy(&saved, &result, sizeof(saved));
        inject = test; subject = m;
        assert(fcam_model_request(m, FCAM_OP_VDF_ZEBRA, changed, 8, out, 168, &result) == -EIO);
        inject = NONE; subject = NULL;
        assert(!memcmp(out, old, sizeof(out)) && !memcmp(&result, &saved, sizeof(saved)) &&
               !memcmp(m->zebra_config, previous, sizeof(previous)) &&
               !memcmp(m->vdf_config, route, sizeof(route)) && !memcmp(&m->config, &config, sizeof(config)) &&
               m->generation == generation && m->vdf_class == 1 && m->vdf_busy && m->stream_state == 3);
        struct fcam_frame_proof proof;
        assert(fcam_model_proof_snapshot(m, &proof, sizeof(proof)) == 0 &&
               proof.opcode == FCAM_OP_VDF_ZEBRA && proof.consumer_kind == FCAM_PROOF_VDF &&
               proof.operation_status == -EIO && !proof.encoder_consumed && !proof.encoded_bytes &&
               !proof.result_bytes && !m->jpeg_encoded && !m->video_encoded && !m->token && !m->result_data);
        if (test == CONFIG_FAIL) assert(!memcmp(&proof.before, &proof.after, sizeof(proof.before)));
        else {
            assert(proof.after.rendered == proof.before.rendered + 1 && proof.render_observed);
            assert(proof.after.consumed == proof.before.consumed +
                   (unsigned)(test == STALE_RETIRE || test == CONFIG_CHANGED));
            if (test == STALE_RETIRE) {
                assert(!proof.retired && proof.retire_status == OPTICAL_FRAME_STALE);
                optical_frame_lease lease = {&m->owner, m->owner.info.generation, m->pool, FRAME_CAPACITY};
                assert(optical_frame_retire(&m->owner, &lease) == OPTICAL_FRAME_OK);
            } else assert(proof.retired);
            if (test == PARTIAL_COPY) assert(m->vdf_copied == 128u * 63u * 3u &&
                proof.consumer_status == OPTICAL_FRAME_CONSUMER_FAILED);
            if (test == SINK_CHANGED) assert(proof.source_fnv1a64 != proof.consumer_after_fnv1a64);
        }
        reject(m, FCAM_OP_VDF_ZEBRA, changed, 8, 168, -EIO);
        assert(fcam_model_request(m, FCAM_OP_CANCEL, NULL, 0, out, 128, &result) == 0);
        zebra(m, changed, out);
        fcam_model_destroy(m);
    }
}
static const uint8_t layout_body[32] = {
    0x07,0x01,0x01,0x00,0x00,0x00,0x00,0x00,0x80,0x02,0xe0,0x01,0x00,0x00,0x00,0x00,
    0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x03,0x00,0x00,0x00,0x00,0x00,0x00,0x00};
static struct fcam_model *layout_model(void)
{
    struct fcam_model *m = fcam_model_create(77);
    assert(m);
    uint8_t config[48] = {0}, out[128];
    struct fcam_exec_result result;
    put32(config, 640); put32(config + 4, 480); put32(config + 8, 117);
    put32(config + 12, 13); put32(config + 16, 800); put32(config + 20, 640);
    put64(config + 24, 8642); put64(config + 32, UINT64_MAX);
    assert(fcam_model_request(m, FCAM_OP_CONFIGURE, config, sizeof(config), out,
                              sizeof(out), &result) == 0);
    return m;
}
static void layout(struct fcam_model *m, const uint8_t input[32], uint8_t response[192])
{
    const struct fcam_model before = *m;
    const struct video_engine_stream_info video_before = video_engine_stream_snapshot(m->video);
    struct fcam_exec_result result;
    assert(fcam_model_request(m, FCAM_OP_VDF_LAYOUT, input, 32, response, 192, &result) == 0);
    assert(result.used == 192 && !result.token && !result.total && !result.offset);
    assert(!memcmp(&m->config, &before.config, sizeof(m->config)) &&
           !memcmp(m->vdf_config, before.vdf_config, sizeof(m->vdf_config)) &&
           !memcmp(m->zebra_config, before.zebra_config, sizeof(m->zebra_config)) &&
           m->vdf_class == 1 && !m->vdf_busy && !m->stream_state && m->layout_valid &&
           !memcmp(m->layout_staged, input, 32) && !memcmp(m->layout_config, input, 32) &&
           !memcmp(response + 160, m->layout_config, 32) &&
           !memcmp(response + 128, before.vdf_config, 16));
    assert(m->generation == before.generation + 1 && m->frame_generation == before.frame_generation + 1 &&
           m->rendered == before.rendered + 1 && m->consumed == before.consumed + 1 &&
           m->retired == before.retired + 1 && m->jpeg_encoded == before.jpeg_encoded &&
           m->video_encoded == before.video_encoded && m->result_read == before.result_read &&
           m->packet_generation == before.packet_generation && m->next_token == before.next_token &&
           !m->token && !m->result_data && m->owner.info.generation == before.owner.info.generation + 1 &&
           m->owner.info.counts.staged == before.owner.info.counts.staged + 1 &&
           m->owner.info.counts.rendered == before.owner.info.counts.rendered + 1 &&
           m->owner.info.counts.read == before.owner.info.counts.read + 1 &&
           m->owner.info.counts.retired == before.owner.info.counts.retired + 1 &&
           m->owner.info.state == OPTICAL_FRAME_IDLE);
    const struct video_engine_stream_info video_after = video_engine_stream_snapshot(m->video);
    assert(video_after.frames_consumed == video_before.frames_consumed &&
           video_after.packets_received == video_before.packets_received &&
           video_after.packets_published == video_before.packets_published &&
           video_after.state == video_before.state);
    assert(m->vdf_sink != m->pool && m->vdf_copied == 640u * 480u * 3u &&
           !memcmp(m->pool, m->vdf_sink, m->vdf_copied));
    struct fcam_frame_proof proof;
    assert(fcam_model_proof_snapshot(m, &proof, sizeof(proof)) == 0 && sizeof(proof) == 376);
    assert(proof.opcode == FCAM_OP_VDF_LAYOUT && proof.consumer_kind == FCAM_PROOF_VDF &&
           proof.serial == before.proof.serial + 1 && proof.config_generation == m->generation &&
           proof.frame_generation == m->frame_generation && proof.lease_generation == m->owner.info.generation &&
           proof.width == 640 && proof.height == 480 && proof.stride == 1920 &&
           proof.active_bytes == m->vdf_copied && proof.source_fnv1a64 == fnv(m->pool, m->vdf_copied) &&
           proof.source_fnv1a64 == proof.consumer_before_fnv1a64 &&
           proof.source_fnv1a64 == proof.consumer_after_fnv1a64 && proof.render_observed &&
           proof.consumer_entered && proof.consumer_returned && proof.retired &&
           proof.source_state == OPTICAL_FRAME_RENDERED &&
           proof.consumer_before_state == OPTICAL_FRAME_READING &&
           proof.consumer_after_state == OPTICAL_FRAME_READING && proof.final_state == OPTICAL_FRAME_IDLE &&
           proof.render_status == OPTICAL_FRAME_OK && proof.consumer_status == OPTICAL_FRAME_OK &&
           proof.retire_status == OPTICAL_FRAME_OK && !proof.operation_status && !proof.encoder_consumed &&
           !proof.encoded_bytes && !proof.result_bytes && !proof.result_token &&
           proof.before.rendered == before.rendered && proof.after.rendered == m->rendered &&
           proof.before.consumed == before.consumed && proof.after.consumed == m->consumed);
}
static void layout_success(void)
{
    struct fcam_model *m = layout_model();
    uint8_t out[192], route[16], input[32], state_reply[128];
    struct fcam_exec_result result;
    assert(!m->layout_valid && !m->vdf_class && !m->rendered && !m->vdf_sink);
    reject(m, FCAM_OP_VDF_LAYOUT, layout_body, 32, 192, -ENODATA);
    assert(fcam_model_request(m, FCAM_OP_INIT, NULL, 0, out, 128, &result) == 0);
    memcpy(route, enabled, 16); route[3] = 0xa9; route[4] = 2; route[8] = 0x67;
    path(m, route, out);
    assert(fcam_model_request(m, FCAM_OP_VDF_ZEBRA, zebra_disabled, 8, out, 168, &result) == 0);
    memcpy(input, layout_body, 32);
    layout(m, input, out);
    emit("LAYOUT_INPUT", input, 32); emit("LAYOUT_ROUTE", route, 16); emit("LAYOUT", out, 192);
    emit("LAYOUT_SOURCE", m->pool, m->vdf_copied); emit("LAYOUT_SINK", m->vdf_sink, m->vdf_copied);
    memset(input, 0xa5, sizeof(input));
    assert(!memcmp(m->layout_config, layout_body, 32));
    layout(m, layout_body, out); emit("LAYOUT_REPEAT", out, 192);
    const struct fcam_model snapshot = *m;
    assert(fcam_model_request(m, FCAM_OP_STATE, NULL, 0, state_reply, 128, &result) == 0);
    assert(fcam_model_request(m, FCAM_OP_INIT, NULL, 0, out, 128, &result) == 0);
    assert(!memcmp(m, &snapshot, sizeof(snapshot)) && !memcmp(out, state_reply, 128));
    assert(get64(out + FCAM_S_GENERATION) == m->generation &&
           get64(out + FCAM_S_FRAME_GENERATION) == m->frame_generation &&
           get64(out + FCAM_S_RENDERED) == m->rendered && get64(out + FCAM_S_CONSUMED) == m->consumed);
    emit("LAYOUT_STATE", state_reply, 128);
    path(m, disabled, out);
    reject(m, FCAM_OP_VDF_LAYOUT, layout_body, 32, 192, -ENODATA);
    assert(m->layout_valid && !memcmp(m->layout_config, layout_body, 32));
    fcam_model_destroy(m);
}
static void layout_validation(void)
{
    struct fcam_model *m = layout_model();
    uint8_t out[192], input[33]; memcpy(input, layout_body, 32); input[32] = 0;
    reject(m, FCAM_OP_VDF_LAYOUT, input, 32, 192, -ENODATA);
    path(m, disabled, out); reject(m, FCAM_OP_VDF_LAYOUT, input, 32, 192, -ENODATA);
    path(m, enabled, out);
    const size_t capacities[] = {0, 128, 191};
    for (size_t i = 0; i < sizeof(capacities) / sizeof(capacities[0]); ++i)
        reject(m, FCAM_OP_VDF_LAYOUT, input, 32, capacities[i], -ENOSPC);
    reject(m, FCAM_OP_VDF_LAYOUT, NULL, 0, 192, -EINVAL);
    reject(m, FCAM_OP_VDF_LAYOUT, input, 31, 192, -EINVAL);
    reject(m, FCAM_OP_VDF_LAYOUT, input, 33, 192, -EINVAL);
    for (size_t i = 0; i < 32; ++i) {
        input[i] ^= 0x80u;
        reject(m, FCAM_OP_VDF_LAYOUT, input, 32, 192, -ENOTSUP);
        input[i] ^= 0x80u;
    }
    uint64_t *counters[] = {&m->generation, &m->proof.serial, &m->frame_generation, &m->rendered,
        &m->consumed, &m->retired, &m->owner.info.generation, &m->owner.info.counts.staged,
        &m->owner.info.counts.rendered, &m->owner.info.counts.read, &m->owner.info.counts.retired};
    for (size_t i = 0; i < sizeof(counters) / sizeof(counters[0]); ++i) {
        const uint64_t old = *counters[i]; *counters[i] = UINT64_MAX;
        reject(m, FCAM_OP_VDF_LAYOUT, input, 32, 192, -EOVERFLOW); *counters[i] = old;
    }
    m->busy = 1; reject(m, FCAM_OP_VDF_LAYOUT, input, 32, 192, -EBUSY); m->busy = 0;
    m->vdf_busy = 1; reject(m, FCAM_OP_VDF_LAYOUT, input, 32, 192, -EBUSY); m->vdf_busy = 0;
    struct fcam_exec_result result;
    assert(fcam_model_request(m, FCAM_OP_VDF_LAYOUT, NULL, 32, out, 192, &result) == -EINVAL);
    assert(fcam_model_request(m, FCAM_OP_VDF_LAYOUT, input, 32, NULL, 192, &result) == -EINVAL);
    assert(fcam_model_request(m, FCAM_OP_VDF_LAYOUT, input, 32, input, 192, &result) == -EINVAL);
    assert(fcam_model_request(m, FCAM_OP_VDF_LAYOUT, input, 32, m->vdf_sink, 192, &result) == -EINVAL);
    assert(fcam_model_request(m, FCAM_OP_VDF_LAYOUT, m->layout_config, 32, out, 192, &result) == -EINVAL);
    assert(fcam_model_request(m, FCAM_OP_VDF_LAYOUT, (const uint8_t *)(UINTPTR_MAX - 3u), 32,
                              out, 192, &result) == -EINVAL);
    optical_frame_lease live;
    assert(optical_frame_acquire(&m->owner, m->pool, FRAME_CAPACITY, &live) == OPTICAL_FRAME_OK);
    reject(m, FCAM_OP_VDF_LAYOUT, input, 32, 192, -EBUSY);
    assert(optical_frame_retire(&m->owner, &live) == OPTICAL_FRAME_OK);
    fcam_model_destroy(m);
    m = model(); path(m, enabled, out);
    reject(m, FCAM_OP_VDF_LAYOUT, layout_body, 32, 192, -ENOTSUP);
    fcam_model_destroy(m);
}
static void layout_pending(void)
{
    struct fcam_model *m = layout_model();
    uint8_t out[192], still[16] = {0}, config[48] = {0};
    path(m, enabled, out);
    put32(still, FCAM_STILL_FULL_JPEG); put32(still + 4, 16);
    put32(still + 8, 16); put32(still + 12, 90);
    struct fcam_exec_result result;
    assert(fcam_model_request(m, FCAM_OP_STILL, still, 16, out, 1, &result) == 0);
    const uint64_t token = m->token, hash = fnv(m->result_data, m->result_size);
    reject(m, FCAM_OP_VDF_LAYOUT, layout_body, 32, 192, -EBUSY);
    assert(m->token == token && fnv(m->result_data, m->result_size) == hash);
    assert(fcam_model_request(m, FCAM_OP_CANCEL, NULL, 0, out, 128, &result) == 0);
    put32(config, 640); put32(config + 4, 480); put32(config + 8, 30);
    put32(config + 12, 90); put32(config + 16, 400); put32(config + 20, 100);
    put64(config + 24, 2500); put64(config + 32, 1000000);
    assert(fcam_model_request(m, FCAM_OP_VIDEO_BEGIN, config, 48, out, 128, &result) == 0);
    const struct video_engine_stream_info before = video_engine_stream_snapshot(m->video);
    reject(m, FCAM_OP_VDF_LAYOUT, layout_body, 32, 192, -EBUSY);
    const struct video_engine_stream_info after = video_engine_stream_snapshot(m->video);
    assert(before.frames_consumed == after.frames_consumed && before.packets_received == after.packets_received);
    assert(fcam_model_request(m, FCAM_OP_CANCEL, NULL, 0, out, 128, &result) == 0);
    layout(m, layout_body, out);
    fcam_model_destroy(m);
}
static void layout_failures(void)
{
    for (enum injection test = CONFIG_FAIL; test <= NO_CONSUMER; ++test) {
        struct fcam_model *m = layout_model();
        uint8_t out[192]; path(m, enabled, out);
        if (test != CONFIG_FAIL) layout(m, layout_body, out);
        const struct fcam_model before = *m;
        struct fcam_exec_result result, saved;
        memset(out, 0xa5, sizeof(out)); memset(&result, 0x59, sizeof(result));
        memcpy(&saved, &result, sizeof(saved));
        inject = test; subject = m;
        assert(fcam_model_request(m, FCAM_OP_VDF_LAYOUT, layout_body, 32, out, 192, &result) == -EIO);
        inject = NONE; subject = NULL;
        for (size_t i = 0; i < sizeof(out); ++i) assert(out[i] == 0xa5);
        assert(!memcmp(&result, &saved, sizeof(saved)) &&
               !memcmp(m->layout_config, before.layout_config, sizeof(m->layout_config)) &&
               m->layout_valid == before.layout_valid &&
               !memcmp(&m->config, &before.config, sizeof(m->config)) &&
               !memcmp(m->vdf_config, before.vdf_config, sizeof(m->vdf_config)) &&
               !memcmp(m->zebra_config, before.zebra_config, sizeof(m->zebra_config)) &&
               m->generation == before.generation && m->frame_generation == before.frame_generation &&
               m->vdf_class == 1 && m->vdf_busy && m->stream_state == 3 && !m->token && !m->result_data &&
               m->packet_generation == before.packet_generation && !m->jpeg_encoded && !m->video_encoded &&
               m->result_read == before.result_read && m->next_token == before.next_token);
        struct fcam_frame_proof proof;
        assert(fcam_model_proof_snapshot(m, &proof, sizeof(proof)) == 0 &&
               proof.opcode == FCAM_OP_VDF_LAYOUT && proof.consumer_kind == FCAM_PROOF_VDF &&
               proof.operation_status == -EIO && proof.config_generation == before.generation &&
               proof.frame_generation == before.frame_generation && !proof.encoder_consumed &&
               !proof.encoded_bytes && !proof.result_bytes && !proof.result_token);
        if (test == CONFIG_FAIL) assert(!memcmp(&proof.before, &proof.after, sizeof(proof.before)));
        else {
            assert(m->rendered == before.rendered + 1 && proof.render_observed &&
                   m->owner.info.generation == before.owner.info.generation + 1 && proof.lease_generation &&
                   m->consumed == before.consumed + (unsigned)(test == STALE_RETIRE || test == CONFIG_CHANGED));
            if (test == STALE_RETIRE) {
                assert(!proof.retired && proof.retire_status == OPTICAL_FRAME_STALE && m->retired == before.retired);
                assert(fcam_model_request(m, FCAM_OP_CANCEL, NULL, 0, out, 128, &result) == -EIO);
                optical_frame_lease lease = {&m->owner, m->owner.info.generation, m->pool, FRAME_CAPACITY};
                assert(optical_frame_retire(&m->owner, &lease) == OPTICAL_FRAME_OK);
            } else assert(proof.retired && m->retired == before.retired + 1);
            if (test == ZERO_LEASE || test == WRONG_LEASE)
                assert(proof.consumer_status == OPTICAL_FRAME_STALE && !proof.consumer_entered &&
                       m->owner.info.counts.read == before.owner.info.counts.read);
            if (test == PARTIAL_COPY) assert(m->vdf_copied == 640u * 479u * 3u);
            if (test == SINK_CHANGED) assert(proof.source_fnv1a64 != proof.consumer_after_fnv1a64);
            if (test == NO_CONSUMER) assert(!proof.consumer_entered && !proof.consumer_returned && !m->vdf_copied);
        }
        reject(m, FCAM_OP_VDF_LAYOUT, layout_body, 32, 192, -EIO);
        assert(fcam_model_request(m, FCAM_OP_CANCEL, NULL, 0, out, 128, &result) == 0);
        layout(m, layout_body, out);
        fcam_model_destroy(m);
    }
}
static const uint8_t peaking_off[FCAM_DISPLAY_INPUT_BYTES] = {
    0x52, 0x01, 0, 0, 8, 0, 0, 0, 3, 0, 1, 0, 0, 235, 128, 128};
static const uint8_t flag_off[FCAM_DISPLAY_INPUT_BYTES] = {0x62, 0x01, 0, 0, 2};
static void display(struct fcam_model *m, const uint8_t input[FCAM_DISPLAY_INPUT_BYTES],
                      uint8_t out[FCAM_DISPLAY_RESULT_BYTES])
{
    const struct fcam_model before = *m;
    const size_t slot = get32(input) == 0x0141u ? 2u : (size_t)(get32(input) == 0x0162u);
    struct fcam_exec_result result;
    assert(fcam_model_request(m, FCAM_OP_VDF_DISPLAY_CONFIG, input, FCAM_DISPLAY_INPUT_BYTES,
                              out, FCAM_DISPLAY_RESULT_BYTES, &result) == 0);
    assert(result.used == 176 && !result.token && !result.total && !result.offset);
    assert(!memcmp(&m->config, &before.config, sizeof(m->config)) &&
           !memcmp(m->vdf_config, before.vdf_config, sizeof(m->vdf_config)) &&
           !memcmp(m->zebra_config, before.zebra_config, sizeof(m->zebra_config)) &&
           !memcmp(m->layout_config, before.layout_config, sizeof(m->layout_config)) &&
           m->layout_valid == before.layout_valid &&
           !memcmp(m->display_staged[slot], input, FCAM_DISPLAY_INPUT_BYTES) &&
           !memcmp(m->display_config[slot], input, FCAM_DISPLAY_INPUT_BYTES) &&
           !memcmp(out + FCAM_DISPLAY_R_CONFIG, input, FCAM_DISPLAY_INPUT_BYTES) &&
           !memcmp(out + FCAM_VDF_R_CONFIG, before.vdf_config, FCAM_VDF_INPUT_BYTES));
    for (size_t other = 0; other < 3; ++other)
        if (other != slot) assert(!memcmp(m->display_config[other], before.display_config[other], FCAM_DISPLAY_INPUT_BYTES));
    assert(m->generation == before.generation + 1 && m->frame_generation == before.frame_generation + 1 &&
           m->rendered == before.rendered + 1 && m->consumed == before.consumed + 1 &&
           m->retired == before.retired + 1 && m->jpeg_encoded == before.jpeg_encoded &&
           m->video_encoded == before.video_encoded && m->packet_generation == before.packet_generation &&
           m->result_read == before.result_read && m->next_token == before.next_token &&
           !m->token && !m->result_data && m->vdf_class == 1 && !m->vdf_busy && !m->stream_state &&
           m->owner.info.generation == before.owner.info.generation + 1 &&
           m->owner.info.counts.read == before.owner.info.counts.read + 1);
    const size_t bytes = (size_t)m->config.width * m->config.height * 3u;
    assert(m->vdf_sink != m->pool && m->vdf_copied == bytes && !memcmp(m->vdf_sink, m->pool, bytes));
    struct fcam_frame_proof proof;
    assert(fcam_model_proof_snapshot(m, &proof, sizeof(proof)) == 0 && sizeof(proof) == 376);
    assert(proof.opcode == FCAM_OP_VDF_DISPLAY_CONFIG && proof.consumer_kind == FCAM_PROOF_VDF &&
           proof.serial == before.proof.serial + 1 && proof.config_generation == m->generation &&
           proof.frame_generation == m->frame_generation && proof.lease_generation == m->owner.info.generation &&
           proof.width == m->config.width && proof.height == m->config.height &&
           proof.stride == m->config.width * 3u && proof.active_bytes == bytes &&
           proof.source_fnv1a64 == fnv(m->pool, bytes) &&
           proof.source_fnv1a64 == proof.consumer_before_fnv1a64 &&
           proof.consumer_after_fnv1a64 == fnv(m->vdf_sink, bytes) &&
           proof.source_fnv1a64 == proof.consumer_after_fnv1a64 && proof.render_observed &&
           proof.consumer_entered && proof.consumer_returned && proof.retired &&
           proof.source_state == OPTICAL_FRAME_RENDERED && proof.consumer_before_state == OPTICAL_FRAME_READING &&
           proof.consumer_after_state == OPTICAL_FRAME_READING && proof.final_state == OPTICAL_FRAME_IDLE &&
           proof.render_status == OPTICAL_FRAME_OK && proof.consumer_status == OPTICAL_FRAME_OK &&
           proof.retire_status == OPTICAL_FRAME_OK && !proof.operation_status && !proof.encoder_consumed &&
           !proof.encoded_bytes && !proof.result_bytes && !proof.result_token &&
           proof.before.rendered == before.rendered && proof.after.rendered == m->rendered &&
           proof.before.consumed == before.consumed && proof.after.consumed == m->consumed);
}
static void display_success(void)
{
    struct fcam_model *m = fcam_model_create(77);
    assert(m && m->generation == 1);
    uint8_t out[192], route[16], input[16], state_reply[128];
    struct fcam_exec_result result;
    reject(m, FCAM_OP_VDF_DISPLAY_CONFIG, peaking_off, 16, 176, -ENODATA);
    reject(m, FCAM_OP_VDF_DISPLAY_CONFIG, flag_off, 16, 176, -ENODATA);
    assert(!m->vdf_sink && !m->rendered);
    assert(fcam_model_request(m, FCAM_OP_INIT, NULL, 0, out, 128, &result) == 0);
    memcpy(route, enabled, 16); route[3] = 0xa9; route[4] = 2; route[8] = 0x67;
    path(m, route, out);
    assert(fcam_model_request(m, FCAM_OP_VDF_ZEBRA, zebra_disabled, 8, out, 168, &result) == 0);
    layout(m, layout_body, out);
    emit("DISPLAY_ROUTE", route, 16); emit("PEAKING_INPUT", peaking_off, 16); emit("FLAG_INPUT", flag_off, 16);
    memcpy(input, peaking_off, 16); display(m, input, out); emit("PEAKING", out, 176);
    emit("PEAKING_SOURCE", m->pool, m->vdf_copied); emit("PEAKING_SINK", m->vdf_sink, m->vdf_copied);
    memset(input, 0xa5, sizeof(input));
    assert(!memcmp(m->display_config[0], peaking_off, 16));
    display(m, flag_off, out); emit("FLAG", out, 176);
    emit("FLAG_SOURCE", m->pool, m->vdf_copied); emit("FLAG_SINK", m->vdf_sink, m->vdf_copied);
    assert(m->generation == 6 && m->frame_generation == 6 && m->rendered == 6 && m->consumed == 5 && m->retired == 6);
    const struct fcam_model snapshot = *m;
    assert(fcam_model_request(m, FCAM_OP_STATE, NULL, 0, state_reply, 128, &result) == 0);
    assert(fcam_model_request(m, FCAM_OP_INIT, NULL, 0, out, 128, &result) == 0);
    assert(!memcmp(m, &snapshot, sizeof(snapshot)) && !memcmp(out, state_reply, 128));
    emit("DISPLAY_STATE", state_reply, 128);
    display(m, peaking_off, out); emit("PEAKING_REPEAT", out, 176);
    assert(!memcmp(m->display_config[1], flag_off, 16));
    path(m, disabled, out);
    reject(m, FCAM_OP_VDF_DISPLAY_CONFIG, peaking_off, 16, 176, -ENODATA);
    reject(m, FCAM_OP_VDF_DISPLAY_CONFIG, flag_off, 16, 176, -ENODATA);
    assert(!memcmp(m->display_config[0], peaking_off, 16) && !memcmp(m->display_config[1], flag_off, 16));
    fcam_model_destroy(m);
    m = model(); path(m, enabled, out);
    static const uint8_t palettes[4][3] = {{81, 90, 240}, {210, 16, 146}, {29, 255, 83}, {235, 128, 128}};
    static const uint8_t magnifications[3] = {0, 10, 40};
    for (size_t i = 0; i < 4; ++i) {
        memcpy(input, peaking_off, 16); input[10] = (uint8_t)(i % 3u); input[11] = magnifications[i % 3u];
        memcpy(input + 13, palettes[i], 3); display(m, input, out);
    }
    display(m, flag_off, out);
    assert(!m->layout_valid && m->config.width == 128 && m->config.height == 64);
    const uint8_t refresh[FCAM_DISPLAY_INPUT_BYTES] = {0x41, 0x01};
    display(m, refresh, out);
    assert(!memcmp(m->display_config[2], refresh, sizeof(refresh)));
    memcpy(input, refresh, sizeof(input)); input[4] = 1;
    reject(m, FCAM_OP_VDF_DISPLAY_CONFIG, input, 16, 176, -EINVAL);
    memcpy(input, refresh, sizeof(input)); input[8] = 1;
    reject(m, FCAM_OP_VDF_DISPLAY_CONFIG, input, 16, 176, -EINVAL);
    path(m, disabled, out);
    reject(m, FCAM_OP_VDF_DISPLAY_CONFIG, refresh, 16, 176, -ENODATA);
    fcam_model_destroy(m);
}
static void display_validation(void)
{
    struct fcam_model *m = model();
    uint8_t out[192], input[17];
    path(m, enabled, out);
    const uint8_t *features[] = {peaking_off, flag_off};
    for (size_t feature = 0; feature < 2; ++feature) {
        memcpy(input, features[feature], 16); input[16] = 0;
        reject(m, FCAM_OP_VDF_DISPLAY_CONFIG, NULL, 0, 176, -EINVAL);
        reject(m, FCAM_OP_VDF_DISPLAY_CONFIG, input, 15, 176, -EINVAL);
        reject(m, FCAM_OP_VDF_DISPLAY_CONFIG, input, 17, 176, -EINVAL);
        reject(m, FCAM_OP_VDF_DISPLAY_CONFIG, input, 16, 0, -ENOSPC);
        reject(m, FCAM_OP_VDF_DISPLAY_CONFIG, input, 16, 175, -ENOSPC);
        for (size_t i = 0; i < 8; ++i) {
            input[i] ^= 0x80u;
            reject(m, FCAM_OP_VDF_DISPLAY_CONFIG, input, 16, 176, i < 4 ? -ENOTSUP : -EINVAL);
            input[i] ^= 0x80u;
        }
        uint64_t *counters[] = {&m->generation, &m->proof.serial, &m->frame_generation, &m->rendered,
            &m->consumed, &m->retired, &m->owner.info.generation, &m->owner.info.counts.staged,
            &m->owner.info.counts.rendered, &m->owner.info.counts.read, &m->owner.info.counts.retired};
        for (size_t i = 0; i < sizeof(counters) / sizeof(counters[0]); ++i) {
            const uint64_t old = *counters[i]; *counters[i] = UINT64_MAX;
            reject(m, FCAM_OP_VDF_DISPLAY_CONFIG, input, 16, 176, -EOVERFLOW); *counters[i] = old;
        }
        m->busy = 1; reject(m, FCAM_OP_VDF_DISPLAY_CONFIG, input, 16, 176, -EBUSY); m->busy = 0;
        m->vdf_busy = 1; reject(m, FCAM_OP_VDF_DISPLAY_CONFIG, input, 16, 176, -EBUSY); m->vdf_busy = 0;
        struct fcam_exec_result result;
        assert(fcam_model_request(m, FCAM_OP_VDF_DISPLAY_CONFIG, NULL, 16, out, 176, &result) == -EINVAL);
        assert(fcam_model_request(m, FCAM_OP_VDF_DISPLAY_CONFIG, input, 16, NULL, 176, &result) == -EINVAL);
        assert(fcam_model_request(m, FCAM_OP_VDF_DISPLAY_CONFIG, input, 16, input, 176, &result) == -EINVAL);
        assert(fcam_model_request(m, FCAM_OP_VDF_DISPLAY_CONFIG, input, 16, m->vdf_sink, 176, &result) == -EINVAL);
        assert(fcam_model_request(m, FCAM_OP_VDF_DISPLAY_CONFIG, m->display_config[feature], 16,
                                  out, 176, &result) == -EINVAL);
        assert(fcam_model_request(m, FCAM_OP_VDF_DISPLAY_CONFIG, (const uint8_t *)(UINTPTR_MAX - 3u),
                                  16, out, 176, &result) == -EINVAL);
    }
    memcpy(input, peaking_off, 16);
    for (size_t i = 8; i < 16; ++i) {
        input[i] ^= 0x80u; reject(m, FCAM_OP_VDF_DISPLAY_CONFIG, input, 16, 176, -ENOTSUP); input[i] ^= 0x80u;
    }
    input[9] = 1; reject(m, FCAM_OP_VDF_DISPLAY_CONFIG, input, 16, 176, -ENOTSUP); input[9] = 0;
    input[10] = 3; reject(m, FCAM_OP_VDF_DISPLAY_CONFIG, input, 16, 176, -ENOTSUP); input[10] = 1;
    input[11] = 1; reject(m, FCAM_OP_VDF_DISPLAY_CONFIG, input, 16, 176, -ENOTSUP);
    memcpy(input, flag_off, 16);
    for (size_t i = 8; i < 16; ++i) {
        input[i] = 1; reject(m, FCAM_OP_VDF_DISPLAY_CONFIG, input, 16, 176, i < 10 ? -ENOTSUP : -EINVAL); input[i] = 0;
    }
    optical_frame_lease live;
    assert(optical_frame_acquire(&m->owner, m->pool, FRAME_CAPACITY, &live) == OPTICAL_FRAME_OK);
    for (size_t i = 0; i < 2; ++i) reject(m, FCAM_OP_VDF_DISPLAY_CONFIG, features[i], 16, 176, -EBUSY);
    assert(optical_frame_retire(&m->owner, &live) == OPTICAL_FRAME_OK);
    uint8_t still[16] = {0};
    put32(still, FCAM_STILL_FULL_JPEG); put32(still + 4, 16); put32(still + 8, 16); put32(still + 12, 90);
    struct fcam_exec_result result;
    assert(fcam_model_request(m, FCAM_OP_STILL, still, 16, out, 1, &result) == 0);
    const uint64_t token = m->token, hash = fnv(m->result_data, m->result_size);
    for (size_t i = 0; i < 2; ++i) reject(m, FCAM_OP_VDF_DISPLAY_CONFIG, features[i], 16, 176, -EBUSY);
    assert(m->token == token && fnv(m->result_data, m->result_size) == hash);
    assert(fcam_model_request(m, FCAM_OP_CANCEL, NULL, 0, out, 128, &result) == 0);
    uint8_t config[48] = {0};
    put32(config, 128); put32(config + 4, 64); put32(config + 8, 25); put32(config + 12, 90);
    put32(config + 16, 400); put32(config + 20, 100); put64(config + 24, 2500); put64(config + 32, 1000000);
    assert(fcam_model_request(m, FCAM_OP_VIDEO_BEGIN, config, 48, out, 128, &result) == 0);
    const struct video_engine_stream_info before = video_engine_stream_snapshot(m->video);
    for (size_t i = 0; i < 2; ++i) reject(m, FCAM_OP_VDF_DISPLAY_CONFIG, features[i], 16, 176, -EBUSY);
    const struct video_engine_stream_info after = video_engine_stream_snapshot(m->video);
    assert(before.state == after.state && before.frames_consumed == after.frames_consumed &&
           before.packets_received == after.packets_received);
    assert(fcam_model_request(m, FCAM_OP_CANCEL, NULL, 0, out, 128, &result) == 0);
    fcam_model_destroy(m);
}
static void display_failures(void)
{
    for (size_t feature = 0; feature < 2; ++feature)
        for (enum injection test = CONFIG_FAIL; test <= NO_CONSUMER; ++test) {
            struct fcam_model *m = model();
            uint8_t out[192], input[16]; path(m, enabled, out);
            display(m, peaking_off, out); display(m, flag_off, out);
            memcpy(input, feature ? flag_off : peaking_off, 16);
            if (!feature) { input[10] = 2; input[11] = 40; }
            const struct fcam_model before = *m;
            struct fcam_exec_result result, saved;
            memset(out, 0xa5, sizeof(out)); memset(&result, 0x59, sizeof(result));
            memcpy(&saved, &result, sizeof(saved));
            display_fault_slot = feature;
            inject = test; subject = m;
            assert(fcam_model_request(m, FCAM_OP_VDF_DISPLAY_CONFIG, input, 16, out, 176, &result) == -EIO);
            inject = NONE; subject = NULL;
            for (size_t i = 0; i < sizeof(out); ++i) assert(out[i] == 0xa5);
            assert(!memcmp(&result, &saved, sizeof(saved)) &&
                   !memcmp(m->display_config, before.display_config, sizeof(m->display_config)) &&
                   !memcmp(&m->config, &before.config, sizeof(m->config)) &&
                   !memcmp(m->vdf_config, before.vdf_config, sizeof(m->vdf_config)) &&
                   !memcmp(m->zebra_config, before.zebra_config, sizeof(m->zebra_config)) &&
                   !memcmp(m->layout_config, before.layout_config, sizeof(m->layout_config)) &&
                   m->layout_valid == before.layout_valid && m->generation == before.generation &&
                   m->frame_generation == before.frame_generation && m->vdf_class == 1 &&
                   m->vdf_busy && m->stream_state == 3 && !m->token && !m->result_data &&
                   !m->jpeg_encoded && !m->video_encoded && m->packet_generation == before.packet_generation &&
                   m->result_read == before.result_read && m->next_token == before.next_token);
            struct fcam_frame_proof proof;
            assert(fcam_model_proof_snapshot(m, &proof, sizeof(proof)) == 0 &&
                   proof.opcode == FCAM_OP_VDF_DISPLAY_CONFIG && proof.consumer_kind == FCAM_PROOF_VDF &&
                   proof.operation_status == -EIO && proof.config_generation == before.generation &&
                   proof.frame_generation == before.frame_generation && !proof.encoder_consumed &&
                   !proof.encoded_bytes && !proof.result_bytes && !proof.result_token);
            if (test == CONFIG_FAIL) assert(!memcmp(&proof.before, &proof.after, sizeof(proof.before)));
            else {
                assert(m->rendered == before.rendered + 1 && proof.render_observed &&
                       m->owner.info.generation == before.owner.info.generation + 1 &&
                       m->consumed == before.consumed + (unsigned)(test == STALE_RETIRE || test == CONFIG_CHANGED));
                if (test == STALE_RETIRE) {
                    assert(!proof.retired && proof.retire_status == OPTICAL_FRAME_STALE && m->retired == before.retired);
                    assert(fcam_model_request(m, FCAM_OP_CANCEL, NULL, 0, out, 128, &result) == -EIO);
                    optical_frame_lease lease = {&m->owner, m->owner.info.generation, m->pool, FRAME_CAPACITY};
                    assert(optical_frame_retire(&m->owner, &lease) == OPTICAL_FRAME_OK);
                } else assert(proof.retired && m->retired == before.retired + 1);
                if (test == ZERO_LEASE || test == WRONG_LEASE)
                    assert(proof.consumer_status == OPTICAL_FRAME_STALE && !proof.consumer_entered);
                if (test == PARTIAL_COPY) assert(m->vdf_copied == 128u * 63u * 3u);
                if (test == SINK_CHANGED) assert(proof.source_fnv1a64 != proof.consumer_after_fnv1a64);
                if (test == NO_CONSUMER) assert(!proof.consumer_entered && !proof.consumer_returned && !m->vdf_copied);
            }
            reject(m, FCAM_OP_VDF_DISPLAY_CONFIG, input, 16, 176, -EIO);
            assert(fcam_model_request(m, FCAM_OP_CANCEL, NULL, 0, out, 128, &result) == 0);
            display(m, input, out);
            fcam_model_destroy(m);
        }
}
int main(int argc, char **argv)
{
    av_log_set_level(AV_LOG_ERROR);
    if (argc == 2 && !strcmp(argv[1], "display")) {
        display_success(); display_validation(); display_failures();
    } else if (argc == 2 && !strcmp(argv[1], "layout")) {
        layout_success(); layout_validation(); layout_pending(); layout_failures();
    } else if (argc == 2 && !strcmp(argv[1], "zebra")) {
        zebra_success(); zebra_validation(); zebra_pending(); zebra_failures();
    } else {
        assert(argc == 1);
        success(); validation(); pending(); failures();
    }
    assert(fflush(stdout) == 0);
    return 0;
}
