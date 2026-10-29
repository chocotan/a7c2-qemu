#!/usr/bin/env python3
"""Read-only verification and bounded reference discovery in the public kernel."""
import hashlib
import json
import struct
from pathlib import Path

from capstone import Cs, CS_ARCH_ARM64, CS_MODE_LITTLE_ENDIAN

OUT = Path(__file__).resolve().parent
ROOT = OUT.parents[2]
KERNEL = ROOT / 'runtime/analysis/unpacked/firmware.tar_unpacked/0700_part_image/dev/nflasha3_unpacked/vmlinux.bin'
BASE = 0xffffff8008080000
EXPECTED = '620a6a3c2b4f09a3696f2fbf06bab98b49be5eaad6bdb366a1f33319fcb6e9d2'
PINS = {
    0x2a253c: '1f100071',  # notify callback controller bound
    0x2a2558: '81000035',  # nonzero event selects connected branch
    0x2a2574: '42001f32',  # flags |= 2
    0x2a257c: '020400b9',  # controller flags store
    0x31c6e0: '40504039',  # parser reads ASCII payload, not mode array
    0x31c6ec: '200800b9',  # writes timer/pulse state +0x38
    0x31c788: '21190090',
    0x31c78c: '21203b91',
    0x31c790: '20d860b8',  # exported pcie_aspm_policy(id), not role
    0x31c884: '135000f9',  # global callback registration
    0x31c8c8: '40003fd6',  # replay cached nonzero state to callback
    0x31d7ec: '331040f9',  # kernel_param.arg
    0x31d7f0: '730202cb',  # arg - policy array
    0x31d7f4: '73fe4293',  # element index = difference / sizeof(u32)
    0x31d808: '04b6fb97',  # parse integer
    0x31d828: '547dfc97',  # normal policy API
    0x23cdd4: 'ff830394',  # API calls exact writer
    0x31ddf0: '417820b8',  # policy[id] = w1
    0x31de58: '34d833b8',  # cached notification state[id] = w20
    0x31de68: '40003fd6',  # notify(id, state)
    0x249504: '43520394',  # second notification producer, state not resolved
    0x24a59c: '21008052',  # connected notification state = 1
    0x24a5a0: '1c4e0394',  # connected notification producer
    0x5cbeac: '6742f597',  # callback registration, coordinator's existing edge
}


def main():
    data = KERNEL.read_bytes()
    assert len(data) == 6610952, len(data)
    digest = hashlib.sha256(data).hexdigest()
    assert digest == EXPECTED, digest
    for offset, expected in PINS.items():
        assert data[offset:offset+len(bytes.fromhex(expected))].hex() == expected, hex(offset)
    assert struct.unpack_from('<5I', data, 0x640ec8) == (1, 1, 1, 1, 1)
    def ptr(offset, target):
        assert struct.unpack_from('<Q', data, offset)[0] == BASE + target, hex(offset)
    def string(offset, text):
        encoded = text.encode('ascii') + b'\0'
        assert data[offset:offset+len(encoded)] == encoded, hex(offset)
    for index in range(5):
        entry = 0x5ac3c8 - index * 0x28
        name = 0x477ed8 - index * 0x10
        ptr(entry, name)
        string(name, f'pcie.aspm{index}')
        ptr(entry + 0x10, 0x477ee8)
        assert struct.unpack_from('<Q', data, entry + 0x18)[0] == 0xff0180
        ptr(entry + 0x20, 0x640ec8 + index * 4)
    ptr(0x477ef0, 0x31d7d8)
    for record, function, nameoff, name in [
        (0x57fe60, 0x31c780, 0x5a3db0, 'pcie_aspm_policy'),
        (0x57fe70, 0x23cd78, 0x59c2eb, 'pcie_aspm_set_domain_policy'),
        (0x57ff50, 0x31c848, 0x5a3d59, 'pcie_host_register_cb'),
    ]:
        ptr(record, function)
        ptr(record + 8, nameoff)
        string(nameoff, name)
    cs = Cs(CS_ARCH_ARM64, CS_MODE_LITTLE_ENDIAN)
    evidence = []
    scopes = [(0x2a2538, 0x2a25f4), (0x31c440, 0x31c744),
              (0x31c848, 0x31c8e8), (0x31d7d8, 0x31d86c),
              (0x31ddd0, 0x31de10), (0x31de10, 0x31de88)]
    for start, end in scopes:
        evidence.append(f'SELECTED_FUNCTION_SCOPE {start:#x}..{end:#x}')
        evidence.extend(f'{i.address:08x}: {i.bytes.hex()} {i.mnemonic} {i.op_str}'
                        for i in cs.disasm(data[start:end], start))
    (OUT / 'raw-evidence.txt').write_text('\n'.join(evidence) + '\n')
    lines = []
    # Only locate references to the known mode page; no general function survey.
    for off in range(0, 0x430000, 4):
        ins, = struct.unpack_from('<I', data, off)
        if ins & 0x9f000000 != 0x90000000:
            continue
        imm = ((ins >> 29) & 3) | (((ins >> 5) & 0x7ffff) << 2)
        if imm & (1 << 20):
            imm -= 1 << 21
        target = (off & ~0xfff) + (imm << 12)
        if target != 0x640000:
            continue
        decoded = list(cs.disasm(data[off:off+48], off))
        if not any('#0xec8' in i.op_str for i in decoded):
            continue
        lines.append('MODE_PAGE_REFERENCE ' + hex(off))
        lines.extend(f'{i.address:08x}: {i.bytes.hex()} {i.mnemonic} {i.op_str}' for i in decoded)
    # Exact function/data pointers are evidence locations, not inferred callers.
    for target in [0x640ec8, 0x31c848, 0x2a2538]:
        needle = struct.pack('<Q', BASE + target)
        at = 0
        while (at := data.find(needle, at)) >= 0:
            lines.append(f'ABS_POINTER target={target:#x} at={at:#x}')
            at += 1
    (OUT / 'references.txt').write_text('\n'.join(lines) + '\n')
    result = {'status': 'PASS_RAW_PINS_AND_PARAMETER_IDENTITY_ONLY', 'activation': 'UNRESOLVED', 'size': len(data),
              'sha256': digest, 'pins': {hex(k): v for k, v in PINS.items()},
              'aspm_policy_initial': [1] * 5, 'parameters': [f'pcie.aspm{i}' for i in range(5)],
              'exact_writer': '0x31ddf0', 'normal_api': 'pcie_aspm_set_domain_policy@0x23cd78',
              'selected_function_scopes': [[hex(a), hex(z)] for a, z in scopes]}
    (OUT / 'aspm-verification.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
