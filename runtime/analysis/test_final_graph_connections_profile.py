"""Independent final graph profile admission; runtime capture claims remain false."""
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
                                      load_script, menu_probe_setup)
from test_infrabb_vef_control_connection_profile import PROFILE_NAMES
from test_native_graph_batch_profile import (FAMILIES as PREVIOUS_FAMILIES, OLD_PROFILES,
    SIXTH_HOST, batch_guard_code, host_environment as previous_environment)
from test_vef_pinmem_input_connection_profile import PREDECESSORS

FAMILIES=(
    ('pinmem_hdmi_video_connection','PINMEM_HDMI_VIDEO_CONNECT',
     backup.FULL_PINMEM_HDMI_VIDEO_CONNECTION_PROFILE,'pinmem-hdmi-video-connection.h'),
    ('pinmem_osd_connection','PINMEM_OSD_CONNECT',
     backup.FULL_PINMEM_OSD_CONNECTION_PROFILE,'pinmem-osd-connection.h'),
)
COMMON_CLAIMS={
    'original_cp_executed','original_event_pointer_verified','original_task_scheduler_verified',
    'original_RTOS_timing_verified','hardware_verified','ap_consumed','runtime_consumed',
    'native_verified','connection_verified','format_consumed','general_format_ready',
    'cmos_verified','frames_verified','pcm_verified','capture_verified',
}
CLAIMS=(COMMON_CLAIMS|{'original_cp_pointer_verified','conditions_consumed','upm_consumed',
                     'hdmi_current_state_original_verified'},
        COMMON_CLAIMS|{'original_cp_pages_verified','original_allocator_capacity_verified',
                     'metadata_ready','gpe_ready'})


def host_environment(tmp_path,build=None,video=True,osd=True,audio=False):
    env=previous_environment(tmp_path,build,steps=3 if audio else 2)
    for enabled,(_,switch,profile,_) in zip((video,osd),FAMILIES):
        if enabled:env['A7C2_'+switch]=profile
    return env


def selected_environment(tmp_path,**options):
    launcher=load_script('final_graph_launcher','start-menu.py')
    return launcher.profile_environment(host_environment(tmp_path,**options),natural_boot=True)


def exported_guest(tmp_path,**options):
    host=selected_environment(tmp_path,**options)
    host.update(MENU_BACKUP_SYNC=backup.PROFILE,SEED_BACKUP='alllang',
                A7C2_DIRECTORY_SD_PROFILE='directory-vvfat-256gb-v1')
    return host,clean_guest_environment(menu_probe_setup(host))


@pytest.mark.parametrize('index',[0,1])
def test_fields_are_exact_default_off_intentions_with_no_promoted_runtime_claim(index):
    name,switch,profile,header=FAMILIES[index]
    function=getattr(backup,name+'_profile_fields')
    fields=function(profile);off=function('');prefix=name+'_'
    assert fields.keys()==off.keys()
    for key,value in off.items():
        assert value is (False if key[len(prefix):] in CLAIMS[index] else None)
    for suffix in CLAIMS[index]:
        assert fields[prefix+suffix] is False
    expected={
        'profile':profile,'predecessor_profile':backup.FULL_PINMEM_PEER_CONNECTIONS_PROFILE,
        'request_bytes':64,'reply_bytes':56,'reply_command':0x8001,'unique_reply_count':1,
        'source_state_path':[1,2,0],'sink_state_path':[1,0],
        'source_event':6,'event_parameter_bytes':12,'saved_request_bytes':64,
        'predecessors_require_ap_consumed':True,'predecessors_require_clean':True,
        'predecessors_require_no_outstanding':True,'audio_edge_required':False,
    }
    for suffix,value in expected.items():
        assert json.dumps(fields[prefix+suffix])==json.dumps(value)
    assert '#define FULL_'+switch.replace('_CONNECT','_CONNECTION_PROFILE')+' "'+profile+'"' in (HERE/'device-models'/header).read_text()
    with pytest.raises(ValueError):function('unknown')


def test_video_contract_keeps_dynamic_notifications_pending_until_original_receive_and_same_thread_free():
    fields=backup.pinmem_hdmi_video_connection_profile_fields(FAMILIES[0][2])
    expected={
        'source_pin':[4,2,0,0x90590818],'peer_pin':[4,1,0,0x909a015a],
        'source_registry_count':13,'source_registry_slot':7,'sink_registry_count':2,'sink_registry_slot':0,
        'source_gate_initial_value':0,'source_gate_unknown_policy':'refused-no-F01F-write',
        'hdmi_state_source':'owner-init-before-any-HDMI-input-never-forced-at-Connect',
        'hdmi_state_scope':'finite-virtual-Initializing-to-HPD-low',
        'hdmi_live_prefix_commands':[0x0102,0x0109,0x0127],
        'hdmi_live_prefix_payload_policy':'actual-owned-message-queue-not-caller-supplied',
        'hdmi_existing_config_replay_count':8,
        'condition_source_sid':0x91ca0816,'condition_payload_bytes':20,
        'condition_payload_words':['2','dynamic-condition-id','1','0','0'],
        'condition_ids':[0,0x17,0x16,0x15,0x14,0x13,0x12,0x11,0x23,0x22,0x21,0x30],
        'condition_destination_policy':'actual-registered-condition-queue',
        'condition_batch_count':2,'condition_message_count':24,
        'upm_destination_sid':0x80920572,'upm_message_count':2,'upm_message_bytes':16,'upm_ack_count':0,
        'notification_consumption_policy':'original-successful-receive-and-same-receiver-thread-real-free',
        'send_or_provider_cleanup_counts_as_consumption':False,
        'driver_initialization_bytes':18,'driver_config_bytes':36,'driver_job_count':6,
        'driver_policy_slot':4,'driver_policy_row':0,'driver_completion_bytes':12,
        'completion_policy':'unique-AP-reply-only-after-all-condition-UPM-and-driver-readiness-consumed',
        'pending_policy':'retain-owned-request-no-AP-ACK','osd_edge_required':False,'frame_count':0,
    }
    for key,value in expected.items():
        assert json.dumps(fields['pinmem_hdmi_video_connection_'+key])==json.dumps(value)


def test_osd_contract_keeps_versions_unknown_masks_persistent_references_and_metadata_only_readiness():
    fields=backup.pinmem_osd_connection_profile_fields(FAMILIES[1][2])
    expected={
        'source_pin':[1,3,0,0x90590818],'peer_pin':[1,3,0,0x9080003b],
        'source_registry_count':13,'source_registry_slot':8,'sink_registry_count':1,'sink_registry_slot':0,
        'pool_unit':0xe1700,'pool_slots':16,'pool_extent_bytes':256,'pool_backing_bytes':4096,
        'pool_capacity_policy':'explicit-virtual-capacity-not-original-allocator-capacity',
        'resource_banks':[{'tag':0,'count':4,'payload_bytes':64},
                          {'tag':0x101,'count':4,'payload_bytes':16},
                          {'tag':0x100,'count':4,'payload_bytes':128},
                          {'tag':0x102,'count':4,'payload_bytes':32}],
        'connected_live_resources':16,'connected_owner_references':32,'connected_open_references':32,
        'reference_policy':'persistent-creator-and-consumer-no-premature-Free',
        'dmm_commands':[0x20,0x21,0x24],'dmm_command_count':48,
        'peer_dmm_request_bytes':40,'pinmem_dmm_request_bytes':152,
        'notice_count':16,'notice_bytes':80,'notice_command':[0x1000,0x0102],
        'pinmem_numeric_version':0x01000000,'pinmem_version_le':[0,0,0,1],
        'peer_numeric_version':1,'peer_version_le':[1,0,0,0],'peer_header_flags':3,
        'unknown_payload_bytes':{'tag100':121,'tag101':2,'tag102':6},
        'initial_inactive_row_count':5,'inactive_tag100_backing_count_after':0,
        'inactive_tag100_cached_count_after':1,'inactive_update_notice_count':0,
        'inactive_update_share_count':0,'inactive_update_open_count':0,
        'metadata_readiness_policy':'all-four-tag101-and-tag102-banks-only',
        'old_dmm_pool_extra_operations':0,'hdmi_video_edge_required':False,
        'predecessor_three_format_caches_preserved':True,'foreign_speech_live_preserved':True,
    }
    for key,value in expected.items():
        assert json.dumps(fields['pinmem_osd_connection_'+key])==json.dumps(value)


@pytest.mark.parametrize('video,osd,audio',[
    (False,False,False),(True,False,False),(False,True,False),(True,True,False),
    (False,False,True),(True,False,True),(False,True,True),(True,True,True)])
def test_launcher_and_actual_guest_exports_keep_final_edges_and_audio_independent(tmp_path,video,osd,audio):
    host,guest=exported_guest(tmp_path,video=video,osd=osd,audio=audio)
    setup=menu_probe_setup(host)
    for enabled,(_,switch,profile,_) in zip((video,osd),FAMILIES):
        assert host.get('MENU_'+switch)==(profile if enabled else None)
        assert guest.get('MENU_'+switch)==(profile if enabled else None)
        assert sum(line=='export MENU_'+switch+'='+profile for line in setup)==int(enabled)
        assert 'A7C2_'+switch not in guest
    assert ('MENU_ADF_HDMI_AUDIO_CONNECT' in guest)==audio
    assert guest['MENU_PINMEM_PEER_CONNECT']==backup.FULL_PINMEM_PEER_CONNECTIONS_PROFILE


@pytest.mark.parametrize('name,switch,profile,header',FAMILIES)
def test_forged_guest_only_flags_do_not_enable_host_profile(tmp_path,name,switch,profile,header):
    launcher=load_script('final_graph_forged_launcher','start-menu.py')
    for env in ({},{'MENU_'+switch:profile},
                {**host_environment(tmp_path,video=False,osd=False),'MENU_'+switch:profile}):
        selected=launcher.profile_environment(env,natural_boot=True)
        assert 'MENU_'+switch not in selected
    with pytest.raises(ValueError):
        launcher.profile_environment({**host_environment(tmp_path),'A7C2_'+switch:'unknown'},natural_boot=True)


@pytest.mark.parametrize('name,switch,profile,header',FAMILIES)
def test_launcher_rejects_every_earlier_missing_link_private_seed_and_conflicts_before_files(tmp_path,name,switch,profile,header):
    launcher=load_script('final_graph_unsafe_launcher','start-menu.py')
    env=host_environment(tmp_path,video=switch=='PINMEM_HDMI_VIDEO_CONNECT',osd=switch=='PINMEM_OSD_CONNECT')
    for key in (*PREDECESSORS,SIXTH_HOST,'A7C2_VEF_PINMEM_CONTROL_CONNECT','A7C2_PINMEM_PEER_CONNECT'):
        bad=dict(env);bad.pop(key)
        with pytest.raises(ValueError):launcher.profile_environment(bad,natural_boot=True)
    with pytest.raises(ValueError):launcher.profile_environment(env,natural_boot=False)
    for key,value in (
        ('SEED_BACKUP','private'),('SEED_BACKUP','full'),('MENU_USB_NET','1'),
        ('A7C2_DIRECTORY_SD','relative'),('A7C2_HOST_SD','256gb'),('A7C2_SD_SPARSE','10g-empty'),
        *[(key,'1') for key in backup.BB_MODE_CONFLICTS]):
        with pytest.raises(ValueError):launcher.profile_environment({**env,key:value},natural_boot=True)
    assert not list(tmp_path.iterdir())


def final_guard_code():
    tree=ast.parse((HERE/'qemu-menu-probe.py').read_text())
    guards=[]
    for prefix in ('PinMem HDMI video connection requires','PinMem OSD connection requires'):
        guards.append(next(node for node in tree.body if isinstance(node,ast.If) and any(
            isinstance(call,ast.Call) and isinstance(call.func,ast.Attribute) and
            ast.unparse(call.func)=='parser.error' and call.args and isinstance(call.args[0],ast.Constant) and
            str(call.args[0].value).startswith(prefix) for call in ast.walk(node))))
    return compile(ast.Module(body=guards,type_ignores=[]),'<actual-final-graph-guards>','exec')


def test_actual_cli_guards_require_both_exact_host_admission_and_entire_guest_chain(tmp_path):
    host,_=exported_guest(tmp_path)
    scope={**guard_scope(),**{name:getattr(backup,name) for name in dir(backup) if name.endswith('_PROFILE')},
           **{name+'_profile':profile for name,profile in OLD_PROFILES.items()},
           **{name+'_profile':profile for name,_,profile in PREVIOUS_FAMILIES[:2]},
           'adf_hdmi_audio_connection_profile':'',
           **{name+'_profile':profile for name,_,profile,_ in FAMILIES}}
    before=batch_guard_code();after=final_guard_code()
    def run(env,**changes):
        with mock.patch.dict(os.environ,env,clear=True):
            active={**scope,**changes};exec(before,active);exec(after,active)
    run(host)
    # The directory profile derives its USB storage bus with this existing internal marker.
    run({**host,'MENU_USB_NET':'1'})
    run({},**{name:'' for name in scope if name.endswith('_profile')})
    for name in ('adf_proc_path',*(name for name in OLD_PROFILES if name!='adf_proc'),
                 *(name for name,_,_ in PREVIOUS_FAMILIES[:2])):
        for value in ('','unknown'):
            with pytest.raises(SystemExit):run(host,**{name+'_profile':value})
    for name,switch,profile,_ in FAMILIES:
        with pytest.raises(SystemExit):run(host,**{name+'_profile':'unknown'})
        for key in ('A7C2_'+switch,'A7C2_PINMEM_PEER_CONNECT','A7C2_VEF_PINMEM_CONTROL_CONNECT',
                    SIXTH_HOST,'SEED_BACKUP','A7C2_DIRECTORY_SD_PROFILE',
                    'MENU_PIN_REGISTRY','MENU_PIN_CONTROL_MEMORY','MENU_PIN_CONNECTION'):
            bad=dict(host);bad.pop(key)
            with pytest.raises(SystemExit):run(bad)
            with pytest.raises(SystemExit):run({**host,key:'unknown'})
    for key in backup.BB_MODE_CONFLICTS:
        with pytest.raises(SystemExit):run({**host,key:'1'})
    for active in (0,1):
        run(host,**{FAMILIES[1-active][0]+'_profile':''})


def test_prepare_rejects_invalid_admission_before_candidate_or_outputs(tmp_path,monkeypatch):
    host,_=exported_guest(tmp_path)
    def no_build(*args):raise AssertionError('invalid final edge reached candidate work')
    monkeypatch.setattr(backup,'validate_build',no_build)
    for key in ('MENU_CP_BACKGROUND','MENU_UDATE_DISTRIBUTION','MENU_TOUCH_PANEL','MENU_TCIN_DETECT',
                'MENU_DFS_SELECTOR','MENU_VEF_PATH','MENU_ADF_PROC_PATH','MENU_ADF_SET_INPUT',
                'MENU_ADF_SET_OUTPUT','MENU_BB_SET_MODE','MENU_IMAGING_CONNECT','MENU_IMAGING_CONTROL_CONNECT',
                'MENU_IMAGING_ADF_CONNECT','MENU_INFRABB_VEF_CONNECT','MENU_INFRABB_VEF_CONTROL_CONNECT',
                'MENU_VEF_PINMEM_INPUT_CONNECT','MENU_VEF_PINMEM_CONTROL_CONNECT','MENU_PINMEM_PEER_CONNECT',
                'MENU_PIN_REGISTRY','MENU_PIN_CONTROL_MEMORY','MENU_PIN_CONNECTION',
                'SEED_BACKUP','A7C2_DIRECTORY_SD_PROFILE','A7C2_BACKUP_SYNC',
                *('A7C2_'+switch for _,switch,_,_ in FAMILIES)):
        bad=dict(host);bad.pop(key)
        with pytest.raises(ValueError):backup.prepare_profile(HERE,bad)
    for key,value in (
        *((prefix+switch,'unknown') for _,switch,_,_ in FAMILIES for prefix in ('A7C2_','MENU_')),
        ('SEED_BACKUP','private'),('SEED_BACKUP','full'),('QEMU_CPU_COUNT','2'),
        *[(key,'1') for key in backup.BB_MODE_CONFLICTS]):
        with pytest.raises(ValueError):backup.prepare_profile(HERE,{**host,key:value})
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize('video,osd',[(False,False),(True,False),(False,True),(True,True)])
def test_real_receipt_manifest_and_typed_validation_include_every_final_edge_field(tmp_path,video,osd):
    build=build_fixture(tmp_path)[0]
    host=selected_environment(tmp_path,build=build,video=video,osd=osd)
    with directory_lease(tmp_path/'card') as lease:
        host.update(directory_profile(HERE,lease,tmp_path/'directory-profile'))
        host.update(backup.prepare_profile(HERE,host))
    path=Path(host['MENU_BACKUP_PROFILE_RECEIPT']);receipt=json.loads(path.read_text())
    active={**OLD_PROFILES,**{name:profile for name,_,profile in PREVIOUS_FAMILIES[:2]},
            'adf_hdmi_audio_connection':'',
            **{name:profile if enabled else '' for enabled,(name,_,profile,_) in zip((video,osd),FAMILIES)}}
    fields={name:getattr(backup,name+'_profile_fields')(active[name]) for name,_,_,_ in FAMILIES}
    tree=ast.parse((HERE/'qemu-menu-probe.py').read_text())
    manifest=next(node.value for node in tree.body if isinstance(node,ast.Assign) and
                  isinstance(node.targets[0],ast.Name) and node.targets[0].id=='manifest')
    scope={name+'_profile':profile for name,profile in active.items()}
    scope['cp302c_no_transition_profile']=''
    scope.update({name+'_profile_fields':getattr(backup,name+'_profile_fields') for name in PROFILE_NAMES})
    for name,_,_,_ in FAMILIES:
        spread=next(value for key,value in zip(manifest.keys,manifest.values) if key is None and
                    isinstance(value,ast.Call) and isinstance(value.func,ast.Name) and
                    value.func.id==name+'_profile_fields')
        assert eval(compile(ast.Expression(spread),'<actual-final-manifest-spread>','eval'),scope)==fields[name]
        for key,value in fields[name].items():
            assert key in receipt and type(receipt[key]) is type(value)
            assert json.dumps(receipt[key])==json.dumps(value)
    validator=next(node for node in tree.body if isinstance(node,ast.If) and
        isinstance(node.test,ast.Name) and node.test.id=='backup_sync' and any(
            isinstance(call,ast.Call) and isinstance(call.func,ast.Name) and call.func.id=='validate_build'
            for call in ast.walk(node)))
    code=compile(ast.Module(body=[validator],type_ignores=[]),'<actual-final-receipt-validator>','exec')
    scope.update(os=os,json=json,Path=Path,base=HERE,sha256_file=backup.sha,backup_sync=backup.PROFILE,
        env=host,kernel_script=Path(host['MENU_KERNEL_SCRIPT']),board_dtb=Path(host['MENU_DTB']),
        adf_proc_path_profile=backup.ADF_PROFILE,
        udate_kernel_receipt=HERE.parents[1]/'report/virtual-cp/udate-distribution/verification.json',
        overwrite_manifest=None,settings_restore_manifest=None)
    with mock.patch.dict(os.environ,host,clear=True):
        exec(code,scope)
        for name,_,_,_ in FAMILIES:
            for key,value in fields[name].items():
                bad=copy.deepcopy(receipt);bad.pop(key);path.write_text(json.dumps(bad))
                with pytest.raises(ValueError,match='identity/admission mismatch'):exec(code,scope)
                bad[key]=(int(not value) if type(value) is bool else float(value) if type(value) is int else 'wrong')
                path.write_text(json.dumps(bad))
                with pytest.raises(ValueError,match='identity/admission mismatch'):exec(code,scope)
        nested=[]
        if video:nested.extend((
            ('pinmem_hdmi_video_connection_source_pin',[2]),
            ('pinmem_hdmi_video_connection_condition_ids',[0])))
        if osd:nested.extend((
            ('pinmem_osd_connection_source_pin',[2]),
            ('pinmem_osd_connection_resource_banks',[0,'tag']),
            ('pinmem_osd_connection_pinmem_version_le',[0]),
            ('pinmem_osd_connection_unknown_payload_bytes',['tag101'])))
        for key,indices in nested:
            bad=copy.deepcopy(receipt);target=bad[key]
            for index in indices[:-1]:target=target[index]
            current=target[indices[-1]]
            for replacement in (float(current),bool(current)):
                assert type(current) is int
                target[indices[-1]]=replacement;path.write_text(json.dumps(bad))
                with pytest.raises(ValueError,match='identity/admission mismatch'):exec(code,scope)
        path.write_text(json.dumps(receipt));exec(code,scope)


@pytest.mark.parametrize('video,osd',[(False,False),(True,False),(False,True),(True,True)])
def test_actual_c_constructor_enables_only_requested_final_edges_without_audio(tmp_path,bb_constructor,video,osd):
    _,guest=exported_guest(tmp_path,video=video,osd=osd)
    log=bb_constructor(guest)
    assert ' pinmem_peers=1 scalar_init=1 pinmem_adf_init=1 drawinfo_init=1 hdmi_audio=0 hdmi_audio_init=0' in log
    assert ' video=%d video_init=%d hdmi_state_init=%d osd=%d osd_init=%d'%(video,video,video,osd,osd) in log


def test_actual_constructor_rejects_each_broken_predecessor_and_selftest_before_new_owners(tmp_path,bb_constructor):
    _,guest=exported_guest(tmp_path)
    for key in ('MENU_PINMEM_PEER_CONNECT','MENU_VEF_PINMEM_CONTROL_CONNECT','MENU_VEF_PINMEM_INPUT_CONNECT',
                'MENU_INFRABB_VEF_CONTROL_CONNECT','MENU_INFRABB_VEF_CONNECT','MENU_IMAGING_ADF_CONNECT',
                'MENU_IMAGING_CONTROL_CONNECT','MENU_IMAGING_CONNECT','MENU_BB_SET_MODE','MENU_ADF_SET_OUTPUT',
                'MENU_BACKUP_SYNC','MENU_CP_BACKGROUND','MENU_UDATE_DISTRIBUTION','MENU_TOUCH_PANEL',
                'MENU_TCIN_DETECT','MENU_DFS_SELECTOR','MENU_AUDIO_BOOT_CONFIG','MENU_PIN_REGISTRY',
                'MENU_PIN_CONTROL_MEMORY','MENU_PIN_CONNECTION'):
        for value in (None,'unknown'):
            bad=dict(guest)
            if value is None:bad.pop(key)
            else:bad[key]=value
            assert ' video=0 video_init=0 hdmi_state_init=0 osd=0 osd_init=0' in bb_constructor(bad)
    assert ' video=0 video_init=0 hdmi_state_init=0 osd=0 osd_init=0' in bb_constructor({**guest,'MENU_OBSERVE_SELFTEST':'1'})
    for _,switch,_,_ in FAMILIES:
        for value in ('','unknown'):
            log=bb_constructor({**guest,'MENU_'+switch:value})
            expected=(' video=0 video_init=0 hdmi_state_init=0 osd=1 osd_init=1' if switch=='PINMEM_HDMI_VIDEO_CONNECT'
                      else ' video=1 video_init=1 hdmi_state_init=1 osd=0 osd_init=0')
            assert expected in log


def test_actual_constructor_prior_owner_failures_block_both_and_hdmi_state_precedes_video(tmp_path,bb_constructor):
    _,guest=exported_guest(tmp_path)
    for owner in ('owner_rc','imaging_owner_rc','control_owner_rc','adf_owner_rc','vef_owner_rc',
                  'vef_control_owner_rc','pinmem_input_owner_rc','pinmem_control_owner_rc',
                  'scalar_owner_rc','adf_connection_owner_rc','drawinfo_owner_rc'):
        assert ' video=0 video_init=0 hdmi_state_init=0 osd=0 osd_init=0' in bb_constructor(guest,**{owner:-1021})
    for options,expected in (
        ({'hdmi_state_owner_rc':-1021},' video=0 video_init=0 hdmi_state_init=1 osd=1 osd_init=1'),
        ({'video_owner_rc':-1021},' video=0 video_init=1 hdmi_state_init=1 osd=1 osd_init=1'),
        ({'osd_owner_rc':-1021},' video=1 video_init=1 hdmi_state_init=1 osd=0 osd_init=1'),
        ({'hdmi_audio_owner_rc':-1021},' video=1 video_init=1 hdmi_state_init=1 osd=1 osd_init=1')):
        assert expected in bb_constructor(guest,**options)


def test_missing_host_or_emitted_peer_export_blocks_new_exports_independently(tmp_path):
    host,guest=exported_guest(tmp_path)
    for key in ('A7C2_PINMEM_PEER_CONNECT','MENU_PINMEM_PEER_CONNECT','A7C2_VEF_PINMEM_CONTROL_CONNECT',
                'MENU_VEF_PINMEM_CONTROL_CONNECT',SIXTH_HOST,'MENU_VEF_PINMEM_INPUT_CONNECT',
                'MENU_INFRABB_VEF_CONTROL_CONNECT','MENU_INFRABB_VEF_CONNECT','MENU_IMAGING_ADF_CONNECT',
                'MENU_IMAGING_CONTROL_CONNECT','MENU_IMAGING_CONNECT','MENU_BB_SET_MODE'):
        bad=dict(host);bad.pop(key)
        changed=clean_guest_environment(menu_probe_setup(bad))
        assert all('MENU_'+switch not in changed for _,switch,_,_ in FAMILIES)
    for _,switch,_,_ in FAMILIES:
        for prefix in ('A7C2_','MENU_'):
            bad=dict(host);bad.pop(prefix+switch)
            changed=clean_guest_environment(menu_probe_setup(bad))
            assert 'MENU_'+switch not in changed
            other=next(key for _,key,_,_ in FAMILIES if key!=switch)
            assert changed['MENU_'+other]==guest['MENU_'+other]
