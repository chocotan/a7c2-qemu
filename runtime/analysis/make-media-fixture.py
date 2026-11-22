#!/usr/bin/env python3
"""Create isolated FAT fixtures; never format or open a physical device."""
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
camera_bytes=4*1024*1024*1024
if shutil.disk_usage(target.parent).free<camera_bytes+64*1024**3:
    raise RuntimeError('Insufficient host space for 4 GiB virtual camera SD image and reserve')
descriptor,name=tempfile.mkstemp(prefix='.media-camera-',dir=target.parent)
try:
    os.ftruncate(descriptor,camera_bytes)
    os.close(descriptor);descriptor=-1
    subprocess.run(['mkfs.fat','-a','-F','32','-s','64','-S','512','-i','7C220201',name],check=True,capture_output=True)
    # Set FAT32 FSInfo FSI_Free_Count / FSI_Nxt_Free to the Microsoft FAT32 spec
    # "unknown / compute from FAT" sentinel (0xFFFFFFFF). Sony's PrFILE2 Fsys_FlushVolume
    # flushes FAT/dir/data while keeping the volume mounted and does not rewrite FSInfo until
    # unmount, so leaving mkfs.fat's initial free count causes read-only fsck.fat -n to fail.
    with open(name,'r+b') as stream:
        boot=stream.read(512)
        fsinfo_sec=int.from_bytes(boot[48:50],'little')
        backup_sec=int.from_bytes(boot[50:52],'little')
        for sec in (fsinfo_sec, backup_sec + fsinfo_sec):
            if sec:
                stream.seek(sec*512)
                fsi=stream.read(512)
                if fsi[:4]==b'RRaA' and fsi[484:488]==b'rrAa' and fsi[508:512]==b'\x00\x00\x55\xaa':
                    stream.seek(sec*512+488)
                    stream.write(b'\xff\xff\xff\xff\xff\xff\xff\xff')
    subprocess.run(['fsck.fat','-n',name],check=True,capture_output=True)
    with open(name,'rb') as stream:
        boot=stream.read(512)
    sectors=int.from_bytes(boot[19:21],'little') or int.from_bytes(boot[32:36],'little')
    assert (sectors*512==camera_bytes and boot[13]==64 and
            boot[82:90]==b'FAT32   ' and boot[510:512]==b'\x55\xaa')
    Path(name).replace(camera)
finally:
    if descriptor>=0:os.close(descriptor)
    Path(name).unlink(missing_ok=True)
print('CAMERA_SD_FIXTURE_PASS',camera,camera_bytes)
