/* SPDX-License-Identifier: MIT */
#ifndef FULL_HDMI_PIN_DEVICE_H
#define FULL_HDMI_PIN_DEVICE_H
#include "vef-device.h"
#define FULL_HDMI_PIN_CP 0x909a015au
/* Independent metadata-only owner. Original CP logging, heap setup, resume,
 * Connect and HDMI frame processing are not executed by this owner. */
int full_hdmi_pin_dispatch(unsigned int,void *,const struct full_imaging_io *,int,int *);
struct pin_registry_owner *full_hdmi_pin_registry(void);
int full_hdmi_pin_release_reply(unsigned int,void *,int (*)(unsigned int,void *),void (*)(const char *,const char *),int *);
void full_hdmi_pin_snapshot(struct full_vef_snapshot *);
/* Original CP raw62276c writes HDMI shared +58h from the VIDEO object's state
 * callback and 622798 writes +60h from AUDIO. Each byte is independent; a VIDEO
 * connect must not set the AUDIO byte. Only these bytes are modelled: the real
 * HSM exit/enter, HPD monitoring and driver work are NOT executed here. */
int full_hdmi_pin_notify_connected(unsigned int);
unsigned int full_hdmi_pin_video_connected(void);
unsigned int full_hdmi_pin_audio_connected(void);
#ifdef FULL_VEF_TEST
void full_hdmi_pin_test_reset(void);
void full_hdmi_pin_test_set_state(unsigned int,unsigned int);
#endif
#endif
