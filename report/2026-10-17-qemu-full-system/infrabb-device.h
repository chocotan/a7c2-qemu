/* SPDX-License-Identifier: MIT */
#ifndef FULL_INFRABB_DEVICE_H
#define FULL_INFRABB_DEVICE_H
#include "vef-device.h"
#define FULL_INFRABB_CP 0x9284074au
int full_infrabb_dispatch(unsigned int,void *,const struct full_imaging_io *,int,int *);
int full_infrabb_release_reply(unsigned int,void *,int (*)(unsigned int,void *),void (*)(const char *,const char *),int *);
void full_infrabb_snapshot(struct full_vef_snapshot *);
struct pin_registry_owner;
struct pin_registry_owner *full_infrabb_registry(void);
#ifdef FULL_VEF_TEST
void full_infrabb_test_reset(void);
#endif
#endif
