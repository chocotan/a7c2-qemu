#!/usr/bin/env python3
"""Verify public original ELF pins and callback GOT binding; never execute firmware."""
import argparse
import hashlib
import json
from pathlib import Path
from elftools.elf.elffile import ELFFile

OWN = Path(__file__).resolve().parent


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('duplicate source-contract key: ' + key)
        result[key] = value
    return result


def verify(library_directory):
    pins = json.loads((OWN / 'source-pins.json').read_text(), object_pairs_hook=unique_object)
    windows, byte_count, bindings = 0, 0, 0
    for name, expected in pins['artifacts'].items():
        path = library_directory / name
        raw = path.read_bytes()
        if len(raw) != expected['bytes'] or hashlib.sha256(raw).hexdigest() != expected['sha256']:
            raise ValueError('original artifact identity mismatch: ' + name)
        with path.open('rb') as stream:
            elf = ELFFile(stream)
            if elf['e_machine'] != 'EM_AARCH64' or not elf.little_endian or elf.elfclass != 64:
                raise ValueError('original AArch64 LE ABI required')
            loads = [s for s in elf.iter_segments() if s['p_type'] == 'PT_LOAD']
            for pin in pins['windows']:
                if pin['artifact'] != name:
                    continue
                start, end = int(pin['start'], 16), int(pin['end'], 16)
                segments = [s for s in loads if s['p_vaddr'] <= start < end <= s['p_vaddr'] + s['p_filesz']]
                if len(segments) != 1:
                    raise ValueError('window is not wholly file-backed: ' + pin['role'])
                offset = segments[0]['p_offset'] + start - segments[0]['p_vaddr']
                if hashlib.sha256(raw[offset:offset + end - start]).hexdigest() != pin['sha256']:
                    raise ValueError('source window mismatch: ' + pin['role'])
                windows += 1
                byte_count += end - start
            wanted = [p for p in pins['got'] if p['artifact'] == name]
            dynamic = elf.get_section_by_name('.dynamic')
            for tag in dynamic.iter_tags():
                if wanted and (tag.entry.d_tag == 'DT_SYMBOLIC' or
                               tag.entry.d_tag == 'DT_FLAGS' and tag.entry.d_val & 2):
                    raise ValueError('symbolic binding prevents callback interposition')
            symbols = elf.get_section_by_name('.dynsym')
            relocations = elf.get_section_by_name('.rela.dyn')
            for pin in wanted:
                matches = [r for r in relocations.iter_relocations() if r['r_offset'] == int(pin['va'], 16)]
                if len(matches) != 1 or matches[0]['r_info_type'] != pin['type'] or matches[0]['r_addend'] != 0:
                    raise ValueError('callback relocation mismatch')
                symbol = symbols.get_symbol(matches[0]['r_info_sym'])
                if (symbol.name != pin['symbol'] or symbol['st_value'] != int(pin['target_va'], 16) or
                        symbol['st_info']['bind'] != 'STB_GLOBAL' or symbol['st_other']['visibility'] != 'STV_DEFAULT'):
                    raise ValueError('callback symbol binding mismatch')
                bindings += 1
    return {'source_verified': True, 'windows': windows, 'window_bytes': byte_count,
            'callback_got_bindings': bindings, 'capture_verified': False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('library_directory', nargs='?', type=Path,
                        default=OWN.parents[1] / 'runtime/analysis/menu-root/usr/lib')
    args = parser.parse_args()
    print(json.dumps(verify(args.library_directory), indent=2))


if __name__ == '__main__':
    main()
