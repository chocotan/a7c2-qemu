#!/usr/bin/env python3
"""Verify conversion callback selection and its static flag notification path."""
import hashlib
import json
import struct
from pathlib import Path

from elftools.elf.elffile import ELFFile
from verify_liro_event_api import check as check_api

ROOT = Path(__file__).resolve().parents[2]/'runtime/analysis/menu-root'
KVA = 0xffffffc001000000


def main():
    check_api()
    image = (ROOT/'system/av-cam.bin').read_bytes()
    assert hashlib.sha256(image).hexdigest() == '90343f5f2edc0393ad8809d907cfe648dfd3a82ce0ef39cf06167929d8955096'

    def pin(address, value):
        expected = bytes.fromhex(value)
        assert image[address:address+len(expected)] == expected, hex(address)

    def branch(address, target):
        word, = struct.unpack_from('<I', image, address)
        assert word & 0xfc000000 in (0x14000000, 0x94000000)
        immediate = word & 0x3ffffff
        if immediate & 0x2000000:
            immediate -= 0x4000000
        assert address+4*immediate == target, hex(address)

    callbacks = (0x53cd4, 0x53cfc, 0x53c5c, 0x53c84, 0x53cac,
                 0, 0, 0, 0, 0, 0x53c34)
    expected = tuple(KVA+x if x else 0 for x in callbacks)
    assert struct.unpack_from('<11Q', image, 0x30b310) == expected
    pin(0x53800, 'e9838052')  # accepted-ID bitmask 0x41f
    pin(0x596a8, 'c88a4079a90e40b9a8120079')
    branch(0x59818, 0x53c08)
    pin(0x5981c, '80e200f9')  # selected callback -> driver input+1c0
    pin(0x649e4, '88e240f9689e00f9')  # input+1c0 -> submission block+138
    pin(0x64a0c, '229c40f9')  # load callback value, not address-of field
    pin(0x2d835c, 'e80306aae60307aae8a000f9')  # callback -> operation record+140
    for callback in callbacks:
        if not callback:
            continue
        pin(callback+4, 'e80315321f000071e90316323301881a')
        branch(callback+0x14, 0x2edcc)
        branch(callback+0x24, 0x2e980)
    with (ROOT/'usr/kmod/liro.ko').open('rb') as stream:
        elf = ELFFile(stream)
        symbols = elf.get_section_by_name('.symtab')
        api = {r['r_offset']: symbols.get_symbol(r['r_info_sym']).name
               for r in elf.get_section_by_name('.rela.init.data').iter_relocations()}
    assert api[0xf0] == 'set_flg' and 0xf0+0x48 == 0x138
    assert api[0x290] == 'sns_ctx' and 0x290+0x48 == 0x2d8
    print(json.dumps({
        'scope': 'static selection, callback storage and flag interface only',
        'supported_flag_ids': [1, 2, 3, 4, 5, 11],
        'callback_parameter_path': 'input+1c0 -> block+138 value -> operation+140',
        'callback_status_zero': 'set_flg(same ID,0x400)',
        'callback_status_nonzero': 'set_flg(same ID,0x800)',
        'helper_before_flag': 'sns_ctx; result ignored, not a proved memory barrier',
        'actual_callback_invocation_or_pixels_verified': False,
        'capture_verified': False,
    }, indent=2))


if __name__ == '__main__':
    main()
