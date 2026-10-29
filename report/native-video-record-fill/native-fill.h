#ifndef NATIVE_VIDEO_RECORD_FILL_H
#define NATIVE_VIDEO_RECORD_FILL_H

#include <stddef.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

#define NFILL_WORK_BYTES 0xe90u
#define NFILL_SEGMENT_COUNT 90u
#define NFILL_NODE_BYTES 0x18u
#define NFILL_RECORD_BYTES 88u
#define NFILL_NOTIFY_BYTES 24u

struct nfill_record {
    uint8_t wire[NFILL_RECORD_BYTES];
    uint8_t semantic_written_bits[NFILL_RECORD_BYTES];
};

/* Pure K2433e0 writer, adapting one AU in a whole immutable PRE-CALLBACK
 * work-item snapshot B (exactly 0xe90 bytes). first/last are explicit inclusive
 * compact-segment indexes, not inferred frame boundaries. L=B+0x620+j*0x10:
 * sum the original LE32(L+8), never an already rewritten cumulative length;
 * each selected length must be nonzero and selector L[0xd]<2, intermediate
 * L[0xc] must be zero and the last end marker must be nonzero. The AU pointer
 * is the full LE64(B+0xbc0+first*8), not the last segment's cursor.
 * Reject W32 length and u64 exclusive-end wrap instead of reproducing wrap.
 * No ES mapping, payload validity, completion or lease is established here.
 * nodeA is exactly 24 immutable bytes already resolved by the source lookup
 * K243e84 with LE16(B+6). This function performs no lookup/key inference.
 * baseline88 is mandatory and exactly 88 bytes: source writes 0..0x53;
 * 0x54..0x57 preserve baseline and have a zero semantic-written mask.
 * Inputs may overlap each other. Their FULL spans must be disjoint from the
 * ENTIRE out_capacity, including unused tail. Byte inputs and nfill_record
 * have alignment 1. Success writes sizeof(*out) only; no pointer is retained.
 */
int nfill_assemble(const uint8_t *workE90, size_t work_size,
    uint32_t first_segment_index, uint32_t last_segment_index,
    const uint8_t *nodeA, size_t node_size,
    const uint8_t *baseline88, size_t baseline_size,
    struct nfill_record *out, size_t out_capacity);

struct nfill_notify_plan {
    uint64_t record_address; /* Logical source S88 slot, never dereferenced. */
    uint32_t index, next_index, destination;
    uint8_t wire[NFILL_NOTIFY_BYTES];
};

/* Pure original 0x011c notification/index plan. index and N are the coherent
 * source cursor/capacity snapshot; CID=T+0x734 and unit=T+0x8e4 are full known
 * u32 values. primary_id is LE32(resolved nodeA+4). secondary_id is the actual
 * secondary lookup's LE32(node+4), or UINT32_MAX only when that lookup really
 * found no matching node. All are explicit inputs: no lookup/default/ACK.
 * Address uses full u64 index*0x58 (source UMADDL), with full N*88 extent and
 * exclusive-end validation. Source order: CPU-write S88 -> advance index ->
 * queue ORIGINAL index/cumulative length -> send wire24 to CID. This helper
 * returns values only: no copy, store, queue, barrier, send or callback.
 * Output must be aligned for nfill_notify_plan; only sizeof(*out) is written.
 */
int nfill_plan_notify(uint32_t index, uint32_t N, uint32_t cid,
    uint32_t unit, uint32_t primary_id, uint32_t secondary_id,
    uint64_t record_base, struct nfill_notify_plan *out, size_t out_capacity);

/* Return 0 or negative errno, preserving errno, all inputs and on failure ALL
 * output bytes, including tail. EINVAL: null, oversized input, alias, bad plan
 * alignment or N=0; ENODATA: short input or zero selected segment length;
 * ENOSPC: short output; ERANGE: first>last, index outside 90/N, selector>=2,
 * missing last end marker or intermediate end marker; EOVERFLOW: host span,
 * W32 cumulative length or u64 logical exclusive end wraps. Caller guarantees
 * accessible immutable full extents, coherent snapshots and lookup provenance.
 * No success result implies engine input/IRQ, ES ownership or native capture.
 * Existing NVIDEO_NATIVE_GAPS remains 63; native_capture remains false.
 */

#ifdef __cplusplus
}
#endif
#endif
