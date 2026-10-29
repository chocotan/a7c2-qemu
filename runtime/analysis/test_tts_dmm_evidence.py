import struct
import subprocess
from pathlib import Path

import pytest

from tts_dmm_evidence import correlate, decode_table, CP_BASE, SLOT_BYTES


def fixture_table():
    data=bytearray(0x90)
    for index in range(2):
        at=index*0x48
        struct.pack_into('<II',data,at,0x1a+index,0x1000+index)
        struct.pack_into('<IIQQ',data,at+0x18,0x8400+index,SLOT_BYTES,
                         CP_BASE+index*SLOT_BYTES,0x7f10000000+index*SLOT_BYTES)
    return data


def fixture_console(before=None,after=None):
    before=fixture_table() if before is None else before
    after=before if after is None else after
    record=(f'/ # OBS FULL_VEF_RESOURCES_TTS_TABLE pid=258 tid=381 appfw_base=0x7f00000000 '
            f'table_va=0x5f66b08 address=0x7f05f66b08 bytes=144 reads=144/144 '
            f'unchanged=1 atomic_snapshot=0 raw_before={bytes(before).hex()} '
            f'raw_after={bytes(after).hex()} ownership_verified=0\r\n')
    return record+('OBS FULL_VEF_RESOURCES_REFUSED tid=381 accepted=0 dmm_enabled=1 dmm_bound=1 '
        'dmm_slots=1/1 dmm_opens=1/1 dmm_handles=0x8400/0x8401 dmm_generations=1/1 control_bound=1\n')


def test_exact_two_slot_match_does_not_grant_completion_or_release():
    result=correlate(fixture_console())
    assert result['speech_handles_match_live_native_slots']
    assert result['ap_pid']==258 and result['appfw_base']=='0x7f00000000'
    assert correlate(fixture_console().replace('pid=258 ',''))['ap_pid'] is None
    assert [e['id'] for e in result['entries']]==[0x1a,0x1b]
    assert [e['cp_handle'] for e in result['entries']]==[0x8400,0x8401]
    assert not result['atomic_snapshot'] and not result['creator_call_chain_verified']
    assert not result['ap_mapping_verified']
    assert not result['resource_release_authorized'] and not result['vef_path_verified']
    assert not result['capture_verified'] and not result['global_dmm_idle_verified']


@pytest.mark.parametrize('kind',['length','entry-id','handle','duplicate-handle','cp-size','cp-address',
                                  'changed','wrong-tid','slot-retired','open-count','generation','table-address',
                                  'missing-marker','high-bits','zero-generation'])
def test_unknown_or_changed_owner_state_is_rejected(kind):
    before=fixture_table();after=None
    if kind=='length':before=before[:-1]
    if kind=='entry-id':struct.pack_into('<I',before,0x48,0x1a)
    if kind=='handle':struct.pack_into('<I',before,0x18,0x8000)
    if kind=='duplicate-handle':struct.pack_into('<I',before,0x48+0x18,0x8400)
    if kind=='cp-size':struct.pack_into('<I',before,0x1c,SLOT_BYTES-1)
    if kind=='cp-address':struct.pack_into('<Q',before,0x20,CP_BASE+SLOT_BYTES)
    if kind=='changed':after=bytearray(before);after[-1]^=1
    if kind in ('missing-marker','high-bits','zero-generation'):
        value={'missing-marker':0x400,'high-bits':0x10008400,'zero-generation':0x8000}[kind]
        struct.pack_into('<I',before,0x18,value)
    console=fixture_console(before,after)
    if kind in ('missing-marker','high-bits','zero-generation'):
        console=console.replace('dmm_handles=0x8400/',f'dmm_handles={value:#x}/')
        if kind=='zero-generation':console=console.replace('dmm_generations=1/1','dmm_generations=0/1')
    if kind=='wrong-tid':console=console.replace('REFUSED tid=381','REFUSED tid=382')
    if kind=='slot-retired':console=console.replace('dmm_slots=1/1','dmm_slots=0/1')
    if kind=='open-count':console=console.replace('dmm_opens=1/1','dmm_opens=2/1')
    if kind=='generation':console=console.replace('dmm_generations=1/1','dmm_generations=2/1')
    if kind=='table-address':console=console.replace('address=0x7f05f66b08','address=0x7f05f66b10')
    with pytest.raises(ValueError):correlate(console)




def test_missing_or_duplicated_readback_is_not_evidence():
    with pytest.raises(ValueError):correlate('')
    with pytest.raises(ValueError):correlate(fixture_console()+fixture_console())
    with pytest.raises(ValueError):decode_table(bytes(0x90))


@pytest.fixture(scope='module')
def record_binary(tmp_path_factory):
    directory=tmp_path_factory.mktemp('actual-observer-record')
    source=(Path(__file__).resolve().parent/'menu-observe.c').read_text()
    start=source.index('static void record(const char *prefix, const char *name) {')
    helper=source[start:source.index('\nvoid *dlopen(',start)]
    fixture=r'''
#include <assert.h>
#include <fcntl.h>
#include <stdio.h>
#include <string.h>
#include <unistd.h>
static unsigned char *memory_log;
static int fake_open(const char *path,int flags,...) {
    assert(!strcmp(path,"/dev/console") && flags==1);return 77;
}
static long fake_write(int fd,const void *data,unsigned long count) {
    assert(fd==77 && fwrite(data,1,count,stdout)==count);return (long)count;
}
#define open fake_open
#define write fake_write
#define MENU_OBSERVE_TRANSPORT_SELFTEST 1
'''
    main=r'''
int main(int argc,char **argv) {
    assert(argc==1 || argc==2);
    char body[8192];size_t count=fread(body,1,sizeof(body)-1,stdin);
    assert(count<sizeof(body)-1);body[count]=0;
    record(argc==2?argv[1]:"FULL_VEF_RESOURCES_TTS_TABLE ",body);
    record("DMM_SERVICE ","following=1");return 0;
}
'''
    path=directory/'record.c';path.write_text(fixture+helper+main)
    binary=directory/'record'
    built=subprocess.run(['cc','-std=c11','-Wall','-Wextra','-Werror',str(path),'-o',str(binary)],
                         capture_output=True,text=True,timeout=20)
    assert built.returncode==0,built.stdout+built.stderr
    return binary


def test_actual_console_formatting_retains_complete_tts_evidence(record_binary):
    console=fixture_console();line,pool=console.split('\r\n',1)
    body=line.removeprefix('/ # OBS FULL_VEF_RESOURCES_TTS_TABLE ')
    result=subprocess.run([str(record_binary)],input=body,capture_output=True,text=True,timeout=5)
    assert result.returncode==0,result.stdout+result.stderr
    assert len(result.stdout.splitlines(keepends=True)[0])>768
    assert result.stdout.splitlines()[0].endswith('ownership_verified=0')
    assert result.stdout.splitlines()[1]=='OBS DMM_SERVICE following=1'
    assert correlate(result.stdout+pool)['speech_handles_match_live_native_slots']


def test_actual_truncated_console_record_preserves_next_line(record_binary):
    line=fixture_console().split('\r\n',1)[0]
    body=line.removeprefix('/ # OBS FULL_VEF_RESOURCES_TTS_TABLE ')+' extra='+'Z'*6000
    result=subprocess.run([str(record_binary)],input=body,capture_output=True,text=True,timeout=5)
    assert result.returncode==0,result.stdout+result.stderr
    lines=result.stdout.splitlines(keepends=True)
    assert len(lines)==2 and lines[0].endswith('\n')
    assert len(lines[0])<len(body) and lines[1]=='OBS DMM_SERVICE following=1\n'
    with pytest.raises(ValueError):correlate(result.stdout)


@pytest.mark.parametrize('prefix', ['FUNCTIONAL_JPEG_CODEC ', 'FUNCTIONAL_MPR_PI ',
                                  'FUNCTIONAL_CAMERA_CONTROL_AP_FREE '])
def test_actual_functional_content_receipt_is_not_truncated(record_binary, prefix):
    body = 'request_hex=' + 'ab' * 104 + ' trace=' + 'Z' * 1900 + ' native_done=1'
    result = subprocess.run([str(record_binary), prefix], input=body,
                            capture_output=True, text=True, timeout=5)
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.splitlines() == ['OBS ' + prefix + body, 'OBS DMM_SERVICE following=1']


def initial_creation_console():
    wire=bytearray(40);struct.pack_into('<H',wire,0,0x20)
    struct.pack_into('<I',wire,4,0x63a);struct.pack_into('<H',wire,22,1)
    base=0x7f00000000;expected=(0x35522a4,0x35527b4,0x34d3614,0x17b2c08)
    lines=[]
    for index in range(2):
        sample=index+1
        lines.append(f'OBS DMM_REQUEST tid=343 op=0x20 unit=0x63a handle=0 option=0x1 source=0x81cf61c3 bytes=40 sampled=40 raw={wire.hex()}')
        for depth,offset in enumerate(expected):
            lines.append(f'OBS DMM_ALLOC_FRAME sample={sample} tid=343 depth={depth} fp={0x7fff1000+depth*16:#x} lr={base+offset:#x} appFw_offset={offset:#x} in_appFw=1 caller_matches=1 frame_candidate_only=1')
        lines.append(f'OBS DMM_ALLOC_CREATOR sample={sample} tid=343 frames=4 caller_matches=1 creator_kind=1 gate_admission_unchanged=1')
        lines.append(f'OBS DMM_SERVICE pid=258 tid=343 source=0x81cf61c3 op=0x20 transport=0 status=0 handle={0x8400+index:#x} address={CP_BASE+index*SLOT_BYTES:#x} size=0x80000 slots=1/{index} opens=1/{index} caller=/usr/lib/appFw.so+0x35522a4 caller_raw={base+expected[0]:#x} sample={sample} creator_kind=1 allocation_count={sample} lifecycle_changed=0 slot_epochs='+('1/0' if index==0 else '1/2')+' slot_creators='+('1/0' if index==0 else '1/1'))
    table=fixture_console().replace('dmm_generations=1/1 ',
        'dmm_generations=1/1 dmm_epochs=1/2 dmm_creators=1/1 dmm_allocation_count=2 dmm_lifecycle_changed=0 ')
    return '\n'.join(lines)+'\n'+table


def test_full_initial_provenance_requires_more_than_table_matching():
    from tts_dmm_evidence import prove_initial_creation
    proof=prove_initial_creation(initial_creation_console())
    assert proof['creator_call_chain_verified'] and proof['initial_speech_lifecycle_verified']
    assert not proof['resource_release_authorized'] and not proof['vef_path_verified']
    assert not proof['ap_mapping_verified'] and not proof['capture_verified']
    assert correlate(fixture_console())['speech_handles_match_live_native_slots']
    with pytest.raises(ValueError):prove_initial_creation(fixture_console())


@pytest.mark.parametrize('kind',['unknown-producer','reinit','missing-frame','unbounded-summary','wrong-pid',
    'caller-mismatch','request-missing','request-unit','epoch-reused','ref-history','ref-roundtrip','unknown-slot',
    'table-changed','backward-frame','source-missing','post-slot-mismatch','second-request-missing'])
def test_creation_or_lifecycle_uncertainty_cannot_grant_speech_exclusion(kind):
    from tts_dmm_evidence import prove_initial_creation
    text=initial_creation_console()
    if kind=='unknown-producer':text=text.replace('creator_kind=1','creator_kind=0',1)
    if kind=='reinit':text=text.replace('appFw_offset=0x17b2c08','appFw_offset=0x17b07e4',1)
    if kind=='missing-frame':text='\n'.join(l for l in text.splitlines() if not ('DMM_ALLOC_FRAME sample=1' in l and 'depth=2 ' in l))+'\n'
    if kind=='unbounded-summary':text=text.replace('frames=4','frames=9',1)
    if kind=='wrong-pid':text=text.replace('DMM_SERVICE pid=258','DMM_SERVICE pid=259',1)
    if kind=='caller-mismatch':text=text.replace('caller_raw=0x7f035522a4','caller_raw=0x7f035522a8',1)
    if kind=='request-missing':text='\n'.join(l for l in text.splitlines() if 'DMM_REQUEST' not in l)+'\n'
    if kind=='second-request-missing':
        lines=text.splitlines(keepends=True);seen=0
        for index,line in enumerate(lines):
            if line.startswith('OBS DMM_REQUEST '):
                seen+=1
                if seen==2:lines[index]='';break
        text=''.join(lines)
    if kind=='request-unit':
        old=bytearray(40);struct.pack_into('<H',old,0,0x20);struct.pack_into('<I',old,4,0x63a);struct.pack_into('<H',old,22,1)
        bad=bytearray(old);struct.pack_into('<I',bad,4,0x62a);text=text.replace(old.hex(),bad.hex(),1)
    if kind=='epoch-reused':text=text.replace('dmm_allocation_count=2','dmm_allocation_count=33')
    if kind=='ref-history':text=text.replace('dmm_lifecycle_changed=0','dmm_lifecycle_changed=1')
    if kind=='ref-roundtrip':
        extra='OBS DMM_SERVICE op=0x21 status=0 transport=0 allocation_count=2 lifecycle_changed=0\nOBS DMM_SERVICE op=0x22 status=0 transport=0 allocation_count=2 lifecycle_changed=0\n'
        text=text.replace('/ # OBS FULL_VEF_RESOURCES_TTS_TABLE',extra+'/ # OBS FULL_VEF_RESOURCES_TTS_TABLE')
    if kind=='unknown-slot':text=text.replace('dmm_creators=1/1','dmm_creators=0/1')
    if kind=='table-changed':text=text.replace('unchanged=1','unchanged=0')
    if kind=='backward-frame':text=text.replace('fp=0x7fff1010','fp=0x7fff1000',1)
    if kind=='source-missing':text=text.replace('source=0x81cf61c3 ','')
    if kind=='post-slot-mismatch':text=text.replace('slots=1/0 opens=1/0','slots=0/0 opens=1/0',1)
    with pytest.raises(ValueError):prove_initial_creation(text)
