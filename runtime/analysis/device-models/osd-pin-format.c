/* SPDX-License-Identifier: MIT */
#include "osd-pin-format.h"
#include <limits.h>
#include <string.h>
#include <unistd.h>

_Static_assert(CHAR_BIT == 8 && sizeof(unsigned int) == 4, "Sony field widths");

static unsigned int u16(const unsigned char *p)
{
    return p[0] | (unsigned int)p[1] << 8;
}

static unsigned int u32(const unsigned char *p)
{
    return u16(p) | u16(p + 2) << 16;
}

static void put16(unsigned char *p, unsigned int value)
{
    p[0] = (unsigned char)value;
    p[1] = (unsigned char)(value >> 8);
}

static void put32(unsigned char *p, unsigned int value)
{
    for (unsigned int i = 0; i < 4; ++i)
        p[i] = (unsigned char)(value >> (8 * i));
}

static int all_known(const unsigned char *known, unsigned int bytes)
{
    for (unsigned int i = 0; i < bytes; ++i)
        if (known[i] != 1)
            return 0;
    return 1;
}

static unsigned int payload_size(unsigned int tag)
{
    if (tag == FULL_OSD_FORMAT_KEY0) return 64;
    if (tag == FULL_OSD_FORMAT_TAG100) return 128;
    if (tag == FULL_OSD_FORMAT_TAG101) return 16;
    if (tag == FULL_OSD_FORMAT_TAG102) return 32;
    return 0;
}

int full_osd_format_build_initial(unsigned int kind, unsigned char *data,
                                  unsigned char *known, unsigned int bytes,
                                  unsigned int *used)
{
    unsigned int size = payload_size(kind);
    if (!data || !known || !used || bytes != FULL_OSD_POOL_EXTENT || !size ||
        kind == FULL_OSD_FORMAT_TAG101)
        return FULL_OSD_FORMAT_REJECT;
    unsigned char packet[FULL_OSD_POOL_EXTENT], mask[FULL_OSD_POOL_EXTENT] = {0};
    memset(packet, FULL_OSD_POOL_UNKNOWN_BYTE, sizeof packet);
    memset(packet, 0, 64);
    memset(mask, 1, 64);
    put32(packet, 0x534f5353u);
    put32(packet + 4, kind == FULL_OSD_FORMAT_KEY0 ? 1u : 0x01000000u);
    put32(packet + 8, kind == FULL_OSD_FORMAT_KEY0 ? 3u : 0u);
    put32(packet + 12, 1);
    put32(packet + 16, 32);
    put32(packet + 32, 0x59525445u);
    put32(packet + 36, kind);
    put32(packet + 44, 64);
    put32(packet + 48, size);
    if (kind == FULL_OSD_FORMAT_KEY0) {
        memset(packet + 64, 0, size);
        memset(mask + 64, 1, size);
    } else if (kind == FULL_OSD_FORMAT_TAG100) {
        put32(packet + 64, 1);
        memset(mask + 64, 1, 4);
        put16(packet + 72, 0);
        memset(mask + 72, 1, 2);
        packet[76] = 0;
        mask[76] = 1;
    } else {
        put32(packet + 64, UINT_MAX);
        memset(mask + 64, 1, 4);
        put16(packet + 68, 0);
        memset(mask + 68, 1, 2);
        memset(packet + 72, 0xff, 20);
        memset(mask + 72, 1, 20);
    }
    memcpy(data, packet, sizeof packet);
    memcpy(known, mask, sizeof mask);
    *used = 64 + size;
    return 0;
}

int full_osd_format_parse(const unsigned char *data, const unsigned char *known,
                          unsigned int bytes, struct full_osd_format_view *out)
{
    if (!data || !known || !out || bytes < 64 || bytes > FULL_OSD_POOL_EXTENT)
        return FULL_OSD_FORMAT_REJECT;
    for (unsigned int i = 0; i < bytes; ++i)
        if (known[i] > 1) return FULL_OSD_FORMAT_REJECT;
    if (!all_known(known, 20) || u32(data) != 0x534f5353u ||
        u32(data + 12) != 1 || u32(data + 16) != 32)
        return FULL_OSD_FORMAT_REJECT;
    const unsigned char *entry = data + 32;
    if (!all_known(known + 32, 24) || u32(entry) != 0x59525445u ||
        u32(entry + 8) || u32(entry + 12) != 64 || u32(entry + 20))
        return FULL_OSD_FORMAT_REJECT;
    unsigned int tag = u32(entry + 4), size = payload_size(tag);
    if (!size || u32(entry + 16) != size || size > bytes - 64 ||
        u32(data + 4) != (tag == FULL_OSD_FORMAT_KEY0 ? 1u : 0x01000000u) ||
        u32(data + 8) != (tag == FULL_OSD_FORMAT_KEY0 ? 3u : 0u))
        return FULL_OSD_FORMAT_REJECT;
    struct full_osd_format_view result = {
        .tag = tag, .version = u32(data + 4), .header_flags = u32(data + 8),
        .payload_offset = 64, .payload_bytes = size
    };
    memcpy(result.payload, data + 64, size);
    memcpy(result.known, known + 64, size);
    *out = result;
    return 0;
}

static unsigned int sid(unsigned int side)
{
    return side == FULL_OSD_PINMEM_SIDE ? FULL_OSD_PINMEM_SID : FULL_OSD_PEER_SID;
}

static unsigned int opposite(unsigned int side)
{
    return side == FULL_OSD_PINMEM_SIDE ? FULL_OSD_PEER_SIDE : FULL_OSD_PINMEM_SIDE;
}

static int valid_side(unsigned int side)
{
    return side == FULL_OSD_PINMEM_SIDE || side == FULL_OSD_PEER_SIDE;
}

static int same_mapping(const struct full_osd_mapping *a, const struct full_osd_mapping *b)
{
    return a->handle == b->handle && a->unit == b->unit && a->extent == b->extent &&
        a->generation == b->generation && a->physical == b->physical && a->cp_alias == b->cp_alias;
}

static int shared_mapping(unsigned int producer_side, unsigned int handle,
                           struct full_osd_mapping *mapping)
{
    if (!valid_side(producer_side) || !mapping) return FULL_OSD_FORMAT_REJECT;
    struct full_osd_pool_snapshot pool;
    full_osd_pool_snapshot(&pool);
    if (!pool.initialized || pool.faults || pool.owner_pid != (unsigned int)getpid())
        return FULL_OSD_FORMAT_REJECT;
    for (unsigned int i = 0; i < FULL_OSD_POOL_SLOTS; ++i) {
        const struct full_osd_pool_slot_snapshot *slot = &pool.slots[i];
        if (slot->live && slot->handle == handle && slot->creator_side == producer_side &&
            slot->consumer_side == opposite(producer_side) && slot->creator_open == 1 &&
            slot->owners == 2 && slot->mapping.handle == handle &&
            slot->mapping.unit == FULL_OSD_POOL_UNIT && slot->mapping.extent == FULL_OSD_POOL_EXTENT) {
            *mapping = slot->mapping;
            return 0;
        }
    }
    return FULL_OSD_FORMAT_REJECT;
}

int full_osd_format_build_completion101(unsigned int peer_handle, unsigned char *data,
                                       unsigned char *known, unsigned int bytes,
                                       unsigned int *used)
{
    struct full_osd_mapping mapping;
    if (!data || !known || !used || bytes != FULL_OSD_POOL_EXTENT ||
        shared_mapping(FULL_OSD_PEER_SIDE, peer_handle, &mapping))
        return FULL_OSD_FORMAT_REJECT;
    unsigned char packet[FULL_OSD_POOL_EXTENT], mask[FULL_OSD_POOL_EXTENT];
    unsigned int initial_used;
    if (full_osd_format_build_initial(FULL_OSD_FORMAT_TAG102, packet, mask,
                                      sizeof packet, &initial_used))
        return FULL_OSD_FORMAT_REJECT;
    memset(packet + 64, FULL_OSD_POOL_UNKNOWN_BYTE, sizeof packet - 64);
    memset(mask + 64, 0, sizeof mask - 64);
    put32(packet + 36, FULL_OSD_FORMAT_TAG101);
    put32(packet + 48, 16);
    put32(packet + 64, 0);
    put32(packet + 68, peer_handle);
    put16(packet + 72, 0);
    put32(packet + 76, 0);
    memset(mask + 64, 1, 10);
    memset(mask + 76, 1, 4);
    memcpy(data, packet, sizeof packet);
    memcpy(known, mask, sizeof mask);
    *used = 80;
    return 0;
}

int full_osd_notice_build(unsigned int producer_side, unsigned int handle,
                          unsigned char *data, unsigned char *known, unsigned int bytes)
{
    struct full_osd_mapping mapping;
    if (!data || !known || bytes != FULL_OSD_NOTICE_BYTES ||
        shared_mapping(producer_side, handle, &mapping))
        return FULL_OSD_FORMAT_REJECT;
    unsigned char packet[FULL_OSD_NOTICE_BYTES] = {0}, mask[FULL_OSD_NOTICE_BYTES];
    memset(mask, 1, sizeof mask);
    put32(packet + 4, 0xa0a0a0a0u);
    put16(packet + 8, 1);
    put16(packet + 10, FULL_OSD_NOTICE_BYTES);
    put32(packet + 12, 24);
    put32(packet + 16, FULL_OSD_NOTICE_BYTES);
    memset(packet + 20, FULL_OSD_POOL_UNKNOWN_BYTE, 4);
    memset(mask + 20, 0, 4);
    put16(packet + 24, 0x1000);
    put16(packet + 26, 0x0102);
    put16(packet + 28, 0x38);
    put16(packet + 30, 1);
    put32(packet + 32, 1);
    put32(packet + 36, 3);
    put32(packet + 44, sid(opposite(producer_side)));
    put32(packet + 48, 1);
    put32(packet + 52, 3);
    put32(packet + 60, sid(producer_side));
    put32(packet + 64, mapping.unit);
    put32(packet + 68, mapping.handle);
    memcpy(data, packet, sizeof packet);
    memcpy(known, mask, sizeof mask);
    return 0;
}

int full_osd_notice_validate(unsigned int producer_side, unsigned int source_sid,
                             unsigned int destination_sid, const unsigned char *data,
                             unsigned int bytes, struct full_osd_mapping *mapping)
{
    if (!valid_side(producer_side) || !data || !mapping || bytes != FULL_OSD_NOTICE_BYTES ||
        source_sid != sid(producer_side) || destination_sid != sid(opposite(producer_side)) ||
        u32(data) || u32(data + 4) != 0xa0a0a0a0u || u16(data + 8) != 1 ||
        u16(data + 10) != bytes || u32(data + 12) != 24 || u32(data + 16) != bytes ||
        u16(data + 24) != 0x1000 || u16(data + 26) != 0x0102 ||
        u16(data + 28) != 0x38 || u16(data + 30) != 1 ||
        u32(data + 32) != 1 || u32(data + 36) != 3 || u32(data + 40) ||
        u32(data + 44) != destination_sid || u32(data + 48) != 1 ||
        u32(data + 52) != 3 || u32(data + 56) || u32(data + 60) != source_sid ||
        u32(data + 64) != FULL_OSD_POOL_UNIT || u32(data + 72) || u32(data + 76))
        return FULL_OSD_FORMAT_REJECT;
    return shared_mapping(producer_side, u32(data + 68), mapping);
}

static int read_view(unsigned int side, unsigned int handle,
                      const struct full_osd_mapping *expected, struct full_osd_format_view *view)
{
    struct full_osd_mapping mapping;
    unsigned char data[FULL_OSD_POOL_EXTENT], known[FULL_OSD_POOL_EXTENT];
    if (full_osd_pool_mapping(side, handle, &mapping) || !same_mapping(&mapping, expected) ||
        full_osd_pool_read(side, handle, 0, data, known, sizeof data))
        return FULL_OSD_FORMAT_REJECT;
    return full_osd_format_parse(data, known, sizeof data, view);
}

int full_osd_format_apply_inactive100(unsigned int handle,
                                     const unsigned char row_enabled[5],
                                     const unsigned char row_known[5])
{
    if (!row_enabled || !row_known || !all_known(row_known, 5))
        return FULL_OSD_FORMAT_REJECT;
    for (unsigned int i = 0; i < 5; ++i)
        if (row_enabled[i] != 0) return FULL_OSD_FORMAT_REJECT;
    struct full_osd_mapping mapping;
    struct full_osd_format_view view;
    if (shared_mapping(FULL_OSD_PINMEM_SIDE, handle, &mapping) ||
        read_view(FULL_OSD_PINMEM_SIDE, handle, &mapping, &view) ||
        view.tag != FULL_OSD_FORMAT_TAG100 || !all_known(view.known, 4) ||
        u32(view.payload) != 1)
        return FULL_OSD_FORMAT_REJECT;
    const unsigned char zero[4] = {0}, known[4] = {1, 1, 1, 1};
    return full_osd_pool_write(FULL_OSD_PINMEM_SIDE, handle, view.payload_offset,
                               zero, known, sizeof zero);
}

static void cache_plane(struct full_osd_format_plane *plane, unsigned int ordinal,
                         const struct full_osd_mapping *mapping, const struct full_osd_format_view *view)
{
    plane->mapping = *mapping;
    plane->handle = mapping->handle;
    plane->ordinal = ordinal;
    plane->tag = view->tag;
    plane->payload_bytes = view->payload_bytes;
    memcpy(plane->payload, view->payload, view->payload_bytes);
    memcpy(plane->known, view->known, view->payload_bytes);
    ++plane->reloads;
}

int full_osd_format_state_init(struct full_osd_format_state *state,
                               const unsigned int output_handles[FULL_OSD_FORMAT_PLANES])
{
    if (!state || !output_handles || state->initialized) return FULL_OSD_FORMAT_REJECT;
    struct full_osd_format_state result = {.owner_pid = (unsigned int)getpid(), .initialized = 1};
    struct full_osd_pool_snapshot pool;
    full_osd_pool_snapshot(&pool);
    if (!pool.initialized || pool.faults || pool.owner_pid != result.owner_pid)
        return FULL_OSD_FORMAT_REJECT;
    for (unsigned int i = 0; i < FULL_OSD_FORMAT_PLANES; ++i) {
        for (unsigned int j = 0; j < i; ++j)
            if (output_handles[j] == output_handles[i]) return FULL_OSD_FORMAT_REJECT;
        unsigned int creator_verified = 0;
        for (unsigned int j = 0; j < FULL_OSD_POOL_SLOTS; ++j)
            if (pool.slots[j].live && pool.slots[j].handle == output_handles[i] &&
                pool.slots[j].creator_side == FULL_OSD_PEER_SIDE && pool.slots[j].creator_open == 1)
                creator_verified = 1;
        struct full_osd_mapping mapping;
        struct full_osd_format_view view;
        if (!creator_verified || full_osd_pool_mapping(FULL_OSD_PEER_SIDE, output_handles[i], &mapping) ||
            mapping.unit != FULL_OSD_POOL_UNIT || mapping.extent != FULL_OSD_POOL_EXTENT ||
            read_view(FULL_OSD_PEER_SIDE, output_handles[i], &mapping, &view) ||
            view.tag != FULL_OSD_FORMAT_KEY0 || !all_known(view.known, view.payload_bytes))
            return FULL_OSD_FORMAT_REJECT;
        for (unsigned int j = 0; j < view.payload_bytes; ++j)
            if (view.payload[j]) return FULL_OSD_FORMAT_REJECT;
        cache_plane(&result.outputs[i], i, &mapping, &view);
        /* 469c1e..469c2e stores the original initial output selection mask 0. */
        result.outputs[i].selection_mask = 0;
        result.outputs[i].selection_mask_known = 1;
    }
    *state = result;
    return 0;
}

static int data_fault(struct full_osd_format_state *state, int unsupported)
{
    ++state->faults;
    state->last_handler_status = UINT_MAX;
    state->unsupported_work = (unsigned int)unsupported;
    return FULL_OSD_FORMAT_REJECT;
}

static int consume_notice(struct full_osd_format_state *state,
                           unsigned int source_sid, unsigned int destination_sid,
                           const unsigned char *notice, unsigned int bytes,
                           const struct full_osd_mapping *opened_mapping)
{
    struct full_osd_mapping mapping;
    if (!state || state->initialized != 1 || state->owner_pid != (unsigned int)getpid() ||
        state->faults || state->notices == UINT_MAX ||
        full_osd_notice_validate(FULL_OSD_PINMEM_SIDE, source_sid, destination_sid,
                                 notice, bytes, &mapping))
        return FULL_OSD_FORMAT_REJECT;
    struct full_osd_format_plane *plane = NULL;
    unsigned int ordinal = 0;
    for (unsigned int i = 0; i < FULL_OSD_FORMAT_PLANES; ++i) {
        if (state->incoming101[i].handle == mapping.handle ||
            state->incoming102[i].handle == mapping.handle)
            return FULL_OSD_FORMAT_REJECT;
        if (state->incoming100[i].handle == mapping.handle) {
            plane = &state->incoming100[i];
            ordinal = i;
        }
    }
    if (plane) {
        if (opened_mapping || !same_mapping(&plane->mapping, &mapping) || plane->reloads == UINT_MAX)
            return FULL_OSD_FORMAT_REJECT;
    } else {
        if (state->retained_opens >= FULL_OSD_POOL_SLOTS)
            return FULL_OSD_FORMAT_REJECT;
        if (opened_mapping) {
            struct full_osd_mapping actual;
            if (!same_mapping(opened_mapping, &mapping) ||
                full_osd_pool_mapping(FULL_OSD_PEER_SIDE, mapping.handle, &actual) ||
                !same_mapping(&actual, opened_mapping))
                return FULL_OSD_FORMAT_REJECT;
        } else if (full_osd_pool_open(FULL_OSD_PEER_SIDE, mapping.handle)) {
            return FULL_OSD_FORMAT_REJECT;
        }
        state->held[state->retained_opens++] = mapping;
        ++state->opens;
    }
    struct full_osd_format_view view;
    if (read_view(FULL_OSD_PEER_SIDE, mapping.handle, &mapping, &view))
        return data_fault(state, 0);
    if (plane && view.tag != FULL_OSD_FORMAT_TAG100) return data_fault(state, 1);
    if (!plane) {
        struct full_osd_format_plane *bank;
        if (view.tag == FULL_OSD_FORMAT_TAG100) bank = state->incoming100;
        else if (view.tag == FULL_OSD_FORMAT_TAG101) bank = state->incoming101;
        else if (view.tag == FULL_OSD_FORMAT_TAG102) bank = state->incoming102;
        else return data_fault(state, 1);
        for (ordinal = 0; ordinal < FULL_OSD_FORMAT_PLANES; ++ordinal)
            if (!bank[ordinal].handle) break;
        if (ordinal == FULL_OSD_FORMAT_PLANES) return data_fault(state, 0);
        plane = &bank[ordinal];
    }
    if (view.tag == FULL_OSD_FORMAT_TAG100) {
        if (!all_known(view.known, 4) || !all_known(view.known + 8, 2))
            return data_fault(state, 0);
        if (u16(view.payload + 8)) return data_fault(state, 1);
        /* Existing count-zero is the original diagnostic 13 branch, not work. */
        unsigned int existing = plane->handle != 0;
        if (u32(view.payload) > 1) return data_fault(state, 1);
        cache_plane(plane, ordinal, &mapping, &view);
        if (existing) ++state->reload100;
        else ++state->new100;
        state->last_handler_status = existing && !u32(view.payload) ? 13u : 0u;
    } else if (view.tag == FULL_OSD_FORMAT_TAG101) {
        if (!all_known(view.known, 10) || !all_known(view.known + 12, 4))
            return data_fault(state, 0);
        if (u32(view.payload) || u16(view.payload + 8) || u32(view.payload + 12))
            return data_fault(state, 1);
        unsigned int output_matches = 0;
        for (unsigned int i = 0; i < FULL_OSD_FORMAT_PLANES; ++i) {
            if (state->outputs[i].handle == u32(view.payload + 4)) ++output_matches;
            if (state->incoming101[i].handle &&
                u32(state->incoming101[i].payload + 4) == u32(view.payload + 4))
                return data_fault(state, 0);
        }
        if (output_matches != 1) return data_fault(state, 0);
        /* 46b17a -> 46b194: initial mask zero skips all plane callbacks. */
        cache_plane(plane, ordinal, &mapping, &view);
        ++state->new101;
        state->last_handler_status = 0;
    } else {
        if (!all_known(view.known + 4, 2)) return data_fault(state, 0);
        if (u16(view.payload + 4)) return data_fault(state, 1);
        cache_plane(plane, ordinal, &mapping, &view);
        ++state->new102;
        state->last_handler_status = 0;
    }
    ++state->notices;
    state->last_outer_status = 0;
    /* ae9ec8 requires four tag101 plus four tag102, not the tag100 bank. */
    unsigned int was_ready = state->ready;
    state->ready = 1;
    for (unsigned int i = 0; i < FULL_OSD_FORMAT_PLANES; ++i)
        if (!state->incoming101[i].handle || !state->incoming102[i].handle) state->ready = 0;
    if (state->ready && !was_ready) {
        ++state->readiness_transitions;
        state->readiness_post_pending = 1;
    }
    return 0;
}

int full_osd_format_consume_notice(struct full_osd_format_state *state,
                                  unsigned int source_sid, unsigned int destination_sid,
                                  const unsigned char *notice, unsigned int bytes)
{
    return consume_notice(state, source_sid, destination_sid, notice, bytes, NULL);
}

int full_osd_format_consume_opened_notice(struct full_osd_format_state *state,
                                         unsigned int source_sid, unsigned int destination_sid,
                                         const unsigned char *notice, unsigned int bytes,
                                         const struct full_osd_mapping *opened_mapping)
{
    if (!opened_mapping) return FULL_OSD_FORMAT_REJECT;
    return consume_notice(state, source_sid, destination_sid, notice, bytes, opened_mapping);
}

void full_osd_format_snapshot(const struct full_osd_format_state *state,
                              struct full_osd_format_state *out)
{
    if (!out) return;
    if (!state || state->owner_pid != (unsigned int)getpid()) {
        memset(out, 0, sizeof *out);
        return;
    }
    *out = *state;
}
