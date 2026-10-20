/* SPDX-License-Identifier: MIT */
#ifndef FULL_SCALAR_CONNECTION_H
#define FULL_SCALAR_CONNECTION_H
#include "imaging-device.h"
struct scalar_connection_snapshot {
    unsigned int started,faults,pending_event6,event6_consumed,yc_callback_seen,yc_format_published;
    unsigned int source_state,peer_state;
    unsigned long long connections,native_reply_frees,waiter_frees;
};
/* Only PinMem OUT1 -> Scalar IN4. Independent virtual dispatcher, not a CP
 * task. Callbacks must not synchronously reenter while the mutex is held. */
int full_scalar_connection_dispatch(unsigned int,void *,const struct full_imaging_io *,int,int *);
int full_scalar_connection_release(unsigned int,void *,int (*)(unsigned int,void *),void (*)(const char *,const char *),int *);
void full_scalar_connection_snapshot(struct scalar_connection_snapshot *);
#ifdef FULL_PIN_CONNECTION_TEST
void full_scalar_connection_test_reset(void);
#endif
#endif
