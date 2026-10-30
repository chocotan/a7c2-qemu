/* SPDX-License-Identifier: MIT */
#ifndef FUNCTIONAL_FACE_RUNTIME_H
#define FUNCTIONAL_FACE_RUNTIME_H
#include "functional-face-registry.h"

#define FUNCTIONAL_FACE_RUNTIME_TRANSACTIONS 16u
#define FUNCTIONAL_FACE_RUNTIME_REFERENCES 32u

/* The parent proves the original caller identity. This is a process-local
 * software producer tag, NOT an original CPPObject identity or CP execution. */
enum functional_face_runtime_trust {
    FUNCTIONAL_FACE_RUNTIME_UNTRUSTED = 0,
    FUNCTIONAL_FACE_RUNTIME_ACCEPTED = 1,
    FUNCTIONAL_FACE_RUNTIME_REJECTED = 2
};
enum functional_face_runtime_reference_kind {
    FUNCTIONAL_FACE_RUNTIME_UNIQUE_REFERENCE = 0,
    FUNCTIONAL_FACE_RUNTIME_SHARE = 0x21,
    FUNCTIONAL_FACE_RUNTIME_OPEN = 0x24
};
struct functional_face_runtime_caller {
    uint64_t producer_owner;
    uint32_t unit;
    enum functional_face_runtime_trust trust;
    /* For op25 only: UNIQUE requires exactly one actual sender-owned ref. */
    enum functional_face_runtime_reference_kind close_kind;
};
struct functional_face_runtime_ticket {
    uint64_t transaction, producer_owner;
    int64_t sender_tid;
    uintptr_t request;
    uint32_t op, request_source;
    struct functional_face_dmm_ticket actual;
};
struct functional_face_runtime_reference {
    uint32_t live, pending, kind;
    int64_t sender_tid;
    struct functional_face_dmm_descriptor span;
    struct functional_face_runtime_ticket receipt;
};
struct functional_face_runtime_unit {
    uint32_t live_creator, retired;
    int64_t creator_tid;
    struct functional_face_dmm_descriptor creator;
    struct functional_face_runtime_ticket receipt, retirement;
    struct functional_face_runtime_reference references[FUNCTIONAL_FACE_RUNTIME_REFERENCES];
};
struct functional_face_runtime_transaction {
    uint64_t id;
    uint32_t active, op, unit, dispatching, dispatch_returned, request_freed;
    uint32_t observed, release_attempted, reply_freed, faulted;
    int dispatch_result, request_free_result, reply_free_result;
    int64_t sender_tid;
    uintptr_t request, reply;
    uint32_t request_source;
    unsigned char request_wire[40];
    struct functional_face_dmm_descriptor binding;
    struct functional_face_runtime_ticket receipt;
};
struct functional_face_runtime_snapshot {
    uint64_t snapshot_id, producer_owner;
    int owner_pid;
    uint32_t enabled, preparing, busy, live_creators, opens, shares, tickets, retained, faults;
    uint64_t actual_receive, actual_request_free, actual_reply_free, ledger_commit, log_dropped;
    /* False throughout this host functional facade. */
    uint32_t physical_verified, original_cp_verified, native_capture_verified;
    struct full_imaging_io io_identity;
    struct functional_face_runtime_unit units[FUNCTIONAL_FACE_DMM_UNITS];
    struct functional_face_runtime_transaction transactions[FUNCTIONAL_FACE_RUNTIME_TRANSACTIONS];
    struct functional_face_runtime_transaction last_completed;
    /* Nonzero means unavailable (e.g. callback reentry -EBUSY), never success
     * with invented zero read/write counts. Only this real model owns stats. */
    int model_snapshot_result;
    struct functional_face_dmm_snapshot model;
};
typedef void (*functional_face_runtime_record)(const char *typed_prefix,
    const struct functional_face_runtime_snapshot *);

/* Explicit enable==1 only. Uses the actual three-slot registry callbacks and
 * enables face DMM once; no RPC, original AP pointer, gate or constructor write.
 * Repeated identical prepare is harmless; owner/IO/logger cannot be replaced.
 * All entry points reject an inherited PID before touching a private mutex. */
int functional_face_runtime_prepare(int explicit_enabled, uint64_t producer_owner,
    const struct full_imaging_io *, functional_face_runtime_record);
/* Disabled, untrusted and unrelated traffic returns 0 without changing result.
 * Recognized bad metadata/busy/fault returns 1 with a negative errno result.
 * Actual nonzero send rc is preserved and leaves original request ownership
 * with its caller, even after an inline receipt (the domain stays faulted).
 * A send0/request-free failure returns -EIO and retains model ownership;
 * release also blocks retries of that retained request. IO queues/size/source
 * and the original individual callback rc in snapshots are preserved.
 * Startup policy: ONE creator lifecycle per unit per process; no wire wrap. */
int functional_face_runtime_dispatch(unsigned int destination, void *request,
    const struct full_imaging_io *, int explicit_enabled,
    const struct functional_face_runtime_caller *, int *result);
/* Call only after the parent's actual original receive. Pass its actual rc;
 * rc!=0 never creates a ticket. Returns 1 claimed, 0 unrelated, negative errno.
 * The returned ticket must be saved unchanged until release; no free lookup. */
int functional_face_runtime_observe(uint64_t producer_owner, unsigned int queue,
    void *message, int original_receive_result, struct functional_face_runtime_ticket *);
/* Intercept original free before calling it. Uses the exact original release
 * function bound at prepare. A failed original free faults/retains, no retry.
 * Fresh unrelated messages at a retired pointer remain unclaimed. */
int functional_face_runtime_release(uint64_t producer_owner, unsigned int queue,
    void *message, const struct functional_face_runtime_ticket *,
    int (*original_release)(unsigned int, void *), int *result);
int functional_face_runtime_lookup_creator(uint64_t producer_owner, uint32_t unit,
    struct functional_face_dmm_descriptor *);
/* Consumer saves lookup's complete creator identity in its real context.
 * Requires that saved identity as well as raw handle; never refreshes epoch.
 * After acquisition use the real face_dmm_write/read/release_borrow APIs.
 * This API does not acknowledge the future original 48+24 transfer protocol. */
int functional_face_runtime_borrow_destination(uint64_t producer_owner, uint32_t unit,
    uint32_t raw_handle, const struct functional_face_dmm_descriptor *saved_creator,
    size_t offset, size_t bytes, unsigned int access, struct functional_face_dmm_borrow *);
/* Whole ledger/tickets copied under the facade mutex; logger runs outside it.
 * Callback snapshots remain readable even while model_snapshot_result is busy. */
int functional_face_runtime_snapshot(struct functional_face_runtime_snapshot *);
#endif
