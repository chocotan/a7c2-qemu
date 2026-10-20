import json
import os
from pathlib import Path
import runpy
import shutil
import tempfile
import unittest

COMPARE=runpy.run_path(str(Path(__file__).with_name('compare-startup-caution.py')))['compare']


@unittest.skipUnless(os.environ.get('A7C2_STARTUP_BASELINE') and os.environ.get('A7C2_STARTUP_NO_MENU'),
                     'Set A7C2_STARTUP_BASELINE and A7C2_STARTUP_NO_MENU')
class StartupComparison(unittest.TestCase):
    def test_real_same_image_control(self):
        proof=COMPARE(Path(os.environ['A7C2_STARTUP_BASELINE']),Path(os.environ['A7C2_STARTUP_NO_MENU']))
        self.assertTrue(proof['identical_guest_image_and_recorded_profile'])
        self.assertTrue(proof['automatic_menu_removed'])
        self.assertFalse(proof['sd_or_mount_failure_proven'])

    def test_image_profile_or_key_evidence_change_rejected(self):
        baseline=Path(os.environ['A7C2_STARTUP_BASELINE']);src=Path(os.environ['A7C2_STARTUP_NO_MENU'])
        for kind in ('image','observer','boot','key'):
            with self.subTest(kind=kind),tempfile.TemporaryDirectory() as temporary:
                dst=Path(temporary)
                for name in ('runtime-manifest.json','summary.json','console.log','headless-osd-pixels-rgba4444-software.png'):
                    shutil.copyfile(src/name,dst/name)
                summary=json.loads((dst/'summary.json').read_text());summary['run']=str(dst)
                (dst/'summary.json').write_text(json.dumps(summary))
                m=json.loads((dst/'runtime-manifest.json').read_text())
                if kind=='image':m['files'][summary['input_image']]='0'*64
                elif kind=='observer':m['compiled_observer']['observer_sha256']='0'*64
                elif kind=='boot':m['boot_type']=2
                else:
                    with (dst/'console.log').open('ab') as f:f.write(b'\nOBS KEY_INJECT bogus unexpected key evidence\n')
                (dst/'runtime-manifest.json').write_text(json.dumps(m))
                with self.assertRaises(ValueError):COMPARE(baseline,dst)


if __name__=='__main__':unittest.main()
