        if (g_strcmp0(g_getenv("QEMU_SONY_PCIDMA_TEST"),"1")==0) {
            DeviceState *edma=qdev_new("sony-virtual-pcidma");
            SysBusDevice *edma_sbd=SYS_BUS_DEVICE(edma);
            object_property_add_child(OBJECT(vms),"sony-pcidma-test",OBJECT(edma));
            object_property_set_link(OBJECT(edma),"local-memory",OBJECT(sysmem),&error_fatal);
            object_property_set_link(OBJECT(edma),"pci-memory",OBJECT(pci),&error_fatal);
            sysbus_realize_and_unref(edma_sbd,&error_fatal);
            memory_region_add_subregion_overlap(sysmem,0xf7380000,
                                                 sysbus_mmio_get_region(edma_sbd,0),2);
            /* Original resource0 LinuxIRQ198, corresponding GIC SPI input166. */
            sysbus_connect_irq(edma_sbd,0,qdev_get_gpio_in(vms->gic,166));
        }
