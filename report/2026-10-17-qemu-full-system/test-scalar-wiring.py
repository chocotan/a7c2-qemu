#!/usr/bin/env python3
from pathlib import Path
import runpy
import subprocess
import sys
import unittest

HERE=Path(__file__).resolve().parent


class ScalarWiring(unittest.TestCase):
    def test_registry_requires_explicit_init2(self):
        result=subprocess.run([sys.executable,'-B',str(HERE/'run-full-system.py'),'--scalar-service','registry'],capture_output=True,text=True)
        self.assertEqual(result.returncode,2)
        self.assertIn('Scalar registry requires init2',result.stderr)

    def test_inherited_profile_cleared(self):
        source=(HERE/'guest/bootin-wrapper').read_text()
        self.assertLess(source.index('unset FULLSYSTEM_SCALAR_SERVICE'),source.index('/simulation/seed-power-on'))
        self.assertLess(source.index('unset FULLSYSTEM_SCALAR_CONNECTION'),source.index('/simulation/seed-power-on'))
        subprocess.run(['bash','-n',str(HERE/'guest/bootin-wrapper')],check=True)

    def test_stop_requires_same_waiter_and_actual_free_after_commit(self):
        ready=runpy.run_path(str(HERE/'run-full-system.py'))['scalar_get_ready']
        fmt=b'OBS FULL_PIN_FORMAT_COMMIT tid=15 handle=0x8000 format_cpu_consumed=1 end=1\n'
        commit=b'OBS FULL_SCALAR_COMMIT tid=15 slot=4 type=0 dir=1 index=4 pin_state=1 owner=0x91670464 status=0 queries=1 reply=0x7000 lease=1 request_free_rc=0 connect_performed=0\n'
        free=b'OBS FULL_SCALAR_NATIVE_REPLY_FREE tid=15 sender=15 waiter=1 destination=0x81a00001 reply=0x7000 lease=1 bytes=56 rc=0\n'
        self.assertTrue(ready(fmt+commit+free))
        self.assertFalse(ready(fmt+commit))
        self.assertFalse(ready(fmt+commit+free.replace(b'lease=1',b'lease=2')))
        self.assertFalse(ready(fmt+commit+free.replace(b'tid=15',b'tid=16')))
        self.assertFalse(ready(fmt+free+commit))

    def test_second_edge_requires_scalar_and_first_format(self):
        result=subprocess.run([sys.executable,'-B',str(HERE/'run-full-system.py'),'--scalar-connection','control'],capture_output=True,text=True)
        self.assertEqual(result.returncode,2)
        self.assertIn('requires Scalar registry',result.stderr)


if __name__=='__main__':unittest.main()
