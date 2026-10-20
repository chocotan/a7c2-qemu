#!/usr/bin/env python3
import ctypes
import os
from pathlib import Path
import runpy
import struct
import unittest

HERE = Path(__file__).resolve().parent
API = runpy.run_path(str(HERE / 'pin-buffer-region.py'))
REGION = runpy.run_path(str(HERE / 'reserved-region.py'))


class Workspace(unittest.TestCase):
    def test_original_end_boundary_and_declared_new_capacity(self):
        self.assertEqual(API['validate_reservation']('memrsv=0xcfc00000@0x430400000:uc'), API['RESERVATION'])
        self.assertEqual(API['CAPACITY'], API['SLOTS'] * API['SLOT_BYTES'])
        self.assertEqual(API['CP_VIRTUAL'], 0x80000000)

    def test_unknown_and_foreign_overlap_refused(self):
        for workspace in ('', 'memrsv=bad', 'memrsv=0x1000@0x500001000',
                          'memrsv=0x1001@0x4fffff000', 'memrsv=0x2000@0x500000000'):
            with self.subTest(workspace=workspace), self.assertRaises(ValueError):
                API['validate_reservation'](workspace)


@unittest.skipUnless(os.environ.get('A7C2_LIBFDT'), 'Set A7C2_LIBFDT for actual FDT reservation tests')
class DeviceTree(unittest.TestCase):
    def tree(self, ram_size=0x200000000):
        # Reuse only the independent minimal board fixture, never sound's API.
        helper = runpy.run_path(str(HERE / 'test-system-sound-region.py'))['SoundDeviceTree']
        return helper.tree(self, ram_size)

    def test_actual_reservation_readback_and_idempotence(self):
        fdt, buffer = self.tree()
        API['add_dtb_reservation'](fdt, buffer, API['RESERVATION'])
        API['add_dtb_reservation'](fdt, buffer, API['RESERVATION'])
        self.assertEqual(fdt.fdt_num_mem_rsv(buffer), 1)
        start, size = ctypes.c_uint64(), ctypes.c_uint64()
        self.assertEqual(fdt.fdt_get_mem_rsv(buffer, 0, ctypes.byref(start), ctypes.byref(size)), 0)
        self.assertEqual((start.value, size.value), (API['PHYSICAL'], API['CAPACITY']))

    def test_sound_and_control_have_distinct_owners(self):
        fdt, buffer = self.tree()
        sound = runpy.run_path(str(HERE / 'system-sound-region.py'))
        command = sound['RESERVATION'] + ' ' + API['RESERVATION']
        sound['add_dtb_reservation'](fdt, buffer, command)
        API['add_dtb_reservation'](fdt, buffer, command)
        self.assertEqual(fdt.fdt_num_mem_rsv(buffer), 2)

    def test_foreign_map_or_too_small_ram_refused(self):
        for size in (0x1000000, 0x200000000):
            fdt, buffer = self.tree(size)
            if size == 0x200000000:
                self.assertEqual(fdt.fdt_add_mem_rsv(buffer, API['PHYSICAL'], API['CAPACITY']), 0)
            with self.assertRaises(ValueError):
                API['add_dtb_reservation'](fdt, buffer, API['RESERVATION'])

    def test_every_reserved_memory_child_range_is_checked(self):
        fdt, buffer = self.tree()
        parent = fdt.fdt_add_subnode(buffer, 0, b'reserved-memory')
        child = fdt.fdt_add_subnode(buffer, parent, b'foreign')
        reg = struct.pack('>QQQQ', 0x60000000, 0x1000, API['PHYSICAL'], API['CAPACITY'])
        self.assertEqual(fdt.fdt_setprop(buffer, child, b'reg', reg, len(reg)), 0)
        with self.assertRaises(ValueError):
            API['add_dtb_reservation'](fdt, buffer, API['RESERVATION'])

    def test_command_geometry_and_duplicates_are_refused(self):
        for command in (API['RESERVATION'] + ' ' + API['RESERVATION'], 'memrsv=0x1000@0x500000000:uc'):
            fdt, buffer = self.tree()
            with self.assertRaises(ValueError):
                REGION['add_reservation'](fdt, buffer, command, physical=API['PHYSICAL'], capacity=API['CAPACITY'], command=command, key=API['KEY'])

    def test_saved_native_board_copy_has_declared_ram_and_separate_sound_owner(self):
        path = HERE / 'runtime/analysis/runs/run-sgnf9rtx/virt.dtb'
        if not path.is_file():
            self.skipTest('Private completed native board not present')
        fdt = ctypes.CDLL(os.environ['A7C2_LIBFDT'])
        source = ctypes.create_string_buffer(path.read_bytes());buffer = ctypes.create_string_buffer(65536)
        self.assertEqual(fdt.fdt_open_into(source, buffer, len(buffer)), 0)
        fdt.fdt_getprop.restype = ctypes.c_void_p
        chosen = fdt.fdt_path_offset(buffer, b'/chosen');size = ctypes.c_int()
        pointer = fdt.fdt_getprop(buffer, chosen, b'bootargs', ctypes.byref(size))
        self.assertTrue(pointer and size.value > 0)
        command = ctypes.string_at(pointer, size.value).rstrip(b'\0').decode() + ' ' + API['RESERVATION']
        before = fdt.fdt_num_mem_rsv(buffer)
        API['add_dtb_reservation'](fdt, buffer, command)
        self.assertEqual(fdt.fdt_num_mem_rsv(buffer), before + 1)

    def test_nested_translated_ram_cannot_supply_physical_backing(self):
        fdt, buffer = self.tree(0x1000000)
        bus = fdt.fdt_add_subnode(buffer, 0, b'translated-bus')
        for key, value in ((b'#address-cells', struct.pack('>I', 2)), (b'#size-cells', struct.pack('>I', 2)),
                           (b'ranges', struct.pack('>QQQ', API['PHYSICAL'], 0x600000000, API['CAPACITY']))):
            self.assertEqual(fdt.fdt_setprop(buffer, bus, key, value, len(value)), 0)
        child = fdt.fdt_add_subnode(buffer, bus, b'memory@500000000')
        for key, value in ((b'device_type', b'memory\0'), (b'reg', struct.pack('>QQ', API['PHYSICAL'], API['CAPACITY']))):
            self.assertEqual(fdt.fdt_setprop(buffer, child, key, value, len(value)), 0)
        with self.assertRaisesRegex(ValueError, 'Nested or translated RAM'):
            API['add_dtb_reservation'](fdt, buffer, API['RESERVATION'])

    def test_overflowing_and_zero_ram_ranges_refused(self):
        for size in (0, 0xffffffffffffffff):
            fdt, buffer = self.tree(size)
            with self.subTest(size=size), self.assertRaisesRegex(ValueError, 'declared board RAM'):
                API['add_dtb_reservation'](fdt, buffer, API['RESERVATION'])


if __name__ == '__main__':
    unittest.main()
