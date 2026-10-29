/* SPDX-License-Identifier: GPL-2.0-or-later
 * Bounded TEST Root-Port DBI compatibility window. No Sony PHY-ready status.
 */
#include "qemu/osdep.h"
#include "qapi/error.h"
#include "qemu/module.h"
#include "hw/core/sysbus.h"
#include "hw/core/qdev-properties.h"
#include "hw/pci/pci_device.h"
#include "hw/pci/pcie.h"

#define TYPE_TEST_DBI "a7c2-test-root-dbi"
OBJECT_DECLARE_SIMPLE_TYPE(TestDbiState, TEST_DBI)
struct TestDbiState {
    SysBusDevice parent_obj;
    PCIDevice *port;
    MemoryRegion dbi,wrapper;
    uint32_t control,write_enable;
};
static MemTxResult dbi_read(void *opaque,hwaddr offset,uint64_t *value,unsigned size,MemTxAttrs attrs)
{
    TestDbiState *s=opaque;
    if (offset==0x8bc && size==4) { *value=s->write_enable;return MEMTX_OK; }
    /* Deliberately do not return fabricated link/PHY values for vendor CSRs. */
    if (offset>=0x700 || offset+size>pci_config_size(s->port)) return MEMTX_DECODE_ERROR;
    *value=s->port->config_read(s->port,offset,size);return MEMTX_OK;
}
static MemTxResult dbi_write(void *opaque,hwaddr offset,uint64_t value,unsigned size,MemTxAttrs attrs)
{
    TestDbiState *s=opaque;
    if (offset==0x8bc && size==4) {
        if (value&~UINT64_C(1)) return MEMTX_DECODE_ERROR;
        s->write_enable=value;return MEMTX_OK;
    }
    if (offset>=0x700 || offset+size>pci_config_size(s->port)) return MEMTX_DECODE_ERROR;
    unsigned cap=s->port->exp.exp_cap;
    bool slot_flags=offset==cap+2 && size==2;
    bool slot_cap=offset==cap+0x14 && size==4;
    bool unlocked=s->write_enable && !(s->control&0x40) && (slot_flags||slot_cap);
    uint8_t saved[4];
    if (unlocked) {
        memcpy(saved,s->port->wmask+offset,size);
        memset(s->port->wmask+offset,0xff,size);
    }
    s->port->config_write(s->port,offset,value,size);
    if (unlocked) memcpy(s->port->wmask+offset,saved,size);
    return MEMTX_OK;
}
static MemTxResult wrapper_read(void *opaque,hwaddr offset,uint64_t *value,unsigned size,MemTxAttrs attrs)
{
    if (offset!=0x20380 || size!=4) return MEMTX_DECODE_ERROR;
    *value=TEST_DBI(opaque)->control;return MEMTX_OK;
}
static MemTxResult wrapper_write(void *opaque,hwaddr offset,uint64_t value,unsigned size,MemTxAttrs attrs)
{
    if (offset!=0x20380 || size!=4 || value&~UINT64_C(0x40)) return MEMTX_DECODE_ERROR;
    TEST_DBI(opaque)->control=value;return MEMTX_OK;
}
static const MemoryRegionOps dbi_ops={
    .read_with_attrs=dbi_read,.write_with_attrs=dbi_write,.endianness=DEVICE_LITTLE_ENDIAN,
    .valid={.min_access_size=1,.max_access_size=4,.unaligned=false},
    .impl={.min_access_size=1,.max_access_size=4},
};
static const MemoryRegionOps wrapper_ops={
    .read_with_attrs=wrapper_read,.write_with_attrs=wrapper_write,.endianness=DEVICE_LITTLE_ENDIAN,
    .valid={.min_access_size=4,.max_access_size=4,.unaligned=false},
    .impl={.min_access_size=4,.max_access_size=4},
};
static void reset_device(DeviceState *device)
{
    TestDbiState *s=TEST_DBI(device);s->control=0x40;s->write_enable=0;
}
static void realize_device(DeviceState *device,Error **errp)
{
    TestDbiState *s=TEST_DBI(device);
    if (!s->port || !pci_is_express(s->port) || !s->port->exp.exp_cap) {
        error_setg(errp,"test Root DBI requires its explicit realized PCIe port");return;
    }
    memory_region_init_io(&s->dbi,OBJECT(device),&dbi_ops,s,"test-root-dbi",4096);
    memory_region_init_io(&s->wrapper,OBJECT(device),&wrapper_ops,s,"test-root-wrapper",0x40000);
    sysbus_init_mmio(SYS_BUS_DEVICE(device),&s->dbi);
    sysbus_init_mmio(SYS_BUS_DEVICE(device),&s->wrapper);
}
static const Property properties[]={
    DEFINE_PROP_LINK("port",TestDbiState,port,TYPE_PCI_DEVICE,PCIDevice *),
};
static void class_init(ObjectClass *klass,const void *data)
{
    DeviceClass *dc=DEVICE_CLASS(klass);dc->realize=realize_device;dc->user_creatable=false;
    device_class_set_legacy_reset(dc,reset_device);device_class_set_props(dc,properties);
    dc->desc="Bounded DBI RO-write TEST window, not Sony PHY";
}
static const TypeInfo type_info={.name=TYPE_TEST_DBI,.parent=TYPE_SYS_BUS_DEVICE,
    .instance_size=sizeof(TestDbiState),.class_init=class_init};
static void register_types(void) { type_register_static(&type_info); }
type_init(register_types)
