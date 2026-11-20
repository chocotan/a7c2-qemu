"""Unexecuted host-test draft. Fake transports only; the real runtime gate stays closed."""
import hashlib
import io
import json
from pathlib import Path
import re
import runpy
import struct
import subprocess
from types import SimpleNamespace

import pytest
from PIL import Image

import usb_msc
import usb_scheduler as scheduler
from sony_usb_device import PROFILE

CONTRACT = dict(source_sha256='a'*64, binary_sha256='b'*64)
BASE = 0x400000
MANAGER = BASE+0x910a108
HEAD = MANAGER+0x310+6*0x90+0x10


def record(kind, **values):
    return 'SNAPSHOT_'+kind+' '+' '.join(key+'='+str(value) for key, value in values.items())+'\n'


def raw_chunks(kind, identifier, value):
    return ''.join(record(kind, id=identifier, offset=offset, bytes=len(value[offset:offset+64]),
                          hex=value[offset:offset+64].hex()) for offset in range(0, len(value), 64))


def sample(phase='before-enter', pid='12', start='345', *, pending=0, active=False,
           dependencies=0, user_stack=False):
    assert active or dependencies == 0
    maps = b'400000-401000 r-xp 00000000 00:01 7 /usr/lib/appFw.so\n'
    nodes = [0x10000+32*i for i in range(pending)]
    active_address = 0x20000 if active else 0
    header = bytearray(0x90)
    first, last = (nodes[0], nodes[-1]) if nodes else (HEAD, HEAD)
    struct.pack_into('<Q', header, 0, MANAGER)
    struct.pack_into('<I', header, 8, 6)
    struct.pack_into('<QQQ', header, 0x10, first, last, pending)
    struct.pack_into('<Q', header, 0x88, active_address)
    text = record('BEGIN', phase=phase, pid=pid, start=start, base=hex(BASE),
                  source_sha256=CONTRACT['source_sha256'], app_sha256=scheduler.APP_SHA,
                  exe_sha256=scheduler.EXE_SHA, monotonic='1.000000000')
    text += record('MAPS', sha256=hashlib.sha256(maps).hexdigest(), bytes=len(maps), device='0:1', inode=7)
    text += raw_chunks('MAPS_BYTES', 0, maps)
    text += record('SCHED_HEADER', base=hex(BASE), first=hex(first), last=hex(last),
                   pending=pending, active=hex(active_address), no_lock=1)

    def scheduled(index, address):
        control = bytearray(0x1b8)
        struct.pack_into('<I', control, 8, 0x31+index)
        struct.pack_into('<Q', control, 0x10, 0x1234+index)
        if index == 0:
            struct.pack_into('<QQQ', control, 0x1a0, 0x30000, 0x30000+24*dependencies,
                             0x30000+24*dependencies)
        body = record('SCHEDULED_READ', index=index, object_readable=1,
                      control_readable=1, run_readable=1, token_readable=1)
        body += record('SCHEDULED', role='pending' if index else 'active', index=index,
                       object=hex(address), control=hex(0x40000+index*0x200), id=hex(0x31+index),
                       token=hex(0x1234+index), run='0x34796b0', stable=1, msc_run=1)
        body += raw_chunks('OBJECT', index, struct.pack('<QQ', 0x50000, 0x40000+index*0x200))
        body += raw_chunks('CONTROL', index, control)
        if index == 0:
            for dependency in range(dependencies):
                future = 0x60000+dependency*0x100
                body += record('DEPENDENCY_STATE', index=dependency, future=hex(future),
                               status='0x1', status_readable=1, stable=1, identity_unverified=1)
                body += raw_chunks('DEPENDENCY', dependency, struct.pack('<QQQ', future, 0, 0))
        return body

    if active:
        text += scheduled(0, active_address)
    for index, node in enumerate(nodes):
        address = 0x21000+index*0x20
        text += raw_chunks('NODE', index+1, struct.pack('<QQQ',
            nodes[index+1] if index+1 < len(nodes) else HEAD,
            nodes[index-1] if index else HEAD, address))
        text += scheduled(index+1, address)
    text += record('SCHED_STABILITY', header_equal=1, visited=pending, pending=pending,
                   complete=1, stable=1, atomic=0)
    text += raw_chunks('SCHED_HEADER_BYTES', 0, header)
    syscall = b'0 0x1 0x2 0x3 0x4 0x5 0x6 0x70000 0x80000\n' if user_stack else b'running\n'
    for field, value in [('comm', b'im\n'), ('wchan', b'futex_wait\n'), ('stack', b'frame\n'),
                         ('syscall', syscall)]:
        text += record('THREAD', tid=12, start=345, start_readable=1, field=field,
                       readable=1, bytes=len(value), errno=0)
        text += raw_chunks('THREAD_'+field.upper()+'_BYTES', 12, value)
    if user_stack:
        text += record('THREAD_USER_STACK', tid=12, sp='0x70000', pc='0x80000', syscall=0,
                       raw_candidates_only=1)
        text += raw_chunks('THREAD_USER_STACK_BYTES', 12, bytes(range(256))*2)
    text += record('THREAD_END', tid=12, generation_equal=1)
    text += record('THREADS_END', visited=1, complete=1, limit=512, atomic=0)
    text += record('END', phase=phase, pid=pid, start=start, generation_equal=1,
                   maps_equal=1, file_identity_equal=1, pending_complete=1,
                   scheduler_stable=1, threads_complete=1, reads_complete=1, atomic=0)
    return (text+'PRODUCT_MSC_SCHEDULER_RC=0\n').encode()


def test_default_has_no_compiler_or_guest_action(monkeypatch, tmp_path):
    monkeypatch.setattr(subprocess, 'run', lambda *_a, **_k: pytest.fail('compiler must remain off'))
    assert scheduler.prepare({}, tmp_path) == {}
    scheduler.runtime_preflight({})
    assert not scheduler.enabled({}) and not list(tmp_path.iterdir())


@pytest.mark.parametrize('value', ['', '0', 'true', '2'])
def test_explicit_value_must_be_one(value):
    with pytest.raises(ValueError):
        scheduler.enabled({'A7C2_USB_MSC_SCHEDULER': value,
                           'A7C2_USB_MSC': '1', 'A7C2_SONY_USB_DEVICE': PROFILE})


@pytest.mark.parametrize('pending,active,dependencies,user_stack', [
    (0, False, 0, False), (2, False, 0, True), (0, True, 2, True), (2, True, 2, True)])
def test_positive_result_is_observation_only(pending, active, dependencies, user_stack):
    settings = dict(pending=pending, active=active, dependencies=dependencies, user_stack=user_stack)
    before = scheduler.parse(sample(**settings), 'before-enter', CONTRACT)
    after = scheduler.parse(sample('after-enter', **settings), 'after-enter', CONTRACT, before)
    assert after['process_identity_verified'] and after['pending_complete'] and after['threads_complete']
    assert after['scheduler_group'] == 6
    assert not after['atomic'] and not after['submission_absence_proven']


@pytest.mark.parametrize('old,new', [
    (b'pending_complete=1', b'pending_complete=0'),
    (b'scheduler_stable=1', b'scheduler_stable=0'),
    (b'reads_complete=1', b'reads_complete=0'),
    (b'threads_complete=1', b'threads_complete=0'),
    (b'maps_equal=1', b'maps_equal=0'),
    (b'generation_equal=1', b'generation_equal=0'),
    (b'PRODUCT_MSC_SCHEDULER_RC=0', b'PRODUCT_MSC_SCHEDULER_RC=79'),
    (b'SNAPSHOT_THREAD_END tid=12 generation_equal=1\n', b''),
    (b'field=stack readable=1', b'field=stack readable=0'),
    (b'start_readable=1', b'start_readable=0'),
    (b'pending=0 active=0x0', b'pending=1 active=0x0'),
    (b'source_sha256='+b'a'*64, b'source_sha256='+b'c'*64),
])
def test_unknown_incomplete_or_mismatched_never_accepted(old, new):
    with pytest.raises(ValueError):
        scheduler.parse(sample().replace(old, new), 'before-enter', CONTRACT)


@pytest.mark.parametrize('field,value', [('pid', '13'), ('start', '346'), ('base', '0x500000')])
def test_same_generation_required_across_enter(field, value):
    before = scheduler.parse(sample(), 'before-enter', CONTRACT)
    raw = sample('after-enter').replace((field+'='+before[field]+' ').encode(),
                                      (field+'='+value+' ').encode())
    with pytest.raises(ValueError, match='generation differs'):
        scheduler.parse(raw, 'after-enter', CONTRACT, before)


@pytest.mark.parametrize('prefix', [b'SNAPSHOT_SCHED_HEADER_BYTES ', b'SNAPSHOT_NODE ',
    b'SNAPSHOT_OBJECT ', b'SNAPSHOT_CONTROL ', b'SNAPSHOT_DEPENDENCY_STATE ',
    b'SNAPSHOT_DEPENDENCY ', b'SNAPSHOT_THREAD_USER_STACK ', b'SNAPSHOT_THREAD_USER_STACK_BYTES '])
@pytest.mark.parametrize('mutation', ['missing', 'duplicate', 'reorder'])
def test_required_raw_records_have_exact_count_and_order(prefix, mutation):
    lines = sample(pending=2, active=True, dependencies=2, user_stack=True).splitlines(keepends=True)
    index = next(i for i, line in enumerate(lines) if line.startswith(prefix))
    if mutation == 'missing':
        del lines[index]
    elif mutation == 'duplicate':
        lines.insert(index, lines[index])
    else:
        lines[index], lines[index+1] = lines[index+1], lines[index]
    with pytest.raises(ValueError):
        scheduler.parse(b''.join(lines), 'before-enter', CONTRACT)


@pytest.mark.parametrize('offset', [0, 8, 0x10, 0x18, 0x20, 0x88])
def test_header_raw_owner_number_list_count_active_must_match(offset):
    lines = sample(pending=2, active=True, dependencies=2).splitlines(keepends=True)
    index = next(i for i, line in enumerate(lines) if line.startswith(b'SNAPSHOT_SCHED_HEADER_BYTES ') and
                 b'offset='+str(offset//64*64).encode()+b' ' in line)
    prefix, value = lines[index].split(b'hex=')
    raw = bytearray.fromhex(value.decode())
    raw[offset % 64] ^= 1
    lines[index] = prefix+b'hex='+raw.hex().encode()+b'\n'
    with pytest.raises(ValueError, match='0x90-byte header'):
        scheduler.parse(b''.join(lines), 'before-enter', CONTRACT)


@pytest.mark.parametrize('old,new', [
    (b'role=pending index=1', b'role=active index=1'),
    (b'run=0x34796b0 stable=1', b'run=0x34796b0 stable=0'),
    (b'index=1 object=0x21000', b'index=1 object=0x21020'),
    (b'active=0x20000', b'active=0x20010'),
    (b'status_readable=1', b'status_readable=0'),
    (b'future=0x60000', b'future=0x60010'),
    (b'index=1 future=', b'index=0 future='),
    (b'sp=0x70000', b'sp=0x70010'),
    (b'pc=0x80000', b'pc=0x80010'),
    (b'bytes=64 hex=000102', b'bytes=63 hex=000102'),
])
def test_pending_dependency_and_user_stack_identity_mismatches(old, new):
    raw = sample(pending=2, active=True, dependencies=2, user_stack=True)
    assert old in raw
    with pytest.raises(ValueError):
        scheduler.parse(raw.replace(old, new), 'before-enter', CONTRACT)


def test_duplicate_header_fields_and_extra_stack_declarations_rejected():
    raw = sample()
    for altered in (raw.replace(b'pending=0 active=', b'pending=0 pending=0 active='),
            raw.replace(b'SNAPSHOT_THREAD_END ',
                        b'SNAPSHOT_THREAD_USER_STACK tid=12 sp=0x1 pc=0x2 syscall=0 raw_candidates_only=1\nSNAPSHOT_THREAD_END '),
            raw.replace(b'SNAPSHOT_END ', b'SNAPSHOT_UNKNOWN field=value\nSNAPSHOT_END ')):
        with pytest.raises(ValueError):
            scheduler.parse(altered, 'before-enter', CONTRACT)


def test_truncation_and_reordered_maps_rejected():
    for raw in (sample().split(b'SNAPSHOT_END')[0],
                sample().replace(b'MAPS_BYTES id=0 offset=0', b'MAPS_BYTES id=0 offset=4')):
        with pytest.raises(ValueError):
            scheduler.parse(raw, 'before-enter', CONTRACT)


def test_explicit_incomplete_and_both_output_limits_are_rejected(monkeypatch):
    raw = sample()
    with pytest.raises(ValueError):
        scheduler.parse(raw.replace(b'SNAPSHOT_END ', b'SNAPSHOT_INCOMPLETE reason=output-budget emitted=1 limit=4194304 reserve=4096\nSNAPSHOT_END '), 'before-enter', CONTRACT)
    monkeypatch.setattr(scheduler, 'TOOL_OUTPUT_LIMIT', len(raw)//2)
    with pytest.raises(ValueError, match='tool output'):
        scheduler.parse(raw, 'before-enter', CONTRACT)
    monkeypatch.setattr(scheduler, 'SERIAL_LIMIT', len(raw)-1)
    with pytest.raises(ValueError, match='serial output'):
        scheduler.parse(raw, 'before-enter', CONTRACT)


def test_failure_is_saved_and_exclusive(tmp_path):
    received = []
    def serial(command):
        received.append(command)
        return sample().replace(b'reads_complete=1', b'reads_complete=0')
    with pytest.raises(ValueError):
        scheduler.collect(serial, tmp_path, 'before-enter', CONTRACT)
    raw = tmp_path/'usb-msc-scheduler-before-enter.raw'
    assert raw.read_bytes().count(b'reads_complete=0') == 1
    assert raw.with_suffix('.error.json').exists()
    with pytest.raises(FileExistsError):
        scheduler.collect(serial, tmp_path, 'before-enter', CONTRACT)
    assert len(received) == 1


@pytest.mark.parametrize('save_stage', ['raw', 'error-json'])
def test_collect_boundary_loss_keeps_original_when_preservation_fails(monkeypatch, tmp_path, save_stage):
    original = scheduler.SerialBoundaryLost('synthetic boundary loss', b'partial sample')
    save_error = OSError('synthetic '+save_stage+' save failure')

    def serial(_command):
        raise original

    def fail_save(*_args, **_kwargs):
        raise save_error

    monkeypatch.setattr(scheduler, '_write_readback' if save_stage == 'raw' else '_json', fail_save)
    with pytest.raises(scheduler.SerialBoundaryLost) as caught:
        scheduler.collect(serial, tmp_path, 'before-enter', CONTRACT)
    assert caught.value is original
    assert caught.value.raw == b'partial sample'
    assert caught.value.__notes__ == ['Scheduler evidence preservation failed: OSError: '+str(save_error)]
    if save_stage == 'error-json':
        assert (tmp_path/'usb-msc-scheduler-before-enter.raw').read_bytes() == original.raw


def test_collect_parse_error_keeps_original_when_preservation_fails(monkeypatch, tmp_path):
    raw = sample().replace(b'reads_complete=1', b'reads_complete=0')

    def fail_save(*_args, **_kwargs):
        raise OSError('synthetic error-json save failure')

    monkeypatch.setattr(scheduler, '_json', fail_save)
    with pytest.raises(ValueError, match='Scheduler receipt incomplete, duplicated or failed') as caught:
        scheduler.collect(lambda _command: raw, tmp_path, 'before-enter', CONTRACT)
    assert type(caught.value) is ValueError
    assert caught.value.__notes__ == ['Scheduler evidence preservation failed: OSError: synthetic error-json save failure']
    assert (tmp_path/'usb-msc-scheduler-before-enter.raw').read_bytes() == raw


@pytest.fixture
def fake_transport(tmp_path, monkeypatch):
    import menu_live
    import console_wakeup
    console = tmp_path/'console.log'
    original = b'original console retained\n'
    console.write_bytes(original)
    class Wakeup:
        def __init__(self, _console):
            pass
        def __enter__(self):
            return self
        def __exit__(self, *_args):
            pass
        def wait(self, _seconds):
            if process.stdin.pending:
                with console.open('ab') as stream:
                    stream.write(process.stdin.pending.pop(0))
    monkeypatch.setattr(console_wakeup, 'ConsoleWakeup', Wakeup)
    monkeypatch.setattr(menu_live, 'FirmwareMonitor', lambda _path: SimpleNamespace(check=lambda: None))
    ticks = iter(range(1000))
    monkeypatch.setattr(scheduler.time, 'monotonic', lambda: next(ticks)/100)
    class Input(io.BytesIO):
        response = b''
        partial = False
        pending = None
        def write(self, wire):
            super().write(wire)
            return len(wire)-int(self.partial)
        def flush(self):
            wire = self.getvalue()
            marker = b'MSC_SCHED_DONE_'+re.search(rb"DONE_([0-9a-f]{24})", wire)[1]
            assert b'MSC_SCHED_DONE_' not in wire
            response = self.response(marker, wire) if callable(self.response) else self.response
            if response == b'completion':
                response = b'\n'+marker+b':0\n'
            self.pending = list(response) if isinstance(response, (list, tuple)) else [response]
            with console.open('ab') as stream:
                stream.write(self.pending.pop(0))
    process = SimpleNamespace(stdin=Input(), poll=lambda: None)
    return process, scheduler.SchedulerSerial(process, console, timeout=3), original


@pytest.mark.parametrize('failure', ['overflow', 'timeout', 'wrong-boundary', 'partial-write'])
def test_serial_boundary_loss_poisoning_and_raw_console_retention(fake_transport, monkeypatch, failure):
    process, serial, original = fake_transport
    if failure == 'overflow':
        monkeypatch.setattr(scheduler, 'SERIAL_LIMIT', 128)
        process.stdin.response = b'x'*129
    elif failure == 'wrong-boundary':
        process.stdin.response = b'\nMSC_SCHED_DONE_old:0\n'
    elif failure == 'partial-write':
        process.stdin.partial = True
    with pytest.raises(scheduler.SerialBoundaryLost):
        serial('echo harmless')
    first_wire = process.stdin.getvalue()
    assert serial.poisoned and process._menu_serial_desynchronized and process._msc_scheduler_owner_required
    assert serial.console.read_bytes().startswith(original)
    with pytest.raises(scheduler.SerialBoundaryLost, match='no further guest commands'):
        serial('echo must-never-be-sent')
    assert process.stdin.getvalue() == first_wire


def test_completed_boundary_and_command_line_bound(fake_transport):
    process, serial, original = fake_transport
    with pytest.raises(ValueError, match='1000'):
        serial('x'*1001)
    assert process.stdin.getvalue() == b'' and not serial.poisoned
    process.stdin.response = b'completion'
    assert b'MSC_SCHED_DONE_' in serial('echo harmless')
    assert not serial.poisoned and serial.console.read_bytes().startswith(original)


def test_collect_preserves_partial_and_never_claims_exit(fake_transport, monkeypatch, tmp_path):
    process, serial, original = fake_transport
    monkeypatch.setattr(scheduler, 'SERIAL_LIMIT', 128)
    process.stdin.response = b'x'*129
    with pytest.raises(scheduler.SerialBoundaryLost):
        scheduler.collect(serial, tmp_path, 'before-enter', CONTRACT)
    raw = tmp_path/'usb-msc-scheduler-before-enter.raw'
    error = json.loads(raw.with_suffix('.error.json').read_text())
    assert raw.read_bytes() == b'x'*129
    assert error['raw_sha256'] == hashlib.sha256(raw.read_bytes()).hexdigest()
    assert not error['exit_verified'] and error['persistent_owner_required'] and error['serial_boundary_lost']
    assert serial.console.read_bytes() == original+b'x'*129


def test_missing_owner_blocks_before_any_probe_action(monkeypatch, tmp_path):
    monkeypatch.setattr(usb_msc, 'action', lambda *_a: pytest.fail('must block before cable action'))
    monkeypatch.setattr(usb_msc, 'serial_command', lambda *_a, **_k: pytest.fail('must block before guest commands'))
    profile = {'A7C2_USB_MSC_SCHEDULER': '1', 'A7C2_USB_MSC': '1', 'A7C2_SONY_USB_DEVICE': PROFILE}
    with pytest.raises(RuntimeError, match='persistent disk owner'):
        scheduler.runtime_preflight(profile)
    with pytest.raises(RuntimeError, match='persistent disk owner'):
        usb_msc.probe(object(), tmp_path, lambda *_a: pytest.fail('no QMP'), scheduler_contract=CONTRACT)
    assert not list(tmp_path.iterdir())


def test_launcher_preserves_existing_precheck_and_rejects_explicit_runtime(monkeypatch):
    api = runpy.run_path(str(Path(__file__).resolve().parents[2]/'tools/run-original-cold.py'))
    monkeypatch.setenv('A7C2_SONY_USB_DEVICE', PROFILE)
    monkeypatch.setenv('A7C2_USB_DEVICE_BUILD', '/virtual/receipt.json')
    for name in ('A7C2_USB_EE_NORMAL_COLD', 'A7C2_USB_EE_NORMAL_COLD_INPUT', 'A7C2_USB_MSC_SCHEDULER'):
        monkeypatch.delenv(name, raising=False)
    environment = {'A7C2_USB_MSC_SCHEDULER': 'stale'}
    api['usb_msc_environment'](environment)
    assert 'A7C2_USB_MSC_SCHEDULER' not in environment
    monkeypatch.setenv('A7C2_USB_MSC_SCHEDULER', '1')
    with pytest.raises(RuntimeError, match='persistent disk owner'):
        api['usb_msc_environment']({})
    monkeypatch.setenv('A7C2_USB_MSC_SCHEDULER', '0')
    with pytest.raises((ValueError, RuntimeError)):
        api['usb_msc_environment']({})


def test_elf_interpreter_and_wrong_machine_rejected():
    data = bytearray(120)
    data[:7] = b'\x7fELF\x02\x01\x01'
    struct.pack_into('<HH', data, 16, 2, 183)
    struct.pack_into('<Q', data, 32, 64)
    struct.pack_into('<HH', data, 54, 56, 1)
    struct.pack_into('<II', data, 64, 1, 5)
    scheduler.static_aarch64(bytes(data))
    struct.pack_into('<I', data, 64, 3)
    with pytest.raises(ValueError):
        scheduler.static_aarch64(bytes(data))
    struct.pack_into('<II', data, 64, 1, 5)
    struct.pack_into('<H', data, 18, 62)
    with pytest.raises(ValueError):
        scheduler.static_aarch64(bytes(data))


@pytest.mark.parametrize('failed_phase', [None, 'before-enter', 'after-enter', 'lost-boundary'])
def test_host_only_original_enter_order_and_boundary_failure(tmp_path, monkeypatch, failed_phase):
    # Only this fake-transport test bypasses the fixed gate. No test starts a VM.
    monkeypatch.setattr(scheduler, 'require_runtime_owner', lambda: None)
    calls = []
    process = SimpleNamespace()
    def action(_run, operation):
        calls.append(operation)
        return dict(cable_connected=operation == 'connect', host_enumerated=True)
    def collect(_serial, run, phase, contract, previous=None):
        assert contract is CONTRACT
        calls.append(phase)
        if failed_phase == 'lost-boundary':
            process._menu_serial_desynchronized = True
            raise scheduler.SerialBoundaryLost('unknown guest command state', b'partial')
        if phase == 'after-enter':
            assert previous['pid'] == '12'
            assert (run/'usb-msc-enter.raw').read_bytes() == b'original ENTER'
        if failed_phase == phase:
            raise ValueError('sampling incomplete; submission unobserved')
        return dict(pid='12', start='345', base=hex(BASE))
    def tap(*_args):
        calls.append('ENTER')
        return b'original ENTER', [1, 2]
    def qmp(_command, arguments):
        Image.new('RGB', (640, 480), (1, 2, 3)).save(tmp_path/Path(arguments['filename']).name)
    monkeypatch.setattr(usb_msc, 'action', action)
    monkeypatch.setattr(scheduler, 'collect', collect)
    monkeypatch.setattr(usb_msc, '_select_msc', lambda *_a: dict(selected_pixels_sha256='0'*64))
    monkeypatch.setattr(usb_msc, '_tap_original', tap)
    monkeypatch.setattr(usb_msc, 'serial_command', lambda *_a, **_k: b'')
    monkeypatch.setattr(usb_msc.time, 'sleep', lambda _s: None)
    if failed_phase == 'lost-boundary':
        with pytest.raises(scheduler.SerialBoundaryLost):
            usb_msc.probe(process, tmp_path, qmp, scheduler_contract=CONTRACT)
        assert calls == ['connect', 'before-enter']
        assert not (tmp_path/'usb-msc-enter.raw').exists()
        result = json.loads((tmp_path/'usb-msc-result.json').read_text())
        assert not result['exit_verified'] and result['persistent_owner_required']
        assert result['usb_state_retained'] and result['disconnect_skipped'] == 'serial-boundary-lost'
        return
    result = usb_msc.probe(process, tmp_path, qmp, scheduler_contract=CONTRACT)
    if failed_phase == 'before-enter':
        assert calls == ['connect', 'before-enter', 'disconnect']
        assert not (tmp_path/'usb-msc-enter.raw').exists()
    else:
        assert calls[:4] == ['connect', 'before-enter', 'ENTER', 'after-enter']
        assert (tmp_path/'usb-msc-enter.raw').read_bytes() == b'original ENTER'
    assert calls[-1] == 'disconnect' and not result['msc_verified']
    if failed_phase:
        assert result['phase'] == 'failed-preserved'
