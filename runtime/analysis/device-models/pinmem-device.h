/* SPDX-License-Identifier: MIT */
#ifndef FULL_PINMEM_DEVICE_H
#define FULL_PINMEM_DEVICE_H
#include "vef-device.h"
#define FULL_PINMEM_CP 0x90590818u
int full_pinmem_dispatch(unsigned int,void *,const struct full_imaging_io *,int,int *);
int full_pinmem_release_reply(unsigned int,void *,int (*)(unsigned int,void *),void (*)(const char *,const char *),int *);
void full_pinmem_snapshot(struct full_vef_snapshot *);
#ifdef FULL_VEF_TEST
void full_pinmem_test_reset(void);
void full_pinmem_test_set_state(unsigned int,unsigned int);
#endif
#endif
