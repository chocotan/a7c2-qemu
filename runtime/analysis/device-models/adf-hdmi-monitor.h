/* SPDX-License-Identifier: MIT */
#ifndef FULL_ADF_HDMI_MONITOR_H
#define FULL_ADF_HDMI_MONITOR_H

#define FULL_ADF_HDMI_MONITOR_CONFIG_BYTES 20u
#define FULL_ADF_HDMI_MONITOR_CACHE_BYTES 16u

/* Return 0 only after the real queue owns a new command: mode0 -> AF/8B,
 * mode1 -> B0(0,0)/16B. This does not attest AIP execution or physical output. */
typedef int (*full_adf_hdmi_monitor_emit)(void *, unsigned int mode,
                                         unsigned int enable, unsigned int channel);
struct full_adf_hdmi_monitor {
    const struct full_adf_hdmi_monitor *identity;
    unsigned int known, fault, busy, pending;
    unsigned int mode, path, field_204, field_20c;
    unsigned int flag_208, flag_240, flag_241, flag_242;
    /* Original +243 has no proved assignment or reader. Never a predicate. */
    unsigned char unknown_243;
    unsigned char config[FULL_ADF_HDMI_MONITOR_CONFIG_BYTES];
    unsigned char cache_230[FULL_ADF_HDMI_MONITOR_CACHE_BYTES];
    unsigned char cache_244[FULL_ADF_HDMI_MONITOR_CACHE_BYTES];
    unsigned long long generation;
    unsigned int prepare_count, commit_count, configure_count;
    unsigned int config_copies, config_readbacks, conversions, first8_equal;
    unsigned int emit_calls, emitted_af, emitted_b0;
    int emit_result;
    full_adf_hdmi_monitor_emit submitted;
    void *context;
};
/* Construct once before Proc0323, on zero owned storage. unknown_243 is opaque
 * and preserved even at construction. Copies and live/failed resets reject.
 * The caller serializes this owner; emit may inspect it, never mutate/reenter.
 * Failure latches fault/pending, preserves data and never retries/reset-fails. */
int full_adf_hdmi_monitor_init(struct full_adf_hdmi_monitor *);
/* Cold Notify1 before Start registration; successful preparation keeps pending. */
int full_adf_hdmi_monitor_prepare(struct full_adf_hdmi_monitor *, unsigned long long generation,
                                  full_adf_hdmi_monitor_emit, void *);
/* Notify4 after the parent commits active path0 at notification0. */
int full_adf_hdmi_monitor_commit(struct full_adf_hdmi_monitor *, unsigned long long generation,
                                 full_adf_hdmi_monitor_emit, void *);
/* First actual 032d only: full 20B 0000000001000101010100000000000000000000.
 * No other mode/path/format, arbitrary Notify, clock, DMM, transport or PCM. */
int full_adf_hdmi_monitor_configure(struct full_adf_hdmi_monitor *, unsigned long long generation,
                                    const unsigned char *, unsigned long bytes,
                                    full_adf_hdmi_monitor_emit, void *);
#endif
