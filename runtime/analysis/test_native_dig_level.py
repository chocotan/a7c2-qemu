import json
import os
from pathlib import Path
import runpy
import shutil
import subprocess
import tempfile
import unittest

HERE=Path(__file__).resolve().parent
VERIFY=runpy.run_path(str(HERE/'verify-native-dig-level.py'))['verify']


@unittest.skipUnless(os.environ.get('A7C2_NATIVE_DIG_LEVEL_RUN'),'Set A7C2_NATIVE_DIG_LEVEL_RUN')
class DigitalLevelEvidence(unittest.TestCase):
    def test_virtual_subscription_without_sensor_claim(self):
        proof=VERIFY(Path(os.environ['A7C2_NATIVE_DIG_LEVEL_RUN']))
        self.assertTrue(proof['virtual_notification_subscription_verified'])
        self.assertFalse(proof['sensor_ready_verified'])
        self.assertFalse(proof['original_backup_mode_verified'])
        self.assertFalse(proof['sample_valid'])
        self.assertEqual(proof['angle_events_emitted'],0)

    def test_changed_state_scope_and_missing_free_remove_old_success(self):
        src=Path(os.environ['A7C2_NATIVE_DIG_LEVEL_RUN'])
        for kind in ('enabled','countdown','sample','free','profile'):
            with self.subTest(kind=kind),tempfile.TemporaryDirectory() as temporary:
                dst=Path(temporary)
                for name in ('console.log','summary.json','runtime-manifest.json'):
                    shutil.copyfile(src/name,dst/name)
                summary=json.loads((dst/'summary.json').read_text());summary['run']=str(dst)
                (dst/'summary.json').write_text(json.dumps(summary))
                cli=['python3',str(HERE/'verify-native-dig-level.py'),str(dst)]
                initial=subprocess.run(cli,capture_output=True,text=True,timeout=20)
                self.assertEqual(initial.returncode,0,initial.stderr)
                text=(dst/'console.log').read_text()
                if kind in ('enabled','countdown','sample'):
                    field,old,new={'enabled':('notification_enabled','1','0'),
                                   'countdown':('countdown','30','0'),
                                   'sample':('sample_valid','0','1')}[kind]
                    rows=text.splitlines(keepends=True)
                    changed=False
                    for i,line in enumerate(rows):
                        if line.startswith('OBS FULL_DIG_LEVEL_CONTROL_CONSUMED '):
                            self.assertIn(field+'='+old,line)
                            rows[i]=line.replace(field+'='+old,field+'='+new);changed=True
                    self.assertTrue(changed);text=''.join(rows)
                elif kind=='free':
                    self.assertIn('OBS FULL_DIG_LEVEL_NATIVE_REPLY_FREE ',text)
                    text='\n'.join(l for l in text.splitlines() if not l.startswith('OBS FULL_DIG_LEVEL_NATIVE_REPLY_FREE '))
                else:
                    m=json.loads((dst/'runtime-manifest.json').read_text());m['digital_level_profile']=''
                    (dst/'runtime-manifest.json').write_text(json.dumps(m))
                (dst/'console.log').write_text(text)
                result=subprocess.run(cli,capture_output=True,text=True,timeout=20)
                self.assertEqual(result.returncode,1,result.stderr)
                proof=json.loads((dst/'digital-level-native-proof.json').read_text())
                self.assertFalse(proof['virtual_notification_subscription_verified'])
                self.assertFalse(proof['sensor_ready_verified'])


if __name__=='__main__':unittest.main()
