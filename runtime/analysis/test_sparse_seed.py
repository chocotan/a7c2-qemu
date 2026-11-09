"""Host-only lossless sparse-seed tests; no block device or VM."""
import hashlib
import json
import os
from pathlib import Path

import pytest

import sparse_seed


def file_sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def test_one_gib_seed_preserves_nonzero_boundaries_and_full_sha(tmp_path):
    source = tmp_path/'source.img'
    with source.open('xb') as stream:
        stream.truncate(sparse_seed.TOTAL)
    values = {0: 1, 4095: 2, 4096: 3, 4*1024**2: 4,
              sparse_seed.TOTAL-4096: 5, sparse_seed.TOTAL-1: 6}
    with source.open('r+b') as stream:
        for offset, value in values.items():
            stream.seek(offset)
            stream.write(bytes([value]))
    expected = file_sha(source)
    result = sparse_seed.build(source, tmp_path/'seed')
    assert result['bytes'] == 1024**3 and result['sha256'] == expected
    assert result['data_bytes'] <= 5 * 4096
    assert result['data_bytes'] < 1024**2
    manifest = json.loads((tmp_path/'seed/manifest.json').read_text())
    assert manifest == result and manifest['representation_only'] is True
    for row in result['chunks']:
        raw = (tmp_path/'seed'/row['file']).read_bytes()
        assert len(raw) == row['length'] and hashlib.sha256(raw).hexdigest() == row['sha256']
        assert row['offset'] % 4096 == row['length'] % 4096 == 0
    for offset, value in values.items():
        row = next(row for row in result['chunks'] if row['offset'] <= offset < row['offset']+row['length'])
        raw = (tmp_path/'seed'/row['file']).read_bytes()
        assert raw[offset-row['offset']] == value
    lines = (tmp_path/'seed/chunks.txt').read_text().splitlines()
    assert len(lines) == len(result['chunks'])


def test_seed_rejects_wrong_size_and_symlink_without_overwrite(tmp_path):
    source = tmp_path/'source.img'
    with source.open('xb') as stream:
        stream.truncate(sparse_seed.TOTAL-4096)
    with pytest.raises(ValueError, match='exactly 1 GiB'):
        sparse_seed.build(source, tmp_path/'wrong-size')
    assert (tmp_path/'wrong-size').exists()  # Preserve the rejected partial output.
    with source.open('ab') as stream:
        stream.truncate(sparse_seed.TOTAL)
    link = tmp_path/'linked.img'
    link.symlink_to(source)
    with pytest.raises((ValueError, OSError)):
        sparse_seed.build(link, tmp_path/'linked')
    with pytest.raises(ValueError, match='fresh'):
        sparse_seed.build(source, tmp_path/'wrong-size')
