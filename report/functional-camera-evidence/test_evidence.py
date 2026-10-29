"""HOST_TEST replays; no fixture is a camera capture or acceptance run.

unittest + stdlib; media fixtures use the already-required independent
ffmpeg/Pillow toolchain. Background tests compile the existing HOST_TEST C owner
and real Core/optics dependencies into a temporary executable, preserving its
actual stdout. No main model build, network, device or VM is started here.
"""
import copy
import importlib.util
import io
import json
import os
from pathlib import Path
import re
import shlex
import struct
import subprocess
import tarfile
import tempfile
import unittest
from unittest import mock

_spec = importlib.util.spec_from_file_location('functional_capture_evidence_host_test',
                                               Path(__file__).with_name('check_evidence.py'))
checker = importlib.util.module_from_spec(_spec)
exec(compile(_spec.loader.get_source(_spec.name), _spec.origin, 'exec'), checker.__dict__)


# Complete public OBS text only, copied from run-jfz16a4v; never native acceptance.
JFZ_VDF_RESOURCE_OBS = '''OBS FUNCTIONAL_VDF_PATH_RESOURCE_DEPENDENCIES pid=258 tid=381 accepted=1 proc_ap_consumed=1 input_ap_consumed=1 output_ap_consumed=1 output_faults=0 current_request_retained_expected=1 capture_verified=0
OBS FUNCTIONAL_VDF_PATH_RESOURCES_TTS_TABLE pid=258 tid=381 appfw_base=0x7f25c3f000 table_va=0x5f66b08 address=0x7f2bba5b08 bytes=144 reads=144/144 unchanged=1 atomic_snapshot=0 raw_before=1a00000005040000000008000000000000802afe0400000000840000000008000000001e000000000060280b7e000000000008001d0000000060280b7e00000000000800000000001b000000060400000000080000000000008032fe0400000001840000000008000000081e000000000060200b7e000000000008001e0000000060200b7e0000000000080000000000 raw_after=1a00000005040000000008000000000000802afe0400000000840000000008000000001e000000000060280b7e000000000008001d0000000060280b7e00000000000800000000001b000000060400000000080000000000008032fe0400000001840000000008000000081e000000000060200b7e000000000008001e0000000060200b7e0000000000080000000000 ownership_verified=0
OBS FUNCTIONAL_VDF_PATH_RESOURCES_RESERVED tid=381 accepted=1 dmm_enabled=1 dmm_bound=1 dmm_slots=1/1 dmm_opens=1/1 dmm_handles=0x8400/0x8401 dmm_generations=1/1 dmm_epochs=1/2 dmm_creators=1/1 dmm_allocation_count=2 dmm_lifecycle_changed=0 dmm_domain=2 foreign_speech_kept=1 data_frozen=0 control_bound=1 control_live=0 control_faults=0 allocations=4 releases=4 connection_started=1 connections=1 format_pending=0 blocked=0 format_consumed=1 buffer_released=1 connection_reply_frees=1 connection_faults=0 vef_init=1 vef_owner=0x905a0048 vef_objects=16 vef_pending=0 vef_live=0 vef_retained=0 vef_faults=0 pinmem_init=1 pinmem_owner=0x90590818 pinmem_objects=13 pinmem_pending=0 pinmem_live=0 pinmem_retained=0 pinmem_faults=0 global_dmm_idle_verified=0 original_cp_executed=0 capture_verified=0
'''
LAYOUT_BODY32 = bytes.fromhex('07010100000000008002e0010000000000000000000000000300000000000000')
PEAKING_BODY8 = bytes.fromhex('0300010000eb8080')
DISPLAY_PATHS = (True, bytes.fromhex('0300204b41000000'), LAYOUT_BODY32,
                 ('display', 0x152, PEAKING_BODY8), ('display', 0x162))
REFRESH_PATHS = DISPLAY_PATHS + (('display', 0x141),)


BB_PATHS = (('bb', 0x111, bytes.fromhex('00000f02') + bytes(24)),
            ('bb', 0x166, b'\x00\x01' + bytes(26)), ('bb', 0x167, bytes(2)),
            ('bb', 0x15f, bytes(4)), ('bb', 0x128, b'\x00\x01\x00\x00' + struct.pack('<I', 60) + bytes(4)))


def histogram_observations(output, inline=False, source=0x80946180):
    """Exact public C logger snapshots, with separate future and notification threads."""
    records = []
    wire = bytes.fromhex('0d2048010c00018001010000')
    ack = bytes.fromhex('0d2048110c00018000005900')
    bins = output[168:]
    notification = bytes.fromhex('0d200c210a0401800100') + bins
    names = [('REQUEST_FREE', 1), ('RECEIVE', 2), ('AP_FREE', 2), ('SEND', 2),
             ('RECEIVE', 3), ('AP_FREE', 3), ('SEND', 3), ('COMPLETE', 0)] if inline else [
             ('REQUEST_FREE', 1), ('SEND', 2), ('SEND', 3), ('COMPLETE', 0),
             ('RECEIVE', 2), ('RECEIVE', 3), ('AP_FREE', 3), ('AP_FREE', 2)]
    def at(event, role):
        return names.index((event, role))
    def row(tag, fields):
        records.append(tag + ' ' + ' '.join(f'{key}={value}' for key, value in fields.items()))
    for index, (name, changed_role) in enumerate(names):
        leases = []
        for role in (1, 2, 3):
            queued = int(role != 1 and index >= at('SEND', role))
            received = int(role != 1 and index >= at('RECEIVE', role))
            freed = int(role == 1 or index >= at('AP_FREE', role))
            inflight = int(role != 1 and at('RECEIVE', role) <= index < at('SEND', role))
            pointer = {2: '0x500000', 3: '0x600000'}.get(role, '(nil)')
            leases.append(dict(pid=77, cycle=1, snapshot_id=index + 1, role=role,
                destination=hex(0x92840747 if role == 1 else source),
                source=hex(source if role == 1 else 0x92840747), bytes=1034 if role == 3 else 12,
                pointer='(nil)' if freed or index == 0 else pointer, retained=int(not freed and index != 0),
                allocate_attempted=int(role != 1 and index != 0),
                allocation_returned='(nil)' if index == 0 else pointer, allocation_alias=0, allocate_rc=0,
                send_started=int(queued or inflight), send_inflight=inflight, queued=queued, send_rc=0, received=received,
                sender_tid=90, receiver_tid=90 + role if received else 0,
                free_tid=(93 if role == 3 else 90) if freed else 0, free_attempted=freed, free_rc=0,
                freed=freed, consumed=int(role != 1 and queued and received and freed), releasing=0, faults=0,
                wire_fnv1a64=f'{checker.fnv(wire if role == 1 else ack if role == 2 else notification):016x}'))
        busy = int(index < names.index(('COMPLETE', 0)))
        fields = dict(pid=77, tid=(90 + changed_role if name == 'RECEIVE' or name == 'AP_FREE' and changed_role == 3 else 90),
            cycle=1, snapshot_id=index + 1, event_role=changed_role,
            source=hex(source), destination='0x92840747', command='0x148', bytes=12,
            original_request='0x400000', raw=wire.hex(),
            original_fnv1a64=f'{checker.fnv(wire):016x}', canonical8=checker.HIST_CANONICAL.hex(),
            queue_bound=1, queue_source=hex(source), bridge_rc=0, validation_rc=0, used=1192, required=1192,
            model_result_bytes=1192, model_result_fnv1a64=f'{checker.fnv(output):016x}', model_instance=99,
            config_generation=struct.unpack_from('<Q', output, 16)[0],
            before_config_generation=struct.unpack_from('<Q', output, 152)[0],
            frame_generation=struct.unpack_from('<Q', output, 24)[0],
            before_frame_generation=struct.unpack_from('<Q', output, 144)[0],
            lease_generation=struct.unpack_from('<Q', output, 32)[0],
            notification_bytes=1034, notification_fnv1a64=f'{checker.fnv(notification):016x}', selector=1,
            **{channel + '_fnv1a64': f'{checker.fnv(bins[c * 256:(c + 1) * 256]):016x}' for c, channel in enumerate('YRGB')},
            request_owned=1, model_complete=1, ACK_AP_consumed=leases[1]['consumed'],
            notification_AP_consumed=leases[2]['consumed'],
            AP_consumed=int(leases[1]['consumed'] and leases[2]['consumed'] and not busy),
            busy=busy, guard=busy, faults=0, functional_model=1, physical_ASIC_verified=0,
            original_CP_FIFO_verified=0, physical_CP_RTOS_verified=0, UI_applied=0, continuous_histogram=0, capture_verified=0)
        row('FUNCTIONAL_HISTOGRAM_' + name, fields)
        for lease in leases:
            row('FUNCTIONAL_HISTOGRAM_LEASE', lease)
    return '\n'.join(records) + '\n'


def layout_stage_observations(count=3, inline=False):
    """Exact guest-local producer schema; no broker/model/frame operation is invented."""
    records = []
    original, ack = bytes.fromhex('0d204c0128000180') + LAYOUT_BODY32, bytes.fromhex('0d204c110c00018000005900')
    for cycle in range(1, count + 1):
        names = ('READBACK', 'REQUEST_FREE', 'RECEIVE', 'AP_FREE', 'SEND', 'COMPLETE') if inline else (
                 'READBACK', 'REQUEST_FREE', 'SEND', 'COMPLETE', 'RECEIVE', 'AP_FREE')
        for index, name in enumerate(names):
            queued, received, freed = (int(index >= names.index(key)) for key in ('SEND', 'RECEIVE', 'AP_FREE'))
            busy = int(index < names.index('COMPLETE'))
            consumed = int(queued and received and freed and not busy)
            fields = dict(pid=77, tid=88, cycle=cycle, stage_generation=cycle, requests=cycle,
                completed_cycles=cycle - 1 + consumed, busy=busy, faults=0, source='0x81cf61c5',
                destination='0x92840747', command='0x14c', bytes=40, original_fnv1a64=f'{checker.fnv(original):016x}',
                bank_written=1, readback_verified=1, bank_fnv1a64=f'{checker.fnv(LAYOUT_BODY32):016x}',
                readback_fnv1a64=f'{checker.fnv(LAYOUT_BODY32):016x}', request_owned=1,
                request_retained='0x400000' if name == 'READBACK' else '(nil)', request_freed=int(name != 'READBACK'),
                request_free_rc=0, ack_retained='(nil)' if freed or name == 'READBACK' else '0x500000',
                queued=queued, received=received, AP_consumed=consumed, sender_tid=88,
                receiver_tid=88 if received else 0, free_tid=88 if freed else 0,
                send_inflight=int(name in ('RECEIVE', 'AP_FREE') and not queued), releasing=0,
                allocate_rc=0, send_rc=0, free_rc=0, validation_rc=0,
                allocation_returned='(nil)' if name == 'READBACK' else '0x500000', allocation_alias=0,
                stage_only=1, semantic_applied=0, frame_consumed=0, hardware_ready=0, capture_verified=0,
                physical_ASIC_verified=0, original_CP_FIFO_verified=0, physical_CP_RTOS_verified=0,
                applied_receipt_verified=0, applied_stage_generation=0, applied_model_instance=0,
                applied_config_generation=0, applied_frame_generation=0, applied_result_fnv1a64='0000000000000000',
                raw=original.hex(), bank32=LAYOUT_BODY32.hex(), copied_readback32=LAYOUT_BODY32.hex(), ack_wire=ack.hex())
            records.append('FUNCTIONAL_LAYOUT_STAGE_' + name + ' ' + ' '.join(f'{k}={v}' for k, v in fields.items()))
    return '\n'.join(records) + '\n'


def host_test_transport(root, operations=None, console_prefix='', guest_pid=77, model_instance=99, model_owner_pid=177,
                        evidence_class='HOST_TEST'):
    """Bounded HOST_TEST bytes with the exact actual broker payload/proof schema."""
    run = root / 'HOST_TEST'
    run.mkdir()
    nonce, pid = model_instance, guest_pid
    mailbox = dict(pid=pid, nonce=nonce, pages=[0x400000000 + i * 4096 for i in range(16)], phys0=0x400000000)
    origin = dict(producer_tid=81, source=0x802a0116, destination=0x82830752,
                  command=0x30304, bytes=104, fnv1a64=checker.fnv(b'HOST_TEST original packet'))
    owner = dict(pid=model_owner_pid, starttime=100, ppid=1, exe='/HOST_TEST/python')
    qemu = dict(pid=178, starttime=101, ppid=177, exe='/HOST_TEST/qemu-system-aarch64')
    config = dict(run=str(run), run_identity=[run.stat().st_dev, run.stat().st_ino],
                  qemu_sha256=checker.QEMU_SHA256, owner=owner, qemu=qemu)
    build = dict(model_sha256='a' * 64, model_build_sha256='b' * 64,
                 model_source_archive_sha256='c' * 64)
    events = []
    def emit(kind, **fields):
        row = dict(event=len(events) + 1, monotonic_ns=len(events) + 1,
                   model_instance=nonce, kind=kind, **fields)
        events.append(row)
        return row
    emit('binding', mailbox=mailbox, actual_core_sha256=build['model_sha256'], config=config,
         payload_policy=dict(directory='functional-camera-data', per_file_bytes=64 * 1024**2,
                             total_bytes=512 * 1024**2, max_files=65536, source_kind='actual_hardware_transfer'),
         native_acceptance=False)
    emit('attached', connected=True, model_created=False, protocol_physmode_restored=True)
    (run / 'functional-camera-data').mkdir(mode=0o700)
    def retain(seq, op, direction, data, native, token=0, total=0, offset=0):
        path = f'functional-camera-data/{seq:020d}-{direction}.bin'
        fd = os.open(run / path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, 'wb') as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        st = (run / path).stat()
        return dict(path=path, source_kind='actual_hardware_transfer', producer_event=len(events) + 1,
                    sequence=seq, opcode=op, model_instance=nonce, origin=native.copy(), direction=direction,
                    token=token, total=total, offset=offset, bytes=len(data), sha256=checker.sha(data),
                    fnv1a64=checker.fnv(data), writeback_sha256=checker.sha(data), writeback_verified=True,
                    device=st.st_dev, inode=st.st_ino, mtime_ns=st.st_mtime_ns, ctime_ns=st.st_ctime_ns)
    active = None
    def exchange(seq, op, data, output, token=0, total=0, offset=0, native=None, proof=None):
        nonlocal active
        native = native or origin
        raw = bytearray(512)
        struct.pack_into('<4I', raw, 0, 0x314d4346, 1, pid, 1)
        struct.pack_into('<2Q', raw, 16, nonce, seq)
        struct.pack_into('<3I', raw, 32, op, len(data), checker.DATA_BYTES)
        struct.pack_into('<Q', raw, 56, checker.fnv(data))
        struct.pack_into('<5I', raw, 96, *(native[k] for k in
                         ('producer_tid', 'source', 'destination', 'command', 'bytes')))
        struct.pack_into('<Q', raw, 120, native['fnv1a64'])
        struct.pack_into('<16Q', raw, 128, *mailbox['pages'])
        incoming = retain(seq, op, 'in', data, native, token=active['token'] if active and op in (64, 65) else 0,
                          total=active['total'] if active and op in (64, 65) else 0,
                          offset=active['cursor'] if active and op in (64, 65) else 0)
        request = emit('request', sequence=seq, opcode=op, origin=native.copy(), raw_header_hex=raw.hex(),
                       raw_header_sha256=checker.sha(raw), request_bytes=len(data), request_payload=incoming,
                       request_sha256=checker.sha(data), request_fnv1a64=checker.fnv(data))
        outgoing = retain(seq, op, 'out', output, native, token=token, total=total, offset=offset)
        fields = dict(sequence=seq, opcode=op, actual_c_result=0, returned_bytes=len(output),
                      returned_sha256=checker.sha(output), returned_fnv1a64=checker.fnv(output),
                      token=token, total=total, offset=offset, request_payload=incoming, output_payload=outgoing,
                      result_transfer=None)
        emit('core_result', **fields, origin=native.copy())
        if proof is not None:
            emit('model_frame', sequence=seq, opcode=op, origin=native.copy(), actual_c_result=0,
                 actual_core_sha256=build['model_sha256'], request_payload=incoming, output_payload=outgoing,
                 proof=proof, native_acceptance=False)
        if token:
            if op != 64:
                active = dict(token=token, total=total, cursor=0)
            active['cursor'] += len(output)
        elif op in (65, 66):
            active = None
        struct.pack_into('<I', raw, 12, 2)
        struct.pack_into('<Ii', raw, 44, len(output), 0)
        struct.pack_into('<4Q', raw, 64, checker.fnv(output), total, offset, token)
        emit('response', **fields, raw_header_sha256=request['raw_header_sha256'],
             response_header_sha256=checker.sha(raw), origin=native.copy(), data_readback=True, native_acceptance=False)
    state = bytearray(128)
    struct.pack_into('<2I', state, 0, 1, 15)
    struct.pack_into('<Q', state, 48, nonce)
    if operations is None:
        output = b'HOST_TEST result bytes, not a JPEG'
        operations = [dict(op=1, data=b'', output=bytes(state)),
                      dict(op=16, data=struct.pack('<4I', 1, 24, 16, 90), output=output)]
    intervals = []
    for operation in operations:
        op, data, payload = operation['op'], operation['data'], operation['output']
        native = operation.get('origin', origin)
        first = sum(event['kind'] == 'request' for event in events) + 1
        token = operation.get('token', len(intervals) + 1) if op in (16, 33, 34) and payload else 0
        chunk_size = operation.get('chunk_size', checker.DATA_BYTES)
        chunks = [payload[i:i + chunk_size] for i in range(0, len(payload), chunk_size)] or [b'']
        seq, offset = first, 0
        exchange(seq, op, data, chunks[0], token=token, total=len(payload) if token else 0,
                 native=native, proof=operation.get('proof'))
        offset += len(chunks[0])
        for chunk in chunks[1:]:
            seq += 1
            exchange(seq, 64, struct.pack('<2Q2I', token, offset, chunk_size, 0), chunk,
                     token=token, total=len(payload), offset=offset, native=native)
            offset += len(chunk)
        if token:
            seq += 1
            exchange(seq, 65, struct.pack('<2Q', token, checker.fnv(payload)), b'', native=native)
        intervals.append((first, seq, op, data, payload, token, native))
    emit('cancel_cleanup', actual_c_result=0, returned_bytes=128, returned_sha256=checker.sha(state))
    emit('detach_commit', sequence=sum(row['kind'] == 'request' for row in events), previous_status=2, model_work_stopped=True,
         no_further_ram_after_ack=True, raw_header_sha256='d' * 64)
    emit('physical_mode_restored', protocol_physmode_restored=True)
    emit('mailbox_detached', cleanup_detach=True, protocol_physmode_restored=True)
    emit('debugger_disconnected', prior_status='paused', final_status='paused', detached=True,
         protocol_physmode_restored=True)
    cleanup = dict(safe_to_close=True, mailbox_detached=True, debugger_stopped=True,
                   protocol_physmode_restored=True, worker_stopped=True, detached=True, errors=[])
    emit('cleanup', **cleanup)
    def transfer(first, last, op, data, payload, token, origin):
        return ('OBS FUNCTIONAL_CAMERA_TRANSFER '
                f'seq={first}..{last} op={op} source={origin["source"]:#x} '
                f'destination={origin["destination"]:#x} command={origin["command"]:#x} '
                f'bytes={origin["bytes"]} native_fnv={origin["fnv1a64"]:#x} request_bytes={len(data)} '
                f'request_fnv={checker.fnv(data):#x} returned_bytes={len(payload)} '
                f'returned_fnv={checker.fnv(payload):#x} required={len(payload)} '
                f'destination_written_bytes={len(payload)} destination_fnv={checker.fnv(payload):#x} '
                f'model_instance={nonce:#x} token={hex(token) if token else "0"} readback_closed=1 error=0\n')
    transfer_lines = [transfer(*interval) for interval in intervals]
    if 'HOST_TEST_TRANSFER_' in console_prefix:
        console = console_prefix
        for index, line in enumerate(transfer_lines):
            marker = f'HOST_TEST_TRANSFER_{index}\n'
            assert console.count(marker) == 1
            console = console.replace(marker, line)
        assert 'HOST_TEST_TRANSFER_' not in console
    else:
        console = console_prefix + ''.join(transfer_lines)
    (run / 'console.log').write_text(console)
    counts = {}
    for event in events:
        counts[event['kind']] = counts.get(event['kind'], 0) + 1
    runner = dict(schema='functional-camera-runner-v1', profile=checker.PROFILE, phase='closed',
                  error=None, broker_started=True, capture_verified=False,
                  physical_ASIC_compatibility_verified=False, original_CP_RAM_verified=False,
                  standalone_host_media_write=False, cleanup=cleanup, owner=owner,
                  artifact=dict(library=str(checker.RUNTIME / 'functional-camera-model.so'),
                                abi_header_sha256='e' * 64,
                                abi=dict(version=1, entry_points=['fcam_model_create', 'fcam_model_destroy', 'fcam_model_request']),
                                library_sha256=build['model_sha256'], build_receipt_sha256=build['model_build_sha256'],
                                source_archive_sha256=build['model_source_archive_sha256'], qemu_sha256=checker.QEMU_SHA256),
                  console_sha256_at_close=checker.sha(console.encode()),
                  mailbox_evidence=dict(mailbox=mailbox), debugger_handoff=dict(qemu_identity=qemu, qemu_pid=178),
                  broker_event_counts=counts, model_response_counts_by_opcode={str(op): sum(
                      event['kind'] == 'request' and event['opcode'] == op for event in events)
                      for op in sorted({event['opcode'] for event in events if event['kind'] == 'request'})})
    (run / 'functional-camera-runner.json').write_text(json.dumps(runner))
    (run / 'functional-camera-broker-receipts.jsonl').write_text(''.join(json.dumps(row) + '\n' for row in events))
    manifest = dict(functional_camera_runtime=runner, evidence_class=evidence_class,
                    files={str(checker.RUNTIME / 'functional-camera-abi.h'): 'e' * 64})
    if any(event['kind'] == 'request' and event['opcode'] in checker.VDF_OPERATIONS for event in events):
        policies = dict(checker.VDF_POLICY)
        if any(event['kind'] == 'request' and event['opcode'] == 6 for event in events):
            policies.update(checker.ZEBRA_POLICY)
        if any(event['kind'] == 'request' and event['opcode'] == 7 for event in events):
            policies.update(checker.LAYOUT_POLICY)
        if any(event['kind'] == 'request' and event['opcode'] == 8 for event in events):
            policies.update(checker.DISPLAY_POLICY)
        if any(event['kind'] == 'request' and event['opcode'] == 9 for event in events):
            policies.update(checker.BB_POLICY)
        policy = {'functional_camera_' + key: value for key, value in policies.items()}
        manifest.update(policy)
        manifest['backup_transport'] = dict(policy)
    if any(event['kind'] == 'request' and event['opcode'] == 10 for event in events):
        policy = {'functional_camera_' + key: value for key, value in checker.HIST_POLICY.items()}
        manifest.update(policy)
        manifest.setdefault('backup_transport', {}).update(policy)
    if 'FUNCTIONAL_LAYOUT_STAGE_' in console:
        policy = {'functional_camera_' + key: value for key, value in checker.STARTUP_LAYOUT_POLICY.items()}
        manifest.update(policy)
        manifest.setdefault('backup_transport', {}).update(policy)
    if 'FUNCTIONAL_CAMERA_CONTROL_' in console:
        policy = {'functional_camera_' + key: value for key, value in checker.XSYNC_POLICY.items()}
        manifest.update(policy)
        manifest.setdefault('backup_transport', {}).update(policy)
    if 'FUNCTIONAL_BACKGROUND_START_' in console:
        policy = {'functional_camera_' + key: value for key, value in checker.BACKGROUND_POLICY.items()}
        manifest.update(policy)
        manifest.setdefault('backup_transport', {}).update(policy)
    (run / 'runtime-manifest.json').write_text(json.dumps(manifest))
    return run, manifest, checker.parse_console(console.encode()), events, build


def independent_media(kind):
    """Real decode fixtures generated only during focused host tests."""
    common = ['ffmpeg', '-nostdin', '-v', 'error', '-f', 'lavfi', '-i',
              'color=c=blue:size=24x16:rate=30', '-threads', '1']
    if kind == 'JPEG':
        tail = ['-frames:v', '1', '-c:v', 'mjpeg', '-pix_fmt', 'yuvj422p', '-f', 'image2pipe', 'pipe:1']
        return subprocess.run(common + tail, check=True, stdout=subprocess.PIPE,
                              stderr=subprocess.PIPE, timeout=15).stdout
    with tempfile.TemporaryDirectory(prefix='HOST_TEST_decoder_') as directory:
        target = Path(directory) / 'HOST_TEST.MP4'
        subprocess.run(common + ['-frames:v', '4', '-c:v', 'libx264', '-profile:v', 'baseline', '-bf', '0',
                       '-tune', 'zerolatency', '-pix_fmt', 'yuv420p', '-movflags', '+faststart', str(target)],
                       check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=15)
        return target.read_bytes()


def host_test_exif(primary, thumb, endian='II'):
    """HOST_TEST TIFF with actual independently decodable embedded JPEG bytes."""
    order = '<' if endian == 'II' else '>'
    tiff = bytearray(endian.encode() + struct.pack(order + 'HI', 42, 8))
    tiff += struct.pack(order + 'HI', 0, 14)
    tiff += struct.pack(order + 'H', 2)
    tiff += struct.pack(order + 'HHII', 0x201, 4, 1, 44)
    tiff += struct.pack(order + 'HHII', 0x202, 4, 1, len(thumb))
    tiff += struct.pack(order + 'I', 0) + thumb
    app = b'Exif\0\0' + tiff
    return primary[:2] + b'\xff\xe1' + struct.pack('>H', len(app) + 2) + app + primary[2:]


def host_test_storage(root, jpeg_payload=None):
    run = root / 'HOST_TEST_storage'
    (run / 'SD').mkdir(parents=True)
    card = run / 'host-sd'
    records, paths = [], []
    for token, (kind, path) in enumerate((('JPEG', 'DCIM/HOST_TEST.JPG'),
                                        ('MP4', 'PRIVATE/M4ROOT/CLIP/HOST_TEST.MP4')), 1):
        payload = jpeg_payload if kind == 'JPEG' and jpeg_payload is not None else independent_media(kind)
        target = card / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(payload)
        paths.append(target)
        digest = f'{checker.fnv(payload):016x}'
        submitted = (len(payload) + 4095) // 4096 * 4096
        common = f'pid=77 token={token}'
        records += [f'FSYS_WRITE_REQUEST {common} cookie=0x{token:x} bytes=1288 request_fnv1a64={checker.fnv(bytes(1288)):016x} '
                    f'areas=1 observation_rc=0 path_hex={("A:/" + path).encode().hex()} payload_complete=1 '
                    f'expected_bytes={len(payload)} address_mode=1 media_origin_verified=0',
                    f'FSYS_WRITE_AREA {common} index=0 offset=0 bytes={len(payload)} data_fnv1a64={digest} readable=1 submitted_bytes={submitted}',
                    f'FSYS_WRITE_SUBMIT {common} rc=0 callback_seen=0',
                    f'MPR_WRITE_CALLBACK {common} cookie=0x{token:x} rc=0 result_copied=1 result_fnv1a64={checker.fnv(bytes(1240)):016x}',
                    f'MPR_WRITE_FINISHED {common} cookie=0x{token:x} rc=0 input_copied=1 returned=1',
                    f'MPR_WRITE_CALLBACK_RETURN {common} returned=1']
    files = []
    for token, path in enumerate(paths, 1):
        payload = path.read_bytes()
        records.append(f'FSYS_WRITE_NATIVE_READBACK pid=77 token={token} cookie=0x{token:x} rc=0 bytes={len(payload)} '
                       f'fnv1a64={checker.fnv(payload):016x} eof=1 close_rc=0')
        files.append(dict(path=str(path.relative_to(card)), bytes=len(payload), sha256=checker.sha(payload)))
    records.append('FSYS_WRITE_READBACK_COVERAGE pid=77 records=2 rc=0')
    (run / 'console.log').write_text('\n'.join(records) + '\n')
    export = dict(ok=True, bytes=256000000000, host_directory=str(card), host_directory_verified=True,
                  original_mount_verified=True, guest_block_sync_confirmed=True,
                  sequence=2, files=files, file_count=len(files),
                  quiesce=dict(owner_stopped=True, original_Fsys_FlushVolume_rc=0, sequence=2, pid=77, drive=65),
                  flush_lifecycle=dict(ok=True, resumed=True, status='resumed', sequence=2, pid=77),
                  directory_commit_status=dict(available=True, pending=False, closed_pending=False))
    (run / 'SD/export.json').write_text(json.dumps(export))
    first = copy.deepcopy(export)
    first['sequence'] = first['quiesce']['sequence'] = first['flush_lifecycle']['sequence'] = 1
    (run / 'gtk-input-proof.json').write_text(json.dumps(dict(sd_export=first, evidence_class='HOST_TEST')))
    return run, paths


def host_test_capture(root, vdf_paths=(), vdf_inline=False, initial_origin=None,
                      startup_stages=0, stage_inline=False, late_apply=False, refresh_source=0x81cf61c9,
                      configuration_only=False, histogram=False, histogram_log=None,
                      jpeg_main=False, jpeg_thumb=False, jpeg_endian='II', jpeg_model=None):
    """Full software replay; every native/observer field is explicitly HOST_TEST.

    Artifact/13-edge provenance is tested separately; this fixture calls the real
    transport/RGB/JPEG/PI/NAL/writeback/decoder stages without starting target code.
    vdf_paths keeps legacy bool/bytes8 Zebra/bytes32 layout entries;
    ('display', native_command[, body8]) selects the independent op8 command.
    Refresh0141/body0 uses only virtual body8 and interleaves a real State128
    exchange before the later original receive/free on its reusable global D.
    """
    actual_histogram = checker.parse_console(histogram_log.encode()) if histogram_log is not None else []
    histogram_owner = next((r['fields'] for r in actual_histogram if r['tag'] == 'FUNCTIONAL_HISTOGRAM_REQUEST_FREE'), None)
    guest_pid = int(histogram_owner['pid']) if histogram_owner else 77
    thumb = None
    if configuration_only:
        storage_run, jpeg, parsed_movie = None, b'', None
    else:
        primary = jpeg_model if jpeg_model is not None else independent_media('JPEG') if jpeg_main else None
        thumb = None
        if jpeg_thumb:
            from PIL import Image
            output = io.BytesIO()
            Image.new('RGB', (160, 120), 'blue').save(output, format='JPEG')
            thumb = output.getvalue()
        storage_run, paths = host_test_storage(root, host_test_exif(primary, thumb, jpeg_endian) if thumb else primary)
        exported_jpeg, movie = (path.read_bytes() for path in paths)
        jpeg = primary if primary is not None else exported_jpeg
        parsed_movie = checker.mp4_samples(movie)
    has_layout = any(isinstance(item, bytes) and len(item) == 32 for item in vdf_paths)
    has_bb = any(isinstance(item, tuple) and item[0] == 'bb' for item in vdf_paths)
    width, height = (640, 480) if has_layout or has_bb or histogram else (24, 16)
    rgb_hashes = {}
    records, operations = JFZ_VDF_RESOURCE_OBS.splitlines() if has_layout else [], []
    def row(tag, **fields):
        if histogram_owner and 'pid' in fields:
            fields['pid'] = guest_pid
        records.append(tag + ' ' + ' '.join(str(k) + '=' + str(v) for k, v in fields.items()))
    def hx(value):
        return hex(value) if value else '0'
    counts = dict(rendered=0, consumed=0, jpeg_encoded=0, video_encoded=0, retired=0)
    serial, generation, configuration = 0, 0, 1
    def proof(op, output, config_generation=None, active=True):
        nonlocal serial, generation
        config_generation = configuration if config_generation is None else config_generation
        serial += 1
        kind = {1: 0, 5: 4, 6: 4, 7: 4, 8: 4, 9: 5, 10: 6, 16: 1, 33: 2, 34: 3}[op]
        rendered = kind != 3 and (kind != 4 or active)
        consumer = kind != 0 and (kind != 4 or active)
        before = counts.copy()
        if rendered:
            generation += 1
            counts['rendered'] += 1
            counts['retired'] += 1
        if kind in (1, 2, 5, 6) or kind == 4 and active:
            counts['consumed'] += 1
        if kind in (1, 2):
            counts['jpeg_encoded' if kind == 1 else 'video_encoded'] += 1
        encoded = checker.jpeg_parts(output)['scan'] if kind == 1 else (
            b''.join(p['packet'] for p in checker.camera_packets(output)) if kind in (2, 3) else b'')
        if rendered and (width, height) not in rgb_hashes:
            rgb_hashes[width, height] = checker.fnv(bytes([0, 0, 255]) * (width * height))
        value = dict(version=1, struct_bytes=376, serial=serial, model_instance=99, model_lifetime=1,
                     owner_pid=177, opcode=op, consumer_kind=kind, config_generation=config_generation,
                     frame_generation=generation, lease_generation=generation if rendered else 0,
                     packet_generation=generation if kind in (2, 3) else 0,
                     width=width if rendered else 0, height=height if rendered else 0,
                     stride=width * 3 if rendered else 0, active_bytes=width * height * 3 if rendered else 0,
                     source_fnv1a64=rgb_hashes[width, height] if rendered else 0,
                     consumer_before_fnv1a64=0, consumer_after_fnv1a64=0,
                     render_observed=int(rendered), consumer_entered=int(consumer),
                     consumer_returned=int(consumer), encoder_consumed=int(kind in (1, 2)), retired=int(rendered),
                     source_state=3 if rendered else 0, consumer_before_state=4 if rendered and consumer else 0,
                     consumer_after_state=4 if rendered and consumer else 0, final_state=1 if kind != 3 else 0,
                     render_status=0 if rendered else -61, consumer_status=0 if consumer else -61,
                     retire_status=0 if rendered else -61, operation_status=0,
                     before=before, after=counts.copy(), encoded_bytes=len(encoded), encoded_fnv1a64=checker.fnv(encoded),
                     result_bytes=0 if kind in (0, 4) else len(output),
                     result_fnv1a64=checker.fnv(b'' if kind in (0, 4) else output),
                     result_token=len(operations) + 1 if kind in (1, 2, 3) else 0)
        if kind in (1, 2, 5, 6) or kind == 4 and active:
            value['consumer_before_fnv1a64'] = value['consumer_after_fnv1a64'] = value['source_fnv1a64']
        return value
    def state(config_generation=None, stream=0):
        config_generation = configuration if config_generation is None else config_generation
        raw = bytearray(128)
        struct.pack_into('<8I2Q', raw, 0, 1, 15, width, height, 30, 90, 400, 100, 10000, 1000000)
        struct.pack_into('<2Q4Q', raw, 48, 99, config_generation, *(counts[key] for key in
                         ('rendered', 'consumed', 'jpeg_encoded', 'video_encoded')))
        struct.pack_into('<I', raw, 108, stream)
        struct.pack_into('<Q', raw, 112, generation)
        return bytes(raw)
    body = bytearray(80)
    struct.pack_into('<3H', body, 0, 3, 0x304, 80)
    struct.pack_into('<H', body, 8, 7)
    struct.pack_into('<4H', body, 12, 3, 0x8310, 3, 0x8311)
    capacity = max(len(jpeg), len(thumb or b'')) + 64
    struct.pack_into('<I', body, 0x28, 5)
    struct.pack_into('<I', body, 0x34, capacity)
    struct.pack_into('<I', body, 0x3c, capacity)
    struct.pack_into('<2H', body, 0x40, 24, 16)
    body[0x49], body[0x4b] = 4, 1
    if jpeg_main:
        struct.pack_into('<2H', body, 0x44, 24, 16)
        body[0x49], body[0x4b] = 2, 0
    wire = bytearray(24) + body
    struct.pack_into('<2I2H2I', wire, 0, 0x802a0116, 0xa0a0a0a0, 1, 104, 24, 104)
    jpeg_origin = dict(producer_tid=90, source=0x802a0116, destination=0x82830752, command=0x30304,
                       bytes=104, fnv1a64=checker.fnv(wire))
    if startup_stages:
        stage_console = layout_stage_observations(startup_stages, stage_inline)
        records.extend(stage_console.splitlines())
        stage_final = checker.parse_console(stage_console.encode())[-1]['fields']
    if not vdf_paths or initial_origin is not None:
        init_proof = proof(1, b'')
        operations.append(dict(op=1, data=b'', output=state(), origin=initial_origin or jpeg_origin, proof=init_proof))
        records.append('HOST_TEST_TRANSFER_0')
    route, saved_zebra, refresh_bound = b'\x00\x01\x01' + bytes(13), bytes(8), False
    mixed_display = any(isinstance(item, (bytes, tuple)) for item in vdf_paths)
    cp_origin = dict(producer_tid=92, source=0x81cf1234, destination=0x92880001,
                     command=0x3003, bytes=8, fnv1a64=checker.fnv(b'HOST_TEST CP INIT'))
    for cycle, requested in enumerate(vdf_paths, 1):
        zebra = isinstance(requested, bytes) and len(requested) == 8
        layout = isinstance(requested, bytes) and len(requested) == 32
        display = isinstance(requested, tuple) and requested[0] == 'display'
        bb = isinstance(requested, tuple) and requested[0] == 'bb'
        assert not isinstance(requested, bytes) or zebra or layout
        op, command, native_bytes = (7, 0x14c, 40) if layout else (6, 0x153, 14) if zebra else (5, 0x138, 24)
        if bb:
            _, command, body = requested
            native_bytes = checker.BB_COMMANDS[command]
            assert len(body) == native_bytes - 8
            op = 9
            canonical = struct.pack('<2H', command, len(body)) + body + bytes(28 - len(body))
        elif display:
            assert requested[0] == 'display' and len(requested) in (2, 3) and requested[1] in (0x141, 0x152, 0x162)
            command = requested[1]
            body = requested[2] if len(requested) == 3 else PEAKING_BODY8 if command == 0x152 else bytes(8)
            assert len(body) == 8
            op, native_bytes = 8, {0x141: 8, 0x152: 16, 0x162: 10}[command]
            canonical = struct.pack('<2I', command, native_bytes - 8) + body
        else:
            canonical = requested if zebra or layout else bytes([int(requested), 5 if requested else 1, 5 if requested else 1, 0xa5, 2,
                                                                 0x63, 0x74, cycle, 0x91, 0x82, 0x73, 0x64, 0x55, 0, 0, 0])
        active = bool(route[0]) if zebra or layout or display or bb else requested
        if display or bb:
            original = struct.pack('<4H', 0x200d, command, native_bytes, 0x8001) + body[:native_bytes - 8]
        elif layout:
            original = bytes.fromhex('0d204c0128000180') + canonical
        elif zebra:
            saved_zebra = canonical
            original = bytes.fromhex('0d2053010e000180') + canonical[:5] + b'\xa5'
        else:
            route = canonical
            original = bytes.fromhex('0d20380118000180') + canonical[:13] + b'\xa5\xff\x55'
        native = dict(producer_tid=90,
                      source=0x81cf61d0 + list(checker.BB_COMMANDS).index(command) if bb else
                             {0x141: refresh_source, 0x152: 0x81cf61c7, 0x162: 0x81cf61c8}[command] if display else
                             0x81cf61c6 if layout else 0x81cf61c5 if zebra else 0x81cf61c4,
                      destination=0x92840747, command=command, bytes=native_bytes, fnv1a64=checker.fnv(original))
        if command == 0x141:
            appfw_base = 0x7f25c3f000
            row('FUNCTIONAL_VDF_REFRESH_QUEUE_BOUND', pid=77, tid=90,
                caller_pc=hex(appfw_base + 0x34e4f3c), global_va='0x910fa30',
                global_address=hex(appfw_base + 0x910fa30), source=hex(refresh_source),
                read_before=4, read_after=4, first=hex(refresh_source), second=hex(refresh_source),
                bind_rc=0, source_match=1, readback_verified=1, capture_verified=0)
            refresh_bound = True
        if cycle == 1:
            init_proof = proof(1, b'') if serial == 0 else None
            operations.append(dict(op=1, data=b'', output=state(), origin=native, proof=init_proof))
            records.append('HOST_TEST_TRANSFER_' + str(len(operations) - 1))
        else:
            configuration += 1
            control = struct.pack('<6I2Q2I', width, height, 30, 90, 400, 100, 10000, 1000000, 0, 0)
            operations.append(dict(op=3, data=control, output=state(), origin=jpeg_origin))
            records.append('HOST_TEST_TRANSFER_' + str(len(operations) - 1))
        before_config, before_frame = configuration, generation
        configuration += 1
        p = proof(op, b'', active=active)
        result = bytearray(192 if bb else 176 if display else 192 if layout else 168 if zebra else 160)
        struct.pack_into('<2I8Q14I', result, 0, 1, len(result), 99, configuration, generation,
                         generation if active else 0, checker.fnv(canonical),
                         p['source_fnv1a64'], p['consumer_after_fnv1a64'], p['active_bytes'],
                         width, height, width * 3, 0x90590819, 1, 1, 5 if bb else int(active), int(active), 1, 1,
                         int(active), int(active), 0, 0)
        result[128:144] = route
        struct.pack_into('<2Q', result, 144, before_frame, before_config)
        if zebra or layout or display or bb:
            result[160:] = canonical
        if bb:
            p.update(result_bytes=len(result), result_fnv1a64=checker.fnv(result))
        operations.append(dict(op=op, data=canonical, output=bytes(result), origin=native, proof=p))
        records.append('HOST_TEST_TRANSFER_' + str(len(operations) - 1))
        names = ('REQUEST_FREE', 'RECEIVE', 'AP_FREE', 'SEND', 'COMPLETE') if vdf_inline else (
                 'REQUEST_FREE', 'SEND', 'COMPLETE', 'RECEIVE', 'AP_FREE')
        for index, name in enumerate(names):
            queued, received, freed = (int(index >= names.index(key)) for key in ('SEND', 'RECEIVE', 'AP_FREE'))
            busy = int(index < names.index('COMPLETE'))
            consumed = int(queued and received and freed and not busy)
            row('FUNCTIONAL_VDF_PATH_' + name, pid=77, tid=90,
                phase=5 if consumed else 4 if received else 3 if queued else 2,
                cycle=cycle, requests=cycle, completed_cycles=cycle - 1 + consumed,
                busy=busy, guard=busy, faults=0, source=hex(native['source']), destination=hex(native['destination']),
                command=hex(command), bytes=native_bytes, original_fnv1a=f'{checker.fnv(original):016x}',
                refresh_queue_bound=int(refresh_bound), refresh_queue_source=hx(refresh_source if refresh_bound else 0),
                model_instance=99, config_generation=configuration, before_config_generation=before_config,
                frame_generation=generation, before_frame_generation=before_frame,
                lease_generation=generation if active else 0, init_rc=0, bridge_rc=0, validation_rc=0,
                request_owned=1, request_retained='(nil)', request_freed=1,
                ack_retained='(nil)' if freed or name == 'REQUEST_FREE' and (layout or display or bb) else '0x500000',
                queued=queued, received=received,
                AP_consumed=consumed, send_inflight=int(name in ('RECEIVE', 'AP_FREE') and not queued), releasing=0,
                sender_tid=90, receiver_tid=90 if received else 0, free_tid=90 if freed else 0,
                allocate_rc=0, send_rc=0, free_rc=0, model_complete=1, functional_model=1,
                original_CP_FIFO_verified=0, physical_CP_RTOS_verified=0, original_selector_verified=0,
                physical_ASIC_verified=0, capture_verified=0, raw=original.hex(),
                ack_wire=struct.pack('<4HI', 0x200d, command + 0x1000, 12, 0x8001, 0 if zebra or bb else 0x590000).hex(),
                canonical_config=route.hex(),
                model_result_fnv1a64=f'{checker.fnv(result):016x}', model_result_hex=result.hex(),
                **(dict(canonical_zebra8=saved_zebra.hex(), model_result_bytes=len(result)) if mixed_display else {}),
                **(dict(canonical_layout32=canonical.hex(), realresultbytes=len(result),
                        allocation_returned='(nil)' if name == 'REQUEST_FREE' else '0x500000',
                        allocation_alias=0, request_free_rc=0) if layout else {}),
                **(dict(canonical_display16=canonical.hex(),
                        allocation_returned='(nil)' if name == 'REQUEST_FREE' else '0x500000',
                        allocation_alias=0, request_free_rc=0) if display else {}),
                **(dict(canonical_bb32=canonical.hex(),
                        allocation_returned='(nil)' if name == 'REQUEST_FREE' else '0x500000',
                        allocation_alias=0, request_free_rc=0) if bb else {}))
            if command == 0x141 and name == 'SEND' and not vdf_inline:
                operations.append(dict(op=2, data=b'', output=state(), origin=cp_origin))
                records.append('HOST_TEST_TRANSFER_' + str(len(operations) - 1))
        if layout and late_apply:
            assert startup_stages
            row('FUNCTIONAL_LAYOUT_STAGE_APPLIED_RECEIPT', **dict(stage_final, tid=90,
                applied_receipt_verified=1, applied_stage_generation=startup_stages, applied_model_instance=99,
                applied_config_generation=configuration, applied_frame_generation=generation,
                applied_result_fnv1a64=f'{checker.fnv(result):016x}'))
        if mixed_display:
            repeat_origin = cp_origin if layout or display else jpeg_origin
            operations.append(dict(op=1, data=b'', output=state(), origin=repeat_origin))
            records.append('HOST_TEST_TRANSFER_' + str(len(operations) - 1))
    if histogram:
        source, appfw_base = int(histogram_owner['source'], 16) if histogram_owner else 0x80946180, 0x7f25c3f000
        sender = int(histogram_owner['tid']) if histogram_owner else 90
        original = bytes.fromhex('0d2048010c00018001010000')
        native = dict(producer_tid=sender, source=source, destination=0x92840747, command=0x148,
                      bytes=12, fnv1a64=checker.fnv(original))
        row('FUNCTIONAL_HISTOGRAM_QUEUE_BOUND', pid=guest_pid, tid=sender, caller_pc=hex(appfw_base + 0x34e53ac),
            global_va='0x910fa20', global_address=hex(appfw_base + 0x910fa20), source=hex(source),
            read_before=4, read_after=4, first=hex(source), second=hex(source), bind_rc=0,
            source_match=1, readback_verified=1, capture_verified=0)
        before_config, before_frame = configuration, generation
        configuration += 1
        p = proof(10, b'')
        result = bytearray(1192)
        struct.pack_into('<2I8Q14I', result, 0, 1, 1192, 99, configuration, generation, generation,
            checker.fnv(checker.HIST_CANONICAL), p['source_fnv1a64'], p['consumer_after_fnv1a64'], p['active_bytes'],
            width, height, width * 3, 0x90590819, 1, 1, 6, 1, 1, 1, 1, 1, 0, 0)
        result[128:144] = route
        struct.pack_into('<2Q', result, 144, before_frame, before_config)
        result[160:168] = checker.HIST_CANONICAL
        # HOST_TEST solid-blue RGB: virtual Y29, R0, G0, B255, one peak per channel.
        for offset in (168 + 29, 168 + 256, 168 + 512, 168 + 1023):
            result[offset] = 255
        p.update(result_bytes=1192, result_fnv1a64=checker.fnv(result))
        operations.append(dict(op=10, data=checker.HIST_CANONICAL, output=bytes(result), origin=native, proof=p))
        records.append('HOST_TEST_TRANSFER_' + str(len(operations) - 1))
        records.extend((histogram_log if histogram_log is not None else
                        histogram_observations(bytes(result), vdf_inline)).splitlines())
    if configuration_only:
        return host_test_transport(root, operations, '\n'.join(records) + '\n', guest_pid=guest_pid)
    if has_layout:
        width, height = 24, 16
        configuration += 1
        control = struct.pack('<6I2Q2I', width, height, 30, 90, 400, 100, 10000, 1000000, 0, 0)
        operations.append(dict(op=3, data=control, output=state(), origin=jpeg_origin))
        records.append('HOST_TEST_TRANSFER_' + str(len(operations) - 1))
    if vdf_paths:
        operations.append(dict(op=1, data=b'', output=state(), origin=jpeg_origin))
        records.append('HOST_TEST_TRANSFER_' + str(len(operations) - 1))
    base = 0x100000
    def jpeg_receipts(seq, encoded, packet_body, selector=0):
        nonlocal width, height
        packet = bytearray(wire[:24]) + packet_body
        native = dict(jpeg_origin, fnv1a64=checker.fnv(packet))
        geometry = checker.jpeg_parts(encoded)['geometry']
        saved_geometry = width, height
        width, height = geometry
        jpeg_proof = proof(16, encoded)
        operations.append(dict(op=16, data=struct.pack('<4I', 1, *geometry, 90), output=encoded, origin=native, proof=jpeg_proof))
        width, height = saved_geometry
        skip = 0 if packet_body[0x4b] else 2
        leased = encoded[skip:]
        common = dict(rc=0, pid=77, tid=81, producer_tid=81, sequence=seq, original_base=hx(base),
                      exec_entry=hx(base + (0x1226c4 if jpeg_main else 0x11b654)), caller=hx(base + 0x13b6ec),
                      object=hx(0x8000 + seq * 256), manager='0x9000', control='0xa000', context=1, key=0 if jpeg_main else 1,
                      source=hx(native['source']), destination=hx(native['destination']), command=hx(native['command']),
                      native_bytes=104, trigger_fnv=f'{checker.fnv(packet):016x}', response_tag=0, model_instance=0,
                      bytes=0, output_fnv='0000000000000000', stream_mode=packet_body[0x4b],
                      kind='main' if jpeg_main else 'without-pin', selector=selector, comp_object='(nil)',
                      physical_asic_compatible=0, capture_verified=0)
        def jr(operation, **fields):
            row('FUNCTIONAL_JPEG_CODEC', **dict(common, operation=operation, **fields))
        jr('original-request', request_hex=packet.hex())
        lease = dict(lease_address=hx(0x700000 + seq * 0x10000), lease_offset=0, lease_capacity=capacity,
                     lease_generation=seq, lease_token=hx(0x100 + seq))
        jr('original-request-lease', **lease, sds_type=0, sds_handle='0x5', sds_offset=0, stream_position=0,
           lease_group=1, lease_unit=5, lease_area=6, lease_unit_type=2)
        records.append('HOST_TEST_TRANSFER_' + str(len(operations) - 1))
        common.update(model_instance=99, bytes=len(leased), output_fnv=f'{checker.fnv(leased):016x}')
        jr('output-readback', **lease, tid=90, model_token=hx(jpeg_proof['result_token']), model_bytes=len(encoded),
           model_fnv=f'{checker.fnv(encoded):016x}', model_offset=skip, readback_bytes=len(leased), readback_fnv=f'{checker.fnv(leased):016x}')
        jr('queued-ack')
        ack = struct.pack('<4H2I', 3, 0x8310, 16, 0, 0, seq)
        for completion in (False, True):
            response = struct.pack('<4H2I', 3, 0x8311, 16, 0, 0, len(leased)) if completion else ack
            fields = dict(receiver_pid=77, receiver_tid=81, response_hex=response.hex(), response_source='0x82830752',
                          response_destination='0x802a0116', lease_generation=seq, lease_token=hx(0x100 + seq))
            reply = bytearray(24) + response
            struct.pack_into('<2I2H2I', reply, 0, 0, 0xa0a0a0a0, 1, 40, 24, 40)
            jr('original-received-done' if completion else 'original-received-ack', **fields,
               reply_address='0xb000', reply_hex=reply.hex())
            jr('original-freed-done' if completion else 'original-freed-ack', **fields,
               reply_address='0xb000', reply_hex=reply.hex(), free_rc=0)
            if completion and jpeg_main:
                jr('original-maincomp-config', native_config='0xd000', config_length_offset=0x5c + 12 * selector,
                   actual_length=len(leased), expected_length=len(leased), original_result=0)
            jr('original-rescmd-done' if completion else 'original-rescmd-ack', **fields, response_address='0xc000',
               callback_caller=hx(base + 0x13b788), res_entry=hx(base + ((0x122b44 if completion else 0x120e64) if jpeg_main else 0x11a9dc)),
               response_mid='0x8311' if completion else '0x8310', original_result=0 if completion or jpeg_main else '0x200',
               expected_result=0 if completion or jpeg_main else '0x200', original_errno=0,
               release_rc=0, terminal=int(completion), lease_released=int(completion))
            if not completion:
                jr('queued-done')
                if jpeg_main:
                    common['comp_object'] = hx(0xe000 + seq * 256)
                    jr('original-maincomp-exec', comp_caller=hx(base + 0x13b7e0), comp_exec_entry=hx(base + 0x122dfc),
                       previous_ack_hex=ack.hex(), previous_ack_address='0xc000', original_result=0,
                       native_config='0xd000', config_length_offset=0x5c + 12 * selector)
    jpeg_receipts(1, jpeg, wire[24:])
    if thumb:
        thumb_body = bytearray(wire[24:])
        struct.pack_into('<2H', thumb_body, 0x40, 160, 120)
        thumb_body[0x49], thumb_body[0x4b] = 4, 1
        jpeg_receipts(2, thumb, thumb_body, 1)
    native_requests, native_origins = {}, {}
    for seq, command in enumerate((0, 1, 3, 4), 1):
        request = bytearray(48)
        struct.pack_into('<H', request, 2, command)
        struct.pack_into('<I', request, 0x10, {0: 0x98, 1: 0x80, 3: 0x10, 4: 0}[command])
        request[0x18] = 0x20
        struct.pack_into('<I', request, 0x24, 0x210)
        native_requests[command] = bytes(request)
        native_origins[command] = dict(producer_tid=90, source=0x80c70047, destination=0x8055001f,
                                       command=command, bytes=48, fnv1a64=checker.fnv(request))
    def request(command):
        seq = (0, 1, 3, 4).index(command) + 1
        row('FUNCTIONAL_MPR_REQUEST', request_seq=seq, command=command, rc=0, pid=77, producer_tid=81,
            src='0x80c70047', dst='0x8055001f', native_bytes=48, native_fnv=hx(checker.fnv(native_requests[command])),
            epoch=1, memory_generation=1, instance=0 if command == 0 else 99, wire_hex=native_requests[command].hex())
    def completed(command):
        seq = (0, 1, 3, 4).index(command) + 1
        request_wire = native_requests[command]
        event = bytearray(48)
        struct.pack_into('<H', event, 2, command * 2 + 1)
        event[0x18] = 0x20
        struct.pack_into('<I', event, 0x24, 0x4e0)
        common_event = dict(seq=seq, command=command, wire_fnv=hx(checker.fnv(event)), src='0x8055001f', dst='0x80c70047',
                            received=1, rc=0, state=0, pending=0, owned=0, pid=77, observer_tid=81,
                            receiver_pid=77, receiver_tid=81, producer_pid=77, producer_tid=81, instance=99, epoch=1,
                            memory_generation=1, request_seq=seq, native_fnv=hx(checker.fnv(request_wire)), reply_address=hx(0xb000 + seq * 64),
                            operation_error=0, wire_hex=event.hex(), request_hex=request_wire.hex())
        row('FUNCTIONAL_MPR_EVENT_RECEIVED', **common_event)
        row('FUNCTIONAL_MPR_EVENT_FREE', **common_event)
        row('FUNCTIONAL_MPR_OPERATION', command=command, native_fnv=hx(checker.fnv(request_wire)), operation_error=0, event_error=0,
            request_seq=seq, epoch=1, memory_generation=1, instance=99, pid=77, producer_tid=81)
    request(0)
    operations.append(dict(op=1, data=b'', output=state(), origin=native_origins[0]))
    records.append('HOST_TEST_TRANSFER_' + str(len(operations) - 1))
    row('FUNCTIONAL_MPR_OPEN', width=24, height=16, virtual_fps=30, audio_field=3, es_capacity=1048576,
        pi_slots=16, P='0x1000', V='0x2000', epoch=1, instance=99, request_seq=1,
        native_fnv=hx(checker.fnv(native_requests[0])), memory_generation=1, es_address='0x900000', info_address='0xa00000',
        read_address='0xb00000', write_address='0xc00004', counter_address='0xc00000', es_correction=0)
    completed(0)
    request(1)
    config = struct.pack('<6I2Q2I', 24, 16, 30, 90, 400, 100, 10000, 1000000, 0, 0)
    configuration += 1
    operations.append(dict(op=32, data=config, output=state(configuration, 1), origin=native_origins[1]))
    records.append('HOST_TEST_TRANSFER_' + str(len(operations) - 1))
    params = b''.join(b'\x00\x00\x00\x01' + nal for nal in parsed_movie['parameters'])
    es_used, ticket, write_cursor, outstanding = 0, 0, 0, 0
    publications = []
    def publish(info, packet_generation, converted=b'', model_proof=None, result_length=0):
        nonlocal ticket, write_cursor, outstanding
        ticket += 1
        f = dict(epoch=1, instance=99, native_start_fnv=hx(checker.fnv(native_requests[1])), memory_generation=1,
                 group=1, pi_token='0x101', es_token='0x102', request_seq=2,
                 call_request_seq=3 if info[0] == 7 else 2,
                 call_native_fnv=hx(checker.fnv(native_requests[3 if info[0] == 7 else 1])),
                 model_token=hx(model_proof['result_token']), result_bytes=result_length, ticket=ticket, slot=ticket,
                 slot_generation=1, cycle=0, frame_generation=packet_generation, es_offset=es_used if converted else 0,
                 es_bytes=len(converted), es_fnv=hx(checker.fnv(converted)) if converted else 0,
                 read_address='0xb00000', read_token='0x103', control_token='0x104', read_before=0, read_after=0,
                 read_seen=0, write_before=write_cursor, write_after=ticket, observed_write=ticket,
                 counter_before=max(0, ticket - 2), counter_after=max(0, ticket - 2),
                 outstanding_before=outstanding, outstanding_after=outstanding + 1, pid=77, observer_tid=90,
                 info_address=hx(0xa00000 + ticket * 96), info_hex=bytes(info).hex(), rc=0)
        row('FUNCTIONAL_MPR_PI_PUBLISH', **f)
        publications.append(f)
        write_cursor, outstanding = ticket, outstanding + 1
        return f
    for index, nals in enumerate(parsed_movie['samples']):
        packet_bytes = b''.join(b'\x00\x00\x00\x01' + nal for nal in nals)
        header = bytearray(96)
        struct.pack_into('<2I3Q4I2Q2I', header, 0, 24, 16, index, index, 1, 1, 30, int(index == 0), 0,
                         len(packet_bytes), generation + 1, len(params), 0x61766331)
        output = bytes(header) + params + packet_bytes
        p = proof(33, output)
        operations.append(dict(op=33, data=b'', output=output, origin=native_origins[1], proof=p))
        records.append('HOST_TEST_TRANSFER_' + str(len(operations) - 1))
        for is_config, source, source_offset, values in (
                [(True, params, 96, parsed_movie['parameters'])] if index == 0 else []) + [
                (False, packet_bytes, 96 + len(params), nals)]:
            converted = checker.avcc_bytes(values)
            info = bytearray(96)
            info[0] = 4 if is_config else int(index != 0)
            struct.pack_into('<Q', info, 8, 0x900000 + es_used)
            struct.pack_into('<I', info, 0x10, len(converted))
            if is_config:
                info[1] = 6
                struct.pack_into('<H', info, 0x2c, len(values[0]) + 4)
                info[0x2e] = 1
                struct.pack_into('<H', info, 0x30, len(values[1]) + 4)
                info[0x32] = 1
            else:
                struct.pack_into('<2Q', info, 0x18, index * 3000, index * 3000)
            row('FUNCTIONAL_MPR_ES', epoch=1, instance=99, native_start_fnv=hx(checker.fnv(native_requests[1])), request_seq=2,
                call_request_seq=2, call_native_fnv=hx(checker.fnv(native_requests[1])), memory_generation=1, group=1, es_token='0x102',
                address=hx(0x900000 + es_used), offset=es_used, bytes=len(converted), avcc_fnv=hx(checker.fnv(converted)),
                nal_count=len(values), nal_payload_fnv=hx(checker.fnv(b''.join(values))), frame_generation=generation,
                packet_sequence=index, model_token=hx(p['result_token']), result_bytes=len(output), source_offset=source_offset,
                source_bytes=len(source), source_fnv=hx(checker.fnv(source)), info_type=info[0], pid=77, observer_tid=90, rc=0)
            pub = publish(info, generation, converted, p, len(output))
            es_used += len(converted)
            if not is_config:
                row('FUNCTIONAL_MPR_PACKET', epoch=1, instance=99, native_start_fnv=hx(checker.fnv(native_requests[1])),
                    frame_generation=generation, packet_bytes=len(packet_bytes), avcc_bytes=len(converted), avcc_fnv=hx(checker.fnv(converted)),
                    native_pts=index * 3000, native_hz=90000, es_used=es_used, es_capacity=1048576, memory_generation=1,
                    request_seq=2, ticket=pub['ticket'], slot=pub['slot'], slot_generation=1, model_token=hx(p['result_token']),
                    counter_before=index, counter_after=index + 1, read_after=0, write_after=pub['slot'],
                    es_address=hx(0x900000 + pub['es_offset']), es_offset=pub['es_offset'], es_token='0x102')
        if index == 0:
            completed(1)
    request(3)
    eos = bytearray(96)
    struct.pack_into('<2I3Q4I2Q2I', eos, 0, 24, 16, 4, 4, 0, 1, 30, 0, 1, 0, generation, 0, 0x61766331)
    p = proof(34, bytes(eos))
    operations.append(dict(op=34, data=b'', output=bytes(eos), origin=native_origins[3], proof=p))
    records.append('HOST_TEST_TRANSFER_' + str(len(operations) - 1))
    info = bytearray(96)
    info[0] = 7
    struct.pack_into('<2Q', info, 0x18, 12000, 12000)
    publish(info, generation, model_proof=p, result_length=len(eos))
    completed(3)
    request(4)
    operations.append(dict(op=66, data=b'', output=state(), origin=native_origins[4]))
    records.append('HOST_TEST_TRANSFER_' + str(len(operations) - 1))
    for f in publications:
        row('FUNCTIONAL_MPR_PI_RETURN', **dict(f, read_before=0, read_after=len(publications), read_seen=len(publications),
            observed_write=len(publications), counter_before=4, counter_after=4,
            outstanding_before=len(publications), outstanding_after=0))
    completed(4)
    native_console = '\n'.join(records) + '\n' + (storage_run / 'console.log').read_text()
    args = host_test_transport(root, operations, native_console)
    run = args[0]
    (run / 'SD').mkdir()
    (run / 'SD/export.json').write_bytes((storage_run / 'SD/export.json').read_bytes())
    (run / 'gtk-input-proof.json').write_bytes((storage_run / 'gtk-input-proof.json').read_bytes())
    # Both cards stay in the fixture run; update export roots without changing media bytes.
    card = run / 'host-sd'
    (storage_run / 'host-sd').rename(card)
    for path in (run / 'SD/export.json', run / 'gtk-input-proof.json'):
        value = json.loads(path.read_text())
        (value.get('sd_export') or value)['host_directory'] = str(card)
        path.write_text(json.dumps(value))
    return args


def control_state(fps=30, generation=7, aperture=400, shutter=10000, iso=100):
    raw = bytearray(128)
    struct.pack_into('<8I2Q', raw, 0, 1, 15, 640, 480, fps, 90, aperture, iso, shutter, 1000000)
    struct.pack_into('<3Q', raw, 48, 99, generation, 1)
    struct.pack_into('<Q', raw, 112, 1)
    return bytes(raw)


def control_fields(state=None):
    """Timing subset of the real regular record, not an AP lifecycle substitute."""
    fields = dict.fromkeys(checker.XSYNC_FIELDS + ('defined_blocks', 'projected_blocks', 'zero_policy_blocks',
        'full_layout_copied', 'model_defined', 'publication_copied', 'published_generation'), '0')
    if state is not None:
        fps, generation = struct.unpack_from('<I', state, 16)[0], struct.unpack_from('<Q', state, 56)[0]
        fields.update(zip(checker.XSYNC_FIELDS, map(str, (1, fps, fps, 1, generation))))
        fields.update(defined_blocks='76', projected_blocks='3', zero_policy_blocks='72',
                      full_layout_copied='1', model_defined='1', publication_copied='1', published_generation=str(generation))
    return fields


def host_test_control(root, probe_states=None):
    """HOST_TEST actual broker-byte joins: full7, ACK-only7, full8; no media."""
    records, operations = [], []
    probe_states = probe_states or {}
    cached = control_fields()
    for index, state in enumerate((control_state(), control_state(), control_state(), control_state(25, 8))):
        start, publish = index == 0, index in (1, 3)
        command, size = (0x3003, 24) if start else (0x4073, 12)
        wire = struct.pack('<HHI', 0 if start else 5, command, 0x80000027) + (bytes(16) if start else struct.pack('<I', 1))
        origin = dict(producer_tid=90, source=0x80020002, destination=0x90030001,
                      command=command, bytes=size, fnv1a64=checker.fnv(wire))
        operations.append(dict(op=1 if start else 2, data=b'', output=probe_states.get(index, state), origin=origin))
        records.append('HOST_TEST_TRANSFER_' + str(index))
        current = dict(cached, pid='77', tid='90', index='0' if start else '2', role='1',
            bytes=str(size), functional_model='1', original_CP='0', physical_ASIC_verified='0', capture='0',
            faults='0', bridge_rc='0', probe_rc='0', probe_run_id=str(index + 1), init_run_id='1',
            state_run_id='0' if start else str(index + 1), model_instance='99',
            config_generation=str(struct.unpack_from('<Q', state, 56)[0]), cycle_id=str(max(0, index - 1)),
            ack_only='1' if index == 2 else '0', lease_cycle_id=str(max(0, index - 1)),
            native_source=hex(origin['source']), native_destination=hex(origin['destination']),
            native_command=hex(command), native_bytes=str(size), native_fnv1a=f'{origin["fnv1a64"]:016x}')
        def row(tag, fields):
            records.append('FUNCTIONAL_CAMERA_CONTROL_' + tag + ' ' + ' '.join(f'{k}={v}' for k, v in fields.items()))
        row('PROBE', current)
        if publish:
            cached = control_fields(state)
            current.update(cached, cycle_id=str(index), lease_cycle_id=str(index))
            full = checker.full_snapshot(state)
            row('SENT', dict(current, index='4', role='3', bytes='1748', wire_fnv1a=f'{checker.fnv(full):016x}'))
            row('RECEIVE', dict(pid='77', tid='91', index='4', role='3', functional_model='1', original_CP='0',
                physical_ASIC_verified='0', capture='0', result='1', reason='accepted', lease_cycle=str(index),
                event_cycle=str(index), bytes='1748', actual_bytes='1748', expected_bytes='1748',
                destination='0x80020002', expected_destination='0x80020002', source='0x90030001',
                actual_source='0x90030001', expected_source='0x90030001',
                envelope_checked='1', wire_checked='1', wire_fnv1a=f'{checker.fnv(full):016x}',
                expected_fnv1a=f'{checker.fnv(full):016x}'))
        row('COMMIT', current)
    return host_test_transport(root, operations, '\n'.join(records) + '\n')


class EvidenceTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='HOST_TEST_functional_evidence_')
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def transport(self):
        args = host_test_transport(self.root)
        return args, checker.check_transport(*args)

    def capture(self):
        args = host_test_capture(self.root)
        transport = checker.check_transport(*args)
        storage = checker.writeback.inspect(args[0])
        self.assertTrue(storage['writeback_verified'], storage)
        self.assertTrue(storage['independent_decoded'], storage)
        return args, transport, storage

    @classmethod
    def background_binary(cls, sanitized=False):
        key = '_background_binary_SAN' if sanitized else '_background_binary'
        if hasattr(cls, key):
            return getattr(cls, key)
        temporary = tempfile.TemporaryDirectory(prefix='HOST_TEST_background_evidence_C_')
        cls.addClassCleanup(temporary.cleanup)
        directory = Path(temporary.name)
        owner_tests = checker.source_module(checker.RUNTIME / 'test_functional_background_start.py')
        original = checker.RUNTIME / 'device-models/test-functional-background-start.c'
        source = original.read_text()
        source = source.replace('    logs++;', '    logs++; printf("%s%s\\n", tag, text);')
        anchor = '    memcpy(op == FCAM_OP_INIT ? actual_init : actual_state, output, 128);'
        assert source.count(anchor) == 1
        source = source.replace(anchor, anchor + '''
    printf("HOST_TEST_CORE op=%u producer_tid=%ld state128=", op, tid());
    for (size_t i = 0; i < 128; i++) printf("%02x", ((unsigned char *)output)[i]);
    struct fcam_frame_proof evidence = {0};
    assert(!fcam_model_proof_snapshot(model, &evidence, sizeof evidence));
    printf(" proof376=");
    for (size_t i = 0; i < sizeof evidence; i++) printf("%02x", ((const unsigned char *)&evidence)[i]);
    puts("");''')
        fixture = directory / 'background.c'
        fixture.write_text(source)
        binary = directory / 'background'
        libraries = shlex.split(subprocess.check_output(['pkg-config', '--cflags', '--libs', 'libjpeg',
            'libavcodec', 'libavformat', 'libavutil', 'libswscale'], text=True, timeout=10))
        flags = ['-fsanitize=address,undefined', '-fno-sanitize-recover=all'] if sanitized else []
        built = subprocess.run([*shlex.split(os.environ.get('CC', 'cc')), '-DHOST_TEST', '-std=c11', '-Wall', '-Wextra',
            '-Werror', '-pedantic', '-O1', '-g', '-fno-omit-frame-pointer', '-fno-pie', '-no-pie', '-pthread', *flags,
            '-I', str(original.parent),
            str(checker.RUNTIME / 'device-models/functional-background-start.c'), str(fixture),
            *(str(checker.NATIVE / 'report' / s) for s in owner_tests.SOURCES), *libraries, '-lm', '-o', str(binary)],
            cwd=directory, capture_output=True, text=True, timeout=90)
        assert built.returncode == 0, built.stdout + built.stderr
        setattr(cls, key, binary)
        return binary

    def background(self, scenario='deferred-thread', *, root=None, require_native=False, sanitized=False):
        """Actual C stdout; native-format parser support is explicitly simulated, never a VM run."""
        process = subprocess.run([str(self.background_binary(sanitized)), scenario], capture_output=True,
                                 env={**os.environ, 'ASAN_OPTIONS': 'detect_leaks=1:halt_on_error=1:abort_on_error=1',
                                      'UBSAN_OPTIONS': 'halt_on_error=1:print_stacktrace=1'},
                                 text=True, check=True, timeout=30)
        self.assertNotIn('Sanitizer', process.stderr)
        self.assertNotIn('runtime error:', process.stderr)
        records = process.stdout.splitlines()
        actual = checker.parse_console(process.stdout.encode())
        accept = next(r for r in actual if r['tag'] == 'FUNCTIONAL_BACKGROUND_START_ACCEPT')['fields']
        pid, sender, source = (checker.number(accept[k]) for k in ('pid', 'sender_tid', 'source'))
        broker = checker.source_module(checker.RUNTIME / 'functional_camera_broker.py')
        operations, console, bound = [], [], 0
        for text in records:
            if text.startswith('FUNCTIONAL_BACKGROUND_START_ACCEPT '):
                accept = dict(p.split('=', 1) for p in text.split()[1:])
                source = checker.number(accept['source'])
                bound += 1
                console.append('FUNCTIONAL_BACKGROUND_START_SOURCE_BOUND ' + ' '.join(f'{k}={v}' for k, v in dict(
                    pid=pid, tid=sender, caller_pc=hex(0x7000000000 + 0xeda50), caller_va='0xeda50',
                    library_base='0x7000000000', source=hex(source), reads='4/4', first='0x97fdb339',
                    second='0x97fdb339', bind_rc=0, original_cp_modules_verified=0, capture_verified=0).items()))
            if text.startswith('FUNCTIONAL_BACKGROUND_START_INIT_BEGIN '):
                producer = checker.number(dict(p.split('=', 1) for p in text.split()[1:])['producer_tid'])
                if not operations:
                    # Explicit simulated parent support, never native predecessor execution.
                    for tag in checker.BACKGROUND_FREE_TAGS:
                        waiter = tag.endswith('_NATIVE_REPLY_FREE') or 'VEF_PINMEM_CONTROL' in tag or 'HDMI_AUDIO' in tag
                        pointer = 'reply' if tag.endswith('_NATIVE_REPLY_FREE') else 'pointer'
                        fields_free = dict(pid=pid, tid=sender, destination='0x80020002', expected='0x80020002',
                                           bytes=56, rc=0, faults=0, ap_consumed=1, capture_verified=0)
                        fields_free[pointer] = '0x400000'
                        if waiter:
                            fields_free.update(sender=sender, waiter=1)
                        if tag.endswith('_NATIVE_REPLY_FREE'):
                            fields_free['command'] = '0x8001'
                        elif tag != 'FULL_ADF_HDMI_AUDIO_CONNECT_REPLY_FREE':
                            fields_free['frames_verified'] = 0
                        if tag == 'FULL_IMAGING_ADF_CONNECT_REPLY_FREE':
                            fields_free['pcm_verified'] = 0
                        if tag == 'FULL_PINMEM_HDMI_VIDEO_CONNECT_NATIVE_REPLY_FREE':
                            fields_free['producer_tid'] = producer
                        console.append(tag + ' ' + ' '.join(f'{k}={v}' for k, v in fields_free.items()))
                console.append(f'NATIVE_CP302C_DIAGNOSTIC_ALL13_READBACK pid={pid} tid={producer} accepted=1 '
                    'video_AP_consumed=1 OSD_AP_consumed=1 audio_AP_consumed=1 OSD_live=16 OSD_owners_each=2 '
                    'OSD_opens_each=2 global_DMM_idle_claimed=0 capture_verified=0')
                guards = JFZ_VDF_RESOURCE_OBS.replace('FUNCTIONAL_VDF_PATH_', 'FUNCTIONAL_BACKGROUND_START_')
                guards = guards.replace('pid=258', f'pid={pid}').replace('tid=381', f'tid={producer}')
                console.extend(guards.splitlines())
            if text.startswith('FUNCTIONAL_BACKGROUND_START_'):
                console.append(text)
            elif text.startswith('HOST_TEST_CORE '):
                fields = dict(p.split('=', 1) for p in text.split()[1:])
                output = bytes.fromhex(fields['state128'])
                raw_proof = broker.FrameProof.from_buffer_copy(bytes.fromhex(fields['proof376']))
                proof = {k: ({n: getattr(getattr(raw_proof, k), n) for n, _ in getattr(raw_proof, k)._fields_}
                             if k in ('before', 'after') else getattr(raw_proof, k)) for k, _ in raw_proof._fields_}
                producer = int(fields['producer_tid'])
                origin = dict(producer_tid=producer, source=source, destination=0x90030001, command=0x3006,
                              bytes=24, fnv1a64=int(accept['wire_fnv'], 16))
                operations.append(dict(op=int(fields['op']), data=b'', output=output, origin=origin,
                                       proof=proof if int(fields['op']) == 1 and len(operations) == 0 else None))
                console.append('HOST_TEST_TRANSFER_' + str(len(operations) - 1))
        self.assertEqual(bound, sum(r['tag'] == 'FUNCTIONAL_BACKGROUND_START_ACCEPT' for r in actual))
        instance = struct.unpack_from('<Q', operations[0]['output'], 48)[0]
        args = host_test_transport(root or self.root, operations, '\n'.join(console) + '\n', guest_pid=pid,
                                   model_instance=instance, model_owner_pid=proof['owner_pid'],
                                   evidence_class='NATIVE_PARSER_TEST' if require_native else 'HOST_TEST')
        return args

    def test_background_real_owner_Core_full_chain_and_no_physical_promotion(self):
        args = self.background()
        transport = checker.check_transport(*args)
        evidence = transport['background_start']
        self.assertTrue(evidence['content_join_verified'], evidence)
        self.assertTrue(evidence['causal_trace_verified'])
        self.assertTrue(evidence['functional_core_initialized'])
        self.assertFalse(evidence['verified'])
        self.assertFalse(evidence['native_completion_verified'])
        self.assertFalse(evidence['AP_consumed'])
        self.assertTrue(evidence['pending'])
        cycle, = evidence['cycles']
        self.assertNotEqual(cycle['sender_tid'], cycle['producer_tid'])
        self.assertEqual((cycle['INIT_sequence'], cycle['STATE_sequence']), (1, 2))
        for key in ('capture_verified', 'hardware_ready', 'image_ready', 'business_published',
                    'physical_asic_compatibility_verified', 'original_CP_executed', 'CP_modules_verified',
                    'original_masks_verified', 'original_CP_RTOS_verified'):
            self.assertIs(evidence[key], False)
        with self.assertRaises(checker.MissingEvidence):
            checker.check_frames(args[0], transport)  # INIT128 still cannot replace JPEG/H264/drain.

    def test_background_pending_is_reported_without_verifying_or_borrowing_generic_ACK(self):
        args = self.background()
        start = next(r['line'] for r in args[2] if r['tag'] == 'FUNCTIONAL_BACKGROUND_START_ACCEPT')
        rows = [r for r in args[2] if r['line'] <= start + 2]
        result = checker.check_background_start(args[0], args[1], rows)
        self.assertTrue(result['pending'])
        self.assertFalse(result['verified'])
        self.assertFalse(result['AP_consumed'])
        fake = copy.deepcopy(rows)
        fake[1]['fields'].update(AP_consumed='1', transport_complete='1', pending='0')
        with self.assertRaises(ValueError):
            checker.check_background_start(args[0], args[1], fake)
        transport = checker.check_transport(*args)
        for tag in ('INIT', 'STATE', 'READBACK', 'REQUEST_FREE', 'ALLOCATE', 'SEND', 'RECEIVE', 'AP_FREE'):
            altered = [r for r in args[2] if r['tag'] != 'FUNCTIONAL_BACKGROUND_START_' + tag]
            with self.subTest(missing=tag), self.assertRaises(ValueError):
                checker.check_background_start(args[0], args[1], altered, transport)

    def test_background_source_scope_cycle_actual_State_and_lifecycle_corruptions(self):
        args = self.background()
        transport = checker.check_transport(*args)
        changes = [
            ('SOURCE_BOUND', 'reads', '4/3'), ('SOURCE_BOUND', 'first', '0x97fdb338'),
            ('SOURCE_BOUND', 'source', '0x810261c5'), ('SOURCE_BOUND', 'caller_va', '0xeda54'),
            ('ACCEPT', 'source', '0x80020002'), ('ACCEPT', 'cycle', '2'), ('ACCEPT', 'bytes', '12'),
            ('ACCEPT', 'requests', '2'), ('ACCEPT', 'hardware_ready', '1'), ('ACCEPT', 'CP_modules_verified', '1'),
            ('INIT', 'instance', '100'), ('INIT', 'result_token', '1'), ('STATE', 'full_state_fnv', '0' * 16),
            ('READBACK', 'cache_fnv', '0' * 16), ('READBACK', 'frame_generation', '0'),
            ('REQUEST_FREE', 'request_freed', '0'), ('SEND', 'readback', '0'),
            ('RECEIVE', 'sender_tid', '1'), ('AP_FREE', 'receiver_tid', '1'), ('AP_FREE', 'AP_consumed', '0'),
        ]
        for suffix, key, value in changes:
            rows = copy.deepcopy(args[2])
            target = next(r for r in rows if r['tag'] == 'FUNCTIONAL_BACKGROUND_START_' + suffix)
            target['fields'][key] = value
            with self.subTest(tag=suffix, field=key), self.assertRaises(ValueError):
                checker.check_background_start(args[0], args[1], rows, transport)
        for tag, key in (('ACCEPT', 'raw24'), ('SEND', 'reply12'), ('INIT', 'actual_state128'),
                         ('STATE', 'actual_state128'), ('READBACK', 'actual_state128')):
            original = next(r for r in args[2] if r['tag'] == 'FUNCTIONAL_BACKGROUND_START_' + tag)['fields'][key]
            for byte in range(len(original) // 2):
                rows = copy.deepcopy(args[2])
                target = next(r for r in rows if r['tag'] == 'FUNCTIONAL_BACKGROUND_START_' + tag)
                raw = bytearray.fromhex(original)
                raw[byte] ^= 1
                target['fields'][key] = raw.hex()
                with self.subTest(tag=tag, byte=byte), self.assertRaises(ValueError):
                    checker.check_background_start(args[0], args[1], rows, transport)

    def test_background_actual_transport_predecessor_and_lease_joins_are_not_copy_fields(self):
        args = self.background()
        transport = checker.check_transport(*args)
        for index, key, value in ((0, 'producer_tid', 1), (0, 'source', 0x80020002), (0, 'command', 0x3003),
                                  (1, 'source', 0x810261c5), (1, 'fnv1a64', 1)):
            changed = copy.deepcopy(transport)
            changed['transfers'][index]['origin'][key] = value
            with self.subTest(origin=key, index=index), self.assertRaises(ValueError):
                checker.check_background_start(args[0], args[1], args[2], changed)
        for tag in checker.BACKGROUND_FREE_TAGS:
            rows = [r for r in args[2] if r['tag'] != tag]
            with self.subTest(missing_native_free=tag), self.assertRaises(ValueError):
                checker.check_background_start(args[0], args[1], rows, transport)
        for suffix in ('RESOURCES_RESERVED', 'RESOURCE_DEPENDENCIES', 'RESOURCES_TTS_TABLE'):
            rows = [r for r in args[2] if r['tag'] != 'FUNCTIONAL_BACKGROUND_START_' + suffix]
            with self.subTest(missing_guard=suffix), self.assertRaises(ValueError):
                checker.check_background_start(args[0], args[1], rows, transport)
        changed = copy.deepcopy(transport)
        changed['safe_cleanup'] = False
        with self.assertRaises(ValueError):
            checker.check_background_start(args[0], args[1], args[2], changed)
        for key, value in (('free_rc', '-5'), ('cycle', '2'), ('source', '0x90030002'),
                           ('free_tid', '1'), ('pointer', '0x1234'), ('consumed', '0')):
            rows = copy.deepcopy(args[2])
            event = next(r for r in rows if r['tag'] == 'FUNCTIONAL_BACKGROUND_START_AP_FREE')
            lease = next(r for r in rows if r['line'] == event['line'] + 2)
            lease['fields'][key] = value
            with self.subTest(lease_field=key), self.assertRaises(ValueError):
                checker.check_background_start(args[0], args[1], rows, transport)

    def test_background_real_inline_pending_repeat_and_native_observation_gate(self):
        for scenario in ('inline', 'no-receive', 'address-reuse', 'dynamic-source', 'retired-source', 'cookie-zero', 'cookie-max'):
            root = self.root / scenario
            root.mkdir()
            args = self.background(scenario, root=root)
            transport = checker.check_transport(*args)
            result = transport['background_start']
            complete = scenario != 'no-receive'
            with self.subTest(scenario=scenario):
                self.assertFalse(result['verified'])
                self.assertEqual(result['content_join_verified'], complete)
                self.assertEqual(result['causal_trace_verified'], complete)
                self.assertTrue(result['pending'])
                self.assertIs(result['native_completion_verified'], False)
                if scenario == 'address-reuse':
                    self.assertEqual(len(result['cycles']), 2)
                    self.assertEqual(result['cycles'][0]['actual_State128_sha256'], result['cycles'][1]['actual_State128_sha256'])
                self.assertIn('HOST_TEST support does not prove native AP/SDK/all13 execution',
                              result['missing_native_observations'])

    def test_background_native_formatter_complete_parser_strict_and_SAN(self):
        for sanitized in (False, True):
            for scenario in ('deferred-thread', 'inline', 'retired-source'):
                root = self.root / f'native-format-{sanitized}-{scenario}'
                root.mkdir()
                args = self.background(scenario, root=root, require_native=True, sanitized=sanitized)
                result = checker.check_transport(*args)['background_start']
                with self.subTest(scenario=scenario, sanitized=sanitized):
                    self.assertEqual(args[1]['evidence_class'], 'NATIVE_PARSER_TEST')
                    self.assertTrue(result['verified'], result)
                    self.assertTrue(result['native_completion_verified'])
                    self.assertTrue(result['content_join_verified'])
                    self.assertTrue(result['causal_trace_verified'])
                    self.assertTrue(result['AP_consumed'])
                    self.assertFalse(result['pending'])
                    self.assertFalse(result['capture_verified'])
                    self.assertEqual(result['missing_native_observations'], [])
                    self.assertEqual(len(result['cycles']), 2 if scenario == 'retired-source' else 1)
                    if scenario == 'retired-source':
                        self.assertNotEqual(result['cycles'][0]['source'], result['cycles'][1]['source'])
                    self.assertTrue(all(c['native_completion_verified'] for c in result['cycles']))

    def test_background_snapshot_groups_allow_interleaved_leases_and_capture_order(self):
        args = self.background(require_native=True)
        transport = checker.check_transport(*args)
        rows = copy.deepcopy(args[2])
        leases = [r for r in rows if r['tag'] == 'FUNCTIONAL_BACKGROUND_START_LEASE']
        rows = [r for r in rows if r not in leases]
        # The logger can emit a later capture while an earlier snapshot's leases wait.
        delayed = [r for r in rows if r['tag'] in ('FUNCTIONAL_BACKGROUND_START_SEND',
                   'FUNCTIONAL_BACKGROUND_START_PROGRESS') and r['fields']['model_complete'] == '1']
        rows = [r for r in rows if r not in delayed] + delayed + leases[::-1]
        for line, row in enumerate(rows, 1):
            row['line'] = line
        changed = copy.deepcopy(transport)
        for tx in changed['transfers']:
            tx['line'] = next(r['line'] for r in rows if r['tag'] == 'FUNCTIONAL_CAMERA_TRANSFER' and
                              r['fields']['seq'] == f'{tx["first"]}..{tx["last"]}')
        result = checker.check_background_start(args[0], args[1], rows, changed)
        self.assertTrue(result['verified'], result)
        self.assertTrue(result['native_completion_verified'])
        self.assertFalse(result['capture_verified'])

    def test_background_legacy_formatter_stays_pending_and_partial_new_fields_reject(self):
        args = self.background(require_native=True)
        transport = checker.check_transport(*args)
        rows = copy.deepcopy(args[2])
        begins = {r['fields']['snapshot_id'] for r in rows if r['tag'] in
                  ('FUNCTIONAL_BACKGROUND_START_INIT_BEGIN', 'FUNCTIONAL_BACKGROUND_START_STATE_BEGIN')}
        # Emulate the old schema only in this explicit missing-evidence negative.
        rows = [r for r in rows if r['fields'].get('snapshot_id') not in begins]
        for row in rows:
            if row['tag'].startswith('FUNCTIONAL_BACKGROUND_START_'):
                for key in ('snapshot_id', 'init_calls', 'state_calls', 'receive_ticket', 'free_ticket',
                            'cached_state128', 'readback_state128'):
                    row['fields'].pop(key, None)
        result = checker.check_background_start(args[0], args[1], rows, transport)
        self.assertTrue(result['content_join_verified'])
        self.assertTrue(result['pending'])
        self.assertFalse(result['verified'])
        self.assertFalse(result['native_completion_verified'])
        self.assertFalse(result['AP_consumed'])
        self.assertEqual(len(result['missing_native_observations']), 4)
        for tag, key in (('ACCEPT', 'snapshot_id'), ('RECEIVE', 'receive_ticket'), ('AP_FREE', 'free_ticket'),
                         ('INIT', 'cached_state128'), ('STATE', 'readback_state128'), ('READBACK', 'cached_state128')):
            changed = copy.deepcopy(args[2])
            del next(r['fields'] for r in changed if r['tag'] == 'FUNCTIONAL_BACKGROUND_START_' + tag)[key]
            with self.subTest(tag=tag, missing=key), self.assertRaises(ValueError):
                checker.check_background_start(args[0], args[1], changed, transport)

    def test_background_preRPC_BEGIN_guard_all13_causality_rejects(self):
        args = self.background(require_native=True)
        transport = checker.check_transport(*args)
        for tag in ('INIT_BEGIN', 'STATE_BEGIN'):
            rows = [r for r in args[2] if r['tag'] != 'FUNCTIONAL_BACKGROUND_START_' + tag]
            with self.subTest(missing=tag), self.assertRaises(ValueError):
                checker.check_background_start(args[0], args[1], rows, transport)
        first_free = min(r['line'] for r in args[2] if r['tag'] in checker.BACKGROUND_FREE_TAGS)
        init_result = next(r['line'] for r in args[2] if r['tag'] == 'FUNCTIONAL_BACKGROUND_START_INIT')
        for tag, line in (('INIT_BEGIN', transport['transfers'][0]['line'] + 1),
                          ('STATE_BEGIN', transport['transfers'][1]['line'] + 1),
                          ('INIT_BEGIN', first_free - 1), ('STATE_BEGIN', init_result - 1)):
            rows = copy.deepcopy(args[2])
            next(r for r in rows if r['tag'] == 'FUNCTIONAL_BACKGROUND_START_' + tag)['line'] = line
            with self.subTest(tag=tag, line=line), self.assertRaises(ValueError):
                checker.check_background_start(args[0], args[1], rows, transport)
        for tag, key, value in (('INIT_BEGIN', 'guard', '0'), ('STATE_BEGIN', 'working', '0'),
                                ('INIT_BEGIN', 'predecessor_rc', '0'), ('RESOURCES_RESERVED', 'control_live', '1'),
                                ('RESOURCES_RESERVED', 'pinmem_live', '1'), ('RESOURCES_RESERVED', 'data_frozen', '1')):
            rows = copy.deepcopy(args[2])
            next(r['fields'] for r in rows if r['tag'] == 'FUNCTIONAL_BACKGROUND_START_' + tag)[key] = value
            with self.subTest(tag=tag, field=key), self.assertRaises(ValueError):
                checker.check_background_start(args[0], args[1], rows, transport)

    def test_background_snapshot_ticket_call_counter_and_cycle_ownership_rejects(self):
        args = self.background(require_native=True)
        transport = checker.check_transport(*args)
        for tag, key, value in (('INIT_BEGIN', 'snapshot_id', '1'), ('INIT', 'snapshot_id', '0'),
                                ('STATE', 'snapshot_id', '01'), ('READBACK', 'snapshot_id', str(2**64)),
                                ('INIT_BEGIN', 'init_calls', '0'), ('INIT_BEGIN', 'state_calls', '1'),
                                ('STATE_BEGIN', 'init_calls', '0'), ('STATE_BEGIN', 'state_calls', '0'),
                                ('RECEIVE', 'receive_ticket', '0'), ('RECEIVE', 'free_ticket', '1'),
                                ('AP_FREE', 'receive_ticket', '2'), ('AP_FREE', 'free_ticket', '2'),
                                ('AP_FREE', 'free_ticket', '0'), ('SEND', 'init_calls', '2')):
            rows = copy.deepcopy(args[2])
            next(r['fields'] for r in rows if r['tag'] == 'FUNCTIONAL_BACKGROUND_START_' + tag)[key] = value
            with self.subTest(tag=tag, field=key, value=value), self.assertRaises(ValueError):
                checker.check_background_start(args[0], args[1], rows, transport)
        for corruption in ('missing-lease', 'duplicate-lease', 'duplicate-main', 'probe-with-lease',
                           'cross-snapshot', 'cross-cycle'):
            rows = copy.deepcopy(args[2])
            lease = next(r for r in rows if r['tag'] == 'FUNCTIONAL_BACKGROUND_START_LEASE')
            if corruption == 'missing-lease':
                rows.remove(lease)
            elif corruption == 'duplicate-lease':
                rows.append(copy.deepcopy(lease))
            elif corruption == 'duplicate-main':
                rows.append(copy.deepcopy(next(r for r in rows if r['tag'] == 'FUNCTIONAL_BACKGROUND_START_INIT')))
            elif corruption == 'probe-with-lease':
                lease['fields']['snapshot_id'] = next(r['fields']['snapshot_id'] for r in rows
                                                      if r['tag'] == 'FUNCTIONAL_BACKGROUND_START_INIT')
            elif corruption == 'cross-snapshot':
                lease['fields']['snapshot_id'] = str(int(lease['fields']['snapshot_id']) + 1)
            else:
                lease['fields']['cycle'] = '2'
            with self.subTest(corruption=corruption), self.assertRaises(ValueError):
                checker.check_background_start(args[0], args[1], rows, transport)

    def test_background_independent_cache_readback_full_bytes_FNV_and_nonce_rejects(self):
        args = self.background(require_native=True)
        transport = checker.check_transport(*args)
        for tag in ('INIT', 'STATE', 'READBACK'):
            for key in ('cached_state128', 'readback_state128'):
                for byte in range(128):
                    rows = copy.deepcopy(args[2])
                    fields = next(r['fields'] for r in rows if r['tag'] == 'FUNCTIONAL_BACKGROUND_START_' + tag)
                    raw = bytearray.fromhex(fields[key])
                    raw[byte] ^= 1
                    fields[key] = raw.hex()
                    with self.subTest(tag=tag, field=key, byte=byte), self.assertRaises(ValueError):
                        checker.check_background_start(args[0], args[1], rows, transport)
        for key in ('full_state_fnv', 'cache_fnv', 'readback_fnv', 'instance', 'config_generation',
                    'frame_generation', 'rendered', 'consumed', 'jpeg_encoded', 'video_encoded', 'result_bytes_read'):
            rows = copy.deepcopy(args[2])
            fields = next(r['fields'] for r in rows if r['tag'] == 'FUNCTIONAL_BACKGROUND_START_READBACK')
            fields[key] = '0' * 16 if key.endswith('_fnv') else str(int(fields[key]) + 1)
            with self.subTest(field=key), self.assertRaises(ValueError):
                checker.check_background_start(args[0], args[1], rows, transport)
        for index in (0, 1):
            for key in ('model_instance', 'first', 'last'):
                changed = copy.deepcopy(transport)
                changed['transfers'][index][key] += 1
                with self.subTest(transfer=index, field=key), self.assertRaises(ValueError):
                    checker.check_background_start(args[0], args[1], args[2], changed)

    def test_background_policy_is_typed_and_old_no_background_logs_are_unaffected(self):
        args, transport = self.transport()
        self.assertFalse(transport['background_start']['required'])
        self.assertFalse(transport['background_start']['verified'])
        for key, value in checker.BACKGROUND_POLICY.items():
            manifest = dict(functional_camera_runtime=args[1]['functional_camera_runtime'],
                            backup_transport={'functional_camera_' + k: v for k, v in checker.BACKGROUND_POLICY.items()},
                            **{'functional_camera_' + k: v for k, v in checker.BACKGROUND_POLICY.items()})
            manifest['functional_camera_' + key] = 0 if value is False else None
            with self.subTest(policy=key), self.assertRaises(ValueError):
                checker.check_background_start(args[0], manifest, [dict(tag='FUNCTIONAL_BACKGROUND_START_SOURCE_BOUND',
                    line=1, fields={})])

    def test_Xsync_full_oracle_exact_source_clock_AP_domain_and_schema(self):
        pins = checker.json_file(checker.NATIVE / 'report/functional-camera-control', 'source-pins.json')
        table = bytes.fromhex(''.join(pins['ap']['table']['raw_rows_hex']))
        self.assertEqual(checker.sha(table), 'a387e2fc4d3fb45047f8f93d5064b575f04d74ac6998dabb6564775d98b75e90')
        tuples = {(word, half) for half, padding, word, enum in struct.iter_unpack('<HHII', table)}
        domain = sorted(word for word, half in tuples if half == 1 and 1 <= word <= 120)
        self.assertEqual(domain, checker.XSYNC_POLICY['xsync_canonical_clock_rates'])
        schema = (checker.RUNTIME / 'device-models/cp-full-state-snapshot.c').read_text()
        self.assertEqual(tuple(tuple(int(v, 16) for v in row) for row in re.findall(
            r'\{(0x[0-9a-f]+), (0x[0-9a-f]+), (0x[0-9a-f]+)\}', schema)), checker.FULL_BLOCKS)
        self.assertEqual(len(checker.FULL_BLOCKS), 76)
        for fps in (1, 13, 25, 30, 45, 60, 100):
            with self.subTest(fps=fps):
                state = control_state(fps)
                raw = checker.full_snapshot(state)
                self.assertEqual(len(raw), 1748)
                self.assertEqual(raw[0x664:0x674], struct.pack('<HHIIHH', 6, 0x20a6, 0, fps, 1, 0))
                self.assertIn((fps, 1), tuples)
                self.assertEqual(checker.check_full_snapshot(state, control_fields(state), raw,
                    b'\x01\x00' + b'\x01' * 1746), raw)
        for fps in (3, 61, 120):
            with self.subTest(rejected_fps=fps), self.assertRaisesRegex(ValueError, 'noncanonical source FPS'):
                checker.full_snapshot(control_state(fps))
        self.assertEqual(checker.full_snapshot(control_state(shutter=20000, iso=3200)), checker.full_snapshot(control_state()))

    def test_Xsync_complete_wire_padding_knownmask_and_all_source_fields_reject(self):
        state = control_state()
        raw, fields = checker.full_snapshot(state), control_fields(state)
        for key, value in fields.items():
            for wrong in ('missing', '0', str(int(value) + 1)):
                changed = dict(fields)
                if wrong == 'missing':
                    del changed[key]
                else:
                    changed[key] = wrong
                with self.subTest(key=key, wrong=wrong), self.assertRaises(ValueError):
                    checker.check_full_snapshot(state, changed, raw)
        for index in range(1748):
            changed = bytearray(raw)
            changed[index] ^= 1
            with self.subTest(wire_byte=index), self.assertRaises(ValueError):
                checker.check_full_snapshot(state, fields, bytes(changed))
        for offset, replacement in ((0x66c, bytes(8)), (0x66c, struct.pack('<IHH', 100, 1, 0)),
                (0x66c, struct.pack('<IHH', 30, 2, 0)), (0x672, b'\x01\x00')):
            changed = bytearray(raw)
            changed[offset:offset + len(replacement)] = replacement
            with self.subTest(offset=offset, replacement=replacement), self.assertRaises(ValueError):
                checker.check_full_snapshot(state, fields, bytes(changed))
        known = b'\x01\x00' + b'\x01' * 1746
        for index in (0, 1, 0x1c5, 0x2a9, 0x665, 0x673, 1747):
            changed = bytearray(known)
            changed[index] ^= 1
            with self.subTest(known_byte=index), self.assertRaises(ValueError):
                checker.check_full_snapshot(state, fields, raw, bytes(changed))
        for changed in (control_state(25), control_state(generation=8), control_state(aperture=800)):
            with self.subTest(source=changed.hex()), self.assertRaises(ValueError):
                checker.check_full_snapshot(changed, fields, raw)

    def test_Xsync_actual_transport_source_publication_and_ACK_only_cached_capability(self):
        args = host_test_control(self.root)
        transport = checker.check_transport(*args)
        control = transport['control']
        self.assertTrue(control['verified'])
        self.assertEqual([(p['source_generation'], p['source_fps']) for p in control['publications']], [(7, 30), (8, 25)])
        self.assertFalse(control['capture_verified'])
        self.assertFalse(control['physical_asic_compatibility_verified'])
        for tag, criteria, key, wrong in (
                ('PROBE', {'probe_run_id': '3'}, 'xsync_source_fps', '25'),
                ('PROBE', {'probe_run_id': '4'}, 'xsync_source_generation', '8'),
                ('SENT', {'published_generation': '8'}, 'xsync_source_generation', '7'),
                ('SENT', {'published_generation': '8'}, 'xsync_source_fps', '30'),
                ('SENT', {'published_generation': '8'}, 'projected_blocks', '2'),
                ('SENT', {'published_generation': '8'}, 'zero_policy_blocks', '73'),
                ('SENT', {'published_generation': '8'}, 'wire_fnv1a', '0000000000000000'),
                ('RECEIVE', {'lease_cycle': '3'}, 'wire_fnv1a', '0000000000000000'),
                ('RECEIVE', {'lease_cycle': '3'}, 'actual_source', '0x90030002'),
                ('RECEIVE', {'lease_cycle': '3'}, 'result', '0'),
                ('SENT', {'published_generation': '8'}, 'model_instance', '100'),
                ('SENT', {'published_generation': '8'}, 'ack_only', '1')):
            rows = copy.deepcopy(args[2])
            field = next(r['fields'] for r in rows if r['tag'] == 'FUNCTIONAL_CAMERA_CONTROL_' + tag and
                         all(r['fields'].get(k) == v for k, v in criteria.items()))
            field[key] = wrong
            with self.subTest(tag=tag, criteria=criteria, key=key), self.assertRaises(ValueError):
                checker.check_control(args[0], rows, transport)
        for key in checker.XSYNC_FIELDS:
            rows = copy.deepcopy(args[2])
            del next(r['fields'] for r in rows if r['tag'] == 'FUNCTIONAL_CAMERA_CONTROL_SENT')[key]
            with self.subTest(missing_source=key), self.assertRaises(ValueError):
                checker.check_control(args[0], rows, transport)
        old = bytearray(checker.full_snapshot(control_state()))
        old[0x66c:0x674] = bytes(8)
        self.assertEqual(checker.sha(old), '1116c69d00ce3ee55f85758d70d368ae43d726161fed323b78363f4988b35484')
        self.assertEqual(f'{checker.fnv(old):016x}', '1fae3c8aaffaf2d0')
        rows = copy.deepcopy(args[2])
        for row in rows:
            if row['tag'] == 'FUNCTIONAL_CAMERA_CONTROL_SENT' and row['fields']['published_generation'] == '7':
                row['fields']['wire_fnv1a'] = f'{checker.fnv(old):016x}'
        with self.assertRaisesRegex(ValueError, 'full1748 FNV'):
            checker.check_control(args[0], rows, transport)
        for kwargs in ({}, {'require_media': True}):
            with self.subTest(default_media=kwargs), self.assertRaises(checker.MissingEvidence):
                checker.check_frames(args[0], transport, **kwargs)

    def test_Xsync_actual_bad_FPS_and_same_generation_State_cannot_borrow_cached_source(self):
        for index, source in ((3, control_state(3, 8)), (3, control_state(61, 8)), (3, control_state(120, 8)),
                (3, control_state(30, 8)), (3, control_state(25, 9)), (2, control_state(25, 7)),
                (2, control_state(30, 7, shutter=20000))):
            with self.subTest(probe=index, source=source.hex()):
                root = self.root / str(len(list(self.root.iterdir())))
                root.mkdir()
                args = host_test_control(root, {index: source})
                with self.assertRaises(ValueError):
                    checker.check_transport(*args)

    def test_Xsync_profile_requires_exact_declared_clock_and_seven_false_claims(self):
        profile = checker.source_module(checker.RUNTIME / 'backup_profile.py').functional_camera_profile_fields(checker.PROFILE)
        manifest = dict(profile, backup_transport=dict(profile), directory_sd_profile='directory-vvfat-256gb-v1',
                        rm_file_image_bytes=checker.writeback.CARD_BYTES)
        self.assertTrue(checker.check_profile(manifest)['verified'])
        policies = dict(checker.XSYNC_POLICY, **{key: value for policy in (checker.BB_POLICY, checker.HIST_POLICY)
                         for key, value in policy.items() if key.endswith('verified')})
        for key, value in policies.items():
            self.assertTrue(checker.typed_equal(profile['functional_camera_' + key], value))
            for section in ('top', 'backup'):
                for wrong in ('missing', None, 0 if type(value) is bool else False, True if value is False else 'exposure'):
                    changed = copy.deepcopy(manifest)
                    target = changed if section == 'top' else changed['backup_transport']
                    if wrong == 'missing':
                        del target['functional_camera_' + key]
                    else:
                        target['functional_camera_' + key] = wrong
                    with self.subTest(key=key, section=section, wrong=wrong), self.assertRaises(ValueError):
                        checker.check_profile(changed)
        for rates in ([3] + checker.XSYNC_POLICY['xsync_canonical_clock_rates'], [30],
                      [float(v) for v in checker.XSYNC_POLICY['xsync_canonical_clock_rates']]):
            changed = copy.deepcopy(manifest)
            for target in (changed, changed['backup_transport']):
                target['functional_camera_xsync_canonical_clock_rates'] = rates
            with self.subTest(rates=rates), self.assertRaises(ValueError):
                checker.check_profile(changed)
        for key in ('original_BB_C_configuration_work_verified', 'original_BB_C_configuration_units_verified',
                    'original_Histogram_bin_semantics_verified', 'original_Histogram_physical_callback_verified',
                    'histogram_UI_applied_verified', 'original_Xsync_state_producer_verified', 'physical_Xsync_capability_verified'):
            changed = copy.deepcopy(manifest)
            for target in (changed, changed['backup_transport']):
                for policy_key in (*checker.BB_POLICY, *checker.HIST_POLICY, *checker.XSYNC_POLICY):
                    if policy_key != key:
                        target.pop('functional_camera_' + policy_key, None)
                target['functional_camera_' + key] = True
            with self.subTest(isolated_claim=key), self.assertRaises(ValueError):
                checker.check_profile(changed)

    def test_BB_neutral_five_banks_and_histogram_source_profile_contract(self):
        profile = checker.source_module(checker.RUNTIME / 'backup_profile.py').functional_camera_profile_fields(checker.PROFILE)
        manifest = dict(profile, backup_transport=dict(profile), directory_sd_profile='directory-vvfat-256gb-v1',
                        rm_file_image_bytes=checker.writeback.CARD_BYTES)
        self.assertTrue(checker.check_profile(manifest)['verified'])
        for policy in (checker.BB_POLICY, checker.HIST_POLICY):
            for key, value in policy.items():
                with self.subTest(key=key):
                    self.assertTrue(checker.typed_equal(profile['functional_camera_' + key], value))
                for section in ('top', 'backup'):
                    changed = copy.deepcopy(manifest)
                    target = changed if section == 'top' else changed['backup_transport']
                    del target['functional_camera_' + key]
                    with self.subTest(missing_policy=key, section=section), self.assertRaises(ValueError):
                        checker.check_profile(changed)
                    target['functional_camera_' + key] = int(value) if type(value) is bool else None
                    with self.subTest(typed_policy=key, section=section), self.assertRaises(ValueError):
                        checker.check_profile(changed)
        header = (checker.RUNTIME / 'functional-bb-startup-abi.h').read_text()
        for definition in ('FCAM_BB_INPUT_BYTES 32u', 'FCAM_BB_RESULT_BYTES 192u', 'FCAM_BB_CLASS 5u',
                           'FCAM_BB_PROOF_KIND 5u', 'FCAM_HIST_INPUT_BYTES 8u', 'FCAM_HIST_RESULT_BYTES 1192u',
                           'FCAM_HIST_R_BINS 168u', 'FCAM_HIST_CLASS 6u', 'FCAM_HIST_PROOF_KIND 6u'):
            self.assertIn('#define ' + definition, header)
        for inline in (False, True):
            root = self.root / str(inline)
            root.mkdir()
            args = host_test_capture(root, (True,) + BB_PATHS, vdf_inline=inline, configuration_only=True)
            transport = checker.check_transport(*args)
            cycles = transport['VDF_path']['cycles']
            self.assertEqual([c['native_command'] for c in cycles], [0x138] + list(checker.BB_COMMANDS))
            frames = checker.check_frames(args[0], transport, require_codecs=False)
            self.assertEqual([j['proof']['consumer_kind'] for j in frames['jobs']], [0, 4] + [5] * 5)
            for tx, requested in zip([tx for tx in transport['transfers'] if tx['opcode'] == 9], BB_PATHS):
                output = checker.transfer_output(args[0], tx)
                self.assertEqual(len(output), 192)
                self.assertEqual(output[160:], checker.payload_read(args[0], tx['request_payload']))
                self.assertEqual(struct.unpack_from('<I', output, 96)[0], 5)
                self.assertEqual(tx['frame']['proof']['result_bytes'], 192)
                sent = next(row['fields'] for row in args[2] if row['tag'] == 'FUNCTIONAL_VDF_PATH_SEND' and
                            checker.number(row['fields']['command']) == requested[1])
                self.assertEqual(bytes.fromhex(sent['ack_wire'])[8:], bytes(4))
                self.assertEqual(sent['allocation_returned'], '0x500000')
                self.assertEqual(sent['ack_retained'], '(nil)' if inline else '0x500000')
            with self.assertRaises(checker.MissingEvidence):
                checker.check_frames(args[0], transport)
            self.assertFalse(transport['histogram']['required'])

    def test_BB_all_opaque_domain_and_disabled_scheduler_periods(self):
        paths = (True,) + BB_PATHS + (('bb', 0x167, b'\x01\x00'),) + tuple(
            ('bb', 0x128, b'\x00\x01\x00\x00' + struct.pack('<I', period) + bytes(4))
            for period in (50, 40, 30, 20, 10, 9, 8, 7, 6, 5, 4, 3, 2, 1))
        args = host_test_capture(self.root, paths, configuration_only=True)
        transport = checker.check_transport(*args)
        self.assertEqual(len(transport['VDF_path']['cycles']), len(paths))
        self.assertTrue(checker.check_frames(args[0], transport, require_codecs=False)['verified'])
        self.assertFalse(transport['VDF_path']['original_BB_C_configuration_work_verified'])
        for _, command, body in BB_PATHS:
            canonical = struct.pack('<2H', command, len(body)) + body + bytes(28 - len(body))
            for offset in range(32):
                changed = bytearray(canonical)
                changed[offset] ^= 0x80
                with self.subTest(command=hex(command), offset=offset), self.assertRaises(ValueError):
                    checker.bb_config(changed)

    def test_BB0166_policy_exception_is_exact_typed_and_off_has_no_claim(self):
        producer = checker.source_module(checker.RUNTIME / 'backup_profile.py')
        profile = producer.functional_camera_profile_fields(checker.PROFILE)
        off = producer.functional_camera_profile_fields('')
        manifest = dict(profile, backup_transport=dict(profile), directory_sd_profile='directory-vvfat-256gb-v1',
                        rm_file_image_bytes=checker.writeback.CARD_BYTES)
        body_key = 'bb_startup_0166_observed_initial_body_hex'
        claims = ('original_BB_C_configuration_work_verified', 'original_BB_C_configuration_units_verified',
                  'physical_ASIC_compatibility_verified')
        for key in checker.BB_POLICY:
            self.assertIs(off['functional_camera_' + key], False if key in claims else None)
        bad_values = {body_key: [None, '', '00' * 28, profile['functional_camera_' + body_key] + '7f000000',
                                bytes.fromhex(profile['functional_camera_' + body_key])],
                      'bb_startup_0166_identity_policy': ['Sony-CreativeLook', 'all-look-modes-RGB-identity', True],
                      'bb_startup_neutral_only': [True, 0, None],
                      'bb_startup_other_commands_neutral_only': [False, 1, None]}
        bad_values.update({key: [True, 0, None] for key in claims})
        for section in ('top', 'backup'):
            for key, values in bad_values.items():
                for value in values:
                    changed = copy.deepcopy(manifest)
                    target = changed if section == 'top' else changed['backup_transport']
                    target['functional_camera_' + key] = value
                    with self.subTest(section=section, key=key, value=value), self.assertRaises(ValueError):
                        checker.check_profile(changed)

    def test_BB0166_observed_initial_complete_receipt_identity_and_lifecycle(self):
        body = bytes.fromhex('00010000000000000000000008000000070000000100000001000000')
        canonical = struct.pack('<2H', 0x166, 28) + body
        self.assertEqual(checker.BB_POLICY['bb_startup_0166_observed_initial_body_hex'], body.hex())
        self.assertEqual(checker.bb_config(canonical), 0x166)
        for offset in range(28):
            for value in range(256):
                if value == body[offset]:
                    continue
                changed = bytearray(canonical)
                changed[offset + 4] = value
                with self.assertRaises(ValueError):
                    checker.bb_config(changed)
        for inline in (False, True):
            root = self.root / str(inline)
            root.mkdir()
            paths = (True,) + BB_PATHS + (('bb', 0x166, body),)
            args = host_test_capture(root, paths, vdf_inline=inline, configuration_only=True)
            transport = checker.check_transport(*args)
            frames = checker.check_frames(args[0], transport, require_codecs=False)
            tx = [tx for tx in transport['transfers'] if tx['opcode'] == 9][-1]
            output = checker.transfer_output(args[0], tx)
            value = checker.vdf_result(output, canonical, 99, 9, output[128:144])
            self.assertEqual((len(output), output[160:], value['class'], value['input_fnv']),
                             (192, canonical, 5, checker.fnv(canonical)))
            self.assertEqual(value['source_fnv'], value['sink_fnv'])
            self.assertEqual((value['active_bytes'], value['frame_consumed'], value['retired']), (921600, 1, 1))
            self.assertEqual(frames['jobs'][-1]['proof']['result_fnv1a64'], checker.fnv(output))
            self.assertEqual(frames['jobs'][-1]['proof']['frame_generation'], value['frame_generation'])
            cycle = transport['VDF_path']['cycles'][-1]
            self.assertTrue(cycle['AP_consumed'])
            records = [row for row in args[2] if row['tag'].startswith('FUNCTIONAL_VDF_PATH_') and
                       row['fields'].get('cycle') == str(len(paths))]
            self.assertEqual(len(records), 5)
            for row in records:
                self.assertEqual(row['fields']['ack_wire'], '0d2066110c00018000000000')
                self.assertEqual(row['fields']['raw'], '0d20660124000180' + body.hex())
            for key, wrong in (('canonical_bb32', '00' * 32), ('model_result_bytes', '160'),
                               ('source', '0x81ce61c6'), ('source', '0x181cf61c6')):
                rows = copy.deepcopy(args[2])
                next(row['fields'] for row in rows if row['tag'] == 'FUNCTIONAL_VDF_PATH_AP_FREE' and
                     row['fields'].get('cycle') == str(len(paths)))[key] = wrong
                with self.subTest(inline=inline, field=key, wrong=wrong), self.assertRaises(ValueError):
                    checker.check_vdf_path(args[0], rows, transport)
            for source in (0, 0x81ce61c6, 0x80946189, 0x181cf61c6, 0x10000000081cf61c6,
                           (1 << 64) - 1, 1 << 64, '0x81cf61c6', None):
                changed = copy.deepcopy(transport)
                [tx for tx in changed['transfers'] if tx['opcode'] == 9][-1]['origin']['source'] = source
                with self.subTest(inline=inline, source=source), self.assertRaises(ValueError):
                    checker.check_vdf_path(args[0], args[2], changed)

    def test_BB_wrong_class_kind_ack_allocation_result_and_noncodec_proof_reject(self):
        args = host_test_capture(self.root, (True,) + BB_PATHS, configuration_only=True)
        transport = checker.check_transport(*args)
        for command in checker.BB_COMMANDS:
            for tag, key, wrong in (('REQUEST_FREE', 'ack_retained', '0x500000'),
                    ('REQUEST_FREE', 'allocation_returned', '0x500000'), ('SEND', 'allocation_returned', '(nil)'),
                    ('SEND', 'allocation_alias', '1'), ('SEND', 'source', '0x80946189'),
                    ('SEND', 'canonical_bb32', '00' * 32), ('SEND', 'model_result_bytes', '160'),
                    ('SEND', 'ack_wire', struct.pack('<4HI', 0x200d, command + 0x1000, 12, 0x8001, 0x590000).hex()),
                    ('RECEIVE', 'ack_retained', '(nil)'), ('AP_FREE', 'free_tid', '92')):
                rows = copy.deepcopy(args[2])
                next(row['fields'] for row in rows if row['tag'] == 'FUNCTIONAL_VDF_PATH_' + tag and
                     checker.number(row['fields']['command']) == command)[key] = wrong
                with self.subTest(command=hex(command), tag=tag, key=key), self.assertRaises(ValueError):
                    checker.check_vdf_path(args[0], rows, transport)
        for key, wrong in (('consumer_kind', 4), ('consumer_kind', 6), ('consumer_kind', 7), ('opcode', 8),
                ('result_bytes', 0), ('result_fnv1a64', checker.fnv(b'')), ('result_token', 1),
                ('encoded_bytes', 192), ('encoder_consumed', 1), ('render_observed', 0),
                ('consumer_entered', 0), ('consumer_returned', 0), ('retired', 0),
                ('source_fnv1a64', 0), ('consumer_before_fnv1a64', 0), ('consumer_after_fnv1a64', 0),
                ('lease_generation', 0), ('model_instance', 100), ('owner_pid', 178)):
            changed = copy.deepcopy(transport)
            next(tx['frame']['proof'] for tx in changed['transfers'] if tx['opcode'] == 9)[key] = wrong
            with self.subTest(proof=key, wrong=wrong), self.assertRaises(ValueError):
                checker.check_vdf_path(args[0], args[2], changed)
        for opcode, policies in ((9, checker.BB_POLICY),):
            for key, value in policies.items():
                for section in ('top', 'backup'):
                    manifest = copy.deepcopy(args[1])
                    (manifest if section == 'top' else manifest['backup_transport'])['functional_camera_' + key] = (
                        int(value) if type(value) is bool else None)
                    with self.subTest(opcode=opcode, policy=key, section=section), self.assertRaises(ValueError):
                        checker.check_transport(args[0], manifest, *args[2:])

    def test_Histogram_first_frame_actual1192_and_full1034_async_inline_future_free(self):
        for inline in (False, True):
            root = self.root / str(inline)
            root.mkdir()
            args = host_test_capture(root, (True,) + BB_PATHS, vdf_inline=inline,
                                     configuration_only=True, histogram=True)
            transport = checker.check_transport(*args)
            hist = transport['histogram']
            self.assertTrue(hist['first_frame_verified'])
            self.assertTrue(hist['readback_verified'])
            self.assertTrue(hist['native_ACK_and_notification_AP_free'])
            self.assertTrue(hist['AP_consumed'])
            self.assertEqual((hist['ACK_receiver_tid'], hist['ACK_free_tid']), (92, 90))
            self.assertEqual((hist['notification_receiver_tid'], hist['notification_free_tid']), (93, 93))
            for key in ('UI_applied', 'continuous_histogram', 'capture_verified',
                        'physical_asic_compatibility_verified', 'original_Histogram_bin_semantics_verified'):
                self.assertIs(hist[key], False)
            output = bytes.fromhex(hist['result1192_hex'])
            notification = bytes.fromhex(hist['notification1034_hex'])
            self.assertEqual((len(output), len(notification)), (1192, 1034))
            self.assertEqual(output[160:168], checker.HIST_CANONICAL)
            self.assertEqual(notification[:10], bytes.fromhex('0d200c210a0401800100'))
            self.assertEqual(notification[10:], output[168:])
            self.assertEqual(hist['bins_fnv1a64'], f'{checker.fnv(output[168:]):016x}')
            self.assertEqual(len(hist['channel_fnv1a64']), 4)
            frames = checker.check_frames(args[0], transport, require_codecs=False)
            self.assertEqual(frames['jobs'][-1]['proof']['consumer_kind'], 6)
            self.assertIn('configuration_result_sha256', frames['jobs'][-1])
            self.assertNotIn('encoded_result_sha256', frames['jobs'][-1])
            self.assertEqual(frames['last_counts']['jpeg_encoded'], 0)
            self.assertEqual(frames['last_counts']['video_encoded'], 0)
            with self.assertRaises(checker.MissingEvidence):
                checker.check_frames(args[0], transport)

    def test_Histogram_capture_ID_join_and_concurrent_other_role_progress(self):
        for inline in (False, True):
            root = self.root / str(inline)
            root.mkdir()
            args = host_test_capture(root, (True,), configuration_only=True, histogram=True, vdf_inline=inline)
            transport = checker.check_transport(*args)
            rows = copy.deepcopy(args[2])
            events = {int(r['fields']['snapshot_id']): r for r in rows if r['tag'].startswith('FUNCTIONAL_HISTOGRAM_') and
                      r['tag'] not in ('FUNCTIONAL_HISTOGRAM_QUEUE_BOUND', 'FUNCTIONAL_HISTOGRAM_LEASE')}

            def role_lease(snapshot_id, role):
                return next(r['fields'] for r in rows if r['tag'] == 'FUNCTIONAL_HISTOGRAM_LEASE' and
                            r['fields']['snapshot_id'] == str(snapshot_id) and r['fields']['role'] == str(role))

            if inline:
                # Notification send already returned; its sender has not captured SEND yet.
                for snapshot_id in (5, 6):
                    lease = role_lease(snapshot_id, 3)
                    lease.update(queued='1', send_inflight='0', consumed=lease['freed'])
                    events[snapshot_id]['fields']['notification_AP_consumed'] = lease['freed']
            else:
                # Both receivers updated state before the ACK receiver captured its record.
                role_lease(5, 3).update(received='1', receiver_tid='93')
            self.assertTrue(checker.check_histogram(args[0], rows, transport)['verified'])
            lifecycle = [r for r in rows if r['tag'].startswith('FUNCTIONAL_HISTOGRAM_') and
                         r['tag'] != 'FUNCTIONAL_HISTOGRAM_QUEUE_BOUND']
            groups = [[r for r in lifecycle if r['fields']['snapshot_id'] == str(i)] for i in range(1, 9)]
            # Main rows may also arrive out of capture order; each producer's own four rows stay ordered.
            interleaved = [r for column in zip(*groups[::-1]) for r in column]
            combined = [r for r in rows if r not in lifecycle] + interleaved
            for line, row in enumerate(combined, 1):
                row['line'] = line
            self.assertTrue(checker.check_histogram(args[0], combined, transport)['verified'])
            if not inline:
                early_free = role_lease(5, 3)
                early_free.update(pointer='(nil)', retained='0', free_attempted='1', freed='1',
                                  free_tid='93', consumed='1')
                events[5]['fields']['notification_AP_consumed'] = '1'
                with self.assertRaisesRegex(ValueError, 'flags contradict'):
                    checker.check_histogram(args[0], combined, transport)

    def test_Histogram_snapshot_ID_role_and_pid_are_not_optional_or_reusable(self):
        args = host_test_capture(self.root, (True,), configuration_only=True, histogram=True)
        transport = checker.check_transport(*args)
        for tag, key, wrong in (
                ('SEND', 'snapshot_id', '18446744073709551616'), ('SEND', 'snapshot_id', '01'),
                ('SEND', 'snapshot_id', '0x2'), ('SEND', 'snapshot_id', '0'),
                ('SEND', 'event_role', '0'), ('REQUEST_FREE', 'event_role', '2'),
                ('COMPLETE', 'event_role', '1'), ('RECEIVE', 'pid', '78'),
                ('LEASE', 'snapshot_id', '9'), ('LEASE', 'pid', '78'), ('LEASE', 'cycle', '2'),
                ('LEASE', 'role', '4')):
            rows = copy.deepcopy(args[2])
            next(r['fields'] for r in rows if r['tag'] == 'FUNCTIONAL_HISTOGRAM_' + tag)[key] = wrong
            with self.subTest(tag=tag, key=key, wrong=wrong), self.assertRaises(ValueError):
                checker.check_histogram(args[0], rows, transport)
        for tag in ('SEND', 'LEASE'):
            rows = copy.deepcopy(args[2])
            duplicate = copy.deepcopy(next(r for r in rows if r['tag'] == 'FUNCTIONAL_HISTOGRAM_' + tag))
            rows.append(duplicate)
            with self.subTest(duplicate=tag), self.assertRaises(ValueError):
                checker.check_histogram(args[0], rows, transport)
        rows = copy.deepcopy(args[2])
        for row in rows:
            if row['tag'].startswith('FUNCTIONAL_HISTOGRAM_'):
                row['fields'].pop('snapshot_id', None)
                row['fields'].pop('event_role', None)
        with self.assertRaises(ValueError):
            checker.check_histogram(args[0], rows, transport)

    def test_Histogram_actual_producer_grammar_not_fabricated_raw_fields(self):
        args = host_test_capture(self.root, (True,), configuration_only=True, histogram=True)
        c = (checker.RUNTIME / 'device-models/functional-histogram.c').read_text()
        log_source = c[c.index('static void record('):c.index('static int wire_valid(')]
        formats = re.findall(r'snprintf\(text,sizeof text,\s*((?:"[^"\n]*"\s*)+)', log_source)
        self.assertEqual(len(formats), 2)
        for fmt, tag in zip(formats, ('FUNCTIONAL_HISTOGRAM_REQUEST_FREE', 'FUNCTIONAL_HISTOGRAM_LEASE')):
            expected = set(re.findall(r'\b([A-Za-z_][A-Za-z_0-9]*)=', fmt))
            actual = next(row['fields'] for row in args[2] if row['tag'] == tag)
            self.assertEqual(set(actual), expected)
        self.assertTrue(checker.check_transport(*args)['histogram']['verified'])

    def test_Histogram_unknown_diagnostic_missing_snapshot_or_unfreed_reply_reject(self):
        args = host_test_capture(self.root, (True,), configuration_only=True, histogram=True)
        transport = checker.check_transport(*args)
        rows = args[2]
        for tag in ('FAIL', 'FAULT', 'REFUSED', 'UNKNOWN', 'RESOURCE_READY'):
            bad = rows + [dict(tag='FUNCTIONAL_HISTOGRAM_' + tag, line=1000, fields={})]
            with self.subTest(tag=tag), self.assertRaises(ValueError):
                checker.check_histogram(args[0], bad, transport)
        for name in ('REQUEST_FREE', 'SEND', 'COMPLETE', 'RECEIVE', 'AP_FREE'):
            bad = copy.deepcopy(rows)
            index = next(i for i, row in enumerate(bad) if row['tag'] == 'FUNCTIONAL_HISTOGRAM_' + name)
            del bad[index:index + 4]
            with self.subTest(missing=name), self.assertRaises(ValueError):
                checker.check_histogram(args[0], bad, transport)
        for role in ('2', '3'):
            for key, wrong in (('cycle', '2'), ('pointer', '(nil)'), ('allocation_returned', '(nil)'),
                    ('allocation_alias', '1'), ('send_started', '0'), ('send_rc', '1'), ('source', '0x80946180'),
                    ('destination', '0x92840747'), ('sender_tid', '91'), ('wire_fnv1a64', '0000000000000000')):
                bad = copy.deepcopy(rows)
                pos = next(i for i, row in enumerate(bad) if row['tag'] == 'FUNCTIONAL_HISTOGRAM_RECEIVE' and
                           bad[i + int(role)]['fields']['received'] == '1')
                bad[pos + int(role)]['fields'][key] = wrong
                with self.subTest(role=role, field=key), self.assertRaises(ValueError):
                    checker.check_histogram(args[0], bad, transport)
        for role, wrong_tid in (('2', '92'), ('3', '90')):
            bad = copy.deepcopy(rows)
            for row in bad:
                if row['tag'] == 'FUNCTIONAL_HISTOGRAM_LEASE' and row['fields']['role'] == role and row['fields']['freed'] == '1':
                    row['fields']['free_tid'] = wrong_tid
            with self.subTest(foreign_free_role=role), self.assertRaises(ValueError):
                checker.check_histogram(args[0], bad, transport)

    def test_Histogram_full_binding_fields_raw_channels_scope_and_extra_fields_reject(self):
        args = host_test_capture(self.root, (True,), configuration_only=True, histogram=True)
        transport = checker.check_transport(*args)
        for tag in ('FUNCTIONAL_HISTOGRAM_QUEUE_BOUND', 'FUNCTIONAL_HISTOGRAM_REQUEST_FREE', 'FUNCTIONAL_HISTOGRAM_LEASE'):
            original = next(row for row in args[2] if row['tag'] == tag)
            for key in tuple(original['fields']) + ('extra',):
                rows = copy.deepcopy(args[2])
                target = next(row for row in rows if row['tag'] == tag)
                if key == 'extra':
                    target['fields']['unknown'] = '0'
                else:
                    del target['fields'][key]
                with self.subTest(tag=tag, missing=key), self.assertRaises(ValueError):
                    checker.check_histogram(args[0], rows, transport)
        for tag, key, wrong in (
                ('QUEUE_BOUND', 'caller_pc', hex(0x7f25c3f000 + 0x34e4f3c)),
                ('QUEUE_BOUND', 'global_va', '0x910fa30'), ('QUEUE_BOUND', 'read_before', '3'),
                ('QUEUE_BOUND', 'second', '0x80946181'), ('QUEUE_BOUND', 'bind_rc', '1'),
                ('QUEUE_BOUND', 'source', '0x92840747'), ('QUEUE_BOUND', 'source_match', '0'),
                ('QUEUE_BOUND', 'tid', '92'), ('QUEUE_BOUND', 'capture_verified', '1'),
                ('SEND', 'raw', '0d2048010c00018000010000'), ('SEND', 'canonical8', '4801040001000000'),
                ('SEND', 'model_result_bytes', '1191'), ('SEND', 'notification_bytes', '2048'),
                ('SEND', 'selector', '0'), ('SEND', 'original_request', '(nil)'),
                ('SEND', 'original_request', '0x400001'), ('SEND', 'Y_fnv1a64', '0000000000000000'),
                ('SEND', 'R_fnv1a64', '0000000000000000'), ('SEND', 'G_fnv1a64', '0000000000000000'),
                ('SEND', 'B_fnv1a64', '0000000000000000'), ('SEND', 'model_result_fnv1a64', '0000000000000000'),
                ('SEND', 'notification_fnv1a64', '0000000000000000'), ('SEND', 'queue_bound', '0'),
                ('SEND', 'UI_applied', '1'), ('SEND', 'capture_verified', '1'), ('SEND', 'continuous_histogram', '1')):
            rows = copy.deepcopy(args[2])
            next(row['fields'] for row in rows if row['tag'] == 'FUNCTIONAL_HISTOGRAM_' + tag)[key] = wrong
            with self.subTest(tag=tag, field=key), self.assertRaises(ValueError):
                checker.check_histogram(args[0], rows, transport)

    def test_Histogram_core_result_geometry_canonical_class_and_proof_are_mandatory(self):
        args = host_test_capture(self.root, (True,), configuration_only=True, histogram=True)
        transport = checker.check_transport(*args)
        tx = next(tx for tx in transport['transfers'] if tx['opcode'] == 10)
        raw = checker.transfer_output(args[0], tx)
        for offset in (0, 4, 8, 16, 24, 32, 40, 48, 56, 64, 72, 76, 80, 84, 88, 92, 96,
                       100, 104, 108, 112, 116, 120, 124, 128, 144, 152, 160, 167, 168 + 29):
            output = bytearray(raw)
            output[offset] ^= 1
            if offset == 32:
                struct.pack_into('<Q', output, 32, 0)
            with self.subTest(result_offset=offset), self.assertRaises(ValueError):
                checker.vdf_result(output, checker.HIST_CANONICAL, 99, 10, raw[128:144])
        for key, wrong in (('consumer_kind', 4), ('consumer_kind', 5), ('consumer_kind', 7),
                ('result_bytes', 0), ('result_fnv1a64', checker.fnv(b'')), ('result_token', 1),
                ('encoded_bytes', 1192), ('encoder_consumed', 1), ('retired', 0), ('consumer_returned', 0),
                ('consumer_before_fnv1a64', 0), ('consumer_after_fnv1a64', 0), ('config_generation', 1),
                ('lease_generation', 0), ('serial', 1), ('model_lifetime', 2)):
            changed = copy.deepcopy(transport)
            next(item['frame']['proof'] for item in changed['transfers'] if item['opcode'] == 10)[key] = wrong
            with self.subTest(proof=key), self.assertRaises(ValueError):
                checker.check_histogram(args[0], args[2], changed)
        for key, value in checker.HIST_POLICY.items():
            for section in ('top', 'backup'):
                manifest = copy.deepcopy(args[1])
                (manifest if section == 'top' else manifest['backup_transport'])['functional_camera_' + key] = (
                    int(value) if type(value) is bool else None)
                with self.subTest(policy=key, section=section), self.assertRaises(ValueError):
                    checker.check_transport(args[0], manifest, *args[2:])
        missing = copy.deepcopy(transport)
        next(item for item in missing['transfers'] if item['opcode'] == 10)['frame'] = None
        with self.assertRaises(checker.MissingEvidence):
            checker.check_histogram(args[0], args[2], missing)
        twice = copy.deepcopy(transport)
        twice['transfers'].append(copy.deepcopy(tx))
        with self.assertRaises(checker.MissingEvidence):
            checker.check_histogram(args[0], args[2], twice)

    def test_BB_Histogram_mailbox_opcodes_sizes_and_class_are_exact(self):
        args = host_test_capture(self.root, (True,) + BB_PATHS, configuration_only=True, histogram=True)
        transport = checker.check_transport(*args)
        for op in (9, 10):
            for field, wrong in (('opcode', 11), ('opcode', 16), ('request_bytes', 0),
                                  ('request_bytes', 16), ('request_bytes', 48)):
                changed = copy.deepcopy(args)
                event = next(event for event in changed[3] if event['kind'] == 'request' and event['opcode'] == op)
                header = bytearray.fromhex(event['raw_header_hex'])
                event[field] = wrong
                struct.pack_into('<I', header, 32 if field == 'opcode' else 36, wrong)
                event.update(raw_header_hex=header.hex(), raw_header_sha256=checker.sha(header))
                with self.subTest(op=op, field=field, wrong=wrong), self.assertRaises(ValueError):
                    checker.check_transport(*changed)
            tx = next(tx for tx in transport['transfers'] if tx['opcode'] == op)
            incoming = checker.payload_read(args[0], tx['request_payload'])
            raw = checker.transfer_output(args[0], tx)
            for wrong_class in (0, 1, 4, 5 if op == 10 else 6, 7):
                output = bytearray(raw)
                struct.pack_into('<I', output, 96, wrong_class)
                with self.subTest(op=op, wrong_class=wrong_class), self.assertRaises(ValueError):
                    checker.vdf_result(output, incoming, 99, op, raw[128:144])
        rows = copy.deepcopy(args[2])
        for row in rows:
            if row['tag'] == 'FUNCTIONAL_HISTOGRAM_LEASE' and row['fields']['role'] == '3':
                for key in ('pointer', 'allocation_returned'):
                    if row['fields'][key] != '(nil)':
                        row['fields'][key] = '0x500000'
        with self.assertRaisesRegex(ValueError, 'allocations alias'):
            checker.check_histogram(args[0], rows, transport)
        for command in checker.BB_COMMANDS:
            rows = copy.deepcopy(args[2])
            target = next(row['fields'] for row in rows if row['tag'] == 'FUNCTIONAL_VDF_PATH_SEND' and
                          checker.number(row['fields']['command']) == command)
            del target['allocation_returned']
            with self.subTest(command=hex(command), missing='SEND allocation'), self.assertRaises(checker.MissingEvidence):
                checker.check_vdf_path(args[0], rows, transport)

    def test_ACK_allocation_source_policy_async_and_inline(self):
        for inline in (False, True):
            root = self.root / str(inline)
            root.mkdir()
            args = host_test_capture(root, REFRESH_PATHS, vdf_inline=inline, refresh_source=0x80946189,
                                     configuration_only=True)
            transport = checker.check_transport(*args)
            self.assertEqual(len(transport['VDF_path']['cycles']), 6)
            for row in args[2]:
                if not row['tag'].startswith('FUNCTIONAL_VDF_PATH_') or 'cycle' not in row['fields']:
                    continue
                f = row['fields']
                after_free = f['command'] in ('0x14c', '0x141', '0x152', '0x162')
                if row['tag'].endswith('REQUEST_FREE'):
                    self.assertEqual(f['ack_retained'], '(nil)' if after_free else '0x500000')
                    if after_free:
                        self.assertEqual(f['allocation_returned'], '(nil)')
                elif after_free:
                    self.assertEqual(f['allocation_returned'], '0x500000')
                    if inline and row['tag'].endswith('SEND'):
                        self.assertEqual(f['ack_retained'], '(nil)')
            self.assertFalse(transport['VDF_path']['physical_asic_compatibility_verified'])

    def test_ACK_allocation_missing_live_or_persistent_address_and_early_allocation_reject(self):
        args = host_test_capture(self.root, REFRESH_PATHS, vdf_inline=True, refresh_source=0x80946189,
                                 configuration_only=True)
        transport = checker.check_transport(*args)
        for command in ('0x14c', '0x152', '0x162', '0x141'):
            for tag, key, value in (
                    ('SEND', 'allocation_returned', None), ('SEND', 'allocation_returned', '(nil)'),
                    ('SEND', 'allocation_returned', '0x400000'), ('SEND', 'allocation_alias', '1'),
                    ('RECEIVE', 'ack_retained', '(nil)'), ('RECEIVE', 'ack_retained', '0x400000'),
                    ('AP_FREE', 'ack_retained', '0x500000'), ('AP_FREE', 'allocation_returned', '(nil)'),
                    ('REQUEST_FREE', 'ack_retained', '0x500000'),
                    ('REQUEST_FREE', 'allocation_returned', '0x500000'),
                    ('REQUEST_FREE', 'allocation_returned', None)):
                changed = copy.deepcopy(args[2])
                f = next(row['fields'] for row in changed if row['tag'] == 'FUNCTIONAL_VDF_PATH_' + tag and
                         row['fields'].get('command') == command)
                if value is None:
                    del f[key]
                else:
                    f[key] = value
                with self.subTest(command=command, tag=tag, key=key, value=value), self.assertRaises(ValueError):
                    checker.check_vdf_path(args[0], changed, transport)
        for command in ('0x138', '0x153'):
            for key, wrong in (('ack_retained', '(nil)'), ('allocation_alias', '1')):
                changed = copy.deepcopy(args[2])
                next(row['fields'] for row in changed if row['tag'] == 'FUNCTIONAL_VDF_PATH_REQUEST_FREE' and
                     row['fields'].get('command') == command)[key] = wrong
                with self.subTest(command=command, key=key), self.assertRaises(ValueError):
                    checker.check_vdf_path(args[0], changed, transport)

    def test_complete_HOST_TEST_actual_positive_stages_and_evaluate(self):
        args, transport, storage = self.capture()
        run, manifest, rows, _, build = args
        self.assertTrue(checker.check_frames(run, transport)['same_frame_RGB_consumer_verified'])
        jpeg = checker.check_jpeg(rows, transport, storage, run)
        video = checker.check_video(rows, transport, storage, run)
        self.assertTrue(jpeg['storage_join_verified'])
        self.assertTrue(video['raw_encoded_NAL_join_verified'])
        self.assertEqual(video['samples'], 4)
        self.assertEqual(video['PI_published_and_returned'], 6)
        # Only public-artifact prerequisites are isolated: every capture/media stage runs.
        with mock.patch.object(checker, 'check_profile', return_value={'verified': True}), mock.patch.object(
                checker, 'check_batch', return_value=(build, {})):
            result = checker.evaluate(run, self.root / 'HOST_TEST_unfrozen_batch')
        for name in ('transport', 'CMOS_encoder', 'JPEG_causality', 'MP4_causality'):
            self.assertTrue(result['evidence'][name]['verified'], result)
        self.assertFalse(result['capture_verified'])
        self.assertFalse(result['products']['JPEG']['capture_verified'])
        self.assertFalse(result['physical_asic_compatibility_verified'])
        self.assertTrue(any(row['stage'] == 'graph' for row in result['missing']))
        self.assertTrue(any(row['stage'] == 'native_acceptance' for row in result['missing']))
        json.dumps(result)

    def test_VDF_requires_declared_software_route_policy(self):
        args = host_test_capture(self.root, (True,))
        for where in ('manifest', 'backup_transport'):
            for key in checker.VDF_POLICY:
                manifest = copy.deepcopy(args[1])
                target = manifest if where == 'manifest' else manifest[where]
                del target['functional_camera_' + key]
                with self.subTest(where=where, missing=key), self.assertRaisesRegex(ValueError, 'software endpoint/mask policy'):
                    checker.check_transport(args[0], manifest, *args[2:])
        manifest = copy.deepcopy(args[1])
        manifest['functional_camera_vdf_virtual_completion_mask'] = True
        with self.assertRaisesRegex(ValueError, 'software endpoint/mask policy'):
            checker.check_transport(args[0], manifest, *args[2:])

    def test_VDF_config_copy_disable_and_original_media_share_one_history(self):
        args = host_test_capture(self.root, (True, False, True))
        run, _, rows, _, build = args
        transport = checker.check_transport(*args)
        self.assertTrue(transport['VDF_path']['verified'])
        self.assertEqual([cycle['active'] for cycle in transport['VDF_path']['cycles']], [True, False, True])
        self.assertEqual(transport['opcodes']['5'], 3)
        self.assertEqual([cycle['config_generation'] for cycle in transport['VDF_path']['cycles']], [2, 4, 6])
        self.assertEqual(transport['transfers'][0]['origin']['command'], 0x138)
        initializations = [tx for tx in transport['transfers'] if tx['opcode'] == 1]
        self.assertEqual(len(initializations), 3)
        self.assertIsNotNone(initializations[0]['frame'])
        self.assertTrue(all(tx['frame'] is None for tx in initializations[1:]))
        repeated_state = checker.transfer_output(run, initializations[1])
        self.assertEqual(struct.unpack_from('<Q', repeated_state, 56)[0], 6)
        self.assertEqual(struct.unpack_from('<Q', repeated_state, 72)[0], 2)
        frames = checker.check_frames(run, transport)
        self.assertEqual(frames['last_counts'], dict(rendered=8, consumed=7, retired=8, jpeg_encoded=1, video_encoded=4))
        self.assertEqual([job['proof']['consumer_kind'] for job in frames['jobs'][:4]], [0, 4, 4, 4])
        for job in (job for job in frames['jobs'] if job['opcode'] == 5):
            self.assertIn('configuration_result_sha256', job)
            self.assertNotIn('encoded_result_sha256', job)
        storage = checker.writeback.inspect(run)
        self.assertTrue(storage['writeback_verified'], storage)
        self.assertTrue(storage['independent_decoded'], storage)
        self.assertTrue(checker.check_jpeg(rows, transport, storage, run)['storage_join_verified'])
        self.assertEqual(checker.check_video(rows, transport, storage, run)['samples'], 4)
        with mock.patch.object(checker, 'check_profile', return_value={'verified': True}), mock.patch.object(
                checker, 'check_batch', return_value=(build, {})):
            result = checker.evaluate(run, self.root / 'HOST_TEST_unfrozen_batch')
        self.assertTrue(result['evidence']['transport']['VDF_path']['verified'], result)
        self.assertTrue(result['evidence']['CMOS_encoder']['verified'], result)
        self.assertFalse(result['capture_verified'])

    def test_VDF_inline_receive_free_before_send_return(self):
        args = host_test_capture(self.root, (True,), vdf_inline=True)
        transport = checker.check_transport(*args)
        self.assertTrue(transport['VDF_path']['verified'])
        repeated_init = [tx for tx in transport['transfers'] if tx['opcode'] == 1][1]
        raw = checker.transfer_output(args[0], repeated_init)
        self.assertIsNone(repeated_init['frame'])
        self.assertEqual(struct.unpack_from('<Q', raw, 56)[0], 2)
        self.assertEqual(struct.unpack_from('<Q', raw, 72)[0], 1)
        self.assertTrue(checker.check_frames(args[0], transport)['verified'])

    def test_VDF160_parser_rejects_source_sink_opaque_masks_generation_and_disabled_frame(self):
        args = host_test_capture(self.root, (True, False))
        transport = checker.check_transport(*args)
        for tx in (tx for tx in transport['transfers'] if tx['opcode'] == 5):
            raw = checker.transfer_output(args[0], tx)
            canonical = checker.payload_read(args[0], tx['request_payload'])
            self.assertEqual(checker.vdf_result(raw, canonical, 99)['enabled'], canonical[0])
            # Every byte range participates: opaque config, identity, generations,
            # enabled/disabled RGB/lease, profile endpoint/masks and commit flags.
            for offset in (0, 4, 8, 16, 24, 32, 40, 48, 56, 64, 72, 76, 80, 84,
                           88, 92, 96, 100, 104, 108, 112, 116, 120, 124, 131, 140, 141, 144, 152):
                changed = bytearray(raw)
                if offset == 32 and canonical[0] or offset == 76:
                    struct.pack_into('<Q' if offset == 32 else '<I', changed, offset, 0)
                else:
                    changed[offset] ^= 1
                with self.subTest(active=canonical[0], offset=offset), self.assertRaises(ValueError):
                    checker.vdf_result(changed, canonical, 99)
            for offset in (0, 1, 2, 3, 4, 5, 12, 13, 15):
                changed = bytearray(canonical)
                changed[offset] ^= 1
                with self.subTest(config_offset=offset), self.assertRaises(ValueError):
                    checker.vdf_result(raw, changed, 99)
            for bad in (raw[:128], raw + b'\x00', bytes(160)):
                with self.subTest(size=len(bad)), self.assertRaises(ValueError):
                    checker.vdf_result(bad, canonical, 99)

    def test_VDF_original_cycle_instance_ACK_and_free_mutations_fail(self):
        args = host_test_capture(self.root, (True, False))
        transport = checker.check_transport(*args)
        mutations = (('RECEIVE', 'raw', '00' * 24), ('RECEIVE', 'ack_wire', '00' * 12),
                     ('SEND', 'canonical_config', '00' * 16), ('SEND', 'model_result_hex', '00' * 160),
                     ('SEND', 'original_fnv1a', '0000000000000000'),
                     ('SEND', 'model_result_fnv1a64', '0000000000000000'),
                     ('SEND', 'model_instance', '100'), ('SEND', 'source', '0x81cf61c5'),
                     ('SEND', 'destination', '0x92840748'), ('SEND', 'config_generation', '1'),
                     ('SEND', 'before_frame_generation', '0'), ('SEND', 'lease_generation', '0'),
                     ('RECEIVE', 'ack_retained', '0x500001'), ('RECEIVE', 'receiver_tid', '91'),
                     ('AP_FREE', 'free_tid', '91'), ('AP_FREE', 'free_rc', '-1'),
                     ('AP_FREE', 'request_freed', '0'), ('AP_FREE', 'AP_consumed', '0'),
                     ('AP_FREE', 'phase', '4'), ('AP_FREE', 'cycle', '2'),
                     ('COMPLETE', 'original_selector_verified', '1'), ('SEND', 'physical_ASIC_verified', '1'))
        for tag, key, value in mutations:
            rows = copy.deepcopy(args[2])
            next(row for row in rows if row['tag'] == 'FUNCTIONAL_VDF_PATH_' + tag)['fields'][key] = value
            with self.subTest(tag=tag, key=key), self.assertRaises(ValueError):
                checker.check_vdf_path(args[0], rows, transport)
        for name in ('RECEIVE', 'AP_FREE', 'REQUEST_FREE', 'COMPLETE', 'SEND'):
            rows = [row for row in args[2] if row['tag'] != 'FUNCTIONAL_VDF_PATH_' + name]
            with self.subTest(missing=name), self.assertRaises(checker.MissingEvidence):
                checker.check_vdf_path(args[0], rows, transport)
        rows = copy.deepcopy(args[2])
        [row for row in rows if row['tag'] == 'FUNCTIONAL_VDF_PATH_AP_FREE'][-1]['fields']['cycle'] = '1'
        with self.assertRaises(ValueError):
            checker.check_vdf_path(args[0], rows, transport)
        with self.assertRaises(checker.MissingEvidence):
            checker.check_vdf_path(args[0], [], transport)
        without_vdf = dict(transport, transfers=[tx for tx in transport['transfers'] if tx['opcode'] != 5])
        with self.assertRaises(checker.MissingEvidence):
            checker.check_vdf_path(args[0], args[2], without_vdf)

    def test_VDF_proof_cannot_count_RGB_copy_or_disable_as_encoding(self):
        args = host_test_capture(self.root, (True, False))
        transport = checker.check_transport(*args)
        for active in (True, False):
            for key, value in (('consumer_kind', 1), ('encoder_consumed', 1), ('encoded_bytes', 1),
                               ('result_bytes', 160), ('result_token', 1), ('source_fnv1a64', 1),
                               ('consumer_after_fnv1a64', 1), ('lease_generation', 0 if active else 1),
                               ('frame_generation', 0), ('config_generation', 0),
                               ('consumer_entered', 0 if active else 1)):
                changed = copy.deepcopy(transport)
                proof = [tx['frame']['proof'] for tx in changed['transfers'] if tx['opcode'] == 5][0 if active else 1]
                proof[key] = value
                with self.subTest(active=active, key=key), self.assertRaises(ValueError):
                    checker.check_frames(args[0], changed)
            for key in ('consumed', 'rendered', 'retired', 'jpeg_encoded', 'video_encoded'):
                changed = copy.deepcopy(transport)
                proof = [tx['frame']['proof'] for tx in changed['transfers'] if tx['opcode'] == 5][0 if active else 1]
                proof['after'][key] += 1
                with self.subTest(active=active, counter=key), self.assertRaises(ValueError):
                    checker.check_frames(args[0], changed)
        changed = copy.deepcopy(transport)
        next(tx for tx in changed['transfers'] if tx['opcode'] == 5)['frame'] = None
        with self.assertRaises(checker.MissingEvidence):
            checker.check_frames(args[0], changed)

    def test_VDF_consumption_preserves_all_original_media_requirements(self):
        args = host_test_capture(self.root, (True,))
        transport = checker.check_transport(*args)
        for op in (16, 33, 34):
            changed = copy.deepcopy(transport)
            changed['transfers'] = [tx for tx in changed['transfers'] if tx['opcode'] != op]
            with self.subTest(missing=op), self.assertRaises(ValueError):
                checker.check_frames(args[0], changed)
        storage = checker.writeback.inspect(args[0])
        rows = [row for row in args[2] if not (row['tag'] == 'FUNCTIONAL_JPEG_CODEC' and
                                              row['fields']['operation'] == 'original-rescmd-done')]
        with self.assertRaises(checker.MissingEvidence):
            checker.check_jpeg(rows, transport, storage, args[0])
        rows = [row for row in args[2] if row['tag'] != 'FUNCTIONAL_MPR_EVENT_FREE']
        with self.assertRaises(checker.MissingEvidence):
            checker.check_video(rows, transport, storage, args[0])

    def test_Zebra_mixed_route_CONFIGURE_repeated_INIT_and_media_history(self):
        zebra = bytes.fromhex('0300204b41000000')
        args = host_test_capture(self.root, (True, zebra, False, zebra, True))
        run, _, rows, _, build = args
        transport = checker.check_transport(*args)
        cycles = transport['VDF_path']['cycles']
        self.assertEqual([item['opcode'] for item in cycles], [5, 6, 5, 6, 5])
        self.assertEqual([item['active'] for item in cycles], [True, True, False, False, True])
        self.assertEqual([item['config_generation'] for item in cycles], [2, 4, 6, 8, 10])
        self.assertEqual([item['frame_generation'] for item in cycles], [2, 3, 3, 3, 4])
        self.assertEqual(transport['opcodes']['6'], 2)
        self.assertFalse(transport['VDF_path']['original_Zebra_gate_verified'])
        frames = checker.check_frames(run, transport)
        self.assertEqual(frames['last_counts'], dict(rendered=9, consumed=8, retired=9, jpeg_encoded=1, video_encoded=4))
        self.assertEqual(sum(job['proof']['consumer_kind'] == 0 for job in frames['jobs']), 1)
        for tx in (tx for tx in transport['transfers'] if tx['opcode'] == 6):
            raw = checker.transfer_output(run, tx)
            self.assertEqual(len(raw), 168)
            self.assertEqual(raw[160:], zebra)
            self.assertEqual(struct.unpack_from('<Q', raw, 40)[0], checker.fnv(zebra))
            self.assertEqual(tx['origin']['command'], 0x153)
            self.assertEqual(tx['origin']['source'], 0x81cf61c5)
            self.assertEqual(tx['origin']['bytes'], 14)
            job = next(job for job in frames['jobs'] if job['first'] == tx['first'])
            self.assertIn('configuration_result_sha256', job)
            self.assertNotIn('encoded_result_sha256', job)
        storage = checker.writeback.inspect(run)
        self.assertTrue(storage['writeback_verified'], storage)
        self.assertTrue(storage['independent_decoded'], storage)
        self.assertTrue(checker.check_jpeg(rows, transport, storage, run)['storage_join_verified'])
        self.assertEqual(checker.check_video(rows, transport, storage, run)['samples'], 4)
        with mock.patch.object(checker, 'check_profile', return_value={'verified': True}), mock.patch.object(
                checker, 'check_batch', return_value=(build, {})):
            result = checker.evaluate(run, self.root / 'NO_FROZEN_BATCH')
        for name in ('transport', 'CMOS_encoder', 'JPEG_causality', 'MP4_causality'):
            self.assertTrue(result['evidence'][name]['verified'], result)
        self.assertFalse(result['capture_verified'])
        self.assertTrue(any(item['stage'] == 'graph' for item in result['missing']))
        self.assertTrue(any(item['stage'] == 'native_acceptance' for item in result['missing']))
        unfrozen = checker.evaluate(run, self.root / 'NO_FROZEN_BATCH')
        self.assertFalse(unfrozen['capture_verified'])
        self.assertTrue(any(item['stage'] == 'batch' for item in unfrozen['missing']))
        self.assertTrue(all(not item['capture_verified'] for item in unfrozen['products'].values()))

    def test_Zebra_first_INIT_uses_complete_origin_among_unrelated_initializations(self):
        zebra = bytes.fromhex('0300204b41000000')
        cp = dict(producer_tid=92, source=0x81cf1234, destination=0x92880001,
                  command=0x3003, bytes=8, fnv1a64=checker.fnv(b'HOST_TEST CP INIT'))
        other = dict(producer_tid=93, source=0x802a0116, destination=0x82830752,
                     command=0x30304, bytes=104, fnv1a64=checker.fnv(b'HOST_TEST unrelated INIT'))
        for name, initial, inline in (('zebra', None, False), ('CP', cp, True), ('unrelated', other, False)):
            root = self.root / name
            root.mkdir()
            args = host_test_capture(root, (zebra,), vdf_inline=inline, initial_origin=initial)
            transport = checker.check_transport(*args)
            self.assertFalse(transport['VDF_path']['cycles'][0]['active'])
            frames = checker.check_frames(args[0], transport)
            self.assertEqual(frames['last_counts']['rendered'], 6)
            self.assertEqual(frames['last_counts']['consumed'], 5)
            self.assertEqual(sum(job['opcode'] == 1 for job in frames['jobs']), 1)
            initializations = [tx for tx in transport['transfers'] if tx['opcode'] == 1]
            self.assertTrue(all(tx['frame'] is None for tx in initializations[1:]))
            for key in ('producer_tid', 'source', 'bytes', 'fnv1a64'):
                changed = copy.deepcopy(transport)
                bound = next(tx for tx in changed['transfers'] if tx['opcode'] == 1 and tx['origin']['command'] == 0x153)
                bound['origin'][key] ^= 1
                with self.subTest(initial=name, origin_field=key), self.assertRaises(checker.MissingEvidence):
                    checker.check_vdf_path(args[0], args[2], changed)

    def test_Zebra_requires_independent_typed_policy_in_host_and_backup(self):
        args = host_test_capture(self.root, (bytes.fromhex('0300204b41000000'),))
        for location in ('manifest', 'backup_transport'):
            for key, expected in checker.ZEBRA_POLICY.items():
                full_key = 'functional_camera_' + key
                for wrong in (None, True if expected is False else False, 0 if expected is False else ''):
                    manifest = copy.deepcopy(args[1])
                    target = manifest if location == 'manifest' else manifest[location]
                    if wrong is None:
                        del target[full_key]
                    else:
                        target[full_key] = wrong
                    with self.subTest(location=location, key=key, wrong=wrong), self.assertRaisesRegex(
                            ValueError, 'disabled/pass-through software policy'):
                        checker.check_transport(args[0], manifest, *args[2:])

    def test_Zebra168_parser_binds_all_fields_tail_hash_and_current_route(self):
        zebra = bytes.fromhex('0300204b41000000')
        args = host_test_capture(self.root, (True, zebra, False, zebra))
        transport = checker.check_transport(*args)
        for tx in (tx for tx in transport['transfers'] if tx['opcode'] == 6):
            raw = checker.transfer_output(args[0], tx)
            route = raw[128:144]
            self.assertEqual(checker.vdf_result(raw, zebra, 99, 6, route)['enabled'], route[0])
            for offset in (0, 4, 8, 16, 24, 32, 40, 48, 56, 64, 72, 76, 80, 84, 88, 92,
                           96, 100, 104, 108, 112, 116, 120, 124, 131, 141, 144, 152,
                           160, 161, 162, 163, 164, 165, 166, 167):
                changed = bytearray(raw)
                if offset in (72, 76) or offset == 32 and route[0]:
                    struct.pack_into('<Q' if offset == 32 else '<I', changed, offset, 0)
                else:
                    changed[offset] ^= 1
                with self.subTest(active=route[0], offset=offset), self.assertRaises(ValueError):
                    checker.vdf_result(changed, zebra, 99, 6, route)
            for index in range(8):
                changed = bytearray(zebra)
                changed[index] ^= 1
                with self.subTest(input=index), self.assertRaises(ValueError):
                    checker.vdf_result(raw, changed, 99, 6, route)
            for bad in (raw[:128], raw[:160], raw + bytes(8), bytes(168)):
                with self.subTest(bytes=len(bad)), self.assertRaises(ValueError):
                    checker.vdf_result(bad, zebra, 99, 6, route)
            with self.assertRaises(ValueError):
                checker.vdf_result(raw, zebra, 99, 5, route)
            with self.assertRaises(ValueError):
                checker.vdf_result(raw, zebra, 99, 6, bytes(16))
            with self.assertRaises(ValueError):
                checker.vdf_result(raw, zebra, 99, 6)
            for index in (1, 5, 6, 7):
                changed, reply = bytearray(zebra), bytearray(raw)
                changed[index] = 1
                reply[160:] = changed
                struct.pack_into('<Q', reply, 40, checker.fnv(changed))
                with self.subTest(unsupported=index), self.assertRaises(ValueError):
                    checker.vdf_result(reply, changed, 99, 6, route)

    def test_Zebra_native_wrong_ACK_opcode_padding_canonical_and_stale_ticket_fail(self):
        zebra = bytes.fromhex('0300204b41000000')
        args = host_test_capture(self.root, (True, zebra, False, zebra))
        transport = checker.check_transport(*args)
        original = next(row['fields']['raw'] for row in args[2] if row['tag'] == 'FUNCTIONAL_VDF_PATH_SEND' and
                        row['fields']['command'] == '0x153')
        mutations = (('ack_wire', '0d2053110c00018000005900'), ('ack_wire', '0d2038110c00018000000000'),
                     ('ack_wire', '0d2053120c00018000000000'), ('command', '0x138'), ('bytes', '24'),
                     ('raw', original[:-2] + '00'), ('raw', original + '00' * 10),
                     ('raw', '0d203801' + original[8:]), ('canonical_zebra8', '00' * 8),
                     ('canonical_config', '00' * 16), ('model_result_bytes', '160'),
                     ('model_result_hex', '00' * 168), ('model_result_fnv1a64', '0000000000000000'),
                     ('original_fnv1a', '0000000000000000'), ('cycle', '1'), ('completed_cycles', '0'),
                     ('receiver_tid', '91'), ('free_tid', '91'), ('AP_consumed', '0'), ('free_rc', '-1'),
                     ('ack_retained', '0x500001'), ('source', '0x81cf61c4'), ('physical_ASIC_verified', '1'))
        for key, wrong in mutations:
            rows = copy.deepcopy(args[2])
            row = next(row for row in rows if row['tag'] == 'FUNCTIONAL_VDF_PATH_AP_FREE' and
                       row['fields']['command'] == '0x153')
            row['fields'][key] = wrong
            with self.subTest(field=key, wrong=wrong), self.assertRaises(ValueError):
                checker.check_vdf_path(args[0], rows, transport)
        for tag in ('REQUEST_FREE', 'SEND', 'COMPLETE', 'RECEIVE', 'AP_FREE'):
            rows = list(args[2])
            rows.remove(next(row for row in rows if row['tag'] == 'FUNCTIONAL_VDF_PATH_' + tag and
                             row['fields']['command'] == '0x153'))
            with self.subTest(missing=tag), self.assertRaises(checker.MissingEvidence):
                checker.check_vdf_path(args[0], rows, transport)
        for key in ('canonical_zebra8', 'model_result_bytes'):
            rows = copy.deepcopy(args[2])
            del next(row for row in rows if row['tag'] == 'FUNCTIONAL_VDF_PATH_SEND' and
                     row['fields']['command'] == '0x153')['fields'][key]
            with self.subTest(missing=key), self.assertRaises((ValueError, KeyError)):
                checker.check_vdf_path(args[0], rows, transport)
        changed = copy.deepcopy(transport)
        next(tx for tx in changed['transfers'] if tx['opcode'] == 6)['opcode'] = 3
        with self.assertRaises(ValueError):
            checker.check_vdf_path(args[0], args[2], changed)

    def test_Zebra_active_and_idle_proofs_cannot_invent_frames_or_encoding(self):
        zebra = bytes.fromhex('0300204b41000000')
        args = host_test_capture(self.root, (True, zebra, False, zebra))
        transport = checker.check_transport(*args)
        for index, active in enumerate((True, False)):
            for key, value in (('consumer_kind', 1), ('opcode', 5), ('encoder_consumed', 1), ('encoded_bytes', 1),
                               ('result_bytes', 168), ('result_token', 1), ('source_fnv1a64', 1),
                               ('consumer_after_fnv1a64', 1), ('lease_generation', 0 if active else 1),
                               ('frame_generation', 0), ('config_generation', 0),
                               ('render_observed', 0 if active else 1), ('consumer_entered', 0 if active else 1),
                               ('render_status', -1), ('consumer_status', -1), ('retire_status', -1),
                               ('width', 1), ('consumer_before_state', 0 if active else 4), ('operation_status', -1)):
                changed = copy.deepcopy(transport)
                p = [tx['frame']['proof'] for tx in changed['transfers'] if tx['opcode'] == 6][index]
                p[key] = value
                with self.subTest(active=active, key=key), self.assertRaises(ValueError):
                    checker.check_vdf_path(args[0], args[2], changed)
                with self.subTest(stage='frames', active=active, key=key), self.assertRaises(ValueError):
                    checker.check_frames(args[0], changed)
            for counter in ('rendered', 'consumed', 'retired', 'jpeg_encoded', 'video_encoded'):
                changed = copy.deepcopy(transport)
                p = [tx['frame']['proof'] for tx in changed['transfers'] if tx['opcode'] == 6][index]
                p['after'][counter] += 1
                with self.subTest(active=active, counter=counter), self.assertRaises(ValueError):
                    checker.check_vdf_path(args[0], args[2], changed)
            changed = copy.deepcopy(transport)
            [tx for tx in changed['transfers'] if tx['opcode'] == 6][index]['frame'] = None
            with self.assertRaises(checker.MissingEvidence):
                checker.check_vdf_path(args[0], args[2], changed)

    def test_Zebra_history_rejects_self_consistent_route_generations_and_Config48_drift(self):
        zebra = bytes.fromhex('0300204b41000000')
        args = host_test_capture(self.root, (True, zebra, False, zebra))
        transport = checker.check_transport(*args)
        tx = next(tx for tx in transport['transfers'] if tx['opcode'] == 6)
        raw = checker.transfer_output(args[0], tx)
        incoming = checker.transfer_output
        for offsets in ((131,), (16, 152), (24, 144), (32,)):
            altered = bytearray(raw)
            for offset in offsets:
                if offset == 131:
                    altered[offset] ^= 1
                elif offset == 32:
                    struct.pack_into('<Q', altered, offset, 1)
                else:
                    struct.pack_into('<Q', altered, offset, struct.unpack_from('<Q', altered, offset)[0] + 1)
            # The forged receipt passes its own internal algebra; actual route/history must still reject it.
            self.assertEqual(checker.vdf_result(altered, zebra, 99, 6, altered[128:144])['enabled'], 1)
            def changed_output(run, transfer):
                return bytes(altered) if transfer['first'] == tx['first'] else incoming(run, transfer)
            with self.subTest(offsets=offsets), mock.patch.object(checker, 'transfer_output', side_effect=changed_output), self.assertRaises(ValueError):
                checker.vdf_history(args[0], transport)
        index = transport['transfers'].index(tx)
        state = transport['transfers'][index + 1]
        self.assertEqual(state['opcode'], 1)
        self.assertIsNone(state['frame'])
        raw = incoming(args[0], state)
        for offset in (8, 12, 16, 20, 24, 28, 32, 40, 56):
            altered = bytearray(raw)
            altered[offset] ^= 1
            def changed_state(run, transfer):
                return bytes(altered) if transfer['first'] == state['first'] else incoming(run, transfer)
            with self.subTest(state_offset=offset), mock.patch.object(checker, 'transfer_output', side_effect=changed_state), self.assertRaisesRegex(
                    ValueError, 'Config48 camera parameters or configuration generation'):
                checker.vdf_history(args[0], transport)

    def test_Zebra_actual_mailbox_opcode6_requires_exact_8byte_request(self):
        args = host_test_capture(self.root, (bytes.fromhex('0300204b41000000'),))
        for offset, wrong in ((32, 5), (36, 16), (36, 48)):
            changed = copy.deepcopy(args)
            event = next(row for row in changed[3] if row['kind'] == 'request' and row['opcode'] == 6)
            header = bytearray.fromhex(event['raw_header_hex'])
            struct.pack_into('<I', header, offset, wrong)
            event.update(raw_header_hex=header.hex(), raw_header_sha256=checker.sha(header))
            with self.subTest(offset=offset, wrong=wrong), self.assertRaises(ValueError):
                checker.check_transport(*changed)

    def test_Zebra_zero_status_never_replaces_media_native_completion_or_decode(self):
        args = host_test_capture(self.root, (True, bytes.fromhex('0300204b41000000')))
        transport = checker.check_transport(*args)
        for op in (16, 33, 34):
            changed = dict(transport, transfers=[tx for tx in transport['transfers'] if tx['opcode'] != op])
            with self.subTest(missing=op), self.assertRaises(ValueError):
                checker.check_frames(args[0], changed)
        storage = checker.writeback.inspect(args[0])
        rows = [row for row in args[2] if not (row['tag'] == 'FUNCTIONAL_JPEG_CODEC' and
                                              row['fields']['operation'] == 'original-rescmd-done')]
        with self.assertRaises(checker.MissingEvidence):
            checker.check_jpeg(rows, transport, storage, args[0])
        rows = [row for row in args[2] if row['tag'] != 'FUNCTIONAL_MPR_EVENT_FREE']
        with self.assertRaises(checker.MissingEvidence):
            checker.check_video(rows, transport, storage, args[0])
        for product in ('JPEG', 'MP4'):
            changed = copy.deepcopy(storage)
            next(item for item in changed['items'] if item['decode']['format'] == product)['independent_decoded'] = False
            function = checker.check_jpeg if product == 'JPEG' else checker.check_video
            with self.subTest(decode=product), self.assertRaises(ValueError):
                function(args[2], transport, changed, args[0])

    def test_original_jfz_resource_diagnostics_stay_outside_cycles_and_claims(self):
        args = host_test_capture(self.root, (True, bytes.fromhex('0300204b41000000')))
        transport = checker.check_transport(*args)
        diagnostics = checker.parse_console(JFZ_VDF_RESOURCE_OBS.encode('ascii'))
        original = copy.deepcopy(diagnostics)
        result = checker.check_vdf_path(args[0], diagnostics + args[2] + diagnostics, transport)
        self.assertTrue(result['verified'])
        self.assertEqual(result['cycles'], transport['VDF_path']['cycles'])
        self.assertEqual(result['diagnostics'], diagnostics * 2)
        self.assertEqual(diagnostics, original)
        self.assertTrue(all('cycle' not in row['fields'] and 'verified' not in row for row in result['diagnostics']))
        self.assertEqual(diagnostics[0]['fields']['pid'], '258')
        self.assertEqual(diagnostics[1]['fields']['atomic_snapshot'], '0')
        self.assertEqual(diagnostics[1]['fields']['ownership_verified'], '0')
        self.assertEqual(diagnostics[2]['fields']['global_dmm_idle_verified'], '0')
        only = checker.check_vdf_path(args[0], diagnostics, {'transfers': []})
        self.assertEqual(only, dict(required=False, verified=False, cycles=[], diagnostics=original))
        for tag in ('REQUEST_FREE', 'SEND', 'COMPLETE', 'RECEIVE', 'AP_FREE'):
            rows = diagnostics + [row for row in args[2] if row['tag'] != 'FUNCTIONAL_VDF_PATH_' + tag]
            with self.subTest(missing=tag), self.assertRaises(checker.MissingEvidence):
                checker.check_vdf_path(args[0], rows, transport)

    def test_resource_diagnostics_require_complete_known_producer_grammar(self):
        rows = checker.parse_console(JFZ_VDF_RESOURCE_OBS.encode('ascii'))
        mutations = ((0, 'accepted', '0'), (0, 'output_faults', '1'), (0, 'capture_verified', '1'),
                     (0, 'pid', '0'), (0, 'tid', '-1'), (0, 'tid', str(2**31)), (0, 'accepted', '01'),
                     (1, 'reads', '144/143'), (1, 'reads', '144/144/144'), (1, 'bytes', '143'),
                     (1, 'raw_before', '00' * 143), (1, 'raw_after', '00' * 144),
                     (1, 'raw_before', rows[1]['fields']['raw_before'].upper()), (1, 'unchanged', '0'),
                     (1, 'atomic_snapshot', '1'), (1, 'ownership_verified', '1'),
                     (1, 'table_va', '0x5f66b09'), (1, 'address', '0x7f2bba5b09'), (1, 'appfw_base', '0'),
                     (2, 'dmm_enabled', '2'), (2, 'dmm_slots', '1/2'), (2, 'dmm_handles', '0x08400/0x8401'),
                     (2, 'dmm_generations', str(2**32) + '/1'), (2, 'dmm_epochs', str(2**64) + '/2'),
                     (2, 'accepted', '0'), (2, 'control_faults', '1'), (2, 'data_frozen', '1'),
                     (2, 'global_dmm_idle_verified', '1'), (2, 'original_cp_executed', '1'),
                     (2, 'capture_verified', '1'), (2, 'allocations', '-1'))
        for index, key, wrong in mutations:
            changed = copy.deepcopy(rows)
            changed[index]['fields'][key] = wrong
            with self.subTest(index=index, key=key, wrong=wrong), self.assertRaises(ValueError):
                checker.check_vdf_path(self.root, changed, {'transfers': []})
        for row in rows:
            for key in row['fields']:
                changed = copy.deepcopy(row)
                del changed['fields'][key]
                with self.subTest(tag=row['tag'], missing=key), self.assertRaises(ValueError):
                    checker.vdf_resource_diagnostic(changed)
            for extra in ('cycle', 'semantic_verified', 'unknown'):
                changed = copy.deepcopy(row)
                changed['fields'][extra] = '1'
                with self.subTest(tag=row['tag'], extra=extra), self.assertRaises(ValueError):
                    checker.vdf_resource_diagnostic(changed)
        for suffix in ('RESOURCES_REFUSED', 'RESOURCES_FAULT', 'RESOURCES_RESERVED_EXTRA', 'FAIL', 'UNKNOWN', 'SEND_FAIL'):
            foreign = dict(tag='FUNCTIONAL_VDF_PATH_' + suffix, line=1, fields={})
            with self.subTest(tag=suffix), self.assertRaisesRegex(ValueError, 'failed/unknown VDF native receipt'):
                checker.check_vdf_path(self.root, rows + [foreign], {'transfers': []})
        for raw in (b'OBS FUNCTIONAL_VDF_PATH_RESOURCES_RESERVED process-owner-or-resource-lock-refused\n',
                    b'OBS FUNCTIONAL_VDF_PATH_RESOURCES_TTS_TABLE raw_before= raw_after=\n'):
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                checker.check_vdf_path(self.root, checker.parse_console(raw), {'transfers': []})

    def test_Layout_0138_0153_014c_then_CP_INIT_preserves_media_and_display_history(self):
        args = host_test_capture(self.root, (True, bytes.fromhex('0300204b41000000'), LAYOUT_BODY32))
        run, _, rows, _, build = args
        transport = checker.check_transport(*args)
        display = transport['VDF_path']
        self.assertEqual([cycle['opcode'] for cycle in display['cycles']], [5, 6, 7])
        self.assertEqual([cycle['config_generation'] for cycle in display['cycles']], [2, 4, 6])
        self.assertEqual([cycle['frame_generation'] for cycle in display['cycles']], [2, 3, 4])
        self.assertTrue(all(cycle['active'] and cycle['AP_consumed'] for cycle in display['cycles']))
        self.assertEqual(display['diagnostics'], checker.parse_console(JFZ_VDF_RESOURCE_OBS.encode('ascii')))
        self.assertEqual(transport['opcodes']['7'], 1)
        layout = next(tx for tx in transport['transfers'] if tx['opcode'] == 7)
        output = checker.transfer_output(run, layout)
        self.assertEqual(len(output), 192)
        self.assertEqual(output[160:], LAYOUT_BODY32)
        self.assertEqual(struct.unpack_from('<Q', output, 40)[0], checker.fnv(LAYOUT_BODY32))
        self.assertEqual(struct.unpack_from('<3I', output, 72), (640, 480, 1920))
        self.assertEqual(struct.unpack_from('<Q', output, 64)[0], 921600)
        cp = transport['transfers'][transport['transfers'].index(layout) + 1]
        self.assertEqual((cp['opcode'], cp['origin']['command']), (1, 0x3003))
        self.assertIsNone(cp['frame'])
        state = checker.transfer_output(run, cp)
        self.assertEqual(struct.unpack_from('<Q', state, 56)[0], 6)
        self.assertEqual(struct.unpack_from('<2Q', state, 64), (4, 3))
        self.assertEqual(struct.unpack_from('<Q', state, 112)[0], 4)
        frames = checker.check_frames(run, transport)
        self.assertEqual(frames['last_counts'], dict(rendered=9, consumed=8, retired=9, jpeg_encoded=1, video_encoded=4))
        self.assertEqual([job['proof']['consumer_kind'] for job in frames['jobs'][:4]], [0, 4, 4, 4])
        job = next(job for job in frames['jobs'] if job['opcode'] == 7)
        self.assertIn('configuration_result_sha256', job)
        self.assertNotIn('encoded_result_sha256', job)
        self.assertFalse(display['original_VDF_area_order_verified'])
        self.assertFalse(display['original_VDF_layout_hardware_verified'])
        storage = checker.writeback.inspect(run)
        self.assertTrue(checker.check_jpeg(rows, transport, storage, run)['storage_join_verified'])
        self.assertEqual(checker.check_video(rows, transport, storage, run)['samples'], 4)
        with mock.patch.object(checker, 'check_profile', return_value={'verified': True}), mock.patch.object(
                checker, 'check_batch', return_value=(build, {})):
            result = checker.evaluate(run, self.root / 'NO_FROZEN_BATCH')
        for name in ('transport', 'CMOS_encoder', 'JPEG_causality', 'MP4_causality'):
            self.assertTrue(result['evidence'][name]['verified'], result)
        self.assertFalse(result['capture_verified'])
        self.assertTrue(all(not product['capture_verified'] for product in result['products'].values()))
        self.assertTrue(any(item['stage'] == 'native_acceptance' for item in result['missing']))
        display_only = dict(transport, transfers=transport['transfers'][:transport['transfers'].index(cp) + 1])
        with self.assertRaises(checker.MissingEvidence):
            checker.check_frames(run, display_only)

    def test_Layout_requires_complete_independent_typed_policy_and_keeps_legacy_optional(self):
        args = host_test_capture(self.root, (True, LAYOUT_BODY32))
        producer = checker.source_module(checker.RUNTIME / 'backup_profile.py')
        fields = producer.functional_camera_profile_fields(checker.PROFILE)
        manifest = dict(fields, backup_transport=copy.deepcopy(fields),
                        directory_sd_profile='directory-vvfat-256gb-v1', rm_file_image_bytes=checker.writeback.CARD_BYTES)
        self.assertTrue(checker.check_profile(manifest)['verified'])
        for location in ('manifest', 'backup_transport'):
            for key, expected in checker.LAYOUT_POLICY.items():
                full_key = 'functional_camera_' + key
                self.assertTrue(checker.typed_equal(fields[full_key], expected))
                for wrong in ('missing', None, True, 0, '', [640, 480, 1920.0], [True, 480, 1920], [640, 480, 640]):
                    changed, profile = copy.deepcopy(args[1]), copy.deepcopy(manifest)
                    for value in (changed, profile):
                        target = value if location == 'manifest' else value[location]
                        if wrong == 'missing':
                            del target[full_key]
                        else:
                            target[full_key] = wrong
                    with self.subTest(location=location, key=key, wrong=wrong), self.assertRaisesRegex(
                            ValueError, 'initial-case0 software policy'):
                        checker.check_transport(args[0], changed, *args[2:])
                    with self.subTest(stage='profile', location=location, key=key, wrong=wrong), self.assertRaisesRegex(
                            ValueError, 'typed functional profile drift'):
                        checker.check_profile(profile)
        legacy = copy.deepcopy(manifest)
        for value in (legacy, legacy['backup_transport']):
            for key in checker.LAYOUT_POLICY:
                del value['functional_camera_' + key]
        self.assertTrue(checker.check_profile(legacy)['verified'])
        partial = copy.deepcopy(legacy)
        partial['functional_camera_layout_policy'] = checker.LAYOUT_POLICY['layout_policy']
        with self.assertRaisesRegex(ValueError, 'typed functional profile drift'):
            checker.check_profile(partial)

    def test_Layout192_binds_every_field_exact_body32_tail_and_active_geometry(self):
        args = host_test_capture(self.root, (True, LAYOUT_BODY32))
        transport = checker.check_transport(*args)
        tx = next(tx for tx in transport['transfers'] if tx['opcode'] == 7)
        raw = checker.transfer_output(args[0], tx)
        route = raw[128:144]
        self.assertEqual(checker.vdf_result(raw, LAYOUT_BODY32, 99, 7, route)['enabled'], 1)
        for offset in (*range(0, 32, 4), 32, *range(40, 128, 4), *range(128, 144), 144, 152, *range(160, 192)):
            changed = bytearray(raw)
            if offset == 32:
                struct.pack_into('<Q', changed, offset, 0)
            else:
                changed[offset] ^= 1
            with self.subTest(result_offset=offset), self.assertRaises(ValueError):
                checker.vdf_result(changed, LAYOUT_BODY32, 99, 7, route)
        for index in range(32):
            changed, output = bytearray(LAYOUT_BODY32), bytearray(raw)
            changed[index] ^= 1
            output[160:] = changed
            struct.pack_into('<Q', output, 40, checker.fnv(changed))
            with self.subTest(self_consistent_body=index), self.assertRaises(ValueError):
                checker.vdf_result(output, changed, 99, 7, route)
        for invalid in (b'', LAYOUT_BODY32[:8], LAYOUT_BODY32[:16], LAYOUT_BODY32[:-1], LAYOUT_BODY32 + b'\0'):
            with self.subTest(input_bytes=len(invalid)), self.assertRaises(ValueError):
                checker.vdf_result(raw, invalid, 99, 7, route)
        for invalid in (raw[:128], raw[:160], raw[:168], raw[:-1], raw + b'\0', bytes(192)):
            with self.subTest(result_bytes=len(invalid)), self.assertRaises(ValueError):
                checker.vdf_result(invalid, LAYOUT_BODY32, 99, 7, route)
        for opcode, instance, current in ((5, 99, route), (6, 99, route), (7, 100, route), (7, 99, None), (7, 99, bytes(16))):
            with self.subTest(opcode=opcode, instance=instance, current=current), self.assertRaises(ValueError):
                checker.vdf_result(raw, LAYOUT_BODY32, instance, opcode, current)
        for width, height, stride in ((24, 16, 72), (640, 480, 1921), (480, 640, 1440)):
            output = bytearray(raw)
            struct.pack_into('<3I', output, 72, width, height, stride)
            struct.pack_into('<Q', output, 64, width * height * 3)
            with self.subTest(geometry=(width, height, stride)), self.assertRaises(ValueError):
                checker.vdf_result(output, LAYOUT_BODY32, 99, 7, route)
        idle, disabled = bytearray(raw), b'\x00\x01\x01' + bytes(13)
        idle[128:144] = disabled
        for offset in (32, 48, 56, 64):
            struct.pack_into('<Q', idle, offset, 0)
        for offset in (96, 100, 112, 116):
            struct.pack_into('<I', idle, offset, 0)
        struct.pack_into('<Q', idle, 24, struct.unpack_from('<Q', idle, 144)[0])
        with self.assertRaises(ValueError):
            checker.vdf_result(idle, LAYOUT_BODY32, 99, 7, disabled)

    def test_Layout_native_ACK_origin_cycle_free_and_foreign_rows_fail_closed(self):
        args = host_test_capture(self.root, (True, bytes.fromhex('0300204b41000000'), LAYOUT_BODY32), vdf_inline=True)
        transport = checker.check_transport(*args)
        original = '0d204c0128000180' + LAYOUT_BODY32.hex()
        mutations = (('ack_wire', '0d204c110c00018000000000'), ('ack_wire', '0d2038110c00018000005900'),
                     ('ack_wire', '0d2053110c00018000000000'), ('ack_wire', '0d204c120c00018000005900'),
                     ('command', '0x153'), ('bytes', '32'), ('raw', original[:-2] + '01'),
                     ('raw', original[:-2]), ('raw', original + '00'), ('raw', '0d203801' + original[8:]),
                     ('canonical_layout32', '00' * 32), ('canonical_config', '00' * 16),
                     ('model_result_bytes', '168'), ('realresultbytes', '160'), ('model_result_hex', '00' * 192),
                     ('original_fnv1a', '0000000000000000'), ('model_result_fnv1a64', '0000000000000000'),
                     ('model_instance', '100'), ('config_generation', '1'), ('before_config_generation', '1'),
                     ('frame_generation', '1'), ('before_frame_generation', '1'), ('lease_generation', '0'),
                     ('cycle', '2'), ('completed_cycles', '3'), ('pid', '78'), ('tid', '91'), ('sender_tid', '91'),
                     ('receiver_tid', '91'), ('free_tid', '91'), ('source', '0x81cf61c5'), ('destination', '0x92840748'),
                     ('ack_retained', '0x500001'), ('allocation_returned', '0x500001'), ('allocation_alias', '1'),
                     ('request_free_rc', '-1'), ('request_retained', '0x1234'), ('request_freed', '0'),
                     ('free_rc', '-1'), ('AP_consumed', '1'), ('physical_ASIC_verified', '1'))
        for key, wrong in mutations:
            rows = copy.deepcopy(args[2])
            target = next(row for row in rows if row['tag'] == 'FUNCTIONAL_VDF_PATH_AP_FREE' and row['fields']['command'] == '0x14c')
            target['fields'][key] = wrong
            with self.subTest(field=key, wrong=wrong), self.assertRaises(ValueError):
                checker.check_vdf_path(args[0], rows, transport)
        for tag in ('REQUEST_FREE', 'SEND', 'COMPLETE', 'RECEIVE', 'AP_FREE'):
            rows = [row for row in args[2] if not (row['tag'] == 'FUNCTIONAL_VDF_PATH_' + tag and row['fields']['command'] == '0x14c')]
            with self.subTest(missing=tag), self.assertRaises(checker.MissingEvidence):
                checker.check_vdf_path(args[0], rows, transport)
        for key in ('canonical_layout32', 'model_result_bytes'):
            rows = copy.deepcopy(args[2])
            del next(row for row in rows if row['tag'] == 'FUNCTIONAL_VDF_PATH_SEND' and row['fields']['command'] == '0x14c')['fields'][key]
            with self.subTest(missing=key), self.assertRaises((ValueError, KeyError)):
                checker.check_vdf_path(args[0], rows, transport)
        for tag in ('UNKNOWN', 'RESOURCES_FAULT', 'FAIL'):
            rows = args[2] + [dict(tag='FUNCTIONAL_VDF_PATH_' + tag, line=1000, fields={})]
            with self.subTest(foreign=tag), self.assertRaises(ValueError):
                checker.check_vdf_path(args[0], rows, transport)
        foreign = copy.deepcopy(next(row for row in args[2] if row['tag'] == 'FUNCTIONAL_VDF_PATH_AP_FREE'))
        foreign['fields']['cycle'] = '4'
        with self.assertRaises(ValueError):
            checker.check_vdf_path(args[0], args[2] + [foreign], transport)
        changed = copy.deepcopy(transport)
        next(tx for tx in changed['transfers'] if tx['opcode'] == 7)['opcode'] = 3
        with self.assertRaises(ValueError):
            checker.check_vdf_path(args[0], args[2], changed)

    def test_Layout_kind4_requires_actual_RGB_lease_retire_and_zero_codec_counters(self):
        args = host_test_capture(self.root, (True, LAYOUT_BODY32))
        transport = checker.check_transport(*args)
        mutations = (('consumer_kind', 1), ('opcode', 6), ('encoder_consumed', 1), ('encoded_bytes', 1),
                     ('encoded_fnv1a64', 0), ('result_bytes', 192), ('result_fnv1a64', 0), ('result_token', 1),
                     ('model_instance', 100), ('owner_pid', 178), ('struct_bytes', 375), ('model_lifetime', 0),
                     ('source_fnv1a64', 1), ('consumer_before_fnv1a64', 1), ('consumer_after_fnv1a64', 1),
                     ('active_bytes', 1152), ('width', 24), ('stride', 72), ('lease_generation', 0),
                     ('frame_generation', 0), ('config_generation', 0), ('consumer_entered', 0), ('consumer_returned', 0),
                     ('render_observed', 0), ('retired', 0), ('source_state', 4), ('consumer_before_state', 3),
                     ('consumer_after_state', 3), ('final_state', 4), ('render_status', -1), ('consumer_status', -1),
                     ('retire_status', -1), ('operation_status', -1))
        for key, wrong in mutations:
            changed = copy.deepcopy(transport)
            next(tx['frame']['proof'] for tx in changed['transfers'] if tx['opcode'] == 7)[key] = wrong
            for stage in ('native', 'frames'):
                with self.subTest(stage=stage, key=key), self.assertRaises(ValueError):
                    if stage == 'native':
                        checker.check_vdf_path(args[0], args[2], changed)
                    else:
                        checker.check_frames(args[0], changed)
        for counter in ('rendered', 'consumed', 'retired', 'jpeg_encoded', 'video_encoded'):
            changed = copy.deepcopy(transport)
            next(tx['frame']['proof'] for tx in changed['transfers'] if tx['opcode'] == 7)['after'][counter] += 1
            with self.subTest(counter=counter), self.assertRaises(ValueError):
                checker.check_vdf_path(args[0], args[2], changed)
        changed = copy.deepcopy(transport)
        next(tx for tx in changed['transfers'] if tx['opcode'] == 7)['frame'] = None
        for function, arguments in ((checker.check_vdf_path, (args[0], args[2], changed)), (checker.check_frames, (args[0], changed))):
            with self.assertRaises(checker.MissingEvidence):
                function(*arguments)

    def test_Layout_history_preserves_current_route_Config48_and_rejects_stale_leases(self):
        args = host_test_capture(self.root, (True, LAYOUT_BODY32))
        transport = checker.check_transport(*args)
        tx = next(tx for tx in transport['transfers'] if tx['opcode'] == 7)
        incoming = checker.transfer_output
        raw = incoming(args[0], tx)
        for offsets in ((131,), (16, 152), (24, 144), (32,)):
            altered = bytearray(raw)
            for offset in offsets:
                if offset == 131:
                    altered[offset] ^= 1
                elif offset == 32:
                    struct.pack_into('<Q', altered, offset, 1)
                else:
                    struct.pack_into('<Q', altered, offset, struct.unpack_from('<Q', altered, offset)[0] + 1)
            self.assertEqual(checker.vdf_result(altered, LAYOUT_BODY32, 99, 7, altered[128:144])['enabled'], 1)
            def changed_output(run, transfer):
                return bytes(altered) if transfer['first'] == tx['first'] else incoming(run, transfer)
            with self.subTest(offsets=offsets), mock.patch.object(checker, 'transfer_output', side_effect=changed_output), self.assertRaises(ValueError):
                checker.vdf_history(args[0], transport)
        state = transport['transfers'][transport['transfers'].index(tx) + 1]
        self.assertEqual((state['opcode'], state['origin']['command']), (1, 0x3003))
        raw = incoming(args[0], state)
        for offset in (8, 12, 16, 20, 24, 28, 32, 40, 56):
            altered = bytearray(raw)
            altered[offset] ^= 1
            def changed_state(run, transfer):
                return bytes(altered) if transfer['first'] == state['first'] else incoming(run, transfer)
            with self.subTest(state_offset=offset), mock.patch.object(checker, 'transfer_output', side_effect=changed_state), self.assertRaisesRegex(
                    ValueError, 'Config48 camera parameters or configuration generation'):
                checker.vdf_history(args[0], transport)

    def test_Layout_mailbox_and_raw_payload_require_exact_opcode7_input32(self):
        args = host_test_capture(self.root, (True, LAYOUT_BODY32))
        for offset, wrong in ((32, 5), (32, 6), (36, 8), (36, 16), (36, 31), (36, 40), (36, 48)):
            changed = copy.deepcopy(args)
            event = next(row for row in changed[3] if row['kind'] == 'request' and row['opcode'] == 7)
            header = bytearray.fromhex(event['raw_header_hex'])
            struct.pack_into('<I', header, offset, wrong)
            event.update(raw_header_hex=header.hex(), raw_header_sha256=checker.sha(header))
            with self.subTest(offset=offset, wrong=wrong), self.assertRaises(ValueError):
                checker.check_transport(*changed)
        for key, wrong in (('model_instance', 100), ('opcode', 6), ('bytes', 8), ('fnv1a64', 0)):
            changed = copy.deepcopy(args)
            event = next(row for row in changed[3] if row['kind'] == 'request' and row['opcode'] == 7)
            event['request_payload'][key] = wrong
            with self.subTest(payload_field=key), self.assertRaises(ValueError):
                checker.check_transport(*changed)

    def test_Display_mixed_5_6_7_8_8_CP_INIT_preserves_independent_configs_and_media(self):
        args = host_test_capture(self.root, DISPLAY_PATHS)
        run, _, rows, _, build = args
        transport = checker.check_transport(*args)
        cycles = transport['VDF_path']['cycles']
        self.assertEqual([item['opcode'] for item in cycles], [5, 6, 7, 8, 8])
        self.assertEqual([item['native_command'] for item in cycles], [0x138, 0x153, 0x14c, 0x152, 0x162])
        self.assertEqual([item['config_generation'] for item in cycles], [2, 4, 6, 8, 10])
        self.assertEqual([item['frame_generation'] for item in cycles], [2, 3, 4, 5, 6])
        self.assertEqual(transport['opcodes']['8'], 2)
        displays = [tx for tx in transport['transfers'] if tx['opcode'] == 8]
        envelopes = [struct.pack('<2I', 0x152, 8) + PEAKING_BODY8, struct.pack('<2I', 0x162, 2) + bytes(8)]
        for tx, envelope in zip(displays, envelopes):
            output = checker.transfer_output(run, tx)
            self.assertEqual(len(output), 176)
            self.assertEqual(output[160:], envelope)
            self.assertEqual(output[128:144], checker.transfer_output(run, displays[0])[128:144])
            self.assertEqual(struct.unpack_from('<Q', output, 40)[0], checker.fnv(envelope))
            self.assertEqual(tx['token'], 0)
        sent = [row['fields'] for row in rows if row['tag'] == 'FUNCTIONAL_VDF_PATH_SEND' and row['fields']['command'] in ('0x152', '0x162')]
        self.assertEqual([f['raw'] for f in sent], ['0d205201100001800300010000eb8080', '0d2062010a0001800000'])
        self.assertEqual([f['ack_wire'] for f in sent], ['0d2052110c00018000005900', '0d2062110c00018000005900'])
        cp = transport['transfers'][transport['transfers'].index(displays[-1]) + 1]
        self.assertEqual((cp['opcode'], cp['origin']['command']), (1, 0x3003))
        self.assertIsNone(cp['frame'])
        state = checker.transfer_output(run, cp)
        self.assertEqual(struct.unpack_from('<Q', state, 56)[0], 10)
        self.assertEqual(struct.unpack_from('<2Q', state, 64), (6, 5))
        self.assertEqual(struct.unpack_from('<Q', state, 112)[0], 6)
        frames = checker.check_frames(run, transport)
        self.assertEqual(frames['last_counts'], dict(rendered=11, consumed=10, retired=11, jpeg_encoded=1, video_encoded=4))
        self.assertEqual([job['proof']['consumer_kind'] for job in frames['jobs'][:6]], [0, 4, 4, 4, 4, 4])
        for job in (job for job in frames['jobs'] if job['opcode'] == 8):
            self.assertIn('configuration_result_sha256', job)
            self.assertNotIn('encoded_result_sha256', job)
        for key in ('original_Peaking_operator_verified', 'original_0162_feature_verified'):
            self.assertFalse(transport['VDF_path'][key])
        storage = checker.writeback.inspect(run)
        self.assertTrue(checker.check_jpeg(rows, transport, storage, run)['storage_join_verified'])
        self.assertEqual(checker.check_video(rows, transport, storage, run)['samples'], 4)
        with mock.patch.object(checker, 'check_profile', return_value={'verified': True}), mock.patch.object(
                checker, 'check_batch', return_value=(build, {})):
            result = checker.evaluate(run, self.root / 'NO_FROZEN_BATCH')
        for name in ('transport', 'CMOS_encoder', 'JPEG_causality', 'MP4_causality'):
            self.assertTrue(result['evidence'][name]['verified'], result)
        self.assertFalse(result['capture_verified'])
        self.assertTrue(all(not item['capture_verified'] for item in result['products'].values()))
        display_only = dict(transport, transfers=transport['transfers'][:transport['transfers'].index(cp) + 1])
        with self.assertRaises(checker.MissingEvidence):
            checker.check_frames(run, display_only)

    def test_Display_disabled_palette_subset_non640_inline_and_active_route_requirement(self):
        cp = dict(producer_tid=92, source=0x81cf1234, destination=0x92880001,
                  command=0x3003, bytes=8, fnv1a64=checker.fnv(b'HOST_TEST CP INIT'))
        args = host_test_capture(self.root, (True, ('display', 0x152), ('display', 0x162)),
                                 vdf_inline=True, initial_origin=cp)
        transport = checker.check_transport(*args)
        frames = checker.check_frames(args[0], transport)
        self.assertEqual(sum(job['opcode'] == 1 for job in frames['jobs']), 1)
        tx = next(tx for tx in transport['transfers'] if tx['opcode'] == 8)
        raw = checker.transfer_output(args[0], tx)
        self.assertEqual(struct.unpack_from('<3I', raw, 72), (24, 16, 72))
        for index, color in enumerate(((81, 90, 240), (210, 16, 146), (29, 255, 83), (235, 128, 128))):
            body = bytes([3, 0, index % 3, (0, 10, 40, 0)[index], 0, *color])
            envelope, output = struct.pack('<2I', 0x152, 8) + body, bytearray(raw)
            output[160:] = envelope
            struct.pack_into('<Q', output, 40, checker.fnv(envelope))
            with self.subTest(palette=index):
                self.assertEqual(checker.vdf_result(output, envelope, 99, 8, output[128:144])['enabled'], 1)
        changed = copy.deepcopy(transport)
        bound = next(tx for tx in changed['transfers'] if tx['opcode'] == 1 and tx['origin']['command'] == 0x138)
        bound['origin']['fnv1a64'] ^= 1
        with self.assertRaises(checker.MissingEvidence):
            checker.check_vdf_path(args[0], args[2], changed)
        idle_root = self.root / 'idle'
        idle_root.mkdir()
        idle = host_test_capture(idle_root, (False, ('display', 0x162)))
        with self.assertRaisesRegex(ValueError, 'committed active RGB route'):
            checker.check_transport(*idle)

    def test_Display_policy_is_exact_typed_in_both_copies_and_optional_without_op8(self):
        args = host_test_capture(self.root, (True, ('display', 0x152), ('display', 0x162)))
        producer = checker.source_module(checker.RUNTIME / 'backup_profile.py')
        fields = producer.functional_camera_profile_fields(checker.PROFILE)
        profile = dict(fields, backup_transport=copy.deepcopy(fields), directory_sd_profile='directory-vvfat-256gb-v1',
                       rm_file_image_bytes=checker.writeback.CARD_BYTES)
        self.assertTrue(checker.check_profile(profile)['verified'])
        for location in ('manifest', 'backup_transport'):
            for key, expected in checker.DISPLAY_POLICY.items():
                full_key = 'functional_camera_' + key
                self.assertTrue(checker.typed_equal(fields[full_key], expected))
                wrong_values = ('missing', None, 0, True) if expected is False else (
                    ('missing', None, [0x162, 0x152], [0x152], [True, 0x162], [338.0, 354]) if type(expected) is list else
                    ('missing', None, False, 'disabled'))
                for wrong in wrong_values:
                    changed, changed_profile = copy.deepcopy(args[1]), copy.deepcopy(profile)
                    for value in (changed, changed_profile):
                        target = value if location == 'manifest' else value[location]
                        if wrong == 'missing':
                            del target[full_key]
                        else:
                            target[full_key] = wrong
                    with self.subTest(location=location, key=key, wrong=wrong):
                        with self.assertRaisesRegex(ValueError, 'disabled/off software policy'):
                            checker.check_transport(args[0], changed, *args[2:])
                        with self.assertRaisesRegex(ValueError, 'typed functional profile drift'):
                            checker.check_profile(changed_profile)
        for target in (profile, profile['backup_transport']):
            for key in checker.DISPLAY_POLICY:
                del target['functional_camera_' + key]
        self.assertTrue(checker.check_profile(profile)['verified'])
        profile['functional_camera_peaking_enabled_supported'] = False
        with self.assertRaisesRegex(ValueError, 'typed functional profile drift'):
            checker.check_profile(profile)

    def test_Display176_rejects_unsupported_enabled_typed_envelopes_and_readback_drift(self):
        args = host_test_capture(self.root, (True, ('display', 0x152), ('display', 0x162)))
        transport = checker.check_transport(*args)
        for tx in (tx for tx in transport['transfers'] if tx['opcode'] == 8):
            raw, canonical = checker.transfer_output(args[0], tx), checker.payload_read(args[0], tx['request_payload'])
            route = raw[128:144]
            for offset, wrong in ((0, 0), (4, 0), (8, 100), (16, 1), (24, 1), (32, 0),
                                  (40, 0), (48, 1), (56, 1), (64, 0), (84, 0), (108, 0), (160, 0)):
                output = bytearray(raw)
                struct.pack_into('<I' if offset in (0, 4, 84, 108, 160) else '<Q', output, offset, wrong)
                with self.subTest(command=tx['origin']['command'], result_offset=offset), self.assertRaises(ValueError):
                    checker.vdf_result(output, canonical, 99, 8, route)
            for output in (raw[:160], raw[:168], raw[:-1], raw + b'\0'):
                with self.subTest(result_bytes=len(output)), self.assertRaises(ValueError):
                    checker.vdf_result(output, canonical, 99, 8, route)
            with self.assertRaises(ValueError):
                checker.vdf_result(raw, canonical, 99, 8, bytes(16))
            mutations = ((0, 0x153), (4, 2), (8, 4), (9, 1), (10, 3), (11, 1), (12, 1), (13, 0)) if tx['origin']['command'] == 0x152 else (
                         (0, 0x152), (4, 8), (8, 1), (9, 1), (10, 1), (15, 1))
            for offset, wrong in mutations:
                envelope, output = bytearray(canonical), bytearray(raw)
                if offset < 8:
                    struct.pack_into('<I', envelope, offset, wrong)
                else:
                    envelope[offset] = wrong
                output[160:] = envelope
                struct.pack_into('<Q', output, 40, checker.fnv(envelope))
                with self.subTest(command=tx['origin']['command'], unsupported_offset=offset), self.assertRaises(ValueError):
                    checker.vdf_result(output, envelope, 99, 8, route)
            for envelope in (canonical[:8], canonical[:-1], canonical + b'\0'):
                with self.subTest(input_bytes=len(envelope)), self.assertRaises(ValueError):
                    checker.vdf_result(raw, envelope, 99, 8, route)

    def test_Display_native_commands_cannot_borrow_ACK_config_or_skip_original_free(self):
        args = host_test_capture(self.root, DISPLAY_PATHS)
        transport = checker.check_transport(*args)
        for command, other in ((0x152, 0x162), (0x162, 0x152)):
            source = next(row for row in args[2] if row['tag'] == 'FUNCTIONAL_VDF_PATH_AP_FREE' and
                          row['fields']['command'] == hex(command))
            borrowed = next(row['fields']['canonical_display16'] for row in args[2] if row['tag'] == 'FUNCTIONAL_VDF_PATH_SEND' and
                            row['fields']['command'] == hex(other))
            mutations = (('ack_wire', struct.pack('<4HI', 0x200d, other + 0x1000, 12, 0x8001, 0x590000).hex()),
                         ('ack_wire', struct.pack('<4HI', 0x200d, command + 0x1000, 12, 0x8001, 0).hex()),
                         ('raw', source['fields']['raw'] + '00'), ('bytes', '8'), ('command', hex(other)),
                         ('canonical_display16', borrowed), ('original_fnv1a', '0000000000000000'),
                         ('model_result_fnv1a64', '0000000000000000'), ('model_result_bytes', '168'),
                         ('model_instance', '100'), ('source', '0x81cf9999'), ('destination', '0x92840748'),
                         ('cycle', '3'), ('AP_consumed', '0'), ('free_tid', '91'), ('free_rc', '-1'))
            for key, wrong in mutations:
                rows = copy.deepcopy(args[2])
                next(row for row in rows if row['line'] == source['line'])['fields'][key] = wrong
                with self.subTest(command=command, field=key), self.assertRaises(ValueError):
                    checker.check_vdf_path(args[0], rows, transport)
            for tag in ('REQUEST_FREE', 'SEND', 'COMPLETE', 'RECEIVE', 'AP_FREE'):
                rows = [row for row in args[2] if not (row['tag'] == 'FUNCTIONAL_VDF_PATH_' + tag and row['fields']['command'] == hex(command))]
                with self.subTest(command=command, missing=tag), self.assertRaises(checker.MissingEvidence):
                    checker.check_vdf_path(args[0], rows, transport)
            for key in ('canonical_display16', 'model_result_bytes'):
                rows = copy.deepcopy(args[2])
                del next(row for row in rows if row['line'] == source['line'])['fields'][key]
                with self.subTest(command=command, missing_field=key), self.assertRaises((ValueError, KeyError)):
                    checker.check_vdf_path(args[0], rows, transport)
            changed = copy.deepcopy(transport)
            next(tx for tx in changed['transfers'] if tx['opcode'] == 8 and tx['origin']['command'] == command)['opcode'] = 3
            with self.subTest(command=command, relabelled=True), self.assertRaises(ValueError):
                checker.check_vdf_path(args[0], args[2], changed)

    def test_Display_kind4_and_history_require_fresh_RGB_without_codec_or_camera_drift(self):
        args = host_test_capture(self.root, DISPLAY_PATHS)
        transport = checker.check_transport(*args)
        displays = [tx for tx in transport['transfers'] if tx['opcode'] == 8]
        for tx in displays:
            for key, wrong in (('consumer_kind', 1), ('encoder_consumed', 1), ('result_bytes', 176),
                               ('source_fnv1a64', 1), ('consumer_entered', 0), ('consumer_returned', 0),
                               ('retired', 0), ('consumer_status', -1), ('lease_generation', 0), ('model_instance', 100)):
                changed = copy.deepcopy(transport)
                next(item['frame']['proof'] for item in changed['transfers'] if item['first'] == tx['first'])[key] = wrong
                with self.subTest(command=tx['origin']['command'], proof=key):
                    with self.assertRaises(ValueError):
                        checker.check_vdf_path(args[0], args[2], changed)
                    with self.assertRaises(ValueError):
                        checker.check_frames(args[0], changed)
            for counter in ('consumed', 'video_encoded'):
                changed = copy.deepcopy(transport)
                next(item['frame']['proof'] for item in changed['transfers'] if item['first'] == tx['first'])['after'][counter] += 1
                with self.subTest(command=tx['origin']['command'], counter=counter), self.assertRaises(ValueError):
                    checker.check_vdf_path(args[0], args[2], changed)
            original = checker.transfer_output
            raw, canonical = original(args[0], tx), checker.payload_read(args[0], tx['request_payload'])
            for offsets in ((131,), (16, 152), (24, 144), (32,)):
                output = bytearray(raw)
                for offset in offsets:
                    if offset == 131:
                        output[offset] ^= 1
                    else:
                        struct.pack_into('<Q', output, offset, 1 if offset == 32 else struct.unpack_from('<Q', output, offset)[0] + 1)
                self.assertEqual(checker.vdf_result(output, canonical, 99, 8, output[128:144])['enabled'], 1)
                def forged(run, item):
                    return bytes(output) if item['first'] == tx['first'] else original(run, item)
                with self.subTest(command=tx['origin']['command'], history=offsets), mock.patch.object(
                        checker, 'transfer_output', side_effect=forged), self.assertRaises(ValueError):
                    checker.vdf_history(args[0], transport)
            changed = copy.deepcopy(transport)
            next(item for item in changed['transfers'] if item['first'] == tx['first'])['frame'] = None
            with self.assertRaises(checker.MissingEvidence):
                checker.check_vdf_path(args[0], args[2], changed)
        cp = transport['transfers'][transport['transfers'].index(displays[-1]) + 1]
        output = bytearray(original(args[0], cp))
        output[24] ^= 1
        def forged_state(run, item):
            return bytes(output) if item['first'] == cp['first'] else original(run, item)
        with mock.patch.object(checker, 'transfer_output', side_effect=forged_state), self.assertRaisesRegex(ValueError, 'Config48'):
            checker.vdf_history(args[0], transport)

    def test_Display_mailbox_requires_opcode8_input16_and_same_native_payload_binding(self):
        args = host_test_capture(self.root, (True, ('display', 0x152), ('display', 0x162)))
        for command in (0x152, 0x162):
            for offset, wrong in ((32, 7), (36, 8), (36, 32), (16, 100)):
                changed = copy.deepcopy(args)
                event = next(row for row in changed[3] if row['kind'] == 'request' and row['opcode'] == 8 and row['origin']['command'] == command)
                header = bytearray.fromhex(event['raw_header_hex'])
                struct.pack_into('<I', header, offset, wrong)
                event.update(raw_header_hex=header.hex(), raw_header_sha256=checker.sha(header))
                with self.subTest(command=command, header_offset=offset, wrong=wrong), self.assertRaises(ValueError):
                    checker.check_transport(*changed)
            changed = copy.deepcopy(args)
            event = next(row for row in changed[3] if row['kind'] == 'request' and row['opcode'] == 8 and row['origin']['command'] == command)
            event['request_payload']['origin']['command'] = 0x162 if command == 0x152 else 0x152
            with self.subTest(command=command, foreign_payload=True), self.assertRaises(ValueError):
                checker.check_transport(*changed)

    def test_Refresh_mixed_5_6_7_8_8_8_CP_INIT_preserves_feature_tails_and_media(self):
        args = host_test_capture(self.root, REFRESH_PATHS)
        run, _, rows, _, build = args
        transport = checker.check_transport(*args)
        cycles = transport['VDF_path']['cycles']
        self.assertEqual([item['opcode'] for item in cycles], [5, 6, 7, 8, 8, 8])
        self.assertEqual([item['native_command'] for item in cycles], [0x138, 0x153, 0x14c, 0x152, 0x162, 0x141])
        self.assertEqual([item['config_generation'] for item in cycles], [2, 4, 6, 8, 10, 12])
        self.assertEqual([item['frame_generation'] for item in cycles], [2, 3, 4, 5, 6, 7])
        self.assertEqual(transport['opcodes']['8'], 3)
        displays = [tx for tx in transport['transfers'] if tx['opcode'] == 8]
        envelopes = [struct.pack('<2I', 0x152, 8) + PEAKING_BODY8,
                     struct.pack('<2I', 0x162, 2) + bytes(8), struct.pack('<2I', 0x141, 0) + bytes(8)]
        for tx, envelope in zip(displays, envelopes):
            output = checker.transfer_output(run, tx)
            self.assertEqual(checker.payload_read(run, tx['request_payload']), envelope)
            self.assertEqual((len(output), output[160:], tx['token']), (176, envelope, 0))
            self.assertEqual(struct.unpack_from('<Q', output, 40)[0], checker.fnv(envelope))
        refresh = displays[-1]
        sent = next(row['fields'] for row in rows if row['tag'] == 'FUNCTIONAL_VDF_PATH_SEND' and row['fields']['command'] == '0x141')
        self.assertEqual((sent['raw'], sent['ack_wire']), ('0d20410108000180', '0d2041110c00018000005900'))
        state_tx, cp = transport['transfers'][transport['transfers'].index(refresh) + 1:][:2]
        self.assertEqual((state_tx['opcode'], cp['opcode'], cp['origin']['command']), (2, 1, 0x3003))
        self.assertIsNone(cp['frame'])
        state = checker.transfer_output(run, cp)
        self.assertEqual(struct.unpack_from('<Q', state, 56)[0], 12)
        self.assertEqual(struct.unpack_from('<2Q', state, 64), (7, 6))
        self.assertEqual(struct.unpack_from('<Q', state, 112)[0], 7)
        self.assertEqual(state[8:48], checker.transfer_output(run, state_tx)[8:48])
        frames = checker.check_frames(run, transport)
        self.assertEqual(frames['last_counts'], dict(rendered=12, consumed=11, retired=12, jpeg_encoded=1, video_encoded=4))
        job = next(job for job in frames['jobs'] if job['first'] == refresh['first'])
        self.assertEqual((job['opcode'], job['proof']['consumer_kind'], job['proof']['encoder_consumed']), (8, 4, 0))
        self.assertIn('configuration_result_sha256', job)
        storage = checker.writeback.inspect(run)
        self.assertTrue(checker.check_jpeg(rows, transport, storage, run)['storage_join_verified'])
        self.assertEqual(checker.check_video(rows, transport, storage, run)['samples'], 4)
        with mock.patch.object(checker, 'check_profile', return_value={'verified': True}), mock.patch.object(
                checker, 'check_batch', return_value=(build, {})):
            result = checker.evaluate(run, self.root / 'NO_FROZEN_BATCH')
        for name in ('transport', 'CMOS_encoder', 'JPEG_causality', 'MP4_causality'):
            self.assertTrue(result['evidence'][name]['verified'], result)
        self.assertFalse(result['capture_verified'])
        self.assertTrue(all(not item['capture_verified'] for item in result['products'].values()))

    def test_Refresh_global_D_reuse_allows_intervening_CP_State_but_not_borrowed_replies(self):
        args = host_test_capture(self.root, (True, ('display', 0x141), ('display', 0x141)))
        run, _, rows, _, _ = args
        transport = checker.check_transport(*args)
        refreshes = [tx for tx in transport['transfers'] if tx['opcode'] == 8]
        self.assertEqual([tx['origin']['source'] for tx in refreshes], [0x81cf61c9] * 2)
        self.assertEqual([tx['origin']['fnv1a64'] for tx in refreshes], [checker.fnv(bytes.fromhex('0d20410108000180'))] * 2)
        self.assertEqual([item['frame_generation'] for item in transport['VDF_path']['cycles']], [2, 3, 4])
        for tx in refreshes:
            cycle = next(item for item in transport['VDF_path']['cycles'] if item['first'] == tx['first'])
            send = next(row for row in rows if row['tag'] == 'FUNCTIONAL_VDF_PATH_SEND' and int(row['fields']['cycle']) == cycle['cycle'])
            state_tx = transport['transfers'][transport['transfers'].index(tx) + 1]
            self.assertEqual((state_tx['opcode'], state_tx['origin']['command']), (2, 0x3003))
            self.assertTrue(send['line'] < state_tx['line'] < cycle['receive_line'] < cycle['free_line'])
            self.assertGreater(state_tx['first'], tx['last'])
            self.assertIsNone(state_tx['frame'])
        self.assertTrue(checker.check_frames(run, transport)['verified'])
        source = next(row for row in rows if row['tag'] == 'FUNCTIONAL_VDF_PATH_AP_FREE' and row['fields']['cycle'] == '3')
        mutations = (('raw', '0d2041010a000180'), ('raw', source['fields']['raw'] + '0000'), ('bytes', '10'),
                     ('ack_wire', '0d2041110c00018000000000'), ('ack_wire', '0d2062110c00018000005900'),
                     ('source', '0x81cf9999'), ('receiver_tid', '91'), ('free_tid', '91'), ('cycle', '2'),
                     ('request_freed', '0'), ('request_free_rc', '-1'), ('ack_retained', '0x500000'),
                     ('canonical_display16', (struct.pack('<2I', 0x162, 2) + bytes(8)).hex()))
        for key, wrong in mutations:
            changed = copy.deepcopy(rows)
            next(row for row in changed if row['line'] == source['line'])['fields'][key] = wrong
            with self.subTest(field=key), self.assertRaises(ValueError):
                checker.check_vdf_path(run, changed, transport)
        for tag in ('REQUEST_FREE', 'AP_FREE'):
            changed = [row for row in rows if not (row['tag'] == 'FUNCTIONAL_VDF_PATH_' + tag and row['fields']['cycle'] == '3')]
            with self.subTest(missing=tag), self.assertRaises(checker.MissingEvidence):
                checker.check_vdf_path(run, changed, transport)
        changed = copy.deepcopy(rows)
        del next(row for row in changed if row['line'] == source['line'])['fields']['raw']
        with self.assertRaises(checker.MissingEvidence):
            checker.check_vdf_path(run, changed, transport)
        changed = copy.deepcopy(rows)
        earlier = next(row['fields'] for row in rows if row['tag'] == source['tag'] and row['fields']['cycle'] == '2')
        late = next(row['fields'] for row in changed if row['line'] == source['line'])
        for key in ('model_result_hex', 'model_result_fnv1a64', 'config_generation', 'frame_generation', 'lease_generation'):
            late[key] = earlier[key]
        with self.assertRaises(ValueError):
            checker.check_vdf_path(run, changed, transport)
        changed = copy.deepcopy(transport)
        next(tx for tx in changed['transfers'] if tx['opcode'] == 2)['origin'] = refreshes[0]['origin'].copy()
        with self.assertRaisesRegex(ValueError, 'relabelled'):
            checker.check_vdf_path(run, rows, changed)

    def test_Refresh_body0_virtual_zeros_tail_and_actual_RGB_proof_are_required(self):
        args = host_test_capture(self.root, (True, ('display', 0x141)))
        run, _, rows, _, _ = args
        transport = checker.check_transport(*args)
        tx = next(tx for tx in transport['transfers'] if tx['opcode'] == 8)
        canonical = checker.payload_read(run, tx['request_payload'])
        raw = checker.transfer_output(run, tx)
        route = raw[128:144]
        for offset, wrong in ((0, 0x142), (0, 0x162), (4, 2), (4, 8), (8, 1), (15, 1)):
            envelope, output = bytearray(canonical), bytearray(raw)
            if offset < 8:
                struct.pack_into('<I', envelope, offset, wrong)
            else:
                envelope[offset] = wrong
            output[160:] = envelope
            struct.pack_into('<Q', output, 40, checker.fnv(envelope))
            with self.subTest(envelope_offset=offset, wrong=wrong), self.assertRaises(ValueError):
                checker.vdf_result(output, envelope, 99, 8, route)
        for envelope in (canonical[:8], canonical[:-1], canonical + b'\0'):
            with self.subTest(input_bytes=len(envelope)), self.assertRaises(ValueError):
                checker.vdf_result(raw, envelope, 99, 8, route)
        for output in (raw[:160], raw[:168], raw + bytes(16), raw[:160] + struct.pack('<2I', 0x162, 2) + bytes(8),
                       raw[:160] + struct.pack('<2I', 0x152, 8) + PEAKING_BODY8):
            with self.subTest(result_bytes=len(output), tail=output[160:]), self.assertRaises(ValueError):
                checker.vdf_result(output, canonical, 99, 8, route)
        for key, wrong in (('consumer_returned', 0), ('retired', 0), ('encoder_consumed', 1)):
            changed = copy.deepcopy(transport)
            next(item['frame']['proof'] for item in changed['transfers'] if item['first'] == tx['first'])[key] = wrong
            with self.subTest(proof=key):
                with self.assertRaises(ValueError):
                    checker.check_vdf_path(run, rows, changed)
                with self.assertRaises(ValueError):
                    checker.check_frames(run, changed)
        changed = copy.deepcopy(args)
        event = next(row for row in changed[3] if row['kind'] == 'request' and row['opcode'] == 8)
        header = bytearray.fromhex(event['raw_header_hex'])
        struct.pack_into('<I', header, 36, 8)
        event.update(raw_header_hex=header.hex(), raw_header_sha256=checker.sha(header))
        with self.assertRaises(ValueError):
            checker.check_transport(*changed)
        idle_root = self.root / 'idle_refresh'
        idle_root.mkdir()
        with self.assertRaisesRegex(ValueError, 'committed active RGB route'):
            checker.check_transport(*host_test_capture(idle_root, (False, ('display', 0x141))))

    def test_Refresh_binding_actual_global_ID_async_inline_and_media_joins(self):
        for source, inline in ((0x80946189, False), (0x80abcd12, True), (0x81cf61c9, False), (1, True)):
            root = self.root / str(source)
            root.mkdir()
            args = host_test_capture(root, (True, ('display', 0x141), ('display', 0x152),
                                     ('display', 0x162), True, ('display', 0x141)),
                                     refresh_source=source, vdf_inline=inline)
            run, _, rows, _, build = args
            transport = checker.check_transport(*args)
            bindings = [row for row in rows if row['tag'] == 'FUNCTIONAL_VDF_REFRESH_QUEUE_BOUND']
            cycles = transport['VDF_path']['cycles']
            refreshes = [cycle for cycle in cycles if cycle['native_command'] == 0x141]
            with self.subTest(source=hex(source), inline=inline):
                self.assertEqual([cycle['refresh_queue_binding'] for cycle in refreshes], bindings)
                self.assertEqual(len(bindings), 2)
                for cycle, binding in zip(refreshes, bindings):
                    tx = next(tx for tx in transport['transfers'] if tx['first'] == cycle['first'])
                    self.assertEqual(tx['origin']['source'], source)
                    self.assertLess(binding['line'], tx['line'])
                    self.assertEqual(binding['fields']['source'], hex(source))
                    result = checker.transfer_output(run, tx)
                    self.assertEqual((len(result), result[160:], tx['token']),
                                     (176, struct.pack('<2I', 0x141, 0) + bytes(8), 0))
                self.assertTrue(all('refresh_queue_binding' not in cycle for cycle in cycles
                                    if cycle['native_command'] != 0x141))
                later = next(row['fields'] for row in rows if row['tag'] == 'FUNCTIONAL_VDF_PATH_SEND' and
                             row['fields']['command'] == '0x152')
                self.assertEqual((later['refresh_queue_bound'], later['refresh_queue_source']), ('1', hex(source)))
                self.assertTrue(checker.check_frames(run, transport)['same_frame_RGB_consumer_verified'])
            if source == 0x80946189:
                storage = checker.writeback.inspect(run)
                self.assertTrue(checker.check_jpeg(rows, transport, storage, run)['storage_join_verified'])
                self.assertTrue(checker.check_video(rows, transport, storage, run)['raw_encoded_NAL_join_verified'])
                with mock.patch.object(checker, 'check_profile', return_value={'verified': True}), mock.patch.object(
                        checker, 'check_batch', return_value=(build, {})):
                    result = checker.evaluate(run, root / 'NO_FROZEN_BATCH')
                self.assertTrue(result['evidence']['transport']['verified'])
                self.assertFalse(result['capture_verified'])
                self.assertFalse(result['physical_asic_compatibility_verified'])

    def test_Refresh_binding_requires_complete_exact_receipt_and_readback(self):
        args = host_test_capture(self.root, (True, ('display', 0x141)), refresh_source=0x80946189)
        run, _, rows, _, _ = args
        transport = checker.check_transport(*args)
        receipt = next(row for row in rows if row['tag'] == 'FUNCTIONAL_VDF_REFRESH_QUEUE_BOUND')
        fields = receipt['fields']
        source = (checker.RUNTIME / 'menu-observe.c').read_text()
        producer = re.search(r'"(pid=%d tid=%ld caller_pc=%#lx global_va=%#lx[^"\n]+)"', source)
        self.assertIsNotNone(producer)
        self.assertIn('unsigned long global_va=command==0x141?0x910fa30UL:0x910fa20UL;', source)
        self.assertEqual(set(re.findall(r'([A-Za-z_][A-Za-z_0-9]*)=', producer.group(1))), set(fields))
        full_prefix = 'FUNCTIONAL_VDF_REFRESH_QUEUE_BOUND '
        self.assertIn('record(command==0x141?"' + full_prefix + '":"FUNCTIONAL_HISTOGRAM_QUEUE_BOUND ",text);', source)
        mirrored = source.split('static const char *mirrored[] = {', 1)[1].split('};', 1)[0]
        self.assertTrue(any(full_prefix.startswith(prefix) for prefix in re.findall(r'"([^"]+)"', mirrored)))
        observed, = checker.parse_console(('OBS ' + full_prefix + ' '.join(f'{key}={value}' for key, value in fields.items()) + '\n').encode())
        self.assertEqual((observed['tag'], observed['fields']), (receipt['tag'], fields))
        for key in fields:
            changed = copy.deepcopy(rows)
            del next(row['fields'] for row in changed if row['line'] == receipt['line'])[key]
            with self.subTest(missing=key), self.assertRaisesRegex(ValueError, 'binding producer grammar'):
                checker.check_vdf_path(run, changed, transport)
        mutations = (('pid', '0'), ('pid', '78'), ('pid', str(2**31)), ('tid', '0'), ('tid', '91'),
                     ('tid', '-1'), ('tid', str(2**31)), ('caller_pc', '0'),
                     ('caller_pc', hex(int(fields['caller_pc'], 16) + 4)),
                     ('caller_pc', str(int(fields['caller_pc'], 16))), ('global_va', '0x910fa34'),
                     ('global_address', hex(int(fields['global_address'], 16) + 4)),
                     ('source', '0'), ('source', '0xffffffff'), ('source', '0x92840747'),
                     ('source', '0x8094618a'), ('source', '0x100000000'), ('source', '0x080946189'),
                     ('source', '0x8094618A'), ('first', '0'), ('first', '0x89619480'),
                     ('second', '0x8094618a'), ('read_before', '0'), ('read_before', '3'),
                     ('read_before', '8'), ('read_before', '-1'), ('read_after', '3'), ('read_after', '-1'),
                     ('read_after', '04'), ('bind_rc', '-116'), ('bind_rc', '1'), ('source_match', '0'),
                     ('readback_verified', '0'), ('capture_verified', '1'), ('extra', '1'))
        for key, wrong in mutations:
            changed = copy.deepcopy(rows)
            next(row['fields'] for row in changed if row['line'] == receipt['line'])[key] = wrong
            with self.subTest(field=key, wrong=wrong), self.assertRaises(ValueError):
                checker.check_vdf_path(run, changed, transport)
        for source in (0, 0xffffffff, 0x92840747):
            changed, txs = copy.deepcopy(rows), copy.deepcopy(transport)
            observation = next(row['fields'] for row in changed if row['line'] == receipt['line'])
            observation.update({key: '0' if source == 0 else hex(source) for key in ('source', 'first', 'second')})
            next(tx for tx in txs['transfers'] if tx['opcode'] == 8)['origin']['source'] = source
            with self.subTest(invalid_bound_ID=source), self.assertRaisesRegex(ValueError, 'global/request source'):
                checker.check_vdf_path(run, changed, txs)

    def test_Refresh_binding_every_native_snapshot_must_use_exact_bound_source(self):
        args = host_test_capture(self.root, (True, ('display', 0x141)), refresh_source=0x80946189)
        run, _, rows, _, _ = args
        transport = checker.check_transport(*args)
        for tag in ('REQUEST_FREE', 'SEND', 'COMPLETE', 'RECEIVE', 'AP_FREE'):
            target = next(row for row in rows if row['tag'] == 'FUNCTIONAL_VDF_PATH_' + tag and row['fields']['command'] == '0x141')
            for key, wrong in (('refresh_queue_bound', '0'), ('refresh_queue_bound', '2'),
                               ('refresh_queue_source', '0'), ('refresh_queue_source', '0x81cf61c9'),
                               ('source', '0x81cf61c9')):
                changed = copy.deepcopy(rows)
                next(row['fields'] for row in changed if row['line'] == target['line'])[key] = wrong
                with self.subTest(tag=tag, field=key, wrong=wrong), self.assertRaises(ValueError):
                    checker.check_vdf_path(run, changed, transport)
            for key in ('refresh_queue_bound', 'refresh_queue_source'):
                changed = copy.deepcopy(rows)
                del next(row['fields'] for row in changed if row['line'] == target['line'])[key]
                with self.subTest(tag=tag, missing=key), self.assertRaises(checker.MissingEvidence):
                    checker.check_vdf_path(run, changed, transport)
        # Non-refresh legacy rows still need neither snapshot fields nor a binding receipt.
        legacy = [row for row in rows if row['tag'] != 'FUNCTIONAL_VDF_REFRESH_QUEUE_BOUND' and
                  row['fields'].get('command') != '0x141']
        for row in legacy:
            for key in ('refresh_queue_bound', 'refresh_queue_source'):
                row['fields'].pop(key, None)
        older = dict(transport, transfers=[tx for tx in transport['transfers'] if tx['origin']['command'] != 0x141])
        self.assertTrue(checker.check_vdf_path(run, legacy, older)['verified'])

    def test_Refresh_binding_receipts_are_unique_ordered_and_cannot_be_borrowed(self):
        args = host_test_capture(self.root, (True, ('display', 0x141), ('display', 0x141)), refresh_source=0x80946189)
        run, _, rows, _, _ = args
        transport = checker.check_transport(*args)
        receipts = [row for row in rows if row['tag'] == 'FUNCTIONAL_VDF_REFRESH_QUEUE_BOUND']
        refreshes = [tx for tx in transport['transfers'] if tx['opcode'] == 8]
        for receipt in receipts:
            changed = [row for row in rows if row['line'] != receipt['line']]
            with self.subTest(missing_line=receipt['line']), self.assertRaises(checker.MissingEvidence):
                checker.check_vdf_path(run, changed, transport)
        with self.assertRaisesRegex(ValueError, 'census'):
            checker.check_vdf_path(run, rows + [copy.deepcopy(receipts[0])], transport)
        previous_free = transport['VDF_path']['cycles'][1]['free_line']
        for receipt, line in ((receipts[0], refreshes[0]['line']), (receipts[0], refreshes[0]['line'] + 1),
                              (receipts[1], receipts[0]['line']), (receipts[1], previous_free),
                              (receipts[1], refreshes[1]['line'] + 1)):
            changed = copy.deepcopy(rows)
            next(row for row in changed if row['line'] == receipt['line'])['line'] = line
            with self.subTest(receipt=receipt['line'], moved_line=line), self.assertRaisesRegex(ValueError, 'first model/owned'):
                checker.check_vdf_path(run, changed, transport)
        changed = copy.deepcopy(transport)
        early = dict(refreshes[0], opcode=1, line=receipts[0]['line'] - 1)
        changed['transfers'].insert(changed['transfers'].index(refreshes[0]), early)
        with mock.patch.object(checker, 'vdf_history', return_value=checker.vdf_history(run, transport)), self.assertRaisesRegex(
                ValueError, 'first model/owned'):
            checker.check_vdf_path(run, rows, changed)
        for tag in ('FUNCTIONAL_VDF_REFRESH_QUEUE_BOUND_EXTRA', 'FUNCTIONAL_VDF_REFRESH_QUEUE_FAILED',
                    'FUNCTIONAL_VDF_PATH_REFRESH_QUEUE_BOUND', 'FUNCTIONAL_VDF_DIAGNOSTIC_EXTRA'):
            changed = rows + [dict(receipts[0], tag=tag)]
            with self.subTest(unknown_tag=tag), self.assertRaisesRegex(ValueError, 'unknown VDF'):
                checker.check_vdf_path(run, changed, transport)
        for raw in (b'OBS FUNCTIONAL_VDF_REFRESH_QUEUE_BOUND read-failed\n',
                    b'OBS FUNCTIONAL_VDF_REFRESH_QUEUE_BOUND pid=77 tid=90\n'):
            changed = rows + checker.parse_console(raw)
            with self.subTest(failed_record=raw), self.assertRaises(ValueError):
                checker.check_vdf_path(run, changed, transport)
        for raw in (b'OBS FUNCTIONAL_VDF_REFRESH_QUEUE_BOUND source=0x80946189 source=0x80946189\n',
                    b'OBS FUNCTIONAL_VDF_REFRESH_QUEUE_BOUND pid=77'):
            with self.subTest(malformed_record=raw), self.assertRaises(ValueError):
                checker.parse_console(raw)
        other = dict(transport, transfers=[tx for tx in transport['transfers'] if tx['origin']['command'] != 0x141])
        with self.assertRaisesRegex(ValueError, 'census'):
            checker.check_vdf_path(run, [row for row in rows if row['fields'].get('command') != '0x141'], other)
        with self.assertRaises(checker.MissingEvidence):
            checker.check_vdf_path(run, receipts, dict(transport, transfers=[]))

    def test_Refresh_binding_is_immutable_and_never_authorizes_other_five_commands(self):
        args = host_test_capture(self.root, REFRESH_PATHS + (('display', 0x141),), refresh_source=0x80946189)
        run, _, rows, _, _ = args
        transport = checker.check_transport(*args)
        changed_rows, changed = copy.deepcopy(rows), copy.deepcopy(transport)
        late = [tx for tx in changed['transfers'] if tx['opcode'] == 8 and tx['origin']['command'] == 0x141][-1]
        late['origin']['source'] = 0x80abcd12
        receipt = [row for row in changed_rows if row['tag'] == 'FUNCTIONAL_VDF_REFRESH_QUEUE_BOUND'][-1]
        receipt['fields'].update({key: '0x80abcd12' for key in ('source', 'first', 'second')})
        cycle = str(transport['VDF_path']['cycles'][-1]['cycle'])
        for row in changed_rows:
            if row['tag'].startswith('FUNCTIONAL_VDF_PATH_') and row['fields'].get('cycle') == cycle:
                row['fields'].update(source='0x80abcd12', refresh_queue_source='0x80abcd12')
        with self.assertRaisesRegex(ValueError, 'immutable global source changed'):
            checker.check_vdf_path(run, changed_rows, changed)
        for command in (0x138, 0x153, 0x14c, 0x152, 0x162):
            changed = copy.deepcopy(transport)
            next(tx for tx in changed['transfers'] if tx['opcode'] in checker.VDF_OPERATIONS and
                 tx['origin']['command'] == command)['origin']['source'] = 0x80946189
            with self.subTest(other_native_command=hex(command)), self.assertRaisesRegex(ValueError, 'original caller/SID/command'):
                checker.check_vdf_path(run, rows, changed)

    def test_Refresh_binding_cannot_replace_RGB_retire_or_actual_AP_free(self):
        args = host_test_capture(self.root, (True, ('display', 0x141)), refresh_source=0x80946189)
        run, _, rows, _, _ = args
        transport = checker.check_transport(*args)
        for key, wrong in (('consumer_entered', 0), ('consumer_returned', 0), ('consumer_after_fnv1a64', 1),
                           ('retired', 0), ('encoder_consumed', 1)):
            changed = copy.deepcopy(transport)
            next(tx['frame']['proof'] for tx in changed['transfers'] if tx['opcode'] == 8)[key] = wrong
            with self.subTest(proof=key), self.assertRaises(ValueError):
                checker.check_vdf_path(run, rows, changed)
        changed = copy.deepcopy(transport)
        next(tx for tx in changed['transfers'] if tx['opcode'] == 8)['frame'] = None
        with self.assertRaises(checker.MissingEvidence):
            checker.check_vdf_path(run, rows, changed)
        for tag in ('REQUEST_FREE', 'RECEIVE', 'AP_FREE'):
            changed = [row for row in rows if not (row['tag'] == 'FUNCTIONAL_VDF_PATH_' + tag and row['fields']['command'] == '0x141')]
            with self.subTest(missing=tag), self.assertRaises(checker.MissingEvidence):
                checker.check_vdf_path(run, changed, transport)
        for key, wrong in (('free_rc', '-1'), ('request_free_rc', '-1'), ('free_tid', '91'), ('AP_consumed', '0')):
            changed = copy.deepcopy(rows)
            next(row['fields'] for row in changed if row['tag'] == 'FUNCTIONAL_VDF_PATH_AP_FREE' and
                 row['fields']['command'] == '0x141')[key] = wrong
            with self.subTest(free_field=key), self.assertRaises(ValueError):
                checker.check_vdf_path(run, changed, transport)

    def test_Startup_three_local_stages_join_path_and_separate_actual_late_014c(self):
        args = host_test_capture(self.root, (True, LAYOUT_BODY32), startup_stages=3, late_apply=True)
        run, manifest, rows, _, build = args
        transport = checker.check_transport(*args)
        stages = transport['startup_layout_stage']
        self.assertEqual([item['stage_generation'] for item in stages['cycles']], [1, 2, 3])
        self.assertEqual([item['opcode'] for item in transport['VDF_path']['cycles']], [5, 7])
        self.assertEqual(transport['opcodes']['7'], 1)
        self.assertTrue(stages['verified'] and stages['late_application_verified'] and stages['owner_bound_to_mailbox'])
        self.assertEqual(stages['status'], 'staged-with-separate-late-op7')
        self.assertTrue(stages['stage_only'])
        for key in ('semantic_applied', 'frame_consumed', 'model_initialized', 'hardware_ready', 'capture_verified',
                    'physical_asic_compatibility_verified', 'original_CP_FIFO_verified', 'original_RTOS_verified'):
            self.assertIs(stages[key], False)
        application, = stages['applications']
        layout = next(tx for tx in transport['transfers'] if tx['opcode'] == 7)
        output = checker.transfer_output(run, layout)
        self.assertEqual(application['first'], layout['first'])
        self.assertEqual(application['result_fnv1a64'], f'{checker.fnv(output):016x}')
        self.assertEqual(output[160:], LAYOUT_BODY32)
        unapplied = checker.check_layout_stage(run, manifest,
            [row for row in rows if row['tag'] != 'FUNCTIONAL_LAYOUT_STAGE_APPLIED_RECEIPT'], transport)
        self.assertEqual(unapplied['status'], 'staged-unapplied')
        self.assertFalse(unapplied['late_application_verified'])
        self.assertEqual((application['config_generation'], application['frame_generation']), (4, 3))
        # The late original worker differs from the startup register/ACK worker.
        self.assertEqual(stages['applied_receipts'][0]['fields']['tid'], '90')
        self.assertEqual(stages['applied_receipts'][0]['fields']['sender_tid'], '88')
        frames = checker.check_frames(run, transport)
        self.assertEqual([job['opcode'] for job in frames['jobs'][:3]], [1, 5, 7])
        self.assertEqual(frames['last_counts'], dict(rendered=8, retired=8, consumed=7, jpeg_encoded=1, video_encoded=4))
        storage = checker.writeback.inspect(run)
        self.assertTrue(checker.check_jpeg(rows, transport, storage, run)['storage_join_verified'])
        self.assertEqual(checker.check_video(rows, transport, storage, run)['samples'], 4)
        with mock.patch.object(checker, 'check_profile', return_value={'verified': True}), mock.patch.object(
                checker, 'check_batch', return_value=(build, {})):
            verdict = checker.evaluate(run, self.root / 'HOST_TEST_unfrozen_batch')
        self.assertTrue(verdict['evidence']['startup_layout_stage']['late_application_verified'])
        self.assertFalse(verdict['capture_verified'])
        self.assertFalse(verdict['physical_asic_compatibility_verified'])
        # Freeze the full known source producer grammar without running or building it.
        source = (checker.RUNTIME / 'device-models/functional-vdf-layout-stage.c').read_text()
        producer = source.split('snprintf(text, sizeof text,', 1)[1].split('s.owner_pid', 1)[0]
        observed = next(row['fields'] for row in rows if row['tag'] == 'FUNCTIONAL_LAYOUT_STAGE_READBACK')
        self.assertEqual(set(re.findall(r'([A-Za-z_][A-Za-z_0-9]*)=', producer)), set(observed))

    def test_Startup_only_async_and_inline_register_ACK_never_supply_frame_or_initialization(self):
        for inline in (False, True):
            root = self.root / str(inline)
            root.mkdir()
            state = bytearray(128)
            struct.pack_into('<2I2I', state, 0, 1, 15, 24, 16)
            struct.pack_into('<2Q', state, 48, 99, 1)
            args = host_test_transport(root, [dict(op=1, data=b'', output=bytes(state))],
                                       console_prefix=layout_stage_observations(inline=inline))
            run, manifest, rows, _, _ = args
            transport = checker.check_transport(*args)
            stage = transport['startup_layout_stage']
            self.assertEqual(stage['status'], 'staged-unapplied')
            self.assertTrue(stage['verified'])
            self.assertFalse(stage['late_application_verified'])
            self.assertFalse(stage['model_initialized'])
            self.assertFalse(stage['frame_consumed'])
            self.assertEqual(stage['applied_receipts'], [])
            self.assertFalse(transport['VDF_path']['required'])
            self.assertNotIn('7', transport['opcodes'])
            with self.assertRaises(checker.MissingEvidence):
                checker.check_frames(run, transport)
            (run / 'functional-camera-broker-receipts.jsonl').unlink()
            verdict = checker.evaluate(run, root / 'HOST_TEST_unfrozen_batch')
            self.assertTrue(verdict['evidence']['startup_layout_stage']['verified'])
            self.assertFalse(verdict['evidence']['startup_layout_stage']['owner_bound_to_mailbox'])
            self.assertFalse(verdict['capture_verified'])
            self.assertFalse(verdict['products']['JPEG']['capture_verified'])
            self.assertFalse(verdict['products']['MP4']['capture_verified'])
        self.assertFalse(checker.check_layout_stage(None, {}, [])['required'])

    def test_Startup_policy_is_exact_typed_in_both_copies_only_when_stage_is_present(self):
        args = host_test_transport(self.root, console_prefix=layout_stage_observations(1))
        producer = checker.source_module(checker.RUNTIME / 'backup_profile.py')
        fields = producer.functional_camera_profile_fields(checker.PROFILE)
        self.assertTrue(all(checker.typed_equal(fields['functional_camera_' + key], value)
                            for key, value in checker.STARTUP_LAYOUT_POLICY.items()))
        for location in ('manifest', 'backup_transport'):
            for key, expected in checker.STARTUP_LAYOUT_POLICY.items():
                for invalid in ('missing', None, 0, 1, not expected if type(expected) is bool else expected + '-wrong'):
                    manifest = copy.deepcopy(args[1])
                    target = manifest if location == 'manifest' else manifest[location]
                    full_key = 'functional_camera_' + key
                    target.pop(full_key) if invalid == 'missing' else target.update({full_key: invalid})
                    with self.subTest(location=location, key=key, invalid=invalid), self.assertRaises(ValueError):
                        checker.check_layout_stage(args[0], manifest, args[2])
        self.assertFalse(checker.check_layout_stage(None, {'functional_camera_startup_layout_frame_completion': True}, [])['required'])

    def test_Startup_requires_complete_known_producer_grammar_and_rejects_unknown_fail_tags(self):
        args = host_test_transport(self.root, console_prefix=layout_stage_observations(1))
        original = args[2]
        for key in original[0]['fields']:
            rows = copy.deepcopy(original)
            del rows[0]['fields'][key]
            with self.subTest(missing=key), self.assertRaises(ValueError):
                checker.check_layout_stage(args[0], args[1], rows)
        for tag in ('FUNCTIONAL_LAYOUT_STAGE', 'FUNCTIONAL_LAYOUT_STAGE_FAULT', 'FUNCTIONAL_LAYOUT_STAGE_FAIL',
                    'FUNCTIONAL_LAYOUT_STAGE_UNKNOWN', 'FUNCTIONAL_LAYOUT_STAGE_APPLIED', 'FUNCTIONAL_LAYOUT_STAGES_READBACK',
                    'FUNCTIONAL_LAYOUT_STAGE_TICKET_RETAINED', 'FUNCTIONAL_LAYOUT_STAGE_BIND_FAILED'):
            rows = copy.deepcopy(original)
            rows[0]['tag'] = tag
            with self.subTest(tag=tag), self.assertRaises(ValueError):
                checker.check_layout_stage(args[0], args[1], rows)
        for extra in ('phase', 'ready', 'model_initialized', 'model_complete', 'model_instance', 'unknown'):
            rows = copy.deepcopy(original)
            rows[0]['fields'][extra] = '1'
            with self.subTest(extra=extra), self.assertRaises(ValueError):
                checker.check_layout_stage(args[0], args[1], rows)
        malformed = checker.parse_console(b'OBS FUNCTIONAL_LAYOUT_STAGE_READBACK bad prose\n')
        with self.assertRaises(ValueError):
            checker.check_layout_stage(args[0], args[1], malformed)
        duplicate = layout_stage_observations(1).replace('pid=77', 'pid=77 pid=77', 1)
        with self.assertRaises(ValueError):
            checker.parse_console(duplicate.encode())

    def test_Startup_wire_digests_owner_generations_and_original_free_states_fail_closed(self):
        args = host_test_transport(self.root, console_prefix=layout_stage_observations())
        changes = (('READBACK', 'raw', ('0d204c0128000180' + LAYOUT_BODY32.hex())[:-2] + '01'),
                   ('READBACK', 'bank32', bytes(32).hex()), ('READBACK', 'copied_readback32', bytes(32).hex()),
                   ('READBACK', 'original_fnv1a64', '0000000000000000'), ('READBACK', 'bank_fnv1a64', '0000000000000000'),
                   ('READBACK', 'readback_fnv1a64', '0000000000000000'), ('READBACK', 'stage_generation', '2'),
                   ('READBACK', 'pid', '78'), ('READBACK', 'tid', '89'), ('READBACK', 'sender_tid', '89'),
                   ('READBACK', 'source', '0x81cf61c6'), ('READBACK', 'source', '0x92840747'),
                   ('READBACK', 'destination', '0x81cf61c5'), ('READBACK', 'command', '0x138'),
                   ('READBACK', 'bytes', '32'), ('READBACK', 'request_retained', '(nil)'),
                   ('READBACK', 'request_retained', '0x500000'), ('READBACK', 'ack_retained', '0x500000'),
                   ('REQUEST_FREE', 'request_freed', '0'), ('REQUEST_FREE', 'request_free_rc', '-1'),
                   ('REQUEST_FREE', 'allocation_returned', '0x500001'), ('REQUEST_FREE', 'allocation_alias', '1'),
                   ('SEND', 'send_rc', '1'), ('SEND', 'queued', '0'), ('SEND', 'releasing', '1'),
                   ('RECEIVE', 'receiver_tid', '89'), ('AP_FREE', 'free_tid', '89'), ('AP_FREE', 'free_rc', '1'),
                   ('AP_FREE', 'AP_consumed', '0'), ('AP_FREE', 'completed_cycles', '0'),
                   ('AP_FREE', 'ack_retained', '0x500000'), ('AP_FREE', 'send_inflight', '1'),
                   ('COMPLETE', 'busy', '1'), ('COMPLETE', 'faults', '1'),
                   ('READBACK', 'pid', '077'), ('READBACK', 'source', '0X81cf61c5'),
                   ('READBACK', 'bank_fnv1a64', '0x00000000000000'), ('READBACK', 'cycle', str(2**64)),
                   ('READBACK', 'request_retained', '0x0500000'), ('READBACK', 'pid', 'true'))
        changes += tuple(('READBACK', key, '1') for key in ('semantic_applied', 'frame_consumed', 'hardware_ready',
                         'capture_verified', 'physical_ASIC_verified', 'original_CP_FIFO_verified', 'physical_CP_RTOS_verified'))
        changes += (('READBACK', 'stage_only', '0'), ('READBACK', 'bank_written', '0'),
                    ('READBACK', 'readback_verified', '0'), ('READBACK', 'applied_receipt_verified', '1'))
        for tag, key, invalid in changes:
            rows = copy.deepcopy(args[2])
            next(row for row in rows if row['tag'] == 'FUNCTIONAL_LAYOUT_STAGE_' + tag)['fields'][key] = invalid
            with self.subTest(tag=tag, key=key, invalid=invalid), self.assertRaises(ValueError):
                checker.check_layout_stage(args[0], args[1], rows)
        for ack in ('0d2038110c00018000005900', '0d2053110c00018000000000', '0d204c110c00018000000000',
                    '0d204c110c000180000059', '0d204c110c0001800000590000'):
            rows = copy.deepcopy(args[2])
            rows[0]['fields']['ack_wire'] = ack
            with self.subTest(ack=ack), self.assertRaises(ValueError):
                checker.check_layout_stage(args[0], args[1], rows)
        for missing in ('READBACK', 'REQUEST_FREE', 'SEND', 'COMPLETE', 'RECEIVE', 'AP_FREE'):
            rows = [row for row in args[2] if not (row['tag'] == 'FUNCTIONAL_LAYOUT_STAGE_' + missing and row['fields']['cycle'] == '1')]
            with self.subTest(missing=missing), self.assertRaises(ValueError):
                checker.check_layout_stage(args[0], args[1], rows)
        with self.assertRaises(ValueError):
            checker.check_layout_stage(args[0], args[1], args[2] + [args[2][0]])

    def test_Startup_late_apply_requires_exact_actual_192_RGB_retire_and_its_own_native_cycle(self):
        args = host_test_capture(self.root, (True, LAYOUT_BODY32), startup_stages=3, late_apply=True)
        transport = checker.check_transport(*args)
        run, manifest, rows, _, _ = args
        receipt = next(row for row in rows if row['tag'] == 'FUNCTIONAL_LAYOUT_STAGE_APPLIED_RECEIPT')
        for key, invalid in (('applied_receipt_verified', '0'), ('applied_stage_generation', '2'),
                             ('applied_model_instance', '100'), ('applied_config_generation', '5'),
                             ('applied_frame_generation', '4'), ('applied_result_fnv1a64', '0000000000000001'),
                             ('AP_consumed', '0'), ('free_tid', '90'), ('request_freed', '0'), ('tid', '91')):
            changed = copy.deepcopy(rows)
            next(row for row in changed if row['tag'] == receipt['tag'])['fields'][key] = invalid
            with self.subTest(key=key), self.assertRaises(ValueError):
                checker.check_layout_stage(run, manifest, changed, transport)
        with self.assertRaises(ValueError):
            checker.check_layout_stage(run, manifest, rows + [receipt], transport)
        layout = next(tx for tx in transport['transfers'] if tx['opcode'] == 7)
        for key, invalid in (('render_observed', 0), ('consumer_entered', 0), ('consumer_returned', 0),
                             ('retired', 0), ('retire_status', -5), ('consumer_status', -5), ('encoder_consumed', 1),
                             ('consumer_after_fnv1a64', 1), ('owner_pid', 178), ('model_instance', 100)):
            changed = copy.deepcopy(transport)
            next(tx for tx in changed['transfers'] if tx['opcode'] == 7)['frame']['proof'][key] = invalid
            with self.subTest(proof=key), self.assertRaises(ValueError):
                checker.check_layout_stage(run, manifest, rows, changed)
        changed = copy.deepcopy(transport)
        next(tx for tx in changed['transfers'] if tx['opcode'] == 7)['frame'] = None
        with self.assertRaises(checker.MissingEvidence):
            checker.check_layout_stage(run, manifest, rows, changed)
        for name in ('REQUEST_FREE', 'RECEIVE', 'AP_FREE'):
            missing = [row for row in rows if not (row['tag'] == 'FUNCTIONAL_VDF_PATH_' + name and row['fields']['command'] == '0x14c')]
            with self.subTest(missing_late=name), self.assertRaises(ValueError):
                checker.check_layout_stage(run, manifest, missing, transport)
            borrowed = copy.deepcopy(missing)
            early = copy.deepcopy(next(row for row in rows if row['tag'] == 'FUNCTIONAL_LAYOUT_STAGE_' + name))
            early['tag'] = 'FUNCTIONAL_VDF_PATH_' + name
            borrowed.append(early)
            with self.subTest(borrowed=name), self.assertRaises(ValueError):
                checker.check_layout_stage(run, manifest, borrowed, transport)
        original_output = checker.transfer_output
        for offset in (8, 16, 24, 40, 112, 116, 160, 191):
            forged = bytearray(original_output(run, layout))
            forged[offset] ^= 1
            changed = copy.deepcopy(rows)
            for row in changed:
                if row['tag'].startswith('FUNCTIONAL_VDF_PATH_') and row['fields'].get('command') == '0x14c':
                    row['fields']['model_result_hex'] = forged.hex()
                    row['fields']['model_result_fnv1a64'] = f'{checker.fnv(forged):016x}'
                if row['tag'] == receipt['tag']:
                    row['fields']['applied_result_fnv1a64'] = f'{checker.fnv(forged):016x}'
            with self.subTest(result192_offset=offset), mock.patch.object(checker, 'transfer_output',
                    side_effect=lambda root, tx: bytes(forged) if tx['first'] == layout['first'] else original_output(root, tx)), self.assertRaises(ValueError):
                checker.check_layout_stage(run, manifest, changed, transport)
        without_layout = dict(transport, transfers=[tx for tx in transport['transfers'] if tx['opcode'] != 7])
        with self.assertRaises(ValueError):
            checker.check_layout_stage(run, manifest, rows, without_layout)

    def test_Startup_distinct_late_original_014c_calls_keep_ordered_independent_apply_receipts(self):
        args = host_test_capture(self.root, (True, LAYOUT_BODY32, LAYOUT_BODY32), startup_stages=3,
                                 stage_inline=True, vdf_inline=True, late_apply=True)
        transport = checker.check_transport(*args)
        stages = transport['startup_layout_stage']
        self.assertTrue(stages['late_application_verified'])
        self.assertEqual([item['config_generation'] for item in stages['applications']], [4, 6])
        self.assertEqual([item['frame_generation'] for item in stages['applications']], [3, 4])
        self.assertEqual(transport['opcodes']['7'], 2)
        self.assertTrue(checker.check_frames(args[0], transport)['verified'])
        for mutation in ('reverse', 'equal-frame', 'foreign-instance'):
            rows = copy.deepcopy(args[2])
            applied = [row for row in rows if row['tag'] == 'FUNCTIONAL_LAYOUT_STAGE_APPLIED_RECEIPT']
            if mutation == 'reverse':
                applied[0]['fields'], applied[1]['fields'] = applied[1]['fields'], applied[0]['fields']
            elif mutation == 'equal-frame':
                applied[1]['fields']['applied_frame_generation'] = applied[0]['fields']['applied_frame_generation']
            else:
                applied[1]['fields']['applied_model_instance'] = '100'
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                checker.check_layout_stage(args[0], args[1], rows)

    def test_Startup_rejects_wrong_phase_foreign_mailbox_and_early_applied_receipt(self):
        args = host_test_capture(self.root, (True, LAYOUT_BODY32), startup_stages=3, late_apply=True, stage_inline=True)
        transport = checker.check_transport(*args)
        run, manifest, rows, _, _ = args
        changed = copy.deepcopy(rows)
        for row in changed:
            if row['tag'].startswith('FUNCTIONAL_LAYOUT_STAGE_') and row['tag'] != 'FUNCTIONAL_LAYOUT_STAGE_APPLIED_RECEIPT':
                row['line'] += 10000
        with self.assertRaises(ValueError):
            checker.check_layout_stage(run, manifest, changed, transport)
        changed = copy.deepcopy(rows)
        next(row for row in changed if row['tag'] == 'FUNCTIONAL_LAYOUT_STAGE_APPLIED_RECEIPT')['line'] = 1
        with self.assertRaises(ValueError):
            checker.check_layout_stage(run, manifest, changed, transport)
        with self.assertRaises(ValueError):
            checker.check_layout_stage(run, manifest, rows, dict(transport, pid=78))

    def test_actual_chunk_reconstruction_and_missing_corrupt_payloads(self):
        output = b'HOST_TEST actual chunk ' * 4000
        operations = [dict(op=1, data=b'', output=bytes(128)),
                      dict(op=16, data=struct.pack('<4I', 1, 24, 16, 90), output=output)]
        args = list(host_test_transport(self.root, operations))
        result = checker.check_transport(*args)
        tx = result['transfers'][1]
        self.assertGreater(len(tx['output_payloads']), 1)
        self.assertEqual(checker.transfer_output(args[0], tx), output)
        self.assertEqual(tx['sha256'], checker.sha(output))
        path = args[0] / tx['output_payloads'][1]['path']
        original = path.read_bytes()
        path.write_bytes(original[:-1] + bytes([original[-1] ^ 1]))
        with self.assertRaises(ValueError):
            checker.check_transport(*args)
        path.unlink()
        with self.assertRaises((OSError, checker.MissingEvidence)):
            checker.check_transport(*args)

    def test_raw_READ_RESULT_cursor_or_RELEASE_RESULT_FNV_cannot_be_relabelled(self):
        output = b'HOST_TEST' * 10000
        args = list(host_test_transport(self.root, [dict(op=1, data=b'', output=bytes(128)),
                    dict(op=16, data=struct.pack('<4I', 1, 24, 16, 90), output=output)]))
        for op in (64, 65):
            changed = copy.deepcopy(args)
            request = next(row for row in changed[3] if row['kind'] == 'request' and row['opcode'] == op)
            request['request_payload']['offset'] += 1
            with self.subTest(op=op), self.assertRaises(ValueError):
                checker.check_transport(*changed)

    def test_actual_frame_RGB_or_generation_or_counter_corruption(self):
        args, transport, _ = self.capture()
        for key in ('consumer_before_fnv1a64', 'config_generation', 'frame_generation', 'lease_generation', 'model_lifetime'):
            changed = copy.deepcopy(transport)
            proof = next(tx['frame']['proof'] for tx in changed['transfers'] if tx['opcode'] == 16)
            proof[key] = 0
            with self.subTest(key=key), self.assertRaises(ValueError):
                checker.check_frames(args[0], changed)
        changed = copy.deepcopy(transport)
        next(tx['frame']['proof'] for tx in changed['transfers'] if tx['opcode'] == 16)['after']['consumed'] += 1
        with self.assertRaises(ValueError):
            checker.check_frames(args[0], changed)
        changed = copy.deepcopy(transport)
        next(tx for tx in changed['transfers'] if tx['opcode'] == 33)['frame'] = None
        with self.assertRaises(checker.MissingEvidence):
            checker.check_frames(args[0], changed)

    def test_Main0_original_Comp_and_free_chain_with_real_writeback(self):
        args = host_test_capture(self.root, jpeg_main=True)
        transport = checker.check_transport(*args)
        checker.check_frames(args[0], transport)
        storage = checker.writeback.inspect(args[0])
        result = checker.check_jpeg(args[2], transport, storage, args[0])
        self.assertEqual([(job['kind'], job['selector']) for job in result['jobs']], [('main', 0)])
        self.assertTrue(result['actual_reply_free_verified'])
        self.assertFalse(result['cross_selector_same_sensor_frame_verified'])
        self.assertFalse(result['screen_MPF_layout_verified'])

    def test_Main0_Thumb1_share_original_JPEG_with_bounded_real_EXIF_both_endians(self):
        from PIL import Image
        for endian in ('II', 'MM'):
            directory = self.root / endian
            directory.mkdir()
            args = host_test_capture(directory, jpeg_main=True, jpeg_thumb=True, jpeg_endian=endian)
            transport = checker.check_transport(*args)
            checker.check_frames(args[0], transport)
            storage = checker.writeback.inspect(args[0])
            result = checker.check_jpeg(args[2], transport, storage, args[0])
            primary, thumb = result['jobs']
            self.assertEqual((primary['selector'], thumb['selector']), (0, 1))
            self.assertEqual(primary['path'], thumb['path'])
            self.assertEqual(thumb['primary_sequence'], primary['sequence'])
            item = next(item for item in storage['items'] if item['path'] == thumb['path'])
            embedded = checker.exif_thumbnail(checker.stored_bytes(storage, item))
            image = Image.open(io.BytesIO(embedded['bytes']))
            image.load()
            self.assertEqual(image.size, (160, 120))
            self.assertEqual(len(result['jobs']), 2)
            self.assertFalse(thumb['cross_selector_same_sensor_frame_verified'])

    def test_MainComp_free_source_closed_fields_cannot_drift(self):
        args = host_test_capture(self.root, jpeg_main=True, jpeg_thumb=True)
        transport = checker.check_transport(*args)
        storage = checker.writeback.inspect(args[0])
        cases = [('original-request', 'kind', 'fake-main'), ('original-request', 'selector', '3'),
                 ('original-request', 'exec_entry', '0x21b654'),
                 ('original-rescmd-ack', 'original_result', '0x200'),
                 ('original-rescmd-ack', 'terminal', '1'), ('original-rescmd-ack', 'lease_released', '1'),
                 ('original-rescmd-ack', 'response_address', '0xc001'),
                 ('original-maincomp-exec', 'comp_object', '0x8100'),
                 ('original-maincomp-exec', 'comp_exec_entry', '0x2226c4'),
                 ('original-maincomp-exec', 'comp_caller', '0x23b6ec'),
                 ('original-maincomp-exec', 'previous_ack_address', '0xc001'),
                 ('original-maincomp-exec', 'previous_ack_hex', '00' * 16),
                 ('original-maincomp-exec', 'original_result', '1'),
                 ('original-maincomp-exec', 'tid', '82'), ('original-maincomp-exec', 'pid', '78'),
                 ('original-maincomp-exec', 'manager', '0x9001'), ('original-maincomp-exec', 'control', '0xa001'),
                 ('original-maincomp-exec', 'context', '2'), ('original-maincomp-exec', 'selector', '1'),
                 ('original-maincomp-exec', 'native_config', '0xd001'),
                 ('original-maincomp-config', 'config_length_offset', '104'),
                 ('original-maincomp-config', 'actual_length', '0'),
                 ('original-maincomp-config', 'expected_length', '0'),
                 ('original-maincomp-config', 'original_result', '1'),
                 ('original-rescmd-done', 'res_entry', '0x220e64'),
                 ('original-freed-ack', 'free_rc', '1'), ('original-freed-done', 'free_rc', '-77'),
                 ('original-freed-done', 'reply_address', '0xb001'),
                 ('original-freed-done', 'reply_hex', '00' * 40),
                 ('original-freed-done', 'receiver_tid', '82'), ('original-freed-done', 'response_source', '0x82830753'),
                 ('original-freed-done', 'response_destination', '0x802a0117'),
                 ('original-freed-done', 'lease_generation', '2'), ('original-freed-done', 'lease_token', '0x102')]
        for operation, key, value in cases:
            rows = copy.deepcopy(args[2])
            event = next(row for row in rows if row['tag'] == 'FUNCTIONAL_JPEG_CODEC' and
                         row['fields']['sequence'] == '1' and row['fields']['operation'] == operation)
            event['fields'][key] = value
            with self.subTest(operation=operation, key=key), self.assertRaises(ValueError):
                checker.check_jpeg(rows, transport, storage, args[0])
        for operation in ('original-maincomp-exec', 'original-maincomp-config', 'original-freed-ack', 'original-freed-done'):
            rows = [row for row in args[2] if not (row['tag'] == 'FUNCTIONAL_JPEG_CODEC' and row['fields']['operation'] == operation)]
            with self.subTest(missing=operation), self.assertRaises(checker.MissingEvidence):
                checker.check_jpeg(rows, transport, storage, args[0])
        for key in ('kind', 'selector', 'comp_object'):
            rows = copy.deepcopy(args[2])
            del next(row for row in rows if row['tag'] == 'FUNCTIONAL_JPEG_CODEC' and
                     row['fields']['operation'] == 'original-request')['fields'][key]
            with self.subTest(missing=key), self.assertRaises(ValueError):
                checker.check_jpeg(rows, transport, storage, args[0])
        rows = copy.deepcopy(args[2])
        free = next(row for row in rows if row['tag'] == 'FUNCTIONAL_JPEG_CODEC' and row['fields']['operation'] == 'original-freed-ack')
        free['line'] = 1
        with self.assertRaises(ValueError):
            checker.check_jpeg(rows, transport, storage, args[0])

    def test_EXIF_TIFF_malformed_type_count_endian_offsets_duplicates_and_spans(self):
        from PIL import Image
        output = io.BytesIO()
        Image.new('RGB', (160, 120), 'blue').save(output, format='JPEG')
        primary, thumb = independent_media('JPEG'), output.getvalue()
        raw = host_test_exif(primary, thumb)
        self.assertEqual(checker.exif_thumbnail(raw)['bytes'], thumb)
        for offset, value in ((12, b'XX'), (12, b'MM'), (14, b'\0\0'), (16, struct.pack('<I', 0xffffffff)),
                              (20, b'\xff\xff'), (22, struct.pack('<I', 8)), (26, b'\x03\0'),
                              (30, struct.pack('<H', 3)), (32, struct.pack('<I', 2)),
                              (36, struct.pack('<I', 0xffffffff)), (36, struct.pack('<I', 14)),
                              (40, struct.pack('<H', 0x201)), (42, struct.pack('<H', 3)),
                              (44, struct.pack('<I', 0)), (48, struct.pack('<I', 0xffffffff)),
                              (48, struct.pack('<I', len(thumb) - 1)), (52, struct.pack('<I', 14))):
            changed = raw[:offset] + value + raw[offset + len(value):]
            with self.subTest(offset=offset, value=value.hex()), self.assertRaises(ValueError):
                checker.exif_thumbnail(changed)
        app_end = 4 + int.from_bytes(raw[4:6], 'big')
        duplicate = raw[:2] + raw[2:app_end] + raw[2:]
        with self.assertRaisesRegex(ValueError, 'duplicate'):
            checker.exif_thumbnail(duplicate)
        with self.assertRaises(checker.MissingEvidence):
            checker.exif_thumbnail(primary[:2] + b'\xff\xfe' + struct.pack('>H', len(thumb) + 2) + thumb + primary[2:])

    def test_Thumb_requires_same_file_Main_source_config_and_exact_embedded_bytes(self):
        args = host_test_capture(self.root, jpeg_main=True, jpeg_thumb=True)
        transport = checker.check_transport(*args)
        storage = checker.writeback.inspect(args[0])
        for key, value in (('control', '0xa001'), ('context', '2')):
            rows = copy.deepcopy(args[2])
            for row in rows:
                if row['tag'] == 'FUNCTIONAL_JPEG_CODEC' and row['fields']['sequence'] == '2':
                    row['fields'][key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                checker.check_jpeg(rows, transport, storage, args[0])
        rows = [row for row in args[2] if not (row['tag'] == 'FUNCTIONAL_JPEG_CODEC' and row['fields']['sequence'] == '1')]
        with self.assertRaises(ValueError):
            checker.check_jpeg(rows, transport, storage, args[0])
        changed = copy.deepcopy(storage)
        next(item for item in changed['items'] if item['decode']['format'] == 'JPEG')['areas'] = []
        with self.assertRaises(checker.MissingEvidence):
            checker.check_jpeg(args[2], transport, changed, args[0])
        item = next(item for item in storage['items'] if item['decode']['format'] == 'JPEG')
        path = Path(storage['exports']['host_directory']) / item['path']
        raw = path.read_bytes()
        thumb = checker.exif_thumbnail(raw)
        mutated = bytearray(raw)
        scan = thumb['offset'] + thumb['parts']['scan_offset']
        mutated[scan + 14] ^= 1
        path.write_bytes(mutated)
        item.update(bytes=len(mutated), sha256=checker.sha(mutated), fnv1a64=f'{checker.fnv(mutated):016x}')
        with self.assertRaises(ValueError):
            checker.check_jpeg(args[2], transport, storage, args[0])

    def test_Thumb_cannot_be_joined_from_another_original_file(self):
        from PIL import Image
        args = host_test_capture(self.root, jpeg_main=True, jpeg_thumb=True)
        transport = checker.check_transport(*args)
        storage = checker.writeback.inspect(args[0])
        item = next(item for item in storage['items'] if item['decode']['format'] == 'JPEG')
        host = Path(storage['exports']['host_directory'])
        path = host / item['path']
        raw = path.read_bytes()
        embedded = checker.exif_thumbnail(raw)['bytes']
        end = 4 + int.from_bytes(raw[4:6], 'big')
        primary_only = raw[:2] + raw[end:]
        path.write_bytes(primary_only)
        item.update(bytes=len(primary_only), sha256=checker.sha(primary_only), fnv1a64=f'{checker.fnv(primary_only):016x}')
        other = io.BytesIO()
        Image.new('RGB', (24, 16), 'red').save(other, format='JPEG')
        separate = host_test_exif(other.getvalue(), embedded)
        second = copy.deepcopy(item)
        second.update(path='DCIM/HOST_TEST_OTHER.JPG', bytes=len(separate), sha256=checker.sha(separate),
                      fnv1a64=f'{checker.fnv(separate):016x}')
        (host / second['path']).write_bytes(separate)
        storage['items'].append(second)
        with self.assertRaisesRegex(ValueError, 'one-to-one|same-file'):
            checker.check_jpeg(args[2], transport, storage, args[0])

    def test_Main_source_raw_geometry_quality_S0I_and_Screen_layout_fail_closed(self):
        args = host_test_capture(self.root, jpeg_main=True)
        transport = checker.check_transport(*args)
        storage = checker.writeback.inspect(args[0])
        request = next(row['fields'] for row in args[2] if row['tag'] == 'FUNCTIONAL_JPEG_CODEC' and
                       row['fields']['operation'] == 'original-request')
        original = bytes.fromhex(request['request_hex'])
        for offset, value in ((0x40, b'\0\0'), (0x42, b'\0\0'), (0x44, b'\0\0'), (0x46, b'\0\0'),
                              (0x44, struct.pack('<H', 23)), (0x44, struct.pack('<H', 8193)),
                              (0x49, b'\x03'), (0x49, b'\x04'), (0x49, b'\x05'), (0x49, b'\x07'),
                              (0x4b, b'\x01'), (0x4c, b'\x01'), (0x4d, b'\x01'),
                              (0x0e, b'\x11\x83'), (0x14, b'\x01\0')):
            rows, changed = copy.deepcopy(args[2]), copy.deepcopy(transport)
            wire = original[:24 + offset] + value + original[24 + offset + len(value):]
            digest = f'{checker.fnv(wire):016x}'
            for row in rows:
                if row['tag'] == 'FUNCTIONAL_JPEG_CODEC':
                    row['fields']['trigger_fnv'] = digest
                    if row['fields']['operation'] == 'original-request':
                        row['fields']['request_hex'] = wire.hex()
            next(tx for tx in changed['transfers'] if tx['opcode'] == 16)['origin']['fnv1a64'] = checker.fnv(wire)
            with self.subTest(offset=offset, value=value.hex()), self.assertRaises(ValueError):
                checker.check_jpeg(rows, changed, storage, args[0])
        rows, changed = copy.deepcopy(args[2]), copy.deepcopy(transport)
        wire = bytearray(original)
        wire[24 + 0x49] = 3
        digest = f'{checker.fnv(wire):016x}'
        for row in rows:
            if row['tag'] == 'FUNCTIONAL_JPEG_CODEC':
                fields = row['fields']
                fields.update(selector='2', trigger_fnv=digest)
                if 'config_length_offset' in fields:
                    fields['config_length_offset'] = str(0x74)
                if fields['operation'] == 'original-request':
                    fields['request_hex'] = wire.hex()
        next(tx for tx in changed['transfers'] if tx['opcode'] == 16)['origin']['fnv1a64'] = checker.fnv(wire)
        with self.assertRaisesRegex(checker.MissingEvidence, 'Screen selector2 original MPF/layout'):
            checker.check_jpeg(rows, changed, storage, args[0])

    def test_original_JPEG_range_request_ResCmd_and_receiver_negatives(self):
        args, transport, storage = self.capture()
        for operation, key, value in (('original-request-lease', 'lease_offset', '1'),
                                      ('output-readback', 'model_offset', '2'),
                                      ('original-rescmd-done', 'original_result', '0x200'),
                                      ('original-rescmd-done', 'receiver_tid', '82'),
                                      ('original-request', 'request_hex', '00' * 104)):
            rows = copy.deepcopy(args[2])
            event = next(row for row in rows if row['tag'] == 'FUNCTIONAL_JPEG_CODEC' and row['fields']['operation'] == operation)
            event['fields'][key] = value
            with self.subTest(operation=operation, key=key), self.assertRaises(ValueError):
                checker.check_jpeg(rows, transport, storage, args[0])
        rows = [row for row in args[2] if not (row['tag'] == 'FUNCTIONAL_JPEG_CODEC' and
                                               row['fields']['operation'] == 'original-received-done')]
        with self.assertRaises(checker.MissingEvidence):
            checker.check_jpeg(rows, transport, storage, args[0])

    def test_original_video_receiver_PI_and_NAL_negative_stages(self):
        args, transport, storage = self.capture()
        for tag, key, value in (('FUNCTIONAL_MPR_EVENT_FREE', 'receiver_tid', '82'),
                                ('FUNCTIONAL_MPR_EVENT_RECEIVED', 'request_seq', '99'),
                                ('FUNCTIONAL_MPR_PI_PUBLISH', 'slot_generation', '2'),
                                ('FUNCTIONAL_MPR_PI_RETURN', 'read_after', '1'),
                                ('FUNCTIONAL_MPR_PI_RETURN', 'info_hex', '00' * 96),
                                ('FUNCTIONAL_MPR_ES', 'nal_payload_fnv', '0'),
                                ('FUNCTIONAL_MPR_ES', 'source_offset', '0'),
                                ('FUNCTIONAL_MPR_PACKET', 'memory_generation', '2')):
            rows = copy.deepcopy(args[2])
            next(row for row in rows if row['tag'] == tag)['fields'][key] = value
            with self.subTest(tag=tag, key=key), self.assertRaises(ValueError):
                checker.check_video(rows, transport, storage, args[0])
        for tag in ('FUNCTIONAL_MPR_PI_RETURN', 'FUNCTIONAL_MPR_EVENT_FREE', 'FUNCTIONAL_MPR_REQUEST'):
            rows = copy.deepcopy(args[2])
            rows.remove(next(row for row in rows if row['tag'] == tag))
            with self.subTest(missing=tag), self.assertRaises(ValueError):
                checker.check_video(rows, transport, storage, args[0])

    def test_JPEG_metadata_may_change_but_coding_or_entropy_may_not(self):
        args, transport, storage = self.capture()
        item = next(item for item in storage['items'] if item['decode']['format'] == 'JPEG')
        path = Path(storage['exports']['host_directory']) / item['path']
        raw = path.read_bytes()
        metadata = b'\xff\xfe\x00\x0bHOST_TEST'
        transformed = raw[:2] + metadata + raw[2:]
        path.write_bytes(transformed)
        item.update(bytes=len(transformed), sha256=checker.sha(transformed), fnv1a64=f'{checker.fnv(transformed):016x}')
        self.assertTrue(checker.check_jpeg(args[2], transport, storage, args[0])['storage_join_verified'])
        changed = bytearray(transformed)
        scan = checker.jpeg_parts(changed)['scan_offset']
        changed[scan + 14] ^= 1
        path.write_bytes(changed)
        item.update(sha256=checker.sha(changed), fnv1a64=f'{checker.fnv(changed):016x}')
        with self.assertRaises(checker.MissingEvidence):
            checker.check_jpeg(args[2], transport, storage, args[0])

    def test_ordered_MP4_sample_NAL_payload_mutation_fails(self):
        args, transport, storage = self.capture()
        item = next(item for item in storage['items'] if item['decode']['format'] == 'MP4')
        path = Path(storage['exports']['host_directory']) / item['path']
        raw = bytearray(path.read_bytes())
        sample = checker.mp4_samples(raw)['extents'][0]
        raw[sample[1] - 1] ^= 1
        path.write_bytes(raw)
        item.update(sha256=checker.sha(raw), fnv1a64=f'{checker.fnv(raw):016x}')
        with self.assertRaises(checker.MissingEvidence):
            checker.check_video(args[2], transport, storage, args[0])

    def test_native_final_Close_and_final_runner_receipt_required(self):
        args, transport, storage = self.capture()
        rows = [row for row in args[2] if not (row['tag'] == 'FUNCTIONAL_MPR_OPERATION' and row['fields']['command'] == '4')]
        with self.assertRaises(checker.MissingEvidence):
            checker.check_video(rows, transport, storage, args[0])
        args[1]['functional_camera_runtime']['phase'] = 'ready'
        (args[0] / 'functional-camera-runner.json').write_text(json.dumps(args[1]['functional_camera_runtime']))
        with self.assertRaises(ValueError):
            checker.check_transport(*args)

    def test_current_batch_graph_API_refuses_unfrozen_or_old_receipts(self):
        with self.assertRaises(checker.MissingEvidence):
            checker.check_graph(self.root, self.root / 'NO_CURRENT_BATCH', {})
        graph_path = checker.NATIVE / 'report/functional-graph-evidence/check_graph.py'
        if graph_path.exists():
            source = checker.source_module(graph_path)
            result = source.evaluate(self.root, self.root / 'NO_CURRENT_BATCH')
            self.assertFalse(result['graph_verified'])
            self.assertFalse(result['all_13_graph_edges_complete'])
            self.assertTrue(result['missing'])
        with self.assertRaises(ValueError):
            checker.check_batch(self.root, self.root, {})

    def test_verdict_gate_needs_both_products_and_rejects_HOST_TEST(self):
        def assembled():
            return dict(evidence={name: dict(verified=True, capture_verified=True) for name in
                                   ('profile', 'batch', 'transport', 'CMOS_encoder', 'graph', 'JPEG_causality', 'MP4_causality')},
                        missing=[], products={kind: dict(writeback_verified=True, independent_decoded=True,
                                                        functional_codec_verified=True) for kind in ('JPEG', 'MP4')})
        for evidence_class in ('HOST_TEST', 'NATIVE_PARSER_TEST'):
            with self.subTest(evidence_class=evidence_class):
                value = checker.finish_verdict(assembled(), {'evidence_class': evidence_class})
                self.assertFalse(value['capture_verified'])
        value = assembled()
        value['products']['MP4']['independent_decoded'] = False
        self.assertFalse(checker.finish_verdict(value, {})['capture_verified'])
        value = assembled()
        value['missing'].append(dict(code='TRACE_MISSING', stage='graph', detail='HOST_TEST missing graph'))
        self.assertFalse(checker.finish_verdict(value, {})['capture_verified'])
        # Pure verdict assembly only, never evaluate()/native evidence acceptance.
        self.assertTrue(checker.finish_verdict(assembled(), {})['capture_verified'])

    def test_QEMU_pin_is_actual_native_candidate_not_production_control(self):
        self.assertEqual(checker.QEMU_SHA256, 'a0d1bdd8a9aad822efe47f740a104972cac6ec1875265e8174b25349f54fee02')
        args = list(host_test_transport(self.root))
        args[3][0]['config']['qemu_sha256'] = 'e23589c44386c19417551c982e394b7a4e779f8e68a72f2964b705aca1e96c0d'
        with self.assertRaises(ValueError):
            checker.check_transport(*args)

    def test_duplicate_and_nonfinite_json_fail_closed(self):
        for raw in (b'{"rc":0,"rc":1}', b'{"nested":{"x":1,"x":2}}', b'{"x":NaN}', b'{"x":1e999}'):
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                checker.object_json(raw)

    def test_jsonl_truncation_sequence_and_duplicate_fields(self):
        for raw in (b'{"event":1}', b'{"event":2,"monotonic_ns":1}\n',
                    b'{"event":1,"event":1,"monotonic_ns":1}\n'):
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                checker.jsonl(raw)

    def test_unsigned_trace_numbers_accept_only_bounded_log_spellings(self):
        accepted = {'0': 0, '0x0': 0, '1': 1, '0x1': 1, '0xAb': 171,
                    str(2**64 - 1): 2**64 - 1, '0xffffffffffffffff': 2**64 - 1}
        for raw, expected in accepted.items():
            with self.subTest(raw=raw):
                self.assertEqual(checker.number(raw), expected)
        for raw in (None, False, 0, b'0', '', '-0', '-1', '+0', '00', '01',
                    '0x', '0x00', '0x01', '0X1', ' 0', '0 ', '0\n', '1.0',
                    '1_000', '0x1_0', '0xg', str(2**64), '0x10000000000000000'):
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                checker.number(raw)

    def test_console_duplicate_and_truncated_fields(self):
        for raw in (b'OBS FUNCTIONAL_CAMERA_TRANSFER error=0 error=1\n',
                    b'OBS FUNCTIONAL_CAMERA_TRANSFER error=0'):
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                checker.parse_console(raw)

    def test_symlink_and_hardlink_evidence_rejected(self):
        original = self.root / 'ordinary'
        original.write_bytes(b'HOST_TEST')
        (self.root / 'symbolic').symlink_to(original)
        os.link(original, self.root / 'hard')
        for name in ('symbolic', 'hard'):
            with self.subTest(name=name), self.assertRaises((OSError, ValueError)):
                checker.read(self.root, name)

    def test_archive_duplicate_escape_and_wrong_content(self):
        for names in (('safe', 'safe'), ('../escape',), ('safe',)):
            raw = io.BytesIO()
            with tarfile.open(fileobj=raw, mode='w:gz') as out:
                for name in names:
                    member = tarfile.TarInfo(name)
                    member.size = 9
                    out.addfile(member, io.BytesIO(b'HOST_TEST'))
            with self.subTest(names=names), self.assertRaises(ValueError):
                checker.archive(raw.getvalue(), {'safe': checker.sha(b'WRONG' if names == ('safe',) else b'HOST_TEST')})

    def test_current_field_transport_positive_bounded_replay(self):
        _, result = self.transport()
        self.assertTrue(result['verified'])
        self.assertEqual(result['requests'], 3)
        self.assertEqual(result['transfers'][1]['opcode'], 16)
        self.assertTrue(result['raw_payload_bytes_verified'])
        self.assertFalse(result['VDF_path']['required'])
        self.assertEqual(result['VDF_path']['cycles'], [])

    def test_actual_C_failure_rejected(self):
        args = list(host_test_transport(self.root))
        next(row for row in args[3] if row['kind'] == 'core_result')['actual_c_result'] = -5
        with self.assertRaises(ValueError):
            checker.check_transport(*args)

    def test_wrong_header_PID_or_instance_rejected(self):
        args = list(host_test_transport(self.root))
        event = next(row for row in args[3] if row['kind'] == 'request')
        raw = bytearray.fromhex(event['raw_header_hex'])
        struct.pack_into('<I', raw, 8, 88)
        event.update(raw_header_hex=raw.hex(), raw_header_sha256=checker.sha(raw))
        with self.assertRaises(ValueError):
            checker.check_transport(*args)

    def test_wrong_receiver_SID_rejected(self):
        args = list(host_test_transport(self.root))
        response = next(row for row in args[3] if row['kind'] == 'response')
        response['origin']['destination'] ^= 1
        with self.assertRaises(ValueError):
            checker.check_transport(*args)

    def test_mixed_run_rejected(self):
        args = list(host_test_transport(self.root))
        args[3][0]['config']['run'] = str(self.root / 'OTHER_RUN')
        with self.assertRaises(ValueError):
            checker.check_transport(*args)

    def test_replayed_request_rejected(self):
        args = list(host_test_transport(self.root))
        requests = [row for row in args[3] if row['kind'] == 'request']
        requests[1]['sequence'] = 1
        with self.assertRaises(ValueError):
            checker.check_transport(*args)

    def test_incomplete_actual_response_rejected(self):
        args = list(host_test_transport(self.root))
        args[3].remove(next(row for row in args[3] if row['kind'] == 'response'))
        with self.assertRaises(ValueError):
            checker.check_transport(*args)

    def test_unconsumed_result_or_bad_destination_rejected(self):
        args = list(host_test_transport(self.root))
        args[2][1]['fields']['destination_fnv'] = '0x1'
        with self.assertRaises(ValueError):
            checker.check_transport(*args)

    def test_unsafe_cleanup_rejected(self):
        args = list(host_test_transport(self.root))
        args[1]['functional_camera_runtime']['cleanup']['safe_to_close'] = False
        (args[0] / 'functional-camera-runner.json').write_text(json.dumps(args[1]['functional_camera_runtime']))
        with self.assertRaises(ValueError):
            checker.check_transport(*args)

    def test_typed_profile_cannot_promote_physical_flags(self):
        manifest = dict(backup_transport={}, functional_camera_physical_ASIC_compatibility_verified=True)
        with self.assertRaises(ValueError):
            checker.check_profile(manifest)
        self.assertFalse(checker.typed_equal(1, True))

    def test_JPEG_ACK_is_not_native_done(self):
        with self.assertRaises(checker.MissingEvidence):
            checker.check_jpeg([dict(tag='FUNCTIONAL_JPEG_CODEC', line=1, fields=dict(
                operation='original-request', rc='0', physical_asic_compatible='0', capture_verified='0', sequence='1'))],
                dict(pid=77, model_instance=99, transfers=[]), {})

    def test_video_packet_without_original_Stop_or_receiver_rejected(self):
        with self.assertRaises(checker.MissingEvidence):
            checker.check_video([], dict(pid=77, model_instance=99, transfers=[]), {})

    def test_real_independent_JPEG_and_MP4_storage_positive_never_capture(self):
        run, _ = host_test_storage(self.root)
        proof = checker.writeback.inspect(run)
        self.assertTrue(proof['writeback_verified'], proof)
        self.assertTrue(proof['independent_decoded'], proof)
        self.assertEqual({item['decode']['format'] for item in proof['items']}, {'JPEG', 'MP4'})
        jpeg = next(item for item in proof['items'] if item['decode']['format'] == 'JPEG')
        self.assertEqual(len(jpeg['decode']['pixel_sha256']), 64)
        movie = next(item for item in proof['items'] if item['decode']['format'] == 'MP4')
        self.assertEqual(movie['decode']['frame_count'], 4)
        self.assertEqual(movie['decode']['ffmpeg_null_rc'], 0)
        self.assertFalse(proof['capture_verified'])

    def test_missing_callback_and_corrupt_export_fail_storage(self):
        run, paths = host_test_storage(self.root)
        original = (run / 'console.log').read_text()
        (run / 'console.log').write_text('\n'.join(line for line in original.splitlines()
                                      if not line.startswith('MPR_WRITE_CALLBACK_RETURN')) + '\n')
        self.assertFalse(checker.writeback.inspect(run)['writeback_verified'])
        (run / 'console.log').write_text(original)
        paths[0].write_bytes(paths[0].read_bytes()[:-2])
        self.assertFalse(checker.writeback.inspect(run)['writeback_verified'])

    def test_evaluate_reports_missing_contract_and_is_JSON_serializable(self):
        run, _, _, _, _ = host_test_transport(self.root)
        result = checker.evaluate(run, self.root / 'NO_FROZEN_BATCH')
        self.assertFalse(result['capture_verified'])
        self.assertFalse(result['physical_asic_compatibility_verified'])
        self.assertFalse(result['original_CP_RAM_verified'])
        self.assertFalse(result['products']['JPEG']['capture_verified'])
        self.assertTrue(any(row['stage'] in ('profile', 'batch') for row in result['missing']))
        self.assertFalse(any('omits actual' in row['detail'] for row in result['missing']))
        json.dumps(result)


if __name__ == '__main__':
    unittest.main()
