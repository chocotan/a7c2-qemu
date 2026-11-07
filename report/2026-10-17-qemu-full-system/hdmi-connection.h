/* SPDX-License-Identifier: MIT */
#ifndef FULL_HDMI_CONNECTION_H
#define FULL_HDMI_CONNECTION_H
#include "scalar-connection.h"
/* Fourth known edge: PinMem HDMIVIDEO OUT0 {4,2,0} -> HDMI VIDEO IN0 {4,1,0}.
 * Independent static dispatcher state/lock/leases; only the exact captured pair
 * is claimed. No original CP task, HSM exit/enter, HPD monitoring or pixels. */
int full_hdmi_connection_dispatch(unsigned int,void *,const struct full_imaging_io *,int,int *);
int full_hdmi_connection_release(unsigned int,void *,int (*)(unsigned int,void *),void (*)(const char *,const char *),int *);
void full_hdmi_connection_snapshot(struct scalar_connection_snapshot *);
#ifdef FULL_PIN_CONNECTION_TEST
void full_hdmi_connection_test_reset(void);
#endif
#endif
