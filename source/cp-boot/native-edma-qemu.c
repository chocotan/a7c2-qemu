/* SPDX-License-Identifier: GPL-2.0-or-later
 * Native-link eDMA adapter for the existing bounded sony_edma C core.
 * The board supplies separate local and PCI memory views. No peer protocol,
 * shared RAM allocation, UIPC acknowledgement or PCIe-ready state lives here.
 * Migration and VM save/restore are unsupported.
 */
#include "qemu/osdep.h"
#include "qemu/module.h"
#include "qapi/error.h"
#include "hw/core/irq.h"
#include "hw/core/qdev-properties.h"
#include "hw/core/sysbus.h"
#include "migration/vmstate.h"
#include "registers.h"

#define TYPE_NATIVE_EDMA "a7c2-native-edma"
#define NATIVE_EDMA_DIRECTIONS 2
#define NATIVE_EDMA_CHANNELS 8
#define NATIVE_EDMA_IRQS (1 + NATIVE_EDMA_DIRECTIONS * NATIVE_EDMA_CHANNELS)
#define NATIVE_EDMA_MMIO_SIZE 0x1200

OBJECT_DECLARE_SIMPLE_TYPE(NativeEdmaState, NATIVE_EDMA)

struct NativeEdmaState {
    SysBusDevice parent_obj;
    MemoryRegion mmio;
    MemoryRegion *local_memory;
    MemoryRegion *pci_memory;
    AddressSpace *local_as;
    AddressSpace *pci_as;
    struct sony_edma_registers state;
    struct sony_edma_bus bus;
    qemu_irq irq[NATIVE_EDMA_IRQS];
    uint32_t max_steps;
    uint64_t max_bytes;
    bool executing;
};

static int native_edma_read(void *opaque, enum sony_edma_domain domain,
                            uint64_t address, void *bytes, size_t size)
{
    NativeEdmaState *s = opaque;
    AddressSpace *as = domain == SONY_EDMA_LOCAL ? s->local_as : s->pci_as;

    if (domain != SONY_EDMA_LOCAL && domain != SONY_EDMA_PCI) {
        return -1;
    }
    return address_space_read(as, address, MEMTXATTRS_UNSPECIFIED,
                              bytes, size) != MEMTX_OK;
}

static int native_edma_write(void *opaque, enum sony_edma_domain domain,
                             uint64_t address, const void *bytes, size_t size)
{
    NativeEdmaState *s = opaque;
    AddressSpace *as = domain == SONY_EDMA_LOCAL ? s->local_as : s->pci_as;

    if (domain != SONY_EDMA_LOCAL && domain != SONY_EDMA_PCI) {
        return -1;
    }
    return address_space_write(as, address, MEMTXATTRS_UNSPECIFIED,
                               bytes, size) != MEMTX_OK;
}

static void native_edma_update_irqs(NativeEdmaState *s)
{
    qemu_set_irq(s->irq[0], sony_edma_irq(&s->state));
    for (unsigned d = 0; d < NATIVE_EDMA_DIRECTIONS; d++) {
        uint32_t active = s->state.status[d] & ~s->state.mask[d];

        for (unsigned ch = 0; ch < NATIVE_EDMA_CHANNELS; ch++) {
            qemu_set_irq(s->irq[1 + d * NATIVE_EDMA_CHANNELS + ch],
                         (active & (UINT32_C(0x10001) << ch)) != 0);
        }
    }
}

static MemTxResult native_edma_mmio_read(void *opaque, hwaddr offset,
                                        uint64_t *value, unsigned size,
                                        MemTxAttrs attrs)
{
    NativeEdmaState *s = opaque;
    uint32_t data;

    if (size != 4 || (offset & 3) || offset >= NATIVE_EDMA_MMIO_SIZE ||
        sony_edma_register(&s->state, &s->bus, offset, &data, 0)) {
        return MEMTX_DECODE_ERROR;
    }
    *value = data;
    return MEMTX_OK;
}

static MemTxResult native_edma_mmio_write(void *opaque, hwaddr offset,
                                         uint64_t value, unsigned size,
                                         MemTxAttrs attrs)
{
    NativeEdmaState *s = opaque;
    uint32_t data;
    int rc;

    /* Reject all reentrant writes, including DMA into our own doorbells. */
    if (s->executing) {
        return MEMTX_ACCESS_ERROR;
    }
    if (size != 4 || (offset & 3) || offset >= NATIVE_EDMA_MMIO_SIZE ||
        value > UINT32_MAX) {
        return MEMTX_DECODE_ERROR;
    }
    data = value;
    s->executing = true;
    rc = sony_edma_register(&s->state, &s->bus, offset, &data, 1);
    s->executing = false;
    native_edma_update_irqs(s);
    return rc ? MEMTX_DECODE_ERROR : MEMTX_OK;
}

static const MemoryRegionOps native_edma_ops = {
    .read_with_attrs = native_edma_mmio_read,
    .write_with_attrs = native_edma_mmio_write,
    .endianness = DEVICE_LITTLE_ENDIAN,
    .valid = { .min_access_size = 4, .max_access_size = 4, .unaligned = false },
    .impl = { .min_access_size = 4, .max_access_size = 4, .unaligned = false },
};

static void native_edma_reset(DeviceState *dev)
{
    NativeEdmaState *s = NATIVE_EDMA(dev);

    sony_edma_reset(&s->state, s->max_steps, s->max_bytes);
    s->executing = false;
    for (unsigned i = 0; i < NATIVE_EDMA_IRQS; i++) {
        qemu_set_irq(s->irq[i], 0);
    }
}

static void native_edma_realize(DeviceState *dev, Error **errp)
{
    NativeEdmaState *s = NATIVE_EDMA(dev);

    if (!s->local_memory || !s->pci_memory || !s->max_steps || !s->max_bytes) {
        error_setg(errp, TYPE_NATIVE_EDMA " requires local-memory and pci-memory "
                   "links and nonzero max-steps/max-bytes execution budgets");
        return;
    }
    s->local_as = g_new0(AddressSpace, 1);
    s->pci_as = g_new0(AddressSpace, 1);
    address_space_init(s->local_as, s->local_memory, "native-edma-local");
    address_space_init(s->pci_as, s->pci_memory, "native-edma-pci");
    s->bus = (struct sony_edma_bus) {
        .opaque = s,
        .read = native_edma_read,
        .write = native_edma_write,
    };
    memory_region_init_io(&s->mmio, OBJECT(dev), &native_edma_ops, s,
                          TYPE_NATIVE_EDMA, NATIVE_EDMA_MMIO_SIZE);
    sysbus_init_mmio(SYS_BUS_DEVICE(dev), &s->mmio);
    for (unsigned i = 0; i < NATIVE_EDMA_IRQS; i++) {
        sysbus_init_irq(SYS_BUS_DEVICE(dev), &s->irq[i]);
    }
    native_edma_reset(dev);
}

static void native_edma_unrealize(DeviceState *dev)
{
    NativeEdmaState *s = NATIVE_EDMA(dev);

    native_edma_reset(dev);
    /* AddressSpace destruction completes via RCU after the device can die. */
    address_space_destroy_free(s->pci_as);
    address_space_destroy_free(s->local_as);
    s->pci_as = s->local_as = NULL;
}

static const Property native_edma_properties[] = {
    DEFINE_PROP_LINK("local-memory", NativeEdmaState, local_memory,
                     TYPE_MEMORY_REGION, MemoryRegion *),
    DEFINE_PROP_LINK("pci-memory", NativeEdmaState, pci_memory,
                     TYPE_MEMORY_REGION, MemoryRegion *),
    /* These are bounded functional-model budgets, not silicon limits. */
    DEFINE_PROP_UINT32("max-steps", NativeEdmaState, max_steps, 128),
    DEFINE_PROP_UINT64("max-bytes", NativeEdmaState, max_bytes,
                       UINT64_C(8) * 1024 * 1024),
};

static const VMStateDescription native_edma_vmstate = {
    .name = TYPE_NATIVE_EDMA,
    .unmigratable = true,
};

static void native_edma_class_init(ObjectClass *klass, const void *data)
{
    DeviceClass *dc = DEVICE_CLASS(klass);

    dc->realize = native_edma_realize;
    dc->unrealize = native_edma_unrealize;
    dc->user_creatable = false;
    dc->vmsd = &native_edma_vmstate;
    device_class_set_legacy_reset(dc, native_edma_reset);
    device_class_set_props(dc, native_edma_properties);
    dc->desc = "Bounded native-link eDMA with explicit memory views; migration unsupported";
}

static const TypeInfo native_edma_type = {
    .name = TYPE_NATIVE_EDMA,
    .parent = TYPE_SYS_BUS_DEVICE,
    .instance_size = sizeof(NativeEdmaState),
    .class_init = native_edma_class_init,
};

static void native_edma_register_types(void)
{
    type_register_static(&native_edma_type);
}
type_init(native_edma_register_types)
