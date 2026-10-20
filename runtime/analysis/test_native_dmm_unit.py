import json
import os
from pathlib import Path
import runpy
import shutil
import subprocess
import tempfile
import unittest

HERE=Path(__file__).resolve().parent
VERIFY=runpy.run_path(str(HERE/'verify-native-dmm-unit.py'))['verify']


@unittest.skipUnless(os.environ.get('A7C2_NATIVE_DMM_UNIT_RUN'),'Set A7C2_NATIVE_DMM_UNIT_RUN')
class DmmUnitEvidence(unittest.TestCase):
    def test_original_table_reply_and_ap_property(self):
        proof=VERIFY(Path(os.environ['A7C2_NATIVE_DMM_UNIT_RUN']))
        self.assertTrue(proof['config_backed_unit_size_verified'])
        self.assertTrue(proof['original_ap_property_readback_verified'])
        self.assertEqual(proof['size'],150*1024*1024)
        self.assertEqual(proof['allocated_bytes'],0)
        self.assertFalse(proof['camera_startup_verified'])

    def test_bad_property_reply_config_and_free_replace_old_success(self):
        src=Path(os.environ['A7C2_NATIVE_DMM_UNIT_RUN'])
        for kind in ('property','reply','config','free'):
            with self.subTest(kind=kind),tempfile.TemporaryDirectory() as temporary:
                dst=Path(temporary)
                for name in ('console.log','summary.json','runtime-manifest.json'):
                    shutil.copyfile(src/name,dst/name)
                summary=json.loads((dst/'summary.json').read_text());summary['run']=str(dst)
                (dst/'summary.json').write_text(json.dumps(summary))
                cli=['python3',str(HERE/'verify-native-dmm-unit.py'),str(dst)]
                initial=subprocess.run(cli,capture_output=True,text=True,timeout=20)
                self.assertEqual(initial.returncode,0,initial.stdout+initial.stderr)
                text=(dst/'console.log').read_text()
                if kind=='property':
                    import re
                    pattern=r'(^[0-9a-f]{16}:) 00 00 60 09\r?$'
                    text,n=re.subn(pattern,r'\1 00 00 00 00',text,flags=re.M)
                    self.assertEqual(n,1)
                elif kind=='reply':
                    import re
                    lines=text.splitlines(keepends=True);changed=False
                    for i,l in enumerate(lines):
                        if l.startswith('OBS FULL_DMM_UNIT_REPLY_QUEUED '):
                            raw=re.search(r'raw=([0-9a-f]+)',l)[1]
                            wire=bytearray.fromhex(raw);wire[18]^=1
                            lines[i]=l.replace(raw,wire.hex());changed=True
                    self.assertTrue(changed);text=''.join(lines)
                elif kind=='config':
                    m=json.loads((dst/'runtime-manifest.json').read_text())
                    m['selected_initramfs_verified_files']['cp/DmmCfg.bin']='0'*64
                    (dst/'runtime-manifest.json').write_text(json.dumps(m))
                else:
                    self.assertIn('OBS FULL_DMM_UNIT_NATIVE_REPLY_FREE ',text)
                    text='\n'.join(l for l in text.splitlines() if not l.startswith('OBS FULL_DMM_UNIT_NATIVE_REPLY_FREE '))
                (dst/'console.log').write_text(text)
                result=subprocess.run(cli,capture_output=True,text=True,timeout=20)
                self.assertEqual(result.returncode,1,result.stdout+result.stderr)
                self.assertFalse(json.loads((dst/'dmm-unit-size-native-proof.json').read_text())['config_backed_unit_size_verified'])


if __name__=='__main__':unittest.main()
