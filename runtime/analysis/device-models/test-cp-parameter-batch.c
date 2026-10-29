/* SPDX-License-Identifier: MIT */
#include "cp-parameter-batch.h"
#include <assert.h>
#include <errno.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/wait.h>
#include <unistd.h>

static void put16(unsigned char *p, unsigned value) {
    p[0] = (unsigned char)value;
    p[1] = (unsigned char)(value >> 8);
}

/* Host-constructed fixture, NOT a captured or executed AP packet. */
static unsigned char *fixture(void) {
    unsigned char *p = malloc(CP_PARAMETER_BATCH_BYTES);
    assert(p);
    for (size_t i = 0; i < CP_PARAMETER_BATCH_BYTES; i++)
        p[i] = (unsigned char)(37 * i + 19);
    p[0] = 5;
    put16(p + 2, 0x4063);
    for (size_t i = 0; i < CP_PARAMETER_BATCH_SLOTS; i++) {
        const struct cp_parameter_batch_slot *s = &cp_parameter_batch_slots[i];
        p[s->offset] = 5;
        put16(p + s->offset + 2, s->opcode);
    }
    return p;
}

static int stage(struct cp_parameter_batch *o, const void *p, size_t n) {
    return cp_parameter_batch_stage(o, CP_PARAMETER_BATCH_SOURCE,
                                    CP_PARAMETER_BATCH_TARGET, p, n);
}
static void unchanged(const struct cp_parameter_batch *o,
                      const struct cp_parameter_batch *before) {
    assert(memcmp(o, before, sizeof(*o)) == 0);
}
static void staged_only(const struct cp_parameter_batch *o, const unsigned char *p) {
    assert(o->staged && !o->semantic_applied);
    for (size_t i = 0; i < CP_PARAMETER_BATCH_MASK_WORDS; i++)
        assert(o->semantic_consumed[i] == 0);
    assert(memcmp(o->bytes, p, CP_PARAMETER_BATCH_BYTES) == 0);
}

int main(int argc, char **argv) {
    struct cp_parameter_batch owner = {0}, before;
    unsigned char *p;
    assert(argc >= 2);
    if (!strcmp(argv[1], "schema")) {
        for (size_t i = 0; i < CP_PARAMETER_BATCH_SLOTS; i++) {
            const struct cp_parameter_batch_slot *s = &cp_parameter_batch_slots[i];
            printf("%x %x %x\n", s->opcode, s->offset, s->size);
        }
        return 0;
    }
    p = fixture();
    assert(cp_parameter_batch_init(&owner, true) == 0);
    before = owner;
    if (!strcmp(argv[1], "copy")) {
        assert(stage(&owner, p, CP_PARAMETER_BATCH_BYTES) == CP_PARAMETER_BATCH_STAGED);
        staged_only(&owner, p);
        memset(p, 0, CP_PARAMETER_BATCH_BYTES);
        free(p);
        assert(owner.bytes[0] == 5 && owner.bytes[CP_PARAMETER_BATCH_BYTES - 1] != 0);
        return 0;
    } else if (!strcmp(argv[1], "unaligned")) {
        unsigned char *q = malloc(CP_PARAMETER_BATCH_BYTES + 1);
        assert(q);
        memcpy(q + 1, p, CP_PARAMETER_BATCH_BYTES);
        assert(stage(&owner, q + 1, CP_PARAMETER_BATCH_BYTES) == CP_PARAMETER_BATCH_STAGED);
        staged_only(&owner, p);
        free(q);
    } else if (!strcmp(argv[1], "opaque")) {
        p[1] = 0xff;
        memset(p + 4, 0xff, 4);
        for (size_t i = 0; i < CP_PARAMETER_BATCH_SLOTS; i++) {
            size_t off = cp_parameter_batch_slots[i].offset;
            p[off + 1] = 0xfe;
            memset(p + off + 4, 0xa5, 4);
        }
        assert(stage(&owner, p, CP_PARAMETER_BATCH_BYTES) == CP_PARAMETER_BATCH_STAGED);
        staged_only(&owner, p);
    } else if (!strcmp(argv[1], "each-pid") || !strcmp(argv[1], "each-type")) {
        size_t delta = !strcmp(argv[1], "each-pid") ? 2 : 0;
        for (size_t i = 0; i < CP_PARAMETER_BATCH_SLOTS; i++) {
            size_t off = cp_parameter_batch_slots[i].offset + delta;
            p[off] ^= 0x80;
            assert(stage(&owner, p, CP_PARAMETER_BATCH_BYTES) == -EPROTO);
            unchanged(&owner, &before);
            p[off] ^= 0x80;
        }
    } else if (!strcmp(argv[1], "order")) {
        put16(p + 0x00a, 0x4006);
        put16(p + 0x016, 0x4002);
        assert(stage(&owner, p, CP_PARAMETER_BATCH_BYTES) == -EPROTO);
        unchanged(&owner, &before);
    } else if (!strcmp(argv[1], "outer")) {
        const size_t offsets[] = {0, 2, 3};
        for (size_t i = 0; i < sizeof(offsets) / sizeof(offsets[0]); i++) {
            p[offsets[i]] ^= 0x80;
            assert(stage(&owner, p, CP_PARAMETER_BATCH_BYTES) == -EPROTO);
            unchanged(&owner, &before);
            p[offsets[i]] ^= 0x80;
        }
    } else if (!strcmp(argv[1], "size")) {
        const size_t sizes[] = {0, 1, 7, 8, 9, CP_PARAMETER_BATCH_BYTES - 1,
                                CP_PARAMETER_BATCH_BYTES + 1, SIZE_MAX};
        for (size_t i = 0; i < sizeof(sizes) / sizeof(sizes[0]); i++) {
            assert(stage(&owner, p, sizes[i]) == -EMSGSIZE);
            unchanged(&owner, &before);
        }
    } else if (!strcmp(argv[1], "source")) {
        assert(cp_parameter_batch_stage(&owner, 0x80020003,
            CP_PARAMETER_BATCH_TARGET, p, CP_PARAMETER_BATCH_BYTES) == -EPERM);
        assert(cp_parameter_batch_stage(&owner, CP_PARAMETER_BATCH_SOURCE,
            0x90030002, p, CP_PARAMETER_BATCH_BYTES) == -EPERM);
        unchanged(&owner, &before);
    } else if (!strcmp(argv[1], "alias")) {
        const void *aliases[] = {&owner, owner.bytes,
            (const unsigned char *)&owner + sizeof(owner) - 1,
            (const void *)((uintptr_t)&owner - CP_PARAMETER_BATCH_BYTES + 1)};
        for (size_t i = 0; i < sizeof(aliases) / sizeof(aliases[0]); i++) {
            assert(stage(&owner, aliases[i], CP_PARAMETER_BATCH_BYTES) == -EINVAL);
            unchanged(&owner, &before);
        }
    } else if (!strcmp(argv[1], "overflow")) {
        assert(stage(&owner, (const void *)(UINTPTR_MAX - 1),
                     CP_PARAMETER_BATCH_BYTES) == -EINVAL);
        unchanged(&owner, &before);
    } else if (!strcmp(argv[1], "missing")) {
        assert(stage(NULL, p, CP_PARAMETER_BATCH_BYTES) == -EINVAL);
        assert(stage(&owner, NULL, CP_PARAMETER_BATCH_BYTES) == -EINVAL);
        assert(cp_parameter_batch_init(NULL, true) == -EINVAL);
        unchanged(&owner, &before);
    } else if (!strcmp(argv[1], "disabled")) {
        struct cp_parameter_batch zero = {0};
        assert(stage(&zero, p, CP_PARAMETER_BATCH_BYTES) == -EACCES);
        assert(!zero.staged);
        assert(cp_parameter_batch_init(&owner, false) == 0);
        before = owner;
        assert(stage(&owner, p, CP_PARAMETER_BATCH_BYTES) == -EACCES);
        unchanged(&owner, &before);
    } else if (!strcmp(argv[1], "one-shot")) {
        assert(stage(&owner, p, CP_PARAMETER_BATCH_BYTES) == CP_PARAMETER_BATCH_STAGED);
        before = owner;
        p[CP_PARAMETER_BATCH_BYTES - 1] ^= 1;
        assert(stage(&owner, p, CP_PARAMETER_BATCH_BYTES) == -EBUSY);
        unchanged(&owner, &before);
        assert(cp_parameter_batch_init(&owner, true) == 0);
        assert(stage(&owner, p, CP_PARAMETER_BATCH_BYTES) == CP_PARAMETER_BATCH_STAGED);
        staged_only(&owner, p);
    } else if (!strcmp(argv[1], "fork")) {
        pid_t child = fork();
        int status;
        assert(child >= 0);
        if (!child) {
            assert(stage(&owner, p, CP_PARAMETER_BATCH_BYTES) == -ECHILD);
            unchanged(&owner, &before);
            assert(cp_parameter_batch_init(&owner, true) == 0);
            assert(stage(&owner, p, CP_PARAMETER_BATCH_BYTES) == CP_PARAMETER_BATCH_STAGED);
            staged_only(&owner, p);
            free(p);
            _exit(0);
        }
        assert(waitpid(child, &status, 0) == child);
        assert(WIFEXITED(status) && WEXITSTATUS(status) == 0);
        unchanged(&owner, &before);
    } else if (!strcmp(argv[1], "zero")) {
        memset(p, 0, CP_PARAMETER_BATCH_BYTES);
        assert(stage(&owner, p, CP_PARAMETER_BATCH_BYTES) == -EPROTO);
        unchanged(&owner, &before);
    } else if (!strcmp(argv[1], "source-header-fixture")) {
        FILE *f;
        assert(argc == 3);
        f = fopen(argv[2], "rb");
        assert(f);
        assert(fread(p, 1, CP_PARAMETER_BATCH_BYTES, f) == CP_PARAMETER_BATCH_BYTES);
        assert(fgetc(f) == EOF && fclose(f) == 0);
        assert(stage(&owner, p, CP_PARAMETER_BATCH_BYTES) == CP_PARAMETER_BATCH_STAGED);
        staged_only(&owner, p);
    } else {
        assert(!"unknown self-test case");
    }
    free(p);
    return 0;
}
