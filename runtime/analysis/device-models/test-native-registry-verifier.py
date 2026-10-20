"""Check native metadata identity and reject corrupted wire/ownership evidence."""
import json
import os
from pathlib import Path
import re
import runpy
import shutil
import tempfile
import unittest

VERIFY = runpy.run_path(str(Path(__file__).with_name('verify-vef-pin.py')))['verify_registry']


def drawinfo(run):
    return VERIFY(run, 'DRAWINFO', '', 0x928d0783, [(0, 1, 0), (6, 1, 0)], (6, 1, 0), 1, native=True)


@unittest.skipUnless(os.environ.get('A7C2_NATIVE_GET_RUN'), 'Set A7C2_NATIVE_GET_RUN to DrawInfo observation')
class NativeRegistry(unittest.TestCase):
    def test_real_get_and_original_waiter(self):
        proof = drawinfo(Path(os.environ['A7C2_NATIVE_GET_RUN']))
        self.assertTrue(proof['pin_registry_query_verified'])
        self.assertEqual(proof['evidence_kind'], 'native')
        self.assertFalse(proof['whole_run_success_verified'])
        self.assertFalse(proof['connection_verified'])

    def test_wire_lease_free_and_profile_corruption_rejected(self):
        for kind in ('wire', 'lease', 'free', 'profile', 'identity'):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as temporary:
                dst = Path(temporary)
                src = Path(os.environ['A7C2_NATIVE_GET_RUN'])
                for name in ('console.log', 'runtime-manifest.json', 'summary.json'):
                    shutil.copyfile(src / name, dst / name)
                summary = json.loads((dst / 'summary.json').read_text())
                summary['run'] = str(src if kind == 'identity' else dst)
                (dst / 'summary.json').write_text(json.dumps(summary))
                if kind == 'profile':
                    manifest = json.loads((dst / 'runtime-manifest.json').read_text())
                    manifest['pin_registry_service'] = False
                    (dst / 'runtime-manifest.json').write_text(json.dumps(manifest))
                lines = (dst / 'console.log').read_text().splitlines(keepends=True)
                for i, line in enumerate(lines):
                    if kind == 'wire' and line.startswith('OBS FULL_DRAWINFO_REPLY_QUEUED '):
                        raw = re.search(r'raw=([0-9a-f]+)', line)[1]
                        changed = bytearray.fromhex(raw); changed[48] ^= 1
                        lines[i] = line.replace(raw, changed.hex())
                    if line.startswith('OBS FULL_DRAWINFO_NATIVE_REPLY_FREE '):
                        if kind == 'free':
                            lines[i] = ''
                        elif kind == 'lease':
                            lines[i] = re.sub(r'lease=\d+', 'lease=999', line)
                (dst / 'console.log').write_text(''.join(lines))
                with self.assertRaises((ValueError, StopIteration)):
                    drawinfo(dst)


@unittest.skipUnless(os.environ.get('A7C2_NATIVE_OSDPIN_RUN'), 'Set A7C2_NATIVE_OSDPIN_RUN')
class NativeOsdRegistry(unittest.TestCase):
    def verify(self, run):
        return VERIFY(run, 'OSDPIN', '', 0x9080003b, [(1, 3, 0)], (1, 3, 0), 0,
                      native=True, reply_sid=0x9080003b)

    def test_own_reply_sid_and_event_omission(self):
        run = Path(os.environ['A7C2_NATIVE_OSDPIN_RUN'])
        self.assertTrue(self.verify(run)['pin_registry_query_verified'])
        scope = next(line for line in (run / 'console.log').read_text().splitlines()
                     if line.startswith('OBS FULL_OSDPIN_SCOPE '))
        self.assertIn('event_emitted=0', scope)
        self.assertIn('event_consumer_verified=0', scope)
        with tempfile.TemporaryDirectory() as temporary:
            dst = Path(temporary)
            for name in ('console.log', 'runtime-manifest.json', 'summary.json'):
                shutil.copyfile(run / name, dst / name)
            summary = json.loads((dst / 'summary.json').read_text()); summary['run'] = str(dst)
            (dst / 'summary.json').write_text(json.dumps(summary))
            lines = (dst / 'console.log').read_text().splitlines(keepends=True)
            for i, line in enumerate(lines):
                if line.startswith('OBS FULL_OSDPIN_REPLY_QUEUED '):
                    raw = re.search(r'raw=([0-9a-f]+)', line)[1]
                    lines[i] = line.replace(raw, '00000000' + raw[8:])
            (dst / 'console.log').write_text(''.join(lines))
            with self.assertRaises(ValueError):
                self.verify(dst)


if __name__ == '__main__':
    unittest.main()
