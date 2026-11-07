#!/usr/bin/env python3
"""Host fixtures test evidence rejection; none is native camera evidence."""
import hashlib
import json
from pathlib import Path
import re
import runpy
import struct
import tempfile
import unittest

HERE = Path(__file__).resolve().parent
VEF = runpy.run_path(str(HERE / 'verify-vef-pin.py'))['verify']
PINMEM = runpy.run_path(str(HERE / 'verify-pinmem-pin.py'))['verify']


def write_fixture(path, console, inputs):
    (path / 'console.log').write_bytes(console)
    (path / 'inputs.json').write_text(json.dumps(inputs))
    (path / 'result.json').write_text(json.dumps({'terminal_evidence_checked': True,
        'terminal_console_sha256': hashlib.sha256(console).hexdigest(), 'host_fixture_only': True}))


def mock_owner(family, owner, properties, keys, slot, tid):
    """Protocol-only fixture deliberately independent of production dispatch."""
    prefix = 'OBS FULL_' + family + '_'
    rows = [prefix + f'PIN_CREATED slot={i} type={k[0]} dir={k[1]} index={k[2]} owner={owner:#x} state=1 '
            'peer_type=255 peer_dir=255 peer_index=0 peer_owner=0' for i, k in enumerate(properties)]
    destination = 0x81cf61c3
    request = bytearray(48)
    struct.pack_into('<IIHHIII', request, 0, destination, 0xa0a0a0a0, 1, 48, 24, 48, 0x7f)
    struct.pack_into('<4H4I', request, 24, 0x1000, 0, 24, 2, *keys, 0)
    reply = bytearray(56)
    struct.pack_into('<IIHHIII', reply, 0, 0, 0xa0a0a0a0, 1, 56, 24, 56, 0)
    struct.pack_into('<4H6I', reply, 24, 0x1000, 0x8000, 32, 2, *keys, 1, owner, 0)
    pointer = '0x7001' if family == 'VEF' else '0x7002'
    rows.extend((
        prefix + f'REQUEST tid={tid} destination={owner:#x} source={destination:#x} reply_destination={destination:#x} bytes=48 raw={request.hex()}',
        prefix + f'REPLY_QUEUED tid={tid} source={owner:#x} destination={destination:#x} reply={pointer} lease=1 bytes=56 raw={reply.hex()}',
        prefix + f'COMMIT tid={tid} slot={slot} type={keys[0]} dir={keys[1]} index={keys[2]} pin_state=1 owner={owner:#x} status=0 '
        f'queries=1 reply={pointer} lease=1 request_free_rc=0 connect_performed=0 pixels_consumed=0 camera_startup_verified=0',
        prefix + f'NATIVE_REPLY_FREE tid={tid} sender={tid} waiter=1 destination={destination:#x} expected={destination:#x} reply={pointer} lease=1 bytes=56 rc=0'))
    return rows


class CrossOwnerFixture(unittest.TestCase):
    def setUp(self):
        self.source = mock_owner('VEF', 0x905a0048, [(0, d, i) for d in (1, 2) for i in range(7)] + [(8, 1, 0), (8, 2, 0)], (0, 2, 3), 10, 7)
        properties = [(0, 1, i) for i in range(3)] + [(0, 2, i) for i in range(4)] + [(4, 2, 0), (1, 3, 0), (4, 1, 0), (6, 2, 0), (6, 1, 0), (8, 1, 0)]
        self.peer = mock_owner('PINMEM', 0x90590818, properties, (0, 1, 1), 1, 7)

    def fixture(self, path, rows):
        write_fixture(path, ('\n'.join(rows) + '\n').encode(), {'experiment': {'vef_service': 'registry', 'pinmem_service': 'registry'}})

    def test_same_waiter_ordered_two_gets_parser_only(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary);self.fixture(path, self.source + self.peer)
            self.assertTrue(PINMEM(path)['source_get_to_same_waiter_peer_get_verified'])

    def test_independently_valid_peer_from_other_waiter_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary)
            self.fixture(path, self.source + [line.replace('tid=7', 'tid=8').replace('sender=7', 'sender=8') for line in self.peer])
            with self.assertRaisesRegex(ValueError, 'same original waiter'):
                PINMEM(path)

    def test_peer_before_actual_source_free_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary);self.fixture(path, self.source[:-1] + self.peer + self.source[-1:])
            with self.assertRaisesRegex(ValueError, 'same original waiter'):
                PINMEM(path)


class ScalarRegistryFixture(unittest.TestCase):
    def test_scalar_exact_owner_and_actual_waiter_required(self):
        verify=runpy.run_path(str(HERE/'verify-vef-pin.py'))['verify_registry']
        props=[(0,d,i) for d in (1,2) for i in range(5)]
        rows=mock_owner('SCALAR',0x91670464,props,(0,1,4),4,19)
        with tempfile.TemporaryDirectory() as temporary:
            path=Path(temporary)
            write_fixture(path,('\n'.join(rows)+'\n').encode(),{'experiment':{'scalar_service':'registry'}})
            self.assertTrue(verify(path,'SCALAR','scalar_service',0x91670464,props,(0,1,4),4)['pin_registry_query_verified'])
            for tag in ('COMMIT','NATIVE_REPLY_FREE'):
                changed=[line for line in rows if not line.startswith('OBS FULL_SCALAR_'+tag+' ')]
                write_fixture(path,('\n'.join(changed)+'\n').encode(),{'experiment':{'scalar_service':'registry'}})
                with self.assertRaises(StopIteration):verify(path,'SCALAR','scalar_service',0x91670464,props,(0,1,4),4)


class NativeBaselineMutations(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        run = HERE / 'runtime/analysis/runs/run-du3q5xp5'
        if not run.is_dir():
            raise unittest.SkipTest('Private native baseline not present')
        cls.console = (run / 'console.log').read_bytes()
        cls.inputs = json.loads((run / 'inputs.json').read_text())

    def test_preserved_baseline_is_still_accepted(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary);write_fixture(path, self.console, self.inputs)
            self.assertTrue(VEF(path)['vef_pin_query_verified'])

    def test_counterfactual_semantics_rejected_with_matching_terminal_hash(self):
        def change_raw(row):
            raw = re.search(rb'raw=([0-9a-f]+)', row)[1];wire = bytearray.fromhex(raw.decode());wire[4] = 0
            return row.replace(raw, wire.hex().encode())
        cases = [('REQUEST', lambda row: row.replace(b'destination=0x905a0048', b'destination=0x9059000e'), 'Request owner'),
                 ('REQUEST', change_raw, 'Dataflow envelope'),
                 ('COMMIT', lambda row: row.replace(b'index=3', b'index=4'), 'Registry consumption'),
                 ('NATIVE_REPLY_FREE', lambda row: row.replace(b'waiter=1', b'waiter=0'), 'Original AP waiter')]
        for tag, transform, reason in cases:
            with self.subTest(tag=tag, reason=reason), tempfile.TemporaryDirectory() as temporary:
                row = re.search(rb'OBS FULL_VEF_' + tag.encode() + rb' [^\r\n]+', self.console)[0]
                data = self.console.replace(row, transform(row));self.assertNotEqual(data, self.console)
                path = Path(temporary);write_fixture(path, data, self.inputs)
                with self.assertRaisesRegex(ValueError, reason):
                    VEF(path)


if __name__ == '__main__':
    unittest.main()
