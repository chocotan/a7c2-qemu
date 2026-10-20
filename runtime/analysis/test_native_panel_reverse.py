import json
import os
from pathlib import Path
import runpy
import shutil
import subprocess
import tempfile
import unittest

HERE=Path(__file__).resolve().parent
VERIFY=runpy.run_path(str(HERE/'verify-native-panel-reverse.py'))['verify']


@unittest.skipUnless(os.environ.get('A7C2_NATIVE_PANEL_REVERSE_RUN'),'Set A7C2_NATIVE_PANEL_REVERSE_RUN')
class PanelReverseEvidence(unittest.TestCase):
    def test_observed_virtual_configuration_only(self):
        proof=VERIFY(Path(os.environ['A7C2_NATIVE_PANEL_REVERSE_RUN']))
        self.assertTrue(proof['virtual_panel_reverse_config_verified'])
        self.assertEqual(proof['virtual_control'],3)
        self.assertFalse(proof['pixels_flipped'])
        self.assertFalse(proof['hardware_driver_executed'])

    def test_cache_control_scope_status_or_free_rejected(self):
        src=Path(os.environ['A7C2_NATIVE_PANEL_REVERSE_RUN'])
        for kind in ('cache','control','scope','status','free'):
            with self.subTest(kind=kind),tempfile.TemporaryDirectory() as temporary:
                dst=Path(temporary)
                for name in ('console.log','runtime-manifest.json','summary.json'):
                    shutil.copyfile(src/name,dst/name)
                summary=json.loads((dst/'summary.json').read_text());summary['run']=str(dst)
                (dst/'summary.json').write_text(json.dumps(summary))
                text=(dst/'console.log').read_text()
                if kind in ('cache','control','scope'):
                    old,new={'cache':('properties=0,1,1,0','properties=0,0,0,0'),
                             'control':('control_readback=3','control_readback=0'),
                             'scope':('pixels_flipped=0','pixels_flipped=1')}[kind]
                    self.assertIn(old,text);text=text.replace(old,new)
                elif kind=='status':
                    self.assertIn('0d2019110c00018000000000',text)
                    text=text.replace('0d2019110c00018000000000','0d2019110c00018000005900')
                else:
                    self.assertIn('cmd=0x119 ',text)
                    text='\n'.join(l for l in text.splitlines() if not
                        (l.startswith('OBS FULL_VDF_NATIVE_REPLY_FREE ') and 'cmd=0x119 ' in l))
                (dst/'panel-reverse-native-proof.json').write_text(json.dumps({'virtual_panel_reverse_config_verified':True}))
                (dst/'console.log').write_text(text)
                result=subprocess.run(['python3',str(HERE/'verify-native-panel-reverse.py'),str(dst)],
                                      capture_output=True,text=True,timeout=20)
                self.assertEqual(result.returncode,1,result.stdout+result.stderr)
                self.assertFalse(json.loads((dst/'panel-reverse-native-proof.json').read_text())['virtual_panel_reverse_config_verified'])


if __name__=='__main__':unittest.main()
