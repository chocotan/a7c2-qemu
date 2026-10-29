/* Host control/ABI fixture only: does not run Linux PCI core or QEMU. */
#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "client.c"
enum scenario { GOOD,EXISTING,MAP_FAIL,WRONG_ROOT,WRONG_CLASS,RESOURCE_FAIL,SCAN_FAIL,BAD_DOMAIN,NO_DEVICE,WRONG_ENDPOINT };
static enum scenario scenario;
static unsigned mapped,adds,free_lists,scans,sized,assigned,published,locked,pass,missing,blocked;
static unsigned char *config;
static _Alignas(8) unsigned char fake_bus[512];
static struct entry entries[2];
static void put32(unsigned off,u32 value) { memcpy(config+off,&value,4); }
void *udif_ioremap(void *resource)
{
    struct iomem *m=resource;assert(m==&ecam && m->physical==ECAM_PHYSICAL && m->size==ECAM_BYTES && !m->flags);
    mapped++;
    if (scenario==MAP_FAIL) return NULL;
    m->virtual=(u64)config;return config;
}
void *pci_find_bus(int domain,int bus) { assert(domain==0 && bus==0);return scenario==EXISTING?fake_bus:NULL; }
void pci_add_resource(struct list *head,struct resource *r)
{
    assert(head==&windows && adds<2 && (r==&bus_resource || r==&mem_resource));
    unsigned i=adds++;
    if (scenario==RESOURCE_FAIL && i==1) return;
    struct entry *e=entries+i;e->resource=r;e->offset=0;
    e->list.next=head;e->list.prev=head->prev;head->prev->next=&e->list;head->prev=&e->list;
}
void pci_free_resource_list(struct list *head)
{
    assert(head==&windows && !locked);free_lists++;head->next=head->prev=head;
}
void pci_lock_rescan_remove(void) { assert(!locked);locked=1; }
void pci_unlock_rescan_remove(void) { assert(locked);locked=0; }
void *pci_scan_root_bus(void *parent,int bus,struct pci_ops *ops,void *data,struct list *head)
{
    assert(!parent && !bus && ops==&sony_pci_ops && data==&context && head==&windows && locked);
    assert(resources_complete());scans++;
    assert(mem_resource.start==0x10000000 && mem_resource.end==0x1fffffff && mem_resource.flags==0x200);
    assert(bus_resource.start==0 && bus_resource.end==15 && bus_resource.flags==0x1000);
    assert(!ops->unused[0] && !ops->unused[1] && !ops->unused[2]);
    if (scenario==SCAN_FAIL) return NULL;
    head->next=head->prev=head; /* normal success transfers entry ownership */
    u32 value;assert(!ops->read(fake_bus,8,0,4,&value) && (value&0xffff)==0x1b36);
    assert(!ops->write(fake_bus,8,0x18,4,0x10100));
    assert(*(u32 *)(config+0x8018)==0x10100);
    return fake_bus;
}
void pci_bus_size_bridges(void *bus) { assert(bus==fake_bus && locked);sized++; }
void pci_bus_assign_resources(void *bus) { assert(bus==fake_bus && sized && locked);assigned++;put32(0x100010,0x11000000); }
void pci_bus_add_devices(void *bus) { assert(bus==fake_bus && assigned && !locked);published++; }
void *pci_get_domain_bus_and_slot(int domain,unsigned bus,unsigned devfn)
{ assert(domain==0 && bus==1 && devfn==0 && published);return scenario==NO_DEVICE?NULL:fake_bus+256; }
int printk(const char *format,...)
{
    if (strstr(format,"PCI_CORE_TEST_BLOCKED:")) blocked++;
    if (strstr(format,"PCI_CORE_TEST_ENUM_PASS:")) pass++;
    if (strstr(format,"PCI_CORE_TEST_ENDPOINT_MISSING:")) missing++;
    return 0;
}
static void run(enum scenario value)
{
    scenario=value;mapped=adds=free_lists=scans=sized=assigned=published=locked=pass=missing=0;
    ecam.virtual=0;context.bus=context.device=NULL;context.reads=context.writes=0;
    config=aligned_alloc(4096,ECAM_BYTES);assert(config);memset(config,0xff,ECAM_BYTES);
    memset(fake_bus,0,sizeof fake_bus);memset(entries,0,sizeof entries);
    put32(0x8000,value==WRONG_ROOT?0x12345678:0x000c1b36);
    put32(0x8008,value==WRONG_CLASS?0x02000000:0x06040000);
    put32(0x100000,value==WRONG_ENDPOINT?0x88881b36:0x00051b36);
    if (value==BAD_DOMAIN) *(int *)(fake_bus+0xe4)=1;
    assert(!sony_pci_core_prototype() && !locked);
    if (value==GOOD) assert(pass && scans==1 && sized==1 && assigned==1 && published==1 && context.device);
    else assert(!pass);
    if (value==EXISTING) assert(!mapped && !scans);
    if (value==MAP_FAIL || value==WRONG_ROOT || value==WRONG_CLASS) assert(!scans && !adds);
    if (value==RESOURCE_FAIL) assert(!scans && free_lists==1);
    if (value==SCAN_FAIL) assert(scans==1 && free_lists==1 && !sized && !published);
    if (value==BAD_DOMAIN) assert(scans==1 && !sized && !published && context.bus);
    if (value==NO_DEVICE || value==WRONG_ENDPOINT) assert(published && missing);
    if (ecam.virtual) {
        u32 out=0;
        put32(0x8004,0x11223344);
        assert(!sony_pci_config_read(fake_bus,8,4,1,&out) && out==0x44);
        assert(!sony_pci_config_read(fake_bus,8,6,2,&out) && out==0x1122);
        assert(!sony_pci_config_write(fake_bus,8,5,1,0xaa));
        assert(!sony_pci_config_write(fake_bus,8,6,2,0xbeef));
        assert(!sony_pci_config_read(fake_bus,8,4,4,&out) && out==0xbeefaa44);
        assert(sony_pci_config_read(NULL,0,0,4,&out)==0x86 && out==0xffffffffU);
        assert(sony_pci_config_read(fake_bus,0,4095,4,&out)==0x87);
        assert(sony_pci_config_write(fake_bus,0,3,2,0)==0x87);
        assert(sony_pci_config_write(fake_bus,256,0,4,0)==0x87);
        assert(sony_pci_config_read(fake_bus,0,-1,4,&out)==0x87);
        fake_bus[0xe0]=16;assert(sony_pci_config_read(fake_bus,0,0,4,&out)==0x87);fake_bus[0xe0]=0;
    }
    free(config);config=NULL;
}
int main(void)
{
    assert(!init_module() && blocked==1 && !mapped && !scans && !published);
    for (unsigned i=GOOD;i<=WRONG_ENDPOINT;i++) run((enum scenario)i);
    puts("PASS_HOST_CONTROL_ONLY: blocked kernel init + 10 prototype scenarios; NO Linux PCI core/runtime proof");
}
