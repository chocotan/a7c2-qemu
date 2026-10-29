/* Read-only check of mappings established by original setup_arch/map_io.
 * No mapper import, page-table writes, MMIO transactions or driver start.
 */
typedef unsigned long u64;
extern int printk(const char *,...);
#ifdef FIXED_IO_HOST_TEST
extern int host_translate(u64,u64 *);
#define translate host_translate
#else
static int translate(u64 address,u64 *physical)
{
    u64 mask,par;
    __asm__ volatile("mrs %0, daif\nmsr daifset, #2\nat s1e1r, %2\nisb\nmrs %1, par_el1\nmsr daif, %0"
        : "=&r"(mask),"=&r"(par) : "r"(address) : "memory");
    if(par&1)return 0;
    *physical=(par&0x0000fffffffff000UL)|(address&4095);return 1;
}
#endif
static const u64 addresses[]={0xf1056000,0xf1057000,0xf1057fff,0xf11c0000,
    0xf11e0380,0xf70008bc,0xf7300000,0xf7380000,0xf7381000,0xf7381fff};
int __attribute__((section(".init.text"))) init_module(void)
{
    for(unsigned i=0;i<sizeof(addresses)/sizeof(addresses[0]);i++) {
        u64 physical=0,virtual=0xffffffff00000000UL|addresses[i];
        if(!translate(virtual,&physical) || physical!=addresses[i]) {
            printk("\0013EARLY_IOMAP_FAIL: index=%u, PA=%lx; no mapper called\n",i,physical);return -22;
        }
    }
    printk("\0016EARLY_IOMAP_PASS: ten existing translations, original boot mapping; no mapper/MMIO/DMA\n");
    return 0;
}
