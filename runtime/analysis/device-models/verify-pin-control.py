#!/usr/bin/env python3
"""Verify a new guest control backing probe, never original CP/frames."""
import argparse
import ctypes
import hashlib
import json
from pathlib import Path
import re
import runpy
import struct

HERE = Path(__file__).resolve().parent


def require(value, reason):
    if not value:
        raise ValueError(reason)


def fnv(data):
    value = 0xcbf29ce484222325
    for byte in data:
        value = ((value ^ byte) * 0x100000001b3) & ((1 << 64) - 1)
    return f'{value:016x}'


def verify_reservation(run, api, library=None):
    fdt = ctypes.CDLL(str(library or HERE / '../../sources/qemu-tools/usr/lib/libfdt.so.1'))
    raw_dtb = (run / 'virt.dtb').read_bytes()
    require(40 <= len(raw_dtb) <= 65536, 'Actual board DTB size differs')
    source = ctypes.create_string_buffer(raw_dtb);buffer = ctypes.create_string_buffer(65536)
    fdt.fdt_check_full.argtypes = [ctypes.c_void_p, ctypes.c_size_t]
    require(fdt.fdt_check_full(source, len(raw_dtb)) == 0, 'Actual board DTB is incomplete or malformed')
    require(fdt.fdt_open_into(source, buffer, len(buffer)) == 0, 'Cannot read actual board DTB')
    fdt.fdt_getprop.restype = ctypes.c_void_p
    chosen = fdt.fdt_path_offset(buffer, b'/chosen');length = ctypes.c_int()
    pointer = fdt.fdt_getprop(buffer, chosen, b'bootargs', ctypes.byref(length))
    require(pointer and length.value > 0, 'Actual DTB bootargs missing')
    command = ctypes.string_at(pointer, length.value).rstrip(b'\0').decode('ascii')
    api['validate_final_command'](command)
    before = fdt.fdt_num_mem_rsv(buffer)
    api['add_dtb_reservation'](fdt, buffer, command)
    require(fdt.fdt_num_mem_rsv(buffer) == before, 'Owner reservation was not already present in actual board')
    return command


def verify(run):
    api = runpy.run_path(str(HERE / 'pin-buffer-region.py'))
    inputs = json.loads((run / 'inputs.json').read_text())
    result = json.loads((run / 'result.json').read_text())
    console = (run / 'console.log').read_bytes();sha = hashlib.sha256(console).hexdigest()
    require(inputs['experiment'].get('pin_control_probe') is True and inputs['experiment']['stage'] == 'mounts' and
            result['state'] == 'observation-completed' and result.get('pin_control_memory_exported') and
            result.get('terminal_evidence_checked') and result['terminal_console_sha256'] == sha and
            result['camera_startup_verified'] is False,
            'Explicit completed backing probe/terminal evidence missing')
    identity = inputs['virtual_pin_control']
    require(all(identity[field] == api[constant] for field, constant in
                (('physical', 'PHYSICAL'), ('capacity', 'CAPACITY'), ('cp_virtual', 'CP_VIRTUAL'),
                 ('slots', 'SLOTS'), ('slot_bytes', 'SLOT_BYTES'))) and
            identity['original_pool_policy_verified'] is False and identity['original_CP_task_running_verified'] is False,
            'New finite owner identity differs')
    log = (run / 'pin-control-probe.log').read_bytes()
    require(re.findall(rb'(?:^|\n)FULL_PIN_CONTROL_PROBE_RC=(\d+)\r?(?:\n|$)', log) == [b'0'] and
            b'FULL_PIN_CONTROL_PROBE_FAILED' not in console, 'Guest probe failed or ambiguous RC')
    rows = re.findall(rb'FULL_PIN_CONTROL_PROBE_PASS ([^\r\n]+)', log)
    require(len(rows) == 1, 'Guest backing record missing or ambiguous')
    require(b'FULL_PIN_CONTROL_PROBE_PASS ' + rows[0] in console and
            re.findall(rb'(?:^|\n)FULL_PIN_CONTROL_PROBE_RC=(\d+)\r?(?:\n|$)', console) == [b'0'],
            'Saved probe record/RC is not associated with terminal console')
    fields = dict(re.findall(r'(\w+)=([^\s]+)', rows[0].decode('ascii')))
    require(int(fields['physical'], 0) == api['PHYSICAL'] and int(fields['cp_virtual'], 0) == api['CP_VIRTUAL'] and
            int(fields['capacity']) == api['CAPACITY'] and int(fields['bytes']) == api['SLOT_BYTES'] and
            int(fields['handle'], 0) == 0x8000 and int(fields['unit'], 0) == 0x404 and fields['live'] == '0' and fields['releases'] == '1',
            'Actual allocated/released lease differs')
    require(all(fields[name] == '0' for name in ('original_CP_task_running', 'pixels_consumed', 'camera_startup_verified')),
            'Guest backing proof exceeds control-only scope')
    data = (run / 'pin-control-memory.bin').read_bytes()
    expected = struct.pack('<II', 0x4e595353, 0x01000000) + bytes(24)
    require(len(data) == api['CAPACITY'] and data[:32] == expected and not any(data[32:]) and
            fields['header_fnv64'] == fnv(data[:32]) and fields['full_fnv64'] == fnv(data),
            'Independent complete QMP export differs from guest writes/readback')
    verify_reservation(run, api)
    return {'reserved_guest_control_backing_verified': True, 'physical': hex(api['PHYSICAL']),
            'cp_virtual': hex(api['CP_VIRTUAL']), 'capacity': len(data), 'slots': api['SLOTS'], 'slot_bytes': api['SLOT_BYTES'],
            'actual_lease_released': True, 'ssyn_header_bytes_written': 32, 'export_sha256': hashlib.sha256(data).hexdigest(),
            'console_sha256': sha, 'original_pool_policy_verified': False, 'original_CP_task_running_verified': False,
            'original_PinMem_consumer_verified': False, 'connection_verified': False, 'pixels_consumed': False,
            'camera_startup_verified': False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('run', type=Path);args = parser.parse_args()
    try:
        proof = verify(args.run)
    except (OSError, KeyError, ValueError, StopIteration, TypeError, UnicodeError) as error:
        proof = {'reserved_guest_control_backing_verified': False, 'error': str(error) or type(error).__name__,
                 'connection_verified': False, 'pixels_consumed': False, 'camera_startup_verified': False}
    (args.run / 'pin-control-backing-proof.json').write_text(json.dumps(proof, indent=2) + '\n')
    print(json.dumps(proof, sort_keys=True))
    return 0 if proof['reserved_guest_control_backing_verified'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
