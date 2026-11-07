"""Desktop close requests must drain input and save before runner termination."""
import os
from pathlib import Path
import runpy
import subprocess
import tempfile
import unittest
from unittest.mock import Mock

HERE=Path(__file__).resolve().parent
UI=runpy.run_path(str(HERE/'run-camera.py'))
VM=runpy.run_path(str(HERE/'run-full-system.py'))


class SaveRequest(unittest.TestCase):
    def test_config_only_deadline_stops_ui_and_acknowledges_the_runner(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);(root/'input-quiesce.request').write_bytes(b'stop')
            ui=Mock();ui.poll.return_value=None
            vm=Mock();vm.poll.return_value=None
            self.assertTrue(UI['wait_ui_or_save'](ui,vm,root,True))
            ui.terminate.assert_called_once()
            self.assertTrue(VM['card_input_stopped'](root))

    def test_no_save_mode_does_not_acknowledge_an_unexpected_stop_request(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);(root/'input-quiesce.request').write_bytes(b'stop')
            ui=Mock();ui.poll.side_effect=[None,0]
            vm=Mock();vm.poll.return_value=None
            self.assertFalse(UI['wait_ui_or_save'](ui,vm,root,False))
            ui.terminate.assert_not_called()
            self.assertFalse((root/'input-producer-stopped').exists())

    def test_deadline_stops_and_joins_ui_before_ack_and_drains_last_commands(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);vmrun=Mock(return_value=b'last command receipt')
            ui=Mock();ui.poll.return_value=None
            def final_input(timeout):
                self.assertFalse((root/'input-producer-stopped').exists())
                (root/'last.cmd').write_text('original final key')
                return 0
            ui.wait.side_effect=final_input
            UI['stop_input_producer'](ui,root)
            self.assertTrue(VM['card_input_stopped'](root))
            ui.terminate.assert_called_once();ui.wait.assert_called_once_with(timeout=5)
            VM['quiesce_card_inputs'](root,vmrun,timeout=0)
            vmrun.assert_called_once_with('original final key',timeout=30)
            self.assertFalse((root/'last.cmd').exists())
            self.assertEqual((root/'last.out').read_bytes(),b'last command receipt')

    def test_missing_stop_ack_refuses_save_even_with_empty_queue(self):
        with tempfile.TemporaryDirectory() as directory:
            vmrun=Mock()
            with self.assertRaisesRegex(TimeoutError,'did not stop'):
                VM['quiesce_card_inputs'](directory,vmrun,timeout=0)
            vmrun.assert_not_called()

    def test_input_after_stop_ack_and_failed_input_refuse_save(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);(root/'input-producer-stopped').write_bytes(VM['CARD_INPUT_STOPPED'])
            (root/'last.cmd').write_text('one')
            def late_input(*args,**kwargs):
                (root/'unexpected.cmd').write_text('late command');return b'receipt'
            with self.assertRaisesRegex(RuntimeError,'after producer-stop'):
                VM['quiesce_card_inputs'](root,late_input)
            self.assertTrue((root/'unexpected.cmd').exists())
            with self.assertRaisesRegex(RuntimeError,'serial failed'):
                VM['quiesce_card_inputs'](root,Mock(side_effect=RuntimeError('serial failed')))
            self.assertTrue((root/'unexpected.cmd').exists())

    def test_stop_ack_is_not_written_until_ui_is_reaped(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);ui=Mock();ui.poll.return_value=None
            ui.wait.side_effect=[subprocess.TimeoutExpired('UI',5),subprocess.TimeoutExpired('UI',5)]
            with self.assertRaises(subprocess.TimeoutExpired):UI['stop_input_producer'](ui,root)
            self.assertFalse((root/'input-producer-stopped').exists())

    def test_atomic_request_waits_for_pending_commands_to_drain(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            self.assertFalse(VM['card_save_requested'](root))
            command=root/'001.cmd';command.write_text('original input')
            UI['request_card_save'](root)
            self.assertFalse((root/'save-card-and-exit.next').exists())
            self.assertFalse(VM['card_save_requested'](root))
            command.unlink()
            self.assertTrue(VM['card_save_requested'](root))

    def test_wrong_content_symlink_and_fifo_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);request=root/'save-card-and-exit.request'
            request.write_bytes(b'not a save request')
            with self.assertRaises(ValueError):VM['card_save_requested'](root)
            request.unlink();source=root/'source';source.write_bytes(VM['CARD_SAVE_REQUEST'])
            request.symlink_to(source)
            with self.assertRaises(OSError):VM['card_save_requested'](root)
            request.unlink();os.mkfifo(request)
            with self.assertRaises(ValueError):VM['card_save_requested'](root)

    def test_close_waits_without_sending_interrupt_or_kill(self):
        vm=Mock();vm.poll.return_value=None;vm.wait.return_value=0
        with tempfile.TemporaryDirectory() as directory:
            self.assertEqual(UI['wait_for_card_save'](vm,directory),0)
            self.assertTrue(VM['card_save_requested'](directory))
        vm.wait.assert_called_once_with(timeout=180)
        vm.send_signal.assert_not_called();vm.kill.assert_not_called()

    def test_failed_or_timed_out_save_does_not_turn_into_success(self):
        with tempfile.TemporaryDirectory() as directory:
            vm=Mock();vm.poll.return_value=None;vm.wait.return_value=1
            self.assertEqual(UI['wait_for_card_save'](vm,directory),1)
        with tempfile.TemporaryDirectory() as directory:
            vm=Mock();vm.poll.return_value=None
            vm.wait.side_effect=subprocess.TimeoutExpired('owned runner',180)
            with self.assertRaises(subprocess.TimeoutExpired):UI['wait_for_card_save'](vm,directory)

    def test_dead_runner_does_not_receive_a_new_request(self):
        vm=Mock();vm.poll.return_value=1;vm.returncode=1
        with tempfile.TemporaryDirectory() as directory:
            self.assertEqual(UI['wait_for_card_save'](vm,directory),1)
            self.assertFalse(list(Path(directory).iterdir()))
        vm.wait.assert_not_called()


if __name__=='__main__':unittest.main()
