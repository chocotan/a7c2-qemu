/* SPDX-License-Identifier: MIT */
#ifndef NATIVE_CP_UPM_HCRN_H
#define NATIVE_CP_UPM_HCRN_H
#include <stddef.h>
#include <stdint.h>

#define CP_UPM_HCRN_BYTES 16u
#define CP_UPM_HCRN_PUBLICATION_BYTES 20u
#define CP_UPM_HCRN_HANDLE UINT32_C(0x92a20845)
#define CP_UPM_HCRN_QUERY UINT32_C(0x00920162)
#define CP_UPM_HCRN_PUBLICATION UINT32_C(0x00920256)
#define CP_UPM_HCRN_DESTINATION UINT32_C(0x9092083f)
/* CP32 evidence tokens, never host pointers: init c0dc50, callback c0dd1b
 * (Thumb c0dd1a), cache 011f70f4, local queue index 0845 under 120f7c0.
 * c0dc8c/90 explicitly zero the CP cache; AP's [0,6,26,31] is unrelated.
 * bebc34 releases the original queue lock around callback(payload,arg0).
 * This private lock only serializes this actor, not original 128-bit copies. */
struct cp_upm_hcrn;
struct cp_upm_hcrn_view {
    uint64_t serial, generation, publications_consumed, queries, callbacks;
    uint64_t last_query_generation;
    uint32_t cache_fnv, publication_fnv, request_fnv, readback_fnv, requested;
    unsigned int virtual_registered, original_registration_verified;
    unsigned int initialized_cache_only, publication_source_runtime_verified;
    unsigned int ap_current_value_verified, source_atomic_snapshot_verified;
    unsigned int publication_history_runtime_complete;
    unsigned char cache[CP_UPM_HCRN_BYTES], cache_known[CP_UPM_HCRN_BYTES];
    unsigned char last_readback[CP_UPM_HCRN_BYTES];
};
/* Source closure: public menu-root/cp/cpapp-b.bin and pinned windows in the
 * Python host tests. No original code executes here. Registration in c0dc50
 * ignores its return; only our allocation/mutex/internal C binding is proved.
 * No operation upgrades original registration/AP/publication/atomic claims. */
struct cp_upm_hcrn *cp_upm_hcrn_create(void);
/* Caller owns immutable packet/mask spans through return. Destination is a
 * numeric CP32 envelope SID, not packet[0]. Require exact 20B and all known=1;
 * consume [00920256,H,C,R,N], copying all 16 data bytes and their masks. */
int cp_upm_hcrn_consume_publication(struct cp_upm_hcrn *, uint32_t destination,
    const unsigned char *packet, size_t size, const unsigned char *known, size_t known_size);
/* Exact source caller 328d18: 62019200000000000000000000000000, known[16]=1.
 * Body/mask must be separate writable 16B spans. Success replaces ALL body
 * bytes with H,C,R,N from the owned cache; no retained command/business ACK.
 * Unknown commands are UNHANDLED (-ENOTSUP), unknown masks fail (-EAGAIN).
 * Parent validates source SID 90030001 in its actual allocator/transport.
 * Zero return describes this call only, never readiness or module completion.
 * No message allocation, ownership transfer, external callbacks or queue ABI. */
int cp_upm_hcrn_query_in_place(struct cp_upm_hcrn *, uint32_t handle,
    unsigned char *body, size_t size, unsigned char *known, size_t known_size);
int cp_upm_hcrn_snapshot(struct cp_upm_hcrn *, struct cp_upm_hcrn_view *);
/* All operations are PID-owned. Destroy requires caller quiescence. */
int cp_upm_hcrn_destroy(struct cp_upm_hcrn *);
#endif
