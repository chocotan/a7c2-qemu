/* SPDX-License-Identifier: MIT
 * Virtual-functional DWC3 USB2 device profile. Physical ASIC unverified.
 * Register/TRB/event layout: Sony 4.9 drivers/usb/dwc3/{core,gadget}.h.
 * No descriptor, Sony protocol, USB/IP or authentication implementation.
 */
#ifndef SONY_DWC3_H
#define SONY_DWC3_H
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#define SONY_DWC3_PROFILE "virtual-functional-dwc3-device-v1"
#define SDWC_MMIO_SIZE 0x10000u
#define SDWC_ENDPOINTS 32u
#define SDWC_MAX_URBS 32u
#define SDWC_MAX_BYTES (8u * 1024u * 1024u)
#define SDWC_MAX_URB (1024u * 1024u)
#define SDWC_HC_CAPBASE 0x0000u
#define SDWC_HC_HCSPARAMS1 0x0004u
#define SDWC_GCTL 0xc110u
#define SDWC_GSNPSID 0xc120u
#define SDWC_GHWPARAMS0 0xc140u
#define SDWC_GEVNTADRLO 0xc400u
#define SDWC_GEVNTADRHI 0xc404u
#define SDWC_GEVNTSIZ 0xc408u
#define SDWC_GEVNTCOUNT 0xc40cu
#define SDWC_DCFG 0xc700u
#define SDWC_DCTL 0xc704u
#define SDWC_DEVTEN 0xc708u
#define SDWC_DSTS 0xc70cu
#define SDWC_DGCMDPAR 0xc710u
#define SDWC_DGCMD 0xc714u
#define SDWC_DALEPENA 0xc720u
#define SDWC_LU1LFPSRXTIM0 0xd000u
#define SDWC_DEP(n) (0xc800u + 16u * (n))
#define SDWC_PAR2(n) (SDWC_DEP(n) + 0u)
#define SDWC_PAR1(n) (SDWC_DEP(n) + 4u)
#define SDWC_PAR0(n) (SDWC_DEP(n) + 8u)
#define SDWC_CMD(n) (SDWC_DEP(n) + 12u)
#define SDWC_RUN (1u << 31)
#define SDWC_SOFTRST (1u << 30)
#define SDWC_INTMASK (1u << 31)
#define SDWC_CMDACT (1u << 10)
#define SDWC_CMDIOC (1u << 8)
#define SDWC_CFG_COMPLETE (1u << 8)
#define SDWC_CFG_PROGRESS (1u << 9)
#define SDWC_CFG_NOTREADY (1u << 10)
#define SDWC_HWO 1u
#define SDWC_LST 2u
#define SDWC_CHN 4u
#define SDWC_CSP 8u
#define SDWC_ISP (1u << 10)
#define SDWC_IOC (1u << 11)
#define SDWC_TRB_TYPE(t) ((t) << 4)
#define SDWC_TRB_NORMAL 1u
#define SDWC_TRB_SETUP 2u
#define SDWC_TRB_STATUS2 3u
#define SDWC_TRB_STATUS3 4u
#define SDWC_TRB_DATA 5u
#define SDWC_TRB_LINK 8u
#define SDWC_SIZE_MASK 0xffffffu

typedef struct SonyDWC3Urb SonyDWC3Urb;
/* DMA callbacks return zero or a negative errno. Probe MUST reject non-RAM,
 * wrapping addresses and writes to ROM. A successful probe must not do DMA.
 * All entry points run on one serialized owner thread (QEMU BQL).
 */
typedef enum SonyDWC3GenerationCause {
    SDWC_CAUSE_RESET, SDWC_CAUSE_VBUS, SDWC_CAUSE_RUNSTOP,
    SDWC_CAUSE_SOFTRST, SDWC_CAUSE_EP0_DISABLE
} SonyDWC3GenerationCause;
/* Post-transition state only; no readiness/DMA probe is performed to collect it. */
typedef struct SonyDWC3Generation {
    uint64_t old_generation, new_generation, event_base;
    uint32_t dctl, dalepena, configured, allocated, active;
    uint32_t event_size, event_count, pending, drained;
    bool vbus, connected, ep0_desynced;
    SonyDWC3GenerationCause cause;
} SonyDWC3Generation;

typedef struct SonyDWC3Ops {
    int (*probe)(void *, uint64_t, size_t, bool write);
    int (*read)(void *, uint64_t, void *, size_t);
    int (*write)(void *, uint64_t, const void *, size_t);
    void (*irq)(void *, bool level);
    void (*error)(void *, const char *what, int error, uint64_t address);
    /* Optional passive callback, NULL by default. Must not mutate/reenter core. */
    void (*generation)(void *, const SonyDWC3Generation *);
} SonyDWC3Ops;

struct SonyDWC3Urb {
    uint64_t id;                 /* Unique among live requests. */
    uint8_t endpoint;            /* USB logical EP, 0..15. */
    uint8_t direction;           /* USB/IP: 0 OUT, 1 IN. */
    uint8_t setup[8];            /* Exact wire SETUP for EP0. */
    uint32_t flags;              /* SHORT_NOT_OK=1, ZERO_PACKET=0x40. */
    uint32_t length;
    uint8_t *data;               /* Caller-owned buffer of at least length. */
    void (*complete)(void *, SonyDWC3Urb *, int status, uint32_t actual);
    void *opaque;
};

typedef struct SonyDWC3Endpoint {
    uint64_t trb;
    uint32_t offset;
    uint32_t cfg0, cfg1;
    uint8_t resource;
    bool configured, allocated, active, stalled, nrdy;
} SonyDWC3Endpoint;

typedef struct SonyDWC3Pending {
    SonyDWC3Urb *urb;
    uint32_t actual;
    uint64_t order;
    uint8_t phase;              /* 0 setup, 1 data, 2 status. */
    bool notified, short_packet, zlp_pending;
} SonyDWC3Pending;

typedef struct SonyDWC3 {
    SonyDWC3Ops ops;
    void *opaque;
    uint32_t regs[SDWC_MMIO_SIZE / 4];
    SonyDWC3Endpoint ep[SDWC_ENDPOINTS];
    SonyDWC3Pending pending[SDWC_MAX_URBS];
    uint32_t event_pos, event_count, reserved_bytes;
    uint64_t dma_bytes, events_written, unsupported, dma_errors, next_order;
    uint64_t cable_generation;  /* Reset, VBUS transition or guest pull-up drop. */
    int last_error;
    bool vbus, connected, ep0_desynced, pumping, irq_level, resetting;
} SonyDWC3;

void sony_dwc3_init(SonyDWC3 *, const SonyDWC3Ops *, void *opaque);
void sony_dwc3_reset(SonyDWC3 *);
/* Full core-window offsets, not offsets relative to globals at 0xc100.
 * Naturally aligned 1/2/4-byte reads are allowed only for read-only HC metadata,
 * GSNPSID and GHWPARAMS. Other reads and all writes require aligned 4-byte access.
 * HC metadata does not implement host registers/ports or make the gadget ready.
 * Unknown MMIO and commands return -EOPNOTSUPP; read value is UINT32_MAX.
 */
int sony_dwc3_read(SonyDWC3 *, uint32_t offset, unsigned size, uint32_t *value);
int sony_dwc3_write(SonyDWC3 *, uint32_t offset, unsigned size, uint32_t value);
/* Transport-ready only. A bridge must additionally discover and validate both
 * device/configuration descriptors through ordinary EP0 submits before export.
 */
bool sony_dwc3_ready(SonyDWC3 *);
int sony_dwc3_set_vbus(SonyDWC3 *, bool present);
int sony_dwc3_bus_reset(SonyDWC3 *);
/* Accepted=0, including synchronous completion; failure<0 retains no ownership.
 * On acceptance the caller retains buffer/URB storage until complete/cancel.
 * No transfer/HWO means pending, never a fabricated successful zero length.
 */
int sony_dwc3_submit(SonyDWC3 *, SonyDWC3Urb *);
int sony_dwc3_cancel(SonyDWC3 *, uint64_t id);
void sony_dwc3_pump(SonyDWC3 *);
/* QEMU glue exports this getter for the per-run endpoint bridge. Use only on
 * the model's qdev, with BQL held. Optional bridge-* qdev string properties
 * enable a per-run endpoint listener; absent properties create no listener.
 * The bridge never opens a host/physical USB device.
 * qdev type: sony-dwc3-gadget; MMIO[0]=64KiB; IRQ[0]=event ring;
 * GPIO input "vbus"[0] applies the controller-side cable signal. The board
 * must also drive the original Sony extcon/VBUS path, not AP state.
 */
SonyDWC3 *sony_dwc3_qemu_core(void *qdev);
#endif
