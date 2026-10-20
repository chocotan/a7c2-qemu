#!/usr/bin/env python3
"""Protocol/DTB host fixtures only; no guest execution or camera evidence."""
import ctypes
import hashlib
import json
from pathlib import Path
import runpy
import struct
import tempfile
import unittest

HERE = Path(__file__).resolve().parent
VERIFY = runpy.run_path(str(HERE / 'verify-pin-control.py'))
REGION = runpy.run_path(str(HERE / 'pin-buffer-region.py'))
LIB = HERE / '../../sources/qemu-tools/usr/lib/libfdt.so.1'
WORKSPACE = 'memrsv=0x1000@0x410000000:uc'


@unittest.skipUnless(LIB.is_file(), 'Prepare local real libfdt tools for host fixtures')
class BackingProof(unittest.TestCase):
    def fixture(self, run, reserve=True):
        fdt = ctypes.CDLL(str(LIB));buffer = ctypes.create_string_buffer(65536)
        self.assertEqual(fdt.fdt_create_empty_tree(buffer, len(buffer)), 0)
        for key, value in ((b'compatible', b'linux,dummy-virt\0'), (b'#address-cells', struct.pack('>I', 2)), (b'#size-cells', struct.pack('>I', 2))):
            self.assertEqual(fdt.fdt_setprop(buffer, 0, key, value, len(value)), 0)
        fdt.fdt_add_subnode(buffer, 0, b'chosen');node = fdt.fdt_add_subnode(buffer, 0, b'memory@400000000')
        for key, value in ((b'device_type', b'memory\0'), (b'reg', struct.pack('>QQ', 0x400000000, 0x200000000))):
            self.assertEqual(fdt.fdt_setprop(buffer, node, key, value, len(value)), 0)
        command = WORKSPACE + ' fullsystem.pin-control-memory=1 ' + REGION['RESERVATION']
        if reserve:
            REGION['add_dtb_reservation'](fdt, buffer, command)
        chosen = fdt.fdt_path_offset(buffer, b'/chosen');encoded = command.encode() + b'\0'
        self.assertEqual(fdt.fdt_setprop(buffer, chosen, b'bootargs', encoded, len(encoded)), 0)
        self.assertEqual(fdt.fdt_pack(buffer), 0)
        (run / 'virt.dtb').write_bytes(buffer.raw[:struct.unpack_from('>I', buffer.raw, 4)[0]])
        data = struct.pack('<II', 0x4e595353, 0x01000000) + bytes(REGION['CAPACITY'] - 8)
        row = (f'FULL_PIN_CONTROL_PROBE_PASS physical=0x500000000 cp_virtual=0x80000000 capacity=8192 unit=0x404 handle=0x8000 bytes=512 '
               f'header_fnv64={VERIFY["fnv"](data[:32])} full_fnv64={VERIFY["fnv"](data)} live=0 releases=1 original_CP_task_running=0 pixels_consumed=0 camera_startup_verified=0\n')
        log = row.encode() + b'FULL_PIN_CONTROL_PROBE_RC=0\n'
        (run / 'console.log').write_bytes(log);(run / 'pin-control-probe.log').write_bytes(log)
        (run / 'pin-control-memory.bin').write_bytes(data)
        (run / 'result.json').write_text(json.dumps({'state': 'observation-completed', 'pin_control_memory_exported': True,
            'terminal_evidence_checked': True, 'terminal_console_sha256': hashlib.sha256(log).hexdigest(), 'camera_startup_verified': False, 'host_fixture_only': True}))
        identity = {name: REGION[constant] for name, constant in (('physical', 'PHYSICAL'), ('capacity', 'CAPACITY'), ('cp_virtual', 'CP_VIRTUAL'), ('slots', 'SLOTS'), ('slot_bytes', 'SLOT_BYTES'))}
        identity.update(original_pool_policy_verified=False, original_CP_task_running_verified=False)
        (run / 'inputs.json').write_text(json.dumps({'experiment': {'pin_control_probe': True, 'stage': 'mounts'}, 'virtual_pin_control': identity, 'host_fixture_only': True}))

    def test_host_fixture_passes_without_frame_or_original_cp_claim(self):
        with tempfile.TemporaryDirectory() as temporary:
            run = Path(temporary);self.fixture(run)
            proof = VERIFY['verify'](run)
            self.assertTrue(proof['reserved_guest_control_backing_verified'])
            self.assertFalse(proof['original_CP_task_running_verified'])
            self.assertFalse(proof['connection_verified'])

    def test_missing_actual_dtb_reservation_is_not_added_into_proof(self):
        with tempfile.TemporaryDirectory() as temporary:
            run = Path(temporary);self.fixture(run, reserve=False)
            with self.assertRaisesRegex(ValueError, 'not already present'):
                VERIFY['verify'](run)

    def test_tail_corruption_or_missing_lease_return_refused(self):
        for target in ('tail', 'lease'):
            with self.subTest(target=target), tempfile.TemporaryDirectory() as temporary:
                run = Path(temporary);self.fixture(run)
                if target == 'tail':
                    data = bytearray((run / 'pin-control-memory.bin').read_bytes());data[-1] = 7
                    (run / 'pin-control-memory.bin').write_bytes(data)
                else:
                    file = run / 'pin-control-probe.log';file.write_bytes(file.read_bytes().replace(b'live=0', b'live=1'))
                with self.assertRaises(ValueError):
                    VERIFY['verify'](run)

    def test_truncated_actual_dtb_refused_before_parse(self):
        with tempfile.TemporaryDirectory() as temporary:
            run = Path(temporary);self.fixture(run)
            path = run / 'virt.dtb';path.write_bytes(path.read_bytes()[:-1])
            with self.assertRaisesRegex(ValueError, 'incomplete or malformed'):
                VERIFY['verify'](run)

    def test_final_command_conflicts_rejected_offline(self):
        variants = ('memrsv=0x1000@0x500001000:uc', 'fullsystem.pin-control-memory=0',
                    'fullsystem.pin-control-memory=1', REGION['RESERVATION'],
                    ' '.join(f'memrsv=0x1000@{0x410000000+i*4096:#x}:uc' for i in range(16)))
        for extra in variants:
            with self.subTest(extra=extra), tempfile.TemporaryDirectory() as temporary:
                run = Path(temporary); self.fixture(run)
                fdt = ctypes.CDLL(str(LIB))
                source = ctypes.create_string_buffer((run / 'virt.dtb').read_bytes())
                buffer = ctypes.create_string_buffer(65536)
                self.assertEqual(fdt.fdt_open_into(source, buffer, len(buffer)), 0)
                chosen = fdt.fdt_path_offset(buffer, b'/chosen')
                command = (WORKSPACE + ' fullsystem.pin-control-memory=1 ' + REGION['RESERVATION'] + ' ' + extra).encode() + b'\0'
                self.assertEqual(fdt.fdt_setprop(buffer, chosen, b'bootargs', command, len(command)), 0)
                self.assertEqual(fdt.fdt_pack(buffer), 0)
                (run / 'virt.dtb').write_bytes(buffer.raw[:struct.unpack_from('>I', buffer.raw, 4)[0]])
                with self.assertRaises(ValueError):
                    VERIFY['verify_reservation'](run, REGION)


if __name__ == '__main__':
    unittest.main()
