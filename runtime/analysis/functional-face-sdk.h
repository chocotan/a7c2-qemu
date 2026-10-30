/* SPDX-License-Identifier: MIT */
#ifndef FUNCTIONAL_FACE_SDK_H
#define FUNCTIONAL_FACE_SDK_H
#include "functional-face-transfer.h"

struct functional_face_sdk_binding {
    struct functional_face_ap_span saved_source;
    struct functional_face_ap_provider provider;
    uint64_t producer_owner;
    int owner_pid;
    int64_t owner_tid;
    long (*read_descriptor)(void *, uintptr_t, void *, size_t);
    void *reader_context;
    /* Trusted parent validates original code/context liveness and calls the
     * original void(int32_t, void *) ABI. Return is the INVOKER's rc only. */
    int (*invoke_callback)(void *, uintptr_t callback, int32_t status, uintptr_t original_context);
    void *callback_context;
};
struct functional_face_sdk_transaction {
    unsigned char api40[40];
    uint32_t class_id, decoded, claimed, started, callback_attempted, callback_returned, callback_uncertain;
    uint32_t pending_fault, provider_may_retain, transfer_faulted, source_live, destination_live;
    int result, copy_result, callback_result;
    struct functional_face_api_request request;
    struct functional_face_ap_span saved_source;
    struct functional_face_dmm_descriptor destination;
    struct functional_face_ap_borrow source_lease;
    struct functional_face_dmm_borrow destination_lease;
    struct functional_face_transfer_receipt copy;
};
/* Zero-initialized, caller-owned, one submit per context. Keep the entire state,
 * provider context and original caller frame alive after any claimed failure.
 * last is readable at idle (also by the same-thread callback invoker). */
struct functional_face_sdk {
    _Atomic unsigned int busy;
    uint32_t initialized, submitted;
    struct functional_face_sdk_binding binding;
    struct functional_face_transfer transfer;
    struct functional_face_sdk_transaction last;
};
/* No source operation, new epoch, default provider or implicit enable at init.
 * Missing integration => -ENODATA. PID/TID must be the actual current caller. */
int functional_face_sdk_init(struct functional_face_sdk *, const struct functional_face_sdk_binding *);
/* caller_bound==1 is an assertion by the trusted parent, NOT authentication.
 * original_sender_started must be exactly zero: never take over queued work.
 * out is required. Preflight failures are unclaimed; started means no original
 * sender fallback, even when acquire returns failure without a caller lease.
 * Successful content invokes status0/original context exactly once before
 * return. Failed invocation is sticky/uncertain; return its real rc to the
 * parent, which must NOT feed a possible post-completion error to Sony cleanup.
 * Guard/busy/duplicate errors leave out and the saved transaction unchanged. */
int functional_face_sdk_submit(struct functional_face_sdk *, const void *api40, size_t bytes,
    int caller_bound, int original_sender_started, struct functional_face_sdk_transaction *out);
#endif
