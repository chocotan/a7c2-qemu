"""Extract finite private EE inputs from one SHA-bound, completed instance copy.

Never reads a live disk; never supplies ADC/current keys or a runtime gate.
"""
import argparse
import hashlib
import io
import json
from pathlib import Path
import runpy
import struct
import sys

HERE = Path(__file__).resolve().parent
CONTRACT = runpy.run_path(str(HERE / 'ee-capability-contract.py'))
BACKUP_SHA = '9d1e03129a8216c101f653acd406c890c8488e5440c0892ec3dda6f5e0e0da92'
BANK_SHA = '657dc090bf08010c0a079fc40080270989fe979c734de86570dc78e56de0feaf'
BANK_OFFSET = 970752


def make_envelope(result, config, generation):
    if type(generation) is not int or not 0 < generation < 2**64:
        raise ValueError('Explicit positive uint64 launch generation required')
    if (result['backup_sha256'] != BACKUP_SHA or result['cp_bank_sha256'] != BANK_SHA
            or result['cp_bank_offset'] != BANK_OFFSET or result['unknown']):
        raise ValueError('Complete current-file/bank/record identity mismatch')
    records = result['records']
    if len(config) != 4 or len(records[0x30162]) != 64 or len(records[0x30a01]) != 4:
        raise ValueError('Required current CP property size mismatch')
    groups = CONTRACT['parse_keymap'](records[0x1120000])
    rows = groups.get(1)
    if not rows:
        raise ValueError('Actual ADC group 1 missing')
    raw = {'01120000': records[0x1120000], '00030162': records[0x30162],
           '00030a01': records[0x30a01], '0092001c': config}
    return dict(schema=1, profile='virtual-normal-wake-cold-v1', generation=generation,
                backup_sha256=BACKUP_SHA, backup_bytes=result['backup_bytes'],
                cp_bank_sha256=BANK_SHA, cp_bank_offset=BANK_OFFSET,
                cp_sha256=CONTRACT['CP_SHA'], keymap_group=1, rows_hex=rows.hex(),
                rows_sha256=hashlib.sha256(rows).hexdigest(),
                records={k: dict(bytes=len(v), hex=v.hex(), sha256=hashlib.sha256(v).hexdigest())
                         for k, v in raw.items()},
                object_10bf=(struct.unpack('<I', config)[0] >> 2) & 1,
                source='verified offline complete AP+CP Backup; unchanged raw records',
                original_cp_runtime_consumed=False, actual_native_registered=False,
                notification_published=False, current_adc_supplied=False)


def prepare(backup, vendor, generation):
    result = CONTRACT['read_backup'](backup, BACKUP_SHA, vendor, cp_bank_offset=BANK_OFFSET)
    data = Path(backup).read_bytes()
    # Recheck the bytes passed to the existing property parser; never mix file generations.
    if hashlib.sha256(data).hexdigest() != BACKUP_SHA:
        raise ValueError('Backup changed during offline extraction')
    if result['cp_bank_sha256'] != BANK_SHA:
        raise ValueError('Current CP bank SHA mismatch')
    old = list(sys.path)
    try:
        sys.path.insert(0, str(Path(vendor).resolve()))
        from pmca.backup import BackupFile
        bank = BackupFile(io.BytesIO(data[BANK_OFFSET:]))
        config = bank.getProperty(0x0092001c).data
    finally:
        sys.path[:] = old
    return make_envelope(result, config, generation)


def render_header(e):
    """Private compile input; adapter must hash-bind this to its launch receipt."""
    def arr(name, data):
        return 'static const uint8_t ' + name + '[]={' + ','.join(str(x) for x in data) + '};\n'
    r = e['records']
    def field(k):
        return '{' + ','.join(str(x) for x in bytes.fromhex(r[k]['hex'])) + '}'
    return ('/* PRIVATE generated raw input; no ADC or native registration. */\n'
            '#include "ee-normal-wake-cold.h"\n' + arr('ee_nwc_prepared_rows', bytes.fromhex(e['rows_hex'])) +
            'static const struct ee_nwc_assets ee_nwc_prepared_assets={\n'
            ' .pid=0, .generation=UINT64_C(' + str(e['generation']) + '),\n'
            ' .backup_sha256=EE_NWC_BACKUP_SHA, .cp_bank_sha256=EE_NWC_BANK_SHA,\n'
            ' .cp_sha256=EE_NWC_CP_SHA, .cp_bank_offset=970752, .verified=1, .keymap_group=1,\n'
            ' .rows=ee_nwc_prepared_rows, .rows_bytes=sizeof(ee_nwc_prepared_rows),\n'
            ' .backup_00030162=' + field('00030162') + ',\n'
            ' .policy_00030a01=' + field('00030a01') + ',\n'
            ' .config_0092001c=' + field('0092001c') + '\n};\n')


def private_write(path, data):
    path = Path(path)
    # Exclusive creation preserves previous failed evidence and enforces private mode at open.
    with path.open('xb') as stream:
        path.chmod(0o600)
        stream.write(data)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--backup', type=Path, required=True)
    parser.add_argument('--vendor', type=Path, required=True)
    parser.add_argument('--generation', type=int, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--header', type=Path)
    args = parser.parse_args()
    envelope = prepare(args.backup, args.vendor, args.generation)
    private_write(args.output, (json.dumps(envelope, indent=2) + '\n').encode())
    if args.header:
        private_write(args.header, render_header(envelope).encode('ascii'))
    print(json.dumps(dict(output=str(args.output), generation=args.generation,
                         rows_bytes=len(bytes.fromhex(envelope['rows_hex'])),
                         original_cp_runtime_consumed=False, notification_published=False)))


if __name__ == '__main__':
    main()
