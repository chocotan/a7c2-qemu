#!/usr/bin/env python3
"""Real C-producer host fixtures, with an explicitly mocked observer getter."""
import ctypes
import hashlib
import json
import os
from pathlib import Path
import re
import runpy
import struct
import subprocess
import tempfile
import unittest

HERE = Path(__file__).resolve().parent
VERIFY = runpy.run_path(str(HERE / 'verify-pin-format.py'))['verify']
LIB = HERE / '../../sources/qemu-tools/usr/lib/libfdt.so.1'


@unittest.skipUnless(LIB.is_file(), 'Prepare local FDT tools for host-only fixtures')
class FormatEvidence(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.workspace = tempfile.TemporaryDirectory(prefix='format-evidence-host-only-')
        cls.binary = Path(cls.workspace.name) / 'producer'
        sources = ('pin-registry-core.c', 'vef-device.c', 'pinmem-device.c', 'pin-buffer-owner.c',
                   'pin-buffer-wire.c', 'pin-connection.c', 'pin-format.c', 'test-pin-connection.c')
        subprocess.run(['clang', '-std=c11', '-O2', '-pthread', '-Wall', '-Wextra', '-Werror',
                        '-DFULL_VEF_TEST', '-DPIN_CONTROL_TEST', '-DFULL_PIN_CONNECTION_TEST',
                        *[str(HERE / name) for name in sources], '-o', str(cls.binary)], check=True)

    @classmethod
    def tearDownClass(cls):
        cls.workspace.cleanup()

    def update_console(self, path, data):
        (path / 'console.log').write_bytes(data)
        result = json.loads((path / 'result.json').read_text())
        result.update(state='observation-completed', terminal_console_sha256=hashlib.sha256(data).hexdigest())
        (path / 'result.json').write_text(json.dumps(result))

    def fixture(self, path):
        helper = runpy.run_path(str(HERE / 'test-pin-control-verifier.py'))['BackingProof']
        helper.fixture(self, path)
        out = subprocess.run([str(self.binary)], capture_output=True, check=True,
                             env={**os.environ, 'PIN_CONNECTION_FORMAT_FIXTURE': str(path / 'pin-control-memory.bin')})
        self.assertTrue(out.stdout.startswith(b'HOST_FIXTURE_ONLY_NO_VM\n'))
        cache = re.search(rb'OBS FULL_PIN_FORMAT_CPU_STATE_READBACK tid=(\d+) handle=([^ ]+)', out.stdout)
        self.assertIsNotNone(cache)
        # The production observer performs this getter after native free. This
        # host fixture mocks that one record; it cannot pass the Native CLI.
        persistent = (b'OBS FULL_PIN_FORMAT_PERSISTENT_READBACK tid=' + cache[1] + b' handle=' + cache[2] +
                      b' format_cpu_consumed=1 buffer_released=1 live=0 pin_index=2 ordinal=1 code=1 component=0 encoded_flags=0 width=1920 height=1080 camera_startup_verified=0\n')
        data = re.sub(rb'(OBS FULL_PIN_CONNECT_NATIVE_REPLY_FREE [^\n]*\n)', lambda m: m[0] + persistent, out.stdout, count=1)
        self.update_console(path, data)
        inputs = json.loads((path / 'inputs.json').read_text())
        inputs['experiment'].update(pin_control_probe=False, pin_connection='control', pin_format='cold', stage='init2',
                                    vef_service='registry', pinmem_service='registry')
        (path / 'inputs.json').write_text(json.dumps(inputs))
        fdt = ctypes.CDLL(str(LIB));source = ctypes.create_string_buffer((path / 'virt.dtb').read_bytes());buffer = ctypes.create_string_buffer(65536)
        self.assertEqual(fdt.fdt_open_into(source, buffer, len(buffer)), 0)
        fdt.fdt_getprop.restype = ctypes.c_void_p
        chosen = fdt.fdt_path_offset(buffer, b'/chosen');size = ctypes.c_int()
        pointer = fdt.fdt_getprop(buffer, chosen, b'bootargs', ctypes.byref(size))
        command = ctypes.string_at(pointer, size.value).rstrip(b'\0') + b' fullsystem.pin-connect=control fullsystem.pin-format=cold\0'
        self.assertEqual(fdt.fdt_setprop(buffer, chosen, b'bootargs', command, len(command)), 0)
        self.assertEqual(fdt.fdt_pack(buffer), 0)
        (path / 'virt.dtb').write_bytes(buffer.raw[:struct.unpack_from('>I', buffer.raw, 4)[0]])

    def test_c_producer_positive_is_explicitly_not_native(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary);self.fixture(path)
            with self.assertRaisesRegex(ValueError, 'Host fixture'):
                VERIFY(path)
            proof = VERIFY(path, allow_host_fixture=True)
            self.assertTrue(proof['cold_cpu_format_consumed_verified'])
            self.assertEqual(proof['evidence_kind'], 'host-fixture-only')
            self.assertFalse(proof['original_next_get_waiter_copy_free_verified'])
            self.assertFalse(proof['camera_startup_verified'])

    def test_lifecycle_cache_and_actual_waiter_records_required(self):
        markers = (b'OBS FULL_PIN_FORMAT_REFERENCE_READBACK ', b'OBS FULL_PIN_FORMAT_CPU_STATE_READBACK ',
                   b'OBS FULL_PIN_FORMAT_PERSISTENT_READBACK ', b'OBS FULL_PIN_CONNECT_NATIVE_REPLY_FREE ')
        for marker in markers:
            with self.subTest(marker=marker), tempfile.TemporaryDirectory() as temporary:
                path = Path(temporary);self.fixture(path)
                self.update_console(path, b'\n'.join(line for line in (path / 'console.log').read_bytes().splitlines() if not line.startswith(marker)) + b'\n')
                with self.assertRaises((ValueError, StopIteration)):
                    VERIFY(path, allow_host_fixture=True)

    def test_ram_and_persistent_dimensions_are_independent_checks(self):
        for kind in ('ram', 'cache'):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as temporary:
                path = Path(temporary);self.fixture(path)
                if kind == 'ram':
                    data = bytearray((path / 'pin-control-memory.bin').read_bytes());data[72] ^= 1
                    (path / 'pin-control-memory.bin').write_bytes(data)
                else:
                    data = (path / 'console.log').read_bytes()
                    self.update_console(path, re.sub(rb'(OBS FULL_PIN_FORMAT_PERSISTENT_READBACK [^\n]*width=)1920', rb'\g<1>1280', data))
                with self.assertRaises(ValueError):
                    VERIFY(path, allow_host_fixture=True)

    def test_failed_observation_component_is_explicit_and_does_not_change_result(self):
        with tempfile.TemporaryDirectory() as temporary:
            path=Path(temporary);self.fixture(path)
            result=json.loads((path/'result.json').read_text())
            result.update(state='failed',error='Actual CPU format consumption/release and next original Get/free were not observed')
            original=json.dumps(result).encode();(path/'result.json').write_bytes(original)
            with self.assertRaisesRegex(ValueError,'Successful terminal'):
                VERIFY(path,allow_host_fixture=True)
            proof=VERIFY(path,allow_host_fixture=True,component_only=True)
            self.assertEqual(proof['original_run_state'],'failed')
            self.assertEqual(proof['verification_scope'],'component-only')
            self.assertFalse(proof['whole_run_success_verified'])
            self.assertEqual((path/'result.json').read_bytes(),original)
            result['error']='Original firmware fatal';(path/'result.json').write_text(json.dumps(result))
            with self.assertRaises(ValueError):VERIFY(path,allow_host_fixture=True,component_only=True)


if __name__ == '__main__':
    unittest.main()
