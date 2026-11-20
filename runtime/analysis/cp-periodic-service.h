/* SPDX-License-Identifier: MIT */
#ifndef NATIVE_CP_PERIODIC_SERVICE_H
#define NATIVE_CP_PERIODIC_SERVICE_H
#include "device-models/imaging-device.h"
#define NATIVE_CP_PERIODIC_START 0x91170319u
#define NATIVE_CP_PERIODIC_STOP 0x9117031au
struct native_cp_periodic_state {
    unsigned int period, count, phase, requested_active;
    unsigned long long starts, stops, released;
};
/* Virtual configuration prefix only: no timer, CP callback, or samples. */
int native_cp_periodic_dispatch(unsigned int,void *,const struct full_imaging_io *,int,int *);
void native_cp_periodic_snapshot(struct native_cp_periodic_state *);
#endif
