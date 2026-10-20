/* SPDX-License-Identifier: MIT */
#ifndef NATIVE_DIG_LEVEL_DEVICE_H
#define NATIVE_DIG_LEVEL_DEVICE_H
#include "device-models/imaging-device.h"
#define NATIVE_DIG_LEVEL_SID 0x912f0335u
struct native_dig_level_snapshot {
    unsigned int mode,worker_started,notification_enabled,notification_countdown;
    unsigned int sample_valid,latched_error,live_replies,faults;
    unsigned long long consumed,queued,request_freed,waiter_freed,next_lease;
};
/* Explicit virtual mode2/inline worker, no accelerometer or angle events. */
int native_dig_level_dispatch(unsigned int,void *,const struct full_imaging_io *,int,int *);
int native_dig_level_release(unsigned int,void *,int (*)(unsigned int,void *),void (*)(const char *,const char *),int *);
void native_dig_level_snapshot(struct native_dig_level_snapshot *);
#endif
