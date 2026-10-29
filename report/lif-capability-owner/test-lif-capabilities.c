/* SPDX-License-Identifier: MIT */
#include "lif-capabilities.h"
#include <assert.h>
#include <errno.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

static unsigned char *stage_bytes;
static struct cp_start_state_guard stage_guard(void)
{
    struct cp_start_state_guard g;
    memset(&g, 0, sizeof(g));
    g.owner_pid = (uint32_t)getpid();
    g.sequence_before = g.sequence_after = 2;
    g.source_origin = CP_START_STATE_ORIGIN_HOST_TEST;
    g.quiescent = 1;
    return g;
}
static struct cp_lif_bitmap_guard guard(uint64_t sequence)
{
    struct cp_lif_bitmap_guard g;
    memset(&g, 0, sizeof(g));
    g.owner_pid = (uint32_t)getpid();
    g.sequence_before = g.sequence_after = sequence;
    g.origin = CP_LIF_ORIGIN_HOST_TEST;
    g.quiescent = 1;
    return g;
}
static void load_stage(struct cp_property_stage *stage)
{
    struct cp_start_state_guard g = stage_guard();
    assert(cp_property_stage_init(stage) == 0);
    assert(cp_property_stage_consume(stage, &g,
        CP_PROPERTY_STAGE_SOURCE_CP_INITIAL_STAGE, stage_bytes,
        CP_PROPERTY_STAGE_BYTES) == 0);
    assert(stage->value.context[0x17] == 0);
    assert(stage->value.context[0x20] == 1);
    assert(stage->value.mode == 1);
}
static void start(struct lif_capabilities_owner *o, uint32_t selector)
{
    struct cp_property_stage stage, before;
    struct cp_start_state_guard g = stage_guard();
    load_stage(&stage);
    memcpy(&before, &stage, sizeof(stage));
    memset(o, 0, sizeof(*o));
    errno = EDOM;
    assert(lif_capabilities_init(o, &stage, &g, selector) == 0);
    assert(errno == EDOM);
    assert(memcmp(&before, &stage, sizeof(stage)) == 0);
    assert(memcmp(&stage.value, &o->value.stage, sizeof(stage.value)) == 0);
}
static void put16(unsigned char *p, unsigned value)
{ p[0] = (unsigned char)value; p[1] = (unsigned char)(value >> 8); }
static unsigned get16(const unsigned char *p)
{ return p[0] | (unsigned)p[1] << 8; }
static void checksum(unsigned char *rx)
{
    unsigned length = get16(rx + 1), sum = 0;
    size_t i;
    for (i = 1; i < length - 3u; ++i) sum += rx[i];
    put16(rx + length - 3, sum);
}
static size_t make_frame(unsigned char *rx, unsigned command,
                         unsigned type, int extra)
{
    size_t i, body_length = command == 1 ? 33 : command == 7 ? 35 :
                            command == 8 ? 202 : command == 9 ? 12 : 64;
    size_t length = body_length + 8;
    memset(rx, 0x6b, CP_LIF_FRAME_MAX_RX_BYTES);
    rx[0] = 0xf0;
    put16(rx + 1, (unsigned)length);
    rx[3] = (unsigned char)(0xb8u | type);
    rx[4] = 0x9a;
    for (i = 0; i < body_length; ++i)
        rx[5 + i] = (unsigned char)(i * 37u + command * 13u + 1u);
    rx[5] = (unsigned char)command;
    if (command == 7) put16(rx + 5 + 0x0a, 0x4123);
    if (command == 9) rx[5 + 8] = rx[5 + 9] = 0;
    if (command == 0x3d) rx[5 + 0x28] &= (unsigned char)~0x20u;
    rx[length - 1] = 0x55;
    rx[length] = 0;
    checksum(rx);
    return length + (size_t)extra;
}
static void accepted(struct lif_capabilities_owner *o, unsigned char *rx,
                     size_t n, uint64_t seq)
{
    struct cp_lif_bitmap_guard g = guard(seq);
    unsigned char before[CP_LIF_FRAME_MAX_RX_BYTES];
    memcpy(before, rx, sizeof(before));
    errno = ERANGE;
    assert(lif_capabilities_receive(o, rx, n, &g) == 0);
    assert(errno == ERANGE);
    assert(memcmp(before, rx, sizeof(before)) == 0);
    assert(o->value.sequence == seq);
    assert(o->value.receipt.sequence == seq);
    assert(o->value.receipt.rx_length == n);
    assert(o->value.receipt.frame_length == get16(rx + 1));
    assert(o->value.receipt.flags == rx[3]);
    assert(o->value.receipt.opaque == rx[4]);
    assert(o->value.receipt.extra_zero == (n != get16(rx + 1)));
    assert(memcmp(o->value.receipt.frame, rx, n) == 0);
}
static void rejected(struct lif_capabilities_owner *o, unsigned char *rx,
                     size_t n, struct cp_lif_bitmap_guard *g, int expected)
{
    struct lif_capabilities_owner before;
    unsigned char input_before[CP_LIF_FRAME_MAX_RX_BYTES];
    struct cp_lif_bitmap_guard guard_before;
    memcpy(&before, o, sizeof(before));
    memcpy(input_before, rx, sizeof(input_before));
    memcpy(&guard_before, g, sizeof(guard_before));
    errno = E2BIG;
    assert(lif_capabilities_receive(o, rx, n, g) == expected);
    assert(errno == E2BIG);
    assert(memcmp(&before, o, sizeof(before)) == 0);
    assert(memcmp(input_before, rx, sizeof(input_before)) == 0);
    assert(memcmp(&guard_before, g, sizeof(*g)) == 0);
}
static void all_commands(struct lif_capabilities_owner *o)
{
    unsigned char rx[CP_LIF_FRAME_MAX_RX_BYTES];
    static const unsigned commands[] = {1, 7, 8, 0x3d};
    size_t i;
    start(o, 1);
    for (i = 0; i < 4; ++i) {
        size_t n = make_frame(rx, commands[i], 2u + (unsigned)(i & 1u), (int)(i & 1u));
        accepted(o, rx, n, 4 + i * 2);
    }
}
static void ordered(void)
{
    struct lif_capabilities_owner o;
    unsigned char rx[CP_LIF_FRAME_MAX_RX_BYTES];
    unsigned char expected[1088], known[1088];
    static const unsigned commands[] = {1, 7, 8, 0x3d};
    static const size_t at[] = {0, 0x21, 0x44, 0x139};
    size_t i, count = 0;
    start(&o, 1);
    memset(expected, 0xa5, sizeof(expected));
    memset(known, 0, sizeof(known));
    for (i = 0; i < 4; ++i) {
        size_t n = make_frame(rx, commands[i], 2u + (unsigned)(i & 1u), (int)(i & 1u));
        size_t body = get16(rx + 1) - 8;
        memcpy(expected + at[i], rx + 5, body);
        memset(known + at[i], 1, body);
        if (commands[i] == 7) {
            memcpy(expected + 0x116, rx + 5, body);
            memset(known + 0x116, 1, body);
        }
        accepted(&o, rx, n, 4 + i * 2);
        assert(memcmp(o.value.property, expected, sizeof(expected)) == 0);
        assert(memcmp(o.value.property_known, known, sizeof(known)) == 0);
        assert(o.value.stage.source_sequence == 2);
    }
    for (i = 0; i < sizeof(known); ++i) count += known[i];
    assert(count == 369);
    assert(o.value.property[0x15a] == expected[0x15a]);
    assert(o.value.property[0x15e] == expected[0x15e]);
    assert(o.value.support_refresh_sequence == 8);
    assert(o.value.diagnostic_only == 1 && o.value.owned_data_transport == 1);
    assert(o.value.original_cache_admission == 0 && o.value.original_CP == 0);
}
static void prez(void)
{
    struct lif_capabilities_owner o;
    unsigned char rx[CP_LIF_FRAME_MAX_RX_BYTES];
    struct cp_lif_bitmap_guard g = guard(4);
    size_t n;
    start(&o, 1);
    n = make_frame(rx, 8, 2, 0);
    rejected(&o, rx, n, &g, -ENODATA);
    n = make_frame(rx, 0x3d, 2, 0);
    rejected(&o, rx, n, &g, -ENODATA);
    n = make_frame(rx, 1, 2, 0);
    memset(rx + 6, 0xff, 32);
    checksum(rx);
    accepted(&o, rx, n, 4);
    assert(o.value.z_known == 0);
    assert(o.value.support_known[1] && o.value.support[1]);
    assert(o.value.support_known[2] && o.value.support[2]);
    assert(!o.value.support_known[0x43]);
    assert(!o.value.support_known[0x5a]);
    /* Clear capability proves false even with different unknown-Z masks. */
    rx[6 + ((0x5a - 1) >> 3)] &= (unsigned char)~(1u << ((0x5a - 1) & 7));
    checksum(rx);
    accepted(&o, rx, n, 6);
    assert(o.value.support_known[0x5a] && !o.value.support[0x5a]);
}
static void refresh_order(void)
{
    struct lif_capabilities_owner o;
    unsigned char rx[CP_LIF_FRAME_MAX_RX_BYTES], support[100], known[100];
    size_t n;
    start(&o, 1);
    n = make_frame(rx, 1, 2, 0);
    memset(rx + 6, 0xff, 32); checksum(rx);
    accepted(&o, rx, n, 4);
    memcpy(support, o.value.support, sizeof(support));
    memcpy(known, o.value.support_known, sizeof(known));
    n = make_frame(rx, 7, 3, 0); accepted(&o, rx, n, 6);
    assert(o.value.z_known && !o.value.z);
    assert(o.value.support_refresh_sequence == 4);
    assert(memcmp(support, o.value.support, sizeof(support)) == 0);
    assert(memcmp(known, o.value.support_known, sizeof(known)) == 0);
    n = make_frame(rx, 8, 2, 0); accepted(&o, rx, n, 8);
    assert(o.value.support_refresh_sequence == 8);
    assert(o.value.support_known[0x5a] && o.value.support[0x5a]);
    n = make_frame(rx, 0x3d, 2, 0); accepted(&o, rx, n, 10);
    assert(o.value.support_refresh_sequence == 8);
}
static uint64_t fnv(const unsigned char *p, size_t n)
{
    uint64_t value = UINT64_C(14695981039346656037);
    size_t i;
    for (i = 0; i < n; ++i) value = (value ^ p[i]) * UINT64_C(1099511628211);
    return value;
}
static void selectors(void)
{
    struct lif_capabilities_owner o;
    unsigned char rx[CP_LIF_FRAME_MAX_RX_BYTES];
    static const uint32_t selectors_to_test[] = {0,1,2,3,4,UINT32_MAX};
    size_t i;
    for (i = 0; i < sizeof(selectors_to_test) / sizeof(selectors_to_test[0]); ++i) {
        uint32_t selector = selectors_to_test[i];
        size_t n;
        start(&o, selector);
        assert(o.value.selector == selector);
        assert(o.value.mask_row == (selector == 3));
        assert(fnv(o.value.request, sizeof(o.value.request)) ==
            (selector == 3 ? UINT64_C(0x7446d46ee330718d) : UINT64_C(0xa706d8a9ad9a33c7)));
        assert(o.value.request_configured && !o.value.receipt.present);
        n = make_frame(rx, 1, 2, 0);
        memset(rx + 6, 0xff, 32); checksum(rx); accepted(&o, rx, n, 4);
        assert(o.value.support_known[0x5a] == (selector == 3));
        n = make_frame(rx, 7, 2, 0); accepted(&o, rx, n, 6);
        n = make_frame(rx, 8, 2, 0); accepted(&o, rx, n, 8);
        assert(o.value.support_known[2]);
        assert(o.value.support[2] == (selector != 3));
    }
}
static void zvalues(int z1)
{
    struct lif_capabilities_owner o;
    unsigned char rx[CP_LIF_FRAME_MAX_RX_BYTES];
    static const unsigned zero_values[] = {0,1,0x0fff,0x1234,0x3fff,0x4000,0x8000,0xbffe,0xbfff,0xcfff,0xffff};
    static const unsigned one_values[] = {0xc000,0xc001,0xcffe,0xd000,0xeffe,0xfffe};
    const unsigned *values = z1 ? one_values : zero_values;
    size_t count = z1 ? sizeof(one_values)/sizeof(one_values[0]) : sizeof(zero_values)/sizeof(zero_values[0]);
    size_t i;
    start(&o, 1);
    for (i = 0; i < count; ++i) {
        size_t n = make_frame(rx, 7, 2, 0);
        struct cp_lif_bitmap_guard g = guard(4 + i * 2);
        put16(rx + 5 + 0x0a, values[i]); checksum(rx);
        if (z1) rejected(&o, rx, n, &g, -ENOTSUP);
        else {
            accepted(&o, rx, n, g.sequence_before);
            assert(o.value.z_known && !o.value.z);
        }
    }
    if (z1) {
        size_t n = make_frame(rx, 7, 2, 0);
        struct cp_lif_bitmap_guard g = guard(6);
        accepted(&o, rx, n, 4);
        put16(rx + 5 + 0x0a, 0xc000); checksum(rx);
        rejected(&o, rx, n, &g, -ENOTSUP);
    }
}
static void dbit(void)
{
    struct lif_capabilities_owner o;
    unsigned char rx[CP_LIF_FRAME_MAX_RX_BYTES];
    struct cp_lif_bitmap_guard g = guard(6);
    size_t n;
    start(&o, 1);
    n = make_frame(rx, 7, 2, 0); accepted(&o, rx, n, 4);
    n = make_frame(rx, 0x3d, 3, 1);
    rx[5 + 0x28] |= 0x20; checksum(rx);
    rejected(&o, rx, n, &g, -ENODATA);
    rx[5 + 0x28] &= (unsigned char)~0x20u; checksum(rx);
    accepted(&o, rx, n, 6);
    assert(memcmp(o.value.property + 0x139, rx + 5, 64) == 0);
    assert(memcmp(o.value.property + 0x15a, rx + 5 + 0x21, 8) == 0);
}
static void export_bitmap(void)
{
    struct lif_capabilities_owner o;
    struct cp_lif_bitmap_inputs input, initial;
    struct cp_lif_bitmap_product product;
    struct cp_lif_bitmap_guard g = guard(2);
    start(&o, 1);
    assert(lif_capabilities_export_bitmap(&o, &g, &initial, sizeof(initial)) == 0);
    assert(initial.known == (CP_LIF_BITMAP_MODE_KNOWN | CP_LIF_BITMAP_S43_KNOWN | CP_LIF_BITMAP_S5A_KNOWN));
    assert(initial.mode == 1 && !(initial.known & CP_LIF_BITMAP_K_KNOWN));
    all_commands(&o); g = guard(10);
    assert(lif_capabilities_export_bitmap(&o, &g, &input, sizeof(input)) == 0);
    assert(input.known == (CP_LIF_BITMAP_MODE_KNOWN | CP_LIF_BITMAP_Z_KNOWN | CP_LIF_BITMAP_S43_KNOWN | CP_LIF_BITMAP_S5A_KNOWN));
    assert(input.mode == 1 && input.z == 0 && input.s43 == 0);
    assert(memcmp(input.property, o.value.property, sizeof(input.property)) == 0);
    assert(memcmp(input.property_known, o.value.property_known, sizeof(input.property_known)) == 0);
    assert(cp_lif_bitmap_build(&input, &g, &product, sizeof(product)) == -ENODATA);
    g = guard(12);
    assert(lif_capabilities_consume_initial_kind_store(&o, &g) == 0);
    assert(o.value.k_store_sequence == 12 && o.value.receipt.sequence == 10);
    assert(lif_capabilities_export_bitmap(&o, &g, &input, sizeof(input)) == 0);
    assert((input.known & CP_LIF_BITMAP_K_KNOWN) && input.k == 4);
    assert(g.origin == CP_LIF_ORIGIN_HOST_TEST);
    assert(cp_lif_bitmap_build(&input, &g, &product, sizeof(product)) == 0);
    assert(product.command[0] == 0x0a && product.owned_virtual_data == 1);
    assert(product.wire[0] == 0xf0 && product.wire[24] == 0x55);
    assert(product.bitmap[0] == ((input.property[0x161] & 0x20) ? 0xdf : 0xff));
    assert((product.bitmap[2] & 0x40) == ((input.property[0x15d] & 0x80) ? 0x40 : 0));
    assert((product.bitmap[3] & 1) == ((input.property[0x161] & 0x40) ? 1 : 0));
    input.property_known[0x15a] = 0;
    assert(cp_lif_bitmap_build(&input, &g, &product, sizeof(product)) == -ENODATA);
}
static void kind_store(void)
{
    struct lif_capabilities_owner o, before;
    struct cp_lif_bitmap_guard g = guard(4);
    unsigned char rx[CP_LIF_FRAME_MAX_RX_BYTES];
    unsigned type;
    start(&o, 1); before = o; errno = EDOM;
    assert(lif_capabilities_consume_initial_kind_store(&o, &g) == -ENODATA && errno == EDOM);
    assert(!memcmp(&o, &before, sizeof(o)));
    for (type = 0; type < 4; ++type) {
        size_t n;
        start(&o, 1);
        n = make_frame(rx, 7, 2, 0);
        rx[6] = (unsigned char)((rx[6] & ~3u) | type); checksum(rx);
        accepted(&o, rx, n, 4); before = o; g = guard(6); errno = E2BIG;
        if (type == 0 || type == 3) {
            assert(lif_capabilities_consume_initial_kind_store(&o, &g) == -ENOTSUP);
            assert(!memcmp(&o, &before, sizeof(o)));
        } else {
            unsigned k = type == 1 ? 4u : 1u;
            assert(lif_capabilities_consume_initial_kind_store(&o, &g) == 0);
            assert(o.value.k_known && o.value.k == k && o.value.k_store_sequence == 6);
            assert(o.value.receipt.sequence == 4 && !o.value.support_refresh_sequence);
            before = o;
            assert(lif_capabilities_consume_initial_kind_store(&o, &g) == -ESTALE);
            assert(!memcmp(&o, &before, sizeof(o)));
            rx[6] = (unsigned char)((rx[6] & ~3u) | (3u - type)); checksum(rx);
            accepted(&o, rx, n, 8);
            assert(o.value.k == k && o.value.k_store_sequence == 6);
            g = guard(10);
            assert(lif_capabilities_consume_initial_kind_store(&o, &g) == 0);
            assert(o.value.k == (type == 1 ? 1u : 4u));
            assert(o.value.receipt.sequence == 8 && o.value.k_store_sequence == 10);
        }
        assert(errno == ((type == 0 || type == 3) ? E2BIG : ERANGE));
    }
}
static void guards(void)
{
    struct lif_capabilities_owner o, before;
    struct lif_capabilities_readback out, out_before;
    struct cp_lif_bitmap_guard g;
    unsigned char rx[CP_LIF_FRAME_MAX_RX_BYTES];
    size_t n = make_frame(rx, 1, 2, 0);
    unsigned i;
    start(&o, 1);
    for (i = 0; i < 10; ++i) {
        int expected = -EAGAIN;
        g = guard(4);
        switch (i) {
        case 0: g.owner_pid++; expected = -EXDEV; break;
        case 1: g.origin = CP_LIF_ORIGIN_VIRTUAL_SOURCE; expected = -EXDEV; break;
        case 2: g.sequence_after = 6; break;
        case 3: g.sequence_before = g.sequence_after = 3; break;
        case 4: g.quiescent = 0; break;
        case 5: g.quiescent = 2; expected = -EINVAL; break;
        case 6: g.sequence_before = g.sequence_after = 2; expected = -ESTALE; break;
        case 7: g.sequence_before = g.sequence_after = 0; expected = -ESTALE; break;
        case 8: g.origin = CP_LIF_ORIGIN_NONE; expected = -ENODATA; break;
        default: g.origin = (enum cp_lif_origin)99; expected = -EXDEV; break;
        }
        rejected(&o, rx, n, &g, expected);
    }
    accepted(&o, rx, n, 4); g = guard(4);
    rejected(&o, rx, n, &g, -ESTALE);
    memset(&out, 0x71, sizeof(out)); memcpy(&out_before, &out, sizeof(out));
    memcpy(&before, &o, sizeof(o));
    g = guard(6);
    assert(lif_capabilities_snapshot(&o, &g, &out, sizeof(out)) == -ESTALE);
    assert(memcmp(&out, &out_before, sizeof(out)) == 0);
    assert(memcmp(&o, &before, sizeof(o)) == 0);
    g = guard(4);
    assert(lif_capabilities_snapshot(&o, &g, &out, sizeof(out)) == 0);
    assert(out.sequence == 4 && out.stage.source_sequence == 2);
    accepted(&o, rx, n, 6);
}
static void initialization(void)
{
    struct lif_capabilities_owner o, before;
    struct cp_property_stage stage;
    struct cp_start_state_guard sg = stage_guard();
    struct cp_lif_bitmap_guard g = guard(4);
    unsigned char rx[CP_LIF_FRAME_MAX_RX_BYTES];
    size_t i, n = make_frame(rx, 1, 2, 0);
    memset(&o, 0, sizeof(o));
    rejected(&o, rx, n, &g, -ENODATA);
    load_stage(&stage);
    o.value.property[500] = 1; memcpy(&before, &o, sizeof(o));
    assert(lif_capabilities_init(&o, &stage, &sg, 1) == -EALREADY);
    assert(memcmp(&o, &before, sizeof(o)) == 0);
    start(&o, 1); memcpy(&before, &o, sizeof(o));
    assert(lif_capabilities_init(&o, &stage, &sg, 3) == -EALREADY);
    assert(memcmp(&o, &before, sizeof(o)) == 0);
    for (i = 0; i < sizeof(o.value.property); ++i) {
        assert(o.value.property_known[i] == 0);
        assert(o.value.property[i] == 0xa5);
    }
    for (i = 0; i < 100; ++i) {
        assert(o.value.support_known[i] == 1);
        assert(o.value.support[i] == (i == 1));
    }
    assert(o.value.reset_sequence == 2 && !o.value.support_refresh_sequence);
    o.revision = LIF_CAPABILITIES_REVISION + 1;
    rejected(&o, rx, n, &g, -ENOTSUP);
    memset(&o, 0, sizeof(o));
    sg.sequence_before = sg.sequence_after = 4;
    assert(lif_capabilities_init(&o, &stage, &sg, 1) == -ESTALE);
    sg = stage_guard(); sg.owner_pid++;
    assert(lif_capabilities_init(&o, &stage, &sg, 1) == -EXDEV);
    sg = stage_guard(); sg.source_origin = CP_START_STATE_ORIGIN_VIRTUAL_SOURCE;
    assert(lif_capabilities_init(&o, &stage, &sg, 1) == -EXDEV);
    /* Check explicit origin mapping with an actually consumed virtual stage. */
    assert(cp_property_stage_init(&stage) == 0);
    assert(cp_property_stage_consume(&stage, &sg,
        CP_PROPERTY_STAGE_SOURCE_CP_INITIAL_STAGE, stage_bytes, CP_PROPERTY_STAGE_BYTES) == 0);
    assert(lif_capabilities_init(&o, &stage, &sg, 3) == 0);
    assert(o.value.origin == CP_LIF_ORIGIN_VIRTUAL_SOURCE);
    assert(o.value.stage.context[0x20] == 1);
    for (i = 0; i < sizeof(o.value.property_known); ++i)
        assert(o.value.property_known[i] == 0);
}
static void frame_lengths(void)
{
    struct lif_capabilities_owner o;
    struct cp_lif_bitmap_guard g = guard(4);
    unsigned char rx[CP_LIF_FRAME_MAX_RX_BYTES];
    static const unsigned bad_lengths[] = {0,8,9,40,42,0x220,0x221,0xffff};
    size_t i, n;
    start(&o, 1);
    for (i = 0; i < sizeof(bad_lengths)/sizeof(bad_lengths[0]); ++i) {
        n = make_frame(rx, 1, 2, 0); put16(rx + 1, bad_lengths[i]);
        rejected(&o, rx, n, &g, bad_lengths[i] == 40 ? -EBADMSG : -EMSGSIZE);
    }
    n = make_frame(rx, 1, 2, 0);
    rejected(&o, rx, 8, &g, -EMSGSIZE);
    rejected(&o, rx, n - 1, &g, -EMSGSIZE);
    rejected(&o, rx, n + 2, &g, -EMSGSIZE);
    rejected(&o, rx, CP_LIF_FRAME_MAX_RX_BYTES + 1u, &g, -EMSGSIZE);
}
static void frame_bytes(void)
{
    struct lif_capabilities_owner o;
    struct cp_lif_bitmap_guard g = guard(4);
    unsigned char rx[CP_LIF_FRAME_MAX_RX_BYTES];
    size_t n;
    start(&o, 1);
    n = make_frame(rx, 1, 2, 1); rx[0] ^= 1; rejected(&o, rx, n, &g, -EBADMSG);
    n = make_frame(rx, 1, 2, 1); rx[n - 2] ^= 1; rejected(&o, rx, n, &g, -EBADMSG);
    n = make_frame(rx, 1, 2, 1); rx[n - 1] = 1; rejected(&o, rx, n, &g, -EBADMSG);
    n = make_frame(rx, 1, 2, 1); rx[12] ^= 1; rejected(&o, rx, n, &g, -EBADMSG);
    n = make_frame(rx, 1, 2, 1); rx[n - 4] ^= 1; rejected(&o, rx, n, &g, -EBADMSG);
    n = make_frame(rx, 1, 2, 1); accepted(&o, rx, n, 4);
}
static void frame_types(void)
{
    struct lif_capabilities_owner o;
    struct cp_lif_bitmap_guard g = guard(4);
    unsigned char rx[CP_LIF_FRAME_MAX_RX_BYTES];
    unsigned type;
    start(&o, 1);
    for (type = 0; type < 8; ++type) {
        size_t n = make_frame(rx, 1, type, 0);
        if (type != 2 && type != 3)
            rejected(&o, rx, n, &g, type == 1 ? -ENODATA : -EBADMSG);
    }
    accepted(&o, rx, make_frame(rx, 1, 2, 0), 4);
    accepted(&o, rx, make_frame(rx, 1, 3, 1), 6);
}
static void frame_commands(void)
{
    struct lif_capabilities_owner o;
    struct cp_lif_bitmap_guard g = guard(4);
    unsigned char rx[CP_LIF_FRAME_MAX_RX_BYTES];
    static const unsigned unknown[] = {0,5,6,0x0a,0xff};
    size_t i, n;
    start(&o, 1);
    for (i = 0; i < sizeof(unknown)/sizeof(unknown[0]); ++i) {
        n = make_frame(rx, 1, 2, 0); rx[5] = (unsigned char)unknown[i]; checksum(rx);
        rejected(&o, rx, n, &g, -ENOTSUP);
    }
    /* Valid envelopes containing two fixed command bodies must be rejected. */
    n = make_frame(rx, 1, 2, 0);
    memcpy(rx + 38, rx + 5, 33); put16(rx + 1, 74); rx[73] = 0x55; checksum(rx);
    rejected(&o, rx, 74, &g, -EMSGSIZE);
    n = make_frame(rx, 1, 2, 0);
    rx[38] = 7; put16(rx + 1, 42); rx[41] = 0x55; checksum(rx);
    rejected(&o, rx, n + 1, &g, -EMSGSIZE);
    n = make_frame(rx, 1, 2, 0);
    put16(rx + 1, 40); rx[39] = 0x55; checksum(rx);
    rejected(&o, rx, 40, &g, -EMSGSIZE);
}
static void aliases(void)
{
    struct lif_capabilities_owner o, before;
    struct cp_lif_bitmap_guard g = guard(2);
    struct cp_property_stage stage;
    struct cp_start_state_guard sg = stage_guard();
    struct snapshot_arena {
        struct lif_capabilities_readback out;
        struct lif_capabilities_owner owner;
        struct cp_lif_bitmap_guard g;
    } a;
    struct bitmap_arena {
        struct cp_lif_bitmap_inputs out;
        struct lif_capabilities_owner owner;
        struct cp_lif_bitmap_guard g;
    } b;
    unsigned char rx[CP_LIF_FRAME_MAX_RX_BYTES];
    size_t n = make_frame(rx, 1, 2, 0);
    start(&o, 1); memcpy(&before, &o, sizeof(o));
    assert(lif_capabilities_snapshot(&o, &g, &o.value, sizeof(o.value)) == -EINVAL);
    assert(lif_capabilities_export_bitmap(&o, &g, (struct cp_lif_bitmap_inputs *)(void *)&o.value,
        sizeof(struct cp_lif_bitmap_inputs)) == -EINVAL);
    assert(memcmp(&o, &before, sizeof(o)) == 0);
    memset(&a, 0x72, sizeof(a)); memcpy(&a.owner, &o, sizeof(o)); a.g = g;
    assert(lif_capabilities_snapshot(&a.owner, &a.g, &a.out, sizeof(a)) == -EINVAL);
    assert(((unsigned char *)&a.out)[0] == 0x72);
    memset(&b, 0x73, sizeof(b)); memcpy(&b.owner, &o, sizeof(o)); b.g = g;
    assert(lif_capabilities_export_bitmap(&b.owner, &b.g, &b.out, sizeof(b)) == -EINVAL);
    assert(((unsigned char *)&b.out)[0] == 0x73);
    /* Unused output tails reaching just the guard are also rejected. */
    assert(lif_capabilities_snapshot(&o, &a.g, &a.out, sizeof(a)) == -EINVAL);
    assert(lif_capabilities_export_bitmap(&o, &b.g, &b.out, sizeof(b)) == -EINVAL);
    g = guard(4);
    assert(lif_capabilities_receive(&o, o.value.property, n, &g) == -EINVAL);
    assert(lif_capabilities_receive(&o, rx, n,
        (const struct cp_lif_bitmap_guard *)(const void *)&o.value) == -EINVAL);
    assert(memcmp(&o, &before, sizeof(o)) == 0);
    load_stage(&stage);
    assert(lif_capabilities_init((struct lif_capabilities_owner *)(void *)&stage,
        &stage, &sg, 1) == -EINVAL);
}
static void spans(void)
{
    struct lif_capabilities_owner o, before;
    struct cp_lif_bitmap_guard g = guard(2);
    struct lif_capabilities_readback out, out_before;
    struct cp_lif_bitmap_inputs inputs, inputs_before;
    _Alignas(struct lif_capabilities_owner) unsigned char misaligned[sizeof(o) + 1];
    unsigned char rx[CP_LIF_FRAME_MAX_RX_BYTES];
    const void *wrapped = (const void *)(uintptr_t)(UINTPTR_MAX - 7u);
    size_t n = make_frame(rx, 1, 2, 0);
    start(&o, 1); memcpy(&before, &o, sizeof(o));
    memset(&out, 0x77, sizeof(out)); memcpy(&out_before, &out, sizeof(out));
    memset(&inputs, 0x78, sizeof(inputs)); memcpy(&inputs_before, &inputs, sizeof(inputs));
    assert(lif_capabilities_snapshot(&o, &g, &out, sizeof(out) - 1) == -EMSGSIZE);
    assert(lif_capabilities_export_bitmap(&o, &g, &inputs, sizeof(inputs) - 1) == -EMSGSIZE);
    assert(lif_capabilities_snapshot(&o, &g, &out, SIZE_MAX) == -EINVAL);
    assert(lif_capabilities_export_bitmap(&o, &g, &inputs, SIZE_MAX) == -EINVAL);
    assert(lif_capabilities_snapshot(&o, &g, (struct lif_capabilities_readback *)wrapped, sizeof(out)) == -EINVAL);
    assert(lif_capabilities_snapshot((const struct lif_capabilities_owner *)wrapped, &g, &out, sizeof(out)) == -EINVAL);
    assert(lif_capabilities_snapshot((const struct lif_capabilities_owner *)(const void *)(misaligned + 1), &g, &out, sizeof(out)) == -EINVAL);
    assert(lif_capabilities_snapshot(&o, (const struct cp_lif_bitmap_guard *)wrapped, &out, sizeof(out)) == -EINVAL);
    assert(lif_capabilities_snapshot(&o, &g, (struct lif_capabilities_readback *)(void *)((unsigned char *)&out + 1), sizeof(out) - 1) == -EINVAL);
    assert(lif_capabilities_export_bitmap(&o, &g, (struct cp_lif_bitmap_inputs *)(void *)((unsigned char *)&inputs + 1), sizeof(inputs) - 1) == -EINVAL);
    g = guard(4);
    assert(lif_capabilities_receive(&o, wrapped, n, &g) == -EINVAL);
    assert(lif_capabilities_receive(&o, rx, SIZE_MAX, &g) == -EINVAL);
    assert(lif_capabilities_receive(&o, NULL, n, &g) == -EINVAL);
    assert(memcmp(&o, &before, sizeof(o)) == 0);
    assert(memcmp(&out, &out_before, sizeof(out)) == 0);
    assert(memcmp(&inputs, &inputs_before, sizeof(inputs)) == 0);
}
static void errno_readback(void)
{
    struct lif_capabilities_owner o, before;
    struct {
        struct lif_capabilities_readback value;
        unsigned char tail[31];
    } out;
    struct {
        struct cp_lif_bitmap_inputs value;
        unsigned char tail[31];
    } input;
    struct cp_lif_bitmap_guard g = guard(2);
    struct cp_start_state_guard sg = stage_guard();
    struct cp_property_stage stage;
    size_t i;
    start(&o, 1); memcpy(&before, &o, sizeof(o));
    memset(&out, 0xc7, sizeof(out)); memset(&input, 0xc8, sizeof(input));
    errno = EILSEQ;
    assert(lif_capabilities_snapshot(&o, &g, &out.value, sizeof(out)) == 0 && errno == EILSEQ);
    assert(memcmp(&out.value, &o.value, sizeof(out.value)) == 0);
    assert(lif_capabilities_export_bitmap(&o, &g, &input.value, sizeof(input)) == 0 && errno == EILSEQ);
    for (i = 0; i < sizeof(out.tail); ++i) assert(out.tail[i] == 0xc7 && input.tail[i] == 0xc8);
    g.sequence_before = g.sequence_after = 4;
    assert(lif_capabilities_snapshot(&o, &g, &out.value, sizeof(out)) == -ESTALE && errno == EILSEQ);
    assert(lif_capabilities_export_bitmap(&o, &g, &input.value, sizeof(input)) == -ESTALE && errno == EILSEQ);
    load_stage(&stage); errno = EILSEQ;
    assert(lif_capabilities_init(&o, &stage, &sg, 1) == -EALREADY && errno == EILSEQ);
    assert(memcmp(&o, &before, sizeof(o)) == 0);
}
static void frozen_stage(void)
{
    struct cp_property_stage stage, before_stage;
    struct cp_start_state_guard sg = stage_guard();
    struct lif_capabilities_owner o, before;
    assert(cp_property_stage_init(&stage) == 0);
    memcpy(&before_stage, &stage, sizeof(stage));
    stage_bytes[9] = 1;
    assert(cp_property_stage_consume(&stage, &sg,
        CP_PROPERTY_STAGE_SOURCE_CP_INITIAL_STAGE, stage_bytes, CP_PROPERTY_STAGE_BYTES) == -EILSEQ);
    stage_bytes[9] = 0;
    assert(memcmp(&stage, &before_stage, sizeof(stage)) == 0);
    memset(&o, 0, sizeof(o)); memcpy(&before, &o, sizeof(o));
    sg.sequence_before = sg.sequence_after = 0;
    assert(lif_capabilities_init(&o, &stage, &sg, 1) == -ENODATA);
    assert(memcmp(&o, &before, sizeof(o)) == 0);
    sg = stage_guard(); load_stage(&stage);
    stage.value.repository = (enum cp_property_stage_repository)0;
    assert(lif_capabilities_init(&o, &stage, &sg, 1) == -ENODATA);
    assert(memcmp(&o, &before, sizeof(o)) == 0);
}
static void public_stage_readback(void)
{
    struct cp_property_stage stage, stage_before;
    struct cp_start_state_guard sg = stage_guard();
    struct lif_capabilities_owner o;
    struct cp_lif_bitmap_inputs input;
    struct cp_lif_bitmap_guard g = guard(8);
    unsigned char rx[CP_LIF_FRAME_MAX_RX_BYTES];
    size_t n;
    load_stage(&stage);
    assert(stage.value.context[0x17] == 0 && stage.value.context[0x20] == 1);
    assert(stage.value.context[17] == 0 && stage.value.context[20] == 0);
    memcpy(&stage_before, &stage, sizeof(stage));
    memset(&o, 0, sizeof(o)); errno = EDOM;
    assert(lif_capabilities_init(&o, &stage, &sg, 1) == 0 && errno == EDOM);
    assert(memcmp(&stage, &stage_before, sizeof(stage)) == 0);
    n = make_frame(rx, 1, 2, 0);
    memset(rx + 6, 0xff, 32); checksum(rx); accepted(&o, rx, n, 4);
    n = make_frame(rx, 7, 2, 0); accepted(&o, rx, n, 6);
    n = make_frame(rx, 8, 2, 0); accepted(&o, rx, n, 8);
    assert(!o.value.support_known[0x43]);
    assert(lif_capabilities_export_bitmap(&o, &g, &input, sizeof(input)) == 0);
    assert(!(input.known & CP_LIF_BITMAP_S43_KNOWN));
    assert(input.mode == 1 && input.z == 0);
    assert(input.known & CP_LIF_BITMAP_S5A_KNOWN);
    /* A zero capability proves false for either value of the unknown getter. */
    n = make_frame(rx, 1, 2, 0); memset(rx + 6, 0xff, 32);
    rx[5 + 9] &= (unsigned char)~0x04u; checksum(rx);
    accepted(&o, rx, n, 10);
    assert(o.value.support_known[0x43] && !o.value.support[0x43]);
    assert(memcmp(&stage, &stage_before, sizeof(stage)) == 0);
    /* HOST_TEST counterfactual exercises the source context-zero early exit. */
    stage.value.context[0x20] = 0;
    memset(&o, 0, sizeof(o)); assert(lif_capabilities_init(&o, &stage, &sg, 1) == 0);
    n = make_frame(rx, 1, 2, 0); memset(rx + 6, 0xff, 32); checksum(rx);
    accepted(&o, rx, n, 4);
    assert(o.value.support_known[0x43] && !o.value.support[0x43]);
}
static void immutable(void)
{
    struct lif_capabilities_owner o;
    struct cp_lif_bitmap_guard g = guard(4);
    unsigned char rx[CP_LIF_FRAME_MAX_RX_BYTES], expected[CP_LIF_FRAME_MAX_RX_BYTES];
    size_t i, n;
    start(&o, 1);
    n = make_frame(rx, 1, 2, 1); memcpy(expected, rx, sizeof(rx));
    accepted(&o, rx, n, 4);
    memset(rx, 0xd7, sizeof(rx));
    assert(memcmp(o.value.receipt.frame, expected, n) == 0);
    assert(memcmp(o.value.property, expected + 5, 33) == 0);
    for (i = n; i < sizeof(o.value.receipt.frame); ++i) assert(o.value.receipt.frame[i] == 0);
    assert(o.value.stage.source_sequence == 2);
    assert(g.sequence_before == 4);
}
typedef int (*local_event)(struct lif_capabilities_owner *, const struct cp_lif_bitmap_guard *);
static void consume(struct lif_capabilities_owner *o, local_event fn)
{
    struct cp_lif_bitmap_guard g = guard(o->value.sequence + 2), before = g;
    errno = EDOM;
    assert(fn(o, &g) == 0 && errno == EDOM);
    assert(o->value.sequence == g.sequence_before && !memcmp(&g, &before, sizeof(g)));
    assert(o->value.origin == CP_LIF_ORIGIN_HOST_TEST);
    assert(!o->value.original_CP && !o->value.original_cache_admission);
    assert(!o->value.original_handler_executed && !o->value.original_event_delivery);
}
static void local_rejected(struct lif_capabilities_owner *o, local_event fn,
                           struct cp_lif_bitmap_guard g, int expected)
{
    struct lif_capabilities_owner before = *o;
    errno = ERANGE;
    assert(fn(o, &g) == expected && errno == ERANGE);
    assert(!memcmp(&before, o, sizeof(before)));
}
static void prepare_handshake(struct lif_capabilities_owner *o, unsigned type, int reset)
{
    static const unsigned commands[] = {1,7,8,0x3d};
    unsigned char rx[CP_LIF_FRAME_MAX_RX_BYTES];
    size_t i, n;
    start(o, 1);
    assert(!o->value.state_known && !o->value.k_known && !o->value.control_enabled_known);
    if (reset) consume(o, lif_capabilities_consume_handshake_reset_store);
    consume(o, lif_capabilities_consume_control_flags_reset);
    for (i = 0; i < 4; ++i) {
        n = make_frame(rx, commands[i], 2, 0);
        if (commands[i] == 7) rx[6] = (unsigned char)((rx[6] & ~3u) | type);
        checksum(rx); accepted(o, rx, n, o->value.sequence + 2);
    }
    if (type == 1 || type == 2) consume(o, lif_capabilities_consume_initial_kind_store);
    assert(o->value.state_known == reset);
    assert(o->value.last_state_request_known && o->value.last_state_request == 2);
    if (reset) assert(o->value.state == 2);
}
static void receive9(struct lif_capabilities_owner *o, unsigned kind)
{
    unsigned char rx[CP_LIF_FRAME_MAX_RX_BYTES];
    size_t n = make_frame(rx, 9, 3, 1);
    rx[6] = (unsigned char)((rx[6] & ~3u) | kind); checksum(rx);
    accepted(o, rx, n, o->value.sequence + 2);
    assert(o->value.receipt.body_length == 12 && o->value.receipt.frame_length == 20);
}
static void handshake_resets(void)
{
    struct lif_capabilities_owner o, expected;
    struct cp_lif_bitmap_guard g;
    start(&o, 1); expected = o;
    expected.value.state = expected.value.k = 0;
    expected.value.state_known = expected.value.k_known = 1;
    expected.value.handshake_reset_sequence = expected.value.state_commit_sequence = 4;
    expected.value.k_store_sequence = expected.value.sequence = 4;
    consume(&o, lif_capabilities_consume_handshake_reset_store);
    assert(!memcmp(&expected, &o, sizeof(o)));
    expected.value.control_enabled = expected.value.pending8 = expected.value.pending9 = 0;
    expected.value.flags_reset_known = expected.value.control_enabled_known = 1;
    expected.value.pending8_known = expected.value.pending9_known = 1;
    expected.value.control_flags_reset_sequence = expected.value.sequence = 6;
    consume(&o, lif_capabilities_consume_control_flags_reset);
    assert(!memcmp(&expected, &o, sizeof(o)) && !o.value.pending9_body_known);
    prepare_handshake(&o, 1, 1); receive9(&o, 1);
    assert(o.value.pending9 && o.value.pending9_body_known);
    expected = o;
    expected.value.pending9 = 0;
    expected.value.control_flags_reset_sequence = expected.value.sequence += 2;
    consume(&o, lif_capabilities_consume_control_flags_reset);
    assert(!memcmp(&expected, &o, sizeof(o))); /* Body/history are not reset. */
    expected = o;
    expected.value.state = expected.value.k = 0;
    expected.value.handshake_reset_sequence = expected.value.state_commit_sequence = o.value.sequence + 2;
    expected.value.k_store_sequence = expected.value.sequence = o.value.sequence + 2;
    consume(&o, lif_capabilities_consume_handshake_reset_store);
    assert(!memcmp(&expected, &o, sizeof(o)));
    g = guard(o.value.sequence);
    local_rejected(&o, lif_capabilities_consume_handshake_reset_store, g, -ESTALE);
    local_rejected(&o, lif_capabilities_consume_control_flags_reset, g, -ESTALE);
    g = guard(o.value.sequence + 2); g.origin = CP_LIF_ORIGIN_VIRTUAL_SOURCE;
    local_rejected(&o, lif_capabilities_consume_dispatch_event9_prefix, g, -EXDEV);
    local_rejected(&o, lif_capabilities_consume_handshake_reset_store, g, -EXDEV);
    local_rejected(&o, lif_capabilities_consume_control_flags_reset, g, -EXDEV);
    consume(&o, lif_capabilities_consume_dispatch_event9_prefix);
    assert(o.value.state == 0 && o.value.k == 0 && !o.value.last_dynamic.decoded.transport_decoded);
}
static void configure_bitmap(struct lif_capabilities_owner *o,
    struct cp_lif_bitmap_owner *b, struct cp_lif_bitmap_lease *lease)
{
    struct cp_lif_bitmap_inputs input;
    struct lif_capabilities_owner before = *o;
    struct cp_lif_bitmap_guard g = guard(o->value.sequence);
    assert(!lif_capabilities_export_bitmap(o, &g, &input, sizeof(input)));
    assert(input.known == 31 && input.mode == 1);
    assert(!cp_lif_bitmap_owner_init(b, &g));
    g = guard(b->sequence + 2);
    assert(!cp_lif_bitmap_request(b, 1, &input, &g, lease, sizeof(*lease)));
    assert(lease->token && lease->logical_bytes == 25 && lease->origin == CP_LIF_ORIGIN_HOST_TEST);
    assert(!memcmp(&before, o, sizeof(before))); /* 0a alone has no state effect. */
}
static void transport_consumed(struct lif_capabilities_owner *o,
    struct cp_lif_bitmap_owner *b, const struct cp_lif_bitmap_lease *lease)
{
    struct lif_capabilities_owner before = *o;
    struct cp_lif_bitmap_owner prior = *b;
    struct cp_lif_bitmap_guard g = guard(b->sequence + 2);
    unsigned char actual[25];
    size_t i;
    memcpy(actual, lease->wire, sizeof(actual));
    for (i = 0; i < sizeof(actual); ++i) {
        actual[i] ^= 1;
        assert(cp_lif_bitmap_observe_transport_consumed(b, lease, actual, sizeof(actual), &g) == -EBADMSG);
        assert(!memcmp(&prior, b, sizeof(prior))); actual[i] ^= 1;
    }
    assert(!cp_lif_bitmap_observe_transport_consumed(b, lease, actual, sizeof(actual), &g));
    assert(!memcmp(&before, o, sizeof(before)));
}
static const unsigned char dynamic_schema5[] = {8,1,8,3,10,28,2,6,1,2,8,6,6,6,1,6,3,3,4,4,4,8,36,40,8,4,6,3};
static const unsigned char dynamic_schema6[] = {2,11,9,4,6,7,45,4,8,8,24};
static size_t dynamic_frame(unsigned char *rx, const unsigned char *bitmap,
                            unsigned first, unsigned second, unsigned type, int extra)
{
    unsigned commands[2] = {first, second};
    size_t pos = 5, c, i, j;
    memset(rx, 0x6b, CP_LIF_FRAME_MAX_RX_BYTES);
    rx[0] = 0xf0; rx[3] = (unsigned char)(0xb8u | type); rx[4] = 0xad;
    for (c = 0; c < 2 && commands[c]; ++c) {
        const unsigned char *schema = commands[c] == 5 ? dynamic_schema5 : dynamic_schema6;
        size_t count = commands[c] == 5 ? sizeof(dynamic_schema5) : sizeof(dynamic_schema6);
        unsigned base = commands[c] == 5 ? 0 : 0x40;
        rx[pos++] = (unsigned char)commands[c];
        for (i = 0; i < count; ++i) if (bitmap[(base + i) >> 3] & (1u << ((base + i) & 7)))
            for (j = 0; j < schema[i]; ++j) {
                assert(pos < CP_LIF_FRAME_MAX_BYTES - 3);
                rx[pos] = (unsigned char)((pos * 7 + i * 3 + j) % 255 + 1); ++pos;
            }
    }
    put16(rx + 1, (unsigned)(pos + 3)); rx[pos + 2] = 0x55; rx[pos + 3] = 0;
    checksum(rx); return pos + 3 + (size_t)extra;
}
static void dynamic_accepted(struct lif_capabilities_owner *o, struct cp_lif_bitmap_owner *b,
                             unsigned first, unsigned second)
{
    struct lif_capabilities_receipt fixed = o->value.receipt;
    struct cp_lif_bitmap_guard g = guard((o->value.sequence > b->sequence ? o->value.sequence : b->sequence) + 2);
    unsigned char rx[CP_LIF_FRAME_MAX_RX_BYTES];
    size_t i, j, n = dynamic_frame(rx, b->configured, first, second, 2, 1);
    errno = EILSEQ;
    assert(lif_capabilities_receive_dynamic(o, b, rx, n, &g) == 0 && errno == EILSEQ);
    assert(o->value.sequence == g.sequence_before && b->sequence == g.sequence_before);
    assert(!memcmp(&fixed, &o->value.receipt, sizeof(fixed)));
    assert(!memcmp(o->value.last_dynamic.decoded.frame, rx, n));
    assert(!memcmp(o->value.last_dynamic.context.bitmap, b->configured, 16));
    assert(o->value.last_dynamic.configured_matches_consumed && o->value.last_dynamic.owned_virtual_data);
    assert(o->value.last_dynamic.decoded.origin == CP_LIF_ORIGIN_HOST_TEST);
    assert(o->value.last_dynamic.decoded.command_count == (second ? 2 : 1));
    assert(o->value.last_dynamic.decoded.commands[0].command == first);
    if (second) assert(o->value.last_dynamic.decoded.commands[1].command == second);
    assert(o->value.last_dynamic.decoded.field_count > 0);
    for (i = 0; i < o->value.last_dynamic.decoded.field_count; ++i) {
        const struct cp_lif_field_view *f = &o->value.last_dynamic.decoded.fields[i];
        assert(f->length && (unsigned)f->offset + f->length < get16(rx + 1) - 2u);
        assert(b->configured[f->id >> 3] & (1u << (f->id & 7)));
        assert(f->command == 5 || f->command == 6);
        assert(f->length == (f->command == 5 ? dynamic_schema5[f->id] : dynamic_schema6[f->id - 0x40]));
        for (j = 0; j < f->length; ++j) assert(rx[f->offset + j]);
    }
    memset(rx, 0, sizeof(rx));
    assert(o->value.last_dynamic.decoded.frame[4] == 0xad);
    assert(!o->value.original_CP && !o->value.original_cache_admission);
    assert(!o->value.original_handler_executed && !o->value.original_event_delivery);
}
static void handshake_chain(void)
{
    struct lif_capabilities_owner o;
    struct cp_lif_bitmap_owner b = {0};
    struct cp_lif_bitmap_lease lease;
    unsigned char body[12], rx[CP_LIF_FRAME_MAX_RX_BYTES];
    uint64_t received, committed, request;
    size_t n;
    prepare_handshake(&o, 1, 1);
    assert(o.value.k == 4 && o.value.state == 2);
    receive9(&o, 1); received = o.value.sequence;
    memcpy(body, o.value.receipt.frame + 5, sizeof(body));
    assert(o.value.pending9_known && o.value.pending9 && o.value.pending9_body_known);
    assert(!memcmp(body, o.value.pending9_body, sizeof(body)) && o.value.pending9_sequence == received);
    assert(o.value.state == 2 && o.value.k == 4 && o.value.last_state_request == 2);
    consume(&o, lif_capabilities_consume_dispatch_event9_prefix);
    committed = o.value.state_commit_sequence;
    assert(o.value.state == 3 && committed == o.value.event9_sequence);
    assert(o.value.state_request_sequence == committed && o.value.last_state_request == 3);
    consume(&o, lif_capabilities_consume_dispatch_event9_prefix);
    request = o.value.state_request_sequence;
    assert(o.value.state == 3 && o.value.state_commit_sequence == committed);
    assert(request == o.value.event9_sequence && request > committed && o.value.pending9);
    assert(o.value.pending9_sequence == received && !memcmp(body, o.value.pending9_body, sizeof(body)));
    configure_bitmap(&o, &b, &lease); transport_consumed(&o, &b, &lease);
    dynamic_accepted(&o, &b, 6, 0);
    assert(o.value.state == 3 && !o.value.received5_sequence && o.value.received6_sequence == o.value.sequence);
    dynamic_accepted(&o, &b, 5, 0);
    assert(o.value.state == 4 && o.value.state_commit_sequence == o.value.sequence);
    dynamic_accepted(&o, &b, 6, 0);
    assert(o.value.state == 5 && o.value.state_commit_sequence == o.value.sequence);
    assert(o.value.last_state_request == 3 && o.value.state_request_sequence == request);
    {
        struct lif_capabilities_readback out;
        struct cp_lif_bitmap_guard current = guard(o.value.sequence);
        assert(!lif_capabilities_snapshot(&o, &current, &out, sizeof(out)));
        assert(out.state_known && out.state == 5 && out.origin == CP_LIF_ORIGIN_HOST_TEST);
        assert(!out.original_CP && !out.original_event_delivery && !out.original_handler_executed);
    }
    assert(o.value.receipt.sequence == received && o.value.diagnostic_only && o.value.owned_data_transport);
    committed = o.value.state_commit_sequence;
    n = make_frame(rx, 8, 2, 0); accepted(&o, rx, n, o.value.sequence + 2);
    assert(o.value.state == 5 && o.value.state_commit_sequence == committed);
    assert(o.value.last_state_request == 2 && o.value.state_request_sequence == o.value.sequence);
}
static void handshake_dynamic_order(void)
{
    struct lif_capabilities_owner o;
    struct cp_lif_bitmap_lease lease;
    unsigned first;
    for (first = 5; first <= 6; ++first) {
        struct cp_lif_bitmap_owner b = {0};
        prepare_handshake(&o, 1, 1); receive9(&o, 3);
        consume(&o, lif_capabilities_consume_dispatch_event9_prefix);
        configure_bitmap(&o, &b, &lease); transport_consumed(&o, &b, &lease);
        dynamic_accepted(&o, &b, first, 11 - first);
        assert(o.value.state_known && o.value.state == 5);
        assert(o.value.received5_sequence == o.value.sequence && o.value.received6_sequence == o.value.sequence);
        assert(o.value.state_commit_sequence == o.value.sequence && o.value.last_state_request == 3);
    }
}
static void handshake_unknown(void)
{
    struct lif_capabilities_owner o;
    struct cp_lif_bitmap_owner b = {0};
    struct cp_lif_bitmap_lease lease;
    uint64_t committed;
    prepare_handshake(&o, 1, 0);
    assert(!o.value.state_known && !o.value.state_commit_sequence);
    receive9(&o, 1); consume(&o, lif_capabilities_consume_dispatch_event9_prefix);
    assert(!o.value.state_known && o.value.last_state_request == 3 && !o.value.state_commit_sequence);
    configure_bitmap(&o, &b, &lease); transport_consumed(&o, &b, &lease);
    dynamic_accepted(&o, &b, 6, 5);
    assert(!o.value.state_known && !o.value.state_commit_sequence);
    consume(&o, lif_capabilities_consume_handshake_reset_store); committed = o.value.state_commit_sequence;
    receive9(&o, 2); /* Enabled control requests 3, known old 0 refuses the store. */
    assert(o.value.state == 0 && o.value.state_commit_sequence == committed);
    dynamic_accepted(&o, &b, 5, 6);
    assert(o.value.state == 0 && o.value.state_commit_sequence == committed);
    assert(o.value.last_state_request == 3);
}
static void handshake_kinds(void)
{
    struct lif_capabilities_owner o;
    unsigned type, kind, immediate;
    for (type = 0; type < 4; ++type) for (kind = 0; kind < 4; ++kind)
        for (immediate = 0; immediate < 2; ++immediate) {
            uint32_t old, expected;
            uint64_t kseq, applied;
            prepare_handshake(&o, type, 1); old = o.value.k; kseq = o.value.k_store_sequence;
            if (immediate) consume(&o, lif_capabilities_consume_dispatch_event9_prefix);
            receive9(&o, kind); applied = o.value.sequence;
            if (!immediate) {
                assert(o.value.state == 2 && o.value.k == old && o.value.k_store_sequence == kseq);
                consume(&o, lif_capabilities_consume_dispatch_event9_prefix); applied = o.value.sequence;
            } else assert(!o.value.pending9 && !o.value.pending9_body_known);
            expected = type == 2 && (kind == 1 || kind == 2) ? (kind == 1 ? 5u : 2u) : old;
            assert(o.value.k_known && o.value.k == expected && o.value.state == 3);
            {
                struct cp_lif_bitmap_inputs exported;
                struct cp_lif_bitmap_guard current = guard(o.value.sequence);
                assert(!lif_capabilities_export_bitmap(&o, &current, &exported, sizeof(exported)));
                assert((exported.known & CP_LIF_BITMAP_K_KNOWN) && exported.k == expected);
            }
            assert(o.value.k_store_sequence == ((type == 2 && (kind == 1 || kind == 2)) ? applied : kseq));
            if (!immediate && type == 2 && (kind == 1 || kind == 2)) {
                uint64_t committed = o.value.state_commit_sequence;
                consume(&o, lif_capabilities_consume_dispatch_event9_prefix);
                assert(o.value.k == expected && o.value.k_store_sequence == o.value.sequence);
                assert(o.value.state_commit_sequence == committed && o.value.pending9);
            }
        }
}
static void handshake_refusals(void)
{
    struct lif_capabilities_owner o, good;
    struct cp_lif_bitmap_guard g;
    unsigned char rx[CP_LIF_FRAME_MAX_RX_BYTES];
    size_t n;
    start(&o, 1); g = guard(4); n = make_frame(rx, 9, 2, 0);
    rejected(&o, rx, n, &g, -ENODATA);
    local_rejected(&o, lif_capabilities_consume_dispatch_event9_prefix, g, -ENODATA);
    prepare_handshake(&o, 2, 1); good = o; g = guard(o.value.sequence + 2);
    /* HOST_TEST unknown-input fault injection; no source history is claimed. */
    o.value.control_enabled_known = 0; rejected(&o, rx, n, &g, -ENODATA); o = good;
    o.value.property_known[0x22] = 0; rejected(&o, rx, n, &g, -ENODATA); o = good;
    o.value.z_known = 0; rejected(&o, rx, n, &g, -ENODATA); o = good;
    o.value.z = 1; rejected(&o, rx, n, &g, -ENOTSUP); o = good;
    rx[13] = 1; checksum(rx); rejected(&o, rx, n, &g, -ENODATA);
    rx[13] = 0; rx[14] = 1; checksum(rx); rejected(&o, rx, n, &g, -ENODATA);
    n = make_frame(rx, 9, 1, 0); rejected(&o, rx, n, &g, -ENODATA);
    n = make_frame(rx, 9, 2, 0); rx[10] ^= 1; rejected(&o, rx, n, &g, -EBADMSG);
    o.value.pending8_known = 0;
    local_rejected(&o, lif_capabilities_consume_dispatch_event9_prefix, g, -ENODATA); o = good;
    o.value.pending8 = 1;
    local_rejected(&o, lif_capabilities_consume_dispatch_event9_prefix, g, -ENOTSUP); o = good;
    o.value.pending9 = 1;
    local_rejected(&o, lif_capabilities_consume_dispatch_event9_prefix, g, -ENODATA); o = good;
    receive9(&o, 1); g = guard(o.value.sequence + 2); o.value.property_known[0x22] = 0;
    local_rejected(&o, lif_capabilities_consume_dispatch_event9_prefix, g, -ENODATA);
}
static void dynamic_rejected(struct lif_capabilities_owner *o, struct cp_lif_bitmap_owner *b,
    const unsigned char *rx, size_t n, struct cp_lif_bitmap_guard *g, int expected)
{
    struct lif_capabilities_owner before = *o;
    struct cp_lif_bitmap_owner prior = *b;
    errno = E2BIG;
    assert(lif_capabilities_receive_dynamic(o, b, rx, n, g) == expected && errno == E2BIG);
    assert(!memcmp(&before, o, sizeof(before)) && !memcmp(&prior, b, sizeof(prior)));
}
static void handshake_dynamic_failures(void)
{
    struct lif_capabilities_owner o;
    struct cp_lif_bitmap_owner b = {0};
    struct cp_lif_bitmap_lease lease;
    struct cp_lif_bitmap_inputs input;
    struct cp_lif_bitmap_guard g, bad;
    unsigned char rx[CP_LIF_FRAME_MAX_RX_BYTES];
    size_t n;
    prepare_handshake(&o, 1, 1); receive9(&o, 1);
    consume(&o, lif_capabilities_consume_dispatch_event9_prefix);
    configure_bitmap(&o, &b, &lease);
    n = dynamic_frame(rx, b.configured, 5, 6, 2, 1); g = guard(b.sequence + 2);
    dynamic_rejected(&o, &b, rx, n, &g, -ENODATA);
    transport_consumed(&o, &b, &lease); g = guard(b.sequence + 2);
    {
        struct lif_capabilities_owner other;
        struct cp_lif_bitmap_owner other_bitmap = {0};
        struct cp_lif_bitmap_lease other_lease;
        prepare_handshake(&other, 2, 1);
        configure_bitmap(&other, &other_bitmap, &other_lease);
        n = dynamic_frame(rx, other_bitmap.configured, 5, 6, 2, 1);
        dynamic_rejected(&o, &b, rx, n, &g, -EMSGSIZE); /* Real different K-derived schema. */
        n = dynamic_frame(rx, b.configured, 5, 6, 2, 1);
    }
    rx[10] ^= 1; dynamic_rejected(&o, &b, rx, n, &g, -EBADMSG); rx[10] ^= 1;
    rx[3] &= (unsigned char)~7u; checksum(rx); dynamic_rejected(&o, &b, rx, n, &g, -EBADMSG);
    n = dynamic_frame(rx, b.configured, 5, 6, 2, 1);
    rx[n - 1] = 1; dynamic_rejected(&o, &b, rx, n, &g, -EBADMSG); rx[n - 1] = 0;
    dynamic_rejected(&o, &b, rx, n + 1, &g, -EMSGSIZE);
    n = dynamic_frame(rx, b.configured, 5, 6, 2, 0);
    put16(rx + 1, (unsigned)n - 1); rx[n - 2] = 0x55; checksum(rx);
    dynamic_rejected(&o, &b, rx, n - 1, &g, -EMSGSIZE);
    n = dynamic_frame(rx, b.configured, 5, 6, 2, 1);
    rx[5] = 9; checksum(rx); dynamic_rejected(&o, &b, rx, n, &g, -ENOTSUP);
    n = dynamic_frame(rx, b.configured, 5, 6, 2, 1);
    bad = guard(o.value.sequence); dynamic_rejected(&o, &b, rx, n, &bad, -ESTALE);
    bad = guard(b.sequence); dynamic_rejected(&o, &b, rx, n, &bad, -ESTALE);
    bad = g; bad.owner_pid++; dynamic_rejected(&o, &b, rx, n, &bad, -EXDEV);
    bad = g; bad.origin = CP_LIF_ORIGIN_VIRTUAL_SOURCE; dynamic_rejected(&o, &b, rx, n, &bad, -EXDEV);
    bad = g; bad.sequence_after += 2; dynamic_rejected(&o, &b, rx, n, &bad, -EAGAIN);
    {
        struct cp_lif_bitmap_owner foreign = {0};
        struct cp_lif_bitmap_guard virtual_guard = g;
        virtual_guard.origin = CP_LIF_ORIGIN_VIRTUAL_SOURCE;
        assert(!cp_lif_bitmap_owner_init(&foreign, &virtual_guard));
        dynamic_rejected(&o, &foreign, rx, n, &g, -EXDEV);
    }
    dynamic_rejected(&o, &b, o.value.property, 20, &g, -EINVAL);
    dynamic_rejected(&o, &b, b.lease.wire, 25, &g, -EINVAL);
    dynamic_rejected(&o, &b, (const unsigned char *)&g, sizeof(g), &g, -EINVAL);
    dynamic_rejected(&o, &b, (const void *)(uintptr_t)(UINTPTR_MAX - 7), 20, &g, -EINVAL);
    dynamic_rejected(&o, &b, rx, SIZE_MAX, &g, -EINVAL);
    {
        struct tail_arena { unsigned char rx[CP_LIF_FRAME_MAX_RX_BYTES]; struct cp_lif_bitmap_owner bitmap; } a = {0};
        struct cp_lif_bitmap_lease local;
        struct cp_lif_bitmap_guard tail_guard;
        configure_bitmap(&o, &a.bitmap, &local);
        transport_consumed(&o, &a.bitmap, &local);
        (void)dynamic_frame(a.rx, a.bitmap.configured, 5, 6, 2, 1);
        tail_guard = guard(a.bitmap.sequence + 2);
        dynamic_rejected(&o, &a.bitmap, a.rx, offsetof(struct tail_arena, bitmap) + 1, &tail_guard, -EINVAL);
    }
    {
        struct lif_capabilities_owner before = o;
        union { struct cp_lif_bitmap_owner bitmap; struct cp_lif_bitmap_guard guard; } alias;
        alias.guard = g;
        assert(lif_capabilities_receive_dynamic(&o, &alias.bitmap, rx, n, &alias.guard) == -EINVAL);
        assert(lif_capabilities_receive_dynamic(&o, (void *)&o.value, rx, n, &g) == -EINVAL);
        assert(lif_capabilities_receive_dynamic(&o, (void *)((unsigned char *)&b + 1), rx, n, &g) == -EINVAL);
        assert(lif_capabilities_receive_dynamic(&o, (void *)(uintptr_t)(UINTPTR_MAX - 7), rx, n, &g) == -EINVAL);
        assert(!memcmp(&before, &o, sizeof(o)));
    }
    dynamic_accepted(&o, &b, 6, 5); assert(o.value.state == 5);
    g = guard(o.value.sequence);
    assert(!lif_capabilities_export_bitmap(&o, &g, &input, sizeof(input)));
    g = guard(b.sequence + 2);
    assert(!cp_lif_bitmap_request(&b, 1, &input, &g, &lease, sizeof(lease)));
    g = guard(b.sequence + 2);
    n = dynamic_frame(rx, b.configured, 5, 6, 2, 1);
    dynamic_rejected(&o, &b, rx, n, &g, -EAGAIN);
}
int main(int argc, char **argv)
{
    FILE *file;
    assert(argc == 3);
    stage_bytes = malloc(CP_PROPERTY_STAGE_BYTES);
    assert(stage_bytes != NULL);
    file = fopen(argv[2], "rb"); assert(file != NULL);
    assert(fread(stage_bytes, 1, CP_PROPERTY_STAGE_BYTES, file) == CP_PROPERTY_STAGE_BYTES);
    assert(fgetc(file) == EOF); assert(fclose(file) == 0);
    assert(fnv(stage_bytes, CP_PROPERTY_STAGE_BYTES) == CP_PROPERTY_STAGE_FNV1A64);
    if (!strcmp(argv[1], "ordered")) ordered();
    else if (!strcmp(argv[1], "prez")) prez();
    else if (!strcmp(argv[1], "refresh")) refresh_order();
    else if (!strcmp(argv[1], "selectors")) selectors();
    else if (!strcmp(argv[1], "zvalues")) zvalues(0);
    else if (!strcmp(argv[1], "zrefusal")) zvalues(1);
    else if (!strcmp(argv[1], "dbit")) dbit();
    else if (!strcmp(argv[1], "export")) export_bitmap();
    else if (!strcmp(argv[1], "kind-store")) kind_store();
    else if (!strcmp(argv[1], "guards")) guards();
    else if (!strcmp(argv[1], "init")) initialization();
    else if (!strcmp(argv[1], "lengths")) frame_lengths();
    else if (!strcmp(argv[1], "bytes")) frame_bytes();
    else if (!strcmp(argv[1], "types")) frame_types();
    else if (!strcmp(argv[1], "commands")) frame_commands();
    else if (!strcmp(argv[1], "aliases")) aliases();
    else if (!strcmp(argv[1], "spans")) spans();
    else if (!strcmp(argv[1], "errno")) errno_readback();
    else if (!strcmp(argv[1], "frozen")) frozen_stage();
    else if (!strcmp(argv[1], "immutable")) immutable();
    else if (!strcmp(argv[1], "public-stage")) public_stage_readback();
    else if (!strcmp(argv[1], "handshake-resets")) handshake_resets();
    else if (!strcmp(argv[1], "handshake-chain")) handshake_chain();
    else if (!strcmp(argv[1], "handshake-dynamic-order")) handshake_dynamic_order();
    else if (!strcmp(argv[1], "handshake-unknown")) handshake_unknown();
    else if (!strcmp(argv[1], "handshake-kinds")) handshake_kinds();
    else if (!strcmp(argv[1], "handshake-refusals")) handshake_refusals();
    else if (!strcmp(argv[1], "handshake-dynamic-failures")) handshake_dynamic_failures();
    else assert(0 && "unknown self-test");
    free(stage_bytes);
    puts("ok");
    return 0;
}
