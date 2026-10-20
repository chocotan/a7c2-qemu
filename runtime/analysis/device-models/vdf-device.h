/* SPDX-License-Identifier: MIT */
#ifndef FULL_SYSTEM_VDF_DEVICE_H
#define FULL_SYSTEM_VDF_DEVICE_H
#include "imaging-device.h"

#define FULL_VDF_CP 0x9059000eu
#define FULL_VDF_HDMI 0x9059081bu
#define FULL_VDF_INPUT 0x92840747u

struct full_vdf_snapshot {
    unsigned int enabled, configured, faults, hdmi_cache, has_config;
    unsigned char body[20], internal_packet[28];
    unsigned long long applied, hdmi_consumed, invalid, queued, request_freed;
    unsigned long long native_freed, waiter_freed, next_lease;
    unsigned int live_replies;
    void *retained_reply, *retained_request;
    unsigned char evf_subscription[8], evf_status[4];
    unsigned int evf_valid, evf_retained;
    unsigned long long evf_subscriptions;
    unsigned char panel_shadow[64], panel_valid[2], panel_size[2];
    unsigned int panel_pending, panel_caller;
    unsigned long long panel_applied, panel_invalid;
    unsigned int reverse_properties[4], reverse_osd, reverse_control;
    unsigned char reverse_internal[20];
    unsigned long long reverse_applied, reverse_control_consumed;
};
/* Disabled dispatch preserves original transport. Enabled transport errors keep
 * the caller's request. Success consumes it once; reply ownership is separate. */
int full_vdf_dispatch(unsigned int, void *, const struct full_imaging_io *, int, int *);
/* Explicit virtual immediate-panel subset; no hardware events or flipped pixels. */
int full_vdf_reverse_dispatch(unsigned int, void *, const struct full_imaging_io *, int, int *);
/* Call independently of the current enable switch: existing leases still own
 * their reply. Matches any dynamic destination, never a fixed AP port. */
int full_vdf_release_reply(unsigned int, void *, int (*)(unsigned int, void *),
                           void (*)(const char *, const char *), int *);
void full_vdf_snapshot(struct full_vdf_snapshot *);
#ifdef FULL_VDF_TEST
void full_vdf_test_reset(void);
#endif
#endif
