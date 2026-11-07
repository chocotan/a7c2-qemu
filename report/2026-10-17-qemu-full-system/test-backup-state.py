import hashlib
from pathlib import Path
import runpy
import struct
import unittest
from unittest.mock import patch

HERE=Path(__file__).resolve().parent
API=runpy.run_path(str(HERE/'backup-state.py'))


def fixture():
    data=bytearray(280)
    struct.pack_into('<9I',data,0,0x04000000,0xaaaaaaaa,0,0x00344b42,1,1,268,12,0)
    data[64:68]=b'test';data[192:199]=b'ALLLANG'
    struct.pack_into('<HI',data,256,1,0)
    struct.pack_into('<HI',data,262,0,(4<<24)|268)
    data[268:272]=b'abcd'
    return repair(data)


def repair(data):
    struct.pack_into('<I',data,32,(sum(data[:32])+sum(data[36:]))&0xffffffff)
    return bytes(data)


class BackupState(unittest.TestCase):
    def test_complete_property_and_generation(self):
        result=API['parse_record'](fixture(),0,280)
        self.assertEqual(result['properties'][0]['data'],b'abcd')
        self.assertEqual(result['region'],'ALLLANG')

    def test_corrupt_checksum_and_truncation(self):
        bad=bytearray(fixture());bad[268]^=1
        for data in (bytes(bad),fixture()[:240]):
            with self.subTest(size=len(data)),self.assertRaises(ValueError):API['parse_record'](data,0,len(data))

    def test_invalid_tables_and_properties(self):
        changes=((16,2),(24,260),(260,0xffff),(264,0x04000001),(264,0x1000010c))
        for offset,value in changes:
            bad=bytearray(fixture());struct.pack_into('<I',bad,offset,value);bad=repair(bad)
            with self.subTest(offset=offset,value=value),self.assertRaises(ValueError):API['parse_record'](bad,0,len(bad))

    def test_reset_and_extended_lengths_are_bounded(self):
        bad=bytearray(fixture());struct.pack_into('<HI',bad,262,4,(8<<24)|268)
        with self.assertRaises(ValueError):API['parse_record'](repair(bad),0,len(bad))
        bad=bytearray(fixture());struct.pack_into('<HI',bad,262,0,268);struct.pack_into('<HH',bad,268,8,4)
        with self.assertRaises(ValueError):API['parse_record'](repair(bad),0,len(bad))

    def test_missing_second_record_rejected(self):
        with self.assertRaises(ValueError):API['parse_file'](fixture())

    def test_only_official_reference_accepted(self):
        with self.assertRaises(ValueError):API['validate'](fixture(),fixture())

    def test_validation_matches_both_record_schemas(self):
        file=fixture()*2;scope=API['validate'].__globals__
        with patch.dict(scope,{'FILE_BYTES':len(file),'RECORD_OFFSETS':(0,280),
                              'OFFICIAL_PP_SHA256':hashlib.sha256(file).hexdigest()}):
            self.assertEqual(len(API['validate'](file,file)['records']),2)
            altered=bytearray(file);altered[280+192]=ord('X')
            altered[280:]=repair(altered[280:])
            with self.assertRaises(ValueError):API['validate'](bytes(altered),file)


if __name__=='__main__':unittest.main()
