import json
from pathlib import Path
import runpy
import subprocess
import sys
import tempfile
import unittest

HERE=Path(__file__).resolve().parent
API=runpy.run_path(str(HERE/'analyze-mmc-trace.py'))
DECLARATIONS=''.join(f'SONY_MMC_TRACE_CREATED phys={base:#x} bytes={size:#x} reset=0x0\n'
                     for base,size in API['WINDOWS'].items())


class TraceEvidence(unittest.TestCase):
    def analyse(self,text):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'console.log';path.write_text(text)
            return API['summarise'](*API['parse'](path))

    def test_no_device_or_no_access_is_failure_even_with_json_output(self):
        for text in ('',DECLARATIONS):
            with self.subTest(text=text),tempfile.TemporaryDirectory() as directory:
                (Path(directory)/'console.log').write_text(text)
                result=subprocess.run([sys.executable,'-B',str(HERE/'analyze-mmc-trace.py'),
                    directory,'--json'],capture_output=True,text=True)
                self.assertEqual(result.returncode,1)
                self.assertFalse(json.loads(result.stdout)['trace_capture_verified'])

    def test_global_order_and_distinct_devices_are_preserved(self):
        summary=self.analyse(DECLARATIONS+
            'SONY_MMC_TRACE_READ base=0xf1388000 n=1 off=0x30000 size=4\n'
            'SONY_MMC_TRACE_READ base=0xf1388000 n=2 off=0x8 size=4\n'
            'SONY_MMC_TRACE_WRITE base=0xf10d2000 n=1 off=0x8 size=4 value=0x1aa\n')
        self.assertTrue(summary['trace_capture_verified'])
        self.assertEqual([r['first_event'] for r in summary['by_first_access']],[0,1,2])
        self.assertEqual(summary['distinct_offsets'],3)
        self.assertFalse(summary['driver_identity_verified'])
        self.assertFalse(summary['media_io_verified'])

    def test_unattributed_legacy_records_are_rejected(self):
        with self.assertRaisesRegex(ValueError,'legacy'):
            self.analyse(DECLARATIONS+'SONY_MMC_TRACE_READ n=1 off=0x30000 size=4\n')

    def test_bad_geometry_missing_value_and_counter_gap_are_rejected(self):
        for record in (
            'READ base=0xf10d2000 n=1 off=0x2000 size=4',
            'READ base=0xf1388000 n=1 off=0x4 size=3',
            'WRITE base=0xf10d2000 n=1 off=0x8 size=4',
            'READ base=0xf1388000 n=2 off=0x30000 size=4',
            'READ base=0xf1111111 n=1 off=0x0 size=4',
        ):
            with self.subTest(record=record):
                self.assertFalse(self.analyse(DECLARATIONS+'SONY_MMC_TRACE_'+record+'\n')['trace_capture_verified'])


if __name__=='__main__':unittest.main()
