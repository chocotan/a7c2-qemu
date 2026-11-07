"""One serial owner alternates the original App32 sender and diagnostic shell."""
import re
import secrets
import time
from pathlib import Path

from console_wakeup import ConsoleWakeup

_NUMBER = r'(?:0x[0-9a-fA-F]+|[0-9]+)'
_COMMAND = re.compile(r'/simulation/inject-key --app\s+(' + _NUMBER + r'(?:\s+' + _NUMBER + r'){6})')


class PersistentAppInput:
    def __init__(self, proc, console, monitor):
        self.proc, self.console, self.monitor = proc, Path(console), monitor
        self.sequence, self.active = 0, False
        self.exit_marker = None
        proc._app_input_transport = self

    def _wait(self, offset, pattern, timeout=10):
        deadline = time.monotonic() + timeout
        try:
            with ConsoleWakeup(self.console) as wakeup:
                while time.monotonic() < deadline:
                    self.monitor.check()
                    if self.proc.poll() is not None:
                        raise RuntimeError('Original input owner exited before its reply')
                    data = self.console.read_bytes()[offset:].replace(b'\r\n', b'\n')
                    match = pattern.search(data)
                    if match:return match, data
                    wakeup.wait(min(.05, max(0, deadline-time.monotonic())))
            raise TimeoutError('Original App32 input reply missing; retain uncertain contact and owner')
        except BaseException:
            self.proc._menu_serial_desynchronized = True
            raise

    def _write(self, command):
        if getattr(self.proc, '_menu_serial_desynchronized', False):
            raise RuntimeError('Input transaction boundary lost; no retry or alternate sender')
        offset = self.console.stat().st_size
        try:
            self.proc.stdin.write(command.encode('ascii') + b'\n'); self.proc.stdin.flush()
        except BaseException:
            self.proc._menu_serial_desynchronized = True
            raise
        return offset

    def start(self):
        if self.active:return
        self.exit_marker = 'APP_INPUT_SHELL_' + secrets.token_hex(16)
        command = ('/simulation/inject-key --serve-app; _app_rc=$?; '
                   f'printf "\\n{self.exit_marker}:%s\\n" "$_app_rc"')
        offset = self._write(command)
        self.active = True
        self._wait(offset, re.compile(rb'(?:^|\n)APP_INPUT_SERVER_READY\n'))

    def __call__(self, command):
        match = _COMMAND.fullmatch(command)
        if match is None:
            raise ValueError('Unsupported original input command; never retry through another channel')
        values = [int(value, 16) if value.startswith('0x') else int(value) for value in match.group(1).split()]
        if values[:2] != [0x5503e0, 0x5503e0] or any(not 0 <= v <= 0xffffffff for v in values):
            raise ValueError('Persistent sender requires the original App32 route and uint32 fields')
        self.start(); self.sequence += 1
        offset = self._write(' '.join(str(v) for v in [self.sequence] + values[2:]))
        pattern = re.compile(rb'(?:^|\n)APP_INPUT_RESULT ' + str(self.sequence).encode() + rb' ([0-9]+)\n')
        reply, data = self._wait(offset, pattern)
        if int(reply.group(1)) != 0:
            raise RuntimeError('Original App32 allocation/send failed rc=' + reply.group(1).decode())
        return data

    def pause(self):
        if not self.active:return
        self.sequence += 1
        offset = self._write('STOP ' + str(self.sequence))
        pattern = re.compile(rb'(?:^|\n)' + self.exit_marker.encode() + rb':([0-9]+)\n')
        reply, _ = self._wait(offset, pattern)
        if int(reply.group(1)) != 0:
            self.proc._menu_serial_desynchronized = True
            raise RuntimeError('Original App32 sender did not return normally to its shell')
        self.active = False
