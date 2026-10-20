/* SPDX-License-Identifier: MIT */
#ifndef FULL_VEF_DEVICE_H
#define FULL_VEF_DEVICE_H
#include "imaging-device.h"
#define FULL_VEF_CP 0x905a0048u
#define FULL_PIN_REGISTRY_CAPACITY 21
struct full_vef_pin { unsigned int self[4],peer[4],state; };
struct full_vef_snapshot {
    unsigned int initialized,faults,pending,live_replies;
    struct full_vef_pin pins[FULL_PIN_REGISTRY_CAPACITY];
    unsigned long long queries,queued,request_freed,native_freed,waiter_freed,next_lease;
    void *retained_request,*retained_reply;
    unsigned int registry_objects,owner_sid;
};
/* Original transport/logger callbacks must not synchronously reenter this
 * module while send/release/record hold its mutex; allocate runs outside it. */
int full_vef_dispatch(unsigned int,void *,const struct full_imaging_io *,int,int *);
int full_vef_release_reply(unsigned int,void *,int (*)(unsigned int,void *),
                           void (*)(const char *,const char *),int *);
void full_vef_snapshot(struct full_vef_snapshot *);
#ifdef FULL_VEF_TEST
void full_vef_test_reset(void);
void full_vef_test_set_state(unsigned int,unsigned int);
#endif
#endif
