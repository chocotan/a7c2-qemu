/* SPDX-License-Identifier: GPL-2.0-or-later
 * Explicit TEST HCLK/APB-reset banks and gated clock-request control words.
 * No link/PHY-ready status, silicon reset claim, or software-ready mutation.
 */
#include "qemu/osdep.h"
#include "qapi/error.h"
#include "qemu/module.h"
#include "hw/core/sysbus.h"
#include "scu.h"

#define TYPE_TEST_SCU "a7c2-test-pcie-scu"
OBJECT_DECLARE_SIMPLE_TYPE(TestScuState, TEST_SCU)
typedef struct TestScuRegion {
    MemoryRegion mr;
    TestScuState *owner;
    uint64_t base;
} TestScuRegion;
struct TestScuState {
    SysBusDevice parent_obj;
    struct sony_pcie_scu_state state;
    TestScuRegion regions[7];
};
static MemTxResult read_register(void *opaque,hwaddr offset,uint64_t *value,unsigned size,MemTxAttrs attrs)
{
    TestScuRegion *r=opaque;uint32_t result;
    if(!sony_pcie_scu_read(&r->owner->state,r->base+offset,size,&result))return MEMTX_DECODE_ERROR;
    *value=result;return MEMTX_OK;
}
static MemTxResult write_register(void *opaque,hwaddr offset,uint64_t value,unsigned size,MemTxAttrs attrs)
{
    TestScuRegion *r=opaque;
    if(value>UINT32_MAX || !sony_pcie_scu_write(&r->owner->state,r->base+offset,size,(uint32_t)value))
        return MEMTX_DECODE_ERROR;
    return MEMTX_OK;
}
static const MemoryRegionOps ops={
    .read_with_attrs=read_register,.write_with_attrs=write_register,.endianness=DEVICE_LITTLE_ENDIAN,
    .valid={.min_access_size=4,.max_access_size=4,.unaligned=false},
    .impl={.min_access_size=4,.max_access_size=4},
};
static void reset_device(DeviceState *dev) { sony_pcie_scu_init(&TEST_SCU(dev)->state); }
static void realize_device(DeviceState *dev,Error **errp)
{
    static const uint64_t bases[]={0xf1388080,0xf1388310,0xf11e0380,0xf1160380,
        0xf11a0380,0xf1220380,0xf1120380};
    TestScuState *s=TEST_SCU(dev);sony_pcie_scu_init(&s->state);
    for(unsigned i=0;i<7;i++) {
        char name[48];snprintf(name,sizeof name,"test-pcie-scu-region%u",i);
        TestScuRegion *r=&s->regions[i];r->owner=s;r->base=bases[i];
        memory_region_init_io(&r->mr,OBJECT(dev),&ops,r,name,i<2?12:4);
        sysbus_init_mmio(SYS_BUS_DEVICE(dev),&r->mr);
    }
    object_property_add_uint32_ptr(OBJECT(dev),"hclk",&s->state.hclk,OBJ_PROP_FLAG_READ);
    object_property_add_uint32_ptr(OBJECT(dev),"apb-reset",&s->state.reset,OBJ_PROP_FLAG_READ);
    for(unsigned i=0;i<5;i++) {
        char name[24];snprintf(name,sizeof name,"wrapper%u",i);
        object_property_add_uint32_ptr(OBJECT(dev),name,&s->state.wrapper[i],OBJ_PROP_FLAG_READ);
    }
}
static void class_init(ObjectClass *klass,const void *data)
{
    DeviceClass *dc=DEVICE_CLASS(klass);dc->realize=realize_device;dc->user_creatable=false;
    device_class_set_legacy_reset(dc,reset_device);
    dc->desc="TEST stateful PCIe HCLK/APB-reset banks, no link/PHY";
}
static const TypeInfo type_info={.name=TYPE_TEST_SCU,.parent=TYPE_SYS_BUS_DEVICE,
    .instance_size=sizeof(TestScuState),.class_init=class_init};
static void register_types(void) { type_register_static(&type_info); }
type_init(register_types)
