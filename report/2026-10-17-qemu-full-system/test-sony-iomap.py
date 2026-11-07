#!/usr/bin/env python3
"""Prove the Sony iomap declarations come from the signed package and patch cleanly.

Uses the real libfdt shipped in the local QEMU tools tree; skips when it or the
signed package's board DTB is unavailable, so the test never invents evidence.
"""
import ctypes
import importlib.util
from pathlib import Path
import unittest

HERE = Path(__file__).resolve().parent
LIB = HERE / 'runtime/sources/qemu-tools/usr/lib/libfdt.so.1'
OFFICIAL_DTB = (HERE.parents[1] / 'analysis/extracted/firmware/0800_appli/setting/cxd90057.dtb')
BOARD = HERE / 'runtime/analysis/boards/virt-four.dtb'

spec = importlib.util.spec_from_file_location('sony_iomap', HERE / 'sony-iomap.py')
IOMAP = importlib.util.module_from_spec(spec)
spec.loader.exec_module(IOMAP)


class SonyIomapDeclarations(unittest.TestCase):
    @unittest.skipUnless(OFFICIAL_DTB.is_file(), 'signed package board DTB not present')
    def test_declarations_match_the_signed_package_dtb(self):
        found = IOMAP.read_iomap_nodes(OFFICIAL_DTB.read_bytes())
        self.assertEqual(found, IOMAP.IOMAP_NODES)
        self.assertEqual(len(found), 3)
        # The window the proprietary mmc driver hardcodes via IO_ADDRESS().
        name, phys, virt, size, memtype = found[0]
        self.assertEqual((phys, virt, size, memtype), (0xF0000000, 0xFFFFFFFFF0000000, 0x0E000000, 1))
        self.assertEqual(virt | 0xF1388000, 0xFFFFFFFFF1388000)

    def test_parser_rejects_truncated_input(self):
        with self.assertRaises(ValueError):
            IOMAP.read_iomap_nodes(b'not a device tree')


@unittest.skipUnless(LIB.is_file() and BOARD.is_file(), 'local libfdt or board DTB missing')
class SonyIomapDtbPatch(unittest.TestCase):
    def open_board(self):
        fdt = ctypes.CDLL(str(LIB))
        source = ctypes.create_string_buffer(BOARD.read_bytes())
        self.assertEqual(fdt.fdt_pack(source), 0)
        buffer = ctypes.create_string_buffer(65536)
        self.assertEqual(fdt.fdt_open_into(source, buffer, len(buffer)), 0)
        fdt.fdt_getprop.restype = ctypes.c_void_p
        return fdt, buffer

    def test_patch_adds_three_nodes_with_exact_byte_values(self):
        fdt, buffer = self.open_board()
        self.assertEqual(IOMAP.add_iomap_nodes(fdt, buffer), 3)
        for name, phys, virt, size, memtype in IOMAP.IOMAP_NODES:
            node = fdt.fdt_path_offset(buffer, ('/' + name).encode())
            self.assertGreaterEqual(node, 0, name)
            for key, value in (('device_type', b'iomap\0'), ('phys', phys.to_bytes(8, 'big')),
                               ('virt', virt.to_bytes(8, 'big')), ('size', size.to_bytes(8, 'big')),
                               ('memtype', memtype.to_bytes(4, 'big'))):
                length = ctypes.c_int()
                pointer = fdt.fdt_getprop(buffer, node, key.encode(), ctypes.byref(length))
                self.assertTrue(pointer, '%s.%s missing' % (name, key))
                self.assertEqual(ctypes.string_at(pointer, length.value), value, '%s.%s' % (name, key))

    def test_patch_is_idempotent_and_rejects_mismatch(self):
        fdt, buffer = self.open_board()
        self.assertEqual(IOMAP.add_iomap_nodes(fdt, buffer), 3)
        self.assertEqual(IOMAP.add_iomap_nodes(fdt, buffer), 0)
        node = fdt.fdt_path_offset(buffer, b'/esram@0xfe000000')
        self.assertGreaterEqual(node, 0)
        self.assertEqual(fdt.fdt_setprop(buffer, node, b'memtype', (2).to_bytes(4, 'big'), 4), 0)
        with self.assertRaisesRegex(ValueError, 'differs'):
            IOMAP.add_iomap_nodes(fdt, buffer)

    def add_shims(self,fdt,buffer):
        for name,phys,virt,size,memtype in IOMAP.ADAPTER_SHIMS:
            root=fdt.fdt_path_offset(buffer,b'/')
            node=fdt.fdt_add_subnode(buffer,root,name.encode())
            self.assertGreaterEqual(node,0)
            values={'device_type':b'iomap\0','phys':phys.to_bytes(8,'big'),
                    'virt':virt.to_bytes(8,'big'),'size':size.to_bytes(8,'big'),
                    'memtype':memtype.to_bytes(4,'big')}
            for key,value in values.items():
                self.assertEqual(fdt.fdt_setprop(buffer,node,key.encode(),value,len(value)),0)

    def test_fresh_adapter_shims_are_retired_without_touching_ram(self):
        fdt,buffer=self.open_board()
        node=fdt.fdt_path_offset(buffer,b'/memory@40000000')
        self.assertGreaterEqual(node,0)
        length=ctypes.c_int()
        pointer=fdt.fdt_getprop(buffer,node,b'reg',ctypes.byref(length))
        ram=ctypes.string_at(pointer,length.value)
        self.add_shims(fdt,buffer)
        self.assertEqual(IOMAP.add_iomap_nodes(fdt,buffer),3)
        for name,*_ in IOMAP.ADAPTER_SHIMS:
            self.assertLess(fdt.fdt_path_offset(buffer,('/'+name).encode()),0)
        node=fdt.fdt_path_offset(buffer,b'/memory@40000000')
        pointer=fdt.fdt_getprop(buffer,node,b'reg',ctypes.byref(length))
        self.assertEqual(ctypes.string_at(pointer,length.value),ram)
        self.assertEqual(IOMAP.add_iomap_nodes(fdt,buffer),0)

    def test_unknown_shim_geometry_is_rejected_before_deletion(self):
        fdt,buffer=self.open_board();self.add_shims(fdt,buffer)
        node=fdt.fdt_path_offset(buffer,b'/sony-scu-map')
        changed=(0x9000).to_bytes(8,'big')
        self.assertEqual(fdt.fdt_setprop(buffer,node,b'size',changed,len(changed)),0)
        with self.assertRaisesRegex(ValueError,'changed adapter'):
            IOMAP.add_iomap_nodes(fdt,buffer)
        for name,*_ in IOMAP.ADAPTER_SHIMS:
            self.assertGreaterEqual(fdt.fdt_path_offset(buffer,('/'+name).encode()),0)

@unittest.skipUnless((HERE / 'build-full-system.py').is_file(), 'build script missing')
class SonyIomapWiring(unittest.TestCase):
    def test_board_adapter_gains_the_iomap_patch_and_drops_conflicting_shims(self):
        text = (HERE / 'build-full-system.py').read_text()
        for marker in ('FULLSYSTEM_SONY_IOMAP', 'FULLSYSTEM_SONY_IOMAP_TIMER_GUARD',
                       'FULLSYSTEM_SONY_IOMAP_SUPERSEDES_SHIMS'):
            self.assertIn(marker, text, marker)
        # The insertion must be gated by the explicit cmdline token, never unconditional.
        self.assertIn('fullsystem.iomap=sony', text)
        self.assertIn('sony-iomap.py', text)

    def test_runner_exposes_the_explicit_flag_and_token(self):
        text = (HERE / 'run-full-system.py').read_text()
        self.assertIn("'--sony-iomap'", text)
        self.assertIn("choices=('off','sony')", text)
        self.assertIn("fullsystem.iomap=sony", text)

ADAPTER = HERE / 'runtime/official-demo/.a7c2/sessions/session-ijc2cbdf/runtime/analysis/qemu-kernel-probe.sh'


@unittest.skipUnless(ADAPTER.is_file(), 'a built runtime is required')
class SonyIomapAdapterWiring(unittest.TestCase):
    """The patched board-DTB block must stay a valid Python program.

    A previous revision guarded the whole ``high_ddr`` block, which also skipped the
    DDR memory-node relocation and made every RAM reservation fail; the unbalanced
    brace variant would have been caught here before booting.
    """

    def test_board_dtb_patch_block_compiles_and_guards_only_the_shim_nodes(self):
        text = ADAPTER.read_text()
        blocks = [part.split("\nPY\n", 1)[0] for part in text.split("<<'PY'\n")[1:]]
        bodies = [block for block in blocks if 'fullsystem.iomap=sony' in block]
        self.assertEqual(len(bodies), 1, 'the board DTB patch block must be unique')
        body = bodies[0]
        compile(body, 'board-dtb-patch', 'exec')
        self.assertIn('board_io = ', body)
        self.assertIn("fullsystem.iomap=sony", body)
        # the DDR relocation must NOT be inside the shim guard
        self.assertIn("if sys.argv[5] == '1':\n    # Minimal GPIO register backing", body)
        # the shim NODES are skipped per node; only the timer node uses a block guard
        self.assertNotIn("if sys.argv[5] == '1' and 'fullsystem.iomap=sony' not in sys.argv[3].split():\n    # Minimal GPIO", body)
        self.assertIn("({} if board_io else {", body)


if __name__ == '__main__':
    unittest.main()
