/* SPDX-License-Identifier: MIT */
#include "adf-hdmi-monitor.h"
#include <assert.h>
#include <limits.h>
#include <stddef.h>
#include <stdio.h>
#include <string.h>

static unsigned int cases;
static const unsigned char config[20] = {
    0, 0, 0, 0, 1, 0, 1, 1, 1, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0
};
static const unsigned char cache[16] = {[7] = 0xff};
struct command { unsigned char data[16]; unsigned int bytes; };
struct emitter_context {
    struct full_adf_hdmi_monitor *owner;
    unsigned int calls, queued, consumed, action, fail_call;
    int result;
    size_t tamper_offset;
    struct command queue[3];
    struct full_adf_hdmi_monitor observed;
};
static int emit(void *, unsigned int, unsigned int, unsigned int);
static int invoke(struct full_adf_hdmi_monitor *s, unsigned int phase,
                    unsigned long long generation, const unsigned char *data,
                    unsigned long bytes, full_adf_hdmi_monitor_emit callback,
                    struct emitter_context *ctx)
{
    if (phase == 0) return full_adf_hdmi_monitor_prepare(s, generation, callback, ctx);
    if (phase == 1) return full_adf_hdmi_monitor_commit(s, generation, callback, ctx);
    return full_adf_hdmi_monitor_configure(s, generation, data, bytes, callback, ctx);
}
static int emit(void *opaque, unsigned int mode, unsigned int enable, unsigned int channel)
{
    struct emitter_context *ctx = opaque;
    struct full_adf_hdmi_monitor *s = ctx->owner;
    unsigned int index = ctx->calls++;
    assert(index < 3 && mode == (index != 0) && !enable && !channel);
    assert(s->known == 1 && s->identity == s && !s->fault && s->busy == 1 && s->pending == 1);
    assert(s->submitted == emit && s->context == ctx && s->emit_calls == index + 1);
    assert(s->generation == (index == 2 ? 2u : 1u));
    assert(s->prepare_count == (index != 0) && s->commit_count == (index == 2));
    assert(!s->configure_count && s->emitted_af == (index != 0) && s->emitted_b0 == (index == 2));
    assert(s->flag_208 == (index == 1) && !s->flag_240 && !s->flag_241 && !s->flag_242);
    assert(s->conversions == (index ? index + 1 : 0) && s->first8_equal == s->conversions);
    assert(s->config_copies == (index == 2) && s->config_readbacks == (index == 2));
    if (index == 2) assert(!memcmp(s->config, config, sizeof config));
    assert(!memcmp(s->cache_230, cache, sizeof cache) && !memcmp(s->cache_244, cache, sizeof cache));
    if (ctx->action >= 1 && ctx->action <= 3)
        assert(invoke(s, ctx->action - 1, ctx->action == 3 ? 2 : 1, config, 20, emit, ctx) == -1021);
    if (ctx->action == 4) {
        struct full_adf_hdmi_monitor before;
        memcpy(&before, s, sizeof before);
        assert(full_adf_hdmi_monitor_init(s) == -1021 && !memcmp(&before, s, sizeof before));
    }
    if (ctx->action == 5) ((unsigned char *)s)[ctx->tamper_offset] ^= 1;
    if (ctx->action == 6) s->unknown_243 ^= 0xff;
    if (ctx->action == 7) s->submitted = 0;
    if (ctx->action == 8) s->context = 0;
    if (ctx->action == 9) s->identity = 0;
    memcpy(&ctx->observed, s, sizeof ctx->observed);
    if (ctx->fail_call == index + 1) return ctx->result;
    assert(ctx->queued < 3);
    struct command *command = &ctx->queue[ctx->queued++];
    command->bytes = mode ? 16 : 8;
    command->data[0] = mode ? 0xb0 : 0xaf;
    command->data[4] = (unsigned char)command->bytes;
    return 0;
}
static void advance(struct full_adf_hdmi_monitor *s, struct emitter_context *ctx,
                      unsigned int phase, unsigned char unknown)
{
    memset(s, 0, sizeof *s);
    s->unknown_243 = unknown;
    assert(!full_adf_hdmi_monitor_init(s) && s->unknown_243 == unknown);
    assert(s->known == 1 && s->identity == s && !s->mode && !s->path && !s->field_204 && !s->field_20c);
    assert(!s->flag_208 && !s->flag_240 && !s->flag_241 && !s->flag_242);
    assert(!memcmp(s->cache_230, cache, sizeof cache) && !memcmp(s->cache_244, cache, sizeof cache));
    memset(ctx, 0, sizeof *ctx);
    ctx->owner = s;
    for (unsigned int i = 0; i < phase; i++)
        assert(!invoke(s, i, i == 2 ? 2 : 1, config, 20, emit, ctx));
}
static void rejected(struct full_adf_hdmi_monitor *s, struct emitter_context *ctx,
                       unsigned int phase, unsigned long long generation,
                       const unsigned char *data, unsigned long bytes,
                       full_adf_hdmi_monitor_emit callback)
{
    struct full_adf_hdmi_monitor expected;
    memcpy(&expected, s, sizeof expected);
    expected.fault = 1;
    expected.pending = 1;
    unsigned int calls = ctx->calls, queued = ctx->queued;
    assert(invoke(s, phase, generation, data, bytes, callback, ctx) == -1021);
    assert(!memcmp(s, &expected, sizeof expected) && ctx->calls == calls && ctx->queued == queued);
    assert(full_adf_hdmi_monitor_init(s) == -1021 && !memcmp(s, &expected, sizeof expected));
    cases++;
}
static void consume(struct emitter_context *ctx)
{
    while (ctx->consumed < ctx->queued) {
        unsigned int index = ctx->consumed++;
        unsigned char expected[16] = {0};
        expected[0] = index ? 0xb0 : 0xaf;
        expected[4] = index ? 16 : 8;
        assert(ctx->queue[index].bytes == expected[4]);
        assert(!memcmp(ctx->queue[index].data, expected, sizeof expected));
    }
}
static void test_three_real_emissions(void)
{
    static const unsigned char opaque_values[3] = {0, 0xa5, 0xff};
    struct full_adf_hdmi_monitor s, before;
    struct emitter_context ctx;
    for (unsigned int value = 0; value < 3; value++) {
        advance(&s, &ctx, 0, opaque_values[value]);
        assert(!full_adf_hdmi_monitor_prepare(&s, 1, emit, &ctx));
        assert(s.pending == 1 && s.flag_208 == 1 && s.flag_240 == 1 && !s.flag_242);
        assert(s.prepare_count == 1 && s.first8_equal == 1 && ctx.queued == 1 && !ctx.consumed);
        consume(&ctx);
        assert(!full_adf_hdmi_monitor_commit(&s, 1, emit, &ctx));
        assert(!s.pending && !s.flag_208 && !s.flag_240 && !s.flag_242);
        assert(s.commit_count == 1 && s.first8_equal == 2 && ctx.queued == 2 && ctx.consumed == 1);
        consume(&ctx);
        unsigned char submitted[20];
        memcpy(submitted, config, sizeof submitted);
        assert(!full_adf_hdmi_monitor_configure(&s, 2, submitted, sizeof submitted, emit, &ctx));
        memset(submitted, 0xcc, sizeof submitted);
        assert(!s.fault && !s.busy && !s.pending && !s.submitted && !s.context);
        assert(s.configure_count == 1 && s.config_copies == 1 && s.config_readbacks == 1);
        assert(s.conversions == 3 && s.first8_equal == 3 && s.emit_calls == 3);
        assert(s.emitted_af == 1 && s.emitted_b0 == 2 && ctx.queued == 3 && ctx.consumed == 2);
        assert(!memcmp(s.config, config, sizeof config) && s.unknown_243 == opaque_values[value]);
        assert(!memcmp(s.cache_230, cache, sizeof cache) && !memcmp(s.cache_244, cache, sizeof cache));
        consume(&ctx);
        assert(ctx.calls == 3 && ctx.consumed == 3 && !s.mode && !s.path && !s.flag_242);
        memcpy(&before, &s, sizeof before);
        assert(full_adf_hdmi_monitor_init(&s) == -1021 && !memcmp(&before, &s, sizeof s));
        cases++;
    }
    puts("ADF_HDMI_MONITOR_REAL_AF_B0_B0_SAME_FIRST8_OPAQUE243_PASS");
}
static void test_arguments_order_and_config(void)
{
    struct full_adf_hdmi_monitor s;
    struct emitter_context ctx;
    static const unsigned long long bad_generations[3][3] = {
        {0, 2, ULLONG_MAX}, {0, 2, ULLONG_MAX}, {0, 1, ULLONG_MAX}
    };
    for (unsigned int phase = 0; phase < 3; phase++) {
        for (unsigned int n = 0; n < 3; n++) {
            advance(&s, &ctx, phase, 0xa5);
            rejected(&s, &ctx, phase, bad_generations[phase][n], config, 20, emit);
        }
        advance(&s, &ctx, phase, 0xa5);
        rejected(&s, &ctx, phase, phase == 2 ? 2 : 1, config, 20, 0);
        assert(invoke(0, phase, phase == 2 ? 2 : 1, config, 20, emit, &ctx) == -1021);
        cases++;
    }
    for (unsigned int state = 0; state <= 3; state++)
        for (unsigned int operation = 0; operation < 3; operation++) {
            if (state == operation) continue;
            advance(&s, &ctx, state, 0xff);
            rejected(&s, &ctx, operation, operation == 2 ? 2 : 1, config, 20, emit);
        }
    for (unsigned int byte = 0; byte < sizeof config; byte++)
        for (unsigned int alternative = 0; alternative < 2; alternative++) {
            unsigned char bad[20];
            memcpy(bad, config, sizeof bad);
            bad[byte] = alternative ? 0xff : (unsigned char)(bad[byte] ^ 1);
            advance(&s, &ctx, 2, 0xa5);
            rejected(&s, &ctx, 2, 2, bad, 20, emit);
        }
    const unsigned long lengths[] = {0, 1, 19, 21, ULONG_MAX};
    for (unsigned int n = 0; n < sizeof lengths / sizeof lengths[0]; n++) {
        advance(&s, &ctx, 2, 0xa5);
        rejected(&s, &ctx, 2, 2, config, lengths[n], emit);
    }
    advance(&s, &ctx, 2, 0xa5);
    rejected(&s, &ctx, 2, 2, 0, 20, emit);
    puts("ADF_HDMI_MONITOR_FULL20B_FORMAT_ORDER_GENERATIONS_REJECT_PASS");
}
#define OFFSET(field) offsetof(struct full_adf_hdmi_monitor, field)
static const size_t tamper_offsets[] = {
    OFFSET(known), OFFSET(fault), OFFSET(busy), OFFSET(pending), OFFSET(mode), OFFSET(path),
    OFFSET(field_204), OFFSET(field_20c), OFFSET(flag_208), OFFSET(flag_240), OFFSET(flag_241),
    OFFSET(flag_242), OFFSET(config), OFFSET(config) + 19, OFFSET(cache_230), OFFSET(cache_230) + 15,
    OFFSET(cache_244), OFFSET(cache_244) + 15, OFFSET(generation), OFFSET(prepare_count),
    OFFSET(commit_count), OFFSET(configure_count), OFFSET(config_copies), OFFSET(config_readbacks),
    OFFSET(conversions), OFFSET(first8_equal), OFFSET(emit_calls), OFFSET(emitted_af), OFFSET(emitted_b0),
    OFFSET(emit_result)
};
static void test_nonzero_copies_and_tamper(void)
{
    struct full_adf_hdmi_monitor s, copy;
    struct emitter_context ctx;
    assert(full_adf_hdmi_monitor_init(0) == -1021);
    for (size_t byte = 0; byte < sizeof s; byte++) {
        if (byte == OFFSET(unknown_243)) continue;
        memset(&s, 0, sizeof s);
        ((unsigned char *)&s)[byte] = 0xa5;
        memcpy(&copy, &s, sizeof copy);
        assert(full_adf_hdmi_monitor_init(&s) == -1021 && !memcmp(&copy, &s, sizeof s));
        cases++;
    }
    for (unsigned int phase = 0; phase < 3; phase++) {
        advance(&s, &ctx, phase, 0xa5);
        memcpy(&copy, &s, sizeof copy);
        rejected(&copy, &ctx, phase, phase == 2 ? 2 : 1, config, 20, emit);
        assert(!s.fault && s.identity == &s && s.unknown_243 == 0xa5);
        for (unsigned int n = 0; n < sizeof tamper_offsets / sizeof tamper_offsets[0]; n++) {
            advance(&s, &ctx, phase, 0xa5);
            ((unsigned char *)&s)[tamper_offsets[n]] ^= 1;
            rejected(&s, &ctx, phase, phase == 2 ? 2 : 1, config, 20, emit);
        }
    }
    memset(&s, 0, sizeof s);
    memset(&ctx, 0, sizeof ctx);
    ctx.owner = &s;
    rejected(&s, &ctx, 0, 1, config, 20, emit);
    puts("ADF_HDMI_MONITOR_CTOR_NO_RESET_COPIES_ALL_OWNED_TAMPER_REJECT_PASS");
}
static void test_emitter_failure_reentry_and_mutation(void)
{
    struct full_adf_hdmi_monitor s;
    struct emitter_context ctx;
    static const int failures[] = {-5, 1, -1021, 0x1004};
    for (unsigned int phase = 0; phase < 3; phase++) {
        for (unsigned int n = 0; n < sizeof failures / sizeof failures[0]; n++) {
            advance(&s, &ctx, phase, 0xa5);
            ctx.fail_call = phase + 1;
            ctx.result = failures[n];
            unsigned int af = s.emitted_af, b0 = s.emitted_b0;
            assert(invoke(&s, phase, phase == 2 ? 2 : 1, config, 20, emit, &ctx) == -1021);
            ctx.observed.fault = 1;
            ctx.observed.pending = 1;
            ctx.observed.emit_result = failures[n];
            assert(!memcmp(&s, &ctx.observed, sizeof s));
            assert(s.fault == 1 && s.busy == 1 && s.pending == 1 && s.submitted == emit && s.context == &ctx);
            assert(s.emit_calls == phase + 1 && s.emit_result == failures[n]);
            assert(s.emitted_af == af && s.emitted_b0 == b0 && ctx.queued == phase && ctx.calls == phase + 1);
            assert(!s.configure_count && s.flag_208 == (phase == 1) && !s.flag_240);
            if (phase == 2)
                assert(s.config_copies == 1 && s.config_readbacks == 1 && !memcmp(s.config, config, 20));
            rejected(&s, &ctx, phase, phase == 2 ? 2 : 1, config, 20, emit);
            cases++;
        }
        for (unsigned int action = 1; action <= 9; action++) {
            advance(&s, &ctx, phase, 0xa5);
            ctx.action = action;
            if (action == 5) continue;
            int rc = invoke(&s, phase, phase == 2 ? 2 : 1, config, 20, emit, &ctx);
            if (action == 4 || action == 6) {
                assert(!rc && !s.fault && !s.busy && s.emit_calls == phase + 1);
                assert(s.unknown_243 == (action == 6 ? 0x5a : 0xa5));
            } else {
                ctx.observed.fault = 1;
                ctx.observed.pending = 1;
                assert(!memcmp(&s, &ctx.observed, sizeof s));
                assert(rc == -1021 && s.fault == 1 && s.pending == 1 && s.busy == 1);
                assert(ctx.calls == phase + 1 && ctx.queued == phase + 1);
                assert(s.emitted_af == (phase != 0) && s.emitted_b0 == (phase == 2));
                rejected(&s, &ctx, phase, phase == 2 ? 2 : 1, config, 20, emit);
            }
            cases++;
        }
        for (unsigned int n = 0; n < sizeof tamper_offsets / sizeof tamper_offsets[0]; n++) {
            advance(&s, &ctx, phase, 0xa5);
            ctx.action = 5;
            ctx.tamper_offset = tamper_offsets[n];
            assert(invoke(&s, phase, phase == 2 ? 2 : 1, config, 20, emit, &ctx) == -1021);
            ctx.observed.fault = 1;
            ctx.observed.pending = 1;
            assert(!memcmp(&s, &ctx.observed, sizeof s));
            assert(s.fault == 1 && s.pending == 1 && ctx.calls == phase + 1 && ctx.queued == phase + 1);
            assert(!s.submitted || s.submitted == emit);
            rejected(&s, &ctx, phase, phase == 2 ? 2 : 1, config, 20, emit);
            cases++;
        }
    }
    puts("ADF_HDMI_MONITOR_EMIT_FAILURE_NO_SUBMISSION_COUNT_RETAINED_PASS");
    puts("ADF_HDMI_MONITOR_REENTRY_CALLBACK_TAMPER_RETAINED_PASS");
}
int main(void)
{
    test_three_real_emissions();
    test_arguments_order_and_config();
    test_nonzero_copies_and_tamper();
    test_emitter_failure_reentry_and_mutation();
    printf("ADF_HDMI_MONITOR_CASES=%u\n", cases);
    return 0;
}
