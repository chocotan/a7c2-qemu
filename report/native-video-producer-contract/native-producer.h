#ifndef NATIVE_VIDEO_PRODUCER_CONTRACT_H
#define NATIVE_VIDEO_PRODUCER_CONTRACT_H

#include <stddef.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

#define NPRODUCER_SOURCE_BYTES 88u
#define NPRODUCER_INFO_BYTES 96u

struct nproducer_record {
    uint8_t wire[NPRODUCER_INFO_BYTES];
    uint8_t semantic_written_bits[NPRODUCER_INFO_BYTES];
};

/* Exact K162ff4 converter, given a resolved, immutable WHOLE internal record.
 * source_size must be exactly 88; baseline_size exactly 96. U and G are the
 * FULL known bytes from C+0x94dd0/C+0x94e98. aux_present must be 0 or 1;
 * aux_next is explicitly supplied and truncates to u16 when used. No array
 * indexing, guessed default, metadata type filtering, allocation or guest IO.
 * Every unassigned wire bit retains the mandatory caller-supplied baseline.
 * K160614 actually clears its local baseline before this converter; callers
 * may explicitly supply those known zero bytes, never infer a generic default.
 * semantic_written_bits describes defined fields, NOT knownness, readiness or
 * a generic patch mask: wire[3]=(baseline[3]&0xfe)|U may also SET opaque upper
 * bits when U has upper bits set, although only bit 0 is semantically defined.
 * source and baseline may overlap. Their full declared spans must be disjoint
 * from the ENTIRE out_capacity, including its unused tail. Byte inputs and
 * struct nproducer_record have alignment 1. Success writes sizeof(*out) only.
 */
int nproducer_convert(const uint8_t *source88, size_t source_size,
    uint8_t U, uint8_t G, uint8_t aux_present, uint32_t aux_next,
    const uint8_t *baseline96, size_t baseline_size,
    struct nproducer_record *out, size_t out_capacity);

struct nproducer_publish_plan {
    uint64_t slot_address, control_index_address; /* Logical values, not pointers. */
    uint32_t record_size, index;
    uint32_t current_after, occupied_after, source_result;
    uint8_t post_publication_queue_full;
};

/* Pure K161374/K168ccc plan for one externally serialized coherent snapshot.
 * Q=C+0x8b390: current at +0, N at +8, occupied at +0xc. j=current+1 resets
 * ONLY when equal to N. Slot size is the proved 96-byte caller size. Supplied
 * slot_count is independent of internal_N; equality is NOT proved/required.
 * Checks j within the supplied ring, original W32 j*96 without wrap, full
 * logical supplied ring extent, and control_base+4's full u32 store extent.
 * Source order: copy96 -> ACTUAL source DSB SY -> store j at control_base+4
 * -> internal queue update. This function performs NONE of these actions.
 * If occupied==N, publication still precedes queue-full callback operation
 * 0x0e (argument C+0x94db0, unmodeled): source_result=1, post flag=1 and both
 * internal counters unchanged. This is a successful plan, not a preflight
 * rejection/rollback. Otherwise source_result=0, current_after=j and count+1.
 * Output must be aligned for struct nproducer_publish_plan; its full declared
 * capacity must be accessible. Success writes sizeof(*out) only. No callback,
 * host fence standing in for DSB, memory copy, index/queue store, or native ACK.
 */
int nproducer_plan_publish(uint64_t slot_base, uint32_t supplied_slot_count,
    uint64_t control_base, uint32_t current, uint32_t internal_N,
    uint32_t occupied, struct nproducer_publish_plan *out, size_t out_capacity);

/* Both return 0 or negative errno, preserving errno and all inputs.
 * Every error leaves ALL output bytes (including capacity tail) unchanged.
 * EINVAL: null, wrong oversized input, aux_present>1, alias, alignment, N/count=0;
 * ENODATA: short source/baseline; ENOSPC: short output; ERANGE: invalid cursor,
 * occupied>N, or j outside supplied count; EOVERFLOW: host/logical extent or
 * original W32 offset wraps. Caller guarantees accessible immutable extents;
 * arithmetic validation cannot establish mappings, provenance, or a lease.
 * Neither helper closes producer fill, pixels, completion, MPR identity or
 * native capture. Existing NVIDEO_NATIVE_GAPS remains 63.
 */

#ifdef __cplusplus
}
#endif
#endif
