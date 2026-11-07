"""Self-owned mock callbacks only; original camera evidence stays separate."""
from pathlib import Path
import os
import subprocess
import sys
import pytest

HERE=Path(__file__).resolve().parent
NATIVE=HERE.parents[1]
HEADER=NATIVE/'source/build/qemu-SRBXNK/qemu-11.1.2/include/plugins/qemu-plugin.h'
sys.path.insert(0,str(HERE))
import writer_record_trace as trace

FAULTS={17,18,19,20,21,22,23,25,26,98,99,103,104,141,142,144,145,146,147,148,151,
        238,239,242,243,*range(244,256),258,259,260,263}
SCENARIOS=(*range(154),*range(200,265))


def checked(command,**kwargs):
    result=subprocess.run(command,capture_output=True,timeout=30,**kwargs)
    assert result.returncode==0,result.stdout.decode(errors='replace')+result.stderr.decode(errors='replace')
    return result


@pytest.fixture(scope='session',params=(False,True),ids=('strict-C11','ASan-UBSan'))
def executable(tmp_path_factory,request):
    folder=tmp_path_factory.mktemp('record-host-'+str(request.param));binary=folder/'check-record'
    flags=subprocess.check_output(['pkg-config','--cflags','--libs','glib-2.0'],text=True).split()
    command=['cc','-std=c11','-Wall','-Wextra','-Werror','-pedantic','-DHOST_MOCK','-I'+str(HEADER.parent),
             str(HERE/'test-writer.c'),'-o',str(binary),*flags]
    if request.param:command[1:1]=['-fsanitize=address,undefined','-fno-omit-frame-pointer','-g']
    checked(command);return binary


@pytest.mark.parametrize('scenario',SCENARIOS)
def test_actual_readonly_callbacks_and_strict_consumer(executable,tmp_path,scenario):
    log=tmp_path/'trace.log'
    checked([str(executable),str(scenario),str(log)],env=dict(os.environ,
        ASAN_OPTIONS='detect_leaks=1:halt_on_error=1',UBSAN_OPTIONS='halt_on_error=1'))
    raw=log.read_bytes()
    if scenario in FAULTS:
        with pytest.raises(ValueError):trace.parse_trace(raw)
        return
    result=trace.parse_trace(raw)
    assert all(result[key] is False for key in ('capture_verified','physical_asic_compatibility_verified',
        'AP_identity_verified','invocation_pairing_verified','store_retirement_verified','memory_readback_verified','record_identity_verified'))
    assert [row['observation_sequence'] for row in result['observation_order']]==list(range(1,len(result['observation_order'])+1))
    if 201<=scenario<=237 or scenario in (261,262):assert not result['record_anchor_seen'] and not result['records']
    elif scenario==240:
        assert not result['records'] and list(result['record_filtered_counts'].values())==[1,1,1]
    elif scenario==241:
        assert len(result['records'])==48 and result['truncated_by_quota']
        assert list(result['record_suppressed_counts'].values())==[2,2,2]
    elif scenario>=200:
        assert len(result['records'])==3
        assert all(event['row']==0xa24 for event in result['records'])
        if scenario==264:assert {row['gdb_pc_raw'] for row in trace.prior.fields(raw) if row['kind']=='writer_record'}=={'0x000000550247088c'}
        if scenario==256:assert [row['kind'] for row in result['observation_order']]==['writer_record']*3+['writer_origin']*3+['shutter_writer']*3


@pytest.mark.parametrize('key',sorted(trace.KEYS))
def test_record_missing_fields_and_false_claims_reject_before_use(tmp_path,key):
    root=NATIVE.parents[3]/'analysis/scratch/functional-model-record-observer-draft-20261103'
    rows=trace.prior.fields((root/'actual-api-v2/original/record.log').read_bytes())
    row=next(value for value in rows if value['kind']=='writer_record');del row[key]
    with pytest.raises(ValueError):trace.parse_trace(trace.prior.wire(rows))
