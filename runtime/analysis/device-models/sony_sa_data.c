/* SPDX-License-Identifier: MIT
 * Pinned reference conversion; optional explicit virtual completion protocol.
 */
#include "qemu/osdep.h"
#include "qapi/error.h"
#include "qemu/module.h"
#include "qemu/log.h"
#include "qemu/bswap.h"
#include "hw/core/sysbus.h"
#include "hw/core/qdev-properties.h"
#include "hw/core/irq.h"
#include "system/address-spaces.h"
#include "nv12-reference.h"
#include "sa-nv12-job.h"

#define TYPE_SONY_SA_DATA "sony-sa-nv12-data-only"
OBJECT_DECLARE_SIMPLE_TYPE(SonySADataState,SONY_SA_DATA)
struct SonySADataState {
    SysBusDevice parent_obj;MemoryRegion mmio;uint32_t registers[1024];unsigned gates;
    bool reference_completion;qemu_irq irq;
};

static void update_irq(SonySADataState *s)
{
    qemu_set_irq(s->irq,s->reference_completion &&
        (s->registers[0x104/4]&s->registers[0x108/4]&1));
}

static void *ram(uint64_t physical,hwaddr *length,bool write)
{
    hwaddr translated,available=*length;
    MemoryRegion *region=address_space_translate(&address_space_memory,physical,&translated,
        &available,write,MEMTXATTRS_UNSPECIFIED);
    if (!region || !memory_region_is_ram(region) || memory_region_is_rom(region) || available<*length)
        return NULL;
    return address_space_map(&address_space_memory,physical,length,write,MEMTXATTRS_UNSPECIFIED);
}

static int snapshot(uint64_t physical,void *destination,size_t bytes)
{
    hwaddr length=bytes;void *source=ram(physical,&length,false);
    if (!source) return -1;
    int result=length<bytes?-1:0;
    if (!result) memcpy(destination,source,bytes);
    address_space_unmap(&address_space_memory,source,length,false,!result?bytes:0);
    return result;
}

static void execute(SonySADataState *s)
{
    uint8_t parameters[512],table[352],program[0x1400];uint32_t p[128],t[88];
    g_autofree char *hash=NULL,*input_hash=NULL,*output_hash=NULL;
    g_autofree uint8_t *input=NULL,*output=NULL;
    if (s->reference_completion && (s->registers[0x104/4]&1)) goto reject;
    uint64_t parameter_pa=UINT64_C(0x400000000)+(uint64_t)s->registers[0x110/4]*4;
    uint64_t table_pa=UINT64_C(0x400000000)+(uint64_t)s->registers[0x114/4]*4;
    if (parameter_pa>UINT64_C(0x500000000)-512 || table_pa>UINT64_C(0x500000000)-352 ||
        snapshot(parameter_pa,parameters,sizeof parameters) || snapshot(table_pa,table,sizeof table)) goto reject;
    for (unsigned i=0;i<128;i++) p[i]=ldl_le_p(parameters+i*4);
    for (unsigned i=0;i<88;i++) t[i]=ldl_le_p(table+i*4);
    struct sa_nv12_job job;
    if (sa_nv12_job_decode(s->registers,p,t,&job) || snapshot(job.program,program,sizeof program)) goto reject;
    hash=g_compute_checksum_for_data(G_CHECKSUM_SHA256,program,sizeof program);
    if (strcmp(hash,"75c481ee17961521fd5cb2c41ab49fec79228839e47faba5d97f8ef59a5a8822")) goto reject;
    input=g_malloc(SA_NV12_SOURCE_BYTES);
    output=g_malloc(SA_NV12_OUTPUT_BYTES);
    if (snapshot(job.source,input,SA_NV12_SOURCE_BYTES) ||
        nv12_reference_convert(input,SA_NV12_SOURCE_BYTES,1920,1080,3840,output,SA_NV12_OUTPUT_BYTES)) goto reject;
    uint8_t check_parameters[512],check_table[352],check_program[0x1400];
    if (snapshot(job.parameters,check_parameters,sizeof check_parameters) ||
        snapshot(job.table,check_table,sizeof check_table) || snapshot(job.program,check_program,sizeof check_program) ||
        memcmp(parameters,check_parameters,sizeof parameters) || memcmp(table,check_table,sizeof table) ||
        memcmp(program,check_program,sizeof program)) goto reject;
    hwaddr length=SA_NV12_OUTPUT_BYTES;
    void *destination=ram(job.destination,&length,true);
    if (!destination) goto reject;
    if (length<SA_NV12_OUTPUT_BYTES) {
        address_space_unmap(&address_space_memory,destination,length,true,0);goto reject;
    }
    memcpy(destination,output,SA_NV12_OUTPUT_BYTES);
    int differs=memcmp(destination,output,SA_NV12_OUTPUT_BYTES);
    address_space_unmap(&address_space_memory,destination,length,true,SA_NV12_OUTPUT_BYTES);
    if (differs) {
        qemu_log_mask(LOG_GUEST_ERROR,"SONY_SA_REFERENCE_OUTPUT_MISMATCH src=0x%"PRIx64
            " dst=0x%"PRIx64" bytes=%u output_written=1 completion_published=0\n",
            job.source,job.destination,SA_NV12_OUTPUT_BYTES);
        return;
    }
    input_hash=g_compute_checksum_for_data(G_CHECKSUM_SHA256,input,SA_NV12_SOURCE_BYTES);
    output_hash=g_compute_checksum_for_data(G_CHECKSUM_SHA256,output,SA_NV12_OUTPUT_BYTES);
    qemu_log_mask(LOG_GUEST_ERROR,"SONY_SA_REFERENCE_DATA%s src=0x%"PRIx64" dst=0x%"PRIx64
        " input_bytes=%u output_bytes=%u input_sha256=%s output_sha256=%s layout=YUYV-vmean-half-up"
        " silicon=unverified completion_published=%u\n",s->reference_completion?"":"_ONLY",
        job.source,job.destination,SA_NV12_SOURCE_BYTES,SA_NV12_OUTPUT_BYTES,input_hash,output_hash,
        (unsigned)s->reference_completion);
    if (s->reference_completion) {
        /* Virtual reference factor, not a recovered Sony hardware bit meaning. */
        s->registers[0x100/4]|=1;
        s->registers[0x104/4]|=1;
        update_irq(s);
    }
    return;
reject:
    qemu_log_mask(LOG_GUEST_ERROR,"SONY_SA_REFERENCE_REJECT output_written=0 completion_published=0\n");
}

static uint64_t sa_read(void *opaque,hwaddr offset,unsigned size)
{ return SONY_SA_DATA(opaque)->registers[offset/4]; }
static void sa_write(void *opaque,hwaddr offset,uint64_t value,unsigned size)
{
    SonySADataState *s=SONY_SA_DATA(opaque);
    if (offset==0x104 || offset==0x144 || offset==0x204) {
        s->registers[offset/4]&=~(uint32_t)value;
        s->registers[(offset-4)/4]&=~(uint32_t)value;
    }
    else s->registers[offset/4]=value;
    qemu_log_mask(LOG_GUEST_ERROR,"SONY_SA_MMIO_WR 0x%"PRIx64" = 0x%"PRIx64"\n",UINT64_C(0xf3170000)+offset,value);
    if (offset==0x104 || offset==0x108) update_irq(s);
    if (offset==0 || offset==4) {
        unsigned bit=1u<<(offset/4);
        if (value&1) s->gates|=bit;else s->gates&=~bit;
        if (s->gates==3) { s->gates=0;execute(s); }
    }
}
static const MemoryRegionOps sa_ops={.read=sa_read,.write=sa_write,.endianness=DEVICE_LITTLE_ENDIAN,
    .valid={.min_access_size=4,.max_access_size=4},.impl={.min_access_size=4,.max_access_size=4}};
static void sa_reset(DeviceState *dev)
{
    SonySADataState *s=SONY_SA_DATA(dev);memset(s->registers,0,sizeof s->registers);s->gates=0;
    qemu_set_irq(s->irq,0);
}
static void sa_realize(DeviceState *dev,Error **errp)
{
    SonySADataState *s=SONY_SA_DATA(dev);
    memory_region_init_io(&s->mmio,OBJECT(dev),&sa_ops,s,TYPE_SONY_SA_DATA,0x1000);
    sysbus_init_mmio(SYS_BUS_DEVICE(dev),&s->mmio);
    sysbus_init_irq(SYS_BUS_DEVICE(dev),&s->irq);
}
static const Property sa_props[]={DEFINE_PROP_BOOL("reference-completion",SonySADataState,reference_completion,false)};
static void sa_class_init(ObjectClass *klass,const void *data)
{
    DeviceClass *dc=DEVICE_CLASS(klass);dc->realize=sa_realize;
    device_class_set_legacy_reset(dc,sa_reset);
    device_class_set_props(dc,sa_props);
    dc->desc="Experimental pinned NV12 conversion; optional virtual completion factor";
}
static const TypeInfo sa_info={.name=TYPE_SONY_SA_DATA,.parent=TYPE_SYS_BUS_DEVICE,
    .instance_size=sizeof(SonySADataState),.class_init=sa_class_init};
static void register_types(void) { type_register_static(&sa_info); }
type_init(register_types)
