import copy
import functools
import hashlib
import json
import operator
import os
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import patch

import sony_wbi as wbi


BASE = 0x400001000
PAGE = 4096


def snapshot(regions=None, flags=0):
    if regions is None:
        regions = [(BASE, b'A' * PAGE, PAGE), (BASE + PAGE, None, PAGE),
                   (BASE + 3 * PAGE, b'C' * PAGE, PAGE)]
    data, rows = bytearray(), []
    for address, payload, length in regions:
        fields = (address, len(payload) if payload is not None else 0, wbi.SEED,
                  int(payload is None), length, 0xffffffc000000000 + address - BASE)
        rows.append(wbi.SECTION.pack(*fields, functools.reduce(operator.xor, fields, wbi.SEED), 0x1234))
        if payload is not None:
            data.extend(payload)
    header = wbi.HEADER.pack(b'WBI2', 0x5678, len(rows), flags, BASE, 0x20060224,
                             512, len(data), 0x400080000, 0, wbi.SEED,
                             sum(length for _, _, length in regions))
    return header.ljust(512, b'\0') + data + b''.join(rows)


def change_header(blob, name, value):
    values = list(wbi.HEADER.unpack_from(blob))
    values[1 + wbi.HEADER_FIELDS.index(name)] = value
    return wbi.HEADER.pack(*values) + blob[wbi.HEADER.size:]


def change_section(blob, index, values, fix_checksum=True):
    offset = 512 + wbi.HEADER.unpack_from(blob)[7] + index * wbi.SECTION.size
    fields = list(wbi.SECTION.unpack_from(blob, offset))
    for name, value in values.items():
        fields[wbi.SECTION_FIELDS.index(name)] = value
    if fix_checksum:
        fields[6] = functools.reduce(operator.xor, fields[:6], wbi.SEED)
    result = bytearray(blob)
    result[offset:offset + wbi.SECTION.size] = wbi.SECTION.pack(*fields)
    return bytes(result)


class SonyWbiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def put(self, name, data):
        path = self.root / name
        path.write_bytes(data)
        return path

    def cache_fixture(self):
        # Explicit synthetic facts: these coordinates never masquerade as Sony evidence.
        ap = b''.join(bytes([65 + index]) * PAGE for index in range(5))
        descriptor_address, mapping = BASE + 16 * PAGE, 0xffffffc012345600
        descriptor = bytearray(PAGE)
        anchors = []
        for index in range(4):
            struct.pack_into('<QQQ', descriptor, index * 64, 0x1002c, mapping, index)
            anchors.append({'file_page_index': index, 'physical': hex(BASE + index * PAGE),
                            'descriptor': hex(descriptor_address + index * 64)})
        image = snapshot([(BASE, ap[:4 * PAGE], 4 * PAGE),
                          (descriptor_address, descriptor, PAGE)])
        facts = {'raw_bytes': len(image), 'raw_sha256': hashlib.sha256(image).hexdigest(),
                 'factory_bytes': len(image) + 512,
                 'cache': {'scope': 'SYNTHETIC TEST: four constructed pages only',
                           'ap_sha256': hashlib.sha256(ap).hexdigest(),
                           'page_bytes': PAGE, 'descriptor_bytes': 56,
                           'mapping': hex(mapping), 'anchors': anchors}}
        return self.put('cache.wbi', image), self.put('ap.so', ap), facts

    def test_header_and_every_raw_section_field_preserved(self):
        raw = snapshot()
        path = self.put('raw.wbi', raw)
        result = wbi.inspect_wbi(path)
        header = wbi.HEADER.unpack_from(raw)
        self.assertEqual(result['header'], {'magic_hex': b'WBI2'.hex(),
                                           **dict(zip(wbi.HEADER_FIELDS, header[1:]))})
        metadata = 512 + header[7]
        for index, row in enumerate(result['sections']):
            values = wbi.SECTION.unpack_from(raw, metadata + index * wbi.SECTION.size)
            self.assertEqual({key: row[key] for key in wbi.SECTION_FIELDS},
                             dict(zip(wbi.SECTION_FIELDS, values)))
        self.assertTrue(result['has_wbi2_header'])
        self.assertTrue(result['structure_verified'])
        self.assertEqual(result['format_status'], 'supported_raw')
        self.assertEqual(result['data_checksum_status'], 'not_required_by_header')
        self.assertEqual(result['kernel_checksum_status'], 'not_checked')
        self.assertEqual(result['source_sha256'], hashlib.sha256(raw).hexdigest())
        self.assertEqual(result['source_readback_sha256'], result['source_sha256'])
        self.assertEqual(result['unknown_gap_bytes'], PAGE)
        self.assertFalse(result['resume_executed'])
        self.assertFalse(result['fullboot_verified'])
        json.dumps(result)

    def test_saved_normal_zero_adjacent_and_unknown_hole(self):
        path = self.put('raw.wbi', snapshot())
        info = wbi.inspect_wbi(path)
        self.assertEqual(wbi.read_saved_range(path, info, BASE + 10, 9), b'A' * 9)
        self.assertEqual(wbi.read_saved_range(path, info, BASE + PAGE, PAGE), bytes(PAGE))
        self.assertEqual(wbi.read_saved_range(path, info, BASE + PAGE - 3, 8), b'AAA' + bytes(5))
        for address, size in [(BASE + 2 * PAGE, 1), (BASE + 2 * PAGE - 1, 2),
                              (BASE - 1, 2), (BASE + 4 * PAGE, 1)]:
            with self.subTest(address=address), self.assertRaisesRegex(ValueError, 'Unrepresented'):
                wbi.read_saved_range(path, info, address, size)

    def test_fd_and_file_object_preserve_offset_and_remain_open(self):
        path = self.put('raw.wbi', snapshot())
        with path.open('rb') as source:
            source.seek(37)
            info = wbi.inspect_wbi(source)
            self.assertEqual(source.tell(), 37)
            self.assertEqual(wbi.read_saved_range(source.fileno(), info, BASE, 2), b'AA')
            self.assertEqual(source.tell(), 37)
            self.assertEqual(os.fstat(source.fileno()).st_size, len(snapshot()))

    def test_non_wbi2_magic_needs_only_four_changed_bytes(self):
        raw = snapshot()
        for magic in (b'WBI0', b'NOPE', bytes(4)):
            with self.subTest(magic=magic):
                path = self.put('negative.wbi', magic + raw[4:])
                info = wbi.inspect_wbi(path)
                self.assertFalse(info['has_wbi2_header'])
                self.assertFalse(info['structure_verified'])
                self.assertEqual(info['format_status'], 'not_wbi2')
                self.assertEqual(info['header']['padding'], 0x5678)
        info = wbi.inspect_wbi(self.put('zero.wbi', bytes(512)))
        self.assertFalse(info['has_wbi2_header'])
        self.assertFalse(info['structure_verified'])
        self.assertFalse(wbi.inspect_wbi(self.put('four.wbi', b'NOPE'))['has_wbi2_header'])

    def test_truncations_and_invalid_header_extents(self):
        raw = snapshot()
        invalid = [raw[:3], raw[:80], raw[:511], raw[:-1],
                   change_header(raw, 'sections', 0), change_header(raw, 'sections', wbi.MAX_SECTIONS + 1),
                   change_header(raw, 'r_data_size', 512), change_header(raw, 'r_data_size', 1),
                   change_header(raw, 'o_data_size', PAGE), change_header(raw, 'sector_size', 1024)]
        for index, blob in enumerate(invalid):
            with self.subTest(case=index), self.assertRaises(ValueError):
                wbi.inspect_wbi(self.put('broken.wbi', blob))

    def test_metadata_checksum_overlap_lengths_flags_and_uint64_boundary(self):
        raw = snapshot()
        invalid = [change_section(raw, 0, {'cksum': 0}, fix_checksum=False),
                   change_section(raw, 1, {'addr': BASE}),
                   change_section(raw, 0, {'rlen': PAGE - 1}),
                   change_section(raw, 1, {'rlen': PAGE}),
                   change_section(raw, 0, {'flag': 2}),
                   change_section(raw, 0, {'addr': BASE + 1}),
                   change_section(raw, 0, {'olen': 0}),
                   change_section(raw, 0, {'addr': (1 << 64) - PAGE, 'olen': 2 * PAGE, 'rlen': 2 * PAGE})]
        for index, blob in enumerate(invalid):
            with self.subTest(case=index), self.assertRaises(ValueError):
                wbi.inspect_wbi(self.put('broken.wbi', blob))

    def test_required_data_checksum_and_compression_are_unsupported(self):
        for flag in (1, 2, 4, 6, 8):
            with self.subTest(flag=flag), self.assertRaisesRegex(ValueError, 'Unsupported WBI'):
                wbi.inspect_wbi(self.put('flags.wbi', snapshot(flags=flag)))
        with self.assertRaisesRegex(ValueError, 'flag4.*not implemented'):
            wbi.inspect_wbi(self.put('flags.wbi', snapshot(flags=4)))

    def test_stale_and_edited_inspections_are_rejected(self):
        path = self.put('raw.wbi', snapshot())
        info = wbi.inspect_wbi(path)
        altered = copy.deepcopy(info)
        altered['sections'][0]['file_offset'] += 1
        with self.assertRaisesRegex(ValueError, 'Inspection does not match'):
            wbi.read_saved_range(path, altered, BASE, 1)
        raw = bytearray(path.read_bytes()); raw[512] ^= 1; path.write_bytes(raw)
        with self.assertRaisesRegex(ValueError, 'Inspection does not match'):
            wbi.read_saved_range(path, info, BASE, 1)

    def test_explicit_physical_and_source_limits(self):
        path = self.put('raw.wbi', snapshot())
        info = wbi.inspect_wbi(path)
        for address, size in [(BASE, wbi.MAX_READ_BYTES + 1), (BASE, 0), (-1, 1),
                              (BASE, True), (True, 1), ((1 << 64) - 1, 2)]:
            with self.subTest(address=address, size=size), self.assertRaisesRegex(ValueError, 'read range'):
                wbi.read_saved_range(path, info, address, size)
        with patch.object(wbi, 'MAX_SOURCE_BYTES', len(snapshot()) - 1), self.assertRaises(ValueError):
            wbi.inspect_wbi(path)

    def test_hashing_streams_bounded_reads_and_rechecks_short_reads(self):
        path = self.put('large.bin', b'NOPE')
        with path.open('r+b') as stream:
            stream.truncate(wbi.CHUNK_BYTES * 3 + 7)
        pread = os.pread
        requests = []
        def bounded(fd, size, offset):
            requests.append(size)
            return pread(fd, size, offset)
        with patch.object(wbi.os, 'pread', side_effect=bounded):
            info = wbi.inspect_wbi(path)
        self.assertFalse(info['has_wbi2_header'])
        self.assertGreater(len(requests), 6)
        self.assertLessEqual(max(requests), wbi.CHUNK_BYTES)
        path = self.put('raw.wbi', snapshot())
        metadata = 512 + 2 * PAGE
        def short(fd, size, offset):
            return b'' if offset == metadata else pread(fd, size, offset)
        with patch.object(wbi.os, 'pread', side_effect=short), self.assertRaisesRegex(ValueError, 'Truncated'):
            wbi.inspect_wbi(path)

    def test_symlink_parent_leaf_fifo_and_devices_are_rejected(self):
        path = self.put('raw.wbi', snapshot())
        alias = self.root / 'alias'; alias.symlink_to(path)
        parent = self.root / 'parent'; parent.symlink_to(self.root, target_is_directory=True)
        fifo = self.root / 'fifo'; os.mkfifo(fifo)
        for candidate in (alias, parent / path.name, fifo, Path('/dev/null')):
            with self.subTest(candidate=candidate), self.assertRaises((ValueError, OSError)):
                wbi.inspect_wbi(candidate)
        with alias.open('rb') as source, self.assertRaises((ValueError, OSError)):
            wbi.inspect_wbi(source)
        with open('/dev/null', 'rb') as source, self.assertRaises(ValueError):
            wbi.inspect_wbi(source.fileno())

    def test_readback_digest_catches_mutation_even_without_timestamp_comparison(self):
        path = self.put('raw.wbi', snapshot())
        inspect = wbi._inspect
        def mutate(*args):
            result = inspect(*args)
            with path.open('r+b') as writer:
                writer.seek(512); writer.write(b'Z')
            return result
        with patch.object(wbi, '_inspect', side_effect=mutate), patch.object(
                wbi, 'identity', side_effect=lambda s: (s.st_dev, s.st_ino, s.st_size)):
            with self.assertRaisesRegex(ValueError, 'readback'):
                wbi.inspect_wbi(path)

    def test_named_inode_replacement_is_rejected(self):
        path = self.put('raw.wbi', snapshot())
        inspect = wbi._inspect
        def replace(*args):
            result = inspect(*args)
            replacement = self.put('replacement.wbi', snapshot())
            replacement.replace(path)
            return result
        with patch.object(wbi, '_inspect', side_effect=replace), self.assertRaisesRegex(ValueError, 'changed'):
            wbi.inspect_wbi(path)

    def test_parent_symlink_swap_during_read_is_rejected(self):
        child = self.root / 'child'; child.mkdir()
        path = child / 'raw.wbi'; path.write_bytes(snapshot())
        inspect = wbi._inspect
        def swap(*args):
            result = inspect(*args)
            child.rename(self.root / 'moved')
            child.symlink_to(self.root / 'moved', target_is_directory=True)
            return result
        with patch.object(wbi, '_inspect', side_effect=swap), self.assertRaises((ValueError, OSError)):
            wbi.inspect_wbi(path)

    def test_synthetic_bound_cache_match_mismatch_and_unchecked_ap_change(self):
        source, ap, facts = self.cache_fixture()
        with patch.object(wbi, '_load_facts', return_value={'wbi': facts}):
            result = wbi.compare_cache(source, ap)
            self.assertEqual(result['cache_compatibility'], 'matched_at_checked_pages')
            self.assertEqual(result['checked_pages'], 4)
            self.assertEqual(result['mismatches'], [])
            self.assertTrue(result['reference_ap_identity_matches'])
            with ap.open('r+b') as stream:
                stream.seek(4 * PAGE); stream.write(b'Z')
            unchecked = wbi.compare_cache(source, ap)
            self.assertEqual(unchecked['cache_compatibility'], 'matched_at_checked_pages')
            self.assertFalse(unchecked['reference_ap_identity_matches'])
            self.assertEqual(unchecked['whole_image_compatibility'], 'unknown')
            self.assertFalse(unchecked['resume_executed'])
            self.assertFalse(unchecked['fullboot_verified'])
            with ap.open('r+b') as stream:
                stream.seek(2 * PAGE + 3); stream.write(b'Z')
            changed = wbi.compare_cache(source, ap)
        self.assertEqual(changed['cache_compatibility'], 'incompatible_at_checked_pages')
        self.assertEqual(changed['checked_pages'], 4)
        self.assertEqual(changed['mismatches'][0]['file_page_index'], 2)
        self.assertEqual(changed['mismatches'][0]['different_bytes'], 1)
        self.assertIn('SYNTHETIC TEST', changed['scope'])

    def test_zero_padded_binding_requires_exact_prefix_length_and_only_zero_tail(self):
        source, ap, facts = self.cache_fixture()
        raw = source.read_bytes()
        padded = self.put('padded.wbi', raw + bytes(512))
        result = wbi._compare_cache(padded, ap, facts)
        self.assertEqual(result['binding'], 'official_zero_padded')
        self.assertEqual(result['checked_pages'], 4)
        for name, invalid in [('nonzero-tail', raw + bytes(511) + b'x'),
                              ('wrong-prefix', raw[:512] + b'Z' + raw[513:] + bytes(512)),
                              ('wrong-length', raw + bytes(513))]:
            path = self.put(name, invalid)
            with patch.object(wbi, '_saved_range', side_effect=AssertionError('must not use anchors')):
                result = wbi._compare_cache(path, ap, facts)
            self.assertIsNone(result['binding'])
            self.assertEqual(result['cache_compatibility'], 'unknown')
            self.assertEqual(result['checked_pages'], 0)

    def test_unknown_sha_never_uses_bound_anchors(self):
        source, ap, facts = self.cache_fixture()
        facts['raw_sha256'] = '0' * 64
        with patch.object(wbi, '_saved_range', side_effect=AssertionError('unbound anchors')):
            result = wbi._compare_cache(source, ap, facts)
        self.assertEqual(result['cache_compatibility'], 'unknown')
        self.assertEqual(result['checked_pages'], 0)
        self.assertEqual(result['mismatches'], [])
        result = wbi.compare_cache(source, ap)
        self.assertEqual(result['cache_compatibility'], 'unknown')
        self.assertEqual(result['checked_pages'], 0)

    def test_bound_descriptor_is_revalidated_and_missing_ap_pages_mismatch(self):
        source, ap, facts = self.cache_fixture()
        ap.write_bytes(b'')
        result = wbi._compare_cache(source, ap, facts)
        self.assertEqual(result['checked_pages'], 4)
        self.assertEqual(len(result['mismatches']), 4)
        self.assertEqual(result['mismatches'][0]['different_bytes'], PAGE)
        raw = bytearray(source.read_bytes())
        raw[512 + 4 * PAGE + 8] ^= 1
        source.write_bytes(raw)
        facts['raw_sha256'] = hashlib.sha256(raw).hexdigest()
        with self.assertRaisesRegex(ValueError, 'descriptor mapping/index'):
            wbi._compare_cache(source, ap, facts)

    def test_cache_also_rejects_symlink_ap(self):
        source, ap, facts = self.cache_fixture()
        alias = self.root / 'ap-alias'; alias.symlink_to(ap)
        with self.assertRaises((ValueError, OSError)):
            wbi._compare_cache(source, alias, facts)

    def test_fixed_public_facts_and_tamper_rejection(self):
        facts = wbi._load_facts()
        self.assertEqual(facts['model'], 'ILCE-7CM2')
        self.assertFalse(facts['loader_executed'])
        self.assertFalse(facts['cold_chain']['guest_executed'])
        self.assertEqual(len(facts['loader']['events']), 25)
        self.assertEqual([row['index'] for row in facts['loader']['events']], list(range(25)))
        self.assertEqual(facts['wbi']['magic_compare_bytes'], 4)
        self.assertEqual(facts['wbi']['drop_request_bytes'], 512)
        self.assertEqual(len(facts['wbi']['cache']['anchors']), 4)
        tampered = self.put('facts.json', json.dumps(facts).encode())
        with patch.object(wbi, 'FACTS_PATH', tampered), self.assertRaisesRegex(ValueError, 'bound facts changed'):
            wbi._load_facts()


if __name__ == '__main__':
    unittest.main()
