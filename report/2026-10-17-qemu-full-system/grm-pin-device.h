/* SPDX-License-Identifier: MIT */
#ifndef FULL_GRM_PIN_DEVICE_H
#define FULL_GRM_PIN_DEVICE_H
#include "vef-device.h"
#define FULL_GRM_PIN_CP 0x9080003bu
int full_grm_pin_dispatch(unsigned int,void *,const struct full_imaging_io *,int,int *);
int full_grm_pin_release_reply(unsigned int,void *,int (*)(unsigned int,void *),void (*)(const char *,const char *),int *);
void full_grm_pin_snapshot(struct full_vef_snapshot *);
struct pin_registry_owner;
struct pin_registry_owner *full_grm_pin_registry(void);
#ifdef FULL_VEF_TEST
void full_grm_pin_test_reset(void);
#endif
#endif
