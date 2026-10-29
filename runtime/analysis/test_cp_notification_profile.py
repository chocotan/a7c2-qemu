"""Finite virtual CP4073 mode0 host admission; no native/hardware completion claim."""
import ast
import copy
import json
import os
from pathlib import Path
import re
from unittest import mock

import pytest

import backup_profile as backup
from test_backup_profile import HERE, build_fixture, directory_lease, directory_profile
from test_bb_set_mode_profile import clean_guest_environment, guard_scope, load_script, menu_probe_setup
from test_cp302c_diagnostic_profile import diagnostic_guard, host_environment as diagnostic_environment
from test_cp302c_no_transition_profile import cp302c_guard
from test_final_graph_connections_profile import FAMILIES as FINAL_FAMILIES, final_guard_code
from test_native_graph_batch_profile import FAMILIES, OLD_PROFILES, batch_guard_code

PROFILE=backup.FULL_CP_NOTIFICATION_CONTROL_PROFILE
HOST='A7C2_CP_NOTIFICATION_CONTROL'
GUEST='MENU_CP_NOTIFICATION_CONTROL'
PREFIX='cp_notification_control_'
CLAIMS={
    'mode_change_0_or_2_supported','mode1_2040_supported',
    'original_CP_executed','original_CP_RAM_verified','current_known','history_known',
    'native_verified','runtime_verified','transport_verified','original_AP_consumed',
    'd018_native_consumption','d018_runtime_verified','ignored_reply_byte1_known',
    'mode_transition_verified','EE_verified','hardware_ready','frames_verified','capture_verified',
}


def host_environment(tmp_path,build=None,enabled=True):
    env=diagnostic_environment(tmp_path,build)
    if enabled:env[HOST]=PROFILE
    return env


def selected_host(tmp_path,build=None,enabled=True):
    launcher=load_script('cp_notification_launcher','start-menu.py')
    host=launcher.profile_environment(host_environment(tmp_path,build,enabled),natural_boot=True)
    host.update(MENU_BACKUP_SYNC=backup.PROFILE,SEED_BACKUP='alllang',
                A7C2_DIRECTORY_SD_PROFILE='directory-vvfat-256gb-v1')
    return host


def probe_tree():
    return ast.parse((HERE/'qemu-menu-probe.py').read_text())


def notification_guard():
    return next(node for node in probe_tree().body if isinstance(node,ast.If) and any(
        isinstance(call,ast.Call) and isinstance(call.func,ast.Attribute) and
        ast.unparse(call.func)=='parser.error' and call.args and isinstance(call.args[0],ast.Constant) and
        str(call.args[0].value).startswith('CP notification control requires') for call in ast.walk(node)))


def test_finite_typed_intent_and_header_identity_never_promote_runtime_claims():
    assert PROFILE=='virtual-cp-notification-mode0-v1'
    header=(HERE/'device-models/cp-notification-control.h').read_text()
    assert re.search(r'^#define FULL_CP_NOTIFICATION_MODE0_PROFILE "'+re.escape(PROFILE)+r'"$',header,re.M)
    fields=backup.cp_notification_control_profile_fields(PROFILE)
    off=backup.cp_notification_control_profile_fields('')
    assert fields.keys()==off.keys() and all(key.startswith(PREFIX) for key in fields)
    for key,value in off.items():
        assert value is (False if key[len(PREFIX):] in CLAIMS else None)
    for name in CLAIMS:assert fields[PREFIX+name] is False
    expected={
        'profile':PROFILE,'request_type':5,'request_command':0x4073,'request_bytes':12,
        'response_type':1,'response_command':0x4073,'response_bytes':12,
        'response_status':0xf000,'AP_result':0,'AP_source':0x80020002,'source_owner':0x90030001,
        'mode':0,'old_mode':0,'initial_notification_mode':0,
        'notification_mode_policy':'explicit-virtual-owned-mode0-not-original-CP-RAM',
        'current':None,'history':None,'predecessor_diagnostic_profile':backup.FULL_CP302C_DIAGNOSTIC_PROFILE,
        'predecessor_connection_count':13,
        'predecessor_policy':'actual-diagnostic-302c-original-AP-reply-free-and-all-13-clean-in-C',
        'd018_command':0xd018,'d018_source':0x90030001,'d018_destination':0x90040193,'d018_bytes':12,
        'd018_sticky_modeled':True,'d013_registered':False,
        'd018_completion_policy':'finite-virtual-consumer-sticky-readback-before-4073-ACK',
    }
    for name,value in expected.items():
        assert type(fields[PREFIX+name]) is type(value)
        assert json.dumps(fields[PREFIX+name])==json.dumps(value)
    for value in ('1','true','unknown',PROFILE+' ',backup.FULL_CP302C_DIAGNOSTIC_PROFILE,None,True,1):
        with pytest.raises(ValueError):backup.cp_notification_control_profile_fields(value)


def test_launcher_default_off_exact_pair_and_real_clean_guest_export(tmp_path):
    launcher=load_script('cp_notification_default','start-menu.py')
    for env in ({},host_environment(tmp_path,enabled=False)):
        assert GUEST not in launcher.profile_environment(env,natural_boot=True)
    host=selected_host(tmp_path)
    setup=menu_probe_setup(host);guest=clean_guest_environment(setup)
    assert host[HOST]==host[GUEST]==guest[GUEST]==PROFILE and HOST not in guest
    assert setup.count('export '+GUEST+'='+PROFILE)==1
    assert guest['MENU_CP302C_DIAGNOSTIC']==backup.FULL_CP302C_DIAGNOSTIC_PROFILE
    paired=host_environment(tmp_path);paired[GUEST]=PROFILE
    assert launcher.profile_environment(paired,natural_boot=True)[GUEST]==PROFILE
    assert not list(tmp_path.iterdir())


def test_launcher_dependency_closure_missing_diagnostic_unknown_mismatch_strict_and_direct_boot(tmp_path):
    launcher=load_script('cp_notification_reject','start-menu.py')
    host=host_environment(tmp_path)
    with pytest.raises(ValueError):launcher.profile_environment(host,natural_boot=False)
    for key in ('A7C2_CP302C_DIAGNOSTIC','A7C2_CP_BACKGROUND',
                'A7C2_VEF_PINMEM_CONTROL_CONNECT','A7C2_PINMEM_OSD_CONNECT'):
        bad=dict(host);bad.pop(key)
        with pytest.raises(ValueError):launcher.profile_environment(bad,natural_boot=True)
    for key,value in (
        *((key,value) for key in (HOST,GUEST) for value in ('1','true','unknown',PROFILE+' ',None,True,1)),
        ('MENU_CP302C_DIAGNOSTIC','unknown'),
        ('A7C2_CP302C_NO_TRANSITION',backup.FULL_CP302C_NO_TRANSITION_PROFILE),
        ('MENU_CP302C_NO_TRANSITION',backup.FULL_CP302C_NO_TRANSITION_PROFILE)):
        with pytest.raises(ValueError):launcher.profile_environment({**host,key:value},natural_boot=True)
    with pytest.raises(ValueError):launcher.profile_environment({GUEST:PROFILE},natural_boot=True)
    assert not list(tmp_path.iterdir())


def test_real_setup_uses_diagnostic_export_closure_and_suppresses_forged_pairs(tmp_path):
    host=selected_host(tmp_path)
    for key in (HOST,GUEST,'A7C2_CP302C_DIAGNOSTIC','MENU_CP302C_DIAGNOSTIC',
                'MENU_CP_BACKGROUND','MENU_BB_SET_MODE','A7C2_PINMEM_PEER_CONNECT','MENU_PINMEM_OSD_CONNECT'):
        bad=dict(host);bad.pop(key)
        assert GUEST not in clean_guest_environment(menu_probe_setup(bad)),key
    for key in (HOST,GUEST):
        for value in ('1','true','unknown',PROFILE+' '):
            assert GUEST not in clean_guest_environment(menu_probe_setup({**host,key:value}))
    for key in ('A7C2_CP302C_NO_TRANSITION','MENU_CP302C_NO_TRANSITION'):
        assert GUEST not in clean_guest_environment(menu_probe_setup(
            {**host,key:backup.FULL_CP302C_NO_TRANSITION_PROFILE}))


def test_actual_cli_guard_composition_requires_the_validated_diagnostic_chain(tmp_path):
    profiles={**OLD_PROFILES,**{name:profile for name,_,profile in FAMILIES},
              **{name:profile for name,_,profile,_ in FINAL_FAMILIES},
              'cp302c_no_transition':'','cp302c_diagnostic':backup.FULL_CP302C_DIAGNOSTIC_PROFILE,
              'cp_notification_control':PROFILE}
    scope={**guard_scope(),**{name:getattr(backup,name) for name in dir(backup) if name.endswith('_PROFILE')},
           **{name+'_profile':value for name,value in profiles.items()},
           'adf_proc_path_profile':backup.ADF_PROFILE}
    guards=compile(ast.Module(body=[cp302c_guard(),diagnostic_guard(),notification_guard()],type_ignores=[]),
                   '<actual-notification-guards>','exec')
    assignments=[node for node in probe_tree().body if isinstance(node,ast.Assign) and
                 isinstance(node.targets[0],ast.Name) and node.targets[0].id in
                 ('cp302c_no_transition_profile','cp302c_diagnostic_profile','cp_notification_control_profile')]
    read_profiles=compile(ast.Module(body=assignments,type_ignores=[]),'<actual-CP-profile-selection>','exec')
    def run(env,**changes):
        with mock.patch.dict(os.environ,env,clear=True):
            active={**scope,**changes};exec(read_profiles,active)
            for code in (batch_guard_code(),final_guard_code(),guards):exec(code,active)
    host=selected_host(tmp_path);run(host)
    run({},**{name+'_profile':'' for name in profiles},adf_proc_path_profile='')
    for key in (HOST,GUEST,'A7C2_CP302C_DIAGNOSTIC','MENU_CP302C_DIAGNOSTIC','A7C2_PINMEM_PEER_CONNECT'):
        for value in ('','unknown'):
            with pytest.raises(SystemExit):run({**host,key:value})
    with pytest.raises(SystemExit):run(host,cp_background='')
    with pytest.raises(SystemExit):run(host,vef_pinmem_control_connection_profile='')
    for key in ('A7C2_CP302C_NO_TRANSITION','MENU_CP302C_NO_TRANSITION'):
        with pytest.raises(SystemExit):run({**host,key:backup.FULL_CP302C_NO_TRANSITION_PROFILE})
    for arg in ('initramfs','observe','load_ipc','seed_backup','load_dmm','dmm_service','sony_timers'):
        args=copy.copy(scope['args']);setattr(args,arg,False)
        with pytest.raises(SystemExit):run(host,args=args)


def test_prepare_rejects_missing_diagnostic_pair_and_chain_before_candidate_work(tmp_path,monkeypatch):
    host=selected_host(tmp_path)
    def no_build(*args):raise AssertionError('invalid notification admission reached candidate work')
    monkeypatch.setattr(backup,'validate_build',no_build)
    for key in (HOST,GUEST,'A7C2_CP302C_DIAGNOSTIC','MENU_CP302C_DIAGNOSTIC',
                'MENU_CP_BACKGROUND','A7C2_VEF_PINMEM_CONTROL_CONNECT','MENU_PINMEM_OSD_CONNECT'):
        bad=dict(host);bad.pop(key)
        with pytest.raises(ValueError):backup.prepare_profile(HERE,bad)
    for key,value in (
        *((key,value) for key in (HOST,GUEST) for value in ('1','true','unknown',PROFILE+' ',None,True,1)),
        ('A7C2_CP302C_NO_TRANSITION',backup.FULL_CP302C_NO_TRANSITION_PROFILE),
        ('MENU_CP302C_NO_TRANSITION',backup.FULL_CP302C_NO_TRANSITION_PROFILE)):
        with pytest.raises(ValueError):backup.prepare_profile(HERE,{**host,key:value})
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize('enabled',[False,True])
def test_actual_receipt_manifest_and_validator_preserve_typed_finite_intent(tmp_path,enabled):
    build=build_fixture(tmp_path)[0];host=selected_host(tmp_path,build,enabled)
    with directory_lease(tmp_path/'card') as lease:
        host.update(directory_profile(HERE,lease,tmp_path/'directory-profile'))
        host.update(backup.prepare_profile(HERE,host))
    path=Path(host['MENU_BACKUP_PROFILE_RECEIPT']);receipt=json.loads(path.read_text())
    fields=backup.cp_notification_control_profile_fields(PROFILE if enabled else '')
    for key,value in fields.items():
        assert key in receipt and type(receipt[key]) is type(value)
        assert json.dumps(receipt[key])==json.dumps(value)
    tree=probe_tree()
    manifest=next(node.value for node in tree.body if isinstance(node,ast.Assign) and
                  isinstance(node.targets[0],ast.Name) and node.targets[0].id=='manifest')
    spread=next(value for key,value in zip(manifest.keys,manifest.values) if key is None and
                isinstance(value,ast.Call) and isinstance(value.func,ast.Name) and
                value.func.id=='cp_notification_control_profile_fields')
    scope={name+'_profile_fields':getattr(backup,name+'_profile_fields') for name in (
        'adf_proc','adf_set_input','adf_set_output','bb_set_mode','imaging_pin_connection',
        'imaging_control_connection','imaging_adf_connection','infrabb_vef_connection',
        'infrabb_vef_control_connection','vef_pinmem_input_connection','vef_pinmem_control_connection',
        'pinmem_peer_connections','pinmem_hdmi_video_connection','pinmem_osd_connection',
        'adf_hdmi_audio_connection','cp302c_no_transition','cp302c_diagnostic','cp_notification_control')}
    profiles={**OLD_PROFILES,**{name:profile for name,_,profile in FAMILIES},
              **{name:profile for name,_,profile,_ in FINAL_FAMILIES},'cp302c_no_transition':'',
              'cp302c_diagnostic':backup.FULL_CP302C_DIAGNOSTIC_PROFILE,
              'cp_notification_control':PROFILE if enabled else ''}
    scope.update({name+'_profile':value for name,value in profiles.items()})
    assert json.loads(json.dumps(eval(compile(ast.Expression(spread),'<actual-notification-manifest>','eval'),scope)))==fields
    nested=next(value for key,value in zip(manifest.keys,manifest.values)
                if isinstance(key,ast.Constant) and key.value=='backup_transport')
    assert eval(compile(ast.Expression(nested),'<actual-nested-receipt>','eval'),
                {'backup_profile_receipt':receipt})==receipt
    validator=next(node for node in tree.body if isinstance(node,ast.If) and
        isinstance(node.test,ast.Name) and node.test.id=='backup_sync' and any(
            isinstance(call,ast.Call) and isinstance(call.func,ast.Name) and call.func.id=='validate_build'
            for call in ast.walk(node)))
    code=compile(ast.Module(body=[validator],type_ignores=[]),'<actual-notification-receipt-validator>','exec')
    scope.update(os=os,json=json,Path=Path,base=HERE,sha256_file=backup.sha,backup_sync=backup.PROFILE,
        env=host,kernel_script=Path(host['MENU_KERNEL_SCRIPT']),board_dtb=Path(host['MENU_DTB']),
        adf_proc_path_profile=backup.ADF_PROFILE,
        udate_kernel_receipt=HERE.parents[1]/'report/virtual-cp/udate-distribution/verification.json',
        overwrite_manifest=None,settings_restore_manifest=None)
    with mock.patch.dict(os.environ,host,clear=True):
        exec(code,scope)
        for key,value in fields.items():
            bad=copy.deepcopy(receipt);bad.pop(key);path.write_text(json.dumps(bad))
            with pytest.raises(ValueError,match='identity/admission mismatch'):exec(code,scope)
            replacement=(int(value) if type(value) is bool else float(value) if type(value) is int else 'wrong')
            bad[key]=replacement;path.write_text(json.dumps(bad))
            with pytest.raises(ValueError,match='identity/admission mismatch'):exec(code,scope)
        path.write_text(json.dumps(receipt));exec(code,scope)
    assert all(receipt[PREFIX+name] is False for name in CLAIMS)
    assert clean_guest_environment(menu_probe_setup(host)).get(GUEST)==(PROFILE if enabled else None)
