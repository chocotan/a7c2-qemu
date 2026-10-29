#!/usr/bin/env python3
"""Read-only verification of the Gamma/ADR correction; no target execution."""
import argparse
import hashlib
import json
from pathlib import Path
import struct

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--cp', type=Path, required=True)
args = parser.parse_args()
raw = args.cp.read_bytes()
if len(raw) != 18090880 or hashlib.sha256(raw).hexdigest() != 'f5a477588698ef965748903b8959a39ce4f59ffd4aee4d4234ef1670f56a1428':
    raise SystemExit('Unsupported CP identity')
BASE = 0x108000


def word(address):
    return struct.unpack_from('<I', raw, address - BASE)[0]


for j in range(74):
    address = word(0x1109230 + j * 4)
    samples = struct.unpack_from('<1025I', raw, address - BASE)
    if samples[0] != 0 or samples[-1] != 0x1fffe or any(a > b for a, b in zip(samples, samples[1:])):
        raise SystemExit(f'Curve mismatch at {address:#x}')
for address, target, text in ((0x3642d0, 0x3642e0, b'CheckSetImageSensorBarrier\0'),
                               (0x35bf42, 0x35bf50, b'FW: SET_IMAGE_SENSOR_BARRIER[%d]\0')):
    opcode = struct.unpack_from('<H', raw, address - BASE)[0]
    if opcode & 0xf800 != 0xa000 or ((address + 4) & ~3) + (opcode & 255) * 4 != target:
        raise SystemExit('Thumb ADR16 mismatch')
    if raw[target - BASE:target - BASE + len(text)] != text:
        raise SystemExit('String mismatch')
for address, target in ((0x10fbdc4, 0x35bf21), (0x10fbdd0, 0x3642b1)):
    if word(address) != target:
        raise SystemExit('Registered function pointer mismatch')
name = raw[0xf90472 - BASE:].split(b'\0', 1)[0]
if b'GammaTable::GetContrastGammaTable' not in name:
    raise SystemExit('Gamma diagnostic name mismatch')
print(json.dumps({'scope': 'static Gamma curves, direct ADR16 strings and registered barrier functions',
                  'verified': True, 'sensor_startup_verified': False, 'capture_verified': False}))
