#!/usr/bin/env python3
"""Reset only an idle, derived runtime; preserve bodydata/, overwrite/, and SD/.

The default only reports. --apply --confirm reset stages the setting volume and
initramfs, verifies the restored official PP, and commits with rollback protection.
The verified PP reference is retained so a second reset remains possible.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import runpy

HERE = Path(__file__).resolve().parent
STATE = runpy.run_path(str(HERE / 'config-state.py'))
OFFICIAL_PP_SHA = '3dab4f0d6b7790f4a7798034b57f43bfe3255c39dc6da2897fc288b3a218fe47'
CONFIRMATION = 'reset'
PROTECTED = ('bodydata', 'overwrite', 'SD')


def sha256(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def reset_locked(args, runtime):
    for name in PROTECTED:
        if os.path.lexists(runtime / name):
            raise SystemExit(f'refusing: {name} lives inside this runtime')
    owned = STATE['owned']
    for name in STATE['TARGETS']:
        owned(runtime, 'analysis/' + name, directory=name == 'runs', missing=True)
    image = owned(runtime, 'analysis/root/partitions/nflasha2.img')
    pp_copy = owned(runtime, 'analysis/official-pp.bin', missing=True)
    reference = STATE['read_regular'](pp_copy) if pp_copy.exists() else None
    if args.apply and reference is not None and hashlib.sha256(reference).hexdigest() != OFFICIAL_PP_SHA:
        raise SystemExit('need a verified official ALLLANG PP reference')
    current = STATE['extract'](image, 'BACKUP.BIN')
    current_sha = hashlib.sha256(current).hexdigest() if current is not None else None
    if reference is None:
        reference = current
    reference_valid = reference is not None and hashlib.sha256(reference).hexdigest() == OFFICIAL_PP_SHA
    if args.apply and not reference_valid:
        raise SystemExit('need a verified official ALLLANG PP reference')
    plan = {'schema': 'config-reset-v2', 'runtime': str(runtime), 'applied': False,
            'confirmation_required': CONFIRMATION,
            'will': ['restore /setting/Backup.bin from the verified official ALLLANG PP',
                     'remove /setting/Backup.bak and analysis/config-generation.json',
                     'repack and verify the initramfs before committing',
                     'remove analysis/runs unless --keep-runs'],
            'untouched': ['bodydata/', 'overwrite/', 'SD/', 'external official firmware assets'],
            'reference_retained': True, 'reference_valid': reference_valid,
            'backup_before': current_sha, 'backup_was_official_pp': current_sha == OFFICIAL_PP_SHA}
    if not args.apply:
        print(json.dumps(plan, indent=2))
        return 0
    with STATE['Transaction'](runtime) as transaction:
        staged_pp = transaction.stage / 'official-pp.bin'
        staged_pp.write_bytes(reference)
        STATE['mcopy'](transaction.image, staged_pp, 'BACKUP.BIN')
        STATE['delete_file'](transaction.image, 'BACKUP.BAK')
        check = STATE['extract'](transaction.image, 'BACKUP.BIN')
        if check != reference or STATE['extract'](transaction.image, 'BACKUP.BAK') is not None:
            raise RuntimeError('staged reset readback differs; original runtime has not been changed')
        plan['initrd_sha256'] = transaction.repack()
        plan['derived_image_sha256'] = sha256(transaction.image)
        plan['applied'] = True
        record = transaction.stage / 'reset-record.json'
        record.write_text(json.dumps(plan, indent=2) + '\n')
        replacements = {'root/partitions/nflasha2.img': transaction.image,
                        'full-system.cpio': transaction.stage / 'full-system.cpio',
                        'full-system.json': transaction.stage / 'full-system.json',
                        'official-pp.bin': staged_pp, 'config-generation.json': None,
                        'reset-record.json': record}
        if not args.keep_runs:
            new_runs = transaction.stage / 'runs'
            new_runs.mkdir()
            replacements['runs'] = new_runs
            plan['runs_removed'] = True
            record.write_text(json.dumps(plan, indent=2) + '\n')
        transaction.commit(replacements)
    print('CONFIG_RESET_APPLIED', runtime / 'analysis/reset-record.json')
    print('  verified official PP restored; Backup.bak removed; initramfs', plan['initrd_sha256'][:16])
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--runtime', type=Path, required=True)
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--confirm', default='')
    parser.add_argument('--keep-runs', action='store_true')
    args = parser.parse_args()
    runtime = args.runtime.resolve(strict=True)
    if not (runtime / 'analysis/full-system.json').is_file():
        raise SystemExit('that path is not a full-system runtime')
    if args.apply and args.confirm != CONFIRMATION:
        raise SystemExit(f'refusing: --apply needs --confirm {CONFIRMATION}')
    with STATE['exclusive_runtime'](runtime):
        return reset_locked(args, runtime)


if __name__ == '__main__':
    raise SystemExit(main())
