#!/usr/bin/env bash
# Explicit, offline CP build. Never installs or replaces the product window QEMU.
set -euo pipefail
umask 077
here="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
if [[ "${1:-}" == --help || "${1:-}" == -h ]]; then
  echo 'Usage: build-cp-native.sh ARCHIVE NEW_OUTPUT'
  echo 'ARCHIVE: pinned official qemu-11.1.2.tar.xz; no downloads or installation.'
  echo 'NEW_OUTPUT: unused child of this product source/build directory, outside /tmp.'
  echo 'Needs 80 GiB free (4 GiB sources + 12 GiB build + 64 GiB reserve).'
  echo 'Builds NEW_OUTPUT/tree/build-cp/qemu-system-aarch64 with ninja -j2.'
  echo 'No tests or QEMU execution. Existing default window binary stays unchanged.'
  exit 0
fi
[[ $# == 2 && "$1" != --* && "$2" != --* ]] || {
  echo 'Usage: build-cp-native.sh ARCHIVE NEW_OUTPUT' >&2
  exit 2
}
exec python3 -B - "$here" "$1" "$2" <<'PY'
import json
import os
from pathlib import Path
import runpy
import shutil
import subprocess
import sys
import tarfile

product = Path(sys.argv[1]).resolve(strict=True)
cp = product / 'source/cp-boot'
port = runpy.run_path(str(cp / 'stage-platform.py'))
check, file_sha, new_file = port['check'], port['file_sha'], port['new_file']
encoded = port['encoded']
admission = port['preflight_build'](sys.argv[2], sys.argv[3])
archive, output = Path(admission['archive']), Path(admission['output'])
origin, origin_sha, _, _ = port['recipe']()
if not hasattr(tarfile, 'data_filter'):
    raise SystemExit('Python tarfile.data_filter is required')
for name in ('bwrap', 'patch', 'ninja', 'cc', 'pkg-config', 'make', 'flex', 'bison'):
    if shutil.which(name) is None:
        raise SystemExit('Missing offline build dependency: ' + name)
subprocess.run(['pkg-config', '--exists', 'gtk+-3.0', 'sdl2', 'pixman-1',
                'glib-2.0', 'libseccomp'], check=True)

child = runpy.run_path(str(cp / 'stage-peripherals.py'))
if (not callable(child.get('validate_receipt')) or
        origin['downstream']['notify_fresh_stage_sha256'] not in child.get('PARENT_SHAS',())):
    raise SystemExit('Child stage lacks the accepted parent/inventory validator')
native = json.loads(check(product, origin['upstream']['native_manifest']['path'],
                          origin['upstream']['native_manifest']['sha256']))
dtc = product / 'source/dtc'
entries = list(dtc.rglob('*'))
if any(path.is_symlink() for path in entries):
    raise SystemExit('DTC source inventory contains a symlink')
if {path.relative_to(dtc).as_posix() for path in entries if path.is_file()} != set(native['dtc_source_files']):
    raise SystemExit('DTC source inventory differs')

# Freeze all product source inputs, including the independently maintained child.
inputs = {'build-cp-native.sh', 'source/manifest.json', 'source/qemu-sony-native.patch',
          'source/cp-boot/stage-platform.py', 'source/cp-boot/platform/source-origins.json',
          'source/cp-boot/platform/cp-platform.patch', 'source/cp-boot/stage-peripherals.py',
          'source/cp-boot/check-notify-qemu.py'}
inputs.update('source/cp-boot/' + name for name in origin['downstream']['recipe_files'])
inputs.update('source/cp-boot/platform/' + row['source'] for row in origin['sources'].values()
              if row['operation'] == 'copy')
inputs.update('source/cp-boot/' + name for name in child['FILES'])
inputs.update(child['RUNTIME_SOURCES'])
inputs.update('source/dtc/' + name for name in native['dtc_source_files'])
snapshot = {name: file_sha(product / name) for name in sorted(inputs)}
for name, digest in native['dtc_source_files'].items():
    if snapshot['source/dtc/' + name] != digest:
        raise SystemExit('DTC source SHA256 differs: ' + name)


def verify_inputs():
    for name, digest in snapshot.items():
        check(product, name, digest)


def verify_tree(table):
    for name, digest in table.items():
        check(tree, name, digest)


def command(argv, log, data=None):
    verify_inputs()
    with (output / log).open('xb') as stream:
        subprocess.run([str(part) for part in argv], input=data, stdout=stream,
                       stderr=subprocess.STDOUT, check=True)
    verify_inputs()


def storage_update(status, error=None):
    record = dict(schema='a7c2-cp-native-build-storage-v1', owner='explicit-offline-cp-native-build',
                  directory=str(output), status=status, budget=admission['storage'],
                  workers=2, default_binary_replaced=False, error=error,
                  next_consumer='Main-session unified regression or an explicit isolated AP/CP run',
                  reclaim_condition='After a replacement is accepted and this tree is not referenced by a live owner, build receipt or failure investigation',
                  retained_reason='Source restoration bytes, stage identities, build outputs and failure logs')
    record['allocated_bytes'] = sum(path.lstat().st_blocks * 512 for path in output.rglob('*')
                                    if not path.is_symlink())
    space = os.statvfs(output)
    record['available_bytes'] = space.f_bavail * space.f_frsize
    temporary = output / 'storage.json.new'
    new_file(temporary, encoded(record))
    os.replace(temporary, output / 'storage.json')


# Recheck the exclusive destination after dependency/source admission.
verify_inputs()
port['preflight_build'](archive, output)
output.parent.mkdir(parents=True, exist_ok=True)
output.mkdir(mode=0o700)
(output / 'tmp').mkdir()
(output / 'cache').mkdir()
os.environ['TMPDIR'] = str(output / 'tmp')
os.environ['PYTHONDONTWRITEBYTECODE'] = '1'
tree = output / 'tree'
try:
    storage_update('extracting')
    new_file(output / 'source-inputs.json', encoded(snapshot))

    def qemu_filter(member, destination):
        # Same sole EDK2 exception as build-qemu.sh; no host absolute links.
        if (member.name == 'qemu-11.1.2/roms/edk2/EmulatorPkg/Unix/Host/X11IncludeHack'
                and member.issym() and member.linkname == '/opt/X11/include'):
            return None
        if member.name != 'qemu-11.1.2' and not member.name.startswith('qemu-11.1.2/'):
            raise ValueError('Unexpected QEMU archive root')
        return tarfile.data_filter(member, destination)

    with tarfile.open(archive) as source:
        source.extractall(output, filter=qemu_filter)
    if file_sha(archive) != origin['upstream']['archive']['sha256']:
        raise ValueError('QEMU archive changed during extraction')
    extracted = output / 'qemu-11.1.2'
    if extracted.is_symlink() or not extracted.is_dir():
        raise ValueError('QEMU archive did not create the exact source directory')
    extracted.rename(tree)
    for name, row in native['source_files'].items():
        check(tree, name, row['before'])
    shutil.copytree(dtc, tree / 'subprojects/dtc', dirs_exist_ok=True)
    for name, digest in native['dtc_source_files'].items():
        check(tree / 'subprojects/dtc', name, digest)
    command(['patch', '--batch', '--forward', '--fuzz=0', '-p1', '-d', tree], 'native-patch.log',
            check(product, origin['upstream']['native_patch']['path'], origin['upstream']['native_patch']['sha256']))
    verify_tree({name: row['after'] for name, row in native['source_files'].items()})
    for name in ('stage-platform.py', 'stage.py', 'stage-notify.py'):
        command([sys.executable, '-B', cp / name, tree], name + '.log')
    check(tree, 'cp-gpio18-stage.json', origin['downstream']['gpio18_stage_sha256'])
    parent_raw = check(tree, 'cp-notify-stage.json', origin['downstream']['notify_fresh_stage_sha256'])
    parent = json.loads(parent_raw)
    command([sys.executable, '-B', cp / 'stage-peripherals.py', tree], 'stage-peripherals.py.log')
    shape = json.loads(port['read'](tree, 'cp-peripherals-stage.json'))
    inherited = {name: digest for name, digest in
                 {**parent['inherited_sources'], **parent['outputs'], **child['UPSTREAM']}.items()
                 if name not in child['BASES']}
    child['validate_receipt'](shape, inherited)
    platform_proof = json.loads(port['read'](tree, 'cp-platform-stage.json'))
    final_sources = {**platform_proof['inherited_sources'], **platform_proof['outputs'],
                     **parent['inherited_sources'], **parent['outputs'],
                     **shape['inherited_sources'], **shape['outputs']}
    verify_tree(final_sources)
    build = tree / 'build-cp'
    build.mkdir()
    configure = ['--target-list=aarch64-softmmu', '--without-default-features',
                 '--enable-tcg', '--enable-gtk', '--enable-sdl', '--enable-pixman',
                 '--enable-seccomp', '--enable-fdt=internal', '--enable-vvfat', '--enable-qcow1',
                 '--disable-docs', '--disable-tools', '--disable-guest-agent',
                 '--disable-werror', '--disable-plugins', '--disable-capstone',
                 '--disable-vhost-user', '--disable-slirp', '--disable-opengl',
                 '--disable-download', '--disable-containers']
    new_file(output / 'configure-arguments.json', encoded(configure))
    storage_update('building')
    # The sole writable bind is this new output; no network or physical devices.
    command(['bwrap', '--unshare-net', '--die-with-parent', '--clearenv',
             '--ro-bind', '/', '/', '--bind', output, output, '--dev', '/dev', '--proc', '/proc',
             '--chdir', build, '--setenv', 'PATH', '/usr/bin:/bin', '--setenv', 'LC_ALL', 'C',
             '--setenv', 'TMPDIR', output / 'tmp', '--setenv', 'XDG_CACHE_HOME', output / 'cache',
             '--setenv', 'PYTHONDONTWRITEBYTECODE', '1', '--setenv', 'GIT_CEILING_DIRECTORIES', output,
             '--setenv', 'PIP_NO_INDEX', '1', '--setenv', 'PIP_NO_CACHE_DIR', '1',
             '/bin/bash', '-c', 'set -e; "$1/configure" "${@:2}"; ninja -k0 -j2 qemu-system-aarch64',
             'cp-native-build', tree, *configure], 'configure-ninja.log')
    verify_tree(final_sources)
    child['validate_receipt'](shape, inherited)
    binary = build / 'qemu-system-aarch64'
    proof = dict(schema='a7c2-cp-notify-build-v1', profile=parent['profile'],
                 binary=str(binary), binary_sha256=file_sha(binary),
                 stage_sha256=file_sha(tree / 'cp-notify-stage.json'),
                 peripherals_stage_sha256=file_sha(tree / 'cp-peripherals-stage.json'),
                 platform_stage_sha256=file_sha(tree / 'cp-platform-stage.json'),
                 gpio18_stage_sha256=file_sha(tree / 'cp-gpio18-stage.json'),
                 source_origins_sha256=origin_sha, source_inputs=snapshot, source_files=final_sources,
                 configure=configure, workers=2, build_completed=True, default_off=True,
                 default_binary_replaced=False, tests_run=False, qemu_executed=False,
                 physical_compatible=False, full_boot_verified=False, capture_verified=False)
    new_file(build / 'cp-notify-build.json', encoded(proof))
    # This function only reads receipts/source/binary SHA; its qtest main is never called.
    checker = runpy.run_path(str(cp / 'check-notify-qemu.py'))
    if checker['contract'](binary, require_peripherals=True) != proof:
        raise ValueError('Native/child binary source contract differs')
    verify_inputs()
    storage_update('built-awaiting-unified-regression')
except BaseException as error:
    try:
        storage_update('failed-retained', repr(error))
    except Exception as storage_error:
        print('Storage receipt also failed: ' + repr(storage_error), file=sys.stderr)
    raise
print('CP_NATIVE_BINARY=' + str(binary))
print('CP_NATIVE_BUILD_RECEIPT=' + str(build / 'cp-notify-build.json'))
print('No tests or QEMU execution performed; unified regression remains pending.')
PY
