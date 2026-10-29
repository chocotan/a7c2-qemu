"""Freeze public C/header/shell inputs; firmware and runtime assets are never copied."""
import argparse
import hashlib
import json
from pathlib import Path
import tarfile

NATIVE = Path('report/2026-10-17-qemu-native-camera/runtime/analysis')
SHARED = NATIVE / 'device-models'
METADATA_INPUTS = (
    'report/native-video-binding/native-video.c', 'report/native-video-binding/native-video.h',
    'report/native-video-paramsets/native-paramsets.c', 'report/native-video-paramsets/native-paramsets.h',
    'report/native-video-au-contract/native-au.c', 'report/native-video-au-contract/native-au.h',
    'report/native-video-length-format/native-lengths.c', 'report/native-video-length-format/native-lengths.h',
    'report/virtual-video-engine/video-engine.h',
)


def source_paths(native):
    local = [path for directory in (native, native / 'device-models')
             for path in sorted(directory.iterdir()) if path.suffix in ('.c', '.h', '.inc', '.sh')]
    return local + [native.parents[1] / name for name in METADATA_INPUTS]


def snapshot(native, work):
    inputs = {}
    for path in source_paths(native):
        if path.is_symlink() or not path.is_file():
            raise ValueError(f'Expected ordinary source: {path}')
        relative = NATIVE.parents[1] / path.relative_to(native.parents[1])
        target = work / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        data = path.read_bytes()
        target.write_bytes(data)
        inputs[str(path)] = {'archive_path': str(relative),
                             'sha256': hashlib.sha256(data).hexdigest()}
    for path, entry in inputs.items():
        if hashlib.sha256(Path(path).read_bytes()).hexdigest() != entry['sha256']:
            raise ValueError(f'Source changed during snapshot: {path}')
    (work / 'source-inputs.json').write_text(json.dumps(inputs, indent=2) + '\n')


def finish(native, work):
    archive = native / 'observer-build-sources.tar.gz'
    with tarfile.open(archive, 'w:gz') as tar:
        tar.add(work / 'report', arcname='report')
        tar.add(work / 'source-inputs.json', arcname='source-inputs.json')
    proof = {'sources': json.loads((work / 'source-inputs.json').read_text()),
             'source_archive_sha256': hashlib.sha256(archive.read_bytes()).hexdigest(),
             'observer_sha256': hashlib.sha256((native / 'menu-observe.so').read_bytes()).hexdigest(),
             'pin_control_probe_sha256': hashlib.sha256((native / 'menu-root/simulation/pin-control-probe').read_bytes()).hexdigest()}
    proof['system_sound_owner_sha256'] = hashlib.sha256((native / 'menu-root/simulation/system-sound-owner').read_bytes()).hexdigest()
    (native / 'observer-build-inputs.json').write_text(json.dumps(proof, indent=2) + '\n')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('native', type=Path)
    parser.add_argument('work', type=Path)
    parser.add_argument('--finish', action='store_true')
    args = parser.parse_args()
    (finish if args.finish else snapshot)(args.native.resolve(), args.work.resolve())
