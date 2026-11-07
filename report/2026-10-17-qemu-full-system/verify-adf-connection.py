#!/usr/bin/env python3
"""Third finite handshake, actual state/messages and original AP consumption."""
import argparse
import json
from pathlib import Path
import runpy
import struct

HERE=Path(__file__).resolve().parent


def verify(run):
    return runpy.run_path(str(HERE/'verify-scalar-connection.py'))['verify_connection'](run,'ADF')


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('run',type=Path);args=parser.parse_args()
    try:proof=verify(args.run)
    except (OSError,ValueError,KeyError,StopIteration,TypeError,struct.error) as error:
        proof={'adf_control_connection_verified':False,'error':str(error) or type(error).__name__,'camera_startup_verified':False}
    (args.run/'adf-connection-proof.json').write_text(json.dumps(proof,indent=2)+'\n')
    print(json.dumps(proof,sort_keys=True));return 0 if proof['adf_control_connection_verified'] else 1


if __name__=='__main__':raise SystemExit(main())
