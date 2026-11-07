#!/usr/bin/env python3
"""Boundary tests for the card-export window (guest helper + reservation).

The window is how the card leaves the VM: the guest copies one chunk into reserved
memory and the host reads it with QMP pmemsave. Both sides must agree on the
geometry, or the export silently reads the wrong bytes.
"""
import importlib.util
from pathlib import Path
import re
import runpy
import tempfile
import unittest
from unittest.mock import patch

HERE=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('card_export_region',HERE/'card-export-region.py')
REGION=importlib.util.module_from_spec(spec);spec.loader.exec_module(REGION)

SOURCE=(HERE/'card-export.c').read_text()
API=runpy.run_path(str(HERE/'run-full-system.py'))


def source_constant(name):
    match=re.search(rf'#define {name}\s+(0x[0-9a-fA-F]+|\d+)',SOURCE)
    return int(match.group(1),0) if match else None


class Geometry(unittest.TestCase):
    def test_the_guest_helper_and_the_reservation_agree(self):
        self.assertEqual(source_constant('CARD_WINDOW_PHYSICAL'),REGION.PHYSICAL)
        self.assertEqual(source_constant('CARD_WINDOW_BYTES'),REGION.CAPACITY)

    def test_the_reservation_token_matches_the_geometry(self):
        self.assertEqual(REGION.RESERVATION,f'memrsv={REGION.CAPACITY:#010x}@{REGION.PHYSICAL:#011x}:uc')

    def test_the_window_is_inside_declared_guest_ram(self):
        self.assertGreaterEqual(REGION.PHYSICAL,0x400000000)
        self.assertLessEqual(REGION.PHYSICAL+REGION.CAPACITY,0x600000000)

    def test_the_window_does_not_overlap_the_known_adapters(self):
        for start,size in ((0x400000000,0x1000000),(0x41d000000,0x20000),
                           (0x41e000000,0xa00000),(0x440000000,0x80000000)):
            with self.subTest(start=hex(start)):
                self.assertFalse(start < REGION.PHYSICAL+REGION.CAPACITY
                                 and REGION.PHYSICAL < start+size)


class Snapshot(unittest.TestCase):
    def export(self, *, corrupt=False, identity_change=False, resume_failure=False):
        export=API['export_card_image']
        with tempfile.TemporaryDirectory() as directory:
            out=Path(directory)
            source=b'abcdefghij'
            staged=b''
            calls=[]
            result={}

            def run(command, timeout):
                nonlocal staged
                index, count=map(int, command.split()[-2:])
                staged=source[index*4:index*4+count]
                value=API['card_chunk_hash'](staged)
                identity='other' if identity_change and index else 'stable'
                receipt=(f'CARD_EXPORT_SOURCE {identity}\n'
                         f'CARD_EXPORT_CHUNK index={index} offset={index*4} bytes={count} '
                         f'fnv64={value:016x} window={REGION.PHYSICAL:#x}\n').encode()
                return receipt+receipt  # Serial may repeat receipts; never repeat commands.

            def qmp(operation, arguments=None):
                calls.append(operation)
                if operation=='query-status':return {'running':True}
                if operation=='pmemsave':
                    data=bytes([staged[0]^1])+staged[1:] if corrupt else staged
                    (out/Path(arguments['filename']).name).write_bytes(data)
                if operation=='cont' and resume_failure:raise RuntimeError('resume failed')

            error=None
            with patch.dict(export.__globals__, {'CARD_EXPORT_CHUNK':4}):
                try:
                    export(run,qmp,{'card_export':{'physical':REGION.PHYSICAL,'capacity':4}},
                           out,result,size=len(source))
                except RuntimeError as failure:error=str(failure)
            actual=(out/'card-image.bin').read_bytes() if (out/'card-image.bin').exists() else None
            return result,actual,error,calls

    def test_verified_chunks_include_short_final_chunk(self):
        result,actual,error,_=self.export()
        self.assertIsNone(error)
        self.assertEqual(actual,b'abcdefghij')
        self.assertEqual([r['bytes'] for r in result['card_chunk_receipts']],[4,4,2])
        self.assertTrue(result['card_snapshot_integrity_verified'])
        self.assertFalse(result['card_persistence_verified'])

    def test_corrupt_qmp_readback_is_not_published(self):
        result,actual,error,calls=self.export(corrupt=True)
        self.assertIn('digest mismatch',error)
        self.assertIsNone(actual)
        self.assertFalse(result['card_image_exported'])
        self.assertIn('cont',calls)

    def test_source_changed_between_chunks_is_rejected(self):
        result,actual,error,_=self.export(identity_change=True)
        self.assertIn('source changed',error)
        self.assertIsNone(actual)
        self.assertFalse(result['card_snapshot_integrity_verified'])

    def test_failed_guest_resume_cannot_report_success(self):
        result,actual,error,_=self.export(resume_failure=True)
        self.assertIn('resume failed',error)
        self.assertIsNone(actual)
        self.assertFalse(result['card_image_exported'])

    def test_wrong_geometry_and_conflicting_receipts_are_rejected(self):
        receipt=b'CARD_EXPORT_CHUNK index=0 offset=0 bytes=4 fnv64=0000000000000000 window=0x41eb00000\n'
        for data in (receipt.replace(b'offset=0',b'offset=4'),
                     receipt+receipt.replace(b'index=0',b'index=1')):
            with self.subTest(data=data),self.assertRaises(RuntimeError):
                API['card_chunk_receipt'](data,0,4,REGION.PHYSICAL)


if __name__=='__main__':unittest.main()
