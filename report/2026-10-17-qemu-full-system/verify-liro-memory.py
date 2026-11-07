#!/usr/bin/env python3
"""Verify a full readonly reserved-window export, including negative residency."""
import argparse
import hashlib
import json
from pathlib import Path
import runpy

HERE = Path(__file__).resolve().parent


def require(value, reason):
    if not value:
        raise ValueError(reason)


def verify(run):
    api = runpy.run_path(str(HERE / 'liro-memory-probe.py'))
    inputs = json.loads((run / 'inputs.json').read_text())
    result = json.loads((run / 'result.json').read_text())
    memory = json.loads((run / 'liro-memory.json').read_text())
    loader = json.loads((run / 'liro-loader-observation-proof-v2.json').read_text())
    console_sha = hashlib.sha256((run / 'console.log').read_bytes()).hexdigest()
    require(inputs['experiment'].get('probe_liro_memory') is True and result.get('liro_reserved_memory_observed'),
            'Explicit memory observation missing')
    require(result.get('terminal_evidence_checked') and result['terminal_console_sha256'] == console_sha,
            'Terminal console differs')
    require(loader.get('liro_loader_observation_verified') and loader['console_sha256'] == console_sha and
            int(loader['caller_slot'], 0) == api['ADDRESS'], 'Native observed address differs')
    data = (run / 'liro-reserved-memory.bin').read_bytes()
    require(len(data) == api['CAPACITY'] and hashlib.sha256(data).hexdigest() == memory['export_sha256'], 'RAM export length/digest differs')
    require(memory['kernel_sha256'] == api['KERNEL_SHA256'] and memory['memstart_value'] == '0x400000000' and
            int(memory['physical'], 0) == api['ADDRESS'] and memory['direct_map_address'] == '0xffffffc001000000',
            'Kernel/base/linked-address evidence differs')
    require(memory['window_all_zero'] == (not any(data)) and memory['image_matches_original'] ==
            (hashlib.sha256(data[:api['IMAGE_BYTES']]).hexdigest() == api['IMAGE_SHA256']), 'Residency classification differs')
    return {'liro_reserved_window_verified': True, 'memstart_value': memory['memstart_value'],
            'physical': memory['physical'], 'capacity': len(data), 'window_all_zero': memory['window_all_zero'],
            'image_matches_original': memory['image_matches_original'], 'export_sha256': memory['export_sha256'],
            'console_sha256': console_sha, 'image_loaded_by_probe': False, 'LIRO_initialized_verified': False,
            'MC_owner_verified': False, 'camera_startup_verified': False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('run', type=Path)
    args = parser.parse_args()
    try:
        proof = verify(args.run)
    except (OSError, KeyError, ValueError, StopIteration, TypeError) as error:
        proof = {'liro_reserved_window_verified': False, 'error': str(error) or type(error).__name__,
                 'LIRO_initialized_verified': False, 'MC_owner_verified': False, 'camera_startup_verified': False}
    (args.run / 'liro-reserved-window-proof.json').write_text(json.dumps(proof, indent=2) + '\n')
    print(json.dumps(proof, sort_keys=True))
    return 0 if proof['liro_reserved_window_verified'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
