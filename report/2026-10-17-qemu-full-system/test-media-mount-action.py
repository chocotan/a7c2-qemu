#!/usr/bin/env python3
"""Boundary tests for the menu-format mount probe.

The probe exists to ask the ORIGINAL firmware, through its own menu, to touch the
card. Three ways it could lie:

* a broken key plan, so the menu is never navigated and "no mount" is reported as
  if the format action had been tried -- run-zn6ghm6w did exactly that, because
  the release halves were scheduled at absolute 6 s and every press arrived with
  prev=1;
* a key still held from the first-setup walk, so the menu press arrives as a
  repeat -- run-a_sftdfi showed repeats 1..8 for DOWN;
* a negative result being upgraded to a pass.

These tests pin all three.
"""
import importlib.util
from pathlib import Path
import unittest

HERE=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('probe_media_mount_action',HERE/'probe-media-mount-action.py')
PROBE=importlib.util.module_from_spec(spec);spec.loader.exec_module(PROBE)


def receive(code,status,repeat,prev=0):
    return (f'OBS FULL_INPUT_RECEIVE tid=542 queue=0x5503e0 message=0x7f9db3b318 '
            f'code={code} status={status} prev={prev} repeat={repeat} from=1 inh=0')


def menu_phase():
    """The menu phase's own presses/releases, all fresh."""
    lines=[]
    for code,count in PROBE.MENU_PRESSES.items():
        for _ in range(count):
            lines.append(receive(code,1,0))
            lines.append(receive(code,0,0))
    return lines


def healthy(with_walk=True):
    lines=[]
    if with_walk:
        # What the walk actually looked like: releases got dropped, so prev stayed 1.
        lines += [receive('0x30',1,n,prev=1) for n in range(1,9)]
        lines += [receive('0x1ac',1,3,prev=1),receive('0x1ab',1,2,prev=1)]
    lines += menu_phase()
    return '\n'.join(lines)


class MenuPlan(unittest.TestCase):
    def test_every_menu_key_is_a_separate_absolute_press_and_release(self):
        plan=PROBE.menu_plan(490.0,6.0,0.6)
        self.assertEqual(len(plan),2*len(PROBE.MENU_KEYS))
        for entry in plan:
            # The old bug shape packed both halves into one entry with a relative
            # second half, which the runner reads as an absolute timestamp.
            self.assertNotIn(';',entry)
        times=[float(e.partition(':')[0]) for e in plan]
        self.assertEqual(times,sorted(times))
        for index,name in enumerate(PROBE.MENU_KEYS):
            press,release=plan[2*index],plan[2*index+1]
            self.assertIn(f'{name} 0 0x1 0 1',press)
            self.assertIn(f'{name} 0 0x0 0 1',release)
            self.assertAlmostEqual(float(release.partition(':')[0])
                                   -float(press.partition(':')[0]),0.6,places=6)

    def test_release_never_precedes_its_press(self):
        plan=PROBE.menu_plan(490.0,6.0,0.6)
        for index,name in enumerate(PROBE.MENU_KEYS):
            self.assertLess(float(plan[2*index].partition(':')[0]),
                            float(plan[2*index+1].partition(':')[0]))

    def test_presses_are_spaced_so_the_screen_can_redraw(self):
        plan=PROBE.menu_plan(490.0,6.0,0.6)
        presses=[float(plan[2*i].partition(':')[0]) for i in range(len(PROBE.MENU_KEYS))]
        self.assertEqual(presses,[490.0,496.0,502.0,508.0])

    def test_normalization_releases_the_walk_codes_before_the_menu_keys(self):
        plan=PROBE.normalize_plan(490.0)
        self.assertEqual(len(plan),len(PROBE.WALK_CODES))
        for entry in plan:
            self.assertIn('0 0x0 0 1',entry)
            self.assertLess(float(entry.partition(':')[0]),490.0)


class PressValidity(unittest.TestCase):
    def test_a_healthy_run_passes_even_though_the_walk_left_keys_held(self):
        self.assertEqual(PROBE.press_validity(healthy(),PROBE.MENU_KEYS),'')

    def test_a_menu_press_that_is_still_a_repeat_invalidates_the_run(self):
        # Exactly run-a_sftdfi: the walk's DOWN was never released, and the menu's
        # OWN DOWN press is therefore still counted as a repeat.
        text=healthy(with_walk=False)+'\n'+receive('0x30',1,9,prev=1)
        self.assertIn('still held',PROBE.press_validity(text,PROBE.MENU_KEYS))

    def test_a_missing_menu_press_invalidates_the_run(self):
        text=healthy(with_walk=False).replace(receive('0x1ac',1,0),'',1)
        self.assertIn('only',PROBE.press_validity(text,PROBE.MENU_KEYS))

    def test_a_missing_release_invalidates_the_run(self):
        text='\n'.join(receive(k,1,0) for k in PROBE.MENU_KEYS)
        self.assertIn('no release',PROBE.press_validity(text,PROBE.MENU_KEYS))

    def test_a_walk_release_before_the_test_press_does_not_count(self):
        text=receive('0x2',0,0)+'\n'+receive('0x2',1,0)
        self.assertIn('no release',PROBE.press_validity(text,('0x2',),{'0x2':1}))

    def test_one_final_release_cannot_cover_two_presses(self):
        text='\n'.join([receive('0x2',1,0),receive('0x2',1,0),receive('0x2',0,0)])
        self.assertIn('no release',PROBE.press_validity(text,('0x2',),{'0x2':2}))

    def test_the_first_broken_run_shape_is_rejected(self):
        # run-zn6ghm6w: release halves fired at 6 s, later presses were repeats.
        text='\n'.join([receive(k,0,0,prev=2147483647) for k in PROBE.MENU_KEYS]
                       +[receive('0x1ac',1,411),receive('0x1ac',1,412)])
        reason=PROBE.press_validity(text,PROBE.MENU_KEYS)
        self.assertTrue(reason)
        self.assertTrue('only' in reason or 'still held' in reason,reason)

    def test_only_the_last_presses_are_judged(self):
        # A walk that pressed MENU/ENTER many times must not fail the gate as long
        # as the menu phase's own presses are fresh.
        self.assertEqual(PROBE.press_validity(healthy(),PROBE.MENU_KEYS),'')


if __name__=='__main__':unittest.main()
