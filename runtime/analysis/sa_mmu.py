"""Decode the original builder's emitted 22-slot table; payload units stay explicit."""
import struct
import hashlib
import json
from pathlib import Path

SLOTS=22


def decode(raw,*,backing_unit=None):
    if len(raw)<SLOTS*16:raise ValueError('SA MMU readback does not cover all 22 builder slots')
    if backing_unit not in (None,'byte','word'):raise ValueError('Unknown SA backing-address unit')
    entries=[];disabled=False;previous_end=-1
    for slot in range(SLOTS):
        enabled,start,end,backing=struct.unpack_from('<4I',raw,slot*16)
        if not enabled:
            if start or end or backing:raise ValueError('Nonzero disabled SA MMU record')
            disabled=True;continue
        if disabled or enabled!=1 or start&~0x1fffff80 or end&~0x1fffff80 or end<start:
            raise ValueError('SA MMU record differs from the bounded original builder format')
        if start<=previous_end:raise ValueError('Overlapping SA logical blocks')
        previous_end=end
        byte_address=backing*(4 if backing_unit=='word' else 1) if backing_unit is not None else None
        physical=None
        if byte_address is not None:
            if not 0<=byte_address<0x200000000:raise ValueError('SA backing outside the two verified RAM windows')
            physical=byte_address+0x400000000
        entries.append(dict(slot=slot,enabled=enabled,logical_start_block=start,
            logical_last_block=end,logical_block_bytes=128,
            logical_covered_bytes=end-start+128,backing_encoded=backing,
            backing_unit=backing_unit,backing_bus_byte_address=byte_address,
            backing_physical_address=physical,payload_size_verified=False))
    return dict(builder_slot_count=SLOTS,enabled_records=len(entries),entries=entries,
        explicit_zero_tail_present=disabled,backing_unit_selected=backing_unit,
        backing_unit_verified=False,
        program_execution_verified=False,completion_verified=False)


def verify_committed(run):
    run=Path(run)
    raw=(run/'sa2-slot1.bin').read_bytes()
    identity=json.loads((run/'sa2-job-readback.json').read_text())
    digest=hashlib.sha256(raw).hexdigest()
    if identity['files']['slot1']['sha256']!=digest:raise ValueError('SA slot readback identity differs')
    entry=None;matches=[]
    for line in (run/'resize-watch-events.jsonl').read_text().splitlines():
        event=json.loads(line)
        if event.get('original_entry_verified') is not True:continue
        if event['kind']=='sa_mmu_builder_entry':entry=event
        if event['kind']=='sa_mmu_builder_commit' and entry is not None:
            pointer=int(event['table_virtual_address'],16)
            physical=pointer-0xffffffbc00000000
            expected=identity['request']['regions']['slot1']['physical_address']
            snapshot=bytes.fromhex(event['table_hex'])
            if physical==expected and len(snapshot)==SLOTS*16 and raw[:SLOTS*16]==snapshot:
                matches.append((entry,event))
    if len(matches)!=1:raise ValueError('No unique original builder entry/committed table pair')
    entry,event=matches[0]
    decoded=decode(raw,backing_unit=entry['backing_unit'])
    if decoded['enabled_records']!=event['builder_record_count']:
        raise ValueError('SA builder count differs from committed enabled records')
    decoded.update(backing_unit_verified=True,original_builder_entry_verified=True,
        original_committed_table_readback_verified=True,table_sha256=digest,
        logical_input_count=entry['logical_input_count'],logical_window_mode=entry['logical_window_mode'])
    return decoded
