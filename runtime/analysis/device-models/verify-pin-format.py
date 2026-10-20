#!/usr/bin/env python3
"""Verify the explicit cold CPU-format owner, references and original next Get."""
import argparse
import hashlib
import json
from pathlib import Path
import runpy
import struct

HERE = Path(__file__).resolve().parent


def require(value, reason):
    if not value:
        raise ValueError(reason)


def verify(run, allow_host_fixture=False, component_only=False, native=False):
    host_fixture = b'HOST_FIXTURE_ONLY_NO_VM' in (run / 'console.log').read_bytes()
    require(not host_fixture or allow_host_fixture, 'Host fixture is not Native evidence')
    api = runpy.run_path(str(HERE / 'verify-pin-connection.py'))
    prefix = api['verify_control_prefix'](run, native=native)
    inputs, result = prefix['inputs'], prefix['result']
    require((inputs.get('pin_connection_mode') if native else inputs['experiment'].get('pin_format')) == 'cold',
            'Explicit cold CPU format profile missing')
    require((native and result.get('probe_collected') is True) or result.get('state') == 'observation-completed' or
            (component_only and result.get('state') == 'failed' and result.get('error') ==
             'Actual CPU format consumption/release and next original Get/free were not observed' and
             not result.get('terminal_errors') and not result.get('original_model_fatal_observed')),
            'Successful terminal observation missing; component-only permits only the retained observation deadline failure')
    tid, D, handle, physical, size = (prefix[key] for key in ('caller_tid', 'dynamic_sid', 'handle', 'physical', 'size'))
    records = prefix['records']
    require(not any('OBS FULL_PIN_CONNECT_FAULT ' in line or 'OBS FULL_PIN_FORMAT_FAULT ' in line
                    for _, line, _ in records), 'Format/control ownership fault')

    def event(family, kind, after=-1, **matches):
        return next(row for row in records if row[0] > after and row[1].startswith('OBS FULL_' + family + '_' + kind + ' ') and
                    all(row[2].get(key) == value for key, value in matches.items()))

    def freed(row, after, count):
        value = event('PIN_CONNECT', 'INTERNAL_FREE', after, pointer=row[2]['pointer'], rc='0', bytes=str(count))
        require(int(value[2]['owner'], 0) == D and int(value[2]['tid']) == tid, 'Actual internal message free owner/caller differs')
        return value

    def dmm(command, option, source, after):
        request = event('PIN_CONNECT', 'FORMAT_DMM_REQUEST', after, source=hex(source))
        answer = event('PIN_CONNECT', 'FORMAT_DMM_REPLY', request[0], destination=hex(source))
        before, response = bytes.fromhex(request[2]['raw']), bytes.fromhex(answer[2]['raw'])
        expected = bytearray(152)
        struct.pack_into('<H', expected, 0, command)
        struct.pack_into('<I', expected, 8, handle)
        struct.pack_into('<H', expected, 0x16, option)
        if command == 0x21:
            struct.pack_into('<I', expected, 4, 0x404)
        require(before == expected, 'Finite model DMM request fields differ')
        expected = bytearray(152)
        struct.pack_into('<H', expected, 0, command | 0x8000)
        struct.pack_into('<I', expected, 0xc, handle)
        if command == 0x21:
            struct.pack_into('<I', expected, 0x10, 0x404)
        if command == 0x24:
            struct.pack_into('<H', expected, 8, 1)
            struct.pack_into('<QII', expected, 0x18, physical, size, 0)
        require(response == expected, 'Finite model DMM reply/descriptor fields differ')
        for row in (request, answer):
            require(int(row[2]['tid']) == tid and int(row[2]['bytes']) == 152, 'DMM actual caller/size differs')
        require(request[2]['pointer'] == answer[2]['pointer'] and int(request[2]['destination'], 0) == 0x61003c and
                int(answer[2]['source'], 0) == 0x61003c, 'DMM in-place allocation or CP route differs')
        return freed(answer, answer[0], 152)

    def references(phase, after, owners, opens, creator, consumer, opened):
        row = event('PIN_FORMAT', 'REFERENCE_READBACK', after, phase=phase)
        f = row[2]
        require(int(f['tid']) == tid and int(f['handle'], 0) == handle and
                tuple(int(f[key]) for key in ('owners', 'opens', 'creator', 'consumer', 'consumer_open')) ==
                (owners, opens, creator, consumer, opened), 'Actual reference readback differs')
        return row

    written = event('PIN_FORMAT', 'BUFFER_WRITTEN', prefix['state_readback'][0])
    f = written[2]
    require(int(f['tid']) == tid and int(f['handle'], 0) == handle and int(f['physical'], 0) == physical and
            f['bytes'] == '80' and f['parameter_source'] == 'virtual-cold-constructor' and
            f['original_negotiation_verified'] == '0' and (f['raw_flags'], f['code'], f['component'], f['width'], f['height']) ==
            ('0', '1', '0', '1920', '1080'), 'Cold parameter origin or actual write differs')
    share = dmm(0x21, 0, 0x9059000e, written[0])
    shared = references('shared', share[0], 2, 1, 1, 1, 0)
    notify = event('PIN_CONNECT', 'FORMAT_NOTIFY_QUEUED', shared[0])
    wire = bytes.fromhex(notify[2]['raw'])
    require(int(notify[2]['tid']) == tid and int(notify[2]['bytes']) == len(wire) == 80 and
            int(notify[2]['source'], 0) == 0x90590818 and int(notify[2]['destination'], 0) == 0x905a0048 and
            struct.unpack_from('<IIHHII', wire) == (0, 0xa0a0a0a0, 1, 80, 24, 80) and
            struct.unpack_from('<4H', wire, 24) == (0x1000, 0x104, 56, 1) and
            struct.unpack_from('<12I', wire, 32) == api['P'] + api['S'] + (0x404, handle, 0, 0),
            'Actual notification route, P/S order or descriptor differs')
    local_release = dmm(0x23, 2, 0x9059000e, notify[0])
    sender_released = references('creator-released', local_release[0], 1, 0, 0, 1, 0)
    opened = dmm(0x24, 0, 0x905a0048, sender_released[0])
    consumer_open = references('consumer-open', opened[0], 1, 1, 0, 1, 1)
    cache = event('PIN_FORMAT', 'CPU_STATE_READBACK', consumer_open[0])
    require(cache[2]['status'] == '0' and cache[2]['status_source'] == 'virtual-cold-constructor' and
            cache[2]['original_runtime_state_verified'] == '0' and cache[2]['source_slot'] == '10' and
            cache[2]['ordinal'] == '1' and cache[2]['downstream_pin'] == '2' and int(cache[2]['handle'], 0) == handle,
            'CPU format state origin differs')
    downstream = event('PIN_FORMAT', 'DOWNSTREAM_READBACK', cache[0], state='1', downstream_pin='2',
                       action='consumer-close-and-owner-release', forwarding='0')
    last_release = dmm(0x23, 2, 0x905a0048, downstream[0])
    notify_freed = freed(notify, last_release[0], 80)
    commit = event('PIN_FORMAT', 'COMMIT', notify_freed[0])
    require(all(commit[2][key] == '0' for key in ('live', 'owners', 'opens', 'pinmem_postprocess_pending', 'frame_ready', 'pixels_consumed', 'camera_startup_verified')) and
            commit[2]['buffer_released'] == commit[2]['format_cpu_consumed'] == '1' and int(commit[2]['tid']) == tid,
            'Final buffer/reference state differs')
    native_free = prefix['native_free']
    require(native_free[0] > commit[0], 'Original AP8001 free did not follow the consumed format postprocess')
    persisted = event('PIN_FORMAT', 'PERSISTENT_READBACK', native_free[0], tid=str(tid))
    require(persisted[2]['format_cpu_consumed'] == persisted[2]['buffer_released'] == '1' and persisted[2]['live'] == '0' and
            int(persisted[2]['handle'], 0) == handle, 'CPU cache not read back after last buffer release and original AP free')
    next_commit = event('PINMEM', 'COMMIT', persisted[0], tid=str(tid), slot='4', type='0', dir='2', index='1', request_free_rc='0')
    require(next_commit[2]['pin_state'] == '1' and int(next_commit[2]['owner'], 0) == 0x90590818,
            'Natural next Get did not preserve its real cold pin state')
    next_free = event('PINMEM', 'NATIVE_REPLY_FREE', next_commit[0], tid=str(tid), sender=str(tid), waiter='1',
                      reply=next_commit[2]['reply'], lease=next_commit[2]['lease'], rc='0')
    require(next_free[2]['bytes'] == '56', 'Natural next Get was not copied/freed by the original waiter')

    memory = (run / ('pin-control-ram.bin' if native else 'pin-control-memory.bin')).read_bytes()
    expected = bytearray(80)
    struct.pack_into('<II', expected, 0, 0x4e595353, 0x01000000)
    struct.pack_into('<II', expected, 0xc, 1, 0x20)
    struct.pack_into('<I', expected, 0x20, 0x59525445)
    struct.pack_into('<II', expected, 0x2c, 0x40, 0x10)
    struct.pack_into('<BBHIII', expected, 0x40, 1, 0, 0, 0, 1920, 1080)
    offset = physical - 0x500000000
    require(len(memory) == 8192 and memory[offset:offset+80] == expected and
            not any(memory[:offset]) and not any(memory[offset+80:]) and (native or result.get('pin_control_memory_exported')),
            'Independent full-region export does not contain the actual cold format record')
    control = runpy.run_path(str(HERE / 'verify-pin-control.py'))
    require(control['fnv'](expected) == f['fnv64'], 'Actual 80B write/readback digest differs')
    expected_current = struct.pack('<IIBBHII', 2, 1, expected[64], expected[65], struct.unpack_from('<H', expected, 66)[0],
                                   struct.unpack_from('<I', expected, 72)[0], struct.unpack_from('<I', expected, 76)[0])
    require(bytes.fromhex(cache[2]['currentinfo_raw']) == expected_current, 'CPU currentinfo differs from consumed RAM')
    require(tuple(int(persisted[2][key]) for key in ('pin_index', 'ordinal', 'code', 'component', 'encoded_flags', 'width', 'height')) ==
            struct.unpack('<IIBBHII', expected_current), 'Persistent CPU getter differs from consumed RAM')
    library = HERE / '../../sources/qemu-tools/usr/lib/libfdt.so.1' if native else None
    command = control['verify_reservation'](run, runpy.run_path(str(HERE / 'pin-buffer-region.py')), library=library)
    if native:
        require(b'export MENU_PIN_CONNECTION=cold' in (run / 'console.log').read_bytes(), 'Native cold profile was not forwarded')
    else:
        require(command.split().count('fullsystem.pin-connect=control') == command.split().count('fullsystem.pin-format=cold') == 1,
                'Actual DTB explicit control/cold format profile missing')
    return {'schema': 1, 'cold_cpu_format_consumed_verified': True, 'virtual_control_connection_verified': True,
            'evidence_kind': 'host-fixture-only' if host_fixture else 'native',
            'verification_scope': 'native-component' if native else 'component-only' if component_only else 'completed-observation',
            'original_run_state': result.get('state'), 'original_run_error': result.get('error'),
            'whole_run_success_verified': not native and result.get('state') == 'observation-completed' and not component_only and not host_fixture,
            'caller_tid': tid, 'dynamic_sid': hex(D), 'handle': hex(handle), 'control_buffer_physical': hex(physical),
            'format_record_bytes': 80, 'buffer_last_reference_released': True, 'cpu_format_persisted_after_release': True,
            'original_next_get_waiter_copy_free_verified': not host_fixture, 'parameter_source': 'virtual-cold-constructor',
            'original_runtime_state_verified': False, 'original_negotiation_verified': False,
            'console_sha256': prefix['console_sha256'], 'backing_sha256': hashlib.sha256(memory).hexdigest(),
            'original_CP_task_running_verified': False, 'frame_ready_verified': False, 'pixels_consumed': False,
            'camera_startup_verified': False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('run', type=Path)
    parser.add_argument('--native', action='store_true', help='validate native manifest/summary identity without synthesizing full-system metadata')
    parser.add_argument('--component-only',action='store_true',
                        help='independently verify format content after an observation-deadline failure; preserve the full-run failure')
    args = parser.parse_args()
    if args.native and args.component_only:
        parser.error('--native and --component-only are separate evidence profiles')
    try:
        proof = verify(args.run, component_only=args.component_only, native=args.native)
    except (OSError, KeyError, ValueError, StopIteration, TypeError, UnicodeError, struct.error) as error:
        proof = {'cold_cpu_format_consumed_verified': False, 'error': str(error) or type(error).__name__,
                 'original_CP_task_running_verified': False, 'frame_ready_verified': False,
                 'pixels_consumed': False, 'camera_startup_verified': False}
    name='pin-format-native-proof.json' if args.native else 'pin-format-component-proof.json' if args.component_only else 'pin-format-proof.json'
    (args.run / name).write_text(json.dumps(proof, indent=2) + '\n')
    print(json.dumps(proof, sort_keys=True))
    return 0 if proof['cold_cpu_format_consumed_verified'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
