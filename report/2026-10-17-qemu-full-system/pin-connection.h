/* SPDX-License-Identifier: MIT */
#ifndef FULL_PIN_CONNECTION_H
#define FULL_PIN_CONNECTION_H
#include "imaging-device.h"
#include "pin-format.h"
struct pin_connection_snapshot {
    unsigned int started,faults,format_pending,blocked_requests;
    unsigned long long peer_requests_consumed,peer_replies_consumed,connections;
    unsigned long long native_reply_frees,waiter_frees,header_digest;
    unsigned int buffer_handle,buffer_bytes;
    unsigned long long buffer_physical;
    unsigned int format_mode,format_consumed,buffer_released,virtual_vef_status;
    unsigned long long format_digest;
    struct pin_yc_current_info format_current;
};
/* Explicit finite virtual CP edge only. The original CP task is not running.
 * Successful control connection is followed by a real control-buffer request
 * and write. Missing format consumer keeps PinMem's subsequent queue blocked.
 * Native transport callbacks must not synchronously reenter this module. */
/* enabled=1 retains the previous missing-format boundary. enabled=2 is an
 * explicit new CPU-format owner using constructor defaults and status0; it
 * does not assert the original CP runtime status or negotiated dimensions. */
int full_pin_connection_dispatch(unsigned int,void *,const struct full_imaging_io *,int,int *);
int full_pin_connection_release(unsigned int,void *,int (*)(unsigned int,void *),void (*)(const char *,const char *),int *);
void full_pin_connection_snapshot(struct pin_connection_snapshot *);
#ifdef FULL_PIN_CONNECTION_TEST
void full_pin_connection_test_reset(void);
#endif
#endif
