from pathlib import Path
import os
import subprocess
import tempfile
import unittest

HERE = Path(__file__).resolve().parent
MODEL = HERE / 'device-models'


class TouchPanelModel(unittest.TestCase):
    def test_sanitized_valid_subset_and_failures(self):
        with tempfile.TemporaryDirectory() as directory:
            binary = Path(directory) / 'touch-panel'
            built = subprocess.run([
                'cc', '-std=c11', '-Wall', '-Wextra', '-Werror', '-pedantic', '-g',
                '-fsanitize=address,undefined', '-fno-omit-frame-pointer', '-no-pie', '-pthread',
                '-DFULL_TOUCH_PANEL_TEST', str(MODEL / 'touch-panel-device.c'),
                str(MODEL / 'test-touch-panel.c'), '-o', str(binary),
            ], capture_output=True, text=True, timeout=30)
            self.assertEqual(built.returncode, 0, built.stdout + built.stderr)
            environment = dict(os.environ, ASAN_OPTIONS='detect_leaks=1:abort_on_error=1',
                               UBSAN_OPTIONS='halt_on_error=1')
            cases = ['normal0', 'normal1', 'reuse', 'invalid', 'alloc-fail', 'send-fail',
                     'request-free-fail', 'reply-free-fail', 'duplicate', 'concurrent']
            for case in cases:
                with self.subTest(case=case):
                    result = subprocess.run([str(binary), case], cwd=directory, env=environment,
                                            capture_output=True, text=True, timeout=20)
                    self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                    self.assertEqual(result.stdout.strip(), f'TOUCH_PANEL_TEST_PASS {case}')

    def test_scope_is_configuration_not_hardware(self):
        source = (MODEL / 'touch-panel-device.c').read_text()
        self.assertIn('0x00590000', source)
        self.assertIn('FULL_TOUCH_PANEL_F02F_DEST', source)
        self.assertIn('control_result_verified=0', source)
        self.assertIn('f02f_transport_verified=0', source)
        self.assertIn('original_cp_executed=0', source)
        self.assertIn('hardware_touch_verified=0', source)
        self.assertIn('in[8]>1', source)

    def test_observer_and_profile_gates(self):
        observer = (HERE / 'menu-observe.c').read_text()
        build = (HERE / 'build-observers.sh').read_text()
        probe = (HERE / 'qemu-menu-probe.py').read_text()
        gtk = (HERE / 'check-natural-gtk-input.py').read_text()
        self.assertIn('touch-panel-device.h', observer)
        self.assertIn('full_touch_panel_dispatch', observer)
        self.assertIn('full_touch_panel_release_reply', observer)
        self.assertIn('"FULL_TOUCH_PANEL_"', observer)
        self.assertIn('touch-panel-device', build)
        self.assertIn('touch_panel_profile', probe)
        self.assertIn('touch_panel_f02f_transport_verified', probe)
        self.assertIn('export MENU_TOUCH_PANEL=virtual-config-v1', probe)
        self.assertIn('touch_panel_admission', gtk)
        self.assertIn('TOUCH_PANEL_PROFILE_BOUND', gtk)
        env = {k: v for k, v in os.environ.items()
               if not k.startswith(('MENU_', 'A7C2_', 'QEMU_', 'SONY_'))}
        base = [os.environ.get('PYTHON', 'python3'), str(HERE / 'qemu-menu-probe.py'),
                '--initramfs', '--observe']
        result = subprocess.run(base, env=dict(env, MENU_TOUCH_PANEL='virtual-config-v1',
                                               MENU_CP_BACKGROUND='virtual-mode3-cold-v1'),
                                capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 2)
        self.assertIn('MENU_TOUCH_PANEL requires CP3007+UDATE', result.stderr)
        result = subprocess.run(base, env=dict(env, MENU_TOUCH_PANEL='virtual-config-v1',
                                               MENU_CP_BACKGROUND='virtual-mode3-cold-v1',
                                               MENU_UDATE_DISTRIBUTION='virtual-roundtrip-v1',
                                               MENU_PIPELINE_ENDPOINT='1'),
                                capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 2)
        self.assertIn('MENU_TOUCH_PANEL requires CP3007+UDATE', result.stderr)
        self.assertNotIn('NameError', result.stderr)


if __name__ == '__main__':
    unittest.main()
