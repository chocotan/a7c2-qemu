#!/usr/bin/env python3
"""Corrupt built ELF metadata to ensure the host checker fails closed."""
import struct
import tempfile
import unittest
from pathlib import Path
import check_client as checker


class CheckerTests(unittest.TestCase):
    def setUp(self):
        self.raw = bytearray((checker.HERE / 'sony_atu_client.ko').read_bytes())
        self.elf = checker.abi.ELF(checker.HERE / 'sony_atu_client.ko')

    def reject(self):
        with tempfile.TemporaryDirectory(dir=checker.HERE, prefix='checker-test-') as temp:
            path = Path(temp) / 'bad.ko'
            path.write_bytes(self.raw)
            with self.assertRaises(ValueError):
                checker.verify(path)

    def section_header(self, name):
        return struct.unpack_from('<Q', self.raw, 40)[0] + 64 * self.elf.sections.index(self.elf.byname[name])

    def test_valid(self):
        self.assertEqual(checker.verify()['status'], 'PASS_HOST_ABI_ONLY')

    def test_descriptor_size(self):
        struct.pack_into('<Q', self.raw, self.section_header(checker.abi.DESC) + 32, 0x2f8)
        self.reject()

    def test_descriptor_alignment(self):
        struct.pack_into('<Q', self.raw, self.section_header(checker.abi.DESC) + 48, 8)
        self.reject()

    def test_descriptor_name(self):
        self.raw[self.elf.byname[checker.abi.DESC]['offset'] + 0x18] ^= 1
        self.reject()

    def test_nonzero_exit(self):
        self.raw[self.elf.byname[checker.abi.DESC]['offset'] + 0x2b8] = 1
        self.reject()

    def test_bad_init_offset(self):
        section = next(s for s in self.elf.sections if s['type'] == 4 and
                       self.elf.sections[s['info']]['name'] == checker.abi.DESC)
        struct.pack_into('<Q', self.raw, section['offset'], 0x160)
        self.reject()

    def test_unsupported_adrp(self):
        section = next(s for s in self.elf.sections if s['type'] == 4 and
                       self.elf.sections[s['info']]['name'] != checker.abi.DESC)
        offset = section['offset'] + 8
        info = struct.unpack_from('<Q', self.raw, offset)[0]
        struct.pack_into('<Q', self.raw, offset, (info & ~0xffffffff) | 275)
        self.reject()

    def test_dependency(self):
        start = self.raw.index(b'depends=pcieatu\0')
        self.raw[start + 8:start + 15] = b'BADxxxx'
        self.reject()

    def test_import(self):
        start = self.raw.index(b'pciatu_map\0')
        self.raw[start:start + 10] = b'fakeatu_xx'
        self.reject()

    def test_vermagic(self):
        start = self.raw.index(b'vermagic=4.9.337-scel+')
        self.raw[start + 9] = ord('5')
        self.reject()


if __name__ == '__main__':
    unittest.main(verbosity=2)
