"""Default-off fourth InfraBB OUT1 -> VEF IN1 same-format profile admission."""
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
                                      load_script, make_candidate, menu_probe_setup, qemu_bb_guard)
from test_imaging_pin_connection_profile import qemu_imaging_guard
from test_imaging_control_connection_profile import qemu_control_guard
from test_imaging_adf_connection_profile import host_environment as audio_environment, qemu_adf_guard

PROFILE=backup.INFRABB_VEF_CONNECT_PROFILE
PREFIX='infrabb_vef_connection_'


def host_environment(tmp_path,build=None):
    return {**audio_environment(tmp_path,build),'A7C2_INFRABB_VEF_CONNECT':PROFILE}


def test_typed_fields_fix_fourth_edge_same_format_synchronous_work_and_references():
    expected={
        'profile':PROFILE,
        'source_pin':[0,2,1,0x9284074a],'peer_pin':[0,1,1,0x905a0048],
        'source_registry_count':21,'source_registry_slot':5,
        'sink_registry_count':16,'sink_registry_slot':1,
        'request_bytes':64,'reply_bytes':56,'reply_command':0x8001,'unique_reply_count':1,
        'source_state_path':[1,2,0],'sink_state_path':[1,0],
        'internal_commands':[0x100,0x8100],'internal_message_bytes':[64,72],
        'sink_connected_marker_write_count':0,
        'first_edge_profile':backup.IMAGING_CONNECT_PROFILE,
        'control_edge_profile':backup.IMAGING_CONTROL_CONNECT_PROFILE,
        'audio_edge_profile':backup.IMAGING_ADF_CONNECT_PROFILE,
        'predecessors_require_ap_consumed':True,'predecessors_require_clean':True,
        'predecessors_require_no_outstanding':True,'predecessors_require_format_preserved':True,
        'predecessors_require_pool_retired':True,'predecessor_histories_unchanged':True,
        'first_edge_config_after':[0,1,1920,1080,0],
        'precondition_refusal_policy':'unadmitted-only-no-request-or-fault-until-predecessors-ready',
        'vef_current_info_bytes':20,'vef_current_info_hex':'0100000000000000010000008007000038040000',
        'vef_pin_index':1,'vef_ordinal':0,'vef_code':1,'vef_component':0,'vef_flags':0,
        'vef_width':1920,'vef_height':1080,
        'format_command_frame':0x2002,'format_command':0xf008,'format_command_bytes':36,
        'format_command_copy_bytes':20,'format_prepare_context':1,'format_command_initial_state':0,
        'format_execute_context':3,'format_execute_type':2,
        'format_execution_policy':'synchronous-context3-type2-not-RTOS-queued-task',
        'old_command_list_policy':'opaque-preserved','old_ordinal1_preserved':True,
        'nomem_history_preserved':True,'s0_ab_failure_history_preserved':True,
        'dmm_unit':0x404,'dmm_owner_code':0x284,
        'dmm_owner_policy':'original-semantic-owner-code-not-service-SID',
        'dmm_sender_policy':'virtual-service-senders-not-original-dynamic-type2a',
        'dmm_allocate_message_bytes':152,'dmm_allocate_option':1,'dmm_allocate_wait':0xffffffff,
        'dmm_creator':'VEF','dmm_creator_close_message_bytes':152,
        'dmm_consumer_message_bytes':216,'dmm_consumer_token':0x55,
        'dmm_open_option':0,'dmm_open_wait':0xffffffff,'dmm_free_option':0,
        'dmm_operations':[0x20,0x25,0x24,0x25,0x23],'dmm_share_count':0,
        'buffer_bytes':80,'ssyn_header_hex':'02000000','ssyn_entry_type':0,'ssyn_key':0,
        'format_payload_bytes':16,'format_payload_hex':'01000000000000008007000038040000',
        'format_notice_bytes':80,'format_notice_command':[0x1000,0x104,0x38,1],
        'format_notice_fields':['peer_pin','source_pin','unit','handle',0,0],
        'format_comparison_fields':['code_u8','component_u8','flags_u16','width_u32','height_u32'],
        'format_unused_payload_offset':4,'format_unused_payload_policy':'ignored-by-semantic-comparison',
        'format_digest_bytes':16,'format_policy':'fixed-known-same-format-only-reject-unknown-metadata',
        'different_format_policy':'fault-and-hold-mapped-buffer-without-Free-or-forward',
        'different_format_unimplemented':'rewrite-BB-table-then-forward-to-connected-BB-IN1-upstream-9005',
        'references_owner_open':[[1,1],[1,0],[1,0],[1,1],[1,0],[0,0]],
        'reference_stages':['allocate','creator-close','same-owner-transfer','consumer-open','consumer-close','consumer-Free'],
        'reference_policy':'same-owner-transfer-without-command21-share',
        'reply_publication_policy':'after-finite-format-Close-Free-before-AP-consumption',
        'source_state_source':'public-InfraBB-image-constructor',
        'sink_state_source':'public-InfraVEF-image-constructor',
        'mapping_profile':'virtual-pin-control-reserved-ram-v1',
        'completion_scope':'three-edge-prerequisites-and-same-format-metadata-only',
        'internal_control_policy':'native-provider-consumption-not-original-CP-tasks',
    }
    fields=backup.infrabb_vef_connection_profile_fields(PROFILE)
    for name,value in expected.items():
        actual=fields[PREFIX+name]
        assert type(actual) is type(value) and json.dumps(actual)==json.dumps(value)
    assert len(bytes.fromhex(fields[PREFIX+'vef_current_info_hex']))==20
    assert len(bytes.fromhex(fields[PREFIX+'format_payload_hex']))==16
    false_fields={PREFIX+name for name in (
        'original_cp_executed','original_cp_ram_mapping_verified','original_cp_page_tables_verified',
        'live_cp_ram_read','original_task_scheduler_verified','original_RTOS_timing_verified',
        'original_cp_command_list_verified','original_semaphore_timing_verified','hardware_verified',
        'ap_consumed','runtime_consumed','native_verified','connection_verified','format_consumed',
        'general_format_ready','cmos_verified','aip_clocks_verified','frames_verified','capture_verified')}
    assert set(fields)=={PREFIX+name for name in expected}|false_fields
    assert all(fields[name] is False for name in false_fields)
    off=backup.infrabb_vef_connection_profile_fields('')
    assert all(value is (False if name in false_fields else None) for name,value in off.items())
    with pytest.raises(ValueError):backup.infrabb_vef_connection_profile_fields('unknown')


def test_launcher_default_off_and_exact_three_predecessors_required(tmp_path):
    launcher=load_script('vef_connection_start_menu','start-menu.py')
    audio=audio_environment(tmp_path)
    for env in ({},audio,{**audio,'MENU_INFRABB_VEF_CONNECT':PROFILE}):
        assert 'MENU_INFRABB_VEF_CONNECT' not in launcher.profile_environment(env,natural_boot=True)
    env=host_environment(tmp_path)
    selected=launcher.profile_environment(env,natural_boot=True)
    assert selected['MENU_INFRABB_VEF_CONNECT']==PROFILE
    for key,value in [('MENU_IMAGING_ADF_CONNECT',backup.IMAGING_ADF_CONNECT_PROFILE),
                      ('MENU_IMAGING_CONTROL_CONNECT',backup.IMAGING_CONTROL_CONNECT_PROFILE),
                      ('MENU_IMAGING_CONNECT',backup.IMAGING_CONNECT_PROFILE)]:
        assert selected[key]==value
    with pytest.raises(ValueError):launcher.profile_environment(env,natural_boot=False)
    for name in ('A7C2_IMAGING_ADF_CONNECT','A7C2_IMAGING_CONTROL_CONNECT','A7C2_IMAGING_CONNECT',
                 'A7C2_BB_SET_MODE','A7C2_BACKUP_SYNC','A7C2_BACKUP_BUILD','A7C2_DIRECTORY_SD',
                 'A7C2_CP_BACKGROUND','A7C2_UDATE_DISTRIBUTION','A7C2_TOUCH_PANEL','A7C2_TCIN_DETECT',
                 'A7C2_DFS_SELECTOR','A7C2_VEF_PATH','A7C2_ADF_PROC_PATH','A7C2_ADF_SET_INPUT','A7C2_ADF_SET_OUTPUT'):
        bad=dict(env);bad.pop(name)
        with pytest.raises(ValueError):launcher.profile_environment(bad,natural_boot=True)
        if name!='A7C2_BACKUP_BUILD':
            with pytest.raises(ValueError):launcher.profile_environment({**env,name:'unknown'},natural_boot=True)
    for name,value in [('A7C2_INFRABB_VEF_CONNECT','unknown'),('SEED_BACKUP','private'),('SEED_BACKUP','full'),
                       ('MENU_USB_NET','1'),('A7C2_HOST_SD','256gb'),('A7C2_SD_SPARSE','10g-empty'),
                       *[(key,'1') for key in backup.BB_MODE_CONFLICTS]]:
        with pytest.raises(ValueError):launcher.profile_environment({**env,name:value},natural_boot=True)


def qemu_vef_guard():
    tree=ast.parse((HERE/'qemu-menu-probe.py').read_text())
    return next(node for node in tree.body if isinstance(node,ast.If) and any(
        isinstance(call,ast.Call) and isinstance(call.func,ast.Attribute) and
        ast.unparse(call.func)=='parser.error' and call.args and isinstance(call.args[0],ast.Constant) and
        str(call.args[0].value).startswith('InfraBB VEF connection requires') for call in ast.walk(node)))


def test_qemu_requires_exact_host_fourth_profile_and_all_prior_guards():
    code=compile(ast.Module(body=[qemu_bb_guard(),qemu_imaging_guard(),qemu_control_guard(),qemu_adf_guard(),qemu_vef_guard()],
                            type_ignores=[]),'<vef-connection-pre-vm-guards>','exec')
    def run(env,**changes):
        scope={**guard_scope(),'IMAGING_CONNECT_PROFILE':backup.IMAGING_CONNECT_PROFILE,
               'IMAGING_CONTROL_CONNECT_PROFILE':backup.IMAGING_CONTROL_CONNECT_PROFILE,
               'IMAGING_ADF_CONNECT_PROFILE':backup.IMAGING_ADF_CONNECT_PROFILE,'INFRABB_VEF_CONNECT_PROFILE':PROFILE,
               'imaging_pin_connection_profile':backup.IMAGING_CONNECT_PROFILE,
               'imaging_control_connection_profile':backup.IMAGING_CONTROL_CONNECT_PROFILE,
               'imaging_adf_connection_profile':backup.IMAGING_ADF_CONNECT_PROFILE,
               'infrabb_vef_connection_profile':PROFILE,**changes}
        with mock.patch.dict(os.environ,env,clear=True):exec(code,scope)
    valid={'A7C2_INFRABB_VEF_CONNECT':PROFILE,'A7C2_IMAGING_ADF_CONNECT':backup.IMAGING_ADF_CONNECT_PROFILE,
           'A7C2_IMAGING_CONTROL_CONNECT':backup.IMAGING_CONTROL_CONNECT_PROFILE,
           'A7C2_IMAGING_CONNECT':backup.IMAGING_CONNECT_PROFILE,'A7C2_BB_SET_MODE':backup.BB_SET_MODE_PROFILE,
           'SEED_BACKUP':'alllang','A7C2_DIRECTORY_SD_PROFILE':'directory-vvfat-256gb-v1',
           'MENU_PIN_REGISTRY':'1','MENU_PIN_CONTROL_MEMORY':'1','MENU_PIN_CONNECTION':'cold'}
    run(valid)
    run({},bb_set_mode_profile='',imaging_pin_connection_profile='',imaging_control_connection_profile='',
        imaging_adf_connection_profile='',infrabb_vef_connection_profile='')
    run({key:value for key,value in valid.items() if key!='A7C2_INFRABB_VEF_CONNECT'},infrabb_vef_connection_profile='')
    for name in ('imaging_adf_connection_profile','imaging_control_connection_profile','imaging_pin_connection_profile',
                 'bb_set_mode_profile','backup_sync','cp_background','udate_distribution','touch_panel','tcin_detect',
                 'dfs_selector','vef_path_profile','adf_proc_path_profile','adf_set_input_profile','adf_set_output_profile'):
        with pytest.raises(SystemExit):run(valid,**{name:''})
    with pytest.raises(SystemExit):run(valid,infrabb_vef_connection_profile='unknown')
    for name in valid:
        bad=dict(valid);bad.pop(name)
        with pytest.raises(SystemExit):run(bad)
        with pytest.raises(SystemExit):run({**valid,name:'unknown'})
    for name in backup.BB_MODE_CONFLICTS:
        with pytest.raises(SystemExit):run({**valid,name:'1'})


def test_prepare_invalid_profiles_reject_before_candidate_or_files(tmp_path,monkeypatch):
    launcher=load_script('vef_connection_prepare_menu','start-menu.py')
    env=launcher.profile_environment(host_environment(tmp_path),natural_boot=True)
    env.update(SEED_BACKUP='alllang',A7C2_DIRECTORY_SD_PROFILE='directory-vvfat-256gb-v1')
    def no_build(*args):raise AssertionError('invalid fourth profile reached candidate/filesystem work')
    monkeypatch.setattr(backup,'validate_build',no_build)
    for name,value in [('MENU_INFRABB_VEF_CONNECT','unknown'),('A7C2_INFRABB_VEF_CONNECT',''),
                       ('A7C2_INFRABB_VEF_CONNECT','unknown'),('MENU_IMAGING_ADF_CONNECT',''),
                       ('A7C2_IMAGING_ADF_CONNECT',''),('MENU_IMAGING_CONTROL_CONNECT',''),
                       ('A7C2_IMAGING_CONTROL_CONNECT',''),('MENU_IMAGING_CONNECT',''),
                       ('A7C2_IMAGING_CONNECT',''),('MENU_BB_SET_MODE',''),('A7C2_BB_SET_MODE',''),
                       ('MENU_PIN_REGISTRY',''),('MENU_PIN_CONTROL_MEMORY',''),('MENU_PIN_CONNECTION',''),
                       ('SEED_BACKUP','private'),('A7C2_DIRECTORY_SD_PROFILE',''),
                       *[(key,'1') for key in backup.BB_MODE_CONFLICTS]]:
        with pytest.raises(ValueError):backup.prepare_profile(HERE,{**env,name:value})


@pytest.mark.parametrize('enabled',[False,True])
def test_public_receipt_manifest_and_complete_guest_exports_preserve_all_three_edges(tmp_path,enabled):
    build=build_fixture(tmp_path)[0]
    env=host_environment(tmp_path,build)
    if not enabled:env.pop('A7C2_INFRABB_VEF_CONNECT')
    launcher=load_script('vef_connection_receipt_menu','start-menu.py')
    host=launcher.profile_environment(env,natural_boot=True)
    with directory_lease(Path(env['A7C2_DIRECTORY_SD'])) as lease:
        host.update(directory_profile(HERE,lease,tmp_path/'directory-profile'))
        host.update(backup.prepare_profile(HERE,host))
    expected=backup.infrabb_vef_connection_profile_fields(PROFILE if enabled else '')
    receipt=json.loads(Path(host['MENU_BACKUP_PROFILE_RECEIPT']).read_text())
    for fields in (expected,backup.imaging_adf_connection_profile_fields(backup.IMAGING_ADF_CONNECT_PROFILE),
                   backup.imaging_control_connection_profile_fields(backup.IMAGING_CONTROL_CONNECT_PROFILE),
                   backup.imaging_pin_connection_profile_fields(backup.IMAGING_CONNECT_PROFILE)):
        assert all(type(receipt[name]) is type(value) and json.dumps(receipt[name])==json.dumps(value)
                   for name,value in fields.items())
    setup=menu_probe_setup(host)
    guest=clean_guest_environment(setup)
    assert guest.get('MENU_INFRABB_VEF_CONNECT')==(PROFILE if enabled else None)
    assert guest['MENU_IMAGING_ADF_CONNECT']==backup.IMAGING_ADF_CONNECT_PROFILE
    assert guest['MENU_IMAGING_CONTROL_CONNECT']==backup.IMAGING_CONTROL_CONNECT_PROFILE
    assert guest['MENU_IMAGING_CONNECT']==backup.IMAGING_CONNECT_PROFILE
    assert 'A7C2_INFRABB_VEF_CONNECT' not in guest
    assert sum(line.startswith('export MENU_INFRABB_VEF_CONNECT=') for line in setup)==int(enabled)
    if enabled:
        for name in ('A7C2_INFRABB_VEF_CONNECT','MENU_INFRABB_VEF_CONNECT','MENU_IMAGING_ADF_CONNECT',
                     'A7C2_IMAGING_ADF_CONNECT','MENU_IMAGING_CONTROL_CONNECT','A7C2_IMAGING_CONTROL_CONNECT',
                     'MENU_IMAGING_CONNECT','A7C2_IMAGING_CONNECT','MENU_BB_SET_MODE'):
            assert 'MENU_INFRABB_VEF_CONNECT' not in clean_guest_environment(menu_probe_setup({**host,name:''}))
    tree=ast.parse((HERE/'qemu-menu-probe.py').read_text())
    manifest=next(node.value for node in tree.body if isinstance(node,ast.Assign) and
                  isinstance(node.targets[0],ast.Name) and node.targets[0].id=='manifest')
    spread=next(value for key,value in zip(manifest.keys,manifest.values) if key is None and
                isinstance(value,ast.Call) and isinstance(value.func,ast.Name) and
                value.func.id=='infrabb_vef_connection_profile_fields')
    scope={'infrabb_vef_connection_profile':PROFILE if enabled else '',
           'infrabb_vef_connection_profile_fields':backup.infrabb_vef_connection_profile_fields}
    actual=eval(compile(ast.Expression(spread),'<actual-fourth-manifest-spread>','eval'),scope)
    assert actual==expected


def test_gtk_rejects_missing_chain_mismatched_candidate_directory_and_unsafe_flow(tmp_path):
    driver=load_script('vef_connection_gtk_driver','check-natural-gtk-input.py')
    build=make_candidate(tmp_path)
    card=tmp_path/'card';card.mkdir()
    env=host_environment(tmp_path,build)
    safe=['check-natural-gtk-input.py','--new-ui','--firstboot','--simplified-chinese',
          '--natural-shutter','--export-sd','--host-sd-dir',str(card),'--candidate-build',str(build)]
    cases=[([item for item in safe if item!=flag],env) for flag in (
        '--new-ui','--firstboot','--simplified-chinese','--natural-shutter','--export-sd','--candidate-build')]
    cases.extend((safe,{**env,name:value}) for name,value in (
        ('A7C2_INFRABB_VEF_CONNECT','unknown'),('A7C2_IMAGING_ADF_CONNECT',''),
        ('A7C2_IMAGING_CONTROL_CONNECT',''),('A7C2_IMAGING_CONNECT',''),('A7C2_BB_SET_MODE',''),
        ('A7C2_BACKUP_BUILD',str(tmp_path/'other')),('A7C2_DIRECTORY_SD',str(tmp_path/'other-card')),
        ('SEED_BACKUP','private'),('SEED_BACKUP','full'),*[(key,'1') for key in backup.BB_MODE_CONFLICTS]))
    for argv,values in cases:
        with mock.patch.object(driver.sys,'argv',argv),mock.patch.dict(driver.os.environ,values,clear=True), \
             mock.patch.object(driver.subprocess,'Popen',side_effect=AssertionError('must reject before Xvfb')):
            with pytest.raises(ValueError):driver.main()
    with mock.patch.object(driver.sys,'argv',safe),mock.patch.dict(driver.os.environ,env,clear=True), \
         mock.patch.object(driver.subprocess,'Popen',side_effect=RuntimeError('accepted-before-Xvfb')):
        with pytest.raises(RuntimeError,match='accepted-before-Xvfb'):driver.main()


@pytest.mark.parametrize('enabled',[False,True])
def test_qemu_rejects_missing_changed_and_untyped_receipt_fields_with_old_identity_preserved(tmp_path,enabled):
    build=build_fixture(tmp_path)[0]
    launcher=load_script('vef_connection_typed_receipt_menu','start-menu.py')
    env=host_environment(tmp_path,build)
    if not enabled:env.pop('A7C2_INFRABB_VEF_CONNECT')
    host=launcher.profile_environment(env,natural_boot=True)
    with directory_lease(Path(env['A7C2_DIRECTORY_SD'])) as lease:
        host.update(directory_profile(HERE,lease,tmp_path/'receipt-profile'))
        host.update(backup.prepare_profile(HERE,host))
    tree=ast.parse((HERE/'qemu-menu-probe.py').read_text())
    validator=next(node for node in tree.body if isinstance(node,ast.If) and
        isinstance(node.test,ast.Name) and node.test.id=='backup_sync' and any(
            isinstance(call,ast.Call) and isinstance(call.func,ast.Name) and call.func.id=='validate_build'
            for call in ast.walk(node)))
    code=compile(ast.Module(body=[validator],type_ignores=[]),'<real-qemu-fourth-receipt-validator>','exec')
    scope={'os':os,'json':json,'Path':Path,'base':HERE,'sha256_file':backup.sha,
           'backup_sync':backup.PROFILE,'env':host,
           'kernel_script':Path(host['MENU_KERNEL_SCRIPT']),'board_dtb':Path(host['MENU_DTB']),
           'adf_proc_path_profile':backup.ADF_PROFILE,'adf_set_input_profile':backup.INPUT_PROFILE,
           'adf_set_output_profile':backup.OUTPUT_PROFILE,'bb_set_mode_profile':backup.BB_SET_MODE_PROFILE,
           'imaging_pin_connection_profile':backup.IMAGING_CONNECT_PROFILE,
           'imaging_control_connection_profile':backup.IMAGING_CONTROL_CONNECT_PROFILE,
           'imaging_adf_connection_profile':backup.IMAGING_ADF_CONNECT_PROFILE,
           'infrabb_vef_connection_profile':PROFILE if enabled else '',
           'infrabb_vef_control_connection_profile':'','vef_pinmem_input_connection_profile':'',
           'vef_pinmem_control_connection_profile':'','pinmem_peer_connections_profile':'',
           'adf_hdmi_audio_connection_profile':'',
           'pinmem_hdmi_video_connection_profile':'','pinmem_osd_connection_profile':'','cp302c_no_transition_profile':'',
           'udate_kernel_receipt':HERE.parents[1]/'report/virtual-cp/udate-distribution/verification.json',
           'overwrite_manifest':None,'settings_restore_manifest':None}
    for name in ('adf_proc','adf_set_input','adf_set_output','bb_set_mode',
                 'imaging_pin_connection','imaging_control_connection','imaging_adf_connection','infrabb_vef_connection',
                 'infrabb_vef_control_connection','vef_pinmem_input_connection',
                 'vef_pinmem_control_connection','pinmem_peer_connections','adf_hdmi_audio_connection',
                 'pinmem_hdmi_video_connection','pinmem_osd_connection','cp302c_no_transition'):
        scope[name+'_profile_fields']=getattr(backup,name+'_profile_fields')
    path=Path(host['MENU_BACKUP_PROFILE_RECEIPT'])
    original=json.loads(path.read_text())
    with mock.patch.dict(os.environ,host,clear=True):
        exec(code,scope)
        for fields in (backup.infrabb_vef_connection_profile_fields(PROFILE if enabled else ''),
                       backup.imaging_adf_connection_profile_fields(backup.IMAGING_ADF_CONNECT_PROFILE),
                       backup.imaging_control_connection_profile_fields(backup.IMAGING_CONTROL_CONNECT_PROFILE),
                       backup.imaging_pin_connection_profile_fields(backup.IMAGING_CONNECT_PROFILE)):
            for name,value in fields.items():
                changed=copy.deepcopy(original);changed.pop(name)
                path.write_text(json.dumps(changed))
                with pytest.raises(ValueError,match='identity/admission mismatch'):exec(code,scope)
                changed[name]=(int(not value) if type(value) is bool else float(value) if type(value) is int else 'wrong')
                path.write_text(json.dumps(changed))
                with pytest.raises(ValueError,match='identity/admission mismatch'):exec(code,scope)
        if enabled:
            for name in ('source_pin','peer_pin','source_state_path','first_edge_config_after','references_owner_open'):
                changed=copy.deepcopy(original)
                changed[PREFIX+name][0]=[1.0,1] if name=='references_owner_open' else float(changed[PREFIX+name][0])
                path.write_text(json.dumps(changed))
                with pytest.raises(ValueError,match='identity/admission mismatch'):exec(code,scope)
        path.write_text(json.dumps(original));exec(code,scope)


def test_complete_guest_exports_execute_actual_fourth_constructor_and_owner_failures(tmp_path,bb_constructor):
    source=(HERE/'menu-observe.c').read_text()
    start=source.index('    const char *output_profile=getenv("MENU_ADF_SET_OUTPUT");')
    end=source.index('    software_gpe =',start)
    assert 'same_name(infrabb_vef_profile,FULL_INFRABB_VEF_CONNECTION_PROFILE)' in source[start:end]
    launcher=load_script('vef_connection_constructor_menu','start-menu.py')
    host=launcher.profile_environment(host_environment(tmp_path),natural_boot=True)
    host.update(MENU_BACKUP_SYNC=backup.PROFILE,SEED_BACKUP='alllang',
                A7C2_DIRECTORY_SD_PROFILE='directory-vvfat-256gb-v1')
    guest=clean_guest_environment(menu_probe_setup(host))
    assert guest['MENU_INFRABB_VEF_CONNECT']==PROFILE
    assert 'A7C2_INFRABB_VEF_CONNECT' not in guest and 'MENU_OBSERVE_SELFTEST' not in guest
    log=bb_constructor(guest)
    assert 'imaging=1 imaging_init=1 control=1 control_init=1 adf=1 adf_init=1 vef=1 vef_init=1' in log
    assert 'FULL_INFRABB_VEF_CONNECT_PROFILE requested='+PROFILE+' enabled=1 first_missing=none ' in log
    assert 'initialized=1 unadmitted_count=0 before_any_input=1 connection_verified=0 capture_verified=0' in log
    for name in ('MENU_IMAGING_ADF_CONNECT','MENU_IMAGING_CONTROL_CONNECT','MENU_IMAGING_CONNECT',
                 'MENU_BB_SET_MODE','MENU_ADF_SET_OUTPUT','MENU_BACKUP_SYNC','MENU_CP_BACKGROUND',
                 'MENU_UDATE_DISTRIBUTION','MENU_TOUCH_PANEL','MENU_TCIN_DETECT','MENU_DFS_SELECTOR',
                 'MENU_AUDIO_BOOT_CONFIG','MENU_PIN_REGISTRY','MENU_PIN_CONTROL_MEMORY','MENU_PIN_CONNECTION'):
        bad=dict(guest);bad.pop(name)
        assert ' vef=0 vef_init=0' in bb_constructor(bad)
    for change in ({'MENU_INFRABB_VEF_CONNECT':'unknown'},{'MENU_INFRABB_VEF_CONNECT':''},
                   {'MENU_IMAGING_ADF_CONNECT':'unknown'},{'MENU_OBSERVE_SELFTEST':'1'}):
        assert ' vef=0 vef_init=0' in bb_constructor({**guest,**change})
    for options in ({'input_enabled':False},{'owner_rc':-1021},{'imaging_owner_rc':-1021},
                    {'control_owner_rc':-1021},{'adf_owner_rc':-1021}):
        assert ' vef=0 vef_init=0' in bb_constructor(guest,**options)
    failure=bb_constructor(guest,vef_owner_rc=-1021)
    assert 'imaging=1 imaging_init=1 control=1 control_init=1 adf=1 adf_init=1 vef=0 vef_init=1' in failure
    assert 'enabled=0 first_missing=owner-init ' in failure
    host.pop('MENU_INFRABB_VEF_CONNECT');host.pop('A7C2_INFRABB_VEF_CONNECT')
    default_guest=clean_guest_environment(menu_probe_setup(host))
    assert 'MENU_INFRABB_VEF_CONNECT' not in default_guest
    default_log=bb_constructor(default_guest)
    assert 'imaging=1 imaging_init=1 control=1 control_init=1 adf=1 adf_init=1 vef=0 vef_init=0' in default_log
    assert 'FULL_INFRABB_VEF_CONNECT_PROFILE ' not in default_log


def test_gtk_requires_typed_fourth_intent_in_both_receipts():
    tree=ast.parse((HERE/'check-natural-gtk-input.py').read_text())
    admission=next(node for node in ast.walk(tree) if isinstance(node,ast.If) and
        isinstance(node.test,ast.Name) and node.test.id=='requested_infrabb_vef_connect' and
        isinstance(node.body[0],ast.Assign) and isinstance(node.body[0].targets[0],ast.Name) and
        node.body[0].targets[0].id=='expected_infrabb_vef')
    code=compile(ast.Module(body=[admission],type_ignores=[]),'<fourth-runtime-admission>','exec')
    fields=backup.infrabb_vef_connection_profile_fields(PROFILE)
    actual={**fields,'backup_transport':copy.deepcopy(fields),'selected_observer_matches_build':True}
    scope={'requested_infrabb_vef_connect':'','actual':actual,'proof':{},'json':json,
           'infrabb_vef_connection_profile_fields':backup.infrabb_vef_connection_profile_fields}
    exec(code,scope);assert not scope['proof']
    scope['requested_infrabb_vef_connect']=PROFILE
    exec(code,scope);assert scope['proof']['infrabb_vef_connection_admission']==fields
    for section in ('top','transport'):
        for name,value in fields.items():
            bad=copy.deepcopy(actual)
            target=bad if section=='top' else bad['backup_transport']
            target.pop(name)
            scope.update(actual=bad,proof={})
            with pytest.raises(RuntimeError):exec(code,scope)
            target[name]=(int(not value) if type(value) is bool else float(value) if type(value) is int else
                          tuple(value) if isinstance(value,list) else 'wrong')
            with pytest.raises(RuntimeError):exec(code,scope)
        for name in ('source_pin','peer_pin','source_state_path','first_edge_config_after','references_owner_open'):
            bad=copy.deepcopy(actual)
            target=bad if section=='top' else bad['backup_transport']
            target[PREFIX+name][0]=[1.0,1] if name=='references_owner_open' else float(target[PREFIX+name][0])
            scope.update(actual=bad,proof={})
            with pytest.raises(RuntimeError):exec(code,scope)
    scope.update(actual={**actual,'selected_observer_matches_build':False},proof={})
    with pytest.raises(RuntimeError):exec(code,scope)
