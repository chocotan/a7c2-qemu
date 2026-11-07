#!/usr/bin/env python3
"""Inject faults at owned-process termination, after the final live monitor."""
import ast
import hashlib
import json
from pathlib import Path
import runpy
import tempfile
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
API = runpy.run_path(str(HERE / 'run-full-system.py'))
finish = API['finish_owned_run']


class Process:
    pid = 601
    returncode = None

    def poll(self):
        return self.returncode

    def wait(self,timeout):
        if self.returncode is None:
            raise TimeoutError('owned process still running')
        return self.returncode


class FinalEvidence(unittest.TestCase):
    def run_case(self, injected=b'', earlier_error=None, stop_error=False, missing=False):
        with tempfile.TemporaryDirectory() as temporary:
            out = Path(temporary)/'runtime/analysis/runs/run-fixture'
            out.mkdir(parents=True)
            log = out / 'console.log'
            log.write_bytes(b'FULLSYSTEM_OBSERVATION_DONE\n')
            result = {'state': 'observation-completed', 'camera_startup_verified': False}
            if earlier_error:
                result.update(state='failed', error=earlier_error)
            process = Process()

            calls=[]
            def qmp_open(path):
                self.assertEqual(path,out/'qmp.sock')
                class Handle:
                    def close(self):calls.append('close')
                def command(name):
                    calls.append(name)
                    self.assertEqual(name,'quit')
                    if stop_error:raise OSError('injected stop failure')
                    with log.open('ab') as stream:stream.write(injected)
                    if missing:log.unlink()
                    process.returncode=0
                    return {}
                return Handle(),Handle(),command

            with patch.dict(finish.__globals__, {'qmp_open': qmp_open}):
                finish(process, result, out)
            self.assertEqual(calls,['quit','close','close'])
            self.assertEqual(result['vm_signals_sent'],[])
            self.assertEqual(result.get('owner_retained',False),stop_error)
            self.assertEqual(result, json.loads((out / 'result.json').read_text()))
            self.assertFalse(result['camera_startup_verified'])
            if result['terminal_evidence_checked']:
                self.assertEqual(result['terminal_console_sha256'],
                                 hashlib.sha256(log.read_bytes()).hexdigest())
            return result

    def test_clean(self):
        result = self.run_case()
        self.assertEqual(result['state'], 'observation-completed')
        self.assertTrue(result['terminal_evidence_checked'])
        self.assertTrue(result['qmp_quit_confirmed'])
        self.assertEqual(result['owned_process_returncode'],0)

    def test_late_ownership_faults(self):
        for kind in ('REMOTE_STATE', 'GUI_MODELS', 'VDF', 'IMAGING', 'AUDIO', 'HDMI', 'VEF', 'PINMEM', 'SCALAR', 'PIN_CONNECT', 'SCALAR_CONNECT'):
            with self.subTest(kind=kind):
                result = self.run_case(('OBS FULL_' + kind + '_FAULT request_free_rc=-88\n').encode())
                self.assertEqual(result['state'], 'failed')
                self.assertTrue(result['terminal_evidence_checked'])
                self.assertIn('ownership fault', result['error'])

    def test_late_native_fatal(self):
        result = self.run_case(b'OBS APPLOG SEQUENCE FATAL ERROR assert at sequence.cpp:99(error:00000011)\n')
        self.assertEqual(result['state'], 'failed')
        self.assertTrue(result['original_model_fatal_observed'])

    def test_late_exception_monitor(self):
        result = self.run_case(b'Entering exception monitor.\r\n')
        self.assertEqual(result['state'], 'failed')

    def test_late_sound_owner_failure(self):
        result = self.run_case(b'FULLSYSTEM_SOUND_OWNER_FAILED\n')
        self.assertEqual(result['state'], 'failed')
        self.assertIn('sound owner', result['error'])

    def test_late_gpio_pad_failure(self):
        result = self.run_case(b'FULLSYSTEM_GPIO_PAD_FAILED\n')
        self.assertEqual(result['state'], 'failed')
        self.assertIn('GPIO pad', result['error'])

    def test_late_loader_observation_failure(self):
        result = self.run_case(b'FULL_LIRO_OBSERVE_FAILURE log-write\n')
        self.assertEqual(result['state'], 'failed')
        self.assertIn('LIRO observation', result['error'])

    def test_late_control_probe_failure(self):
        result = self.run_case(b'FULL_PIN_CONTROL_PROBE_FAILED stage=readback\n')
        self.assertEqual(result['state'], 'failed')
        self.assertIn('control backing probe', result['error'])

    def test_stop_failure(self):
        result = self.run_case(stop_error=True)
        self.assertEqual(result['state'], 'failed')
        self.assertFalse(result['terminal_evidence_checked'])

    def test_nonzero_owner_exit_preserves_failure(self):
        with tempfile.TemporaryDirectory() as temporary:
            out=Path(temporary);(out/'console.log').write_bytes(b'clean-looking console\n')
            process=Process();process.returncode=7
            result={'state':'observation-completed'}
            finish(process,result,out)
            self.assertEqual(result['owned_process_returncode'],7)
            self.assertEqual(result['state'],'failed')
            self.assertTrue(result['terminal_evidence_checked'])
            self.assertNotIn('qmp_quit_attempted',result)
            self.assertEqual(result['vm_signals_sent'],[])

    def test_missing_evidence(self):
        result = self.run_case(missing=True)
        self.assertEqual(result['state'], 'failed')
        self.assertFalse(result['terminal_evidence_checked'])

    def test_prior_failure_is_preserved(self):
        result = self.run_case(b'OBS FULL_VDF_FAULT rc=-88\n', earlier_error='original failure')
        self.assertEqual(result['error'], 'original failure')
        self.assertTrue(result['terminal_errors'])


class DeferredInput(unittest.TestCase):
    def test_original_library_start_waits_for_first_input(self):
        tree=ast.parse((HERE/'run-full-system.py').read_text())
        start=next(node for node in ast.walk(tree) if isinstance(node,ast.FunctionDef) and node.name=='start_input')
        closure=next(node for node in ast.walk(tree) if isinstance(node,ast.FunctionDef) and node.name=='run' and
                     any(isinstance(child,ast.Name) and child.id=='start_input' for child in ast.walk(node)))
        factory=ast.parse('def factory():\n    low_input=None\n    return run\n').body[0]
        factory.body[1:1]=[start,closure]
        namespace={};calls=[];ready=[False]
        class Session:
            def __init__(self,*args):
                if not ready[0]:raise RuntimeError('original UIPC driver not loaded')
                calls.append('create')
            def execute(self,command,timeout):calls.append('input');return b'original delivery'
            def cancel(self):pass
            def check(self):pass
        parser=runpy.run_path(str(HERE/'low-latency-input.py'))['parse_command']
        class Args:low_latency_input='mailbox-v1'
        namespace.update(args=Args(),low_input_api={'parse_command':parser,'LowLatencyInput':Session},
                         out=None,qmp=None,serial_run=lambda command,**kw:calls.append('serial'),result={})
        exec(compile(ast.fix_missing_locations(ast.Module(body=[factory],type_ignores=[])),'actual-input-closure','exec'),namespace)
        run=namespace['factory']()
        run('true');run('/sbin/init2 &')
        self.assertEqual(calls,['serial','serial'])
        ready[0]=True
        for _ in range(2):self.assertEqual(run(API['input_tap_command'](0x1ab)),b'original delivery')
        self.assertEqual(calls,['serial','serial','create','input','input'])
        with self.assertRaises(ValueError):run('/simulation/inject-key unsupported')
        self.assertEqual(calls,['serial','serial','create','input','input'])
        self.assertTrue(namespace['result']['low_latency_input_started'])


class RetainedInput(unittest.TestCase):
    def test_retention_keeps_parent_alive_across_timeout_and_interrupt(self):
        class Retained(Process):
            attempts=0
            def wait(self,timeout):
                self.attempts+=1
                if self.attempts==1:raise API['subprocess'].TimeoutExpired('owned',timeout)
                if self.attempts==2:raise KeyboardInterrupt()
                self.returncode=0;return 0
        with tempfile.TemporaryDirectory() as temporary:
            process=Retained();result={'state':'failed','owner_retained':True,'terminal_evidence_checked':False}
            API['wait_retained_owner'](process,result,Path(temporary))
            self.assertEqual(process.attempts,3)
            self.assertEqual(result['retained_owner_observed_exit'],0)
            self.assertFalse(result['terminal_evidence_checked'])
            self.assertEqual(result['state'],'failed')
            self.assertNotIn('qmp_quit_confirmed',result)

    def test_failed_release_preserves_vm_and_blocks_runtime_reuse(self):
        tree=ast.parse((HERE/'run-full-system.py').read_text())
        main=next(node for node in tree.body if isinstance(node,ast.FunctionDef) and node.name=='main')
        cleanup=next(node for node in ast.walk(main) if isinstance(node,ast.Try) and
                     any(isinstance(child,ast.Name) and child.id=='lcd_safe' for item in node.finalbody for child in ast.walk(item)))
        code=compile(ast.Module(body=cleanup.finalbody,type_ignores=[]),'actual-finally','exec')
        class Unreleased:
            def close(self):raise RuntimeError('original release unconfirmed')
        with tempfile.TemporaryDirectory() as temporary:
            runtime=Path(temporary)/'runtime';out=runtime/'analysis/runs/run-fixture';out.mkdir(parents=True)
            called=[];result={'state':'observation-completed'}
            namespace=dict(low_input=Unreleased(),input_wakeup=None,fatal_probe=None,shutdown_probe=None,
                           stream=None,qsock=None,lcd_producer=None,process=Process(),result=result,out=out,json=json,
                           collect_observer_result=lambda *args:None,finish_owned_run=lambda *args:called.append('quit'),
                           preserve_owned_run=API['preserve_owned_run'])
            exec(code,namespace)
            self.assertEqual(called,[])
            self.assertTrue(result['vm_cleanup_blocked_by_input'])
            self.assertTrue(result['owner_retained'])
            self.assertFalse(result['terminal_evidence_checked'])
            self.assertEqual(json.loads((runtime/'analysis/.owner-retained.json').read_text())['owner_pid'],601)
            locks=runpy.run_path(str(HERE/'runtime-lock.py'))
            with self.assertRaisesRegex(RuntimeError,'owned VM resources are unresolved'):
                locks['open_runtime_lock'](runtime,allow_pending=True)


class FailureContentExport(unittest.TestCase):
    def test_failed_observation_logs_preserve_error_and_bound_reads(self):
        with tempfile.TemporaryDirectory() as temporary:
            out=Path(temporary);calls=[];result={'state':'failed','error':'Original pin timeout'}
            def run(command,timeout):
                calls.append((command,timeout));return b'HOST_FAILURE_LOG_FIXTURE\n'
            API['collect_failed_observation_logs'](run,TimeoutError('Actual CPU format timeout'),result,out)
            self.assertEqual(result['state'],'failed');self.assertEqual(result['error'],'Original pin timeout')
            self.assertEqual((out/'failure-bounded-logs.log').read_bytes(),b'HOST_FAILURE_LOG_FIXTURE\n')
            self.assertIn('4096',calls[0][0]);self.assertIn('8192',calls[0][0]);self.assertNotIn(' -f ',calls[0][0])
            self.assertEqual(calls[0][1],60)

    def test_uart_missing_marker_never_gets_followup_commands(self):
        calls=[]
        API['collect_failed_observation_logs'](lambda *a,**kw:calls.append(a),TimeoutError('串口命令缺少完成标记'),{},None)
        self.assertEqual(calls,[])

    def test_readonly_export_preserves_original_failure(self):
        with tempfile.TemporaryDirectory() as temporary:
            out=Path(temporary);(out/'console.log').write_bytes(b'FULL_SOUND_OWNER_READY source=original\n')
            result={'state':'failed','error':'original pin connection failure'};calls=[]

            def qmp(name,args=None):
                calls.append((name,args))
                return {'running':True} if name=='query-status' else {}

            API['export_sound_memory'](qmp,{'virtual_system_sound':{'physical':0x41d000000,'capacity':0x20000}},out,result)
            self.assertEqual(result['state'],'failed')
            self.assertEqual(result['error'],'original pin connection failure')
            self.assertTrue(result['system_sound_memory_exported'])
            self.assertEqual(calls[-1][0],'cont')

    def test_export_failure_restores_running_and_is_not_success(self):
        with tempfile.TemporaryDirectory() as temporary:
            out=Path(temporary);(out/'console.log').write_bytes(b'FULL_SOUND_OWNER_READY source=original\n')
            result={'state':'failed'};calls=[]

            def qmp(name,args=None):
                calls.append(name)
                if name=='pmemsave':raise OSError('injected readonly export failure')
                return {'running':True} if name=='query-status' else {}

            with self.assertRaises(OSError):
                API['export_sound_memory'](qmp,{'virtual_system_sound':{'physical':0x41d000000,'capacity':0x20000}},out,result)
            self.assertEqual(calls[-1],'cont')
            self.assertFalse(result.get('system_sound_memory_exported'))
            self.assertEqual(result['state'],'failed')


if __name__ == '__main__':
    unittest.main()
