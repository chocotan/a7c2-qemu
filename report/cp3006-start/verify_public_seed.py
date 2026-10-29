#!/usr/bin/env python3
"""Read only selected control/shadow keys from the pinned public ALLLANG seed.

Rejects other bytes before interpreting them; never opens a device, private
backup, live setting, or another path automatically. No writes or defaulting.
"""
import argparse
import hashlib
import json
from pathlib import Path
import struct


SIZE = 2390264
SHA256 = '3dab4f0d6b7790f4a7798034b57f43bfe3255c39dc6da2897fc288b3a218fe47'


def require(condition, message):
    if not condition:
        raise ValueError(message)


def verify(path, keys=(0x0051001d, 0x003100a6, 0x02a40000, 0x02a4000e)):
    with path.open('rb') as file:
        blob = file.read(SIZE + 1)
    require(len(blob) == SIZE and hashlib.sha256(blob).hexdigest() == SHA256,
            'not the supported immutable official ALLLANG seed')
    records = []
    for base in (0, 0xed000):
        require(blob[base + 12:base + 16] == b'BK4\0', 'unsupported record')
        sections, properties, offset, length, checksum = struct.unpack_from('<5I', blob, base + 16)
        size = offset + length
        record = blob[base:base + size]
        require(len(record) == size and (sum(record[:32]) + sum(record[36:])) & 0xffffffff == checksum,
                'record checksum/length mismatch')
        table = 0x100 + sections * 6
        require(table + properties * 6 <= offset <= size, 'invalid metadata boundaries')
        values = {}
        for key in keys:
            section, index = key >> 16, key & 0xffff
            require(section < sections, 'section absent')
            count, first = struct.unpack_from('<HI', record, 0x100 + section * 6)
            require(first + count <= properties, 'invalid section')
            if index >= count:
                values[f'{key:08x}'] = {'present': False, 'reason': 'item outside section',
                                       'section_property_count': count}
                continue
            attr, pointer = struct.unpack_from('<HI', record, table + (first + index) * 6)
            if pointer == 0xffffffff:
                values[f'{key:08x}'] = {'present': False, 'reason': 'unmapped item'}
                continue
            size_value, at = pointer >> 24, pointer & 0xffffff
            maximum = size_value
            require(offset <= at < size, 'invalid data pointer')
            if size_value == 255:
                size_value = maximum = struct.unpack_from('<H', record, at)[0]
                at += 2
            elif not size_value:
                size_value, maximum = struct.unpack_from('<HH', record, at)
                at += 4
            require(size_value <= maximum and at + maximum <= size, 'invalid item size')
            data = record[at:at + size_value]
            value = {'present': True, 'bytes': size_value, 'attr': attr,
                     'file_offset': base + at, 'sha256': hashlib.sha256(data).hexdigest()}
            if size_value <= 16:
                value['data'] = data.hex()
            else:
                value['prefix_16_bytes'] = data[:16].hex()
            values[f'{key:08x}'] = value
        records.append({'offset': base, 'checksum_verified': True, 'keys': values})
    return {'verified': True, 'scope': 'selected keys in original public update seed only',
            'source_class': 'sony_original_ALLLANG', 'sha256': SHA256, 'records': records,
            'cp_runtime_loader_binding_proven': False, 'variant_default_proven': False,
            'cp3006_success_implemented': False}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--seed', type=Path, default=Path(__file__).resolve().parents[2] /
                        'runtime/analysis/menu-root/seed-backup.bin')
    args = parser.parse_args()
    print(json.dumps(verify(args.seed), indent=2))
