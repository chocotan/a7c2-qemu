/* SPDX-License-Identifier: MIT */
#ifndef NATIVE_OSDPIN_REGISTRY_H
#define NATIVE_OSDPIN_REGISTRY_H
#include "device-models/vef-device.h"
#define NATIVE_OSDPIN_CP 0x9080003bu
/* Observed 130 Get subset; original ignores keys and emits a CP graphics event. */
int native_osdpin_dispatch(unsigned int,void *,const struct full_imaging_io *,int,int *);
int native_osdpin_release_reply(unsigned int,void *,int (*)(unsigned int,void *),void (*)(const char *,const char *),int *);
void native_osdpin_snapshot(struct full_vef_snapshot *);
struct pin_registry_owner *native_osdpin_registry(void);
#endif
