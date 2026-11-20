#!/usr/bin/env python3
"""Locked qtest endpoint for a paired native AP/CP QEMU; device cases live elsewhere.

The shipped check-notify-qemu.py framing is loaded (never its main). Callers admit the
pair and make the output directory first, then run the checker with cwd=pair so every
AF_UNIX name here stays short. No command line: check-native-qemu.py owns all cases.
"""
import json
import os
from pathlib import Path
import resource
import runpy
import socket
import stat
import struct
import subprocess

HERE = Path(__file__).absolute().parent
MIB, GIB = 1024 ** 2, 1024 ** 3
LINK = runpy.run_path(str(HERE / 'native-link.py'))
_NOTIFY = runpy.run_path(str(HERE / 'check-notify-qemu.py'))
Endpoint = _NOTIFY['Endpoint']
QtestTransportError = _NOTIFY['QtestTransportError']
EXPECTED = {
    'ap': [('native-local-ram', 'ap-ram.bin', 24 * GIB, 0),
           ('native-peer-ram', 'cp-ram.bin', 128 * MIB, 0),
           ('native-peer-oom', 'cp-oom.bin', 0x101000, 0)],
    'cp': [('native-local-ram', 'cp-ram.bin', 128 * MIB, 0),
           ('native-peer-ram', 'ap-ram.bin', 8 * GIB, 15 * GIB),
           ('native-local-oom', 'cp-oom.bin', 0x101000, 0)],
}
# Qtest runs no original AP/CP software; selected input/clock cases temporarily resume the VM.
COMPONENT_EVIDENCE = False
RETAINED = []  # Live owners/clients stay reachable for an importing coordinator.


def require(condition, message):
    if not condition:
        raise ValueError(message)


def build_command(binary, pair, out, side, ram):
    """Pure role geometry; the RAM arguments must already be the helper's exact output."""
    require(side in ('ap', 'cp'), 'Side must be ap or cp')
    require(len(ram) == 6 and all(ram[index] == '-object' for index in (0, 2, 4)),
            'Native RAM contract must return only three -object arguments')
    for index, (name, filename, size, offset) in enumerate(EXPECTED[side]):
        require(json.loads(ram[index * 2 + 1]) == {
            'qom-type': 'memory-backend-file', 'id': name,
            'mem-path': str(Path(pair) / filename), 'size': size, 'offset': offset,
            'share': True, 'discard-data': False}, 'Native RAM geometry differs: ' + side)
    if side == 'ap':
        role = ['-M', 'virt,gic-version=2,memory-backend=native-local-ram',
                '-m', '24G', '-cpu', 'cortex-a53', '-smp', '1']
    else:
        role = ['-M', 'none,memory-backend=native-local-ram',
                '-m', '128M', '-cpu', 'cortex-a53', '-smp', '4']
    # Qtest cannot disable AArch64; no original RTOS executes in this fixture.
    # Stock multi-CPU GIC requires qtest mode for non-vCPU MMIO callbacks.
    command = [str(binary), *role, *ram, '-accel', 'qtest', '-S', '-nodefaults', '-display', 'none', '-nic', 'none',
               '-audio', 'none', '-monitor', 'none', '-serial', 'none', '-sandbox', 'on',
               '-qmp', 'unix:' + side + '-qmp.sock,server=on,wait=off',
               '-qtest', 'unix:' + side + '-qt.sock,server=on,wait=off',
               '-chardev', 'socket,id=notify-peer,path=notify.sock,'
                          + ('server=on,wait=off' if side == 'ap' else 'server=off')]
    if side == 'cp':
        # QemuOpts escapes a literal comma by doubling it.
        for uart in range(5):
            path = str(Path(out) / ('uart%d.log' % uart)).replace(',', ',,')
            command += ['-chardev', 'file,id=cp-uart%d,path=%s' % (uart, path)]
    return command


def strip_environment(inherited):
    return {name: value for name, value in inherited.items()
            if not name.startswith(('MENU_', 'QEMU_', 'SONY_', 'A7C2_'))}


def child_environment(side, pair, inherited=None, *, p1_spi_component=False):
    require(type(p1_spi_component) is bool and (not p1_spi_component or side=='ap'),
            'P1 SPI component is an explicit AP-only diagnostic')
    env = strip_environment(os.environ if inherited is None else inherited)
    env.update(LINK['environment'](side, pair))
    if side == 'cp':
        env['QEMU_NATIVE_COMPONENT_GIC_GROUPS'] = 'virtual-native-component-gic-groups-v1'
    if p1_spi_component:
        env['QEMU_NATIVE_P1_SPI_COMPONENT'] = 'virtual-p1-pl022-component-v1'
    return env


def limits():
    return dict(core=0, cpu_soft=250, cpu_hard=260, address_space=32 * GIB,
                file_size=64 * MIB)


def child_limits():
    budget = limits()
    os.umask(0o077)
    for name, soft, hard in (('CORE', 0, 0),
                             ('CPU', budget['cpu_soft'], budget['cpu_hard']),
                             ('AS', budget['address_space'], budget['address_space']),
                             ('FSIZE', budget['file_size'], budget['file_size'])):
        resource.setrlimit(getattr(resource, 'RLIMIT_' + name), (soft, hard))


class NativeEndpoint(Endpoint):
    def __init__(self, binary, pair, out, side, *, p1_spi_component=False):
        require(side in ('ap', 'cp'), 'Side must be ap or cp')
        self.side = side
        self.binary, self.pair, self.out = Path(binary), Path(pair), Path(out)
        info = self.out.lstat()
        require(stat.S_ISDIR(info.st_mode) and stat.S_IMODE(info.st_mode) == 0o700
                and info.st_uid == os.geteuid(), 'Output must be an owned mode 0700 directory')
        self.process = self.qmp = self.qt = self.qmp_socket = self.qt_socket = None
        self.records, self.counter = [], 0
        self._startup_error = self._shutdown = None
        self._owner = dict(side=side, qmp=side + '-qmp.sock', qt=side + '-qt.sock',
                           profile=LINK['PROFILE'], signals_sent=[],
                           component_evidence=COMPONENT_EVIDENCE)
        LINK['admit'](self.pair, self.binary)  # read-only; before logs and any process
        self.command_line = build_command(self.binary, self.pair, self.out, side,
                                          LINK['ram_arguments'](self.pair, side))
        self._owner['command'] = self.command_line
        self.records.append(dict(command=self.command_line, profile=LINK['PROFILE'], side=side))
        fd = os.open(str(self.out / (side + '.stderr')),
                     os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        os.fchmod(fd, 0o600)
        self.log = os.fdopen(fd, 'wb', buffering=0)
        try:
            self.process = subprocess.Popen(
                self.command_line, cwd=str(self.pair),
                env=child_environment(side, self.pair, p1_spi_component=p1_spi_component),
                stdin=subprocess.DEVNULL, stdout=self.log, stderr=self.log,
                preexec_fn=child_limits, start_new_session=True)
            self.qmp_socket = self.connect(side + '-qmp.sock')
            self._peer(self.qmp_socket)
            self.qmp = self.qmp_socket.makefile('rwb', buffering=0)
            require('QMP' in self.receive(), 'QMP greeting missing')
            self.command('qmp_capabilities')
            self.qt_socket = self.connect(side + '-qt.sock')
            self._peer(self.qt_socket)
            self.qt = self.qt_socket.makefile('rwb', buffering=0)
        except BaseException as error:
            # Keep the original exception; only a cleanly dead owner is released here.
            self._startup_error = repr(error)
            if self.process is not None:
                try:
                    self.close()
                except BaseException:
                    pass
                if self.process is not None:
                    RETAINED.append(self)
            else:
                self.log.close()
            raise

    def _peer(self, connection):
        pid, uid, gid = struct.unpack('3i', connection.getsockopt(
            socket.SOL_SOCKET, socket.SO_PEERCRED, struct.calcsize('3i')))
        require(pid == self.process.pid and uid == os.geteuid(),
                'QMP/qtest peer pid/uid does not belong to the owned QEMU')
        self.records.append(dict(side=self.side, peer=dict(pid=pid, uid=uid, gid=gid)))

    def command(self, name, arguments=None):
        if name not in ('cont', 'stop', 'input-send-event'):
            require(arguments is None, 'Unexpected component QMP arguments')
            return super().command('qmp_capabilities' if name == 'capabilities' else name)
        require(self.side == 'cp', 'Virtual key component commands are CP-only')
        if name == 'input-send-event':
            require(type(arguments) is dict and set(arguments) == {'events'} and
                    type(arguments['events']) is list and len(arguments['events']) == 1,
                    'Expected one virtual key event')
            event = arguments['events'][0]
            require(type(event) is dict and set(event) == {'type', 'data'} and event['type'] == 'key',
                    'Only virtual key events are allowed')
            data = event['data']
            require(type(data) is dict and set(data) == {'down', 'key'} and type(data['down']) is bool and
                    type(data['key']) is dict and set(data['key']) == {'type', 'data'} and
                    data['key']['type'] == 'qcode' and type(data['key']['data']) is str and
                    data['key']['data'] in {'f'+str(i) for i in range(1,14)},
                    'Only boolean F1..F13 virtual key transitions are allowed')
        else:
            require(arguments is None, 'Unexpected component run-state arguments')
        self.counter += 1
        request = dict(execute=name, id=self.counter)
        if arguments is not None:
            request['arguments'] = arguments
        self.records.append(dict(qmp_execute=request))
        self.qmp.write((json.dumps(request, allow_nan=False)+'\n').encode())
        for _ in range(64):
            reply = self.receive()
            if 'event' in reply:
                continue
            if reply.get('id') != self.counter or 'return' not in reply or 'error' in reply:
                raise QtestTransportError('Virtual key component QMP command failed: '+repr(reply))
            return reply['return']
        raise QtestTransportError('Virtual key QMP reply exceeded event budget')

    def _write_owner(self, result, error):
        self._owner['shutdown'] = result
        self._owner['records'] = self.records
        if self._startup_error:
            self._owner.setdefault('initial_error', self._startup_error)
        if error is not None:
            self._owner.setdefault('retained_error', repr(error))
        raw = (json.dumps(self._owner, indent=2, sort_keys=True, allow_nan=False) + '\n').encode()
        path = self.out / (self.side + '-owner.json')
        temp = self.out / ('.' + path.name + '.tmp')
        fd = os.open(str(temp), os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
        try:
            os.fchmod(fd, 0o600)
            while raw:
                written = os.write(fd, raw)
                require(written > 0, 'Owner receipt write made no progress')
                raw = raw[written:]
            os.fsync(fd)
        finally:
            os.close(fd)
        os.replace(temp, path)

    def close(self):
        """Release only on a confirmed dead owner; otherwise keep Popen/handles and raise."""
        result = dict(self._shutdown or {})
        result.setdefault('signals_sent', [])
        error = None
        if self.process is not None:
            result['pid'] = self.process.pid
            try:
                if self.process.poll() is None:
                    require(self.qmp is not None, 'QMP missing; owned process retained')
                    self.command('quit')
                    result['qmp_quit_confirmed'] = True
                self.process.wait(timeout=10)
                result['returncode'] = self.process.returncode
                require(result.get('qmp_quit_confirmed') is True and result['returncode'] == 0,
                        'Native QEMU did not exit normally: ' + repr(result['returncode']))
            except BaseException as caught:
                error = caught
            result['alive'] = self.process.poll() is None
            if result['alive']:
                # Never fake a released lease or a cleared RAM pair.
                result['retained'] = True
                self._shutdown = result
                self._write_owner(result, error)
                raise ValueError('Native QEMU ' + self.side + ' owner retained: ' + repr(error))
            # Definitely dead: clients and the raw log may close only now.
            result.pop('retained', None)
            for stream in (self.qt, self.qmp, self.qt_socket, self.qmp_socket, self.log):
                if stream is not None:
                    stream.close()
            self.qt = self.qmp = self.qt_socket = self.qmp_socket = self.log = None
            self.process = None
            self._shutdown = result
            self._write_owner(result, error)
            if error is not None:
                raise ValueError('Native QEMU ' + self.side
                                 + ' exited without a clean quit: ' + repr(error)) from error
            return result
        result['alive'] = False
        self._shutdown = result
        self._write_owner(result, None)
        return result
