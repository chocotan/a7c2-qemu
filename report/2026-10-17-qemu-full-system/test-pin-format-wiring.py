#!/usr/bin/env python3
import runpy
import subprocess
import sys
from pathlib import Path
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
READY = runpy.run_path(str(HERE / 'run-full-system.py'))['pin_format_consumed_ready']


class ColdFormatWiring(unittest.TestCase):
    def test_incomplete_profile_rejected_before_runtime_lock(self):
        result = subprocess.run([sys.executable, '-B', str(HERE / 'run-full-system.py'), '--pin-format', 'cold'], capture_output=True, text=True)
        self.assertEqual(result.returncode, 2)
        self.assertIn('requires --pin-connection control', result.stderr)

    def test_inherited_format_environment_cleared(self):
        source = (HERE / 'guest/bootin-wrapper').read_text()
        self.assertLess(source.index('unset FULLSYSTEM_PIN_FORMAT'), source.index('/simulation/seed-power-on'))
        subprocess.run(['bash', '-n', str(HERE / 'guest/bootin-wrapper')], check=True)

    def test_stop_requires_post_format_same_waiter_same_lease_free(self):
        commit = b'OBS FULL_PIN_FORMAT_COMMIT tid=55 handle=0x8000 live=0 buffer_released=1 format_cpu_consumed=1 \n'
        native = b'OBS FULL_PIN_CONNECT_NATIVE_REPLY_FREE tid=55 sender=55 waiter=1 bytes=56 command=0x8001 rc=0\n'
        get = b'OBS FULL_PINMEM_COMMIT tid=55 slot=4 type=0 dir=2 index=1 pin_state=1 owner=0x90590818 status=0 queries=2 reply=0x123 lease=2 request_free_rc=0 \n'
        free = b'OBS FULL_PINMEM_NATIVE_REPLY_FREE tid=55 sender=55 waiter=1 reply=0x123 lease=2 bytes=56 rc=0\n'
        with patch.dict(READY.__globals__, {'boot_config_waiters_ready': lambda *args: True}):
            self.assertTrue(READY(commit + native + get + free))
            self.assertFalse(READY(commit + native + get))
            self.assertFalse(READY(commit + native + get + free.replace(b'lease=2', b'lease=3')))
            self.assertFalse(READY(commit + native + get + free.replace(b'tid=55', b'tid=56')))
            self.assertFalse(READY(native + commit + get + free))


if __name__ == '__main__':
    unittest.main()
