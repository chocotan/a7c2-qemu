#!/usr/bin/env python3
"""Create a small isolated FAT fixture; never format or open a physical device."""
import io
import os
from pathlib import Path
import stat
import sys
import time
import shutil
import subprocess
import tempfile

BASE = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE / 'vendor/fwtool'))
from fwtool.archive import UnixFile
from fwtool.archive.fat import readFat, writeFat

os.environ['TZ'] = 'CST-8'
time.tzset()
marker = b'A7C2 virtual file-media fixture\n'
image = io.BytesIO()
writeFat([UnixFile('/SEED.TXT', len(marker), 315532800, stat.S_IFREG | 0o644,
                   0, 0, io.BytesIO(marker))], 4 * 1024 * 1024, image)
image.seek(43)
image.write(b'NO NAME    ')  # Standard unlabelled FAT volume; fwtool leaves an invalid blank label.
image.seek(0)
assert {entry.path: entry.contents.read() for entry in readFat(image)} == {'/SEED.TXT': marker}
target = BASE / 'menu-root/simulation/media-template.fat'
target.parent.mkdir(exist_ok=True)
temporary = target.with_suffix('.new')
with temporary.open('xb') as output:
    output.write(image.getvalue())
temporary.replace(target)
print('MEDIA_FIXTURE_PASS', target, len(image.getvalue()))

# The original application allocates a 0x939000-byte image database; 4 MiB is only a unit-test card.
camera=target.with_name('media-camera.fat')
camera_bytes=128*1024*1024
if shutil.disk_usage(target.parent).free<camera_bytes*3+1024*1024*1024:
    raise RuntimeError('Insufficient host space for camera SD image and initramfs')
descriptor,name=tempfile.mkstemp(prefix='.media-camera-',dir=target.parent)
try:
    os.ftruncate(descriptor,camera_bytes)
    os.close(descriptor);descriptor=-1
    subprocess.run(['mkfs.fat','-F','16','-s','4','-S','512','-i','7C220201',name],check=True,capture_output=True)
    subprocess.run(['fsck.fat','-n',name],check=True,capture_output=True)
    with open(name,'rb') as stream:
        boot=stream.read(512)
    sectors=int.from_bytes(boot[19:21],'little') or int.from_bytes(boot[32:36],'little')
    assert sectors*512==camera_bytes and boot[510:512]==b'\x55\xaa'
    Path(name).replace(camera)
finally:
    if descriptor>=0:os.close(descriptor)
    Path(name).unlink(missing_ok=True)
print('CAMERA_SD_FIXTURE_PASS',camera,camera_bytes)
