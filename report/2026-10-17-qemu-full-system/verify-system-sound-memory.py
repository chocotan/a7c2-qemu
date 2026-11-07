#!/usr/bin/env python3
"""Check original bytes in independently exported, VM-owned sound memory."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import struct

BYTES = 0x10340
CAPACITY = 0x20000
PHYSICAL = 0x41d000000
BUS = 0x1d000000
AUDIO_PHYS64 = 0x81d000000
SHA256 = '5d94c660c48afde364fbb936105abdaf5c35f8bf8fc0bfd6945cd12146f6824a'


def require(condition, why):
    if not condition:
        raise ValueError(why)


def verify(run):
    console = (run / 'console.log').read_bytes()
    result = json.loads((run / 'result.json').read_text())
    identity = json.loads((run / 'inputs.json').read_text())
    require(identity['experiment'].get('system_sound_memory') is True, 'Sound owner was not explicitly enabled')
    require(result.get('terminal_evidence_checked') is True, 'Terminal evidence was not checked')
    require(result['terminal_console_sha256'] == hashlib.sha256(console).hexdigest(), 'Terminal console changed')
    require(result.get('system_sound_memory_exported') is True, 'No independent memory export')
    dtb = (run / 'virt.dtb').read_bytes()
    header = struct.unpack_from('>10I', dtb)
    require(header[0] == 0xd00dfeed and header[1] <= len(dtb), 'Invalid retained board DTB')
    cursor, reservations = header[4], []
    while cursor + 16 <= len(dtb):
        start, size = struct.unpack_from('>QQ', dtb, cursor)
        cursor += 16
        if start == size == 0:
            break
        reservations.append((start, size))
    require(reservations.count((PHYSICAL, CAPACITY)) == 1, 'Sound region is not uniquely reserved in loaded DTB')
    rows = [line for line in console.decode(errors='replace').splitlines()
            if line.startswith('FULL_SOUND_OWNER_READY ')]
    require(bool(rows), 'No original guest owner readback marker')
    owner = dict(re.findall(r'(\w+)=([^\s]+)', rows[0]))
    require(int(owner['physical'], 0) == PHYSICAL and int(owner['virtual_bus'], 0) == BUS,
            'Guest owner address pair differs')
    require(int(owner['audio_phys64'], 0) == AUDIO_PHYS64, 'ADF phys64 address differs')
    require(int(owner['capacity']) == CAPACITY and int(owner['bytes']) == BYTES, 'Guest capacity differs')
    dump = (run / 'system-sound-memory.bin').read_bytes()
    require(len(dump) == CAPACITY, 'Independent export has wrong length')
    digest = hashlib.sha256(dump[:BYTES]).hexdigest()
    require(digest == SHA256, 'Export differs from original SysSound')
    require(not any(dump[BYTES:]), 'Owned padding is not zero')
    h = 0xcbf29ce484222325
    for byte in dump[:BYTES]:
        h = ((h ^ byte) * 0x100000001b3) & ((1 << 64) - 1)
    require(owner['fnv64'] == f'{h:016x}', 'Guest/independent content digests disagree')
    return {'system_sound_memory_verified': True, 'physical': hex(PHYSICAL),
            'virtual_bus': hex(BUS), 'audio_phys64': hex(AUDIO_PHYS64), 'capacity': CAPACITY, 'bytes': BYTES,
            'source_sha256': digest, 'fnv64': f'{h:016x}',
            'console_sha256': hashlib.sha256(console).hexdigest(),
            'original_allocator_verified': False, 'audio_output_verified': False,
            'camera_startup_verified': False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('run', type=Path)
    args = parser.parse_args()
    try:
        proof = verify(args.run)
    except (OSError, ValueError, KeyError) as error:
        proof = {'system_sound_memory_verified': False, 'error': str(error),
                 'audio_output_verified': False, 'camera_startup_verified': False}
    (args.run / 'system-sound-memory-proof.json').write_text(json.dumps(proof, indent=2) + '\n')
    print(json.dumps(proof, sort_keys=True))
    return 0 if proof['system_sound_memory_verified'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
