#!/usr/bin/env python3
"""Boundary tests for the mcmn subscribe/replay probe.

The probe exists to turn "the mount did not happen" into one concrete edge: does the
original driver replay its cached 7-byte front-end state to a subscriber, and are
those bytes the ones we published?
"""
import importlib.util
from pathlib import Path
import unittest

HERE=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('probe_mcmn_subscribe',HERE/'probe-mcmn-subscribe.py')
PROBE=importlib.util.module_from_spec(spec);spec.loader.exec_module(PROBE)


class Plan(unittest.TestCase):
    def test_publish_comes_before_subscribe(self):
        plan=PROBE.plan_for('70:/simulation/inject-key a',505.0,545.0,(2,0,0,2,0,2,0))
        publish=next(i for i,e in enumerate(plan) if 'cp-rm-notify' in e)
        subscribe=next(i for i,e in enumerate(plan) if 'mcmn-query subscribe' in e)
        self.assertLess(publish,subscribe)

    def test_every_entry_is_one_command(self):
        for entry in PROBE.plan_for('70:x',505.0,545.0,(2,0,0,2,0,2,0)):
            self.assertNotIn(';',entry)
            self.assertNotIn('$',entry)

    def test_the_packet_is_passed_as_seven_arguments(self):
        plan=PROBE.plan_for('70:x',505.0,545.0,(2,0,0,2,0,2,0))
        entry=next(e for e in plan if 'cp-rm-notify' in e)
        self.assertTrue(entry.endswith('/simulation/cp-rm-notify 2 0 0 2 0 2 0'))


class Verdict(unittest.TestCase):
    def test_a_matching_replay_passes(self):
        # Measured shape: the 7-byte state is the direct reply to command 3.
        text=('CP_RM_NOTIFY_SENT rc=0\n'
              'MCMN_SUBSCRIBE_SEND destination=0x80d9016e rc=0\n'
              'MCMN_SUBSCRIBE_REPLY_SIZE bytes=7\n'
              'MCMN_QUERY_SUBSCRIBE_REPLY command=3 bytes=7 raw=02000002000200\n')
        result=PROBE.verdict(text,(2,0,0,2,0,2,0))
        self.assertTrue(result['published'])
        self.assertTrue(result['subscription_accepted'])
        self.assertEqual(result['state_bytes'],7)
        self.assertTrue(result['replay_matches_sent'])

    def test_a_different_replay_is_reported_as_mismatch(self):
        text=('CP_RM_NOTIFY_SENT rc=0\nMCMN_SUBSCRIBE_SEND destination=0x80d9016e rc=0\n'
              'MCMN_SUBSCRIBE_REPLY_SIZE bytes=7\n'
              'MCMN_QUERY_SUBSCRIBE_REPLY command=3 bytes=7 raw=02000007000200\n')
        result=PROBE.verdict(text,(2,0,0,2,0,2,0))
        self.assertTrue(result['subscription_accepted'])
        self.assertFalse(result['replay_matches_sent'])

    def test_no_replay_is_not_a_pass(self):
        text=('CP_RM_NOTIFY_SENT rc=0\nMCMN_SUBSCRIBE_SEND destination=0x80d9016e rc=0\n'
              'MCMN_SUBSCRIBE_REPLY_SIZE bytes=7\n')
        result=PROBE.verdict(text,(2,0,0,2,0,2,0))
        # The reply claimed 7 bytes but no payload was logged, so there is no replay to
        # compare: that must not read as a pass.
        self.assertIsNone(result['replay_hex'])
        self.assertFalse(result['replay_matches_sent'])

    def test_missing_publish_is_visible(self):
        result=PROBE.verdict('nothing',(2,0,0,2,0,2,0))
        self.assertFalse(result['published'])
        self.assertFalse(result['subscription_accepted'])


if __name__=='__main__':unittest.main()
