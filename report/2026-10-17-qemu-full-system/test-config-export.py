#!/usr/bin/env python3
"""Boundary tests for the allowlisted configuration export.

The card export deliberately refuses any path but `/image_mmca`. The config export
is the only other reader allowed to reuse that declared window, so its path list and
its digest checks are tested here rather than assumed.
"""
import hashlib
import importlib.util
import json
import re
from pathlib import Path
import tempfile
import unittest

HERE=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('run_full_system',HERE/'run-full-system.py')
RUNNER=importlib.util.module_from_spec(spec);spec.loader.exec_module(RUNNER)

PAYLOAD=b'BK4'*4000
GEO={'physical':0x41eb00000,'capacity':0x400000}


def size_receipt(command, size):
    nonce = re.search(r'CONFIG_EXPORT_SIZE_([0-9a-f]{24}):%s', command).group(1)
    return f'CONFIG_EXPORT_SIZE_{nonce}:{size}:END_{nonce}\n'.encode()


def receipt(payload,index=0):
    return (f'CARD_EXPORT_SOURCE dev=1 ino=2 size={len(payload)} mtime=0.000000001 ctime=0.000000001\n'
            f'CARD_EXPORT_CHUNK index={index} offset={index*RUNNER.CARD_EXPORT_CHUNK} '
            f'bytes={len(payload)} fnv64={RUNNER.card_chunk_hash(payload):016x} '
            f'window={GEO["physical"]:#x}\n').encode()


class FakeQmp:
    def __init__(self,out,payload):self.out=out;self.payload=payload;self.stopped=False
    def __call__(self,command,arguments=None,**keyword):
        arguments=arguments or keyword
        if command=='query-status':return {'running':True}
        if command=='stop':self.stopped=True;return {}
        if command=='cont':self.stopped=False;return {}
        if command=='pmemsave':
            (self.out/Path(arguments['filename']).name).write_bytes(self.payload[:arguments['size']])
            return {}
        raise AssertionError(command)


class ConfigExport(unittest.TestCase):
    def test_allowlist_is_closed(self):
        self.assertEqual(RUNNER.CONFIG_EXPORT_TARGETS,('/setting/Backup.bin','/setting/Backup.bak'))
        for path in ('/image_mmca','/setting/Backup.bin.bak','/etc/Backup.bin',''):
            with self.assertRaises(ValueError):
                RUNNER.guest_file_size(lambda *a,**k:b'1\n',path)
            with self.assertRaises(ValueError):
                RUNNER.export_config_file(lambda *a,**k:b'',FakeQmp(Path('/tmp'),b''),
                                          {'card_export':GEO},Path('/tmp'),path,'Backup.bin')

    def test_size_comes_from_the_guest(self):
        self.assertEqual(RUNNER.guest_file_size(lambda command,**k:size_receipt(command,2390264),'/setting/Backup.bin'),2390264)
        with self.assertRaises(RuntimeError):
            RUNNER.guest_file_size(lambda *a,**k:b'CONFIG_EXPORT_MISSING\n','/setting/Backup.bin')
        with self.assertRaises(RuntimeError):
            RUNNER.guest_file_size(lambda command,**k:size_receipt(command,0),'/setting/Backup.bin')
        with self.assertRaises(RuntimeError):
            RUNNER.guest_file_size(lambda *a,**k:b'10\n20\n','/setting/Backup.bin')

    def test_echo_and_interleaved_bare_number_never_supply_the_size(self):
        def run(command, **kwargs):
            return (command.encode() + b'\r\n2390264[\r\n42.022000] kernel warning\n'
                    + size_receipt(command,2390264))
        self.assertEqual(RUNNER.guest_file_size(run,'/setting/Backup.bak'),2390264)
        with self.assertRaises(RuntimeError):
            RUNNER.guest_file_size(lambda *a,**k:b'2390264[\n42.022000] warning\n','/setting/Backup.bak')

    def test_wrong_nonce_and_duplicate_size_frames_are_rejected(self):
        def duplicate(command, **kwargs):
            return size_receipt(command,2390264) * 2
        with self.assertRaises(RuntimeError):
            RUNNER.guest_file_size(duplicate,'/setting/Backup.bak')
        with self.assertRaises(RuntimeError):
            RUNNER.guest_file_size(lambda *a,**k:b'CONFIG_EXPORT_SIZE_wrong:2390264:END_wrong\n',
                                   '/setting/Backup.bak')

    def test_wc_padding_is_allowed_but_kernel_text_inside_the_frame_is_not(self):
        self.assertEqual(RUNNER.guest_file_size(lambda command,**k:size_receipt(command,'  2390264\t'),
                                               '/setting/Backup.bak'),2390264)
        with self.assertRaises(RuntimeError):
            RUNNER.guest_file_size(lambda command,**k:size_receipt(command,'2390264[kernel warning]'),
                                   '/setting/Backup.bak')

    def test_export_roundtrip_records_digest(self):
        with tempfile.TemporaryDirectory() as directory:
            out=Path(directory)
            def run(command,timeout=None,cleanup=False):
                if 'busybox wc -c' in command:
                    return size_receipt(command,len(PAYLOAD))
                return receipt(PAYLOAD)
            record=RUNNER.export_config_file(run,FakeQmp(out,PAYLOAD),{'card_export':GEO},out,
                                             '/setting/Backup.bin','Backup.bin')
            self.assertEqual((out/'Backup.bin').read_bytes(),PAYLOAD)
            self.assertEqual(record['bytes'],len(PAYLOAD))
            self.assertEqual(record['sha256'],hashlib.sha256(PAYLOAD).hexdigest())
            self.assertEqual(record['fnv64'],f'{RUNNER.card_chunk_hash(PAYLOAD):016x}')
            self.assertFalse((out/'Backup.bin.chunk').exists())

    def test_digest_mismatch_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            out=Path(directory)
            def run(command,timeout=None,cleanup=False):
                if 'busybox wc -c' in command:
                    return size_receipt(command,len(PAYLOAD))
                return receipt(PAYLOAD+b'X')
            with self.assertRaises(RuntimeError):
                RUNNER.export_config_file(run,FakeQmp(out,PAYLOAD),{'card_export':GEO},out,
                                          '/setting/Backup.bin','Backup.bin')
            self.assertFalse((out/'Backup.bin').exists())

    def test_existing_export_is_never_overwritten(self):
        with tempfile.TemporaryDirectory() as directory:
            out=Path(directory)
            (out/'Backup.bin').write_bytes(b'previous')
            def run(command,timeout=None,cleanup=False):
                return size_receipt(command,len(PAYLOAD)) if 'busybox wc -c' in command else receipt(PAYLOAD)
            with self.assertRaises(RuntimeError):
                RUNNER.export_config_file(run,FakeQmp(out,PAYLOAD),{'card_export':GEO},out,
                                          '/setting/Backup.bin','Backup.bin')
            self.assertEqual((out/'Backup.bin').read_bytes(),b'previous')

    def test_pair_exports_both_files(self):
        with tempfile.TemporaryDirectory() as directory:
            out=Path(directory)
            def run(command,timeout=None,cleanup=False):
                return size_receipt(command,len(PAYLOAD)) if 'busybox wc -c' in command else receipt(PAYLOAD)
            result={}
            RUNNER.export_config_pair(run,FakeQmp(out,PAYLOAD),{'card_export':GEO},out,result)
            self.assertTrue(result['config_export']['verified'])
            self.assertEqual([item['name'] for item in result['config_export']['files']],
                             ['Backup.bin','Backup.bak'])
            self.assertTrue((out/'Backup.bak').is_file())

    def test_card_export_still_refuses_other_paths(self):
        with tempfile.TemporaryDirectory() as directory:
            out=Path(directory)
            with self.assertRaises(ValueError):
                RUNNER.export_card_snapshot(lambda *a,**k:b'',FakeQmp(out,b''),
                                            {'card_export':GEO},out,{},
                                            image='/setting/Backup.bin',size=0x1000)


if __name__=='__main__':unittest.main()
