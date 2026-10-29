import hashlib
from pathlib import Path
import struct
import json
import pytest

from sa_mmu import decode,verify_committed


def records():
    raw=bytearray(512)
    struct.pack_into('<4I',raw,0,1,0,0x1f80,0x25558000)
    struct.pack_into('<4I',raw,16,1,0x2000,0x3f80,0x3e140000)
    return raw


def test_units_remain_unknown_without_the_original_caller_mode():
    result=decode(records())
    assert result['enabled_records']==2 and result['explicit_zero_tail_present']
    assert result['entries'][0]['logical_covered_bytes']==8192
    assert result['entries'][0]['backing_physical_address'] is None
    assert decode(records(),backing_unit='byte')['entries'][0]['backing_physical_address']==0x425558000
    assert decode(records(),backing_unit='word')['entries'][1]['backing_physical_address']==0x4f8500000
    assert not result['program_execution_verified'] and not result['completion_verified']


@pytest.mark.parametrize('fault',['short','enable','mask','gap','reverse','overlap','tail'])
def test_unexpected_table_is_not_admitted(fault):
    raw=records()
    if fault=='short':raw=raw[:351]
    elif fault=='enable':struct.pack_into('<I',raw,0,2)
    elif fault=='mask':struct.pack_into('<I',raw,4,1)
    elif fault=='gap':raw[:16]=bytes(16)
    elif fault=='reverse':struct.pack_into('<I',raw,20,0x4000)
    elif fault=='overlap':struct.pack_into('<I',raw,20,0x1f80)
    elif fault=='tail':struct.pack_into('<I',raw,36,1)
    with pytest.raises(ValueError):decode(raw)


def test_actual_original_builder_fields_and_units_branch():
    path=Path(__file__).resolve().parent/'menu-root/system/av-cam.bin'
    if not path.exists():pytest.skip('Original firmware is not distributed')
    b=path.read_bytes();assert hashlib.sha256(b).hexdigest()=='90343f5f2edc0393ad8809d907cfe648dfd3a82ce0ef39cf06167929d8955096'
    for offset,word in ((0x2ff7ec,0x29002d4d),(0x2ff7f0,0xb900094c),
        (0x2ff850,0xd342fd09),(0x2ff854,0x72001f9f),(0x2ff860,0x9a891108),
        (0x2ff884,0xb9000d48),(0x2ff8b4,0x528002c9)):
        assert struct.unpack_from('<I',b,offset)[0]==word


def test_committed_table_units_require_matching_original_entry_and_full_bytes(tmp_path):
    raw=bytes(records());(tmp_path/'sa2-slot1.bin').write_bytes(raw)
    (tmp_path/'sa2-job-readback.json').write_text(json.dumps(dict(files=dict(slot1=dict(sha256=hashlib.sha256(raw).hexdigest())),
        request=dict(regions=dict(slot1=dict(physical_address=0x47e5bd400))))))
    entry=dict(kind='sa_mmu_builder_entry',original_entry_verified=True,logical_input_count=2,
        logical_window_mode=1,backing_unit='word')
    commit=dict(kind='sa_mmu_builder_commit',original_entry_verified=True,builder_record_count=2,
        table_virtual_address='0xffffffc07e5bd400',table_hex=raw[:352].hex())
    path=tmp_path/'resize-watch-events.jsonl'
    path.write_text('\n'.join(map(json.dumps,[entry,commit])))
    proof=verify_committed(tmp_path)
    assert proof['backing_unit_verified'] and proof['original_committed_table_readback_verified']
    commit['table_hex']='00'*352;path.write_text('\n'.join(map(json.dumps,[entry,commit])))
    with pytest.raises(ValueError,match='unique'):verify_committed(tmp_path)
