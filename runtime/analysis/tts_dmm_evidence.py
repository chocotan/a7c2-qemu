"""Read-only correlation of the original AP text-speech table and native DMM slots.

A match is ownership evidence for this snapshot, never permission to free a
handle, change the NoMem admission rule, or claim any camera/frame completion.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import struct

TABLE_VA = 0x5f66b08
TABLE_BYTES = 0x90
CP_BASE = 0x1e000000
SLOT_BYTES = 0x80000


def decode_table(data):
    if len(data) != TABLE_BYTES:
        raise ValueError('Text-speech table is not exactly two 0x48-byte entries')
    entries = []
    for offset in (0, 0x48):
        entry = {
            'id': struct.unpack_from('<I', data, offset)[0],
            'ap_handle': struct.unpack_from('<I', data, offset+4)[0],
            'cp_handle': struct.unpack_from('<I', data, offset+0x18)[0],
            'cp_bytes': struct.unpack_from('<I', data, offset+0x1c)[0],
            'cp_address': struct.unpack_from('<Q', data, offset+0x20)[0],
            'ap_mapping': struct.unpack_from('<Q', data, offset+0x28)[0],
        }
        entries.append(entry)
    if {entry['id'] for entry in entries} != {0x1a, 0x1b}:
        raise ValueError('Original text-speech entry identities are missing or duplicated')
    return entries


def correlate(console):
    if isinstance(console, str):
        console = console.encode('utf-8')
    clean = console.replace(b'\r', b'')
    table_rows = re.findall(
        rb'^(?:/ # )?OBS FULL_VEF_RESOURCES_TTS_TABLE (?:pid=(\d+) )?tid=(\d+) appfw_base=(0x[0-9a-f]+) '
        rb'table_va=0x5f66b08 address=(0x[0-9a-f]+) bytes=144 reads=144/144 '
        rb'unchanged=1 atomic_snapshot=0 raw_before=([0-9a-f]{288}) '
        rb'raw_after=([0-9a-f]{288}) ownership_verified=0$', clean, re.M)
    if len(table_rows) != 1:
        raise ValueError('No unique complete unchanged original text-speech table readback')
    pid, tid, base, address, before, after = table_rows[0]
    if int(address, 16) != int(base, 16)+TABLE_VA or before != after:
        raise ValueError('Text-speech table identity/address changed')
    raw = bytes.fromhex(before.decode())
    entries = decode_table(raw)
    pool_rows = re.findall(
        rb'^(?:/ # )?OBS FULL_VEF_RESOURCES_(?:REFUSED|RESERVED) tid='+tid+
        rb' accepted=[01] dmm_enabled=1 dmm_bound=1 dmm_slots=(\d)/(\d) '
        rb'dmm_opens=(\d+)/(\d+) dmm_handles=(0x[0-9a-f]+|0)/(0x[0-9a-f]+|0) '
        rb'dmm_generations=(\d+)/(\d+) ', clean, re.M)
    if len(pool_rows) != 1:
        raise ValueError('No unique same-thread native DMM snapshot with handle generations')
    a, b, opened_a, opened_b, handle_a, handle_b, gen_a, gen_b = pool_rows[0]
    slots = [dict(index=index, allocated=int(allocated), opens=int(opens),
                  handle=int(handle, 0), generation=int(generation))
             for index, allocated, opens, handle, generation in (
                 (0, a, opened_a, handle_a, gen_a), (1, b, opened_b, handle_b, gen_b))]
    if any(slot['allocated'] != 1 or slot['opens'] != 1 for slot in slots):
        raise ValueError('This bounded correlation requires both live singly-open slots')
    indices = set()
    for entry in entries:
        if not entry['cp_handle'] & 0x8000 or entry['cp_handle'] >> 16:
            raise ValueError('Text-speech CP handle lacks the native CP marker or exceeds u16')
        index = entry['cp_handle'] & 0x3ff
        if index >= len(slots) or index in indices:
            raise ValueError('Text-speech handles do not name two distinct native slots')
        indices.add(index)
        slot = slots[index]
        if (entry['cp_handle'] != slot['handle'] or not slot['generation'] or
                ((entry['cp_handle'] >> 10) & 31) != slot['generation'] or
                entry['cp_bytes'] != SLOT_BYTES or entry['cp_address'] != CP_BASE+index*SLOT_BYTES):
            raise ValueError('Text-speech handle/generation/address/length does not match native slot')
    return {'available': True,
            'scope': 'original AP table readback correlated with tracked native DMM slots only',
            'ap_pid': int(pid) if pid else None, 'ap_tid': int(tid),
            'appfw_base': hex(int(base,16)), 'table_elf_va': hex(TABLE_VA),
            'table_sha256': hashlib.sha256(raw).hexdigest(), 'table_bytes': len(raw),
            'table_unchanged_between_reads': True, 'atomic_snapshot': False,
            'speech_handles_match_live_native_slots': True,
            'entries': entries, 'native_slots': slots,
            'creator_call_chain_verified': False, 'ap_mapping_verified': False,
            'global_dmm_idle_verified': False,
            'resource_release_authorized': False, 'vef_path_verified': False, 'capture_verified': False}


def _rows(console, tag):
    text=console.decode('ascii') if isinstance(console,bytes) else console
    prefix='OBS '+tag+' '
    rows=[]
    for number,line in enumerate(text.replace('\r','').splitlines()):
        if line.startswith('/ # '):line=line[4:]
        if line.startswith(prefix):
            row=dict(re.findall(r'(\w+)=([^\s]+)',line[len(prefix):]))
            row['_line']=number;rows.append(row)
    return rows


def _number(row,key):
    try:return int(row[key],0)
    except (KeyError,ValueError,TypeError):raise ValueError('Missing or invalid provenance field: '+key) from None


def prove_initial_creation(console):
    proof=correlate(console)
    if proof['ap_pid'] is None:raise ValueError('Creation proof needs an explicit original AP PID')
    pools=_rows(console,'FULL_VEF_RESOURCES_REFUSED')+_rows(console,'FULL_VEF_RESOURCES_RESERVED')
    if len(pools)!=1:raise ValueError('No unique native resource admission epoch')
    pool=pools[0]
    if (_number(pool,'tid')!=proof['ap_tid'] or pool.get('dmm_epochs')!='1/2' or
            pool.get('dmm_creators')!='1/1' or _number(pool,'dmm_allocation_count')!=2 or
            _number(pool,'dmm_lifecycle_changed')!=0):
        raise ValueError('Native resource lifecycle is not the first two untouched Speech allocations')
    services=[r for r in _rows(console,'DMM_SERVICE') if r['_line']<pool['_line']]
    created=[]
    for row in services:
        op=_number(row,'op');status=_number(row,'status');transport=_number(row,'transport')
        if _number(row,'lifecycle_changed')!=0 or _number(row,'allocation_count')>2:
            raise ValueError('Native DMM history changed before NoMem admission')
        if transport==0 and op in (0x21,0x22,0x23) and status>=0:
            raise ValueError('Reference or release history invalidates the cold Speech exclusion')
        if op==0x20 and transport==0 and status==0:created.append(row)
    if len(created)!=2:raise ValueError('No exact pair of successful initial allocations')
    expected=(0x35522a4,0x35527b4,0x34d3614,0x17b2c08)
    requests=_rows(console,'DMM_REQUEST');frames=_rows(console,'DMM_ALLOC_FRAME')
    summaries=_rows(console,'DMM_ALLOC_CREATOR');base=int(proof['appfw_base'],16)
    previous_completion=-1
    for index,row in enumerate(created):
        sample=index+1;slot=proof['native_slots'][index];sender=_number(row,'source')
        if sender>>28!=8 or not sender&0x0fffffff:
            raise ValueError('Speech allocation has no original local caller source')
        if (_number(row,'pid')!=proof['ap_pid'] or _number(row,'sample')!=sample or
                _number(row,'creator_kind')!=1 or _number(row,'handle')!=slot['handle'] or
                _number(row,'address')!=CP_BASE+index*SLOT_BYTES or _number(row,'size')!=SLOT_BYTES or
                _number(row,'allocation_count')!=sample or
                row.get('slots')!=('1/0' if index==0 else '1/1') or
                row.get('opens')!=('1/0' if index==0 else '1/1') or
                row.get('slot_epochs')!=('1/0' if index==0 else '1/2') or
                row.get('slot_creators')!=('1/0' if index==0 else '1/1') or
                row.get('caller')!='/usr/lib/appFw.so+0x35522a4' or
                _number(row,'caller_raw')!=base+expected[0]):
            raise ValueError('Successful allocation lacks exact process/caller/slot/epoch binding')
        preceding=[r for r in requests if r['_line']<row['_line']]
        if not preceding:raise ValueError('Successful allocation lacks its original request')
        request=preceding[-1]
        if request['_line']<=previous_completion:
            raise ValueError('Each allocation needs a distinct request after the previous completion')
        try:wire=bytes.fromhex(request['raw'])
        except (KeyError,ValueError):raise ValueError('Missing original DMM request bytes') from None
        if (len(wire)!=40 or _number(request,'bytes')!=40 or _number(request,'sampled')!=40 or
                _number(request,'tid')!=_number(row,'tid') or _number(request,'source')!=sender or
                _number(request,'op')!=0x20 or _number(request,'unit')!=0x63a or _number(request,'option')!=1 or
                struct.unpack_from('<H',wire)[0]!=0x20 or struct.unpack_from('<I',wire,4)[0]!=0x63a or
                struct.unpack_from('<H',wire,22)[0]!=1):
            raise ValueError('Original 40-byte Speech CP allocation request differs')
        chain=[r for r in frames if _number(r,'sample')==sample and _number(r,'depth')<4]
        if len(chain)!=4:raise ValueError('No unique four-frame Speech creation witness')
        first=None
        for depth,(frame,offset) in enumerate(zip(chain,expected)):
            fp=_number(frame,'fp')
            if first is None:first=fp
            if (_number(frame,'depth')!=depth or _number(frame,'tid')!=_number(row,'tid') or
                    _number(frame,'appFw_offset')!=offset or _number(frame,'lr')!=base+offset or
                    _number(frame,'in_appFw')!=1 or _number(frame,'caller_matches')!=1 or
                    _number(frame,'frame_candidate_only')!=1 or fp&15 or
                    not 0x10000<=fp<=0x800000000000-16 or fp<first or fp-first>0x40000 or
                    (depth and fp<=_number(chain[depth-1],'fp')) or
                    not request['_line']<frame['_line']<row['_line']):
                raise ValueError('Bounded original AP return-PC creation witness differs')
        summary=[r for r in summaries if _number(r,'sample')==sample]
        if (len(summary)!=1 or _number(summary[0],'creator_kind')!=1 or
                _number(summary[0],'caller_matches')!=1 or not 4<=_number(summary[0],'frames')<=8 or
                _number(summary[0],'tid')!=_number(row,'tid') or
                not chain[-1]['_line']<summary[0]['_line']<row['_line']):
            raise ValueError('Original creation summary is incomplete or unknown')
        previous_completion=row['_line']
    proof.update(creator_call_chain_verified=True,initial_speech_lifecycle_verified=True,
                 creator_proof_scope='four bounded saved AP return PCs, request/response and first allocation epochs; not a complete unwind')
    return proof


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('run', type=Path)
    args = parser.parse_args()
    console=(args.run/'console.log').read_bytes()
    try:
        proof=prove_initial_creation(console)
    except ValueError as provenance_error:
        try:
            proof=correlate(console)
            proof.update(initial_speech_lifecycle_verified=False,provenance_reason=str(provenance_error))
        except ValueError as error:
            proof={'available':False,'reason':str(error),'initial_speech_lifecycle_verified':False,
                   'speech_handles_match_live_native_slots':False,'resource_release_authorized':False,
                   'vef_path_verified':False,'capture_verified':False}
    (args.run/'tts-dmm-evidence.json').write_text(json.dumps(proof, indent=2)+'\n')
    print(json.dumps(proof, indent=2))
    return 0 if proof.get('initial_speech_lifecycle_verified') else 1


if __name__ == '__main__':
    raise SystemExit(main())
