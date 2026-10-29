/* SPDX-License-Identifier: MIT */
#include "osd-pin-format.h"
#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/wait.h>
#include <unistd.h>

static unsigned char backing[FULL_OSD_POOL_BYTES];
static unsigned int outputs[4];
static struct full_osd_format_state state;

static unsigned int u32(const unsigned char *p)
{
    return p[0] | (unsigned int)p[1] << 8 | (unsigned int)p[2] << 16 | (unsigned int)p[3] << 24;
}

static void put32(unsigned char *p, unsigned int n)
{
    for (unsigned int i = 0; i < 4; ++i) p[i] = (unsigned char)(n >> (8 * i));
}

static void hex(const char *label, const unsigned char *p, unsigned int n)
{
    printf("%s=", label);
    for (unsigned int i = 0; i < n; ++i) printf("%02x", p[i]);
    putchar('\n');
}

static unsigned int known_count(const unsigned char *p, unsigned int n)
{
    unsigned int count = 0;
    for (unsigned int i = 0; i < n; ++i) {
        assert(p[i] <= 1);
        count += p[i];
    }
    return count;
}

static void bind_pool(void)
{
    assert(FULL_OSD_POOL_SLOTS == 16 && FULL_OSD_POOL_BYTES == 4096);
    assert(!full_osd_pool_bind(backing, sizeof backing, 0x600100000ULL, 0x90010000u));
}

static unsigned int create(unsigned int side, unsigned int kind, unsigned int peer)
{
    unsigned int handle = 0, used = 0;
    unsigned char data[256], known[256];
    assert(!full_osd_pool_allocate(side, &handle));
    if (kind == FULL_OSD_FORMAT_TAG101)
        assert(!full_osd_format_build_completion101(peer, data, known, sizeof data, &used));
    else
        assert(!full_osd_format_build_initial(kind, data, known, sizeof data, &used));
    assert(used >= 80 && used <= 192);
    assert(!full_osd_pool_write(side, handle, 0, data, known, sizeof data));
    return handle;
}

static void notice(unsigned int side, unsigned int handle, unsigned char *data)
{
    unsigned char known[80];
    assert(!full_osd_notice_build(side, handle, data, known, 80));
    assert(known_count(known, 80) == 76);
}

static void setup(void)
{
    bind_pool();
    for (unsigned int i = 0; i < 4; ++i) {
        outputs[i] = create(FULL_OSD_PEER_SIDE, FULL_OSD_FORMAT_KEY0, 0);
        assert(!full_osd_pool_share(FULL_OSD_PEER_SIDE, outputs[i]));
        assert(!full_osd_pool_open(FULL_OSD_PINMEM_SIDE, outputs[i]));
    }
    assert(!full_osd_format_state_init(&state, outputs));
}

static unsigned int publish(unsigned int kind, unsigned int peer)
{
    unsigned int h = create(FULL_OSD_PINMEM_SIDE, kind, peer);
    assert(!full_osd_pool_share(FULL_OSD_PINMEM_SIDE, h));
    return h;
}

static int consume(unsigned int handle)
{
    unsigned char packet[80];
    notice(FULL_OSD_PINMEM_SIDE, handle, packet);
    return full_osd_format_consume_notice(&state, FULL_OSD_PINMEM_SID,
                                          FULL_OSD_PEER_SID, packet, sizeof packet);
}

static void rewrite(unsigned int handle, unsigned int offset, const unsigned char *data,
                     const unsigned char *known, unsigned int bytes)
{
    assert(!full_osd_pool_write(FULL_OSD_PINMEM_SIDE, handle, offset, data, known, bytes));
}

static void cleanup(void)
{
    struct full_osd_pool_snapshot pool;
    full_osd_pool_snapshot(&pool);
    for (unsigned int i = 0; i < FULL_OSD_POOL_SLOTS; ++i) {
        if (!pool.slots[i].live) continue;
        /* Test teardown explicitly acquires any still-closed shared owner. */
        if (pool.slots[i].consumer_side && !pool.slots[i].consumer_open)
            assert(!full_osd_pool_open(pool.slots[i].consumer_side, pool.slots[i].handle));
        if (pool.slots[i].consumer_side)
            assert(!full_osd_pool_release(pool.slots[i].consumer_side, pool.slots[i].handle));
        if (pool.slots[i].creator_open)
            assert(!full_osd_pool_release(pool.slots[i].creator_side, pool.slots[i].handle));
    }
    full_osd_pool_snapshot(&pool);
    assert(!pool.live && !pool.faults);
}

static void builders(void)
{
    unsigned char data[256], known[256];
    unsigned int used = 0;
    for (unsigned int i = 0; i < 3; ++i) {
        unsigned int tag = i == 0 ? 0 : i == 1 ? 0x100 : 0x102;
        assert(!full_osd_format_build_initial(tag, data, known, sizeof data, &used));
        assert(u32(data) == 0x534f5353 && u32(data + 36) == tag);
        assert(used == (i == 0 ? 128u : i == 1 ? 192u : 96u));
        assert(known_count(known, used) == (i == 0 ? 128u : i == 1 ? 71u : 90u));
        assert(!memcmp(data + 4, i == 0 ? "\1\0\0\0" : "\0\0\0\1", 4));
        assert(u32(data + 8) == (i == 0 ? 3u : 0u));
        for (unsigned int j = used; j < sizeof data; ++j)
            assert(data[j] == 0xa5 && !known[j]);
        if (i == 1) {
            assert(u32(data + 64) == 1 && !data[72] && !data[73] && !data[76]);
            for (unsigned int j = 64; j < used; ++j)
                if (!known[j]) assert(data[j] == 0xa5);
        }
        if (i == 2) {
            assert(u32(data + 64) == 0xffffffffu && !data[68] && !data[69]);
            for (unsigned int j = 72; j < 92; ++j) assert(data[j] == 0xff && known[j]);
            assert(data[70] == 0xa5 && !known[70] && data[95] == 0xa5 && !known[95]);
        }
        hex(i == 0 ? "KEY0" : i == 1 ? "TAG100" : "TAG102", data, used);
        hex(i == 0 ? "KEY0_KNOWN" : i == 1 ? "TAG100_KNOWN" : "TAG102_KNOWN", known, used);
    }
}

static void builder_rejections(void)
{
    unsigned char data[256], mask[256], before[256];
    memset(data, 0x6d, sizeof data); memcpy(before, data, sizeof before);
    memset(mask, 0x9b, sizeof mask);
    unsigned int used = 0xfeed;
    assert(full_osd_format_build_initial(0x101, data, mask, 256, &used) == -1021);
    assert(full_osd_format_build_initial(3, data, mask, 256, &used) == -1021);
    assert(full_osd_format_build_initial(0, data, mask, 255, &used) == -1021);
    assert(full_osd_format_build_initial(0, NULL, mask, 256, &used) == -1021);
    assert(full_osd_format_build_initial(0, data, NULL, 256, &used) == -1021);
    assert(full_osd_format_build_initial(0, data, mask, 256, NULL) == -1021);
    assert(!memcmp(before, data, sizeof data) && used == 0xfeed && mask[0] == 0x9b);
}

static void completion_builder(void)
{
    setup();
    unsigned char data[256], known[256]; unsigned int used;
    assert(!full_osd_format_build_completion101(outputs[2], data, known, 256, &used));
    assert(used == 80 && u32(data + 36) == 0x101 && u32(data + 48) == 16);
    assert(!u32(data + 64) && u32(data + 68) == outputs[2] && !u32(data + 76));
    assert(known_count(known + 64, 16) == 14 && !known[74] && !known[75]);
    assert(known_count(known, 256) == 78 && data[74] == 0xa5 && data[75] == 0xa5);
    hex("TAG101", data, used); hex("TAG101_KNOWN", known, used);
    unsigned int wrong = create(FULL_OSD_PINMEM_SIDE, 0x100, 0);
    assert(!full_osd_pool_share(FULL_OSD_PINMEM_SIDE, wrong));
    assert(full_osd_format_build_completion101(wrong, data, known, 256, &used) == -1021);
    assert(full_osd_format_build_completion101(0xffffu, data, known, 256, &used) == -1021);
    assert(full_osd_format_build_completion101(outputs[2], data, known, 255, &used) == -1021);
    cleanup();
}

static void parser(void)
{
    unsigned char data[256], known[256]; unsigned int used;
    struct full_osd_format_view out;
    for (unsigned int i = 0; i < 3; ++i) {
        unsigned int kind = i == 0 ? 0 : i == 1 ? 0x100 : 0x102;
        assert(!full_osd_format_build_initial(kind, data, known, 256, &used));
        assert(!full_osd_format_parse(data, known, used, &out));
        assert(out.tag == kind && out.payload_offset == 64 && out.payload_bytes == used - 64);
        assert(!memcmp(out.payload, data + 64, out.payload_bytes));
        assert(!memcmp(out.known, known + 64, out.payload_bytes));
        assert(!full_osd_format_parse(data, known, 256, &out));
    }
}

static void parser_bounds(void)
{
    unsigned char data[256], known[256], corrupt[256]; unsigned int used;
    struct full_osd_format_view out, before;
    assert(!full_osd_format_build_initial(0x100, data, known, 256, &used));
    memset(&out, 0x61, sizeof out); before = out;
    const unsigned int offsets[] = {0, 4, 8, 12, 16, 32, 36, 40, 44, 48, 52};
    const unsigned int values[] = {0xffffffffu, 0, 0x20, 0xffffffc0u, 0x40, 2};
    for (unsigned int i = 0; i < sizeof offsets / sizeof offsets[0]; ++i) {
        for (unsigned int j = 0; j < sizeof values / sizeof values[0]; ++j) {
            if (u32(data + offsets[i]) == values[j]) continue;
            memcpy(corrupt, data, sizeof data); put32(corrupt + offsets[i], values[j]);
            assert(full_osd_format_parse(corrupt, known, 256, &out) == -1021);
            assert(!memcmp(&out, &before, sizeof out));
        }
    }
    for (unsigned int n = 0; n < 192; ++n)
        assert(full_osd_format_parse(data, known, n, &out) == -1021);
    assert(full_osd_format_parse(data, known, 257, &out) == -1021);
    assert(full_osd_format_parse(NULL, known, 256, &out) == -1021);
    assert(full_osd_format_parse(data, NULL, 256, &out) == -1021);
    assert(full_osd_format_parse(data, known, 256, NULL) == -1021);
}

static void parser_masks(void)
{
    unsigned char data[256], known[256]; unsigned int used;
    struct full_osd_format_view out;
    assert(!full_osd_format_build_initial(0x100, data, known, 256, &used));
    const unsigned int offsets[] = {0, 4, 8, 12, 16, 32, 36, 40, 44, 48, 52};
    for (unsigned int i = 0; i < sizeof offsets / sizeof offsets[0]; ++i) {
        known[offsets[i]] = 0;
        assert(full_osd_format_parse(data, known, 256, &out) == -1021);
        known[offsets[i]] = 1;
    }
    known[21] = 0; data[21] = 0xd6; known[60] = 0; data[60] = 0x44;
    data[80] = 0x73;
    assert(!full_osd_format_parse(data, known, 256, &out));
    assert(out.payload[16] == 0x73 && out.known[16] == 0);
    known[80] = 2;
    assert(full_osd_format_parse(data, known, 256, &out) == -1021);
}

static void notices(void)
{
    setup();
    unsigned int source = publish(0x100, 0);
    for (unsigned int side = 1; side <= 2; ++side) {
        unsigned int handle = side == 1 ? source : outputs[0];
        unsigned int src = side == 1 ? FULL_OSD_PINMEM_SID : FULL_OSD_PEER_SID;
        unsigned int dst = side == 1 ? FULL_OSD_PEER_SID : FULL_OSD_PINMEM_SID;
        unsigned char data[80], mask[80]; struct full_osd_mapping map;
        assert(!full_osd_notice_build(side, handle, data, mask, sizeof data));
        assert(!full_osd_notice_validate(side, src, dst, data, sizeof data, &map));
        assert(map.handle == handle && map.unit == 0xe1700 && map.extent == 256);
        assert(u32(data + 44) == dst && u32(data + 60) == src);
        assert(u32(data + 32) == 1 && u32(data + 36) == 3 && !u32(data + 40));
        assert(u32(data + 48) == 1 && u32(data + 52) == 3 && !u32(data + 56));
        assert(known_count(mask, sizeof mask) == 76 && u32(data + 20) == 0xa5a5a5a5u);
        memset(data + 20, 0x1e, 4);
        assert(!full_osd_notice_validate(side, src, dst, data, sizeof data, &map));
        hex(side == 1 ? "NOTICE_PINMEM" : "NOTICE_PEER", data, sizeof data);
    }
    cleanup();
}

static void notice_rejections(void)
{
    setup(); unsigned int h = publish(0x100, 0);
    unsigned char data[80], copy[80]; notice(1, h, data);
    struct full_osd_mapping map, before; memset(&map, 0x82, sizeof map); before = map;
    for (unsigned int i = 0; i < 80; ++i) {
        if (i >= 20 && i < 24) continue;
        memcpy(copy, data, 80); copy[i] ^= 0x80;
        assert(full_osd_notice_validate(1, FULL_OSD_PINMEM_SID, FULL_OSD_PEER_SID,
                                         copy, 80, &map) == -1021);
        assert(!memcmp(&map, &before, sizeof map));
    }
    assert(full_osd_notice_validate(2, FULL_OSD_PEER_SID, FULL_OSD_PINMEM_SID, data, 80, &map) == -1021);
    assert(full_osd_notice_validate(1, FULL_OSD_PINMEM_SID + 1, FULL_OSD_PEER_SID, data, 80, &map) == -1021);
    assert(full_osd_notice_validate(1, FULL_OSD_PINMEM_SID, FULL_OSD_PEER_SID + 1, data, 80, &map) == -1021);
    assert(full_osd_notice_validate(1, FULL_OSD_PINMEM_SID, FULL_OSD_PEER_SID, data, 79, &map) == -1021);
    assert(full_osd_notice_validate(0, 0, 0, data, 80, &map) == -1021);
    cleanup();
}

static void initialization(void)
{
    setup();
    assert(full_osd_format_state_init(&state, outputs) == -1021);
    for (unsigned int i = 0; i < 4; ++i) {
        const struct full_osd_format_plane *p = &state.outputs[i];
        assert(p->handle == outputs[i] && p->ordinal == i && p->payload_bytes == 64 && p->reloads == 1);
        assert(p->selection_mask_known == 1 && p->selection_mask == 0);
        assert(known_count(p->known, 64) == 64);
        for (unsigned int j = 0; j < 64; ++j) assert(!p->payload[j]);
        assert(!state.incoming100[i].handle && !state.incoming101[i].handle && !state.incoming102[i].handle);
    }
    struct full_osd_format_state bad = {0}; unsigned int duplicate[4];
    memcpy(duplicate, outputs, sizeof duplicate); duplicate[2] = duplicate[1];
    assert(full_osd_format_state_init(&bad, duplicate) == -1021 && !bad.initialized);
    assert(!state.ready && !state.opens && !state.notices);
    cleanup();
}

static void init_bad_data(void)
{
    setup(); struct full_osd_format_state fresh = {0};
    unsigned char one = 1, known = 1;
    assert(!full_osd_pool_write(2, outputs[1], 64, &one, &known, 1));
    assert(full_osd_format_state_init(&fresh, outputs) == -1021 && !fresh.initialized);
    assert(!state.outputs[1].payload[0]);
    cleanup();
}

static void initial100_102(void)
{
    setup();
    for (unsigned int i = 0; i < 4; ++i) assert(!consume(publish(0x100, 0)));
    for (unsigned int i = 0; i < 4; ++i) assert(!consume(publish(0x102, 0)));
    assert(state.new100 == 4 && state.new102 == 4 && !state.new101 && state.opens == 8 && state.notices == 8);
    assert(!state.ready && !state.readiness_post_pending && !state.fifo_submissions && !state.output_callbacks);
    struct full_osd_pool_snapshot pool; full_osd_pool_snapshot(&pool);
    assert(pool.live == 12 && pool.opens == 12 && pool.releases == 0);
    for (unsigned int i = 0; i < 4; ++i) {
        assert(state.incoming100[i].handle != state.incoming102[i].handle);
        assert(known_count(state.incoming100[i].known, 128) == 7);
        assert(known_count(state.incoming102[i].known, 32) == 26);
        assert(!state.incoming101[i].handle);
    }
    cleanup();
}

static void complete16(void)
{
    setup();
    for (unsigned int i = 0; i < 4; ++i) assert(!consume(publish(0x101, outputs[i])));
    assert(!state.ready && state.new101 == 4);
    for (unsigned int i = 0; i < 4; ++i) assert(!consume(publish(0x100, 0)));
    for (unsigned int i = 0; i < 4; ++i) {
        assert(!consume(publish(0x102, 0)));
        assert(state.ready == (i == 3));
    }
    assert(state.new100 == 4 && state.new101 == 4 && state.new102 == 4);
    assert(state.opens == 12 && state.retained_opens == 12 && state.notices == 12);
    assert(state.ready && state.readiness_transitions == 1 && state.readiness_post_pending == 1);
    assert(!state.faults && !state.unsupported_work && !state.completion_callbacks && !state.output_callbacks && !state.fifo_submissions);
    struct full_osd_pool_snapshot pool; full_osd_pool_snapshot(&pool);
    assert(pool.live == 16 && pool.allocations == 16 && pool.shares == 16 && pool.opens == 16 && !pool.releases);
    for (unsigned int i = 0; i < 16; ++i) {
        assert(pool.slots[i].owners == 2 && pool.slots[i].open_count == 2);
        assert(pool.slots[i].creator_open == 1 && pool.slots[i].consumer_open == 1);
    }
    for (unsigned int i = 0; i < 4; ++i) {
        assert(u32(state.incoming101[i].payload + 4) == outputs[i]);
        assert(known_count(state.incoming101[i].known, 16) == 14);
        assert(!state.incoming101[i].known[10] && !state.incoming101[i].known[11]);
    }
    puts("PERSISTENT_RESOURCES=16"); puts("PERSISTENT_OWNERS=32"); puts("PERSISTENT_OPENS=32");
    cleanup();
}

static void mutation(void)
{
    setup(); unsigned int h = publish(0x100, 0); assert(!consume(h));
    unsigned char original[256], original_known[256], actual[256], actual_known[256];
    assert(!full_osd_pool_read(1, h, 0, original, original_known, sizeof original));
    struct full_osd_pool_snapshot before, after; full_osd_pool_snapshot(&before);
    const unsigned char rows[5] = {0}, known[5] = {1, 1, 1, 1, 1};
    assert(!full_osd_format_apply_inactive100(h, rows, known));
    assert(!full_osd_pool_read(1, h, 0, actual, actual_known, sizeof actual));
    full_osd_pool_snapshot(&after);
    assert(after.opens == before.opens && after.allocations == before.allocations &&
           after.shares == before.shares && after.writes == before.writes + 1 &&
           after.reads == before.reads + 2);
    assert(!u32(actual + 64) && u32(original + 64) == 1);
    assert(!memcmp(original, actual, 64) && !memcmp(original + 68, actual + 68, 188));
    assert(!memcmp(original_known, actual_known, sizeof actual_known));
    assert(state.opens == 1 && state.notices == 1 && !state.reload100 && state.incoming100[0].reloads == 1);
    assert(u32(state.incoming100[0].payload) == 1 && state.last_handler_status == 0);
    assert(!state.faults && !state.fifo_submissions && !state.output_callbacks);
    cleanup();
}

static void mutation_gates(void)
{
    setup(); unsigned int h = publish(0x100, 0); assert(!consume(h));
    unsigned char rows[5] = {0}, known[5] = {1, 1, 1, 1, 1};
    struct full_osd_pool_snapshot before, after; full_osd_pool_snapshot(&before);
    for (unsigned int i = 0; i < 5; ++i) {
        rows[i] = 1;
        assert(full_osd_format_apply_inactive100(h, rows, known) == -1021);
        rows[i] = 0; known[i] = 0;
        assert(full_osd_format_apply_inactive100(h, rows, known) == -1021);
        known[i] = 1;
    }
    assert(full_osd_format_apply_inactive100(h, NULL, known) == -1021);
    full_osd_pool_snapshot(&after);
    assert(after.reads == before.reads && after.writes == before.writes && after.opens == before.opens);
    assert(u32(state.incoming100[0].payload) == 1 && state.notices == 1);
    cleanup();
}

static void explicit_count0_notice(void)
{
    setup(); unsigned int h = publish(0x100, 0); assert(!consume(h));
    const unsigned char rows[5] = {0}, known[5] = {1, 1, 1, 1, 1};
    assert(!full_osd_format_apply_inactive100(h, rows, known));
    /* Explicit negative/frontier packet, never emitted by apply_inactive100. */
    assert(!consume(h));
    assert(!u32(state.incoming100[0].payload) && state.last_handler_status == 13);
    assert(state.last_outer_status == 0 && state.opens == 1 && state.reload100 == 1);
    cleanup();
}

static void same_count_reload(void)
{
    setup(); unsigned int h = publish(0x100, 0); assert(!consume(h));
    unsigned char opaque = 0x67, unknown = 0; rewrite(h, 81, &opaque, &unknown, 1);
    assert(!consume(h));
    assert(state.incoming100[0].payload[17] == 0x67 && !state.incoming100[0].known[17]);
    assert(state.incoming100[0].reloads == 2 && state.opens == 1 && state.last_handler_status == 0);
    cleanup();
}

static void duplicate(unsigned int kind)
{
    setup(); unsigned int h = publish(kind, kind == 0x101 ? outputs[0] : 0); assert(!consume(h));
    struct full_osd_format_state before = state;
    struct full_osd_pool_snapshot pool_before, after; full_osd_pool_snapshot(&pool_before);
    assert(consume(h) == -1021); full_osd_pool_snapshot(&after);
    assert(!memcmp(&before, &state, sizeof state) && after.opens == pool_before.opens && after.reads == pool_before.reads);
    cleanup();
}

static void invalid_business(unsigned int kind, unsigned int offset, int make_unknown)
{
    setup(); unsigned int h = publish(kind, kind == 0x101 ? outputs[0] : 0);
    unsigned char data = make_unknown ? 0 : 1;
    unsigned char known = make_unknown ? 0 : 1;
    rewrite(h, 64 + offset, &data, &known, 1);
    assert(consume(h) == -1021 && state.faults == 1 && state.opens == 1 && state.retained_opens == 1);
    assert(state.unsupported_work == (unsigned int)!make_unknown);
    assert(!state.notices && !state.ready && !state.output_callbacks && !state.completion_callbacks && !state.fifo_submissions);
    struct full_osd_pool_snapshot before, after; full_osd_pool_snapshot(&before);
    assert(before.live == 5 && before.slots[4].owners == 2 && before.slots[4].open_count == 2);
    assert(consume(h) == -1021); full_osd_pool_snapshot(&after);
    assert(after.opens == before.opens && after.reads == before.reads);
    cleanup();
}

static void bad_completion_owner(void)
{
    setup(); unsigned int h = publish(0x101, outputs[0]);
    unsigned char value[4], known[4] = {1, 1, 1, 1}; put32(value, h);
    rewrite(h, 68, value, known, 4);
    assert(consume(h) == -1021 && state.faults && !state.new101 && state.opens == 1);
    cleanup();
}

static void duplicate_completion_owner(void)
{
    setup(); unsigned int a = publish(0x101, outputs[1]); assert(!consume(a));
    unsigned int b = publish(0x101, outputs[1]);
    assert(consume(b) == -1021 && state.faults && state.new101 == 1 && state.opens == 2);
    assert(state.incoming101[0].handle == a && !state.incoming101[1].handle);
    cleanup();
}

static void opaque102(void)
{
    setup(); unsigned int h = publish(0x102, 0);
    unsigned char arbitrary[2] = {0x37, 0xf1}, unknown[2] = {0};
    rewrite(h, 70, arbitrary, unknown, 2); rewrite(h, 92, arbitrary, unknown, 2);
    assert(!consume(h));
    assert(state.incoming102[0].payload[6] == 0x37 && state.incoming102[0].payload[7] == 0xf1);
    assert(!state.incoming102[0].known[6] && !state.incoming102[0].known[7]);
    assert(state.incoming102[0].payload[28] == 0x37 && !state.incoming102[0].known[28]);
    assert(!state.faults && state.new102 == 1 && !state.output_callbacks);
    cleanup();
}

static void corrupt_buffer(void)
{
    setup(); unsigned int h = publish(0x100, 0);
    unsigned char bad = 0, known = 1; rewrite(h, 0, &bad, &known, 1);
    assert(consume(h) == -1021 && state.opens == 1 && state.faults == 1 && !state.new100);
    assert(state.retained_opens == 1 && !state.notices && !state.ready);
    cleanup();
}

static void wrong_mapping(void)
{
    setup(); unsigned int h = publish(0x100, 0); assert(!consume(h));
    ++state.incoming100[0].mapping.physical;
    struct full_osd_pool_snapshot before, after; full_osd_pool_snapshot(&before);
    assert(consume(h) == -1021); full_osd_pool_snapshot(&after);
    assert(after.reads == before.reads && after.opens == before.opens && !state.faults);
    cleanup();
}

static void packet_no_mutation(void)
{
    setup(); unsigned int h = publish(0x100, 0); unsigned char data[80]; notice(1, h, data);
    data[26] = 3;
    struct full_osd_format_state before = state;
    struct full_osd_pool_snapshot pool_before, after; full_osd_pool_snapshot(&pool_before);
    assert(full_osd_format_consume_notice(&state, FULL_OSD_PINMEM_SID, FULL_OSD_PEER_SID, data, 80) == -1021);
    assert(!memcmp(&before, &state, sizeof state)); full_osd_pool_snapshot(&after);
    assert(after.opens == pool_before.opens && after.reads == pool_before.reads && after.releases == 0);
    cleanup();
}

static void opened_by_endpoint(void)
{
    setup(); unsigned int h = publish(0x100, 0); unsigned char data[80]; notice(1, h, data);
    struct full_osd_mapping mapping, bad;
    assert(full_osd_pool_mapping(2, h, &mapping) == -1021);
    assert(!full_osd_pool_open(2, h));
    assert(!full_osd_pool_mapping(2, h, &mapping));
    struct full_osd_pool_snapshot before, after; full_osd_pool_snapshot(&before);
    bad = mapping; ++bad.physical;
    assert(full_osd_format_consume_opened_notice(&state, FULL_OSD_PINMEM_SID,
        FULL_OSD_PEER_SID, data, 80, &bad) == -1021);
    assert(!state.opens && !state.notices);
    assert(!full_osd_format_consume_opened_notice(&state, FULL_OSD_PINMEM_SID,
        FULL_OSD_PEER_SID, data, 80, &mapping));
    full_osd_pool_snapshot(&after);
    assert(after.opens == before.opens && after.reads == before.reads + 1);
    assert(state.opens == 1 && state.notices == 1 && state.incoming100[0].handle == h);
    assert(full_osd_format_consume_opened_notice(&state, FULL_OSD_PINMEM_SID,
        FULL_OSD_PEER_SID, data, 80, &mapping) == -1021);
    assert(full_osd_format_consume_opened_notice(&state, FULL_OSD_PINMEM_SID,
        FULL_OSD_PEER_SID, data, 80, NULL) == -1021);
    cleanup();
}

static void foreign_process(void)
{
    setup(); unsigned int h = publish(0x100, 0); unsigned char data[80]; notice(1, h, data);
    struct full_osd_format_state before = state;
    pid_t child = fork(); assert(child >= 0);
    if (!child) {
        struct full_osd_format_state copy;
        assert(full_osd_format_consume_notice(&state, FULL_OSD_PINMEM_SID, FULL_OSD_PEER_SID, data, 80) == -1021);
        full_osd_format_snapshot(&state, &copy);
        assert(!copy.initialized && !copy.owner_pid && !copy.opens);
        _exit(0);
    }
    int status; assert(waitpid(child, &status, 0) == child && WIFEXITED(status) && !WEXITSTATUS(status));
    assert(!memcmp(&before, &state, sizeof state)); assert(!consume(h));
    cleanup();
}

int main(int argc, char **argv)
{
    assert(argc == 2);
    const char *name = argv[1];
    if (!strcmp(name, "BUILDERS")) builders();
    else if (!strcmp(name, "BUILDER_REJECTIONS")) builder_rejections();
    else if (!strcmp(name, "COMPLETION_BUILDER")) completion_builder();
    else if (!strcmp(name, "PARSER")) parser();
    else if (!strcmp(name, "PARSER_BOUNDS")) parser_bounds();
    else if (!strcmp(name, "PARSER_KNOWN_MASK")) parser_masks();
    else if (!strcmp(name, "NOTICES_BOTH_DIRECTIONS")) notices();
    else if (!strcmp(name, "NOTICE_REJECTIONS")) notice_rejections();
    else if (!strcmp(name, "INITIALIZATION")) initialization();
    else if (!strcmp(name, "INIT_BAD_DATA")) init_bad_data();
    else if (!strcmp(name, "INITIAL100_102_NOT_READY")) initial100_102();
    else if (!strcmp(name, "ALL16_PERSISTENT")) complete16();
    else if (!strcmp(name, "MUTABLE100_COUNT0")) mutation();
    else if (!strcmp(name, "SOURCE100_ROW_GATES")) mutation_gates();
    else if (!strcmp(name, "EXPLICIT_COUNT0_NOTICE_STATUS13")) explicit_count0_notice();
    else if (!strcmp(name, "MUTABLE100_SAME_COUNT")) same_count_reload();
    else if (!strcmp(name, "DUPLICATE101")) duplicate(0x101);
    else if (!strcmp(name, "DUPLICATE102")) duplicate(0x102);
    else if (!strcmp(name, "ACTIVE100")) invalid_business(0x100, 8, 0);
    else if (!strcmp(name, "ACTIVE101")) invalid_business(0x101, 8, 0);
    else if (!strcmp(name, "ACTIVE102")) invalid_business(0x102, 4, 0);
    else if (!strcmp(name, "UNKNOWN100_INPUT")) invalid_business(0x100, 8, 1);
    else if (!strcmp(name, "UNKNOWN101_INPUT")) invalid_business(0x101, 4, 1);
    else if (!strcmp(name, "UNKNOWN102_INPUT")) invalid_business(0x102, 4, 1);
    else if (!strcmp(name, "BAD_COMPLETION_OWNER")) bad_completion_owner();
    else if (!strcmp(name, "DUPLICATE_COMPLETION_OWNER")) duplicate_completion_owner();
    else if (!strcmp(name, "OPAQUE102_HOLES")) opaque102();
    else if (!strcmp(name, "CORRUPT_BUFFER_RETAINS")) corrupt_buffer();
    else if (!strcmp(name, "WRONG_MAPPING")) wrong_mapping();
    else if (!strcmp(name, "PACKET_NO_MUTATION")) packet_no_mutation();
    else if (!strcmp(name, "ENDPOINT_OPEN_NO_DUPLICATION")) opened_by_endpoint();
    else if (!strcmp(name, "FOREIGN_PROCESS")) foreign_process();
    else assert(!"unknown OSD format test");
    printf("OSD_PIN_FORMAT_%s_PASS\n", name);
    return 0;
}
