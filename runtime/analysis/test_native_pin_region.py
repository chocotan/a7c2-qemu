import ctypes
import os
from pathlib import Path
import runpy
import struct
import unittest

HERE = Path(__file__).resolve().parent
REGION = runpy.run_path(str(HERE / 'native-pin-control-region.py'))
SHARED = HERE / 'device-models'
OWN = 'fullsystem.pin-control-memory=1 memrsv=0x00002000@0x500000000:uc'
WORK = 'memrsv=0x1000@0x410000000:uc'


class Validation(unittest.TestCase):
    def test_conflicts_rejected_before_dtb_access(self):
        cases = ['', WORK, OWN, WORK + ' ' + OWN + ' ' + OWN,
                 WORK + ' ' + OWN + ' fullsystem.pin-control-memory=0',
                 WORK + ' ' + OWN + ' memrsv=0x1000@0x500001000:uc',
                 WORK + ' ' + OWN + ' memrsv=8192@21474836480:uc',
                 ' '.join(f'memrsv=0x1000@{0x410000000+i*4096:#x}' for i in range(16)) + ' ' + OWN]
        for command in cases:
            with self.subTest(command=command), self.assertRaises(ValueError):
                REGION['reserve'](None, None, command)


@unittest.skipUnless(os.environ.get('A7C2_LIBFDT'), 'Set A7C2_LIBFDT')
class DeviceTree(unittest.TestCase):
    def test_identity_and_real_reservation(self):
        fixture = runpy.run_path(str(SHARED / 'test-system-sound-region.py'))['SoundDeviceTree']
        fdt, buffer = fixture.tree(self, 0x140000000)
        REGION['reserve'](fdt, buffer, WORK + ' ' + OWN)
        REGION['reserve'](fdt, buffer, WORK + ' ' + OWN)
        self.assertEqual(fdt.fdt_num_mem_rsv(buffer), 1)
        start, size = ctypes.c_uint64(), ctypes.c_uint64()
        self.assertEqual(fdt.fdt_get_mem_rsv(buffer, 0, ctypes.byref(start), ctypes.byref(size)), 0)
        self.assertEqual((start.value, size.value), (0x500000000, 8192))
        chosen = fdt.fdt_path_offset(buffer, b'/chosen')
        length = ctypes.c_int()
        p = fdt.fdt_getprop(buffer, chosen, REGION['API']['KEY'], ctypes.byref(length))
        self.assertEqual(ctypes.string_at(p, length.value), struct.pack('>QQ', 0x500000000, 8192))

    @unittest.skipUnless(os.environ.get('A7C2_NATIVE_DTB'), 'Set A7C2_NATIVE_DTB for saved native board')
    def test_saved_native_board_copy(self):
        fdt = ctypes.CDLL(os.environ['A7C2_LIBFDT'])
        source = ctypes.create_string_buffer(Path(os.environ['A7C2_NATIVE_DTB']).read_bytes())
        buffer = ctypes.create_string_buffer(65536)
        self.assertEqual(fdt.fdt_open_into(source, buffer, len(buffer)), 0)
        fdt.fdt_getprop.restype = ctypes.c_void_p
        chosen, length = fdt.fdt_path_offset(buffer, b'/chosen'), ctypes.c_int()
        p = fdt.fdt_getprop(buffer, chosen, b'bootargs', ctypes.byref(length))
        command = ctypes.string_at(p, length.value).rstrip(b'\0').decode() + ' ' + OWN
        before = fdt.fdt_num_mem_rsv(buffer)
        REGION['reserve'](fdt, buffer, command)
        self.assertEqual(fdt.fdt_num_mem_rsv(buffer), before + 1)


if __name__ == '__main__':
    unittest.main()
