#!/usr/bin/env python3
"""Explicit, data-only loading of the original image expected by load=0."""
import argparse
import hashlib
from pathlib import Path
import re
import runpy
import shutil
import tempfile

HERE = Path(__file__).resolve().parent
PHYSICAL = 0x401000000
CAPACITY = 0x1000000
IMAGE_BYTES = 0xd286e0
IMAGE_SHA256 = '90343f5f2edc0393ad8809d907cfe648dfd3a82ce0ef39cf06167929d8955096'
SYSTEM_BYTES = 78643200
SYSTEM_SHA256 = 'b6ea7fced5622e9b36c9bd5b2c7e16743559fe05e50a8da2063a741dfc047ebd'
KERNEL_SHA256 = '620a6a3c2b4f09a3696f2fbf06bab98b49be5eaad6bdb366a1f33319fcb6e9d2'
NUMBER = r'(?:0[xX][0-9a-fA-F]+|0|[1-9][0-9]*)'


def ordinary(path):
    path = Path(path)
    if path.is_symlink() or not path.is_file():
        raise ValueError('Expected an ordinary preload input: ' + str(path))
    return path


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def validate_image(path):
    path = ordinary(path)
    if path.stat().st_size != IMAGE_BYTES or digest(path) != IMAGE_SHA256:
        raise ValueError('Original av-cam data identity differs')
    with path.open('rb') as stream:
        stream.seek(8)
        if stream.read(4) != b'ORIL':
            raise ValueError('Original av-cam ORIL header differs')
    return path


def ensure_image(base):
    """Caller owns the runtime lock; original FAT and inputs remain read-only."""
    base = Path(base)
    directory = base / 'liro-preload'
    if directory.is_symlink():
        raise ValueError('Refuse a symlink preload directory')
    target = directory / 'av-cam.bin'
    if target.exists() or target.is_symlink():
        return validate_image(target)
    source = ordinary(base / 'root/partitions/nflasha3.img')
    if source.stat().st_size != SYSTEM_BYTES or digest(source) != SYSTEM_SHA256:
        raise ValueError('Full-dump system partition identity differs')
    if shutil.disk_usage(base).free < 2 * IMAGE_BYTES + 1024 * 1024:
        raise ValueError('Insufficient space for verified data extraction')
    directory.mkdir(exist_ok=True)
    api = runpy.run_path(str(HERE / 'prepare-full-system.py'))
    with tempfile.TemporaryDirectory(prefix='extract-', dir=directory) as temporary:
        extracted = Path(temporary) / 'av-cam.bin'
        api['fat_extract'](source, Path(temporary), {'av-cam.bin'})
        validate_image(extracted)
        # Exclusive creation does not replace unexpected/partial evidence.
        with extracted.open('rb') as incoming, target.open('xb') as outgoing:
            while chunk := incoming.read(65536):
                outgoing.write(chunk)
        target.chmod(0o444)
    return validate_image(target)


def validate_plan(workspace, loads):
    """Sony's original early memrsv parser reserves and maps :ex as executable.

    This switch supplies data in that existing reservation; it changes neither
    the memory attributes nor any CPU entry/LIRO initialization path.
    """
    if not isinstance(workspace, str) or not workspace.strip():
        raise ValueError('Missing original workspace memory plan')
    owned = 0
    for word in workspace.split():
        if not word.startswith('memrsv='):
            continue
        match = re.fullmatch(r'memrsv=(' + NUMBER + r')@(' + NUMBER + r')(?::([a-z]+))?', word)
        if not match:
            raise ValueError('Unrecognized original reservation token')
        size, start = (int(value, 0) for value in match.groups()[:2])
        if not size or start + size > 1 << 64:
            raise ValueError('Invalid original reservation range')
        if start < PHYSICAL + CAPACITY and PHYSICAL < start + size:
            if (start, size, match.group(3)) != (PHYSICAL, CAPACITY, 'ex') or owned:
                raise ValueError('Missing, duplicate or foreign overlapping preload reservation')
            owned += 1
    if owned != 1:
        raise ValueError('Original 16 MiB executable reservation was not declared')
    if not 0x400000000 <= PHYSICAL < PHYSICAL + CAPACITY <= 0x600000000:
        raise ValueError('Preload is outside declared full-dump DDR')
    for name, start, size in loads:
        if size <= 0 or start < 0 or start + size > 1 << 64:
            raise ValueError('Invalid declared boot load: ' + name)
        if start < PHYSICAL + CAPACITY and PHYSICAL < start + size:
            raise ValueError('Preload overlaps a declared boot load: ' + name)
    return {'physical': PHYSICAL, 'capacity': CAPACITY, 'bytes': IMAGE_BYTES, 'sha256': IMAGE_SHA256,
            'supplies_image_data': True, 'sets_cpu_entry': False, 'initializes_LIRO': False}


def adapt_script(text):
    if '# FULLSYSTEM_AVCAM_DATA_PRELOAD' in text:
        return text
    anchor = 'mkdir -p "$output_dir"\nif [[ -n "${QEMU_OUTPUT_DIR:-}" ]]; then'
    if text.count(anchor) != 1 or text.count('    "${handoff_bind[@]}" \\\n') != 1:
        raise ValueError('Ambiguous data preload sandbox/loader insertion')
    code = ('# FULLSYSTEM_AVCAM_DATA_PRELOAD: no cpu-num, no entry-point change.\n'
            'avcam_bind=()\n'
            'if [[ "${QEMU_FULL_AVCAM_PRELOAD:-0}" == 1 ]]; then\n'
            '  [[ "$high_ddr" == 1 ]] || { echo "Preload requires full-dump DDR" >&2; exit 2; }\n'
            '  python3 "$analysis_dir/../../avcam-preload.py" --image "${QEMU_FULL_AVCAM_IMAGE:?}" \\\n'
            '    --workspace "$cmdline" --kernel "$bootfs/vmlinux.bin" --initrd "$test_initrd" --dtb "$output_dir/virt.dtb"\n'
            '  avcam_bind=(--ro-bind "$QEMU_FULL_AVCAM_IMAGE" /av-cam-preload.bin)\n'
            '  loader_args+=(-device loader,file=/av-cam-preload.bin,addr=0x401000000,force-raw=on)\n'
            'fi\n')
    return text.replace(anchor, code + anchor, 1).replace('    "${handoff_bind[@]}" \\\n',
        '    "${handoff_bind[@]}" \\\n    "${avcam_bind[@]}" \\\n', 1)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('image', 'kernel', 'initrd', 'dtb'):
        parser.add_argument('--' + name, type=Path, required=True)
    parser.add_argument('--workspace', required=True)
    args = parser.parse_args()
    validate_image(args.image)
    if digest(ordinary(args.kernel)) != KERNEL_SHA256:
        raise ValueError('Preload requires the original Sony memrsv kernel')
    loads = [(name, address, ordinary(path).stat().st_size) for name, address, path in
             (('kernel', 0x400080000, args.kernel), ('initrd', 0x440000000, args.initrd), ('DTB', 0x400002000, args.dtb))]
    validate_plan(args.workspace, loads + [('boot handoff', 0x400010000, 96)])
    print('FULLSYSTEM_AVCAM_DATA_PRELOAD_VALIDATED bytes=' + str(IMAGE_BYTES) + ' sha256=' + IMAGE_SHA256)


if __name__ == '__main__':
    main()
