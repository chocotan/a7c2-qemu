"""The display switch must not choose the QEMU build.

An isolated USB-Ethernet run names a candidate QEMU build that carries the sysbus
xHCI controller. Before this test the native-window branch overwrote that choice
with the shipped `build-sony-ui`, so `-device usb-net` failed with
"No 'usb-bus' bus found" and the whole network run died at startup.
"""
import importlib.util
from pathlib import Path
import tempfile
import unittest

BASE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('menu_control', BASE/'menu_control.py')
control = importlib.util.module_from_spec(spec)
spec.loader.exec_module(control)
live_spec = importlib.util.spec_from_file_location('menu_live', BASE/'menu_live.py')
live = importlib.util.module_from_spec(live_spec)
live_spec.loader.exec_module(live)

CANDIDATE = '/tmp/candidate/qemu-11.1.2/build'


class IsolatedNetdevSocket(unittest.TestCase):
    def test_alias_keeps_the_socket_path_inside_the_af_unix_limit(self):
        # menu-runs paths are ~155 characters, past the 108-byte sun_path limit;
        # the peer must therefore connect through the short alias.
        with tempfile.TemporaryDirectory() as temporary:
            deep = Path(temporary)/('d'*60)/('e'*60)/'run-abcdefgh'
            deep.mkdir(parents=True)
            socket_path, alias = live.netdev_socket_alias(deep)
            try:
                self.assertGreater(len(str(deep/'ethernet.sock')), 107)
                self.assertLess(len(str(socket_path)), 108)
                self.assertTrue(alias.is_symlink())
                self.assertEqual(alias.parent, Path('/var/tmp'))
                self.assertEqual(socket_path.parent.resolve(), deep.resolve())
            finally:
                alias.unlink(missing_ok=True)

    def test_alias_is_replaced_when_a_stale_one_exists(self):
        with tempfile.TemporaryDirectory() as temporary:
            deep = Path(temporary)/'run-zzzzzzzz'
            deep.mkdir()
            socket_path, alias = live.netdev_socket_alias(deep)
            alias.unlink(missing_ok=True)
            second, alias2 = live.netdev_socket_alias(deep)
            try:
                self.assertEqual(str(second), str(socket_path))
                self.assertTrue(alias2.is_symlink())
            finally:
                alias2.unlink(missing_ok=True)

    def test_unrelated_file_is_preserved(self):
        with tempfile.TemporaryDirectory() as temporary:
            deep = Path(temporary)/'run-protect1'; deep.mkdir()
            _, alias = live.netdev_socket_alias(deep)
            alias.unlink()
            alias.write_bytes(b'keep unrelated file')
            try:
                with self.assertRaisesRegex(ValueError, 'unrelated socket alias'):
                    live.netdev_socket_alias(deep)
                self.assertEqual(alias.read_bytes(), b'keep unrelated file')
            finally:
                alias.unlink()


class BackupSaveForwarding(unittest.TestCase):
    """Backup_save is opt-in and must survive both launcher profiles.

    profile_environment() scrubs every MENU_* name, so a flag missing from both
    whitelists silently disables the experiment; that has happened three times.
    """

    def test_natural_and_non_natural_profiles_both_forward_the_flag(self):
        for natural in (True, False):
            forwarded = control.launcher.profile_environment(
                {'MENU_BACKUP_SAVE': '1'}, natural_boot=natural)
            self.assertEqual(forwarded.get('MENU_BACKUP_SAVE'), '1', natural)

    def test_flag_stays_absent_when_not_requested(self):
        for natural in (True, False):
            forwarded = control.launcher.profile_environment({}, natural_boot=natural)
            self.assertNotIn('MENU_BACKUP_SAVE', forwarded, natural)


class WifiCommand(unittest.TestCase):
    def _vm(self, usb_net):
        vm = control.VM(usb_net=usb_net)
        vm.state = 'running'
        return vm

    def test_wifi_is_refused_when_this_run_has_no_isolated_network(self):
        with self.assertRaises(ValueError):
            self._vm(False).enqueue({'action': 'wifi', 'enabled': True})

    def test_wifi_needs_a_real_boolean_not_an_int_or_string(self):
        for value in (1, 0, 'true', None, 'false'):
            with self.assertRaises(ValueError):
                self._vm(True).enqueue({'action': 'wifi', 'enabled': value})

    def test_wifi_is_queued_unchanged_when_enabled(self):
        vm = self._vm(True)
        vm.enqueue({'action': 'wifi', 'enabled': False})
        self.assertEqual(vm.commands.get_nowait(), {'action': 'wifi', 'enabled': False})


class NativeDisplayEnvironment(unittest.TestCase):
    def test_explicit_candidate_build_survives_the_display_switch(self):
        env = {'QEMU_SYSTEM_DIR': CANDIDATE}
        control.native_display_environment(env, 'gtk')
        self.assertEqual(env['QEMU_SYSTEM_DIR'], CANDIDATE)
        self.assertEqual(env['MENU_NATIVE_WINDOW'], '1')
        self.assertEqual(env['QEMU_NATIVE_DISPLAY'], 'gtk')
        self.assertEqual(env['QEMU_NATIVE_INPUT'], '1')

    def test_default_build_is_used_when_no_candidate_is_named(self):
        env = control.native_display_environment({}, 'gtk')
        self.assertTrue(env['QEMU_SYSTEM_DIR'].endswith('sources/qemu-11.1.2/build-sony-ui'))

    def test_candidate_named_for_usb_net_reaches_the_display_branch_intact(self):
        # The launcher forwards the candidate only in the isolated-USB profile;
        # the display branch must then keep that exact path.
        forwarded = control.launcher.profile_environment(
            {'MENU_USB_NET': '1', 'QEMU_SYSTEM_DIR': CANDIDATE,
             'QEMU_SYSTEM_BINARY': 'qemu-system-aarch64'}, natural_boot=True)
        self.assertEqual(forwarded['QEMU_SYSTEM_DIR'], CANDIDATE)
        control.native_display_environment(forwarded, 'gtk')
        self.assertEqual(forwarded['QEMU_SYSTEM_DIR'], CANDIDATE)

    def test_usb_profile_without_a_candidate_still_gets_the_shipped_build(self):
        forwarded = control.launcher.profile_environment({'MENU_USB_NET': '1'}, natural_boot=True)
        control.native_display_environment(forwarded, 'gtk')
        self.assertTrue(forwarded['QEMU_SYSTEM_DIR'].endswith('sources/qemu-11.1.2/build-sony-ui'))


if __name__ == '__main__':
    unittest.main()
