/* SPDX-License-Identifier: MIT */
/* Real owner transactions with faults at allocation/config/copy/readback/retire. */
#include "../virtual-optical-frame-owner/optical-frame-owner.h"
#include <assert.h>
#include <stdlib.h>
#include <string.h>
static optical_frame_status checked_configure(optical_frame_owner *, const optical_frame_config *);
static optical_frame_status checked_render(optical_frame_owner *, const optical_frame_lease *);
static optical_frame_status checked_read(optical_frame_owner *, const optical_frame_lease *,
                                          optical_frame_consumer, void *);
static optical_frame_status checked_retire(optical_frame_owner *, const optical_frame_lease *);
static void *checked_malloc(size_t);
static void *checked_copy(void *, const void *, size_t);
#define optical_frame_configure checked_configure
#define optical_frame_render checked_render
#define optical_frame_consumer_read checked_read
#define optical_frame_retire checked_retire
#define malloc checked_malloc
#define memcpy checked_copy
#include "functional-camera-core.c"
#undef optical_frame_configure
#undef optical_frame_render
#undef optical_frame_consumer_read
#undef optical_frame_retire
#undef malloc
#undef memcpy
#include <libavutil/log.h>
_Static_assert(FCAM_MAILBOX_PAGES == 16 && FCAM_STATE_BYTES == 128, "old mailbox/state ABI");
_Static_assert(FCAM_VDF_RESULT_MAX_BYTES == 192, "old VDF owners remain bounded");
_Static_assert(FCAM_BB_RESULT_BYTES == 192 && FCAM_HIST_RESULT_BYTES == 1192, "new fixed replies");
_Static_assert(FCAM_HIST_R_BINS + FCAM_HIST_BINS == FCAM_HIST_RESULT_BYTES, "histogram extent");
_Static_assert(FCAM_BB_PROOF_KIND == FCAM_PROOF_BB_STARTUP &&
               FCAM_HIST_PROOF_KIND == FCAM_PROOF_HISTOGRAM, "proof class values");

enum injection { NONE, ALLOCATION, CONFIGURE, RENDER, SOURCE_BEFORE, SOURCE_AFTER,
    PARTIAL_COPY, SINK_CHANGED, ZERO_LEASE, WRONG_LEASE, NO_CONSUMER, RETIRE,
    STAGED, STAGED_AFTER, POLICY_CHANGED, COMMITTED, CACHE, CACHE_READBACK, POST_RETIRE };
static enum injection inject;
static struct fcam_model *subject;
static int hist_subject, feature_subject;
static int injected_once;
static uint8_t *stage_config(void)
{
    return hist_subject ? subject->hist_staged : subject->bb_staged[feature_subject];
}
static uint8_t *saved_config(void)
{
    return hist_subject ? subject->hist_config : subject->bb_config[feature_subject];
}
static uint8_t *result_cache(void)
{
    return hist_subject ? subject->hist_result : subject->bb_result;
}
static void *checked_malloc(size_t bytes)
{
    if (subject && inject == ALLOCATION) return NULL;
    return malloc(bytes);
}
static void *checked_copy(void *destination, const void *source, size_t bytes)
{
    void *result = memcpy(destination, source, bytes);
    if (!subject || !subject->vdf_busy || injected_once || !bytes) return result;
    if ((inject == STAGED && destination == stage_config()) ||
        (inject == COMMITTED && destination == saved_config()) ||
        (inject == CACHE && destination == result_cache()) ||
        (inject == CACHE_READBACK && source == result_cache())) {
        ((uint8_t *)destination)[bytes - 1] ^= 1u;
        injected_once = 1;
    }
    return result;
}
static optical_frame_status checked_configure(optical_frame_owner *owner, const optical_frame_config *config)
{
    if (inject == CONFIGURE) {
        optical_frame_config invalid = *config;
        invalid.params.f_number = 0;
        return optical_frame_configure(owner, &invalid);
    }
    return optical_frame_configure(owner, config);
}
static optical_frame_status checked_render(optical_frame_owner *owner, const optical_frame_lease *lease)
{
    if (inject == RENDER) {
        optical_frame_lease stale = *lease;
        --stale.generation;
        return optical_frame_render(owner, &stale);
    }
    return optical_frame_render(owner, lease);
}
static int source_after(const optical_frame_view *view, void *context)
{
    const int result = vdf_copy(view, context);
    subject->pool[0] ^= 1u;
    return result;
}
static optical_frame_status checked_read(optical_frame_owner *owner, const optical_frame_lease *lease,
                                          optical_frame_consumer consumer, void *context)
{
    if (inject == SOURCE_BEFORE) subject->pool[0] ^= 1u;
    if (inject == NO_CONSUMER) return OPTICAL_FRAME_OK;
    if (inject == ZERO_LEASE || inject == WRONG_LEASE) {
        optical_frame_lease invalid = *lease;
        if (inject == ZERO_LEASE) invalid.generation = 0;
        else invalid.buffer = subject->vdf_sink;
        return optical_frame_consumer_read(owner, &invalid, consumer, context);
    }
    const size_t capacity = subject ? subject->vdf_capacity : 0;
    if (inject == PARTIAL_COPY) --subject->vdf_capacity;
    const optical_frame_status status = optical_frame_consumer_read(owner, lease,
        inject == SOURCE_AFTER ? source_after : consumer, context);
    if (inject == PARTIAL_COPY) subject->vdf_capacity = capacity;
    if (inject == SINK_CHANGED) subject->vdf_sink[0] ^= 1u;
    if (inject == STAGED_AFTER) stage_config()[0] ^= 1u;
    if (inject == POLICY_CHANGED) {
        if (hist_subject) subject->bb_applied.input_tag ^= 1u;
        else subject->bb_staged_policy.input_tag ^= 1u;
    }
    return status;
}
static optical_frame_status checked_retire(optical_frame_owner *owner, const optical_frame_lease *lease)
{
    if (inject == RETIRE) {
        optical_frame_lease stale = *lease;
        --stale.generation;
        return optical_frame_retire(owner, &stale);
    }
    const optical_frame_status status = optical_frame_retire(owner, lease);
    if (inject == POST_RETIRE && status == OPTICAL_FRAME_OK) subject->vdf_sink[0] ^= 1u;
    return status;
}
static const uint8_t path_on[16] = {1,5,5,0xa9,2,0,0,0,0x67};
static const uint8_t bb_inputs[FCAM_BB_FEATURES + 1][FCAM_BB_INPUT_BYTES] = {
    {0x11,1,28,0,0,0,15,2}, {0x66,1,28,0,0,1}, {0x67,1,2,0,1},
    {0x5f,1,4}, {0x28,1,12,0,0,1,0,0,60},
    {[0]=0x66,[1]=1,[2]=28,[5]=1,[16]=8,[20]=7,[24]=1,[28]=1}};
static const uint8_t hist_input[8] = {0x48,1,4,0,1,1};
static void config_wire(uint8_t config[48])
{
    memset(config, 0, 48);
    put32(config, 640); put32(config + 4, 480); put32(config + 8, 117);
    put32(config + 12, 13); put32(config + 16, 800); put32(config + 20, 640);
    put64(config + 24, 8642); put64(config + 32, UINT64_MAX);
}
static void request(struct fcam_model *m, uint32_t op, const uint8_t *input, size_t bytes,
                     uint8_t *output, size_t capacity)
{
    struct fcam_exec_result result;
    assert(fcam_model_request(m, op, input, bytes, output, capacity, &result) == 0);
    assert(!result.token && !result.total && !result.offset && result.used == capacity);
}
static struct fcam_model *model(int active)
{
    assert(inject == NONE && !subject);
    struct fcam_model *m = fcam_model_create(77);
    assert(m);
    uint8_t config[48], out[160];
    config_wire(config);
    request(m, FCAM_OP_CONFIGURE, config, sizeof(config), out, FCAM_STATE_BYTES);
    if (active) request(m, FCAM_OP_VDF_PATH, path_on, sizeof(path_on), out, sizeof(out));
    return m;
}
static void reject(struct fcam_model *m, uint32_t op, const uint8_t *input,
                    size_t bytes, size_t capacity, int expected)
{
    uint8_t saved[sizeof(*m)], output[FCAM_HIST_RESULT_BYTES + 1];
    struct fcam_exec_result result, old;
    memcpy(saved, m, sizeof(saved));
    memset(output, 0xa5, sizeof(output)); memset(&result, 0x59, sizeof(result));
    memcpy(&old, &result, sizeof(old));
    assert(capacity <= sizeof(output));
    assert(fcam_model_request(m, op, input, bytes, output, capacity, &result) == expected);
    assert(!memcmp(saved, m, sizeof(saved)) && !memcmp(&result, &old, sizeof(old)));
    for (size_t i = 0; i < sizeof(output); ++i) assert(output[i] == 0xa5);
}
static void emit(const char *name, const uint8_t *bytes, size_t count)
{
    assert(printf("BLOB %s %zu\n", name, count) > 0);
    assert(fwrite(bytes, 1, count, stdout) == count);
}
static void transaction(struct fcam_model *m, int feature, const uint8_t *input, const char *name)
{
    const int hist = feature < 0;
    const uint32_t op = hist ? FCAM_OP_HISTOGRAM : FCAM_OP_BB_STARTUP_CONFIG;
    const size_t in_bytes = hist ? FCAM_HIST_INPUT_BYTES : FCAM_BB_INPUT_BYTES;
    const size_t out_bytes = hist ? FCAM_HIST_RESULT_BYTES : FCAM_BB_RESULT_BYTES;
    const struct fcam_model before_state = *m;
    uint8_t output[FCAM_HIST_RESULT_BYTES];
    const struct config config = m->config;
    const uint64_t generation = m->generation, frame = m->frame_generation;
    const struct fcam_proof_counts counts = proof_counts(m);
    request(m, op, input, in_bytes, output, out_bytes);
    assert(m->generation == generation + 1 && m->frame_generation == frame + 1 &&
           m->rendered == counts.rendered + 1 && m->consumed == counts.consumed + 1 &&
           m->retired == counts.retired + 1 && !m->jpeg_encoded && !m->video_encoded &&
           !m->token && !m->result_data && !m->result_read && !m->vdf_busy &&
           !memcmp(&config, &m->config, sizeof(config)) && m->vdf_class == 1 &&
           !memcmp(m->vdf_config, path_on, sizeof(path_on)) &&
           m->owner.info.state == OPTICAL_FRAME_IDLE && m->vdf_copied == 921600 &&
           m->vdf_sink != m->pool && !memcmp(m->pool, m->vdf_sink, m->vdf_copied));
    const struct fcam_model *before = &before_state;
    for (size_t i = 0; i < FCAM_BB_FEATURES; ++i) {
        if (!hist && i == (size_t)feature) {
            assert(m->bb_valid[i] && !memcmp(m->bb_config[i], input, in_bytes));
            assert(!memcmp(m->bb_staged[i], input, in_bytes));
        } else {
            assert(m->bb_valid[i] == before->bb_valid[i]);
            assert(!memcmp(m->bb_config[i], before->bb_config[i], FCAM_BB_INPUT_BYTES));
        }
    }
    assert(!memcmp(m->display_config, before->display_config, sizeof(m->display_config)) &&
           !memcmp(m->layout_config, before->layout_config, sizeof(m->layout_config)) &&
           !memcmp(m->zebra_config, before->zebra_config, sizeof(m->zebra_config)));
    if (hist) {
        assert(m->hist_valid && !memcmp(m->hist_config, input, in_bytes) &&
               !memcmp(m->hist_result, output, out_bytes) &&
               !memcmp(&m->bb_applied, &before->bb_applied, sizeof(m->bb_applied)));
    } else {
        assert(!memcmp(m->bb_result, output, out_bytes) && m->hist_valid == before->hist_valid &&
               !memcmp(m->hist_result, before->hist_result, sizeof(m->hist_result)));
    }
    assert(!memcmp(output + 160, input, in_bytes) &&
           get32(output + FCAM_VDF_R_CLASS) == (hist ? FCAM_HIST_CLASS : FCAM_BB_CLASS) &&
           get64(output + FCAM_VDF_R_INPUT_FNV) == fnv(input, in_bytes) &&
           get64(output + FCAM_VDF_R_BEFORE_CONFIG_GENERATION) == generation &&
           get64(output + FCAM_VDF_R_BEFORE_FRAME_GENERATION) == frame);
    struct fcam_frame_proof proof;
    assert(fcam_model_proof_snapshot(m, &proof, sizeof(proof)) == 0 && sizeof(proof) == 376);
    assert(proof.opcode == op && proof.consumer_kind == (hist ? FCAM_PROOF_HISTOGRAM : FCAM_PROOF_BB_STARTUP) &&
           proof.config_generation == generation + 1 && proof.frame_generation == frame + 1 &&
           proof.render_observed && proof.consumer_entered && proof.consumer_returned && proof.retired &&
           !proof.operation_status && !proof.render_status && !proof.consumer_status && !proof.retire_status &&
           proof.source_fnv1a64 == fnv(m->pool, m->vdf_copied) &&
           proof.source_fnv1a64 == proof.consumer_before_fnv1a64 &&
           proof.source_fnv1a64 == proof.consumer_after_fnv1a64 &&
           !proof.encoder_consumed && !proof.encoded_bytes && !proof.result_token &&
           proof.result_bytes == out_bytes && proof.result_fnv1a64 == fnv(output, out_bytes));
    if (name) emit(name, output, out_bytes);
}
static void mixed(void)
{
    struct fcam_model *m = model(0);
    uint8_t output[FCAM_HIST_RESULT_BYTES];
    request(m, FCAM_OP_INIT, NULL, 0, output, FCAM_STATE_BYTES);
    request(m, FCAM_OP_VDF_PATH, path_on, sizeof(path_on), output, FCAM_VDF_RESULT_BYTES);
    static const uint8_t peaking[16] = {0x52,1,0,0,8,0,0,0,3,0,1,0,0,235,128,128};
    request(m, FCAM_OP_VDF_DISPLAY_CONFIG, peaking, sizeof(peaking), output, FCAM_DISPLAY_RESULT_BYTES);
    static const char *names[] = {"BB_0111", "BB_0166", "BB_0167", "BB_015F", "BB_0128"};
    for (int i = 0; i < (int)FCAM_BB_FEATURES; ++i) transaction(m, i, bb_inputs[i], names[i]);
    assert(!m->bb_applied.sq_mode && !m->bb_applied.sq_rate && m->bb_applied.look[1] == 1 &&
           m->bb_applied.input_tag == 1 && !m->bb_applied.gain_tag &&
           !m->bb_applied.interval_enabled && m->bb_applied.interval_mode == 1 &&
           m->bb_applied.interval_period == 60 && !m->bb_applied.delay_enabled);
    transaction(m, -1, hist_input, "HISTOGRAM");
    emit("ACTUAL_SOURCE", m->pool, m->vdf_copied); emit("ACTUAL_SINK", m->vdf_sink, m->vdf_copied);
    request(m, FCAM_OP_STATE, NULL, 0, output, FCAM_STATE_BYTES);
    emit("BB_STATE", output, FCAM_STATE_BYTES);
    uint8_t changed[FCAM_BB_INPUT_BYTES]; memcpy(changed, bb_inputs[2], sizeof(changed));
    changed[4] = 0; transaction(m, 2, changed, "BB_TAG_ZERO");
    memcpy(changed, bb_inputs[4], sizeof(changed)); changed[8] = 1;
    transaction(m, 4, changed, "BB_PERIOD_ONE");
    transaction(m, 3, bb_inputs[3], "BB_GAIN_REPEAT");
    transaction(m, -1, hist_input, "HISTOGRAM_REPEAT");
    transaction(m, 1, bb_inputs[FCAM_BB_FEATURES], "BB_0166_INITIAL");
    static const uint32_t initial_look[8] = {0,1,0,0,8,7,1,1};
    assert(!memcmp(m->bb_applied.look, initial_look, sizeof initial_look));
    transaction(m, -1, hist_input, "HISTOGRAM_INITIAL");
    const struct bb_policy saved = m->bb_applied;
    struct bb_policy nonzero_gain = saved; nonzero_gain.gain_tag = 12345;
    const struct bb_policy kept = bb_apply(&nonzero_gain, 3, bb_inputs[3]);
    assert(kept.gain_tag == 12345 && !memcmp(&kept, &nonzero_gain, sizeof(kept)));
    const struct fcam_frame_proof proof = m->proof;
    request(m, FCAM_OP_INIT, NULL, 0, output, FCAM_STATE_BYTES);
    assert(!memcmp(&proof, &m->proof, sizeof(proof)));
    fcam_model_destroy(m);
}
static void validation(void)
{
    struct fcam_model *m = model(1);
    for (int feature = -1; feature <= (int)FCAM_BB_FEATURES; ++feature) {
        const int hist = feature < 0;
        const uint32_t op = hist ? FCAM_OP_HISTOGRAM : FCAM_OP_BB_STARTUP_CONFIG;
        const size_t size = hist ? FCAM_HIST_INPUT_BYTES : FCAM_BB_INPUT_BYTES;
        const size_t capacity = hist ? FCAM_HIST_RESULT_BYTES : FCAM_BB_RESULT_BYTES;
        const uint8_t *canonical = hist ? hist_input : bb_inputs[feature];
        uint8_t input[FCAM_BB_INPUT_BYTES + 1]; memcpy(input, canonical, size);
        for (size_t i = 0; i < capacity; ++i) reject(m, op, input, size, i, -ENOSPC);
        for (size_t i = 0; i < size; ++i) reject(m, op, input, i, capacity, -EINVAL);
        reject(m, op, input, size + 1, capacity, -EINVAL);
        input[0] = 0xff; reject(m, op, input, size, capacity, -ENOTSUP); input[0] = canonical[0];
        input[2] ^= 1u; reject(m, op, input, size, capacity, -EINVAL); input[2] = canonical[2];
        for (size_t i = 4; i < size; ++i) {
            input[i] ^= 0x80u;
            const int padding = hist ? i == 7 : i >= 4u + get16(canonical + 2);
            reject(m, op, input, size, capacity, padding ? -EINVAL : -ENOTSUP);
            input[i] = canonical[i];
        }
        uint64_t *counters[] = {&m->generation, &m->frame_generation, &m->proof.serial,
            &m->rendered, &m->consumed, &m->retired, &m->owner.info.generation,
            &m->owner.info.counts.staged, &m->owner.info.counts.rendered,
            &m->owner.info.counts.read, &m->owner.info.counts.retired};
        for (size_t i = 0; i < sizeof(counters) / sizeof(counters[0]); ++i) {
            const uint64_t old = *counters[i]; *counters[i] = UINT64_MAX;
            reject(m, op, canonical, size, capacity, -EOVERFLOW); *counters[i] = old;
        }
        m->busy = 1; reject(m, op, canonical, size, capacity, -EBUSY); m->busy = 0;
        m->vdf_busy = 1; reject(m, op, canonical, size, capacity, -EBUSY); m->vdf_busy = 0;
        m->stream_state = 3; reject(m, op, canonical, size, capacity, -EIO); m->stream_state = 0;
        m->config.width = 128; reject(m, op, canonical, size, capacity, -ENOTSUP); m->config.width = 640;
        m->vdf_class = 0; reject(m, op, canonical, size, capacity, -ENODATA); m->vdf_class = 1;
        struct fcam_exec_result result;
        uint8_t output[FCAM_HIST_RESULT_BYTES];
        assert(fcam_model_request(m, op, NULL, size, output, capacity, &result) == -EINVAL);
        assert(fcam_model_request(m, op, canonical, size, NULL, capacity, &result) == -EINVAL);
        assert(fcam_model_request(m, op, input, size, input, capacity, &result) == -EINVAL);
        assert(fcam_model_request(m, op, m->bb_config[0], size, output, capacity, &result) == -EINVAL);
        assert(fcam_model_request(m, op, canonical, size, m->hist_result, capacity, &result) == -EINVAL);
        assert(fcam_model_request(m, op, canonical, size, m->vdf_sink, capacity, &result) == -EINVAL);
        assert(fcam_model_request(m, op, canonical, size, output, FCAM_DATA_BYTES + 1, &result) == -E2BIG);
        assert(fcam_model_request(m, op, (const uint8_t *)(UINTPTR_MAX - 3u), size,
                                  output, capacity, &result) == -EINVAL);
        optical_frame_lease live;
        assert(optical_frame_acquire(&m->owner, m->pool, FRAME_CAPACITY, &live) == OPTICAL_FRAME_OK);
        reject(m, op, canonical, size, capacity, -EBUSY);
        assert(optical_frame_retire(&m->owner, &live) == OPTICAL_FRAME_OK);
    }
    for (size_t sample = 1; sample <= FCAM_BB_FEATURES; sample += FCAM_BB_FEATURES - 1) {
        const uint8_t *body = bb_inputs[sample] + 4;
        uint8_t changed[28]; memcpy(changed, body, sizeof changed);
        const struct bb_policy applied = bb_apply(&m->bb_applied, 1, bb_inputs[sample]);
        assert(bb_identity(&applied));
        for (size_t i = 0; i < 8; ++i) {
            struct bb_policy changed_policy = applied;
            changed_policy.look[i] |= UINT32_C(0x80000000);
            assert(!bb_identity(&changed_policy) && !fcam_bb_0166_identity(changed_policy.look));
        }
        assert(fcam_bb_0166_body_valid(body));
        for (size_t offset = 0; offset < sizeof changed; ++offset) {
            for (unsigned int value = 0; value <= 255; ++value) {
                changed[offset] = (uint8_t)value;
                assert(fcam_bb_0166_body_valid(changed) == (value == body[offset]));
            }
            changed[offset] = body[offset];
        }
    }
    uint8_t period[32]; memcpy(period, bb_inputs[4], sizeof(period));
    for (uint32_t value = 0; value <= 61; ++value) {
        put32(period + 8, value);
        assert((bb_validate(period) == 0) == bb_period(value));
    }
    fcam_model_destroy(m);
}
static void pending(void)
{
    struct fcam_model *m = model(1);
    uint8_t output[FCAM_HIST_RESULT_BYTES], still[16] = {1,0,0,0,128,0,0,0,64,0,0,0,90};
    struct fcam_exec_result result;
    assert(fcam_model_request(m, FCAM_OP_STILL, still, sizeof(still), output, 1, &result) == 0);
    const uint64_t token = m->token, hash = fnv(m->result_data, m->result_size);
    for (int i = -1; i <= (int)FCAM_BB_FEATURES; ++i)
        reject(m, i < 0 ? FCAM_OP_HISTOGRAM : FCAM_OP_BB_STARTUP_CONFIG,
               i < 0 ? hist_input : bb_inputs[i], i < 0 ? 8 : 32, i < 0 ? 1192 : 192, -EBUSY);
    assert(m->token == token && fnv(m->result_data, m->result_size) == hash);
    request(m, FCAM_OP_CANCEL, NULL, 0, output, FCAM_STATE_BYTES);
    uint8_t config[48]; config_wire(config);
    m->bb_applied.sq_mode = 1;
    reject(m, FCAM_OP_VIDEO_BEGIN, config, sizeof(config), FCAM_STATE_BYTES, -ENOTSUP);
    m->bb_applied.sq_mode = 0;
    request(m, FCAM_OP_VIDEO_BEGIN, config, sizeof(config), output, FCAM_STATE_BYTES);
    const struct video_engine_stream_info before = video_engine_stream_snapshot(m->video);
    for (int i = -1; i <= (int)FCAM_BB_FEATURES; ++i)
        reject(m, i < 0 ? FCAM_OP_HISTOGRAM : FCAM_OP_BB_STARTUP_CONFIG,
               i < 0 ? hist_input : bb_inputs[i], i < 0 ? 8 : 32, i < 0 ? 1192 : 192, -EBUSY);
    const struct video_engine_stream_info after = video_engine_stream_snapshot(m->video);
    assert(before.state == after.state && before.frames_consumed == after.frames_consumed);
    assert(fcam_model_request(m, FCAM_OP_VIDEO_FRAME, NULL, 0, output, 1, &result) == 0 && result.token);
    const uint64_t video_hash = fnv(m->result_data, m->result_size);
    reject(m, FCAM_OP_HISTOGRAM, hist_input, sizeof(hist_input), FCAM_HIST_RESULT_BYTES, -EBUSY);
    assert(fnv(m->result_data, m->result_size) == video_hash);
    request(m, FCAM_OP_CANCEL, NULL, 0, output, FCAM_STATE_BYTES);
    fcam_model_destroy(m);
}
static void failures(void)
{
    for (int feature = -1; feature <= (int)FCAM_BB_FEATURES; ++feature) {
        const int bank = feature == (int)FCAM_BB_FEATURES ? 1 : feature;
        for (enum injection test = ALLOCATION; test <= POST_RETIRE; ++test) {
            struct fcam_model *m = model(1);
            const int hist = feature < 0;
            const uint32_t op = hist ? FCAM_OP_HISTOGRAM : FCAM_OP_BB_STARTUP_CONFIG;
            const uint8_t *input = hist ? hist_input : bb_inputs[feature];
            const size_t in_bytes = hist ? FCAM_HIST_INPUT_BYTES : FCAM_BB_INPUT_BYTES;
            const size_t out_bytes = hist ? FCAM_HIST_RESULT_BYTES : FCAM_BB_RESULT_BYTES;
            if (test != ALLOCATION) transaction(m, bank, input, NULL);
            else { free(m->vdf_sink); m->vdf_sink = NULL; m->vdf_capacity = 0; }
            uint8_t output[FCAM_HIST_RESULT_BYTES], previous[32], old_cache[FCAM_HIST_RESULT_BYTES];
            uint8_t banks[sizeof(m->bb_config)]; memcpy(banks, m->bb_config, sizeof(banks));
            memcpy(previous, hist ? m->hist_config : m->bb_config[bank], in_bytes);
            memcpy(old_cache, hist ? m->hist_result : m->bb_result, out_bytes);
            const uint64_t generation = m->generation, frame = m->frame_generation;
            const struct bb_policy policy = m->bb_applied;
            const int valid = hist ? m->hist_valid : m->bb_valid[bank];
            struct fcam_exec_result result, old;
            memset(output, 0xa5, sizeof(output)); memset(&result, 0x59, sizeof(result));
            memcpy(&old, &result, sizeof(old));
            subject = m; hist_subject = hist; feature_subject = hist ? 0 : bank;
            injected_once = 0; inject = test;
            assert(fcam_model_request(m, op, input, in_bytes, output, out_bytes, &result) ==
                   (test == ALLOCATION ? -ENOMEM : -EIO));
            inject = NONE; subject = NULL;
            assert(m->generation == generation && m->frame_generation == frame &&
                   valid == (hist ? m->hist_valid : m->bb_valid[bank]) &&
                   !memcmp(previous, hist ? m->hist_config : m->bb_config[bank], in_bytes) &&
                   !memcmp(old_cache, hist ? m->hist_result : m->bb_result, out_bytes) &&
                   !memcmp(banks, m->bb_config, sizeof(banks)) &&
                   !memcmp(&policy, &m->bb_applied, sizeof(policy)) &&
                   !memcmp(&result, &old, sizeof(result)) && !m->token && !m->result_data);
            for (size_t i = 0; i < sizeof(output); ++i) assert(output[i] == 0xa5);
            if (test != ALLOCATION) {
                assert(m->stream_state == 3 && m->vdf_busy && m->proof.operation_status == -EIO &&
                       !m->proof.result_bytes && !m->proof.encoder_consumed);
                if (test == POST_RETIRE) assert(m->proof.source_fnv1a64 != m->proof.consumer_after_fnv1a64);
                if (test == RETIRE) {
                    optical_frame_lease live = {&m->owner, m->owner.info.generation, m->pool, FRAME_CAPACITY};
                    assert(optical_frame_retire(&m->owner, &live) == OPTICAL_FRAME_OK);
                }
                reject(m, op, input, in_bytes, out_bytes, -EIO);
                request(m, FCAM_OP_CANCEL, NULL, 0, output, FCAM_STATE_BYTES);
            }
            fcam_model_destroy(m);
        }
    }
}
static void known_histograms(void)
{
    uint8_t bins[FCAM_HIST_BINS_BYTES];
    static const uint8_t small[] = {0,0,0, 255,0,0, 0,255,0, 0,0,255,
        255,255,255, 0,0,0, 0,0,0, 128,16,231, 128,16,231};
    assert(histogram(small, sizeof(small), bins) == 0);
    emit("SMALL_RGB", small, sizeof(small)); emit("SMALL_BINS", bins, sizeof(bins));
    uint8_t gradient[256 * 3], flat[8 * 3];
    for (size_t i = 0; i < 256; ++i) {
        gradient[i * 3] = (uint8_t)i;
        gradient[i * 3 + 1] = (uint8_t)(255 - i);
        gradient[i * 3 + 2] = (uint8_t)(i * 37);
    }
    for (size_t i = 0; i < sizeof(flat); i += 3) { flat[i] = 17; flat[i + 1] = 93; flat[i + 2] = 241; }
    assert(histogram(gradient, sizeof(gradient), bins) == 0);
    emit("GRADIENT_RGB", gradient, sizeof(gradient)); emit("GRADIENT_BINS", bins, sizeof(bins));
    assert(histogram(flat, sizeof(flat), bins) == 0);
    emit("FLAT_RGB", flat, sizeof(flat)); emit("FLAT_BINS", bins, sizeof(bins));
    memset(bins, 0xa5, sizeof(bins));
    assert(histogram(NULL, 3, bins) == -EINVAL && histogram(flat, 0, bins) == -EINVAL &&
           histogram(flat, 2, bins) == -EINVAL && histogram(flat, FRAME_CAPACITY + 3u, bins) == -EINVAL);
    for (size_t i = 0; i < sizeof(bins); ++i) assert(bins[i] == 0xa5);
}
int main(int argc, char **argv)
{
    av_log_set_level(AV_LOG_ERROR);
    if (argc == 2 && !strcmp(argv[1], "mixed")) { mixed(); known_histograms(); }
    else if (argc == 2 && !strcmp(argv[1], "validation")) { validation(); pending(); }
    else if (argc == 2 && !strcmp(argv[1], "faults")) failures();
    else assert(0);
    return 0;
}
