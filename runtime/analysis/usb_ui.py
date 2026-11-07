#!/usr/bin/env python3
"""UI-facing USB actions for exactly one run's declared virtual endpoint backend."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from usb_control import ControlBlocked, UsbControl, read_json


def action(run_dir, operation):
    if operation not in ('status', 'connect', 'disconnect'):
        raise ValueError('Unknown USB UI action')
    run = Path(run_dir)
    if not run.is_absolute():
        raise ValueError('USB run directory must be absolute')
    for component in (*reversed(run.parents), run):
        if component.is_symlink():
            raise ValueError('USB run directory cannot contain symlinks')
    try:
        context = read_json(run / 'usb-context.json')
    except FileNotFoundError:
        return {'schema':'a7c2.usb-control.v1','phase':'blocked',
                'blocked_reason':{'code':'device_backend_not_enabled',
                                  'detail':'本次 VM 尚未启用相机 USB 设备端点模型，不能连接本机电脑'},
                'host_enumerated':False,'authentication_verified':False,'guest_root_verified':False}
    if set(context) != {'run_id','qmp_path','backend_path','lease','vm_pid'}:
        raise ControlBlocked('invalid_context', 'Unexpected USB run context fields')
    control = UsbControl(run, **context)
    result = getattr(control, operation)()
    # Authentication/root are set only by a separate, real jiritsu consumer.
    return result


def display_result(result):
    reason = result.get('blocked_reason') or {}
    if result.get('phase') == 'recovery_required':
        return 'USB 需要先完成相机侧恢复：' + str(reason.get('detail', '请保留当前连接'))
    if reason:
        return 'USB 连接未完成：' + str(reason.get('detail', '后端尚未就绪'))
    if result.get('guest_root_verified'):
        return '本机已通过 USB 验证相机侧 root 权限'
    if result.get('host_enumerated'):
        return '本机已枚举相机 USB；认证和权限尚未验证'
    if result.get('phase') == 'disconnected':
        return 'USB 已断开'
    return 'USB 正在等待本机枚举'


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-dir',type=Path,required=True)
    parser.add_argument('operation',choices=('status','connect','disconnect'))
    parser.add_argument('--human', action='store_true', help='display connection status without implementation fields')
    args=parser.parse_args(argv)
    try:
        result=action(args.run_dir,args.operation)
    except (OSError,ValueError,ControlBlocked) as error:
        result={'schema':'a7c2.usb-control.v1','phase':'blocked',
                'blocked_reason':{'code':getattr(error,'code','usb_action_refused'),'detail':str(error)},
                'host_enumerated':False,'authentication_verified':False,'guest_root_verified':False}
    print(display_result(result) if args.human else json.dumps(result,ensure_ascii=False,allow_nan=False))
    return 2 if result['phase'] in ('blocked','error','recovery_required') else 0


if __name__=='__main__':raise SystemExit(main())
