#!/usr/bin/env python3
"""Verify the fourth (PinMem HDMIVIDEO->HDMI VIDEO) and fifth (ADF AUDIO->HDMI
AUDIO) edges from F's own console.

Each edge must show its four captured frames, event6, the original waiter's
56 B reply release, and the independent shared state byte. A HDMI VIDEO connect
must not set the AUDIO byte and vice versa.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import struct

EDGES={
    'hdmi':{'prefix':'FULL_HDMI_CONNECT_','S':(4,2,0,0x90590818),'P':(4,1,0,0x909a015a),
            'source_slot':7,'peer_slot':0,'byte':'video_connected','profile':'hdmi_connection'},
    'adf_audio':{'prefix':'FULL_ADFAUDIO_CONNECT_','S':(5,2,0,0x9058003f),'P':(5,1,0,0x909a015a),
                 'source_slot':9,'peer_slot':1,'byte':'audio_connected','profile':'adf_audio_connection'},
}


def records(console,prefix):
    rows=[]
    needle=prefix.encode()
    for index,line in enumerate(console.splitlines()):
        at=line.find(needle)
        if at<0:continue
        rest=line[at+len(needle):].decode(errors='replace')
        tag,_,tail=rest.partition(' ')
        rows.append((index,tag.strip(),dict(re.findall(r'(\w+)=([^\s]+)',tail))))
    return rows


def require(value,why):
    if not value:raise ValueError(why)


def frame(row,command,size,flags,source,destination,words):
    """Words are the captured body after the 32 B header, in order."""
    fields=row[2]
    wire=bytes.fromhex(fields['raw'])
    require(len(wire)==size==32+4*len(words),'Frame length differs: %#x'%command)
    require(int(fields['source'],0)==source and int(fields['destination'],0)==destination,'Frame route differs: %#x'%command)
    require(struct.unpack_from('<4H',wire,24)==(0x1000,command,size-32,flags),'Frame envelope differs: %#x'%command)
    require(struct.unpack_from('<'+'I'*len(words),wire,32)==tuple(words),'Frame body differs: %#x'%command)
    return row


def verify_edge(console,key):
    spec=EDGES[key];rows=records(console,spec['prefix'])
    if not rows:return {'edge':key,'verified':False,'reason':'no records'}
    S,P=spec['S'],spec['P']
    order=[row[1] for row in rows]
    required=('REQUEST','PEER_REQUEST','PEER_REPLY','REPLY_QUEUED','YC_DIRECTION_CHECK',
              'EVENT6_CONSUMED','NATIVE_REPLY_FREE','STATE_READBACK')
    missing=[tag for tag in required if tag not in order]
    if missing:raise ValueError('Missing edge records: '+','.join(missing))
    request=next(r for r in rows if r[1]=='REQUEST')
    frame(request,1,64,2,spec['S'][3],spec['S'][3],S+P)
    forward=next(r for r in rows if r[1]=='PEER_REQUEST')
    frame(forward,0x100,64,1,spec['S'][3],spec['P'][3],S+P)
    answer=next(r for r in rows if r[1]=='PEER_REPLY')
    frame(answer,0x8100,72,1,spec['P'][3],spec['S'][3],S+P+(0,0))
    final=next(r for r in rows if r[1]=='REPLY_QUEUED')
    frame(final,0x8001,56,2,spec['S'][3],spec['S'][3],S+(0,0))
    direction=next(r for r in rows if r[1]=='YC_DIRECTION_CHECK')
    require(int(direction[2]['type'])==P[0] and int(direction[2]['dir'])==2,'Type/dir of the captured edge differs')
    require(direction[2]['format_published']=='0' and direction[2]['buffer_allocated']=='0',
            'A dir2 source must not publish format or allocate a buffer')
    event6=next(r for r in rows if r[1]=='EVENT6_CONSUMED')
    require(event6[2]['status']=='0','event6 status differs')
    free=next(r for r in rows if r[1]=='NATIVE_REPLY_FREE')
    require(free[2]['waiter']=='1' and free[2]['rc']=='0','Original waiter did not release the 56 B reply')
    require(int(free[2]['sender'])==int(free[2]['tid']),'Reply was released by another thread')
    state=next(r for r in rows if r[1]=='STATE_READBACK')
    require(int(state[2]['source_slot'])==spec['source_slot'] and int(state[2]['peer_slot'])==spec['peer_slot'],
            'Edge slot identity differs')
    require(state[2]['source_state']=='0' and state[2]['peer_state']=='0' and state[2]['source_pending']=='0',
            'Both ends did not settle to state 0')
    byte=next((r for r in rows if spec['byte'] in r[2]),None)
    require(byte is not None,'Own shared byte was not reported')
    require(int(byte[2][spec['byte']])==1,'Own shared byte was not set')
    other='audio_connected' if spec['byte']=='video_connected' else 'video_connected'
    # Independence: when this edge set its own byte, the other family's byte must
    # not have been set by it. The two owners are separate fields in the original.
    if other in byte[2]:
        require(int(byte[2][other])==0,
                'Edge %s also set the unrelated shared byte %s'%(key,other))
    require(not any(tag in ('FAULT','UNSUPPORTED') for tag in order),'Edge reported a fault/unsupported path')
    return {'edge':key,'verified':True,'source_slot':spec['source_slot'],'peer_slot':spec['peer_slot'],
            'shared_byte':spec['byte'],'records':len(rows),
            'own_byte':int(byte[2][spec['byte']]),
            'other_byte_seen':int(byte[2].get(other,0)) if other in byte[2] else None}


def verify(run):
    console=(run/'console.log').read_bytes()
    result=json.loads((run/'result.json').read_text())
    identity=json.loads((run/'inputs.json').read_text())
    digest=hashlib.sha256(console).hexdigest()
    require(result.get('terminal_evidence_checked') is True and result.get('terminal_console_sha256')==digest,
            'Terminal console is not the checked one')
    edges={}
    for key,spec in EDGES.items():
        enabled=identity['experiment'].get(spec['profile'])!='off'
        proof=verify_edge(console,key)
        if enabled:require(proof['verified'],'Enabled edge lacks complete evidence: '+proof.get('reason',''))
        edges[key]=proof
    hdmi=edges['hdmi'];audio=edges['adf_audio']
    if hdmi['verified'] and audio['verified']:
        # Both edges ran in this console. Each state readback reports only its own
        # family's byte; a later AUDIO edge must not clear the VIDEO byte.
        video=records(console,'FULL_HDMI_CONNECT_');audio_rows=records(console,'FULL_ADFAUDIO_CONNECT_')
        vstate=[r for r in video if r[1]=='STATE_READBACK'][0][2]
        astate=[r for r in audio_rows if r[1]=='STATE_READBACK'][0][2]
        require(int(vstate['video_connected'])==1,'VIDEO byte not set in its own readback')
        require(int(astate['audio_connected'])==1,'AUDIO byte not set in its own readback')
        require(int(astate.get('video_connected','0'))==0,'AUDIO edge touched the VIDEO byte')
        require(int(vstate.get('audio_connected','0'))==0,'VIDEO edge touched the AUDIO byte')
    require(not (result.get('camera_startup_verified') is True),
            'Component edge evidence must not claim camera startup')
    return {'fourth_edge_verified':hdmi['verified'],'fifth_edge_verified':audio['verified'],
            'edges':edges,'console_sha256':digest,
            'visible_pixels_verified':False,'viewfinder_verified':False,
            'original_cp_task_running':False,'camera_startup_verified':False}


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('run',type=Path);args=parser.parse_args()
    try:proof=verify(args.run)
    except (OSError,ValueError,KeyError,TypeError,StopIteration) as error:
        proof={'fourth_edge_verified':False,'fifth_edge_verified':False,'error':str(error),
               'camera_startup_verified':False}
    (args.run/'hdmi-audio-edges-proof.json').write_text(json.dumps(proof,indent=2)+'\n')
    print(json.dumps(proof,sort_keys=True))
    return 0 if proof.get('fourth_edge_verified') and proof.get('fifth_edge_verified') else 1


if __name__=='__main__':raise SystemExit(main())
