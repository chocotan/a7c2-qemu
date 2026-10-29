#!/usr/bin/env python3
"""Host-only ELF/import check, using the established project ABI reader."""
import hashlib
import importlib.util
import json
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
REPORT = HERE.parents[1]
ABI_PATH = REPORT/'virtual-dma330/dma330-kernel-client-abi/check_elf.py'
if not ABI_PATH.is_file():
    raise SystemExit('Established sibling dma330-kernel-client-abi/check_elf.py not found')
spec = importlib.util.spec_from_file_location('original_module_abi', ABI_PATH)
abi = importlib.util.module_from_spec(spec)
spec.loader.exec_module(abi)


def verify(path=HERE / 'sony_atu_client.ko'):
    module = abi.ELF(path)
    module.descriptor('sony_atu_client', [(0x158, 257, 'init_module', 0)])
    module.no_versions()
    imports = {s['name'] for s in module.symbols if s['shndx'] == 0 and s['name']}
    abi.require(imports == {'pciatu_map', 'pciatu_unmap', 'udif_ioremap', 'udif_iounmap', 'printk'},
                'unexpected imports')
    abi.require(all(r['type'] in {257, 283} for r in module.relocs), 'unsupported relocation; ABS64/CALL26 only')
    abi.require(set(module.modinfo()) == {
        'license=GPL', 'description=Original ATU TESTPCI peer diagnostic for isolated QEMU',
        'depends=pcieatu', 'vermagic=' + abi.VERMAGIC}, 'unexpected module metadata')
    abi.require(not any(s['name'] == 'cleanup_module' for s in module.symbols) and
                not any(s['name'].startswith('.exit') for s in module.sections), 'must remain resident: no exit')
    init = module.named('init_module')
    abi.require(init['shndx'] == module.sections.index(module.byname['.init.text']) and
                init['info'] == 18 and init['size'] > 0, 'init callback symbol/section')
    abi.require(module.byname['.init.text']['flags'] == 6, 'init flags')
    for name in imports:
        calls = [r for r in module.relocs if r['type'] == 283 and r['symbol'] == name]
        abi.require(bool(calls), 'missing ordinary imported call: ' + name)
    for r in module.relocs:
        target = module.byname[r['section']]
        width = 8 if r['type'] == 257 else 4
        abi.require(r['offset'] + width <= target['size'], 'relocation target bounds')
        if r['type'] == 283:
            abi.require(target['flags'] & 4 and
                        module.unpack('<I', target['offset'] + r['offset'])[0] & 0xfc000000 == 0x94000000,
                        'CALL26 must be ordinary BL')
    return {
        'status': 'PASS_HOST_ABI_ONLY',
        'scope': 'ELF ABI/import/relocation checks; no VM or hardware execution',
        'file': module.path.name, 'size': len(module.raw),
        'sha256': hashlib.sha256(module.raw).hexdigest(),
        'imports': sorted(imports), 'relocation_types': sorted({r['type'] for r in module.relocs}),
        'descriptor': {'size': 0x300, 'alignment': 64, 'name_offset': 0x18,
                       'init_offset': 0x158, 'exit': 'absent'},
        'abi_tool': str(ABI_PATH.relative_to(REPORT)),
        'abi_tool_sha256': hashlib.sha256(ABI_PATH.read_bytes()).hexdigest(),
        'source_sha256': hashlib.sha256((HERE / 'client.c').read_bytes()).hexdigest(),
        'runtime_gate': 'NOT_EVALUATED: use separate guest and independent content evidence'
    }


if __name__ == '__main__':
    print(json.dumps(verify(Path(sys.argv[1]) if len(sys.argv) > 1 else HERE / 'sony_atu_client.ko'), indent=2))
