#!/usr/bin/env python3
import hashlib
import importlib.util
import json
from pathlib import Path
HERE = Path(__file__).resolve().parent
path = HERE.parents[1] / 'virtual-dma330/dma330-kernel-client-abi/check_elf.py'
spec = importlib.util.spec_from_file_location('yc_inject_abi', path)
abi = importlib.util.module_from_spec(spec)
spec.loader.exec_module(abi)
module = abi.ELF(HERE / 'yc_inject.ko')
module.descriptor('yc_inject', [(0x158, 257, 'init_module', 0)])
entry = module.named('init_module')
abi.require(entry['shndx'] == module.sections.index(module.byname['.init.text']) and
            entry['size'] > 0 and entry['info'] == 18, 'init_module must be defined code')
abi.require(not any(s['name'] == 'cleanup_module' for s in module.symbols),
            'diagnostic must remain resident while DMM buffers are shared')
module.no_versions()
imports = {s['name'] for s in module.symbols if s['shndx'] == 0 and s['name']}
expected = {'printk', 'osal_reg_msg_queue_cb', 'osal_unreg_msg_queue_cb',
            'osal_valloc_msg_wait', 'osal_set_msg_src', 'osal_snd_msg',
            'osal_free_msg', 'osal_msg_size', 'osal_get_msg_src', 'memremap', 'memunmap', 'msleep',
            'filp_open', 'kernel_read', 'filp_close'}
abi.require(imports <= expected, f'unexpected imports: {sorted(imports - expected)}')
abi.require(all(r['type'] in (257, 282, 283) for r in module.relocs), 'unsupported relocation')
print(json.dumps({
    'scope': 'normal exported osal_uipc + memremap APIs only; YC IN1 injection diagnostic, not a real CMOS or consumption proof',
    'size': len(module.raw), 'sha256': hashlib.sha256(module.raw).hexdigest(),
    'imports': sorted(imports),
    'sources_sha256': {name: hashlib.sha256((HERE/name).read_bytes()).hexdigest()
                       for name in ('yc_inject.c','unit-info.h','descriptor.S','build.sh','check_module.py')}
}, indent=2))
