#!/usr/bin/env python3
"""Exercise the real shell census over synthetic proc files, without ptrace."""
import os
from pathlib import Path
import runpy
import subprocess
import tempfile
import unittest

HERE = Path(__file__).resolve().parent
api = runpy.run_path(str(HERE / 'run-full-system.py'))
sound_ready = api['sound_config_waiter_ready']


class StackCensus(unittest.TestCase):
    def run_census(self, failure='', critical=True):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            proc = root / 'proc/123'
            (proc / 'task').mkdir(parents=True)
            (proc / 'maps').write_text('synthetic mappings\n')
            (proc / 'mem').touch()
            names = ['other'] * 20
            if critical:
                names += ['AppFw', 'SeqQueueCommon', 'IWrapperImaging', 'IWrapperUPM',
                          'SeqThreadPool0', 'SeqThreadPool1', 'SeqThreadPool2', 'SeqThreadPool3']
            for index, name in enumerate(names, 200):
                task = proc / 'task' / str(index)
                task.mkdir()
                (task / 'comm').write_text(name + '\n')
            helpers = root / 'helpers'
            helpers.mkdir()
            for name, body in {
                'cat': '#!/bin/sh\necho invoked >> "$CAT_COUNT"\nexec /bin/cat "$@"\n',
                'busybox': '#!/bin/sh\nexec "$@"\n',
                'reader': '#!/bin/sh\nexit 0\n',
                'snapshot': '#!/bin/sh\n[ "$1" != "$FAIL_TID" ] || exit 5\necho "REGS tid=$1 seize=1 frozen_frames=1"\n',
            }.items():
                path = helpers / name
                path.write_text(body)
                path.chmod(0o755)
            transport = root / 'transport'
            transport.write_text('tid=221 synthetic transport\n')
            source = (HERE / 'guest/stack-census.sh').read_text()
            source = source.replace('/proc/', str(root / 'proc') + '/')
            source = source.replace('/simulation/menu-readmem', str(helpers / 'reader'))
            source = source.replace('/simulation/thread-snapshot', str(helpers / 'snapshot'))
            source = source.replace('/tmp/menu-load.log', str(transport))
            script = root / 'census.sh'
            script.write_text(source)
            counts = root / 'cat-count'
            result = subprocess.run(['sh', str(script), '123', '0x400000000'], capture_output=True,
                                    text=True, timeout=5, env=dict(os.environ,
                                    PATH=str(helpers) + os.pathsep + os.environ['PATH'],
                                    CAT_COUNT=str(counts), FAIL_TID=failure))
            return result, counts.read_text().splitlines()

    def test_critical_names_do_not_fork_cat(self):
        result, calls = self.run_census()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('count=8 failures=0', result.stdout)
        self.assertEqual(len(calls), 1)  # Maps only; comm uses the shell builtin.
        self.assertEqual(result.stdout.count('frozen_frames=1'), 8)

    def test_one_snapshot_failure_is_not_success(self):
        result, _ = self.run_census(failure='225')
        self.assertEqual(result.returncode, 1)
        self.assertIn('FULLSYSTEM_THREAD_STACK_RC=5 tid=225', result.stdout)
        self.assertIn('count=8 failures=1', result.stdout)

    def test_missing_critical_scope_fails(self):
        result, calls = self.run_census(critical=False)
        self.assertEqual(result.returncode, 1)
        self.assertIn('count=0 failures=1', result.stdout)
        self.assertEqual(len(calls), 1)


class OriginalSoundTrigger(unittest.TestCase):
    query = b'OBS FULL_AUDIO_REQUEST tid=509 source=0x81cf61c2 command=0x33f bytes=8\n'

    def rows(self, count, tid=509):
        return b''.join(('OBS FULL_AUDIO_NATIVE_REPLY_FREE tid=%d sender=%d waiter=1 '
                         'destination=0x81cf61c2 lease=%d command=0x32c bytes=12 rc=0\n' %
                         (tid, tid, i)).encode() for i in range(count))

    def test_25_actual_waiter_frees(self):
        self.assertTrue(sound_ready(self.query + self.rows(25)))

    def test_duplicate_tail_and_other_thread_do_not_trigger(self):
        self.assertFalse(sound_ready(self.query + self.rows(24) * 2))
        self.assertFalse(sound_ready(self.query + self.rows(25, tid=510)))

    def test_failure_and_missing_query_do_not_trigger(self):
        self.assertFalse(sound_ready(self.rows(25)))
        self.assertFalse(sound_ready(self.query + self.rows(25).replace(b'rc=0', b'rc=-1')))

    def test_enabled_capability_and_resolution_waiters_are_required(self):
        console = self.query + self.rows(25)
        ready = api['boot_config_waiters_ready']
        self.assertTrue(ready(console))
        self.assertFalse(ready(console, 'inputless', 'boot'))
        caps = b'OBS FULL_AUDIO_NATIVE_REPLY_FREE tid=510 sender=510 waiter=1 lease=60 command=0x327 bytes=28 rc=0\n'
        hdmi = b'OBS FULL_HDMI_NATIVE_REPLY_FREE tid=511 sender=511 waiter=1 lease=2 command=0x101 bytes=12 status=0 rc=0\n'
        rates = b''.join(('OBS FULL_HDMI_NATIVE_REPLY_FREE tid=511 sender=511 waiter=1 lease=%d command=0x117 bytes=12 status=0 rc=0\n' % i).encode() for i in range(3,8))
        self.assertFalse(ready(console + caps, 'inputless', 'boot'))
        self.assertFalse(ready(console + caps + hdmi, 'inputless', 'boot'))
        self.assertTrue(ready(console + caps + hdmi + rates, 'inputless', 'boot'))
        self.assertFalse(ready(console + caps + hdmi.replace(b'status=0', b'status=1') + rates, 'inputless', 'boot'))
        full = console + caps + hdmi + rates
        self.assertFalse(ready(full, 'inputless', 'boot', 'registry'))
        vef = b'OBS FULL_VEF_NATIVE_REPLY_FREE tid=511 sender=511 waiter=1 lease=1 bytes=56 rc=0\n'
        self.assertTrue(ready(full + vef, 'inputless', 'boot', 'registry'))
        self.assertFalse(ready(full + vef, 'inputless', 'boot', 'registry', 'registry'))
        pinmem = b'OBS FULL_PINMEM_NATIVE_REPLY_FREE tid=511 sender=511 waiter=1 lease=1 bytes=56 rc=0\n'
        self.assertTrue(ready(full + vef + pinmem, 'inputless', 'boot', 'registry', 'registry'))

    def test_pin_capture_waits_for_five_distinct_original_rate_releases(self):
        raw = bytearray(48);raw[24:32]=bytes.fromhex('0010000018000200')
        pin = b'OBS FULL_PIN_REQUEST_OBSERVE tid=511 destination=0x905a0048 source=0x81cf61c1 bytes=48 captured=48 raw='+raw.hex().encode()+b'\n'
        rates = b''.join(('OBS FULL_HDMI_NATIVE_REPLY_FREE tid=511 sender=511 waiter=1 lease=%d command=0x117 bytes=12 status=0 rc=0\n' % i).encode() for i in range(5))
        ready = api['post_rate_pin_request_ready']
        self.assertFalse(ready(pin))
        self.assertTrue(ready(rates + pin))
        self.assertFalse(ready(rates.replace(b'rc=0', b'rc=-1') + pin))
        self.assertFalse(ready(rates + pin.replace(b'tid=511', b'tid=512')))

    def test_peer_capture_requires_source_free_and_actual_peer_tuple(self):
        console = self.query + self.rows(25)
        console += b'OBS FULL_HDMI_NATIVE_REPLY_FREE tid=511 sender=511 waiter=1 lease=2 command=0x101 bytes=12 status=0 rc=0\n'
        console += b''.join(('OBS FULL_HDMI_NATIVE_REPLY_FREE tid=511 sender=511 waiter=1 lease=%d command=0x117 bytes=12 status=0 rc=0\n' % i).encode() for i in range(3,8))
        raw=bytearray(48);raw[24:32]=bytes.fromhex('0010000018000200');raw[32:44]=bytes.fromhex('000000000100000001000000')
        peer=b'OBS FULL_PIN_REQUEST_OBSERVE tid=511 destination=0x90590818 source=0x81cf61c1 bytes=48 captured=48 raw='+raw.hex().encode()+b'\n'
        source=b'OBS FULL_VEF_NATIVE_REPLY_FREE tid=511 sender=511 waiter=1 lease=1 bytes=56 rc=0\n'
        ready=api['pin_peer_request_ready']
        self.assertFalse(ready(console+peer))
        self.assertTrue(ready(console+source+peer))
        self.assertFalse(ready(console+source.replace(b'rc=0',b'rc=-1')+peer))
        self.assertFalse(ready(console+source+peer.replace(b'destination=0x90590818',b'destination=0x9059000e')))


if __name__ == '__main__':
    unittest.main()
