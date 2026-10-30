/* SPDX-License-Identifier: MIT */
#ifndef FUNCTIONAL_FACE_DMM_H
#define FUNCTIONAL_FACE_DMM_H
#include <stddef.h>
#include <stdint.h>
#include "device-models/imaging-device.h"

#define FUNCTIONAL_FACE_DMM_CP UINT32_C(0x9061003c)
#define FUNCTIONAL_FACE_DMM_DOMAIN 1u
#define FUNCTIONAL_FACE_DMM_UNITS 3u
#define FUNCTIONAL_FACE_DMM_PAGE 4096u
#define FUNCTIONAL_FACE_DMM_READ 1u
#define FUNCTIONAL_FACE_DMM_WRITE 2u
#define FUNCTIONAL_FACE_DMM_TRANSFER 4u

/* Software profile: indices 2/3/4, page-aligned anonymous backing, zero-init.
 * logical is supplied by the parent's registry, never derived from host_view.
 * owner is the parent's trusted producer identity; reference=0 is its creator.
 * Handle-only wire users MUST supply their saved epoch/owner/reference binding.
 * Copying a current descriptor onto an old ambiguous wire request is forbidden. */
struct functional_face_dmm_descriptor {
    uint32_t domain, unit, handle;
    uint64_t epoch, owner, reference, logical, registration;
    uintptr_t host_view;
    size_t bytes, mapped_bytes;
};
struct functional_face_dmm_registry {
    void *context;
    /* Only logical/registration may change. All-or-nothing on failure. The
     * registration must resolve the entire owned host span in a distinct IOVA
     * domain. All three callbacks are required; there is no default backend.
     * Calls run outside the private mutex; reentry is refused with -EBUSY. */
    int (*register_span)(void *, struct functional_face_dmm_descriptor *);
    int (*validate_span)(void *, const struct functional_face_dmm_descriptor *);
    /* Nonzero means registration/backing still valid and owned; retain it. */
    int (*unregister_span)(void *, const struct functional_face_dmm_descriptor *);
};
struct functional_face_dmm_borrow {
    struct functional_face_dmm_descriptor span;
    uintptr_t host_view;
    uint64_t logical, nonce, before_digest;
    size_t offset, bytes;
    uint32_t access;
};
struct functional_face_dmm_readback {
    uint64_t before_digest, after_digest;
    size_t verified_bytes;
};
struct functional_face_dmm_ticket {
    uint64_t nonce;
    uintptr_t reply;
    uint32_t destination;
    unsigned char wire[40];
    struct functional_face_dmm_descriptor span;
};
struct functional_face_dmm_unit_snapshot {
    struct functional_face_dmm_descriptor span;
    uint32_t allocated, generation, opens, shares, borrows, transfers;
    uint64_t digest, verified_write_bytes, verified_read_bytes;
};
struct functional_face_dmm_snapshot {
    int owner_pid;
    uint32_t enabled, busy, faults, live_requests, live_replies, retained_cleanup;
    uint64_t epochs, queued, request_freed, reply_freed, received, ap_consumed;
    struct functional_face_dmm_unit_snapshot units[FUNCTIONAL_FACE_DMM_UNITS];
};

/* Explicit functional-profile activation; no constructor, no CoreREADY. Forks
 * fail before locks. Errors are negative errno and leave outputs unchanged. */
int functional_face_dmm_enable(const struct functional_face_dmm_registry *);
int functional_face_dmm_snapshot(struct functional_face_dmm_snapshot *);
int functional_face_dmm_shutdown(void);

/* Return 0 to decline unknown/malformed/disabled traffic to the strict backend.
 * Wire offsets are hexadecimal: only 20/24 use +0c=ffffffff; 21/23/25 use 0.
 * The u16 at +14 is low16(io->source(request)) for 23, otherwise zero;
 * +16 is face mode zero. Other callers/modes and opcode 2a are declined.
 * Replies follow the existing dmm-service software policy; the original CP
 * response producer is not pinned by the request/consumer source evidence.
 * Handled returns 1 and sets result to the actual transport result. A nonzero
 * send result leaves caller ownership of the request; cleanup failures retain
 * ownership and fault the domain. No callback runs under this module's mutex.
 * binding is trusted parent metadata, NEVER inferred from the request handle.
 * Successful queue publishes a reply lease before inline receive/free reentry. */
int functional_face_dmm_dispatch(unsigned int, void *, const struct full_imaging_io *,
    int enabled, const struct functional_face_dmm_descriptor *binding, int *result);
/* Parent calls after actual successful original receive, on its sender TID.
 * The immutable ticket includes exact wire bytes, nonce, destination and span.
 * Descriptor publication is through this ticket, never an unbound handle lookup. */
int functional_face_dmm_receive(unsigned int, void *, struct functional_face_dmm_ticket *);
/* Parent intercepts original sender free: actual release=0 plus a previously
 * validated receive ticket is required for ap_consumed. Failure retains lease.
 * Return 0 for an unrelated message; otherwise 1 and the real release result. */
int functional_face_dmm_release_reply(unsigned int, void *,
    const struct functional_face_dmm_ticket *, int (*)(unsigned int, void *), int *);

/* Acquires an actual current owned range; epoch/domain/owner/reference required.
 * WRITE is exclusive, READ may coexist. TRANSFER is an additional lease flag.
 * A close revokes that reference's byte access but retains outstanding borrowed
 * backing until release; unit_free refuses every outstanding open/share/borrow/
 * transfer/transport lease. */
int functional_face_dmm_borrowed_span(const struct functional_face_dmm_descriptor *,
    size_t offset, size_t bytes, unsigned int access, struct functional_face_dmm_borrow *);
int functional_face_dmm_write(const struct functional_face_dmm_borrow *, size_t,
    const void *, size_t, struct functional_face_dmm_readback *);
int functional_face_dmm_read(const struct functional_face_dmm_borrow *, size_t,
    void *, size_t, struct functional_face_dmm_readback *);
int functional_face_dmm_release_borrow(const struct functional_face_dmm_borrow *,
    struct functional_face_dmm_readback *);
#endif
