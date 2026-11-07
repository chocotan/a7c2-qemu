#!/usr/bin/env python3
"""Host-only derivation checks with synthetic ELF; no firmware/VM/device needed."""
import hashlib
import importlib.util
import inspect
import json
import os
from pathlib import Path
import stat
import struct
import tempfile
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('dev_update_profile_tested', HERE / 'dev-update-profile.py')
PROFILE = importlib.util.module_from_spec(spec)
spec.loader.exec_module(PROFILE)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def fixture(*, machine=183, kind=3, flags=5, offset=0, va=0,
            filesz=0xb100, memsz=None, duplicate=False):
    """ELF64 with a real program header, no firmware and the pinned call window."""
    data = bytearray(0xb100)
    ident = b'\x7fELF' + bytes([2, 1, 1, 0]) + bytes(8)
    struct.pack_into('<16sHHIQQQIHHHHHH', data, 0, ident, kind, machine, 1,
                     0, 64, 0, 0, 64, 56, 2 if duplicate else 1, 64, 0, 0)
    header = struct.pack('<IIQQQQQQ', 1, flags, offset, va, va, filesz,
                         filesz if memsz is None else memsz, 1)
    data[64:120] = header
    if duplicate:
        data[120:176] = header
    data[0xae08:0xae14] = bytes.fromhex('72f1ff971f04007140010054')
    return bytes(data)


class DerivationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.source = self.base / 'input' / 'receiver.so'
        self.output = self.base / 'output' / 'receiver-dev.so'
        self.source.parent.mkdir()
        self.output.parent.mkdir()
        self.data = fixture()
        self.source.write_bytes(self.data)

    def derive(self, *, source=None, output=None, mode=PROFILE.MODE):
        # Alternate identity is confined to tests; the public API has no override.
        facts = {'sha256': sha(self.data), 'size': len(self.data)}
        with patch.object(PROFILE, '_SOURCE_FACTS', facts):
            return PROFILE.derive_receiver(self.source if source is None else source,
                                           self.output if output is None else output, mode=mode)

    def reject_fixture(self, data):
        self.data = data
        self.source.write_bytes(data)
        with self.assertRaises((ValueError, OSError)):
            self.derive()
        self.assertFalse(self.output.exists())
        self.assertEqual(self.source.read_bytes(), data)

    def test_exact_patch_and_receipt(self):
        original = self.source.stat()
        receipt = self.derive()
        result = self.output.read_bytes()
        changed = [i for i, (a, b) in enumerate(zip(self.data, result)) if a != b]
        self.assertEqual(changed, list(range(0xae08, 0xae0c)))
        self.assertEqual(result[0xae08:0xae14], bytes.fromhex('200080521f04007140010054'))
        self.assertEqual(self.source.read_bytes(), self.data)
        self.assertEqual(PROFILE._identity(original), PROFILE._identity(self.source.stat()))
        self.assertNotEqual(PROFILE._inode(self.source.stat()), PROFILE._inode(self.output.stat()))
        self.assertTrue(stat.S_ISREG(self.output.stat().st_mode))
        self.assertEqual(self.output.stat().st_nlink, 1)
        for field in ('virtual_only', 'bypass_configured',
                      'stock_signature_verification_preserved_on_original', 'requires_explicit_selection'):
            self.assertIs(receipt[field], True)
        for field in ('bypass_executed', 'guest_execution_verified', 'default_official_start_applies'):
            self.assertIs(receipt[field], False)
        self.assertEqual(receipt['source']['sha256_before'], sha(self.data))
        self.assertEqual(receipt['source']['sha256_after'], sha(self.data))
        self.assertEqual(receipt['output']['sha256'], sha(result))
        self.assertEqual(receipt['patch']['file_offset'], 0xae08)
        self.assertEqual(receipt['patch']['virtual_address'], 0xae08)
        self.assertEqual(receipt['patch']['executable_load']['flags'], 5)
        self.assertEqual(json.loads(json.dumps(receipt)), receipt)

    def test_production_rejects_unknown_hash_without_override(self):
        self.assertEqual(PROFILE._SOURCE_FACTS['sha256'],
                         '1a6a3226993ce7c25659bd58e20871d91869083b31440650eec555a06d592d2f')
        self.assertEqual(list(inspect.signature(PROFILE.derive_receiver).parameters),
                         ['source', 'output', 'mode'])
        # Match the stock length so this exercises the production hash guard.
        self.source.write_bytes(self.data.ljust(PROFILE._SOURCE_FACTS['size'], b'\0'))
        with self.assertRaisesRegex(ValueError, 'SHA-256'):
            PROFILE.derive_receiver(self.source, self.output)
        self.assertFalse(self.output.exists())

    def test_wrong_source_hash(self):
        damaged = bytearray(self.data)
        damaged[0x300] ^= 1
        self.source.write_bytes(damaged)
        with self.assertRaisesRegex(ValueError, 'SHA-256'):
            self.derive()
        self.assertFalse(self.output.exists())

    def test_empty_and_wrong_length_source(self):
        for data in (b'', self.data[:-1], self.data + b'\0'):
            with self.subTest(size=len(data)):
                self.source.write_bytes(data)
                with self.assertRaisesRegex(ValueError, 'pinned size'):
                    self.derive()
                self.assertFalse(self.output.exists())

    def test_wrong_architecture_type_class_and_endianness(self):
        for data in (fixture(machine=62), fixture(kind=2),
                     self.data[:4] + b'\x01' + self.data[5:],
                     self.data[:5] + b'\x02' + self.data[6:]):
            with self.subTest(header=data[:20].hex()):
                self.reject_fixture(data)

    def test_unknown_original_instruction_or_following_branch(self):
        for index in (0xae08, 0xae0c, 0xae10):
            with self.subTest(offset=index):
                damaged = bytearray(fixture())
                damaged[index] ^= 1
                self.reject_fixture(bytes(damaged))

    def test_already_patched_input(self):
        self.reject_fixture(self.data[:0xae08] + bytes.fromhex('20008052') + self.data[0xae0c:])

    def test_wrong_va_mapping(self):
        for data in (fixture(va=0x10000), fixture(offset=4, filesz=0xb0fc),
                     fixture(va=4, filesz=0xb0fc)):
            with self.subTest(header=data[64:120].hex()):
                self.reject_fixture(data)

    def test_executable_file_backed_and_unique_load_boundary(self):
        for data in (fixture(flags=6), fixture(filesz=0xae0a, memsz=0xb100),
                     fixture(filesz=0xae10, memsz=0xb100), fixture(duplicate=True),
                     fixture(filesz=0xae08, memsz=0xae08)):
            with self.subTest(header=data[64:176].hex()):
                self.reject_fixture(data)

    def test_bad_load_bounds_and_alignment(self):
        bad_alignment = bytearray(fixture())
        struct.pack_into('<Q', bad_alignment, 64 + 48, 3)
        for data in (fixture(filesz=0xb101), fixture(memsz=1),
                     fixture(va=2**64 - 16), bytes(bad_alignment)):
            with self.subTest(header=data[64:120].hex()):
                self.reject_fixture(data)

    def test_full_diff_helper_rejects_extra_or_missing_changes(self):
        expected = self.data[:0xae08] + bytes.fromhex('20008052') + self.data[0xae0c:]
        damaged = bytearray(expected)
        damaged[0x300] ^= 1
        for result in (expected[:-1], expected + b'x', bytes(damaged), self.data):
            with self.subTest(size=len(result)):
                with self.assertRaisesRegex(ValueError, 'Full receiver diff'):
                    PROFILE._check_diff(self.data, result)

    def test_modes_are_explicitly_limited(self):
        for mode in ('', 'physical', 'official', None, 'virtual-dev-sd-update-v2'):
            with self.subTest(mode=mode), self.assertRaisesRegex(ValueError, 'Only'):
                self.derive(mode=mode)
        self.assertFalse(self.output.exists())

    def test_empty_and_dot_paths(self):
        for name, value in (('source', ''), ('output', ''),
                            ('source', str(self.base / 'input') + '/../input/receiver.so'),
                            ('output', str(self.output.parent) + '/./receiver-dev.so')):
            with self.subTest(name=name, value=value), self.assertRaises(ValueError):
                self.derive(**{name: value})
        self.assertFalse(self.output.exists())

    def test_aliases_and_no_overwrite(self):
        for kind in ('same', 'hardlink', 'symlink', 'ordinary', 'directory', 'fifo', 'dangling'):
            target = self.base / ('existing-' + kind)
            if kind == 'same':
                target = self.source
            elif kind == 'hardlink':
                os.link(self.source, target)
            elif kind == 'symlink':
                target.symlink_to(self.source)
            elif kind == 'ordinary':
                target.write_bytes(b'keep')
            elif kind == 'directory':
                target.mkdir()
            elif kind == 'fifo':
                os.mkfifo(target)
            else:
                target.symlink_to(self.base / 'missing')
            info = target.lstat()
            with self.subTest(kind=kind), self.assertRaises((ValueError, OSError)):
                self.derive(output=target)
            self.assertEqual(PROFILE._identity(info), PROFILE._identity(target.lstat()))
            self.assertEqual(self.source.read_bytes(), self.data)
            if kind == 'ordinary':
                self.assertEqual(target.read_bytes(), b'keep')

    def test_source_symlink_fifo_directory_and_device_refused(self):
        link = self.base / 'source-link'
        link.symlink_to(self.source)
        fifo = self.base / 'source-fifo'
        os.mkfifo(fifo)
        for source in (link, fifo, self.source.parent, Path('/dev/null')):
            with self.subTest(source=source), self.assertRaises(ValueError):
                self.derive(source=source)
        self.assertFalse(self.output.exists())

    def test_parent_symlinks_refused_for_both_paths(self):
        for name, directory, leaf in (('source', self.source.parent, self.source.name),
                                      ('output', self.output.parent, self.output.name)):
            link = self.base / ('parent-' + name)
            link.symlink_to(directory, target_is_directory=True)
            with self.subTest(name=name), self.assertRaises(OSError):
                self.derive(**{name: link / leaf})
        self.assertFalse(self.output.exists())

    def test_missing_source_or_output_parent(self):
        for kwargs in ({'source': self.base / 'missing'},
                       {'output': self.base / 'absent' / 'receiver.so'}):
            with self.subTest(kwargs=kwargs), self.assertRaises(OSError):
                self.derive(**kwargs)
        self.assertFalse(self.output.exists())
        self.assertFalse((self.base / 'absent').exists())

    def test_source_swap_between_stat_and_open(self):
        real_open = os.open
        replacement = self.base / 'replacement'
        replacement.write_bytes(self.data)

        def race(name, flags, *args, **kwargs):
            if name == self.source.name and kwargs.get('dir_fd') is not None:
                os.replace(replacement, self.source)
            return real_open(name, flags, *args, **kwargs)

        with patch.object(PROFILE.os, 'open', side_effect=race):
            with self.assertRaisesRegex(ValueError, 'Source changed while opening'):
                self.derive()
        self.assertFalse(self.output.exists())
        self.assertEqual(self.source.read_bytes(), self.data)

    def test_source_mutation_after_validation(self):
        validate = PROFILE._validate_receiver
        changed = self.data[:-1] + b'X'

        def race(data):
            result = validate(data)
            self.source.write_bytes(changed)
            return result

        with patch.object(PROFILE, '_validate_receiver', side_effect=race):
            with self.assertRaisesRegex(ValueError, 'Source'):
                self.derive()
        self.assertFalse(self.output.exists())
        self.assertEqual(self.source.read_bytes(), changed)

    def test_source_inode_swap_during_output_write(self):
        write = PROFILE._write

        def race(fd, data):
            write(fd, data)
            self.source.unlink()
            self.source.write_bytes(self.data)

        with patch.object(PROFILE, '_write', side_effect=race):
            with self.assertRaisesRegex(ValueError, 'Source'):
                self.derive()
        self.assertFalse(self.output.exists())
        self.assertEqual(self.source.read_bytes(), self.data)

    def test_source_parent_swap_during_write(self):
        write = PROFILE._write
        saved = self.base / 'saved-input'

        def race(fd, data):
            write(fd, data)
            self.source.parent.rename(saved)
            self.source.parent.symlink_to(saved, target_is_directory=True)

        with patch.object(PROFILE, '_write', side_effect=race):
            with self.assertRaises(OSError):
                self.derive()
        self.assertFalse(self.output.exists())
        self.assertEqual((saved / self.source.name).read_bytes(), self.data)

    def test_output_parent_swap_does_not_escape_or_delete_replacement(self):
        write = PROFILE._write
        saved = self.base / 'saved-output'
        innocent = self.base / 'innocent'
        innocent.mkdir()
        sentinel = innocent / self.output.name
        sentinel.write_bytes(b'keep')

        def race(fd, data):
            write(fd, data)
            self.output.parent.rename(saved)
            self.output.parent.symlink_to(innocent, target_is_directory=True)

        with patch.object(PROFILE, '_write', side_effect=race):
            with self.assertRaises(OSError):
                self.derive()
        self.assertFalse((saved / self.output.name).exists())
        self.assertEqual(sentinel.read_bytes(), b'keep')

    def test_output_replaced_during_write_is_retained(self):
        write = PROFILE._write

        def race(fd, data):
            write(fd, data)
            self.output.unlink()
            self.output.write_bytes(b'replacement')

        with patch.object(PROFILE, '_write', side_effect=race):
            with self.assertRaisesRegex(ValueError, 'Output changed'):
                self.derive()
        self.assertEqual(self.output.read_bytes(), b'replacement')
        self.assertEqual(self.source.read_bytes(), self.data)

    def test_output_created_just_before_exclusive_open_is_retained(self):
        real_open = os.open

        def race(name, flags, *args, **kwargs):
            if name == self.output.name and flags & os.O_CREAT:
                fd = real_open(name, flags, *args, **kwargs)
                os.write(fd, b'keep')
                os.close(fd)
            return real_open(name, flags, *args, **kwargs)

        with patch.object(PROFILE.os, 'open', side_effect=race):
            with self.assertRaises(FileExistsError):
                self.derive()
        self.assertEqual(self.output.read_bytes(), b'keep')

    def test_output_hardlink_added_during_write_refused(self):
        write = PROFILE._write
        alias = self.base / 'output-alias'

        def race(fd, data):
            write(fd, data)
            os.link(self.output, alias)

        with patch.object(PROFILE, '_write', side_effect=race):
            with self.assertRaisesRegex(ValueError, 'Output changed'):
                self.derive()
        self.assertFalse(self.output.exists())
        self.assertEqual(self.source.read_bytes(), self.data)

    def test_output_mutated_after_readback_is_detected(self):
        verify = PROFILE._verify_source
        calls = 0

        def race(*args):
            nonlocal calls
            digest = verify(*args)
            calls += 1
            if calls == 2:
                with self.output.open('r+b') as stream:
                    stream.seek(0x300)
                    stream.write(b'X')
            return digest

        with patch.object(PROFILE, '_verify_source', side_effect=race):
            with self.assertRaisesRegex(ValueError, 'Output changed'):
                self.derive()
        self.assertFalse(self.output.exists())

    def test_corrupt_or_truncated_readback_refused(self):
        write = PROFILE._write
        for kind in ('corrupt', 'short'):
            def damaged(fd, data):
                value = bytearray(data)
                if kind == 'corrupt':
                    value[0x300] ^= 1
                else:
                    value = value[:-1]
                write(fd, value)

            with self.subTest(kind=kind), patch.object(PROFILE, '_write', side_effect=damaged):
                with self.assertRaises((ValueError, OSError)):
                    self.derive()
            self.assertFalse(self.output.exists())
            self.assertEqual(self.source.read_bytes(), self.data)

    def test_short_writes_are_completed(self):
        real_write = os.write
        with patch.object(PROFILE.os, 'write', side_effect=lambda fd, data: real_write(fd, data[:4096])):
            receipt = self.derive()
        self.assertEqual(receipt['output']['sha256'], sha(self.output.read_bytes()))

    def test_zero_write_refused_and_own_file_removed(self):
        with patch.object(PROFILE.os, 'write', return_value=0):
            with self.assertRaisesRegex(OSError, 'Zero receiver write'):
                self.derive()
        self.assertFalse(self.output.exists())
        self.assertEqual(self.source.read_bytes(), self.data)


if __name__ == '__main__':
    unittest.main(verbosity=2)
