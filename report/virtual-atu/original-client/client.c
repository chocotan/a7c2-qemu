/* Original-provider diagnostic for an explicit, isolated TESTPCI peer.
 * No unload callback: this module and established IOMEM live until VM exit.
 */
typedef unsigned long u64;
typedef unsigned int u32;
typedef int s32;
struct atu_option { u32 search; s32 timeout; };
struct iomem {
    char name[8];
    u64 physical, size, virtual;
    u32 flags, padding;
};
_Static_assert(sizeof(u64) == 8 && sizeof(s32) == 4, "native ABI");
_Static_assert(sizeof(struct iomem) == 0x28, "original IOMEM size");
_Static_assert(__builtin_offsetof(struct iomem, physical) == 8 &&
               __builtin_offsetof(struct iomem, size) == 0x10 &&
               __builtin_offsetof(struct iomem, virtual) == 0x18 &&
               __builtin_offsetof(struct iomem, flags) == 0x20, "IOMEM fields");
extern s32 pciatu_map(u64 pci, u64 *physical, u32 size, const struct atu_option *option);
extern s32 pciatu_unmap(u32 slot);
extern void *udif_ioremap(void *resource);
extern void udif_iounmap(void *resource);
extern int printk(const char *, ...);

#ifndef ATU_CTRL_BASE
#define ATU_CTRL_BASE 0xfffffffff7300000UL
#endif
#define PAGE_BYTES 4096U
#define MAP_BYTES 0x100000U
#define PAYLOAD_START 16U
#define PAYLOAD_BYTES 256U
static struct iomem aperture = { .name = "atu-ap", .size = PAGE_BYTES };
static struct iomem peer = {
    .name = "atupeer", .physical = 0x600000000UL, .size = PAGE_BYTES
};

static void io_barrier(void)
{
#ifdef __aarch64__
    __asm__ volatile("dsb sy" ::: "memory");
#endif
}

static unsigned char expected(unsigned offset, unsigned changed)
{
    unsigned i;
    if (offset < PAYLOAD_START || offset >= PAYLOAD_START + PAYLOAD_BYTES)
        return 0xa5;
    i = offset - PAYLOAD_START;
    return changed ? (unsigned char)(i * 53 + 0x91) : (unsigned char)(i * 29 + 7);
}

static int page_matches(volatile unsigned char *bytes, unsigned changed)
{
    unsigned i;
    for (i = 0; i < PAGE_BYTES; i++) {
        if (bytes[i] != expected(i, changed)) return 0;
    }
    return 1;
}

static int map_page(struct iomem *resource)
{
    void *address = udif_ioremap(resource);
    return address && (u64)address == resource->virtual && !((u64)address & 4095);
}

int __attribute__((section(".init.text"))) init_module(void)
{
    u64 physical = 0;
    s32 slot, released;
    u32 control;
    unsigned i, data_ok = 0;
    volatile unsigned char *ap, *observation;
    printk("\0016ATU_CLIENT_BEGIN: explicit TESTPCI peer, original provider, NULL/no-wait\n");
    slot = pciatu_map(0x04000000UL, &physical, MAP_BYTES, (const struct atu_option *)0);
    printk("\0016ATU_CLIENT_MAP_RC=%d phys=%lx bytes=%x\n", slot, physical, MAP_BYTES);
    if (slot < 0) {
        printk("\0013ATU_CLIENT_NOT_MAPPED: provider refused; resident, no data access\n");
        return 0;
    }
    if (slot > 7) {
        printk("\0013ATU_CLIENT_OWNER_UNCERTAIN: invalid positive slot; no unmap/MMIO guessing\n");
        return 0;
    }
    if (physical < 0xc0000000UL || physical > 0xe0000000UL - MAP_BYTES ||
        (physical & (MAP_BYTES - 1))) {
        printk("\0013ATU_CLIENT_FAIL: returned aperture outside aligned allocator window\n");
        goto release_slot;
    }
    aperture.physical = physical;
    if (!map_page(&aperture) || !map_page(&peer)) {
        /* Roll back only incomplete setup, before any peer/aperture byte access. */
        if (peer.virtual) udif_iounmap(&peer);
        if (aperture.virtual) udif_iounmap(&aperture);
        printk("\0013ATU_CLIENT_FAIL: IOMEM setup rejected; setup mappings rolled back\n");
        goto release_slot;
    }
    ap = (volatile unsigned char *)aperture.virtual;
    observation = (volatile unsigned char *)peer.virtual;
    for (i = 0; i < PAGE_BYTES; i++) observation[i] = expected(i, 0);
    io_barrier();
    printk("\0016ATU_CLIENT_PEER_INITIALIZED: guards+256 bytes via observation\n");
    if (!page_matches(ap, 0)) {
        printk("\0013ATU_CLIENT_FAIL: aperture initial bytes/guards differ\n");
        goto release_slot;
    }
    printk("\0016ATU_CLIENT_APERTURE_READ_PASS: guarded page, payload=256\n");
    for (i = 0; i < PAYLOAD_BYTES; i++) ap[PAYLOAD_START + i] = expected(PAYLOAD_START + i, 1);
    io_barrier();
    printk("\0016ATU_CLIENT_APERTURE_WRITTEN: changed 256 bytes through aperture\n");
    if (!page_matches(observation, 1)) {
        printk("\0013ATU_CLIENT_FAIL: observation changed bytes/guards differ\n");
        goto release_slot;
    }
    data_ok = 1;
    printk("\0016ATU_CLIENT_DATA_PASS: observation verifies aperture stores and guards\n");

release_slot:
    /* Only the slot returned by this map is released; never touch other slots. */
    released = pciatu_unmap((u32)slot);
    printk("\0016ATU_CLIENT_UNMAP_RC=%d slot=%d\n", released, slot);
    if (released != 0) {
        printk("\0013ATU_CLIENT_OWNER_UNCERTAIN: original unmap failed; resources resident\n");
        return 0;
    }
    io_barrier();
    control = *(volatile u32 *)(ATU_CTRL_BASE + (u64)slot * 0x200 + 4);
    printk("\0016ATU_CLIENT_CTRL_AFTER_UNMAP=%08x slot=%d\n", control, slot);
    if (control & 0x80000000U) {
        printk("\0013ATU_CLIENT_OWNER_UNCERTAIN: enable remains set after unmap\n");
        return 0;
    }
    printk("\0016ATU_CLIENT_OWNER_RELEASED: own slot enable clear; no invalid aperture read\n");
    if (data_ok)
        printk("\0016ATU_CLIENT_PASS: original map, peer/aperture bytes+guards, original unmap; resident\n");
    return 0;
}
