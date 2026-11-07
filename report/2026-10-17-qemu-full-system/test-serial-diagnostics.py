#!/usr/bin/env python3
from pathlib import Path
import runpy
import unittest
from unittest.mock import patch

COLLECT=runpy.run_path(str(Path(__file__).with_name('run-full-system.py')))['collect_serial_diagnostics']


class SerialDiagnostics(unittest.TestCase):
    def test_all_steps_keep_one_deadline_and_bounded_contents(self):
        calls=[];result={}
        def run(command,timeout):
            calls.append((command,timeout))
            return b'LOG_SNAPSHOT_INIT2_RC=0\nLOG_SNAPSHOT_IM_RC=0\nLOG_SNAPSHOT_OBSERVER_RC=0\nFULLSYSTEM_OBSERVATION_DONE\n'
        with patch.object(COLLECT.__globals__['time'],'monotonic',side_effect=range(8)):
            COLLECT(run,result)
        self.assertEqual([value for command,value in calls],[59,58,57,56,55,54,53])
        self.assertEqual([e['step'] for e in result['serial_diagnostic_steps']],['modules','init2-log','processes','mounts','im-log','observer-log','done'])
        self.assertTrue(all(e['completed'] for e in result['serial_diagnostic_steps']))
        self.assertEqual(result['serial_diagnostic_budget_seconds'],60)
        self.assertEqual([e['remaining_seconds_before'] for e in result['serial_diagnostic_steps']],[59,58,57,56,55,54,53])
        self.assertEqual(calls[2][0],'ps');self.assertEqual(calls[3][0],'cat /proc/mounts')
        self.assertEqual(result['serial_diagnostic_log_suffix_bytes'],{'init2.log':4096,'im.log':4096,'menu-load.log':8192})

    def test_missing_process_rc_stops_before_mounts(self):
        calls=[];result={}
        def run(command,timeout):
            calls.append(command)
            if command=='ps':raise TimeoutError('missing completion sentinel')
            return b'LOG_SNAPSHOT_INIT2_RC=0\n'
        with self.assertRaisesRegex(RuntimeError,'step processes failed'):
            COLLECT(run,result)
        self.assertEqual(len(calls),3);self.assertFalse(result['serial_diagnostic_steps'][-1]['completed'])

    def test_failed_reader_cannot_be_hidden_by_echo(self):
        result={}
        with self.assertRaisesRegex(RuntimeError,'step init2-log failed'):
            COLLECT(lambda *args,**kwargs:b'LOG_SNAPSHOT_INIT2_RC=1\n',result)
        self.assertEqual(len(result['serial_diagnostic_steps']),2)

    def test_optional_im_log_absence_is_recorded_not_fabricated(self):
        result={}
        def run(command,timeout):
            if '/log/qemu/im.log' in command:
                return b'FULLSYSTEM_LOG_SNAPSHOT_MISSING path=/log/qemu/im.log errno=2\r\nLOG_SNAPSHOT_IM_RC=3\r\n'
            return b'LOG_SNAPSHOT_INIT2_RC=0\nLOG_SNAPSHOT_OBSERVER_RC=0\nFULLSYSTEM_OBSERVATION_DONE\n'
        COLLECT(run,result)
        im=result['serial_diagnostic_steps'][4]
        self.assertTrue(im['completed']);self.assertEqual((im['availability'],im['reader_rc'],im['errno']),('not-created',3,2))
        self.assertEqual(len(result['serial_diagnostic_steps']),7)

    def test_optional_log_other_errors_or_missing_rc_still_fail(self):
        for failure in (b'FULLSYSTEM_LOG_SNAPSHOT_MISSING path=/log/qemu/im.log errno=13\nLOG_SNAPSHOT_IM_RC=3\n',
                        b'FULLSYSTEM_LOG_SNAPSHOT_MISSING path=/log/qemu/im.log errno=2\n',
                        b'LOG_SNAPSHOT_IM_RC=6\n'):
            result={}
            def run(command,timeout):
                if '/log/qemu/im.log' in command:return failure
                return b'LOG_SNAPSHOT_INIT2_RC=0\n'
            with self.assertRaisesRegex(RuntimeError,'step im-log failed'):COLLECT(run,result)
            self.assertFalse(result['serial_diagnostic_steps'][-1]['completed'])


if __name__=='__main__':unittest.main()
