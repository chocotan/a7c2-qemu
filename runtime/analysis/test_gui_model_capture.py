import base64
import struct
import unittest
from pathlib import Path
import shutil
import subprocess
import tempfile

from gui_model_capture import TYPES, PREFIX_BYTES, decode_model_export, fnv64


class ModelCaptureTests(unittest.TestCase):
    def test_snapshot_fields_and_rejections(self):
        entries=b''.join(struct.pack('<II',kind,size)+bytes(size) for kind,size in TYPES)
        entries+=struct.pack('<II',0x12345678,4)+b'NEWM'
        packet=struct.pack('<II',0,len(entries))+entries
        raw = bytearray(860+len(packet))
        raw[:8] = b'GMDL0003'
        struct.pack_into('<QQ10I', raw, 8, 7, fnv64(packet), 63, 1, 4, 1, 1, 125, 100, 1, 6, len(raw))
        offset = 64
        for kind, size in TYPES:
            struct.pack_into('<IIQ', raw, offset, kind, size, 7)
            offset += 16 + size
        self.assertEqual(offset, 852)
        raw[PREFIX_BYTES:-8]=packet
        checksum = 14695981039346656037
        for byte in raw[:-8]:
            checksum = ((checksum ^ byte) * 1099511628211) & ((1 << 64) - 1)
        struct.pack_into('<Q', raw, len(raw)-8, checksum)

        def exported(data):
            return b'GUI_MODEL_BEGIN\n' + base64.b64encode(data) + b'\nGUI_MODEL_END\n'

        data, info = decode_model_export(exported(raw))
        self.assertEqual(data, raw)
        self.assertEqual(info['packets'], 7)
        self.assertEqual(info['fixed_exposure']['iso'], 100)
        self.assertFalse(info['guest_exposure_queries_implemented'])
        self.assertFalse(info['cp_subscriptions_implemented'])
        self.assertEqual(info['models'][-1]['type'],0x12345678)
        self.assertEqual(info['models'][-1]['raw_hex'],b'NEWM'.hex())
        noisy = exported(raw)
        middle = noisy.index(b'\n') + 41
        record = (b'OBS GUI_MODEL_COMMITTED packets=1024 types=0x3f changed=0 bytes=748 '
                  b'input_fnv=e45054b418261e91 original_free=0 state=/tmp/gui-model-state.bin '
                  b'CP_subscriptions=unimplemented exposure_fixture=F4,1/125,ISO100\n')
        self.assertEqual(decode_model_export(noisy[:middle]+record+noisy[middle:])[0], raw)
        bad_body = bytearray(raw)
        bad_body[128] ^= 1
        with self.assertRaisesRegex(ValueError, 'checksum'):
            decode_model_export(exported(bad_body))
        for offset, value in [(0, 0), (24, 127), (28, 128), (48, 101), (68, 0xffffffff), (72, 8)]:
            with self.subTest(offset=offset):
                bad = bytearray(raw)
                struct.pack_into('<I', bad, offset, value)
                with self.assertRaises(ValueError):
                    decode_model_export(exported(bad))
        with self.assertRaises(ValueError):
            decode_model_export(exported(raw[:-1]))
        with tempfile.TemporaryDirectory() as name:
            directory=Path(name)
            binary=directory/'exporter'
            subprocess.run([shutil.which('cc'),'-x','c','-',str(Path(__file__).with_name('headless-osd-export.c')),
                            '-DHOSD_EXPORT_TEST','-DGUI_MODEL_EXPORT','-o',str(binary),'-Wall','-Wextra','-Werror'],
                           input='extern int hosd_export(const char *); int main(int n,char **v){return n==2?hosd_export(v[1]):2;}\n',
                           text=True,capture_output=True,check=True)
            snapshot=directory/'model.bin';snapshot.write_bytes(raw)
            output=subprocess.run([str(binary),str(snapshot)],capture_output=True,check=True)
            self.assertEqual(decode_model_export(output.stdout)[0],raw)
            snapshot.write_bytes(raw[:-1])
            failed=subprocess.run([str(binary),str(snapshot)],capture_output=True)
            self.assertNotEqual(failed.returncode,0)
            self.assertNotIn(b'GUI_MODEL_END',failed.stdout)


if __name__ == '__main__':
    unittest.main()
