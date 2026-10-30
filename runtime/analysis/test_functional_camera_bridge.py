# SPDX-License-Identifier: MIT
"""Focused parent-run batch. Do not execute until the parent freezes all agents.

Wire fixtures exercise transport only. Real-model tests compile/load the actual
core and consume its in-memory bytes; no fixture synthesizes a camera product.
"""
import errno
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
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
        subprocess.run(cc + ['-std=c11', '-Wall', '-Wextra', '-Werror', '-pedantic', '-pthread'] + flags +
                       [str(HERE / 'test-functional-camera-bridge.c'), '-o', str(executable)],
                       check=True, capture_output=True, timeout=45)
        result[name] = executable
    return result


@pytest.mark.parametrize('mode', ['normal', 'sanitized'])
@pytest.mark.parametrize('scenario', C_SCENARIOS)
def test_actual_c_bridge_contracts(guest_builds, mode, scenario):
    env = dict(os.environ, ASAN_OPTIONS='detect_leaks=1:abort_on_error=1', UBSAN_OPTIONS='halt_on_error=1:print_stacktrace=1')
    process = subprocess.run([str(guest_builds[mode]), scenario], env=env, capture_output=True, timeout=8)
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
        'virtual-camera-pipeline/camera-pipeline.c')]
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


def test_actual_ctypes_video_proof_binds_packet_bytes_and_separates_drain(actual_core_library):
    library, digest = actual_core_library
    core = b.Core(library, digest)
    instance = MAILBOX['nonce']

    def encoded(op):
        code, first, result = core.execute(instance, op, b'', 53)
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
        eos, drained = encoded(b.VIDEO_END)
        assert len(eos) == 96 and b.u32(eos, 44) == 1
        assert drained['serial'] == 3 and drained['consumer_kind'] == 3 and drained['before'] == drained['after']
        assert not any(drained[key] for key in ('render_observed', 'encoder_consumed', 'encoded_bytes', 'active_bytes', 'retired'))
        assert core.execute(instance, b.CANCEL, b'', 128)[0] == 0 and core.proof_snapshot() == drained
    finally:
        core.close()
