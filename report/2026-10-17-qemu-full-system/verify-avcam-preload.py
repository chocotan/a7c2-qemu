#!/usr/bin/env python3
"""Prove original data residency without claiming module/code execution."""
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
    api = runpy.run_path(str(HERE / 'avcam-preload.py'))
    inputs = json.loads((run / 'inputs.json').read_text())
    loader = json.loads((run / 'liro-loader-observation-proof-v2.json').read_text())
    memory = json.loads((run / 'liro-reserved-window-proof.json').read_text())
    result = json.loads((run / 'result.json').read_text())
    console = (run / 'console.log').read_bytes()
    sha = hashlib.sha256(console).hexdigest()
    identity = inputs['avcam_preload']
    require(inputs['experiment'].get('preload_avcam') is True and
            identity['physical'] == api['PHYSICAL'] and identity['capacity'] == api['CAPACITY'] and
            identity['bytes'] == api['IMAGE_BYTES'] and identity['sha256'] == api['IMAGE_SHA256'] and
            identity['sets_cpu_entry'] is False and identity['initializes_LIRO'] is False and
            identity['supplies_image_data'] is True and identity['original_module_arguments_changed'] is False,
            'Explicit bounded data preload identity differs')
    require(result.get('terminal_evidence_checked') and result['terminal_console_sha256'] == sha and
            loader.get('liro_loader_observation_verified') and loader['console_sha256'] == sha and
            memory.get('liro_reserved_window_verified') and memory['console_sha256'] == sha,
            'Native loader/full-window/terminal association missing')
    require(int(loader['caller_slot'], 0) == api['PHYSICAL'] and loader['native_backup_return_matches_slot_length'] and
            not int(loader['flags_at_format_sample'], 0) & 0x1000 and loader['module_link_failed'],
            'Original loader no longer follows the observed preload path/link-failure boundary')
    require(loader['actual_module_arguments'] == ' adr=0x401000000  ' and
            all(int(loader[field], 0) == 1 for field in
                ('flags_at_backup_sample', 'flags_at_format_sample', 'argv_flags_at_format_sample')),
            'Actual original module parameters or flags differ from the observed data-preload profile')
    require(b'memrsv: 0x1000000@0x401000000' in console and b'FULLSYSTEM_AVCAM_DATA_PRELOAD_VALIDATED ' in console,
            'Original reservation or explicit prelaunch validation missing')
    data = (run / 'liro-reserved-memory.bin').read_bytes()
    require(len(data) == api['CAPACITY'] and hashlib.sha256(data).hexdigest() == memory['export_sha256'],
            'Complete reserved RAM export differs')
    require(hashlib.sha256(data[:api['IMAGE_BYTES']]).hexdigest() == api['IMAGE_SHA256'] and
            not any(data[api['IMAGE_BYTES']:]) and data[8:12] == b'ORIL' and memory['image_matches_original'],
            'Original image prefix or remaining padding differs')
    return {'schema': 2, 'original_avcam_data_resident': True, 'source': 'explicit-QEMU-file-loader-data',
            'physical': hex(api['PHYSICAL']), 'capacity': len(data), 'image_bytes': api['IMAGE_BYTES'],
            'image_sha256': api['IMAGE_SHA256'], 'padding_bytes': len(data) - api['IMAGE_BYTES'],
            'padding_all_zero': True, 'console_sha256': sha, 'export_sha256': memory['export_sha256'],
            'cpu_entry_changed_by_preload': False, 'original_module_arguments_changed': False,
            'actual_module_arguments': loader['actual_module_arguments'],
            'loader_flags_samples_verified': 1,
            'LIRO_initialized_verified': False, 'MC_owner_verified': False, 'camera_startup_verified': False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('run', type=Path)
    args = parser.parse_args()
    try:
        proof = verify(args.run)
    except (OSError, KeyError, ValueError, StopIteration, TypeError) as error:
        proof = {'original_avcam_data_resident': False, 'error': str(error) or type(error).__name__,
                 'LIRO_initialized_verified': False, 'MC_owner_verified': False, 'camera_startup_verified': False}
    (args.run / 'avcam-data-preload-proof.json').write_text(json.dumps(proof, indent=2) + '\n')
    print(json.dumps(proof, sort_keys=True))
    return 0 if proof['original_avcam_data_resident'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
