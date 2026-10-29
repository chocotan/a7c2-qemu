/* SPDX-License-Identifier: MIT */
#ifndef FUNCTIONAL_MPR_MEMORY_H
#define FUNCTIONAL_MPR_MEMORY_H
#include <stddef.h>
#include <stdint.h>

#define FUNCTIONAL_MPR_MEMORY_TABLE_BYTES 0x760u
#define FUNCTIONAL_MPR_MEMORY_GENERATIONS 4u
#define FUNCTIONAL_MPR_MEMORY_MAIN_BYTES (32u * 1024u * 1024u)
#define FUNCTIONAL_MPR_MEMORY_SECONDARY_BYTES (8u * 1024u * 1024u)
#define FUNCTIONAL_MPR_MEMORY_METADATA_BYTES (16u * 1024u * 1024u)
#define FUNCTIONAL_MPR_MEMORY_FIXED_BYTES 512u
#define FUNCTIONAL_MPR_MEMORY_LIBRARY_SHA256 \
 "4fb6d886c1ac620399d09c9c2ffc074315968cf0ada764062913c4e0783fc7f9"

struct functional_mpr_memory_span {
    uintptr_t virtual_base;
    uint64_t iova_base, generation;
    size_t capacity, offset;
    uint32_t group, unit, area, unit_type;
};
struct functional_mpr_memory_lease {
    struct functional_mpr_memory_span span;
    uintptr_t address;
    size_t bytes;
    uint64_t token;
};
struct functional_mpr_memory_snapshot {
    uint64_t mapped_bytes, generations, active_generation, leases;
    uint32_t enabled, active_group, active_mask, fixed_mapped;
};

/* Explicit functional-profile setup only; no constructor, no allocation here.
 * Callback receives metadata, runs outside the model lock, and must not
 * recursively allocate/free MPR memory. Returns 0 or negative errno. */
int functional_mpr_memory_enable(void (*record)(const char *, const char *));
/* Only current owned RW spans are queryable, including the separate 512-byte
 * fixed area. IOVA is an identity software address, never a physical RAM claim.
 * Failure leaves caller output unchanged. All APIs reject a fork before locks. */
int functional_mpr_memory_query(uintptr_t address, size_t bytes,
    struct functional_mpr_memory_span *);
/* Codec must acquire before writing, validate before publication, then release.
 * Retirement invalidates validation/query but retains the actual mapped bytes.
 * A token owns one real span; duplicate releases fail. */
int functional_mpr_memory_acquire(uintptr_t address, size_t bytes,
    struct functional_mpr_memory_lease *);
int functional_mpr_memory_validate(const struct functional_mpr_memory_lease *);
/* Copies immutable input into a live lease and verifies destination readback
 * while serialized against Free. Retired tokens never write. */
int functional_mpr_memory_write(const struct functional_mpr_memory_lease *,
    size_t offset, const void *data, size_t bytes);
int functional_mpr_memory_release(uint64_t token);
int functional_mpr_memory_snapshot(struct functional_mpr_memory_snapshot *);
/* Parent stops codec workers and flushes original MPR/Fsys before calling.
 * Refuses an active group or outstanding lease, retaining mappings on refusal.
 * Successful shutdown disables the wrappers and unmaps retired generations. */
int functional_mpr_memory_shutdown(void);

/* Type0 uses GetUnitInfo's unit ID directly, with separately registered area
 * metadata; never a pointer or packed unit/area. Acquire exactly the requested
 * current range in the same generation. Unknown handles return -ENODATA;
 * retired/changed identities return -ESTALE. Failure leaves output unchanged. */
int functional_mpr_memory_acquire_sds(uint32_t type, uint32_t handle,
    uint32_t offset, size_t bytes, struct functional_mpr_memory_lease *);

#endif
