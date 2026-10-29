#!/usr/bin/env python3
"""Verify public ALLLANG synchronous movie/Fsys bytes; never run firmware."""
import argparse
import hashlib
import json
from pathlib import Path

from elftools.elf.elffile import ELFFile

OWN = Path(__file__).resolve().parent


def verify(libraries):
    pins = json.loads((OWN / 'source-pins.json').read_text())
    windows = bindings = 0
    for name, identity in pins['artifacts'].items():
        path = libraries / name
        raw = path.read_bytes()
        if len(raw) != identity['bytes'] or hashlib.sha256(raw).hexdigest() != identity['sha256']:
            raise ValueError('public original identity mismatch: ' + name)
        with path.open('rb') as stream:
            elf = ELFFile(stream)
            if elf.elfclass != 64 or not elf.little_endian or elf['e_machine'] != 'EM_AARCH64':
                raise ValueError('AArch64 LE required')
            loads = [s for s in elf.iter_segments() if s['p_type'] == 'PT_LOAD']
            for pin in pins['windows']:
                if pin['artifact'] != name:
                    continue
                start, end = int(pin['start'], 16), int(pin['end'], 16)
                segments = [s for s in loads if s['p_vaddr'] <= start < end <= s['p_vaddr'] + s['p_filesz']]
                if len(segments) != 1:
                    raise ValueError('source window is not file-backed')
                offset = segments[0]['p_offset'] + start - segments[0]['p_vaddr']
                if hashlib.sha256(raw[offset:offset + end - start]).hexdigest() != pin['sha256']:
                    raise ValueError('source window mismatch: ' + pin['role'])
                windows += 1
            wanted = [p for p in pins['plt'] if p['artifact'] == name]
            symbols = elf.get_section_by_name('.dynsym')
            relocations = elf.get_section_by_name('.rela.plt')
            for pin in wanted:
                matches = [r for r in relocations.iter_relocations() if r['r_offset'] == int(pin['got'], 16)]
                if len(matches) != 1 or matches[0]['r_info_type'] != 1026 or matches[0]['r_addend']:
                    raise ValueError('PLT relocation mismatch')
                if symbols.get_symbol(matches[0]['r_info_sym']).name != pin['symbol']:
                    raise ValueError('PLT symbol mismatch')
                bindings += 1
    return {'source_verified': True, 'windows': windows, 'sync_plt_bindings': bindings,
            'capture_verified': False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('libraries', nargs='?', type=Path,
                        default=OWN.parents[1] / 'runtime/analysis/menu-root/usr/lib')
    print(json.dumps(verify(parser.parse_args().libraries), indent=2))


if __name__ == '__main__':
    main()
