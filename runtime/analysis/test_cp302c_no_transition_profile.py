"""CP302c typed host intent and actual constructor gate; no native completion claim."""
import ast
import copy
import json
import os
from pathlib import Path
from unittest import mock

import pytest

import backup_profile as backup
from test_backup_profile import HERE, build_fixture, directory_lease, directory_profile
from test_bb_set_mode_profile import bb_constructor, clean_guest_environment, guard_scope, load_script, menu_probe_setup
from test_final_graph_connections_profile import (FAMILIES as FINAL_FAMILIES, final_guard_code,
                                                  host_environment as graph_environment)
from test_infrabb_vef_control_connection_profile import PROFILE_NAMES
from test_native_graph_batch_profile import FAMILIES, OLD_PROFILES, batch_guard_code
from test_vef_pinmem_input_connection_profile import PREDECESSORS

PROFILE=backup.FULL_CP302C_NO_TRANSITION_PROFILE
PREFIX='cp302c_no_transition_'
HOST='A7C2_CP302C_NO_TRANSITION'
GUEST='MENU_CP302C_NO_TRANSITION'
CLAIMS={
    'normal_3041_transition_supported','original_CP_executed','ignored_reply_byte1_known',
    'native_verified','original_AP_consumed','branch_consumed','mode_transition_verified',
    'module_completion_verified','EE_verified','hardware_ready','frames_verified','capture_verified',
}
CHAIN=(*PREDECESSORS,'A7C2_VEF_PINMEM_INPUT_CONNECT',
       *(('A7C2_'+switch) for _,switch,_ in FAMILIES),
       *(('A7C2_'+switch) for _,switch,_,_ in FINAL_FAMILIES))


def host_environment(tmp_path,build=None,enabled=True):
    env=graph_environment(tmp_path,build,audio=True)
    if enabled:env[HOST]=PROFILE
    return env


def selected_host(tmp_path,build=None,enabled=True):
    launcher=load_script('cp302c_no_transition_launcher','start-menu.py')
    host=launcher.profile_environment(host_environment(tmp_path,build,enabled),natural_boot=True)
    host.update(MENU_BACKUP_SYNC=backup.PROFILE,SEED_BACKUP='alllang',
                A7C2_DIRECTORY_SD_PROFILE='directory-vvfat-256gb-v1')
    return host


@pytest.mark.parametrize('failure', ['', 'off', 'owner', 'bind', 'video', 'osd', 'audio'])
def test_actual_constructor_requires_clean_full_profile_and_both_initializers(tmp_path, bb_constructor, failure):
    exports = clean_guest_environment(menu_probe_setup(selected_host(tmp_path)))
    if failure == 'off':
        exports.pop(GUEST)
    if failure in ('video', 'osd', 'audio'):
        exports.pop({'video':'MENU_PINMEM_HDMI_VIDEO_CONNECT', 'osd':'MENU_PINMEM_OSD_CONNECT',
                     'audio':'MENU_ADF_HDMI_AUDIO_CONNECT'}[failure])
    if failure == 'bind':
        exports['FIXTURE_CP302C_BIND_FAIL'] = '1'
    result = bb_constructor(exports, cp302c_owner_rc=-1021 if failure == 'owner' else 0)
    line = next(line for line in result.splitlines() if line.startswith('RESULT '))
    fields = dict(part.split('=',1) for part in line.split()[1:])
    assert fields['cp302c'] == ('1' if not failure else '0')
    assert fields['cp302c_init'] == ('1' if failure in ('', 'owner', 'bind') else '0')
    profiles = [line for line in result.splitlines() if line.startswith('NATIVE_CP302C_NOCONVERT_PROFILE ')]
    if failure == 'off':
        assert not profiles
    else:
        assert len(profiles) == 1 and 'before_any_input=1' in profiles[0]
        assert 'mode_transition_verified=0' in profiles[0] and 'capture_verified=0' in profiles[0]


def test_fields_are_source_supported_branch_intent_and_never_mode_completion():
    assert PROFILE=='virtual-cp302c-current0-no-transition-v1'
    fields=backup.cp302c_no_transition_profile_fields(PROFILE)
    off=backup.cp302c_no_transition_profile_fields('')
    assert fields.keys()==off.keys()
    for key,value in off.items():
        assert value is (False if key[len(PREFIX):] in CLAIMS else None)
    for name in CLAIMS:assert fields[PREFIX+name] is False
    expected={
        'profile':PROFILE,'no_transition_branch_supported':True,
        'request_bytes':24,'response_bytes':12,'request_command':0x302c,
        'source_event':0x17,'query_command':0x3041,'query_record_present':False,
        'source_branch':{'outer':0xb1ffba,'query':0xb1f140,
                         'reject_handler':0x4b4b00,'reply_constructor':0xb22788},
        'branch_policy':'outer-query-not-admissible-before-observer',
        'response_type':1,'response_command':0x302c,'response_status':0xf000,
        'response_status_meaning':'positive-NO-TRANSITION-reply','AP_result':0,
        'cookie_policy':'echo-owned-request-cookie','origin_policy':'echo-incoming-origin',
        'ignored_reply_byte1_policy':'unknown-source-byte-virtual-padding-zero',
        'ignored_reply_byte1_virtual_padding':0,'ctor_initial_current':0,
        'current_validity_policy':'source-derived-explicit-clear-not-live-CP-RAM',
        'current_history_policy':'actual-3007-predecessors-and-strict-prefix-proof-in-C',
        'predecessor_connection_count':13,
        'predecessor_policy':'all-13-actual-AP-consumed-clean-no-outstanding-not-flags-only',
        'mode_3041_start_count':0,'module_mask_update_count':0,
        'current_mode_commit_count':0,'EE_ready_write_count':0,
    }
    for name,value in expected.items():
        assert type(fields[PREFIX+name]) is type(value)
        assert json.dumps(fields[PREFIX+name])==json.dumps(value)
    for value in ('1','true','virtual-cp302c-v1',PROFILE+' ',None,True,1):
        with pytest.raises(ValueError):backup.cp302c_no_transition_profile_fields(value)


def test_launcher_is_default_off_and_exact_selection_emits_only_the_guest_switch(tmp_path):
    launcher=load_script('cp302c_no_transition_default','start-menu.py')
    for env in ({},{GUEST:PROFILE},host_environment(tmp_path,enabled=False),
                {**host_environment(tmp_path,enabled=False),GUEST:PROFILE}):
        assert GUEST not in launcher.profile_environment(env,natural_boot=True)
    host=selected_host(tmp_path)
    assert host[GUEST]==PROFILE
    setup=menu_probe_setup(host);guest=clean_guest_environment(setup)
    assert guest[GUEST]==PROFILE and HOST not in guest
    assert setup.count('export '+GUEST+'='+PROFILE)==1
    for key in ('MENU_CP_EMULATION','MENU_VIRTUAL_CP_SENDER','MENU_BB_READY_INJECT',
                'MENU_BB_READY_LATE','MENU_YC_INJECT','MENU_FRAME_INJECT'):
        assert key not in guest
    assert not list(tmp_path.iterdir())


def test_launcher_rejects_all_missing_predecessors_private_seeds_and_existing_conflicts(tmp_path):
    launcher=load_script('cp302c_no_transition_unsafe','start-menu.py')
    env=host_environment(tmp_path)
    with pytest.raises(ValueError):launcher.profile_environment(env,natural_boot=False)
    for key in CHAIN:
        bad=dict(env);bad.pop(key)
        with pytest.raises(ValueError):launcher.profile_environment(bad,natural_boot=True)
    for key,value in (
        *((HOST,value) for value in ('1','true','unknown',PROFILE+' ')),
        ('SEED_BACKUP','private'),('SEED_BACKUP','full'),('MENU_USB_NET','1'),
        ('A7C2_DIRECTORY_SD','relative'),('A7C2_HOST_SD','256gb'),('A7C2_SD_SPARSE','10g-empty'),
        *[(key,'1') for key in backup.BB_MODE_CONFLICTS]):
        with pytest.raises(ValueError):launcher.profile_environment({**env,key:value},natural_boot=True)
    assert not list(tmp_path.iterdir())


def test_actual_setup_suppresses_new_export_if_host_or_any_emitted_dependency_is_missing(tmp_path):
    host=selected_host(tmp_path)
    dependencies=(HOST,GUEST,'MENU_CP_BACKGROUND',
        *(key for key in host if key.startswith(('A7C2_','MENU_')) and key.endswith('_CONNECT')),
        'MENU_BB_SET_MODE')
    for key in dependencies:
        bad=dict(host);bad.pop(key)
        assert GUEST not in clean_guest_environment(menu_probe_setup(bad)),key
    for key in (HOST,GUEST):
        for value in ('1','true','unknown',PROFILE+' '):
            assert GUEST not in clean_guest_environment(menu_probe_setup({**host,key:value}))


def cp302c_guard():
    tree=ast.parse((HERE/'qemu-menu-probe.py').read_text())
    return next(node for node in tree.body if isinstance(node,ast.If) and any(
        isinstance(call,ast.Call) and isinstance(call.func,ast.Attribute) and
        ast.unparse(call.func)=='parser.error' and call.args and isinstance(call.args[0],ast.Constant) and
        str(call.args[0].value).startswith('CP302c NO-TRANSITION requires') for call in ast.walk(node)))


def test_actual_cli_guards_require_full_chain_and_exact_paired_host_guest_values(tmp_path):
    host=selected_host(tmp_path)
    profiles={**OLD_PROFILES,**{name:profile for name,_,profile in FAMILIES},
              **{name:profile for name,_,profile,_ in FINAL_FAMILIES},'cp302c_no_transition':PROFILE}
    scope={**guard_scope(),**{name:getattr(backup,name) for name in dir(backup) if name.endswith('_PROFILE')},
           **{name+'_profile':value for name,value in profiles.items()},
           'adf_proc_path_profile':backup.ADF_PROFILE}
    codes=(batch_guard_code(),final_guard_code(),
           compile(ast.Module(body=[cp302c_guard()],type_ignores=[]),'<actual-cp302c-guard>','exec'))
    def run(env,**changes):
        with mock.patch.dict(os.environ,env,clear=True):
            active={**scope,**changes}
            for code in codes:exec(code,active)
    run(host)
    run({**host,'MENU_USB_NET':'1'})  # Existing internal directory-storage marker.
    run({},**{name+'_profile':'' for name in profiles},adf_proc_path_profile='')
    for name in (*profiles,'adf_proc_path'):
        if name=='adf_proc':continue
        for value in ('','unknown'):
            with pytest.raises(SystemExit):run(host,**{name+'_profile':value})
    with pytest.raises(SystemExit):run(host,cp_background='')
    for key in (HOST,'SEED_BACKUP','A7C2_DIRECTORY_SD_PROFILE','MENU_PIN_REGISTRY',
                'MENU_PIN_CONTROL_MEMORY','MENU_PIN_CONNECTION',
                *(key for key in CHAIN if key.endswith('_CONNECT'))):
        for value in ('','unknown'):
            with pytest.raises(SystemExit):run({**host,key:value})
    for value in ('1','true','unknown',PROFILE+' '):
        with pytest.raises(SystemExit):run({**host,HOST:value},cp302c_no_transition_profile='')
    for key in backup.BB_MODE_CONFLICTS:
        with pytest.raises(SystemExit):run({**host,key:'1'})


def test_prepare_rejects_bad_profile_chain_or_seed_before_candidate_and_outputs(tmp_path,monkeypatch):
    host=selected_host(tmp_path)
    def no_build(*args):raise AssertionError('invalid CP302c admission reached candidate work')
    monkeypatch.setattr(backup,'validate_build',no_build)
    for key in (HOST,GUEST,'MENU_CP_BACKGROUND',
                *(key for key in host if key.startswith(('A7C2_','MENU_')) and key.endswith('_CONNECT')),
                'MENU_BB_SET_MODE','MENU_ADF_SET_OUTPUT','MENU_PIN_REGISTRY',
                'MENU_PIN_CONTROL_MEMORY','MENU_PIN_CONNECTION','SEED_BACKUP','A7C2_DIRECTORY_SD_PROFILE'):
        bad=dict(host);bad.pop(key)
        with pytest.raises(ValueError):backup.prepare_profile(HERE,bad)
    for key,value in (
        *((key,value) for key in (HOST,GUEST) for value in ('1','true','unknown',PROFILE+' ')),
        ('SEED_BACKUP','private'),('SEED_BACKUP','full'),('QEMU_CPU_COUNT','2'),
        *[(key,'1') for key in backup.BB_MODE_CONFLICTS]):
        with pytest.raises(ValueError):backup.prepare_profile(HERE,{**host,key:value})
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize('enabled',[False,True])
def test_actual_receipt_and_manifest_keep_typed_intent_and_reject_all_mutations(tmp_path,enabled):
    build=build_fixture(tmp_path)[0]
    host=selected_host(tmp_path,build,enabled)
    with directory_lease(tmp_path/'card') as lease:
        host.update(directory_profile(HERE,lease,tmp_path/'directory-profile'))
        host.update(backup.prepare_profile(HERE,host))
    path=Path(host['MENU_BACKUP_PROFILE_RECEIPT']);receipt=json.loads(path.read_text())
    fields=backup.cp302c_no_transition_profile_fields(PROFILE if enabled else '')
    for key,value in fields.items():
        assert key in receipt and type(receipt[key]) is type(value)
        assert json.dumps(receipt[key])==json.dumps(value)
    tree=ast.parse((HERE/'qemu-menu-probe.py').read_text())
    manifest=next(node.value for node in tree.body if isinstance(node,ast.Assign) and
                  isinstance(node.targets[0],ast.Name) and node.targets[0].id=='manifest')
    spread=next(value for key,value in zip(manifest.keys,manifest.values) if key is None and
                isinstance(value,ast.Call) and isinstance(value.func,ast.Name) and
                value.func.id=='cp302c_no_transition_profile_fields')
    active={**OLD_PROFILES,**{name:profile for name,_,profile in FAMILIES},
            **{name:profile for name,_,profile,_ in FINAL_FAMILIES},
            'cp302c_no_transition':PROFILE if enabled else ''}
    scope={name+'_profile':value for name,value in active.items()}
    scope.update({name+'_profile_fields':getattr(backup,name+'_profile_fields')
                  for name in (*PROFILE_NAMES,'cp302c_no_transition')})
    assert eval(compile(ast.Expression(spread),'<actual-cp302c-manifest>','eval'),scope)==fields
    nested=next(value for key,value in zip(manifest.keys,manifest.values)
                if isinstance(key,ast.Constant) and key.value=='backup_transport')
    assert eval(compile(ast.Expression(nested),'<actual-nested-receipt>','eval'),
                {'backup_profile_receipt':receipt})==receipt
    validator=next(node for node in tree.body if isinstance(node,ast.If) and
        isinstance(node.test,ast.Name) and node.test.id=='backup_sync' and any(
            isinstance(call,ast.Call) and isinstance(call.func,ast.Name) and call.func.id=='validate_build'
            for call in ast.walk(node)))
    code=compile(ast.Module(body=[validator],type_ignores=[]),'<actual-cp302c-receipt-validator>','exec')
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
            for key,value in fields[PREFIX+'source_branch'].items():
                for replacement in (float(value),bool(value)):
                    bad=copy.deepcopy(receipt);bad[PREFIX+'source_branch'][key]=replacement
                    path.write_text(json.dumps(bad))
                    with pytest.raises(ValueError,match='identity/admission mismatch'):exec(code,scope)
            bad=copy.deepcopy(receipt);bad[PREFIX+'predecessor_profiles']['cp_background']='unknown'
            path.write_text(json.dumps(bad))
            with pytest.raises(ValueError,match='identity/admission mismatch'):exec(code,scope)
        for option in ('overwrite_manifest','settings_restore_manifest'):
            path.write_text(json.dumps(receipt));scope[option]={'forbidden':'private-instance'}
            with pytest.raises(ValueError,match='identity/admission mismatch'):exec(code,scope)
            scope[option]=None
        path.write_text(json.dumps(receipt));exec(code,scope)
    assert all(receipt[PREFIX+name] is False for name in CLAIMS)
    assert clean_guest_environment(menu_probe_setup(host)).get(GUEST)==(PROFILE if enabled else None)
