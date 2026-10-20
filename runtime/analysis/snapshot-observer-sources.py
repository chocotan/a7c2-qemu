"""Freeze public C/header/shell inputs; firmware and runtime assets are never copied."""
import argparse
import hashlib
import json
from pathlib import Path
import tarfile

NATIVE = Path('report/2026-10-17-qemu-native-camera/runtime/analysis')
SHARED = NATIVE / 'device-models'


def snapshot(native, work):
    inputs = {}
    for source, relative in ((native, NATIVE), (native / 'device-models', SHARED)):
        target = work / relative
        target.mkdir(parents=True)
        files = sorted(p for p in source.iterdir() if p.suffix in ('.c', '.h', '.inc','.sh'))
        for path in files:
            if path.is_symlink() or not path.is_file():
                raise ValueError(f'Expected ordinary source: {path}')
            data = path.read_bytes()
            (target / path.name).write_bytes(data)
            inputs[str(path)] = {'archive_path': str(relative / path.name),
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
