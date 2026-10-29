#!/usr/bin/env python3
import hashlib
import importlib.util
import json
from pathlib import Path
HERE=Path(__file__).resolve().parent
path=HERE.parents[1]/'virtual-dma330/dma330-kernel-client-abi/check_elf.py'
spec=importlib.util.spec_from_file_location('virtual_cp_sender_abi',path)
abi=importlib.util.module_from_spec(spec);spec.loader.exec_module(abi)
module=abi.ELF(HERE/'sony_virtual_cp_send.ko')
module.descriptor('sony_virtual_cp_send',[(0x158,257,'init_module',0)]);module.no_versions()
imports={s['name'] for s in module.symbols if s['shndx']==0 and s['name']}
abi.require(imports=={'printk','osal_reg_public'},'normal exported APIs only')
abi.require(all(r['type'] in (257,282,283) for r in module.relocs),'unsupported relocation')
abi.require(not any(s['name']=='cleanup_module' for s in module.symbols),'must remain resident')
print(json.dumps({'scope':'normal exported osal_reg_public ABI only; capture-only tap, not a real CP or runtime proof',
    'size':len(module.raw),'sha256':hashlib.sha256(module.raw).hexdigest(),'imports':sorted(imports)},indent=2))
