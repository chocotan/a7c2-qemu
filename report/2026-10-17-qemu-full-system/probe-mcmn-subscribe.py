#!/usr/bin/env python3
"""Ask the original mcmn driver to replay its cached front-end state packet.

`mcmn_drv.ko`'s worker caches the 7-byte front-end state it receives and only
forwards it to a notify queue once someone subscribes with command 3. This probe
publishes the verified CP packet (so the cache is populated), then subscribes with
the original protocol via `mcmn-query subscribe` and reads the replayed bytes.

Three layers, none of which substitutes for another:

A. the original driver accepts the subscription  -> `MCMN_SUBSCRIBE_REPLY_SIZE bytes=28`
B. it replays a 7-byte state                     -> `MCMN_SUBSCRIBE_STATE_SIZE bytes=7`
C. the replay is byte-identical to what we sent  -> parse the `raw=` hex
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import runpy
import subprocess
import sys
import tempfile

HERE=Path(__file__).resolve().parent
CP=runpy.run_path(str(HERE/'probe-cp-rm-notify.py'))
normalize_plan=runpy.run_path(str(HERE/'probe-media-mount-action.py'))['normalize_plan']


def plan_for(walk, publish_at, subscribe_at, packet):
    plan=walk.split(';')
    plan.extend(normalize_plan(publish_at))
    plan.append(f'{publish_at:.1f}:/simulation/cp-rm-notify '+' '.join(str(b) for b in packet))
    plan.append(f'{subscribe_at:.1f}:/simulation/mcmn-query subscribe')
    plan.sort(key=lambda item:float(item.partition(':')[0]))
    return plan


def replay_bytes(text):
    """The 7-byte state the driver replayed.

    Measured protocol (run-_xwo2mtn): the 7-byte front-end state arrives as the
    DIRECT REPLY to command 3 (`MCMN_QUERY_SUBSCRIBE_REPLY ... bytes=7 raw=02000002000200`),
    and the 24+4 command echo follows as a second, 28-byte message. The first version of
    this probe assumed the opposite order and mislabelled both.
    """
    match=re.search(r'MCMN_QUERY_SUBSCRIBE_REPLY command=3 bytes=\d+ raw=([0-9a-f]+)',text)
    if not match:return None
    return bytes.fromhex(match.group(1))


def verdict(text, packet):
    published=bool(re.search(r'CP_RM_NOTIFY_SENT rc=0',text))
    subscribed=bool(re.search(r'MCMN_SUBSCRIBE_SEND destination=0x[0-9a-f]+ rc=0',text))
    sized=re.search(r'MCMN_SUBSCRIBE_REPLY_SIZE bytes=(\d+)',text)
    replay=replay_bytes(text)
    return {'published':published,'subscription_accepted':subscribed,
            'state_bytes':int(sized.group(1)) if sized else None,
            'replay_hex':replay.hex() if replay else None,
            'replay_matches_sent':replay==bytes(packet) if replay else False}


def verify_helper(runtime):
    manifest=json.loads((runtime/'analysis/full-system.json').read_text())
    program=runtime/'analysis/root/simulation/mcmn-query'
    if not program.is_file():raise SystemExit('Rebuild the runtime: /simulation/mcmn-query missing')
    if manifest.get('mcmn_query_source_sha256')!=hashlib.sha256((HERE/'mcmn-query.c').read_bytes()).hexdigest():
        raise SystemExit('Rebuild the runtime: mcmn-query.c changed since it was built')
    if manifest.get('mcmn_query_program_sha256')!=hashlib.sha256(program.read_bytes()).hexdigest():
        raise SystemExit('Rebuild the runtime: mcmn-query program identity differs')
    return manifest['mcmn_query_program_sha256']


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--runtime',type=Path,required=True)
    parser.add_argument('--seconds',type=int,default=680)
    parser.add_argument('--publish-at',type=float,default=505)
    parser.add_argument('--subscribe-at',type=float,default=545)
    parser.add_argument('--packet',default='2,0,0,2,0,2,0',
                        help='the 7-byte state to publish (byte3=enable mask, byte5=RM2 state)')
    args=parser.parse_args();runtime=args.runtime.resolve(strict=True)
    packet=tuple(int(part,0) for part in args.packet.split(','))
    if len(packet)!=7 or packet[0]!=2:parser.error('packet must be 7 bytes with byte0==2')
    helper_sha256=verify_helper(runtime)
    configure=runpy.run_path(str(HERE/'run-camera.py'))['configuration']
    walk=runpy.run_path(str(HERE/'start-official-camera.py'))['first_setup_plan']()
    plan=plan_for(walk,args.publish_at,args.subscribe_at,packet)
    queue=Path(tempfile.mkdtemp(prefix='mcmn-subscribe-',dir=runtime/'analysis'))
    command=[sys.executable,'-B',str(HERE/'run-full-system.py'),'--runtime',str(runtime),
             *configure(queue,args.seconds,True,official=True,key_plan=';'.join(plan)),
             '--bluetooth-policy','original']
    run=None
    with (queue/'runner.log').open('w') as output:
        process=subprocess.Popen(command,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True)
        try:
            for line in process.stdout:
                output.write(line);output.flush();print(line,end='',flush=True)
                if line.startswith('FULLSYSTEM_RUN '):run=Path(line.removeprefix('FULLSYSTEM_RUN ').strip())
            rc=process.wait()
        except BaseException:
            process.terminate();process.wait(timeout=30);raise
        finally:process.stdout.close()
    if run is None:raise SystemExit('no owned run; keep '+str(queue/'runner.log'))
    if run.parent.resolve()!=(runtime/'analysis/runs').resolve():raise ValueError('Foreign run path')
    console=(run/'console.log').read_bytes();text=console.decode(errors='replace')
    result={'schema':'mcmn-subscribe-v1','run':str(run),
            'console_sha256':hashlib.sha256(console).hexdigest(),'returncode':rc,
            'mcmn_query_program_sha256':helper_sha256,
            'sent_hex':bytes(packet).hex(),**verdict(text,packet)}
    out=run/'mcmn-subscribe.json'
    out.write_text(json.dumps(result,indent=2)+'\n')
    print('MCMN_SUBSCRIBE '+str(out))
    print('  published the 7-byte packet:',result['published'])
    print('  subscription accepted:',result['subscription_accepted'])
    print('  replayed state bytes:',result['state_bytes'],'hex:',result['replay_hex'])
    print('  replay matches what we sent:',result['replay_matches_sent'])
    if not result['published'] or not result['subscription_accepted']:
        print('MCMN_SUBSCRIBE_INVALID publish or subscription did not happen')
        return 2
    return 0 if result['replay_matches_sent'] else 1


if __name__=='__main__':raise SystemExit(main())
