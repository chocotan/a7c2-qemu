"""Read back declared RC reference operations; never claim silicon pixel fidelity."""
import hashlib
import json
from pathlib import Path
import re
import sys

SIZE=1920*1080*2
DATA=re.compile(r'^SONY_RC_DATA engine=([12]) src=(0x[0-9a-f]+) dst=(0x[0-9a-f]+) '
    r'bytes=(\d+) source_fnv=([0-9a-f]{16}) output_fnv=([0-9a-f]{16}) '
    r'backend=lane-preserving-unity-v1 silicon-packing=unverified$',re.M)


def data_log(run,console):
    trace=run/'boot-trace.log'
    text=trace.read_text(errors='replace') if trace.exists() else ''
    return text if DATA.search(text) else console


def operations(console):
    matches=DATA.findall(console.replace('\r\n','\n'))
    if len(matches)>6:raise ValueError('RC reference capture exceeds the three-frame B/C experiment')
    result=[]
    for engine,source,destination,size,before,after in matches:
        source,destination,size=int(source,16),int(destination,16),int(size)
        if (size!=SIZE or before!=after or
                not 0x400000000<=source<=0x600000000-SIZE or
                not 0x400000000<=destination<=0x600000000-SIZE or
                source<destination+SIZE and destination<source+SIZE):
            raise ValueError('Invalid RC reference data receipt')
        result.append(dict(engine=int(engine),source=source,destination=destination,
            bytes=size,source_fnv=before,output_fnv=after))
    return result


def capture(qmp,run,console):
    decoded=operations(data_log(run,console))
    if decoded and not (run/'yc-pixel-readback.bin').exists():
        allocations=re.findall(r'YCIN_DMM: type=0x431 handle=(0x[0-9a-f]+) addr=(0x[0-9a-f]+) len=(0x[0-9a-f]+)',console)
        if len(allocations)!=1:raise ValueError('No unique source allocation for RC failure snapshot')
        handle,address,capacity=(int(value,16) for value in allocations[0])
        storage=1920*1080*5//2
        if (capacity<storage or not 0x400000000<=address<=0x500000000-storage or
                any(operation['source']!=address for operation in decoded)):
            raise ValueError('RC source differs from bounded allocation')
        qmp('pmemsave',dict(val=address,size=storage,filename='/out/yc-pixel-readback.bin'))
        if (run/'yc-pixel-readback.bin').stat().st_size!=storage:raise ValueError('Short failure source readback')
        (run/'yc-pixel-readback.json').write_text(json.dumps(dict(unit_type=0x431,
            handle=handle,physical_address=address,bytes=storage))+'\n')
    for index,operation in enumerate(decoded):
        name=f'rc-output-{index:02d}'
        sidecar=run/(name+'.json')
        if sidecar.exists():
            if json.loads(sidecar.read_text())!=operation:raise ValueError('RC readback identity changed')
            continue
        qmp('pmemsave',dict(val=operation['destination'],size=SIZE,filename='/out/'+name+'.bin'))
        raw=(run/(name+'.bin')).read_bytes()
        if len(raw)!=SIZE:raise ValueError('Short RC output readback')
        sidecar.write_text(json.dumps(operation,indent=2)+'\n')


def verify(run):
    run=Path(run)
    manifest=json.loads((run/'runtime-manifest.json').read_text())
    console=(run/'console.log').read_text(errors='replace')
    source=(run/'yc-pixel-readback.bin').read_bytes()
    if len(source)!=1920*1080*5//2:raise ValueError('Missing complete RDIMG source storage')
    pixel=json.loads((run/'yc-pixel-readback.json').read_text())
    if pixel['unit_type']!=0x431 or pixel['bytes']!=len(source):raise ValueError('Wrong source allocation')
    expected=source[:SIZE]
    fnv=0xcbf29ce484222325
    for byte in expected:fnv=((fnv^byte)*0x100000001b3)&0xffffffffffffffff
    reports=[]
    for index,operation in enumerate(operations(data_log(run,console))):
        sidecar=json.loads((run/f'rc-output-{index:02d}.json').read_text())
        raw=(run/f'rc-output-{index:02d}.bin').read_bytes()
        reports.append(dict(**operation,output_sha256=hashlib.sha256(raw).hexdigest(),
            identity_verified=sidecar==operation and operation['source']==pixel['physical_address'],
            declared_byte_operation_readback_verified=raw==expected and
                operation['source_fnv']==f'{fnv:016x}'))
    events=run/'resize-watch-events.jsonl'
    callbacks=[];submissions=set()
    for line in events.read_text().splitlines() if events.exists() else []:
        event=json.loads(line)
        if event['kind']=='resize_submit' and event.get('original_entry_verified') is True:
            submissions.add((event['input_address'],event['output_address']))
        if event['kind']=='resize_complete_callback' and event.get('original_entry_verified') is True:
            callbacks.append(dict(result=event['registers']['x0']&0xffffffff,
                cookie=event['registers']['x1']&0xffffffff))
    no_exception=not any(token in console for token in ('Exception>','Internal error: Oops','YCIN_INIT_FAILED:'))
    verified=bool(manifest.get('rc_board_profile') is True and manifest.get('gic_loader_handoff') is True and
        reports and {r['engine'] for r in reports}=={1,2} and
        all(r['identity_verified'] and r['declared_byte_operation_readback_verified'] for r in reports))
    return dict(declared_reference_output_readback_verified=verified,operations=reports,
        original_submission_identity_verified=bool(reports) and all(
            (r['source'],r['destination']) in submissions for r in reports),
        original_callback_observations=callbacks,original_success_callback_observed=any(c['result']==0 for c in callbacks),
        run_without_observed_exception=no_exception,silicon_packing_verified=False,
        color_pixels_verified=False,capture_verified=False)


def verify_after_crash(run):
    run=Path(run)
    if not (run/'yc-pixel-readback.bin').exists() or not (run/'yc-pixel-readback.json').exists():
        return dict(available=False,reason='missing bounded RC source readback at crash boundary',
            declared_reference_output_readback_verified=False,original_submission_identity_verified=False,
            original_success_callback_observed=False,run_without_observed_exception=False,
            silicon_packing_verified=False,color_pixels_verified=False,capture_verified=False)
    result=verify(run)
    result['available']=True
    return result


if __name__=='__main__':
    print(json.dumps(verify(Path(sys.argv[1])),indent=2))
