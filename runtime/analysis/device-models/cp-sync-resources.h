/* SPDX-License-Identifier: MIT */
#ifndef NATIVE_CP_SYNC_RESOURCES_H
#define NATIVE_CP_SYNC_RESOURCES_H
#include <stddef.h>
#include <stdint.h>

/* Finite virtual backing policy, not Sony's allocation ABI. IDs and idle
 * predicate come from CP2.01 SyncResMgr: 72 entries, excluding SGC1 (12).
 * No CP status, ACK, pixels, init completion or guest address is synthesized.
 * A backend must bind its real buffer operations to this bank before using
 * idle as one prerequisite of module0108; other prerequisites are independent.
 * Bytes are copied through checked leases; internal pointers never escape.
 * Successful acquire/alias permanently freezes writes until backing free.
 * Release drops a reference, not backing. The allocation's initial lease token
 * remains its backing identity after release; free must match that identity
 * and requires every alias unreferenced. Old frees cannot retire a reused ID.
 * Instances inherited through fork refuse use, including destruction. Tokens
 * are process-wide unique, so another bank cannot accept a foreign lease.
 * The owner must quiesce callers before destruction (ordinary C lifetime). */
#define CP_SYNC_RESOURCE_COUNT 72u
#define CP_SYNC_LEASE_COUNT 256u
struct cp_sync_resources;
struct cp_sync_snapshot {
    size_t bytes;
    unsigned int backing_groups, bound_resources, references;
    int idle;
};
struct cp_sync_resources *cp_sync_create(size_t budget);
int cp_sync_destroy(struct cp_sync_resources *);
int cp_sync_allocate(struct cp_sync_resources *, unsigned int id, size_t bytes, uint64_t *lease);
int cp_sync_alias(struct cp_sync_resources *, unsigned int id, uint64_t source, uint64_t *lease);
int cp_sync_acquire(struct cp_sync_resources *, unsigned int id, uint64_t *lease);
int cp_sync_release(struct cp_sync_resources *, uint64_t lease);
int cp_sync_free(struct cp_sync_resources *, unsigned int id, uint64_t allocation);
int cp_sync_write(struct cp_sync_resources *, uint64_t, size_t offset, const void *, size_t);
int cp_sync_read(struct cp_sync_resources *, uint64_t, size_t offset, void *, size_t);
int cp_sync_snapshot(struct cp_sync_resources *, struct cp_sync_snapshot *);
#endif
