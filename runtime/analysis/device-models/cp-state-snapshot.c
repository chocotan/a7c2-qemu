/* SPDX-License-Identifier: MIT */
#include "cp-state-snapshot.h"
#include <errno.h>
#include <string.h>

static int range_ok(const void *p, size_t size) {
    return p && size <= UINTPTR_MAX - (uintptr_t)p;
}
static int overlap(const void *a, size_t an, const void *b, size_t bn) {
    return (uintptr_t)a < (uintptr_t)b + bn && (uintptr_t)b < (uintptr_t)a + an;
}
static uint16_t le16(const unsigned char *p) {
    return (uint16_t)(p[0] | (unsigned int)p[1] << 8);
}
static uint32_t le32(const unsigned char *p) {
    return p[0] | (uint32_t)p[1] << 8 | (uint32_t)p[2] << 16 | (uint32_t)p[3] << 24;
}
static int header_ok(const unsigned char *p, uint16_t opcode) {
    return p[0] == 6 && le16(p + 2) == opcode;
}
int cp_state_snapshot_copy(const struct cp_state_snapshot_input *input,
                           struct cp_state_snapshot *output) {
    const size_t a = CP_STATE_SNAPSHOT_APERTURE_OFFSET, l = CP_STATE_SNAPSHOT_LENS_OFFSET;
    /* Every mutable destination is checked before any input-mask read/write. */
    if (!range_ok(input, sizeof *input) || !range_ok(output, sizeof *output)) return -EINVAL;
    struct cp_state_snapshot_input v = *input;
    if (v.size != CP_STATE_SNAPSHOT_BYTES || v.known_size < v.size ||
        !range_ok(v.bytes, v.size) || !range_ok(v.known, v.known_size) ||
        overlap(output, sizeof *output, input, sizeof *input) ||
        overlap(output, sizeof *output, v.bytes, v.size) ||
        overlap(output, sizeof *output, v.known, v.known_size)) return -EINVAL;
    if (v.generation.provenance == CP_STATE_SNAPSHOT_UNPUBLISHED) return -ENOTSUP;
    if (v.generation.provenance != CP_STATE_SNAPSHOT_PUBLISHED_BYTES) return -EINVAL;
    if (v.generation.published_generation == v.generation.shadow_generation) return -ESTALE;
    for (size_t i = 0; i < v.size; i++) if (v.known[i] > 1) return -EINVAL;
    /* shortcut: unknown getter reads require full known backing; narrow this
     * only after all 76 getter/consumer schemas have source-backed coverage. */
    for (size_t i = 0; i < v.size; i++)
        if (i != 1 && i != a + 1 && i != l + 1 && !v.known[i]) return -ENODATA;
    if (!header_ok(v.bytes, 0x2040) || le32(v.bytes + 4) != 0 ||
        !header_ok(v.bytes + a, 0x201b) || !header_ok(v.bytes + l, 0x2044)) return -EPROTO;
    const unsigned char *lens = v.bytes + l;
    /* AP351fdb8's closed assert domains, with original wire values retained.
     * +d is deliberately raw: its unsupported branch is not a proven assert.
     * +88 is a bitfield; +14/+1c are u32 copies, not float/ratio consumers. */
    static const unsigned char boolean_offsets[] = {
        0xa, 0xb, 0xf, 0x10, 0x75, 0x78, 0x79, 0x7a, 0x7b,
        0x7e, 0x7f, 0x82, 0x83, 0x86, 0x87, 0x8e
    };
    static const unsigned char ternary_offsets[] = {9, 0xc, 0x77, 0x7c, 0x8a, 0x8b, 0x8c, 0x8d};
    if ((lens[8] != 0 && lens[8] != 1 && lens[8] != 4) || lens[0xe] > 3) return -ERANGE;
    for (size_t i = 0; i < sizeof boolean_offsets; i++)
        if (lens[boolean_offsets[i]] > 1) return -ERANGE;
    for (size_t i = 0; i < sizeof ternary_offsets; i++)
        if (lens[ternary_offsets[i]] > 2) return -ERANGE;

    memcpy(output->bytes, v.bytes, v.size);
    memcpy(output->known, v.known, v.size);
    output->generation = v.generation;
    for (size_t i = 0; i < 5; i++) output->aperture_words[i] = le16(v.bytes + a + 8 + 2*i);
    output->lens_wire_state = lens[8];
    output->lens_values[0] = le32(lens + 0x14);
    output->lens_values[1] = le32(lens + 0x1c);
    memcpy(output->lens_name, lens + 0x34, CP_STATE_SNAPSHOT_NAME_BYTES);
    output->lens_name[CP_STATE_SNAPSHOT_NAME_BYTES] = 0;
    return CP_STATE_SNAPSHOT_LAYOUT_COPIED;
}
