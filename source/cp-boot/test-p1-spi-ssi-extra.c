/* SPDX-License-Identifier: GPL-2.0-or-later */
/* Synthetic SSI coverage: multi-block ACK and checksum response tag wrap. */
#ifdef NDEBUG
#error "This test requires assertions"
#endif
#include <assert.h>
#include <stdint.h>
#include <string.h>
#include "p1-spi-ssi.h"

#define BASE UINT32_C(0x1000)
#define LENGTH 256u

static void put32(uint8_t *p, uint32_t value)
{
    for (unsigned i = 0; i < 4; ++i) {
        p[i] = (uint8_t)(value >> (8 * i));
    }
}

static uint16_t beat(struct p1_spi_ssi *s, uint16_t input)
{
    uint16_t output = 0xdead;
    assert(p1_spi_ssi_transfer(s, 16, input, &output));
    return output;
}

static void ready(struct p1_spi_ssi *s)
{
    assert(beat(s, 0) == 0xffff);
    assert(beat(s, 0) == 0x10c3);
    assert(beat(s, 0) == 0xffff);
    assert(beat(s, 0) == 0x11c3);
    assert(s->monitor.state == P1_SPI_COMMAND);
}

static void input_block(struct p1_spi_ssi *s, const uint8_t *block)
{
    for (unsigned i = 0; i < 16; i += 2) {
        assert(beat(s, (uint16_t)(block[i] | (uint16_t)block[i + 1] << 8)) == 0);
    }
}

static void ack(struct p1_spi_ssi *s, unsigned tag)
{
    assert(beat(s, 0) == 0xffff);
    assert(beat(s, 0) == (uint16_t)((tag << 8) | 0x3a));
}

static void response(struct p1_spi_ssi *s, const uint8_t *expected, unsigned length)
{
    for (unsigned i = 0; i < length; ++i) {
        assert(beat(s, 0) == 0xffff);
        assert(beat(s, 0) == (uint16_t)(((0x30u | (i & 15u)) << 8) | expected[i]));
    }
}

int main(void)
{
    struct p1_spi_ssi s;
    uint8_t ram[512] = {0}, data[LENGTH], request[16] = {0}, reply[20] = {0};
    uint32_t sum = 0;

    for (unsigned i = 0; i < LENGTH; ++i) {
        data[i] = (uint8_t)(i ^ 0x5a);
        sum += data[i];
    }
    assert(p1_spi_ssi_init(&s, P1_SSI_PROFILE, ram, BASE, sizeof(ram)));
    assert(p1_spi_ssi_select(&s, false));
    assert(p1_spi_ssi_select(&s, true));
    ready(&s);

    request[0] = 0x21;
    request[1] = 2;
    put32(request + 4, LENGTH);
    put32(request + 8, BASE);
    put32(request + 12, LENGTH / 4);
    input_block(&s, request);
    ack(&s, 0x20);
    for (unsigned i = 0; i < LENGTH / 16; ++i) {
        input_block(&s, data + i * 16);
        ack(&s, 0x20u | ((i + 1u) & 15u));
    }
    assert(memcmp(ram, data, LENGTH) == 0);
    assert(s.monitor.bytes_written == LENGTH && s.monitor.bytes_readback == LENGTH);
    reply[0] = 0x81;
    response(&s, reply, 16);
    ready(&s);

    memset(request, 0, sizeof(request));
    request[0] = 0x12;
    put32(request + 8, BASE);
    put32(request + 12, LENGTH);
    input_block(&s, request);
    ack(&s, 0x20);
    memset(reply, 0, sizeof(reply));
    reply[0] = 0x81;
    reply[4] = 4;
    put32(reply + 16, sum);
    response(&s, reply, 20);
    assert(s.monitor.bytes_checksummed == LENGTH);
    assert(s.monitor.state == P1_SPI_READY);
    return 0;
}
