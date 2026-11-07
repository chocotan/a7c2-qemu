#!/usr/bin/env python3
"""Validate the second finite handshake, event association and original waiter."""
import argparse
import json
from pathlib import Path
import re
import runpy
import struct

HERE=Path(__file__).resolve().parent
S=(0,2,1,0x90590818)
P=(0,1,4,0x91670464)


def require(value,reason):
    if not value:raise ValueError(reason)


def verify_connection(run,family):
    if family=='SCALAR':
        S,P=(0,2,1,0x90590818),(0,1,4,0x91670464)
        source_slot,peer_slot,next_slot,next_keys=4,4,5,(0,2,2)
        profile,predecessor_name='scalar_connection','verify-scalar-pin.py'
        proof_key,next_key='scalar_control_connection_verified','next_out2_get_free_verified'
        token='fullsystem.scalar-connect=control'
    elif family=='ADF':
        S,P=(0,2,2,0x90590818),(0,1,0,0x9058003f)
        source_slot,peer_slot,next_slot,next_keys=5,0,7,(4,2,0)
        profile,predecessor_name='adf_connection','verify-adf-pin.py'
        proof_key,next_key='adf_control_connection_verified','next_type4_out0_get_free_verified'
        token='fullsystem.adf-connect=control'
    else:raise ValueError('Unknown metadata edge')
    predecessor=runpy.run_path(str(HERE/predecessor_name))['verify'](run)
    inputs=json.loads((run/'inputs.json').read_text())
    require(inputs['experiment'].get(profile)=='control','Explicit metadata-edge profile missing')
    api=runpy.run_path(str(HERE/'verify-system-sound-config.py'))
    lines,_=api['observer_lines']((run/'console.log').read_bytes(),(family,'PINMEM'),deduplicate=False)
    require(not any('OBS FULL_'+family+'_CONNECT_FAULT ' in line for line in lines),'Metadata-edge ownership fault')
    rows=[(i,line,dict(re.findall(r'(\w+)=([^\s]+)',line))) for i,line in enumerate(lines)]
    tid=predecessor['caller_tid']

    def event(kind,after=-1,**matches):
        return next(r for r in rows if r[0]>after and r[1].startswith('OBS FULL_'+family+'_CONNECT_'+kind+' ') and
                    all(r[2].get(k)==v for k,v in matches.items()))

    request=event('REQUEST');D=int(request[2]['source'],0)
    getfree=next(r for r in rows if r[1].startswith('OBS FULL_'+family+'_NATIVE_REPLY_FREE ') and
                 r[2].get('tid')==r[2].get('sender')==str(tid) and r[2].get('waiter')=='1' and r[2].get('rc')=='0')
    require(request[0]>getfree[0],'Second connection preceded original Scalar Get release')

    def frame(row,cmd,size,flags,source,destination,body):
        f=row[2];wire=bytes.fromhex(f['raw'])
        require(int(f['tid'])==tid and int(f['bytes'])==len(wire)==size and int(f['source'],0)==source and
                int(f['destination'],0)==destination,'Second-edge caller/route/size differs')
        require(struct.unpack_from('<IIHHII',wire)==(D if cmd==1 else 0,0xa0a0a0a0,1,size,24,size) and
                struct.unpack_from('<4H',wire,24)==(0x1000,cmd,size-24,flags),'Second-edge envelope differs')
        require(struct.unpack_from('<'+'I'*len(body),wire,32)==body,'Second-edge attributes/status differ')

    def freed(row,after,size):
        free=event('INTERNAL_FREE',after,pointer=row[2]['pointer'],bytes=str(size),rc='0')
        require(int(free[2]['owner'],0)==D and int(free[2]['tid'])==tid,'Internal allocation/free owner differs')
        return free

    frame(request,1,64,2,D,S[3],S+P)
    forward=event('PEER_REQUEST',request[0]);frame(forward,0x100,64,1,S[3],P[3],S+P)
    answer=event('PEER_REPLY',forward[0]);frame(answer,0x8100,72,1,P[3],S[3],S+P+(0,0))
    forward_free=freed(forward,answer[0],64)
    direction=event('YC_DIRECTION_CHECK',forward_free[0])
    # The shared producer also appends peer_post_attempts/peer_post_status
    # diagnostics. Require the documented guard fields to hold exactly, allow
    # only those two known extras, and require the extras to be decimal
    # counters -- so a renamed, retyped or dropped guard field still fails.
    guard={'command':'0x8100','selected_group':'source','type':'0','dir':'2',
           'index':str(S[2]),'format_published':'0','buffer_allocated':'0'}
    observed=direction[2]
    extra=set(observed)-set(guard)
    require(all(observed.get(name)==value for name,value in guard.items()) and
            extra<={'peer_post_attempts','peer_post_status'} and
            all(re.fullmatch(r'\d+',observed[name]) for name in extra),
            'Original YC direction guard was not applied to OUT1')
    resumed=event('EVENT6_CONSUMED',direction[0])
    require(resumed[2]=={'source':f'0,2,{S[2]},0x90590818','peer':f'0,1,{P[2]},{P[3]:#x}','status':'0'},'Event6 identity/status differs')
    answer_free=freed(answer,resumed[0],72)
    reply=event('REPLY_QUEUED',answer_free[0]);frame(reply,0x8001,56,2,S[3],D,S+(0,0))
    request_free=event('REQUEST_FREE',reply[0],pointer=request[2]['pointer'],bytes='64',rc='0')
    require(int(request_free[2]['owner'],0)==S[3] and int(request_free[2]['tid'])==tid,'Original PinMem request free differs')
    state=event('STATE_READBACK',request_free[0]);f=state[2]
    attrs=lambda name:tuple(int(n,0) for n in f[name].split(','))
    require(int(f['tid'])==tid and f['source_slot']==str(source_slot) and f['peer_slot']==str(peer_slot) and
            f['source_state']==f['peer_state']==f['source_pending']=='0' and
            attrs('source_self')==S and attrs('source_peer')==P and attrs('peer_self')==P and attrs('peer_peer')==S and
            f['event6_consumed']=='1' and f['yc_format_published']==f['pixels_consumed']=='0','Actual connected object readback differs')
    native=event('NATIVE_REPLY_FREE',state[0],reply=reply[2]['pointer'],rc='0')
    f=native[2]
    require(f['tid']==f['sender']==str(tid) and f['waiter']=='1' and int(f['destination'],0)==int(f['expected'],0)==D and
            f['bytes']=='56' and f['command']=='0x8001','Original connection waiter did not consume/free reply')
    continuation=next(r for r in rows if r[0]>native[0] and r[1].startswith('OBS FULL_PINMEM_COMMIT ') and
                      r[2].get('tid')==str(tid) and r[2].get('slot')==str(next_slot) and r[2].get('type')==str(next_keys[0]) and
                      r[2].get('dir')==str(next_keys[1]) and r[2].get('index')==str(next_keys[2]) and r[2].get('request_free_rc')=='0' and
                      r[2].get('pin_state')=='1' and int(r[2].get('owner','0'),0)==S[3] and r[2].get('status')=='0')
    next_reply=next(r for r in rows if native[0]<r[0]<continuation[0] and r[1].startswith('OBS FULL_PINMEM_REPLY_QUEUED ') and
                    r[2].get('reply')==continuation[2]['reply'] and r[2].get('lease')==continuation[2]['lease'])
    next_destination=int(next_reply[2]['destination'],0)
    require(next_destination>>28==8 and next_destination&0xfffffff,'Next Get destination is not a local waiter')
    frame(next_reply,0x8000,56,2,S[3],next_destination,next_keys+(1,S[3],0))
    next_free=next(r for r in rows if r[0]>continuation[0] and r[1].startswith('OBS FULL_PINMEM_NATIVE_REPLY_FREE ') and
         r[2].get('tid')==r[2].get('sender')==str(tid) and r[2].get('waiter')=='1' and r[2].get('rc')=='0' and
         r[2].get('reply')==continuation[2]['reply'] and r[2].get('lease')==continuation[2]['lease'])
    require(next_free[2].get('bytes')=='56' and int(next_free[2]['destination'],0)==int(next_free[2]['expected'],0)==next_destination,
            'Next Get actual free size/destination differs from its own queued reply')
    reservation=runpy.run_path(str(HERE/'verify-pin-control.py'))
    command=reservation['verify_reservation'](run,runpy.run_path(str(HERE/'pin-buffer-region.py')))
    require(command.split().count(token)==1,'Actual metadata-edge DTB profile missing')
    return {'schema':1,proof_key:True,'caller_tid':tid,'dynamic_sid':hex(D),'source':list(S),'peer':list(P),
            'event6_consumed_verified':True,'original_waiter_reply_free_verified':True,next_key:True,
            'yc_direction_guard_skipped_publication':True,'console_sha256':predecessor['console_sha256'],
            'original_CP_task_running_verified':False,'pixels_consumed':False,'camera_startup_verified':False}


def verify(run):
    return verify_connection(run,'SCALAR')


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('run',type=Path);args=parser.parse_args()
    try:proof=verify(args.run)
    except (OSError,ValueError,KeyError,StopIteration,TypeError,struct.error) as error:
        proof={'scalar_control_connection_verified':False,'error':str(error) or type(error).__name__,'camera_startup_verified':False}
    (args.run/'scalar-connection-proof.json').write_text(json.dumps(proof,indent=2)+'\n')
    print(json.dumps(proof,sort_keys=True));return 0 if proof['scalar_control_connection_verified'] else 1


if __name__=='__main__':raise SystemExit(main())
