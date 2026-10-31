/* SPDX-License-Identifier: MIT */
/* Actual Core/optics/codecs, with faults only at existing resource boundaries. */
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

_Static_assert(FCAM_OP_STARTUP_CONTROL == 14u && FCAM_STARTUP_CONTROL_INPUT_BYTES == 32u, "input ABI");
_Static_assert(FCAM_STARTUP_CONTROL_RESULT_BYTES == 192u && FCAM_STARTUP_CONTROL_R_CONFIG == 160u && FCAM_STARTUP_CONTROL_CLASS == 9u, "result ABI");
_Static_assert(FCAM_ABI_VERSION == 1u && FCAM_OP_STILL_FORMAT == 13u && FCAM_STATE_BYTES == 128u, "old ABI");
static const uint8_t route[16] = {1,5,5,0xa9,2,0,0,0,0x67};
enum injection { NONE, ALLOC_FAIL, RENDER_FAIL, NO_CONSUMER, SOURCE_CHANGED, SINK_CHANGED,
    RETIRE_FAIL, STAGE_CHANGED, COMMIT_CHANGED, READBACK_CHANGED, CHECKPOINT_STAGE,
    CHECKPOINT_COMMIT, CHECKPOINT_READBACK, POST_RETIRE_CHANGED };
static enum injection inject;
static struct fcam_model *subject;
static int injected;
static void *checked_malloc(size_t n) { return inject == ALLOC_FAIL ? NULL : malloc(n); }
static void *checked_copy(void *dst, const void *src, size_t n)
{
    void *result = memcpy(dst, src, n);
    if (subject && subject->vdf_busy && !injected && n &&
        ((inject == STAGE_CHANGED && dst == subject->startup_staged[subject->startup_slot]) ||
         (inject == COMMIT_CHANGED && dst == (subject->startup_slot ? subject->setting_bank32 : subject->mode_bank32)) ||
         (inject == READBACK_CHANGED && src == (subject->startup_slot ? subject->setting_bank32 : subject->mode_bank32)) ||
         (inject == CHECKPOINT_STAGE && dst == subject->settings_staged40) ||
         (inject == CHECKPOINT_COMMIT && dst == subject->settings_snapshot40) ||
         (inject == CHECKPOINT_READBACK && src == subject->settings_snapshot40))) {
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
    assert(printf("BLOB %s %zu\n", tag, n) > 0); assert(fwrite(p, 1, n, stdout) == n);
}
static void config_input(uint8_t out[48])
{
    memset(out, 0, 48); put32(out, 640); put32(out + 4, 480); put32(out + 8, 117);
    put32(out + 12, 13); put32(out + 16, 800); put32(out + 20, 640);
    put64(out + 24, 8642); put64(out + 32, UINT64_MAX);
}
static void canonical(struct fcam_model *m, unsigned command, uint8_t out[32])
{
    uint8_t actual_state[128]; request(m, FCAM_OP_STATE, NULL, 0, actual_state, 128);
    assert(get64(actual_state + FCAM_S_INSTANCE) == m->instance);
    memset(out, 0, 32); out[0] = (uint8_t)command; out[1] = (uint8_t)(command >> 8);
    out[2] = command == 0x4014 ? 16 : 4;
    if (command == 0x4014) memcpy(out + 4, fcam_startup_control_mode_body, 16);
    put64(out + 24, fnv(actual_state + 8, 40));
}
static struct fcam_model *setup(void)
{
    struct fcam_model *m = fcam_model_create(77); assert(m);
    uint8_t response[192], config[48], width[8] = {0};
    request(m, FCAM_OP_INIT, NULL, 0, response, 128);
    assert(m->sensor_initialized && m->rendered == 1 && m->retired == 1 && !m->consumed);
    config_input(config); request(m, FCAM_OP_CONFIGURE, config, 48, response, 128);
    request(m, FCAM_OP_VDF_PATH, route, 16, response, 160);
    request(m, FCAM_OP_VDF_BIT_WIDTH, width, 8, response, 168);
    request(m, FCAM_OP_STILL_FORMAT, fcam_still_format_initial, 16, response, 176);
    assert(!m->mode_valid && !m->setting_valid && startup_domain(m));
    return m;
}
static void old_banks(const struct fcam_model *m, const struct fcam_model *old)
{
    const size_t at = offsetof(struct fcam_model, vdf_staged);
    const size_t n = offsetof(struct fcam_model, startup_staged) - at;
    assert(!memcmp((const uint8_t *)m + at, (const uint8_t *)old + at, n));
    assert(!memcmp(&m->config, &old->config, sizeof m->config) && m->vdf_class == old->vdf_class);
}
static void rejected(struct fcam_model *m, const uint8_t *p, size_t n, size_t cap, int error)
{
    uint8_t out[200], saved[200]; memset(out, 0xa5, sizeof out); memcpy(saved, out, sizeof out);
    struct fcam_exec_result r = {19,20,21,22}, previous = r; const struct fcam_model before = *m;
    assert(fcam_model_request(m, 14, p, n, out, cap, &r) == error);
    assert(!memcmp(out, saved, sizeof out) && !memcmp(&r, &previous, sizeof r) && !memcmp(m, &before, sizeof before));
}
static void validation(void)
{
    struct fcam_model *m = setup(); uint8_t in[33], out[200]; canonical(m, 0x4014, in); in[32] = 0;
    assert(fcam_startup_control_validate_basic(in) && !fcam_startup_control_validate_basic(NULL));
    for (size_t n = 0; n <= 33; ++n) if (n != 32) rejected(m, in, n, 192, -EINVAL);
    for (size_t n = 0; n < 192; ++n) rejected(m, in, 32, n, -ENOSPC);
    for (unsigned command = 0; command < 2; ++command) {
        canonical(m, command ? 0x4057 : 0x4014, in);
        for (size_t i = 0; i < 32; ++i) {
            in[i] ^= 1;
            rejected(m, in, 32, 192, i < 24 ? -ENOTSUP : -ESTALE);
            in[i] ^= 1;
        }
    }
    canonical(m, 0x4014, in); in[0] = 0xc8; rejected(m, in, 32, 192, -ENOTSUP); in[0] = 0x14;
    put64(in + 24, 0); rejected(m, in, 32, 192, -ESTALE); canonical(m, 0x4014, in);
    m->busy = 1; rejected(m, in, 32, 192, -EBUSY); m->busy = 0;
    m->vdf_busy = 1; rejected(m, in, 32, 192, -EBUSY); m->vdf_busy = 0;
    m->stream_state = 1; rejected(m, in, 32, 192, -EBUSY); m->stream_state = 0;
    m->stream_state = 3; rejected(m, in, 32, 192, -EIO); m->stream_state = 0;
    m->token = 9; rejected(m, in, 32, 192, -EBUSY); m->token = 0;
    m->sensor_initialized = 0; rejected(m, in, 32, 192, -ENODATA); m->sensor_initialized = 1;
    m->vdf_class = 0; rejected(m, in, 32, 192, -ENODATA); m->vdf_class = 1;
    for (size_t i = 0; i < 3; ++i) { uint8_t saved = m->vdf_config[i]; m->vdf_config[i] = 0;
        rejected(m, in, 32, 192, -ENODATA); m->vdf_config[i] = saved; }
    m->config.width = 641; rejected(m, in, 32, 192, -ENOTSUP); m->config.width = 640;
    m->config.height = 479; rejected(m, in, 32, 192, -ENOTSUP); m->config.height = 480;
    m->owner.info.state = OPTICAL_FRAME_READING; rejected(m, in, 32, 192, -EBUSY); m->owner.info.state = OPTICAL_FRAME_IDLE;
    uint64_t *counters[] = {&m->generation, &m->frame_generation, &m->rendered, &m->consumed, &m->retired,
        &m->proof.serial, &m->owner.info.generation, &m->owner.info.counts.staged,
        &m->owner.info.counts.rendered, &m->owner.info.counts.read, &m->owner.info.counts.retired};
    for (size_t i = 0; i < sizeof counters / sizeof counters[0]; ++i) {
        uint64_t saved = *counters[i]; *counters[i] = UINT64_MAX;
        rejected(m, in, 32, 192, -EOVERFLOW); *counters[i] = saved;
    }
    struct fcam_exec_result r = {1,2,3,4}, prior = r; const struct fcam_model before = *m;
    assert(fcam_model_request(m, 14, out, 32, out, 192, &r) == -EINVAL);
    assert(fcam_model_request(m, 14, in, 32, m->vdf_sink, 192, &r) == -EINVAL);
    assert(fcam_model_request(m, 14, m->mode_bank32, 32, out, 192, &r) == -EINVAL);
    assert(fcam_model_request(m, 14, in, 32, out, 192, (struct fcam_exec_result *)(void *)out) == -EINVAL);
    assert(fcam_model_request(m, 14, (const uint8_t *)(UINTPTR_MAX - 3), 32, out, 192, &r) == -EINVAL);
    assert(!memcmp(&r, &prior, sizeof r) && !memcmp(m, &before, sizeof before));
    pid_t child = fork(); assert(child >= 0);
    if (!child) { rejected(m, in, 32, 192, -ECHILD); _exit(0); }
    int status; assert(waitpid(child, &status, 0) == child && WIFEXITED(status) && !WEXITSTATUS(status));
    uint8_t still[16] = {0}, cfg[48]; put32(still, FCAM_STILL_FULL_JPEG);
    put32(still + 4, 128); put32(still + 8, 64); put32(still + 12, 73);
    assert(!fcam_model_request(m, FCAM_OP_STILL, still, 16, out, 1, &r) && r.token);
    rejected(m, in, 32, 192, -EBUSY); request(m, FCAM_OP_CANCEL, NULL, 0, out, 128);
    config_input(cfg); request(m, FCAM_OP_VIDEO_BEGIN, cfg, 48, out, 128);
    rejected(m, in, 32, 192, -EBUSY); request(m, FCAM_OP_CANCEL, NULL, 0, out, 128);
    fcam_model_destroy(m);
    m = fcam_model_create(78); assert(m); rejected(m, in, 32, 192, -ENODATA);
    request(m, 1, NULL, 0, out, 128); rejected(m, in, 32, 192, -ENODATA); fcam_model_destroy(m);
}
static void success(void)
{
    struct fcam_model *m = setup(); uint8_t out[1192], in[32], s[128];
    static const uint8_t bb[5][32] = {{0x11,1,28,0,0,0,15,2}, {0x66,1,28,0,0,1},
        {0x67,1,2,0,1}, {0x5f,1,4}, {0x28,1,12,0,0,1,0,0,60}};
    static const uint8_t display[3][16] = {{0x52,1,0,0,8,0,0,0,3,0,1,0,0,235,128,128}, {0x62,1,0,0,2}, {0x41,1}};
    const uint8_t zebra[8] = {3,0,32,75,65}, hist[8] = {0x48,1,4,0,1,1};
    for (size_t i = 0; i < 5; ++i) request(m, 9, bb[i], 32, out, 192);
    for (size_t i = 0; i < 3; ++i) request(m, 8, display[i], 16, out, 176);
    request(m, 6, zebra, 8, out, 168); request(m, 7, layout_case0, 32, out, 192);
    request(m, 10, hist, 8, out, 1192);
    const struct fcam_model saved = *m;
    request(m, 2, NULL, 0, s, 128); blob("BEFORE", s, 128); blob("ROUTE", route, 16);
    static const char *input_tags[] = {"MODE_INPUT", "SETTINGS_INPUT", "MODE_REPEAT_INPUT", "SETTINGS_REPEAT_INPUT"};
    static const char *result_tags[] = {"MODE", "SETTINGS", "MODE_REPEAT", "SETTINGS_REPEAT"};
    static const char *state_tags[] = {"MODE_STATE", "SETTINGS_STATE", "MODE_REPEAT_STATE", "SETTINGS_REPEAT_STATE"};
    static const char *source_tags[] = {"MODE_SOURCE", "SETTINGS_SOURCE", "MODE_REPEAT_SOURCE", "SETTINGS_REPEAT_SOURCE"};
    static const char *sink_tags[] = {"MODE_SINK", "SETTINGS_SINK", "MODE_REPEAT_SINK", "SETTINGS_REPEAT_SINK"};
    for (size_t i = 0; i < 4; ++i) {
        canonical(m, i & 1 ? 0x4057 : 0x4014, in); const struct fcam_model before = *m;
        memset(out, 0xa5, sizeof out); struct fcam_exec_result r;
        assert(!fcam_model_request(m, 14, in, 32, out, 200, &r));
        assert(r.used == 192 && !r.token && !r.total && !r.offset);
        for (size_t j = 192; j < sizeof out; ++j) assert(out[j] == 0xa5);
        assert(m->generation == before.generation + 1 && m->frame_generation == before.frame_generation + 1);
        assert(m->rendered == before.rendered + 1 && m->consumed == before.consumed + 1 && m->retired == before.retired + 1);
        assert(!m->jpeg_encoded && !m->video_encoded && !m->result_read && !m->result_data && startup_domain(m));
        old_banks(m, &saved);
        assert(!memcmp(i & 1 ? m->setting_bank32 : m->mode_bank32, in, 32));
        if (i & 1) { assert(m->setting_valid == 1 && !memcmp(m->mode_bank32, before.mode_bank32, 32));
            request(m, 2, NULL, 0, s, 128); assert(!memcmp(m->settings_snapshot40, s + 8, 40)); }
        else assert(m->mode_valid == 1 && !memcmp(m->setting_bank32, before.setting_bank32, 32));
        assert(m->pool != m->vdf_sink && m->vdf_copied == 921600 && !memcmp(m->pool, m->vdf_sink, 921600));
        struct fcam_frame_proof p; assert(!fcam_model_proof_snapshot(m, &p, sizeof p));
        assert(p.serial == before.proof.serial + 1 && p.opcode == 14 && p.consumer_kind == 4);
        assert(p.model_instance == 77 && p.model_lifetime == m->lifetime && p.owner_pid == (uint64_t)getpid());
        assert(p.config_generation == m->generation && p.frame_generation == m->frame_generation && p.lease_generation == m->owner.info.generation);
        assert(p.width == 640 && p.height == 480 && p.stride == 1920 && p.active_bytes == 921600);
        assert(p.source_fnv1a64 == fnv(m->pool, 921600) && p.consumer_after_fnv1a64 == fnv(m->vdf_sink, 921600));
        assert(p.source_fnv1a64 == p.consumer_before_fnv1a64 && p.source_fnv1a64 == p.consumer_after_fnv1a64);
        assert(p.render_observed && p.consumer_entered && p.consumer_returned && p.retired && !p.encoder_consumed);
        assert(!p.render_status && !p.consumer_status && !p.retire_status && !p.operation_status && p.final_state == OPTICAL_FRAME_IDLE);
        assert(p.result_bytes == 192 && p.result_fnv1a64 == fnv(out, 192) && !p.result_token && !p.encoded_bytes && p.encoded_fnv1a64 == FNV_OFFSET);
        assert(p.after.rendered == p.before.rendered + 1 && p.after.consumed == p.before.consumed + 1 && p.after.retired == p.before.retired + 1);
        request(m, 2, NULL, 0, s, 128); request(m, 66, NULL, 0, s, 128);
        assert(!memcmp(&p, &m->proof, sizeof p) && startup_domain(m));
        blob(input_tags[i], in, 32); blob(result_tags[i], out, 192); blob(state_tags[i], s, 128);
        blob(source_tags[i], m->pool, 921600); blob(sink_tags[i], m->vdf_sink, 921600);
    }
    blob("CHECKPOINT", m->settings_snapshot40, 40); fcam_model_destroy(m);
}
static void faults(void)
{
    for (int kind = ALLOC_FAIL; kind <= POST_RETIRE_CHANGED; ++kind) {
        struct fcam_model *m = setup(); uint8_t in[32], out[200];
        canonical(m, 0x4014, in); request(m, 14, in, 32, out, 192);
        canonical(m, 0x4057, in); request(m, 14, in, 32, out, 192);
        const struct fcam_model before = *m; subject = m; injected = 0;
        if (kind == ALLOC_FAIL) { free(m->vdf_sink); m->vdf_sink = NULL; m->vdf_capacity = 0; }
        inject = (enum injection)kind; memset(out, 0xa5, sizeof out);
        struct fcam_exec_result r = {1,2,3,4}, previous = r;
        assert(fcam_model_request(m, 14, in, 32, out, sizeof out, &r) == (kind == ALLOC_FAIL ? -ENOMEM : -EIO));
        assert(!memcmp(&r, &previous, sizeof r) && m->generation == before.generation && m->frame_generation == before.frame_generation);
        assert(!memcmp(m->mode_bank32, before.mode_bank32, 32) && !memcmp(m->setting_bank32, before.setting_bank32, 32));
        assert(m->mode_valid == 1 && m->setting_valid == 1 && !memcmp(m->startup_saved_generation, before.startup_saved_generation, sizeof m->startup_saved_generation));
        old_banks(m, &before); for (size_t i = 0; i < sizeof out; ++i) assert(out[i] == 0xa5);
        if (kind == ALLOC_FAIL) assert(!memcmp(&m->proof, &before.proof, sizeof m->proof));
        else assert(m->stream_state == 3 && m->proof.opcode == 14 && m->proof.operation_status == -EIO && !m->proof.result_bytes && !m->proof.result_token);
        if (kind == RETIRE_FAIL) {
            assert(!m->proof.retired && m->owner.info.state != OPTICAL_FRAME_IDLE);
            const optical_frame_lease live = {.owner = &m->owner, .generation = m->owner.info.generation, .buffer = m->owner.buffer, .capacity = m->owner.capacity};
            assert(optical_frame_retire(&m->owner, &live) == OPTICAL_FRAME_OK);
        }
        inject = NONE; subject = NULL; fcam_model_destroy(m);
    }
}
static void consumers(void)
{
    struct fcam_model *m = setup(); uint8_t in[32], out[FCAM_DATA_BYTES], cfg[48], still[16] = {0};
    canonical(m, 0x4014, in); request(m, 14, in, 32, out, 192);
    canonical(m, 0x4057, in); request(m, 14, in, 32, out, 192);
    put32(still, FCAM_STILL_FULL_JPEG); put32(still + 4, 128); put32(still + 8, 64); put32(still + 12, 73);
    const uint32_t ops[] = {FCAM_OP_VDF_ZEBRA, FCAM_OP_STILL, FCAM_OP_VIDEO_FRAME};
    const uint8_t zebra[8] = {3,0,32,75,65}; const uint8_t *p[] = {zebra, still, NULL};
    const size_t n[] = {8,16,0}, cap[] = {168,FCAM_DATA_BYTES,FCAM_DATA_BYTES};
    for (size_t op = 0; op < 3; ++op) {
        config_input(cfg); if (op == 2) { put32(cfg, 128); put32(cfg + 4, 64); put32(cfg + 8, 30); }
        request(m, op == 2 ? FCAM_OP_VIDEO_BEGIN : FCAM_OP_CONFIGURE, cfg, 48, out, 128);
        struct fcam_exec_result r;
        assert(!fcam_model_request(m, ops[op], p[op], n[op], out, cap[op], &r) && !m->proof.operation_status);
        if (op) assert(m->proof.encoder_consumed == 1);
        if (op == 1) { uint8_t quant[2][64]; assert(!quant_tables(&m->quant, 73, quant));
            assert(!memcmp(out + 7, quant[0], 64) && !memcmp(out + 72, quant[1], 64)); blob("JPEG", out, r.used); }
        request(m, 66, NULL, 0, out, 128);
        /* Poison each saved byte, valid bits, checkpoint and generation/instance seals. */
        for (size_t poison = 0; poison < 114; ++poison) {
            if (op == 2) request(m, 32, cfg, 48, out, 128);
            const struct fcam_model healthy = *m;
            if (poison < 32) m->mode_bank32[poison] ^= 1;
            else if (poison < 64) m->setting_bank32[poison - 32] ^= 1;
            else if (poison < 104) m->settings_snapshot40[poison - 64] ^= 1;
            else if (poison < 108) { if (poison < 106) m->mode_valid = poison == 104 ? 0 : 2;
                else m->setting_valid = poison == 106 ? 0 : 2; }
            else if (poison < 110) ++m->startup_saved_generation[poison - 108];
            else if (poison < 112) m->startup_saved_seal[poison - 110] ^= 1;
            else if (poison == 112) ++m->instance;
            else ++m->lifetime;
            assert(!startup_domain(m)); const uint64_t generation = m->generation;
            struct fcam_exec_result previous = {1,2,3,4}; r = previous; memset(out, 0xa5, sizeof out);
            assert(fcam_model_request(m, ops[op], p[op], n[op], out, cap[op], &r) == -EIO);
            assert(m->stream_state == 3 && m->generation == generation && !memcmp(&r, &previous, sizeof r));
            assert(m->proof.operation_status == -EIO && !m->proof.encoder_consumed && !m->proof.result_bytes);
            for (size_t j = 0; j < sizeof out; ++j) assert(out[j] == 0xa5);
            memcpy(m->mode_bank32, healthy.mode_bank32, 32); memcpy(m->setting_bank32, healthy.setting_bank32, 32);
            memcpy(m->settings_snapshot40, healthy.settings_snapshot40, 40);
            m->mode_valid = healthy.mode_valid; m->setting_valid = healthy.setting_valid;
            memcpy(m->startup_saved_generation, healthy.startup_saved_generation, sizeof m->startup_saved_generation);
            memcpy(m->startup_saved_seal, healthy.startup_saved_seal, sizeof m->startup_saved_seal);
            m->instance = healthy.instance; m->lifetime = healthy.lifetime;
            request(m, 66, NULL, 0, out, 128); assert(startup_domain(m));
        }
    }
    for (unsigned poison = 0; poison < 2; ++poison) {
        config_input(cfg); put32(cfg, 128); put32(cfg + 4, 64); put32(cfg + 8, 30);
        request(m, FCAM_OP_VIDEO_BEGIN, cfg, 48, out, 128);
        struct fcam_exec_result r;
        assert(!fcam_model_request(m, FCAM_OP_VIDEO_FRAME, NULL, 0, out, sizeof out, &r));
        assert(m->proof.encoder_consumed == 1);
        if (!poison && r.used) blob("H264_FRAME", out, r.used);
        if (r.token) {
            assert(r.used == r.total); uint8_t release[16]; put64(release, r.token); put64(release + 8, fnv(out, r.used));
            request(m, FCAM_OP_RELEASE_RESULT, release, 16, out, 0);
        }
        if (poison) m->settings_snapshot40[0] ^= 1;
        struct fcam_exec_result previous = {1,2,3,4}; r = previous;
        const int error = fcam_model_request(m, FCAM_OP_VIDEO_END, NULL, 0, out, sizeof out, &r);
        if (poison) {
            assert(error == -EIO && !memcmp(&r, &previous, sizeof r));
            assert(m->proof.consumer_kind == FCAM_PROOF_DRAIN && m->proof.operation_status == -EIO);
            assert(!m->proof.encoder_consumed && !m->proof.result_bytes && !m->proof.encoded_bytes);
            m->settings_snapshot40[0] ^= 1;
        } else {
            assert(!error && r.token && r.used && m->proof.consumer_kind == FCAM_PROOF_DRAIN);
            blob("H264_END", out, r.used);
        }
        request(m, FCAM_OP_CANCEL, NULL, 0, out, 128);
    }
    fcam_model_destroy(m);
}
static void reload(void)
{
    struct fcam_model *m = setup(); uint8_t in[32], old[32], out[FCAM_DATA_BYTES], cfg[48], checkpoint[40];
    canonical(m, 0x4057, old); request(m, 14, old, 32, out, 192); memcpy(checkpoint, m->settings_snapshot40, 40);
    config_input(cfg); put32(cfg + 12, 71); put32(cfg + 20, 800); put64(cfg + 24, 12345);
    request(m, 3, cfg, 48, out, 128); assert(startup_domain(m) && !memcmp(checkpoint, m->settings_snapshot40, 40));
    rejected(m, old, 32, 192, -ESTALE); canonical(m, 0x4057, in);
    assert(get64(in + 24) != get64(old + 24)); request(m, 14, in, 32, out, 192);
    assert(startup_domain(m) && memcmp(checkpoint, m->settings_snapshot40, 40));
    assert(fnv(m->settings_snapshot40, 40) == get64(in + 24)); rejected(m, old, 32, 192, -ESTALE);
    canonical(m, 0x4014, in); request(m, 14, in, 32, out, 192);
    uint8_t mode[32]; memcpy(mode, m->mode_bank32, 32);
    config_input(cfg); put32(cfg + 12, 82); request(m, 3, cfg, 48, out, 128);
    const uint8_t zebra[8] = {3,0,32,75,65}; request(m, 6, zebra, 8, out, 168);
    assert(startup_domain(m) && !memcmp(mode, m->mode_bank32, 32));
    fcam_model_destroy(m);
}
int main(int argc, char **argv)
{
    assert(argc == 2); av_log_set_level(AV_LOG_ERROR);
    if (!strcmp(argv[1], "success")) success();
    else if (!strcmp(argv[1], "validation")) validation();
    else if (!strcmp(argv[1], "faults")) faults();
    else if (!strcmp(argv[1], "consumers")) consumers();
    else { assert(!strcmp(argv[1], "reload")); reload(); }
    return 0;
}
