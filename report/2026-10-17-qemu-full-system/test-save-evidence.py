#!/usr/bin/env python3
"""Synthetic host fault fixtures never count as original guest acceptance."""
import hashlib
import json
from pathlib import Path
import runpy
import tempfile
import unittest
from unittest import mock

HERE=Path(__file__).resolve().parent
API=runpy.run_path(str(HERE/'save-evidence.py'))
RUN=runpy.run_path(str(HERE/'run-full-system.py'))


def result():
    return {'state':'failed','error':'config timeout','failure_scope':API['CONFIG_FAILURE'],
            'configuration_save_failed':True,'card_image_exported':True,
            'card_snapshot_integrity_verified':True,'card_flush_lifecycle_verified':True,
            'card_input_producer_stopped_verified':True,'card_input_queue_empty_verified':True,
            'terminal_evidence_checked':True,'card_image_bytes':3,
            'card_chunk_receipts':[{'index':0,'offset':0,'bytes':3,'fnv64':'0'*16,'verified':True}],
            'card_source_identity':'fixture','card_image_sha256':hashlib.sha256(b'abc').hexdigest(),
            'terminal_console_sha256':hashlib.sha256(b'fixture console').hexdigest()}


class ScopedEvidence(unittest.TestCase):
    def test_card_success_never_rewrites_the_session_failure(self):
        source=result();receipt=API['card_receipt'](source)
        self.assertEqual(source['state'],'failed')
        self.assertEqual(receipt['state'],'card-save-completed')
        self.assertEqual(receipt['session_state'],'failed')

    def test_any_unrelated_failure_or_incomplete_card_evidence_is_refused(self):
        for change in [{'failure_scope':'other'},{'state':'cancelled'},{'configuration_save_failed':False},
                       {'terminal_evidence_checked':False},{'terminal_errors':['ownership fault']},
                       {'card_input_queue_empty_verified':False},{'card_chunk_receipts':[]},
                       {'card_flush_lifecycle_verified':False},{'card_image_sha256':'wrong'}]:
            with self.subTest(change=change):
                self.assertIsNone(API['card_receipt']({**result(),**change}))

    def test_receipt_is_bound_to_the_exact_terminal_result(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);raw=json.dumps(result()).encode()
            (root/'result.json').write_bytes(raw)
            receipt=API['card_receipt'](result());receipt['session_result_sha256']=hashlib.sha256(raw).hexdigest()
            (root/'sd-terminal-receipt.json').write_text(json.dumps(receipt))
            self.assertEqual(API['load_card_receipt'](root),receipt)
            (root/'result.json').write_bytes(raw+b' ')
            with self.assertRaisesRegex(ValueError,'differs'):
                API['load_card_receipt'](root)

    def test_real_finalizer_keeps_config_failure_and_publishes_scoped_receipt(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);(root/'console.log').write_bytes(b'fixture console')
            source=result();source['terminal_evidence_checked']=False
            proc=mock.Mock();proc.poll.return_value=0
            RUN['finish_owned_run'](proc,source,root)
            self.assertEqual(source['state'],'failed')
            self.assertEqual(API['load_card_receipt'](root)['session_state'],'failed')


if __name__=='__main__':unittest.main()
