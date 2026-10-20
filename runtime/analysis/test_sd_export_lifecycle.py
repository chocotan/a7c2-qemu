import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from sd_export_lifecycle import export_with_flush_lifecycle
from test_sd_flush_barrier import CANCEL, REPLY, SerialStub


class IntegrationTests(unittest.TestCase):
    def test_all_export_paths_cancel_and_replace_old_success_report(self):
        for mode in ('success', 'quiesce_error', 'export_error', 'returned_failure', 'resume_error'):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as name:
                path = Path(name) / 'export.json'
                path.write_text('{"ok":true,"stale":true}\n')
                serial = SerialStub([CANCEL, REPLY,
                                     b'SD_RECOVERY=CONT_FAILED\n' if mode == 'resume_error'
                                     else b'SD_RECOVERY=RESUMED\n'])

                def export_once(barrier):
                    barrier()
                    if mode == 'export_error':
                        raise RuntimeError('download failed')
                    if mode == 'returned_failure':
                        return dict(ok=False, error='fsck failed')
                    result = dict(ok=True, sha256='verified-data-digest')
                    path.write_text(json.dumps(result))
                    return result

                def publish(result):
                    new = path.with_suffix('.new')
                    new.write_text(json.dumps(result))
                    new.replace(path)

                with patch('sd_export_lifecycle.quiesce',
                           side_effect=RuntimeError('flush timeout') if mode == 'quiesce_error' else None):
                    result = export_with_flush_lifecycle(export_once, serial, 123, publish)
                saved = json.loads(path.read_text())
                self.assertEqual(saved, result)
                self.assertEqual(saved['ok'], mode == 'success')
                self.assertNotIn('stale', saved)
                self.assertEqual(len(serial.calls), 3)
                if mode == 'resume_error':
                    self.assertTrue(saved['export_data_ok'])
                    self.assertFalse(saved['flush_lifecycle']['ok'])
                    self.assertIn('CONT_FAILED', saved['error'])

    def test_publication_failure_never_returns_success(self):
        serial = SerialStub([CANCEL, REPLY, b'SD_RECOVERY=RESUMED\n'])
        def failed_publish(result):
            self.assertTrue(result['ok'])
            raise OSError('evidence storage failed')
        with self.assertRaisesRegex(OSError, 'storage failed'):
            export_with_flush_lifecycle(lambda _: dict(ok=True), serial, 123, failed_publish)


if __name__ == '__main__':
    unittest.main()
