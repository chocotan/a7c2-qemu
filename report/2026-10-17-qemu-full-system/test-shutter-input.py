#!/usr/bin/env python3
"""Boundary tests for the two-stage shutter probe.

The probe presses the ORIGINAL shutter with S1=0x1f1 / S2=0xa7 (from appFw's
raw->UIBIZ table at 0x3704b98). The order matters: AF/AE lock happens during the
half press, capture on the full press, and the release order is the mirror of the
press order. If the plan got that wrong, the observations would be worthless.
"""
import importlib.util
from pathlib import Path
import unittest

HERE=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('probe_shutter_input',HERE/'probe-shutter-input.py')
PROBE=importlib.util.module_from_spec(spec);spec.loader.exec_module(PROBE)


class ShutterPlan(unittest.TestCase):
    def test_two_stage_order_is_half_then_full_then_release_full_then_half(self):
        plan=PROBE.shutter_plan(500.0,5.0,1.0)
        self.assertEqual(len(plan),4)
        for entry in plan:
            self.assertNotIn(';',entry)
        self.assertIn('0x1f1 0 1 0 1',plan[0])   # S1 down
        self.assertIn('0xa7 0 1 0 1',plan[1])    # S2 down
        self.assertIn('0xa7 0 0 0 1',plan[2])    # S2 up
        self.assertIn('0x1f1 0 0 0 1',plan[3])   # S1 up

    def test_times_are_absolute_and_ascending(self):
        times=[float(e.partition(':')[0]) for e in PROBE.shutter_plan(500.0,5.0,1.0)]
        self.assertEqual(times,sorted(times))
        self.assertEqual(times[0],500.0)
        self.assertAlmostEqual(times[1]-times[0],5.0,places=6)   # AF/AE settle window

    def test_the_half_press_is_held_through_the_full_press(self):
        # S1 up must come after S2 up, otherwise the firmware sees a bare full press.
        times=[float(e.partition(':')[0]) for e in PROBE.shutter_plan(500.0,5.0,1.0)]
        self.assertGreater(times[3],times[2])

    def test_codes_match_the_body_key_table(self):
        self.assertEqual(PROBE.S1,0x1f1)
        self.assertEqual(PROBE.S2,0xa7)
        self.assertEqual(PROBE.SHUTTER_KEYS,('0x1f1','0xa7'))


if __name__=='__main__':unittest.main()
