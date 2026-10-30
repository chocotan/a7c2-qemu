"""Original replay identity and read-only bounded shutter-route capture."""
import hashlib
import os
from pathlib import Path
import re
import struct
import subprocess

import pytest

BASE = Path(__file__).resolve().parent
SOURCE = (BASE/'menu-observe.c').read_text()


def test_original_replay_and_continuations():
    image = BASE/'menu-root/usr/lib/appFw.so'
    if not image.exists():
        pytest.skip('Original appFw is not distributed')
    raw = image.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == '2ea02f7ecbc5bb917316fe8ef4ce5ffd87eb66efaae78ba2ce11420552df539b'
    for name, address in [('key_return', 0x1794fa8), ('route', 0x1e7a054),
                          ('convert', 0x1792338), ('event', 0x1e79d64)]:
        start = SOURCE.index(f'"shutter_{name}_trampoline:')
        end = SOURCE.index('"    br x16', start)
        block = SOURCE[start:end]
        words = [int(w, 16) for w in re.findall(r'\.inst (0x[0-9a-f]+)', block)]
        assert words == list(struct.unpack_from('<4I', raw, address))
        assert 'PROBE_SAVE_ARGS' in block and 'PROBE_RESTORE_ARGS' in block
        assert f'shutter_{name}_continue=(void *)(base+0x{address+16:x});' in SOURCE
    assert '"SHUTTER_ROUTE"' in SOURCE
    assert 'original bytes differ; no routing probes enabled' in SOURCE
    for name, address in [('canonical', 0x1ac6710), ('target', 0x1ac67d4),
                          ('half', 0x1b3a818), ('release', 0x1aff508),
                          ('full', 0x1b54dc0), ('extra', 0x1b23a6c),
                          ('core', 0x1b54444), ('final', 0x1af16dc),
                          ('send', 0x1af1584), ('call', 0x2688f44),
                          ('wrapper', 0x2688eac), ('execute', 0x2688a08),
                          ('mode0', 0x1b489f4), ('mode1', 0x1b496e8), ('mode2', 0x1b4a000),
                          ('mode_exec', 0x26b8428), ('mode_model', 0x1b25cb0),
                          ('mode_rep', 0x205fcd0), ('mode_scr', 0x209dd68),
                          ('mode_exposure', 0x26cb0ec),
                          ('mode_feature', 0x1b4987c), ('mode_feature_join', 0x1b49a34),
                          ('gate', 0x26c96b0), ('start', 0x26c9534), ('write', 0x25d38d0),
                          ('still', 0x26c8ed4), ('movie', 0x26c91d8),
                          ('request', 0x2489564), ('factory', 0x3274f90), ('run', 0x347618c),
                          ('enqueue', 0x24e9eb4),
                          ('map', 0x1b5a09c), ('lookup', 0x1b6f8f4),
                          ('check', 0x1b76980), ('api_start_ee', 0x26c9848),
                          ('api_forced', 0x26c915c), ('restart_run', 0x3418e58),
                          ('resume_run', 0x30aba88),
                          ('table', 0x248ff44), ('direct', 0x32c6edc),
                          ('still_lower', 0x34cb808), ('movie_lower', 0x34cb948),
                          ('still_send', 0x3546040), ('movie_send', 0x35461e8)]:
        family = ('feature_detail' if name in ('map', 'lookup', 'check') else
                  'ee_sequence' if name in ('request', 'factory', 'run', 'enqueue',
                                            'restart_run', 'resume_run', 'still_lower',
                                            'movie_lower', 'still_send', 'movie_send') else
                  'sequence_create' if name == 'create' else
                  'mode_factory' if name in ('table', 'direct') else
                  'mode_dependency' if name == 'dependency' else
                  'system_mode' if name in ('gate', 'start', 'write', 'still', 'movie',
                                            'api_start_ee', 'api_forced') else
                  'shutter_flow' if name in ('core', 'final', 'send') else
                  'shutter_api' if name in ('call', 'wrapper', 'execute') else
                  'shutter' if name in ('mode0', 'mode1', 'mode2', 'mode_exec', 'mode_model',
                                        'mode_rep', 'mode_scr', 'mode_exposure',
                                        'mode_feature', 'mode_feature_join') else 'shutter_detail')
        start = SOURCE.index(f'"{family}_{name}_trampoline:')
        end = SOURCE.index('"    br x16', start)
        block = SOURCE[start:end]
        words = [int(w, 16) for w in re.findall(r'\.inst (0x[0-9a-f]+)', block)]
        assert words == list(struct.unpack_from('<4I', raw, address))
        assert 'PROBE_SAVE_ARGS' in block and 'PROBE_RESTORE_ARGS' in block
        assert f'{family}_{name}_continue=(void *)(base+0x{address+16:x});' in SOURCE
    assert 'install_shutter_detail_trace(base);' in SOURCE
    start = SOURCE.index('"sequence_create_trampoline:')
    end = SOURCE.index('"    br x16', start)
    block = SOURCE[start:end]
    words = [int(w, 16) for w in re.findall(r'\.inst (0x[0-9a-f]+)', block)]
    assert words == list(struct.unpack_from('<4I', raw, 0x24cc968))
    assert 'PROBE_SAVE_ARGS' in block and 'PROBE_RESTORE_ARGS' in block
    assert 'sequence_create_continue=(void *)(base+0x24cc978);' in SOURCE
    start = SOURCE.index('"mode_dependency_trampoline:')
    end = SOURCE.index('"    br x16', start)
    block = SOURCE[start:end]
    words = [int(w, 16) for w in re.findall(r'\.inst (0x[0-9a-f]+)', block)]
    assert words == list(struct.unpack_from('<4I', raw, 0x303d93c))
    assert 'PROBE_SAVE_ARGS' in block and 'PROBE_RESTORE_ARGS' in block
    assert 'mode_dependency_continue=(void *)(base+0x303d94c);' in SOURCE
    start = SOURCE.index('power_queue_trampoline:\\n')
    end = SOURCE.index('br x16\\n', start)
    block = SOURCE[start:end]
    words = [int(w, 16) for w in re.findall(r'\.inst (0x[0-9a-f]+)', block)]
    assert words == list(struct.unpack_from('<4I', raw, 0x24cba1c))
    assert block.count('PROBE_SAVE_ARGS') == 2
    assert block.count('PROBE_RESTORE_ARGS') == 2
    assert 'power_queue_continue=(void *)(base+0x24cba2cUL);' in SOURCE
    assert 'if(request_queue_probe_armed)return;' in SOURCE


def test_capture_filter_bounds_errno_and_no_writes(tmp_path):
    start = SOURCE.index('void capture_shutter_route(')
    end = SOURCE.index('__asm__(', start)
    capture = SOURCE[start:end]
    assert not re.search(r'\b(?:pwrite|memcpy|memset|osal_\w+)\s*\(', capture)
    harness = r'''
#include <stdio.h>
#include <unistd.h>
#include <fcntl.h>
#include <errno.h>
#include <assert.h>
#include <string.h>
static unsigned records;
static char last[512];
static void record(const char *prefix,const char *line) {
    assert(!strcmp(prefix,"SHUTTER_ROUTE "));
    records++;snprintf(last,sizeof last,"%s",line);
}
''' + capture + r'''
int main(void) {
    unsigned int manager[256]={0},raw[8]={0x1d,0,1,0,0,0,0,0};
    unsigned int copy[8]; memcpy(copy,raw,sizeof raw);
    manager[0x3ac/4]=2;errno=EDOM;
    capture_shutter_route(1,(unsigned long)manager,(unsigned long)raw,1,0);
    assert(errno==EDOM && records==1 && strstr(last,"manager_3ac=2"));
    assert(strstr(last,"flags=0x1/0") && !memcmp(copy,raw,sizeof raw));
    assert(manager[0x3ac/4]==2);
    raw[0]=0x30;capture_shutter_route(1,0,(unsigned long)raw,0,0);assert(records==1);
    capture_shutter_route(1,0,1,0,0);assert(records==1 && errno==EDOM);
    raw[0]=0xf;
    for(unsigned i=0;i<40;i++)capture_shutter_route(1,0,(unsigned long)raw,0,0);
    assert(records==32);
    raw[0]=0;raw[2]=0x02070000;
    capture_shutter_route(3,(unsigned long)manager,(unsigned long)raw,0,0);
    assert(records==33 && strstr(last,"stage=3"));
    raw[2]=0x1234;capture_shutter_route(3,0,(unsigned long)raw,0,0);assert(records==33);
    return 0;
}
'''
    source = tmp_path/'capture.c'
    source.write_text(harness)
    binary = tmp_path/'capture'
    subprocess.run(['clang', '-O1', '-fsanitize=address,undefined', str(source), '-o', str(binary)], check=True)
    subprocess.run([str(binary)], check=True, timeout=15)


def test_detail_filter_target_handler_and_bounds(tmp_path):
    worker_start = SOURCE.index('void capture_mode_worker(unsigned long control) {')
    worker = SOURCE[worker_start:SOURCE.index('void capture_queue_loop(', worker_start)]
    start = SOURCE.index('static int shutter_detail_code(')
    end = SOURCE.index('__asm__(', start)
    capture = SOURCE[start:end]
    assert not re.search(r'\b(?:pwrite|memcpy|memset|osal_\w+)\s*\(', capture)
    harness = r'''
#include <stdio.h>
#include <unistd.h>
#include <fcntl.h>
#include <errno.h>
#include <assert.h>
#include <string.h>
#include <sys/mman.h>
static unsigned records;
static char last[1024];
static unsigned long appfw_base=0x100000UL;
static void record(const char *prefix,const char *line) {
    (void)prefix; records++; snprintf(last,sizeof last,"%s",line);
}
''' + capture + worker + r'''
int main(void) {
    unsigned char frame[64]={0},frame_copy[64];
    unsigned int event[8]={0},event_copy[8],mode_event[8]={0},ee_obj[16]={0},raw=0x02060001;
    unsigned short desc[92]={0};
    unsigned long methods[3]={0,0,appfw_base+0x1234};
    unsigned long vtable=(unsigned long)methods;
    void *globals=mmap((void *)(appfw_base+0x7e40000),0xb0000,
                       PROT_READ|PROT_WRITE,MAP_PRIVATE|MAP_ANONYMOUS|MAP_FIXED,-1,0);
    assert(globals!=MAP_FAILED);
    void *inhibit_page=mmap((void *)(appfw_base+0x8333000),0x1000,
                       PROT_READ|PROT_WRITE,MAP_PRIVATE|MAP_ANONYMOUS|MAP_FIXED,-1,0);
    assert(inhibit_page!=MAP_FAILED);
    *(unsigned char *)(appfw_base+0x83337e3)=0xa5;
    *(unsigned char *)(appfw_base+0x83337e4)=0xfe;
    void *product=mmap((void *)(appfw_base+0x370c000),0x1000,
                       PROT_READ|PROT_WRITE,MAP_PRIVATE|MAP_ANONYMOUS|MAP_FIXED,-1,0);
    void *groups=mmap((void *)(appfw_base+0x3dcf000),0x1000,
                      PROT_READ|PROT_WRITE,MAP_PRIVATE|MAP_ANONYMOUS|MAP_FIXED,-1,0);
    void *index=mmap((void *)(appfw_base+0x5bc3000),0x1000,
                     PROT_READ|PROT_WRITE,MAP_PRIVATE|MAP_ANONYMOUS|MAP_FIXED,-1,0);
    void *sequence_groups=mmap((void *)(appfw_base+0x4c02000),0x1000,
                     PROT_READ|PROT_WRITE,MAP_PRIVATE|MAP_ANONYMOUS|MAP_FIXED,-1,0);
    assert(product!=MAP_FAILED && groups!=MAP_FAILED && index!=MAP_FAILED && sequence_groups!=MAP_FAILED);
    *(unsigned int *)(appfw_base+0x4c020c8+0x2f*4)=0;
    *(unsigned int *)(appfw_base+0x5bc35b0)=16;
    *(unsigned int *)(appfw_base+0x370ce60+16*4)=8;
    *(unsigned char *)(appfw_base+0x3dcf200+7)=10;
    *(unsigned char *)(appfw_base+0x7e4e608)=1;
    *(unsigned int *)(appfw_base+0x7e5c408)=0x11;
    *(unsigned int *)(appfw_base+0x7e5d428)=0x22;
    *(unsigned int *)(appfw_base+0x7e5d498)=0x44;
    *(unsigned int *)(appfw_base+0x7e67700)=0x55;
    *(unsigned int *)(appfw_base+0x7e67fc8)=0x66;
    *(unsigned int *)(appfw_base+0x7e5d570)=0x77;
    *(unsigned int *)(appfw_base+0x7e71f00)=0x33;
    *(unsigned int *)(appfw_base+0x7e71a70)=1;
    *(unsigned int *)(appfw_base+0x7ee4778)=2;
    *(unsigned int *)(appfw_base+0x7ee4750)=3;
    memcpy(frame+44,&raw,sizeof raw); event[3]=0x02070000; event[7]=0x99;
    memcpy(frame_copy,frame,sizeof frame); memcpy(event_copy,event,sizeof event);
    errno=EDOM;
    capture_shutter_detail_dispatch(0x02060000,0x5555,(unsigned long)frame);
    assert(errno==EDOM && records==1 && strstr(last,"canonical=0x2060000"));
    capture_shutter_detail_target((unsigned long)&vtable,(unsigned long)event,
                                  (unsigned long)frame,0x5555);
    assert(errno==EDOM && records==2 && strstr(last,"target_appfw_offset=0x1234"));
    capture_shutter_detail_handler(0x6666,(unsigned long)event,0x1b54dc0);
    assert(errno==EDOM && records==3 && strstr(last,"handler=appFw+0x1b54dc0") && strstr(last,"code=0x2070000"));
    assert(strstr(last,"state_c408=0x11") && strstr(last,"state_d428=0x22") && strstr(last,"state_71f00=0x33"));
    assert(strstr(last,"state_d498=0x44") && strstr(last,"reads=16/4/4/4/4"));
    unsigned int id=0x40a;
    capture_shutter_flow(0,(unsigned long)event,0x111,0x222,0x333);
    assert(records==4 && strstr(last,"site=core") && strstr(last,"code=0x2070000"));
    capture_shutter_flow(1,(unsigned long)(event+7),0,0,0);
    assert(records==5 && strstr(last,"site=final") && strstr(last,"code=0x2070000"));
    assert(strstr(last,"press_local=0x99") && strstr(last,"transition_67fc8=0x66"));
    assert(strstr(last,"inhibit_83337e3=0xa5") && strstr(last,"duplicate_d570=0x77"));
    assert(strstr(last,"gate_reads=4/4/1/4 observation_only=1 atomic_snapshot=0 original_branch_observed=0"));
    assert(errno==EDOM && *(unsigned char *)(appfw_base+0x83337e3)==0xa5);
    assert(*(unsigned char *)(appfw_base+0x83337e4)==0xfe);
    capture_shutter_flow(2,0x555,(unsigned long)&id,0,0);
    assert(records==6 && strstr(last,"site=send") && strstr(last,"id=0x40a"));
    capture_shutter_api(2,1,0,0,0,appfw_base+0x2688f18);
    assert(records==7 && strstr(last,"site=execute") && strstr(last,"option_d498=0x44"));
    assert(strstr(last,"ee_67700=0x55") && strstr(last,"transition_67fc8=0x66"));
    assert(strstr(last,"caller=appFw+0x2688f18"));
    mode_event[3]=0x02240002;
    capture_shutter_mode_model(0x777,(unsigned long)mode_event,appfw_base+0x1b25fa0);
    assert(records==8 && strstr(last,"site=model") && strstr(last,"code=0x2240002"));
    assert(strstr(last,"switch=0x2") && strstr(last,"dial=0x3") && strstr(last,"gate_71a70=0x1"));
    assert(strstr(last,"caller=appFw+0x1b25fa0"));
    capture_shutter_mode_change(2,1,2,3,4,5,6,appfw_base+0x209e468);
    assert(records==9 && strstr(last,"site=exposure") && strstr(last,"a5=0x6"));
    assert(strstr(last,"switch=0x2") && strstr(last,"dial=0x3") && strstr(last,"caller=appFw+0x209e468"));
    capture_shutter_mode_feature(0,1,1,1,(unsigned long)mode_event);
    assert(records==10 && strstr(last,"site=feature_available") && strstr(last,"result=0x1"));
    capture_shutter_mode_feature(1,0,1,1,(unsigned long)mode_event);
    assert(records==11 && strstr(last,"site=feature_or_exec_join") && strstr(last,"prior=0x1"));
    for(unsigned long i=0;i<5;i++)capture_system_mode(i,2,0,appfw_base+0x26c9840);
    assert(records==16 && strstr(last,"site=movie") && strstr(last,"a0=0x2"));
    assert(strstr(last,"system_mode=0x22") && strstr(last,"option=0x44"));
    assert(strstr(last,"caller=appFw+0x26c9840") && strstr(last,"queue_ready=1"));
    unsigned int ee_control[4]={0};ee_control[2]=0x297;
    *(unsigned long *)(ee_obj+2)=(unsigned long)ee_control;
    ee_obj[5]=0x1234;ee_obj[6]=2;ee_obj[8]=0x5678;
    capture_ee_sequence(2,(unsigned long)ee_obj,0,0,0,appfw_base+0x3476200);
    assert(records==17 && strstr(last,"site=run") && strstr(last,"type=0x2"));
    assert(strstr(last,"object_id=0x297") && strstr(last,"argument=0x5678"));
    assert(strstr(last,"queue_ready=1"));
    capture_ee_sequence(3,0,1,0,0,appfw_base+0x25474d0);
    assert(records==18 && strstr(last,"site=enqueue") && strstr(last,"queue_ready=1"));
    assert(strstr(last,"caller=appFw+0x25474d0"));
    *(unsigned int *)desc=0x1531;desc[0x10+10]=1;
    capture_feature_detail(0,0x777,0x8d,appfw_base+0x1b6b3c8);
    assert(records==19 && strstr(last,"site=feature_map") && strstr(last,"feature=0x8d"));
    capture_feature_detail(1,0x777,0x1531,appfw_base+0x1b5a0b8);
    assert(records==20 && strstr(last,"site=feature_lookup") && strstr(last,"feature=0x1531"));
    capture_feature_detail(2,(unsigned long)desc,0,appfw_base+0x1b5ebc8);
    assert(records==21 && strstr(last,"site=feature_check") && strstr(last,"available=1"));
    assert(strstr(last,"desc_id=0x1531") && strstr(last,"product_index=16"));
    assert(strstr(last,"product_id=8") && strstr(last,"group=10"));
    assert(strstr(last,"reads=4/4/1/4/2"));
    capture_feature_detail(0,0x777,0x8e,appfw_base+0x1b6b3c8);
    assert(records==21);
    capture_system_mode(5,0x777,0,appfw_base+0x26c96b0);
    assert(records==22 && strstr(last,"site=api_start_ee") && strstr(last,"queue_ready=1"));
    capture_system_mode(6,0x777,0,appfw_base+0x26c915c);
    assert(records==23 && strstr(last,"site=api_forced") && strstr(last,"ee_67700=0x55"));
    capture_ee_sequence(4,0x777,0,0,0,appfw_base+0x3418e68);
    assert(records==24 && strstr(last,"site=restart_run"));
    capture_ee_sequence(5,0x777,0,0,0,appfw_base+0x30aba98);
    assert(records==25 && strstr(last,"site=resume_run"));
    capture_ee_sequence(6,0x777,0,0,0,appfw_base+0x338ea5c);
    assert(records==26 && strstr(last,"site=still_lower") && strstr(last,"caller=appFw+0x338ea5c"));
    capture_ee_sequence(7,0x777,0,0,0,appfw_base+0x30abaf8);
    assert(records==27 && strstr(last,"site=movie_lower"));
    capture_ee_sequence(8,0x777,0,0,0,appfw_base+0x34cb830);
    assert(records==28 && strstr(last,"site=still_send"));
    capture_ee_sequence(9,0x777,0,0,0,appfw_base+0x34cb970);
    assert(records==29 && strstr(last,"site=movie_send"));
    capture_sequence_create(appfw_base+0x272ffa8);
    assert(records==30 && strstr(last,"caller=appFw+0x272ffa8") && strstr(last,"reads=8"));
    ee_obj[0]=0x2f;
    capture_mode_factory(0,(unsigned long)ee_obj,0,appfw_base+0x24cca04);
    assert(records==31 && strstr(last,"site=table") && strstr(last,"request_id=0x2f"));
    capture_mode_factory(1,0x777,0x2f,appfw_base+0x31a5854);
    assert(records==32 && strstr(last,"site=direct") && strstr(last,"request_id=0x2f"));
    unsigned int dep_obj[16]={0},dep_control[4]={0};
    ee_control[2]=0x2f;dep_control[2]=0x2a;
    *(unsigned long *)(ee_obj+2)=(unsigned long)ee_control;
    *(unsigned long *)(dep_obj+2)=(unsigned long)dep_control;
    capture_mode_dependency((unsigned long)ee_obj,(unsigned long)dep_obj,appfw_base+0x3222b20);
    assert(records==33 && strstr(last,"new_id=0x2f") && strstr(last,"predecessor_id=0x2a"));
    assert(strstr(last,"reads=8/4/8/4") && strstr(last,"caller=appFw+0x3222b20"));
    unsigned char wait_control[0x1b8]={0};unsigned long wait_deps[6]={0};
    *(unsigned int *)(wait_control+8)=0x2f;
    *(unsigned long *)(wait_control+0x1a0)=(unsigned long)wait_deps;
    *(unsigned long *)(wait_control+0x1a8)=(unsigned long)(wait_deps+6);
    *(unsigned int *)((unsigned char *)wait_deps+0x10)=0x2a;
    *(unsigned int *)((unsigned char *)wait_deps+0x28)=0x45;
    capture_mode_worker((unsigned long)wait_control);
    assert(records==34 && strstr(last,"sequence_id=0x2f") && strstr(last,"deps=2"));
    assert(strstr(last,"first_dep=0x2a") && strstr(last,"second_dep=0x45"));
    assert(strstr(last,"reads=4/8/8/4/4"));
    *(unsigned int *)(wait_control+8)=0x83;
    capture_mode_worker((unsigned long)wait_control);
    assert(records==35 && strstr(last,"sequence_id=0x83") && strstr(last,"deps=2"));
    *(unsigned int *)(wait_control+8)=0x2a;
    capture_mode_worker((unsigned long)wait_control);
    assert(records==35);
    unsigned char manager[0x500]={0};
    ee_control[2]=0x2a;
    *(unsigned long *)(manager+0x398)=(unsigned long)ee_obj;
    *(unsigned long *)(manager+0x330)=2;
    *(unsigned int *)(manager+0x318)=0;
    capture_mode_schedule((unsigned long)manager,(unsigned long)ee_obj,0x2f,
                          appfw_base+0x3228cbc);
    assert(records==36 && strstr(last,"sequence_id=0x2f") && strstr(last,"group=0"));
    assert(strstr(last,"current_id=0x2a") && strstr(last,"queued=2") && strstr(last,"stop=0"));
    assert(strstr(last,"reads=4/8/4/8/8/4") && strstr(last,"caller=appFw+0x3228cbc"));
    capture_mode_schedule((unsigned long)manager,(unsigned long)ee_obj,0x2a,
                          appfw_base+0x3228cbc);
    assert(records==36);
    unsigned char clock_obj[0x48]={0};
    ee_control[2]=0x83;
    *(unsigned long *)(clock_obj+8)=(unsigned long)ee_control;
    *(unsigned int *)(clock_obj+0x10)=2;
    *(unsigned int *)(clock_obj+0x44)=1;
    capture_clock_sequence((unsigned long)clock_obj,appfw_base+0x3209e34);
    assert(records==37 && strstr(last,"sequence_id=0x83") && strstr(last,"case=0x2"));
    assert(strstr(last,"flag_44=0x1") && strstr(last,"reads=8/4/4/4"));
    assert(!memcmp(frame,frame_copy,sizeof frame) && !memcmp(event,event_copy,sizeof event));
    raw=0x1234; memcpy(frame+44,&raw,sizeof raw);
    capture_shutter_detail_dispatch(0x1234,0,(unsigned long)frame);
    assert(records==37);
    raw=0x02060000; memcpy(frame+44,&raw,sizeof raw);
    for(unsigned i=0;i<40;i++)capture_shutter_detail_dispatch(raw,0,(unsigned long)frame);
    assert(records==68 && errno==EDOM);
    assert(shutter_detail_mode_code(0x02240002));
    assert(!shutter_detail_mode_code(0x02240007));
    assert(munmap(inhibit_page,0x1000)==0);
    capture_shutter_flow(1,(unsigned long)(event+7),0,0,0);
    assert(records==69 && errno==EDOM && strstr(last,"gate_reads=4/4/-1/4"));
    assert(strstr(last,"inhibit_83337e3=0 ") && strstr(last,"original_branch_observed=0"));
    capture_shutter_flow(0,(unsigned long)event,0,0,0);
    assert(records==70 && strstr(last,"gate_reads=-1/-1/-1/-1"));
    assert(!memcmp(event,event_copy,sizeof event));
    munmap(globals,0xb0000);munmap(product,0x1000);munmap(groups,0x1000);munmap(index,0x1000);
    munmap(sequence_groups,0x1000);
    return 0;
}
'''
    source = tmp_path/'detail.c'
    source.write_text(harness)
    binary = tmp_path/'detail'
    subprocess.run(['clang', '-O1', '-fsanitize=address,undefined', str(source), '-o', str(binary)], check=True)
    subprocess.run([str(binary)], check=True, timeout=15)


def test_sequence_queue_filter_reads_original_request_shape(tmp_path):
    start = SOURCE.index('static unsigned int sequence_queue_observer_enabled;')
    end = SOURCE.index('__asm__(', start)
    capture = SOURCE[start:end]
    assert not re.search(r'\b(?:pwrite|memcpy|memset|osal_\w+)\s*\(', capture)
    harness = r'''
#include <stdio.h>
#include <unistd.h>
#include <fcntl.h>
#include <errno.h>
#include <assert.h>
#include <string.h>
static unsigned records;
static char last[512];
static unsigned long appfw_base=0x100000UL;
static void record(const char *prefix,const char *line) {
    assert(!strcmp(prefix,"SEQUENCE_QUEUE "));
    records++;snprintf(last,sizeof last,"%s",line);
}
''' + capture + r'''
int main(void) {
    unsigned char request_data[0x18]={0};
    unsigned int *requestp=(unsigned int *)request_data,original;
    *requestp=0x2f;
    unsigned long request_slot=(unsigned long)requestp;
    unsigned long *items=&request_slot;
    unsigned long vector=(unsigned long)&items;
    unsigned long holder=(unsigned long)&vector;
    const unsigned char *queue=(const unsigned char *)(appfw_base+0x7e4e5d0);
    unsigned long caller=appfw_base+0x24e9ec4;
    capture_sequence_queue_enter(queue,(const unsigned long *)holder,caller);
    assert(records==0);
    sequence_queue_observer_enabled=1;errno=EDOM;
    capture_sequence_queue_enter(queue,(const unsigned long *)holder,caller);
    assert(records==1 && errno==EDOM && strstr(last,"request_id=0x2f"));
    assert(strstr(last,"reads=8/8/8/4/8/1") && strstr(last,"caller_app=0x24e9ec4"));
    for(unsigned int id=0x12a;id;id=id==0x12a?0x297:(id==0x297?0x2b7:0)) {
        *requestp=id;capture_sequence_queue_enter(queue,(const unsigned long *)holder,caller);
    }
    assert(records==4 && strstr(last,"request_id=0x2b7"));
    original=*requestp=0x123;
    capture_sequence_queue_enter(queue,(const unsigned long *)holder,caller);
    assert(records==4 && *requestp==original);
    capture_sequence_queue_enter(queue,(const unsigned long *)-1,caller);
    assert(records==5 && strstr(last,"site=enqueue_unresolved") && strstr(last,"reads=-1/-1/-1/-1"));
    *requestp=0x2f;
    for(unsigned i=0;i<40;i++)capture_sequence_queue_enter(queue,(const unsigned long *)holder,caller);
    assert(records==33 && errno==EDOM && *requestp==0x2f);
    return 0;
}
'''
    source = tmp_path/'sequence-queue.c'
    source.write_text(harness)
    binary = tmp_path/'sequence-queue'
    subprocess.run(['clang', '-O1', '-fsanitize=address,undefined', str(source), '-o', str(binary)], check=True)
    subprocess.run([str(binary)], check=True, timeout=15)


def test_detail_table_sizes_match_the_probe_count():
    start = SOURCE.index('static void install_shutter_detail_trace(unsigned long base) {')
    end = SOURCE.index('/* Natural startup frontier:', start)
    block = SOURCE[start:end]
    match = re.search(r'const unsigned long offsets\[(\d+)\].*?=\s*\{(.*?)\};', block, re.S)
    assert match
    assert int(match.group(1)) == 49
    assert len(re.findall(r'0x[0-9a-f]+', match.group(2))) == 49
    assert 'const unsigned int expected[49][4]' in block
    assert 'for (unsigned int i=0;i<49;i++)' in block
    assert 'if (selected[46]) install_dep_wait_probe(base);' in block
    assert 'if (selected[47]) arm_entry_probe' in block
    assert 'if (selected[48]) arm_entry_probe' in block


def test_system_mode_records_are_mirrored_to_the_console():
    start = SOURCE.index('static const char *mirrored[]')
    end = SOURCE.index('};', start)
    block = SOURCE[start:end]
    assert '"SYSTEM_MODE "' in block
    assert '"SHUTTER_MODE "' in block
    assert '"EE_SEQUENCE "' in block
    assert '"SEQUENCE_QUEUE "' in block
    assert '"SEQUENCE_CREATE "' in block
    assert '"MODE_FACTORY "' in block
    assert '"MODE_DEPENDENCY "' in block
    assert '"MODE_WORKER "' in block
    assert '"MODE_SCHEDULE "' in block
    assert '"CLOCK_SEQUENCE "' in block


def test_mode_gate_addresses_are_not_low_page_aliases():
    assert 'appfw_base + 0x7eddbc8UL' in SOURCE
    assert 'appfw_base + 0x7e5dbc8UL' not in SOURCE
    assert 'appfw_base + 0x7e5c050UL' in SOURCE
    assert 'appfw_base + 0x7e71a70UL' in SOURCE


def test_gate_is_fail_closed():
    env = {k:v for k,v in os.environ.items() if not k.startswith(('MENU_','A7C2_','QEMU_','SONY_'))}
    result = subprocess.run(['python3', str(BASE/'qemu-menu-probe.py')],
                            env=dict(env, MENU_INPUT_ROUTE_TRACE='2'), capture_output=True, text=True, timeout=10)
    assert result.returncode == 2 and 'MENU_INPUT_ROUTE_TRACE must be 1 or unset' in result.stderr
    probe = (BASE/'qemu-menu-probe.py').read_text()
    assert "'input_route_trace': os.environ.get('MENU_INPUT_ROUTE_TRACE') == '1'" in probe
    assert "setup += ['export MENU_INPUT_ROUTE_TRACE=1']" in probe
    assert 'getenv("MENU_INPUT_ROUTE_TRACE") && !getenv("MENU_OBSERVE_SELFTEST")' in SOURCE
    assert 'if (!mode) return; /* Experimental detail probes are independently opt-in. */' in SOURCE
    assert "'input_route_detail_trace': input_route_detail or None" in probe
    result = subprocess.run(['python3', str(BASE/'qemu-menu-probe.py')],
                            env=dict(env, A7C2_INPUT_ROUTE_DETAIL='target'), capture_output=True, text=True, timeout=10)
    assert result.returncode == 2 and 'requires MENU_INPUT_ROUTE_TRACE=1' in result.stderr
    result = subprocess.run(['python3', str(BASE/'qemu-menu-probe.py'), '--initramfs', '--observe'],
                            env=dict(env, MENU_INPUT_ROUTE_TRACE='1', A7C2_INPUT_ROUTE_DETAIL='receiver'),
                            capture_output=True, text=True, timeout=10)
    assert result.returncode == 2 and 'must be 1, canonical, target, handlers, flow or unset' in result.stderr
    result = subprocess.run(['python3', str(BASE/'qemu-menu-probe.py')],
                            env=dict(env, MENU_UDATE_DISTRIBUTION='bad'), capture_output=True, text=True, timeout=10)
    assert result.returncode == 2 and 'MENU_UDATE_DISTRIBUTION must be virtual-roundtrip-v1 or unset' in result.stderr
    result = subprocess.run(['python3', str(BASE/'qemu-menu-probe.py'), '--initramfs', '--observe'],
                            env=dict(env, MENU_UDATE_DISTRIBUTION='virtual-roundtrip-v1'),
                            capture_output=True, text=True, timeout=10)
    assert result.returncode == 2 and 'requires CP3007' in result.stderr
    result = subprocess.run(['python3', str(BASE/'qemu-menu-probe.py'), '--initramfs', '--observe'],
                            env=dict(env, MENU_CP_BACKGROUND='virtual-mode3-cold-v1',
                                     MENU_UDATE_DISTRIBUTION='virtual-roundtrip-v1', MENU_ASYNC_SEND='1'),
                            capture_output=True, text=True, timeout=10)
    assert result.returncode == 2 and 'no experimental send-GOT hooks' in result.stderr
    result = subprocess.run(['python3', str(BASE/'qemu-menu-probe.py'), '--initramfs', '--observe', '--load-ipc'],
                            env=dict(env, MENU_CP_BACKGROUND='virtual-mode3-cold-v1',
                                     MENU_UDATE_DISTRIBUTION='virtual-roundtrip-v1', MENU_VPANEL='1'),
                            capture_output=True, text=True, timeout=10)
    assert result.returncode == 2 and 'conflicts with the selected public sender owner' in result.stderr
    assert 'NameError' not in result.stderr
    assert "'udate_distribution_original_cp_executed':False" in probe
    assert "'udate_distribution_hardware_ready':False" in probe
