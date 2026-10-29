/* SPDX-License-Identifier: MIT */
#include "cp-full-state-snapshot.h"
#include <assert.h>
#include <errno.h>
#include <stdio.h>
#include <string.h>

struct fixture {
    unsigned char bytes[CP_STATE_SNAPSHOT_BYTES], known[CP_STATE_SNAPSHOT_BYTES + 9];
    struct cp_state_snapshot_input full, fragments[CP_FULL_STATE_SNAPSHOT_BLOCKS];
    struct cp_state_snapshot_generation generation;
};
static const unsigned char boolean_offsets[] = {
    0xa, 0xb, 0xf, 0x10, 0x75, 0x78, 0x79, 0x7a, 0x7b,
    0x7e, 0x7f, 0x82, 0x83, 0x86, 0x87, 0x8e
};
static const unsigned char ternary_offsets[] = {9, 0xc, 0x77, 0x7c, 0x8a, 0x8b, 0x8c, 0x8d};
static void put16(unsigned char *p, unsigned int v) {
    p[0] = (unsigned char)v; p[1] = (unsigned char)(v >> 8);
}
static void header(unsigned char *p, unsigned int command) {
    p[0] = 6; put16(p + 2, command); memset(p + 4, 0, 4);
}
static void generations(struct fixture *f) {
    f->full.generation = f->generation;
    for (size_t i = 0; i < CP_FULL_STATE_SNAPSHOT_BLOCKS; i++)
        f->fragments[i].generation = f->generation;
}
static void fixture(struct fixture *f) {
    const size_t a = CP_STATE_SNAPSHOT_APERTURE_OFFSET, l = CP_STATE_SNAPSHOT_LENS_OFFSET;
    memset(f, 0, sizeof *f);
    /* LAB virtual values only: every payload is explicitly supplied and nonzero.
     * This fixture claims no original getter/provider/native/business history. */
    for (size_t i = 0; i < sizeof f->bytes; i++) f->bytes[i] = (unsigned char)(1 + (37*i + 19)%255);
    memset(f->known, 1, sizeof f->known);
    memset(f->known + sizeof f->bytes, 0xee, 9);
    header(f->bytes, 0x2040);
    f->generation = (struct cp_state_snapshot_generation){CP_STATE_SNAPSHOT_PUBLISHED_BYTES, 9, 7, 6};
    f->full = (struct cp_state_snapshot_input){f->bytes, f->known, sizeof f->bytes, sizeof f->known, f->generation};
    size_t end = 8;
    for (size_t i = 0; i < CP_FULL_STATE_SNAPSHOT_BLOCKS; i++) {
        const struct cp_full_state_snapshot_block b = cp_full_state_snapshot_blocks[i];
        assert(b.offset == end && b.bytes >= 8);
        header(f->bytes + b.offset, b.command);
        f->fragments[i] = (struct cp_state_snapshot_input){
            f->bytes + b.offset, f->known + b.offset, b.bytes, b.bytes, f->generation
        };
        end += b.bytes;
    }
    assert(end == CP_STATE_SNAPSHOT_BYTES);
    assert(cp_full_state_snapshot_blocks[19].offset == a && cp_full_state_snapshot_blocks[19].bytes == 20);
    assert(cp_full_state_snapshot_blocks[32].offset == l && cp_full_state_snapshot_blocks[32].bytes == 0xa0);
    f->fragments[75].known_size += 9; /* unused capacity is deliberately not a logical mask */
    const unsigned int aperture[5] = {0xf4, 0xffff, 0x8000, 1, 0x201b};
    for (size_t i = 0; i < 5; i++) put16(f->bytes + a + 8 + 2*i, aperture[i]);
    f->bytes[l + 8] = 4; f->bytes[l + 0xe] = 3;
    for (size_t i = 0; i < sizeof boolean_offsets; i++) f->bytes[l + boolean_offsets[i]] = 1;
    for (size_t i = 0; i < sizeof ternary_offsets; i++) f->bytes[l + ternary_offsets[i]] = 2;
    f->bytes[l + 0xd] = 0xfe; f->bytes[l + 0x88] = 0xaa;
    memset(f->bytes + l + 0x34, 'L', CP_STATE_SNAPSHOT_NAME_BYTES);
}
static void reject_copy(const struct cp_state_snapshot_input *input, struct cp_state_snapshot *out, int error) {
    unsigned char before[sizeof *out];
    memcpy(before, out, sizeof before);
    assert(cp_full_state_snapshot_copy(input, out) == error);
    assert(memcmp(before, out, sizeof before) == 0);
}
static void reject_assemble(struct fixture *f, size_t count,
                            const struct cp_state_snapshot_generation *g,
                            struct cp_state_snapshot *out, int error) {
    unsigned char before[sizeof *out], source[sizeof *f];
    memcpy(before, out, sizeof before); memcpy(source, f, sizeof source);
    assert(cp_full_state_snapshot_assemble(f->fragments, count, g, out) == error);
    assert(memcmp(before, out, sizeof before) == 0 && memcmp(source, f, sizeof source) == 0);
}
static void reject_both(struct fixture *f, struct cp_state_snapshot *out, int error) {
    unsigned char source[sizeof *f];
    memcpy(source, f, sizeof source);
    reject_copy(&f->full, out, error);
    reject_assemble(f, CP_FULL_STATE_SNAPSHOT_BLOCKS, &f->generation, out, error);
    assert(memcmp(source, f, sizeof source) == 0);
}
static void success(struct fixture *f, struct cp_state_snapshot *out) {
    unsigned char source[sizeof *f];
    memcpy(source, f, sizeof source);
    assert(cp_full_state_snapshot_copy(&f->full, out) == CP_FULL_STATE_SNAPSHOT_LAYOUT_ASSEMBLED);
    assert(memcmp(out->bytes, f->bytes, sizeof out->bytes) == 0);
    assert(memcmp(out->known, f->known, sizeof out->known) == 0);
    assert(cp_full_state_snapshot_assemble(f->fragments, CP_FULL_STATE_SNAPSHOT_BLOCKS,
                                          &f->generation, out) == CP_FULL_STATE_SNAPSHOT_LAYOUT_ASSEMBLED);
    assert(out->bytes[1] == 0 && out->known[1] == 0);
    assert(memcmp(out->bytes + 8, f->bytes + 8, sizeof out->bytes - 8) == 0);
    assert(memcmp(out->known + 8, f->known + 8, sizeof out->known - 8) == 0);
    assert(memcmp(source, f, sizeof source) == 0);
    assert(out->aperture_words[0] == 0xf4 && out->aperture_words[1] == UINT16_MAX);
    assert(out->aperture_words[2] == 0x8000 && out->aperture_words[3] == 1 && out->aperture_words[4] == 0x201b);
    assert(out->lens_wire_state == 4 && out->lens_name[0] == 'L' && out->lens_name[0x41] == 0);
    assert(out->generation.published_generation == f->generation.published_generation);
}
int main(void) {
    struct fixture f;
    struct cp_state_snapshot out;
    const size_t a = CP_STATE_SNAPSHOT_APERTURE_OFFSET, l = CP_STATE_SNAPSHOT_LENS_OFFSET;
    fixture(&f); memset(&out, 0xa5, sizeof out); success(&f, &out);
    f.known[1] = f.known[a + 1] = f.known[l + 1] = 0;
    f.bytes[1] = 0x93; f.bytes[a + 1] = 0xe5; f.bytes[l + 1] = 0xff;
    success(&f, &out);
    assert(out.bytes[a + 1] == 0xe5 && out.known[a + 1] == 0);
    assert(out.bytes[l + 1] == 0xff && out.known[l + 1] == 0);
    f.fragments[0].known_size = sizeof f.known - 8;
    success(&f, &out); /* read-only input capacities may overlap each other */
    f.generation.published_generation = 0; f.generation.shadow_generation = UINT32_MAX;
    generations(&f); success(&f, &out);
    f.generation.mutable_generation = 0; generations(&f); success(&f, &out);
    f.generation.shadow_generation = 0; generations(&f); reject_both(&f, &out, -ESTALE);
    f.generation.provenance = CP_STATE_SNAPSHOT_UNPUBLISHED; generations(&f); reject_both(&f, &out, -ENOTSUP);
    f.generation.provenance = (enum cp_state_snapshot_provenance)17; generations(&f); reject_both(&f, &out, -EINVAL);

    /* Every block's type, both command bytes and all four zero-word bytes. */
    const unsigned int fields[] = {0, 2, 3, 4, 5, 6, 7};
    for (size_t i = 0; i < CP_FULL_STATE_SNAPSHOT_BLOCKS; i++) {
        for (size_t j = 0; j < sizeof fields / sizeof fields[0]; j++) {
            fixture(&f); f.bytes[cp_full_state_snapshot_blocks[i].offset + fields[j]] ^= 1;
            reject_both(&f, &out, -EPROTO);
        }
        fixture(&f); f.fragments[i].size = 0;
        reject_assemble(&f, 76, &f.generation, &out, -EINVAL);
        fixture(&f); f.fragments[i].size--;
        reject_assemble(&f, 76, &f.generation, &out, -EINVAL);
        fixture(&f); f.fragments[i].size++;
        reject_assemble(&f, 76, &f.generation, &out, -EINVAL);
        fixture(&f); f.fragments[i].bytes = NULL;
        reject_assemble(&f, 76, &f.generation, &out, -EINVAL);
        fixture(&f); f.fragments[i].known = NULL;
        reject_assemble(&f, 76, &f.generation, &out, -EINVAL);
        fixture(&f); f.fragments[i].known_size = f.fragments[i].size - 1;
        reject_assemble(&f, 76, &f.generation, &out, -EINVAL);
        fixture(&f); f.fragments[i].generation.mutable_generation++;
        reject_assemble(&f, 76, &f.generation, &out, -ESTALE);
        fixture(&f); f.fragments[i].generation.published_generation++;
        reject_assemble(&f, 76, &f.generation, &out, -ESTALE);
        fixture(&f); f.fragments[i].generation.shadow_generation++;
        reject_assemble(&f, 76, &f.generation, &out, -ESTALE);
        fixture(&f); f.fragments[i].generation.provenance = CP_STATE_SNAPSHOT_UNPUBLISHED;
        reject_assemble(&f, 76, &f.generation, &out, -ESTALE);
    }
    for (size_t j = 0; j < sizeof fields / sizeof fields[0]; j++) {
        fixture(&f); f.bytes[fields[j]] ^= 1; reject_copy(&f.full, &out, -EPROTO);
    }
    /* Keep precisely the existing three unknown-byte exceptions, including +1. */
    fixture(&f);
    for (size_t i = 0; i < sizeof f.bytes; i++) {
        f.known[i] = 0;
        if (i == 1 || i == a + 1 || i == l + 1) success(&f, &out);
        else {
            reject_copy(&f.full, &out, -ENODATA);
            if (i >= 8) reject_assemble(&f, 76, &f.generation, &out, -ENODATA);
        }
        f.known[i] = 2;
        reject_copy(&f.full, &out, -EINVAL);
        if (i >= 8) reject_assemble(&f, 76, &f.generation, &out, -EINVAL);
        f.known[i] = 1;
    }
    for (size_t i = 0; i < sizeof boolean_offsets; i++) {
        fixture(&f); f.bytes[l + boolean_offsets[i]] = 2; reject_both(&f, &out, -ERANGE);
    }
    for (size_t i = 0; i < sizeof ternary_offsets; i++) {
        fixture(&f); f.bytes[l + ternary_offsets[i]] = 3; reject_both(&f, &out, -ERANGE);
    }
    fixture(&f); f.bytes[l + 8] = 2; reject_both(&f, &out, -ERANGE);
    fixture(&f); f.bytes[l + 0xe] = 4; reject_both(&f, &out, -ERANGE);
    fixture(&f); struct cp_state_snapshot_input swap = f.fragments[0];
    f.fragments[0] = f.fragments[1]; f.fragments[1] = swap;
    reject_assemble(&f, 76, &f.generation, &out, -EPROTO);
    fixture(&f); f.fragments[1] = f.fragments[0];
    reject_assemble(&f, 76, &f.generation, &out, -EPROTO);
    fixture(&f); struct cp_state_snapshot_generation other = f.generation; other.published_generation++;
    reject_assemble(&f, 76, &other, &out, -ESTALE);
    const size_t bad_counts[] = {0, 75, 77, SIZE_MAX};
    for (size_t i = 0; i < sizeof bad_counts / sizeof bad_counts[0]; i++)
        reject_assemble(&f, bad_counts[i], &f.generation, &out, -EINVAL);

    fixture(&f); f.full.size--; reject_copy(&f.full, &out, -EINVAL);
    f.full.size += 2; reject_copy(&f.full, &out, -EINVAL);
    fixture(&f); f.full.known_size--; f.full.known_size -= 9; reject_copy(&f.full, &out, -EINVAL);
    fixture(&f); f.full.bytes = NULL; reject_copy(&f.full, &out, -EINVAL);
    fixture(&f); f.full.known = NULL; reject_copy(&f.full, &out, -EINVAL);
    fixture(&f); f.full.bytes = (const unsigned char *)(UINTPTR_MAX - 3); reject_copy(&f.full, &out, -EINVAL);
    fixture(&f); f.full.known_size = SIZE_MAX; reject_copy(&f.full, &out, -EINVAL);
    reject_copy(NULL, &out, -EINVAL);
    reject_copy((const struct cp_state_snapshot_input *)(UINTPTR_MAX - 3), &out, -EINVAL);
    fixture(&f); assert(cp_full_state_snapshot_copy(&f.full, NULL) == -EINVAL);
    assert(cp_full_state_snapshot_copy(&f.full, (struct cp_state_snapshot *)(UINTPTR_MAX - 3)) == -EINVAL);
    assert(cp_full_state_snapshot_assemble(NULL, 76, &f.generation, &out) == -EINVAL);
    assert(cp_full_state_snapshot_assemble((const struct cp_state_snapshot_input *)(UINTPTR_MAX - 3),
                                           76, &f.generation, &out) == -EINVAL);
    reject_assemble(&f, 76, NULL, &out, -EINVAL);
    reject_assemble(&f, 76, (const struct cp_state_snapshot_generation *)(UINTPTR_MAX - 3), &out, -EINVAL);
    assert(cp_full_state_snapshot_assemble(f.fragments, 76, &f.generation, NULL) == -EINVAL);
    assert(cp_full_state_snapshot_assemble(f.fragments, 76, &f.generation,
                                           (struct cp_state_snapshot *)(UINTPTR_MAX - 3)) == -EINVAL);
    for (size_t i = 0; i < CP_FULL_STATE_SNAPSHOT_BLOCKS; i++) {
        fixture(&f); f.fragments[i].bytes = (const unsigned char *)(UINTPTR_MAX - 3);
        reject_assemble(&f, 76, &f.generation, &out, -EINVAL);
        fixture(&f); f.fragments[i].known = (const unsigned char *)(UINTPTR_MAX - 3);
        reject_assemble(&f, 76, &f.generation, &out, -EINVAL);
        fixture(&f); f.fragments[i].known_size = SIZE_MAX;
        reject_assemble(&f, 76, &f.generation, &out, -EINVAL);
        fixture(&f); f.fragments[i].bytes = out.bytes;
        reject_assemble(&f, 76, &f.generation, &out, -EINVAL);
        fixture(&f); f.fragments[i].known = out.known;
        reject_assemble(&f, 76, &f.generation, &out, -EINVAL);
    }
    fixture(&f); f.full.bytes = out.bytes; reject_copy(&f.full, &out, -EINVAL);
    fixture(&f); f.full.known = out.known; reject_copy(&f.full, &out, -EINVAL);
    fixture(&f); reject_assemble(&f, 76, &out.generation, &out, -EINVAL);
    union { struct cp_state_snapshot output; struct cp_state_snapshot_input input; } u;
    memset(&u, 0x55, sizeof u); u.input = f.full; reject_copy(&u.input, &u.output, -EINVAL);
    union {
        struct cp_state_snapshot output;
        struct cp_state_snapshot_input fragments[76];
        unsigned char room[76 * sizeof(struct cp_state_snapshot_input) + sizeof(struct cp_state_snapshot)];
    } v;
    memset(&v, 0x55, sizeof v); memcpy(v.fragments, f.fragments, sizeof v.fragments);
    unsigned char before[sizeof v]; memcpy(before, &v, sizeof v);
    assert(cp_full_state_snapshot_assemble(v.fragments, 76, &f.generation, &v.output) == -EINVAL);
    struct cp_state_snapshot *last_descriptor = (struct cp_state_snapshot *)(void *)&v.fragments[75];
    assert(cp_full_state_snapshot_assemble(v.fragments, 76, &f.generation, last_descriptor) == -EINVAL);
    assert(memcmp(before, &v, sizeof v) == 0);
    struct { unsigned char mask[CP_STATE_SNAPSHOT_BYTES]; struct cp_state_snapshot output; } tail;
    memset(&tail, 1, sizeof tail);
    fixture(&f); f.full.known = tail.mask; f.full.known_size = sizeof tail;
    reject_copy(&f.full, &tail.output, -EINVAL);
    for (size_t i = 0; i < CP_FULL_STATE_SNAPSHOT_BLOCKS; i++) {
        fixture(&f); f.fragments[i].known = tail.mask; f.fragments[i].known_size = sizeof tail;
        reject_assemble(&f, 76, &f.generation, &tail.output, -EINVAL);
    }
    fixture(&f); success(&f, &out);
    memset(f.bytes, 0xee, sizeof f.bytes); memset(f.known, 0, sizeof f.known);
    assert(out.bytes[8] == 6 && out.known[8] == 1 && out.lens_name[0] == 'L');
    puts("full_layout_assembled_only=1 blocks=76 providers_complete=0 publication=0 native_business=0 frame=0 capture=0");
    return 0;
}
