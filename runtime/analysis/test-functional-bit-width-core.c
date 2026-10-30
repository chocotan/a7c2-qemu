/* SPDX-License-Identifier: MIT */
/* Actual Core/optics/codec contexts; fault hooks only at real resource boundaries. */
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

_Static_assert(FCAM_OP_VDF_BIT_WIDTH == 12 && FCAM_BIT_WIDTH_INPUT_BYTES == 8, "typed input");
_Static_assert(FCAM_BIT_WIDTH_CLASS == 7 && FCAM_BIT_WIDTH_RESULT_BYTES == 168 && FCAM_BIT_WIDTH_R_CONFIG == 160, "typed result");
_Static_assert(FCAM_STATE_BYTES == 128 && FCAM_VDF_RESULT_MAX_BYTES == 192, "old ABIs unchanged");
static const uint8_t route[16] = {1,5,5,0xa9,2,0,0,0,0x67};
static const uint8_t input[8] = {0};
static const uint8_t bb_inputs[5][32] = {{0x11,1,28,0,0,0,15,2}, {0x66,1,28,0,0,1},
    {0x67,1,2,0,1}, {0x5f,1,4}, {0x28,1,12,0,0,1,0,0,60}};
static const uint8_t hist_input[8] = {0x48,1,4,0,1,1};
static const uint8_t displays[3][16] = {{0x52,1,0,0,8,0,0,0,3,0,1,0,0,235,128,128},
    {0x62,1,0,0,2}, {0x41,1}};
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
        ((inject == STAGE_CHANGED && dst == subject->bit_width_staged) ||
         (inject == COMMIT_CHANGED && dst == subject->bit_width_config) ||
         (inject == READBACK_CHANGED && src == subject->bit_width_config))) {
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
static struct fcam_model *setup(void)
{
    struct fcam_model *m = fcam_model_create(77); assert(m);
    uint8_t response[FCAM_STATE_BYTES]; request(m, FCAM_OP_INIT, NULL, 0, response, sizeof response);
    assert(m->sensor_initialized && m->rendered == 1 && m->retired == 1 && !m->consumed);
    assert(m->proof.opcode == FCAM_OP_INIT && m->proof.consumer_kind == FCAM_PROOF_PROBE);
    uint8_t config[48] = {0};
    put32(config, 640); put32(config + 4, 480); put32(config + 8, 117); put32(config + 12, 13);
    put32(config + 16, 800); put32(config + 20, 640); put64(config + 24, 8642); put64(config + 32, UINT64_MAX);
    request(m, FCAM_OP_CONFIGURE, config, sizeof config, response, sizeof response);
    uint8_t receipt[160]; request(m, FCAM_OP_VDF_PATH, route, sizeof route, receipt, sizeof receipt);
    return m;
}
static void rejected(struct fcam_model *m, const uint8_t *p, size_t n, size_t cap, int error)
{
    uint8_t out[FCAM_BIT_WIDTH_RESULT_BYTES + 8], saved[sizeof out];
    memset(out, 0xa5, sizeof out); memcpy(saved, out, sizeof out);
    struct fcam_exec_result r = {19,20,21,22}, previous = r;
    struct fcam_model before = *m;
    assert(fcam_model_request(m, FCAM_OP_VDF_BIT_WIDTH, p, n, out, cap, &r) == error);
    assert(!memcmp(out, saved, sizeof out) && !memcmp(&r, &previous, sizeof r));
    assert(!memcmp(m, &before, sizeof before));
}
static void validation(void)
{
    struct fcam_model *m = setup(); uint8_t sized_input[9] = {0};
    for (size_t n = 0; n <= sizeof sized_input; ++n) if (n != 8) rejected(m, sized_input, n, 168, -EINVAL);
    for (size_t n = 0; n < 168; ++n) rejected(m, input, 8, n, -ENOSPC);
    for (size_t i = 1; i < 8; ++i) { uint8_t malformed[8] = {0}; malformed[i] = 1;
        rejected(m, malformed, 8, 168, -EINVAL); }
    for (unsigned i = 1; i <= 255; ++i) { uint8_t unsupported[8] = {0}; unsupported[0] = (uint8_t)i;
        rejected(m, unsupported, 8, 168, -ENOTSUP); }
    m->busy = 1; rejected(m, input, 8, 168, -EBUSY); m->busy = 0;
    m->vdf_busy = 1; rejected(m, input, 8, 168, -EBUSY); m->vdf_busy = 0;
    m->stream_state = 1; rejected(m, input, 8, 168, -EBUSY); m->stream_state = 0;
    m->stream_state = 3; rejected(m, input, 8, 168, -EIO); m->stream_state = 0;
    m->token = 9; rejected(m, input, 8, 168, -EBUSY); m->token = 0;
    m->sensor_initialized = 0; rejected(m, input, 8, 168, -ENODATA); m->sensor_initialized = 1;
    m->vdf_class = 0; rejected(m, input, 8, 168, -ENODATA); m->vdf_class = 1;
    m->vdf_config[1] = 1; rejected(m, input, 8, 168, -ENODATA); m->vdf_config[1] = 5;
    m->config.width = 641; rejected(m, input, 8, 168, -ENOTSUP); m->config.width = 640;
    m->config.height = 479; rejected(m, input, 8, 168, -ENOTSUP); m->config.height = 480;
    m->owner.info.state = OPTICAL_FRAME_READING; rejected(m, input, 8, 168, -EBUSY); m->owner.info.state = OPTICAL_FRAME_IDLE;
    uint64_t *counters[] = {&m->generation, &m->frame_generation, &m->rendered, &m->consumed, &m->retired,
        &m->proof.serial, &m->owner.info.generation, &m->owner.info.counts.staged,
        &m->owner.info.counts.rendered, &m->owner.info.counts.read, &m->owner.info.counts.retired};
    for (size_t i = 0; i < sizeof counters / sizeof counters[0]; ++i) {
        const uint64_t saved = *counters[i]; *counters[i] = UINT64_MAX;
        rejected(m, input, 8, 168, -EOVERFLOW); *counters[i] = saved;
    }
    uint8_t out[176] = {0}; struct fcam_exec_result result = {1,2,3,4}, prior = result;
    struct fcam_model before = *m;
    assert(fcam_model_request(m, FCAM_OP_VDF_BIT_WIDTH, out, 8, out, 168, &result) == -EINVAL);
    assert(fcam_model_request(m, FCAM_OP_VDF_BIT_WIDTH, input, 8, m->vdf_sink, 168, &result) == -EINVAL);
    assert(fcam_model_request(m, FCAM_OP_VDF_BIT_WIDTH, input, 8, out, 168, (struct fcam_exec_result *)(void *)out) == -EINVAL);
    assert(fcam_model_request(m, FCAM_OP_VDF_BIT_WIDTH, m->bit_width_config, 8, out, 168, &result) == -EINVAL);
    assert(!memcmp(&result, &prior, sizeof result) && !memcmp(m, &before, sizeof before));
    for (size_t i = 0; i < sizeof out; ++i) assert(!out[i]);
    const uint64_t pid = m->owner_pid; m->owner_pid = pid + 1;
    rejected(m, input, 8, 168, -ECHILD); m->owner_pid = pid;
    pid_t child = fork(); assert(child >= 0);
    if (!child) { rejected(m, input, 8, 168, -ECHILD); _exit(0); }
    int status; assert(waitpid(child, &status, 0) == child && WIFEXITED(status) && !WEXITSTATUS(status));
    uint8_t still[16] = {0}; put32(still, FCAM_STILL_FULL_JPEG); put32(still + 4, 128);
    put32(still + 8, 64); put32(still + 12, 90);
    assert(!fcam_model_request(m, FCAM_OP_STILL, still, sizeof still, out, 1, &result));
    assert(result.token && m->result_data); rejected(m, input, 8, 168, -EBUSY);
    uint8_t state[128]; request(m, FCAM_OP_CANCEL, NULL, 0, state, sizeof state);
    uint8_t video[48] = {0}; put32(video, 640); put32(video + 4, 480); put32(video + 8, 30);
    put32(video + 12, 90); put32(video + 16, 400); put32(video + 20, 100);
    put64(video + 24, 16667); put64(video + 32, 3000000);
    request(m, FCAM_OP_VIDEO_BEGIN, video, sizeof video, state, sizeof state);
    assert(m->stream_state == 1); rejected(m, input, 8, 168, -EBUSY);
    request(m, FCAM_OP_CANCEL, NULL, 0, state, sizeof state);
    /* No implicit INIT or route acquisition. */
    fcam_model_destroy(m); m = fcam_model_create(78); assert(m);
    rejected(m, input, 8, 168, -ENODATA); fcam_model_destroy(m);
}
static void success(void)
{
    struct fcam_model *m = setup(); uint8_t out[FCAM_HIST_RESULT_BYTES];
    for (size_t i = 0; i < 5; ++i) request(m, FCAM_OP_BB_STARTUP_CONFIG, bb_inputs[i], 32, out, 192);
    for (size_t i = 0; i < 3; ++i) request(m, FCAM_OP_VDF_DISPLAY_CONFIG, displays[i], 16, out, 176);
    const uint8_t zebra[8] = {3,0,32,75,65}; request(m, FCAM_OP_VDF_ZEBRA, zebra, 8, out, 168);
    request(m, FCAM_OP_VDF_LAYOUT, layout_case0, 32, out, 192);
    request(m, FCAM_OP_HISTOGRAM, hist_input, 8, out, FCAM_HIST_RESULT_BYTES);
    const struct fcam_model old_banks = *m;
    memset(m->bit_width_staged, 0xc7, 8); memset(m->bit_width_config, 0xd3, 8);
    uint8_t state_before[128]; request(m, FCAM_OP_STATE, NULL, 0, state_before, 128);
    blob("BEFORE", state_before, sizeof state_before); blob("INPUT", input, sizeof input);
    blob("ROUTE", route, sizeof route);
    for (unsigned i = 0; i < 2; ++i) {
        const struct fcam_model before = *m; uint8_t response[176]; memset(response, 0xa5, sizeof response);
        struct fcam_exec_result result = {0};
        assert(!fcam_model_request(m, FCAM_OP_VDF_BIT_WIDTH, input, 8, response, sizeof response, &result));
        assert(result.used == 168 && !result.token && !result.total && !result.offset);
        for (size_t j = 168; j < sizeof response; ++j) assert(response[j] == 0xa5);
        assert(m->generation == before.generation + 1 && m->frame_generation == before.frame_generation + 1);
        assert(m->rendered == before.rendered + 1 && m->consumed == before.consumed + 1 && m->retired == before.retired + 1);
        assert(!m->jpeg_encoded && !m->video_encoded && !m->result_read && !m->result_data);
        assert(m->bit_width_valid && !memcmp(m->bit_width_staged, input, 8) && !memcmp(m->bit_width_config, input, 8));
        assert(!memcmp(&m->config, &old_banks.config, sizeof m->config));
        assert(!memcmp(m->vdf_config, old_banks.vdf_config, sizeof m->vdf_config) && m->vdf_class == old_banks.vdf_class);
        assert(!memcmp(m->bb_config, old_banks.bb_config, sizeof m->bb_config) && !memcmp(m->bb_valid, old_banks.bb_valid, sizeof m->bb_valid));
        assert(!memcmp(&m->bb_applied, &old_banks.bb_applied, sizeof m->bb_applied));
        assert(!memcmp(m->display_config, old_banks.display_config, sizeof m->display_config));
        assert(!memcmp(m->zebra_config, old_banks.zebra_config, sizeof m->zebra_config));
        assert(!memcmp(m->layout_config, old_banks.layout_config, sizeof m->layout_config) && m->layout_valid == old_banks.layout_valid);
        assert(!memcmp(m->hist_config, old_banks.hist_config, sizeof m->hist_config) && m->hist_valid == old_banks.hist_valid);
        assert(!memcmp(m->hist_result, old_banks.hist_result, sizeof m->hist_result) && !memcmp(m->bb_result, old_banks.bb_result, sizeof m->bb_result));
        assert(m->vdf_sink != m->pool && m->vdf_copied == 640u * 480u * 3u && !memcmp(m->pool, m->vdf_sink, m->vdf_copied));
        const struct fcam_frame_proof proof = m->proof;
        assert(proof.opcode == FCAM_OP_VDF_BIT_WIDTH && proof.consumer_kind == FCAM_PROOF_VDF && proof.serial == before.proof.serial + 1);
        assert(proof.source_fnv1a64 == fnv(m->pool, m->vdf_copied) && proof.consumer_after_fnv1a64 == fnv(m->vdf_sink, m->vdf_copied));
        assert(proof.source_fnv1a64 == proof.consumer_before_fnv1a64 && proof.source_fnv1a64 == proof.consumer_after_fnv1a64);
        assert(proof.render_observed && proof.consumer_entered && proof.consumer_returned && proof.retired && !proof.encoder_consumed);
        assert(!proof.render_status && !proof.consumer_status && !proof.retire_status && !proof.operation_status);
        assert(proof.final_state == OPTICAL_FRAME_IDLE && proof.result_bytes == 168 && proof.result_fnv1a64 == fnv(response, 168));
        uint8_t state[128]; request(m, FCAM_OP_STATE, NULL, 0, state, 128);
        request(m, FCAM_OP_CANCEL, NULL, 0, state, 128);
        assert(!memcmp(&proof, &m->proof, sizeof proof) && m->bit_width_valid && !memcmp(m->bit_width_config, input, 8));
        blob(i ? "REPEAT" : "RECEIPT", response, 168); blob(i ? "STATE_REPEAT" : "STATE", state, sizeof state);
    }
    blob("SOURCE", m->pool, m->vdf_copied); blob("SINK", m->vdf_sink, m->vdf_copied);
    /* Saved bus participates in the consumer, including old feature ops. */
    request(m, FCAM_OP_VDF_ZEBRA, zebra, 8, out, 168);
    request(m, FCAM_OP_VDF_DISPLAY_CONFIG, displays[0], 16, out, 176);
    request(m, FCAM_OP_BB_STARTUP_CONFIG, bb_inputs[0], 32, out, 192);
    request(m, FCAM_OP_HISTOGRAM, hist_input, 8, out, FCAM_HIST_RESULT_BYTES);
    for (size_t i = 0; i < 4; ++i) {
        const uint32_t op[] = {FCAM_OP_VDF_ZEBRA, FCAM_OP_VDF_DISPLAY_CONFIG, FCAM_OP_BB_STARTUP_CONFIG, FCAM_OP_HISTOGRAM};
        const uint8_t *p[] = {zebra, displays[0], bb_inputs[0], hist_input}; const size_t n[] = {8,16,32,8}, cap[] = {168,176,192,1192};
        m->bit_width_config[0] = 1; const uint64_t generation = m->generation, frame = m->frame_generation;
        struct fcam_exec_result r = {1,2,3,4}, saved = r; memset(out, 0xa5, sizeof out);
        assert(fcam_model_request(m, op[i], p[i], n[i], out, cap[i], &r) == -EIO);
        assert(m->stream_state == 3 && m->generation == generation && !memcmp(&r, &saved, sizeof r));
        assert(m->frame_generation == frame + (op[i] == FCAM_OP_VDF_ZEBRA));
        for (size_t j = 0; j < sizeof out; ++j) assert(out[j] == 0xa5);
        m->bit_width_config[0] = 0; request(m, FCAM_OP_CANCEL, NULL, 0, out, 128);
    }
    fcam_model_destroy(m);
}
static void faults(void)
{
    for (int kind = ALLOC_FAIL; kind <= POST_RETIRE_CHANGED; ++kind) {
        struct fcam_model *m = setup(); subject = m; injected = 0;
        /* A saved prior value must survive each failed new transaction. */
        memset(m->bit_width_config, 0x79, 8); const struct fcam_model before = *m;
        if (kind == ALLOC_FAIL) { free(m->vdf_sink); m->vdf_sink = NULL; m->vdf_capacity = 0; }
        inject = (enum injection)kind;
        uint8_t output[176]; memset(output, 0xa5, sizeof output);
        struct fcam_exec_result r = {1,2,3,4}, previous = r;
        const int error = fcam_model_request(m, FCAM_OP_VDF_BIT_WIDTH, input, 8, output, sizeof output, &r);
        assert(error == (kind == ALLOC_FAIL ? -ENOMEM : -EIO));
        assert(!memcmp(&r, &previous, sizeof r) && !memcmp(m->bit_width_config, before.bit_width_config, 8) && !m->bit_width_valid);
        for (size_t i = 0; i < sizeof output; ++i) assert(output[i] == 0xa5);
        assert(m->generation == before.generation && m->frame_generation == before.frame_generation);
        if (kind != ALLOC_FAIL) assert(m->stream_state == 3 && m->proof.opcode == 12 && m->proof.operation_status == -EIO);
        else assert(!memcmp(&m->proof, &before.proof, sizeof m->proof));
        if (kind == RETIRE_FAIL) {
            assert(!m->proof.retired && m->owner.info.state != OPTICAL_FRAME_IDLE);
            /* Re-use the actual live lease to retire after preserving failure. */
            const optical_frame_lease live = {.owner = &m->owner, .generation = m->owner.info.generation,
                .buffer = m->owner.buffer, .capacity = m->owner.capacity};
            assert(optical_frame_retire(&m->owner, &live) == OPTICAL_FRAME_OK);
        }
        inject = NONE; subject = NULL; fcam_model_destroy(m);
    }
}
int main(int argc, char **argv)
{
    assert(argc == 2); av_log_set_level(AV_LOG_ERROR);
    if (!strcmp(argv[1], "success")) success();
    else if (!strcmp(argv[1], "validation")) validation();
    else { assert(!strcmp(argv[1], "faults")); faults(); }
    return 0;
}
