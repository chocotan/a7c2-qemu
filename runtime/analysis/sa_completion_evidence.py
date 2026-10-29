"""Experimental completion is distinct from recovered silicon semantics or capture."""
import hashlib
import json
import re
from pathlib import Path

from sa_data_evidence import expected_nv12

DATA=re.compile(r'^SONY_SA_REFERENCE_DATA src=(0x[0-9a-f]+) dst=(0x[0-9a-f]+) '
    r'input_bytes=4147200 output_bytes=3110400 input_sha256=([0-9a-f]{64}) output_sha256=([0-9a-f]{64}) '
    r'layout=YUYV-vmean-half-up silicon=unverified completion_published=1$',re.M)


def verify(run):
    run=Path(run);manifest=json.loads((run/'runtime-manifest.json').read_text())
    trace=(run/'boot-trace.log').read_text(errors='replace')
    records=DATA.findall(trace)
    if len(records)>3:raise ValueError('SA reference completion exceeds the three-frame experiment')
    events=[json.loads(line) for line in (run/'resize-watch-events.jsonl').read_text().splitlines()]
    irqs=[];consumed=[];waiting=[];paired=[];ordered=True
    queued=[event for event in events if event['kind']=='sa_nv12_output_queued' and event.get('original_entry_verified') is True]
    for event in events:
        if event.get('original_entry_verified') is not True:continue
        if event['kind']=='sa_reference_group0_irq':
            if event.get('engine')!=2 or event.get('group')!=0:ordered=False;continue
            waiting.append(len(irqs));irqs.append(event)
        elif event['kind']=='sa_nv12_consumer':
            consumed.append(event)
            if waiting:paired.append((waiting.pop(0),event))
            else:ordered=False;paired.append((None,event))
    if waiting:ordered=False
    reports=[]
    for publication,event in paired:
        name=event['output_file']
        if Path(name).name!=name or event['output_bytes']!=3110400:raise ValueError('Invalid original-consumer snapshot')
        raw=(run/name).read_bytes();digest=hashlib.sha256(raw).hexdigest()
        verified=False;source_hash=None
        record=records[publication] if publication is not None and publication<len(records) else None
        if (record is not None and int(record[1],16)==event['output_physical_address'] and
                record[3]==digest==event['output_sha256']):
            source,_,source_hash,_=record
            for sidecar in run.glob('rc-output-*.json'):
                allocation=json.loads(sidecar.read_text())
                if allocation['destination']!=int(source,16):continue
                source_bytes=sidecar.with_suffix('.bin').read_bytes()
                if hashlib.sha256(source_bytes).hexdigest()==source_hash and raw==expected_nv12(source_bytes):
                    verified=True
        reports.append(dict(output_handle=event['output_handle'],output_physical_address=event['output_physical_address'],
            output_bytes=len(raw),output_sha256=digest,input_sha256=source_hash,
            publication_index=publication,stream_enabled=event.get('stream_enabled'),
            uvc_format=event.get('uvc_format'),
            declared_reference_output_at_original_consumer_verified=verified))
    console=(run/'console.log').read_text(errors='replace')
    received=[]
    for seq,handle,address,size,fmt,digest in re.findall(
        r'YCIN_NV12_CONSUMED: seq=(\d+) handle=(0x[0-9a-f]+) addr=(0x[0-9a-f]+) bytes=(\d+) '
        r'format=(0x[0-9a-f]+) fnv64=([0-9a-f]{16}) full_read=1 lifetime=callback-only',console):
        matches=[event for event in consumed if event['output_handle']==int(handle,16) and
            event['output_physical_address']==int(address,16)]
        matched=False
        if len(matches)==1 and int(size)==3110400 and int(fmt,16)==0x10:
            raw=(run/matches[0]['output_file']).read_bytes();fnv=0xcbf29ce484222325
            for byte in raw:fnv=((fnv^byte)*0x100000001b3)&0xffffffffffffffff
            matched=f'{fnv:016x}'==digest
        received.append(dict(sequence=int(seq),output_handle=int(handle,16),output_physical_address=int(address,16),
            output_bytes=int(size),format=int(fmt,16),full_buffer_readback_fnv_matches_original_consumer=matched))
    receiver_verified=bool(received and [r['sequence'] for r in received]==list(range(1,len(received)+1)) and
        len(received)<=len(reports) and all(r['full_buffer_readback_fnv_matches_original_consumer'] for r in received))
    return dict(reference_completion_profile_selected=manifest.get('sa_reference_completion') is True,
        virtual_completion_protocol='group0 bit0 after RAM conversion/readback; not a recovered hardware factor',
        reference_data_publications=len(records),original_group0_irq_entries=len(irqs),
        original_nv12_consumer_entries=len(consumed),outputs=reports,
        ordered_irq_consumer_pairs_verified=ordered,
        publication_coverage_complete=len(records)==len(irqs)==len(consumed),
        original_nv12_output_queue_entries=len(queued),
        diagnostic_receiver_full_reads=received,
        reference_pixels_consumed_by_diagnostic_receiver_verified=receiver_verified,
        reference_completion_to_original_consumer_verified=bool(manifest.get('sa_reference_completion') is True and
            records and ordered and len(records)==len(irqs)==len(consumed) and reports and
            all(report['declared_reference_output_at_original_consumer_verified'] for report in reports)),
        run_without_observed_exception=not any(token in console for token in ('Exception>','Internal error: Oops')),
        hardware_factor_verified=False,native_sa_isa_execution_verified=False,silicon_packing_verified=False,
        downstream_pixel_consumption_verified=False,capture_verified=False)
