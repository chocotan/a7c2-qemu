/* SPDX-License-Identifier: GPL-2.0-or-later */
#include "qemu/osdep.h"
#include "qemu/log.h"
#include "qemu/module.h"
#include "hw/i2c/i2c.h"
#include "hw/core/irq.h"
#include "beets-core.h"
#include "beets-qemu.h"

OBJECT_DECLARE_SIMPLE_TYPE(SonyBeetsState, SONY_BEETS)
struct SonyBeetsState {
    I2CSlave parent_obj;
    BeetsCore core;
    qemu_irq event[2];
};

static void update(SonyBeetsState *s)
{
    qemu_set_irq(s->event[0], s->core.primary);
    qemu_set_irq(s->event[1], s->core.secondary);
}

static int result(SonyBeetsState *s, int rc)
{
    if (rc) qemu_log_mask(LOG_GUEST_ERROR,
        "SONY_BEETS reject register=0x%04x cursor=%u reason=%s\n",
        s->core.address, s->core.cursor, s->core.error ? s->core.error : "unknown");
    update(s);
    return rc;
}

static int event(I2CSlave *dev, enum i2c_event ev)
{
    SonyBeetsState *s = SONY_BEETS(dev);
    switch (ev) {
    case I2C_START_SEND: return result(s, beets_start_write(&s->core));
    case I2C_START_RECV: return result(s, beets_start_read(&s->core));
    case I2C_FINISH: beets_finish(&s->core); return result(s, s->core.failed ? -1 : 0);
    case I2C_NACK: return 0; /* Master terminates read; STOP follows. */
    case I2C_START_SEND_ASYNC: break;
    }
    s->core.failed = true;
    s->core.error = "unsupported I2C event";
    return result(s, -1);
}

static int send(I2CSlave *dev, uint8_t byte)
{
    SonyBeetsState *s = SONY_BEETS(dev);
    return result(s, beets_send(&s->core, byte));
}

static uint8_t recv(I2CSlave *dev)
{
    SonyBeetsState *s = SONY_BEETS(dev);
    uint8_t byte = beets_recv(&s->core);
    result(s, s->core.failed ? -1 : 0);
    return byte;
}

static void enable(void *opaque, int line, int level)
{
    SonyBeetsState *s = opaque;
    beets_enable(&s->core, level != 0);
    update(s);
}

static void reset_line(void *opaque, int line, int level)
{
    SonyBeetsState *s = opaque;
    beets_reset_line(&s->core, level != 0);
    if (!level && s->core.reset_seen)
        qemu_log_mask(LOG_GUEST_ERROR,
            "SONY_BEETS reset pulse released; Reset Complete wire payload/mode evidence missing; no completion fabricated\n");
    update(s);
}

int sony_beets_reset_complete(DeviceState *dev, const uint8_t reply[2], uint8_t mode)
{
    SonyBeetsState *s = SONY_BEETS(dev);
    return result(s, beets_complete_reset(&s->core, reply, mode));
}

int sony_beets_port_response(DeviceState *dev, const uint8_t reply[4])
{
    SonyBeetsState *s = SONY_BEETS(dev);
    return result(s, beets_port_event(&s->core, reply));
}

static void reset(DeviceState *dev)
{
    SonyBeetsState *s = SONY_BEETS(dev);
    beets_init(&s->core);
    update(s);
}

static void init(Object *obj)
{
    DeviceState *dev = DEVICE(obj);
    qdev_init_gpio_out_named(dev, SONY_BEETS(obj)->event, "event", 2);
    qdev_init_gpio_in_named(dev, enable, "enable", 1);
    qdev_init_gpio_in_named(dev, reset_line, "reset", 1);
}

static void class_init(ObjectClass *klass, const void *data)
{
    DeviceClass *dc = DEVICE_CLASS(klass);
    I2CSlaveClass *ic = I2C_SLAVE_CLASS(klass);
    ic->event = event;
    ic->send = send;
    ic->recv = recv;
    dc->desc = "Source-only Beets register subset; command encoding unverified";
    dc->user_creatable = false;
    device_class_set_legacy_reset(dc, reset);
}

static const TypeInfo info = {
    .name = TYPE_SONY_BEETS,
    .parent = TYPE_I2C_SLAVE,
    .instance_size = sizeof(SonyBeetsState),
    .instance_init = init,
    .class_init = class_init,
};
static void register_types(void) { type_register_static(&info); }
type_init(register_types)
