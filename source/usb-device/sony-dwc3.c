/* SPDX-License-Identifier: MIT */
#ifdef SONY_DWC3_QEMU
#include "qemu/osdep.h"
#include "qemu/log.h"
#endif
#include "sony-dwc3.h"
#include <errno.h>
#include <limits.h>
#include <string.h>

#define REG(s, r) ((s)->regs[(r) / 4])
#define EV_COMPLETE 1u
#define EV_PROGRESS 2u
#define EV_NOTREADY 3u
#define EV_COMMAND 7u
#define ST_BUSERR 1u
#define ST_SHORT 2u
#define ST_IOC 4u
#define ST_LST 8u
#define DSTS_HALT (1u << 22)
#define MAX_TRBS 256u

static uint32_t get32(const uint8_t *p)
{
    return (uint32_t)p[0] | (uint32_t)p[1] << 8 |
           (uint32_t)p[2] << 16 | (uint32_t)p[3] << 24;
}

static void put32(uint8_t *p, uint32_t v)
{
    p[0] = v; p[1] = v >> 8; p[2] = v >> 16; p[3] = v >> 24;
}

static int fail(SonyDWC3 *s, const char *what, int err, uint64_t addr)
{
    s->last_error = err;
    if (err == -EOPNOTSUPP) {
        s->unsupported++;
    }
    if (s->ops.error) {
        s->ops.error(s->opaque, what, err, addr);
    }
    return err;
}

static int probe(SonyDWC3 *s, uint64_t addr, size_t n, bool wr)
{
    if (n && (addr > UINT64_MAX - n || !s->ops.probe ||
              s->ops.probe(s->opaque, addr, n, wr))) {
        s->dma_errors++;
        return fail(s, "DMA is not accessible guest RAM", -EFAULT, addr);
    }
    return 0;
}

static int dma_read(SonyDWC3 *s, uint64_t addr, void *p, size_t n)
{
    if (probe(s, addr, n, false) || (n && s->ops.read(s->opaque, addr, p, n))) {
        return fail(s, "DMA read failed", -EFAULT, addr);
    }
    s->dma_bytes += n;
    return 0;
}

static int dma_write(SonyDWC3 *s, uint64_t addr, const void *p, size_t n)
{
    if (probe(s, addr, n, true) || (n && s->ops.write(s->opaque, addr, p, n))) {
        return fail(s, "DMA write failed", -EFAULT, addr);
    }
    s->dma_bytes += n;
    return 0;
}

static uint64_t event_base(SonyDWC3 *s)
{
    return REG(s, SDWC_GEVNTADRLO) | (uint64_t)REG(s, SDWC_GEVNTADRHI) << 32;
}

static void irq_update(SonyDWC3 *s)
{
    bool level = s->event_count && !(REG(s, SDWC_GEVNTSIZ) & SDWC_INTMASK);
    if (level != s->irq_level) {
        s->irq_level = level;
        if (s->ops.irq) {
            s->ops.irq(s->opaque, level);
        }
    }
}

static int event_space(SonyDWC3 *s)
{
    uint32_t size = REG(s, SDWC_GEVNTSIZ) & 0xffff;
    uint64_t base = event_base(s);
    if (size < 4 || (size & 3) || (base & 3)) {
        return -EAGAIN;
    }
    if (s->event_count > size - 4) {
        return -ENOSPC;
    }
    if (base > UINT64_MAX - size || probe(s, base, size, true)) {
        return -EFAULT;
    }
    return 0;
}

static int event(SonyDWC3 *s, uint32_t value)
{
    uint8_t bytes[4];
    int rc = event_space(s);
    if (rc) {
        return rc;
    }
    put32(bytes, value);
    if (dma_write(s, event_base(s) + s->event_pos, bytes, 4)) {
        return -EFAULT;
    }
    s->event_pos = (s->event_pos + 4) % (REG(s, SDWC_GEVNTSIZ) & 0xffff);
    s->event_count += 4;
    s->events_written++;
    irq_update(s);
    return 0;
}

static int ep_event(SonyDWC3 *s, unsigned ep, unsigned type,
                    unsigned status, unsigned parameter)
{
    return event(s, (ep << 1) | (type << 6) | (status << 12) | (parameter << 16));
}

static int dev_event(SonyDWC3 *s, unsigned type)
{
    if (!(REG(s, SDWC_DEVTEN) & (1u << type))) {
        return 0;
    }
    return event(s, 1u | (type << 8));
}

static void finish(SonyDWC3 *s, SonyDWC3Pending *p, int status)
{
    SonyDWC3Urb *u = p->urb;
    uint32_t actual = p->actual;
    s->reserved_bytes -= u->length;
    memset(p, 0, sizeof(*p));
    u->complete(u->opaque, u, status, actual);
}

static unsigned drain(SonyDWC3 *s, int status)
{
    unsigned count = 0;
    bool was_resetting = s->resetting;
    s->resetting = true;
    for (unsigned i = 0; i < SDWC_MAX_URBS; i++) {
        if (s->pending[i].urb) {
            finish(s, &s->pending[i], status);
            count++;
        }
    }
    s->resetting = was_resetting;
    return count;
}

static void observe_generation(SonyDWC3 *s, SonyDWC3GenerationCause cause,
                               uint64_t old, unsigned drained)
{
    if (!s->ops.generation) { return; }
    SonyDWC3Generation g = {
        .old_generation = old, .new_generation = s->cable_generation,
        .event_base = event_base(s), .dctl = REG(s, SDWC_DCTL),
        .dalepena = REG(s, SDWC_DALEPENA),
        .event_size = REG(s, SDWC_GEVNTSIZ), .event_count = s->event_count,
        .drained = drained, .vbus = s->vbus, .connected = s->connected,
        .ep0_desynced = s->ep0_desynced, .cause = cause,
    };
    for (unsigned n = 0; n < SDWC_ENDPOINTS; n++) {
        if (s->ep[n].configured) { g.configured |= 1u << n; }
        if (s->ep[n].allocated) { g.allocated |= 1u << n; }
        if (s->ep[n].active) { g.active |= 1u << n; }
    }
    for (unsigned n = 0; n < SDWC_MAX_URBS; n++) {
        g.pending += s->pending[n].urb != NULL;
    }
    s->ops.generation(s->opaque, &g);
}

static void reset_core(SonyDWC3 *s, SonyDWC3GenerationCause cause)
{
    SonyDWC3Ops ops = s->ops;
    void *opaque = s->opaque;
    bool vbus = s->vbus;
    uint64_t generation = s->cable_generation + 1;
    unsigned drained = drain(s, -ESHUTDOWN);
    if (s->irq_level && ops.irq) {
        ops.irq(opaque, false);
    }
    memset(s, 0, sizeof(*s));
    s->ops = ops; s->opaque = opaque; s->vbus = vbus;
    s->cable_generation = generation;
    /* Read-only metadata for Sony's OTG status helper, not an xHCI engine. */
    REG(s, SDWC_HC_CAPBASE) = 0x01000040; /* HCIVERSION 1.0, CAPLENGTH 0x40. */
    REG(s, SDWC_HC_HCSPARAMS1) = 0; /* No host ports in this device profile. */
    REG(s, SDWC_GSNPSID) = 0x5533290a; /* DWC_usb3 revision 2.90a. */
    REG(s, SDWC_GCTL) = 2u << 12;    /* Device only, not an xHCI host. */
    REG(s, SDWC_GHWPARAMS0) = 0x40404002; /* Functional DRD peripheral switching; host mode remains rejected. */
    REG(s, SDWC_GHWPARAMS0 + 4) = 1u << 15; /* One event buffer/IRQ. */
    REG(s, SDWC_GHWPARAMS0 + 12) = (16u << 18) | (32u << 12) | 4u;
    REG(s, SDWC_GHWPARAMS0 + 28) = 0x04000400; /* Functional FIFO depth. */
    REG(s, SDWC_DSTS) = DSTS_HALT;
    for (unsigned i = 0; i < 16; i++) {
        REG(s, 0xc300 + i * 4) = (i * 1024u << 16) | 1024u;
    }
    REG(s, 0xc380) = 1024;
    observe_generation(s, cause, generation - 1, drained);
}

void sony_dwc3_reset(SonyDWC3 *s)
{
    reset_core(s, SDWC_CAUSE_RESET);
}

void sony_dwc3_init(SonyDWC3 *s, const SonyDWC3Ops *ops, void *opaque)
{
    memset(s, 0, sizeof(*s));
    s->ops = *ops; s->opaque = opaque;
    sony_dwc3_reset(s);
}

static bool running(SonyDWC3 *s)
{
    return s->vbus && s->connected && !s->resetting &&
           (REG(s, SDWC_DCTL) & SDWC_RUN);
}

bool sony_dwc3_ready(SonyDWC3 *s)
{
    return running(s) && !s->ep0_desynced &&
           (REG(s, SDWC_DALEPENA) & 3) == 3 &&
           s->ep[0].configured && s->ep[1].configured &&
           s->ep[0].allocated && s->ep[1].allocated &&
           event_space(s) == 0;
}

static int link_up(SonyDWC3 *s)
{
    if (s->connected || !s->vbus || !(REG(s, SDWC_DCTL) & SDWC_RUN)) {
        return 0;
    }
    /* Preflight both device events so a full ring cannot claim connection. */
    unsigned bytes = ((REG(s, SDWC_DEVTEN) >> 1) & 1) * 4 +
                     ((REG(s, SDWC_DEVTEN) >> 2) & 1) * 4;
    uint32_t size = REG(s, SDWC_GEVNTSIZ) & 0xffff;
    if (event_space(s) || bytes > size - s->event_count) {
        return -EAGAIN;
    }
    s->connected = true;
    REG(s, SDWC_DSTS) = 0; /* USB2 high-speed functional link. */
    dev_event(s, 1);
    dev_event(s, 2);
    return 0;
}

int sony_dwc3_set_vbus(SonyDWC3 *s, bool present)
{
    if (present == s->vbus) {
        return present ? link_up(s) : 0;
    }
    s->vbus = present;
    s->cable_generation++;
    if (present) {
        int rc = link_up(s);
        observe_generation(s, SDWC_CAUSE_VBUS, s->cable_generation - 1, 0);
        return rc;
    }
    bool connected = s->connected;
    s->connected = false;
    unsigned drained = drain(s, -ENODEV);
    for (unsigned n = 0; n < SDWC_ENDPOINTS; n++) {
        s->ep[n].active = false;
        s->ep[n].offset = 0;
    }
    s->ep0_desynced = false;
    REG(s, SDWC_DSTS) = (REG(s, SDWC_DCTL) & SDWC_RUN ? 0 : DSTS_HALT) |
                         (5u << 18);
    int rc = connected ? dev_event(s, 0) : 0;
    observe_generation(s, SDWC_CAUSE_VBUS, s->cable_generation - 1, drained);
    return rc;
}

int sony_dwc3_bus_reset(SonyDWC3 *s)
{
    if (!running(s)) {
        return -ENODEV;
    }
    unsigned bytes = ((REG(s, SDWC_DEVTEN) >> 1) & 1) * 4 +
                     ((REG(s, SDWC_DEVTEN) >> 2) & 1) * 4;
    uint32_t size = REG(s, SDWC_GEVNTSIZ) & 0xffff;
    if (event_space(s) || bytes > size - s->event_count) {
        return -EAGAIN;
    }
    drain(s, -ECONNRESET);
    for (unsigned n = 0; n < SDWC_ENDPOINTS; n++) {
        /* EP0's outstanding SETUP reception remains valid across USB reset. */
        if (n || s->ep0_desynced) {
            s->ep[n].active = false;
            s->ep[n].offset = 0;
        }
        s->ep[n].stalled = false;
        s->ep[n].nrdy = false;
    }
    s->ep0_desynced = false;
    REG(s, SDWC_DCFG) &= ~(0x7fu << 3);
    dev_event(s, 1);
    return dev_event(s, 2);
}

/* One ring entry; ownership is tested before buffer addresses are used. */
static int trb_read(SonyDWC3 *s, SonyDWC3Endpoint *e, uint32_t w[4])
{
    uint8_t bytes[16];
    if ((e->trb & 15) || dma_read(s, e->trb, bytes, 16)) {
        return -EFAULT;
    }
    for (unsigned i = 0; i < 4; i++) {
        w[i] = get32(bytes + i * 4);
    }
    return w[3] & SDWC_HWO ? 0 : -EAGAIN;
}

static int trb_write(SonyDWC3 *s, uint64_t addr, uint32_t size, uint32_t ctrl)
{
    uint8_t bytes[8];
    put32(bytes, size); put32(bytes + 4, ctrl);
    return dma_write(s, addr + 8, bytes, 8);
}

static int notify(SonyDWC3 *s, SonyDWC3Pending *p, unsigned ep, unsigned phase)
{
    SonyDWC3Endpoint *e = &s->ep[ep];
    if (p->notified || e->nrdy || !(e->cfg1 & SDWC_CFG_NOTREADY)) {
        return 0;
    }
    int rc = ep_event(s, ep, EV_NOTREADY, phase, e->resource);
    if (!rc) {
        p->notified = true;
        e->nrdy = true;
    }
    return rc;
}

/* Run until this token needs the guest, a packet boundary or an event slot.
 * A partially consumed IN TRB retains HWO/offset for the next host URB.
 */
static int transfer(SonyDWC3 *s, SonyDWC3Pending *p, unsigned ep,
                    unsigned type, uint8_t *data, uint32_t length,
                    bool in, bool *done)
{
    SonyDWC3Endpoint *e = &s->ep[ep];
    uint32_t w[4];
    *done = false;
    if (!(REG(s, SDWC_DALEPENA) & (1u << ep)) || !e->configured ||
        !e->allocated || !e->active) {
        return -EAGAIN;
    }
    for (unsigned steps = 0; steps < MAX_TRBS; steps++) {
        int rc = trb_read(s, e, w);
        if (rc) {
            return rc;
        }
        unsigned trbtype = (w[3] >> 4) & 0x3f;
        uint64_t addr = w[0] | (uint64_t)w[1] << 32;
#ifdef SONY_DWC3_QEMU
        if (!in && length > 1024) {
            qemu_log_mask(LOG_GUEST_ERROR,
                "SONY_DWC3_LARGE_TRB ep=%u trb=0x%" PRIx64
                " buffer=0x%" PRIx64 " size=0x%x ctrl=0x%x actual=%u\n",
                ep, e->trb, addr, w[2], w[3], p->actual);
        }
#endif
        if (trbtype == SDWC_TRB_LINK) {
            if (addr == e->trb || (addr & 15) || probe(s, addr, 16, false)) {
                return fail(s, "invalid/cyclic LINK TRB", -EFAULT, addr);
            }
            e->trb = addr;
            e->offset = 0;
            continue; /* Linux's cyclic link remains HWO. */
        }
        if (trbtype != type) {
            return fail(s, "TRB type unsupported for token", -EOPNOTSUPP, e->trb);
        }
        uint32_t capacity = w[2] & SDWC_SIZE_MASK;
        if (e->offset > capacity) {
            return -EFAULT;
        }
        uint32_t remain = capacity - e->offset;
        uint32_t want = length - p->actual;
        uint32_t count = remain < want ? remain : want;
        unsigned packet = (e->cfg0 >> 3) & 0x7ff;
        bool short_packet = !in && want < remain &&
                            (!want || want % packet != 0);
        if ((w[3] & SDWC_LST) && !in && want > remain && !(w[3] & SDWC_CHN) &&
            remain % packet != 0) {
            return fail(s, "OUT packet exceeds guest receive buffer", -EOVERFLOW, e->trb);
        }
        if (!in && count == want && count < remain && !short_packet) {
            /* Full OUT packets leave the guest's larger receive TRB owned. */
            if (addr > UINT64_MAX - e->offset ||
                probe(s, addr + e->offset, count, true) ||
                dma_write(s, addr + e->offset, data + p->actual, count)) {
                return -EFAULT;
            }
            p->actual += count;
            e->offset += count;
            *done = true;
            return 0;
        }
        unsigned mps = (e->cfg0 >> 3) & 0x7ff;
        bool terminal_packet = in && !(w[3] & SDWC_CHN) &&
                               (capacity == 0 || capacity % mps != 0);
        bool consume = count == remain || short_packet;
        bool lst = w[3] & SDWC_LST;
        unsigned evtype = lst ? EV_COMPLETE : EV_PROGRESS;
        if ((type == SDWC_TRB_SETUP && capacity != 8) ||
            ((type == SDWC_TRB_STATUS2 || type == SDWC_TRB_STATUS3) && capacity)) {
            return fail(s, "invalid control TRB length", -EPROTO, e->trb);
        }
        bool control_end = ep < 2 && (!(w[3] & SDWC_CHN) || short_packet);
        bool need_event = consume && (((lst || control_end) &&
            (e->cfg1 & SDWC_CFG_COMPLETE)) ||
            (!lst && !control_end && (e->cfg1 & SDWC_CFG_PROGRESS) &&
             ((w[3] & SDWC_IOC) || (short_packet && (w[3] & SDWC_ISP)))));
        if (control_end) { evtype = EV_COMPLETE; }
        if (need_event) {
            rc = event_space(s);
            if (rc) {
                return rc == -ENOSPC ? -EAGAIN : rc;
            }
        }
        if (addr > UINT64_MAX - e->offset ||
            probe(s, e->trb + 8, 8, true) ||
            probe(s, addr + e->offset, count, !in)) {
            return -EFAULT;
        }
        uint8_t *target = count ? data + p->actual : NULL;
        rc = in ? dma_read(s, addr + e->offset, target, count)
                : dma_write(s, addr + e->offset, target, count);
        if (rc) {
            return rc;
        }
        p->actual += count;
        e->offset += count;
        if (!consume) {
            *done = true; /* Host IN buffer filled; guest transfer stays active. */
            return 0;
        }
        uint32_t residual = capacity - e->offset;
        if (trb_write(s, e->trb, (w[2] & ~SDWC_SIZE_MASK) | residual,
                      w[3] & ~SDWC_HWO)) {
            return -EFAULT;
        }
        unsigned status = (short_packet ? ST_SHORT : 0) |
                          ((w[3] & SDWC_IOC) ? ST_IOC : 0) |
                          (lst ? ST_LST : 0);
        if (need_event && ep_event(s, ep, evtype, status, e->resource)) {
            return -EFAULT;
        }
        if (e->trb > UINT64_MAX - 16) {
            return -EFAULT;
        }
        e->trb += 16;
        e->offset = 0;
        e->nrdy = false;
        if (lst || control_end) {
            e->active = false;
        }
        p->short_packet |= short_packet || terminal_packet;
        if (short_packet || terminal_packet ||
            (p->actual == length && !(ep < 2 && (w[3] & SDWC_CHN)))) {
            *done = true;
            return 0;
        }
        if (lst || control_end) { return -EAGAIN; }
    }
    return fail(s, "TRB walk exceeds bounded profile", -ELOOP, e->trb);
}

static int pump_one(SonyDWC3 *s, SonyDWC3Pending *p)
{
    SonyDWC3Urb *u = p->urb;
    bool done;
    unsigned ep = u->endpoint * 2 + u->direction;
    int rc;
    if (u->endpoint) {
        if (s->ep[ep].stalled) {
            return -EPIPE;
        }
        if (!p->zlp_pending) {
            rc = transfer(s, p, ep, SDWC_TRB_NORMAL, u->data, u->length,
                          u->direction, &done);
#ifdef SONY_DWC3_QEMU
            if (!u->direction && u->length > 1024) {
                qemu_log_mask(LOG_GUEST_ERROR,
                    "SONY_DWC3_LARGE_RESULT ep=%u length=%u actual=%u rc=%d done=%u\n",
                    ep, u->length, p->actual, rc, done);
            }
#endif
            if (rc == -EAGAIN) { notify(s, p, ep, 0); }
            if (rc || !done) { return rc ? rc : -EAGAIN; }
            unsigned mps = (s->ep[ep].cfg0 >> 3) & 0x7ff;
            if (!u->direction && (u->flags & 0x40) && u->length &&
                !p->short_packet && mps && !(u->length % mps)) {
                p->zlp_pending = true;
            }
        }
        if (p->zlp_pending) {
            /* A following OUT ZLP is a real token consuming the guest TRB. */
            SonyDWC3Pending zlp = {0};
            rc = transfer(s, &zlp, ep, SDWC_TRB_NORMAL, NULL, 0, false, &done);
            if (rc || !done) {
                return rc ? rc : -EAGAIN;
            }
            p->zlp_pending = false;
        }
        return 0;
    }
    if (s->ep0_desynced) {
        return -ECONNRESET;
    }
    if ((p->phase && (s->ep[0].stalled || s->ep[1].stalled))) {
        return -EPIPE;
    }
    if (!p->phase) {
        /* A new SETUP clears the protocol stall, as on a USB bus. */
        s->ep[0].stalled = false; s->ep[1].stalled = false;
        SonyDWC3Pending setup = {0};
        rc = transfer(s, &setup, 0, SDWC_TRB_SETUP, u->setup, 8, false, &done);
        if (rc || !done) {
            return rc ? rc : -EAGAIN;
        }
        if (setup.actual != 8) { return -EPROTO; }
        p->phase = u->length ? 1 : 2;
        p->notified = false;
        /* Guest must process SETUP completion before DATA/STATUS NRDY. */
        return -EAGAIN;
    }
    if (p->phase == 1) {
        ep = u->direction;
        rc = transfer(s, p, ep, SDWC_TRB_DATA, u->data, u->length,
                      u->direction, &done);
        if (rc == -EAGAIN) {
            notify(s, p, ep, 1);
        }
        if (rc || !done) {
            return rc ? rc : -EAGAIN;
        }
        p->phase = 2;
        p->notified = false;
        return -EAGAIN;
    }
    ep = u->length ? !u->direction : 1;
    SonyDWC3Pending status = {0};
    rc = transfer(s, &status, ep, u->length ? SDWC_TRB_STATUS3 : SDWC_TRB_STATUS2,
                  NULL, 0, ep, &done);
    if (rc == -EAGAIN) {
        notify(s, p, ep, 2);
    }
    return rc ? rc : (done ? 0 : -EAGAIN);
}

void sony_dwc3_pump(SonyDWC3 *s)
{
    if (s->pumping || !running(s)) {
        return;
    }
    s->pumping = true;
    uint64_t visited = 0;
    for (unsigned step = 0; step < SDWC_MAX_URBS; step++) {
        SonyDWC3Pending *p = NULL;
        unsigned chosen = 0;
        for (unsigned i = 0; i < SDWC_MAX_URBS; i++) {
            SonyDWC3Pending *candidate = &s->pending[i];
            if (candidate->urb && !(visited & (UINT64_C(1) << i)) &&
                (!p || candidate->order < p->order)) {
                p = candidate; chosen = i;
            }
        }
        if (!p) { break; }
        visited |= UINT64_C(1) << chosen;
        bool earlier = false;
        for (unsigned j = 0; j < SDWC_MAX_URBS; j++) {
            SonyDWC3Pending *q = &s->pending[j];
            if (q->urb && q->order < p->order &&
                q->urb->endpoint == p->urb->endpoint &&
                (!p->urb->endpoint || q->urb->direction == p->urb->direction)) {
                earlier = true;
                break;
            }
        }
        if (earlier) { continue; }
        int rc = pump_one(s, p);
        if (rc != -EAGAIN) {
            if (rc && !p->urb->endpoint && p->phase) {
                s->ep0_desynced = rc != -EPIPE;
            } else if (rc && p->urb->endpoint && rc != -EPIPE) {
                s->ep[p->urb->endpoint * 2u + p->urb->direction].active = false;
            }
            if (!rc && (p->urb->flags & 1) && p->urb->direction &&
                p->actual < p->urb->length) {
                rc = -EREMOTEIO;
            }
            finish(s, p, rc);
        }
    }
    s->pumping = false;
}

int sony_dwc3_submit(SonyDWC3 *s, SonyDWC3Urb *u)
{
    unsigned free_slot = SDWC_MAX_URBS;
    if (!u || !u->id || u->endpoint > 15 || u->direction > 1 ||
        !u->complete || u->length > SDWC_MAX_URB ||
        (u->length && !u->data) || (u->flags & ~(1u | 0x40u))) {
        return -EINVAL;
    }
    if (!sony_dwc3_ready(s)) {
        return -ENODEV;
    }
    if (!u->endpoint && (((uint32_t)u->setup[6] | (uint32_t)u->setup[7] << 8) != u->length ||
        (u->length && (u->setup[0] >> 7) != u->direction))) {
        return -EINVAL;
    }
    for (unsigned i = 0; i < SDWC_MAX_URBS; i++) {
        SonyDWC3Urb *old = s->pending[i].urb;
        if (!old) {
            if (free_slot == SDWC_MAX_URBS) {
                free_slot = i;
            }
        } else if (old->id == u->id) {
            return -EEXIST;
        }
    }
    if (free_slot == SDWC_MAX_URBS || u->length > SDWC_MAX_BYTES - s->reserved_bytes) {
        return -ENOSPC;
    }
    SonyDWC3Pending *p = &s->pending[free_slot];
    memset(p, 0, sizeof(*p));
    p->urb = u;
    p->order = ++s->next_order;
    s->reserved_bytes += u->length;
    sony_dwc3_pump(s);
    return 0;
}

int sony_dwc3_cancel(SonyDWC3 *s, uint64_t id)
{
    for (unsigned i = 0; i < SDWC_MAX_URBS; i++) {
        SonyDWC3Pending *p = &s->pending[i];
        if (p->urb && p->urb->id == id) {
            /* Bus unlink does not dequeue the gadget's request. It removes
             * this host token synchronously, and no future DMA can reference it. */
            if (!p->urb->endpoint && p->phase) {
                s->ep0_desynced = true;
            }
            s->reserved_bytes -= p->urb->length;
            memset(p, 0, sizeof(*p));
            return 0;
        }
    }
    return -ENOENT;
}

static int command(SonyDWC3 *s, unsigned n, uint32_t cmd)
{
    SonyDWC3Endpoint *e = &s->ep[n];
    uint32_t p0 = REG(s, SDWC_PAR0(n)), p1 = REG(s, SDWC_PAR1(n));
    unsigned op = cmd & 15;
    int rc = 0;
    bool no_response_update = op == 7 && n >= 2 && e->configured &&
                              ((e->cfg0 >> 1) & 3) != 1 && !(cmd & SDWC_CMDIOC);
    if (!(cmd & SDWC_CMDACT) && !no_response_update) {
        return fail(s, "endpoint command without CMDACT", -EINVAL, SDWC_CMD(n));
    }
    if ((cmd & SDWC_CMDIOC) && event_space(s)) {
        return -EAGAIN;
    }
    switch (op) {
    case 1: /* SETEPCONFIG */
        if (((p1 >> 25) & 31) != n || (p1 & 31) ||
            (p1 & (1u << 24)) || ((p0 >> 1) & 3) == 1 ||
            !((p0 >> 3) & 0x7ff) || (n < 2 && ((p0 >> 1) & 3))) {
            rc = -EOPNOTSUPP; /* No ISO, streams or second event buffer. */
            break;
        }
        e->cfg0 = p0; e->cfg1 = p1; e->configured = true;
        break;
    case 2: /* SETTRANSFRESOURCE: one transfer resource per physical EP. */
        if (p0 != 1) { rc = -EOPNOTSUPP; break; }
        e->allocated = true;
        break;
    case 4: e->stalled = true; break;
    case 5: e->stalled = false; break;
    case 6: /* STARTTRANSFER: PAR1 low, PAR0 high (not DWC2 registers). */
        if (!e->configured || !e->allocated || e->active) {
            rc = -EBUSY; break;
        }
        e->trb = p1 | (uint64_t)p0 << 32;
        if ((e->trb & 15) || probe(s, e->trb, 16, false) ||
            probe(s, e->trb + 8, 8, true)) {
            rc = -EFAULT; break;
        }
        e->active = true; e->offset = 0; e->nrdy = false;
        e->resource = n + 1;
        break;
    case 7: /* UPDATETRANSFER */
        if (!e->active || ((cmd >> 16) & 127) != e->resource) {
            rc = -EINVAL;
        }
        e->nrdy = false;
        break;
    case 8: /* ENDTRANSFER */
        if (e->active && ((cmd >> 16) & 127) != e->resource) {
            rc = -EINVAL; break;
        }
        e->active = false; e->offset = 0; e->nrdy = false;
        for (unsigned i = 0; i < SDWC_MAX_URBS; i++) {
            SonyDWC3Pending *p = &s->pending[i];
            if (p->urb && (p->urb->endpoint ?
                p->urb->endpoint * 2u + p->urb->direction == n : n < 2)) {
                if (!p->urb->endpoint && p->phase) {
                    s->ep0_desynced = true;
                }
                finish(s, p, -ECONNRESET);
            }
        }
        break;
    case 9: /* DEPSTARTCFG: no hidden allocation or reset side effect. */
        if (n || ((cmd >> 16) & 127) > 2) { rc = -EOPNOTSUPP; }
        break;
    default: rc = -EOPNOTSUPP; break;
    }
    REG(s, SDWC_CMD(n)) = (cmd & ~(SDWC_CMDACT | (15u << 12) | (127u << 16))) |
                         (rc ? (1u << 12) : (uint32_t)e->resource << 16);
    if (cmd & SDWC_CMDIOC) {
        ep_event(s, n, EV_COMMAND, rc ? 1 : 0,
                 (op << 8) | e->resource);
    }
    if (rc) {
        return fail(s, "endpoint command rejected", rc, SDWC_CMD(n));
    }
    return 0;
}

static bool storage_register(uint32_t off)
{
    switch (off) {
    case 0xc100: case 0xc104: case 0xc108: case 0xc10c:
    case 0xc110: case 0xc11c: case 0xc124: case 0xc128: case 0xc12c:
    case 0xc19c: case 0xc200: case 0xc2c0: case 0xc60c: case 0xc630:
    case SDWC_DCFG: case SDWC_DEVTEN: case SDWC_DGCMDPAR: case SDWC_DALEPENA:
    case SDWC_LU1LFPSRXTIM0: /* Original core.c dwc3_set_prtcap U1 exit-clock RMW. */
        return true;
    default:
        return (off >= 0xc300 && off < 0xc340) || off == 0xc380;
    }
}

static bool capability_register(uint32_t off)
{
    return off == SDWC_HC_CAPBASE || off == SDWC_HC_HCSPARAMS1 ||
           off == SDWC_GSNPSID || (off >= SDWC_GHWPARAMS0 && off <= 0xc15c);
}

int sony_dwc3_read(SonyDWC3 *s, uint32_t off, unsigned size, uint32_t *value)
{
    if (!value) { return -EINVAL; }
    *value = UINT32_MAX;
    if ((size != 1 && size != 2 && size != 4) || (off & (size - 1)) ||
        off >= SDWC_MMIO_SIZE || size > SDWC_MMIO_SIZE - off) {
        return fail(s, "unsupported MMIO width/alignment", -EOPNOTSUPP, off);
    }
    if (capability_register(off & ~3u)) {
        uint32_t mask = UINT32_MAX >> ((4 - size) * 8);
        *value = (REG(s, off & ~3u) >> ((off & 3) * 8)) & mask;
        return 0;
    }
    /* Never widen a subword command/status access or perform a read-modify-write. */
    if (size != 4) {
        return fail(s, "subword access outside read-only capabilities", -EOPNOTSUPP, off);
    }
    if (off == SDWC_GEVNTCOUNT) {
        *value = s->event_count;
    } else if (storage_register(off) || off == SDWC_GSNPSID ||
               (off >= 0xc140 && off <= 0xc15c) || off == 0xc600 ||
               (off >= SDWC_GEVNTADRLO && off <= SDWC_GEVNTSIZ) ||
               off == SDWC_DCTL || off == SDWC_DSTS || off == SDWC_DGCMD ||
               (off >= SDWC_DEP(0) && off <= SDWC_CMD(31))) {
        *value = REG(s, off);
    } else {
        return fail(s, "unsupported MMIO read", -EOPNOTSUPP, off);
    }
    return 0;
}

int sony_dwc3_write(SonyDWC3 *s, uint32_t off, unsigned size, uint32_t val)
{
    int rc = 0;
    if (size != 4 || (off & 3) || off >= SDWC_MMIO_SIZE) {
        return fail(s, "unsupported MMIO width/alignment", -EOPNOTSUPP, off);
    }
    if (off == SDWC_GEVNTCOUNT) {
        uint32_t count = val & 0xfffc; /* EHB is not part of the byte count. */
        if ((val & 3) || count > s->event_count) {
            return fail(s, "event acknowledgement exceeds pending bytes", -EINVAL, off);
        }
        s->event_count -= count;
        irq_update(s);
    } else if (off >= SDWC_GEVNTADRLO && off <= SDWC_GEVNTSIZ) {
        if (s->event_count && (off != SDWC_GEVNTSIZ ||
            ((val ^ REG(s, off)) & ~SDWC_INTMASK))) {
            return fail(s, "event ring reprogrammed while pending", -EBUSY, off);
        }
        if (off == SDWC_GEVNTSIZ && ((val & 0xffff) & 3)) {
            return fail(s, "event ring size is unaligned", -EINVAL, off);
        }
        REG(s, off) = val;
        if (off != SDWC_GEVNTSIZ) { s->event_pos = 0; }
        irq_update(s);
    } else if (off == SDWC_DCTL) {
        if (val & SDWC_SOFTRST) {
            reset_core(s, SDWC_CAUSE_SOFTRST);
            return 0;
        }
        bool was_run = REG(s, SDWC_DCTL) & SDWC_RUN;
        REG(s, off) = val;
        if (val & SDWC_RUN) {
            REG(s, SDWC_DSTS) &= ~DSTS_HALT;
        }
        if (!(val & SDWC_RUN) && was_run) {
            s->cable_generation++;
            bool connected = s->connected;
            s->connected = false;
            unsigned drained = drain(s, -ESHUTDOWN);
            for (unsigned i = 0; i < SDWC_ENDPOINTS; i++) {
                s->ep[i].active = false;
            }
            REG(s, SDWC_DSTS) = DSTS_HALT;
            if (connected) { rc = dev_event(s, 0); }
            observe_generation(s, SDWC_CAUSE_RUNSTOP, s->cable_generation - 1, drained);
        }
    } else if (off >= SDWC_DEP(0) && off <= SDWC_CMD(31)) {
        if ((off & 15) == 12) {
            rc = command(s, (off - SDWC_DEP(0)) / 16, val);
        } else {
            REG(s, off) = val;
        }
    } else if (off == SDWC_DGCMD) {
        unsigned op = val & 0xff;
        if ((val & SDWC_CMDIOC) && (REG(s, SDWC_DEVTEN) & (1u << 10)) && event_space(s)) {
            return -EAGAIN;
        }
        /* No internal FIFO exists: bytes move only during a host token. */
        rc = ((val & SDWC_CMDACT) && (op == 9 || op == 10)) ? 0 : -EOPNOTSUPP;
        REG(s, off) = (val & ~(SDWC_CMDACT | (15u << 12))) | (rc ? 1u << 12 : 0);
        if (val & SDWC_CMDIOC) { dev_event(s, 10); }
        if (rc) { fail(s, "unsupported generic device command", rc, off); }
    } else if (storage_register(off)) {
        if (off == SDWC_GCTL && ((val >> 12) & 3) != 2) {
            return fail(s, "host/OTG mode outside device profile", -EOPNOTSUPP, off);
        }
        bool ep0_drop = off == SDWC_DALEPENA && (REG(s, off) & 3) == 3 && (val & 3) != 3;
        if (ep0_drop) { s->cable_generation++; }
        REG(s, off) = val;
        if (ep0_drop) {
            observe_generation(s, SDWC_CAUSE_EP0_DISABLE, s->cable_generation - 1, 0);
        }
    } else {
        return fail(s, "unsupported MMIO write", -EOPNOTSUPP, off);
    }
    if (!rc) {
        link_up(s);
        sony_dwc3_pump(s);
    }
    return rc;
}

#ifdef SONY_DWC3_QEMU
#include "hw/core/sysbus.h"
#include "hw/core/irq.h"
#include "qemu/log.h"
#include "qemu/module.h"
#include "system/address-spaces.h"
#include "qapi/error.h"
#include "migration/vmstate.h"
#include "hw/core/qdev-properties.h"
#include "sony-dwc3-bridge.h"

#define TYPE_SONY_DWC3 "sony-dwc3-gadget"
typedef struct SonyDWC3Qemu {
    SysBusDevice parent_obj;
    MemoryRegion mmio;
    qemu_irq irq, vbus_request;
    SonyDWC3 core;
    SonyDWC3Bridge *bridge;
    char *bridge_run_id, *bridge_lease, *bridge_qmp_host_path, *bridge_socket;
    bool generation_observe;
    unsigned generation_records, generation_log_bytes;
} SonyDWC3Qemu;

static void qemu_generation(void *opaque, const SonyDWC3Generation *g)
{
    SonyDWC3Qemu *q = opaque;
    if (q->generation_records >= 32 || q->generation_log_bytes >= 4096) { return; }
    SonyDWC3BridgeState b = {0};
    bool known = sony_dwc3_bridge_state(q->bridge, &b);
    char line[512];
    int n = snprintf(line, sizeof line,
        "SONY_DWC3_GEN cause=%u old=%" PRIu64 " new=%" PRIu64
        " run=%u conn=%u vb=%u de=%u ep=%x/%x/%x/%x ev=%" PRIx64 "/%x/%u"
        " pending=%u drained=%u bridge=%d/%d/%d/%d/%d/%d pre_invalidate=1\n",
        (unsigned)g->cause, g->old_generation, g->new_generation,
        !!(g->dctl & SDWC_RUN), g->connected, g->vbus, g->ep0_desynced,
        g->dalepena, g->configured, g->allocated, g->active,
        g->event_base, g->event_size, g->event_count, g->pending, g->drained,
        known ? (int)b.discovery_stage : -1, known ? (int)b.discovery_active : -1,
        known ? (int)b.discovery_done : -1, known ? (int)b.ready : -1,
        known ? (int)b.import_owner : -1, known ? (int)b.pending : -1);
    if (n < 0 || (size_t)n >= sizeof line || (unsigned)n > 4096 - q->generation_log_bytes) { return; }
    q->generation_records++; q->generation_log_bytes += (unsigned)n;
    qemu_log_mask(LOG_GUEST_ERROR, "%s", line);
}

static int qemu_probe(void *opaque, uint64_t addr, size_t n, bool wr)
{
    (void)opaque;
    while (n) {
        hwaddr translated, len = n;
        MemoryRegion *mr = address_space_translate(&address_space_memory, addr,
                                                   &translated, &len, wr,
                                                   MEMTXATTRS_UNSPECIFIED);
        if (!len || !memory_region_is_ram(mr) || memory_region_is_ram_device(mr) ||
            (wr && memory_region_is_rom(mr))) {
            return -EFAULT;
        }
        addr += len; n -= len;
    }
    return 0;
}

static int qemu_dma_read(void *opaque, uint64_t addr, void *data, size_t n)
{
    (void)opaque;
    return address_space_read(&address_space_memory, addr,
                              MEMTXATTRS_UNSPECIFIED, data, n) == MEMTX_OK ? 0 : -EFAULT;
}

static int qemu_dma_write(void *opaque, uint64_t addr, const void *data, size_t n)
{
    (void)opaque;
    return address_space_write(&address_space_memory, addr,
                               MEMTXATTRS_UNSPECIFIED, data, n) == MEMTX_OK ? 0 : -EFAULT;
}

static void qemu_level(void *opaque, bool level)
{
    SonyDWC3Qemu *q = opaque;
    qemu_set_irq(q->irq, level);
}

static void qemu_model_error(void *opaque, const char *what, int error, uint64_t addr)
{
    (void)opaque;
    qemu_log_mask(LOG_GUEST_ERROR, "SONY_DWC3 %s error=%d address=0x%" PRIx64 "\n",
                  what, error, addr);
}

static MemTxResult qemu_mmio_read(void *opaque, hwaddr off, uint64_t *data,
                                  unsigned size, MemTxAttrs attrs)
{
    SonyDWC3Qemu *q = opaque;
    uint32_t value;
    int rc = sony_dwc3_read(&q->core, off, size, &value);
    *data = value;
    qemu_log_mask(LOG_GUEST_ERROR, "SONY_DWC3_MMIO_READ address=0x%" HWADDR_PRIx
                  " size=%u value=0x%x rc=%d\n", (hwaddr)0xf10c0000 + off, size, value, rc);
    return rc ? MEMTX_ERROR : MEMTX_OK;
}

static MemTxResult qemu_mmio_write(void *opaque, hwaddr off, uint64_t data,
                                   unsigned size, MemTxAttrs attrs)
{
    SonyDWC3Qemu *q = opaque;
    int rc = sony_dwc3_write(&q->core, off, size, data);
    qemu_log_mask(LOG_GUEST_ERROR, "SONY_DWC3_MMIO_WRITE address=0x%" HWADDR_PRIx
                  " size=%u value=0x%" PRIx64 " rc=%d\n", (hwaddr)0xf10c0000 + off, size, data, rc);
    sony_dwc3_bridge_tick(q->bridge);
    return rc ? MEMTX_ERROR : MEMTX_OK;
}

static const MemoryRegionOps qemu_dwc3_ops = {
    .read_with_attrs = qemu_mmio_read,
    .write_with_attrs = qemu_mmio_write,
    .endianness = DEVICE_LITTLE_ENDIAN,
    .valid.min_access_size = 1, .valid.max_access_size = 4,
    .valid.unaligned = false,
    .impl.min_access_size = 1, .impl.max_access_size = 4,
    .impl.unaligned = false,
};

static void qemu_vbus(void *opaque, int n, int level)
{
    SonyDWC3Qemu *q = opaque;
    int rc = sony_dwc3_set_vbus(&q->core, level != 0);
    if (rc) { qemu_model_error(q, "VBUS controller transition blocked", rc, 0); }
    sony_dwc3_bridge_tick(q->bridge);
}

SonyDWC3 *sony_dwc3_qemu_core(void *qdev)
{
    SonyDWC3Qemu *q = OBJECT_CHECK(SonyDWC3Qemu, qdev, TYPE_SONY_DWC3);
    return &q->core;
}

static void qemu_dwc3_reset(DeviceState *dev)
{
    SonyDWC3Qemu *q = OBJECT_CHECK(SonyDWC3Qemu, dev, TYPE_SONY_DWC3);
    sony_dwc3_reset(&q->core);
    sony_dwc3_bridge_tick(q->bridge);
}

static void qemu_dwc3_init(Object *obj)
{
    SonyDWC3Qemu *q = OBJECT_CHECK(SonyDWC3Qemu, obj, TYPE_SONY_DWC3);
    const SonyDWC3Ops ops = {
        .probe = qemu_probe, .read = qemu_dma_read, .write = qemu_dma_write,
        .irq = qemu_level, .error = qemu_model_error,
    };
    sysbus_init_irq(SYS_BUS_DEVICE(obj), &q->irq);
    sony_dwc3_init(&q->core, &ops, q);
    memory_region_init_io(&q->mmio, obj, &qemu_dwc3_ops, q,
                          TYPE_SONY_DWC3, SDWC_MMIO_SIZE);
    sysbus_init_mmio(SYS_BUS_DEVICE(obj), &q->mmio);
    qdev_init_gpio_in_named(DEVICE(obj), qemu_vbus, "vbus", 1);
    qdev_init_gpio_out_named(DEVICE(obj), &q->vbus_request, "vbus-request", 1);
}

static int qemu_bridge_vbus(void *opaque, bool present)
{
    SonyDWC3Qemu *q = opaque;
    if (!qdev_get_gpio_out_connector(DEVICE(q), "vbus-request", 0)) {
        return -EOPNOTSUPP;
    }
    qemu_set_irq(q->vbus_request, present);
    return 0;
}

static void qemu_dwc3_realize(DeviceState *dev, Error **errp)
{
    SonyDWC3Qemu *q = OBJECT_CHECK(SonyDWC3Qemu, dev, TYPE_SONY_DWC3);
    q->core.ops.generation = q->generation_observe ? qemu_generation : NULL;
    if (!q->bridge_run_id && !q->bridge_lease && !q->bridge_qmp_host_path && !q->bridge_socket) {
        return;
    }
    SonyDWC3BridgeConfig config = {
        .run_id = q->bridge_run_id, .lease = q->bridge_lease,
        .qmp_host_path = q->bridge_qmp_host_path, .socket_path = q->bridge_socket,
    };
    q->bridge = sony_dwc3_bridge_new(&q->core, &config, qemu_bridge_vbus, q, errp);
}

static void qemu_dwc3_unrealize(DeviceState *dev)
{
    SonyDWC3Qemu *q = OBJECT_CHECK(SonyDWC3Qemu, dev, TYPE_SONY_DWC3);
    sony_dwc3_bridge_free(q->bridge); q->bridge = NULL;
}

static const Property qemu_dwc3_properties[] = {
    DEFINE_PROP_BOOL("generation-observe", SonyDWC3Qemu, generation_observe, false),
    DEFINE_PROP_STRING("bridge-run-id", SonyDWC3Qemu, bridge_run_id),
    DEFINE_PROP_STRING("bridge-lease", SonyDWC3Qemu, bridge_lease),
    DEFINE_PROP_STRING("bridge-qmp-host-path", SonyDWC3Qemu, bridge_qmp_host_path),
    DEFINE_PROP_STRING("bridge-socket", SonyDWC3Qemu, bridge_socket),
};

static const VMStateDescription qemu_dwc3_unmigratable = {
    .name = TYPE_SONY_DWC3, .unmigratable = 1,
};

static void qemu_dwc3_class_init(ObjectClass *klass, const void *data)
{
    DeviceClass *dc = DEVICE_CLASS(klass);
    dc->desc = "Virtual-functional DWC3 device (physical ASIC unverified)";
    device_class_set_legacy_reset(dc, qemu_dwc3_reset);
    dc->realize = qemu_dwc3_realize;
    dc->unrealize = qemu_dwc3_unrealize;
    device_class_set_props(dc, qemu_dwc3_properties);
    /* Live host URBs and the bridge owner cannot migrate. */
    dc->user_creatable = false;
    dc->vmsd = &qemu_dwc3_unmigratable;
}

static const TypeInfo qemu_dwc3_type = {
    .name = TYPE_SONY_DWC3,
    .parent = TYPE_SYS_BUS_DEVICE,
    .instance_size = sizeof(SonyDWC3Qemu),
    .instance_init = qemu_dwc3_init,
    .class_init = qemu_dwc3_class_init,
};

static void sony_dwc3_register_types(void)
{
    type_register_static(&qemu_dwc3_type);
}
type_init(sony_dwc3_register_types)
#endif
