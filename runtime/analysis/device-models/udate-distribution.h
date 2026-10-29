/* SPDX-License-Identifier: MIT */
#ifndef NATIVE_UDATE_DISTRIBUTION_H
#define NATIVE_UDATE_DISTRIBUTION_H
#include <stdint.h>
#define NATIVE_UDATE_DISTRIBUTION_PROFILE_NAME "virtual-roundtrip-v1"
/* SID is the source/base pool. The original target table selects target1
 * (0x909005c5); its bits 28..30 are also required on the received type4 source
 * so the original done notifier signals target1 rather than target0. */
#define NATIVE_UDATE_DISTRIBUTION_SID 0x809005c5u
#define NATIVE_UDATE_DISTRIBUTION_TARGET1_SID 0x909005c5u
#define NATIVE_UDATE_DISTRIBUTION_MESSAGE_BYTES 44u
#define NATIVE_UDATE_DISTRIBUTION_REPLY_TIMEOUT_MS 5000L

struct native_udate_io {
    int (*allocate)(unsigned int, void **, unsigned int, unsigned int);
    int (*release)(unsigned int, void *);
    void (*set_source)(void *, unsigned int);
    int (*send)(unsigned int, void *);
    unsigned int (*size)(void *);
    unsigned int (*source)(void *);
    void (*record)(const char *, const char *);
    int (*dynamic_id)(unsigned int, unsigned int, unsigned long);
    int (*receive)(unsigned int, void **, long);
    int (*sync_direct)(unsigned int, void *);
};
struct native_udate_snapshot {
    unsigned char date[16], timezone[8];
    unsigned short reason;
    unsigned long long timer_before, timer_after, elapsed, generation;
    unsigned int valid, done_sent, faults, busy, retained;
};
/* Returns 0 for an unhandled message. Recognized requests return 1 and set
 * result. Success consumes the original type1 only after real round-trip work
 * and a successful type4 transfer. The remote clock is an explicit virtual
 * model, not execution of the original CP or a hardware/Backup ready claim. */
int native_udate_distribution_dispatch(unsigned int, void *,
    const struct native_udate_io *, int, int *);
int native_udate_distribution_release(unsigned int, void *,
    int (*)(unsigned int, void *), void (*)(const char *, const char *), int *);
#ifdef NATIVE_UDATE_DISTRIBUTION_TEST
void native_udate_test_reset(void);
void native_udate_test_snapshot(struct native_udate_snapshot *);
void native_udate_test_lock_state(void);
void native_udate_test_unlock_state(void);
#endif
#endif
