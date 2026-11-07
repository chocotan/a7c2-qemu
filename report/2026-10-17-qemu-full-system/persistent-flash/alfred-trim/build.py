#!/usr/bin/env python3
"""Build an opt-in variant in fresh scratch, using the official native p1 builder."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import runpy
import shutil

HERE = Path(__file__).resolve().parent
BASE_SHA = '15b6a84827a0d6e2925ea4fd6f9d17b6b820aedf0e6b790706b90ab4300b2b9f'
KNOWN_MODULE_SHA = '5d069cd2c2eb5fbbd9d933e4768a65b0b71e3505fadcf245d5541a2e99a74383'
KNOWN_RECEIPT_SHA = '36cec193d065b2aa3873d68a699980e5b04a8703a85aeb1a3ea3f679edbeff50'
QEMU_SHA = '2c4ea6c9343771225915c604c4ab81ec2f45bb922e3365931710e295c4d9d83c'


def build(known_receipt, output):
    api = runpy.run_path(str(HERE.parents[1] / 'p1-persistent-module.py'))
    record, checked = api['record'], api['checked_path']
    known_receipt = checked(known_receipt)
    if record(known_receipt)['sha256'] != KNOWN_RECEIPT_SHA:
        raise ValueError('Exact known large-BIO .186 receipt required')
    known = json.loads(known_receipt.read_text())
    old_module = checked(known['module']['file']['path'])
    api['require_abi'](api['module_info'](old_module))
    if (known['status'] != 'compiled' or record(old_module)['sha256'] != KNOWN_MODULE_SHA
            or known['driver']['sony_persistent_flash.c']['sha256'] != BASE_SHA
            or known['exports']['status'] != 'verified' or known['exports']['required_count'] != 34):
        raise ValueError('Known base module/driver/export binding differs')
    output = checked(output, missing=True)
    project = api['PROJECT']
    allowed = project / 'analysis/scratch/p1-alfred-trim-batch-20261106'
    if not output.is_relative_to(allowed):
        raise ValueError('Output must be under the declared trim scratch directory')
    free = shutil.disk_usage(output.parent).free
    if free < 2 * 1024**3:
        raise ValueError('Need at least 2 GiB host free space before building')
    base_source = HERE.parent / 'sony_persistent_flash.c'
    if record(base_source)['sha256'] != BASE_SHA:
        raise ValueError('Frozen canonical driver drift')
    output.mkdir(mode=0o700)
    receipt = dict(schema='a7c2-p1-alfred-trim-zero-v1', status='building', commands=[],
                   profile='virtual-storage-alfred-trim-zero-v1',
                   required_module_parameters={'functional_alfred_trim_zero': 1},
                   physical_compatibility=False, guest_verified=False, installation_verified=False,
                   force_load_allowed=False, host_module_loaded=False, physical_devices_used=False,
                   space_free_before=free, space_reserve_required=2*1024**3,
                   known_receipt=record(known_receipt), known_module=record(old_module),
                   canonical_base=record(base_source), expected_qemu_sha256=QEMU_SHA,
                   inputs={n: record(HERE / n) for n in ('build.py', 'module.patch', 'trim-zero.h')})
    try:
        originals = Path(known['original_modules']['modules'][0]['file']['path']).parent.parent
        base = api['build'](Path(known['source']['path']), output / 'base',
                            original_p1_kernel=Path(known['original_kernel']['path']),
                            original_module_directory=originals)
        if base['status'] != 'compiled':
            raise RuntimeError('Native official base build failed: ' + base.get('error', 'unknown'))
        receipt['base_build_receipt'] = record(output / 'base/p1-persistent-module.json')
        module = output / 'variant'
        module.mkdir()
        for n in ('Makefile', 'sony_persistent_flash.c'):
            shutil.copyfile(output / 'base/module' / n, module / n)
        shutil.copyfile(HERE / 'trim-zero.h', module / 'trim-zero.h')
        api['command'](['patch', '--batch', '--fuzz=0', '--no-backup-if-mismatch', '-p0',
                        '-i', HERE / 'module.patch'], output, receipt, 'apply-patch', cwd=module)
        receipt['variant_source'] = {n: record(module / n) for n in ('Makefile', 'sony_persistent_flash.c', 'trim-zero.h')}
        receipt['variant_source_set_sha256'] = api['json_sha'](
            {n: r['sha256'] for n, r in receipt['variant_source'].items()})
        args = ['make', '-j2', '-C', output / 'base/kernel-source',
                'O=' + str(output / 'base/kernel-build'), 'ARCH=arm64',
                'CROSS_COMPILE=/usr/bin/aarch64-linux-gnu-', 'HOSTCC=/usr/bin/gcc-15',
                'LOCALVERSION=', 'KCFLAGS=-fno-pie', 'M=' + str(module), 'modules']
        api['command'](args, output, receipt, 'variant-build')
        ko = module / 'sony_persistent_flash.ko'
        info = api['module_info'](ko)
        api['require_abi'](info)
        if info['license'] != ['GPL'] or not any(
                s.startswith('functional_alfred_trim_zero:') for s in info['modinfo'].get('parmtype', [])):
            raise ValueError('Missing GPL license or explicit trim parameter')
        receipt['module'] = info
        symbols = api['command'](['aarch64-linux-gnu-readelf', '-sW', ko], output, receipt, 'variant-symbols')
        required = sorted(set(re.findall(r'^\s*\d+:\s+\S+\s+\d+\s+\S+\s+GLOBAL\s+DEFAULT\s+UND\s+(\S+)\s*$', symbols, re.M)))
        if not required:
            raise ValueError('Missing imports')
        receipt['undefined_symbols'] = required
        receipt['exports'] = api['original_exports'](Path(known['original_kernel']['path']).read_bytes(), required)
        if receipt['exports']['missing']:
            raise ValueError('Original kernel lacks variant imports')
        receipt['new_imports_vs_base34'] = sorted(set(required) - set(known['undefined_symbols']))
        receipt['kernel_sha256'] = base['original_kernel']['sha256']
        receipt['abi'] = dict(vermagic=info['vermagic'], struct_module_bytes=info['struct_module_bytes'],
                              struct_module_alignment=info['struct_module_alignment'],
                              versions_present=info['versions_present'], config_sha256=api['CONFIG_SHA'],
                              source_tree_sha256=api['TREE_SHA'], original_modules_sha256=api['MODULES_SHA'])
        if {n: record(module / n) for n in receipt['variant_source']} != receipt['variant_source']:
            raise ValueError('Variant inputs changed during build')
        if record(base_source) != receipt['canonical_base'] or record(old_module) != receipt['known_module']:
            raise ValueError('Frozen canonical source or known module changed')
        receipt.update(status='compiled', canonical_and_known_module_unchanged=True)
    except Exception as exc:
        receipt.update(status='failed', error=str(exc), error_type=type(exc).__name__)
    finally:
        (output / 'alfred-trim-module.json').write_text(json.dumps(receipt, indent=2) + '\n')
    return receipt


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--known-receipt', required=True, type=Path)
    p.add_argument('--output', required=True, type=Path)
    a = p.parse_args()
    r = build(a.known_receipt, a.output)
    print(json.dumps({k:r.get(k) for k in ('status', 'error', 'module', 'new_imports_vs_base34')}, indent=2))
    raise SystemExit(0 if r['status'] == 'compiled' else 1)
