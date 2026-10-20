import base64
import hashlib
import io
from pathlib import Path
import tempfile
import unittest

from PIL import Image
from menu_live import display_snapshot_message


class DisplaySnapshotTests(unittest.TestCase):
    def test_actual_surface_bytes_and_source_label(self):
        with tempfile.TemporaryDirectory() as name:
            path=Path(name)/'display.ppm'
            image=Image.new('RGB',(640,480),(17,85,153));image.save(path,format='PPM')
            result=display_snapshot_message(path,7)
            self.assertEqual(result['info']['sequence'],7)
            self.assertIsNone(result['info']['pixel_source_seq'])
            self.assertEqual(result['info']['source'],'QMP ramfb display')
            self.assertEqual(result['info']['sha256'],hashlib.sha256(image.tobytes()).hexdigest())
            with Image.open(io.BytesIO(base64.b64decode(result['png']))) as decoded:
                self.assertEqual(decoded.tobytes(),image.tobytes())
            alias=path.with_name('alias');alias.symlink_to(path)
            with self.assertRaises(ValueError):display_snapshot_message(alias,8)
            Image.new('RGB',(1,1)).save(path,format='PPM')
            with self.assertRaises(ValueError):display_snapshot_message(path,8)
            image.save(path,format='PNG')
            with self.assertRaises(ValueError):display_snapshot_message(path,8)


if __name__=='__main__':unittest.main()
