/* SPDX-License-Identifier: MIT */
/* Explicit host-only source-input fixtures; these are not native CP history. */
#include "cp-start-state-data.h"
#include <assert.h>
#include <stdio.h>
#include <string.h>
#include <sys/wait.h>
#include <unistd.h>

struct fixture {
    struct cp_start_state_data owner;
    struct cp_start_state_guard guard;
    unsigned char lif[CP_START_STATE_LIF_BYTES], lm[CP_START_STATE_LIF_BYTES];
    unsigned char bank[CP_START_STATE_OVERRIDE_BYTES], bm[CP_START_STATE_OVERRIDE_BYTES];
    unsigned char merge[3], mm[3];
    struct cp_start_state_span ls, bs, ms;
};

static void setup(struct fixture *f)
{
    memset(f, 0, sizeof(*f));
    assert(cp_start_state_data_init(&f->owner) == 0);
    f->guard.owner_pid = (uint32_t)getpid();
    f->guard.source_origin = CP_START_STATE_ORIGIN_HOST_TEST;
    f->guard.quiescent = 1;
    memset(f->lm + 0x81, 1, 7);
    f->lm[0x128] = 1;
    f->bm[0x1c8] = 1;
    f->mm[0] = 1;
    f->mm[2] = 1;
    f->ls = (struct cp_start_state_span){f->lif, f->lm, sizeof(f->lif), sizeof(f->lm)};
    f->bs = (struct cp_start_state_span){f->bank, f->bm, sizeof(f->bank), sizeof(f->bm)};
    f->ms = (struct cp_start_state_span){f->merge, f->mm, sizeof(f->merge), sizeof(f->mm)};
}

static int sample(struct fixture *f, unsigned char kind, unsigned char state,
                  unsigned char subcode, uint32_t flags, unsigned char action,
                  unsigned char mode)
{
    unsigned int i;
    f->lif[0x81] = kind;
    f->lif[0x82] = state;
    f->lif[0x83] = subcode;
    for (i = 0; i < 4; ++i)
        f->lif[0x84 + i] = (unsigned char)(flags >> (8u * i));
    f->lif[0x128] = action;
    f->bank[0x1c8] = mode;
    return cp_start_state_data_consume_lif(&f->owner, &f->guard, &f->ls, &f->bs,
                                          mode == 1 ? &f->ms : NULL);
}

static void bytes3(const struct fixture *f, unsigned char a, unsigned char b,
                   unsigned char c)
{
    assert((f->owner.known_mask & 7u) == 7u);
    assert(f->owner.data[0] == a && f->owner.data[1] == b && f->owner.data[2] == c);
}

static int event(struct fixture *f, enum cp_start_state_event which,
                 const unsigned char *bytes, size_t size)
{
    unsigned char known[7];
    struct cp_start_state_span span;
    assert(size <= sizeof(known));
    memset(known, 1, sizeof(known));
    span = (struct cp_start_state_span){bytes, size ? known : NULL, size, size};
    return cp_start_state_data_consume_event(&f->owner, &f->guard, which, &span);
}

static void history(struct fixture *f, unsigned char state, uint32_t flags)
{
    unsigned int i;
    unsigned char h[7] = {0};
    h[0] = state;
    for (i = 0; i < 4; ++i)
        h[3 + i] = (unsigned char)(flags >> (8u * i));
    assert(event(f, CP_START_STATE_EVENT_HISTORY, h, sizeof(h)) == 0);
}

static int profile(struct fixture *f, unsigned char value)
{
    unsigned char p[5] = {0}, known[5] = {0, 0, 0, 0, 1};
    struct cp_start_state_span span = {p, known, sizeof(p), sizeof(known)};
    p[4] = value;
    return cp_start_state_data_consume_property(&f->owner, &f->guard,
                                               CP_START_STATE_PROPERTY_ID, &span);
}

static int adj(struct fixture *f, unsigned int index, unsigned char value)
{
    unsigned char p[0x31] = {0}, known[0x31] = {0};
    struct cp_start_state_span span = {p, known, sizeof(p), sizeof(known)};
    p[0x26] = 0xff;
    p[0x28] = (unsigned char)index;
    p[0x29] = (unsigned char)(index >> 8);
    p[0x2a] = 0x0a;
    p[0x2c] = 1;
    p[0x30] = value;
    known[0x26] = 1;
    memset(known + 0x28, 1, 9);
    return cp_start_state_data_consume_adj(&f->owner, &f->guard, &span);
}

static int read_fourth(struct fixture *f)
{
    return event(f, CP_START_STATE_EVENT_FOURTH_READ, NULL, 0);
}

static void test_unknown_and_atomic(void)
{
    struct fixture f;
    struct cp_start_state_data before;
    struct cp_start_state_readback readback;
    unsigned char out[16], untouched[16];
    size_t i;
    setup(&f);
    assert(f.owner.known_mask == 0 && f.owner.predicate_known_mask == 0);
    assert(!f.owner.previous_tuple_known && !f.owner.previous_flags_known);
    assert(cp_start_state_data_snapshot(&f.owner, &f.guard, &readback) == 0);
    assert(readback.source_origin == CP_START_STATE_ORIGIN_NONE && !readback.data_ready);
    memset(out, 0xa5, sizeof(out));
    memcpy(untouched, out, sizeof(out));
    before = f.owner;
    assert(cp_start_state_data_build_reply(&f.owner, &f.guard, 0x3003, 0, out, 16) == -ENODATA);
    assert(memcmp(out, untouched, 16) == 0 && memcmp(&before, &f.owner, sizeof(before)) == 0);
    assert(read_fourth(&f) == -ENODATA);
    assert(memcmp(&before, &f.owner, sizeof(before)) == 0);
    for (i = 0x81; i <= 0x87; ++i) {
        f.lm[i] = 0;
        assert(sample(&f, 0x62, 1, 0x32, 0x22, 3, 0) == -ENODATA);
        assert(memcmp(&before, &f.owner, sizeof(before)) == 0);
        f.lm[i] = 1;
    }
    f.lm[0x128] = 0;
    assert(sample(&f, 0x62, 1, 0x32, 0x22, 3, 0) == -ENODATA);
    f.lm[0x128] = 1;
    f.bm[0x1c8] = 0;
    assert(sample(&f, 0x62, 1, 0x32, 0x22, 3, 0) == -ENODATA);
    f.bm[0x1c8] = 1;
    /* Unknown old flags could clear this newly set bit: do not assume BSS zero. */
    assert(sample(&f, 0x60, 1, 0x32, 0, 0, 0) == -ENODATA);
    assert(memcmp(&before, &f.owner, sizeof(before)) == 0);
    assert(sample(&f, 0, 0, 0, 0, 0, 0) == 0);
    bytes3(&f, 0, 0, 0);
    assert(f.owner.known_mask == 7 && f.owner.lif_consumed);
    assert(cp_start_state_data_build_reply(&f.owner, &f.guard, 0x3000, 0, out, 16) == -ENODATA);
    assert(memcmp(out, untouched, 16) == 0);
    setup(&f);
    assert(sample(&f, 0x60, 1, 0, 0, 1, 0) == 0);
    bytes3(&f, 1, 0, 0); /* The later action resolves this earlier flags ambiguity. */
    setup(&f);
    before = f.owner;
    assert(sample(&f, 0x62, 1, 0, 0, 1, 0) == -ENODATA);
    assert(memcmp(&before, &f.owner, sizeof(before)) == 0);
    assert(sample(&f, 0x62, 1, 0, 0, 0, 2) == 0);
    bytes3(&f, 1, 1, 0); /* Mode 2 replays tuple setting after flags clear. */
}

static void test_tuple_and_flags(void)
{
    static const unsigned char kinds[] = {0x60, 0x61, 0x62, 0x00, 0xff};
    size_t i;
    for (i = 0; i < sizeof(kinds); ++i) {
        struct fixture f;
        setup(&f);
        history(&f, 0, 0);
        assert(sample(&f, kinds[i], 1, 0xff, 0, 0, 0) == 0);
        bytes3(&f, kinds[i] == 0x60 || kinds[i] == 0x62,
               kinds[i] == 0x61 || kinds[i] == 0x62, 0);
        /* 1 -> 3 retains, 3 -> 0 clears, and only source state 1 sets bits. */
        assert(sample(&f, 0, 3, 0, 0, 0, 0) == 0);
        bytes3(&f, kinds[i] == 0x60 || kinds[i] == 0x62,
               kinds[i] == 0x61 || kinds[i] == 0x62, 0);
        assert(sample(&f, 0x62, 0, 0, 0, 0, 0) == 0);
        bytes3(&f, 0, 0, 0);
        assert(sample(&f, 0x62, 2, 0, 0, 0, 0) == 0);
        bytes3(&f, 0, 0, 0);
    }
    {
        struct fixture f;
        setup(&f);
        assert(sample(&f, 0, 0, 0, 0x22, 0, 0) == 0);
        bytes3(&f, 1, 1, 0);
        assert(sample(&f, 0, 0, 0, 2, 0, 0) == 0);
        bytes3(&f, 1, 1, 0); /* Losing one bit does not clear retained cache. */
        assert(sample(&f, 0, 0, 0, 0, 0, 0) == 0);
        bytes3(&f, 0, 0, 0);
        assert(sample(&f, 0, 0, 0, UINT32_C(0x80000021), 0, 0) == 0);
        bytes3(&f, 1, 0, 0);
        assert(sample(&f, 0x62, 1, 0x32, 0, 2, 0) == 0);
        bytes3(&f, 0, 1, 0); /* Tuple bits are cleared before action sets byte 2. */
        assert(sample(&f, 0x62, 1, 0x32, 0, 0, 0) == 0);
        bytes3(&f, 1, 1, 0); /* Same tuple still sets 60/61/62 bits. */
    }
}

static void test_action_u8_and_capture(void)
{
    unsigned int action;
    for (action = 0; action < 256; ++action) {
        struct fixture f;
        unsigned char copy[CP_START_STATE_LIF_BYTES];
        setup(&f);
        history(&f, 0, 0);
        assert(sample(&f, 0, 0, 0, 0, (unsigned char)action, 2) == 0);
        bytes3(&f, action == 1, action == 2, action == 3);
        assert(f.owner.effective_action == (action >= 1 && action <= 3 ? action : 0));
        assert(f.owner.raw_action == action);
        assert(f.owner.captured_live_known && f.owner.captured_live[3] == action);
        memcpy(copy, f.lif, sizeof(copy));
        assert(cp_start_state_data_consume_lif(&f.owner, &f.guard, &f.ls, &f.bs, NULL) == 0);
        assert(memcmp(copy, f.lif, sizeof(copy)) == 0);
    }
}

static void test_override_precedence(void)
{
    static const struct {
        unsigned char kind, alt_kind, subcode, alt_subcode;
        unsigned char effective_kind, effective_state, effective_subcode, action;
    } cases[] = {
        {0x10,0x11,0,0,0x11,3,0x61,2},
        {0x11,0x62,0,0,0x11,3,0x61,2},
        {0x62,0x10,0,0x61,0x10,3,0x61,2},
        {0x10,0,0x61,0,0x10,3,0x61,2},
        {0x62,0,0x61,0,0,3,0x61,2},
        {0x62,0x60,0,0x61,0,3,0x61,2},
        {0x61,0x62,0,0,0x62,1,0x32,1},
        {0x62,0x61,0,0,0x62,1,0x32,1},
        {0x60,0x61,0,0,0x61,1,0x32,1},
        {0,0x60,0,0,0x60,1,0x32,1},
        {0xff,0xfe,0xff,0xff,0,0,0,0}
    };
    size_t i;
    for (i = 0; i < sizeof(cases) / sizeof(cases[0]); ++i) {
        struct fixture f;
        setup(&f);
        history(&f, 0, 0);
        f.merge[0] = cases[i].alt_kind;
        f.merge[2] = cases[i].alt_subcode;
        assert(sample(&f, cases[i].kind, 0, cases[i].subcode, 0, 0, 1) == 0);
        assert(f.owner.effective_kind == cases[i].effective_kind);
        assert(f.owner.effective_state == cases[i].effective_state);
        assert(f.owner.effective_subcode == cases[i].effective_subcode);
        assert(f.owner.effective_action == cases[i].action);
        if (cases[i].action == 2)
            bytes3(&f, 0, 1, 0);
        else if (cases[i].effective_kind == 0x60)
            bytes3(&f, 1, 0, 0);
        else if (cases[i].action == 1)
            bytes3(&f, 1, 1, 0);
        else
            bytes3(&f, 0, 0, 0);
    }
    {
        struct fixture f;
        struct cp_start_state_data before;
        setup(&f);
        f.merge[0] = 0x11;
        before = f.owner;
        f.mm[0] = 0;
        assert(sample(&f, 0, 0, 0, 0, 0, 1) == -ENODATA);
        f.mm[0] = 1;
        f.mm[2] = 0;
        assert(sample(&f, 0, 0, 0, 0, 0, 1) == -ENODATA);
        assert(memcmp(&before, &f.owner, sizeof(before)) == 0);
        f.mm[2] = 1;
        assert(sample(&f, 0x62, 1, 0x32, 0x22, 0, 255) == 0);
        bytes3(&f, 1, 1, 0);
        assert(f.owner.effective_kind == 0x62 && !f.owner.captured_live_known);
    }
}

static void test_fourth_source_history(void)
{
    struct fixture f;
    struct cp_start_state_data before;
    unsigned int value;
    unsigned char k;
    unsigned char q[4] = {2, 9, 0x2f, 0x13};
    setup(&f);
    assert(profile(&f, 2) == 0);
    before = f.owner;
    assert(read_fourth(&f) == -ENODATA); /* Profile alone does not invent M=0. */
    assert(memcmp(&before, &f.owner, sizeof(before)) == 0);
    assert(adj(&f, 0x80, 0) == 0);
    assert(read_fourth(&f) == 0 && f.owner.data[3] == 1);
    assert((f.owner.predicate_known_mask & 4u) == 0); /* M=0 did not write C. */
    assert(profile(&f, 1) == 0);
    assert((f.owner.known_mask & 8u) == 0 && read_fourth(&f) == -ENODATA);
    for (value = 0; value < 256; ++value) {
        k = (unsigned char)value;
        assert(event(&f, CP_START_STATE_EVENT_PREDICATE_KIND, &k, 1) == 0);
        assert(read_fourth(&f) == 0);
        assert(f.owner.data[3] == (value >= 1 && value <= 3));
    }
    assert(profile(&f, 0) == 0 && read_fourth(&f) == -ENODATA);
    assert(event(&f, CP_START_STATE_EVENT_Q_COPY, q, 4) == 0);
    assert(read_fourth(&f) == 0 && f.owner.data[3] == 1);
    assert(event(&f, CP_START_STATE_EVENT_Q_CLEAR, NULL, 0) == 0);
    assert(read_fourth(&f) == 0 && f.owner.data[3] == 0);
    /* Every other profile value follows Q, including values >127. */
    assert(profile(&f, 255) == 0);
    assert(event(&f, CP_START_STATE_EVENT_Q_COPY, q, 4) == 0);
    assert(read_fourth(&f) == 0 && f.owner.data[3] == 1);
    for (value = 0; value < 4; ++value) {
        unsigned char bad[4];
        memcpy(bad, q, 4);
        bad[value] = value == 2 ? 0x30 : 0;
        assert(event(&f, CP_START_STATE_EVENT_Q_COPY, bad, 4) == 0);
        assert(read_fourth(&f) == 0 && f.owner.data[3] == 0);
    }
    /* Source getter writes C only on M=2; property/ADJ consumption alone does not. */
    assert(adj(&f, 0x80, 2) == 0 && adj(&f, 0xb2, 0xf7) == 0);
    assert(profile(&f, 2) == 0);
    assert(f.owner.override_cache == 0xf7);
    assert(adj(&f, 0x80, 1) == 0);
    assert(read_fourth(&f) == 0 && f.owner.data[3] == 0xf7);
    assert(adj(&f, 0x80, 2) == 0);
    assert(read_fourth(&f) == 0 && f.owner.override_cache == 1);
    assert(profile(&f, 1) == 0); /* Cached C remains 1 until another getter. */
    assert(adj(&f, 0x80, 1) == 0);
    assert(read_fourth(&f) == 0 && f.owner.data[3] == 1);
    for (value = 0; value < 256; ++value) {
        assert(adj(&f, 0xb2, (unsigned char)value) == 0);
        assert(read_fourth(&f) == 0 && f.owner.data[3] == value);
    }
    setup(&f);
    assert(adj(&f, 0x80, 1) == 0 && read_fourth(&f) == -ENODATA);
    assert(adj(&f, 0xb2, 0xfe) == 0);
    assert(read_fourth(&f) == 0 && f.owner.data[3] == 0xfe);
    assert(f.owner.predicate_known_mask == 6); /* Return independent of unknown compute inputs. */
    setup(&f);
    assert(adj(&f, 0x80, 0xff) == 0 && profile(&f, 0) == 0);
    for (value = 0; value < 1024; ++value) {
        unsigned int at = value / 256, byte = value % 256;
        unsigned char candidate[4];
        memcpy(candidate, q, 4);
        candidate[at] = (unsigned char)byte;
        assert(event(&f, CP_START_STATE_EVENT_Q_COPY, candidate, 4) == 0);
        assert(read_fourth(&f) == 0);
        assert(f.owner.data[3] == (candidate[0] >= 1 && candidate[0] <= 3 &&
            candidate[1] == 9 && (candidate[2] & 0xf0u) == 0x20 && candidate[3] == 0x13));
    }
}

static void test_packet_and_event_errors(void)
{
    struct fixture f;
    struct cp_start_state_data before;
    unsigned char p[0x32] = {0}, known[0x32];
    struct cp_start_state_span s = {p, known, 0x31, sizeof(known)};
    size_t i;
    setup(&f);
    memset(known, 1, sizeof(known));
    p[0x26] = 0xff; p[0x28] = 0x80; p[0x2a] = 0x0a; p[0x2c] = 1;
    before = f.owner;
    for (i = 0x28; i <= 0x30; ++i) {
        known[i] = 0;
        assert(cp_start_state_data_consume_adj(&f.owner, &f.guard, &s) == -ENODATA);
        assert(memcmp(&before, &f.owner, sizeof(before)) == 0);
        known[i] = 1;
    }
    known[0x26] = 0;
    assert(cp_start_state_data_consume_adj(&f.owner, &f.guard, &s) == -ENODATA);
    known[0x26] = 1;
    for (i = 0; i < 5; ++i) {
        size_t at[] = {0x26, 0x28, 0x2a, 0x2b, 0x2c};
        unsigned char save = p[at[i]];
        p[at[i]] = 0x77;
        assert(cp_start_state_data_consume_adj(&f.owner, &f.guard, &s) == -ENOTSUP);
        assert(memcmp(&before, &f.owner, sizeof(before)) == 0);
        p[at[i]] = save;
    }
    p[0x2c] = 2;
    s.size = sizeof(p);
    assert(cp_start_state_data_consume_adj(&f.owner, &f.guard, &s) == -ENOTSUP);
    p[0x2c] = 1; s.size = 0x31;
    known[0] = 2;
    assert(cp_start_state_data_consume_adj(&f.owner, &f.guard, &s) == -EINVAL);
    known[0] = 1;
    s.size = 4;
    assert(cp_start_state_data_consume_property(&f.owner, &f.guard,
                                               CP_START_STATE_PROPERTY_ID, &s) == -EMSGSIZE);
    s.size = 5; known[4] = 0;
    assert(cp_start_state_data_consume_property(&f.owner, &f.guard,
                                               CP_START_STATE_PROPERTY_ID, &s) == -ENODATA);
    known[4] = 1;
    assert(cp_start_state_data_consume_property(&f.owner, &f.guard, 0, &s) == -ENOTSUP);
    assert(event(&f, (enum cp_start_state_event)255, NULL, 0) == -ENOTSUP);
    assert(event(&f, CP_START_STATE_EVENT_Q_COPY, p, 3) == -EMSGSIZE);
    s.size = 4; known[2] = 0;
    assert(cp_start_state_data_consume_event(&f.owner, &f.guard,
                                           CP_START_STATE_EVENT_Q_COPY, &s) == -ENODATA);
    assert(memcmp(&before, &f.owner, sizeof(before)) == 0);
}

static void test_guard_range_and_alias(void)
{
    struct fixture f;
    struct cp_start_state_data before;
    struct cp_start_state_readback readback, untouched;
    struct cp_start_state_span bad;
    struct cp_start_state_guard g;
    unsigned char aligned_storage[sizeof(struct cp_start_state_data) + 16];
    unsigned char *unaligned;
    pid_t child;
    int status;
    setup(&f);
    unaligned = aligned_storage;
    while ((uintptr_t)unaligned % _Alignof(struct cp_start_state_data) != 0)
        ++unaligned;
    ++unaligned;
    assert(cp_start_state_data_init((struct cp_start_state_data *)unaligned) == -EINVAL);
    assert(cp_start_state_data_init(NULL) == -EINVAL);
    assert(cp_start_state_data_snapshot(NULL, &f.guard, &readback) == -EINVAL);
    assert(cp_start_state_data_snapshot(&f.owner, NULL, &readback) == -EINVAL);
    assert(cp_start_state_data_snapshot(&f.owner, &f.guard,
        (struct cp_start_state_readback *)unaligned) == -EINVAL);
    assert(cp_start_state_data_snapshot(&f.owner,
        (const struct cp_start_state_guard *)unaligned, &readback) == -EINVAL);
    assert(cp_start_state_data_consume_lif(&f.owner, &f.guard,
        (const struct cp_start_state_span *)unaligned, &f.bs, NULL) == -EINVAL);
    memset(&readback, 0x5a, sizeof(readback));
    untouched = readback;
    before = f.owner;
    g = f.guard; g.quiescent = 0;
    assert(cp_start_state_data_snapshot(&f.owner, &g, &readback) == -EAGAIN);
    g = f.guard; g.sequence_after = 2;
    assert(cp_start_state_data_snapshot(&f.owner, &g, &readback) == -EAGAIN);
    g.sequence_before = 1; g.sequence_after = 1;
    assert(cp_start_state_data_snapshot(&f.owner, &g, &readback) == -EAGAIN);
    g = f.guard; g.owner_pid++;
    assert(cp_start_state_data_snapshot(&f.owner, &g, &readback) == -EXDEV);
    g = f.guard; g.source_origin = CP_START_STATE_ORIGIN_NONE;
    assert(cp_start_state_data_snapshot(&f.owner, &g, &readback) == -EINVAL);
    assert(memcmp(&readback, &untouched, sizeof(readback)) == 0);
    f.lm[0] = 2;
    assert(sample(&f, 0, 0, 0, 0, 0, 0) == -EINVAL);
    f.lm[0] = 0;
    bad = f.ls; bad.known_size--;
    assert(cp_start_state_data_consume_lif(&f.owner, &f.guard, &bad, &f.bs, NULL) == -EINVAL);
    bad = f.ls; bad.known_size = UINTPTR_MAX;
    assert(cp_start_state_data_consume_lif(&f.owner, &f.guard, &bad, &f.bs, NULL) == -EINVAL);
    bad = f.ls; bad.size--;
    assert(cp_start_state_data_consume_lif(&f.owner, &f.guard, &bad, &f.bs, NULL) == -EMSGSIZE);
    bad = f.ls; bad.bytes = (const unsigned char *)(uintptr_t)(UINTPTR_MAX - 8u);
    assert(cp_start_state_data_consume_lif(&f.owner, &f.guard, &bad, &f.bs, NULL) == -EINVAL);
    bad = f.ls; bad.bytes = (const unsigned char *)&f.owner;
    assert(cp_start_state_data_consume_lif(&f.owner, &f.guard, &bad, &f.bs, NULL) == -EINVAL);
    bad = f.ls; bad.known = (const unsigned char *)&f.owner;
    assert(cp_start_state_data_consume_lif(&f.owner, &f.guard, &bad, &f.bs, NULL) == -EINVAL);
    assert(cp_start_state_data_consume_lif(&f.owner, &f.guard,
        (const struct cp_start_state_span *)&f.owner, &f.bs, NULL) == -EINVAL);
    assert(cp_start_state_data_snapshot(&f.owner,
        (const struct cp_start_state_guard *)&f.owner, &readback) == -EINVAL);
    assert(cp_start_state_data_snapshot(&f.owner, &f.guard,
        (struct cp_start_state_readback *)&f.owner) == -EINVAL);
    assert(cp_start_state_data_consume_lif(&f.owner, &f.guard, NULL, &f.bs, NULL) == -EINVAL);
    assert(cp_start_state_data_consume_lif(&f.owner, &f.guard, &f.ls, NULL, NULL) == -EINVAL);
    assert(cp_start_state_data_consume_lif(&f.owner, &f.guard, &f.ls, &f.bs, &f.ms) == -EINVAL);
    f.bank[0x1c8] = 1;
    assert(cp_start_state_data_consume_lif(&f.owner, &f.guard, &f.ls, &f.bs, NULL) == -EINVAL);
    f.bank[0x1c8] = 0;
    assert(memcmp(&before, &f.owner, sizeof(before)) == 0);
    child = fork();
    assert(child >= 0);
    if (child == 0) {
        int rc = cp_start_state_data_snapshot(&f.owner, &f.guard, &readback);
        _exit(rc == -EXDEV ? 0 : 1);
    }
    assert(waitpid(child, &status, 0) == child && WIFEXITED(status) && WEXITSTATUS(status) == 0);
    f.guard.sequence_before = 2; f.guard.sequence_after = 2;
    assert(sample(&f, 0, 0, 0, 0, 0, 0) == 0);
    g = f.guard; g.sequence_before = 0; g.sequence_after = 0;
    assert(cp_start_state_data_snapshot(&f.owner, &g, &readback) == -ESTALE);
    g.sequence_before = 4; g.sequence_after = 4;
    assert(cp_start_state_data_snapshot(&f.owner, &g, &readback) == -ESTALE);
    g = f.guard; g.source_origin = CP_START_STATE_ORIGIN_VIRTUAL_SOURCE;
    assert(cp_start_state_data_snapshot(&f.owner, &g, &readback) == -EXDEV);
    before = f.owner;
    f.guard.sequence_before = 0; f.guard.sequence_after = 0;
    assert(sample(&f, 0, 0, 0, 0, 0, 0) == -ESTALE);
    assert(memcmp(&before, &f.owner, sizeof(before)) == 0);
    f.guard.sequence_before = 2; f.guard.sequence_after = 2;
    f.owner.revision = UINT64_MAX;
    assert(sample(&f, 0, 0, 0, 0, 0, 0) == -EOVERFLOW);
}

static void test_span_overlap_contract(void)
{
    struct fixture f;
    struct {
        unsigned char mask[CP_START_STATE_LIF_BYTES];
        struct cp_start_state_data owner;
    } storage;
    struct cp_start_state_span source;
    struct cp_start_state_data before;
    unsigned char shared[CP_START_STATE_LIF_BYTES], copy[CP_START_STATE_LIF_BYTES];
    setup(&f);
    assert(cp_start_state_data_init(&storage.owner) == 0);
    memset(storage.mask, 0, sizeof(storage.mask));
    source = f.ls;
    source.known = storage.mask;
    source.known_size = sizeof(storage);
    before = storage.owner;
    assert(cp_start_state_data_consume_lif(&storage.owner, &f.guard,
                                           &source, &f.bs, NULL) == -EINVAL);
    assert(memcmp(&before, &storage.owner, sizeof(before)) == 0);
    /* Two read-only inputs can alias; all-one bytes are valid raw source data. */
    memset(shared, 1, sizeof(shared));
    memcpy(copy, shared, sizeof(copy));
    source = (struct cp_start_state_span){shared, shared, sizeof(shared), sizeof(shared)};
    assert(cp_start_state_data_consume_lif(&f.owner, &f.guard, &source, &f.bs, NULL) == 0);
    assert(memcmp(copy, shared, sizeof(copy)) == 0);
    bytes3(&f, 1, 0, 0);
    /* Mask capacity tails are range checked but do not require logical 0/1. */
    {
        unsigned char property[5] = {0, 0, 0, 0, 2};
        unsigned char known[6] = {0, 0, 0, 0, 1, 0xff};
        struct cp_start_state_span p = {property, known, sizeof(property), sizeof(known)};
        assert(cp_start_state_data_consume_property(&f.owner, &f.guard,
                                                   CP_START_STATE_PROPERTY_ID, &p) == 0);
    }
}

static void test_complete_reply(void)
{
    struct fixture f;
    struct cp_start_state_readback r;
    struct cp_start_state_data before;
    unsigned char reply[16], untouched[16];
    unsigned char expected[16] = {1, 0, 3, 0x30, 0x78, 0x56, 0x34, 0x12,
                                  0, 0xf0, 0, 0, 1, 1, 1, 0xe7};
    setup(&f);
    assert(sample(&f, 0x62, 1, 0x32, 0x22, 3, 2) == 0);
    assert(adj(&f, 0x80, 1) == 0);
    assert(adj(&f, 0xb2, 0xe7) == 0);
    assert(read_fourth(&f) == 0);
    assert(cp_start_state_data_snapshot(&f.owner, &f.guard, &r) == 0);
    assert(r.known_mask == 15 && r.data_ready && r.snapshot_copied);
    assert(r.source_origin == CP_START_STATE_ORIGIN_HOST_TEST && r.lif_consumed && r.adj_consumed);
    assert(!r.business_ready && !r.configuration_ready && !r.published && !r.ap_applied);
    assert(r.publication_generation == 0);
    before = f.owner;
    assert(cp_start_state_data_build_reply(&f.owner, &f.guard, 0x3003,
                                           UINT32_C(0x12345678), reply, 16) == 0);
    assert(memcmp(reply, expected, 16) == 0);
    expected[2] = 0;
    assert(cp_start_state_data_build_reply(&f.owner, &f.guard, 0x3000,
                                           UINT32_C(0x12345678), reply, 16) == 0);
    assert(memcmp(reply, expected, 16) == 0 && memcmp(&before, &f.owner, sizeof(before)) == 0);
    memset(reply, 0x6c, sizeof(reply)); memcpy(untouched, reply, sizeof(reply));
    assert(cp_start_state_data_build_reply(&f.owner, &f.guard, 0x3004, 0, reply, 16) == -ENOTSUP);
    assert(cp_start_state_data_build_reply(&f.owner, &f.guard, 0x3003, 0, reply, 15) == -EMSGSIZE);
    assert(cp_start_state_data_build_reply(&f.owner, &f.guard, 0x3003, 0,
                                           (unsigned char *)&f.owner, 16) == -EINVAL);
    assert(cp_start_state_data_build_reply(&f.owner, &f.guard, 0x3003, 0,
                                           (unsigned char *)&f.guard, 16) == -EINVAL);
    assert(memcmp(reply, untouched, 16) == 0 && memcmp(&before, &f.owner, sizeof(before)) == 0);
    assert(adj(&f, 0xb2, 0) == 0); /* Even zero input invalidates the prior getter. */
    assert(cp_start_state_data_build_reply(&f.owner, &f.guard, 0x3003, 0, reply, 16) == -ENODATA);
    assert(read_fourth(&f) == 0);
    assert(cp_start_state_data_build_reply(&f.owner, &f.guard, 0x3003, 0, reply, 16) == 0);
    assert(reply[15] == 0);
}

int main(void)
{
    test_unknown_and_atomic();
    test_tuple_and_flags();
    test_action_u8_and_capture();
    test_override_precedence();
    test_fourth_source_history();
    test_packet_and_event_errors();
    test_guard_range_and_alias();
    test_span_overlap_contract();
    test_complete_reply();
    puts("host_source_inputs_consumed=1 reply_built=1 native_history=0 publication=0 ap_applied=0");
    return 0;
}
