#!/usr/bin/env python3
"""A completed card snapshot is separate from the overall session outcome."""
import hashlib
import json
from pathlib import Path
import re

SCHEMA = 'sd-terminal-receipt-v1'
CONFIG_FAILURE = 'configuration-after-card-save'
CHUNK = 4 * 1024**2


def card_receipt(result):
    flags = ('card_image_exported', 'card_snapshot_integrity_verified',
             'card_flush_lifecycle_verified', 'card_input_producer_stopped_verified',
             'card_input_queue_empty_verified', 'terminal_evidence_checked')
    if not all(result.get(name) is True for name in flags):
        return None
    if result.get('terminal_errors') or result.get('original_model_fatal_observed'):
        return None
    state = result.get('state')
    if state != 'observation-completed' and not (
            state == 'failed' and result.get('failure_scope') == CONFIG_FAILURE
            and result.get('configuration_save_failed') is True):
        return None
    size = result.get('card_image_bytes')
    chunks = result.get('card_chunk_receipts', [])
    if type(size) is not int or size <= 0 or len(chunks) != (size + CHUNK - 1) // CHUNK:
        return None
    for i, chunk in enumerate(chunks):
        if (chunk.get('index') != i or chunk.get('offset') != i * CHUNK
                or chunk.get('bytes') != min(CHUNK, size - i * CHUNK)
                or chunk.get('verified') is not True
                or re.fullmatch(r'[0-9a-f]{16}', str(chunk.get('fnv64'))) is None):
            return None
    for name in ('card_image_sha256', 'terminal_console_sha256'):
        if re.fullmatch(r'[0-9a-f]{64}', str(result.get(name))) is None:
            return None
    if not result.get('card_source_identity'):
        return None
    return {'schema': SCHEMA, 'scope': 'original card flush/snapshot/recovery only',
            'state': 'card-save-completed', 'session_state': state,
            'session_error': result.get('error'), 'failure_scope': result.get('failure_scope'),
            **{name: result[name] for name in flags},
            **{name: result[name] for name in ('card_image_bytes', 'card_image_sha256',
                                              'card_chunk_receipts', 'card_source_identity',
                                              'terminal_console_sha256')}}


def load_card_receipt(run):
    run = Path(run)
    raw = (run / 'result.json').read_bytes()
    receipt = json.loads((run / 'sd-terminal-receipt.json').read_bytes())
    expected = card_receipt(json.loads(raw))
    if expected is None:
        raise ValueError('card terminal evidence is incomplete')
    expected['session_result_sha256'] = hashlib.sha256(raw).hexdigest()
    if receipt != expected:
        raise ValueError('card receipt differs from its terminal session result')
    return receipt
