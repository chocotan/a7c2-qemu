/* SPDX-License-Identifier: MIT */
#include "adf-hdmi-monitor.h"
#include <stddef.h>
#include <string.h>

static const unsigned char canonical_cache[16] = {
    0, 0, 0, 0, 0, 0, 0, 0xff, 0, 0, 0, 0, 0, 0, 0, 0
};
static const unsigned char actual_config[20] = {
    0, 0, 0, 0, 1, 0, 1, 1, 1, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0
};
static int owned_equal(const struct full_adf_hdmi_monitor *a,
                        const struct full_adf_hdmi_monitor *b)
{
    const size_t opaque = offsetof(struct full_adf_hdmi_monitor, unknown_243);
    return !memcmp(a, b, opaque) &&
        !memcmp((const unsigned char *)a + opaque + 1,
                 (const unsigned char *)b + opaque + 1, sizeof *a - opaque - 1);
}
static int fail(struct full_adf_hdmi_monitor *s)
{
    if (s) { s->fault = 1; s->pending = 1; }
    return -1021;
}
int full_adf_hdmi_monitor_init(struct full_adf_hdmi_monitor *s)
{
    struct full_adf_hdmi_monitor zero;
    memset(&zero, 0, sizeof zero);
    if (!s || !owned_equal(s, &zero)) return -1021;
    /* M1220de8: 667c02 -> 670c46, then 6710c2 builds both 16B caches. */
    s->identity = s;
    s->known = 1;
    memcpy(s->cache_230, canonical_cache, sizeof s->cache_230);
    memcpy(s->cache_244, canonical_cache, sizeof s->cache_244);
    return 0;
}
static int phase_matches(const struct full_adf_hdmi_monitor *s, unsigned int phase)
{
    struct full_adf_hdmi_monitor expected;
    memset(&expected, 0, sizeof expected);
    expected.identity = s;
    expected.known = 1;
    memcpy(expected.cache_230, canonical_cache, sizeof expected.cache_230);
    memcpy(expected.cache_244, canonical_cache, sizeof expected.cache_244);
    if (phase) {
        expected.generation = 1;
        expected.prepare_count = 1;
        expected.emitted_af = 1;
        expected.emit_calls = phase;
        expected.conversions = phase;
        expected.first8_equal = phase;
    }
    if (phase == 1) {
        expected.pending = 1;
        expected.flag_208 = 1;
        expected.flag_240 = 1;
    }
    if (phase >= 2) {
        expected.commit_count = 1;
        expected.emitted_b0 = phase - 1;
    }
    if (phase == 3) {
        expected.generation = 2;
        expected.configure_count = 1;
        expected.config_copies = 1;
        expected.config_readbacks = 1;
        memcpy(expected.config, actual_config, sizeof expected.config);
    }
    return s && owned_equal(s, &expected);
}
static void begin(struct full_adf_hdmi_monitor *s, unsigned long long generation,
                   full_adf_hdmi_monitor_emit emit, void *context)
{
    s->busy = 1;
    s->pending = 1;
    s->generation = generation;
    s->submitted = emit;
    s->context = context;
}
static int emit_command(struct full_adf_hdmi_monitor *s, unsigned int mode)
{
    struct full_adf_hdmi_monitor expected;
    s->emit_calls++;
    memcpy(&expected, s, sizeof expected);
    int rc = s->submitted(s->context, mode, 0, 0);
    if (!owned_equal(s, &expected)) return fail(s);
    s->emit_result = rc;
    if (rc) return fail(s);
    if (mode) s->emitted_b0++;
    else s->emitted_af++;
    return 0;
}
static int convert_same(struct full_adf_hdmi_monitor *s)
{
    unsigned char converted[16] = {0};
    /* 670fb8: 08 22 / 670fc0: 44 d0 compare only eight bytes. */
    converted[7] = 0xff;
    if (memcmp(converted, s->cache_230, 8)) return fail(s);
    s->conversions++;
    s->first8_equal++;
    return 0;
}
static int finish(struct full_adf_hdmi_monitor *s, unsigned int phase)
{
    s->busy = 0;
    s->submitted = 0;
    s->context = 0;
    return phase_matches(s, phase) ? 0 : fail(s);
}
int full_adf_hdmi_monitor_prepare(struct full_adf_hdmi_monitor *s,
                                  unsigned long long generation,
                                  full_adf_hdmi_monitor_emit emit, void *context)
{
    if (generation != 1 || !emit || !phase_matches(s, 0)) return fail(s);
    begin(s, generation, emit, context);
    /* Notify1(reason1), 6691a0 -> 671278: emit13d(0,0,0) before flags. */
    if (emit_command(s, 0)) return -1021;
    s->flag_208 = 1;
    s->flag_240 = 1;
    if (convert_same(s)) return -1021;
    s->prepare_count = 1;
    return finish(s, 1);
}
int full_adf_hdmi_monitor_commit(struct full_adf_hdmi_monitor *s,
                                 unsigned long long generation,
                                 full_adf_hdmi_monitor_emit emit, void *context)
{
    if (generation != 1 || !emit || !phase_matches(s, 1)) return fail(s);
    begin(s, generation, emit, context);
    /* Notify4, 669248 -> 67128e: equal cache still calls 671062(mode1). */
    s->flag_240 = 0;
    if (convert_same(s) || emit_command(s, 1)) return -1021;
    s->flag_208 = 0;
    s->pending = 0;
    s->commit_count = 1;
    return finish(s, 2);
}
int full_adf_hdmi_monitor_configure(struct full_adf_hdmi_monitor *s,
                                    unsigned long long generation,
                                    const unsigned char *config, unsigned long bytes,
                                    full_adf_hdmi_monitor_emit emit, void *context)
{
    /* shortcut: the first captured 032d only; prove new modes/formats before reuse. */
    if (generation != 2 || !config || bytes != sizeof actual_config || !emit ||
        !phase_matches(s, 2) || memcmp(config, actual_config, sizeof actual_config)) return fail(s);
    begin(s, generation, emit, context);
    /* 670e36 copies all +210..223 before Notify2, including sixteen choices. */
    memcpy(s->config, config, sizeof s->config);
    s->config_copies = 1;
    if (memcmp(s->config, actual_config, sizeof s->config)) return fail(s);
    s->config_readbacks = 1;
    if (convert_same(s) || emit_command(s, 1)) return -1021;
    s->pending = 0;
    s->configure_count = 1;
    return finish(s, 3);
}
