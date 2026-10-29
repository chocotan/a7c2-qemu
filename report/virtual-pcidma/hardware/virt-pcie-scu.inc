    /* Explicit finite SCU profile. Never overlap the separate Root-DBI profile. */
    if (g_getenv("QEMU_SONY_CCF_TEST") && !g_getenv("QEMU_SONY_PCIE_SCU_TEST")) {
        error_report("TEST CCF requires explicit TEST SCU profile");
        exit(1);
    }
    if (g_getenv("QEMU_SONY_PHY_INIT_TEST") &&
        (!g_getenv("QEMU_SONY_CCF_TEST") || g_getenv("QEMU_SONY_PHY_SRAM_TEST"))) {
        error_report("TEST timed PHY SRAM clearing requires CCF profile and excludes data-only profile");
        exit(1);
    }
    if (g_getenv("QEMU_SONY_PCIE_SCU_TEST")) {
        if (!g_getenv("QEMU_SONY_PCIE_PEER_TEST") || g_getenv("QEMU_SONY_PCIE_DBI_TEST")) {
            error_report("TEST SCU requires TEST peer and excludes Root DBI profile");
            exit(1);
        }
        static const hwaddr bases[]={0xf1388080,0xf1388310,0xf11e0380,0xf1160380,
            0xf11a0380,0xf1220380,0xf1120380};
        bool ccf=g_getenv("QEMU_SONY_CCF_TEST")!=NULL;
        bool phy=g_getenv("QEMU_SONY_PHY_INIT_TEST")!=NULL;
        DeviceState *scu=qdev_new(phy?"a7c2-test-scu-phy-init":ccf?"a7c2-test-scu-ccf":"a7c2-test-pcie-scu");
        object_property_add_child(OBJECT(vms),"sony-pcie-scu-test",OBJECT(scu));
        /* PHY profile defers realize+mapping: its port/peer links only exist
         * after the TEST peer topology is created (see virt-pcie-peer.inc). */
        if (!phy) {
            sysbus_realize_and_unref(SYS_BUS_DEVICE(scu),&error_fatal);
            for(unsigned i=0;i<7;i++) {
                hwaddr base=ccf && i==0?0xf1388000:ccf && i==1?0xf1388300:bases[i];
                memory_region_add_subregion_overlap(sysmem,base,
                    sysbus_mmio_get_region(SYS_BUS_DEVICE(scu),i),4);
            }
        }
    }
    if (g_getenv("QEMU_SONY_PHY_SRAM_TEST")) {
        if (!g_getenv("QEMU_SONY_CCF_TEST")) {
            error_report("TEST PHY SRAM data consumer requires explicit CCF/SCU/peer profile");
            exit(1);
        }
        DeviceState *sram=qdev_new("a7c2-test-phy-sram");
        object_property_add_child(OBJECT(vms),"sony-phy-sram-test",OBJECT(sram));
        sysbus_realize_and_unref(SYS_BUS_DEVICE(sram),&error_fatal);
        memory_region_add_subregion_overlap(sysmem,0xf11d8000,
            sysbus_mmio_get_region(SYS_BUS_DEVICE(sram),0),5);
        memory_region_add_subregion_overlap(sysmem,0xf11e00ac,
            sysbus_mmio_get_region(SYS_BUS_DEVICE(sram),1),5);
    }
    /* Independent virtual selector policy; no PHY/PCI gates or clocks change. */
    if (g_getenv("QEMU_SONY_DFS_TEST")) {
        DeviceState *dfs=qdev_new("a7c2-virtual-dfs-selector");
        object_property_add_child(OBJECT(vms),"sony-dfs-test",OBJECT(dfs));
        sysbus_realize_and_unref(SYS_BUS_DEVICE(dfs),&error_fatal);
        memory_region_add_subregion_overlap(sysmem,0xf1388f50,
            sysbus_mmio_get_region(SYS_BUS_DEVICE(dfs),0),5);
    }
