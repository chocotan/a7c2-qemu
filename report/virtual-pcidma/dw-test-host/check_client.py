#!/usr/bin/env python3
import hashlib
import importlib.util
import json
from pathlib import Path
HERE=Path(__file__).resolve().parent
path=HERE.parents[1]/'virtual-dma330/dma330-kernel-client-abi/check_elf.py'
spec=importlib.util.spec_from_file_location('pci_core_module_abi',path)
abi=importlib.util.module_from_spec(spec);spec.loader.exec_module(abi)
m=abi.ELF(HERE/'sony_dw_test_host.ko');m.descriptor('sony_dw_test_host',[(0x158,257,'init_module',0)]);m.no_versions()
imports={s['name'] for s in m.symbols if s['shndx']==0 and s['name']}
expected={'udif_ioremap','pci_add_resource','pci_free_resource_list','pci_scan_root_bus',
 'pci_bus_size_bridges','pci_bus_assign_resources','pci_bus_add_devices','pci_find_bus',
 'pci_get_domain_bus_and_slot','pci_lock_rescan_remove','pci_unlock_rescan_remove','printk'}
abi.require(imports==expected,'unexpected imports')
abi.require(all(r['type'] in (257,283) for r in m.relocs),'unsupported relocation')
abi.require(not any(s['name']=='cleanup_module' for s in m.symbols),'must remain resident')
abi.require(not any(s['name'].startswith('__ksymtab_') for s in m.symbols),'test host must not publish new exports')
ops=m.named('sony_dw_ops');abi.require(ops['size']==40,'original ops extent')
for callback,offset in (('sony_dw_config_read',0x18),('sony_dw_config_write',0x20)):
    symbol=m.named(callback);section=m.sections[symbol['shndx']]
    abi.require(section['name']=='.text' and symbol['size']>0,'callback must survive init retirement')
    matches=[r for r in m.relocs if r['symbol']==callback and r['type']==257 and
             r['section']==m.sections[ops['shndx']]['name'] and r['offset']==ops['value']+offset]
    abi.require(len(matches)==1,'original ops callback slot')
print(json.dumps({'scope':'owned-context module ABI only; runtime needs separate evidence',
 'size':len(m.raw),'sha256':hashlib.sha256(m.raw).hexdigest(),'imports':sorted(imports),
 'owned_context_min_extent':0x168,'ops_extent':0x18,'pp_delta':0x20,
 'runtime_verified':False},indent=2))
