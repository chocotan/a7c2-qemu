/* SPDX-License-Identifier: MIT */
#ifndef FUNCTIONAL_FACE_TRANSFER_H
#define FUNCTIONAL_FACE_TRANSFER_H
#include "functional-face-runtime.h"
#include <stdatomic.h>

/* Actual AP allocation identity saved by the native provider, not a wire lookup. */
struct functional_face_ap_span {
    uint32_t domain, unit, handle;
    uint64_t epoch, owner;
    size_t bytes;
};
struct functional_face_ap_borrow {
    struct functional_face_ap_span span;
    uint64_t nonce;
    size_t offset, bytes;
};
struct functional_face_ap_provider {
    void *context;
    /* Failure owns no lease; success returns the complete actual immutable token. */
    int (*acquire)(void *, const struct functional_face_ap_span *, size_t, size_t,
        struct functional_face_ap_borrow *);
    /* Must return the actual number of bytes read, or a negative error. */
    long (*read)(void *, const struct functional_face_ap_borrow *, size_t, void *, size_t);
    /* Must prove distinct backing; different address-domain labels alone do not. */
    int (*check_disjoint)(void *, const struct functional_face_ap_borrow *,
        const struct functional_face_dmm_descriptor *);
    int (*release)(void *, const struct functional_face_ap_borrow *);
};
/* The original input20 after bounded descriptor reads, not SDK pointer casts. */
struct functional_face_transfer_input {
    uint32_t source_handle, source_offset, destination_handle, destination_offset, bytes;
};
struct functional_face_api_request {
    struct functional_face_transfer_input input;
    uintptr_t source_descriptor, destination_descriptor, callback, callback_context;
};
/* The exported SDK reads only a 40-byte API input. No result/padding fields are
 * present here; those belong to its separately allocated 48-byte OSAL message. */
int functional_face_transfer_decode_api40(const void *, size_t,
    long (*read_descriptor)(void *, uintptr_t, void *, size_t), void *, struct functional_face_api_request *);
struct functional_face_sdk_request {
    struct functional_face_transfer_input input;
    uintptr_t source_descriptor, destination_descriptor, callback, callback_context;
    uint32_t submission_result_before, opaque_padding;
};
/* Byte decoding only: the parent separately proves the original SDK caller and
 * native allocation identities. Read each descriptor twice; output unchanged on
 * failure. Neither callback invocation nor a submission-result write occurs. */
int functional_face_transfer_decode_sdk48(const void *, size_t,
    long (*read_descriptor)(void *, uintptr_t, void *, size_t), void *, struct functional_face_sdk_request *);
struct functional_face_transfer_receipt {
    uint64_t source_digest, destination_digest;
    size_t written, readback;
    uint32_t source_acquired, destination_acquired, source_released, destination_released, content_complete;
    int operation_result, source_release_result, destination_release_result;
};
struct functional_face_transfer {
    _Atomic unsigned int busy;
    int owner_pid;
    uint32_t initialized, faulted, source_live, destination_live, destination_release_attempted;
    struct functional_face_ap_provider provider;
    struct functional_face_ap_borrow source;
    struct functional_face_dmm_borrow destination;
    struct functional_face_transfer_receipt last;
};
/* Zero-initialized caller-owned state. No default AP provider or native ACK. */
int functional_face_transfer_init(struct functional_face_transfer *, const struct functional_face_ap_provider *);
/* Only the three original face transfers, offsets zero and exact unit lengths.
 * Both saved identities are required. Zero means content readback AND actual
 * source/destination lease releases passed. This does NOT send the original
 * 48+24 completion or prove AP/ASIC/capture. Failed cleanup retains full leases
 * in state, faults it, and is never retried implicitly. Read last only at idle. */
int functional_face_transfer_copy(struct functional_face_transfer *, uint64_t producer_owner,
    const struct functional_face_ap_span *saved_source,
    const struct functional_face_dmm_descriptor *saved_destination,
    const struct functional_face_transfer_input *);
#endif
