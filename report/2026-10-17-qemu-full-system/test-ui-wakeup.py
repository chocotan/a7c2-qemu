#!/usr/bin/env python3
import ast
import copy
from pathlib import Path
import os
import runpy
import tempfile
import threading
import time
import types
import unittest
from unittest import mock

HERE=Path(__file__).resolve().parent
API=runpy.run_path(str(HERE/'ui-wakeup.py'))
UiWakeup=API['UiWakeup']
TREE=ast.parse((HERE/'run-full-system.py').read_text())


class WakeupTest(unittest.TestCase):
    def setUp(self):
        self.temporary=tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.directory=Path(self.temporary.name)
        self.wakeup=UiWakeup(self.directory)
        self.addCleanup(self.wakeup.close)

    def test_atomic_publication_interrupts_select(self):
        def publish():
            path=self.directory/'one.tmp';path.write_text('original tap')
            path.replace(path.with_suffix('.cmd'))
        timer=threading.Timer(.025,publish)
        timer.start();self.addCleanup(timer.join)
        self.assertEqual(self.wakeup.wait(time.monotonic()+1),'input')
        self.assertEqual((self.directory/'one.cmd').read_text(),'original tap')

    def test_preexisting_requests_and_leftover_batch_do_not_lose_wakeup(self):
        for index in range(5):(self.directory/f'{index:02}.cmd').write_text(str(index))
        with mock.patch.object(API['select'],'select') as select:
            self.assertEqual(self.wakeup.wait(),'input')
            for index in range(4):(self.directory/f'{index:02}.cmd').unlink()
            self.assertEqual(self.wakeup.wait(),'input')
            select.assert_not_called()

    def test_unrelated_output_does_not_end_the_display_wait(self):
        timer=threading.Timer(.015,lambda:(self.directory/'one.out').write_text('ACK'))
        timer.start();self.addCleanup(timer.join)
        started=time.monotonic()
        self.assertEqual(self.wakeup.wait(started+.060),'deadline')
        self.assertGreaterEqual(time.monotonic()-started,.050)

    def test_control_marker_wakes_once_without_persistent_busy_poll(self):
        (self.directory/'save-card-and-exit.request').write_bytes(b'A7C2_SAVE_CARD_AND_EXIT_V1\n')
        self.assertEqual(self.wakeup.wait(),'control')
        with mock.patch.object(API['select'],'select',return_value=([],[],[])) as select:
            self.assertEqual(self.wakeup.wait(),'deadline')
            select.assert_called_once()

    def test_replaced_directory_fails_closed(self):
        self.directory.rename(self.directory.with_name(self.directory.name+'-moved'))
        moved=self.directory.with_name(self.directory.name+'-moved')
        self.addCleanup(moved.rmdir)
        self.directory.mkdir()
        with self.assertRaisesRegex(RuntimeError,'replaced'):
            self.wakeup.wait()

    def test_symlink_input_directory_is_refused(self):
        link=self.directory/'linked';link.symlink_to(self.directory,target_is_directory=True)
        with self.assertRaises(OSError):UiWakeup(link)

    def test_foreign_owner_is_refused(self):
        with mock.patch.object(API['os'],'geteuid',return_value=os.geteuid()+1):
            with self.assertRaisesRegex(ValueError,'belong'):UiWakeup(self.directory)

    def test_no_directory_uses_next_deadline_and_200ms_ceiling(self):
        wakeup=UiWakeup()
        with mock.patch.object(API['time'],'monotonic',return_value=10.0), \
             mock.patch.object(API['select'],'select',return_value=([],[],[])) as select:
            self.assertEqual(wakeup.wait(10.025),'deadline')
            self.assertAlmostEqual(select.call_args.args[3],.025)
            wakeup.wait(11)
            self.assertAlmostEqual(select.call_args.args[3],.2)
        self.assertIsNone(wakeup.fd)

    def test_close_releases_both_descriptors(self):
        descriptors=(self.wakeup.fd,self.wakeup.directory_fd)
        self.wakeup.close();self.wakeup.close()
        for fd in descriptors:
            with self.assertRaises(OSError):os.fstat(fd)

    def test_queue_overflow_rescans_pending_files(self):
        (self.directory/'one.cmd').write_text('same request')
        overflow=UiWakeup.event.pack(-1,0x4000,0,0)
        with mock.patch.object(API['os'],'read',side_effect=[overflow,BlockingIOError()]):
            self.assertEqual(self.wakeup.wait(),'input')


class SchedulingTest(unittest.TestCase):
    def setUp(self):
        self.temporary=tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.directory=Path(self.temporary.name)
        self.events=[]
        self.saving=False
        self.environment=dict(Path=Path,time=time,until=time.monotonic()+10,
            args=types.SimpleNamespace(input_queue_dir=str(self.directory),live_frame_seconds=.4),
            save_requested=lambda:self.saving,
            capture_live_frame=lambda **kw:self.events.append(('frame',kw)),
            save_input_session=lambda *a:self.events.append(('save',)),
            qmp=None,manifest=None,out=self.directory,result={})
        def run(command,timeout):
            self.events.append(('input',command,timeout))
            return b'original nonce and send result=0'
        self.environment['run']=run
        node=next(n for n in ast.walk(TREE) if isinstance(n,ast.If)
            and ast.unparse(n.test)=='args.input_queue_dir'
            and any(isinstance(child,ast.For) and ast.unparse(child.target)=='request' for child in n.body))
        loop=ast.For(target=ast.Name(id='_fixture',ctx=ast.Store()),
            iter=ast.List(elts=[ast.Constant(0)],ctx=ast.Load()),body=[copy.deepcopy(node)],orelse=[])
        self.code=compile(ast.fix_missing_locations(ast.Module(body=[loop],type_ignores=[])),
                          '<actual input queue block>','exec')

    def requests(self,count):
        for index in range(count):(self.directory/f'{index:02}.cmd').write_text(f'original-{index}')

    def test_four_batch_keeps_order_ack_and_frame_between_each_input(self):
        self.requests(5)
        exec(self.code,self.environment)
        self.assertEqual(self.events,[entry for i in range(4) for entry in
            [('input',f'original-{i}',30),('frame',{'force':True})]])
        self.assertEqual([p.name for p in self.directory.glob('*.cmd')],['04.cmd'])
        for i in range(4):
            self.assertEqual((self.directory/f'{i:02}.out').read_bytes(),b'original nonce and send result=0')

    def test_async_frame_followup_has_one_bounded_deadline_after_ack(self):
        self.requests(1)
        started=time.monotonic()
        exec(self.code,self.environment)
        self.assertGreaterEqual(self.environment['input_frame_due'],started+.1)
        self.assertLessEqual(self.environment['input_frame_due'],time.monotonic()+.1)

    def test_save_arriving_during_command_preempts_next_frame_and_command(self):
        self.requests(4)
        def run(command,timeout):
            self.events.append(('input',command))
            self.saving=True
            return b'original release completed'
        self.environment['run']=run
        exec(self.code,self.environment)
        self.assertEqual(self.events,[('input','original-0'),('save',)])
        self.assertEqual(len(list(self.directory.glob('*.cmd'))),3)
        self.assertEqual((self.directory/'00.out').read_bytes(),b'original release completed')

    def test_timeout_keeps_original_failure_and_never_runs_next_request(self):
        self.requests(2)
        def run(command,timeout):raise TimeoutError('serial owner unknown')
        self.environment['run']=run
        with self.assertRaisesRegex(TimeoutError,'owner unknown'):exec(self.code,self.environment)
        self.assertEqual((self.directory/'00.out').read_text(),'serial owner unknown')
        self.assertTrue((self.directory/'01.cmd').is_file())
        self.assertEqual(self.events,[])

    def test_persistent_request_read_fault_does_not_spin(self):
        self.requests(1)
        with mock.patch.object(Path,'read_text',side_effect=PermissionError('unreadable')):
            with self.assertRaises(PermissionError):exec(self.code,self.environment)
        self.assertEqual(self.events,[])

    def test_observation_deadline_preempts_next_request(self):
        self.requests(1)
        self.environment['until']=0
        exec(self.code,self.environment)
        self.assertEqual(self.events,[])
        self.assertTrue((self.directory/'00.cmd').is_file())

    def test_early_post_input_frame_does_not_postpone_periodic_deadline(self):
        node=copy.deepcopy(next(n for n in ast.walk(TREE)
            if isinstance(n,ast.FunctionDef) and n.name=='capture_live_frame'))
        node.body=[ast.Global(names=n.names) if isinstance(n,ast.Nonlocal) else n for n in node.body]
        now=[.1];calls=[]
        def qmp(name,arguments):
            calls.append((name,arguments))
            (self.directory/'live-frame.next.ppm').write_bytes(b'original QMP pixels')
        environment=dict(live_frame_at=0.0,time=types.SimpleNamespace(monotonic=lambda:now[0]),
            args=types.SimpleNamespace(live_frame_seconds=.4),out=self.directory,qmp=qmp,result={},lcd_producer=None)
        exec(compile(ast.fix_missing_locations(ast.Module(body=[node],type_ignores=[])),
                     '<actual live frame function>','exec'),environment)
        capture=environment['capture_live_frame']
        capture(force=True)
        self.assertEqual(environment['live_frame_at'],0)
        now[0]=.4;capture()
        self.assertEqual(environment['live_frame_at'],.4)
        self.assertEqual(len(calls),2)
        self.assertEqual((self.directory/'live-frame.ppm').read_bytes(),b'original QMP pixels')
        environment['lcd_producer']=object()
        now[0]=.8;capture(force=True)
        self.assertEqual(len(calls),2)
        environment['lcd_producer']=None
        environment['args'].live_frame_seconds=0
        capture(force=True)
        self.assertEqual(len(calls),2)


if __name__=='__main__':unittest.main()
