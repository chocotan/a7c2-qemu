#!/usr/bin/env python3
"""Compare two BK4 configuration files property by property.

A boot rewrites bookkeeping properties, so a plain byte or SHA comparison cannot
answer "did my setting survive". This tool reports which (record, subsystem, local)
properties actually differ, and can subtract a known boot-time set so only real
setting changes remain.
"""
import argparse
import hashlib
import json
from pathlib import Path
import runpy

HERE = Path(__file__).resolve().parent


def properties(data):
    state = runpy.run_path(str(HERE / 'backup-state.py'))
    # Structure only: a comparator must accept a file that a boot has just rewritten,
    # and it is not this tool's job to re-assert the BK4 checksum.
    parsed = state['parse_file'](data, verify_checksum=False)
    out = {}
    for index, record in enumerate(parsed):
        for key, value in record['properties'].items():
            out[(index, key >> 16, key & 0xffff)] = value['data']
    return out


def power_saving_key(record=0, subsystem=0x2cf, local=0x50):
    """The property the project already traced for setting_start_power_saving."""
    return (record, subsystem, local)


def diff_properties(a, b, boot_set=None):
    """Pure comparison of two {key: bytes} maps, with an optional boot-time set."""
    if set(a) != set(b):
        raise ValueError('the two files do not expose the same property set')
    changed = {key for key in a if a[key] != b[key]}
    boot = {tuple(item) for item in (boot_set or [])}
    return {'properties': len(a),
            'changed': len(changed),
            'changed_keys': sorted(changed),
            'setting_changes': sorted(changed - boot),
            'boot_bookkeeping_changes': len(changed & boot) if boot else None}


def compare(base, variant, boot_set=None):
    result = diff_properties(properties(base), properties(variant), boot_set)
    result['base_sha256'] = hashlib.sha256(base).hexdigest()
    result['variant_sha256'] = hashlib.sha256(variant).hexdigest()
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base', type=Path, required=True)
    parser.add_argument('--variant', type=Path, required=True)
    parser.add_argument('--boot-set', type=Path, default=None,
                        help='JSON with a list of [record, subsystem, local] keys known to change at boot')
    parser.add_argument('--json', type=Path, default=None)
    args = parser.parse_args()
    boot = json.loads(args.boot_set.read_text()) if args.boot_set else None
    result = compare(args.base.read_bytes(), args.variant.read_bytes(), boot)
    if args.json:
        args.json.write_text(json.dumps(result, indent=2) + '\n')
    print(f"properties {result['properties']}  changed {result['changed']}"
          f"  setting-level {len(result['setting_changes'])}")
    for record, subsystem, local in result['setting_changes'][:20]:
        print(f'  setting change record={record} subsystem={subsystem:#x} local={local:#x}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
