/* SPDX-License-Identifier: GPL-2.0-or-later */
#include "p1-spi-ssi.h"

#include <string.h>

static bool stop(struct p1_spi_ssi *s, enum p1_ssi_error error)
{
    if (!s->blocked) {
        s->error = error;
        s->blocked = true;
        s->monitor.state = P1_SPI_BLOCKED;
        s->monitor.output_used = s->monitor.output_pos = 0;
    }
    return false;
}

bool p1_spi_ssi_init(struct p1_spi_ssi *s, const char *profile,
                     uint8_t *ram, uint32_t base, size_t size)
{
    if (!s) {
        return false;
    }
    memset(s, 0, sizeof(*s));
    if (!profile) {
        s->error = P1_SSI_DISABLED;
        return true;
    }
    if (strcmp(profile, P1_SSI_PROFILE)) {
        return stop(s, P1_SSI_PROFILE_ERROR);
    }
    s->enabled = true;
    if (!p1_spi_monitor_init(&s->monitor, ram, base, size)) {
        return stop(s, P1_SSI_PROTOCOL);
    }
    return true;
}

bool p1_spi_ssi_select(struct p1_spi_ssi *s, bool selected)
{
    if (!s || !s->enabled || s->blocked) {
        return false;
    }
    if (!s->cs_known) {
        if (selected) {
            return stop(s, P1_SSI_CS_UNKNOWN);
        }
        s->cs_known = true;
        return true;
    }
    if (selected == s->selected) {
        return true;
    }
    if (s->started) {
        /* Virtual policy: hold CS active for one session, never guess GPIO. */
        return stop(s, P1_SSI_CS_ABORT);
    }
    s->selected = selected;
    s->started = true;
    if (!p1_spi_monitor_enter(&s->monitor)) {
        return stop(s, P1_SSI_PROTOCOL);
    }
    return true;
}

bool p1_spi_ssi_reset(struct p1_spi_ssi *s)
{
    if (!s || !s->enabled || s->blocked) {
        return false;
    }
    if (s->started) {
        return stop(s, P1_SSI_RESET);
    }
    return true;
}

/* Validate the complete command before publishing even its receipt ACK.
 * The pinned core dispatch only reads RAM here; data commits occur later.
 */
static bool command_allowed(struct p1_spi_ssi *s, uint16_t frame)
{
    struct p1_spi_monitor probe = s->monitor;
    uint16_t unused;
    if (!p1_spi_monitor_receive_frame(&probe, frame)) {
        return stop(s, P1_SSI_PROTOCOL);
    }
    while (probe.state == P1_SPI_COMMAND_ACK) {
        if (p1_spi_monitor_next_frame(&probe, &unused) != 1) {
            return stop(s, P1_SSI_PROTOCOL);
        }
    }
    if (probe.state == P1_SPI_BLOCKED) {
        s->monitor.error = probe.error;
        return stop(s, P1_SSI_PROTOCOL);
    }
    return true;
}

bool p1_spi_ssi_transfer(struct p1_spi_ssi *s, unsigned width,
                         uint32_t mosi, uint16_t *miso)
{
    if (miso) {
        *miso = 0;
    }
    if (!s || !s->enabled || s->blocked) {
        return false;
    }
    if (!miso) {
        return stop(s, P1_SSI_PROTOCOL);
    }
    if (!s->cs_known) {
        return stop(s, P1_SSI_CS_UNKNOWN);
    }
    if (!s->selected || !s->started) {
        return false;
    }
    if (width != 16) {
        return stop(s, P1_SSI_WIDTH);
    }
    if (mosi > UINT16_MAX) {
        return stop(s, P1_SSI_WORD_RANGE);
    }
    const enum p1_spi_state before = s->monitor.state;
    if (before == P1_SPI_COMMAND || before == P1_SPI_DATA) {
        if (before == P1_SPI_COMMAND && s->monitor.block_used == 14 &&
            !command_allowed(s, (uint16_t)mosi)) {
            return false;
        }
        if (!p1_spi_monitor_receive_frame(&s->monitor, (uint16_t)mosi)) {
            return stop(s, P1_SSI_PROTOCOL);
        }
        return true; /* Virtual idle MISO=0 is not an ACK or an error sentinel. */
    }
    switch (before) {
    case P1_SPI_READY:
    case P1_SPI_COMMAND_ACK:
    case P1_SPI_DATA_ACK:
    case P1_SPI_RESPONSE:
        if (p1_spi_monitor_next_frame(&s->monitor, miso) != 1 ||
            s->monitor.state == P1_SPI_BLOCKED) {
            *miso = 0;
            return stop(s, P1_SSI_PROTOCOL);
        }
        /* MOSI on this whole output beat is ignored, even if state changed. */
        return true;
    default:
        return stop(s, P1_SSI_PROTOCOL);
    }
}
