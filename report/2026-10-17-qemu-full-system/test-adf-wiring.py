#!/usr/bin/env python3
from pathlib import Path
import runpy
import subprocess
import sys
import unittest

HERE=Path(__file__).resolve().parent


class AdfWiring(unittest.TestCase):
    def test_default_off_and_prerequisites(self):
        for args,reason in ((['--adf-service','registry'],'ADF registry requires init2'),
                            (['--until-adf-get'],'ADF Get observation requires registry'),
                            (['--adf-connection','control'],'ADF connection requires ADF registry'),
                            (['--until-adf-connection'],'ADF connection observation requires control')):
            result=subprocess.run([sys.executable,'-B',str(HERE/'run-full-system.py'),*args],capture_output=True,text=True)
            self.assertEqual(result.returncode,2);self.assertIn(reason,result.stderr)
        source=(HERE/'guest/bootin-wrapper').read_text()
        self.assertLess(source.index('unset FULLSYSTEM_ADF_SERVICE'),source.index('/simulation/seed-power-on'))
        self.assertLess(source.index('unset FULLSYSTEM_ADF_CONNECTION'),source.index('/simulation/seed-power-on'))
        subprocess.run(['bash','-n',str(HERE/'guest/bootin-wrapper')],check=True)

    def test_ordered_free_then_actual_next_connect(self):
        ready=runpy.run_path(str(HERE/'run-full-system.py'))['adf_get_ready']
        prefix=(b'OBS FULL_PIN_FORMAT_COMMIT tid=15 handle=0x8000 format_cpu_consumed=1 end=1\n'
                b'OBS FULL_SCALAR_COMMIT tid=15 slot=4 type=0 dir=1 index=4 pin_state=1 owner=0x91670464 status=0 queries=1 reply=0x6000 lease=1 request_free_rc=0 end=1\n'
                b'OBS FULL_SCALAR_NATIVE_REPLY_FREE tid=15 sender=15 waiter=1 destination=0x81cf61c3 reply=0x6000 lease=1 bytes=56 rc=0\n')
        connection=b'OBS FULL_SCALAR_CONNECT_NATIVE_REPLY_FREE tid=15 sender=15 waiter=1 destination=0x81cf61c3 bytes=56 command=0x8001 rc=0\n'
        out2=b'OBS FULL_PINMEM_COMMIT tid=15 slot=5 type=0 dir=2 index=2 pin_state=1 owner=0x90590818 status=0 reply=0x7000 lease=3 request_free_rc=0 end=1\n'
        outfree=b'OBS FULL_PINMEM_NATIVE_REPLY_FREE tid=15 sender=15 waiter=1 destination=0x81cf61c3 reply=0x7000 lease=3 bytes=56 rc=0\n'
        commit=b'OBS FULL_ADF_COMMIT tid=15 slot=0 type=0 dir=1 index=0 pin_state=1 owner=0x9058003f status=0 reply=0x8000 lease=1 request_free_rc=0 end=1\n'
        free=b'OBS FULL_ADF_NATIVE_REPLY_FREE tid=15 sender=15 waiter=1 destination=0x81cf61c3 expected=0x81cf61c3 reply=0x8000 lease=1 bytes=56 rc=0\n'
        request=b'OBS FULL_PIN_REQUEST_OBSERVE tid=15 destination=0x90590818 source=0x81cf61c3 bytes=64 captured=64 raw=c361cf81a0a0a0a0010040001800000040000000000000000010010028000200000000000200000002000000180859900000000001000000000000003f005890\n'
        console=out2+outfree+commit+free+request
        self.assertTrue(ready(prefix+connection+console))
        full=prefix+connection+console
        third=(b'OBS FULL_ADF_CONNECT_NATIVE_REPLY_FREE tid=15 sender=15 waiter=1 destination=0x81cf61c3 reply=0x9000 bytes=56 command=0x8001 rc=0\n'
               b'OBS FULL_PINMEM_COMMIT tid=15 slot=7 type=4 dir=2 index=0 pin_state=1 owner=0x90590818 status=0 reply=0xa000 lease=4 request_free_rc=0 end=1\n'
               b'OBS FULL_PINMEM_NATIVE_REPLY_FREE tid=15 sender=15 waiter=1 destination=0x81cf61c3 reply=0xa000 lease=4 bytes=56 rc=0\n')
        third_ready=runpy.run_path(str(HERE/'run-full-system.py'))['adf_connection_ready']
        self.assertTrue(third_ready(full+third))
        self.assertFalse(third_ready(full))
        self.assertFalse(third_ready(third+full))
        self.assertFalse(third_ready(full+third.replace(b'tid=15',b'tid=16').replace(b'sender=15',b'sender=16')))
        self.assertFalse(third_ready(full+third.replace(b'lease=4 bytes',b'lease=5 bytes')))
        for bad in (out2+outfree+commit+request, out2+outfree+free+commit+request,
                    out2+outfree+commit+request+free,out2+commit+free+request,
                    console.replace(b'3f005890',b'40005890'),console.replace(b'sender=15',b'sender=16'),
                    console.replace(b'a0a0a0a0010040',b'a0a0a0a0010050'),
                    console.replace(b'bytes=56 rc=0',b'bytes=56 rc=-1'),console.replace(b'lease=1 bytes',b'lease=2 bytes')):
            self.assertFalse(ready(prefix+connection+bad))
        # Full unmocked join: unrelated waiter and same waiter before predecessor.
        unrelated=console.replace(b'tid=15',b'tid=16').replace(b'sender=15',b'sender=16')
        self.assertFalse(ready(prefix+unrelated+connection+out2+outfree))
        self.assertFalse(ready(prefix+console+connection+out2+outfree))
        self.assertFalse(ready(prefix+connection+unrelated))
        self.assertFalse(ready(prefix+connection.replace(b'tid=15',b'tid=16').replace(b'sender=15',b'sender=16')+console))
        self.assertFalse(ready(console))


if __name__=='__main__':unittest.main()
