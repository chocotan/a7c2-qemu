"""Actual native sound observation and independent evidence corruption checks."""
import ctypes
import json
import os
from pathlib import Path
import runpy
import shutil
import struct
import tempfile
import unittest

HERE = Path(__file__).resolve().parent
VERIFY = runpy.run_path(str(HERE / 'device-models/verify-system-sound-config.py'))['verify']


@unittest.skipUnless(os.environ.get('A7C2_NATIVE_SOUND_RUN'), 'Set A7C2_NATIVE_SOUND_RUN')
class NativeSoundEvidence(unittest.TestCase):
    def test_real_source_slices_and_original_waiters(self):
        proof = VERIFY(Path(os.environ['A7C2_NATIVE_SOUND_RUN']),native=True)
        self.assertTrue(proof['system_sound_memory_verified'])
        self.assertTrue(proof['system_sound_config_verified'])
        self.assertEqual(proof['default_table_count'],25)
        self.assertFalse(proof['whole_run_success_verified'])
        self.assertFalse(proof['audio_output_verified'])

    def test_memory_tail_profile_helper_free_and_bootargs_rejected(self):
        src = Path(os.environ['A7C2_NATIVE_SOUND_RUN'])
        for kind in ('source','tail','profile','helper','free','bootargs'):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as temporary:
                dst=Path(temporary)
                for name in ('console.log','runtime-manifest.json','summary.json','virt.dtb','system-sound-ram.bin'):
                    shutil.copyfile(src/name,dst/name)
                summary=json.loads((dst/'summary.json').read_text());summary['run']=str(dst)
                (dst/'summary.json').write_text(json.dumps(summary))
                if kind in ('source','tail'):
                    raw=bytearray((dst/'system-sound-ram.bin').read_bytes())
                    raw[0 if kind=='source' else -1]^=1
                    (dst/'system-sound-ram.bin').write_bytes(raw)
                elif kind in ('profile','helper'):
                    manifest=json.loads((dst/'runtime-manifest.json').read_text())
                    if kind=='profile':manifest['system_sound_owner']=False
                    else:manifest['selected_initramfs_verified_files']['simulation/system-sound-owner']='0'*64
                    (dst/'runtime-manifest.json').write_text(json.dumps(manifest))
                elif kind=='free':
                    lines=(dst/'console.log').read_text().splitlines(keepends=True)
                    (dst/'console.log').write_text(''.join(l for l in lines if not
                        (l.startswith('OBS FULL_AUDIO_NATIVE_REPLY_FREE ') and 'command=0x33f ' in l)))
                else:
                    fdt=ctypes.CDLL(str(HERE/'../sources/qemu-tools/usr/lib/libfdt.so.1'))
                    fdt.fdt_getprop.restype=ctypes.c_void_p
                    source=ctypes.create_string_buffer((dst/'virt.dtb').read_bytes())
                    buffer=ctypes.create_string_buffer(65536)
                    self.assertEqual(fdt.fdt_open_into(source,buffer,len(buffer)),0)
                    chosen=fdt.fdt_path_offset(buffer,b'/chosen');length=ctypes.c_int()
                    p=fdt.fdt_getprop(buffer,chosen,b'bootargs',ctypes.byref(length))
                    command=ctypes.string_at(p,length.value).rstrip(b'\0')+b' memrsv=0x1000@0x41d010000:uc\0'
                    self.assertEqual(fdt.fdt_setprop(buffer,chosen,b'bootargs',command,len(command)),0)
                    self.assertEqual(fdt.fdt_pack(buffer),0)
                    (dst/'virt.dtb').write_bytes(buffer.raw[:struct.unpack_from('>I',buffer.raw,4)[0]])
                with self.assertRaises((ValueError,StopIteration,KeyError)):
                    VERIFY(dst,native=True)


if __name__ == '__main__':
    unittest.main()
