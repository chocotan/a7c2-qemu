#!/usr/bin/env python3
"""Request owned containers, export their bytes, and run the strict UI gate.

The guest snapshot is saved by the original OSD worker before freeing its buffer.
Base64 is only a read-only transport; corruption/interleaving fails validation.
Original console and result.json are never rewritten to make a verdict pass.
"""
import argparse
import base64
import hashlib
import json
from pathlib import Path
import re
import runpy
import secrets
import subprocess
import sys
import tempfile

HERE=Path(__file__).resolve().parent


def request_command(nonce):
    root='/log/qemu/immutable-osd'
    return (f'echo HOSDREQ1 {nonce} >{root}/{nonce}.request && '
            f'busybox chmod 600 {root}/{nonce}.request && '
            f'echo {nonce} >{root}/current.next && busybox chmod 600 {root}/current.next && '
            f'busybox mv {root}/current.next {root}/current.nonce')


CHUNK_BYTES=4096


CHUNK_BYTES=4096
# ceil(639458 / CHUNK_BYTES); the camera has no stat/wc, so the count is fixed.
CHUNK_COUNT=157


def export_command(nonce):
    """Indexed chunks: a raw dump is broken up by concurrent kernel log output,
    so each 4096-byte block is framed on its own line and the container is only
    accepted when every index is present and the FNV in the COMMIT record
    matches the reassembled bytes."""
    return f'''echo OSD_EXPORT_BEGIN_{nonce}
for pass in 1 2
do
for file in /log/qemu/immutable-osd/{nonce}-*.hosd
do
index=0
while [ $index -lt {CHUNK_COUNT} ]
do
block=$(dd if="$file" bs={CHUNK_BYTES} skip=$index count=1 2>/dev/null | /usr/bin/openssl base64 -A)
echo "OSDCHUNK $index $block"
index=$((index+1))
done
break
done
done
echo OSD_EXPORT_END_{nonce}
'''


def export_region(console,nonce,after):
    """Locate the real export payload.

    The serial console echoes the typed command block before executing it, so
    both markers appear twice. Only the trailing pair is output, and it must
    come after the COMMIT record that vouches for the container.
    """
    if isinstance(nonce,str):nonce=nonce.encode()
    begin=console.rindex(b'OSD_EXPORT_BEGIN_'+nonce)
    end=console.rindex(b'OSD_EXPORT_END_'+nonce)
    if not after<begin<end:
        raise ValueError('Export output does not follow the COMMIT record')
    return console[begin:end]


def reassemble(region,size):
    """Strictly rebuild one container from indexed chunk lines.

    A missing, duplicated or short chunk is a failed transfer, never a partial
    snapshot. Integrity is confirmed later against the guest's own COMMIT hash.
    """
    if size<=0:raise ValueError('Invalid size')
    expected=(size+CHUNK_BYTES-1)//CHUNK_BYTES
    if expected!=CHUNK_COUNT:raise ValueError('Chunk count constant is stale')
    # Concurrent kernel output can interrupt a line, leaving a truncated
    # base64 run that still carries the right index. Keep every candidate and
    # require exactly one that decodes to the full expected block, so a damaged
    # copy is discarded rather than silently accepted.
    candidates={}
    for match in re.finditer(rb'OSDCHUNK (\d+) ([A-Za-z0-9+/=]+)',region):
        candidates.setdefault(int(match.group(1)),set()).add(match.group(2))
    missing=[i for i in range(expected) if i not in candidates]
    if missing:raise ValueError('Incomplete transfer; missing chunks '+str(missing[:8]))
    raw=bytearray()
    for index in range(expected):
        want=min(CHUNK_BYTES,size-index*CHUNK_BYTES)
        good=set()
        for payload in candidates[index]:
            try:block=base64.b64decode(payload,validate=True)
            except Exception:continue
            if len(block)==want:good.add(payload)
        if len(good)!=1:
            raise ValueError(f'Chunk {index} has {len(good)} usable copies of {want} bytes')
        raw+=base64.b64decode(next(iter(good)),validate=True)
    raw=bytes(raw)
    if len(raw)!=size:raise ValueError('Reassembled length differs')
    return raw


# The guest helper hashes the container with its own digest field (bytes 40..47)
# read back as zero, so the transfer check must do the same.
HASH_FIELD=slice(40,48)


def fnv1a64(raw):
    value=0xcbf29ce484222325
    for position,byte in enumerate(raw):
        if 40<=position<48:byte=0
        value=((value^byte)*0x100000001b3)&0xffffffffffffffff
    return value


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--runtime',type=Path,required=True)
    args=parser.parse_args();runtime=args.runtime.resolve(strict=True)
    configure=runpy.run_path(str(HERE/'run-camera.py'))['configuration']
    walk=runpy.run_path(str(HERE/'start-official-camera.py'))['first_setup_plan']()
    nonces={'main':secrets.token_hex(16),'menu':secrets.token_hex(16)}
    plan=walk.split(';')
    for when,label,export_at in ((440,'main',449),(451,'menu',454)):
        nonce=nonces[label]
        plan.extend((f'{when}:'+request_command(nonce),f'{export_at}:'+export_command(nonce)))
    plan.sort(key=lambda item:float(item.partition(':')[0]))
    queue=Path(tempfile.mkdtemp(prefix='immutable-osd-input-',dir=runtime/'analysis'))
    command=[sys.executable,'-B',str(HERE/'run-full-system.py'),'--runtime',str(runtime),
             *configure(queue,500,True,official=True,key_plan=';'.join(plan)),
             '--bluetooth-policy','original','--immutable-osd','capture']
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
    if rc or run is None:raise RuntimeError('Owned snapshot experiment failed; retain runner log '+str(queue))
    if run.parent.resolve()!=(runtime/'analysis/runs').resolve():raise ValueError('Foreign run path')
    console=(run/'console.log').read_bytes();result=json.loads((run/'result.json').read_text())
    digest=hashlib.sha256(console).hexdigest()
    if not result.get('terminal_evidence_checked') or result.get('terminal_console_sha256')!=digest:
        raise ValueError('Terminal console binding failed')
    manifest={'schema':'immutable-osd-captures-v1','console_sha256':digest,'frames':{},'errors':[]}
    for label,nonce in nonces.items():
        try:
            commits=list(re.finditer(rb'OSD_IMMUTABLE_COMMIT sequence=(\d+) pixel_source=(\d+) '
                rb'id=(0x[0-9a-f]+) physical=(0x[0-9a-f]+) fnv1a64=([0-9a-f]{16}) '
                rb'size=(\d+) nonce='+nonce.encode()+rb' file=([0-9a-fA-F]+-\d+\.hosd)',console))
            if len(commits)!=1:raise ValueError('Missing unique guest snapshot COMMIT')
            commit=commits[0]
            size=int(commit[6])
            if size!=639458:raise ValueError('Unexpected snapshot size')
            region=export_region(console,nonce,commit.end())
            raw=reassemble(region,size)
            value=fnv1a64(raw)
            if value!=int(commit[5],16):
                raise ValueError('Reassembled hash differs from the guest COMMIT record')
            filename=commit[7].decode()
            if filename!=f'{nonce}-{int(commit[1])}.hosd':raise ValueError('Commit file identity differs')
            with (run/filename).open('xb') as stream:stream.write(raw)
            manifest['frames'][commit[1].decode()]={'snapshot_file':filename,'nonce':nonce,
                'requested_screen':label,'sha256':hashlib.sha256(raw).hexdigest(),
                'guest_fnv1a64':format(value,'016x'),'chunks':(size+CHUNK_BYTES-1)//CHUNK_BYTES,
                'method':'indexed 4096-byte guest export, reassembled and matched to the guest COMMIT hash'}
        except (ValueError,OSError) as error:
            manifest['errors'].append({'screen':label,'nonce':nonce,'error':str(error)})
    (run/'immutable-osd-captures.json').write_text(json.dumps(manifest,indent=2)+'\n')
    proof=runpy.run_path(str(HERE/'verify-shooting-ui.py'))['verify']
    try:verdict=proof(run)
    except (ValueError,OSError,KeyError,TypeError) as error:
        verdict={'shooting_ui_drawn_verified':False,'error':str(error),'camera_startup_verified':False}
    verdict['schema']='immutable-content-epoch-v1'
    (run/'shooting-ui-proof-immutable.json').write_text(json.dumps(verdict,indent=2)+'\n')
    print('IMMUTABLE_OSD_PROOF '+str(run/'shooting-ui-proof-immutable.json'),flush=True)
    return 0 if not manifest['errors'] and verdict.get('shooting_ui_drawn_verified') else 1


if __name__=='__main__':raise SystemExit(main())
