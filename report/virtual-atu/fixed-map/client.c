/* One fixed-board I/O mapping baseline, using the ORIGINAL exported mapper.
 * No page-table patching, MMU bypass, channel state or transfer is performed.
 * This resident module owns the mapping until the isolated VM exits.
 */
typedef unsigned long u64;
typedef unsigned int u32;
extern int ioremap_page_range(u64 start, u64 end, u64 physical, u64 protection);
extern int printk(const char *, ...);
#ifdef FIXED_ATU_PROFILE
#define IO_VA 0xfffffffff7300000UL
#define IO_PHYSICAL 0xf7300000UL
#else
#define IO_VA 0xfffffffff1056000UL
#define IO_PHYSICAL 0xf1056000UL
#endif
/* Device, privileged RW/XN, nonglobal. The exact value is emitted by this
 * kernel's own UDIF mapping path (not borrowed from reference 4.9.186).
 */
#define DEVICE_PROTECTION 0x00e8000000000f07UL

#ifdef FIXED_IO_HOST_TEST
extern int host_present(u64 address);
extern u32 host_pid(void);
static int present(u64 address) { return host_present(address); }
#ifndef FIXED_ATU_PROFILE
static u32 pid(void) { return host_pid(); }
#endif
#else
static int present(u64 address)
{
    u64 interrupt_mask, result;
    __asm__ volatile("mrs %0, daif\nmsr daifset, #2\nat s1e1r, %2\nisb\nmrs %1, par_el1\nmsr daif, %0"
                     : "=&r"(interrupt_mask), "=&r"(result) : "r"(address) : "memory");
    return !(result & 1);
}
#ifndef FIXED_ATU_PROFILE
static u32 pid(void) { return *(volatile u32 *)(IO_VA+0xfe0); }
#endif
#endif

int __attribute__((section(".init.text"))) init_module(void)
{
    int status;
    if (present(IO_VA) || present(IO_VA+4095)) {
        printk("\0013FIXED_IO_REFUSED: mapping already present\n");
        return -16;
    }
    status = ioremap_page_range(IO_VA, IO_VA+4096, IO_PHYSICAL, DEVICE_PROTECTION);
    if (status) {
        printk("\0013FIXED_IO_FAILED: mapper status=%d\n", status);
        return status;
    }
#ifdef __aarch64__
    __asm__ volatile("dsb ish\nisb" ::: "memory");
#endif
    if (!present(IO_VA)
#ifndef FIXED_ATU_PROFILE
        || pid() != 0x30
#endif
       ) {
        /* Mapping exists: stay resident even if observation fails. Never
         * return a negative init and abandon a mapping owned by this module.
         */
        printk("\0013FIXED_IO_RESIDENT_UNVERIFIED: translation/PID mismatch\n");
        return 0;
    }
#ifdef FIXED_ATU_PROFILE
    printk("\0016FIXED_ATU_MAP_PASS: original mapper, ATU VA translated; data unverified\n");
#else
    printk("\0016FIXED_IO_PASS: original mapper, fixed VA, PID30, no DMA\n");
#endif
    return 0;
}
