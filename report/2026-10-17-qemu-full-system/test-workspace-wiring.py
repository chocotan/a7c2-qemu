#!/usr/bin/env python3
"""Launcher wiring: reload before boot, save only after a completed original path."""
from pathlib import Path
import runpy
import unittest
from unittest import mock

HERE = Path(__file__).resolve().parent
CAMERA = runpy.run_path(str(HERE / 'run-camera.py'))
LAUNCHER = runpy.run_path(str(HERE / 'start-official-camera.py'))



class Wiring(unittest.TestCase):
    def test_runner_gets_exclusive_config_export_only_when_workspace_is_used(self):
        configure = CAMERA['configuration']
        plain = configure(Path('/tmp/q'), 60)
        self.assertNotIn('--config-export-on-request', plain)

    def test_close_stops_input_before_waiting_for_session_save(self):
        source = (HERE / 'run-camera.py').read_text()
        close = source.split('if config_lock is not None and not input_closed_for_save', 1)[1]
        self.assertLess(close.index('stop_input_producer'), close.index('wait_for_card_save'))

    def test_save_failure_keeps_previous_generation_and_is_not_success(self):
        source = (HERE / 'run-camera.py').read_text()
        self.assertIn("if rc:raise RuntimeError('Configuration save failed", source)
        self.assertIn("'WORKSPACE_CONFIG_SAVED '", source)

    def test_save_reuses_the_session_lock_instead_of_locking_twice(self):
        # Regression: a second LOCK_EX from the same process (different open file
        # description) fails with EWOULDBLOCK and aborted every real save.
        source = (HERE / 'run-camera.py').read_text()
        self.assertEqual(source.count("config_api['locked']("), 1)
        self.assertIn("pointer=config_store.save_run(run,config_reference,expected_generation)", source)

    def test_launcher_reloads_before_starting_any_session(self):
        source = (HERE / 'start-official-camera.py').read_text()
        # Helpers above are definitions; the executed start block is this one.
        reload_at = source.index("store.load_into(runtime)")
        start_block = source.index("    if not args.prepare_only:", reload_at)
        self.assertLess(reload_at, start_block)
        self.assertLess(reload_at, source.index("desktop_storage_arguments(workspace", start_block))
        self.assertIn("WORKSPACE_CONFIG_LOADED", source)

    def test_official_launcher_holds_the_lease_and_passes_a_real_descriptor(self):
        source = (HERE / 'start-official-camera.py').read_text()
        self.assertIn("with config['locked'](workspace) as store:", source)
        self.assertIn("prepared=start_owned(args,workspace,store)", source)
        self.assertIn("pass_fds=(store.fd,)", source)
        self.assertIn("'--workspace-lock-fd',str(store.fd)", source)

    def test_official_sd_entry_enables_both_serialized_exports(self):
        arguments = LAUNCHER['desktop_storage_arguments'](Path('/tmp/work space'), True)
        self.assertEqual(arguments, ['--config-workspace', '/tmp/work space', '--attach-sd', '--workspace', '/tmp/work space'])

    def test_official_non_sd_entry_enables_configuration_save(self):
        arguments = LAUNCHER['desktop_storage_arguments'](Path('/tmp/work space'), False)
        self.assertEqual(arguments, ['--config-workspace', '/tmp/work space'])


if __name__ == '__main__':
    unittest.main()
