/* SPDX-License-Identifier: MIT */
#ifndef FULL_HDMI_PIN_DEVICE_H
#define FULL_HDMI_PIN_DEVICE_H
#include "vef-device.h"
#define FULL_HDMI_PIN_CP 0x909a015au
/* Independent metadata-only owner. Original CP logging, heap setup, resume,
 * Connect and HDMI frame processing are not executed by this owner. */
int full_hdmi_pin_dispatch(unsigned int,void *,const struct full_imaging_io *,int,int *);
int full_hdmi_pin_release_reply(unsigned int,void *,int (*)(unsigned int,void *),void (*)(const char *,const char *),int *);
void full_hdmi_pin_snapshot(struct full_vef_snapshot *);
#ifdef FULL_VEF_TEST
void full_hdmi_pin_test_reset(void);
void full_hdmi_pin_test_set_state(unsigned int,unsigned int);
#endif
#endif
