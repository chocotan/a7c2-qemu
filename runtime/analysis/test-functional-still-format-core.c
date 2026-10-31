/* SPDX-License-Identifier: MIT */
/* Actual installed Core/optics/codec contexts; hooks only at resource boundaries. */
#include "../../report/virtual-optical-frame-owner/optical-frame-owner.h"
#include <assert.h>
#include <stdlib.h>
#include <string.h>
static void *checked_malloc(size_t);
static void *checked_copy(void *, const void *, size_t);
static optical_frame_status checked_render(optical_frame_owner *, const optical_frame_lease *);
static optical_frame_status checked_read(optical_frame_owner *, const optical_frame_lease *, optical_frame_consumer, void *);
static optical_frame_status checked_retire(optical_frame_owner *, const optical_frame_lease *);
#define malloc checked_malloc
#define memcpy checked_copy
#define optical_frame_render checked_render
#define optical_frame_consumer_read checked_read
#define optical_frame_retire checked_retire
#include "../../report/functional-camera-core/functional-camera-core.c"
#undef malloc
#undef memcpy
#undef optical_frame_render
#undef optical_frame_consumer_read
#undef optical_frame_retire
#include <libavutil/log.h>
#include <sys/wait.h>

_Static_assert(FCAM_OP_STILL_FORMAT == 13 && FCAM_STILL_FORMAT_INPUT_BYTES == 16, "typed input");
_Static_assert(FCAM_STILL_FORMAT_RESULT_BYTES == 176 && FCAM_STILL_FORMAT_R_CONFIG == 160 && FCAM_STILL_FORMAT_CLASS == 8, "typed result");
_Static_assert(FCAM_OP_VDF_BIT_WIDTH == 12 && FCAM_OP_STILL == 16 && FCAM_STATE_BYTES == 128, "old ABI");
static const uint8_t route[16] = {1,5,5,0xa9,2,0,0,0,0x67};
static const uint8_t bit_width[8] = {0};
static const uint8_t input[16] = {2,0,0,1,0,1,0,0,0,1,0,1,0,0,0,0};
static const uint8_t first_m[16] = {2,0,1,1,1,1,1,0,1,1,1,1,1,0,0,0};
static const uint8_t bb_inputs[5][32] = {{0x11,1,28,0,0,0,15,2}, {0x66,1,28,0,0,1},
    {0x67,1,2,0,1}, {0x5f,1,4}, {0x28,1,12,0,0,1,0,0,60}};
static const uint8_t hist_input[8] = {0x48,1,4,0,1,1};
static const uint8_t displays[3][16] = {{0x52,1,0,0,8,0,0,0,3,0,1,0,0,235,128,128},
    {0x62,1,0,0,2}, {0x41,1}};
static const uint8_t zebra[8] = {3,0,32,75,65};
enum injection { NONE, ALLOC_FAIL, RENDER_FAIL, NO_CONSUMER, SOURCE_CHANGED, SINK_CHANGED,
    RETIRE_FAIL, STAGE_CHANGED, COMMIT_CHANGED, READBACK_CHANGED, POST_RETIRE_CHANGED };
static enum injection inject;
static struct fcam_model *subject;
static int injected;
static void *checked_malloc(size_t n) { return inject == ALLOC_FAIL ? NULL : malloc(n); }
static void *checked_copy(void *dst, const void *src, size_t n)
{
    void *result = memcpy(dst, src, n);
    if (subject && subject->vdf_busy && !injected && n &&
        ((inject == STAGE_CHANGED && dst == subject->still_format_staged) ||
         (inject == COMMIT_CHANGED && dst == subject->still_format_config) ||
         (inject == READBACK_CHANGED && src == subject->still_format_config))) {
        ((uint8_t *)dst)[n - 1] ^= 1; injected = 1;
    }
    return result;
}
static optical_frame_status checked_render(optical_frame_owner *owner, const optical_frame_lease *lease)
{
    if (inject == RENDER_FAIL) { optical_frame_lease stale = *lease; --stale.generation;
        return optical_frame_render(owner, &stale); }
    return optical_frame_render(owner, lease);
}
static optical_frame_status checked_read(optical_frame_owner *owner, const optical_frame_lease *lease,
                                         optical_frame_consumer consumer, void *context)
{
    if (inject == NO_CONSUMER) return OPTICAL_FRAME_OK;
    if (inject == SOURCE_CHANGED) subject->pool[0] ^= 1;
    const optical_frame_status result = optical_frame_consumer_read(owner, lease, consumer, context);
    if (inject == SINK_CHANGED) subject->vdf_sink[0] ^= 1;
    return result;
}
static optical_frame_status checked_retire(optical_frame_owner *owner, const optical_frame_lease *lease)
{
    if (inject == RETIRE_FAIL) { optical_frame_lease stale = *lease; --stale.generation;
        return optical_frame_retire(owner, &stale); }
    const optical_frame_status result = optical_frame_retire(owner, lease);
    if (inject == POST_RETIRE_CHANGED && result == OPTICAL_FRAME_OK) subject->vdf_sink[0] ^= 1;
    return result;
}
static void request(struct fcam_model *m, uint32_t op, const uint8_t *p, size_t n, uint8_t *out, size_t cap)
{
    struct fcam_exec_result result;
    assert(!fcam_model_request(m, op, p, n, out, cap, &result));
    assert(!result.token && !result.total && !result.offset && result.used == cap);
}
static void blob(const char *tag, const uint8_t *p, size_t n)
{
    assert(printf("BLOB %s %zu\n", tag, n) > 0);
    assert(fwrite(p, 1, n, stdout) == n);
}
static void video_config(uint8_t out[48])
{
    memset(out, 0, 48); put32(out, 128); put32(out + 4, 64); put32(out + 8, 30);
    put32(out + 12, 73); put32(out + 16, 800); put32(out + 20, 640);
    put64(out + 24, 8642); put64(out + 32, UINT64_MAX);
}
static struct fcam_model *setup(void)
{
    struct fcam_model *m = fcam_model_create(77); assert(m);
    uint8_t response[176]; request(m, FCAM_OP_INIT, NULL, 0, response, 128);
    assert(m->sensor_initialized && m->rendered == 1 && m->retired == 1 && !m->consumed);
    assert(m->proof.opcode == FCAM_OP_INIT && m->proof.consumer_kind == FCAM_PROOF_PROBE);
    uint8_t config[48]; video_config(config);
    put32(config, 640); put32(config + 4, 480); put32(config + 8, 117); put32(config + 12, 13);
    request(m, FCAM_OP_CONFIGURE, config, sizeof config, response, 128);
    request(m, FCAM_OP_VDF_PATH, route, sizeof route, response, 160);
    request(m, FCAM_OP_VDF_BIT_WIDTH, bit_width, sizeof bit_width, response, 168);
    return m;
}
static void rejected(struct fcam_model *m, const uint8_t *p, size_t n, size_t cap, int error)
{
    uint8_t out[184], saved[sizeof out]; memset(out, 0xa5, sizeof out); memcpy(saved, out, sizeof out);
    struct fcam_exec_result r = {19,20,21,22}, previous = r;
    const struct fcam_model before = *m;
    assert(fcam_model_request(m, FCAM_OP_STILL_FORMAT, p, n, out, cap, &r) == error);
    assert(!memcmp(out, saved, sizeof out) && !memcmp(&r, &previous, sizeof r));
    assert(!memcmp(m, &before, sizeof before));
}
static void validation(void)
{
    struct fcam_model *m = setup(); uint8_t sized[17] = {0}; memcpy(sized, input, sizeof input);
    assert(!memcmp(input, fcam_still_format_initial, sizeof input) && fcam_still_format_input_valid(input));
    assert(!fcam_still_format_input_valid(NULL));
    for (size_t n = 0; n <= sizeof sized; ++n) if (n != 16) rejected(m, sized, n, 176, -EINVAL);
    for (size_t cap = 0; cap < 176; ++cap) rejected(m, input, 16, cap, -ENOSPC);
    for (size_t i = 0; i < 16; ++i) for (unsigned value = 0; value < 256; ++value) {
        if (value == input[i]) continue;
        uint8_t malformed[16]; memcpy(malformed, input, 16); malformed[i] = (uint8_t)value;
        assert(!fcam_still_format_input_valid(malformed)); rejected(m, malformed, 16, 176, -ENOTSUP);
    }
    rejected(m, first_m, 16, 176, -ENOTSUP);
    m->busy = 1; rejected(m, input, 16, 176, -EBUSY); m->busy = 0;
    m->vdf_busy = 1; rejected(m, input, 16, 176, -EBUSY); m->vdf_busy = 0;
    m->stream_state = 1; rejected(m, input, 16, 176, -EBUSY); m->stream_state = 0;
    m->stream_state = 3; rejected(m, input, 16, 176, -EIO); m->stream_state = 0;
    m->token = 9; rejected(m, input, 16, 176, -EBUSY); m->token = 0;
    m->sensor_initialized = 0; rejected(m, input, 16, 176, -ENODATA); m->sensor_initialized = 1;
    m->vdf_class = 0; rejected(m, input, 16, 176, -ENODATA); m->vdf_class = 1;
    for (size_t i = 0; i < 3; ++i) { const uint8_t saved = m->vdf_config[i]; m->vdf_config[i] = 0;
        rejected(m, input, 16, 176, -ENODATA); m->vdf_config[i] = saved; }
    m->config.width = 641; rejected(m, input, 16, 176, -ENOTSUP); m->config.width = 640;
    m->config.height = 479; rejected(m, input, 16, 176, -ENOTSUP); m->config.height = 480;
    m->owner.info.state = OPTICAL_FRAME_READING; rejected(m, input, 16, 176, -EBUSY); m->owner.info.state = OPTICAL_FRAME_IDLE;
    uint64_t *counters[] = {&m->generation, &m->frame_generation, &m->rendered, &m->consumed, &m->retired,
        &m->proof.serial, &m->owner.info.generation, &m->owner.info.counts.staged,
        &m->owner.info.counts.rendered, &m->owner.info.counts.read, &m->owner.info.counts.retired};
    for (size_t i = 0; i < sizeof counters / sizeof counters[0]; ++i) {
        const uint64_t saved = *counters[i]; *counters[i] = UINT64_MAX;
        rejected(m, input, 16, 176, -EOVERFLOW); *counters[i] = saved;
    }
    uint8_t out[184] = {0}; struct fcam_exec_result r = {1,2,3,4}, prior = r;
    const struct fcam_model before = *m;
    assert(fcam_model_request(m, 13, out, 16, out, 176, &r) == -EINVAL);
    assert(fcam_model_request(m, 13, input, 16, m->vdf_sink, 176, &r) == -EINVAL);
    assert(fcam_model_request(m, 13, input, 16, out, 176, (struct fcam_exec_result *)(void *)out) == -EINVAL);
    assert(fcam_model_request(m, 13, m->still_format_config, 16, out, 176, &r) == -EINVAL);
    assert(fcam_model_request(m, 13, (const uint8_t *)(UINTPTR_MAX - 3), 16, out, 176, &r) == -EINVAL);
    assert(!memcmp(&r, &prior, sizeof r) && !memcmp(m, &before, sizeof before));
    for (size_t i = 0; i < sizeof out; ++i) assert(!out[i]);
    const uint64_t pid = m->owner_pid; m->owner_pid = pid + 1;
    rejected(m, input, 16, 176, -ECHILD); m->owner_pid = pid;
    pid_t child = fork(); assert(child >= 0);
    if (!child) { rejected(m, input, 16, 176, -ECHILD); _exit(0); }
    int status; assert(waitpid(child, &status, 0) == child && WIFEXITED(status) && !WEXITSTATUS(status));
    uint8_t still[16] = {0}; put32(still, FCAM_STILL_FULL_JPEG); put32(still + 4, 128);
    put32(still + 8, 64); put32(still + 12, 73);
    assert(!fcam_model_request(m, FCAM_OP_STILL, still, sizeof still, out, 1, &r) && r.token);
    rejected(m, input, 16, 176, -EBUSY); request(m, FCAM_OP_CANCEL, NULL, 0, out, 128);
    uint8_t video[48]; video_config(video); request(m, FCAM_OP_VIDEO_BEGIN, video, 48, out, 128);
    /* Restore software geometry so this checks recording admission first. */
    put32(video, 640); put32(video + 4, 480);
    request(m, FCAM_OP_CANCEL, NULL, 0, out, 128);
    request(m, FCAM_OP_VIDEO_BEGIN, video, 48, out, 128);
    rejected(m, input, 16, 176, -EBUSY); request(m, FCAM_OP_CANCEL, NULL, 0, out, 128);
    fcam_model_destroy(m); m = fcam_model_create(78); assert(m);
    rejected(m, input, 16, 176, -ENODATA); request(m, FCAM_OP_INIT, NULL, 0, out, 128);
    rejected(m, input, 16, 176, -ENODATA); fcam_model_destroy(m);
}
static void unchanged_banks(const struct fcam_model *m, const struct fcam_model *old)
{
    assert(!memcmp(&m->config, &old->config, sizeof m->config));
    assert(!memcmp(m->vdf_config, old->vdf_config, sizeof m->vdf_config) && m->vdf_class == old->vdf_class);
    assert(!memcmp(m->vdf_staged, old->vdf_staged, sizeof m->vdf_staged));
    assert(!memcmp(m->bb_config, old->bb_config, sizeof m->bb_config) && !memcmp(m->bb_valid, old->bb_valid, sizeof m->bb_valid));
    assert(!memcmp(m->bb_staged, old->bb_staged, sizeof m->bb_staged));
    assert(!memcmp(&m->bb_applied, &old->bb_applied, sizeof m->bb_applied));
    assert(!memcmp(&m->bb_staged_policy, &old->bb_staged_policy, sizeof m->bb_staged_policy));
    assert(!memcmp(m->display_config, old->display_config, sizeof m->display_config));
    assert(!memcmp(m->display_staged, old->display_staged, sizeof m->display_staged));
    assert(!memcmp(m->zebra_config, old->zebra_config, sizeof m->zebra_config));
    assert(!memcmp(m->zebra_staged, old->zebra_staged, sizeof m->zebra_staged));
    assert(!memcmp(m->layout_config, old->layout_config, sizeof m->layout_config) && m->layout_valid == old->layout_valid);
    assert(!memcmp(m->layout_staged, old->layout_staged, sizeof m->layout_staged));
    assert(!memcmp(m->hist_config, old->hist_config, sizeof m->hist_config) && m->hist_valid == old->hist_valid);
    assert(!memcmp(m->hist_staged, old->hist_staged, sizeof m->hist_staged));
    assert(!memcmp(m->hist_result, old->hist_result, sizeof m->hist_result) && !memcmp(m->bb_result, old->bb_result, sizeof m->bb_result));
    assert(!memcmp(m->bit_width_config, old->bit_width_config, sizeof m->bit_width_config) && m->bit_width_valid == old->bit_width_valid);
    assert(!memcmp(m->bit_width_staged, old->bit_width_staged, sizeof m->bit_width_staged));
}
static void success(void)
{
    struct fcam_model *m = setup(); uint8_t out[FCAM_HIST_RESULT_BYTES];
    for (size_t i = 0; i < 5; ++i) request(m, FCAM_OP_BB_STARTUP_CONFIG, bb_inputs[i], 32, out, 192);
    for (size_t i = 0; i < 3; ++i) request(m, FCAM_OP_VDF_DISPLAY_CONFIG, displays[i], 16, out, 176);
    request(m, FCAM_OP_VDF_ZEBRA, zebra, 8, out, 168);
    request(m, FCAM_OP_VDF_LAYOUT, layout_case0, 32, out, 192);
    request(m, FCAM_OP_HISTOGRAM, hist_input, 8, out, FCAM_HIST_RESULT_BYTES);
    const struct fcam_model old_banks = *m;
    assert(!m->still_format_valid && still_format_domain(m));
    uint8_t state_before[128]; request(m, FCAM_OP_STATE, NULL, 0, state_before, 128);
    blob("BEFORE", state_before, 128); blob("INPUT", input, sizeof input); blob("ROUTE", route, sizeof route);
    for (unsigned i = 0; i < 2; ++i) {
        const struct fcam_model before = *m; uint8_t response[184]; memset(response, 0xa5, sizeof response);
        struct fcam_exec_result result = {0};
        assert(!fcam_model_request(m, FCAM_OP_STILL_FORMAT, input, 16, response, sizeof response, &result));
        assert(result.used == 176 && !result.token && !result.total && !result.offset);
        for (size_t j = 176; j < sizeof response; ++j) assert(response[j] == 0xa5);
        assert(m->generation == before.generation + 1 && m->frame_generation == before.frame_generation + 1);
        assert(m->rendered == before.rendered + 1 && m->consumed == before.consumed + 1 && m->retired == before.retired + 1);
        assert(!m->jpeg_encoded && !m->video_encoded && !m->result_read && !m->result_data);
        assert(m->still_format_valid == 1 && still_format_domain(m));
        assert(!memcmp(m->still_format_staged, input, 16) && !memcmp(m->still_format_config, input, 16));
        unchanged_banks(m, &old_banks);
        assert(m->vdf_sink != m->pool && m->vdf_copied == 921600 && !memcmp(m->pool, m->vdf_sink, m->vdf_copied));
        struct fcam_frame_proof proof; assert(!fcam_model_proof_snapshot(m, &proof, sizeof proof));
        assert(proof.opcode == 13 && proof.consumer_kind == 4 && proof.serial == before.proof.serial + 1);
        assert(proof.model_instance == 77 && proof.model_lifetime == m->lifetime && proof.owner_pid == (uint64_t)getpid());
        assert(proof.config_generation == m->generation && proof.frame_generation == m->frame_generation);
        assert(proof.lease_generation == m->owner.info.generation && !proof.result_token);
        assert(proof.source_fnv1a64 == fnv(m->pool, m->vdf_copied) && proof.consumer_after_fnv1a64 == fnv(m->vdf_sink, m->vdf_copied));
        assert(proof.source_fnv1a64 == proof.consumer_before_fnv1a64 && proof.source_fnv1a64 == proof.consumer_after_fnv1a64);
        assert(proof.width == 640 && proof.height == 480 && proof.stride == 1920 && proof.active_bytes == 921600);
        assert(proof.render_observed && proof.consumer_entered && proof.consumer_returned && proof.retired && !proof.encoder_consumed);
        assert(!proof.render_status && !proof.consumer_status && !proof.retire_status && !proof.operation_status);
        assert(proof.final_state == OPTICAL_FRAME_IDLE && proof.result_bytes == 176 && proof.result_fnv1a64 == fnv(response, 176));
        assert(!proof.encoded_bytes && proof.encoded_fnv1a64 == FNV_OFFSET && !proof.result_token);
        assert(proof.after.rendered == proof.before.rendered + 1 && proof.after.consumed == proof.before.consumed + 1);
        assert(proof.after.retired == proof.before.retired + 1 && !proof.after.jpeg_encoded && !proof.after.video_encoded);
        uint8_t state[128]; request(m, FCAM_OP_STATE, NULL, 0, state, 128);
        request(m, FCAM_OP_CANCEL, NULL, 0, state, 128);
        assert(!memcmp(&proof, &m->proof, sizeof proof) && m->still_format_valid == 1 && !memcmp(m->still_format_config, input, 16));
        blob(i ? "REPEAT" : "RECEIPT", response, 176); blob(i ? "STATE_REPEAT" : "STATE", state, 128);
        blob(i ? "SOURCE_REPEAT" : "SOURCE", m->pool, m->vdf_copied);
        blob(i ? "SINK_REPEAT" : "SINK", m->vdf_sink, m->vdf_copied);
    }
    fcam_model_destroy(m);
}
static void faults(void)
{
    for (int kind = ALLOC_FAIL; kind <= POST_RETIRE_CHANGED; ++kind) {
        struct fcam_model *m = setup(); uint8_t prior[176]; request(m, 13, input, 16, prior, 176);
        subject = m; injected = 0; const struct fcam_model before = *m;
        if (kind == ALLOC_FAIL) { free(m->vdf_sink); m->vdf_sink = NULL; m->vdf_capacity = 0; }
        inject = (enum injection)kind;
        uint8_t output[184]; memset(output, 0xa5, sizeof output);
        struct fcam_exec_result r = {1,2,3,4}, previous = r;
        const int error = fcam_model_request(m, 13, input, 16, output, sizeof output, &r);
        assert(error == (kind == ALLOC_FAIL ? -ENOMEM : -EIO));
        assert(!memcmp(&r, &previous, sizeof r) && !memcmp(m->still_format_config, before.still_format_config, 16));
        assert(m->still_format_valid == 1 && m->generation == before.generation && m->frame_generation == before.frame_generation);
        for (size_t i = 0; i < sizeof output; ++i) assert(output[i] == 0xa5);
        unchanged_banks(m, &before);
        if (kind != ALLOC_FAIL) {
            assert(m->stream_state == 3 && m->proof.opcode == 13 && m->proof.operation_status == -EIO);
            assert(!m->proof.result_bytes && !m->proof.result_token && m->proof.result_fnv1a64 == FNV_OFFSET);
        } else assert(!memcmp(&m->proof, &before.proof, sizeof m->proof));
        if (kind == RETIRE_FAIL) {
            assert(!m->proof.retired && m->owner.info.state != OPTICAL_FRAME_IDLE);
            const optical_frame_lease live = {.owner = &m->owner, .generation = m->owner.info.generation,
                .buffer = m->owner.buffer, .capacity = m->owner.capacity};
            assert(optical_frame_retire(&m->owner, &live) == OPTICAL_FRAME_OK);
        }
        inject = NONE; subject = NULL; fcam_model_destroy(m);
    }
}
static void consumers(void)
{
    struct fcam_model *m = setup(); uint8_t out[FCAM_DATA_BYTES], config[48], still[16] = {0};
    request(m, 13, input, 16, out, 176);
    put32(still, FCAM_STILL_FULL_JPEG); put32(still + 4, 128); put32(still + 8, 64); put32(still + 12, 73);
    struct fcam_exec_result result;
    assert(!fcam_model_request(m, FCAM_OP_STILL, still, 16, out, sizeof out, &result));
    assert(result.token && result.used == result.total && result.used > 575 && out[0] == 0xff && out[1] == 0xd8);
    assert(m->proof.width == 128 && m->proof.height == 64 && m->proof.encoder_consumed == 1);
    uint8_t expected_quant[2][64]; assert(!quant_tables(&m->quant, 73, expected_quant));
    assert(out[2] == 0xff && out[3] == 0xdb && !memcmp(out + 7, expected_quant[0], 64));
    assert(!memcmp(out + 72, expected_quant[1], 64));
    assert(m->config.quality == 13 && m->config.width == 640 && m->config.height == 480);
    blob("JPEG", out, result.used);
    request(m, FCAM_OP_CANCEL, NULL, 0, out, 128);
    video_config(config); request(m, FCAM_OP_VIDEO_BEGIN, config, 48, out, 128);
    assert(!fcam_model_request(m, FCAM_OP_VIDEO_FRAME, NULL, 0, out, sizeof out, &result));
    assert(m->proof.consumer_kind == FCAM_PROOF_H264 && m->proof.encoder_consumed == 1);
    assert(m->proof.width == 128 && m->proof.height == 64 && !m->proof.operation_status);
    request(m, FCAM_OP_CANCEL, NULL, 0, out, 128);
    put32(config, 640); put32(config + 4, 480); request(m, FCAM_OP_CONFIGURE, config, 48, out, 128);
    const uint32_t ops[] = {FCAM_OP_VDF_ZEBRA, FCAM_OP_VDF_DISPLAY_CONFIG, FCAM_OP_BB_STARTUP_CONFIG,
        FCAM_OP_HISTOGRAM, FCAM_OP_VDF_BIT_WIDTH, FCAM_OP_STILL_FORMAT, FCAM_OP_STILL, FCAM_OP_VIDEO_FRAME};
    const uint8_t *p[] = {zebra, displays[0], bb_inputs[0], hist_input, bit_width, input, still, NULL};
    const size_t n[] = {8,16,32,8,8,16,16,0}, cap[] = {168,176,192,1192,168,176,FCAM_DATA_BYTES,FCAM_DATA_BYTES};
    for (size_t i = 0; i < sizeof ops / sizeof ops[0]; ++i) {
        if (ops[i] == FCAM_OP_VIDEO_FRAME) request(m, FCAM_OP_VIDEO_BEGIN, config, 48, out, 128);
        assert(!fcam_model_request(m, ops[i], p[i], n[i], out, cap[i], &result));
        assert(!m->proof.operation_status && m->still_format_valid == 1 && still_format_domain(m));
        if (ops[i] == FCAM_OP_STILL || ops[i] == FCAM_OP_VIDEO_FRAME) {
            assert(m->proof.encoder_consumed == 1);
            request(m, FCAM_OP_CANCEL, NULL, 0, out, 128);
            if (ops[i] == FCAM_OP_VIDEO_FRAME) request(m, FCAM_OP_VIDEO_BEGIN, config, 48, out, 128);
        }
        /* Every saved byte, plus corrupted/cleared valid bits, must close actual consumers. */
        for (size_t poison = 0; poison < 18; ++poison) {
            if (poison < 16) m->still_format_config[poison] ^= 1;
            else m->still_format_valid = poison == 16 ? 0 : 2;
            assert(!still_format_domain(m));
            const uint64_t generation = m->generation;
            memset(out, 0xa5, sizeof out); struct fcam_exec_result saved = {1,2,3,4}; result = saved;
            assert(fcam_model_request(m, ops[i], p[i], n[i], out, cap[i], &result) == -EIO);
            assert(m->stream_state == 3 && m->generation == generation && !memcmp(&result, &saved, sizeof result));
            assert(m->proof.operation_status == -EIO && !m->proof.encoder_consumed && !m->proof.result_bytes);
            for (size_t j = 0; j < sizeof out; ++j) assert(out[j] == 0xa5);
            if (poison < 16) m->still_format_config[poison] ^= 1; else m->still_format_valid = 1;
            request(m, FCAM_OP_CANCEL, NULL, 0, out, 128);
            if (ops[i] == FCAM_OP_VIDEO_FRAME && poison != 17)
                request(m, FCAM_OP_VIDEO_BEGIN, config, 48, out, 128);
        }
    }
    assert(still_format_domain(m) && !memcmp(m->still_format_config, input, 16));
    fcam_model_destroy(m);
}
int main(int argc, char **argv)
{
    assert(argc == 2); av_log_set_level(AV_LOG_ERROR);
    if (!strcmp(argv[1], "success")) success();
    else if (!strcmp(argv[1], "validation")) validation();
    else if (!strcmp(argv[1], "faults")) faults();
    else { assert(!strcmp(argv[1], "consumers")); consumers(); }
    return 0;
}
