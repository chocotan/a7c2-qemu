"""Finite no-change panel completion and routing; no physical display assertion."""
from pathlib import Path
import os
import subprocess
import tempfile
import unittest

N = Path(__file__).resolve().parent

class PanelOutTests(unittest.TestCase):
    def test_nochange_and_ownership(self):
        with tempfile.TemporaryDirectory(prefix='vdf-panel-', dir=os.environ['TMPDIR']) as folder:
            output = Path(folder) / 'test'
            subprocess.run(['cc', '-std=c11', '-Wall', '-Wextra', '-Werror', '-O1', '-g', '-pthread',
                            '-DFULL_VDF_TEST', '-fsanitize=address,undefined', '-fno-omit-frame-pointer',
                            str(N/'device-models/vdf-device.c'), str(N/'device-models/test-vdf-panel-out.c'),
                            '-o', str(output)], check=True)
            subprocess.run([str(output)], check=True)

    def test_original_shutdown_zoom_reaches_config_owner(self):
        text = (N/'menu-observe.c').read_text()
        route = text.split('if(bytes>=4 && wire[0]==5 && command==0x4001) {', 1)[1].split('int selected=', 1)[0]
        self.assertLess(route.index('native_cp_background_dispatch'), route.index('cp302c_no_transition_predecessors_ready'))
        self.assertIn('"virtual-mode3-cold-v1"', route)
        self.assertIn('functional_cp_zoom_dispatch', route)
        self.assertIn('headless_osd_enabled && full_vdf_panel_out_dispatch', text)
        self.assertIn('headless_panel_owner_pid==getpid() && headless_thread_live && !headless_stop', text)

if __name__ == '__main__':
    unittest.main()
