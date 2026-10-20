#!/usr/bin/env python3
import runpy
from pathlib import Path
import unittest
import ctypes
import os
import struct

API = runpy.run_path(str(Path(__file__).with_name('system-sound-region.py')))
validate = API['validate_reservation']


class SoundReservation(unittest.TestCase):
    def test_original_neighbors(self):
        workspace = ('memrsv=0x0BE00000@0x410200000:uc\n'
                     'memrsv=0x00100000@0x41e000000:uc\n'
                     'memrsv=0xCFC00000@0x430400000:uc')
        self.assertEqual(validate(workspace), API['RESERVATION'])

    def test_overlap_and_duplicate(self):
        for workspace in ('memrsv=0x20000@0x41d000000:uc',
                          'memrsv=0x20001@0x41cffffff:uc',
                          'memrsv=0x10000@0x41d010000:uc'):
            with self.subTest(workspace=workspace), self.assertRaises(ValueError):
                validate(workspace)

    def test_unknown_or_missing(self):
        for workspace in ('', None, 'ordinary_parameter=1', 'memrsv=bad',
                          'memrsv=0@0x400000000',
                          'memrsv=0x20000@0xffffffffffff0000'):
            with self.subTest(workspace=workspace), self.assertRaises(ValueError):
                validate(workspace)

    def test_exact_adjacent_ranges(self):
        self.assertEqual(validate('memrsv=0x1000@0x41cfff000:uc '
                                  'memrsv=0x1000@0x41d020000:uc'), API['RESERVATION'])


@unittest.skipUnless(os.environ.get('A7C2_LIBFDT'), 'Set A7C2_LIBFDT to exercise real FDT reservations')
class SoundDeviceTree(unittest.TestCase):
    def tree(self, ram_size=0x200000000):
        fdt = ctypes.CDLL(os.environ['A7C2_LIBFDT'])
        buffer = ctypes.create_string_buffer(65536)
        self.assertEqual(fdt.fdt_create_empty_tree(buffer, len(buffer)), 0)
        for key, value in ((b'compatible', b'linux,dummy-virt\0'),
                           (b'#address-cells', struct.pack('>I', 2)),
                           (b'#size-cells', struct.pack('>I', 2))):
            self.assertEqual(fdt.fdt_setprop(buffer, 0, key, value, len(value)), 0)
        self.assertGreaterEqual(fdt.fdt_add_subnode(buffer, 0, b'chosen'), 0)
        node = fdt.fdt_add_subnode(buffer, 0, b'memory@400000000')
        for key, value in ((b'device_type', b'memory\0'),
                           (b'reg', struct.pack('>QQ', 0x400000000, ram_size))):
            self.assertEqual(fdt.fdt_setprop(buffer, node, key, value, len(value)), 0)
        fdt.fdt_add_mem_rsv.argtypes = [ctypes.c_void_p, ctypes.c_uint64, ctypes.c_uint64]
        return fdt, buffer

    def test_real_reservation_and_idempotence(self):
        fdt, buffer = self.tree()
        command = 'fullsystem.sound-owner=1 ' + API['RESERVATION']
        API['add_dtb_reservation'](fdt, buffer, command)
        self.assertEqual(fdt.fdt_num_mem_rsv(buffer), 1)
        API['add_dtb_reservation'](fdt, buffer, command)
        self.assertEqual(fdt.fdt_num_mem_rsv(buffer), 1)
        start, size = ctypes.c_uint64(), ctypes.c_uint64()
        self.assertEqual(fdt.fdt_get_mem_rsv(buffer, 0, ctypes.byref(start), ctypes.byref(size)), 0)
        self.assertEqual((start.value, size.value), (API['PHYSICAL'], API['CAPACITY']))

    def test_foreign_reservation(self):
        for start, size in ((API['PHYSICAL'], API['CAPACITY']), (API['PHYSICAL'] - 4096, 8192)):
            fdt, buffer = self.tree()
            self.assertEqual(fdt.fdt_add_mem_rsv(buffer, start, size), 0)
            with self.assertRaises(ValueError):
                API['add_dtb_reservation'](fdt, buffer, API['RESERVATION'])

    def test_not_in_board_ram(self):
        fdt, buffer = self.tree(ram_size=0x1000000)
        with self.assertRaises(ValueError):
            API['add_dtb_reservation'](fdt, buffer, API['RESERVATION'])

    def test_nested_memory_is_not_physical_ram(self):
        fdt, buffer = self.tree(ram_size=0x1000000)
        parent = fdt.fdt_add_subnode(buffer, 0, b'translated-bus')
        for key, value in ((b'#address-cells', struct.pack('>I', 2)), (b'#size-cells', struct.pack('>I', 2)),
                           (b'ranges', struct.pack('>QQQ', API['PHYSICAL'], 0x700000000, API['CAPACITY']))):
            self.assertEqual(fdt.fdt_setprop(buffer, parent, key, value, len(value)), 0)
        node = fdt.fdt_add_subnode(buffer, parent, b'memory')
        for key, value in ((b'device_type', b'memory\0'), (b'reg', struct.pack('>QQ', API['PHYSICAL'], API['CAPACITY']))):
            self.assertEqual(fdt.fdt_setprop(buffer, node, key, value, len(value)), 0)
        with self.assertRaisesRegex(ValueError, 'Nested or translated RAM'):
            API['add_dtb_reservation'](fdt, buffer, API['RESERVATION'])

    def test_invalid_or_overflowing_ram_is_refused(self):
        for size in (0, 0xffffffffffffffff):
            fdt, buffer = self.tree(ram_size=size)
            with self.subTest(size=size), self.assertRaisesRegex(ValueError, 'declared board RAM'):
                API['add_dtb_reservation'](fdt, buffer, API['RESERVATION'])

    def test_adapter_does_not_repeat_insertion(self):
        text = '# Reject overlapping static virtual mappings before booting the unmodified kernel.\n'
        changed = API['adapt_script'](text)
        self.assertEqual(API['adapt_script'](changed), changed)
        self.assertEqual(changed.count('FULLSYSTEM_SYSTEM_SOUND_RESERVATION'), 1)

    def reserved_tree(self, cells=2):
        fdt, buffer = self.tree()
        node = fdt.fdt_add_subnode(buffer, 0, b'reserved-memory')
        for key, value in ((b'#address-cells', struct.pack('>I', cells)),
                           (b'#size-cells', struct.pack('>I', cells)), (b'ranges', b'')):
            self.assertEqual(fdt.fdt_setprop(buffer, node, key, value, len(value)), 0)
        child = fdt.fdt_add_subnode(buffer, node, b'foreign')
        return fdt, buffer, child

    def test_reserved_memory_foreign_owner(self):
        fdt, buffer, child = self.reserved_tree()
        reg = struct.pack('>QQ', API['PHYSICAL'], API['CAPACITY'])
        self.assertEqual(fdt.fdt_setprop(buffer, child, b'reg', reg, len(reg)), 0)
        self.assertEqual(fdt.fdt_setprop(buffer, child, b'no-map', b'', 0), 0)
        with self.assertRaises(ValueError):
            API['add_dtb_reservation'](fdt, buffer, API['RESERVATION'])

    def test_dynamic_reserved_memory_is_unknown(self):
        fdt, buffer, child = self.reserved_tree()
        size = struct.pack('>Q', API['CAPACITY'])
        self.assertEqual(fdt.fdt_setprop(buffer, child, b'size', size, len(size)), 0)
        with self.assertRaises(ValueError):
            API['add_dtb_reservation'](fdt, buffer, API['RESERVATION'])

    def test_reserved_memory_one_cell_nonoverlap(self):
        fdt, buffer, child = self.reserved_tree(cells=1)
        reg = struct.pack('>II', 0x60000000, 0x100000)
        self.assertEqual(fdt.fdt_setprop(buffer, child, b'reg', reg, len(reg)), 0)
        API['add_dtb_reservation'](fdt, buffer, API['RESERVATION'])
        self.assertEqual(fdt.fdt_num_mem_rsv(buffer), 1)


if __name__ == '__main__':
    unittest.main()
