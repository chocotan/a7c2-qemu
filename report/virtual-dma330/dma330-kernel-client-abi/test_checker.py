"""Mutation checks for the built artifact; all temporary writes stay here."""
import struct
import tempfile
import unittest

from check_elf import DESC, ELF, HERE, verify


class CheckerTests(unittest.TestCase):
    def setUp(self):
        self.elf = ELF(HERE / 'dma330_abi_diag.ko')

    def rejected(self, offset, replacement):
        data = bytearray(self.elf.raw)
        data[offset:offset + len(replacement)] = replacement
        with tempfile.TemporaryDirectory(dir=HERE) as tmp:
            path = HERE / tmp / 'mutated.ko'
            path.write_bytes(data)
            with self.assertRaises((ValueError, KeyError, IndexError, struct.error)):
                verify(path)

    def test_valid(self):
        self.assertTrue(verify()['status'].startswith('PASS:'))

    def test_wrong_arch(self):
        self.rejected(18, struct.pack('<H', 62))

    def test_descriptor_size(self):
        header = struct.unpack_from('<Q', self.elf.raw, 40)[0]
        index = self.elf.sections.index(self.elf.byname[DESC])
        self.rejected(header + 64 * index + 32, struct.pack('<Q', 760))

    def test_descriptor_nonzero(self):
        self.rejected(self.elf.byname[DESC]['offset'] + 0x80, b'\1')

    def test_wrong_name(self):
        self.rejected(self.elf.byname[DESC]['offset'] + 0x18, b'x')

    def test_callback_offset(self):
        self.rejected(self.elf.byname['.rela' + DESC]['offset'], struct.pack('<Q', 0x150))

    def test_extra_memory_store(self):
        self.rejected(self.elf.byname['.init.text']['offset'] + 20, struct.pack('<I', 0xf9000000))

    def test_unexpected_import(self):
        self.rejected(self.elf.raw.index(b'printk\0'), b'strcpy')

    def test_wrong_vermagic(self):
        self.rejected(self.elf.raw.index(b'vermagic=') + len(b'vermagic='), b'5')


if __name__ == '__main__':
    unittest.main(verbosity=2)
