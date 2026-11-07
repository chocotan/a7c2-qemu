#!/usr/bin/env python3
from pathlib import Path
import runpy
import subprocess
import sys
import unittest

HERE=Path(__file__).resolve().parent
PREFIX=b'''OBS FULL_PIN_FORMAT_COMMIT tid=15 format_cpu_consumed=1 end=1
OBS FULL_SCALAR_COMMIT tid=15 slot=4 type=0 dir=1 index=4 pin_state=1 owner=0x91670464 status=0 reply=0x6000 lease=1 request_free_rc=0 end=1
OBS FULL_SCALAR_NATIVE_REPLY_FREE tid=15 sender=15 waiter=1 destination=0x81cf61c3 reply=0x6000 lease=1 bytes=56 rc=0
OBS FULL_SCALAR_CONNECT_NATIVE_REPLY_FREE tid=15 sender=15 waiter=1 bytes=56 command=0x8001 rc=0
OBS FULL_PINMEM_COMMIT tid=15 slot=5 type=0 dir=2 index=2 pin_state=1 owner=0x90590818 status=0 reply=0x7000 lease=3 request_free_rc=0 end=1
OBS FULL_PINMEM_NATIVE_REPLY_FREE tid=15 sender=15 waiter=1 reply=0x7000 lease=3 bytes=56 rc=0
OBS FULL_ADF_COMMIT tid=15 slot=0 type=0 dir=1 index=0 pin_state=1 owner=0x9058003f status=0 reply=0x8000 lease=1 request_free_rc=0 end=1
OBS FULL_ADF_NATIVE_REPLY_FREE tid=15 sender=15 waiter=1 destination=0x81cf61c3 reply=0x8000 lease=1 bytes=56 rc=0
OBS FULL_PIN_REQUEST_OBSERVE tid=15 destination=0x90590818 source=0x81cf61c3 bytes=64 captured=64 raw=c361cf81a0a0a0a0010040001800000040000000000000000010010028000200000000000200000002000000180859900000000001000000000000003f005890
OBS FULL_ADF_CONNECT_NATIVE_REPLY_FREE tid=15 sender=15 waiter=1 bytes=56 command=0x8001 rc=0
OBS FULL_PINMEM_COMMIT tid=15 slot=7 type=4 dir=2 index=0 pin_state=1 owner=0x90590818 status=0 reply=0xa000 lease=4 request_free_rc=0 end=1
OBS FULL_PINMEM_NATIVE_REPLY_FREE tid=15 sender=15 waiter=1 reply=0xa000 lease=4 bytes=56 rc=0
'''
HDMI=b'''OBS FULL_HDMIPIN_COMMIT tid=15 slot=0 type=4 dir=1 index=0 pin_state=1 owner=0x909a015a status=0 reply=0xb000 lease=1 request_free_rc=0 end=1
OBS FULL_HDMIPIN_NATIVE_REPLY_FREE tid=15 sender=15 waiter=1 destination=0x81cf61c3 reply=0xb000 lease=1 bytes=56 rc=0
OBS FULL_PIN_REQUEST_OBSERVE tid=15 destination=0x90590818 source=0x81cf61c3 bytes=64 captured=64 raw=c361cf81a0a0a0a0010040001800000040000000000000000010010028000200040000000200000000000000180859900400000001000000000000005a019a90
'''


class HdmiPinWiring(unittest.TestCase):
    def test_explicit_profile_and_environment(self):
        for args,reason in ((['--hdmi-pin-service','registry'],'HDMI pin registry requires init2'),
                            (['--until-hdmi-pin-get'],'HDMI pin observation requires registry')):
            r=subprocess.run([sys.executable,'-B',str(HERE/'run-full-system.py'),*args],capture_output=True,text=True)
            self.assertEqual(r.returncode,2);self.assertIn(reason,r.stderr)
        source=(HERE/'guest/bootin-wrapper').read_text()
        self.assertLess(source.index('unset FULLSYSTEM_HDMI_PIN_SERVICE'),source.index('/simulation/seed-power-on'))
        subprocess.run(['bash','-n',str(HERE/'guest/bootin-wrapper')],check=True)

    def test_unmocked_same_waiter_order_and_wire(self):
        ready=runpy.run_path(str(HERE/'run-full-system.py'))['hdmi_pin_get_ready']
        self.assertTrue(ready(PREFIX+HDMI))
        for bad in (HDMI,PREFIX,HDMI+PREFIX,PREFIX+HDMI.replace(b'tid=15',b'tid=16').replace(b'sender=15',b'sender=16'),
                    PREFIX+HDMI.replace(b'pin_state=1',b'pin_state=2'),PREFIX+HDMI.replace(b'status=0',b'status=57346'),
                    PREFIX+HDMI.replace(b'lease=1 bytes',b'lease=2 bytes'),PREFIX+HDMI.replace(b'5a019a90',b'5b019a90')):
            self.assertFalse(ready(bad))


if __name__=='__main__':unittest.main()
