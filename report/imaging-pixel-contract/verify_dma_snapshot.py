#!/usr/bin/env python3
"""Original read_regs dispatch and snapshot-only entry, no firmware execution."""
import hashlib
from pathlib import Path
import struct
from elftools.elf.elffile import ELFFile

target = Path(__file__).resolve().parents[2]/'runtime/analysis/menu-root/kmod/dma330.ko'
assert hashlib.sha256(target.read_bytes()).hexdigest() == '9ba277f011b3ddcfbc3fa610d22b63ae3be1e0ded385b42ff2c7cf0a83e520ab'
with target.open('rb') as stream:
    elf = ELFFile(stream)
    text = elf.get_section_by_name('.text').data()
    symbols = elf.get_section_by_name('.symtab')
    reloc = {r['r_offset']: r for r in elf.get_section_by_name('.rela.text').iter_relocations()}
    literal = reloc[0x2d30]
    symbol = symbols.get_symbol(literal['r_info_sym'])
    source = elf.get_section(symbol['st_shndx']).data()
    position = symbol['st_value']+literal['r_addend']
    assert source[position:position+11] == b'read_regs=\0'
    assert text[0x1ee8:0x1ef8] == bytes.fromhex('41720058e00316aa420180d200000094')
    assert symbols.get_symbol(reloc[0x1ef4]['r_info_sym']).name == 'strncmp'
    # CBZ comparison result enters 20a8; integer parser base is zero.
    assert struct.unpack_from('<I', text, 0x1ef8)[0] == 0x34000d80
    assert symbols.get_symbol(reloc[0x20bc]['r_info_sym']).name == 'simple_strtoul'
    assert text[0x21e0:0x21f4] == bytes.fromhex('0000805287f7ff972000805285f7ff97f4feff17')
    for call in (0x21e4, 0x21ec):
        word = struct.unpack_from('<I', text, call)[0]
        immediate = word & 0x3ffffff
        if immediate & 0x2000000:
            immediate -= 0x4000000
        assert call+immediate*4 == 0
    assert text[:0x20] == bytes.fromhex('e503002a043981d2c3100058a10c049b221040f9420040b99f3d03d5222800b9')
print('PASS original read_regs prefix -> chips0/1 snapshot entry; no DMA request producer')
