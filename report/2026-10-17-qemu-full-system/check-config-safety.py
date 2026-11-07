#!/usr/bin/env python3
"""Host-only real mtools/cpio checks in a new scratch runtime, never a running VM."""
import argparse
import fcntl
import hashlib
import json
from pathlib import Path
import runpy
import shutil
import subprocess
import sys
from types import SimpleNamespace
from unittest import mock

HERE = Path(__file__).resolve().parent
STATE = runpy.run_path(str(HERE / 'config-state.py'))
BACKUP = runpy.run_path(str(HERE / 'backup-state.py'))
RESET = runpy.run_path(str(HERE / 'reset-derived-state.py'))


def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def tree(root):
    return {str(p.relative_to(root)): digest(p) for p in root.rglob('*') if p.is_file()}


def check(reference_image, source_run, output):
    output.mkdir(parents=True, exist_ok=False)
    runtime = output / 'scratch'
    base = runtime / 'analysis'
    (base / 'root/partitions').mkdir(parents=True)
    (base / '.run.lock').touch()
    (base / 'full-system.json').write_text('{"initrd_sha256":"not-built"}\n')
    (base / 'full-system.cpio').write_bytes(b'initial fixture archive')
    (base / 'runs').mkdir()
    (base / 'runs/canary').write_bytes(b'owned old run')
    image = base / 'root/partitions/nflasha2.img'
    shutil.copyfile(reference_image, image)
    image.chmod(0o600)
    official = STATE['extract'](image, 'BACKUP.BIN')
    if official is None or hashlib.sha256(official).hexdigest() != BACKUP['OFFICIAL_PP_SHA256']:
        raise ValueError('scratch must start from a derived image containing the verified official PP')
    source_hashes = {str(reference_image): digest(reference_image)}
    for name in ('Backup.bin', 'Backup.bak', 'config-persistence.json'):
        source_hashes[str(source_run / name)] = digest(source_run / name)
    protected = {}
    for name in ('bodydata', 'overwrite', 'SD'):
        (output / name).mkdir()
        (output / name / 'canary').write_bytes(b'untouched workspace data')
        protected[name] = tree(output / name)
    result = {'schema': 'config-storage-safety-check-v1', 'scope': 'host storage only, no VM or physical device',
              'runtime': str(runtime), 'cases': [], 'verified': False}

    def command(script, *args, success=True):
        invocation = [sys.executable, '-B', str(HERE / script), '--runtime', str(runtime), *map(str, args)]
        process = subprocess.run(invocation, capture_output=True, text=True, timeout=180)
        number = len(result['cases'])
        (output / f'command-{number:02d}.stdout').write_text(process.stdout)
        (output / f'command-{number:02d}.stderr').write_text(process.stderr)
        result['cases'].append({'command': invocation, 'returncode': process.returncode,
                                'expected_success': success})
        if (process.returncode == 0) != success:
            raise RuntimeError('unexpected command result: ' + script + ': ' + process.stderr[:600])
        return process

    def archive_matches():
        manifest = json.loads((base / 'full-system.json').read_text())
        assert manifest['initrd_sha256'] == digest(base / 'full-system.cpio')
        with (base / 'full-system.cpio').open('rb') as archive:
            extracted = subprocess.run(['cpio', '-i', '--to-stdout', 'partitions/nflasha2.img'],
                                       stdin=archive, capture_output=True, check=True, timeout=60).stdout
        assert hashlib.sha256(extracted).hexdigest() == digest(image)

    try:
        before = tree(runtime)
        command('publish-config.py', '--from-run', source_run)
        assert tree(runtime) == before  # Includes absence of an official-pp cache before dry-run.
        with (base / '.run.lock').open('a') as runner:
            fcntl.flock(runner, fcntl.LOCK_EX | fcntl.LOCK_NB)
            for script, args in [('publish-config.py', ['--from-run', source_run, '--apply']),
                                 ('reset-derived-state.py', ['--apply', '--confirm', 'reset'])]:
                process = command(script, *args, success=False)
                assert 'runtime is busy' in process.stderr
        assert tree(runtime) == before
        tampered = output / 'tampered-source'
        tampered.mkdir()
        for name in ('Backup.bin', 'Backup.bak', 'config-persistence.json'):
            shutil.copyfile(source_run / name, tampered / name)
        data = bytearray((tampered / 'Backup.bin').read_bytes())
        data[-1] ^= 1
        (tampered / 'Backup.bin').write_bytes(data)
        process = command('publish-config.py', '--from-run', tampered, '--apply', success=False)
        assert 'no longer match' in process.stderr
        assert tree(runtime) == before
        for name in ('runs', 'root/partitions/nflasha2.img'):
            target = base / name
            saved = target.with_name(target.name + '.saved')
            target.rename(saved)
            outside = output / 'outside-target'
            if saved.is_dir():
                outside.mkdir()
                (outside / 'canary').write_bytes(b'do not delete')
            else:
                shutil.copyfile(saved, outside)
            outside_before = tree(outside) if outside.is_dir() else digest(outside)
            target.symlink_to(outside, target_is_directory=saved.is_dir())
            try:
                process = command('reset-derived-state.py', '--apply', '--confirm', 'reset', success=False)
                assert 'symlink' in process.stderr
                assert (tree(outside) if outside.is_dir() else digest(outside)) == outside_before
            finally:
                target.unlink()
                saved.rename(target)
                shutil.rmtree(outside) if outside.is_dir() else outside.unlink()
        assert tree(runtime) == before
        command('publish-config.py', '--from-run', source_run, '--apply')
        for local, remote in [('Backup.bin', 'BACKUP.BIN'), ('Backup.bak', 'BACKUP.BAK')]:
            restored = STATE['extract'](image, remote)
            assert restored == (source_run / local).read_bytes()
            BACKUP['validate'](restored, official)
        archive_matches()
        published = tree(runtime)
        with RESET['STATE']['exclusive_runtime'](runtime):
            with mock.patch.object(RESET['STATE']['Transaction'], 'repack',
                                   side_effect=RuntimeError('injected packing failure')) as pack:
                try:
                    RESET['reset_locked'](SimpleNamespace(apply=True, keep_runs=False), runtime)
                except RuntimeError as error:
                    assert str(error) == 'injected packing failure'
                else:
                    raise AssertionError('fault injection was not reached')
                pack.assert_called_once()
        assert tree(runtime) == published
        result['cases'].append({'reset_packing_failure_leaves_all_published_files_unchanged': True})
        for attempt in range(2):
            command('reset-derived-state.py', '--apply', '--confirm', 'reset')
            assert STATE['extract'](image, 'BACKUP.BIN') == official
            assert STATE['extract'](image, 'BACKUP.BAK') is None
            assert not (base / 'config-generation.json').exists()
            assert digest(base / 'official-pp.bin') == BACKUP['OFFICIAL_PP_SHA256']
            assert not any((base / 'runs').iterdir())
            archive_matches()
        for name in protected:
            assert tree(output / name) == protected[name]
        assert all(digest(Path(path)) == value for path, value in source_hashes.items())
        result.update(verified=True, source_unchanged=True, protected_workspaces_unchanged=True,
                      original_image_sha256=source_hashes[str(reference_image)],
                      final_image_sha256=digest(image), final_initrd_sha256=digest(base / 'full-system.cpio'),
                      backend_sources={name: digest(HERE / name) for name in
                                       ('config-state.py', 'runtime-lock.py', 'publish-config.py', 'reset-derived-state.py')})
    except BaseException as error:
        result['error'] = repr(error)
        raise
    finally:
        (output / 'result.json').write_text(json.dumps(result, indent=2) + '\n')
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--reference-image', type=Path, required=True)
    parser.add_argument('--from-run', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True, help='a new scratch directory, must not exist')
    args = parser.parse_args()
    result = check(args.reference_image.resolve(strict=True), args.from_run.resolve(strict=True), args.output.absolute())
    print('CONFIG_STORAGE_SAFETY_VERIFIED', args.output / 'result.json', len(result['cases']), 'cases')


if __name__ == '__main__':
    main()
