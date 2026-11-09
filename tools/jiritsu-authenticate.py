#!/usr/bin/env python3
"""Authenticate only the current product run's actually enumerated virtual Sony USB."""
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
    args=parser.parse_args(argv)
    run=args.run.absolute()
    if run.parent!=ANALYSIS/'menu-runs' or any(p.is_symlink() for p in (run,*run.parents)):
        parser.error('ordinary product menu-runs/run-* directory required')
    context=read_json(run/'usb-context.json')
    if set(context)!={'run_id','qmp_path','backend_path','lease','vm_pid'}:
        raise ValueError('Unexpected USB context fields')
    control=UsbControl(run,**context)
    result=JiritsuConsumer(control).run('authenticate')
    from usb_control import usbip
    usbip.write_owned_json(run/'jiritsu-authentication.json',result)
    print(json.dumps(result,ensure_ascii=False,indent=2))
    return 0 if result.get('phase')=='complete' and result.get('authentication_verified') is True else 2


if __name__=='__main__':raise SystemExit(main())
