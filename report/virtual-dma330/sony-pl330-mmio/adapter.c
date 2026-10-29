/* Local virt-board MMIO resource adapter, loaded BEFORE the original dma330.
 * No channel state, IRQ, request, DMA buffer, AP or CP business data is changed.
 * This module intentionally has no unload callback: mappings live until VM exit.
 */
typedef unsigned long u64;
typedef unsigned int u32;
_Static_assert(sizeof(u64) == 8 && sizeof(u32) == 4, "AArch64 ABI");
extern unsigned char udif_devices[];
extern void *udif_ioremap(void *resource);
extern void udif_iounmap(void *resource);
extern int printk(const char *, ...);

struct iomem {
    char name[8];
    u64 physical, size, virtual;
    u32 flags, padding;
};
_Static_assert(sizeof(struct iomem) == 0x28, "original IOMEM layout");
static struct iomem mappings[2];

static u64 *field(unsigned char *base, unsigned offset)
{
    return (u64 *)(base+offset);
}

int __attribute__((section(".init.text"))) init_module(void)
{
    unsigned char *device = udif_devices+0x240;
    unsigned char *channels;
    unsigned i;
    if (*field(device, 0) != 0x302d64303333UL || *(u32 *)(device+0x18) != 18) {
        printk("\0013sony_dma_map: device layout rejected\n");
        return -22;
    }
    channels = (unsigned char *)*field(device, 0x20);
    if (!channels) {
        return -22;
    }
    /* Validate all records before mapping or publishing any address. IRQ
     * handlers must still be unset: adapting a live driver is not supported.
     */
    for (i = 0; i < 18; i++) {
        unsigned char *record = channels+i*0x98;
        if (*field(record, 0x40)) {
            printk("\0013sony_dma_map: driver already owns IRQ\n");
            return -16;
        }
        if (i < 16) {
            u64 physical = i < 8 ? 0xf1056000UL : 0xf1057000UL;
            if (*field(record, 8) != physical || *field(record, 0x10) != 0x1000
                || *field(record, 0x18) != (0xffffffff00000000UL | physical)
                || *(u32 *)(record+0x20) != 0) {
                printk("\0013sony_dma_map: unexpected resource\n");
                return -22;
            }
        }
    }
    for (i = 0; i < 2; i++) {
        struct iomem *mapping = &mappings[i];
        void *address;
        mapping->name[0] = 's'; mapping->name[1] = 'd'; mapping->name[2] = 'm';
        mapping->name[3] = 'a'; mapping->name[4] = '0'+i; mapping->name[5] = 0;
        mapping->physical = 0xf1056000UL+i*0x1000;
        mapping->size = 0x1000;
        address = udif_ioremap(mapping);
        if (!address || (u64)address != mapping->virtual
            || *(volatile u32 *)((unsigned char *)address+0xfe0) != 0x30) {
            unsigned rollback;
            for (rollback = 0; rollback <= i; rollback++) {
                if (mappings[rollback].virtual) {
                    udif_iounmap(&mappings[rollback]);
                }
            }
            printk("\0013sony_dma_map: mapping/PID failed; unpublished\n");
            return -19;
        }
    }
    for (i = 0; i < 16; i++) {
        *field(channels+i*0x98, 0x18) = mappings[i/8].virtual;
    }
#ifdef __aarch64__
    __asm__ volatile("dsb ishst" ::: "memory");
#endif
    printk("\0016sony_dma_map: published 16 resources, PID30x2, no DMA\n");
    return 0;
}
