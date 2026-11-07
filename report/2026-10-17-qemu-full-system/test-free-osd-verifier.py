#!/usr/bin/env python3
import hashlib
import json
from pathlib import Path
import runpy
import tempfile
import unittest

HERE=Path(__file__).resolve().parent
VERIFY=runpy.run_path(str(HERE/'verify-free-osd.py'))['verify']


class FreeOsd(unittest.TestCase):
    def make(self,run,order,until=False):
        def screen(name):
            return ('OBS CREATE_SCREEN_ARGS call=1 id='+name+' count=28 orientation=0\n').encode()
        console=b'OBS OBSERVER_READY pid=1 base=0x1 MENU_FORCE_SET=(unset) MENU_FORCE_IN_FACTORY=(unset) FACTORY_HOOK=(unset) OPEN_SET=0x308 OPEN_SET_LOG_ONLY=1\n'
        console+=b''.join(screen(name) for name in order)
        console+=b'OBS OSD_TRANSPORT_SEND call=1 endpoint=0x8280074d source=0x9088076b bytes=96 shown=96 payload=00\n'
        console+=b'OBS OSD_TRANSPORT_RECEIVE call=16 tid=430 endpoint=0x8288076c source=0x8280074d bytes=8 shown=8 payload=0360000000000000\n'
        if until:console+=b'until marker\n'
        (run/'console.log').write_bytes(console)
        digest=hashlib.sha256(console).hexdigest()
        (run/'result.json').write_text(json.dumps({'state':'observation-completed',
            'terminal_evidence_checked':True,'terminal_console_sha256':digest}))
        (run/'inputs.json').write_text(json.dumps({'experiment':{'until_scalar_get':until}}))

    def test_advance_is_measured_not_assumed(self):
        with tempfile.TemporaryDirectory() as d:
            run=Path(d);self.make(run,['0x308'])
            proof=VERIFY(run)
            self.assertTrue(proof['boot_screen_created'])
            self.assertFalse(proof['shooting_screen_requested'])
            self.assertFalse(proof['visible_pixels_verified'])
            self.assertEqual(proof['osd_original_6003_receives'],1)
            # A --until-* run is not free-running evidence even with all screens.
            self.make(run,['0x308','0x347','0x343','0'],until=True)
            with self.assertRaises(ValueError):VERIFY(run)
            self.make(run,['0x308','0x347','0x343','0'])
            proof=VERIFY(run)
            self.assertTrue(proof['shooting_screen_requested'])
            self.assertFalse(proof['camera_startup_verified'])
            self.make(run,['0x308','0x347'])
            proof=VERIFY(run)
            self.assertTrue(proof['shooting_screen_requested'])
            self.assertFalse(proof['transition_screen_seen'])
            self.make(run,[],until=False)
            with self.assertRaises(ValueError):VERIFY(run)
            self.make(run,['0x308'])
            (run/'console.log').write_bytes((run/'console.log').read_bytes()+b'late\n')
            with self.assertRaises(ValueError):VERIFY(run)


if __name__=='__main__':unittest.main()
