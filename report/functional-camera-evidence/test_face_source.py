"""Synthetic current-run evidence, with 514304 actual owned and retained bytes.

Uses the production broker Snapshot/PayloadRecords/READ/RELEASE/publication paths
against owned QMP/mailbox protocol mocks. Never starts a VM, C model or device.
"""
import copy
import importlib.util
import io
import json
from pathlib import Path
import struct
import sys
from unittest import mock

import pytest

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('source_capture_evidence_test', HERE / 'check_evidence.py')
checker = importlib.util.module_from_spec(spec)
exec(compile(spec.loader.get_source(spec.name), spec.origin, 'exec'), checker.__dict__)
source_checker = checker.source_module(HERE / 'check_face_source.py')
with mock.patch.object(sys, 'path', [str(checker.RUNTIME), *sys.path]):
    host = checker.source_module(checker.RUNTIME / 'test_functional_face_source_snapshot.py')
b, s = host.b, host.s


def source_fixture(root, monkeypatch, width=8, initially_paused=False, inband_cancel=False):
    run = root / 'HOST_TEST_source'
    run.mkdir(mode=0o700)
    factory = host.host.__wrapped__(run, monkeypatch)
    broker = next(factory)
    broker.qmp.running = not initially_paused
    mailbox = broker.mailbox
    pid, tid, nonce = mailbox['pid'], 1235, mailbox['nonce']
    owner = dict(pid=177, starttime=100, ppid=1, exe='/HOST_TEST/python')
    qemu = dict(pid=178, starttime=101, ppid=177, exe='/HOST_TEST/qemu-system-aarch64')
    broker.config = dict(run=str(run), run_identity=[run.stat().st_dev, run.stat().st_ino],
                         qemu_sha256=checker.QEMU_SHA256, owner=owner, qemu=qemu)
    build = dict(model_sha256='a' * 64, model_build_sha256='b' * 64, model_source_archive_sha256='c' * 64)
    broker.emit('binding', mailbox=mailbox, actual_core_sha256=build['model_sha256'], config=broker.config,
        payload_policy=dict(directory='functional-camera-data', per_file_bytes=64 * 1024**2,
                            total_bytes=512 * 1024**2, max_files=65536, source_kind='actual_hardware_transfer'))
    broker.emit('attached', connected=True, model_created=False, protocol_physmode_restored=True)
    original_execute = broker.core.execute
    broker.core.execute = lambda instance, op, raw, capacity: original_execute(
        instance, b.STATE if op == b.INIT else op, raw, capacity)
    console = []
    owned = []
    def row(tag, **fields):
        console.append('OBS ' + tag + ' ' + ' '.join(f'{k}={v}' for k, v in fields.items()))
    def exchange(op, incoming, origin, flags, capacity=b.DATA):
        h = host.header(op, incoming, seq=broker.sequence + 1, capacity=capacity, flag=flags)
        struct.pack_into('<5I', h, 96, *(origin[k] for k in ('producer_tid', 'source', 'destination', 'command', 'bytes')))
        struct.pack_into('<Q', h, 120, origin['fnv1a64'])
        h = bytes(h)
        host.stage(broker, h, incoming)
        request, actual = broker.fetch()
        error, output, result = broker.call_core(request, actual, capacity)
        assert error == 0 and broker.publish(request, output, error, result)
        staged = bytes(broker.rsp.data[b.HEADER:b.HEADER + result.used])
        assert staged == output
        return result, staged
    def transfer(first, op, data, output, token, origin):
        row('FUNCTIONAL_CAMERA_TRANSFER', seq=f'{first}..{broker.sequence}', op=op,
            source=hex(origin['source']), destination=hex(origin['destination']), command=hex(origin['command']),
            bytes=origin['bytes'], native_fnv=hex(origin['fnv1a64']), request_bytes=len(data),
            request_fnv=hex(b.fnv64(data)), returned_bytes=len(output), returned_fnv=hex(b.fnv64(output)),
            required=len(output), destination_written_bytes=len(output), destination_fnv=hex(b.fnv64(output)),
            model_instance=hex(nonce), token=hex(token), readback_closed=1, error=0)
    native = dict(producer_tid=tid, source=0x802a0116, destination=0x82830752,
                  command=0x30304, bytes=104, fnv1a64=b.fnv64(b'HOST_TEST initial'))
    result, output = exchange(1, b'', native, 0)
    transfer(1, 1, b'', output, 0, native)
    for index, (unit, length) in enumerate(s.UNITS.items()):
        ap, cp = 0x92a + index, 0x8c02 + index
        birth, share, opened = 41 + index * 10, 43 + index * 10, 44 + index * 10
        close, freed = opened + 1, opened + 2
        token = 0xface000000000001 + index
        physical = host.SOURCE
        raw = bytearray(host.packet(unit, ap=ap))
        struct.pack_into('<Q', raw, 32, token)
        struct.pack_into('<Q', raw, 56, pid << 32 | 0x46414345)
        struct.pack_into('<3Q', raw, 80, birth, share, opened)
        raw = bytes(raw)
        api40 = raw[304:344]
        callback, context = struct.unpack_from('<2Q', api40, 24)
        native = dict(producer_tid=tid, source=ap, destination=cp, command=s.COMMAND,
                      bytes=40, fnv1a64=b.fnv64(api40))
        def proc(phase, owners, opens):
            actual = (f'{ap:04x}     {unit:08x}  {2 if opens else 1:04x}    {owners:02x}     {opens:02x}    '
                      f'00    {ap >> 10:02x}      00004567  {physical:09x}  {length:08x}  0456').encode()
            row('FUNCTIONAL_FACE_DMM_PROC_READ', pid=pid, tid=tid, birth_observation=birth, **{'pass': phase},
                unit=hex(unit), handle=hex(ap), eof=1, table_bytes=4096, table_fnv=hex(b.fnv64(actual)), parse_rc=0,
                diagnostic_only=1, atomic_snapshot_verified=0, competing_readers_excluded=0, capture_verified=0)
            for offset in range(0, len(actual), 128):
                chunk = actual[offset:offset + 128]
                row('FUNCTIONAL_FACE_DMM_PROC_ROW', pid=pid, tid=tid, birth_observation=birth,
                    **{'pass': phase}, row_offset=256, row_bytes=len(actual), chunk_offset=offset,
                    chunk_bytes=len(chunk), raw=chunk.hex(), diagnostic_only=1)
        def metadata(owners, opens, transaction):
            proc(3, owners, opens)
            proc(4, owners, opens)
            row('FUNCTIONAL_FACE_SOURCE_CURRENT_METADATA', pid=pid, tid=tid, unit=hex(unit), handle=hex(ap),
                birth_observation=birth, native_transaction=transaction, software_allocation_token=hex(token), rc=0,
                relation='0x4567', generation=ap >> 10, owners=owners, opens=opens, state=2 if opens else 1,
                address=hex(physical), bytes=length, extent_id='0x456', shares=0, segments=1,
                diagnostic_only=1, native_atomicity_verified=0, original_global_writer_exclusion_verified=0,
                capture_verified=0)
        def ticket(op, observation, request=None, reply=None):
            queue = 0x80946180
            if request is None:
                request = bytearray(40)
                struct.pack_into('<3I', request, 0, op, unit if op == 0x20 else 0, 0 if op == 0x20 else ap)
                if op == 0x23:
                    struct.pack_into('<H', request, 20, queue & 0xffff)
                request = bytes(request)
            if reply is None:
                reply = bytearray(40)
                struct.pack_into('<Hh', reply, 0, op | 0x8000, 0)
                struct.pack_into('<I', reply, 12, ap)
                reply = bytes(reply)
            for event in (1, 2, 3, 4):
                row('FUNCTIONAL_FACE_DMM_AP_OBSERVATION', pid=pid, tid=tid, event=event, observation=observation,
                    sender_tid=tid, active=int(event != 4), source=hex(queue), op=hex(op), unit=hex(unit) if op in (0x20, 0x21) else 0,
                    handle=0 if op == 0x20 else hex(ap), request='0x700000', send_seen=int(event >= 2), send_rc=0,
                    received=int(event >= 3), reply='0x710000' if event >= 3 else 0,
                    reply_source='0x61003c' if event >= 3 else 0, reply_bytes=40 if event >= 3 else 0,
                    free_attempts=int(event == 4), free_rc=0, dropped=0, request_raw=request.hex(),
                    reply_raw=reply.hex() if event >= 3 else bytes(40).hex(), observation_only=1,
                    allocation_pin_verified=0, capture_verified=0)
        def command(op, observation, request=None, reply=None):
            ticket(op, observation, request, reply)
            row('FUNCTIONAL_FACE_DMM_NATIVE_AP_COMMAND', pid=pid, tid=tid, op=hex(op), unit=hex(unit), handle=hex(ap),
                birth_observation=birth, transaction=observation, helper_error=0, capture_rc=0, result_storage_bytes=32,
                original_api_invoked=1, raw_ticket_capture_only=1, allocation_pin_verified=0, capture_verified=0)
        ticket(0x20, birth)
        proc(1, 1, 0)
        proc(2, 1, 0)
        row('FUNCTIONAL_FACE_DMM_PROC_BIRTH', pid=pid, tid=tid, birth_observation=birth, unit=hex(unit), handle=hex(ap),
            capture_rc=0, software_allocation_token=hex(token), relation='0x4567', generation=ap >> 10,
            owners=1, opens=0, state=1, address=hex(physical), bytes=length, extent_id='0x456',
            diagnostic_only=1, observed_at_original_birth=1, capture_verified=0)
        row('FUNCTIONAL_FACE_DMM_UNIT', pid=pid, unit=hex(unit), handle=hex(cp), live_creator=1, epoch=0x456,
            owner=hex(pid << 32 | 0x46414345), reference=0, logical='0x70000000', registration=0x789,
            host_view='0x7f40000000', bytes=length, mapped_bytes=(length + 4095) // 4096 * 4096)
        row('FUNCTIONAL_FACE_DMM_API40_ORIGIN', pid=pid, tid=tid, unit=hex(unit), rc=0, source_birth=birth,
            frame=hex(s.number(raw, 288, 8)), api=hex(s.number(raw, 296, 8)), caller=hex(callback + 0x440),
            native_metadata_observed=1, original_caller_bound=1, capture_verified=0)
        metadata(1, 0, share - 1)
        command(0x21, share, raw[128:168], raw[168:208])
        metadata(2, 0, share)
        command(0x24, opened, raw[208:248], raw[248:288])
        metadata(2, 1, opened)
        # Real synthetic input -> independent snapshot -> staged mailbox -> CP ->
        # independently opened/read file, not a boolean readback mock.
        original = bytes(((n * 37 + index * 53 + 11) ^ (n >> 7)) & 255 for n in range(length))
        broker.qmp.source = bytearray(original)
        if width == 16:
            original_dump = host.dump
            monkeypatch.setattr(host, 'dump', lambda address, data: ''.join(
                f'{address + n:016x}:' + ''.join(f' 0x{v:02x}' for v in data[n:n + 8]) + '\r\n'
                for n in range(0, len(data), 8)))
        first = broker.sequence + 1
        result, output = exchange(11, raw, native, 1, 47001)
        snapshot_token = result.token
        cp_body = bytearray(length)
        cp_body[:len(output)] = output
        cursor = len(output)
        broker.qmp.source[:] = b'\x9a' * length
        while cursor < length:
            result, output = exchange(64, struct.pack('<2Q2I', snapshot_token, cursor, 47001, 0), native, 1, 47001)
            cp_body[cursor:cursor + len(output)] = output
            cursor += len(output)
        result, output = exchange(65, struct.pack('<2Q', snapshot_token, b.fnv64(bytes(cp_body))), native, 1, 0)
        assert not output and broker.source().active is None and broker.transfer is None
        cp_file = run / f'HOST_TEST-cp-{unit:x}.bin'
        cp_file.write_bytes(bytes(cp_body))
        with cp_file.open('rb') as independent:
            readback = independent.read()
        assert readback == original and len(readback) == length
        owned.append((unit, original, readback))
        transfer(first, 11, raw, readback, snapshot_token, native)
        metadata(2, 1, opened)
        command(0x25, close)
        metadata(2, 0, close)
        command(0x23, freed)
        metadata(1, 0, freed)
        f = dict(pid=pid, tid=tid, unit=hex(unit), allocation_token=hex(token), model_instance=hex(nonce),
                 snapshot_token=hex(snapshot_token), source_fnv=hex(b.fnv64(original)), cp_fnv=hex(b.fnv64(readback)),
                 original_sender_started=0, capture_verified=0)
        cb = dict(callback=hex(callback), context=hex(context), actual_original_callback=1, content_readback_complete=1)
        row('FUNCTIONAL_FACE_SOURCE_CALLBACK_ENTER', **f, **cb)
        row('FUNCTIONAL_FACE_SOURCE_CALLBACK_RETURN', **f, **cb, actual_original_callback_returned=1)
        row('FUNCTIONAL_FACE_SOURCE_SNAPSHOT_RESULT', **f, rc=0, claimed=1, started=1, source_bytes=length,
            cp_written=length, cp_readback=len(readback), original_callback_invoked=1, original_callback_returned=1,
            original_global_writer_exclusion_verified=0, physical_ASIC_verified=0)
        if width == 16:
            monkeypatch.setattr(host, 'dump', original_dump)
    if inband_cancel:
        first = broker.sequence + 1
        result, output = exchange(66, b'', native, 0, 128)
        transfer(first, 66, b'', output, 0, native)
    broker.clear_source('broker_cleanup')
    error, state, _ = broker.core.execute(nonce, b.CANCEL, b'', 128)
    broker.emit('cancel_cleanup', actual_c_result=error, returned_bytes=len(state), returned_sha256=checker.sha(state))
    broker.emit('detach_commit', sequence=broker.sequence, model_work_stopped=True, no_further_ram_after_ack=True)
    broker.emit('mailbox_detached', cleanup_detach=True)
    broker.emit('debugger_disconnected', detached=True)
    cleanup = dict(safe_to_close=True, mailbox_detached=True, debugger_stopped=True,
                   protocol_physmode_restored=True, worker_stopped=True, errors=[])
    broker.emit('cleanup', **cleanup)
    events = [json.loads(line) for line in broker.events.getvalue().splitlines()]
    # PayloadRecords carries the actual producer event IDs emitted above.
    next(factory, None)
    text = '\n'.join(console) + '\n'
    (run / 'console.log').write_text(text)
    counts = {kind: sum(e['kind'] == kind for e in events) for kind in {e['kind'] for e in events}}
    runner = dict(schema='functional-camera-runner-v1', profile=checker.PROFILE, phase='closed', error=None,
        broker_started=True, capture_verified=False, physical_ASIC_compatibility_verified=False,
        original_CP_RAM_verified=False, standalone_host_media_write=False, cleanup=cleanup, owner=owner,
        artifact=dict(library=str(checker.RUNTIME / 'functional-camera-model.so'), abi_header_sha256='e' * 64,
            abi=dict(version=1, entry_points=['fcam_model_create', 'fcam_model_destroy', 'fcam_model_request']),
            library_sha256=build['model_sha256'], build_receipt_sha256=build['model_build_sha256'],
            source_archive_sha256=build['model_source_archive_sha256'], qemu_sha256=checker.QEMU_SHA256),
        console_sha256_at_close=checker.sha(text.encode()), mailbox_evidence=dict(mailbox=mailbox),
        debugger_handoff=dict(qemu_identity=qemu, qemu_pid=178), broker_event_counts=counts,
        model_response_counts_by_opcode={str(op): sum(e['kind'] == 'request' and e['opcode'] == op for e in events)
                                        for op in {e['opcode'] for e in events if e['kind'] == 'request'}})
    declared = checker.source_module(checker.RUNTIME / 'backup_profile.py').functional_camera_profile_fields(checker.PROFILE)
    policy = {key: declared[key] for key in (
        'functional_camera_cp_face_dmm_functional_source_snapshot_policy',
        'functional_camera_cp_face_dmm_functional_source_snapshot_verified',
        'functional_camera_cp_face_dmm_original_global_writer_exclusion_verified')}
    manifest = dict(functional_camera_runtime=runner, evidence_class='HOST_TEST', backup_transport=dict(policy),
                    files={str(checker.RUNTIME / 'functional-camera-abi.h'): 'e' * 64}, **policy)
    (run / 'functional-camera-runner.json').write_text(json.dumps(runner))
    (run / 'runtime-manifest.json').write_text(json.dumps(manifest))
    (run / 'functional-camera-broker-receipts.jsonl').write_text(''.join(json.dumps(e) + '\n' for e in events))
    assert sum(len(content) for _, content, _ in owned) == 514304
    return [run, manifest, checker.parse_console(text.encode()), events, build], owned


@pytest.fixture
def source_run(tmp_path, monkeypatch):
    return source_fixture(tmp_path, monkeypatch)


def inspect(args):
    transport = checker.check_transport(*args)
    return checker.check_face_source(*args[:4], transport), transport


def test_actual_owned_514304_bytes_have_complete_source_stage(source_run):
    args, owned = source_run
    result, transport = inspect(args)
    assert result.get('content_joins_verified') is True, result
    assert len(result['transactions']) == 3 and sum(t['bytes'] for t in result['transactions']) == 514304
    assert result['status'] == 'complete' and result['verified'] is True
    assert result['missing'] == []
    for actual, (unit, original, readback) in zip(result['transactions'], owned):
        assert actual['unit'] == unit and actual['sha256'] == checker.sha(original) == checker.sha(readback)
        assert actual['full_xp_content_verified'] and actual['actual_CP_content_readback_verified']
        assert actual['exact_winning_RAM_row_verified'] and actual['actual_CPU_AS_verified'] and actual['monitor_cpu0_verified']
        assert actual['actual_original_callback_returned'] and actual['paused_window_verified']
        assert actual['copy_window_continuation'] == 'resumed'
    assert all(result[k] is False for k in source_checker.FALSE_CLAIMS)
    assert all(t['frame'] is None and t['provider_kind'] == 'source' for t in transport['transfers'][1:])
    with pytest.raises(ValueError):
        checker.check_frames(args[0], transport)


@pytest.mark.parametrize('container', ['top', 'backup_transport'])
@pytest.mark.parametrize('key', [
    'functional_camera_cp_face_dmm_functional_source_snapshot_policy',
    'functional_camera_cp_face_dmm_functional_source_snapshot_verified',
    'functional_camera_cp_face_dmm_original_global_writer_exclusion_verified'])
def test_source_requires_actual_prefixed_profile_scope(source_run, container, key):
    original, _ = source_run
    for value in (None, 0, True, 'missing', 'unprefixed'):
        args = [original[0], copy.deepcopy(original[1]), original[2], original[3], original[4]]
        target = args[1] if container == 'top' else args[1]['backup_transport']
        if value == 'missing':
            del target[key]
        elif value == 'unprefixed':
            target[key.removeprefix('functional_camera_')] = target.pop(key)
        else:
            target[key] = value
        result, _ = inspect(args)
        assert result['status'] == 'invalid' and not result['verified']
        assert 'profile/scope' in result['missing'][0]['detail']


def test_real_inband_C_cancel_and_separate_source_finalizer(tmp_path, monkeypatch):
    args, _ = source_fixture(tmp_path, monkeypatch, inband_cancel=True)
    result, transport = inspect(args)
    assert result['verified'] is True and transport['opcodes']['66'] == 1
    cancellations = [e for e in args[3] if e['kind'] == 'source_cancel']
    assert [e['reason'] for e in cancellations] == ['actual_c_cancel', 'broker_cleanup']
    assert cancellations[0]['actual_c_result'] == 0 and 'actual_c_result' not in cancellations[1]


@pytest.mark.parametrize('case, error', [
    ('token_retained', 'retains source storage'), ('bytes_retained', 'retains source storage'),
    ('boolean_token', 'integer'), ('not_cleared', 'retains source storage'),
    ('scope_promoted', 'promotes scope'), ('wrong_model', 'mixed model instance'),
    ('wrong_detach_sequence', 'cleanup lifecycle is unsafe'),
    ('fake_actual_C', 'actual in-band C CANCEL'), ('wrong_reason', 'actual in-band C CANCEL'),
    ('host_claims_C', 'disguised as C CANCEL'), ('missing_source_finalizer', 'source finalizer'),
    ('duplicate_source_finalizer', 'source finalizer duplicate'),
    ('missing_actual_C', 'actual cancel/detach'), ('C_error', 'cleanup cancel failed'),
    ('C_zero_ACK', 'cleanup cancel failed'), ('C_boolean_success', 'cleanup cancel failed'),
    ('source_after_C', 'source finalizer not before actual C'),
    ('source_after_detach', 'access after detach'), ('post_detach_result', 'access after detach'),
    ('inflight_source', 'source finalizer duplicate/in-flight'),
    ('unreleased_source', 'retains source storage'),
])
def test_source_cleanup_cannot_substitute_for_actual_C_or_release(source_run, case, error):
    original, _ = source_run
    args = [original[0], copy.deepcopy(original[1]), original[2], copy.deepcopy(original[3]), original[4]]
    events = args[3]
    source = next(e for e in events if e['kind'] == 'source_cancel')
    actual = next(e for e in events if e['kind'] == 'cancel_cleanup')
    if case == 'token_retained':
        source['token'] = 1 << 63 | 1
    elif case == 'bytes_retained':
        source['discarded_bytes'] = 409600
    elif case == 'boolean_token':
        source['token'] = False
    elif case == 'not_cleared':
        source['host_snapshot_cleared'] = False
    elif case == 'scope_promoted':
        source['capture_verified'] = True
    elif case == 'wrong_model':
        source['model_instance'] += 1
    elif case == 'wrong_detach_sequence':
        next(e for e in events if e['kind'] == 'detach_commit')['sequence'] += 1
    elif case == 'fake_actual_C':
        source.update(reason='actual_c_cancel', actual_c_result=0)
    elif case == 'wrong_reason':
        source['reason'] = 'runner_closed'
    elif case == 'host_claims_C':
        source['actual_c_result'] = 0
    elif case == 'missing_source_finalizer':
        events.remove(source)
    elif case == 'duplicate_source_finalizer':
        events.insert(events.index(source), copy.deepcopy(source))
    elif case == 'missing_actual_C':
        events.remove(actual)
    elif case == 'C_error':
        actual['actual_c_result'] = -5
    elif case == 'C_zero_ACK':
        actual.update(returned_bytes=0, returned_sha256=checker.sha(b''))
    elif case == 'C_boolean_success':
        actual['actual_c_result'] = False
    elif case in ('source_after_C', 'source_after_detach'):
        target = actual if case == 'source_after_C' else next(e for e in events if e['kind'] == 'detach_commit')
        events.remove(source)
        events.insert(events.index(target) + 1, source)
    elif case == 'post_detach_result':
        events.insert(events.index(next(e for e in events if e['kind'] == 'detach_commit')) + 1,
                      copy.deepcopy(next(e for e in events if e['kind'] == 'ap_source_result')))
    elif case in ('inflight_source', 'unreleased_source'):
        events.remove(source)
        target = next(e for e in reversed(events) if e['kind'] == ('response' if case == 'inflight_source' else 'request'))
        events.insert(events.index(target), source)
    # Re-seal only the synthetic fixture census, so failures reach the actual
    # cleanup/order guards rather than an unrelated runner-count mismatch.
    for index, event in enumerate(events, 1):
        event.update(event=index, monotonic_ns=index)
    runner = args[1]['functional_camera_runtime']
    runner['broker_event_counts'] = {kind: sum(e['kind'] == kind for e in events) for kind in {e['kind'] for e in events}}
    (args[0] / 'functional-camera-runner.json').write_text(json.dumps(runner))
    with pytest.raises(ValueError, match=error):
        checker.check_transport(*args)


def test_saved_xnod_actual_source_stage_after_transport_fixes():
    run = checker.RUNTIME / 'menu-runs/run-xnodlttg'
    batch = checker.RUNTIME / 'scratch/unified-camera-qfascipj'
    formal = checker.RUNTIME / 'scratch/functional-xnod-acceptance/native-content-check.json'
    if not all(p.is_file() for p in (run / 'runtime-manifest.json', batch / 'ready.json', formal)):
        pytest.skip('private immutable xnod replay is not distributed')
    saved = checker.json_file(formal.parent, formal.name)
    ready = checker.read(batch, 'ready.json')
    assert checker.sha(ready) == saved['evidence']['batch']['ready_sha256'] == (
        'b6b0583c26b5a718474628315146abc7d02bcb920d8fd81ae3fe513ada522ec4')
    raw = {name: checker.read(run, name) for name in ('runtime-manifest.json', 'console.log',
           'functional-camera-broker-receipts.jsonl', 'functional-camera-runner.json')}
    for name, stage in (('runtime-manifest.json', 'manifest_file'), ('console.log', 'console'),
                        ('functional-camera-broker-receipts.jsonl', 'broker_jsonl')):
        assert checker.sha(raw[name]) == saved['evidence'][stage]['sha256']
    events = checker.jsonl(raw['functional-camera-broker-receipts.jsonl'])
    rows = checker.parse_console(raw['console.log'])
    manifest = checker.object_json(raw['runtime-manifest.json'])
    assert [(e['event'], e['kind']) for e in events if e['kind'] in ('source_cancel', 'cancel_cleanup')] == [
        (4268, 'source_cancel'), (4269, 'cancel_cleanup')]
    transfers = [r for r in rows if r['tag'] == 'FUNCTIONAL_CAMERA_TRANSFER']
    assert len(transfers) == 19 and [r['fields']['seq'] for r in transfers[-3:]] == ['17..24', '25..26', '27..28']
    assert sum(int(r['fields']['returned_bytes']) for r in transfers[-3:]) == 514304
    # This is a current-code direct stage replay, not acceptance of the old frozen whole checker.
    transport = checker.check_transport(run, manifest, rows, events, saved['evidence']['batch'])
    assert transport['verified'] is True and transport['background_start']['verified'] is True
    source = checker.check_face_source(run, manifest, rows, events, transport)
    assert source['status'] == 'complete' and source['verified'] is True and not source['missing']
    assert len(source['transactions']) == 3 and sum(tx['bytes'] for tx in source['transactions']) == 514304
    assert all(tx['paused_window_verified'] and tx['full_xp_content_verified'] and
               tx['actual_CP_content_readback_verified'] and tx['actual_original_callback_returned']
               for tx in source['transactions'])
    assert all(source[key] is False for key in source_checker.FALSE_CLAIMS)
    assert saved['evidence']['functional_AP_source_snapshot_consumed']['verified'] is False
    assert all(checker.read(run, name) == data for name, data in raw.items())
    assert saved['verdict'] == 'FAIL' and saved['capture_verified'] is False


def test_16_digit_original_xp_formatter_reconstructs_the_whole_dump(tmp_path, monkeypatch):
    args, _ = source_fixture(tmp_path, monkeypatch, width=16)
    result, _ = inspect(args)
    assert result.get('content_joins_verified') is True and result['verified'] is True, result


def test_existing_paused_window_uses_actual_same_status_id_and_no_stop_or_cont(tmp_path, monkeypatch):
    args, _ = source_fixture(tmp_path, monkeypatch, initially_paused=True)
    result, _ = inspect(args)
    assert result['verified'] is True and result['status'] == 'complete', result
    assert all(tx['copy_window_continuation'] == 'kept_paused' and tx['qmp_last_id'] == tx['qmp_first_id'] + 4
               for tx in result['transactions'])


def fields(args, suffix):
    return next(r['fields'] for r in args[2] if r['tag'] == 'FUNCTIONAL_FACE_SOURCE_' + suffix)


@pytest.mark.parametrize('case', [
    'fake_ack', 'missing_source_payload', 'chunk_locally_rehashed', 'fake_C_core', 'source_actual_C_zero',
    'wrong_kind', 'stale_nonce', 'wrong_source_handle', 'wrong_frame', 'wrong_context', 'missing_native_free',
    'missing_readback', 'wrong_CP_FNV', 'early_callback', 'double_callback', 'metadata_generation',
    'sole_mapping_flags', 'borrowed_old_checksum', 'capture_promoted', 'birth_token_rebuilt',
    'wrong_native_source', 'kernel_status', 'metadata_extent', 'missing_CP_creator', 'missing_callback_return',
    'source_global_writer_promoted', 'wrong_release_whole_digest', 'wrong_source_offset',
    'mtree_tampered_unrehashed', 'mtree_rehashed_split_row', 'mtree_missing', 'mtree_oversized',
    'monitor_wrong_cpu', 'monitor_reply_error',
])
def test_source_semantic_rejections_reach_content_or_transport_failure(source_run, case):
    original, _ = source_run
    args = [original[0], copy.deepcopy(original[1]), copy.deepcopy(original[2]), copy.deepcopy(original[3]), original[4]]
    opened = next(e for e in args[3] if e['kind'] == 'ap_source_result' and e['opcode'] == 11)
    response = next(e for e in args[3] if e['kind'] == 'response' and e['sequence'] == opened['sequence'])
    if case == 'fake_ack':
        opened.update(token=0, total=0, returned_bytes=0)
    elif case == 'missing_source_payload':
        del opened['output_payload']
    elif case == 'chunk_locally_rehashed':
        reference = opened['output_payload']
        path = args[0] / reference['path']
        raw = bytearray(path.read_bytes())
        raw[17] ^= 0x42
        path.write_bytes(raw)
        st = path.stat()
        for e in (opened, response):
            ref = e['output_payload']
            ref.update(bytes=len(raw), sha256=checker.sha(raw), writeback_sha256=checker.sha(raw),
                       fnv1a64=checker.fnv(raw), mtime_ns=st.st_mtime_ns, ctime_ns=st.st_ctime_ns)
            e.update(returned_sha256=checker.sha(raw), returned_fnv1a64=checker.fnv(raw))
        # Every local chunk hash is valid; the retained reconstruction and whole
        # source/release digest still describe the original actual body.
        # Reseal the staged response's local FNV as well. Whole-stream RELEASE
        # must still reject the changed content, despite valid local hashes.
        request = next(e for e in args[3] if e['kind'] == 'request' and e['sequence'] == response['sequence'])
        h = bytearray.fromhex(request['raw_header_hex'])
        struct.pack_into('<I', h, 12, 2)
        struct.pack_into('<Ii', h, 44, len(raw), 0)
        struct.pack_into('<4Q', h, 64, checker.fnv(raw), response['total'], response['offset'], response['token'])
        response['response_header_sha256'] = checker.sha(h)
        assert checker.payload_read(args[0], reference) == raw
    elif case in ('fake_C_core', 'wrong_kind'):
        opened['kind'] = 'core_result' if case == 'fake_C_core' else 'model_frame'
    elif case == 'source_actual_C_zero':
        opened['actual_c_result'] = 0
    elif case == 'stale_nonce':
        opened['model_instance'] += 1
    elif case in ('wrong_source_handle', 'wrong_frame'):
        ref = next(e for e in args[3] if e['kind'] == 'request' and e['opcode'] == 11)['request_payload']
        path = args[0] / ref['path']
        raw = bytearray(path.read_bytes())
        struct.pack_into('<Q' if case == 'wrong_frame' else '<I', raw, 288 if case == 'wrong_frame' else 8, 0x123)
        path.write_bytes(raw)
        st = path.stat()
        request = next(e for e in args[3] if e['kind'] == 'request' and e['opcode'] == 11)
        for event in (request, opened, response):
            event['request_payload'].update(sha256=checker.sha(raw), writeback_sha256=checker.sha(raw),
                fnv1a64=checker.fnv(raw), mtime_ns=st.st_mtime_ns, ctime_ns=st.st_ctime_ns)
        h = bytearray.fromhex(request['raw_header_hex'])
        struct.pack_into('<Q', h, 56, checker.fnv(raw))
        request.update(raw_header_hex=h.hex(), raw_header_sha256=checker.sha(h),
                       request_sha256=checker.sha(raw), request_fnv1a64=checker.fnv(raw))
        response['raw_header_sha256'] = request['raw_header_sha256']
        struct.pack_into('<I', h, 12, 2)
        struct.pack_into('<Ii', h, 44, response['returned_bytes'], 0)
        struct.pack_into('<4Q', h, 64, response['returned_fnv1a64'], response['total'], response['offset'], response['token'])
        response['response_header_sha256'] = checker.sha(h)
        transfer = next(r for r in args[2] if r['tag'] == 'FUNCTIONAL_CAMERA_TRANSFER' and r['fields']['op'] == '11')
        transfer['fields']['request_fnv'] = hex(checker.fnv(raw))
    elif case == 'wrong_context':
        fields(args, 'CALLBACK_ENTER')['context'] = '0x1234'
    elif case == 'missing_native_free':
        args[2] = [r for r in args[2] if not (r['tag'] == 'FUNCTIONAL_FACE_DMM_AP_OBSERVATION' and
            r['fields']['op'] == '0x25' and r['fields']['event'] == '4')]
    elif case == 'missing_readback':
        fields(args, 'SNAPSHOT_RESULT')['cp_readback'] = '0'
    elif case == 'wrong_CP_FNV':
        fields(args, 'SNAPSHOT_RESULT')['cp_fnv'] = '0x123'
    elif case == 'early_callback':
        next(r for r in args[2] if r['tag'] == 'FUNCTIONAL_FACE_SOURCE_CALLBACK_ENTER')['line'] = 1
    elif case == 'double_callback':
        args[2].append(copy.deepcopy(next(r for r in args[2] if r['tag'] == 'FUNCTIONAL_FACE_SOURCE_CALLBACK_ENTER')))
    elif case == 'metadata_generation':
        fields(args, 'CURRENT_METADATA')['generation'] = '3'
    elif case == 'sole_mapping_flags':
        for e in (opened, response):
            e['source_snapshot']['mapping'] = dict(actual_cpu_as_ram_coverage=True,
                one_winning_ram_row_verified=True, canonical_mr_offsets_disjoint=True)
    elif case.startswith('mtree_') or case.startswith('monitor_'):
        for e in (opened, response):
            mapping = e['source_snapshot']['mapping']
            if case == 'mtree_tampered_unrehashed':
                mapping['mtree_raw'] = mapping['mtree_raw'].replace('owned-ram', 'other-ram')
            elif case == 'mtree_rehashed_split_row':
                # Identical owner/name and affine MR offsets still represent two
                # different winning rows. Replay must refuse this exact forgery.
                tree = host.HEAD + host.row(0x400000000, host.SOURCE) + host.row(
                    host.SOURCE, 0x500000000, offset=host.SOURCE - 0x400000000)
                mapping.update(mtree_raw=tree, mtree_sha256=checker.sha(tree.encode()), mtree_bytes=len(tree.encode()))
            elif case == 'mtree_missing':
                mapping.pop('mtree_raw')
            elif case == 'mtree_oversized':
                tree = mapping['mtree_raw'] + '\n' * (256 * 1024)
                mapping.update(mtree_raw=tree, mtree_sha256=checker.sha(tree.encode()), mtree_bytes=len(tree.encode()))
            elif case == 'monitor_wrong_cpu':
                mapping['monitor_cpu'] = 1
            else:
                mapping['monitor_selection_reply'] = 'Invalid CPU index'
    elif case == 'borrowed_old_checksum':
        opened['source_snapshot']['sha256'] = '7' * 64
    elif case == 'capture_promoted':
        fields(args, 'SNAPSHOT_RESULT')['capture_verified'] = '1'
    elif case == 'birth_token_rebuilt':
        next(r['fields'] for r in args[2] if r['tag'] == 'FUNCTIONAL_FACE_DMM_PROC_BIRTH').pop('software_allocation_token')
    elif case in ('wrong_native_source', 'kernel_status'):
        f = next(r['fields'] for r in args[2] if r['tag'] == 'FUNCTIONAL_FACE_DMM_AP_OBSERVATION' and
                 r['fields']['op'] == '0x21' and r['fields']['event'] == '4')
        if case == 'wrong_native_source':
            f['reply_source'] = '0x61003d'
        else:
            raw = bytearray.fromhex(f['reply_raw'])
            struct.pack_into('<h', raw, 2, -7)
            f['reply_raw'] = raw.hex()
    elif case == 'metadata_extent':
        fields(args, 'CURRENT_METADATA')['extent_id'] = '0x999'
    elif case == 'missing_CP_creator':
        args[2] = [r for r in args[2] if r['tag'] != 'FUNCTIONAL_FACE_DMM_UNIT']
    elif case == 'missing_callback_return':
        args[2] = [r for r in args[2] if r['tag'] != 'FUNCTIONAL_FACE_SOURCE_CALLBACK_RETURN']
    elif case == 'source_global_writer_promoted':
        opened['source_snapshot']['native_global_writer_exclusion_verified'] = True
    elif case == 'wrong_release_whole_digest':
        released = next(e for e in args[3] if e['kind'] == 'ap_source_result' and e['opcode'] == 65)
        released['result_transfer']['sha256'] = '2' * 64
    elif case == 'wrong_source_offset':
        chunk = next(e for e in args[3] if e['kind'] == 'ap_source_result' and e['opcode'] == 64)
        chunk['offset'] += 1
    try:
        result, _ = inspect(args)
    except (ValueError, FileNotFoundError):
        return  # A transport-boundary rejection precedes the independent stage.
    assert result.get('content_joins_verified') is not True, (case, result)
    assert result['verified'] is False and result['missing']
    assert any('OP11 source_snapshot' not in m['detail'] for m in result['missing']), (case, result)


@pytest.mark.parametrize('case', [
    'missing_window', 'wrong_header', 'wrong_payload', 'wrong_observed_header', 'wrong_observed_payload',
    'wrong_nonce', 'wrong_sequence', 'wrong_origin', 'untyped_running', 'missing_stop_reply', 'still_running',
    'stop_id_replayed', 'paused_id_reordered', 'wrong_cpu_command', 'missing_xp', 'command_id_replayed',
    'hidden_cont_gap', 'early_resume', 'explicit_cont_inside', 'wrong_xp_hash', 'untyped_reply_bytes',
    'wrong_reply_type', 'mode_not_restored', 'window_not_closed', 'fake_resume_reply', 'fake_resume_status',
    'resume_status_id_replayed', 'suppressed_without_end_status', 'fake_kept_paused', 'boolean_qmp_id',
    'mtree_self_rehashed_against_actual_reply',
])
def test_paused_window_semantic_rejections(source_run, case):
    original, _ = source_run
    args = [original[0], copy.deepcopy(original[1]), copy.deepcopy(original[2]), copy.deepcopy(original[3]), original[4]]
    opened = next(e for e in args[3] if e['kind'] == 'ap_source_result' and e['opcode'] == 11)
    response = next(e for e in args[3] if e['kind'] == 'response' and e['sequence'] == opened['sequence'])
    for event in (opened, response):
        snapshot = event['source_snapshot']
        if case == 'missing_window':
            del snapshot['paused_window']
            continue
        w = snapshot['paused_window']
        if case in ('wrong_header', 'wrong_payload', 'wrong_observed_header', 'wrong_observed_payload'):
            key = {'wrong_header': 'request_header_sha256', 'wrong_payload': 'request_payload_sha256',
                   'wrong_observed_header': 'observed_header_sha256', 'wrong_observed_payload': 'observed_payload_sha256'}[case]
            w[key] = '1' * 64
        elif case == 'wrong_nonce':
            w['model_instance'] += 1
        elif case == 'wrong_sequence':
            w['sequence'] += 1
        elif case == 'wrong_origin':
            w['origin']['source'] += 1
        elif case == 'untyped_running':
            w['prior_status']['running'] = 1
        elif case == 'missing_stop_reply':
            w['stop_reply'] = None
        elif case == 'still_running':
            w['paused_status'] = dict(running=True, status='running')
        elif case == 'stop_id_replayed':
            w['stop_qmp_id'] = w['prior_status_qmp_id']
        elif case == 'paused_id_reordered':
            w['paused_status_qmp_id'] = w['stop_qmp_id']
        elif case == 'wrong_cpu_command':
            w['commands'][0]['arguments']['command-line'] = 'cpu 1'
        elif case == 'missing_xp':
            w['commands'].pop()
        elif case == 'command_id_replayed':
            w['commands'][2]['qmp_id'] = w['commands'][1]['qmp_id']
        elif case == 'hidden_cont_gap':
            w['commands'][2]['qmp_id'] += 1
        elif case == 'early_resume':
            w['resume_qmp_id'] = w['commands'][1]['qmp_id']
        elif case == 'explicit_cont_inside':
            w['commands'][2].update(command='cont', arguments={})
        elif case == 'wrong_xp_hash':
            w['commands'][2]['reply_sha256'] = '0' * 64
        elif case == 'untyped_reply_bytes':
            w['commands'][0]['reply_bytes'] = False
        elif case == 'wrong_reply_type':
            w['commands'][0]['reply_type'] = 'bytes'
        elif case == 'mode_not_restored':
            w['physical_mode_restored_before_exit'] = False
        elif case == 'window_not_closed':
            w['window_closed'] = False
        elif case == 'fake_resume_reply':
            w['resume_reply'] = None
        elif case == 'fake_resume_status':
            w['resumed_status'] = dict(running=False, status='paused')
        elif case == 'resume_status_id_replayed':
            w['resumed_status_qmp_id'] = w['resume_qmp_id']
        elif case == 'suppressed_without_end_status':
            w['continuation'] = 'suppressed'
            for key in ('resume_reply', 'resume_qmp_id', 'resumed_status', 'resumed_status_qmp_id'):
                w.pop(key)
        elif case == 'fake_kept_paused':
            w['prior_status'] = dict(running=False, status='paused')
            w['continuation'] = 'kept_paused'
        elif case == 'boolean_qmp_id':
            w['prior_status_qmp_id'] = True
        elif case == 'mtree_self_rehashed_against_actual_reply':
            mapping = snapshot['mapping']
            tree = mapping['mtree_raw'].replace('owned-ram', 'changed-ram')
            request = next(e for e in args[3] if e['kind'] == 'request' and e['sequence'] == opened['sequence'])
            mailbox = args[3][0]['mailbox']
            packet = s.packet(checker.payload_read(args[0], request['request_payload']),
                              bytes.fromhex(request['raw_header_hex']), mailbox)
            mapping.update(s.disjoint(tree, packet, mailbox), mtree_raw=tree,
                           mtree_sha256=checker.sha(tree.encode()), mtree_bytes=len(tree.encode()))
    transport = checker.check_transport(*args)
    assert transport['verified'] is True  # Reach the window validator, not a mismatched response shortcut.
    result = checker.check_face_source(*args[:4], transport)
    assert result['verified'] is False and result.get('content_joins_verified') is not True, (case, result)
    assert any('paused_window' in m['detail'] for m in result['missing']), (case, result)
    if case in ('missing_window', 'missing_xp', 'suppressed_without_end_status'):
        assert result['status'] == 'incomplete' and result['missing'][-1]['code'] == 'TRACE_MISSING'
    else:
        assert result['status'] == 'invalid' and result['missing'][-1]['code'] == 'EVIDENCE_INVALID'
    assert all(result[k] is False for k in source_checker.FALSE_CLAIMS)


def test_source_is_integrated_into_evaluate_with_frozen_dependencies(source_run):
    args, _ = source_run
    paths = [HERE / 'check_face_source.py', checker.RUNTIME / 'functional_face_source_snapshot.py',
             checker.RUNTIME / 'functional-face-source-snapshot-abi.h']
    sources = {str(p): checker.sha(p.read_bytes()) for p in paths}
    with mock.patch.object(checker, 'check_profile', return_value={'verified': True}), mock.patch.object(
            checker, 'check_batch', return_value=(dict(args[4], batch=str(args[0])), sources)):
        result = checker.evaluate(args[0], args[0])
    source = result['evidence'][source_checker.STAGE]
    assert source.get('content_joins_verified') is True, result
    assert source['verified'] is True and source['status'] == 'complete' and source['missing'] == []
    assert result['capture_verified'] is False and result['verdict'] == 'FAIL'
    assert all(p['capture_verified'] is False for p in result['products'].values())
    transport = checker.check_transport(*args)
    with pytest.raises(checker.MissingEvidence, match='freeze source snapshot dependency'):
        checker.check_face_source(*args[:4], transport, {})


def test_new_checker_uses_existing_payload_reader_trust_boundaries(source_run, tmp_path):
    args, _ = source_run
    transport = checker.check_transport(*args)
    reference = transport['transfers'][1]['output_payloads'][0]
    path = args[0] / reference['path']
    original = path.read_bytes()
    foreign = tmp_path / 'foreign'
    foreign.write_bytes(original)
    path.unlink()
    path.symlink_to(foreign)
    result = checker.check_face_source(*args[:4], transport)
    assert result['verified'] is False and result.get('content_joins_verified') is not True
    assert result['missing']
