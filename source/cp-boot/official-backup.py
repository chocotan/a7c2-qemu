#!/usr/bin/env python3
"""Load one verbatim official BK4 record for explicit CP input diagnostics."""
import argparse
import hashlib
import json
from pathlib import Path
import struct

PROFILE='virtual-official-cp-bk4-input-v1'
PP_BYTES=2390264
PP_SHA='3dab4f0d6b7790f4a7798034b57f43bfe3255c39dc6da2897fc288b3a218fe47'
RECORDS={
    'rec0':(0,970752,'a6d0b73062731fbec2c556509b70ac794a23b33c135f491fb2338e992702ec8b'),
    'ed000':(970752,1419512,'a90b46ae1d0fa054daeba321c52dc9d44d6bf32ca6eefcd1efb84fab2116e977'),
    'full':(0,PP_BYTES,PP_SHA),
}
ADDRESS=0x04000000


def load_record(path,selector):
    if selector not in RECORDS:
        raise ValueError('Unknown official BK4 record selection')
    path=Path(path)
    if not path.is_file() or path.stat().st_size!=PP_BYTES:
        raise ValueError('Official PP size/type differs')
    with path.open('rb') as stream:data=stream.read(PP_BYTES+1)
    if len(data)!=PP_BYTES or hashlib.sha256(data).hexdigest()!=PP_SHA:
        raise ValueError('Official PP identity differs')
    offset,size,digest=RECORDS[selector]
    record=data[offset:offset+size]
    if len(record)!=size or hashlib.sha256(record).hexdigest()!=digest:
        raise ValueError('Official BK4 record identity differs')
    for name in (('rec0','ed000') if selector=='full' else (selector,)):
        start,length,expected=RECORDS[name]
        part=data[start:start+length]
        if len(part)!=length or hashlib.sha256(part).hexdigest()!=expected:
            raise ValueError('Official BK4 record identity differs')
        if part[12:16]!=b'BK4\0' or struct.unpack_from('<I',part)[0]!=ADDRESS or struct.unpack_from('<I',part,16)[0]!=819:
            raise ValueError('Original BK4 header fields differ')
    return record,dict(profile=PROFILE,pp_sha256=PP_SHA,record=selector,offset=offset,
        bytes=size,sha256=digest,load_address=hex(ADDRESS),subsystems=819,
        bytes_modified=False,source_class='official ALLLANG PP record',
        selection_scope='Explicit functional-model choice; original loader record selection unknown',
        sony_loader_selection_verified=False,physical_alias_verified=False,
        tomco_modified=False,bkup_ready_or_ack_injected=False)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--pp',type=Path,required=True)
    parser.add_argument('--record',choices=tuple(RECORDS),required=True)
    parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args();record,proof=load_record(args.pp,args.record)
    with args.out.open('xb') as stream:stream.write(record)
    if hashlib.sha256(args.out.read_bytes()).hexdigest()!=proof['sha256']:
        raise ValueError('Staged original BK4 readback differs')
    print(json.dumps(proof,indent=2))
