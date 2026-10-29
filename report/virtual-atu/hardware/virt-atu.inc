    /* Experimental endpoint memory is explicit test backing, not a CP-ready
     * or CMOS claim. This entire board fragment is default-off.
     */
    if (g_strcmp0(g_getenv("QEMU_SONY_ATU_TEST"), "1") == 0) {
        MemoryRegion *pci = g_new0(MemoryRegion, 1);
        MemoryRegion *peer = g_new0(MemoryRegion, 1);
        MemoryRegion *observe = g_new0(MemoryRegion, 1);
        DeviceState *atu = qdev_new("sony-virtual-atu");
        SysBusDevice *sbd = SYS_BUS_DEVICE(atu);
        memory_region_init(pci, OBJECT(vms), "sony-test-pci-space", UINT64_MAX);
        memory_region_init_ram(peer, OBJECT(atu), "sony-test-pci-peer", 16 * MiB, &error_fatal);
        memory_region_add_subregion(pci, 0x04000000, peer);
        object_property_set_link(OBJECT(atu), "pci-memory", OBJECT(pci), &error_fatal);
        sysbus_realize_and_unref(sbd, &error_fatal);
        memory_region_add_subregion_overlap(sysmem, 0xf7300000,
                                             sysbus_mmio_get_region(sbd, 0), 1);
        memory_region_add_subregion_overlap(sysmem, 0xc0000000,
                                             sysbus_mmio_get_region(sbd, 1), 1);
        /* Outside the original kernel's declared RAM. This observation alias
         * lets tests compare actual peer backing with aperture transactions.
         */
        memory_region_init_alias(observe, OBJECT(vms), "sony-test-pci-observe", peer, 0, 16 * MiB);
        memory_region_add_subregion_overlap(sysmem, 0x600000000ULL, observe, 1);
    }
