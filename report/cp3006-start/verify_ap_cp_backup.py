#!/usr/bin/env python3
"""Verify AP Backup record selection; not CP startup loading or DMA execution."""
import hashlib
import json
import struct
from pathlib import Path

from elftools.elf.elffile import ELFFile

ROOT = Path(__file__).resolve().parents[2]/'runtime/analysis/menu-root'
MODULE = ROOT/'usr/kmod/backup.ko'
SEED = ROOT/'seed-backup.bin'


def main():
    raw = MODULE.read_bytes()
    seed = SEED.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == '167715ebd8086b0751e95396ecc214c4d65ec54e11a9f2737a05664e03ad237b'
    assert hashlib.sha256(seed).hexdigest() == '3dab4f0d6b7790f4a7798034b57f43bfe3255c39dc6da2897fc288b3a218fe47'
    with MODULE.open('rb') as stream:
        elf = ELFFile(stream)
        text = elf.get_section_by_name('.text').data()
        symbols = elf.get_section_by_name('.symtab')
        relocations = {r['r_offset']: symbols.get_symbol(r['r_info_sym']).name
                       for r in elf.get_section_by_name('.rela.text').iter_relocations()}
    pins = {
        0x59a0: '000443290000018b00fc3f9100cc7492a500008b',
        0x7044: '21008052',
        0x7054: '800080529f820339808603399f8a0339',
        0x7068: '21008052',
        0x7074: 'a00240b9',
        0x7080: 'e00315aa',
        0x71e8: '0286a0d2',
        0x72e4: '22008052',
    }
    for address, expected in pins.items():
        value = bytes.fromhex(expected)
        assert text[address:address+len(value)] == value, hex(address)
    calls = {0x59b8: 'Data_GetFormatRevision', 0x7040: 'Data_GetHeader',
             0x7048: 'Data_getAdrs', 0x706c: 'Data_getSize',
             0x7078: 'arch_p32_to_p64', 0x7084: 'arch_va_to_phys',
             0x70bc: 'pcidma_transfer_async', 0x7220: 'pcidma_transfer_async',
             0x7318: 'pcidma_transfer_async'}
    for address, name in calls.items():
        assert relocations[address] == name, (hex(address), name)
    assert relocations[0x7198] == 'backupfile_cb_getcp'
    direct_dma_calls = sorted(address for address, name in relocations.items()
                              if name == 'pcidma_transfer_async')
    assert direct_dma_calls == [0x70bc, 0x7220, 0x7318]
    header_size, payload_size = struct.unpack_from('<II', seed, 0x18)
    second = (header_size+payload_size+0xfff) & ~0xfff
    assert second == 0xed000 and seed[second+0xc:second+0xf] == b'BK4'
    record_size = sum(struct.unpack_from('<II', seed, second+0x18))
    assert record_size == 1419512 and second+record_size == len(seed)
    assert struct.unpack_from('<I', seed, second)[0] == 0x04000000
    print(json.dumps({
        'scope': 'AP ET_REL functions and public input layout only',
        'ap_type1_record_offset': hex(second), 'record_bytes': record_size,
        'record_first_word': '0x04000000',
        'backupfile_get_cp_data_direct_dma_call': 'text+0x70bc',
        'dma_controller': 0, 'dma_channel': 4, 'dma_direction': 'PCI-to-AP',
        'cp_startup_upload_or_active_primary_source_verified': False,
        'dma_executed': False, 'capture_verified': False,
    }, indent=2))


if __name__ == '__main__':
    main()
