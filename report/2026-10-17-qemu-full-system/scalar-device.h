/* SPDX-License-Identifier: MIT */
#ifndef FULL_SCALAR_DEVICE_H
#define FULL_SCALAR_DEVICE_H
#include "vef-device.h"
#define FULL_SCALAR_CP 0x91670464u
/* Explicit Get-only owner. Does not run the original CP Scalar task, connect
 * pins, allocate image planes or produce pixels. Same transport contract as
 * the other registries; state and message leases are independently owned. */
int full_scalar_dispatch(unsigned int,void *,const struct full_imaging_io *,int,int *);
int full_scalar_release_reply(unsigned int,void *,int (*)(unsigned int,void *),void (*)(const char *,const char *),int *);
void full_scalar_snapshot(struct full_vef_snapshot *);
#ifdef FULL_VEF_TEST
void full_scalar_test_reset(void);
void full_scalar_test_set_state(unsigned int,unsigned int);
#endif
#endif
