#!/usr/bin/env python3
"""User-visible config round trip through the standard launcher, two real sessions.

Session 1: official desktop session on a fresh workspace. Keys go through the same
owned input queue the Rust UI uses (press/release pairs, one at a time). The screen
is classified with the same screen map, so nothing depends on a fixed key count.
After the JPEG size row is reached, the editor gets exactly one DOWN (14M -> 8.2M)
and one ENTER, then MENU closes. The window is then closed (SIGTERM to the owned UI,
the same stop-input/save path as a user close), which saves the workspace generation.

Session 2 separately records whether first setup recurs. If it does, normal wizard
input can continue to the shooting view for a JPEG-only diagnostic; it cannot make
the direct-boot criterion pass. Frames require a separate visual value check.
"""
import hashlib
import argparse
import io
import json
import os
from pathlib import Path
import runpy
import re
import secrets
import select
import signal
import subprocess
import sys
import tempfile
import time

HERE = Path(__file__).resolve().parent
SCREENS = runpy.run_path(str(HERE / 'screen-map.py'))
KEY_CODES = runpy.run_path(str(HERE / 'start-official-camera.py'))['KEY_CODES']
SHARED = ['--cache-dir', str(HERE / 'runtime/bodydata/eb4943e6099754d64deaef5047942e9bfe258f232d0b7bc39fa23b3cd10e1e31'),
          '--factory-dir', str(HERE / 'runtime/factory-images/candidate-003')]
INJECT = '/simulation/inject-key 0x807a0020 0x92840747 {code:#x} 0 {status} 0x0 1'


def injection_receipt(raw, code):
    markers = re.findall(rb'MENU_DIAG_COMMAND_DONE_([0-9a-f]{24}):(\d+):END_([0-9a-f]{24})', raw)
    if not markers or len(set(markers)) != 1 or markers[0][0] != markers[0][2] or markers[0][1] != b'0':
        raise RuntimeError('missing or conflicting closed serial completion receipt')
    records = []
    for body in re.findall(rb'(?:^|\n)INJECT_KEY_SEND ([^\r\n]*)', raw):
        try:
            values = {key.decode(): int(value, 0) for key, value in
                      (item.split(b'=', 1) for item in body.split())}
        except (ValueError, UnicodeError):
            raise RuntimeError('malformed original input receipt')
        records.append(values)
    common = dict(queue=0x807a0020, src=0x92840747, key_code=code, sub=0, ex=0, **{'from': 1}, result=0)
    if records != [{**common, 'status': 1}, {**common, 'status': 0}]:
        raise RuntimeError('original press/release receipts differ from requested pulse')


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def start_display(out, env):
    read_fd, write_fd = os.pipe()
    with (out / 'xvfb.log').open('wb') as log:
        server = subprocess.Popen(['Xvfb', '-screen', '0', '1600x1000x24', '-nolisten', 'tcp',
                                   '-displayfd', str(write_fd)], pass_fds=(write_fd,), stdout=log, stderr=log)
    os.close(write_fd)
    try:
        if not select.select([read_fd], [], [], 10)[0]:
            raise TimeoutError('owned Xvfb display')
        number = os.read(read_fd, 32).decode().strip()
        if not number.isdigit():
            raise RuntimeError('Xvfb did not return an owned display')
    except BaseException:
        server.terminate()
        try:
            server.wait(timeout=5)
        except subprocess.TimeoutExpired:
            server.kill()
            server.wait(timeout=5)
        raise
    finally:
        os.close(read_fd)
    env['DISPLAY'] = ':' + number
    return server


class Session:
    def __init__(self, workspace, out, env, name, attach_sd=False):
        self.workspace, self.out, self.env, self.name = workspace, out, env, name
        self.run = None
        self.ui_pid = None
        self.queue = None
        self.request = 0
        self.proc = None
        self.prefix = 'roundtrip-' + secrets.token_hex(8)
        self.saved_frames = set()
        self.last_observation = None
        self.attach_sd = attach_sd

    def launch(self):
        with (self.out / f'{self.name}.log').open('wb') as log:
            self.proc = subprocess.Popen(
                [sys.executable, '-B', str(HERE / 'start-official-camera.py'), '--workspace', str(self.workspace),
                 *SHARED, '--seconds', '420', *(['--attach-sd'] if self.attach_sd else [])],
                env=self.env, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
        return self

    def log_text(self):
        return (self.out / f'{self.name}.log').read_text(errors='replace')

    def wait_markers(self, timeout):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.proc.poll() is not None:
                raise RuntimeError(f'{self.name} launcher ended early rc={self.proc.returncode}')
            text = self.log_text()
            for line in text.splitlines():
                if line.startswith('CAMERA_UI_SESSION ') and self.ui_pid is None:
                    session = json.loads(line.split(' ', 1)[1])
                    run = Path(session['run']).resolve(strict=True)
                    if not run.is_relative_to((self.workspace / '.a7c2/sessions').resolve(strict=True)):
                        raise RuntimeError('launcher returned a foreign run')
                    recorded = json.loads((run / 'camera-ui-session.json').read_text())
                    if recorded != session or session.get('asset_source') != 'official-bodydata-derived':
                        raise RuntimeError('UI session does not match its owned run record')
                    self.ui_pid = session['ui_pid']
                    self.queue = Path(session['input_dir'])
                    info = self.queue.lstat()
                    if self.queue.is_symlink() or info.st_uid != os.getuid() or info.st_mode & 0o077:
                        raise RuntimeError('input queue is not a private owned directory')
                    self.run = run
            if self.ui_pid is not None:
                return
            time.sleep(.3)
        raise TimeoutError(f'{self.name} owned UI session')

    def frame(self):
        from PIL import Image, UnidentifiedImageError
        path = self.run / 'live-frame.ppm'
        try:
            before = path.stat()
            data = path.read_bytes()
            after = path.stat()
            if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
                return None
            image = Image.open(io.BytesIO(data))
            image.load()
            if image.size != (640, 480):
                return None
        except (OSError, ValueError, UnidentifiedImageError):
            return None
        digest = hashlib.sha256(data).hexdigest()
        target = self.out / f'{self.name}-frame-{digest}.ppm'
        if not target.exists():
            if len(self.saved_frames) >= 64:
                raise RuntimeError('frame evidence exceeded 64 distinct images for this session')
            with target.open('xb') as stream:
                stream.write(data)
            self.saved_frames.add(target)
        return target

    def screen(self):
        frame = self.frame()
        if frame is None:
            self.last_observation = None
            return None, None
        name, distance = SCREENS['classify'](frame)
        self.last_observation = {'screen': name, 'distance': distance, 'frame': str(frame)}
        return name, distance

    def press(self, name, settle=.9):
        code = KEY_CODES[name]
        tag = f'{self.prefix}-{self.request:03d}'
        self.request += 1
        response = self.queue / (tag + '.out')
        if response.exists():
            raise RuntimeError('input response already exists before request')
        temporary = self.queue / (tag + '.next')
        with temporary.open('xb') as stream:
            stream.write((INJECT.format(code=code, status='0x1') + ' --pulse-ms 50').encode('ascii'))
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(self.queue / (tag + '.cmd'))
        deadline = time.monotonic() + 25
        while time.monotonic() < deadline:
            if response.exists():
                raw = response.read_bytes()
                (self.out / f'{self.name}-input-{self.request:03d}.out').write_bytes(raw)
                injection_receipt(raw, code)
                break
            if self.proc is not None and self.proc.poll() is not None:
                raise RuntimeError('owned session exited before the input receipt')
            time.sleep(.1)
        else:
            raise TimeoutError(f'no guest receipt for {name}')
        # The guest pulse already released the key, as checked above.
        time.sleep(settle)

    def stop_owned_ui(self):
        if self.ui_pid is not None and self.run is not None and self.queue is not None:
            command = Path(f'/proc/{self.ui_pid}/cmdline')
            if command.exists():
                args = command.read_bytes().split(b'\0')
                if args == [b'']:
                    return False  # Already exited/zombie: never signal a reused PID.
                if os.fsencode(str(self.queue)) not in args or os.fsencode(str(self.run / 'live-frame.ppm')) not in args:
                    raise RuntimeError('UI PID no longer names this owned session')
                try:
                    os.kill(self.ui_pid, signal.SIGTERM)
                except ProcessLookupError:
                    return False
                return True
        return False

    def close(self):
        self.stop_owned_ui()
        if self.proc.poll() is not None:
            if self.proc.returncode:
                raise RuntimeError(f'{self.name} rc={self.proc.returncode}')
            return
        self.proc.wait(timeout=300)
        if self.proc.returncode != 0:
            raise RuntimeError(f'{self.name} rc={self.proc.returncode}')

    def cleanup(self):
        stopped = self.stop_owned_ui()
        if self.proc is None or self.proc.poll() is not None:
            return {'already_exited': True, **({'orphan_ui_termination_requested': True} if stopped else {})}
        try:
            self.close()
            return {'closed_and_reaped': True}
        except Exception as error:
            if self.proc.poll() is None:
                # launch() created this exact session/process group.
                os.killpg(self.proc.pid, signal.SIGINT)
                try:
                    self.proc.wait(timeout=45)
                except subprocess.TimeoutExpired:
                    os.killpg(self.proc.pid, signal.SIGTERM)
                    self.proc.wait(timeout=10)
            return {'close_error': str(error), 'returncode': self.proc.returncode}


def drive_first_setup(session, record, timeout=180):
    """Only named, visually checked setup pages receive keys; unknown frames wait."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        name, distance = session.screen()
        if name == 'shooting':
            record['first_setup_seconds'] = round(timeout - (deadline - time.monotonic()), 1)
            return
        keys = SCREENS['keys_for'](name) if name else None
        key = SCREENS['key_for'](name) if name else None
        record['first_setup_seen'] = record.get('first_setup_seen', []) + [name]
        if keys:
            for item in keys:
                session.press(item)
        elif key:
            session.press(key)
        elif name is None:
            time.sleep(2)
        else:
            raise RuntimeError('recognised screen has no defined action: ' + str(name))
    raise TimeoutError('first setup did not reach the shooting screen')


def change_jpeg_size(session, record):
    session.press('MENU')
    deadline = time.monotonic() + 60
    for expected in ('menu_shutter_speed', 'menu_format', 'menu_jpeg_size'):
        found = None
        while time.monotonic() < deadline:
            name, _ = session.screen()
            if name == expected:
                found = name
                break
            time.sleep(.8)
        record.setdefault('menu_seen', []).append(found)
        if found is None:
            raise TimeoutError('menu row not recognised: ' + expected)
        session.press('DOWN' if expected != 'menu_jpeg_size' else 'ENTER')
    # Editor: 33M / 14M(current) / 8.2M — exactly one DOWN then ENTER (run-ps34e5bz path).
    session.press('DOWN', settle=1.2)
    session.press('ENTER', settle=1.2)
    session.press('MENU')
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        if session.screen()[0] == 'shooting':
            break
        time.sleep(.2)
    else:
        raise TimeoutError('JPEG editor did not return to a fresh shooting frame')
    record['setting_change'] = 'JPEG size one row down from 14M to 8.2M via recognised menu rows'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--resume-result', type=Path,
                        help='seed a fresh diagnostic workspace from a preserved first-session export; never marks full acceptance')
    parser.add_argument('--attach-sd', action='store_true', help='also exercise real card save and directory restoration')
    args = parser.parse_args()
    out = Path(tempfile.mkdtemp(prefix='config-value-roundtrip-', dir=HERE / 'runtime/analysis'))
    workspace = out / 'workspace'
    workspace.mkdir()
    if args.attach_sd:
        (workspace / 'SD').mkdir()
        (workspace / 'SD/CONFIG-CYCLE.TXT').write_bytes(b'owned SD configuration-cycle canary\n')
    source_result = None
    previous = None
    if args.resume_result:
        source_result = args.resume_result.resolve(strict=True)
        previous = json.loads(source_result.read_text())
        if previous.get('scope') != 'user-visible JPEG size round trip through the standard launcher':
            raise ValueError('resume requires the original failed roundtrip report')
        source_workspace = Path(previous['workspace']).resolve(strict=True)
        if not source_workspace.is_relative_to((HERE / 'runtime/analysis').resolve(strict=True)):
            raise ValueError('diagnostic resume is limited to owned local experiments')
        original = source_result.parent / 'session1-before-close.ppm'
        if sha(original) != previous.get('session1_frame_sha256'):
            raise ValueError('first-session frame differs from the preserved evidence')
    env = {**os.environ, 'WINIT_X11_SCALE_FACTOR': '1', 'LIBGL_ALWAYS_SOFTWARE': '1'}
    env.pop('WAYLAND_DISPLAY', None)
    record = {'scope': 'user-visible JPEG size round trip through the standard launcher',
              'verified': False, 'workspace': str(workspace), 'output': str(out)}
    if previous:
        record['scope'] = 'diagnostic recheck of the loaded session of a failed roundtrip'
        record['source_result'] = {'path': str(source_result), 'sha256': sha(source_result)}
    sources = ['run-camera.py', 'start-official-camera.py', 'workspace-config.py',
               'run-full-system.py', 'screen-map.py', 'screens.json', 'check-config-value-roundtrip.py',
               'save-evidence.py', 'sd-directory.py', 'sd_flush_barrier.py']
    before = {n: sha(HERE / n) for n in sources}
    server = None
    sessions = []
    try:
        server = start_display(out, env)
        saved_frame = out / 'session1-before-close.ppm'
        if previous:
            saved_frame.write_bytes(original.read_bytes())
            markers = [json.loads(line.split(' ', 1)[1])
                       for line in (source_result.parent / 'session1.log').read_text(errors='replace').splitlines()
                       if line.startswith('CAMERA_UI_SESSION ')]
            if len(markers) != 1:
                raise ValueError('ambiguous original first-session ownership record')
            first_run = Path(markers[0]['run']).resolve(strict=True)
            if not first_run.is_relative_to(source_workspace / '.a7c2/sessions'):
                raise ValueError('first export is outside the recorded source workspace')
            api = runpy.run_path(str(HERE / 'workspace-config.py'))
            reference = api['official_reference'](first_run.parent.parent.parent)
            with api['locked'](source_workspace) as source_store:
                original_generation = source_store.generation(previous['saved_generation'], reference)
            with api['locked'](workspace) as store:
                seeded = store.save_run(first_run, reference)
                copied_generation = store.current(reference)
            if copied_generation['files'] != original_generation['files']:
                raise ValueError('source export no longer matches the preserved generation bytes')
            record['saved_generation'] = seeded['generation']
            record['source_generation'] = previous['saved_generation']
            record['seeded_from_original_run'] = str(first_run)
            record['source_workspace_unchanged_by_diagnostic'] = str(source_workspace)
        else:
            first = Session(workspace, out, env, 'session1', args.attach_sd)
            sessions.append(first)
            first.launch()
            first.wait_markers(300)
            drive_first_setup(first, record)
            change_jpeg_size(first, record)
            frame = first.frame()
            if frame is None:
                raise RuntimeError('first-session frame was not stable')
            saved_frame.write_bytes(frame.read_bytes())
            first.close()
            record['session1_rc'] = 0
            saved = [l.split(' ', 1)[1] for l in first.log_text().splitlines() if l.startswith('WORKSPACE_CONFIG_SAVED ')]
            record['saved_generation'] = saved[-1] if saved else None
        record['session1_frame_sha256'] = sha(saved_frame)
        if not record['saved_generation']:
            raise RuntimeError('session 1 did not save a workspace generation')

        second = Session(workspace, out, env, 'session2', args.attach_sd)
        sessions.append(second)
        second.launch()
        second.wait_markers(300)
        runtime = second.run.parent.parent.parent
        loaded = json.loads((runtime.parent / 'config-load.json').read_text())['generation']
        if loaded != record['saved_generation']:
            raise RuntimeError('new session did not load the specific saved generation')
        record['loaded_generation'] = loaded
        deadline = time.monotonic() + 240
        record['first_setup_recurred'] = False
        while time.monotonic() < deadline:
            name, _ = second.screen()
            if name == 'shooting':
                break
            if name == 'system_error':
                raise RuntimeError('reloaded session entered the original system-error screen')
            if name in ('language', 'accessibility', 'privacy_notice', 'creators_app', 'area_datetime_prompt'):
                record['first_setup_recurred'] = True
                record['repeated_setup_first_frame'] = second.last_observation
                drive_first_setup(second, record.setdefault('second_session_setup', {}))
                break
            time.sleep(2)
        else:
            raise TimeoutError('session 2 did not reach the shooting screen')
        record['direct_boot_verified'] = not record['first_setup_recurred']
        record['session2_boot'] = ('normal wizard input was required; no JPEG menu commands in second session'
                                   if record['first_setup_recurred'] else 'direct shooting view')
        if args.attach_sd:
            mount = re.compile(rb'FILE_MEDIA_FSYS op=Mount path=/nondev/rm2 flags=0x300 drive=\d+ result=0')
            deadline = time.monotonic() + 45
            while time.monotonic() < deadline:
                if mount.search((second.run / 'console.log').read_bytes()):
                    record['original_card_mount_verified'] = True
                    break
                time.sleep(.2)
            else:
                raise TimeoutError('original card mount did not complete before close')
        frame2 = second.frame()
        if frame2 is None:
            raise RuntimeError('reloaded shooting frame was not stable')
        target = out / 'session2-shooting.ppm'
        target.write_bytes(frame2.read_bytes())
        record['session2_frame'] = str(target)
        record['session2_frame_sha256'] = sha(target)
        from PIL import Image
        image = Image.open(target).convert('RGB')
        image.save(out / 'session2-shooting.png')
        Image.open(saved_frame).save(out / 'session1-before-close.png')
        second.close()
        record['session2_rc'] = 0
        saved_again = [l.split(' ', 1)[1] for l in second.log_text().splitlines() if l.startswith('WORKSPACE_CONFIG_SAVED ')]
        if not saved_again:
            raise RuntimeError('reloaded session did not save successfully on close')
        record['session2_saved_generation'] = saved_again[-1]
        if args.attach_sd:
            sd = json.loads((second.run / 'sd-directory-sync.json').read_text())
            receipt = runpy.run_path(str(HERE / 'save-evidence.py'))['load_card_receipt'](second.run)
            if (workspace / 'SD/CONFIG-CYCLE.TXT').read_bytes() != b'owned SD configuration-cycle canary\n':
                raise RuntimeError('original SD canary changed during combined save')
            if sd['image_sha256'] != receipt['card_image_sha256']:
                raise RuntimeError('SD directory restoration did not use the verified snapshot')
            record['combined_sd_config_save_observed'] = True
            record['sd_image_sha256'] = receipt['card_image_sha256']
            record['sd_scope'] = 'original mount/flush/snapshot/recovery and existing canary; not photo capture'
        record['source_unchanged'] = before == {n: sha(HERE / n) for n in sources}
        if not record['source_unchanged']:
            raise AssertionError('launcher sources changed during the experiment')
        record.update(observation_completed=True, value_visual_review_pending=True,
                      value_roundtrip_verified=False,
                      value_check='first/second raw frames require separate visual checks; lit pixels are not a value check',
                      limits=['SIGTERM closes the owned UI; the runner stop/save path is the same as a window close',
                              'one setting only (JPEG size); not a claim that every setting persists',
                              'workspace reset entry not yet implemented'])
        if record['first_setup_recurred'] and not previous:
            raise RuntimeError('frames captured, but the no-repeated-setup criterion still failed')
    except BaseException as error:
        record['error'] = repr(error)
        raise
    finally:
        cleanup = []
        for session in reversed(sessions):
            try:
                cleanup.append({'session': session.name, 'launcher_pid': session.proc.pid if session.proc else None,
                                **session.cleanup()})
            except Exception as error:
                cleanup.append({'session': session.name, 'cleanup_error': str(error)})
        record['cleanup'] = cleanup
        if server is not None and server.poll() is None:
            server.terminate()
            try:
                server.wait(timeout=5)
            except subprocess.TimeoutExpired:
                server.kill()
                server.wait(timeout=5)
        record['source_before'] = before
        record['source_after'] = {n: sha(HERE / n) for n in sources}
        (out / 'result.json').write_text(json.dumps(record, ensure_ascii=False, indent=2) + '\n')
        print('CONFIG_VALUE_ROUNDTRIP', out, flush=True)


if __name__ == '__main__':
    main()
