/* SPDX-License-Identifier: MIT */
#include "cp-slot2-inputs.h"
#include <assert.h>
#include <errno.h>
#include <stdio.h>
#include <string.h>

struct fixture {
    unsigned char n[208], nk[208], r[0x940], rk[0x940];
    unsigned char c[0x1360], ck[0x1360], a[0x3d0], ak[0x3d0], t[0x188], tk[0x188];
    struct cp_slot2_inputs in;
};
static const struct field {
    size_t source, destination, width;
    uint32_t value[2];
} fields[] = {
    {0x3e8, 0x3ac, 4, {0x12345678, 0xdeadbeef}},
    {0x3ec, 0x3b0, 2, {0x9abc, 0x12ef}},
    {0x3f0, 0x3b4, 4, {0x89abcdef, 0xff000080}},
    {0x400, 0x3b8, 4, {0x10203040, 0x80706050}},
    {0x3f4, 0x3bc, 4, {0x80000001, 0x0100ff02}},
    {0x3f8, 0x3c0, 2, {0xff00, 0x80fe}},
    {0x3fc, 0x3c4, 4, {0x00010002, 0x81828384}},
    {0x400, 0x3c8, 4, {0x10203040, 0x80706050}}
};
static void put(unsigned char *p, uint32_t value, size_t width) {
    for (size_t i = 0; i < width; i++) p[i] = (unsigned char)(value >> (8*i));
}
static struct cp_slot2_input_span span(unsigned char *b, unsigned char *k, size_t n,
                                      size_t capacity, uint32_t token) {
    struct cp_slot2_input_span s = {b, k, n, capacity, token}; return s;
}
static struct cp_slot2_input_span *at(struct fixture *f, size_t i) {
    struct cp_slot2_input_span *s[] = {&f->in.n, &f->in.root, &f->in.working, &f->in.action, &f->in.t178};
    return s[i];
}
static void init(struct fixture *f, unsigned int variant) {
    memset(f, 0, sizeof *f);
    memset(f->n, 0xa5, sizeof f->n); memset(f->r, 0xa5, sizeof f->r);
    memset(f->c, 0xa5, sizeof f->c); memset(f->a, 0xa5, sizeof f->a);
    memset(f->t, 0xa5, sizeof f->t);
    f->in.n = span(f->n, f->nk, 200, sizeof f->nk, 0x03000000);
    f->in.root = span(f->r, f->rk, 0x930, sizeof f->rk, 0x10000000);
    f->in.working = span(f->c, f->ck, 0xf3a, sizeof f->ck, CP_SLOT2_INPUT_WORKING_TOKEN);
    f->in.action = span(f->a, f->ak, 0x3cc, sizeof f->ak, CP_SLOT2_INPUT_ACTION_TOKEN);
    f->in.t178 = span(f->t, f->tk, 3, sizeof f->tk, CP_SLOT2_INPUT_T178_TOKEN);
    put(f->n, f->in.root.token, 4); memset(f->nk, 1, 4);
    for (size_t i = 0; i < sizeof fields / sizeof fields[0]; i++) {
        put(f->r + fields[i].source, fields[i].value[variant], fields[i].width);
        memset(f->rk + fields[i].source, 1, fields[i].width);
    }
    put(f->r + 0x92c, variant ? 2 : 1, 4); memset(f->rk + 0x92c, 1, 4);
    put(f->r + 0x158, variant ? 0x10000000 : 0, 4); memset(f->rk + 0x158, 1, 4);
    put(f->r + 0x1c4, 0xfedcba98, 4); memset(f->rk + 0x1c4, 1, 4);
    f->a[0x32d] = (unsigned char)(0x7d + variant); f->ak[0x32d] = 1;
    f->t[2] = 4; f->tk[2] = 1; f->in.mode_b_known = 1;
}
static void stage_ok(struct fixture *f, unsigned int variant) {
    struct fixture expected = *f;
    unsigned char saved = 0x5b, old = f->a[0x32d];
    static const unsigned char one[4] = {1, 0, 0, 0}, zero[4] = {0, 0, 0, 0};
    expected.a[0x32d] = 0; expected.ak[0x32d] = 1;
    expected.c[0xf38] = memcmp(f->r + 0x92c, one, 4) == 0;
    expected.c[0xf39] = memcmp(f->r + 0x158, zero, 4) == 0;
    expected.ck[0xf38] = expected.ck[0xf39] = 1;
    for (size_t i = 0; i < sizeof fields / sizeof fields[0]; i++) {
        put(expected.a + fields[i].destination, fields[i].value[variant], fields[i].width);
        memset(expected.ak + fields[i].destination, 1, fields[i].width);
    }
    if (!f->in.mode_b) {
        if (f->t[2] == 1) memset(expected.c + 0x798, 0, 4);
        else memcpy(expected.c + 0x798, f->r + 0x1c4, 4);
        memset(expected.ck + 0x798, 1, 4);
    }
    assert(cp_slot2_inputs_stage(&f->in, &saved) == CP_SLOT2_INPUTS_STAGED);
    assert(saved == old);
    assert(memcmp(f, &expected, sizeof *f) == 0);
}
static void stage_fail(struct fixture *f, int error) {
    struct fixture before = *f;
    unsigned char saved = 0x5b;
    assert(cp_slot2_inputs_stage(&f->in, &saved) == error);
    assert(saved == 0x5b && memcmp(f, &before, sizeof *f) == 0);
}
static void unknown_reads(void) {
    static const size_t offsets[] = {0x92c, 0x158, 0x1c4};
    struct fixture f;
    for (size_t i = 0; i < 4; i++) { init(&f, 0); f.nk[i] = 0; stage_fail(&f, -ENODATA); }
    for (size_t i = 0; i < sizeof fields / sizeof fields[0]; i++)
        for (size_t j = 0; j < fields[i].width; j++) {
            init(&f, 0); f.rk[fields[i].source + j] = 0; stage_fail(&f, -ENODATA);
        }
    for (size_t i = 0; i < sizeof offsets / sizeof offsets[0]; i++)
        for (size_t j = 0; j < 4; j++) {
            init(&f, 0); f.rk[offsets[i] + j] = 0; stage_fail(&f, -ENODATA);
        }
    init(&f, 0); f.ak[0x32d] = 0; stage_fail(&f, -ENODATA);
    init(&f, 0); f.tk[2] = 0; stage_fail(&f, -ENODATA);
    init(&f, 0); f.in.mode_b_known = 0; stage_fail(&f, -ENODATA);
}
static void aliases(void) {
    struct fixture f, before;
    for (size_t mutable = 2; mutable < 4; mutable++) for (size_t other = 0; other < 5; other++)
        for (size_t masks = 0; masks < 4; masks++) {
            if (mutable == other && (masks == 0 || masks == 3)) continue;
            init(&f, 0);
            unsigned char **target = masks & 1 ? &at(&f, mutable)->known : &at(&f, mutable)->bytes;
            *target = masks & 2 ? at(&f, other)->known : at(&f, other)->bytes;
            stage_fail(&f, -EINVAL);
        }
    for (size_t i = 0; i < 5; i++) for (size_t mask = 0; mask < 2; mask++) {
        init(&f, 0); before = f;
        unsigned char *saved = mask ? at(&f, i)->known : at(&f, i)->bytes;
        assert(cp_slot2_inputs_stage(&f.in, saved) == -EINVAL);
        assert(memcmp(&f, &before, sizeof f) == 0);
    }
    init(&f, 0); before = f;
    assert(cp_slot2_inputs_stage(&f.in, (unsigned char *)&f.in) == -EINVAL);
    assert(memcmp(&f, &before, sizeof f) == 0);
    init(&f, 0); f.in.root.token = f.in.working.token; put(f.n, f.in.root.token, 4);
    stage_fail(&f, -EINVAL);
    init(&f, 0); f.in.working.bytes = f.r + 1; stage_fail(&f, -EINVAL);
    init(&f, 0); f.in.action.known = (unsigned char *)&f.in; stage_fail(&f, -EINVAL);
}
static void normal_init(struct fixture *f, unsigned int command, unsigned char status) {
    init(f, 0); f->in.working.size = 0x10ab;
    put(f->c, command, 2); memset(f->ck, 1, 2);
    f->c[0x10aa] = status; f->ck[0x10aa] = 1;
    put(f->c + 6, 0xe19a, 2); memset(f->ck + 6, 1, 2);
}
static void capacity_tail_aliases(void) {
    struct fixture f, before;
    init(&f, 0); f.nk[200] = 0x5b; before = f;
    assert(cp_slot2_inputs_stage(&f.in, f.nk + 200) == -EINVAL);
    assert(!memcmp(&f, &before, sizeof f));
    normal_init(&f, 0x323, 1); f.ck[0x10ab] = f.ck[0x10ac] = 0x5b; before = f;
    assert(cp_slot2_normal_word_032x(&f.in.working, f.ck + 0x10ab) == -EINVAL);
    assert(!memcmp(&f, &before, sizeof f));
    unsigned char mask_tail[0x930 + 0xf3a], old[sizeof mask_tail];
    init(&f, 0); memset(mask_tail, 0x5b, sizeof mask_tail);memcpy(mask_tail, f.rk, 0x930);
    f.in.root.known = mask_tail; f.in.root.known_size = sizeof mask_tail;
    f.in.working.bytes = mask_tail + 0x930;
    memcpy(old, mask_tail, sizeof old); before = f; unsigned char saved = 0x5b;
    assert(cp_slot2_inputs_stage(&f.in, &saved) == -EINVAL);
    assert(saved == 0x5b && !memcmp(old, mask_tail, sizeof old) && !memcmp(&f, &before, sizeof f));
}
static void normal_check(struct fixture *f, int result, unsigned int word) {
    struct fixture before = *f;
    unsigned char output[4] = {0x5a, 0xa5, 0xa5, 0x5a};
    assert(cp_slot2_normal_word_032x(&f->in.working, output + 1) == result);
    assert(output[0] == 0x5a && output[3] == 0x5a);
    if (!result) assert(output[1] == (word & 255) && output[2] == (word >> 8));
    else assert(output[1] == 0xa5 && output[2] == 0xa5);
    assert(memcmp(f, &before, sizeof *f) == 0);
}
int main(int argc, char **argv) {
    assert(argc == 2);
    const char *name = argv[1]; struct fixture f;
    if (!strcmp(name, "table-a") || !strcmp(name, "table-b")) {
        unsigned int variant = !strcmp(name, "table-b"); init(&f, variant); stage_ok(&f, variant);
    } else if (!strcmp(name, "mode0-t-one")) {
        init(&f, 0); f.t[2] = 1; memset(f.rk + 0x1c4, 0, 4); stage_ok(&f, 0);
    } else if (!strcmp(name, "mode0-t-other")) {
        const unsigned char values[] = {0, 2, 255};
        for (size_t i = 0; i < sizeof values; i++) { init(&f, 0); f.t[2] = values[i]; stage_ok(&f, 0); }
    } else if (!strcmp(name, "mode-nonzero")) {
        const unsigned char values[] = {1, 2, 255};
        for (size_t i = 0; i < sizeof values; i++) {
            init(&f, 0); f.in.mode_b = values[i]; f.tk[2] = 0; memset(f.rk + 0x1c4, 0, 4);
            f.c[0x798] = 0x19; f.ck[0x799] = 1; f.c[0x79b] = 0xee; stage_ok(&f, 0);
        }
    } else if (!strcmp(name, "exact-enums")) {
        const uint32_t values[] = {0, 1, 2, 0x100, 0x01000000, UINT32_MAX};
        for (size_t i = 0; i < sizeof values / sizeof values[0]; i++) {
            init(&f, 0); put(f.r + 0x92c, values[i], 4); put(f.r + 0x158, values[i], 4); stage_ok(&f, 0);
        }
    } else if (!strcmp(name, "unknown-read")) unknown_reads();
    else if (!strcmp(name, "conditional-unknown")) {
        init(&f, 0); f.t[2] = 1; memset(f.rk + 0x1c4, 0, 4); stage_ok(&f, 0);
        init(&f, 0); f.in.mode_b = 1; f.tk[2] = 0; memset(f.rk + 0x1c4, 0, 4); stage_ok(&f, 0);
        init(&f, 0); f.t[2] = 2; memset(f.rk + 0x1c4, 0, 4); stage_fail(&f, -ENODATA);
    } else if (!strcmp(name, "token")) {
        for (size_t i = 1; i < 5; i++) { init(&f, 0); at(&f, i)->token++; stage_fail(&f, -EINVAL); }
        init(&f, 0); f.in.n.token = 0; stage_fail(&f, -EINVAL);
        init(&f, 0); f.n[3] ^= 1; stage_fail(&f, -EINVAL);
    } else if (!strcmp(name, "short-span")) {
        for (size_t i = 0; i < 5; i++) {
            init(&f, 0); at(&f, i)->size--; stage_fail(&f, -EINVAL);
            init(&f, 0); at(&f, i)->known_size = at(&f, i)->size - 1; stage_fail(&f, -EINVAL);
        }
        init(&f, 0); f.in.n.size++; stage_fail(&f, -EINVAL);
        init(&f, 0); f.in.working.size = 0x1350; f.in.t178.size = 0x178; stage_ok(&f, 0);
    } else if (!strcmp(name, "mask")) {
        for (size_t i = 0; i < 5; i++) { init(&f, 0); at(&f, i)->known[7 % at(&f, i)->size] = 2; stage_fail(&f, -EINVAL); }
        init(&f, 0); f.ck[0x798] = 2; f.in.mode_b = 1; stage_fail(&f, -EINVAL);
        init(&f, 0); f.in.mode_b_known = 2; stage_fail(&f, -EINVAL);
    } else if (!strcmp(name, "alias")) aliases();
    else if (!strcmp(name, "capacity-tail-alias")) capacity_tail_aliases();
    else if (!strcmp(name, "readonly-alias")) {
        init(&f, 0); f.in.n.bytes = f.r; f.in.n.known = f.rk; f.in.n.token = f.in.root.token;
        put(f.r, f.in.root.token, 4); memset(f.rk, 1, 4); stage_ok(&f, 0);
    } else if (!strcmp(name, "overflow")) {
        for (size_t i = 0; i < 5; i++) {
            init(&f, 0); at(&f, i)->size = SIZE_MAX; at(&f, i)->known_size = SIZE_MAX; stage_fail(&f, -EINVAL);
            init(&f, 0); at(&f, i)->known_size = SIZE_MAX; stage_fail(&f, -EINVAL);
            init(&f, 0); at(&f, i)->bytes = (unsigned char *)(UINTPTR_MAX - 1); stage_fail(&f, -EINVAL);
            init(&f, 0); at(&f, i)->known = (unsigned char *)(UINTPTR_MAX - 1); stage_fail(&f, -EINVAL);
            init(&f, 0); at(&f, i)->token = UINT32_MAX - 1; stage_fail(&f, -EINVAL);
        }
        init(&f, 0); f.in.root.token = UINT32_MAX - 0x92f; put(f.n, f.in.root.token, 4); stage_ok(&f, 0);
        init(&f, 0); struct fixture before = f; unsigned char saved = 0x5b;
        assert(cp_slot2_inputs_stage((const struct cp_slot2_inputs *)UINTPTR_MAX, &saved) == -EINVAL);
        assert(cp_slot2_inputs_stage(&f.in, (unsigned char *)UINTPTR_MAX) == -EINVAL);
        assert(saved == 0x5b && memcmp(&f, &before, sizeof f) == 0);
    } else if (!strcmp(name, "missing")) {
        for (size_t i = 0; i < 5; i++) {
            init(&f, 0); at(&f, i)->bytes = NULL; stage_fail(&f, -EINVAL);
            init(&f, 0); at(&f, i)->known = NULL; stage_fail(&f, -EINVAL);
        }
        init(&f, 0); struct fixture before = f; unsigned char saved = 0x5b;
        assert(cp_slot2_inputs_stage(NULL, &saved) == -EINVAL);
        assert(cp_slot2_inputs_stage(&f.in, NULL) == -EINVAL);
        assert(saved == 0x5b && memcmp(&f, &before, sizeof f) == 0);
    } else if (!strcmp(name, "normal-0323") || !strcmp(name, "normal-032c")) {
        unsigned int command = !strcmp(name, "normal-0323") ? 0x323 : 0x32c;
        normal_init(&f, command, 1); memset(f.ck + 6, 0, 2); normal_check(&f, 0, command);
    } else if (!strcmp(name, "normal-preserve")) {
        normal_init(&f, 0x32c, 0); normal_check(&f, 0, 0xe19a);
    } else if (!strcmp(name, "normal-exact-status")) {
        const unsigned char values[] = {0, 2, 255};
        for (size_t i = 0; i < sizeof values; i++) { normal_init(&f, 0x323, values[i]); normal_check(&f, 0, 0xe19a); }
    } else if (!strcmp(name, "normal-unsupported")) {
        const unsigned int commands[] = {0x302, 0, 0x322, 0x8323};
        for (size_t i = 0; i < sizeof commands / sizeof commands[0]; i++) {
            normal_init(&f, commands[i], 1); normal_check(&f, -ENOTSUP, 0);
        }
    } else if (!strcmp(name, "normal-unknown")) {
        const size_t offsets[] = {0, 1, 6, 7, 0x10aa};
        for (size_t i = 0; i < sizeof offsets / sizeof offsets[0]; i++) {
            normal_init(&f, 0x323, 0); f.ck[offsets[i]] = 0; normal_check(&f, -ENODATA, 0);
        }
    } else if (!strcmp(name, "normal-invalid")) {
        normal_init(&f, 0x323, 1); f.in.working.size = 0x10aa; normal_check(&f, -EINVAL, 0);
        normal_init(&f, 0x323, 1); f.in.working.known_size = 0x10aa; normal_check(&f, -EINVAL, 0);
        normal_init(&f, 0x323, 1); f.in.working.token++; normal_check(&f, -EINVAL, 0);
        normal_init(&f, 0x323, 1); f.ck[3] = 2; normal_check(&f, -EINVAL, 0);
        normal_init(&f, 0x323, 1); f.in.working.known_size = SIZE_MAX; normal_check(&f, -EINVAL, 0);
        normal_init(&f, 0x323, 1); struct fixture before = f;
        unsigned char output[2] = {0xa5, 0xa5};
        assert(cp_slot2_normal_word_032x(NULL, output) == -EINVAL);
        assert(output[0] == 0xa5 && output[1] == 0xa5);
        assert(cp_slot2_normal_word_032x(&f.in.working, NULL) == -EINVAL);
        assert(cp_slot2_normal_word_032x(&f.in.working, f.c + 6) == -EINVAL);
        assert(cp_slot2_normal_word_032x(&f.in.working, f.ck) == -EINVAL);
        assert(cp_slot2_normal_word_032x(&f.in.working, (unsigned char *)&f.in.working) == -EINVAL);
        assert(cp_slot2_normal_word_032x(&f.in.working, (unsigned char *)UINTPTR_MAX) == -EINVAL);
        assert(memcmp(&f, &before, sizeof f) == 0);
    } else assert(!"unknown test case");
    puts("inputs_staged_only=1 command_completed=0 original_CP_executed=0 publication=0");
    return 0;
}
