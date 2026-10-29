/* SPDX-License-Identifier: MIT */
#include "osd-buffer-owner.h"
#include <limits.h>
#include <pthread.h>
#include <stdatomic.h>
#include <stdint.h>
#include <string.h>
#include <unistd.h>

_Static_assert(sizeof(unsigned int) == 4, "OSD handles require 32-bit unsigned int");
_Static_assert(sizeof(unsigned long long) == 8, "OSD mappings require 64-bit addresses");
#define HANDLE_PREFIX 0xe1000000u
#define MAX_GENERATION 0x000fffffu

static pthread_mutex_t mutex = PTHREAD_MUTEX_INITIALIZER;
static _Atomic unsigned int owner_pid;
static volatile unsigned char *backing;
static unsigned long long physical_base;
static unsigned int cp_base;
static unsigned char known_bytes[FULL_OSD_POOL_SLOTS][FULL_OSD_POOL_EXTENT];
static struct full_osd_pool_snapshot state;

static int valid_side(unsigned int side)
{
    return side == FULL_OSD_PINMEM_SIDE || side == FULL_OSD_PEER_SIDE;
}

static int this_process(void)
{
    unsigned int owner = atomic_load(&owner_pid);
    return owner != 0 && owner == (unsigned int)getpid();
}

static int overlaps(unsigned long long base, unsigned long long last,
                    unsigned long long reserved, unsigned int bytes)
{
    return base <= reserved + bytes - 1u && reserved <= last;
}

static int valid_binding(void *memory, unsigned int bytes,
                         unsigned long long physical, unsigned int cp_alias)
{
    if (!memory || bytes != FULL_OSD_POOL_BYTES ||
        (uintptr_t)memory > UINTPTR_MAX - (FULL_OSD_POOL_BYTES - 1u) ||
        physical % FULL_OSD_POOL_EXTENT || cp_alias % FULL_OSD_POOL_EXTENT ||
        physical > ULLONG_MAX - (FULL_OSD_POOL_BYTES - 1u) ||
        cp_alias > UINT_MAX - (FULL_OSD_POOL_BYTES - 1u))
        return 0;
    unsigned long long last = physical + FULL_OSD_POOL_BYTES - 1u;
    unsigned long long cp_last = (unsigned long long)cp_alias + FULL_OSD_POOL_BYTES - 1u;
    /* Existing reserved namespaces are exclusions, not calls into those pools. */
    return !overlaps(physical, last, 0x500000000ULL, 0x2000u) &&
        !overlaps(physical, last, 0x41d000000ULL, 0x20000u) &&
        !overlaps(physical, last, 0x81d000000ULL, 0x20000u) &&
        !overlaps(cp_alias, cp_last, 0x80000000ULL, 0x2000u) &&
        !overlaps(cp_alias, cp_last, 0x1d000000ULL, 0x20000u);
}

static int slot_for(unsigned int handle)
{
    unsigned int index = handle & 0xfu;
    if (!state.initialized || state.faults ||
        (handle & 0xff000000u) != HANDLE_PREFIX || index >= FULL_OSD_POOL_SLOTS ||
        !state.slots[index].live || state.slots[index].handle != handle)
        return -1;
    return (int)index;
}

static int open_for(const struct full_osd_pool_slot_snapshot *slot, unsigned int side)
{
    return valid_side(side) &&
        ((side == slot->creator_side && slot->creator_open) ||
         (side == slot->consumer_side && slot->consumer_open));
}

static void describe(unsigned int index, struct full_osd_mapping *out)
{
    unsigned int offset = index * FULL_OSD_POOL_EXTENT;
    memset(out, 0, sizeof *out);
    out->handle = state.slots[index].handle;
    out->unit = FULL_OSD_POOL_UNIT;
    out->extent = FULL_OSD_POOL_EXTENT;
    out->generation = state.slots[index].generation;
    out->physical = physical_base + offset;
    out->cp_alias = cp_base + offset;
}

int full_osd_pool_bind(void *memory, unsigned int bytes,
                       unsigned long long physical, unsigned int cp_alias)
{
    if (!valid_binding(memory, bytes, physical, cp_alias))
        return FULL_OSD_POOL_REJECT;
    unsigned int expected = 0, pid = (unsigned int)getpid();
    atomic_compare_exchange_strong(&owner_pid, &expected, pid);
    if (!this_process())
        return FULL_OSD_POOL_REJECT;
    pthread_mutex_lock(&mutex);
    if (state.live || state.faults) {
        pthread_mutex_unlock(&mutex);
        return FULL_OSD_POOL_REJECT;
    }
    backing = memory;
    physical_base = physical;
    cp_base = cp_alias;
    for (unsigned int i = 0; i < FULL_OSD_POOL_BYTES; ++i)
        backing[i] = FULL_OSD_POOL_UNKNOWN_BYTE;
    memset(known_bytes, 0, sizeof known_bytes);
    for (unsigned int i = 0; i < FULL_OSD_POOL_SLOTS; ++i)
        state.slots[i].known_bytes = 0;
    state.initialized = 1;
    state.owner_pid = pid;
    pthread_mutex_unlock(&mutex);
    return 0;
}

int full_osd_pool_allocate(unsigned int creator_side, unsigned int *handle)
{
    if (!handle || !valid_side(creator_side) || !this_process())
        return FULL_OSD_POOL_REJECT;
    pthread_mutex_lock(&mutex);
    if (state.initialized && !state.faults) {
        for (unsigned int i = 0; i < FULL_OSD_POOL_SLOTS; ++i) {
            struct full_osd_pool_slot_snapshot *slot = &state.slots[i];
            if (slot->live || slot->generation == MAX_GENERATION)
                continue;
            unsigned int generation = slot->generation + 1u;
            memset(slot, 0, sizeof *slot);
            slot->handle = HANDLE_PREFIX | (generation << 4) | i;
            slot->generation = generation;
            slot->creator_side = creator_side;
            slot->live = slot->owners = slot->open_count = slot->creator_open = 1;
            memset(known_bytes[i], 0, sizeof known_bytes[i]);
            for (unsigned int j = 0; j < FULL_OSD_POOL_EXTENT; ++j)
                backing[i * FULL_OSD_POOL_EXTENT + j] = FULL_OSD_POOL_UNKNOWN_BYTE;
            ++state.live;
            ++state.allocations;
            *handle = slot->handle;
            pthread_mutex_unlock(&mutex);
            return 0;
        }
    }
    pthread_mutex_unlock(&mutex);
    return FULL_OSD_POOL_REJECT;
}

int full_osd_pool_share(unsigned int creator_side, unsigned int handle)
{
    if (!valid_side(creator_side) || !this_process())
        return FULL_OSD_POOL_REJECT;
    pthread_mutex_lock(&mutex);
    int index = slot_for(handle);
    if (index < 0 || state.slots[index].creator_side != creator_side ||
        !state.slots[index].creator_open || state.slots[index].consumer_side) {
        pthread_mutex_unlock(&mutex);
        return FULL_OSD_POOL_REJECT;
    }
    struct full_osd_pool_slot_snapshot *slot = &state.slots[index];
    slot->consumer_side = creator_side == FULL_OSD_PINMEM_SIDE ?
        FULL_OSD_PEER_SIDE : FULL_OSD_PINMEM_SIDE;
    ++slot->owners;
    ++state.shares;
    pthread_mutex_unlock(&mutex);
    return 0;
}

int full_osd_pool_open(unsigned int consumer_side, unsigned int handle)
{
    if (!valid_side(consumer_side) || !this_process())
        return FULL_OSD_POOL_REJECT;
    pthread_mutex_lock(&mutex);
    int index = slot_for(handle);
    if (index < 0 || state.slots[index].consumer_side != consumer_side ||
        state.slots[index].consumer_open ||
        state.slots[index].owners <= state.slots[index].creator_open) {
        pthread_mutex_unlock(&mutex);
        return FULL_OSD_POOL_REJECT;
    }
    state.slots[index].consumer_open = 1;
    ++state.slots[index].open_count;
    ++state.opens;
    pthread_mutex_unlock(&mutex);
    return 0;
}

int full_osd_pool_release(unsigned int side, unsigned int handle)
{
    if (!valid_side(side) || !this_process())
        return FULL_OSD_POOL_REJECT;
    pthread_mutex_lock(&mutex);
    int index = slot_for(handle);
    if (index < 0 || !open_for(&state.slots[index], side)) {
        pthread_mutex_unlock(&mutex);
        return FULL_OSD_POOL_REJECT;
    }
    struct full_osd_pool_slot_snapshot *slot = &state.slots[index];
    if (slot->creator_side == side)
        slot->creator_open = 0;
    else
        slot->consumer_open = 0;
    --slot->owners;
    --slot->open_count;
    ++state.releases;
    if (!slot->owners) {
        slot->live = 0;
        --state.live;
    }
    pthread_mutex_unlock(&mutex);
    return 0;
}

static int valid_span(unsigned int offset, unsigned int bytes)
{
    return bytes && offset < FULL_OSD_POOL_EXTENT && bytes <= FULL_OSD_POOL_EXTENT - offset;
}

int full_osd_pool_write(unsigned int side, unsigned int handle,
                        unsigned int offset, const void *data,
                        const unsigned char *known, unsigned int bytes)
{
    if (!data || !known || !valid_span(offset, bytes) || !valid_side(side) || !this_process())
        return FULL_OSD_POOL_REJECT;
    pthread_mutex_lock(&mutex);
    int index = slot_for(handle);
    if (index < 0 || !open_for(&state.slots[index], side)) {
        pthread_mutex_unlock(&mutex);
        return FULL_OSD_POOL_REJECT;
    }
    for (unsigned int i = 0; i < bytes; ++i) {
        if (known[i] > 1) {
            pthread_mutex_unlock(&mutex);
            return FULL_OSD_POOL_REJECT;
        }
    }
    const unsigned char *source = data;
    struct full_osd_pool_slot_snapshot *slot = &state.slots[index];
    for (unsigned int i = 0; i < bytes; ++i) {
        unsigned int at = offset + i;
        backing[(unsigned int)index * FULL_OSD_POOL_EXTENT + at] = source[i];
        slot->known_bytes -= known_bytes[index][at];
        known_bytes[index][at] = known[i];
        slot->known_bytes += known[i];
    }
    ++state.writes;
    pthread_mutex_unlock(&mutex);
    return 0;
}

int full_osd_pool_read(unsigned int side, unsigned int handle,
                       unsigned int offset, void *data,
                       unsigned char *known, unsigned int bytes)
{
    if (!data || !known || !valid_span(offset, bytes) || !valid_side(side) || !this_process())
        return FULL_OSD_POOL_REJECT;
    pthread_mutex_lock(&mutex);
    int index = slot_for(handle);
    if (index < 0 || !open_for(&state.slots[index], side)) {
        pthread_mutex_unlock(&mutex);
        return FULL_OSD_POOL_REJECT;
    }
    unsigned char *destination = data;
    for (unsigned int i = 0; i < bytes; ++i) {
        destination[i] = backing[(unsigned int)index * FULL_OSD_POOL_EXTENT + offset + i];
        known[i] = known_bytes[index][offset + i];
    }
    ++state.reads;
    pthread_mutex_unlock(&mutex);
    return 0;
}

int full_osd_pool_mapping(unsigned int side, unsigned int handle, struct full_osd_mapping *out)
{
    if (!out || !valid_side(side) || !this_process())
        return FULL_OSD_POOL_REJECT;
    pthread_mutex_lock(&mutex);
    int index = slot_for(handle);
    if (index < 0 || !open_for(&state.slots[index], side)) {
        pthread_mutex_unlock(&mutex);
        return FULL_OSD_POOL_REJECT;
    }
    describe((unsigned int)index, out);
    pthread_mutex_unlock(&mutex);
    return 0;
}

void full_osd_pool_snapshot(struct full_osd_pool_snapshot *out)
{
    if (!out)
        return;
    unsigned int owner = atomic_load(&owner_pid);
    if (!owner || owner != (unsigned int)getpid()) {
        memset(out, 0, sizeof *out);
        out->owner_pid = owner;
        out->faults = owner != 0;
        return;
    }
    pthread_mutex_lock(&mutex);
    *out = state;
    for (unsigned int i = 0; i < FULL_OSD_POOL_SLOTS; ++i)
        describe(i, &out->slots[i].mapping);
    pthread_mutex_unlock(&mutex);
}
