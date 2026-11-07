#!/usr/bin/env python3
"""Verify a narrow native 403d milestone without changing the VM failure result."""
import argparse
import hashlib
import json
from pathlib import Path
import struct

if not __debug__:
    raise RuntimeError('Evidence verification cannot run with Python assertions disabled')


def verify(run, next_command):
    raw=(run/'console.log').read_bytes()
    lines=raw.decode('utf-8',errors='replace').replace('\r','').splitlines()
    assert not any('OBS FULL_IMAGING_FAULT ' in line for line in lines),'imaging ownership fault'
    requests={};committed={};completed={};observed=set();next_seen=False
    for line in lines:
        if not line.startswith('OBS FULL_IMAGING_'):continue
        fields=dict(part.split('=',1) for part in line.split() if '=' in part)
        if line.startswith('OBS FULL_IMAGING_REQUEST '):
            command=int(fields['cmd'],0)
            if command==next_command:
                assert requests.keys()==committed.keys()==completed.keys()
                assert {(0x8000,0),(0x8000,1)}<=observed,'next operation preceded the set/clear pair'
                next_seen=True
            if command!=0x403d:continue
            assert int(fields['destination'],0)==0x90040193 and int(fields['source'],0)==0x80020002
            body=bytes.fromhex(fields['raw'])
            assert len(body)==16 and body[:4]==b'\x05\x00\x3d\x40'
            token,mask=struct.unpack_from('<II',body,4)
            assert mask in (0x8000,0x200000) and body[12] in (0,1) and body[13:]==b'\0'*3
            key=(int(fields['tid']),token)
            assert key not in requests,'duplicate native request identity'
            requests[key]=(mask,body[12])
        elif line.startswith('OBS FULL_IMAGING_COMMIT ') and int(fields['cmd'],0)==0x403d:
            key=(int(fields['tid']),int(fields['token'],0));mask,lock=requests[key]
            before=int(fields['before'],0);after=int(fields['requested'],0)
            assert after==(before|mask if lock else before&~mask)
            assert int(fields['effective'],0)==after
            assert after&0x04000000,'unmodeled power-on inhibit was cleared'
            assert int(fields['status'],0)==0xf000 and int(fields['request_free_rc'])==0
            committed[key]=fields['reply'];observed.add((mask,lock))
        elif line.startswith('OBS FULL_IMAGING_NATIVE_REPLY_FREE ') and int(fields['cmd'],0)==0x403d:
            key=(int(fields['sender']),int(fields['token'],0))
            assert key in committed and fields['reply']==committed[key]
            assert int(fields['tid'])==key[0] and int(fields['waiter'])==1
            assert fields.get('rc')=='0','missing or failed actual native reply free'
            assert int(fields['bytes'])==12 and int(fields['status'],0)==0xf000
            assert key not in completed,'reply released twice'
            completed[key]=fields['reply']
    assert {(0x8000,0),(0x8000,1)}<=observed,'native ordinary set/clear pair missing'
    assert requests.keys()==committed.keys()==completed.keys(),'incomplete native RPC ownership chain'
    assert next_seen,'original startup did not reach the expected next operation'
    result=json.loads((run/'result.json').read_text())
    assert result['camera_startup_verified'] is False
    proof={'subset':'403d-native-request-state-reply-waiter-release',
           'verified':True,'camera_startup_verified':False,'native_completed':len(completed),
           'next_command':hex(next_command),'original_run_state':result['state'],
           'console_sha256':hashlib.sha256(raw).hexdigest(),
           'initrd_sha256':json.loads((run/'inputs.json').read_text())['initrd_sha256']}
    (run/'release-lock-proof.json').write_text(json.dumps(proof,indent=2)+'\n')
    return proof


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('run',type=Path)
    parser.add_argument('--next-command',required=True,type=lambda value:int(value,0))
    args=parser.parse_args()
    print(json.dumps(verify(args.run,args.next_command),indent=2))
