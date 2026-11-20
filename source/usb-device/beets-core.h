/* SPDX-License-Identifier: GPL-2.0-or-later */
#ifndef A7C2_BEETS_CORE_H
#define A7C2_BEETS_CORE_H
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

/* Register transport only: no invented command opcode or success response. */
#define BEETS_ADDRESS 0x08
#define BEETS_DEVICE_PENDING 1u
#define BEETS_PORT_PENDING 2u
#define BEETS_PENDING_MASK (BEETS_DEVICE_PENDING | BEETS_PORT_PENDING)
typedef struct BeetsCore {
    uint8_t mode, pending, device[2], port[4];
    uint16_t address;
    unsigned address_bytes, cursor;
    bool writing, reading, selected, failed, reset_asserted;
    bool reset_seen, reset_complete, enabled;
    bool primary, secondary;
    const char *error;
} BeetsCore;

void beets_init(BeetsCore *s);
void beets_reset_line(BeetsCore *s, bool asserted);
void beets_enable(BeetsCore *s, bool enabled);
/* Evidence producer supplies original wire bytes and observed low mode bits. */
int beets_complete_reset(BeetsCore *s, const uint8_t response[2], uint8_t mode);
int beets_port_event(BeetsCore *s, const uint8_t response[4]);
int beets_start_write(BeetsCore *s);
int beets_send(BeetsCore *s, uint8_t byte);
int beets_start_read(BeetsCore *s);
uint8_t beets_recv(BeetsCore *s);
void beets_finish(BeetsCore *s);
#endif
