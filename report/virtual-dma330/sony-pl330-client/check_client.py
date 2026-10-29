#!/usr/bin/env python3
import hashlib
import importlib.util
import json
from pathlib import Path

here = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('module_abi', here.parent/'dma330-kernel-client-abi/check_elf.py')
abi = importlib.util.module_from_spec(spec)
spec.loader.exec_module(abi)
module = abi.ELF(here/'sony_dma_probe.ko')
module.descriptor('sony_dma_probe', [(0x158, 257, 'init_module', 0)])
module.no_versions()
imports = {s['name'] for s in module.symbols if s['shndx'] == 0 and s['name']}
abi.require(imports == {'__get_free_pages', 'free_pages', 'arch_va_to_phys', 'flush_dcache_all',
                        'msleep', 'printk', 'dma330_mem_transfer_async'}, 'unexpected imports')
abi.require(all(r['type'] in {257, 283} for r in module.relocs), 'unsupported relocations')
abi.require('depends=dma330' in module.modinfo(), 'provider dependency')
abi.require(not any(s['name'] == 'cleanup_module' for s in module.symbols), 'owned request must remain resident')
print(json.dumps({'scope':'host ABI/import checks only, no original DMA yet',
                  'sha256':hashlib.sha256(module.raw).hexdigest(), 'size':len(module.raw),
                  'imports':sorted(imports), 'source_sha256':hashlib.sha256((here/'client.c').read_bytes()).hexdigest()}, indent=2))
