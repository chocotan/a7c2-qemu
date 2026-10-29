/* Explicit QEMU TEST host with OWNED context matching the actual Root Port
 * fixup ABI. Normal PCI core only; not a Sony PHY-probe completion claim.
 * No private kernel flags, host notifications or PCIDMA submissions.
 */
typedef unsigned long u64;
typedef unsigned int u32;
typedef unsigned short u16;
typedef unsigned char u8;
struct list { struct list *next,*prev; };
struct resource { u64 start,end; const char *name; u64 flags,opaque[4]; };
struct entry { struct list list; struct resource *resource; u64 offset; };
struct iomem { char name[8]; u64 physical,size,virtual; u32 flags,padding; };
struct pci_ops {
    void *unused[3];
    int (*read)(void *,unsigned,int,int,u32 *);
    int (*write)(void *,unsigned,int,int,u32);
};
struct dbi_ops { void *unused,*read,*write; };
_Static_assert(sizeof(struct dbi_ops)==0x18,"actual default DBI ops extent");
struct ctrl_compat {
    void *device;
    u64 dbi;
    u8 opaque[0x148];
    const struct dbi_ops *ops;
    u64 wrapper;
};
_Static_assert(__builtin_offsetof(struct ctrl_compat,ops)==0x158 &&
               __builtin_offsetof(struct ctrl_compat,wrapper)==0x160 &&
               sizeof(struct ctrl_compat)==0x168,"actual quirk context extent");
_Static_assert(sizeof(u64)==8 && sizeof(struct resource)==64,"original resource ABI");
_Static_assert(sizeof(struct iomem)==40 && sizeof(struct pci_ops)==40,"original IOMEM/ops ABI");
_Static_assert(__builtin_offsetof(struct pci_ops,read)==0x18 &&
               __builtin_offsetof(struct pci_ops,write)==0x20,"original callbacks");
extern void *udif_ioremap(void *);
extern void pci_add_resource(struct list *,struct resource *);
extern void pci_free_resource_list(struct list *);
extern void *pci_scan_root_bus(void *,int,struct pci_ops *,void *,struct list *);
extern void pci_bus_size_bridges(void *);
extern void pci_bus_assign_resources(void *);
extern void pci_bus_add_devices(void *);
extern void *pci_find_bus(int,int);
extern void *pci_get_domain_bus_and_slot(int,unsigned,unsigned);
extern void pci_lock_rescan_remove(void);
extern void pci_unlock_rescan_remove(void);
extern int printk(const char *,...);

#define ECAM_PHYSICAL 0x4010000000UL
#define ECAM_BYTES 0x1000000UL
static struct iomem ecam={.name="pciecfg",.physical=ECAM_PHYSICAL,.size=ECAM_BYTES};
static struct iomem dbi={.name="testdbi",.physical=0xf7000000,.size=4096};
static struct iomem wrapper={.name="testwrp",.physical=0xf11c0000,.size=0x40000};
static struct resource bus_resource={.start=0,.end=15,.name="QEMU TEST PCI buses",.flags=0x1000};
static struct resource mem_resource={.start=0x10000000,.end=0x1fffffff,.name="QEMU TEST PCI memory",.flags=0x200};
static struct list windows;
static const struct dbi_ops default_dbi_ops={0};
static struct { struct ctrl_compat ctrl; void *bus,*device; u32 reads,writes; } context;

static void barrier(void)
{
#ifdef __aarch64__
    __asm__ volatile("dsb sy" ::: "memory");
#endif
}
static int offset_of(unsigned bus,unsigned devfn,int where,int size,u64 *offset)
{
    if (!ecam.virtual || bus>15 || devfn>255 || where<0 ||
        (size!=1 && size!=2 && size!=4) || where>4096-size || (where&(size-1))) return 0;
    *offset=((u64)bus<<20)|((u64)devfn<<12)|(unsigned)where;
    return 1;
}
static int config_read(unsigned bus,unsigned devfn,int where,int size,u32 *value)
{
    u64 offset;
    if (!value) return 0x87;
    *value=0xffffffffU;
    if (!offset_of(bus,devfn,where,size,&offset)) return 0x87;
    volatile u8 *p=(volatile u8 *)(bus==0 && devfn==8 && where<0x700?
        dbi.virtual+(unsigned)where:ecam.virtual+offset);
    barrier();
    *value=size==1?*p:size==2?*(volatile u16 *)p:*(volatile u32 *)p;
    barrier();context.reads++;
    return 0;
}
static int config_write(unsigned bus,unsigned devfn,int where,int size,u32 value)
{
    u64 offset;
    if (!offset_of(bus,devfn,where,size,&offset)) return 0x87;
    volatile u8 *p=(volatile u8 *)(bus==0 && devfn==8 && where<0x700?
        dbi.virtual+(unsigned)where:ecam.virtual+offset);
    if (size==1) *p=(u8)value;
    else if (size==2) *(volatile u16 *)p=(u16)value;
    else *(volatile u32 *)p=value;
    barrier();context.writes++;return 0;
}
int sony_dw_config_read(void *bus,unsigned devfn,int where,int size,u32 *value)
{
    if (!bus) { if(value)*value=0xffffffffU;return 0x86; }
    if (*((u8 *)bus+0xe0)==0 && !context.ctrl.device) {
        context.ctrl.device=*(void **)((u8 *)bus+0x120);
        if (!context.ctrl.device) { if(value)*value=0xffffffffU;return 0x86; }
    }
    return config_read(*((u8 *)bus+0xe0),devfn,where,size,value);
}
int sony_dw_config_write(void *bus,unsigned devfn,int where,int size,u32 value)
{
    if (!bus) return 0x86;
    return config_write(*((u8 *)bus+0xe0),devfn,where,size,value);
}
struct pci_ops sony_dw_ops={.read=sony_dw_config_read,.write=sony_dw_config_write};
static int resources_complete(void)
{
    struct list *node=windows.next;
    unsigned seen=0;
    for (unsigned n=0;n<3 && node!=&windows;n++) {
        if (!node || ((u64)node&7)) return 0;
        struct entry *e=(struct entry *)node;
        unsigned bit=e->resource==&bus_resource?1:e->resource==&mem_resource?2:0;
        if (!bit || (seen&bit) || e->offset) return 0;
        seen|=bit;node=node->next;
    }
    return node==&windows && seen==3;
}

static int map_resource(struct iomem *resource)
{
    void *p=udif_ioremap(resource);
    return p && (u64)p==resource->virtual && !((u64)p&4095);
}
int __attribute__((section(".init.text"))) init_module(void)
{
    u32 identity,bar;
    printk("\0016DW_TEST_HOST_BEGIN: owned compatible context, actual TEST DBI and PCI function\n");
    if (pci_find_bus(0,0)) {
        printk("\0013PCI_CORE_TEST_REFUSED: existing domain0/rootbus0, no scan\n");return 0;
    }
    if (!map_resource(&ecam) || !map_resource(&dbi) || !map_resource(&wrapper)) {
        printk("\0013PCI_CORE_TEST_NOT_SCANNED: ECAM mapping failed, resident\n");return 0;
    }
    context.ctrl.dbi=dbi.virtual;context.ctrl.wrapper=wrapper.virtual;
    context.ctrl.ops=&default_dbi_ops;
    if (*(volatile u32 *)(wrapper.virtual+0x20380)!=0x40 ||
        *(volatile u32 *)(dbi.virtual+0x8bc)!=0) {
        printk("\0013DW_TEST_HOST_NOT_SCANNED: explicit DBI/control initial state differs\n");return 0;
    }
    /* Check an actual QEMU root-port config transaction, never fabricate IDs. */
    if (config_read(0,8,0,4,&identity) || (identity&0xffff)!=0x1b36) {
        printk("\0013PCI_CORE_TEST_NOT_SCANNED: expected virtual root-port absent\n");return 0;
    }
    if (config_read(0,8,8,4,&identity) || (identity>>16)!=0x0604) {
        printk("\0013PCI_CORE_TEST_NOT_SCANNED: expected virtual root-port class differs\n");return 0;
    }
    windows.next=windows.prev=&windows;
    pci_add_resource(&windows,&bus_resource);pci_add_resource(&windows,&mem_resource);
    if (!resources_complete()) {
        pci_free_resource_list(&windows);
        printk("\0013PCI_CORE_TEST_NOT_SCANNED: resource entry allocation incomplete\n");return 0;
    }
    pci_lock_rescan_remove();
    context.bus=pci_scan_root_bus((void *)0,0,&sony_dw_ops,(u8 *)&context.ctrl+0x20,&windows);
    if (!context.bus) {
        pci_unlock_rescan_remove();pci_free_resource_list(&windows);
        printk("\0013PCI_CORE_TEST_SCAN_FAILED: normal scan returned NULL, resident, no retry\n");return 0;
    }
    /* Resources, callbacks, names, ECAM and module code remain alive. */
    if (windows.next!=&windows || windows.prev!=&windows) {
        pci_unlock_rescan_remove();
        printk("\0013PCI_CORE_TEST_OWNER_UNCERTAIN: scan resource ownership differs, resident\n");return 0;
    }
    int domain=*(int *)((u8 *)context.bus+0xe4);
    unsigned number=*((u8 *)context.bus+0xe0);
    printk("\0016PCI_CORE_TEST_BUS: domain=%d bus=%u\n",domain,number);
    if (domain!=0 || number!=0) {
        pci_unlock_rescan_remove();
        printk("\0013PCI_CORE_TEST_DOMAIN_MISMATCH: keep normal assigned domain, no force/no retry\n");return 0;
    }
    pci_bus_size_bridges(context.bus);pci_bus_assign_resources(context.bus);
    pci_unlock_rescan_remove();
    pci_bus_add_devices(context.bus);
    context.device=pci_get_domain_bus_and_slot(0,1,0);
    if (!context.device || config_read(1,0,0,4,&identity) || identity!=0x00051b36) {
        printk("\0013PCI_CORE_TEST_ENDPOINT_MISSING: normal 0000:01:00.0 TEST peer not verified\n");return 0;
    }
    config_read(1,0,0x10,4,&bar);
    if (bar<0x10000000U || bar>0x1f000000U || (bar&0x00ffffffU)) {
        printk("\0013DW_TEST_HOST_BAR_INVALID: actual assigned BAR outside TEST window\n");return 0;
    }
    printk("\0016PCI_CORE_TEST_ENDPOINT: id=%08x bar0=%08x reads=%u writes=%u\n",
           identity,bar,context.reads,context.writes);
    printk("\0016DW_TEST_HOST_ENUM_PASS: actual kernel PCI device, owned DW context; no PCIDMA transfer\n");
    return 0;
}
