    if (native_link_enabled("ap")) {
        const char *p1_spi = g_getenv("QEMU_NATIVE_P1_SPI_COMPONENT");
        if (p1_spi && strcmp(p1_spi, "virtual-p1-pl022-component-v1")) {
            error_report("Unknown P1 SPI component profile");
            exit(1);
        }
        MemoryRegion *pci = native_link_peer_memory(MACHINE(vms), "ap");
        DeviceState *edma = qdev_new("a7c2-native-edma");
        object_property_add_child(OBJECT(vms), "native-edma", OBJECT(edma));
        object_property_set_link(OBJECT(edma), "local-memory", OBJECT(sysmem), &error_fatal);
        object_property_set_link(OBJECT(edma), "pci-memory", OBJECT(pci), &error_fatal);
        if (p1_spi) qdev_prop_set_uint64(edma, "max-bytes", UINT64_C(24) * 1024 * 1024);
        SysBusDevice *dma_bus = SYS_BUS_DEVICE(edma);
        sysbus_realize_and_unref(dma_bus, &error_fatal);
        memory_region_add_subregion_overlap(sysmem, 0xf7380000,
            sysbus_mmio_get_region(dma_bus, 0), 3);
        /* Original AP resource0 LinuxIRQ198 = GIC SPI166. */
        sysbus_connect_irq(dma_bus, 0, qdev_get_gpio_in(vms->gic, 198 - 32));
        DeviceState *atu = qdev_new("sony-virtual-atu");
        object_property_add_child(OBJECT(vms), "native-atu", OBJECT(atu));
        object_property_set_link(OBJECT(atu), "pci-memory", OBJECT(pci), &error_fatal);
        SysBusDevice *atu_bus = SYS_BUS_DEVICE(atu);
        sysbus_realize_and_unref(atu_bus, &error_fatal);
        memory_region_add_subregion_overlap(sysmem, 0xf7300000,
            sysbus_mmio_get_region(atu_bus, 0), 3);
        memory_region_add_subregion_overlap(sysmem, 0xc0000000,
            sysbus_mmio_get_region(atu_bus, 1), 3);
        if (p1_spi) {
            DeviceState *spi = qdev_new("pl022");
            object_property_add_child(OBJECT(vms), "p1-spi-component", OBJECT(spi));
            SysBusDevice *spi_bus = SYS_BUS_DEVICE(spi);
            sysbus_realize_and_unref(spi_bus, &error_fatal);
            memory_region_add_subregion_overlap(sysmem, 0xf1017000,
                sysbus_mmio_get_region(spi_bus, 0), 3);
            /* OSS SPI0 GIC SPI193; no BootROM/SSI peer or ready response. */
            sysbus_connect_irq(spi_bus, 0, qdev_get_gpio_in(vms->gic, 193));
        }
    }
