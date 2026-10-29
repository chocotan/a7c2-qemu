/* SPDX-License-Identifier: MIT */
#ifndef FULL_OSD_BUFFER_OWNER_H
#define FULL_OSD_BUFFER_OWNER_H

#define FULL_OSD_POOL_UNIT 0xe1700u
#define FULL_OSD_POOL_SLOTS 16u
#define FULL_OSD_POOL_EXTENT 256u
#define FULL_OSD_POOL_BYTES (FULL_OSD_POOL_SLOTS * FULL_OSD_POOL_EXTENT)
#define FULL_OSD_POOL_UNKNOWN_BYTE 0xa5u
#define FULL_OSD_POOL_REJECT (-1021)
#define FULL_OSD_PINMEM_SIDE 1u
#define FULL_OSD_PEER_SIDE 2u

/* Source unit record {e1700,0,e2,ffffffff} has nine allocation rules,
 * including {5,e2,100,10f,0}; nine rules do not establish a slot count.
 * This virtual FORMAT pool provides 16 persistent 256-byte resources for the
 * closed 4-peer/8-source/4-key0-completion path. Original capacity and CP pages
 * remain unverified.
 * The backing and semantic physical/CP bases belong to the binding caller;
 * they are not original RAM addresses, CPU aliases, pixels or RTOS emulation.
 * Untouched bytes are virtual poison a5 with known=0, never original zeroes.
 * Handles are explicit 32-bit virtual identities, not local 16-bit leases or
 * the original allocator's ABI. A retired generation is never reused/wrapped.
 */
struct full_osd_mapping {
    unsigned int handle, unit, extent, generation;
    unsigned long long physical;
    unsigned int cp_alias;
};

struct full_osd_pool_slot_snapshot {
    unsigned int live, handle, generation, creator_side, consumer_side;
    unsigned int owners, open_count, creator_open, consumer_open, known_bytes;
    struct full_osd_mapping mapping;
};

struct full_osd_pool_snapshot {
    unsigned int owner_pid, initialized, faults, live;
    unsigned long long allocations, releases, reads, writes, shares, opens;
    unsigned int original_allocator_capacity_verified, original_cp_pages_verified;
    struct full_osd_pool_slot_snapshot slots[FULL_OSD_POOL_SLOTS];
};

/* All operations return 0 or -1021. Invalid calls leave data/history unchanged.
 * Bind requires exactly 4096 bytes and aligned, non-overflowing semantic bases
 * distinct from the existing pin/sound namespaces. The caller retains exclusive
 * ownership of backing and keeps it mapped; all shared accesses use this API.
 * Bind poisons backing and clears its known mask, and only binds this PID.
 * Rebinding is refused while any resource lives; counters/generations persist.
 * Forked processes refuse before touching an inherited mutex, including bind.
 */
int full_osd_pool_bind(void *backing, unsigned int bytes,
                       unsigned long long physical, unsigned int cp_alias);
/* Allocate: creator owners/open=1/1. Share adds the opposite closed owner;
 * Open adds its one open, without another owner. Share never freezes writers.
 * Read/write/mapping require the named role's current owner and open.
 * Write takes one 0/1 known flag per byte and copies actual bytes and flags.
 * Both open roles see the current backing, rather than a notification cache.
 */
int full_osd_pool_allocate(unsigned int creator_side, unsigned int *handle);
int full_osd_pool_share(unsigned int creator_side, unsigned int handle);
int full_osd_pool_open(unsigned int consumer_side, unsigned int handle);
/* One op23 option2: close and drop only this role's open owner reference.
 * The other role stays usable; the final release retires the resource.
 * Snapshot releases counts successful role releases; opens counts op24 calls.
 */
int full_osd_pool_release(unsigned int side, unsigned int handle);
int full_osd_pool_write(unsigned int side, unsigned int handle,
                        unsigned int offset, const void *data,
                        const unsigned char *known, unsigned int bytes);
int full_osd_pool_read(unsigned int side, unsigned int handle,
                       unsigned int offset, void *data,
                       unsigned char *known, unsigned int bytes);
int full_osd_pool_mapping(unsigned int side, unsigned int handle,
                          struct full_osd_mapping *out);
/* A foreign PID receives only owner_pid, with initialized=0/faults=1.
 * Before first bind the snapshot is zero. There are no reset/mutation exports.
 */
void full_osd_pool_snapshot(struct full_osd_pool_snapshot *out);

#endif
