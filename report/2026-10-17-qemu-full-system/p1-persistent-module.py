#!/usr/bin/env python3
"""Build the persistent block adapter for the exact original p1 Linux 4.9.186.

build(kernel_source, output, *, original_p1_kernel, original_module_directory)
returns a receipt, including failed compiler commands. output must not exist.
The module directory is the extracted original root, with kmod/ and usr/kmod/.
Only the private kernel-source/kernel-build/module directories are built.
No host insmod, QEMU launch, updater execution or physical device access occurs.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import struct
import subprocess

HERE = Path(__file__).resolve().parent
PROJECT = HERE.parents[1]
RELEASE = '4.9.186-scel'
VERMAGIC = RELEASE + ' SMP preempt mod_unload aarch64'
KERNEL_SHA = '9812ab13f73e6a98d0113f9500853739edcd5bb06e2952c42295b9dae06c758e'
CONFIG_SHA = 'dc9f316be46eded739c16aaffb3ab481f29c653abcc640fdb3d2e87f2ccf6a29'
TREE_SHA = '7d7e4cec0bed250e153ed0806a7d857dc6918a7b8a00a35282bd0d8a678436af'
MODULES_SHA = '1af381c5856713d4889c4b954a9f96ab0cd227fdbc6d8604009a9d30c1440b74'
SOURCE_PINS = {
    'Makefile': '80637ee707bb7d9b82aad011ac21e5878b04ccf3ad202f59e8e457f67938c875',
    '.config': CONFIG_SHA,
    'include/linux/module.h': 'aa9ff4522e1fcb67e981f32af8639a80dc7e49d7b3d12f06567ce8a6505f0103',
    'include/linux/blkdev.h': 'b26e1adfe40f1e155af1199213dbdf856866252d2cad23c6b4581beef3f4b7ef',
    'include/linux/blk_types.h': '566fcce4f729971736a2b1ab12a3d2f5e555583964674bb4d442cdfb7f92d4dd',
    'include/linux/bio.h': '982fd2b13c2a6aca8e9ee96b3111222435f669309cb7aef248455aea9d3e49a1',
}
# Large-I/O code-only fix replaces 850ec0d7...; MMIO protocol and module ABI unchanged.
DRIVER_PINS = {
    'sony_persistent_flash.c': '15b6a84827a0d6e2925ea4fd6f9d17b6b820aedf0e6b790706b90ab4300b2b9f',
    'Makefile': 'fff13b32354b61e8f2434d87ec25868fb2e2d16fb03683730efb5732b73b3b39',
}
ARCHIVE = dict(sha256='10ab84b343a4c195701cfc47f508fd9a12bbcf0ed2bd3b80d72cce4ebee1c405',
               bytes=109661212, md5_base64='FCo90WzArqhiW8J16RZkZQ==',
               source='Sony 20230901_ILCE-7CM2 linux-kernel.tar.gz')
ENV = dict(PATH='/usr/bin:/bin', LC_ALL='C', KBUILD_BUILD_USER='p1-module',
           KBUILD_BUILD_HOST='isolated', KBUILD_BUILD_TIMESTAMP='2026-11-06 00:00:00 UTC',
           SOURCE_DATE_EPOCH='1793923200')


def json_sha(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def checked_path(path, *, directory=False, missing=False):
    raw = os.fspath(path)
    if any(p in ('.', '..') for p in raw.split('/')):
        raise ValueError('Dot components/source outside declared directory')
    path = Path(os.path.abspath(raw))
    for p in (*reversed(path.parents), path):
        if p.is_symlink():
            raise ValueError('Symlink host path refused: ' + str(p))
    if missing:
        if path.exists():
            raise ValueError('Fresh output required: ' + str(path))
        checked_path(path.parent, directory=True)
    elif directory:
        if not path.is_dir():
            raise ValueError('Directory required: ' + str(path))
    elif not path.is_file():
        raise ValueError('Regular file required: ' + str(path))
    return path


def record(path):
    path = checked_path(path)
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        before = os.fstat(fd)
        if not stat.S_ISREG(before.st_mode):
            raise ValueError('Regular file required')
        digest = hashlib.sha256()
        while block := os.read(fd, 1024 * 1024):
            digest.update(block)
        after = os.fstat(fd)
        if (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns) != (
                after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns):
            raise ValueError('Input changed while hashing: ' + str(path))
        return dict(path=str(path), bytes=before.st_size, sha256=digest.hexdigest())
    finally:
        os.close(fd)


def tree_inventory(source):
    rows = []
    for path in sorted(source.rglob('*')):
        if path.is_symlink():
            raise ValueError('Symlink/source outside declared tree: ' + str(path))
        if path.is_dir():
            continue
        row = record(path)
        rows.append(dict(path=str(path.relative_to(source)), sha256=row['sha256']))
    return rows


def verify_source(source):
    checked_path(source / 'Makefile')
    text = (source / 'Makefile').read_text()
    for key, expected in (('VERSION', '4'), ('PATCHLEVEL', '9'), ('SUBLEVEL', '186'), ('EXTRAVERSION', '')):
        match = re.search(r'^' + key + r'\s*=([^\n]*)$', text, re.M)
        if not match or match[1].strip() != expected:
            raise ValueError('Wrong source kernel version: ' + key)
    for name, expected in SOURCE_PINS.items():
        if record(source / name)['sha256'] != expected:
            raise ValueError('Wrong pinned source/config: ' + name)
    rows = tree_inventory(source)
    if json_sha(rows) != TREE_SHA:
        raise ValueError('Wrong official source tree content')
    return rows


def elf_sections(raw):
    if len(raw) < 64 or raw[:7] != b'\x7fELF\x02\x01\x01' or struct.unpack_from('<HH', raw, 16) != (1, 183):
        raise ValueError('Expected ELF64 little-endian AArch64 relocatable module')
    offset = struct.unpack_from('<Q', raw, 40)[0]
    width, count, names_index = struct.unpack_from('<HHH', raw, 58)
    if width != 64 or not 0 < names_index < count or offset + count * width > len(raw):
        raise ValueError('Invalid ELF section table')
    headers = [struct.unpack_from('<IIQQQQIIQQ', raw, offset + i * width) for i in range(count)]
    def data(h):
        if h[1] == 8:
            return b''
        if h[4] + h[5] > len(raw):
            raise ValueError('ELF section outside file')
        return raw[h[4]:h[4] + h[5]]
    names = data(headers[names_index])
    result = {}
    for header in headers[1:]:
        begin = header[0]
        end = names.find(b'\0', begin)
        if end < begin:
            raise ValueError('Invalid ELF section name')
        name = names[begin:end].decode('ascii')
        if name in result:
            raise ValueError('Duplicate ELF section')
        result[name] = dict(size=header[5], alignment=header[8], data=data(header))
    return result


def module_info(path):
    sections = elf_sections(checked_path(path).read_bytes())
    fields = {}
    for entry in sections.get('.modinfo', {}).get('data', b'').split(b'\0'):
        if b'=' in entry:
            key, value = entry.decode('ascii').split('=', 1)
            fields.setdefault(key, []).append(value)
    layout = sections.get('.gnu.linkonce.this_module', {})
    return dict(file=record(path), vermagic=fields.get('vermagic', []),
                license=fields.get('license', []), modinfo=fields,
                struct_module_bytes=layout.get('size'), struct_module_alignment=layout.get('alignment'),
                versions_present='__versions' in sections)


def require_abi(info):
    if (info['vermagic'] != [VERMAGIC] or info['struct_module_bytes'] != 768
            or info['struct_module_alignment'] != 64 or info['versions_present']):
        raise ValueError('Unknown/incompatible original p1 module ABI: ' + json.dumps(info))


def original_modules(directory):
    # Explicit original-root locations exclude later simulation/ adapters.
    paths = sorted([*(directory / 'kmod').glob('*.ko'), *(directory / 'usr/kmod').glob('*.ko')])
    rows = [dict(name=str(p.relative_to(directory)), sha256=record(p)['sha256']) for p in paths]
    if len(rows) != 90 or json_sha(rows) != MODULES_SHA:
        raise ValueError('Unknown original p1 module inventory (requires exact 90 originals)')
    infos = [module_info(p) for p in paths]
    for info in infos:
        require_abi(info)
    return dict(count=len(infos), inventory_sha256=json_sha(rows), modules=infos,
                actual_kernel_config=None, config_equivalence_verified=False)


def original_exports(raw, required):
    """Exact-image table pins, validated as real 16-byte kernel_symbol records.

    include/linux/export.h defines {unsigned long value; const char *name;}.
    vmlinux.lds.h sorts normal then GPL tables. Fixed offsets belong only to
    KERNEL_SHA; no guessed C struct offsets or strings-only export claims.
    """
    if hashlib.sha256(raw).hexdigest() != KERNEL_SHA:
        raise ValueError('Unknown original p1 kernel for export-table binding')
    base, start, gpl, stop = 0xffffff8008080000, 0x573f78, 0x581d18, 0x58b3b8
    if raw[56:60] != b'ARM\x64' or struct.unpack_from('<Q', raw, 8)[0] != 0x80000:
        raise ValueError('Wrong original arm64 Image header')
    entries = {}
    tables = []
    for begin, end, kind in ((start, gpl, 'normal'), (gpl, stop, 'GPL-only')):
        previous = ''
        for offset in range(begin, end, 16):
            value, pointer = struct.unpack_from('<QQ', raw, offset)
            string_offset = pointer - base
            if not stop <= string_offset < len(raw):
                raise ValueError('Export name pointer outside original string table')
            nul = raw.find(b'\0', string_offset, min(len(raw), string_offset + 128))
            name = raw[string_offset:nul].decode('ascii') if nul >= 0 else ''
            if (not re.fullmatch(r'[A-Za-z_][A-Za-z_0-9]*', name) or name <= previous
                    or name in entries or not base <= value < base + 0x6a6000):
                raise ValueError('Original export table value/order/uniqueness invalid')
            entries[name] = dict(name=name, kind=kind, entry_offset=offset, value=hex(value),
                                 name_pointer=hex(pointer), name_offset=string_offset,
                                 entry_hex=raw[offset:offset + 16].hex())
            previous = name
        tables.append(dict(start=begin, stop=end, count=(end - begin) // 16, kind=kind))
    missing = sorted(set(required) - entries.keys())
    return dict(status='verified' if not missing else 'missing-exports',
                method='original Image kernel_symbol pointer pairs and two sorted linker tables',
                image_virtual_base=hex(base), entry_bytes=16, tables=tables,
                total_exports=len(entries), required_count=len(required), missing=missing,
                required=[entries[n] for n in required if n in entries],
                function_signature_binding='unknown', actual_kernel_config=None,
                full_abi_binding_verified=False)


def command(argv, output, receipt, name, *, cwd=None):
    argv = [str(a) for a in argv]
    row = dict(name=name, argv=argv, cwd=str(cwd) if cwd else None, rc=None, timed_out=False)
    receipt['commands'].append(row)
    with (output / (name + '.stdout')).open('xb') as stdout, (output / (name + '.stderr')).open('xb') as stderr:
        try:
            row['rc'] = subprocess.run(argv, cwd=cwd, env=ENV, stdout=stdout, stderr=stderr,
                                       timeout=180).returncode
        except subprocess.TimeoutExpired:
            row['timed_out'] = True
    for stream in ('stdout', 'stderr'):
        row[stream] = record(output / (name + '.' + stream))
    if row['rc'] != 0:
        raise RuntimeError(name + ' failed: rc=' + str(row['rc']) + ', timed_out=' + str(row['timed_out']))
    return (output / (name + '.stdout')).read_text()


def config_values(path):
    values = {}
    for line in path.read_text().splitlines():
        if line.startswith('CONFIG_') and '=' in line:
            key, value = line.split('=', 1)
            values[key] = value
        elif line.startswith('# CONFIG_') and line.endswith(' is not set'):
            values[line[2:-11]] = 'n'
    return values


def build(kernel_source, output, *, original_p1_kernel, original_module_directory):
    source = checked_path(kernel_source, directory=True)
    kernel = checked_path(original_p1_kernel)
    originals = checked_path(original_module_directory, directory=True)
    output = checked_path(output, missing=True)
    for protected in (source, kernel, originals, PROJECT / 'final', PROJECT / 'analysis/output/system-dump'):
        if output.is_relative_to(protected) or protected.is_relative_to(output):
            raise ValueError('Output overlaps original source/kernel/modules/delivery/dump')
    output.mkdir(mode=0o700)
    receipt = dict(schema='a7c2-original-p1-persistent-module-v1', status='building', output=str(output),
                   commands=[], official_archive=ARCHIVE, source_patches=[], config_derivation=[],
                   environment=ENV, original_kernel_config=None, guest_abi_verified=False,
                   installation_verified=False, p1_installer_verified=False, capture_verified=False,
                   physical_devices_used=False, host_module_loaded=False, force_load_allowed=False)
    before = None
    try:
        receipt['builder'] = record(HERE / 'p1-persistent-module.py')
        receipt['original_kernel'] = record(kernel)
        if receipt['original_kernel']['sha256'] != KERNEL_SHA:
            raise ValueError('Wrong original p1 kernel identity')
        if b'Linux version ' + RELEASE.encode() + b' ' not in kernel.read_bytes():
            raise ValueError('Wrong original p1 kernel release')
        before = verify_source(source)
        (output / 'source-inventory.json').write_text(json.dumps(before, indent=2) + '\n')
        receipt['source'] = dict(path=str(source), tree_sha256=json_sha(before), file_count=len(before),
                                 pins={name: record(source / name) for name in SOURCE_PINS})
        receipt['original_modules'] = original_modules(originals)
        receipt['driver'] = {}
        for name, expected in DRIVER_PINS.items():
            row = record(HERE / 'persistent-flash' / name)
            if row['sha256'] != expected:
                raise ValueError('Persistent driver source changed: ' + name)
            receipt['driver'][name] = row
        receipt['tools'] = {}
        for name in ('make', 'cp', 'gcc-15', 'ld', 'aarch64-linux-gnu-gcc', 'aarch64-linux-gnu-as',
                     'aarch64-linux-gnu-ld', 'aarch64-linux-gnu-readelf', 'aarch64-linux-gnu-objcopy'):
            path = Path(shutil.which(name, path=ENV['PATH'])).resolve(strict=True)
            receipt['tools'][name] = dict(**record(path), version=command([path, '--version'], output, receipt, 'tool-' + name).splitlines()[0])
        for compiler in ('gcc-15', 'aarch64-linux-gnu-gcc'):
            cc1 = command([compiler, '-print-prog-name=cc1'], output, receipt, 'cc1-' + compiler).strip()
            receipt['tools'][compiler + '/cc1'] = record(Path(cc1).resolve(strict=True))
        private = output / 'kernel-source'
        out = output / 'kernel-build'
        module = output / 'module'
        command(['cp', '-a', '--reflink=auto', source, private], output, receipt, 'copy-source')
        copied = tree_inventory(private)
        if copied != before:
            raise ValueError('Private source copy differs')
        out.mkdir(); module.mkdir()
        shutil.copyfile(private / '.config', out / '.config')
        (private / '.config').unlink()
        # GCC >=10 defaults to -fno-common; dtc's parser owns yylloc.
        for name in ('scripts/dtc/dtc-lexer.l', 'scripts/dtc/dtc-lexer.lex.c_shipped'):
            path = private / name
            original = record(path)
            text = path.read_text()
            if text.count('\nYYLTYPE yylloc;\n') != 1:
                raise ValueError('Unexpected official dtc lexer compatibility anchor')
            path.write_text(text.replace('\nYYLTYPE yylloc;\n', '\nextern YYLTYPE yylloc;\n'))
            receipt['source_patches'].append(dict(path=name, before_sha256=original['sha256'],
                after_sha256=record(path)['sha256'], old='YYLTYPE yylloc;', new='extern YYLTYPE yylloc;',
                reason='Host GCC -fno-common; preserve single parser definition, no target ABI change'))
        for name in DRIVER_PINS:
            shutil.copyfile(HERE / 'persistent-flash' / name, module / name)
        receipt['config_derivation'].append(dict(step='copy official .config to private O= build',
                                                sha256=record(out / '.config')['sha256']))
        args = ['make', '-j2', '-C', private, 'O=' + str(out), 'ARCH=arm64',
                'CROSS_COMPILE=/usr/bin/aarch64-linux-gnu-', 'HOSTCC=/usr/bin/gcc-15',
                'LOCALVERSION=', 'KCFLAGS=-fno-pie']
        command(args + ['olddefconfig', 'modules_prepare'], output, receipt, 'prepare')
        old, new = config_values(source / '.config'), config_values(out / '.config')
        changes = {key: dict(before=old.get(key), after=new.get(key)) for key in old.keys() | new.keys()
                   if old.get(key) != new.get(key)}
        receipt['config_derivation'].append(dict(step='Kbuild olddefconfig/modules_prepare',
            output=record(out / '.config'), changes=changes, release_argument='LOCALVERSION=',
            release_mode='native Sony Makefile EXTRAVERSION appends -scel; suppress only SCM +'))
        if changes:
            raise ValueError('Unexpected reference config derivation: ' + json.dumps(changes))
        generated = (out / 'include/config/kernel.release').read_text().strip()
        receipt['generated_release'] = dict(value=generated, file=record(out / 'include/config/kernel.release'),
                                           utsrelease=record(out / 'include/generated/utsrelease.h'))
        if generated != RELEASE:
            raise ValueError('Kbuild did not generate exact original p1 release')
        command(args + ['M=' + str(module), 'modules'], output, receipt, 'module-build')
        ko = module / 'sony_persistent_flash.ko'
        info = module_info(ko)
        require_abi(info)
        if info['license'] != ['GPL']:
            raise ValueError('Expected GPL persistent adapter license')
        receipt['module'] = info
        command(['aarch64-linux-gnu-readelf', '-hSW', ko], output, receipt, 'module-layout')
        command(['aarch64-linux-gnu-readelf', '-p', '.modinfo', ko], output, receipt, 'module-modinfo')
        symbols = command(['aarch64-linux-gnu-readelf', '-sW', ko], output, receipt, 'module-symbols')
        required = sorted(set(re.findall(r'^\s*\d+:\s+\S+\s+\d+\s+\S+\s+GLOBAL\s+DEFAULT\s+UND\s+(\S+)\s*$', symbols, re.M)))
        if not required:
            raise ValueError('Missing module undefined symbol evidence')
        receipt['undefined_symbols'] = required
        receipt['exports'] = original_exports(kernel.read_bytes(), required)
        if receipt['exports']['missing']:
            raise ValueError('Original p1 does not export required symbols')
        receipt['private_makefile'] = record(private / 'Makefile')
        receipt['driver_copies'] = {name: record(module / name) for name in DRIVER_PINS}
        if any(row['sha256'] != DRIVER_PINS[name] for name, row in receipt['driver_copies'].items()):
            raise ValueError('Reused module source changed during build')
        receipt['status'] = 'compiled'
        receipt['next_step'] = 'Isolated original-p1 read-only ABI probe; then parent update-boot integration'
    except Exception as exc:
        receipt.update(status='failed', error=str(exc), error_type=type(exc).__name__)
    finally:
        if before is not None:
            try:
                after = tree_inventory(source)
                receipt['original_source_unchanged'] = before == after
                receipt['source_after_tree_sha256'] = json_sha(after)
                if before != after:
                    receipt.update(status='failed', error='Original source changed during build')
            except Exception as exc:
                receipt.update(status='failed', original_source_unchanged=False, error=str(exc))
        (output / 'p1-persistent-module.json').write_text(json.dumps(receipt, indent=2) + '\n')
    return receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--kernel-source', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--original-p1-kernel', required=True, type=Path)
    parser.add_argument('--original-module-directory', required=True, type=Path)
    args = parser.parse_args()
    receipt = build(args.kernel_source, args.output, original_p1_kernel=args.original_p1_kernel,
                    original_module_directory=args.original_module_directory)
    print(json.dumps({k: receipt.get(k) for k in ('status', 'error', 'output', 'generated_release')}, indent=2))
    return 0 if receipt['status'] == 'compiled' else 1


if __name__ == '__main__':
    raise SystemExit(main())
