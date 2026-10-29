#!/usr/bin/env python3
"""Private PCI DMA diagnostic candidate over pinned native/USB/DMA and explicit ATU test peer."""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import tempfile

HERE = Path(__file__).resolve().parent
PRODUCT = HERE.parents[1]
DMA = HERE.parent/'virtual-dma330'
sys.path.insert(0, str(DMA))
from admission import idle_lock
from stage_hardware import stage as stage_pci_hardware


def sha(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def main():
    with idle_lock(PRODUCT/'runtime/analysis/.menu-probe.lock'):
        if shutil.disk_usage(HERE).free < 4*1024**3:
            raise RuntimeError('Less than 4GiB free for a separate private QEMU source/build')
        origin = json.loads((DMA/'SOURCE-ORIGINS.json').read_text())
        source = PRODUCT/'source'
        archive = source/'vendor/qemu-11.1.2.tar.xz'
        assert sha(archive) == origin['source_archive_sha256']
        manifest = json.loads((source/'manifest.json').read_text())
        for path, expected in ((source/'qemu-sony-native.patch', origin['native_patch_sha256']),
                               (source/'qemu-sony-usb.patch', origin['usb_patch_sha256']),
                               (DMA/'qemu-dma330.patch', origin['delta_patch_sha256'])):
            assert sha(path) == expected
        stage = Path(tempfile.mkdtemp(prefix='candidate-', dir=HERE))
        print('PCIDMA_CANDIDATE_STAGE', stage, flush=True)

        def filter_member(member, destination):
            if (member.name == 'qemu-11.1.2/roms/edk2/EmulatorPkg/Unix/Host/X11IncludeHack'
                    and member.issym() and member.linkname == '/opt/X11/include'):
                return None
            return tarfile.data_filter(member, destination)

        with tarfile.open(archive) as bundle:
            bundle.extractall(stage, filter=filter_member)
        src = stage/'qemu-11.1.2'
        for name, expected in manifest['dtc_source_files'].items():
            assert not (source/'dtc'/name).is_symlink() and sha(source/'dtc'/name) == expected
        shutil.copytree(source/'dtc', src/'subprojects/dtc', dirs_exist_ok=True)
        for patch in (source/'qemu-sony-native.patch', source/'qemu-sony-usb.patch', DMA/'qemu-dma330.patch'):
            subprocess.run(['patch', '--batch', '-p1', '-d', str(src), '-i', str(patch)], check=True)
        proof = {'scope':'default-off bounded PCI DMA hardware with explicit TEST peer; no CP/CMOS proof',
                 'source_archive_sha256':origin['source_archive_sha256'],
                 **stage_pci_hardware(src)}
        (stage/'source-proof.json').write_text(json.dumps(proof, indent=2)+'\n')
        for name in ('build', 'tmp', 'cache'):
            (stage/name).mkdir()
        command = ['bwrap', '--unshare-net', '--die-with-parent', '--clearenv', '--ro-bind', '/', '/',
                   '--bind', str(stage), str(stage), '--dev', '/dev', '--proc', '/proc',
                   '--chdir', str(stage/'build')]
        for key, value in {'PATH':'/usr/bin:/bin', 'LC_ALL':'C', 'TMPDIR':str(stage/'tmp'),
                           'PIP_NO_INDEX':'1', 'PYTHONDONTWRITEBYTECODE':'1',
                           'XDG_CACHE_HOME':str(stage/'cache')}.items():
            command += ['--setenv', key, value]
        command += ['/bin/bash', '-c',
                    'set -e; "$1/configure" --target-list=aarch64-softmmu '
                    '--without-default-features --enable-tcg --enable-pixman --enable-seccomp '
                    '--enable-fdt=internal --disable-opengl --disable-download --disable-docs '
                    '--disable-containers --disable-werror --disable-tools; ninja -j8 qemu-system-aarch64',
                    'build-pcidma', str(src)]
        subprocess.run(command, check=True)
        proof['binary_sha256'] = sha(stage/'build/qemu-system-aarch64')
        (stage/'build-proof.json').write_text(json.dumps(proof, indent=2)+'\n')
        print('PCIDMA_CANDIDATE_BINARY', stage/'build/qemu-system-aarch64', flush=True)


if __name__ == '__main__':
    main()
