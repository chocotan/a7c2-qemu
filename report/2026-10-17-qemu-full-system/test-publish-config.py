#!/usr/bin/env python3
"""The verdict must bind the current source bytes before any publication."""
import hashlib
from pathlib import Path
import runpy
import tempfile
import unittest
from unittest import mock

HERE = Path(__file__).resolve().parent
PUBLISH = runpy.run_path(str(HERE / 'publish-config.py'))


class ExportBinding(unittest.TestCase):
    def pair(self):
        root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        items = []
        for name, data in [('Backup.bin', b'one'), ('Backup.bak', b'two')]:
            (root / name).write_bytes(data)
            items.append({'name': name, 'valid': True, 'bytes': len(data),
                          'sha256': hashlib.sha256(data).hexdigest()})
        return root, {'export_verified': True, 'files': items}

    def test_stale_success_does_not_authorise_changed_source(self):
        root, verdict = self.pair()
        (root / 'Backup.bin').write_bytes(b'bad')
        validate = mock.Mock()
        with mock.patch.dict(PUBLISH['BACKUP'], {'FILE_BYTES': 3, 'validate': validate}):
            with self.assertRaisesRegex(ValueError, 'no longer match'):
                PUBLISH['verified_pair'](root, verdict, b'reference')
        validate.assert_not_called()

    def test_both_snapshots_are_validated_and_remain_fixed_after_source_changes(self):
        root, verdict = self.pair()
        validate = mock.Mock()
        with mock.patch.dict(PUBLISH['BACKUP'], {'FILE_BYTES': 3, 'validate': validate}):
            pair = PUBLISH['verified_pair'](root, verdict, b'reference')
        self.assertEqual(validate.call_args_list, [mock.call(b'one', b'reference'), mock.call(b'two', b'reference')])
        (root / 'Backup.bin').write_bytes(b'bad')
        self.assertEqual(pair, {'BACKUP.BIN': b'one', 'BACKUP.BAK': b'two'})

    def test_valid_digest_does_not_skip_bk4_revalidation(self):
        root, verdict = self.pair()
        with mock.patch.dict(PUBLISH['BACKUP'], {'FILE_BYTES': 3}):
            with self.assertRaisesRegex(ValueError, 'Reference must be the verified official'):
                PUBLISH['verified_pair'](root, verdict, b'not official PP')

    def test_missing_duplicate_or_invalid_evidence_is_refused(self):
        root, verdict = self.pair()
        for items in [verdict['files'][:1], [verdict['files'][0]] * 2]:
            with self.assertRaisesRegex(ValueError, 'exactly the verified'):
                PUBLISH['verified_pair'](root, {'export_verified': True, 'files': items}, b'PP')
        verdict['files'][0]['valid'] = False
        with mock.patch.dict(PUBLISH['BACKUP'], {'FILE_BYTES': 3}):
            with self.assertRaisesRegex(ValueError, 'no longer match'):
                PUBLISH['verified_pair'](root, verdict, b'PP')

    def test_symlink_and_wrong_length_are_not_read_as_backup(self):
        root, verdict = self.pair()
        (root / 'Backup.bin').unlink()
        (root / 'Backup.bin').symlink_to(root / 'Backup.bak')
        with mock.patch.dict(PUBLISH['BACKUP'], {'FILE_BYTES': 3}):
            with self.assertRaises(OSError):
                PUBLISH['verified_pair'](root, verdict, b'PP')
        (root / 'Backup.bin').unlink()
        (root / 'Backup.bin').write_bytes(b'')
        with self.assertRaisesRegex(ValueError, 'type/size'):
            PUBLISH['verified_pair'](root, verdict, b'PP')


if __name__ == '__main__':
    unittest.main()
