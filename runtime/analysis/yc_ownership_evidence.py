"""Bind original op28 snapshots to the injector's original allocation; no retirement claim."""
import hashlib
import json
from pathlib import Path
import re
import struct


IDENTITY = r'tag=(0x[0-9a-f]+) handle=(0x[0-9a-f]+) addr=(0x[0-9a-f]+) capacity=(0x[0-9a-f]+) type=(0x[0-9a-f]+)'


def verify_build(source, module):
    """An old installed injector cannot silently omit a requested observation."""
    source, module = Path(source), Path(module)
    receipt = json.loads((source/'verification.json').read_text())
    expected = {name: hashlib.sha256((source/name).read_bytes()).hexdigest()
                for name in ('yc_inject.c','unit-info.h','descriptor.S','build.sh','check_module.py')}
    if (receipt.get('sources_sha256') != expected or
            receipt.get('sha256') != hashlib.sha256(module.read_bytes()).hexdigest()):
        raise ValueError('Rebuild the YC injector before requesting ownership observation')
    return receipt


def verify(run):
    run = Path(run)
    text = (run/'console.log').read_text(errors='replace')
    allocations = re.findall(r'YCIN_DMM: type=0x431 handle=(0x[0-9a-f]+) addr=(0x[0-9a-f]+) len=(0x[0-9a-f]+)', text)
    result = dict(verified=False, scope='original DMM op28 count observations only',
                  retirement_verified=False, overwrite_authorized=False, snapshots=[])
    try:
        if len(allocations) != 1:
            raise ValueError('No unique original unit431 allocation')
        handle, address, capacity = (int(value, 16) for value in allocations[0])
        if not handle or not 0x400000000 <= address <= 0x500000000-capacity or capacity < 5184000:
            raise ValueError('Original allocation outside storage bounds')
        events = [line[line.index('YCIN_OWNERSHIP'):].strip() for line in text.splitlines()
                  if 'YCIN_OWNERSHIP' in line]
        if len(events) != 4:
            raise ValueError('Expected exactly two ordered requests and replies; failure/duplicate/partial evidence rejects')
        for index, tag in enumerate((0x4c01, 0x4c02)):
            request = re.fullmatch('YCIN_OWNERSHIP_REQUEST: '+IDENTITY, events[2*index])
            reply = re.fullmatch('YCIN_OWNERSHIP: '+IDENTITY+
                r' extents=(\d+) refs=(\d+) opens=(\d+) source=(0x[0-9a-f]+) bytes=(\d+) raw=([0-9a-f]{80}) retirement_verified=0',
                events[2*index+1])
            expected = (tag, handle, address, capacity, 0x431)
            if not request or not reply or tuple(int(v,16) for v in request.groups()) != expected or tuple(int(v,16) for v in reply.groups()[:5]) != expected:
                raise ValueError('Request/reply/allocation identity mismatch')
            extents, refs, opens = (int(v) for v in reply.groups()[5:8])
            source, length, raw = int(reply[9],16), int(reply[10]), bytes.fromhex(reply[11])
            opcode, status, echoed_tag = struct.unpack_from('<Hh2xH', raw)
            wire_counts = struct.unpack_from('<3H', raw, 8)
            wire_size, wire_type = struct.unpack_from('<2I', raw, 16)
            if ((source & 0x7fffffff) != 0x61003c or length != 40 or opcode != 0x8028 or status or
                    echoed_tag != tag or wire_counts != (extents, refs, opens) or
                    not 1 <= extents <= 12 or not 1 <= refs <= 255 or not 0 <= opens <= 255 or
                    wire_size != capacity or wire_type != 0x431):
                raise ValueError('Original op28 wire/printed fields disagree')
            result['snapshots'].append(dict(tag=tag, handle=handle, physical_address=address,
                capacity=capacity, type=wire_type, extents=extents, references=refs, opens=opens,
                raw_reply=raw.hex()))
        result['verified'] = True
    except (ValueError, struct.error) as error:
        result['error'] = str(error)
    (run/'yc-ownership-proof.json').write_text(json.dumps(result, indent=2)+'\n')
    return result
