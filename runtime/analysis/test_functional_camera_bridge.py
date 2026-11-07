# SPDX-License-Identifier: MIT
"""Focused parent-run batch. Do not execute until the parent freezes all agents.

Wire fixtures exercise transport only. Real-model tests compile/load the actual
core and consume its in-memory bytes; no fixture synthesizes a camera product.
"""
import ctypes
import errno
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import re
import shlex
import socket
import struct
import subprocess
import threading
import time

import pytest

HERE = Path(__file__).resolve().parent
REPORT = HERE.parent.parent / 'report'
spec = importlib.util.spec_from_file_location('functional_camera_broker_tested', HERE / 'functional_camera_broker.py')
b = importlib.util.module_from_spec(spec)
spec.loader.exec_module(b)
MAILBOX = dict(phys0=0x400021000, nonce=0xaabbccdd11223344, pid=1234,
               pages=[0x400021000 - i * 8192 for i in range(16)])


def header(*, seq=1, op=b.STATE, data=b'', capacity=b.DATA, status=b.REQUEST):
    raw = bytearray(b.HEADER)
    struct.pack_into('<4I4Q', raw, 0, b.MAGIC, b.VERSION, MAILBOX['pid'], status,
                     MAILBOX['nonce'], seq, op | (len(data) << 32), capacity)
    # The preceding packed capacity's upper word is response_bytes=0.
    struct.pack_into('<Q', raw, 56, b.fnv64(data))
    struct.pack_into('<5I', raw, 96, 1235, 0x111, 0x222, 0x333, 144)
    struct.pack_into('<Q', raw, 120, 0x123456789abc)
    struct.pack_into('<16Q', raw, 128, *MAILBOX['pages'])
    return bytes(raw)


def state():
    raw = bytearray(128)
    struct.pack_into('<I', raw, 0, 1)
    struct.pack_into('<Q', raw, 48, MAILBOX['nonce'])
    return bytes(raw)


class PhysicalMemory:
    def __init__(self):
        self.pages = {address: bytearray(b.PAGE) for address in MAILBOX['pages']}
        self.mode = False
        self.commands = []
        self.short_read = self.corrupt_write = self.fail_restore = False
        self.detached = False
        self.after_ack_accesses = 0
        self.memory_reads = self.memory_writes = 0

    def access(self, address, size, data=None):
        if self.detached:
            self.after_ack_accesses += 1
            raise AssertionError('RAM access after detach')
        base = address - address % b.PAGE
        assert base in self.pages and size <= b.PAGE - address % b.PAGE
        page = self.pages[base]
        offset = address - base
        if data is None:
            self.memory_reads += 1
            return bytes(page[offset:offset + size])
        self.memory_writes += 1
        page[offset:offset + size] = data
        if self.corrupt_write and address != MAILBOX['phys0'] + 12:
            page[offset] ^= 0x40
            self.corrupt_write = False
        if address == MAILBOX['phys0'] + 12 and data == struct.pack('<I', b.DETACHED):
            self.detached = True

    def logical(self, offset, size, data=None):
        output, used = bytearray(), 0
        while used < size:
            page, inside = divmod(offset + used, b.PAGE)
            count = min(size - used, b.PAGE - inside)
            address = MAILBOX['pages'][page] + inside
            if data is None:
                output.extend(self.access(address, count))
            else:
                self.access(address, count, data[used:used + count])
            used += count
        return bytes(output)

    def dispatch(self, command):
        self.commands.append(command)
        if command == b'qSupported':
            return b'PacketSize=100;Qqemu.PhyMemMode+'
        if command.startswith(b'Qqemu.PhyMemMode:'):
            if command.endswith(b'0') and self.fail_restore:
                return b'E01'
            self.mode = command.endswith(b'1')
            return b'OK'
        if command.startswith(b'm'):
            assert self.mode
            address, count = (int(v, 16) for v in command[1:].split(b','))
            data = self.access(address, count)
            if self.short_read:
                data = data[:-1]
                self.short_read = False
            return data.hex().encode('ascii')
        if command.startswith(b'M'):
            assert self.mode
            span, data = command[1:].split(b':')
            address, count = (int(v, 16) for v in span.split(b','))
            value = bytes.fromhex(data.decode('ascii'))
            assert len(value) == count
            self.access(address, count, value)
            return b'OK'
        raise AssertionError('Unapproved RSP command: ' + repr(command))


class RSPServer:
    """Actual AF_UNIX byte-stream fixture, with deliberately fragmented packets."""
    def __init__(self, path, memory):
        self.path, self.memory = path, memory
        self.errors = []
        self.listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.listener.bind(str(path))
        os.chmod(path, 0o600)
        self.listener.listen(1)
        self.connection = None
        self.thread = threading.Thread(target=self.run, daemon=True)
        self.thread.start()

    @staticmethod
    def byte(connection):
        raw = connection.recv(1)
        if not raw:
            raise EOFError
        return raw

    def run(self):
        try:
            connection, _ = self.listener.accept()
            self.connection = connection
            with connection:
                while True:
                    lead = self.byte(connection)
                    if lead in (b'+', b'-'):
                        continue
                    assert lead == b'$'
                    command = bytearray()
                    while (value := self.byte(connection)) != b'#':
                        command.extend(value)
                    check = self.byte(connection) + self.byte(connection)
                    assert int(check, 16) == sum(command) % 256
                    reply = self.memory.dispatch(bytes(command))
                    packet = b'+$' + reply + b'#' + f'{sum(reply) % 256:02x}'.encode('ascii')
                    # One-byte headers and uneven payload splits defeat recv assumptions.
                    for offset in range(0, len(packet), 7):
                        connection.sendall(packet[offset:offset + 7])
        except (EOFError, BrokenPipeError, ConnectionResetError, OSError):
            pass
        except BaseException as error:
            self.errors.append(error)
        finally:
            self.listener.close()

    def close(self):
        if self.connection:
            try:
                self.connection.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
        self.listener.close()
        self.thread.join(timeout=2)
        assert not self.errors, self.errors


class QMPState:
    def __init__(self, running=True):
        self.running = running
        self.commands = []

    def status(self):
        return dict(running=self.running, status='running' if self.running else 'paused')

    def execute(self, command):
        self.commands.append(command)
        assert command in ('stop', 'cont')
        self.running = command == 'cont'
        return {}


def component(memory, rsp, monkeypatch, *, running=True, resume=lambda: True):
    broker = b.Broker.__new__(b.Broker)
    broker.mailbox = b.validate_mailbox(MAILBOX)
    broker.config = {}
    monkeypatch.setattr(b, 'revalidate', lambda config: None)
    broker.lock = threading.RLock()
    broker.io_timeout = 0.5
    broker.resume_allowed = resume
    broker.acknowledged, broker.phys_restored = False, True
    broker.sequence, broker.event_serial = 0, 0
    broker.cleaning, broker.log_errors = False, []
    broker.last_response = None
    broker.pending_payloads = broker.transfer = broker.last_frame = None
    broker.root = rsp.evidence_root
    broker.payloads = b.PayloadRecords(broker.root)
    rsp.evidence_stores.append(broker.payloads)
    broker.events = io.StringIO()
    broker.done = threading.Event()
    broker.rsp, broker.qmp = rsp, QMPState(running)
    return broker


def retained_publish(broker, request, data, error, result, incoming=b''):
    """HOST_TEST transport fixture; does not claim an actual C-model call."""
    input_ref = broker.payloads.retain(request, 'in', incoming, event=broker.event_serial + 1)
    output_ref = broker.payloads.retain(request, 'out', data, event=broker.event_serial + 1,
                                       token=result.token, total=result.total, offset=result.offset)
    broker.pending_payloads = dict(sequence=b.u64(request, 24), request=request, incoming=incoming,
                                   actual_c_result=error, result=(result.token, result.total, result.offset, result.used),
                                   request_payload=input_ref, output_payload=output_ref, result_transfer=None)
    return broker.publish(request, data, error, result)


@pytest.fixture
def wire(tmp_path):
    memory = PhysicalMemory()
    server = RSPServer(tmp_path / 'gdb.sock', memory)
    rsp = b.RSP(server.path, timeout=2, expected_pid=os.getpid())
    rsp.evidence_root, rsp.evidence_stores = tmp_path, []
    try:
        yield memory, rsp, server
    finally:
        for store in rsp.evidence_stores:
            store.close()
        rsp.close()
        server.close()


@pytest.mark.parametrize('field,value', [('nonce', 0), ('pid', 0), ('phys0', 0x400000001)])
def test_invalid_mailbox_binding(field, value):
    candidate = dict(MAILBOX, **{field: value})
    with pytest.raises(ValueError):
        b.validate_mailbox(candidate)


def test_distinct_fragmented_physical_pages_required():
    candidate = dict(MAILBOX, pages=[MAILBOX['phys0']] * 16)
    with pytest.raises(ValueError, match='distinct'):
        b.validate_mailbox(candidate)
    candidate = dict(MAILBOX, pages=[*MAILBOX['pages'][:-1], 0x540000000])
    with pytest.raises(ValueError):
        b.validate_mailbox(candidate)


@pytest.mark.parametrize('offset,raw', [
    (0, struct.pack('<I', 0)), (4, struct.pack('<I', 2)), (8, struct.pack('<I', 4321)),
    (16, struct.pack('<Q', 1)), (136, struct.pack('<Q', MAILBOX['pages'][0])),
    (256, b'\x01'), (116, b'\x01'), (52, b'\x01'),
    (24, struct.pack('<Q', 0)), (32, struct.pack('<I', 999)),
    (36, struct.pack('<I', b.DATA + 1)), (40, struct.pack('<I', b.DATA + 1)),
    (44, b'\x01'), (64, b'\x01'), (56, struct.pack('<Q', 0)),
    (96, struct.pack('<I', 0)), (100, struct.pack('<I', 0)), (112, struct.pack('<I', 0)),
])
def test_strict_request_header_validation(offset, raw):
    request = bytearray(header())
    request[offset:offset + len(raw)] = raw
    with pytest.raises(ValueError):
        b.validate_request(bytes(request), b'', MAILBOX, 0)


def test_replay_sequence_and_result_request_bounds():
    for previous in (1, 2, 2**64 - 1):
        with pytest.raises(ValueError, match='sequence'):
            b.validate_request(header(), b'', MAILBOX, previous)
    data = struct.pack('<QQII', 77, 0, 32, 0)
    with pytest.raises(ValueError, match='retained'):
        b.validate_request(header(op=b.READ_RESULT, data=data, capacity=31), data, MAILBOX, 0)
    assert b.validate_request(header(op=b.READ_RESULT, data=data, capacity=32), data, MAILBOX, 0) == (b.READ_RESULT, 32)


def test_segmented_rsp_and_noncontiguous_mailbox(wire, monkeypatch):
    memory, rsp, _ = wire
    broker = component(memory, rsp, monkeypatch)
    payload = bytes((n * 37 + n // 29) % 256 for n in range(b.MAILBOX_BYTES))
    memory.logical(0, len(payload), payload)
    with broker.copy_window(), broker.physical():
        assert broker.read(0, len(payload)) == payload
        replacement = bytes(reversed(payload[:9000]))
        broker.write(4000, replacement)
        assert broker.read(4000, 9000) == replacement
    assert not memory.mode and broker.phys_restored
    assert broker.qmp.commands == ['stop', 'cont']
    reads = [command for command in memory.commands if command.startswith(b'm')]
    writes = [command for command in memory.commands if command.startswith(b'M')]
    assert len(reads) > 500 and len(writes) > 50
    assert all(len(command) <= rsp.packet_size for command in memory.commands)
    assert any(f'{MAILBOX["pages"][1]:x}'.encode() in command for command in reads)


def test_copy_exception_always_restores_physical_mode(wire, monkeypatch):
    memory, rsp, _ = wire
    broker = component(memory, rsp, monkeypatch)
    with pytest.raises(RuntimeError, match='consumer failure'):
        with broker.copy_window(), broker.physical():
            broker.read(0, 32)
            raise RuntimeError('consumer failure')
    assert not memory.mode and broker.phys_restored and broker.qmp.running
    assert memory.commands[-1] == b'Qqemu.PhyMemMode:0'


def test_failed_mode_enable_still_attempts_restore(wire, monkeypatch):
    memory, rsp, _ = wire
    broker = component(memory, rsp, monkeypatch)
    actual = rsp.mode
    calls = []

    def mode(value):
        calls.append(value)
        if value:
            raise ValueError('enable rejected')
        actual(value)

    monkeypatch.setattr(rsp, 'mode', mode)
    with pytest.raises(ValueError, match='enable rejected'):
        with broker.copy_window(), broker.physical():
            pass
    assert calls == [True, False] and broker.phys_restored


def test_restore_failure_keeps_vm_stopped(wire, monkeypatch):
    memory, rsp, _ = wire
    broker = component(memory, rsp, monkeypatch)
    memory.fail_restore = True
    with pytest.raises(ValueError):
        with broker.copy_window(), broker.physical():
            broker.read(0, 1)
    assert not broker.phys_restored and not broker.qmp.running
    assert broker.qmp.commands == ['stop']
    memory.fail_restore = False
    rsp.mode(False)


@pytest.mark.parametrize('running,resume,expected', [(False, True, []), (True, False, ['stop'])])
def test_paused_vm_and_sdstop_barrier_are_not_resumed(wire, monkeypatch, running, resume, expected):
    memory, rsp, _ = wire
    memory.logical(0, b.HEADER, header())
    broker = component(memory, rsp, monkeypatch, running=running, resume=lambda: resume)
    assert broker.fetch()[1] == b''
    assert broker.qmp.commands == expected and not broker.qmp.running
    assert b'D' not in memory.commands and not memory.mode


def test_short_partial_rsp_read_is_failure_and_restores_mode(wire, monkeypatch):
    memory, rsp, _ = wire
    memory.logical(0, b.HEADER, header())
    broker = component(memory, rsp, monkeypatch)
    memory.short_read = True
    with pytest.raises(ValueError, match='Short'):
        broker.fetch()
    assert not memory.mode and broker.phys_restored and broker.qmp.running


@pytest.mark.parametrize('offset,value,kind', [(16, struct.pack('<Q', 9), 'header_rejected'),
                                             (24, struct.pack('<Q', 0), 'request_rejected')])
def test_rejected_wire_keeps_raw_header_evidence(wire, monkeypatch, offset, value, kind):
    memory, rsp, _ = wire
    request = bytearray(header())
    request[offset:offset + len(value)] = value
    memory.logical(0, b.HEADER, request)
    broker = component(memory, rsp, monkeypatch)
    with pytest.raises(ValueError):
        broker.fetch()
    receipts = [json.loads(line) for line in broker.events.getvalue().splitlines()]
    rejected = next(item for item in receipts if item['kind'] == kind)
    assert rejected['raw_header_hex'] == request.hex()
    assert rejected['raw_header_sha256'] == hashlib.sha256(request).hexdigest()
    assert not memory.mode and broker.phys_restored


def test_publish_stages_actual_bytes_then_commits_last(wire, monkeypatch):
    memory, rsp, _ = wire
    request = header()
    memory.logical(0, b.HEADER, request)
    broker = component(memory, rsp, monkeypatch)
    raw, data = broker.fetch()
    assert raw == request and data == b''
    broker.sequence = 1
    result = b.ExecResult(0, 0, 0, 128)
    output = state()
    assert retained_publish(broker, raw, output, 0, result)
    assert memory.logical(b.HEADER, len(output)) == output
    response = memory.logical(0, b.HEADER)
    assert b.u32(response, 12) == b.RESPONSE and b.u64(response, 64) == b.fnv64(output)
    writes = [command for command in memory.commands if command.startswith(b'M')]
    assert writes[-1].startswith(f'M{MAILBOX["phys0"] + 12:x},4:'.encode())
    receipt = [json.loads(line) for line in broker.events.getvalue().splitlines() if json.loads(line)['kind'] == 'response'][0]
    assert receipt['data_readback'] is True and receipt['native_acceptance'] is False
    assert receipt['returned_sha256'] == hashlib.sha256(output).hexdigest()
    assert broker.fetch()[1] is None


@pytest.mark.parametrize('error,result', [(1, b.ExecResult()), (0, b.ExecResult(1, 0, 0, 0)),
                                        (0, b.ExecResult(1, b.MAX_RESULT + 1, 0, 0))])
def test_invalid_core_response_is_never_written(wire, monkeypatch, error, result):
    memory, rsp, _ = wire
    request = header()
    memory.logical(0, b.HEADER, request)
    broker = component(memory, rsp, monkeypatch)
    before = memory.memory_writes
    with pytest.raises(ValueError, match='core output'):
        broker.publish(request, b'', error, result)
    assert memory.memory_writes == before


def test_changed_actual_result_metadata_never_commits(wire, monkeypatch):
    memory, rsp, _ = wire
    broker = component(memory, rsp, monkeypatch)
    request = header()
    memory.logical(0, b.HEADER, request)
    original = broker.publish

    def changed(raw, data, error, result):
        result.token, result.total = 77, len(data)  # Valid bounds, different actual C result.
        return original(raw, data, error, result)

    monkeypatch.setattr(broker, 'publish', changed)
    before = memory.memory_writes
    with pytest.raises(ValueError, match='changed actual'):
        retained_publish(broker, request, state(), 0, b.ExecResult(0, 0, 0, 128))
    assert memory.memory_writes == before and broker.last_response is None


def test_staged_data_readback_mismatch_never_commits_success(wire, monkeypatch):
    memory, rsp, _ = wire
    request = header()
    memory.logical(0, b.HEADER, request)
    broker = component(memory, rsp, monkeypatch)
    memory.corrupt_write = True
    with pytest.raises(ValueError, match='readback'):
        retained_publish(broker, request, state(), 0, b.ExecResult(0, 0, 0, 128))
    assert b.u32(memory.logical(0, b.HEADER), 12) == b.REQUEST
    assert not memory.mode


def test_late_close_discards_result_and_final_ack_has_no_more_ram_access(wire, monkeypatch):
    memory, rsp, _ = wire
    request = header()
    closed = bytearray(request)
    struct.pack_into('<I', closed, 12, b.CLOSED)
    memory.logical(0, b.HEADER, closed)
    broker = component(memory, rsp, monkeypatch)
    assert retained_publish(broker, request, state(), 0, b.ExecResult(0, 0, 0, 128)) is False
    assert memory.memory_writes == 1  # Fixture's initial header, no broker writes.
    broker.core = type('DestroyedModel', (), {'model': None})()
    broker.detach_mailbox()
    assert broker.acknowledged and memory.detached and memory.after_ack_accesses == 0
    assert broker.phys_restored and not memory.mode
    with pytest.raises(ValueError, match='after DETACHED'):
        broker.read(0, 1)
    with pytest.raises(ValueError, match='after DETACHED'):
        broker.write(0, b'\x00')
    assert memory.after_ack_accesses == 0


def test_no_detach_with_live_model(wire, monkeypatch):
    memory, rsp, _ = wire
    broker = component(memory, rsp, monkeypatch)
    broker.core = type('LiveModel', (), {'model': object()})()
    with pytest.raises(ValueError, match='core owns'):
        broker.detach_mailbox()
    assert not memory.detached


def test_debugger_handoff_required_before_endpoint_or_library_access():
    with pytest.raises(ValueError, match='old debugger shutdown'):
        b.start('/nonexistent', 0, {}, '/nonexistent', qemu_pid=0, qemu_sha256='', library_sha256='',
                gdb_socket='/nonexistent', qmp_socket='/nonexistent', coordination_lock=None,
                debugger_quiesced=False, resume_allowed=lambda: True)


def test_listener_binding_permissions_and_existing_client(wire):
    _, _, server = wire
    with pytest.raises(ValueError, match='connected client'):
        b.checked_socket(server.path.parent, server.path, os.getpid())
    os.chmod(server.path, 0o644)
    with pytest.raises(ValueError, match='0600'):
        b.checked_socket(server.path.parent, server.path, os.getpid())
    os.chmod(server.path, 0o600)
    with pytest.raises(FileNotFoundError):
        b.checked_socket(server.path.parent, server.path.parent / 'missing', os.getpid())


def test_rsp_peer_pid_must_be_the_actual_bound_process(tmp_path):
    server = RSPServer(tmp_path / 'gdb.sock', PhysicalMemory())
    try:
        with pytest.raises(ValueError, match='peer process'):
            b.RSP(server.path, expected_pid=os.getpid() + 100000)
    finally:
        server.close()


@pytest.mark.parametrize('long_path', [False, True])
def test_qmp_fragmented_events_and_matching_ids(tmp_path, long_path):
    directory = tmp_path / ('deep-' + 'x' * 90) if long_path else tmp_path
    directory.mkdir(exist_ok=True)
    path = directory / 'qmp.sock'
    listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    if long_path:
        fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
        try:
            listener.bind(f'/proc/self/fd/{fd}/{path.name}')
        finally:
            os.close(fd)
        assert len(os.fsencode(path)) >= 108
    else:
        listener.bind(str(path))
    listener.listen(1)
    errors = []

    def serve():
        try:
            with listener.accept()[0] as connection:
                connection.sendall(b'{"QMP":{}}\r\n')
                stream = connection.makefile('rb')
                for line in stream:
                    request = json.loads(line)
                    result = dict(running=False, status='paused') if request['execute'] == 'query-status' else {}
                    payload = b'{"event":"STOP"}\r\n' + json.dumps(dict(id=request['id'], **{'return': result})).encode() + b'\r\n'
                    for n in range(0, len(payload), 3):
                        connection.sendall(payload[n:n + 3])
        except BaseException as error:
            errors.append(error)
        finally:
            listener.close()

    thread = threading.Thread(target=serve, daemon=True)
    thread.start()
    qmp = b.QMP(path, expected_pid=os.getpid())
    try:
        assert qmp.status() == dict(running=False, status='paused')
    finally:
        qmp.close()
        thread.join(timeout=2)
    assert not errors and not thread.is_alive()


def test_rsp_long_run_path_uses_real_peer(tmp_path):
    directory = tmp_path / ('deep-' + 'x' * 90)
    directory.mkdir()
    path = directory / 'gdb.sock'
    assert len(os.fsencode(path)) >= 108
    fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
    try:
        server = RSPServer(Path(f'/proc/self/fd/{fd}/{path.name}'), PhysicalMemory())
    finally:
        os.close(fd)
    rsp = None
    try:
        rsp = b.RSP(path, expected_pid=os.getpid())
        rsp.mode(True)
        rsp.mode(False)
    finally:
        if rsp is not None:
            rsp.close()
        server.close()


def test_socket_connect_failure_closes_directory_fd(tmp_path, monkeypatch):
    opened = []
    real_open = os.open

    def tracked_open(*args, **kwargs):
        fd = real_open(*args, **kwargs)
        opened.append(fd)
        return fd

    stream = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    monkeypatch.setattr(b.os, 'open', tracked_open)
    try:
        with pytest.raises(FileNotFoundError):
            b.connect_unix(stream, tmp_path / 'missing.sock')
    finally:
        stream.close()
    assert opened
    for fd in opened:
        with pytest.raises(OSError):
            os.fstat(fd)


BANK_SCENARIOS = (
    'bank', 'bank-validation', 'bank-version', 'bank-size-field', 'bank-instance', 'bank-generation',
    'bank-before', 'bank-after', 'bank-input-fnv', 'bank-fps', 'bank-slots', 'bank-raw-bytes', 'bank-reserved',
    'bank-state-abi', 'bank-state-fps', 'bank-state-instance', 'bank-state-generation',
    'bank-state-rendered', 'bank-state-frame', 'bank-state-reserved', 'bank-cookie', 'bank-last',
    'bank-stale21', 'bank-short', 'bank-token', 'bank-upstream', 'bank-transport-fnv', 'bank-copy')


@pytest.mark.parametrize('mode', ['normal', 'sanitized'])
@pytest.mark.parametrize('scenario', BANK_SCENARIOS)
def test_actual_c_parameter_bank_bridge_contracts(guest_builds, mode, scenario):
    test_actual_c_bridge_contracts(guest_builds, mode, scenario)


@pytest.mark.parametrize('mode', ['normal', 'sanitized'])
@pytest.mark.parametrize('scenario', ('ou', 'ou-validation', 'ou-mutation', 'ou-short', 'ou-long',
    'ou-token', 'ou-upstream', 'ou-transport-fnv', 'ou-origin', 'ou-copy'))
def test_actual_c_ou_crank_bridge_contracts(guest_builds, mode, scenario):
    test_actual_c_bridge_contracts(guest_builds, mode, scenario)


MOVIE_SCENARIOS = ('movie', 'movie-validation', 'movie-mutation', 'movie-retry', 'movie-short', 'movie-long',
    'movie-token', 'movie-errorpayload', 'movie-upstream', 'movie-transport-fnv', 'movie-origin', 'movie-copy')


@pytest.mark.parametrize('mode', ['normal', 'sanitized'])
@pytest.mark.parametrize('scenario', MOVIE_SCENARIOS)
def test_actual_c_movie_format_bridge_contracts(guest_builds, mode, scenario):
    test_actual_c_bridge_contracts(guest_builds, mode, scenario)


CRANK_SCENARIOS = (
    'crank', 'crank-validation', 'crank-mutation', 'crank-retry', 'crank-version', 'crank-size-field',
    'crank-instance', 'crank-generation', 'crank-bank', 'crank-before', 'crank-after', 'crank-input-fnv',
    'crank-mode', 'crank-fps', 'crank-state-abi', 'crank-state-fps', 'crank-state-instance',
    'crank-state-config', 'crank-state-rendered', 'crank-state-consumed', 'crank-state-jpeg',
    'crank-state-video', 'crank-state-result-read', 'crank-state-pending', 'crank-state-stream',
    'crank-state-frame', 'crank-state-reserved', 'crank-type', 'crank-opaque', 'crank-command',
    'crank-cookie', 'crank-echo-mode', 'crank-reserved', 'crank-last', 'crank-short', 'crank-long',
    'crank-token', 'crank-errorpayload', 'crank-upstream', 'crank-transport-fnv', 'crank-origin', 'crank-copy')


@pytest.mark.parametrize('mode', ['normal', 'sanitized'])
@pytest.mark.parametrize('scenario', CRANK_SCENARIOS)
def test_actual_c_crank_control_bridge_contracts(guest_builds, mode, scenario):
    test_actual_c_bridge_contracts(guest_builds, mode, scenario)


STARTUP_CONTROL_SCENARIOS = (
    'startup', 'startup-focus', 'startup-validation', 'startup-class5', 'startup-class8',
    'startup-size176', 'startup-short', 'startup-tailbody', 'startup-tailreserved',
    'startup-tailfp', 'startup-inputfnv', 'startup-sink', 'startup-active',
    'startup-width', 'startup-heightstride', 'startup-endpoint', 'startup-selectedcompleted',
    'startup-route', 'startup-generations', 'startup-lease', 'startup-enabled',
    'startup-readback', 'startup-commit', 'startup-consume', 'startup-retire',
    'startup-status', 'startup-instance', 'startup-token', 'startup-errorpayload',
    'startup-upstream', 'startup-fnv', 'startup-copy', 'startup-flags', 'startup-origin',
    'startup-declared', 'startup-overflow')


@pytest.mark.parametrize('mode', ['normal', 'sanitized'])
@pytest.mark.parametrize('scenario', STARTUP_CONTROL_SCENARIOS)
def test_actual_c_startup_control_bridge_contracts(guest_builds, mode, scenario):
    # Host-only wire fixture: actual STATE128 config40 fingerprint, no broker/socket/VM.
    test_actual_c_bridge_contracts(guest_builds, mode, scenario)


STILL_FORMAT_SCENARIOS = (
    'stillformat', 'stillformat-validation', 'stillformat-class7', 'stillformat-class5',
    'stillformat-badabi', 'stillformat-baddeclared', 'stillformat-size168', 'stillformat-badsize',
    'stillformat-badinputfnv', 'stillformat-badsink', 'stillformat-badactive',
    'stillformat-badwidth', 'stillformat-badheight', 'stillformat-badstride',
    'stillformat-badendpoint', 'stillformat-badselected', 'stillformat-badcompleted',
    'stillformat-badenabled', 'stillformat-badreadback', 'stillformat-badcommit',
    'stillformat-badconsume', 'stillformat-badretire', 'stillformat-badstatus',
    'stillformat-badreserved', 'stillformat-badlease', 'stillformat-badframe',
    'stillformat-badconfig', 'stillformat-overflowframe', 'stillformat-overflowconfig',
    'stillformat-badroute', 'stillformat-badroutepin', 'stillformat-badroutemode',
    'stillformat-badroutetail', 'stillformat-badtail', 'stillformat-badslot',
    'stillformat-badinstance', 'stillformat-upstream', 'stillformat-errorpayload',
    'stillformat-badtoken', 'stillformat-badfnv', 'stillformat-badflags',
    'stillformat-badsource', 'stillformat-baddestination', 'stillformat-badorigin', 'stillformat-copy')


@pytest.mark.parametrize('mode', ['normal', 'sanitized'])
@pytest.mark.parametrize('scenario', STILL_FORMAT_SCENARIOS)
def test_actual_c_still_format_bridge_contracts(guest_builds, mode, scenario):
    # Host-only typed wire fixture; no broker, QMP/RSP endpoint or native completion.
    test_actual_c_bridge_contracts(guest_builds, mode, scenario)


C_SCENARIOS = ('bitwidth', 'bitwidth-validation', 'bitwidth-badclass', 'bitwidth-badsize',
               'bitwidth-badtail', 'bitwidth-badinputfnv', 'bitwidth-badsink', 'bitwidth-badinstance',
               'bitwidth-badreserved', 'bitwidth-badframe', 'bitwidth-badgeneration', 'bitwidth-badroute',
               'bitwidth-badretire', 'bitwidth-badtoken', 'bitwidth-badfnv', 'bitwidth-upstream', 'bitwidth-copy',
               'snapshot-1d9', 'snapshot-1da', 'snapshot-1db', 'snapshot-schema',
               'snapshot-empty', 'snapshot-total', 'snapshot-short', 'snapshot-digest', 'snapshot-flags',
               'snapshot-partial', 'snapshot-release', 'snapshot-token',
               'vdf', 'vdfbadsize', 'vdfbadinstance', 'vdfbadreserved',
               'zebra', 'zebrabadsize', 'zebrabadinstance', 'zebrabadreserved',
               'layout', 'layoutbadsize', 'layoutbadinstance', 'layoutbadreserved',
               'display', 'displaybadsize', 'displaybadinstance', 'displaybadreserved',
               'bb', 'bbbadsize', 'bbbadinstance', 'bbbadreserved', 'bbbadclass', 'bbsmall',
               'hist', 'histbadsize', 'histbadinstance', 'histbadreserved', 'histbadclass', 'histsmall',
               'transfer', 'enospc', 'partial', 'readback', 'latebuffer', 'shortchunk', 'lateclose', 'timeoutretain', 'fork',
               'validation', 'serialize', 'pin', 'duplicate', 'pfnzero', 'pfnrange', 'pfnalign', 'pfnchanged', 'pagemap', 'noncezero',
               'badnonce', 'badpid', 'badpages', 'badreserved', 'badseq', 'badop', 'badbounds', 'badfnv')


@pytest.fixture(scope='session')
def guest_builds(tmp_path_factory):
    directory = tmp_path_factory.mktemp('functional-camera-bridge-build')
    cc = shlex.split(os.environ.get('CC', 'cc'))
    result = {}
    for name, flags in [('normal', ['-O2']), ('sanitized', ['-O1', '-g', '-fsanitize=address,undefined',
                         '-fno-sanitize-recover=all', '-fno-omit-frame-pointer', '-fno-pie', '-no-pie'])]:
        executable = directory / name
        process = subprocess.run(cc + ['-std=c11', '-Wall', '-Wextra', '-Werror', '-pedantic', '-pthread'] + flags +
                                 [str(HERE / 'test-functional-camera-bridge.c'), '-o', str(executable)],
                                 capture_output=True, timeout=45)
        (directory / (name + '.compile.log')).write_bytes(process.stdout + process.stderr)
        assert process.returncode == 0, process.stderr.decode(errors='replace')
        result[name] = executable
    return result


@pytest.mark.parametrize('mode', ['normal', 'sanitized'])
@pytest.mark.parametrize('scenario', C_SCENARIOS)
def test_actual_c_bridge_contracts(guest_builds, mode, scenario):
    env = dict(os.environ, ASAN_OPTIONS='detect_leaks=1:abort_on_error=1', UBSAN_OPTIONS='halt_on_error=1:print_stacktrace=1')
    executable = guest_builds[mode]
    process = subprocess.run([str(executable), scenario], env=env, capture_output=True, timeout=8)
    (executable.parent / (mode + '-' + scenario + '.stdout.bin')).write_bytes(process.stdout)
    (executable.parent / (mode + '-' + scenario + '.stderr.log')).write_bytes(process.stderr)
    assert process.returncode == 0, process.stderr.decode(errors='replace')
    assert b'Sanitizer' not in process.stderr and b'runtime error:' not in process.stderr


@pytest.fixture(scope='session')
def actual_core_library(tmp_path_factory):
    if configured := os.environ.get('FCAM_CORE_LIBRARY'):
        library = Path(configured).resolve(strict=True)
        expected = os.environ.get('FCAM_CORE_SHA256')
        assert expected and hashlib.sha256(library.read_bytes()).hexdigest() == expected
        return library, expected
    core = REPORT / 'functional-camera-core/functional-camera-core.c'
    dependencies = [REPORT / path for path in (
        'virtual-optics/optics.c', 'virtual-optical-frame-owner/optical-frame-owner.c',
        'virtual-jpeg-hardware/jpeg-hardware.c', 'virtual-jpeg-hardware/jpeg-hardware-codec.c',
        'virtual-jpeg-sos/jpeg-sos.c', 'virtual-video-engine/video-engine.c',
        'virtual-camera-pipeline/camera-pipeline.c',
        '../runtime/analysis/device-models/cp-parameter-batch.c')]
    if not core.exists() or not all(path.exists() for path in dependencies):
        pytest.skip('Actual core/dependencies have not been delivered yet')
    libraries = shlex.split(subprocess.check_output(['pkg-config', '--cflags', '--libs',
                           'libjpeg', 'libavcodec', 'libavformat', 'libavutil', 'libswscale'], text=True, timeout=10))
    library = tmp_path_factory.mktemp('functional-camera-bridge-core') / 'libfunctional-camera-core.so'
    cc = shlex.split(os.environ.get('CC', 'cc'))
    subprocess.run(cc + ['-std=c11', '-Wall', '-Wextra', '-Werror', '-pedantic', '-O2', '-fPIC', '-shared',
                        '-Wl,-z,defs', str(core)] + list(map(str, dependencies)) + libraries + ['-lm', '-o', str(library)],
                   check=True, capture_output=True, timeout=90)
    return library, hashlib.sha256(library.read_bytes()).hexdigest()


def test_actual_ctypes_bb_histogram_use_real_rgb_without_encoded_results(actual_core_library):
    library, digest = actual_core_library
    core = b.Core(library, digest)
    instance = MAILBOX['nonce']
    examples = [(0x111, 28, bytes.fromhex('00000f02') + bytes(24)),
                (0x166, 28, bytes.fromhex('0001') + bytes(26)),
                (0x167, 2, bytes.fromhex('0100')), (0x15f, 4, bytes(4)),
                (0x128, 12, bytes.fromhex('000100001e00000000000000'))]
    canonical = [struct.pack('<2H', command, count) + body + bytes(28 - count)
                 for command, count, body in examples]
    try:
        assert core.execute(instance, b.INIT, b'', 128)[0] == 0
        route = b'\x01\x05\x05' + bytes(13)
        assert core.execute(instance, b.VDF_PATH, route, 160)[0] == 0
        previous = core.proof_snapshot()
        code, data, result = core.execute(instance, b.BB_STARTUP_CONFIG, canonical[0], 191)
        assert code == -errno.ENOSPC and data == b'' and result.used == 0
        assert core.proof_snapshot() == previous
        for data in canonical:
            code, output, result = core.execute(instance, b.BB_STARTUP_CONFIG, data, 192)
            assert code == 0 and result.used == 192 and not result.token and output[160:] == data
            assert b.u32(output, 96) == 5 and b.u64(output, 40) == b.fnv64(data) and output[128:144] == route
            proof = core.proof_snapshot()
            assert proof['serial'] == previous['serial'] + 1 and proof['consumer_kind'] == 5
            assert proof['source_fnv1a64'] == proof['consumer_before_fnv1a64'] == proof['consumer_after_fnv1a64'] == b.u64(output, 48)
            assert proof['retired'] == proof['consumer_entered'] == proof['consumer_returned'] == 1
            assert proof['after']['consumed'] == previous['after']['consumed'] + 1
            previous = proof
        request = bytes.fromhex('4801040001010000')
        code, data, result = core.execute(instance, b.HISTOGRAM, request, 1191)
        assert code == -errno.ENOSPC and data == b'' and not result.used and core.proof_snapshot() == previous
        code, output, result = core.execute(instance, b.HISTOGRAM, request, 1192)
        assert code == 0 and result.used == 1192 and not result.token
        assert output[160:168] == request and len(output[168:]) == 1024
        assert all(max(output[offset:offset + 256]) == 255 for offset in range(168, 1192, 256))
        proof = core.proof_snapshot()
        assert proof['serial'] == previous['serial'] + 1 and proof['opcode'] == b.HISTOGRAM and proof['consumer_kind'] == 6
        assert proof['owner_pid'] == os.getpid() and proof['model_instance'] == instance
        assert proof['source_fnv1a64'] == proof['consumer_before_fnv1a64'] == proof['consumer_after_fnv1a64'] == b.u64(output, 48) == b.u64(output, 56)
        assert proof['active_bytes'] == 921600 and proof['render_observed'] == proof['consumer_entered'] == proof['consumer_returned'] == proof['retired'] == 1
        assert not any(proof[key] for key in ('encoder_consumed', 'encoded_bytes', 'result_token'))
        assert proof['result_bytes'] == 1192 and proof['result_fnv1a64'] == b.fnv64(output)
        assert proof['after']['jpeg_encoded'] == proof['after']['video_encoded'] == 0
        code, state_bytes, _ = core.execute(instance, b.STATE, b'', 128)
        assert code == 0 and b.u64(state_bytes, 72) == 7 and b.u32(state_bytes, 104) == 0 and b.u32(state_bytes, 108) == 0
        assert core.proof_snapshot() == proof
    finally:
        core.close()


def test_ctypes_requires_accepted_actual_library_hash(actual_core_library):
    library, _ = actual_core_library
    with pytest.raises(ValueError, match='accepted build'):
        b.Core(library, '0' * 64)


def test_actual_ctypes_core_drains_sequential_chunks_and_cancels(actual_core_library):
    library, digest = actual_core_library
    core = b.Core(library, digest)
    instance = MAILBOX['nonce']
    try:
        assert core.model is None
        with pytest.raises(ValueError, match='INIT'):
            core.execute(instance, b.STATE, b'', 128)
        code, data, result = core.execute(instance, b.INIT, b'', 128)
        assert code == 0 and len(data) == 128 and b.u64(data, 48) == instance and result.used == 128
        probe = core.proof_snapshot()
        assert probe['serial'] == 1 and probe['consumer_kind'] == 0 and probe['render_observed'] == probe['retired'] == 1
        assert probe['width'] == 640 and probe['height'] == 480 and probe['stride'] == 1920
        assert not any(probe[key] for key in ('consumer_entered', 'consumer_returned', 'encoder_consumed', 'encoded_bytes', 'result_bytes'))
        assert probe['before']['rendered'] == 0 and probe['after']['rendered'] == probe['after']['retired'] == 1
        assert probe['after']['consumed'] == probe['after']['jpeg_encoded'] == probe['after']['video_encoded'] == 0
        request = struct.pack('<IIII', 1, 128, 64, 90)
        code, first, result = core.execute(instance, b.STILL, request, 37)
        assert code == 0 and result.token and result.total > len(first)
        token, total = result.token, result.total
        proof = core.proof_snapshot()
        assert proof['serial'] == 2 and proof['frame_generation'] == 2 and proof['consumer_kind'] == 1
        assert proof['source_fnv1a64'] == proof['consumer_before_fnv1a64'] == proof['consumer_after_fnv1a64']
        assert proof['consumer_entered'] == proof['consumer_returned'] == proof['encoder_consumed'] == proof['retired'] == 1
        assert proof['owner_pid'] == os.getpid() and proof['model_instance'] == instance and proof['operation_status'] == 0
        output = bytearray(first)
        while len(output) < total:
            request = struct.pack('<QQII', token, len(output), 37, 0)
            code, chunk, result = core.execute(instance, b.READ_RESULT, request, 53)
            assert code == 0 and result.offset == len(output) and chunk
            output.extend(chunk)
            assert core.proof_snapshot() == proof
        assert output[:2] == b'\xff\xd8' and output[-2:] == b'\xff\xd9'
        assert proof['result_bytes'] == len(output) and proof['result_fnv1a64'] == b.fnv64(output)
        assert proof['encoded_bytes'] == len(output) - 575 and proof['encoded_fnv1a64'] == b.fnv64(output[575:])
        code, empty, result = core.execute(instance, b.RELEASE_RESULT, struct.pack('<QQ', token, b.fnv64(output)), 0)
        assert (code, empty, result.used) == (0, b'', 0)
        assert core.proof_snapshot() == proof
        code, data, result = core.execute(instance, b.STATE, b'', 128)
        assert code == 0 and b.u64(data, 72) == 1 and b.u32(data, 104) == 0
        code, _, result = core.execute(instance, b.STILL, struct.pack('<IIII', 1, 128, 64, 90), 1)
        assert code == 0 and result.token
        token = result.token
        proof = core.proof_snapshot()
        assert core.execute(instance, b.CANCEL, b'', 128)[0] == 0
        assert core.proof_snapshot() == proof
        assert core.execute(instance, b.READ_RESULT, struct.pack('<QQII', token, 1, 1, 0), 1)[0] == -errno.ESTALE
    finally:
        core.close()


def test_actual_core_bytes_through_fragmented_mailbox(actual_core_library, wire, monkeypatch):
    library, digest = actual_core_library
    memory, rsp, _ = wire
    broker = component(memory, rsp, monkeypatch)
    broker.core = b.Core(library, digest)
    seq = 0

    def execute(op, data=b'', capacity=256):
        nonlocal seq
        seq += 1
        request = header(seq=seq, op=op, data=data, capacity=capacity)
        memory.logical(0, len(request), request)
        if data:
            memory.logical(b.HEADER, len(data), data)
        raw, actual_input = broker.fetch()
        opcode, cap = b.validate_request(raw, actual_input, MAILBOX, broker.sequence)
        code, output, result = broker.call_core(raw, actual_input, cap)
        assert broker.publish(raw, output, code, result)
        response = memory.logical(0, b.HEADER)
        actual = memory.logical(b.HEADER, b.u32(response, 44))
        assert actual == output and b.fnv64(actual) == b.u64(response, 64)
        return code, actual, result

    try:
        assert execute(b.INIT)[0] == 0
        code, first, result = execute(b.STILL, struct.pack('<IIII', 1, 128, 64, 90))
        assert code == 0 and result.token
        token, total = result.token, result.total
        destination = bytearray(first)
        while len(destination) < total:
            code, chunk, result = execute(b.READ_RESULT, struct.pack('<QQII', token, len(destination), 256, 0))
            assert code == 0 and result.offset == len(destination)
            destination.extend(chunk)
        assert destination[:2] == b'\xff\xd8' and destination[-2:] == b'\xff\xd9'
        assert execute(b.RELEASE_RESULT, struct.pack('<QQ', token, b.fnv64(destination)), capacity=0)[0] == 0
        receipts = [json.loads(line) for line in broker.events.getvalue().splitlines()]
        responses = [item for item in receipts if item['kind'] == 'response']
        assert len(responses) == seq and all(item['data_readback'] and not item['native_acceptance'] for item in responses)
        assert all(item['actual_c_result'] == 0 for item in responses)
        requests = {item['sequence']: item for item in receipts if item['kind'] == 'request'}
        results = {item['sequence']: item for item in receipts if item['kind'] == 'core_result'}
        for response in responses:
            sequence = response['sequence']
            assert response['request_payload'] == requests[sequence]['request_payload']
            assert response['output_payload'] == results[sequence]['output_payload']
            for field, producer in (('request_payload', requests[sequence]), ('output_payload', results[sequence])):
                ref = response[field]
                path = broker.root / ref['path']
                raw = path.read_bytes()
                assert path.stat().st_mode & 0o777 == 0o600 and path.stat().st_nlink == 1
                assert ref['producer_event'] == producer['event'] and ref['sequence'] == sequence
                assert ref['source_kind'] == 'actual_hardware_transfer' and ref['model_instance'] == MAILBOX['nonce']
                assert ref['origin'] == response['origin'] and ref['writeback_verified'] is True
                assert hashlib.sha256(raw).hexdigest() == ref['sha256'] == ref['writeback_sha256']
                assert b.fnv64(raw) == ref['fnv1a64'] and len(raw) == ref['bytes']
        raw_output = b''.join((broker.root / item['output_payload']['path']).read_bytes()
                              for item in results.values() if item['token'] == token)
        assert raw_output == destination
        release = responses[-1]
        release_args = (broker.root / release['request_payload']['path']).read_bytes()
        assert struct.unpack('<QQ', release_args) == (token, b.fnv64(destination))
        assert release['result_transfer']['status'] == 'released' and release['result_transfer']['complete'] is True
        assert release['result_transfer']['reconstructed_bytes'] == total
        assert release['result_transfer']['fnv1a64'] == b.fnv64(destination)
        assert release['result_transfer']['sha256'] == hashlib.sha256(destination).hexdigest()
        frames = [item for item in receipts if item['kind'] == 'model_frame']
        assert [(item['sequence'], item['opcode']) for item in frames] == [(1, b.INIT), (2, b.STILL)]
        assert frames[-1]['proof']['result_fnv1a64'] == b.fnv64(destination)
        for item in requests.values():
            if item['opcode'] == b.READ_RESULT:
                raw = (broker.root / item['request_payload']['path']).read_bytes()
                actual_token, cursor, capacity, zero = struct.unpack('<QQII', raw)
                assert (actual_token, cursor, capacity, zero) == (token, results[item['sequence']]['offset'], 256, 0)
    finally:
        broker.core.destroy_model()
        broker.detach_mailbox()
        broker.core.close()
    assert memory.detached and memory.after_ack_accesses == 0


def test_actual_negative_core_call_retains_exact_input_and_empty_output(actual_core_library, wire, monkeypatch):
    library, digest = actual_core_library
    memory, rsp, _ = wire
    broker = component(memory, rsp, monkeypatch)
    broker.core = b.Core(library, digest)
    try:
        initial = header(op=b.INIT, capacity=128)
        memory.logical(0, b.HEADER, initial)
        code, raw, result = broker.call_core(initial, b'', 128)
        assert code == 0 and broker.publish(initial, raw, code, result)
        proof = broker.core.proof_snapshot()
        invalid = struct.pack('<IIIIIIQQII', 128, 64, 30, 0, 400, 100, 2500, 1000000, 0, 0)
        request = header(seq=2, op=b.CONFIGURE, data=invalid, capacity=128)
        memory.logical(0, b.HEADER, request)
        memory.logical(b.HEADER, len(invalid), invalid)
        code, raw, result = broker.call_core(request, invalid, 128)
        assert code == -errno.ERANGE and raw == b'' and not any((result.token, result.total, result.offset, result.used))
        assert broker.publish(request, raw, code, result)
        events = [json.loads(line) for line in broker.events.getvalue().splitlines()]
        response = [item for item in events if item['kind'] == 'response'][-1]
        assert response['actual_c_result'] == -errno.ERANGE and response['returned_bytes'] == 0
        assert (broker.root / response['request_payload']['path']).read_bytes() == invalid
        assert (broker.root / response['output_payload']['path']).read_bytes() == b''
        assert response['result_transfer'] is None and broker.core.proof_snapshot() == proof
        assert len([item for item in events if item['kind'] == 'model_frame']) == 1
    finally:
        broker.core.destroy_model()
        broker.detach_mailbox()
        broker.core.close()


def parameter_bank_input(library, *, fps=30, cookie=0x80000061):
    class Slot(ctypes.Structure):
        _fields_ = [(name, ctypes.c_uint16) for name in ('opcode', 'offset', 'size')]
    slots = (Slot * b.CP_PARAMETER_BANK_SLOTS).in_dll(library, 'cp_parameter_batch_slots')
    raw = bytearray((i * 73 + i // 29 + 19) % 256 for i in range(b.CP_PARAMETER_BANK_BYTES))
    raw[0] = 5
    struct.pack_into('<HI', raw, 2, 0x4063, cookie)
    for slot in slots:
        raw[slot.offset] = 5
        struct.pack_into('<H', raw, slot.offset + 2, slot.opcode)
    struct.pack_into('<I', raw, b.CP_PARAMETER_FPS_AT, fps)
    return bytes(raw)


def parameter_bank_header(seq, data, *, op=b.CP_PARAMETER_BANK, capacity=b.CP_PARAMETER_BANK_RESULT_BYTES):
    raw = bytearray(header(seq=seq, op=op, data=data if op == b.CP_PARAMETER_BANK else b'', capacity=capacity))
    struct.pack_into('<4I', raw, 100, 0x80020002, 0x90030001, 0x4063, b.CP_PARAMETER_BANK_BYTES)
    struct.pack_into('<Q', raw, 120, b.fnv64(data))
    return bytes(raw)


@pytest.mark.parametrize('field,value', [(100, 0x80020003), (104, 0x90030002), (108, 0x4064), (112, 2563),
                                        (120, 0), (40, 2755), (52, 1)])
def test_bank_wire_origin_rejection_and_state_origin_keeps_old_api(actual_core_library, field, value):
    library, digest = actual_core_library
    core = b.Core(library, digest)
    try:
        data = parameter_bank_input(core.library)
        raw = bytearray(parameter_bank_header(1, data))
        struct.pack_into('<Q' if field == 120 else '<I', raw, field, value)
        with pytest.raises(ValueError):
            b.validate_request(bytes(raw), data, MAILBOX, 0)
        bank_state = parameter_bank_header(1, data, op=b.STATE, capacity=128)
        assert b.validate_request(bank_state, b'', MAILBOX, 0) == (b.STATE, 128)
        assert b.validate_request(header(op=b.STATE, capacity=128), b'', MAILBOX, 0) == (b.STATE, 128)
        assert b.AP_SOURCE_SNAPSHOT == 11 and b.CP_PARAMETER_BANK == 20
    finally:
        core.close()


def test_actual_bank_transfer_retains_all_bytes_and_has_no_frame_or_source_receipt(actual_core_library, wire, monkeypatch):
    library, digest = actual_core_library
    memory, rsp, _ = wire
    broker = component(memory, rsp, monkeypatch)
    broker.core = b.Core(library, digest)

    def execute(op, data=b'', capacity=128, native=None):
        sequence = broker.sequence + 1
        request = parameter_bank_header(sequence, native or data, op=op, capacity=capacity) if native is not None or op == b.CP_PARAMETER_BANK else header(
            seq=sequence, op=op, data=data, capacity=capacity)
        memory.logical(0, len(request), request)
        if data:
            memory.logical(b.HEADER, len(data), data)
        actual_request, actual_input = broker.fetch()
        code, output, result = broker.call_core(actual_request, actual_input, capacity)
        assert broker.publish(actual_request, output, code, result)
        assert memory.logical(b.HEADER, len(output)) == output
        return code, output, result

    try:
        assert execute(b.INIT)[0] == 0
        settings = struct.pack('<6I2Q2I', 640, 480, 30, 13, 800, 640, 8642, 2**64 - 1, 0, 0)
        for _ in range(21):
            assert execute(b.CONFIGURE, settings)[0] == 0
        # The independent pre-query must use live generation22 rather than any older control cache.
        proof = broker.core.proof_snapshot()
        for count in range(1, 4):
            data = parameter_bank_input(broker.core.library, fps=30, cookie=0x80000060 + count)
            assert execute(b.STATE, native=data)[0] == 0
            broker.core.configuration_fingerprint = 0  # HOST stale cache must never substitute for live C STATE.
            code, output, result = execute(b.CP_PARAMETER_BANK, data, 2756)
            assert code == 0 and result.used == 2756 and not result.token
            assert output[192:] == data and b.u64(output, 16) == count and b.u64(output, 24) == 21 + count
            assert b.u64(output, 32) == 22 + count and b.u32(output, 48) == 30
            assert execute(b.STATE, native=data)[1] == output[64:192]
            assert broker.core.proof_snapshot() == proof
        events = [json.loads(line) for line in broker.events.getvalue().splitlines()]
        banks = [event for event in events if event['kind'] == 'model_parameter_bank']
        assert len(banks) == 3 and all(event['actual_core_sha256'] == digest and event['actual_c_result'] == 0 for event in banks)
        assert not any(event['kind'] == 'ap_source_result' for event in events)
        assert [(event['opcode']) for event in events if event['kind'] == 'model_frame'] == [b.INIT]
        for event in banks:
            observation = event['observation']
            actual_input = (broker.root / event['request_payload']['path']).read_bytes()
            actual_output = (broker.root / event['output_payload']['path']).read_bytes()
            assert len(actual_input) == 2564 and len(actual_output) == 2756 and actual_output[192:] == actual_input
            assert observation['query_c_result'] == observation['after_state_c_result'] == observation['actual_c_result'] == 0
            assert observation['readback_verified'] is True
            assert bytes.fromhex(observation['snapshot_hex']) == bytes.fromhex(observation['returned_hex']) == actual_output
            assert bytes.fromhex(observation['after_state_hex']) == actual_output[64:192]
            assert b.u64(bytes.fromhex(observation['before_state_hex']), 56) == b.u64(actual_output, 24)
        bad = bytearray(data)
        bad[8] ^= 1
        code, output, result = execute(b.CP_PARAMETER_BANK, bytes(bad), 2756)
        assert code == -errno.EPROTO and output == b'' and result.used == 0 and broker.core.proof_snapshot() == proof
        events = [json.loads(line) for line in broker.events.getvalue().splitlines()]
        rejected = [event for event in events if event['kind'] == 'core_result'][-1]
        assert rejected['actual_c_result'] == -errno.EPROTO and rejected['actual_core_sha256'] == digest
        assert (broker.root / rejected['request_payload']['path']).read_bytes() == bytes(bad)
        assert (broker.root / rejected['output_payload']['path']).read_bytes() == b''
    finally:
        broker.core.destroy_model()
        broker.detach_mailbox()
        broker.core.close()


@pytest.mark.parametrize('owner', ['source', 'retained-result'])
def test_bank_never_enters_source_provider_or_core_with_an_existing_broker_lease(actual_core_library, wire, monkeypatch, owner):
    library, digest = actual_core_library
    memory, rsp, _ = wire
    broker = component(memory, rsp, monkeypatch)
    broker.core = b.Core(library, digest)
    try:
        request = header(op=b.INIT, capacity=128)
        memory.logical(0, b.HEADER, request)
        code, output, result = broker.call_core(request, b'', 128)
        assert code == 0 and broker.publish(request, output, code, result)
        source = broker.source()
        if owner == 'source':
            source.active = object()  # HOST-owned lease sentinel; no original source bytes are claimed.
        else:
            broker.transfer = dict(token=77, total=1, cursor=0)
        proof = broker.core.proof_snapshot()
        def uncalled(*args):
            raise AssertionError('Bank admission must reject before a C request')
        monkeypatch.setattr(broker.core, 'execute', uncalled)
        monkeypatch.setattr(broker, 'call_source', uncalled)
        data = parameter_bank_input(broker.core.library)
        request = parameter_bank_header(2, data)
        memory.logical(0, b.HEADER, request)
        memory.logical(b.HEADER, len(data), data)
        code, output, result = broker.call_core(request, data, 2756)
        assert code == -errno.EBUSY and output == b'' and result.used == 0
        assert broker.publish(request, output, code, result) and broker.core.proof_snapshot() == proof
        events = [json.loads(line) for line in broker.events.getvalue().splitlines()]
        rejected = [event for event in events if event['kind'] == 'core_result'][-1]
        assert rejected['actual_c_result'] is None and rejected['admission_error'] == -errno.EBUSY
        assert not any(event['kind'] in ('model_parameter_bank', 'ap_source_result') for event in events)
        assert source.active is not None if owner == 'source' else broker.transfer['token'] == 77
    finally:
        broker.source().active = None
        broker.transfer = None
        broker.core.destroy_model()
        broker.detach_mailbox()
        broker.core.close()


@pytest.mark.parametrize('failure', ['query-error', 'query-last-byte', 'after-state'])
def test_bank_independent_readback_failure_retains_actual_c_output(actual_core_library, wire, monkeypatch, failure):
    library, digest = actual_core_library
    memory, rsp, _ = wire
    broker = component(memory, rsp, monkeypatch)
    broker.core = b.Core(library, digest)
    try:
        request = header(op=b.INIT, capacity=128)
        memory.logical(0, b.HEADER, request)
        code, output, result = broker.call_core(request, b'', 128)
        assert code == 0 and broker.publish(request, output, code, result)
        proof = broker.core.proof_snapshot()
        original_query = broker.core.library.fcam_model_cp_parameter_bank_snapshot
        original_execute = broker.core.execute
        def query(model, generation, output, size):
            code = original_query(model, generation, output, size)
            if failure == 'query-error':
                return -errno.EIO
            if failure == 'query-last-byte':
                ctypes.cast(output, ctypes.POINTER(ctypes.c_uint8))[size - 1] ^= 1
            return code
        if failure == 'after-state':
            state_calls = 0
            def changed_state(instance, op, incoming, capacity):
                nonlocal state_calls
                code, data, result = original_execute(instance, op, incoming, capacity)
                if op == b.STATE:
                    state_calls += 1
                    if state_calls == 2:
                        data = data[:-1] + bytes([data[-1] ^ 1])
                return code, data, result
            monkeypatch.setattr(broker.core, 'execute', changed_state)
        else:
            monkeypatch.setattr(broker.core.library, 'fcam_model_cp_parameter_bank_snapshot', query)
        data = parameter_bank_input(broker.core.library)
        request = parameter_bank_header(2, data)
        memory.logical(0, b.HEADER, request)
        memory.logical(b.HEADER, len(data), data)
        with pytest.raises(ValueError, match='query differs|after-State128'):
            broker.call_core(request, data, 2756)
        events = [json.loads(line) for line in broker.events.getvalue().splitlines()]
        rejected = [event for event in events if event['kind'] == 'parameter_bank_rejected'][-1]
        assert rejected['actual_c_result'] == 0 and rejected['actual_core_sha256'] == digest
        assert (broker.root / rejected['request_payload']['path']).read_bytes() == data
        actual_output = (broker.root / rejected['output_payload']['path']).read_bytes()
        assert len(actual_output) == 2756 and actual_output[192:] == data
        assert bytes.fromhex(rejected['observation']['returned_hex']) == actual_output
        assert rejected['observation']['readback_verified'] is False
        assert not any(event.get('sequence') == 2 and event['kind'] in ('response', 'model_parameter_bank', 'model_frame') for event in events)
        assert broker.pending_payloads is None and broker.core.proof_snapshot() == proof
    finally:
        broker.core.destroy_model()
        broker.detach_mailbox()
        broker.core.close()


def ou_crank_input(*, opaque=0, cookie=0x80000061):
    return struct.pack('<BBHII',5,opaque,0x4072,cookie,0)


def ou_crank_header(seq, data, *, capacity=224):
    raw = bytearray(header(seq=seq,op=b.CP_OU_CRANK_CONTROL,data=data,capacity=capacity))
    struct.pack_into('<4I',raw,100,0x80020002,0x90030001,0x4072,len(data))
    struct.pack_into('<Q',raw,120,b.fnv64(data))
    return bytes(raw)


def ou_broker_execute(broker, memory, op, data=b'', capacity=128):
    if op not in (b.CP_OU_CRANK_CONTROL,b.STARTUP_CONTROL):
        return movie_broker_execute(broker,memory,op,data,capacity)
    request = ou_crank_header(broker.sequence+1,data,capacity=capacity) if op == b.CP_OU_CRANK_CONTROL else bytearray(
        header(seq=broker.sequence+1,op=op,data=data,capacity=capacity))
    if op == b.STARTUP_CONTROL:
        struct.pack_into('<4I',request,100,0x80020002,0x90030001,0x4057,12)
        struct.pack_into('<Q',request,120,b.fnv64(data))
        request = bytes(request)
    memory.logical(0,b.HEADER,request); memory.logical(b.HEADER,len(data),data)
    actual_request, actual_input = broker.fetch()
    code, output, result = broker.call_core(actual_request,actual_input,capacity)
    assert broker.publish(actual_request,output,code,result)
    assert memory.logical(b.HEADER,len(output)) == output
    return code, output, result


def ou_settings_predecessor(broker, memory):
    state_bytes = ou_broker_execute(broker,memory,b.STATE)[1]
    data = struct.pack('<HH',0x4057,4) + bytes(20) + struct.pack('<Q',b.fnv64(state_bytes[8:48]))
    assert ou_broker_execute(broker,memory,b.STARTUP_CONTROL,data,192)[0] == 0


def ou_predecessors(broker, memory, *, fps=30, cookie=0x80000061):
    route = b'\x01\x05\x05' + bytes(13)
    if broker.core.vdf_route != route:
        assert ou_broker_execute(broker,memory,b.VDF_PATH,route,160)[0] == 0
    movie_predecessors(broker,memory,fps=fps,cookie=cookie)
    assert ou_broker_execute(broker,memory,b.CP_MOVIE_FORMAT,movie_format_input(),240)[0] == 0
    ou_settings_predecessor(broker,memory)


def test_ou_wire_exact12_origin_flags_body_and_capacity():
    data = ou_crank_input()
    assert data.hex() == '050072406100008000000000'
    assert b.validate_request(ou_crank_header(1,data),data,MAILBOX,0) == (23,224)
    for field,value in ((100,0x80020003),(104,0x90030002),(108,0x4073),(112,11),(120,0),(40,223),(52,1)):
        request = bytearray(ou_crank_header(1,data))
        struct.pack_into('<Q' if field == 120 else '<I',request,field,value)
        with pytest.raises(ValueError):
            b.validate_request(bytes(request),data,MAILBOX,0)
    for size in (0,11,13):
        raw = (data+b'\0')[:size]
        with pytest.raises(ValueError):
            b.validate_request(ou_crank_header(1,raw),raw,MAILBOX,0)
    for offset in (0,2,3,8,9,10,11):
        raw = bytearray(data); raw[offset] ^= 1
        with pytest.raises(ValueError):
            b.validate_request(ou_crank_header(1,raw),bytes(raw),MAILBOX,0)
    opaque = ou_crank_input(opaque=0xef,cookie=0xfedcba98)
    assert b.validate_request(ou_crank_header(1,opaque),opaque,MAILBOX,0) == (23,224)
    assert (b.AP_SOURCE_SNAPSHOT,b.CP_PARAMETER_BANK,b.CP_CRANK_CONTROL,b.CP_MOVIE_FORMAT) == (11,20,21,22)


def test_actual_ou224_broker_live_state_independent_query_and_opaque_input(crank_broker,monkeypatch):
    broker,memory,digest = crank_broker
    monkeypatch.setattr(broker,'call_source',lambda *args: pytest.fail('OU cannot borrow OP11'))
    assert broker.core.library.fcam_model_cp_ou_crank_snapshot.argtypes == [ctypes.c_void_p,ctypes.c_uint64,
        ctypes.c_uint64,ctypes.c_uint64,ctypes.c_uint64,ctypes.c_void_p,ctypes.c_size_t]
    assert broker.core.library.fcam_model_cp_ou_crank_snapshot.restype == ctypes.c_int
    for generation,fps in enumerate((30,60),1):
        ou_predecessors(broker,memory,fps=fps,cookie=0x80000060+generation)
        histories = tuple(dict(getattr(broker.core,key)) for key in
            ('parameter_bank_observation','crank_control_observation','movie_format_observation'))
        before = ou_broker_execute(broker,memory,b.STATE)[1]
        proof = broker.core.proof_snapshot()
        assert proof['opcode'] == 14 and proof['config_generation'] == b.u64(before,56)
        data = ou_crank_input() if generation == 1 else ou_crank_input(opaque=0xef,cookie=0xfedcba98)
        code,receipt,result = ou_broker_execute(broker,memory,23,data,b.DATA)
        expected = bytearray(before); struct.pack_into('<Q',expected,56,b.u64(before,56)+1)
        assert code == 0 and result.used == 224 and not (result.token or result.total or result.offset)
        assert struct.unpack_from('<II8Q2I',receipt) == (1,224,MAILBOX['nonce'],generation,generation,generation,generation,
            b.u64(before,56),b.u64(before,56)+1,b.fnv64(data),0,fps)
        assert receipt[80:208] == bytes(expected) == ou_broker_execute(broker,memory,b.STATE)[1]
        assert receipt[208:220] == data and receipt[220:] == bytes(4) and broker.core.proof_snapshot() == proof
        assert histories == tuple(getattr(broker.core,key) for key in
            ('parameter_bank_observation','crank_control_observation','movie_format_observation'))
        query = ctypes.create_string_buffer(224)
        assert broker.core.library.fcam_model_cp_ou_crank_snapshot(broker.core.model,generation,generation,generation,generation,query,224) == 0
        assert query.raw == receipt
        code,output,_ = ou_broker_execute(broker,memory,23,ou_crank_input(opaque=0x7f,cookie=0x87654321),224)
        assert code == -errno.ESTALE and not output
    events = [json.loads(line) for line in broker.events.getvalue().splitlines()]
    witnesses = [event for event in events if event['kind'] == 'model_ou_crank_control']
    assert len(witnesses) == 2 and not any(event['kind'] == 'ap_source_result' for event in events)
    assert not any(event['kind'] == 'model_frame' and event['opcode'] == 23 for event in events)
    decoder_spec = importlib.util.spec_from_file_location('actual_ou_formal_decoder',
        REPORT / 'functional-camera-evidence/check_evidence.py')
    decoder = importlib.util.module_from_spec(decoder_spec)
    decoder_spec.loader.exec_module(decoder)
    for event in witnesses:
        observed = event['observation']; source = (broker.root/event['request_payload']['path']).read_bytes()
        output = (broker.root/event['output_payload']['path']).read_bytes()
        assert event['actual_c_result'] == 0 and event['actual_core_sha256'] == digest and event['native_acceptance'] is False
        assert event['model_called'] is event['model_committed'] is True and event['validation_error'] is None
        assert observed['actual_c_result'] == observed['query_c_result'] == observed['before_state_c_result'] == observed['after_state_c_result'] == 0
        assert observed['readback_verified'] is True and observed['predecessor_proof']['opcode'] == 14
        assert bytes.fromhex(observed['returned_hex']) == bytes.fromhex(observed['snapshot_hex']) == output
        assert bytes.fromhex(observed['output_buffer_hex']) == output + bytes(b.DATA-224)
        assert observed['request_hex'] == source.hex() and output[208:220] == source
        assert bytes.fromhex(observed['after_state_hex']) == output[80:208]
        value = decoder.cp_ou_crank_control_observation(observed, output, source, MAILBOX['nonce'],
            bytes.fromhex(observed['before_state_hex']), observed['bank_generation'],
            observed['crank_generation'], observed['movie_generation'], b.DATA)
        assert value['config_generation'] == b.u64(output, 56) and value['ou_generation'] == b.u64(output, 16)
        with pytest.raises(ValueError, match='independent actual C'):
            decoder.cp_ou_crank_control_observation(dict(observed, state_delta_verified=False), output,
                source, MAILBOX['nonce'], bytes.fromhex(observed['before_state_hex']),
                observed['bank_generation'], observed['crank_generation'], observed['movie_generation'], b.DATA)


def test_actual_ou_requires_just_completed4057_at_current_generation(crank_broker):
    broker,memory,_ = crank_broker
    route = b'\x01\x05\x05' + bytes(13)
    assert ou_broker_execute(broker,memory,b.VDF_PATH,route,160)[0] == 0
    movie_predecessors(broker,memory)
    assert ou_broker_execute(broker,memory,22,movie_format_input(),240)[0] == 0
    assert ou_broker_execute(broker,memory,23,ou_crank_input(),224)[0] == -errno.ENODATA
    ou_settings_predecessor(broker,memory)
    state_bytes = ou_broker_execute(broker,memory,b.STATE)[1]
    assert ou_broker_execute(broker,memory,b.CONFIGURE,state_bytes[8:48]+bytes(8))[0] == 0
    before = ou_broker_execute(broker,memory,b.STATE)[1]
    assert ou_broker_execute(broker,memory,23,ou_crank_input(),224)[0] == -errno.ESTALE
    assert ou_broker_execute(broker,memory,b.STATE)[1] == before
    ou_settings_predecessor(broker,memory)
    assert ou_broker_execute(broker,memory,23,ou_crank_input(),224)[0] == 0


@pytest.mark.parametrize('owner',('source','retained-result'))
def test_ou_admission_keeps_current_broker_owners(crank_broker,monkeypatch,owner):
    broker,memory,_ = crank_broker
    ou_predecessors(broker,memory)
    if owner == 'source': broker.source().active = object()
    else: broker.transfer = dict(token=77,total=1,cursor=0)
    def uncalled(*args): pytest.fail('OU admission must precede actual C/source call')
    monkeypatch.setattr(broker.core,'execute',uncalled); monkeypatch.setattr(broker,'call_source',uncalled)
    code,output,result = ou_broker_execute(broker,memory,23,ou_crank_input(),224)
    assert code == -errno.EBUSY and not output and not result.used
    event = [json.loads(line) for line in broker.events.getvalue().splitlines() if json.loads(line)['kind'] == 'ou_crank_control_rejected'][-1]
    assert event['actual_c_result'] is None and event['admission_error'] == -errno.EBUSY
    assert event['model_called'] is event['model_committed'] is False
    assert broker.source().active is not None if owner == 'source' else broker.transfer['token'] == 77


@pytest.mark.parametrize('failure',('query-error','query-last-byte','query-exception','returned-cookie','after-state','empty-C0'))
def test_ou_postvalidation_preserves_actual_c0_buffer_and_query(crank_broker,monkeypatch,failure):
    broker,memory,digest = crank_broker
    ou_predecessors(broker,memory)
    original_query = broker.core.library.fcam_model_cp_ou_crank_snapshot
    original_request,original_execute = broker.core.library.fcam_model_request,broker.core.execute
    if failure.startswith('query-'):
        def query(model,ou,bank,crank,movie,output,size):
            code = original_query(model,ou,bank,crank,movie,output,size)
            if failure == 'query-error': return -errno.EIO
            ctypes.cast(output,ctypes.POINTER(ctypes.c_uint8))[size-1] ^= 1
            if failure == 'query-exception': raise ValueError('OU independent query exception after actual readback')
            return code
        monkeypatch.setattr(broker.core.library,'fcam_model_cp_ou_crank_snapshot',query)
    elif failure == 'after-state':
        calls = 0
        def state(instance,op,data,capacity):
            nonlocal calls
            code,output,result = original_execute(instance,op,data,capacity)
            if op == b.STATE:
                calls += 1
                if calls == 2: output = output[:-1] + bytes([output[-1]^1])
            return code,output,result
        monkeypatch.setattr(broker.core,'execute',state)
    else:
        def changed(model,op,data,size,output,capacity,result):
            if failure == 'empty-C0' and op == 23: return 0
            code = original_request(model,op,data,size,output,capacity,result)
            if op == 23 and code == 0: ctypes.cast(output,ctypes.POINTER(ctypes.c_uint8))[212] ^= 1
            return code
        monkeypatch.setattr(broker.core.library,'fcam_model_request',changed)
    data = ou_crank_input(); request = ou_crank_header(broker.sequence+1,data,capacity=b.DATA)
    memory.logical(0,b.HEADER,request); memory.logical(b.HEADER,12,data)
    with pytest.raises(ValueError,match='OU|ou'):
        broker.call_core(request,data,b.DATA)
    event = [json.loads(line) for line in broker.events.getvalue().splitlines() if json.loads(line)['kind'] == 'ou_crank_control_rejected'][-1]
    observed = event['observation']; actual = (broker.root/event['output_payload']['path']).read_bytes()
    assert event['actual_c_result'] == 0 and event['actual_core_sha256'] == digest and event['validation_error']
    assert event['model_called'] is True and observed['c_call_succeeded'] is True and observed['readback_verified'] is False
    assert len(bytes.fromhex(observed['output_buffer_hex'])) == b.DATA
    assert len(bytes.fromhex(observed['snapshot_hex'])) == 224
    assert (broker.root/event['request_payload']['path']).read_bytes() == data
    assert actual.hex() == observed['returned_hex'] and broker.pending_payloads is None
    if failure == 'empty-C0':
        assert not event['model_committed'] and not actual and observed['query_c_result'] == -errno.ENODATA
    else:
        assert len(actual) == 224 and event['model_committed'] is True
        assert observed['state_delta_verified'] is (failure != 'after-state')
    assert not any(json.loads(line)['kind'] == 'model_ou_crank_control' for line in broker.events.getvalue().splitlines())


def movie_format_input(*, opaque=0xa7, cookie=0x80aa5560, opaque11=0xb3, opaque19=0xc4):
    return struct.pack('<BBHI4BI4B', 5, opaque, 0x4000, cookie, 5, 1, 0, opaque11, 0, 0, 0, 1, opaque19)


def movie_format_header(seq, data, *, capacity=240):
    raw = bytearray(header(seq=seq, op=b.CP_MOVIE_FORMAT, data=data, capacity=capacity))
    struct.pack_into('<4I', raw, 100, 0x80020002, 0x90030001, 0x4000, len(data))
    struct.pack_into('<Q', raw, 120, b.fnv64(data))
    return bytes(raw)


def movie_broker_execute(broker, memory, op, data=b'', capacity=128):
    if op != b.CP_MOVIE_FORMAT:
        return crank_broker_execute(broker,memory,op,data,capacity)
    request = movie_format_header(broker.sequence+1,data,capacity=capacity)
    memory.logical(0,b.HEADER,request)
    memory.logical(b.HEADER,len(data),data)
    actual_request, actual_input = broker.fetch()
    code, output, result = broker.call_core(actual_request,actual_input,capacity)
    assert broker.publish(actual_request,output,code,result)
    return code, output, result


def movie_predecessors(broker, memory, *, fps=30, cookie=0x80000061):
    bank = parameter_bank_input(broker.core.library,fps=fps,cookie=cookie)
    assert crank_broker_execute(broker,memory,b.CP_PARAMETER_BANK,bank,2756)[0] == 0
    assert crank_broker_execute(broker,memory,b.CP_CRANK_CONTROL,crank_control_input(),208)[0] == 0


@pytest.mark.parametrize('field,value', [(100,0x80020003),(104,0x90030002),(108,0x4001),(112,19),(120,0),(40,239),(52,1)])
def test_movie_wire_requires_exact_origin_capacity_and_flag(field,value):
    data = movie_format_input()
    request = bytearray(movie_format_header(1,data))
    struct.pack_into('<Q' if field == 120 else '<I',request,field,value)
    with pytest.raises(ValueError):
        b.validate_request(bytes(request),data,MAILBOX,0)
    assert b.CP_MOVIE_FORMAT == 22 and b.CP_CRANK_CONTROL == 21 and b.AP_SOURCE_SNAPSHOT == 11


@pytest.mark.parametrize('offset', [0,2,3,8,9,10,12,13,14,15,16,17,18])
def test_movie_wire_rejects_each_known_selector_change(offset):
    data = bytearray(movie_format_input()); data[offset] ^= 1
    with pytest.raises(ValueError):
        b.validate_request(movie_format_header(1,data),bytes(data),MAILBOX,0)


@pytest.mark.parametrize('size', [0,19,21])
def test_movie_wire_rejects_nonexact_input(size):
    data = (movie_format_input()+b'\0')[:size]
    with pytest.raises(ValueError):
        b.validate_request(movie_format_header(1,data),data,MAILBOX,0)


def test_actual_movie_broker_records_live_state_and_preserves_predecessor_histories(crank_broker,monkeypatch):
    broker,memory,digest = crank_broker
    execute = lambda op,data=b'',capacity=128: movie_broker_execute(broker,memory,op,data,capacity)
    settings = struct.pack('<6I2Q2I',128,64,30,13,800,640,8642,2**64-1,0,0)
    assert execute(b.CONFIGURE,settings)[0] == 0
    proof = broker.core.proof_snapshot()
    monkeypatch.setattr(broker,'call_source',lambda *args: pytest.fail('Movie format cannot borrow source11'))
    for generation,fps in enumerate((30,60,30),1):
        movie_predecessors(broker,memory,fps=fps,cookie=0x80000060+generation)
        bank_observation,crank_observation = dict(broker.core.parameter_bank_observation),dict(broker.core.crank_control_observation)
        # Advance live state after OP21 so a historical crank receipt cannot substitute.
        changed = bytearray(settings); struct.pack_into('<I',changed,8,fps); struct.pack_into('<I',changed,12,70+generation)
        assert execute(b.CONFIGURE,bytes(changed))[0] == 0
        before = execute(b.STATE)[1]
        data = movie_format_input(opaque=0xa0+generation,cookie=0xfedcba00+generation,opaque11=generation,opaque19=255-generation)
        code,receipt,result = execute(b.CP_MOVIE_FORMAT,data,240)
        expected = bytearray(before); struct.pack_into('<Q',expected,56,b.u64(before,56)+1)
        assert code == 0 and result.used == 240 and not (result.token or result.total or result.offset)
        assert struct.unpack_from('<II7Q4I',receipt) == (1,240,MAILBOX['nonce'],generation,generation,generation,
            b.u64(before,56),b.u64(before,56)+1,b.fnv64(data),5,0,fps,1)
        assert receipt[80:208] == bytes(expected) == execute(b.STATE)[1] and receipt[208:228] == data and receipt[228:] == bytes(12)
        assert broker.core.proof_snapshot() == proof
        assert broker.core.parameter_bank_observation == bank_observation and broker.core.crank_control_observation == crank_observation
        code,output,_ = execute(b.CP_MOVIE_FORMAT,movie_format_input(),240)
        assert code == -errno.ESTALE and not output
    events = [json.loads(line) for line in broker.events.getvalue().splitlines()]
    witnesses = [event for event in events if event['kind'] == 'model_movie_format']
    assert len(witnesses) == 3 and not any(event['kind'] == 'ap_source_result' for event in events)
    assert [event['opcode'] for event in events if event['kind'] == 'model_frame'] == [b.INIT]
    for event in witnesses:
        observed = event['observation']
        source = (broker.root/event['request_payload']['path']).read_bytes()
        destination = (broker.root/event['output_payload']['path']).read_bytes()
        assert len(source) == 20 and len(destination) == 240 and destination[208:228] == source
        assert event['opcode'] == 22 and event['actual_core_sha256'] == digest and event['actual_c_result'] == 0
        assert event['origin']['command'] == 0x4000 and event['origin']['bytes'] == 20 and event['origin']['fnv1a64'] == b.fnv64(source)
        assert event['input_hex'] == source.hex() and event['request_fnv1a64'] == b.fnv64(source)
        assert event['model_called'] is event['model_committed'] is True and event['native_acceptance'] is False
        assert observed['actual_c_result'] == observed['query_c_result'] == observed['before_state_c_result'] == observed['after_state_c_result'] == 0
        assert observed['readback_verified'] is True
        assert bytes.fromhex(observed['returned_hex']) == bytes.fromhex(observed['snapshot_hex']) == destination
        assert bytes.fromhex(observed['output_buffer_hex']) == destination
        assert bytes.fromhex(observed['after_state_hex']) == destination[80:208]
    rejected = [event for event in events if event['kind'] == 'movie_format_rejected']
    assert len(rejected) == 3 and all(event['actual_c_result'] == -errno.ESTALE and not event['model_committed'] for event in rejected)


@pytest.mark.parametrize('owner',['source','retained-result'])
def test_movie_broker_admission_preserves_existing_owners(crank_broker,monkeypatch,owner):
    broker,memory,digest = crank_broker
    movie_predecessors(broker,memory)
    if owner == 'source': broker.source().active = object()
    else: broker.transfer = dict(token=77,total=1,cursor=0)
    def uncalled(*args): pytest.fail('Movie admission must precede C/source invocation')
    monkeypatch.setattr(broker.core,'execute',uncalled); monkeypatch.setattr(broker,'call_source',uncalled)
    code,output,result = movie_broker_execute(broker,memory,b.CP_MOVIE_FORMAT,movie_format_input(),240)
    assert code == -errno.EBUSY and not output and not result.used
    event = [json.loads(line) for line in broker.events.getvalue().splitlines() if json.loads(line)['kind'] == 'movie_format_rejected'][-1]
    assert event['actual_c_result'] is None and event['admission_error'] == -errno.EBUSY and event['actual_core_sha256'] == digest
    assert event['model_called'] is event['model_committed'] is False and len(bytes.fromhex(event['input_hex'])) == 20
    assert broker.source().active is not None if owner == 'source' else broker.transfer['token'] == 77


@pytest.mark.parametrize('failure',['query-error','query-last-byte','query-exception','after-state','proof-readback',
    'returned-instance','returned-movie','returned-bank','returned-crank','returned-before','returned-after',
    'returned-fnv','returned-format','returned-rate','returned-fps','returned-codec','returned-state','returned-opaque11','returned-opaque19','returned-reserved'])
def test_movie_postvalidation_keeps_actual_c_commit_and_original_bytes(crank_broker,monkeypatch,failure):
    broker,memory,digest = crank_broker
    movie_predecessors(broker,memory)
    original_query = broker.core.library.fcam_model_cp_movie_format_snapshot
    original_execute,original_request,original_proof = broker.core.execute,broker.core.library.fcam_model_request,broker.core.proof_snapshot
    proof = original_proof()
    if failure.startswith('query-'):
        def query(model,movie,bank,crank,output,size):
            code = original_query(model,movie,bank,crank,output,size)
            if failure == 'query-error': return -errno.EIO
            ctypes.cast(output,ctypes.POINTER(ctypes.c_uint8))[size-1] ^= 1
            if failure == 'query-exception': raise ValueError('Movie independent query exception after raw readback')
            return code
        monkeypatch.setattr(broker.core.library,'fcam_model_cp_movie_format_snapshot',query)
    elif failure == 'after-state':
        calls = 0
        def state(instance,op,data,capacity):
            nonlocal calls
            code,output,result = original_execute(instance,op,data,capacity)
            if op == b.STATE:
                calls += 1
                if calls == 2: output = output[:-1] + bytes([output[-1]^1])
            return code,output,result
        monkeypatch.setattr(broker.core,'execute',state)
    elif failure == 'proof-readback':
        monkeypatch.setattr(broker.core,'proof_snapshot',lambda: dict(original_proof(),serial=proof['serial']+1))
    else:
        offsets = dict(instance=8,movie=16,bank=24,crank=32,before=40,after=48,fnv=56,format=64,rate=68,fps=72,codec=76,
                       state=144,opaque11=219,opaque19=227,reserved=239)
        def changed(model,op,data,size,output,capacity,result):
            code = original_request(model,op,data,size,output,capacity,result)
            if op == b.CP_MOVIE_FORMAT and code == 0:
                ctypes.cast(output,ctypes.POINTER(ctypes.c_uint8))[offsets[failure.removeprefix('returned-')]] ^= 1
            return code
        monkeypatch.setattr(broker.core.library,'fcam_model_request',changed)
    data = movie_format_input(); sequence = broker.sequence+1
    request = movie_format_header(sequence,data)
    memory.logical(0,b.HEADER,request); memory.logical(b.HEADER,len(data),data)
    with pytest.raises(ValueError,match='movie|Movie'):
        broker.call_core(request,data,240)
    events = [json.loads(line) for line in broker.events.getvalue().splitlines()]
    rejected = [event for event in events if event['kind'] == 'movie_format_rejected'][-1]
    assert rejected['opcode'] == 22 and rejected['actual_c_result'] == 0 and rejected['actual_core_sha256'] == digest
    assert rejected['model_called'] is rejected['model_committed'] is True
    observed = rejected['observation']
    actual = (broker.root/rejected['output_payload']['path']).read_bytes()
    assert len(actual) == 240 and actual.hex() == observed['returned_hex'] == observed['output_buffer_hex']
    assert (broker.root/rejected['request_payload']['path']).read_bytes() == data
    assert len(bytes.fromhex(observed['before_state_hex'])) == len(bytes.fromhex(observed['after_state_hex'])) == 128
    assert len(bytes.fromhex(observed['snapshot_hex'])) == 240
    assert observed['readback_verified'] is (failure == 'proof-readback')
    assert broker.pending_payloads is None and original_proof() == proof
    assert not any(event.get('sequence') == sequence and event['kind'] in ('response','model_movie_format','model_frame','ap_source_result') for event in events)


def test_empty_zero_c_return_never_becomes_movie_commit(crank_broker,monkeypatch):
    broker,memory,_ = crank_broker
    movie_predecessors(broker,memory)
    original = broker.core.library.fcam_model_request
    def empty(model,op,data,size,output,capacity,result):
        return 0 if op == b.CP_MOVIE_FORMAT else original(model,op,data,size,output,capacity,result)
    monkeypatch.setattr(broker.core.library,'fcam_model_request',empty)
    data = movie_format_input(); request = movie_format_header(broker.sequence+1,data)
    memory.logical(0,b.HEADER,request); memory.logical(b.HEADER,len(data),data)
    with pytest.raises(ValueError,match='movie format receipt'):
        broker.call_core(request,data,240)
    event = [json.loads(line) for line in broker.events.getvalue().splitlines() if json.loads(line)['kind'] == 'movie_format_rejected'][-1]
    assert event['actual_c_result'] == 0 and event['model_called'] is True and event['model_committed'] is False
    assert event['observation']['query_c_result'] == -errno.ENODATA and not event['observation']['returned_hex']
    assert event['observation']['before_state_hex'] == event['observation']['after_state_hex']
    assert (broker.root/event['output_payload']['path']).read_bytes() == b''


def crank_control_input(*, opaque=0xa7, cookie=0x80aa5560):
    return struct.pack('<BBHII', 5, opaque, 0x409d, cookie, 0)


def crank_control_header(seq, data, *, op=b.CP_CRANK_CONTROL, capacity=b.CP_CRANK_RESULT_BYTES):
    raw = bytearray(header(seq=seq, op=op, data=data if op == b.CP_CRANK_CONTROL else b'', capacity=capacity))
    struct.pack_into('<4I', raw, 100, 0x80020002, 0x90030001, 0x409d, 12)
    struct.pack_into('<Q', raw, 120, b.fnv64(data))
    return bytes(raw)


def crank_broker_execute(broker, memory, op, data=b'', capacity=128, *, native=None):
    sequence = broker.sequence + 1
    if op == b.CP_CRANK_CONTROL or native is not None:
        request = crank_control_header(sequence, data if native is None else native, op=op, capacity=capacity)
    elif op == b.CP_PARAMETER_BANK:
        request = parameter_bank_header(sequence, data, capacity=capacity)
    else:
        request = header(seq=sequence, op=op, data=data, capacity=capacity)
    memory.logical(0, b.HEADER, request)
    if data:
        memory.logical(b.HEADER, len(data), data)
    actual_request, actual_input = broker.fetch()
    code, output, result = broker.call_core(actual_request, actual_input, capacity)
    assert broker.publish(actual_request, output, code, result)
    assert memory.logical(b.HEADER, len(output)) == output
    return code, output, result


@pytest.fixture
def crank_broker(actual_core_library, wire, monkeypatch):
    library, digest = actual_core_library
    memory, rsp, _ = wire
    broker = component(memory, rsp, monkeypatch)
    broker.core = b.Core(library, digest)
    try:
        assert crank_broker_execute(broker, memory, b.INIT)[0] == 0
        yield broker, memory, digest
    finally:
        broker.source().active = None
        broker.transfer = None
        broker.core.destroy_model()
        broker.detach_mailbox()
        broker.core.close()


@pytest.mark.parametrize('field,value', [(100, 0x80020003), (104, 0x90030002), (108, 0x409e), (112, 11),
                                        (120, 0), (40, 207), (52, 1)])
def test_crank_wire_requires_exact_original_origin_and_legacy_flag(field, value):
    data = crank_control_input()
    request = bytearray(crank_control_header(1, data))
    struct.pack_into('<Q' if field == 120 else '<I', request, field, value)
    with pytest.raises(ValueError):
        b.validate_request(bytes(request), data, MAILBOX, 0)
    assert b.validate_request(crank_control_header(1, data, op=b.STATE, capacity=128), b'', MAILBOX, 0) == (b.STATE, 128)
    assert b.AP_SOURCE_SNAPSHOT == 11 and b.CP_PARAMETER_BANK == 20 and b.CP_CRANK_CONTROL == 21


@pytest.mark.parametrize('offset', [0, 2, 3, 8, 9, 10, 11])
def test_crank_wire_rejects_malformed_type_command_and_nonzero_mode(offset):
    data = bytearray(crank_control_input())
    data[offset] ^= 1
    with pytest.raises(ValueError):
        b.validate_request(crank_control_header(1, data), bytes(data), MAILBOX, 0)


@pytest.mark.parametrize('size', [0, 11, 13])
def test_crank_wire_rejects_nonexact_size(size):
    data = (crank_control_input() + b'\0')[:size]
    with pytest.raises(ValueError):
        b.validate_request(crank_control_header(1, data), data, MAILBOX, 0)


def test_actual_crank_broker_keeps_both_histories_and_full_payloads(crank_broker, monkeypatch):
    broker, memory, digest = crank_broker
    settings = struct.pack('<6I2Q2I', 640, 480, 30, 13, 800, 640, 8642, 2**64 - 1, 0, 0)
    execute = lambda op, data=b'', capacity=128, **kw: crank_broker_execute(broker, memory, op, data, capacity, **kw)
    for _ in range(21):
        assert execute(b.CONFIGURE, settings)[0] == 0
    proof = broker.core.proof_snapshot()
    monkeypatch.setattr(broker, 'call_source', lambda *args: pytest.fail('Crank must never borrow source11'))
    for generation, fps in enumerate((30, 60, 30), 1):
        bank = parameter_bank_input(broker.core.library, fps=fps, cookie=0x80000060 + generation)
        assert execute(b.CP_PARAMETER_BANK, bank, 2756)[0] == 0
        bank_observation = dict(broker.core.parameter_bank_observation)
        request = crank_control_input(opaque=0xa0 + generation, cookie=0xfedcba00 + generation)
        before = execute(b.STATE, native=request)[1]
        broker.core.configuration_fingerprint = 0
        code, receipt, result = execute(b.CP_CRANK_CONTROL, request, 208)
        assert code == 0 and result.used == 208 and not (result.token or result.total or result.offset)
        expected = bytearray(before)
        struct.pack_into('<Q', expected, 56, b.u64(before, 56) + 1)
        assert receipt[64:192] == bytes(expected) == execute(b.STATE, native=request)[1]
        assert struct.unpack_from('<II6Q2I', receipt) == (1, 208, MAILBOX['nonce'], generation, generation,
            b.u64(before, 56), b.u64(before, 56) + 1, b.fnv64(request), 0, fps)
        assert receipt[192:204] == request and receipt[204:] == bytes(4)
        assert broker.core.proof_snapshot() == proof and broker.core.parameter_bank_observation == bank_observation
        historical = ctypes.create_string_buffer(2756)
        assert broker.core.library.fcam_model_cp_parameter_bank_snapshot(broker.core.model, generation, historical, 2756) == 0
        assert historical.raw.hex() == bank_observation['returned_hex']
        assert b.u64(historical.raw, 32) == b.u64(before, 56) < b.u64(receipt, 40)
        duplicate = crank_control_input(opaque=0xff, cookie=0x87654321)
        code, output, result = execute(b.CP_CRANK_CONTROL, duplicate, 208)
        assert code == -errno.ESTALE and output == b'' and not result.used
        assert broker.core.proof_snapshot() == proof
    events = [json.loads(line) for line in broker.events.getvalue().splitlines()]
    witnesses = [event for event in events if event['kind'] == 'model_crank_control']
    assert len(witnesses) == 3 and not any(event['kind'] == 'ap_source_result' for event in events)
    assert [event['opcode'] for event in events if event['kind'] == 'model_frame'] == [b.INIT]
    for event in witnesses:
        observation = event['observation']
        actual_input = (broker.root / event['request_payload']['path']).read_bytes()
        actual_output = (broker.root / event['output_payload']['path']).read_bytes()
        assert len(actual_input) == 12 and len(actual_output) == 208 and actual_output[192:204] == actual_input
        assert event['actual_c_result'] == 0 and event['actual_core_sha256'] == digest
        assert event['model_called'] is event['model_committed'] is True and event['native_acceptance'] is False
        assert event['origin']['source'] == 0x80020002 and event['origin']['destination'] == 0x90030001
        assert event['origin']['command'] == 0x409d and event['origin']['bytes'] == 12
        assert event['origin']['fnv1a64'] == b.fnv64(actual_input)
        assert observation['actual_c_result'] == observation['query_c_result'] == observation['before_state_c_result'] == observation['after_state_c_result'] == 0
        assert observation['readback_verified'] is True
        assert bytes.fromhex(observation['snapshot_hex']) == bytes.fromhex(observation['returned_hex']) == actual_output
        assert bytes.fromhex(observation['after_state_hex']) == actual_output[64:192]
        before = bytearray.fromhex(observation['before_state_hex'])
        assert len(before) == 128
        struct.pack_into('<Q', before, 56, b.u64(before, 56) + 1)
        assert bytes(before) == actual_output[64:192]
    rejections = [event for event in events if event['kind'] == 'crank_control_rejected']
    assert len(rejections) == 3 and all(event['actual_c_result'] == -errno.ESTALE for event in rejections)
    assert all(event['model_called'] is True and event['model_committed'] is False for event in rejections)


def test_actual_crank_no_bank_and_fps_mismatch_preserve_authorization(crank_broker):
    broker, memory, _ = crank_broker
    request = crank_control_input()
    execute = lambda op, data=b'', capacity=128: crank_broker_execute(broker, memory, op, data, capacity)
    assert execute(b.CP_CRANK_CONTROL, request, 208)[0] == -errno.ENODATA
    bank = parameter_bank_input(broker.core.library)
    assert execute(b.CP_PARAMETER_BANK, bank, 2756)[0] == 0
    wrong_fps = struct.pack('<6I2Q2I', 640, 480, 60, 13, 800, 640, 8642, 2**64 - 1, 0, 0)
    assert execute(b.CONFIGURE, wrong_fps)[0] == 0
    assert execute(b.CP_CRANK_CONTROL, request, 208)[0] == -errno.ESTALE
    restored = bytearray(wrong_fps)
    struct.pack_into('<I', restored, 8, 30)
    assert execute(b.CONFIGURE, bytes(restored))[0] == 0
    assert execute(b.CP_CRANK_CONTROL, request, 208)[0] == 0
    events = [json.loads(line) for line in broker.events.getvalue().splitlines()]
    rejections = [event for event in events if event['kind'] == 'crank_control_rejected']
    assert [event['actual_c_result'] for event in rejections] == [-errno.ENODATA, -errno.ESTALE]
    for event in rejections:
        assert event['observation']['before_state_hex'] == event['observation']['after_state_hex']
        assert event['model_called'] is True and event['model_committed'] is False


@pytest.mark.parametrize('owner', ['source', 'retained-result'])
def test_crank_admission_keeps_existing_broker_owners_and_never_calls_source(crank_broker, monkeypatch, owner):
    broker, memory, digest = crank_broker
    bank = parameter_bank_input(broker.core.library)
    assert crank_broker_execute(broker, memory, b.CP_PARAMETER_BANK, bank, 2756)[0] == 0
    source = broker.source()
    if owner == 'source':
        source.active = object()
    else:
        broker.transfer = dict(token=77, total=1, cursor=0)
    proof = broker.core.proof_snapshot()
    def uncalled(*args):
        pytest.fail('Crank admission must reject before C or source11')
    monkeypatch.setattr(broker.core, 'execute', uncalled)
    monkeypatch.setattr(broker, 'call_source', uncalled)
    code, output, result = crank_broker_execute(broker, memory, b.CP_CRANK_CONTROL, crank_control_input(), 208)
    assert code == -errno.EBUSY and not output and not result.used and broker.core.proof_snapshot() == proof
    events = [json.loads(line) for line in broker.events.getvalue().splitlines()]
    rejected = [event for event in events if event['kind'] == 'crank_control_rejected'][-1]
    assert rejected['actual_c_result'] is None and rejected['admission_error'] == -errno.EBUSY
    assert rejected['model_called'] is rejected['model_committed'] is False and rejected['actual_core_sha256'] == digest
    assert source.active is not None if owner == 'source' else broker.transfer['token'] == 77
    assert not any(event['kind'] in ('model_crank_control', 'ap_source_result') for event in events)


@pytest.mark.parametrize('failure', ['query-error', 'query-last-byte', 'after-state', 'returned-cookie',
    'returned-bank', 'returned-mode', 'returned-state', 'returned-reserved', 'returned-fnv', 'returned-instance', 'proof-readback'])
def test_crank_postvalidation_failure_preserves_actual_c_zero_and_full208(crank_broker, monkeypatch, failure):
    broker, memory, digest = crank_broker
    bank = parameter_bank_input(broker.core.library)
    assert crank_broker_execute(broker, memory, b.CP_PARAMETER_BANK, bank, 2756)[0] == 0
    proof = broker.core.proof_snapshot()
    original_query = broker.core.library.fcam_model_cp_crank_control_snapshot
    original_execute = broker.core.execute
    original_request = broker.core.library.fcam_model_request
    original_proof = broker.core.proof_snapshot
    def query(model, crank, bank, output, size):
        code = original_query(model, crank, bank, output, size)
        if failure == 'query-error':
            return -errno.EIO
        ctypes.cast(output, ctypes.POINTER(ctypes.c_uint8))[size - 1] ^= 1
        return code
    if failure.startswith('query-'):
        monkeypatch.setattr(broker.core.library, 'fcam_model_cp_crank_control_snapshot', query)
    elif failure == 'after-state':
        state_calls = 0
        def changed_state(instance, op, incoming, capacity):
            nonlocal state_calls
            code, data, result = original_execute(instance, op, incoming, capacity)
            if op == b.STATE:
                state_calls += 1
                if state_calls == 2:
                    data = data[:-1] + bytes([data[-1] ^ 1])
            return code, data, result
        monkeypatch.setattr(broker.core, 'execute', changed_state)
    elif failure == 'proof-readback':
        def changed_proof():
            observed = original_proof()
            return dict(observed, serial=observed['serial'] + 1)
        monkeypatch.setattr(broker.core, 'proof_snapshot', changed_proof)
    else:
        offsets = {'returned-cookie': 196, 'returned-bank': 24, 'returned-mode': 56,
                   'returned-state': 128, 'returned-reserved': 207, 'returned-fnv': 48, 'returned-instance': 8}
        def changed_output(model, op, incoming, size, output, capacity, result):
            code = original_request(model, op, incoming, size, output, capacity, result)
            if op == b.CP_CRANK_CONTROL and code == 0:
                ctypes.cast(output, ctypes.POINTER(ctypes.c_uint8))[offsets[failure]] ^= 1
            return code
        monkeypatch.setattr(broker.core.library, 'fcam_model_request', changed_output)
    request = crank_control_input()
    sequence = broker.sequence + 1
    wire = crank_control_header(sequence, request)
    memory.logical(0, b.HEADER, wire)
    memory.logical(b.HEADER, 12, request)
    with pytest.raises(ValueError, match='crank|Crank'):
        broker.call_core(wire, request, 208)
    events = [json.loads(line) for line in broker.events.getvalue().splitlines()]
    rejected = [event for event in events if event['kind'] == 'crank_control_rejected'][-1]
    assert rejected['actual_c_result'] == 0 and rejected['actual_core_sha256'] == digest
    assert rejected['model_called'] is rejected['model_committed'] is True
    assert (broker.root / rejected['request_payload']['path']).read_bytes() == request
    actual_output = (broker.root / rejected['output_payload']['path']).read_bytes()
    assert len(actual_output) == 208 and actual_output.hex() == rejected['observation']['returned_hex']
    assert len(bytes.fromhex(rejected['observation']['before_state_hex'])) == 128
    assert len(bytes.fromhex(rejected['observation']['after_state_hex'])) == 128
    assert rejected['observation']['readback_verified'] is (failure == 'proof-readback')
    assert not any(event.get('sequence') == sequence and event['kind'] in ('response', 'model_crank_control', 'model_frame', 'ap_source_result') for event in events)
    assert broker.pending_payloads is None and original_proof() == proof


def test_host_injected_empty_zero_return_never_claims_a_crank_commit(crank_broker, monkeypatch):
    broker, memory, digest = crank_broker
    bank = parameter_bank_input(broker.core.library)
    assert crank_broker_execute(broker, memory, b.CP_PARAMETER_BANK, bank, 2756)[0] == 0
    original_request = broker.core.library.fcam_model_request
    # HOST fault injection only: this zero-return stub does not call the C crank.
    def empty_ack(model, op, incoming, size, output, capacity, result):
        return 0 if op == b.CP_CRANK_CONTROL else original_request(model, op, incoming, size, output, capacity, result)
    monkeypatch.setattr(broker.core.library, 'fcam_model_request', empty_ack)
    data = crank_control_input()
    request = crank_control_header(broker.sequence + 1, data)
    memory.logical(0, b.HEADER, request)
    memory.logical(b.HEADER, 12, data)
    with pytest.raises(ValueError, match='crank control receipt'):
        broker.call_core(request, data, 208)
    events = [json.loads(line) for line in broker.events.getvalue().splitlines()]
    rejected = [event for event in events if event['kind'] == 'crank_control_rejected'][-1]
    assert rejected['actual_c_result'] == 0 and rejected['actual_core_sha256'] == digest
    assert rejected['model_called'] is True and rejected['model_committed'] is False
    assert rejected['observation']['before_state_hex'] == rejected['observation']['after_state_hex']
    assert (broker.root / rejected['output_payload']['path']).read_bytes() == b''
    readback = ctypes.create_string_buffer(208)
    assert broker.core.library.fcam_model_cp_crank_control_snapshot(broker.core.model, 1, 1, readback, 208) == -errno.ENODATA
    assert not any(event['kind'] == 'model_crank_control' for event in events)


def test_payload_record_exact_empty_and_nonempty_writeback(tmp_path):
    store = b.PayloadRecords(tmp_path)
    try:
        request = header(data=b'HOST_TEST raw protocol bytes')
        reference = store.retain(request, 'in', b'HOST_TEST raw protocol bytes', event=1)
        empty = store.retain(request, 'out', b'', event=2)
        assert (tmp_path / reference['path']).read_bytes() == b'HOST_TEST raw protocol bytes'
        assert (tmp_path / empty['path']).read_bytes() == b''
        assert reference['sha256'] == reference['writeback_sha256'] and reference['writeback_verified'] is True
        assert empty['fnv1a64'] == b.FNV_SEED and empty['sha256'] == hashlib.sha256(b'').hexdigest()
        assert store.used == reference['bytes'] and store.files == 2
        for ref, raw in ((reference, b'HOST_TEST raw protocol bytes'), (empty, b'')):
            assert (tmp_path / ref['path']).stat().st_mode & 0o777 == 0o600
            store.verify(ref, raw)
        with pytest.raises(FileExistsError):
            store.retain(request, 'in', b'HOST_TEST raw protocol bytes', event=3)
        assert store.poisoned
    finally:
        store.close()


@pytest.mark.parametrize('existing', ['directory', 'symlink'])
def test_payload_directory_is_exclusive_and_never_follows_links(tmp_path, existing):
    target = tmp_path / 'outside'
    target.mkdir()
    path = tmp_path / b.PAYLOAD_DIRECTORY
    if existing == 'directory':
        path.mkdir()
    else:
        path.symlink_to(target, target_is_directory=True)
    with pytest.raises(FileExistsError):
        b.PayloadRecords(tmp_path)
    assert list(target.iterdir()) == []


@pytest.mark.parametrize('mutation', ['symlink', 'hardlink', 'short', 'corrupt', 'mode'])
def test_retained_payload_replacement_is_poisoned(tmp_path, mutation):
    store = b.PayloadRecords(tmp_path)
    raw = b'HOST_TEST exact immutable evidence'
    try:
        reference = store.retain(header(data=raw), 'in', raw, event=1)
        path = tmp_path / reference['path']
        if mutation == 'symlink':
            other = tmp_path / 'other.bin'
            other.write_bytes(raw)
            path.unlink()
            path.symlink_to(other)
        elif mutation == 'hardlink':
            os.link(path, tmp_path / 'alias.bin')
        elif mutation == 'mode':
            path.chmod(0o644)
        else:
            path.write_bytes(raw[:-1] if mutation == 'short' else bytes([raw[0] ^ 1]) + raw[1:])
        with pytest.raises((ValueError, OSError)):
            store.verify(reference, raw)
        assert store.poisoned
        with pytest.raises(ValueError, match='poisoned'):
            store.retain(header(seq=2), 'in', b'', event=2)
    finally:
        store.close()


@pytest.mark.parametrize('failure', ['short', 'corrupt', 'zero-write', 'enospc'])
def test_payload_write_or_writeback_failure_never_returns_a_record(tmp_path, monkeypatch, failure):
    store = b.PayloadRecords(tmp_path)
    actual_read, actual_write = os.pread, os.write

    def read(fd, count, offset):
        data = actual_read(fd, count, offset)
        if data and failure in ('short', 'corrupt'):
            return data[:-1] if failure == 'short' else bytes([data[0] ^ 1]) + data[1:]
        return data

    def write(fd, data):
        if failure == 'enospc':
            raise OSError(errno.ENOSPC, 'HOST_TEST storage full')
        return 0 if failure == 'zero-write' else actual_write(fd, data)

    monkeypatch.setattr(b.os, 'pread', read)
    monkeypatch.setattr(b.os, 'write', write)
    try:
        with pytest.raises((ValueError, OSError)):
            store.retain(header(), 'in', b'HOST_TEST payload', event=1)
        assert store.poisoned
        with pytest.raises(ValueError, match='poisoned'):
            store.retain(header(seq=2), 'out', b'', event=2)
    finally:
        store.close()


@pytest.mark.parametrize('limit', ['file', 'total', 'count'])
def test_payload_limits_refuse_without_truncation(tmp_path, monkeypatch, limit):
    store = b.PayloadRecords(tmp_path)
    try:
        if limit == 'file':
            monkeypatch.setattr(b, 'MAX_RESULT', 2)
        elif limit == 'total':
            monkeypatch.setattr(b, 'PAYLOAD_BUDGET', 4)
            store.retain(header(), 'in', b'123', event=1)
        else:
            monkeypatch.setattr(b, 'PAYLOAD_FILE_LIMIT', 1)
            store.retain(header(), 'in', b'', event=1)
        with pytest.raises(ValueError, match='Invalid payload|budget'):
            store.retain(header(seq=2), 'out', b'123' if limit == 'file' else b'12' if limit == 'total' else b'', event=2)
        assert store.poisoned
        assert not (tmp_path / b.PAYLOAD_DIRECTORY / '00000000000000000002-out.bin').exists()
        if limit == 'total':
            assert (tmp_path / b.PAYLOAD_DIRECTORY / '00000000000000000001-in.bin').read_bytes() == b'123'
    finally:
        store.close()


def test_payload_failure_prevents_actual_core_call_and_guest_response(wire, monkeypatch):
    memory, rsp, _ = wire
    broker = component(memory, rsp, monkeypatch)

    class UncalledCore:
        def execute(self, *args):
            raise AssertionError('Core must not execute after input evidence write failed')

    broker.core = UncalledCore()
    monkeypatch.setattr(b.os, 'write', lambda fd, raw: 0)
    before = memory.memory_writes
    config = struct.pack('<IIIIIIQQII', 128, 64, 30, 90, 400, 100, 2500, 1000000, 0, 0)
    with pytest.raises(ValueError, match='payload write'):
        broker.call_core(header(op=b.INIT, data=config), config, b.DATA)
    assert broker.payloads.poisoned and memory.memory_writes == before
    assert not any(json.loads(line)['kind'] == 'response' for line in broker.events.getvalue().splitlines())


@pytest.mark.parametrize('invalid', ['token', 'cursor', 'capacity', 'short', 'total'])
def test_whole_result_tracker_rejects_mismatched_actual_read_arguments(invalid):
    broker = b.Broker.__new__(b.Broker)
    broker.transfer = None
    first = b'HOST_TEST'
    tail = b' arbitrary wire bytes'
    total = len(first) + len(tail)
    broker.observe_transfer(header(op=b.STILL), b'', first, 0, b.ExecResult(77, total, 0, len(first)))
    args = struct.pack('<QQII', 78 if invalid == 'token' else 77,
                       len(first) + (invalid == 'cursor'), len(tail) - (invalid == 'capacity'), 0)
    result = b.ExecResult(77, total + (invalid == 'total'), len(first), len(tail) - (invalid == 'short'))
    data = tail[:-1] if invalid == 'short' else tail
    with pytest.raises(ValueError, match='READ_RESULT'):
        broker.observe_transfer(header(seq=2, op=b.READ_RESULT, data=args, capacity=len(tail)), args, data, 0, result)
    assert broker.transfer['cursor'] == len(first) and broker.transfer['fnv1a64'] == b.fnv64(first)


def test_whole_result_tracker_uses_actual_release16_hash_and_cancel_extent():
    broker = b.Broker.__new__(b.Broker)
    broker.transfer = None
    first, tail = b'HOST_TEST ', bytes(range(64))
    whole = first + tail
    broker.observe_transfer(header(op=b.STILL), b'', first, 0, b.ExecResult(77, len(whole), 0, len(first)))
    args = struct.pack('<QQII', 77, len(first), len(tail), 0)
    observed = broker.observe_transfer(header(seq=2, op=b.READ_RESULT, data=args, capacity=len(tail)), args, tail, 0,
                                       b.ExecResult(77, len(whole), len(first), len(tail)))
    assert observed['complete'] is True and observed['sha256'] == hashlib.sha256(whole).hexdigest()
    wrong = struct.pack('<QQ', 77, b.fnv64(whole) ^ 1)
    assert broker.observe_transfer(header(seq=3, op=b.RELEASE_RESULT, data=wrong), wrong, b'', -errno.EBADMSG,
                                   b.ExecResult()) is None
    with pytest.raises(ValueError, match='whole-byte FNV'):
        broker.observe_transfer(header(seq=3, op=b.RELEASE_RESULT, data=wrong), wrong, b'', 0, b.ExecResult())
    correct = struct.pack('<QQ', 77, b.fnv64(whole))
    released = broker.observe_transfer(header(seq=3, op=b.RELEASE_RESULT, data=correct), correct, b'', 0, b.ExecResult())
    assert released['status'] == 'released' and released['fnv1a64'] == b.fnv64(whole) and broker.transfer is None
    broker.observe_transfer(header(seq=4, op=b.STILL), b'', first, 0, b.ExecResult(78, len(whole), 0, len(first)))
    cancelled = broker.observe_transfer(header(seq=5, op=b.CANCEL), b'', state(), 0, b.ExecResult(0, 0, 0, 128))
    assert cancelled['status'] == 'cancelled' and cancelled['complete'] is False and broker.transfer is None
    assert cancelled['reconstructed_bytes'] == len(first) and cancelled['fnv1a64'] == b.fnv64(first)


@pytest.mark.parametrize('data,accepted', [
    (b'', True), (b'\x01\x00\x00\x00', True), (bytes(4), False),
    (b'\x02\x00\x00\x00', False), (b'\x01\x00\x00', False),
    (b'\x01\x00\x00\x00\x00', False), (b'\x01\x00\x00\x01', False)])
def test_video_frame_request_flags_are_exact(data, accepted):
    raw = header(op=b.VIDEO_FRAME, data=data)
    if accepted:
        assert b.validate_request(raw, data, MAILBOX, 0)[0] == b.VIDEO_FRAME
    else:
        with pytest.raises(ValueError, match='request size|force-IDR'):
            b.validate_request(raw, data, MAILBOX, 0)


@pytest.mark.parametrize('changed', [None, 'source', 'destination', 'command', 'bytes', 'digest', 'trigger', 'reserved'])
def test_capture_request_requires_exact_native_origin(changed):
    incoming = bytearray(struct.pack('<IIB3xI', 0x40380005, 29, 2, 0))
    raw = bytearray(header(op=b.FRAME_CAPTURE, data=incoming))
    struct.pack_into('<4I', raw, 100, 0x80020002, 0x90040193, 0x4038, 16)
    struct.pack_into('<Q', raw, 120, b.fnv64(incoming))
    fields = {'source': 100, 'destination': 104, 'command': 108, 'bytes': 112, 'digest': 120}
    if changed in fields:
        raw[fields[changed]] ^= 1
    elif changed:
        incoming[8 if changed == 'trigger' else 9] = 1
        struct.pack_into('<Q', raw, 56, b.fnv64(incoming))
        struct.pack_into('<Q', raw, 120, b.fnv64(incoming))
    if changed:
        with pytest.raises(ValueError, match='exact original4038'):
            b.validate_request(bytes(raw), bytes(incoming), MAILBOX, 0)
    else:
        assert b.validate_request(bytes(raw), bytes(incoming), MAILBOX, 0)[0] == b.FRAME_CAPTURE


def test_actual_retained_frame_ctypes_transfer_and_content_checker(actual_core_library, wire, monkeypatch):
    library, digest = actual_core_library
    memory, rsp, _ = wire
    broker = component(memory, rsp, monkeypatch)
    core = broker.core = b.Core(library, digest)
    spec = importlib.util.spec_from_file_location('retained_frame_checker_tested', REPORT / 'functional-camera-evidence/check_evidence.py')
    checker = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(checker)
    instance = MAILBOX['nonce']
    transfers, sequence = [], 0

    def execute(op, incoming=b'', capacity=128):
        nonlocal sequence
        sequence += 1
        request = bytearray(header(seq=sequence, op=op, data=incoming, capacity=capacity))
        if op == b.FRAME_CAPTURE:
            struct.pack_into('<4I', request, 100, 0x80020002, 0x90040193, 0x4038, 16)
            struct.pack_into('<Q', request, 120, b.fnv64(incoming))
        memory.logical(0, len(request), request)
        if incoming:
            memory.logical(b.HEADER, len(incoming), incoming)
        raw, data = broker.fetch()
        b.validate_request(raw, data, MAILBOX, broker.sequence)
        code, output, result = broker.call_core(raw, data, capacity)
        assert broker.publish(raw, output, code, result)
        events = [json.loads(line) for line in broker.events.getvalue().splitlines()]
        actual = [event for event in events if event['kind'] == 'core_result' and event['sequence'] == sequence][0]
        if code == 0 and op not in (b.READ_RESULT, b.RELEASE_RESULT):
            transfers.append(dict(first=sequence, opcode=op, token=result.token,
                request_payload=actual['request_payload'], output_payloads=[actual['output_payload']],
                bytes=len(output), sha256=b.hashlib.sha256(output).hexdigest(), fnv1a64=f'{b.fnv64(output):016x}',
                frame=next((event for event in events if event['kind'] == 'model_frame' and event['sequence'] == sequence), None)))
        return code, output, result, actual['output_payload']

    def collect(op, incoming):
        code, data, result, _ = execute(op, incoming, 127)
        assert code == 0 and result.token
        token, total = result.token, result.total
        output = bytearray(data)
        proof = core.proof_snapshot()
        tx = transfers[-1]
        while len(output) < total:
            code, data, result, reference = execute(b.READ_RESULT,
                struct.pack('<QQII', token, len(output), 127, 0), 127)
            assert code == 0
            output.extend(data)
            tx['output_payloads'].append(reference)
        tx.update(bytes=len(output), sha256=hashlib.sha256(output).hexdigest(), fnv1a64=f'{b.fnv64(output):016x}')
        assert execute(b.RELEASE_RESULT, struct.pack('<QQ', token, b.fnv64(output)), 0)[0] == 0
        return bytes(output), proof, token

    def delta(proof):
        return {key: proof['after'][key] - proof['before'][key] for key in proof['before']}

    try:
        assert execute(b.INIT)[0] == 0
        config = struct.pack('<IIIIIIQQII', 128, 64, 30, 95, 400, 100, 2500, 1000000, 0, 0)
        assert execute(b.CONFIGURE, config)[0] == 0
        request = struct.pack('<IIB3xI', 0x40380005, 29, 2, 0)
        frame, proof, transfer_token = collect(b.FRAME_CAPTURE, request)
        retained = checker.retained_frame_proof(17, request, frame, proof, delta(proof), None,
            proof['frame_generation'] - 1, proof['config_generation'], transfer_token, instance)
        corrupted = bytearray(frame); corrupted[-1] ^= 1
        with pytest.raises(ValueError, match='result/proof|header/pixels'):
            checker.retained_frame_proof(17, request, bytes(corrupted), proof, delta(proof), None,
                proof['frame_generation'] - 1, proof['config_generation'], transfer_token, instance)
        frame_token = b.u64(frame, 8)
        changed_config = struct.pack('<IIIIIIQQII', 64, 32, 30, 95, 400, 100, 20000, 4000000, 0, 0)
        assert execute(b.CONFIGURE, changed_config)[0] == 0
        incoming = struct.pack('<Q6I', frame_token, 0, 0, 1, 128, 64, 95)
        jpeg, proof, transfer_token = collect(b.FRAME_STILL, incoming)
        encoded = checker.retained_frame_proof(18, incoming, jpeg, proof, delta(proof), retained,
            proof['frame_generation'], proof['config_generation'], transfer_token, instance)
        forged = dict(proof, render_observed=1)
        with pytest.raises(ValueError, match='token/source/lifetime'):
            checker.retained_frame_proof(18, incoming, jpeg, forged, delta(proof), retained,
                proof['frame_generation'], proof['config_generation'], transfer_token, instance)
        done = struct.pack('<QII', frame_token, 1, 0)
        assert execute(b.FRAME_RELEASE, done, 0)[0] == 0
        proof = core.proof_snapshot()
        assert checker.retained_frame_proof(19, done, b'', proof, delta(proof), encoded,
            proof['frame_generation'], proof['config_generation'], 0, instance) is None
        assert execute(b.FRAME_RELEASE, done, 0)[0] == -errno.ESTALE
        actual_history = dict(transfers=transfers, model_instance=instance, owner_pid=os.getpid())
        checked = checker.check_frames(broker.root, actual_history, require_media=False)
        assert checked['verified'] and checked['last_counts']['jpeg_encoded'] == 1
        assert [job['opcode'] for job in checked['jobs']] == [b.INIT, b.FRAME_CAPTURE, b.FRAME_STILL, b.FRAME_RELEASE]
    finally:
        core.destroy_model()
        broker.detach_mailbox()
        core.close()


@pytest.mark.parametrize('force_idr', [False, True])
def test_actual_ctypes_video_proof_binds_packet_bytes_and_separates_drain(actual_core_library, force_idr):
    library, digest = actual_core_library
    core = b.Core(library, digest)
    instance = MAILBOX['nonce']

    def encoded(op, data=b''):
        code, first, result = core.execute(instance, op, data, 53)
        assert code == 0 and result.token
        token, total = result.token, result.total
        output = bytearray(first)
        proof = core.proof_snapshot()
        while len(output) < total:
            args = struct.pack('<QQII', token, len(output), 53, 0)
            code, chunk, result = core.execute(instance, b.READ_RESULT, args, 53)
            assert code == 0 and result.offset == len(output)
            output.extend(chunk)
            assert core.proof_snapshot() == proof
        assert proof['result_bytes'] == len(output) and proof['result_fnv1a64'] == b.fnv64(output)
        args = struct.pack('<QQ', token, b.fnv64(output))
        assert core.execute(instance, b.RELEASE_RESULT, args, 0)[0] == 0
        assert core.proof_snapshot() == proof
        return bytes(output), proof

    try:
        assert core.execute(instance, b.INIT, b'', 128)[0] == 0
        config = struct.pack('<IIIIIIQQII', 128, 64, 30, 90, 400, 100, 2500, 1000000, 0, 0)
        assert core.execute(instance, b.VIDEO_BEGIN, config, 128)[0] == 0
        packet, proof = encoded(b.VIDEO_FRAME)
        payload = packet[96 + b.u32(packet, 64):]
        assert proof['serial'] == 2 and proof['frame_generation'] == proof['packet_generation'] == b.u64(packet, 56)
        assert proof['consumer_kind'] == 2 and proof['operation_status'] == proof['consumer_status'] == 0
        assert proof['source_fnv1a64'] == proof['consumer_before_fnv1a64'] == proof['consumer_after_fnv1a64']
        assert proof['consumer_entered'] == proof['consumer_returned'] == proof['encoder_consumed'] == proof['retired'] == 1
        assert proof['encoded_bytes'] == len(payload) == b.u64(packet, 48) and proof['encoded_fnv1a64'] == b.fnv64(payload)
        assert proof['before']['consumed'] == 0 and proof['after']['consumed'] == proof['after']['video_encoded'] == 1
        if force_idr:
            packet, proof = encoded(b.VIDEO_FRAME, b'\x01\x00\x00\x00')
            payload = packet[96 + b.u32(packet, 64):]
            starts = list(re.finditer(b'\x00\x00\x00\x01|\x00\x00\x01', payload))
            assert starts and any(payload[start.end()] & 31 == 5 for start in starts)
            assert b.u32(packet, 40) == 1 and proof['encoder_consumed'] == proof['retired'] == 1
            assert proof['before']['consumed'] == 1 and proof['after']['consumed'] == 2
        eos, drained = encoded(b.VIDEO_END)
        assert len(eos) == 96 and b.u32(eos, 44) == 1
        assert drained['serial'] == 3 + force_idr and drained['consumer_kind'] == 3 and drained['before'] == drained['after']
        assert not any(drained[key] for key in ('render_observed', 'encoder_consumed', 'encoded_bytes', 'active_bytes', 'retired'))
        assert core.execute(instance, b.CANCEL, b'', 128)[0] == 0 and core.proof_snapshot() == drained
    finally:
        core.close()
