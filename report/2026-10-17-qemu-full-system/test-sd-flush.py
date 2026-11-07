#!/usr/bin/env python3
"""Fault injection for native flush/STOP/CONT protocol; never signal a host process."""
import runpy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

HERE=Path(__file__).resolve().parent
API=runpy.run_path(str(HERE/'sd_flush_barrier.py'))
RUN=runpy.run_path(str(HERE/'run-full-system.py'))


class Protocol(unittest.TestCase):
    def test_quiesce_requires_real_flush_and_observed_stop(self):
        replies=[b'SD_REQUEST_seq=12\n',b'SD_FSYS_FLUSH seq=12 pid=453 drive=65 rc=0\n',b'SD_STATE=T\n']
        def serial(command,**options):return replies.pop(0)
        state=API['quiesce'](serial,12)
        self.assertTrue(state['owner_stopped'])
        self.assertEqual(state['original_Fsys_FlushVolume_rc'],0)

    def test_original_flush_error_is_rejected(self):
        replies=[b'SD_REQUEST_seq=12\n',b'SD_FSYS_FLUSH seq=12 pid=453 drive=65 rc=-9\n']
        with self.assertRaises(API['BarrierError']):
            API['quiesce'](lambda *args,**options:replies.pop(0),12)

    def test_cancellation_is_armed_before_reply_lookup(self):
        seen=[]
        replies=[b'SD_CANCEL_seq=12\n',b'SD_FSYS_FLUSH seq=12 pid=453 drive=65 rc=0\n',b'SD_RECOVERY=RESUMED\n']
        def serial(command,**options):
            self.assertTrue(options['cleanup'])
            self.assertIsNone(options['timeout'])
            seen.append(command)
            return replies.pop(0)
        self.assertTrue(API['cancel_resume'](serial,12)['resumed'])
        self.assertIn('.cancel.new',seen[0])
        self.assertIn('.reply',seen[1])
        self.assertIn('kill -CONT 453',seen[2])

    def test_missing_reply_is_cancelled_without_guessing_owner(self):
        replies=[b'SD_CANCEL_seq=12\n',b'SD_FSYS_ABSENT_seq=12\n']
        state=API['cancel_resume'](lambda *args,**options:replies.pop(0),12)
        self.assertFalse(state['resumed'])
        self.assertEqual(state['status'],'cancel_armed_no_reply')

    def test_duplicate_and_conflicting_replies_are_rejected(self):
        for raw in (b'SD_CANCEL_seq=12\nSD_CANCEL_seq=12\n',
                    b'SD_CANCEL_seq=13\n'):
            with self.subTest(raw=raw),self.assertRaises(API['BarrierError']):
                API['cancel_resume'](lambda *args,**options:raw,12)


class ExportRecovery(unittest.TestCase):
    def test_recovery_runs_even_if_quiesce_or_export_fails(self):
        export=RUN['export_card_image']
        for phase in ('quiesce','snapshot'):
            calls=[]
            def quiesce(serial,seq,**options):
                calls.append('quiesce')
                if phase=='quiesce':raise RuntimeError('quiesce failed')
                return {'owner_stopped':True}
            def cancel(serial,seq):calls.append('cancel');return {'ok':True}
            def snapshot(*args,**kwargs):calls.append('snapshot');raise RuntimeError('snapshot failed')
            fake={'quiesce':quiesce,'cancel_resume':cancel}
            with tempfile.TemporaryDirectory() as directory:
                with patch('runpy.run_path',return_value=fake),patch.dict(export.__globals__,{'export_card_snapshot':snapshot}):
                    result={}
                    with self.assertRaises(RuntimeError):
                        export(None,None,{},Path(directory),result,barrier_serial=object())
                    self.assertEqual(calls[-1],'cancel')
                    self.assertFalse(result['card_image_exported'])

    def test_cleanup_failure_cannot_publish_success(self):
        export=RUN['export_card_image']
        fake={'quiesce':lambda *a,**k:{'owner_stopped':True},
              'cancel_resume':lambda *a,**k:(_ for _ in ()).throw(RuntimeError('CONT failed'))}
        def snapshot(run,qmp,manifest,out,result,image,size):
            (out/'card-image.bin').write_bytes(b'evidence')
            result['card_image_exported']=True
        with tempfile.TemporaryDirectory() as directory:
            out=Path(directory);result={}
            with patch('runpy.run_path',return_value=fake),patch.dict(export.__globals__,{'export_card_snapshot':snapshot}):
                with self.assertRaisesRegex(RuntimeError,'CONT failed'):
                    export(None,None,{},out,result,barrier_serial=object())
            self.assertFalse(result['card_image_exported'])
            self.assertFalse((out/'card-image.bin').exists())
            self.assertEqual((out/'card-image.bin.unrecovered').read_bytes(),b'evidence')


if __name__=='__main__':unittest.main()
