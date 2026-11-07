#!/usr/bin/env python3
"""P1 exact-input checks plus log boundaries; no VM or firmware writes."""
import hashlib
from pathlib import Path
import runpy
import shutil
import tempfile
import unittest

HERE = Path(__file__).resolve().parent
API = runpy.run_path(str(HERE / 'p1-file-media-contract.py'))
ROOT = HERE.parents[1] / 'analysis/scratch/p1-original-update-resources-20261106/update-build-v3/root'


def receipt(data=b'abc', **changes):
    fields = dict(pid=44, handle='a', generation=1, offset=0, requested=7,
                  actual=len(data), hashed=len(data), known=1, actor=1,
                  sha256=hashlib.sha256(data).hexdigest())
    fields.update(changes)
    return 'P1_BODY_READ ' + ' '.join(f'{key}={value}' for key, value in fields.items())


class Source(unittest.TestCase):
    @unittest.skipUnless(ROOT.exists() and shutil.which('aarch64-linux-gnu-readelf'), 'private original P1 root/tool absent')
    def test_exact_p1_bytes_and_version_bindings(self):
        result = API['inspect'](ROOT)
        self.assertEqual(len(result['pins']), 34)
        self.assertFalse(result['read_verified'])
        self.assertFalse(result['dependencies']['module_free'])
        self.assertIn('0xf6', result['binding']['readback_required'][1])
        self.assertEqual(next(p['offset'] for p in result['pins'] if p['name'] == 'mmca_path'), '0x6f5f8')
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / API['SAMPLES']['media'][0]
            path.parent.mkdir(parents=True)
            raw = bytearray((ROOT / API['SAMPLES']['media'][0]).read_bytes())
            raw[0x27f70] ^= 1
            path.write_bytes(raw)
            with self.assertRaisesRegex(ValueError, 'identity mismatch'):
                API['inspect'](directory)

    def test_va_translation_rejects_a_non_elf_and_wrong_arch(self):
        for data in (b'not elf' * 64, b'\x7fELF\x02\x01' + bytes(128)):
            with self.assertRaises(ValueError):
                API['va_offset'](data, 0, 4)


class Observations(unittest.TestCase):
    def observe(self, text, data=b'abcdefg'):
        return API['body_observations'](text, data, 44)

    def test_partial_probe_is_only_partial(self):
        result = self.observe(receipt())
        self.assertTrue(result['observations'][0]['matches_expected_slice'])
        self.assertFalse(result['observed_byte_coverage'])
        self.assertFalse(result['coverage'])
        self.assertFalse(result['read_verified'])

    def test_short_reads_rewind_and_multiopen_do_not_fill_holes(self):
        first = receipt()
        end = receipt(b'defg', offset=3, requested=8)
        self.assertTrue(self.observe(first + '\n' + end)['observed_byte_coverage'])
        for changes in ({'generation': 2}, {'handle': 'b'}, {'offset': 4}, {'pid': 45}):
            with self.subTest(changes=changes):
                self.assertFalse(self.observe(first + '\n' + receipt(b'defg', **{'offset': 3, 'requested': 8, **changes}))['observed_byte_coverage'])
        self.assertFalse(self.observe(first + '\n' + first)['observed_byte_coverage'])

    def test_unknown_error_bounds_digest_and_truncation_reject(self):
        for changes in ({'known': 0}, {'actor': 0}, {'actual': -7, 'hashed': 0, 'sha256': '-'},
                        {'actual': 8}, {'hashed': 4}, {'offset': 7}, {'sha256': '0' * 64}):
            with self.subTest(changes=changes):
                self.assertFalse(self.observe(receipt(**changes))['observations'][0]['matches_expected_slice'])
        for line in (receipt()[:-1], receipt() + ' suffix', 'P1_BODY_READ truncated'):
            with self.assertRaises(ValueError):
                self.observe(line)
        self.assertEqual(self.observe('FILE_MEDIA_READ file=1')['observations'], [])

    def test_hash_cap_contributes_only_hashed_bytes(self):
        data = b'x' * 65537
        result = self.observe(receipt(data[:65536], requested=len(data), actual=len(data)), data)
        self.assertTrue(result['observations'][0]['matches_expected_slice'])
        self.assertFalse(result['observed_byte_coverage'])


if __name__ == '__main__':
    unittest.main()
