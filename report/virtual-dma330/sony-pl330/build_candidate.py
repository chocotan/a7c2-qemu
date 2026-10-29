#!/usr/bin/env python3
"""Build a private opt-in PL330 candidate; never install over stable binaries."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import tarfile
import tempfile
from transaction_faults import transform

HERE = Path(__file__).resolve().parent
PRODUCT = HERE.parents[2]
SOURCE = PRODUCT/'source'


def sha(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def main():
    spec = importlib.util.spec_from_file_location('admission', HERE.parent/'admission.py')
    gate = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(gate)
    with gate.idle_lock(PRODUCT/'runtime/analysis/.menu-probe.lock'):
        archive = SOURCE/'vendor/qemu-11.1.2.tar.xz'
        manifest = json.loads((SOURCE/'manifest.json').read_text())
        usb = json.loads((SOURCE/'qemu-sony-usb.json').read_text())
        assert sha(archive) == manifest['base_sha256']
        assert sha(SOURCE/'qemu-sony-native.patch') == manifest['patch_sha256']
        assert usb['base_patch_sha256'] == manifest['patch_sha256']
        assert sha(SOURCE/'qemu-sony-usb.patch') == usb['patch_sha256']
        stage = Path(tempfile.mkdtemp(prefix='candidate-', dir=HERE))
        print('PL330_CANDIDATE_STAGE', stage, flush=True)

        def archive_filter(member, destination):
            if (member.name == 'qemu-11.1.2/roms/edk2/EmulatorPkg/Unix/Host/X11IncludeHack'
                    and member.issym() and member.linkname == '/opt/X11/include'):
                return None
            return tarfile.data_filter(member, destination)

        with tarfile.open(archive) as bundle:
            bundle.extractall(stage, filter=archive_filter)
        src = stage/'qemu-11.1.2'
        dtc = SOURCE/'dtc'
        for name, expected in manifest['dtc_source_files'].items():
            assert sha(dtc/name) == expected and not (dtc/name).is_symlink()
        shutil.copytree(dtc, src/'subprojects/dtc', dirs_exist_ok=True)
        for patch in ('qemu-sony-native.patch', 'qemu-sony-usb.patch'):
            subprocess.run(['patch', '--batch', '-p1', '-d', str(src), '-i', str(SOURCE/patch)], check=True)
        for name, record in usb['source_files'].items():
            assert sha(src/name) == record['after']
        for name, record in manifest['source_files'].items():
            assert sha(src/name) == (usb['source_files'].get(name, {}).get('after') or record['after'])
        virt = src/'hw/arm/virt.c'
        before = sha(virt)
        data = virt.read_text()
        anchor = '    create_gic(vms, sysmem);\n'
        assert data.count(anchor) == 1
        virt.write_text(data.replace(anchor, anchor+(HERE/'virt-dma330.inc').read_text()))
        pl330 = src/'hw/dma/pl330.c'
        pl330_before = sha(pl330)
        pl330.write_text(transform(pl330.read_text()))
        declared = json.loads((HERE.parent/'SOURCE-ORIGINS.json').read_text())
        assert sha(virt) == declared['source_files']['hw/arm/virt.c']['after']
        assert sha(pl330) == declared['source_files']['hw/dma/pl330.c']['after']
        proof = {'scope': 'opt-in stock PL330 experiment, not original-driver/camera completion',
                 'source_archive_sha256': sha(archive), 'native_patch_sha256': manifest['patch_sha256'],
                 'usb_patch_sha256': usb['patch_sha256'], 'virt_before': before,
                 'virt_after': sha(virt), 'fragment_sha256': sha(HERE/'virt-dma330.inc'),
                 'pl330_before': pl330_before, 'pl330_after': sha(pl330),
                 'transfer_verified': False, 'original_driver_verified': False, 'capture_verified': False}
        (stage/'source-proof.json').write_text(json.dumps(proof, indent=2)+'\n')
        for name in ('build', 'tmp', 'cache'):
            (stage/name).mkdir()
        command = ['bwrap', '--unshare-net', '--die-with-parent', '--clearenv',
                   '--ro-bind', '/', '/', '--bind', str(stage), str(stage),
                   '--dev', '/dev', '--proc', '/proc', '--chdir', str(stage/'build')]
        for key, value in {'PATH':'/usr/bin:/bin', 'LC_ALL':'C', 'TMPDIR':str(stage/'tmp'),
                           'XDG_CACHE_HOME':str(stage/'cache'), 'PIP_NO_INDEX':'1',
                           'PYTHONDONTWRITEBYTECODE':'1', 'GIT_CEILING_DIRECTORIES':str(stage)}.items():
            command += ['--setenv', key, value]
        command += ['/bin/bash', '-c',
                    'set -e; "$1/configure" --target-list=aarch64-softmmu '
                    '--without-default-features --enable-tcg --enable-pixman --enable-fdt=internal --enable-seccomp '
                    '--disable-opengl --disable-download --disable-docs --disable-containers '
                    '--disable-werror --disable-tools; ninja -j8 qemu-system-aarch64',
                    'build-pl330', str(src)]
        subprocess.run(command, check=True)
        binary = stage/'build/qemu-system-aarch64'
        proof['binary_sha256'] = sha(binary)
        (stage/'build-proof.json').write_text(json.dumps(proof, indent=2)+'\n')
        print('PL330_CANDIDATE_BINARY', binary, flush=True)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
