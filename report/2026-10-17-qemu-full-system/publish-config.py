#!/usr/bin/env python3
"""Publish a revalidated, immutable BK4 export snapshot into an idle private runtime.

Official assets are read only. Volume edits and initramfs packing run on a staging
copy; guarded commit errors roll back, and interrupted commits block boot/build
until config-state.py --recover resolves their journal.
"""
import argparse
import hashlib
import json
from pathlib import Path
import runpy

HERE = Path(__file__).resolve().parent
STATE = runpy.run_path(str(HERE / 'config-state.py'))
BACKUP = runpy.run_path(str(HERE / 'backup-state.py'))
TARGETS = (('Backup.bin', 'BACKUP.BIN'), ('Backup.bak', 'BACKUP.BAK'))


def sha256(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def verified_pair(run, verdict, reference):
    items = verdict.get('files', [])
    if (verdict.get('export_verified') is not True or len(items) != 2
            or {item.get('name') for item in items} != {name for name, _ in TARGETS}):
        raise ValueError('export verdict must describe exactly the verified Backup pair')
    evidence = {item['name']: item for item in items}
    snapshots = {}
    for local, remote in TARGETS:
        item = evidence[local]
        data = STATE['read_regular'](run / local, expected=BACKUP['FILE_BYTES'])
        if (item.get('valid') is not True or item.get('bytes') != len(data)
                or item.get('sha256') != hashlib.sha256(data).hexdigest()):
            raise ValueError('export bytes no longer match their verdict: ' + local)
        BACKUP['validate'](data, reference)
        snapshots[remote] = data
    return snapshots


def publish_locked(args, runtime, run):
    owned = STATE['owned']
    for name in STATE['TARGETS']:
        owned(runtime, 'analysis/' + name, directory=name == 'runs', missing=True)
    image = owned(runtime, 'analysis/root/partitions/nflasha2.img')
    reference_path = owned(runtime, 'analysis/official-pp.bin', missing=True)
    current = STATE['extract'](image, 'BACKUP.BIN')
    if current is None:
        raise ValueError('derived volume has no BACKUP.BIN')
    current_sha = hashlib.sha256(current).hexdigest()
    official_sha = BACKUP['OFFICIAL_PP_SHA256']
    if current_sha != official_sha and not args.force_generation:
        raise ValueError('derived volume no longer holds official PP; --force-generation is required')
    reference = STATE['read_regular'](reference_path) if reference_path.exists() else current
    if hashlib.sha256(reference).hexdigest() != official_sha:
        raise ValueError('verified official PP reference is unavailable')
    BACKUP['validate'](current, reference)
    verdict = json.loads(STATE['read_regular'](run / 'config-persistence.json'))
    snapshots = verified_pair(run, verdict, reference)
    if args.keep_parent_as_bak:
        snapshots['BACKUP.BAK'] = current
    if args.omit_bak:
        snapshots.pop('BACKUP.BAK')
    record = {'schema': 'config-generation-v2', 'runtime': str(runtime), 'source_run': str(run),
              'parent_backup_sha256': current_sha, 'parent_was_official_pp': current_sha == official_sha,
              'console_sha256': verdict.get('console_sha256'), 'applied': False,
              'files': {name: {'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()}
                        for name, data in snapshots.items()}}
    if args.keep_parent_as_bak:
        record['files']['BACKUP.BAK']['source'] = 'parent generation'
    if not args.apply:
        print(json.dumps(record, indent=2))
        return 0
    with STATE['Transaction'](runtime) as transaction:
        for remote, data in snapshots.items():
            source = transaction.stage / remote
            source.write_bytes(data)
            STATE['mcopy'](transaction.image, source, remote)
        if args.omit_bak:
            STATE['delete_file'](transaction.image, 'BACKUP.BAK')
        for remote, data in snapshots.items():
            if STATE['extract'](transaction.image, remote) != data:
                raise RuntimeError('staged ' + remote + ' readback differs')
        record['initrd_sha256'] = transaction.repack()
        record['derived_image_sha256'] = sha256(transaction.image)
        record['applied'] = True
        staged_record = transaction.stage / 'config-generation.json'
        staged_record.write_text(json.dumps(record, indent=2) + '\n')
        staged_reference = transaction.stage / 'official-pp.bin'
        staged_reference.write_bytes(reference)
        transaction.commit({'root/partitions/nflasha2.img': transaction.image,
                            'full-system.cpio': transaction.stage / 'full-system.cpio',
                            'full-system.json': transaction.stage / 'full-system.json',
                            'official-pp.bin': staged_reference, 'config-generation.json': staged_record})
    print('CONFIG_GENERATION_PUBLISHED', runtime / 'analysis/config-generation.json')
    print('  parent', current_sha[:16], '-> Backup.bin', record['files']['BACKUP.BIN']['sha256'][:16])
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--runtime', type=Path, required=True)
    parser.add_argument('--from-run', type=Path, required=True)
    parser.add_argument('--apply', action='store_true')
    pairing = parser.add_mutually_exclusive_group()
    pairing.add_argument('--omit-bak', action='store_true')
    pairing.add_argument('--keep-parent-as-bak', action='store_true')
    parser.add_argument('--force-generation', action='store_true')
    args = parser.parse_args()
    runtime, run = args.runtime.resolve(strict=True), args.from_run.resolve(strict=True)
    with STATE['exclusive_runtime'](runtime):
        return publish_locked(args, runtime, run)


if __name__ == '__main__':
    raise SystemExit(main())
