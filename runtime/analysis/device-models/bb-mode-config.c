/* SPDX-License-Identifier: MIT */
#include "bb-mode-config.h"
#include <string.h>

#define FNV_START UINT64_C(0xcbf29ce484222325)
#define FNV_PRIME UINT64_C(0x100000001b3)
#define REFUSE (-1021)
static const struct { unsigned int offset, length, value; } initial[] = {
#include "bb-mode-config-init.inc"
};
static uint64_t hash(const void *data, size_t bytes)
{
    const unsigned char *p = data;
    uint64_t value = FNV_START;
    while (bytes--) value = (value ^ *p++) * FNV_PRIME;
    return value;
}
static uint64_t seal(const struct full_bb_mode_config *s)
{
    return hash(s, offsetof(struct full_bb_mode_config, seal));
}
static int fail(struct full_bb_mode_config *s)
{
    if (s) { s->fault = 1; s->seal = seal(s); }
    return REFUSE;
}
static int intact(const struct full_bb_mode_config *s)
{
    return s && s->identity == s && s->initialized == 1 && !s->fault &&
        s->live.identity == &s->live && s->snapshot.identity == &s->snapshot &&
        s->live.token == FULL_BB_MODE_CONFIG_LIVE_TOKEN &&
        s->snapshot.token == FULL_BB_MODE_CONFIG_SNAPSHOT_TOKEN && s->seal == seal(s);
}
static int ready(struct full_bb_mode_config *s)
{
    return intact(s) && !s->busy ? 0 : fail(s);
}
static int overlaps(const void *p, size_t n, const void *q, size_t m)
{
    uintptr_t a = (uintptr_t)p, b = (uintptr_t)q;
    return n && m && (a <= b ? b - a < n : a - b < m);
}
static uint32_t le32(const unsigned char *p)
{
    return (uint32_t)p[0] | (uint32_t)p[1] << 8 |
           (uint32_t)p[2] << 16 | (uint32_t)p[3] << 24;
}
static int all_known(const struct full_bb_mode_config_view *v, size_t off, size_t n)
{
    size_t i;
    if (!n || off >= FULL_BB_MODE_CONFIG_BYTES || n > FULL_BB_MODE_CONFIG_BYTES - off) return 0;
    for (i = 0; i < n; i++) if (v->known[off + i] != 0xff) return 0;
    return 1;
}
static void fingerprint(struct full_bb_mode_config_view *v)
{
    v->data_fnv = hash(v->bytes, sizeof v->bytes);
    v->known_fnv = hash(v->known, sizeof v->known);
}
static void commit_live(struct full_bb_mode_config *s)
{
    s->live.serial = s->live.source_epoch = ++s->epoch;
    fingerprint(&s->live);
    s->seal = seal(s);
}
static int packet(struct full_bb_mode_config *s, const void *raw, size_t bytes,
                  const unsigned char *expected, size_t wanted)
{
    if (ready(s)) return REFUSE;
    if (!raw || bytes != wanted || overlaps(raw, bytes, s, sizeof *s) ||
        memcmp(raw, expected, wanted) || s->epoch == UINT64_MAX) return fail(s);
    return 0;
}
int full_bb_mode_config_init(struct full_bb_mode_config *s)
{
    size_t i, j, count = 0;
    const unsigned char *old = (const unsigned char *)s;
    if (!s) return REFUSE;
    for (i = 0; i < sizeof *s; i++) if (old[i]) return fail(s);
    s->identity = s; s->initialized = 1;
    s->live.identity = &s->live; s->snapshot.identity = &s->snapshot;
    s->live.token = FULL_BB_MODE_CONFIG_LIVE_TOKEN;
    s->snapshot.token = FULL_BB_MODE_CONFIG_SNAPSHOT_TOKEN;
    memset(s->live.bytes, 0xa5, sizeof s->live.bytes);
    memset(s->snapshot.bytes, 0xa5, sizeof s->snapshot.bytes);
    for (i = 0; i < sizeof initial / sizeof *initial; i++) {
        unsigned int off = initial[i].offset, n = initial[i].length;
        if (!n || off >= FULL_BB_MODE_CONFIG_BYTES || n > FULL_BB_MODE_CONFIG_BYTES - off ||
            initial[i].value > 0xff) return fail(s);
        for (j = 0; j < n; j++) {
            if (s->live.known[off + j]) return fail(s);
            s->live.bytes[off + j] = (unsigned char)initial[i].value;
            s->live.known[off + j] = 0xff; count++;
        }
    }
    fingerprint(&s->live); fingerprint(&s->snapshot);
    if (count != FULL_BB_MODE_CONFIG_INITIAL_KNOWN ||
        s->live.data_fnv != UINT64_C(0x2b36ad636500d7e0) ||
        s->live.known_fnv != UINT64_C(0x847482dffb36c59c)) return fail(s);
    s->seal = seal(s);
    return 0;
}
int full_bb_mode_config_invalidate(struct full_bb_mode_config *s)
{
    if (ready(s)) return REFUSE;
    if (s->epoch == UINT64_MAX) return fail(s);
    memset(s->live.known, 0, sizeof s->live.known);
    s->invalidated_epoch = s->epoch + 1; s->saved_valid = 0;
    commit_live(s);
    return 0;
}
int full_bb_mode_config_apply0118(struct full_bb_mode_config *s, const void *raw, size_t bytes)
{
    /* Public CP 1c1128; exact observed bit0/bit1 update subset, not ADF Output. */
    static const unsigned char expected[22] = {
        0x0d,0x20,0x18,0x01,0x16,0,1,0x80,3,1,0,0,0,0,0,0,0,0,0,0,1,0
    };
    static const struct { unsigned int offset, source, length; } fields[] = {
        {0x663,8,1}, {0x664,9,4}, {0x668,10,4}, {0x66c,11,4}, {0x670,17,4},
        {0x674,18,4}, {0x678,19,4}, {0x67c,20,4}, {0x680,21,4}, {0x298,15,4}, {0x2a0,13,4}
    };
    const unsigned char *p = raw;
    size_t i, j;
    if (packet(s, raw, bytes, expected, sizeof expected)) return REFUSE;
    if (s->panel_updates == UINT64_MAX) return fail(s);
    for (i = 0; i < sizeof fields / sizeof *fields; i++) {
        unsigned int off = fields[i].offset, n = fields[i].length;
        for (j = 0; j < n; j++) {
            s->live.bytes[off + j] = j ? 0 : p[fields[i].source];
            s->live.known[off + j] = 0xff;
        }
        if (!all_known(&s->live, off, n) ||
            (n == 1 ? s->live.bytes[off] : le32(s->live.bytes + off)) != p[fields[i].source])
            return fail(s);
    }
    s->panel_updates++; commit_live(s);
    return 0;
}
int full_bb_mode_config_apply0110(struct full_bb_mode_config *s, const void *raw, size_t bytes)
{
    static const unsigned char expected[10] = {0x0d,0x20,0x10,1,10,0,1,0x80,0,0};
    const unsigned char *p = raw;
    if (packet(s, raw, bytes, expected, sizeof expected)) return REFUSE;
    if (s->mode_updates == UINT64_MAX) return fail(s);
    /* CP 699ba6 reads byte+8, 699bb4 stores its zero-extended u32 at live+68. */
    s->live.bytes[0x68] = p[8];
    memset(s->live.bytes + 0x69, 0, 3); memset(s->live.known + 0x68, 0xff, 4);
    if (!all_known(&s->live, 0x68, 4) || le32(s->live.bytes + 0x68) != p[8]) return fail(s);
    s->mode_updates++; s->mode_epoch = s->epoch + 1; s->saved_valid = 0;
    commit_live(s);
    return 0;
}
int full_bb_mode_config_save_operation_mode(struct full_bb_mode_config *s)
{
    if (ready(s)) return REFUSE;
    if (!s->mode_updates || s->mode_epoch <= s->invalidated_epoch ||
        s->mode_epoch <= s->saved_mode_epoch || !all_known(&s->live, 0x68, 4)) return REFUSE;
    if (s->saves == UINT64_MAX) return fail(s);
    /* CP 1c1e8c -> 6986e6 publishes the independently owned 17890fc word. */
    s->saved_operation_mode = le32(s->live.bytes + 0x68);
    s->saved_mode_epoch = s->mode_epoch; s->saved_valid = 1; s->saves++;
    s->seal = seal(s);
    return 0;
}
int full_bb_mode_config_saved_operation_mode(struct full_bb_mode_config *s, uint32_t *out)
{
    if (ready(s)) return REFUSE;
    if (!out || overlaps(out, sizeof *out, s, sizeof *s) || !s->saved_valid ||
        s->saved_mode_epoch != s->mode_epoch || s->saved_mode_epoch <= s->invalidated_epoch)
        return REFUSE;
    *out = s->saved_operation_mode;
    return 0;
}
int full_bb_mode_config_snapshot(struct full_bb_mode_config *s,
                                 const struct full_bb_mode_config_sem5 *sem5)
{
    struct full_bb_mode_config_sem5 ops;
    int copied = 0, unlocked;
    if (ready(s)) return REFUSE;
    if (!sem5 || !sem5->lock || !sem5->unlock || s->copies == UINT64_MAX) return fail(s);
    ops = *sem5;
    s->busy = 1; s->seal = seal(s);
    if (ops.lock(ops.context)) {
        fail(s); s->busy = 0; s->seal = seal(s);
        return REFUSE;
    }
    if (intact(s) && s->busy == 1) {
        /* CP 1aadfa: size 6e0. Opaque unknown bytes keep their physical payload. */
        memcpy(s->snapshot.bytes, s->live.bytes, sizeof s->snapshot.bytes);
        memcpy(s->snapshot.known, s->live.known, sizeof s->snapshot.known);
        fingerprint(&s->live); fingerprint(&s->snapshot);
        if (s->live.data_fnv == s->snapshot.data_fnv && s->live.known_fnv == s->snapshot.known_fnv &&
            !memcmp(s->live.bytes, s->snapshot.bytes, sizeof s->live.bytes) &&
            !memcmp(s->live.known, s->snapshot.known, sizeof s->live.known)) {
            s->snapshot.serial = ++s->copies; s->snapshot.source_epoch = s->live.source_epoch;
            copied = 1; s->seal = seal(s);
        }
    }
    if (!copied) fail(s); /* Latch before releasing sem5, including reentrant/tampered acquisition. */
    unlocked = ops.unlock(ops.context);
    if (unlocked || !intact(s) || s->busy != 1) fail(s);
    s->busy = 0; s->seal = seal(s);
    return s->fault ? REFUSE : 0;
}
const struct full_bb_mode_config_view *full_bb_mode_config_view(
    struct full_bb_mode_config *s, uint32_t token)
{
    if (ready(s)) return NULL;
    if (token == FULL_BB_MODE_CONFIG_LIVE_TOKEN) return &s->live;
    if (token == FULL_BB_MODE_CONFIG_SNAPSHOT_TOKEN && s->copies) return &s->snapshot;
    return NULL;
}
int full_bb_mode_config_read(struct full_bb_mode_config *s, uint32_t token,
                             size_t offset, void *out, size_t bytes)
{
    const struct full_bb_mode_config_view *v = full_bb_mode_config_view(s, token);
    if (!v || !out || overlaps(out, bytes, s, sizeof *s) || !all_known(v, offset, bytes)) return REFUSE;
    memcpy(out, v->bytes + offset, bytes);
    return 0;
}
