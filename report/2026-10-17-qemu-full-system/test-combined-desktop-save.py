#!/usr/bin/env python3
"""Controller fault injection; synthetic processes are not real guest acceptance."""
import json
from pathlib import Path
import runpy
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

HERE=Path(__file__).resolve().parent
CAMERA=runpy.run_path(str(HERE/'run-camera.py'))


class ImmediateThread:
    def __init__(self, target, **kwargs):self.target=target
    def start(self):self.target()


class CombinedDesktopSave(unittest.TestCase):
    def execute(self, rc, bad_receipt=False):
        root=Path(self.enterContext(tempfile.TemporaryDirectory()))
        workspace=root/'workspace';workspace.mkdir()
        runtime=root/'runtime';run=runtime/'analysis/runs/run-fixture';run.mkdir(parents=True)
        (run/'inputs.json').write_text('{"source":"official-bodydata-derived"}')
        (run/'result.json').write_text(json.dumps({'state':'failed' if rc else 'observation-completed',
                                                  'terminal_console_sha256':'0'*64}))
        ui_binary=root/'camera-ui';ui_binary.write_bytes(b'not executable; processes are mocked')
        events=[]
        vm=mock.Mock();vm.pid=101;vm.returncode=None
        vm.stdout=[f'FULLSYSTEM_RUN {run}\n'];vm.poll.return_value=None
        def wait(**kwargs):
            events.append('guest-finished');vm.returncode=rc;vm.poll.return_value=rc;return rc
        vm.wait.side_effect=wait
        ui=mock.Mock();ui.pid=202;ui.returncode=0;ui.poll.return_value=0
        store=mock.Mock();store.current.return_value={'identity':'gen-'+'1'*64}
        def save(*args):events.append('config-published');return {'generation':'gen-'+'2'*64}
        store.save_run.side_effect=save
        lease=mock.Mock();lease.__enter__=mock.Mock(return_value=store);lease.__exit__=mock.Mock()
        config={'locked':lambda *args:lease,'official_reference':lambda *args:b'PP fixture'}
        def restore(*args):events.append('sd-restored');return {'image_sha256':'3'*64}
        sd={'pack':mock.Mock(return_value={'tree':{}}),'restore':mock.Mock(side_effect=restore)}
        load=mock.Mock(side_effect=ValueError('bad receipt') if bad_receipt else None,
                       return_value={'schema':'sd-terminal-receipt-v1'})
        def modules(path):
            name=Path(path).name
            return {'workspace-config.py':config,'sd-directory.py':sd,'save-evidence.py':{'load_card_receipt':load}}[name]
        cli=['run-camera.py','--runtime',str(runtime),'--ui',str(ui_binary),
             '--workspace',str(workspace),'--config-workspace',str(workspace),'--attach-sd']
        # Keep the temporary input directory inside this owned fixture too.
        original_mkdtemp=tempfile.mkdtemp
        def temporary(*args,**kwargs):
            kwargs.setdefault('dir',root)
            return original_mkdtemp(*args,**kwargs)
        error=None;returned=None
        with mock.patch.object(sys,'argv',cli), \
             mock.patch.object(CAMERA['runpy'],'run_path',side_effect=modules), \
             mock.patch.object(CAMERA['subprocess'],'Popen',side_effect=[vm,ui]), \
             mock.patch.object(CAMERA['subprocess'],'run'), \
             mock.patch.object(CAMERA['threading'],'Thread',ImmediateThread), \
             mock.patch.object(CAMERA['tempfile'],'mkdtemp',side_effect=temporary):
            try:returned=CAMERA['main']()
            except Exception as caught:error=caught
        return root,run,events,vm,store,sd,lease,returned,error

    def test_success_restores_card_before_publishing_config(self):
        root,run,events,vm,store,sd,lease,returned,error=self.execute(0)
        self.assertIsNone(error)
        self.assertEqual(returned,0)
        self.assertEqual(events,['guest-finished','sd-restored','config-published'])
        vm.wait.assert_called_once_with(timeout=420)
        self.assertTrue((run/'workspace-config-save.json').is_file())
        lease.__exit__.assert_called_once()

    def test_later_config_failure_still_restores_card_but_session_fails(self):
        root,run,events,vm,store,sd,lease,returned,error=self.execute(1)
        self.assertIsInstance(error,RuntimeError)
        self.assertIn('verified SD content was synchronized',str(error))
        self.assertEqual(events,['guest-finished','sd-restored'])
        store.save_run.assert_not_called()
        self.assertFalse((run/'workspace-config-save.json').exists())
        self.assertTrue((run/'sd-directory-sync.json').exists())

    def test_invalid_receipt_publishes_neither_card_nor_config(self):
        root,run,events,vm,store,sd,lease,returned,error=self.execute(1,bad_receipt=True)
        self.assertIsInstance(error,ValueError)
        sd['restore'].assert_not_called();store.save_run.assert_not_called()
        self.assertFalse((run/'sd-directory-sync.json').exists())


if __name__=='__main__':unittest.main()
