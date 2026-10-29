/* SPDX-License-Identifier: MIT */
#ifndef NATIVE_CP_NOTIFICATION_CONTROL_H
#define NATIVE_CP_NOTIFICATION_CONTROL_H
#include "imaging-device.h"
#define NATIVE_CP_NOTIFICATION_SID 0x90030001u
#define FULL_CP_NOTIFICATION_MODE0_PROFILE "virtual-cp-notification-mode0-v1"

/* Parent enables ONLY the exact profile above. Under its shared reservation,
 * predecessor_ready must inspect the actual same-PID diagnostic 302c original
 * AP reply free rc0/sender identity AND the unchanged clean all13 owner, with
 * no live/retained/inflight work. No caller-provided ready flags substitute.
 * Every callback runs outside this owner's mutex, including release/logging. */
struct native_cp_notification_guard {
    int (*reserve)(void);
    void (*release)(void);
    int (*predecessor_ready)(void);
};
struct native_cp_notification_snapshot {
    unsigned int initialized, virtual_mode_policy, notification_mode;
    unsigned int native_verified, source_byte1_known, virtual_padding;
    unsigned int startup_sticky, d013_registered, d018_consumed, d018_readback;
    unsigned int d018_source, d018_destination, d018_bytes;
    unsigned int requests, busy, guard_held, faults, queued, request_freed, reply_freed;
    unsigned int clean_completion, ap_consumed, destination, cookie;
    unsigned int reply_free_destination, reply_free_source, reply_free_bytes;
    int owner_pid, allocate_rc, send_rc, request_free_rc, reply_free_rc;
    long sender_tid, waiter_tid;
    unsigned char request_wire[12], reply_wire[12], d018_wire[12], freed_reply_wire[12];
    void *retained_request, *live_reply, *retained_cleanup;
};
/* One-shot constructor BEFORE inputs: explicit VIRTUAL notification-off policy,
 * NOT proof of original CP P+20 RAM initialization, central current, or 302c
 * state. Sticky=0 and no D013 registration belong solely to this finite owner.
 * No D013 registration importer exists; it must not stand in for an external
 * imaging owner with a pending D013. No reset, mode transition or snapshot API.
 *
 * Public CP f5a477...a1428, CPVA=raw+108000, Thumb source pins:
 * 357750:ac SHA 8c0ce4610acdc4e1742fad2e66b6ffa823769461a39edb8febefd61440b6c317
 *   mode=u8+8; same-mode immediate 12B type1/4073/echo+4/f000; changes pending
 *   35448c -> 8dad54 -> 8db16a (UNIMPLEMENTED, never acknowledged here).
 * ae2b76:86 SHA f63538dd6688de20b86cd9d90846650d7fc67c4f4b8228eaa342550d83efd550
 *   12B type5/d018/+4=0, source90030001 -> 90040193; byte1/tail unassigned.
 * 4590e8:104 SHA fd72439f9171e3eb791f29070b1e1a17861819185df6d2abec2bf4f023941816
 *   d000 jump table +18 => 459370 -> 459040 on owner1a2332c.
 * 459040:90 SHA c93598c4538cd997c75456c7fd3a67bc0f36134a5306ad2c4bf0e0af789e5804
 *   sticky+2e4 (1a23610) nonzero returns; else sets1 -> 4586d0.
 * 4586d0:170 SHA ab360e7c6026bc1ffc4a772ca3b6ef24ff631238c87fb3c41e58dad868c84ea5
 *   only if D013 registered+2d8==1 calls ae427c then clears registration.
 * 458fc8 stores registration=1; this finite owner never admits that input.
 *
 * Internal D018 consumes a full virtual wire into sticky state and readback;
 * it sends no D018 ACK and claims no original OSAL delivery. Unassigned wire
 * bytes are explicit virtual zero padding. AP publication after that readback
 * is conservative VIRTUAL ordering, not the source RTOS order (reply first).
 * No generation/pending/full snapshot, CP history, native CP, EE or capture
 * completion is established. See report/lens-init-contract/README.md section2.
 */
int native_cp_notification_owner_init(void);
/* 0 delegates unrelated/default-off. Refusal returns 1, nonzero *result and
 * leaves request with caller. After admission returns 1 with *result=0 even on send
 * failure: this owner consumed/retains original and cleanup pointers. One
 * transaction per process; allocation failure without a pointer is retryable.
 * Only source80020002/type5/4073/12B/mode0 is admitted; +9..11 are opaque. */
int native_cp_notification_dispatch(unsigned int, void *, const struct full_imaging_io *,
                                    const struct native_cp_notification_guard *, int enabled, int *result);
int native_cp_notification_release_reply(unsigned int, void *, int (*)(unsigned int, void *),
                                         void (*)(const char *, const char *), int *result);
void native_cp_notification_snapshot(struct native_cp_notification_snapshot *);
#ifdef NATIVE_CP_NOTIFICATION_TEST
void native_cp_notification_test_hold_lock(void);
void native_cp_notification_test_drop_lock(void);
#endif
#endif
