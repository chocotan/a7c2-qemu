/* SPDX-License-Identifier: MIT */
#ifndef NATIVE_DMM_UNIT_CONFIG_H
#define NATIVE_DMM_UNIT_CONFIG_H
#include "device-models/imaging-device.h"
#define NATIVE_DMM_UNIT_SID 0x9061003cu
/* Read-only single-unit config lookup, no allocation or buffer-ready claim. */
int native_dmm_unit_bind(const unsigned char *,unsigned int);
int native_dmm_unit_dispatch(unsigned int,void *,const struct full_imaging_io *,int,int *);
int native_dmm_unit_release(unsigned int,void *,int (*)(unsigned int,void *),void (*)(const char *,const char *),int *);
#endif
