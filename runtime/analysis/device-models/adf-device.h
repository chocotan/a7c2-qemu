/* SPDX-License-Identifier: MIT */
#ifndef FULL_ADF_DEVICE_H
#define FULL_ADF_DEVICE_H
#include "vef-device.h"
#define FULL_ADF_CP 0x9058003fu
/* Explicit independent Get-only owner. No original CP task or frame handling.
 * Only found keys are supported; original missing-key replies are out of scope. */
int full_adf_dispatch(unsigned int,void *,const struct full_imaging_io *,int,int *);
int full_adf_release_reply(unsigned int,void *,int (*)(unsigned int,void *),void (*)(const char *,const char *),int *);
void full_adf_snapshot(struct full_vef_snapshot *);
#ifdef FULL_VEF_TEST
void full_adf_test_reset(void);
void full_adf_test_set_state(unsigned int,unsigned int);
#endif
#endif
