"""Default-off 032d profile and observer admission; no guest or native capture claim."""
import argparse
import ast
import copy
import os
from pathlib import Path
import re
import subprocess
from types import SimpleNamespace
from unittest import mock

import pytest

import backup_profile as backup
from test_backup_profile import (HERE, adf_host_environment, build_fixture,
                                 directory_lease, directory_profile, required)
from language_fonts import FONT_GUEST, FONT_SPECS


def host_environment(tmp_path):
    return {**adf_host_environment(tmp_path),'A7C2_ADF_SET_INPUT':backup.INPUT_PROFILE,
            'A7C2_ADF_SET_OUTPUT':backup.OUTPUT_PROFILE}


def test_output_default_off_host_to_guest_and_export(tmp_path):
    launcher=backup.load_module('output_launcher',HERE/'start-menu.py')
    for natural in (False,True):
        selected=launcher.profile_environment({'MENU_ADF_SET_OUTPUT':backup.OUTPUT_PROFILE},natural_boot=natural)
        assert 'MENU_ADF_SET_OUTPUT' not in selected
    env=host_environment(tmp_path)
    selected=launcher.profile_environment(env,natural_boot=True)
    assert selected['MENU_ADF_SET_OUTPUT']==backup.OUTPUT_PROFILE
    assert selected['MENU_ADF_SET_INPUT']==backup.INPUT_PROFILE
    assert selected['MENU_ADF_PROC_PATH']==backup.ADF_PROFILE
    assert not any(selected.get(name) for name in (*backup.ADF_CONFLICTS,'MENU_USB_NET'))
    assert not any(selected.get(name) for name in ('QEMU_SONY_SA_REFERENCE_COMPLETE','QEMU_SONY_RC'))
    with pytest.raises(ValueError):launcher.profile_environment(env,natural_boot=False)
    tree=ast.parse((HERE/'qemu-menu-probe.py').read_text())
    export=next(n for n in ast.walk(tree) if isinstance(n,ast.If) and
                isinstance(n.test,ast.Name) and n.test.id=='adf_set_output_profile')
    code=compile(ast.Module(body=[export],type_ignores=[]),'<guest-output-export>','exec')
    scope={'adf_set_output_profile':'','setup':[]}
    exec(code,scope)
    assert not scope['setup']
    scope['adf_set_output_profile']=selected['MENU_ADF_SET_OUTPUT']
    exec(code,scope)
    assert scope['setup']==[
        'export MENU_BACKUP_SYNC=virtual-primary-v1',
        'export MENU_UDATE_DISTRIBUTION=virtual-roundtrip-v1',
        'export MENU_DFS_SELECTOR=virtual-selector-v1',
        'export MENU_PIN_CONTROL_MEMORY=1',
        'export MENU_ADF_SET_OUTPUT=virtual-output-nochange-v1',
    ]


def guest_setup(host):
    tree=ast.parse((HERE/'qemu-menu-probe.py').read_text())
    parser_start=next(i for i,n in enumerate(tree.body) if isinstance(n,ast.Assign) and
                      isinstance(n.targets[0],ast.Name) and n.targets[0].id=='parser')
    args_end=next(i for i,n in enumerate(tree.body) if isinstance(n,ast.Assign) and
                  isinstance(n.targets[0],ast.Name) and n.targets[0].id=='args')
    globals_end=next(i for i,n in enumerate(tree.body) if isinstance(n,ast.Assign) and
                     isinstance(n.targets[0],ast.Name) and n.targets[0].id=='base')
    globals_code=ast.Module(body=tree.body[parser_start:args_end]+[
        n for n in tree.body[args_end+1:globals_end] if isinstance(n,ast.Assign)],type_ignores=[])
    setup_body=next(n.body for n in ast.walk(tree) if isinstance(n,ast.With) and
                    any(isinstance(s,ast.Assign) and isinstance(s.targets[0],ast.Name) and
                        s.targets[0].id=='setup' for s in n.body))
    start=next(i for i,n in enumerate(setup_body) if isinstance(n,ast.Assign) and
               isinstance(n.targets[0],ast.Name) and n.targets[0].id=='setup')
    end=next(i for i,n in enumerate(setup_body) if isinstance(n,ast.Expr) and
             isinstance(n.value,ast.Call) and isinstance(n.value.func,ast.Attribute) and
             ast.unparse(n.value.func)=='proc.stdin.write')
    scope={'argparse':argparse,'__doc__':'setup-only regression','os':os,'Path':Path,
           '__file__':str(HERE/'qemu-menu-probe.py'),
           'args':SimpleNamespace(),'manifest':{'qemu_cpu_count':1},'live_fd':False,
           'host_sd_fd':None,'directory_sd_fd':40,'sd_seed':None,
           'FONT_GUEST':FONT_GUEST,'FONT_SPECS':FONT_SPECS,
           'ADF_PROFILE':backup.ADF_PROFILE,'INPUT_PROFILE':backup.INPUT_PROFILE,
           'OUTPUT_PROFILE':backup.OUTPUT_PROFILE,'BB_SET_MODE_PROFILE':backup.BB_SET_MODE_PROFILE,
           'IMAGING_CONNECT_PROFILE':backup.IMAGING_CONNECT_PROFILE,
           'IMAGING_CONTROL_CONNECT_PROFILE':backup.IMAGING_CONTROL_CONNECT_PROFILE,
           'IMAGING_ADF_CONNECT_PROFILE':backup.IMAGING_ADF_CONNECT_PROFILE,
           'INFRABB_VEF_CONNECT_PROFILE':backup.INFRABB_VEF_CONNECT_PROFILE,
           'FULL_INFRABB_VEF_CONTROL_CONNECTION_PROFILE':backup.FULL_INFRABB_VEF_CONTROL_CONNECTION_PROFILE,
           'FULL_VEF_PINMEM_INPUT_CONNECTION_PROFILE':backup.FULL_VEF_PINMEM_INPUT_CONNECTION_PROFILE,
           'FULL_VEF_PINMEM_CONTROL_CONNECTION_PROFILE':backup.FULL_VEF_PINMEM_CONTROL_CONNECTION_PROFILE,
           'FULL_PINMEM_PEER_CONNECTIONS_PROFILE':backup.FULL_PINMEM_PEER_CONNECTIONS_PROFILE,
           'FULL_ADF_HDMI_AUDIO_CONNECTION_PROFILE':backup.FULL_ADF_HDMI_AUDIO_CONNECTION_PROFILE,
           'FULL_PINMEM_HDMI_VIDEO_CONNECTION_PROFILE':backup.FULL_PINMEM_HDMI_VIDEO_CONNECTION_PROFILE,
           'FULL_PINMEM_OSD_CONNECTION_PROFILE':backup.FULL_PINMEM_OSD_CONNECTION_PROFILE,
           'FUNCTIONAL_CAMERA_PROFILE':backup.FUNCTIONAL_CAMERA_PROFILE,
           'FULL_CP302C_NO_TRANSITION_PROFILE':backup.FULL_CP302C_NO_TRANSITION_PROFILE}
    with mock.patch.dict(os.environ,host,clear=True):
        exec(compile(globals_code,'<probe-setup-globals>','exec'),scope)
        scope['args']=scope['parser'].parse_args([
            '--initramfs','--observe','--sony-timers','--load-ipc','--seed-backup',
            '--load-dmm','--dmm-service','--software-gpe','--headless-osd',
            '--native-display','none','--bootin'])
        exec(compile(ast.Module(body=setup_body[start:end],type_ignores=[]),
                     '<complete-guest-setup>','exec'),scope)
    return scope['setup']


def guest_environment(setup):
    # Execute exports only; mounts, modules, self-tests and the firmware launch stay inert.
    exports=[line for line in setup if line.startswith('export ')]
    assert exports
    assert all(re.fullmatch(r'export [A-Za-z_][A-Za-z0-9_]*=[A-Za-z0-9_./:,=-]*',line)
               for line in exports), 'unsafe or compound export in setup fixture'
    result=subprocess.run(['/bin/sh','-eu','-c','\n'.join([*exports,'/usr/bin/env -0'])],
                          env={},check=True,capture_output=True,timeout=5)
    return dict(entry.decode().split('=',1) for entry in result.stdout.split(b'\0') if entry)


@pytest.fixture(scope='module')
def output_host(tmp_path_factory):
    directory=tmp_path_factory.mktemp('output-profile')
    build,_=build_fixture(directory)
    launcher=backup.load_module('output_complete_launcher',HERE/'start-menu.py')
    host=launcher.profile_environment({**host_environment(directory),
        'A7C2_BACKUP_BUILD':str(build),'A7C2_DIRECTORY_SD':str(directory/'card')},natural_boot=True)
    with directory_lease(directory/'card') as lease:
        host.update(directory_profile(HERE,lease,directory/'profiles'))
        host.update(backup.prepare_profile(HERE,host))
    return host


@pytest.fixture(scope='module')
def output_guest(output_host):
    return guest_environment(guest_setup(output_host))


@pytest.fixture(scope='module')
def output_constructor(tmp_path_factory):
    source=(HERE/'menu-observe.c').read_text()
    start=source.index('    const char *output_profile=getenv("MENU_ADF_SET_OUTPUT");')
    end=source.index('    const char *bb_profile=',start)
    directory=tmp_path_factory.mktemp('output-constructor')
    path=directory/'constructor.c'
    path.write_text(r'''
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
static int adf_set_input_enabled,full_adf_set_output_enabled,owner_init_calls,owner_init_rc;
static int same_name(const char *left,const char *right) {return left && right && !strcmp(left,right);}
static int full_adf_set_output_owner_init(void) {owner_init_calls++;return owner_init_rc;}
static void record(const char *tag,const char *text) {printf("%s%s\n",tag,text);}
static void output_constructor(void) {
'''+source[start:end]+r'''
}
int main(int argc,char **argv) {
    if(argc!=3)return 2;
    adf_set_input_enabled=atoi(argv[1]);owner_init_rc=atoi(argv[2]);output_constructor();
    printf("RESULT enabled=%d owner_init=%d\n",full_adf_set_output_enabled,owner_init_calls);
    return 0;
}
''')
    binary=directory/'constructor'
    subprocess.run(['cc','-std=c11','-Wall','-Wextra','-Werror','-pedantic',
                    str(path),'-o',str(binary)],check=True,capture_output=True,text=True,timeout=30)
    def run(env,*,input_enabled=True,owner_rc=0):
        return subprocess.run([str(binary),str(int(input_enabled)),str(owner_rc)],env=env,
                              check=True,capture_output=True,text=True,timeout=5).stdout
    return run


def test_complete_guest_exports_enable_original_constructor(output_host,output_guest,output_constructor):
    assert output_host['MENU_BACKUP_SYNC']==backup.PROFILE
    assert output_host['MENU_ADF_SET_OUTPUT']==backup.OUTPUT_PROFILE
    assert 'A7C2_BACKUP_SYNC' not in output_guest
    assert 'MENU_OBSERVE_SELFTEST' not in output_guest
    log=output_constructor(output_guest)
    assert 'RESULT enabled=1 owner_init=1' in log
    assert ('FULL_ADF_SET_OUTPUT_PROFILE requested='+backup.OUTPUT_PROFILE+
            ' enabled=1 first_missing=none ') in log
    assert 'before_fork=1 ap_consumed=0 capture_verified=0' in log
    setup=guest_setup({k:v for k,v in output_host.items() if k!='MENU_ADF_SET_OUTPUT'})
    default_guest=guest_environment(setup)
    for name in ('MENU_ADF_SET_OUTPUT','MENU_BACKUP_SYNC','MENU_UDATE_DISTRIBUTION',
                 'MENU_DFS_SELECTOR','MENU_PIN_CONTROL_MEMORY'):
        assert name not in default_guest
    assert 'RESULT enabled=0 owner_init=0' in output_constructor(default_guest)


@pytest.mark.parametrize('name',[
    'MENU_BACKUP_SYNC','MENU_CP_BACKGROUND','MENU_UDATE_DISTRIBUTION','MENU_TOUCH_PANEL',
    'MENU_TCIN_DETECT','MENU_DFS_SELECTOR','MENU_AUDIO_BOOT_CONFIG','MENU_PIN_REGISTRY',
    'MENU_PIN_CONTROL_MEMORY','MENU_PIN_CONNECTION',
])
@pytest.mark.parametrize('value',[None,'wrong'])
def test_original_output_constructor_rejects_each_prerequisite(output_guest,output_constructor,name,value):
    env=dict(output_guest)
    if value is None:env.pop(name)
    else:env[name]=value
    log=output_constructor(env)
    assert 'RESULT enabled=0 owner_init=0' in log
    assert ' enabled=0 first_missing='+name+' ' in log


@pytest.mark.parametrize('value',['','0','false','true','01'])
def test_original_output_constructor_requires_exact_boolean_marker(output_guest,output_constructor,value):
    log=output_constructor({**output_guest,'MENU_PIN_CONTROL_MEMORY':value})
    assert 'RESULT enabled=0 owner_init=0' in log
    assert 'first_missing=MENU_PIN_CONTROL_MEMORY ' in log


@pytest.mark.parametrize('change',[
    {'MENU_ADF_SET_OUTPUT':None},{'MENU_ADF_SET_OUTPUT':''},{'MENU_ADF_SET_OUTPUT':'unknown'},
    {'MENU_OBSERVE_SELFTEST':'1'},{'MENU_OBSERVE_SELFTEST':'0'},
])
def test_original_output_constructor_default_off_and_selftest(output_guest,output_constructor,change):
    env=dict(output_guest)
    for name,value in change.items():
        if value is None:env.pop(name)
        else:env[name]=value
    log=output_constructor(env)
    assert 'RESULT enabled=0 owner_init=0' in log
    if env.get('MENU_ADF_SET_OUTPUT') is not None:
        assert ' enabled=0 first_missing=input-profile-or-selftest ' in log


def test_original_output_constructor_requires_input_and_owner(output_guest,output_constructor):
    log=output_constructor(output_guest,input_enabled=False)
    assert 'RESULT enabled=0 owner_init=0' in log
    assert 'first_missing=input-profile-or-selftest ' in log
    log=output_constructor(output_guest,owner_rc=-1021)
    assert 'RESULT enabled=0 owner_init=1' in log
    assert 'FULL_ADF_SET_OUTPUT_FAULT ' in log and 'first_missing=owner-init ' in log


@pytest.mark.parametrize('name,value',[
    ('A7C2_ADF_SET_OUTPUT','unknown'),('A7C2_ADF_SET_INPUT',''),
    ('A7C2_ADF_SET_INPUT','unknown'),('A7C2_ADF_PROC_PATH',''),('A7C2_VEF_PATH',''),
    ('A7C2_DFS_SELECTOR',''),('A7C2_TCIN_DETECT',''),('A7C2_BACKUP_SYNC',''),
    ('A7C2_CP_BACKGROUND',''),('A7C2_UDATE_DISTRIBUTION',''),('A7C2_TOUCH_PANEL',''),
    ('A7C2_BACKUP_BUILD',''),('A7C2_DIRECTORY_SD',''),('SEED_BACKUP','private'),
    ('MENU_USB_NET','1'),('A7C2_NATURAL_IMAGING_PROFILE','1'),('MENU_BB_READY_INJECT','1'),
    ('MENU_YC_INJECT','1'),('MENU_FORCE_SET','1'),
])
def test_output_rejects_missing_chain_or_conflict_before_process(tmp_path,name,value,monkeypatch):
    launcher=backup.load_module('output_bad_launcher',HERE/'start-menu.py')
    driver=backup.load_module('output_bad_driver',HERE/'check-natural-gtk-input.py')
    env={**host_environment(tmp_path),name:value}
    with pytest.raises(ValueError):launcher.profile_environment(env,natural_boot=True)
    argv=['check-natural-gtk-input.py','--new-ui','--firstboot','--export-sd']
    if name!='A7C2_DIRECTORY_SD':argv+=['--host-sd-dir',str(tmp_path)]
    monkeypatch.setattr(driver.sys,'argv',argv)
    monkeypatch.setattr(driver.os,'environ',env)
    with mock.patch.object(driver.subprocess,'Popen',side_effect=AssertionError('must reject before Xvfb')):
        with pytest.raises(ValueError):driver.main()


def test_output_prepare_and_probe_validation_are_pre_vm(tmp_path,monkeypatch):
    launcher=backup.load_module('output_admission_launcher',HERE/'start-menu.py')
    env=launcher.profile_environment(host_environment(tmp_path),natural_boot=True)
    env.update(required(tmp_path),MENU_ADF_SET_OUTPUT=backup.OUTPUT_PROFILE,
               MENU_USB_NET='1',SEED_BACKUP='alllang')
    def no_build(*args):raise AssertionError('invalid output profile reached build/filesystem work')
    monkeypatch.setattr(backup,'validate_build',no_build)
    for name,value in [('MENU_ADF_SET_OUTPUT','wrong'),('MENU_ADF_SET_INPUT',''),
                       ('MENU_ADF_PROC_PATH',''),('A7C2_DIRECTORY_SD_PROFILE','wrong'),
                       *[(key,'') for key in ('MENU_TCIN_DETECT','MENU_DFS_SELECTOR','MENU_VEF_PATH',
                                               'MENU_CP_BACKGROUND','MENU_UDATE_DISTRIBUTION','MENU_TOUCH_PANEL')]]:
        with pytest.raises(ValueError):backup.prepare_profile(HERE,{**env,name:value})
    tree=ast.parse((HERE/'qemu-menu-probe.py').read_text())
    first=next(i for i,n in enumerate(tree.body) if isinstance(n,ast.Assign) and
               isinstance(n.targets[0],ast.Name) and n.targets[0].id=='vef_path_profile')
    last=next(i for i,n in enumerate(tree.body) if isinstance(n,ast.Assign) and
              isinstance(n.targets[0],ast.Name) and n.targets[0].id=='font_option')
    code=compile(ast.Module(body=tree.body[first:last],type_ignores=[]),'<pre-vm-output-profile>','exec')
    def run(values):
        monkeypatch.setattr(os,'environ',values)
        scope={'os':os,'parser':argparse.ArgumentParser(),
               'args':SimpleNamespace(dmm_service=True,sony_timers=True,native_display='none'),
               'dfs_selector':'virtual-selector-v1','ADF_PROFILE':backup.ADF_PROFILE,
               'INPUT_PROFILE':backup.INPUT_PROFILE,'OUTPUT_PROFILE':backup.OUTPUT_PROFILE,
               'ADF_CONFLICTS':backup.ADF_CONFLICTS}
        exec(code,scope)
        return scope
    assert run({})['adf_set_output_profile']==''
    assert run(env)['adf_set_output_profile']==backup.OUTPUT_PROFILE
    for name,value in [('MENU_ADF_SET_OUTPUT','wrong'),('MENU_ADF_SET_INPUT',''),
                       ('MENU_ADF_PROC_PATH',''),('A7C2_DIRECTORY_SD_PROFILE','wrong'),('MENU_AUDIO_BOOT_CONFIG',''),
                       ('SEED_BACKUP','private'),*[(key,'1') for key in backup.ADF_CONFLICTS]]:
        with pytest.raises(SystemExit) as failure:run({**env,name:value})
        assert failure.value.code==2


@pytest.mark.parametrize('profile',['',backup.OUTPUT_PROFILE])
def test_output_manifest_exact_wire_owned_work_and_false_claims(profile):
    fields=backup.adf_set_output_profile_fields(profile)
    selected=bool(profile)
    assert fields['adf_set_output_profile']==(profile or None)
    expected={'request_bytes':26,'request_flags':0,'i2s_hex':'0100010101010000',
              'hdmi_hex':'0000000000000000','completion_scope':'virtualOutputConfigurationNoChange',
              'old_mask':8,'target_mask':8,'prior_avio_stages':3,'prior_source_cache':255,
              'power20':0,'power22':0,'power_owner':'same-Glee','output_owner':'same-Output60',
              'clock_generation':3,'clock_sequence_start':9,'clock_sequence_end':9,
              'clock_period_ns':1000000,'monitor_generation':2,'monitor_notify':2,
              'monitor_format_bytes':20,'monitor_prior_notifies':[1,4],'monitor_control13d':[1,0,0],
              'aip_business_generation':3,'aip_new_b0_commands':1,
              'disable_writes_total':21,'disable_readbacks_total':21,'avio_generation':2,'avio_jobs':1,
              'avio_job_hex':'0000080000000000616f6600','avio_shadow_writes_added':0,
              'completion_order':'new-B0-before-AVIO-NoOp',
              'native_consumption_requires':'original-AP132d-reply-free'}
    for name,value in expected.items():
        actual=fields['adf_set_output_'+name]
        assert type(actual) is type(value if selected else None) and actual==(value if selected else None)
    if selected:
        wire=bytes.fromhex(fields['adf_set_output_request_hex'])
        assert len(wire)==26 and wire[:8]==bytes.fromhex('0d202d031a000180')
        assert wire[8:10]==b'\0\0'
        assert wire[10:18].hex()==expected['i2s_hex'] and wire[18:].hex()==expected['hdmi_hex']
        assert bytes.fromhex(fields['adf_set_output_monitor_format_hex'])==b'\0'*4+wire[10:]
    for name in ('system_sound_snapshot_known','clock_counter_reset','original_cp_executed',
                 'hardware_verified','audio_output_verified','native_frequency_verified',
                 'original_event_identity_verified','pcm_verified','frames_verified',
                 'ap_consumed','native_verified','capture_verified'):
        assert fields['adf_set_output_'+name] is False
    with pytest.raises(ValueError):backup.adf_set_output_profile_fields('wrong')
    source=(HERE/'qemu-menu-probe.py').read_text()
    assert '**adf_set_output_profile_fields(adf_set_output_profile)' in source
    assert 'adf_set_output_profile_fields(adf_set_output_profile).items()' in source


def test_output_actual_identity_requires_every_typed_field_in_both_receipts():
    source=(HERE/'check-natural-gtk-input.py').read_text()
    tree=ast.parse(source)
    main=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='main')
    intent=next(n for n in main.body if isinstance(n,ast.If) and isinstance(n.test,ast.Name) and
                n.test.id=='requested_adf_output' and isinstance(n.body[0],ast.Assign))
    admission=next(n for n in ast.walk(main) if isinstance(n,ast.If) and isinstance(n.test,ast.Name) and
                   n.test.id=='requested_adf_output' and isinstance(n.body[0],ast.Assign) and
                   isinstance(n.body[0].targets[0],ast.Name) and n.body[0].targets[0].id=='expected_adf_output')
    code=compile(ast.Module(body=[intent,admission],type_ignores=[]),'<actual-output-admission>','exec')
    fields=backup.adf_set_output_profile_fields(backup.OUTPUT_PROFILE)
    actual={**fields,'backup_transport':dict(fields),'selected_observer_matches_build':True}
    scope={'requested_adf_output':'','proof':{},'actual':actual,
           'adf_set_output_profile_fields':backup.adf_set_output_profile_fields}
    exec(code,scope)
    assert not scope['proof']
    scope['requested_adf_output']=backup.OUTPUT_PROFILE
    exec(code,scope)
    assert scope['proof']['adf_set_output_intent']==fields
    assert scope['proof']['adf_set_output_admission']==fields
    for section in ('top','transport'):
        for name,value in fields.items():
            changed=copy.deepcopy(actual)
            target=changed if section=='top' else changed['backup_transport']
            target.pop(name)
            scope.update(actual=changed,proof={})
            with pytest.raises(RuntimeError):exec(code,scope)
            target[name]=int(value) if type(value) is bool else (float(value) if type(value) is int else 'wrong')
            scope.update(proof={})
            with pytest.raises(RuntimeError):exec(code,scope)
    scope.update(actual={**actual,'selected_observer_matches_build':False},proof={})
    with pytest.raises(RuntimeError):exec(code,scope)


def test_observer_prior_snapshots_never_take_current_endpoint_mutex(tmp_path):
    source=(HERE/'menu-observe.c').read_text()
    start=source.index('static int tracked_native_reserve_resources(int adf) {')
    end=source.index('    int rc=full_vef_resources_lock();',start)
    guard=source[start:end]+'    return 0;\n}\n'
    assert 'full_bb_set_mode_snapshot' not in guard
    prefix=r'''
#define _GNU_SOURCE
#include <assert.h>
#include <stdio.h>
#include <unistd.h>
#include "adf-set-output-device.h"
#include "adf-set-input-device.h"
#include "functional-still-format.h"
#include "functional-startup-control.h"
static unsigned int functional_still_format_used,functional_startup_control_used;
void functional_still_format_snapshot(struct functional_still_format_snapshot *s) {(void)s;assert(0);}
void functional_startup_control_snapshot(struct functional_startup_control_snapshot *s) {
 (void)s;assert(!"startup-control is disabled in this ADF fixture");
}
static struct full_adf_proc_snapshot proc;
static struct full_adf_set_input_snapshot input;
static struct full_adf_set_output_snapshot output;
static unsigned int input_reads,output_reads;
void full_adf_proc_snapshot(struct full_adf_proc_snapshot *s) {*s=proc;}
void full_adf_set_input_snapshot(struct full_adf_set_input_snapshot *s) {*s=input;input_reads++;}
void full_adf_set_output_snapshot(struct full_adf_set_output_snapshot *s) {*s=output;output_reads++;}
static void record(const char *tag,const char *text) {(void)tag;(void)text;}
'''
    suffix=r'''
int main(void) {
 proc.owner_pid=input.owner_pid=getpid();proc.configured=input.configured=1;
 proc.clean_completion=input.clean_completion=1;proc.ap_consumed=input.ap_consumed=1;
 proc.request_freed=input.request_freed=1;proc.reply_freed=input.reply_freed=1;
 assert(!tracked_native_reserve_resources(2) && !input_reads);
 assert(!tracked_native_reserve_resources(3) && input_reads==1 && !output_reads);
#define REJECT_FLAG(owner,field) owner.field=1;assert(tracked_native_reserve_resources(3)==-1021);owner.field=0
 REJECT_FLAG(proc,busy);REJECT_FLAG(proc,worker_active);REJECT_FLAG(proc,faults);
 REJECT_FLAG(proc,guard_held);REJECT_FLAG(proc,pending_config);REJECT_FLAG(proc,source5_pending);
 REJECT_FLAG(proc,queued_config);REJECT_FLAG(input,busy);REJECT_FLAG(input,worker_active);
 REJECT_FLAG(input,faults);REJECT_FLAG(input,guard_held);REJECT_FLAG(input,pending_config);
 REJECT_FLAG(input,digital_pending);
#define REJECT_MISSING(owner,field) owner.field=0;assert(tracked_native_reserve_resources(3)==-1021);owner.field=1
 REJECT_MISSING(proc,configured);REJECT_MISSING(proc,clean_completion);REJECT_MISSING(proc,ap_consumed);
 REJECT_MISSING(proc,request_freed);REJECT_MISSING(proc,reply_freed);
 REJECT_MISSING(input,configured);REJECT_MISSING(input,clean_completion);REJECT_MISSING(input,ap_consumed);
 REJECT_MISSING(input,request_freed);REJECT_MISSING(input,reply_freed);
#define REJECT_POINTER(owner,field) owner.field=&owner;assert(tracked_native_reserve_resources(3)==-1021);owner.field=0
 REJECT_POINTER(proc,retained_request);REJECT_POINTER(proc,live_reply);
 REJECT_POINTER(proc,retained_reply);REJECT_POINTER(proc,retained_cleanup);
 REJECT_POINTER(input,retained_request);REJECT_POINTER(input,live_reply);
 REJECT_POINTER(input,retained_reply);REJECT_POINTER(input,retained_cleanup);
 proc.owner_pid++;assert(tracked_native_reserve_resources(3)==-1021);proc.owner_pid--;
 input.owner_pid++;assert(tracked_native_reserve_resources(3)==-1021);input.owner_pid--;
 assert(!tracked_native_reserve_resources(3) && !functional_startup_control_used);return 0;
}
'''
    path=tmp_path/'guard.c';path.write_text(prefix+guard+suffix)
    binary=tmp_path/'guard'
    subprocess.run(['cc','-std=c11','-Wall','-Wextra','-Werror','-I',str(HERE/'device-models'),
                    str(path),'-o',str(binary)],check=True,capture_output=True,text=True,timeout=30)
    subprocess.run([str(binary)],check=True,capture_output=True,text=True,timeout=5)
    reserve=source[start:source.index('static unsigned int record_osd_transport',start)]
    assert '(adf<3 || dmm_domain==FULL_VEF_DMM_SPEECH_INITIAL)' in reserve
    assert 'tracked_native_reserve_resources(3)' in reserve
    route=source.index('if (id == FULL_ADF_SET_OUTPUT_INPUT && full_adf_set_output_enabled)')
    dispatch=source.index('full_adf_set_output_dispatch(',route)
    assert route<source.index('full_adf_set_output_snapshot(&outputSnapshot)',route)<dispatch
    assert dispatch<source.index('full_adf_dispatch(id, message, &io, 1, &result)',dispatch)
    assert 'full_adf_set_output_release_reply(id, message, real_free_msg, record, &vdf_result)' in source
    assert 'adf-set-output-device' in (HERE/'build-observers.sh').read_text()
