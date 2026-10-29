/* SPDX-License-Identifier: MIT */
#ifndef NATIVE_INFRABB_REGISTRY_H
#define NATIVE_INFRABB_REGISTRY_H
#include "device-models/vef-device.h"
#define NATIVE_INFRABB_CP 0x9284074au
int native_infrabb_dispatch(unsigned int, void *, const struct full_imaging_io *, int, int *);
int native_infrabb_release_reply(unsigned int, void *, int (*)(unsigned int, void *),
                                void (*)(const char *, const char *), int *);
void native_infrabb_snapshot(struct full_vef_snapshot *);
#define NATIVE_INFRAIMAGING_CP 0x90050004u
int native_infraimaging_dispatch(unsigned int, void *, const struct full_imaging_io *, int, int *);
int native_infraimaging_release_reply(unsigned int, void *, int (*)(unsigned int, void *),
                                     void (*)(const char *, const char *), int *);
void native_infraimaging_snapshot(struct full_vef_snapshot *);
#endif
