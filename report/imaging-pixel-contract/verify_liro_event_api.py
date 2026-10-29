#!/usr/bin/env python3
"""Resolve original LIRO flag API slots from loader copy and ELF relocations."""
import hashlib
import json
import struct
from pathlib import Path

from elftools.elf.elffile import ELFFile

ROOT = Path(__file__).resolve().parents[2]/'runtime/analysis/menu-root'


def check():
    module = ROOT/'usr/kmod/liro.ko'
    image = (ROOT/'system/av-cam.bin').read_bytes()
    assert hashlib.sha256(module.read_bytes()).hexdigest() == 'b4bd80cc614751e0092ee19e89cb90632db580bc01f23f1a1df23544e9b10186'
    assert hashlib.sha256(image).hexdigest() == '90343f5f2edc0393ad8809d907cfe648dfd3a82ce0ef39cf06167929d8955096'
    with module.open('rb') as stream:
        elf = ELFFile(stream)
        symbols = elf.get_section_by_name('.symtab')
        init_text = elf.get_section_by_name('.init.text').data()
        text = elf.get_section_by_name('.text').data()
        api = {r['r_offset']: symbols.get_symbol(r['r_info_sym']).name
               for r in elf.get_section_by_name('.rela.init.data').iter_relocations()}
        relocations = {r['r_offset']: r for r in elf.get_section_by_name('.rela.init.text').iter_relocations()}
        src = symbols.get_symbol(relocations[0x598]['r_info_sym'])
        assert elf.get_section(src['st_shndx']).name == '.init.data'
        assert relocations[0x598]['r_addend'] == 0
        assert symbols.get_symbol(relocations[0x4c4]['r_info_sym']).name == 'memcpy'
        assert elf.get_section_by_name('.init.data')['sh_size'] == 0x698
    # Loader copies exactly the source API array into image.API+0x48.
    assert init_text[0x4b0:0x4c8] == bytes.fromhex('742a40f92107005802d380d2801240f90020019100000094')
    assert struct.unpack_from('<II', image, 8) == (0x4c49524f, 5)
    assert struct.unpack_from('<Q', image, 0x20)[0] == 0xffffffc0010001a4
    assert api[0xf8] == 'clr_flg' and 0xf8+0x48 == 0x140
    assert api[0x100] == 'twai_flg' and 0x100+0x48 == 0x148
    assert image[0x2e994:0x2e9a8] == bytes.fromhex('88feffd008010091081140f902a140f940001fd6')
    assert image[0x2e9a8:0x2e9bc] == bytes.fromhex('88feffd008010091081140f905a540f9a0001fd6')
    # clr_flg's actual operation is flags &= supplied_mask.
    assert text[0x47a4:0x47b0] == bytes.fromhex('431440b96300140a431400b9')
    # twai_flg mode 1 tests non-empty intersection and stores the flags word.
    assert text[0x4830:0x4848] == bytes.fromhex('bf060071c1020054201440b91f03006a60020054e00200b9')
    return {'abi_static_symbol_binding_verified': True,
            'api_prefix_bytes': 0x48, 'copied_api_bytes': 0x698,
            'slot_0x140': 'clr_flg (flags &= mask)',
            'slot_0x148': 'twai_flg (mode1: any requested bit)',
            'runtime_module_or_conversion_executed': False,
            'timeout_unit_verified': False, 'capture_verified': False}


if __name__ == '__main__':
    print(json.dumps(check(), indent=2))
