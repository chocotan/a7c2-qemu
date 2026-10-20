/* SPDX-License-Identifier: MIT */
#ifndef NATIVE_CP_BACKGROUND_DEVICE_H
#define NATIVE_CP_BACKGROUND_DEVICE_H
#include "imaging-device.h"
#include "cp-cold-control.h"
#define NATIVE_CP_BACKGROUND_SID 0x90030001u
/* Opt-in explicit virtual-mode3/cold control endpoint. Only the observed type0
 * 24B/3007/no-arguments envelope is supported; unconsumed reserved bytes are
 * ignored as in the original receiver. A success describes the selected
 * control transition, never image/pool/AF/capture readiness. Other commands and
 * channels are unhandled, delegated to the original transport, not silently
 * acknowledged by this model. Malformed recognized requests are refused. */
int native_cp_background_dispatch(unsigned int,void *,const struct full_imaging_io *,int,int *);
int native_cp_background_release(unsigned int,void *,int (*)(unsigned int,void *),
                                 void (*)(const char *,const char *),int *);
/* Shared real backing for future finite image consumers; VM/process lifetime.
 * Never substitute an independent empty bank when a consumer has allocations. */
struct cp_sync_resources *native_cp_background_resources(void);
#endif
