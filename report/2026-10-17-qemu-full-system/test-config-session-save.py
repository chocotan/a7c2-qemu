#!/usr/bin/env python3
"""The exit path must stop input, call the real subsystem API once, then export."""
from pathlib import Path
import runpy
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

VM = runpy.run_path(str(Path(__file__).with_name('run-full-system.py')))
SYNC = VM['sync_and_export_config']
SAVE = VM['save_input_session']


class SessionSave(unittest.TestCase):
    def test_combined_mode_serializes_card_then_config_with_one_stop_barrier(self):
        with tempfile.TemporaryDirectory() as directory:
            calls=[]
            args=SimpleNamespace(input_queue_dir=directory,card_export_on_request=True,config_export_on_request=True)
            def card(*args,**kwargs):calls.append('card')
            with mock.patch.dict(SAVE.__globals__, {
                    'quiesce_card_inputs':lambda *a:calls.append('stop') or 0,
                    'export_card_image':card,
                    'sync_and_export_config':lambda *a:calls.append('config')}):
                result={};SAVE(args,None,None,{},Path(directory),result,'owned-ui-close-request')
            self.assertEqual(calls,['stop','card','config'])
            self.assertTrue(result['card_input_queue_empty_verified'])

    def test_config_failure_preserves_a_separate_successful_card_stage(self):
        with tempfile.TemporaryDirectory() as directory:
            args=SimpleNamespace(input_queue_dir=directory,card_export_on_request=True,config_export_on_request=True)
            result={}
            def card(*args,**kwargs):result['card_image_exported']=True
            with mock.patch.dict(SAVE.__globals__, {
                    'quiesce_card_inputs':lambda *a:0,'export_card_image':card,
                    'sync_and_export_config':mock.Mock(side_effect=TimeoutError('config timeout'))}):
                with self.assertRaises(TimeoutError):
                    SAVE(args,None,None,{},Path(directory),result,'owned-ui-close-request')
            self.assertTrue(result['card_image_exported'])
            self.assertEqual(result['failure_scope'],'configuration-after-card-save')
            self.assertTrue(result['configuration_save_failed'])

    def test_card_failure_does_not_start_config_or_reuse_a_corrupt_window(self):
        with tempfile.TemporaryDirectory() as directory:
            args=SimpleNamespace(input_queue_dir=directory,card_export_on_request=True,config_export_on_request=True)
            config=mock.Mock()
            with mock.patch.dict(SAVE.__globals__, {
                    'quiesce_card_inputs':lambda *a:0,
                    'export_card_image':mock.Mock(side_effect=OSError('bad card export')),
                    'sync_and_export_config':config}):
                with self.assertRaises(OSError):
                    SAVE(args,None,None,{},Path(directory),{},'observation-deadline')
            config.assert_not_called()

    def test_original_zero_receipt_then_export_exactly_once(self):
        with tempfile.TemporaryDirectory() as directory:
            run = mock.Mock(return_value=b'BACKUP_SYNC_BEGIN\nBACKUP_SYNC_END scope=subsystem subsystem=719 result=0\r\n')
            export = mock.Mock(return_value={'verified': True})
            result = {}
            with mock.patch.dict(SYNC.__globals__, {'export_config_pair': export}):
                self.assertTrue(SYNC(run, None, {}, Path(directory), result)['verified'])
            run.assert_called_once_with('/simulation/backup-sync --subsystem 0x2cf', timeout=60)
            export.assert_called_once()
            self.assertTrue(result['config_sync']['verified'])

    def test_missing_wrong_or_repeated_api_receipt_never_exports(self):
        line = b'BACKUP_SYNC_END scope=subsystem subsystem=719 result=0\n'
        for response in (b'', line.replace(b'=0', b'=-1'), line + line,
                         line.replace(b'719', b'718')):
            with self.subTest(response=response), tempfile.TemporaryDirectory() as directory:
                export = mock.Mock()
                with mock.patch.dict(SYNC.__globals__, {'export_config_pair': export}):
                    with self.assertRaises(RuntimeError):
                        SYNC(mock.Mock(return_value=response), None, {}, Path(directory), {})
                export.assert_not_called()

    def test_serial_timeout_is_not_retried_or_followed_by_export(self):
        with tempfile.TemporaryDirectory() as directory:
            run = mock.Mock(side_effect=TimeoutError('no closed nonce'))
            export = mock.Mock()
            with mock.patch.dict(SYNC.__globals__, {'export_config_pair': export}):
                with self.assertRaises(TimeoutError):
                    SYNC(run, None, {}, Path(directory), {})
            run.assert_called_once()
            export.assert_not_called()

    def test_stop_handshake_precedes_config_sync(self):
        with tempfile.TemporaryDirectory() as directory:
            calls = []
            args = SimpleNamespace(input_queue_dir=directory, card_export_on_request=False,
                                   config_export_on_request=True)
            result = {}
            with mock.patch.dict(SAVE.__globals__, {
                    'quiesce_card_inputs': lambda *a: calls.append('stop') or 0,
                    'sync_and_export_config': lambda *a: calls.append('sync-export')}):
                SAVE(args, None, None, {}, Path(directory), result, 'observation-deadline')
            self.assertEqual(calls, ['stop', 'sync-export'])
            self.assertEqual(result['config_export_trigger'], 'observation-deadline')
            self.assertNotIn('card_image_exported', result)

    def test_failed_stop_handshake_never_syncs(self):
        with tempfile.TemporaryDirectory() as directory:
            args = SimpleNamespace(input_queue_dir=directory, card_export_on_request=False,
                                   config_export_on_request=True)
            sync = mock.Mock()
            with mock.patch.dict(SAVE.__globals__, {'quiesce_card_inputs': mock.Mock(side_effect=TimeoutError()),
                                                    'sync_and_export_config': sync}):
                with self.assertRaises(TimeoutError):
                    SAVE(args, None, None, {}, Path(directory), {}, 'owned-ui-close-request')
            sync.assert_not_called()


if __name__ == '__main__':
    unittest.main()
