/* SPDX-License-Identifier: MIT */
#ifndef FULL_DMM_DEVICE_H
#define FULL_DMM_DEVICE_H
#include "imaging-device.h"
/* Original appFw 0x3552d80 = dmm_get_unit_size wrapper:
 *   dest = (in[1]==1) ? 0x9061003c : 0x61003c
 *   request 40 B: +0 u16 = 0x0018, +4 u32 = input field, +20 u16 = 0
 *   then osal_rcv_msg_tmo(source, out, -1)  -> unbounded wait
 *   reply: +2 i16 ret_code (<=0 means OK), +0x10 u32 unit size
 * This owner exposes a declared page policy for captured parameter 0x50b58
 * and a default query 0; other parameters are refused. It does not claim the
 * original pool geometry, actual allocation or any DMA transfer. */
#define FULL_DMM_CP 0x9061003cu
#define FULL_DMM_LOCAL 0x0061003cu
#define FULL_DMM_REQUEST_BYTES 40u
#define FULL_DMM_REPLY_BYTES 40u
struct full_dmm_snapshot {
    unsigned int queries, faults, live_replies, unit_size;
    /* One in-flight request at a time, like every other owner. */
    unsigned int pending, pending_destination;
    unsigned long long answered, request_freed, native_freed, waiter_freed, next_lease;
    unsigned int last_input,last_reported_size;
    void *retained_request, *retained_reply;
};
int full_dmm_dispatch(unsigned int,void *,const struct full_imaging_io *,int,int *);
int full_dmm_release_reply(unsigned int,void *,int (*)(unsigned int,void *),
                           void (*)(const char *,const char *),int *);
void full_dmm_snapshot(struct full_dmm_snapshot *);
#ifdef FULL_DMM_TEST
void full_dmm_test_reset(void);
void full_dmm_test_set_unit_size(unsigned int);
#endif
#endif
