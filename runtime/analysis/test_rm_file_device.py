from pathlib import Path
import subprocess
import tempfile
import unittest

HERE=Path(__file__).resolve().parent


class RmFileDevice(unittest.TestCase):
    def test_owned_file_protocol_and_failure_paths(self):
        with tempfile.TemporaryDirectory() as temporary:
            binary=Path(temporary)/'rm-test'
            compiled=subprocess.run(['cc','-std=c11','-Wall','-Wextra','-Werror','-g','-DNATIVE_RM_FILE_TEST','-fsanitize=address,undefined',
                            '-fno-omit-frame-pointer','-no-pie','-pthread',str(HERE/'rm-file-device.c'),
                            str(HERE/'sd-state.c'),str(HERE/'sd-hotplug-runtime.c'),
                            str(HERE/'test-rm-file-device.c'),'-ldl','-o',str(binary)],text=True,capture_output=True)
            self.assertEqual(compiled.returncode,0,compiled.stdout+compiled.stderr)
            for case in ('normal','large','bad-geometry','oversize','symlink','allocfail','sendfail','alias','wrongfree','fork','unregfail','fastfree',
                         'sparse10g','ten-gib-without-profile','sparse-wrong-size','sparse-bad-profile',
                         'block-refuse-regular','block-bad-profile',
                         'front-normal','front-allocfail','front-sendfail','front-fastfree','front-wrongfree'):
                with self.subTest(case=case),tempfile.TemporaryDirectory() as working:
                    result=subprocess.run([str(binary),case],cwd=working,capture_output=True,text=True,timeout=20)
                    self.assertEqual(result.returncode,0,result.stdout+result.stderr)


if __name__=='__main__':unittest.main()
