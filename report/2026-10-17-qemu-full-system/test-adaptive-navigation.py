#!/usr/bin/env python3
"""A menu search must not send fallback ENTER into an unknown confirmation page."""
from pathlib import Path
import runpy
import unittest

RUNNER = runpy.run_path(str(Path(__file__).with_name('run-full-system.py')))
phase = RUNNER['adaptive_phase']
seek_keys = RUNNER['adaptive_seek_keys']


class NavigationBoundary(unittest.TestCase):
    def test_adaptive_taps_are_admitted_by_actual_mailbox_parser(self):
        mailbox=runpy.run_path(str(Path(__file__).with_name('low-latency-input.py')))
        for code in (0x1ab,0x1ac,3,0x30,0x15,0x1af):
            command=RUNNER['input_tap_command'](code)
            self.assertEqual(mailbox['parse_command'](command),mailbox['packet'](2,code,1,50))
        for code in (True,-1,0x100000000,'MENU; echo hidden'):
            with self.assertRaises(ValueError):RUNNER['input_tap_command'](code)

    def test_search_waits_for_startup_completion(self):
        self.assertEqual(phase({}, 'menu_format', 120, 140), 'startup')

    def test_no_fallback_keys_while_waiting_for_menu(self):
        self.assertEqual(phase({'adaptive_stopped': 'shooting'}, 'menu_format', 120, 110),
                         'waiting-for-seek')

    def test_pending_search_resumes_only_its_search_phase(self):
        self.assertEqual(phase({'adaptive_stopped': 'shooting'}, 'menu_format', 120, 120),
                         'seeking')

    def test_target_gets_exactly_one_enter_then_loop_is_done(self):
        keys, found = seek_keys('menu_format', 'menu_format', 'UP', True, 0)
        self.assertEqual(keys, ['ENTER'])
        self.assertTrue(found)
        result = {'adaptive_stopped': 'menu_format', 'adaptive_seek_found': 'menu_format'}
        # An unknown dialog following this state must not enter the screenshot/key loop.
        self.assertEqual(phase(result, 'menu_format', 120, 125), 'done')
        self.assertEqual(phase(result, 'menu_format', 120, 180), 'done')

    def test_search_without_enter_stops_without_a_press(self):
        self.assertEqual(seek_keys('menu_format', 'menu_format', 'UP', False, 2), ([], True))

    def test_unknown_screens_only_get_search_direction(self):
        self.assertEqual(seek_keys(None, 'menu_format', 'UP', True, 4), (['UP'], False))

    def test_search_is_bounded_and_never_confirms_on_exhaustion(self):
        with self.assertRaisesRegex(TimeoutError, 'no confirmation sent'):
            seek_keys(None, 'menu_format', 'UP', True, 16)

    def test_startup_without_a_search_stays_stopped(self):
        self.assertEqual(phase({'adaptive_stopped': 'shooting'}, None, None, 100), 'done')


if __name__ == '__main__':
    unittest.main()
