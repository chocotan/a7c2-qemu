/* SPDX-License-Identifier: GPL-2.0-or-later
 * Explicit TEST SCU CCF register storage composed with verified APB access gates.
 * No PLL lock, PHY/link ready, DMA completion or private-kernel state.
 */
#include "qemu/osdep.h"
#include "qapi/error.h"
#include "qemu/module.h"
#include "hw/core/sysbus.h"
#include "ccf.h"
#include "scu.h"

#define TYPE_TEST_CCF "a7c2-test-scu-ccf"
OBJECT_DECLARE_SIMPLE_TYPE(TestCcfState, TEST_CCF)
typedef struct TestCcfRegion {MemoryRegion mr;TestCcfState *owner;uint64_t base;unsigned index;} TestCcfRegion;
struct TestCcfState {
    SysBusDevice parent_obj;
    struct sony_ccf_state ccf;
    struct sony_pcie_scu_state wrapper;
    TestCcfRegion regions[7];
};
static void synchronize(TestCcfState *s)
{
    s->wrapper.hclk=s->ccf.gates[8];s->wrapper.reset=s->ccf.resets[1];
}
static MemTxResult read_register(void *opaque,hwaddr offset,uint64_t *value,unsigned size,MemTxAttrs attrs)
{
    TestCcfRegion *r=opaque;uint32_t result;bool ok;synchronize(r->owner);
    if(r->index<2)ok=sony_ccf_read(&r->owner->ccf,r->base+offset,size,&result);
    else ok=sony_pcie_scu_read(&r->owner->wrapper,r->base+offset,size,&result);
    if(!ok)return MEMTX_DECODE_ERROR;
    *value=result;return MEMTX_OK;
}
static MemTxResult write_register(void *opaque,hwaddr offset,uint64_t value,unsigned size,MemTxAttrs attrs)
{
    TestCcfRegion *r=opaque;bool ok;
    if(value>UINT32_MAX)return MEMTX_DECODE_ERROR;
    synchronize(r->owner);
    if(r->index<2)ok=sony_ccf_write(&r->owner->ccf,r->base+offset,size,(uint32_t)value);
    else ok=sony_pcie_scu_write(&r->owner->wrapper,r->base+offset,size,(uint32_t)value);
    synchronize(r->owner);
    return ok?MEMTX_OK:MEMTX_DECODE_ERROR;
}
static const MemoryRegionOps ops={.read_with_attrs=read_register,.write_with_attrs=write_register,
    .endianness=DEVICE_LITTLE_ENDIAN,.valid={.min_access_size=4,.max_access_size=4,.unaligned=false},
    .impl={.min_access_size=4,.max_access_size=4}};
static void reset_device(DeviceState *device)
{
    TestCcfState *s=TEST_CCF(device);sony_ccf_init(&s->ccf);sony_pcie_scu_init(&s->wrapper);synchronize(s);
}
static void realize_device(DeviceState *device,Error **errp)
{
    static const uint64_t bases[]={0xf1388000,0xf1388300,0xf11e0380,0xf1160380,
        0xf11a0380,0xf1220380,0xf1120380};
    TestCcfState *s=TEST_CCF(device);reset_device(device);
    for(unsigned i=0;i<7;i++) {
        TestCcfRegion *r=&s->regions[i];r->owner=s;r->base=bases[i];r->index=i;
        char name[48];snprintf(name,sizeof name,"test-pcie-scu-region%u",i);
        memory_region_init_io(&r->mr,OBJECT(device),&ops,r,name,i==0?0x300:i==1?0x80:4);
        sysbus_init_mmio(SYS_BUS_DEVICE(device),&r->mr);
    }
    object_property_add_uint32_ptr(OBJECT(device),"hclk",&s->ccf.gates[8],OBJ_PROP_FLAG_READ);
    object_property_add_uint32_ptr(OBJECT(device),"apb-reset",&s->ccf.resets[1],OBJ_PROP_FLAG_READ);
    for(unsigned i=0;i<9;i++) {
        char name[24];snprintf(name,sizeof name,"gate%u",i);
        object_property_add_uint32_ptr(OBJECT(device),name,&s->ccf.gates[i],OBJ_PROP_FLAG_READ);
    }
    for(unsigned i=0;i<5;i++) {
        char name[24];snprintf(name,sizeof name,"wrapper%u",i);
        object_property_add_uint32_ptr(OBJECT(device),name,&s->wrapper.wrapper[i],OBJ_PROP_FLAG_READ);
    }
}
static void class_init(ObjectClass *klass,const void *data)
{
    DeviceClass *dc=DEVICE_CLASS(klass);dc->realize=realize_device;dc->user_creatable=false;
    device_class_set_legacy_reset(dc,reset_device);dc->desc="TEST SCU clock/reset CCF storage, no SoC host/PHY";
}
static const TypeInfo type_info={.name=TYPE_TEST_CCF,.parent=TYPE_SYS_BUS_DEVICE,.instance_size=sizeof(TestCcfState),.class_init=class_init};
static void register_types(void) {type_register_static(&type_info);}
type_init(register_types)
