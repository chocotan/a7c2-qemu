import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

HERE=Path(__file__).resolve().parent


@unittest.skipUnless(os.environ.get('A7C2_FSYS_CAMERA_FLAGS_RUN'),'Set A7C2_FSYS_CAMERA_FLAGS_RUN')
class MediaCameraFlags(unittest.TestCase):
    def test_real_original_fsys_image_and_camera_flags(self):
        run=Path(os.environ['A7C2_FSYS_CAMERA_FLAGS_RUN'])
        result=subprocess.run(['python3',str(HERE/'verify-media-image.py'),'--camera-flags',str(run)],
                              capture_output=True,text=True,timeout=30)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        self.assertTrue(json.loads((run/'media-result.json').read_text())['camera_mount_flags_0x100_verified'])

    def test_missing_camera_flags_or_corrupt_export_removes_old_success(self):
        src=Path(os.environ['A7C2_FSYS_CAMERA_FLAGS_RUN'])
        for kind in ('flags','image'):
            with self.subTest(kind=kind),tempfile.TemporaryDirectory() as temporary:
                dst=Path(temporary)
                for name in ('console.log','media-disk.img'):
                    shutil.copyfile(src/name,dst/name)
                (dst/'media-result.json').write_text(json.dumps({'check':'ORIGINAL_FSYS_DISK_PASS',
                                                               'camera_mount_flags_0x100_verified':True}))
                if kind=='flags':
                    text=(dst/'console.log').read_text();self.assertIn('mount_flags=0x100',text)
                    (dst/'console.log').write_text(text.replace('mount_flags=0x100','mount_flags=0'))
                else:
                    data=bytearray((dst/'media-disk.img').read_bytes());data[-1]^=1
                    (dst/'media-disk.img').write_bytes(data)
                result=subprocess.run(['python3',str(HERE/'verify-media-image.py'),'--camera-flags',str(dst)],
                                      capture_output=True,text=True,timeout=30)
                self.assertEqual(result.returncode,2,result.stdout+result.stderr)
                proof=json.loads((dst/'media-result.json').read_text())
                self.assertEqual(proof['check'],'ORIGINAL_FSYS_DISK_FAIL')
                self.assertFalse(proof['camera_mount_flags_0x100_verified'])


if __name__=='__main__':unittest.main()
