#!/usr/bin/env python3
"""Start the explicitly bound retained source once, attach the existing Rust GUI.

The base context/sequence capability is read-only. Hot stays unavailable unless
main supplies a reviewed, real closed live-result binding with current sources.
"""
import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import runpy
import stat
import subprocess
import sys
import time

HERE = Path(__file__).resolve().parent
LIVE = runpy.run_path(str(HERE / 'retained-camera-live.py'))
DEV, R = LIVE['DEV'], LIVE['R']


def gui_context(base, owner, validation=None):
    context = copy.deepcopy(base)
    instance = DEV['bind_instance'](base)
    sequence = DEV['sequence_capability'](base, instance)
    caps = context.setdefault('available_capabilities', {})
    caps['hot'] = dict(available=False, contract=DEV['SCHEMA'], instance_identity=instance,
                       blocked_reason='Explicit reviewed actual closed live result required; GUI switch unverified')
    if validation is not None:
        caps['hot'] = dict(available=True, contract=DEV['SCHEMA'], instance_identity=instance,
                           retained_audit=copy.deepcopy(sequence['retained_audit']),
                           backend_source=LIVE['binding'](HERE / 'retained-camera-live.py'),
                           live_owner=owner, live_validation=validation)
        DEV['hot_capability'](context, instance)
    return context


def gui_environment(context_path):
    # Do not inherit another instance's reset, USB or configuration targets.
    env = {key: value for key, value in os.environ.items() if not key.startswith('CAMUI_')}
    env.update(CAMUI_FIRMWARE_CONTEXT=str(context_path), CAMUI_FIRMWARE_BACKEND=str(HERE / 'firmware-development.py'),
               CAMUI_FIRMWARE_PYTHON=sys.executable)
    return env


def wait_ready(daemon, directory, instance, timeout=240):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if daemon.poll() is not None:
            raise RuntimeError('Source controller exited before ready; inspect owner.log and owner/failure.json')
        descriptor, ready = directory / 'live-owner.json', directory / 'source-ready.json'
        # serve prints only after descriptor fsync and socket listen. File existence alone can race both.
        log = directory.parent / 'owner.log'
        publications = []
        if log.exists():
            fd = os.open(DEV['path_checked'](log, private=True), os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
            try:
                raw = os.read(fd, LIVE['WIRE_LIMIT'] + 1)
                LIVE['check'](len(raw) <= LIVE['WIRE_LIMIT'], 'Controller publication exceeds budget')
            finally:
                os.close(fd)
            for line in raw.splitlines(keepends=True):
                if not line.endswith(b'\n'):
                    continue
                try:
                    value = json.loads(line, object_pairs_hook=DEV['_pairs'])
                except json.JSONDecodeError:
                    continue
                if type(value) is dict and value.get('schema') == LIVE['SCHEMA'] and value.get('status') == 'source-running':
                    publications.append(value)
        LIVE['check'](len(publications) <= 1, 'Duplicate source-ready publication')
        if publications and descriptor.exists() and ready.exists():
            row = publications[0]['owner']  # Pin the one published binding; never rediscover after refusal.
            LIVE['check'](row.get('path') == str(descriptor), 'Foreign source owner publication')
            info = LIVE['inspect_owner'](row, instance)
            source = DEV['read_json'](ready)
            LIVE['check'](info['controller_identity'] == LIVE['process'](daemon.pid) == source['controller_identity'] and
                          source['instance_identity'] == instance and source['state'] == 'source-running',
                          'Source-ready/controller binding differs')
            return row, info
        time.sleep(.05)
    raise TimeoutError('Source not ready; controller/lease preserved without signals')


def close_owned(daemon, owner, instance, output):
    if daemon.poll() is not None:
        R['save'](output / 'controller-ended.json', dict(controller_pid=daemon.pid, returncode=daemon.returncode,
                    reason='Owner already ended; no stale endpoint request', **LIVE['LIMITS']))
        return daemon.returncode
    try:
        response = LIVE['request'](owner, instance, 'close')
        R['save'](output / 'close-response.json', response)
    except Exception as error:
        state = error.state if isinstance(error, LIVE['LiveRequestRefused']) else None
        R['save'](output / 'owner-preserved.json', dict(controller_pid=daemon.pid, live_owner=owner,
                    error=type(error).__name__ + ': ' + str(error), live_state=state,
                    owner_retained=bool(state['live_owner_pids']) if state is not None else None,
                    lease_retained_until_owner_exit=True, **LIVE['LIMITS']))
        raise
    return daemon.wait()  # Only after typed normal close; no signal or timeout release.


def run(args):
    context_path = DEV['path_checked'](args.context, private=True)
    base = DEV['load_context'](context_path)
    instance = DEV['bind_instance'](base)
    DEV['sequence_capability'](base, instance)
    ui = args.ui.resolve(strict=True)
    info = ui.stat()
    LIVE['check'](stat.S_ISREG(info.st_mode) and info.st_uid == os.geteuid() and os.access(ui, os.X_OK),
                  'An existing owned executable Rust UI is required; no build is performed')
    with ui.open('rb') as stream:
        ui_sha = hashlib.file_digest(stream, 'sha256').hexdigest()
    output = Path(os.path.abspath(args.output))
    LIVE['check'](not os.path.lexists(output), 'Runner output must be a new private directory')
    DEV['path_checked'](output.parent, directory=True)
    for asset in (Path(base['runtime']), Path(base['workspace']), Path(instance['disk']).parent):
        LIVE['check'](not output.is_relative_to(asset) and not asset.is_relative_to(output), 'Runner output overlaps source assets')
    output.mkdir(mode=0o700)
    validation = None
    if args.live_validation is not None:
        validation = dict(path=str(args.live_validation.absolute()), sha256=args.live_validation_sha256)
        DEV['checked_binding'](validation, private=True)
    owner = None
    daemon = None
    ui_process = None
    try:
        log_fd = os.open(output / 'owner.log', os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(log_fd, 'wb', buffering=0) as log:
            daemon = subprocess.Popen([sys.executable, '-B', str(HERE / 'retained-camera-live.py'), 'serve',
                        '--context', str(context_path), '--output', str(output / 'owner'), '--frontend'],
                        stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT)
        owner, descriptor = wait_ready(daemon, output / 'owner', instance)
        context = gui_context(base, owner, validation)
        new_context = output / 'gui-context.json'
        DEV['write_json'](new_context, context)
        R['save'](output / 'gui-session.json', dict(live_owner=owner, controller_identity=descriptor['controller_identity'],
                    base_context=LIVE['binding'](context_path), gui_context=LIVE['binding'](new_context), ui=str(ui),
                    ui_sha256=ui_sha, panel_hot_is_transaction_then_close=True, **LIVE['LIMITS']))
        LIVE['check'](DEV['_identity'](ui.stat()) == DEV['_identity'](info), 'Rust UI changed before launch')
        ui_process = subprocess.Popen([str(ui), '--live', str(output / 'owner/frontend/live-frame.ppm'),
                        '--input-dir', str(output / 'owner/frontend/input'), '--managed-close-on-eof'],
                        env=gui_environment(new_context), stdin=subprocess.PIPE, umask=0o077)
        print('RETAINED_CAMERA_GUI ' + json.dumps(dict(output=str(output), live_owner=owner,
                    gui_context=str(new_context), hot_available=context['available_capabilities']['hot']['available'],
                    **LIVE['LIMITS'])), flush=True)
        ended = False
        while ui_process.poll() is None:
            if not ended and daemon.poll() is not None:
                print('OWNER_ENDED: original LCD producer stopped; GUI live channel becomes stale.', flush=True)
                ended = True
            time.sleep(.1)
        ui_process.stdin.close()
        rc = close_owned(daemon, owner, instance, output)
        return rc or ui_process.returncode
    except BaseException as error:
        # EOF asks only our dedicated GUI to close. A live VM/controller is never signalled.
        if ui_process is not None and ui_process.stdin is not None:
            ui_process.stdin.close()
        R['save'](output / 'runner-error.json', dict(error=type(error).__name__ + ': ' + str(error), live_owner=owner,
                    controller_pid=daemon.pid if daemon is not None else None,
                    controller_alive=daemon.poll() is None if daemon is not None else False,
                    owner_retained=None, lease_retained_until_owner_exit=True, **LIVE['LIMITS']))
        raise


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--context', type=Path, required=True, help='explicit existing 0600 base context with sequence capability')
    parser.add_argument('--output', type=Path, required=True, help='new private runner output outside instance/runtime/workspace')
    parser.add_argument('--ui', type=Path, default=HERE / 'camera-ui-rs/target/release/camera-ui-rs')
    parser.add_argument('--live-validation', type=Path, help='main-reviewed previous actual closed live result; no discovery')
    parser.add_argument('--live-validation-sha256')
    args = parser.parse_args(argv)
    if (args.live_validation is None) != (args.live_validation_sha256 is None):
        parser.error('--live-validation and --live-validation-sha256 are required together')
    return run(args)


if __name__ == '__main__':
    raise SystemExit(main())
