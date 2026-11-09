/* SPDX-License-Identifier: MIT
 * cc -std=c11 -Wall -Wextra -Werror -pedantic sony-dwc3.c test-dwc3.c -o test-dwc3
 * Synthetic guest only: no Sony descriptors or original-driver success claim.
 */
#include "sony-dwc3.h"
#include <assert.h>
#include <errno.h>
#include <stdio.h>
#include <string.h>

#define RAM_SIZE 0x20000u
#define RAM_BASE UINT64_C(0x400000000)
#define EVENT 0x1000u
#define RING 0x2000u
#define BUFFER 0x6000u
#define PHYS(n) (RAM_BASE + (n))

typedef struct Fixture {
    SonyDWC3 s;
    uint8_t ram[RAM_SIZE];
    unsigned completions, errors, irq_changes;
    bool irq;
    int status;
    uint32_t actual;
    uint64_t last_id;
} Fixture;

static Fixture f;
static unsigned enabled, snapshots;
static SonyDWC3Generation observed[128];
static void observe(void *opaque, const SonyDWC3Generation *g) {
    assert(opaque == &f && snapshots < 128);
    observed[snapshots++] = *g;
}

static int ram_probe(void *opaque, uint64_t addr, size_t n, bool wr)
{
    (void)opaque; (void)wr;
    return addr < RAM_BASE || n > RAM_SIZE || addr - RAM_BASE > RAM_SIZE - n ? -EFAULT : 0;
}
static int ram_read(void *opaque, uint64_t addr, void *p, size_t n)
{
    Fixture *x = opaque;
    assert(!ram_probe(opaque, addr, n, false));
    memcpy(p, x->ram + addr - RAM_BASE, n);
    return 0;
}
static int ram_write(void *opaque, uint64_t addr, const void *p, size_t n)
{
    Fixture *x = opaque;
    assert(!ram_probe(opaque, addr, n, true));
    memcpy(x->ram + addr - RAM_BASE, p, n);
    return 0;
}
static void irq(void *opaque, bool level)
{
    Fixture *x = opaque;
    x->irq_changes++; x->irq = level;
}
static void error(void *opaque, const char *what, int rc, uint64_t addr)
{
    Fixture *x = opaque;
    assert(what && rc < 0); (void)addr; x->errors++;
}
static void completed(void *opaque, SonyDWC3Urb *u, int status, uint32_t actual)
{
    Fixture *x = opaque;
    assert(actual <= u->length);
    x->completions++; x->status = status; x->actual = actual; x->last_id = u->id;
}
static void put(unsigned addr, uint32_t v)
{
    assert(addr <= RAM_SIZE - 4);
    for (unsigned i = 0; i < 4; i++) { f.ram[addr + i] = v >> (8 * i); }
}
static uint32_t get(unsigned addr)
{
    uint32_t v = 0;
    for (unsigned i = 0; i < 4; i++) { v |= (uint32_t)f.ram[addr + i] << (8 * i); }
    return v;
}
static void wr(uint32_t off, uint32_t v)
{
    assert(sony_dwc3_write(&f.s, off, 4, v) == 0);
}
static uint32_t rd(uint32_t off)
{
    uint32_t v;
    assert(sony_dwc3_read(&f.s, off, 4, &v) == 0);
    return v;
}
static void cmd(unsigned ep, unsigned op, uint32_t p0, uint32_t p1)
{
    wr(SDWC_PAR2(ep), 0); wr(SDWC_PAR1(ep), p1); wr(SDWC_PAR0(ep), p0);
    wr(SDWC_CMD(ep), SDWC_CMDACT | op);
}
static void config(unsigned ep, unsigned mps)
{
    cmd(ep, 1, ((ep < 2 ? 0u : 2u) << 1) | (mps << 3),
        (ep << 25) | SDWC_CFG_COMPLETE | SDWC_CFG_PROGRESS | SDWC_CFG_NOTREADY);
    cmd(ep, 2, 1, 0);
    wr(SDWC_DALEPENA, rd(SDWC_DALEPENA) | (1u << ep));
}
static void trb(unsigned addr, uint64_t buf, uint32_t size, unsigned type, uint32_t flags)
{
    put(addr, buf); put(addr + 4, buf >> 32); put(addr + 8, size);
    put(addr + 12, SDWC_TRB_TYPE(type) | flags);
}
static void start(unsigned ep, unsigned addr)
{
    cmd(ep, 6, PHYS(addr) >> 32, (uint32_t)PHYS(addr));
    assert(!(rd(SDWC_CMD(ep)) & (1u << 10)));
    assert((rd(SDWC_CMD(ep)) >> 16) == ep + 1);
}
static void ack(void)
{
    wr(SDWC_GEVNTCOUNT, rd(SDWC_GEVNTCOUNT));
}
static SonyDWC3Urb urb(uint64_t id, unsigned ep, unsigned in, uint8_t *data, unsigned n)
{
    SonyDWC3Urb u = {
        .id = id, .endpoint = ep, .direction = in, .data = data, .length = n,
        .complete = completed, .opaque = &f,
    };
    u.setup[0] = in ? 0xc0 : 0x40; u.setup[1] = 0x5a;
    u.setup[6] = n; u.setup[7] = n >> 8;
    return u;
}
static void init(void)
{
    memset(&f, 0, sizeof(f));
    const SonyDWC3Ops ops = {
        .probe = ram_probe, .read = ram_read, .write = ram_write,
        .irq = irq, .error = error,
    };
    sony_dwc3_init(&f.s, &ops, &f); f.s.ops.generation = enabled ? observe : NULL;
    assert(rd(SDWC_GSNPSID) == 0x5533290a);
    assert(rd(SDWC_DSTS) & (1u << 22));
    assert(!sony_dwc3_ready(&f.s));
    wr(SDWC_GEVNTADRLO, (uint32_t)PHYS(EVENT)); wr(SDWC_GEVNTADRHI, PHYS(EVENT) >> 32);
    wr(SDWC_GEVNTSIZ, 0x1000);
    wr(SDWC_DEVTEN, 7);
    config(0, 64); config(1, 64);
    wr(SDWC_DCTL, SDWC_RUN);
    assert(!sony_dwc3_ready(&f.s));
    assert(!sony_dwc3_set_vbus(&f.s, true));
    assert(sony_dwc3_ready(&f.s));
    assert(rd(SDWC_GEVNTCOUNT) == 8 && f.irq);
    assert(get(EVENT) == 0x101 && get(EVENT + 4) == 0x201);
    ack();
    assert(!f.irq);
}

static void test_control_in(void)
{
    uint8_t data[64] = {0};
    init();
    trb(RING, PHYS(BUFFER), 8, SDWC_TRB_SETUP, SDWC_HWO | SDWC_LST | SDWC_IOC);
    start(0, RING);
    SonyDWC3Urb u = urb(11, 0, 1, data, sizeof(data));
    assert(!sony_dwc3_submit(&f.s, &u));
    assert(!memcmp(f.ram + BUFFER, u.setup, 8));
    assert(!(get(RING + 12) & SDWC_HWO));
    assert(f.completions == 0 && rd(SDWC_GEVNTCOUNT) == 4);
    assert(((get(EVENT + 8) >> 6) & 15) == 1);
    /* The synthetic guest consumes SETUP, then provides its own response. */
    memcpy(f.ram + BUFFER + 0x100, "guest-response", 14);
    trb(RING + 0x100, PHYS(BUFFER + 0x100), 14, SDWC_TRB_DATA,
        SDWC_HWO | SDWC_LST | SDWC_IOC);
    start(1, RING + 0x100);
    assert(!memcmp(data, "guest-response", 14));
    assert(f.completions == 0);
    assert(!(get(RING + 0x10c) & SDWC_HWO));
    ack(); /* Drives genuine STATUS not-ready, no successful empty ACK. */
    assert(f.completions == 0);
    trb(RING + 0x200, PHYS(BUFFER), 0, SDWC_TRB_STATUS3,
        SDWC_HWO | SDWC_LST | SDWC_IOC);
    start(0, RING + 0x200);
    assert(f.completions == 1 && f.status == 0 && f.actual == 14);
    assert(f.last_id == 11 && f.irq && f.s.events_written >= 5);
}

static void test_control_out_address_config(void)
{
    uint8_t bytes[] = { 1, 3, 5, 7 };
    init();
    SonyDWC3Urb u = urb(12, 0, 0, bytes, sizeof(bytes));
    trb(RING, PHYS(BUFFER), 8, SDWC_TRB_SETUP, SDWC_HWO | SDWC_LST);
    start(0, RING);
    assert(!sony_dwc3_submit(&f.s, &u));
    trb(RING + 16, PHYS(BUFFER + 0x100), 64, SDWC_TRB_DATA,
        SDWC_HWO | SDWC_LST | SDWC_IOC);
    start(0, RING + 16);
    assert(!memcmp(f.ram + BUFFER + 0x100, bytes, 4));
    assert((get(RING + 24) & SDWC_SIZE_MASK) == 60);
    trb(RING + 32, 0, 0, SDWC_TRB_STATUS3, SDWC_HWO | SDWC_LST);
    start(1, RING + 32);
    assert(f.completions == 1 && f.actual == 4 && !f.status);
    /* SET_ADDRESS/CONFIG are never interpreted by the host-side model. */
    for (unsigned request = 5; request <= 9; request += 4) {
        u = urb(20 + request, 0, 0, NULL, 0);
        u.setup[0] = 0; u.setup[1] = request; u.setup[2] = 7;
        trb(RING, PHYS(BUFFER), 8, SDWC_TRB_SETUP, SDWC_HWO | SDWC_LST);
        start(0, RING);
        assert(!sony_dwc3_submit(&f.s, &u));
        assert(!memcmp(f.ram + BUFFER, u.setup, 8));
        assert(!(rd(SDWC_DCFG) & (127u << 3)) || request == 9);
        if (request == 5) { wr(SDWC_DCFG, 7u << 3); }
        unsigned before = f.completions;
        trb(RING + 32, 0, 0, SDWC_TRB_STATUS2, SDWC_HWO | SDWC_LST);
        start(1, RING + 32);
        assert(f.completions == before + 1 && !f.status);
    }
    assert(((rd(SDWC_DCFG) >> 3) & 127) == 7);
}

static void test_pending_hwo_and_unlink(void)
{
    uint8_t in[16] = {0};
    init(); config(3, 64);
    SonyDWC3Urb u = urb(30, 1, 1, in, sizeof(in));
    assert(!sony_dwc3_submit(&f.s, &u));
    assert(!f.completions); /* no guest transfer is NAK/pending */
    trb(RING, PHYS(BUFFER), 6, SDWC_TRB_NORMAL, SDWC_LST | SDWC_IOC);
    memcpy(f.ram + BUFFER, "abcdef", 6);
    start(3, RING);
    assert(!f.completions && get(RING + 8) == 6);
    assert(!sony_dwc3_cancel(&f.s, 30));
    assert(sony_dwc3_cancel(&f.s, 30) == -ENOENT);
    put(RING + 12, get(RING + 12) | SDWC_HWO);
    sony_dwc3_pump(&f.s);
    assert(!f.completions && !in[0] && (get(RING + 12) & SDWC_HWO));
    u.id++;
    assert(!sony_dwc3_submit(&f.s, &u));
    assert(f.completions == 1 && f.actual == 6 && !memcmp(in, "abcdef", 6));
}

static void test_chain_link_and_short(void)
{
    uint8_t data[128] = {0};
    init(); config(2, 64);
    trb(RING, PHYS(RING + 16), 0, SDWC_TRB_LINK, SDWC_HWO);
    trb(RING + 16, PHYS(BUFFER), 64, SDWC_TRB_NORMAL, SDWC_HWO | SDWC_CHN);
    trb(RING + 32, PHYS(BUFFER + 64), 64, SDWC_TRB_NORMAL,
        SDWC_HWO | SDWC_LST | SDWC_IOC | SDWC_ISP);
    start(2, RING);
    for (unsigned i = 0; i < 70; i++) { data[i] = i + 1; }
    SonyDWC3Urb u = urb(40, 1, 0, data, 70);
    assert(!sony_dwc3_submit(&f.s, &u));
    assert(f.completions == 1 && !f.status && f.actual == 70);
    assert(!memcmp(data, f.ram + BUFFER, 70));
    assert(get(RING + 12) & SDWC_HWO); /* LINK remains reusable */
    assert(!(get(RING + 28) & SDWC_HWO) && !(get(RING + 44) & SDWC_HWO));
    assert((get(RING + 40) & SDWC_SIZE_MASK) == 58);
    uint32_t e = get(EVENT + f.s.event_pos - 4);
    assert(((e >> 12) & 15) == (2 | 4 | 8));
    assert(f.irq);
}

static void test_in_partial_and_packet_boundary(void)
{
    uint8_t a[32] = {0}, b[64] = {0}, c[64] = {0};
    init(); config(3, 64);
    memset(f.ram + BUFFER, 0x55, 64);
    trb(RING, PHYS(BUFFER), 64, SDWC_TRB_NORMAL, SDWC_HWO | SDWC_LST | SDWC_IOC);
    start(3, RING);
    SonyDWC3Urb u = urb(50, 1, 1, a, 32);
    assert(!sony_dwc3_submit(&f.s, &u));
    assert(f.completions == 1 && f.actual == 32 && (get(RING + 12) & SDWC_HWO));
    u = urb(51, 1, 1, b, 64);
    assert(!sony_dwc3_submit(&f.s, &u));
    assert(f.completions == 1 && !(get(RING + 12) & SDWC_HWO));
    /* A 64-byte packet ending a guest request is not a USB short packet. */
    memcpy(f.ram + BUFFER + 64, "tail", 4);
    trb(RING + 16, PHYS(BUFFER + 64), 4, SDWC_TRB_NORMAL, SDWC_HWO | SDWC_IOC | SDWC_LST);
    start(3, RING + 16);
    assert(f.completions == 2 && f.actual == 36 && !memcmp(b + 32, "tail", 4));
    SonyDWC3Urb v = urb(52, 1, 1, c, 64);
    v.flags = 1;
    trb(RING, PHYS(BUFFER), 3, SDWC_TRB_NORMAL, SDWC_HWO | SDWC_IOC | SDWC_LST);
    start(3, RING);
    assert(!sony_dwc3_submit(&f.s, &v));
    assert(f.status == -EREMOTEIO && f.actual == 3);
}

static void test_stall_end_reset_disconnect(void)
{
    uint8_t data[8] = {0};
    init(); config(3, 64);
    cmd(3, 4, 0, 0);
    SonyDWC3Urb u = urb(60, 1, 1, data, 8);
    assert(!sony_dwc3_submit(&f.s, &u));
    assert(f.completions == 1 && f.status == -EPIPE);
    cmd(3, 5, 0, 0);
    trb(RING, PHYS(BUFFER), 8, SDWC_TRB_NORMAL, SDWC_LST);
    start(3, RING);
    u.id++;
    assert(!sony_dwc3_submit(&f.s, &u));
    wr(SDWC_CMD(3), SDWC_CMDACT | SDWC_CMDIOC | 8 | (4u << 16));
    assert(!f.s.ep[3].active && f.completions == 2 && f.status == -ECONNRESET);
    assert(((get(EVENT + f.s.event_pos - 4) >> 6) & 15) == 7);
    u.id++; assert(!sony_dwc3_submit(&f.s, &u));
    wr(SDWC_DCFG, 7u << 3);
    assert(!sony_dwc3_bus_reset(&f.s));
    assert(f.completions == 3 && f.status == -ECONNRESET);
    assert(!(rd(SDWC_DCFG) & (127u << 3)));
    u.id++; assert(!sony_dwc3_submit(&f.s, &u));
    assert(!sony_dwc3_set_vbus(&f.s, false));
    assert(f.completions == 4 && f.status == -ENODEV && !sony_dwc3_ready(&f.s));
    assert(sony_dwc3_submit(&f.s, &u) == -ENODEV);
}

static void test_errors_and_event_backpressure(void)
{
    uint8_t data[8] = {0};
    uint32_t value;
    init(); config(3, 64);
    assert(sony_dwc3_read(&f.s, 0x9000, 4, &value) == -EOPNOTSUPP && value == UINT32_MAX);
    assert(sony_dwc3_write(&f.s, 0xc101, 4, 0) == -EOPNOTSUPP);
    assert(sony_dwc3_read(&f.s, SDWC_DCTL, 1, &value) == -EOPNOTSUPP);
    assert(sony_dwc3_write(&f.s, SDWC_CMD(3), 4, SDWC_CMDACT | 15) == -EOPNOTSUPP);
    assert((rd(SDWC_CMD(3)) >> 12 & 15) == 1 && !(rd(SDWC_CMD(3)) & SDWC_CMDACT));
    assert(sony_dwc3_write(&f.s, SDWC_GEVNTCOUNT, 4, 4) == -EINVAL);
    trb(RING, UINT64_MAX - 3, 8, SDWC_TRB_NORMAL, SDWC_HWO | SDWC_IOC | SDWC_LST);
    start(3, RING);
    SonyDWC3Urb u = urb(70, 1, 1, data, 8);
    assert(!sony_dwc3_submit(&f.s, &u));
    assert(f.status == -EFAULT && f.actual == 0 && (get(RING + 12) & SDWC_HWO));
    cmd(3, 8 | (4u << 16), 0, 0);
    ack(); wr(SDWC_GEVNTADRLO, (uint32_t)PHYS(EVENT));
    wr(SDWC_GEVNTSIZ, 4); /* exactly one event entry */
    trb(RING, PHYS(BUFFER), 3, SDWC_TRB_NORMAL, SDWC_HWO | SDWC_LST | SDWC_IOC);
    memcpy(f.ram + BUFFER, "one", 3);
    start(3, RING);
    u.id++; assert(!sony_dwc3_submit(&f.s, &u));
    assert(f.status == 0 && f.actual == 3 && rd(SDWC_GEVNTCOUNT) == 4);
    wr(SDWC_GEVNTSIZ, 4 | SDWC_INTMASK);
    assert(!f.irq);
    wr(SDWC_GEVNTSIZ, 4);
    assert(f.irq);
    trb(RING + 16, PHYS(BUFFER), 3, SDWC_TRB_NORMAL, SDWC_HWO | SDWC_LST | SDWC_IOC);
    start(3, RING + 16);
    u.id++;
    /* Full event ring makes backend not ready and prevents any export/submit. */
    assert(sony_dwc3_submit(&f.s, &u) == -ENODEV);
    ack();
    assert(!sony_dwc3_submit(&f.s, &u));
    assert(f.actual == 3 && !(get(RING + 28) & SDWC_HWO));
    assert(f.errors >= 6 && f.s.unsupported >= 4 && f.s.dma_errors);
}

static void test_update_out_packets_and_zlp(void)
{
    uint8_t data[128];
    memset(data, 0x73, sizeof(data));
    init(); config(2, 64);
    trb(RING, PHYS(BUFFER), 128, SDWC_TRB_NORMAL, SDWC_LST | SDWC_IOC);
    start(2, RING);
    SonyDWC3Urb a = urb(90, 1, 0, data, 64);
    assert(!sony_dwc3_submit(&f.s, &a) && !f.completions);
    put(RING + 12, get(RING + 12) | SDWC_HWO);
    wr(SDWC_CMD(2), SDWC_CMDACT | 7 | (3u << 16));
    assert(f.completions == 1 && f.actual == 64 && (get(RING + 12) & SDWC_HWO));
    assert(f.s.ep[2].offset == 64 && !memcmp(data, f.ram + BUFFER, 64));
    a.id++; a.length = 3;
    assert(!sony_dwc3_submit(&f.s, &a));
    assert(f.completions == 2 && f.actual == 3 && !(get(RING + 12) & SDWC_HWO));
    assert((get(RING + 8) & SDWC_SIZE_MASK) == 61);
    trb(RING, PHYS(BUFFER), 128, SDWC_TRB_NORMAL, SDWC_HWO | SDWC_LST | SDWC_IOC);
    start(2, RING);
    a.id++; a.length = 64; a.flags = 0x40;
    assert(!sony_dwc3_submit(&f.s, &a));
    assert(f.completions == 3 && f.actual == 64 && !f.status);
    assert((get(RING + 8) & SDWC_SIZE_MASK) == 64 && !(get(RING + 12) & SDWC_HWO));
    trb(RING, PHYS(BUFFER), 4, SDWC_TRB_NORMAL, SDWC_HWO | SDWC_LST | SDWC_IOC);
    start(2, RING);
    a.id++; a.length = 8; a.flags = 0;
    assert(!sony_dwc3_submit(&f.s, &a));
    assert(f.status == -EOVERFLOW && !f.actual && (get(RING + 12) & SDWC_HWO));
}

static void test_control_chain_bounce_and_stall(void)
{
    uint8_t data[4] = {1, 2, 3, 4};
    init();
    trb(RING, PHYS(BUFFER), 8, SDWC_TRB_SETUP, SDWC_HWO | SDWC_LST);
    start(0, RING);
    SonyDWC3Urb u = urb(100, 0, 0, data, 4);
    assert(!sony_dwc3_submit(&f.s, &u));
    trb(RING + 16, PHYS(BUFFER + 64), 4, SDWC_TRB_DATA, SDWC_HWO | SDWC_CHN);
    trb(RING + 32, PHYS(BUFFER + 128), 60, SDWC_TRB_DATA, SDWC_HWO | SDWC_LST);
    start(0, RING + 16);
    assert(!(get(RING + 28) & SDWC_HWO) && !(get(RING + 44) & SDWC_HWO));
    assert((get(RING + 40) & SDWC_SIZE_MASK) == 60 && !f.completions);
    trb(RING + 48, 0, 0, SDWC_TRB_STATUS3, SDWC_HWO | SDWC_LST);
    start(1, RING + 48);
    assert(f.completions == 1 && !f.status && f.actual == 4);
    trb(RING, PHYS(BUFFER), 8, SDWC_TRB_SETUP, SDWC_HWO | SDWC_LST);
    start(0, RING);
    u.id++; assert(!sony_dwc3_submit(&f.s, &u));
    cmd(0, 4, 0, 0);
    assert(f.completions == 2 && f.status == -EPIPE && !f.actual);
}

static void test_queue_cancel_and_ep0_reset(void)
{
    uint8_t data[2][8] = {{0}};
    init(); config(3, 64);
    SonyDWC3Urb a = urb(80, 1, 1, data[0], 8), b = urb(81, 1, 1, data[1], 8);
    assert(!sony_dwc3_submit(&f.s, &a));
    assert(!sony_dwc3_submit(&f.s, &b));
    assert(sony_dwc3_submit(&f.s, &a) == -EEXIST);
    assert(!sony_dwc3_cancel(&f.s, 80));
    trb(RING, PHYS(BUFFER), 3, SDWC_TRB_NORMAL, SDWC_HWO | SDWC_LST | SDWC_IOC);
    memcpy(f.ram + BUFFER, "new", 3);
    start(3, RING);
    assert(f.completions == 1 && f.last_id == 81 && !data[0][0]);
    a = urb(82, 0, 1, data[0], 8);
    trb(RING, PHYS(BUFFER), 8, SDWC_TRB_SETUP, SDWC_HWO | SDWC_LST);
    start(0, RING);
    assert(!sony_dwc3_submit(&f.s, &a));
    assert(!sony_dwc3_cancel(&f.s, 82));
    assert(f.s.ep0_desynced && !sony_dwc3_ready(&f.s));
    assert(!sony_dwc3_bus_reset(&f.s));
    assert(!f.s.ep0_desynced && sony_dwc3_ready(&f.s));
    wr(SDWC_DCTL, SDWC_SOFTRST);
    assert(!sony_dwc3_ready(&f.s) && !rd(SDWC_GEVNTCOUNT) && !f.irq);
}

static void generation_sequence(void) {
    uint8_t bytes[8] = {0};
    init(); config(3,64);
    SonyDWC3Urb u=urb(123,1,1,bytes,8);
    assert(!sony_dwc3_submit(&f.s,&u));
    uint64_t generation=f.s.cable_generation;
    assert(!sony_dwc3_set_vbus(&f.s,true));
    assert(f.s.cable_generation==generation);
    wr(SDWC_DALEPENA, rd(SDWC_DALEPENA)&~1u);
    assert(f.s.cable_generation==generation+1 && !f.completions);
    assert(!sony_dwc3_set_vbus(&f.s,false));
    assert(f.completions==1 && f.status==-ENODEV && !f.s.reserved_bytes);
    uint64_t dma=f.s.dma_bytes;
    sony_dwc3_pump(&f.s);
    assert(f.s.dma_bytes==dma && !bytes[0]);
    sony_dwc3_reset(&f.s);
    wr(SDWC_DCTL,SDWC_SOFTRST);
    init(); config(3,64);
    u=urb(124,1,1,bytes,8);
    assert(!sony_dwc3_submit(&f.s,&u));
    wr(SDWC_DCTL,0);
    assert(f.completions==1 && f.status==-ESHUTDOWN);
}
static void test_no_response_update(void) {
    init();config(4,512);trb(RING,PHYS(BUFFER),512,SDWC_TRB_NORMAL,SDWC_IOC|SDWC_LST);
    start(4,RING);uint64_t dma=f.s.dma_bytes;unsigned completions=f.completions;
    assert(!sony_dwc3_write(&f.s,SDWC_CMD(4),4,0x50007));
    assert(f.s.ep[4].active && f.s.ep[4].resource==5 && f.s.dma_bytes==dma && f.completions==completions);
    assert(sony_dwc3_write(&f.s,SDWC_CMD(4),4,0x60007)==-EINVAL);
    assert(sony_dwc3_write(&f.s,SDWC_CMD(0),4,0x10007)==-EINVAL);
    assert(sony_dwc3_write(&f.s,SDWC_CMD(4),4,0x50007|SDWC_CMDIOC)==-EINVAL);
    assert(f.s.ep[4].active && f.s.dma_bytes==dma && f.completions==completions);
}
static void compare(void (*scenario)(void)) {
    static Fixture before;
    enabled=0; snapshots=0; scenario(); assert(!snapshots);
    f.s.ops.generation=NULL; before=f;
    enabled=1; scenario(); assert(snapshots);
    f.s.ops.generation=NULL;
    assert(!memcmp(&before,&f,sizeof f));
}
int main(void) {
    test_no_response_update();
    init();
    assert((rd(SDWC_GHWPARAMS0)&3u)==2);
    uint32_t old_control=rd(SDWC_GCTL);
    uint64_t old_dma=f.s.dma_bytes;
    assert(sony_dwc3_write(&f.s,SDWC_GCTL,4,(old_control&~(3u<<12))|(1u<<12))==-EOPNOTSUPP);
    assert(rd(SDWC_GCTL)==old_control && f.s.dma_bytes==old_dma);
    void (*tests[])(void)={test_control_in,test_control_out_address_config,
        test_pending_hwo_and_unlink,test_chain_link_and_short,
        test_in_partial_and_packet_boundary,test_stall_end_reset_disconnect,
        test_errors_and_event_backpressure,test_queue_cancel_and_ep0_reset,
        test_update_out_packets_and_zlp,test_control_chain_bounce_and_stall,generation_sequence};
    for(unsigned i=0;i<sizeof tests/sizeof *tests;i++)compare(tests[i]);
    bool causes[5]={0},drained=false;
    for(unsigned i=0;i<snapshots;i++) {
        assert(observed[i].cause<=SDWC_CAUSE_EP0_DISABLE);
        assert(observed[i].new_generation==observed[i].old_generation+1);
        causes[observed[i].cause]=true;
        drained|=observed[i].drained>0;
    }
    for(unsigned i=0;i<5;i++)assert(causes[i]);
    assert(drained);
    puts("11 paired scenarios: complete core/fixture state, DMA, counters, IRQ, cancel and errors identical; all five causes and actual drains observed");
    return 0;
}
