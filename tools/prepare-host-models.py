#!/usr/bin/env python3
"""Build public DTC/libfdt and the project DTB for host profile tests; never build or run QEMU."""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]


def sha(path):
    if path.is_symlink() or not path.is_file():
        raise ValueError('Expected ordinary public source: ' + str(path))
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def main():
    source = ROOT / 'source/dtc'
    expected = json.loads((ROOT / 'source/manifest.json').read_text())['dtc_source_files']
    if {p.relative_to(source).as_posix() for p in source.rglob('*') if p.is_file()} != set(expected):
        raise ValueError('DTC source inventory differs')
    if any(sha(source / name) != digest for name, digest in expected.items()):
        raise ValueError('DTC source identity differs')
    temporary = ROOT / 'validation/tmp'
    temporary.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix='host-dtc-', dir=temporary))
    tree = work / 'dtc'
    shutil.copytree(source, tree)
    command = ['make', '-j2', 'NO_PYTHON=1', 'EXTRA_CFLAGS=-Wno-error=discarded-qualifiers', 'dtc', 'libfdt']
    with (work / 'build.log').open('xb') as log:
        result = subprocess.run(command, cwd=tree, stdout=log, stderr=subprocess.STDOUT)
    if result.returncode:
        raise ValueError('Public DTC host build failed; see ' + str(work / 'build.log'))
    dtc = ROOT / 'runtime/sources/dtc-local/dtc'
    library = ROOT / 'runtime/sources/qemu-tools/usr/lib/libfdt.so.1'
    for original, target in ((tree / 'dtc', dtc), ((tree / 'libfdt/libfdt.so.1').resolve(strict=True), library)):
        if target.is_symlink():
            raise ValueError('Refusing linked host build output')
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(original, target)
        target.chmod(0o755)
        if sha(original) != sha(target):
            raise ValueError('Host build output readback differs')
    board = ROOT / 'runtime/analysis/qemu-virt-board/virt-packed.dts'
    output = board.with_suffix('.dtb')
    command = [str(dtc), '-I', 'dts', '-O', 'dtb', '-o', str(output), str(board)]
    with (work / 'board.log').open('xb') as log:
        subprocess.run(command, check=True, stdout=log, stderr=subprocess.STDOUT)
    if output.read_bytes()[:4] != bytes.fromhex('d00dfeed'):
        raise ValueError('Generated project DTB magic differs')
    if any(sha(source / name) != digest for name, digest in expected.items()):
        raise ValueError('Public DTC source changed during host preparation')
    receipt = dict(scope='public DTC and project DTB only; no QEMU, Sony firmware or VM',
                   source_files=len(expected), dtc_sha256=sha(dtc), libfdt_sha256=sha(library),
                   dts_sha256=sha(board), dtb_sha256=sha(output), build_returncode=result.returncode)
    (work / 'result.json').write_text(json.dumps(receipt, indent=2) + '\n')
    print('HOST_DTC_AND_PROJECT_DTB_PREPARED', work)


if __name__ == '__main__':
    main()
