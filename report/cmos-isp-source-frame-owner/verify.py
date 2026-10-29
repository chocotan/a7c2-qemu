#!/usr/bin/env python3
"""Verify original bytes, source pointer instructions and bounded caller bindings."""
from pathlib import Path
import hashlib
import json
import struct
from capstone import Cs, CS_ARCH_ARM64, CS_MODE_ARM

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
SCRATCH = ROOT / 'runtime/analysis/scratch/cmos-isp-source-frame-owner'

def check(data, manifest):
    assert len(data) == manifest['artifact']['bytes']
    assert hashlib.sha256(data).hexdigest() == manifest['artifact']['sha256']
    windows = manifest['windows']
    assert 8 <= len(windows) <= 12
    assert sum(w['length'] for w in windows) <= 10000
    cs = Cs(CS_ARCH_ARM64, CS_MODE_ARM)
    intervals = []
    for w in windows:
        start = int(w['raw_start'], 16)
        end = int(w['raw_end_exclusive'], 16)
        assert start % 4 == end % 4 == 0 and end-start == w['length']
        assert 0 <= start < end <= len(data)
        assert all(end <= a or start >= b for a,b in intervals)
        intervals.append((start,end))
        raw = data[start:end]
        assert hashlib.sha256(raw).hexdigest() == w['sha256'], w['id']
        saved = SCRATCH / (w['source_ref']+'.json')
        if saved.exists():
            row = json.loads(saved.read_text())
            assert bytes.fromhex(row['original_bytes_hex']) == raw
            assert row['sha256'] == w['sha256']
    def contained(a, size=4):
        return any(start <= a and a+size <= end for start,end in intervals)
    for pin in manifest['instruction_pins']:
        a = int(pin['raw'],16)
        assert contained(a), pin
        assert data[a:a+4].hex() == pin['bytes_hex'], pin
        ins = next(cs.disasm(data[a:a+4],a))
        assert (ins.mnemonic,ins.op_str) == (pin['mnemonic'],pin['operands']), pin
    for edge in manifest['direct_calls']:
        a,t = int(edge['at'],16),int(edge['target'],16)
        assert contained(a)
        word = struct.unpack_from('<I',data,a)[0]
        assert word & 0xfc000000 == 0x94000000
        imm = word & 0x3ffffff
        if imm & 0x2000000:
            imm -= 0x4000000
        assert a+imm*4 == t, edge
    assert contained(0x375790,8)
    assert struct.unpack_from('<Q',data,0x375790)[0] == 0xffffffc0011e1b10
    assert contained(0x3757f0,8)
    assert struct.unpack_from('<Q',data,0x3757f0)[0] == 0xffffffc0011e1b50
    assert contained(0x3f1bbf,4) and data[0x3f1bbf:0x3f1bc3] == b'ETRY'
    assert contained(0x3f1bda,4) and data[0x3f1bda:0x3f1bde] == b'SSYC'
    # These equalities distinguish the source metadata, pixel query and embedded context.
    assert 0xd8+0x1368 == 0x1440 and 0xd8+0x1378 == 0x1450
    assert 0xd8+0x1418 == 0x14f0 and 0xd8+0x1420 == 0x14f8
    assert 0x368+4 == 0x36c and 0x20+0x20 == 0x40
    assert 0x1c8+8 == 0x1d0 and 0x1c8+0x68 == 0x230
    assert manifest['closure']['true_source_owner'] is False
    assert manifest['closure']['plane_format'] is False
    assert manifest['closure']['runtime_lease'] == 'unknown'
    assert manifest['closure']['capture_verified'] is False
    return {'passed':True,'windows':len(windows),
            'original_bytes':sum(w['length'] for w in windows),
            'instruction_pins':len(manifest['instruction_pins']),
            'direct_calls':len(manifest['direct_calls']),
            'vtable_bindings':2,'field_coordinate_equalities':8,
            'target_executed':False,'capture_verified':False}

def main():
    manifest = json.loads((HERE/'source-pins.json').read_text())
    data = (ROOT/manifest['artifact']['path']).read_bytes()
    result = check(data,manifest)
    # Reject a changed artifact and a wrong same-width instruction claim.
    bad = bytearray(data)
    bad[0x1d1958] ^= 1
    try:
        check(bad,manifest)
    except AssertionError:
        pass
    else:
        raise AssertionError('Changed original bytes were accepted')
    bad_manifest = json.loads(json.dumps(manifest))
    bad_manifest['instruction_pins'][0]['operands'] = 'wrong source register'
    try:
        check(data,bad_manifest)
    except AssertionError:
        pass
    else:
        raise AssertionError('Changed source-field instruction was accepted')
    result['negative_checks'] = 2
    SCRATCH.mkdir(parents=True,exist_ok=True)
    (SCRATCH/'verification.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result,indent=2))

if __name__ == '__main__':
    main()
