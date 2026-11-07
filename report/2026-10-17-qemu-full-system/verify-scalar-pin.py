#!/usr/bin/env python3
"""Scalar Get content and original same-waiter continuation; no pixels."""
import argparse
import json
from pathlib import Path
import re
import runpy

HERE=Path(__file__).resolve().parent


def verify(run):
    properties=[(0,d,i) for d in (1,2) for i in range(5)]
    proof=runpy.run_path(str(HERE/'verify-vef-pin.py'))['verify_registry'](
        run,'SCALAR','scalar_service',0x91670464,properties,(0,1,4),4)
    format_proof=runpy.run_path(str(HERE/'verify-pin-format.py'))['verify'](run)
    if proof['caller_tid']!=format_proof['caller_tid'] or proof['console_sha256']!=format_proof['console_sha256']:
        raise ValueError('Scalar Get caller differs from original format continuation')
    api=runpy.run_path(str(HERE/'verify-system-sound-config.py'))
    lines,_=api['observer_lines']((run/'console.log').read_bytes(),('SCALAR','PINMEM'),deduplicate=False)
    records=[(i,line,dict(re.findall(r'(\w+)=([^\s]+)',line))) for i,line in enumerate(lines)]
    tid=str(proof['caller_tid'])
    commit=next(row for row in records if row[1].startswith('OBS FULL_PINMEM_COMMIT ') and
                row[2].get('tid')==tid and row[2].get('slot')=='4' and row[2].get('request_free_rc')=='0')
    freed=next(row for row in records if row[0]>commit[0] and row[1].startswith('OBS FULL_PINMEM_NATIVE_REPLY_FREE ') and
               row[2].get('reply')==commit[2]['reply'] and row[2].get('lease')==commit[2]['lease'] and
               row[2].get('tid')==row[2].get('sender')==tid and row[2].get('rc')=='0' and row[2].get('waiter')=='1')
    request=next(row for row in records if row[1].startswith('OBS FULL_SCALAR_REQUEST ') and row[2].get('tid')==tid)
    if request[0]<=freed[0]:raise ValueError('Scalar request did not follow original PinMem OUT1 waiter free')
    proof.update(scalar_pin_query_verified=True,source_get_to_same_waiter_scalar_get_verified=True,
                 scalar_connection_verified=False,scalar_frame_processing_verified=False)
    return proof


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('run',type=Path);args=parser.parse_args()
    try:proof=verify(args.run)
    except (OSError,KeyError,ValueError,StopIteration,TypeError) as error:
        proof={'scalar_pin_query_verified':False,'error':str(error) or type(error).__name__,
               'camera_startup_verified':False,'pixels_consumed':False}
    (args.run/'scalar-pin-query-proof.json').write_text(json.dumps(proof,indent=2)+'\n')
    print(json.dumps(proof,sort_keys=True));return 0 if proof['scalar_pin_query_verified'] else 1


if __name__=='__main__':raise SystemExit(main())
