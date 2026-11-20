#!/usr/bin/env python3
"""Build the standalone kernel type carrier read by the model17c GDB owner.

The ABI manifest and its 406 dependency headers stay the single source of
truth, so the carrier is compiled with the same cross GCC flags and the same
kernel configuration as the guest module. Only the reduced-debug flag is
dropped: -femit-struct-debug-baseonly removes every structure the headers
define, which is exactly what this artifact has to carry. -DMODULE goes too:
these are core kernel structures. The remaining -DKBUILD_* strings are inert
for this file and stay verbatim so the recorded argv is auditable against the
manifest command.
"""
from pathlib import Path
import argparse, hashlib, json, os, shutil, subprocess
from elftools.elf.elffile import ELFFile

CARRIER = 'a7c2-kernel-types.elf'
STATIC = ('-femit-struct-debug-baseonly', '-DMODULE')
STRUCTS = {
    'task_struct': ('pid', 'tgid', 'mm', 'fs'),
    'mm_struct': ('mmap', 'pgd', 'env_start', 'env_end'),
    'vm_area_struct': ('vm_start', 'vm_end', 'vm_next', 'vm_mm', 'vm_file', 'vm_flags', 'vm_pgoff'),
    'file': ('f_path', 'f_inode'),
    'dentry': ('d_parent', 'd_name'),
    'inode': ('i_sb', 'i_ino'),
    'super_block': ('s_dev',),
    'fs_struct': ('root',),
    'path': ('mnt', 'dentry'),
    'qstr': ('name',),
}
# The GDB owner pins these two offsets as its H contract; a carrier that
# disagrees with the running kernel must not be published.
TASK_OFFSETS = {'pid': 0x388, 'tgid': 0x38c}


def need(ok, message):
    if not ok:
        raise ValueError(message)


def sha(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def inspect(carrier):
    """Return {struct: {field: offset}} for every fully defined structure."""
    with carrier.open('rb') as stream:
        elf = ELFFile(stream)
        need(elf['e_machine'] == 'EM_AARCH64' and elf['e_type'] == 'ET_REL',
             'Wrong carrier architecture/type')
        found = {}
        for unit in elf.get_dwarf_info().iter_CUs():
            for die in unit.iter_DIEs():
                if die.tag != 'DW_TAG_structure_type' or 'DW_AT_name' not in die.attributes:
                    continue
                members = {}
                for child in die.iter_children():
                    if child.tag != 'DW_TAG_member' or 'DW_AT_name' not in child.attributes:
                        continue
                    if 'DW_AT_data_member_location' in child.attributes:
                        members[child.attributes['DW_AT_name'].value.decode()] = \
                            child.attributes['DW_AT_data_member_location'].value
                if members:
                    found.setdefault(die.attributes['DW_AT_name'].value.decode(), members)
    for name, fields in STRUCTS.items():
        need(name in found, 'Carrier lacks struct ' + name)
        missing = [field for field in fields if field not in found[name]]
        need(not missing, 'Carrier lacks ' + name + ' fields ' + repr(missing))
    offsets = {field: found['task_struct'][field] for field in TASK_OFFSETS}
    need(offsets == TASK_OFFSETS, 'Kernel task ABI differs from H: ' + repr(offsets))
    return found, offsets


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    source = args.source.resolve(strict=True)
    out = args.output.absolute()
    need(not out.exists(), 'Fresh carrier output required')
    out.mkdir(parents=True, mode=0o700)
    manifest = json.loads((source / 'abi-manifest.json').read_bytes())
    need(manifest['kernel_release'] == '4.9.337-scel+', 'Unknown module ABI version')
    expected = {name for name in manifest['files'] if name.startswith('abi/')}
    actual = {str(path.relative_to(source)) for path in (source / 'abi').rglob('*')
              if path.is_file() or path.is_symlink()}
    need(actual == expected, 'Persistent kernel ABI header inventory differs')
    for name, row in manifest['files'].items():
        path = source / name
        need(not path.is_symlink() and path.resolve().is_relative_to(source) and
             path.stat().st_size == row['bytes'] and sha(path) == row['sha256'],
             'Module ABI/source identity changed: ' + name)
    cc = shutil.which('aarch64-linux-gnu-gcc')
    need(cc, 'AArch64 GCC required')
    builtin = subprocess.run([cc, '-print-file-name=include'], capture_output=True, text=True,
                             check=True).stdout.strip()
    need(Path(builtin).is_dir(), 'Cross compiler builtin headers missing')
    words = manifest['commands'][0]
    argv = []
    for word in words[:words.index('-c')] + ['-c', '-o', CARRIER, 'kernel-types.c']:
        if word in STATIC:
            continue
        if word == 'aarch64-linux-gnu-gcc':
            argv.extend([cc, '-isystem', builtin])
        elif word.startswith('-Iabi/'):
            argv.append('-I' + str(source / word[2:]))
        elif word.startswith('abi/') or word == 'kernel-types.c':
            argv.append(str(source / word))
        else:
            argv.append(word)
    result = subprocess.run(argv, cwd=out, capture_output=True, timeout=300)
    (out / 'command-0.stdout').write_bytes(result.stdout)
    (out / 'command-0.stderr').write_bytes(result.stderr)
    need(result.returncode == 0, 'Carrier compile failed: ' +
         result.stderr.decode(errors='replace')[-2000:])
    carrier = out / CARRIER
    found, offsets = inspect(carrier)
    value = dict(schema='a7c2-kernel-type-carrier-build-v1', kernel_release='4.9.337-scel+',
                 types=dict(bytes=carrier.stat().st_size, sha256=sha(carrier)),
                 source_manifest_sha256=sha(source / 'abi-manifest.json'),
                 all_header_source_hashes_verified=True,
                 structs={name: dict(sorted(found[name].items())) for name in sorted(STRUCTS)},
                 task_offsets=offsets, struct_debug_baseonly=False,
                 reduced_debug_flag_dropped='-femit-struct-debug-baseonly',
                 original_kernel_component_unmodified=True,
                 original_guest_load_not_applicable=True, commands=[dict(argv=argv, returncode=0)])
    with (out / 'result.json').open('x') as stream:
        stream.write(json.dumps(value, indent=2) + '\n')
        stream.flush()
        os.fsync(stream.fileno())
    print('KERNEL_TYPE_CARRIER_BUILD_PASS', out, value['types']['sha256'], flush=True)


if __name__ == '__main__':
    main()
