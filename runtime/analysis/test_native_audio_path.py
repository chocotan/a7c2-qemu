import json
import os
from pathlib import Path
import runpy
import shutil
import subprocess
import tempfile
import unittest

VERIFY=runpy.run_path(str(Path(__file__).with_name('verify-native-audio-path.py')))['verify']


@unittest.skipUnless(os.environ.get('A7C2_NATIVE_AUDIO_PATH_RUN'),'Set A7C2_NATIVE_AUDIO_PATH_RUN')
class NativePath(unittest.TestCase):
    def test_observed_route_and_original_waiter(self):
        proof=VERIFY(Path(os.environ['A7C2_NATIVE_AUDIO_PATH_RUN']))
        self.assertTrue(proof['system_sound_path_verified'])
        self.assertFalse(proof['audio_output_verified'])

    def test_route_control_or_reply_free_corruption_rejected(self):
        src=Path(os.environ['A7C2_NATIVE_AUDIO_PATH_RUN'])
        for kind in ('cache','control','free'):
            with self.subTest(kind=kind),tempfile.TemporaryDirectory() as temporary:
                dst=Path(temporary)
                for name in ('console.log','summary.json','runtime-manifest.json','virt.dtb','system-sound-ram.bin'):
                    shutil.copyfile(src/name,dst/name)
                summary=json.loads((dst/'summary.json').read_text());summary['run']=str(dst)
                (dst/'summary.json').write_text(json.dumps(summary))
                text=(dst/'console.log').read_text()
                if kind=='cache':
                    self.assertIn('cached_path=7',text);text=text.replace('cached_path=7','cached_path=0')
                elif kind=='control':
                    self.assertIn('control_consumed=1',text);text=text.replace('control_consumed=1','control_consumed=0')
                else:
                    self.assertIn('command=0x32a',text)
                    text='\n'.join(l for l in text.splitlines() if not
                        ('FULL_AUDIO_NATIVE_REPLY_FREE ' in l and 'command=0x32a ' in l))
                cli=Path(__file__).with_name('verify-native-audio-path.py')
                first=subprocess.run(['python3',str(cli),str(dst)],capture_output=True,text=True,timeout=30)
                self.assertEqual(first.returncode,0,first.stderr)
                self.assertTrue(json.loads((dst/'audio-path-native-proof.json').read_text())['system_sound_path_verified'])
                (dst/'console.log').write_text(text)
                with self.assertRaises((ValueError,StopIteration)):
                    VERIFY(dst)
                second=subprocess.run(['python3',str(cli),str(dst)],capture_output=True,text=True,timeout=30)
                self.assertEqual(second.returncode,1,second.stderr)
                self.assertFalse(json.loads((dst/'audio-path-native-proof.json').read_text())['system_sound_path_verified'])


if __name__=='__main__':
    unittest.main()
