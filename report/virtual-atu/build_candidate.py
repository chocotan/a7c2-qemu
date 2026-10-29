#!/usr/bin/env python3
"""Private ATU candidate over pinned native/USB/DMA sources; never install."""
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


def sha(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def main():
    with idle_lock(PRODUCT/'runtime/analysis/.menu-probe.lock'):
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
        print('ATU_CANDIDATE_STAGE', stage, flush=True)

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
        for name, record in origin['source_files'].items():
            assert sha(src/name) == record['after']
        model_files = ('sony_atu.c', 'atu_core.c', 'atu_core.h')
        for name in model_files:
            shutil.copyfile(HERE/'hardware'/name, src/'hw/misc'/name)
        meson = src/'hw/misc/meson.build'
        with meson.open('a') as stream:
            stream.write("\nsystem_ss.add(files('sony_atu.c', 'atu_core.c'))\n")
        virt = src/'hw/arm/virt.c'
        text = virt.read_text(); anchor = '    create_gic(vms, sysmem);\n'
        assert text.count(anchor) == 1
        virt.write_text(text.replace(anchor, anchor+(HERE/'hardware/virt-atu.inc').read_text()))
        proof = {'scope':'default-off virtual ATU with explicit test peer RAM; no CP/CMOS',
                 'source_archive_sha256':origin['source_archive_sha256'],
                 'dma_delta_sha256':origin['delta_patch_sha256'],
                 'model_source_sha256':{name:sha(HERE/'hardware'/name) for name in model_files},
                 'virt_after':sha(virt), 'pcidma_verified':False, 'capture_verified':False}
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
                    'build-atu', str(src)]
        subprocess.run(command, check=True)
        proof['binary_sha256'] = sha(stage/'build/qemu-system-aarch64')
        (stage/'build-proof.json').write_text(json.dumps(proof, indent=2)+'\n')
        print('ATU_CANDIDATE_BINARY', stage/'build/qemu-system-aarch64', flush=True)


if __name__ == '__main__':
    main()
