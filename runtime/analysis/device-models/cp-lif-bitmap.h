/* SPDX-License-Identifier: MIT */
#ifndef NATIVE_CP_LIF_BITMAP_H
#define NATIVE_CP_LIF_BITMAP_H
#include "cp-lif-frame.h"

#define CP_LIF_BITMAP_PROPERTY_BYTES 0x162u
#define CP_LIF_BITMAP_COMMAND_BYTES 17u
#define CP_LIF_BITMAP_WIRE_BYTES 25u
#define CP_LIF_BITMAP_DMA_SPAN 32u
#define CP_LIF_BITMAP_OWNER_REVISION 1u

enum cp_lif_bitmap_input_known {
    CP_LIF_BITMAP_K_KNOWN = 1u,
    CP_LIF_BITMAP_MODE_KNOWN = 2u,
    CP_LIF_BITMAP_Z_KNOWN = 4u,
    CP_LIF_BITMAP_S43_KNOWN = 8u,
    CP_LIF_BITMAP_S5A_KNOWN = 16u
};
/* External serialization is mandatory. Even matching sequences describe one
 * immutable source transaction. They cannot prove a native source event. */
struct cp_lif_bitmap_guard {
    uint32_t owner_pid;
    uint64_t sequence_before, sequence_after;
    enum cp_lif_origin origin;
    unsigned char quiescent;
};
/* K: [1a03ac0+10] via a909b0; property: *1a03cdc, little endian;
 * mode: [1107178]; Z: [1b1ad1d], coherent for BOTH a9902a reads;
 * s43/s5a: actual helper results using support source 1719e40.
 * No fallback values: only source-consumed fields need be known. */
struct cp_lif_bitmap_inputs {
    uint32_t known, k, mode;
    unsigned char z, s43, s5a;
    unsigned char property[CP_LIF_BITMAP_PROPERTY_BYTES];
    unsigned char property_known[CP_LIF_BITMAP_PROPERTY_BYTES];
};
struct cp_lif_bitmap_product {
    unsigned char bitmap[CP_LIF_BITMAP_BYTES], gate;
    unsigned char command[CP_LIF_BITMAP_COMMAND_BYTES];
    unsigned char wire[CP_LIF_BITMAP_WIRE_BYTES];
    unsigned char logical_bytes, dma_span, dma_known_bytes;
    unsigned char owned_virtual_data; /* never native wire execution */
};
struct cp_lif_bitmap_lease {
    uint64_t token, configured_generation, producer_sequence;
    uint32_t owner_pid;
    enum cp_lif_origin origin;
    unsigned char wire[CP_LIF_BITMAP_WIRE_BYTES];
    unsigned char logical_bytes, dma_span, dma_known_bytes, owned_virtual_data;
};
/* Caller-owned fixed storage; treat members as private. Never memcpy/reset an
 * initialized owner to reuse tokens; no mutex, pointers or globals are kept. */
struct cp_lif_bitmap_owner {
    uint32_t revision, owner_pid;
    enum cp_lif_origin origin;
    uint64_t sequence, configured_generation, data_producer_sequence;
    uint64_t next_token, consumed_generation, consumed_producer_sequence;
    unsigned char configured[CP_LIF_BITMAP_BYTES], gate, configured_known;
    unsigned char pending, owned_transport_consumed;
    struct cp_lif_bitmap_lease lease;
};
struct cp_lif_bitmap_received {
    uint64_t configured_generation, consumed_generation, data_producer_sequence;
    unsigned char configured_matches_consumed, owned_virtual_data;
    struct cp_lif_frame_context context; /* SNAPSHOT exists only here */
    struct cp_lif_decoded_frame decoded; /* owns its received bytes */
};
/* All APIs return 0 or -errno. Errors leave owner and output unchanged.
 * Full output capacity may not overlap inputs/owner, even its unused tail.
 * Callers supply accessible immutable storage and the external lock. */
int cp_lif_bitmap_build(const struct cp_lif_bitmap_inputs *,
    const struct cp_lif_bitmap_guard *, struct cp_lif_bitmap_product *, size_t);
/* Requires zero-initialized storage. Init records origin/PID/sequence only;
 * configured bitmap and gate remain unknown until an actual named event. */
int cp_lif_bitmap_owner_init(struct cp_lif_bitmap_owner *,
    const struct cp_lif_bitmap_guard *);
/* a946fe selector 1 builds+commits then produces a copied lease if no lease is
 * pending. While pending it STILL commits newer configuration, returns a zero
 * lease, and preserves the old immutable lease. This is not enqueue/send.
 * Selector 2 is -ENOTSUP (1719ee8 is not configured). Other selectors execute
 * a92296 clear under the caller's resource-31-equivalent lock, without wire.
 * Successful mutations require a strictly newer guard sequence. */
int cp_lif_bitmap_request(struct cp_lif_bitmap_owner *, unsigned selector,
    const struct cp_lif_bitmap_inputs *, const struct cp_lif_bitmap_guard *,
    struct cp_lif_bitmap_lease *, size_t);
/* a92590: clear only the gate; bitmap generation stays unchanged. */
int cp_lif_bitmap_gate_clear(struct cp_lif_bitmap_owner *,
    const struct cp_lif_bitmap_guard *);
/* Receipt requires all 25 ACTUAL consumed bytes, exact lease identity and a
 * newer guard. It retires the single pending lease. No rc==0 sentinel. */
int cp_lif_bitmap_observe_transport_consumed(struct cp_lif_bitmap_owner *,
    const struct cp_lif_bitmap_lease *, const unsigned char *actual, size_t,
    const struct cp_lif_bitmap_guard *);
/* Explicit receive boundary: copy current configured B+gate into a923d0
 * context and invoke the existing decoder on immutable rx. Conservative owner
 * policy requires latest config generation == last consumed generation;
 * source itself snapshots current config even if newer/unsent. No CP state,
 * ACK, readiness, source queue-admission or native DMA claim is made.
 * Requires a newer guard; success records sequence, errors are atomic. */
int cp_lif_bitmap_receive_decode(struct cp_lif_bitmap_owner *,
    const unsigned char *rx, size_t, const struct cp_lif_bitmap_guard *,
    struct cp_lif_bitmap_received *, size_t);
#endif
