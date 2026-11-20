/* SPDX-License-Identifier: GPL-2.0-or-later */
#ifndef A7C2_P1_SPI_SSI_H
#define A7C2_P1_SPI_SSI_H

#include "p1-spi-monitor.h"

#define P1_SSI_PROFILE "virtual-p1-ssi-monitor-v1"

enum p1_ssi_error {
    P1_SSI_OK, P1_SSI_DISABLED, P1_SSI_PROFILE_ERROR, P1_SSI_CS_UNKNOWN,
    P1_SSI_CS_ABORT, P1_SSI_WIDTH, P1_SSI_WORD_RANGE, P1_SSI_RESET,
    P1_SSI_PROTOCOL
};

struct p1_spi_ssi {
    struct p1_spi_monitor monitor;
    enum p1_ssi_error error;
    bool enabled, cs_known, selected, started, blocked;
};

/* NULL profile leaves the adapter disabled. RAM is caller-owned virtual RAM. */
bool p1_spi_ssi_init(struct p1_spi_ssi *s, const char *profile,
                     uint8_t *ram, uint32_t base, size_t size);
/* Explicit inactive CS must be supplied before the first active edge. */
bool p1_spi_ssi_select(struct p1_spi_ssi *s, bool selected);
/* Reset never silently restarts a session or discards its failure. */
bool p1_spi_ssi_reset(struct p1_spi_ssi *s);
/* false means no valid reply; an input beat may legitimately reply with zero. */
bool p1_spi_ssi_transfer(struct p1_spi_ssi *s, unsigned width,
                         uint32_t mosi, uint16_t *miso);

#endif
