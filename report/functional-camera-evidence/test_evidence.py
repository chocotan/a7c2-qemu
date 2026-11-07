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
import sys
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
# Exact original e6mx bytes; these parser fixtures do not attest capture or source consumption.
E6MX_CONSOLE_SHA256 = '845f3de194621180c687bedabdd65fdc456cce5389b5419588868c64eca71ff3'
E6MX_TRANSFER_OFFSET = 2594388
E6MX_TRANSFER_RECORD = (
    b'OBS FUNCTIONAL_CAMERA_TRANSFER seq=27..28 op=11 source=0x42e destination=0x8403 command=0x2820746 bytes=40 '
    b'native_fnv=0x329254c5e41f02e3 request_bytes=480 request_fnv=0x296c85ea5c5dcabf returned_bytes=51200 '
    b'returned_fnv=0x36e5ede026e630fe required=51200 destination_written_bytes=51200 destination_fnv=0x36e5ede026e630fe '
    b'model_instance=0xe8825ba5bb7c0855 token=0x8000000000000003 readback_closed=1 error=0 origin_kind=api40-source-snapshot'
    b'[ 5583.762945] UDIF: cdev_ioctl() Line 100: uipc: warning ret = -1022\r\n')
E6MX_CONTROL_COMMIT = (
    b'OBS FUNCTIONAL_CAMERA_CONTROL_COMMIT pid=259 tid=380 phase=3 index=1 role=2 bytes=16 '
    b'destination=0x80020002 source=0x90030001 wire_fnv1a=765864c96674cfe9 queued=1 received=1 freed=0 consumed=0 '
    b'send_inflight=0 releasing=0 lease_cycle_id=0 sender_tid=380 receiver_tid=355 free_tid=0 allocate_rc=0 send_rc=0 '
    b'free_rc=0 retained=0x7f7a4dc700 faults=0 busy=0 guard=0 probe_run_id=1 init_run_id=1 state_run_id=0 bridge_rc=0 '
    b'probe_rc=0 native_source=0x80020002 native_destination=0x90030001 native_command=0x3003 native_bytes=24 '
    b'native_fnv1a=cbe972b9ca65f4c8 model_initialized=1 probe_attempts=1 probe_successes=1 probe_refusals=0 '
    b'model_instance=16754054331144865877 config_generation=3 rendered=3 frame_generation=3 start_complete=0 '
    b'mode1_complete=0 defined_mask=15 full_layout_copied=0 model_defined=0 defined_blocks=0 projected_blocks=0 '
    b'zero_policy_blocks=0 publication_copied=0 xsync_defined=0 xsync_source_fps=0 xsync_word=0 xsync_half=0 '
    b'xsync_source_generation=0 published_generation=0 shadow_generation=0 notification_queued=0 notification_received=0 '
    b'notification_AP_consumed=0 cycle_id=0 cycle_generation=0 ack_only=0 mode1_requests=0 cycles_completed=0 '
    b'ack_only_requests=0 ack_only_completed=0 full_queued=0 full_consumed=0 notification_mode=0 business_ready=1 '
    b'functional_model=1 original_CP=0 physical_ASIC_verified=0 fixed_optics_policy=integrated-noneLIF LIF_tuple=0,0,0 '
    b'cache4=0 original_getters_executed=0 original_source_proof=0 EE=0 frame=0 capture=0\r\n')
# Exact public formatter bytes from _zfq; parser/host tests never attest a native capture.
ZFQ_CONSOLE_SHA256 = '2ac0b5ae87335a6a0cc6a4c09734a54dcf9866ecdc4f8794fc382a30b934913f'
ZFQ_VDF_OFFSET = 2334822
ZFQ_VDF_RECORD = (
    b'OBS FUNCTIONAL_VDF_PATH_COMPLETE pid=259 tid=382 phase=3 cycle=4 requests=4 completed_cycles=3 busy=0 '
    b'guard=0 faults=0 source=0x81cf61c6 destination=0x92840747 command=0x152 bytes=16 '
    b'original_fnv1a=e1b56c922a2b5cfb refresh_queue_bound=0 refresh_queue_source=0 '
    b'model_instance=11836296783859096614 config_generation=5 before_config_generation=4 frame_generation=5 '
    b'before_frame_generation=4 lease_generation=5 init_rc=0 bridge_rc=0 validation_rc=0 request_owned=1 '
    b'request_retained=(nil) request_freed=1 ack_retained=0x7fb6b33140 queued=1 received=0 AP_consumed=0 '
    b'send_inflight=0 releasing=0 sender_tid=382 receiver_tid=0 free_tid=0 allocate_rc=0 '
    b'allocation_returned=0x7fb6b33140 allocation_alias=0 request_free_rc=0 send_rc=0 free_rc=0 model_complete=1 '
    b'functional_model=1 original_CP_FIFO_verified=0 physical_CP_RTOS_verified=0 original_selector_verified=0 '
    b'physical_ASIC_verified=0 capture_verified=0 raw=0d205201100001800300010000eb8080 '
    b'ack_wire=0d2052110c00018000005900 canonical_config=01050500000000000000000000000000 '
    b'canonical_zebra8=0300204b41000000 '
    b'canonical_layout32=07010100000000008002e0010000000000000000000000000300000000000000 '
    b'canonical_display16=52010000080000000300010000eb8080 '
    b'canonical_bb32=0000000000000000000000000000000000000000000000000000000000000000 '
    b'canonical_bit_width8=0000000000000000 model_result_bytes=176 realresultbytes=176 '
    b'model_result_fnv1a64=059b6b8e5b5ada03 '
    b'model_result_hex=01000000b0000000261c05aa36f942a4050000000000000005000000000000000500000000000000bb4ec06e8400add325d8b8043b81193025d8b8043b81193000100e000000000080020000e0010000800700001908599001000000010000000100000001000000010000000100000001000000010000000000000000000000010505000000000000000000000000000400000000000000040000000000000052010000080000000300010000eb8080[ '
    b'5541.864466] [K]**UIPC ERROR** free_dynamic_msgq_id: QID[81cf61c4] M=1 C=0 S=0 A=1\r\n')
# Exact zd4 LF record; a framed predecessor does not attest its content or capture.
ZD4_CONSOLE_SHA256 = '92478a134c3743bbc092e6ddc3a19d999e38d1de99239eeff512411a3e11373b'
ZD4_STARTUP_PREDECESSOR_OFFSET = 2682970
ZD4_STARTUP_PREDECESSOR_RECORD = (
    b'OBS FUNCTIONAL_STARTUP_CONTROL_PREDECESSORS pid=259 tid=383 accepted=1 initial_mode_requests=1 '
    b'initial_mode_AP_consumed=1 initial_settings_requests=1 initial_settings_AP_consumed=1 all13_AP_consumed=1 '
    b'VDF_AP_consumed=1 still_format_AP_consumed=1 still_format_cycle=1 model_instance=805113156714136530 '
    b'source_business_equivalent=0 physical_ASIC_verified=0 capture_verified=0'
    b'[ 5546.369864] UDIF: cdev_ioctl() Line 100: uipc: warning ret = -1022\r\n')
ZD4_ADF_FREE_RECORD = (
    b'OBS FULL_ADF_CONNECT_NATIVE_REPLY_FREE pid=259 tid=383 sender=383 waiter=1 '
    b'destination=0x81cf61c4 expected=0x81cf61c4 reply=0x7f96d0bd00 bytes=56 command=0x8001 '
    b'rc=0 faults=0 ap_consumed=1 capture_verified=0'
    b'qemu-system-aarch64: warning: vvfat: host directory commit pending\n\r\n')
# Exact 05b0 original bytes; parser recovery never proves capture or physical compatibility.
SF05_CONSOLE_SHA256 = 'e835b770209eb83423757f1d711c5f6fb43065649344e5b450388a6c6f84d1c0'
SF05_TRANSFER_ECHO = (
    b"'; elOBS FUNCTIONAL_CAMERA_TRANSFER seq=30..30 op=7 source=0x81cf61c6 destination=0x92840747 "
    b'command=0x14c bytes=40 native_fnv=0x965c2abd4f26a9b1 request_bytes=32 request_fnv=0xa453e280c5c66b5e '
    b'returned_bytes=192 returned_fnv=0x5df495954a7b0e74 required=192 destination_written_bytes=192 '
    b'destination_fnv=0x5df495954a7b0e74 model_instance=0xbf06ca9153360c80 token=0 readback_closed=1 error=0 '
    b'origin_kind=native-osal\r\n')
SF05_AUDIT_BYTES = (
    b'OBS NATIVE_CP_BACKGROUND_INPUT_AUDIT_BYTES pid=259 tid=383 sequence=50 offset=768 bytes=128 '
    b'raw=000000000000000005005d40000000000000000005005e40000000000000000005005f400000000000000000'
    b'0500604000000000000000000500614000000000010000000500624000000000020200000500644000000000'
    b'0000000005006640000000000100000005006740000000000000000005006e400000000000000000'
    b'[ 5638.875229] UDIF: cdev_ioctl() Line 100: uipc: warning ret = -1022\r\n')
SF05_FACE_SOURCE_BOUND = (
    b'OBS FUNCTIONAL_FACE_DMM_SOURCE_BOUND pid=259 tid=383 op=0x25 caller_pc=0x7f62cd58ac caller_va=0x35528ac '
    b'library_base=0x7f5f783000 source=0x81cf61c6 reads=4/4 first=0x9784308a second=0x9784308a rc=0 '
    b'producer=process-local-software-owner original_cp_verified=0 capture_verified=0'
    b'[ 5736.378554] UDIF: cdev_ioctl() Line 100: uipc: warning ret = -1022\r\n')
# Exact lwo raw LF record; parser framing makes no capture/ownership claim.
LWO_CONTROL_TTS_RECORD = (
    b'OBS FUNCTIONAL_CAMERA_CONTROL_RESOURCES_TTS_TABLE pid=259 tid=381 appfw_base=0x7f4535b000 '
    b'table_va=0x5f66b08 address=0x7f4b2c1b08 bytes=144 reads=144/144 unchanged=1 atomic_snapshot=0 '
    b'raw_before=1a00000005040000000008000000000000802afe0400000000840000000008000000001e0000000000209a2a7e000000000008001d00000000209a2a7e00000000000800000000001b000000060400000000080000000000008032fe0400000001840000000008000000081e000000000020922a7e000000000008001e0000000020922a7e0000000000080000000000 '
    b'raw_after=1a00000005040000000008000000000000802afe0400000000840000000008000000001e0000000000209a2a7e000000000008001d00000000209a2a7e00000000000800000000001b000000060400000000080000000000008032fe0400000001840000000008000000081e000000000020922a7e000000000008001e0000000020922a7e0000000000080000000000 '
    b'ownership_verified=0[ 5584.789973] [K]**UIPC ERROR** free_dynamic_msgq_id: QID[81cf61c4] M=1 C=0 S=0 A=1\r\n')
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
                 model_source_archive_sha256='c' * 64, qemu_sha256=checker.QEMU_SHA256)
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
        token = operation.get('token', len(intervals) + 1) if op in (16, 17, 18, 33, 34) and payload else 0
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
        if any(event['kind'] == 'request' and event['opcode'] == 12 for event in events):
            policies.update(checker.BIT_WIDTH_POLICY)
        generated = checker.source_module(checker.RUNTIME / 'backup_profile.py').functional_camera_profile_fields(checker.PROFILE)
        policy = {'functional_camera_' + key: generated['functional_camera_' + key] for key in policies}
        manifest.update(policy)
        manifest['backup_transport'] = dict(policy)
    if any(event['kind'] == 'request' and event['opcode'] == 13 for event in events):
        generated = checker.source_module(checker.RUNTIME / 'backup_profile.py').functional_camera_profile_fields(checker.PROFILE)
        policy = {'functional_camera_' + key: generated['functional_camera_' + key] for key in checker.STILL_FORMAT_POLICY}
        manifest.update(policy)
        manifest.setdefault('backup_transport', {}).update(policy)
    if any(event['kind'] == 'request' and event['opcode'] == 14 for event in events):
        generated = checker.source_module(checker.RUNTIME / 'backup_profile.py').functional_camera_profile_fields(checker.PROFILE)
        policy = {'functional_camera_' + key: generated['functional_camera_' + key] for key in checker.STARTUP_CONTROL_POLICY}
        manifest.update(policy)
        manifest.setdefault('backup_transport', {}).update(policy)
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


def host_test_scope_assets(root, reader, *, version=1):
    """Owned text assets only; real digest readers run with patched binary pins."""
    assert version in (1, 2, 3)
    root.mkdir(parents=True, exist_ok=True)
    source_root = reader.NATIVE / ('report/2026-10-31-qemu-M-writer-observer-v3' if version == 3 else
                                  'report/2026-10-30-qemu-readonly-scope-observer')
    source_root.mkdir(parents=True, exist_ok=True)
    sources, files = {}, {}
    names = ('scope-observer.c', 'late-sites.inc', 'build-plugin.sh')
    if version in (2, 3):
        names += (f'log-schema-v{version}.json', f'source-contract-v{version}.json',
            f'check_run_context_v{version}.py', 'check_run_context.py',
            f'integration/scope_trace_checks_v{version}.py', 'integration/scope_trace_checks.py')
    for name in names:
        path = source_root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b'HOST_TEST source ' + name.encode())
        sources[name] = files[str(path)] = reader.sha(path.read_bytes())
    frozen = files.copy()
    header = reader.NATIVE / 'source/build/qemu-SRBXNK/qemu-11.1.2/include/plugins/qemu-plugin.h'
    header.parent.mkdir(parents=True, exist_ok=True)
    header.write_bytes(b'HOST_TEST API7 header')
    candidate, library, receipt_path = (root / name for name in
        ('qemu-system-aarch64', 'readonly-scope-observer.so', 'scope-build.json'))
    candidate.write_bytes(b'HOST_TEST plugin-enabled candidate')
    library.write_bytes(b'HOST_TEST observer library, never loaded')
    scope = dict(profile=f'qemu-readonly-scope-v{version}', identity_binding='unverified',
                 library=str(library), library_sha256=reader.sha(library.read_bytes()),
                 source_sha256=sources, qemu_sha256=reader.sha(candidate.read_bytes()),
                 qemu_header_sha256=reader.sha(header.read_bytes()), log=str(root / 'readonly-scope-trace.log'),
                 capture_verified=False, physical_asic_compatibility_verified=False)
    receipt = {key: scope[key] for key in ('library', 'library_sha256', 'source_sha256', 'qemu_sha256',
                                         'qemu_header_sha256', 'capture_verified', 'physical_asic_compatibility_verified')}
    receipt.update(schema=scope['profile'], plugin_api=7, readonly_imports_verified=True, runtime_verified=False)
    if version in (2, 3):
        extra = dict(trace_schema=f'readonly_scope_v{version}', trace_schema_sha256=sources[f'log-schema-v{version}.json'],
                     source_contract_sha256=sources[f'source-contract-v{version}.json'])
        scope.update(extra)
        receipt.update(extra)
    receipt_path.write_text(json.dumps(receipt))
    scope.update(build_receipt=str(receipt_path), build_receipt_sha256=reader.sha(receipt_path.read_bytes()))
    for path in (candidate, library, receipt_path):
        files[str(path)] = reader.sha(path.read_bytes())
    return dict(backup_transport=dict(binary=str(candidate), binary_sha256=scope['qemu_sha256']),
                files=files, readonly_scope_observer=scope), frozen


class QemuAdmissionTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='HOST_TEST_qemu_admission_')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        native = self.root / 'native'
        patches = mock.patch.multiple(checker, NATIVE=native, RUNTIME=native / 'runtime/analysis',
            QEMU_SHA256=checker.sha(b'HOST_TEST legacy candidate'),
            READONLY_SCOPE_QEMU_SHA256=checker.sha(b'HOST_TEST plugin-enabled candidate'))
        patches.start()
        self.addCleanup(patches.stop)
        self.manifest, self.frozen = host_test_scope_assets(self.root, checker)

    def test_v2_scope_closure_schema_and_receipt_are_explicit_and_bound(self):
        header = checker.NATIVE / 'source/build/qemu-SRBXNK/qemu-11.1.2/include/plugins/qemu-plugin.h'
        header.unlink()
        manifest, frozen = host_test_scope_assets(self.root, checker, version=2)
        self.assertEqual(checker.check_qemu_files(manifest, frozen), checker.READONLY_SCOPE_QEMU_SHA256)
        scope = manifest['readonly_scope_observer']
        self.assertEqual(len(scope['source_sha256']), 9)
        self.assertIs(scope['capture_verified'], False)
        for key, value in (('profile', 'qemu-readonly-scope-v1'), ('profile', 'qemu-readonly-scope-v3'),
                ('trace_schema', 'readonly_scope_v1'),
                ('trace_schema_sha256', '8b6e2bf3576e7e4e5566fa215d2758e088ae8867ed6b3c36ea7b90f38767e50c'),
                ('source_contract_sha256', '0' * 64)):
            changed = copy.deepcopy(manifest)
            changed['readonly_scope_observer'][key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                checker.check_qemu_files(changed, frozen)
        for alias in ('schema_sha256', 'log_schema_sha256'):
            changed = copy.deepcopy(manifest)
            changed['readonly_scope_observer'][alias] = scope['trace_schema_sha256']
            with self.subTest(alias=alias), self.assertRaises(ValueError):
                checker.check_qemu_files(changed, frozen)
        for name in scope['source_sha256']:
            changed = copy.deepcopy(manifest)
            del changed['readonly_scope_observer']['source_sha256'][name]
            with self.subTest(missing=name), self.assertRaises(ValueError):
                checker.check_qemu_files(changed, frozen)
            changed_frozen = dict(frozen)
            del changed_frozen[str(checker.NATIVE / 'report/2026-10-30-qemu-readonly-scope-observer' / name)]
            with self.subTest(unfrozen=name), self.assertRaises(ValueError):
                checker.check_qemu_files(manifest, changed_frozen)
        receipt_path = Path(scope['build_receipt'])
        original = checker.object_json(receipt_path.read_bytes())
        for key, value in (('trace_schema', 'readonly_scope_v1'), ('trace_schema_sha256', '0' * 64),
                           ('source_contract_sha256', '0' * 64)):
            receipt = dict(original, **{key: value})
            receipt_path.write_text(json.dumps(receipt))
            changed = copy.deepcopy(manifest)
            digest = checker.sha(receipt_path.read_bytes())
            changed['files'][str(receipt_path)] = changed['readonly_scope_observer']['build_receipt_sha256'] = digest
            with self.subTest(receipt=key), self.assertRaisesRegex(ValueError, 'v2 receipt schema binding'):
                checker.check_qemu_files(changed, frozen)
        for alias in ('schema_sha256', 'log_schema_sha256'):
            receipt_path.write_text(json.dumps(dict(original, **{alias: scope['trace_schema_sha256']})))
            changed = copy.deepcopy(manifest)
            digest = checker.sha(receipt_path.read_bytes())
            changed['files'][str(receipt_path)] = changed['readonly_scope_observer']['build_receipt_sha256'] = digest
            with self.subTest(receipt_alias=alias), self.assertRaises(ValueError):
                checker.check_qemu_files(changed, frozen)

    def test_v3_scope_requires_its_fixed_root_exact_sources_and_explicit_receipt(self):
        manifest, frozen = host_test_scope_assets(self.root, checker, version=3)
        self.assertEqual(checker.check_qemu_files(manifest, frozen), checker.READONLY_SCOPE_QEMU_SHA256)
        scope = manifest['readonly_scope_observer']
        self.assertEqual(len(scope['source_sha256']), 9)
        for key, value in (('profile', 'qemu-readonly-scope-v2'), ('profile', 'qemu-readonly-scope-v4'),
                           ('trace_schema', 'readonly_scope_v2'), ('trace_schema_sha256', '0' * 64),
                           ('source_contract_sha256', '0' * 64), ('capture_verified', 0)):
            changed = copy.deepcopy(manifest)
            changed['readonly_scope_observer'][key] = value
            with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                checker.check_qemu_files(changed, frozen)
        for alias in ('schema_sha256', 'log_schema_sha256'):
            changed = copy.deepcopy(manifest)
            changed['readonly_scope_observer'][alias] = scope['trace_schema_sha256']
            with self.subTest(alias=alias), self.assertRaises(ValueError):
                checker.check_qemu_files(changed, frozen)
        for name in scope['source_sha256']:
            changed = copy.deepcopy(manifest)
            del changed['readonly_scope_observer']['source_sha256'][name]
            with self.subTest(missing=name), self.assertRaises(ValueError):
                checker.check_qemu_files(changed, frozen)
        changed = copy.deepcopy(manifest)
        wrong_frozen = dict(frozen)
        for name in scope['source_sha256']:
            selected = str(checker.NATIVE / 'report/2026-10-31-qemu-M-writer-observer-v3' / name)
            foreign = str(checker.NATIVE / 'report/2026-10-30-qemu-readonly-scope-observer' / name)
            changed['files'][foreign] = changed['files'].pop(selected)
            wrong_frozen[foreign] = wrong_frozen.pop(selected)
        with self.assertRaisesRegex(ValueError, 'not indexed/frozen'):
            checker.check_qemu_files(changed, wrong_frozen)
        receipt_path = Path(scope['build_receipt'])
        original = checker.object_json(receipt_path.read_bytes())
        for key, value in (('schema', 'qemu-readonly-scope-v2'), ('trace_schema', 'readonly_scope_v2'),
                           ('schema_sha256', scope['trace_schema_sha256']), ('plugin_api', True)):
            receipt_path.write_text(json.dumps(dict(original, **{key: value})))
            changed = copy.deepcopy(manifest)
            digest = checker.sha(receipt_path.read_bytes())
            changed['files'][str(receipt_path)] = changed['readonly_scope_observer']['build_receipt_sha256'] = digest
            with self.subTest(receipt=key), self.assertRaises(ValueError):
                checker.check_qemu_files(changed, frozen)

    def test_new_candidate_reads_actual_assets_and_returns_its_digest(self):
        selected = checker.check_qemu_files(self.manifest, self.frozen)
        self.assertEqual(selected, checker.READONLY_SCOPE_QEMU_SHA256)
        self.assertEqual(checker.check_qemu_files(self.manifest), selected)
        self.assertNotEqual(selected, checker.QEMU_SHA256)
        scope = self.manifest['readonly_scope_observer']
        self.assertIs(scope['capture_verified'], False)
        self.assertIs(scope['physical_asic_compatibility_verified'], False)
        args = host_test_transport(self.root)
        runner = args[1]['functional_camera_runtime']
        args[4]['qemu_sha256'] = runner['artifact']['qemu_sha256'] = args[3][0]['config']['qemu_sha256'] = selected
        (args[0] / 'functional-camera-runner.json').write_text(json.dumps(runner))
        self.assertTrue(checker.check_transport(*args)['verified'])

    def test_legacy_pin_remains_dynamic_and_default_scope_is_off(self):
        candidate = Path(self.manifest['backup_transport']['binary'])
        candidate.write_bytes(b'HOST_TEST legacy candidate')
        self.manifest['backup_transport']['binary_sha256'] = self.manifest['files'][str(candidate)] = checker.QEMU_SHA256
        for explicit_null in (False, True):
            manifest = copy.deepcopy(self.manifest)
            if explicit_null:
                manifest['readonly_scope_observer'] = None
            else:
                del manifest['readonly_scope_observer']
            self.assertEqual(checker.check_qemu_files(manifest, self.frozen), checker.QEMU_SHA256)
        with self.assertRaisesRegex(ValueError, 'exact candidate/profile'):
            checker.check_qemu_files(self.manifest, self.frozen)

    def test_missing_wrong_mixed_scope_and_claims_fail_closed(self):
        mutations = (('profile', 'arbitrary'), ('qemu_sha256', checker.QEMU_SHA256),
                     ('identity_binding', 'verified'), ('library_sha256', 'not-a-digest'),
                     ('capture_verified', 0), ('physical_asic_compatibility_verified', 0))
        for key, value in mutations:
            manifest = copy.deepcopy(self.manifest)
            manifest['readonly_scope_observer'][key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                checker.check_qemu_files(manifest, self.frozen)
        for key in ('profile', 'identity_binding', 'capture_verified', 'physical_asic_compatibility_verified'):
            manifest = copy.deepcopy(self.manifest)
            del manifest['readonly_scope_observer'][key]
            with self.subTest(missing=key), self.assertRaises(ValueError):
                checker.check_qemu_files(manifest, self.frozen)
        for value in (None, 'qemu-readonly-scope-v1', {}):
            manifest = copy.deepcopy(self.manifest)
            manifest['readonly_scope_observer'] = value
            with self.subTest(scope=value), self.assertRaises(ValueError):
                checker.check_qemu_files(manifest, self.frozen)
        manifest = copy.deepcopy(self.manifest)
        del manifest['readonly_scope_observer']
        with self.assertRaises(ValueError):
            checker.check_qemu_files(manifest, self.frozen)

    def test_unknown_candidate_and_manifest_file_mismatch_rejected(self):
        for digest in ('e23589c44386c19417551c982e394b7a4e779f8e68a72f2964b705aca1e96c0d', 'f' * 64, 'arbitrary'):
            manifest = copy.deepcopy(self.manifest)
            manifest['backup_transport']['binary_sha256'] = digest
            manifest['files'][manifest['backup_transport']['binary']] = digest
            with self.subTest(digest=digest), self.assertRaises(ValueError):
                checker.check_qemu_files(manifest, self.frozen)
        manifest = copy.deepcopy(self.manifest)
        manifest['files'][manifest['backup_transport']['binary']] = checker.QEMU_SHA256
        with self.assertRaises(ValueError):
            checker.check_qemu_files(manifest, self.frozen)
        Path(self.manifest['backup_transport']['binary']).write_bytes(b'HOST_TEST replaced candidate')
        with self.assertRaisesRegex(ValueError, 'SHA256 differs'):
            checker.check_qemu_files(self.manifest, self.frozen)

    def test_library_receipt_source_and_frozen_bindings_are_actual(self):
        scope = self.manifest['readonly_scope_observer']
        for name in ('library', 'build_receipt'):
            path = Path(scope[name])
            original = path.read_bytes()
            path.write_bytes(original + b'HOST_TEST changed')
            with self.subTest(actual=name), self.assertRaisesRegex(ValueError, 'SHA256 differs'):
                checker.check_qemu_files(self.manifest, self.frozen)
            path.write_bytes(original)
            manifest = copy.deepcopy(self.manifest)
            manifest['files'][str(path)] = '0' * 64
            with self.subTest(index=name), self.assertRaises(ValueError):
                checker.check_qemu_files(manifest, self.frozen)
        for name in scope['source_sha256']:
            path = str(checker.NATIVE / 'report/2026-10-30-qemu-readonly-scope-observer' / name)
            manifest = copy.deepcopy(self.manifest)
            del manifest['readonly_scope_observer']['source_sha256'][name]
            with self.subTest(missing_source=name), self.assertRaises(ValueError):
                checker.check_qemu_files(manifest, self.frozen)
            frozen = dict(self.frozen)
            del frozen[path]
            with self.subTest(unfrozen=name), self.assertRaises(ValueError):
                checker.check_qemu_files(self.manifest, frozen)
            manifest = copy.deepcopy(self.manifest)
            manifest['files'][path] = '0' * 64
            with self.subTest(unindexed=name), self.assertRaises(ValueError):
                checker.check_qemu_files(manifest, self.frozen)
        include = checker.NATIVE / 'report/2026-10-30-qemu-readonly-scope-observer/late-sites.inc'
        include.write_bytes(b'HOST_TEST replaced include')
        with self.assertRaisesRegex(ValueError, 'SHA256 differs'):
            checker.check_qemu_files(self.manifest, self.frozen)

    def test_rehashed_receipt_cannot_change_bound_fields_or_promote_claims(self):
        scope = self.manifest['readonly_scope_observer']
        path = Path(scope['build_receipt'])
        original = checker.object_json(path.read_bytes())
        for key, value in (('qemu_sha256', checker.QEMU_SHA256), ('library_sha256', '0' * 64),
                           ('qemu_header_sha256', '0' * 64), ('source_sha256', {}),
                           ('plugin_api', 7.0), ('readonly_imports_verified', False),
                           ('runtime_verified', True), ('capture_verified', True),
                           ('physical_asic_compatibility_verified', True)):
            path.write_text(json.dumps({**original, key: value}))
            manifest = copy.deepcopy(self.manifest)
            digest = checker.sha(path.read_bytes())
            manifest['readonly_scope_observer']['build_receipt_sha256'] = manifest['files'][str(path)] = digest
            with self.subTest(key=key), self.assertRaisesRegex(ValueError, 'build receipt/profile/source/asset'):
                checker.check_qemu_files(manifest, self.frozen)

    def test_actual_api_header_is_bound(self):
        header = checker.NATIVE / 'source/build/qemu-SRBXNK/qemu-11.1.2/include/plugins/qemu-plugin.h'
        header.write_bytes(b'HOST_TEST changed API header')
        with self.assertRaisesRegex(ValueError, 'SHA256 differs'):
            checker.check_qemu_files(self.manifest, self.frozen)


def independent_media(kind, force_idr_at=None):
    """Real decode fixtures generated only during focused host tests."""
    common = ['ffmpeg', '-nostdin', '-v', 'error', '-f', 'lavfi', '-i',
              'color=c=blue:size=24x16:rate=30', '-threads', '1']
    if kind == 'JPEG':
        tail = ['-frames:v', '1', '-c:v', 'mjpeg', '-pix_fmt', 'yuvj422p', '-f', 'image2pipe', 'pipe:1']
        return subprocess.run(common + tail, check=True, stdout=subprocess.PIPE,
                              stderr=subprocess.PIPE, timeout=15).stdout
    with tempfile.TemporaryDirectory(prefix='HOST_TEST_decoder_') as directory:
        target = Path(directory) / 'HOST_TEST.MP4'
        force = ['-force_key_frames', f'expr:eq(n,{force_idr_at})'] if force_idr_at is not None else []
        subprocess.run(common + force + ['-frames:v', '4', '-c:v', 'libx264', '-profile:v', 'baseline', '-bf', '0',
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


def host_test_storage(root, jpeg_payload=None, force_idr_at=None):
    run = root / 'HOST_TEST_storage'
    (run / 'SD').mkdir(parents=True)
    card = run / 'host-sd'
    records, paths = [], []
    for token, (kind, path) in enumerate((('JPEG', 'DCIM/HOST_TEST.JPG'),
                                        ('MP4', 'PRIVATE/M4ROOT/CLIP/HOST_TEST.MP4')), 1):
        payload = jpeg_payload if kind == 'JPEG' and jpeg_payload is not None else independent_media(
            kind, force_idr_at if kind == 'MP4' else None)
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
                      jpeg_main=False, jpeg_thumb=False, jpeg_endian='II', jpeg_model=None, video_idr_at=None,
                      native_force_factor=None):
    """Full software replay; every native/observer field is explicitly HOST_TEST.

    Artifact/13-edge provenance is tested separately; this fixture calls the real
    transport/RGB/JPEG/PI/NAL/writeback/decoder stages without starting target code.
    vdf_paths keeps legacy bool/bytes8 Zebra/bytes32 layout entries;
    ('display', native_command[, body8]) selects the independent op8 command.
    ('bit_width',) selects original015e/body0000 and actual typed op12/result168.
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
        storage_run, paths = host_test_storage(root, host_test_exif(primary, thumb, jpeg_endian) if thumb else primary,
                                               force_idr_at=1 if native_force_factor is not None else None)
        exported_jpeg, movie = (path.read_bytes() for path in paths)
        jpeg = primary if primary is not None else exported_jpeg
        parsed_movie = checker.mp4_samples(movie)
    has_layout = any(isinstance(item, bytes) and len(item) == 32 for item in vdf_paths)
    has_bb = any(isinstance(item, tuple) and item[0] == 'bb' for item in vdf_paths)
    has_bit_width = any(isinstance(item, tuple) and item[0] == 'bit_width' for item in vdf_paths)
    width, height = (640, 480) if has_layout or has_bb or has_bit_width or histogram else (24, 16)
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
        kind = {1: 0, 5: 4, 6: 4, 7: 4, 8: 4, 9: 5, 10: 6, 12: 4, 16: 1, 33: 2, 34: 3}[op]
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
        bit_width = isinstance(requested, tuple) and requested[0] == 'bit_width'
        assert not isinstance(requested, bytes) or zebra or layout
        op, command, native_bytes = (7, 0x14c, 40) if layout else (6, 0x153, 14) if zebra else (5, 0x138, 24)
        if bit_width:
            assert requested == ('bit_width',)
            op, command, native_bytes, body, canonical = 12, 0x15e, 10, bytes(2), bytes(8)
        elif bb:
            _, command, body = requested
            native_bytes = checker.BB_COMMANDS[command]
            assert len(body) == native_bytes - 8
            op = 9
            canonical = struct.pack('<2H', command, len(body)) + body + bytes(28 - len(body))
        elif display:
            assert requested[0] == 'display' and len(requested) in (2, 3) and requested[1] in (0x141, 0x152, 0x162, 0x163, 0x170)
            command = requested[1]
            body = requested[2] if len(requested) == 3 else PEAKING_BODY8 if command == 0x152 else bytes(8)
            assert len(body) == 8
            op, native_bytes = 8, {0x141: 8, 0x152: 16, 0x162: 10, 0x163: 14, 0x170: 12}[command]
            canonical = struct.pack('<2I', command, native_bytes - 8) + body
        else:
            canonical = requested if zebra or layout else bytes([int(requested), 5 if requested else 1, 5 if requested else 1, 0xa5, 2,
                                                                 0x63, 0x74, cycle, 0x91, 0x82, 0x73, 0x64, 0x55, 0, 0, 0])
        active = bool(route[0]) if zebra or layout or display or bb or bit_width else requested
        if display or bb or bit_width:
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
                      source=0x81cf61ca if bit_width else
                             0x81cf61d0 + list(checker.BB_COMMANDS).index(command) if bb else
                             {0x141: refresh_source, 0x152: 0x81cf61c7, 0x162: 0x81cf61c8, 0x163: 0x81cf61ca, 0x170: 0x81cf61c7}[command] if display else
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
        result = bytearray(168 if bit_width else 192 if bb else 176 if display else 192 if layout else 168 if zebra else 160)
        struct.pack_into('<2I8Q14I', result, 0, 1, len(result), 99, configuration, generation,
                         generation if active else 0, checker.fnv(canonical),
                         p['source_fnv1a64'], p['consumer_after_fnv1a64'], p['active_bytes'],
                         width, height, width * 3, 0x90590819, 1, 1, 7 if bit_width else 5 if bb else int(active), int(active), 1, 1,
                         int(active), int(active), 0, 0)
        result[128:144] = route
        struct.pack_into('<2Q', result, 144, before_frame, before_config)
        if zebra or layout or display or bb or bit_width:
            result[160:] = canonical
        if bb or bit_width:
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
                ack_retained='(nil)' if freed or name == 'REQUEST_FREE' and (layout or display or bb or bit_width) else '0x500000',
                queued=queued, received=received,
                AP_consumed=consumed, send_inflight=int(name in ('RECEIVE', 'AP_FREE') and not queued), releasing=0,
                sender_tid=90, receiver_tid=90 if received else 0, free_tid=90 if freed else 0,
                allocate_rc=0, send_rc=0, free_rc=0, model_complete=1, functional_model=1,
                original_CP_FIFO_verified=0, physical_CP_RTOS_verified=0, original_selector_verified=0,
                physical_ASIC_verified=0, capture_verified=0, raw=original.hex(),
                ack_wire=(bytes.fromhex('0d205e110c00018000005900') if bit_width else
                          struct.pack('<4HI', 0x200d, command + 0x1000, 12, 0x8001, 0 if zebra or bb else 0x590000)).hex(),
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
                        allocation_alias=0, request_free_rc=0) if bb else {}),
                **(dict(canonical_bit_width8=canonical.hex(), realresultbytes=len(result),
                        allocation_returned='(nil)' if name == 'REQUEST_FREE' else '0x500000',
                        allocation_alias=0, request_free_rc=0) if bit_width else {}))
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
            repeat_origin = cp_origin if layout or display or bit_width else jpeg_origin
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
    lifecycle = (0, 1, 2, 3, 4) if native_force_factor is not None else (0, 1, 3, 4)
    for seq, command in enumerate(lifecycle, 1):
        request = bytearray(48)
        struct.pack_into('<H', request, 2, command)
        struct.pack_into('<I', request, 0x10, {0: 0x98, 1: 0x80, 2: 4, 3: 0x10, 4: 0}[command])
        if command == 2:
            struct.pack_into('<Q', request, 8, 0x2500)
            struct.pack_into('<Q', request, 0x28, 0x3500)
        request[0x18] = 0x20
        struct.pack_into('<I', request, 0x24, 0x210)
        native_requests[command] = bytes(request)
        native_origins[command] = dict(producer_tid=90, source=0x80c70047, destination=0x8055001f,
                                       command=command, bytes=48, fnv1a64=checker.fnv(request))
    def request(command):
        seq = lifecycle.index(command) + 1
        row('FUNCTIONAL_MPR_REQUEST', request_seq=seq, command=command, rc=0, pid=77, producer_tid=81,
            src='0x80c70047', dst='0x8055001f', native_bytes=48, native_fnv=hx(checker.fnv(native_requests[command])),
            epoch=1, memory_generation=1, instance=0 if command == 0 else 99, wire_hex=native_requests[command].hex())
    def completed(command):
        seq = lifecycle.index(command) + 1
        request_wire = native_requests[command]
        event = bytearray(48)
        struct.pack_into('<H', event, 2, (4 if native_force_factor == 1 else 5) if command == 2 else command * 2 + 1)
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
    def publish(info, packet_generation, converted=b'', model_proof=None, result_length=0, command=1):
        nonlocal ticket, write_cursor, outstanding
        ticket += 1
        call_command = 3 if info[0] == 7 else command
        f = dict(epoch=1, instance=99, native_start_fnv=hx(checker.fnv(native_requests[1])), memory_generation=1,
                 group=1, pi_token='0x101', es_token='0x102', request_seq=2,
                 call_request_seq=lifecycle.index(call_command) + 1,
                 call_native_fnv=hx(checker.fnv(native_requests[call_command])),
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
        command = 2 if native_force_factor is not None and index == 1 else 1
        if command == 2:
            request(2)
            row('FUNCTIONAL_MPR_FORCE_REQUEST', request_seq=3, native_fnv=hx(checker.fnv(native_requests[2])),
                opaque4='efcdab89', opaque_word='0x89abcdef', parameter_v='0x3500', parameter_p='0x2500',
                parameter_generation=2, parameter_token='0x301', parameter_fnv=hx(checker.fnv(bytes.fromhex('efcdab89'))),
                parameter_bytes=4, expected_factor=hx(native_force_factor), expected_result='0x990000',
                software_policy='opaque4-force-this-frame-v1', original_argument_semantics_verified=0, capture_verified=0)
        packet_bytes = b''.join(b'\x00\x00\x00\x01' + nal for nal in nals)
        header = bytearray(96)
        struct.pack_into('<2I3Q4I2Q2I', header, 0, 24, 16, index, index, 1, 1, 30, int(any(nal[0] & 31 == 5 for nal in nals)), 0,
                         len(packet_bytes), generation + 1, len(params), 0x61766331)
        output = bytes(header) + params + packet_bytes
        p = proof(33, output)
        frame_input = struct.pack('<I', 1) if index == video_idr_at or command == 2 else b''
        operations.append(dict(op=33, data=frame_input, output=output, origin=native_origins[command], proof=p))
        records.append('HOST_TEST_TRANSFER_' + str(len(operations) - 1))
        for is_config, source, source_offset, values in (
                [(True, params, 96, parsed_movie['parameters'])] if index == 0 else []) + [
                (False, packet_bytes, 96 + len(params), nals)]:
            converted = checker.avcc_bytes(values)
            info = bytearray(96)
            info[0] = 4 if is_config else int(not any(nal[0] & 31 == 5 for nal in nals))
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
                call_request_seq=lifecycle.index(command) + 1, call_native_fnv=hx(checker.fnv(native_requests[command])),
                memory_generation=1, group=1, es_token='0x102',
                address=hx(0x900000 + es_used), offset=es_used, bytes=len(converted), avcc_fnv=hx(checker.fnv(converted)),
                nal_count=len(values), nal_payload_fnv=hx(checker.fnv(b''.join(values))), frame_generation=generation,
                packet_sequence=index, model_token=hx(p['result_token']), result_bytes=len(output), source_offset=source_offset,
                source_bytes=len(source), source_fnv=hx(checker.fnv(source)), info_type=info[0], pid=77, observer_tid=90, rc=0)
            pub = publish(info, generation, converted, p, len(output), command)
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
        if command == 2:
            row('FUNCTIONAL_MPR_FORCE_IDR', request_seq=3, native_fnv=hx(checker.fnv(native_requests[2])),
                opaque_word='0x89abcdef', expected_factor=hx(native_force_factor), expected_result='0x990000',
                frame_generation=generation, model_token=hx(p['result_token']), actual_IDR_NAL5=1, publication_complete=1,
                software_policy='opaque4-force-this-frame-v1', original_argument_semantics_verified=0, capture_verified=0)
            completed(2)
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


class MofControlResourceFramingTests(unittest.TestCase):
    # Original m_of LF19957/[2418208,2419095); framing never attests a capture.
    OFFSET, RAW_LF = 2418208, 19957
    RECORD = (
        b'OBS FUNCTIONAL_CAMERA_CONTROL_RESOURCES_RESERVED tid=382 accepted=1 dmm_enabled=1 dmm_bound=1 '
        b'dmm_slots=1/1 dmm_opens=1/1 dmm_handles=0x8400/0x8401 dmm_generations=1/1 dmm_epochs=1/2 '
        b'dmm_creators=1/1 dmm_allocation_count=2 dmm_lifecycle_changed=0 dmm_domain=2 foreign_speech_kept=1 '
        b'data_frozen=0 control_bound=1 control_live=0 control_faults=0 allocations=4 releases=4 connection_started=1 '
        b'connections=1 format_pending=0 blocked=0 format_consumed=1 buffer_released=1 connection_reply_frees=1 '
        b'connection_faults=0 vef_init=1 vef_owner=0x905a0048 vef_objects=16 vef_pending=0 vef_live=0 '
        b'vef_retained=0 vef_faults=0 pinmem_init=1 pinmem_owner=0x90590818 pinmem_objects=13 pinmem_pending=0 '
        b'pinmem_live=0 pinmem_retained=0 pinmem_faults=0 global_dmm_idle_verified=0 original_cp_executed=0 '
        b'capture_verified=0[ 5563.322680] [K]**UIPC ERROR** free_dynamic_msgq_id: QID[81cf61c4] M=1 C=0 S=0 A=1\r\n')
    PAYLOAD, _TAIL = RECORD[4:-2].split(b'[ ', 1)
    KERNEL = b'[ ' + _TAIL

    def test_mof_original887_CRLF_fields_raw_spans_and_resource_only_nonclaim(self):
        self.assertEqual(len(self.RECORD), 887)
        self.assertEqual(checker.sha(self.RECORD),
                         'aa2f2563e44fc478c6762a0f52416f0c0ee23e3e17f0fefed20ee6a796fd00f9')
        framed, note = checker.frame_console_kernel(self.RECORD[4:], self.OFFSET + 4, self.RAW_LF)
        self.assertEqual(framed, self.PAYLOAD + b'\r\n')
        self.assertEqual(note, dict(raw=self.KERNEL.decode(), bytes=84,
            sha256='79b3116030e6d362c6e5cb8bc67ec3e7d73f7cca957e95316551a1dfb7dd4d12',
            byte_offset=2419009, raw_lf_line=19957, cause='unknown', line_ending='\r\n',
            payload=dict(raw=self.PAYLOAD.decode(), bytes=797,
                sha256='0e5f31ffb4bd3dbc7ddaf3cf7e1175d422fd06322dc84be8e60aba1c07a28399',
                byte_offset=2418212)))
        expected = dict(part.split('=', 1) for part in JFZ_VDF_RESOURCE_OBS.splitlines()[-1].split(' ')[2:])
        expected['tid'] = '382'
        self.assertEqual(len(expected), 45)
        self.assertEqual(checker.console_producer_fields(self.PAYLOAD), expected)
        row, = checker.parse_console(self.RECORD)
        self.assertEqual(row['fields'], expected)
        self.assertEqual(list(row['fields']), list(expected))
        self.assertNotIn('diagnostic', row)
        self.assertNotIn('verified', row)
        only_resource = checker.check_control(None, [row], {})
        self.assertFalse(only_resource['required'])
        self.assertFalse(only_resource['verified'])
        self.assertFalse(only_resource['capture_verified'])
        self.assertFalse(only_resource['physical_asic_compatibility_verified'])
        self.assertFalse(only_resource['original_CP_executed'])

    def test_mof_clean_and_framed_prefixes_endings_preserve_fields_offsets_and_following_row(self):
        before = b'boot\rprogress\r\nordinary\n'
        after = b'OBS FUNCTIONAL_CAMERA_TRANSFER op=2 error=0\n'
        for prefix in (b'', b'OBS ', b'/ # OBS '):
            for ending in (b'\n', b'\r\n'):
                clean, = checker.parse_console(prefix + self.PAYLOAD + ending)
                self.assertNotIn('diagnostic', clean)
                self.assertNotIn('kernel_diagnostic', clean)
                raw = before + prefix + self.PAYLOAD + self.KERNEL + ending + after
                with self.subTest(prefix=prefix, ending=ending):
                    row, following = checker.parse_console(raw)
                    self.assertEqual(row['fields'], clean['fields'])
                    self.assertEqual((row['line'], following['line']), (4, 5))
                    note = row['kernel_diagnostic']
                    self.assertEqual((note['raw_lf_line'], note['cause']), (3, 'unknown'))
                    self.assertEqual(note['line_ending'].encode(), ending)
                    self.assertEqual(note['payload']['byte_offset'], len(before) + len(prefix))
                    self.assertEqual(note['byte_offset'], len(before) + len(prefix) + len(self.PAYLOAD))
                    for part in (note, note['payload']):
                        start, size = part['byte_offset'], part['bytes']
                        self.assertEqual(raw[start:start + size], part['raw'].encode())
                        self.assertEqual(checker.sha(raw[start:start + size]), part['sha256'])
                    self.assertNotIn('verified', row)

    def test_mof_every_missing_renamed_reordered_extra_and_duplicate_key_fails_closed(self):
        parts = self.PAYLOAD.split(b' ')
        malformed = [self.PAYLOAD + b' extra=0', self.PAYLOAD + b' native_fnv1a=0000000000000000']
        for index in range(1, len(parts)):
            renamed = parts[:index] + [b'unknown_' + parts[index]] + parts[index + 1:]
            swapped = parts[:]
            other = 1 if index == len(parts) - 1 else index + 1
            swapped[index], swapped[other] = swapped[other], swapped[index]
            malformed.extend((b' '.join(parts[:index] + parts[index + 1:]), b' '.join(renamed), b' '.join(swapped)))
        for payload in malformed:
            with self.subTest(payload=payload):
                self.assertIsNone(checker.console_producer_fields(payload))
                for tail in (b'', self.KERNEL):
                    row, = checker.parse_console(b'OBS ' + payload + tail + b'\n')
                    self.assertIn('diagnostic', row)
                    self.assertNotIn('kernel_diagnostic', row)
                    with self.assertRaisesRegex(ValueError, 'malformed control resource diagnostic'):
                        checker.check_control(None, [row], {})
        for token in parts[1:]:
            payload = self.PAYLOAD + b' ' + token
            with self.subTest(duplicate=token), self.assertRaisesRegex(ValueError, 'duplicate JSON key'):
                checker.console_producer_fields(payload)
            for tail in (b'', self.KERNEL):
                with self.subTest(duplicate=token, tail=tail), self.assertRaisesRegex(ValueError, 'duplicate JSON key'):
                    checker.parse_console(b'OBS ' + payload + tail + b'\n')

    def test_mof_clean_and_framed_numbers_tuples_ranges_and_false_claims_fail_closed(self):
        changes = ((b'tid=382', b'tid=0'), (b'tid=382', b'tid=-1'), (b'tid=382', b'tid=0382'),
            (b'tid=382', b'tid=2147483648'), (b'accepted=1', b'accepted=0'), (b'accepted=1', b'accepted=true'),
            (b'dmm_enabled=1', b'dmm_enabled=2'), (b'dmm_slots=1/1', b'dmm_slots=1'),
            (b'dmm_slots=1/1', b'dmm_slots=1/1/0'), (b'dmm_slots=1/1', b'dmm_slots=2/1'),
            (b'dmm_opens=1/1', b'dmm_opens=-1/1'), (b'dmm_opens=1/1', b'dmm_opens=4294967296/1'),
            (b'dmm_handles=0x8400/0x8401', b'dmm_handles=0x100000000/0x8401'),
            (b'dmm_handles=0x8400/0x8401', b'dmm_handles=0X8400/0x8401'),
            (b'dmm_generations=1/1', b'dmm_generations=01/1'),
            (b'dmm_epochs=1/2', b'dmm_epochs=18446744073709551616/2'),
            (b'dmm_creators=1/1', b'dmm_creators=1/4294967296'),
            (b'dmm_allocation_count=2', b'dmm_allocation_count=18446744073709551616'),
            (b'dmm_domain=2', b'dmm_domain=2.0'), (b'allocations=4', b'allocations=+4'),
            (b'releases=4', b'releases=0x4'), (b'vef_objects=16', b'vef_objects=4294967296'),
            (b'vef_owner=0x905a0048', b'vef_owner=0x905A0048'),
            (b'pinmem_owner=0x90590818', b'pinmem_owner=0x090590818'))
        fields = dict(part.split(b'=', 1) for part in self.PAYLOAD.split(b' ')[1:])
        changes += tuple((key + b'=0', key + b'=1') for key in fields if key in (
            b'data_frozen', b'control_live', b'control_faults', b'format_pending', b'blocked', b'connection_faults',
            b'vef_pending', b'vef_live', b'vef_retained', b'vef_faults', b'pinmem_pending', b'pinmem_live',
            b'pinmem_retained', b'pinmem_faults', b'global_dmm_idle_verified', b'original_cp_executed', b'capture_verified'))
        for old, new in changes:
            payload = self.PAYLOAD.replace(old, new, 1)
            with self.subTest(change=(old, new)):
                self.assertNotEqual(payload, self.PAYLOAD)
                self.assertIsNone(checker.console_producer_fields(payload))
                for tail in (b'', self.KERNEL):
                    row, = checker.parse_console(payload + tail + b'\r\n')
                    self.assertIn('diagnostic', row)
                    self.assertNotIn('kernel_diagnostic', row)
                    with self.assertRaisesRegex(ValueError, 'malformed control resource diagnostic'):
                        checker.check_control(None, [row], {})

    def test_mof_shared_nonclaim_grammar_accepts_canonical_numeric_boundaries(self):
        # Synthetic formatter limits are diagnostics, with no resource/business success claim.
        replacements = {b'tid': b'2147483647', b'dmm_opens': b'4294967295/0',
            b'dmm_handles': b'0xffffffff/0', b'dmm_generations': b'4294967295/0',
            b'dmm_epochs': b'18446744073709551615/0', b'dmm_creators': b'4294967295/0',
            b'dmm_allocation_count': b'18446744073709551615', b'dmm_domain': b'4294967295',
            b'allocations': b'18446744073709551615', b'releases': b'18446744073709551615',
            b'vef_owner': b'0xffffffff', b'vef_objects': b'4294967295'}
        parts = self.PAYLOAD.split(b' ')
        payload = b' '.join(parts[:1] + [key + b'=' + replacements.get(key, value)
            for key, value in (part.split(b'=', 1) for part in parts[1:])])
        expected = checker.console_producer_fields(payload)
        self.assertIsNotNone(expected)
        for tail in (b'', self.KERNEL):
            row, = checker.parse_console(payload + tail + b'\n')
            self.assertEqual(row['fields'], expected)
            self.assertNotIn('diagnostic', row)
            result = checker.check_control(None, [row], {})
            self.assertFalse(result['required'])
            self.assertFalse(result['verified'])
            self.assertFalse(result['capture_verified'])
            self.assertFalse(result['physical_asic_compatibility_verified'])

    def test_mof_exact_dynamic_trailer_only_timestamp_QID_bits_and_original_ending(self):
        udif = b'[ 5563.322680] UDIF: cdev_ioctl() Line 100: uipc: warning ret = -1022'
        invalid = (self.KERNEL.replace(b'5563.322680', b'05563.322680'),
            self.KERNEL.replace(b'5563.322680', b'5563.32268'),
            self.KERNEL.replace(b'5563.322680', b'5563.3226800'),
            self.KERNEL.replace(b'81cf61c4', b'81CF61C4'), self.KERNEL.replace(b'81cf61c4', b'81cf61c'),
            self.KERNEL.replace(b'81cf61c4', b'081cf61c4'), self.KERNEL.replace(b'M=1', b'M=0'),
            self.KERNEL.replace(b'C=0', b'C=1'), self.KERNEL.replace(b'S=0', b'S=1'),
            self.KERNEL.replace(b'A=1', b'A=0'), self.KERNEL.replace(b'M=1 C=0', b'C=0 M=1'),
            self.KERNEL.replace(b'free_dynamic_msgq_id', b'unknown_operation'),
            self.KERNEL + b' extra', self.KERNEL + self.KERNEL, b' ' + self.KERNEL,
            self.KERNEL[:-1], b'unknown kernel trailer', udif,
            udif.replace(b'-1022', b'-1021'), udif.replace(b'Line 100', b'Line 101'))
        for tail in invalid:
            raw = self.PAYLOAD + tail + b'\r\n'
            with self.subTest(tail=tail):
                self.assertEqual(checker.frame_console_kernel(raw, 0, 1), (raw, None))
                row, = checker.parse_console(b'OBS ' + raw)
                self.assertIn('diagnostic', row)
                self.assertNotIn('kernel_diagnostic', row)
                with self.assertRaisesRegex(ValueError, 'malformed control resource diagnostic'):
                    checker.check_control(None, [row], {})
        for ending in (b'', b'\r'):
            raw = self.PAYLOAD + self.KERNEL + ending
            with self.subTest(ending=ending):
                self.assertEqual(checker.frame_console_kernel(raw, 0, 1), (raw, None))
                with self.assertRaisesRegex(ValueError, 'truncated evidence trace'):
                    checker.parse_console(b'OBS ' + raw)

    def test_mof_unknown_family_foreign_trailers_and_refusal_prose_are_not_promoted(self):
        for tag in (b'FUNCTIONAL_CAMERA_CONTROL_RESOURCES_UNKNOWN', b'FUNCTIONAL_CAMERA_CONTROL_RESOURCES_REFUSED',
                    b'FUNCTIONAL_CAMERA_CONTROL_RESOURCE_DEPENDENCIES', b'FUNCTIONAL_UNKNOWN_RESOURCES_RESERVED'):
            payload = tag + b' ' + self.PAYLOAD.split(b' ', 1)[1]
            raw = payload + self.KERNEL + b'\n'
            with self.subTest(tag=tag):
                self.assertIsNone(checker.console_producer_fields(payload))
                self.assertEqual(checker.frame_console_kernel(raw, 0, 1), (raw, None))
                row, = checker.parse_console(raw)
                self.assertIn('diagnostic', row)
                self.assertNotIn('kernel_diagnostic', row)
                self.assertNotIn('verified', row)
        for payload in (b'FUNCTIONAL_CAMERA_CONTROL_RESOURCES_RESERVED process-owner-or-resource-lock-refused',
                        self.PAYLOAD + b' unknown=trailer'):
            for tail in (b'', self.KERNEL):
                row, = checker.parse_console(payload + tail + b'\n')
                self.assertIn('diagnostic', row)
                self.assertNotIn('kernel_diagnostic', row)
                with self.assertRaisesRegex(ValueError, 'malformed control resource diagnostic'):
                    checker.check_control(None, [row], {})

    def test_mof_resource_framing_cannot_replace_source_State128_or_full_wire_FNV_joins(self):
        resource, = checker.parse_console(self.RECORD)
        with tempfile.TemporaryDirectory() as temporary:
            args = host_test_control(Path(temporary))
            transport = checker.check_transport(*args)
            self.assertEqual(checker.check_control(args[0], [resource] + args[2], transport), transport['control'])
            self.assertFalse(transport['control']['capture_verified'])
            self.assertFalse(transport['control']['physical_asic_compatibility_verified'])
            for tag, key, wrong in (('PROBE', 'native_fnv1a', '0000000000000000'),
                    ('PROBE', 'native_source', '0x80020003'), ('PROBE', 'model_instance', '100'),
                    ('SENT', 'wire_fnv1a', '0000000000000000'), ('COMMIT', 'capture', '1')):
                rows = copy.deepcopy(args[2])
                next(row['fields'] for row in rows if row['tag'] == 'FUNCTIONAL_CAMERA_CONTROL_' + tag)[key] = wrong
                with self.subTest(tag=tag, key=key), self.assertRaises(ValueError):
                    checker.check_control(args[0], [resource] + rows, transport)


class ConsoleFramingTests(unittest.TestCase):
    # Exact public logger text; physical LF19720 differs from the saved parser's line20748.
    RUN64_CONTROL_COMMIT = (
        b'OBS FUNCTIONAL_CAMERA_CONTROL_COMMIT pid=259 tid=380 phase=3 index=1 role=2 bytes=16 '
        b'destination=0x80020002 source=0x90030001 wire_fnv1a=765864c96674cfe9 queued=1 received=1 freed=0 consumed=0 '
        b'send_inflight=0 releasing=0 lease_cycle_id=0 sender_tid=380 receiver_tid=355 free_tid=0 allocate_rc=0 send_rc=0 '
        b'free_rc=0 retained=0x7f96c17480 faults=0 busy=0 guard=0 probe_run_id=1 init_run_id=1 state_run_id=0 bridge_rc=0 '
        b'probe_rc=0 native_source=0x80020002 native_destination=0x90030001 native_command=0x3003 native_bytes=24 '
        b'native_fnv1a=cbe972b9ca65f4c8 model_initialized=1 probe_attempts=1 probe_successes=1 probe_refusals=0 '
        b'model_instance=2017555474633331667 config_generation=3 rendered=3 frame_generation=3 start_complete=0 '
        b'mode1_complete=0 defined_mask=15 full_layout_copied=0 model_defined=0 defined_blocks=0 projected_blocks=0 '
        b'zero_policy_blocks=0 publication_copied=0 xsync_defined=0 xsync_source_fps=0 xsync_word=0 xsync_half=0 '
        b'xsync_source_generation=0 published_generation=0 shadow_generation=0 notification_queued=0 notification_received=0 '
        b'notification_AP_consumed=0 cycle_id=0 cycle_generation=0 ack_only=0 mode1_requests=0 cycles_completed=0 '
        b'ack_only_requests=0 ack_only_completed=0 full_queued=0 full_consumed=0 notification_mode=0 business_ready=1 '
        b'functional_model=1 original_CP=0 physical_ASIC_verified=0 fixed_optics_policy=integrated-noneLIF LIF_tuple=0,0,0 '
        b'cache4=0 original_getters_executed=0 original_source_proof=0 EE=0 frame=0 capture=0'
        b'[ 5803.776761] [K]**UIPC ERROR** free_dynamic_msgq_id: QID[81cf61c4] M=1 C=0 S=0 A=1\r\n')

    def test_selector0_control_commit_exact_extended_schema_keeps_legacy(self):
        legacy = E6MX_CONTROL_COMMIT[4:].rstrip(b'\r\n')
        extension = (b'mode_selector=0 mode_complete=0 mode0_requests=0 mode0_complete=0 '
                     b'mode0_cycles_completed=0 mode1_cycle_id=0 mode1_cycle_generation=0 '
                     b'selector_policy=opaque-state-refresh-v1 ')
        payload = legacy.replace(b'notification_mode=0 ', b'notification_mode=0 ' + extension)
        self.assertIsNotNone(checker.console_producer_fields(legacy))
        parsed = checker.console_producer_fields(payload)
        self.assertIsNotNone(parsed)
        self.assertEqual(len(parsed), 93)
        self.assertEqual(parsed['mode_selector'], '0')
        kernel = b'[ 5803.776761] UDIF: cdev_ioctl() Line 100: uipc: warning ret = -1022'
        row, = checker.parse_console(b'OBS ' + payload + kernel + b'\r\n')
        self.assertEqual(row['fields'], parsed)
        self.assertNotIn('diagnostic', row)
        self.assertEqual(row['kernel_diagnostic']['payload']['raw'].encode(), payload)
        for word in extension.split():
            with self.subTest(missing=word):
                self.assertIsNone(checker.console_producer_fields(payload.replace(word + b' ', b'')))
                with self.assertRaisesRegex(ValueError, 'duplicate JSON key'):
                    checker.console_producer_fields(payload + b' ' + word)
        for before, after in ((b'mode_selector=0', b'mode_selector=2'),
                              (b'mode_complete=0', b'mode_complete=01'),
                              (b'mode0_complete=0', b'mode0_complete=-1'),
                              (b'mode0_requests=0', b'mode0_requests=4294967296'),
                              (b'mode1_cycle_id=0', b'mode1_cycle_id=18446744073709551616'),
                              (b'mode1_cycle_generation=0', b'mode1_cycle_generation=4294967296'),
                              (b'selector_policy=opaque-state-refresh-v1', b'selector_policy=unknown'),
                              (b'mode_selector=0 mode_complete=0', b'mode_complete=0 mode_selector=0')):
            with self.subTest(before=before, after=after):
                self.assertIsNone(checker.console_producer_fields(payload.replace(before, after)))
        self.assertIsNone(checker.console_producer_fields(payload + b' extra=0'))

    def test_run64_control_commit_exact_bytes_offsets_and_stage_snapshot(self):
        raw = self.RUN64_CONTROL_COMMIT
        self.assertEqual(len(raw), 1543)
        self.assertEqual(checker.sha(raw), 'd88235fcd226465425c2703657b95d0145a0c5e69a37f81b2e617789fcbe70b7')
        payload, tail = raw[4:-2].split(b'[ ', 1)
        kernel = b'[ ' + tail
        normalized, note = checker.frame_console_kernel(raw[4:], 2356118, 19720)
        self.assertEqual(normalized, payload + b'\r\n')
        self.assertEqual(note, dict(raw=kernel.decode(), bytes=84,
            sha256='c3117affb7e7d1c67a3b764ba880f2782890e46ae5a29f656fa1cda174c60059',
            byte_offset=2357571, raw_lf_line=19720, cause='unknown', line_ending='\r\n',
            payload=dict(raw=payload.decode(), bytes=1453,
                sha256='b0e418d2d9b626f5330bea6b862f958d27890bca639e76bb56fcdf91e74205d3', byte_offset=2356118)))
        self.assertEqual(b'OBS ' + note['payload']['raw'].encode() + note['raw'].encode() + note['line_ending'].encode(), raw)
        original, = checker.parse_console(b'OBS ' + payload + b'\r\n')
        row, = checker.parse_console(raw)
        self.assertEqual(row['fields'], original['fields'])
        self.assertEqual(len(row['fields']), 85)
        self.assertEqual((row['fields']['freed'], row['fields']['consumed'], row['fields']['capture']), ('0', '0', '0'))
        self.assertNotIn('diagnostic', row)
        self.assertNotIn('verified', row)
        self.assertNotIn('capture_verified', row)

    def test_run64_control_commit_prefix_endings_and_physical_LF_preserve_raw_parts(self):
        payload, tail = self.RUN64_CONTROL_COMMIT[4:-2].split(b'[ ', 1)
        kernel = b'[ ' + tail
        before = b'boot\rprogress\r\nordinary\n'
        for prefix in (b'', b'OBS ', b'/ # OBS '):
            for ending in (b'\n', b'\r\n'):
                raw = before + prefix + payload + kernel + ending
                with self.subTest(prefix=prefix, ending=ending):
                    row, = checker.parse_console(raw)
                    self.assertEqual(row['line'], 4)
                    note = row['kernel_diagnostic']
                    self.assertEqual((note['raw_lf_line'], note['cause'], note['line_ending']), (3, 'unknown', ending.decode()))
                    self.assertEqual(note['payload']['byte_offset'], len(before) + len(prefix))
                    self.assertEqual(note['byte_offset'], len(before) + len(prefix) + len(payload))
                    for part in (note, note['payload']):
                        start, size = part['byte_offset'], part['bytes']
                        self.assertEqual(raw[start:start + size], part['raw'].encode())
                        self.assertEqual(checker.sha(raw[start:start + size]), part['sha256'])
                    self.assertEqual(raw[note['byte_offset'] + note['bytes']:], ending)

    def test_run64_control_commit_unknown_kernel_values_and_incomplete_tails_stay_diagnostic(self):
        payload, tail = self.RUN64_CONTROL_COMMIT[4:-2].split(b'[ ', 1)
        kernel = b'[ ' + tail
        invalid = (kernel.replace(b'5803.776761', b'05803.776761'), kernel.replace(b'5803.776761', b'5803.77676'),
            kernel.replace(b'5803.776761', b'5803.7767610'), kernel.replace(b'81cf61c4', b'81CF61C4'),
            kernel.replace(b'81cf61c4', b'81cf61c'), kernel.replace(b'81cf61c4', b'081cf61c4'),
            kernel.replace(b'81cf61c4', b'81cf61cg'), kernel.replace(b'M=1', b'M=0'),
            kernel.replace(b'C=0', b'C=1'), kernel.replace(b'S=0', b'S=1'), kernel.replace(b'A=1', b'A=0'),
            kernel.replace(b'M=1', b'M=-1'), kernel.replace(b'M=1', b'M=01'),
            kernel.replace(b'M=1', b'M=4294967296'), kernel.replace(b'M=1 C=0', b'C=0 M=1'),
            kernel.replace(b' S=0', b''), kernel + b' M=1', kernel + b' extra', kernel + kernel,
            kernel.replace(b'free_dynamic_msgq_id', b'unknown_operation'), kernel[:-1], b' ' + kernel,
            b'[ 5803.776761] UDIF: cdev_ioctl() Line 100: uipc: warning ret = 0',
            b'[ 5803.776761] UDIF: cdev_ioctl() Line 100: uipc: warning ret = -1021', b'unknown trailer')
        for changed in invalid:
            with self.subTest(kernel=changed):
                row, = checker.parse_console(b'OBS ' + payload + changed + b'\r\n')
                self.assertIn('diagnostic', row)
                self.assertNotIn('kernel_diagnostic', row)
        for changed in (self.RUN64_CONTROL_COMMIT[:-2], self.RUN64_CONTROL_COMMIT[:-1]):
            with self.subTest(raw=changed), self.assertRaisesRegex(ValueError, 'truncated evidence trace'):
                checker.parse_console(changed)
        for changed in (payload + b'\r' + kernel + b'\n', payload + kernel + b'\r\r\n'):
            with self.subTest(raw=changed), self.assertRaisesRegex(ValueError, 'truncated evidence trace'):
                checker.parse_console(changed)

    def test_run64_control_commit_all_formatter_fields_order_types_and_unique_values_are_required(self):
        payload, tail = self.RUN64_CONTROL_COMMIT[4:-2].split(b'[ ', 1)
        kernel = b'[ ' + tail
        parts = payload.split(b' ')
        for index in range(1, len(parts)):
            with self.subTest(missing=parts[index]):
                row, = checker.parse_console(b' '.join(parts[:index] + parts[index + 1:]) + kernel + b'\n')
                self.assertIn('diagnostic', row)
                self.assertNotIn('kernel_diagnostic', row)
        invalid = (payload.replace(b'pid=259 tid=380', b'tid=380 pid=259'), payload + b' extra=0',
            payload.replace(b'pid=259', b'pid=0259'), payload.replace(b'phase=3', b'phase=4294967296'),
            payload.replace(b'lease_cycle_id=0', b'lease_cycle_id=18446744073709551616'),
            payload.replace(b'send_rc=0', b'send_rc=2147483648'), payload.replace(b'free_rc=0', b'free_rc=-2147483649'),
            payload.replace(b'destination=0x80020002', b'destination=0x100000000'),
            payload.replace(b'wire_fnv1a=765864c96674cfe9', b'wire_fnv1a=765864C96674cfe9'),
            payload.replace(b'retained=0x7f96c17480', b'retained=0x07f96c17480'),
            payload.replace(b'fixed_optics_policy=integrated-noneLIF', b'fixed_optics_policy=unknown'),
            payload.replace(b'physical_ASIC_verified=0', b'physical_ASIC_verified=1'),
            payload.replace(b'capture=0', b'capture=1'), payload.replace(b'capture=0', b'capture=0=pid=259'))
        for changed in invalid:
            with self.subTest(payload=changed):
                row, = checker.parse_console(changed + kernel + b'\n')
                self.assertIn('diagnostic', row)
                self.assertNotIn('kernel_diagnostic', row)
        for changed in (payload + b' pid=259',
                        payload.replace(b'capture=0', b'capture=0=pid=259') + b' pid=259'):
            with self.subTest(payload=changed), self.assertRaisesRegex(ValueError, 'duplicate JSON key'):
                checker.parse_console(changed + kernel + b'\n')

    def test_run64_control_commit_both_existing_trailers_keep_other_family_pairings(self):
        payload, tail = self.RUN64_CONTROL_COMMIT[4:-2].split(b'[ ', 1)
        dynamic = b'[ ' + tail
        udif = b'[ 5803.776761] UDIF: cdev_ioctl() Line 100: uipc: warning ret = -1022'
        for kernel in (dynamic, udif):
            with self.subTest(kernel=kernel):
                row, = checker.parse_console(payload + kernel + b'\r\n')
                self.assertIn('kernel_diagnostic', row)
                self.assertEqual(row['kernel_diagnostic']['raw'].encode(), kernel)
        for fixture in (E6MX_TRANSFER_RECORD, ZD4_STARTUP_PREDECESSOR_RECORD, SF05_AUDIT_BYTES, SF05_FACE_SOURCE_BOUND):
            guest = fixture[4:-2].split(b'[ ', 1)[0]
            with self.subTest(tag=guest.split(b' ', 1)[0]):
                row, = checker.parse_console(guest + dynamic + b'\r\n')
                self.assertIn('diagnostic', row)
                self.assertNotIn('kernel_diagnostic', row)
        for event in (b'PROBE', b'SENT', b'OWNED_FREE', b'AP_FREE', b'RECEIVE', b'FAULT'):
            with self.subTest(event=event):
                row, = checker.parse_console(payload.replace(b'CONTROL_COMMIT', b'CONTROL_' + event) + dynamic + b'\n')
                self.assertIn('diagnostic', row)
                self.assertNotIn('kernel_diagnostic', row)
        for fixture in (ZFQ_VDF_RECORD, LWO_CONTROL_TTS_RECORD):
            guest = fixture[4:-2].split(b'[ ', 1)[0]
            with self.subTest(tag=guest.split(b' ', 1)[0]):
                row, = checker.parse_console(guest + udif + b'\r\n')
                if fixture == ZFQ_VDF_RECORD:
                    self.assertNotIn('diagnostic', row)
                    self.assertEqual(row['kernel_diagnostic']['raw'].encode(), udif)
                else:
                    self.assertIn('diagnostic', row)
                    self.assertNotIn('kernel_diagnostic', row)

    def test_run64_control_commit_framing_cannot_replace_real_control_source_receipts(self):
        payload, tail = self.RUN64_CONTROL_COMMIT[4:-2].split(b'[ ', 1)
        kernel = b'[ ' + tail
        row, = checker.parse_console(self.RUN64_CONTROL_COMMIT)
        with self.assertRaisesRegex(ValueError, 'source probe not joined'):
            checker.check_control(None, [row], {'pid': 259})
        for key, value in ((b'faults', b'1'), (b'bridge_rc', b'-5'), (b'probe_rc', b'-5')):
            changed = payload.replace(key + b'=0 ', key + b'=' + value + b' ', 1)
            with self.subTest(key=key):
                failed, = checker.parse_console(changed + kernel + b'\r\n')
                self.assertIn('kernel_diagnostic', failed)
                self.assertNotIn('diagnostic', failed)
                with self.assertRaisesRegex(ValueError, 'failed control timing probe'):
                    checker.check_control(None, [failed], {'pid': 259})

    RUN64_SLASH_TRANSFER = (
        b'/OBS FUNCTIONAL_CAMERA_TRANSFER seq=3..3 op=1 source=0x81cf61c4 destination=0x92840747 '
        b'command=0x138 bytes=24 native_fnv=0xe39cfe6ede356b69 request_bytes=0 '
        b'request_fnv=0xcbf29ce484222325 returned_bytes=128 returned_fnv=0xa3b050f8feba6f36 required=128 '
        b'destination_written_bytes=128 destination_fnv=0xa3b050f8feba6f36 '
        b'model_instance=0x1bffcc03c42a13d3 token=0 readback_closed=1 error=0 origin_kind=native-osal\r\n')

    def test_run64_exact_slash_transfer_preserves_original_prefix_offsets_and_fields(self):
        raw = self.RUN64_SLASH_TRANSFER
        self.assertEqual(len(raw), 409)
        self.assertEqual(checker.sha(raw), '0b61cd96df065cfb5c3b59fbb55f703a6a7735b5d5f1b51dc1a5000d1ccb3fc3')
        normalized, note = checker.frame_console_transfer_echo(raw, 2298910, 19584)
        self.assertEqual(normalized, raw[5:])
        self.assertEqual((note['raw'], note['cause'], note['byte_offset'], note['raw_lf_line']),
                         ('/OBS ', 'unknown', 2298910, 19584))
        self.assertEqual(note['payload']['byte_offset'], 2298915)
        self.assertEqual(note['payload']['raw'].encode() + b'\r\n', raw[5:])
        for part in (note, note['payload']):
            self.assertEqual(checker.sha(part['raw'].encode()), part['sha256'])
        row, = checker.parse_console(raw)
        self.assertEqual(row['tag'], 'FUNCTIONAL_CAMERA_TRANSFER')
        self.assertEqual((row['fields']['seq'], row['fields']['returned_bytes']), ('3..3', '128'))
        self.assertEqual(row['fields']['model_instance'], '0x1bffcc03c42a13d3')
        self.assertEqual(row['console_prefix_diagnostic']['raw'], '/OBS ')
        self.assertNotIn('verified', row)
        self.assertNotIn('capture_verified', row)

    def test_run64_slash_transfer_keeps_exact_formatter_rejections_and_original_errors(self):
        raw = self.RUN64_SLASH_TRANSFER
        body = raw[5:-2]
        for prefix in (b'//OBS ', b'x/OBS ', b'/ OBS ', b' /OBS ', b'/OBS  ', b'other/OBS '):
            with self.subTest(prefix=prefix):
                self.assertEqual(checker.parse_console(prefix + body + b'\r\n'), [])
        malformed = (body + b' extra=0', body + b' unknown',
            body.replace(b'op=1 ', b'op=01 '), body.replace(b'seq=3..3 ', b'seq=03..3 '),
            body.replace(b'token=0 ', b'token=0x0 '), body.replace(b'error=0 ', b'error=-0 '),
            body.replace(b' origin_kind=native-osal', b''),
            body.replace(b'origin_kind=native-osal', b'origin_kind=unknown'))
        for value in malformed:
            with self.subTest(value=value):
                self.assertEqual(checker.parse_console(b'/OBS ' + value + b'\r\n'), [])
        with self.assertRaisesRegex(ValueError, 'duplicate JSON key'):
            checker.parse_console(b'/OBS ' + body + b' op=1\r\n')
        for value in (raw[:-2], raw[:-1]):
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, 'truncated evidence trace'):
                checker.parse_console(value)
        rows = [checker.parse_console(prefix + body + b'\r\n')[0] for prefix in (b"'; elOBS ", b'/OBS ')]
        self.assertEqual(rows[0]['fields'], rows[1]['fields'])
        failed, = checker.parse_console(raw.replace(b'readback_closed=1 error=0', b'readback_closed=0 error=-5'))
        self.assertEqual((failed['fields']['readback_closed'], failed['fields']['error']), ('0', '-5'))
        self.assertNotIn('verified', failed)

    def test_slash_transfer_reaches_actual_transport_without_waiving_response_binding(self):
        with tempfile.TemporaryDirectory() as temporary:
            run, manifest, _, events, build = host_test_transport(Path(temporary))
            first, rest = (run / 'console.log').read_bytes().split(b'\n', 1)
            self.assertTrue(first.startswith(b'OBS FUNCTIONAL_CAMERA_TRANSFER '))
            self.assertNotIn(b'origin_kind=', first)
            raw = b'/OBS ' + first[4:] + b' origin_kind=native-osal\r\n' + rest
            (run / 'console.log').write_bytes(raw)
            runner = manifest['functional_camera_runtime']
            runner['console_sha256_at_close'] = checker.sha(raw)
            (run / 'functional-camera-runner.json').write_text(json.dumps(runner))
            rows = checker.parse_console(raw)
            self.assertIn('console_prefix_diagnostic', rows[0])
            self.assertTrue(checker.check_transport(run, manifest, rows, events, build)['verified'])
            for key, value in (('model_instance', '0x64'), ('op', '2'), ('source', '0x80020002'),
                ('native_fnv', '0x1'), ('returned_fnv', '0x1'), ('destination_fnv', '0x1'),
                ('returned_bytes', '127'), ('readback_closed', '0'), ('error', '-5')):
                changed = copy.deepcopy(rows)
                changed[0]['fields'][key] = value
                with self.subTest(key=key), self.assertRaises(ValueError):
                    checker.check_transport(run, manifest, changed, events, build)
            with self.assertRaisesRegex(ValueError, 'not fully consumed'):
                checker.check_transport(run, manifest, rows[1:], events, build)

    def test_lwo_control_TTS_exact_formatter_UIPC_offsets_endings_and_no_success_claim(self):
        self.assertEqual(checker.sha(LWO_CONTROL_TTS_RECORD),
                         '453c6d8d286760f6b2b09fc3512133a146660c87e53f966dd20dd74f6d0a3bf6')
        guest, kernel = LWO_CONTROL_TTS_RECORD[4:-2].split(b'[ ', 1)
        kernel = b'[ ' + kernel
        original, = checker.parse_console(guest + b'\r\n')
        before = b'boot\rprogress\r\nordinary\n'
        for prefix in (b'', b'OBS ', b'/ # OBS '):
            for ending in (b'\n', b'\r\n'):
                raw = before + prefix + guest + kernel + ending
                with self.subTest(prefix=prefix, ending=ending):
                    row, = checker.parse_console(raw)
                    self.assertEqual(row['fields'], original['fields'])
                    self.assertEqual(len(row['fields']), 12)
                    self.assertNotIn('diagnostic', row)
                    self.assertNotIn('verified', row)
                    self.assertEqual(row['line'], 4)
                    note = row['kernel_diagnostic']
                    self.assertEqual(note['raw_lf_line'], 3)
                    self.assertEqual(note['cause'], 'unknown')
                    self.assertEqual(note['payload']['byte_offset'], len(before) + len(prefix))
                    self.assertEqual(note['byte_offset'], len(before) + len(prefix) + len(guest))
                    self.assertEqual(note['line_ending'].encode(), ending)
                    for part in (note, note['payload']):
                        start, size = part['byte_offset'], part['bytes']
                        self.assertEqual(raw[start:start + size], part['raw'].encode())
                        self.assertEqual(checker.sha(raw[start:start + size]), part['sha256'])
                    notes = checker.check_control(None, [row], {})
                    self.assertFalse(notes['required'])
                    self.assertFalse(notes['verified'])
                    self.assertFalse(notes['capture_verified'])
                    self.assertFalse(notes['physical_asic_compatibility_verified'])

    def test_lwo_control_TTS_unknown_tail_wrong_family_ret_and_truncation_fail_closed(self):
        guest, kernel = LWO_CONTROL_TTS_RECORD[:-2].split(b'[ ', 1)
        kernel = b'[ ' + kernel
        bad_tails = (kernel.replace(b'5584.789973', b'05584.789973'),
                     kernel.replace(b'5584.789973', b'5584.78997'),
                     kernel.replace(b'81cf61c4', b'81CF61C4'), kernel.replace(b'M=1', b'M=0'),
                     kernel.replace(b'C=0', b'C=1'), kernel.replace(b'S=0', b'S=1'),
                     kernel.replace(b'A=1', b'A=0'), kernel + b' extra', kernel + kernel,
                     b'unknown trailer', b' ' + kernel, kernel[:-1],
                     b'[ 5584.789973] UDIF: cdev_ioctl() Line 100: uipc: warning ret = -1022',
                     b'[ 5584.789973] UDIF: cdev_ioctl() Line 100: uipc: warning ret = -1021')
        for tail in bad_tails:
            with self.subTest(tail=tail):
                row, = checker.parse_console(guest + tail + b'\n')
                self.assertIn('diagnostic', row)
                self.assertNotIn('kernel_diagnostic', row)
                with self.assertRaisesRegex(ValueError, 'malformed control resource diagnostic'):
                    checker.check_control(None, [row], {})
        for truncated in (LWO_CONTROL_TTS_RECORD[:-2], LWO_CONTROL_TTS_RECORD[:-1]):
            with self.subTest(truncated=truncated), self.assertRaisesRegex(ValueError, 'truncated evidence trace'):
                checker.parse_console(truncated)

    def test_lwo_control_TTS_requires_every_ordered_typed_field_complete_reads_and_duplicate_guard(self):
        guest, kernel = LWO_CONTROL_TTS_RECORD[:-2].split(b'[ ', 1)
        kernel = b'[ ' + kernel
        parts = guest.split(b' ')
        malformed = [b' '.join(parts[:index] + parts[index + 1:]) for index in range(2, len(parts))]
        changes = ((b'pid=259 tid=381', b'tid=381 pid=259'), (b'pid=259', b'pid=0259'),
                   (b'tid=381', b'tid=9223372036854775808'),
                   (b'appfw_base=0x7f4535b000', b'appfw_base=0xffff'),
                   (b'appfw_base=0x7f4535b000', b'appfw_base=0x7ff0000000'),
                   (b'table_va=0x5f66b08', b'table_va=0x5f66b09'),
                   (b'address=0x7f4b2c1b08', b'address=0x7f4b2c1b09'),
                   (b'bytes=144', b'bytes=143'), (b'reads=144/144', b'reads=-1/144'),
                   (b'reads=144/144', b'reads=144/143'), (b'unchanged=1', b'unchanged=0'),
                   (b'atomic_snapshot=0', b'atomic_snapshot=1'), (b'raw_before=1a', b'raw_before=1A'),
                   (b'raw_before=1a', b'raw_before=00'), (b'raw_after=1a', b'raw_after=1a00'),
                   (b'ownership_verified=0', b'ownership_verified=1'))
        malformed += [guest.replace(old, new, 1) for old, new in changes]
        malformed += [guest + b' extra=0']
        for payload in malformed:
            with self.subTest(payload=payload):
                row, = checker.parse_console(payload + kernel + b'\n')
                self.assertIn('diagnostic', row)
                self.assertNotIn('kernel_diagnostic', row)
        for duplicate in (guest + b' pid=259', guest.replace(b'tid=381', b'tid=381 tid=381', 1)):
            with self.subTest(duplicate=duplicate), self.assertRaisesRegex(ValueError, 'duplicate'):
                checker.parse_console(duplicate + kernel + b'\n')

    def test_sf05_exact_echo_and_UDIF_bytes_keep_offsets_endings_and_legacy_lines(self):
        fixtures = ((SF05_TRANSFER_ECHO, 'c5676efdfa21f89ba61a8a7c9284621623076c70a40f9b3e03a3dc6e3021f15d'),
                    (SF05_AUDIT_BYTES, '31f424334f1372d7fae30dc46657b6ae86f82b23ba207ffe541534962129cdb3'),
                    (SF05_FACE_SOURCE_BOUND, '69bfddf4e9f728bef3d0b8f5d672abe5656da2338db4e8eb63c98011e6203af9'))
        before, after = b'boot\rprogress\r\nordinary\n', b'OBS FUNCTIONAL_CAMERA_TRANSFER op=2 error=0\n'
        for fixture, digest in fixtures:
            self.assertEqual(checker.sha(fixture), digest)
            for ending in (b'\n', b'\r\n'):
                raw = before + fixture[:-2] + ending + after
                with self.subTest(digest=digest, ending=ending):
                    row, following = checker.parse_console(raw)
                    self.assertEqual((row['line'], following['line']), (4, 5))
                    self.assertNotIn('diagnostic', row)
                    self.assertNotIn('verified', row)
                    key = 'console_prefix_diagnostic' if fixture is SF05_TRANSFER_ECHO else 'kernel_diagnostic'
                    note = row[key]
                    self.assertEqual(note['raw_lf_line'], 3)
                    self.assertEqual(note['cause'], 'unknown')
                    self.assertEqual(note['line_ending'].encode(), ending)
                    for part in (note, note['payload']):
                        start, size = part['byte_offset'], part['bytes']
                        self.assertEqual(raw[start:start + size], part['raw'].encode())
                        self.assertEqual(checker.sha(raw[start:start + size]), part['sha256'])
                    self.assertEqual(following['fields'], dict(op='2', error='0'))
        echo, = checker.parse_console(SF05_TRANSFER_ECHO)
        self.assertEqual((echo['fields']['seq'], echo['fields']['op']), ('30..30', '7'))
        self.assertEqual(echo['console_prefix_diagnostic']['raw'], "'; elOBS ")
        audit, = checker.parse_console(SF05_AUDIT_BYTES)
        self.assertEqual(len(bytes.fromhex(audit['fields']['raw'])), 128)
        source, = checker.parse_console(SF05_FACE_SOURCE_BOUND)
        self.assertEqual(source['fields']['op'], '0x25')

    def test_sf05_UDIF_families_reject_unknown_suffix_noncanonical_missing_and_duplicate_fields(self):
        for fixture in (SF05_AUDIT_BYTES, SF05_FACE_SOURCE_BOUND):
            guest, kernel = fixture[4:-2].split(b'[ ', 1)
            kernel = b'[ ' + kernel
            bad_tails = (kernel.replace(b'-1022', b'-1021'), kernel.replace(b'-1022', b'0'),
                         kernel.replace(b'Line 100', b'Line 101'), kernel + b' extra', kernel + kernel,
                         kernel.replace(b'[ 5', b'[ 05'), b' ' + kernel,
                         ZFQ_VDF_RECORD[ZFQ_VDF_RECORD.index(b'[ '):-2])
            for suffix in bad_tails:
                with self.subTest(fixture=fixture[:45], suffix=suffix):
                    row, = checker.parse_console(guest + suffix + b'\n')
                    self.assertIn('diagnostic', row)
                    self.assertNotIn('kernel_diagnostic', row)
            parts = guest.split(b' ')
            malformed = [b' '.join(parts[:i] + parts[i + 1:]) for i in range(1, len(parts))]
            malformed += [guest + b' extra=0', guest.replace(b'pid=259 tid=383', b'tid=383 pid=259'),
                          guest.replace(b'pid=259', b'pid=0259'), guest.replace(b'pid=259', b'pid=2147483648'),
                          guest.replace(b'tid=383', b'tid=9223372036854775808')]
            if fixture is SF05_AUDIT_BYTES:
                malformed += [guest.replace(b'bytes=128', b'bytes=129'), guest.replace(b'offset=768', b'offset=769'),
                              guest.replace(b'sequence=50', b'sequence=0'), guest.replace(b'raw=00', b'raw=0'),
                              guest.replace(b'offset=768', b'offset=4096')]
            else:
                malformed += [guest.replace(b'op=0x25', b'op=0x26'), guest.replace(b'op=0x25', b'op=0x025'),
                              guest.replace(b'caller_va=0x35528ac', b'caller_va=0x35528ad'),
                              guest.replace(b'reads=4/4', b'reads=04/4'), guest.replace(b'rc=0', b'rc=-0'),
                              guest.replace(b'producer=process-local-software-owner', b'producer=unknown'),
                              guest.replace(b'capture_verified=0', b'capture_verified=1')]
            for payload in malformed:
                with self.subTest(payload=payload):
                    row, = checker.parse_console(payload + kernel + b'\r\n')
                    self.assertIn('diagnostic', row)
                    self.assertNotIn('kernel_diagnostic', row)
            with self.assertRaises(ValueError):
                checker.parse_console(guest + b' pid=259' + kernel + b'\n')
            for truncated in (guest + kernel, guest + kernel + b'\r'):
                with self.assertRaisesRegex(ValueError, 'truncated evidence trace'):
                    checker.parse_console(truncated)
        failed, = checker.parse_console(SF05_FACE_SOURCE_BOUND.replace(b'reads=4/4', b'reads=-1/-1').replace(
            b'rc=0 producer=', b'rc=-80 producer='))
        self.assertEqual(failed['fields']['rc'], '-80')
        self.assertIn('kernel_diagnostic', failed)
        self.assertNotIn('verified', failed)

    def test_sf05_echo_requires_complete_formatter_exact_prefix_and_original_ending(self):
        prefix = b"'; elOBS "
        body = SF05_TRANSFER_ECHO[len(prefix):-2]
        parts = body.split(b' ')
        malformed = [b' '.join(parts[:i] + parts[i + 1:]) for i in range(1, len(parts))]
        malformed += [body + b' extra=0', body + b' unknown suffix', body.replace(b'op=7', b'op=15'),
                      body.replace(b'op=7', b'op=07'), body.replace(b'request_bytes=32', b'request_bytes=16'),
                      body.replace(b'seq=30..30', b'seq=030..30'), body.replace(b'token=0', b'token=0x0'),
                      body.replace(b'error=0', b'error=-0'), body.replace(b'readback_closed=1', b'readback_closed=0'),
                      body.replace(b'origin_kind=native-osal', b'origin_kind=unknown')]
        for payload in malformed:
            with self.subTest(payload=payload):
                self.assertEqual(checker.parse_console(prefix + payload + b'\r\n'), [])
        for unknown_prefix in (b'0OBS ', b'00OBS ', b'xOBS ', b"'; eOBS ", b"'; elseOBS ", b" '; elOBS "):
            with self.subTest(prefix=unknown_prefix):
                self.assertEqual(checker.parse_console(unknown_prefix + body + b'\r\n'), [])
        with self.assertRaises(ValueError):
            checker.parse_console(prefix + body + b' op=7\n')
        for truncated in (SF05_TRANSFER_ECHO[:-2], SF05_TRANSFER_ECHO[:-1]):
            with self.assertRaisesRegex(ValueError, 'truncated evidence trace'):
                checker.parse_console(truncated)
        failed, = checker.parse_console(SF05_TRANSFER_ECHO.replace(b'readback_closed=1 error=0',
                                                                  b'readback_closed=0 error=-5'))
        self.assertEqual(failed['fields']['error'], '-5')
        self.assertIn('console_prefix_diagnostic', failed)
        self.assertNotIn('verified', failed)

    def test_sf05_echo_still_requires_actual_nonce_op_origin_result_and_Core_success(self):
        with tempfile.TemporaryDirectory(prefix='HOST_TEST_sf05_echo_transport_') as directory:
            run, manifest, original_rows, events, build = host_test_transport(Path(directory))
            lines = (run / 'console.log').read_bytes().splitlines(keepends=True)
            raw = b"'; elOBS " + lines[0][4:-1] + b' origin_kind=native-osal\r\n' + b''.join(lines[1:])
            recovered = checker.parse_console(raw)
            self.assertEqual(len(recovered), len(original_rows))
            self.assertIn('console_prefix_diagnostic', recovered[0])
            self.assertTrue(checker.check_transport(run, manifest, recovered, events, build)['verified'])
            for key, value in (('model_instance', '0x64'), ('op', '2'), ('source', '0x80020002'),
                               ('native_fnv', '0x1'), ('returned_fnv', '0x1'), ('destination_fnv', '0x1'),
                               ('returned_bytes', '127'), ('readback_closed', '0'), ('error', '-5')):
                changed = copy.deepcopy(recovered)
                changed[0]['fields'][key] = value
                with self.subTest(key=key), self.assertRaises(ValueError):
                    checker.check_transport(run, manifest, changed, events, build)
            for kind in ('core_result', 'response'):
                changed = copy.deepcopy(events)
                next(event for event in changed if event['kind'] == kind)['actual_c_result'] = -5
                with self.subTest(kind=kind), self.assertRaises(ValueError):
                    checker.check_transport(run, manifest, recovered, changed, build)
            with self.assertRaisesRegex(ValueError, 'not fully consumed'):
                checker.check_transport(run, manifest, recovered[1:], events, build)
            self.assertEqual(original_rows[0]['fields']['model_instance'], '0x63')

    def test_original_sf05_all_affected_records_bind_exact_bytes_when_private_console_is_available(self):
        path = checker.RUNTIME / 'menu-runs/run-05b0sf_b/console.log'
        if not path.exists():
            self.skipTest('private 05b0 console is excluded from the public package')
        before = path.stat()
        raw = path.read_bytes()
        self.assertEqual(checker.sha(raw), SF05_CONSOLE_SHA256)
        rows = checker.parse_console(raw)
        for fixture, offset, lf, legacy, note_key in (
                (SF05_TRANSFER_ECHO, 2638989, 20041, 21072, 'console_prefix_diagnostic'),
                (SF05_AUDIT_BYTES, 2217466, 18826, 19830, 'kernel_diagnostic'),
                (SF05_FACE_SOURCE_BOUND, 2604975, 19969, 20999, 'kernel_diagnostic')):
            with self.subTest(offset=offset):
                self.assertEqual(raw[offset:offset + len(fixture)], fixture)
                self.assertEqual(raw.split(b'\n')[lf - 1] + b'\n', fixture)
                self.assertEqual(raw.splitlines(keepends=True)[legacy - 1], fixture)
                row, = [row for row in rows if row['line'] == legacy]
                self.assertNotIn('diagnostic', row)
                note = row[note_key]
                self.assertEqual(note['raw_lf_line'], lf)
                for part in (note, note['payload']):
                    self.assertEqual(raw[part['byte_offset']:part['byte_offset'] + part['bytes']], part['raw'].encode())
                    self.assertEqual(checker.sha(part['raw'].encode()), part['sha256'])
        self.assertEqual(len([row for row in rows if row['tag'] == 'FUNCTIONAL_CAMERA_TRANSFER']), 27)
        self.assertFalse(any('diagnostic' in row for row in rows))
        # FULL_PINMEM_REPLY_QUEUED is exclusively owned by the separate graph checker.
        self.assertFalse(any(row['tag'] == 'FULL_PINMEM_REPLY_QUEUED' for row in rows))
        after = path.stat()
        self.assertEqual((before.st_ino, before.st_size, before.st_mtime_ns),
                         (after.st_ino, after.st_size, after.st_mtime_ns))
        self.assertEqual(checker.sha(path.read_bytes()), SF05_CONSOLE_SHA256)

    """Pure parser/layout joins; no compiler, codec, VM, or acceptance checker."""

    def test_original_transfer_bytes_and_framing_keep_both_payloads(self):
        self.assertEqual(checker.sha(E6MX_TRANSFER_RECORD), '9614beb578af7a1ff9d50c2571d813a88aa5334f6e6ccd5296192a0fcae5933c')
        guest, kernel = E6MX_TRANSFER_RECORD[:-2].split(b'[ ', 1)
        kernel = b'[ ' + kernel
        row, = checker.parse_console(E6MX_TRANSFER_RECORD)
        plain, = checker.parse_console(guest + b'\r\n')
        self.assertEqual(row['fields'], plain['fields'])
        self.assertEqual(len(row['fields']), 19)
        self.assertEqual(row['fields']['op'], '11')
        self.assertEqual(row['fields']['seq'], '27..28')
        self.assertNotIn('diagnostic', row)
        self.assertNotIn('verified', row)
        self.assertNotIn('capture_verified', row)
        note = row['kernel_diagnostic']
        self.assertEqual(note, dict(raw=kernel.decode(), bytes=len(kernel), sha256=checker.sha(kernel),
            byte_offset=len(guest), raw_lf_line=1, cause='unknown', line_ending='\r\n',
            payload=dict(raw=guest[4:].decode(), bytes=len(guest) - 4, sha256=checker.sha(guest[4:]), byte_offset=4)))

    def test_zd4_startup_predecessor_exact_bytes_offsets_endings_and_no_claims(self):
        self.assertEqual(checker.sha(ZD4_STARTUP_PREDECESSOR_RECORD),
                         '973d878657d5ff04a4bc6a8ae4f30160825767eaf43e12efe459397876e896aa')
        guest, kernel = ZD4_STARTUP_PREDECESSOR_RECORD[4:-2].split(b'[ ', 1)
        kernel = b'[ ' + kernel
        original, = checker.parse_console(guest + b'\r\n')
        self.assertEqual(list(original['fields']), list(StartupControlEvidenceTests.predecessor()))
        self.assertEqual(len(original['fields']), 15)
        before, after = b'boot\rprogress\r\nordinary\n', b'OBS FUNCTIONAL_CAMERA_TRANSFER op=2 error=0\n'
        for prefix in (b'', b'OBS ', b'/ # OBS '):
            for ending in (b'\n', b'\r\n'):
                raw = before + prefix + guest + kernel + ending + after
                with self.subTest(prefix=prefix, ending=ending):
                    row, following = checker.parse_console(raw)
                    self.assertEqual(row['fields'], original['fields'])
                    self.assertNotIn('diagnostic', row)
                    self.assertNotIn('verified', row)
                    self.assertEqual((row['line'], following['line']), (4, 5))
                    note = row['kernel_diagnostic']
                    self.assertEqual(note['raw'], kernel.decode())
                    self.assertEqual(note['cause'], 'unknown')
                    self.assertEqual(note['raw_lf_line'], 3)
                    self.assertEqual(note['line_ending'].encode(), ending)
                    self.assertEqual(note['payload']['byte_offset'], len(before) + len(prefix))
                    self.assertEqual(note['byte_offset'], len(before) + len(prefix) + len(guest))
                    for part in (note, note['payload']):
                        start, size = part['byte_offset'], part['bytes']
                        self.assertEqual(raw[start:start + size], part['raw'].encode())
                        self.assertEqual(checker.sha(raw[start:start + size]), part['sha256'])
                    self.assertEqual(following['fields'], dict(op='2', error='0'))

    def test_zd4_startup_predecessor_exact_trailer_family_and_truncation(self):
        guest, kernel = ZD4_STARTUP_PREDECESSOR_RECORD[:-2].split(b'[ ', 1)
        kernel = b'[ ' + kernel
        wrong_kind = ZFQ_VDF_RECORD[ZFQ_VDF_RECORD.index(b'[ '):-2]
        invalid = (kernel.replace(b'-1022', b'-1021'), kernel.replace(b'-1022', b'0'),
                   kernel.replace(b'-1022', b'-10220'), kernel.replace(b'Line 100', b'Line 101'),
                   kernel.replace(b'5546.369864', b'05546.369864'), kernel.replace(b'5546.369864', b'5546.36986'),
                   kernel.replace(b'warning', b'unknown'), kernel + b' extra', kernel + kernel,
                   b'unknown trailer', b' ' + kernel, kernel[:-1], wrong_kind)
        for suffix in invalid:
            with self.subTest(suffix=suffix):
                row, = checker.parse_console(guest + suffix + b'\n')
                self.assertIn('diagnostic', row)
                self.assertNotIn('kernel_diagnostic', row)
        for tag in (b'FUNCTIONAL_STARTUP_CONTROL', b'FUNCTIONAL_STARTUP_CONTROL_PREDECESSORS_EXTRA',
                    b'FUNCTIONAL_STILL_FORMAT_PREDECESSORS', b'FUNCTIONAL_CAMERA_CONTROL_COMMIT',
                    b'FUNCTIONAL_VDF_PATH_COMPLETE'):
            with self.subTest(tag=tag):
                row, = checker.parse_console(ZD4_STARTUP_PREDECESSOR_RECORD.replace(
                    b'FUNCTIONAL_STARTUP_CONTROL_PREDECESSORS', tag, 1))
                self.assertIn('diagnostic', row)
                self.assertNotIn('kernel_diagnostic', row)
        for raw in (ZD4_STARTUP_PREDECESSOR_RECORD[:-2], ZD4_STARTUP_PREDECESSOR_RECORD[:-1],
                    guest + kernel + b'\r'):
            with self.subTest(raw=raw), self.assertRaisesRegex(ValueError, 'truncated evidence trace'):
                checker.parse_console(raw)

    def test_zd4_startup_predecessor_full_order_schema_ranges_and_duplicates(self):
        guest, kernel = ZD4_STARTUP_PREDECESSOR_RECORD[:-2].split(b'[ ', 1)
        kernel = b'[ ' + kernel
        parts = guest.split(b' ')
        for index in range(2, len(parts)):
            with self.subTest(missing=parts[index]):
                row, = checker.parse_console(b' '.join(parts[:index] + parts[index + 1:]) + kernel + b'\n')
                self.assertIn('diagnostic', row)
                self.assertNotIn('kernel_diagnostic', row)
        changes = ((b'pid=259 tid=383', b'tid=383 pid=259'), (b'pid=259', b'pid=0259'),
                   (b'pid=259', b'pid=0'), (b'pid=259', b'pid=2147483648'), (b'tid=383', b'tid=-0'),
                   (b'tid=383', b'tid=9223372036854775808'), (b'accepted=1', b'accepted=2'),
                   (b'initial_mode_requests=1', b'initial_mode_requests=4294967296'),
                   (b'initial_mode_AP_consumed=1', b'initial_mode_AP_consumed=01'),
                   (b'all13_AP_consumed=1', b'all13_AP_consumed=2'),
                   (b'still_format_cycle=1', b'still_format_cycle=0x1'),
                   (b'still_format_cycle=1', b'still_format_cycle=18446744073709551616'),
                   (b'model_instance=805113156714136530', b'model_instance=18446744073709551616'),
                   (b'source_business_equivalent=0', b'source_business_equivalent=1'),
                   (b'physical_ASIC_verified=0', b'physical_ASIC_verified=1'),
                   (b'capture_verified=0', b'capture_verified=1'))
        for old, new in changes:
            with self.subTest(field=old, value=new):
                row, = checker.parse_console(guest.replace(old, new, 1) + kernel + b'\n')
                self.assertIn('diagnostic', row)
                self.assertNotIn('kernel_diagnostic', row)
        row, = checker.parse_console(guest + b' host_ready=1' + kernel + b'\n')
        self.assertIn('diagnostic', row)
        self.assertNotIn('kernel_diagnostic', row)
        for changed in (guest + b' model_instance=1', guest.replace(b'accepted=1', b'accepted=1 accepted=0', 1)):
            with self.subTest(duplicate=changed), self.assertRaises(ValueError):
                checker.parse_console(changed + kernel + b'\n')

    def test_original_zd4_startup_predecessor_raw_LF_binding_when_private_run_is_available(self):
        path = checker.RUNTIME / 'menu-runs/run-zd4qa2vi/console.log'
        if not path.exists():
            self.skipTest('private original zd4 console is not part of the public package')
        before = path.stat()
        raw = path.read_bytes()
        self.assertEqual(checker.sha(raw), ZD4_CONSOLE_SHA256)
        self.assertEqual(raw[ZD4_STARTUP_PREDECESSOR_OFFSET:
                             ZD4_STARTUP_PREDECESSOR_OFFSET + len(ZD4_STARTUP_PREDECESSOR_RECORD)],
                         ZD4_STARTUP_PREDECESSOR_RECORD)
        self.assertEqual(raw.split(b'\n')[20230] + b'\n', ZD4_STARTUP_PREDECESSOR_RECORD)
        self.assertEqual(raw.splitlines(keepends=True)[21223], ZD4_STARTUP_PREDECESSOR_RECORD)
        row = next(row for row in checker.parse_console(raw) if row['line'] == 21224)
        self.assertNotIn('diagnostic', row)
        self.assertNotIn('verified', row)
        self.assertEqual((row['fields']['still_format_cycle'], row['fields']['model_instance']),
                         ('1', '805113156714136530'))
        note = row['kernel_diagnostic']
        self.assertEqual(note['raw_lf_line'], 20231)
        self.assertEqual(note['payload']['byte_offset'], ZD4_STARTUP_PREDECESSOR_OFFSET + 4)
        self.assertEqual(note['cause'], 'unknown')
        for part in (note, note['payload']):
            self.assertEqual(raw[part['byte_offset']:part['byte_offset'] + part['bytes']], part['raw'].encode())
            self.assertEqual(checker.sha(part['raw'].encode()), part['sha256'])
        after = path.stat()
        self.assertEqual((before.st_ino, before.st_size, before.st_mtime_ns),
                         (after.st_ino, after.st_size, after.st_mtime_ns))
        self.assertEqual(checker.sha(path.read_bytes()), ZD4_CONSOLE_SHA256)

    def test_zfq_exact_VDF_formatter_and_paired_UIPC_keep_bytes_offsets_and_endings(self):
        self.assertEqual(checker.sha(ZFQ_VDF_RECORD), '2a104e0840dae649b9691461410b282236ff7a9c768f9df476f71d37dd6c69c0')
        guest, kernel = ZFQ_VDF_RECORD[:-2].split(b'[ ', 1)
        guest, kernel = guest[4:], b'[ ' + kernel
        original, = checker.parse_console(guest + b'\r\n')
        before, after = b'boot\rprogress\r\nordinary\n', b'OBS FUNCTIONAL_CAMERA_TRANSFER op=2 error=0\n'
        for prefix in (b'', b'OBS ', b'/ # OBS '):
            for ending in (b'\n', b'\r\n'):
                raw = before + prefix + guest + kernel + ending + after
                with self.subTest(prefix=prefix, ending=ending):
                    row, following = checker.parse_console(raw)
                    self.assertEqual(row['fields'], original['fields'])
                    self.assertNotIn('diagnostic', row)
                    self.assertNotIn('verified', row)
                    self.assertEqual((row['line'], following['line']), (4, 5))
                    note = row['kernel_diagnostic']
                    self.assertEqual(note['raw'], kernel.decode())
                    self.assertEqual(note['cause'], 'unknown')
                    self.assertEqual(note['raw_lf_line'], 3)
                    self.assertEqual(note['payload']['byte_offset'], len(before) + len(prefix))
                    self.assertEqual(note['byte_offset'], len(before) + len(prefix) + len(guest))
                    self.assertEqual(note['line_ending'].encode(), ending)
                    for part in (note, note['payload']):
                        start, size = part['byte_offset'], part['bytes']
                        self.assertEqual(raw[start:start + size], part['raw'].encode())
                        self.assertEqual(checker.sha(raw[start:start + size]), part['sha256'])
                    self.assertEqual(following['fields'], dict(op='2', error='0'))
        for event in (b'REQUEST_FREE', b'SEND', b'COMPLETE', b'RECEIVE', b'AP_FREE'):
            row, = checker.parse_console(ZFQ_VDF_RECORD.replace(b'PATH_COMPLETE', b'PATH_' + event, 1))
            self.assertEqual(row['fields'], original['fields'])
            self.assertIn('kernel_diagnostic', row)

    def test_huti_complete_vdf_family_exact_ioctl_offsets_endings_and_no_claims(self):
        guest = ZFQ_VDF_RECORD[:-2].split(b'[ ', 1)[0][4:]
        kernel = b'[ 5620.916062] UDIF: cdev_ioctl() Line 100: uipc: warning ret = -1022'
        before = b'boot\rprogress\r\nordinary\n'
        for event in (b'REQUEST_FREE', b'SEND', b'COMPLETE', b'RECEIVE', b'AP_FREE'):
            payload = guest.replace(b'PATH_COMPLETE', b'PATH_' + event, 1)
            clean, = checker.parse_console(payload + b'\n')
            for prefix in (b'', b'OBS ', b'/ # OBS '):
                for ending in (b'\n', b'\r\n'):
                    with self.subTest(event=event, prefix=prefix, ending=ending):
                        raw = before + prefix + payload + kernel + ending
                        row, = checker.parse_console(raw)
                        self.assertEqual(row['fields'], clean['fields'])
                        self.assertNotIn('diagnostic', row)
                        self.assertNotIn('verified', row)
                        note = row['kernel_diagnostic']
                        self.assertEqual(note['raw'], kernel.decode())
                        self.assertEqual(note['cause'], 'unknown')
                        self.assertEqual(note['raw_lf_line'], 3)
                        self.assertEqual(note['line_ending'].encode(), ending)
                        for part in (note, note['payload']):
                            start, size = part['byte_offset'], part['bytes']
                            self.assertEqual(raw[start:start + size], part['raw'].encode())
                            self.assertEqual(checker.sha(raw[start:start + size]), part['sha256'])
        for bad in (kernel.replace(b'-1022', b'-1021'), kernel.replace(b'Line 100', b'Line 101'),
                    kernel.replace(b'5620.916062', b'05620.916062'), kernel + b' extra',
                    kernel + kernel, b' ' + kernel):
            with self.subTest(bad=bad):
                row, = checker.parse_console(guest + bad + b'\n')
                self.assertIn('diagnostic', row)
                self.assertNotIn('kernel_diagnostic', row)

    def test_zfq_unknown_UIPC_suffix_family_ambiguity_and_truncation_fail_closed(self):
        guest, kernel = ZFQ_VDF_RECORD[:-2].split(b'[ ', 1)
        kernel = b'[ ' + kernel
        udif = E6MX_TRANSFER_RECORD[E6MX_TRANSFER_RECORD.index(b'[ '):-2]
        invalid = (kernel.replace(b'5541.864466', b'05541.864466'), kernel.replace(b'5541.864466', b'5541.86446'),
                   kernel.replace(b'81cf61c4', b'81CF61C4'), kernel.replace(b'81cf61c4', b'81cf61c'),
                   kernel.replace(b'M=1', b'M=0'), kernel.replace(b'C=0', b'C=1'), kernel.replace(b'A=1', b'A=0'),
                   kernel.replace(b'free_dynamic_msgq_id', b'unknown_operation'), kernel + b' extra',
                   kernel + kernel, b'unknown trailer', b' ' + kernel, kernel[:-1], udif.replace(b'-1022', b'-1021'))
        for suffix in invalid:
            with self.subTest(suffix=suffix):
                row, = checker.parse_console(guest + suffix + b'\n')
                self.assertIn('diagnostic', row)
                self.assertNotIn('kernel_diagnostic', row)
        for tag in (b'FUNCTIONAL_VDF_PATH_OTHER', b'FUNCTIONAL_VDF_PATH_COMPLETE_EXTRA',
                    b'FUNCTIONAL_CAMERA_TRANSFER', b'FUNCTIONAL_CAMERA_CONTROL_COMMIT'):
            row, = checker.parse_console(ZFQ_VDF_RECORD.replace(b'FUNCTIONAL_VDF_PATH_COMPLETE', tag, 1))
            self.assertIn('diagnostic', row)
            self.assertNotIn('kernel_diagnostic', row)
        for legacy in (E6MX_CONTROL_COMMIT[:-2].replace(b'CONTROL_COMMIT ', b'CONTROL_PROBE ', 1),
                       E6MX_TRANSFER_RECORD[:E6MX_TRANSFER_RECORD.index(b'[ ')]):
            row, = checker.parse_console(legacy + kernel + b'\n')
            self.assertIn('diagnostic', row)
            self.assertNotIn('kernel_diagnostic', row)
        for raw in (ZFQ_VDF_RECORD[:-2], ZFQ_VDF_RECORD[:-1], guest + kernel + b'\r'):
            with self.subTest(raw=raw), self.assertRaisesRegex(ValueError, 'truncated evidence trace'):
                checker.parse_console(raw)

    def test_zfq_VDF_full_formatter_order_types_lengths_and_duplicate_keys(self):
        guest, kernel = ZFQ_VDF_RECORD[:-2].split(b'[ ', 1)
        kernel = b'[ ' + kernel
        parts = guest.split(b' ')
        for index in range(2, len(parts)):
            with self.subTest(missing=parts[index]):
                row, = checker.parse_console(b' '.join(parts[:index] + parts[index + 1:]) + kernel + b'\n')
                self.assertIn('diagnostic', row)
                self.assertNotIn('kernel_diagnostic', row)
        changes = ((b'pid=259 tid=382', b'tid=382 pid=259'), (b'pid=259', b'pid=0259'),
                   (b'phase=3', b'phase=4294967296'), (b'cycle=4', b'cycle=18446744073709551616'),
                   (b'source=0x81cf61c6', b'source=0x81CF61C6'), (b'command=0x152', b'command=0x150'),
                   (b'bytes=16', b'bytes=14'), (b'bridge_rc=0', b'bridge_rc=-2147483649'),
                   (b'original_fnv1a=e1b56c922a2b5cfb', b'original_fnv1a=E1b56c922a2b5cfb'),
                   (b'raw=0d205201100001800300010000eb8080', b'raw=0d205201100001800300010000eb808000'),
                   (b'canonical_bit_width8=0000000000000000', b'canonical_bit_width8=00000000000000'),
                   (b'realresultbytes=176', b'realresultbytes=168'), (b'model_result_bytes=176', b'model_result_bytes=168'),
                   (b'model_result_hex=01', b'model_result_hex=0100'), (b'capture_verified=0', b'capture_verified=1'))
        for old, new in changes:
            with self.subTest(field=old, value=new):
                row, = checker.parse_console(guest.replace(old, new, 1) + kernel + b'\n')
                self.assertIn('diagnostic', row)
                self.assertNotIn('kernel_diagnostic', row)
        for changed in (guest + b' extra=0', guest + b' model_result_hex=00',
                        guest.replace(b'cycle=4', b'cycle=4 cycle=4', 1)):
            with self.subTest(raw=changed):
                if b' extra=0' in changed:
                    row, = checker.parse_console(changed + kernel + b'\n')
                    self.assertIn('diagnostic', row)
                    self.assertNotIn('kernel_diagnostic', row)
                else:
                    with self.assertRaises(ValueError):
                        checker.parse_console(changed + kernel + b'\n')

    def test_zfq_diagnostic_or_missing_required_VDF_fields_raise_missing_not_KeyError(self):
        guest, kernel = ZFQ_VDF_RECORD[:-2].split(b'[ ', 1)
        transport = dict(transfers=[dict(opcode=8, origin=dict(destination=0x92840747, command=0x152))])
        malformed = [guest + b'unknown suffix\n', guest + b'[ ' + kernel + b' extra\n']
        for field in (b'cycle=4 ', b'ack_retained=0x7fb6b33140 ', b'pid=259 ', b'config_generation=5 '):
            malformed.append(guest.replace(b' ' + field, b' ', 1) + b'\n')
        for raw in malformed:
            row, = checker.parse_console(raw)
            row['line'] = 100
            original = copy.deepcopy(row)
            with self.subTest(raw=raw), self.assertRaisesRegex(checker.MissingEvidence,
                    'VDF FUNCTIONAL_VDF_PATH_COMPLETE line 100: missing '):
                checker.check_vdf_path(None, [row], transport)
            self.assertEqual(row, original)

    def test_zfq_framing_requires_actual_typed_result_and_original_VDF_lifecycle(self):
        guest, kernel = ZFQ_VDF_RECORD[:-2].split(b'[ ', 1)
        template, = checker.parse_console(guest + b'\n')
        kernel = b'[ ' + kernel
        with tempfile.TemporaryDirectory(prefix='HOST_TEST_zfq_VDF_join_') as directory:
            args = host_test_capture(Path(directory), (True, ('display', 0x152)))
            transport = checker.check_transport(*args)
            target = next(row for row in args[2] if row['tag'] == 'FUNCTIONAL_VDF_PATH_COMPLETE' and
                          row['fields']['command'] == '0x152')
            fields = dict(template['fields'])
            fields.update(target['fields'])
            for updates in ({}, dict(bridge_rc='-5'), dict(send_rc='-5'), dict(faults='1'),
                            dict(original_fnv1a='0000000000000000'), dict(source='0x81cf61c9'),
                            dict(cycle='1'), dict(phase='2'), dict(model_result_hex='00' + fields['model_result_hex'][2:])):
                changed_fields = dict(fields, **updates)
                raw = ('OBS ' + target['tag'] + ' ' + ' '.join(f'{key}={value}' for key, value in changed_fields.items())).encode()
                framed, = checker.parse_console(raw + kernel + b'\r\n')
                self.assertEqual(framed['fields'], changed_fields)
                self.assertIn('kernel_diagnostic', framed)
                framed['line'] = target['line']
                rows = [framed if row is target else row for row in args[2]]
                with self.subTest(updates=updates):
                    if updates:
                        with self.assertRaises(ValueError):
                            checker.check_vdf_path(args[0], rows, transport)
                    else:
                        self.assertTrue(checker.check_vdf_path(args[0], rows, transport)['verified'])
                        self.assertNotIn('capture_verified', framed)
            for rows in ([row for row in args[2] if row is not target], args[2] + [copy.deepcopy(target)],
                         [dict(row, line=transport['transfers'][0]['line']) if row is target else row for row in args[2]]):
                with self.subTest(lifecycle=rows), self.assertRaises(ValueError):
                    checker.check_vdf_path(args[0], rows, transport)
            failed, = checker.parse_console(guest.replace(b'bridge_rc=0', b'bridge_rc=-5', 1) + kernel + b'\n')
            self.assertEqual(failed['fields']['bridge_rc'], '-5')
            self.assertIn('kernel_diagnostic', failed)
            with self.assertRaises(checker.MissingEvidence):
                checker.check_vdf_path(args[0], [failed], dict(transport, transfers=[]))

    def test_original_zfq_console_binding_when_private_run_is_available(self):
        path = checker.RUNTIME / 'menu-runs/run-_zfqamkr/console.log'
        if not path.exists():
            self.skipTest('private original _zfq console is not part of the public package')
        before = path.stat()
        raw = path.read_bytes()
        self.assertEqual(checker.sha(raw), ZFQ_CONSOLE_SHA256)
        self.assertEqual(raw[ZFQ_VDF_OFFSET:ZFQ_VDF_OFFSET + len(ZFQ_VDF_RECORD)], ZFQ_VDF_RECORD)
        self.assertEqual(raw.count(b'\n', 0, ZFQ_VDF_OFFSET) + 1, 19487)
        row = next(row for row in checker.parse_console(raw) if row['line'] == 20465)
        self.assertEqual((row['fields']['cycle'], row['fields']['command']), ('4', '0x152'))
        note = row['kernel_diagnostic']
        self.assertEqual(note['raw_lf_line'], 19487)
        self.assertEqual(note['payload']['byte_offset'], ZFQ_VDF_OFFSET + 4)
        for part in (note, note['payload']):
            self.assertEqual(raw[part['byte_offset']:part['byte_offset'] + part['bytes']], part['raw'].encode())
        after = path.stat()
        self.assertEqual((before.st_ino, before.st_size, before.st_mtime_ns), (after.st_ino, after.st_size, after.st_mtime_ns))
        self.assertEqual(checker.sha(path.read_bytes()), ZFQ_CONSOLE_SHA256)

    def test_known_prefixes_original_endings_neighbors_and_raw_LF_offsets(self):
        guest, kernel = E6MX_TRANSFER_RECORD[:-2].split(b'[ ', 1)
        guest, kernel = guest[4:], b'[ ' + kernel
        before = b'boot\rprogress\r\nordinary\n'
        after = b'OBS FUNCTIONAL_CAMERA_TRANSFER op=2 error=0 readback_closed=1\n'
        for prefix in (b'', b'OBS ', b'/ # OBS '):
            for ending in (b'\n', b'\r\n'):
                raw = before + prefix + guest + kernel + ending + after
                with self.subTest(prefix=prefix, ending=ending):
                    row, following = checker.parse_console(raw)
                    note = row['kernel_diagnostic']
                    self.assertEqual((row['line'], following['line']), (4, 5))
                    self.assertEqual(note['raw_lf_line'], 3)
                    self.assertEqual(note['payload']['byte_offset'], len(before) + len(prefix))
                    self.assertEqual(note['byte_offset'], len(before) + len(prefix) + len(guest))
                    self.assertEqual(note['line_ending'].encode(), ending)
                    for part in (note, note['payload']):
                        start, size = part['byte_offset'], part['bytes']
                        self.assertEqual(raw[start:start + size], part['raw'].encode())
                        self.assertEqual(checker.sha(raw[start:start + size]), part['sha256'])
                    self.assertEqual(following['fields'], dict(op='2', error='0', readback_closed='1'))

    def test_unknown_kernel_tail_timestamp_family_or_truncation_is_not_framed(self):
        guest, kernel = E6MX_TRANSFER_RECORD[:-2].split(b'[ ', 1)
        kernel = b'[ ' + kernel
        for changed in (kernel.replace(b'-1022', b'-1021'), kernel.replace(b'-1022', b'0'),
                        kernel.replace(b'Line 100', b'Line 101'), kernel.replace(b'5583.762945', b'05583.762945'),
                        kernel.replace(b'5583.762945', b'not-a-timestamp'), kernel + b' extra',
                        b'unknown kernel trailer', b' ' + kernel, kernel[:-1]):
            with self.subTest(trailer=changed):
                row, = checker.parse_console(guest + changed + b'\r\n')
                self.assertIn('diagnostic', row)
                self.assertNotIn('kernel_diagnostic', row)
        for tag in (b'FUNCTIONAL_CAMERA_CONTROL_COMMIT', b'FUNCTIONAL_CAMERA_CONTROL_SENT', b'FUNCTIONAL_CAMERA_OTHER'):
            with self.subTest(tag=tag):
                row, = checker.parse_console(E6MX_TRANSFER_RECORD.replace(b'FUNCTIONAL_CAMERA_TRANSFER', tag))
                self.assertIn('diagnostic', row)
                self.assertNotIn('kernel_diagnostic', row)
        for raw in (E6MX_TRANSFER_RECORD[:-2], E6MX_TRANSFER_RECORD[:-1], guest + kernel + b'\r'):
            with self.subTest(raw=raw), self.assertRaisesRegex(ValueError, 'truncated evidence trace'):
                checker.parse_console(raw)
        partial, = checker.parse_console(guest[:guest.index(b' returned_fnv=')] + kernel + b'\n')
        self.assertIn('diagnostic', partial)
        self.assertNotIn('kernel_diagnostic', partial)

    def test_full_order_canonical_fields_ranges_and_origin_opcode_are_required(self):
        guest, kernel = E6MX_TRANSFER_RECORD[:-2].split(b'[ ', 1)
        kernel = b'[ ' + kernel
        invalid = (
            (b'seq=27..28', b'seq=0..28'), (b'seq=27..28', b'seq=28..27'),
            (b'seq=27..28', b'seq=27..18446744073709551616'), (b'op=11', b'op=011'),
            (b'op=11', b'op=12'), (b'op=11', b'op=65'), (b'op=11', b'op=4294967296'),
            (b'source=0x42e', b'source=0x0'), (b'source=0x42e', b'source=0x042e'),
            (b'source=0x42e', b'source=0X42e'), (b'source=0x42e', b'source=0x42E'),
            (b'source=0x42e', b'source=0x100000000'), (b'bytes=40 ', b'bytes=4294967296 '),
            (b'native_fnv=0x329254c5e41f02e3', b'native_fnv=0x10000000000000000'),
            (b'request_bytes=480', b'request_bytes=+480'), (b'request_bytes=480', b'request_bytes=0480'),
            (b'request_bytes=480', b'request_bytes=32'), (b'required=51200', b'required=-1'),
            (b'required=51200', b'required=18446744073709551616'), (b'error=0', b'error=-0'),
            (b'error=0', b'error=-2147483649'), (b'error=0', b'error=1'),
            (b'readback_closed=1', b'readback_closed=2'),
            (b'command=0x2820746', b'command=0x2820747'),
            (b'origin_kind=api40-source-snapshot', b'origin_kind=native-osal'),
            (b'origin_kind=api40-source-snapshot', b'origin_kind=unknown'))
        for old, new in invalid:
            with self.subTest(field=old, value=new):
                row, = checker.parse_console(guest.replace(old, new, 1) + kernel + b'\n')
                self.assertIn('diagnostic', row)
                self.assertNotIn('kernel_diagnostic', row)
        parts = guest.split(b' ')
        for index in range(2, len(parts)):
            with self.subTest(missing=parts[index]):
                row, = checker.parse_console(b' '.join(parts[:index] + parts[index + 1:]) + kernel + b'\n')
                self.assertIn('diagnostic', row)
                self.assertNotIn('kernel_diagnostic', row)
        for changed in (guest.replace(b'op=11 source=0x42e', b'source=0x42e op=11'),
                        guest + b' capture_verified=1'):
            row, = checker.parse_console(changed + kernel + b'\n')
            self.assertIn('diagnostic', row)
            self.assertNotIn('kernel_diagnostic', row)
        for changed in (guest.replace(b'op=11', b'op=11 op=11'), guest.replace(b'error=0', b'error=0 error=-5')):
            with self.subTest(duplicate=changed), self.assertRaises(ValueError):
                checker.parse_console(changed + kernel + b'\n')

    def test_framed_failure_and_missing_opcode_remain_layout_errors(self):
        policy = {'functional_camera_' + key: value for key, value in checker.STARTUP_LAYOUT_POLICY.items()}
        manifest = dict(policy, backup_transport=dict(policy))
        stage = checker.parse_console(layout_stage_observations(1).encode())
        diagnostic, = checker.parse_console(b'OBS FUNCTIONAL_CAMERA_TRANSFER incomplete failure prose\n')
        diagnostic['line'] = 100
        original = copy.deepcopy(diagnostic)
        with self.assertRaisesRegex(checker.MissingEvidence, 'transfer line 100: missing op; diagnostic='):
            checker.check_layout_stage(None, manifest, stage + [diagnostic])
        self.assertEqual(diagnostic, original)
        failed, = checker.parse_console(E6MX_TRANSFER_RECORD.replace(b'readback_closed=1 error=0', b'readback_closed=0 error=-5'))
        self.assertEqual(failed['fields']['error'], '-5')
        self.assertIn('kernel_diagnostic', failed)
        failed['line'] = 100
        for row in (failed, dict(diagnostic, fields=dict(op='11', error='0', readback_closed='1')),
                    dict(tag='FUNCTIONAL_CAMERA_TRANSFER', line=100, fields=dict(op='11'))):
            with self.subTest(row=row), self.assertRaisesRegex(ValueError, 'malformed/failed actual bridge transfer'):
                checker.check_layout_stage(None, manifest, stage + [row])

    def test_original_console_binding_when_private_run_is_available(self):
        path = checker.RUNTIME / 'menu-runs/run-e6mx3j3f/console.log'
        if not path.exists():
            self.skipTest('private original e6mx console is not part of the public package')
        before = path.stat()
        raw = path.read_bytes()
        self.assertEqual(checker.sha(raw), E6MX_CONSOLE_SHA256)
        self.assertEqual(raw[E6MX_TRANSFER_OFFSET:E6MX_TRANSFER_OFFSET + len(E6MX_TRANSFER_RECORD)], E6MX_TRANSFER_RECORD)
        self.assertEqual(raw.count(b'\n', 0, E6MX_TRANSFER_OFFSET) + 1, 20041)
        self.assertEqual(raw.splitlines(keepends=True)[21042], E6MX_TRANSFER_RECORD)
        transfers = [row for row in checker.parse_console(raw) if row['tag'] == 'FUNCTIONAL_CAMERA_TRANSFER']
        self.assertEqual(len(transfers), 27)
        self.assertTrue(all('diagnostic' not in row for row in transfers))
        framed = next(row for row in transfers if row['line'] == 21043)
        note = framed['kernel_diagnostic']
        self.assertEqual(note['raw_lf_line'], 20041)
        self.assertEqual(note['payload']['byte_offset'], E6MX_TRANSFER_OFFSET + 4)
        for part in (note, note['payload']):
            self.assertEqual(raw[part['byte_offset']:part['byte_offset'] + part['bytes']], part['raw'].encode())
        after = path.stat()
        self.assertEqual((before.st_ino, before.st_size, before.st_mtime_ns), (after.st_ino, after.st_size, after.st_mtime_ns))
        self.assertEqual(checker.sha(path.read_bytes()), E6MX_CONSOLE_SHA256)

    def test_recomputed_console_hash_cannot_replace_actual_broker_origin(self):
        with tempfile.TemporaryDirectory(prefix='HOST_TEST_framed_hash_') as directory:
            args = list(host_test_transport(Path(directory)))
            run, manifest, _, events, build = args
            lines = (run / 'console.log').read_bytes().splitlines(keepends=True)
            kernel = E6MX_TRANSFER_RECORD[E6MX_TRANSFER_RECORD.index(b'[ '):-2]
            lines[0] = re.sub(rb' native_fnv=0x[0-9a-f]+', b' native_fnv=0x1', lines[0][:-1]) + b' origin_kind=native-osal' + kernel + b'\r\n'
            raw = b''.join(lines)
            (run / 'console.log').write_bytes(raw)
            runner = manifest['functional_camera_runtime']
            runner['console_sha256_at_close'] = checker.sha(raw)
            (run / 'functional-camera-runner.json').write_text(json.dumps(runner))
            rows = checker.parse_console(raw)
            self.assertIn('kernel_diagnostic', rows[0])
            with self.assertRaisesRegex(ValueError, 'bridge original native origin differs'):
                checker.check_transport(run, manifest, rows, events, build)
    def test_unknown_or_mismatched_declared_origin_never_passes_the_broker_join(self):
        with tempfile.TemporaryDirectory(prefix='HOST_TEST_framed_origin_') as directory:
            run, manifest, rows, events, build = host_test_transport(Path(directory))
            for origin in ('native-osal-extra', 'api40-source-snapshot', 'unknown', 'native-osal[ret=-1021]'):
                changed = copy.deepcopy(rows)
                changed[0]['fields']['origin_kind'] = origin
                with self.subTest(origin=origin), self.assertRaisesRegex(ValueError, 'origin_kind differs'):
                    checker.check_transport(run, manifest, changed, events, build)


class Run9sxHdmiNativeFreeFramingTests(unittest.TestCase):
    # Public original LF/byte spans only; framing cannot attest a native graph or capture.
    CONSOLE_SHA256 = '0c79c47fd3399fd41b029083cdd0658a3ad0b5e32d947d0996437fdf30b239bc'
    OFFSET, RAW_LF = 2092576, 18924
    RECORD = (
        b'/ # OBS FULL_HDMI_VIDEO_STATE_NATIVE_FREE tid=352 receiver=352 sender=384 '
        b'destination=0x802a0116 pointer=0x7fabc1af80 lease=15 kind=2 bytes=20 rc=0 '
        b'received=1 consumed=1 original_cp_executed=0 hardware_verified=0 capture_verified=0'
        b'[ 5788.347794] UDIF: cdev_ioctl() Line 100: uipc: warning ret = -1022\r\n')
    PAYLOAD, KERNEL = RECORD[8:231], RECORD[231:-2]
    PREFIX_FREE = (
        b'OBS FULL_HDMI_VIDEO_STATE_NATIVE_FREE tid=384 receiver=384 sender=384 '
        b'destination=0x81cf61c3 pointer=0x7fabc58900 lease=1 kind=1 bytes=12 rc=0 '
        b'received=1 consumed=1 original_cp_executed=0 hardware_verified=0 capture_verified=0\r\n')
    DYNAMIC = b'[ 5788.347794] [K]**UIPC ERROR** free_dynamic_msgq_id: QID[81cf61c4] M=1 C=0 S=0 A=1'

    def test_original_record_SHA_raw_LF_and_offsets_preserve_every_byte(self):
        self.assertEqual(len(self.RECORD), 302)
        self.assertEqual(checker.sha(self.RECORD),
                         'c55bf039bdd1812e792ef7c4ad010905afe8dec123df74682a35b0301408f56e')
        self.assertEqual(checker.sha(self.RECORD + b'\r\n'),
                         '31a665dd9df991c8ca0b2be9c93519a9acd4ae457236f5b8447dfc986d935e71')
        framed, note = checker.frame_console_kernel(self.RECORD[8:], self.OFFSET + 8, self.RAW_LF)
        self.assertEqual(framed, self.PAYLOAD + b'\r\n')
        self.assertEqual(note, dict(raw=self.KERNEL.decode(), bytes=69,
            sha256='9c4f0fdac160b474910d0052e893712c0b0db9be1faec3ab9b7fc6812fa7c844',
            byte_offset=2092807, raw_lf_line=18924, cause='unknown', line_ending='\r\n',
            payload=dict(raw=self.PAYLOAD.decode(), bytes=223,
                sha256='b683c1a5acbd11dbd958e26245edc6c87b9c859a8c4ca168c4bec557729e3fa4',
                byte_offset=2092584)))
        self.assertEqual(b'/ # OBS ' + note['payload']['raw'].encode() + note['raw'].encode() +
                         note['line_ending'].encode(), self.RECORD)
        row, = checker.parse_console(self.RECORD + b'\r\n')
        self.assertEqual(row['fields'], checker.console_producer_fields(self.PAYLOAD))
        self.assertEqual(len(row['fields']), 14)
        self.assertEqual(row['fields']['capture_verified'], '0')
        self.assertNotIn('diagnostic', row)
        self.assertNotIn('verified', row)
        self.assertNotIn('AP_consumed', row['fields'])

    def test_standalone_prefixes_endings_and_both_existing_kernel_trailers(self):
        before = b'boot\rprogress\r\nordinary\n'
        for payload in (self.PAYLOAD, self.PREFIX_FREE[4:-2]):
            expected = checker.console_producer_fields(payload)
            self.assertIsNotNone(expected)
            for prefix in (b'', b'OBS ', b'/ # OBS '):
                for ending in (b'\n', b'\r\n'):
                    with self.subTest(kind=expected['kind'], prefix=prefix, ending=ending):
                        standalone, = checker.parse_console(before + prefix + payload + ending)
                        self.assertEqual(standalone['fields'], expected)
                        self.assertNotIn('kernel_diagnostic', standalone)
                    for kernel in (self.KERNEL, self.DYNAMIC):
                        raw = before + prefix + payload + kernel + ending
                        with self.subTest(kind=expected['kind'], prefix=prefix, ending=ending, kernel=kernel):
                            row, = checker.parse_console(raw)
                            self.assertEqual(row['fields'], expected)
                            self.assertEqual(row['line'], 4)
                            note = row['kernel_diagnostic']
                            self.assertEqual((note['raw_lf_line'], note['cause'], note['line_ending']),
                                             (3, 'unknown', ending.decode()))
                            self.assertEqual(note['payload']['byte_offset'], len(before) + len(prefix))
                            self.assertEqual(note['byte_offset'], len(before) + len(prefix) + len(payload))
                            for part in (note, note['payload']):
                                offset, count = part['byte_offset'], part['bytes']
                                self.assertEqual(raw[offset:offset + count], part['raw'].encode())
                                self.assertEqual(checker.sha(raw[offset:offset + count]), part['sha256'])
                            self.assertEqual(raw[note['byte_offset'] + note['bytes']:], ending)
                            self.assertNotIn('verified', row)

    def test_complete_successful_C_variants_keep_prefix_and_UPM_ownership_distinct(self):
        source = (checker.RUNTIME / 'device-models/hdmi-video-state.c').read_text()
        self.assertIn('tid=%ld receiver=%ld sender=%ld destination=%#x pointer=%p lease=%llu kind=%u '
                      'bytes=%u rc=%d received=%u consumed=%u original_cp_executed=0 '
                      'hardware_verified=0 capture_verified=0', source)
        self.assertIn('record(rc?"FULL_HDMI_VIDEO_STATE_FREE_FAULT ":"FULL_HDMI_VIDEO_STATE_NATIVE_FREE ",line);', source)
        prefix = self.PREFIX_FREE[4:-2]
        variants = (prefix, prefix.replace(b'receiver=384', b'receiver=0').replace(b'received=1', b'received=0'),
                    self.PAYLOAD, self.PAYLOAD.replace(b'destination=0x802a0116', b'destination=0x80920572').replace(
                        b'kind=2 bytes=20', b'kind=3 bytes=16'))
        for payload in variants:
            with self.subTest(payload=payload):
                self.assertIsNotNone(checker.console_producer_fields(payload))
                framed, note = checker.frame_console_kernel(payload + self.KERNEL + b'\r\n', 0, 1)
                self.assertEqual(framed, payload + b'\r\n')
                self.assertEqual(note['payload']['raw'].encode(), payload)
                self.assertNotIn('verified', note)
        invalid = (prefix.replace(b'received=1', b'received=0'),
                   prefix.replace(b'receiver=384', b'receiver=0'),
                   self.PAYLOAD.replace(b'receiver=352', b'receiver=351'),
                   variants[-1].replace(b'destination=0x80920572', b'destination=0x802a0116'))
        for payload in invalid:
            with self.subTest(payload=payload):
                self.assertIsNone(checker.console_producer_fields(payload))

    def test_every_formatter_field_requires_exact_name_order_type_and_unique_key(self):
        parts = self.PAYLOAD.split(b' ')
        for index, token in enumerate(parts[1:], 1):
            key, value = token.split(b'=', 1)
            renamed = parts[:index] + [b'unknown_' + key + b'=' + value] + parts[index + 1:]
            mistyped = parts[:index] + [key + b'=unknown'] + parts[index + 1:]
            swapped = list(parts)
            other = 1 + index % (len(parts) - 1)
            swapped[index], swapped[other] = swapped[other], swapped[index]
            for malformed in (parts[:index] + parts[index + 1:], renamed, mistyped, swapped):
                payload = b' '.join(malformed)
                raw = payload + self.KERNEL + b'\r\n'
                with self.subTest(field=key, payload=payload):
                    self.assertIsNone(checker.console_producer_fields(payload))
                    self.assertEqual(checker.frame_console_kernel(raw, 0, 1), (raw, None))
            with self.subTest(duplicate=key), self.assertRaisesRegex(ValueError, 'duplicate JSON key'):
                checker.console_producer_fields(self.PAYLOAD + b' ' + token)
            with self.subTest(duplicate_kernel=key), self.assertRaisesRegex(ValueError, 'duplicate JSON key'):
                checker.frame_console_kernel(self.PAYLOAD + b' ' + token + self.KERNEL + b'\n', 0, 1)
        for suffix in (b' extra=0', b' unknown', b' ', b'=unknown'):
            payload = self.PAYLOAD + suffix
            with self.subTest(suffix=suffix):
                self.assertIsNone(checker.console_producer_fields(payload))
                self.assertIsNone(checker.frame_console_kernel(payload + self.KERNEL + b'\n', 0, 1)[1])

    def test_numeric_bounds_false_claims_nonzero_rc_and_wrong_kind_sizes_stay_unframed(self):
        replacements = {
            b'tid=352': (b'tid=-1', b'tid=0', b'tid=0352', b'tid=+352', b'tid=2147483648'),
            b'receiver=352': (b'receiver=-1', b'receiver=0', b'receiver=0352', b'receiver=2147483648'),
            b'sender=384': (b'sender=-1', b'sender=0', b'sender=0384', b'sender=2147483648'),
            b'destination=0x802a0116': (b'destination=0', b'destination=0x80000000',
                b'destination=0x902a0116', b'destination=0x0802a0116', b'destination=0x802A0116',
                b'destination=0x1802a0116', b'destination=-1'),
            b'pointer=0x7fabc1af80': (b'pointer=(nil)', b'pointer=0x0', b'pointer=0x07fabc1af80',
                b'pointer=0x7Fabc1af80', b'pointer=-1', b'pointer=0x10000000000000000'),
            b'lease=15': (b'lease=-1', b'lease=0', b'lease=015', b'lease=18446744073709551616'),
            b'kind=2': (b'kind=-1', b'kind=0', b'kind=1', b'kind=3', b'kind=4', b'kind=4294967296'),
            b'bytes=20': (b'bytes=-1', b'bytes=12', b'bytes=16', b'bytes=020', b'bytes=4294967296'),
            b'rc=0': (b'rc=-1021', b'rc=1', b'rc=-0', b'rc=00', b'rc=2147483648'),
            b'received=1': (b'received=-1', b'received=0', b'received=2', b'received=01'),
            b'consumed=1': (b'consumed=-1', b'consumed=0', b'consumed=2', b'consumed=01'),
            b'original_cp_executed=0': (b'original_cp_executed=-1', b'original_cp_executed=1'),
            b'hardware_verified=0': (b'hardware_verified=-1', b'hardware_verified=1'),
            b'capture_verified=0': (b'capture_verified=-1', b'capture_verified=1', b'capture_verified=00'),
        }
        for before, values in replacements.items():
            for value in values:
                payload = self.PAYLOAD.replace(before, value, 1)
                with self.subTest(before=before, value=value):
                    self.assertIsNone(checker.console_producer_fields(payload))
                    self.assertIsNone(checker.frame_console_kernel(payload + self.KERNEL + b'\n', 0, 1)[1])

    def test_unknown_kernel_partial_tail_noncanonical_timestamp_and_no_ending_are_rejected(self):
        invalid = (self.KERNEL.replace(b'-1022', b'-1021'), self.KERNEL.replace(b'-1022', b'0'),
            self.KERNEL.replace(b'Line 100', b'Line 101'), self.KERNEL.replace(b'5788.', b'05788.'),
            self.KERNEL.replace(b'347794', b'34779'), self.KERNEL.replace(b'347794', b'3477940'),
            self.KERNEL.replace(b'[ ', b'['), self.KERNEL + b' extra=0', self.KERNEL + self.KERNEL,
            b' ' + self.KERNEL, self.KERNEL[:-1], b'unknown kernel trailer', b'[ 5788.347794] unknown',
            self.DYNAMIC.replace(b'81cf61c4', b'81CF61C4'), self.DYNAMIC.replace(b'81cf61c4', b'81cf61c'),
            self.DYNAMIC.replace(b'M=1', b'M=0'), self.DYNAMIC.replace(b'C=0', b'C=1'),
            self.DYNAMIC.replace(b'S=0', b'S=1'), self.DYNAMIC.replace(b'A=1', b'A=0'),
            self.DYNAMIC.replace(b'M=1', b'M=-1'), self.DYNAMIC.replace(b'M=1 C=0', b'C=0 M=1'),
            self.DYNAMIC + b' extra', self.DYNAMIC + self.DYNAMIC)
        for kernel in invalid:
            raw = self.PAYLOAD + kernel + b'\r\n'
            with self.subTest(kernel=kernel):
                self.assertEqual(checker.frame_console_kernel(raw, 0, 1), (raw, None))
                row, = checker.parse_console(b'OBS ' + raw)
                self.assertIn('diagnostic', row)
                self.assertNotIn('kernel_diagnostic', row)
        for ending in (b'', b'\r'):
            for tail in (b'', self.KERNEL, self.DYNAMIC):
                raw = self.PAYLOAD + tail + ending
                with self.subTest(ending=ending, tail=tail):
                    self.assertEqual(checker.frame_console_kernel(raw, 0, 1), (raw, None))
                    with self.assertRaisesRegex(ValueError, 'truncated evidence trace'):
                        checker.parse_console(b'OBS ' + raw)
        for suffix in (b'FREE_FAULT', b'FREE_REJECTED', b'MESSAGE_SENT', b'MESSAGE_PUBLISHED',
                       b'KERNEL_RETIRED', b'CLEANUP_FREE', b'UNKNOWN', b'NATIVE_FREE_EXTRA'):
            payload = self.PAYLOAD.replace(b'NATIVE_FREE', suffix, 1)
            with self.subTest(suffix=suffix):
                self.assertIsNone(checker.console_producer_fields(payload))
                self.assertIsNone(checker.frame_console_kernel(payload + self.KERNEL + b'\n', 0, 1)[1])

    def test_private_closed_run_binds_original_SHA_raw_LF_and_readonly_excerpt(self):
        path = checker.RUNTIME / 'menu-runs/run-9sx3odm3/console.log'
        if not path.exists():
            self.skipTest('private closed run9sx console is excluded from the public package')
        before = path.stat()
        raw = path.read_bytes()
        self.assertEqual(checker.sha(raw), self.CONSOLE_SHA256)
        self.assertEqual(raw[self.OFFSET:self.OFFSET + 302], self.RECORD)
        self.assertEqual(raw[self.OFFSET + 302:self.OFFSET + 304], b'\r\n')
        self.assertEqual(raw.count(b'\n', 0, self.OFFSET) + 1, self.RAW_LF)
        self.assertEqual(raw.split(b'\n')[self.RAW_LF - 1] + b'\n', self.RECORD)
        after = path.stat()
        self.assertEqual((before.st_ino, before.st_size, before.st_mtime_ns),
                         (after.st_ino, after.st_size, after.st_mtime_ns))
        self.assertEqual(checker.sha(path.read_bytes()), self.CONSOLE_SHA256)


class IztnScalarConsoleFramingTests(unittest.TestCase):
    GUEST = (b'OBS FULL_SCALAR_CONNECT_NATIVE_REPLY_FREE pid=259 tid=383 sender=383 waiter=1 '
             b'destination=0x81cf61c4 expected=0x81cf61c4 reply=0x7f8f73ee40 bytes=56 '
             b'command=0x8001 rc=0 faults=0 ap_consumed=1 capture_verified=0\r\n')

    def test_scalar_partial_tag_reuses_exact_formatter_and_original_byte_spans(self):
        tag = b'OBS FULL_SCALAR_CONNECT_NATIVE_REPLY_FREE '
        source = (checker.RUNTIME / 'device-models/pin-peer-connection.inc').read_text()
        self.assertIn('pid=%d tid=%ld sender=%ld waiter=%u destination=%#x expected=%#x reply=%p '
                      'bytes=56 command=0x8001 rc=%d faults=%u ap_consumed=%u capture_verified=0', source)
        self.assertIn('#define EDGE_TAG "SCALAR"',
                      (checker.RUNTIME / 'device-models/scalar-connection.c').read_text())
        before, after = b'boot\rprogress\r\n', b'OBS FUNCTIONAL_CAMERA_TRANSFER op=2 error=0\n'
        for ending in (b'\n', b'\r\n'):
            guest = self.GUEST[:-2] + ending
            intact, = checker.parse_console(guest)
            for warning in checker.ADF_HOST_WARNINGS:
                for cut in range(len(b'OBS ') + 1, len(tag)):
                    raw = before + guest[:cut] + warning + guest[cut:] + after
                    with self.subTest(ending=ending, warning=warning, cut=cut):
                        row, following = checker.parse_console(raw)
                        self.assertEqual(row['fields'], intact['fields'])
                        self.assertEqual((row['line'], following['line']), (3, 5))
                        self.assertNotIn('diagnostic', row)
                        self.assertNotIn('verified', row)
                        note = row['host_diagnostic']
                        self.assertEqual(note['cause'], 'unknown')
                        self.assertFalse(note['guest_bytes_invented'])
                        self.assertEqual((note['raw_lf_line'], note['raw_lf_end']), (2, 3))
                        self.assertEqual(raw[note['byte_offset']:note['byte_offset'] + note['bytes']], warning)
                        original = raw[note['raw_record_start']:note['raw_record_end']]
                        self.assertEqual(original, guest[:cut] + warning + guest[cut:])
                        self.assertEqual(checker.sha(original), note['raw_record_sha256'])
                        spans = note['payload']['spans']
                        joined = b''.join(raw[s['byte_offset']:s['byte_offset'] + s['bytes']] for s in spans)
                        self.assertEqual(joined, guest)
                        self.assertEqual(checker.sha(joined), note['payload']['sha256'])
                        self.assertNotIn('content_verifier_joined', note)
                        self.assertEqual(following['fields'], dict(op='2', error='0'))

    def test_scalar_partial_tag_keeps_malformed_unknown_and_owner_negatives_closed(self):
        guest, cut = self.GUEST, len(b'OBS FULL')
        warning = checker.ADF_HOST_WARNINGS[0]
        parts = guest[:-2].split(b' ')
        bad = [b' '.join(parts[:i] + parts[i + 1:]) + b'\r\n' for i in range(2, len(parts))]
        bad += [guest.replace(old, new, 1) for old, new in (
            (b'pid=259', b'pid=0259'), (b'pid=259', b'pid=2147483648'),
            (b'tid=383', b'tid=0'), (b'tid=383', b'tid=-1'), (b'tid=383', b'tid=2147483648'),
            (b'sender=383', b'sender=384'), (b'sender=383', b'sender=2147483648'),
            (b'waiter=1', b'waiter=0'), (b'expected=0x81cf61c4', b'expected=0x81cf61c5'),
            (b'destination=0x81cf61c4', b'destination=0x71cf61c4'),
            (b'destination=0x81cf61c4 expected=0x81cf61c4', b'destination=0x80000000 expected=0x80000000'),
            (b'reply=0x7f8f73ee40', b'reply=(nil)'), (b'reply=0x7f8f73ee40', b'reply=0x0'),
            (b'reply=0x7f8f73ee40', b'reply=0x10000000000000000'),
            (b'bytes=56', b'bytes=55'), (b'command=0x8001', b'command=0x8002'),
            (b'rc=0', b'rc=-1'), (b'faults=0', b'faults=1'),
            (b'ap_consumed=1', b'ap_consumed=0'), (b'capture_verified=0', b'capture_verified=1'),
            (b'pid=259 tid=383', b'tid=383 pid=259'), (b'pid=259 tid=383', b'pid=259  tid=383'),
            (b'pid=259 tid=383', b'pid=259\ttid=383'),
            (b'\r\n', b' extra=1\r\n'), (b'\r\n', b' rc=0\r\n'), (b'\r\n', b' \r\n'),
            (b'\r\n', b'\r\r\n'))]
        for changed in bad:
            with self.subTest(changed=changed), self.assertRaises(ValueError):
                checker.parse_console(changed[:cut] + warning + changed[cut:])
        for unknown in (b'FULL_SCALAR_CONNECT_COMMIT', b'FULL_SCALAR_CONNECT_NATIVE_REPLY_FREE_EXTRA',
                        b'FULL_ADF_CONNECT_NATIVE_REPLY_FREE'):
            changed = guest.replace(b'FULL_SCALAR_CONNECT_NATIVE_REPLY_FREE', unknown)
            self.assertEqual(checker.parse_console(changed[:cut] + warning + changed[cut:]), [])
        for changed in (warning.replace(b'pending', b'unknown'), warning.replace(b'warning:', b'Warning:'),
                        warning.replace(b'commit ', b'commit  '), warning[:-1] + b'\r\n'):
            self.assertEqual(checker.parse_console(guest[:cut] + changed + guest[cut:]), [])
        for suffix in (b'', guest[cut:-2]):
            with self.subTest(suffix=suffix), self.assertRaises(ValueError):
                checker.parse_console(guest[:cut] + warning + suffix)
        for suffix in (warning + guest[cut:], b'OBS OTHER value=1\r\n'):
            self.assertFalse(any(r['tag'] == 'FULL_SCALAR_CONNECT_NATIVE_REPLY_FREE'
                for r in checker.parse_console(guest[:cut] + warning + suffix)))

    def test_original_iztn_scalar_279_bytes_if_private_console_available(self):
        mixed = self.GUEST[:8] + checker.ADF_HOST_WARNINGS[0] + self.GUEST[8:]
        self.assertEqual(checker.sha(mixed), '31a8b5911e787490f61f2eb876b19ed20251e395fe40f2ac34bf5bc752fdded6')
        path = checker.RUNTIME / 'menu-runs/run-iztn71wy/console.log'
        if not path.exists():
            self.skipTest('private iztn console excluded from public package')
        raw = path.read_bytes()
        self.assertEqual(checker.sha(raw), '668b17becd0407b85c5073bacbf01a83eb8fd4c31eb882b33f79244d52815178')
        self.assertEqual(raw[1956448:1956727], mixed)
        rows = checker.parse_console(raw)
        added = {'NATIVE_CP_OUTPUT_POLICY_CONSUMED': 1, 'NATIVE_CP_EE_DIAGNOSTIC_REQUEST_FREE': 3,
                 'NATIVE_CP_EE_DIAGNOSTIC_COMPLETE': 3, 'NATIVE_CP_EE_DIAGNOSTIC_REPLY_FREE': 2}
        self.assertEqual({tag: sum(r['tag'] == tag for r in rows) for tag in added}, added)
        movie_added = {'NATIVE_CP_MOVIE_FORMAT_DIAGNOSTIC_' + name: 1
                       for name in ('REQUEST_FREE', 'REPLY_FREE', 'COMPLETE')}
        self.assertEqual({tag: sum(r['tag'] == tag for r in rows) for tag in movie_added}, movie_added)
        historical = [r for r in rows if r['tag'] not in added and r['tag'] not in movie_added]
        self.assertEqual(sum(r['tag'] != 'FULL_HDMI_VIDEO_STATE_NATIVE_FREE' for r in historical), 923)
        self.assertEqual(sum(r['tag'] == 'FULL_HDMI_VIDEO_STATE_NATIVE_FREE' for r in rows), 27)
        row, = [r for r in rows if r['tag'] == 'FULL_SCALAR_CONNECT_NATIVE_REPLY_FREE']
        self.assertEqual(row['host_diagnostic']['raw_record_start'], 1956448)
        self.assertEqual(row['host_diagnostic']['raw_record_end'], 1956727)
        self.assertEqual((row['host_diagnostic']['raw_lf_line'], row['host_diagnostic']['raw_lf_end']), (18052, 18053))
        transfers = [r for r in rows if r['tag'] == 'FUNCTIONAL_CAMERA_TRANSFER']
        self.assertEqual(len(transfers), 27)
        self.assertEqual([n for r in transfers for n in range(int(r['fields']['seq'].split('..')[0]),
            int(r['fields']['seq'].split('..')[1]) + 1)], list(range(1, 37)))
        self.assertEqual(checker.sha(path.read_bytes()), checker.sha(raw))


class IztnTransferConsoleFramingTests(unittest.TestCase):
    # Original iztn console SHA668b17be..., offset2645777, LF20521; parser fixture only.
    RECORD = (
        b'AND_DONE_e86OBS FUNCTIONAL_CAMERA_TRANSFER seq=27..28 op=11 source=0x42e destination=0x8403 '
        b'command=0x2820746 bytes=40 native_fnv=0x9b46d73d17f4c433 request_bytes=480 '
        b'request_fnv=0x41b17d1821e8e50b returned_bytes=51200 returned_fnv=0x36e5ede026e630fe '
        b'required=51200 destination_written_bytes=51200 destination_fnv=0x36e5ede026e630fe '
        b'model_instance=0x8bfb1b06c4c070a5 token=0x8000000000000003 readback_closed=1 error=0 '
        b'origin_kind=api40-source-snapshot\r\n')
    PREFIX = b'AND_DONE_e86OBS '

    def test_iztn_exact_transfer_keeps_original_bytes_offsets_and_fields(self):
        raw, prefix = self.RECORD, self.PREFIX
        self.assertEqual(len(raw), 453)
        self.assertEqual(checker.sha(raw), 'c3ca5cb80d90cb705b5f4143f93c04d414b5e8a8b85f3d17bb27462220a00e43')
        normalized, note = checker.frame_console_transfer_echo(raw, 2645777, 20521)
        self.assertEqual(normalized, raw[len(prefix):])
        self.assertEqual((note['raw'], note['byte_offset'], note['raw_lf_line'], note['cause']),
                         (prefix.decode(), 2645777, 20521, 'unknown'))
        self.assertEqual(note['payload']['byte_offset'], 2645793)
        self.assertEqual(note['line_ending'], '\r\n')
        for part in (note, note['payload']):
            self.assertEqual(checker.sha(part['raw'].encode()), part['sha256'])
            self.assertEqual(part['bytes'], len(part['raw'].encode()))
        before = b'boot\rprogress\r\nordinary\n'
        for ending in (b'\n', b'\r\n'):
            with self.subTest(ending=ending):
                row, = checker.parse_console(before + raw[:-2] + ending)
                plain, = checker.parse_console(raw[len(prefix):-2] + ending)
                self.assertEqual(row['fields'], plain['fields'])
                self.assertEqual((row['line'], row['console_prefix_diagnostic']['raw_lf_line']), (4, 3))
                self.assertEqual((row['fields']['seq'], row['fields']['token']),
                                 ('27..28', '0x8000000000000003'))
                self.assertEqual(row['console_prefix_diagnostic']['line_ending'].encode(), ending)
                self.assertNotIn('verified', row)
                self.assertNotIn('capture_verified', row)

    def test_iztn_transfer_requires_exact_prefix_family_and_complete_formatter(self):
        prefix = self.PREFIX
        body = self.RECORD[len(prefix):-2]
        prefixes = (b'AND_DONE_e85OBS ', b'AND_DONE_e86OBS  ', b'AND_DONE_e86 OBS ',
                    b' AND_DONE_e86OBS ', b'xAND_DONE_e86OBS ', b'AND_DONE_e86OBS\t',
                    b'AND_DONE_e86e7f1OBS ')
        for changed in prefixes:
            with self.subTest(prefix=changed):
                self.assertEqual(checker.parse_console(changed + body + b'\r\n'), [])
        for tag in (b'FUNCTIONAL_CAMERA_CONTROL_COMMIT', b'FUNCTIONAL_FACE_SOURCE_SNAPSHOT_RESULT'):
            with self.subTest(tag=tag):
                self.assertEqual(checker.parse_console(prefix + body.replace(b'FUNCTIONAL_CAMERA_TRANSFER', tag) + b'\r\n'), [])
        parts = body.split(b' ')
        malformed = [b' '.join(parts[:i] + parts[i + 1:]) for i in range(1, len(parts))]
        malformed += [body + b' extra=0', body + b' unknown',
            body.replace(b'seq=27..28', b'seq=027..28'), body.replace(b'op=11', b'op=011'),
            body.replace(b'op=11', b'op=65'), body.replace(b'request_bytes=480', b'request_bytes=479'),
            body.replace(b'command=0x2820746', b'command=0x2820747'),
            body.replace(b'origin_kind=api40-source-snapshot', b'origin_kind=native-osal'),
            body.replace(b'readback_closed=1 error=0', b'readback_closed=0 error=0'),
            body.replace(b'model_instance=0x8bfb1b06c4c070a5', b'model_instance=0'),
            body.replace(b'source=0x42e destination=0x8403', b'destination=0x8403 source=0x42e')]
        for changed in malformed:
            with self.subTest(payload=changed):
                self.assertEqual(checker.parse_console(prefix + changed + b'\r\n'), [])
        with self.assertRaisesRegex(ValueError, 'duplicate JSON key'):
            checker.parse_console(prefix + body + b' op=11\r\n')
        for raw in (self.RECORD[:-2], self.RECORD[:-1]):
            with self.subTest(raw=raw), self.assertRaisesRegex(ValueError, 'truncated evidence trace'):
                checker.parse_console(raw)

    def test_iztn_transfer_preserves_original_failure_and_does_not_promote_it(self):
        raw = self.RECORD.replace(b'readback_closed=1 error=0', b'readback_closed=0 error=-5')
        row, = checker.parse_console(raw)
        self.assertEqual((row['fields']['readback_closed'], row['fields']['error']), ('0', '-5'))
        self.assertEqual(row['console_prefix_diagnostic']['raw'], self.PREFIX.decode())
        self.assertNotIn('verified', row)
        self.assertNotIn('capture_verified', row)

    def test_iztn_prefix_transport_keeps_binding_overlap_and_complete_coverage_guards(self):
        with tempfile.TemporaryDirectory() as temporary:
            run, manifest, _, events, build = host_test_transport(Path(temporary))
            first, rest = (run / 'console.log').read_bytes().split(b'\n', 1)
            self.assertTrue(first.startswith(b'OBS FUNCTIONAL_CAMERA_TRANSFER '))
            self.assertNotIn(b'origin_kind=', first)
            raw = self.PREFIX + first[4:] + b' origin_kind=native-osal\r\n' + rest
            (run / 'console.log').write_bytes(raw)
            runner = manifest['functional_camera_runtime']
            runner['console_sha256_at_close'] = checker.sha(raw)
            (run / 'functional-camera-runner.json').write_text(json.dumps(runner))
            rows = checker.parse_console(raw)
            self.assertEqual(rows[0]['console_prefix_diagnostic']['raw'], self.PREFIX.decode())
            self.assertTrue(checker.check_transport(run, manifest, rows, events, build)['verified'])
            for key, value in (('model_instance', '0x64'), ('op', '2'), ('source', '0x1'),
                ('native_fnv', '0x1'), ('request_fnv', '0x1'), ('returned_fnv', '0x1'),
                ('destination_fnv', '0x1'), ('returned_bytes', '127'), ('token', '0x8000000000000003'),
                ('readback_closed', '0'), ('error', '-5')):
                changed = copy.deepcopy(rows)
                changed[0]['fields'][key] = value
                with self.subTest(key=key), self.assertRaises(ValueError):
                    checker.check_transport(run, manifest, changed, events, build)
            with self.assertRaisesRegex(ValueError, 'duplicate/overlapping bridge transfer'):
                checker.check_transport(run, manifest, rows + [copy.deepcopy(rows[0])], events, build)
            with self.assertRaisesRegex(ValueError, 'not fully consumed'):
                checker.check_transport(run, manifest, rows[1:], events, build)


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
        snapshot = checker.source_module(checker.RUNTIME / 'functional_face_source_snapshot.py')
        with mock.patch.dict(sys.modules, functional_face_source_snapshot=snapshot):
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

    def test_sf05_framed_background_does_not_bypass_missing_callback_cycle_nonce_or_failed_free(self):
        args = self.background(require_native=True)
        run, manifest, rows, events, build = args
        target = next(row for row in rows if row['tag'] == 'FUNCTIONAL_CAMERA_TRANSFER')
        body = target['tag'] + ' ' + ' '.join(f'{key}={value}' for key, value in target['fields'].items())
        framed, = checker.parse_console(b"'; elOBS " + body.encode() + b' origin_kind=native-osal\r\n')
        framed['line'] = target['line']
        recovered = [framed if row is target else row for row in rows]
        transport = checker.check_transport(run, manifest, recovered, events, build)
        self.assertTrue(transport['background_start']['content_join_verified'])
        self.assertFalse(transport['background_start']['capture_verified'])
        for tag in ('FUNCTIONAL_BACKGROUND_START_RECEIVE', 'FUNCTIONAL_BACKGROUND_START_AP_FREE',
                    'FULL_ADF_CONNECT_NATIVE_REPLY_FREE'):
            missing = [row for row in recovered if row['tag'] != tag]
            with self.subTest(missing=tag), self.assertRaises(ValueError):
                checker.check_background_start(run, manifest, missing, transport)
        for tag, key, value in (('FUNCTIONAL_BACKGROUND_START_AP_FREE', 'cycle', '2'),
                                ('FUNCTIONAL_BACKGROUND_START_AP_FREE', 'free_ticket', '2'),
                                ('FUNCTIONAL_BACKGROUND_START_READBACK', 'instance', '1')):
            changed = copy.deepcopy(recovered)
            next(row for row in changed if row['tag'] == tag)['fields'][key] = value
            with self.subTest(tag=tag, key=key), self.assertRaises(ValueError):
                checker.check_background_start(run, manifest, changed, transport)
        changed = copy.deepcopy(recovered)
        next(row for row in changed if row['tag'] == 'FUNCTIONAL_BACKGROUND_START_LEASE' and
             row['fields']['lease'] == '1' and row['fields']['freed'] == '1')['fields']['free_rc'] = '-5'
        with self.assertRaises(ValueError):
            checker.check_background_start(run, manifest, changed, transport)
        changed = copy.deepcopy(recovered)
        next(row for row in changed if row['tag'] == 'FUNCTIONAL_CAMERA_TRANSFER')['fields']['model_instance'] = '0x1'
        with self.assertRaises(ValueError):
            checker.check_transport(run, manifest, changed, events, build)
        for bad_transport in (None, dict(transport, safe_cleanup=False)):
            with self.subTest(transport=bad_transport is None), self.assertRaises(ValueError):
                checker.check_background_start(run, manifest, recovered, bad_transport)

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

    def test_adf_host_free_exact_producer_and_original_offsets(self):
        self.assertEqual(checker.sha(ZD4_ADF_FREE_RECORD),
                         '5a9205d146106d868d3e92723f18897ec3f15ee7efa048dd7ef23c5092b4fdf2')
        body = ZD4_ADF_FREE_RECORD[4:].split(checker.ADF_HOST_WARNINGS[0])[0]
        self.assertEqual(len(body.split()) - 1, 13)
        source = (checker.RUNTIME / 'device-models/pin-peer-connection.inc').read_text()
        self.assertIn('pid=%d tid=%ld sender=%ld waiter=%u destination=%#x expected=%#x reply=%p '
                      'bytes=56 command=0x8001 rc=%d faults=%u ap_consumed=%u capture_verified=0', source)
        self.assertIn('#define EDGE_TAG "ADF"', (checker.RUNTIME / 'device-models/adf-connection.c').read_text())
        before = b'boot\rstep\r\n'
        after = b'OBS FUNCTIONAL_CAMERA_TRANSFER op=2 error=0\n'
        intact, = checker.parse_console(b'OBS ' + body + b'\r\n')
        for prefix in (b'', b'OBS ', b'/ # OBS '):
            for warning in checker.ADF_HOST_WARNINGS:
                raw = before + prefix + body + warning + b'\r\n' + after
                with self.subTest(prefix=prefix, warning=warning):
                    row, following = checker.parse_console(raw)
                    self.assertEqual(row['fields'], intact['fields'])
                    self.assertNotIn('diagnostic', row)
                    self.assertNotIn('kernel_diagnostic', row)
                    self.assertNotIn('verified', row)
                    self.assertEqual((row['line'], following['line']), (3, 5))
                    note = row['host_diagnostic']
                    self.assertEqual((note['raw_lf_line'], note['ending_raw_lf_line']), (2, 3))
                    self.assertEqual(note['raw'].encode(), warning)
                    self.assertEqual(note['cause'], 'unknown')
                    self.assertFalse(note['guest_bytes_invented'])
                    self.assertEqual(raw[note['line_ending_byte_offset']:note['line_ending_byte_offset'] + 2], b'\r\n')
                    for part in (note, note['payload']):
                        start, size = part['byte_offset'], part['bytes']
                        self.assertEqual(raw[start:start + size], part['raw'].encode())
                        self.assertEqual(checker.sha(raw[start:start + size]), part['sha256'])
                    self.assertEqual(following['fields'], dict(op='2', error='0'))

    def test_adf_host_free_unknown_incomplete_and_noncanonical_records_refused(self):
        body = ZD4_ADF_FREE_RECORD[4:].split(checker.ADF_HOST_WARNINGS[0])[0]
        warning = checker.ADF_HOST_WARNINGS[0]
        parts = body.split(b' ')
        bad = [b' '.join(parts[:i] + parts[i + 1:]) for i in range(1, len(parts))]
        bad += [body + b' rc=0', body + b' extra=1',
            body.replace(b'pid=259 tid=383', b'tid=383 pid=259'),
            body.replace(b'pid=259', b'pid=0259'), body.replace(b'pid=259', b'pid=2147483648'),
            body.replace(b'tid=383', b'tid=9223372036854775808'),
            body.replace(b'sender=383', b'sender=-9223372036854775809'),
            body.replace(b'waiter=1', b'waiter=2'), body.replace(b'bytes=56', b'bytes=55'),
            body.replace(b'command=0x8001', b'command=0x8000'),
            body.replace(b'rc=0', b'rc=2147483648'), body.replace(b'faults=0', b'faults=4294967296'),
            body.replace(b'ap_consumed=1', b'ap_consumed=2'),
            body.replace(b'capture_verified=0', b'capture_verified=1'),
            body.replace(b'reply=0x7f96d0bd00', b'reply=0x10000000000000000'),
            body.replace(b'destination=0x81cf61c4', b'destination=0x181cf61c4')]
        for payload in bad:
            with self.subTest(payload=payload):
                row, = checker.parse_console(b'OBS ' + payload + warning + b'\r\n')
                self.assertIn('diagnostic', row)
                self.assertNotIn('host_diagnostic', row)
        for changed in (warning.replace(b'pending', b'unknown'), warning.replace(b'warning:', b'Warning:'),
                        warning.replace(b'commit ', b'commit  '), warning[:-1] + b'\r\n'):
            with self.subTest(warning=changed):
                rows = checker.parse_console(b'OBS ' + body + changed + b'\r\n')
                self.assertTrue(rows)
                self.assertTrue(all('host_diagnostic' not in row for row in rows))
                self.assertIn('diagnostic', rows[0])
        for ending in (b'\n', b'x\r\n', b'OBS FUNCTIONAL_CAMERA_TRANSFER op=2 error=0\n', warning + b'\r\n'):
            with self.subTest(ending=ending), self.assertRaises(ValueError):
                checker.parse_console(b'OBS ' + body + warning + ending)
        with self.assertRaises(checker.MissingEvidence):
            checker.parse_console(b'OBS ' + body + warning)
        for prefix in (b'0OBS ', b'00OBS ', b'xOBS '):
            self.assertEqual(checker.parse_console(prefix + body + warning + b'\r\n'), [])

    def test_original_zd4_adf_host_free_when_private_console_is_available(self):
        path = checker.RUNTIME / 'menu-runs/run-zd4qa2vi/console.log'
        if not path.exists():
            self.skipTest('private zd4 console is excluded from the public package')
        raw = path.read_bytes()
        before = (path.stat().st_size, path.stat().st_mtime_ns)
        self.assertEqual(checker.sha(raw), ZD4_CONSOLE_SHA256)
        self.assertEqual(raw[1924780:1925056], ZD4_ADF_FREE_RECORD)
        rows = checker.parse_console(raw)
        added = {'NATIVE_CP_OUTPUT_POLICY_CONSUMED': 1, 'NATIVE_CP_EE_DIAGNOSTIC_REQUEST_FREE': 3,
                 'NATIVE_CP_EE_DIAGNOSTIC_COMPLETE': 3, 'NATIVE_CP_EE_DIAGNOSTIC_REPLY_FREE': 2}
        self.assertEqual({tag: sum(r['tag'] == tag for r in rows) for tag in added}, added)
        movie_added = {'NATIVE_CP_MOVIE_FORMAT_DIAGNOSTIC_' + name: 1
                       for name in ('REQUEST_FREE', 'REPLY_FREE', 'COMPLETE')}
        self.assertEqual({tag: sum(r['tag'] == tag for r in rows) for tag in movie_added}, movie_added)
        historical = [r for r in rows if r['tag'] not in added and r['tag'] not in movie_added]
        self.assertEqual(sum(r['tag'] != 'FULL_HDMI_VIDEO_STATE_NATIVE_FREE' for r in historical), 923)
        self.assertEqual(sum(r['tag'] == 'FULL_HDMI_VIDEO_STATE_NATIVE_FREE' for r in rows), 27)
        row, = [r for r in rows if r['tag'] == 'FULL_ADF_CONNECT_NATIVE_REPLY_FREE']
        self.assertEqual(row['line'], 18830)
        self.assertEqual((row['host_diagnostic']['raw_lf_line'], row['host_diagnostic']['ending_raw_lf_line']), (17871, 17872))
        self.assertNotIn('diagnostic', row)
        self.assertFalse(any('diagnostic' in r for r in rows))
        self.assertEqual((path.stat().st_size, path.stat().st_mtime_ns), before)
        self.assertEqual(checker.sha(path.read_bytes()), ZD4_CONSOLE_SHA256)

    def test_background_scalar_framing_keeps_all13_and_real_lifecycle_guards(self):
        args = self.background(require_native=True)
        transport = checker.check_transport(*args)
        target = next(r for r in args[2] if r['tag'] == 'FULL_SCALAR_CONNECT_NATIVE_REPLY_FREE')
        order = ('pid tid sender waiter destination expected reply bytes command rc faults ap_consumed capture_verified').split()
        guest = ('OBS ' + target['tag'] + ' ' + ' '.join(k + '=' + target['fields'][k] for k in order)).encode() + b'\r\n'
        row, = checker.parse_console(guest[:8] + checker.ADF_HOST_WARNINGS[0] + guest[8:])
        row['line'] = target['line']
        rows = [row if r is target else r for r in args[2]]
        self.assertIn('host_diagnostic', row)
        evidence = checker.check_background_start(args[0], args[1], rows, transport)
        self.assertTrue(evidence['content_join_verified'])
        self.assertFalse(evidence['capture_verified'])
        for tag in ('FULL_SCALAR_CONNECT_NATIVE_REPLY_FREE', 'FULL_ADF_CONNECT_NATIVE_REPLY_FREE',
                    'FULL_ADF_HDMI_AUDIO_CONNECT_REPLY_FREE', 'FUNCTIONAL_BACKGROUND_START_RECEIVE'):
            with self.subTest(missing=tag), self.assertRaises(ValueError):
                checker.check_background_start(args[0], args[1], [r for r in rows if r['tag'] != tag], transport)
        with self.assertRaisesRegex(ValueError, 'all13 original AP free missing/ambiguous'):
            checker.check_background_start(args[0], args[1], rows + [copy.deepcopy(row)], transport)
        for key, value in (('sender', str(int(row['fields']['sender']) + 1)), ('waiter', '0'),
                           ('expected', '0x80000001'), ('rc', '-1'), ('ap_consumed', '0')):
            bad = copy.deepcopy(row)
            bad['fields'][key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                checker.check_background_start(args[0], args[1], [bad if r is row else r for r in rows], transport)
        for bad_transport in (None, dict(transport, safe_cleanup=False)):
            with self.subTest(no_transport=bad_transport is None), self.assertRaises(ValueError):
                checker.check_background_start(args[0], args[1], rows, bad_transport)

    def test_background_adf_host_free_keeps_original_identity_and_lifecycle_checks(self):
        args = self.background(require_native=True)
        transport = checker.check_transport(*args)
        target = next(row for row in args[2] if row['tag'] == 'FULL_ADF_CONNECT_NATIVE_REPLY_FREE')
        order = ('pid tid sender waiter destination expected reply bytes command rc faults ap_consumed capture_verified').split()
        payload = ('OBS ' + target['tag'] + ' ' + ' '.join(key + '=' + target['fields'][key] for key in order)).encode()
        framed, = checker.parse_console(payload + checker.ADF_HOST_WARNINGS[0] + b'\r\n')
        framed['line'] = target['line']
        self.assertIn('host_diagnostic', framed)
        rows = [framed if row is target else row for row in args[2]]
        self.assertTrue(checker.check_background_start(args[0], args[1], rows, transport)['content_join_verified'])
        for key, value in (('pid', '1'), ('sender', str(int(framed['fields']['sender']) + 1)),
                           ('waiter', '0'), ('destination', '0x70020002'), ('expected', '0x80000001'),
                           ('reply', '(nil)'), ('rc', '-1'), ('faults', '1'), ('ap_consumed', '0')):
            bad = copy.deepcopy(framed)
            bad['fields'][key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                checker.check_background_start(args[0], args[1], [bad if row is framed else row for row in rows], transport)
        missing = [row for row in rows if row is not framed]
        with self.assertRaisesRegex(ValueError, 'all13 original AP free missing'):
            checker.check_background_start(args[0], args[1], missing, transport)

    def test_background_all13_frees_use_dynamic_AP_queue_not_control_service_prefix(self):
        args = self.background(require_native=True)
        transport = checker.check_transport(*args)
        rows = copy.deepcopy(args[2])
        for row in rows:
            if row['tag'] in checker.BACKGROUND_FREE_TAGS:
                row['fields'].update(destination='0x81cf61c4', expected='0x81cf61c4')
        evidence = checker.check_background_start(args[0], args[1], rows, transport)
        self.assertTrue(evidence['content_join_verified'])
        for destination, expected in (('0x70020002', '0x70020002'), ('0x80000000', '0x80000000'),
                                      ('0x81cf61c4', '0x81cf61c5')):
            bad = copy.deepcopy(rows)
            free = next(row['fields'] for row in bad if row['tag'] in checker.BACKGROUND_FREE_TAGS)
            free.update(destination=destination, expected=expected)
            with self.subTest(destination=destination, expected=expected), self.assertRaises(ValueError):
                checker.check_background_start(args[0], args[1], bad, transport)

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
        self.assertEqual(checker.check_face_source(*args[:4], transport)['status'], 'not_observed')
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

    def test_control_resource_notes_are_not_timing_receipts_or_success(self):
        args = host_test_control(self.root)
        transport = checker.check_transport(*args)
        notes = [dict(tag='FUNCTIONAL_CAMERA_CONTROL_' + suffix, line=index,
                      fields={'pid': str(transport['pid']), 'accepted': '1'})
                 for index, suffix in enumerate(('RESOURCE_DEPENDENCIES', 'RESOURCES_TTS_TABLE',
                                                 'RESOURCES_RESERVED'), 1)]
        self.assertEqual(checker.check_control(args[0], notes + args[2], transport), transport['control'])
        only_notes = checker.check_control(args[0], notes, transport)
        self.assertFalse(only_notes['required'])
        self.assertFalse(only_notes['verified'])
        for suffix in ('RESOURCE_UNKNOWN', 'RESOURCES_RESERVED_FAULT', 'FAILED'):
            row = dict(notes[0], tag='FUNCTIONAL_CAMERA_CONTROL_' + suffix)
            with self.subTest(suffix=suffix), self.assertRaises(ValueError):
                checker.check_control(args[0], [row] + args[2], transport)
        malformed = dict(notes[0], diagnostic='duplicate field')
        with self.assertRaises(ValueError):
            checker.check_control(args[0], [malformed] + args[2], transport)

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
            args = host_test_capture(root, REFRESH_PATHS + (('display', 0x170, bytes.fromhex('01010000') + bytes(4)),),
                                     vdf_inline=inline, refresh_source=0x80946189, configuration_only=True)
            transport = checker.check_transport(*args)
            self.assertEqual(len(transport['VDF_path']['cycles']), 7)
            for row in args[2]:
                if not row['tag'].startswith('FUNCTIONAL_VDF_PATH_') or 'cycle' not in row['fields']:
                    continue
                f = row['fields']
                after_free = f['command'] in ('0x14c', '0x141', '0x152', '0x162', '0x163', '0x170')
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
        self.assertEqual(result['evidence']['functional_AP_source_snapshot_consumed']['status'], 'not_observed')
        self.assertTrue(any(row['stage'] == 'graph' for row in result['missing']))
        self.assertTrue(any(row['stage'] == 'native_acceptance' for row in result['missing']))
        json.dumps(result)

    def test_native_force_IDR_wait_modes_and_actual_packet_join(self):
        for factor in (1, 0x1004):
            directory = self.root / str(factor)
            directory.mkdir()
            args = host_test_capture(directory, native_force_factor=factor)
            transport = checker.check_transport(*args)
            storage = checker.writeback.inspect(args[0])
            self.assertTrue(checker.check_frames(args[0], transport)['verified'])
            result = checker.check_video(args[2], transport, storage, args[0])
            self.assertEqual(result['native_forced_IDR_requests'], 1)
            self.assertEqual(result['native_force_waiter_factor'], factor)
            self.assertTrue(result['raw_encoded_NAL_join_verified'])
            self.assertFalse(storage['capture_verified'])
            queued = copy.deepcopy(args[2])
            def event(tag):
                return next(row for row in queued if row['tag'] == tag and row['fields'].get('command') == '2')
            operation, receive, freed = map(event, ('FUNCTIONAL_MPR_OPERATION',
                'FUNCTIONAL_MPR_EVENT_RECEIVED', 'FUNCTIONAL_MPR_EVENT_FREE'))
            operation['line'], receive['line'], freed['line'] = receive['line'], freed['line'], operation['line']
            self.assertLess(operation['line'], receive['line'])
            self.assertLess(receive['line'], freed['line'])
            self.assertEqual(checker.check_video(queued, transport, storage, args[0])['native_forced_IDR_requests'], 1)
            operation['line'] = 1
            with self.assertRaises(ValueError):
                checker.check_video(queued, transport, storage, args[0])

    def test_native_force_IDR_opaque_waiter_and_order_negative_stages(self):
        args = host_test_capture(self.root, native_force_factor=1)
        transport = checker.check_transport(*args)
        storage = checker.writeback.inspect(args[0])
        checker.check_video(args[2], transport, storage, args[0])
        mutations = (
            ('FUNCTIONAL_MPR_FORCE_REQUEST', 'opaque_word', '0'),
            ('FUNCTIONAL_MPR_FORCE_REQUEST', 'opaque4', '00000000'),
            ('FUNCTIONAL_MPR_FORCE_REQUEST', 'parameter_v', '0x3501'),
            ('FUNCTIONAL_MPR_FORCE_REQUEST', 'parameter_generation', '0'),
            ('FUNCTIONAL_MPR_FORCE_REQUEST', 'expected_factor', '2'),
            ('FUNCTIONAL_MPR_FORCE_IDR', 'expected_result', '0x990008'),
            ('FUNCTIONAL_MPR_FORCE_IDR', 'frame_generation', '0'),
            ('FUNCTIONAL_MPR_FORCE_IDR', 'model_token', '0'),
            ('FUNCTIONAL_MPR_FORCE_IDR', 'actual_IDR_NAL5', '0'),
            ('FUNCTIONAL_MPR_FORCE_IDR', 'publication_complete', '0'),
            ('FUNCTIONAL_MPR_FORCE_IDR', 'original_argument_semantics_verified', '1'),
        )
        for tag, key, value in mutations:
            rows = copy.deepcopy(args[2])
            next(row['fields'] for row in rows if row['tag'] == tag)[key] = value
            with self.subTest(tag=tag, key=key), self.assertRaises(ValueError):
                checker.check_video(rows, transport, storage, args[0])
        for tag in ('FUNCTIONAL_MPR_FORCE_REQUEST', 'FUNCTIONAL_MPR_FORCE_IDR'):
            rows = [row for row in args[2] if row['tag'] != tag]
            with self.subTest(missing=tag), self.assertRaises(ValueError):
                checker.check_video(rows, transport, storage, args[0])
        rows = copy.deepcopy(args[2])
        next(row for row in rows if row['tag'] == 'FUNCTIONAL_MPR_FORCE_IDR')['line'] = 1
        with self.assertRaises(ValueError):
            checker.check_video(rows, transport, storage, args[0])
        changed = copy.deepcopy(transport)
        next(tx for tx in changed['transfers'] if tx['origin']['command'] == 2)['origin']['command'] = 1
        with self.assertRaises(ValueError):
            checker.check_video(args[2], changed, storage, args[0])
        rows = copy.deepcopy(args[2])
        for row in rows:
            if row['tag'] in ('FUNCTIONAL_MPR_EVENT_RECEIVED', 'FUNCTIONAL_MPR_EVENT_FREE') and row['fields']['command'] == '2':
                wire = bytearray.fromhex(row['fields']['wire_hex'])
                struct.pack_into('<H', wire, 2, 5)
                row['fields'].update(wire_hex=wire.hex(), wire_fnv=hex(checker.fnv(wire)))
        with self.assertRaises(ValueError):
            checker.check_video(rows, transport, storage, args[0])

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

    def test_forced_frame_evidence_requires_actual_idr_nal(self):
        args = host_test_capture(self.root, video_idr_at=0)
        transport = checker.check_transport(*args)
        self.assertTrue(checker.check_frames(args[0], transport)['verified'])
        forced = next(tx for tx in transport['transfers'] if tx['opcode'] == 33)
        self.assertEqual(checker.payload_read(args[0], forced['request_payload']), struct.pack('<I', 1))
        self.assertTrue(any(nal[0] & 31 == 5 for nal in checker.camera_packets(
            checker.transfer_output(args[0], forced))[0]['nals']))

    def test_non_idr_cannot_be_relabelled_as_forced(self):
        args = host_test_capture(self.root, video_idr_at=1)
        transport = checker.check_transport(*args)
        with self.assertRaisesRegex(ValueError, 'forced video frame lacks actual IDR'):
            checker.check_frames(args[0], transport)

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

    def test_VDF163_zero6_SET_full176_and_original14_to12_lifecycle(self):
        args = host_test_capture(self.root, (True, ('display', 0x163)))
        transport = checker.check_transport(*args)
        cycle = transport['VDF_path']['cycles'][-1]
        self.assertEqual((cycle['opcode'], cycle['native_command']), (8, 0x163))
        tx = next(tx for tx in transport['transfers'] if tx['opcode'] == 8)
        canonical = struct.pack('<2I', 0x163, 6) + bytes(8)
        output = checker.transfer_output(args[0], tx)
        self.assertEqual(len(output), 176)
        self.assertEqual(output[160:], canonical)
        self.assertEqual(struct.unpack_from('<Q', output, 40)[0], checker.fnv(canonical))
        self.assertEqual(struct.unpack_from('<2Q', output, 48)[0], struct.unpack_from('<2Q', output, 48)[1])
        sent = next(row['fields'] for row in args[2] if row['tag'] == 'FUNCTIONAL_VDF_PATH_SEND' and row['fields']['command'] == '0x163')
        self.assertEqual(sent['raw'], '0d2063010e000180000000000000')
        self.assertEqual(sent['ack_wire'], '0d2063110c00018000005900')
        self.assertEqual((sent['bytes'], sent['AP_consumed']), ('14', '0'))
        checked = checker.vdf_result(output, canonical, 99, 8, output[128:144])
        self.assertEqual((checked['frame_consumed'], checked['retired'], checked['status']), (1, 1, 0))
        for offset in range(8, 16):
            wrong = bytearray(canonical);wrong[offset] = 1
            forged = bytearray(output);forged[160:] = wrong
            struct.pack_into('<Q', forged, 40, checker.fnv(wrong))
            with self.subTest(offset=offset), self.assertRaisesRegex(ValueError, 'unsupported command/body/enabled'):
                checker.vdf_result(forged, bytes(wrong), 99, 8, output[128:144])

    def test_Display_exact_legacy_policy_is_readable_only_without_new163(self):
        old_root = self.root / 'legacy-display'
        old_root.mkdir()
        args = host_test_capture(old_root, (True, ('display', 0x152), ('display', 0x162)), configuration_only=True)
        for target in (args[1], args[1]['backup_transport']):
            for key, value in checker.LEGACY_DISPLAY_POLICY.items():
                target['functional_camera_' + key] = copy.deepcopy(value)
        self.assertTrue(checker.check_transport(*args)['verified'])
        mixed = copy.deepcopy(args)
        for key, value in checker.DISPLAY_POLICY.items():
            mixed[1]['backup_transport']['functional_camera_' + key] = copy.deepcopy(value)
        with self.assertRaisesRegex(ValueError, 'Display operation lacks'):
            checker.check_transport(*mixed)
        new_root = self.root / 'new-zero6-legacy-policy'
        new_root.mkdir()
        newer = host_test_capture(new_root, (True, ('display', 0x163)), configuration_only=True)
        for target in (newer[1], newer[1]['backup_transport']):
            for key, value in checker.LEGACY_DISPLAY_POLICY.items():
                target['functional_camera_' + key] = copy.deepcopy(value)
        with self.assertRaisesRegex(ValueError, 'Display operation lacks'):
            checker.check_transport(*newer)

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

    def test_BitWidth_OP12_full_typed_content_and_original_lifecycle(self):
        for inline in (False, True):
            root = self.root / str(inline)
            root.mkdir()
            paths = REFRESH_PATHS + BB_PATHS + (('bit_width',), ('bit_width',))
            args = host_test_capture(root, paths, vdf_inline=inline, configuration_only=True, histogram=True)
            transport = checker.check_transport(*args)
            frames = checker.check_frames(args[0], transport, require_codecs=False)
            self.assertEqual(transport['opcodes']['12'], 2)
            self.assertEqual(transport['opcodes']['9'], len(BB_PATHS))
            self.assertEqual(transport['opcodes']['10'], 1)
            self.assertEqual(frames['last_counts']['jpeg_encoded'], 0)
            self.assertEqual(frames['last_counts']['video_encoded'], 0)
            self.assertFalse(transport['VDF_path']['display_bit_width_physical_mapping_verified'])
            self.assertIs(args[1]['functional_camera_runtime']['capture_verified'], False)
            generated = checker.source_module(checker.RUNTIME / 'backup_profile.py').functional_camera_profile_fields(checker.PROFILE)
            for key, expected in checker.BIT_WIDTH_POLICY.items():
                full = 'functional_camera_' + key
                self.assertTrue(checker.typed_equal(generated[full], expected))
                self.assertTrue(checker.typed_equal(args[1][full], generated[full]))
                self.assertTrue(checker.typed_equal(args[1]['backup_transport'][full], generated[full]))
            for tx in (tx for tx in transport['transfers'] if tx['opcode'] == 12):
                output = checker.transfer_output(args[0], tx)
                canonical = checker.payload_read(args[0], tx['request_payload'])
                value = checker.vdf_result(output, canonical, 99, 12, output[128:144])
                self.assertEqual((len(output), canonical, output[160:], value['class']), (168, bytes(8), bytes(8), 7))
                self.assertEqual((value['width'], value['height'], value['stride'], value['active_bytes']),
                                 (640, 480, 1920, 921600))
                self.assertEqual(value['source_fnv'], checker.fnv(bytes([0, 0, 255]) * (640 * 480)))
                self.assertEqual(value['source_fnv'], value['sink_fnv'])
                self.assertEqual(value['config_generation'], value['before_config_generation'] + 1)
                self.assertEqual(value['frame_generation'], value['before_frame_generation'] + 1)
                self.assertEqual((value['frame_consumed'], value['retired'], value['config_readback']), (1, 1, 1))
                p = tx['frame']['proof']
                self.assertEqual((p['consumer_kind'], p['result_bytes'], p['result_fnv1a64'], p['result_token']),
                                 (4, 168, checker.fnv(output), 0))
                self.assertEqual((tx['first'], tx['token']), (tx['last'], 0))
                job = next(job for job in frames['jobs'] if job['first'] == tx['first'])
                self.assertEqual(job['configuration_result_sha256'], checker.sha(output))
                self.assertNotIn('encoded_result_sha256', job)
                cycle = next(c for c in transport['VDF_path']['cycles'] if c['first'] == tx['first'])
                self.assertEqual((cycle['opcode'], cycle['native_command'], cycle['AP_consumed']), (12, 0x15e, True))
                records = [r for r in args[2] if r['tag'].startswith('FUNCTIONAL_VDF_PATH_') and
                           r['fields'].get('cycle') == str(cycle['cycle'])]
                self.assertEqual(len(records), 5)
                for row in records:
                    f = row['fields']
                    self.assertEqual(f['raw'], '0d205e010a0001800000')
                    self.assertEqual(f['ack_wire'], '0d205e110c00018000005900')
                    self.assertEqual(f['original_fnv1a'], f'{checker.fnv(bytes.fromhex(f["raw"])):016x}')
                    self.assertEqual(f['canonical_bit_width8'], '00' * 8)
                    self.assertEqual(f['model_result_hex'], output.hex())
                    self.assertEqual(f['allocation_returned'], '(nil)' if row['tag'].endswith('REQUEST_FREE') else '0x500000')
                self.assertLess(cycle['receive_line'], cycle['free_line'])
            with self.assertRaises(checker.MissingEvidence):
                checker.check_frames(args[0], transport)

    def test_BitWidth_policy_is_real_typed_complete_in_both_copies_and_legacy_optional(self):
        args = host_test_capture(self.root, (True, ('bit_width',)), configuration_only=True)
        fields = checker.source_module(checker.RUNTIME / 'backup_profile.py').functional_camera_profile_fields(checker.PROFILE)
        profile = dict(fields, backup_transport=copy.deepcopy(fields), directory_sd_profile='directory-vvfat-256gb-v1',
                       rm_file_image_bytes=checker.writeback.CARD_BYTES)
        self.assertTrue(checker.check_profile(profile)['verified'])
        for location in ('top', 'backup_transport'):
            for key, expected in checker.BIT_WIDTH_POLICY.items():
                full = 'functional_camera_' + key
                wrong_values = ('missing', None, 0, True) if expected is False else (
                    ('missing', None, [], [True], [False], [float(expected[0])], [expected[0], expected[0]])
                    if type(expected) is list else ('missing', None, False, 'physical-8bit'))
                for wrong in wrong_values:
                    changed, changed_profile = copy.deepcopy(args[1]), copy.deepcopy(profile)
                    for value in (changed, changed_profile):
                        target = value if location == 'top' else value[location]
                        if wrong == 'missing':
                            del target[full]
                        else:
                            target[full] = wrong
                    with self.subTest(location=location, key=key, wrong=wrong):
                        with self.assertRaisesRegex(ValueError, 'exact typed software policy'):
                            checker.check_transport(args[0], changed, *args[2:])
                        with self.assertRaisesRegex(ValueError, 'typed functional profile drift'):
                            checker.check_profile(changed_profile)
        legacy = self.root / 'legacy'
        legacy.mkdir()
        old = host_test_capture(legacy, (True,), configuration_only=True)
        for target in (profile, profile['backup_transport']):
            for key in checker.BIT_WIDTH_POLICY:
                del target['functional_camera_' + key]
        self.assertTrue(checker.check_profile(profile)['verified'])
        self.assertTrue(checker.check_transport(*old)['verified'])
        self.assertTrue(checker.check_frames(old[0], checker.check_transport(*old), require_codecs=False)['verified'])
        profile['functional_camera_display_bit_width_physical_mapping_verified'] = False
        with self.assertRaises(ValueError):
            checker.check_profile(profile)

    def test_BitWidth_result168_rejects_selector_reserved_tail_class_and_shapes(self):
        args = host_test_capture(self.root, (True, ('bit_width',)), configuration_only=True)
        transport = checker.check_transport(*args)
        tx = next(tx for tx in transport['transfers'] if tx['opcode'] == 12)
        raw = checker.transfer_output(args[0], tx)
        route = raw[128:144]
        mutations = ((0, '<I', 0), (4, '<I', 160), (8, '<Q', 100), (16, '<Q', 1),
                     (24, '<Q', 1), (32, '<Q', 0), (40, '<Q', 0), (48, '<Q', 0), (56, '<Q', 1),
                     (64, '<Q', 0), (72, '<I', 320), (76, '<I', 240), (80, '<I', 2560),
                     (84, '<I', 0), (88, '<I', 0), (92, '<I', 0), (96, '<I', 1), (96, '<I', 5),
                     (96, '<I', 6), (100, '<I', 0), (104, '<I', 0), (108, '<I', 0),
                     (112, '<I', 0), (116, '<I', 0), (120, '<I', 1), (124, '<I', 1),
                     (144, '<Q', 0), (152, '<Q', 0))
        for offset, fmt, wrong in mutations:
            output = bytearray(raw)
            struct.pack_into(fmt, output, offset, wrong)
            with self.subTest(offset=offset, wrong=wrong), self.assertRaises(ValueError):
                checker.vdf_result(output, bytes(8), 99, 12, route)
        for offset in range(8):
            for wrong in ((1, 2, 3, 255) if offset == 0 else (1, 255)):
                canonical, output = bytearray(8), bytearray(raw)
                canonical[offset] = wrong
                output[160:] = canonical
                struct.pack_into('<Q', output, 40, checker.fnv(canonical))
                with self.subTest(input_offset=offset, wrong=wrong), self.assertRaises(ValueError):
                    checker.vdf_result(output, canonical, 99, 12, route)
            output = bytearray(raw)
            output[160 + offset] = 1
            with self.subTest(saved_tail=offset), self.assertRaises(ValueError):
                checker.vdf_result(output, bytes(8), 99, 12, route)
        for output in (raw[:160], raw[:-1], raw + b'\0', raw + bytes(24)):
            with self.subTest(result_bytes=len(output)), self.assertRaises(ValueError):
                checker.vdf_result(output, bytes(8), 99, 12, route)
        for canonical in (b'', bytes(2), bytes(7), bytes(9), bytes(16), bytes(32)):
            with self.subTest(input_bytes=len(canonical)), self.assertRaises(ValueError):
                checker.vdf_result(raw, canonical, 99, 12, route)
        for op in (5, 6, 7, 8, 9, 10):
            with self.subTest(wrong_opcode=op), self.assertRaises(ValueError):
                checker.vdf_result(raw, bytes(8), 99, op, route)
        with self.assertRaises(ValueError):
            checker.vdf_result(raw, bytes(8), 99, 12, bytes(16))

    def test_BitWidth_original10_header_full_hash_source_and_independent115e_are_exact(self):
        args = host_test_capture(self.root, (True, ('bit_width',)), configuration_only=True)
        transport = checker.check_transport(*args)
        original = bytes.fromhex('0d205e010a0001800000')
        raw_packets = [original[:n] for n in (0, 8, 9)] + [original + b'\0', original + bytes(2)]
        for offset, wrong in ((0, 0), (2, 0x5f), (4, 8), (4, 12), (6, 0), (8, 1), (8, 2), (8, 3), (9, 1)):
            wire = bytearray(original)
            wire[offset] = wrong
            raw_packets.append(bytes(wire))
        for wire in raw_packets:
            rows = copy.deepcopy(args[2])
            changed = copy.deepcopy(transport)
            for row in rows:
                if row['tag'].startswith('FUNCTIONAL_VDF_PATH_') and row['fields'].get('command') == '0x15e':
                    row['fields'].update(raw=wire.hex(), original_fnv1a=f'{checker.fnv(wire):016x}')
            for tx in changed['transfers']:
                if tx['origin']['command'] == 0x15e:
                    tx['origin']['fnv1a64'] = checker.fnv(wire)
            with self.subTest(raw=wire.hex()), self.assertRaises(ValueError):
                checker.check_vdf_path(args[0], rows, changed)
        for key, wrong in (('ack_wire', '0d205e110c00018000000000'),
                ('ack_wire', '0d205e110c00018001005900'), ('ack_wire', '0d205e110c00018005005900'),
                ('ack_wire', '0d205e110c000180ffffffff'), ('ack_wire', '0d205f110c00018000005900'),
                ('ack_wire', '0d205e110c0001800000590000'), ('canonical_bit_width8', '00' * 7),
                ('model_result_bytes', '160'), ('realresultbytes', '192'), ('model_instance', '100'),
                ('original_fnv1a', '0000000000000000'), ('model_result_fnv1a64', '0000000000000000'),
                ('source', '0x81cf1234'), ('destination', '0x92840748'), ('command', '0x15f'), ('bytes', '12')):
            rows = copy.deepcopy(args[2])
            next(row['fields'] for row in rows if row['tag'] == 'FUNCTIONAL_VDF_PATH_AP_FREE' and
                 row['fields']['command'] == '0x15e')[key] = wrong
            with self.subTest(field=key, wrong=wrong), self.assertRaises(ValueError):
                checker.check_vdf_path(args[0], rows, transport)
        for source in (0, True, 0x81ce61ca, 0x181cf61ca, 0x10000000081cf61ca, (1 << 64) - 1, '0x81cf61ca', None):
            changed = copy.deepcopy(transport)
            next(tx for tx in changed['transfers'] if tx['opcode'] == 12)['origin']['source'] = source
            with self.subTest(source=source), self.assertRaises(ValueError):
                checker.check_vdf_path(args[0], args[2], changed)

    def test_BitWidth_original_request_free_precedes_allocation_and_receive_free_are_required(self):
        args = host_test_capture(self.root, (True, ('bit_width',)), configuration_only=True)
        transport = checker.check_transport(*args)
        mutations = (('REQUEST_FREE', 'ack_retained', '0x500000'), ('REQUEST_FREE', 'allocation_returned', '0x500000'),
            ('REQUEST_FREE', 'request_freed', '0'), ('REQUEST_FREE', 'request_free_rc', '-1'),
            ('SEND', 'allocation_returned', '(nil)'), ('SEND', 'allocation_alias', '1'),
            ('SEND', 'request_retained', '0x400000'), ('RECEIVE', 'ack_retained', '(nil)'),
            ('RECEIVE', 'receiver_tid', '91'), ('AP_FREE', 'free_tid', '91'), ('AP_FREE', 'free_rc', '-1'),
            ('AP_FREE', 'AP_consumed', '0'), ('COMPLETE', 'model_complete', '0'), ('SEND', 'sender_tid', '91'),
            ('SEND', 'tid', '91'), ('AP_FREE', 'model_instance', '100'), ('SEND', 'capture_verified', '1'),
            ('SEND', 'physical_ASIC_verified', '1'), ('SEND', 'original_selector_verified', '1'),
            ('SEND', 'original_CP_FIFO_verified', '1'), ('SEND', 'physical_CP_RTOS_verified', '1'))
        for tag, key, wrong in mutations:
            rows = copy.deepcopy(args[2])
            next(row['fields'] for row in rows if row['tag'] == 'FUNCTIONAL_VDF_PATH_' + tag and
                 row['fields']['command'] == '0x15e')[key] = wrong
            with self.subTest(tag=tag, key=key), self.assertRaises(ValueError):
                checker.check_vdf_path(args[0], rows, transport)
        for tag in ('REQUEST_FREE', 'SEND', 'COMPLETE', 'RECEIVE', 'AP_FREE'):
            rows = [row for row in args[2] if not (row['tag'] == 'FUNCTIONAL_VDF_PATH_' + tag and
                    row['fields']['command'] == '0x15e')]
            with self.subTest(missing=tag), self.assertRaises(checker.MissingEvidence):
                checker.check_vdf_path(args[0], rows, transport)
        for key in ('canonical_bit_width8', 'model_result_bytes', 'allocation_returned', 'allocation_alias', 'request_free_rc'):
            rows = copy.deepcopy(args[2])
            del next(row['fields'] for row in rows if row['tag'] == 'FUNCTIONAL_VDF_PATH_REQUEST_FREE' and
                     row['fields']['command'] == '0x15e')[key]
            with self.subTest(missing_field=key), self.assertRaises((ValueError, KeyError)):
                checker.check_vdf_path(args[0], rows, transport)
        rows = copy.deepcopy(args[2])
        send = next(row for row in rows if row['tag'] == 'FUNCTIONAL_VDF_PATH_SEND' and row['fields']['command'] == '0x15e')
        free = next(row for row in rows if row['tag'] == 'FUNCTIONAL_VDF_PATH_REQUEST_FREE' and row['fields']['command'] == '0x15e')
        send['line'], free['line'] = free['line'], send['line']
        with self.assertRaisesRegex(ValueError, 'order differs'):
            checker.check_vdf_path(args[0], rows, transport)

    def test_BitWidth_native015e_cannot_be_relabelled_as_STILL_CONFIG_BB_or_STATE(self):
        args = host_test_capture(self.root, (True, ('bit_width',)), configuration_only=True)
        transport = checker.check_transport(*args)
        for opcode in (True, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 16, 32, 33, 34, 64, 65, 66):
            changed = copy.deepcopy(transport)
            next(tx for tx in changed['transfers'] if tx['opcode'] == 12)['opcode'] = opcode
            with self.subTest(opcode=opcode), self.assertRaisesRegex(ValueError, 'original015e.*relabelled'):
                checker.check_vdf_path(args[0], args[2], changed)
        for key, wrong in (('command', 0x15f), ('command', 0x153), ('bytes', 12), ('destination', 0x92840748),
                           ('producer_tid', 91), ('fnv1a64', 0)):
            changed = copy.deepcopy(transport)
            next(tx for tx in changed['transfers'] if tx['opcode'] == 12)['origin'][key] = wrong
            with self.subTest(origin=key), self.assertRaises(ValueError):
                checker.check_vdf_path(args[0], args[2], changed)

    def test_BitWidth_kind4_requires_full168_receipt_fresh_RGB_and_no_codec(self):
        args = host_test_capture(self.root, (True, ('bit_width',)), configuration_only=True)
        transport = checker.check_transport(*args)
        mutations = (('consumer_kind', 1), ('consumer_kind', 5), ('consumer_kind', 6), ('opcode', 9),
            ('result_bytes', 0), ('result_bytes', 160), ('result_fnv1a64', checker.fnv(b'')), ('result_token', 1),
            ('encoder_consumed', 1), ('encoded_bytes', 168), ('encoded_fnv1a64', 0),
            ('source_fnv1a64', 0), ('consumer_before_fnv1a64', 1), ('consumer_after_fnv1a64', 1),
            ('render_observed', 0), ('consumer_entered', 0), ('consumer_returned', 0), ('retired', 0),
            ('model_instance', 100), ('owner_pid', 178), ('config_generation', 1), ('frame_generation', 1),
            ('lease_generation', 0), ('width', 24), ('height', 16), ('stride', 1921), ('active_bytes', 0),
            ('render_status', -1), ('consumer_status', -1), ('retire_status', -1), ('operation_status', -1))
        for key, wrong in mutations:
            changed = copy.deepcopy(transport)
            next(tx['frame']['proof'] for tx in changed['transfers'] if tx['opcode'] == 12)[key] = wrong
            with self.subTest(proof=key):
                with self.assertRaises(ValueError):
                    checker.check_vdf_path(args[0], args[2], changed)
                with self.assertRaises(ValueError):
                    checker.check_frames(args[0], changed, require_codecs=False)
        for counter in ('rendered', 'consumed', 'retired', 'jpeg_encoded', 'video_encoded'):
            changed = copy.deepcopy(transport)
            next(tx['frame']['proof'] for tx in changed['transfers'] if tx['opcode'] == 12)['after'][counter] += 1
            with self.subTest(counter=counter), self.assertRaises(ValueError):
                checker.check_vdf_path(args[0], args[2], changed)
        changed = copy.deepcopy(transport)
        next(tx for tx in changed['transfers'] if tx['opcode'] == 12)['frame'] = None
        with self.assertRaises(checker.MissingEvidence):
            checker.check_vdf_path(args[0], args[2], changed)
        with self.assertRaises(checker.MissingEvidence):
            checker.check_frames(args[0], changed, require_codecs=False)
        for key, wrong in (('serial', 1), ('model_lifetime', 2), ('render_observed', True)):
            changed = copy.deepcopy(transport)
            next(tx['frame']['proof'] for tx in changed['transfers'] if tx['opcode'] == 12)[key] = wrong
            with self.subTest(frame_history=key):
                with self.assertRaises(ValueError):
                    checker.check_vdf_path(args[0], args[2], changed)
                with self.assertRaises(ValueError):
                    checker.check_frames(args[0], changed, require_codecs=False)

    def test_BitWidth_actual_payload_tail_cannot_be_repaired_with_only_local_FNV(self):
        args = host_test_capture(self.root, (True, ('bit_width',)), configuration_only=True)
        transport = checker.check_transport(*args)
        tx = next(tx for tx in transport['transfers'] if tx['opcode'] == 12)
        rows = copy.deepcopy(args[2])
        output = bytearray(checker.transfer_output(args[0], tx))
        output[-1] = 1
        for row in rows:
            if row['tag'].startswith('FUNCTIONAL_VDF_PATH_') and row['fields'].get('command') == '0x15e':
                row['fields'].update(model_result_hex=output.hex(), model_result_fnv1a64=f'{checker.fnv(output):016x}')
        with self.assertRaisesRegex(ValueError, 'raw request/ACK/config/result bytes differ'):
            checker.check_vdf_path(args[0], rows, transport)
        reference = tx['output_payloads'][0]
        (args[0] / reference['path']).write_bytes(output)
        with self.assertRaises(ValueError):
            checker.check_transport(*args)
        with self.assertRaises(ValueError):
            checker.vdf_result(output, bytes(8), 99, 12, output[128:144])

    def test_BitWidth_frame_history_preserves_route_Config48_and_generation_lease(self):
        args = host_test_capture(self.root, (True, ('bit_width',), ('bit_width',)), configuration_only=True)
        transport = checker.check_transport(*args)
        tx = next(tx for tx in transport['transfers'] if tx['opcode'] == 12)
        original = checker.transfer_output
        raw = original(args[0], tx)
        for offsets in ((131,), (16, 152), (24, 144), (32,)):
            output = bytearray(raw)
            for offset in offsets:
                if offset == 131:
                    output[offset] ^= 1
                else:
                    struct.pack_into('<Q', output, offset, 1 if offset == 32 else struct.unpack_from('<Q', output, offset)[0] + 1)
            self.assertEqual(checker.vdf_result(output, bytes(8), 99, 12, output[128:144])['class'], 7)
            def forged(run, item):
                return bytes(output) if item['first'] == tx['first'] else original(run, item)
            with self.subTest(history=offsets), mock.patch.object(checker, 'transfer_output', side_effect=forged):
                with self.assertRaises(ValueError):
                    checker.vdf_history(args[0], transport)
        follow = transport['transfers'][transport['transfers'].index(tx) + 1]
        output = bytearray(original(args[0], follow))
        output[24] ^= 1
        def forged_state(run, item):
            return bytes(output) if item['first'] == follow['first'] else original(run, item)
        with mock.patch.object(checker, 'transfer_output', side_effect=forged_state), self.assertRaisesRegex(ValueError, 'Config48'):
            checker.vdf_history(args[0], transport)

    def test_BitWidth_mailbox_requires_real_integer_OP12_input8_and_native_origin(self):
        args = host_test_capture(self.root, (True, ('bit_width',)), configuration_only=True)
        for offset, wrong in ((32, 9), (32, 6), (36, 2), (36, 7), (36, 9), (36, 16), (16, 100),
                              (96, 91), (100, 0x81cf1234), (104, 0x92840748), (108, 0x15f), (112, 12)):
            changed = copy.deepcopy(args)
            event = next(row for row in changed[3] if row['kind'] == 'request' and row['opcode'] == 12)
            header = bytearray.fromhex(event['raw_header_hex'])
            struct.pack_into('<I', header, offset, wrong)
            event.update(raw_header_hex=header.hex(), raw_header_sha256=checker.sha(header))
            with self.subTest(header_offset=offset, wrong=wrong), self.assertRaises(ValueError):
                checker.check_transport(*changed)
        for opcode in (True, 12.0, '12'):
            changed = copy.deepcopy(args)
            next(row for row in changed[3] if row['kind'] == 'request' and row['opcode'] == 12)['opcode'] = opcode
            with self.subTest(opcode=opcode), self.assertRaises(ValueError):
                checker.check_transport(*changed)
        for location in ('origin', 'request_payload'):
            changed = copy.deepcopy(args)
            event = next(row for row in changed[3] if row['kind'] == 'request' and row['opcode'] == 12)
            target = event['origin'] if location == 'origin' else event['request_payload']['origin']
            target['source'] += 1 << 32
            with self.subTest(source_high=location), self.assertRaises(ValueError):
                checker.check_transport(*changed)

    def test_BitWidth_disabled_route_is_not_a_consumed_frame(self):
        args = host_test_capture(self.root, (False, ('bit_width',)), configuration_only=True)
        with self.assertRaisesRegex(ValueError, 'active full 640x480'):
            checker.check_transport(*args)

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

    def test_Display0170_three_boolean_identity_all_eight_tuples_full_readback(self):
        for bits in range(8):
            flags = tuple((bits >> index) & 1 for index in range(3))
            body = bytes((*flags, 0, 0, 0, 0, 0))
            root = self.root / f'0170-tuple-{bits}'
            root.mkdir()
            args = host_test_capture(root, (True, ('display', 0x170, body)), configuration_only=True)
            transport = checker.check_transport(*args)
            frames = checker.check_frames(args[0], transport, require_codecs=False)
            self.assertTrue(frames['verified'])
            tx = next(tx for tx in transport['transfers'] if tx['opcode'] == 8)
            output = checker.transfer_output(args[0], tx)
            canonical = checker.payload_read(args[0], tx['request_payload'])
            self.assertEqual((len(output), len(canonical)), (176, 16))
            self.assertEqual(canonical, struct.pack('<2I', 0x170, 4) + body)
            self.assertEqual(output[160:], canonical)
            self.assertEqual(struct.unpack_from('<Q', output, 40)[0], checker.fnv(canonical))
            value = checker.vdf_result(output, canonical, 99, 8, output[128:144])
            self.assertEqual((value['enabled'], value['frame_consumed'], value['retired'],
                              value['config_readback'], value['committed']), (1, 1, 1, 1, 1))
            self.assertEqual((value['stride'], value['active_bytes']),
                             (value['width'] * 3, value['width'] * value['height'] * 3))
            self.assertEqual(value['source_fnv'], value['sink_fnv'])
            self.assertEqual(value['source_fnv'], checker.fnv(bytes([0, 0, 255]) * (value['width'] * value['height'])))
            self.assertNotEqual(value['source_fnv'], 0)
            self.assertEqual(value['config_generation'], value['before_config_generation'] + 1)
            self.assertEqual(value['frame_generation'], value['before_frame_generation'] + 1)
            proof = tx['frame']['proof']
            self.assertEqual((proof['opcode'], proof['consumer_kind'], proof['render_observed'],
                              proof['retired'], proof['encoder_consumed']), (8, 4, 1, 1, 0))
            self.assertEqual(proof['source_fnv1a64'], value['source_fnv'])
            self.assertEqual(proof['consumer_after_fnv1a64'], value['sink_fnv'])
            sent = next(row['fields'] for row in args[2] if row['tag'] == 'FUNCTIONAL_VDF_PATH_SEND' and
                        row['fields']['command'] == '0x170')
            self.assertEqual(sent['raw'], '0d2070010c000180' + body[:4].hex())
            self.assertEqual(sent['ack_wire'], '0d2070110c00018000005900')
            self.assertEqual((sent['bytes'], sent['source']), ('12', '0x81cf61c7'))
            self.assertEqual(len(bytes.fromhex(sent['raw'])), 12)
            cycle = next(cycle for cycle in transport['VDF_path']['cycles'] if cycle['first'] == tx['first'])
            self.assertEqual((cycle['opcode'], cycle['native_command'], cycle['AP_consumed']), (8, 0x170, True))
            self.assertLess(cycle['receive_line'], cycle['free_line'])
            self.assertEqual(len([row for row in args[2] if row['tag'].startswith('FUNCTIONAL_VDF_PATH_') and
                                  row['fields'].get('cycle') == str(cycle['cycle'])]), 5)
            self.assertIs(args[1]['functional_camera_runtime']['capture_verified'], False)
            self.assertFalse(transport['VDF_path']['physical_asic_compatibility_verified'])
            self.assertFalse(transport['VDF_path']['original_0162_feature_verified'])
            if bits == 3:
                self.assertEqual(body[:4], bytes.fromhex('01010000'))

    def test_Display0170_full_capture_async_and_inline_keep_capture_false(self):
        body = bytes.fromhex('01010000') + bytes(4)
        for inline in (False, True):
            root = self.root / ('0170-full-inline' if inline else '0170-full-async')
            root.mkdir()
            args = host_test_capture(root, (True, ('display', 0x170, body)), vdf_inline=inline)
            transport = checker.check_transport(*args)
            frames = checker.check_frames(args[0], transport, require_codecs=False)
            self.assertTrue(frames['verified'])
            tx = next(tx for tx in transport['transfers'] if tx['opcode'] == 8)
            output = checker.transfer_output(args[0], tx)
            canonical = checker.payload_read(args[0], tx['request_payload'])
            value = checker.vdf_result(output, canonical, 99, 8, output[128:144])
            self.assertEqual((len(output), output[160:]), (176, struct.pack('<2I', 0x170, 4) + body))
            self.assertEqual(value['source_fnv'], value['sink_fnv'])
            self.assertEqual((value['retired'], value['frame_consumed'], value['config_generation'],
                              value['frame_generation']),
                             (1, 1, value['before_config_generation'] + 1, value['before_frame_generation'] + 1))
            cycle = next(cycle for cycle in transport['VDF_path']['cycles'] if cycle['first'] == tx['first'])
            self.assertEqual((cycle['opcode'], cycle['native_command'], cycle['AP_consumed']), (8, 0x170, True))
            self.assertLess(cycle['receive_line'], cycle['free_line'])
            self.assertIs(args[1]['functional_camera_runtime']['capture_verified'], False)
            self.assertFalse(transport['VDF_path']['physical_asic_compatibility_verified'])

    def test_Display0170_invalid_body_and_transport_mutants_reject(self):
        valid = bytes.fromhex('01010000') + bytes(4)
        for name, body in (('flag2', bytes([1, 2, 0, 0, 0, 0, 0, 0])),
                           ('reserved-byte11', bytes([1, 1, 0, 1, 0, 0, 0, 0])),
                           ('virtual-padding', bytes([1, 1, 0, 0, 1, 0, 0, 0]))):
            root = self.root / ('0170-invalid-' + name)
            root.mkdir()
            args = host_test_capture(root, (True, ('display', 0x170, body)), configuration_only=True)
            with self.subTest(body=name), self.assertRaises(ValueError):
                checker.check_transport(*args)

        root = self.root / '0170-mutants'
        root.mkdir()
        args = host_test_capture(root, (True, ('display', 0x152, PEAKING_BODY8),
                                        ('display', 0x170, valid)), configuration_only=True)
        transport = checker.check_transport(*args)
        tx = next(item for item in transport['transfers'] if item['opcode'] == 8 and item['origin']['command'] == 0x170)
        raw = checker.transfer_output(args[0], tx)
        canonical = checker.payload_read(args[0], tx['request_payload'])
        route = raw[128:144]
        value = checker.vdf_result(raw, canonical, 99, 8, route)
        self.assertEqual((value['retired'], value['config_generation'], value['frame_generation']),
                         (1, value['before_config_generation'] + 1, value['before_frame_generation'] + 1))
        for offset, wrong in ((0, 0x171), (4, 3), (4, 5)):
            envelope, output = bytearray(canonical), bytearray(raw)
            struct.pack_into('<I', envelope, offset, wrong)
            output[160:] = envelope
            struct.pack_into('<Q', output, 40, checker.fnv(envelope))
            with self.subTest(command_size=offset), self.assertRaises(ValueError):
                checker.vdf_result(output, envelope, 99, 8, route)
        for index in (11, 12):
            envelope, output = bytearray(canonical), bytearray(raw)
            envelope[index] = 1
            output[160:] = envelope
            struct.pack_into('<Q', output, 40, checker.fnv(envelope))
            with self.subTest(body_reserved=index), self.assertRaises(ValueError):
                checker.vdf_result(output, envelope, 99, 8, route)
        for key, wrong in (('bytes', '13'), ('command', '0x171')):
            rows = copy.deepcopy(args[2])
            next(row for row in rows if row['tag'] == 'FUNCTIONAL_VDF_PATH_SEND' and
                 row['fields']['command'] == '0x170')['fields'][key] = wrong
            with self.subTest(receipt=key), self.assertRaises(ValueError):
                checker.check_vdf_path(args[0], rows, transport)
        for name, offset in (('sink', 56), ('readback', None)):
            output = bytearray(raw)
            if offset is None:
                output[160] ^= 1
            else:
                struct.pack_into('<Q', output, offset, 0)
            with self.subTest(missing=name), self.assertRaises(ValueError):
                checker.vdf_result(output, canonical, 99, 8, output[128:144])
        for offset, old in ((16, 152), (24, 144)):
            output = bytearray(raw)
            struct.pack_into('<Q', output, offset, struct.unpack_from('<Q', raw, old)[0])
            with self.subTest(old_generation=offset), self.assertRaises(ValueError):
                checker.vdf_result(output, canonical, 99, 8, output[128:144])
        changed = copy.deepcopy(transport)
        next(item for item in changed['transfers'] if item['first'] == tx['first'])['frame'] = None
        with self.subTest(mutant='frame'), self.assertRaises(checker.MissingEvidence):
            checker.check_vdf_path(args[0], args[2], changed)
        changed = copy.deepcopy(transport)
        next(item['frame']['proof'] for item in changed['transfers'] if item['first'] == tx['first'])[
            'frame_generation'] = value['before_frame_generation']
        with self.subTest(mutant='proof-generation'), self.assertRaises(ValueError):
            checker.check_vdf_path(args[0], args[2], changed)
        rows = copy.deepcopy(args[2])
        other = next(row['fields']['canonical_display16'] for row in rows if
                     row['tag'] == 'FUNCTIONAL_VDF_PATH_SEND' and row['fields']['command'] == '0x152')
        next(row for row in rows if row['tag'] == 'FUNCTIONAL_VDF_PATH_SEND' and
             row['fields']['command'] == '0x170')['fields']['canonical_display16'] = other
        with self.subTest(mutant='other-display-bank'), self.assertRaises(ValueError):
            checker.check_vdf_path(args[0], rows, transport)
        rows = copy.deepcopy(args[2])
        next(row for row in rows if row['tag'] == 'FUNCTIONAL_VDF_PATH_SEND' and
             row['fields']['command'] == '0x170')['fields']['ack_wire'] = struct.pack(
                 '<4HI', 0x200d, 0x1170, 12, 0x8001, 0xf000).hex()
        with self.subTest(mutant='ack-status'), self.assertRaises(ValueError):
            checker.check_vdf_path(args[0], rows, transport)
        for tag in ('RECEIVE', 'AP_FREE'):
            rows = [row for row in args[2] if not (row['tag'] == 'FUNCTIONAL_VDF_PATH_' + tag and
                                                   row['fields'].get('command') == '0x170')]
            with self.subTest(mutant='missing-' + tag), self.assertRaises(checker.MissingEvidence):
                checker.check_vdf_path(args[0], rows, transport)
        rows = copy.deepcopy(args[2])
        next(row for row in rows if row['tag'] == 'FUNCTIONAL_VDF_PATH_SEND' and
             row['fields']['command'] == '0x170')['fields']['source'] = '0x81cf61c8'
        with self.subTest(mutant='source'), self.assertRaises(ValueError):
            checker.check_vdf_path(args[0], rows, transport)
        changed = copy.deepcopy(args)
        event = next(row for row in changed[3] if row['kind'] == 'request' and row['opcode'] == 8 and
                     row['origin']['command'] == 0x170)
        event['origin']['source'] ^= 1
        event['request_payload']['origin']['source'] ^= 1
        with self.subTest(mutant='payload-source'), self.assertRaises(ValueError):
            checker.check_transport(*changed)

    def test_Display0170_policy_producer_exact_old3_old4_borrow_and_mixed_reject(self):
        producer = checker.source_module(checker.RUNTIME / 'backup_profile.py')
        generated = producer.functional_camera_profile_fields(checker.PROFILE)
        for key, expected in checker.DISPLAY_POLICY.items():
            self.assertTrue(checker.typed_equal(generated['functional_camera_' + key], expected))
        self.assertEqual(checker.DISPLAY_POLICY['display_config_commands'], [0x141, 0x152, 0x162, 0x163, 0x170])
        body = bytes.fromhex('01010000') + bytes(4)
        for name, paths, policy in (
                ('old3', (True, ('display', 0x152, PEAKING_BODY8), ('display', 0x162)),
                 checker.LEGACY_DISPLAY_POLICY),
                ('old4', (True, ('display', 0x163)), checker.ZERO6_DISPLAY_POLICY)):
            root = self.root / ('0170-policy-' + name)
            root.mkdir()
            args = host_test_capture(root, paths, configuration_only=True)
            for target in (args[1], args[1]['backup_transport']):
                for key, value in policy.items():
                    target['functional_camera_' + key] = copy.deepcopy(value)
            self.assertTrue(checker.check_transport(*args)['verified'])
        base_root = self.root / '0170-policy-170'
        base_root.mkdir()
        base = host_test_capture(base_root, (True, ('display', 0x152, PEAKING_BODY8),
                                            ('display', 0x170, body)), configuration_only=True)
        for name, policy in (('legacy', checker.LEGACY_DISPLAY_POLICY),
                             ('zero6', checker.ZERO6_DISPLAY_POLICY)):
            changed = copy.deepcopy(base)
            for target in (changed[1], changed[1]['backup_transport']):
                for key, value in policy.items():
                    target['functional_camera_' + key] = copy.deepcopy(value)
            with self.subTest(borrowed=name), self.assertRaisesRegex(ValueError, 'Display operation lacks'):
                checker.check_transport(*changed)
        for side in ('manifest', 'backup_transport'):
            changed = copy.deepcopy(base)
            target = changed[1] if side == 'manifest' else changed[1]['backup_transport']
            for key, value in checker.ZERO6_DISPLAY_POLICY.items():
                target['functional_camera_' + key] = copy.deepcopy(value)
            with self.subTest(single_side=side), self.assertRaisesRegex(ValueError, 'Display operation lacks'):
                checker.check_transport(*changed)
        missing_transport = copy.deepcopy(base)
        del missing_transport[1]['backup_transport']['functional_camera_display_config_commands']
        with self.subTest(missing='transport-field'), self.assertRaisesRegex(ValueError, 'Display operation lacks'):
            checker.check_transport(*missing_transport)
        fields = producer.functional_camera_profile_fields(checker.PROFILE)
        profile = dict(fields, backup_transport=copy.deepcopy(fields), directory_sd_profile='directory-vvfat-256gb-v1',
                       rm_file_image_bytes=checker.writeback.CARD_BYTES)
        self.assertTrue(checker.check_profile(profile)['verified'])
        for side, policy in (('manifest', checker.ZERO6_DISPLAY_POLICY),
                             ('backup_transport', checker.LEGACY_DISPLAY_POLICY)):
            changed = copy.deepcopy(profile)
            target = changed if side == 'manifest' else changed[side]
            for key, value in policy.items():
                target['functional_camera_' + key] = copy.deepcopy(value)
            with self.subTest(profile_side=side), self.assertRaisesRegex(
                    ValueError, 'typed functional profile drift: display policy'):
                checker.check_profile(changed)
        mixed = copy.deepcopy(profile)
        for key, value in checker.ZERO6_DISPLAY_POLICY.items():
            mixed['functional_camera_' + key] = copy.deepcopy(value)
        for key, value in checker.LEGACY_DISPLAY_POLICY.items():
            mixed['backup_transport']['functional_camera_' + key] = copy.deepcopy(value)
        with self.subTest(profile='mixed'), self.assertRaisesRegex(
                ValueError, 'typed functional profile drift: display policy'):
            checker.check_profile(mixed)
        missing_profile = copy.deepcopy(profile)
        del missing_profile['backup_transport']['functional_camera_display_config_commands']
        with self.subTest(profile='missing'), self.assertRaisesRegex(
                ValueError, 'typed functional profile drift: display policy'):
            checker.check_profile(missing_profile)

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
        value['evidence'] = {'functional_AP_source_snapshot_consumed': dict(verified=True)}
        self.assertFalse(checker.finish_verdict(value, {})['capture_verified'])
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
        self.assertEqual(checker.READONLY_SCOPE_QEMU_SHA256, '4e85c70ba38774e9439562a7178a65bdbe6b660fdf8dd6bd4ece686fb707a4d4')
        args = list(host_test_transport(self.root))
        args[3][0]['config']['qemu_sha256'] = 'e23589c44386c19417551c982e394b7a4e779f8e68a72f2964b705aca1e96c0d'
        with self.assertRaises(ValueError):
            checker.check_transport(*args)

    def test_transport_uses_bound_new_digest_and_rejects_old_new_broker_mixes(self):
        args = list(host_test_transport(self.root))
        run, manifest, rows, events, build = args
        runner = manifest['functional_camera_runtime']
        build['qemu_sha256'] = checker.READONLY_SCOPE_QEMU_SHA256
        runner['artifact']['qemu_sha256'] = checker.READONLY_SCOPE_QEMU_SHA256
        events[0]['config']['qemu_sha256'] = checker.READONLY_SCOPE_QEMU_SHA256
        (run / 'functional-camera-runner.json').write_text(json.dumps(runner))
        self.assertTrue(checker.check_transport(*args)['verified'])
        events[0]['config']['qemu_sha256'] = checker.QEMU_SHA256
        with self.assertRaisesRegex(ValueError, 'mixed-run/owner/QEMU'):
            checker.check_transport(*args)
        build['qemu_sha256'] = runner['artifact']['qemu_sha256'] = checker.QEMU_SHA256
        events[0]['config']['qemu_sha256'] = checker.READONLY_SCOPE_QEMU_SHA256
        (run / 'functional-camera-runner.json').write_text(json.dumps(runner))
        with self.assertRaisesRegex(ValueError, 'mixed-run/owner/QEMU'):
            checker.check_transport(*args)
        build['qemu_sha256'] = runner['artifact']['qemu_sha256'] = events[0]['config']['qemu_sha256'] = 'f' * 64
        (run / 'functional-camera-runner.json').write_text(json.dumps(runner))
        with self.assertRaisesRegex(ValueError, 'not an admitted batch executable'):
            checker.check_transport(*args)

    def test_duplicate_and_nonfinite_json_fail_closed(self):
        for raw in (b'{"rc":0,"rc":1}', b'{"nested":{"x":1,"x":2}}', b'{"x":NaN}', b'{"x":1e999}'):
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                checker.object_json(raw)

    def test_jsonl_truncation_sequence_and_duplicate_fields(self):
        oversized = dict(event=1, monotonic_ns=1, kind='core_result', padding='x' * 17000)
        with self.assertRaisesRegex(ValueError, 'oversized non-source'):
            checker.jsonl((json.dumps(oversized) + '\n').encode())
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

    def test_actual_ash_prompt_prefix_keeps_observer_fields_and_line_numbers(self):
        record = b'FUNCTIONAL_CAMERA_TRANSFER seq=17..24 op=11 token=0x8000000000000001 error=0\n'
        raw = b'ordinary console\n' + record + b'OBS ' + record + b'/ # OBS ' + record
        rows = checker.parse_console(raw)
        self.assertEqual([r['line'] for r in rows], [2, 3, 4])
        self.assertEqual([r['fields'] for r in rows], [rows[0]['fields']] * 3)
        self.assertEqual(rows[0]['fields']['seq'], '17..24')
        for prefix in (b'echo OBS ', b'/ # echo OBS ', b'output / # OBS ', b'/ # OBS OBS '):
            with self.subTest(prefix=prefix):
                self.assertEqual(checker.parse_console(prefix + record), [])
        for suffix in (b'error=0 error=1\n', b'error=0'):
            with self.subTest(suffix=suffix), self.assertRaises(ValueError):
                checker.parse_console(b'/ # OBS FUNCTIONAL_CAMERA_TRANSFER ' + suffix)

    def test_complete_control_commit_and_exact_kernel_trailer_keep_both_records(self):
        original, = checker.parse_console(E6MX_CONTROL_COMMIT)
        guest = E6MX_CONTROL_COMMIT[:-2]
        kernel = b'[ 5371.235382] UDIF: cdev_ioctl() Line 100: uipc: warning ret = -1022'
        raw = guest + kernel + b'\r\n'
        parsed, = checker.parse_console(raw)
        self.assertEqual(parsed['fields'], original['fields'])
        self.assertEqual(parsed['kernel_diagnostic']['raw'], kernel.decode())
        self.assertEqual(parsed['kernel_diagnostic']['sha256'], checker.sha(kernel))
        self.assertEqual(parsed['kernel_diagnostic']['bytes'], len(kernel))
        self.assertEqual(parsed['kernel_diagnostic']['cause'], 'unknown')
        self.assertEqual(parsed['kernel_diagnostic']['payload']['raw'].encode(), guest[4:])
        self.assertEqual(parsed['kernel_diagnostic']['byte_offset'], len(guest))
        for changed in (kernel.replace(b'-1022', b'-1021'), b'unknown kernel trailer',
                        kernel.replace(b'5371.235382', b'not-a-timestamp')):
            row, = checker.parse_console(guest + changed + b'\n')
            self.assertIn('diagnostic', row)
            self.assertNotIn('kernel_diagnostic', row)
        for changed in (guest.replace(b'capture=0', b'capture=1'),
                        guest.removesuffix(b' capture=0'), guest.replace(b'pid=259', b'pid=0259'),
                        guest.replace(b'phase=3', b'phase=4294967296'),
                        guest.replace(b'wire_fnv1a=765864c96674cfe9', b'wire_fnv1a=765864C96674cfe9'),
                        guest.replace(b'pid=259 tid=380', b'tid=380 pid=259'),
                        b'OBS FUNCTIONAL_CAMERA_CONTROL_COMMIT pid=259 capture=0',
                        guest.replace(b'FUNCTIONAL_CAMERA_CONTROL_COMMIT', b'FUNCTIONAL_CAMERA_TRANSFER')):
            row, = checker.parse_console(changed + kernel + b'\n')
            self.assertIn('diagnostic', row)
            self.assertNotIn('kernel_diagnostic', row)
        for changed in (guest + kernel, b'OBS FUNCTIONAL_CAMERA_CONTROL_COMMIT pid=1 pid=2 capture=0' + kernel + b'\n'):
            with self.subTest(raw=changed), self.assertRaises(ValueError):
                checker.parse_console(changed)
        self.assertEqual(raw, guest + kernel + b'\r\n')

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


class StartupControlEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='HOST_TEST_startup_control_evidence_')
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def replay(self, *, inline=False, commands=(0x4014, 0x4057, 0x4014, 0x4057),
               cookies=(0x8000003c, 0x80000026, 0x8000003c, 0), root=None):
        """HOST_TEST replays actual owner generic events; no native execution or ready stub."""
        root = root or self.root
        base = root / 'base'
        base.mkdir()
        still = StillFormatEvidenceTests()
        args = still.replay(root=base)
        requests = [e for e in args[3] if e['kind'] == 'request']
        outputs = {e['sequence']: e for e in args[3] if e['kind'] == 'core_result'}
        proofs = {e['sequence']: e['proof'] for e in args[3] if e['kind'] == 'model_frame'}
        operations = [dict(op=e['opcode'], data=checker.payload_read(args[0], e['request_payload']),
            output=checker.payload_read(args[0], outputs[e['sequence']]['output_payload']), origin=e['origin'],
            **(dict(proof=proofs[e['sequence']]) if e['sequence'] in proofs else {})) for e in requests]
        records, index = [], 0
        for text in (args[0] / 'console.log').read_text().splitlines():
            if text.startswith('OBS FUNCTIONAL_CAMERA_TRANSFER '):
                text = 'HOST_TEST_TRANSFER_' + str(index)
                index += 1
            records.append(text)
        previous, last_proof = operations[-1]['output'], copy.deepcopy(list(proofs.values())[-1])
        route = next(o['output'][128:144] for o in reversed(operations) if o['op'] == 13)
        requested, completed = [0, 0], [0, 0]
        def emit(tag, fields):
            records.append(tag + ' ' + ' '.join(f'{k}={v}' for k, v in fields.items()))
        for cycle, (command, cookie) in enumerate(zip(commands, cookies), 1):
            focus = command == 0x403f
            slot, size = int(command == 0x4057), 24 if command == 0x4014 else 16 if focus else 12
            body = checker.STARTUP_CONTROL_MODE_BODY if command == 0x4014 else bytes(8 if focus else 4)
            wire = bytes((5, 0 if focus else 0xa5 if cycle > 2 else 0)) + struct.pack('<HI', command, cookie) + body
            native = dict(producer_tid=90, source=0x80020002, destination=0x90040193 if focus else 0x90030001,
                          command=command, bytes=size, fnv1a64=checker.fnv(wire))
            if focus:
                emit('FUNCTIONAL_CAMERA_FOCUS_MAGNIFICATION_RESET_REQUEST', dict(pid=77, tid=90,
                    source='0x80020002', destination='0x90040193', cmd='0x403f', token=hex(cookie), request_bytes=16,
                    raw=wire.hex(), native_fnv=hex(checker.fnv(wire)), policy=checker.FOCUS_RESET_POLICY, capture_verified=0))
            else:
                emit('NATIVE_CP_BACKGROUND_INPUT_AUDIT', dict(pid=77, tid=90, sequence=200 + cycle, entry='async',
                    pointer='0x500000', destination='0x90030001', bytes=size, source='0x80020002', size_known=1,
                    source_known=1, bytes_complete=1, complete=1, producer_return=hex(0x7f25c3f000 + 0x3535a68),
                    consumed=0, state_verified=0, capture_verified=0))
                emit('NATIVE_CP_BACKGROUND_INPUT_AUDIT_BYTES', dict(pid=77, tid=90, sequence=200 + cycle,
                    offset=0, bytes=size, raw=wire.hex()))
                records.extend(JFZ_VDF_RESOURCE_OBS.replace('FUNCTIONAL_VDF_PATH_', 'FUNCTIONAL_STARTUP_CONTROL_')
                               .replace('pid=258', 'pid=77').replace('tid=381', 'tid=90').splitlines())
                pred = self.predecessor()
                emit('FUNCTIONAL_STARTUP_CONTROL_PREDECESSORS', pred)
            operations.append(dict(op=2, data=b'', output=previous, origin=native))
            records.append('HOST_TEST_TRANSFER_' + str(len(operations) - 1))
            if not focus:
                emit('FUNCTIONAL_STARTUP_CONTROL_PREDECESSORS', pred)
            cfg, frame = (struct.unpack_from('<Q', previous, off)[0] + 1 for off in (56, 112))
            output, canonical = self.receipt(command, checker.fnv(previous[8:48]))
            output = bytearray(output)
            struct.pack_into('<4Q', output, 8, 99, cfg, frame, frame)
            struct.pack_into('<2Q', output, 48, last_proof['source_fnv1a64'], last_proof['source_fnv1a64'])
            output[128:144] = route
            struct.pack_into('<2Q', output, 144, frame - 1, cfg - 1)
            p = copy.deepcopy(last_proof)
            p.update(serial=p['serial'] + 1, opcode=14, config_generation=cfg, frame_generation=frame,
                     lease_generation=frame, result_bytes=192, result_fnv1a64=checker.fnv(output), result_token=0)
            p['before'] = p['after'].copy()
            for key in ('rendered', 'consumed', 'retired'):
                p['after'][key] += 1
            operations.append(dict(op=14, data=canonical, output=bytes(output), origin=native, proof=p))
            records.append('HOST_TEST_TRANSFER_' + str(len(operations) - 1))
            if focus:
                self.focus_rows(emit, cookie, wire, previous, bytes(output), canonical, inline)
                previous = bytearray(previous)
                for offset in (56, 64, 72, 112):
                    struct.pack_into('<Q', previous, offset, struct.unpack_from('<Q', previous, offset)[0] + 1)
                previous, last_proof = bytes(previous), p
                continue
            emit('FUNCTIONAL_STARTUP_CONTROL_PREDECESSORS', pred)
            requested[slot] += 1
            names = ('REQUEST_FREE', 'RECEIVE', 'SENDER_FREE', 'CYCLE') if inline else ('REQUEST_FREE', 'CYCLE', 'RECEIVE', 'SENDER_FREE')
            for ordinal, name in enumerate(names):
                received, freed = (int(ordinal >= names.index(key)) for key in ('RECEIVE', 'SENDER_FREE'))
                busy = int(ordinal < names.index('CYCLE'))
                inflight = int(name != 'REQUEST_FREE' and ordinal < names.index('CYCLE'))
                queued = int(ordinal >= names.index('CYCLE'))
                consumed = int(queued and received and freed and not busy and not inflight)
                current_completed = completed.copy()
                current_completed[slot] += consumed
                f = dict(event=name, pid=77, tid=355 if name == 'RECEIVE' else 90, cycle=cycle, command=hex(command),
                    requests=cycle, completed=cycle - 1 + consumed, command_requests=','.join(map(str, requested)),
                    command_completed=','.join(map(str, current_completed)), mode_applied=1,
                    busy=busy, guard=busy, faults=0, retained=int(name != 'REQUEST_FREE' and not freed), model_instance=99,
                    before_cfg=cfg - 1, cfg=cfg, before_frame=frame - 1, frame=frame, lease=frame,
                    state_rc=0, state_validation_rc=0, bridge_rc=0, validation_rc=0, transport_rc=0,
                    attempted=1, model_complete=1, origin_fnv=f'{checker.fnv(wire):016x}', config40_fnv=f'{checker.fnv(previous[8:48]):016x}',
                    result_fnv=f'{checker.fnv(output):016x}', used=192, required=192, token=0, request='(nil)',
                    reply='(nil)' if freed or name == 'REQUEST_FREE' else '0x500000', req_free_rc=0, alloc_rc=0, send_rc=0,
                    reply_free_rc=0, queued=queued, received=received, freed=freed, send_inflight=inflight,
                    sender_tid=0 if name == 'REQUEST_FREE' else 90, receiver_tid=355 if received else 0,
                    free_tid=90 if freed else 0, AP_consumed=consumed, functional_only=1, source_dependencies_closed=0,
                    original_AP_verified=0, original_CP=0, native_CP=0, EE=0, physical_ASIC_verified=0,
                    physical_CP_RTOS_verified=0, capture_verified=0)
                emit('FUNCTIONAL_STARTUP_CONTROL', f)
                if name == 'REQUEST_FREE':
                    emit('FUNCTIONAL_STARTUP_CONTROL_TICKET_BOUND', dict(pid=77, tid=90, cycle=cycle, pointer='0x500000',
                        destination='0x80020002', source='0x90030001', bytes=12, cookie=hex(cookie),
                        reply=(b'\x01\0' + struct.pack('<HI', command, cookie) + struct.pack('<I', 0xf000)).hex(),
                        before_actual_send=1, physical_ASIC_verified=0, capture_verified=0))
            completed[slot] += 1
            previous = bytearray(previous)
            for offset in (56, 64, 72, 112):
                struct.pack_into('<Q', previous, offset, struct.unpack_from('<Q', previous, offset)[0] + 1)
            previous, last_proof = bytes(previous), p
        operations.append(dict(op=2, data=b'', output=previous, origin=operations[-1]['origin']))
        records.append('HOST_TEST_TRANSFER_' + str(len(operations) - 1))
        return host_test_transport(root, operations, '\n'.join(records) + '\n')

    @staticmethod
    def predecessor():
        # HOST_TEST schema replay of Main; readiness is never injected into the runtime.
        return dict(pid=77, tid=90, accepted=1, initial_mode_requests=1, initial_mode_AP_consumed=1,
            initial_settings_requests=1, initial_settings_AP_consumed=1, all13_AP_consumed=1,
            VDF_AP_consumed=1, still_format_AP_consumed=1, still_format_cycle=2, model_instance=99,
            source_business_equivalent=0, physical_ASIC_verified=0, capture_verified=0)

    @staticmethod
    def receipt(command=0x4014, fingerprint=0xf1278198c173ab21):
        body = checker.STARTUP_CONTROL_MODE_BODY if command == 0x4014 else bytes(16)
        canonical = struct.pack('<2H', command, 16 if command == 0x4014 else 8 if command == 0x403f else 4) + body + bytes(4) + struct.pack('<Q', fingerprint)
        raw = bytearray(StillFormatEvidenceTests.receipt()[:160] + canonical)
        struct.pack_into('<I', raw, 4, 192)
        struct.pack_into('<Q', raw, 40, checker.fnv(canonical))
        struct.pack_into('<I', raw, 96, 9)
        return bytes(raw), canonical

    @staticmethod
    def focus_rows(emit, cookie, wire, state, output, canonical, inline):
        family = 'FUNCTIONAL_CAMERA_FOCUS_MAGNIFICATION_'
        cfg, frame = struct.unpack_from('<2Q', output, 16)
        before_cfg, before_frame = (struct.unpack_from('<Q', state, off)[0] for off in (56, 112))
        common = dict(pid=77, tid=90, native_fnv=hex(checker.fnv(wire)), model_instance=99, capture_verified=0)
        emit('FUNCTIONAL_FOCUS_RESET_MODEL', dict(common, rc=0, state_used=128, state_required=128,
            result_used=192, result_required=192, result_token=0, result_fnv=hex(checker.fnv(output)),
            policy=checker.FOCUS_RESET_POLICY, physical_ASIC_verified=0))
        received = dict(tid=355, sender_tid=90, source='0x90040193', destination='0x80020002', cmd='0x403f',
            token=hex(cookie), bytes=12, status='0xf000', rc=0, magnification_disabled=1, capture_verified=0)
        freed = dict(received, tid=90, receiver_tid=355)
        if inline:
            emit(family + 'APPLIED_REPLY_RECEIVED', received)
            emit(family + 'APPLIED_REPLY_FREE', freed)
        emit(family + 'BACKEND', dict(common, cmd='0x403f', token=hex(cookie), backend_rc=0,
            cfg_before=before_cfg, cfg=cfg, frame_before=before_frame, frame=frame,
            canonical_fnv=hex(checker.fnv(canonical)), model_fnv=hex(checker.fnv(output))))
        emit(family + 'APPLIED', dict(common, source='0x80020002', destination='0x90040193', cmd='0x403f',
            token=hex(cookie), request_bytes=16, reply_bytes=12, status='0xf000', request_free_rc=0,
            policy=checker.FOCUS_RESET_POLICY, cfg=cfg, frame=frame, model_fnv=hex(checker.fnv(output)),
            rgb_bytes=921600, frame_consumed=1, frame_retired=1, magnification_disabled=1))
        if not inline:
            emit(family + 'APPLIED_REPLY_RECEIVED', received)
            emit(family + 'APPLIED_REPLY_FREE', freed)

    def test_focus_reset_whole_rgb_and_original_receiver_sender_free(self):
        for inline in (False, True):
            root = self.root / str(inline)
            root.mkdir()
            args = self.replay(root=root, inline=inline, commands=(0x4014, 0x4057, 0x403f, 0x403f),
                               cookies=(0x8000003c, 0x80000026, 0x80000049, 0x8000004a))
            transport = checker.check_transport(*args)
            self.assertTrue(transport['verified'])
            self.assertTrue(transport['focus_reset']['verified'])
            self.assertEqual(len(transport['focus_reset']['cycles']), 2)
            self.assertEqual(len(transport['startup_control']['cycles']), 2)
            self.assertFalse(transport['focus_reset']['capture_verified'])
            self.assertFalse(transport['focus_reset']['physical_asic_compatibility_verified'])
            self.assertTrue(all(c['sender_tid'] == 90 and c['receiver_tid'] == 355 and c['rgb_bytes'] == 921600
                                for c in transport['focus_reset']['cycles']))

    def test_focus_reset_original_fields_roles_and_no_empty_ACK(self):
        args = self.replay(commands=(0x4014, 0x4057, 0x403f), cookies=(0x8000003c, 0x80000026, 0x80000049))
        transport = checker.check_transport(*args)
        family = 'FUNCTIONAL_CAMERA_FOCUS_MAGNIFICATION_'
        mutations = [('RESET_REQUEST', 'source', '0x80020003'), ('RESET_REQUEST', 'native_fnv', '0'),
            ('RESET_REQUEST', 'request_bytes', '12'), ('RESET_REQUEST', 'policy', 'ACK'),
            ('APPLIED', 'status', '0xf001'), ('APPLIED', 'rgb_bytes', '0'), ('APPLIED', 'frame_retired', '0'),
            ('APPLIED', 'capture_verified', '1'), ('BACKEND', 'backend_rc', '-5'), ('APPLIED', 'model_fnv', '0'),
            ('APPLIED_REPLY_RECEIVED', 'sender_tid', '355'), ('APPLIED_REPLY_FREE', 'tid', '355'),
            ('APPLIED_REPLY_FREE', 'receiver_tid', '90'), ('APPLIED_REPLY_FREE', 'source', '0x90030001')]
        for suffix, key, value in mutations:
            rows = copy.deepcopy(args[2])
            next(r for r in rows if r['tag'] == family + suffix)['fields'][key] = value
            with self.subTest(suffix=suffix, key=key), self.assertRaises(ValueError):
                checker.check_focus_reset(args[0], args[1], rows, transport)
        for suffix in ('BACKEND', 'APPLIED', 'APPLIED_REPLY_RECEIVED', 'APPLIED_REPLY_FREE'):
            rows = [r for r in args[2] if r['tag'] != family + suffix]
            self.assertFalse(checker.check_focus_reset(args[0], args[1], rows, transport)['verified'])
        changed = copy.deepcopy(transport)
        changed['transfers'] = [tx for tx in changed['transfers'] if not (tx['opcode'] == 14 and tx['origin']['command'] == 0x403f)]
        with self.assertRaisesRegex(ValueError, 'ACK without actual Core'):
            checker.check_focus_reset(args[0], args[1], args[2], changed)
        for key, value in (('consumer_kind', 1), ('retired', 0), ('consumer_after_fnv1a64', 0), ('result_bytes', 176)):
            changed = copy.deepcopy(transport)
            next(t for t in changed['transfers'] if t['opcode'] == 14 and t['origin']['command'] == 0x403f)['frame']['proof'][key] = value
            with self.subTest(proof=key), self.assertRaises(ValueError):
                checker.check_focus_reset(args[0], args[1], args[2], changed)
        row = copy.deepcopy(next(r for r in args[2] if r['tag'] == family + 'APPLIED'))
        with self.assertRaises(ValueError):
            checker.check_focus_reset(args[0], args[1], args[2] + [row], transport)
        row['tag'] = family + 'READY'
        with self.assertRaises(ValueError):
            checker.check_focus_reset(args[0], args[1], args[2] + [row], transport)

    def test_focus_off_complete192_rejects_nonzero_consistent_tuple(self):
        raw, canonical = self.receipt(0x403f)
        self.assertEqual(checker.vdf_result(raw, canonical, 77, 14, raw[128:144])['class'], 9)
        for index in range(24):
            incoming, changed = bytearray(canonical), bytearray(raw)
            incoming[index] ^= 1
            changed[160:] = incoming
            struct.pack_into('<Q', changed, 40, checker.fnv(incoming))
            with self.subTest(index=index), self.assertRaises(ValueError):
                checker.vdf_result(changed, incoming, 77, 14, raw[128:144])

    def test_StartupControl_complete192_class9_both_commands(self):
        for command in (0x4014, 0x4057):
            raw, canonical = self.receipt(command)
            value = checker.vdf_result(raw, canonical, 77, 14, raw[128:144])
            self.assertEqual((len(raw), value['class'], value['active_bytes']), (192, 9, 921600))
            self.assertEqual(checker.startup_control_config(canonical), command)
        self.assertEqual(checker.OPS[14], (32,))
        self.assertNotIn(14, checker.VDF_OPERATIONS)

    def test_StartupControl_192_rejects_old_BB_still_and_bad_tuple(self):
        raw, canonical = self.receipt()
        for offset, fmt, wrong in ((4, '<I', 176), (8, '<Q', 78), (32, '<Q', 0), (48, '<Q', 0),
                (56, '<Q', 1), (64, '<Q', 921599), (72, '<I', 320), (80, '<I', 1921),
                (84, '<I', 0), (88, '<I', 0), (92, '<I', 0), (96, '<I', 5), (96, '<I', 8),
                (104, '<I', 0), (108, '<I', 0), (112, '<I', 0), (116, '<I', 0),
                (120, '<I', 1), (124, '<I', 1), (144, '<Q', 13), (152, '<Q', 14)):
            changed = bytearray(raw)
            struct.pack_into(fmt, changed, offset, wrong)
            with self.subTest(offset=offset, wrong=wrong), self.assertRaises(ValueError):
                checker.vdf_result(changed, canonical, 77, 14, raw[128:144])
        for index in range(24):
            changed, incoming = bytearray(raw), bytearray(canonical)
            incoming[index] ^= 1
            changed[160:] = incoming
            struct.pack_into('<Q', changed, 40, checker.fnv(incoming))
            with self.subTest(canonical_byte=index), self.assertRaises(ValueError):
                checker.vdf_result(changed, incoming, 77, 14, raw[128:144])
        for bad in (raw[:160], raw[:176], raw[:-1], raw + b'\0'):
            with self.subTest(bytes=len(bad)), self.assertRaises(ValueError):
                checker.vdf_result(bad, canonical, 77, 14, raw[128:144])


    def test_StartupControl_kind4_full192_never_empty_or_codec(self):
        args = self.replay()
        transport = checker.check_transport(*args)
        for key, wrong in (('consumer_kind', 1), ('consumer_kind', 5), ('result_bytes', 0),
                ('result_bytes', 176), ('result_fnv1a64', checker.fnv(b'')), ('result_token', 1),
                ('encoder_consumed', 1), ('encoded_bytes', 1), ('encoded_fnv1a64', 0),
                ('consumer_before_fnv1a64', 0), ('retired', 0), ('consumer_status', -1)):
            changed = copy.deepcopy(transport)
            next(t for t in changed['transfers'] if t['opcode'] == 14)['frame']['proof'][key] = wrong
            with self.subTest(proof=key, wrong=wrong), self.assertRaises(ValueError):
                checker.check_frames(args[0], changed, require_media=False)
        self.assertTrue(checker.check_frames(args[0], transport, require_media=False)['verified'])

    def test_StartupControl_fingerprint_binds_actual_STATE_not_local_rehash(self):
        args = self.replay()
        transport = checker.check_transport(*args)
        tx = next(t for t in transport['transfers'] if t['opcode'] == 14)
        raw_read, payload_read = checker.transfer_output, checker.payload_read
        actual = raw_read(args[0], tx)
        incoming = payload_read(args[0], tx['request_payload'])
        for fingerprint in (0, 1, checker.fnv(raw_read(args[0], transport['transfers'][0])[8:48]) ^ 1):
            canonical, output = bytearray(incoming), bytearray(actual)
            struct.pack_into('<Q', canonical, 24, fingerprint)
            output[160:] = canonical
            struct.pack_into('<Q', output, 40, checker.fnv(canonical))
            self.assertEqual(checker.vdf_result(output, canonical, 99, 14, output[128:144])['class'], 9)
            def forged_output(run, item):
                return bytes(output) if item['first'] == tx['first'] else raw_read(run, item)
            def forged_input(run, item, *rest):
                return bytes(canonical) if item == tx['request_payload'] else payload_read(run, item, *rest)
            with self.subTest(fingerprint=fingerprint), mock.patch.object(checker, 'transfer_output', side_effect=forged_output), \
                    mock.patch.object(checker, 'payload_read', side_effect=forged_input), self.assertRaisesRegex(ValueError, 'fingerprint'):
                checker.vdf_history(args[0], transport)

    def test_StartupControl_STATE_config40_tamper_rehashed_and_postparams_stay_bound(self):
        args = self.replay()
        transport = checker.check_transport(*args)
        tx = next(t for t in transport['transfers'] if t['opcode'] == 14)
        idx = transport['transfers'].index(tx)
        original, payload = checker.transfer_output, checker.payload_read
        before, after = transport['transfers'][idx - 1], transport['transfers'][idx + 1]
        for state_tx in (before, after):
            state = bytearray(original(args[0], state_tx))
            state[20] ^= 1
            canonical, output = bytearray(payload(args[0], tx['request_payload'])), bytearray(original(args[0], tx))
            if state_tx is before:
                struct.pack_into('<Q', canonical, 24, checker.fnv(state[8:48]))
                output[160:] = canonical
                struct.pack_into('<Q', output, 40, checker.fnv(canonical))
            def forged(run, item):
                return bytes(state) if item['first'] == state_tx['first'] else bytes(output) if item['first'] == tx['first'] else original(run, item)
            def input_forged(run, item, *rest):
                return bytes(canonical) if item == tx['request_payload'] else payload(run, item, *rest)
            with self.subTest(state=state_tx['first']), mock.patch.object(checker, 'transfer_output', side_effect=forged), \
                    mock.patch.object(checker, 'payload_read', side_effect=input_forged), self.assertRaisesRegex(ValueError, 'Config48|fingerprint'):
                checker.vdf_history(args[0], transport)

    def test_StartupControl_route_generations_lease_counters_one_history(self):
        args = self.replay()
        transport = checker.check_transport(*args)
        tx = next(t for t in transport['transfers'] if t['opcode'] == 14)
        original = checker.transfer_output
        actual, canonical = original(args[0], tx), checker.payload_read(args[0], tx['request_payload'])
        for offsets in ((131,), (16, 152), (24, 144), (32,)):
            changed = bytearray(actual)
            for offset in offsets:
                if offset == 131:
                    changed[offset] ^= 1
                else:
                    struct.pack_into('<Q', changed, offset, 1 if offset == 32 else struct.unpack_from('<Q', changed, offset)[0] + 1)
            self.assertEqual(checker.vdf_result(changed, canonical, 99, 14, changed[128:144])['class'], 9)
            def forged(run, item):
                return bytes(changed) if item['first'] == tx['first'] else original(run, item)
            with self.subTest(offsets=offsets), mock.patch.object(checker, 'transfer_output', side_effect=forged), self.assertRaises(ValueError):
                checker.check_frames(args[0], transport, require_media=False)
        for part, key in (('before', 'rendered'), ('after', 'consumed'), ('after', 'jpeg_encoded'), ('after', 'video_encoded')):
            changed = copy.deepcopy(transport)
            next(t for t in changed['transfers'] if t['opcode'] == 14)['frame']['proof'][part][key] += 1
            with self.subTest(counter=part + '.' + key), self.assertRaises(ValueError):
                checker.check_frames(args[0], changed, require_media=False)

    def test_StartupControl_retained_header_nonce_origin_size_and_native_opcode(self):
        args = self.replay()
        for offset, wrong in ((16, 100), (32, 13), (36, 16), (36, 31), (36, 33), (96, 355),
                (100, 0x81cf61c6), (104, 0x92840747), (108, 0x40c8), (112, 12)):
            changed = copy.deepcopy(args)
            event = next(e for e in changed[3] if e['kind'] == 'request' and e['opcode'] == 14)
            raw = bytearray.fromhex(event['raw_header_hex'])
            struct.pack_into('<I', raw, offset, wrong)
            event.update(raw_header_hex=raw.hex(), raw_header_sha256=checker.sha(raw))
            with self.subTest(header=offset), self.assertRaises(ValueError):
                checker.check_transport(*changed)
        transport = checker.check_transport(*args)
        for op in (True, 1, 3, 4, 5, 9, 10, 11, 12, 13, 16, 32, 66):
            changed = copy.deepcopy(transport)
            next(t for t in changed['transfers'] if t['opcode'] == 14)['opcode'] = op
            with self.subTest(relabelled=op), self.assertRaises(ValueError):
                checker.check_startup_control(args[0], args[1], args[2], changed)
        for key in ('producer_tid', 'source', 'destination', 'command', 'bytes', 'fnv1a64'):
            changed = copy.deepcopy(transport)
            next(t for t in changed['transfers'] if t['opcode'] == 14)['origin'][key] += 1 << 64
            with self.subTest(origin=key), self.assertRaises(ValueError):
                checker.check_startup_control(args[0], args[1], args[2], changed)

    def test_StartupControl_policy_real_generator_types_double_container_and_off_None(self):
        producer = checker.source_module(checker.RUNTIME / 'backup_profile.py')
        generated, disabled = producer.functional_camera_profile_fields(checker.PROFILE), producer.functional_camera_profile_fields('')
        for key, value in checker.STARTUP_CONTROL_POLICY.items():
            self.assertTrue(checker.typed_equal(generated['functional_camera_' + key], value))
            self.assertIsNone(disabled['functional_camera_' + key])
        args = self.replay()
        transport = checker.check_transport(*args)
        for location in ('top', 'backup_transport'):
            for key, value in checker.STARTUP_CONTROL_POLICY.items():
                for wrong in (None, True if type(value) is not bool else 0, [] if type(value) is not list else tuple(value)):
                    manifest = copy.deepcopy(args[1])
                    target = manifest if location == 'top' else manifest['backup_transport']
                    target['functional_camera_' + key] = wrong
                    with self.subTest(location=location, key=key, wrong=wrong), self.assertRaises(ValueError):
                        checker.check_startup_control(args[0], manifest, args[2], transport)
            manifest = copy.deepcopy(args[1])
            target = manifest if location == 'top' else manifest['backup_transport']
            for key in checker.STARTUP_CONTROL_POLICY:
                target.pop('functional_camera_' + key)
            with self.subTest(all_missing=location), self.assertRaises(ValueError):
                checker.check_startup_control(args[0], manifest, args[2], transport)
        manifest = copy.deepcopy(args[1])
        for target in (manifest, manifest['backup_transport']):
            for key in checker.STARTUP_CONTROL_POLICY:
                target.pop('functional_camera_' + key)
        with self.assertRaises(ValueError):
            checker.check_startup_control(args[0], manifest, args[2], transport)
        historical = copy.deepcopy(transport)
        historical['transfers'] = [t for t in historical['transfers'] if t['origin']['command'] not in (0x4014, 0x4057)]
        records = [r for r in args[2] if not r['tag'].startswith('FUNCTIONAL_STARTUP_CONTROL')]
        self.assertEqual(checker.check_startup_control(args[0], manifest, records, historical)['status'], 'not_observed')
        self.assertFalse(disabled['functional_camera_capture_verified'])

    def test_StartupControl_whole_capture_requires_JPEG_MP4_even_when_configuration_verified(self):
        args = self.replay()
        transport = checker.check_transport(*args)
        self.assertTrue(checker.check_frames(args[0], transport, require_media=False)['verified'])
        with self.assertRaises(checker.MissingEvidence):
            checker.check_frames(args[0], transport)
        result = dict(evidence=dict(transport=transport, startup_control=transport['startup_control']), missing=[],
                      products={kind: dict(capture_verified=False) for kind in ('JPEG', 'MP4')})
        verdict = checker.finish_verdict(result, dict(evidence_class='HOST_TEST'))
        self.assertEqual(verdict['verdict'], 'SOURCE/TRACE_MISSING')
        self.assertFalse(verdict['capture_verified'])
        self.assertFalse(transport['startup_control']['physical_asic_compatibility_verified'])

    def test_StartupControl_same_cookie_low_cookie_reused_address_and_cross_tid_inline(self):
        for inline in (False, True):
            root = self.root / str(inline)
            root.mkdir()
            args = self.replay(root=root, inline=inline, cookies=(0xffffffff, 7, 0xffffffff, 7))
            transport = checker.check_transport(*args)
            stage = transport['startup_control']
            self.assertEqual([c['command'] for c in stage['cycles']], [0x4014, 0x4057, 0x4014, 0x4057])
            self.assertEqual([c['cookie'] for c in stage['cycles']], [0xffffffff, 7, 0xffffffff, 7])
            self.assertTrue(all(c['receiver_tid'] == 355 and c['sender_tid'] == 90 and c['AP_consumed'] for c in stage['cycles']))
            self.assertEqual(stage['initial_diagnostic'], {'0x4014': 'not_observed', '0x4057': 'not_observed'})
            self.assertTrue(checker.check_frames(args[0], transport, require_media=False)['verified'])
            self.assertEqual(stage['missing'], [])
            self.assertEqual(stage['status'], 'complete')
            self.assertTrue(stage['verified'])
            self.assertTrue(stage['startup_control_applied'])
            self.assertTrue(stage['mode_applied'])
            self.assertTrue(stage['settings_checkpoint_loaded'])
            self.assertFalse(stage['capture_verified'])
            self.assertFalse(stage['physical_asic_compatibility_verified'])

    def test_StartupControl_tickets_cookie_full12_late_missing_and_stale_cycle(self):
        args = self.replay()
        transport = checker.check_transport(*args)
        for key, wrong in (('pid', '78'), ('tid', '355'), ('pointer', '0'), ('cycle', '2'), ('cookie', '0x3c'),
                ('cookie', '0x18000003c'), ('destination', '0x90030001'), ('source', '0x80020002'),
                ('bytes', '16'), ('before_actual_send', '0'), ('physical_ASIC_verified', '1'),
                ('capture_verified', '1'), ('reply', '010014403c00008001f00000')):
            rows = copy.deepcopy(args[2])
            next(r['fields'] for r in rows if r['tag'] == 'FUNCTIONAL_STARTUP_CONTROL_TICKET_BOUND')[key] = wrong
            with self.subTest(ticket=key, wrong=wrong), self.assertRaises(ValueError):
                checker.check_startup_control(args[0], args[1], rows, transport)
        rows = copy.deepcopy(args[2])
        ticket = next(r for r in rows if r['tag'] == 'FUNCTIONAL_STARTUP_CONTROL_TICKET_BOUND')
        ticket['line'] = next(r['line'] for r in rows if r['tag'] == 'FUNCTIONAL_STARTUP_CONTROL' and r['fields']['event'] == 'CYCLE') + 1
        with self.assertRaisesRegex(ValueError, 'order differs'):
            checker.check_startup_control(args[0], args[1], rows, transport)
        rows = [r for r in args[2] if r['tag'] != 'FUNCTIONAL_STARTUP_CONTROL_TICKET_BOUND']
        self.assertFalse(checker.check_startup_control(args[0], args[1], rows, transport)['verified'])
        for offset in (0, 2, 4, 8):
            rows, changed = copy.deepcopy(args[2]), copy.deepcopy(transport)
            audit = next(r for r in rows if r['tag'] == 'NATIVE_CP_BACKGROUND_INPUT_AUDIT_BYTES' and int(r['fields']['sequence']) == 201)
            wire = bytearray.fromhex(audit['fields']['raw'])
            old_fnv = checker.fnv(wire)
            wire[offset] ^= 1
            audit['fields']['raw'] = wire.hex()
            for tx in changed['transfers']:
                if tx['origin']['fnv1a64'] == old_fnv:
                    tx['origin']['fnv1a64'] = checker.fnv(wire)
            for row in rows:
                if row['tag'] == 'FUNCTIONAL_STARTUP_CONTROL' and row['fields']['cycle'] == '1':
                    row['fields']['origin_fnv'] = f'{checker.fnv(wire):016x}'
            with self.subTest(original_wire_byte=offset), self.assertRaises(ValueError):
                checker.check_startup_control(args[0], args[1], rows, changed)

    def test_StartupControl_request_free_ACK_alloc_sender_free_scope_and_command_counters(self):
        args = self.replay(inline=True)
        transport = checker.check_transport(*args)
        for event, key, wrong in (('REQUEST_FREE', 'reply', '0x500000'), ('REQUEST_FREE', 'request', '0x500000'),
                ('REQUEST_FREE', 'req_free_rc', '-1'), ('REQUEST_FREE', 'sender_tid', '90'),
                ('RECEIVE', 'received', '0'), ('RECEIVE', 'tid', '90'), ('RECEIVE', 'receiver_tid', '0'),
                ('SENDER_FREE', 'free_tid', '355'), ('SENDER_FREE', 'tid', '355'), ('SENDER_FREE', 'freed', '0'),
                ('SENDER_FREE', 'reply_free_rc', '-1'), ('SENDER_FREE', 'AP_consumed', '1'),
                ('CYCLE', 'send_inflight', '1'), ('CYCLE', 'send_rc', '-1'), ('CYCLE', 'guard', '1'),
                ('CYCLE', 'completed', '0'), ('CYCLE', 'command_requests', '1,1'), ('CYCLE', 'command_completed', '0,0'),
                ('CYCLE', 'mode_applied', '0'), ('CYCLE', 'config40_fnv', '0000000000000000'),
                ('CYCLE', 'used', '176'), ('CYCLE', 'required', '176'), ('CYCLE', 'token', '1')):
            rows = copy.deepcopy(args[2])
            next(r['fields'] for r in rows if r['tag'] == 'FUNCTIONAL_STARTUP_CONTROL' and r['fields']['event'] == event)[key] = wrong
            with self.subTest(event=event, key=key), self.assertRaises(ValueError):
                checker.check_startup_control(args[0], args[1], rows, transport)
        for key in ('capture_verified', 'physical_ASIC_verified', 'physical_CP_RTOS_verified', 'original_AP_verified',
                    'original_CP', 'native_CP', 'EE', 'source_dependencies_closed'):
            rows = copy.deepcopy(args[2])
            next(r['fields'] for r in rows if r['tag'] == 'FUNCTIONAL_STARTUP_CONTROL')[key] = '1'
            with self.subTest(scope=key), self.assertRaises(ValueError):
                checker.check_startup_control(args[0], args[1], rows, transport)
        rows = copy.deepcopy(args[2])
        free = next(r for r in rows if r['tag'] == 'FUNCTIONAL_STARTUP_CONTROL' and r['fields']['event'] == 'REQUEST_FREE')
        free['line'] = next(t['line'] for t in transport['transfers'] if t['opcode'] == 14) - 1
        with self.assertRaisesRegex(ValueError, 'order differs'):
            checker.check_startup_control(args[0], args[1], rows, transport)
        for event in ('REQUEST_FREE', 'RECEIVE', 'SENDER_FREE', 'CYCLE'):
            rows = [r for r in args[2] if not (r['tag'] == 'FUNCTIONAL_STARTUP_CONTROL' and r['fields']['cycle'] == '1' and r['fields']['event'] == event)]
            with self.subTest(missing=event):
                self.assertFalse(checker.check_startup_control(args[0], args[1], rows, transport)['verified'])

    def test_StartupControl_predecessor_fixture_matches_actual_Main_schema(self):
        source = (checker.RUNTIME / 'menu-observe.c').read_text()
        producer = source.split('static int functional_startup_control_predecessors_ready(void) {', 1)[1].split('\n}', 1)[0]
        schema = re.search(r'"(pid=%d tid=%ld accepted=%u initial_mode_requests=[^"]+)"', producer).group(1)
        self.assertEqual(list(self.predecessor()), [field.split('=', 1)[0] for field in schema.split()])
        self.assertIn('record("FUNCTIONAL_STARTUP_CONTROL_PREDECESSORS ",text);return ready;', producer)
        self.assertEqual(self.predecessor()['still_format_cycle'], 2)

    def test_StartupControl_framed_predecessors_require_actual_model_and_lifecycle(self):
        args = self.replay()
        transport = checker.check_transport(*args)
        kernel = ZD4_STARTUP_PREDECESSOR_RECORD[ZD4_STARTUP_PREDECESSOR_RECORD.index(b'[ '):-2]
        predecessors = [r for r in args[2] if r['tag'] == 'FUNCTIONAL_STARTUP_CONTROL_PREDECESSORS']
        for target in predecessors[:3]:
            fields = dict(self.predecessor())
            for changes in ({}, dict(accepted=0), dict(model_instance=100), dict(still_format_cycle=1)):
                current = dict(fields, **changes)
                payload = ('OBS ' + target['tag'] + ' ' + ' '.join(f'{k}={v}' for k, v in current.items())).encode()
                framed, = checker.parse_console(payload + kernel + b'\r\n')
                self.assertIn('kernel_diagnostic', framed)
                self.assertNotIn('verified', framed)
                framed['line'] = target['line']
                rows = [framed if row is target else row for row in args[2]]
                with self.subTest(line=target['line'], changes=changes):
                    if changes:
                        with self.assertRaises(ValueError):
                            checker.check_startup_control(args[0], args[1], rows, transport)
                    else:
                        stage = checker.check_startup_control(args[0], args[1], rows, transport)
                        self.assertTrue(stage['verified'])
                        self.assertFalse(stage['capture_verified'])
                        self.assertFalse(stage['physical_asic_compatibility_verified'])
        target = predecessors[0]
        payload = ('OBS ' + target['tag'] + ' ' + ' '.join(f'{k}={v}' for k, v in self.predecessor().items())).encode()
        framed, = checker.parse_console(payload + kernel + b'\r\n')
        framed['line'] = target['line']
        missing = [framed if row is target else row for row in args[2] if not (
            row['tag'] == 'FUNCTIONAL_STILL_FORMAT' and row['fields']['cycle'] == '2' and
            row['fields']['event'] == 'SENDER_FREE')]
        self.assertFalse(checker.check_startup_control(args[0], args[1], missing, transport)['verified'])

    def test_CP_configuration_unknown_or_incomplete_framing_remains_MissingEvidence(self):
        args = self.replay()
        transport = checker.check_transport(*args)
        kernel = ZD4_STARTUP_PREDECESSOR_RECORD[ZD4_STARTUP_PREDECESSOR_RECORD.index(b'[ '):-2]
        for tag, check in (('FUNCTIONAL_STILL_FORMAT', checker.check_still_format),
                           ('FUNCTIONAL_STARTUP_CONTROL_PREDECESSORS', checker.check_startup_control)):
            target = next(row for row in args[2] if row['tag'] == tag)
            payload = ('OBS ' + tag + ' ' + ' '.join(f'{k}={v}' for k, v in target['fields'].items())).encode()
            for malformed in (payload + b' unknown trailer\n', payload + kernel + b' extra\n',
                              payload.rsplit(b' ', 1)[0] + kernel + b'\n'):
                diagnostic, = checker.parse_console(malformed)
                self.assertIn('diagnostic', diagnostic)
                self.assertNotIn('kernel_diagnostic', diagnostic)
                diagnostic['line'] = target['line']
                rows = [diagnostic if row is target else row for row in args[2]]
                original = copy.deepcopy(diagnostic)
                with self.subTest(tag=tag, malformed=malformed), self.assertRaisesRegex(
                        checker.MissingEvidence, tag + r' line [0-9]+: missing complete original formatter'):
                    check(args[0], args[1], rows, transport)
                self.assertEqual(diagnostic, original)

    def test_StartupControl_predecessor_every_field_at_all_three_checks(self):
        args = self.replay()
        transport = checker.check_transport(*args)
        self.assertTrue(transport['startup_control']['verified'])
        for window in range(3):
            for key, value in self.predecessor().items():
                wrong = {'pid': 78, 'tid': 355, 'model_instance': 100, 'still_format_cycle': 1}.get(key, 1 - value)
                rows = copy.deepcopy(args[2])
                pred = [r for r in rows if r['tag'] == 'FUNCTIONAL_STARTUP_CONTROL_PREDECESSORS'][window]
                pred['fields'][key] = str(wrong)
                with self.subTest(window=window, field=key, wrong=wrong), self.assertRaises(ValueError):
                    checker.check_startup_control(args[0], args[1], rows, transport)
                rows = copy.deepcopy(args[2])
                pred = [r for r in rows if r['tag'] == 'FUNCTIONAL_STARTUP_CONTROL_PREDECESSORS'][window]
                del pred['fields'][key]
                with self.subTest(window=window, missing=key):
                    stage = checker.check_startup_control(args[0], args[1], rows, transport)
                    self.assertEqual((stage['status'], stage['verified'], stage['startup_control_applied']),
                                     ('incomplete', False, False))
        for key in ('pid', 'tid', 'model_instance', 'still_format_cycle'):
            for wrong in ('-1', 'true', '01', '18446744073709551616'):
                rows = copy.deepcopy(args[2])
                next(r['fields'] for r in rows if r['tag'] == 'FUNCTIONAL_STARTUP_CONTROL_PREDECESSORS')[key] = wrong
                with self.subTest(field=key, malformed=wrong), self.assertRaises(ValueError):
                    checker.check_startup_control(args[0], args[1], rows, transport)
        rows = copy.deepcopy(args[2])
        next(r['fields'] for r in rows if r['tag'] == 'FUNCTIONAL_STARTUP_CONTROL_PREDECESSORS')['host_ready'] = '1'
        with self.assertRaises(ValueError):
            checker.check_startup_control(args[0], args[1], rows, transport)

    def test_StartupControl_predecessors_missing_late_boundaries_and_duplicates_per_cycle(self):
        args = self.replay()
        transport = checker.check_transport(*args)
        transfers = [t for t in transport['transfers'] if t['opcode'] == 14]
        predecessors = [r for r in args[2] if r['tag'] == 'FUNCTIONAL_STARTUP_CONTROL_PREDECESSORS']
        for cycle, tx in enumerate(transfers, 1):
            before = transport['transfers'][transport['transfers'].index(tx) - 1]
            free = next(r for r in args[2] if r['tag'] == 'FUNCTIONAL_STARTUP_CONTROL' and
                        r['fields']['cycle'] == str(cycle) and r['fields']['event'] == 'REQUEST_FREE')
            audit = next(r for r in args[2] if r['tag'] == 'NATIVE_CP_BACKGROUND_INPUT_AUDIT' and
                         r['fields']['sequence'] == str(200 + cycle))
            for window in range(3):
                index = (cycle - 1) * 3 + window
                for moved in (None, audit['line'], before['line'], tx['line'], free['line'], free['line'] + 1):
                    rows = copy.deepcopy(args[2])
                    pred = [r for r in rows if r['tag'] == 'FUNCTIONAL_STARTUP_CONTROL_PREDECESSORS'][index]
                    if moved is None:
                        rows.remove(pred)
                    else:
                        pred['line'] = moved
                    with self.subTest(cycle=cycle, window=window, moved=moved):
                        stage = checker.check_startup_control(args[0], args[1], rows, transport)
                        self.assertEqual((stage['status'], stage['verified'], stage['AP_consumed']),
                                         ('incomplete', False, False))
                rows = copy.deepcopy(args[2]) + [copy.deepcopy(predecessors[index])]
                with self.subTest(cycle=cycle, duplicate=window), self.assertRaisesRegex(ValueError, 'duplicate predecessor'):
                    checker.check_startup_control(args[0], args[1], rows, transport)
        rows = [r for r in args[2] if r['tag'] != 'FUNCTIONAL_STARTUP_CONTROL_PREDECESSORS']
        self.assertFalse(checker.check_startup_control(args[0], args[1], rows, transport)['verified'])
        rows = copy.deepcopy(args[2]) + [copy.deepcopy(predecessors[0])]
        rows[-1]['line'] = max(r['line'] for r in rows) + 1
        stage = checker.check_startup_control(args[0], args[1], rows, transport)
        self.assertFalse(stage['verified'])
        self.assertTrue(any('outside' in m for m in stage['missing']))

    def test_StartupControl_predecessor_current_format_cycle_requires_raw_complete_lifecycle(self):
        args = self.replay()
        transport = checker.check_transport(*args)
        self.assertTrue(transport['still_format']['verified'])
        for cycle in ('0', '1', '3', '18446744073709551615'):
            rows = copy.deepcopy(args[2])
            for row in rows:
                if row['tag'] == 'FUNCTIONAL_STARTUP_CONTROL_PREDECESSORS':
                    row['fields']['still_format_cycle'] = cycle
            with self.subTest(format_cycle=cycle), self.assertRaises(ValueError):
                checker.check_startup_control(args[0], args[1], rows, transport)
        for event in ('REQUEST_FREE', 'RECEIVE', 'SENDER_FREE', 'CYCLE'):
            rows = [r for r in args[2] if not (r['tag'] == 'FUNCTIONAL_STILL_FORMAT' and
                    r['fields']['cycle'] == '2' and r['fields']['event'] == event)]
            with self.subTest(missing_current_format=event):
                stage = checker.check_startup_control(args[0], args[1], rows, transport)
                self.assertFalse(stage['verified'])
                self.assertFalse(stage['startup_control_applied'])
        for key, wrong in (('pid', '78'), ('model_instance', '100'), ('faults', '1'), ('AP_consumed', '0'),
                           ('reply_free_rc', '-1'), ('free_tid', '355')):
            rows = copy.deepcopy(args[2])
            current = next(r for r in rows if r['tag'] == 'FUNCTIONAL_STILL_FORMAT' and
                           r['fields']['cycle'] == '2' and r['fields']['event'] == 'SENDER_FREE')
            current['fields'][key] = wrong
            with self.subTest(format_field=key), self.assertRaises(ValueError):
                checker.check_startup_control(args[0], args[1], rows, transport)
        for tag in ('FUNCTIONAL_STILL_FORMAT', 'FUNCTIONAL_STILL_FORMAT_TICKET_BOUND',
                    'FUNCTIONAL_STILL_FORMAT_PREDECESSORS'):
            rows = [r for r in args[2] if r['tag'] != tag]
            with self.subTest(missing_format=tag):
                self.assertFalse(checker.check_startup_control(args[0], args[1], rows, transport)['verified'])
        rows = copy.deepcopy(args[2])
        first = next(t for t in transport['transfers'] if t['opcode'] == 14)
        before = transport['transfers'][transport['transfers'].index(first) - 1]
        free = next(r for r in rows if r['tag'] == 'FUNCTIONAL_STILL_FORMAT' and
                    r['fields']['cycle'] == '2' and r['fields']['event'] == 'SENDER_FREE')
        free['line'] = before['line']
        self.assertTrue(checker.check_still_format(args[0], args[1], rows, transport)['verified'])
        with self.assertRaisesRegex(ValueError, 'not complete before predecessor'):
            checker.check_startup_control(args[0], args[1], rows, transport)

    def test_StartupControl_initial_diagnostics_bind_own_wire_cookie_free_and_never_apply(self):
        records = []
        for command, cookie in ((0x4014, 0x80000026), (0x4057, 0)):
            wire = b'\x05\0' + struct.pack('<HI', command, cookie) + (checker.STARTUP_CONTROL_MODE_BODY if command == 0x4014 else bytes(4))
            digest = 2166136261
            for byte in wire:
                digest = ((digest ^ byte) * 16777619) & 0xffffffff
            ack = b'\x01\0' + struct.pack('<HI', command, cookie) + struct.pack('<I', 0xf000)
            f = dict(pid=77, opcode=hex(command), sender_tid=384, waiter_tid=384, requests=1, busy=0, guard=0, faults=0,
                source='0x80020002', request_destination='0x90030001', destination='0x80020002', bytes=len(wire), request=wire.hex(),
                cookie=hex(cookie), wire_fnv1a32=hex(digest), source_byte1_known=int(command == 0x4057), reply=ack.hex(), freed_reply=ack.hex(),
                reply_free_destination='0x80020002', reply_free_source='0x90030001', reply_free_bytes=12, allocate_rc=0, send_rc=0,
                request_free_rc=0, reply_free_rc=0, queued=1, request_freed=1, reply_freed=1, clean_completion=1, ap_consumed=1,
                retained_request='(nil)', live_reply='(nil)', retained_cleanup='(nil)', diagnostic_only=1, virtual_padding=1,
                business_applied=0, source_dependencies_closed=0, configured=0, published=0, generation=0, native_cp=0, EE=0, frame=0, capture=0)
            records.append('NATIVE_CP_STARTUP_DIAGNOSTIC_REPLY_FREE ' + ' '.join(f'{k}={v}' for k, v in f.items()))
        rows = checker.parse_console(('\n'.join(records) + '\n').encode())
        stage = checker.check_startup_control_diagnostics(rows, [], 77)
        self.assertTrue(all(v['status'] == 'transport_only' and not v['format_applied'] and not v['mode_applied'] for v in stage.values()))
        for key, wrong in (('request', '00' * 24), ('cookie', '0x26'), ('waiter_tid', '355'), ('reply_free_rc', '-1'),
                ('freed_reply', '00' * 12), ('source', '0x90030001'), ('clean_completion', '0'), ('ap_consumed', '0'),
                ('business_applied', '1'), ('source_dependencies_closed', '1'), ('capture', '1'), ('live_reply', '0x500000')):
            changed = copy.deepcopy(rows)
            changed[0]['fields'][key] = wrong
            with self.subTest(diagnostic=key), self.assertRaises(ValueError):
                checker.check_startup_control_diagnostics(changed, [], 77)
        with self.assertRaises(ValueError):
            checker.check_startup_control_diagnostics(rows + rows, [], 77)

    def test_StartupControl_actual_retained_Core192_and_four_independent_RGB_readbacks(self):
        path = checker.NATIVE.parents[3] / ('analysis/scratch/functional-startup-control-core/logs/02-core-both/'
            'functional-startup-control-core-strict0/success.stdout.bin')
        if not path.is_file():
            self.skipTest('private retained Core stdout unavailable; no model is rebuilt')
        raw = path.read_bytes()
        self.assertEqual(checker.sha(raw), '34b0ecc8ca6d4367d767cf40af7a97f2d92744b57b65747a9cfd819f700762d4')
        stream, blobs = io.BytesIO(raw), {}
        while line := stream.readline():
            tag, name, count = line.split()
            self.assertEqual(tag, b'BLOB')
            self.assertNotIn(name, blobs)
            size = int(count)
            self.assertLessEqual(size, 2 * 1024**2)
            blobs[name] = stream.read(size)
            self.assertEqual(len(blobs[name]), size)
        previous = blobs[b'BEFORE']
        for name in (b'MODE', b'SETTINGS', b'MODE_REPEAT', b'SETTINGS_REPEAT'):
            source, sink = blobs[name + b'_SOURCE'], blobs[name + b'_SINK']
            canonical, output, state = blobs[name + b'_INPUT'], blobs[name], blobs[name + b'_STATE']
            self.assertEqual(source, sink)
            self.assertEqual(len(source), 921600)
            self.assertGreater(len(set(zip(source[::3], source[1::3], source[2::3]))), 1)
            self.assertEqual(struct.unpack_from('<Q', canonical, 24)[0], checker.fnv(previous[8:48]))
            value = checker.vdf_result(output, canonical, 77, 14, blobs[b'ROUTE'])
            self.assertEqual(value['source_fnv'], checker.fnv(source))
            self.assertEqual(value['sink_fnv'], checker.fnv(sink))
            self.assertEqual(previous[8:48], state[8:48])
            self.assertEqual(previous[80:112], state[80:112])
            self.assertEqual((value['before_config_generation'], value['before_frame_generation']),
                             (struct.unpack_from('<Q', previous, 56)[0], struct.unpack_from('<Q', previous, 112)[0]))
            self.assertGreater(value['lease_generation'], struct.unpack_from('<Q', previous, 64)[0])
            previous = state
        self.assertEqual(blobs[b'CHECKPOINT'], blobs[b'BEFORE'][8:48])


class StillFormatEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='HOST_TEST_still_format_evidence_')
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    @staticmethod
    def receipt():
        canonical = checker.STILL_FORMAT_CANONICAL
        raw = bytearray(176)
        route = bytes.fromhex('010505a9020000006700000000000000')
        struct.pack_into('<2I8Q14I', raw, 0, 1, 176, 77, 16, 15, 15, checker.fnv(canonical),
                         0x4b356052ebdcbb25, 0x4b356052ebdcbb25, 921600,
                         640, 480, 1920, 0x90590819, 1, 1, 8, 1, 1, 1, 1, 1, 0, 0)
        raw[128:144] = route
        struct.pack_into('<2Q', raw, 144, 14, 15)
        raw[160:] = canonical
        return bytes(raw)

    def replay(self, *, inline=False, cookies=(0x8000003b, 5), tails=(b'\0\0', b'\xa5\xfe'), root=None):
        """Pure HOST_TEST replay of the current owner, Main ticket and CP audit producers."""
        root = root or self.root
        base = root / 'base'
        base.mkdir()
        args = host_test_capture(base, (True, ('bit_width',)), configuration_only=True)
        requests = [e for e in args[3] if e['kind'] == 'request']
        outputs = {e['sequence']: e for e in args[3] if e['kind'] == 'core_result'}
        proofs = {e['sequence']: e['proof'] for e in args[3] if e['kind'] == 'model_frame'}
        operations = [dict(op=e['opcode'], data=checker.payload_read(args[0], e['request_payload']),
            output=checker.payload_read(args[0], outputs[e['sequence']]['output_payload']), origin=e['origin'],
            **(dict(proof=proofs[e['sequence']]) if e['sequence'] in proofs else {})) for e in requests]
        records, index = [], 0
        for text in (args[0] / 'console.log').read_text().splitlines():
            if text.startswith('OBS FUNCTIONAL_CAMERA_TRANSFER '):
                text = 'HOST_TEST_TRANSFER_' + str(index)
                index += 1
            records.append(text)
        previous = operations[-1]['output']
        last_proof = copy.deepcopy(list(proofs.values())[-1])
        route = next(o['output'][128:144] for o in reversed(operations) if o['op'] == 12)
        def emit(tag, fields):
            records.append(tag + ' ' + ' '.join(f'{k}={v}' for k, v in fields.items()))
        for cycle, (cookie, tail) in enumerate(zip(cookies, tails), 1):
            wire = b'\x05' + (b'\xa5' if cycle == 2 else b'\0') + b'\x2d\x40' + struct.pack('<I', cookie) + checker.STILL_FORMAT_CANONICAL[:14] + tail
            native = dict(producer_tid=90, source=0x80020002, destination=0x90030001,
                          command=0x402d, bytes=24, fnv1a64=checker.fnv(wire))
            emit('NATIVE_CP_BACKGROUND_INPUT_AUDIT', dict(pid=77, tid=90, sequence=100 + cycle, entry='async',
                pointer='0x400000', destination='0x90030001', bytes=24, source='0x80020002', size_known=1,
                source_known=1, bytes_complete=1, complete=1, producer_return=hex(0x7f25c3f000 + 0x3535a68),
                consumed=0, state_verified=0, capture_verified=0))
            emit('NATIVE_CP_BACKGROUND_INPUT_AUDIT_BYTES', dict(pid=77, tid=90, sequence=100 + cycle, offset=0, bytes=24, raw=wire.hex()))
            records.extend(JFZ_VDF_RESOURCE_OBS.replace('FUNCTIONAL_VDF_PATH_', 'FUNCTIONAL_STILL_FORMAT_')
                           .replace('pid=258', 'pid=77').replace('tid=381', 'tid=90').splitlines())
            pred = dict(pid=77, tid=90, accepted=1, initial_diagnostic_requests=1,
                        initial_diagnostic_AP_consumed=1, VDF_AP_consumed=1, model_instance=99,
                        source_business_equivalent=0, physical_ASIC_verified=0, capture_verified=0)
            emit('FUNCTIONAL_STILL_FORMAT_PREDECESSORS', pred)
            operations.append(dict(op=2, data=b'', output=previous, origin=native))
            records.append('HOST_TEST_TRANSFER_' + str(len(operations) - 1))
            emit('FUNCTIONAL_STILL_FORMAT_PREDECESSORS', pred)
            cfg, frame = (struct.unpack_from('<Q', previous, offset)[0] + 1 for offset in (56, 112))
            output = bytearray(self.receipt())
            struct.pack_into('<4Q', output, 8, 99, cfg, frame, frame)
            struct.pack_into('<2Q', output, 48, last_proof['source_fnv1a64'], last_proof['source_fnv1a64'])
            output[128:144] = route
            struct.pack_into('<2Q', output, 144, frame - 1, cfg - 1)
            p = copy.deepcopy(last_proof)
            p.update(serial=p['serial'] + 1, opcode=13, config_generation=cfg, frame_generation=frame,
                     lease_generation=frame, result_bytes=176, result_fnv1a64=checker.fnv(output), result_token=0)
            p['before'] = p['after'].copy()
            for key in ('rendered', 'consumed', 'retired'):
                p['after'][key] += 1
            operations.append(dict(op=13, data=checker.STILL_FORMAT_CANONICAL, output=bytes(output), origin=native, proof=p))
            records.append('HOST_TEST_TRANSFER_' + str(len(operations) - 1))
            emit('FUNCTIONAL_STILL_FORMAT_PREDECESSORS', pred)
            names = ('REQUEST_FREE', 'RECEIVE', 'SENDER_FREE', 'CYCLE') if inline else ('REQUEST_FREE', 'CYCLE', 'RECEIVE', 'SENDER_FREE')
            for ordinal, name in enumerate(names):
                received, freed = (int(ordinal >= names.index(key)) for key in ('RECEIVE', 'SENDER_FREE'))
                busy = int(ordinal < names.index('CYCLE'))
                inflight = int(name != 'REQUEST_FREE' and ordinal < names.index('CYCLE'))
                queued = int(ordinal >= names.index('CYCLE'))
                consumed = int(queued and received and freed and not busy and not inflight)
                f = dict(event=name, pid=77, tid=355 if name == 'RECEIVE' else 90, cycle=cycle,
                    requests=cycle, completed=cycle - 1 + consumed, busy=busy, guard=busy, faults=0,
                    retained=int(name != 'REQUEST_FREE' and not freed), model_instance=99,
                    before_cfg=cfg - 1, cfg=cfg, before_frame=frame - 1, frame=frame, lease=frame,
                    state_rc=0, state_validation_rc=0, bridge_rc=0, validation_rc=0, transport_rc=0,
                    attempted=1, model_complete=1, origin_fnv=f'{checker.fnv(wire):016x}', result_fnv=f'{checker.fnv(output):016x}',
                    used=176, required=176, token=0, request='(nil)',
                    reply='(nil)' if freed or name == 'REQUEST_FREE' else '0x500000',
                    req_free_rc=0, alloc_rc=0, send_rc=0, reply_free_rc=0, queued=queued, received=received,
                    freed=freed, send_inflight=inflight, sender_tid=0 if name == 'REQUEST_FREE' else 90,
                    receiver_tid=355 if received else 0, free_tid=90 if freed else 0, AP_consumed=consumed,
                    functional_only=1, original_AP_verified=0, original_CP=0, physical_ASIC_verified=0,
                    physical_CP_RTOS_verified=0, capture_verified=0)
                emit('FUNCTIONAL_STILL_FORMAT', f)
                if name == 'REQUEST_FREE':
                    emit('FUNCTIONAL_STILL_FORMAT_TICKET_BOUND', dict(pid=77, tid=90, cycle=cycle, pointer='0x500000',
                        destination='0x80020002', source='0x90030001', bytes=12, cookie=hex(cookie),
                        reply=(b'\x01\0\x2d\x40' + struct.pack('<2I', cookie, 0xf000)).hex(),
                        before_actual_send=1, physical_ASIC_verified=0, capture_verified=0))
            previous = bytearray(previous)
            for offset in (56, 64, 72, 112):
                struct.pack_into('<Q', previous, offset, struct.unpack_from('<Q', previous, offset)[0] + 1)
            previous, last_proof = bytes(previous), p
        operations.append(dict(op=2, data=b'', output=previous, origin=operations[-1]['origin']))
        records.append('HOST_TEST_TRANSFER_' + str(len(operations) - 1))
        return host_test_transport(root, operations, '\n'.join(records) + '\n')

    def test_StillFormat_minimal_typed176_class8_positive(self):
        raw = self.receipt()
        parsed = checker.vdf_result(raw, checker.STILL_FORMAT_CANONICAL, 77, 13, raw[128:144])
        self.assertEqual((len(raw), parsed['class'], parsed['active_bytes']), (176, 8, 921600))
        self.assertEqual((parsed['config_generation'], parsed['frame_generation'], parsed['lease_generation']),
                         (16, 15, 15))
        self.assertEqual(checker.OPS[13], (16,))
        self.assertNotIn(13, checker.VDF_OPERATIONS)

    def test_StillFormat_typed176_rejects_old_ABI_class_tail_and_local_rehash(self):
        raw = self.receipt()
        for offset, fmt, wrong in ((4, '<I', 168), (8, '<Q', 78), (32, '<Q', 0), (48, '<Q', 0),
                (56, '<Q', 1), (64, '<Q', 921599), (72, '<I', 320), (80, '<I', 1921),
                (84, '<I', 0), (88, '<I', 0), (92, '<I', 0), (96, '<I', 7), (96, '<I', 1),
                (104, '<I', 0), (108, '<I', 0), (112, '<I', 0), (116, '<I', 0),
                (120, '<I', 1), (124, '<I', 1), (144, '<Q', 13), (152, '<Q', 14)):
            changed = bytearray(raw)
            struct.pack_into(fmt, changed, offset, wrong)
            with self.subTest(offset=offset, wrong=wrong), self.assertRaises(ValueError):
                checker.vdf_result(changed, checker.STILL_FORMAT_CANONICAL, 77, 13, raw[128:144])
        for index in range(16):
            changed, canonical = bytearray(raw), bytearray(checker.STILL_FORMAT_CANONICAL)
            canonical[index] ^= 1
            changed[160:] = canonical
            struct.pack_into('<Q', changed, 40, checker.fnv(canonical))
            with self.subTest(canonical_byte=index), self.assertRaises(ValueError):
                checker.vdf_result(changed, canonical, 77, 13, raw[128:144])
            changed = bytearray(raw)
            changed[160 + index] ^= 1
            with self.subTest(readback_byte=index), self.assertRaises(ValueError):
                checker.vdf_result(changed, checker.STILL_FORMAT_CANONICAL, 77, 13, raw[128:144])
        for changed in (raw[:160], raw[:168], raw[:-1], raw + b'\0'):
            with self.subTest(size=len(changed)), self.assertRaises(ValueError):
                checker.vdf_result(changed, checker.STILL_FORMAT_CANONICAL, 77, 13, raw[128:144])

    def test_StillFormat_two_cycles_full176_opaque_tail_same_address_and_cross_thread(self):
        for inline in (False, True):
            root = self.root / str(inline)
            root.mkdir()
            args = self.replay(root=root, inline=inline)
            transport = checker.check_transport(*args)
            stage = transport['still_format']
            self.assertTrue(transport['verified'], stage)
            self.assertEqual((stage['status'], stage['verified'], stage['format_applied'], stage['AP_consumed']),
                             ('complete', True, True, True))
            self.assertEqual([c['cookie'] for c in stage['cycles']], [0x8000003b, 5])
            self.assertTrue(all(c['receiver_tid'] == 355 and c['sender_tid'] == 90 for c in stage['cycles']))
            self.assertTrue(stage['cycles'][1]['original_wire'].endswith('a5fe'))
            self.assertEqual(stage['initial_diagnostic'], 'not_observed')
            self.assertTrue(checker.check_frames(args[0], transport, require_media=False)['verified'])
            for tx in (tx for tx in transport['transfers'] if tx['opcode'] == 13):
                raw = checker.transfer_output(args[0], tx)
                self.assertEqual((tx['frame']['proof']['consumer_kind'], tx['frame']['proof']['result_bytes'],
                                  tx['frame']['proof']['result_fnv1a64'], tx['token']), (4, 176, checker.fnv(raw), 0))
            self.assertFalse(stage['capture_verified'])
            with self.assertRaises(checker.MissingEvidence):
                checker.check_frames(args[0], transport)

    def test_StillFormat_actual_retained_Core176_and_independent_active_RGB(self):
        path = checker.NATIVE.parents[3] / ('analysis/scratch/functional-still-format-core/core-verified/'
            'functional-still-format-core-strict0/still-format-success.stdout.bin')
        if not path.is_file():
            self.skipTest('private retained Core stdout is unavailable; no model is rebuilt')
        raw = path.read_bytes()
        self.assertEqual(checker.sha(raw), 'bbf4b34ffde38c9b5804b1a8e4adb63ccd41ec3f2031b48a0c619f93828b06a7')
        stream, blobs = io.BytesIO(raw), {}
        while line := stream.readline():
            tag, name, count = line.split()
            self.assertEqual(tag, b'BLOB')
            self.assertNotIn(name, blobs)
            size = int(count)
            self.assertLessEqual(size, 2 * 1024**2)
            blobs[name] = stream.read(size)
            self.assertEqual(len(blobs[name]), size)
        self.assertEqual(blobs[b'INPUT'], checker.STILL_FORMAT_CANONICAL)
        previous = blobs[b'BEFORE']
        for receipt, state, suffix in ((b'RECEIPT', b'STATE', b''), (b'REPEAT', b'STATE_REPEAT', b'_REPEAT')):
            source, sink = blobs[b'SOURCE' + suffix], blobs[b'SINK' + suffix]
            self.assertEqual(source, sink)
            self.assertEqual(len(source), 921600)
            self.assertGreater(len(set(zip(source[::3], source[1::3], source[2::3]))), 1)
            value = checker.vdf_result(blobs[receipt], blobs[b'INPUT'], 77, 13, blobs[b'ROUTE'])
            self.assertEqual(value['source_fnv'], checker.fnv(source))
            self.assertEqual(value['sink_fnv'], checker.fnv(sink))
            self.assertEqual(value['config_generation'], struct.unpack_from('<Q', previous, 56)[0] + 1)
            self.assertEqual(value['frame_generation'], struct.unpack_from('<Q', previous, 112)[0] + 1)
            self.assertEqual(blobs[state][8:48], previous[8:48])
            self.assertEqual(blobs[state][80:104], previous[80:104])
            previous = blobs[state]
        self.assertEqual(blobs[b'RECEIPT'], self.receipt())

    def test_StillFormat_original_wire_and_full_u32_origin_cookie_are_bound(self):
        args = self.replay()
        transport = checker.check_transport(*args)
        first = next(tx for tx in transport['transfers'] if tx['opcode'] == 13)
        wire = bytes.fromhex(transport['still_format']['cycles'][0]['original_wire'])
        first_m = bytes.fromhex('05002d402600008002000101010101000101010101000000')
        for offset in ('oldM', 'short', 'long', 0, 2, 3, 4, 7, 8, 9, 10, 15, 21):
            changed, rows = copy.deepcopy(transport), copy.deepcopy(args[2])
            raw = bytearray(first_m if offset == 'oldM' else wire[:-1] if offset == 'short' else
                            wire + b'\0' if offset == 'long' else wire)
            if type(offset) is int:
                raw[offset] ^= 1
            for row in rows:
                if row['tag'] == 'NATIVE_CP_BACKGROUND_INPUT_AUDIT_BYTES' and row['fields']['sequence'] == '101':
                    row['fields']['raw'] = raw.hex()
                if row['tag'] == 'FUNCTIONAL_STILL_FORMAT' and row['fields']['cycle'] == '1':
                    row['fields']['origin_fnv'] = f'{checker.fnv(raw):016x}'
            for tx in changed['transfers']:
                if tx['origin'] == first['origin']:
                    tx['origin']['fnv1a64'] = checker.fnv(raw)
            with self.subTest(wire_byte=offset), self.assertRaises(ValueError):
                checker.check_still_format(args[0], args[1], rows, changed)
        for key, wrong in (('source', 0x180020002), ('source', True), ('source', 0x81cf61c6),
                ('destination', 0x92840747), ('destination', 0x190030001), ('command', 0x402e),
                ('bytes', 22), ('producer_tid', 383), ('fnv1a64', 1 << 64)):
            changed = copy.deepcopy(transport)
            next(tx for tx in changed['transfers'] if tx['opcode'] == 13)['origin'][key] = wrong
            with self.subTest(origin=key, wrong=wrong), self.assertRaises(ValueError):
                checker.check_still_format(args[0], args[1], args[2], changed)
        for key, wrong in (('producer_return', '0x7f4f174a68'), ('pointer', '0x0'), ('source', '0x81cf61c6'),
                           ('pid', '78'), ('entry', 'sync'), ('complete', '0'), ('capture_verified', '1')):
            rows = copy.deepcopy(args[2])
            next(r['fields'] for r in rows if r['tag'] == 'NATIVE_CP_BACKGROUND_INPUT_AUDIT' and
                 r['fields']['sequence'] == '101')[key] = wrong
            with self.subTest(original_audit=key), self.assertRaises(ValueError):
                checker.check_still_format(args[0], args[1], rows, transport)
        diagnostic_fields = dict(pid=77, sender_tid=90, waiter_tid=90, requests=1, source='0x80020002',
            destination='0x90030001', bytes=24, request=first_m.hex(), cookie='0x80000026',
            reply='01002d402600008000f00000', freed_reply='01002d402600008000f00000',
            reply_free_destination='0x80020002', reply_free_source='0x90030001', reply_free_bytes=12,
            busy=0, guard=0, faults=0, allocate_rc=0, send_rc=0, request_free_rc=0, reply_free_rc=0,
            queued=1, request_freed=1, reply_freed=1, clean_completion=1, ap_consumed=1,
            retained_request='(nil)', live_reply='(nil)', retained_cleanup='(nil)', diagnostic_only=1,
            no_publication=1, source_business_applied=0, generation=0, native_verified=0, native_cp=0,
            CP_history_verified=0, EE=0, frame=0, capture=0)
        text = 'NATIVE_CP_CAPTURE_FORMAT_DIAGNOSTIC_REPLY_FREE ' + ' '.join(f'{k}={v}' for k, v in diagnostic_fields.items()) + '\n'
        diagnostic, = checker.parse_console(text.encode())
        diagnostic['line'] = 0
        observed = checker.check_still_format(args[0], args[1], [diagnostic] + args[2], transport)
        self.assertTrue(observed['verified'])
        self.assertEqual(observed['initial_diagnostic']['status'], 'transport_only')
        self.assertFalse(observed['initial_diagnostic']['format_applied'])
        for key in ('clean_completion', 'ap_consumed', 'requests', 'source_business_applied', 'capture'):
            altered = copy.deepcopy(diagnostic)
            altered['fields'][key] = '1' if key in ('source_business_applied', 'capture') else '0'
            with self.subTest(initial_diagnostic=key), self.assertRaises(ValueError):
                checker.check_still_format(args[0], args[1], [altered] + args[2], transport)
        for key, wrong in (('cookie', '0x18000003b'), ('reply', '01002d403b00008000000000'),
                ('reply', '01012d403b00008000f00000'), ('reply', '01002d403b00000000f00000'),
                ('reply', '01002d403b00008000f0000000'), ('source', '0x92840747'), ('destination', '0x81cf61c6')):
            rows = copy.deepcopy(args[2])
            next(r['fields'] for r in rows if r['tag'] == 'FUNCTIONAL_STILL_FORMAT_TICKET_BOUND')[key] = wrong
            with self.subTest(ticket=key, wrong=wrong), self.assertRaises(ValueError):
                checker.check_still_format(args[0], args[1], rows, transport)

    def test_StillFormat_full176_kind4_is_never_empty_or_codec_proof(self):
        args = self.replay()
        transport = checker.check_transport(*args)
        for key, wrong in (('consumer_kind', 1), ('consumer_kind', 5), ('opcode', 12), ('result_bytes', 0),
                ('result_bytes', 168), ('result_fnv1a64', checker.fnv(b'')), ('result_token', 1),
                ('encoder_consumed', 1), ('encoded_bytes', 176), ('encoded_fnv1a64', 0),
                ('consumer_before_fnv1a64', 0), ('consumer_after_fnv1a64', 0), ('retired', 0),
                ('consumer_returned', 0), ('lease_generation', 1), ('active_bytes', 0), ('serial', 1),
                ('owner_pid', 178), ('model_instance', 100), ('render_observed', True)):
            changed = copy.deepcopy(transport)
            next(tx['frame']['proof'] for tx in changed['transfers'] if tx['opcode'] == 13)[key] = wrong
            with self.subTest(proof=key), self.assertRaises(ValueError):
                checker.check_still_format(args[0], args[1], args[2], changed)
        for counter in ('rendered', 'consumed', 'retired', 'jpeg_encoded', 'video_encoded'):
            changed = copy.deepcopy(transport)
            next(tx['frame']['proof'] for tx in changed['transfers'] if tx['opcode'] == 13)['after'][counter] += 1
            with self.subTest(counter=counter), self.assertRaises(ValueError):
                checker.check_frames(args[0], changed, require_media=False)

    def test_StillFormat_owner_full_result_origin_and_generations_cannot_be_locally_rehashed(self):
        args = self.replay()
        transport = checker.check_transport(*args)
        for key, wrong in (('origin_fnv', '0000000000000000'), ('result_fnv', '0000000000000000'),
                ('used', '168'), ('required', '168'), ('model_instance', '100'), ('cfg', '99'), ('before_cfg', '99'),
                ('frame', '99'), ('before_frame', '99'), ('lease', '1'), ('model_complete', '0'), ('attempted', '0')):
            rows = copy.deepcopy(args[2])
            next(r['fields'] for r in rows if r['tag'] == 'FUNCTIONAL_STILL_FORMAT' and r['fields']['event'] == 'REQUEST_FREE')[key] = wrong
            with self.subTest(field=key), self.assertRaises(ValueError):
                checker.check_still_format(args[0], args[1], rows, transport)
        tx = next(tx for tx in transport['transfers'] if tx['opcode'] == 13)
        output = bytearray(checker.transfer_output(args[0], tx))
        output[-1] = 1
        rows = copy.deepcopy(args[2])
        for row in rows:
            if row['tag'] == 'FUNCTIONAL_STILL_FORMAT' and row['fields']['cycle'] == '1':
                row['fields']['result_fnv'] = f'{checker.fnv(output):016x}'
        with self.assertRaises(ValueError):
            checker.check_still_format(args[0], args[1], rows, transport)
        reference = tx['output_payloads'][0]
        (args[0] / reference['path']).write_bytes(output)
        with self.assertRaises(ValueError):
            checker.check_transport(*args)

    def test_StillFormat_ticket_is_per_actual_send_and_cannot_borrow_old_cycle(self):
        args = self.replay()
        transport = checker.check_transport(*args)
        original = [r for r in args[2] if r['tag'] == 'FUNCTIONAL_STILL_FORMAT_TICKET_BOUND']
        for key, wrong in (('cycle', '1'), ('cookie', '0x8000003b'), ('pointer', '0x600000'), ('pid', '78'),
                           ('tid', '355'), ('before_actual_send', '0')):
            rows = copy.deepcopy(args[2])
            [r for r in rows if r['tag'] == 'FUNCTIONAL_STILL_FORMAT_TICKET_BOUND'][1]['fields'][key] = wrong
            with self.subTest(field=key), self.assertRaises(ValueError):
                checker.check_still_format(args[0], args[1], rows, transport)
        rows = copy.deepcopy(args[2])
        ticket = next(r for r in rows if r['tag'] == 'FUNCTIONAL_STILL_FORMAT_TICKET_BOUND')
        ticket['line'] = next(r['line'] for r in rows if r['tag'] == 'FUNCTIONAL_STILL_FORMAT' and
                              r['fields']['cycle'] == '1' and r['fields']['event'] == 'CYCLE') + 1
        with self.assertRaisesRegex(ValueError, 'order differs'):
            checker.check_still_format(args[0], args[1], rows, transport)
        rows = [r for r in args[2] if r is not original[1]]
        result = checker.check_still_format(args[0], args[1], rows, transport)
        self.assertEqual((result['status'], result['verified'], result['format_applied']), ('incomplete', False, False))
        root = self.root / 'same-cookie'
        root.mkdir()
        same = checker.check_transport(*self.replay(root=root, cookies=(7, 7)))['still_format']
        self.assertTrue(same['verified'])
        self.assertEqual([c['cookie'] for c in same['cycles']], [7, 7])
        root = self.root / 'cookie-extremes'
        root.mkdir()
        extremes = checker.check_transport(*self.replay(root=root, cookies=(0xffffffff, 0)))['still_format']
        self.assertTrue(extremes['verified'])
        self.assertEqual([c['cookie'] for c in extremes['cycles']], [0xffffffff, 0])

    def test_StillFormat_request_free_allocation_original_receiver_and_sender_free_order(self):
        args = self.replay(inline=True)
        transport = checker.check_transport(*args)
        for event, key, wrong in (('REQUEST_FREE', 'reply', '0x500000'), ('REQUEST_FREE', 'request', '0x400000'),
                ('REQUEST_FREE', 'req_free_rc', '-1'), ('REQUEST_FREE', 'sender_tid', '90'),
                ('RECEIVE', 'received', '0'), ('RECEIVE', 'receiver_tid', '0'), ('RECEIVE', 'tid', '90'),
                ('SENDER_FREE', 'free_tid', '355'), ('SENDER_FREE', 'tid', '355'), ('SENDER_FREE', 'freed', '0'),
                ('SENDER_FREE', 'reply_free_rc', '-1'), ('SENDER_FREE', 'AP_consumed', '1'),
                ('CYCLE', 'send_inflight', '1'), ('CYCLE', 'send_rc', '-1'), ('CYCLE', 'faults', '1')):
            rows = copy.deepcopy(args[2])
            next(r['fields'] for r in rows if r['tag'] == 'FUNCTIONAL_STILL_FORMAT' and r['fields']['event'] == event)[key] = wrong
            with self.subTest(event=event, key=key), self.assertRaises(ValueError):
                checker.check_still_format(args[0], args[1], rows, transport)
        rows = copy.deepcopy(args[2])
        request_free = next(r for r in rows if r['tag'] == 'FUNCTIONAL_STILL_FORMAT' and r['fields']['event'] == 'REQUEST_FREE')
        request_free['line'] = next(tx['line'] for tx in transport['transfers'] if tx['opcode'] == 13) - 1
        with self.assertRaisesRegex(ValueError, 'order differs'):
            checker.check_still_format(args[0], args[1], rows, transport)

    def test_StillFormat_missing_real_receipts_remain_incomplete_and_failed_Core_cannot_ACK(self):
        args = self.replay()
        transport = checker.check_transport(*args)
        for event in ('REQUEST_FREE', 'RECEIVE', 'SENDER_FREE', 'CYCLE'):
            rows = [r for r in args[2] if not (r['tag'] == 'FUNCTIONAL_STILL_FORMAT' and
                    r['fields']['cycle'] == '1' and r['fields']['event'] == event)]
            stage = checker.check_still_format(args[0], args[1], rows, transport)
            with self.subTest(missing=event):
                self.assertEqual((stage['status'], stage['verified'], stage['AP_consumed']), ('incomplete', False, False))
        for tag in ('NATIVE_CP_BACKGROUND_INPUT_AUDIT_BYTES', 'FUNCTIONAL_STILL_FORMAT_PREDECESSORS',
                    'FUNCTIONAL_STILL_FORMAT_RESOURCE_DEPENDENCIES'):
            rows = [r for r in args[2] if r['tag'] != tag]
            with self.subTest(missing=tag):
                self.assertFalse(checker.check_still_format(args[0], args[1], rows, transport)['verified'])
        changed = copy.deepcopy(transport)
        changed['transfers'] = [tx for tx in changed['transfers'] if tx['opcode'] != 13 and
                                not (tx['opcode'] == 2 and tx['origin']['command'] == 0x402d)]
        refused = checker.parse_console(b'FUNCTIONAL_STILL_FORMAT event=REFUSED cycle=1\n')
        self.assertEqual(checker.check_still_format(args[0], args[1], refused, changed)['status'], 'incomplete')
        with self.assertRaises(ValueError):
            checker.check_still_format(args[0], args[1], refused + [next(r for r in args[2] if
                r['tag'] == 'FUNCTIONAL_STILL_FORMAT_TICKET_BOUND')], changed)

    def test_StillFormat_STATE_route_Config48_generations_and_fresh_lease_use_one_history(self):
        args = self.replay()
        transport = checker.check_transport(*args)
        tx = next(tx for tx in transport['transfers'] if tx['opcode'] == 13)
        original = checker.transfer_output
        raw = original(args[0], tx)
        for offsets in ((131,), (16, 152), (24, 144), (32,)):
            changed = bytearray(raw)
            for offset in offsets:
                if offset == 131:
                    changed[offset] ^= 1
                else:
                    struct.pack_into('<Q', changed, offset, 1 if offset == 32 else struct.unpack_from('<Q', changed, offset)[0] + 1)
            self.assertEqual(checker.vdf_result(changed, checker.STILL_FORMAT_CANONICAL, 99, 13, changed[128:144])['class'], 8)
            def forged(run, item):
                return bytes(changed) if item['first'] == tx['first'] else original(run, item)
            with self.subTest(offsets=offsets), mock.patch.object(checker, 'transfer_output', side_effect=forged):
                with self.assertRaises(ValueError):
                    checker.check_still_format(args[0], args[1], args[2], transport)
        state_tx = transport['transfers'][transport['transfers'].index(tx) + 1]
        state = bytearray(original(args[0], state_tx))
        state[20] ^= 1
        def forged_state(run, item):
            return bytes(state) if item['first'] == state_tx['first'] else original(run, item)
        with mock.patch.object(checker, 'transfer_output', side_effect=forged_state), self.assertRaisesRegex(ValueError, 'Config48'):
            checker.vdf_history(args[0], transport)

    def test_StillFormat_retained_mailbox_nonce_origin_and_OP13_are_exact(self):
        args = self.replay()
        for offset, wrong in ((16, 100), (32, 12), (36, 8), (36, 14), (36, 17), (96, 383),
                              (100, 0x81cf61c6), (104, 0x92840747), (108, 0x402e), (112, 22)):
            changed = copy.deepcopy(args)
            event = next(e for e in changed[3] if e['kind'] == 'request' and e['opcode'] == 13)
            raw = bytearray.fromhex(event['raw_header_hex'])
            struct.pack_into('<I', raw, offset, wrong)
            event.update(raw_header_hex=raw.hex(), raw_header_sha256=checker.sha(raw))
            with self.subTest(header=offset), self.assertRaises(ValueError):
                checker.check_transport(*changed)
        for location in ('origin', 'request_payload'):
            changed = copy.deepcopy(args)
            event = next(e for e in changed[3] if e['kind'] == 'request' and e['opcode'] == 13)
            target = event['origin'] if location == 'origin' else event['request_payload']['origin']
            target['source'] += 1 << 32
            with self.subTest(source=location), self.assertRaises(ValueError):
                checker.check_transport(*changed)
        transport = checker.check_transport(*args)
        for op in (True, 1, 3, 4, 5, 9, 10, 11, 12, 16, 32, 66):
            changed = copy.deepcopy(transport)
            next(tx for tx in changed['transfers'] if tx['opcode'] == 13)['opcode'] = op
            with self.subTest(relabelled=op), self.assertRaises(ValueError):
                checker.check_still_format(args[0], args[1], args[2], changed)

    def test_StillFormat_scope_claims_and_whole_capture_remain_false(self):
        args = self.replay()
        transport = checker.check_transport(*args)
        for key in ('capture_verified', 'physical_ASIC_verified', 'physical_CP_RTOS_verified', 'original_AP_verified', 'original_CP'):
            rows = copy.deepcopy(args[2])
            next(r['fields'] for r in rows if r['tag'] == 'FUNCTIONAL_STILL_FORMAT')[key] = '1'
            with self.subTest(scope=key), self.assertRaises(ValueError):
                checker.check_still_format(args[0], args[1], rows, transport)
        for key in ('initial_diagnostic_requests', 'initial_diagnostic_AP_consumed', 'VDF_AP_consumed', 'model_instance'):
            rows = copy.deepcopy(args[2])
            next(r['fields'] for r in rows if r['tag'] == 'FUNCTIONAL_STILL_FORMAT_PREDECESSORS')[key] = '0'
            with self.subTest(predecessor=key), self.assertRaises(ValueError):
                checker.check_still_format(args[0], args[1], rows, transport)
        result = dict(evidence=dict(transport=transport, still_format=transport['still_format']), missing=[],
                      products={kind: dict(capture_verified=False) for kind in ('JPEG', 'MP4')})
        checked = checker.finish_verdict(result, dict(evidence_class='HOST_TEST'))
        self.assertFalse(checked['capture_verified'])
        self.assertTrue(all(p['capture_verified'] is False for p in checked['products'].values()))
        self.assertFalse(transport['still_format']['physical_asic_compatibility_verified'])
        self.assertFalse(transport['still_format']['original_CP_executed'])

    def test_StillFormat_policy_matches_real_generator_both_copies_and_off_None(self):
        producer = checker.source_module(checker.RUNTIME / 'backup_profile.py')
        fields = producer.functional_camera_profile_fields(checker.PROFILE)
        disabled = producer.functional_camera_profile_fields('')
        profile = dict(fields, backup_transport=copy.deepcopy(fields), directory_sd_profile='directory-vvfat-256gb-v1',
                       rm_file_image_bytes=checker.writeback.CARD_BYTES)
        self.assertTrue(checker.check_profile(profile)['verified'])
        for key, expected in checker.STILL_FORMAT_POLICY.items():
            full = 'functional_camera_' + key
            self.assertTrue(checker.typed_equal(fields[full], expected))
            self.assertIsNone(disabled[full])
            wrong_values = (None, 0, True) if expected is False else (None, False, [True], 'physical-ready')
            for location in ('top', 'backup_transport'):
                for wrong in ('missing', *wrong_values):
                    changed = copy.deepcopy(profile)
                    target = changed if location == 'top' else changed[location]
                    if wrong == 'missing':
                        del target[full]
                    else:
                        target[full] = wrong
                    with self.subTest(key=key, location=location, wrong=wrong), self.assertRaises(ValueError):
                        checker.check_profile(changed)
        for target in (profile, profile['backup_transport']):
            for key in checker.STILL_FORMAT_POLICY:
                del target['functional_camera_' + key]
        self.assertTrue(checker.check_profile(profile)['verified'])
        profile['functional_camera_still_format_request_bytes'] = 24
        with self.assertRaises(ValueError):
            checker.check_profile(profile)
        self.assertIs(disabled['functional_camera_capture_verified'], False)
        self.assertIs(disabled['functional_camera_physical_ASIC_compatibility_verified'], False)
        args = self.replay()
        for location in ('top', 'backup_transport'):
            for key in checker.STILL_FORMAT_POLICY:
                changed = copy.deepcopy(args[1])
                target = changed if location == 'top' else changed[location]
                del target['functional_camera_' + key]
                with self.subTest(required_OP13_policy=key, location=location), self.assertRaises(ValueError):
                    checker.check_transport(args[0], changed, *args[2:])
        changed = copy.deepcopy(args[1])
        for target in (changed, changed['backup_transport']):
            for key in checker.STILL_FORMAT_POLICY:
                del target['functional_camera_' + key]
        with self.assertRaises(ValueError):
            checker.check_transport(args[0], changed, *args[2:])
        changed['functional_camera_still_format_physical_selector_mapping_verified'] = True
        with self.assertRaises(ValueError):
            checker.check_transport(args[0], changed, *args[2:])


class CPParameterBankEvidenceTests(unittest.TestCase):
    """Synthetic OP20 parser fixtures; no Core, transport, frame or capture is run."""

    @classmethod
    def setUpClass(cls):
        source = (checker.RUNTIME / 'device-models/cp-parameter-batch.c').read_bytes()
        if checker.sha(source) != '8f627e77d94d63434e4be7de3d398a1e3865946c44c7244f2b2553a483409a2e':
            raise AssertionError('fixed190 fixture source changed')
        cls.slots = [tuple(int(word, 16) for word in item) for item in re.findall(
            rb'\{(0x[0-9a-f]+),(0x[0-9a-f]+),(0x[0-9a-f]+)\}', source)]
        if len(cls.slots) != 190:
            raise AssertionError('fixed190 fixture table is incomplete')

    def setUp(self):
        self.instance = 99
        self.prior = control_state(fps=24, generation=7)
        self.packet = self.original_packet()
        self.raw = self.result(self.packet)

    def original_packet(self, fps=30, cookie=0x80000027, tail=0xfe):
        packet = bytearray((index * 37 + 0xa5) & 0xff for index in range(2564))
        struct.pack_into('<HHI', packet, 0, 5, 0x4063, cookie)
        end = 8
        for command, offset, size in self.slots:
            self.assertEqual(offset, end)
            self.assertGreaterEqual(size, 8)
            packet[offset] = 5
            struct.pack_into('<H', packet, offset + 2, command)
            end += size
        self.assertEqual(end, len(packet))
        self.assertEqual(next(slot for slot in self.slots if slot[0] == 0x4151), (0x4151, 0x864, 0x18))
        struct.pack_into('<I', packet, 0x86c, fps)
        packet[-1] = tail
        return bytes(packet)

    def result(self, packet, prior=None, bank_generation=1):
        """Pack declared evidence bytes only; this does not execute the hardware model."""
        prior = self.prior if prior is None else prior
        fps = struct.unpack_from('<I', packet, 0x86c)[0]
        before = struct.unpack_from('<Q', prior, 56)[0]
        state = bytearray(prior)
        struct.pack_into('<I', state, 16, fps)
        struct.pack_into('<Q', state, 56, (before + 1) & (2**64 - 1))
        raw = bytearray(2756)
        struct.pack_into('<2I5Q4I', raw, 0, 1, 2756, self.instance, bank_generation,
                         before, (before + 1) & (2**64 - 1), checker.fnv(packet), fps, 190, 2564, 0)
        raw[64:192], raw[192:] = state, packet
        return bytes(raw)

    @staticmethod
    def profile():
        producer = checker.source_module(checker.RUNTIME / 'backup_profile.py')
        fields = producer.functional_camera_profile_fields(checker.PROFILE)
        return dict(fields, backup_transport=copy.deepcopy(fields),
                    directory_sd_profile='directory-vvfat-256gb-v1',
                    rm_file_image_bytes=checker.writeback.CARD_BYTES)

    def test_full190_fps30_60_opaque_cookie_and_last_byte_are_preserved(self):
        for fps in (30, 60):
            for cookie in (0, 0x80000027, 0xffffffff):
                for tail in (0, 0xfe):
                    with self.subTest(fps=fps, cookie=cookie, tail=tail):
                        packet = self.original_packet(fps, cookie, tail)
                        raw = self.result(packet)
                        value = checker.cp_parameter_bank_result(raw, packet, self.instance, self.prior)
                        self.assertEqual(value, dict(model_instance=99, bank_generation=1,
                            before_config_generation=7, config_generation=8, input_fnv=checker.fnv(packet),
                            fps=fps, slots=190, raw_bytes=2564, reserved=0, frame_generation=1))
                        self.assertEqual(raw[192:], packet)
                        self.assertEqual(struct.unpack_from('<I', raw, 196)[0], cookie)
                        self.assertEqual(raw[-1], tail)
                        self.assertEqual(raw[72:80], self.prior[8:16])
                        self.assertEqual(raw[84:112], self.prior[20:48])
                        self.assertEqual(raw[176:184], self.prior[112:120])

    def test_result_version_size_truncation_and_trailing_bytes_are_rejected(self):
        for version, size in ((0, 2756), (2, 2756), (1, 0), (1, 128), (1, 2755), (1, 2757)):
            raw = bytearray(self.raw)
            struct.pack_into('<2I', raw, 0, version, size)
            with self.subTest(version=version, size=size), self.assertRaises(ValueError):
                checker.cp_parameter_bank_result(bytes(raw), self.packet, self.instance, self.prior)
        for raw in (b'', self.raw[:63], self.raw[:191], self.raw[:-1], self.raw + b'\0'):
            with self.subTest(result_bytes=len(raw)), self.assertRaises(ValueError):
                checker.cp_parameter_bank_result(raw, self.packet, self.instance, self.prior)

    def test_original_packet_outer_type_command_and_exact_length_are_required(self):
        for offset in (0, 2, 3):
            packet = bytearray(self.packet)
            packet[offset] ^= 0x80
            with self.subTest(outer_header_byte=offset), self.assertRaises(ValueError):
                checker.cp_parameter_bank_result(self.result(packet), bytes(packet), self.instance, self.prior)
        for packet in (b'', self.packet[:7], self.packet[:-1], self.packet + b'\0'):
            with self.subTest(packet_bytes=len(packet)), self.assertRaises(ValueError):
                checker.cp_parameter_bank_result(self.raw, packet, self.instance, self.prior)

    def test_each_of190_slot_type_and_command_bytes_reject_even_when_rehashed(self):
        for command, offset, _ in self.slots:
            for relative in (0, 2, 3):
                packet = bytearray(self.packet)
                packet[offset + relative] ^= 0x80
                with self.subTest(command=hex(command), header_byte=relative), self.assertRaises(ValueError):
                    checker.cp_parameter_bank_result(self.result(packet), bytes(packet), self.instance, self.prior)

    def test_each_slot_must_remain_at_its_fixed_original_offset(self):
        for command, offset, _ in self.slots:
            packet = bytearray(self.packet)
            packet[offset:offset + 5] = b'\0' + self.packet[offset:offset + 4]
            with self.subTest(shifted_command=hex(command), offset=offset), self.assertRaises(ValueError):
                checker.cp_parameter_bank_result(self.result(packet), bytes(packet), self.instance, self.prior)

    def test_independent_readback_binds_every_bank_byte_including_opaque_bytes(self):
        for offset in range(2564):
            raw = bytearray(self.raw)
            raw[192 + offset] ^= 1
            with self.subTest(readback_byte=offset), self.assertRaises(ValueError):
                checker.cp_parameter_bank_result(bytes(raw), self.packet, self.instance, self.prior)

    def test_input_digest_nonce_bank_generation_counts_fps_and_reserved_are_bound(self):
        for fmt, offset, values in (
                ('Q', 8, (0, 100)), ('Q', 16, (0,)),
                ('Q', 40, (0, checker.fnv(self.packet) ^ 1)),
                ('I', 48, (0, 29, 60)), ('I', 52, (0, 189, 191)),
                ('I', 56, (0, 2563, 2565)), ('I', 60, (1, 0xffffffff))):
            for value in values:
                raw = bytearray(self.raw)
                struct.pack_into('<' + fmt, raw, offset, value)
                with self.subTest(offset=offset, value=value), self.assertRaises(ValueError):
                    checker.cp_parameter_bank_result(bytes(raw), self.packet, self.instance, self.prior)
        packet = self.original_packet(fps=0)
        with self.subTest(fps='zero-in-both-copies'), self.assertRaises(ValueError):
            checker.cp_parameter_bank_result(self.result(packet), packet, self.instance, self.prior)
        for instance in (0, 100):
            with self.subTest(expected_instance=instance), self.assertRaises(ValueError):
                checker.cp_parameter_bank_result(self.raw, self.packet, instance, self.prior)

    def test_configuration_generation_requires_latest_state_exact_increment_and_no_wrap(self):
        for offset, values in ((24, (0, 6, 8, 2**64 - 1)), (32, (0, 7, 9, 2**64 - 1))):
            for value in values:
                raw = bytearray(self.raw)
                struct.pack_into('<Q', raw, offset, value)
                with self.subTest(offset=offset, generation=value), self.assertRaises(ValueError):
                    checker.cp_parameter_bank_result(bytes(raw), self.packet, self.instance, self.prior)
        for generation in (0, 2**64 - 1):
            prior = bytearray(self.prior)
            struct.pack_into('<Q', prior, 56, generation)
            with self.subTest(before_generation=generation), self.assertRaises(ValueError):
                checker.cp_parameter_bank_result(self.result(self.packet, prior), self.packet,
                                                 self.instance, bytes(prior))

    def test_prior_State128_version_instance_length_and_generation_are_mandatory(self):
        for prior in (b'', self.prior[:47], self.prior[:-1], self.prior + b'\0'):
            with self.subTest(prior_bytes=len(prior)), self.assertRaises(ValueError):
                checker.cp_parameter_bank_result(self.raw, self.packet, self.instance, prior)
        for fmt, offset, values in (('I', 0, (0, 2)), ('Q', 48, (0, 100)),
                                    ('Q', 56, (0, 6, 8, 2**64 - 1))):
            for value in values:
                prior = bytearray(self.prior)
                struct.pack_into('<' + fmt, prior, offset, value)
                with self.subTest(prior_offset=offset, value=value), self.assertRaises(ValueError):
                    checker.cp_parameter_bank_result(self.raw, self.packet, self.instance, bytes(prior))

    def test_readback_State128_version_instance_config_fps_and_frame_are_bound(self):
        for start, size in ((0, 4), (16, 4), (48, 8), (56, 8), (112, 8)):
            for relative in range(size):
                raw = bytearray(self.raw)
                raw[64 + start + relative] ^= 1
                with self.subTest(state_byte=start + relative), self.assertRaises(ValueError):
                    checker.cp_parameter_bank_result(bytes(raw), self.packet, self.instance, self.prior)

    def test_config40_can_change_only_the_declared_fps_projection(self):
        for offset in (*range(8, 16), *range(20, 48)):
            raw = bytearray(self.raw)
            raw[64 + offset] ^= 1
            with self.subTest(unrelated_config_byte=offset), self.assertRaises(ValueError):
                checker.cp_parameter_bank_result(bytes(raw), self.packet, self.instance, self.prior)
        raw = bytearray(self.raw)
        struct.pack_into('<Q', raw, 176, 2)
        with self.subTest(invented_frame_generation=2), self.assertRaises(ValueError):
            checker.cp_parameter_bank_result(bytes(raw), self.packet, self.instance, self.prior)

    def test_OP20_full_bank_does_not_reassign_OP11_source_snapshot(self):
        self.assertEqual(checker.OPS[20], (2564,))
        self.assertEqual(checker.OPS[11], tuple(360 + 8 * (cp + sdk)
                         for cp in (100, 13, 14) for sdk in (1, 2)))
        self.assertNotIn(2564, checker.OPS[11])

    def test_policy_reads_actual_producer_and_all_absent_legacy_remains_valid(self):
        profile = self.profile()
        expected = checker.CP_PARAMETER_BANK_POLICY
        self.assertEqual(len(expected), 9)
        for key, value in expected.items():
            for target in (profile, profile['backup_transport']):
                self.assertTrue(checker.typed_equal(target['functional_camera_' + key], value))
        verdict = checker.check_profile(profile)
        self.assertTrue(verdict['verified'])
        self.assertIs(verdict['physical_asic_compatibility_verified'], False)
        self.assertIs(verdict['original_CP_executed'], False)
        self.assertIs(profile['functional_camera_capture_verified'], False)
        self.assertIs(profile['functional_camera_physical_ASIC_compatibility_verified'], False)
        for target in (profile, profile['backup_transport']):
            for key in expected:
                del target['functional_camera_' + key]
        self.assertTrue(checker.check_profile(profile)['verified'])

    def test_each_policy_field_requires_both_complete_typed_manifest_copies(self):
        original = self.profile()
        for key, value in checker.CP_PARAMETER_BANK_POLICY.items():
            full = 'functional_camera_' + key
            wrong_values = [None, 'undeclared-physical-policy', {}, []]
            if type(value) is int:
                wrong_values += [True, float(value), value + 1]
            elif type(value) is bool:
                wrong_values += [0, True]
            elif type(value) is list:
                wrong_values += [(0x4063,), [True], [float(0x4063)], [0x4062]]
            else:
                wrong_values += [False, value + ' ']
            for side in ('top', 'backup_transport', 'both'):
                for missing, wrong in [(True, None), *((False, wrong) for wrong in wrong_values)]:
                    profile = copy.deepcopy(original)
                    targets = (profile, profile['backup_transport']) if side == 'both' else (
                        profile if side == 'top' else profile['backup_transport'],)
                    for target in targets:
                        if missing:
                            del target[full]
                        else:
                            target[full] = wrong
                    with self.subTest(field=key, side=side, missing=missing, wrong=wrong), self.assertRaises(ValueError):
                        checker.check_profile(profile)

    def test_any_partial_policy_on_an_older_manifest_is_rejected(self):
        legacy = self.profile()
        for target in (legacy, legacy['backup_transport']):
            for key in checker.CP_PARAMETER_BANK_POLICY:
                del target['functional_camera_' + key]
        for key, value in checker.CP_PARAMETER_BANK_POLICY.items():
            for side in ('top', 'backup_transport', 'both'):
                profile = copy.deepcopy(legacy)
                targets = (profile, profile['backup_transport']) if side == 'both' else (
                    profile if side == 'top' else profile['backup_transport'],)
                for target in targets:
                    target['functional_camera_' + key] = copy.deepcopy(value)
                with self.subTest(partial_field=key, side=side), self.assertRaises(ValueError):
                    checker.check_profile(profile)

    def test_mixed_source_snapshot_or_reply_policy_cannot_promote_software_bank(self):
        for field, wrong in (('opcode', 11), ('reply_policy', 'echo-f000-independent-ACK'),
                             ('physical_semantics_verified', True)):
            profile = self.profile()
            for target in (profile, profile['backup_transport']):
                target['functional_camera_cp_parameter_bank_' + field] = wrong
            with self.subTest(mixed_field=field), self.assertRaises(ValueError):
                checker.check_profile(profile)


class CPParameterBankTransportEvidenceTests(unittest.TestCase):
    """HOST_TEST file/console/broker fixtures; no C model or original VM is run."""

    @classmethod
    def setUpClass(cls):
        CPParameterBankEvidenceTests.setUpClass()

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        wire = CPParameterBankEvidenceTests('runTest')
        wire.setUp()
        wire.prior = control_state(fps=24, generation=22)
        self.packet, self.prior = wire.packet, wire.prior
        self.receipt = wire.result(self.packet)
        self.following = self.receipt[64:192]
        self.origin = dict(producer_tid=90, source=0x80020002, destination=0x90030001,
                           command=0x4063, bytes=2564, fnv1a64=checker.fnv(self.packet))
        start_wire = struct.pack('<HHI', 0, 0x3003, 0x80000027) + bytes(16)
        start = dict(self.origin, command=0x3003, bytes=24, fnv1a64=checker.fnv(start_wire))
        cached = control_state(fps=24, generation=21)
        operations = [dict(op=1, data=b'', output=cached, origin=start),
                      dict(op=2, data=b'', output=self.prior, origin=self.origin),
                      dict(op=20, data=self.packet, output=self.receipt, origin=self.origin),
                      dict(op=2, data=b'', output=self.following, origin=self.origin)]
        records = ['HOST_TEST_TRANSFER_0']
        legacy, = checker.parse_console(E6MX_CONTROL_COMMIT)
        control = dict(legacy['fields'])
        control.update(pid='77', tid='90', sender_tid='90', receiver_tid='91', free_tid='91',
            freed='1', consumed='1', retained='(nil)', model_instance='99', config_generation='21',
            rendered='1', frame_generation='1', start_complete='1', mode1_complete='1',
            notification_queued='1', notification_received='1', notification_AP_consumed='1',
            native_fnv1a=f'{start["fnv1a64"]:016x}')
        extended = {}
        for key, value in control.items():
            if key == 'business_ready':
                extended.update(mode_selector='0', mode_complete='1', mode0_requests='1', mode0_complete='1',
                    mode0_cycles_completed='1', mode1_cycle_id='1', mode1_cycle_generation='21',
                    selector_policy='opaque-state-refresh-v1')
            extended[key] = value
        for event in ('PROBE', 'COMMIT'):
            records.append(self.record('FUNCTIONAL_CAMERA_CONTROL_' + event, extended))
        resources = checker.parse_console(JFZ_VDF_RESOURCE_OBS.encode())
        for row in resources:
            row['tag'] = row['tag'].replace('FUNCTIONAL_VDF_PATH', 'FUNCTIONAL_CP_PARAMETER_BANK')
            row['fields']['tid'] = '90'
            if 'pid' in row['fields']:
                row['fields']['pid'] = '77'
        base = checker.number(resources[1]['fields']['appfw_base'])
        audit = dict(pid=77, tid=90, sequence=50, entry='async', pointer='0x400000',
            destination='0x90030001', bytes=2564, source='0x80020002', size_known=1, source_known=1,
            bytes_complete=1, complete=1, producer_return=hex(base + 0x3535a68),
            consumed=0, state_verified=0, capture_verified=0)
        records.append(self.record('NATIVE_CP_BACKGROUND_INPUT_AUDIT', audit))
        for offset in range(0, len(self.packet), 128):
            data = self.packet[offset:offset + 128]
            records.append(self.record('NATIVE_CP_BACKGROUND_INPUT_AUDIT_BYTES',
                dict(pid=77, tid=90, sequence=50, offset=offset, bytes=len(data), raw=data.hex())))
        events = ('BEGIN', 'BEFORE', 'MODEL', 'AFTER', 'VERIFIED', 'OWNED_FREE', 'COMMIT')
        streams = dict(BEGIN=('request', self.packet), BEFORE=('before_state', self.prior),
                       MODEL=('receipt', self.receipt), AFTER=('after_state', self.following))
        for index, event in enumerate(events):
            if event in ('BEFORE', 'MODEL', 'AFTER'):
                records.append('HOST_TEST_TRANSFER_' + str(index))
            fields = dict(event=event, pid=77, tid=90, transaction=2, sender_tid=90,
                source='0x80020002', destination='0x90030001', command='0x4063', bytes=2564,
                native_fnv1a=f'{self.origin["fnv1a64"]:016x}', cookie=hex(struct.unpack_from('<I', self.packet, 4)[0]),
                busy=1, guard=int(event not in ('BEGIN', 'COMMIT')), faults=0, error=0, model_rc=0,
                model_called=int(index >= 2), model_committed=int(index >= 2), verified=int(index >= 4),
                owned=int(index >= 4), retained='0x400000' if event == 'VERIFIED' else '(nil)', releasing=0,
                request_freed=int(index >= 5), free_rc=0, free_tid=90 if index >= 5 else 0,
                commits=int(index >= 4), released=int(index >= 5), model_instance=99,
                bank_generation=int(index >= 2), before_config_generation=22 if index >= 1 else 0,
                config_generation=23 if index >= 2 else 0, fps=30,
                before_used=128 if index >= 1 else 0, before_required=128 if index >= 1 else 0,
                before_token=0, before_instance=99 if index >= 1 else 0,
                bank_used=2756 if index >= 2 else 0, bank_required=2756 if index >= 2 else 0,
                bank_token=0, bank_instance=99 if index >= 2 else 0,
                after_used=128 if index >= 3 else 0, after_required=128 if index >= 3 else 0,
                after_token=0, after_instance=99 if index >= 3 else 0,
                policy='full-190-slot-bank-fps4151-v1', oneway=1, ACK_sent=0, notification_sent=0,
                functional_model=1, original_CP=0, physical_ASIC_verified=0, capture_verified=0)
            records.append(self.record('FUNCTIONAL_CP_PARAMETER_BANK_EVENT', fields))
            if event in streams:
                kind, raw = streams[event]
                for offset in range(0, len(raw), 128):
                    data = raw[offset:offset + 128]
                    records.append(self.record('FUNCTIONAL_CP_PARAMETER_BANK_BYTES',
                        dict(pid=77, tid=90, transaction=2, kind=kind, total=len(raw), offset=offset,
                            bytes=len(data), raw=data.hex(), native_fnv1a=fields['native_fnv1a'],
                            model_instance=99, bank_generation=fields['bank_generation'], capture_verified=0)))
            if event == 'BEGIN':
                records.extend(self.record(row['tag'], row['fields']) for row in resources)
        self.args = host_test_transport(Path(temporary.name), operations, '\n'.join(records) + '\n')
        self.run, self.manifest, self.rows, broker, build = self.args
        policy = {'functional_camera_' + key: copy.deepcopy(value)
                  for key, value in checker.CP_PARAMETER_BANK_POLICY.items()}
        self.manifest.update(policy)
        self.manifest['backup_transport'].update(copy.deepcopy(policy))
        core = next(event for event in broker if event['kind'] == 'core_result' and event['opcode'] == 20)
        witness = dict(kind='model_parameter_bank', model_instance=99, sequence=3, opcode=20,
            origin=copy.deepcopy(self.origin), actual_c_result=0, actual_core_sha256=build['model_sha256'],
            request_payload=core['request_payload'], output_payload=core['output_payload'], native_acceptance=False,
            observation=dict(actual_c_result=0, returned_hex=self.receipt.hex(), readback_verified=True,
                before_state_c_result=0, before_state_hex=self.prior.hex(),
                result=dict(token=0, total=0, offset=0, used=2756), query_c_result=0,
                bank_generation=1, snapshot_hex=self.receipt.hex(), after_state_c_result=0,
                after_state_hex=self.following.hex()))
        broker.insert(broker.index(core) + 1, witness)
        for event in broker:
            if event.get('opcode') == 20 and event['kind'] in ('core_result', 'response'):
                event['actual_core_sha256'] = build['model_sha256']
        self.persist_broker(self.args)
        transfers = []
        for row in self.rows:
            if row['tag'] != 'FUNCTIONAL_CAMERA_TRANSFER':
                continue
            sequence = int(row['fields']['seq'].split('..')[0])
            request = next(event for event in broker if event['kind'] == 'request' and event['sequence'] == sequence)
            result = next(event for event in broker if event['kind'] == 'core_result' and event['sequence'] == sequence)
            reference = result['output_payload']
            tx = dict(line=row['line'], first=sequence, last=sequence, opcode=request['opcode'],
                origin=copy.deepcopy(request['origin']), bytes=reference['bytes'], sha256=reference['sha256'],
                fnv1a64=f'{reference["fnv1a64"]:016x}', request_payload=request['request_payload'],
                output_payloads=[reference], token=0, frame=None, model_instance=99, provider_kind='core')
            if request['opcode'] == 20:
                tx['parameter_bank'] = witness
            transfers.append(tx)
        self.transport = dict(pid=77, model_instance=99, owner_pid=177, transfers=transfers)

    @staticmethod
    def record(tag, fields):
        return tag + ' ' + ' '.join(f'{key}={value}' for key, value in fields.items())

    @staticmethod
    def persist_broker(args):
        run, manifest, _, events, _ = args
        counts = {}
        for index, event in enumerate(events, 1):
            event.update(event=index, monotonic_ns=index)
            counts[event['kind']] = counts.get(event['kind'], 0) + 1
            if event['kind'] == 'request':
                event['request_payload']['producer_event'] = index
            elif event['kind'] == 'core_result':
                event['output_payload']['producer_event'] = index
        manifest['functional_camera_runtime']['broker_event_counts'] = counts
        (run / 'functional-camera-runner.json').write_text(json.dumps(manifest['functional_camera_runtime']))
        (run / 'functional-camera-broker-receipts.jsonl').write_text(''.join(json.dumps(event) + '\n' for event in events))
        (run / 'runtime-manifest.json').write_text(json.dumps(manifest))

    def bank(self, rows=None, transport=None, manifest=None):
        return checker.check_cp_parameter_bank(self.run, self.manifest if manifest is None else manifest,
            self.rows if rows is None else rows, self.transport if transport is None else transport)

    @staticmethod
    def native(rows, *, event=None, kind=None):
        return [row for row in rows if
            (event is None or row['tag'] == 'FUNCTIONAL_CP_PARAMETER_BANK_EVENT' and row['fields']['event'] == event) and
            (kind is None or row['tag'] == 'FUNCTIONAL_CP_PARAMETER_BANK_BYTES' and row['fields']['kind'] == kind)]

    def test_complete_file_broker_native_join_uses_live22_not_cached21_and_preserves_scope(self):
        events = checker.jsonl((self.run / 'functional-camera-broker-receipts.jsonl').read_bytes())
        transport = checker.check_transport(self.run, self.manifest, self.rows, events, self.args[4])
        result = transport['parameter_bank']
        self.assertTrue(transport['verified'])
        self.assertTrue(result['required'] and result['verified'])
        self.assertEqual(result, self.bank())
        self.assertEqual(len(self.native(self.rows, kind='request')), 21)
        self.assertEqual(sum(len(self.native(self.rows, kind=kind)) for kind in
            ('request', 'before_state', 'receipt', 'after_state')), 45)
        self.assertEqual(sum(row['tag'] == 'NATIVE_CP_BACKGROUND_INPUT_AUDIT_BYTES' for row in self.rows), 21)
        self.assertEqual(len(list((self.run / 'functional-camera-data').iterdir())), 8)
        self.assertEqual([tx['opcode'] for tx in transport['transfers']], [1, 2, 20, 2])
        self.assertEqual([tx['opcode'] for tx in transport['transfers'] if 'parameter_bank' in tx], [20])
        self.assertEqual(result['transactions'][0], dict(transaction=2, bank_generation=1, source_audit_sequence=50,
            original_free_line=self.native(self.rows, event='OWNED_FREE')[0]['line'], model_sequence=3,
            before_STATE_sequence=2, after_STATE_sequence=4, result_sha256=checker.sha(self.receipt),
            packet_sha256=checker.sha(self.packet), model_instance=99, before_config_generation=22,
            config_generation=23, frame_generation=1, fps=30))
        self.assertEqual(checker.vdf_history(self.run, transport)[3]['before_config_generation'], 22)
        self.assertTrue(all(tx['frame'] is None and tx['token'] == 0 for tx in transport['transfers']))
        self.assertTrue(all(result[key] is False for key in
            ('frame_consumed', 'capture_verified', 'physical_asic_compatibility_verified')))
        commit = self.native(self.rows, event='COMMIT')[0]['fields']
        self.assertEqual((commit['busy'], commit['guard'], commit['request_freed']), ('1', '0', '1'))

    def test_outer_and_all190_inner_header_byte1_are_opaque_and_preserved(self):
        wire = CPParameterBankEvidenceTests('runTest')
        wire.setUp()
        wire.prior = self.prior
        for outer in (0, 0xa5, 0xff):
            for shift in (0, 0x5a):
                packet = bytearray(self.packet)
                packet[1] = outer
                for index, (_, offset, _) in enumerate(wire.slots):
                    packet[offset + 1] = (index + shift) & 0xff
                packet = bytes(packet)
                raw = wire.result(packet)
                with self.subTest(outer_byte1=outer, inner_shift=shift):
                    value = checker.cp_parameter_bank_result(raw, packet, 99, self.prior)
                    self.assertEqual(value['input_fnv'], checker.fnv(packet))
                    self.assertEqual(struct.unpack_from('<Q', raw, 40)[0], checker.fnv(packet))
                    self.assertEqual(raw[192:], packet)
                    self.assertEqual(raw[193], outer)
                    self.assertEqual(raw[64:192], self.following)
                    self.assertEqual([raw[192 + offset + 1] for _, offset, _ in wire.slots],
                                     [(index + shift) & 0xff for index in range(190)])

    def test_orphan_native_records_require_actual_Core20_while_old_transport_stays_optional(self):
        empty = dict(self.transport, transfers=[])
        self.assertFalse(self.bank(rows=[], transport=empty)['required'])
        for tag in ('FUNCTIONAL_CP_PARAMETER_BANK_EVENT', 'FUNCTIONAL_CP_PARAMETER_BANK_BYTES',
                    'FUNCTIONAL_CP_PARAMETER_BANK_RESOURCES_RESERVED'):
            row = next(row for row in self.rows if row['tag'] == tag)
            with self.subTest(tag=tag), self.assertRaisesRegex(ValueError, 'lack actual Core20'):
                self.bank(rows=[row], transport=empty)

    def test_actual_bank_requires_complete_typed_policy_on_both_sides(self):
        for key in checker.CP_PARAMETER_BANK_POLICY:
            for side in ('top', 'backup_transport', 'both'):
                changed = copy.deepcopy(self.manifest)
                targets = (changed, changed['backup_transport']) if side == 'both' else (
                    changed if side == 'top' else changed['backup_transport'],)
                for target in targets:
                    del target['functional_camera_' + key]
                with self.subTest(key=key, side=side), self.assertRaisesRegex(ValueError, 'explicit software policy'):
                    self.bank(manifest=changed)
        for key, wrong in (('opcode', True), ('physical_semantics_verified', 0), ('native_commands', [float(0x4063)])):
            changed = copy.deepcopy(self.manifest)
            for target in (changed, changed['backup_transport']):
                target['functional_camera_cp_parameter_bank_' + key] = wrong
            with self.subTest(key=key), self.assertRaises(ValueError):
                self.bank(manifest=changed)

    def test_STATE_queries_are_adjacent_same_origin_core_tokenless_and_frameless(self):
        for index in (1, 2, 3):
            for key, wrong in (('token', 1), ('frame', {'proof': {'opcode': 20}}), ('provider_kind', 'source')):
                changed = copy.deepcopy(self.transport)
                changed['transfers'][index][key] = wrong
                with self.subTest(index=index, field=key), self.assertRaises(ValueError):
                    self.bank(transport=changed)
        for index in (1, 3):
            for key in ('producer_tid', 'source', 'destination', 'command', 'bytes', 'fnv1a64'):
                changed = copy.deepcopy(self.transport)
                changed['transfers'][index]['origin'][key] ^= 1
                with self.subTest(index=index, origin=key), self.assertRaises(ValueError):
                    self.bank(transport=changed)
            for key, wrong in (('opcode', 1), ('first', 9), ('last', 9)):
                changed = copy.deepcopy(self.transport)
                changed['transfers'][index][key] = wrong
                with self.subTest(index=index, field=key), self.assertRaises(ValueError):
                    self.bank(transport=changed)

    def test_cached21_cannot_replace_live22_and_post_STATE_must_be_identical(self):
        for target, donor in ((1, 0), (3, 1)):
            changed = copy.deepcopy(self.transport)
            for key in ('output_payloads', 'bytes', 'sha256', 'fnv1a64'):
                changed['transfers'][target][key] = copy.deepcopy(changed['transfers'][donor][key])
            with self.subTest(target=target, donor=donor), self.assertRaises(ValueError):
                self.bank(transport=changed)
        for missing in (1, 3):
            changed = copy.deepcopy(self.transport)
            del changed['transfers'][missing]
            with self.subTest(missing=missing), self.assertRaises(ValueError):
                self.bank(transport=changed)

    def test_native_lifecycle_requires_every_event_once_in_original_order(self):
        for event in ('BEGIN', 'BEFORE', 'MODEL', 'AFTER', 'VERIFIED', 'OWNED_FREE', 'COMMIT'):
            for mutation in ('missing', 'duplicate', 'reordered'):
                rows = copy.deepcopy(self.rows)
                row = self.native(rows, event=event)[0]
                index = rows.index(row)
                if mutation == 'missing':
                    rows.pop(index)
                elif mutation == 'duplicate':
                    rows.insert(index, copy.deepcopy(row))
                else:
                    row['line'] = (self.native(rows, event='COMMIT')[0]['line'] + 1 if event == 'BEGIN' else
                                   self.native(rows, event='BEGIN')[0]['line'] - 1)
                with self.subTest(event=event, mutation=mutation), self.assertRaises(ValueError):
                    self.bank(rows=rows)

    def test_native_identity_cookie_and_whole_original_FNV_are_bound(self):
        for key, wrong in (('pid', '78'), ('tid', '91'), ('sender_tid', '91'), ('cookie', '0x80000028'),
                           ('source', '0x80020003'), ('destination', '0x90030002'), ('command', '0x4062'),
                           ('bytes', '2563'), ('native_fnv1a', '0000000000000000')):
            rows = copy.deepcopy(self.rows)
            self.native(rows, event='VERIFIED')[0]['fields'][key] = wrong
            with self.subTest(field=key), self.assertRaises(ValueError):
                self.bank(rows=rows)

    def test_commit_records_busy1_guard0_and_actual_original_free_not_a_ready_flag(self):
        for key, wrong in (('busy', '0'), ('guard', '1'), ('faults', '1'), ('error', '-5'), ('model_rc', '-5'),
                ('model_called', '0'), ('model_committed', '0'), ('verified', '0'), ('owned', '0'),
                ('request_freed', '0'), ('retained', '0x400000'), ('releasing', '1'), ('free_rc', '-5'),
                ('free_tid', '91'), ('released', '0'), ('commits', '0'), ('before_token', '1'),
                ('bank_required', '2755'), ('after_instance', '100')):
            rows = copy.deepcopy(self.rows)
            self.native(rows, event='COMMIT')[0]['fields'][key] = wrong
            with self.subTest(field=key), self.assertRaises(ValueError):
                self.bank(rows=rows)
        for event, key, wrong in (('VERIFIED', 'retained', '(nil)'), ('VERIFIED', 'request_freed', '1'),
                ('OWNED_FREE', 'free_rc', '-5'), ('OWNED_FREE', 'retained', '0x400000')):
            rows = copy.deepcopy(self.rows)
            self.native(rows, event=event)[0]['fields'][key] = wrong
            with self.subTest(event=event, field=key), self.assertRaises(ValueError):
                self.bank(rows=rows)

    def test_full_original_audit_requires_pointer_callsite_all21_chunks_and_unchanged_bytes(self):
        for key, wrong in (('pointer', '0x400001'), ('producer_return', '0x3535a68'), ('entry', 'sync'),
                           ('complete', '0'), ('source', '0x80020003'), ('bytes', '2563')):
            rows = copy.deepcopy(self.rows)
            next(row for row in rows if row['tag'] == 'NATIVE_CP_BACKGROUND_INPUT_AUDIT')['fields'][key] = wrong
            with self.subTest(field=key), self.assertRaises(ValueError):
                self.bank(rows=rows)
        for mutation in ('missing', 'duplicate', 'offset', 'raw', 'last'):
            rows = copy.deepcopy(self.rows)
            chunks = [row for row in rows if row['tag'] == 'NATIVE_CP_BACKGROUND_INPUT_AUDIT_BYTES']
            if mutation in ('missing', 'last'):
                rows.remove(chunks[0 if mutation == 'missing' else -1])
            elif mutation == 'duplicate':
                rows.insert(rows.index(chunks[1]), copy.deepcopy(chunks[0]))
            elif mutation == 'offset':
                chunks[1]['fields']['offset'] = '0'
            else:
                chunks[-1]['fields']['raw'] = '00' + chunks[-1]['fields']['raw'][2:]
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                self.bank(rows=rows)

    def test_each_native_stream_rejects_missing_duplicate_offset_or_last_byte_corruption(self):
        for kind in ('request', 'before_state', 'receipt', 'after_state'):
            for mutation in ('missing', 'duplicate', 'offset', 'last_byte'):
                rows = copy.deepcopy(self.rows)
                chunks = self.native(rows, kind=kind)
                if mutation == 'missing':
                    rows.remove(chunks[-1])
                elif mutation == 'duplicate':
                    rows.insert(rows.index(chunks[0]), copy.deepcopy(chunks[0]))
                elif mutation == 'offset':
                    chunks[-1]['fields']['offset'] = str(int(chunks[-1]['fields']['offset']) + 128)
                else:
                    raw = bytearray.fromhex(chunks[-1]['fields']['raw'])
                    raw[-1] ^= 1
                    chunks[-1]['fields']['raw'] = raw.hex()
                with self.subTest(kind=kind, mutation=mutation), self.assertRaises(ValueError):
                    self.bank(rows=rows)

    def test_native_stream_metadata_is_bound_to_each_parent_stage_and_transaction(self):
        for kind in ('request', 'before_state', 'receipt', 'after_state'):
            for key, wrong in (('pid', '78'), ('tid', '91'), ('transaction', '3'), ('model_instance', '100'),
                               ('bank_generation', '9'), ('native_fnv1a', '0000000000000000')):
                rows = copy.deepcopy(self.rows)
                self.native(rows, kind=kind)[0]['fields'][key] = wrong
                with self.subTest(kind=kind, field=key), self.assertRaises(ValueError):
                    self.bank(rows=rows)
            rows = copy.deepcopy(self.rows)
            self.native(rows, kind=kind)[0]['line'] = self.native(rows, event='COMMIT')[0]['line'] + 1
            with self.subTest(kind=kind, outside_stage=True), self.assertRaises(ValueError):
                self.bank(rows=rows)

    def test_resource33_cannot_be_missing_reordered_wrong_thread_or_borrow_mode25(self):
        for suffix in ('RESOURCE_DEPENDENCIES', 'RESOURCES_TTS_TABLE', 'RESOURCES_RESERVED'):
            for mutation in ('missing', 'wrong_thread', 'mode25', 'orphan'):
                rows = copy.deepcopy(self.rows)
                row = next(row for row in rows if row['tag'] == 'FUNCTIONAL_CP_PARAMETER_BANK_' + suffix)
                if mutation == 'missing':
                    rows.remove(row)
                elif mutation == 'wrong_thread':
                    row['fields']['tid'] = '91'
                elif mutation == 'mode25':
                    row['tag'] = row['tag'].replace('FUNCTIONAL_CP_PARAMETER_BANK', 'FUNCTIONAL_CAMERA_CONTROL')
                else:
                    row['line'] = self.native(rows, event='COMMIT')[0]['line'] + 1
                with self.subTest(resource=suffix, mutation=mutation), self.assertRaises(ValueError):
                    self.bank(rows=rows)
        rows = copy.deepcopy(self.rows)
        held = [row for row in rows if row['tag'].startswith('FUNCTIONAL_CP_PARAMETER_BANK_RESOURCE')]
        first, second = rows.index(held[0]), rows.index(held[1])
        rows[first], rows[second] = rows[second], rows[first]
        with self.assertRaises(ValueError):
            self.bank(rows=rows)

    def test_resource33_rejects_accepted_records_with_the_wrong_DMM_allocation(self):
        for key, wrong in (('dmm_handles', '0x8400/0x8402'), ('dmm_domain', '3'),
                           ('dmm_enabled', '0'), ('dmm_bound', '0'), ('dmm_slots', '0/1')):
            rows = copy.deepcopy(self.rows)
            next(row for row in rows if row['tag'] == 'FUNCTIONAL_CP_PARAMETER_BANK_RESOURCES_RESERVED')['fields'][key] = wrong
            with self.subTest(field=key), self.assertRaises(ValueError):
                self.bank(rows=rows)

    def test_historical_mode1_does_not_substitute_for_current_mode_ACK_and_notice_retirement(self):
        for key, wrong in (('mode_complete', '0'), ('notification_AP_consumed', '0'), ('start_complete', '0'),
                           ('mode1_complete', '0'), ('busy', '1'), ('guard', '1'), ('faults', '1'), ('model_instance', '100')):
            rows = copy.deepcopy(self.rows)
            mode = next(row for row in rows if row['tag'] == 'FUNCTIONAL_CAMERA_CONTROL_COMMIT')['fields']
            self.assertEqual(mode['mode1_complete'], '1')
            mode[key] = wrong
            with self.subTest(field=key), self.assertRaisesRegex(ValueError, 'historical mode1'):
                self.bank(rows=rows)

    def test_broker_independent_query_requires_exact_library_shape_result_and_success_returns(self):
        changes = [('actual_core_sha256', 'd' * 64), ('actual_c_result', -5), ('native_acceptance', True)]
        changes += [('observation.' + key, wrong) for key, wrong in
            (('query_c_result', -5), ('actual_c_result', -5), ('before_state_c_result', -5),
             ('after_state_c_result', -5), ('readback_verified', False), ('bank_generation', 2),
             ('result', dict(token=0, total=0, offset=0, used=2755)))]
        for key, wrong in changes:
            args = copy.deepcopy(self.args)
            event = next(event for event in args[3] if event['kind'] == 'model_parameter_bank')
            if key.startswith('observation.'):
                event['observation'][key.split('.')[1]] = wrong
            else:
                event[key] = wrong
            self.persist_broker(args)
            with self.subTest(field=key), self.assertRaises(ValueError):
                checker.check_transport(*args)
        for key in ('actual_core_sha256', 'observation'):
            args = copy.deepcopy(self.args)
            event = next(event for event in args[3] if event['kind'] == 'model_parameter_bank')
            del event[key]
            self.persist_broker(args)
            with self.subTest(missing=key), self.assertRaises(ValueError):
                checker.check_transport(*args)
        for key in self.transport['transfers'][2]['parameter_bank']['observation']:
            args = copy.deepcopy(self.args)
            event = next(event for event in args[3] if event['kind'] == 'model_parameter_bank')
            del event['observation'][key]
            self.persist_broker(args)
            with self.subTest(missing=key), self.assertRaises(ValueError):
                checker.check_transport(*args)

    def test_broker_full2756_query_and_State128_are_compared_as_bytes(self):
        for key, raw in (('returned_hex', self.receipt), ('snapshot_hex', self.receipt),
                         ('before_state_hex', self.prior), ('after_state_hex', self.following)):
            for mutation in ('truncated', 'different'):
                args = copy.deepcopy(self.args)
                event = next(event for event in args[3] if event['kind'] == 'model_parameter_bank')
                changed = bytearray(raw)
                if mutation == 'truncated':
                    changed.pop()
                else:
                    changed[-1] ^= 1
                event['observation'][key] = changed.hex()
                self.persist_broker(args)
                with self.subTest(field=key, mutation=mutation), self.assertRaises(ValueError):
                    checker.check_transport(*args)
        args = copy.deepcopy(self.args)
        event = next(event for event in args[3] if event['kind'] == 'model_parameter_bank')
        event['observation']['before_state_hex'] = control_state(fps=24, generation=21).hex()
        self.persist_broker(args)
        with self.assertRaises(ValueError):
            checker.check_transport(*args)

    def test_broker_before_STATE_cannot_diverge_from_bracketing_live_STATE_at_same_generation(self):
        args = copy.deepcopy(self.args)
        event = next(event for event in args[3] if event['kind'] == 'model_parameter_bank')
        before = bytearray(self.prior)
        struct.pack_into('<I', before, 16, 25)
        event['observation']['before_state_hex'] = before.hex()
        self.persist_broker(args)
        with self.assertRaises(ValueError):
            checker.check_transport(*args)

    def test_broker_query_must_be_once_between_original_Core20_and_response(self):
        for mutation in ('missing', 'duplicate', 'late', 'wrong_origin', 'wrong_request', 'wrong_output'):
            args = copy.deepcopy(self.args)
            events = args[3]
            event = next(event for event in events if event['kind'] == 'model_parameter_bank')
            index = events.index(event)
            if mutation == 'missing':
                events.remove(event)
            elif mutation == 'duplicate':
                events.insert(index, copy.deepcopy(event))
            elif mutation == 'late':
                events[index], events[index + 1] = events[index + 1], events[index]
            elif mutation == 'wrong_origin':
                event['origin']['producer_tid'] += 1
            else:
                key = 'request_payload' if mutation == 'wrong_request' else 'output_payload'
                event[key] = copy.deepcopy(event[key])
                event[key]['sequence'] += 1
            self.persist_broker(args)
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                checker.check_transport(*args)

    def test_bank_events_bytes_and_resource33_frame_both_exact_trailers_without_byte_changes(self):
        samples = [row for row in self.rows if row['tag'].startswith('FUNCTIONAL_CP_PARAMETER_BANK_')]
        before = b'ordinary\n'
        trailers = (b'[ 5638.875229] UDIF: cdev_ioctl() Line 100: uipc: warning ret = -1022',
                    b'[ 5541.864466] [K]**UIPC ERROR** free_dynamic_msgq_id: QID[81cf61c4] M=1 C=0 S=0 A=1')
        for sample in samples:
            payload = self.record(sample['tag'], sample['fields']).encode()
            self.assertEqual(checker.console_producer_fields(payload), sample['fields'])
            for trailer in trailers:
                for ending in (b'\n', b'\r\n'):
                    with self.subTest(tag=sample['tag'], kind=sample['fields'].get('kind'),
                                      offset=sample['fields'].get('offset'), trailer=trailer, ending=ending):
                        raw = before + b'OBS ' + payload + trailer + ending
                        row, = checker.parse_console(raw)
                        self.assertNotIn('diagnostic', row)
                        self.assertEqual(row['fields'], sample['fields'])
                        diagnostic = row['kernel_diagnostic']
                        self.assertEqual((diagnostic['raw_lf_line'], diagnostic['cause'], diagnostic['line_ending']),
                                         (2, 'unknown', ending.decode()))
                        self.assertEqual(diagnostic['payload']['byte_offset'], len(before) + 4)
                        self.assertEqual(diagnostic['byte_offset'], len(before) + 4 + len(payload))
                        for part in (diagnostic, diagnostic['payload']):
                            original = raw[part['byte_offset']:part['byte_offset'] + part['bytes']]
                            self.assertEqual(original, part['raw'].encode())
                            self.assertEqual(checker.sha(original), part['sha256'])
                        self.assertEqual(diagnostic['payload']['raw'].encode() + diagnostic['raw'].encode() + ending,
                                         raw[len(before) + 4:])
                        if 'capture_verified' in row['fields']:
                            self.assertEqual(row['fields']['capture_verified'], '0')
                        else:
                            self.assertEqual(row['fields']['ownership_verified'], '0')

    def test_bank_formatter_unknown_missing_duplicate_and_reordered_keys_never_gain_repair(self):
        tags = ('FUNCTIONAL_CP_PARAMETER_BANK_EVENT', 'FUNCTIONAL_CP_PARAMETER_BANK_BYTES',
                'FUNCTIONAL_CP_PARAMETER_BANK_RESOURCE_DEPENDENCIES',
                'FUNCTIONAL_CP_PARAMETER_BANK_RESOURCES_TTS_TABLE', 'FUNCTIONAL_CP_PARAMETER_BANK_RESOURCES_RESERVED')
        trailer = b'[ 5638.875229] UDIF: cdev_ioctl() Line 100: uipc: warning ret = -1022\n'
        for tag in tags:
            sample = next(row for row in self.rows if row['tag'] == tag)
            payload = self.record(tag, sample['fields']).encode()
            parts = payload.split(b' ')
            variants = [payload + b' unknown=0', b' '.join(parts[:2] + parts[3:]),
                        b' '.join(parts[:1] + [parts[2], parts[1]] + parts[3:])]
            for changed in variants:
                with self.subTest(tag=tag, payload=changed):
                    self.assertIsNone(checker.console_producer_fields(changed))
                    row, = checker.parse_console(changed + trailer)
                    self.assertIn('diagnostic', row)
                    self.assertNotIn('kernel_diagnostic', row)
            with self.subTest(tag=tag, duplicate=True), self.assertRaisesRegex(ValueError, 'duplicate JSON key'):
                checker.parse_console(payload + b' ' + parts[1] + trailer)

    def test_bank_formatter_rejects_invalid_kind_event_lengths_total_tail_and_claims(self):
        event = self.record('FUNCTIONAL_CP_PARAMETER_BANK_EVENT', self.native(self.rows, event='BEGIN')[0]['fields']).encode()
        byte_row = self.native(self.rows, kind='request')[-1]
        chunk = self.record(byte_row['tag'], byte_row['fields']).encode()
        variants = [event.replace(b'event=BEGIN', b'event=SUCCESS'),
                    event.replace(b'capture_verified=0', b'capture_verified=1'),
                    event.replace(b'ACK_sent=0', b'ACK_sent=1'),
                    chunk.replace(b'kind=request', b'kind=frame'),
                    chunk.replace(b'total=2564', b'total=2563'),
                    chunk.replace(b'offset=2560', b'offset=2561'),
                    chunk.replace(b'bytes=4 ', b'bytes=3 '),
                    chunk.replace(('raw=' + byte_row['fields']['raw']).encode(), b'raw=00')]
        trailer = b'[ 5541.864466] [K]**UIPC ERROR** free_dynamic_msgq_id: QID[81cf61c4] M=1 C=0 S=0 A=1\r\n'
        for payload in variants:
            with self.subTest(payload=payload):
                self.assertIsNone(checker.console_producer_fields(payload))
                row, = checker.parse_console(payload + trailer)
                self.assertIn('diagnostic', row)
                self.assertNotIn('kernel_diagnostic', row)
        for payload in (event, chunk):
            with self.subTest(truncated=payload), self.assertRaisesRegex(ValueError, 'truncated evidence trace'):
                checker.parse_console(payload + trailer[:-2])

    def test_bank_framer_rejects_noncanonical_UIPC_trailers_and_keeps_resource_schema(self):
        sample = self.native(self.rows, event='BEGIN')[0]
        payload = self.record(sample['tag'], sample['fields']).encode()
        dynamic = b'[ 5541.864466] [K]**UIPC ERROR** free_dynamic_msgq_id: QID[81cf61c4] M=1 C=0 S=0 A=1'
        for trailer in (dynamic.replace(b'5541.864466', b'05541.864466'), dynamic.replace(b'81cf61c4', b'81CF61C4'),
                        dynamic.replace(b'M=1', b'M=0'), dynamic.replace(b'C=0 S=0', b'S=0 C=0'),
                        dynamic + b' extra', dynamic[:-1],
                        b'[ 5638.875229] UDIF: cdev_ioctl() Line 100: uipc: warning ret = -1021'):
            with self.subTest(trailer=trailer):
                row, = checker.parse_console(payload + trailer + b'\n')
                self.assertIn('diagnostic', row)
                self.assertNotIn('kernel_diagnostic', row)
        sample = next(row for row in self.rows if row['tag'] == 'FUNCTIONAL_CP_PARAMETER_BANK_RESOURCES_RESERVED')
        for key, wrong in (('dmm_handles', '0x8400'), ('dmm_slots', '1/2'), ('dmm_domain', '4294967296'),
                           ('control_live', '1'), ('capture_verified', '1')):
            fields = dict(sample['fields'], **{key: wrong})
            changed = self.record(sample['tag'], fields).encode()
            with self.subTest(resource_field=key):
                self.assertIsNone(checker.console_producer_fields(changed))
                row, = checker.parse_console(changed + dynamic + b'\n')
                self.assertIn('diagnostic', row)
                self.assertNotIn('kernel_diagnostic', row)


class CPCrankControlEvidenceTests(unittest.TestCase):
    """Declared 208-byte parser fixtures only; no C model or original AP is run."""

    def setUp(self):
        prior = bytearray(control_state(fps=30, generation=23))
        struct.pack_into('<5Q', prior, 64, 22, 9, 3, 4, 17613)
        struct.pack_into('<Q', prior, 112, 22)
        self.prior = bytes(prior)
        self.packet = self.request()
        self.raw = self.receipt(self.packet, self.prior)

    @staticmethod
    def request(byte1=0xa5, cookie=0x80000060):
        return struct.pack('<BBHI', 5, byte1, 0x409d, cookie) + bytes(4)

    @staticmethod
    def receipt(packet, prior, bank_generation=4, crank_generation=2):
        before = struct.unpack_from('<Q', prior, 56)[0]
        state = bytearray(prior)
        struct.pack_into('<Q', state, 56, (before + 1) & (2**64 - 1))
        raw = bytearray(208)
        struct.pack_into('<2I6Q2I', raw, 0, 1, 208, struct.unpack_from('<Q', prior, 48)[0],
                         crank_generation, bank_generation, before, (before + 1) & (2**64 - 1),
                         checker.fnv(packet), 0, struct.unpack_from('<I', prior, 16)[0])
        raw[64:192], raw[192:204] = state, packet
        return bytes(raw)

    def decode(self, raw=None, packet=None, prior=None, instance=99, bank_generation=4):
        return checker.cp_crank_control_result(self.raw if raw is None else raw,
            self.packet if packet is None else packet, instance,
            self.prior if prior is None else prior, bank_generation)

    def test_mode0_preserves_active_fps_all_config_frame_and_nonzero_counters(self):
        for fps in (1, 30, 60, 120):
            prior = bytearray(self.prior)
            struct.pack_into('<I', prior, 16, fps)
            prior = bytes(prior)
            raw = self.receipt(self.packet, prior)
            value = self.decode(raw=raw, prior=prior)
            self.assertEqual(value, dict(model_instance=99, crank_generation=2, bank_generation=4,
                before_config_generation=23, config_generation=24, input_fnv=checker.fnv(self.packet),
                mode=0, fps=fps, frame_generation=22))
            self.assertEqual(raw[72:112], prior[8:48])
            self.assertEqual(raw[128:192], prior[64:128])
            self.assertEqual(raw[192:204], self.packet)
            self.assertEqual(raw[204:], bytes(4))

    def test_byte1_and_all_cookie_values_are_opaque_and_preserved_in_full12(self):
        for byte1 in (0, 0xa5, 0xff):
            for cookie in (0, 0x80000060, 0xffffffff):
                packet = self.request(byte1, cookie)
                raw = self.receipt(packet, self.prior)
                with self.subTest(byte1=byte1, cookie=cookie):
                    value = self.decode(raw=raw, packet=packet)
                    self.assertEqual(value['input_fnv'], checker.fnv(packet))
                    self.assertEqual(raw[192:204], packet)
                    self.assertEqual(struct.unpack_from('<I', raw, 196)[0], cookie)

    def test_nonzero_body_type_command_and_non12_inputs_cannot_borrow_bank_API(self):
        for offset in (0, 2, 3, 8, 9, 10, 11):
            packet = bytearray(self.packet)
            packet[offset] ^= 1
            packet = bytes(packet)
            with self.subTest(changed_request_byte=offset), self.assertRaises(ValueError):
                self.decode(raw=self.receipt(packet, self.prior), packet=packet)
        for packet in (b'', self.packet[:8], self.packet[:-1], self.packet + b'\0', bytes(2564)):
            with self.subTest(bytes=len(packet)), self.assertRaises(ValueError):
                self.decode(packet=packet)
        self.assertEqual(checker.OPS[21], (12,))
        self.assertEqual(checker.OPS[20], (2564,))
        self.assertEqual(checker.OPS[11], tuple(360 + 8 * (cp + sdk)
                         for cp in (100, 13, 14) for sdk in (1, 2)))
        self.assertNotIn(2564, checker.OPS[21])
        self.assertNotIn(12, checker.OPS[11])

    def test_full208_header_and_trailing_bytes_are_exact(self):
        for raw in (b'', self.raw[:63], self.raw[:191], self.raw[:-1], self.raw + b'\0', bytes(2756)):
            with self.subTest(bytes=len(raw)), self.assertRaises(ValueError):
                self.decode(raw=raw)
        for offset, values in ((0, (0, 2)), (4, (0, 128, 207, 209, 2756))):
            for value in values:
                raw = bytearray(self.raw)
                struct.pack_into('<I', raw, offset, value)
                with self.subTest(offset=offset, value=value), self.assertRaises(ValueError):
                    self.decode(raw=bytes(raw))

    def test_all12_readback_bytes_and_all_four_reserved_bytes_are_checked(self):
        for offset in range(192, 208):
            raw = bytearray(self.raw)
            raw[offset] ^= 1
            with self.subTest(offset=offset), self.assertRaises(ValueError):
                self.decode(raw=bytes(raw))
        packet = self.request(cookie=0x80000061)
        raw = bytearray(self.raw)
        struct.pack_into('<Q', raw, 48, checker.fnv(packet))
        with self.assertRaises(ValueError):
            self.decode(raw=bytes(raw), packet=packet)

    def test_instance_expected_bank_and_positive_crank_generation_are_mandatory(self):
        for instance in (0, 98, True, 99.0, None):
            with self.subTest(instance=instance), self.assertRaises(ValueError):
                self.decode(instance=instance)
        for bank in (0, -1, 3, 5, 2**64, True, 4.0, None):
            with self.subTest(expected_bank=bank), self.assertRaises(ValueError):
                self.decode(bank_generation=bank)
        with self.assertRaises(TypeError):
            checker.cp_crank_control_result(self.raw, self.packet, 99, self.prior)
        for offset, values in ((8, (0, 98)), (16, (0,)), (24, (0, 3, 5)),
                               (48, (0, checker.fnv(self.packet) ^ 1)), (56, (1, 0xffffffff)),
                               (60, (0, 29, 60))):
            fmt = '<Q' if offset < 56 else '<I'
            for value in values:
                raw = bytearray(self.raw)
                struct.pack_into(fmt, raw, offset, value)
                with self.subTest(offset=offset, value=value), self.assertRaises(ValueError):
                    self.decode(raw=bytes(raw))

    def test_before_generation_and_exact_increment_cannot_wrap_or_skip(self):
        for offset, values in ((32, (0, 22, 24, 2**64 - 1)), (40, (0, 23, 25, 2**64 - 1))):
            for value in values:
                raw = bytearray(self.raw)
                struct.pack_into('<Q', raw, offset, value)
                with self.subTest(offset=offset, value=value), self.assertRaises(ValueError):
                    self.decode(raw=bytes(raw))
        for generation in (0, 2**64 - 1):
            prior = bytearray(self.prior)
            struct.pack_into('<Q', prior, 56, generation)
            prior = bytes(prior)
            with self.subTest(generation=generation), self.assertRaises(ValueError):
                self.decode(raw=self.receipt(self.packet, prior), prior=prior)

    def test_prior_uninitialized_pending_stream_and_reserved_states_refuse_even_if_echoed(self):
        for prior in (b'', self.prior[:-1], self.prior + b'\0'):
            with self.subTest(bytes=len(prior)), self.assertRaises(ValueError):
                self.decode(prior=prior)
        for fmt, offset, values in (('I', 0, (0, 2)), ('I', 4, (0, 14)), ('Q', 48, (0, 98)),
                ('Q', 64, (0,)), ('I', 104, (1,)), ('I', 108, (1, 2, 3)),
                ('Q', 112, (0,)), ('Q', 120, (1,))):
            for value in values:
                prior = bytearray(self.prior)
                struct.pack_into('<' + fmt, prior, offset, value)
                prior = bytes(prior)
                with self.subTest(offset=offset, value=value), self.assertRaises(ValueError):
                    self.decode(raw=self.receipt(self.packet, prior), prior=prior)

    def test_every_after_state_byte_is_bound_including_config_fps_frame_and_counters(self):
        for offset in range(128):
            raw = bytearray(self.raw)
            raw[64 + offset] ^= 1
            with self.subTest(after_state_byte=offset), self.assertRaises(ValueError):
                self.decode(raw=bytes(raw))
        raw = bytearray(self.raw)
        struct.pack_into('<I', raw, 60, 60)
        struct.pack_into('<I', raw, 80, 60)
        with self.assertRaises(ValueError):
            self.decode(raw=bytes(raw))

    def test_policy_is_typed_complete_on_both_sides_and_optional_for_old_history(self):
        profile = CPParameterBankEvidenceTests.profile()
        self.assertTrue(checker.check_profile(profile)['verified'])
        self.assertIs(profile['functional_camera_capture_verified'], False)
        self.assertIs(profile['functional_camera_cp_crank_control_physical_semantics_verified'], False)
        for key, value in checker.CP_CRANK_CONTROL_POLICY.items():
            self.assertTrue(checker.typed_equal(profile['functional_camera_' + key], value))
            self.assertTrue(checker.typed_equal(profile['backup_transport']['functional_camera_' + key], value))
        legacy = copy.deepcopy(profile)
        for target in (legacy, legacy['backup_transport']):
            for key in checker.CP_CRANK_CONTROL_POLICY:
                del target['functional_camera_' + key]
        self.assertTrue(checker.check_profile(legacy)['verified'])
        for key, value in checker.CP_CRANK_CONTROL_POLICY.items():
            wrong = True if type(value) is int or type(value) is bool else [0, 1] if type(value) is list else value + ' '
            for side in ('top', 'backup_transport', 'both'):
                for mutation in ('wrong', 'missing', 'partial'):
                    changed = copy.deepcopy(legacy if mutation == 'partial' else profile)
                    targets = (changed, changed['backup_transport']) if side == 'both' else (
                        changed if side == 'top' else changed['backup_transport'],)
                    for target in targets:
                        if mutation == 'missing':
                            del target['functional_camera_' + key]
                        else:
                            target['functional_camera_' + key] = copy.deepcopy(value if mutation == 'partial' else wrong)
                    with self.subTest(key=key, side=side, mutation=mutation), self.assertRaises(ValueError):
                        checker.check_profile(changed)
        for field in ('cp_crank_control_mode1_supported', 'cp_crank_control_physical_layout'):
            for side in ('top', 'backup_transport'):
                changed = copy.deepcopy(legacy)
                target = changed if side == 'top' else changed['backup_transport']
                target['functional_camera_' + field] = True
                with self.subTest(undeclared=field, side=side), self.assertRaises(ValueError):
                    checker.check_profile(changed)


class CPCrankControlTransportEvidenceTests(unittest.TestCase):
    """HOST_TEST retained files and broker witnesses; native completion stays pending."""

    @classmethod
    def setUpClass(cls):
        CPParameterBankEvidenceTests.setUpClass()

    def setUp(self):
        bank = CPParameterBankTransportEvidenceTests('runTest')
        bank.setUp()
        self.addCleanup(bank.doCleanups)
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.packet = CPCrankControlEvidenceTests.request()
        self.prior = bank.following
        self.receipt = CPCrankControlEvidenceTests.receipt(self.packet, self.prior, bank_generation=1, crank_generation=1)
        self.following = self.receipt[64:192]
        self.origin = dict(producer_tid=94, source=0x80020002, destination=0x90030001,
                           command=0x409d, bytes=12, fnv1a64=checker.fnv(self.packet))
        operations = [dict(op=tx['opcode'], data=checker.payload_read(bank.run, tx['request_payload']),
            output=checker.transfer_output(bank.run, tx), origin=copy.deepcopy(tx['origin']))
            for tx in bank.transport['transfers']]
        operations += [dict(op=2, data=b'', output=self.prior, origin=self.origin),
                       dict(op=21, data=self.packet, output=self.receipt, origin=self.origin),
                       dict(op=2, data=b'', output=self.following, origin=self.origin)]
        lines, count = [], 0
        for line in (bank.run / 'console.log').read_text().splitlines():
            if line.startswith('OBS FUNCTIONAL_CAMERA_TRANSFER '):
                lines.append('HOST_TEST_TRANSFER_' + str(count))
                count += 1
            else:
                lines.append(line)
        lines += ['HOST_TEST_TRANSFER_' + str(index) for index in range(count, len(operations))]
        self.args = host_test_transport(Path(temporary.name), operations, '\n'.join(lines) + '\n')
        self.run, self.manifest, self.rows, events, build = self.args
        policy = {'functional_camera_' + key: copy.deepcopy(value) for key, value in
                  {**checker.CP_PARAMETER_BANK_POLICY, **checker.CP_CRANK_CONTROL_POLICY}.items()}
        policy['functional_camera_profile'] = checker.PROFILE
        self.manifest.update(policy)
        self.manifest['backup_transport'].update(copy.deepcopy(policy))
        for op in (20, 21):
            core = next(event for event in events if event['kind'] == 'core_result' and event['opcode'] == op)
            observed = (copy.deepcopy(bank.transport['transfers'][2]['parameter_bank']['observation']) if op == 20 else
                dict(actual_c_result=0, returned_hex=self.receipt.hex(), readback_verified=True,
                    model_called=True, model_committed=True, request_hex=self.packet.hex(),
                    before_state_c_result=0, before_state_hex=self.prior.hex(),
                    result=dict(token=0, total=0, offset=0, used=208),
                    output_buffer_hex=(self.receipt + bytes(checker.DATA_BYTES - 208)).hex(),
                    after_state_c_result=0, after_state_hex=self.following.hex(), query_c_result=0,
                    crank_generation=1, bank_generation=1, snapshot_hex=self.receipt.hex()))
            witness = dict(kind='model_parameter_bank' if op == 20 else 'model_crank_control', model_instance=99,
                sequence=core['sequence'], opcode=op, origin=copy.deepcopy(core['origin']),
                actual_c_result=0, actual_core_sha256=build['model_sha256'], request_payload=core['request_payload'],
                output_payload=core['output_payload'], native_acceptance=False, observation=observed)
            if op == 21:
                witness.update(model_called=True, model_committed=True)
            events.insert(events.index(core) + 1, witness)
            for event in events:
                if event.get('opcode') == op and event['kind'] in ('core_result', 'response'):
                    event['actual_core_sha256'] = build['model_sha256']
        self.persist(self.args)
        transfers = []
        for row in self.rows:
            if row['tag'] != 'FUNCTIONAL_CAMERA_TRANSFER':
                continue
            seq = int(row['fields']['seq'].split('..')[0])
            request = next(event for event in events if event['kind'] == 'request' and event['sequence'] == seq)
            core = next(event for event in events if event['kind'] == 'core_result' and event['sequence'] == seq)
            reference = core['output_payload']
            tx = dict(line=row['line'], first=seq, last=seq, opcode=request['opcode'], origin=request['origin'],
                bytes=reference['bytes'], sha256=reference['sha256'], fnv1a64=f'{reference["fnv1a64"]:016x}',
                request_payload=request['request_payload'], output_payloads=[reference], token=0, frame=None,
                model_instance=99, provider_kind='core')
            if request['opcode'] in (20, 21):
                key = 'parameter_bank' if request['opcode'] == 20 else 'crank_control'
                tx[key] = next(event for event in events if event['kind'] == 'model_' + key)
                if request['opcode'] == 21:
                    tx['capacity'] = checker.DATA_BYTES
            transfers.append(tx)
        self.transport = dict(pid=77, model_instance=99, owner_pid=177, transfers=transfers)
        self.transport['parameter_bank'] = checker.check_cp_parameter_bank(self.run, self.manifest, self.rows, self.transport)

    persist = staticmethod(CPParameterBankTransportEvidenceTests.persist_broker)

    @staticmethod
    def witness(args):
        return next(event for event in args[3] if event['kind'] == 'model_crank_control')

    def content(self, transport=None, manifest=None):
        return checker.check_cp_crank_control_content(self.run,
            self.manifest if manifest is None else manifest, self.rows,
            self.transport if transport is None else transport)

    def test_actual_bank1_live23_crank1_state24_content_is_not_native_or_capture_success(self):
        transport = checker.check_transport(*self.args)
        result = transport['crank_control_content']
        self.assertEqual(result, self.content())
        self.assertTrue(result['required'] and result['content_join_verified'])
        self.assertTrue(transport['parameter_bank']['verified'])
        self.assertFalse(transport['verified'])
        self.assertTrue(all(result[key] is False for key in ('verified', 'native_completion_verified',
            'frame_consumed', 'capture_verified', 'physical_asic_compatibility_verified')))
        self.assertEqual(result['missing_native_observations'], list(checker.CP_CRANK_NATIVE_JOINS))
        self.assertEqual([tx['opcode'] for tx in transport['transfers']], [1, 2, 20, 2, 2, 21, 2])
        value, = result['transactions']
        self.assertEqual((value['bank_generation'], value['crank_generation'], value['before_config_generation'],
                          value['config_generation'], value['fps'], value['frame_generation']), (1, 1, 23, 24, 30, 1))
        self.assertNotEqual(self.origin['producer_tid'], transport['transfers'][2]['origin']['producer_tid'])
        self.assertIsNone(transport['transfers'][5]['frame'])

    def test_every_independent_C_status_shape_and_current_library_hash_is_required(self):
        mutations = [('actual_core_sha256', 'd' * 64), ('actual_c_result', -5), ('native_acceptance', True),
                     ('model_called', False), ('model_committed', False)]
        mutations += [('observation.' + key, wrong) for key, wrong in
            (('actual_c_result', -5), ('query_c_result', -5), ('before_state_c_result', -5),
             ('after_state_c_result', -5), ('readback_verified', False), ('model_called', False),
             ('model_committed', False), ('bank_generation', 2), ('crank_generation', 2),
             ('result', dict(token=0, total=0, offset=0, used=207)))]
        for key, wrong in mutations:
            args = copy.deepcopy(self.args)
            event = self.witness(args)
            target = event['observation'] if key.startswith('observation.') else event
            target[key.split('.')[-1]] = wrong
            self.persist(args)
            with self.subTest(field=key), self.assertRaises(ValueError):
                checker.check_transport(*args)
        for key in self.witness(self.args)['observation']:
            args = copy.deepcopy(self.args)
            del self.witness(args)['observation'][key]
            self.persist(args)
            with self.subTest(missing=key), self.assertRaises(ValueError):
                checker.check_transport(*args)
        for kind in ('core_result', 'response'):
            args = copy.deepcopy(self.args)
            event = next(event for event in args[3] if event['kind'] == kind and event.get('opcode') == 21)
            event['actual_core_sha256'] = 'd' * 64
            self.persist(args)
            with self.subTest(stale_hash=kind), self.assertRaises(ValueError):
                checker.check_transport(*args)

    def test_full208_query_request12_state128_and_output_buffer_are_compared_as_bytes(self):
        observed = self.witness(self.args)['observation']
        for key in ('returned_hex', 'snapshot_hex', 'request_hex', 'before_state_hex', 'after_state_hex', 'output_buffer_hex'):
            for mutation in ('truncated', 'different'):
                args = copy.deepcopy(self.args)
                raw = bytearray.fromhex(observed[key])
                if mutation == 'truncated':
                    raw.pop()
                else:
                    raw[-1] ^= 1
                self.witness(args)['observation'][key] = raw.hex()
                self.persist(args)
                with self.subTest(field=key, mutation=mutation), self.assertRaises(ValueError):
                    checker.check_transport(*args)
        args = copy.deepcopy(self.args)
        prior = bytearray(self.prior)
        struct.pack_into('<Q', prior, 96, 64)
        raw = CPCrankControlEvidenceTests.receipt(self.packet, bytes(prior), 1, 1)
        event = self.witness(args)
        event['observation'].update(before_state_hex=prior.hex(), returned_hex=raw.hex(), snapshot_hex=raw.hex(),
            after_state_hex=raw[64:192].hex(), output_buffer_hex=(raw + bytes(checker.DATA_BYTES - 208)).hex())
        self.persist(args)
        with self.assertRaises(ValueError):
            checker.check_transport(*args)

    def test_model_witness_cannot_be_missing_replayed_late_wrong_opcode_or_foreign_origin(self):
        for mutation in ('missing', 'duplicate', 'late', 'opcode', 'origin', 'request', 'output'):
            args = copy.deepcopy(self.args)
            events, event = args[3], self.witness(args)
            index = events.index(event)
            if mutation == 'missing':
                events.remove(event)
            elif mutation == 'duplicate':
                events.insert(index, copy.deepcopy(event))
            elif mutation == 'late':
                events[index], events[index + 1] = events[index + 1], events[index]
            elif mutation == 'opcode':
                event['opcode'] = 11
            elif mutation == 'origin':
                event['origin']['producer_tid'] += 1
            else:
                key = mutation + '_payload'
                event[key] = copy.deepcopy(event[key])
                event[key]['sequence'] += 1
            self.persist(args)
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                checker.check_transport(*args)

    def test_bracketing_STATE2_origin_provider_frame_and_full_bytes_cannot_be_borrowed(self):
        for index in (4, 5, 6):
            for key, wrong in (('token', 1), ('frame', {'proof': {'opcode': 21}}), ('provider_kind', 'source')):
                changed = copy.deepcopy(self.transport)
                changed['transfers'][index][key] = wrong
                with self.subTest(index=index, field=key), self.assertRaises(ValueError):
                    self.content(transport=changed)
        for index in (4, 6):
            for key, wrong in (('opcode', 1), ('first', 90), ('last', 90)):
                changed = copy.deepcopy(self.transport)
                changed['transfers'][index][key] = wrong
                with self.subTest(index=index, field=key), self.assertRaises(ValueError):
                    self.content(transport=changed)
            changed = copy.deepcopy(self.transport)
            changed['transfers'][index]['origin']['producer_tid'] ^= 1
            with self.subTest(foreign_STATE=index), self.assertRaises(ValueError):
                self.content(transport=changed)
        changed = copy.deepcopy(self.transport)
        for key in ('output_payloads', 'bytes', 'sha256', 'fnv1a64'):
            changed['transfers'][6][key] = copy.deepcopy(changed['transfers'][4][key])
        with self.assertRaises(ValueError):
            self.content(transport=changed)

    def test_no_frame_binding_rejects_incomplete_proofs_before_history_scan(self):
        frames = ({}, {'proof': {}}, {'proof': {'opcode': 21}},
                  {'proof': {'opcode': 21, 'render_observed': 0}})
        for index in (4, 5, 6):
            for frame in frames:
                changed = copy.deepcopy(self.transport)
                changed['transfers'][index]['frame'] = copy.deepcopy(frame)
                with self.subTest(index=index, frame=frame), self.assertRaisesRegex(ValueError,
                        'crank control queries/core/no-frame binding differs'):
                    self.content(transport=changed)

    def test_same_generation_full_before_and_after_STATE_fields_cannot_diverge_from_receipt(self):
        original = checker.transfer_output
        for index, state in ((4, self.prior), (6, self.following)):
            for offset in (8, 16, 24, 64, 72, 80, 88, 96, 112):
                raw = bytearray(state)
                raw[offset] ^= 1
                raw = bytes(raw)
                sequence = self.transport['transfers'][index]['first']
                def output(run, tx):
                    return raw if tx['first'] == sequence else original(run, tx)
                with mock.patch.object(checker, 'transfer_output', side_effect=output):
                    with self.subTest(STATE=index, byte=offset), self.assertRaises(ValueError):
                        self.content()

    def test_current_bank_authority_and_exact_original_CP_origin_are_required(self):
        for mutation in ('no_bank', 'not_freed', 'wrong_bank', 'wrong_instance'):
            changed = copy.deepcopy(self.transport)
            if mutation == 'no_bank':
                changed['parameter_bank']['verified'] = False
            else:
                receipt = changed['parameter_bank']['transactions'][0]
                receipt[{'not_freed': 'original_free_line', 'wrong_bank': 'bank_generation',
                         'wrong_instance': 'model_instance'}[mutation]] = 999
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                self.content(transport=changed)
        for key in ('source', 'destination', 'command', 'bytes', 'fnv1a64'):
            changed = copy.deepcopy(self.transport)
            for index in (4, 5, 6):
                changed['transfers'][index]['origin'][key] ^= 1
            with self.subTest(origin=key), self.assertRaises(ValueError):
                self.content(transport=changed)
        for profile in ('', 'strict', checker.PROFILE + ' ', None, True):
            changed = copy.deepcopy(self.manifest)
            for target in (changed, changed['backup_transport']):
                target['functional_camera_profile'] = profile
            with self.subTest(profile=profile), self.assertRaises(ValueError):
                self.content(manifest=changed)
        for key in checker.CP_CRANK_CONTROL_POLICY:
            changed = copy.deepcopy(self.manifest)
            del changed['backup_transport']['functional_camera_' + key]
            with self.subTest(policy=key), self.assertRaises(ValueError):
                self.content(manifest=changed)
        changed = copy.deepcopy(self.manifest)
        for target in (changed, changed['backup_transport']):
            target['functional_camera_cp_crank_control_mode1_supported'] = True
        with self.assertRaises(ValueError):
            self.content(manifest=changed)

    def test_history_binds_to_decoded_bank_not_arbitrary_nonzero_generation_and_never_model_frame(self):
        original = checker.transfer_output
        crank = self.transport['transfers'][5]
        for bank, generation in ((2, 1), (1, 2), (1, 0)):
            raw = CPCrankControlEvidenceTests.receipt(self.packet, self.prior, bank, generation)
            def output(run, tx):
                return raw if tx['first'] == crank['first'] else original(run, tx)
            with mock.patch.object(checker, 'transfer_output', side_effect=output):
                with self.subTest(bank=bank, crank=generation), self.assertRaises(ValueError):
                    checker.vdf_history(self.run, self.transport)
        changed = copy.deepcopy(self.transport)
        duplicate = copy.deepcopy(changed['transfers'][5])
        duplicate['first'] = duplicate['last'] = 8
        changed['transfers'].append(duplicate)
        raw = CPCrankControlEvidenceTests.receipt(self.packet, self.following, 1, 2)
        with mock.patch.object(checker, 'transfer_output', side_effect=lambda run, tx:
                               raw if tx['first'] == 8 else original(run, tx)):
            with self.assertRaisesRegex(ValueError, 'once-only'):
                checker.vdf_history(self.run, changed)
        args = copy.deepcopy(self.args)
        event = copy.deepcopy(self.witness(args))
        event['kind'], event['proof'] = 'model_frame', {'opcode': 21}
        args[3].insert(args[3].index(self.witness(args)) + 1, event)
        self.persist(args)
        with self.assertRaises(ValueError):
            checker.check_transport(*args)

    def test_new_decoded_bank2_authorizes_monotonic_crank2_with_its_active_fps(self):
        wire = CPParameterBankEvidenceTests('runTest')
        wire.setUp()
        packet = wire.original_packet(fps=60)
        bank_raw = wire.result(packet, self.following, bank_generation=2)
        crank_raw = CPCrankControlEvidenceTests.receipt(self.packet, bank_raw[64:192], 2, 2)
        changed = copy.deepcopy(self.transport)
        bank_tx = copy.deepcopy(changed['transfers'][2])
        bank_tx.update(first=8, last=8)
        before = copy.deepcopy(changed['transfers'][6])
        before.update(first=9, last=9)
        crank_tx = copy.deepcopy(changed['transfers'][5])
        crank_tx.update(first=10, last=10)
        after = copy.deepcopy(changed['transfers'][6])
        after.update(first=11, last=11)
        changed['transfers'] += [bank_tx, before, crank_tx, after]
        outputs = {8: bank_raw, 9: bank_raw[64:192], 10: crank_raw, 11: crank_raw[64:192]}
        original_output, original_input = checker.transfer_output, checker.payload_read
        def output(run, tx):
            return outputs[tx['first']] if tx['first'] in outputs else original_output(run, tx)
        def incoming(run, reference, *args):
            return packet if reference is bank_tx['request_payload'] else original_input(run, reference, *args)
        with mock.patch.object(checker, 'transfer_output', side_effect=output), \
                mock.patch.object(checker, 'payload_read', side_effect=incoming):
            history = checker.vdf_history(self.run, changed)
        self.assertEqual((history[10]['bank_generation'], history[10]['crank_generation'], history[10]['fps'],
                          history[10]['before_config_generation'], history[10]['config_generation']), (2, 2, 60, 25, 26))
        self.assertEqual(history[10]['frame_generation'], 1)

    def test_rejection_keeps_actual_negative_rc_or_postcommit_C0_and_original208(self):
        for actual_rc in (-5, 0):
            args = copy.deepcopy(self.args)
            event = self.witness(args)
            core = next(item for item in args[3] if item['kind'] == 'core_result' and item.get('opcode') == 21)
            core['actual_c_result'] = actual_rc
            event.update(kind='crank_control_rejected', actual_c_result=actual_rc,
                         model_committed=actual_rc == 0, error='actual query rejected after call')
            event['observation'].update(actual_c_result=actual_rc, model_committed=actual_rc == 0,
                                        query_c_result=-5, readback_verified=False)
            self.persist(args)
            original = copy.deepcopy(event)
            with self.subTest(actual_C_rc=actual_rc), self.assertRaises(checker.CrankControlRejected) as caught:
                checker.check_transport(*args)
            self.assertEqual(caught.exception.event, original)
            self.assertEqual(caught.exception.event['actual_c_result'], actual_rc)
            self.assertEqual(checker.payload_read(self.run, caught.exception.event['output_payload']), self.receipt)
            self.assertEqual(caught.exception.event['observation']['returned_hex'], self.receipt.hex())
            self.assertEqual(event, original)
        args = copy.deepcopy(self.args)
        event = self.witness(args)
        event.update(kind='crank_control_rejected', actual_c_result=0, error='actual getter refused')
        event['observation'].update(query_c_result=-5, readback_verified=False)
        core = next(item for item in args[3] if item['kind'] == 'core_result' and item.get('opcode') == 21)
        args[3].remove(event)
        args[3].insert(args[3].index(core), event)
        self.persist(args)
        with self.assertRaises(checker.CrankControlRejected) as caught:
            checker.check_transport(*args)
        self.assertEqual(caught.exception.event, event)
        self.assertEqual(caught.exception.event['actual_c_result'], 0)


class CPCrankNativeJoinEvidenceTests(unittest.TestCase):
    """Synthetic complete producer streams; these fixtures never attest native capture."""

    @classmethod
    def setUpClass(cls):
        CPCrankControlTransportEvidenceTests.setUpClass()

    def setUp(self):
        baseline = CPCrankControlTransportEvidenceTests('runTest')
        baseline.setUp()
        self.addCleanup(baseline.doCleanups)
        self.args = baseline.args
        self.run, self.manifest, self.rows, _, _ = self.args
        self.packet, self.prior, self.receipt, self.following = (
            baseline.packet, baseline.prior, baseline.receipt, baseline.following)
        self.transport = copy.deepcopy(baseline.transport)
        self.base_rows = copy.deepcopy(self.rows)
        self.assemble('normal')

    record = staticmethod(CPParameterBankTransportEvidenceTests.record)

    @staticmethod
    def row(tag, fields):
        return dict(tag=tag, fields={k: str(v) for k, v in fields.items()})

    def audit(self, raw, pointer, sequence):
        return [self.row('NATIVE_CP_BACKGROUND_INPUT_AUDIT', dict(pid=77, tid=94, sequence=sequence,
            entry='async', pointer=pointer, destination='0x90030001', bytes=len(raw), source='0x80020002',
            size_known=1, source_known=1, bytes_complete=1, complete=1, producer_return='0x7f29174a68',
            consumed=0, state_verified=0, capture_verified=0)),
            self.row('NATIVE_CP_BACKGROUND_INPUT_AUDIT_BYTES', dict(pid=77, tid=94, sequence=sequence,
                offset=0, bytes=len(raw), raw=raw.hex()))]

    def strict_history(self):
        wire = bytes.fromhex('05009d404400008000000000')
        ack = b'\x01\0\x9d\x40' + wire[4:8] + struct.pack('<I', 0xf000)
        digest = 2166136261
        for byte in wire:
            digest = ((digest ^ byte) * 16777619) & 0xffffffff
        f = dict(pid=77, opcode='0x409d', sender_tid=87, waiter_tid=0, attempts=1, requests=1,
            busy=1, guard=1, faults=0, source='0x80020002', request_destination='0x90030001',
            destination='0x80020002', bytes=12, request=wire.hex(), cookie='0x80000044', wire_fnv1a32=hex(digest),
            source_byte1_known=0, reply=ack.hex(), freed_reply='none', reply_free_destination=0,
            reply_free_source=0, reply_free_bytes=0, allocate_rc=0, send_rc=0, request_free_rc=0,
            reply_free_rc=0, queued=1, request_freed=1, reply_freed=0, clean_completion=0, ap_consumed=0,
            oneway=0, oneway_consumed=0, virtual_field_mask='0xf', virtual_fields_readback=1,
            virtual_fields_consumed='0xf', virtual_fields='0,0,0,0', virtual_readback='0,0,0,0',
            retained_request='(nil)', live_reply='0x380000', retained_cleanup='(nil)', diagnostic_only=1,
            virtual_padding=1, business_applied=0, source_dependencies_closed=0, configured=0,
            published=0, generation=0, native_cp=0, EE=0, frame=0, capture=0)
        result = [self.row('NATIVE_CP_EE_DIAGNOSTIC_REQUEST_FREE', f)]
        f.update(busy=0, guard=0)
        result.append(self.row('NATIVE_CP_EE_DIAGNOSTIC_COMPLETE', f))
        f.update(waiter_tid=87, freed_reply=ack.hex(), reply_free_destination='0x80020002',
            reply_free_source='0x90030001', reply_free_bytes=12, reply_freed=1, clean_completion=1,
            ap_consumed=1, live_reply='(nil)')
        result.append(self.row('NATIVE_CP_EE_DIAGNOSTIC_REPLY_FREE', f))
        return result

    def all13_frees(self):
        rows = []
        for index, tag in enumerate(checker.BACKGROUND_FREE_TAGS):
            f = dict(pid=77, tid=88, destination='0x81020027', expected='0x81020027', bytes=56,
                     rc=0, faults=0, ap_consumed=1, capture_verified=0)
            f['reply' if tag.endswith('_NATIVE_REPLY_FREE') else 'pointer'] = hex(0x200000 + 0x100 * index)
            if tag.endswith('_NATIVE_REPLY_FREE') or tag in ('FULL_VEF_PINMEM_CONTROL_CONNECT_REPLY_FREE',
                                                           'FULL_ADF_HDMI_AUDIO_CONNECT_REPLY_FREE'):
                f.update(sender=88, waiter=1)
            if tag.endswith('_NATIVE_REPLY_FREE'):
                f['command'] = '0x8001'
            else:
                if tag != 'FULL_ADF_HDMI_AUDIO_CONNECT_REPLY_FREE':
                    f['frames_verified'] = 0
                if tag == 'FULL_IMAGING_ADF_CONNECT_REPLY_FREE':
                    f['pcm_verified'] = 0
            if tag == 'FULL_PINMEM_HDMI_VIDEO_CONNECT_NATIVE_REPLY_FREE':
                f['producer_tid'] = 89
            rows.append(self.row(tag, f))
        return rows

    def assemble(self, variant):
        rows = self.all13_frees() + self.strict_history()
        rows += [copy.deepcopy(r) for r in self.base_rows if not
                 (r['tag'] == 'FUNCTIONAL_CAMERA_TRANSFER' and int(r['fields']['seq'].split('..')[0]) >= 5)]
        mode = next(r['fields'] for r in reversed(rows) if r['tag'] == 'FUNCTIONAL_CAMERA_CONTROL_COMMIT')
        mode = dict(mode, cycle_id='2', cycle_generation=mode['config_generation'])
        for index in range(5):
            request = index in (0, 2)
            complete = str(int(index == 4))
            fields = dict(mode, index=str(index), role=str(1 if request else 3 if index == 4 else 2),
                          bytes=str((24, 16, 12, 12, 1748)[index]),
                          source='0x80020002' if request else '0x90030001',
                          destination='0x90030001' if request else '0x80020002',
                          lease_cycle_id='0' if index < 2 else mode['cycle_id'],
                          queued=str(int(not request)), received=str(int(not request)),
                          freed='1', consumed=str(int(not request)), retained='(nil)',
                          receiver_tid='0' if request else mode['receiver_tid'],
                          tid=mode['receiver_tid'] if index == 4 else mode['sender_tid'],
                          free_tid=mode['receiver_tid'] if index == 4 else mode['sender_tid'],
                          busy=str(int(request)), guard=str(int(request)), mode_complete=complete,
                          mode0_complete=complete, mode0_cycles_completed=complete,
                          notification_AP_consumed=complete)
            rows.append(self.row('FUNCTIONAL_CAMERA_CONTROL_AP_FREE' if index in (1, 3, 4) else
                                 'FUNCTIONAL_CAMERA_CONTROL_OWNED_FREE', fields))
            if index == 2:
                # The current mode COMMIT precedes its ACK/notice frees; it is not the old start COMMIT.
                commit = dict(fields, index='3', role='2', source='0x90030001', destination='0x80020002',
                              tid=mode['sender_tid'], receiver_tid='0', free_tid='0', queued='1', received='0',
                              freed='0', consumed='0', retained='0x490000', busy='0', guard='0')
                rows.append(self.row('FUNCTIONAL_CAMERA_CONTROL_COMMIT', commit))
        bank_packet = checker.payload_read(self.run, self.transport['transfers'][2]['request_payload'])
        policy = b'\x05\0\xf9\x40' + bank_packet[4:8] + bytes(12)
        rows += self.audit(policy, '0x480000', 70)
        rows.append(self.row('NATIVE_CP_OUTPUT_POLICY_CONSUMED', dict(pid=77, tid=94, bytes=20, slots=0,
            copied_readback=1, config_fields=4, known_mask=15, wire_fnv1a=f'{checker.fnv(policy):016x}',
            request_free_rc=0, request_retained=0, stage_only=1, semantic_applied=0, semantic_slots=0,
            generation_advanced=0, published=0, ACK_sent=0, original_CP_executed=0, EE_verified=0, capture_verified=0)))
        rows += self.audit(self.packet, '0x500000', 71)
        rows.append(self.row('NATIVE_CP302C_NOCONVERT_ALL13_READBACK', dict(pid=77, tid=94,
            accepted=1, video_AP_consumed=1, OSD_AP_consumed=1, audio_AP_consumed=1,
            OSD_live=16, OSD_owners_each=2, OSD_opens_each=2, global_DMM_idle_claimed=0, capture_verified=0)))
        resources = checker.parse_console(JFZ_VDF_RESOURCE_OBS.encode())
        for row in resources:
            row['tag'] = row['tag'].replace('FUNCTIONAL_VDF_PATH', 'FUNCTIONAL_CP_CRANK_CONTROL')
            row['fields']['tid'] = '94'
            if 'pid' in row['fields']:
                row['fields']['pid'] = '77'
        stages = ['BEGIN', 'BEFORE', 'MODEL', 'AFTER', 'VERIFIED', 'REPLY', 'ALLOCATED']
        if variant == 'inline':
            stages += ['RECEIVE', 'REPLY_FREE', 'SENT', 'REQUEST_FREE', 'COMMIT']
        elif variant == 'request_free_receive':
            stages += ['SENT', 'RECEIVE', 'REQUEST_FREE', 'COMMIT', 'REPLY_FREE']
        else:
            stages += ['SENT', 'REQUEST_FREE', 'COMMIT', 'RECEIVE', 'REPLY_FREE']
        fields = {}
        for part in checker.CP_CRANK_EVENT_SCHEMA.split():
            key, grammar = part.split(':', 1)
            fields[key] = '(nil)' if grammar == 'pointer' else '0000000000000000' if grammar == 'digest' else (
                grammar if grammar not in ('crank_event', 'pid', 'tid', 'u64', 'u32', 'hex32', 'i32', 'bit') else '0')
        fields.update(pid='77', tid='94', sender_tid='94', transaction='1', requests='1', busy='1', source='0x80020002',
            destination='0x90030001', command='0x409d', bytes='12', native_fnv1a=f'{checker.fnv(self.packet):016x}',
            cookie=hex(struct.unpack_from('<I', self.packet, 4)[0]), request_pointer='0x500000', model_instance='99',
            bank_generation='1', bank_transaction='2', bank_commits='1', bank_released='1', bank_source='0x80020002',
            bank_destination='0x90030001', bank_command='0x4063', bank_bytes='2564', bank_native_fnv1a=f'{checker.fnv(bank_packet):016x}')
        for key in ('before_rc', 'model_rc', 'after_rc', 'allocate_rc', 'send_rc', 'request_free_rc', 'reply_free_rc', 'receive_rc'):
            fields[key] = '-61'
        reply = b'\x01\0\x9d\x40' + self.packet[4:8] + struct.pack('<I', 0xf000)
        streams = dict(BEGIN=('request', self.packet), BEFORE=('before_state', self.prior),
            MODEL=('receipt', self.receipt), AFTER=('after_state', self.following), REPLY=('reply', reply))
        transfers = {int(r['fields']['seq'].split('..')[0]): copy.deepcopy(r) for r in self.base_rows
                     if r['tag'] == 'FUNCTIONAL_CAMERA_TRANSFER'}
        for event in stages:
            fields['event'] = event
            fields['tid'] = '95' if event == 'RECEIVE' else '94'
            if event in ('BEFORE', 'MODEL', 'AFTER'):
                rows.append(transfers[{'BEFORE': 5, 'MODEL': 6, 'AFTER': 7}[event]])
            if event == 'BEFORE':
                fields.update(guard='1', before_rc='0', before_config_generation='23', frame_generation='1', fps='30',
                    before_used='128', before_required='128', before_instance='99')
            elif event == 'MODEL':
                fields.update(model_called='1', model_committed='1', model_rc='0', commits='1', crank_generation='1',
                    config_generation='24', crank_used='208', crank_required='208', crank_instance='99',
                    receipt_fnv1a=f'{checker.fnv(self.receipt):016x}')
            elif event == 'AFTER':
                fields.update(after_rc='0', after_used='128', after_required='128', after_instance='99')
            elif event == 'VERIFIED':
                fields.update(verified='1', owned='1', verified_commits='1', last_bank_generation='1',
                    last_crank_generation='1', retained_request='0x500000')
            elif event == 'REPLY':
                fields['reply_fnv1a'] = f'{checker.fnv(reply):016x}'
            elif event == 'ALLOCATED':
                fields.update(reply_pointer='0x600000', allocation_pointer='0x600000', retained_reply='0x600000',
                    reply_allocated='1', reply_valid='1', allocate_rc='0')
            elif event == 'SENT':
                fields.update(send_started='1', send_inflight='0', send_rc='0', ACK_sent='1')
            elif event == 'REQUEST_FREE':
                fields.update(request_releasing='0', request_freed='1', request_free_rc='0',
                    request_free_tid='94', retained_request='(nil)')
            elif event == 'COMMIT':
                fields.update(busy='0', guard='0')
            elif event == 'RECEIVE':
                fields.update(reply_received='1', receive_rc='0', receiver_tid='95', send_started='1')
                if variant == 'inline':
                    fields['send_inflight'] = '1'
                if variant == 'request_free_receive':
                    fields['request_releasing'] = '1'
            elif event == 'REPLY_FREE':
                fields.update(reply_freed='1', reply_free_rc='0', reply_free_tid='94', retained_reply='(nil)')
            fields['reply_consumed'] = str(int(all(fields[k] == '1' for k in ('ACK_sent', 'reply_received', 'reply_freed'))))
            fields['complete'] = fields['completions'] = str(int(fields['reply_consumed'] == fields['request_freed'] == '1' and
                                                               fields['busy'] == fields['guard'] == '0'))
            rows.append(self.row('FUNCTIONAL_CP_CRANK_CONTROL_EVENT', fields))
            if event in streams:
                kind, raw = streams[event]
                for offset in range(0, len(raw), 128):
                    block = raw[offset:offset + 128]
                    rows.append(self.row('FUNCTIONAL_CP_CRANK_CONTROL_BYTES', dict(event=event, pid=77, tid=94,
                        transaction=1, kind=kind, total=len(raw), offset=offset, bytes=len(block), raw=block.hex(),
                        native_fnv1a=fields['native_fnv1a'], content_fnv1a=f'{checker.fnv(raw):016x}', model_instance=99,
                        bank_generation=1, crank_generation=fields['crank_generation'], functional_model=1,
                        original_CP=0, physical_ASIC_verified=0, capture_verified=0)))
            if event == 'BEGIN':
                rows += copy.deepcopy(resources)
        self.rows[:] = checker.parse_console(('\n'.join('OBS ' + self.record(r['tag'], r['fields']) for r in rows) + '\n').encode())
        raw = ('\n'.join('OBS ' + self.record(r['tag'], r['fields']) for r in self.rows) + '\n').encode()
        (self.run / 'console.log').write_bytes(raw)
        self.manifest['functional_camera_runtime']['console_sha256_at_close'] = checker.sha(raw)
        CPCrankControlTransportEvidenceTests.persist(self.args)
        for tx in self.transport['transfers']:
            tx['line'] = next(r['line'] for r in self.rows if r['tag'] == 'FUNCTIONAL_CAMERA_TRANSFER' and
                              int(r['fields']['seq'].split('..')[0]) == tx['first'])
        self.transport['parameter_bank'] = checker.check_cp_parameter_bank(self.run, self.manifest, self.rows, self.transport)

    def native(self, rows=None, event=None, kind=None):
        return [r for r in (self.rows if rows is None else rows) if
            (kind is None and r['tag'] == 'FUNCTIONAL_CP_CRANK_CONTROL_EVENT' and (event is None or r['fields']['event'] == event)) or
            (kind is not None and r['tag'] == 'FUNCTIONAL_CP_CRANK_CONTROL_BYTES' and r['fields']['kind'] == kind)]

    def joined(self, rows=None, transport=None):
        return checker.check_cp_crank_control_content(self.run, self.manifest,
            self.rows if rows is None else rows, self.transport if transport is None else transport)

    def test_complete_native_join_accepts_real_transport_thread_and_sender_free(self):
        result = self.joined()
        self.assertTrue(result['verified'] and result['native_completion_verified'] and result['content_join_verified'])
        self.assertEqual(result['missing_native_observations'], [])
        value, = result['transactions']
        self.assertEqual((value['transaction'], value['sender_tid'], value['receiver_tid']), (1, 94, 95))
        strict_sender = next(r['fields']['sender_tid'] for r in self.rows if r['tag'] == 'NATIVE_CP_EE_DIAGNOSTIC_REPLY_FREE')
        self.assertNotEqual(int(strict_sender), value['sender_tid'])
        self.assertEqual((value['bank_generation'], value['crank_generation'], value['fps']), (1, 1, 30))
        self.assertEqual(value['request_pointer'], '0x500000')
        self.assertEqual(value['reply_pointer'], '0x600000')
        self.assertTrue(all(result[k] is False for k in ('frame_consumed', 'capture_verified', 'physical_asic_compatibility_verified')))
        aggregate = checker.check_transport(*self.args)
        self.assertTrue(aggregate['verified'])
        self.assertEqual(aggregate['crank_control_content'], result)

    def test_sync_inline_receive_and_request_free_reentrant_receive_keep_true_roles(self):
        for variant in ('inline', 'request_free_receive', 'normal'):
            self.assemble(variant)
            result = self.joined()
            with self.subTest(variant=variant):
                self.assertTrue(result['native_completion_verified'])
                value, = result['transactions']
                self.assertNotEqual(value['sender_tid'], value['receiver_tid'])
                if variant == 'inline':
                    self.assertLess(value['reply_free_line'], self.native(event='SENT')[0]['line'])
                elif variant == 'request_free_receive':
                    self.assertEqual(self.native(event='RECEIVE')[0]['fields']['request_releasing'], '1')
                    self.assertLess(value['reply_receive_line'], value['original_free_line'])
        rows = copy.deepcopy(self.rows)
        for row in rows:
            if row['tag'] == 'NATIVE_CP_OUTPUT_POLICY_CONSUMED' or (
                    row['tag'] in ('NATIVE_CP_BACKGROUND_INPUT_AUDIT', 'NATIVE_CP_BACKGROUND_INPUT_AUDIT_BYTES') and
                    row['fields'].get('sequence') == '70'):
                row['fields']['tid'] = '96'
        self.assertEqual(self.joined(rows=rows)['transactions'][0]['output_policy_sender_tid'], 96)

    def test_every_native_stage_is_required_once_and_ordered_with_real_receive(self):
        for sample in self.native():
            for mutation in ('missing', 'duplicate', 'order'):
                rows = copy.deepcopy(self.rows)
                row = next(r for r in rows if r['tag'] == sample['tag'] and r['fields']['event'] == sample['fields']['event'])
                if mutation == 'missing':
                    rows.remove(row)
                elif mutation == 'duplicate':
                    rows.insert(rows.index(row), copy.deepcopy(row))
                else:
                    row['line'] = (self.native(event='REPLY_FREE')[0]['line'] + 1 if row['fields']['event'] == 'BEGIN' else
                                   self.native(event='BEGIN')[0]['line'] - 1)
                with self.subTest(event=sample['fields']['event'], mutation=mutation), self.assertRaises(ValueError):
                    self.joined(rows=rows)

    def test_full_native12_128_208_128_12_streams_reject_each_byte_mutation(self):
        for kind in ('request', 'before_state', 'receipt', 'after_state', 'reply'):
            samples = self.native(kind=kind)
            for sample in samples:
                for index in range(int(sample['fields']['bytes'])):
                    rows = copy.deepcopy(self.rows)
                    row = next(r for r in rows if r['tag'] == sample['tag'] and r['fields']['kind'] == kind and
                               r['fields']['offset'] == sample['fields']['offset'])
                    raw = bytearray.fromhex(row['fields']['raw']); raw[index] ^= 1; row['fields']['raw'] = raw.hex()
                    with self.subTest(kind=kind, offset=sample['fields']['offset'], byte=index), self.assertRaises(ValueError):
                        self.joined(rows=rows)
            for mutation in ('missing', 'duplicate', 'foreign_transaction', 'offset', 'seal'):
                rows = copy.deepcopy(self.rows); row = self.native(rows, kind=kind)[-1]
                if mutation == 'missing':
                    rows.remove(row)
                elif mutation == 'duplicate':
                    rows.insert(rows.index(row), copy.deepcopy(row))
                else:
                    key, value = {'foreign_transaction': ('transaction', '2'), 'offset': ('offset', '1'),
                                  'seal': ('content_fnv1a', '0000000000000000')}[mutation]
                    row['fields'][key] = value
                with self.subTest(kind=kind, mutation=mutation), self.assertRaises(ValueError):
                    self.joined(rows=rows)

    def test_transaction_pointer_generation_bank_source_and_actual_rc_are_immutable(self):
        mutations = [('pid', '78'), ('sender_tid', '95'), ('transaction', '2'), ('request_pointer', '0x500001'),
            ('reply_pointer', '0x600001'), ('allocation_pointer', '0x600001'), ('native_fnv1a', '0000000000000000'),
            ('cookie', '0x80000061'), ('model_instance', '100'), ('bank_generation', '2'), ('crank_generation', '2'),
            ('config_generation', '25'), ('before_config_generation', '22'), ('frame_generation', '2'), ('fps', '60'),
            ('last_bank_generation', '0'), ('last_crank_generation', '0'), ('bank_transaction', '1'), ('bank_commits', '0'),
            ('bank_released', '0'), ('bank_source', '0x80020003'), ('bank_native_fnv1a', '0000000000000000'),
            ('source', '0x90030001'), ('destination', '0x80020002'), ('bytes', '11'), ('command', '0x4063'),
            ('before_rc', '-5'), ('model_rc', '-5'), ('after_rc', '-5'), ('allocate_rc', '-12'), ('send_rc', '-5'),
            ('request_free_rc', '-5'), ('reply_free_rc', '-5'), ('receive_rc', '-5'), ('error', '-5'), ('faults', '1'),
            ('busy', '1'), ('guard', '1'), ('request_releasing', '1'), ('reply_releasing', '1'), ('reply_inspecting', '1'),
            ('send_inflight', '1'), ('reply_alias', '1'), ('reply_cleanup_freed', '1'), ('complete', '0'),
            ('reply_consumed', '0'), ('request_freed', '0'), ('reply_received', '0'), ('reply_freed', '0'),
            ('reply_free_tid', '95'), ('request_free_tid', '95'), ('receiver_tid', '0'), ('retained_request', '0x500000'),
            ('retained_reply', '0x600000'), ('crank_used', '207'), ('after_instance', '100'), ('before_token', '1')]
        for key, value in mutations:
            rows = copy.deepcopy(self.rows); self.native(rows, event='REPLY_FREE')[0]['fields'][key] = value
            with self.subTest(field=key), self.assertRaises(ValueError):
                self.joined(rows=rows)
        for pointer in ('0x500000', '0x500004', '0x4ffffc'):
            rows = copy.deepcopy(self.rows)
            for row in self.native(rows):
                for key in ('reply_pointer', 'allocation_pointer', 'retained_reply'):
                    if row['fields'][key] == '0x600000':
                        row['fields'][key] = pointer
            with self.subTest(alias=pointer), self.assertRaisesRegex(ValueError, 'aliases'):
                self.joined(rows=rows)

    def test_new_transaction_cannot_borrow_old_receive_free_or_byte_ticket(self):
        for names in (('RECEIVE',), ('REPLY_FREE',), ('RECEIVE', 'REPLY_FREE')):
            rows = copy.deepcopy(self.rows)
            for name in names:
                self.native(rows, event=name)[0]['fields']['transaction'] = '2'
            with self.subTest(stolen=names), self.assertRaises(ValueError):
                self.joined(rows=rows)
        rows = [r for r in copy.deepcopy(self.rows) if not
                (r['tag'] == 'FUNCTIONAL_CP_CRANK_CONTROL_EVENT' and r['fields']['event'] == 'RECEIVE')]
        for row in self.native(rows):
            if row['fields']['event'] == 'REPLY_FREE':
                row['fields'].update(reply_received='1', receiver_tid='94', receive_rc='0', complete='1')
        with self.assertRaises(ValueError):
            self.joined(rows=rows)

    def test_resource34_needs_three_actual_preSTATE_records_not_accepted_bit(self):
        for suffix in ('RESOURCE_DEPENDENCIES', 'RESOURCES_TTS_TABLE', 'RESOURCES_RESERVED'):
            for mutation in ('missing', 'duplicate', 'late'):
                rows = copy.deepcopy(self.rows)
                row = next(r for r in rows if r['tag'] == 'FUNCTIONAL_CP_CRANK_CONTROL_' + suffix)
                if mutation == 'missing':
                    rows.remove(row)
                elif mutation == 'duplicate':
                    rows.insert(rows.index(row), copy.deepcopy(row))
                else:
                    row['line'] = self.native(event='BEFORE')[0]['line']
                with self.subTest(suffix=suffix, mutation=mutation), self.assertRaises(ValueError):
                    self.joined(rows=rows)
        for key, value in (('dmm_slots', '1/0'), ('dmm_handles', '0x8400/0x8402'), ('dmm_domain', '0'),
                ('dmm_lifecycle_changed', '1'), ('allocations', '5'), ('vef_live', '1'), ('pinmem_retained', '1'),
                ('control_faults', '1'), ('tid', '95')):
            rows = copy.deepcopy(self.rows)
            next(r for r in rows if r['tag'] == 'FUNCTIONAL_CP_CRANK_CONTROL_RESOURCES_RESERVED')['fields'][key] = value
            with self.subTest(field=key), self.assertRaises(ValueError):
                self.joined(rows=rows)
        for offset in (0, 0x18, 0x20, 0x48, 0x60, 0x68):
            rows = copy.deepcopy(self.rows)
            fields = next(r for r in rows if r['tag'] == 'FUNCTIONAL_CP_CRANK_CONTROL_RESOURCES_TTS_TABLE')['fields']
            raw = bytearray.fromhex(fields['raw_before']); raw[offset] ^= 1
            fields['raw_before'] = fields['raw_after'] = raw.hex()
            with self.subTest(full_TTS_offset=offset), self.assertRaises(ValueError):
                self.joined(rows=rows)

    def test_all13_mode_bank_strict_history_and_late40f9_each_need_content(self):
        cases = [(tag, 'rc', '-5') for tag in checker.BACKGROUND_FREE_TAGS]
        cases += [('NATIVE_CP302C_NOCONVERT_ALL13_READBACK', 'video_AP_consumed', '0'),
            ('FUNCTIONAL_CAMERA_CONTROL_AP_FREE', 'mode_complete', '0'),
            ('FUNCTIONAL_CAMERA_CONTROL_AP_FREE', 'free_tid', '94'),
            ('NATIVE_CP_EE_DIAGNOSTIC_REPLY_FREE', 'attempts', '2'),
            ('NATIVE_CP_EE_DIAGNOSTIC_REPLY_FREE', 'waiter_tid', '94'),
            ('NATIVE_CP_EE_DIAGNOSTIC_REPLY_FREE', 'freed_reply', bytes(12).hex()),
            ('NATIVE_CP_OUTPUT_POLICY_CONSUMED', 'request_free_rc', '-5'),
            ('NATIVE_CP_OUTPUT_POLICY_CONSUMED', 'wire_fnv1a', '0000000000000000'),
            ('NATIVE_CP_OUTPUT_POLICY_CONSUMED', 'request_retained', '1')]
        for tag, key, value in cases:
            rows = copy.deepcopy(self.rows)
            matches = [r for r in rows if r['tag'] == tag]
            matches[-1]['fields'][key] = value
            with self.subTest(tag=tag, field=key), self.assertRaises(ValueError):
                self.joined(rows=rows)
        for tag in (*checker.BACKGROUND_FREE_TAGS, 'NATIVE_CP_EE_DIAGNOSTIC_REQUEST_FREE',
                    'NATIVE_CP_OUTPUT_POLICY_CONSUMED'):
            rows = copy.deepcopy(self.rows); rows.remove(next(r for r in rows if r['tag'] == tag))
            with self.subTest(missing=tag), self.assertRaises(ValueError):
                self.joined(rows=rows)
        for key, value in (('request_freed', '0'), ('retained', '0x400000'), ('faults', '1')):
            rows = copy.deepcopy(self.rows)
            next(r for r in rows if r['tag'] == 'FUNCTIONAL_CP_PARAMETER_BANK_EVENT' and
                 r['fields']['event'] == 'COMMIT')['fields'][key] = value
            with self.subTest(bank=key), self.assertRaises(ValueError):
                self.joined(rows=rows)
        for sequence in ('70', '71'):
            for key, value in (('source', '0x90030001'), ('producer_return', '0x35358b8'), ('complete', '0')):
                rows = copy.deepcopy(self.rows)
                next(r for r in rows if r['tag'] == 'NATIVE_CP_BACKGROUND_INPUT_AUDIT' and
                     r['fields']['sequence'] == sequence)['fields'][key] = value
                with self.subTest(audit=sequence, field=key), self.assertRaises(ValueError):
                    self.joined(rows=rows)

    def test_exact_crank_console_94_18_and_three_resource_grammars_frame_both_trailers(self):
        samples = [r for r in self.rows if r['tag'].startswith('FUNCTIONAL_CP_CRANK_CONTROL_')]
        self.assertEqual(len(self.native()[0]['fields']), 94)
        self.assertEqual(len(self.native(kind='receipt')[0]['fields']), 18)
        trailers = (b'[ 5638.875229] UDIF: cdev_ioctl() Line 100: uipc: warning ret = -1022',
                    b'[ 5541.864466] [K]**UIPC ERROR** free_dynamic_msgq_id: QID[81cf61c4] M=1 C=0 S=0 A=1')
        for sample in samples:
            payload = self.record(sample['tag'], sample['fields']).encode()
            self.assertEqual(checker.console_producer_fields(payload), sample['fields'])
            for trailer in trailers:
                for ending in (b'\n', b'\r\n'):
                    raw = b'ordinary\nOBS ' + payload + trailer + ending
                    row, = checker.parse_console(raw)
                    with self.subTest(tag=sample['tag'], event=sample['fields'].get('event'), ending=ending):
                        self.assertEqual(row['fields'], sample['fields'])
                        note = row['kernel_diagnostic']
                        self.assertEqual(note['payload']['byte_offset'], len(b'ordinary\nOBS '))
                        for part in (note, note['payload']):
                            self.assertEqual(raw[part['byte_offset']:part['byte_offset'] + part['bytes']], part['raw'].encode())
                            self.assertEqual(checker.sha(part['raw'].encode()), part['sha256'])

    def test_crank_formatter_rejects_unknown_missing_duplicate_order_type_and_widening(self):
        for tag in ('EVENT', 'BYTES', 'RESOURCE_DEPENDENCIES', 'RESOURCES_TTS_TABLE', 'RESOURCES_RESERVED'):
            sample = next(r for r in self.rows if r['tag'] == 'FUNCTIONAL_CP_CRANK_CONTROL_' + tag)
            payload = self.record(sample['tag'], sample['fields']).encode(); parts = payload.split(b' ')
            variants = [payload + b' unknown=0', b' '.join(parts[:2] + parts[3:]),
                        b' '.join(parts[:1] + [parts[2], parts[1]] + parts[3:])]
            if tag == 'EVENT':
                variants += [payload.replace(b'event=BEGIN', b'event=SUCCESS'), payload.replace(b'transaction=1', b'transaction=01'),
                             payload.replace(b'capture_verified=0', b'capture_verified=1')]
            if tag == 'BYTES':
                variants += [payload.replace(b'kind=request', b'kind=frame'), payload.replace(b'total=12', b'total=13'),
                             payload.replace(b'offset=0', b'offset=1')]
            for value in variants:
                with self.subTest(tag=tag, value=value):
                    self.assertIsNone(checker.console_producer_fields(value))
                    row, = checker.parse_console(value + b'[ 1.000000] UDIF: cdev_ioctl() Line 100: uipc: warning ret = -1022\n')
                    self.assertIn('diagnostic', row)
                    self.assertNotIn('kernel_diagnostic', row)
            with self.assertRaisesRegex(ValueError, 'duplicate JSON key'):
                checker.console_producer_fields(payload + b' ' + parts[1])

    def test_final_owner_formatter_schema_and_real_metadata_checks_match_source(self):
        source = (checker.NATIVE / 'runtime/analysis/device-models/functional-camera-control.c').read_text()
        block = source[source.index('static void crank_record('):source.index('static int crank_control_ready(')]
        formats = re.findall(r'snprintf\(text, sizeof text,\s*((?:"[^"\n]*"\s*)+)', block)
        self.assertEqual(len(formats), 2)
        for declaration, formatter, count in zip((checker.CP_CRANK_EVENT_SCHEMA, checker.CP_CRANK_BYTES_SCHEMA), formats, (94, 18)):
            text = ''.join(re.findall(r'"([^"\n]*)"', formatter))
            keys = re.findall(r'([A-Za-z_][A-Za-z_0-9]*)=', text)
            self.assertEqual(len(keys), count)
            self.assertEqual(keys, [part.split(':', 1)[0] for part in declaration.split()])
        wire = source[source.index('static int crank_wire_matches('):source.index('static int crank_context_matches(')]
        self.assertIn('bytes = io->size(pointer), actual_source = io->source(pointer)', wire)
        self.assertIn('bytes == 12 && actual_source == source', wire)
        self.assertIn('memcmp(pointer, expected, 12)', wire)
        receive = source[source.index('int native_functional_camera_crank_release('):source.index('static void crank_finish(')]
        self.assertIn('current_tid != crank_state.sender_tid', receive)
        self.assertIn('event->source != FUNCTIONAL_CAMERA_CONTROL_SID', receive)
        self.assertIn('event->bytes != 12', receive)
        self.assertIn('crank_state.receiver_tid = current_tid', receive)
        self.assertNotIn('current_tid != crank_state.sender_tid || event', receive)

    def test_main_source_binds_shared_event_tickets_and_never_clears_on_free(self):
        source = (checker.NATIVE / 'runtime/analysis/menu-observe.c').read_text()
        ticket_start = source.index('static uint64_t native_crank_ticket_for(')
        ticket_end = source.index('static void native_crank_received(', ticket_start)
        lookup = source[ticket_start:ticket_end]
        self.assertIn('pthread_mutex_lock(functional_cp_crank_control_ticket_mutex)', lookup)
        self.assertIn('functional_cp_crank_control_ticket_pid!=(unsigned int)getpid()', lookup)
        self.assertNotIn('native_functional_camera_crank_snapshot', lookup)
        receive = source[ticket_end:source.index('int osal_rcv_msg_tmo(', ticket_end)]
        self.assertIn('native_crank_ticket_for(destination,pointer),&event', receive)
        self.assertNotIn('native_functional_camera_crank_snapshot', receive)
        free_start = source.index('if(__atomic_load_n(&functional_cp_crank_control_used', source.index('int osal_free_msg('))
        free_block = source[free_start:source.index('if(__atomic_load_n(&functional_cp_parameter_bank_used', free_start)]
        self.assertIn('native_crank_ticket_for(id,message),0', free_block)
        self.assertNotIn('=0;', free_block)
        allocator = source[source.index('static void native_crank_allocated(unsigned int id,'):source.index('static void native_pin_peer_allocated(', source.index('static void native_crank_allocated(unsigned int id,'))]
        self.assertIn('result || count!=1', allocator)
        self.assertIn('functional_cp_crank_control_ticket.reply=0', allocator)
        self.assertNotRegex(source, r'_Thread_local[^;]*functional_cp_crank_control_ticket')


    def snapshot_received(self, rows, *events):
        for event in events:
            self.native(rows, event=event)[0]['fields'].update(reply_received='1', receive_rc='0', receiver_tid='95')

    def receive_logged_before(self, event):
        rows = copy.deepcopy(self.rows)
        receive = self.native(rows, event='RECEIVE')[0]
        rows.remove(receive)
        rows.insert(rows.index(self.native(rows, event=event)[0]), receive)
        for row, original in zip(rows, self.rows):
            row['line'] = original['line']
        return rows

    def assert_snapshot_interleaving_verified(self, rows):
        self.assertEqual(len(rows), len(self.rows))
        self.assertEqual({r['fields']['event'] for r in self.native(rows)},
                         {r['fields']['event'] for r in self.native()})
        result = self.joined(rows=rows)
        self.assertTrue(result['native_completion_verified'] and result['content_join_verified'])
        self.assertTrue(all(result[key] is False for key in
            ('frame_consumed', 'capture_verified', 'physical_asic_compatibility_verified')))
        self.assertEqual((result['transactions'][0]['sender_tid'], result['transactions'][0]['receiver_tid']), (94, 95))

    def test_sender_snapshots_can_observe_receive_before_its_log_line(self):
        for first in ('SENT', 'REQUEST_FREE', 'COMMIT'):
            rows = copy.deepcopy(self.rows)
            events = ('SENT', 'REQUEST_FREE', 'COMMIT')
            self.snapshot_received(rows, *events[events.index(first):])
            with self.subTest(first_received_sender_snapshot=first):
                self.assertLess(self.native(rows, event=first)[0]['line'], self.native(rows, event='RECEIVE')[0]['line'])
                self.assert_snapshot_interleaving_verified(rows)

    def test_receive_snapshot_can_observe_freed_request_before_request_free_log(self):
        rows = self.receive_logged_before('REQUEST_FREE')
        self.native(rows, event='RECEIVE')[0]['fields'].update(busy='1', guard='1')
        self.snapshot_received(rows, 'COMMIT')
        receive, request_free = (self.native(rows, event=name)[0] for name in ('RECEIVE', 'REQUEST_FREE'))
        self.assertEqual((receive['fields']['request_freed'], receive['fields']['request_free_tid']), ('1', '94'))
        self.assertEqual((request_free['fields']['reply_received'], request_free['fields']['receive_rc']), ('0', '-61'))
        self.assertLess(receive['line'], request_free['line'])
        self.assert_snapshot_interleaving_verified(rows)

    def test_receive_snapshot_can_observe_send_returned_before_sent_log(self):
        rows = self.receive_logged_before('SENT')
        self.native(rows, event='RECEIVE')[0]['fields'].update(busy='1', guard='1', request_freed='0',
            request_free_rc='-61', request_free_tid='0', retained_request='0x500000')
        self.snapshot_received(rows, 'REQUEST_FREE', 'COMMIT')
        receive, sent = (self.native(rows, event=name)[0] for name in ('RECEIVE', 'SENT'))
        self.assertEqual(tuple(receive['fields'][key] for key in ('send_started', 'send_inflight', 'send_rc', 'ACK_sent')),
                         ('1', '0', '0', '1'))
        self.assertEqual(sent['fields']['reply_received'], '0')
        self.assertLess(receive['line'], sent['line'])
        self.assert_snapshot_interleaving_verified(rows)

    def test_receive_snapshot_during_guard_release_or_after_finish_before_commit_log(self):
        for busy, commit_received in (('1', True), ('0', False), ('0', True)):
            rows = self.receive_logged_before('COMMIT')
            self.native(rows, event='RECEIVE')[0]['fields'].update(busy=busy, guard='0')
            if commit_received:
                self.snapshot_received(rows, 'COMMIT')
            with self.subTest(receive_busy=busy, commit_snapshot_received=commit_received):
                self.assertLess(self.native(rows, event='RECEIVE')[0]['line'], self.native(rows, event='COMMIT')[0]['line'])
                self.assert_snapshot_interleaving_verified(rows)

    def test_interleaved_snapshots_still_require_actual_receive_and_event_transaction(self):
        for mutation in ('missing_receive', 'wrong_receiver_tid', 'cross_transaction', 'foreign_sender_free'):
            rows = copy.deepcopy(self.rows)
            self.snapshot_received(rows, 'SENT', 'REQUEST_FREE', 'COMMIT')
            receive = self.native(rows, event='RECEIVE')[0]
            if mutation == 'missing_receive':
                rows.remove(receive)
            elif mutation == 'wrong_receiver_tid':
                self.native(rows, event='COMMIT')[0]['fields']['receiver_tid'] = '96'
            elif mutation == 'cross_transaction':
                receive['fields']['transaction'] = '2'
            else:
                self.native(rows, event='REPLY_FREE')[0]['fields'].update(tid='95', reply_free_tid='95')
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                self.joined(rows=rows)

    def test_received_before_send_or_sender_snapshot_regression_is_rejected(self):
        for event in ('BEGIN', 'VERIFIED', 'REPLY', 'ALLOCATED'):
            rows = copy.deepcopy(self.rows)
            self.snapshot_received(rows, event)
            with self.subTest(received_before_send=event), self.assertRaises(ValueError):
                self.joined(rows=rows)
        rows = copy.deepcopy(self.rows)
        self.snapshot_received(rows, 'SENT', 'COMMIT')
        self.assertEqual(self.native(rows, event='REQUEST_FREE')[0]['fields']['reply_received'], '0')
        with self.assertRaisesRegex(ValueError, 'same-sender.*regressed'):
            self.joined(rows=rows)

    def test_receive_cannot_claim_reply_freed_before_original_future_returns(self):
        rows = copy.deepcopy(self.rows)
        self.native(rows, event='RECEIVE')[0]['fields'].update(reply_freed='1', reply_free_rc='0', reply_free_tid='94',
            retained_reply='(nil)', reply_consumed='1', complete='1', completions='1')
        with self.assertRaisesRegex(ValueError, 'RECEIVE.*snapshot'):
            self.joined(rows=rows)
        rows = copy.deepcopy(self.rows)
        rows.remove(self.native(rows, event='RECEIVE')[0])
        self.snapshot_received(rows, 'COMMIT')
        with self.assertRaises(ValueError):
            self.joined(rows=rows)

    def test_receive_snapshot_rejects_invalid_send_request_free_and_guard_combinations(self):
        for changes in (
                dict(send_started='0'), dict(send_inflight='1'), dict(ACK_sent='0'),
                dict(send_inflight='1', ACK_sent='0', send_rc='-61'),
                dict(request_releasing='1'), dict(busy='0', guard='1'),
                dict(busy='1', guard='0', request_freed='0', request_free_rc='-61',
                     request_free_tid='0', retained_request='0x500000'),
                dict(request_free_rc='-61'), dict(request_free_tid='95'), dict(retained_request='0x500000'),
                dict(reply_received='0', receive_rc='-61', receiver_tid='0'), dict(receiver_tid='94'),
                dict(reply_consumed='1'), dict(complete='1', completions='1')):
            rows = copy.deepcopy(self.rows)
            self.native(rows, event='RECEIVE')[0]['fields'].update(changes)
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                self.joined(rows=rows)

    def test_interleaved_snapshot_rc_and_initial_enodata_are_exact(self):
        for event, key, wrong in (
                ('SENT', 'receive_rc', '-61'), ('SENT', 'receive_rc', '-5'),
                ('REQUEST_FREE', 'receive_rc', '-61'), ('COMMIT', 'receive_rc', '-5'),
                ('ALLOCATED', 'send_rc', '0'), ('ALLOCATED', 'receive_rc', '0'),
                ('RECEIVE', 'send_rc', '-61'), ('RECEIVE', 'request_free_rc', '-61'),
                ('RECEIVE', 'reply_free_rc', '0'), ('RECEIVE', 'before_rc', '-61'),
                ('RECEIVE', 'model_rc', '-5'), ('RECEIVE', 'after_rc', '-5'),
                ('RECEIVE', 'allocate_rc', '-12')):
            rows = copy.deepcopy(self.rows)
            self.snapshot_received(rows, 'SENT', 'REQUEST_FREE', 'COMMIT')
            self.native(rows, event=event)[0]['fields'][key] = wrong
            with self.subTest(event=event, key=key, wrong=wrong), self.assertRaises(ValueError):
                self.joined(rows=rows)

    def test_reordered_receive_does_not_advance_sender_stages_or_fake_completion(self):
        rows = self.receive_logged_before('COMMIT')
        self.native(rows, event='RECEIVE')[0]['fields'].update(busy='1', guard='0')
        self.snapshot_received(rows, 'COMMIT')
        for event, changes in (
                ('SENT', dict(busy='0', guard='0')),
                ('REQUEST_FREE', dict(busy='1', guard='0')),
                ('COMMIT', dict(busy='1', guard='0')),
                ('COMMIT', dict(reply_consumed='1', complete='1', completions='1')),
                ('RECEIVE', dict(complete='1', completions='1')),
                ('REPLY_FREE', dict(reply_consumed='0', complete='0', completions='0'))):
            mutated = copy.deepcopy(rows)
            self.native(mutated, event=event)[0]['fields'].update(changes)
            with self.subTest(event=event, changes=changes), self.assertRaises(ValueError):
                self.joined(rows=mutated)

    def test_crank_signed_initial_rc_does_not_widen_unsigned_or_formatter_grammar(self):
        self.assertTrue(self.joined()['native_completion_verified'])
        begin = self.native(event='BEGIN')[0]['fields']
        self.assertEqual(begin['before_rc'], '-61')
        with self.assertRaisesRegex(ValueError, 'unsigned'):
            checker.number('-61')
        for text in ('+0', '-0', '-061', '0x0', '-2147483649'):
            rows = copy.deepcopy(self.rows)
            self.native(rows, event='BEGIN')[0]['fields']['before_rc'] = text
            with self.subTest(rc=text), self.assertRaises(ValueError):
                self.joined(rows=rows)
        rows = copy.deepcopy(self.rows)
        self.native(rows, event='BEGIN')[0]['fields']['bank_generation'] = '-1'
        with self.assertRaises(ValueError):
            self.joined(rows=rows)


class CPMovieFormatEvidenceTests(unittest.TestCase):
    """Declared MovieFormat240 parser fixtures; no C/Core/AP or media execution."""

    def setUp(self):
        base = CPCrankControlEvidenceTests('runTest')
        base.setUp()
        prior = bytearray(base.prior)
        struct.pack_into('<Q', prior, 56, 24)
        self.prior = bytes(prior)
        self.packet = self.request()
        self.raw = self.receipt(self.packet, self.prior)

    @staticmethod
    def request(byte1=0xa5, cookie=0x80000060, byte11=0x7e, byte19=0x9f):
        return struct.pack('<BBHI', 5, byte1, 0x4000, cookie) + bytes((5, 1, 0, byte11)) + bytes(6) + bytes((1, byte19))

    @staticmethod
    def receipt(packet, prior, movie_generation=1, bank_generation=4, crank_generation=2):
        before = struct.unpack_from('<Q', prior, 56)[0]
        state = bytearray(prior)
        struct.pack_into('<Q', state, 56, (before + 1) & (2**64 - 1))
        raw = bytearray(240)
        struct.pack_into('<2I7Q4I', raw, 0, 1, 240, struct.unpack_from('<Q', prior, 48)[0],
                         movie_generation, bank_generation, crank_generation, before,
                         (before + 1) & (2**64 - 1), checker.fnv(packet), 5, 0,
                         struct.unpack_from('<I', prior, 16)[0], 1)
        raw[80:208], raw[208:228] = state, packet
        return bytes(raw)

    @staticmethod
    def observation(raw, packet, prior, capacity=checker.DATA_BYTES):
        return dict(actual_c_result=0, returned_hex=raw.hex(), readback_verified=True,
            model_called=True, model_committed=True, request_hex=packet.hex(), input_hex=packet.hex(),
            input_fnv1a64=checker.fnv(packet), returned_bytes=240, returned_fnv1a64=checker.fnv(raw),
            before_state_c_result=0, before_state_hex=prior.hex(), result=dict(token=0, total=0, offset=0, used=240),
            output_buffer_hex=(raw + bytes(capacity - 240)).hex(), after_state_c_result=0,
            after_state_hex=raw[80:208].hex(), query_c_result=0,
            movie_generation=struct.unpack_from('<Q', raw, 16)[0], bank_generation=struct.unpack_from('<Q', raw, 24)[0],
            crank_generation=struct.unpack_from('<Q', raw, 32)[0], snapshot_hex=raw.hex())

    def decode(self, raw=None, packet=None, prior=None, instance=99, bank=4, crank=2):
        return checker.cp_movie_format_result(self.raw if raw is None else raw,
            self.packet if packet is None else packet, instance, self.prior if prior is None else prior, bank, crank)

    def test_exact240_software_mapping_retains_all_state_config_and_nonzero_counters(self):
        for fps in (1, 30, 60, 120):
            prior = bytearray(self.prior); struct.pack_into('<I', prior, 16, fps); prior = bytes(prior)
            raw = self.receipt(self.packet, prior)
            value = self.decode(raw=raw, prior=prior)
            self.assertEqual((value['movie_generation'], value['bank_generation'], value['crank_generation'],
                              value['before_config_generation'], value['config_generation'], value['format'],
                              value['rate'], value['fps'], value['codec'], value['frame_generation']),
                             (1, 4, 2, 24, 25, 5, 0, fps, 1, 22))
            self.assertEqual(raw[80:136], prior[:56])
            self.assertEqual(raw[144:208], prior[64:])
            self.assertEqual(raw[208:228], self.packet)
            self.assertEqual(raw[228:], bytes(12))

    def test_byte1_cookie_byte11_and_byte19_are_opaque_full_original_bytes(self):
        for offset in (1, 4, 5, 6, 7, 11, 19):
            for value in (0, 0xa5, 0xff):
                packet = bytearray(self.packet); packet[offset] = value; packet = bytes(packet)
                raw = self.receipt(packet, self.prior)
                with self.subTest(offset=offset, value=value):
                    self.assertEqual(self.decode(raw=raw, packet=packet)['input_fnv'], checker.fnv(packet))
                    self.assertEqual(raw[208:228], packet)
                    if packet != self.packet:
                        with self.assertRaises(ValueError):
                            self.decode(raw=raw)

    def test_every_known_selector_and_type_command_byte_rejects_before_receipt(self):
        for offset in (0, 2, 3, 8, 9, 10, 12, 13, 14, 15, 16, 17, 18):
            packet = bytearray(self.packet); packet[offset] ^= 1; packet = bytes(packet)
            with self.subTest(offset=offset), self.assertRaisesRegex(ValueError, 'original20'):
                self.decode(raw=self.receipt(packet, self.prior), packet=packet)

    def test_input_and_result_require_exact_bytes_sizes_versions_and_all240_bytes(self):
        for packet in (b'', self.packet[:-1], self.packet + b'\0', bytearray(self.packet), None):
            with self.subTest(packet_type=type(packet).__name__, packet=packet), self.assertRaises(ValueError):
                self.decode(packet=packet) if packet is not None else checker.cp_movie_format_result(
                    self.raw, None, 99, self.prior, 4, 2)
        for raw in (b'', self.raw[:-1], self.raw + b'\0', bytearray(self.raw), None):
            with self.subTest(raw_type=type(raw).__name__), self.assertRaises(ValueError):
                checker.cp_movie_format_result(raw, self.packet, 99, self.prior, 4, 2)
        for offset in range(240):
            raw = bytearray(self.raw); raw[offset] ^= 1
            # A different positive movie generation is a history violation, not a wire-shape violation.
            if 16 <= offset < 24:
                continue
            with self.subTest(result_offset=offset), self.assertRaises(ValueError):
                self.decode(raw=bytes(raw))

    def test_instance_pair_types_positive_generations_and_config_overflow(self):
        for key in ('instance', 'bank', 'crank'):
            for wrong in (0, -1, 2**64, True, 1.0, '1'):
                with self.subTest(field=key, wrong=wrong), self.assertRaises(ValueError):
                    self.decode(**{key: wrong})
        for offset in (8, 16, 24, 32):
            raw = bytearray(self.raw); struct.pack_into('<Q', raw, offset, 0)
            with self.subTest(zero_at=offset), self.assertRaises(ValueError):
                self.decode(raw=bytes(raw))
        for generation in (0, 2**64 - 1):
            prior = bytearray(self.prior); struct.pack_into('<Q', prior, 56, generation); prior = bytes(prior)
            with self.subTest(overflow=generation), self.assertRaises(ValueError):
                self.decode(raw=self.receipt(self.packet, prior), prior=prior)

    def test_busy_stream_invalid_state_and_every_preserved_counter_byte_are_rejected(self):
        for offset in (0, 4, 48, 104, 108, 120):
            prior = bytearray(self.prior); prior[offset] ^= 1; prior = bytes(prior)
            with self.subTest(state_offset=offset), self.assertRaises(ValueError):
                self.decode(raw=self.receipt(self.packet, prior), prior=prior)
        for offset in range(64, 128):
            raw = bytearray(self.raw); raw[80 + offset] ^= 1
            with self.subTest(preserved_state_offset=offset), self.assertRaises(ValueError):
                self.decode(raw=bytes(raw))

    def test_independent_getter_full_c_buffer_and_every_observation_field_are_required(self):
        observed = self.observation(self.raw, self.packet, self.prior)
        def check(value, capacity=checker.DATA_BYTES):
            return checker.cp_movie_format_observation(value, self.raw, self.packet, 99, self.prior, 4, 2, capacity)
        self.assertEqual(check(observed), self.decode())
        for key in observed:
            value = copy.deepcopy(observed); del value[key]
            with self.subTest(missing=key), self.assertRaises(ValueError):
                check(value)
        for key in ('returned_hex', 'snapshot_hex', 'request_hex', 'input_hex', 'before_state_hex', 'after_state_hex', 'output_buffer_hex'):
            for at in (0, len(observed[key]) // 2 - 1):
                value = copy.deepcopy(observed); raw = bytearray.fromhex(value[key]); raw[at] ^= 1; value[key] = raw.hex()
                with self.subTest(field=key, offset=at), self.assertRaises(ValueError):
                    check(value)
        for key, wrong in (('query_c_result', -5), ('actual_c_result', False), ('after_state_c_result', -61),
                ('before_state_c_result', -61), ('model_called', False), ('model_committed', False),
                ('readback_verified', 1), ('movie_generation', 2), ('bank_generation', 5), ('crank_generation', 3),
                ('returned_bytes', 239), ('returned_fnv1a64', 0), ('input_fnv1a64', 0),
                ('result', dict(token=1, total=240, offset=0, used=240))):
            value = copy.deepcopy(observed); value[key] = wrong
            with self.subTest(field=key, wrong=wrong), self.assertRaises(ValueError):
                check(value)
        for capacity in (239, checker.DATA_BYTES + 1, True, 240.0):
            with self.subTest(capacity=capacity), self.assertRaises(ValueError):
                check(observed, capacity)


class CPBoundedWitnessJSONLEvidenceTests(unittest.TestCase):
    """Only exact typed OP21/22 full C-buffer witnesses receive the bounded allowance."""

    def setUp(self):
        base = CPMovieFormatEvidenceTests('runTest'); base.setUp()
        self.prior, self.packet, self.raw = base.prior, base.packet, base.raw

    observation = staticmethod(CPMovieFormatEvidenceTests.observation)

    def witness(self, op):
        packet, raw, prior = self.packet, self.raw, self.prior
        if op == 21:
            packet = CPCrankControlEvidenceTests.request()
            raw = CPCrankControlEvidenceTests.receipt(packet, prior)
            observed = dict(actual_c_result=0, returned_hex=raw.hex(), readback_verified=True, model_called=True,
                model_committed=True, request_hex=packet.hex(), before_state_c_result=0, before_state_hex=prior.hex(),
                result=dict(token=0, total=0, offset=0, used=208), output_buffer_hex=(raw + bytes(checker.DATA_BYTES - 208)).hex(),
                after_state_c_result=0, after_state_hex=raw[64:192].hex(), query_c_result=0,
                crank_generation=2, bank_generation=4, snapshot_hex=raw.hex())
        else:
            observed = self.observation(raw, packet, prior)
        origin = dict(producer_tid=385, source=0x80020002, destination=0x90030001,
                      command=0x409d if op == 21 else 0x4000, bytes=len(packet), fnv1a64=checker.fnv(packet))
        row = dict(event=1, monotonic_ns=1, kind='model_crank_control' if op == 21 else 'model_movie_format',
            model_instance=99, sequence=1, opcode=op, actual_c_result=0, actual_core_sha256='a' * 64,
            origin=origin, native_acceptance=False, model_called=True, model_committed=True, observation=observed)
        for key, data, direction in (('request_payload', packet, 'in'), ('output_payload', raw, 'out')):
            row[key] = dict(bytes=len(data), direction=direction, opcode=op, sequence=1, model_instance=99, origin=origin.copy())
        if op == 22:
            row.update(admission_error=None, input_hex=packet.hex(), request_fnv1a64=checker.fnv(packet), error=0)
        return row

    @staticmethod
    def encoded(row, size=None):
        raw = json.dumps(row, separators=(',', ':')).encode()
        if size is not None:
            raw += b' ' * (size - len(raw))
        return raw + b'\n'

    def test_only_two_typed_actual_cbuffer_witnesses_fit_finite192KiB_cap(self):
        for op in (21, 22):
            row = self.witness(op)
            self.assertGreater(len(self.encoded(row)), 16384)
            self.assertEqual(checker.jsonl(self.encoded(row)), [row])
            self.assertEqual(checker.jsonl(self.encoded(row, 192 * 1024)), [row])
            with self.assertRaisesRegex(ValueError, 'oversized non-source'):
                checker.jsonl(self.encoded(row, 192 * 1024 + 1))

    def test_wrong_kind_opcode_type_native_source_or_fixed_lengths_do_not_widen_cap(self):
        for op in (21, 22):
            for key, wrong in (('kind', 'core_result'), ('kind', 'response'), ('kind', 'model_parameter_bank'),
                    ('kind', 'crank_control_rejected'), ('kind', 'movie_format_rejected'),
                    ('kind', 'cp_movie_format'), ('opcode', float(op)), ('opcode', True), ('opcode', 11),
                    ('actual_c_result', -5), ('actual_c_result', False), ('model_committed', False), ('native_acceptance', True)):
                row = self.witness(op); row[key] = wrong
                with self.subTest(op=op, field=key, wrong=wrong), self.assertRaises(ValueError):
                    checker.jsonl(self.encoded(row))
            for key, wrong in (('source', 0x80020003), ('destination', 0x90030002), ('command', 0x4063),
                               ('bytes', 11), ('producer_tid', 0), ('fnv1a64', 0)):
                row = self.witness(op); row['origin'][key] = wrong
                with self.subTest(op=op, origin=key), self.assertRaises(ValueError):
                    checker.jsonl(self.encoded(row))
            for reference in ('request_payload', 'output_payload'):
                row = self.witness(op); row[reference]['bytes'] -= 1
                with self.subTest(op=op, reference=reference), self.assertRaises(ValueError):
                    checker.jsonl(self.encoded(row))

    def test_opaque_bytes_wrong_query_receipt_zero_tail_and_cbuffer_extent_reject(self):
        for op in (21, 22):
            for key in ('request_hex', 'returned_hex', 'snapshot_hex', 'before_state_hex', 'after_state_hex', 'output_buffer_hex'):
                row = self.witness(op); data = bytearray.fromhex(row['observation'][key]); data[-1] ^= 1
                row['observation'][key] = data.hex()
                with self.subTest(op=op, field=key), self.assertRaises(ValueError):
                    checker.jsonl(self.encoded(row))
            row = self.witness(op); row['observation']['output_buffer_hex'] += '00'
            with self.subTest(op=op, excessive_capacity=True), self.assertRaises(ValueError):
                checker.jsonl(self.encoded(row))
            row = self.witness(op); row['observation']['output_buffer_hex'] = row['observation']['output_buffer_hex'][:-1]
            with self.subTest(op=op, odd_hex=True), self.assertRaises(ValueError):
                checker.jsonl(self.encoded(row))

    def test_original16KiB_noncontrol_and_OP11_paused_source_exception_are_preserved(self):
        ordinary = dict(event=1, monotonic_ns=1, kind='core_result')
        self.assertEqual(checker.jsonl(self.encoded(ordinary, 16384)), [ordinary])
        with self.assertRaisesRegex(ValueError, 'oversized non-source'):
            checker.jsonl(self.encoded(ordinary, 16385))
        for kind in ('ap_source_result', 'response'):
            source = dict(event=1, monotonic_ns=1, kind=kind, opcode=11, actual_c_result=None,
                          source_provider_kind='paused-source-snapshot-v1')
            self.assertEqual(checker.jsonl(self.encoded(source, 192 * 1024 + 1)), [source])


class CPParameterModeRetirementEvidenceTests(unittest.TestCase):
    """Synthetic five-lease retirement snapshots, never an assertion about a live VM."""

    @staticmethod
    def lifecycle():
        row, = checker.parse_console(E6MX_CONTROL_COMMIT)
        base = dict(row['fields'], pid='260', tid='385', sender_tid='385', receiver_tid='357',
            model_instance='99', cycle_id='2', cycle_generation='21', lease_cycle_id='2',
            config_generation='21', frame_generation='21', start_complete='1', mode1_complete='1',
            mode_complete='1', notification_AP_consumed='1', notification_received='1', notification_queued='1',
            faults='0', busy='0', guard='0', queued='1', received='1', freed='1', consumed='1', retained='(nil)')
        rows = []
        for index, line in ((0, 1), (1, 2), (2, 11), (3, 12), (4, 13)):
            f = dict(base, index=str(index), role=str(1 if index in (0, 2) else 3 if index == 4 else 2),
                bytes=str({0: 24, 1: 16, 2: 12, 3: 12, 4: 1748}[index]),
                tid='357' if index == 4 else '385', free_tid='357' if index == 4 else '385',
                source='0x80020002' if index in (0, 2) else '0x90030001',
                destination='0x90030001' if index in (0, 2) else '0x80020002',
                busy=str(int(index in (0, 2))), guard=str(int(index in (0, 2))))
            rows.append(dict(tag='FUNCTIONAL_CAMERA_CONTROL_' + ('OWNED_FREE' if index in (0, 2) else 'AP_FREE'),
                             line=line, fields=f))
        commit = dict(base, index='3', role='2', bytes='12', freed='0', consumed='0', retained='0x600000',
                      free_tid='0', mode_complete='0', notification_AP_consumed='0')
        rows.append(dict(tag='FUNCTIONAL_CAMERA_CONTROL_COMMIT', line=10, fields=commit))
        return sorted(rows, key=lambda r: r['line'])

    def test_post_commit_real_notification_free_retires_current_cycle(self):
        rows = self.lifecycle()
        self.assertEqual(checker.cp_parameter_mode_retirement(rows, 20, 260, 99), rows[-1])
        ack_last = self.lifecycle()
        ack = next(r for r in ack_last if r['tag'].endswith('AP_FREE') and r['fields']['index'] == '3')
        ack['line'] = 14
        ack_last.sort(key=lambda r: r['line'])
        self.assertEqual(checker.cp_parameter_mode_retirement(ack_last, 20, 260, 99), ack)
        with self.assertRaisesRegex(ValueError, 'full retirement'):
            checker.cp_parameter_mode_retirement([r for r in rows if r['line'] <= 10], 20, 260, 99)

    def test_current_active_cycle_is_not_replaced_by_historical_complete_commit(self):
        for tag in ('PROBE', 'SENT', 'OWNED_FREE', 'RECEIVE', 'REFUSED'):
            rows = self.lifecycle()
            active = copy.deepcopy(rows[2]); active.update(line=15, tag='FUNCTIONAL_CAMERA_CONTROL_' + tag)
            active['fields'].update(cycle_id='3', busy='1', guard='1', mode_complete='0')
            rows.append(active)
            with self.subTest(active=tag), self.assertRaises(ValueError):
                checker.cp_parameter_mode_retirement(rows, 20, 260, 99)

    def test_each_retired_lease_is_required_and_cannot_be_retained_foreign_or_unreceived(self):
        for index in range(5):
            rows = self.lifecycle(); lease = next(r for r in rows if r['fields']['index'] == str(index) and not r['tag'].endswith('COMMIT'))
            rows.remove(lease)
            with self.subTest(missing=index), self.assertRaises(ValueError):
                checker.cp_parameter_mode_retirement(rows, 20, 260, 99)
            for key, wrong in (('retained', '0x700000'), ('freed', '0'), ('free_rc', '-5'), ('send_inflight', '1'),
                               ('pid', '261'), ('model_instance', '100'), ('free_tid', '99')):
                rows = self.lifecycle(); lease = next(r for r in rows if r['fields']['index'] == str(index) and not r['tag'].endswith('COMMIT'))
                lease['fields'][key] = wrong
                with self.subTest(lease=index, field=key), self.assertRaises(ValueError):
                    checker.cp_parameter_mode_retirement(rows, 20, 260, 99)
        for key, wrong in (('received', '0'), ('consumed', '0'), ('lease_cycle_id', '1'), ('sender_tid', '386'),
                           ('cycle_generation', '20'), ('config_generation', '20')):
            rows = self.lifecycle(); rows[-1]['fields'][key] = wrong
            with self.subTest(notification=key), self.assertRaises(ValueError):
                checker.cp_parameter_mode_retirement(rows, 20, 260, 99)


class CPMovieFormatTransportEvidenceTests(unittest.TestCase):
    """HOST_TEST files and broker joins; native and capture remain unverified."""

    @classmethod
    def setUpClass(cls):
        CPCrankControlTransportEvidenceTests.setUpClass()

    def setUp(self):
        base = CPCrankControlTransportEvidenceTests('runTest'); base.setUp(); self.addCleanup(base.doCleanups)
        temporary = tempfile.TemporaryDirectory(); self.addCleanup(temporary.cleanup)
        self.packet = CPMovieFormatEvidenceTests.request()
        self.prior = base.following
        self.raw = CPMovieFormatEvidenceTests.receipt(self.packet, self.prior, bank_generation=1, crank_generation=1)
        self.origin = dict(producer_tid=96, source=0x80020002, destination=0x90030001,
                           command=0x4000, bytes=20, fnv1a64=checker.fnv(self.packet))
        operations = [dict(op=tx['opcode'], data=checker.payload_read(base.run, tx['request_payload']),
            output=checker.transfer_output(base.run, tx), origin=copy.deepcopy(tx['origin'])) for tx in base.transport['transfers']]
        operations += [dict(op=2, data=b'', output=self.prior, origin=self.origin),
                       dict(op=22, data=self.packet, output=self.raw, origin=self.origin),
                       dict(op=2, data=b'', output=self.raw[80:208], origin=self.origin)]
        lines, count = [], 0
        for line in (base.run / 'console.log').read_text().splitlines():
            if line.startswith('OBS FUNCTIONAL_CAMERA_TRANSFER '):
                lines.append('HOST_TEST_TRANSFER_' + str(count)); count += 1
            else:
                lines.append(line)
        lines += ['HOST_TEST_TRANSFER_' + str(index) for index in range(count, len(operations))]
        self.args = host_test_transport(Path(temporary.name), operations, '\n'.join(lines) + '\n')
        self.run, self.manifest, self.rows, events, build = self.args
        policy = {'functional_camera_' + key: copy.deepcopy(value) for key, value in
                  {**checker.CP_PARAMETER_BANK_POLICY, **checker.CP_CRANK_CONTROL_POLICY, **checker.CP_MOVIE_FORMAT_POLICY}.items()}
        policy['functional_camera_profile'] = checker.PROFILE
        self.manifest.update(policy); self.manifest['backup_transport'].update(copy.deepcopy(policy))
        for op, kind, key in ((20, 'model_parameter_bank', 'parameter_bank'),
                              (21, 'model_crank_control', 'crank_control'), (22, 'model_movie_format', 'movie_format')):
            core = next(e for e in events if e['kind'] == 'core_result' and e['opcode'] == op)
            observed = (CPMovieFormatEvidenceTests.observation(self.raw, self.packet, self.prior) if op == 22 else
                        copy.deepcopy(next(t for t in base.transport['transfers'] if t['opcode'] == op)[key]['observation']))
            witness = dict(kind=kind, model_instance=99, sequence=core['sequence'], opcode=op,
                origin=copy.deepcopy(core['origin']), actual_c_result=0, actual_core_sha256=build['model_sha256'],
                request_payload=core['request_payload'], output_payload=core['output_payload'],
                native_acceptance=False, observation=observed)
            if op in (21, 22):
                witness.update(model_called=True, model_committed=True)
            if op == 22:
                witness.update(admission_error=None, input_hex=self.packet.hex(), request_fnv1a64=checker.fnv(self.packet), error=0)
            events.insert(events.index(core) + 1, witness)
            for event in events:
                if event.get('opcode') == op and event['kind'] in ('core_result', 'response'):
                    event['actual_core_sha256'] = build['model_sha256']
        self.persist(self.args)
        self.transport = checker.check_transport(*self.args)

    persist = staticmethod(CPParameterBankTransportEvidenceTests.persist_broker)

    def content(self, transport=None, manifest=None):
        return checker.check_cp_movie_format_content(self.run, self.manifest if manifest is None else manifest,
            self.rows, self.transport if transport is None else transport)

    def test_broker_and_independent_getter_exact_content_never_establish_native_or_media(self):
        self.assertEqual(checker.OPS[22], (20,))
        self.assertEqual(checker.OPS[21], (12,))
        parsed = checker.jsonl((self.run / 'functional-camera-broker-receipts.jsonl').read_bytes())
        self.assertEqual([e['kind'] for e in parsed if e['kind'] in ('model_crank_control', 'model_movie_format')],
                         ['model_crank_control', 'model_movie_format'])
        result = self.content()
        self.assertTrue(result['content_join_verified'])
        self.assertFalse(result['native_completion_verified'] or result['verified'] or result['capture_verified'] or result['frame_consumed'])
        self.assertFalse(self.transport['verified'])
        value, = result['transactions']
        self.assertEqual((value['bank_generation'], value['crank_generation'], value['movie_generation'],
                          value['before_config_generation'], value['config_generation']), (1, 1, 1, 24, 25))
        self.assertEqual(result['missing_native_observations'], list(checker.CP_MOVIE_NATIVE_JOINS))

    def test_partial_or_borrowed_frame_proof_fails_before_history_scan(self):
        for index in (7, 8, 9):
            transport = copy.deepcopy(self.transport); transport['transfers'][index]['frame'] = {'proof': {}}
            with mock.patch.object(checker, 'vdf_history') as history:
                with self.subTest(index=index), self.assertRaisesRegex(ValueError, 'no-frame'):
                    self.content(transport)
                history.assert_not_called()
        transport = copy.deepcopy(self.transport); transport['transfers'].pop()
        with mock.patch.object(checker, 'vdf_history') as history:
            with self.assertRaisesRegex(ValueError, 'no-frame'):
                self.content(transport)
            history.assert_not_called()

    def test_wrong_broker_receipt_source_library_or_opaque_input_rejects(self):
        for key, wrong in (('actual_core_sha256', 'b' * 64), ('actual_c_result', -5), ('model_committed', False),
                ('input_hex', '00' * 20), ('request_fnv1a64', 0), ('error', False), ('admission_error', -16)):
            args = copy.deepcopy(self.args); event = next(e for e in args[3] if e['kind'] == 'model_movie_format'); event[key] = wrong
            self.persist(args)
            with self.subTest(field=key), self.assertRaises(ValueError):
                checker.check_transport(*args)
        for key, wrong in (('source', 0x80020003), ('destination', 0x90030002), ('command', 0x409d), ('bytes', 12)):
            transport = copy.deepcopy(self.transport); transport['transfers'][8]['origin'][key] = wrong
            with self.subTest(origin=key), self.assertRaises(ValueError):
                self.content(transport)

    def test_c0_then_postcheck_failure_retains_actual_commit_and_original_output(self):
        args = copy.deepcopy(self.args); event = next(e for e in args[3] if e['kind'] == 'model_movie_format')
        event.update(kind='movie_format_rejected', error='independent getter failure')
        event['observation'].update(query_c_result=-5, readback_verified=False)
        self.persist(args)
        with self.assertRaises(checker.MovieFormatRejected) as caught:
            checker.check_transport(*args)
        saved = caught.exception.event
        self.assertEqual(saved['actual_c_result'], 0)
        self.assertIs(saved['model_committed'], True)
        self.assertEqual(bytes.fromhex(saved['observation']['returned_hex']), self.raw)

    def test_same_pair_replay_monotonic_movie_and_stale_bank_are_rejected(self):
        transport = copy.deepcopy(self.transport)
        before, movie, after = copy.deepcopy(transport['transfers'][7:10])
        for tx in (before, movie, after):
            tx['first'] += 3; tx['last'] += 3; tx['line'] += 100
        transport['transfers'] += [before, movie, after]
        outputs = {before['first']: self.raw[80:208], movie['first']: CPMovieFormatEvidenceTests.receipt(
            self.packet, self.raw[80:208], movie_generation=2, bank_generation=1, crank_generation=1),
            after['first']: self.raw[80:208]}
        original = checker.transfer_output
        with mock.patch.object(checker, 'transfer_output', side_effect=lambda run, tx:
                               outputs[tx['first']] if tx['first'] in outputs else original(run, tx)):
            with self.assertRaisesRegex(ValueError, 'once-only'):
                checker.vdf_history(self.run, transport)
        for key in ('parameter_bank', 'crank_control_content'):
            transport = copy.deepcopy(self.transport)
            transport[key]['verified' if key == 'parameter_bank' else 'content_join_verified'] = False
            with self.subTest(missing=key), self.assertRaises(ValueError):
                self.content(transport)

    def test_movie_generation_jump_and_retained_optical_predecessor_reject(self):
        original = checker.transfer_output
        jumped = CPMovieFormatEvidenceTests.receipt(self.packet, self.prior,
            movie_generation=2, bank_generation=1, crank_generation=1)
        with mock.patch.object(checker, 'transfer_output', side_effect=lambda run, tx:
                               jumped if tx['opcode'] == 22 else original(run, tx)):
            with self.assertRaisesRegex(ValueError, 'once-only'):
                checker.vdf_history(self.run, self.transport)
        transport = copy.deepcopy(self.transport)
        # An already-consumed optical capture remains leased until OP19/CANCEL, even with tokenless transfer.
        capture = dict(transport['transfers'][7], opcode=17, first=700, last=700, token=0, frame=None)
        transport['transfers'].insert(7, capture)
        with self.assertRaisesRegex(ValueError, 'retained result/optical frame'):
            checker.vdf_history(self.run, transport)

    def test_next_real_bank_crank_pair_authorizes_exactly_one_new_monotonic_movie(self):
        transport = copy.deepcopy(self.transport)
        wire = CPParameterBankEvidenceTests('runTest'); wire.setUp()
        prior = self.raw[80:208]
        wire.prior = prior
        bank_packet = wire.original_packet(fps=60)
        bank_raw = wire.result(bank_packet, prior, bank_generation=2)
        crank_packet = CPCrankControlEvidenceTests.request(cookie=0x80000061)
        crank_raw = CPCrankControlEvidenceTests.receipt(crank_packet, bank_raw[64:192], bank_generation=2, crank_generation=2)
        movie_packet = CPMovieFormatEvidenceTests.request(cookie=0x80000062)
        movie_raw = CPMovieFormatEvidenceTests.receipt(movie_packet, crank_raw[64:192],
            movie_generation=2, bank_generation=2, crank_generation=2)
        outputs = {11: prior, 12: bank_raw, 13: bank_raw[64:192], 14: crank_raw,
                   15: crank_raw[64:192], 16: movie_raw, 17: movie_raw[80:208]}
        inputs = {12: bank_packet, 14: crank_packet, 16: movie_packet}
        for sequence, op in ((11, 2), (12, 20), (13, 2), (14, 21), (15, 2), (16, 22), (17, 2)):
            transport['transfers'].append(dict(first=sequence, last=sequence, opcode=op, token=0, frame=None,
                request_payload={'HOST_TEST_sequence': sequence}))
        old_output, old_payload = checker.transfer_output, checker.payload_read
        with mock.patch.object(checker, 'transfer_output', side_effect=lambda run, tx:
                outputs[tx['first']] if tx['first'] in outputs else old_output(run, tx)), \
             mock.patch.object(checker, 'payload_read', side_effect=lambda run, reference:
                inputs[reference['HOST_TEST_sequence']] if 'HOST_TEST_sequence' in reference else old_payload(run, reference)):
            value = checker.vdf_history(self.run, transport)[16]
        self.assertEqual((value['bank_generation'], value['crank_generation'], value['movie_generation'], value['fps']), (2, 2, 2, 60))
        self.assertEqual(movie_raw[144:208], self.raw[144:208])

    def test_new_policy_is_typed_optional_for_old_callers_but_complete_when_present(self):
        profile = CPParameterBankEvidenceTests.profile()
        for target in (profile, profile['backup_transport']):
            target.update({'functional_camera_' + k: copy.deepcopy(v) for k, v in checker.CP_MOVIE_FORMAT_POLICY.items()})
        self.assertTrue(checker.check_profile(profile)['verified'])
        for key, value in checker.CP_MOVIE_FORMAT_POLICY.items():
            changed = copy.deepcopy(profile); del changed['functional_camera_' + key]
            with self.subTest(missing=key), self.assertRaises(ValueError):
                checker.check_profile(changed)
            changed = copy.deepcopy(profile)
            changed['functional_camera_' + key] = True if type(value) is int else 'unsupported'
            with self.subTest(wrong_type=key), self.assertRaises(ValueError):
                checker.check_profile(changed)
        changed = copy.deepcopy(profile)
        changed['functional_camera_cp_movie_format_physical_ready'] = True
        with self.assertRaises(ValueError):
            checker.check_profile(changed)



# Append before the existing unittest.main() guard; preserve every existing test method.
class CPMovieFormatNativeJoinEvidenceTests(unittest.TestCase):
    """Synthetic exact producer streams; execution belongs to the parent's concentrated suite."""

    @classmethod
    def setUpClass(cls):
        CPMovieFormatTransportEvidenceTests.setUpClass()

    def setUp(self):
        base = CPMovieFormatTransportEvidenceTests('runTest'); base.setUp(); self.addCleanup(base.doCleanups)
        predecessor = CPCrankNativeJoinEvidenceTests('runTest'); predecessor.setUp(); self.addCleanup(predecessor.doCleanups)
        self.args = base.args
        self.run, self.manifest, self.rows, _, _ = self.args
        self.transport = copy.deepcopy(base.transport)
        self.packet, self.prior, self.raw = base.packet, base.prior, base.raw
        self.following = self.raw[80:208]
        self.predecessor_rows = copy.deepcopy(predecessor.rows)
        self.movie_transfers = {int(r['fields']['seq'].split('..')[0]): copy.deepcopy(r) for r in self.rows
                                if r['tag'] == 'FUNCTIONAL_CAMERA_TRANSFER' and
                                int(r['fields']['seq'].split('..')[0]) >= 8}
        self.assemble('normal')

    row = staticmethod(CPCrankNativeJoinEvidenceTests.row)
    record = staticmethod(CPParameterBankTransportEvidenceTests.record)

    def initial4000(self):
        packet = CPMovieFormatEvidenceTests.request(byte1=0, cookie=0x80000042, byte11=0, byte19=0)
        reply = b'\x01\0\0\x40' + packet[4:8] + struct.pack('<I', 0xf000)
        digest = 2166136261
        for byte in packet:
            digest = ((digest ^ byte) * 16777619) & 0xffffffff
        f = dict(pid=77, opcode='0x4000', sender_tid=87, waiter_tid=0, attempts=1, requests=1, busy=1, guard=1,
            faults=0, source='0x80020002', request_destination='0x90030001', destination='0x80020002', bytes=20,
            request=packet.hex(), cookie='0x80000042', wire_fnv1a32=hex(digest), reply=reply.hex(), freed_reply=bytes(12).hex(),
            reply_free_destination=0, reply_free_source=0, reply_free_bytes=0, allocate_rc=0, send_rc=0,
            request_free_rc=0, reply_free_rc=0, queued=1, request_freed=1, reply_freed=0, clean_completion=0, ap_consumed=0,
            known_field_mask='0x7f', virtual_field_mask='0x7f', virtual_fields_readback=1, virtual_fields_consumed='0x7f',
            virtual_fields='5,1,0,0,0,0,1', virtual_readback='5,1,0,0,0,0,1', retained_request='(nil)',
            live_reply='0x370000', retained_cleanup='(nil)', diagnostic_only=1, no_publication=1, virtual_padding=1,
            source_byte1_known=0, source_business_applied=0, current_known=0, source_dependency_closed=0,
            business_applied=0, source_dependencies_closed=0, configured=0, published=0, pending_complete=0,
            generation=0, native_verified=0, native_cp=0, EE=0, frame=0, capture=0)
        rows = [self.row('NATIVE_CP_MOVIE_FORMAT_DIAGNOSTIC_REQUEST_FREE', f)]
        f.update(busy=0, guard=0)
        rows.append(self.row('NATIVE_CP_MOVIE_FORMAT_DIAGNOSTIC_COMPLETE', f))
        f.update(waiter_tid=87, freed_reply=reply.hex(), reply_free_destination='0x80020002',
            reply_free_source='0x90030001', reply_free_bytes=12, reply_freed=1, clean_completion=1, ap_consumed=1, live_reply='(nil)')
        rows.append(self.row('NATIVE_CP_MOVIE_FORMAT_DIAGNOSTIC_REPLY_FREE', f))
        return rows

    def assemble(self, variant):
        rows = copy.deepcopy(self.predecessor_rows)
        at = max(i for i, r in enumerate(rows) if r['tag'].startswith('NATIVE_CP_EE_DIAGNOSTIC_')) + 1
        rows[at:at] = self.initial4000()
        rows += [self.row('NATIVE_CP_BACKGROUND_INPUT_AUDIT', dict(pid=77, tid=96, sequence=72, entry='async',
            pointer='0x700000', destination='0x90030001', bytes=20, source='0x80020002', size_known=1,
            source_known=1, bytes_complete=1, complete=1, producer_return='0x7f29174a68', consumed=0,
            state_verified=0, capture_verified=0)), self.row('NATIVE_CP_BACKGROUND_INPUT_AUDIT_BYTES',
            dict(pid=77, tid=96, sequence=72, offset=0, bytes=20, raw=self.packet.hex()))]
        resources = checker.parse_console(JFZ_VDF_RESOURCE_OBS.encode())
        for row in resources:
            row['tag'] = row['tag'].replace('FUNCTIONAL_VDF_PATH', 'FUNCTIONAL_CP_MOVIE_FORMAT')
            row['fields']['tid'] = '96'
            if 'pid' in row['fields']:
                row['fields']['pid'] = '77'
        bank_packet = checker.payload_read(self.run, self.transport['transfers'][2]['request_payload'])
        crank_packet = checker.payload_read(self.run, self.transport['transfers'][5]['request_payload'])
        fields = {}
        for part in checker.CP_MOVIE_EVENT_SCHEMA.split():
            key, grammar = part.split(':', 1)
            fields[key] = ('(nil)' if grammar == 'pointer' else '0000000000000000' if grammar == 'digest' else
                grammar if grammar not in ('crank_event', 'pid', 'tid', 'u64', 'u32', 'hex32', 'i32', 'bit') else '0')
        fields.update(pid='77', tid='96', transaction='1', requests='1', sender_tid='96', busy='1',
            source='0x80020002', destination='0x90030001', command='0x4000', bytes='20',
            native_fnv1a=f'{checker.fnv(self.packet):016x}', cookie=hex(struct.unpack_from('<I', self.packet, 4)[0]),
            request_pointer='0x700000', model_instance='99', bank_generation='1', crank_generation='1',
            bank_transaction='2', bank_commits='1', bank_released='1', bank_source='0x80020002',
            bank_destination='0x90030001', bank_command='0x4063', bank_bytes='2564', bank_native_fnv1a=f'{checker.fnv(bank_packet):016x}',
            crank_transaction='1', crank_completions='1', crank_source='0x80020002', crank_destination='0x90030001',
            crank_command='0x409d', crank_bytes='12', crank_native_fnv1a=f'{checker.fnv(crank_packet):016x}')
        for key in ('before_rc', 'model_rc', 'after_rc', 'validation_rc', 'allocate_rc', 'send_rc',
                    'request_free_rc', 'reply_free_rc', 'receive_rc'):
            fields[key] = '-61'
        reply = b'\x01\0\0\x40' + self.packet[4:8] + struct.pack('<I', 0xf000)
        streams = dict(BEGIN=('request', self.packet), BEFORE=('before_state', self.prior),
            MODEL=('receipt', self.raw), AFTER=('after_state', self.following), REPLY=('reply', reply))
        stages = ['BEGIN', 'BEFORE', 'MODEL', 'AFTER', 'VERIFIED', 'REPLY', 'ALLOCATED']
        stages += (['RECEIVE', 'REPLY_FREE', 'SENT', 'REQUEST_FREE', 'COMMIT'] if variant == 'inline' else
                   ['SENT', 'RECEIVE', 'REQUEST_FREE', 'COMMIT', 'REPLY_FREE'] if variant == 'request_free_receive' else
                   ['SENT', 'REQUEST_FREE', 'COMMIT', 'RECEIVE', 'REPLY_FREE'])
        for event in stages:
            fields['event'], fields['tid'] = event, '97' if event == 'RECEIVE' else '96'
            if event in ('BEFORE', 'MODEL', 'AFTER'):
                rows.append(copy.deepcopy(self.movie_transfers[{'BEFORE': 8, 'MODEL': 9, 'AFTER': 10}[event]]))
            if event == 'BEFORE':
                fields.update(guard='1', before_rc='0', before_config_generation='24', frame_generation='1', fps='30',
                    before_used='128', before_required='128', before_instance='99')
            elif event == 'MODEL':
                fields.update(model_called='1', model_committed='1', model_rc='0', validation_rc='0', commits='1',
                    movie_generation='1', config_generation='25', software_format='5', software_rate_index='0', software_codec='1',
                    movie_used='240', movie_required='240', movie_instance='99', receipt_fnv1a=f'{checker.fnv(self.raw):016x}')
            elif event == 'AFTER':
                fields.update(after_rc='0', after_used='128', after_required='128', after_instance='99')
            elif event == 'VERIFIED':
                fields.update(verified='1', owned='1', verified_commits='1', last_bank_generation='1', last_crank_generation='1',
                    last_movie_generation='1', retained_request='0x700000')
            elif event == 'REPLY':
                fields['reply_fnv1a'] = f'{checker.fnv(reply):016x}'
            elif event == 'ALLOCATED':
                fields.update(reply_pointer='0x800000', allocation_pointer='0x800000', retained_reply='0x800000',
                    reply_allocated='1', reply_valid='1', allocate_rc='0')
            elif event == 'SENT':
                fields.update(send_started='1', send_inflight='0', ACK_sent='1', send_rc='0')
            elif event == 'REQUEST_FREE':
                fields.update(request_releasing='0', request_freed='1', request_free_rc='0', request_free_tid='96', retained_request='(nil)')
            elif event == 'COMMIT':
                fields.update(busy='0', guard='0')
            elif event == 'RECEIVE':
                fields.update(send_started='1', reply_received='1', receive_rc='0', receiver_tid='97')
                if variant == 'inline':
                    fields['send_inflight'] = '1'
                if variant == 'request_free_receive':
                    fields['request_releasing'] = '1'
            elif event == 'REPLY_FREE':
                fields.update(reply_freed='1', reply_free_rc='0', reply_free_tid='96', retained_reply='(nil)')
            fields['reply_consumed'] = str(int(fields['ACK_sent'] == fields['reply_received'] == fields['reply_freed'] == '1' and
                                               fields['send_inflight'] == '0'))
            fields['complete'] = fields['completions'] = str(int(fields['reply_consumed'] == fields['request_freed'] == '1' and
                                                                fields['busy'] == fields['guard'] == '0'))
            rows.append(self.row('FUNCTIONAL_CP_MOVIE_FORMAT_EVENT', fields))
            if event in streams:
                kind, raw = streams[event]
                for offset in range(0, len(raw), 128):
                    block = raw[offset:offset + 128]
                    rows.append(self.row('FUNCTIONAL_CP_MOVIE_FORMAT_BYTES', dict(event=event, pid=77, tid=96,
                        transaction=1, kind=kind, total=len(raw), offset=offset, bytes=len(block), raw=block.hex(),
                        native_fnv1a=fields['native_fnv1a'], content_fnv1a=f'{checker.fnv(raw):016x}', model_instance=99,
                        bank_generation=1, crank_generation=1, movie_generation=fields['movie_generation'],
                        functional_model=1, original_CP=0, physical_ASIC_verified=0, capture_verified=0)))
            if event == 'BEGIN':
                rows += copy.deepcopy(resources)
                # This is the actual post-reservation predecessor callback position, before the first STATE RPC.
                rows.append(self.row('NATIVE_CP302C_NOCONVERT_ALL13_READBACK', dict(pid=77, tid=96, accepted=1,
                    video_AP_consumed=1, OSD_AP_consumed=1, audio_AP_consumed=1, OSD_live=16, OSD_owners_each=2,
                    OSD_opens_each=2, global_DMM_idle_claimed=0, capture_verified=0)))
        self.rows[:] = checker.parse_console(('\n'.join('OBS ' + self.record(r['tag'], r['fields']) for r in rows) + '\n').encode())
        self.persist()
        for tx in self.transport['transfers']:
            tx['line'] = next(r['line'] for r in self.rows if r['tag'] == 'FUNCTIONAL_CAMERA_TRANSFER' and
                              int(r['fields']['seq'].split('..')[0]) == tx['first'])
        self.transport['parameter_bank'] = checker.check_cp_parameter_bank(self.run, self.manifest, self.rows, self.transport)
        self.transport['crank_control_content'] = checker.check_cp_crank_control_content(self.run, self.manifest, self.rows, self.transport)

    def persist(self):
        raw = ('\n'.join('OBS ' + self.record(r['tag'], r['fields']) for r in self.rows) + '\n').encode()
        (self.run / 'console.log').write_bytes(raw)
        self.manifest['functional_camera_runtime']['console_sha256_at_close'] = checker.sha(raw)
        CPMovieFormatTransportEvidenceTests.persist(self.args)

    def native(self, rows=None, event=None, kind=None):
        return [r for r in (self.rows if rows is None else rows) if
            (kind is None and r['tag'] == 'FUNCTIONAL_CP_MOVIE_FORMAT_EVENT' and
             (event is None or r['fields']['event'] == event)) or
            (kind is not None and r['tag'] == 'FUNCTIONAL_CP_MOVIE_FORMAT_BYTES' and r['fields']['kind'] == kind)]

    def joined(self, rows=None, transport=None):
        return checker.check_cp_movie_format_content(self.run, self.manifest,
            self.rows if rows is None else rows, self.transport if transport is None else transport)

    def test_complete_native_join_keeps_distinct_early_sender_transport_receiver_and_no_frame_scope(self):
        result = self.joined(); value, = result['transactions']
        self.assertTrue(result['verified'] and result['native_completion_verified'] and result['native_control_transaction_verified'])
        self.assertEqual(result['missing_native_observations'], [])
        self.assertEqual((value['strict_initial_sender_tid'], value['sender_tid'], value['receiver_tid']), (87, 96, 97))
        self.assertEqual((value['before_config_generation'], value['config_generation'], value['movie_generation']), (24, 25, 1))
        self.assertTrue(value['native_control_transaction_verified'])
        self.assertTrue(all(result[key] is False for key in ('frame_consumed', 'capture_verified', 'physical_asic_compatibility_verified')))
        aggregate = checker.check_transport(*self.args)
        self.assertEqual(aggregate['movie_format_content'], result)

    def test_actual_EHG_mixed409d_and3012_history_keeps_both_original_opcodes(self):
        self.assertTrue(self.joined()['native_completion_verified'])
        # Exact unrelated original EHG reply-free; never remove it to make409d unique.
        extra, = checker.parse_console((
            'OBS NATIVE_CP_EE_DIAGNOSTIC_REPLY_FREE pid=259 opcode=0x3012 sender_tid=384 waiter_tid=384 '
            'attempts=1 requests=1 busy=0 guard=0 faults=0 source=0x80020002 request_destination=0x90030001 '
            'destination=0x80020002 bytes=24 request=000012302600008000000000000000000000000000000000 '
            'cookie=0x80000026 wire_fnv1a32=0xcd6fc1f1 source_byte1_known=0 reply=010012302600008000f00000 '
            'freed_reply=010012302600008000f00000 reply_free_destination=0x80020002 reply_free_source=0x90030001 '
            'reply_free_bytes=12 allocate_rc=0 send_rc=0 request_free_rc=0 reply_free_rc=0 queued=1 request_freed=1 '
            'reply_freed=1 clean_completion=1 ap_consumed=1 oneway=0 oneway_consumed=0 virtual_field_mask=0 '
            'virtual_fields_readback=0 virtual_fields_consumed=0 virtual_fields=0,0,0,0 virtual_readback=0,0,0,0 '
            'retained_request=(nil) live_reply=(nil) retained_cleanup=(nil) diagnostic_only=1 virtual_padding=1 '
            'business_applied=0 source_dependencies_closed=0 configured=0 published=0 generation=0 native_cp=0 EE=0 frame=0 capture=0\n').encode())
        rows = copy.deepcopy(self.rows)
        first_bank = next(r for r in rows if r['tag'] == 'FUNCTIONAL_CP_PARAMETER_BANK_EVENT')
        extra['line'] = first_bank['line'] - 0.5
        rows.insert(rows.index(first_bank), extra)
        saved = copy.deepcopy(rows)
        self.assertTrue(self.joined(rows)['native_completion_verified'])
        self.assertEqual(rows, saved)
        for key, wrong in (('opcode', '0x3012'), ('attempts', '2'), ('freed_reply', bytes(12).hex()),
                           ('request', bytes(12).hex()), ('reply_free_source', '0x80020002')):
            changed = copy.deepcopy(rows)
            original = next(r for r in changed if r['tag'] == 'NATIVE_CP_EE_DIAGNOSTIC_REPLY_FREE' and
                            r['fields']['opcode'] == '0x409d')
            original['fields'][key] = wrong
            with self.subTest(strict409d=key), self.assertRaises(ValueError):
                self.joined(changed)
        changed = copy.deepcopy(rows)
        original = next(r for r in changed if r['tag'] == 'NATIVE_CP_EE_DIAGNOSTIC_REPLY_FREE' and
                        r['fields']['opcode'] == '0x409d')
        changed.insert(changed.index(original), copy.deepcopy(original))
        with self.assertRaisesRegex(ValueError, 'strict initial409d|preceding strict409d'):
            self.joined(changed)

    def test_current_mode_retirement_requires_its_commit_and_each_actual_role_free(self):
        self.assertTrue(self.joined()['native_completion_verified'])
        begin = self.native(event='BEGIN')[0]
        retired = checker.cp_parameter_mode_retirement(self.rows, begin['line'], 77, 99)
        self.assertEqual((retired['fields']['index'], retired['fields']['role'], retired['fields']['bytes']),
                         ('4', '3', '1748'))
        cycle = retired['fields']['cycle_id']
        commit = next(r for r in self.rows if r['tag'] == 'FUNCTIONAL_CAMERA_CONTROL_COMMIT' and
                      r['fields']['cycle_id'] == cycle)
        self.assertNotEqual(cycle, '0')
        self.assertLess(commit['line'], retired['line'])
        rows = copy.deepcopy(self.rows); rows.remove(next(r for r in rows if r['line'] == commit['line']))
        with self.assertRaisesRegex(ValueError, 'notification free transaction/generation/receiver differs'):
            self.joined(rows)
        for index in range(5):
            tag = 'FUNCTIONAL_CAMERA_CONTROL_' + ('OWNED_FREE' if index in (0, 2) else 'AP_FREE')
            lease = next(r for r in self.rows if r['tag'] == tag and r['fields']['index'] == str(index))
            self.assertEqual((lease['fields']['role'], lease['fields']['bytes']),
                (str(1 if index in (0, 2) else 3 if index == 4 else 2), str((24, 16, 12, 12, 1748)[index])))
            rows = copy.deepcopy(self.rows); rows.remove(next(r for r in rows if r['line'] == lease['line']))
            expected = {0: 'mode lacks all five retired leases', 1: 'current mode lease is live/faulted/unconsumed/foreign',
                        2: 'mode lacks all five retired leases', 3: 'current mode lease is live/faulted/unconsumed/foreign',
                        4: 'historical mode1 before current ACK/full retirement'}[index]
            with self.subTest(missing_actual_free=index), self.assertRaisesRegex(ValueError, expected):
                checker.cp_parameter_mode_retirement(rows, begin['line'], 77, 99)
            with self.assertRaises(ValueError):
                self.joined(rows)
        for key, wrong in (('role', '2'), ('lease_cycle_id', '1'), ('free_tid', '96'), ('cycle_generation', '20')):
            rows = copy.deepcopy(self.rows)
            next(r for r in rows if r['line'] == retired['line'])['fields'][key] = wrong
            with self.subTest(notification=key), self.assertRaisesRegex(ValueError,
                    'notification free transaction/generation/receiver differs'):
                checker.cp_parameter_mode_retirement(rows, begin['line'], 77, 99)
            with self.assertRaises(ValueError):
                self.joined(rows)

    def test_actual_receive_inline_and_request_free_reentrant_snapshots_pass(self):
        for variant in ('normal', 'inline', 'request_free_receive'):
            self.assemble(variant)
            with self.subTest(variant=variant):
                result = self.joined(); self.assertTrue(result['native_completion_verified'])
                value, = result['transactions']
                self.assertEqual((value['sender_tid'], value['receiver_tid']), (96, 97))
                if variant == 'inline':
                    self.assertLess(value['reply_free_line'], self.native(event='SENT')[0]['line'])

    def snapshot_received(self, rows, *events):
        for event in events:
            self.native(rows, event=event)[0]['fields'].update(reply_received='1', receive_rc='0', receiver_tid='97')

    def receive_before(self, event):
        rows = copy.deepcopy(self.rows); receive = self.native(rows, event='RECEIVE')[0]
        rows.remove(receive); rows.insert(rows.index(self.native(rows, event=event)[0]), receive)
        for row, original in zip(rows, self.rows):
            row['line'] = original['line']
        return rows

    def test_sender_can_observe_receive_before_its_log_and_receive_can_observe_sender_before_its_log(self):
        for first in ('SENT', 'REQUEST_FREE', 'COMMIT'):
            rows = copy.deepcopy(self.rows); events = ('SENT', 'REQUEST_FREE', 'COMMIT')
            self.snapshot_received(rows, *events[events.index(first):])
            with self.subTest(sender_first=first):
                self.assertTrue(self.joined(rows)['native_completion_verified'])
        for event, snapshot in (
                ('SENT', dict(busy='1', guard='1', request_freed='0', request_free_rc='-61', request_free_tid='0', retained_request='0x700000')),
                ('REQUEST_FREE', dict(busy='1', guard='1')),
                ('COMMIT', dict(busy='1', guard='0')),
                ('COMMIT', dict(busy='0', guard='0'))):
            rows = self.receive_before(event); self.native(rows, event='RECEIVE')[0]['fields'].update(snapshot)
            self.snapshot_received(rows, *{'SENT': ('REQUEST_FREE', 'COMMIT'), 'REQUEST_FREE': ('COMMIT',), 'COMMIT': ()}[event])
            with self.subTest(receive_before=event, snapshot=snapshot):
                self.assertTrue(self.joined(rows)['native_completion_verified'])

    def test_same_sender_receive_is_supported_without_weakening_the_actual_receive_requirement(self):
        rows = copy.deepcopy(self.rows)
        for row in self.native(rows):
            if row['fields']['event'] == 'RECEIVE':
                row['fields']['tid'] = '96'
            if row['fields']['receiver_tid'] == '97':
                row['fields']['receiver_tid'] = '96'
        self.assertEqual(self.joined(rows)['transactions'][0]['receiver_tid'], 96)
        rows.remove(self.native(rows, event='RECEIVE')[0])
        with self.assertRaises(ValueError):
            self.joined(rows)

    def test_every_real_stage_and_ticket_is_required_once(self):
        for sample in self.native():
            for mutation in ('missing', 'duplicate', 'foreign_ticket'):
                rows = copy.deepcopy(self.rows); row = self.native(rows, event=sample['fields']['event'])[0]
                if mutation == 'missing':
                    rows.remove(row)
                elif mutation == 'duplicate':
                    rows.insert(rows.index(row), copy.deepcopy(row))
                else:
                    row['fields']['transaction'] = '2'
                with self.subTest(event=sample['fields']['event'], mutation=mutation), self.assertRaises(ValueError):
                    self.joined(rows)
        for event in ('REQUEST_FREE', 'REPLY_FREE', 'SENT'):
            rows = copy.deepcopy(self.rows); self.native(rows, event=event)[0]['fields']['tid'] = '97'
            with self.subTest(foreign_sender=event), self.assertRaises(ValueError):
                self.joined(rows)

    def test_full_request_receipt_after_before_and_reply_bytes_reject_every_byte_mutation(self):
        for kind in ('request', 'before_state', 'receipt', 'after_state', 'reply'):
            for sample in self.native(kind=kind):
                for index in range(int(sample['fields']['bytes'])):
                    rows = copy.deepcopy(self.rows)
                    row = next(r for r in self.native(rows, kind=kind) if r['fields']['offset'] == sample['fields']['offset'])
                    raw = bytearray.fromhex(row['fields']['raw']); raw[index] ^= 1; row['fields']['raw'] = raw.hex()
                    with self.subTest(kind=kind, offset=sample['fields']['offset'], byte=index), self.assertRaises(ValueError):
                        self.joined(rows)
            for key, wrong in (('offset', '1'), ('bytes', '1'), ('content_fnv1a', '0000000000000000'),
                               ('movie_generation', '9'), ('transaction', '2')):
                rows = copy.deepcopy(self.rows); self.native(rows, kind=kind)[0]['fields'][key] = wrong
                with self.subTest(kind=kind, field=key), self.assertRaises(ValueError):
                    self.joined(rows)

    def test_all_owner_critical_flags_counters_identities_and_canonical_signed_rc_are_bound(self):
        cases = [('pid', '78'), ('sender_tid', '97'), ('receiver_tid', '98'), ('request_free_tid', '97'), ('reply_free_tid', '97'),
            ('model_instance', '100'), ('bank_generation', '2'), ('crank_generation', '2'), ('movie_generation', '2'),
            ('before_config_generation', '23'), ('config_generation', '26'), ('frame_generation', '2'), ('fps', '60'),
            ('software_format', '6'), ('software_rate_index', '1'), ('software_codec', '0'), ('cookie', '0x80000061'),
            ('native_fnv1a', '0000000000000000'), ('bank_transaction', '1'), ('bank_commits', '0'), ('bank_released', '0'),
            ('bank_native_fnv1a', '0000000000000000'), ('crank_transaction', '2'), ('crank_completions', '0'),
            ('crank_native_fnv1a', '0000000000000000'), ('crank_command', '0x4000'), ('bank_bytes', '2563'),
            ('request_pointer', '0x700001'), ('reply_pointer', '0x800001'), ('allocation_pointer', '0x800001'),
            ('retained_request', '0x700000'), ('retained_reply', '0x800000'), ('faults', '1'), ('error', '-5'),
            ('validation_rc', '-5'), ('before_rc', '-61'), ('model_rc', '-5'), ('after_rc', '-5'), ('allocate_rc', '-12'),
            ('send_rc', '-5'), ('request_free_rc', '-5'), ('receive_rc', '-5'), ('reply_free_rc', '-5'),
            ('busy', '1'), ('guard', '1'), ('request_releasing', '1'), ('reply_releasing', '1'), ('reply_inspecting', '1'),
            ('send_inflight', '1'), ('reply_alias', '1'), ('reply_cleanup_freed', '1'), ('model_called', '0'),
            ('model_committed', '0'), ('verified', '0'), ('owned', '0'), ('complete', '0'), ('request_freed', '0'),
            ('reply_received', '0'), ('reply_freed', '0'), ('reply_consumed', '0'), ('reply_allocated', '0'), ('reply_valid', '0'),
            ('send_started', '0'), ('ACK_sent', '0'), ('requests', '2'), ('commits', '0'), ('verified_commits', '0'),
            ('completions', '0'), ('last_bank_generation', '0'), ('last_crank_generation', '0'), ('last_movie_generation', '0'),
            ('before_used', '127'), ('movie_required', '239'), ('movie_token', '1'), ('after_instance', '100')]
        for key, wrong in cases:
            rows = copy.deepcopy(self.rows); self.native(rows, event='REPLY_FREE')[0]['fields'][key] = wrong
            with self.subTest(field=key), self.assertRaises(ValueError):
                self.joined(rows)
        for pointer in ('0x700000', '0x700004', '0x700010', '0x6ffffc', '0xffffffffffffffff'):
            rows = copy.deepcopy(self.rows)
            for row in self.native(rows):
                for key in ('reply_pointer', 'allocation_pointer', 'retained_reply'):
                    if row['fields'][key] == '0x800000':
                        row['fields'][key] = pointer
            with self.subTest(alias_or_overflow=pointer), self.assertRaises(ValueError):
                self.joined(rows)

    def test_interleaved_snapshots_cannot_forge_receive_regress_sender_or_drop_retained_failure(self):
        for changes in (dict(send_started='0'), dict(send_inflight='1'), dict(ACK_sent='0'), dict(request_releasing='1'),
                dict(busy='0', guard='1'), dict(busy='0', guard='0', request_freed='0', request_free_rc='-61',
                     request_free_tid='0', retained_request='0x700000'), dict(reply_freed='1'),
                dict(reply_received='0'), dict(receiver_tid='0'), dict(receive_rc='-5')):
            rows = copy.deepcopy(self.rows); self.native(rows, event='RECEIVE')[0]['fields'].update(changes)
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                self.joined(rows)
        rows = copy.deepcopy(self.rows); self.snapshot_received(rows, 'SENT', 'COMMIT')
        with self.assertRaisesRegex(ValueError, 'same-sender.*regressed'):
            self.joined(rows)
        rows = copy.deepcopy(self.rows); self.native(rows, event='MODEL')[0]['fields']['validation_rc'] = '-5'
        saved = copy.deepcopy(rows)
        with self.assertRaises(ValueError):
            self.joined(rows)
        self.assertEqual(rows, saved)
        self.assertEqual((self.native(rows, event='MODEL')[0]['fields']['model_rc'],
                          self.native(rows, event='MODEL')[0]['fields']['model_committed']), ('0', '1'))

    def test_resource35_exact_three_tags_full_TTS_dual_DMM_PIN_VEF_and_every_gate_are_required(self):
        for suffix in ('RESOURCE_DEPENDENCIES', 'RESOURCES_TTS_TABLE', 'RESOURCES_RESERVED'):
            for mutation in ('missing', 'duplicate', 'late'):
                rows = copy.deepcopy(self.rows); row = next(r for r in rows if r['tag'] == 'FUNCTIONAL_CP_MOVIE_FORMAT_' + suffix)
                if mutation == 'missing':
                    rows.remove(row)
                elif mutation == 'duplicate':
                    rows.insert(rows.index(row), copy.deepcopy(row))
                else:
                    row['line'] = self.native(event='BEFORE')[0]['line']
                with self.subTest(suffix=suffix, mutation=mutation), self.assertRaises(ValueError):
                    self.joined(rows)
        mutations = [('RESOURCE_DEPENDENCIES', key, '0') for key in
                     ('accepted', 'proc_ap_consumed', 'input_ap_consumed', 'output_ap_consumed', 'current_request_retained_expected')]
        mutations += [('RESOURCES_RESERVED', key, wrong) for key, wrong in (
            ('dmm_slots', '1/0'), ('dmm_opens', '1/2'), ('dmm_handles', '0x8400/0x8402'), ('dmm_generations', '1/2'),
            ('dmm_epochs', '1/3'), ('dmm_creators', '1/0'), ('dmm_domain', '0'), ('dmm_lifecycle_changed', '1'),
            ('allocations', '5'), ('vef_live', '1'), ('pinmem_retained', '1'), ('control_faults', '1'),
            ('format_pending', '1'), ('blocked', '1'), ('connection_faults', '1'), ('tid', '97'))]
        for suffix, key, wrong in mutations:
            rows = copy.deepcopy(self.rows)
            next(r for r in rows if r['tag'] == 'FUNCTIONAL_CP_MOVIE_FORMAT_' + suffix)['fields'][key] = wrong
            with self.subTest(suffix=suffix, field=key), self.assertRaises(ValueError):
                self.joined(rows)
        for offset in (0, 0x18, 0x20, 0x48, 0x60, 0x68):
            rows = copy.deepcopy(self.rows)
            f = next(r['fields'] for r in rows if r['tag'] == 'FUNCTIONAL_CP_MOVIE_FORMAT_RESOURCES_TTS_TABLE')
            raw = bytearray.fromhex(f['raw_before']); raw[offset] ^= 1; f['raw_before'] = f['raw_after'] = raw.hex()
            with self.subTest(TTS_offset=offset), self.assertRaises(ValueError):
                self.joined(rows)

    def test_native_bank_crank_cannot_be_replaced_by_caller_booleans_or_old_transaction(self):
        for tag, event, key, wrong in (
                ('FUNCTIONAL_CP_PARAMETER_BANK_EVENT', 'OWNED_FREE', 'request_freed', '0'),
                ('FUNCTIONAL_CP_PARAMETER_BANK_EVENT', 'COMMIT', 'transaction', '3'),
                ('FUNCTIONAL_CP_CRANK_CONTROL_EVENT', 'REQUEST_FREE', 'request_free_rc', '-5'),
                ('FUNCTIONAL_CP_CRANK_CONTROL_EVENT', 'RECEIVE', 'transaction', '2'),
                ('FUNCTIONAL_CP_CRANK_CONTROL_EVENT', 'REPLY_FREE', 'reply_free_tid', '95'),
                ('FUNCTIONAL_CP_CRANK_CONTROL_EVENT', 'REPLY_FREE', 'complete', '0')):
            rows = copy.deepcopy(self.rows)
            next(r for r in rows if r['tag'] == tag and r['fields']['event'] == event)['fields'][key] = wrong
            with self.subTest(predecessor=tag, event=event, field=key), self.assertRaises(ValueError):
                self.joined(rows)
        rows = [r for r in copy.deepcopy(self.rows) if not r['tag'].startswith('FUNCTIONAL_CP_CRANK_CONTROL_')]
        with self.assertRaises(ValueError):
            self.joined(rows)

    def test_all13_current_mode_and_single_initial4000_history_must_remain_real(self):
        cases = [(tag, 'rc', '-5') for tag in checker.BACKGROUND_FREE_TAGS]
        cases += [('NATIVE_CP302C_NOCONVERT_ALL13_READBACK', 'accepted', '0'),
            ('FUNCTIONAL_CAMERA_CONTROL_AP_FREE', 'mode_complete', '0'),
            ('FUNCTIONAL_CAMERA_CONTROL_AP_FREE', 'free_tid', '96'),
            ('NATIVE_CP_MOVIE_FORMAT_DIAGNOSTIC_REPLY_FREE', 'attempts', '2'),
            ('NATIVE_CP_MOVIE_FORMAT_DIAGNOSTIC_REPLY_FREE', 'waiter_tid', '96'),
            ('NATIVE_CP_MOVIE_FORMAT_DIAGNOSTIC_REPLY_FREE', 'freed_reply', bytes(12).hex()),
            ('NATIVE_CP_MOVIE_FORMAT_DIAGNOSTIC_REPLY_FREE', 'virtual_fields_consumed', '0'),
            ('NATIVE_CP_MOVIE_FORMAT_DIAGNOSTIC_COMPLETE', 'native_verified', '1')]
        for tag, key, wrong in cases:
            rows = copy.deepcopy(self.rows); [r for r in rows if r['tag'] == tag][-1]['fields'][key] = wrong
            with self.subTest(tag=tag, field=key), self.assertRaises(ValueError):
                self.joined(rows)
        for tag in ('NATIVE_CP_MOVIE_FORMAT_DIAGNOSTIC_REQUEST_FREE', 'NATIVE_CP_MOVIE_FORMAT_DIAGNOSTIC_REPLY_FREE',
                    'NATIVE_CP_MOVIE_FORMAT_DIAGNOSTIC_COMPLETE'):
            for duplicate in (False, True):
                rows = copy.deepcopy(self.rows); row = next(r for r in rows if r['tag'] == tag)
                if duplicate:
                    rows.insert(rows.index(row), copy.deepcopy(row))
                else:
                    rows.remove(row)
                with self.subTest(tag=tag, duplicate=duplicate), self.assertRaises(ValueError):
                    self.joined(rows)

    def test_original20_audit_pointer_source_size_and_sender_are_bound(self):
        for key, wrong in (('pointer', '0x700001'), ('source', '0x90030001'), ('bytes', '12'), ('tid', '94'),
                           ('producer_return', '0x3535b04'), ('complete', '0')):
            rows = copy.deepcopy(self.rows)
            next(r for r in rows if r['tag'] == 'NATIVE_CP_BACKGROUND_INPUT_AUDIT' and
                 r['fields'].get('sequence') == '72')['fields'][key] = wrong
            with self.subTest(field=key), self.assertRaises(ValueError):
                self.joined(rows)

    def test_movie_partial_frame_proofs_fail_before_any_history_or_predecessor_scan(self):
        for index in (7, 8, 9):
            for proof in ({}, {'proof': {}}, {'proof': {'opcode': 22}}):
                changed = copy.deepcopy(self.transport); changed['transfers'][index]['frame'] = proof
                with mock.patch.object(checker, 'vdf_history') as history, mock.patch.object(checker, 'check_cp_parameter_bank') as bank:
                    with self.subTest(index=index, proof=proof), self.assertRaisesRegex(ValueError, 'no-frame'):
                        self.joined(transport=changed)
                    history.assert_not_called(); bank.assert_not_called()

    def test_typed_movie_success_kind_opcode_origin_and_actual_commit_cannot_be_borrowed(self):
        for key, wrong in (('kind', 'model_crank_control'), ('opcode', 21), ('actual_c_result', False),
                           ('model_called', False), ('model_committed', False), ('native_acceptance', True),
                           ('sequence', 6), ('model_instance', 100)):
            changed = copy.deepcopy(self.transport); changed['transfers'][8]['movie_format'][key] = wrong
            with mock.patch.object(checker, 'vdf_history') as history:
                with self.subTest(field=key), self.assertRaises(ValueError):
                    self.joined(transport=changed)
                history.assert_not_called()
        changed = copy.deepcopy(self.transport)
        event = changed['transfers'][8]['movie_format']
        event.update(kind='movie_format_rejected', actual_c_result=0, model_committed=True, error='post-C0 independent query failed')
        event['observation'].update(query_c_result=-5, readback_verified=False)
        saved = copy.deepcopy(event)
        with mock.patch.object(checker, 'vdf_history') as history:
            with self.assertRaises(checker.MovieFormatRejected) as caught:
                self.joined(transport=changed)
            history.assert_not_called()
        self.assertEqual(caught.exception.event, saved)
        self.assertEqual(caught.exception.event['actual_c_result'], 0)
        self.assertIs(caught.exception.event['model_committed'], True)

    def test_exact_106_19_schemas_match_actual_owner_formatter_and_metadata_readbacks(self):
        source = (checker.NATIVE / 'runtime/analysis/device-models/functional-camera-control.c').read_text()
        block = source[source.index('static void movie_format_record('):source.index('static int movie_format_crank_ready(')]
        formats = re.findall(r'snprintf\(text, sizeof text,\s*((?:"[^"\n]*"\s*)+)', block)
        self.assertEqual(len(formats), 2)
        self.assertIn('s = *observed', block)
        self.assertNotIn('native_functional_camera_movie_format_snapshot(', block)
        for schema, formatter, count in zip((checker.CP_MOVIE_EVENT_SCHEMA, checker.CP_MOVIE_BYTES_SCHEMA), formats, (106, 19)):
            keys = re.findall(r'([A-Za-z_][A-Za-z_0-9]*)=', ''.join(re.findall(r'"([^"\n]*)"', formatter)))
            self.assertEqual(len(keys), count)
            self.assertEqual(keys, [part.split(':', 1)[0] for part in schema.split()])
        wire = source[source.index('static int movie_format_wire_matches('):source.index('static int movie_format_context_matches(')]
        self.assertIn('actual_bytes = io->size(pointer), actual_source = io->source(pointer)', wire)
        self.assertIn('actual_bytes == bytes && actual_source == source', wire)
        self.assertIn('memcmp(pointer, expected, bytes)', wire)
        receive = source[source.index('int native_functional_camera_movie_format_release('):source.index('static void movie_format_finish(')]
        for text in ('transaction != movie_format_state.transaction', 'current_tid != movie_format_state.sender_tid',
                     'event->source != FUNCTIONAL_CAMERA_CONTROL_SID', 'event->bytes != 12', 'movie_format_state.receiver_tid = current_tid'):
            self.assertIn(text, receive)

    def test_main_ticket_is_same_pid_mutex_bound_and_retained_after_real_free(self):
        source = (checker.NATIVE / 'runtime/analysis/menu-observe.c').read_text()
        self.assertIn('functional_cp_movie_format_reserve_resources(void) {return tracked_native_reserve_resources(35);}', source)
        begin = source.index('static uint64_t native_movie_format_ticket_for(')
        end = source.index('static void native_movie_format_received(', begin)
        lookup = source[begin:end]
        self.assertIn('functional_cp_movie_format_ticket_pid!=(unsigned int)getpid()', lookup)
        self.assertIn('pthread_mutex_lock(functional_cp_movie_format_ticket_mutex)', lookup)
        self.assertNotIn('native_functional_camera_movie_format_snapshot', lookup)
        receive = source[end:source.index('int osal_rcv_msg_tmo(', end)]
        self.assertIn('native_movie_format_ticket_for(destination,pointer),&event', receive)
        start = source.index('if(__atomic_load_n(&functional_cp_movie_format_used', source.index('int osal_free_msg('))
        free = source[start:source.index('if(__atomic_load_n(&functional_cp_crank_control_used', start)]
        self.assertIn('native_movie_format_ticket_for(id,message),0', free)
        self.assertNotIn('=0;', free)
        self.assertNotRegex(source, r'_Thread_local[^;]*functional_cp_movie_format_ticket')

    def test_movie_parser_exact_order_types_signed_bounds_and_kernel_trailers(self):
        samples = [r for r in self.rows if r['tag'].startswith('FUNCTIONAL_CP_MOVIE_FORMAT_')]
        trailers = (b'[ 5638.875229] UDIF: cdev_ioctl() Line 100: uipc: warning ret = -1022',
                    b'[ 5541.864466] [K]**UIPC ERROR** free_dynamic_msgq_id: QID[81cf61c4] M=1 C=0 S=0 A=1')
        for sample in samples:
            payload = self.record(sample['tag'], sample['fields']).encode()
            self.assertEqual(checker.console_producer_fields(payload), sample['fields'])
            for trailer in trailers:
                for ending in (b'\n', b'\r\n'):
                    raw = b'ordinary\nOBS ' + payload + trailer + ending
                    row, = checker.parse_console(raw)
                    self.assertEqual(row['fields'], sample['fields']); self.assertIn('kernel_diagnostic', row)
                    note = row['kernel_diagnostic']
                    self.assertEqual((note['payload']['byte_offset'], note['raw_lf_line']), (len(b'ordinary\nOBS '), 2))
                    self.assertEqual(note['line_ending'], ending.decode())
                    for part in (note, note['payload']):
                        self.assertEqual(raw[part['byte_offset']:part['byte_offset'] + part['bytes']], part['raw'].encode())
                        self.assertEqual(checker.sha(part['raw'].encode()), part['sha256'])
            parts = payload.split(b' ')
            for bad in (payload + b' unknown=0', b' '.join(parts[:2] + parts[3:]),
                        b' '.join(parts[:1] + [parts[2], parts[1]] + parts[3:])):
                with self.subTest(tag=sample['tag'], bad=bad):
                    self.assertIsNone(checker.console_producer_fields(bad))
                    for trailer in trailers:
                        row, = checker.parse_console(b'OBS ' + bad + trailer + b'\n')
                        self.assertIn('diagnostic', row); self.assertNotIn('kernel_diagnostic', row)
            for bad in (payload.replace(sample['tag'].encode(), b'FUNCTIONAL_CP_MOVIE_FORMAT_UNKNOWN', 1) + trailers[0],
                        payload + trailers[0].replace(b'-1022', b'-1021'),
                        payload + trailers[1].replace(b'A=1', b'A=0'), payload + trailers[0] + trailers[1]):
                row, = checker.parse_console(b'OBS ' + bad + b'\n')
                self.assertIn('diagnostic', row); self.assertNotIn('kernel_diagnostic', row)
            with self.assertRaises(ValueError):
                checker.console_producer_fields(payload + b' ' + parts[1])
        begin = self.native(event='BEGIN')[0]
        payload = self.record(begin['tag'], begin['fields']).encode()
        for old, wrong in ((b'before_rc=-61', b'before_rc=-061'), (b'before_rc=-61', b'before_rc=+0'),
                           (b'before_rc=-61', b'before_rc=-2147483649'), (b'transaction=1', b'transaction=01'),
                           (b'transaction=1', b'transaction=18446744073709551616'), (b'sender_tid=96', b'sender_tid=9223372036854775808'),
                           (b'bytes=20', b'bytes=4294967296'), (b'capture_verified=0', b'capture_verified=1')):
            self.assertIsNone(checker.console_producer_fields(payload.replace(old, wrong)))
        with self.assertRaises(ValueError):
            checker.number('-61')

class CPOuCrankControlEvidenceTests(unittest.TestCase):
    """Exact OP23 wire fixtures; no model, native VM or capture is executed."""

    def setUp(self):
        base = CPCrankControlEvidenceTests('runTest'); base.setUp()
        prior = bytearray(base.prior); struct.pack_into('<Q', prior, 56, 26)
        self.prior, self.packet = bytes(prior), self.request()
        self.raw = self.receipt(self.packet, self.prior)

    @staticmethod
    def request(byte1=0xa5, cookie=0x80000061):
        return struct.pack('<BBHI', 5, byte1, 0x4072, cookie) + bytes(4)

    @staticmethod
    def receipt(packet, prior, ou=1, bank=4, crank=2, movie=1):
        before = struct.unpack_from('<Q', prior, 56)[0]
        after = bytearray(prior); struct.pack_into('<Q', after, 56, (before + 1) % 2**64)
        raw = bytearray(224)
        struct.pack_into('<2I8Q2I', raw, 0, 1, 224, struct.unpack_from('<Q', prior, 48)[0],
            ou, bank, crank, movie, before, (before + 1) % 2**64, checker.fnv(packet), 0,
            struct.unpack_from('<I', prior, 16)[0])
        raw[80:208], raw[208:220] = after, packet
        return bytes(raw)

    @staticmethod
    def observation(raw, packet, prior, proof, capacity=checker.DATA_BYTES):
        return dict(actual_c_result=0, returned_hex=raw.hex(), readback_verified=True, model_called=True,
            model_committed=True, input_hex=packet.hex(), request_hex=packet.hex(), input_fnv1a64=checker.fnv(packet),
            software_mode='ou_crank_mode0', validation_error=None, ou_generation=struct.unpack_from('<Q', raw, 16)[0],
            bank_generation=struct.unpack_from('<Q', raw, 24)[0], crank_generation=struct.unpack_from('<Q', raw, 32)[0],
            movie_generation=struct.unpack_from('<Q', raw, 40)[0], predecessor_proof=copy.deepcopy(proof),
            before_state_c_result=0, before_state_hex=prior.hex(), c_call_succeeded=True, returned_bytes=224,
            returned_fnv1a64=checker.fnv(raw), output_buffer_hex=(raw + bytes(capacity - 224)).hex(),
            result=dict(token=0, total=0, offset=0, used=224), after_state_c_result=0,
            after_state_hex=raw[80:208].hex(), query_c_result=0, snapshot_hex=raw.hex(), state_delta_verified=True)

    def decode(self, raw=None, packet=None, prior=None, instance=99, bank=4, crank=2, movie=1):
        return checker.cp_ou_crank_control_result(self.raw if raw is None else raw,
            self.packet if packet is None else packet, instance, self.prior if prior is None else prior, bank, crank, movie)

    def test_full224_preserves_every_nonconfig_byte_and_all_nonzero_counters(self):
        value = self.decode()
        self.assertEqual(value, dict(model_instance=99, ou_generation=1, bank_generation=4, crank_generation=2,
            movie_generation=1, before_config_generation=26, config_generation=27, input_fnv=checker.fnv(self.packet),
            mode=0, fps=30, frame_generation=22))
        self.assertEqual(self.raw[80:136], self.prior[:56])
        self.assertEqual(self.raw[144:208], self.prior[64:])
        self.assertEqual(self.raw[208:], self.packet + bytes(4))
        for fps in (1, 60, 120):
            prior = bytearray(self.prior); struct.pack_into('<I', prior, 16, fps); prior = bytes(prior)
            self.assertEqual(self.decode(raw=self.receipt(self.packet, prior), prior=prior)['fps'], fps)

    def test_original_byte1_cookie_opaque_and_zero_body_is_exact(self):
        for byte1, cookie in ((0, 0), (0xff, 0xffffffff), (0xa5, 0x80000061)):
            packet = self.request(byte1, cookie)
            self.assertEqual(self.decode(raw=self.receipt(packet, self.prior), packet=packet)['input_fnv'], checker.fnv(packet))
        for offset in (0, 2, 3, 8, 9, 10, 11):
            packet = bytearray(self.packet); packet[offset] ^= 1; packet = bytes(packet)
            with self.subTest(offset=offset), self.assertRaisesRegex(ValueError, 'original12'):
                self.decode(raw=self.receipt(packet, self.prior), packet=packet)
        for packet in (b'', self.packet[:-1], self.packet + b'\0', bytearray(self.packet)):
            with self.subTest(size=len(packet)), self.assertRaises(ValueError):
                self.decode(packet=packet)

    def test_all224_bytes_and_tuple_types_have_content_or_history_guards(self):
        for offset in range(224):
            raw = bytearray(self.raw); raw[offset] ^= 1
            if 16 <= offset < 24:
                continue  # Positive OU-generation jumps are rejected by the monotonic history checker.
            with self.subTest(offset=offset), self.assertRaises(ValueError):
                self.decode(raw=bytes(raw))
        for key in ('instance', 'bank', 'crank', 'movie'):
            for wrong in (0, -1, 2**64, True, 1.0, '1'):
                with self.subTest(key=key, wrong=wrong), self.assertRaises(ValueError):
                    self.decode(**{key: wrong})
        for prior_offset in (0, 4, 48, 104, 108, 120):
            prior = bytearray(self.prior); prior[prior_offset] ^= 1; prior = bytes(prior)
            with self.subTest(prior_offset=prior_offset), self.assertRaises(ValueError):
                self.decode(raw=self.receipt(self.packet, prior), prior=prior)
        for generation in (0, 2**64 - 1):
            prior = bytearray(self.prior); struct.pack_into('<Q', prior, 56, generation); prior = bytes(prior)
            with self.subTest(generation=generation), self.assertRaises(ValueError):
                self.decode(raw=self.receipt(self.packet, prior), prior=prior)
        raw = bytearray(self.raw); struct.pack_into('<Q', raw, 16, 0)
        with self.assertRaises(ValueError):
            self.decode(raw=bytes(raw))

    def test_exact13_policy_optional_all_or_none_and_typed_on_both_sides(self):
        profile = CPParameterBankEvidenceTests.profile()
        for target in (profile, profile['backup_transport']):
            for key in checker.CP_OU_CRANK_CONTROL_POLICY:
                target.pop('functional_camera_' + key, None)
        self.assertTrue(checker.check_profile(profile)['verified'])
        self.assertEqual(len(checker.CP_OU_CRANK_CONTROL_POLICY), 13)
        for target in (profile, profile['backup_transport']):
            target.update({'functional_camera_' + k: copy.deepcopy(v) for k, v in checker.CP_OU_CRANK_CONTROL_POLICY.items()})
        self.assertTrue(checker.check_profile(profile)['verified'])
        for side in ('manifest', 'backup'):
            for key, value in checker.CP_OU_CRANK_CONTROL_POLICY.items():
                changed = copy.deepcopy(profile); target = changed if side == 'manifest' else changed['backup_transport']
                del target['functional_camera_' + key]
                with self.subTest(side=side, missing=key), self.assertRaisesRegex(ValueError, 'profile drift'):
                    checker.check_profile(changed)
                changed = copy.deepcopy(profile); target = changed if side == 'manifest' else changed['backup_transport']
                target['functional_camera_' + key] = True if type(value) is int else 'unsupported'
                with self.subTest(side=side, wrong=key), self.assertRaisesRegex(ValueError, 'profile drift'):
                    checker.check_profile(changed)
        changed = copy.deepcopy(profile); changed['functional_camera_cp_ou_crank_control_ready'] = True
        with self.assertRaisesRegex(ValueError, 'undeclared OU'):
            checker.check_profile(changed)


class CPOuCrankWitnessEvidenceTests(unittest.TestCase):
    """Use a complete existing4057 RGB proof; OP23 itself owns no frame proof."""

    def setUp(self):
        fixture = StartupControlEvidenceTests('runTest'); fixture.setUp(); self.addCleanup(fixture.doCleanups)
        args = fixture.replay(commands=(0x4014, 0x4057), cookies=(0x8000003c, 0x80000026))
        transport = checker.check_transport(*args)
        self.assertTrue(transport['startup_control']['verified'])
        tx = next(t for t in reversed(transport['transfers']) if t['opcode'] == 14)
        self.proof = tx['frame']['proof']
        self.prior = checker.transfer_output(args[0], transport['transfers'][-1])
        self.packet = CPOuCrankControlEvidenceTests.request()
        self.raw = CPOuCrankControlEvidenceTests.receipt(self.packet, self.prior)
        self.observed = CPOuCrankControlEvidenceTests.observation(self.raw, self.packet, self.prior, self.proof)
        self.origin = dict(producer_tid=384, source=0x80020002, destination=0x90030001,
                           command=0x4072, bytes=12, fnv1a64=checker.fnv(self.packet))
        self.witness = dict(event=1, monotonic_ns=1, kind='model_ou_crank_control', model_instance=99, sequence=1,
            opcode=23, actual_c_result=0, actual_core_sha256='a' * 64, admission_error=None,
            origin=copy.deepcopy(self.origin), native_acceptance=False, model_called=True, model_committed=True,
            input_hex=self.packet.hex(), request_fnv1a64=checker.fnv(self.packet), observation=self.observed,
            error=0, validation_error=None)
        for key, data, direction in (('request_payload', self.packet, 'in'), ('output_payload', self.raw, 'out')):
            self.witness[key] = dict(bytes=len(data), direction=direction, opcode=23, sequence=1,
                                     model_instance=99, origin=copy.deepcopy(self.origin))

    encoded = staticmethod(CPBoundedWitnessJSONLEvidenceTests.encoded)

    def observed_value(self, observed):
        return checker.cp_ou_crank_control_observation(observed, self.raw, self.packet, 99, self.prior, 4, 2, 1, checker.DATA_BYTES)

    def test_actual_c_full_buffer_getter_and_all_observation_fields_are_bound(self):
        self.assertEqual(self.observed_value(self.observed)['config_generation'], struct.unpack_from('<Q', self.prior, 56)[0] + 1)
        for key in self.observed:
            observed = copy.deepcopy(self.observed); del observed[key]
            with self.subTest(missing=key), self.assertRaisesRegex(ValueError, 'independent actual C'):
                self.observed_value(observed)
        for key, wrong in (('actual_c_result', False), ('query_c_result', -5), ('c_call_succeeded', False),
                ('model_committed', False), ('state_delta_verified', False), ('state_delta_verified', 1),
                ('validation_error', 'post-C0 failure'), ('ou_generation', 2),
                ('movie_generation', 2), ('software_mode', 'mode1'), ('returned_bytes', 223)):
            observed = copy.deepcopy(self.observed); observed[key] = wrong
            with self.subTest(field=key), self.assertRaises(ValueError):
                self.observed_value(observed)
        for key in ('returned_hex', 'snapshot_hex', 'output_buffer_hex', 'after_state_hex', 'before_state_hex', 'request_hex', 'input_hex'):
            observed = copy.deepcopy(self.observed); raw = bytearray.fromhex(observed[key]); raw[-1] ^= 1; observed[key] = raw.hex()
            with self.subTest(bytes=key), self.assertRaises(ValueError):
                self.observed_value(observed)

    def test_only_successful_fixed12_224_full_Cbuffer_gets192KiB_allowance(self):
        self.assertTrue(checker.bounded_control_witness(self.witness))
        self.assertEqual(checker.jsonl(self.encoded(self.witness, 192 * 1024)), [self.witness])
        with self.assertRaisesRegex(ValueError, 'oversized non-source'):
            checker.jsonl(self.encoded(self.witness, 192 * 1024 + 1))
        for key, wrong in (('kind', 'ou_crank_control_rejected'), ('kind', 'response'), ('kind', 'unknown'),
                ('opcode', 22), ('opcode', True), ('actual_c_result', False), ('actual_c_result', -5),
                ('model_committed', False), ('validation_error', 'error'), ('admission_error', -16)):
            witness = copy.deepcopy(self.witness); witness[key] = wrong
            with self.subTest(field=key), self.assertRaises(ValueError):
                checker.jsonl(self.encoded(witness))
        for key in ('request_payload', 'output_payload'):
            witness = copy.deepcopy(self.witness); witness[key]['bytes'] -= 1
            with self.subTest(reference=key), self.assertRaises(ValueError):
                checker.jsonl(self.encoded(witness))
        witness = copy.deepcopy(self.witness); witness['observation']['output_buffer_hex'] += '00'
        with self.assertRaisesRegex(ValueError, 'capacity'):
            checker.jsonl(self.encoded(witness))

    def test_native_missing_is_fail_closed_even_with_caller_ready_booleans(self):
        tx = dict(first=1, last=1, line=20, opcode=23, origin=self.origin, token=0, frame=None, provider_kind='core',
            request_payload=self.witness['request_payload'], output_payloads=[self.witness['output_payload']],
            ou_crank_control=self.witness, capacity=checker.DATA_BYTES)
        before = dict(tx, first=0, last=0, line=10, opcode=2)
        after = dict(tx, first=2, last=2, line=30, opcode=2)
        policy = {'functional_camera_' + k: copy.deepcopy(v) for k, v in checker.CP_OU_CRANK_CONTROL_POLICY.items()}
        policy['functional_camera_profile'] = checker.PROFILE
        manifest = dict(policy, backup_transport=copy.deepcopy(policy))
        transport = dict(model_instance=99, transfers=[before, tx, after],
            parameter_bank={'verified': True}, crank_control_content={'verified': True}, movie_format_content={'verified': True},
            startup_control={'verified': True})
        with self.assertRaisesRegex(checker.MissingEvidence, 'original one-way EVENT/BYTES/resource36 records missing'):
            checker.check_cp_ou_crank_control_content(None, manifest, [], transport)
        event = copy.deepcopy(self.witness); event.update(kind='ou_crank_control_rejected', actual_c_result=0,
            model_committed=True, validation_error='independent getter failed')
        event['observation'].update(query_c_result=-5, readback_verified=False)
        tx['ou_crank_control'] = event
        with self.assertRaises(checker.OuCrankControlRejected) as caught:
            checker.check_cp_ou_crank_control_content(None, manifest, [], transport)
        self.assertEqual(caught.exception.event, event)
        self.assertEqual(caught.exception.event['actual_c_result'], 0)
        self.assertIs(caught.exception.event['model_committed'], True)


class CPOuCrankNativeEvidenceTests(unittest.TestCase):
    """Complete synthetic OU formatter streams; direct helper results are not AP acceptance."""

    @classmethod
    def setUpClass(cls):
        CPMovieFormatNativeJoinEvidenceTests.setUpClass()

    row = staticmethod(CPCrankNativeJoinEvidenceTests.row)
    record = staticmethod(CPParameterBankTransportEvidenceTests.record)

    def setUp(self):
        base = CPMovieFormatNativeJoinEvidenceTests('runTest'); base.setUp(); self.addCleanup(base.doCleanups)
        self.assertTrue(base.joined()['native_control_transaction_verified'])
        startup_fixture = StartupControlEvidenceTests('runTest'); startup_fixture.setUp(); self.addCleanup(startup_fixture.doCleanups)
        source_args = startup_fixture.replay(commands=(0x4014, 0x4057), cookies=(0x8000003c, 0x80000026))
        source = checker.check_transport(*source_args)
        source_vdf = next(t for t in source['transfers'] if t['opcode'] == 5)
        self.movie_prior = base.raw[80:208]
        movie_cfg = struct.unpack_from('<Q', self.movie_prior, 56)[0]
        movie_frame = struct.unpack_from('<Q', self.movie_prior, 112)[0]
        vdf_cfg, vdf_frame, vdf_lease = movie_cfg + 1, movie_frame + 1, movie_frame + 1
        # Commit the replay's complete enabled OP5 before borrowing its route for4057.
        vdf_canonical = checker.payload_read(source_args[0], source_vdf['request_payload'])
        vdf_raw = bytearray(checker.transfer_output(source_args[0], source_vdf))
        struct.pack_into('<4Q', vdf_raw, 8, 99, vdf_cfg, vdf_frame, vdf_lease)
        struct.pack_into('<2Q', vdf_raw, 144, movie_frame, movie_cfg)
        vdf_raw = bytes(vdf_raw)
        vdf_proof = copy.deepcopy(source_vdf['frame']['proof'])
        counts = struct.unpack_from('<4Q', self.movie_prior, 64)
        vdf_proof.update(serial=movie_frame + 1, config_generation=vdf_cfg, frame_generation=vdf_frame,
                         lease_generation=vdf_lease)
        vdf_proof['before'] = dict(zip(('rendered', 'consumed', 'jpeg_encoded', 'video_encoded'), counts), retired=counts[0])
        vdf_proof['after'] = dict(vdf_proof['before'])
        for key in ('rendered', 'consumed', 'retired'):
            vdf_proof['after'][key] += 1
        vdf_state = bytearray(self.movie_prior)
        for offset in (56, 64, 72, 112):
            struct.pack_into('<Q', vdf_state, offset, struct.unpack_from('<Q', vdf_state, offset)[0] + 1)
        vdf_state = bytes(vdf_state)
        startup_cfg, startup_frame, startup_lease = vdf_cfg + 1, vdf_frame + 1, vdf_lease + 1
        self.startup_wire = bytes.fromhex('050057406100008000000000')
        startup_origin = dict(producer_tid=90, source=0x80020002, destination=0x90030001, command=0x4057,
                              bytes=12, fnv1a64=checker.fnv(self.startup_wire))
        startup_raw, canonical = StartupControlEvidenceTests.receipt(0x4057, checker.fnv(vdf_state[8:48]))
        startup_raw = bytearray(startup_raw)
        struct.pack_into('<4Q', startup_raw, 8, 99, startup_cfg, startup_frame, startup_lease)
        struct.pack_into('<2Q', startup_raw, 48, vdf_proof['source_fnv1a64'], vdf_proof['source_fnv1a64'])
        startup_raw[128:144] = vdf_raw[128:144]
        struct.pack_into('<2Q', startup_raw, 144, vdf_frame, vdf_cfg)
        startup_raw = bytes(startup_raw)
        p = copy.deepcopy(vdf_proof)
        p.update(serial=vdf_proof['serial'] + 1, opcode=14, config_generation=startup_cfg,
                 frame_generation=startup_frame, lease_generation=startup_lease, result_bytes=192,
                 result_fnv1a64=checker.fnv(startup_raw), result_token=0)
        p['before'] = dict(vdf_proof['after'])
        p['after'] = dict(p['before'])
        for key in ('rendered', 'consumed', 'retired'):
            p['after'][key] += 1
        self.prior = bytearray(vdf_state)
        for offset in (56, 64, 72, 112):
            struct.pack_into('<Q', self.prior, offset, struct.unpack_from('<Q', self.prior, offset)[0] + 1)
        self.prior = bytes(self.prior)
        self.packet = CPOuCrankControlEvidenceTests.request()
        self.raw = CPOuCrankControlEvidenceTests.receipt(self.packet, self.prior, bank=1, crank=1, movie=1)
        self.origin = dict(startup_origin, producer_tid=98, command=0x4072, fnv1a64=checker.fnv(self.packet))
        operations = [dict(op=t['opcode'], data=checker.payload_read(base.run, t['request_payload']),
            output=checker.transfer_output(base.run, t), origin=t['origin'],
            **({'proof': t['frame']['proof']} if t.get('frame') else {})) for t in base.transport['transfers']]
        operations += [dict(op=5, data=vdf_canonical, output=vdf_raw, origin=source_vdf['origin'], proof=vdf_proof),
            dict(op=14, data=canonical, output=startup_raw, origin=startup_origin, proof=p),
            dict(op=2, data=b'', output=self.prior, origin=self.origin),
            dict(op=23, data=self.packet, output=self.raw, origin=self.origin),
            dict(op=2, data=b'', output=self.raw[80:208], origin=self.origin)]
        rows = copy.deepcopy(base.rows)
        # Preserve the already-used cold4072 as its own two original one-way events.
        strict = CPCrankNativeJoinEvidenceTests('runTest').strict_history()[:2]
        wire = bytes.fromhex('050072402600008000000000')
        digest = 2166136261
        for byte in wire:
            digest = ((digest ^ byte) * 16777619) & 0xffffffff
        for ordinal, r in enumerate(strict):
            r['fields'].update(opcode='0x4072', waiter_tid='0', destination='0', request=wire.hex(), cookie='0x80000026',
                wire_fnv1a32=hex(digest), reply='none', freed_reply='none', queued='0', oneway='1', oneway_consumed='1',
                virtual_field_mask='0x3', virtual_fields_consumed='0x3', live_reply='(nil)', clean_completion=str(ordinal))
        at = next(i for i, r in enumerate(rows) if r['tag'] == 'FUNCTIONAL_CP_PARAMETER_BANK_EVENT')
        rows[at:at] = strict
        # A complete4057 sender lifecycle is kept as native input, not a ready boolean.
        rows.append(self.row('FUNCTIONAL_CAMERA_TRANSFER', {'HOST_TEST_marker': len(base.transport['transfers'])}))
        rows.append(self.row('FUNCTIONAL_CAMERA_TRANSFER', {'HOST_TEST_marker': len(base.transport['transfers']) + 1}))
        for r in source_args[2]:
            if r['tag'] == 'FUNCTIONAL_STARTUP_CONTROL' and r['fields'].get('cycle') == '2':
                r = copy.deepcopy(r)
                r['fields'].update(before_cfg=str(vdf_cfg), cfg=str(startup_cfg), before_frame=str(vdf_frame),
                    frame=str(startup_frame), lease=str(startup_lease),
                    origin_fnv=f'{checker.fnv(self.startup_wire):016x}', config40_fnv=f'{checker.fnv(self.prior[8:48]):016x}',
                    result_fnv=f'{checker.fnv(startup_raw):016x}')
                rows.append(r)
                if r['fields']['event'] == 'REQUEST_FREE':
                    ticket = copy.deepcopy(next(t for t in source_args[2] if t['tag'] == 'FUNCTIONAL_STARTUP_CONTROL_TICKET_BOUND' and
                                                t['fields']['cycle'] == '2'))
                    ticket['fields'].update(cookie='0x80000061', reply=(b'\x01\0\x57\x40' + self.startup_wire[4:8] + struct.pack('<I', 0xf000)).hex())
                    rows.append(ticket)
        self.startup = dict(cycle=2, first=len(base.transport['transfers']) + 2, cookie=0x80000061, original_wire=self.startup_wire.hex(),
            original_fnv1a64=f'{checker.fnv(self.startup_wire):016x}', result_fnv1a64=f'{checker.fnv(startup_raw):016x}',
            model_instance=99, config_generation=startup_cfg, frame_generation=startup_frame, lease_generation=startup_lease, sender_tid=90,
            receiver_tid=355, AP_consumed=True, command=0x4057, config40_fnv1a64=f'{checker.fnv(self.prior[8:48]):016x}')
        resources = checker.parse_console(JFZ_VDF_RESOURCE_OBS.replace('FUNCTIONAL_VDF_PATH_',
            'FUNCTIONAL_CP_OU_CRANK_CONTROL_').replace('pid=258', 'pid=77').replace('tid=381', 'tid=98').encode())
        rows.extend([self.row('NATIVE_CP_BACKGROUND_INPUT_AUDIT', dict(pid=77, tid=98, sequence=140, entry='async',
            pointer='0x900000', destination='0x90030001', bytes=12, source='0x80020002', size_known=1, source_known=1,
            bytes_complete=1, complete=1, producer_return='0x7f29174a68', consumed=0, state_verified=0, capture_verified=0)),
            self.row('NATIVE_CP_BACKGROUND_INPUT_AUDIT_BYTES', dict(pid=77, tid=98, sequence=140, offset=0, bytes=12, raw=self.packet.hex()))])
        fields = {}
        for part in checker.CP_OU_CRANK_EVENT_SCHEMA.split():
            key, grammar = part.split(':', 1)
            fields[key] = '(nil)' if grammar == 'pointer' else '0000000000000000' if grammar == 'digest' else (
                '0' if grammar in ('ou_event', 'pid', 'tid', 'u64', 'u32', 'hex32', 'i32', 'bit') else grammar)
        fields.update(pid='77', tid='98', sender_tid='98', transaction='1', requests='1', busy='1', source='0x80020002',
            destination='0x90030001', command='0x4072', bytes='12', native_fnv1a=f'{checker.fnv(self.packet):016x}',
            cookie='0x80000061', request_pointer='0x900000', model_instance='99', bank_generation='1', crank_generation='1',
            movie_generation='1', bank_transaction='2', bank_commits='1', bank_released='1', crank_transaction='1',
            crank_completions='1', movie_transaction='1', movie_completions='1', startup_cycle='2', startup_completed_cycles='2',
            startup_config_generation=str(startup_cfg), startup_frame_generation=str(startup_frame), startup_lease_generation=str(startup_lease),
            startup_result_fnv1a=f'{checker.fnv(startup_raw):016x}', startup_config40_fnv1a=f'{checker.fnv(self.prior[8:48]):016x}')
        for prefix, origin in [('bank', base.transport['transfers'][2]['origin']), ('crank', base.transport['transfers'][5]['origin']),
                               ('movie', base.transport['transfers'][8]['origin']), ('startup', startup_origin)]:
            for key in ('source', 'destination', 'command'):
                fields[prefix + '_' + key] = hex(origin[key])
            fields[prefix + '_bytes'], fields[prefix + '_native_fnv1a'] = str(origin['bytes']), f'{origin["fnv1a64"]:016x}'
        for key in ('before_rc', 'model_rc', 'after_rc', 'validation_rc', 'free_rc'):
            fields[key] = '-61'
        streams = dict(BEGIN=('request', self.packet), BEFORE=('before_state', self.prior), MODEL=('receipt', self.raw),
                       AFTER=('after_state', self.raw[80:208]))
        for name in ('BEGIN', 'BEFORE', 'MODEL', 'AFTER', 'VERIFIED', 'REQUEST_FREE', 'COMMIT'):
            fields['event'] = name
            if name in ('BEFORE', 'MODEL', 'AFTER'):
                rows.append(self.row('FUNCTIONAL_CAMERA_TRANSFER', {'HOST_TEST_marker': len(base.transport['transfers']) + {'BEFORE': 2, 'MODEL': 3, 'AFTER': 4}[name]}))
            if name == 'BEFORE':
                fields.update(guard='1', before_rc='0', before_config_generation=str(startup_cfg), frame_generation=str(startup_frame), fps='30',
                              before_used='128', before_required='128', before_instance='99')
            elif name == 'MODEL':
                fields.update(model_called='1', model_committed='1', model_rc='0', validation_rc='0', commits='1', ou_generation='1',
                    config_generation=str(startup_cfg + 1), receipt_fnv1a=f'{checker.fnv(self.raw):016x}', ou_used='224', ou_required='224', ou_instance='99')
            elif name == 'AFTER':
                fields.update(after_rc='0', after_used='128', after_required='128', after_instance='99')
            elif name == 'VERIFIED':
                fields.update(verified='1', owned='1', verified_commits='1', retained_request='0x900000',
                    last_bank_generation='1', last_crank_generation='1', last_movie_generation='1', last_ou_generation='1')
            elif name == 'REQUEST_FREE':
                fields.update(request_freed='1', free_rc='0', free_tid='98', released='1', retained_request='(nil)')
            elif name == 'COMMIT':
                fields.update(busy='0', guard='0', complete='1', completions='1')
            rows.append(self.row('FUNCTIONAL_CP_OU_CRANK_CONTROL_EVENT', fields))
            if name in streams:
                kind, raw = streams[name]
                for offset in range(0, len(raw), 128):
                    block = raw[offset:offset + 128]
                    rows.append(self.row('FUNCTIONAL_CP_OU_CRANK_CONTROL_BYTES', dict(event=name, pid=77, tid=98, transaction=1,
                        kind=kind, total=len(raw), offset=offset, bytes=len(block), raw=block.hex(), native_fnv1a=fields['native_fnv1a'],
                        content_fnv1a=f'{checker.fnv(raw):016x}', model_instance=99, bank_generation=1, crank_generation=1,
                        movie_generation=1, ou_generation=fields['ou_generation'], functional_model=1, original_CP=0,
                        physical_ASIC_verified=0, capture_verified=0)))
            if name == 'BEGIN':
                rows += resources
                rows.append(self.row('NATIVE_CP302C_NOCONVERT_ALL13_READBACK', dict(pid=77, tid=98, accepted=1,
                    video_AP_consumed=1, OSD_AP_consumed=1, audio_AP_consumed=1, OSD_live=16, OSD_owners_each=2,
                    OSD_opens_each=2, global_DMM_idle_claimed=0, capture_verified=0)))
        lines = []
        for r in rows:
            if r['tag'] == 'FUNCTIONAL_CAMERA_TRANSFER':
                index = r['fields'].get('HOST_TEST_marker')
                if index is None:
                    index = int(r['fields']['seq'].split('..')[0]) - 1
                lines.append('HOST_TEST_TRANSFER_' + str(index))
            else:
                lines.append('OBS ' + self.record(r['tag'], r['fields']))
        temporary = tempfile.TemporaryDirectory(); self.addCleanup(temporary.cleanup)
        self.args = host_test_transport(Path(temporary.name), operations, '\n'.join(lines) + '\n')
        self.run, self.manifest, self.rows, events, _ = self.args
        self.transport = copy.deepcopy(base.transport)
        self.transport['transfers'] = []
        for index, op in enumerate(operations, 1):
            event = next(e for e in events if e['kind'] == 'core_result' and e['sequence'] == index)
            tx = copy.deepcopy(base.transport['transfers'][index - 1]) if index <= 10 else dict(
                first=index, last=index, opcode=op['op'], origin=op['origin'], bytes=len(op['output']),
                token=0, provider_kind='core', frame=None, capacity=checker.DATA_BYTES)
            tx.update(request_payload=event['request_payload'], output_payloads=[event['output_payload']],
                sha256=event['output_payload']['sha256'], fnv1a64=f'{event["output_payload"]["fnv1a64"]:016x}',
                line=next(r['line'] for r in self.rows if r['tag'] == 'FUNCTIONAL_CAMERA_TRANSFER' and r['fields']['seq'] == f'{index}..{index}'))
            if op.get('proof'):
                tx['frame'] = dict(proof=op['proof'])
            self.transport['transfers'].append(tx)
        self.tx = self.transport['transfers'][-2]
        self.before, self.after, self.startup_tx = self.transport['transfers'][-3], self.transport['transfers'][-1], self.transport['transfers'][-4]
        self.bank = checker.check_cp_parameter_bank(self.run, base.manifest, self.rows, self.transport)['transactions'][0]
        current = dict(self.transport, parameter_bank=dict(verified=True, transactions=[self.bank]))
        self.crank = checker.check_cp_crank_control_content(self.run, base.manifest, self.rows, current)['transactions'][0]
        current['crank_control_content'] = dict(verified=True, content_join_verified=True, transactions=[self.crank])
        self.movie = checker.check_cp_movie_format_content(self.run, base.manifest, self.rows, current)['transactions'][0]
        group = [r for r in self.rows if r['tag'] == 'FUNCTIONAL_STARTUP_CONTROL']
        self.startup.update(ticket_line=next(r['line'] for r in self.rows if r['tag'] == 'FUNCTIONAL_STARTUP_CONTROL_TICKET_BOUND'),
            receive_line=next(r['line'] for r in group if r['fields']['event'] == 'RECEIVE'),
            free_line=next(r['line'] for r in group if r['fields']['event'] == 'SENDER_FREE'))
        self.value = checker.cp_ou_crank_control_result(self.raw, self.packet, 99, self.prior, 1, 1, 1)

    def native(self, rows=None):
        return checker.check_cp_ou_crank_native(self.run, self.rows if rows is None else rows, self.transport,
            self.tx, self.before, self.after, self.bank, self.transport['transfers'][2], self.crank,
            self.transport['transfers'][5], self.movie, self.transport['transfers'][8], self.startup, self.startup_tx, self.value, 1, 0)

    def test_direct_native_content_requires_seven_stages_five_chunks_and_no_reply(self):
        result = self.native()
        self.assertTrue(result['native_control_transaction_verified'])
        self.assertTrue(result['oneway'])
        self.assertTrue(all(result[key] is False for key in ('ACK_sent', 'reply_allocated', 'reply_sent', 'reply_received')))
        self.assertLess(result['original_free_line'], result['complete_line'])
        for sample in [r for r in self.rows if r['tag'] == 'FUNCTIONAL_CP_OU_CRANK_CONTROL_EVENT']:
            rows = copy.deepcopy(self.rows); rows.remove(next(r for r in rows if r['line'] == sample['line']))
            with self.subTest(missing=sample['fields']['event']), self.assertRaisesRegex(ValueError, 'one-way original lifecycle'):
                self.native(rows)
        rows = copy.deepcopy(self.rows)
        next(r for r in rows if r['tag'] == 'FUNCTIONAL_CP_OU_CRANK_CONTROL_EVENT' and r['fields']['event'] == 'REQUEST_FREE')['fields']['free_rc'] = '-5'
        with self.assertRaisesRegex(ValueError, 'actual C/validation/free result'):
            self.native(rows)

    def test_current_tuple_replay_rejects_after_a_new_consistent4057_checkpoint(self):
        history = checker.vdf_history(self.run, self.transport)
        self.assertEqual(history[self.tx['first']], self.value)
        transport = copy.deepcopy(self.transport)
        prior = self.raw[80:208]
        canonical = bytearray(checker.payload_read(self.run, self.startup_tx['request_payload']))
        struct.pack_into('<Q', canonical, 24, checker.fnv(prior[8:48])); canonical = bytes(canonical)
        settings = bytearray(checker.transfer_output(self.run, self.startup_tx))
        current_cfg, current_frame = self.value['config_generation'], self.value['frame_generation']
        struct.pack_into('<3Q', settings, 16, current_cfg + 1, current_frame + 1, self.startup['lease_generation'] + 1)
        struct.pack_into('<Q', settings, 40, checker.fnv(canonical))
        struct.pack_into('<2Q', settings, 144, current_frame, current_cfg); settings[160:] = canonical
        checkpoint = bytearray(prior)
        for offset in (56, 64, 72, 112):
            struct.pack_into('<Q', checkpoint, offset, struct.unpack_from('<Q', checkpoint, offset)[0] + 1)
        checkpoint = bytes(checkpoint)
        raw = CPOuCrankControlEvidenceTests.receipt(self.packet, checkpoint, ou=2, bank=1, crank=1, movie=1)
        seq_start = transport['transfers'][-1]['last'] + 1
        outputs = {seq_start: bytes(settings), seq_start + 1: checkpoint, seq_start + 2: raw, seq_start + 3: raw[80:208]}
        inputs = {seq_start: canonical, seq_start + 2: self.packet}
        for seq, op in enumerate((14, 2, 23, 2), seq_start):
            transport['transfers'].append(dict(first=seq, last=seq, opcode=op, token=0, frame=None,
                                               request_payload={'HOST_TEST_sequence': seq}))
        original_output, original_payload = checker.transfer_output, checker.payload_read
        with mock.patch.object(checker, 'transfer_output', side_effect=lambda run, tx:
                outputs[tx['first']] if tx['first'] in outputs else original_output(run, tx)), \
             mock.patch.object(checker, 'payload_read', side_effect=lambda run, ref:
                inputs[ref['HOST_TEST_sequence']] if 'HOST_TEST_sequence' in ref else original_payload(run, ref)):
            with self.assertRaisesRegex(ValueError, 'OU crank current tuple/FPS/once-only history'):
                checker.vdf_history(self.run, transport)
        rows = copy.deepcopy(self.rows)
        chunk = next(r for r in rows if r['tag'] == 'FUNCTIONAL_CP_OU_CRANK_CONTROL_BYTES' and r['fields']['kind'] == 'receipt')
        raw = bytearray.fromhex(chunk['fields']['raw']); raw[8] ^= 1; chunk['fields']['raw'] = raw.hex()
        with self.assertRaisesRegex(ValueError, 'complete request12/STATE128/receipt224'):
            self.native(rows)

    def test_exact_five_tag_schema_matches_actual_formatter_and_both_existing_trailers(self):
        source = (checker.RUNTIME / 'device-models/functional-camera-control.c').read_text()
        block = source[source.index('static void ou_crank_record('):source.index('static int ou_crank_movie_ready(')]
        formats = re.findall(r'snprintf\(text, sizeof text,\s*((?:"[^"\n]*"\s*)+)', block)
        self.assertEqual(len(formats), 2)
        for schema, fmt in zip((checker.CP_OU_CRANK_EVENT_SCHEMA, checker.CP_OU_CRANK_BYTES_SCHEMA), formats):
            actual = re.findall(r'([A-Za-z_][A-Za-z_0-9]*)=', ''.join(re.findall(r'"([^"\n]*)"', fmt)))
            self.assertEqual(actual, [part.split(':', 1)[0] for part in schema.split()])
        trailers = (b'[ 5638.875229] UDIF: cdev_ioctl() Line 100: uipc: warning ret = -1022',
                    b'[ 5541.864466] [K]**UIPC ERROR** free_dynamic_msgq_id: QID[81cf61c4] M=1 C=0 S=0 A=1')
        for r in [r for r in self.rows if r['tag'].startswith('FUNCTIONAL_CP_OU_CRANK_CONTROL_')]:
            payload = self.record(r['tag'], r['fields']).encode()
            self.assertEqual(checker.console_producer_fields(payload), r['fields'])
            for trailer in trailers:
                row, = checker.parse_console(b'OBS ' + payload + trailer + b'\r\n')
                self.assertEqual(row['fields'], r['fields']); self.assertIn('kernel_diagnostic', row)
                for bad in (payload + b' unknown=0', payload.replace(r['tag'].encode(), b'FUNCTIONAL_CP_OU_CRANK_CONTROL_UNKNOWN', 1)):
                    self.assertIsNone(checker.console_producer_fields(bad))
                    row, = checker.parse_console(b'OBS ' + bad + trailer + b'\n')
                    self.assertNotIn('kernel_diagnostic', row)

    def test_resource36_TTS_dual_DMM_and_current_predecessors_reject_real_mutations(self):
        self.assertTrue(self.native()['native_control_transaction_verified'])
        for suffix, key, wrong in (('RESOURCE_DEPENDENCIES', 'accepted', '0'), ('RESOURCES_RESERVED', 'vef_live', '1'),
                ('RESOURCES_RESERVED', 'dmm_slots', '1/0'), ('RESOURCES_RESERVED', 'pinmem_faults', '1'),
                ('RESOURCES_TTS_TABLE', 'raw_after', bytes(144).hex())):
            rows = copy.deepcopy(self.rows)
            r = next(r for r in rows if r['tag'] == 'FUNCTIONAL_CP_OU_CRANK_CONTROL_' + suffix); r['fields'][key] = wrong
            # Grammar validation is part of the public entry point and is tested explicitly here.
            payload = self.record(r['tag'], r['fields']).encode()
            if key == 'dmm_slots':
                self.assertEqual(checker.console_producer_fields(payload), r['fields'])
            else:
                self.assertIsNone(checker.console_producer_fields(payload))
            with self.subTest(resource=key), self.assertRaisesRegex(ValueError, 'resource36'):
                self.native(rows)
        for tag, key, wrong in (('NATIVE_CP302C_NOCONVERT_ALL13_READBACK', 'accepted', '0'),
                ('FUNCTIONAL_STARTUP_CONTROL', 'AP_consumed', '0'), ('NATIVE_CP_EE_DIAGNOSTIC_COMPLETE', 'attempts', '2')):
            rows = copy.deepcopy(self.rows)
            found = [r for r in rows if r['tag'] == tag and (tag != 'NATIVE_CP_EE_DIAGNOSTIC_COMPLETE' or r['fields']['opcode'] == '0x4072')]
            found[-1]['fields'][key] = wrong
            with self.subTest(predecessor=tag), self.assertRaises(ValueError):
                self.native(rows)
        rows = copy.deepcopy(self.rows)
        event = next(r for r in rows if r['tag'] == 'FUNCTIONAL_CP_OU_CRANK_CONTROL_EVENT' and r['fields']['event'] == 'COMMIT')
        event['fields']['movie_native_fnv1a'] = '0000000000000000'
        with self.assertRaisesRegex(ValueError, 'predecessor original source/command/full input seal'):
            self.native(rows)


if __name__ == '__main__':
    unittest.main()
