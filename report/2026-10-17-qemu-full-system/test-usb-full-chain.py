#!/usr/bin/env python3
"""Synthetic controller tests only; never evidence of USB authentication/root."""
from pathlib import Path
import hashlib,runpy,unittest
API=runpy.run_path(str(Path(__file__).with_name('usb-full-chain.py')))
G=API['run'].__globals__
VERSION=dict(bytes=4,content_hex=b'2.01'.hex(),sha256=hashlib.sha256(b'2.01').hexdigest())
ORIGINAL=dict(original_function_bound=True,descriptor_verified=True)

class Control:
    def __init__(self,connected=True):self.connected=connected;self.disconnected=0;self.calls=0
    def connect(self):self.calls+=1;return dict(phase='connected' if self.connected else 'blocked',host_enumerated=self.connected,blocked_reason=None if self.connected else dict(code='vhci_permission_denied'))
    def disconnect(self):self.disconnected+=1;return dict(phase='disconnected')

class Chain(unittest.TestCase):
    def setUp(self):self.old_controller=G['controller'];self.old_consumer=G['JIRITSU']['JiritsuConsumer'];self.addCleanup(self.restore)
    def restore(self):G['controller']=self.old_controller;G['JIRITSU']['JiritsuConsumer']=self.old_consumer
    def test_original_function_required(self):
        G['controller']=lambda path:(_ for _ in ()).throw(AssertionError('must not connect'))
        result=API['run']('/unused',dict(original_function_bound=False,descriptor_verified=True))
        self.assertEqual(result['blocked_reason']['code'],'original_function_or_ep0_unverified');self.assertFalse(result['host_enumerated']);self.assertFalse(result['host_resources_released'])
    def consume(self,control,result):
        G['controller']=lambda path:control
        class Consumer:
            def __init__(self,control,pmca=None):pass
            def run(self,action):self.action=action;return dict(result)
        G['JIRITSU']['JiritsuConsumer']=Consumer
        return API['run']('/unused',ORIGINAL)
    def test_complete_requires_real_final_identity_before_disconnect(self):
        self.assertEqual(API['final_identity'](dict(events=[])),False)
        control=Control();result=dict(phase='complete',authentication_verified=True,version=VERSION,
                                    guest_root_verified=False,preload_recovery_required=False,
                                    events=[dict(event='stop_identity_result',verified=False)])
        got=self.consume(control,result);self.assertEqual(got['phase'],'blocked');self.assertEqual(control.disconnected,0);self.assertEqual(got['blocked_reason']['code'],'final_usb_identity_unverified')
    def test_complete_version_and_owned_final_identity_disconnect(self):
        control=Control();result=dict(phase='complete',authentication_verified=True,version=VERSION,guest_root_verified=False,preload_recovery_required=False,events=[dict(event='stop_identity_result',verified=True,source='owned-host-sysfs-readback',target=dict(vendor_id=0x054c,product_id=0x096f))])
        got=self.consume(control,result);self.assertEqual(got['phase'],'complete');self.assertFalse(got['guest_root_over_usb_verified']);self.assertEqual(control.disconnected,1)
    def test_recovery_retains_connection(self):
        control=Control();result=dict(phase='recovery_required',authentication_verified=False,guest_root_verified=False,preload_recovery_required=True,events=[])
        got=self.consume(control,result);self.assertEqual(control.disconnected,0);self.assertEqual(got['phase'],'recovery_required')
    def test_connect_denial_does_not_consume(self):
        control=Control(False)
        class Consumer:
            def __init__(self,*a,**kw):raise AssertionError('consumer called')
        G['controller']=lambda path:control;G['JIRITSU']['JiritsuConsumer']=Consumer
        got=API['run']('/unused',ORIGINAL);self.assertEqual(got['blocked_reason']['code'],'vhci_permission_denied');self.assertEqual(control.calls,1)
        self.assertEqual(control.disconnected,1);self.assertTrue(got['host_resources_released'])
    def test_pending_attach_cannot_be_closed_by_enumerated_false(self):
        control=Control(False);control.disconnect=lambda:dict(phase='blocked',blocked_reason=dict(code='detach_pending'))
        G['controller']=lambda path:control
        got=API['run']('/unused',ORIGINAL)
        self.assertFalse(got['host_resources_released']);self.assertEqual(got['blocked_reason']['code'],'vhci_permission_denied')
    def test_context_failure_is_structured(self):
        for error in (ValueError('bad context'),RuntimeError('parent Blocked'),TypeError('bad run path')):
            with self.subTest(error=type(error).__name__):
                G['controller']=lambda path,error=error:(_ for _ in ()).throw(error)
                got=API['run']('/unused',ORIGINAL)
                self.assertEqual(got['phase'],'blocked');self.assertEqual(got['blocked_reason']['code'],'invalid_context')
                self.assertFalse(got['host_resources_released'])
    def test_original_receipt_type_is_structured(self):
        G['controller']=lambda path:(_ for _ in ()).throw(AssertionError('must not construct'))
        got=API['run']('/unused',None)
        self.assertEqual(got['blocked_reason']['code'],'invalid_original_receipt')
        self.assertFalse(got['host_resources_released'])
    def test_bad_version_receipt_cannot_complete(self):
        control=Control();result=dict(phase='complete',authentication_verified=True,
            version=dict(VERSION,sha256='0'*64),preload_recovery_required=False,events=[])
        got=self.consume(control,result);self.assertEqual(got['blocked_reason']['code'],'version_content_unverified')
        self.assertEqual(control.disconnected,0)
    def test_consumer_failure_is_preserved(self):
        control=Control();original=dict(code='original_auth_failure',detail='raw failure')
        got=self.consume(control,dict(phase='blocked',authentication_verified=False,preload_recovery_required=False,events=[],blocked_reason=original))
        self.assertEqual(got['blocked_reason'],original);self.assertFalse(got['host_resources_released'])

if __name__=='__main__':unittest.main()
