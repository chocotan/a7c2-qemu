/* PCI binding tests use ordinary API mocks and the pinned public record. */
#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
static unsigned int read_control32(const volatile void *);
static void write_control32(volatile void *, unsigned int);
#define BACKUP_CONTROL_READ32(address) read_control32(address)
#define BACKUP_CONTROL_WRITE32(address, value) write_control32(address, value)
#include "client.c"

static union { u64 alignment; u8 bytes[0x500]; } device;
static u8 data[BACKUP_DATA_BYTES], controls[4096];
static u32 fault_case, get_calls, put_calls, enables, disables, maps, unmaps, registers, connects, master;
static u32 locked, freeze_failure;
static long register_result;
static void put64_test(u8 *p, u64 value) { for (u32 i=0;i<8;i++) p[i]=value>>(8*i); }
static void resource(u32 bar, u64 start, u64 size)
{
    u8 *p=device.bytes+0x368+bar*0x40;
    put64_test(p,start);put64_test(p+8,start+size-1);put64_test(p+0x18,0x200);
}
void *pci_get_domain_bus_and_slot(int domain,unsigned bus,unsigned function)
{ assert(domain==0 && bus==1 && function==0);get_calls++;return fault_case==1?NULL:device.bytes; }
int pci_enable_device(void *p) { assert(p==device.bytes);enables++;return fault_case==3?-5:0; }
void pci_disable_device(void *p) { assert(p==device.bytes);disables++; }
void pci_set_master(void *p) { assert(p==device.bytes && registers==1);master++; }
void pci_dev_put(void *p) { assert(p==device.bytes);put_calls++; }
int pci_bus_read_config_dword(void *bus,unsigned function,int offset,u32 *value)
{ assert(bus==&device && function==0 && offset==0);*value=fault_case==2?0x12345678:0x00051b36;return 0; }
void *pci_iomap_range(void *p,int bar,unsigned long offset,unsigned long size)
{
    assert(p==device.bytes && !offset && (bar==0 || bar==1));maps++;
    assert(size==(bar?4096:BACKUP_DATA_BYTES));
    if ((fault_case==4 && !bar) || (fault_case==5 && bar)) return NULL;
    return bar?controls:data;
}
void pci_iounmap(void *p,void *mapping)
{ assert(p==device.bytes && (mapping==controls || mapping==data));unmaps++; }
void pcidma_connect(u32 controller,u32 connected)
{ assert(controller==0 && connected==1 && registers==1 && master==1);connects++; }
void __memcpy_fromio(void *out,const volatile void *in,unsigned long size)
{
    const volatile u8 *p=in;
    u64 at=(u64)p;
    /* The real kernel copies a 4B tail bytewise; control registers must not use this API. */
    assert(at>=(u64)data && size<=sizeof(data) && at-(u64)data<=sizeof(data)-size);
    for (u64 i=0;i<size;i++) ((u8 *)out)[i]=p[i];
}
static unsigned int read_control32(const volatile void *address)
{
    u64 offset=(u64)address-(u64)controls;
    assert(offset<=32 && !(offset&3));
    return get32(controls+offset);
}
static void write_control32(volatile void *out,unsigned int command)
{
    assert(out==controls+24);
    if (command==1 && !locked) {
        if (freeze_failure) return;
        locked=1;data[9]=1;put32(controls+12,1);put32(controls+16,get32(controls+16)+1);
    } else if (command==2 && locked && get32(controls+32)==1) {
        locked=0;put32(controls+12,0);
    } else assert(0);
}
long osal_reg_public(long slot)
{ assert(slot==(long)&sender_handle && (!backup_model || maps==2));registers++;return register_result; }
long osal_valloc_msg_wait(u32 id,void **out,u32 size,u32 flags)
{ (void)id;(void)out;(void)size;(void)flags;assert(0);return -1; }
void osal_set_msg_src(void *p,u32 source) { ((u32 *)p)[-3]=source; }
u32 osal_get_msg_src(void *p) { return ((u32 *)p)[-3]; }
long osal_snd_msg(u32 id,void *p) { (void)id;(void)p;assert(0);return -1; }
long osal_free_msg(u32 id,void *p) { (void)id;(void)p;assert(0);return -1; }
long osal_dynamic_id(u32 type,u32 owner,unsigned long value)
{ (void)type;(void)owner;(void)value;assert(0);return -1; }
long osal_rcv_msg_tmo(u32 id,void **p,long t) { (void)id;(void)p;(void)t;assert(0);return -1; }
long osal_snd_sync_direct(u32 id,void *p) { (void)id;(void)p;assert(0);return -1; }
int printk(const char *format,...) { (void)format;return 0; }

int main(int argc,char **argv)
{
    assert(argc==3);
    FILE *seed=fopen(argv[2],"rb");assert(seed && !fseek(seed,0xed000,SEEK_SET));
    assert(fread(data,1,sizeof(data),seed)==sizeof(data) && fgetc(seed)==EOF);fclose(seed);
    backup_model=1;
    *(void **)(device.bytes+0x10)=&device;
    resource(0,0xe0000000,16UL*1024*1024);resource(1,0xe1000000,4096);
    put32(controls,0x42555031);put32(controls+4,1);put32(controls+8,BACKUP_DATA_BYTES);
    if (!strcmp(argv[1],"default-off")) {
        backup_model=0;assert(init_module()==0 && registers==1 && !get_calls && !maps && !backup_enabled);return 0;
    }
    if (!strcmp(argv[1],"normal")) {
        assert(init_module()==0 && backup_enabled && get_calls==1 && enables==1 && maps==2 && connects==1);
        assert(!unmaps && !put_calls && !disables);
        assert(backup_pci_freeze(NULL)==0 && locked && data[9]==1);
        u64 fingerprint;assert(!backup_read_record(1,BACKUP_FROZEN_FNV64,&fingerprint));
        assert(backup_pci_unlock(NULL)<0 && locked);
        put32(controls+32,1);assert(backup_pci_unlock(NULL)==0 && !locked && data[9]==1);
        return 0;
    }
    if (!strcmp(argv[1],"freeze-failure")) {
        assert(init_module()==0);freeze_failure=1;
        assert(backup_pci_freeze(NULL)<0 && !locked);return 0;
    }
    if (!strcmp(argv[1],"epoch-mismatch")) {
        assert(init_module()==0 && !backup_pci_freeze(NULL));
        put32(controls+32,1);put32(controls+16,get32(controls+16)+1);
        assert(backup_pci_unlock(NULL)<0 && locked);return 0;
    }
    fault_case=(u32)atoi(argv[1]);assert(fault_case>=1 && fault_case<=12);
    if (fault_case==6) put32(controls,0);
    if (fault_case==7) put32(controls+12,1);
    if (fault_case==8) data[BACKUP_DATA_BYTES-1]^=1;
    if (fault_case==9) register_result=-1018;
    if (fault_case==10) resource(0,0xe0000000,BACKUP_DATA_BYTES-1);
    if (fault_case==11) resource(1,0xe1000000,16);
    if (fault_case==12) put64_test(device.bytes+0x380,0x100);
    assert(init_module()!=0 && !backup_enabled && !connects && !master);
    assert(registers==(fault_case==9?1:0));
    assert(put_calls==(fault_case==1?0:1));
    assert(!backup_pdev && !backup_io && !backup_control && !backup_device_enabled);
    if (fault_case==4 || fault_case==5) assert(unmaps==1 && disables==1);
    if (fault_case>=6 && fault_case<=9) assert(unmaps==2 && disables==1);
    if (fault_case>=10) assert(!maps && !enables && !unmaps && !disables);
    return 0;
}
