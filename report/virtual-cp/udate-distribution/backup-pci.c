/* Ordinary PCI APIs bind the explicit virtual peer, never AP root memory. */
extern void *pci_get_domain_bus_and_slot(int, unsigned, unsigned);
extern int pci_enable_device(void *);
extern void pci_disable_device(void *);
extern void pci_set_master(void *);
extern void pci_dev_put(void *);
extern int pci_bus_read_config_dword(void *, unsigned, int, u32 *);
extern void *pci_iomap_range(void *, int, unsigned long, unsigned long);
extern void pci_iounmap(void *, void *);
extern void __memcpy_fromio(void *, const volatile void *, unsigned long);
extern void pcidma_connect(u32, u32);

u8 backup_model; /* __param bool, default off; explicit load must fail closed */
static void *backup_pdev;
static volatile u8 *backup_io, *backup_control;
static u32 backup_device_enabled;
static u64 backup_epoch;

static void backup_barrier(void)
{
#if defined(__aarch64__)
    __asm__ volatile("dsb sy" ::: "memory");
#else
    __sync_synchronize();
#endif
}
#ifndef BACKUP_CONTROL_READ32
#define BACKUP_CONTROL_READ32(address) (*(const volatile u32 *)(address))
#define BACKUP_CONTROL_WRITE32(address, value) (*(volatile u32 *)(address) = (value))
#endif
static u32 backup_control_read(u32 offset)
{
    u32 value;
    backup_barrier();
    value = BACKUP_CONTROL_READ32(backup_control + offset);
    backup_barrier();
    return value;
}
static void backup_control_write(u32 command)
{
    backup_barrier();
    BACKUP_CONTROL_WRITE32(backup_control + 24, command);
    backup_barrier();
}
static u64 backup_control_epoch(void)
{
    return (u64)backup_control_read(16) | (u64)backup_control_read(20) << 32;
}
static long backup_pci_read(void *opaque, u32 offset, void *out, u32 size)
{
    (void)opaque;
    if (!backup_io || offset > BACKUP_DATA_BYTES || size > BACKUP_DATA_BYTES - offset)
        return -1021;
    __memcpy_fromio(out, backup_io + offset, size);
    return 0;
}
static long backup_pci_freeze(void *opaque)
{
    u64 before;
    (void)opaque;
    if (!backup_control || backup_control_read(12) != 0) return -1021;
    before = backup_control_epoch();
    backup_control_write(1);
    backup_epoch = backup_control_epoch();
    if (backup_control_read(12) != 1 || backup_epoch != before + 1) return -1021;
    return 0;
}
static long backup_pci_unlock(void *opaque)
{
    (void)opaque;
    if (!backup_control || backup_control_read(12) != 1 ||
        backup_control_epoch() != backup_epoch || backup_control_read(32) != 1)
        return -1021;
    backup_control_write(2);
    if (backup_control_read(12) != 0 || backup_control_epoch() != backup_epoch)
        return -1021;
    return 0;
}
static u32 backup_bar_extent(void *device, u32 bar, u64 required, u64 *start_out)
{
    /* Pinned 4.9.337 pci_iomap_range ABI: resource start/end/flags at +368/+370/+380. */
    const u8 *resource = (const u8 *)device + 0x368 + bar * 0x40;
    u64 start = get64(resource), end = get64(resource + 8), flags = get64(resource + 0x18);
    if (!start || (start & 3) || end < start || !(flags & 0x200) || (flags & 0x100) ||
        end - start < required - 1) return 0;
    *start_out = start;
    return 1;
}
static void backup_pci_release(void)
{
    backup_enabled = 0;
    zero(&backup_backend, sizeof(backup_backend));
    if (backup_control) pci_iounmap(backup_pdev, (void *)backup_control);
    if (backup_io) pci_iounmap(backup_pdev, (void *)backup_io);
    backup_control = backup_io = 0;
    if (backup_device_enabled) pci_disable_device(backup_pdev);
    backup_device_enabled = 0;
    if (backup_pdev) pci_dev_put(backup_pdev);
    backup_pdev = 0;
}
static long backup_pci_prepare(void)
{
    void *bus;
    u32 identity;
    u64 data_start = 0, control_start = 0, fingerprint = 0;
    long rc = -19;
    const char *where = "lookup";
    backup_pdev = pci_get_domain_bus_and_slot(0, 1, 0);
    if (!backup_pdev) {
        printk("\0016BACKUP_K_INIT_ERROR: stage=lookup rc=-19\n");
        return rc;
    }
    where = "identity-resource";
    bus = *(void **)((u8 *)backup_pdev + 0x10);
    if (!bus || pci_bus_read_config_dword(bus, 0, 0, &identity) || identity != 0x00051b36u ||
        !backup_bar_extent(backup_pdev, 0, 16UL * 1024 * 1024, &data_start) ||
        !backup_bar_extent(backup_pdev, 1, 4096, &control_start)) goto failed;
    where = "enable";
    rc = pci_enable_device(backup_pdev);
    if (rc) goto failed;
    backup_device_enabled = 1;
    where = "map-control-contract";
    backup_io = pci_iomap_range(backup_pdev, 0, 0, BACKUP_DATA_BYTES);
    backup_control = pci_iomap_range(backup_pdev, 1, 0, 4096);
    rc = -19;
    if (!backup_io || !backup_control || backup_control_read(0) != 0x42555031 ||
        backup_control_read(4) != 1 || backup_control_read(8) != BACKUP_DATA_BYTES ||
        backup_control_read(12) != 0) goto failed;
    backup_backend = (struct backup_backend){0, backup_pci_freeze, backup_pci_read, backup_pci_unlock};
    where = "public-fixture-readback";
    rc = backup_read_record(0, BACKUP_INITIAL_FNV64, &fingerprint);
    if (rc) goto failed;
    printk("\0016BACKUP_K_PREPARED: BDF=0000:01:00.0 bar0=%#lx bar1=%#lx bytes=%u fnv=%016lx virtual_fixture=1 original_cp_executed=0\n",
           data_start, control_start, BACKUP_DATA_BYTES, fingerprint);
    return 0;
failed:
    printk("\0016BACKUP_K_INIT_ERROR: stage=%s rc=%ld bar0=%#lx bar1=%#lx\n",
           where, rc, data_start, control_start);
    backup_pci_release();
    return rc;
}
static void backup_pci_connect(void)
{
    pci_set_master(backup_pdev);
    pcidma_connect(0, 1);
    backup_enabled = 1;
    printk("\0016BACKUP_K_BOUND: controller=0 channel=4 pci_source=0x404000000 bytes=%u guarded_backend=1 dma_completed=0\n",
           BACKUP_DATA_BYTES);
}
