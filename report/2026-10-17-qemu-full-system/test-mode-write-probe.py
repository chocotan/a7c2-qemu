"""Reuse the original-store fixture for mode-specific capture and coverage."""
import json
from pathlib import Path
import runpy
import tempfile
import unittest
from unittest.mock import patch

HERE=Path(__file__).resolve().parent
Mode=runpy.run_path(str(HERE/'mode-write-probe.py'))['ModeWriteProbe']
Fixture=runpy.run_path(str(HERE/'test-shutdown-watch.py'))['WatchStore']


class ModeStore(unittest.TestCase):
    def make(self,directory,value,writes=0,missing_code=False):
        make=Fixture.make
        with patch.dict(make.__globals__,{'Probe':Mode}):
            probe=make(self,directory,value,writes)
        original=probe.memory
        def memory(address,size):
            if address-probe.base in Mode.CODE_OFFSETS:
                if missing_code:raise RuntimeError('RSP error: E14')
                self.assertEqual(size,4);return bytes.fromhex('fd7bb6a9')
            return original(address,size)
        probe.memory=memory
        return probe

    def test_capture_original_movie_store_without_model_write(self):
        with tempfile.TemporaryDirectory() as directory:
            probe=self.make(directory,3);probe.check()
            self.assertTrue(probe.captured and probe.finished)
            result=json.loads((Path(directory)/Mode.CAPTURE_FILE).read_text())
            self.assertEqual(result['model_after_hex'][:8],'03000000')
            self.assertEqual(len(result['original_appfw_code_windows']),6)
            self.assertEqual(probe.commands[-1],'c')
            self.assertFalse(any(c.startswith(('M','X','P','G')) for c in probe.commands))
            self.assertFalse((Path(directory)/'shutdown-factor-15.json').exists())

    def test_no_movie_within_limit_is_not_a_capture(self):
        with tempfile.TemporaryDirectory() as directory:
            probe=self.make(directory,2,writes=31);probe.check()
            self.assertTrue(probe.finished);self.assertFalse(probe.captured)
            self.assertTrue((Path(directory)/Mode.LIMIT_FILE).is_file())

    def test_unmapped_optional_code_is_preserved_as_unknown(self):
        with tempfile.TemporaryDirectory() as directory:
            probe=self.make(directory,3,missing_code=True);probe.check()
            result=json.loads((Path(directory)/Mode.CAPTURE_FILE).read_text())
            self.assertTrue(all('read_error' in value for value in result['original_appfw_code_windows'].values()))


if __name__=='__main__':unittest.main()
