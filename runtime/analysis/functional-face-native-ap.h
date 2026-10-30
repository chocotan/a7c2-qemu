/* SPDX-License-Identifier: MIT */
#ifndef FUNCTIONAL_FACE_NATIVE_AP_H
#define FUNCTIONAL_FACE_NATIVE_AP_H
#include "functional-face-transfer.h"
#include "functional-face-ap-observer.h"

/* Saved AT the original allocation, never reconstructed from a current handle.
 * span.epoch is the parent's allocation identity, not observation_sequence.
 * owners/opens/shares are the actual native +08/+09/+0a bytes. */
struct functional_face_native_ap_reference {
    struct functional_face_ap_span span;
    uint64_t birth_sequence, unit_identity, extent_identity;
    uint32_t allocation_sequence, generation, state, owners, opens, shares;
};
struct functional_face_native_ap_input { uint32_t unit, chip, handle; };
struct functional_face_native_ap_operation {
    struct functional_face_ap_observer observed;
    struct functional_face_native_ap_reference before, after;
};
struct functional_face_native_ap_range { uint64_t backing, offset, bytes; };
#define FUNCTIONAL_FACE_NATIVE_AP_MAX_RANGES 128u
/* Owned snapshot in stable member order; never a hull across unmapped gaps. */
struct functional_face_native_ap_range_set {
    uint32_t count;
    struct functional_face_native_ap_range ranges[FUNCTIONAL_FACE_NATIVE_AP_MAX_RANGES];
};
struct functional_face_native_ap_mapping {
    uint64_t lease, address, physical;
    struct functional_face_native_ap_range source;
    struct functional_face_native_ap_range_set sdk, mailer;
};
struct functional_face_native_ap_mapping_proof {
    struct functional_face_native_ap_mapping mapping;
    struct functional_face_dmm_descriptor destination;
    struct functional_face_native_ap_range_set cp;
};
enum functional_face_native_ap_writer_action {
    FACE_NATIVE_AP_WRITER_BEGIN = 1, FACE_NATIVE_AP_WRITER_CHECK, FACE_NATIVE_AP_WRITER_END
};
struct functional_face_native_ap_writer {
    struct functional_face_native_ap_reference current;
    /* A unique reader lease binds original caller/writer/completion identities
     * and excludes ALL writers until END; equal observations alone do not. */
    uint64_t lease, writer_identity, completion_identity, writer_sequence, completed_sequence;
    /* Optional one source-proven original-owner 23 (2 -> 1), not an inferred
     * count change. This is not the provider's extra-owner balance. */
    struct functional_face_native_ap_operation producer_drop;
};
struct functional_face_native_ap_ops {
    /* Calls original APIs only: 21/24 input is {unit,chip0,handle}; 25 is Close;
     * 23 is low Free(handle,mode0). Preserve the entire actual observer ticket,
     * including on failure. Helper return zero is NOT a kernel owner proof.
     * Share/Open SDK result needs 32 bytes: error@24, padding@28. */
    int (*original_native_operation)(void *, uint32_t,
        const struct functional_face_native_ap_input *, struct functional_face_native_ap_operation *);
    long (*read_physical)(void *, const struct functional_face_native_ap_mapping *, uint64_t, void *, size_t);
    /* Trusted backend boundary: NULL destination proves the single contiguous
     * source and COMPLETE SDK/mailer canonical range sets, not just their VAs.
     * Otherwise also prove EVERY registered CP mapped page, including padding:
     * exact destination identity, page-aligned offsets/page-multiple extents,
     * summed bytes == mapped_bytes. Coalesce only genuinely contiguous ranges.
     * One canonical backing identity must resolve aliases across all mappings;
     * domain/VA differences are no proof. Stable ordered snapshots are borrowed
     * from the writer lease until END. Missing evidence => ENODATA, never an
     * assumed contiguous range. Nonempty sets alone prove no pin/PFN validity. */
    int (*prove_mapping_and_disjoint)(void *, const struct functional_face_native_ap_reference *,
        uint64_t native_address, size_t, const struct functional_face_dmm_descriptor *,
        struct functional_face_native_ap_mapping_proof *);
    /* BEGIN binds the saved birth to actual same-allocation metadata; CHECK and
     * END return current refs and the SAME writer capability. END is all-or-
     * nothing. Missing actual serial/consistency evidence must return ENODATA.
     * These callbacks are trusted integration boundaries, not authentication:
     * a test callback cannot turn this module into a verified native backend. */
    int (*source_writer_serial)(void *, enum functional_face_native_ap_writer_action,
        const struct functional_face_ap_birth *, const struct functional_face_native_ap_reference *,
        const struct functional_face_native_ap_writer *, struct functional_face_native_ap_writer *);
};
/* Caller-owned zero-initialized, single-thread/process, single acquisition.
 * Keep context, observer and IO backend alive after EVERY retained fault. */
struct functional_face_native_ap {
    _Atomic unsigned int busy;
    int owner_pid;
    int64_t owner_tid;
    uint32_t initialized, attempted, faulted, uncertain, source_live, owner_live, open_live, writer_live;
    uint32_t close_attempted, free_attempted, producer_dropped, candidate_capability;
    int last_error, cleanup_error;
    uint64_t last_sequence, native_address;
    size_t bytes_read;
    const struct functional_face_ap_observer *observer;
    struct functional_face_ap_birth birth;
    struct functional_face_native_ap_reference native_birth, reference;
    struct functional_face_native_ap_writer writer, last_writer;
    struct functional_face_native_ap_mapping mapping;
    struct functional_face_dmm_descriptor destination;
    struct functional_face_native_ap_range_set cp;
    struct functional_face_native_ap_mapping_proof last_mapping;
    struct functional_face_native_ap_operation operations[4], producer_drop;
    struct functional_face_ap_borrow token;
    struct functional_face_native_ap_ops ops;
    void *io_context;
};
/* No defaults, environment activation, native-ready/ACK writes or SDK calls at
 * init. Missing ops/evidence => -ENODATA; outputs unchanged on failure.
 * acquire failure returns NO caller lease, but uncertain native resources can
 * remain in this provider's sticky retained-fault context. */
int functional_face_native_ap_init(struct functional_face_native_ap *,
    const struct functional_face_native_ap_ops *, void *, const struct functional_face_ap_observer *,
    const struct functional_face_native_ap_reference *, struct functional_face_ap_provider *);
#endif
