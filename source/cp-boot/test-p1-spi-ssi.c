/* SPDX-License-Identifier: GPL-2.0-or-later */
#ifdef NDEBUG
#error "This test requires assertions"
#endif
#include "p1-spi-ssi.h"
#include <assert.h>
#include <stdio.h>
#include <string.h>

#define BASE UINT32_C(0x1000)

static void begin(struct p1_spi_ssi *s, uint8_t ram[64])
{
    assert(p1_spi_ssi_init(s, P1_SSI_PROFILE, ram, BASE, 64));
    assert(s->monitor.state == P1_SPI_OFF && !s->cs_known);
    assert(p1_spi_ssi_select(s, false));
    assert(p1_spi_ssi_reset(s));
    assert(p1_spi_ssi_select(s, true));
    assert(s->monitor.state == P1_SPI_READY);
}

static uint16_t beat(struct p1_spi_ssi *s, uint16_t mosi)
{
    uint16_t miso = 0x1234;
    assert(p1_spi_ssi_transfer(s, 16, mosi, &miso));
    return miso;
}

static void ready(struct p1_spi_ssi *s)
{
    assert(beat(s, 0xdead) == 0xffff);
    assert(beat(s, 0xbeef) == 0x10c3);
    assert(beat(s, 0x1234) == 0xffff);
    assert(beat(s, 0x5678) == 0x11c3);
    assert(s->monitor.state == P1_SPI_COMMAND);
    assert(s->monitor.block_used == 0);
}

static void put32(uint8_t *p, uint32_t v)
{
    for (unsigned i = 0; i < 4; i++) {
        p[i] = (uint8_t)(v >> (8 * i));
    }
}

static void request(uint8_t r[16], uint8_t op, uint32_t address, uint32_t bytes)
{
    memset(r, 0, 16);
    r[0] = op;
    put32(r + 8, address);
    if (op == 0x21) {
        r[1] = 2;
        put32(r + 4, bytes);
        put32(r + 12, bytes / 4);
    } else if (op == 0x12) {
        put32(r + 12, bytes);
    }
}

static void block(struct p1_spi_ssi *s, const uint8_t r[16])
{
    for (unsigned i = 0; i < 8; i++) {
        assert(beat(s, (uint16_t)(r[2 * i] | r[2 * i + 1] << 8)) == 0);
    }
}

static void ack(struct p1_spi_ssi *s, uint8_t tag)
{
    assert(beat(s, 0xaaaa) == 0xffff);
    assert(beat(s, 0xbbbb) == (uint16_t)((uint16_t)tag << 8 | 0x3a));
    assert(s->monitor.block_used == 0 || s->monitor.state == P1_SPI_RESPONSE);
}

static void response(struct p1_spi_ssi *s)
{
    for (unsigned i = 0; i < 16; i++) {
        assert(beat(s, 0xface) == 0xffff);
        assert(beat(s, 0xcafe) ==
               (uint16_t)((0x30 + i) << 8 | (i == 0 ? 0x81 : 0)));
    }
}

static void test_boundaries_and_zero_input(void)
{
    struct p1_spi_ssi s;
    uint8_t ram[64] = {0}, r[16];
    begin(&s, ram);
    ready(&s);
    request(r, 0x11, 0, 0);
    block(&s, r); /* Seven zero halfwords are legal input, never an idle test. */
    assert(s.monitor.blocks_received == 1);
    ack(&s, 0x20);
    assert(s.monitor.state == P1_SPI_RESPONSE);
    response(&s);
    assert(s.monitor.state == P1_SPI_READY);
    ready(&s);
    assert(s.monitor.blocks_received == 1 && s.monitor.block_used == 0);
    request(r, 0x21, BASE + 60, 4);
    block(&s, r);
    ack(&s, 0x20);
    assert(s.monitor.state == P1_SPI_DATA && s.monitor.block_used == 0);
    memset(r, 0, sizeof(r));
    r[0] = 0xf1; r[1] = 0xa2; r[2] = 0x83; r[3] = 0x74;
    block(&s, r);
    ack(&s, 0x21);
    assert(s.monitor.bytes_written == 4 && s.monitor.bytes_readback == 4);
    assert(memcmp(ram + 60, r, 4) == 0);
    for (unsigned i = 0; i < 60; i++) {
        assert(ram[i] == 0);
    }
    response(&s);
}

static void test_invalid_commands_have_no_ack(void)
{
    const struct { uint8_t op; uint32_t address, bytes; } cases[] = {
        {0x00, 0, 0}, {0x22, BASE, 4}, {0xff, 0, 0},
        {0x21, BASE + 60, 8}, {0x12, BASE + 60, 5},
        {0x13, BASE + 64, 0}, {0x13, BASE + 1, 0},
        {0x21, UINT32_MAX - 3, 4},
    };
    for (size_t i = 0; i < sizeof(cases) / sizeof(cases[0]); i++) {
        struct p1_spi_ssi s;
        uint8_t ram[64], r[16];
        memset(ram, 0x78, sizeof(ram));
        begin(&s, ram);
        ready(&s);
        request(r, cases[i].op, cases[i].address, cases[i].bytes);
        for (unsigned n = 0; n < 7; n++) {
            assert(beat(&s, (uint16_t)(r[2 * n] | r[2 * n + 1] << 8)) == 0);
        }
        uint16_t miso = 0x1234;
        assert(!p1_spi_ssi_transfer(&s, 16,
                (uint16_t)(r[14] | r[15] << 8), &miso));
        assert(miso == 0 && s.blocked && s.error == P1_SSI_PROTOCOL);
        assert(s.monitor.output_used == 0 && !s.monitor.execute_requested);
        assert(!s.monitor.bytes_written);
        assert(!p1_spi_ssi_transfer(&s, 16, 0, &miso));
        for (unsigned n = 0; n < sizeof(ram); n++) {
            assert(ram[n] == 0x78);
        }
    }
}

static void test_width_and_word_range(void)
{
    const unsigned widths[] = {0, 8, 15, 17, 32};
    for (size_t i = 0; i < sizeof(widths) / sizeof(widths[0]); i++) {
        struct p1_spi_ssi s;
        uint8_t ram[64] = {0};
        uint16_t miso = 0x1234;
        begin(&s, ram);
        assert(!p1_spi_ssi_transfer(&s, widths[i], 0, &miso));
        assert(s.error == P1_SSI_WIDTH && miso == 0 && s.blocked);
    }
    struct p1_spi_ssi s;
    uint8_t ram[64] = {0};
    uint16_t miso = 0x1234;
    begin(&s, ram);
    assert(!p1_spi_ssi_transfer(&s, 16, 0x10000, &miso));
    assert(s.error == P1_SSI_WORD_RANGE && miso == 0);
}

static void test_cs_reset_and_partial_write(void)
{
    for (unsigned cs_abort = 0; cs_abort < 2; cs_abort++) {
        struct p1_spi_ssi s;
        uint8_t ram[64] = {0}, r[16];
        uint16_t miso = 0x1234;
        begin(&s, ram);
        ready(&s);
        request(r, 0x21, BASE, 32);
        block(&s, r);
        ack(&s, 0x20);
        memset(r, 0x6b, sizeof(r));
        block(&s, r);
        ack(&s, 0x21);
        assert(s.monitor.bytes_written == 16);
        assert(beat(&s, 0xffff) == 0); /* Incomplete next data block. */
        assert(cs_abort ? !p1_spi_ssi_select(&s, false) : !p1_spi_ssi_reset(&s));
        assert(s.error == (cs_abort ? P1_SSI_CS_ABORT : P1_SSI_RESET));
        assert(!p1_spi_ssi_transfer(&s, 16, 0, &miso) && miso == 0);
        assert(!p1_spi_ssi_select(&s, true) && !p1_spi_ssi_reset(&s));
        for (unsigned i = 0; i < sizeof(ram); i++) {
            assert(ram[i] == (i < 16 ? 0x6b : 0));
        }
    }
    struct p1_spi_ssi s;
    uint8_t ram[64] = {0};
    begin(&s, ram);
    assert(beat(&s, 0) == 0xffff);
    assert(!p1_spi_ssi_reset(&s)); /* Partial output cannot silently restart. */
    assert(s.error == P1_SSI_RESET);
}

static void test_default_off_cs_initialization_and_execute(void)
{
    struct p1_spi_ssi s;
    uint8_t ram[64] = {0}, r[16];
    uint16_t miso = 0x1234;
    assert(p1_spi_ssi_init(&s, NULL, NULL, 0, 0));
    assert(!s.enabled && s.error == P1_SSI_DISABLED);
    assert(!p1_spi_ssi_transfer(&s, 16, 0, &miso) && miso == 0);
    assert(!p1_spi_ssi_init(&s, "physical-rom", ram, BASE, sizeof(ram)));
    assert(s.error == P1_SSI_PROFILE_ERROR);
    assert(p1_spi_ssi_init(&s, P1_SSI_PROFILE, ram, BASE, sizeof(ram)));
    assert(!p1_spi_ssi_select(&s, true) && s.error == P1_SSI_CS_UNKNOWN);
    assert(p1_spi_ssi_init(&s, P1_SSI_PROFILE, ram, BASE, sizeof(ram)));
    assert(!p1_spi_ssi_transfer(&s, 16, 0, &miso));
    assert(s.error == P1_SSI_CS_UNKNOWN);
    assert(p1_spi_ssi_init(&s, P1_SSI_PROFILE, ram, BASE, sizeof(ram)));
    assert(p1_spi_ssi_select(&s, false));
    assert(!p1_spi_ssi_transfer(&s, 16, 0, &miso));
    assert(!s.blocked && s.monitor.state == P1_SPI_OFF);
    begin(&s, ram);
    ready(&s);
    request(r, 0x13, BASE + 60, 0);
    block(&s, r);
    ack(&s, 0x20);
    assert(s.monitor.execute_requested && s.monitor.state == P1_SPI_RESPONSE);
    response(&s);
    assert(s.monitor.state == P1_SPI_EXEC_REQUESTED);
    assert(s.monitor.execute_address == BASE + 60 && s.monitor.bytes_written == 0);
    assert(!p1_spi_ssi_transfer(&s, 16, 0, &miso));
    assert(s.blocked); /* No CPU callback, invented handoff, or extra ACK. */
}

int main(void)
{
    test_boundaries_and_zero_input();
    test_invalid_commands_have_no_ack();
    test_width_and_word_range();
    test_cs_reset_and_partial_write();
    test_default_off_cs_initialization_and_execute();
    puts("P1 SSI SYNTHETIC CHECKS PASSED (virtual protocol only)");
    return 0;
}
