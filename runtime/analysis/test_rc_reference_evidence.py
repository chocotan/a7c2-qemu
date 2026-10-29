import json
import pytest
from rc_reference_evidence import capture,operations,verify,verify_after_crash,SIZE


def test_actual_readback_bound_to_source_and_callback_without_capture_claim(tmp_path):
    source=bytes([128])*(1920*1080*5//2)
    (tmp_path/'yc-pixel-readback.bin').write_bytes(source)
    (tmp_path/'yc-pixel-readback.json').write_text(json.dumps(dict(unit_type=0x431,
        physical_address=0x425558000,bytes=len(source))))
    console='\n'.join(f'SONY_RC_DATA engine={engine} src=0x425558000 dst={destination} bytes={SIZE} '
        'source_fnv=c093758771ffc325 output_fnv=c093758771ffc325 '
        'backend=lane-preserving-unity-v1 silicon-packing=unverified'
        for engine,destination in ((1,'0x4f8500000'),(2,'0x453cae000')))
    (tmp_path/'console.log').write_text(console)
    (tmp_path/'runtime-manifest.json').write_text(json.dumps(dict(rc_board_profile=True,gic_loader_handoff=True)))
    events=[dict(kind='resize_submit',original_entry_verified=True,input_address=0x425558000,
        output_address=address) for address in (0x4f8500000,0x453cae000)]
    events.append(dict(kind='resize_complete_callback',original_entry_verified=True,registers=dict(x0=0,x1=0x10002)))
    (tmp_path/'resize-watch-events.jsonl').write_text('\n'.join(map(json.dumps,events))+'\n')
    calls=[]
    def qmp(command,args):
        calls.append((command,args));assert command=='pmemsave' and args['size']==SIZE
        (tmp_path/args['filename'].removeprefix('/out/')).write_bytes(source[:SIZE])
    capture(qmp,tmp_path,console);capture(qmp,tmp_path,console)
    assert len(calls)==2
    proof=verify(tmp_path)
    assert proof['declared_reference_output_readback_verified'] and proof['original_success_callback_observed']
    assert verify_after_crash(tmp_path)['available']
    assert proof['original_submission_identity_verified']
    (tmp_path/'boot-trace.log').write_text(console+'\n')
    damaged_console='non-UTF8 guest log: \ufffd\n'+'\n'.join(console.splitlines()[:1])
    (tmp_path/'console.log').write_text(damaged_console)
    assert verify(tmp_path)['declared_reference_output_readback_verified']
    (tmp_path/'console.log').write_text(console)
    assert not proof['silicon_packing_verified'] and not proof['capture_verified']
    (tmp_path/'rc-output-00.bin').write_bytes(source[:SIZE-1]+b'\0')
    assert not verify(tmp_path)['declared_reference_output_readback_verified']
    (tmp_path/'console.log').write_text(console+'\nInternal error: Oops\n')
    assert not verify(tmp_path)['run_without_observed_exception']


def test_receipt_bounds_and_cap_are_fail_closed():
    text=f'SONY_RC_DATA engine=1 src=0x425558000 dst=0x4f8500000 bytes={SIZE} '
    suffix='source_fnv=c093758771ffc325 output_fnv=c093758771ffc325 backend=lane-preserving-unity-v1 silicon-packing=unverified'
    for invalid in ((text+suffix).replace('bytes=4147200','bytes=1'),
                    (text+suffix).replace('dst=0x4f8500000','dst=0x5fffffff0'),
                    '\n'.join([text+suffix]*7)):
        with pytest.raises(ValueError):operations(invalid)


def test_failure_snapshot_keeps_source_and_complete_output_without_success_claim(tmp_path):
    console=('YCIN_DMM: type=0x431 handle=0x415 addr=0x425558000 len=0x500000\n'
        f'SONY_RC_DATA engine=1 src=0x425558000 dst=0x4f8500000 bytes={SIZE} '
        'source_fnv=c093758771ffc325 output_fnv=c093758771ffc325 '
        'backend=lane-preserving-unity-v1 silicon-packing=unverified\nInternal error: Oops\n')
    calls=[]
    def qmp(command,args):
        calls.append(args);assert command=='pmemsave'
        (tmp_path/args['filename'].removeprefix('/out/')).write_bytes(bytes([128])*args['size'])
    capture(qmp,tmp_path,console)
    assert [c['size'] for c in calls]==[1920*1080*5//2,SIZE]
    assert json.loads((tmp_path/'yc-pixel-readback.json').read_text())['handle']==0x415
    (tmp_path/'console.log').write_text(console)
    (tmp_path/'runtime-manifest.json').write_text(json.dumps(dict(rc_board_profile=True,gic_loader_handoff=True)))
    proof=verify(tmp_path)
    assert not proof['run_without_observed_exception'] and not proof['declared_reference_output_readback_verified']
    assert proof['operations'][0]['declared_byte_operation_readback_verified']


def test_crash_boundary_without_source_is_unavailable_not_a_second_failure(tmp_path):
    (tmp_path/'runtime-manifest.json').write_text(json.dumps(dict(rc_board_profile=True,gic_loader_handoff=True)))
    (tmp_path/'console.log').write_text('Exception> original guest abort\n')
    with pytest.raises(FileNotFoundError):verify(tmp_path)
    proof=verify_after_crash(tmp_path)
    assert not proof['available'] and not proof['run_without_observed_exception']
    assert not proof['declared_reference_output_readback_verified'] and not proof['capture_verified']
