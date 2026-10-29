    /* Opt-in Sony memory DMA experiment. Resources were read from the original
     * running kernel's UDIF records, not inferred from a successful submit.
     * Data movement and event generation are performed by the stock PL330.
     */
    if (g_getenv("QEMU_SONY_DMA330")) {
        MemoryRegion *bus = g_new0(MemoryRegion, 1);
        MemoryRegion *dram = g_new0(MemoryRegion, 1);
        MemoryRegion *sram = g_new0(MemoryRegion, 1);
        const hwaddr bases[2] = { 0xf1056000, 0xf1057000 };
        const unsigned event_spi[2] = { 80, 113 };
        const unsigned abort_spi[2] = { 112, 145 };

        memory_region_init(bus, OBJECT(vms), "sony-dma330-bus", 1ULL << 32);
        /* Original arch_p32_to_p64: <= fdffffff gains bit34; fe000000..
         * feffffff is identity; ff000000..ffffffff is rejected. These aliases
         * refer to actual system backing. Unbacked accesses remain faults.
         */
        memory_region_init_alias(dram, OBJECT(vms), "sony-dma330-dram",
                                 sysmem, 0x400000000ULL, 0xfe000000ULL);
        memory_region_add_subregion(bus, 0, dram);
        memory_region_init_alias(sram, OBJECT(vms), "sony-dma330-sram",
                                 sysmem, 0xfe000000, 0x1000000);
        memory_region_add_subregion(bus, 0xfe000000, sram);

        for (unsigned controller = 0; controller < 2; controller++) {
            DeviceState *dma = qdev_new("pl330");
            SysBusDevice *sbd = SYS_BUS_DEVICE(dma);
            object_property_set_link(OBJECT(dma), "memory", OBJECT(bus),
                                     &error_fatal);
            qdev_prop_set_uint32(dma, "num_chnls", 8);
            qdev_prop_set_uint8(dma, "num_events", 8);
            /* Original programs use non-secure DMAGO (a2). Model these eight
             * event resources as non-secure: do not turn a completed copy's
             * DMASEV into EVENT_ERR just because stock INS defaults to zero.
             * The PL330 still executes WMB/SEV and checks every transaction.
             */
            qdev_prop_set_uint32(dma, "INS", 0xff);
            sysbus_realize_and_unref(sbd, &error_fatal);
            memory_region_add_subregion_overlap(sysmem, bases[controller],
                                                 sysbus_mmio_get_region(sbd, 0), 1);
            sysbus_connect_irq(sbd, 0,
                               qdev_get_gpio_in(vms->gic, abort_spi[controller]));
            for (unsigned event = 0; event < 8; event++) {
                sysbus_connect_irq(sbd, event + 1,
                                   qdev_get_gpio_in(vms->gic,
                                                    event_spi[controller] + event));
            }
        }
    }
