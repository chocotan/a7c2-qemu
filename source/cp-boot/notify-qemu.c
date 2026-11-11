/* SPDX-License-Identifier: GPL-2.0-or-later
 * Functional AP/CP GPIO lines. Snapshots come only from the other device's
 * output latch; disconnected or malformed peers never provide input values.
 * AP exposes two GPIO IRQ outputs; CP IRQ, PCIe ready and UIPC ACK remain absent.
 * The cross-chip line pairing is a declared functional profile, not physical wiring.
 */
#include "qemu/osdep.h"
#include "qemu/bswap.h"
#include "qemu/module.h"
#include "hw/core/sysbus.h"
#include "hw/core/irq.h"
#include "hw/core/qdev-properties.h"
#include "hw/core/qdev-properties-system.h"
#include "chardev/char-fe.h"
#include "qapi/error.h"
#include "notify.h"

#define TYPE_NOTIFY_DEVICE "a7c2-ap-cp-gpio-lines"
#define AP_MAGIC 0x31475041u
#define CP_MAGIC 0x31475043u
OBJECT_DECLARE_SIMPLE_TYPE(NotifyDevice, NOTIFY_DEVICE)
struct NotifyRegion { NotifyDevice *owner; unsigned port; };
struct NotifyDevice {
    SysBusDevice parent_obj;
    MemoryRegion regs[2];
    struct NotifyRegion contexts[2];
    struct notify_gpio gpio;
    qemu_irq irq[2];
    CharFrontend chr;
    char *side;
    uint8_t incoming[16];
    unsigned used, logged;
    uint64_t tx_seq, rx_seq;
    uint32_t sent_known, sent_levels;
    bool opened, failed, sent;
};

static void log_access(NotifyDevice *s, const char *op, unsigned port,
                       hwaddr offset, uint32_t value, int result)
{
    if (s->logged++ < 96) {
        fprintf(stderr, "AP_CP_GPIO side=%s op=%s port=%u offset=0x%" HWADDR_PRIx
                " value=0x%x result=%d physical_compatible=0\n",
                s->side, op, port, offset, value, result);
    }
}
static void update_ap_irq(NotifyDevice *s)
{
    for (unsigned channel = 0; channel < 2; channel++) {
        uint32_t pin = channel ? 8 : 16;
        bool driven = s->gpio.side == NOTIFY_AP && s->gpio.peer_valid &&
            (s->gpio.peer_known & (1u << channel)) &&
            (s->gpio.bank17.inen & pin) && !(s->gpio.bank17.dir & pin);
        qemu_set_irq(s->irq[channel], driven && (s->gpio.peer_levels & (1u << channel)));
    }
}
static void fail_peer(NotifyDevice *s, const char *reason)
{
    s->failed = true;
    notify_disconnect(&s->gpio);
    update_ap_irq(s);
    log_access(s, reason, 0, 0, 0, -1);
}
static void send_snapshot(NotifyDevice *s, bool force)
{
    uint32_t known, levels;
    uint8_t frame[16];
    if (!s->opened || s->failed) {
        return;
    }
    if (notify_output(&s->gpio, &known, &levels)) {
        fail_peer(s, "output-invalid");
        return;
    }
    if (!force && s->sent && known == s->sent_known && levels == s->sent_levels) {
        return;
    }
    if (s->tx_seq > UINT32_MAX) {
        fail_peer(s, "sequence-exhausted");
        return;
    }
    stl_le_p(frame, s->gpio.side == NOTIFY_AP ? AP_MAGIC : CP_MAGIC);
    stl_le_p(frame + 4, (uint32_t)s->tx_seq);
    stl_le_p(frame + 8, known);
    stl_le_p(frame + 12, levels);
    if (qemu_chr_fe_write(&s->chr, frame, sizeof(frame)) != (int)sizeof(frame)) {
        fail_peer(s, "short-output-frame");
        return;
    }
    s->tx_seq++;
    s->sent = true;
    s->sent_known = known;
    s->sent_levels = levels;
    log_access(s, "send", 18, known, levels, 0);
}
static int can_receive(void *opaque)
{
    NotifyDevice *s = opaque;
    return s->failed ? 0 : sizeof(s->incoming) - s->used;
}
static void receive_frame(void *opaque, const uint8_t *data, int size)
{
    NotifyDevice *s = opaque;
    if (s->failed || !s->opened || size < 0 || (unsigned)size > sizeof(s->incoming) - s->used) {
        fail_peer(s, "invalid-frame-length");
        return;
    }
    memcpy(s->incoming + s->used, data, size);
    s->used += size;
    if (s->used == sizeof(s->incoming)) {
        uint32_t magic = s->gpio.side == NOTIFY_AP ? CP_MAGIC : AP_MAGIC;
        uint32_t known = ldl_le_p(s->incoming + 8);
        uint32_t levels = ldl_le_p(s->incoming + 12);
        if (ldl_le_p(s->incoming) != magic ||
            s->rx_seq > UINT32_MAX || ldl_le_p(s->incoming + 4) != s->rx_seq ||
            notify_peer(&s->gpio, known, levels)) {
            fail_peer(s, "invalid-peer-frame");
            return;
        }
        s->rx_seq++;
        s->used = 0;
        update_ap_irq(s);
        log_access(s, "receive", 17, known, levels, 0);
    }
}
static void notify_event(void *opaque, QEMUChrEvent event)
{
    NotifyDevice *s = opaque;
    if (event == CHR_EVENT_OPENED || event == CHR_EVENT_CLOSED) {
        s->opened = event == CHR_EVENT_OPENED;
        s->used = 0;
        s->tx_seq = s->rx_seq = 0;
        s->failed = s->sent = false;
        notify_disconnect(&s->gpio);
        update_ap_irq(s);
        log_access(s, s->opened ? "connected" : "disconnected", 0, 0, 0, 0);
        if (s->opened) {
            send_snapshot(s, true);
        }
    }
}
static MemTxResult notify_mmio_read(void *opaque, hwaddr offset,
                                    uint64_t *value, unsigned size, MemTxAttrs attrs)
{
    struct NotifyRegion *region = opaque;
    NotifyDevice *s = region->owner;
    uint32_t data = 0;
    int rc = size == 4 ? notify_read(&s->gpio, region->port, offset, &data) : -1;
    log_access(s, "read", region->port, offset, data, rc);
    if (rc) {
        return MEMTX_ERROR;
    }
    *value = data;
    return MEMTX_OK;
}
static MemTxResult notify_mmio_write(void *opaque, hwaddr offset,
                                     uint64_t value, unsigned size, MemTxAttrs attrs)
{
    struct NotifyRegion *region = opaque;
    NotifyDevice *s = region->owner;
    int rc = size == 4 && value <= UINT32_MAX ?
        notify_write(&s->gpio, region->port, offset, value) : -1;
    log_access(s, "write", region->port, offset, value, rc);
    if (!rc) {
        update_ap_irq(s);
        if (region->port == 18) {
            send_snapshot(s, false);
        }
    }
    return rc ? MEMTX_ERROR : MEMTX_OK;
}
static const MemoryRegionOps notify_ops = {
    .read_with_attrs = notify_mmio_read, .write_with_attrs = notify_mmio_write,
    .endianness = DEVICE_LITTLE_ENDIAN,
    .valid = { .min_access_size = 4, .max_access_size = 4, .unaligned = false },
    .impl = { .min_access_size = 4, .max_access_size = 4 },
};
static void notify_device_reset(DeviceState *dev)
{
    NotifyDevice *s = NOTIFY_DEVICE(dev);
    if (notify_reset(&s->gpio)) {
        fail_peer(s, "invalid-reset");
        return;
    }
    update_ap_irq(s);
    send_snapshot(s, true);
}
static void notify_realize(DeviceState *dev, Error **errp)
{
    NotifyDevice *s = NOTIFY_DEVICE(dev);
    enum notify_side side;
    if (s->side && !strcmp(s->side, "ap")) {
        side = NOTIFY_AP;
    } else if (s->side && !strcmp(s->side, "cp")) {
        side = NOTIFY_CP;
    } else {
        error_setg(errp, "GPIO lines require explicit side=ap or side=cp");
        return;
    }
    if (!qemu_chr_fe_backend_connected(&s->chr) || notify_init(&s->gpio, side)) {
        error_setg(errp, "GPIO lines require a dedicated peer chardev and valid side");
        return;
    }
    for (unsigned i = 0; i < 2; i++) {
        s->contexts[i].owner = s;
        s->contexts[i].port = 17 + i;
        memory_region_init_io(&s->regs[i], OBJECT(dev), &notify_ops, &s->contexts[i],
                              i ? "notify-gpio18" : "notify-gpio17", 0x1000);
        sysbus_init_mmio(SYS_BUS_DEVICE(dev), &s->regs[i]);
        sysbus_init_irq(SYS_BUS_DEVICE(dev), &s->irq[i]);
    }
    qemu_chr_fe_set_handlers(&s->chr, can_receive, receive_frame, notify_event,
                             NULL, s, NULL, true);
}
static void notify_unrealize(DeviceState *dev)
{
    NotifyDevice *s = NOTIFY_DEVICE(dev);
    qemu_chr_fe_set_handlers(&s->chr, NULL, NULL, NULL, NULL, NULL, NULL, false);
    notify_disconnect(&s->gpio);
    update_ap_irq(s);
}
static const Property notify_properties[] = {
    DEFINE_PROP_STRING("side", NotifyDevice, side),
    DEFINE_PROP_CHR("chardev", NotifyDevice, chr),
};
static void notify_class_init(ObjectClass *klass, const void *data)
{
    DeviceClass *dc = DEVICE_CLASS(klass);
    dc->realize = notify_realize;
    dc->unrealize = notify_unrealize;
    device_class_set_legacy_reset(dc, notify_device_reset);
    device_class_set_props(dc, notify_properties);
    dc->desc = "Functional AP/CP GPIO lines with AP GPIO IRQ outputs; no CP IRQ or PCIe completion";
}
/* shortcut: no VMState; add a paired transport/state contract before RAM restore. */
static const TypeInfo notify_type = {
    .name = TYPE_NOTIFY_DEVICE, .parent = TYPE_SYS_BUS_DEVICE,
    .instance_size = sizeof(NotifyDevice), .class_init = notify_class_init,
};
static void notify_register_types(void) { type_register_static(&notify_type); }
type_init(notify_register_types)
