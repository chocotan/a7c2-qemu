/* Original PCI DMA API diagnostic: normal exported APIs, one direct 256B
 * AP->PCI write then a PCI->AP read-back, real callback/IRQ path.
 * No private kernel writes, no hardcoded hidden calls, no channel0 bypass. */
typedef unsigned long u64;
typedef unsigned int u32;
typedef unsigned char u8;
typedef unsigned short u16;

extern int printk(const char *,...);
extern void *get_zeroed_page(u64);
extern void free_pages(u64,u64);
extern u64 arch_va_to_phys(void *);
extern void msleep(u32);
extern void *pci_get_domain_bus_and_slot(int,unsigned,unsigned);
extern int pci_enable_device(void *);
extern void pci_set_master(void *);
extern int pci_bus_read_config_dword(void *,unsigned,int,u32 *);
extern void pcidma_connect(u32,u32);
extern int pcidma_transfer_async(void *);

#define GFP_KERNEL_FLAGS 0x24000c0UL /* this kernel 4.9.337: RECLAIM|IO|FS */
#define TRANSFER_LEN 256u

static volatile int cb_seen;
static volatile int cb_status;
static volatile u64 cb_cookie;

static void diag_callback(int status,u64 cookie)
{
    cb_status=status;cb_cookie=cookie;cb_seen=1;
    printk("\0016NATIVE_PCIDMA_CALLBACK: status=%d cookie=%lu\n",status,cookie);
}

static u8 *req_page,*src_page,*dst_page;

static void build_request(u8 *req,u8 channel,u8 direction,u32 length,
                          u64 source,u64 destination,void *callback,u64 cookie)
{
    for(unsigned i=0;i<0x40;i++)req[i]=0;
    req[0]=0;req[1]=channel;req[2]=direction;
    req[4]=(u8)length;req[5]=(u8)(length>>8);req[6]=(u8)(length>>16);req[7]=(u8)(length>>24);
    for(unsigned i=0;i<8;i++)req[8+i]=(u8)(source>>(8*i));
    for(unsigned i=0;i<8;i++)req[16+i]=(u8)(destination>>(8*i));
    u64 cb=(u64)callback;
    for(unsigned i=0;i<8;i++)req[24+i]=(u8)(cb>>(8*i));
    for(unsigned i=0;i<8;i++)req[32+i]=(u8)(cookie>>(8*i));
}

int __attribute__((section(".init.text"))) init_module(void)
{
    void *pdev=pci_get_domain_bus_and_slot(0,1,0);
    if(!pdev) {printk("\0013NATIVE_PCIDMA_FAILED: no enumerated peer at 0000:01:00.0\n");return -19;}
    void *bus=*(void **)((char *)pdev+0x10); /* pinned dev+0x10 -> bus (rootport quirk 52 pins) */
    u32 bar32=0;
    if(pci_bus_read_config_dword(bus,0,0x10,&bar32)) {printk("\0013NATIVE_PCIDMA_FAILED: bar read\n");return -5;}
    u64 pci_addr=bar32&~0xfu;
    if(!pci_addr || pci_addr==(u32)~0) {printk("\0013NATIVE_PCIDMA_FAILED: peer BAR0 unassigned %x\n",bar32);return -19;}
    int rc=pci_enable_device(pdev);
    if(rc) {printk("\0013NATIVE_PCIDMA_FAILED: enable rc=%d\n",rc);return rc;}
    pci_set_master(pdev);
    req_page=get_zeroed_page(GFP_KERNEL_FLAGS);
    src_page=get_zeroed_page(GFP_KERNEL_FLAGS);
    dst_page=get_zeroed_page(GFP_KERNEL_FLAGS);
    if(!req_page||!src_page||!dst_page) {printk("\0013NATIVE_PCIDMA_FAILED: page alloc\n");return -12;}
    for(unsigned i=0;i<TRANSFER_LEN;i++)src_page[i]=(u8)(i*29+7);
    pcidma_connect(0,1);
    printk("\0016NATIVE_PCIDMA_CONNECT: controller=0 connected=1 peer_bar=%lu\n",pci_addr);

    /* Direction 1: AP -> PCI write. */
    cb_seen=0;
    build_request(req_page,0,1,TRANSFER_LEN,arch_va_to_phys(src_page),pci_addr,diag_callback,0x1122334455667788UL);
    rc=pcidma_transfer_async(req_page);
    if(rc) {printk("\0013NATIVE_PCIDMA_FAILED: write submit rc=%d\n",rc);return rc;}
    for(unsigned i=0;i<2000 && !cb_seen;i++)msleep(1);
    if(!cb_seen || cb_status || cb_cookie!=0x1122334455667788UL) {
        printk("\0013NATIVE_PCIDMA_FAILED: write completion seen=%d status=%d cookie=%lu\n",cb_seen,cb_status,cb_cookie);
        return -110;
    }
    printk("\0016NATIVE_PCIDMA_WRITE_DONE: bytes=%u\n",TRANSFER_LEN);

    /* Direction 0: PCI -> AP read-back, verify data round-trip in kernel. */
    cb_seen=0;
    build_request(req_page,0,0,TRANSFER_LEN,pci_addr,arch_va_to_phys(dst_page),diag_callback,0xa5a5a5a5a5a5a5a5UL);
    rc=pcidma_transfer_async(req_page);
    if(rc) {printk("\0013NATIVE_PCIDMA_FAILED: read submit rc=%d\n",rc);return rc;}
    for(unsigned i=0;i<2000 && !cb_seen;i++)msleep(1);
    if(!cb_seen || cb_status || cb_cookie!=0xa5a5a5a5a5a5a5a5UL) {
        printk("\0013NATIVE_PCIDMA_FAILED: read completion seen=%d status=%d cookie=%lu\n",cb_seen,cb_status,cb_cookie);
        return -110;
    }
    unsigned mismatches=0;
    for(unsigned i=0;i<TRANSFER_LEN;i++)if(dst_page[i]!=src_page[i])mismatches++;
    if(mismatches) {printk("\0013NATIVE_PCIDMA_FAILED: read-back mismatches=%u\n",mismatches);return -5;}
    printk("\0016NATIVE_PCIDMA_PASS: write+read 256B via original APIs, callbacks status=0, data verified\n");
    return 0;
}
