/* SPDX-License-Identifier: MIT */
#ifndef FULL_ADF_AUDIO_CONNECTION_H
#define FULL_ADF_AUDIO_CONNECTION_H
#include "scalar-connection.h"
/* Fifth known edge: ADF AUDIO OUT0 {5,2,0,9058003f} -> HDMI AUDIO IN0
 * {5,1,0,909a015a}. Shares the captured four-frame engine with its own state,
 * lock and leases. Only shared byte +60h is modelled after the connect. */
int full_adf_audio_connection_dispatch(unsigned int,void *,const struct full_imaging_io *,int,int *);
int full_adf_audio_connection_release(unsigned int,void *,int (*)(unsigned int,void *),void (*)(const char *,const char *),int *);
void full_adf_audio_connection_snapshot(struct scalar_connection_snapshot *);
#ifdef FULL_PIN_CONNECTION_TEST
void full_adf_audio_connection_test_reset(void);
#endif
#endif
