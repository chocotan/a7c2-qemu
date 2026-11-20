        if (native_link_enabled("cp")) {
            Object *view = object_resolve_path_component(OBJECT(mch), "native-peer-view");
            if (!view) {
                error_report("Native CP peer view missing before eDMA realization");
                exit(1);
            }
            DeviceState *edma = qdev_new("a7c2-native-edma");
            object_property_add_child(OBJECT(mch), "native-edma", OBJECT(edma));
            object_property_set_link(OBJECT(edma), "local-memory", OBJECT(get_system_memory()), &error_fatal);
            object_property_set_link(OBJECT(edma), "pci-memory",
                OBJECT(sysbus_mmio_get_region(SYS_BUS_DEVICE(view), 0)), &error_fatal);
            SysBusDevice *edma_bus = SYS_BUS_DEVICE(edma);
            sysbus_realize_and_unref(edma_bus, &error_fatal);
            sysbus_mmio_map(edma_bus, 0, 0xf6780000);
            for (unsigned i = 0; i < 16; i++) {
                sysbus_connect_irq(edma_bus, 1 + i,
                    qdev_get_gpio_in_named(gate, "edma", i));
            }
        }
