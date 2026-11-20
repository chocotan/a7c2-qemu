#!/usr/bin/env python3
"""Compose the SCU/5xDW-I2C boot batch over the exact accepted GPIO stage."""
import argparse
import hashlib
import json
from pathlib import Path

HERE=Path(__file__).resolve().parent
PROFILE='virtual-cp-boot-peripherals-v1'
SCHEMA='a7c2-cp-peripherals-stage-v6'
PARENT_SHA='79041461b7b834ef3c1610bb98eff521574d567c5f789d5eb7d62b65b7d67c1e'
FRESH_PARENT_SHA='1efa461744f73cea3199f2dd14cd0b361608c9d0760e1e4b99069e732b618a14'
PARENT_SHAS=(PARENT_SHA,FRESH_PARENT_SHA)
BASES={
 'hw/core/null-machine.c':'9ddd3e6dc7eff63eb8a328be723d56f8202d61112fe9c4c63c098435eb51c5e0',
 'hw/arm/Kconfig':'75fb56926a49c78fa387ac8ac3813afb65bf471999db409d29eb30f88deef7fc',
 'hw/misc/meson.build':'9721ba5a49048114ed7e91b6297aee7bbf77c8bc4e1ac26d57aa8c11869882ad',
 'hw/arm/virt.c':'cfeaf610e44199db5d6076084933c8cda5ca506bdf7117ea478d44b18a72384e',
 'hw/gpio/notify-qemu.c':'a7f4031567c724700420259ac5bcc3170349ed5a15f5e55fcbca0dada03ecda4',
}
UPSTREAM={
 'hw/i2c/designware_i2c.c':'48035387864db59e0eb376447672174cc892d6a7ce46349a26abd37152d68785',
 'include/hw/i2c/designware_i2c.h':'1fd1c92862820002f324ce6bb394c3c456ff8c1e3aae10ec516c022f74145866',
 'hw/i2c/Kconfig':'64065413fe35e304b44c68f9fe71677ec14a5592552820b06be149717e9295c1',
 'hw/dma/pl330.c':'e34d68bd9a30854c8b616a3b6fc582ca6db8498a250096e11d0b61dd3f017cba',
 'hw/dma/pl080.c':'0a1a151fefe1e3b987dc760522970ef6257110aafbf7c396e13bfefab60832f4',
 'hw/char/pl011.c':'bd7961c4f1f9caaf85ed04f17fe6754ece40b957868b3ea896bdb23b9c9fabf9',
 'hw/ssi/pl022.c':'a98f4f14ccb322696f08341051d978f7524a72a68ac35d7d3041ad12081fec48',
 'include/hw/ssi/pl022.h':'5d0787394b1c2a12c74eb83be3ad6b772ce492d01be69600d4f94349a360f73e',
 'hw/ssi/ssi.c':'2b0e06eeca9d4566db5bb0e5e0bdfd9ed82e16c4db3ff4fb4ea26161f6ef7d73',
 'include/hw/char/pl011.h':'8b3ef84c7ccb26b35e2ee4386638572c03d34b06afd525b18ded90891c2f83f6',
 'ui/input.c':'619089241c78af002e296ce54627ae2a30cb3421dc8684e8d879471e3af43b83',
 'include/ui/input.h':'7ebddaca72c431b3fd91fd4b96fb5c23d2bdd99b416da655625339b8d515426f',
 'qapi/ui.json':'87ac10949caa0da383eaba3d0676f078915bed9ea96025a6c7fb1c08135548ba',
}
FILES=('scu.h','scu.c','scu-qemu.c','pl080-route-qemu.c','tpu.h','tpu.c','tpu-qemu.c',
       'native-edma-qemu.c','native-peer-ram-qemu.c','native-link-board.h',
       'native-link-cp.inc','native-link-ap.inc','native-notify-qemu.c','component-gic-groups-qemu.c',
       'native-key-gpio-qemu.c','native-key-gpio-init.h')
PRODUCT=HERE.parent.parent
RUNTIME_SOURCES={**{'report/virtual-pcidma/hardware/'+n:n for n in ('registers.h','registers.c','lli.h','lli.c')},
                 **{'report/virtual-atu/hardware/'+n:n for n in ('sony_atu.c','atu_core.h','atu_core.c')}}
ANCHOR='    if (g_getenv("QEMU_CP_EDMA_GATE")) {'
INSERT='''    const char *peripherals = g_getenv("QEMU_CP_BOOT_PERIPHERALS");
    if (peripherals) {
        if (strcmp(peripherals, "virtual-cp-boot-peripherals-v1")) {
            error_report("Unknown CP boot peripheral profile");
            exit(1);
        }
        if (!cp_wdt) {
            error_report("CP boot peripherals require the original watchdog for shared SRST4");
            exit(1);
        }
        DeviceState *dw[5];
        for (unsigned bank = 0; bank < 5; bank++) {
            dw[bank] = qdev_new(TYPE_DESIGNWARE_I2C);
            SysBusDevice *bus = SYS_BUS_DEVICE(dw[bank]);
            sysbus_realize_and_unref(bus, &error_fatal);
            /* Original CP ctx INTID table + raw GICD ISENABLER path. */
            sysbus_connect_irq(bus, 0, qdev_get_gpio_in(gic, 429 + bank - 32));
        }
        DeviceState *dma[2];
        for (unsigned controller = 0; controller < 2; controller++) {
            dma[controller] = qdev_new("pl330");
            object_property_set_link(OBJECT(dma[controller]), "memory", OBJECT(get_system_memory()), &error_fatal);
            qdev_prop_set_uint8(dma[controller], "num_events", 8);
            qdev_prop_set_uint8(dma[controller], "num_periph_req", 32);
            SysBusDevice *bus = SYS_BUS_DEVICE(dma[controller]);
            sysbus_realize_and_unref(bus, &error_fatal);
            sysbus_connect_irq(bus, 0, qdev_get_gpio_in(gic, 344 + controller * 33 - 32));
            for (unsigned event = 0; event < 8; event++) {
                sysbus_connect_irq(bus, 1 + event,
                    qdev_get_gpio_in(gic, 312 + controller * 33 + event - 32));
            }
        }
        DeviceState *pl080_router[2];
        for (unsigned controller = 0; controller < 2; controller++) {
            DeviceState *engine = qdev_new("pl080");
            object_property_set_link(OBJECT(engine), "downstream", OBJECT(get_system_memory()), &error_fatal);
            sysbus_realize_and_unref(SYS_BUS_DEVICE(engine), &error_fatal);
            pl080_router[controller] = qdev_new("a7c2-cp-pl080");
            object_property_set_link(OBJECT(pl080_router[controller]), "controller", OBJECT(engine), &error_fatal);
            SysBusDevice *router_bus = SYS_BUS_DEVICE(pl080_router[controller]);
            sysbus_realize_and_unref(router_bus, &error_fatal);
            for (unsigned channel = 0; channel < 8; channel++) {
                sysbus_connect_irq(router_bus, channel,
                    qdev_get_gpio_in(gic, 378 + controller * 8 + channel - 32));
            }
        }
        DeviceState *tpu[6];
        for (unsigned bank = 0; bank < 6; bank++) {
            tpu[bank] = qdev_new("a7c2-cp-tpu");
            qdev_prop_set_uint32(tpu[bank], "bank", bank);
            SysBusDevice *tpu_bus = SYS_BUS_DEVICE(tpu[bank]);
            sysbus_realize_and_unref(tpu_bus, &error_fatal);
            sysbus_mmio_map(tpu_bus, 0, 0xf100b000 + bank * 0x1000);
        }
        DeviceState *scu = qdev_new("a7c2-cp-scu");
        for (unsigned bank = 0; bank < 5; bank++) {
            char property[8];
            snprintf(property, sizeof(property), "i2c%u", bank);
            object_property_set_link(OBJECT(scu), property, OBJECT(dw[bank]), &error_fatal);
        }
        object_property_set_link(OBJECT(scu), "dma0", OBJECT(dma[0]), &error_fatal);
        object_property_set_link(OBJECT(scu), "dma1", OBJECT(dma[1]), &error_fatal);
        object_property_set_link(OBJECT(scu), "dma2", OBJECT(pl080_router[0]), &error_fatal);
        object_property_set_link(OBJECT(scu), "dma3", OBJECT(pl080_router[1]), &error_fatal);
        object_property_set_link(OBJECT(scu), "watchdog", OBJECT(cp_wdt), &error_fatal);
        for (unsigned bank = 0; bank < 6; bank++) {
            char property[8];
            snprintf(property, sizeof(property), "tpu%u", bank);
            object_property_set_link(OBJECT(scu), property, OBJECT(tpu[bank]), &error_fatal);
        }
        SysBusDevice *bus = SYS_BUS_DEVICE(scu);
        sysbus_realize_and_unref(bus, &error_fatal);
        for (unsigned group = 0; group < 9; group++) {
            sysbus_mmio_map(bus, group, 0xf1388000 + group * 0x10);
        }
        const unsigned reset_group[] = {0,1,2,3,5};
        for (unsigned i = 0; i < 5; i++) {
            /* SRST4 is composed separately; WDT_MISC remains with its owner. */
            memory_region_add_subregion_overlap(get_system_memory(),
                0xf1388300 + reset_group[i] * 0x10,
                sysbus_mmio_get_region(bus, 9 + i), 2);
            sysbus_mmio_map(bus, 14 + i, 0xf1012000 + i * 0x1000);
        }
        for (unsigned i = 0; i < 4; i++) {
            sysbus_mmio_map(bus, 19 + i, 0xf1056000 + i * 0x1000);
        }
        memory_region_add_subregion_overlap(get_system_memory(), 0xf1388340,
            sysbus_mmio_get_region(bus, 23), 2);
        /* CP DFS selector: SCU+0xf48, not the AP selector at SCU+0xf50. */
        sysbus_mmio_map(bus, 24, 0xf1388f48);
        Clock *uart_clock = clock_new(OBJECT(mch), "cp-functional-uart-clock");
        clock_set_hz(uart_clock, 12000000);
        for (unsigned i = 0; i < 5; i++) {
            char name[24];
            snprintf(name, sizeof(name), "cp-uart%u", i);
            Chardev *chr = qemu_chr_find(name);
            if (!chr) {
                chr = qemu_chr_new(name, "null", NULL);
            }
            if (!chr) {
                error_report("Cannot create CP UART backend");
                exit(1);
            }
            DeviceState *uart = qdev_new(TYPE_PL011);
            qdev_prop_set_chr(uart, "chardev", chr);
            qdev_connect_clock_in(uart, "clk", uart_clock);
            SysBusDevice *uart_bus = SYS_BUS_DEVICE(uart);
            sysbus_realize_and_unref(uart_bus, &error_fatal);
            sysbus_mmio_map(uart_bus, 0, 0xf1000000 + i * 0x1000);
            /* CP UART IRQ identity is not established; polling/TX still work. */
        }
    }
'''


def sha(data):return hashlib.sha256(data).hexdigest()


def once(text,old,new):
    if text.count(old)!=1:raise ValueError('Unknown native link board anchor: '+old[:80])
    return text.replace(old,new)


def target_path(tree,name):
    relative=Path(name)
    if relative.is_absolute() or '..' in relative.parts:
        raise ValueError('Unsafe peripheral source path')
    path=tree
    for part in relative.parts:
        path=path/part
        if path.is_symlink():raise ValueError('Peripheral source path cannot contain symlinks')
    return path


def validate_receipt(proof,inherited):
    if type(proof) is not dict or any(type(proof.get(field)) is not dict for field in
            ('base_sha256','inherited_sources','upstream_sources','sources','runtime_sources','outputs')):
        raise ValueError('Peripheral receipt source tables must be objects')
    destinations={('hw/gpio/notify-qemu.c' if name=='native-notify-qemu.c' else 'hw/misc/a7c2-cp/'+name) for name in FILES}
    destinations.update('hw/misc/a7c2-cp/'+name for name in RUNTIME_SOURCES.values())
    expected_outputs=set(BASES)|destinations
    if (proof.get('schema')!=SCHEMA or proof.get('profile')!=PROFILE or
        proof.get('default_off') is not True or proof.get('parent_stage_sha256') not in PARENT_SHAS or
        proof.get('base_sha256')!=BASES or proof.get('inherited_sources')!=inherited or
        proof.get('upstream_sources')!=UPSTREAM or set(proof.get('sources',{}))!=set(FILES) or
        set(proof.get('runtime_sources',{}))!=set(RUNTIME_SOURCES) or
        set(proof.get('outputs',{}))!=expected_outputs or
        proof.get('native_link_profile')!='virtual-native-ap-cp-link-v1' or proof.get('native_link_default_off') is not True or
        proof.get('component_secure_groups_profile')!='virtual-native-component-gic-groups-v1' or
        proof.get('component_secure_groups_default_off') is not True or
        proof.get('component_secure_groups_base')!=0x0b020000 or proof.get('component_secure_groups_bytes')!=0x40 or
        proof.get('key_gpio_profile')!='virtual-cp-key-gpio-v1' or proof.get('key_gpio_default_off') is not True or
        proof.get('key_gpio_physical_mapping_verified') is not False or
        proof.get('cp_dfs_base')!=0xf1388f48 or proof.get('cp_dfs_bytes')!=0x14 or
        proof.get('cp_dfs_physical_compatible') is not False or proof.get('cp_dfs_clocks_changed') is not False or
        proof.get('p1_spi_component_profile')!='virtual-p1-pl022-component-v1' or
        proof.get('p1_spi_component_default_off') is not True or proof.get('p1_spi_peer_verified') is not False or
        proof.get('p1_dma_max_bytes')!=24*1024*1024 or
        proof.get('ap_gpio_output_readback_profile')!='virtual-native-ap-gpio-output-readback-v1' or
        proof.get('ap_gpio_output_readback_default_off') is not True or
        proof.get('ap_gpio_output_readback_mask')!=0x300 or
        proof.get('ap_gpio_output_source')!='local-port18-wdata-latch' or
        proof.get('ap_gpio_output_physical_readback_verified') is not False or

        any(proof.get(field) is not False for field in ('physical_compatible','virtual_reset_measured','forced_slave_ack','tpu_runtime_supported',
            'pl080_scu_reset_route_verified','native_physical_edge_encoding_verified','native_local_ram_unified'))):
        raise ValueError('Unknown or incomplete CP peripheral stage')
    for name in FILES:
        target = 'hw/gpio/notify-qemu.c' if name=='native-notify-qemu.c' else 'hw/misc/a7c2-cp/'+name
        if (sha(target_path(HERE,name).read_bytes())!=proof['sources'].get(name) or
                proof['outputs'].get(target)!=proof['sources'].get(name)):
            raise ValueError('Peripheral model source or staged copy changed')
    for name,digest in proof['runtime_sources'].items():
        target='hw/misc/a7c2-cp/'+RUNTIME_SOURCES[name]
        if sha(target_path(PRODUCT,name).read_bytes())!=digest or proof['outputs'].get(target)!=digest:
            raise ValueError('Shared runtime model source or staged copy changed')


def stage(tree):
    tree=Path(tree).resolve(strict=True)
    parent_path=tree/'cp-notify-stage.json'
    parent_digest=sha(parent_path.read_bytes())
    if parent_path.is_symlink() or parent_digest not in PARENT_SHAS:
        raise ValueError('Known GPIO parent stage differs')
    parent=json.loads(parent_path.read_text())
    inherited={k:v for k,v in {**parent['inherited_sources'],**parent['outputs'],**UPSTREAM}.items() if k not in BASES}
    for name,digest in inherited.items():
        path=target_path(tree,name)
        if sha(path.read_bytes())!=digest:
            raise ValueError('Inherited/upstream source drift: '+name)
    receipt=target_path(tree,'cp-peripherals-stage.json')
    if receipt.exists():
        proof=json.loads(receipt.read_text())
        if proof.get('parent_stage_sha256')!=parent_digest:
            raise ValueError('Peripheral receipt belongs to a different parent')
        validate_receipt(proof,inherited)
        for name,digest in proof['outputs'].items():
            path=target_path(tree,name)
            if sha(path.read_bytes())!=digest:
                raise ValueError('Staged peripheral source drift')
        return proof
    originals={}
    for name,digest in BASES.items():
        path=target_path(tree,name)
        if sha(path.read_bytes())!=digest:
            raise ValueError('CP peripheral base identity differs: '+name)
        originals[name]=path.read_bytes()
    board=originals['hw/core/null-machine.c'].decode()
    include='#include "hw/core/qdev-properties.h"'
    gate='    if (g_getenv("QEMU_CP_GIC")) {'
    if board.count(ANCHOR)!=1 or board.count(include)!=1 or board.count(gate)!=1:
        raise ValueError('Unknown CP peripheral board anchors')
    board=board.replace(include,include+'\n#include "hw/i2c/designware_i2c.h"\n#include "hw/char/pl011.h"\n#include "hw/core/clock.h"\n#include "hw/core/qdev-clock.h"\n#include "hw/misc/a7c2-cp/native-link-board.h"')
    watchdog_anchor='    if (g_getenv("QEMU_CP_WATCHDOG")) {'
    watchdog_new='        DeviceState *wdt = qdev_new("sony-cp-wdt");'
    if board.count(watchdog_anchor)!=1 or board.count(watchdog_new)!=1:
        raise ValueError('Unknown original watchdog ownership anchors')
    board=board.replace(watchdog_anchor,'    DeviceState *cp_wdt = NULL;\n'+watchdog_anchor)
    board=board.replace(watchdog_new,watchdog_new+'\n        cp_wdt = wdt;')
    board=board.replace(ANCHOR,INSERT+ANCHOR)
    board=board.replace(gate,'''    if (g_getenv("QEMU_CP_BOOT_PERIPHERALS") && !g_getenv("QEMU_CP_GIC")) {
        error_report("CP peripherals require the explicit CP GIC model");
        exit(1);
    }
'''+gate)
    group_anchor='    if (g_getenv("QEMU_CP_TIMERS")) {'
    board=once(board,group_anchor,'''    const char *component_groups = g_getenv("QEMU_NATIVE_COMPONENT_GIC_GROUPS");
    if (component_groups) {
        if (strcmp(component_groups, "virtual-native-component-gic-groups-v1") || !native_link_enabled("cp")) {
            error_report("Unknown component secure GIC group profile");
            exit(1);
        }
        DeviceState *groups = qdev_new("a7c2-component-gic-groups");
        object_property_set_link(OBJECT(groups), "controller", OBJECT(gic), &error_fatal);
        SysBusDevice *groups_bus = SYS_BUS_DEVICE(groups);
        sysbus_realize_and_unref(groups_bus, &error_fatal);
        sysbus_mmio_map(groups_bus, 0, 0x0b020000);
    }
'''+group_anchor)
    board=once(board,'static void cp_attach_gic(MachineState *mch)','static DeviceState *cp_attach_gic(MachineState *mch)')
    board=once(board,'    }\n}\n\nstatic void machine_none_init',
                     '    }\n    return gic;\n}\n\nstatic void machine_none_init')
    board=once(board,'    const char *notify = g_getenv("QEMU_AP_CP_GPIO_LINES");',
                     '''    bool native_link = native_link_enabled("cp");
    const char *key_profile = g_getenv("QEMU_CP_KEY_GPIO_PROFILE");
    if (key_profile && (strcmp(key_profile, "virtual-cp-key-gpio-v1") || !native_link)) {
        error_report("Virtual keyboard GPIO requires explicit native CP profile");
        exit(1);
    }
    DeviceState *notify_device = NULL;
    const char *notify = g_getenv("QEMU_AP_CP_GPIO_LINES");''')
    board=once(board,'        qdev_prop_set_string(dev, "side", side);',
                     '        notify_device = dev;\n        qdev_prop_set_bit(dev, "native-cp-inputs", native_link);\n        qdev_prop_set_bit(dev, "edge-doorbells", native_link);\n        qdev_prop_set_bit(dev, "native-key-inputs", key_profile != NULL);\n        qdev_prop_set_string(dev, "side", side);')
    board=once(board,'        sysbus_mmio_map(bus, 1, 0xf102f000);',
                     '        sysbus_mmio_map(bus, 1, 0xf102f000);\n        if (native_link) {\n            sysbus_mmio_map(bus, 2, 0xf102d000);\n        }')
    oom='''        memory_region_init_ram(oom, NULL, "cp-uipc-oom", 0x101000,
                               &error_fatal);'''
    board=once(board,oom,'''        if (native_link) {
            g_free(oom);
            oom = a7c2_native_local_oom(mch, &error_fatal);
        } else {
'''+oom+'''\n        }''')
    board=once(board,gate,'''    if (native_link) {
        native_link_peer_memory(mch, "cp");
    }
'''+gate)
    board=once(board,'        cp_attach_gic(mch);','''        DeviceState *gic = cp_attach_gic(mch);
        if (native_link && notify_device) {
            /* Original IRQ records EB020c/EB0228 and raw GICD path. */
            sysbus_connect_irq(SYS_BUS_DEVICE(notify_device), 0,
                               qdev_get_gpio_in(gic, 0x122 - 32));
            sysbus_connect_irq(SYS_BUS_DEVICE(notify_device), 1,
                               qdev_get_gpio_in(gic, 0x121 - 32));
            if (key_profile) {
                DeviceState *keys = qdev_new("a7c2-cp-key-gpio");
                object_property_add_child(OBJECT(mch), "native-key-gpio", OBJECT(keys));
                qdev_prop_set_string(keys, "profile", key_profile);
                SysBusDevice *keys_bus = SYS_BUS_DEVICE(keys);
                sysbus_realize_and_unref(keys_bus, &error_fatal);
                const unsigned key_ports[] = {6, 7, 11};
                for (unsigned bank = 0; bank < 3; bank++) {
                    sysbus_mmio_map(keys_bus, bank, 0xf101d000 + key_ports[bank] * 0x1000);
                    qdev_connect_gpio_out_named(keys, "key-17", bank,
                        qdev_get_gpio_in_named(notify_device, "keyboard-input", bank));
                }
                device_cold_reset(keys);
            }
        }''')
    board=once(board,'        if (g_getenv("QEMU_CP_EDMA_DIRECT")) {',
                     (HERE/'native-link-cp.inc').read_text()+'        if (g_getenv("QEMU_CP_EDMA_DIRECT")) {')
    virt=originals['hw/arm/virt.c'].decode()
    virt=once(virt,'#include "qemu/osdep.h"\n','#include "qemu/osdep.h"\n#include "hw/misc/a7c2-cp/native-link-board.h"\n')
    virt=once(virt,'    create_gic(vms, sysmem);\n','    create_gic(vms, sysmem);\n'+(HERE/'native-link-ap.inc').read_text())
    virt=once(virt,'        qdev_prop_set_string(dev, "side", "ap");',
                   '        qdev_prop_set_bit(dev, "edge-doorbells", native_link_enabled("ap"));\n        qdev_prop_set_bit(dev, "native-ap-output-readback", native_link_enabled("ap"));\n        qdev_prop_set_string(dev, "side", "ap");')
    config=originals['hw/arm/Kconfig'].decode()
    config_anchor='config ARM_VIRT\n    bool\n'
    if config.count(config_anchor)!=1:raise ValueError('Unknown ARM_VIRT Kconfig anchor')
    planned={'hw/core/null-machine.c':board.encode(),'hw/arm/virt.c':virt.encode(),
        'hw/arm/Kconfig':config.replace(config_anchor,config_anchor+'    select DESIGNWARE_I2C\n    select PL330\n    select PL080\n    select PL011\n').encode(),
        'hw/misc/meson.build':originals['hw/misc/meson.build']+b"system_ss.add(when: 'CONFIG_ARM_VIRT', if_true: files('a7c2-cp/scu.c', 'a7c2-cp/scu-qemu.c', 'a7c2-cp/pl080-route-qemu.c', 'a7c2-cp/tpu.c', 'a7c2-cp/tpu-qemu.c', 'a7c2-cp/native-edma-qemu.c', 'a7c2-cp/native-peer-ram-qemu.c', 'a7c2-cp/registers.c', 'a7c2-cp/lli.c', 'a7c2-cp/sony_atu.c', 'a7c2-cp/atu_core.c', 'a7c2-cp/component-gic-groups-qemu.c', 'a7c2-cp/native-key-gpio-qemu.c'))\n"}
    sources={}
    for name in FILES:
        target='hw/gpio/notify-qemu.c' if name=='native-notify-qemu.c' else 'hw/misc/a7c2-cp/'+name
        if target_path(tree,target).exists() and target not in BASES:raise ValueError('Unowned peripheral destination')
        data=target_path(HERE,name).read_bytes();planned[target]=data;sources[name]=sha(data)
    runtime_sources={}
    for name,filename in RUNTIME_SOURCES.items():
        target='hw/misc/a7c2-cp/'+filename
        if target_path(tree,target).exists():raise ValueError('Unowned shared runtime model destination')
        path=target_path(PRODUCT,name)
        data=path.read_bytes();planned[target]=data;runtime_sources[name]=sha(data)
    backup=tree/'cp-peripherals-before';backup.mkdir()
    for name,data in originals.items():
        path=backup/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(data)
        if path.read_bytes()!=data:raise ValueError('Peripheral backup readback differs')
    for name,data in planned.items():
        path=target_path(tree,name);path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(data)
        if path.read_bytes()!=data:raise ValueError('Peripheral source readback differs')
    proof=dict(schema=SCHEMA,profile=PROFILE,default_off=True,
        parent_stage_sha256=parent_digest,base_sha256=BASES,inherited_sources=inherited,sources=sources,runtime_sources=runtime_sources,
        outputs={name:sha(data) for name,data in planned.items()},upstream_sources=UPSTREAM,
        i2c_bases=[0xf1012000+i*0x1000 for i in range(5)],i2c_intids=list(range(429,434)),
        clock_bits=list(range(18,23)),reset_bits=list(range(24,29)),
        watchdog_original_semantics_preserved=True,shared_srst4_proxy=True,watchdog_misc_shadowed=False,
        cp_dfs_base=0xf1388f48,cp_dfs_bytes=0x14,cp_dfs_physical_compatible=False,cp_dfs_clocks_changed=False,
        p1_spi_component_profile='virtual-p1-pl022-component-v1',p1_spi_component_default_off=True,p1_spi_peer_verified=False,
        p1_dma_max_bytes=24*1024*1024,
        tpu_bases=[0xf100b000+i*0x1000 for i in range(6)],tpu_configuration_only=True,tpu_runtime_supported=False,
        pl330_bases=[0xf1056000,0xf1057000],pl330_event_intids=[list(range(312,320)),list(range(345,353))],
        pl330_abort_intids=[344,377],pl080_bases=[0xf1058000,0xf1059000],
        pl080_channel_intids=list(range(378,394)),pl080_aggregate_irq_directly_wired=False,
        pl080_scu_reset_route_verified=False,
        uart_bases=[0xf1000000+i*0x1000 for i in range(5)],
        uart_clock_hz=12000000,uart_irq_wired=False,
        native_link_profile='virtual-native-ap-cp-link-v1',native_link_default_off=True,
        native_cp_intids=[0x122,0x121],native_ap_intids=[92,91],native_ap_edma_intid=198,
        native_cp_bank16_reset_inen_virtual=4,native_edge_policy='both-validated-peer-output-transitions',
        native_physical_edge_encoding_verified=False,native_local_ram_unified=False,
        component_secure_groups_profile='virtual-native-component-gic-groups-v1',component_secure_groups_default_off=True,
        component_secure_groups_base=0x0b020000,component_secure_groups_bytes=0x40,
        key_gpio_profile='virtual-cp-key-gpio-v1',key_gpio_default_off=True,key_gpio_physical_mapping_verified=False,
        key_gpio_ports=[6,7,11],key_gpio17_pins=[9,12,18],key_gpio_virtual_policy='F1..F13 pressed-low released-high',
        ap_gpio_output_readback_profile='virtual-native-ap-gpio-output-readback-v1',
        ap_gpio_output_readback_default_off=True,ap_gpio_output_readback_mask=0x300,
        ap_gpio_output_source='local-port18-wdata-latch',ap_gpio_output_physical_readback_verified=False,
        physical_compatible=False,virtual_reset_measured=False,forced_slave_ack=False)
    with receipt.open('x') as stream:stream.write(json.dumps(proof,indent=2,sort_keys=True)+'\n')
    return proof


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('qemu_source',type=Path)
    print(json.dumps(stage(parser.parse_args().qemu_source),indent=2))
