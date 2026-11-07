#!/usr/bin/env python3
"""Boundary tests for the media-in notification probe.

The probe injects the raw codes the firmware itself synthesises from a media
notification (0x0c000003..0x0c000012 -> UIBIZ_KEY_MEDIA_INOUT00..15). Two things
must not drift silently: the code set, and the press validity gate.
"""
import importlib.util
from pathlib import Path
import unittest

HERE=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('probe_media_notify',HERE/'probe-media-notify.py')
PROBE=importlib.util.module_from_spec(spec);spec.loader.exec_module(PROBE)


def receive(code,status,repeat=0):
    return (f'OBS FULL_INPUT_RECEIVE tid=542 queue=0x5503e0 message=0x7f9db3b318 '
            f'code={code} status={status} prev=0 repeat={repeat} from=1 inh=0')


class CodeSet(unittest.TestCase):
    def test_codes_cover_both_media_families(self):
        # 0x0c000000..0x0c000002 are REMOVABLEMEDIA1..3 (the card slots);
        # 0x0c000003..0x0c000012 are INOUT00..15. The first run only tried the
        # INOUT family and the mount path stayed silent, so both are injected.
        self.assertEqual(PROBE.REMOVABLE_CODES,tuple(hex(0x0c000000+k) for k in range(3)))
        self.assertEqual(PROBE.INOUT_CODES,tuple(hex(0x0c000003+k) for k in range(16)))
        self.assertEqual(PROBE.MEDIA_CODES,PROBE.REMOVABLE_CODES+PROBE.INOUT_CODES)
        self.assertEqual(len(PROBE.MEDIA_CODES),19)
        values=[int(c,16) for c in PROBE.MEDIA_CODES]
        self.assertEqual(values,list(range(0x0c000000,0x0c000013)))

    def test_provenance_is_declared_as_modelled(self):
        # A future edit must not quietly turn the model into a claim about the CP.
        source=(HERE/'probe-media-notify.py').read_text()
        self.assertIn("'notification_source':'modeled",source)
        self.assertIn('media_io_verified',source)


class NotifyPlan(unittest.TestCase):
    def test_all_codes_get_one_press_and_one_release_in_order(self):
        plan=PROBE.notify_plan(500.0,3.0,0.6,1)
        self.assertEqual(len(plan),2*len(PROBE.MEDIA_CODES))
        for entry in plan:
            self.assertNotIn(';',entry)
        times=[float(e.partition(':')[0]) for e in plan]
        self.assertEqual(times,sorted(times))
        for index,code in enumerate(PROBE.MEDIA_CODES):
            press,release=plan[2*index],plan[2*index+1]
            self.assertIn(f'{code} 0 1 0 1',press)
            self.assertIn(f'{code} 0 0 0 1',release)
            self.assertAlmostEqual(float(release.partition(':')[0])
                                   -float(press.partition(':')[0]),0.6,places=6)

    def test_status_is_carried_into_the_record(self):
        plan=PROBE.notify_plan(500.0,3.0,0.6,0)
        self.assertIn('0 0 0 1',plan[0].split(':')[1][-12:])


class Gate(unittest.TestCase):
    def test_all_sixteen_fresh_presses_pass(self):
        text='\n'.join(receive(c,1)+'\n'+receive(c,0) for c in PROBE.MEDIA_CODES)
        self.assertEqual(PROBE.press_validity(text,PROBE.MEDIA_CODES,
                                              {c:1 for c in PROBE.MEDIA_CODES}),'')

    def test_a_missing_code_invalidates_the_run(self):
        text='\n'.join(receive(c,1)+'\n'+receive(c,0)
                       for c in PROBE.MEDIA_CODES if c!=PROBE.MEDIA_CODES[7])
        self.assertIn('only',PROBE.press_validity(text,PROBE.MEDIA_CODES,
                                                  {c:1 for c in PROBE.MEDIA_CODES}))

    def test_a_repeat_invalidates_the_run(self):
        text='\n'.join(receive(c,1)+'\n'+receive(c,0) for c in PROBE.MEDIA_CODES)
        text=text.replace(receive(PROBE.MEDIA_CODES[3],1),receive(PROBE.MEDIA_CODES[3],1,repeat=4),1)
        self.assertIn('still held',PROBE.press_validity(text,PROBE.MEDIA_CODES,
                                                        {c:1 for c in PROBE.MEDIA_CODES}))


class Seen(unittest.TestCase):
    def test_an_unpadded_code_is_recognised(self):
        # The firmware prints `code=0xc000003`; a padded `0x0c000003` regex found 0.
        text=receive('0xc000003',1)
        self.assertEqual(PROBE.codes_seen(text,PROBE.MEDIA_CODES),['0xc000003'])

    def test_unrelated_codes_are_ignored(self):
        text=receive('0x1ab',1)
        self.assertEqual(PROBE.codes_seen(text,PROBE.MEDIA_CODES),[])

    def test_removable_and_inout_families_are_both_reported(self):
        text=receive('0xc000000',1)+'\n'+receive('0xc000012',1)
        self.assertEqual(PROBE.codes_seen(text,PROBE.MEDIA_CODES),['0xc000000','0xc000012'])


if __name__=='__main__':unittest.main()
