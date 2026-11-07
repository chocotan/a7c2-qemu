/* SPDX-License-Identifier: MIT */
#ifndef FULL_DRAWINFO_DEVICE_H
#define FULL_DRAWINFO_DEVICE_H
#include "vef-device.h"
#define FULL_DRAWINFO_CP 0x928d0783u
int full_drawinfo_dispatch(unsigned int,void *,const struct full_imaging_io *,int,int *);
int full_drawinfo_release_reply(unsigned int,void *,int (*)(unsigned int,void *),void (*)(const char *,const char *),int *);
void full_drawinfo_snapshot(struct full_vef_snapshot *);
struct pin_registry_owner;
struct pin_registry_owner *full_drawinfo_registry(void);
#ifdef FULL_VEF_TEST
void full_drawinfo_test_reset(void);
#endif
#endif
