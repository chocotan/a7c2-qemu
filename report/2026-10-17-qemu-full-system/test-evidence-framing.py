#!/usr/bin/env python3
"""Audio record framing only; component schemas still validate every field."""
from pathlib import Path
import runpy
import unittest

HERE = Path(__file__).resolve().parent
lines = runpy.run_path(str(HERE / 'verify-system-sound-config.py'))['observer_lines']


class EvidenceFraming(unittest.TestCase):
    def test_exact_marker_recovers_only_echo_prefix(self):
        first = 'OBS FULL_AUDIO_NATIVE_REPLY_FREE tid=511 lease=17 command=0x32c bytes=12 rc=0'
        second = 'OBS FULL_AUDIO_REQUEST tid=511 command=0x329 bytes=40 raw=0d20'
        raw = ('cat /proc/module' + first + '\ns' + second + '\n').encode()
        observed, recovered = lines(raw)
        self.assertEqual(observed, [first, second])
        self.assertEqual(recovered, 2)
        self.assertTrue(raw.startswith(b'cat /proc/module'))

    def test_unclear_multiple_events_are_rejected(self):
        with self.assertRaisesRegex(ValueError, 'Ambiguous'):
            lines(b'OBS FULL_AUDIO_REQUEST tid=1 OBS FULL_AUDIO_COMMIT tid=1\n')

    def test_no_partial_marker_or_payload_repair(self):
        raw = b'prefix OBS FULL_AUDIO_REQUEST\nOBS FULL_AUDIO_REQUEST tid=1 raw=nothex\n'
        observed, recovered = lines(raw)
        self.assertEqual(recovered, 0)
        self.assertEqual(observed, raw.decode().splitlines())


if __name__ == '__main__':
    unittest.main()
