import json
import os
from pathlib import Path
import runpy
import shutil
import subprocess
import tempfile
import unittest

HERE=Path(__file__).resolve().parent
VERIFY=runpy.run_path(str(HERE/'verify-native-dialog-resource.py'))['verify']


@unittest.skipUnless(os.environ.get('A7C2_NATIVE_DIALOG_RUN'),'Set A7C2_NATIVE_DIALOG_RUN')
class DialogResourceEvidence(unittest.TestCase):
    def test_actual_module_text_and_original_predicate_input(self):
        p=VERIFY(Path(os.environ['A7C2_NATIVE_DIALOG_RUN']))
        self.assertTrue(p['actual_dialog_resource_chain_verified'])
        self.assertEqual(p['module_index'],'0x262')
        self.assertEqual(p['secondary_model_name'],'media_error_slot1')
        self.assertEqual(p['secondary_model_value'],1)
        self.assertFalse(p['filesystem_or_mount_error_proven'])

    def test_wrong_index_model_resource_or_method_rejects_stale_success(self):
        src=Path(os.environ['A7C2_NATIVE_DIALOG_RUN'])
        for old,new in (('module_index=0x262','module_index=0x233'),
                        ('text_resource=0x200a73b','text_resource=0'),
                        ('method_appFw_offset=0x1882dc8','method_appFw_offset=0'),
                        (': 02 00 00 00',': 00 00 00 00'),('selected_app_identity',''),('secondary_model',''),('infra_key_injection','')):
            with self.subTest(old=old),tempfile.TemporaryDirectory() as temporary:
                dst=Path(temporary)
                for name in ('console.log','runtime-manifest.json','summary.json','headless-osd-pixels-rgba4444-software.png'):
                    shutil.copyfile(src/name,dst/name)
                summary=json.loads((dst/'summary.json').read_text());summary['run']=str(dst)
                (dst/'summary.json').write_text(json.dumps(summary))
                text=(dst/'console.log').read_text()
                if old=='infra_key_injection':
                    manifest=json.loads((dst/'runtime-manifest.json').read_text())
                    manifest['infra_key_injection']='0x1ac,0,1,0,1,0.05,0'
                    (dst/'runtime-manifest.json').write_text(json.dumps(manifest))
                elif old=='selected_app_identity':
                    manifest=json.loads((dst/'runtime-manifest.json').read_text())
                    manifest['selected_initramfs_verified_files']['usr/lib/appFw.so']='0'*64
                    (dst/'runtime-manifest.json').write_text(json.dumps(manifest))
                elif old=='secondary_model':
                    import re
                    block=re.search(r'^DIALOG_MODULE_233_INPUT_BEGIN\r?\n(.*?)^DIALOG_MODULE_233_INPUT_RC=0\r?$',text,re.M|re.S)
                    self.assertIsNotNone(block);self.assertIn(': 01 00 00 00',block[1])
                    text=text[:block.start(1)]+block[1].replace(': 01 00 00 00',': 00 00 00 00')+text[block.end(1):]
                    (dst/'console.log').write_text(text)
                else:
                    self.assertIn(old,text);(dst/'console.log').write_text(text.replace(old,new))
                (dst/'dialog-resource-chain-proof.json').write_text(json.dumps({'actual_dialog_resource_chain_verified':True}))
                result=subprocess.run(['python3',str(HERE/'verify-native-dialog-resource.py'),str(dst)],capture_output=True,text=True,timeout=20)
                self.assertEqual(result.returncode,1,result.stdout+result.stderr)
                self.assertFalse(json.loads((dst/'dialog-resource-chain-proof.json').read_text())['actual_dialog_resource_chain_verified'])


if __name__=='__main__':unittest.main()
