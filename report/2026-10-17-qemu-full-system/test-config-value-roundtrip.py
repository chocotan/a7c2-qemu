#!/usr/bin/env python3
"""Harness transport and frame checks, not substitutes for a real camera UI run."""
import hashlib
from pathlib import Path
import runpy
import tempfile
import unittest
from unittest import mock
from PIL import Image

HERE = Path(__file__).resolve().parent
CHECK = runpy.run_path(str(HERE / 'check-config-value-roundtrip.py'))
Session = CHECK['Session']


def receipt(code=0x1ac, states=(1, 0), rc=0, end=None):
    nonce = b'1234567890abcdef12345678'
    lines = [f'INJECT_KEY_SEND queue=0x807a0020 src=0x92840747 key_code={code:#x} '
             f'sub=0 status={state:#x} ex=0 from=0x1 result=0'.encode() for state in states]
    lines.extend([b'MENU_DIAG_COMMAND_DONE_' + nonce + b':' + str(rc).encode()
                  + b':END_' + (end or nonce)] * 3)
    return b'\r\n'.join(lines) + b'\r\n'


class InputReceipts(unittest.TestCase):
    def test_actual_requested_pulse_and_closed_zero_receipt(self):
        CHECK['injection_receipt'](receipt(), 0x1ac)

    def test_wrong_key_release_missing_or_failed_command_is_rejected(self):
        for raw in (receipt(code=0x30), receipt(states=(1,)), receipt(states=(0, 1)),
                    receipt(rc=1), receipt(end=b'a' * 24), b'other command result=0'):
            with self.subTest(raw=raw), self.assertRaises(RuntimeError):
                CHECK['injection_receipt'](raw, 0x1ac)

    def test_conflicting_nonce_receipts_are_rejected(self):
        with self.assertRaisesRegex(RuntimeError, 'conflicting'):
            CHECK['injection_receipt'](receipt() + receipt().replace(b'1234567890abcdef12345678', b'a' * 24), 0x1ac)

    def test_press_waits_for_its_exact_response_and_does_not_accept_another_command(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            session = Session(root, root, {}, 'fixture')
            session.queue = root
            session.prefix = 'unique-fixture'
            session.proc = mock.Mock()
            session.proc.poll.return_value = None
            (root / 'unrelated.out').write_bytes(receipt(code=0x30))
            def respond(_):
                commands = list(root.glob('*.cmd'))
                self.assertEqual(len(commands), 1)
                self.assertTrue(commands[0].read_text().endswith('--pulse-ms 50'))
                self.assertFalse(list(root.glob('*.next')))
                (root / 'unique-fixture-000.out').write_bytes(receipt())
            with mock.patch.object(CHECK['time'], 'sleep', side_effect=respond):
                session.press('ENTER', settle=0)
            self.assertEqual(session.request, 1)
            self.assertEqual(len(list(root.glob('*.cmd'))), 1)  # No separate unacknowledged release.
            self.assertTrue((root / 'fixture-input-001.out').exists())


class FrameAndLifecycle(unittest.TestCase):
    def test_frame_snapshot_is_decodable_and_deduplicates_content(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            session = Session(root, root, {}, 'fixture')
            session.run = root
            live = root / 'live-frame.ppm'
            live.write_bytes(b'P6\n640 480\n255\n\0')
            self.assertIsNone(session.frame())
            Image.new('RGB', (640, 480), (0, 100, 30)).save(live)
            first = session.frame()
            self.assertEqual(first, session.frame())
            self.assertEqual(len(session.saved_frames), 1)
            self.assertEqual(first.read_bytes(), live.read_bytes())
            live.write_bytes(b'partial next frame')
            self.assertIsNone(session.frame())
            self.assertTrue(first.exists())

    def test_unstable_frame_does_not_reuse_a_stale_screen_observation(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            session = Session(root, root, {}, 'fixture')
            session.run = root
            session.last_observation = {'screen': 'area_datetime_prompt', 'frame': 'old'}
            self.assertEqual(session.screen(), (None, None))
            self.assertIsNone(session.last_observation)

    def test_unknown_boot_frame_does_not_receive_an_enter_before_a_known_prompt(self):
        session = mock.Mock()
        session.screen.side_effect = [(None, None), ('language', 0), ('shooting', 0)]
        session.last_observation = None
        with mock.patch.object(CHECK['time'], 'sleep'):
            CHECK['drive_first_setup'](session, {})
        session.press.assert_called_once_with('ENTER')

    def test_cleanup_ignores_an_already_reaped_launcher(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            session = Session(root, root, {}, 'fixture')
            session.proc = mock.Mock()
            session.proc.poll.return_value = 0
            with mock.patch.dict(Session.cleanup.__globals__, {'os': mock.Mock()}) as _:
                self.assertEqual(session.cleanup(), {'already_exited': True})


if __name__ == '__main__':
    unittest.main()
