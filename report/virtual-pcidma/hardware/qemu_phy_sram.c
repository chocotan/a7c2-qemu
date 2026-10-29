/* SPDX-License-Identifier: GPL-2.0-or-later
 * TEST SRAM data consumer only. NEVER advertises INIT_DONE, lane or link ready.
 * Readback is a TEST observation extension, not a Sony SRAM read ABI.
 */
#include "qemu/osdep.h"
#include "qapi/error.h"
#include "qemu/module.h"
#include "qemu/bswap.h"
#include "hw/core/sysbus.h"
#include "system/address-spaces.h"
#include "phy_sram.h"

#define TYPE_TEST_PHY_SRAM "a7c2-test-phy-sram"
OBJECT_DECLARE_SIMPLE_TYPE(TestPhySram, TEST_PHY_SRAM)
struct TestPhySram {
    SysBusDevice parent_obj;
    MemoryRegion data,control;
    struct sony_phy_sram storage;
    uint8_t exported[SONY_PHY_SRAM_BYTES];
    uint32_t control_value,accepted_words,image_matches,apply_seen;
    char digest[65];
};
static bool prerequisites(void)
{
    uint8_t clock[4],reset[4];
    if(address_space_read(&address_space_memory,0xf1388080,MEMTXATTRS_UNSPECIFIED,clock,4)!=MEMTX_OK ||
       address_space_read(&address_space_memory,0xf1388310,MEMTXATTRS_UNSPECIFIED,reset,4)!=MEMTX_OK)return false;
    return (ldl_le_p(clock)&0x3e)==0x3e && !(ldl_le_p(reset)&0xf);
}
static MemTxResult data_read(void *opaque,hwaddr offset,uint64_t *value,unsigned size,MemTxAttrs attrs)
{
    TestPhySram *s=TEST_PHY_SRAM(opaque);
    if(size!=4 || offset&3 || offset>=0x4000 || !prerequisites())return MEMTX_DECODE_ERROR;
    *value=s->storage.words[offset/4];return MEMTX_OK;
}
static MemTxResult data_write(void *opaque,hwaddr offset,uint64_t value,unsigned size,MemTxAttrs attrs)
{
    TestPhySram *s=TEST_PHY_SRAM(opaque);
    if(!prerequisites()) {s->storage.failed=true;s->image_matches=0;s->digest[0]=0;return MEMTX_DECODE_ERROR;}
    if(value>UINT32_MAX || !sony_phy_sram_write(&s->storage,SONY_PHY_SRAM_OFFSET+(uint32_t)offset,size,(uint32_t)value)) {
        s->image_matches=0;s->digest[0]=0;
        return MEMTX_DECODE_ERROR;
    }
    s->accepted_words=(uint32_t)s->storage.count;return MEMTX_OK;
}
static MemTxResult control_read(void *opaque,hwaddr offset,uint64_t *value,unsigned size,MemTxAttrs attrs)
{
    if(offset || size!=4)return MEMTX_DECODE_ERROR;
    *value=TEST_PHY_SRAM(opaque)->control_value;return MEMTX_OK;
}
static MemTxResult control_write(void *opaque,hwaddr offset,uint64_t value,unsigned size,MemTxAttrs attrs)
{
    TestPhySram *s=TEST_PHY_SRAM(opaque);
    if(offset || size!=4 || value&~UINT64_C(3))return MEMTX_DECODE_ERROR;
    s->control_value=(uint32_t)value;
    if(value&2) {
        s->apply_seen=1;s->image_matches=0;s->digest[0]=0;
        bool complete=sony_phy_sram_apply_requested(&s->storage);
        if(complete && prerequisites() && !(value&1) &&
           sony_phy_sram_export_le(&s->storage,s->exported,sizeof s->exported)) {
            char *digest=g_compute_checksum_for_data(G_CHECKSUM_SHA256,s->exported,sizeof s->exported);
            g_strlcpy(s->digest,digest,sizeof s->digest);g_free(digest);
            s->image_matches=!strcmp(s->digest,"6133a8e7fb95e2ac83119517c00a306d485dcf3bf4afd814411317af64439f95");
        }
    }
    /* Bit2 stays zero: content completeness never fabricates PHY readiness. */
    return MEMTX_OK;
}
static const MemoryRegionOps data_ops={.read_with_attrs=data_read,.write_with_attrs=data_write,
    .endianness=DEVICE_LITTLE_ENDIAN,.valid={.min_access_size=4,.max_access_size=4,.unaligned=false},
    .impl={.min_access_size=4,.max_access_size=4}};
static const MemoryRegionOps control_ops={.read_with_attrs=control_read,.write_with_attrs=control_write,
    .endianness=DEVICE_LITTLE_ENDIAN,.valid={.min_access_size=4,.max_access_size=4,.unaligned=false},
    .impl={.min_access_size=4,.max_access_size=4}};
static char *digest_property(Object *obj,Error **errp) {return g_strdup(TEST_PHY_SRAM(obj)->digest);}
static void reset_device(DeviceState *device)
{
    TestPhySram *s=TEST_PHY_SRAM(device);sony_phy_sram_clear_storage(&s->storage);
    s->control_value=s->accepted_words=s->image_matches=s->apply_seen=0;s->digest[0]=0;
}
static void realize_device(DeviceState *device,Error **errp)
{
    TestPhySram *s=TEST_PHY_SRAM(device);reset_device(device);
    memory_region_init_io(&s->data,OBJECT(device),&data_ops,s,"test-phy-sram-data",0x4000);
    memory_region_init_io(&s->control,OBJECT(device),&control_ops,s,"test-phy-sram-control",4);
    sysbus_init_mmio(SYS_BUS_DEVICE(device),&s->data);sysbus_init_mmio(SYS_BUS_DEVICE(device),&s->control);
    object_property_add_uint32_ptr(OBJECT(device),"accepted-words",&s->accepted_words,OBJ_PROP_FLAG_READ);
    object_property_add_uint32_ptr(OBJECT(device),"image-matches",&s->image_matches,OBJ_PROP_FLAG_READ);
    object_property_add_uint32_ptr(OBJECT(device),"apply-seen",&s->apply_seen,OBJ_PROP_FLAG_READ);
    object_property_add_str(OBJECT(device),"input-sha256",digest_property,NULL);
}
static void class_init(ObjectClass *klass,const void *data)
{
    DeviceClass *dc=DEVICE_CLASS(klass);dc->realize=realize_device;dc->user_creatable=false;
    device_class_set_legacy_reset(dc,reset_device);dc->desc="TEST PHY SRAM data/authentication only, no ready";
}
static const TypeInfo type_info={.name=TYPE_TEST_PHY_SRAM,.parent=TYPE_SYS_BUS_DEVICE,.instance_size=sizeof(TestPhySram),.class_init=class_init};
static void register_types(void) {type_register_static(&type_info);}
type_init(register_types)
