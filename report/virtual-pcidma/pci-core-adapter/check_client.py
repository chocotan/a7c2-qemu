#!/usr/bin/env python3
import hashlib
import importlib.util
import json
from pathlib import Path
HERE=Path(__file__).resolve().parent
path=HERE.parents[1]/'virtual-dma330/dma330-kernel-client-abi/check_elf.py'
spec=importlib.util.spec_from_file_location('pci_core_module_abi',path)
abi=importlib.util.module_from_spec(spec);spec.loader.exec_module(abi)
m=abi.ELF(HERE/'sony_pci_core.ko');m.descriptor('sony_pci_core',[(0x158,257,'init_module',0)]);m.no_versions()
imports={s['name'] for s in m.symbols if s['shndx']==0 and s['name']}
expected={'udif_ioremap','pci_add_resource','pci_free_resource_list','pci_scan_root_bus',
 'pci_bus_size_bridges','pci_bus_assign_resources','pci_bus_add_devices','pci_find_bus',
 'pci_get_domain_bus_and_slot','pci_lock_rescan_remove','pci_unlock_rescan_remove','printk'}
abi.require(imports==expected,'unexpected imports')
abi.require(all(r['type'] in (257,283) for r in m.relocs),'unsupported relocation')
abi.require(not any(s['name']=='cleanup_module' for s in m.symbols),'must remain resident')
init=m.named('init_module')
init_section=m.sections[init['shndx']]['name']
init_calls=[r['symbol'] for r in m.relocs if r['section']==init_section and r['type']==283]
abi.require(init_calls==['printk'],'blocked init must not call prototype or PCI APIs')
abi.require(not any(s['name'].startswith('__ksymtab_') for s in m.symbols),'prototype must not be exported')
ops=m.named('sony_pci_ops');abi.require(ops['size']==40,'original ops extent')
for callback,offset in (('sony_pci_config_read',0x18),('sony_pci_config_write',0x20)):
    symbol=m.named(callback);section=m.sections[symbol['shndx']]
    abi.require(section['name']=='.text' and symbol['size']>0,'callback must survive init retirement')
    matches=[r for r in m.relocs if r['symbol']==callback and r['type']==257 and
             r['section']==m.sections[ops['shndx']]['name'] and r['offset']==ops['value']+offset]
    abi.require(len(matches)==1,'original ops callback slot')
print(json.dumps({'scope':'module ABI only; host control/platform hooks/runtime need separate evidence',
 'size':len(m.raw),'sha256':hashlib.sha256(m.raw).hexdigest(),'imports':sorted(imports),
 'runtime_blocked':True,'blocked_reason':'original wildcard Root Port fixup casts sysdata to DW context',
 'runtime_verified':False},indent=2))
