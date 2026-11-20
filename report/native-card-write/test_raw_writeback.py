import hashlib
from pathlib import Path
import types

import pytest

HERE = Path(__file__).resolve().parent
raw = types.ModuleType('test_raw_card_writeback')
raw.__file__ = str(HERE / 'check_raw_writeback.py')
exec(compile(Path(raw.__file__).read_bytes(), raw.__file__, 'exec'), raw.__dict__)


def proof(sequence, sha, evidence, old=None):
    return dict(ok=True, card_published=True, expected_total=1024**3, fsck_rc=0,
                sha256=sha, evidence='export-'+evidence*32, sequence=sequence,
                expected_old_sha256=old,
                chunks=[dict(offset=i*raw.sd.CAP, len=raw.sd.CAP, qmp={'return': {}},
                             guest_fnv64='0'*16, actual_fnv64='0'*16) for i in range(256)],
                quiesce=dict(owner_stopped=True, original_Fsys_FlushVolume_rc=0,
                              sequence=sequence, pid=123, drive=65),
                flush_lifecycle=dict(ok=True, resumed=True, status='resumed',
                                     sequence=sequence, pid=123))


def test_two_proofs_require_chronology_and_matching_publication(monkeypatch, tmp_path):
    first = proof(10, '1'*64, 'a')
    second = proof(20, '2'*64, 'b', first['sha256'])
    rows = {'SD/capture-export-00000000000000000010.json': first,
            'SD/capture-export-00000000000000000020.json': second,
            'SD/export.json': second}
    monkeypatch.setattr(raw.wb, 'load_json', lambda _run, path: rows[path])
    assert raw.read_export_pair(tmp_path, 10, 20) == (first, second)
    with pytest.raises(ValueError, match='increasing'):
        raw.read_export_pair(tmp_path, 20, 10)
    second['expected_old_sha256'] = '3'*64
    with pytest.raises(ValueError, match='bind'):
        raw.read_export_pair(tmp_path, 10, 20)
    second['expected_old_sha256'] = first['sha256']
    rows['SD/export.json'] = first
    with pytest.raises(ValueError, match='latest'):
        raw.read_export_pair(tmp_path, 10, 20)


def test_raw_fsck_requires_readable_original_summary(tmp_path):
    directory = tmp_path/'SD'/'export-1'
    directory.mkdir(parents=True)
    evidence = directory/'fsck.txt'
    content = b'fsck.fat 4.2\ncard: 1 files, 2/1024 clusters\n'
    evidence.write_bytes(content)
    row = {'evidence':'export-1'}
    assert raw.check_fsck(tmp_path, row) == hashlib.sha256(content).hexdigest()
    evidence.write_bytes(b'fsck failed\n')
    with pytest.raises(ValueError, match='fsck evidence'):
        raw.check_fsck(tmp_path, row)


def test_writeback_never_claims_capture_and_rejects_card_disagreement(monkeypatch, tmp_path):
    (tmp_path/'SD').mkdir(mode=0o700)
    first = proof(10, '1'*64, 'a')
    second = proof(20, '2'*64, 'b', first['sha256'])
    monkeypatch.setattr(raw, 'read_export_pair', lambda *_args: (first, second))
    monkeypatch.setattr(raw, 'check_fsck', lambda *_args: 'c'*64)
    data = b'bounded media evidence'
    record = {'pid': 123, 'token': 1, 'path': 'DCIM/100MSDCF/DSC00001.JPG',
              'native_readbacks': [{'fnv1a64': raw.fnv(data)}]}
    monkeypatch.setattr(raw.wb, 'parse_trace', lambda _run: ([record], 'a'*64, [{'pid': '123'}]))
    ranges = [dict(offset=0, bytes=len(data), fnv1a64=raw.fnv(data))]
    monkeypatch.setattr(raw.wb, 'lifecycle', lambda *_args: (ranges, len(data), True))
    monkeypatch.setattr(raw.wb, 'decode', lambda *_args, **_kwargs: {'decoded': True})
    def card(_run, relative, _sha, _wanted):
        return {record['path']: data}, {'inode': 1 if 'previous-card' in relative else 2, 'device': 1}
    monkeypatch.setattr(raw, 'read_card', card)
    result = raw.inspect(tmp_path, 10, 20)
    assert result['writeback_verified'] and result['independent_decoded']
    assert result['capture_verified'] is False
    monkeypatch.setattr(raw, 'read_card', lambda _run, relative, _sha, _wanted:
                        ({record['path']: data if 'previous-card' in relative else b'changed'},
                         {'inode': 1 if 'previous-card' in relative else 2, 'device': 1}))
    result = raw.inspect(tmp_path, 10, 20)
    assert not result['writeback_verified'] and 'differ' in result['error']


@pytest.fixture
def jpeg_raw_replay(monkeypatch, tmp_path):
    """HOST_TEST parser replay only; no card image or native capture is manufactured."""
    first = proof(10, '1'*64, 'a')
    second = proof(20, '2'*64, 'b', first['sha256'])
    data = b'HOST_TEST bounded JPEG content'
    record = dict(pid=123, token=1, path='DCIM/100MSDCF/DSC00001.JPG',
                  native_readbacks=[dict(fnv1a64=raw.fnv(data), line=9)])
    ranges = [dict(offset=0, bytes=len(data), fnv1a64=raw.fnv(data))]
    monkeypatch.setattr(raw, 'read_export_pair', lambda *_args: (first, second))
    monkeypatch.setattr(raw, 'check_fsck', lambda *_args: 'c'*64)
    monkeypatch.setattr(raw.wb, 'parse_trace', lambda _run: ([record], 'a'*64, [{'pid': '123'}]))
    monkeypatch.setattr(raw.wb, 'lifecycle', lambda *_args: (ranges, len(data), True))
    monkeypatch.setattr(raw.wb, 'decode', lambda *_args:
                        dict(format='JPEG', decoded=True, frame_count=1, width=16, height=16))
    def card(_run, relative, export_proof, _wanted):
        return {record['path']: data}, dict(path=relative, bytes=raw.CARD_BYTES, sha256=export_proof['sha256'],
            inode=1 if 'previous-card' in relative else 2, device=1)
    monkeypatch.setattr(raw, 'read_card', card)
    return tmp_path, record, first, second, data


def test_explicit_jpeg_raw_items_preserve_native_identity_and_never_claim_capture(jpeg_raw_replay):
    run, record, _, _, data = jpeg_raw_replay
    result = raw.inspect(run, 10, 20, jpeg_only=True)
    assert result['writeback_verified'] and result['independent_decoded']
    item = result['items'][0]
    assert item['pid'] == 123 and item['token'] == 1 and item['drive'] == 'A'
    assert item['areas'] and item['native_readbacks'] == record['native_readbacks']
    assert item['decode']['format'] == 'JPEG' and item['writeback_verified']
    assert result['capture_verified'] is False and item['capture_verified'] is False
    assert raw.stored_media_bytes(run, result, item) == data
    assert raw.check_unchanged(run, result)['verified']


def test_jpeg_raw_requires_independent_single_jpeg_decode(jpeg_raw_replay, monkeypatch):
    run = jpeg_raw_replay[0]
    monkeypatch.setattr(raw.wb, 'decode', lambda *_args: dict(decoded=True, format='MP4', frame_count=2))
    result = raw.inspect(run, 10, 20, jpeg_only=True)
    assert not result['writeback_verified'] and 'single JPEG' in result['error']
    result = raw.inspect(run, 10, 20, 'M4ROOT/CLIP/C0001.MP4', jpeg_only=True)
    assert not result['writeback_verified'] and 'cannot select' in result['error']


def test_raw_join_rechecks_both_images_and_complete_export_proofs(jpeg_raw_replay, monkeypatch):
    run, _, first, second, _ = jpeg_raw_replay
    result = raw.inspect(run, 10, 20, jpeg_only=True)
    original = raw.read_card
    def changed(_run, relative, digest, wanted):
        files, identity = original(_run, relative, digest, wanted)
        if 'previous-card' in relative:
            identity['inode'] = 77
        return files, identity
    monkeypatch.setattr(raw, 'read_card', changed)
    with pytest.raises(ValueError, match='identity changed'):
        raw.check_unchanged(run, result)
    monkeypatch.setattr(raw, 'read_card', original)
    second['chunks'][0]['guest_fnv64'] = second['chunks'][0]['actual_fnv64'] = '1'*16
    with pytest.raises(ValueError, match='proof changed'):
        raw.check_unchanged(run, result)


def test_all_raw_readback_consumers_preserve_full_window_proofs(jpeg_raw_replay, monkeypatch):
    run, _, first, second, _ = jpeg_raw_replay
    original = raw.read_card
    seen = []
    def observe(_run, relative, export_proof, wanted):
        assert export_proof is first or export_proof is second
        assert 'chunks' in export_proof
        seen.append(export_proof)
        return original(_run, relative, export_proof, wanted)
    monkeypatch.setattr(raw, 'read_card', observe)
    result = raw.inspect(run, 10, 20, jpeg_only=True)
    assert result['writeback_verified']
    raw.stored_media_bytes(run, result, result['items'][0])
    raw.check_unchanged(run, result)
    assert seen == [first, second, second, first, second]


def test_raw_content_join_rejects_same_bytes_from_replaced_card(jpeg_raw_replay, monkeypatch):
    run = jpeg_raw_replay[0]
    result = raw.inspect(run, 10, 20, jpeg_only=True)
    original = raw.read_card
    def replaced(*args):
        files, identity = original(*args)
        identity['inode'] += 100
        return files, identity
    monkeypatch.setattr(raw, 'read_card', replaced)
    with pytest.raises(ValueError, match='identity'):
        raw.stored_media_bytes(run, result, result['items'][0])


def test_raw_jpeg_mode_rejects_missing_or_multiple_native_writes(jpeg_raw_replay, monkeypatch):
    run, record, _, _, _ = jpeg_raw_replay
    other = dict(record, token=2, path='DCIM/100MSDCF/DSC00002.JPG')
    monkeypatch.setattr(raw.wb, 'parse_trace', lambda _run: ([record, other], 'a'*64, [{'pid': '123'}]))
    result = raw.inspect(run, 10, 20, jpeg_only=True)
    assert not result['writeback_verified'] and 'one unambiguous' in result['error']
    monkeypatch.setattr(raw.wb, 'parse_trace', lambda _run: ([], 'a'*64, [{'pid': '123'}]))
    result = raw.inspect(run, 10, 20, jpeg_only=True)
    assert not result['writeback_verified'] and 'no selected' in result['error']


@pytest.fixture
def actual_window_card(monkeypatch, tmp_path):
    """HOST_TEST real bytes, with only card size/schema/FAT walking substituted."""
    data = bytes(range(96))
    path = tmp_path / 'card.img'
    path.write_bytes(data)
    monkeypatch.setattr(raw, 'CARD_BYTES', len(data))
    chunks = [dict(offset=offset, len=32, guest_fnv64=raw.fnv(data[offset:offset + 32]),
                   actual_fnv64=raw.fnv(data[offset:offset + 32]), qmp={'return': {}})
              for offset in range(0, len(data), 32)]
    export_proof = dict(sha256=hashlib.sha256(data).hexdigest(), chunks=chunks)
    # The production 1GiB proof schema is exercised by read_export_pair tests above.
    monkeypatch.setattr(raw.sd, 'validate_capture_export_proof', lambda _row: None)
    class Fat:
        lfn_skipped = 0
        def __init__(self, *_args, **_kwargs):
            pass
        def walk(self):
            pass
    monkeypatch.setattr(raw.wb._reader, 'Fat16', Fat)
    return tmp_path, path, data, export_proof


@pytest.mark.parametrize('index', [0, 1, 2])
def test_actual_card_rejects_both_window_fnvs_forged_together(actual_window_card, index, monkeypatch):
    run, path, data, export_proof = actual_window_card
    observed = []
    original_fnv = raw.fnv
    def observe(window):
        observed.append(window)
        return original_fnv(window)
    monkeypatch.setattr(raw, 'fnv', observe)
    files, identity = raw.read_card(run, path.name, export_proof, set())
    assert files == {} and identity['sha256'] == hashlib.sha256(data).hexdigest()
    assert observed == [data[offset:offset + 32] for offset in range(0, len(data), 32)]
    chunk = export_proof['chunks'][index]
    chunk['guest_fnv64'] = chunk['actual_fnv64'] = f'{int(chunk["guest_fnv64"], 16) ^ 1:016x}'
    # Full-card SHA is still correct and the two claimed FNVs agree with each other.
    with pytest.raises(ValueError, match='actual raw-card window FNV'):
        raw.read_card(run, path.name, export_proof, set())


def test_actual_windows_do_not_replace_complete_sha_or_identity_checks(actual_window_card, monkeypatch):
    run, path, _, export_proof = actual_window_card
    digest = export_proof['sha256']
    export_proof['sha256'] = '0' * 64
    with pytest.raises(ValueError, match='complete raw card SHA256'):
        raw.read_card(run, path.name, export_proof, set())
    export_proof['sha256'] = digest
    def change_during_walk(_self):
        with path.open('ab') as stream:
            stream.write(b'X')
    monkeypatch.setattr(raw.wb._reader.Fat16, 'walk', change_during_walk)
    with pytest.raises(ValueError, match='raw card changed'):
        raw.read_card(run, path.name, export_proof, set())

