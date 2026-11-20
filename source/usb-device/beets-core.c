/* SPDX-License-Identifier: GPL-2.0-or-later */
#include "beets-core.h"
#include <string.h>

static int reject(BeetsCore *s, const char *why)
{
    s->failed = true;
    s->error = why;
    return -1;
}

static void lines(BeetsCore *s)
{
    s->primary = s->enabled && !s->reset_asserted && s->pending != 0;
    s->secondary = s->enabled && !s->reset_asserted &&
                   (s->pending & BEETS_PORT_PENDING) != 0;
}

void beets_init(BeetsCore *s)
{
    memset(s, 0, sizeof(*s));
}

void beets_enable(BeetsCore *s, bool enabled)
{
    s->enabled = enabled;
    lines(s);
}

void beets_reset_line(BeetsCore *s, bool asserted)
{
    if (asserted == s->reset_asserted) return;
    if (asserted) {
        bool enabled = s->enabled;
        beets_init(s);
        s->enabled = enabled;
        s->reset_seen = true;
    }
    s->reset_asserted = asserted;
    lines(s);
}

int beets_complete_reset(BeetsCore *s, const uint8_t response[2], uint8_t mode)
{
    if (!response || !mode || (mode & ~3u) || !s->reset_seen ||
        s->reset_asserted || s->reset_complete || s->pending)
        return reject(s, "Reset Complete without released pulse/observed mode");
    memcpy(s->device, response, sizeof(s->device));
    s->mode = (s->mode & ~3u) | mode;
    s->reset_complete = true;
    s->pending |= BEETS_DEVICE_PENDING;
    lines(s);
    return 0;
}

int beets_port_event(BeetsCore *s, const uint8_t response[4])
{
    if (!response || !s->reset_complete || s->reset_asserted ||
        (s->pending & BEETS_PORT_PENDING))
        return reject(s, "port event before reset completion or mailbox busy");
    memcpy(s->port, response, sizeof(s->port));
    s->pending |= BEETS_PORT_PENDING;
    lines(s);
    return 0;
}

int beets_start_write(BeetsCore *s)
{
    if (!s->enabled || s->reset_asserted)
        return reject(s, "write while disabled/reset");
    s->address = s->address_bytes = s->cursor = 0;
    s->selected = s->reading = s->failed = false;
    s->error = NULL;
    s->writing = true;
    return 0;
}

int beets_send(BeetsCore *s, uint8_t byte)
{
    if (!s->writing || s->failed || !s->enabled || s->reset_asserted)
        return reject(s, "byte outside writable transaction");
    if (s->address_bytes < 2) {
        s->address |= (uint16_t)byte << (8 * s->address_bytes++);
        s->selected = s->address_bytes == 2;
        return 0;
    }
    if (s->address != 0x0006 || s->cursor || (byte & ~BEETS_PENDING_MASK))
        return reject(s, "unknown command/register write or excess payload");
    s->pending &= ~byte; /* W1C; reading responses never acknowledges pending. */
    s->cursor++;
    lines(s);
    return 0;
}

static unsigned width(uint16_t address)
{
    switch (address) {
    case 0x0000: case 0x0006: return 1;
    case 0x007e: return 2;
    case 0x1400: return 4;
    default: return 0;
    }
}

int beets_start_read(BeetsCore *s)
{
    if (!s->enabled || s->reset_asserted || s->failed ||
        !s->writing || !s->selected || s->cursor || !width(s->address))
        return reject(s, "read requires two-byte LE address and repeated START");
    s->writing = false;
    s->reading = true;
    return 0;
}

uint8_t beets_recv(BeetsCore *s)
{
    uint8_t byte;
    if (!s->reading || s->failed || !s->enabled || s->reset_asserted ||
        s->cursor >= width(s->address)) {
        reject(s, "read overrun or byte outside readable transaction");
        return 0xff; /* QEMU I2C recv cannot NACK a data byte; log failure. */
    }
    switch (s->address) {
    case 0x0000: byte = s->mode; break;
    case 0x0006: byte = s->pending; break;
    case 0x007e: byte = s->device[s->cursor]; break;
    case 0x1400: byte = s->port[s->cursor]; break;
    default: return 0xff;
    }
    s->cursor++;
    return byte;
}

void beets_finish(BeetsCore *s)
{
    if (s->writing && s->address_bytes != 2)
        reject(s, "STOP with truncated register address");
    s->writing = s->reading = s->selected = false;
    s->address_bytes = s->cursor = 0;
}
