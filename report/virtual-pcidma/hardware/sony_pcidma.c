/* SPDX-License-Identifier: GPL-2.0-or-later
 * Experimental eDMA subset. Local/PCI address spaces must be explicit links.
 */
#include "qemu/osdep.h"
#include "qapi/error.h"
#include "qemu/module.h"
#include "hw/core/sysbus.h"
#include "hw/core/qdev-properties.h"
#include "hw/core/irq.h"
#include "registers.h"
#include "backup_peer.h"

#define TYPE_SONY_PCIDMA "sony-virtual-pcidma"
OBJECT_DECLARE_SIMPLE_TYPE(SonyPcidmaState, SONY_PCIDMA)
struct SonyPcidmaState {
    SysBusDevice parent_obj;
    MemoryRegion registers;
    MemoryRegion *local_memory, *pci_memory;
    AddressSpace local_as, pci_as;
    struct sony_edma_registers state;
    struct sony_edma_bus bus;
    qemu_irq irq;
    uint32_t max_steps;
    uint64_t max_bytes, read4_sequence, reset_sequence;
    struct sony_backup_dma_snapshot read4;
    bool executing;
};
static int dma_read(void *opaque, enum sony_edma_domain domain, uint64_t address, void *bytes, size_t size)
{
    SonyPcidmaState *s=opaque;
    AddressSpace *as=domain==SONY_EDMA_LOCAL?&s->local_as:&s->pci_as;
    return address_space_read(as,address,MEMTXATTRS_UNSPECIFIED,bytes,size)!=MEMTX_OK;
}
static int dma_write(void *opaque, enum sony_edma_domain domain, uint64_t address, const void *bytes, size_t size)
{
    SonyPcidmaState *s=opaque;
    AddressSpace *as=domain==SONY_EDMA_LOCAL?&s->local_as:&s->pci_as;
    return address_space_write(as,address,MEMTXATTRS_UNSPECIFIED,bytes,size)!=MEMTX_OK;
}
static MemTxResult register_read(void *opaque, hwaddr offset, uint64_t *value,
                                 unsigned size, MemTxAttrs attrs)
{
    SonyPcidmaState *s=opaque; uint32_t data;
    if (size!=4 || offset>UINT32_MAX || sony_edma_register(&s->state,&s->bus,offset,&data,0))
        return MEMTX_DECODE_ERROR;
    *value=data; return MEMTX_OK;
}
static MemTxResult register_write(void *opaque, hwaddr offset, uint64_t value,
                                  unsigned size, MemTxAttrs attrs)
{
    SonyPcidmaState *s=opaque; uint32_t data=value;
    /* A DMA write into this same engine must not recursively ring doorbells.
     * Reject it as a real transaction error; the outer request will abort.
     */
    if (s->executing) return MEMTX_ACCESS_ERROR;
    if (size!=4 || offset>UINT32_MAX) return MEMTX_DECODE_ERROR;
    s->executing=true;
    int rc=sony_edma_register(&s->state,&s->bus,offset,&data,1);
    if (!rc && offset == 0x30 && value == 4) {
        const uint32_t *r = s->state.channel[1][4];
        s->read4 = (struct sony_backup_dma_snapshot){
            .sequence = ++s->read4_sequence, .reset = s->reset_sequence,
            .source = r[3] | (uint64_t)r[4] << 32,
            .destination = r[5] | (uint64_t)r[6] << 32,
            .requested = r[2], .copied = s->state.last[1][4].bytes,
            .result = s->state.last[1][4].result, .mode = r[0] & ~0x60U,
        };
    }
    s->executing=false;
    qemu_set_irq(s->irq,sony_edma_irq(&s->state));
    return rc?MEMTX_DECODE_ERROR:MEMTX_OK;
}
static const MemoryRegionOps register_ops={
    .read_with_attrs=register_read, .write_with_attrs=register_write,
    .endianness=DEVICE_LITTLE_ENDIAN,
    .valid={.min_access_size=4,.max_access_size=4,.unaligned=false},
    .impl={.min_access_size=4,.max_access_size=4},
};
static void reset_device(DeviceState *device)
{
    SonyPcidmaState *s=SONY_PCIDMA(device);
    sony_edma_reset(&s->state,s->max_steps,s->max_bytes);
    s->read4_sequence = 0;
    memset(&s->read4, 0, sizeof(s->read4));
    s->reset_sequence++;
    s->executing=false; qemu_set_irq(s->irq,0);
}
static void realize_device(DeviceState *device, Error **errp)
{
    SonyPcidmaState *s=SONY_PCIDMA(device);
    if (!s->local_memory || !s->pci_memory || !s->max_steps || !s->max_bytes) {
        error_setg(errp,"sony-virtual-pcidma requires local/PCI memory links and nonzero diagnostic bounds");
        return;
    }
    address_space_init(&s->local_as,s->local_memory,"sony-edma-local");
    address_space_init(&s->pci_as,s->pci_memory,"sony-edma-pci");
    s->bus=(struct sony_edma_bus){s,dma_read,dma_write};
    memory_region_init_io(&s->registers,OBJECT(device),&register_ops,s,"sony-edma-registers",0x1200);
    sysbus_init_mmio(SYS_BUS_DEVICE(device),&s->registers);
    sysbus_init_irq(SYS_BUS_DEVICE(device),&s->irq);
}
void sony_pcidma_backup_snapshot(DeviceState *device, struct sony_backup_dma_snapshot *out)
{
    SonyPcidmaState *s = SONY_PCIDMA(device);
    *out = s->read4;
    out->reset = s->reset_sequence;
    out->executing = s->executing;
}
static const Property properties[]={
    DEFINE_PROP_LINK("local-memory",SonyPcidmaState,local_memory,TYPE_MEMORY_REGION,MemoryRegion *),
    DEFINE_PROP_LINK("pci-memory",SonyPcidmaState,pci_memory,TYPE_MEMORY_REGION,MemoryRegion *),
    DEFINE_PROP_UINT32("max-steps",SonyPcidmaState,max_steps,64),
    DEFINE_PROP_UINT64("max-bytes",SonyPcidmaState,max_bytes,0x100000),
};
static void class_init(ObjectClass *klass, const void *data)
{
    DeviceClass *dc=DEVICE_CLASS(klass);
    dc->realize=realize_device; dc->user_creatable=false;
    device_class_set_legacy_reset(dc,reset_device); device_class_set_props(dc,properties);
    dc->desc="Bounded explicit-address-space PCI DMA diagnostic";
}
static const TypeInfo type_info={.name=TYPE_SONY_PCIDMA,.parent=TYPE_SYS_BUS_DEVICE,
    .instance_size=sizeof(SonyPcidmaState),.class_init=class_init};
static void register_types(void) { type_register_static(&type_info); }
type_init(register_types)
