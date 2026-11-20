#!/usr/bin/env python3
"""DRAFT, NOT RUN. Requires a future independent tree with candidate.patch applied."""
import argparse
import ast
import hashlib
import importlib.util
import json
from pathlib import Path
import struct
import sys
import tempfile


EXPECTED_MODULES = (
    ('usbg_buspower', 'usbg_buspower.ko',
     'final/a7c2-qemu/runtime/analysis/menu-root/usr/kmod/usbg_buspower.ko',
     'dd0681bf59ea4132db498afdd236188235dafb640adcc5c0d822c96359889232'),
    ('usb_beets', 'usb_beets.ko',
     'final/a7c2-qemu/runtime/analysis/menu-root/usr/kmod/usb_beets.ko',
     '2988e06ad49cd9c56c1b6ee9563f58b1cb03a003bf9767e287defb4d3d482c60'),
    ('usb_buspwr', 'usb_buspwr.ko',
     'final/a7c2-qemu/runtime/analysis/menu-root/usr/kmod/usb_buspwr.ko',
     'fcf9efaf116a76ca4bcebff829c111ebf3c77929e4bfae3a9b277b24bdd00c41'),
)


def validate_modules(modules, root):
    actual = tuple(tuple(m.get(k) for k in ('name', 'file', 'source', 'sha256'))
                   for m in modules)
    if actual != EXPECTED_MODULES:
        raise ValueError('Exact ordered name/file/source/original-SHA list required')
    for _, _, relative, digest in EXPECTED_MODULES:
        source = root / relative
        if (source.is_symlink() or any(p.is_symlink() for p in source.parents)
                or not source.is_file()):
            raise ValueError('Ordinary pinned module source required')
        if hashlib.sha256(source.read_bytes()).hexdigest() != digest:
            raise ValueError('Original module SHA mismatch')


def test_default_stage(stage, workdir):
    # Fail on any candidate-only helper call, even if it happens to write nothing.
    def forbidden(*args):
        raise AssertionError('Default stage reached BusPower branch')
    saved = stage.buspower_stage_inputs, stage.buspower_stage_files
    stage.buspower_stage_inputs = stage.buspower_stage_files = forbidden
    source = Path(tempfile.mkdtemp(prefix='buspower-default-', dir=workdir))
    # Retain this small fixture on failure; the future test owner accounts for it.
    print('default stage fixture:', source)
    try:
        (source / 'hw/arm').mkdir(parents=True)
        (source / 'hw/usb').mkdir()
        board = source / 'hw/arm/virt.c'
        meson = source / 'hw/usb/meson.build'
        config = source / 'hw/arm/Kconfig'
        board.write_text('#include "hw/arm/virt.h"\nvoid draft(void) {\n    create_msi_controller(vms);\n}\n')
        meson.write_text('# unchanged baseline\n')
        config.write_text('config ARM_VIRT\n    bool\n')
        original_config = config.read_bytes()
        receipt = stage.stage(source)
        assert config.read_bytes() == original_config
        assert receipt['schema'] == 'a7c2-product-sony-usb-device-build-v1'
        assert receipt['default_enabled'] is False
        provider = (source / 'hw/arm/sony-usb-device-platform.inc').read_text()
        assert '#define SONY_USB_BUSPOWER_CANDIDATE' not in provider
        assert 'BusPower requires USB device profile' not in board.read_text()
        assert 'beets-core.c' not in meson.read_text()
        assert 'CONFIG_USB' in meson.read_text()
        assert not any((source / 'hw/usb' / name).exists()
                       for name in (*stage.BUSPOWER_FILES, *stage.BUSPOWER_SCU))
        assert not set(stage.BUSPOWER_FILES) & set(receipt['product_sources'])
    finally:
        stage.buspower_stage_inputs, stage.buspower_stage_files = saved


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--integrated-project', type=Path, required=True)
    parser.add_argument('--workdir', type=Path, required=True,
                        help='Existing dedicated project task directory; never /tmp')
    args = parser.parse_args()
    root = args.integrated_project.resolve(strict=True)
    draft = Path(__file__).resolve().parents[1]
    workdir = args.workdir.resolve(strict=True)
    assert workdir.is_dir() and workdir.is_relative_to(root)
    analysis = root / 'final/a7c2-qemu/runtime/analysis'
    sys.path.insert(0, str(analysis))
    assets = load('candidate_assets', analysis / 'prepare-assets.py')
    assert hasattr(assets, 'usb_buspower_imdb'), 'Independent patched source required'
    data = (analysis / 'menu-root/usr/lib/libIMDB.so').read_bytes()
    msc, bp = assets.usb_msc_imdb(data), assets.usb_buspower_imdb(data)
    elf = assets.ELF(msc)
    off = elf.offset(0x1e740, 4)
    assert bp[:off] == msc[:off] and bp[off + 4:] == msc[off + 4:]
    assert struct.unpack_from('<I', msc, off)[0] == 0xffffffb8
    assert struct.unpack_from('<I', bp, off)[0] == 0xffffffbf
    assert assets.ELF(bp).number(0x1e860, '<I') == 0xffffff98
    assert sum(a != b for a, b in zip(msc, bp)) == 1
    assert assets.USB_MSC_INIT == {'libInfraUsbCmn.so', 'libUsbControl.so'}
    assert hashlib.sha256(bp).hexdigest() == assets.USB_BUSPOWER_IMDB_SHA
    cold = load('candidate_cold', analysis / 'original_cold_boot.py')
    assert not cold.usb_buspower_candidate({})
    good = dict(A7C2_ORIGINAL_COLD='original-init-v1', A7C2_USB_MSC='1',
                A7C2_SONY_USB_DEVICE='virtual-functional-sony-usb-device-v1',
                A7C2_USB_BUSPOWER_MODEL='virtual-a7c2-usb-buspower-v1')
    assert cold.usb_buspower_candidate(good)
    try:
        cold.usb_imdb(good, draft / 'must-not-exist')
    except ValueError as exc:
        assert 'Source-only BusPower candidate' in str(exc)
    else:
        raise AssertionError('Unaccepted candidate reached payload generation')
    for key, value in [('A7C2_USB_BUSPOWER_MODEL', ''), ('A7C2_USB_BUSPOWER_MODEL', '0'),
                       ('A7C2_USB_BUSPOWER_MODEL', 'wrong'), ('A7C2_USB_MSC', '0'),
                       ('A7C2_USB_SENSER', ''), ('MENU_BUSPOWER', '0'),
                       ('A7C2_ORIGINAL_COLD', 'wrong'), ('A7C2_SONY_USB_DEVICE', None)]:
        bad = dict(good, **{key: value})
        try:
            cold.usb_buspower_candidate(bad)
        except ValueError:
            pass
        else:
            raise AssertionError((key, value))
    modules = json.loads((draft / 'modules.json').read_text())['modules']
    validate_modules(modules, root)
    negatives = [modules[:-1], modules + [dict(modules[0])],
                 list(reversed(modules))]
    for i in range(3):
        for key in ('name', 'file', 'source', 'sha256'):
            bad = [dict(m) for m in modules]
            bad[i][key] += '.renamed'
            negatives.append(bad)
    for bad in negatives:
        try:
            validate_modules(bad, root)
        except ValueError:
            pass
        else:
            raise AssertionError('Mutated module identity accepted: ' + repr(bad))
    stage = load('candidate_stage', root / 'final/a7c2-qemu/source/usb-device/stage.py')
    test_default_stage(stage, workdir)
    tree = ast.parse((analysis / 'original_cold_boot.py').read_text())
    init_values = [n for n in ast.walk(tree) if isinstance(n, ast.Dict) and
                   any(isinstance(k, ast.Constant) and k.value == 'MENU_BUSPOWER' for k in n.keys)]
    assert len(init_values) == 1
    observer = (analysis / 'menu-observe.c').read_text()
    assert observer.count('getenv("MENU_BUSPOWER") && !getenv("MENU_OBSERVE_SELFTEST")') == 1
    assert observer.count('start_bus_power_module();') == 1


if __name__ == '__main__':
    main()
