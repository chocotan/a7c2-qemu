/* SPDX-License-Identifier: MIT
 * Experimental unity RC backend. Packing/filter fidelity is unverified.
 * Completion is published only after a bounded real RAM-to-RAM operation.
 */
#include "qemu/osdep.h"
#include "qapi/error.h"
#include "qemu/module.h"
#include "qemu/log.h"
#include "hw/core/sysbus.h"
#include "hw/core/qdev-properties.h"
#include "hw/core/irq.h"
#include "system/address-spaces.h"
#include "rc-reference.h"

#define TYPE_SONY_RC "sony-rc-reference"
OBJECT_DECLARE_SIMPLE_TYPE(SonyRCState, SONY_RC)
struct SonyRCState {
    SysBusDevice parent_obj;
    MemoryRegion mmio;
    uint32_t registers[0x10000/4];
    uint32_t engine;
    qemu_irq irq;
};

static void update_irq(SonyRCState *s)
{
    qemu_set_irq(s->irq, !!(s->registers[0x1000/4]&s->registers[0x1008/4]&0xff));
}

static void *map_ram(uint64_t physical,hwaddr *length,bool write)
{
    hwaddr translated,available=*length;
    MemoryRegion *region=address_space_translate(&address_space_memory,physical,&translated,
        &available,write,MEMTXATTRS_UNSPECIFIED);
    if (!region || !memory_region_is_ram(region) || memory_region_is_rom(region) ||
        available<*length) return NULL;
    return address_space_map(&address_space_memory,physical,length,write,MEMTXATTRS_UNSPECIFIED);
}

static uint64_t fnv(const void *pointer,size_t bytes)
{
    const uint8_t *p=pointer;
    uint64_t value=UINT64_C(0xcbf29ce484222325);
    for (size_t i=0;i<bytes;i++) value=(value^p[i])*UINT64_C(0x100000001b3);
    return value;
}

static void execute(SonyRCState *s)
{
    struct rc_reference_request request;
    if (rc_reference_decode(s->registers+0x2000/4,s->registers+0x1200/4,
            s->registers+0x1280/4,s->registers+0xd100/4,s->registers+0xc100/4,&request)) {
        fprintf(stderr,"SONY_RC_REJECT engine=%u reason=unsupported-register-contract\n",s->engine);
        return;
    }
    hwaddr bytes=request.input.capacity,in_length=bytes,out_length=bytes;
    void *input=map_ram(request.source,&in_length,false);
    void *output=map_ram(request.destination,&out_length,true);
    int result=-1;
    bool copied=false;
    uint64_t source_digest=0,output_digest=0;
    if (input && output && in_length>=bytes && out_length>=bytes) {
        source_digest=fnv(input,bytes);
        result=rc_identity_copy(&request.input,input,&request.output,output);
        copied=!result;
        if (!result) output_digest=fnv(output,bytes);
        if (source_digest!=output_digest) result=-1;
    }
    if (input) address_space_unmap(&address_space_memory,input,in_length,false,in_length>=bytes?bytes:0);
    if (output) address_space_unmap(&address_space_memory,output,out_length,true,copied?bytes:0);
    if (result) {
        fprintf(stderr,"SONY_RC_REJECT engine=%u reason=RAM-range-or-copy-failure\n",s->engine);
        return;
    }
    g_autofree char *receipt=g_strdup_printf("SONY_RC_DATA engine=%u src=0x%"PRIx64" dst=0x%"PRIx64
        " bytes=%"PRIu64" source_fnv=%016"PRIx64" output_fnv=%016"PRIx64
        " backend=lane-preserving-unity-v1 silicon-packing=unverified\n",
        s->engine,request.source,request.destination,(uint64_t)bytes,source_digest,output_digest);
    fprintf(stderr,"%s",receipt);
    qemu_log_mask(LOG_GUEST_ERROR,"%s",receipt);
    /* Real DMA transactions have finished before normal channel status/IRQ. */
    s->registers[0x1200/4]&=~1u;
    s->registers[0x1280/4]&=~1u;
    s->registers[0x1000/4]|=0x11;
    update_irq(s);
}

static uint64_t rc_read(void *opaque,hwaddr offset,unsigned size)
{
    SonyRCState *s=opaque;
    return s->registers[offset/4];
}

static void rc_write(void *opaque,hwaddr offset,uint64_t value,unsigned size)
{
    SonyRCState *s=opaque;
    qemu_log_mask(LOG_GUEST_ERROR,"SONY_RC_MMIO_WR 0x%"PRIx64" = 0x%"PRIx64"\n",
        UINT64_C(0xf30a0000)+s->engine*0x10000+offset,value);
    if (offset==0x1000) s->registers[offset/4]&=~(uint32_t)value; /* Channel status W1C. */
    else s->registers[offset/4]=(uint32_t)value;
    if (offset==0x2000 && value==1) execute(s);
    if (offset==0x1000 || offset==0x1008) update_irq(s);
}

static const MemoryRegionOps rc_ops={.read=rc_read,.write=rc_write,
    .endianness=DEVICE_LITTLE_ENDIAN,.valid={.min_access_size=4,.max_access_size=4},
    .impl={.min_access_size=4,.max_access_size=4}};

static void rc_realize(DeviceState *dev,Error **errp)
{
    SonyRCState *s=SONY_RC(dev);
    if (s->engine>=6) { error_setg(errp,"Invalid RC engine index");return; }
    memory_region_init_io(&s->mmio,OBJECT(dev),&rc_ops,s,TYPE_SONY_RC,0x10000);
    sysbus_init_mmio(SYS_BUS_DEVICE(dev),&s->mmio);
    sysbus_init_irq(SYS_BUS_DEVICE(dev),&s->irq);
}
static const Property rc_props[]={DEFINE_PROP_UINT32("engine",SonyRCState,engine,0)};
static void rc_reset(DeviceState *dev)
{
    SonyRCState *s=SONY_RC(dev);
    memset(s->registers,0,sizeof s->registers);
    qemu_set_irq(s->irq,0);
}
static void rc_class_init(ObjectClass *klass,const void *data)
{
    DeviceClass *dc=DEVICE_CLASS(klass);
    dc->realize=rc_realize;
    device_class_set_legacy_reset(dc,rc_reset);
    device_class_set_props(dc,rc_props);
    dc->desc="Experimental RC unity backend; silicon packing/filter fidelity unverified";
}
static const TypeInfo rc_info={.name=TYPE_SONY_RC,.parent=TYPE_SYS_BUS_DEVICE,
    .instance_size=sizeof(SonyRCState),.class_init=rc_class_init};
static void register_types(void) { type_register_static(&rc_info); }
type_init(register_types)
