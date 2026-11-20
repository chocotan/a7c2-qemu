/* SPDX-License-Identifier: GPL-2.0-or-later */
#include "p1-spi-monitor.h"

#include <string.h>

static bool block_error(struct p1_spi_monitor *m, enum p1_spi_error error)
{
    m->state = P1_SPI_BLOCKED;
    m->error = error;
    m->output_used = m->output_pos = 0;
    return false;
}

static uint32_t le32(const uint8_t *p)
{
    return (uint32_t)p[0] | (uint32_t)p[1] << 8 |
           (uint32_t)p[2] << 16 | (uint32_t)p[3] << 24;
}

static void put32(uint8_t *p, uint32_t value)
{
    for (unsigned i = 0; i < 4; ++i) {
        p[i] = (uint8_t)(value >> (8 * i));
    }
}

static bool in_ram(const struct p1_spi_monitor *m, uint32_t address,
                   uint32_t length)
{
    return address >= m->ram_base &&
           (uint64_t)address - m->ram_base + length <= m->ram_size;
}

static void item(struct p1_spi_monitor *m, uint8_t tag, uint8_t byte)
{
    /* All callers emit at most 20 items (40 frames) per queue. */
    m->output[m->output_used++] = 0xffff;
    m->output[m->output_used++] = (uint16_t)((uint16_t)tag << 8 | byte);
}

static void ready(struct p1_spi_monitor *m)
{
    /* ROM 5444/5448 and client 400ec8 reset all tag classes per command. */
    m->output_pos = m->output_used = 0;
    m->block_used = 0;
    m->ack_tag = 0x20;
    item(m, 0x10, 0xc3);
    item(m, 0x11, 0xc3);
    m->state = P1_SPI_READY;
}

static void response(struct p1_spi_monitor *m, bool checksum, uint32_t sum)
{
    uint8_t bytes[20] = {0x81};
    size_t length = checksum ? 20 : 16;
    if (checksum) {
        bytes[4] = 4;
        put32(bytes + 16, sum);
    }
    m->output_pos = m->output_used = 0;
    for (size_t i = 0; i < length; ++i) {
        item(m, (uint8_t)(0x30 | (i & 15)), bytes[i]);
    }
    m->state = P1_SPI_RESPONSE;
}

static void command(struct p1_spi_monitor *m)
{
    const uint8_t *r = m->request;
    uint32_t length = le32(r + 4), address = le32(r + 8);
    uint32_t count = le32(r + 12);
    if (r[2] || r[3]) {
        block_error(m, P1_SPI_BAD_REQUEST);
        return;
    }
    switch (r[0]) {
    case 0x11:
        if (r[1] || length || address || count) {
            block_error(m, P1_SPI_BAD_REQUEST);
            return;
        }
        response(m, false, 0);
        break;
    case 0x12: {
        uint32_t sum = 0;
        if (r[1] || length || !address || !count) {
            block_error(m, P1_SPI_BAD_REQUEST);
            return;
        }
        if (!in_ram(m, address, count)) {
            block_error(m, P1_SPI_RANGE);
            return;
        }
        for (uint32_t i = 0; i < count; ++i) {
            sum += m->ram[(size_t)(address - m->ram_base) + i];
        }
        m->bytes_checksummed += count;
        response(m, true, sum);
        break;
    }
    case 0x13:
        if (r[1] || length || !address || count || (address & 3)) {
            block_error(m, P1_SPI_BAD_REQUEST);
            return;
        }
        if (!in_ram(m, address, 4)) {
            block_error(m, P1_SPI_RANGE);
            return;
        }
        m->execute_address = address;
        m->execute_requested = true;
        response(m, false, 0);
        break;
    case 0x21:
        if (r[1] != 2) {
            block_error(m, P1_SPI_UNSUPPORTED);
            return;
        }
        if (!address || !count || (uint64_t)count * 4 != length || (address & 3)) {
            block_error(m, P1_SPI_BAD_REQUEST);
            return;
        }
        if (!in_ram(m, address, length)) {
            block_error(m, P1_SPI_RANGE);
            return;
        }
        m->write_address = address;
        m->write_left = length;
        m->block_used = 0;
        m->state = P1_SPI_DATA;
        break;
    default:
        block_error(m, P1_SPI_UNSUPPORTED);
        break;
    }
}

static void commit_block(struct p1_spi_monitor *m)
{
    uint32_t length = m->write_left < 16 ? m->write_left : 16;
    size_t offset = (size_t)(m->write_address - m->ram_base);
    /* Full request range was checked before accepting any data. */
    memcpy(m->ram + offset, m->block, length);
    m->bytes_written += length;
    for (uint32_t i = 0; i < length; ++i) {
        if (m->ram[offset + i] != m->block[i]) {
            block_error(m, P1_SPI_READBACK);
            return;
        }
        ++m->bytes_readback;
    }
    m->write_left -= length;
    m->block_used = 0;
    if (m->write_left) {
        m->write_address += length;
        m->state = P1_SPI_DATA;
    } else {
        response(m, false, 0);
    }
}

bool p1_spi_monitor_init(struct p1_spi_monitor *m, uint8_t *ram,
                         uint32_t ram_base, size_t ram_size)
{
    if (!m) {
        return false;
    }
    memset(m, 0, sizeof(*m));
    if (!ram || !ram_size || (ram_base & 3) ||
        (uint64_t)ram_size > UINT64_C(0x100000000) - ram_base) {
        return block_error(m, P1_SPI_BAD_CONFIG);
    }
    m->ram = ram;
    m->ram_base = ram_base;
    m->ram_size = ram_size;
    return true;
}

bool p1_spi_monitor_enter(struct p1_spi_monitor *m)
{
    if (!m || !m->ram || !m->ram_size) {
        return false;
    }
    m->error = P1_SPI_OK;
    m->write_address = m->write_left = m->execute_address = 0;
    m->execute_requested = false;
    memset(m->request, 0, sizeof(m->request));
    ready(m);
    return true;
}

bool p1_spi_monitor_receive_frame(struct p1_spi_monitor *m, uint16_t frame)
{
    if (!m || m->state == P1_SPI_BLOCKED) {
        return false;
    }
    if (m->state != P1_SPI_COMMAND && m->state != P1_SPI_DATA) {
        return block_error(m, P1_SPI_BAD_STATE);
    }
    m->block[m->block_used++] = (uint8_t)frame;
    m->block[m->block_used++] = (uint8_t)(frame >> 8);
    if (m->block_used == sizeof(m->block)) {
        ++m->blocks_received;
        if (m->state == P1_SPI_COMMAND) {
            memcpy(m->request, m->block, sizeof(m->request));
            m->state = P1_SPI_COMMAND_ACK;
        } else {
            m->state = P1_SPI_DATA_ACK;
        }
        m->output_pos = m->output_used = 0;
        item(m, m->ack_tag, 0x3a);
        m->ack_tag = (uint8_t)(0x20 | ((m->ack_tag + 1) & 15));
    }
    return true;
}

int p1_spi_monitor_next_frame(struct p1_spi_monitor *m, uint16_t *frame)
{
    if (!m) {
        return -1;
    }
    if (!frame) {
        block_error(m, P1_SPI_BAD_STATE);
        return -1;
    }
    if (m->state == P1_SPI_BLOCKED) {
        return -1;
    }
    if (m->output_pos == m->output_used) {
        return 0;
    }
    *frame = m->output[m->output_pos++];
    if (m->output_pos == m->output_used) {
        m->output_pos = m->output_used = 0;
        switch (m->state) {
        case P1_SPI_READY:
            m->state = P1_SPI_COMMAND;
            break;
        case P1_SPI_COMMAND_ACK:
            command(m);
            break;
        case P1_SPI_DATA_ACK:
            commit_block(m);
            break;
        case P1_SPI_RESPONSE:
            if (m->execute_requested) {
                m->state = P1_SPI_EXEC_REQUESTED;
            } else {
                ready(m);
            }
            break;
        default:
            block_error(m, P1_SPI_BAD_STATE);
            break;
        }
    }
    return 1;
}
