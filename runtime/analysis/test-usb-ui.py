import json
import os
from pathlib import Path
import runpy
import tempfile
import unittest
from unittest.mock import patch

m=runpy.run_path(str(Path(__file__).with_name('usb_ui.py')))


class UsbUiTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)

    def test_missing_backend_is_blocked_without_connection_or_auth(self):
        value=m['action'](self.root,'connect')
        self.assertEqual(value['phase'],'blocked')
        self.assertEqual(value['blocked_reason']['code'],'device_backend_not_enabled')
        for key in ['host_enumerated','authentication_verified','guest_root_verified']:
            self.assertFalse(value[key])
        self.assertIn('未完成',m['display_result'](value))

    def test_context_is_owned_and_exact_before_dispatch(self):
        context={'run_id':self.root.name,'qmp_path':str(self.root/'qmp.sock'),
                 'backend_path':str(self.root/'usb-endpoint.sock'),'lease':'a'*32,'vm_pid':os.getpid()}
        path=self.root/'usb-context.json';path.write_text(json.dumps(context));path.chmod(0o600)
        with patch.dict(m['action'].__globals__, UsbControl=lambda run,**kw:self.assertEqual(kw,context) or
                         type('Control',(),{'connect':lambda self:{'phase':'attached','host_enumerated':False}})()):
            result=m['action'](self.root,'connect')
        self.assertEqual(result['phase'],'attached')
        self.assertFalse(result['host_enumerated'])
        context['surprise']='untrusted';path.write_text(json.dumps(context))
        with self.assertRaises(m['ControlBlocked']):m['action'](self.root,'connect')

    def test_symlink_or_insecure_context_never_dispatches(self):
        alias=self.root/'linked';alias.symlink_to(self.root,target_is_directory=True)
        with self.assertRaises(ValueError):m['action'](alias,'connect')
        path=self.root/'usb-context.json';path.write_text('{}');path.chmod(0o644)
        with self.assertRaises(m['ControlBlocked']):m['action'](self.root,'connect')
        with self.assertRaises(ValueError):m['action'](self.root,'execute-host-command')

    def test_enumeration_does_not_display_authentication_or_root(self):
        message=m['display_result']({'phase':'enumerated','host_enumerated':True,
                                     'authentication_verified':False,'guest_root_verified':False})
        self.assertIn('枚举',message)
        self.assertIn('尚未验证',message)
        self.assertNotIn('root',message)
        message=m['display_result']({'phase':'recovery_required','preload_recovery_required':True,
                                    'blocked_reason':{'detail':'neutralization not verified'}})
        self.assertIn('恢复',message)


if __name__=='__main__':unittest.main()
