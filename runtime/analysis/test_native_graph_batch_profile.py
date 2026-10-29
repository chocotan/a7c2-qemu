"""Host admission for edges 7, 8/9/10 and 13; no native AP, PCM or capture claims."""
import ast
import copy
import json
import os
from pathlib import Path
from unittest import mock

import pytest

import backup_profile as backup
from test_backup_profile import HERE, build_fixture, directory_lease, directory_profile
from test_bb_set_mode_profile import (bb_constructor, clean_guest_environment, guard_scope,
                                      load_script, menu_probe_setup, qemu_bb_guard)
from test_imaging_pin_connection_profile import qemu_imaging_guard
from test_imaging_control_connection_profile import qemu_control_guard
from test_imaging_adf_connection_profile import qemu_adf_guard
from test_infrabb_vef_connection_profile import qemu_vef_guard
from test_infrabb_vef_control_connection_profile import PROFILE_NAMES, qemu_fifth_guard
from test_vef_pinmem_input_connection_profile import (
    PREDECESSORS, host_environment as sixth_environment, qemu_sixth_guard)

FAMILIES=(
    ('vef_pinmem_control_connection','VEF_PINMEM_CONTROL_CONNECT',
     backup.FULL_VEF_PINMEM_CONTROL_CONNECTION_PROFILE),
    ('pinmem_peer_connections','PINMEM_PEER_CONNECT',backup.FULL_PINMEM_PEER_CONNECTIONS_PROFILE),
    ('adf_hdmi_audio_connection','ADF_HDMI_AUDIO_CONNECT',backup.FULL_ADF_HDMI_AUDIO_CONNECTION_PROFILE),
)
SIXTH_HOST='A7C2_VEF_PINMEM_INPUT_CONNECT'
OLD_PROFILES={
    'adf_proc':backup.ADF_PROFILE,'adf_set_input':backup.INPUT_PROFILE,
    'adf_set_output':backup.OUTPUT_PROFILE,'bb_set_mode':backup.BB_SET_MODE_PROFILE,
    'imaging_pin_connection':backup.IMAGING_CONNECT_PROFILE,
    'imaging_control_connection':backup.IMAGING_CONTROL_CONNECT_PROFILE,
    'imaging_adf_connection':backup.IMAGING_ADF_CONNECT_PROFILE,
    'infrabb_vef_connection':backup.INFRABB_VEF_CONNECT_PROFILE,
    'infrabb_vef_control_connection':backup.FULL_INFRABB_VEF_CONTROL_CONNECTION_PROFILE,
    'vef_pinmem_input_connection':backup.FULL_VEF_PINMEM_INPUT_CONNECTION_PROFILE,
}


def host_environment(tmp_path,build=None,steps=3):
    return {**sixth_environment(tmp_path,build),
            **{'A7C2_'+switch:profile for _,switch,profile in FAMILIES[:steps]}}


def test_seventh_fields_pin_event8_and_zero_effects():
    fields=backup.vef_pinmem_control_connection_profile_fields(FAMILIES[0][2])
    expected={
        'source_pin':[8,2,0,0x905a0048],'peer_pin':[8,1,0,0x90590818],
        'source_registry_count':16,'source_registry_slot':15,
        'sink_registry_count':13,'sink_registry_slot':12,
        'source_event':8,'event_parameter_bytes':32,'event_parameter_pointer_offset':0,
        'event_pointer_policy':'virtual-token-bound-to-owned-72B-message',
        'event_peer_check':'saved-original-full-peer-key-must-equal-reply-peer-key',
        'source_posthook_ordinal':15,'source_posthook_allowed_ordinals':[1,2,3],
        'source_posthook_selected':False,'sink_manager_callback_expected_return':0,
    }
    for name,value in expected.items():
        assert json.dumps(fields['vef_pinmem_control_connection_'+name])==json.dumps(value)
    for name in ('connected_marker_write','dmm_command','ssyn_notice','format_cache_write',
                 'current_info_write','f008_command','clock_write','mmio_write','frame'):
        assert fields['vef_pinmem_control_connection_'+name+'_count']==0


def test_aggregate_fields_pin_three_edges_and_actual_twelve_byte_event6():
    fields=backup.pinmem_peer_connections_profile_fields(FAMILIES[1][2])
    assert fields['pinmem_peer_connections_edges']==[
        {'source_pin':[0,2,1,0x90590818],'peer_pin':[0,1,4,0x91670464],
         'source_slot':4,'peer_slot':4,'peer_count':10,'profile':'virtual-pinmem-out1-scalar-in4-v1'},
        {'source_pin':[0,2,2,0x90590818],'peer_pin':[0,1,0,0x9058003f],
         'source_slot':5,'peer_slot':0,'peer_count':10,'profile':'virtual-pinmem-out2-adf-in0-v1'},
        {'source_pin':[6,2,0,0x90590818],'peer_pin':[6,1,0,0x928d0783],
         'source_slot':10,'peer_slot':1,'peer_count':2,'profile':'virtual-pinmem-drawinfo0-drawinfo-in0-v1'}]
    assert fields['pinmem_peer_connections_unique_reply_count']==3
    assert fields['pinmem_peer_connections_source_event']==6
    assert fields['pinmem_peer_connections_event_parameter_bytes']==12
    assert fields['pinmem_peer_connections_event_parameter_pointer_offset']==0
    assert fields['pinmem_peer_connections_event_pointer_policy']=='virtual-token-bound-to-owned-reply-inner-header'
    assert fields['pinmem_peer_connections_saved_request_policy']=='owned-original-64B-copy-phase1-wait6-full-peer-check'
    for name in ('dmm_command','ssyn_notice','format_cache_write','marker_write','clock_write','mmio_write','frame'):
        assert fields['pinmem_peer_connections_'+name+'_count']==0


def test_audio_fields_keep_unknown_old_shared_byte_and_no_pcm_claim():
    fields=backup.adf_hdmi_audio_connection_profile_fields(FAMILIES[2][2])
    expected={
        'source_pin':[5,2,0,0x9058003f],'peer_pin':[5,1,0,0x909a015a],
        'source_registry_count':10,'source_registry_slot':9,'sink_registry_count':2,'sink_registry_slot':1,
        'hdmi_singleton_pointer_CP_VA':0x01791f04,'audio_connected_byte_offset':0x60,
        'audio_connected_old_value_known':False,'audio_connected_write_value':1,
        'audio_connected_write_count':1,'shared_audio_connected_readback_required':True,
        'sink_posthook_state_policy':'same-connected-true-effect-in-all-ten-HDMI-states',
        'sink_posthook_return_meaning':'no-next-state-not-protocol-status',
        'unhandled_video_OSD_edges_may_remain_refused':True,
        'pcm_verified':False,'hdmi_current_state_verified':False,'capture_verified':False,
    }
    for name,value in expected.items():
        assert json.dumps(fields['adf_hdmi_audio_connection_'+name])==json.dumps(value)


@pytest.mark.parametrize('name,switch,profile',FAMILIES)
def test_fields_default_off_exact_profiles_and_false_runtime_intentions(name,switch,profile):
    function=getattr(backup,name+'_profile_fields')
    fields=function(profile);off=function('')
    assert fields.keys()==off.keys()
    assert fields[name+'_profile']==profile
    claims={
        'original_cp_executed','original_cp_ram_mapping_verified','original_cp_page_tables_verified',
        'original_cp_pointer_verified','original_event_pointer_verified','original_task_scheduler_verified',
        'original_RTOS_timing_verified','original_semaphore_timing_verified','hardware_verified',
        'ap_consumed','runtime_consumed','native_verified','event8_consumed','event6_consumed',
        'connection_verified','connections_verified','format_consumed','general_format_ready',
        'audio_connected_verified','hdmi_current_state_verified','pcm_verified',
        'cmos_verified','frames_verified','capture_verified',
    }
    for key,value in off.items():
        assert value is (False if key[len(name)+1:] in claims else None)
    for suffix in ('original_cp_executed','original_task_scheduler_verified','hardware_verified',
                   'ap_consumed','runtime_consumed','native_verified','frames_verified','capture_verified'):
        assert fields[name+'_'+suffix] is False
    for suffix,value in {
        'request_bytes':64,'reply_bytes':56,'reply_command':0x8001,
        'source_state_path':[1,2,0],'sink_state_path':[1,0],
        'internal_commands':[0x100,0x8100],'internal_message_bytes':[64,72],
        'imaging_config_preserved':[1,1,1920,1080,3],
        'predecessors_require_ap_consumed':True,'predecessors_require_clean':True,
        'predecessors_require_no_outstanding':True,
    }.items():
        assert json.dumps(fields[name+'_'+suffix])==json.dumps(value)
    with pytest.raises(ValueError):function('unknown')


def test_public_python_profiles_match_actual_c_header_macros():
    for constant,header in (
        ('FULL_VEF_PINMEM_CONTROL_CONNECTION_PROFILE','vef-pinmem-control-connection.h'),
        ('FULL_PINMEM_PEER_CONNECTIONS_PROFILE','scalar-connection.h'),
        ('FULL_ADF_HDMI_AUDIO_CONNECTION_PROFILE','adf-hdmi-audio-connection.h')):
        assert '#define '+constant+' "'+getattr(backup,constant)+'"' in (HERE/'device-models'/header).read_text()


@pytest.mark.parametrize('steps',[1,2,3])
def test_launcher_exact_default_off_switches_ignore_forged_guest_toggles(tmp_path,steps):
    launcher=load_script('batch_launcher','start-menu.py')
    before=host_environment(tmp_path,steps=steps-1)
    _,switch,profile=FAMILIES[steps-1]
    for env in ({},before,{**before,'MENU_'+switch:profile}):
        assert 'MENU_'+switch not in launcher.profile_environment(env,natural_boot=True)
    selected=launcher.profile_environment(host_environment(tmp_path,steps=steps),natural_boot=True)
    for index,(_,key,value) in enumerate(FAMILIES):
        assert selected.get('MENU_'+key)==(value if index<steps else None)
    with pytest.raises(ValueError):
        launcher.profile_environment(host_environment(tmp_path,steps=steps),natural_boot=False)
    with pytest.raises(ValueError):
        launcher.profile_environment({**host_environment(tmp_path,steps=steps),'A7C2_'+switch:'unknown'},natural_boot=True)


@pytest.mark.parametrize('steps',[1,2,3])
def test_launcher_rejects_every_missing_predecessor_or_unsafe_mode_before_files(tmp_path,steps):
    launcher=load_script('batch_launcher_rejection','start-menu.py')
    env=host_environment(tmp_path,steps=steps)
    for missing in (SIXTH_HOST,*PREDECESSORS,*('A7C2_'+switch for _,switch,_ in FAMILIES[:steps-1])):
        bad=dict(env);bad.pop(missing)
        with pytest.raises(ValueError):launcher.profile_environment(bad,natural_boot=True)
    for key,value in (
        ('SEED_BACKUP','private'),('SEED_BACKUP','full'),('MENU_USB_NET','1'),
        ('A7C2_HOST_SD','256gb'),('A7C2_SD_SPARSE','10g-empty'),
        *[(key,'1') for key in backup.BB_MODE_CONFLICTS]):
        with pytest.raises(ValueError):launcher.profile_environment({**env,key:value},natural_boot=True)
    assert not list(tmp_path.iterdir())


def batch_guard_code():
    tree=ast.parse((HERE/'qemu-menu-probe.py').read_text())
    extra=[]
    for prefix in ('VEF PinMem control connection requires','PinMem peer connections require',
                   'ADF HDMI audio connection requires'):
        extra.append(next(node for node in tree.body if isinstance(node,ast.If) and any(
            isinstance(call,ast.Call) and isinstance(call.func,ast.Attribute) and
            ast.unparse(call.func)=='parser.error' and call.args and isinstance(call.args[0],ast.Constant) and
            str(call.args[0].value).startswith(prefix) for call in ast.walk(node))))
    return compile(ast.Module(body=[qemu_bb_guard(),qemu_imaging_guard(),qemu_control_guard(),
        qemu_adf_guard(),qemu_vef_guard(),qemu_fifth_guard(),qemu_sixth_guard(),*extra],type_ignores=[]),
        '<actual-batch-profile-guards>','exec')


def test_actual_cli_guards_require_exact_host_and_guest_chain(tmp_path):
    launcher=load_script('batch_cli_launcher','start-menu.py')
    host=launcher.profile_environment(host_environment(tmp_path),natural_boot=True)
    host.update(SEED_BACKUP='alllang',A7C2_DIRECTORY_SD_PROFILE='directory-vvfat-256gb-v1')
    scope={**guard_scope(),**{name:getattr(backup,name) for name in dir(backup) if name.endswith('_PROFILE')},
           **{name+'_profile':profile for name,profile in OLD_PROFILES.items()},
           **{name+'_profile':profile for name,_,profile in FAMILIES}}
    code=batch_guard_code()
    def run(env,**changes):
        with mock.patch.dict(os.environ,env,clear=True):exec(code,{**scope,**changes})
    run(host)
    run({},**{name:'' for name in scope if name.endswith('_profile')})
    for name in ('adf_proc_path',*(name for name in OLD_PROFILES if name!='adf_proc'),
                 *(name for name,_,_ in FAMILIES)):
        with pytest.raises(SystemExit):run(host,**{name+'_profile':'unknown'})
    for name in ('adf_proc_path',*(name for name in OLD_PROFILES if name!='adf_proc'),
                 *(name for name,_,_ in FAMILIES[:-1])):
        with pytest.raises(SystemExit):run(host,**{name+'_profile':''})
    for key in ('A7C2_BB_SET_MODE','A7C2_IMAGING_CONNECT','A7C2_IMAGING_CONTROL_CONNECT',
                'A7C2_IMAGING_ADF_CONNECT','A7C2_INFRABB_VEF_CONNECT','A7C2_INFRABB_VEF_CONTROL_CONNECT',
                SIXTH_HOST,*('A7C2_'+switch for _,switch,_ in FAMILIES),
                'SEED_BACKUP','A7C2_DIRECTORY_SD_PROFILE','MENU_PIN_REGISTRY','MENU_PIN_CONTROL_MEMORY','MENU_PIN_CONNECTION'):
        bad=dict(host);bad.pop(key)
        with pytest.raises(SystemExit):run(bad)
        with pytest.raises(SystemExit):run({**host,key:'unknown'})
    for key in backup.BB_MODE_CONFLICTS:
        with pytest.raises(SystemExit):run({**host,key:'1'})


def test_prepare_rejects_new_bad_switches_and_broken_guest_chain_before_candidate(tmp_path,monkeypatch):
    launcher=load_script('batch_prepare_launcher','start-menu.py')
    host=launcher.profile_environment(host_environment(tmp_path),natural_boot=True)
    host.update(SEED_BACKUP='alllang',A7C2_DIRECTORY_SD_PROFILE='directory-vvfat-256gb-v1')
    def no_build(*args):raise AssertionError('invalid batch admission reached candidate or output work')
    monkeypatch.setattr(backup,'validate_build',no_build)
    keys=('MENU_CP_BACKGROUND','MENU_UDATE_DISTRIBUTION','MENU_TOUCH_PANEL','MENU_TCIN_DETECT',
          'MENU_DFS_SELECTOR','MENU_VEF_PATH','MENU_ADF_PROC_PATH','MENU_ADF_SET_INPUT',
          'MENU_ADF_SET_OUTPUT','MENU_BB_SET_MODE','MENU_IMAGING_CONNECT','MENU_IMAGING_CONTROL_CONNECT',
          'MENU_IMAGING_ADF_CONNECT','MENU_INFRABB_VEF_CONNECT','MENU_INFRABB_VEF_CONTROL_CONNECT',
          'MENU_VEF_PINMEM_INPUT_CONNECT','MENU_PIN_REGISTRY','MENU_PIN_CONTROL_MEMORY','MENU_PIN_CONNECTION',
          'SEED_BACKUP','A7C2_DIRECTORY_SD_PROFILE',
          *('A7C2_'+switch for _,switch,_ in FAMILIES),
          *('MENU_'+switch for _,switch,_ in FAMILIES[:-1]))
    for missing in keys:
        bad=dict(host);bad.pop(missing)
        with pytest.raises(ValueError):backup.prepare_profile(HERE,bad)
    for key,value in (
        *((prefix+switch,'unknown') for _,switch,_ in FAMILIES for prefix in ('A7C2_','MENU_')),
        ('SEED_BACKUP','private'),('SEED_BACKUP','full'),('QEMU_CPU_COUNT','2'),
        *[(key,'1') for key in backup.BB_MODE_CONFLICTS]):
        with pytest.raises(ValueError):backup.prepare_profile(HERE,{**host,key:value})
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize('enabled',[False,True])
def test_real_receipt_manifest_and_typed_validator_cover_all_new_fields(tmp_path,enabled):
    build=build_fixture(tmp_path)[0]
    launcher=load_script('batch_receipt_launcher','start-menu.py')
    host=launcher.profile_environment(host_environment(tmp_path,build,steps=3 if enabled else 0),natural_boot=True)
    with directory_lease(tmp_path/'card') as lease:
        host.update(directory_profile(HERE,lease,tmp_path/'directory-profile'))
        host.update(backup.prepare_profile(HERE,host))
    path=Path(host['MENU_BACKUP_PROFILE_RECEIPT']);receipt=json.loads(path.read_text())
    active={**OLD_PROFILES,**{name:profile if enabled else '' for name,_,profile in FAMILIES}}
    fields={name:getattr(backup,name+'_profile_fields')(profile) for name,profile in active.items()}
    for expected in fields.values():
        for key,value in expected.items():
            assert key in receipt and type(receipt[key]) is type(value)
            assert json.dumps(receipt[key])==json.dumps(value)
    tree=ast.parse((HERE/'qemu-menu-probe.py').read_text())
    manifest=next(node.value for node in tree.body if isinstance(node,ast.Assign) and
                  isinstance(node.targets[0],ast.Name) and node.targets[0].id=='manifest')
    scope={name+'_profile':profile for name,profile in active.items()}
    scope.update(pinmem_hdmi_video_connection_profile='',pinmem_osd_connection_profile='',cp302c_no_transition_profile='')
    scope.update({name+'_profile_fields':getattr(backup,name+'_profile_fields') for name in PROFILE_NAMES})
    for name,_,_ in FAMILIES:
        spread=next(value for key,value in zip(manifest.keys,manifest.values) if key is None and
                    isinstance(value,ast.Call) and isinstance(value.func,ast.Name) and
                    value.func.id==name+'_profile_fields')
        assert eval(compile(ast.Expression(spread),'<actual-batch-manifest-spread>','eval'),scope)==fields[name]
    validator=next(node for node in tree.body if isinstance(node,ast.If) and
        isinstance(node.test,ast.Name) and node.test.id=='backup_sync' and any(
            isinstance(call,ast.Call) and isinstance(call.func,ast.Name) and call.func.id=='validate_build'
            for call in ast.walk(node)))
    code=compile(ast.Module(body=[validator],type_ignores=[]),'<actual-batch-receipt-validator>','exec')
    scope.update(os=os,json=json,Path=Path,base=HERE,sha256_file=backup.sha,backup_sync=backup.PROFILE,
        env=host,kernel_script=Path(host['MENU_KERNEL_SCRIPT']),board_dtb=Path(host['MENU_DTB']),
        adf_proc_path_profile=backup.ADF_PROFILE,
        udate_kernel_receipt=HERE.parents[1]/'report/virtual-cp/udate-distribution/verification.json',
        overwrite_manifest=None,settings_restore_manifest=None)
    with mock.patch.dict(os.environ,host,clear=True):
        exec(code,scope)
        for name,_,_ in FAMILIES:
            for key,value in fields[name].items():
                bad=copy.deepcopy(receipt);bad.pop(key);path.write_text(json.dumps(bad))
                with pytest.raises(ValueError,match='identity/admission mismatch'):exec(code,scope)
                bad[key]=(int(not value) if type(value) is bool else float(value) if type(value) is int else 'wrong')
                path.write_text(json.dumps(bad))
                with pytest.raises(ValueError,match='identity/admission mismatch'):exec(code,scope)
            if enabled:
                bad=copy.deepcopy(receipt);bad[name+'_capture_verified']=True;path.write_text(json.dumps(bad))
                with pytest.raises(ValueError,match='identity/admission mismatch'):exec(code,scope)
        if enabled:
            for key,indices in (
                ('vef_pinmem_control_connection_source_pin',[2]),
                ('vef_pinmem_control_connection_peer_pin',[2]),
                ('vef_pinmem_control_connection_source_state_path',[2]),
                ('pinmem_peer_connections_edges',[0,'source_pin',0]),
                ('pinmem_peer_connections_edges',[1,'peer_pin',2]),
                ('pinmem_peer_connections_edges',[2,'source_pin',2]),
                ('pinmem_peer_connections_edges',[1,'peer_slot']),
                ('adf_hdmi_audio_connection_source_pin',[2]),
                ('adf_hdmi_audio_connection_peer_pin',[2])):
                for replacement in (0.0,False):
                    bad=copy.deepcopy(receipt);target=bad[key]
                    for index in indices[:-1]:target=target[index]
                    assert type(target[indices[-1]]) is int and target[indices[-1]]==0
                    target[indices[-1]]=replacement;path.write_text(json.dumps(bad))
                    with pytest.raises(ValueError,match='identity/admission mismatch'):exec(code,scope)
        path.write_text(json.dumps(receipt));exec(code,scope)


def test_actual_batch_dispatch_precedes_legacy_gate_and_preserves_fallthrough():
    source=(HERE/'menu-observe.c').read_text()
    start=source.index('int osal_snd_msg(unsigned int id, void *message) {')
    end=source.index('full_vef_resource_send_enter(id,vef_path_enabled)',start)
    prefix=' '.join(source[start:end].split())
    assert 'id==FULL_VEF_CP && (vef_pinmem_input_connection_enabled || vef_pinmem_control_connection_enabled)' in prefix
    assert 'id==FULL_PINMEM_CP && pinmem_peer_connections_enabled' in prefix
    assert 'id==FULL_ADF_CP && adf_hdmi_audio_connection_enabled' in prefix
    for name in ('full_vef_pinmem_input_connection_dispatch','full_vef_pinmem_control_connection_dispatch',
                 'full_scalar_connection_native_dispatch','full_adf_connection_native_dispatch',
                 'full_pinmem_drawinfo_connection_native_dispatch','full_adf_hdmi_audio_connection_dispatch'):
        assert prefix.count(name+'(')==1
    assert ('if(full_scalar_connection_native_dispatch(id,message,&io,&scalar,1,&result) || '
            'full_adf_connection_native_dispatch(id,message,&io,&adf,1,&result) || '
            'full_pinmem_drawinfo_connection_native_dispatch(id,message,&io,&drawinfo,1,&result))return result;') in prefix


def exported_guest(tmp_path,steps=3):
    launcher=load_script('batch_export_launcher','start-menu.py')
    host=launcher.profile_environment(host_environment(tmp_path,steps=steps),natural_boot=True)
    host.update(MENU_BACKUP_SYNC=backup.PROFILE,SEED_BACKUP='alllang',
                A7C2_DIRECTORY_SD_PROFILE='directory-vvfat-256gb-v1')
    return host,clean_guest_environment(menu_probe_setup(host))


@pytest.mark.parametrize('steps',[0,1,2,3])
def test_actual_clean_guest_exports_and_constructor_enable_only_selected_stages(tmp_path,bb_constructor,steps):
    host,guest=exported_guest(tmp_path,steps)
    assert all('A7C2_'+switch not in guest for _,switch,_ in FAMILIES)
    assert all(key not in guest for key in (*PREDECESSORS,SIXTH_HOST) if key.startswith('A7C2_'))
    assert guest['MENU_VEF_PINMEM_INPUT_CONNECT']==backup.FULL_VEF_PINMEM_INPUT_CONNECTION_PROFILE
    setup=menu_probe_setup(host)
    for index,(_,switch,profile) in enumerate(FAMILIES):
        assert guest.get('MENU_'+switch)==(profile if index<steps else None)
        assert sum(line=='export MENU_'+switch+'='+profile for line in setup)==int(index<steps)
    log=bb_constructor(guest)
    assert ' pinmem_input=1 pinmem_input_init=1' in log
    assert (' pinmem_control=%d pinmem_control_init=%d pinmem_peers=%d scalar_init=%d '
            'pinmem_adf_init=%d drawinfo_init=%d hdmi_audio=%d hdmi_audio_init=%d'%(
                int(steps>=1),int(steps>=1),int(steps>=2),int(steps>=2),int(steps>=2),
                int(steps>=2),int(steps>=3),int(steps>=3))) in log
    for tag,enabled in (('FULL_VEF_PINMEM_CONTROL_CONNECT_PROFILE ',steps>=1),
                        ('FULL_PINMEM_PEER_CONNECT_PROFILE ',steps>=2),
                        ('FULL_ADF_HDMI_AUDIO_CONNECT_PROFILE ',steps>=3)):
        assert (tag in log)==enabled


def test_missing_earlier_host_or_guest_export_blocks_every_later_export(tmp_path):
    host,guest=exported_guest(tmp_path)
    for key in ('MENU_BB_SET_MODE','A7C2_IMAGING_CONNECT','MENU_IMAGING_CONNECT',
                'A7C2_IMAGING_CONTROL_CONNECT','MENU_IMAGING_CONTROL_CONNECT','A7C2_IMAGING_ADF_CONNECT',
                'MENU_IMAGING_ADF_CONNECT','A7C2_INFRABB_VEF_CONNECT','MENU_INFRABB_VEF_CONNECT',
                'A7C2_INFRABB_VEF_CONTROL_CONNECT','MENU_INFRABB_VEF_CONTROL_CONNECT',
                SIXTH_HOST,'MENU_VEF_PINMEM_INPUT_CONNECT'):
        changed=clean_guest_environment(menu_probe_setup({**host,key:''}))
        assert all('MENU_'+switch not in changed for _,switch,_ in FAMILIES)
    for index,(_,switch,_) in enumerate(FAMILIES):
        for prefix in ('A7C2_','MENU_'):
            bad=dict(host);bad.pop(prefix+switch)
            changed=clean_guest_environment(menu_probe_setup(bad))
            assert all('MENU_'+key not in changed for _,key,_ in FAMILIES[index:])
    assert guest['MENU_ADF_HDMI_AUDIO_CONNECT']==FAMILIES[2][2]


def test_actual_constructor_rejects_missing_or_wrong_earlier_exports(tmp_path,bb_constructor):
    _,guest=exported_guest(tmp_path)
    for key in ('MENU_VEF_PINMEM_INPUT_CONNECT','MENU_INFRABB_VEF_CONTROL_CONNECT','MENU_INFRABB_VEF_CONNECT',
                'MENU_IMAGING_ADF_CONNECT','MENU_IMAGING_CONTROL_CONNECT','MENU_IMAGING_CONNECT',
                'MENU_BB_SET_MODE','MENU_ADF_SET_OUTPUT','MENU_BACKUP_SYNC','MENU_CP_BACKGROUND','MENU_UDATE_DISTRIBUTION',
                'MENU_TOUCH_PANEL','MENU_TCIN_DETECT','MENU_DFS_SELECTOR','MENU_AUDIO_BOOT_CONFIG',
                'MENU_PIN_REGISTRY','MENU_PIN_CONTROL_MEMORY','MENU_PIN_CONNECTION'):
        for value in (None,'unknown'):
            bad=dict(guest)
            if value is None:bad.pop(key)
            else:bad[key]=value
            log=bb_constructor(bad)
            assert ' pinmem_control=0 pinmem_control_init=0 pinmem_peers=0 scalar_init=0 pinmem_adf_init=0 drawinfo_init=0 hdmi_audio=0 hdmi_audio_init=0' in log


def test_actual_constructor_old_owner_failures_prevent_new_owner_calls(tmp_path,bb_constructor):
    _,guest=exported_guest(tmp_path)
    for options in ({'input_enabled':False},{'owner_rc':-1021},{'imaging_owner_rc':-1021},
                    {'control_owner_rc':-1021},{'adf_owner_rc':-1021},{'vef_owner_rc':-1021},
                    {'vef_control_owner_rc':-1021},{'pinmem_input_owner_rc':-1021}):
        assert ' pinmem_control=0 pinmem_control_init=0 pinmem_peers=0 scalar_init=0 pinmem_adf_init=0 drawinfo_init=0 hdmi_audio=0 hdmi_audio_init=0' in bb_constructor(guest,**options)


@pytest.mark.parametrize('owner,expected',[
    ('pinmem_control_owner_rc','pinmem_control=0 pinmem_control_init=1 pinmem_peers=0 scalar_init=0 pinmem_adf_init=0 drawinfo_init=0 hdmi_audio=0 hdmi_audio_init=0'),
    ('scalar_owner_rc','pinmem_control=1 pinmem_control_init=1 pinmem_peers=0 scalar_init=1 pinmem_adf_init=0 drawinfo_init=0 hdmi_audio=0 hdmi_audio_init=0'),
    ('adf_connection_owner_rc','pinmem_control=1 pinmem_control_init=1 pinmem_peers=0 scalar_init=1 pinmem_adf_init=1 drawinfo_init=0 hdmi_audio=0 hdmi_audio_init=0'),
    ('drawinfo_owner_rc','pinmem_control=1 pinmem_control_init=1 pinmem_peers=0 scalar_init=1 pinmem_adf_init=1 drawinfo_init=1 hdmi_audio=0 hdmi_audio_init=0'),
    ('hdmi_audio_owner_rc','pinmem_control=1 pinmem_control_init=1 pinmem_peers=1 scalar_init=1 pinmem_adf_init=1 drawinfo_init=1 hdmi_audio=0 hdmi_audio_init=1'),
])
def test_actual_constructor_each_new_owner_failure_stops_downstream(tmp_path,bb_constructor,owner,expected):
    _,guest=exported_guest(tmp_path)
    assert ' '+expected in bb_constructor(guest,**{owner:-1021})


def test_actual_constructor_wrong_or_off_new_profile_and_selftest_block_downstream(tmp_path,bb_constructor):
    _,guest=exported_guest(tmp_path)
    for index,(_,switch,_) in enumerate(FAMILIES):
        for value in ('','unknown'):
            log=bb_constructor({**guest,'MENU_'+switch:value})
            if index==0:assert ' pinmem_control=0 pinmem_control_init=0' in log
            if index<=1:assert ' pinmem_peers=0 scalar_init=0 pinmem_adf_init=0 drawinfo_init=0' in log
            assert ' hdmi_audio=0 hdmi_audio_init=0' in log
    log=bb_constructor({**guest,'MENU_OBSERVE_SELFTEST':'1'})
    assert ' pinmem_control=0 pinmem_control_init=0 pinmem_peers=0 scalar_init=0 pinmem_adf_init=0 drawinfo_init=0 hdmi_audio=0 hdmi_audio_init=0' in log
