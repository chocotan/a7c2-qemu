#!/usr/bin/env python3
"""Boundary tests for the power-key probe.

Two mistakes this pins down:

* pressing POWER without a release, so the front-end sees a held key and the run
  is not evidence at all;
* calling a harness teardown a successful power-off. The real interactive session
  ended right after POWER was pressed three times, and its stage result was
  "interrupted; cleaning this owned VM" -- that is our teardown, not the camera
  switching itself off.
"""
import importlib.util
from pathlib import Path
import unittest

HERE=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('probe_power_key',HERE/'probe-power-key.py')
PROBE=importlib.util.module_from_spec(spec);spec.loader.exec_module(PROBE)


class PowerPlan(unittest.TestCase):
    def test_one_press_and_release_of_the_power_code(self):
        plan=PROBE.power_plan(500.0,0.6,1)
        self.assertEqual(len(plan),2)
        self.assertIn('0x2 0 0x1 0 1',plan[0])
        self.assertIn('0x2 0 0x0 0 1',plan[1])
        self.assertAlmostEqual(float(plan[1].partition(':')[0])
                               -float(plan[0].partition(':')[0]),0.6,places=6)

    def test_several_presses_are_spaced_and_ordered(self):
        plan=PROBE.power_plan(500.0,0.6,3)
        self.assertEqual(len(plan),6)
        times=[float(e.partition(':')[0]) for e in plan]
        self.assertEqual(times,sorted(times))
        for index in range(3):
            self.assertIn('0x1', plan[2*index])
            self.assertIn('0x0', plan[2*index+1])

    def test_the_code_is_the_tact_power_entry_not_the_slikey(self):
        self.assertEqual(PROBE.POWER,0x02)
        self.assertEqual(PROBE.POWER_KEYS,('0x2',))


class Verdict(unittest.TestCase):
    def test_power_gate_table_indices_distinguish_switch_and_tact(self):
        for index,gate in ((25,1),(18,0),(21,0)):
            raw=index.to_bytes(4,'little').hex(' ')
            text=('POWER_GATE_BEGIN\nREADMEM /proc/444/mem address=7f05bc35b0 bytes=4\n'
                  '0000007f05bc35b0: '+raw+'\nPOWER_GATE_END\n')
            got=PROBE.power_gate_snapshots(text)
            self.assertTrue(got[0]['verified'])
            self.assertEqual(got[0]['gate'],gate)

    def test_power_gate_short_read_and_unknown_index_are_not_guessed(self):
        self.assertEqual(PROBE.power_gate_snapshots('command echo POWER_GATE_BEGIN'),[])
        text=('POWER_GATE_BEGIN\nREADMEM /proc/444/mem address=7f05bc35b0 bytes=4\n'
              '0000007f05bc35b0: ff ff ff ff\nPOWER_GATE_END\n')
        self.assertFalse(PROBE.power_gate_snapshots(text)[0]['verified'])
        self.assertNotIn(';',PROBE.power_gate_command())

    def test_a_real_power_path_counts(self):
        self.assertTrue(PROBE.power_off_verified(True,True,False,True,True))

    def test_a_harness_teardown_never_counts(self):
        # Exactly the shape of the interactive session that ended after POWER.
        self.assertFalse(PROBE.power_off_verified(True,True,True,True,True))

    def test_observation_completion_with_live_vm_is_not_a_natural_exit(self):
        self.assertTrue(PROBE.harness_terminated('',{'state':'observation-completed',
                        'owned_process_returncode_before_cleanup':None}))
        self.assertFalse(PROBE.harness_terminated('',{'owned_process_returncode_before_cleanup':0}))

    def test_no_firmware_marker_means_no_verification(self):
        self.assertFalse(PROBE.power_off_verified(True,False,False))

    def test_an_invalid_run_never_counts(self):
        self.assertFalse(PROBE.power_off_verified(False,True,False))

    def test_markers_without_shutdown_and_natural_exit_do_not_count(self):
        self.assertFalse(PROBE.power_off_verified(True,True,False))
        self.assertFalse(PROBE.power_off_verified(True,True,False,True,False))
        self.assertFalse(PROBE.power_off_verified(True,True,False,False,True))

    def test_boot_markers_are_excluded_from_power_press_evidence(self):
        text='set_pre_power_off_seq\nOBS FULL_INPUT_RECEIVE code=0x2 status=1\nnew event\n'
        self.assertNotIn('set_pre_power_off_seq',PROBE.after_power_press(text))
        self.assertIn('new event',PROBE.after_power_press(text))
        self.assertEqual(PROBE.after_power_press('power_off at boot\n'),'')

    def test_release_and_unrelated_keys_are_not_the_trigger(self):
        self.assertEqual(PROBE.after_power_press('OBS FULL_INPUT_RECEIVE code=0x2 status=0\npoweroff\n'),'')
        self.assertEqual(PROBE.after_power_press('OBS FULL_INPUT_RECEIVE code=0x20 status=1\npoweroff\n'),'')


if __name__=='__main__':unittest.main()
