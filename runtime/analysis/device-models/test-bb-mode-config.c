/* SPDX-License-Identifier: MIT */
#include "bb-mode-config.h"
#include <assert.h>
#include <stdio.h>
#include <string.h>

#define REFUSE (-1021)
static const unsigned char panel[22] = {
    0x0d,0x20,0x18,1,22,0,1,0x80,3,1,0,0,0,0,0,0,0,0,0,0,1,0
};
static const unsigned char mode[10] = {0x0d,0x20,0x10,1,10,0,1,0x80,0,0};
static unsigned int cases;
static void passed(const char *name) { puts(name); cases++; }
static uint64_t fnv(const unsigned char *p, size_t n)
{
    uint64_t h = UINT64_C(0xcbf29ce484222325);
    size_t i;
    for (i = 0; i < n; i++) h = (h ^ p[i]) * UINT64_C(0x100000001b3);
    return h;
}
static unsigned int count_known(const struct full_bb_mode_config_view *v)
{
    unsigned int i, n = 0;
    for (i = 0; i < FULL_BB_MODE_CONFIG_BYTES; i++) {
        assert(v->known[i] == 0 || v->known[i] == 0xff);
        n += v->known[i] == 0xff;
    }
    return n;
}
static uint32_t word(const unsigned char *p)
{
    return (uint32_t)p[0] | (uint32_t)p[1] << 8 | (uint32_t)p[2] << 16 | (uint32_t)p[3] << 24;
}
static void dump(const char *name, const unsigned char *p, size_t n)
{
    size_t i;
    printf("%s=", name);
    for (i = 0; i < n; i++) printf("%02x", p[i]);
    putchar('\n');
}
struct gate {
    struct full_bb_mode_config *owner;
    unsigned int held, locks, unlocks, fail_lock, fail_unlock, reenter_lock, reenter_unlock, tamper;
    unsigned int saw_fault_before_unlock;
};
static int lock_sem5(void *context)
{
    struct gate *g = context;
    assert(!g->held); g->locks++;
    if (g->fail_lock) return -7;
    g->held = 1;
    if (g->reenter_lock) assert(full_bb_mode_config_apply0110(g->owner, mode, sizeof mode) == REFUSE);
    if (g->tamper) g->owner->live.bytes[0x190] ^= 1;
    return 0;
}
static int unlock_sem5(void *context)
{
    struct gate *g = context;
    assert(g->held); g->unlocks++;
    g->saw_fault_before_unlock = g->owner->fault;
    if (g->reenter_unlock) assert(full_bb_mode_config_invalidate(g->owner) == REFUSE);
    if (g->fail_unlock) return -8;
    g->held = 0;
    return 0;
}
static int snapshot(struct full_bb_mode_config *s, struct gate *g)
{
    struct full_bb_mode_config_sem5 sem5 = {g, lock_sem5, unlock_sem5};
    g->owner = s;
    return full_bb_mode_config_snapshot(s, &sem5);
}
static void ctor(void)
{
    static const unsigned int holes[][2] = {
        {0x000,0x003},{0x025,0x027},{0x058,0x05b},{0x064,0x067},{0x108,0x17f},
        {0x181,0x183},{0x1a8,0x1ab},{0x1c1,0x1c3},{0x1cd,0x1cf},{0x239,0x23b},
        {0x24e,0x24f},{0x29d,0x29f},{0x2a9,0x2ab},{0x2d2,0x2d3},{0x2de,0x2df},
        {0x2e9,0x2eb},{0x38e,0x38f},{0x39e,0x39f},{0x402,0x403},{0x40e,0x40f},
        {0x43e,0x43f},{0x47a,0x47b},{0x4ac,0x4af},{0x4bc,0x4bf},{0x4e5,0x4e7},
        {0x5a2,0x5a3},{0x61d,0x61f},{0x657,0x657}
    };
    static const struct { unsigned int offset; uint32_t value; } words[] = {
        {0x0c,27},{0x68,0},{0x6c,UINT32_MAX},{0x90,UINT32_MAX},{0x190,60},
        {0x228,26},{0x3cc,16},{0x3f4,UINT32_MAX},{0x4d0,1600},{0x4d4,900},
        {0x5ac,21},{0x5b4,0},{0x628,11},{0x688,15}
    };
    struct full_bb_mode_config s = {0};
    unsigned int i, j, unknown = 0;
    uint32_t op = UINT32_MAX;
    assert(!full_bb_mode_config_init(&s));
    assert(s.identity == &s && s.initialized && !s.fault && !s.busy);
    assert(count_known(&s.live) == 1565 && count_known(&s.snapshot) == 0);
    for (i = 0; i < FULL_BB_MODE_CONFIG_BYTES; i++) {
        int hole = 0;
        for (j = 0; j < sizeof holes / sizeof *holes; j++)
            hole |= i >= holes[j][0] && i <= holes[j][1];
        assert(s.live.known[i] == (hole ? 0 : 0xff));
        if (hole) { assert(s.live.bytes[i] == 0xa5); unknown++; }
        assert(s.snapshot.bytes[i] == 0xa5);
    }
    assert(unknown == 195);
    for (i = 0; i < sizeof words / sizeof *words; i++) {
        unsigned char got[4];
        assert(!full_bb_mode_config_read(&s, FULL_BB_MODE_CONFIG_LIVE_TOKEN, words[i].offset, got, 4));
        assert(word(got) == words[i].value);
    }
    assert(s.live.bytes[0x2a7] == 99 && s.live.bytes[0x547] == 8);
    assert(s.live.bytes[0x478] == 8 && s.live.bytes[0x479] == 1);
    assert(s.live.data_fnv == UINT64_C(0x2b36ad636500d7e0));
    assert(s.live.known_fnv == UINT64_C(0x847482dffb36c59c));
    assert(full_bb_mode_config_save_operation_mode(&s) == REFUSE && !s.fault);
    assert(full_bb_mode_config_saved_operation_mode(&s, &op) == REFUSE && op == UINT32_MAX);
    assert(!full_bb_mode_config_view(&s, FULL_BB_MODE_CONFIG_SNAPSHOT_TOKEN));
    dump("BB_MODE_INITIAL_VALUES", s.live.bytes, sizeof s.live.bytes);
    dump("BB_MODE_INITIAL_KNOWN", s.live.known, sizeof s.live.known);
    passed("BB_MODE_CTOR_KNOWN1565_UNKNOWN195_SOURCE_PINS_PASS");
    passed("BB_MODE_CTOR_ZERO_CANNOT_SUBSTITUTE_ACTUAL0110_PASS");
}
static void packets_and_copy(void)
{
    struct full_bb_mode_config s = {0};
    struct gate g = {0};
    struct full_bb_mode_config_view before, panel_once;
    const struct full_bb_mode_config_view *source, *copy;
    uint32_t op = UINT32_MAX;
    size_t i;
    assert(!full_bb_mode_config_init(&s)); before = s.live;
    assert(!full_bb_mode_config_apply0118(&s, panel, sizeof panel)); panel_once = s.live;
    assert(!full_bb_mode_config_apply0118(&s, panel, sizeof panel));
    assert(s.panel_updates == 2 && s.epoch == 2 && s.live.serial == 2);
    assert(!memcmp(s.live.bytes, panel_once.bytes, sizeof s.live.bytes));
    assert(!memcmp(s.live.known, panel_once.known, sizeof s.live.known));
    for (i = 0; i < sizeof s.live.bytes; i++) {
        if (i == 0x663 || i == 0x664 || i == 0x67c) assert(s.live.bytes[i] == (i == 0x663 ? 3 : 1));
        else assert(s.live.bytes[i] == before.bytes[i]);
        assert(s.live.known[i] == before.known[i]);
    }
    assert(!full_bb_mode_config_apply0110(&s, mode, sizeof mode));
    assert(s.mode_updates == 1 && s.mode_epoch == 3 && !s.saved_valid && !s.saves);
    assert(!full_bb_mode_config_save_operation_mode(&s));
    assert(!full_bb_mode_config_saved_operation_mode(&s, &op) && op == 0);
    assert(s.saved_mode_epoch == s.mode_epoch && s.saves == 1 && s.saved_valid);
    assert(full_bb_mode_config_save_operation_mode(&s) == REFUSE && !s.fault && s.saves == 1);
    before = s.live;
    assert(!snapshot(&s, &g));
    assert(g.locks == 1 && g.unlocks == 1 && !g.held && !g.saw_fault_before_unlock);
    assert(!memcmp(&s.live, &before, sizeof before));
    assert(s.copies == 1 && s.snapshot.serial == 1 && s.snapshot.source_epoch == 3);
    source = full_bb_mode_config_view(&s, FULL_BB_MODE_CONFIG_LIVE_TOKEN);
    copy = full_bb_mode_config_view(&s, FULL_BB_MODE_CONFIG_SNAPSHOT_TOKEN);
    assert(source == &s.live && copy == &s.snapshot && source != copy);
    assert(source->identity == source && copy->identity == copy);
    assert(source->token != copy->token && source->bytes != copy->bytes && source->known != copy->known);
    assert(!memcmp(source->bytes, copy->bytes, FULL_BB_MODE_CONFIG_BYTES));
    assert(!memcmp(source->known, copy->known, FULL_BB_MODE_CONFIG_BYTES));
    assert(fnv(source->bytes, sizeof source->bytes) == source->data_fnv);
    assert(fnv(copy->bytes, sizeof copy->bytes) == copy->data_fnv);
    assert(fnv(source->known, sizeof source->known) == source->known_fnv);
    assert(fnv(copy->known, sizeof copy->known) == copy->known_fnv);
    assert(count_known(copy) == 1565 && copy->bytes[0x108] == 0xa5 && !copy->known[0x108]);
    assert(!snapshot(&s, &g));
    assert(s.copies == 2 && full_bb_mode_config_view(&s, copy->token) == copy && !g.held);
    passed("BB_MODE_TWO_ACTUAL0118_IDEMPOTENT_VALUES_FRESH_SERIALS_PASS");
    passed("BB_MODE_ACTUAL0110_SAVE_DISTINCT_WORD_READBACK_PASS");
    passed("BB_MODE_SEM5_FULL1760_COPY_MASK_HASH_NO_ALIAS_PASS");
}
static void invalidation(void)
{
    struct full_bb_mode_config s = {0};
    struct gate g = {0};
    struct full_bb_mode_config_view saved, initial;
    unsigned char out[8], untouched[8];
    uint32_t op = UINT32_MAX;
    assert(!full_bb_mode_config_init(&s)); initial = s.live;
    assert(!full_bb_mode_config_apply0110(&s, mode, sizeof mode));
    assert(!full_bb_mode_config_save_operation_mode(&s));
    assert(!snapshot(&s, &g)); saved = s.snapshot;
    assert(!full_bb_mode_config_invalidate(&s));
    assert(!memcmp(s.live.bytes, initial.bytes, sizeof initial.bytes));
    assert(!memcmp(&s.snapshot, &saved, sizeof saved));
    assert(s.initialized && s.mode_updates == 1 && s.saves == 1 && !s.saved_valid);
    assert(count_known(&s.live) == 0 && s.invalidated_epoch == 2);
    memset(out, 0x7b, sizeof out); memcpy(untouched, out, sizeof out);
    assert(full_bb_mode_config_read(&s, s.live.token, 0x68, out, 4) == REFUSE);
    assert(!memcmp(out, untouched, sizeof out) && !s.fault);
    assert(full_bb_mode_config_saved_operation_mode(&s, &op) == REFUSE && op == UINT32_MAX);
    assert(full_bb_mode_config_save_operation_mode(&s) == REFUSE && !s.fault);
    assert(!full_bb_mode_config_apply0118(&s, panel, sizeof panel));
    assert(count_known(&s.live) == 41 && !s.live.known[0x68]);
    assert(full_bb_mode_config_save_operation_mode(&s) == REFUSE && !s.fault);
    assert(!full_bb_mode_config_apply0110(&s, mode, sizeof mode));
    assert(count_known(&s.live) == 45 && !s.live.known[0x190]);
    assert(!full_bb_mode_config_save_operation_mode(&s));
    assert(!full_bb_mode_config_saved_operation_mode(&s, &op) && op == 0);
    assert(!snapshot(&s, &g)); assert(count_known(&s.snapshot) == 45);
    assert(!memcmp(s.live.bytes, s.snapshot.bytes, sizeof s.live.bytes));
    assert(!memcmp(s.live.known, s.snapshot.known, sizeof s.live.known));
    assert(full_bb_mode_config_read(&s, s.snapshot.token, 0x190, out, 4) == REFUSE);
    assert(!memcmp(out, untouched, sizeof out) && !s.fault);
    assert(!full_bb_mode_config_read(&s, s.snapshot.token, 0x68, out, 4));
    assert(word(out) == 0 && s.panel_updates == 1 && s.mode_updates == 2 && s.saves == 2);
    dump("BB_MODE_INVALIDATED_COPY_VALUES", s.snapshot.bytes, sizeof s.snapshot.bytes);
    dump("BB_MODE_INVALIDATED_COPY_KNOWN", s.snapshot.known, sizeof s.snapshot.known);
    passed("BB_MODE_INVALIDATE_RETAINS_OPAQUE_BYTES_HISTORY_SNAPSHOT_PASS");
    passed("BB_MODE_UNKNOWN_READ_UNTOUCHED_THEN_ONLY_REAL_UPDATES_RESTORE_PASS");
}
static void read_boundaries(void)
{
    struct full_bb_mode_config s = {0};
    struct gate g = {0};
    unsigned char out[8], before[8];
    assert(!full_bb_mode_config_init(&s)); assert(!snapshot(&s, &g));
    memset(out, 0x5c, sizeof out); memcpy(before, out, sizeof out);
    assert(full_bb_mode_config_read(&s, s.live.token, 0x67, out, 4) == REFUSE);
    assert(full_bb_mode_config_read(&s, s.snapshot.token, 0x6df, out, 2) == REFUSE);
    assert(full_bb_mode_config_read(&s, s.snapshot.token, (size_t)-1, out, 1) == REFUSE);
    assert(full_bb_mode_config_read(&s, s.snapshot.token, 0, out, (size_t)-1) == REFUSE);
    assert(full_bb_mode_config_read(&s, s.live.token, 0x68, out, 0) == REFUSE);
    assert(full_bb_mode_config_read(&s, FULL_BB_MODE_CONFIG_SAVED_TOKEN, 0x68, out, 4) == REFUSE);
    assert(full_bb_mode_config_read(&s, s.live.token, 0x68, s.live.bytes, 4) == REFUSE);
    assert(!memcmp(out, before, sizeof out) && !s.fault);
    passed("BB_MODE_MASKED_READ_RANGES_PARTIAL_UNKNOWN_ALIAS_UNTOUCHED_PASS");
}
static void identity_and_fault(void)
{
    unsigned int which;
    for (which = 0; which < 8; which++) {
        struct full_bb_mode_config s = {0}, copied;
        unsigned char before[FULL_BB_MODE_CONFIG_BYTES];
        assert(!full_bb_mode_config_init(&s)); copied = s;
        assert(!full_bb_mode_config_view(&copied, copied.live.token));
        assert(copied.fault && !s.fault && full_bb_mode_config_init(NULL) == REFUSE);
        if (which == 0) s.live.bytes[0x68] ^= 1;
        if (which == 1) s.live.known[0x108] = 0xff;
        if (which == 2) s.snapshot.bytes[0x108] = 0;
        if (which == 3) s.live.token++;
        if (which == 4) s.mode_updates++;
        if (which == 5) s.saved_operation_mode++;
        if (which == 6) s.identity = &copied;
        if (which == 7) s.snapshot.identity = &s.live;
        memcpy(before, s.live.bytes, sizeof before);
        assert(!full_bb_mode_config_view(&s, FULL_BB_MODE_CONFIG_LIVE_TOKEN));
        assert(s.fault && !memcmp(before, s.live.bytes, sizeof before));
        assert(full_bb_mode_config_init(&s) == REFUSE);
        assert(full_bb_mode_config_apply0110(&s, mode, sizeof mode) == REFUSE);
        assert(!memcmp(before, s.live.bytes, sizeof before));
    }
    {
        struct full_bb_mode_config s = {0};
        assert(!full_bb_mode_config_init(&s));
        assert(full_bb_mode_config_init(&s) == REFUSE && s.fault);
        assert(s.initialized && count_known(&s.live) == 1565 && s.live.bytes[0x108] == 0xa5);
    }
    passed("BB_MODE_LIVE_COPY_OWNER_REJECTED_ORIGINAL_RETAINED_PASS");
    passed("BB_MODE_DATA_MASK_TOKEN_HISTORY_SEAL_TAMPER_LATCHED_PASS");
    passed("BB_MODE_DOUBLE_INIT_AND_FAULT_NEVER_RESET_PASS");
}
static void shapes(void)
{
    unsigned int which;
    for (which = 0; which < 8; which++) {
        struct full_bb_mode_config s = {0};
        struct full_bb_mode_config_view before;
        unsigned char bad[22];
        int rc;
        assert(!full_bb_mode_config_init(&s)); before = s.live;
        memcpy(bad, panel, sizeof bad);
        if (which == 0) rc = full_bb_mode_config_apply0118(&s, bad, 21);
        else if (which == 1) { bad[3] = 0; rc = full_bb_mode_config_apply0118(&s, bad, 22); }
        else if (which == 2) { bad[7] = 0; rc = full_bb_mode_config_apply0118(&s, bad, 22); }
        else if (which == 3) { bad[8] = 1; rc = full_bb_mode_config_apply0118(&s, bad, 22); }
        else {
            memcpy(bad, mode, sizeof mode);
            if (which == 4) bad[7] = 0;
            if (which == 5) bad[8] = 1;
            if (which == 6) bad[9] = 1;
            rc = full_bb_mode_config_apply0110(&s, which == 7 ? NULL : bad, sizeof mode);
        }
        assert(rc == REFUSE && s.fault && !s.epoch && !s.panel_updates && !s.mode_updates);
        assert(!memcmp(&before, &s.live, sizeof before));
        assert(full_bb_mode_config_init(&s) == REFUSE);
    }
    passed("BB_MODE_WRONG_LENGTH_0018_FLAGS_BODY_NULL_FAIL_RETAIN_PASS");
}
static void guards(void)
{
    unsigned int which;
    for (which = 0; which < 5; which++) {
        struct full_bb_mode_config s = {0};
        struct full_bb_mode_config_view before;
        struct gate g = {0};
        assert(!full_bb_mode_config_init(&s)); before = s.snapshot;
        g.fail_lock = which == 0; g.reenter_lock = which == 1;
        g.tamper = which == 2; g.fail_unlock = which == 3; g.reenter_unlock = which == 4;
        assert(snapshot(&s, &g) == REFUSE);
        assert(s.fault && !s.busy && g.locks == 1);
        if (which == 0) assert(!g.unlocks && !g.held);
        else assert(g.unlocks == 1);
        if (which == 1 || which == 2) assert(g.saw_fault_before_unlock);
        if (which < 3) assert(!s.copies && !memcmp(&before, &s.snapshot, sizeof before));
        else assert(s.copies == 1 && !memcmp(s.snapshot.known, s.live.known, sizeof s.live.known));
        if (which != 3) assert(!g.held);
        else assert(g.held); /* Parent must diagnose failed release; no fake unlocked claim. */
        assert(full_bb_mode_config_init(&s) == REFUSE);
    }
    {
        struct full_bb_mode_config s = {0};
        assert(!full_bb_mode_config_init(&s));
        assert(full_bb_mode_config_snapshot(&s, NULL) == REFUSE && s.fault && !s.copies);
    }
    passed("BB_MODE_SEM5_ACQUIRE_FAIL_NO_COPY_OR_RELEASE_PASS");
    passed("BB_MODE_SEM5_REENTRY_TAMPER_LATCH_BEFORE_RELEASE_PASS");
    passed("BB_MODE_SEM5_RELEASE_FAILURE_REENTRY_RETAIN_COPY_PASS");
    passed("BB_MODE_MISSING_SEM5_NEVER_COPY_PASS");
}
int main(void)
{
    assert(full_bb_mode_config_init(NULL) == REFUSE);
    ctor(); packets_and_copy(); invalidation(); read_boundaries();
    identity_and_fault(); shapes(); guards();
    printf("BB_MODE_CONFIG_CASES=%u\n", cases);
    return 0;
}
