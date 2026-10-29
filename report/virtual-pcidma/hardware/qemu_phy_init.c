/* SPDX-License-Identifier: GPL-2.0-or-later
 * Separate TEST-board functional SRAM-clear producer. NOT Sony silicon timing,
 * microcode execution, PHY calibration, lane/link training or a host model.
 * The original driver's upload is observable; lane-ready remains unavailable.
 */
#include "qemu/osdep.h"
#include "qapi/error.h"
#include "qemu/module.h"
#include "qemu/timer.h"
#include "qemu/bswap.h"
#include "hw/core/sysbus.h"
#include "hw/core/qdev-properties.h"
#include "hw/pci/pci_device.h"
#include "system/address-spaces.h"
#include "ccf.h"
#include "phy_clear_job.h"
#include "phy_calib.h"

#define TYPE_PHY_INIT "a7c2-test-scu-phy-init"
OBJECT_DECLARE_SIMPLE_TYPE(PhyInitState, PHY_INIT)
typedef struct InitRegion {MemoryRegion mr;PhyInitState *owner;unsigned index;uint64_t base;} InitRegion;
struct PhyInitState {
    SysBusDevice parent_obj;
    struct sony_ccf_state ccf;
    struct sony_phy_clear_job job;
    InitRegion regions[13];
    QEMUTimer *timer;
    uint32_t wrapper[5],control,powerdown,core_control,boost;
    uint32_t sideband_int[2]; /* W+20274/20278 enables; pinned masks 0x78ffff/0x04000000 */
    uint32_t sideband_stat[2]; /* W+2026c/20270 status; no sideband event source modeled, stays 0 */
    uint32_t port_logic[3]; /* D+710 lane-mode mask 3f0000; D+80c width+speed 21f00; D+890 bit0 */
    uint32_t last_count,last_match,completed_jobs,last_clear_words,rejected_accesses,dbi_accesses;
    uint32_t ready_read_before_upload,apply_after_upload;
    struct sony_phy_calib calib;
    uint32_t lane_status,link_status;
    PCIDevice *port,*peer;
    uint32_t atu[8],write_enable,shadow_bar[2],msi_target[2],msi_ctrl[3],aux_clock;
    uint8_t last_bytes[SONY_PHY_SRAM_BYTES];
    char last_digest[65];
};
static bool all_inputs(PhyInitState *);
static void refresh(PhyInitState *s)
{
    sony_phy_clear_inputs(&s->job,s->ccf.gates[8],s->ccf.resets[1],!(s->control&1));
    /* Explicit TEST policy: calibration requires the AUTHENTIC table applied,
     * IDDQ cleared and inputs held; LTSSM + present TEST peer only arm link
     * after calibration. Nothing here is silicon calibration/training. */
    bool applied=s->job.storage.apply_seen && !s->job.storage.failed &&
        s->job.storage.count==SONY_PHY_SRAM_WORDS && s->last_match==1;
    sony_phy_calib_inputs(&s->calib,applied,!(s->powerdown&(UINT32_C(1)<<29)),
        all_inputs(s),(s->core_control&4)!=0,true);
    s->lane_status=sony_phy_calib_lane_status(&s->calib);
    s->link_status=sony_phy_calib_link_status(&s->calib);
    if(!s->timer)return;
    if(s->job.phase==SONY_CLEAR_RUNNING || sony_phy_calib_busy(&s->calib)) {
        if(!timer_pending(s->timer))timer_mod(s->timer,qemu_clock_get_ns(QEMU_CLOCK_VIRTUAL)+1000);
    } else timer_del(s->timer);
}
static void init_tick(void *opaque)
{
    PhyInitState *s=opaque;
    if(s->job.phase==SONY_CLEAR_RUNNING) {
        sony_phy_clear_step(&s->job,64); /* Explicit TEST throughput, 64 halfwords/us. */
        if(sony_phy_clear_complete(&s->job)) {s->completed_jobs++;s->last_clear_words=s->job.cleared;}
    }
    sony_phy_calib_tick(&s->calib);
    refresh(s);
}
static bool apb(PhyInitState *s,unsigned port)
{
    static const unsigned clock[]={1,7,13,19,25},reset[]={3,11,7,15,19};
    return (s->ccf.gates[8]&(1u<<clock[port])) && !(s->ccf.resets[1]&(1u<<reset[port]));
}
static bool all_inputs(PhyInitState *s)
{
    return (s->ccf.gates[8]&0x3e)==0x3e && !(s->ccf.resets[1]&15) && !(s->control&1);
}
/* Real DBI window per the 290-pin original whitelist: config alias below
 * 0x700 with RO-write gating, 8bc write-enable, viewport 900-91c, MSI target
 * 820/824, AUX b40, shadow BARs 100010/100014. Unmodeled offsets reject. */
static MemTxResult dbi_read(PhyInitState *s,hwaddr offset,uint64_t *value,unsigned size)
{
    s->dbi_accesses++;
    if(offset==0x8bc) {
        if(size!=4)goto reject;
        *value=s->write_enable;return MEMTX_OK;
    }
    if(offset>=0x900 && offset<0x920) {
        if(size!=4 || offset&3)goto reject;
        *value=s->atu[(offset-0x900)/4];return MEMTX_OK;
    }
    if(offset==0x820 || offset==0x824) {
        if(size!=4)goto reject;
        *value=s->msi_target[(offset-0x820)/4];return MEMTX_OK;
    }
    /* MSI INT0 enable/mask/status 828/82c/830: no MSI source in this profile,
     * status reads stay 0 so dw_handle_msi_irq skips dispatch; storage accepts
     * the clear-back write pattern. */
    if(offset==0x828 || offset==0x82c || offset==0x830) {
        if(size!=4)goto reject;
        *value=s->msi_ctrl[(offset-0x828)/4];return MEMTX_OK;
    }
    if(offset==0xb40) {
        if(size!=4)goto reject;
        *value=s->aux_clock;return MEMTX_OK;
    }
    if(offset==0x100010 || offset==0x100014) {
        if(size!=4)goto reject;
        *value=s->shadow_bar[(offset-0x100010)/4];return MEMTX_OK;
    }
    /* Port Logic registers accessed via DBI in the original setup path. */
    if(offset==0x710 || offset==0x80c || offset==0x890) {
        if(size!=4)goto reject;
        unsigned i=offset==0x710?0:offset==0x80c?1:2;
        *value=s->port_logic[i];return MEMTX_OK;
    }
    if(offset<0x700 && s->port && offset+size<=pci_config_size(s->port)) {
        *value=s->port->config_read(s->port,offset,size);return MEMTX_OK;
    }
reject:s->rejected_accesses++;return MEMTX_DECODE_ERROR;
}
static MemTxResult dbi_write(PhyInitState *s,hwaddr offset,uint64_t value,unsigned size)
{
    s->dbi_accesses++;
    if(!size || size>4 || value>>(size*8))goto reject;
    if(offset==0x8bc) {
        if(size!=4 || value&~UINT64_C(1))goto reject;
        s->write_enable=(uint32_t)value;return MEMTX_OK;
    }
    if(offset>=0x900 && offset<0x920) {
        if(size!=4 || offset&3)goto reject;
        s->atu[(offset-0x900)/4]=(uint32_t)value;return MEMTX_OK;
    }
    if(offset==0x820 || offset==0x824) {
        if(size!=4)goto reject;
        s->msi_target[(offset-0x820)/4]=(uint32_t)value;return MEMTX_OK;
    }
    if(offset==0x828 || offset==0x82c || offset==0x830) {
        if(size!=4)goto reject;
        s->msi_ctrl[(offset-0x828)/4]=(uint32_t)value;return MEMTX_OK;
    }
    if(offset==0xb40) {
        if(size!=4)goto reject;
        s->aux_clock=(uint32_t)value;return MEMTX_OK;
    }
    if(offset==0x100010 || offset==0x100014) {
        if(size!=4)goto reject;
        s->shadow_bar[(offset-0x100010)/4]=(uint32_t)value;return MEMTX_OK;
    }
    /* Port Logic: lane-mode mask 3f0000, width+speed 21f00, L1-timeout bit0. */
    if(offset==0x710 || offset==0x80c || offset==0x890) {
        if(size!=4)goto reject;
        static const uint32_t masks[3]={0x3f0000,0x21f00,1};
        unsigned i=offset==0x710?0:offset==0x80c?1:2;
        if(value&~(uint64_t)masks[i])goto reject;
        s->port_logic[i]=(uint32_t)value;return MEMTX_OK;
    }
    if(offset<0x700 && s->port && offset+size<=pci_config_size(s->port)) {
        /* Original RO-write license: DBI 8bc bit0 AND wrapper bit6 clear.
         * Open BOTH wmask and w1cmask: pci_default_write_config asserts they
         * never overlap (command/status dword 0x004 mixes RW and W1C bytes). */
        bool unlocked=s->write_enable && !(s->wrapper[0]&0x40);
        uint8_t saved[4],saved_w1c[4];
        if(unlocked) {
            memcpy(saved,s->port->wmask+offset,size);
            memcpy(saved_w1c,s->port->w1cmask+offset,size);
            memset(s->port->wmask+offset,0xff,size);
            memset(s->port->w1cmask+offset,0,size);
        }
        s->port->config_write(s->port,offset,value,size);
        if(unlocked) {
            memcpy(s->port->wmask+offset,saved,size);
            memcpy(s->port->w1cmask+offset,saved_w1c,size);
        }
        return MEMTX_OK;
    }
reject:s->rejected_accesses++;return MEMTX_DECODE_ERROR;
}
/* CFG0/CFG1 downstream windows via viewport region1 (type 4/5). Absent BDF
 * reads return all-ones like a real host completing with no device. */
static MemTxResult cfg_access(PhyInitState *s,hwaddr offset,uint64_t *value,bool wr,
                              uint64_t wval,unsigned size,unsigned want_type)
{
    if(!size || size>4 || offset&(size-1)) {s->rejected_accesses++;return MEMTX_DECODE_ERROR;}
    if(!(s->atu[2]&0x80000000) || (s->atu[1]&0x1f)!=want_type) {
        s->rejected_accesses++;return MEMTX_DECODE_ERROR;
    }
    uint32_t target=s->atu[6];
    unsigned bus=(target>>24)&0xff,slot=(target>>19)&0x1f,fn=(target>>16)&7;
    unsigned reg=offset&0xfff;
    PCIDevice *pdev=(bus==1 && slot==0 && fn==0)?s->peer:NULL;
    if(!pdev || reg+size>pci_config_size(pdev)) {
        if(wr)return MEMTX_OK;
        *value=size==4?UINT32_MAX:size==2?UINT16_MAX:UINT8_MAX;return MEMTX_OK;
    }
    if(wr)pdev->config_write(pdev,reg,wval,size);
    else *value=pdev->config_read(pdev,reg,size);
    return MEMTX_OK;
}
static void apply_payload(PhyInitState *s)
{
    s->last_count=(uint32_t)s->job.storage.count;s->last_match=0;s->last_digest[0]=0;
    if(sony_phy_sram_apply_requested(&s->job.storage) && all_inputs(s) &&
       sony_phy_sram_export_le(&s->job.storage,s->last_bytes,sizeof s->last_bytes)) {
        char *digest=g_compute_checksum_for_data(G_CHECKSUM_SHA256,s->last_bytes,sizeof s->last_bytes);
        g_strlcpy(s->last_digest,digest,sizeof s->last_digest);g_free(digest);
        s->last_match=!strcmp(s->last_digest,"6133a8e7fb95e2ac83119517c00a306d485dcf3bf4afd814411317af64439f95");
    }
}
static MemTxResult read_register(void *opaque,hwaddr offset,uint64_t *value,unsigned size,MemTxAttrs attrs)
{
    InitRegion *r=opaque;PhyInitState *s=r->owner;uint64_t address=r->base+offset;uint32_t result;
    if(r->index==10) {
        if(size>8 || offset>sizeof s->last_bytes || size>sizeof s->last_bytes-offset)goto reject;
        *value=0;for(unsigned i=0;i<size;i++)*value|=(uint64_t)s->last_bytes[offset+i]<<(8*i);
        return MEMTX_OK;
    }
    if(r->index==9)return dbi_read(s,offset,value,size);
    if(r->index==11 || r->index==12)return cfg_access(s,offset,value,false,0,size,r->index==12?5:4);
    if(size!=4 || address&3)goto reject;
    if(r->index<2) {
        if(!sony_ccf_read(&s->ccf,address,size,&result))goto reject;
        *value=result;return MEMTX_OK;
    }
    if(r->index<=6) {
        unsigned i=r->index-2;if(!apb(s,i))goto reject;
        *value=s->wrapper[i];return MEMTX_OK;
    }
    offset=address-0xf11c0000;
    if(!apb(s,0))goto reject;
    if(offset>=0x18000 && offset<0x1c000) {
        if(!all_inputs(s))goto reject;
        *value=s->job.storage.words[(offset-0x18000)/4];return MEMTX_OK;
    }
    switch(offset) {
    case 0x3c:*value=s->boost;return MEMTX_OK;
    case 0x20018:*value=s->powerdown;return MEMTX_OK;
    case 0x200ac:
        *value=s->control|(sony_phy_clear_complete(&s->job)?4:0);
        /* Native proof that the original poll observed DONE before any table write. */
        if((*value&4) && !s->job.storage.count)s->ready_read_before_upload=1;
        return MEMTX_OK;
    case 0x201ac:*value=s->core_control;return MEMTX_OK;
    case 0x201b8:*value=sony_phy_calib_link_status(&s->calib);return MEMTX_OK; /* TEST functional link only; real training unmodeled. */
    case 0x20274:case 0x20278:*value=s->sideband_int[(offset-0x20274)/4];return MEMTX_OK;
    /* Status: the TEST model produces no sideband events; the only evidenced
     * write is the clear-back of the observed value (dw_pcie_clear_Interrupt*). */
    case 0x2026c:case 0x20270:*value=s->sideband_stat[(offset<0x20270)?0:1];return MEMTX_OK;
    case 0x2038c:
        if((s->wrapper[0]&0x1f0000)!=0x1f0000)goto reject;
        *value=sony_phy_calib_lane_status(&s->calib);return MEMTX_OK;
    default:break;
    }
reject:s->rejected_accesses++;return MEMTX_DECODE_ERROR;
}
static MemTxResult write_register(void *opaque,hwaddr offset,uint64_t value,unsigned size,MemTxAttrs attrs)
{
    InitRegion *r=opaque;PhyInitState *s=r->owner;uint64_t address=r->base+offset;
    if(r->index==9)return dbi_write(s,offset,value,size);
    if(r->index==11 || r->index==12)return cfg_access(s,offset,NULL,true,value,size,r->index==12?5:4);
    if(r->index==10) {s->rejected_accesses++;return MEMTX_DECODE_ERROR;}
    if(size!=4 || address&3 || value>UINT32_MAX)goto reject;
    if(r->index<2) {
        if(!sony_ccf_write(&s->ccf,address,size,(uint32_t)value))goto reject;
        refresh(s);return MEMTX_OK;
    }
    if(r->index<=6) {
        unsigned i=r->index-2;uint32_t mask=i==0?0x1f0057:16;
        if(!apb(s,i) || value&~(uint64_t)mask)goto reject;
        s->wrapper[i]=(uint32_t)value;return MEMTX_OK;
    }
    offset=address-0xf11c0000;if(!apb(s,0))goto reject;
    if(offset>=0x18000 && offset<0x1c000) {
        if(!all_inputs(s) || !sony_phy_clear_complete(&s->job) ||
           !sony_phy_sram_write(&s->job.storage,(uint32_t)offset,size,(uint32_t)value))goto reject;
        return MEMTX_OK;
    }
    switch(offset) {
    case 0x3c:if(value&~UINT64_C(0x3c0))goto reject;s->boost=(uint32_t)value;refresh(s);return MEMTX_OK;
    case 0x20018:if(value&~(UINT64_C(1)<<29))goto reject;s->powerdown=(uint32_t)value;refresh(s);return MEMTX_OK;
    case 0x200ac:
        if(value&~UINT64_C(7))goto reject;
        s->control=(uint32_t)value&3; /* Software echo of readonly bit2 never sets readiness. */
        refresh(s);
        if((value&2) && s->job.storage.count==SONY_PHY_SRAM_WORDS && sony_phy_clear_complete(&s->job))
            s->apply_after_upload=1;
        if(value&2)apply_payload(s);return MEMTX_OK;
    case 0x201ac:
        /* Bits 7:4 are the device-mode field: original dw_pcie_set_Mode
         * (0x246b60..0x246bc4) does (old & ~0xf0) | (mode<<4), RC=4 -> 0x40.
         * bit10 APP_CLK_REQ_N, bit2 LTSSM enable. Setting LTSSM still never
         * fabricates link: W+201b8 stays 0. */
        if(value&~UINT64_C(0x4f4))goto reject;s->core_control=(uint32_t)value;refresh(s);return MEMTX_OK;
    case 0x20274:case 0x20278: {
        /* Pinned masks from 60-pin contract (246a20/246a88 clear-reread-set). */
        uint32_t mask=offset==0x20274?0x78ffff:0x04000000;
        if(value&~(uint64_t)mask)goto reject;
        s->sideband_int[(offset-0x20274)/4]=(uint32_t)value;return MEMTX_OK;
    }
    case 0x2026c:case 0x20270:
        s->sideband_stat[(offset<0x20270)?0:1]=(uint32_t)value;return MEMTX_OK;
    default:break;
    }
    goto reject;
reject:s->rejected_accesses++;return MEMTX_DECODE_ERROR;
}
static const MemoryRegionOps ops={.read_with_attrs=read_register,.write_with_attrs=write_register,
    .endianness=DEVICE_LITTLE_ENDIAN,.valid={.min_access_size=4,.max_access_size=4,.unaligned=false},
    .impl={.min_access_size=4,.max_access_size=4}};
static const MemoryRegionOps observe_ops={.read_with_attrs=read_register,.write_with_attrs=write_register,
    .endianness=DEVICE_LITTLE_ENDIAN,.valid={.min_access_size=1,.max_access_size=8,.unaligned=true},
    .impl={.min_access_size=1,.max_access_size=8}};
/* DBI and CFG windows accept the original 8/16/32-bit accesses. */
static const MemoryRegionOps wide_ops={.read_with_attrs=read_register,.write_with_attrs=write_register,
    .endianness=DEVICE_LITTLE_ENDIAN,.valid={.min_access_size=1,.max_access_size=4,.unaligned=false},
    .impl={.min_access_size=1,.max_access_size=4}};
static char *digest_property(Object *obj,Error **errp) {return g_strdup(PHY_INIT(obj)->last_digest);}
static void reset_device(DeviceState *device)
{
    PhyInitState *s=PHY_INIT(device);if(s->timer)timer_del(s->timer);
    sony_ccf_init(&s->ccf);s->ccf.resets[1]|=7; /* Explicit TEST cold-powerup policy. */
    sony_phy_clear_reset(&s->job);sony_phy_calib_reset(&s->calib);memset(s->wrapper,0,sizeof s->wrapper);
    s->control=1;s->powerdown=1u<<29;s->core_control=s->boost=0;memset(s->sideband_int,0,sizeof s->sideband_int);memset(s->sideband_stat,0,sizeof s->sideband_stat);
    memset(s->port_logic,0,sizeof s->port_logic);
    s->last_count=s->last_match=s->completed_jobs=s->last_clear_words=s->rejected_accesses=s->dbi_accesses=0;
    s->ready_read_before_upload=s->apply_after_upload=0;
    memset(s->atu,0,sizeof s->atu);s->write_enable=0;memset(s->shadow_bar,0,sizeof s->shadow_bar);
    memset(s->msi_target,0,sizeof s->msi_target);s->aux_clock=0;memset(s->msi_ctrl,0,sizeof s->msi_ctrl);
    s->last_digest[0]=0;memset(s->last_bytes,0,sizeof s->last_bytes);refresh(s);
}
static void realize_device(DeviceState *device,Error **errp)
{
    static const uint64_t bases[]={0xf1388000,0xf1388300,0xf11e0380,0xf1160380,0xf11a0380,
        0xf1220380,0xf1120380,0xf11c0000,0xf11e0384,0xf7000000,0x602000000,0xdffc0000,0xdffd0000};
    static const uint64_t sizes[]={0x300,0x80,4,4,4,4,4,0x20380,0x1fc7c,0x380000,0x2000,0x10000,0x10000};
    PhyInitState *s=PHY_INIT(device);s->timer=timer_new_ns(QEMU_CLOCK_VIRTUAL,init_tick,s);reset_device(device);
    for(unsigned i=0;i<13;i++) {
        InitRegion *r=&s->regions[i];r->owner=s;r->index=i;r->base=bases[i];char name[48];
        snprintf(name,sizeof name,"test-phy-init-region%u",i);
        const MemoryRegionOps *selected=i==10?&observe_ops:(i==9 || i>=11)?&wide_ops:&ops;
        memory_region_init_io(&r->mr,OBJECT(device),selected,r,name,sizes[i]);
        sysbus_init_mmio(SYS_BUS_DEVICE(device),&r->mr);
    }
    object_property_add_uint32_ptr(OBJECT(device),"hclk",&s->ccf.gates[8],OBJ_PROP_FLAG_READ);
    object_property_add_uint32_ptr(OBJECT(device),"reset1",&s->ccf.resets[1],OBJ_PROP_FLAG_READ);
    object_property_add_uint32_ptr(OBJECT(device),"last-accepted-words",&s->last_count,OBJ_PROP_FLAG_READ);
    object_property_add_uint32_ptr(OBJECT(device),"last-image-matches",&s->last_match,OBJ_PROP_FLAG_READ);
    object_property_add_uint32_ptr(OBJECT(device),"completed-clear-jobs",&s->completed_jobs,OBJ_PROP_FLAG_READ);
    object_property_add_uint32_ptr(OBJECT(device),"last-cleared-words",&s->last_clear_words,OBJ_PROP_FLAG_READ);
    object_property_add_uint32_ptr(OBJECT(device),"ready-read-before-upload",&s->ready_read_before_upload,OBJ_PROP_FLAG_READ);
    object_property_add_uint32_ptr(OBJECT(device),"apply-after-upload",&s->apply_after_upload,OBJ_PROP_FLAG_READ);
    object_property_add_uint32_ptr(OBJECT(device),"lane-status",&s->lane_status,OBJ_PROP_FLAG_READ);
    object_property_add_uint32_ptr(OBJECT(device),"link-status",&s->link_status,OBJ_PROP_FLAG_READ);
    object_property_add_uint32_ptr(OBJECT(device),"rejected-accesses",&s->rejected_accesses,OBJ_PROP_FLAG_READ);
    object_property_add_uint32_ptr(OBJECT(device),"dbi-accesses",&s->dbi_accesses,OBJ_PROP_FLAG_READ);
    object_property_add_str(OBJECT(device),"last-input-sha256",digest_property,NULL);
}
static const Property properties[]={
    DEFINE_PROP_LINK("port",PhyInitState,port,TYPE_PCI_DEVICE,PCIDevice *),
    DEFINE_PROP_LINK("peer",PhyInitState,peer,TYPE_PCI_DEVICE,PCIDevice *),
};
static void class_init(ObjectClass *klass,const void *data)
{
    DeviceClass *dc=DEVICE_CLASS(klass);dc->realize=realize_device;dc->user_creatable=false;
    device_class_set_legacy_reset(dc,reset_device);device_class_set_props(dc,properties);
    dc->desc="TEST timed SRAM clearing/upload; lane/link are functional policy, not silicon";
}
static const TypeInfo type_info={.name=TYPE_PHY_INIT,.parent=TYPE_SYS_BUS_DEVICE,.instance_size=sizeof(PhyInitState),.class_init=class_init};
static void register_types(void) {type_register_static(&type_info);}
type_init(register_types)
