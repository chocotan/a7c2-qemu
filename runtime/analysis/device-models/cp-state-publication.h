/* SPDX-License-Identifier: MIT */
#ifndef NATIVE_CP_STATE_PUBLICATION_H
#define NATIVE_CP_STATE_PUBLICATION_H
#include "imaging-device.h"
#include "cp-start-state-data.h"
#include "cp-full-state-snapshot.h"

#define NATIVE_CP_STATE_PUBLICATION_SID 0x90030001u
#define NATIVE_CP_STATE_PUBLICATION_AP 0x80020002u
#define CP_STATE_PUBLICATION_BLOCKED (-ENODATA)
#define CP_STATE_PUBLICATION_LEASES 5u

/* Called with the parent's existing resource reservation, outside this owner's
 * mutex. Providers copy their actual coherent owner state; they may not turn
 * an unsupported input/default/test fixture into source-ready data. Parent
 * predecessor_ready proves the native same-process control/connection cohort.
 * No callback here grants native CP history, mode application, EE or capture.
 */
struct native_cp_state_publication_providers {
    void *context;
    int (*start)(void *, struct cp_start_state_data *, struct cp_start_state_guard *);
    int (*full)(void *, struct cp_state_snapshot *);
};
struct native_cp_state_publication_guard {
    int (*reserve)(void);
    void (*release)(void);
    int (*predecessor_ready)(void);
};
struct native_cp_state_publication_lease {
    unsigned int role, bytes, destination, source, queued, freed;
    unsigned int received, consumed, faults, releasing, send_inflight;
    int allocate_rc, send_rc, free_rc;
    long sender_tid, receiver_tid, free_tid;
    void *pointer;
    uint64_t wire_fnv1a64;
};
struct native_cp_state_publication_snapshot {
    int owner_pid;
    unsigned int initialized, busy, guard_held, faults;
    unsigned int start_requests, start_complete, mode1_requests, mode1_complete;
    unsigned int start_data_known_mask, full_layout_copied, full_source_copied;
    unsigned int notification_mode, shadow_generation, published_generation;
    unsigned int publication_copied, notification_queued, notification_ap_consumed;
    unsigned int business_applied, original_cp, ee, frame, capture;
    unsigned int provider_refusals;
    int provider_rc;
    struct native_cp_state_publication_lease leases[CP_STATE_PUBLICATION_LEASES];
};
/* One process-local constructor before any inputs. Shadow=0 is this virtual
 * owner's explicit initial policy, not an original RAM claim. No reset/import.
 * Supports one type0/3003 OR3000/24B (zero tail), then one type5/4073/12B/mode1.
 * 3003/3000 reply is 16B with four real owner-derived data bytes. Mode1 validates
 * a complete same-generation 76-block snapshot BEFORE taking ownership or ACK;
 * then queues the independent 12B ACK before the independent 6d4B notification.
 * Missing data delegates no success: returns handled=1/result<0, caller-owned.
 * Mode0/2 and unrelated commands return0 for their existing separate owners.
 * After taking ownership returns handled=1/result0 even on transport failure;
 * sticky faults and retained original/cleanup pointers remain visible.
 */
int native_cp_state_publication_owner_init(void);
int native_cp_state_publication_dispatch(unsigned int, void *,
    const struct full_imaging_io *, const struct native_cp_state_publication_guard *,
    const struct native_cp_state_publication_providers *, int enabled, int *result);
/* Parent calls ONLY after an actual successful original receive. The exact
 * 2040 pointer/source/length/bytes identify its receiver. Original notification
 * free must occur on that receiver; it need not be the mode1 sender. ACK free
 * must occur on that ACK's own original sender. Shadow advances ONLY after the
 * queued full notification's observed original receive and real free rc0.
 */
int native_cp_state_publication_observe_receive(unsigned int, void *, unsigned int, unsigned int);
int native_cp_state_publication_release(unsigned int, void *, int (*)(unsigned int, void *),
                                        void (*)(const char *, const char *), int *result);
void native_cp_state_publication_snapshot(struct native_cp_state_publication_snapshot *);
#endif
