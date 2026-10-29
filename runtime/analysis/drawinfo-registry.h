/* SPDX-License-Identifier: MIT */
#ifndef NATIVE_DRAWINFO_REGISTRY_H
#define NATIVE_DRAWINFO_REGISTRY_H
#include "device-models/vef-device.h"
#define NATIVE_DRAWINFO_CP 0x928d0783u
int native_drawinfo_dispatch(unsigned int, void *, const struct full_imaging_io *, int, int *);
int native_drawinfo_release_reply(unsigned int, void *, int (*)(unsigned int, void *),
                                 void (*)(const char *, const char *), int *);
void native_drawinfo_snapshot(struct full_vef_snapshot *);
struct pin_registry_owner *native_drawinfo_registry(void);
#endif
