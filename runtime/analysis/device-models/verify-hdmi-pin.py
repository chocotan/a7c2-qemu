#!/usr/bin/env python3
"""Independent HDMI pin metadata and actual original AP continuation."""
import argparse
import json
from pathlib import Path
import runpy

HERE=Path(__file__).resolve().parent


def verify(run):
    proof=runpy.run_path(str(HERE/'verify-vef-pin.py'))['verify_registry'](
        run,'HDMIPIN','hdmi_pin_service',0x909a015a,[(4,1,0),(5,1,0)],(4,1,0),0)
    previous=runpy.run_path(str(HERE/'verify-adf-connection.py'))['verify'](run)
    if proof['caller_tid']!=previous['caller_tid'] or proof['console_sha256']!=previous['console_sha256']:
        raise ValueError('HDMI pin query differs from original third-edge continuation')
    result=json.loads((run/'result.json').read_text());console=(run/'console.log').read_bytes()
    if result['state']!='observation-completed':raise ValueError('Whole observation did not complete')
    if not runpy.run_path(str(HERE/'run-full-system.py'))['hdmi_pin_get_ready'](console):
        raise ValueError('Same waiter HDMI Get/free and exact next Connect missing')
    reservation=runpy.run_path(str(HERE/'verify-pin-control.py'))
    command=reservation['verify_reservation'](run,runpy.run_path(str(HERE/'pin-buffer-region.py')))
    if command.split().count('fullsystem.hdmi-pin=registry')!=1 or b'FULLSYSTEM_HDMIPIN_PROFILE=registry' not in console:
        raise ValueError('Actual HDMI pin opt-in missing')
    proof.update(hdmi_pin_query_verified=True,virtual_slot=0,original_object_location='PinHandler+8',
                 next_type4_hdmi_connect_request_observed=True,hdmi_pin_connection_verified=False,
                 original_cp_diagnostic_path_executed=False,hdmi_output_verified=False)
    return proof


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('run',type=Path);args=parser.parse_args()
    try:proof=verify(args.run)
    except (OSError,KeyError,ValueError,StopIteration,TypeError) as error:
        proof={'hdmi_pin_query_verified':False,'error':str(error) or type(error).__name__,'camera_startup_verified':False,'pixels_consumed':False}
    (args.run/'hdmi-pin-query-proof.json').write_text(json.dumps(proof,indent=2)+'\n')
    print(json.dumps(proof,sort_keys=True));return 0 if proof['hdmi_pin_query_verified'] else 1


if __name__=='__main__':raise SystemExit(main())
