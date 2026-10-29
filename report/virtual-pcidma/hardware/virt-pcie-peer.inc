    /* Independent, default-off TEST topology. It does not simulate Sony PHY
     * status or fabricate its host-init notification. The old bare-peer mode
     * remains a separate diagnostic profile.
     */
    bool sony_backup_test = g_strcmp0(g_getenv("QEMU_SONY_BACKUP_TEST"), "1") == 0;
    if (sony_backup_test && g_strcmp0(g_getenv("QEMU_SONY_PCIE_PEER_TEST"), "1") != 0) {
        error_report("Backup test window requires the explicit PCIe peer");
        exit(1);
    }
    if (g_strcmp0(g_getenv("QEMU_SONY_PCIE_PEER_TEST"),"1")==0) {
        if (g_strcmp0(g_getenv("QEMU_SONY_ATU_TEST"),"1")==0) {
            error_report("PCIe BAR peer and bare ATU test peer profiles are exclusive");
            exit(1);
        }
        PCIDevice *port=pci_new(PCI_DEVFN(1,0),"pcie-root-port");
        qdev_prop_set_uint8(DEVICE(port),"chassis",1);
        qdev_prop_set_uint16(DEVICE(port),"slot",1);
        pci_realize_and_unref(port,vms->bus,&error_fatal);
        if (g_strcmp0(g_getenv("QEMU_SONY_PCIE_DBI_TEST"),"1")==0) {
            DeviceState *dbi=qdev_new("a7c2-test-root-dbi");
            object_property_add_child(OBJECT(vms),"a7c2-test-dbi",OBJECT(dbi));
            object_property_set_link(OBJECT(dbi),"port",OBJECT(port),&error_fatal);
            sysbus_realize_and_unref(SYS_BUS_DEVICE(dbi),&error_fatal);
            memory_region_add_subregion_overlap(sysmem,0xf7000000,sysbus_mmio_get_region(SYS_BUS_DEVICE(dbi),0),3);
            memory_region_add_subregion_overlap(sysmem,0xf11c0000,sysbus_mmio_get_region(SYS_BUS_DEVICE(dbi),1),3);
        }
        PCIBus *secondary=pci_bridge_get_sec_bus(PCI_BRIDGE(port));
        PCIDevice *peer_device=pci_new(PCI_DEVFN(0,0),"a7c2-test-pcie-peer");
        /* Link setters resolve canonical QOM paths. Parent the owner before
         * creating/linking its RAM; an unparented target resolves to NULL.
         */
        object_property_add_child(OBJECT(vms),"a7c2-test-peer-function",OBJECT(peer_device));
        MemoryRegion *peer, *observe=g_new0(MemoryRegion,1);
        if (sony_backup_test) {
            qdev_prop_set_bit(DEVICE(peer_device), "backup-control", true);
            if (g_getenv("QEMU_SONY_BACKUP_FILE")) {
                qdev_prop_set_string(DEVICE(peer_device), "initial-image",
                                     g_getenv("QEMU_SONY_BACKUP_FILE"));
            }
        } else {
            peer = g_new0(MemoryRegion, 1);
            memory_region_init_ram(peer,OBJECT(peer_device),"a7c2-test-pcie-ram",16*MiB,&error_fatal);
            object_property_set_link(OBJECT(peer_device),"memory",OBJECT(peer),&error_fatal);
            assert(object_property_get_link(OBJECT(peer_device),"memory",&error_abort)==OBJECT(peer));
        }
        pci_realize_and_unref(peer_device,secondary,&error_fatal);
        peer = sony_test_peer_memory(peer_device);
        if (sony_backup_test) {
            /* Explicit primary-only virtual decode, independent of BAR gating;
             * it is not a claim about NOR/CP hardware address aliases.
             */
            MemoryRegion *backup = g_new0(MemoryRegion, 1);
            memory_region_init_alias(backup, OBJECT(vms), "sony-backup-pci",
                                     peer, 0, 2 * MiB);
            memory_region_add_subregion(vms->bus->address_space_mem,
                                        0x404000000ULL, backup);
            DeviceState *atu = qdev_new("sony-virtual-atu");
            SysBusDevice *atu_sbd = SYS_BUS_DEVICE(atu);
            object_property_add_child(OBJECT(vms), "sony-backup-atu", OBJECT(atu));
            object_property_set_link(OBJECT(atu), "pci-memory",
                                     OBJECT(vms->bus->address_space_mem), &error_fatal);
            sysbus_realize_and_unref(atu_sbd, &error_fatal);
            memory_region_add_subregion_overlap(sysmem, 0xf7300000,
                sysbus_mmio_get_region(atu_sbd, 0), 2);
            memory_region_add_subregion_overlap(sysmem, 0xc0000000,
                sysbus_mmio_get_region(atu_sbd, 1), 1);
            /* Official host ranges are PCI==CPU at dffe0000; this TEST profile
             * uses the 64MiB guarded-control extension from iomap_board. */
            MemoryRegion *host_window = g_new0(MemoryRegion, 1);
            memory_region_init_alias(host_window, OBJECT(vms), "sony-backup-host-window",
                                     vms->bus->address_space_mem, 0xdffe0000, 64 * MiB);
            memory_region_add_subregion_overlap(sysmem, 0xdffe0000, host_window, 2);
        }
        memory_region_init_alias(observe,OBJECT(vms),"a7c2-test-pcie-observe",peer,0,16*MiB);
        memory_region_add_subregion_overlap(sysmem,0x600000000ULL,observe,1);
        DeviceState *edma=qdev_new("sony-virtual-pcidma");
        SysBusDevice *edma_sbd=SYS_BUS_DEVICE(edma);
        object_property_add_child(OBJECT(vms),"sony-pcidma-test",OBJECT(edma));
        object_property_set_link(OBJECT(edma),"local-memory",OBJECT(sysmem),&error_fatal);
        object_property_set_link(OBJECT(edma),"pci-memory",OBJECT(vms->bus->address_space_mem),&error_fatal);
        if (sony_backup_test) {
            qdev_prop_set_uint64(edma, "max-bytes", 2 * MiB);
        }
        sysbus_realize_and_unref(edma_sbd,&error_fatal);
        memory_region_add_subregion_overlap(sysmem,0xf7380000,sysbus_mmio_get_region(edma_sbd,0),2);
        sysbus_connect_irq(edma_sbd,0,qdev_get_gpio_in(vms->gic,166));
        if (sony_backup_test) sony_test_peer_attach_dma(peer_device, edma);
        if (g_getenv("QEMU_SONY_PHY_INIT_TEST")) {
            Object *phyobj=object_resolve_path("/machine/sony-pcie-scu-test",NULL);
            if (!phyobj) {
                error_report("PHY init profile requires its SCU/PHY device first");
                exit(1);
            }
            object_property_set_link(phyobj,"port",OBJECT(port),&error_fatal);
            object_property_set_link(phyobj,"peer",OBJECT(peer_device),&error_fatal);
            /* Deferred from virt-pcie-scu.inc: links must precede realize. */
            sysbus_realize(SYS_BUS_DEVICE(phyobj),&error_fatal);
            static const hwaddr bases[]={0xf1388000,0xf1388300,0xf11e0380,0xf1160380,
                0xf11a0380,0xf1220380,0xf1120380};
            for(unsigned i=0;i<7;i++) {
                memory_region_add_subregion_overlap(sysmem,bases[i],
                    sysbus_mmio_get_region(SYS_BUS_DEVICE(phyobj),i),4);
            }
            static const hwaddr extra[]={0xf11c0000,0xf11e0384,0xf7000000,0x602000000ULL,
                0xdffc0000,0xdffd0000};
            for(unsigned i=0;i<6;i++) {
                /* DBI window priority stays below the already explicit ATU device. */
                memory_region_add_subregion_overlap(sysmem,extra[i],
                    sysbus_mmio_get_region(SYS_BUS_DEVICE(phyobj),7+i),i==2?1:5);
            }
        }
    }
