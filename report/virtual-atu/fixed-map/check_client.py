#!/usr/bin/env python3
import hashlib
import importlib.util
import json
from pathlib import Path
import sys

here = Path(__file__).resolve().parent
path = here.parents[1]/'virtual-dma330/dma330-kernel-client-abi/check_elf.py'
spec = importlib.util.spec_from_file_location('module_abi', path)
abi = importlib.util.module_from_spec(spec)
spec.loader.exec_module(abi)
name = 'sony_atu_map' if '--atu' in sys.argv else 'sony_fixed_io'
module = abi.ELF(here/(name+'.ko'))
module.descriptor(name, [(0x158, 257, 'init_module', 0)])
module.no_versions()
imports = {s['name'] for s in module.symbols if s['shndx'] == 0 and s['name']}
abi.require(imports == {'ioremap_page_range', 'printk'}, 'unexpected imports')
abi.require(all(r['type'] in {257, 283} for r in module.relocs), 'unsupported relocations')
abi.require(not any(s['name'] == 'cleanup_module' for s in module.symbols), 'mapping owner remains resident')
print(json.dumps({'scope':'host ABI only; no guest load', 'size':len(module.raw),
                  'sha256':hashlib.sha256(module.raw).hexdigest(), 'imports':sorted(imports)}, indent=2))
