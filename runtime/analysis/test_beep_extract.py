"""Host test for the beep extractor (no guest, no audio device).

The extractor only slices bytes the firmware ships: `beeplist.txt` gives
id/size/offset, and each per-beep `.bin` must equal that slice of `SysSound.bin`.
"""
from pathlib import Path
import json
import struct
import subprocess
import sys
import tempfile
import unittest
import wave

HERE = Path(__file__).resolve().parent
ROOT = HERE/'menu-root/usr/share/avsystemsound'
sys.path.insert(0, str(HERE))
import importlib.util
spec = importlib.util.spec_from_file_location('beep_extract', HERE/'beep-extract.py')
beep_extract = importlib.util.module_from_spec(spec)
spec.loader.exec_module(beep_extract)


class BeepExtract(unittest.TestCase):
    def setUp(self):
        if not (ROOT/'beeplist.txt').is_file() or not (ROOT/'SysSound.bin').is_file():
            self.skipTest('original beep assets are not present')

    def test_index_rows_are_parsed_with_offsets(self):
        index = beep_extract.parse_index((ROOT/'beeplist.txt').read_text(errors='replace'))
        self.assertIn(0x0000, index)
        startup = index[0x0000]
        self.assertEqual(startup['name'], 'BEEP_ID_STARTUP')
        self.assertEqual(startup['size'], 0x2000)
        self.assertEqual(startup['offset'], 0x97C0)
        # Rows whose size/offset are N/A must stay explicitly incomplete.
        self.assertTrue(any(row['size'] is None for row in index.values()))
        self.assertEqual(len(index), 36)

    def test_every_slice_matches_the_shipped_standalone_file(self):
        index = beep_extract.parse_index((ROOT/'beeplist.txt').read_text(errors='replace'))
        sound = (ROOT/'SysSound.bin').read_bytes()
        checked = 0
        for beep in index.values():
            if beep['size'] is None or beep['offset'] is None:
                continue
            standalone = ROOT/beep['file']
            if not standalone.is_file():
                continue
            self.assertEqual(beep_extract.slice_beep(sound, beep), standalone.read_bytes(),
                             beep['name'])
            checked += 1
        self.assertGreaterEqual(checked, 5, 'too few slices verified')

    def test_extracted_wav_matches_the_slice(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary)/'startup.wav'
            result = subprocess.run(
                [sys.executable, str(HERE/'beep-extract.py'), '--rate', '48000',
                 '--beep', '0x0000', '--output', str(output), '--json'],
                text=True, capture_output=True, timeout=120)
            self.assertEqual(result.returncode, 0, result.stderr)
            report = json.loads(result.stdout)
            self.assertEqual(report['bytes'], 0x2000)
            self.assertTrue(report['slice_matches_standalone'])
            with wave.open(str(output)) as wav:
                self.assertEqual((wav.getnchannels(), wav.getsampwidth(), wav.getframerate()),
                                 (1, 2, 48000))
                self.assertEqual(wav.getnframes(), report['frames'])
                payload = wav.readframes(wav.getnframes())
            self.assertEqual(len(payload), (report['bytes'] - 128)//2*2)
            samples = struct.unpack('<%dh' % (len(payload)//2), payload)
            self.assertGreater(max(samples), 1000, 'extracted audio is silent')

    def test_incomplete_rows_fall_back_to_the_standalone_file(self):
        index = beep_extract.parse_index((ROOT/'beeplist.txt').read_text(errors='replace'))
        sound = (ROOT/'SysSound.bin').read_bytes()
        incomplete = [row for row in index.values() if row['size'] is None]
        self.assertTrue(incomplete)
        # A container offset is genuinely absent, so the container reader refuses...
        with self.assertRaises(ValueError):
            beep_extract.slice_beep(sound, incomplete[0])
        # ...but the shipped standalone file still resolves, and is real audio.
        raw, source = beep_extract.resolve_beep(ROOT, sound, incomplete[0])
        self.assertEqual(source, 'standalone')
        self.assertGreater(len(beep_extract.pcm_samples(raw)), 1000)

    def test_every_indexed_beep_resolves_and_sources_agree(self):
        index = beep_extract.parse_index((ROOT/'beeplist.txt').read_text(errors='replace'))
        sound = (ROOT/'SysSound.bin').read_bytes()
        sources = {'container': 0, 'standalone': 0}
        header_only = []
        for beep in index.values():
            raw, source = beep_extract.resolve_beep(ROOT, sound, beep)
            sources[source] += 1
            payload = beep_extract.pcm_samples(raw)
            if not payload:
                header_only.append(beep['name'])
            else:
                self.assertTrue(payload, beep['name'])
        self.assertGreaterEqual(sources['container'], 10)
        self.assertGreaterEqual(sources['standalone'], 10)
        # A 128-byte slice is preamble only: no PCM, and that must stay visible
        # instead of being presented as a playable sound.
        self.assertIn('BEEP_ID_KA', header_only)

    def test_missing_both_sources_is_refused(self):
        index = beep_extract.parse_index((ROOT/'beeplist.txt').read_text(errors='replace'))
        sound = (ROOT/'SysSound.bin').read_bytes()
        row = dict(index[0x0000], file='definitely-absent.bin', size=None, offset=None)
        with self.assertRaises(ValueError):
            beep_extract.resolve_beep(ROOT, sound, row)


if __name__ == '__main__':
    unittest.main()
