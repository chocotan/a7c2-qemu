#!/usr/bin/env python3
import hashlib
import importlib.util
import json
from pathlib import Path

here = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('module_abi', here.parent/'dma330-kernel-client-abi/check_elf.py')
abi = importlib.util.module_from_spec(spec)
spec.loader.exec_module(abi)
module = abi.ELF(here/'sony_dma_map.ko')
module.descriptor('sony_dma_map', [(0x158, 257, 'init_module', 0)])
module.no_versions()
imports = {s['name'] for s in module.symbols if s['shndx'] == 0 and s['name']}
abi.require(imports == {'printk', 'udif_devices', 'udif_ioremap', 'udif_iounmap'}, 'unexpected imports')
abi.require(all(r['type'] in {257, 283} for r in module.relocs), 'unsupported relocation')
abi.require(not any(s['name'] == 'cleanup_module' for s in module.symbols), 'mapping owner must not unload')
print(json.dumps({'scope':'host ABI and imports; not loaded', 'sha256': hashlib.sha256(module.raw).hexdigest(),
                  'size':len(module.raw), 'imports': sorted(imports),
                  'source_sha256':hashlib.sha256((here/'adapter.c').read_bytes()).hexdigest()}, indent=2))
