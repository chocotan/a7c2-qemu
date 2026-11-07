#!/usr/bin/env python3
"""Serialized LCD/input transport for the live owner's existing QMP and stdin.

The .out receipt confirms only original inject-key delivery, never AP behavior.
No socket, process, QMP connection, guest path or shell command is supplied by UI.
"""
from contextlib import contextmanager
import os
from pathlib import Path
import re
import runpy
import secrets
import stat
import struct
import time

HERE = Path(__file__).resolve().parent
INPUT = runpy.run_path(str(HERE / 'low-latency-input.py'))
LIMITS = dict(gui_owner_switch_verified=False, ui_hot_enabled=False, full_boot_verified=False,
              physical_devices_used=False, capture_verified=False, capture_actual_verified=False)


def check(value, message):
    if not value:
        raise ValueError(message)


def atomic_bytes(directory, name, raw):
    temporary = name + '.new-' + secrets.token_hex(12)
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=directory)
    try:
        with os.fdopen(fd, 'wb') as out:
            out.write(raw)
            out.flush()
        os.replace(temporary, name, src_dir_fd=directory, dst_dir_fd=directory)
    finally:
        try:
            os.unlink(temporary, dir_fd=directory)
        except FileNotFoundError:
            pass


class Frontend:
    def __init__(self, session, helpers, development):
        self.session, self.r, self.dev = session, helpers, development
        self.output = session.output / 'frontend'
        self.output.mkdir(mode=0o700)
        self.input_dir = self.output / 'input'
        self.input_dir.mkdir(mode=0o700)
        self.frame = self.output / 'live-frame.ppm'
        self.fd = os.open(self.input_dir, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        self.frame_fd = os.open(self.output, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        self.directory_identity = self.dev['_identity'](os.fstat(self.fd))[:2]
        self.paused = self.inflight = False
        self.fault = ''
        self.admit_after_ns = time.time_ns()
        self.next_frame = 0
        self.last_status = None
        self.status('source-ready')

    def dispose(self):
        for name in ('fd', 'frame_fd'):
            fd = getattr(self, name)
            if fd is not None:
                os.close(fd)
                setattr(self, name, None)

    def status(self, phase, **fields):
        row = dict(phase=phase, frame=str(self.frame), input_dir=str(self.input_dir),
                   state=self.session.state(), error=self.fault, **fields, **LIMITS)
        if row != self.last_status:
            self.dev['write_json'](self.output / 'status.json', row)
            self.last_status = row

    def entries(self):
        self.dev['path_checked'](self.input_dir, directory=True, private=True)
        check(self.dev['_identity'](self.input_dir.stat())[:2] == self.directory_identity,
              'Frontend input directory inode changed')
        return sorted(name for name in os.listdir(self.fd) if name.endswith('.cmd'))

    def reply(self, name, info, text):
        current = os.stat(name, dir_fd=self.fd, follow_symlinks=False)
        check(self.dev['_identity'](current) == self.dev['_identity'](info), 'Input changed before receipt')
        output = name[:-4] + '.out'
        try:
            os.stat(output, dir_fd=self.fd, follow_symlinks=False)
        except FileNotFoundError:
            pass
        else:
            raise ValueError('Input receipt already exists; refusing replay')
        atomic_bytes(self.fd, output, text.encode('utf-8'))
        check(self.dev['_identity'](os.stat(name, dir_fd=self.fd, follow_symlinks=False)) ==
              self.dev['_identity'](info), 'Input changed before unlink')
        os.unlink(name, dir_fd=self.fd)

    def reject_queued(self, reason):
        for name in self.entries():
            info = os.stat(name, dir_fd=self.fd, follow_symlinks=False)
            self.reply(name, info, 'RETAINED_GUI_INPUT_REFUSED: ' + reason + '\n')

    @contextmanager
    def transition(self, action):
        if action == 'hot':
            check(not self.session.used and not self.session.closed, 'This test-session permits exactly one hot request')
            check(not self.inflight, 'Guest input release is still uncertain')
            check(not self.fault, 'Frontend is blocked: ' + self.fault)
        self.paused = True
        try:
            self.status(action + '-busy')
            self.reject_queued(action + ' boundary; queued input was not executed')
            yield
        except BaseException as error:
            self.fault = type(error).__name__ + ': ' + str(error)
            raise
        finally:
            try:
                self.reject_queued(action + ' boundary; input queued during transition was not executed')
                self.admit_after_ns = time.time_ns()  # Also rejects a .tmp renamed after hot returns.
                self.next_frame = 0
                self.status('ended' if self.session.closed else 'blocked' if self.fault else 'target-ready')
            finally:
                self.paused = False

    def current(self):
        check(not self.paused and not self.fault and not self.session.closed, 'Frontend unavailable')
        execution = self.session.execution
        target = execution.target
        if target is not None:
            check(self.session.content is not None and execution.continued and not execution.failed,
                  'Target restore/continuation is not verified')
            owner, qmp = target, execution.target_qmp
            directory = self.session.tx._output / 'target'
            log, side = directory / 'console.log', 'target'
        else:
            check(not self.session.used, 'Hot failed; source input must stay blocked')
            owner, qmp = self.session.owner, self.session.qmp
            directory = Path(self.session.launch['dtb']).parent
            log, side = self.session.log, 'source'
        check(owner is not None and owner.poll() is None and qmp is not None, 'Current original owner is not live')
        check(self.session.state()['live_owner_pids'] == [owner.pid], 'Unknown additional live owner')
        return owner, qmp, directory, log, side

    def read_command(self, name, info):
        check(re.fullmatch(r'[A-Za-z0-9_-]{1,120}\.cmd', name), 'Invalid GUI command filename')
        check(stat.S_ISREG(info.st_mode) and info.st_uid == os.geteuid() and info.st_nlink == 1 and
              0 < info.st_size <= 4096, 'Expected an owned bounded single-link regular command')
        fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=self.fd)
        try:
            check(self.dev['_identity'](os.fstat(fd)) == self.dev['_identity'](info), 'Input inode changed')
            raw = os.read(fd, 4097)
            check(len(raw) == info.st_size and self.dev['_identity'](os.fstat(fd)) == self.dev['_identity'](info),
                  'Input changed during read')
        finally:
            os.close(fd)
        command = raw.decode('ascii')
        body = INPUT['parse_command'](command)
        check(body is not None, 'Unknown GUI command; no shell fallback')
        op, code, _, _ = struct.unpack('<4I', body[:16])
        check(op in (2, 5) or (op == 1 and code not in INPUT['CONTACTS']),
              'A contact requires its complete 50ms press/release pair')
        return command.strip(), {1: 1, 2: 2, 5: 4}[op]

    def input(self, owner, log):
        names = self.entries()
        if not names:
            return
        name = names[0]
        info = os.stat(name, dir_fd=self.fd, follow_symlinks=False)
        try:
            check(info.st_mtime_ns > self.admit_after_ns, 'Input predates the current owner admission boundary')
            command, count = self.read_command(name, info)
        except (ValueError, UnicodeError) as error:
            self.reply(name, info, 'RETAINED_GUI_INPUT_REFUSED: ' + str(error) + '\n')
            return
        self.inflight = True
        token, phase = secrets.token_hex(16), 'gui'
        completion = 'MENU_DIAG_COMMAND_DONE_' + token
        script = '(' + command + '\n)\na7c2_gui_rc=$?\necho \'' + completion + ':\'"$a7c2_gui_rc"\n'
        script += "echo 'RETAINED_DONE_" + phase + '=' + token + "'\n"
        try:
            text = self.r['shell'](owner, log, script, phase, token)
            lines = text.splitlines()
            sent = [line for line in lines if line.startswith('INJECT_KEY_SEND ')]
            check([line for line in lines if line.startswith(completion + ':')] == [completion + ':0'] and
                  len(sent) == count and all(line.endswith('result=0') for line in sent),
                  'Original inject-key delivery/release failed or is uncertain')
            # Only original send output and an actually observed zero-status marker reach the UI.
            self.reply(name, info, text)
            self.inflight = False
        except BaseException as error:
            self.reply(name, info, 'RETAINED_GUI_INPUT_UNCERTAIN: ' + type(error).__name__ + ': ' + str(error) + '\n')
            raise

    def snapshot(self, qmp, directory):
        path = directory / 'gui-frame.next.ppm'
        path.unlink(missing_ok=True)
        qmp('screendump', dict(filename='/out/gui-frame.next.ppm'))
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        try:
            before = os.fstat(fd)
            check(stat.S_ISREG(before.st_mode) and before.st_uid == os.geteuid() and before.st_nlink == 1 and
                  before.st_size <= self.r['LCD']['PIXEL_BYTES'] + 64, 'Invalid original QMP frame')
            raw = os.read(fd, self.r['LCD']['PIXEL_BYTES'] + 65)
            check(self.dev['_identity'](before) == self.dev['_identity'](os.fstat(fd)) ==
                  self.dev['_identity'](path.lstat()), 'Original QMP frame changed during read')
        finally:
            os.close(fd)
        pixels = self.r['LCD']['decode_ppm'](raw)
        atomic_bytes(self.frame_fd, self.frame.name, raw)
        return pixels

    def pump(self):
        try:
            if self.paused:
                return
            if self.session.closed or self.fault:
                self.reject_queued('owner ended or frontend blocked; no input executed')
                self.status('ended' if self.session.closed else 'blocked')
                return
            owner, qmp, directory, log, side = self.current()
            due = time.monotonic() >= self.next_frame
            if due or self.entries():
                state = qmp('query-status')
                check(state.get('running') is True and state.get('status') == 'running', 'Current QMP owner is not running')
            if due:
                pixels = self.snapshot(qmp, directory)
                self.next_frame = time.monotonic() + .05
                self.status(side + '-running', owner_pid=owner.pid, source_directory=str(directory), pixels_sha256=pixels)
            self.input(owner, log)
        except Exception as error:
            self.fault = type(error).__name__ + ': ' + str(error)
            # Transport faults must not escape into serve()'s original owner-cleanup path.
            try:
                self.r['save'](self.output / ('error-' + secrets.token_hex(12) + '.json'),
                               dict(error=self.fault, input_release_uncertain=self.inflight,
                                    lease_retained_until_owner_exit=True, **LIMITS))
                self.status('blocked')
            except OSError:
                pass
