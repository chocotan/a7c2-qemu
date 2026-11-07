/* SPDX-License-Identifier: MIT */
#ifndef FULL_SYSTEM_HDMI_DEVICE_H
#define FULL_SYSTEM_HDMI_DEVICE_H
#include "imaging-device.h"
#define FULL_HDMI_CP 0x909a015au
#define FULL_HDMI_DEFINITION 1
#define FULL_HDMI_BOOT 2
struct full_hdmi_snapshot {
    unsigned int known, definition, faults, pending, live_replies;
    unsigned long long applied, queries, queued, request_freed;
    unsigned long long native_freed, waiter_freed, next_lease;
    void *retained_request, *retained_reply;
    unsigned int resolution_known;
    unsigned char resolution[6];
    unsigned long long resolution_applied, resolution_queries;
    unsigned char rates[5], last_rate_payload[4];
    unsigned int rate_known_mask;
    unsigned long long rate_requests;
};
/* Shared HDMI state configuration only. No cable, output state or frames.
 * send/release/record must not synchronously reenter this module: they run
 * under its state mutex. The observer supplies original OSAL transport and
 * a file/console logger, not model callbacks. allocate runs outside the lock. */
int full_hdmi_dispatch(unsigned int, void *, const struct full_imaging_io *, int, int *);
int full_hdmi_release_reply(unsigned int, void *, int (*)(unsigned int, void *),
                            void (*)(const char *, const char *), int *);
void full_hdmi_snapshot(struct full_hdmi_snapshot *);
#ifdef FULL_HDMI_TEST
void full_hdmi_test_reset(void);
#endif
#endif
