#!/usr/bin/env python3
"""Check the original static conversion handoff, not executed pixel conversion."""
import hashlib
import json
import struct
from pathlib import Path

from verify_liro_event_api import check as check_event_api

IMAGE = Path(__file__).resolve().parents[2]/'runtime/analysis/menu-root/system/av-cam.bin'
SHA = '90343f5f2edc0393ad8809d907cfe648dfd3a82ce0ef39cf06167929d8955096'
KVA = 0xffffffc001000000


def main():
    raw = IMAGE.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == SHA

    def pin(address, value):
        expected = bytes.fromhex(value)
        assert raw[address:address+len(expected)] == expected, hex(address)

    def branch(address, target):
        word, = struct.unpack_from('<I', raw, address)
        assert word & 0xfc000000 in (0x14000000, 0x94000000), hex(address)
        immediate = word & 0x3ffffff
        if immediate & 0x2000000:
            immediate -= 0x4000000
        assert address+4*immediate == target, (hex(address), hex(target))

    pin(0x5a9b4, 'c81600f008c1309108410091680200f9')
    pin(0x562c0, '480040f9080940f9e00302aa00013fd6')
    assert struct.unpack_from('<Q', raw, 0x335c50)[0] == KVA+0x5a9e8
    assert struct.unpack_from('<Q', raw, 0x335c70)[0] == KVA+0x5d440
    assert raw[0x30bc60:0x30bc60+len(b'N3Sdt18ModuleResizeRotateE')] == b'N3Sdt18ModuleResizeRotateE'
    pin(0x5aa2c, '29020034')
    pin(0x5bf7c, '880240f9081940f9e00314aa00013fd6')
    for address, target in ((0x5aa80, 0x5b3e0), (0x5b460, 0x5bd6c),
                            (0x5d458, 0x599bc), (0x5bf98, 0x599fc),
                            (0x59a3c, 0x5a36c), (0x59a54, 0x59bf4),
                            (0x59c98, 0x592b0), (0x593c8, 0x647fc),
                            (0x64820, 0x649fc), (0x64a18, 0x2daf2c),
                            (0x593bc, 0x2e994), (0x59430, 0x598b4),
                            (0x598d0, 0x2e9a8)):
        branch(address, target)
    pin(0x598c0, 'e1071632e2030032e333009104c48952')
    pin(0x598e0, 'e837403928031037')
    pin(0x2e9b4, '05a540f9a0001fd6')
    event_api = check_event_api()
    print(json.dumps({
        'scope': 'original static vtable/call edges and post-submit branch only',
        'constructor': 'Kraw 0x5a9a8', 'vptr': 'KVA+0x335c40',
        'slot_0x10_target': 'Kraw 0x5a9e8',
        'factory_0x30_target': 'Kraw 0x5d440 -> ctor 0x599bc',
        'case_X10_zero_tail': '0x5b3e0',
        'driver_facing_entry': '0x649fc -> 0x2daf2c',
        'post_submit_check': '0x598b4 -> imported ABI slot 0x148',
        'check_arguments': {'mask': '0xc00', 'mode': 1, 'limit': 20000},
        'success_branch': 'rc==0 and output byte[1] bit2 set',
        'imported_ABI_static_symbol_verified': event_api['abi_static_symbol_binding_verified'],
        'runtime_ABI_binding_or_time_unit_verified': False,
        'pixel_layout_or_execution_verified': False, 'capture_verified': False,
    }, indent=2))


if __name__ == '__main__':
    main()
