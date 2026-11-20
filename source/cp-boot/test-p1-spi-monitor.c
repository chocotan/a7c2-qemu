/* SPDX-License-Identifier: GPL-2.0-or-later */
#include "p1-spi-monitor.h"

#include <assert.h>
#include <stdio.h>
#include <string.h>

#define BASE UINT32_C(0x1000)

static void put32(uint8_t *p, uint32_t value)
{
    for (unsigned i = 0; i < 4; ++i) {
        p[i] = (uint8_t)(value >> (8 * i));
    }
}

static void expect_frame(struct p1_spi_monitor *m, uint16_t expected)
{
    uint16_t actual = 0;
    assert(p1_spi_monitor_next_frame(m, &actual) == 1);
    assert(actual == expected);
}

static void expect_item(struct p1_spi_monitor *m, uint8_t tag, uint8_t value)
{
    expect_frame(m, 0xffff);
    expect_frame(m, (uint16_t)((uint16_t)tag << 8 | value));
}

static void consume_ready(struct p1_spi_monitor *m)
{
    assert(m->state == P1_SPI_READY);
    expect_item(m, 0x10, 0xc3);
    assert(m->state == P1_SPI_READY);
    expect_item(m, 0x11, 0xc3);
    assert(m->state == P1_SPI_COMMAND);
}

static void begin(struct p1_spi_monitor *m, uint8_t *ram, size_t size)
{
    assert(p1_spi_monitor_init(m, ram, BASE, size));
    assert(m->state == P1_SPI_OFF);
    assert(p1_spi_monitor_enter(m));
    consume_ready(m);
}

static void send_block(struct p1_spi_monitor *m, const uint8_t block[16])
{
    uint16_t unused = 0;
    for (unsigned i = 0; i < 8; ++i) {
        uint16_t frame = (uint16_t)(block[2 * i] |
                                   (uint16_t)block[2 * i + 1] << 8);
        assert(p1_spi_monitor_receive_frame(m, frame));
        if (i < 7) {
            assert(p1_spi_monitor_next_frame(m, &unused) == 0);
        }
    }
}

static void send_request(struct p1_spi_monitor *m, uint8_t op, uint8_t unit,
                         uint32_t bytes, uint32_t address, uint32_t count)
{
    uint8_t r[16] = {0};
    r[0] = op;
    r[1] = unit;
    put32(r + 4, bytes);
    put32(r + 8, address);
    put32(r + 12, count);
    send_block(m, r);
    assert(m->state == P1_SPI_COMMAND_ACK);
    expect_item(m, 0x20, 0x3a);
}

static void expect_response(struct p1_spi_monitor *m, bool checksum,
                            uint32_t sum)
{
    uint8_t expected[20] = {0x81};
    size_t length = checksum ? 20 : 16;
    assert(m->state == P1_SPI_RESPONSE);
    if (checksum) {
        expected[4] = 4;
        put32(expected + 16, sum);
    }
    for (size_t i = 0; i < length; ++i) {
        expect_item(m, (uint8_t)(0x30 | (i & 15)), expected[i]);
    }
}

static void test_query_checksum_execute(void)
{
    struct p1_spi_monitor m;
    uint8_t ram[64];
    memset(ram, 0xa5, sizeof(ram));
    begin(&m, ram, sizeof(ram));
    send_request(&m, 0x11, 0, 0, 0, 0);
    expect_response(&m, false, 0);
    consume_ready(&m);
    /* Checksum is byte-based, including unaligned addresses and high bytes. */
    ram[1] = 0xff;
    ram[2] = 0x80;
    ram[3] = 0x01;
    send_request(&m, 0x12, 0, 0, BASE + 1, 3);
    expect_response(&m, true, 0x180);
    assert(m.bytes_checksummed == 3);
    consume_ready(&m);
    send_request(&m, 0x13, 0, 0, BASE + 60, 0);
    assert(m.execute_requested && m.execute_address == BASE + 60);
    expect_response(&m, false, 0);
    assert(m.state == P1_SPI_EXEC_REQUESTED);
    uint16_t frame = 0;
    assert(p1_spi_monitor_next_frame(&m, &frame) == 0);
    assert(!p1_spi_monitor_receive_frame(&m, 0));
    assert(m.state == P1_SPI_BLOCKED);
    assert(m.error == P1_SPI_BAD_STATE);
    assert(p1_spi_monitor_enter(&m));
    assert(!m.execute_requested);
    consume_ready(&m);
    assert(ram[1] == 0xff);
}

static void test_segmented_write_and_readback(void)
{
    struct p1_spi_monitor m;
    uint8_t ram[64], block[16], expected[20];
    memset(ram, 0xa5, sizeof(ram));
    for (unsigned i = 0; i < sizeof(expected); ++i) {
        expected[i] = (uint8_t)(i * 11 + 3);
    }
    begin(&m, ram, sizeof(ram));
    send_request(&m, 0x21, 2, 20, BASE + 44, 5);
    assert(m.state == P1_SPI_DATA);
    assert(m.bytes_written == 0);
    memcpy(block, expected, 16);
    send_block(&m, block);
    assert(m.state == P1_SPI_DATA_ACK);
    expect_frame(&m, 0xffff);
    assert(m.bytes_written == 0);
    expect_frame(&m, 0x213a);
    assert(m.bytes_written == 16 && m.bytes_readback == 16);
    assert(memcmp(ram + 44, expected, 16) == 0);
    memset(block, 0xee, sizeof(block));
    memcpy(block, expected + 16, 4);
    send_block(&m, block);
    expect_item(&m, 0x22, 0x3a);
    assert(m.bytes_written == 20 && m.bytes_readback == 20);
    assert(memcmp(ram + 44, expected, 20) == 0);
    for (unsigned i = 0; i < 44; ++i) {
        assert(ram[i] == 0xa5);
    }
    assert(m.blocks_received == 3);
    expect_response(&m, false, 0);
    consume_ready(&m);
    uint32_t sum = 0;
    for (unsigned i = 0; i < 20; ++i) {
        sum += expected[i];
    }
    send_request(&m, 0x12, 0, 0, BASE + 44, 20);
    expect_response(&m, true, sum);
}

static void test_ack_wrap(void)
{
    struct p1_spi_monitor m;
    uint8_t ram[272] = {0}, block[16];
    begin(&m, ram, sizeof(ram));
    send_request(&m, 0x21, 2, 272, BASE, 68);
    for (unsigned i = 0; i < 17; ++i) {
        memset(block, (int)i + 1, sizeof(block));
        send_block(&m, block);
        expect_item(&m, (uint8_t)(0x20 | ((i + 1) & 15)), 0x3a);
    }
    for (unsigned i = 0; i < sizeof(ram); ++i) {
        assert(ram[i] == i / 16 + 1);
    }
    assert(m.bytes_written == sizeof(ram));
    assert(m.bytes_readback == sizeof(ram));
    expect_response(&m, false, 0);
    consume_ready(&m);
    send_request(&m, 0x11, 0, 0, 0, 0);
    expect_response(&m, false, 0);
}

static void test_command_tag_reset_after_wrap(void)
{
    struct p1_spi_monitor m;
    uint8_t ram[272] = {0}, block[16];
    begin(&m, ram, sizeof(ram));
    for (unsigned command = 0; command < 18; ++command) {
        memset(block, (int)command + 1, sizeof(block));
        send_request(&m, 0x21, 2, sizeof(ram), BASE, sizeof(ram) / 4);
        for (unsigned i = 0; i < 17; ++i) {
            send_block(&m, block);
            expect_item(&m, (uint8_t)(0x20 | ((i + 1) & 15)), 0x3a);
        }
        expect_response(&m, false, 0);
        consume_ready(&m);
        /* ACK restarts at 20 despite 18 blocks in the preceding command. */
        send_request(&m, 0x12, 0, 0, BASE, sizeof(ram));
        expect_response(&m, true, (command + 1) * sizeof(ram));
        consume_ready(&m);
        /* The 20-byte checksum response ended at 33; query restarts at 30. */
        send_request(&m, 0x11, 0, 0, 0, 0);
        expect_response(&m, false, 0);
        consume_ready(&m);
    }
    assert(m.blocks_received == 18 * 20);
    assert(m.bytes_written == 18 * sizeof(ram));
    assert(m.bytes_readback == m.bytes_written);
    assert(m.bytes_checksummed == m.bytes_written);
}

static void test_bad_requests(void)
{
    const struct {
        uint8_t op, unit;
        uint32_t bytes, address, count;
        enum p1_spi_error error;
    } cases[] = {
        {0x00, 0, 0, 0, 0, P1_SPI_UNSUPPORTED},
        {0x22, 2, 4, BASE, 1, P1_SPI_UNSUPPORTED},
        {0x11, 0, 0, BASE, 0, P1_SPI_BAD_REQUEST},
        {0x11, 1, 0, 0, 0, P1_SPI_BAD_REQUEST},
        {0x12, 0, 0, BASE, 0, P1_SPI_BAD_REQUEST},
        {0x12, 0, 4, BASE, 4, P1_SPI_BAD_REQUEST},
        {0x12, 0, 0, BASE - 1, 1, P1_SPI_RANGE},
        {0x12, 0, 0, BASE + 60, 5, P1_SPI_RANGE},
        {0x12, 0, 0, UINT32_MAX, 2, P1_SPI_RANGE},
        {0x13, 0, 0, BASE + 1, 0, P1_SPI_BAD_REQUEST},
        {0x13, 0, 0, BASE + 64, 0, P1_SPI_RANGE},
        {0x13, 0, 0, BASE, 1, P1_SPI_BAD_REQUEST},
        {0x21, 0, 4, BASE, 4, P1_SPI_UNSUPPORTED},
        {0x21, 1, 4, BASE, 2, P1_SPI_UNSUPPORTED},
        {0x21, 32, 4, BASE, 1, P1_SPI_UNSUPPORTED},
        {0x21, 2, 0, BASE, 0, P1_SPI_BAD_REQUEST},
        {0x21, 2, 4, BASE, 2, P1_SPI_BAD_REQUEST},
        {0x21, 2, 4, BASE + 2, 1, P1_SPI_BAD_REQUEST},
        {0x21, 2, 8, BASE + 60, 2, P1_SPI_RANGE},
        {0x21, 2, 0, BASE, UINT32_C(0x40000000), P1_SPI_BAD_REQUEST},
        {0x21, 2, 4, UINT32_C(0xf1017008), 1, P1_SPI_RANGE},
    };
    for (size_t i = 0; i < sizeof(cases) / sizeof(cases[0]); ++i) {
        struct p1_spi_monitor m;
        uint8_t ram[64], before[64];
        memset(ram, 0x7b, sizeof(ram));
        memcpy(before, ram, sizeof(ram));
        begin(&m, ram, sizeof(ram));
        send_request(&m, cases[i].op, cases[i].unit, cases[i].bytes,
                     cases[i].address, cases[i].count);
        assert(m.state == P1_SPI_BLOCKED && m.error == cases[i].error);
        assert(memcmp(ram, before, sizeof(ram)) == 0);
        assert(!m.bytes_written && !m.execute_requested);
        uint16_t frame = 0;
        assert(p1_spi_monitor_next_frame(&m, &frame) == -1);
        assert(!p1_spi_monitor_receive_frame(&m, 0));
        assert(m.error == cases[i].error);
    }
}

static void test_zero_address_is_blocked(void)
{
    const uint8_t ops[] = {0x12, 0x13, 0x21};
    for (size_t i = 0; i < sizeof(ops); ++i) {
        struct p1_spi_monitor m;
        uint8_t ram[16], before[16];
        memset(ram, 0xa5, sizeof(ram));
        memcpy(before, ram, sizeof(ram));
        assert(p1_spi_monitor_init(&m, ram, 0, sizeof(ram)));
        assert(p1_spi_monitor_enter(&m));
        consume_ready(&m);
        send_request(&m, ops[i], ops[i] == 0x21 ? 2 : 0,
                     ops[i] == 0x21 ? 4 : 0, 0, ops[i] == 0x13 ? 0 : 1);
        assert(m.state == P1_SPI_BLOCKED && m.error == P1_SPI_BAD_REQUEST);
        assert(!m.bytes_written && !m.bytes_checksummed && !m.execute_requested);
        assert(memcmp(ram, before, sizeof(ram)) == 0);
    }
}

static void test_framing_and_reset(void)
{
    struct p1_spi_monitor m;
    uint8_t ram[64] = {0}, block[16] = {0x11};
    begin(&m, ram, sizeof(ram));
    for (unsigned i = 0; i < 7; ++i) {
        assert(p1_spi_monitor_receive_frame(&m, i ? 0 : 0x11));
    }
    assert(m.state == P1_SPI_COMMAND && m.block_used == 14);
    assert(m.blocks_received == 0);
    assert(p1_spi_monitor_enter(&m));
    consume_ready(&m);
    block[3] = 1;
    send_block(&m, block);
    expect_item(&m, 0x20, 0x3a);
    assert(m.state == P1_SPI_BLOCKED && m.error == P1_SPI_BAD_REQUEST);
    assert(p1_spi_monitor_enter(&m));
    /* No input accepted while the ready queue is still being consumed. */
    expect_frame(&m, 0xffff);
    assert(!p1_spi_monitor_receive_frame(&m, 0x11));
    assert(m.state == P1_SPI_BLOCKED && m.error == P1_SPI_BAD_STATE);
    assert(p1_spi_monitor_enter(&m));
    consume_ready(&m);
    block[3] = 0;
    send_block(&m, block);
    /* No ninth halfword may steal the ACK output slot. */
    assert(!p1_spi_monitor_receive_frame(&m, 0));
    assert(m.state == P1_SPI_BLOCKED && !m.bytes_written);
    assert(p1_spi_monitor_enter(&m));
    consume_ready(&m);
    send_request(&m, 0x11, 0, 0, 0, 0);
    assert(!p1_spi_monitor_receive_frame(&m, 0));
    assert(m.state == P1_SPI_BLOCKED);
}

static void test_partial_write_failure_and_top_address(void)
{
    struct p1_spi_monitor m;
    uint8_t ram[32] = {0}, block[16];
    memset(block, 0x83, sizeof(block));
    begin(&m, ram, sizeof(ram));
    send_request(&m, 0x21, 2, 32, BASE, 8);
    send_block(&m, block);
    expect_item(&m, 0x21, 0x3a);
    send_block(&m, block);
    assert(!p1_spi_monitor_receive_frame(&m, 0));
    for (unsigned i = 0; i < 32; ++i) {
        assert(ram[i] == (i < 16 ? 0x83 : 0));
    }
    assert(m.bytes_written == 16);
    assert(p1_spi_monitor_init(&m, ram, UINT32_C(0xffffffe0), 32));
    assert(p1_spi_monitor_enter(&m));
    consume_ready(&m);
    send_request(&m, 0x21, 2, 4, UINT32_C(0xfffffffc), 1);
    send_block(&m, block);
    expect_item(&m, 0x21, 0x3a);
    assert(m.bytes_written == 4 && m.bytes_readback == 4);
    for (unsigned i = 28; i < 32; ++i) {
        assert(ram[i] == 0x83);
    }
    expect_response(&m, false, 0);
}

static void test_config(void)
{
    struct p1_spi_monitor m;
    uint8_t ram[8] = {0};
    assert(!p1_spi_monitor_init(NULL, ram, BASE, sizeof(ram)));
    assert(!p1_spi_monitor_init(&m, NULL, BASE, sizeof(ram)));
    assert(m.error == P1_SPI_BAD_CONFIG);
    assert(!p1_spi_monitor_enter(&m));
    assert(!p1_spi_monitor_init(&m, ram, BASE, 0));
    assert(!p1_spi_monitor_init(&m, ram, BASE + 1, sizeof(ram)));
    assert(!p1_spi_monitor_init(&m, ram, UINT32_C(0xfffffffc), 8));
    assert(!p1_spi_monitor_enter(NULL));
    assert(!p1_spi_monitor_receive_frame(NULL, 0));
    uint16_t frame = 0;
    assert(p1_spi_monitor_next_frame(NULL, &frame) == -1);
    assert(p1_spi_monitor_init(&m, ram, BASE, sizeof(ram)));
    assert(p1_spi_monitor_next_frame(&m, &frame) == 0);
    assert(!p1_spi_monitor_receive_frame(&m, 0));
    assert(m.state == P1_SPI_BLOCKED);
    assert(p1_spi_monitor_enter(&m));
    assert(p1_spi_monitor_next_frame(&m, NULL) == -1);
    assert(m.state == P1_SPI_BLOCKED);
}

int main(void)
{
    test_query_checksum_execute();
    test_segmented_write_and_readback();
    test_ack_wrap();
    test_command_tag_reset_after_wrap();
    test_bad_requests();
    test_zero_address_is_blocked();
    test_framing_and_reset();
    test_partial_write_failure_and_top_address();
    test_config();
    puts("ALL P1 SPI MONITOR HOST CHECKS PASSED (virtual protocol only)");
    return 0;
}
