import hashlib
import ast
from pathlib import Path
import struct

import pytest
from sa_job_evidence import capture,request

CONSOLE='\n'.join(f'REGFILE_WR {0xf3170000+offset:#x} = {value:#x}' for offset,value in
    ((0x110,0x1f96f480),(0x114,0x1f96f500),(0x30,0x7d0e0900),(0x60,0),(0,1),(4,1)))


def test_storage_mapping_is_distinct_from_payload_decoding(tmp_path):
    observed=request(CONSOLE.replace('REGFILE_WR 0xf3170030','YC_INJECT_MOD_OKREGFILE_WR 0xf3170030'))
    assert observed['program_entry_physical_address']=='0x47d0e0900'
    assert observed['regions']['program']==dict(physical_address=0x47d0e0000,bytes=8192)
    assert observed['regions']['slot0']==dict(physical_address=0x47e5bd200,bytes=512)
    assert observed['regions']['slot1']==dict(physical_address=0x47e5bd400,bytes=512)
    calls=[]
    def qmp(command,args):
        calls.append((command,args));assert command=='pmemsave'
        (tmp_path/args['filename'].removeprefix('/out/')).write_bytes(bytes([len(calls)])*args['size'])
    result=capture(qmp,tmp_path,CONSOLE)
    assert len(calls)==3 and capture(qmp,tmp_path,CONSOLE)==result and len(calls)==3
    assert not result['payload_address_decoded'] and not result['program_execution_verified']
    assert not result['completion_verified'] and not result['snapshot_consistency_verified']
    (tmp_path/'boot-trace.log').write_text(CONSOLE.replace('REGFILE_WR','SONY_SA_MMIO_WR'))
    assert capture(qmp,tmp_path,'interleaved console missing required words')==result


@pytest.mark.parametrize('console',[CONSOLE.replace('0xf3170060 = 0x0','0xf3170060 = 0x1'),
    CONSOLE.replace('0x1f96f480','0xffffffff'),CONSOLE.replace('0x7d0e0900','0xfffffff0')])
def test_unknown_address_mode_or_cross_window_is_rejected(console):
    with pytest.raises(ValueError):request(console)


def test_no_launch_or_missing_address_is_not_execution():
    assert request(CONSOLE.replace('0xf3170004 = 0x1','0xf3170004 = 0x0')) is None
    with pytest.raises(ValueError):request(CONSOLE.replace('REGFILE_WR 0xf3170030 = 0x7d0e0900',''))


def test_short_dump_does_not_publish_a_completed_readback(tmp_path):
    def qmp(command,args):
        (tmp_path/args['filename'].removeprefix('/out/')).write_bytes(bytes(args['size']-1))
    with pytest.raises(ValueError,match='Short'):capture(qmp,tmp_path,CONSOLE)
    assert not (tmp_path/'sa2-job-readback.json').exists()


def test_actual_settle_loop_captures_launched_job_without_ycstat_timer(tmp_path):
    script=Path(__file__).with_name('qemu-menu-probe.py')
    nodes=[node for node in ast.walk(ast.parse(script.read_text())) if isinstance(node,ast.While)
           and ast.unparse(node.test)=='time.monotonic() < settle_deadline']
    assert len(nodes)==1
    first=nodes[0].body[0]
    assert isinstance(first,ast.If)
    (tmp_path/'console.log').write_text(CONSOLE)
    calls=[]
    def qmp(command,args):
        calls.append(command)
        (tmp_path/args['filename'].removeprefix('/out/')).write_bytes(bytes(args['size']))
    scope=dict(manifest={'rc_board_profile':True,'sa_reference_data_only':False},out=tmp_path,qmp=qmp)
    exec(compile(ast.Module(body=[first],type_ignores=[]),'actual-settle-capture','exec'),scope)
    assert calls==['pmemsave']*3 and (tmp_path/'sa2-job-readback.json').exists()


def test_original_sa_storage_window_tables():
    path=Path(__file__).resolve().parent/'menu-root/system/av-cam.bin'
    if not path.exists():pytest.skip('Original firmware is not distributed')
    raw=path.read_bytes()
    assert hashlib.sha256(raw).hexdigest()=='90343f5f2edc0393ad8809d907cfe648dfd3a82ce0ef39cf06167929d8955096'
    assert struct.unpack_from('<4Q',raw,0x332558)==(0,0x400000000,0xffffffc000000000,0x100000000)
    assert struct.unpack_from('<4Q',raw,0x3325d8)==(0xffffffc000000000,0x400000000,0,0x100000000)
