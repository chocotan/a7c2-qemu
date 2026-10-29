#!/usr/bin/env python3
"""ADF found-key Get and original waiter continuation; no third-edge success."""
import argparse
import json
from pathlib import Path
import runpy

HERE=Path(__file__).resolve().parent


def verify(run):
    properties=[(0,1,0),(2,1,0),(2,1,1),(2,1,2),(3,1,0),(5,1,0),(2,2,0),(2,2,1),(2,2,2),(5,2,0)]
    proof=runpy.run_path(str(HERE/'verify-vef-pin.py'))['verify_registry'](
        run,'ADF','adf_service',0x9058003f,properties,(0,1,0),0)
    previous=runpy.run_path(str(HERE/'verify-scalar-connection.py'))['verify'](run)
    if proof['caller_tid']!=previous['caller_tid'] or proof['console_sha256']!=previous['console_sha256']:
        raise ValueError('ADF Get differs from original OUT2 continuation waiter/console')
    result=json.loads((run/'result.json').read_text())
    if result['state']!='observation-completed':raise ValueError('Whole run did not complete')
    if not runpy.run_path(str(HERE/'run-full-system.py'))['adf_get_ready']((run/'console.log').read_bytes()):
        raise ValueError('Ordered OUT2 free, ADF free and exact next Connect request missing')
    proof.update(adf_pin_query_verified=True,out2_to_adf_get_free_verified=True,
                 next_out2_adf_connect_request_observed=True,adf_connection_verified=False)
    return proof


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('run',type=Path);args=parser.parse_args()
    try:proof=verify(args.run)
    except (OSError,KeyError,ValueError,StopIteration,TypeError) as error:
        proof={'adf_pin_query_verified':False,'error':str(error) or type(error).__name__,
               'camera_startup_verified':False,'pixels_consumed':False}
    (args.run/'adf-pin-query-proof.json').write_text(json.dumps(proof,indent=2)+'\n')
    print(json.dumps(proof,sort_keys=True));return 0 if proof['adf_pin_query_verified'] else 1


if __name__=='__main__':raise SystemExit(main())
