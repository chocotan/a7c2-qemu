import hashlib
import json
import pytest
from sa_completion_evidence import verify


def test_original_consumer_bytes_bound_to_reference_receipt_not_native_capture(tmp_path):
    source=bytes([128])*4147200;output=bytes([128])*3110400
    sha=lambda data:hashlib.sha256(data).hexdigest()
    (tmp_path/'runtime-manifest.json').write_text(json.dumps(dict(sa_reference_completion=True)))
    (tmp_path/'console.log').write_text('original handler and consumer observed\n')
    (tmp_path/'boot-trace.log').write_text(f'SONY_SA_REFERENCE_DATA src=0x4f8500000 dst=0x4af654000 '
        f'input_bytes=4147200 output_bytes=3110400 input_sha256={sha(source)} output_sha256={sha(output)} '
        'layout=YUYV-vmean-half-up silicon=unverified completion_published=1\n')
    (tmp_path/'rc-output-00.json').write_text(json.dumps(dict(destination=0x4f8500000)))
    (tmp_path/'rc-output-00.bin').write_bytes(source)
    (tmp_path/'sa-consumer-nv12-00.bin').write_bytes(output)
    events=[dict(kind='sa_reference_group0_irq',original_entry_verified=True,engine=2,group=0),
        dict(kind='sa_nv12_consumer',original_entry_verified=True,output_file='sa-consumer-nv12-00.bin',
            output_handle=0x421,output_physical_address=0x4af654000,output_bytes=len(output),output_sha256=sha(output))]
    path=tmp_path/'resize-watch-events.jsonl';path.write_text('\n'.join(map(json.dumps,events)))
    proof=verify(tmp_path)
    assert proof['reference_completion_to_original_consumer_verified']
    assert proof['ordered_irq_consumer_pairs_verified'] and proof['publication_coverage_complete']
    assert not proof['hardware_factor_verified'] and not proof['capture_verified']
    assert not proof['downstream_pixel_consumption_verified']
    value=0xcbf29ce484222325
    for byte in output:value=((value^byte)*0x100000001b3)&0xffffffffffffffff
    readlog=(f'YCIN_NV12_CONSUMED: seq=1 handle=0x421 addr=0x4af654000 bytes=3110400 '
        f'format=0x10 fnv64={value:016x} full_read=1 lifetime=callback-only\n')
    (tmp_path/'console.log').write_text(readlog)
    assert verify(tmp_path)['reference_pixels_consumed_by_diagnostic_receiver_verified']
    (tmp_path/'console.log').write_text(readlog.replace(f'{value:016x}','0000000000000000'))
    assert not verify(tmp_path)['reference_pixels_consumed_by_diagnostic_receiver_verified']
    (tmp_path/'console.log').write_text('original handler and consumer observed\n')
    path.write_text('\n'.join(map(json.dumps,list(reversed(events)))))
    assert not verify(tmp_path)['reference_completion_to_original_consumer_verified']
    path.write_text('\n'.join(map(json.dumps,events)))
    trace=(tmp_path/'boot-trace.log').read_text();(tmp_path/'boot-trace.log').write_text(trace*3)
    partial=verify(tmp_path)
    assert not partial['reference_completion_to_original_consumer_verified'] and not partial['publication_coverage_complete']
    (tmp_path/'boot-trace.log').write_text(trace)
    (tmp_path/'sa-consumer-nv12-00.bin').write_bytes(output[:-1]+b'\0')
    assert not verify(tmp_path)['reference_completion_to_original_consumer_verified']
    events[-1]['output_file']='../outside.bin';path.write_text('\n'.join(map(json.dumps,events)))
    with pytest.raises(ValueError,match='snapshot'):verify(tmp_path)
