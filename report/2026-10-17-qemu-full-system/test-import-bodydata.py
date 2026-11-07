#!/usr/bin/env python3
"""Untrusted container/archive boundary tests; real package is tested separately."""
import binascii
import hashlib
import io
from pathlib import Path
import runpy
import struct
import tarfile
import tempfile
import unittest

API=runpy.run_path(str(Path(__file__).with_name('import-bodydata.py')))


def ufu():
    result=bytearray(API['MAGIC'])
    for name,data in ((b'DATV',struct.pack('>HH',0x100,0)),(b'PROV',struct.pack('>HH',0x100,0)),
                      (b'UDID',struct.pack('>IHHB3x',1,0xe8a,0x54c,1)),(b'FDAT',bytes(1296))):
        result+=struct.pack('>I4s',len(data),name)+data
    crc=binascii.crc32(result)&0xffffffff
    result+=struct.pack('>I4sI',4,b'DEND',crc)
    return result


def archive(entries):
    data=io.BytesIO()
    with tarfile.open(fileobj=data,mode='w') as out:
        for name,kind,contents in entries:
            entry=tarfile.TarInfo(name);entry.uid=entry.gid=0;entry.mtime=123
            entry.mode=0o777 if kind=='symlink' else 0o640
            if kind=='symlink':entry.type=tarfile.SYMTYPE;entry.linkname=contents
            else:entry.size=len(contents)
            out.addfile(entry,None if kind=='symlink' else io.BytesIO(contents))
    data.seek(0);return data


class PublicContainerBoundary(unittest.TestCase):
    def test_chunk_lengths_and_unknown_trailing_data(self):
        raw=ufu();size,parts=API['chunks'](io.BytesIO(raw))
        self.assertEqual(size,len(raw));self.assertEqual(parts[b'FDAT'][1],1296)
        with self.assertRaises(ValueError):API['chunks'](io.BytesIO(raw+b'trailing'))
        damaged=raw.copy();offset=parts[b'FDAT'][0]-8
        damaged[offset:offset+4]=(0xffffffff).to_bytes(4,'big')
        with self.assertRaisesRegex(ValueError,'out-of-bounds'):API['chunks'](io.BytesIO(damaged))

    def test_duplicate_chunks_fail_before_vendor_parser(self):
        raw=ufu();raw[24:28]=b'DATV'
        with self.assertRaisesRegex(ValueError,'Duplicate'):API['chunks'](io.BytesIO(raw))

    def test_crc_and_invalid_rsa_are_separate_failures(self):
        class PublicKey:
            n=(1<<2048)-159;e=65537
            def size_in_bytes(self):return 256
        raw=ufu();_,parts=API['chunks'](io.BytesIO(raw))
        with self.assertRaisesRegex(ValueError,'signature invalid'):API['inspect'](io.BytesIO(raw),PublicKey())
        raw[parts[b'FDAT'][0]+20]^=1
        with self.assertRaisesRegex(ValueError,'CRC mismatch'):API['inspect'](io.BytesIO(raw),PublicKey())


class ArchiveBoundary(unittest.TestCase):
    def test_traversal_and_duplicate_members(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)/'payload';root.mkdir()
            with self.assertRaisesRegex(ValueError,'Unsafe'):API['extract_tar'](archive([('../escape','file',b'x')]),root)
            self.assertFalse((Path(d)/'escape').exists())
            with self.assertRaisesRegex(ValueError,'Duplicate'):
                API['extract_tar'](archive([('same','file',b'a'),('same','file',b'b')]),root)

    def test_guest_links_are_metadata_only(self):
        rows=[{'path':'data','type':'file','size':3,'mode':0o640,'uid':0,'gid':0,'mtime':123,
               'sha256':hashlib.sha256(b'abc').hexdigest()},
              {'path':'mtab','type':'symlink','size':0,'mode':0o777,'uid':0,'gid':0,'mtime':123,'target':'/proc/mounts'}]
        expected=hashlib.sha256(API['canonical_json'](rows)).hexdigest()
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)
            actual=API['extract_tar'](archive([('data','file',b'abc'),('mtab','symlink','/proc/mounts')]),root,expected)
            self.assertEqual(actual,rows)
            self.assertEqual((root/'data').read_bytes(),b'abc')
            self.assertFalse((root/'mtab').exists() or (root/'mtab').is_symlink())

    def test_link_parent_never_becomes_a_host_directory(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)
            with self.assertRaisesRegex(ValueError,'descends through a guest symlink'):
                API['extract_tar'](archive([('link','symlink','/tmp'),('link/escape','file',b'x')]),root)
            self.assertFalse((root/'link').exists())

    def test_discovery_does_not_follow_file_links(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);source=root/'real';source.write_bytes(ufu())
            (root/'alias').symlink_to(source)
            self.assertEqual(API['discover'](root),source)
            (root/'another').write_bytes(ufu())
            with self.assertRaisesRegex(ValueError,'found 2'):API['discover'](root)


if __name__=='__main__':unittest.main()
