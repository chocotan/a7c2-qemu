#!/usr/bin/env python3
"""Create and verify the FAT16 template used as the virtual SD backing file.

The firmware's own file media backend maps `/dev/mmca` onto the guest regular file
`/image_mmca`, so that file must be a valid FAT volume *before* the firmware
mounts it. Geometry matters: the original firmware writes
`A:/PRIVATE/DATABASE/DATABASE.BIN` at 0x939000 (9,670,656) bytes, so a 4 MiB card
fails with 0x80000082 -- the card has to be big enough to hold the database plus
the directory tree. 128 MiB FAT16 is what the sibling deliverable proved with.

A volume label is written: an unlabelled FAT volume failed their fsck criterion.
"""
import argparse
import hashlib
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
from fat_image import secure_open

HERE=Path(__file__).resolve().parent

# 128 MiB = 262144 x 512B sectors, 64 heads x 32 sectors/track (classic FAT16 geometry).
TOTAL_SECTORS=262144
HEADS=64
SECTORS_PER_TRACK=32
VOLUME_LABEL='A7C2CARD'
# A fixed serial keeps the template byte-for-byte reproducible: mformat otherwise
# derives it from the clock, and the manifest compares hashes.
VOLUME_SERIAL='0xA7C20001'
# Fixed seed timestamp (2000-01-01T00:00:00Z) keeps the image reproducible.
SEED_EPOCH=946684800
SEED_NAME='SEED.TXT'
SEED_TEXT=b'A7C2 virtual card seed\n'


def mtools_bin():
    root=HERE/'runtime/analysis'
    for candidate in sorted(root.glob('mtools-*/extracted/usr/bin')):
        if (candidate/'mformat').is_file() and (candidate/'mcopy').is_file():
            return candidate
    raise SystemExit('mtools (mformat/mcopy) not found under runtime/analysis/mtools-*')


def create(path):
    """Write a fresh 128 MiB FAT16 volume with one seed file."""
    tools=mtools_bin()
    path.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(dir=path.parent) as scratch:
        image=Path(scratch)/'card.img'
        with image.open('wb') as handle:
            handle.truncate(TOTAL_SECTORS*512)
        seed=Path(scratch)/SEED_NAME
        seed.write_bytes(SEED_TEXT)
        # mcopy writes the source mtime into the directory entry, so pin it; with
        # -m (preserve time) the template bytes are then reproducible.
        os.utime(seed,(SEED_EPOCH,SEED_EPOCH))
        # mformat also timestamps the volume-label entry; mcopy -m alone is insufficient.
        env={'PATH':str(tools)+':/usr/bin','MTOOLS_SKIP_CHECK':'1',
             'SOURCE_DATE_EPOCH':str(SEED_EPOCH),'TZ':'UTC'}
        subprocess.run([str(tools/'mformat'),'-i',str(image),'-T',str(TOTAL_SECTORS),
                        '-h',str(HEADS),'-s',str(SECTORS_PER_TRACK),'-v',VOLUME_LABEL,
                        '-N',VOLUME_SERIAL,'::'],
                       check=True,env=env,capture_output=True)
        subprocess.run([str(tools/'mcopy'),'-m','-i',str(image),str(seed),'::/'+SEED_NAME],
                       check=True,env=env,capture_output=True)
        shutil.copyfile(image,path)
    return path


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def copy_seed(source, destination):
    """Snapshot a regular FAT16 card; never modify or pass through a source device."""
    fd=secure_open(os.path.abspath(source))
    try:
        before=os.fstat(fd)
        import stat
        if not stat.S_ISREG(before.st_mode) or before.st_size!=TOTAL_SECTORS*512:
            raise ValueError('card seed must be a regular 128 MiB image')
        destination=Path(destination)
        with tempfile.TemporaryDirectory(dir=destination.parent) as temporary:
            image=Path(temporary)/'seed.fat'
            with os.fdopen(os.dup(fd),'rb') as original, image.open('xb') as output:
                shutil.copyfileobj(original,output,1024*1024)
            after=os.fstat(fd)
            key=lambda st:(st.st_dev,st.st_ino,st.st_size,st.st_mtime_ns,st.st_ctime_ns)
            if key(before)!=key(after) or image.stat().st_size!=before.st_size:
                raise ValueError('card seed changed while copying')
            with image.open('rb') as handle:boot=handle.read(512)
            if boot[54:62]!=b'FAT16   ' or boot[510:512]!=b'\x55\xaa':
                raise ValueError('card seed must contain a FAT16 superfloppy')
            fsck=shutil.which('fsck.fat') or shutil.which('fsck.vfat')
            if not fsck:
                raise RuntimeError('fsck.fat is required for card seed validation')
            subprocess.run([fsck,'-n',str(image)],check=True,capture_output=True)
            sha=digest(image)
            image.replace(destination)
        return {'bytes':before.st_size,'sha256':sha,'source_unchanged':True}
    finally:
        os.close(fd)


def inspect(path):
    """Independent structural check with fsck.fat when it is available."""
    tools=mtools_bin()
    env={'PATH':str(tools)+':'+str(Path('/usr/bin')),'MTOOLS_SKIP_CHECK':'1'}
    listing=subprocess.run([str(tools/'mdir'),'-i',str(path),'::/'],
                           check=True,env=env,capture_output=True,text=True).stdout
    info=subprocess.run([str(tools/'minfo'),'-i',str(path)],
                        check=True,env=env,capture_output=True,text=True).stdout
    fsck=None
    fsck_binary=shutil.which('fsck.fat') or shutil.which('fsck.vfat')
    if fsck_binary:
        fsck=subprocess.run([fsck_binary,'-n',str(path)],capture_output=True,text=True)
    return {'listing':listing,'info':info,
            'fsck_rc':None if fsck is None else fsck.returncode,
            'fsck_output':None if fsck is None else (fsck.stdout+fsck.stderr)[-400:],
            # mdir prints the 8.3 name in padded columns ("SEED     TXT"), so match
            # the columns instead of a "SEED.TXT" literal -- that literal never matches.
            'seed_present':bool(re.search(r'^SEED\s+TXT\b',listing,re.M))}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('path',type=Path,help='template image to create or verify')
    parser.add_argument('--verify-only',action='store_true')
    args=parser.parse_args()
    if not args.verify_only:
        create(args.path)
    if not args.path.is_file():
        raise SystemExit('missing template: '+str(args.path))
    report=inspect(args.path)
    print('FILE_MEDIA_TEMPLATE',args.path)
    print('  bytes',args.path.stat().st_size,'sha256',digest(args.path))
    print('  volume',VOLUME_LABEL,'seed_present',report['seed_present'])
    print('  fsck_rc',report['fsck_rc'])
    if report['fsck_rc'] not in (None,0):
        print(report['fsck_output'])
        return 1
    if not report['seed_present']:
        print(report['listing'])
        return 1
    return 0


if __name__=='__main__':raise SystemExit(main())
