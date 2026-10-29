/* SPDX-License-Identifier: MIT */
#include "cp-full-state-snapshot.h"
#include <errno.h>
#include <string.h>

/* CP D93660's 76 rows; successful getter lengths, not incremental 10fa3e4. */
const struct cp_full_state_snapshot_block
cp_full_state_snapshot_blocks[CP_FULL_STATE_SNAPSHOT_BLOCKS] = {
    {0x2000, 0x008, 0x0c}, {0x2001, 0x014, 0x0c},
    {0x2002, 0x020, 0x0c}, {0x2003, 0x02c, 0x34},
    {0x2004, 0x060, 0x84}, {0x2005, 0x0e4, 0x0c},
    {0x2006, 0x0f0, 0x0c}, {0x2008, 0x0fc, 0x10},
    {0x2009, 0x10c, 0x0c}, {0x200d, 0x118, 0x0c},
    {0x200e, 0x124, 0x28}, {0x2012, 0x14c, 0x0c},
    {0x2013, 0x158, 0x20}, {0x2014, 0x178, 0x10},
    {0x2016, 0x188, 0x0c}, {0x2017, 0x194, 0x0c},
    {0x2018, 0x1a0, 0x0c}, {0x2019, 0x1ac, 0x0c},
    {0x201a, 0x1b8, 0x0c}, {0x201b, 0x1c4, 0x14},
    {0x201d, 0x1d8, 0x10}, {0x201e, 0x1e8, 0x30},
    {0x2020, 0x218, 0x0c}, {0x2022, 0x224, 0x0c},
    {0x202d, 0x230, 0x10}, {0x202f, 0x240, 0x18},
    {0x2030, 0x258, 0x0c}, {0x2031, 0x264, 0x0c},
    {0x2032, 0x270, 0x0c}, {0x2036, 0x27c, 0x0c},
    {0x2041, 0x288, 0x14}, {0x2043, 0x29c, 0x0c},
    {0x2044, 0x2a8, 0xa0}, {0x2045, 0x348, 0x0c},
    {0x204a, 0x354, 0x0c}, {0x204c, 0x360, 0x0c},
    {0x204f, 0x36c, 0x0c}, {0x2050, 0x378, 0x0c},
    {0x2053, 0x384, 0x14}, {0x2054, 0x398, 0x0c},
    {0x2057, 0x3a4, 0x0c}, {0x2058, 0x3b0, 0x0c},
    {0x2059, 0x3bc, 0x1c}, {0x205a, 0x3d8, 0x40},
    {0x205c, 0x418, 0x0c}, {0x205d, 0x424, 0x0c},
    {0x205e, 0x430, 0x0c}, {0x2061, 0x43c, 0x0c},
    {0x2062, 0x448, 0x0c}, {0x2065, 0x454, 0x0c},
    {0x2066, 0x460, 0x0c}, {0x2067, 0x46c, 0x24},
    {0x2068, 0x490, 0x0c}, {0x2069, 0x49c, 0x0c},
    {0x206a, 0x4a8, 0x0c}, {0x206b, 0x4b4, 0x0c},
    {0x206c, 0x4c0, 0x0c}, {0x206d, 0x4cc, 0x0c},
    {0x206e, 0x4d8, 0x0c}, {0x206f, 0x4e4, 0x0c},
    {0x2070, 0x4f0, 0x0c}, {0x2071, 0x4fc, 0x0c},
    {0x209e, 0x508, 0x0c}, {0x209f, 0x514, 0x84},
    {0x20a0, 0x598, 0x9c}, {0x20a1, 0x634, 0x0c},
    {0x20a2, 0x640, 0x0c}, {0x20a4, 0x64c, 0x0c},
    {0x20a5, 0x658, 0x0c}, {0x20a6, 0x664, 0x10},
    {0x20a8, 0x674, 0x0c}, {0x20ac, 0x680, 0x10},
    {0x20ad, 0x690, 0x0c}, {0x20af, 0x69c, 0x1c},
    {0x20b0, 0x6b8, 0x0c}, {0x20b1, 0x6c4, 0x10}
};

static int range_ok(const void *p, size_t size) {
    return p && size <= UINTPTR_MAX - (uintptr_t)p;
}
static int overlap(const void *a, size_t an, const void *b, size_t bn) {
    return (uintptr_t)a < (uintptr_t)b + bn && (uintptr_t)b < (uintptr_t)a + an;
}
static int header_ok(const unsigned char *p, uint16_t command) {
    return p[0] == 6 && p[2] == (unsigned char)command &&
        p[3] == (unsigned char)(command >> 8) &&
        p[4] == 0 && p[5] == 0 && p[6] == 0 && p[7] == 0;
}
static int spans_ok(const struct cp_state_snapshot_input *v, size_t size,
                    const struct cp_state_snapshot *output) {
    return v->size == size && v->known_size >= size &&
        range_ok(v->bytes, v->size) && range_ok(v->known, v->known_size) &&
        !overlap(output, sizeof *output, v->bytes, v->size) &&
        !overlap(output, sizeof *output, v->known, v->known_size);
}
int cp_full_state_snapshot_copy(const struct cp_state_snapshot_input *input,
                                struct cp_state_snapshot *output) {
    if (!range_ok(input, sizeof *input) || !range_ok(output, sizeof *output) ||
        overlap(output, sizeof *output, input, sizeof *input)) return -EINVAL;
    struct cp_state_snapshot_input v = *input;
    if (!spans_ok(&v, CP_STATE_SNAPSHOT_BYTES, output)) return -EINVAL;
    if (!header_ok(v.bytes, 0x2040)) return -EPROTO;
    for (size_t i = 0; i < CP_FULL_STATE_SNAPSHOT_BLOCKS; i++)
        if (!header_ok(v.bytes + cp_full_state_snapshot_blocks[i].offset,
                       cp_full_state_snapshot_blocks[i].command)) return -EPROTO;
    return cp_state_snapshot_copy(input, output);
}
int cp_full_state_snapshot_assemble(const struct cp_state_snapshot_input *fragments,
                                    size_t count,
                                    const struct cp_state_snapshot_generation *generation,
                                    struct cp_state_snapshot *output) {
    if (count != CP_FULL_STATE_SNAPSHOT_BLOCKS ||
        !range_ok(fragments, count * sizeof *fragments) ||
        !range_ok(generation, sizeof *generation) || !range_ok(output, sizeof *output) ||
        overlap(output, sizeof *output, fragments, count * sizeof *fragments) ||
        overlap(output, sizeof *output, generation, sizeof *generation)) return -EINVAL;
    const struct cp_state_snapshot_generation g = *generation;
    for (size_t i = 0; i < count; i++) {
        const struct cp_state_snapshot_input v = fragments[i];
        if (!spans_ok(&v, cp_full_state_snapshot_blocks[i].bytes, output)) return -EINVAL;
        if (v.generation.provenance != g.provenance ||
            v.generation.mutable_generation != g.mutable_generation ||
            v.generation.published_generation != g.published_generation ||
            v.generation.shadow_generation != g.shadow_generation) return -ESTALE;
        if (!header_ok(v.bytes, cp_full_state_snapshot_blocks[i].command)) return -EPROTO;
    }
    unsigned char bytes[CP_STATE_SNAPSHOT_BYTES], known[CP_STATE_SNAPSHOT_BYTES];
    const unsigned char outer[8] = {6, 0, 0x40, 0x20, 0, 0, 0, 0};
    memcpy(bytes, outer, sizeof outer);
    memset(known, 1, sizeof outer);
    known[1] = 0; /* Explicit VIRTUAL reserved zero; source byte is unknown. */
    for (size_t i = 0; i < count; i++) {
        const struct cp_full_state_snapshot_block b = cp_full_state_snapshot_blocks[i];
        memcpy(bytes + b.offset, fragments[i].bytes, b.bytes);
        memcpy(known + b.offset, fragments[i].known, b.bytes);
    }
    const struct cp_state_snapshot_input full = {bytes, known, sizeof bytes, sizeof known, g};
    return cp_full_state_snapshot_copy(&full, output);
}
