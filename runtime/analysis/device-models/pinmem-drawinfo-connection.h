/* SPDX-License-Identifier: MIT */
#ifndef FULL_PINMEM_DRAWINFO_CONNECTION_H
#define FULL_PINMEM_DRAWINFO_CONNECTION_H
#include "scalar-connection.h"
#include "adf-proc-device.h"
#define FULL_PINMEM_DRAWINFO_CONNECTION_PROFILE "virtual-pinmem-drawinfo0-drawinfo-in0-v1"
/* Finite native type6 metadata connection; DrawInfoRawManager +0xc returns 0.
 * Its separate data callback is unsupported; no drawing or image readiness. */
int full_pinmem_drawinfo_connection_owner_init(void);
int full_pinmem_drawinfo_connection_native_dispatch(unsigned int,void *,const struct full_imaging_io *,const struct full_adf_proc_guard *,int,int *);
int full_pinmem_drawinfo_connection_dispatch(unsigned int,void *,const struct full_imaging_io *,int,int *);
int full_pinmem_drawinfo_connection_release(unsigned int,void *,int (*)(unsigned int,void *),void (*)(const char *,const char *),int *);
void full_pinmem_drawinfo_connection_snapshot(struct scalar_connection_snapshot *);
#if defined(FULL_PIN_CONNECTION_TEST) || defined(FULL_VEF_TEST)
void full_pinmem_drawinfo_connection_test_event_corrupt(unsigned int);
int full_pinmem_drawinfo_connection_test_event_consume(const struct full_imaging_io *);
#endif
#ifdef FULL_PIN_CONNECTION_TEST
void full_pinmem_drawinfo_connection_test_reset(void);
#endif
#endif
