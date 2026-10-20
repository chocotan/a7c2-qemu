import ctypes
import os
from pathlib import Path
import runpy
import struct
import tempfile
import unittest

HERE = Path(__file__).resolve().parent
REGION = runpy.run_path(str(HERE / 'native-sound-region.py'))
OWN = 'fullsystem.sound-owner=1 ' + REGION['API']['RESERVATION']
WORK = 'memrsv=0x1000@0x410000000:uc'


class Validation(unittest.TestCase):
    def test_invalid_final_commands_rejected_before_dtb_access(self):
        for command in ('', WORK, OWN, WORK+' '+OWN+' '+OWN,
                        WORK+' '+OWN+' fullsystem.sound-owner=0',
                        WORK+' '+OWN+' memrsv=0x1000@0x41d010000:uc',
                        WORK+' '+OWN+' memrsv=131072@17666408448:uc',
                        ' '.join(f'memrsv=0x1000@{0x410000000+i*4096:#x}:uc' for i in range(16))+' '+OWN):
            with self.subTest(command=command), self.assertRaises(ValueError):
                REGION['reserve'](None,None,command)

    def test_sixteen_reservations_allowed_before_dtb(self):
        command = ' '.join(f'memrsv=0x1000@{0x410000000+i*4096:#x}:uc' for i in range(15))+' '+OWN
        REGION['API']['validate_final_command'](command)


@unittest.skipUnless(os.environ.get('A7C2_LIBFDT'), 'Set A7C2_LIBFDT')
class DeviceTree(unittest.TestCase):
    def test_offline_actual_board_rejects_conflicting_bootargs(self):
        fixture = runpy.run_path(str(HERE / 'device-models/test-system-sound-region.py'))['SoundDeviceTree']
        extras = ('', ' memrsv=0x1000@0x41d010000:uc', ' fullsystem.sound-owner=0',
                  ' '+REGION['API']['RESERVATION'],
                  ' '+' '.join(f'memrsv=0x1000@{0x410000000+i*4096:#x}:uc' for i in range(16)))
        for extra in extras:
            with self.subTest(extra=extra), tempfile.TemporaryDirectory() as temporary:
                fdt,buffer=fixture.tree(self,0x140000000)
                REGION['reserve'](fdt,buffer,WORK+' '+OWN)
                command=(WORK+' '+OWN+extra).encode()+b'\0'
                chosen=fdt.fdt_path_offset(buffer,b'/chosen')
                self.assertEqual(fdt.fdt_setprop(buffer,chosen,b'bootargs',command,len(command)),0)
                self.assertEqual(fdt.fdt_pack(buffer),0)
                run=Path(temporary)
                (run/'virt.dtb').write_bytes(buffer.raw[:struct.unpack_from('>I',buffer.raw,4)[0]])
                if extra:
                    with self.assertRaises(ValueError):
                        REGION['verify_reservation'](run,os.environ['A7C2_LIBFDT'])
                else:
                    self.assertEqual(REGION['verify_reservation'](run,os.environ['A7C2_LIBFDT']),WORK+' '+OWN)

    def test_owner_identity_and_idempotence(self):
        fixture = runpy.run_path(str(HERE / 'device-models/test-system-sound-region.py'))['SoundDeviceTree']
        fdt,buffer = fixture.tree(self,0x140000000)
        REGION['reserve'](fdt,buffer,WORK+' '+OWN)
        REGION['reserve'](fdt,buffer,WORK+' '+OWN)
        self.assertEqual(fdt.fdt_num_mem_rsv(buffer),1)
        fdt.fdt_getprop.restype=ctypes.c_void_p
        chosen=fdt.fdt_path_offset(buffer,b'/chosen');length=ctypes.c_int()
        p=fdt.fdt_getprop(buffer,chosen,b'qemu,a7c2-system-sound-owner',ctypes.byref(length))
        self.assertEqual(ctypes.string_at(p,length.value),struct.pack('>QQ',0x41d000000,0x20000))

    @unittest.skipUnless(os.environ.get('A7C2_NATIVE_DTB'), 'Set A7C2_NATIVE_DTB without sound owner')
    def test_saved_native_board_compatible_with_pin_owner(self):
        fdt=ctypes.CDLL(os.environ['A7C2_LIBFDT']);fdt.fdt_getprop.restype=ctypes.c_void_p
        source=ctypes.create_string_buffer(Path(os.environ['A7C2_NATIVE_DTB']).read_bytes())
        buffer=ctypes.create_string_buffer(65536)
        self.assertEqual(fdt.fdt_open_into(source,buffer,len(buffer)),0)
        chosen=fdt.fdt_path_offset(buffer,b'/chosen');length=ctypes.c_int()
        p=fdt.fdt_getprop(buffer,chosen,b'bootargs',ctypes.byref(length))
        command=ctypes.string_at(p,length.value).rstrip(b'\0').decode()+' '+OWN
        before=fdt.fdt_num_mem_rsv(buffer)
        REGION['reserve'](fdt,buffer,command)
        self.assertEqual(fdt.fdt_num_mem_rsv(buffer),before+1)
        pin=runpy.run_path(str(HERE/'native-pin-control-region.py'))
        pin['reserve'](fdt,buffer,command)
        self.assertEqual(fdt.fdt_num_mem_rsv(buffer),before+1)


if __name__ == '__main__':
    unittest.main()
