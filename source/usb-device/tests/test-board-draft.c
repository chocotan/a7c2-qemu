/* SPDX-License-Identifier: GPL-2.0-or-later */
/* DRAFT, NOT BUILT OR RUN. Future system-linked QEMU unit, no guest/real device.
 * Compile against candidate-staged hw/arm/sony-usb-device-platform.inc and link
 * real DW-I2C, Beets, SCU and QEMU reset/qdev implementations. No model mocks.
 * Meson registration in an independent build tree remains a future task. */
#include "qemu/osdep.h"
#include "qemu/error-report.h"
#include "qemu/log.h"
#include "qemu/main-loop.h"
#include "qemu/module.h"
#include "qapi/error.h"
#include "hw/core/qdev.h"
#include "hw/core/sysbus.h"
#include "system/reset.h"
#include "hw/arm/sony-usb-device-platform.inc"

#define TYPE_TEST_SINK "buspower-test-irq-sink"
typedef struct TestSink {
    DeviceState parent_obj;
    unsigned rises[256];
    bool levels[256];
    qemu_irq request;
} TestSink;

static void sink_irq(void *opaque, int n, int level)
{
    TestSink *s = opaque;
    if (level && !s->levels[n]) s->rises[n]++;
    s->levels[n] = level != 0;
}

static void sink_init(Object *obj)
{
    TestSink *s = (TestSink *)obj;
    qdev_init_gpio_in(DEVICE(obj), sink_irq, 256);
    qdev_init_gpio_in_named(DEVICE(obj), sink_irq, "vbus", 1);
    qdev_init_gpio_out_named(DEVICE(obj), &s->request, "vbus-request", 1);
}

static const TypeInfo sink_type = {
    .name = TYPE_TEST_SINK,
    .parent = TYPE_DEVICE,
    .instance_size = sizeof(TestSink),
    .instance_init = sink_init,
};

static void bp_write(SonyBusPower *p, unsigned region, hwaddr off, uint32_t v)
{
    g_assert_cmpint(sony_buspower_write(&p->regions[region], off, v, 4,
                                      MEMTXATTRS_UNSPECIFIED), ==, MEMTX_OK);
}

static uint32_t bp_read(SonyBusPower *p, unsigned region, hwaddr off)
{
    uint64_t v;
    g_assert_cmpint(sony_buspower_read(&p->regions[region], off, &v, 4,
                                     MEMTXATTRS_UNSPECIFIED), ==, MEMTX_OK);
    return v;
}

static void gpio_write(SonyUsbPlatform *p, hwaddr off, uint32_t v)
{
    g_assert_cmpint(sony_usb_gpio_write(p, off, v, 4, MEMTXATTRS_UNSPECIFIED),
                   ==, MEMTX_OK);
}

static void int_write(SonyUsbPlatform *p, hwaddr off, uint32_t v)
{
    g_assert_cmpint(sony_usb_int_write(p, off, v, 4, MEMTXATTRS_UNSPECIFIED),
                   ==, MEMTX_OK);
}

static void slave_read(I2CBus *bus, uint16_t reg, uint8_t *out, unsigned length)
{
    g_assert_cmpint(i2c_start_transfer(bus, 8, false), ==, 0);
    g_assert_cmpint(i2c_send(bus, reg & 0xff), ==, 0);
    g_assert_cmpint(i2c_send(bus, reg >> 8), ==, 0);
    g_assert_cmpint(i2c_start_transfer(bus, 8, true), ==, 0);
    for (unsigned i = 0; i < length; i++) out[i] = i2c_recv(bus);
    i2c_nack(bus);
    i2c_end_transfer(bus);
}

static void pending_clear(I2CBus *bus, uint8_t mask)
{
    g_assert_cmpint(i2c_start_transfer(bus, 8, false), ==, 0);
    g_assert_cmpint(i2c_send(bus, 6), ==, 0);
    g_assert_cmpint(i2c_send(bus, 0), ==, 0);
    g_assert_cmpint(i2c_send(bus, mask), ==, 0);
    i2c_end_transfer(bus);
}

static void ready(SonyUsbPlatform *p)
{
    const uint8_t reply[2] = {0x59, 0xa6}; /* Synthetic, not a wire command. */
    gpio_write(p, 0x04, 1u << 13);
    gpio_write(p, 0x44, 1u << 13);
    bp_write(p->buspower, 3, 0x44, 1u << 7); /* Baseline before DIR. */
    bp_write(p->buspower, 3, 0x04, 1u << 7);
    bp_write(p->buspower, 3, 0x48, 1u << 7);
    bp_write(p->buspower, 3, 0x44, 1u << 7);
    g_assert_cmpint(sony_beets_reset_complete(p->buspower->beets, reply, 2), ==, 0);
}

static void assert_ready(SonyBusPower *p)
{
    uint8_t mode, pending, reply[2];
    I2CBus *bus = DESIGNWARE_I2C(p->dw)->bus;
    slave_read(bus, 0, &mode, 1);
    slave_read(bus, 6, &pending, 1);
    slave_read(bus, 0x7e, reply, 2);
    g_assert_cmpuint(mode & 3, ==, 2);
    g_assert_cmpuint(pending, ==, 1);
    g_assert_cmpuint(reply[0], ==, 0x59);
    g_assert_cmpuint(reply[1], ==, 0xa6);
}

static void master_reset_test(SonyUsbPlatform *p, TestSink *sink)
{
    SonyBusPower *bp = p->buspower;
    DesignWareI2CState *dw = DESIGNWARE_I2C(bp->dw);
    uint64_t rejected;
    ready(p);
    bp_write(bp, 1, 4, SONY_BUSPOWER_I2C_CLOCK);
    bp_write(bp, 0, 0x00, 0x65); /* master, restart, slave disabled. */
    bp_write(bp, 0, 0x04, 8);
    bp_write(bp, 0, 0x30, 1u << 2); /* RX_FULL IRQ. */
    bp_write(bp, 0, 0x6c, 1);
    bp_write(bp, 0, 0x10, 0);
    bp_write(bp, 0, 0x10, 0);
    bp_write(bp, 0, 0x10, 0x500); /* Repeated START read, no STOP. */
    g_assert_cmpuint(fifo8_num_used(&dw->rx_fifo), ==, 1);
    g_assert_true(i2c_bus_busy(dw->bus));
    g_assert_true(bp->raw_irq);
    g_assert_true(sink->levels[216]);
    bp_write(bp, 2, 4, SONY_BUSPOWER_I2C_RESET);
    g_assert_cmpuint(dw->status, ==, DW_I2C_STATUS_IDLE);
    g_assert_cmpuint(fifo8_num_used(&dw->rx_fifo), ==, 0);
    g_assert_false(i2c_bus_busy(dw->bus));
    g_assert_cmpuint(dw->regs[0x6c / 4], ==, 0);
    g_assert_false(bp->raw_irq);
    g_assert_false(sink->levels[216]);
    g_assert_cmpint(sony_buspower_read(&bp->regions[0], 0x6c, &rejected, 4,
                                     MEMTXATTRS_UNSPECIFIED), ==, MEMTX_ERROR);
    assert_ready(bp); /* Must preserve slave even while master reset is asserted. */
    bp_write(bp, 2, 4, SONY_BUSPOWER_I2C_RESET); /* Repeated assert. */
    bp_write(bp, 2, 8, SONY_BUSPOWER_I2C_RESET);
    assert_ready(bp);
    g_assert_cmpuint(bp_read(bp, 0, 0x6c), ==, 0);
}

static void edge_test(SonyUsbPlatform *p, TestSink *sink)
{
    I2CBus *bus = DESIGNWARE_I2C(p->buspower->dw)->bus;
    const uint32_t pins = (1u << 15) | (1u << 11);
    const uint8_t port[4] = {0x19, 0x28, 0x37, 0x46};
    pending_clear(bus, 3);
    gpio_write(p, 0x28, pins); /* Disable INEN. */
    int_write(p, 0x24, pins); /* Rising enabled; no synthetic edge from config. */
    unsigned a = sink->rises[71], b = sink->rises[67];
    g_assert_cmpint(sony_beets_port_response(p->buspower->beets, port), ==, 0);
    g_assert_cmpuint(sink->rises[71], ==, a);
    g_assert_cmpuint(sink->rises[67], ==, b);
    gpio_write(p, 0x24, pins); /* Already high remains silent. */
    g_assert_cmpuint(sink->rises[71], ==, a);
    pending_clear(bus, 2); /* Falling edges remain silent. */
    g_assert_cmpint(sony_beets_port_response(p->buspower->beets, port), ==, 0);
    g_assert_cmpuint(sink->rises[71], ==, ++a);
    g_assert_cmpuint(sink->rises[67], ==, ++b);
    sony_usb_beets_event(p, 0, 1); /* Held high is not a second IRQ. */
    sony_usb_beets_event(p, 1, 1);
    g_assert_cmpuint(sink->rises[71], ==, a);
    g_assert_cmpuint(sink->rises[67], ==, b);
    pending_clear(bus, 2);
    int_write(p, 0x14, pins); /* Mask. */
    g_assert_cmpint(sony_beets_port_response(p->buspower->beets, port), ==, 0);
    int_write(p, 0x18, pins); /* Unmask while high cannot generate an edge. */
    g_assert_cmpuint(sink->rises[71], ==, a);
    g_assert_cmpuint(sink->rises[67], ==, b);
    pending_clear(bus, 2);
    gpio_write(p, 0x04, pins); /* Output direction suppresses edge IRQs. */
    g_assert_cmpint(sony_beets_port_response(p->buspower->beets, port), ==, 0);
    gpio_write(p, 0x08, pins);
    g_assert_cmpuint(sink->rises[71], ==, a);
    g_assert_cmpuint(sink->rises[67], ==, b);
    pending_clear(bus, 2);
    int_write(p, 0x28, pins); /* No rising enable. */
    g_assert_cmpint(sony_beets_port_response(p->buspower->beets, port), ==, 0);
    g_assert_cmpuint(sink->rises[71], ==, a);
    g_assert_cmpuint(sink->rises[67], ==, b);
}

static void system_defaults(SonyUsbPlatform *p, TestSink *sink)
{
    SonyBusPower *bp = p->buspower;
    const uint32_t pins = (1u << 11) | (1u << 13) | (1u << 15);
    g_assert_cmpuint(bp_read(bp, 1, 0), ==, 0);
    g_assert_cmpuint(bp_read(bp, 2, 0), ==, 0);
    for (unsigned off = 0; off <= 0x40; off += 0x10)
        g_assert_cmpuint(bp_read(bp, 3, off), ==, 0);
    for (unsigned i = 0; i < ARRAY_SIZE(bp->gpio0); i++)
        g_assert_cmpuint(bp->gpio0[i], ==, 0);
    g_assert_false(bp->reset_tracking);
    g_assert_false(bp->reset_baseline);
    g_assert_false(bp->reset_departed);
    g_assert_false(bp->raw_irq);
    g_assert_false(p->beets_primary);
    g_assert_false(p->beets_secondary);
    for (unsigned i = 0; i < ARRAY_SIZE(p->gpio_regs); i++)
        g_assert_cmpuint(p->gpio_regs[i] & pins, ==, 0);
    for (unsigned i = 0; i < ARRAY_SIZE(p->int_regs); i++)
        g_assert_cmpuint(p->int_regs[i] & pins, ==, 0);
    g_assert_cmpuint(sony_usb_gpio_rdata(p) & pins, ==, 0);
    g_assert_false(sink->levels[216]);
    g_assert_false(sink->levels[71]);
    g_assert_false(sink->levels[67]);
    /* A transfer must NACK until the GPIO enable is restored. */
    I2CBus *bus = DESIGNWARE_I2C(bp->dw)->bus;
    g_assert_cmpint(i2c_start_transfer(bus, 8, false), !=, 0);
    i2c_end_transfer(bus);
    gpio_write(p, 0x04, 1u << 13);
    gpio_write(p, 0x44, 1u << 13);
    uint8_t mode, pending, reply[2];
    slave_read(bus, 0, &mode, 1);
    slave_read(bus, 6, &pending, 1);
    slave_read(bus, 0x7e, reply, 2);
    g_assert_cmpuint(mode, ==, 0);
    g_assert_cmpuint(pending, ==, 0);
    g_assert_cmpuint(reply[0] | reply[1], ==, 0);
}

static void board_tests(void)
{
    MemoryRegion sysmem;
    memory_region_init(&sysmem, NULL, "buspower-unit-memory", UINT64_MAX);
    TestSink *sink = (TestSink *)qdev_new(TYPE_TEST_SINK);
    qdev_realize(DEVICE(sink), NULL, &error_fatal);
    g_setenv("QEMU_SONY_USB_BUSPOWER_PROFILE", SONY_BUSPOWER_PROFILE, true);
    sony_usb_platform_create(&sysmem, DEVICE(sink), DEVICE(sink));
    MemoryRegionSection sec = memory_region_find(&sysmem, 0xf102e000, 4);
    g_assert_nonnull(sec.mr);
    SonyUsbPlatform *p = sec.mr->opaque;
    memory_region_unref(sec.mr);
    g_assert_nonnull(p->buspower);
    qemu_devices_reset(RESET_TYPE_COLD);
    master_reset_test(p, sink);
    edge_test(p, sink);
    bp_write(p->buspower, 1, 4, 0x80000001);
    bp_write(p->buspower, 2, 4, 0x80000001);
    qemu_devices_reset(RESET_TYPE_COLD);
    system_defaults(p, sink);
    ready(p);
    bp_write(p->buspower, 3, 0x48, 1u << 7); /* Leave pulse asserted across reset. */
    g_assert_true(p->buspower->reset_departed);
    qemu_devices_reset(RESET_TYPE_COLD);
    system_defaults(p, sink);
    /* No further fixture consumer: one process owns devices/callbacks to exit. */
}

int main(int argc, char **argv)
{
    g_test_init(&argc, &argv, NULL);
    module_call_init(MODULE_INIT_QOM);
    type_register_static(&sink_type);
    Object *machine = object_property_add_new_container(object_get_root(), "machine");
    object_property_add_new_container(machine, "unattached");
    qemu_init_main_loop(&error_fatal);
    qemu_register_resettable(OBJECT(sysbus_get_default()));
    g_test_add_func("/sony/buspower/board-reset-and-edges", board_tests);
    return g_test_run();
}
