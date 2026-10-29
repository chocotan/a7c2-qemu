/* Normal exported fixed I/O mapper for resource0 PCI DMA. Resident until exit.
 * Translation proof only: does not connect PCI, publish state or submit DMA.
 */
typedef unsigned long u64;
_Static_assert(sizeof(u64)==8,"original A64 mapping ABI");
extern int ioremap_page_range(u64,u64,u64,u64);
extern int printk(const char *,...);
#define IO_VA 0xfffffffff7380000UL
#define IO_PHYSICAL 0xf7380000UL
#define IO_BYTES 8192UL
#define DEVICE_PROTECTION 0x00e8000000000f07UL
#ifdef FIXED_IO_HOST_TEST
extern int host_translate(u64,u64 *);
static int translate(u64 address,u64 *physical) { return host_translate(address,physical); }
#else
static int translate(u64 address,u64 *physical)
{
    u64 mask,par;
    __asm__ volatile("mrs %0, daif\nmsr daifset, #2\nat s1e1r, %2\nisb\nmrs %1, par_el1\nmsr daif, %0"
        : "=&r"(mask),"=&r"(par) : "r"(address) : "memory");
    if (par&1) return 0;
    *physical=(par&0x0000fffffffff000UL)|(address&4095);
    return 1;
}
#endif
int __attribute__((section(".init.text"))) init_module(void)
{
    u64 physical;
    unsigned any=0,valid=1;
    for (u64 offset=0;offset<IO_BYTES;offset+=4096) {
        if (translate(IO_VA+offset,&physical)) {
            printk("\0013FIXED_PCIDMA_REFUSED: pre-existing translation\n");
            return -16;
        }
    }
    int rc=ioremap_page_range(IO_VA,IO_VA+IO_BYTES,IO_PHYSICAL,DEVICE_PROTECTION);
#ifdef __aarch64__
    __asm__ volatile("dsb ish\nisb" ::: "memory");
#endif
    for (u64 offset=0;offset<IO_BYTES;offset+=4096) {
        if (translate(IO_VA+offset,&physical)) {
            any=1;
            if (physical!=IO_PHYSICAL+offset) valid=0;
        } else valid=0;
    }
    if (rc && !any) {
        printk("\0013FIXED_PCIDMA_FAILED: mapper status=%d, no page mapped\n",rc);
        return rc;
    }
    if (rc || !valid) {
        printk("\0013FIXED_PCIDMA_RESIDENT_UNVERIFIED: rc=%d, partial/physical mismatch\n",rc);
        return 0;
    }
    printk("\0016FIXED_PCIDMA_MAP_PASS: two pages, original mapper and PAR physical verified; no DMA\n");
    return 0;
}
