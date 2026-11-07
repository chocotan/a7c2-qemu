/* SPDX-License-Identifier: MIT */
#ifndef CAPTURE_DELIVERY_H
#define CAPTURE_DELIVERY_H
#include "capture-notifications.h"
#include "../../runtime/analysis/device-models/cp-state-publication.h"
struct capture_delivery;
struct capture_delivery_info {
    int owner_pid,first_error,guard_held,sending;
    unsigned queued,received,wire_consumed,retained;
    uint64_t frame_token,request_fnv1a64;
    uint32_t job_scalar;
    struct native_cp_state_publication_lease leases[3];
};
/* Explicit functional-profile caller only, after actual encoding/resources.
 * reserve/predecessor_ready must check this natural original AP job's mode,
 * callbacks, full imaging gate and live hardware state; no supplied ready flag.
 * Queues start->entry->info via the real parent IO, never direct AP callbacks.
 * No4038 request free is performed here: its producer owns that separate lease.
 * After any IO attempt out retains the delivery even on error, for diagnostics
 * and exact original receive/free retirement. Message consumption is not Fsys. */
int capture_delivery_begin(struct capture_output_memory *,const uint8_t original4038[16],
    const uint8_t job_time[12],const struct full_imaging_io *,
    const struct native_cp_state_publication_guard *,struct capture_delivery **out);
/* Only after actual successful original receive of this exact source/size/body. */
int capture_delivery_observe(struct capture_delivery *,unsigned destination,void *message);
/* Hook actual original free. Return0 delegates a foreign pointer; return1 means
 * owned and puts the real free/result in rc. Receiver must match observed TID. */
int capture_delivery_free(struct capture_delivery *,unsigned destination,void *message,int *rc);
int capture_delivery_info(struct capture_delivery *,struct capture_delivery_info *);
/* Sender-thread retry of real free for allocated but never queued/received
 * messages after failure. It cannot retire any successful/received send. */
int capture_delivery_cleanup(struct capture_delivery *);
/* Refuses every queued/unconsumed or retained message and inflight callback.
 * Drops only the notification borrow; parent keeps actual MPR/Fsys export refs.
 * Called on the begin/reservation thread, serialized against new API entries.
 * Read/preserve first_error before closing: return0 means cleanup only, never
 * job success, Fsys completion or recovery from the original transport fault. */
int capture_delivery_close(struct capture_delivery *);
#endif
