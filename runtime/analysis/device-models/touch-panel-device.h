/* SPDX-License-Identifier: MIT */
#ifndef A7C2_TOUCH_PANEL_DEVICE_H
#define A7C2_TOUCH_PANEL_DEVICE_H
#include "imaging-device.h"

#define FULL_TOUCH_PANEL_INPUT 0x92840747u
#define FULL_TOUCH_PANEL_F02F_DEST 0x90590819u
#define FULL_TOUCH_PANEL_VDF_REPLY 0x9059000eu

struct full_touch_panel_snapshot {
    unsigned int enabled, configured, faults, pending;
    /* This is a declared virtual Accessor gate, not a CP memory read. */
    unsigned int control_gate, control_result_verified, clean_completion;
    unsigned char cache, readback, f02f[12], control[8];
    unsigned int outer_status;
    unsigned long long requests, applied, queued, request_freed;
    unsigned long long waiter_freed, native_freed, next_lease, control_submissions;
    unsigned int live_replies;
    void *retained_request, *retained_reply;
    int last_request_free_rc, last_reply_free_rc;
};

/* Only the analyzed AP 200d:0146, enable 0/1 subset is handled. Other
 * destinations/commands return 0; malformed known requests fail without a
 * normal completion. No CP transport or hardware touch is implied. */
int full_touch_panel_dispatch(unsigned int, void *, const struct full_imaging_io *, int, int *);
int full_touch_panel_release_reply(unsigned int, void *, int (*)(unsigned int, void *),
                                   void (*)(const char *, const char *), int *);
void full_touch_panel_snapshot(struct full_touch_panel_snapshot *);
#ifdef FULL_TOUCH_PANEL_TEST
void full_touch_panel_test_reset(void);
#endif
#endif
