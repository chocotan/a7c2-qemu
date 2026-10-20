#!/usr/bin/env python3
"""Host/mock tests only. No QEMU, builds, hardware or shared flock."""
import base64
import http.client
import io
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from menu_control import BASE, Server, VM, terminate_owned
from menu_live import FirmwareFault, FirmwareMonitor, serial_command, snapshot_message,receive_message,send_message


def wait_for(predicate, timeout=8):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(.02)
    raise AssertionError('condition timed out')


def mock_vm(mode='normal'):
    return VM([sys.executable, str(BASE / 'mock_menu_vm.py'), mode])


class ControlTests(unittest.TestCase):
    def setUp(self):
        self.vm = mock_vm()
        self.server = Server(self.vm)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.vm.close()
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()

    def request(self, path='/api/state', method='GET', payload=None, headers=None):
        conn = http.client.HTTPConnection('127.0.0.1', self.server.server_port, timeout=3)
        base = {'X-Session-Token': self.server.token, 'Origin': self.server.origin,
                'Content-Type': 'application/json'}
        base.update(headers or {})
        base = {key: value for key, value in base.items() if value is not None}
        body = json.dumps(payload) if payload is not None else None
        conn.request(method, path, body, base)
        response = conn.getresponse()
        result = response.status, response.read(), dict(response.getheaders())
        conn.close()
        return result

    def test_auth_and_fixed_routes(self):
        self.assertEqual(self.request()[0], 200)
        for headers in ({'X-Session-Token': 'wrong'}, {'Origin':'http://evil.invalid'},
                        {'Origin':'null'}, {'Host':'evil.invalid'}, {'Sec-Fetch-Site':'cross-site'}):
            self.assertEqual(self.request(headers=headers)[0], 403)
            self.assertEqual(self.request('/api/start', 'POST', {}, headers)[0], 403)
        for path in ('/api/shell', '/../../etc/passwd', '/api/state?file=/etc/passwd'):
            self.assertEqual(self.request(path)[0], 404)
        self.assertEqual(self.request('/api/start', 'POST', {'shell':'true'})[0], 400)
        self.assertEqual(self.request('/api/start', 'POST', {}, {'Content-Length':'257'})[0], 413)
        self.assertEqual(self.request('/api/start', 'POST', {}, {'Content-Type':'text/plain'})[0], 415)
        self.assertEqual(self.request('/api/start', 'POST', {}, {'Origin':None})[0], 403)
        self.assertEqual(self.request(headers={'X-Session-Token':'é'})[0], 403)
        self.assertEqual(self.request('/api/key', 'POST', {'key':'UP'})[0], 400)
        self.assertEqual(self.request('/api/key', 'POST', {'key':[]})[0], 400)
        self.assertEqual(self.request('/api/save')[0], 409)

    def test_state_queue_snapshot_and_stop(self):
        self.assertEqual(self.vm.status()['state'], 'disconnected')
        self.assertEqual(self.request('/api/start', 'POST', {})[0], 202)
        wait_for(lambda: self.vm.status()['snapshot'])
        self.assertEqual(self.vm.status()['state'], 'running')
        self.assertFalse(self.vm.status()['stale'])
        self.assertEqual(self.request('/api/start', 'POST', {})[0], 400)
        self.assertEqual(self.request('/api/key', 'POST', {'key':'MENU'})[0], 202)
        self.assertEqual(self.request('/api/snapshot', 'POST', {})[0], 202)
        wait_for(lambda: self.vm.status()['snapshot']['number'] == 2)
        events = self.vm.status()['events']
        self.assertEqual(events[1]['kind'], 'input')
        self.assertEqual(events[1]['message'], 'MENU：输入已提交')
        status, png, headers = self.request('/api/save')
        self.assertEqual(status, 200)
        self.assertTrue(png.startswith(b'\x89PNG'))
        self.assertEqual(headers['X-Snapshot-Number'], '2')
        self.assertEqual(self.request('/api/stop', 'POST', {})[0], 202)
        wait_for(lambda: self.vm.status()['state'] == 'exited')
        self.assertTrue(self.vm.status()['stale'])
        self.assertEqual(self.vm.png, png)
        self.assertEqual(self.request('/api/key', 'POST', {'key':'MENU'})[0], 400)

    def test_position_roundtrip_keeps_label_and_input_event(self):
        self.vm.start();wait_for(lambda:self.vm.status()['snapshot'])
        self.vm.enqueue({'action':'position','key':'MODE','position':'A'})
        wait_for(lambda:any(event['kind']=='input' and 'MODE A' in event['message'] for event in self.vm.status()['events']))
        self.assertEqual(self.vm.status()['state'],'running')

    def test_bad_reply_and_exit_do_not_succeed(self):
        for mode in ('bad-reply', 'exit'):
            vm = mock_vm(mode)
            try:
                vm.start()
                wait_for(lambda: vm.status()['state'] == 'error')
                self.assertIsNone(vm.status()['snapshot'])
                self.assertTrue(vm.status()['error'])
            finally:
                vm.close()

    def test_validation_failure_retains_old_frame(self):
        self.vm.start()
        wait_for(lambda: self.vm.status()['snapshot'])
        old = self.vm.png
        self.vm.stop()
        self.vm.thread.join(8)
        self.vm.command[-1] = 'corrupt'
        self.vm.start()
        wait_for(lambda: bool(self.vm.status()['error']))
        self.assertEqual(self.vm.png, old)
        self.assertTrue(self.vm.status()['stale'])
        self.assertIn('校验失败', self.vm.status()['error'])

    def test_stop_cancels_startup_or_inflight(self):
        for mode in ('startup-hang', 'hang'):
            vm = mock_vm(mode)
            vm.start()
            if mode == 'hang':
                wait_for(lambda: vm.status()['busy'] == 'snapshot')
            vm.stop()
            vm.thread.join(8)
            self.assertFalse(vm.thread.is_alive())
            self.assertEqual(vm.status()['state'], 'exited')

    def test_firmware_crash_between_commands_and_inflight_stops_input(self):
        (BASE / 'menu-runs').mkdir(exist_ok=True)
        for mode in ('idle-crash', 'inflight-crash'):
            with tempfile.TemporaryDirectory(dir=BASE / 'menu-runs') as run:
                (Path(run)/'runtime-manifest.json').write_text('{}')
                vm = VM([sys.executable, str(BASE / 'mock_menu_vm.py'), mode, run], native_display='none')
                vm.mock = False  # Exercise the real console monitor, without starting a VM.
                try:
                    vm.start()
                    wait_for(lambda: vm.status()['state'] == 'running')
                    vm.enqueue({'action': 'key', 'key': 'ENTER'})
                    if mode == 'inflight-crash':
                        for _ in range(6):
                            vm.enqueue({'action': 'key', 'key': 'DOWN'})
                    wait_for(lambda: vm.status()['state'] == 'error', timeout=3)
                    vm.thread.join(8)
                    self.assertFalse(vm.thread.is_alive())
                    self.assertIn('固件发生异常', vm.status()['error'])
                    self.assertEqual(vm.status()['pending'], 0)
                    with self.assertRaisesRegex(ValueError, '尚未运行'):
                        vm.enqueue({'action': 'key', 'key': 'LEFT'})
                finally:
                    vm.close()


class StorageShutdownTests(unittest.TestCase):
    def test_unexpected_exit_during_save_is_not_a_successful_close(self):
        (BASE/'menu-runs').mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=BASE/'menu-runs') as directory:
            run=Path(directory);(run/'runtime-manifest.json').write_text('{}');(run/'console.log').write_text('')
            vm=VM([sys.executable,str(BASE/'mock_menu_vm.py'),'sd-exit',str(run)],native_display='none',natural_boot=True)
            vm.mock=False
            try:
                vm.start();wait_for(lambda:vm.state=='running')
                with self.assertRaisesRegex(RuntimeError,'未完成'):vm.close()
                self.assertEqual(vm.state,'error');self.assertIsNone(vm.sd_export)
            finally:vm.natural_boot=False;vm.close()

    def test_fault_during_export_waits_for_recovery_and_preserves_faulted_vm(self):
        (BASE/'menu-runs').mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=BASE/'menu-runs') as directory:
            run=Path(directory);(run/'runtime-manifest.json').write_text('{}');(run/'console.log').write_text('')
            vm=VM([sys.executable,str(BASE/'mock_menu_vm.py'),'sd-fault',str(run)],native_display='none',natural_boot=True)
            vm.mock=False
            try:
                with patch('menu_control.receive_message',wraps=receive_message) as received:
                    vm.start();wait_for(lambda:vm.state=='running');vm.stop()
                    wait_for(lambda:(run/'fault-written').exists())
                    time.sleep(.3)
                    self.assertTrue(vm.thread.is_alive());self.assertIsNone(vm.owned_process.poll())
                    self.assertFalse((run/'recovery-done').exists())
                    self.assertIsNone(received.call_args_list[1].kwargs['cancelled'])
                    (run/'allow-recovery-reply').write_text('1')
                    wait_for(lambda:vm.state=='faulted')
                    self.assertTrue((run/'recovery-done').exists());self.assertTrue(vm.shutdown_done.is_set())
                    self.assertIsNone(vm.owned_process.poll());self.assertTrue(vm.status()['can_stop'])
                    with self.assertRaises(ValueError):vm.enqueue({'action':'key','key':'UP'})
                    with self.assertRaisesRegex(RuntimeError,'SD保存失败'):vm.close()
                    self.assertEqual(vm.state,'faulted');self.assertIsNone(vm.owned_process.poll())
            finally:
                (run/'allow-recovery-reply').write_text('1');vm.natural_boot=False;vm.close()

    def test_close_reports_cleanup_failure_and_retries_only_owned_process(self):
        (BASE/'menu-runs').mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=BASE/'menu-runs') as directory:
            run=Path(directory);(run/'runtime-manifest.json').write_text('{}');(run/'console.log').write_text('')
            vm=VM([sys.executable,str(BASE/'mock_menu_vm.py'),'sd-cleanup-hang',str(run)],native_display='none',natural_boot=True)
            vm.mock=False
            try:
                vm.start();wait_for(lambda:vm.state=='running')
                with patch('menu_control.terminate_owned',side_effect=OSError('injected cleanup failure')):
                    with self.assertRaisesRegex(RuntimeError,'清理失败'):vm.close()
                    self.assertEqual(vm.state,'error');self.assertIsNone(vm.owned_process.poll())
                    self.assertFalse(vm.status()['can_start'])
                    with self.assertRaisesRegex(ValueError,'上一VM'):vm.start()
                    with self.assertRaisesRegex(RuntimeError,'仍失败'):vm.close()
                vm.close();self.assertEqual(vm.state,'exited');self.assertIsNone(vm.owned_process)
            finally:
                vm.natural_boot=False;vm.close()

    def test_save_success_stops_and_failure_preserves_vm(self):
        (BASE/'menu-runs').mkdir(exist_ok=True)
        for mode in ('sd-ok','sd-fail'):
            with self.subTest(mode=mode),tempfile.TemporaryDirectory(dir=BASE/'menu-runs') as directory:
                run=Path(directory);(run/'runtime-manifest.json').write_text('{}');(run/'console.log').write_text('')
                vm=VM([sys.executable,str(BASE/'mock_menu_vm.py'),mode,str(run)],native_display='none',natural_boot=True)
                vm.mock=False
                try:
                    with patch('menu_control.receive_message',wraps=receive_message) as received:
                        vm.start();wait_for(lambda:vm.status()['state']=='running')
                        if mode=='sd-ok':
                            vm.close()
                            self.assertEqual(vm.status()['state'],'exited')
                            self.assertEqual(vm.card_seed,run/'SD/card.img')
                            self.assertFalse(vm.thread.is_alive())
                        else:
                            with self.assertRaisesRegex(RuntimeError,'SD保存失败'):vm.close()
                            self.assertEqual(vm.status()['state'],'running')
                            self.assertTrue(vm.thread.is_alive());self.assertFalse(vm.cancel.is_set())
                        self.assertIsNone(received.call_args_list[1].kwargs['timeout'])
                finally:
                    vm.natural_boot=False;vm.close()

    def test_full_queue_does_not_partially_start_shutdown(self):
        vm=VM(natural_boot=True);vm.state='running'
        for _ in range(vm.commands.maxsize):vm.commands.put_nowait({'action':'snapshot'})
        with self.assertRaisesRegex(ValueError,'队列已满'):vm.stop()
        self.assertEqual(vm.state,'running');self.assertFalse(vm.cancel.is_set())


class TransportTests(unittest.TestCase):
    def test_snapshot_io_failure_keeps_storage_session_alive(self):
        import socket
        from menu_live import run_live
        class Process:
            alive=True;returncode=0
            def poll(self):return None if self.alive else 0
        class Monitor:
            def check(self):pass
        proc=Process();left,right=socket.socketpair();descriptor=right.detach();errors=[]
        def capture():raise OSError('snapshot ENOSPC')
        def server():
            try:run_live(proc,Path('/unused'),descriptor,display_capture=capture,sd_export=lambda:{'ok':True})
            except Exception as error:errors.append(error)
        with patch('menu_live.FirmwareMonitor',return_value=Monitor()),patch('menu_live.serial_command',return_value=b'normal RC'):
            thread=threading.Thread(target=server);thread.start()
            try:
                self.assertEqual(receive_message(left)['type'],'ready')
                send_message(left,{'action':'snapshot'});self.assertIn('ENOSPC',receive_message(left)['error'])
                self.assertTrue(thread.is_alive())
                send_message(left,{'action':'export_sd'});self.assertTrue(receive_message(left)['ok'])
            finally:
                proc.alive=False;thread.join(timeout=3);left.close()
            self.assertFalse(thread.is_alive());self.assertEqual(errors,[])

    def test_storage_session_quarantines_fault_without_losing_export_channel(self):
        import socket
        from menu_live import run_live
        fault=threading.Event();done=threading.Event();errors=[];effects=[];exports=[]
        class Monitor:
            def check(self):
                if fault.is_set():raise FirmwareFault('injected AP fault')
        class Process:
            alive=True
            returncode=0
            def poll(self):return None if self.alive else 0
        proc=Process();left,right=socket.socketpair();descriptor=right.detach()
        def serial(*args,**kwargs):
            Monitor().check();effects.append(args[2]);return b'normal serial RC'
        def export():
            exports.append(1)
            if len(exports)==3:raise OSError('injected final report ENOSPC')
            fault.set();done.set();return {'ok':True,'flush_lifecycle':{'ok':True,'status':'resumed'}}
        def server():
            try:run_live(proc,Path('/unused'),descriptor,sd_export=export)
            except Exception as error:errors.append(error)
        with patch('menu_live.FirmwareMonitor',return_value=Monitor()),patch('menu_live.serial_command',side_effect=serial):
            thread=threading.Thread(target=server);thread.start()
            try:
                self.assertEqual(receive_message(left)['type'],'ready')
                send_message(left,{'action':'export_sd'});reply=receive_message(left)
                self.assertTrue(reply['ok']);self.assertTrue(done.is_set());self.assertTrue(thread.is_alive())
                send_message(left,{'action':'key','key':'UP'})
                self.assertIn('injected AP fault',receive_message(left)['error'])
                self.assertEqual(effects,['true'])
                send_message(left,{'action':'export_sd'});self.assertTrue(receive_message(left)['ok'])
                send_message(left,{'action':'export_sd'});self.assertIn('ENOSPC',receive_message(left)['error'])
                self.assertTrue(thread.is_alive())
                send_message(left,{'action':'export_sd'});self.assertTrue(receive_message(left)['ok'])
            finally:
                proc.alive=False;thread.join(timeout=3);left.close()
            self.assertFalse(thread.is_alive());self.assertEqual(errors,[])

    def test_no_deadline_receive_still_accepts_data_and_cancellation(self):
        import socket
        left,right=socket.socketpair()
        with left,right:
            with self.assertRaisesRegex(RuntimeError,'已取消'):
                receive_message(left,timeout=None,cancelled=lambda:True)
            send_message(right,{'type':'slow-export-completed'})
            self.assertEqual(receive_message(left,timeout=None),{'type':'slow-export-completed'})

    def test_trusted_cleanup_runs_after_fault_without_deadline(self):
        with tempfile.TemporaryDirectory() as directory:
            console=Path(directory)/'console.log';console.write_bytes(b'Entering exception monitor.\nException> ')
            class Writer:
                def write(self,data):
                    marker=re.search(rb'MENU_DIAG_COMMAND_DONE_[a-f0-9]+',data)[0]
                    with console.open('ab') as output:output.write(b'\n'+marker+b':0\n')
                def flush(self):pass
            class Process:
                stdin=Writer()
                def poll(self):return None
            self.assertIn(b':0',serial_command(Process(),console,'true',timeout=None,allow_faulted_cleanup=True))

    def test_existing_exception_prevents_any_serial_write(self):
        from unittest.mock import Mock
        with tempfile.TemporaryDirectory() as tmp:
            console = Path(tmp) / 'console.log'
            console.write_bytes(b'command succeeded\nEntering exception monitor.\nException> ')
            process = Mock()
            with self.assertRaises(FirmwareFault):
                serial_command(process, console, 'true')
            process.stdin.write.assert_not_called()

    def test_monitor_handles_split_marker_and_log_truncation(self):
        with tempfile.TemporaryDirectory() as tmp:
            console = Path(tmp) / 'console.log'
            console.write_bytes(b'normal startup\n' * 100)
            monitor = FirmwareMonitor(console)
            monitor.check()
            console.write_bytes(b'new log\r\nEntering except')
            monitor.check()
            with console.open('ab') as output:
                output.write(b'ion monitor.\r\n')
            with self.assertRaises(FirmwareFault):
                monitor.check()
            with self.assertRaises(FirmwareFault):
                monitor.check()

    def test_cleanup_only_owns_created_group(self):
        owned = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'], start_new_session=True)
        unrelated = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'], start_new_session=True)
        try:
            terminate_owned(owned)
            self.assertIsNotNone(owned.poll())
            self.assertIsNone(unrelated.poll())
        finally:
            terminate_owned(unrelated)

    def test_sentinel_ignores_prompt_echo_and_old_markers(self):
        with tempfile.TemporaryDirectory() as tmp:
            console = Path(tmp) / 'console.log'
            console.write_bytes(b'old data\nMENU_DIAG_COMMAND_DONE_old:0\n')
            class Writer:
                status = b'0'
                def write(self, data):
                    marker = re.search(rb'MENU_DIAG_COMMAND_DONE_[a-f0-9]+', data)[0]
                    with console.open('ab') as output:
                        output.write(b'\n/ # ' + data + b'\n/ # \nMENU_DIAG_COMMAND_DONE_old:0\n')
                    def complete():
                        with console.open('ab') as output:
                            output.write(b'\n' + marker + b':' + self.status + b'\n')
                    threading.Timer(.15, complete).start()
                def flush(self):
                    pass
            class Proc:
                stdin = Writer()
                def poll(self):
                    return None
            start = time.monotonic()
            serial_command(Proc(), console, 'true', timeout=2)
            self.assertGreaterEqual(time.monotonic() - start, .14)
            Writer.status = b'7'
            with self.assertRaisesRegex(RuntimeError, '返回码 7'):
                serial_command(Proc(), console, 'false', timeout=2)
            with patch.object(Writer, 'write', lambda self, data: None):
                with self.assertRaises(TimeoutError):
                    serial_command(Proc(), console, 'true', timeout=.1)

    def test_container_validation_is_required(self):
        valid = (BASE / 'fixtures/headless-osd.b64').read_bytes()
        message = snapshot_message(valid)
        self.assertEqual(message['info']['sequence'], 2)
        with self.assertRaises(ValueError):
            snapshot_message(valid.replace(b'HEADLESS_OSD_END', b'BROKEN'))
        lines = valid.splitlines()
        start, end = lines.index(b'HEADLESS_OSD_BEGIN'), lines.index(b'HEADLESS_OSD_END')
        raw = bytearray(base64.b64decode(b''.join(lines[start + 1:end])))
        raw[-1] ^= 1
        with self.assertRaises(ValueError):
            snapshot_message(b'HEADLESS_OSD_BEGIN\n' + base64.b64encode(raw) + b'\nHEADLESS_OSD_END\n')


if __name__ == '__main__':
    unittest.main(verbosity=2)
