#!/usr/bin/env python3
"""One owner-bound original USB selection -> host enumeration -> read-only version.

The caller supplies the same run's original function/EP0 receipt. No guest input,
USB reply, descriptor, credential, or preload result is produced by this module.
The host VHCI permission helper is deliberately not invoked here.
"""
from pathlib import Path
import hashlib
import runpy

HERE=Path(__file__).resolve().parent
CONTROL=runpy.run_path(str(HERE/'usb_control.py'))
JIRITSU=runpy.run_path(str(HERE/'usb_jiritsu.py'))


def controller(run_dir):
    run=Path(run_dir)
    if not run.is_absolute() or any(p.is_symlink() for p in (*reversed(run.parents),run)):
        raise ValueError('USB run must be an absolute non-symlink path')
    context=CONTROL['read_json'](run/'usb-context.json')
    if set(context)!={'run_id','qmp_path','backend_path','lease','vm_pid'}:
        raise CONTROL['ControlBlocked']('invalid_context','Unexpected USB run context')
    return CONTROL['UsbControl'](run,**context)


def final_identity(result):
    rows=[row for row in result.get('events',[]) if isinstance(row,dict) and
          row.get('event')=='stop_identity_result' and row.get('verified') is True]
    if len(rows)!=1 or not isinstance(rows[0].get('target'),dict):return False
    target=rows[0]['target']
    return (target.get('product_id') in (0x096f,0x0336) and target.get('vendor_id')==0x054c and
            rows[0].get('source')=='owned-host-sysfs-readback')


def version_verified(result):
    version=result.get('version')
    if not isinstance(version,dict):return False
    try:
        raw=bytes.fromhex(version['content_hex'])
    except (KeyError,ValueError,TypeError):return False
    return (0<len(raw)<=65536 and type(version.get('bytes')) is int and
            version['bytes']==len(raw) and version.get('sha256')==hashlib.sha256(raw).hexdigest())


def run(run_dir, original, *, pmca=None, disconnect=True):
    if not isinstance(original,dict):
        return dict(schema='a7c2.usb-full-chain.v1',phase='blocked',
                    blocked_reason=dict(code='invalid_original_receipt',detail='original function/EP0 receipt must be an object'),
                    host_resources_released=False,host_enumerated=False,authentication_verified=False,
                    guest_root_verified=False,final_identity_verified=False)
    if original.get('original_function_bound') is not True or original.get('descriptor_verified') is not True:
        return dict(schema='a7c2.usb-full-chain.v1',phase='blocked',
                    blocked_reason=dict(code='original_function_or_ep0_unverified',
                                        detail='original camera function and actual EP0 descriptors are required'),
                    host_resources_released=False,host_enumerated=False,authentication_verified=False,guest_root_verified=False,
                    final_identity_verified=False)
    try:
        control=controller(run_dir)
    except (OSError,ValueError,TypeError,RuntimeError) as error:
        return dict(schema='a7c2.usb-full-chain.v1',phase='blocked',
                    blocked_reason=dict(code=getattr(error,'code','invalid_context'),detail=str(error)),
                    host_resources_released=False,host_enumerated=False,authentication_verified=False,guest_root_verified=False,
                    final_identity_verified=False)
    connection=control.connect()
    if connection.get('host_enumerated') is not True:
        closed=control.disconnect() if disconnect else {}
        return dict(schema='a7c2.usb-full-chain.v1',phase=connection.get('phase','blocked'),
                    blocked_reason=connection.get('blocked_reason'),connection=connection,disconnect=closed,
                    host_resources_released=closed.get('phase')=='disconnected',
                    host_enumerated=False,authentication_verified=False,guest_root_verified=False,
                    final_identity_verified=False)
    result=JIRITSU['JiritsuConsumer'](control,pmca=pmca).run('version')
    result['host_resources_released']=False
    complete=(result.get('phase')=='complete' and result.get('authentication_verified') is True and
              version_verified(result) and result.get('preload_recovery_required') is False)
    if result.get('phase')=='complete' and not complete:
        result['phase']='blocked'
        result['blocked_reason']=dict(code='version_content_unverified',detail='consumer version byte/hash receipt is incomplete')
    result['final_identity_verified']=complete and final_identity(result)
    if complete and not result['final_identity_verified']:
        result['phase']='blocked'
        result['blocked_reason']=dict(code='final_usb_identity_unverified',
                                      detail='real owned host readback did not prove final identity')
    if disconnect and result.get('final_identity_verified') is True and not result.get('preload_recovery_required'):
        result['disconnect']=control.disconnect()
        result['host_resources_released']=result['disconnect'].get('phase')=='disconnected'
        if not result['host_resources_released']:
            result['phase']='blocked';result['blocked_reason']=dict(code='owned_usb_disconnect_unverified',detail='owned virtual port was not released')
    result['host_enumerated']=True
    result['guest_root_over_usb_verified']=False
    result['schema']='a7c2.usb-full-chain.v1'
    return result
