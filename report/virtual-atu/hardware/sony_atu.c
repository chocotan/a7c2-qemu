/* SPDX-License-Identifier: GPL-2.0-or-later
 * Virtual ATU register bank and real PCI-memory aperture. Endpoint memory is
 * an explicit link; no implicit CP-ready state or constant success replies.
 */
#include "qemu/osdep.h"
#include "qapi/error.h"
#include "qemu/module.h"
#include "hw/core/sysbus.h"
#include "hw/core/qdev-properties.h"
#include "system/address-spaces.h"
#include "atu_core.h"

#define TYPE_SONY_ATU "sony-virtual-atu"
OBJECT_DECLARE_SIMPLE_TYPE(SonyAtuState, SONY_ATU)
struct SonyAtuState {
    SysBusDevice parent_obj;
    MemoryRegion registers, aperture;
    MemoryRegion *pci_memory;
    AddressSpace pci_as;
    struct sony_atu state;
};

static MemTxResult register_read(void *opaque, hwaddr address, uint64_t *value,
                                 unsigned size, MemTxAttrs attrs)
{
    SonyAtuState *s = opaque;
    uint32_t data;
    if (size != 4 || sony_atu_register(&s->state, address, &data, 0)) return MEMTX_DECODE_ERROR;
    *value = data;
    return MEMTX_OK;
}
static MemTxResult register_write(void *opaque, hwaddr address, uint64_t value,
                                  unsigned size, MemTxAttrs attrs)
{
    SonyAtuState *s = opaque;
    uint32_t data = value;
    return size != 4 || sony_atu_register(&s->state, address, &data, 1)
        ? MEMTX_DECODE_ERROR : MEMTX_OK;
}
struct peer_transaction { SonyAtuState *state; MemTxAttrs attrs; MemTxResult result; };
static int peer_access(void *opaque, uint64_t target, void *bytes, size_t size, int write)
{
    struct peer_transaction *transaction = opaque;
    transaction->result = address_space_rw(&transaction->state->pci_as, target,
                                            transaction->attrs, bytes, size, write);
    return transaction->result != MEMTX_OK;
}
static MemTxResult aperture_access(void *opaque, hwaddr offset, uint64_t *value,
                                   unsigned size, MemTxAttrs attrs, bool write)
{
    SonyAtuState *s = opaque;
    struct peer_transaction transaction = { s, attrs, MEMTX_DECODE_ERROR };
    uint8_t bytes[8];
    if (!size || size > sizeof bytes) return MEMTX_DECODE_ERROR;
    if (write) {
        for (unsigned i = 0; i < size; i++) bytes[i] = *value >> (8*i);
    }
    if (sony_atu_transfer(&s->state, 0xc0000000ULL+offset, bytes, size, write,
                          peer_access, &transaction)) return transaction.result;
    if (!write) {
        *value = 0;
        for (unsigned i = 0; i < size; i++) *value |= (uint64_t)bytes[i] << (8*i);
    }
    return MEMTX_OK;
}
static MemTxResult aperture_read(void *opaque, hwaddr offset, uint64_t *value,
                                  unsigned size, MemTxAttrs attrs)
{
    return aperture_access(opaque, offset, value, size, attrs, false);
}
static MemTxResult aperture_write(void *opaque, hwaddr offset, uint64_t value,
                                   unsigned size, MemTxAttrs attrs)
{
    return aperture_access(opaque, offset, &value, size, attrs, true);
}
static const MemoryRegionOps register_ops = {
    .read_with_attrs = register_read, .write_with_attrs = register_write,
    .endianness = DEVICE_LITTLE_ENDIAN,
    .valid = { .min_access_size = 4, .max_access_size = 4, .unaligned = false },
    .impl = { .min_access_size = 4, .max_access_size = 4 },
};
static const MemoryRegionOps aperture_ops = {
    .read_with_attrs = aperture_read, .write_with_attrs = aperture_write,
    .endianness = DEVICE_LITTLE_ENDIAN,
    .valid = { .min_access_size = 1, .max_access_size = 8, .unaligned = true },
    .impl = { .min_access_size = 1, .max_access_size = 8, .unaligned = true },
};
static void sony_atu_reset_device(DeviceState *device)
{
    sony_atu_reset(&SONY_ATU(device)->state);
}
static void sony_atu_realize(DeviceState *device, Error **errp)
{
    SonyAtuState *s = SONY_ATU(device);
    if (!s->pci_memory) {
        error_setg(errp, "sony-virtual-atu requires an explicit owned PCI memory link");
        return;
    }
    address_space_init(&s->pci_as, s->pci_memory, "sony-virtual-pci");
    memory_region_init_io(&s->registers, OBJECT(device), &register_ops, s,
                          "sony-atu-registers", 4096);
    memory_region_init_io(&s->aperture, OBJECT(device), &aperture_ops, s,
                          "sony-atu-aperture", 0x20000000ULL);
    sysbus_init_mmio(SYS_BUS_DEVICE(device), &s->registers);
    sysbus_init_mmio(SYS_BUS_DEVICE(device), &s->aperture);
}
static const Property sony_atu_properties[] = {
    DEFINE_PROP_LINK("pci-memory", SonyAtuState, pci_memory, TYPE_MEMORY_REGION, MemoryRegion *),
};
static void sony_atu_class_init(ObjectClass *klass, const void *data)
{
    DeviceClass *dc = DEVICE_CLASS(klass);
    dc->realize = sony_atu_realize;
    device_class_set_legacy_reset(dc, sony_atu_reset_device);
    device_class_set_props(dc, sony_atu_properties);
    dc->desc = "Explicit virtual eight-window PCI ATU";
}
static const TypeInfo sony_atu_type = {
    .name = TYPE_SONY_ATU, .parent = TYPE_SYS_BUS_DEVICE,
    .instance_size = sizeof(SonyAtuState), .class_init = sony_atu_class_init,
};
static void sony_atu_register_types(void) { type_register_static(&sony_atu_type); }
type_init(sony_atu_register_types)
