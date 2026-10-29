"""Regress address-domain, length and immutable-input mistakes in the report tool."""
import hashlib

import pytest

from verify_boot_backup import ROOT, public_layout, read_pinned, reset_projection
from verify_public_seed import verify as verify_seed


def test_public_projection_preserves_high_bits_and_data_lengths():
    result = public_layout(ROOT / 'seed-backup.bin')
    assert result['ap_next_record'] == '0x4040ed000'
    assert result['pci_primary_target_before_context_bias'] == '0x804000000'
    assert result['pci_secondary_target_before_context_bias'] == '0x80415b000'
    assert result['root_data_bytes'] == 0xec915
    assert result['root_padded_span'] == 0xed000
    assert result['next_record_data_bytes'] == 0x15a8f8
    assert result['raw_second_record_is_final_boot_content_verified'] is False
    resets = result['reset_projection']
    assert all(r['unchanged_by_reset'] and r['compared_items'] > 0 for r in resets)
    assert all(r['version_values'] == ['00000000', '00000000'] for r in resets)
    assert resets[1]['repeated_items'] == 2 and resets[1]['repeat_count'] == 13


def test_reset_projection_detects_changed_repeated_copy():
    seed = ROOT / 'seed-backup.bin'
    public = verify_seed(seed, keys=(0x000300ab,))['records'][1]
    item = public['keys']['000300ab']
    data = bytearray(seed.read_bytes()[0xed000:])
    assert item['attr'] & 0x80 and item['bytes'] % 13 == 0
    data[item['file_offset'] - 0xed000 + item['bytes'] // 13] ^= 1
    result = reset_projection(data, 13)
    assert result['unchanged_by_reset'] is False
    assert result['changed_keys'] == ['000300ab']


def test_reset_projection_rejects_truncated_record():
    data = (ROOT / 'seed-backup.bin').read_bytes()[0xed000:]
    with pytest.raises(ValueError, match='record length mismatch'):
        reset_projection(data[:-1], 13)


def test_default_seed_report_keeps_its_existing_keys():
    records = verify_seed(ROOT / 'seed-backup.bin')['records']
    assert all(set(record['keys']) == {'0051001d', '003100a6', '02a40000', '02a4000e'}
               for record in records)


def test_modified_or_truncated_seed_is_not_accepted(tmp_path):
    source = bytearray((ROOT / 'seed-backup.bin').read_bytes())
    source[0xed000 + 9] ^= 1
    path = tmp_path / 'changed.bin'
    path.write_bytes(source)
    with pytest.raises(ValueError, match='immutable official ALLLANG'):
        public_layout(path)
    path.write_bytes(source[:0xed000])
    with pytest.raises(ValueError, match='immutable official ALLLANG'):
        public_layout(path)


def test_asset_reader_rejects_truncation_and_trailing_bytes(tmp_path):
    data = b'bounded original-byte test'
    path = tmp_path / 'asset.bin'
    digest = hashlib.sha256(data).hexdigest()
    path.write_bytes(data)
    assert read_pinned(path, len(data), digest) == data
    for altered in (data[:-1], data + b'\0', data[:-1] + b'!'):
        path.write_bytes(altered)
        with pytest.raises(ValueError, match='unsupported original asset'):
            read_pinned(path, len(data), digest)
