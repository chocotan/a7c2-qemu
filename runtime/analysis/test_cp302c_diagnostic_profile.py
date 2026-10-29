"""Bounded diagnostic CP302c admission/transport; never a strict branch or capture claim."""
import ast
import copy
import json
import os
from pathlib import Path
from unittest import mock

import pytest

import backup_profile as backup
from test_backup_profile import HERE, build_fixture, directory_lease, directory_profile
from test_bb_set_mode_profile import clean_guest_environment, guard_scope, load_script, menu_probe_setup
from test_cp302c_no_transition_profile import CHAIN, cp302c_guard
from test_final_graph_connections_profile import (FAMILIES as FINAL_FAMILIES, final_guard_code,
                                                  host_environment as graph_environment)
from test_infrabb_vef_control_connection_profile import PROFILE_NAMES
from test_native_graph_batch_profile import FAMILIES, OLD_PROFILES, batch_guard_code

PROFILE=backup.FULL_CP302C_DIAGNOSTIC_PROFILE
PREFIX='cp302c_diagnostic_'
HOST='A7C2_CP302C_DIAGNOSTIC'
GUEST='MENU_CP302C_DIAGNOSTIC'
STRICT_HOST='A7C2_CP302C_NO_TRANSITION'
STRICT_GUEST='MENU_CP302C_NO_TRANSITION'
CLAIMS={
    'no_transition_branch_supported','normal_3041_transition_supported',
    'source_branch_equivalent','original_CP_executed','original_initializer_verified',
    'live_CP_RAM_read','source_history_equivalent','source_prefix_equivalent',
    'current_known','history_known','ignored_reply_byte1_known',
    'transport_verified','native_verified','original_AP_consumed','branch_consumed',
    'mode_transition_verified','module_completion_verified','EE_verified',
    'hardware_ready','frames_verified','capture_verified',
}


def host_environment(tmp_path,build=None,enabled=True):
    env=graph_environment(tmp_path,build,audio=True)
    if enabled:env[HOST]=PROFILE
    return env


def selected_host(tmp_path,build=None,enabled=True):
    launcher=load_script('cp302c_diagnostic_launcher','start-menu.py')
    host=launcher.profile_environment(host_environment(tmp_path,build,enabled),natural_boot=True)
    host.update(MENU_BACKUP_SYNC=backup.PROFILE,SEED_BACKUP='alllang',
                A7C2_DIRECTORY_SD_PROFILE='directory-vvfat-256gb-v1')
    return host


def test_fields_are_diagnostic_only_with_unknown_current_history_and_no_promoted_claims():
    assert PROFILE=='diagnostic-cp302c-reply-only-v1'
    fields=backup.cp302c_diagnostic_profile_fields(PROFILE)
    off=backup.cp302c_diagnostic_profile_fields('')
    assert fields.keys()==off.keys() and all(key.startswith(PREFIX) for key in fields)
    for key,value in off.items():
        assert value is (False if key[len(PREFIX):] in CLAIMS else None)
    for name in CLAIMS:assert fields[PREFIX+name] is False
    expected={
        'profile':PROFILE,'diagnostic_only':1,'no_transition':0,
        'request_bytes':24,'response_bytes':12,'request_command':0x302c,
        'source_event':0x17,'query_command':0x3041,'query_record_present':False,
        'response_type':1,'response_command':0x302c,'response_status':0xf000,'AP_result':0,
        'response_status_meaning':'diagnostic-positive-reply-no-source-branch-equivalence',
        'current':None,'history':None,
        'current_validity_policy':'unknown-never-inferred-from-public-initializer',
        'current_history_policy':'unknown-after-actual-3007-and-full-13-consumed',
        'prefix_policy':'unknown-prefix-audited-only-for-diagnostic-transport',
        'predecessor_connection_count':13,
        'predecessor_policy':'actual-3007-reply-free-and-all-13-AP-consumed-clean-no-outstanding',
        'mode_3041_start_count':0,'module_mask_update_count':0,
        'current_mode_commit_count':0,'EE_ready_write_count':0,
        'native_consumption_requires':'original-AP302c-reply-free',
    }
    for name,value in expected.items():
        assert type(fields[PREFIX+name]) is type(value)
        assert json.dumps(fields[PREFIX+name])==json.dumps(value)
    for value in ('1','true','unknown',PROFILE+' ',backup.FULL_CP302C_NO_TRANSITION_PROFILE,None,True,1):
        with pytest.raises(ValueError):backup.cp302c_diagnostic_profile_fields(value)


def test_launcher_default_off_and_actual_clean_guest_export_are_exact_and_separate(tmp_path):
    launcher=load_script('cp302c_diagnostic_default','start-menu.py')
    for env in ({},{GUEST:PROFILE},host_environment(tmp_path,enabled=False),
                {**host_environment(tmp_path,enabled=False),GUEST:PROFILE}):
        assert GUEST not in launcher.profile_environment(env,natural_boot=True)
    host=selected_host(tmp_path)
    setup=menu_probe_setup(host);guest=clean_guest_environment(setup)
    assert host[GUEST]==guest[GUEST]==PROFILE and HOST not in guest
    assert setup.count('export '+GUEST+'='+PROFILE)==1
    assert not host.get(STRICT_GUEST) and STRICT_GUEST not in guest
    for key in ('MENU_CP_EMULATION','MENU_VIRTUAL_CP_SENDER','MENU_BB_READY_INJECT',
                'MENU_BB_READY_LATE','MENU_YC_INJECT','MENU_FRAME_INJECT'):
        assert key not in guest
    assert not list(tmp_path.iterdir())


def test_launcher_rejects_missing_chain_prior_conflicts_unknown_and_direct_or_private_modes(tmp_path):
    launcher=load_script('cp302c_diagnostic_unsafe','start-menu.py')
    env=host_environment(tmp_path)
    with pytest.raises(ValueError):launcher.profile_environment(env,natural_boot=False)
    for key in CHAIN:
        bad=dict(env);bad.pop(key)
        with pytest.raises(ValueError):launcher.profile_environment(bad,natural_boot=True)
    for key,value in (
        *((key,value) for key in (HOST,GUEST) for value in ('1','true','unknown',PROFILE+' ')),
        (STRICT_HOST,backup.FULL_CP302C_NO_TRANSITION_PROFILE),
        (STRICT_GUEST,backup.FULL_CP302C_NO_TRANSITION_PROFILE),
        ('SEED_BACKUP','private'),('SEED_BACKUP','full'),('MENU_USB_NET','1'),
        ('A7C2_DIRECTORY_SD','relative'),('A7C2_HOST_SD','256gb'),('A7C2_SD_SPARSE','10g-empty'),
        *[(key,'1') for key in backup.BB_MODE_CONFLICTS]):
        with pytest.raises(ValueError):launcher.profile_environment({**env,key:value},natural_boot=True)
    assert not list(tmp_path.iterdir())


def test_actual_setup_suppresses_diagnostic_for_missing_or_forged_pair_chain_or_strict_owner(tmp_path):
    host=selected_host(tmp_path)
    for key in (HOST,GUEST,'MENU_CP_BACKGROUND','MENU_BB_SET_MODE',
                *(key for key in host if key.startswith(('A7C2_','MENU_')) and key.endswith('_CONNECT'))):
        bad=dict(host);bad.pop(key)
        assert GUEST not in clean_guest_environment(menu_probe_setup(bad)),key
    for key in (HOST,GUEST):
        for value in ('1','true','unknown',PROFILE+' '):
            assert GUEST not in clean_guest_environment(menu_probe_setup({**host,key:value}))
    for key in (STRICT_HOST,STRICT_GUEST):
        guest=clean_guest_environment(menu_probe_setup({**host,key:backup.FULL_CP302C_NO_TRANSITION_PROFILE}))
        assert GUEST not in guest and STRICT_GUEST not in guest


def diagnostic_guard():
    tree=ast.parse((HERE/'qemu-menu-probe.py').read_text())
    return next(node for node in tree.body if isinstance(node,ast.If) and any(
        isinstance(call,ast.Call) and isinstance(call.func,ast.Attribute) and
        ast.unparse(call.func)=='parser.error' and call.args and isinstance(call.args[0],ast.Constant) and
        str(call.args[0].value).startswith('CP302c diagnostic requires') for call in ast.walk(node)))


def test_actual_cli_guards_reject_incomplete_chain_mismatches_unknown_and_both_owners(tmp_path):
    host=selected_host(tmp_path)
    profiles={**OLD_PROFILES,**{name:profile for name,_,profile in FAMILIES},
              **{name:profile for name,_,profile,_ in FINAL_FAMILIES},
              'cp302c_no_transition':'','cp302c_diagnostic':PROFILE}
    scope={**guard_scope(),**{name:getattr(backup,name) for name in dir(backup) if name.endswith('_PROFILE')},
           **{name+'_profile':value for name,value in profiles.items()},
           'adf_proc_path_profile':backup.ADF_PROFILE}
    codes=(batch_guard_code(),final_guard_code(),compile(ast.Module(
        body=[cp302c_guard(),diagnostic_guard()],type_ignores=[]),'<actual-cp302c-diagnostic-guards>','exec'))
    def run(env,**changes):
        with mock.patch.dict(os.environ,env,clear=True):
            active={**scope,**changes}
            for code in codes:exec(code,active)
    run(host)
    run({**host,'MENU_USB_NET':'1'})
    run({},**{name+'_profile':'' for name in profiles},adf_proc_path_profile='')
    for name in (*profiles,'adf_proc_path'):
        if name in ('adf_proc','cp302c_no_transition'):continue
        for value in ('','unknown'):
            with pytest.raises(SystemExit):run(host,**{name+'_profile':value})
    with pytest.raises(SystemExit):run(host,cp_background='')
    for key in (HOST,'SEED_BACKUP','A7C2_DIRECTORY_SD_PROFILE','MENU_PIN_REGISTRY',
                'MENU_PIN_CONTROL_MEMORY','MENU_PIN_CONNECTION',
                *(key for key in CHAIN if key.endswith('_CONNECT'))):
        for value in ('','unknown'):
            with pytest.raises(SystemExit):run({**host,key:value})
    for value in ('1','true','unknown',PROFILE+' '):
        with pytest.raises(SystemExit):run({**host,HOST:value},cp302c_diagnostic_profile='')
    for key in (STRICT_HOST,STRICT_GUEST):
        with pytest.raises(SystemExit):run({**host,key:backup.FULL_CP302C_NO_TRANSITION_PROFILE})
    for key in backup.BB_MODE_CONFLICTS:
        with pytest.raises(SystemExit):run({**host,key:'1'})


def test_prepare_rejects_invalid_admission_before_build_or_outputs(tmp_path,monkeypatch):
    host=selected_host(tmp_path)
    def no_build(*args):raise AssertionError('invalid diagnostic admission reached candidate work')
    monkeypatch.setattr(backup,'validate_build',no_build)
    for key in (HOST,GUEST,'MENU_CP_BACKGROUND',
                *(key for key in host if key.startswith(('A7C2_','MENU_')) and key.endswith('_CONNECT')),
                'MENU_BB_SET_MODE','MENU_ADF_SET_OUTPUT','MENU_PIN_REGISTRY',
                'MENU_PIN_CONTROL_MEMORY','MENU_PIN_CONNECTION','SEED_BACKUP','A7C2_DIRECTORY_SD_PROFILE'):
        bad=dict(host);bad.pop(key)
        with pytest.raises(ValueError):backup.prepare_profile(HERE,bad)
    for key,value in (
        *((key,value) for key in (HOST,GUEST) for value in ('1','true','unknown',PROFILE+' ')),
        (STRICT_HOST,backup.FULL_CP302C_NO_TRANSITION_PROFILE),
        (STRICT_GUEST,backup.FULL_CP302C_NO_TRANSITION_PROFILE),
        ('SEED_BACKUP','private'),('SEED_BACKUP','full'),('QEMU_CPU_COUNT','2'),
        *[(key,'1') for key in backup.BB_MODE_CONFLICTS]):
        with pytest.raises(ValueError):backup.prepare_profile(HERE,{**host,key:value})
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize('enabled',[False,True])
def test_actual_receipt_lifecycle_and_manifest_keep_typed_diagnostic_intent(tmp_path,enabled):
    build=build_fixture(tmp_path)[0]
    host=selected_host(tmp_path,build,enabled)
    with directory_lease(tmp_path/'card') as lease:
        host.update(directory_profile(HERE,lease,tmp_path/'directory-profile'))
        host.update(backup.prepare_profile(HERE,host))
    path=Path(host['MENU_BACKUP_PROFILE_RECEIPT']);receipt=json.loads(path.read_text())
    fields=backup.cp302c_diagnostic_profile_fields(PROFILE if enabled else '')
    strict=backup.cp302c_no_transition_profile_fields('')
    for key,value in {**fields,**strict}.items():
        assert key in receipt and type(receipt[key]) is type(value)
        assert json.dumps(receipt[key])==json.dumps(value)
    tree=ast.parse((HERE/'qemu-menu-probe.py').read_text())
    manifest=next(node.value for node in tree.body if isinstance(node,ast.Assign) and
                  isinstance(node.targets[0],ast.Name) and node.targets[0].id=='manifest')
    spread=next(value for key,value in zip(manifest.keys,manifest.values) if key is None and
                isinstance(value,ast.Call) and isinstance(value.func,ast.Name) and
                value.func.id=='cp302c_diagnostic_profile_fields')
    active={**OLD_PROFILES,**{name:profile for name,_,profile in FAMILIES},
            **{name:profile for name,_,profile,_ in FINAL_FAMILIES},
            'cp302c_no_transition':'','cp302c_diagnostic':PROFILE if enabled else ''}
    scope={name+'_profile':value for name,value in active.items()}
    scope.update({name+'_profile_fields':getattr(backup,name+'_profile_fields')
                  for name in (*PROFILE_NAMES,'cp302c_no_transition','cp302c_diagnostic')})
    actual=eval(compile(ast.Expression(spread),'<actual-diagnostic-manifest>','eval'),scope)
    assert json.loads(json.dumps(actual))==fields
    nested=next(value for key,value in zip(manifest.keys,manifest.values)
                if isinstance(key,ast.Constant) and key.value=='backup_transport')
    assert eval(compile(ast.Expression(nested),'<actual-nested-receipt>','eval'),
                {'backup_profile_receipt':receipt})==receipt
    validator=next(node for node in tree.body if isinstance(node,ast.If) and
        isinstance(node.test,ast.Name) and node.test.id=='backup_sync' and any(
            isinstance(call,ast.Call) and isinstance(call.func,ast.Name) and call.func.id=='validate_build'
            for call in ast.walk(node)))
    code=compile(ast.Module(body=[validator],type_ignores=[]),'<actual-diagnostic-receipt-validator>','exec')
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
            replacements=([int(value),not value] if type(value) is bool else
                          [float(value),bool(value)] if type(value) is int else ['wrong'])
            for replacement in replacements:
                bad[key]=replacement;path.write_text(json.dumps(bad))
                with pytest.raises(ValueError,match='identity/admission mismatch'):exec(code,scope)
        if enabled:
            bad=copy.deepcopy(receipt);bad[PREFIX+'predecessor_profiles']['cp_background']='unknown'
            path.write_text(json.dumps(bad))
            with pytest.raises(ValueError,match='identity/admission mismatch'):exec(code,scope)
            bad=copy.deepcopy(receipt);bad['cp302c_no_transition_profile']=backup.FULL_CP302C_NO_TRANSITION_PROFILE
            path.write_text(json.dumps(bad))
            with pytest.raises(ValueError,match='identity/admission mismatch'):exec(code,scope)
        for option in ('overwrite_manifest','settings_restore_manifest'):
            path.write_text(json.dumps(receipt));scope[option]={'forbidden':'private-instance'}
            with pytest.raises(ValueError,match='identity/admission mismatch'):exec(code,scope)
            scope[option]=None
        path.write_text(json.dumps(receipt));exec(code,scope)
    assert all(receipt[PREFIX+name] is False for name in CLAIMS)
    assert receipt['cp302c_no_transition_profile'] is None
    assert clean_guest_environment(menu_probe_setup(host)).get(GUEST)==(PROFILE if enabled else None)
