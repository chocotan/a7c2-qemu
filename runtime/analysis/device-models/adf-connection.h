/* SPDX-License-Identifier: MIT */
#ifndef FULL_ADF_CONNECTION_H
#define FULL_ADF_CONNECTION_H
#include "scalar-connection.h"
/* Same snapshot layout, independent static dispatcher state/lock/leases.
 * Only the exact cold PinMem OUT2 -> ADF IN0 edge is supported. */
int full_adf_connection_dispatch(unsigned int,void *,const struct full_imaging_io *,int,int *);
int full_adf_connection_release(unsigned int,void *,int (*)(unsigned int,void *),void (*)(const char *,const char *),int *);
void full_adf_connection_snapshot(struct scalar_connection_snapshot *);
#ifdef FULL_PIN_CONNECTION_TEST
void full_adf_connection_test_reset(void);
#endif
#endif
