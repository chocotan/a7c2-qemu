#!/usr/bin/env python3
"""Build the software-defined camera hardware model; never runs a VM or writes media."""
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import tarfile
import tempfile

BASE = Path(__file__).resolve().parent
ROOT = BASE.parents[1]
REPORT = ROOT / 'report'
COMPONENTS = (
    'virtual-optics', 'virtual-optical-frame-owner', 'virtual-jpeg-hardware',
    'virtual-jpeg-sos', 'virtual-video-engine', 'virtual-camera-pipeline',
    'functional-camera-core',
)
SOURCES = (
    'virtual-optics/optics.c',
    'virtual-optical-frame-owner/optical-frame-owner.c',
    'virtual-jpeg-hardware/jpeg-hardware.c',
    'virtual-jpeg-hardware/jpeg-hardware-codec.c',
    'virtual-jpeg-sos/jpeg-sos.c',
    'virtual-video-engine/video-engine.c',
    'virtual-camera-pipeline/camera-pipeline.c',
    'functional-camera-core/functional-camera-core.c',
)


def sha(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def save(path, value):
    with path.open('x') as stream:
        json.dump(value, stream, indent=2)
        stream.write('\n')


def main():
    if len(sys.argv) != 1:
        raise ValueError('the functional model has one fixed local build, with no alternate source or output path')
    compiler = shutil.which('cc')
    if not compiler:
        raise RuntimeError('installed host C compiler is required')
    sources = [REPORT / name for name in SOURCES]
    headers = [BASE / 'functional-camera-abi.h', BASE / 'functional-vdf-path-abi.h',
               BASE / 'functional-bb-startup-abi.h']
    for component in COMPONENTS:
        headers.extend((REPORT / component).glob('*.h'))
    paths = sorted(set([*sources, *headers, Path(__file__)]))
    missing = [str(path.relative_to(ROOT)) for path in paths if not path.is_file()]
    if missing:
        raise RuntimeError('finish the complete model before building: ' + ', '.join(missing))
    before = {str(path.relative_to(ROOT)): sha(path) for path in paths}
    work = Path(tempfile.mkdtemp(prefix='functional-model-build-', dir=BASE / 'scratch'))
    save(work / 'inputs.json', {'scope': 'host software hardware model, not original ASIC compatibility',
                              'sources': before, 'capture_verified': False})
    flags = subprocess.check_output([
        'pkg-config', '--cflags', '--libs', 'libjpeg', 'libavcodec', 'libavformat',
        'libavutil', 'libswscale'], text=True, timeout=15).split()
    candidate = work / 'functional-camera-model.so'
    command = [compiler, '-std=c11', '-O2', '-fPIC', '-shared', '-Wall', '-Wextra',
               '-Werror', '-pedantic', '-Wl,--no-undefined', *map(str, sources),
               '-o', str(candidate), *flags, '-lm']
    built = subprocess.run(command, capture_output=True, text=True, timeout=180)
    with (work / 'build.log').open('x') as stream:
        stream.write(built.stdout + built.stderr)
    save(work / 'compile.json', {'command': command, 'returncode': built.returncode,
                                'log_sha256': sha(work / 'build.log')})
    if built.returncode:
        raise RuntimeError('functional model build failed; evidence retained at ' + str(work))
    if {str(path.relative_to(ROOT)): sha(path) for path in paths} != before:
        raise RuntimeError('model sources changed during compilation; binary not published: ' + str(work))
    raw = candidate.read_bytes()
    if raw[:6] != b'\x7fELF\x02\x01' or len(raw) < 64 or struct.unpack_from('<H', raw, 16)[0] != 3:
        raise RuntimeError('compiler did not produce a little-endian ELF64 shared library')
    archive_path = work / 'functional-model-sources.tar.gz'
    with tarfile.open(archive_path, 'x:gz') as archive:
        for path in paths:
            content = path.read_bytes()
            name = str(path.relative_to(ROOT))
            if hashlib.sha256(content).hexdigest() != before[name]:
                raise RuntimeError('source changed before archive: ' + name)
            item = tarfile.TarInfo(name)
            item.size = len(content)
            item.mode = path.stat().st_mode & 0o777
            archive.addfile(item, io.BytesIO(content))
    with tarfile.open(archive_path, 'r:gz') as archive:
        members = archive.getmembers()
        if len(members) != len(before) or len({item.name for item in members}) != len(members):
            raise RuntimeError('model archive is incomplete or has duplicate members')
        for item in members:
            if hashlib.sha256(archive.extractfile(item).read()).hexdigest() != before[item.name]:
                raise RuntimeError('model archive readback differs: ' + item.name)
    receipt = {'scope': 'software-defined functional camera hardware model; original AP/MPR/Fsys acceptance is separate',
               'profile': 'virtual-functional-camera-v1', 'work': str(work.relative_to(ROOT)),
               'sources': before, 'source_archive_sha256': sha(archive_path),
               'library_sha256': sha(candidate), 'compiler': compiler,
               'compile_receipt_sha256': sha(work / 'compile.json'),
               'physical_asic_compatibility_verified': False, 'capture_verified': False}
    save(work / 'build.json', receipt)
    target = BASE / 'functional-camera-model.so'
    metadata = BASE / 'functional-camera-model-build.json'
    if target.is_symlink() or metadata.is_symlink():
        raise RuntimeError('functional model output may not be a symlink')
    # Publish only a compiled/read-back model; preserve its immutable source/archive receipts.
    pending = BASE / ('.functional-camera-model-' + work.name + '.so')
    with pending.open('xb') as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    if sha(pending) != receipt['library_sha256']:
        raise RuntimeError('model library writeback differs')
    os.replace(pending, target)
    pending_metadata = BASE / ('.functional-camera-model-' + work.name + '.json')
    save(pending_metadata, receipt)
    os.replace(pending_metadata, metadata)
    if sha(target) != receipt['library_sha256']:
        raise RuntimeError('published model differs')
    print('FUNCTIONAL_CAMERA_MODEL_BUILD_PASS', work, receipt['library_sha256'])
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
