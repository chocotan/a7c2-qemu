import os
import re
import unittest
from unittest.mock import patch

from menu_live import inject_key_tool, key_status_command, shutter_cycle_command


class InjectKeyToolTest(unittest.TestCase):
    def test_legacy_route_is_unchanged(self):
        self.assertEqual(inject_key_tool('0x807a0020', '0x92840747'),
                         '/simulation/inject-key')

    def test_app32_route_uses_app_abi(self):
        self.assertEqual(inject_key_tool('0x005503e0', '0x5503e0', True),
                         '/simulation/inject-key --app')

    def test_app32_rejects_mismatched_queue_or_source(self):
        for queue, source in (('0x807a0020', '0x5503e0'),
                              ('0x5503e0', '0x92840747')):
            with self.subTest(queue=queue, source=source):
                with self.assertRaises(ValueError):
                    inject_key_tool(queue, source, True)

    def test_shutter_cycle_preserves_half_press_until_full_release(self):
        command = shutter_cycle_command()
        records = re.findall(
            r'inject-key --app 0x005503e0 0x005503e0 (0x[0-9a-f]+) 0 ([01]) 0 0',
            command)
        self.assertEqual(records, [('0x1f1', '1'), ('0xa7', '1'),
                                   ('0xa7', '0'), ('0x1f1', '0')])
        self.assertIn('test "$half_pressed" = 0', command)
        self.assertIn('test "$half_released" = 0', command)
        with self.assertRaises(ValueError):
            key_status_command('SHUTTER_HALF', 2, True)

    def test_shutter_hold_is_bounded_and_preserves_order(self):
        with patch.dict(os.environ, {'A7C2_SHUTTER_HOLD_MS': '1000'}):
            command = shutter_cycle_command()
        self.assertEqual(command.count('sleep 1.000'), 2)
        records = re.findall(r'inject-key --app .*? (0x[0-9a-f]+) 0 ([01]) 0 0', command)
        self.assertEqual(records, [('0x1f1', '1'), ('0xa7', '1'),
                                   ('0xa7', '0'), ('0x1f1', '0')])
        for value in ('1', '5001', 'not-a-number'):
            with self.subTest(value=value), patch.dict(os.environ, {'A7C2_SHUTTER_HOLD_MS': value}):
                with self.assertRaises(ValueError):
                    shutter_cycle_command()


if __name__ == '__main__':
    unittest.main()
