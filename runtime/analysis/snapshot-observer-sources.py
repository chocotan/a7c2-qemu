"""Freeze public observer/runtime contract sources; firmware and assets are never copied."""
import argparse
import hashlib
import json
from pathlib import Path
import tarfile

NATIVE = Path('report/2026-10-17-qemu-native-camera/runtime/analysis')
SHARED = NATIVE / 'device-models'
METADATA_INPUTS = (
    'report/virtual-sensor/sensor-core.c', 'report/virtual-sensor/sensor-core.h',
    'runtime/analysis/functional_camera_broker.py', 'runtime/analysis/backup_profile.py',
    'report/native-video-binding/native-video.c', 'report/native-video-binding/native-video.h',
    'report/native-video-paramsets/native-paramsets.c', 'report/native-video-paramsets/native-paramsets.h',
    'report/native-video-au-contract/native-au.c', 'report/native-video-au-contract/native-au.h',
    'report/native-video-length-format/native-lengths.c', 'report/native-video-length-format/native-lengths.h',
    'report/virtual-video-engine/video-engine.h',
    'report/functional-capture-input/capture-input.c', 'report/functional-capture-input/capture-input.h',
    'report/functional-capture-input/capture-mapper.c', 'report/functional-capture-input/capture-mapper.h',
    'report/functional-capture-input/capture-jpeg-input.c', 'report/functional-capture-input/capture-jpeg-input.h',
    'report/functional-capture-output/capture-output-memory.c', 'report/functional-capture-output/capture-output-memory.h',
    'report/functional-capture-output/capture-notifications.c', 'report/functional-capture-output/capture-notifications.h',
    'report/functional-capture-output/capture-delivery.c', 'report/functional-capture-output/capture-delivery.h',
    'report/functional-capture-output/capture-save.c', 'report/functional-capture-output/capture-save.h',
    'report/functional-capture-output/capture-dma.c', 'report/functional-capture-output/capture-dma.h',
    'report/functional-capture-queue/capture-resize-request.c', 'report/functional-capture-queue/capture-resize-request.h',
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


def _build_stamp_state(native):
    udate_dir = native.parents[1] / 'report/virtual-cp/udate-distribution'
    udate_inputs = sorted(p for p in udate_dir.iterdir() if p.suffix in ('.c', '.S', '.h', '.sh')) if udate_dir.is_dir() else []
    extra_dirs = (
        native / 'guest-overlay/simulation/diag.sh',
        native / 'guest-overlay/simulation/input-state.sh',
        native / 'build-observers.sh',
        native / 'snapshot-observer-sources.py',
        native / 'make-media-fixture.py',
        *udate_inputs,
    )
    libs = tuple(native / 'menu-root/lib' / name for name in ('libc-2.25.so', 'libdl-2.25.so', 'libpthread-2.25.so', 'ld-2.25.so'))
    outputs = [
        native / 'menu-observe.so',
        native / 'observer-build-inputs.json',
        native / 'observer-build-sources.tar.gz',
        native / 'menu-root/simulation/menu-observe.so',
        native / 'menu-root/simulation/pin-control-probe',
        native / 'menu-root/simulation/system-sound-owner',
        native / 'menu-root/simulation/sony_udate_distribution.ko',
        native / 'menu-root/simulation/mutex-trace.so',
        native / 'menu-root/simulation/ramfb-viewer',
        native / 'menu-root/simulation/sd-window-export',
        native / 'menu-root/simulation/sd-sparse',
        native / 'menu-root/simulation/host-sd-probe',
        native / 'menu-root/simulation/virtual-hci',
        native / 'menu-root/simulation/headless-osd-export',
        native / 'menu-root/simulation/gui-model-export',
        native / 'menu-root/simulation/menu-readmem',
        native / 'menu-root/simulation/menu-regs',
        native / 'menu-root/simulation/input-table',
        native / 'menu-root/simulation/menu-scanmem',
        native / 'menu-root/lib/observe-constructor.so',
        native / 'menu-root/simulation/check-menu-observe',
        native / 'menu-root/simulation/seed-date-clock',
        native / 'menu-root/simulation/seed-power-on',
        native / 'menu-root/simulation/user-settings-checkpoint',
        native / 'menu-root/simulation/seed-indicator-config',
        native / 'menu-root/simulation/inject-key',
        native / 'menu-root/simulation/inject-cp-event',
        native / 'menu-root/simulation/backup-dump',
        native / 'fast-osd-blend.so',
    ]
    media_flags = (os.environ.get('MENU_MEDIA_SELFTEST', '0'), os.environ.get('MENU_RM_FILE', '0'))
    if '1' in media_flags:
        outputs.extend([
            native / 'menu-root/simulation/host-block-sd.so',
            native / 'menu-root/simulation/file-media-config.so',
            native / 'menu-root/simulation/fsys-file-test',
            native / 'menu-root/simulation/media-camera.fat',
        ])
    input_rows = {}
    for path in [*source_paths(native), *extra_dirs, *libs]:
        if path.is_symlink() or not path.is_file():
            return None
        st = path.stat()
        input_rows[str(path)] = [st.st_size, st.st_mtime_ns]
    output_rows = {}
    for path in outputs:
        if not path.is_file():
            return None
        st = path.stat()
        output_rows[str(path)] = [st.st_size, st.st_mtime_ns]
    return {'media_flags': list(media_flags), 'inputs': input_rows, 'outputs': output_rows}


def check_stamp(native):
    stamp = native / '.observer-build.stamp.json'
    if not stamp.is_file():
        return 1
    try:
        recorded = json.loads(stamp.read_text())
    except (OSError, json.JSONDecodeError):
        return 1
    current = _build_stamp_state(native)
    return 0 if current is not None and current == recorded else 1


def write_stamp(native):
    state = _build_stamp_state(native)
    if state is None:
        raise ValueError('Observer build outputs incomplete')
    (native / '.observer-build.stamp.json').write_text(json.dumps(state, sort_keys=True) + '\n')


if __name__ == '__main__':
    import os
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('native', type=Path)
    parser.add_argument('work', type=Path, nargs='?')
    parser.add_argument('--finish', action='store_true')
    parser.add_argument('--check-stamp', action='store_true')
    parser.add_argument('--write-stamp', action='store_true')
    args = parser.parse_args()
    native = args.native.resolve()
    if args.check_stamp:
        raise SystemExit(check_stamp(native))
    if args.write_stamp:
        write_stamp(native)
    else:
        if args.work is None:
            parser.error('work directory required unless --check-stamp or --write-stamp is set')
        (finish if args.finish else snapshot)(native, args.work.resolve())
