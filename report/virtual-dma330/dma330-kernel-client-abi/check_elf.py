#!/usr/bin/env python3
"""Bounded ELF64/AArch64 REL checker; Python standard library only, no execution."""
import hashlib
import json
from pathlib import Path
import struct
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
KMOD = ROOT/'runtime/analysis/menu-root/kmod'
VERMAGIC = '4.9.337-scel+ SMP preempt mod_unload aarch64'
DESC = '.gnu.linkonce.this_module'
MARKER = b'\x016dma330_abi_diag: marker-only init\n\0'


def require(condition, message):
    if not condition:
        raise ValueError(message)


class ELF:
    def __init__(self, path):
        self.path = Path(path)
        self.raw = self.path.read_bytes()
        h = self.unpack('<16sHHIQQQIHHHHHH', 0)
        require(h[0][:7] == b'\x7fELF\x02\x01\x01', 'not ELF64 LE v1')
        require(h[1:4] == (1, 183, 1), 'not AArch64 ET_REL v1')
        require(h[4] == 0 and h[5] == 0 and h[7] == 0, 'unexpected entry/phdr/flags')
        require(h[8] == 64 and h[10] == 0 and h[11] == 64, 'unexpected header size')
        require(0 < h[12] < 1000 and h[13] < h[12], 'bad section count')
        self.sections = []
        for i in range(h[12]):
            s = self.unpack('<IIQQQQIIQQ', h[6] + i * 64)
            self.sections.append(dict(zip(
                ('nameoff', 'type', 'flags', 'addr', 'offset', 'size', 'link', 'info', 'align', 'entsize'), s)))
        names = self.data(self.sections[h[13]])
        for s in self.sections:
            s['name'] = self.string(names, s['nameoff'])
        self.byname = {s['name']: s for s in self.sections}
        require(len(self.byname) == len(self.sections), 'duplicate sections')
        self.symbols = []
        syms = self.byname['.symtab']
        require(syms['entsize'] == 24 and syms['size'] % 24 == 0, 'bad symtab')
        strings = self.data(self.sections[syms['link']])
        for off in range(0, syms['size'], 24):
            n, info, other, shndx, value, size = self.unpack('<IBBHQQ', syms['offset'] + off)
            self.symbols.append(dict(name=self.string(strings, n), info=info, other=other,
                                     shndx=shndx, value=value, size=size))
        self.relocs = []
        for s in self.sections:
            require(s['type'] != 9, 'REL relocations unsupported; expected RELA')
            if s['type'] != 4:
                continue
            require(s['link'] == self.sections.index(syms) and s['entsize'] == 24 and
                    s['size'] % 24 == 0, 'bad rela table')
            for off in range(0, s['size'], 24):
                offset, info, addend = self.unpack('<QQq', s['offset'] + off)
                symbol = self.symbols[info >> 32]
                self.relocs.append(dict(section=self.sections[s['info']]['name'], offset=offset,
                                        type=info & 0xffffffff, symbol=symbol['name'],
                                        symbol_index=info >> 32, addend=addend))

    def unpack(self, fmt, offset):
        require(0 <= offset <= len(self.raw) - struct.calcsize(fmt), 'ELF bounds')
        return struct.unpack_from(fmt, self.raw, offset)

    @staticmethod
    def string(data, offset):
        require(0 <= offset < len(data), 'string offset')
        end = data.find(b'\0', offset)
        require(end >= 0, 'unterminated string')
        return data[offset:end].decode('ascii')

    def data(self, section):
        s = self.byname[section] if isinstance(section, str) else section
        require(s['type'] != 8 and s['offset'] + s['size'] <= len(self.raw), 'section bounds/type')
        return self.raw[s['offset']:s['offset'] + s['size']]

    def named(self, name):
        matches = [s for s in self.symbols if s['name'] == name]
        require(len(matches) == 1, 'missing/duplicate symbol ' + name)
        return matches[0]

    def descriptor(self, name, callbacks):
        s = self.byname[DESC]
        require((s['type'], s['flags'], s['size'], s['align']) == (1, 3, 768, 64), 'descriptor ABI')
        symbol = self.named('__this_module')
        require(symbol['shndx'] == self.sections.index(s) and symbol['value'] == 0 and
                symbol['size'] == 768 and symbol['info'] == 17, '__this_module symbol')
        expected = bytearray(768)
        expected[24:24 + len(name) + 1] = name.encode() + b'\0'
        require(self.data(s) == expected, 'descriptor is not zero-filled except own name')
        got = sorted((r['offset'], r['type'], r['symbol'], r['addend'])
                     for r in self.relocs if r['section'] == DESC)
        require(got == callbacks, 'descriptor callbacks')

    def modinfo(self):
        return [x.decode('ascii') for x in self.data('.modinfo').split(b'\0') if x]

    def no_versions(self):
        require(not {'__versions', '.versions', '__version_ext_crcs', '__version_ext_names'} &
                self.byname.keys(), 'version section present: requires exact CRC analysis')
        require('vermagic=' + VERMAGIC in self.modinfo(), 'vermagic mismatch')


CALLBACKS = [(0x158, 257, 'init_module', 0), (0x2b8, 257, 'cleanup_module', 0)]


def verify(path=HERE / 'dma330_abi_diag.ko'):
    evidence = {}
    for name, digest in (
        ('dma330', '9ba277f011b3ddcfbc3fa610d22b63ae3be1e0ded385b42ff2c7cf0a83e520ab'),
        ('devno', 'cca1d9acd87a718c7742d168ea0de402b01a7c04cd40433ff2ca4071150dbc23')):
        original = ELF(KMOD / (name + '.ko'))
        require(hashlib.sha256(original.raw).hexdigest() == digest, 'reference hash mismatch')
        original.descriptor(name, CALLBACKS if name == 'dma330' else [])
        original.no_versions()
        evidence[name] = dict(size=len(original.raw), sha256=digest, modinfo=original.modinfo())
    elf = ELF(path)
    elf.descriptor('dma330_abi_diag', CALLBACKS)
    elf.no_versions()
    require(set(elf.modinfo()) == {'license=GPL', 'depends=', 'vermagic=' + VERMAGIC,
                'description=Independent marker-only local QEMU diagnostic'}, 'unexpected modinfo')
    require([s['name'] for s in elf.symbols if s['shndx'] == 0 and s['name']] == ['printk'],
            'unexpected undefined imports')
    for name, section in [('init_module', '.init.text'), ('cleanup_module', '.exit.text')]:
        symbol = elf.named(name)
        require(symbol['shndx'] == elf.sections.index(elf.byname[section]) and
                symbol['value'] == 0 and symbol['size'] == (28 if name == 'init_module' else 4) and
                symbol['info'] == 18, 'callback symbol ' + name)
    rels = [r for r in elf.relocs if r['section'] != DESC]
    require(len(rels) == 2 and all(r['section'] == '.init.text' for r in rels), 'unexpected relocations')
    require(sorted(r['type'] for r in rels) == [257, 283], 'expected ABS64/CALL26, no unsupported ADRP')
    call = [r for r in rels if r['type'] == 283][0]
    require(call['symbol'] == 'printk' and call['addend'] == 0, 'unexpected init call')
    address_rels = [r for r in rels if r['type'] != 283]
    for r in address_rels:
        sym = elf.symbols[r['symbol_index']]
        require(sym['shndx'] > 0, 'marker must be own rodata')
        sec = elf.sections[sym['shndx']]
        require(sec['flags'] & 7 == 2 and elf.data(sec)[sym['value'] + r['addend']:] == MARKER,
                'unexpected marker reference')
    # Strict instruction allowlist also rejects indirect calls and memory stores except stack save.
    init = elf.data('.init.text')
    words = list(struct.unpack('<' + 'I' * (len(init) // 4), init))
    require(words == [0xa9bf7bfd, 0x910003fd, 0x580000c0, 0x94000000,
                      0x52800000, 0xa8c17bfd, 0xd65f03c0, 0xd503201f, 0, 0],
            'unexpected init sequence; review compiler output before accepting')
    fixed = {0xa9bf7bfd, 0x910003fd, 0x580000c0, 0x52800000, 0xa8c17bfd, 0xd65f03c0, 0xd503201f, 0}
    reloc_words = {257: 0, 283: 0x94000000}
    for r in rels:
        require(words[r['offset'] // 4] == reloc_words[r['type']], 'unexpected relocated instruction')
    relocated = {r['offset'] // 4 for r in rels}
    require(all(w in fixed for i, w in enumerate(words) if i not in relocated), 'unexpected init instruction')
    require(call['offset'] == 12 and address_rels[0]['offset'] == 32, 'call/literal positions')
    require(words[6] == 0xd65f03c0 and words.count(0x52800000) == 1, 'init return')
    require(elf.data('.exit.text') == struct.pack('<I', 0xd65f03c0), 'exit must only return')
    require(elf.byname['.data']['size'] == 0 and elf.byname['.bss']['size'] == 0, 'unexpected mutable data')
    allowed_alloc = {DESC, '.modinfo', '.init.text', '.exit.text', '.text', '.data', '.bss'}
    allowed_alloc.update(elf.sections[elf.symbols[r['symbol_index']]['shndx']]['name'] for r in address_rels)
    require(all(not s['flags'] & 2 or s['name'] in allowed_alloc for s in elf.sections), 'unexpected alloc section')
    require(elf.byname['.text']['size'] == 0, 'unexpected text')
    for name in ('.init.text', '.exit.text'):
        require(elf.byname[name]['flags'] == 6, 'callback section flags')
    require(elf.byname['.modinfo']['flags'] == 2, 'modinfo section flags')
    return dict(status='PASS: host ELF checks only; never loaded',
                output=dict(file=elf.path.name, bytes=len(elf.raw), sha256=hashlib.sha256(elf.raw).hexdigest(),
                            init_bytes=len(init), exit_bytes=4, descriptor_bytes=768,
                            descriptor_alignment=64, name_offset=24, init_offset=344, exit_offset=696,
                            modinfo=elf.modinfo(), relocations=elf.relocs,
                            undefined_imports=['printk']), references=evidence)


if __name__ == '__main__':
    print(json.dumps(verify(Path(sys.argv[1]) if len(sys.argv) > 1 else HERE / 'dma330_abi_diag.ko'), indent=2))
