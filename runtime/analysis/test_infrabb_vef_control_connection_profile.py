"""Default-off fifth BB type8 OUT0 -> VEF type8 IN0 profile admission."""
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
from test_imaging_adf_connection_profile import qemu_adf_guard
from test_infrabb_vef_connection_profile import host_environment as fourth_environment, qemu_vef_guard

PROFILE=backup.FULL_INFRABB_VEF_CONTROL_CONNECTION_PROFILE
PREFIX='infrabb_vef_control_connection_'
HOST='A7C2_INFRABB_VEF_CONTROL_CONNECT'
GUEST='MENU_INFRABB_VEF_CONTROL_CONNECT'
PREDECESSORS=(
    'A7C2_INFRABB_VEF_CONNECT','A7C2_IMAGING_ADF_CONNECT','A7C2_IMAGING_CONTROL_CONNECT',
    'A7C2_IMAGING_CONNECT','A7C2_BB_SET_MODE','A7C2_BACKUP_SYNC','A7C2_BACKUP_BUILD',
    'A7C2_DIRECTORY_SD','A7C2_CP_BACKGROUND','A7C2_UDATE_DISTRIBUTION','A7C2_TOUCH_PANEL',
    'A7C2_TCIN_DETECT','A7C2_DFS_SELECTOR','A7C2_VEF_PATH','A7C2_ADF_PROC_PATH',
    'A7C2_ADF_SET_INPUT','A7C2_ADF_SET_OUTPUT')
PROFILE_NAMES=('adf_proc','adf_set_input','adf_set_output','bb_set_mode',
               'imaging_pin_connection','imaging_control_connection','imaging_adf_connection',
               'infrabb_vef_connection','infrabb_vef_control_connection','vef_pinmem_input_connection',
               'vef_pinmem_control_connection','pinmem_peer_connections','adf_hdmi_audio_connection',
               'pinmem_hdmi_video_connection','pinmem_osd_connection','cp302c_no_transition')


def host_environment(tmp_path,build=None):
    return {**fourth_environment(tmp_path,build),HOST:PROFILE}


def test_fields_fix_fifth_edge_zero_effects_and_preserve_all_predecessors():
    expected={
        'profile':PROFILE,
        'source_pin':[8,2,0,0x9284074a],'peer_pin':[8,1,0,0x905a0048],
        'source_registry_count':21,'source_registry_slot':9,'source_object_CP_VA':0x01789514,
        'sink_registry_count':16,'sink_registry_slot':14,'vef_current_ordinal':14,
        'request_bytes':64,'reply_bytes':56,'reply_command':0x8001,'unique_reply_count':1,
        'source_state_path':[1,2,0],'sink_state_path':[1,0],
        'internal_commands':[0x100,0x8100],'internal_message_bytes':[64,72],
        'source_posthook_direction':2,'source_posthook_selected':False,
        'source_type8_marker_selected':False,'sink_connected_marker_write_count':0,
        'vef_posthook_allowed_ordinals':[1,2,3],'vef_posthook_selected':False,
        'dmm_allocation_count':0,'ssyn_notice_count':0,'format_cache_write_count':0,
        'vef_current_info_write_count':0,'f008_command_count':0,
        'source7_event_count':0,'clock_write_count':0,'mmio_write_count':0,'frame_count':0,
        'first_edge_profile':backup.IMAGING_CONNECT_PROFILE,
        'control_edge_profile':backup.IMAGING_CONTROL_CONNECT_PROFILE,
        'audio_edge_profile':backup.IMAGING_ADF_CONNECT_PROFILE,
        'image_edge_profile':backup.INFRABB_VEF_CONNECT_PROFILE,
        'predecessors_require_ap_consumed':True,'predecessors_require_clean':True,
        'predecessors_require_no_outstanding':True,'predecessors_require_data_Free':True,
        'predecessors_require_pool_retired':True,'predecessors_require_format_preserved':True,
        'predecessor_histories_unchanged':True,'nomem_history_preserved':True,
        's0_ab_failure_history_preserved':True,'dmm_counters_unchanged':True,
        'backing_records_preserved':[0,1],'first_edge_config_after':[0,1,1920,1080,0],
        'precondition_refusal_policy':'unadmitted-only-no-request-or-fault-until-predecessors-ready',
        'source_state_source':'public-InfraBB-image-constructor',
        'sink_state_source':'public-InfraVEF-image-constructor',
        'registry_initial_state':'cold-disconnected-not-ready',
        'mapping_profile':'virtual-pin-control-reserved-ram-v1',
        'completion_scope':'four-edge-prerequisites-and-zero-format-effects',
        'internal_control_policy':'native-provider-consumption-not-original-CP-tasks',
    }
    false_names=(
        'original_cp_executed','original_cp_ram_mapping_verified','original_cp_page_tables_verified',
        'live_cp_ram_read','original_task_scheduler_verified','original_RTOS_timing_verified',
        'original_semaphore_timing_verified','hardware_verified','ap_consumed','runtime_consumed',
        'native_verified','control_consumed','connection_verified','format_consumed',
        'general_format_ready','cmos_verified','frames_verified','capture_verified')
    fields=backup.infrabb_vef_control_connection_profile_fields(PROFILE)
    assert set(fields)=={PREFIX+name for name in (*expected,*false_names)}
    for name,value in expected.items():
        assert type(fields[PREFIX+name]) is type(value)
        assert json.dumps(fields[PREFIX+name])==json.dumps(value)
    assert all(fields[PREFIX+name] is False for name in false_names)
    off=backup.infrabb_vef_control_connection_profile_fields('')
    assert all(off[PREFIX+name] is None for name in expected)
    assert all(off[PREFIX+name] is False for name in false_names)
    with pytest.raises(ValueError):backup.infrabb_vef_control_connection_profile_fields('unknown')
    header=(HERE/'device-models/infrabb-vef-control-connection.h').read_text()
    assert '#define FULL_INFRABB_VEF_CONTROL_CONNECTION_PROFILE "'+PROFILE+'"' in header


def test_launcher_default_off_exact_fifth_host_switch_and_complete_chain(tmp_path):
    launcher=load_script('vef_control_start_menu','start-menu.py')
    fourth=fourth_environment(tmp_path)
    for env in ({},fourth,{**fourth,GUEST:PROFILE}):
        assert GUEST not in launcher.profile_environment(env,natural_boot=True)
    env=host_environment(tmp_path)
    selected=launcher.profile_environment(env,natural_boot=True)
    assert selected[GUEST]==PROFILE
    assert selected['MENU_INFRABB_VEF_CONNECT']==backup.INFRABB_VEF_CONNECT_PROFILE
    with pytest.raises(ValueError):launcher.profile_environment(env,natural_boot=False)
    for name in PREDECESSORS:
        bad=dict(env);bad.pop(name)
        with pytest.raises(ValueError):launcher.profile_environment(bad,natural_boot=True)
        if name not in ('A7C2_BACKUP_BUILD','A7C2_DIRECTORY_SD'):
            with pytest.raises(ValueError):launcher.profile_environment({**env,name:'unknown'},natural_boot=True)
    for name,value in [(HOST,'unknown'),('SEED_BACKUP','private'),('SEED_BACKUP','full'),
                       ('MENU_USB_NET','1'),('A7C2_HOST_SD','256gb'),('A7C2_SD_SPARSE','10g-empty'),
                       *[(key,'1') for key in backup.BB_MODE_CONFLICTS]]:
        with pytest.raises(ValueError):launcher.profile_environment({**env,name:value},natural_boot=True)


def qemu_fifth_guard():
    tree=ast.parse((HERE/'qemu-menu-probe.py').read_text())
    return next(node for node in tree.body if isinstance(node,ast.If) and any(
        isinstance(call,ast.Call) and isinstance(call.func,ast.Attribute) and
        ast.unparse(call.func)=='parser.error' and call.args and isinstance(call.args[0],ast.Constant) and
        str(call.args[0].value).startswith('InfraBB VEF control connection requires') for call in ast.walk(node)))


def test_qemu_guard_requires_four_predecessors_and_exact_host_switch(tmp_path):
    code=compile(ast.Module(body=[qemu_bb_guard(),qemu_imaging_guard(),qemu_control_guard(),
        qemu_adf_guard(),qemu_vef_guard(),qemu_fifth_guard()],type_ignores=[]),'<fifth-guards>','exec')
    scope={**guard_scope(),**{name:getattr(backup,name) for name in (
        'IMAGING_CONNECT_PROFILE','IMAGING_CONTROL_CONNECT_PROFILE','IMAGING_ADF_CONNECT_PROFILE',
        'INFRABB_VEF_CONNECT_PROFILE','FULL_INFRABB_VEF_CONTROL_CONNECTION_PROFILE')},
        'imaging_pin_connection_profile':backup.IMAGING_CONNECT_PROFILE,
        'imaging_control_connection_profile':backup.IMAGING_CONTROL_CONNECT_PROFILE,
        'imaging_adf_connection_profile':backup.IMAGING_ADF_CONNECT_PROFILE,
        'infrabb_vef_connection_profile':backup.INFRABB_VEF_CONNECT_PROFILE,
        'infrabb_vef_control_connection_profile':PROFILE}
    valid={**host_environment(tmp_path),'A7C2_DIRECTORY_SD_PROFILE':'directory-vvfat-256gb-v1',
           'MENU_PIN_REGISTRY':'1','MENU_PIN_CONTROL_MEMORY':'1','MENU_PIN_CONNECTION':'cold'}
    def run(env,**changes):
        with mock.patch.dict(os.environ,env,clear=True):exec(code,{**scope,**changes})
    run(valid)
    run({},bb_set_mode_profile='',imaging_pin_connection_profile='',imaging_control_connection_profile='',
        imaging_adf_connection_profile='',infrabb_vef_connection_profile='',infrabb_vef_control_connection_profile='')
    run({name:value for name,value in valid.items() if name!=HOST},infrabb_vef_control_connection_profile='')
    for name in ('infrabb_vef_connection_profile','imaging_adf_connection_profile',
                 'imaging_control_connection_profile','imaging_pin_connection_profile','bb_set_mode_profile',
                 'backup_sync','cp_background','udate_distribution','touch_panel','tcin_detect','dfs_selector',
                 'vef_path_profile','adf_proc_path_profile','adf_set_input_profile','adf_set_output_profile'):
        with pytest.raises(SystemExit):run(valid,**{name:''})
    for name in (HOST,'A7C2_INFRABB_VEF_CONNECT','A7C2_IMAGING_ADF_CONNECT',
                 'A7C2_IMAGING_CONTROL_CONNECT','A7C2_IMAGING_CONNECT','A7C2_BB_SET_MODE',
                 'A7C2_DIRECTORY_SD_PROFILE','SEED_BACKUP','MENU_PIN_REGISTRY','MENU_PIN_CONTROL_MEMORY','MENU_PIN_CONNECTION'):
        bad=dict(valid);bad.pop(name)
        with pytest.raises(SystemExit):run(bad)
        with pytest.raises(SystemExit):run({**valid,name:'unknown'})
    with pytest.raises(SystemExit):run(valid,infrabb_vef_control_connection_profile='unknown')
    for name in backup.BB_MODE_CONFLICTS:
        with pytest.raises(SystemExit):run({**valid,name:'1'})


def test_prepare_rejects_invalid_fifth_before_candidate_or_files(tmp_path,monkeypatch):
    launcher=load_script('vef_control_prepare_menu','start-menu.py')
    env=launcher.profile_environment(host_environment(tmp_path),natural_boot=True)
    env.update(SEED_BACKUP='alllang',A7C2_DIRECTORY_SD_PROFILE='directory-vvfat-256gb-v1')
    def no_build(*args):raise AssertionError('invalid fifth profile reached candidate/filesystem work')
    monkeypatch.setattr(backup,'validate_build',no_build)
    for name,value in [(GUEST,'unknown'),(HOST,''),(HOST,'unknown'),('MENU_INFRABB_VEF_CONNECT',''),
                       ('A7C2_INFRABB_VEF_CONNECT',''),('MENU_IMAGING_ADF_CONNECT',''),
                       ('MENU_IMAGING_CONTROL_CONNECT',''),('MENU_IMAGING_CONNECT',''),('MENU_BB_SET_MODE',''),
                       ('MENU_ADF_SET_OUTPUT',''),('MENU_PIN_REGISTRY',''),('MENU_PIN_CONTROL_MEMORY',''),
                       ('MENU_PIN_CONNECTION',''),('SEED_BACKUP','private'),('A7C2_DIRECTORY_SD_PROFILE',''),
                       *[(key,'1') for key in backup.BB_MODE_CONFLICTS]]:
        with pytest.raises(ValueError):backup.prepare_profile(HERE,{**env,name:value})


@pytest.mark.parametrize('enabled',[False,True])
def test_receipt_manifest_and_shell_exports_preserve_all_four_profiles(tmp_path,enabled):
    build=build_fixture(tmp_path)[0]
    env=host_environment(tmp_path,build)
    if not enabled:env.pop(HOST)
    launcher=load_script('vef_control_receipt_menu','start-menu.py')
    host=launcher.profile_environment(env,natural_boot=True)
    with directory_lease(Path(env['A7C2_DIRECTORY_SD'])) as lease:
        host.update(directory_profile(HERE,lease,tmp_path/'directory-profile'))
        host.update(backup.prepare_profile(HERE,host))
    fields=backup.infrabb_vef_control_connection_profile_fields(PROFILE if enabled else '')
    receipt=json.loads(Path(host['MENU_BACKUP_PROFILE_RECEIPT']).read_text())
    previous=(backup.infrabb_vef_connection_profile_fields(backup.INFRABB_VEF_CONNECT_PROFILE),
              backup.imaging_adf_connection_profile_fields(backup.IMAGING_ADF_CONNECT_PROFILE),
              backup.imaging_control_connection_profile_fields(backup.IMAGING_CONTROL_CONNECT_PROFILE),
              backup.imaging_pin_connection_profile_fields(backup.IMAGING_CONNECT_PROFILE))
    for expected in (fields,*previous):
        assert all(name in receipt and type(receipt[name]) is type(value) and
                   json.dumps(receipt[name])==json.dumps(value) for name,value in expected.items())
    setup=menu_probe_setup(host);guest=clean_guest_environment(setup)
    assert guest.get(GUEST)==(PROFILE if enabled else None)
    assert guest['MENU_INFRABB_VEF_CONNECT']==backup.INFRABB_VEF_CONNECT_PROFILE
    assert HOST not in guest
    assert sum(line.startswith('export '+GUEST+'=') for line in setup)==int(enabled)
    if enabled:
        for name in (HOST,GUEST,'MENU_INFRABB_VEF_CONNECT','A7C2_INFRABB_VEF_CONNECT',
                     'MENU_IMAGING_ADF_CONNECT','A7C2_IMAGING_ADF_CONNECT','MENU_IMAGING_CONTROL_CONNECT',
                     'A7C2_IMAGING_CONTROL_CONNECT','MENU_IMAGING_CONNECT','A7C2_IMAGING_CONNECT','MENU_BB_SET_MODE'):
            assert GUEST not in clean_guest_environment(menu_probe_setup({**host,name:''}))
    tree=ast.parse((HERE/'qemu-menu-probe.py').read_text())
    manifest=next(node.value for node in tree.body if isinstance(node,ast.Assign) and
                  isinstance(node.targets[0],ast.Name) and node.targets[0].id=='manifest')
    spread=next(value for key,value in zip(manifest.keys,manifest.values) if key is None and
                isinstance(value,ast.Call) and isinstance(value.func,ast.Name) and
                value.func.id=='infrabb_vef_control_connection_profile_fields')
    scope={'infrabb_vef_control_connection_profile':PROFILE if enabled else '',
           'infrabb_vef_control_connection_profile_fields':backup.infrabb_vef_control_connection_profile_fields}
    assert eval(compile(ast.Expression(spread),'<fifth-manifest>','eval'),scope)==fields
    validator=next(node for node in tree.body if isinstance(node,ast.If) and
        isinstance(node.test,ast.Name) and node.test.id=='backup_sync' and any(
            isinstance(call,ast.Call) and isinstance(call.func,ast.Name) and call.func.id=='validate_build'
            for call in ast.walk(node)))
    code=compile(ast.Module(body=[validator],type_ignores=[]),'<real-fifth-receipt-validator>','exec')
    scope.update(os=os,json=json,Path=Path,base=HERE,sha256_file=backup.sha,
        backup_sync=backup.PROFILE,env=host,kernel_script=Path(host['MENU_KERNEL_SCRIPT']),
        board_dtb=Path(host['MENU_DTB']),adf_proc_path_profile=backup.ADF_PROFILE,
        adf_set_input_profile=backup.INPUT_PROFILE,adf_set_output_profile=backup.OUTPUT_PROFILE,
        bb_set_mode_profile=backup.BB_SET_MODE_PROFILE,imaging_pin_connection_profile=backup.IMAGING_CONNECT_PROFILE,
        imaging_control_connection_profile=backup.IMAGING_CONTROL_CONNECT_PROFILE,
        imaging_adf_connection_profile=backup.IMAGING_ADF_CONNECT_PROFILE,
        infrabb_vef_connection_profile=backup.INFRABB_VEF_CONNECT_PROFILE,
        vef_pinmem_input_connection_profile='',vef_pinmem_control_connection_profile='',
        pinmem_peer_connections_profile='',adf_hdmi_audio_connection_profile='',
        pinmem_hdmi_video_connection_profile='',pinmem_osd_connection_profile='',cp302c_no_transition_profile='',
        udate_kernel_receipt=HERE.parents[1]/'report/virtual-cp/udate-distribution/verification.json',
        overwrite_manifest=None,settings_restore_manifest=None)
    scope.update({name+'_profile_fields':getattr(backup,name+'_profile_fields') for name in PROFILE_NAMES})
    path=Path(host['MENU_BACKUP_PROFILE_RECEIPT'])
    with mock.patch.dict(os.environ,host,clear=True):
        exec(code,scope)
        for name,value in fields.items():
            bad=copy.deepcopy(receipt);bad.pop(name);path.write_text(json.dumps(bad))
            with pytest.raises(ValueError,match='identity/admission mismatch'):exec(code,scope)
            bad[name]=(int(not value) if type(value) is bool else float(value) if type(value) is int else 'wrong')
            path.write_text(json.dumps(bad))
            with pytest.raises(ValueError,match='identity/admission mismatch'):exec(code,scope)
        if enabled:
            for name in ('source_pin','peer_pin','source_state_path','vef_posthook_allowed_ordinals','backing_records_preserved'):
                bad=copy.deepcopy(receipt);bad[PREFIX+name][0]=float(bad[PREFIX+name][0])
                path.write_text(json.dumps(bad))
                with pytest.raises(ValueError,match='identity/admission mismatch'):exec(code,scope)
        path.write_text(json.dumps(receipt));exec(code,scope)


def test_gtk_rejects_unsafe_fifth_flow_before_xvfb(tmp_path):
    driver=load_script('vef_control_gtk_driver','check-natural-gtk-input.py')
    build=make_candidate(tmp_path);card=tmp_path/'card';card.mkdir()
    env=host_environment(tmp_path,build)
    safe=['check-natural-gtk-input.py','--new-ui','--firstboot','--simplified-chinese',
          '--natural-shutter','--export-sd','--host-sd-dir',str(card),'--candidate-build',str(build)]
    cases=[([item for item in safe if item!=flag],env) for flag in (
        '--new-ui','--firstboot','--simplified-chinese','--natural-shutter','--export-sd','--candidate-build')]
    cases.extend((safe,{**env,name:''}) for name in PREDECESSORS if name!='A7C2_DIRECTORY_SD')
    cases.extend((safe,{**env,name:value}) for name,value in (
        (HOST,'unknown'),('A7C2_BACKUP_BUILD',str(tmp_path/'other')),
        ('A7C2_DIRECTORY_SD',str(tmp_path/'other-card')),('SEED_BACKUP','private'),('SEED_BACKUP','full'),
        *[(key,'1') for key in backup.BB_MODE_CONFLICTS]))
    for argv,values in cases:
        with mock.patch.object(driver.sys,'argv',argv),mock.patch.dict(driver.os.environ,values,clear=True), \
             mock.patch.object(driver.subprocess,'Popen',side_effect=AssertionError('must reject before Xvfb')):
            with pytest.raises(ValueError):driver.main()
    with mock.patch.object(driver.sys,'argv',safe),mock.patch.dict(driver.os.environ,env,clear=True), \
         mock.patch.object(driver.subprocess,'Popen',side_effect=RuntimeError('accepted-before-Xvfb')):
        with pytest.raises(RuntimeError,match='accepted-before-Xvfb'):driver.main()


def test_actual_guest_exports_execute_entire_c_constructor_and_owner_failures(tmp_path,bb_constructor):
    launcher=load_script('vef_control_ctor_menu','start-menu.py')
    host=launcher.profile_environment(host_environment(tmp_path),natural_boot=True)
    host.update(MENU_BACKUP_SYNC=backup.PROFILE,SEED_BACKUP='alllang',
                A7C2_DIRECTORY_SD_PROFILE='directory-vvfat-256gb-v1')
    guest=clean_guest_environment(menu_probe_setup(host))
    assert guest[GUEST]==PROFILE and HOST not in guest and 'MENU_OBSERVE_SELFTEST' not in guest
    log=bb_constructor(guest)
    assert 'imaging=1 imaging_init=1 control=1 control_init=1 adf=1 adf_init=1 vef=1 vef_init=1 vef_control=1 vef_control_init=1' in log
    assert 'FULL_INFRABB_VEF_CONTROL_CONNECT_PROFILE requested='+PROFILE+' enabled=1 first_missing=none ' in log
    assert 'initialized=1 unadmitted_count=0 before_any_input=1 connection_verified=0 capture_verified=0' in log
    for name in ('MENU_INFRABB_VEF_CONNECT','MENU_IMAGING_ADF_CONNECT','MENU_IMAGING_CONTROL_CONNECT',
                 'MENU_IMAGING_CONNECT','MENU_BB_SET_MODE','MENU_ADF_SET_OUTPUT','MENU_BACKUP_SYNC',
                 'MENU_CP_BACKGROUND','MENU_UDATE_DISTRIBUTION','MENU_TOUCH_PANEL','MENU_TCIN_DETECT',
                 'MENU_DFS_SELECTOR','MENU_AUDIO_BOOT_CONFIG','MENU_PIN_REGISTRY','MENU_PIN_CONTROL_MEMORY','MENU_PIN_CONNECTION'):
        bad=dict(guest);bad.pop(name)
        assert ' vef_control=0 vef_control_init=0' in bb_constructor(bad)
    for change in ({GUEST:'unknown'},{GUEST:''},{'MENU_INFRABB_VEF_CONNECT':'unknown'},
                   {'MENU_OBSERVE_SELFTEST':'1'}):
        assert ' vef_control=0 vef_control_init=0' in bb_constructor({**guest,**change})
    for options in ({'input_enabled':False},{'owner_rc':-1021},{'imaging_owner_rc':-1021},
                    {'control_owner_rc':-1021},{'adf_owner_rc':-1021},{'vef_owner_rc':-1021}):
        assert ' vef_control=0 vef_control_init=0' in bb_constructor(guest,**options)
    failure=bb_constructor(guest,vef_control_owner_rc=-1021)
    assert ' vef=1 vef_init=1 vef_control=0 vef_control_init=1' in failure
    assert 'enabled=0 first_missing=owner-init ' in failure
    host.pop(HOST);host.pop(GUEST)
    default_guest=clean_guest_environment(menu_probe_setup(host))
    assert GUEST not in default_guest
    default_log=bb_constructor(default_guest)
    assert ' vef=1 vef_init=1 vef_control=0 vef_control_init=0' in default_log
    assert 'FULL_INFRABB_VEF_CONTROL_CONNECT_PROFILE ' not in default_log


def test_gtk_typed_fifth_admission_checks_both_receipts():
    tree=ast.parse((HERE/'check-natural-gtk-input.py').read_text())
    admission=next(node for node in ast.walk(tree) if isinstance(node,ast.If) and
        isinstance(node.test,ast.Name) and node.test.id=='requested_infrabb_vef_control_connect' and
        isinstance(node.body[0],ast.Assign) and isinstance(node.body[0].targets[0],ast.Name) and
        node.body[0].targets[0].id=='expected_infrabb_vef_control')
    code=compile(ast.Module(body=[admission],type_ignores=[]),'<fifth-runtime-admission>','exec')
    fields=backup.infrabb_vef_control_connection_profile_fields(PROFILE)
    actual={**fields,'backup_transport':copy.deepcopy(fields),'selected_observer_matches_build':True}
    scope={'requested_infrabb_vef_control_connect':'','actual':actual,'proof':{},'json':json,
           'infrabb_vef_control_connection_profile_fields':backup.infrabb_vef_control_connection_profile_fields}
    exec(code,scope);assert not scope['proof']
    scope['requested_infrabb_vef_control_connect']=PROFILE
    exec(code,scope);assert scope['proof']['infrabb_vef_control_connection_admission']==fields
    for section in ('top','transport'):
        for name,value in fields.items():
            bad=copy.deepcopy(actual);target=bad if section=='top' else bad['backup_transport'];target.pop(name)
            scope.update(actual=bad,proof={})
            with pytest.raises(RuntimeError):exec(code,scope)
            target[name]=(int(not value) if type(value) is bool else float(value) if type(value) is int else
                          tuple(value) if isinstance(value,list) else 'wrong')
            with pytest.raises(RuntimeError):exec(code,scope)
        for name in ('source_pin','peer_pin','source_state_path','vef_posthook_allowed_ordinals','backing_records_preserved'):
            bad=copy.deepcopy(actual);target=bad if section=='top' else bad['backup_transport']
            target[PREFIX+name][0]=float(target[PREFIX+name][0]);scope.update(actual=bad,proof={})
            with pytest.raises(RuntimeError):exec(code,scope)
    scope.update(actual={**actual,'selected_observer_matches_build':False},proof={})
    with pytest.raises(RuntimeError):exec(code,scope)
