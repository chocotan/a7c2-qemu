#!/usr/bin/env python3
"""Source-bound P1 MMC identification slice. No original-module launcher.

source ROOT GPL KERNEL PRIOR_RESOURCE_RECEIPT NEW_OUTPUT
build SOURCE_RECEIPT PRODUCTION_QEMU_DIR NEW_OUTPUT

The one-register identification contract is closed. The four original module
initialization contract remains blocked; this tool cannot widen the updater's
seven-module allowlist or launch an original kernel/module experiment.
"""
import argparse
import ctypes
import hashlib
import json
import os
from pathlib import Path
import runpy
import subprocess

HERE = Path(__file__).resolve().parent
PROJECT = HERE.parents[1]
SCRATCH = PROJECT / 'analysis/scratch/p1-mmc-bootstrap-20261106'
PROBE = runpy.run_path(str(HERE / 'p1-module-probe.py'))
UPDATE = PROBE['UPDATE']
ABI = runpy.run_path(str(HERE / 'p1-persistent-module.py'))
BUILD = runpy.run_path(str(HERE / 'retained-persistent-build.py'))
PROFILE = 'original-p1-mmc-identification-v1'
PRIOR_SHA = 'a546973f95df3950ea29e950e16de1b46f9cef6e18719cc463c5f925d832bccd'
IO_SHA = '40be3a943f2273b5f84f67c0c6a5ebb8704e6d63ca18b0c33408ca865375cd37'
BOARD_SHA = 'fd8acceb826709d7834f4737a429db47df7ea71e3739dc58e3f7de1f7d0d9727'
QEMU_SHA = 'afad09ca01c16108e93cd2a1e980ee3b07796d7dda7e858fcf757bd68603e2c7'
MODULES = {
    'mcmn_drv': '84fd64a01715b88cfc08ea0e6c43bc9c73dd30703d481fcae2f42168344600f8',
    'mmc_drv': 'eb5ae29db913c2faad941df6b0439b2790781daa9f294157942b5794e6ceda4f',
    'nvme-core': '05e22b01cf52d1872e087b877f4ece0523373bd487ae205de6ab6b9077c17dfa',
    'nvme': '0f37469de0a80d1b038d0f8e0c9d3deefce4b9587694b1af1743dbe275415b1b',
}
ID_CONTRACT = dict(address='0xf13b8000', virtual='0xfffffffff13b8000', page_bytes=4096,
    access_bytes=4, byte_order='little', access='read-only', reset_value='0x1000',
    consumed_mask='0xf000', consumer='mmc_drv .text+0x2e010 -> mmc_os_read32; ubfx +0x2e014 #12,#4',
    virtual_revision=1, transition='reset -> identified on accepted read; any illegal IO -> sticky fault',
    w1c='not applicable: no writable register in this slice',
    unknown='MEMTX_ERROR, first fault retained, subsequent reads fail',
    card_present=False, sd_commands=False, dma=False, irq=False, physical_compatibility=False)
BLOCKERS = [
    dict(id='B1-mcmn-pcie-backup', stage='mcmnd_core_init -> mcmnd_pcie_init',
         evidence='mcmnd_pcie_arch_init .text+0x12a20 and setpciclk +0x12808',
         condition='g_mcmnd_pcie_param[0]==2 && [1]==3',
         missing='Actual Backup-derived parameter bytes and GPIO clock provider; branch not proven inactive',
         io='ioremap 0xf1220268/4; optional pci_find_bus then (read & 0x1f8200)==0xa0200 polling; GPIO mode 0x11',
         backup_ids=['0x00f90ae9', '0x00f90aea']),
    dict(id='B2-mcmn-prepower', stage='mcmnd_mediapwr_prepoweroncheck .text+0x11198',
         missing='Backup-derived power/insert branches, actual absent-media input and conditional power transitions',
         evidence='calls insmedia_checkinsertedmedia +0xfc60 and setmediapower +0x10c08'),
    dict(id='B3-original-owners', stage='RMCMND-RM/UIPC/DFS and MMC per-channel probe',
         missing='Actual original thread/queue/callback/node observations; init rc0 ignores mcmn child errors',
         evidence='mcmn .init.text+0x30..0x44; UIPC .text+0x1bf8 dynamic(0x2a,0xd9), callback0x80d9016e; RM waits0x8028017c',
         conditional_mmc_writes='get_ops_info +0x2ded8 writes SCU offsets0x4/0x308 if getmediapower==1'),
]


def sha(data):
    return hashlib.sha256(data).hexdigest()


def fresh(output):
    output = ABI['checked_path'](output, missing=True)
    if not output.is_relative_to(SCRATCH) or output == SCRATCH:
        raise ValueError('Output must be a fresh child of p1-mmc-bootstrap-20261106 scratch')
    output.mkdir(mode=0o700)
    return output


def save(path, value):
    PROBE['save'](path, value)


def exact(path, expected):
    row = ABI['record'](path)
    if row['sha256'] != expected:
        raise ValueError('Source identity differs: ' + str(path))
    return row


def window(path, section, start, size):
    from elftools.elf.elffile import ELFFile
    with Path(path).open('rb') as stream:
        elf = ELFFile(stream)
        data = elf.get_section_by_name(section).data()
        if start < 0 or size <= 0 or start + size > len(data):
            raise ValueError('Original source window outside section')
        raw = data[start:start + size]
        reloc = elf.get_section_by_name('.rela' + section)
        symtab = elf.get_section_by_name('.symtab')
        relocs = []
        for r in reloc.iter_relocations() if reloc else ():
            if start <= r['r_offset'] < start + size:
                symbol = symtab.get_symbol(r['r_info_sym'])
                name = symbol.name
                if not name and isinstance(symbol['st_shndx'], int):
                    name = elf.get_section(symbol['st_shndx']).name
                relocs.append(dict(offset=hex(r['r_offset']), kind=r['r_info_type'],
                                   symbol=name, addend=r['r_addend']))
        return dict(section=section, offset=hex(start), bytes=size, sha256=sha(raw),
                    raw_hex=raw.hex(), relocations=relocs)


def source(root, gpl, kernel, prior_receipt, output):
    """Reuse the 90-module inventory receipt; only recheck the eleven actual files."""
    os.umask(0o077)
    output = fresh(output)
    try:
        root, gpl = (ABI['checked_path'](p, directory=True) for p in (root, gpl))
        prior_row = exact(prior_receipt, PRIOR_SHA)
        prior = json.loads(Path(prior_receipt).read_text())
        kernel_row = exact(kernel, PROBE['KERNEL_SHA'])
        if (kernel_row['bytes'] != 6582280 or prior['inventory_count'] != 90 or
                prior['inventory_sha256'] != '1af381c5856713d4889c4b954a9f96ab0cd227fdbc6d8604009a9d30c1440b74'):
            raise ValueError('Original kernel/inventory receipt differs')
        io = exact(gpl / 'drivers/udif/io.c', IO_SHA)
        providers, modules, inputs = {}, [], [kernel_row, prior_row, io]
        kernel_raw = Path(kernel).read_bytes()
        for name in [r['path'].lstrip('/') for r in prior['modules']] + ['usr/kmod/' + n + '.ko' for n in MODULES]:
            path = root / name
            info = ABI['module_info'](path); ABI['require_abi'](info)
            expected = MODULES.get(path.stem)
            if expected is None:
                expected = next(r['file']['sha256'] for r in prior['modules'] if r['path'] == '/' + name)
            exact(path, expected)
            imported, exported = UPDATE['resource_symbols'](path)
            dependency = {n: providers[n] for n in imported if n in providers}
            exports = ABI['original_exports'](kernel_raw, sorted(set(imported) - dependency.keys()))
            if exports['missing']:
                raise ValueError('Unprovided original symbol: ' + name + ' ' + str(exports['missing']))
            sections = ABI['elf_sections'](path.read_bytes())
            if path.stem in ('mcmn_drv', 'mmc_drv') and ('__param' in sections or info['modinfo'].get('parm')):
                raise ValueError('Unexpected module parameters')
            modules.append(dict(path='/' + name, file=info['file'], vermagic=info['vermagic'],
                undefined_symbols=imported, exported_symbols=exported, module_providers=dependency,
                kernel_exports=exports, init_executed=False))
            inputs.append(info['file'])
            providers.update({r['name']: '/' + name for r in exported})
        script = exact(root / 'usr/bin/execute_ufp.sh', '08edf12a2b4b33a285866e88b94ef1d973bf50cec373dea6796d0ad52d5e6b9b')
        inputs.append(script)
        ranges = {
            'mmc_drv': [('.text', 0x15650, 0x80), ('.text', 0x2dfa8, 0x150),
                        ('.text', 0x1610, 0x10), ('.text', 0x25228, 0xb0),
                        ('.text', 0x2ded8, 0xd0), ('.init.text', 0, 0x1f0)],
            'mcmn_drv': [('.text', 0xc70, 0xf0), ('.text', 0x12a20, 0xb8),
                         ('.text', 0x12808, 0x198), ('.text', 0x11198, 0x178),
                         ('.text', 0x1bf8, 0x90), ('.text', 0x1468, 0xb0),
                         ('.text', 0xdd0, 0x250), ('.init.text', 0, 0x58)],
        }
        pins = {name: [window(root / ('usr/kmod/' + name + '.ko'), *r) for r in rows]
                for name, rows in ranges.items()}
        for name in ranges:
            result = subprocess.run(['aarch64-linux-gnu-objdump', '-dr', str(root / ('usr/kmod/' + name + '.ko'))],
                                    capture_output=True, timeout=30)
            (output / (name + '.disasm.txt')).write_bytes(result.stdout)
            (output / (name + '.stderr')).write_bytes(result.stderr)
            if result.returncode:
                raise RuntimeError('Original disassembly failed rc=' + str(result.returncode))
        result = dict(schema='a7c2.p1-mmc-bootstrap-source.v1', status='source-verified', profile=PROFILE,
            inputs=inputs, modules=modules, windows=pins, register_contract=ID_CONTRACT,
            identification_slice_closed=True, initialization_contract_closed=False,
            original_module_load_allowed=False, blockers=BLOCKERS,
            inventory_reused_from=prior_row, inventory_regenerated=False,
            physical_compatibility=False, original_module_init_verified=False,
            bodydata_installation_verified=False)
        save(output / 'source-receipt.json', result)
        return result
    except BaseException as error:
        save(output / 'failure.json', dict(error=type(error).__name__ + ': ' + str(error), guest_started=False))
        raise


def check_source(path):
    receipt, row = UPDATE['checked_json'](path)
    if (receipt.get('schema') != 'a7c2.p1-mmc-bootstrap-source.v1' or
            receipt.get('status') != 'source-verified' or receipt.get('profile') != PROFILE or
            receipt.get('register_contract') != ID_CONTRACT or receipt.get('blockers') != BLOCKERS or
            receipt.get('identification_slice_closed') is not True or
            receipt.get('initialization_contract_closed') is not False or
            receipt.get('original_module_load_allowed') is not False):
        raise ValueError('Only the source-bound identification slice may build')
    prior_row = next((r for r in receipt['inputs'] if r.get('sha256') == PRIOR_SHA), None)
    kernel_row = next((r for r in receipt['inputs'] if r.get('sha256') == PROBE['KERNEL_SHA']), None)
    io_row = next((r for r in receipt['inputs'] if r.get('sha256') == IO_SHA), None)
    if (not prior_row or not kernel_row or not io_row or kernel_row.get('bytes') != 6582280 or
            receipt.get('inventory_regenerated') is not False):
        raise ValueError('Original source/kernel/prior inventory bindings missing')
    for item in receipt['inputs']:
        PROBE['checked'](item)
    prior = json.loads(Path(prior_row['path']).read_text())
    expected = {m['path']: m['file']['sha256'] for m in prior['modules']}
    expected.update({'/usr/kmod/' + n + '.ko': h for n, h in MODULES.items()})
    modules = receipt['modules']
    if len(modules) != 11 or {m['path'] for m in modules} != set(expected):
        raise ValueError('Expected exact original seven plus four module bindings')
    for module in modules:
        if module['file']['sha256'] != expected[module['path']]:
            raise ValueError('Exact original module binding missing')
        exact(module['file']['path'], expected[module['path']])
        ABI['require_abi'](ABI['module_info'](module['file']['path']))
    return receipt, row


def build(source_receipt, template, output):
    """Recompile only virt.c and relink a reflink copy; production is read-only."""
    os.umask(0o077)
    receipt, receipt_row = check_source(source_receipt)
    template = ABI['checked_path'](template, directory=True)
    output = fresh(output)
    before = {n: BUILD['tree_files'](template / n) for n in ('qemu-11.1.2', 'build')}
    result = dict(schema='a7c2.p1-mmc-bootstrap-build.v1', status='started', profile=PROFILE,
        source_receipt=receipt_row, original_module_load_allowed=False,
        identification_slice_closed=True, initialization_contract_closed=False,
        original_module_init_verified=False, blockers=receipt['blockers'],
        physical_compatibility=False, original_kernel_executed=False)
    try:
        exact(template / 'build/qemu-system-aarch64', QEMU_SHA)
        exact(template / 'qemu-11.1.2/hw/arm/virt.c', BOARD_SHA)
        for name in before:
            subprocess.run(['cp', '-a', '--reflink=auto', str(template / name), str(output / name)],
                           check=True, capture_output=True, timeout=60)
            if BUILD['tree_files'](output / name) != before[name]:
                raise ValueError('Independent source/build copy differs')
        board = output / 'qemu-11.1.2/hw/arm/virt.c'
        if board.is_symlink() or board.stat().st_nlink != 1:
            raise ValueError('Private board source is aliased')
        text = board.read_text()
        text = BUILD['replace'](text, 'static void machvirt_init(MachineState *machine)\n',
            '#define P1_MMC_QEMU\n#include "p1-mmc-model.c"\n\nstatic void machvirt_init(MachineState *machine)\n')
        text = BUILD['replace'](text, '    create_msi_controller(vms);\n',
            '    p1_mmc_qemu_create(sysmem);\n    create_msi_controller(vms);\n')
        board.write_text(text)
        model_inputs = []
        for name in ('p1-mmc-model.c', 'p1-mmc-model.h'):
            target = board.parent / name
            if target.exists() or target.is_symlink():
                raise ValueError('Private model destination already exists')
            UPDATE['copy_input'](HERE / name, target)
            model_inputs.append(ABI['record'](HERE / name))
        production = (template / 'build/flash.ninja').read_text()
        target = 'libsystem_arm.a.p/hw_arm_virt.c.o'
        header = production[:production.index('\nbuild ')]
        compile_rule = BUILD['block'](production, target).replace(' ARGS = ', ' ARGS = -Werror ')
        frozen = header + '\n' + compile_rule + '\n' + BUILD['block'](production, 'qemu-system-aarch64')
        frozen = frozen.replace(str(template), str(output))
        frozen_path = output / 'build/p1-mmc.ninja'; frozen_path.write_text(frozen)
        (output / 'build' / target).unlink()
        (output / 'build/qemu-system-aarch64').unlink()
        command = ['bwrap', '--unshare-all', '--die-with-parent', '--ro-bind', '/', '/',
                   '--dev-bind', '/dev', '/dev', '--proc', '/proc', '--tmpfs', '/tmp',
                   '--bind', str(output), str(output), '--chdir', str(output / 'build'),
                   'ninja', '-f', frozen_path.name, '-j2', 'qemu-system-aarch64']
        result['compile_command'] = command
        with (output / 'compile.log').open('xb') as log:
            compiled = subprocess.run(command, stdout=log, stderr=subprocess.STDOUT)
        result['compile_returncode'] = compiled.returncode
        if compiled.returncode:
            raise RuntimeError('MMC private QEMU compile failed; original log retained')
        after = BUILD['tree_files'](output / 'qemu-11.1.2')
        expected = dict(before['qemu-11.1.2'])
        expected['hw/arm/virt.c'] = sha(board.read_bytes())
        expected.update({'hw/arm/' + r['path'].split('/')[-1]: r['sha256'] for r in model_inputs})
        if after != expected:
            raise ValueError('Private source modification escaped bounded model delta')
        binary = ABI['record'](output / 'build/qemu-system-aarch64')
        result.update(status='compiled', qemu=binary, model_inputs=model_inputs,
                      board=ABI['record'](board), frozen_ninja=ABI['record'](frozen_path),
                      source_tree_sha256=BUILD['tree_digest'](after),
                      original_tree_sha256={n: BUILD['tree_digest'](v) for n, v in before.items()})
    except BaseException as error:
        result.update(status='failed', error=type(error).__name__ + ': ' + str(error))
        raise
    finally:
        result['production_unchanged'] = all(BUILD['tree_files'](template / n) == v for n, v in before.items())
        if not result['production_unchanged']:
            result.update(status='failed', error='Original production source/build changed')
        save(output / 'build-receipt.json', result)
    if result['status'] != 'compiled':
        raise RuntimeError(result['error'])
    return result


def iomaps(dtb, libpath):
    """Read actual DTB fields, preserving GIC's physical alias independently."""
    lib = ctypes.CDLL(str(libpath)); lib.fdt_getprop.restype = ctypes.c_void_p
    lib.fdt_get_name.restype = ctypes.c_char_p
    raw = Path(dtb).read_bytes()
    if len(raw) < 40 or len(raw) > 1024**2 or int.from_bytes(raw[4:8], 'big') != len(raw):
        raise ValueError('Invalid DTB length')
    data = ctypes.create_string_buffer(raw)
    if lib.fdt_check_full(data, len(raw)):
        raise ValueError('Invalid DTB structure')
    def get(offset, name):
        size = ctypes.c_int()
        pointer = lib.fdt_getprop(data, offset, name.encode(), ctypes.byref(size))
        if not pointer or size.value != 8:
            raise ValueError('Missing/malformed iomap property: ' + name)
        return int.from_bytes(ctypes.string_at(pointer, size.value), 'big')
    rows, offset, depth = {}, -1, ctypes.c_int(-1)
    while True:
        offset = lib.fdt_next_node(data, offset, ctypes.byref(depth))
        if offset == -1 or (offset >= 0 and depth.value < 0):
            break
        if offset < 0:
            raise ValueError('Malformed DTB node traversal')
        size = ctypes.c_int()
        pointer = lib.fdt_getprop(data, offset, b'device_type', ctypes.byref(size))
        if pointer and ctypes.string_at(pointer, size.value) == b'iomap\0':
            name = lib.fdt_get_name(data, offset, None).decode('ascii')
            if name in rows:
                raise ValueError('Duplicate iomap name')
            rows[name] = {key: get(offset, key) for key in ('phys', 'virt', 'size')}
            if rows[name]['size'] <= 0 or any(rows[name][key] + rows[name]['size'] > 2**64 for key in ('phys', 'virt')):
                raise ValueError('Invalid/overflowing iomap extent')
    for name in ('sony-gic-alias', 'sony-scu-map', 'sony-mmc-identification-map'):
        if name not in rows:
            raise ValueError('Missing required iomap: ' + name)
    names = tuple(rows)
    if rows['sony-gic-alias'] != dict(phys=0x08000000, virt=0xfffffffff13a1000, size=0x1000):
        raise ValueError('Original GIC physical alias changed')
    if rows['sony-scu-map'] != dict(phys=0xf1388000, virt=0xfffffffff1388000, size=0x2000):
        raise ValueError('Original SCU map changed')
    if rows['sony-mmc-identification-map'] != dict(phys=0xf13b8000, virt=0xfffffffff13b8000, size=0x1000):
        raise ValueError('Identification map exceeds source-bound page')
    for i, name in enumerate(names):
        for other in names[i + 1:]:
            a, b = rows[name], rows[other]
            for key in ('phys', 'virt'):
                if max(a[key], b[key]) < min(a[key] + a['size'], b[key] + b['size']):
                    raise ValueError('Overlapping iomaps: ' + name + '/' + other)
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='action', required=True)
    p = commands.add_parser('source')
    for name in ('root', 'gpl', 'kernel', 'prior_receipt', 'output'):
        p.add_argument(name, type=Path)
    p = commands.add_parser('build')
    for name in ('source_receipt', 'template', 'output'):
        p.add_argument(name, type=Path)
    args = vars(parser.parse_args()); action = args.pop('action')
    result = globals()[action](**args)
    print(json.dumps({k:result[k] for k in ('schema', 'status', 'profile', 'original_module_load_allowed')}, indent=2))


if __name__ == '__main__':
    main()
