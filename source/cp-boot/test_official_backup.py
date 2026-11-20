import importlib.util
import hashlib
import struct
from pathlib import Path
import pytest

spec=importlib.util.spec_from_file_location('official_cp_backup',Path(__file__).with_name('official-backup.py'))
backup=importlib.util.module_from_spec(spec)
spec.loader.exec_module(backup)


def test_record_slices_are_disjoint_and_cover_the_original_pp():
    start0,size0,sha0=backup.RECORDS['rec0']
    start1,size1,sha1=backup.RECORDS['ed000']
    assert start0==0 and start1==size0 and start1+size1==backup.PP_BYTES
    assert size0==970752 and size1==1419512 and sha0!=sha1
    assert backup.ADDRESS==0x04000000


def test_full_pp_requires_both_original_records(tmp_path, monkeypatch):
    def record(marker):
        data = bytearray(32)
        struct.pack_into('<I', data, 0, backup.ADDRESS)
        data[12:16] = b'BK4\0'
        struct.pack_into('<I', data, 16, 819)
        data[31] = marker
        return bytes(data)

    first, second = record(1), record(2)
    whole = first + second
    sha = lambda value: hashlib.sha256(value).hexdigest()
    monkeypatch.setattr(backup, 'PP_BYTES', len(whole))
    monkeypatch.setattr(backup, 'PP_SHA', sha(whole))
    monkeypatch.setattr(backup, 'RECORDS', {
        'rec0': (0, len(first), sha(first)),
        'ed000': (len(first), len(second), sha(second)),
        'full': (0, len(whole), sha(whole)),
    })
    source = tmp_path / 'pp'
    source.write_bytes(whole)
    loaded, proof = backup.load_record(source, 'full')
    assert loaded == whole and proof['record'] == 'full'
    assert proof['bytes_modified'] is False and proof['physical_alias_verified'] is False
    monkeypatch.setitem(backup.RECORDS, 'ed000', (len(first), len(second), '0' * 64))
    with pytest.raises(ValueError, match='record identity'):
        backup.load_record(source, 'full')


def test_available_official_pp_preserves_both_records():
    product = Path(__file__).resolve().parents[2]
    source = product / 'runtime/analysis/unpacked/firmware.tar_unpacked/0110_backup/SYSIPSX-DSLR/PP/CX89701_ALLLANG.bin'
    if not source.is_file():
        pytest.skip('Official PP input is not installed')
    data, proof = backup.load_record(source, 'full')
    assert len(data) == backup.PP_BYTES
    assert hashlib.sha256(data).hexdigest() == backup.PP_SHA == proof['sha256']
    assert data[12:16] == b'BK4\0' and data[0xed000+12:0xed000+16] == b'BK4\0'


def test_unknown_selector_rejected_before_file_access(tmp_path):
    with pytest.raises(ValueError,match='selection'):
        backup.load_record(tmp_path/'does-not-exist','unverified')


@pytest.mark.parametrize('kind',('missing','directory','short','oversized'))
def test_bad_input_size_or_type_rejected(tmp_path,kind):
    source=tmp_path/'input'
    if kind=='directory':source.mkdir()
    elif kind=='short':source.write_bytes(b'wrong')
    elif kind=='oversized':
        with source.open('wb') as stream:stream.truncate(backup.PP_BYTES+1)
    with pytest.raises(ValueError,match='size/type'):
        backup.load_record(source,'ed000')


def test_same_size_corrupt_source_not_accepted(tmp_path):
    source=tmp_path/'wrong-pp'
    with source.open('wb') as stream:stream.truncate(backup.PP_BYTES)
    with pytest.raises(ValueError,match='identity'):
        backup.load_record(source,'rec0')
