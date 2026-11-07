#!/usr/bin/env python3
"""Verify the second Get owner without asserting Connect/buffer completion."""
import argparse
import json
from pathlib import Path
import runpy

HERE = Path(__file__).resolve().parent


def verify(run):
    api = runpy.run_path(str(HERE / 'verify-vef-pin.py'))
    properties = [(0, 1, 0), (0, 1, 1), (0, 1, 2), (0, 2, 0), (0, 2, 1), (0, 2, 2), (0, 2, 3),
                  (4, 2, 0), (1, 3, 0), (4, 1, 0), (6, 2, 0), (6, 1, 0), (8, 1, 0)]
    proof = api['verify_registry'](run, 'PINMEM', 'pinmem_service', 0x90590818, properties, (0, 1, 1), 1)
    source = api['verify'](run)
    if not (source['console_sha256'] == proof['console_sha256'] and source['caller_tid'] == proof['caller_tid'] and
            source['native_free_observer_record'] < proof['request_observer_record']):
        raise ValueError('Peer Get was not issued by the same original waiter after source release')
    proof['source_get_to_same_waiter_peer_get_verified'] = True
    proof['pinmem_pin_query_verified'] = True
    return proof


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('run', type=Path)
    args = parser.parse_args()
    try:
        proof = verify(args.run)
    except (OSError, KeyError, ValueError, StopIteration, TypeError) as error:
        proof = {'pinmem_pin_query_verified': False, 'error': str(error) or type(error).__name__,
                 'connection_verified': False, 'pixels_consumed': False, 'camera_startup_verified': False}
    (args.run / 'pinmem-pin-query-proof.json').write_text(json.dumps(proof, indent=2) + '\n')
    print(json.dumps(proof, sort_keys=True))
    return 0 if proof['pinmem_pin_query_verified'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
