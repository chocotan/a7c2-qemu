#!/usr/bin/env python3
import hashlib
import importlib.util
import json
from pathlib import Path
HERE=Path(__file__).resolve().parent
path=HERE.parents[1]/'virtual-dma330/dma330-kernel-client-abi/check_elf.py'
spec=importlib.util.spec_from_file_location('pcidma_xfer_abi',path)
abi=importlib.util.module_from_spec(spec);spec.loader.exec_module(abi)
module=abi.ELF(HERE/'sony_pcidma_xfer.ko')
module.descriptor('sony_pc_pci_dma_xfer',[(0x158,257,'init_module',0)]);module.no_versions()
imports={s['name'] for s in module.symbols if s['shndx']==0 and s['name']}
abi.require(imports=={'printk','get_zeroed_page','arch_va_to_phys','msleep',
    'pci_get_domain_bus_and_slot','pci_enable_device','pci_set_master','pci_bus_read_config_dword',
    'pcidma_connect','pcidma_transfer_async'},'normal exported APIs only')
# JUMP26 (282) is the unconditional-branch twin of CALL26; the kernel module
# loader handles both identically. It appears for the resident callback's
# cross-section printk call.
abi.require(all(r['type'] in (257,282,283) for r in module.relocs),'unsupported relocation')
abi.require(not any(s['name']=='cleanup_module' for s in module.symbols),'must remain resident')
print(json.dumps({'scope':'normal original PCI DMA APIs ABI only; not runtime or transfer proof',
    'size':len(module.raw),'sha256':hashlib.sha256(module.raw).hexdigest(),'imports':sorted(imports)},indent=2))
