/* SPDX-License-Identifier: MIT */
#include "cp-state-snapshot.h"
#include <assert.h>
#include <errno.h>
#include <stdio.h>
#include <string.h>

struct fixture {
    unsigned char bytes[CP_STATE_SNAPSHOT_BYTES];
    unsigned char known[CP_STATE_SNAPSHOT_BYTES + 9];
    struct cp_state_snapshot_input input;
};
static void put16(unsigned char *p, unsigned int value) {
    p[0] = (unsigned char)value; p[1] = (unsigned char)(value >> 8);
}
static void put32(unsigned char *p, uint32_t value) {
    for (size_t i = 0; i < 4; i++) p[i] = (unsigned char)(value >> (8*i));
}
static void header(unsigned char *p, unsigned int opcode) {
    p[0] = 6; put16(p + 2, opcode); put32(p + 4, 0);
}
static void fixture(struct fixture *f) {
    const size_t a = CP_STATE_SNAPSHOT_APERTURE_OFFSET, l = CP_STATE_SNAPSHOT_LENS_OFFSET;
    /* Explicit HOST virtual raw fixture only: every byte is supplied. This
     * patterned opaque payload is NOT a valid runtime 76-getter snapshot. */
    for (size_t i = 0; i < sizeof f->bytes; i++) f->bytes[i] = (unsigned char)(37*i + 19);
    memset(f->known, 1, sizeof f->known);
    memset(f->known + sizeof f->bytes, 0xee, 9); /* capacity tail is not logical mask */
    header(f->bytes, 0x2040); header(f->bytes + a, 0x201b); header(f->bytes + l, 0x2044);
    for (size_t i = 8; i < 0x14; i++) f->bytes[l + i] = 0;
    for (size_t i = 0x75; i <= 0x8e; i++) f->bytes[l + i] = 0;
    f->bytes[l + 8] = 1;
    const unsigned int values[5] = {400, 0, 0xffff, 0x8000, 0x201b};
    for (size_t i = 0; i < 5; i++) put16(f->bytes + a + 8 + 2*i, values[i]);
    put32(f->bytes + l + 0x14, 240); put32(f->bytes + l + 0x1c, 700);
    memset(f->bytes + l + 0x34, 'V', CP_STATE_SNAPSHOT_NAME_BYTES);
    f->input = (struct cp_state_snapshot_input){
        f->bytes, f->known, sizeof f->bytes, sizeof f->known,
        {CP_STATE_SNAPSHOT_PUBLISHED_BYTES, 9, 7, 6}
    };
}
static void reject(const struct cp_state_snapshot_input *input,
                   struct cp_state_snapshot *out, int error) {
    unsigned char before[sizeof *out];
    memcpy(before, out, sizeof before);
    assert(cp_state_snapshot_copy(input, out) == error);
    assert(memcmp(before, out, sizeof before) == 0);
}
int main(void) {
    struct fixture f;
    struct cp_state_snapshot out;
    const size_t a = CP_STATE_SNAPSHOT_APERTURE_OFFSET, l = CP_STATE_SNAPSHOT_LENS_OFFSET;
    fixture(&f); memset(&out, 0xa5, sizeof out);
    assert(cp_state_snapshot_copy(&f.input, &out) == CP_STATE_SNAPSHOT_LAYOUT_COPIED);
    assert(memcmp(out.bytes, f.bytes, sizeof f.bytes) == 0);
    assert(memcmp(out.known, f.known, sizeof out.known) == 0);
    assert(out.generation.mutable_generation == 9 && out.generation.published_generation == 7);
    assert(out.generation.shadow_generation == 6 && out.lens_wire_state == 1);
    assert(out.aperture_words[0] == 400 && out.aperture_words[1] == 0);
    assert(out.aperture_words[2] == UINT16_MAX && out.aperture_words[3] == 0x8000);
    assert(out.aperture_words[4] == 0x201b && out.lens_values[0] == 240 && out.lens_values[1] == 700);
    assert(out.lens_name[0] == 'V' && out.lens_name[0x40] == 'V' && out.lens_name[0x41] == 0);
    memset(f.bytes, 0xa7, sizeof f.bytes); memset(f.known, 0, sizeof f.known);
    assert(out.bytes[l + 8] == 1 && out.known[l + 8] == 1 && out.lens_name[0] == 'V');
    assert(out.generation.published_generation == 7 && out.generation.shadow_generation == 6);

    /* Exhaust the raw wire domain, not invented attached/ready booleans. */
    for (unsigned int value = 0; value < 256; value++) {
        fixture(&f); f.bytes[l + 8] = (unsigned char)value;
        if (value == 0 || value == 1 || value == 4) {
            assert(cp_state_snapshot_copy(&f.input, &out) == 0);
            assert(out.lens_wire_state == value);
        } else reject(&f.input, &out, -ERANGE);
    }
    fixture(&f); f.input.generation.published_generation = 0;
    f.input.generation.shadow_generation = UINT32_MAX;
    assert(cp_state_snapshot_copy(&f.input, &out) == 0); /* wrapped generation is fresh */
    f.input.generation.shadow_generation = 0; reject(&f.input, &out, -ESTALE);
    f.input.generation.provenance = CP_STATE_SNAPSHOT_UNPUBLISHED;
    reject(&f.input, &out, -ENOTSUP);
    f.input.generation.provenance = (enum cp_state_snapshot_provenance)42;
    reject(&f.input, &out, -EINVAL);
    fixture(&f);
    /* Every required byte, including fields outside lens/aperture, is gated. */
    for (size_t i = 0; i < sizeof f.bytes; i++) {
        f.known[i] = 0;
        if (i == 1 || i == a + 1 || i == l + 1) {
            assert(cp_state_snapshot_copy(&f.input, &out) == 0);
            assert(out.bytes[i] == f.bytes[i] && out.known[i] == 0);
        } else reject(&f.input, &out, -ENODATA);
        f.known[i] = 1;
    }
    f.known[l + 1] = 2; reject(&f.input, &out, -EINVAL);
    fixture(&f); f.input.size--; reject(&f.input, &out, -EINVAL);
    f.input.size += 2; reject(&f.input, &out, -EINVAL);
    fixture(&f); f.input.known_size = f.input.size - 1; reject(&f.input, &out, -EINVAL);
    fixture(&f); f.input.bytes = NULL; reject(&f.input, &out, -EINVAL);
    fixture(&f); f.input.known = NULL; reject(&f.input, &out, -EINVAL);
    fixture(&f); f.input.bytes = (const unsigned char *)(UINTPTR_MAX - 3);
    reject(&f.input, &out, -EINVAL);
    fixture(&f); f.input.known_size = SIZE_MAX; reject(&f.input, &out, -EINVAL);
    reject(NULL, &out, -EINVAL);
    assert(cp_state_snapshot_copy(&f.input, NULL) == -EINVAL);

    const size_t heads[] = {0, a, l};
    for (size_t i = 0; i < 3; i++) {
        fixture(&f); f.bytes[heads[i]] = 5; reject(&f.input, &out, -EPROTO);
        fixture(&f); f.bytes[heads[i] + 2] ^= 1; reject(&f.input, &out, -EPROTO);
        fixture(&f); f.bytes[heads[i] + 3] ^= 0x80; reject(&f.input, &out, -EPROTO);
    }
    fixture(&f); put32(f.bytes + 4, 7); reject(&f.input, &out, -EPROTO);
    fixture(&f); f.bytes[l + 0xa] = 2; reject(&f.input, &out, -ERANGE);
    fixture(&f); f.bytes[l + 9] = 3; reject(&f.input, &out, -ERANGE);
    fixture(&f); f.bytes[l + 0xe] = 4; reject(&f.input, &out, -ERANGE);
    fixture(&f); f.input.bytes = out.bytes; reject(&f.input, &out, -EINVAL);
    fixture(&f); f.input.known = out.known; reject(&f.input, &out, -EINVAL);
    union { struct cp_state_snapshot output; struct cp_state_snapshot_input input; } u;
    fixture(&f); u.input = f.input; reject(&u.input, &u.output, -EINVAL);
    struct { unsigned char mask[CP_STATE_SNAPSHOT_BYTES]; struct cp_state_snapshot output; } tail;
    fixture(&f); memset(&tail, 1, sizeof tail);
    f.input.known = tail.mask; f.input.known_size = sizeof tail;
    reject(&f.input, &tail.output, -EINVAL); /* output aliases unused mask capacity */
    puts("layout_copied_only=1 semantic_applied=0 publication=0 runtime_snapshot_offered=0");
    return 0;
}
