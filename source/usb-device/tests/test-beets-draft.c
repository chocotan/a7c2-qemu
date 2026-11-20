/* SPDX-License-Identifier: GPL-2.0-or-later */
/* DRAFT, NOT RUN. Synthetic response bytes test transport, not Sony encoding. */
#include "beets-core.h"
#include <assert.h>
#include <string.h>

static void select_register(BeetsCore *s, uint16_t address)
{
    assert(beets_start_write(s) == 0);
    assert(beets_send(s, address & 0xff) == 0);
    assert(beets_send(s, address >> 8) == 0);
}

int main(void)
{
    BeetsCore s;
    const uint8_t device[] = {0xa5, 0x5a};
    const uint8_t port[] = {0x12, 0x34, 0x56, 0x78};
    beets_init(&s);
    assert(beets_start_write(&s) != 0);
    beets_enable(&s, true);
    assert((s.mode & 3) == 0 && !s.primary && !s.secondary);
    assert(beets_complete_reset(&s, device, 1) != 0);
    beets_reset_line(&s, true);
    assert(beets_start_write(&s) != 0);
    beets_reset_line(&s, false);
    assert((s.mode & 3) == 0); /* Pulse alone cannot invent a firmware reply. */
    assert(beets_complete_reset(&s, device, 1) == 0);
    assert((s.mode & 3) == 1 && s.pending == 1 && s.primary && !s.secondary);
    select_register(&s, 0x007e);
    assert(beets_start_read(&s) == 0); /* repeated START, no STOP */
    assert(beets_recv(&s) == 0xa5 && beets_recv(&s) == 0x5a);
    beets_finish(&s);
    assert(s.pending == 1 && s.primary); /* Read is not W1C. */
    assert(beets_port_event(&s, port) == 0);
    assert(s.pending == 3 && s.primary && s.secondary);
    select_register(&s, 0x1400);
    assert(beets_start_read(&s) == 0);
    for (unsigned i = 0; i < sizeof(port); i++) assert(beets_recv(&s) == port[i]);
    assert(beets_recv(&s) == 0xff && s.failed); /* No silent overrun. */
    beets_finish(&s);
    select_register(&s, 0x0006);
    assert(beets_send(&s, 0) == 0 && s.pending == 3);
    beets_finish(&s);
    select_register(&s, 0x0006);
    assert(beets_send(&s, 1) == 0 && s.pending == 2 && s.primary && s.secondary);
    beets_finish(&s);
    select_register(&s, 0x0006);
    assert(beets_send(&s, 2) == 0 && !s.pending && !s.primary && !s.secondary);
    beets_finish(&s);
    select_register(&s, 0x1234);
    assert(beets_start_read(&s) != 0);
    beets_finish(&s);
    select_register(&s, 0x0008); /* Unknown reset-command encoding is rejected. */
    assert(beets_send(&s, 0x01) != 0);
    beets_finish(&s);
    assert(beets_start_write(&s) == 0);
    assert(beets_send(&s, 0x7e) == 0 && beets_start_read(&s) != 0);
    beets_finish(&s);
    select_register(&s, 0x007e);
    beets_finish(&s);
    assert(beets_start_read(&s) != 0); /* STOP breaks repeated-START contract. */
    beets_reset_line(&s, true);
    assert(!s.pending && !s.primary && !s.secondary && !s.reset_complete);
    beets_reset_line(&s, false);
    assert(beets_complete_reset(&s, device, 2) == 0 && (s.mode & 3) == 2);
    beets_enable(&s, false);
    assert(s.pending == 1 && !s.primary && beets_start_write(&s) != 0);
    return 0;
}
