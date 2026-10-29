/* SPDX-License-Identifier: MIT */
#include "lif-cache.h"
#include <assert.h>
#include <errno.h>
#include <stddef.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/wait.h>
#include <unistd.h>

static unsigned char *stage_bytes;
static unsigned decode_calls;
int __real_cp_lif_bitmap_receive_decode(struct cp_lif_bitmap_owner *, const unsigned char *,
    size_t, const struct cp_lif_bitmap_guard *, struct cp_lif_bitmap_received *, size_t);
int __wrap_cp_lif_bitmap_receive_decode(struct cp_lif_bitmap_owner *b, const unsigned char *rx,
    size_t n, const struct cp_lif_bitmap_guard *g, struct cp_lif_bitmap_received *out, size_t cap)
{
    ++decode_calls;
    return __real_cp_lif_bitmap_receive_decode(b, rx, n, g, out, cap);
}
struct environment {
    struct lif_cache_owner cache;
    struct lif_cache_handle cap_tail_out;
    struct lif_capabilities_owner capabilities;
    struct cp_lif_bitmap_owner bitmap;
    _Alignas(16) unsigned char pool[32768];
    unsigned char rx[CP_LIF_FRAME_MAX_RX_BYTES];
    size_t n;
};
static struct cp_lif_bitmap_guard guard(uint64_t sequence)
{
    struct cp_lif_bitmap_guard g;
    memset(&g, 0, sizeof(g)); g.owner_pid = (uint32_t)getpid();
    g.origin = CP_LIF_ORIGIN_HOST_TEST; g.quiescent = 1;
    g.sequence_before = g.sequence_after = sequence;
    return g;
}
static void put16(unsigned char *p, size_t v)
{ p[0] = (unsigned char)v; p[1] = (unsigned char)(v >> 8); }
static size_t get16(const unsigned char *p) { return p[0] | (size_t)p[1] << 8; }
static void checksum(unsigned char *rx)
{
    size_t i, length = get16(rx + 1), sum = 0;
    for (i = 1; i < length - 3; ++i) sum += rx[i];
    put16(rx + length - 3, sum);
}
static size_t fixed(unsigned char *rx, unsigned command, unsigned kind)
{
    size_t body = command == 1 ? 33 : command == 7 ? 35 : command == 8 ? 202 :
        command == 9 ? LIF_CAPABILITIES_HANDSHAKE_BODY_BYTES : 64;
    size_t n = body + 8;
    memset(rx, 0, CP_LIF_FRAME_MAX_RX_BYTES);
    rx[0] = 0xf0; put16(rx + 1, n); rx[3] = 2; rx[4] = 0xd1; rx[5] = (unsigned char)command;
    if (command == 1) {
        memset(rx + 6, 0xff, 32);
        rx[5 + 9] &= (unsigned char)~4u; /* Actual S43 false; public gate byte stays unknown. */
    }
    if (command == 7) { rx[6] = (unsigned char)kind; put16(rx + 15, 0x4123); }
    rx[n - 1] = 0x55; checksum(rx);
    return n;
}
static void setup_source(struct environment *e, unsigned kind, size_t pool_capacity,
    int consumed, int handshake_reset)
{
    static const unsigned commands[] = {1, 7, 8, 0x3d};
    struct cp_property_stage stage;
    struct cp_start_state_guard sg;
    struct cp_lif_bitmap_guard g;
    struct cp_lif_bitmap_inputs input;
    struct cp_lif_bitmap_lease lease;
    unsigned char actual[CP_LIF_BITMAP_WIRE_BYTES];
    size_t i;
    memset(e, 0, sizeof(*e)); memset(e->pool, 0xc7, sizeof(e->pool));
    memset(&sg, 0, sizeof(sg)); sg.owner_pid = (uint32_t)getpid();
    sg.sequence_before = sg.sequence_after = 2;
    sg.source_origin = CP_START_STATE_ORIGIN_HOST_TEST; sg.quiescent = 1;
    assert(cp_property_stage_init(&stage) == 0);
    assert(cp_property_stage_consume(&stage, &sg, CP_PROPERTY_STAGE_SOURCE_CP_INITIAL_STAGE,
        stage_bytes, CP_PROPERTY_STAGE_BYTES) == 0);
    assert(stage.value.context[0x17] == 0 && stage.value.context[0x20] == 1);
    assert(lif_capabilities_init(&e->capabilities, &stage, &sg, 1) == 0);
    if (handshake_reset) {
        g = guard(4); assert(lif_capabilities_consume_handshake_reset_store(&e->capabilities, &g) == 0);
    }
    for (i = 0; i < 4; ++i) {
        e->n = fixed(e->rx, commands[i], kind ? kind : 1);
        g = guard(6 + 2 * i);
        assert(lif_capabilities_receive(&e->capabilities, e->rx, e->n, &g) == 0);
    }
    g = guard(14);
    if (kind) assert(lif_capabilities_consume_initial_kind_store(&e->capabilities, &g) == 0);
    else assert(lif_capabilities_consume_handshake_reset_store(&e->capabilities, &g) == 0);
    assert(lif_capabilities_export_bitmap(&e->capabilities, &g, &input, sizeof(input)) == 0);
    assert(input.known == 31 && input.z == 0 && input.k == (kind == 1 ? 4u : kind == 2 ? 1u : 0u));
    assert(cp_lif_bitmap_owner_init(&e->bitmap, &g) == 0);
    g = guard(16); assert(cp_lif_bitmap_request(&e->bitmap, 1, &input, &g, &lease, sizeof(lease)) == 0);
    memcpy(actual, lease.wire, sizeof(actual));
    if (consumed) {
        g = guard(18);
        assert(cp_lif_bitmap_observe_transport_consumed(&e->bitmap, &lease, actual, sizeof(actual), &g) == 0);
    }
    g = guard(2); errno = EDOM;
    assert(lif_cache_init(&e->cache, e->pool, pool_capacity, &g) == 0 && errno == EDOM);
    g = guard(4); assert(lif_cache_consume_reset_and_prime(&e->cache, &g) == 0);
}
static void setup(struct environment *e, unsigned kind, size_t pool_capacity, int consumed)
{ setup_source(e, kind, pool_capacity, consumed, 1); }
static const unsigned char schema5[] = {8,1,8,3,10,28,2,6,1,2,8,6,6,6,1,6,3,3,4,4,4,8,36,40,8,4,6,3};
static const unsigned char schema6[] = {2,11,9,4,6,7,45,4,8,8,24};
static void dynamic(struct environment *e, unsigned first, unsigned second, unsigned opaque, int extra)
{
    unsigned commands[2] = {first, second};
    size_t pos = 5, c, i, j;
    memset(e->rx, 0x6b, sizeof(e->rx)); e->rx[0] = 0xf0; e->rx[3] = 0xba;
    e->rx[4] = (unsigned char)opaque;
    for (c = 0; c < 2 && commands[c]; ++c) {
        const unsigned char *schema = commands[c] == 5 ? schema5 : schema6;
        size_t count = commands[c] == 5 ? sizeof(schema5) : sizeof(schema6);
        unsigned base = commands[c] == 5 ? 0 : 0x40;
        e->rx[pos++] = (unsigned char)commands[c];
        for (i = 0; i < count; ++i) if (e->bitmap.configured[(base + i) >> 3] & (1u << ((base + i) & 7)))
            for (j = 0; j < schema[i]; ++j) {
                e->rx[pos] = (unsigned char)(1 + (pos + i + j) % 250); ++pos;
            }
    }
    put16(e->rx + 1, pos + 3); e->rx[pos + 2] = 0x55; e->rx[pos + 3] = 0;
    checksum(e->rx); e->n = pos + 3 + (size_t)extra;
}
static struct cp_lif_bitmap_guard mutation(const struct environment *e)
{
    uint64_t seq = e->cache.value.sequence;
    if (seq < e->bitmap.sequence) seq = e->bitmap.sequence;
    if (seq < e->capabilities.value.sequence) seq = e->capabilities.value.sequence;
    return guard(seq + 2);
}
static struct lif_cache_ingress ingress(unsigned token)
{
    struct lif_cache_ingress in;
    memset(&in, 0, sizeof(in)); in.token = (unsigned char)token;
    in.metadata8 = UINT32_C(0x73625140); in.metadata10 = UINT32_C(0xd5c4b3a2);
    return in;
}
static struct lif_cache_handle accept(struct environment *e, unsigned token)
{
    struct lif_capabilities_owner before;
    struct cp_lif_bitmap_guard cg = guard(e->capabilities.value.sequence), g = mutation(e);
    struct lif_cache_ingress in = ingress(token);
    struct lif_cache_handle h;
    unsigned char rx_before[CP_LIF_FRAME_MAX_RX_BYTES];
    unsigned calls = decode_calls;
    memcpy(&before, &e->capabilities, sizeof(before)); memcpy(rx_before, e->rx, sizeof(rx_before));
    errno = EILSEQ;
    assert(lif_cache_receive(&e->cache, &e->capabilities, &cg, &e->bitmap, e->rx, e->n,
        &in, &g, &h, sizeof(h)) == 0 && errno == EILSEQ);
    assert(decode_calls == calls + 1 && e->bitmap.sequence == g.sequence_before);
    assert(e->cache.value.sequence == g.sequence_before);
    assert(memcmp(&before, &e->capabilities, sizeof(before)) == 0);
    assert(memcmp(rx_before, e->rx, sizeof(rx_before)) == 0);
    assert(h.incarnation && h.slot < 64);
    assert(e->cache.value.records[h.slot].admitted_owned_frame);
    return h;
}
static void reject(struct environment *e, struct cp_lif_bitmap_guard cg,
    struct cp_lif_bitmap_guard g, int expected, unsigned calls_expected)
{
    struct environment before;
    struct lif_cache_ingress in = ingress(0x19), prior_in;
    struct lif_cache_handle h, prior_h;
    struct cp_lif_bitmap_guard prior_cg, prior_g;
    unsigned calls = decode_calls;
    memcpy(&prior_cg, &cg, sizeof(cg)); memcpy(&prior_g, &g, sizeof(g));
    memcpy(&before, e, sizeof(before)); memcpy(&prior_in, &in, sizeof(in));
    memset(&h, 0xe7, sizeof(h)); memcpy(&prior_h, &h, sizeof(h)); errno = ERANGE;
    assert(lif_cache_receive(&e->cache, &e->capabilities, &cg, &e->bitmap, e->rx, e->n,
        &in, &g, &h, sizeof(h)) == expected && errno == ERANGE);
    assert(decode_calls == calls + calls_expected);
    assert(memcmp(&before, e, sizeof(before)) == 0 && memcmp(&prior_h, &h, sizeof(h)) == 0);
    assert(memcmp(&prior_in, &in, sizeof(in)) == 0);
    assert(memcmp(&prior_cg, &cg, sizeof(cg)) == 0 && memcmp(&prior_g, &g, sizeof(g)) == 0);
}
static void roll(struct environment *e, unsigned token)
{
    const unsigned char actual = (unsigned char)token;
    struct cp_lif_bitmap_guard g = mutation(e);
    assert(lif_cache_consume_cycle_roll(&e->cache, &actual, 1, &g) == 0);
}
static void lookup(struct environment *e, struct lif_cache_handle h, unsigned id, int expected)
{
    struct lif_cache_result out, before;
    struct cp_lif_bitmap_guard g = guard(e->cache.value.sequence);
    size_t i;
    memset(&out, 0xa3, sizeof(out)); memcpy(&before, &out, sizeof(out)); errno = EDOM;
    assert(lif_cache_lookup_field(&e->cache, h, id, &g, &out, sizeof(out)) == expected && errno == EDOM);
    if (expected) assert(memcmp(&out, &before, sizeof(out)) == 0);
    else {
        assert(out.size && out.diagnostic_only && out.source_sequence == e->cache.value.records[h.slot].source_sequence);
        assert(out.handle.incarnation == h.incarnation && out.handle.slot == h.slot);
        for (i = out.size; i < sizeof(out.bytes); ++i) assert(out.bytes[i] == 0);
    }
}
static void current(struct environment *e, unsigned command, unsigned id, int expected)
{
    struct lif_cache_result out, before;
    struct cp_lif_bitmap_guard g = guard(e->cache.value.sequence);
    memset(&out, 0xa4, sizeof(out)); memcpy(&before, &out, sizeof(out));
    assert(lif_cache_lookup_current_field(&e->cache, command, id, &g, &out, sizeof(out)) == expected);
    if (expected) assert(memcmp(&out, &before, sizeof(out)) == 0);
    else assert(out.ingress_token == e->cache.value.current.token && out.opaque == out.ingress_token);
}
static void test_init(void)
{
    struct lif_cache_owner o, before;
    _Alignas(16) unsigned char pool[544];
    struct cp_lif_bitmap_guard g = guard(2);
    memset(&o, 0, sizeof(o)); memset(pool, 0x72, sizeof(pool));
    memcpy(&before, &o, sizeof(o));
    assert(lif_cache_init(&o, pool, 543, &g) == -ENOSPC && memcmp(&before, &o, sizeof(o)) == 0);
    o.value.records[3].flags = 1; memcpy(&before, &o, sizeof(o));
    assert(lif_cache_init(&o, pool, sizeof(pool), &g) == -EALREADY && memcmp(&before, &o, sizeof(o)) == 0);
    memset(&o, 0, sizeof(o)); assert(lif_cache_init(&o, pool, sizeof(pool), &g) == 0);
    assert(!o.value.source_primed && !o.value.current.known && !o.value.previous.known);
    assert(!o.value.global_last[0].known && !o.value.global_last[1].known);
    assert(!o.value.next_incarnation && o.value.diagnostic_only && o.value.owned_virtual_policy);
    assert(pool[0] == 0x72 && pool[543] == 0x72);
    assert(lif_cache_init(&o, pool, sizeof(pool), &g) == -EALREADY);
    assert(lif_cache_init(&o, (unsigned char *)&o, sizeof(o), &g) == -EINVAL);
    {
        struct environment e;
        struct lif_cache_ingress in = ingress(1);
        struct lif_cache_handle h;
        struct cp_lif_bitmap_guard cg;
        unsigned calls = decode_calls;
        setup(&e, 1, sizeof(e.pool), 1); dynamic(&e, 5, 6, 0, 0);
        cg = guard(e.capabilities.value.sequence); g = mutation(&e);
        memcpy(&before, &o, sizeof(o));
        assert(lif_cache_receive(&o, &e.capabilities, &cg, &e.bitmap, e.rx, e.n,
            &in, &g, &h, sizeof(h)) == -ENODATA);
        assert(decode_calls == calls && memcmp(&before, &o, sizeof(o)) == 0);
    }
}
static void test_reset(void)
{
    struct environment e;
    struct cp_lif_bitmap_guard g;
    unsigned char before[sizeof(e.pool)];
    struct lif_cache_handle h;
    setup(&e, 1, sizeof(e.pool), 1); dynamic(&e, 5, 6, 0xb0, 1); h = accept(&e, 1);
    roll(&e, 0xb0); memcpy(before, e.pool, sizeof(before)); g = mutation(&e);
    assert(lif_cache_consume_reset_and_prime(&e.cache, &g) == 0);
    assert(e.cache.value.source_primed && !e.cache.value.current.known && !e.cache.value.previous.known);
    assert(e.cache.value.global_last[0].known && !e.cache.value.global_last[0].present);
    assert(e.cache.value.global_last[1].handle.slot == 0xff && !e.cache.value.last_rx_size);
    assert(e.cache.value.next_incarnation == h.incarnation && e.cache.value.next_slot == 0);
    assert(memcmp(before, e.pool, sizeof(before)) == 0); lookup(&e, h, 0x40, -ESTALE);
}
static void test_cycle(void)
{
    struct environment e;
    struct cp_lif_bitmap_guard g;
    const unsigned char actual[2] = {0xff, 0x19};
    setup(&e, 1, sizeof(e.pool), 1); current(&e, 5, 0, -ENODATA);
    g = mutation(&e);
    assert(lif_cache_consume_cycle_roll(&e.cache, actual, 0, &g) == -EMSGSIZE);
    assert(lif_cache_consume_cycle_roll(&e.cache, actual, sizeof(actual), &g) == -EMSGSIZE);
    roll(&e, 0xff);
    assert(e.cache.value.current.known && e.cache.value.current.token == 0xff && !e.cache.value.previous.known);
    assert(e.cache.value.current.command[0].known && !e.cache.value.current.command[0].present);
    current(&e, 5, 0, -ENOENT); current(&e, 6, 0x40, -ENOENT);
    roll(&e, 0);
    assert(e.cache.value.previous.known && e.cache.value.previous.token == 0xff);
    assert(e.cache.value.current.known && e.cache.value.current.token == 0);
}
static void test_order(unsigned first)
{
    struct environment e;
    struct lif_cache_handle h;
    struct lif_cache_result out;
    struct cp_lif_bitmap_guard g;
    const struct lif_cache_record *r;
    size_t i;
    unsigned last = 11 - first, kept = last == 5 ? 0 : 0x40, lost = last == 5 ? 0x40 : 0;
    setup(&e, 1, sizeof(e.pool), 1); dynamic(&e, first, last, 0x19, 1); h = accept(&e, 0x19);
    r = &e.cache.value.records[h.slot]; g = guard(e.cache.value.sequence);
    assert(r->field_table_known && r->field_table_command == last && r->last_top_index == 1);
    assert(r->last_dynamic_index == r->field_count - 1 && r->command_count == 2);
    for (i = 0; i < r->field_count; ++i) assert(r->fields[i].command == last);
    for (i = r->field_count; i < CP_LIF_MAX_FIELDS; ++i) assert(r->fields[i].length == 0);
    lookup(&e, h, kept, 0); lookup(&e, h, lost, -ENOENT);
    for (i = 5; i <= 6; ++i) {
        assert(lif_cache_lookup_command(&e.cache, h, (unsigned)i, &g, &out, sizeof(out)) == 0);
        assert(out.bytes[0] == i && out.size > 1);
        assert(memcmp(out.bytes, e.rx + r->commands[i == first ? 0 : 1].offset, out.size) == 0);
    }
    assert(e.cache.value.global_last[0].present && e.cache.value.global_last[1].present);
    assert(!e.cache.value.current.known);
}
static void test_empty(unsigned first, unsigned kind)
{
    struct environment e;
    struct lif_cache_handle h;
    const struct lif_cache_record *r;
    setup(&e, kind, sizeof(e.pool), 1); dynamic(&e, first, 11 - first, 0x19, 0); h = accept(&e, 0x19);
    r = &e.cache.value.records[h.slot];
    if (kind) {
        assert(r->field_table_known && r->field_table_command == 5 && r->field_count == 1);
        assert(r->fields[0].id == 6 && r->last_dynamic_index == 0); lookup(&e, h, 6, 0);
        lookup(&e, h, 0x40, -ENOENT);
    } else {
        assert(!r->field_table_known && !r->field_count && r->last_dynamic_index == 0xff);
        lookup(&e, h, 0, -ENODATA); lookup(&e, h, 0x40, -ENODATA);
    }
}
static void test_copy(void)
{
    struct environment e;
    struct lif_cache_handle h;
    struct lif_cache_result out;
    struct cp_lif_bitmap_guard g;
    const struct lif_cache_record *r;
    unsigned char expected[CP_LIF_FRAME_MAX_RX_BYTES];
    size_t i;
    setup(&e, 1, sizeof(e.pool), 1); dynamic(&e, 5, 6, 0xee, 1);
    memcpy(expected, e.rx, sizeof(expected)); h = accept(&e, 0x17); r = &e.cache.value.records[h.slot];
    assert(r->pool_offset == 0 && r->flags == 0xba && r->opaque == 0xee && r->ingress_token == 0x17);
    assert(r->metadata8 == 0x73625140 && r->metadata10 == 0xd5c4b3a2 && !r->verdict && r->extra_zero);
    assert(r->rx_length == e.n && r->frame_length + 1u == e.n);
    assert(memcmp(expected, e.pool, e.n) == 0);
    for (i = e.n; i < sizeof(e.pool); ++i) assert(e.pool[i] == 0xc7);
    memset(e.rx, 0x23, sizeof(e.rx)); g = guard(e.cache.value.sequence);
    assert(lif_cache_lookup_field(&e.cache, h, 0x40, &g, &out, sizeof(out)) == 0);
    assert(memcmp(out.bytes, expected + r->fields[0].offset, out.size) == 0);
    memset(out.bytes, 0, out.size); lookup(&e, h, 0x40, 0);
}
static void test_history(void)
{
    struct environment e;
    struct lif_cache_handle h, other;
    setup(&e, 1, sizeof(e.pool), 1); roll(&e, 0x19);
    dynamic(&e, 5, 0, 0x19, 0); h = accept(&e, 0x19); current(&e, 5, 0, 0);
    dynamic(&e, 6, 0, 0x19, 0); other = accept(&e, 0x42);
    assert(e.cache.value.global_last[1].handle.incarnation == other.incarnation);
    assert(!e.cache.value.current.command[1].present); current(&e, 6, 0x40, -ENOENT);
    assert(e.cache.value.current.command[0].handle.incarnation == h.incarnation);
    dynamic(&e, 6, 0, 0x19, 0); other = accept(&e, 0x19); current(&e, 6, 0x40, 0);
    assert(e.cache.value.current.command[1].handle.incarnation == other.incarnation);
}
static void test_opaque(void)
{
    struct environment e;
    struct lif_cache_handle h;
    setup(&e, 1, sizeof(e.pool), 1); roll(&e, 0x19);
    dynamic(&e, 5, 6, 0x42, 0); h = accept(&e, 0x19);
    assert(e.cache.value.current.command[0].present && e.cache.value.current.command[1].present);
    lookup(&e, h, 0x40, 0); current(&e, 5, 0, -ESTALE); current(&e, 6, 0x40, -ESTALE);
    dynamic(&e, 6, 5, 0x19, 0); h = accept(&e, 0x19);
    current(&e, 5, 0, 0); current(&e, 6, 0x40, -ENOENT); lookup(&e, h, 0x40, -ENOENT);
}
static void test_previous(void)
{
    struct environment e;
    struct lif_cache_epoch prior;
    struct lif_cache_handle h;
    setup(&e, 1, sizeof(e.pool), 1); roll(&e, 0x19);
    dynamic(&e, 5, 0, 0x19, 0); h = accept(&e, 0x19);
    memcpy(&prior, &e.cache.value.current, sizeof(prior)); roll(&e, 0xfe);
    assert(memcmp(&prior, &e.cache.value.previous, sizeof(prior)) == 0);
    assert(!e.cache.value.current.command[0].present && e.cache.value.current.command[0].known);
    assert(e.cache.value.global_last[0].handle.incarnation == h.incarnation);
    current(&e, 5, 0, -ENOENT); lookup(&e, h, 0, 0);
}
static void test_eviction(int metadata)
{
    struct environment e;
    struct lif_cache_handle old, h;
    struct cp_lif_bitmap_guard g;
    struct lif_cache_result out;
    size_t i, count = metadata ? 64 : 1;
    setup(&e, 2, metadata ? sizeof(e.pool) : 544, 1);
    dynamic(&e, 5, 0, 0x19, 0); old = accept(&e, 0x19);
    for (i = 0; i < count; ++i) { dynamic(&e, 5, 0, 0x19, 0); h = accept(&e, 0x19); }
    assert(h.incarnation > old.incarnation);
    if (metadata) assert(h.slot == old.slot && e.cache.value.next_slot == 1);
    else assert(h.slot != old.slot && e.cache.value.records[old.slot].live == 0);
    lookup(&e, old, 6, -ESTALE); lookup(&e, h, 6, 0);
    g = guard(e.cache.value.sequence);
    assert(lif_cache_lookup_command(&e.cache, old, 5, &g, &out, sizeof(out)) == -ESTALE);
}
static void test_reset_aba(void)
{
    struct environment e;
    struct lif_cache_handle old, h;
    struct cp_lif_bitmap_guard g;
    setup(&e, 2, sizeof(e.pool), 1); dynamic(&e, 5, 0, 0, 0); old = accept(&e, 0);
    g = mutation(&e); assert(lif_cache_consume_reset_and_prime(&e.cache, &g) == 0);
    h = accept(&e, 0); assert(h.slot == old.slot && h.incarnation > old.incarnation);
    lookup(&e, old, 6, -ESTALE); lookup(&e, h, 6, 0);
}
static void test_capability(unsigned mode)
{
    struct environment e;
    struct cp_lif_bitmap_guard cg, g;
    setup(&e, 1, sizeof(e.pool), 1);
    dynamic(&e, mode == 1 ? 6 : 5, 0, 0, 0);
    /* HOST_TEST fault injections; no source-event or native-history claim. */
    if (mode == 0) e.capabilities.value.support[6] = 0;
    if (mode == 1) e.capabilities.value.support_known[5] = 0;
    if (mode == 2) e.capabilities.value.z = 1;
    if (mode == 3) e.capabilities.value.z_known = 0;
    cg = guard(e.capabilities.value.sequence); g = mutation(&e);
    reject(&e, cg, g, mode == 0 ? -EACCES : mode == 2 ? -ENOTSUP : -ENODATA, 0);
}
static void test_cap_guard(void)
{
    struct environment e;
    struct cp_lif_bitmap_guard cg, g;
    setup(&e, 1, sizeof(e.pool), 1); dynamic(&e, 5, 6, 0, 0);
    cg = guard(e.capabilities.value.sequence - 2); g = mutation(&e); reject(&e, cg, g, -ESTALE, 0);
    cg = guard(e.capabilities.value.sequence); cg.sequence_after += 2; reject(&e, cg, g, -EAGAIN, 0);
    cg = guard(e.capabilities.value.sequence); cg.origin = CP_LIF_ORIGIN_VIRTUAL_SOURCE; reject(&e, cg, g, -EXDEV, 0);
    cg = guard(e.capabilities.value.sequence); g = cg; reject(&e, cg, g, -ESTALE, 0);
}
static void test_bitmap(int newer)
{
    struct environment e;
    struct cp_lif_bitmap_guard cg, g;
    setup(&e, 1, sizeof(e.pool), newer); dynamic(&e, 5, 6, 0, 0);
    if (newer) {
        struct cp_lif_bitmap_inputs input;
        struct cp_lif_bitmap_lease lease;
        cg = guard(e.capabilities.value.sequence);
        assert(lif_capabilities_export_bitmap(&e.capabilities, &cg, &input, sizeof(input)) == 0);
        g = mutation(&e); assert(cp_lif_bitmap_request(&e.bitmap, 1, &input, &g, &lease, sizeof(lease)) == 0);
    }
    cg = guard(e.capabilities.value.sequence); g = mutation(&e);
    reject(&e, cg, g, newer ? -EAGAIN : -ENODATA, 1);
}
static void test_guards(void)
{
    struct environment e;
    struct cp_lif_bitmap_guard cg, g;
    unsigned i;
    setup(&e, 1, sizeof(e.pool), 1); dynamic(&e, 5, 6, 0, 0); cg = guard(e.capabilities.value.sequence);
    for (i = 0; i < 10; ++i) {
        int expected = -EAGAIN;
        g = mutation(&e);
        switch (i) {
        case 0: g.owner_pid++; expected = -EXDEV; break;
        case 1: g.origin = CP_LIF_ORIGIN_VIRTUAL_SOURCE; expected = -EXDEV; break;
        case 2: g.sequence_after += 2; break;
        case 3: g.sequence_before = g.sequence_after = 21; break;
        case 4: g.quiescent = 0; break;
        case 5: g.quiescent = 2; expected = -EINVAL; break;
        case 6: g = guard(e.cache.value.sequence); expected = -ESTALE; break;
        case 7: g.owner_pid = 0; expected = -ENODATA; break;
        case 8: g.origin = CP_LIF_ORIGIN_NONE; expected = -ENODATA; break;
        default: g = guard(e.bitmap.sequence); expected = -ESTALE; break;
        }
        reject(&e, cg, g, expected, i == 9 ? 1 : 0);
    }
}
static void test_aliases(void)
{
    struct environment e, before;
    struct lif_cache_handle h;
    struct cp_lif_bitmap_guard cg, g;
    struct lif_cache_ingress in = ingress(1);
    unsigned calls;
    setup(&e, 1, sizeof(e.pool), 1); dynamic(&e, 5, 6, 0, 0);
    cg = guard(e.capabilities.value.sequence); g = mutation(&e); memcpy(&before, &e, sizeof(e)); calls = decode_calls;
#define RECEIVE(CAP, CG, BM, RX, IN, G, OUT, N) lif_cache_receive(&e.cache, CAP, CG, BM, RX, e.n, IN, G, OUT, N)
    assert(RECEIVE(&e.capabilities, &cg, &e.bitmap, e.pool, &in, &g, &h, sizeof(h)) == -EINVAL);
    assert(RECEIVE(&e.capabilities, &cg, &e.bitmap, e.rx, &in, &g,
        (struct lif_cache_handle *)(void *)(e.pool + sizeof(e.pool) - sizeof(h)), sizeof(h)) == -EINVAL);
    assert(RECEIVE(&e.capabilities, &cg, &e.bitmap, e.rx, &in,
        (const struct cp_lif_bitmap_guard *)(const void *)&e.cache, &h, sizeof(h)) == -EINVAL);
    assert(RECEIVE(&e.capabilities, &cg, &e.bitmap, e.rx,
        (const struct lif_cache_ingress *)(const void *)e.pool, &g, &h, sizeof(h)) == -EINVAL);
    assert(RECEIVE((const struct lif_capabilities_owner *)(const void *)e.pool, &cg,
        &e.bitmap, e.rx, &in, &g, &h, sizeof(h)) == -EINVAL);
    assert(RECEIVE(&e.capabilities, &cg, (struct cp_lif_bitmap_owner *)(void *)e.pool,
        e.rx, &in, &g, &h, sizeof(h)) == -EINVAL);
    assert(RECEIVE(&e.capabilities, (const struct cp_lif_bitmap_guard *)(const void *)e.pool,
        &e.bitmap, e.rx, &in, &g, &h, sizeof(h)) == -EINVAL);
    assert(RECEIVE(&e.capabilities, &cg, &e.bitmap, (const unsigned char *)&cg,
        &in, &g, &h, sizeof(h)) == -EINVAL);
    assert(decode_calls == calls && memcmp(&before, &e, sizeof(e)) == 0);
#undef RECEIVE
    {
        struct arena { struct lif_cache_handle out; struct cp_lif_bitmap_guard g; } a;
        a.g = g;
        assert(lif_cache_receive(&e.cache, &e.capabilities, &cg, &e.bitmap, e.rx, e.n,
            &in, &a.g, &a.out, sizeof(a)) == -EINVAL);
    }
}
static void test_read_aliases(void)
{
    struct environment e;
    struct lif_cache_handle h;
    struct cp_lif_bitmap_guard g;
    struct lif_cache_result out, before;
    struct lif_cache_readback snapshot;
    struct arena { struct lif_cache_result out; struct cp_lif_bitmap_guard g; } a;
    setup(&e, 1, sizeof(e.pool), 1); dynamic(&e, 5, 6, 0, 0); h = accept(&e, 0); g = guard(e.cache.value.sequence);
    memset(&out, 0xb7, sizeof(out)); memcpy(&before, &out, sizeof(out));
    assert(lif_cache_lookup_field(&e.cache, h, 0x40, &g, &out, sizeof(out) - 1) == -EMSGSIZE);
    assert(memcmp(&out, &before, sizeof(out)) == 0);
    assert(lif_cache_lookup_command(&e.cache, h, 6, &g, (struct lif_cache_result *)(void *)e.pool, sizeof(out)) == -EINVAL);
    a.g = g;
    assert(lif_cache_lookup_field(&e.cache, h, 0x40, &a.g, &a.out, sizeof(a)) == -EINVAL);
    assert(lif_cache_snapshot(&e.cache, &g, (struct lif_cache_readback *)(void *)e.pool, sizeof(snapshot)) == -EINVAL);
    assert(lif_cache_snapshot(&e.cache, &g, &snapshot, sizeof(snapshot) - 1) == -EMSGSIZE);
    g.sequence_before = g.sequence_after = e.cache.value.sequence + 2;
    assert(lif_cache_snapshot(&e.cache, &g, &snapshot, sizeof(snapshot)) == -ESTALE);
    {
        struct arena_pool { struct lif_cache_result out; unsigned char pool[544]; } p;
        struct lif_cache_owner o;
        memset(&o, 0, sizeof(o)); g = guard(2);
        assert(lif_cache_init(&o, p.pool, sizeof(p.pool), &g) == 0);
        assert(lif_cache_lookup_field(&o, h, 0x40, &g, &p.out, sizeof(p)) == -EINVAL);
    }
}
static void test_spans(void)
{
    struct environment e;
    struct cp_lif_bitmap_guard cg, g;
    struct lif_cache_handle h = {0, 0};
    struct lif_cache_ingress in = ingress(1);
    struct lif_cache_result out;
    const void *wrapped = (const void *)(uintptr_t)(UINTPTR_MAX - 7u);
    setup(&e, 1, sizeof(e.pool), 1); dynamic(&e, 5, 6, 0, 0); cg = guard(e.capabilities.value.sequence); g = mutation(&e);
    assert(lif_cache_receive(&e.cache, &e.capabilities, &cg, &e.bitmap, wrapped, e.n,
        &in, &g, &h, sizeof(h)) == -EINVAL);
    assert(lif_cache_receive(&e.cache, &e.capabilities, &cg, &e.bitmap, e.rx, e.n,
        &in, &g, &h, SIZE_MAX) == -EINVAL);
    assert(lif_cache_init((struct lif_cache_owner *)wrapped, e.pool, sizeof(e.pool), &g) == -EINVAL);
    assert(lif_cache_lookup_field(&e.cache, h, 0, &g, &out, SIZE_MAX) == -ESTALE);
    g = guard(e.cache.value.sequence);
    assert(lif_cache_lookup_field(&e.cache, (struct lif_cache_handle){1,0}, 0, &g,
        (struct lif_cache_result *)(void *)((unsigned char *)&out + 1), sizeof(out) - 1) == -EINVAL);
}
static void test_overflow(void)
{
    struct environment e;
    struct cp_lif_bitmap_guard cg, g;
    setup(&e, 1, sizeof(e.pool), 1); dynamic(&e, 5, 6, 0, 0);
    e.cache.value.next_incarnation = UINT64_MAX; cg = guard(e.capabilities.value.sequence); g = mutation(&e);
    reject(&e, cg, g, -EOVERFLOW, 0);
    assert(lif_cache_consume_reset_and_prime(&e.cache, &g) == 0);
    assert(e.cache.value.next_incarnation == UINT64_MAX); g = mutation(&e); reject(&e, cg, g, -EOVERFLOW, 0);
}
static void test_bad_rx(void)
{
    struct environment e;
    struct cp_lif_bitmap_guard cg, g;
    struct cp_lif_bitmap_received received;
    setup(&e, 1, sizeof(e.pool), 1); dynamic(&e, 5, 6, 0, 1);
    cg = guard(e.capabilities.value.sequence); g = mutation(&e);
    e.rx[10] ^= 1; reject(&e, cg, g, -EBADMSG, 1); e.rx[10] ^= 1;
    e.rx[e.n - 1] = 1; reject(&e, cg, g, -EBADMSG, 1);
    memset(e.rx, 0, sizeof(e.rx)); e.rx[0] = 0xf0; put16(e.rx + 1, 544);
    e.rx[3] = 2; e.rx[5] = 5; e.rx[543] = 0x55; checksum(e.rx);
    e.n = 545; reject(&e, cg, g, -EMSGSIZE, 0);
    /* Real bitmap/decoder accepts this RX extent, then rejects its extra command.
     * The cache's earlier -EMSGSIZE is the stronger whole-reserve boundary. */
    assert(__real_cp_lif_bitmap_receive_decode(&e.bitmap, e.rx, e.n, &g,
        &received, sizeof(received)) == -ENOTSUP);
    e.n = 544; reject(&e, cg, g, -ENOTSUP, 1);
}
static void test_dataflow(void)
{
    struct environment e;
    struct lif_capabilities_readback before, after;
    struct cp_lif_bitmap_guard cg, g;
    struct lif_cache_readback out;
    struct lif_cache_handle h;
    setup(&e, 1, sizeof(e.pool), 1); cg = guard(e.capabilities.value.sequence);
    assert(lif_capabilities_snapshot(&e.capabilities, &cg, &before, sizeof(before)) == 0);
    assert(before.state_known && before.state == 2 && before.k_known && before.k == 4);
    roll(&e, 0x19); dynamic(&e, 5, 0, 0x19, 1); h = accept(&e, 0x19);
    current(&e, 5, 0, 0); lookup(&e, h, 0, 0);
    dynamic(&e, 6, 0, 0x19, 1); h = accept(&e, 0x19);
    current(&e, 5, 0, 0); current(&e, 6, 0x40, 0); lookup(&e, h, 0x40, 0);
    assert(lif_capabilities_snapshot(&e.capabilities, &cg, &after, sizeof(after)) == 0);
    assert(memcmp(&before, &after, sizeof(before)) == 0);
    g = guard(e.cache.value.sequence); assert(lif_cache_snapshot(&e.cache, &g, &out, sizeof(out)) == 0);
    assert(out.diagnostic_only && out.owned_virtual_policy && out.origin == CP_LIF_ORIGIN_HOST_TEST);
    assert(!out.original_cache_executed && !out.worker_published && !out.ack && !out.ready);
    assert(!after.original_cache_admission && !after.original_CP && !after.last_dynamic.decoded.transport_decoded);
}
static void prepare_combined(struct environment *e)
{
    struct cp_lif_bitmap_guard g;
    setup(e, 1, sizeof(e->pool), 1);
    assert(e->capabilities.value.state_known && e->capabilities.value.state == 2);
    g = mutation(e); assert(lif_capabilities_consume_control_flags_reset(&e->capabilities, &g) == 0);
    e->n = fixed(e->rx, 9, 1); e->rx[6] = 1; checksum(e->rx);
    g = mutation(e); assert(lif_capabilities_receive(&e->capabilities, e->rx, e->n, &g) == 0);
    assert(e->capabilities.value.pending9 && e->capabilities.value.pending9_body_known);
    assert(e->capabilities.value.state == 2 && e->capabilities.value.k == 4);
    g = mutation(e); assert(lif_capabilities_consume_dispatch_event9_prefix(&e->capabilities, &g) == 0);
    assert(e->capabilities.value.state == 3 && e->capabilities.value.k == 4);
    assert(e->capabilities.value.pending9 && e->capabilities.value.control_enabled);
}
static struct lif_cache_handle accept_combined(struct environment *e, unsigned token)
{
    struct lif_capabilities_receipt fixed_before = e->capabilities.value.receipt;
    struct cp_lif_bitmap_guard cg = guard(e->capabilities.value.sequence), g = mutation(e);
    struct lif_cache_ingress in = ingress(token);
    struct { struct lif_cache_handle handle; unsigned char tail[23]; } out, before;
    struct lif_capabilities_readback cap;
    struct lif_cache_readback cache;
    const struct lif_cache_record *r;
    unsigned char rx_before[sizeof(e->rx)], pool_before[sizeof(e->pool)];
    size_t i;
    unsigned calls = decode_calls;
    memset(&out, 0xe7, sizeof(out)); memcpy(&before, &out, sizeof(out));
    memcpy(rx_before, e->rx, sizeof(rx_before)); memcpy(pool_before, e->pool, sizeof(pool_before));
    errno = EILSEQ;
    assert(lif_cache_receive_with_handshake(&e->cache, &e->capabilities, &cg, &e->bitmap,
        e->rx, e->n, &in, &g, &out.handle, sizeof(out)) == 0 && errno == EILSEQ);
    assert(decode_calls == calls + 1 && e->bitmap.sequence == g.sequence_before);
    assert(e->cache.value.sequence == g.sequence_before && e->capabilities.value.sequence == g.sequence_before);
    assert(lif_capabilities_snapshot(&e->capabilities, &g, &cap, sizeof(cap)) == 0);
    assert(lif_cache_snapshot(&e->cache, &g, &cache, sizeof(cache)) == 0);
    assert(memcmp(&fixed_before, &cap.receipt, sizeof(fixed_before)) == 0);
    assert(memcmp((const unsigned char *)&out + sizeof(out.handle),
        (const unsigned char *)&before + sizeof(before.handle), sizeof(out) - sizeof(out.handle)) == 0);
    assert(memcmp(rx_before, e->rx, sizeof(rx_before)) == 0);
    assert(out.handle.incarnation && out.handle.slot < LIF_CACHE_RECORDS);
    r = &cache.records[out.handle.slot];
    assert(r->admitted_owned_frame && r->source_sequence == g.sequence_before);
    assert(cap.last_dynamic.decoded.source_sequence == r->source_sequence);
    assert(cap.last_dynamic.decoded.transport_decoded && cap.last_dynamic.configured_matches_consumed);
    assert(cap.last_dynamic.owned_virtual_data && cap.last_dynamic.decoded.rx_length == e->n);
    assert(memcmp(cap.last_dynamic.decoded.frame, rx_before, e->n) == 0);
    assert(memcmp(e->pool + r->pool_offset, cap.last_dynamic.decoded.frame, e->n) == 0);
    for (i = 0; i < sizeof(e->pool); ++i)
        if (i < r->pool_offset || i >= r->pool_offset + e->n) assert(e->pool[i] == pool_before[i]);
    assert(!cache.original_cache_executed && !cache.worker_published && !cache.ack && !cache.ready);
    assert(!cap.original_cache_admission && !cap.original_CP);
    assert(!cap.original_handler_executed && !cap.original_event_delivery);
    return out.handle;
}
static void reject_combined(struct environment *e, struct cp_lif_bitmap_guard cg,
    struct cp_lif_bitmap_guard g, int expected, unsigned calls_expected)
{
    struct environment before;
    struct lif_cache_ingress in = ingress(0x19), prior_in;
    struct { struct lif_cache_handle handle; unsigned char tail[23]; } out, prior_out;
    struct cp_lif_bitmap_guard prior_cg, prior_g;
    unsigned calls = decode_calls;
    memcpy(&before, e, sizeof(before)); memcpy(&prior_in, &in, sizeof(in));
    memcpy(&prior_cg, &cg, sizeof(cg)); memcpy(&prior_g, &g, sizeof(g));
    memset(&out, 0xe7, sizeof(out)); memcpy(&prior_out, &out, sizeof(out)); errno = ERANGE;
    assert(lif_cache_receive_with_handshake(&e->cache, &e->capabilities, &cg, &e->bitmap,
        e->rx, e->n, &in, &g, &out.handle, sizeof(out)) == expected && errno == ERANGE);
    assert(decode_calls == calls + calls_expected);
    assert(memcmp(&before, e, sizeof(before)) == 0 && memcmp(&prior_out, &out, sizeof(out)) == 0);
    assert(memcmp(&prior_in, &in, sizeof(in)) == 0);
    assert(memcmp(&prior_cg, &cg, sizeof(cg)) == 0 && memcmp(&prior_g, &g, sizeof(g)) == 0);
}
static void test_combined_flow(void)
{
    struct environment e;
    struct lif_cache_handle h;
    struct cp_lif_bitmap_guard g;
    struct lif_cache_result body;
    const struct lif_cache_record *r;
    const struct cp_lif_decoded_frame *decoded;
    size_t i;
    prepare_combined(&e); roll(&e, 0x19);
    dynamic(&e, 5, 6, 0x19, 1); h = accept_combined(&e, 0x19);
    r = &e.cache.value.records[h.slot]; decoded = &e.capabilities.value.last_dynamic.decoded;
    assert(e.capabilities.value.state_known && e.capabilities.value.state == 5);
    assert(e.capabilities.value.state_commit_sequence == e.cache.value.sequence);
    assert(e.capabilities.value.received5_sequence == e.cache.value.sequence);
    assert(e.capabilities.value.received6_sequence == e.cache.value.sequence);
    assert(r->field_table_known && r->field_table_command == 6 && r->last_top_index == 1);
    assert(r->field_count == decoded->commands[1].field_count && r->last_dynamic_index == r->field_count - 1u);
    assert(memcmp(r->fields, decoded->fields + decoded->commands[1].first_field,
        r->field_count * sizeof(r->fields[0])) == 0);
    g = guard(e.cache.value.sequence);
    for (i = 0; i < 2; ++i) {
        const struct lif_cache_history_ref *global = &e.cache.value.global_last[i];
        const struct lif_cache_history_ref *current_ref = &e.cache.value.current.command[i];
        assert(global->known && global->present && global->handle.incarnation == h.incarnation && global->handle.slot == h.slot);
        assert(current_ref->known && current_ref->present && current_ref->handle.incarnation == h.incarnation && current_ref->handle.slot == h.slot);
        assert(lif_cache_lookup_command(&e.cache, h, (unsigned)(5 + i), &g, &body, sizeof(body)) == 0);
        assert(body.size == r->commands[i].length && memcmp(body.bytes, e.rx + r->commands[i].offset, body.size) == 0);
    }
    current(&e, 6, 0x40, 0); current(&e, 5, 0, -ENOENT);
    lookup(&e, h, 0, -ENOENT); lookup(&e, h, 0x40, 0);
}
static void test_combined_order(void)
{
    struct environment e;
    struct lif_cache_handle h;
    uint64_t committed;
    prepare_combined(&e); roll(&e, 0x19); dynamic(&e, 6, 5, 0x19, 0);
    h = accept_combined(&e, 0x19);
    assert(e.capabilities.value.state == 5 && e.capabilities.value.state_commit_sequence == e.cache.value.sequence);
    assert(e.cache.value.records[h.slot].field_table_command == 5);
    current(&e, 5, 0, 0); current(&e, 6, 0x40, -ENOENT);
    lookup(&e, h, 0, 0); lookup(&e, h, 0x40, -ENOENT);
    {
        struct environment chain;
        prepare_combined(&chain); roll(&chain, 0x19); committed = chain.capabilities.value.state_commit_sequence;
        dynamic(&chain, 6, 0, 0x19, 0); h = accept_combined(&chain, 0x19);
        assert(chain.capabilities.value.state == 3 && chain.capabilities.value.state_commit_sequence == committed);
        assert(!chain.capabilities.value.received5_sequence && chain.capabilities.value.received6_sequence == chain.cache.value.sequence);
        lookup(&chain, h, 0x40, 0);
        dynamic(&chain, 5, 0, 0x19, 0); h = accept_combined(&chain, 0x19);
        assert(chain.capabilities.value.state == 4 && chain.capabilities.value.state_commit_sequence == chain.cache.value.sequence);
        current(&chain, 5, 0, 0); current(&chain, 6, 0x40, 0);
        dynamic(&chain, 6, 0, 0x19, 0); h = accept_combined(&chain, 0x19);
        assert(chain.capabilities.value.state == 5 && chain.capabilities.value.state_commit_sequence == chain.cache.value.sequence);
        lookup(&chain, h, 0, -ENOENT); current(&chain, 5, 0, 0); current(&chain, 6, 0x40, 0);
    }
    {
        struct environment empty;
        setup(&empty, 2, sizeof(empty.pool), 1); dynamic(&empty, 5, 6, 0x19, 0);
        h = accept_combined(&empty, 0x19);
        assert(empty.cache.value.records[h.slot].field_table_command == 5);
        assert(empty.cache.value.records[h.slot].field_count == 1);
        lookup(&empty, h, 6, 0); lookup(&empty, h, 0x40, -ENOENT);
    }
}
static void test_combined_failures(void)
{
    struct environment e;
    struct cp_lif_bitmap_guard cg, g;
    unsigned mode;
    for (mode = 0; mode < 4; ++mode) {
        struct environment fault;
        prepare_combined(&fault); dynamic(&fault, 5, 6, 0x19, 0);
        /* HOST_TEST fault injections; the invalid owner itself must stay unchanged. */
        if (mode == 0) fault.capabilities.value.support[6] = 0;
        if (mode == 1) fault.capabilities.value.support_known[5] = 0;
        if (mode == 2) fault.capabilities.value.z = 1;
        if (mode == 3) fault.capabilities.value.z_known = 0;
        cg = guard(fault.capabilities.value.sequence); g = mutation(&fault);
        reject_combined(&fault, cg, g, mode == 0 ? -EACCES : mode == 2 ? -ENOTSUP : -ENODATA, 0);
    }
    prepare_combined(&e); dynamic(&e, 5, 6, 0x19, 1);
    cg = guard(e.capabilities.value.sequence); g = mutation(&e);
    e.rx[10] ^= 1; reject_combined(&e, cg, g, -EBADMSG, 1); e.rx[10] ^= 1;
    {
        struct cp_lif_bitmap_guard bad = cg;
        bad.sequence_before = bad.sequence_after = cg.sequence_before - 2;
        reject_combined(&e, bad, g, -ESTALE, 0);
        bad = cg; bad.sequence_after += 2; reject_combined(&e, bad, g, -EAGAIN, 0);
        bad = g; bad.owner_pid++; reject_combined(&e, cg, bad, -EXDEV, 0);
        bad = g; bad.origin = CP_LIF_ORIGIN_VIRTUAL_SOURCE; reject_combined(&e, cg, bad, -EXDEV, 0);
        reject_combined(&e, cg, cg, -ESTALE, 0);
    }
    {
        struct environment before;
        struct lif_cache_ingress in = ingress(0x19);
        size_t capacity = offsetof(struct environment, bitmap) - offsetof(struct environment, cap_tail_out);
        unsigned calls = decode_calls;
        memset(&e.cap_tail_out, 0xe7, sizeof(e.cap_tail_out)); memcpy(&before, &e, sizeof(before));
        errno = ERANGE;
        assert(lif_cache_receive_with_handshake(&e.cache, &e.capabilities, &cg, &e.bitmap,
            e.rx, e.n, &in, &g, &e.cap_tail_out, capacity) == -EINVAL && errno == ERANGE);
        assert(decode_calls == calls && memcmp(&before, &e, sizeof(before)) == 0);
    }
    e.n = LIF_CACHE_RESERVE_BYTES + 1u; reject_combined(&e, cg, g, -EMSGSIZE, 0);
    {
        struct environment missing;
        setup(&missing, 1, sizeof(missing.pool), 0); dynamic(&missing, 5, 6, 0x19, 0);
        cg = guard(missing.capabilities.value.sequence); g = mutation(&missing);
        reject_combined(&missing, cg, g, -ENODATA, 1);
    }
    {
        struct environment changed;
        struct cp_lif_bitmap_inputs input;
        struct cp_lif_bitmap_lease lease;
        prepare_combined(&changed);
        cg = guard(changed.capabilities.value.sequence);
        assert(lif_capabilities_export_bitmap(&changed.capabilities, &cg, &input, sizeof(input)) == 0);
        g = mutation(&changed); assert(cp_lif_bitmap_request(&changed.bitmap, 1, &input, &g, &lease, sizeof(lease)) == 0);
        dynamic(&changed, 5, 6, 0x19, 0); g = mutation(&changed);
        reject_combined(&changed, cg, g, -EAGAIN, 1);
    }
}
static void test_combined_unknown(void)
{
    struct environment e;
    struct lif_cache_handle h;
    setup_source(&e, 1, sizeof(e.pool), 1, 0);
    assert(!e.capabilities.value.state_known && !e.capabilities.value.handshake_reset_sequence);
    assert(!e.capabilities.value.state_commit_sequence && e.capabilities.value.k == 4);
    roll(&e, 0x19); dynamic(&e, 5, 6, 0x19, 0); h = accept_combined(&e, 0x19);
    assert(!e.capabilities.value.state_known && !e.capabilities.value.state_commit_sequence);
    assert(e.capabilities.value.received5_sequence == e.cache.value.sequence);
    assert(e.capabilities.value.received6_sequence == e.cache.value.sequence);
    lookup(&e, h, 0x40, 0); current(&e, 6, 0x40, 0);
}
static void test_fork(void)
{
    struct environment e;
    struct cp_lif_bitmap_guard cg, g;
    pid_t child;
    int status;
    setup(&e, 1, sizeof(e.pool), 1); dynamic(&e, 5, 6, 0, 0);
    cg = guard(e.capabilities.value.sequence); g = mutation(&e);
    child = fork(); assert(child >= 0);
    if (!child) { reject(&e, cg, g, -EXDEV, 0); _exit(0); }
    assert(waitpid(child, &status, 0) == child && WIFEXITED(status) && WEXITSTATUS(status) == 0);
}
int main(int argc, char **argv)
{
    FILE *f;
    assert(argc == 3); f = fopen(argv[2], "rb"); assert(f);
    stage_bytes = malloc(CP_PROPERTY_STAGE_BYTES); assert(stage_bytes);
    assert(fread(stage_bytes, 1, CP_PROPERTY_STAGE_BYTES, f) == CP_PROPERTY_STAGE_BYTES);
    assert(fgetc(f) == EOF && fclose(f) == 0);
#define CASE(NAME, CALL) if (strcmp(argv[1], NAME) == 0) { CALL; } else
    CASE("init", test_init())
    CASE("reset", test_reset())
    CASE("cycle", test_cycle())
    CASE("order5", test_order(5))
    CASE("order6", test_order(6))
    CASE("empty-last", test_empty(5, 2))
    CASE("empty-first", test_empty(6, 2))
    CASE("all-empty", test_empty(5, 0))
    CASE("copy", test_copy())
    CASE("history", test_history())
    CASE("opaque", test_opaque())
    CASE("previous", test_previous())
    CASE("byte-eviction", test_eviction(0))
    CASE("metadata-reuse", test_eviction(1))
    CASE("reset-aba", test_reset_aba())
    CASE("support-zero", test_capability(0))
    CASE("support-unknown", test_capability(1))
    CASE("z-one", test_capability(2))
    CASE("z-unknown", test_capability(3))
    CASE("cap-guard", test_cap_guard())
    CASE("bitmap-receipt", test_bitmap(0))
    CASE("bitmap-config", test_bitmap(1))
    CASE("guards", test_guards())
    CASE("aliases", test_aliases())
    CASE("read-aliases", test_read_aliases())
    CASE("spans", test_spans())
    CASE("overflow", test_overflow())
    CASE("bad-rx", test_bad_rx())
    CASE("dataflow", test_dataflow())
    CASE("combined-flow", test_combined_flow())
    CASE("combined-order", test_combined_order())
    CASE("combined-failures", test_combined_failures())
    CASE("combined-unknown", test_combined_unknown())
    CASE("fork", test_fork())
    { assert(!"unknown test case"); }
#undef CASE
    free(stage_bytes); puts("ok"); return 0;
}
