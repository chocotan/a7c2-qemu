/* SPDX-License-Identifier: MIT */
#ifndef A7C2_TCIN_DEVICE_H
#define A7C2_TCIN_DEVICE_H
#include "imaging-device.h"
#define FULL_TCIN_INPUT 0x92840747u

struct full_tcin_snapshot {
    unsigned int configured, busy, faults, requested, applied, condition, active, connected;
    unsigned int pending_flags, clean_completion, live_replies, retained_cleanup_owner;
    unsigned long long requests, applications, queued, request_freed, reply_freed, next_lease;
    void *retained_request, *retained_reply, *retained_cleanup_reply;
    int request_free_rc, reply_free_rc, cleanup_free_rc;
};
/* Only explicit virtual inactive state + 200d:0429 disable is implemented. */
int full_tcin_dispatch(unsigned int, void *, const struct full_imaging_io *, int, int *);
int full_tcin_release_reply(unsigned int, void *, int (*)(unsigned int, void *),
                            void (*)(const char *, const char *), int *);
void full_tcin_snapshot(struct full_tcin_snapshot *);
#ifdef FULL_TCIN_TEST
void full_tcin_test_reset(void);
void full_tcin_test_state(unsigned int, unsigned int, unsigned int);
#endif
#endif
