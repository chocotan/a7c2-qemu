/* SPDX-License-Identifier: MIT */
#include "cp-slot2-inputs.h"
#include <errno.h>
#include <string.h>

static int range_ok(const void *p, size_t size) {
    return p && size <= UINTPTR_MAX - (uintptr_t)p;
}
static int overlap(const void *a, size_t an, const void *b, size_t bn) {
    return (uintptr_t)a < (uintptr_t)b + bn && (uintptr_t)b < (uintptr_t)a + an;
}
static int span_ok(const struct cp_slot2_input_span *s, size_t minimum) {
    return s->size >= minimum && s->known_size >= s->size && s->token &&
        s->size - 1 <= UINT32_MAX - s->token && range_ok(s->bytes, s->size) &&
        range_ok(s->known, s->known_size);
}
static int mask_ok(const struct cp_slot2_input_span *s) {
    for (size_t i = 0; i < s->size; i++) if (s->known[i] > 1) return 0;
    return 1;
}
static int known(const struct cp_slot2_input_span *s, size_t offset, size_t size) {
    for (size_t i = 0; i < size; i++) if (s->known[offset + i] != 1) return 0;
    return 1;
}
static uint32_t le32(const unsigned char *p) {
    return p[0] | (uint32_t)p[1] << 8 | (uint32_t)p[2] << 16 | (uint32_t)p[3] << 24;
}
int cp_slot2_inputs_stage(const struct cp_slot2_inputs *input, unsigned char *saved_marker) {
    static const unsigned short fields[][3] = {
        {0x3ac, 0x3e8, 4}, {0x3b0, 0x3ec, 2}, {0x3b4, 0x3f0, 4},
        {0x3b8, 0x400, 4}, {0x3bc, 0x3f4, 4}, {0x3c0, 0x3f8, 2},
        {0x3c4, 0x3fc, 4}, {0x3c8, 0x400, 4}
    };
    static const size_t minimum[] = {200, 0x930, 0xf3a, 0x3cc, 3};
    if (!range_ok(input, sizeof *input) || !range_ok(saved_marker, 1)) return -EINVAL;
    struct cp_slot2_inputs v = *input;
    const struct cp_slot2_input_span *spans[] = {&v.n, &v.root, &v.working, &v.action, &v.t178};
    const void *p[12]; size_t size[12];
    for (size_t i = 0; i < 5; i++) {
        if (!span_ok(spans[i], minimum[i])) return -EINVAL;
        p[2*i] = spans[i]->bytes; p[2*i+1] = spans[i]->known;
        size[2*i] = spans[i]->size; size[2*i+1] = spans[i]->known_size;
    }
    if (v.n.size != 200 || v.working.token != CP_SLOT2_INPUT_WORKING_TOKEN ||
        v.action.token != CP_SLOT2_INPUT_ACTION_TOKEN || v.t178.token != CP_SLOT2_INPUT_T178_TOKEN ||
        v.mode_b_known > 1) return -EINVAL;
    p[10] = saved_marker; size[10] = 1; p[11] = input; size[11] = sizeof *input;
    /* Host storage checks include cross-aliases between bytes and masks. */
    for (size_t i = 0; i < 12; i++) for (size_t j = 0; j < i; j++)
        if (((i >= 4 && i < 8) || i == 10 || (j >= 4 && j < 8) || j == 10) &&
            overlap(p[i], size[i], p[j], size[j])) return -EINVAL;
    for (size_t i = 0; i < 5; i++) for (size_t j = 0; j < i; j++)
        if ((i == 2 || i == 3 || j == 2 || j == 3) &&
            (uint64_t)spans[i]->token < (uint64_t)spans[j]->token + spans[j]->size &&
            (uint64_t)spans[j]->token < (uint64_t)spans[i]->token + spans[i]->size) return -EINVAL;
    for (size_t i = 0; i < 5; i++) if (!mask_ok(spans[i])) return -EINVAL;
    if (!v.mode_b_known || !known(&v.n, 0, 4)) return -ENODATA;
    if (le32(v.n.bytes) != v.root.token) return -EINVAL;
    if (!known(&v.root, 0x92c, 4) || !known(&v.root, 0x158, 4) ||
        !known(&v.action, 0x32d, 1)) return -ENODATA;
    for (size_t i = 0; i < sizeof fields / sizeof fields[0]; i++)
        if (!known(&v.root, fields[i][1], fields[i][2])) return -ENODATA;
    if (!v.mode_b && (!known(&v.t178, 2, 1) ||
        (v.t178.bytes[2] != 1 && !known(&v.root, 0x1c4, 4)))) return -ENODATA;

    /* Caller-side save/clear at 32880e..328822, before the 8a3bd8 effects. */
    *saved_marker = v.action.bytes[0x32d];
    v.action.bytes[0x32d] = 0; v.action.known[0x32d] = 1;
    v.working.bytes[0xf38] = le32(v.root.bytes + 0x92c) == 1;
    v.working.bytes[0xf39] = le32(v.root.bytes + 0x158) == 0;
    v.working.known[0xf38] = v.working.known[0xf39] = 1;
    for (size_t i = 0; i < sizeof fields / sizeof fields[0]; i++) {
        memcpy(v.action.bytes + fields[i][0], v.root.bytes + fields[i][1], fields[i][2]);
        memset(v.action.known + fields[i][0], 1, fields[i][2]);
    }
    if (!v.mode_b) {
        if (v.t178.bytes[2] == 1) memset(v.working.bytes + 0x798, 0, 4);
        else memcpy(v.working.bytes + 0x798, v.root.bytes + 0x1c4, 4);
        memset(v.working.known + 0x798, 1, 4);
    }
    return CP_SLOT2_INPUTS_STAGED;
}
int cp_slot2_normal_word_032x(const struct cp_slot2_input_span *working, unsigned char candidate[2]) {
    if (!range_ok(working, sizeof *working) || !range_ok(candidate, 2)) return -EINVAL;
    struct cp_slot2_input_span c = *working;
    if (!span_ok(&c, 0x10ab) || c.token != CP_SLOT2_INPUT_WORKING_TOKEN ||
        overlap(candidate, 2, c.bytes, c.size) || overlap(candidate, 2, c.known, c.known_size) ||
        overlap(candidate, 2, working, sizeof *working)) return -EINVAL;
    if (!mask_ok(&c)) return -EINVAL;
    if (!known(&c, 0, 2) || !known(&c, 0x10aa, 1)) return -ENODATA;
    unsigned int command = c.bytes[0] | (unsigned int)c.bytes[1] << 8;
    if (command != 0x323 && command != 0x32c) return -ENOTSUP;
    size_t offset = c.bytes[0x10aa] == 1 ? 0 : 6;
    if (!known(&c, offset, 2)) return -ENODATA;
    memcpy(candidate, c.bytes + offset, 2);
    return CP_SLOT2_NORMAL_WORD_STAGED;
}
