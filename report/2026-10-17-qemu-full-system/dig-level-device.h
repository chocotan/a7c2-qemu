/* SPDX-License-Identifier: MIT */
#ifndef FULL_DIG_LEVEL_DEVICE_H
#define FULL_DIG_LEVEL_DEVICE_H
#include "imaging-device.h"
/* Original CP registers 912f0335 (raw 486c64) as the digital level service.
 * AP sends a 24 B request of six little-endian u32 (boot passes first u32=3,
 * the "off" variant passes 4) and reads only u32[4] (+0x10) as the result.
 * AP maps CP result 0 -> model 0, 1 -> a2, 2 -> a3; anything else is a generic
 * error and a non-zero mapped value reaches the boot fatal path at row 0x7ae.
 * The original function does not wait for a first angle sample, so an owner that
 * declares the feature disabled can complete this transaction honestly. */
#define FULL_DIG_LEVEL_INPUT 0x912f0335u
int full_dig_level_dispatch(unsigned int,void *,const struct full_imaging_io *,int,int *);
int full_dig_level_release_reply(unsigned int,void *,int (*)(unsigned int,void *),
                                 void (*)(const char *,const char *),int *);
struct full_dig_level_snapshot {
    unsigned int queries, enables, disables, faults, live_replies, enabled, result;
    /* One in-flight request at a time, like every other owner; a concurrent caller
     * would otherwise interleave reply leases with the same slot bookkeeping. */
    unsigned int pending, pending_destination;
    unsigned long long queued, request_freed, native_freed, waiter_freed, next_lease;
    void *retained_request, *retained_reply;
};
void full_dig_level_snapshot(struct full_dig_level_snapshot *);
#ifdef FULL_DIG_LEVEL_TEST
void full_dig_level_test_reset(void);
void full_dig_level_test_set_pending(unsigned int pending, unsigned int destination);
#endif
#endif
