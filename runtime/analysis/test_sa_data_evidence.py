import hashlib
import json
import pytest

from sa_data_evidence import capture,verify,expected_nv12


def test_complete_data_only_readback_keeps_completion_and_capture_false(tmp_path,monkeypatch):
    source=bytes([128])*4147200;output=bytes([128])*3110400
    sha=lambda data:hashlib.sha256(data).hexdigest()
    trace=(f'SONY_SA_REFERENCE_DATA_ONLY src=0x4f8500000 dst=0x4af654000 input_bytes=4147200 '
        f'output_bytes=3110400 input_sha256={sha(source)} output_sha256={sha(output)} '
        'layout=YUYV-vmean-half-up silicon=unverified completion_published=0\n')
    (tmp_path/'boot-trace.log').write_text(trace)
    (tmp_path/'runtime-manifest.json').write_text(json.dumps(dict(sa_reference_data_only=True)))
    calls=[]
    def qmp(command,args):
        calls.append(command);assert command=='pmemsave'
        (tmp_path/args['filename'].removeprefix('/out/')).write_bytes(source if args['size']==4147200 else output)
    capture(qmp,tmp_path);capture(qmp,tmp_path)
    assert calls==['pmemsave','pmemsave']
    monkeypatch.setattr('sa_program_evidence.verify',lambda _:dict(loaded_nv12_program_identity_verified=True))
    monkeypatch.setattr('sa_mmu.verify_committed',lambda _:dict(entries=[{},
        dict(backing_physical_address=0x4f8500000),dict(backing_physical_address=0x4af654000)]))
    proof=verify(tmp_path)
    assert proof['data_only_reference_readback_verified']
    assert not proof['completion_published'] and not proof['capture_verified']
    assert not proof['silicon_packing_verified'] and not proof['native_sa_isa_execution_verified']
    (tmp_path/'sa-nv12-output.bin').write_bytes(output[:-1]+b'\0')
    assert not verify(tmp_path)['data_only_reference_readback_verified']


def test_no_receipt_no_read_and_unknown_layout_never_admitted(tmp_path):
    (tmp_path/'boot-trace.log').write_text('waiting for actual source processing\n')
    def qmp(*args):raise AssertionError('No read without valid data receipt')
    assert capture(qmp,tmp_path) is None
    with pytest.raises(ValueError):expected_nv12(bytes(16))
