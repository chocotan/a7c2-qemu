#!/usr/bin/env python3
"""Read-only verification of the AP 032b call chain; requires pyelftools."""
import argparse
import hashlib
import json
import struct
from elftools.elf.elffile import ELFFile

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--ap', required=True, help='Official appFw.so; never modified')
args = parser.parse_args()
with open(args.ap, 'rb') as stream:
    segments = [dict(s.header) for s in ELFFile(stream).iter_segments()
                if s['p_type'] == 'PT_LOAD']
    stream.seek(0)
    raw = stream.read()
if len(raw) != 99960744 or hashlib.sha256(raw).hexdigest() != '2ea02f7ecbc5bb917316fe8ef4ce5ffd87eb66efaae78ba2ce11420552df539b':
    raise SystemExit('Unsupported AP identity')


def at(va, size=4):
    segment = next(s for s in segments
                   if s['p_vaddr'] <= va and va + size <= s['p_vaddr'] + s['p_filesz'])
    offset = segment['p_offset'] + va - segment['p_vaddr']
    return raw[offset:offset + size]


def signed(value, width):
    return value - (1 << width) if value & (1 << (width - 1)) else value


for source, target in ((0x3485b74, 0x34c7d98), (0x34b05c0, 0x34c7d98),
                       (0x34c7dc0, 0x34f2f84), (0x34f3004, 0x34e552c)):
    word, = struct.unpack('<I', at(source))
    if word & 0xfc000000 != 0x94000000 or source + signed(word & 0x3ffffff, 26) * 4 != target:
        raise SystemExit(f'BL mismatch at {source:#x}')

for adrp, add, text in ((0x3485b80, 0x3485b84, b'Failure MSGID_START_SYSTEM_SOUND_CMD(BEEP_ID_REC_START)'),
                        (0x34b05cc, 0x34b05d0, b'Failure MSGID_START_SYSTEM_SOUND_CMD(BEEP_ID_REC_STOP)')):
    word, = struct.unpack('<I', at(adrp))
    following, = struct.unpack('<I', at(add))
    if word & 0x9f000000 != 0x90000000 or following & 0x7f000000 != 0x11000000:
        raise SystemExit('ADRP/ADD opcode mismatch')
    if word & 31 != (following >> 5) & 31:
        raise SystemExit('ADRP/ADD register mismatch')
    delta = signed(((word >> 5) & 0x7ffff) * 4 + ((word >> 29) & 3), 21)
    page = (adrp & ~4095) + delta * 4096
    address = page + (((following >> 10) & 4095) << (12 if following & (1 << 22) else 0))
    if at(address, len(text)) != text:
        raise SystemExit('Failure-string reference mismatch')

print(json.dumps({'scope': 'static AP 032b call chain and RECSTART/RECSTOP string references',
                  'verified': True, 'playback_verified': False, 'host_audio_verified': False}))
