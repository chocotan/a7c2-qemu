from pathlib import Path
import shlex
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from sd_flush_barrier import BarrierError, cancel_resume, quiesce


class SerialStub:
    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = []

    def __call__(self, command, *, timeout, cleanup):
        self.calls.append((command, timeout, cleanup))
        if not self.replies:
            raise AssertionError('unexpected serial call: ' + command)
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply


REPLY = b'SD_FSYS_FLUSH seq=123 pid=1234 drive=65 rc=0\n'
CANCEL = b'SD_CANCEL_seq=123\n'


class HostBarrierTests(unittest.TestCase):
    def test_real_shell_recovery_uses_only_mocked_owner_files_and_signals(self):
        for mode in ('stopped', 'late_stop', 'cancelled', 'cont_failed', 'exited'):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as name:
                root = Path(name)
                (root / 'maps').write_text('/usr/lib/appFw.so\n')
                (root / 'status').write_text('State:\t' + ('T' if mode in ('stopped', 'cont_failed') else 'S') + '\n')
                (root / 'sd-flush.123.reply').write_bytes(REPLY)
                if mode == 'exited':
                    (root / 'maps').unlink()
                calls = []

                def serial(command, *, timeout, cleanup):
                    self.assertIsNone(timeout)
                    self.assertTrue(cleanup)
                    calls.append(command)
                    command = command.replace('/tmp/sd-flush.', str(root / 'sd-flush.'))
                    command = command.replace('/proc/1234/maps', str(root / 'maps'))
                    command = command.replace('/proc/1234/status', str(root / 'status'))
                    command = command.replace('kill -CONT 1234', 'mock_cont')
                    self.assertNotIn('/proc/', command)
                    self.assertNotIn('kill ', command)
                    status = shlex.quote(str(root / 'status'))
                    count = shlex.quote(str(root / 'continued'))
                    ack = shlex.quote(str(root / 'sd-flush.123.cancelled'))
                    cont = 'return 1' if mode == 'cont_failed' else f'echo CONT >> {count}; echo "State: S" > {status}'
                    advance = (f'echo "SD_FSYS_CANCELLED seq=123 pid=1234" > {ack}'
                               if mode == 'cancelled' else f'echo "State: T" > {status}')
                    script = f'mock_cont() {{ {cont}; }}; sleep() {{ {advance}; }}; ' + command
                    return subprocess.run(['/bin/sh', '-c', script], capture_output=True,
                                          timeout=2, check=True).stdout

                if mode in ('cont_failed', 'exited'):
                    with self.assertRaises(BarrierError):
                        cancel_resume(serial, 123)
                else:
                    result = cancel_resume(serial, 123)
                    self.assertEqual(result['status'], 'cancelled' if mode == 'cancelled' else 'resumed')
                    self.assertEqual((root / 'continued').exists(), mode != 'cancelled')
                self.assertTrue((root / 'sd-flush.123.cancel').exists())

    def test_normal_flush_waits_for_actual_stop(self):
        serial = SerialStub([b'SD_REQUEST_seq=123\n', REPLY, b'SD_STATE=S\n',
                             REPLY, b'SD_STATE=T\n'])
        with patch('sd_flush_barrier.time.sleep'):
            self.assertTrue(quiesce(serial, 123)['owner_stopped'])
        self.assertFalse(any(c[2] for c in serial.calls))

    def test_timeout_then_cancel_before_late_reply(self):
        serial = SerialStub([b'SD_REQUEST_seq=123\n', b'SD_FSYS_ABSENT_seq=123\n',
                             CANCEL, b'SD_FSYS_ABSENT_seq=123\n'])
        with self.assertRaises(BarrierError):
            quiesce(serial, 123, timeout=0)
        self.assertEqual(cancel_resume(serial, 123)['status'], 'cancel_armed_no_reply')
        command, timeout, cleanup = serial.calls[2]
        self.assertIn('mv /tmp/sd-flush.123.cancel.new /tmp/sd-flush.123.cancel', command)
        self.assertTrue(cleanup)
        self.assertIsNone(timeout)
        self.assertNotIn('rm ', ' '.join(c[0] for c in serial.calls))

    def test_cancel_after_reply_waits_for_ack_or_actual_stop(self):
        for status in (b'CANCELLED', b'RESUMED'):
            with self.subTest(status=status):
                serial = SerialStub([CANCEL, REPLY, b'SD_RECOVERY=' + status + b'\n'])
                self.assertTrue(cancel_resume(serial, 123)['ok'])
                self.assertTrue(all(timeout is None and cleanup
                                    for _, timeout, cleanup in serial.calls))
                command = serial.calls[-1][0]
                self.assertLess(command.index('T) if ! kill -CONT'), command.index('SD_RECOVERY=RESUMED'))
                self.assertIn('SD_FSYS_CANCELLED seq=123 pid=1234', command)

    def test_original_flush_failure_is_failure(self):
        failed = REPLY.replace(b'rc=0', b'rc=-9')
        serial = SerialStub([b'SD_REQUEST_seq=123\n', failed, CANCEL, failed])
        with self.assertRaisesRegex(BarrierError, 'rc=-9'):
            quiesce(serial, 123)
        self.assertEqual(cancel_resume(serial, 123)['status'], 'flush_failed_no_stop')

    def test_cont_failure_exit_or_console_loss_never_reports_recovered(self):
        for result in (b'SD_RECOVERY=CONT_FAILED\n', b'SD_RECOVERY=OWNER_LOST\n',
                       OSError('console dead'), b'SD_RECOVERY=RESUMED\nSD_RECOVERY=OWNER_LOST\n'):
            with self.subTest(result=result):
                serial = SerialStub([CANCEL, REPLY, result])
                with self.assertRaises((BarrierError, OSError)):
                    cancel_resume(serial, 123)

    def test_reply_storage_or_cancel_publication_failures(self):
        for invalid in (b'', b'SD_FSYS_FLUSH seq=122 pid=1234 drive=65 rc=0\n',
                        REPLY + REPLY, REPLY.replace(b'1234', b'1')):
            serial = SerialStub([CANCEL, invalid])
            with self.subTest(invalid=invalid), self.assertRaises(BarrierError):
                cancel_resume(serial, 123)
        serial = SerialStub([b'mv failed\n'])
        with self.assertRaises(BarrierError):
            cancel_resume(serial, 123)
        self.assertEqual(len(serial.calls), 1)

    def test_new_sequence_never_removes_old_cancel(self):
        serial = SerialStub([CANCEL, b'SD_FSYS_ABSENT_seq=123\n',
                             b'SD_CANCEL_seq=124\n', b'SD_FSYS_ABSENT_seq=124\n'])
        cancel_resume(serial, 123)
        cancel_resume(serial, 124)
        self.assertNotIn('rm ', ' '.join(c[0] for c in serial.calls))

    def test_untrusted_sequences_rejected_without_serial(self):
        for seq in (True, 0, -1, 2**64, '123; kill -STOP 1'):
            with self.subTest(seq=seq), self.assertRaises(ValueError):
                cancel_resume(SerialStub([]), seq)


if __name__ == '__main__':
    unittest.main()
