/* SPDX-License-Identifier: GPL-2.0-or-later
 * Virtual DFS selector only: current mode 0 and 1000 ns completion are explicit
 * virtual policies, not silicon reset/timing claims. No clocks or IRQs change;
 * the original UPM poll/checkstatus path owns its event 3 notification.
 */
#include "qemu/osdep.h"
#include "qapi/error.h"
#include "qemu/module.h"
#include "qemu/timer.h"
#include "hw/core/sysbus.h"
#include "dfs.h"

#define TYPE_SONY_DFS "a7c2-virtual-dfs-selector"
#define SONY_DFS_DELAY_NS 1000u
OBJECT_DECLARE_SIMPLE_TYPE(SonyDfsState, SONY_DFS)

struct SonyDfsState {
    SysBusDevice parent_obj;
    MemoryRegion mmio;
    struct sony_dfs_selector selector;
    QEMUTimer *timer;
};

static void dfs_tick(void *opaque)
{
    SonyDfsState *s = opaque;

    if (sony_dfs_complete(&s->selector)) {
        fprintf(stderr, "SONY_DFS_COMPLETE target=0x%08x generation=%" PRIu64
                " completed_generation=%" PRIu64
                " readback_request=0x%08x readback_ckstatus=0x%08x"
                " virtual_selector=1 clocks_changed=0\n",
                s->selector.target, s->selector.generation,
                s->selector.completed_generation,
                s->selector.request, s->selector.status);
    }
}

static MemTxResult dfs_read(void *opaque, hwaddr offset, uint64_t *value,
                            unsigned size, MemTxAttrs attrs)
{
    SonyDfsState *s = opaque;

    *value = 0;
    if (sony_dfs_read(&s->selector, offset, size, value)) {
        timer_del(s->timer);
        fprintf(stderr, "SONY_DFS_REJECT access=read offset=0x%" HWADDR_PRIx
                " size=%u target=0x%08x generation=%" PRIu64
                " readback_request=0x%08x readback_ckstatus=0x%08x faults=%u"
                " virtual_selector=1 clocks_changed=0\n",
                offset, size, s->selector.target, s->selector.generation,
                s->selector.request, s->selector.status, s->selector.faults);
        return MEMTX_DECODE_ERROR;
    }
    return MEMTX_OK;
}

static MemTxResult dfs_write(void *opaque, hwaddr offset, uint64_t value,
                             unsigned size, MemTxAttrs attrs)
{
    SonyDfsState *s = opaque;

    if (sony_dfs_write(&s->selector, offset, size, value)) {
        timer_del(s->timer);
        fprintf(stderr, "SONY_DFS_REJECT access=write offset=0x%" HWADDR_PRIx
                " size=%u value=0x%" PRIx64
                " target=0x%08x generation=%" PRIu64
                " readback_request=0x%08x readback_ckstatus=0x%08x faults=%u"
                " virtual_selector=1 clocks_changed=0\n",
                offset, size, value, s->selector.target, s->selector.generation,
                s->selector.request, s->selector.status, s->selector.faults);
        return MEMTX_DECODE_ERROR;
    }
    if (s->selector.phase == SONY_DFS_BUSY && !timer_pending(s->timer)) {
        timer_mod(s->timer,
                  qemu_clock_get_ns(QEMU_CLOCK_VIRTUAL) + SONY_DFS_DELAY_NS);
        fprintf(stderr, "SONY_DFS_REQUEST target=0x%08x generation=%" PRIu64
                " readback_request=0x%08x readback_ckstatus=0x%08x"
                " delay_ns=%u virtual_selector=1 clocks_changed=0\n",
                s->selector.target, s->selector.generation,
                s->selector.request, s->selector.status, SONY_DFS_DELAY_NS);
    }
    return MEMTX_OK;
}

/* Pass widths/alignment unchanged so the core faults instead of split success. */
static const MemoryRegionOps dfs_ops = {
    .read_with_attrs = dfs_read,
    .write_with_attrs = dfs_write,
    .endianness = DEVICE_LITTLE_ENDIAN,
    .valid = { .min_access_size = 1, .max_access_size = 8, .unaligned = true },
    .impl = { .min_access_size = 1, .max_access_size = 8, .unaligned = true },
};

static void dfs_reset(DeviceState *device)
{
    SonyDfsState *s = SONY_DFS(device);

    if (s->timer) {
        timer_del(s->timer);
    }
    sony_dfs_reset(&s->selector);
}

static void dfs_realize(DeviceState *device, Error **errp)
{
    SonyDfsState *s = SONY_DFS(device);

    s->timer = timer_new_ns(QEMU_CLOCK_VIRTUAL, dfs_tick, s);
    dfs_reset(device);
    memory_region_init_io(&s->mmio, OBJECT(device), &dfs_ops, s,
                          "sony-dfs-selector", 0x14);
    sysbus_init_mmio(SYS_BUS_DEVICE(device), &s->mmio);
    object_property_add_uint32_ptr(OBJECT(device), "phase",
                                  &s->selector.phase, OBJ_PROP_FLAG_READ);
    object_property_add_uint32_ptr(OBJECT(device), "current-mode",
                                  &s->selector.current_mode, OBJ_PROP_FLAG_READ);
    object_property_add_uint32_ptr(OBJECT(device), "request-count",
                                  &s->selector.requests, OBJ_PROP_FLAG_READ);
    object_property_add_uint32_ptr(OBJECT(device), "completion-count",
                                  &s->selector.completions, OBJ_PROP_FLAG_READ);
    object_property_add_uint32_ptr(OBJECT(device), "faults",
                                  &s->selector.faults, OBJ_PROP_FLAG_READ);
}

static void dfs_finalize(Object *obj)
{
    SonyDfsState *s = SONY_DFS(obj);

    timer_free(s->timer);
}

static void dfs_class_init(ObjectClass *klass, const void *data)
{
    DeviceClass *dc = DEVICE_CLASS(klass);

    dc->realize = dfs_realize;
    dc->user_creatable = false;
    device_class_set_legacy_reset(dc, dfs_reset);
    dc->desc = "Virtual DFS selector consumption; no clock or frequency changes";
}

static const TypeInfo dfs_type_info = {
    .name = TYPE_SONY_DFS,
    .parent = TYPE_SYS_BUS_DEVICE,
    .instance_size = sizeof(SonyDfsState),
    .instance_finalize = dfs_finalize,
    .class_init = dfs_class_init,
};

static void dfs_register_types(void)
{
    type_register_static(&dfs_type_info);
}
type_init(dfs_register_types)
