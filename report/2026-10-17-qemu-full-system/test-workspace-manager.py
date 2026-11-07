"""Manager shutdown must let a confirmed backend finish, never kill only its UI."""
from pathlib import Path
import io
import runpy
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

HERE=Path(__file__).resolve().parent
API=runpy.run_path(str(HERE/'start-official-camera.py'))


class ManagerTests(unittest.TestCase):
    def test_interrupt_closes_owned_control_pipe_and_waits_without_termination(self):
        class Process:
            pid=12345
            returncode=None
            def __init__(self):self.stdin=io.BytesIO();self.calls=0
            def poll(self):return self.returncode
            def wait(self,timeout=None):
                self.calls+=1
                if self.calls==1:raise KeyboardInterrupt()
                assert self.stdin.closed
                if self.calls==2:raise subprocess.TimeoutExpired('owned UI',1)
                if self.calls==3:raise KeyboardInterrupt()
                self.returncode=0
                return 0
        child=Process();scope=API['main'].__globals__
        with tempfile.TemporaryDirectory() as directory:
            argv=['start-official-camera.py','--workspace',directory,'--manage-settings']
            with mock.patch.object(sys,'argv',argv),mock.patch.dict(scope,start_owned=lambda *a:Path(directory)/'runtime'), \
                 mock.patch.object(Path,'is_file',return_value=True), \
                 mock.patch.object(subprocess,'Popen',return_value=child) as spawn:
                with self.assertRaises(KeyboardInterrupt):API['main']()
        self.assertEqual(child.returncode,0)
        self.assertEqual(child.calls,4)
        self.assertIn('--managed-close-on-eof',spawn.call_args.args[0])
        self.assertIs(spawn.call_args.kwargs['stdin'],subprocess.PIPE)

    def test_offline_manager_refuses_guest_run_modes_before_preparing(self):
        for option in ('--headless','--attach-sd','--prepare-only','--walk-first-setup'):
            with self.subTest(option=option),mock.patch.object(sys,'argv',['start-official-camera.py','--manage-settings',option]), \
                 mock.patch.dict(API['main'].__globals__,start_owned=mock.Mock(side_effect=AssertionError('must not prepare'))):
                with self.assertRaises(SystemExit) as error:API['main']()
                self.assertEqual(error.exception.code,2)
