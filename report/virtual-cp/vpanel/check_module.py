#!/usr/bin/env python3
import hashlib
import importlib.util
import json
from pathlib import Path
HERE = Path(__file__).resolve().parent
path = HERE.parents[1] / 'virtual-dma330/dma330-kernel-client-abi/check_elf.py'
spec = importlib.util.spec_from_file_location('vpanel_abi', path)
abi = importlib.util.module_from_spec(spec)
spec.loader.exec_module(abi)
module = abi.ELF(HERE / 'vpanel.ko')
module.descriptor('vpanel', [(0x158, 257, 'init_module', 0), (0x2b8, 257, 'cleanup_module', 0)])
module.no_versions()
imports = {s['name'] for s in module.symbols if s['shndx'] == 0 and s['name']}
expected = {'printk', 'osal_reg_public', 'osal_unreg_public',
            'osal_valloc_msg_wait', 'osal_set_msg_src', 'osal_snd_msg', 'osal_get_msg_src',
            'osal_free_msg'}
abi.require(imports <= expected, f'unexpected imports: {sorted(imports - expected)}')
abi.require(all(r['type'] in (257, 282, 283) for r in module.relocs), 'unsupported relocation')
print(json.dumps({
    'scope': 'normal exported osal_uipc APIs only; virtual panel backend for 200d:0118, not display hardware or a consumption proof',
    'size': len(module.raw), 'sha256': hashlib.sha256(module.raw).hexdigest(),
    'imports': sorted(imports)}, indent=2))
