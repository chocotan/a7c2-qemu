#ifndef NATIVE_VIDEO_RING_CONTRACT_H
#define NATIVE_VIDEO_RING_CONTRACT_H

#include <stddef.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

#define NRING_INFO_BYTES 96u

/* Host projection of only the proved fields in an original 0x24-byte record:
 * id at +0, read_index at +4, status at +0x1c. Never cast the original table. */
struct nring_user {
    uint32_t id, read_index, status;
};
struct nring_advance {
    uint32_t user_read_index, shared_read_index, delta;
};

/* Cursor = last processed slot; copy every available slot, starting at R+1.
 * Capacities are bytes and describe the FULL caller-owned accessible spans.
 * All declared spans (including unused tails and out_count) must be disjoint.
 * NULL out_bytes is allowed only with zero capacity and an empty read list.
 * No index changes, metadata interpretation, ES reads, or native completion. */
int nring_copy_read_list(const uint8_t *ringbytes, size_t ring_capacity,
    uint32_t slot_count, uint32_t write_index, uint32_t user_read_index,
    uint8_t *out_bytes, size_t out_capacity, size_t *out_count);

/* Plan SetVideoInfoReadIndexCount for one coherent, externally locked snapshot.
 * Status 1/2/3 is active; other statuses are skipped. IDs must be unique.
 * returned_count is actually processed SLOT count, not bytes; borrowed_count
 * MUST be the real out_count from that same immutable read-list snapshot.
 * Caller establishes native consumer completion, applies the user index, then
 * performs the actual source-appropriate release barrier before shared store.
 * This function proves neither ES consumption nor hardware/lease completion.
 * count=0 succeeds and can still move the shared cursor to the active minimum.
 * The full users array and result span must be disjoint and suitably aligned. */
int nring_advance_read(const struct nring_user *users, size_t user_count,
    uint32_t user_id, size_t returned_count, size_t borrowed_count,
    uint32_t slot_count, uint32_t write_index, uint32_t shared_read_index,
    struct nring_advance *result);

/* Both helpers return 0 or a positive errno code, preserving errno itself.
 * EINVAL: null/misaligned/overlapping spans, duplicate IDs, or zero slot_count.
 * ERANGE: cursor/count outside its bound; EOVERFLOW: host span/product wraps.
 * ENOSPC: insufficient storage (no partial copy); ENODATA: no selected user.
 * ENOTSUP: selected user exists but its status is inactive/unknown.
 * Every error leaves ALL output bytes, output counts, and inputs unchanged.
 * Caller supplies valid accessible objects of each declared extent and holds
 * the actual source lock across snapshot, native consumption, and application.
 * These pure helpers contain no synchronization, producer, ACK, or MMIO API. */

#ifdef __cplusplus
}
#endif
#endif
