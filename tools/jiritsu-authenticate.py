#!/usr/bin/env python3
"""Authenticate, read version, or verify guest credentials on this run's virtual Sony USB."""
import argparse
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
ANALYSIS=ROOT/'runtime/analysis'
sys.path.insert(0,str(ANALYSIS))
from usb_control import UsbControl,read_json
from usb_jiritsu import JiritsuConsumer


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run',type=Path,required=True,help='current product menu-runs/run-* directory')
    parser.add_argument('--action',choices=('authenticate','version','root'),default='authenticate')
    parser.add_argument('--command',action='append',help='ASCII shell command in the same virtual root worker session; repeat for ordered readback and cleanup')
    parser.add_argument('--large-out-check',action='store_true',help='write/read exactly 70,912 bytes through this root session before worker deployment')
    args=parser.parse_args(argv)
    if (args.command or args.large_out_check) and args.action!='root':parser.error('--command/--large-out-check require --action root')
    run=args.run.absolute()
    if run.parent!=ANALYSIS/'menu-runs' or any(p.is_symlink() for p in (run,*run.parents)):
        parser.error('ordinary product menu-runs/run-* directory required')
    context=read_json(run/'usb-context.json')
    if set(context)!={'run_id','qmp_path','backend_path','lease','vm_pid'}:
        raise ValueError('Unexpected USB context fields')
    control=UsbControl(run,**context)
    result=JiritsuConsumer(control).run(args.action,commands=args.command,large_out_check=args.large_out_check)
    from usb_control import usbip
    output={'authenticate':'jiritsu-authentication.json','version':'jiritsu-version.json','root':'jiritsu-root.json'}[args.action]
    usbip.write_owned_json(run/output,result)
    print(json.dumps(result,ensure_ascii=False,indent=2))
    verified=result.get('phase')=='complete' and result.get('authentication_verified') is True
    if args.action=='version':
        verified &= type(result.get('version',{}).get('bytes')) is int and result['version']['bytes']>0
    if args.action=='root':
        verified &= result.get('guest_root_verified') is True and not result.get('preload_recovery_required')
        if args.command:verified &= result.get('requested_commands_verified') is True
        if args.large_out_check:verified &= result.get('large_out_verified') is True
    return 0 if verified else 2


if __name__=='__main__':raise SystemExit(main())
