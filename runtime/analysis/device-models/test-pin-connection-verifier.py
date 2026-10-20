#!/usr/bin/env python3
"""C-producer host fixtures and counterfactuals, never Native camera proof."""
import ctypes
import hashlib
import json
import os
from pathlib import Path
import runpy
import subprocess
import tempfile
import unittest

HERE = Path(__file__).resolve().parent
VERIFY = runpy.run_path(str(HERE / 'verify-pin-connection.py'))['verify']
LIB = HERE / '../../sources/qemu-tools/usr/lib/libfdt.so.1'


@unittest.skipUnless(LIB.is_file(), 'Prepare local FDT tools for host-only fixtures')
class ConnectionEvidence(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.workspace = tempfile.TemporaryDirectory(prefix='connection-evidence-host-only-')
        cls.binary = Path(cls.workspace.name) / 'producer'
        sources = ('pin-registry-core.c', 'vef-device.c', 'pinmem-device.c', 'pin-buffer-owner.c', 'pin-buffer-wire.c', 'pin-connection.c', 'pin-format.c', 'test-pin-connection.c')
        subprocess.run(['clang', '-std=c11', '-O2', '-pthread', '-Wall', '-Wextra', '-Werror',
                        '-DFULL_VEF_TEST', '-DPIN_CONTROL_TEST', '-DFULL_PIN_CONNECTION_TEST',
                        *[str(HERE / name) for name in sources], '-o', str(cls.binary)], check=True)

    @classmethod
    def tearDownClass(cls):
        cls.workspace.cleanup()

    def fixture(self, path):
        helper = runpy.run_path(str(HERE / 'test-pin-control-verifier.py'))['BackingProof']
        helper.fixture(self, path)
        out = subprocess.run([str(self.binary)], capture_output=True, check=True,
                             env={**os.environ, 'PIN_CONNECTION_HOST_FIXTURE': str(path / 'pin-control-memory.bin')})
        self.assertTrue(out.stdout.startswith(b'HOST_FIXTURE_ONLY_NO_VM\n'))
        self.update_console(path, out.stdout)
        inputs = json.loads((path / 'inputs.json').read_text())
        inputs['experiment'].update(pin_control_probe=False, pin_connection='control', stage='init2', vef_service='registry', pinmem_service='registry')
        (path / 'inputs.json').write_text(json.dumps(inputs))
        fdt = ctypes.CDLL(str(LIB));source = ctypes.create_string_buffer((path / 'virt.dtb').read_bytes());buffer = ctypes.create_string_buffer(65536)
        self.assertEqual(fdt.fdt_open_into(source, buffer, len(buffer)), 0)
        fdt.fdt_getprop.restype = ctypes.c_void_p
        chosen = fdt.fdt_path_offset(buffer, b'/chosen');size = ctypes.c_int()
        pointer = fdt.fdt_getprop(buffer, chosen, b'bootargs', ctypes.byref(size))
        command = ctypes.string_at(pointer, size.value).rstrip(b'\0') + b' fullsystem.pin-connect=control\0'
        self.assertEqual(fdt.fdt_setprop(buffer, chosen, b'bootargs', command, len(command)), 0)
        self.assertEqual(fdt.fdt_pack(buffer), 0)
        import struct
        (path / 'virt.dtb').write_bytes(buffer.raw[:struct.unpack_from('>I', buffer.raw, 4)[0]])

    def update_console(self, path, data):
        (path / 'console.log').write_bytes(data)
        result = json.loads((path / 'result.json').read_text())
        result['terminal_console_sha256'] = hashlib.sha256(data).hexdigest()
        (path / 'result.json').write_text(json.dumps(result))

    def test_actual_c_host_producer_chain_passes_only_control_scope(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary);self.fixture(path)
            proof = VERIFY(path)
            self.assertTrue(proof['virtual_control_connection_verified'])
            self.assertTrue(proof['control_buffer_lease_retained'])
            self.assertTrue(proof['format_consumer_missing'])
            self.assertFalse(proof['camera_startup_verified'])

    def test_post_connection_queue_and_original_waiter_are_required(self):
        for marker in (b'OBS FULL_PIN_CONNECT_FORMAT_BLOCKED_REQUEST ', b'OBS FULL_PIN_CONNECT_NATIVE_REPLY_FREE ', b'OBS FULL_PIN_CONNECT_STATE_READBACK '):
            with self.subTest(marker=marker), tempfile.TemporaryDirectory() as temporary:
                path = Path(temporary);self.fixture(path)
                lines=(path / 'console.log').read_bytes().splitlines(keepends=True)
                self.update_console(path,b''.join(line for line in lines if not line.startswith(marker)))
                with self.assertRaises((StopIteration,ValueError)):
                    VERIFY(path)

    def test_independent_backing_corruption_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary);self.fixture(path)
            data = bytearray((path / 'pin-control-memory.bin').read_bytes());data[4000] = 1
            (path / 'pin-control-memory.bin').write_bytes(data)
            with self.assertRaisesRegex(ValueError,'backing differs'):
                VERIFY(path)

    def test_native_same_pointer_free_events_are_not_collapsed(self):
        path = HERE / 'runtime/analysis/runs/run-1iwjggjk'
        if not path.is_dir():
            self.skipTest('Private native address-reuse regression not present')
        proof = VERIFY(path)
        self.assertTrue(proof['virtual_control_connection_verified'])
        self.assertTrue(proof['transport_event_multiplicity_preserved'])
        self.assertTrue(proof['format_consumer_missing'])


if __name__ == '__main__':
    unittest.main()
