"""Reuse the full content verifier against native identity and negative copies."""
import json
import os
from pathlib import Path
import runpy
import shutil
import tempfile
import unittest

VERIFY = runpy.run_path(str(Path(__file__).with_name('verify-pin-format.py')))['verify']


@unittest.skipUnless(os.environ.get('A7C2_NATIVE_PIN_RUN'), 'Set A7C2_NATIVE_PIN_RUN')
class NativeContent(unittest.TestCase):
    def test_original_observation(self):
        proof = VERIFY(Path(os.environ['A7C2_NATIVE_PIN_RUN']), native=True)
        self.assertTrue(proof['cold_cpu_format_consumed_verified'])
        self.assertTrue(proof['buffer_last_reference_released'])
        self.assertFalse(proof['whole_run_success_verified'])
        self.assertFalse(proof['camera_startup_verified'])

    def test_corrupted_memory_state_and_missing_free_are_rejected(self):
        for corruption in ('memory', 'state', 'free', 'profile'):
            with self.subTest(corruption=corruption), tempfile.TemporaryDirectory(prefix='native-pin-negative-') as temp:
                src, dst = Path(os.environ['A7C2_NATIVE_PIN_RUN']), Path(temp)
                for name in ('console.log', 'runtime-manifest.json', 'summary.json', 'virt.dtb', 'pin-control-ram.bin'):
                    shutil.copyfile(src / name, dst / name)
                summary = json.loads((dst / 'summary.json').read_text())
                summary['run'] = str(dst)
                (dst / 'summary.json').write_text(json.dumps(summary))
                if corruption == 'memory':
                    raw = bytearray((dst / 'pin-control-ram.bin').read_bytes())
                    raw[72] ^= 1
                    (dst / 'pin-control-ram.bin').write_bytes(raw)
                elif corruption == 'profile':
                    manifest = json.loads((dst / 'runtime-manifest.json').read_text())
                    manifest['pin_connection_mode'] = ''
                    (dst / 'runtime-manifest.json').write_text(json.dumps(manifest))
                else:
                    text = (dst / 'console.log').read_text()
                    if corruption == 'state':
                        self.assertIn('source_state=0', text)
                        text = text.replace('source_state=0', 'source_state=1')
                    else:
                        text = '\n'.join(line for line in text.splitlines()
                                         if 'FULL_PIN_CONNECT_NATIVE_REPLY_FREE ' not in line)
                    (dst / 'console.log').write_text(text)
                with self.assertRaises((ValueError, StopIteration, KeyError)):
                    VERIFY(dst, native=True)


if __name__ == '__main__':
    unittest.main()
