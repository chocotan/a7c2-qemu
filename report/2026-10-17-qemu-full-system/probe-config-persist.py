#!/usr/bin/env python3
"""Export the original firmware's own Backup pair after a real subsystem sync.

Why this is not fabrication: the guest runs the original `Backup_sync_subsystem`
through the project helper, then the *original* filesystem bytes at
`/setting/Backup.bin` and `/setting/Backup.bak` leave the VM through the declared
export window (`card-export`, which only preads the guest's own file and memcpy's it
into a reserved region). The host then validates the BK4 records with
`backup-state.py` against the verified official ALLLANG PP.

`config_persistence_verified` stays false: this run only proves that the pair can be
taken out and parsed. Publishing it and re-reading it in a fresh VM is the next step.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import runpy
import shutil
import subprocess
import sys
import tempfile

HERE = Path(__file__).resolve().parent
DEFAULT_SUBSYSTEM = 0x2cf          # user settings, verified earlier by backup-sync tests
MTOOLS = ('mtools-arch-yRYM5W/extracted/usr/bin',)
OFFICIAL_PP_SHA = '3dab4f0d6b7790f4a7798034b57f43bfe3255c39dc6da2897fc288b3a218fe47'


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def verify_runtime(runtime):
    manifest = json.loads((runtime / 'analysis/full-system.json').read_text())
    checks = (('backup_sync_source_sha256', HERE / 'backup-sync.c'),
              ('backup_sync_program_sha256', runtime / 'analysis/root/simulation/backup-sync'),
              ('card_export_source_sha256', HERE / 'card-export.c'),
              ('card_export_program_sha256', runtime / 'analysis/root/simulation/card-export'))
    for key, path in checks:
        if not path.is_file():
            raise SystemExit(f'Rebuild the runtime: {path} is missing')
        if manifest.get(key) != sha256(path):
            raise SystemExit(f'Rebuild the runtime: {path} identity differs from the manifest')
    return manifest


def mtools_binary(name):
    for relative in MTOOLS:
        candidate = HERE / 'runtime/analysis' / relative / name
        if candidate.is_file():
            return candidate
    found = shutil.which(name)
    return Path(found) if found else None


def official_pp(runtime, explicit=None):
    """Extract the official ALLLANG PP from a pristine nflasha2 image.

    The runtime under test may already carry a published generation, so the
    reference is only taken from its own image when that image still holds the PP.
    """
    image = Path(explicit) if explicit else runtime / 'analysis/root/partitions/nflasha2.img'
    mcopy = mtools_binary('mcopy')
    if not image.is_file() or mcopy is None:
        return None, 'mtools or nflasha2 image unavailable'
    with tempfile.TemporaryDirectory() as directory:
        target = Path(directory) / 'Backup.bin'
        result = subprocess.run([str(mcopy), '-n', '-i', str(image), '::/BACKUP.BIN', str(target)],
                                capture_output=True, text=True,
                                env={**__import__('os').environ, 'MTOOLS_SKIP_CHECK': '1'})
        if result.returncode or not target.is_file():
            return None, 'extract failed: ' + (result.stderr or result.stdout)[:200]
        data = target.read_bytes()
        if hashlib.sha256(data).hexdigest() != OFFICIAL_PP_SHA:
            return None, 'that image does not hold the official ALLLANG PP'
        return data, None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--runtime', type=Path, required=True)
    parser.add_argument('--seconds', type=int, default=620)
    parser.add_argument('--sync-at', type=float, default=470)
    parser.add_argument('--export-at', type=float, default=540)
    parser.add_argument('--subsystem', type=lambda text: int(text, 0), default=DEFAULT_SUBSYSTEM)
    parser.add_argument('--adaptive', action='store_true',
                        help='let the runner recognise each screen and press the key that screen needs')
    parser.add_argument('--adaptive-interval', type=float, default=6.0)
    parser.add_argument('--adaptive-default-after', type=float, default=None)
    parser.add_argument('--adaptive-stop-screen', default=None)
    parser.add_argument('--adaptive-default', default=None,
                        help='key to press once on a screen the map does not know')
    parser.add_argument('--capture-frames', action='store_true',
                        help='dump periodic OSD frames, so a run with no injected keys can still be seen')
    parser.add_argument('--observe-panel-tick', action='store_true',
                        help='count executions of the panel tick at 0x20acae8')
    parser.add_argument('--observe-system-error', action='store_true',
                        help='attach the conditional MODEL_SYSTEM_ERROR probe, to see why a boot fails')
    parser.add_argument('--shift-after', default='',
                        help='TIME:SECONDS -- delay every walk entry later than TIME by SECONDS, so an '
                             'extra screen can be answered without losing the rest of the walk')
    parser.add_argument('--no-walk', action='store_true',
                        help='inject no keys at all: used to see what a stored configuration does '
                             'on its own, without first-setup keystrokes landing on a live screen')
    parser.add_argument('--walk-cutoff', type=float, default=None,
                        help='drop walk entries at or after this second, so a survey can stop in a '
                             'menu instead of pressing the walk\'s own ENTER')
    parser.add_argument('--extra-keys', default='',
                        help='comma-separated TIME:NAME presses injected after the walk, e.g. '
                             '"462.5:DOWN" -- used to drive a different menu item through the original UI')
    parser.add_argument('--no-sync', action='store_true',
                        help='skip the original sync, so a published configuration is read back untouched')
    parser.add_argument('--insmod-policy', default='media-rm')
    parser.add_argument('--reference-image', type=Path, default=None,
                        help='a pristine nflasha2 image that still holds the official PP; required '
                             'once the runtime under test carries a published generation')
    args = parser.parse_args()
    runtime = args.runtime.resolve(strict=True)
    manifest = verify_runtime(runtime)

    configure = runpy.run_path(str(HERE / 'run-camera.py'))['configuration']
    walk = runpy.run_path(str(HERE / 'start-official-camera.py'))['first_setup_plan']()
    plan = [] if args.no_walk else walk.split(';')
    if args.shift_after:
        boundary, _, amount = args.shift_after.partition(':')
        boundary, amount = float(boundary), float(amount)
        shifted = []
        for entry in plan:
            when, sep, command = entry.partition(':')
            try:
                value = float(when)
            except ValueError:
                shifted.append(entry)
                continue
            shifted.append(f'{value + amount if value > boundary else value:.1f}{sep}{command}')
        plan = shifted
    if args.walk_cutoff is not None:
        def when(entry):
            try:
                return float(entry.partition(':')[0])
            except ValueError:
                return 0.0
        kept = [entry for entry in plan if when(entry) < args.walk_cutoff]
        if not kept:
            parser.error('--walk-cutoff removed every walk entry')
        plan = kept
    if not args.no_sync:
        plan.append(f'{args.sync_at:.1f}:/simulation/backup-sync --subsystem {args.subsystem:#x}')
    codes = {'ENTER': 0x1ac, 'DOWN': 0x30, 'UP': 0x3, 'MENU': 0x1ab,
             'RIGHT': 0x1af, 'LEFT': 0x15, 'DELETE': 0x1f8,
             # raw 0x02 = UIBIZ_KEY_TACT_POWER in the body's raw->UIBIZ table
             'POWER': 0x2}
    for entry in [item for item in args.extra_keys.split(',') if item.strip()]:
        when, _, name = entry.partition(':')
        if name.strip() not in codes:
            parser.error('unknown key name in --extra-keys: ' + name)
        code = codes[name.strip()]
        at = float(when)
        plan.append(f'{at:.1f}:/simulation/inject-key 0x807a0020 0x92840747 {code:#x} 0 0x1 0x0 1 --pulse-ms 50')
        plan.append(f'{at + 0.5:.1f}:/simulation/inject-key 0x807a0020 0x92840747 {code:#x} 0 0x0 0x0 1')
    plan.sort(key=lambda item: float(item.partition(':')[0]))
    queue = Path(tempfile.mkdtemp(prefix='config-persist-', dir=runtime / 'analysis'))
    argv = configure(queue, args.seconds, True, official=True, key_plan=';'.join(plan))
    if '--insmod-policy' in argv:
        argv[argv.index('--insmod-policy') + 1] = args.insmod_policy
    else:
        argv += ['--insmod-policy', args.insmod_policy]
    argv += ['--config-export-at', str(args.export_at)]
    if args.observe_panel_tick:
        argv.append('--observe-panel-tick')
    if args.observe_system_error:
        argv.append('--observe-system-error-source')
    if args.capture_frames:
        argv.append('--capture-osd-frames')
    if args.adaptive:
        argv += ['--adaptive-first-setup', '--adaptive-interval', str(args.adaptive_interval)]
        if args.adaptive_default:
            argv += ['--adaptive-default', args.adaptive_default]
        if args.adaptive_default_after is not None:
            argv += ['--adaptive-default-after', str(args.adaptive_default_after)]
        if args.adaptive_stop_screen:
            argv += ['--adaptive-stop-screen', args.adaptive_stop_screen]
    command = [sys.executable, '-B', str(HERE / 'run-full-system.py'), '--runtime', str(runtime), *argv]
    run = None
    with (queue / 'runner.log').open('w') as output:
        process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        try:
            for line in process.stdout:
                output.write(line)
                output.flush()
                print(line, end='', flush=True)
                if line.startswith('FULLSYSTEM_RUN '):
                    run = Path(line.removeprefix('FULLSYSTEM_RUN ').strip())
            rc = process.wait()
        except BaseException:
            process.terminate()
            process.wait(timeout=30)
            raise
        finally:
            process.stdout.close()
    if run is None:
        raise SystemExit('no owned run; keep ' + str(queue / 'runner.log'))
    if run.parent.resolve() != (runtime / 'analysis/runs').resolve():
        raise ValueError('Foreign run path')

    console = (run / 'console.log').read_bytes()
    text = console.decode(errors='replace')
    vm_path = run / 'result.json'
    if not vm_path.is_file():
        failure = {'schema': 'config-persistence-run-failure-v1', 'run': str(run),
                   'returncode': rc, 'console_sha256': hashlib.sha256(console).hexdigest(),
                   'error': 'runner did not produce result.json; inspect the owned runner log',
                   'runner_log': str(queue / 'runner.log'),
                   'config_persistence_verified': False}
        (run / 'config-persistence-failure.json').write_text(json.dumps(failure, indent=2) + '\n')
        print('CONFIG_PERSISTENCE_FAILED', failure['error'], flush=True)
        return rc if rc else 1
    vm = json.loads(vm_path.read_text())
    export = vm.get('config_export') or {}
    verdict = {'schema': 'config-persistence-export-v1', 'run': str(run),
               'console_sha256': hashlib.sha256(console).hexdigest(), 'returncode': rc,
               'subsystem': None if args.no_sync else f'{args.subsystem:#x}',
               'sync_skipped': bool(args.no_sync),
               'extra_keys': args.extra_keys,
               'sync_receipts': re.findall(r'BACKUP_SYNC_(?:BEGIN|END)[^\r\n]{0,90}', text)[:6],
               'export_trigger': vm.get('config_export_trigger'),
               'export': export,
               'config_persistence_verified': False,
               'not_claimed': ['that the pair is published for the next VM',
                               'that a fresh VM reads back the same setting',
                               'that the reset entry exists'],
               'manifest_backup_sync': manifest.get('backup_sync_program_sha256'),
               }
    reference, why = official_pp(runtime, args.reference_image)
    state = runpy.run_path(str(HERE / 'backup-state.py'))
    results = []
    for item in export.get('files', []):
        path = run / item['name']
        record = {'name': item['name'], 'bytes': item['bytes'], 'sha256': item['sha256']}
        if not path.is_file():
            record['error'] = 'exported file is missing'
            results.append(record)
            continue
        data = path.read_bytes()
        if hashlib.sha256(data).hexdigest() != item['sha256']:
            record['error'] = 'exported bytes differ from the recorded digest'
            results.append(record)
            continue
        try:
            if reference is None:
                raise ValueError('no official reference: ' + str(why))
            parsed = state['validate'](data, reference)
            record['records'] = parsed['records']
            record['equals_official_pp'] = hashlib.sha256(data).hexdigest() == state['OFFICIAL_PP_SHA256']
            record['valid'] = True
        except ValueError as error:
            record['valid'] = False
            record['error'] = str(error)
        results.append(record)
    verdict['files'] = results
    verdict['export_verified'] = bool(export.get('verified')) and all(
        item.get('valid') for item in results) and bool(results)
    # A published generation lets this run prove the derived volume is what the VM reads.
    generation_path = runtime / 'analysis/config-generation.json'
    if generation_path.is_file():
        generation = json.loads(generation_path.read_text())
        expected = {name: item['sha256'] for name, item in generation.get('files', {}).items()}
        for item in results:
            remote = 'BACKUP.BIN' if item['name'] == 'Backup.bin' else 'BACKUP.BAK'
            item['matches_published'] = expected.get(remote) == item.get('sha256')
        verdict['generation'] = {
            'source_run': generation.get('source_run'),
            'parent_was_official_pp': generation.get('parent_was_official_pp'),
            'published': {name: item['sha256'] for name, item in generation.get('files', {}).items()},
            'all_match_published': bool(results) and all(
                item.get('matches_published') for item in results)}
        verdict['reload_verified'] = bool(verdict['export_verified']
                                          and verdict['generation']['all_match_published'])
    verdict['config_persistence_verified'] = False
    verdict['persistence_gap'] = ('byte-level reload only: no individual setting value has been '
                                  'round-tripped yet, so the application model is not shown to adopt it')
    (run / 'config-persistence.json').write_text(json.dumps(verdict, indent=2) + '\n')
    print('CONFIG_PERSISTENCE', run / 'config-persistence.json')
    for item in results:
        print('  ', item['name'], item['bytes'], 'valid=', item.get('valid'), item.get('error', ''))
    if rc:
        return rc
    return 0 if verdict['export_verified'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
