import json
from pathlib import Path
import runpy
import subprocess
import sys
import tempfile
import unittest

HERE=Path(__file__).resolve().parent
API=runpy.run_path(str(HERE/'factory_images.py'))


class FactoryImagesTest(unittest.TestCase):
    def test_layout_rejects_missing_and_duplicate_partitions(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'mount.conf'
            path.write_text('/dev/nflasha1 none vfat 4194304 16384\n')
            with self.assertRaises(ValueError):API['layout'](path)
            path.write_text(path.read_text()*2)
            with self.assertRaises(ValueError):API['layout'](path)

    def test_fat_native_fsck_and_regular_symlink_readback(self):
        # Isolate vendor import from unrelated tests' Python module namespace.
        code='''import io,runpy,stat,sys,tempfile
from pathlib import Path
sys.path.insert(0,str(Path(sys.argv[1]).parent));a=runpy.run_path(sys.argv[1]);p=Path(sys.argv[2]);fat,archive=a['vendor'](p,('fwtool.archive.fat','fwtool.archive'))
with tempfile.TemporaryDirectory() as directory:
 root=Path(directory);image=root/'volume.img'
 files={'/Backup.bin':{'data':b'original bytes'},'/mtab':{'data':b'/proc/mounts','mode':stat.S_IFLNK|0o777},
        '/pam.d/.gitkeep':{'data':b''},'/images/MYingHeiC-first.ltt':{'data':b'one'},'/images/MYingHeiC-second.ltt':{'data':b'two'}}
 result=a['fat_image'](image,4194304,files,fat,archive.UnixFile)
 assert result['/mtab']['kind']=='symlink' and result['/Backup.bin']['size']==14
 a['check']('fsck.fat',image,root/'fsck.log')
 image2=root/'empty.img';assert a['fat_image'](image2,4194304,{},fat,archive.UnixFile)=={}
 a['check']('fsck.fat',image2,root/'empty-fsck.log')
'''
        vendor=HERE/'vendor/fwtool-sdk'
        self.assertTrue(vendor.is_dir())
        subprocess.run([sys.executable,'-I','-B','-c',code,str(HERE/'factory_images.py'),str(vendor)],check=True,timeout=60)


if __name__=='__main__':unittest.main()
