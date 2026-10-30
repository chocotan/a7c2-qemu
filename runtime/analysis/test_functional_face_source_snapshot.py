# SPDX-License-Identifier: MIT
"""Host owned-buffer/protocol checks only. Never connects to a VM or device."""
import errno
import hashlib
import io
import json
from pathlib import Path
import struct
import threading

import pytest
import functional_camera_broker as b
import functional_face_source_snapshot as s

# Independent GUEST provider/CP tests; existing host broker tests stay below.
import os
import re
import shlex
import shutil
import subprocess

GUEST_HERE = Path(__file__).resolve().parent
GUEST_MODES = ('three-units', 'init', 'ticket', 'pagemap', 'bridge', 'tokens', 'drift-release', 'identity', 'metadata', 'fork-thread')
GUEST_SOURCES = ('functional-face-source-snapshot.c', 'functional-face-ap-observer.c',
                 'functional-face-registry.c', 'functional-face-dmm.c', 'functional-face-transfer.c',
                 'functional-face-sdk.c')


@pytest.fixture(scope='module', params=[False, True], ids=['guest-c11', 'guest-asan-ubsan'])
def source_snapshot_guest_executable(request, tmp_path_factory):
    output = tmp_path_factory.mktemp('source-snapshot-guest') / 'provider'
    flags = ['-std=c11', '-O1', '-g', '-Wall', '-Wextra', '-Werror', '-pedantic', '-pthread', '-DFCAM_HOST_TEST']
    if request.param:
        flags += ['-fsanitize=address,undefined', '-fno-omit-frame-pointer', '-fno-pie', '-no-pie']
    process = subprocess.run([*shlex.split(os.environ.get('CC', 'cc')), *flags,
        str(GUEST_HERE / 'test-functional-face-source-snapshot.c'),
        *(str(GUEST_HERE / name) for name in GUEST_SOURCES), str(GUEST_HERE / 'dmm-service.c'),
        '-o', str(output)], capture_output=True, text=True, timeout=60)
    assert process.returncode == 0, process.stdout + process.stderr
    return output


@pytest.mark.parametrize('mode', GUEST_MODES)
def test_source_snapshot_guest_provider(source_snapshot_guest_executable, mode):
    process = subprocess.run([str(source_snapshot_guest_executable), mode], capture_output=True, text=True, timeout=20,
        env=dict(os.environ, ASAN_OPTIONS='detect_leaks=1:halt_on_error=1',
                 UBSAN_OPTIONS='halt_on_error=1:print_stacktrace=1'))
    assert process.returncode == 0, process.stdout + process.stderr
    assert (f'FACE_SOURCE_SNAPSHOT_GUEST_HOST_PASS mode={mode} synthetic_pfn=1 '
            'native_verified=0 capture_verified=0') in process.stdout
    if mode == 'three-units':
        assert ('SNAPSHOT_HOST_COUNTS units=3 snapshot=514304 cp_write=514304 cp_readback=514304 '
                'independent_read=514304 callbacks=3 speech_bytes=1048576 speech_unchanged=1 '
                'synthetic_pfn=1 native_verified=0') in process.stdout
        for i, length in enumerate((409600, 51200, 53504)):
            content = bytes(((n * 37 + i * 53 + 11) ^ (n >> 7)) & 255 for n in range(length))
            assert f'unit={0x1d9 + i:x} bytes={length} digest={b.fnv64(content):016x}' in process.stdout


def test_source_snapshot_guest_aarch64_libc_225_link_only(tmp_path):
    compiler = shutil.which('clang')
    reader = shutil.which('aarch64-linux-gnu-readelf')
    if not compiler or not reader:
        pytest.skip('requires installed clang/lld and AArch64 readelf')
    library = GUEST_HERE / 'menu-root/lib'
    names = ('libc-2.25.so', 'libpthread-2.25.so', 'ld-2.25.so')
    if not all((library / name).is_file() for name in names):
        pytest.skip('guest libc 2.25 link libraries unavailable')
    output = tmp_path / 'face-source-snapshot-aarch64.so'
    process = subprocess.run([compiler, '--target=aarch64-linux-gnu', '-fuse-ld=lld', '-nostdlib', '-O2',
        '-mno-outline-atomics', '-std=c11', '-Wall', '-Wextra', '-Werror', '-pedantic',
        '-DFULL_IMAGING_GUEST', '-isystem', '/usr/aarch64-linux-gnu/include', '-shared', '-fPIC',
        '-Wl,--no-undefined', *(str(GUEST_HERE / name) for name in GUEST_SOURCES),
        str(GUEST_HERE / 'functional-face-runtime.c'), str(GUEST_HERE / 'functional-camera-bridge.c'),
        *(str(library / name) for name in names), '-o', str(output)], capture_output=True, text=True, timeout=60)
    assert process.returncode == 0, process.stdout + process.stderr
    imported = subprocess.run([reader, '--dyn-syms', '-W', str(output)], check=True,
                              capture_output=True, text=True, timeout=10).stdout
    assert '__isoc23' not in imported and '__aarch64_' not in imported
    assert re.search(r'\bgetpid@GLIBC_2\.17\b', imported)
    assert re.search(r'\bsyscall@GLIBC_2\.17\b', imported)
    versions = subprocess.run([reader, '--version-info', '-W', str(output)], check=True,
                              capture_output=True, text=True, timeout=10).stdout
    assert set(re.findall(r'Name: (GLIBC_\d+\.\d+)', versions)) == {'GLIBC_2.17'}


MAILBOX = dict(phys0=0x400021000, nonce=0xaabbccdd11223344, pid=1234,
               pages=[0x400021000 - n * 8192 for n in range(16)])
SOURCE = 0x410300000
HEAD = 'FlatView #4\n AS "memory", root: system\n AS "cpu-memory-0", root: system\n Root memory region: system\n'


def row(a=0x400000000, end=0x500000000, *, offset=0, kind='ram', name='owned-ram'):
    return f'  {a:016x}-{end - 1:016x} (prio 0, {kind}): {name} @{offset:016x} owner:{{obj path=/objects/owned}}\n'


def header(op=s.OP, incoming=b'', *, seq=1, capacity=b.DATA, flag=1):
    raw = bytearray(b.HEADER)
    struct.pack_into('<4I', raw, 0, b.MAGIC, b.VERSION, MAILBOX['pid'], b.REQUEST)
    struct.pack_into('<QQIII', raw, 16, MAILBOX['nonce'], seq, op, len(incoming), capacity)
    struct.pack_into('<I', raw, 52, flag)
    struct.pack_into('<Q', raw, 56, b.fnv64(incoming))
    struct.pack_into('<5I', raw, 96, 1235, 0x123456, 0xabcdef, s.COMMAND, 40)
    struct.pack_into('<16Q', raw, 128, *MAILBOX['pages'])
    return raw


def packet(unit=0x1d9, *, frame=0x7f70000fc0, ap=0x92a, physical=SOURCE):
    length = s.UNITS[unit]
    cp_count = (length + b.PAGE - 1) // b.PAGE
    sdk_count = (frame % b.PAGE + s.FRAME_BYTES + b.PAGE - 1) // b.PAGE
    cp = 0x8c00 | (unit - 0x1d9 + 2)
    raw = bytearray(360 + 8 * (cp_count + sdk_count))
    struct.pack_into('<8I', raw, 0, 1, unit, ap, cp, length, cp_count, sdk_count, 3)
    struct.pack_into('<5Q', raw, 32, 0x123, 0x456, 0x789, 0xabc, physical)
    struct.pack_into('<3Q', raw, 80, 41, 43, 45)
    struct.pack_into('<6I', raw, 104, 0x4567, ap >> 10, 0x456, MAILBOX['pid'], 1235, 0)
    struct.pack_into('<3I', raw, 128, 0x21, unit, ap)
    struct.pack_into('<Hh', raw, 168, 0x8021, 0)
    struct.pack_into('<I', raw, 208, 0x24)
    struct.pack_into('<2I', raw, 216, ap, 0xffffffff)
    struct.pack_into('<Hh', raw, 248, 0x8024, 0)
    struct.pack_into('<H', raw, 256, 1)
    struct.pack_into('<I', raw, 260, ap)
    struct.pack_into('<Q', raw, 272, physical)
    struct.pack_into('<I', raw, 280, length)
    struct.pack_into('<2Q', raw, 288, frame, frame + 0xb8)
    struct.pack_into('<QQIIQQ', raw, 304, frame + 0x68, frame + 0x70, length, 1, frame + 0x1234, frame + 0x60)
    struct.pack_into('<4I', raw, 344, ap, 0, cp, 0)
    struct.pack_into('<Q', raw, 72, b.fnv64(raw[304:344]))
    pages = [0x420000000 + n * 8192 for n in range(cp_count)] + [0x430000000 + n * 8192 for n in range(sdk_count)]
    struct.pack_into('<' + 'Q' * len(pages), raw, 360, *pages)
    return bytes(raw)


def request(raw=None, **kwargs):
    raw = packet() if raw is None else raw
    h = header(incoming=raw, **kwargs)
    if len(raw) >= 80:
        h[120:128] = raw[72:80]
    return bytes(h), raw


def dump(address, raw):
    return ''.join(f'{address + n:08x}:' + ''.join(f' 0x{v:02x}' for v in raw[n:n + 8]) + '\r\n'
                   for n in range(0, len(raw), 8))


@pytest.mark.parametrize('unit', s.UNITS)
@pytest.mark.parametrize('frame', [0x7f70000010, 0x7f70000fc0])
def test_packet_all_units_and_exact_sdk_pages(unit, frame):
    h, raw = request(packet(unit, frame=frame))
    info = s.packet(raw, h, MAILBOX)
    assert info['unit'] == unit and info['length'] == s.UNITS[unit]
    assert len(info['cp_pages']) == {0x1d9: 100, 0x1da: 13, 0x1db: 14}[unit]
    assert len(info['sdk_pages']) == (1 if frame % b.PAGE == 16 else 2)
    assert info['allocation_token'] != info['birth']


@pytest.mark.parametrize('at,fmt,value', [
    (0, 'I', 2), (4, 'I', 0x1dc), (8, 'I', 0x3ff), (8, 'I', 0x83ff), (8, 'I', 0x7ff),
    (12, 'I', 0x8c03), (12, 'I', 0x8002), (16, 'I', 409600 - 1), (20, 'I', 99), (24, 'I', 1),
    (28, 'I', 1), (32, 'Q', 0), (40, 'Q', 0), (48, 'Q', 0), (56, 'Q', 0),
    (64, 'Q', 2**64 - 2), (72, 'Q', 123), (80, 'Q', 43), (88, 'Q', 46), (96, 'Q', 0),
    (104, 'I', 0), (108, 'I', 3), (112, 'I', 0x10000), (116, 'I', 99), (120, 'I', 99), (124, 'I', 1),
    (128, 'I', 0x22), (132, 'I', 0), (136, 'I', 0x92b), (140, 'I', 1),
    (168, 'H', 0x8024), (170, 'h', -1), (208, 'I', 0x25), (212, 'I', 1), (220, 'I', 0),
    (224, 'I', 1), (248, 'H', 0x8021), (250, 'h', 1), (256, 'H', 2), (260, 'I', 0x92b),
    (272, 'Q', SOURCE + 1), (280, 'I', 1), (288, 'Q', 0x7f70000fc1), (296, 'Q', 0),
    (304, 'Q', 0), (312, 'Q', 0), (320, 'I', 1), (324, 'I', 0), (328, 'Q', 0), (336, 'Q', 0),
    (344, 'I', 0), (348, 'I', 1), (352, 'I', 0), (356, 'I', 1), (360, 'Q', 0), (360, 'Q', 3),
])
def test_packet_field_rejection(at, fmt, value):
    raw = bytearray(packet())
    struct.pack_into('<' + fmt, raw, at, value)
    h, raw = request(bytes(raw))
    with pytest.raises(ValueError):
        s.packet(raw, h, MAILBOX)


@pytest.mark.parametrize('at,value', [(8, 999), (16, 0), (52, 0), (52, 2), (96, 1236), (108, 0x02820747), (112, 48), (120, 999)])
def test_packet_header_binding(at, value):
    h, raw = request()
    h = bytearray(h)
    struct.pack_into('<Q' if at in (16, 120) else '<I', h, at, value)
    with pytest.raises(ValueError):
        s.packet(raw, bytes(h), MAILBOX)


@pytest.mark.parametrize('raw', [packet()[:-1], packet() + b'\0', b'', bytes(359)])
def test_packet_exact_size(raw):
    h, raw = request(raw)
    with pytest.raises(ValueError):
        s.packet(raw, h, MAILBOX)


def test_flatview_ram_coverage_and_inclusive_end():
    view = s.selected(s.mtree(HEAD + row(0x1000, 0x3000, offset=0x4000)))
    assert s.cover(view, 0x1000, 0x2000)[0][1:] == (0x4000, 0x6000)
    with pytest.raises(ValueError, match='uncovered'):
        s.cover(view, 0x1000, 0x2001)
    h, raw = request()
    info = s.packet(raw, h, MAILBOX)
    mapping = s.disjoint(HEAD + row(), info, MAILBOX)
    assert mapping['canonical_mr_offsets_disjoint'] and mapping['spans'] == 119
    assert mapping['physicalBackingObjectVerified'] is False


@pytest.mark.parametrize('text', [
    HEAD + row(kind='i/o'), HEAD + row(kind='romd'), HEAD + row() + row(),
    HEAD.replace('cpu-memory-0', 'iommu') + row(), HEAD + row() + ' AS "memory", root: system\n',
    HEAD.replace('root: system', 'root: other') + row(), HEAD + row(offset=2**64 - 1),
    HEAD + row(0x1000, 0x2000) + row(0x3000, 0x4000), 'garbage\n' + HEAD + row(),
    HEAD + row().replace('owner:{', 'owner:{nested{'),
])
def test_invalid_or_ambiguous_flatview(text):
    h, raw = request()
    with pytest.raises(ValueError):
        s.disjoint(text, s.packet(raw, h, MAILBOX), MAILBOX)


@pytest.mark.parametrize('at', [360, 360 + 99 * 8, 360 + 100 * 8, 360 + 101 * 8])
def test_all_cp_sdk_pages_including_last_rounded_page_are_disjoint(at):
    raw = bytearray(packet())
    struct.pack_into('<Q', raw, at, MAILBOX['pages'][-1])
    h, raw = request(bytes(raw))
    with pytest.raises(ValueError, match='alias'):
        s.disjoint(HEAD + row(), s.packet(raw, h, MAILBOX), MAILBOX)


def test_different_gpas_cannot_hide_mr_offset_alias_or_unknown_backing():
    h, raw = request()
    info = s.packet(raw, h, MAILBOX)
    text = HEAD + row(0x400000000, SOURCE) + row(SOURCE, 0x500000000, offset=0)
    with pytest.raises(ValueError, match='alias'):
        s.disjoint(text, info, MAILBOX)
    text = HEAD + row(0x400000000, 0x410000000) + row(0x410000000, 0x500000000, name='other-MR')
    with pytest.raises(ValueError, match='Cross-MR'):
        s.disjoint(text, info, MAILBOX)


def test_same_owner_name_across_different_winning_rows_is_not_object_identity():
    h, raw = request()
    info = s.packet(raw, h, MAILBOX)
    text = HEAD + row(0x400000000, 0x410000000) + row(0x410000000, 0x500000000, offset=0x10000000)
    with pytest.raises(ValueError, match='winning-row'):
        s.disjoint(text, info, MAILBOX)


def test_false_iova_is_never_translated_into_ddr():
    h, raw = request(packet(physical=0x700300000))
    with pytest.raises(ValueError, match='uncovered'):
        s.disjoint(HEAD + row(), s.packet(raw, h, MAILBOX), MAILBOX)


@pytest.mark.parametrize('raw', [b'a', bytes(range(17)), bytes(range(256))])
def test_xp_exact_owned_content(raw):
    assert s.parse_xp(dump(SOURCE, raw), SOURCE, len(raw)) == raw


@pytest.mark.parametrize('bad', [
    'short-tail', 'extra-byte', 'duplicate', 'address-gap', 'error', 'bad-byte', 'prefix', 'extra-line', 'blank-line',
])
def test_xp_strict_grammar_and_completeness(bad):
    raw = bytes(range(17))
    text = dump(SOURCE, raw)
    if bad == 'short-tail': text = dump(SOURCE, raw[:-1])
    if bad == 'extra-byte': text = dump(SOURCE, raw + b'\0')
    if bad == 'duplicate': text += text.splitlines()[0] + '\n'
    if bad == 'address-gap': text = text.replace(f'{SOURCE + 8:08x}:', f'{SOURCE + 9:08x}:')
    if bad == 'error': text += 'Cannot access memory\n'
    if bad == 'bad-byte': text = text.replace('0x01', '0x1', 1)
    if bad == 'prefix': text = '0x' + text
    if bad == 'extra-line': text += 'garbage\n'
    if bad == 'blank-line': text += '\n'
    with pytest.raises(ValueError):
        s.parse_xp(text, SOURCE, len(raw))


class OwnedMailbox:
    def __init__(self):
        self.data = bytearray(b.MAILBOX_BYTES)
        self.mode_on, self.detached = False, False
        self.window_deadline = None
        self.accesses = self.writes = 0

    def mode(self, physical):
        self.mode_on = physical

    def location(self, address, size):
        assert not self.detached and self.mode_on
        for n, page in enumerate(MAILBOX['pages']):
            if page <= address and address + size <= page + b.PAGE:
                self.accesses += 1
                return n * b.PAGE + address - page
        raise AssertionError('Only dedicated mailbox pages may use RSP')

    def read(self, address, size):
        at = self.location(address, size)
        return bytes(self.data[at:at + size])

    def write(self, address, raw):
        at = self.location(address, len(raw))
        self.writes += 1
        self.data[at:at + len(raw)] = raw
        if at == 12 and raw == struct.pack('<I', b.DETACHED):
            self.detached = True


class OwnedQMP:
    def __init__(self, broker):
        self.broker, self.running, self.commands, self.serial = broker, True, [], 0
        self.source = bytearray((n * 31 + n // 256 + 17) & 255 for n in range(s.UNITS[0x1d9]))
        self.tree, self.read_count, self.failure = HEAD + row(), 0, None

    def status(self):
        self.serial += 1
        self.commands.append('query-status')
        return dict(running=self.running, status='running' if self.running else 'paused')

    def execute(self, command, arguments=None):
        self.serial += 1
        assert self.broker.lock._is_owned()
        if command != 'human-monitor-command':
            assert command in ('stop', 'cont') and arguments is None
            self.commands.append(command)
            self.running = command == 'cont'
            return {}
        assert not self.running and not self.broker.acknowledged and not self.broker.rsp.detached
        line = arguments['command-line']
        self.commands.append(line)
        if line == 'cpu 0':
            return 'Invalid CPU index' if self.failure == 'cpu0' else ''
        if line == 'info mtree -f -o':
            return self.tree
        assert line == f'xp /{len(self.source)}bx 0x{SOURCE:x}'
        self.read_count += 1
        if self.failure == 'changed' and self.read_count == 2:
            self.source[-1] ^= 1
        text = dump(SOURCE, self.source)
        if self.failure == 'short':
            text = dump(SOURCE, self.source[:-1])
        if self.failure == 'line':
            text = text.replace('0x11', '0xz1', 1)
        return text


class CoreProtocolMock:
    """Only original state/CANCEL protocol behavior; this is never native evidence."""
    def __init__(self):
        self.model, self.calls, self.proofs = object(), [], 0

    def execute(self, instance, op, raw, capacity):
        self.calls.append((instance, op, raw, capacity))
        assert op in (b.STATE, b.CANCEL)
        state = bytearray(128)
        struct.pack_into('<I', state, 0, 1)
        struct.pack_into('<Q', state, 48, instance)
        return 0, bytes(state), b.ExecResult(0, 0, 0, 128)

    def proof_snapshot(self):
        self.proofs += 1
        return None

    def destroy_model(self):
        self.model = None


@pytest.fixture
def host(tmp_path, monkeypatch):
    broker = b.Broker.__new__(b.Broker)
    broker.mailbox, broker.config = b.validate_mailbox(MAILBOX), {'generation': 'owned-mock'}
    broker.lock, broker.io_timeout = threading.RLock(), .5
    broker.resume_allowed = lambda: True
    broker.acknowledged, broker.phys_restored = False, True
    broker.sequence, broker.event_serial = 0, 0
    broker.cleaning, broker.log_errors = False, []
    broker.last_response = broker.pending_payloads = broker.transfer = broker.last_frame = None
    broker.source_provider = s.Snapshot(True)
    broker.root, broker.events, broker.done = tmp_path, io.StringIO(), threading.Event()
    broker.payloads = b.PayloadRecords(tmp_path)
    broker.rsp, broker.core = OwnedMailbox(), CoreProtocolMock()
    broker.qmp = OwnedQMP(broker)
    monkeypatch.setattr(b, 'revalidate', lambda config: config == broker.config or pytest.fail('Wrong generation'))
    try:
        yield broker
    finally:
        (tmp_path / 'host-mock-receipts.jsonl').write_text(broker.events.getvalue(), encoding='ascii')
        broker.source().cancel()
        broker.payloads.close()


def stage(host, h, raw):
    host.rsp.data[:b.HEADER] = h
    host.rsp.data[b.HEADER:b.HEADER + len(raw)] = raw


def exchange(host, op=s.OP, incoming=None, *, capacity=b.DATA, flag=1, mutate=None, publish=True):
    if op == s.OP:
        incoming = packet() if incoming is None else incoming
        h, incoming = request(incoming, seq=host.sequence + 1, capacity=capacity, flag=flag)
    else:
        incoming = b'' if incoming is None else incoming
        h = header(op, incoming, seq=host.sequence + 1, capacity=capacity, flag=flag)
        active = host.source().active
        struct.pack_into('<Q', h, 120, active['source']['api_fnv'] if active else b.fnv64(packet()[304:344]))
        h = bytes(h)
    if mutate:
        h = bytearray(h)
        mutate(h)
        h = bytes(h)
    stage(host, h, incoming)
    actual, data = host.fetch()
    assert actual == h and data == incoming
    error, output, result = host.call_core(actual, data, capacity)
    if publish:
        assert host.publish(actual, output, error, result)
        assert bytes(host.rsp.data[b.HEADER:b.HEADER + result.used]) == output
        assert b.u64(host.rsp.data, 64) == b.fnv64(output)
    return error, output, result, h


def events(host, kind):
    return [v for line in host.events.getvalue().splitlines() if (v := json.loads(line))['kind'] == kind]


@pytest.mark.parametrize('unit', s.UNITS)
def test_real_owned_source_content_flows_through_mailbox_readback_and_whole_fnv_release(host, unit):
    expected = bytes(host.qmp.source[:s.UNITS[unit]])
    host.qmp.source = bytearray(expected)
    error, first, result, h = exchange(host, incoming=packet(unit), capacity=47001)
    assert error == 0 and result.token >= s.TOKEN_BASE and result.total == len(expected)
    snapshot = host.source().active['data']
    assert type(snapshot) is bytes and snapshot == expected
    token, total = result.token, result.total
    # Guest protocol mock really copies each mailbox chunk into a separate CP buffer.
    cp = bytearray(total)
    cp[:len(first)] = host.rsp.data[b.HEADER:b.HEADER + len(first)]
    cursor = len(first)
    host.qmp.source[:] = bytes([0x9a]) * total
    assert snapshot == expected and host.core.calls == [] and host.core.proofs == 0
    while cursor < total:
        args = struct.pack('<QQII', token, cursor, 47001, 0)
        code, chunk, r, _ = exchange(host, b.READ_RESULT, args, capacity=47001)
        assert code == 0 and r.offset == cursor
        cp[cursor:cursor + len(chunk)] = host.rsp.data[b.HEADER:b.HEADER + len(chunk)]
        assert bytes(cp[cursor:cursor + len(chunk)]) == chunk
        cursor += len(chunk)
    assert bytes(cp) == expected
    code, empty, r, _ = exchange(host, b.RELEASE_RESULT, struct.pack('<QQ', token, b.fnv64(bytes(cp))), capacity=0)
    assert code == 0 and empty == b'' and r.used == 0 and host.source().active is None and host.transfer is None
    sources, responses = events(host, 'ap_source_result'), events(host, 'response')
    assert sources and not events(host, 'core_result') and not events(host, 'model_frame') and host.last_frame is None
    retained = b''.join((host.root / item['output_payload']['path']).read_bytes() for item in sources if item['token'] == token)
    assert retained == expected and hashlib.sha256(retained).hexdigest() == hashlib.sha256(expected).hexdigest()
    assert all(item['actual_c_result'] is None and item['actual_source_result'] == 0 for item in sources + responses)
    assert all(not item['source_snapshot']['capture_verified'] and
               not item['source_snapshot']['native_global_writer_exclusion_verified'] for item in sources)
    snapshot_receipt = sources[0]['source_snapshot']
    window = snapshot_receipt['paused_window']
    assert window['sequence'] == 1 and window['model_instance'] == MAILBOX['nonce'] and window['window_closed']
    assert window['request_header_sha256'] == window['observed_header_sha256'] == hashlib.sha256(h).hexdigest()
    assert window['request_payload_sha256'] == window['observed_payload_sha256'] == hashlib.sha256(packet(unit)).hexdigest()
    assert window['prior_status']['running'] and not window['paused_status']['running']
    assert window['stop_reply'] == window['resume_reply'] == {} and window['continuation'] == 'resumed'
    assert window['physical_mode_restored_before_exit'] and window['resumed_status']['running']
    assert [c['arguments']['command-line'] for c in window['commands']] == ['cpu 0', 'info mtree -f -o',
        f'xp /{total}bx 0x{SOURCE:x}', f'xp /{total}bx 0x{SOURCE:x}']
    ids = [window['prior_status_qmp_id'], window['stop_qmp_id'], window['paused_status_qmp_id'],
           *[c['qmp_id'] for c in window['commands']], window['resume_qmp_id'], window['resumed_status_qmp_id']]
    assert ids == sorted(set(ids)) and all(type(v) is int for v in ids)
    assert window['commands'][0]['reply_sha256'] == hashlib.sha256(b'').hexdigest()
    assert window['commands'][1]['reply_sha256'] == hashlib.sha256(host.qmp.tree.encode()).hexdigest()
    assert [c['reply_sha256'] for c in window['commands'][2:]] == [v['sha256'] for v in snapshot_receipt['full_span_reads']]
    mapping = snapshot_receipt['mapping']
    assert mapping['mtree_raw'] == host.qmp.tree and mapping['mtree_bytes'] == len(host.qmp.tree.encode())
    assert mapping['mtree_sha256'] == hashlib.sha256(host.qmp.tree.encode()).hexdigest()
    assert mapping['monitor_cpu'] == 0 and mapping['monitor_selection_reply'] == ''
    actual_mapping = s.disjoint(mapping['mtree_raw'], s.packet(packet(unit), h, MAILBOX), MAILBOX)
    assert all(mapping[k] == v for k, v in actual_mapping.items())
    released = responses[-1]['result_transfer']
    assert released['complete'] and released['status'] == 'released' and released['provider_kind'] == 'source'
    assert released['sha256'] == hashlib.sha256(expected).hexdigest() and released['fnv1a64'] == b.fnv64(expected)
    commands = host.qmp.commands
    at = commands.index('info mtree -f -o')
    assert commands[at - 4:at + 5] == ['query-status', 'stop', 'query-status', 'cpu 0', 'info mtree -f -o',
        f'xp /{total}bx 0x{SOURCE:x}', f'xp /{total}bx 0x{SOURCE:x}', 'cont', 'query-status']
    assert host.qmp.read_count == 2


@pytest.mark.parametrize('kind', ['short', 'changed', 'line', 'cpu0', 'gap', 'mmio', 'alias-last', 'unknown-AS'])
def test_source_faults_keep_negative_empty_output_and_sticky_evidence(host, kind):
    raw = packet()
    if kind in ('short', 'changed', 'line', 'cpu0'):
        host.qmp.failure = kind
    elif kind == 'gap':
        host.qmp.tree = HEAD + row(0x400000000, SOURCE) + row(SOURCE + 1, 0x500000000, offset=0x10300001)
    elif kind == 'mmio':
        host.qmp.tree = HEAD + row(kind='i/o')
    elif kind == 'unknown-AS':
        host.qmp.tree = host.qmp.tree.replace('cpu-memory-0', 'io-memory-0')
    else:
        raw = bytearray(raw)
        struct.pack_into('<Q', raw, 360 + 99 * 8, MAILBOX['pages'][-1])
        raw = bytes(raw)
    error, data, result, _ = exchange(host, incoming=raw)
    assert error < 0 and not data and not result.used and host.source().active is None
    assert host.source().fault and not events(host, 'core_result') and host.core.calls == []
    count = host.qmp.read_count
    assert exchange(host, incoming=raw)[0] == -errno.EIO
    assert host.qmp.read_count == count and host.qmp.running
    assert all(item['actual_source_result'] < 0 and item['returned_bytes'] == 0 for item in events(host, 'response'))


@pytest.mark.parametrize('at,value', [(96, 8888), (100, 8888), (104, 8888), (120, 8888)])
def test_retained_reads_and_release_require_unchanged_original_api40_tuple(host, at, value):
    _, first, r, _ = exchange(host, capacity=64)
    token = r.token
    mutate = lambda h: struct.pack_into('<Q' if at == 120 else '<I', h, at, value)
    for op, args in ((b.READ_RESULT, struct.pack('<QQII', token, len(first), 64, 0)),
                     (b.RELEASE_RESULT, struct.pack('<QQ', token, 0))):
        error, data, result, _ = exchange(host, op, args, capacity=64, mutate=mutate)
        assert error == -errno.EPERM and data == b'' and result.used == 0
    assert host.transfer['cursor'] == 64 and host.core.calls == []


@pytest.mark.parametrize('bad', ['wrong-token', 'stale-token', 'cursor', 'flags0', 'new-core-operation', 'wrong-release-fnv', 'early-release'])
def test_source_stream_never_falls_back_to_core(host, bad):
    _, first, r, _ = exchange(host, capacity=64)
    token = r.token
    if bad in ('wrong-release-fnv', 'early-release'):
        args = struct.pack('<QQ', token, b.fnv64(first))
        error, data, result, _ = exchange(host, b.RELEASE_RESULT, args, capacity=0)
    elif bad == 'new-core-operation':
        error, data, result, _ = exchange(host, b.STATE, capacity=128, flag=0)
    else:
        args = struct.pack('<QQII', token + (bad in ('wrong-token', 'stale-token')), 65 if bad == 'cursor' else 64, 64, 0)
        error, data, result, _ = exchange(host, b.READ_RESULT, args, capacity=64, flag=0 if bad == 'flags0' else 1)
    assert error < 0 and not data and not result.used and host.core.calls == []
    assert host.source().active is not None and host.transfer['cursor'] == 64


@pytest.mark.parametrize('flag', [0, 1])
def test_cancel_calls_original_core_state128_and_clears_source(host, flag):
    _, _, r, _ = exchange(host, capacity=64)
    old_token = r.token
    code, state, result, _ = exchange(host, b.CANCEL, capacity=128, flag=flag)
    assert code == 0 and len(state) == result.used == 128 and host.source().active is None and host.transfer is None
    assert [v[1] for v in host.core.calls] == [b.CANCEL]
    receipt = events(host, 'source_cancel')[-1]
    assert receipt['host_snapshot_cleared'] and receipt['token'] == old_token and receipt['actual_c_result'] == 0
    assert events(host, 'response')[-1]['actual_c_result'] == 0
    old_calls = list(host.core.calls)
    args = struct.pack('<QQII', old_token, 64, 64, 0)
    assert exchange(host, b.READ_RESULT, args, capacity=64)[0] == -errno.ESTALE
    assert exchange(host, b.READ_RESULT, args, capacity=64, flag=0)[0] < 0
    assert host.core.calls == old_calls


def test_late_close_clears_snapshot_then_actual_cancel_destroy_detach_blocks_all_access(host):
    error, data, result, h = exchange(host, capacity=64, publish=False)
    struct.pack_into('<I', host.rsp.data, 12, b.CLOSED)
    assert host.publish(h, data, error, result) is False
    assert host.source().active is None and host.transfer is None and not events(host, 'response')
    assert events(host, 'late_close')[-1]['actual_c_result'] is None
    host.core.execute(MAILBOX['nonce'], b.CANCEL, b'', 128)
    host.core.destroy_model()
    host.detach_mailbox()
    accesses, reads = host.rsp.accesses, host.qmp.read_count
    error, data, result, _ = host.call_source(h, packet(), 64)
    assert error < 0 and not data and not result.used and host.rsp.accesses == accesses and host.qmp.read_count == reads
    assert host.acknowledged and host.rsp.detached


@pytest.mark.parametrize('menu,ap', [('', ''), (s.PROFILE, ''), ('', s.PROFILE), ('strict', 'strict')])
def test_disabled_or_unpaired_functional_profile_rejects_without_source_reads(host, monkeypatch, menu, ap):
    monkeypatch.setenv('MENU_FUNCTIONAL_CAMERA', menu)
    monkeypatch.setenv('A7C2_FUNCTIONAL_CAMERA', ap)
    del host.source_provider
    code, data, result, _ = exchange(host)
    assert code == -errno.ENOTSUP and not data and not result.used and host.qmp.read_count == 0
    assert host.core.calls == []


@pytest.mark.parametrize('running,resume', [(False, True), (True, False)])
def test_source_respects_prior_pause_and_parent_resume_barrier(host, running, resume):
    host.qmp.running = running
    host.resume_allowed = lambda: resume
    assert exchange(host, capacity=64)[0] == 0
    assert not host.qmp.running and 'cont' not in host.qmp.commands


def test_generation_revalidation_failure_prevents_source_access(host, monkeypatch):
    h, raw = request()
    stage(host, h, raw)
    monkeypatch.setattr(b, 'revalidate', lambda config: (_ for _ in ()).throw(ValueError('generation changed')))
    error, data, result, metadata = host.call_source(h, raw, 64)
    assert error < 0 and not data and not result.used and host.qmp.commands == []
    assert metadata['error'] == 'generation changed'


@pytest.mark.parametrize('field,value', [(8, 99), (16, 99), (52, 2), (108, 99), (112, 48)])
def test_bad_mailbox_and_origin_header_is_rejected_before_source(host, field, value):
    with pytest.raises(ValueError):
        exchange(host, mutate=lambda h: struct.pack_into('<Q' if field == 16 else '<I', h, field, value))
    assert host.qmp.read_count == 0 and host.core.calls == []
    assert events(host, 'header_rejected')


def test_snapshot_opcode_is_forbidden_at_ctypes_boundary():
    with pytest.raises(ValueError, match='Invalid core call boundary'):
        b.Core.__new__(b.Core).execute(MAILBOX['nonce'], s.OP, packet(), 64)


class OwnedWire:
    def __init__(self, data):
        self.data, self.cursor, self.sent = data, 0, []

    def settimeout(self, timeout):
        pass

    def recv(self, amount):
        raw = self.data[self.cursor:self.cursor + amount]
        self.cursor += len(raw)
        return raw

    def sendall(self, raw):
        self.sent.append(json.loads(raw))


def qmp_wire(reply):
    qmp = b.QMP.__new__(b.QMP)
    qmp.timeout, qmp.serial, qmp.buffer = 2, 0, bytearray()
    qmp.socket = OwnedWire(reply)
    return qmp


def test_actual_qmp_codec_accepts_whole_409600_byte_hmp_reply_within_4mib():
    raw = bytes((n * 7) & 255 for n in range(s.UNITS[0x1d9]))
    text = dump(SOURCE, raw)
    wire = json.dumps({'id': 1, 'return': text}).encode() + b'\n'
    assert 1024 * 1024 < len(wire) < 4 * 1024 * 1024
    qmp = qmp_wire(wire)
    reply = qmp.execute('human-monitor-command', {'command-line': f'xp /409600bx 0x{SOURCE:x}'})
    assert s.parse_xp(reply, SOURCE, len(raw)) == raw
    assert qmp.socket.sent == [dict(execute='human-monitor-command', id=1,
                                  arguments={'command-line': f'xp /409600bx 0x{SOURCE:x}'})]


@pytest.mark.parametrize('reply', [b'x' * (4 * 1024 * 1024 + 1), b'[]\n', b'{"id":2,"return":"x"}\n',
                                 b'{"id":1,"error":{"class":"GenericError"}}\n'])
def test_qmp_codec_rejects_oversize_invalid_or_wrong_reply(reply):
    with pytest.raises(ValueError):
        qmp_wire(reply).execute('human-monitor-command', {'command-line': 'info mtree -f -o'})


@pytest.mark.parametrize('line', ['cpu 1', 'cpu 0; cont', 'pmemsave 0 4 /tmp/anything', 'info ramblock', 'xp /409601bx 0x410300000',
                                 'xp /1bx 0xfffffffffffffffff', 'xp /0bx 0x410300000', 'xp /4wx 0x410300000',
                                 'xp /409600bx 0xffffffffffffffff', 'xp /8bx 0x1; cont'])
def test_qmp_command_allowlist_does_not_allow_arbitrary_hmp(line):
    qmp = qmp_wire(b'')
    with pytest.raises(ValueError):
        qmp.execute('human-monitor-command', {'command-line': line})
    assert not qmp.socket.sent


@pytest.mark.parametrize('index,unit', list(enumerate(s.UNITS)))
def test_standard_sdk_api40_golden_descriptor_handle_and_zero_offsets(index, unit):
    # Same golden handles/lengths as test-functional-face-transfer.c:sdk_golden.
    raw = bytearray(packet(unit, ap=0x400 + index))
    cp = 0x8402 + index
    struct.pack_into('<I', raw, 12, cp)
    struct.pack_into('<2I', raw, 352, cp, 0)
    h, raw = request(bytes(raw))
    info = s.packet(raw, h, MAILBOX)
    assert info['ap_handle'] == 0x400 + index and info['cp_handle'] == cp
    assert raw[348:352] == bytes(4) and raw[356:360] == bytes(4)
    assert b.u32(raw, 324) == 1


@pytest.mark.parametrize('at', [348, 356])
@pytest.mark.parametrize('value', [1, 0xffffffff])
def test_descriptor_offsets_are_zero_and_are_not_domain_selectors(at, value):
    raw = bytearray(packet())
    struct.pack_into('<I', raw, at, value)
    h, raw = request(bytes(raw))
    with pytest.raises(ValueError, match='offset'):
        s.packet(raw, h, MAILBOX)


@pytest.mark.parametrize('left,right', [(0, 99), (100, 101), (99, 101)])
def test_cp_internal_sdk_internal_and_cp_sdk_gpa_aliases(left, right):
    raw = bytearray(packet())
    raw[360 + right * 8:368 + right * 8] = raw[360 + left * 8:368 + left * 8]
    h, raw = request(bytes(raw))
    with pytest.raises(ValueError, match='alias'):
        s.disjoint(HEAD + row(), s.packet(raw, h, MAILBOX), MAILBOX)


def test_complete_guest_readback_requires_exact_whole_fnv_then_stale_tokens_stay_out_of_core(host):
    raw = packet(0x1da)
    host.qmp.source = host.qmp.source[:s.UNITS[0x1da]]
    code, first, result, _ = exchange(host, incoming=raw)
    assert code == 0 and len(first) == result.total
    token, whole = result.token, b.fnv64(bytes(bytearray(first)))
    assert exchange(host, b.READ_RESULT, struct.pack('<QQII', token, len(first), 1, 0), capacity=1)[0] == -errno.ERANGE
    assert exchange(host, b.RELEASE_RESULT, struct.pack('<QQ', token, whole ^ 1), capacity=0)[0] == -errno.EBADMSG
    assert host.source().active is not None and host.transfer['cursor'] == len(first)
    assert exchange(host, b.RELEASE_RESULT, struct.pack('<QQ', token, whole), capacity=0)[0] == 0
    for flag in (0, 1):
        assert exchange(host, b.RELEASE_RESULT, struct.pack('<QQ', token, whole), capacity=0, flag=flag)[0] < 0
    assert host.core.calls == []
    code, _, next_result, _ = exchange(host, incoming=raw)
    assert code == 0 and next_result.token > token


def test_duplicate_snapshot_cannot_replace_an_existing_lease(host):
    assert exchange(host, capacity=64)[0] == 0
    active = host.source().active
    code, data, result, _ = exchange(host, capacity=64)
    assert code == -errno.EBUSY and not data and not result.used and host.source().active is active
    assert host.qmp.read_count == 2 and host.core.calls == []


def test_original_cancel_error_still_discards_host_snapshot(host, monkeypatch):
    assert exchange(host, capacity=64)[0] == 0
    def failed(instance, op, raw, capacity):
        host.core.calls.append((instance, op, raw, capacity))
        assert op == b.CANCEL
        return -errno.EIO, b'', b.ExecResult()
    monkeypatch.setattr(host.core, 'execute', failed)
    code, data, result, _ = exchange(host, b.CANCEL, capacity=128)
    assert code == -errno.EIO and not data and not result.used
    assert host.source().active is None and host.transfer is None
    assert events(host, 'source_cancel')[-1]['actual_c_result'] == -errno.EIO
    assert events(host, 'core_result')[-1]['actual_c_result'] == -errno.EIO


def test_source_content_is_never_published_after_staged_mailbox_corruption(host, monkeypatch):
    error, data, result, h = exchange(host, capacity=64, publish=False)
    real_write = host.rsp.write
    def corrupt(address, raw):
        real_write(address, raw)
        if address == MAILBOX['phys0'] + b.HEADER:
            host.rsp.data[b.HEADER] ^= 1
    monkeypatch.setattr(host.rsp, 'write', corrupt)
    with pytest.raises(ValueError, match='readback'):
        host.publish(h, data, error, result)
    assert b.u32(host.rsp.data, 12) == b.REQUEST and not events(host, 'response')
    assert not events(host, 'core_result')
    host.clear_source('test_cleanup_after_readback_failure')
    assert host.source().active is None and host.transfer is None


def test_core_result_tokens_cannot_enter_source_namespace():
    host = b.Broker.__new__(b.Broker)
    host.transfer = None
    with pytest.raises(ValueError, match='invalid bytes'):
        host.observe_transfer(bytes(header(b.STILL, flag=0)), b'', b'x', 0, b.ExecResult(s.TOKEN_BASE | 1, 1, 0, 1))
    assert host.transfer is None


def test_source_snapshot_rejects_nonpaused_debug_state(host, monkeypatch):
    host.qmp.running = False
    monkeypatch.setattr(host.qmp, 'status', lambda: dict(running=False, status='debug'))
    code, data, result, _ = exchange(host, capacity=64)
    assert code < 0 and not data and not result.used and host.qmp.read_count == 0


def test_source_snapshot_has_no_effect_on_existing_frame_proof_or_counters(host):
    previous = dict(serial=37, after=dict(rendered=30, consumed=29))
    host.last_frame = previous
    assert exchange(host, capacity=64)[0] == 0
    assert host.last_frame is previous and previous == dict(serial=37, after=dict(rendered=30, consumed=29))
    assert host.core.proofs == 0 and host.core.calls == [] and not events(host, 'model_frame')
