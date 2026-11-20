"""Unexecuted test draft; synthetic cases need no firmware or research workspace."""
import hashlib
import importlib.util
import io
import os
from pathlib import Path
import struct
import tarfile
import tempfile
import unittest
from unittest import mock

SPEC = importlib.util.spec_from_file_location(
    "official_loader_page_tables", Path(__file__).with_name("official_loader_page_tables.py"))
nor = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(nor)


class SyntheticContractTests(unittest.TestCase):
    def test_synthetic_archive_rejects_changed_missing_duplicate_and_link_members(self):
        files = {'loader_nor.bin': b'synthetic-loader', 'LdrBkupList.txt': b'list',
                 'pformat_config.txt': b'config', 'loader_nor.md5': b'md5'}
        members = {name: (len(data), hashlib.sha256(data).hexdigest()) for name, data in files.items()}
        def archive(rows):
            output = io.BytesIO()
            with tarfile.open(fileobj=output, mode='w') as tar:
                for name, data in rows:
                    info = tarfile.TarInfo(name)
                    if data is None or data is False:
                        info.type = tarfile.SYMTYPE if data is None else tarfile.LNKTYPE
                        info.linkname = '/untrusted'
                        tar.addfile(info)
                    else:
                        info.size = len(data)
                        tar.addfile(info, io.BytesIO(data))
            raw = output.getvalue()
            return raw + bytes(nor.TAR_BYTES - len(raw))
        good = archive(list(files.items()))
        with mock.patch.object(nor, 'TAR_MEMBERS', members), \
             mock.patch.object(nor, 'TAR_SHA', hashlib.sha256(good).hexdigest()):
            self.assertEqual(nor.read_archive(good), files['loader_nor.bin'])
            with self.assertRaisesRegex(ValueError, 'archive size/SHA256'):
                nor.read_archive(good[:-1] + b'x')
        broken = b'\xff' * nor.TAR_BYTES
        with mock.patch.object(nor, 'TAR_SHA', hashlib.sha256(broken).hexdigest()), \
             self.assertRaisesRegex(ValueError, 'malformed official loader archive'):
            nor.read_archive(broken)
        for rows in (list(files.items())[:-1], list(files.items()) + [('loader_nor.bin', b'other')],
                     [(name, None if name == 'loader_nor.bin' else data) for name, data in files.items()],
                     [(name, False if name == 'loader_nor.bin' else data) for name, data in files.items()]):
            raw = archive(rows)
            with mock.patch.object(nor, 'TAR_MEMBERS', members), \
                 mock.patch.object(nor, 'TAR_SHA', hashlib.sha256(raw).hexdigest()), \
                 self.assertRaises(ValueError):
                nor.read_archive(raw)

    def test_synthetic_table_reconstruction_is_not_official_execution(self):
        source = bytearray(nor.SOURCE_BYTES)
        for va, value in nor.CONSTANTS:
            struct.pack_into('<Q', source, va - nor.BASE, value)
        struct.pack_into('<Q', source, 0xFE049620 - nor.BASE, 0xFE160000)
        struct.pack_into('<QQQQ', source, 0xFE05F5F8 - nor.BASE,
                         0xFE05FFE0, 0xFE05FFE0, 0x1B18, 0xFE04C678)
        probes = (0xFE049000, 0xF102F000, 0x403E42000, 0x803E42000,
                  0x800107F10, 0x804000000, 0xBFE0B0400, 0x03E42000)
        starts = [value & ~(nor.BLOCK_BYTES - 1) for value in probes]
        for index, va in enumerate(range(nor.REGION_START, nor.REGION_END, 24)):
            start = starts[index % len(starts)]
            struct.pack_into('<QQQ', source, va - nor.BASE, start, start + nor.BLOCK_BYTES, 0xF01)
        source = bytes(source)
        window = lambda start, end: hashlib.sha256(nor.read_at(source, start, end - start)).hexdigest()
        with mock.patch.object(nor, 'SOURCE_SHA', hashlib.sha256(source).hexdigest()), \
             mock.patch.object(nor, 'BUILDER_SHA', window(nor.BUILDER_START, nor.BUILDER_END)), \
             mock.patch.object(nor, 'REGION_SHA', window(nor.REGION_START, nor.REGION_END)):
            memory, regions = nor.reconstruct(source)
            report = nor.inspect(source)
        self.assertEqual(len(regions), 25)
        self.assertEqual(len(memory), nor.MEMORY_BYTES)
        self.assertEqual(nor.walk(memory, probes[-1], 36)['pa'], hex(probes[-1]))
        self.assertEqual(report['schema'], 'a7c2-official-loader-page-tables-v4')
        self.assertEqual(report['runtime_layout']['stack_top_aff0_zero'], '0xfe160000')
        self.assertEqual(report['runtime_layout']['bss_end_exclusive'], '0xfe061af8')
        self.assertFalse(report['runtime_layout']['stack_depth_verified'])
        self.assertFalse(report['runtime_layout']['physical_backing_verified'])
        for name in ('original_loader_executed', 'physical_bus_alias_verified',
                     'physical_compatible', 'full_boot_verified', 'bootrom_executed'):
            self.assertIs(report[name], False)

    def test_stack_and_bss_constants_are_checked(self):
        source = bytearray(nor.SOURCE_BYTES)
        struct.pack_into('<Q', source, 0xFE049620 - nor.BASE, 0xFE160000)
        struct.pack_into('<QQQQ', source, 0xFE05F5F8 - nor.BASE,
                         0xFE05FFE0, 0xFE05FFE0, 0x1B18, 0xFE04C678)
        self.assertEqual(nor.runtime_layout(source)['bss_end_exclusive'], '0xfe061af8')
        for offset in (0xFE049620 - nor.BASE, 0xFE05F5F8 - nor.BASE):
            bad = bytearray(source)
            bad[offset] ^= 1
            with self.subTest(offset=offset), self.assertRaisesRegex(ValueError, 'stack or BSS'):
                nor.runtime_layout(bad)

    def test_wrong_lengths_and_same_length_wrong_digest_rejected(self):
        for size in (0, nor.SOURCE_BYTES - 1, nor.SOURCE_BYTES,
                     nor.SOURCE_BYTES + 1, 417792):
            with self.subTest(size=size), self.assertRaisesRegex(ValueError, "size/SHA256"):
                nor.reconstruct(bytes(size))

    def test_direct_base_and_input_read_boundaries(self):
        source = b"abcdefgh"
        self.assertEqual(nor.read_at(source, 0xFE049000, 8), source)
        self.assertEqual(nor.read_at(source, 0xFE049007, 1), b"h")
        self.assertEqual(nor.read_at(source, 0xFE049008, 0), b"")
        for va, size in ((0xFE048FFF, 1), (0xFE049007, 2),
                         (0xFE049008, 1), (0xFE049009, 0), (0xFE049000, -1)):
            with self.subTest(va=va, size=size), self.assertRaisesRegex(ValueError, "read outside"):
                nor.read_at(source, va, size)

    def test_each_original_constant_guard(self):
        # This helper fixture never passes the full official source admission gate.
        source = bytearray(nor.SOURCE_BYTES)
        for va, value in nor.CONSTANTS:
            struct.pack_into("<Q", source, va - nor.BASE, value)
        nor.validate_constants(source)
        for va, value in nor.CONSTANTS:
            bad = bytearray(source)
            struct.pack_into("<Q", bad, va - nor.BASE, value ^ 1)
            with self.subTest(va=va), self.assertRaisesRegex(ValueError, "original constant"):
                nor.validate_constants(bad)
        with self.assertRaisesRegex(ValueError, "size/SHA256"):
            nor.reconstruct(source)
        with self.assertRaisesRegex(ValueError, "read outside"):
            nor.validate_constants(bytes(8))

    def test_region_bounds_alignment_and_attributes(self):
        nor.validate_region(0, nor.BLOCK_BYTES, 0xF01)
        nor.validate_region((1 << 36) - nor.BLOCK_BYTES, 1 << 36, 0xF05)
        for start, end, attrs in (
            (-nor.BLOCK_BYTES, 0, 0xF01), (1, nor.BLOCK_BYTES, 0xF01),
            (0, nor.BLOCK_BYTES + 1, 0xF01), (0, 0, 0xF01),
            (nor.BLOCK_BYTES, 0, 0xF01), (0, (1 << 36) + nor.BLOCK_BYTES, 0xF01),
            (0, nor.BLOCK_BYTES, 0), (0, nor.BLOCK_BYTES, 1 << 64),
        ):
            with self.subTest(start=start, end=end, attrs=attrs), self.assertRaises(ValueError):
                nor.validate_region(start, end, attrs)

    def test_store_boundaries_and_uint64(self):
        memory = bytearray(nor.MEMORY_BYTES)
        nor.store(memory, nor.L2, 0)
        nor.store(memory, nor.L2 + nor.MEMORY_BYTES - 8, (1 << 64) - 1)
        self.assertEqual(struct.unpack_from("<Q", memory, nor.MEMORY_BYTES - 8)[0], (1 << 64) - 1)
        for va in (nor.L2 - 8, nor.L2 + 1, nor.L2 + nor.MEMORY_BYTES):
            with self.subTest(va=va), self.assertRaises(ValueError):
                nor.store(memory, va, 1)
        for value in (-1, 1 << 64):
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, "unsigned 64-bit"):
                nor.store(memory, nor.L2, value)
        with self.assertRaisesRegex(ValueError, "clear extents"):
            nor.store(bytearray(8), nor.L2, 0)

    def test_walk_preserves_high_pa_bits(self):
        memory = bytearray(nor.MEMORY_BYTES)
        va = 0x803E42000
        struct.pack_into("<Q", memory, nor.ROOT36 - nor.L2 + (va >> 30) * 8, 0xFE1A0003)
        struct.pack_into("<Q", memory, 0x20000 + ((va >> 21) & 511) * 8, 0x803E00F05)
        result = nor.walk(memory, va, 36)
        self.assertEqual(result["pa"], hex(va))
        self.assertTrue(result["identity"])
        self.assertNotEqual(result["pa"], hex(va & 0xFFFFFFFF))
        with self.assertRaisesRegex(ValueError, "T0SZ"):
            nor.walk(memory, va, 32)

    def test_unmapped_l2_and_non_table_l1_do_not_translate_to_zero(self):
        for first, second, status in (
            (nor.L2 | 3, 0, "unmapped_or_not_l2_block"),
            (nor.L2 | 3, 3, "unmapped_or_not_l2_block"),
            (0, 0, "l1_not_table_not_interpreted"),
            (nor.L2 | 1, 0, "l1_not_table_not_interpreted"),
        ):
            with self.subTest(first=first, second=second):
                memory = bytearray(nor.MEMORY_BYTES)
                struct.pack_into("<Q", memory, nor.ROOT36 - nor.L2, first)
                struct.pack_into("<Q", memory, 0, second)
                row = nor.walk(memory, 0x108000, 36)
                self.assertEqual(row["status"], status)
                self.assertNotIn("pa", row)

    def test_walk_rejects_bad_extent_va_bits_and_table_pointers(self):
        memory = bytearray(nor.MEMORY_BYTES)
        for va, bits in ((-1, 36), (1 << 36, 36), (1 << 32, 32), (0, 40)):
            with self.subTest(va=va, bits=bits), self.assertRaisesRegex(ValueError, "T0SZ"):
                nor.walk(memory, va, bits)
        for size in (0, nor.MEMORY_BYTES - 8, nor.MEMORY_BYTES + 8):
            with self.subTest(size=size), self.assertRaisesRegex(ValueError, "memory extent"):
                nor.walk(bytes(size), 0, 36)
        for table in (nor.L2 - 0x1000, nor.L2 + nor.MEMORY_BYTES):
            struct.pack_into("<Q", memory, nor.ROOT36 - nor.L2, table | 3)
            with self.subTest(table=table), self.assertRaisesRegex(ValueError, "descriptor outside"):
                nor.walk(memory, 0, 36)

    def test_failed_probe_is_value_error_instead_of_optimization_sensitive_assert(self):
        for rows in ([], [{}], [{"status": "mapped_l2_block", "identity": False}],
                     [{"status": "unmapped_or_not_l2_block", "identity": True}]):
            with self.subTest(rows=rows), self.assertRaisesRegex(ValueError, "static walk"):
                nor.require_identity(rows)
        nor.require_identity([{"status": "mapped_l2_block", "identity": True}])

    def test_file_reader_rejects_special_input_without_blocking(self):
        # The caller must provide a project-owned TMPDIR; never write beside source.
        parent = Path(os.environ.get("TMPDIR", ""))
        if (not parent.is_absolute() or any(parent == Path(root) or parent.is_relative_to(root)
                for root in ("/tmp", "/var/tmp", "/dev", "/proc", "/sys", "/run"))):
            raise ValueError("Set a project-local TMPDIR for synthetic tests")
        with tempfile.TemporaryDirectory(prefix="synthetic-", dir=parent) as directory:
            root = Path(directory)
            wrong = root / "wrong.bin"
            wrong.write_bytes(bytes(nor.SOURCE_BYTES))
            with self.assertRaisesRegex(ValueError, "size/SHA256"):
                nor.read_loader(wrong)
            alias = root / "alias"
            alias.symlink_to(wrong)
            with self.assertRaisesRegex(ValueError, "canonical ordinary path"):
                nor.read_loader(alias)
            with self.assertRaisesRegex(ValueError, "host temporary and device roots"):
                nor.read_loader(Path('/tmp/untrusted-loader'))
            if hasattr(os, "mkfifo"):
                fifo = root / "synthetic-fifo"
                os.mkfifo(fifo)
                with self.assertRaisesRegex(ValueError, "regular file"):
                    nor.read_loader(fifo)


@unittest.skipUnless(os.environ.get("A7C2_OFFICIAL_NOR_TAR"), "explicit official loader archive not supplied")
class OptionalOfficialArchiveTests(unittest.TestCase):
    def test_official_archive_yields_exact_loader_without_modifying_input(self):
        path = Path(os.environ['A7C2_OFFICIAL_NOR_TAR'])
        before = path.stat()
        source = nor.read_loader(path)
        report = nor.inspect(source)
        after = path.stat()
        self.assertEqual(hashlib.sha256(source).hexdigest(), nor.SOURCE_SHA)
        self.assertEqual(report['schema'], 'a7c2-official-loader-page-tables-v4')
        self.assertEqual(len(report['regions']), 25)
        self.assertEqual(len(report['walks_36bit']), 8)
        self.assertEqual(report['runtime_layout']['stack_top_aff0_zero'], '0xfe160000')
        self.assertEqual(report['runtime_layout']['bss_end_exclusive'], '0xfe061af8')
        for name in ('original_loader_executed', 'physical_bus_alias_verified',
                     'physical_compatible', 'full_boot_verified', 'bootrom_executed'):
            self.assertIs(report[name], False)
        self.assertEqual((before.st_dev, before.st_ino, before.st_size, before.st_mode, before.st_mtime_ns,
                          before.st_ctime_ns),
                         (after.st_dev, after.st_ino, after.st_size, after.st_mode, after.st_mtime_ns,
                          after.st_ctime_ns))


@unittest.skipUnless(os.environ.get("A7C2_OFFICIAL_LOADER"), "explicit official loader not supplied")
class OptionalOfficialInputTests(unittest.TestCase):
    def setUp(self):
        self.source = nor.read_loader(Path(os.environ["A7C2_OFFICIAL_LOADER"]))

    def test_real_source_windows_regions_and_static_walks(self):
        result = nor.inspect(self.source)
        self.assertEqual(result["schema"], "a7c2-official-loader-page-tables-v4")
        self.assertEqual(result["source_bytes"], 94176)
        self.assertEqual(result["source_sha256"], nor.SOURCE_SHA)
        self.assertEqual(result["builder_sha256"], nor.BUILDER_SHA)
        self.assertEqual(result["region_table_sha256"], nor.REGION_SHA)
        self.assertEqual(len(result["regions"]), 25)
        self.assertEqual(len(result["walks_36bit"]), 8)
        self.assertEqual(len(result["walks_initial_32bit"]), 2)
        self.assertEqual(result["evidence_level"], "static_reconstruction_only")
        for key in ("original_loader_executed", "physical_bus_alias_verified", "physical_compatible",
                    "full_boot_verified", "bootrom_executed"):
            self.assertIs(result[key], False)
        # No comparison with the historical private-container table hash.

    def test_each_window_pin_is_independently_enforced(self):
        for name in ("BUILDER_SHA", "REGION_SHA"):
            with self.subTest(name=name), mock.patch.object(nor, name, "0" * 64):
                with self.assertRaisesRegex(ValueError, "SHA256"):
                    nor.reconstruct(self.source)

    def test_real_source_mutation_truncation_extension_rejected(self):
        changed = bytearray(self.source)
        changed[0xD8] ^= 1
        for bad in (changed, self.source[:-1], self.source + b"x"):
            with self.subTest(length=len(bad)), self.assertRaisesRegex(ValueError, "size/SHA256"):
                nor.reconstruct(bad)


if __name__ == "__main__":
    unittest.main()
