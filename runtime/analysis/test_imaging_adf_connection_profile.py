"""Default-off third InfraImaging AUDIO0 -> ADF AUDIO0 profile admission."""
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
from test_imaging_control_connection_profile import (host_environment as control_environment,
                                                      qemu_control_guard)

PROFILE=backup.IMAGING_ADF_CONNECT_PROFILE


def host_environment(tmp_path,build=None):
    return {**control_environment(tmp_path,build),'A7C2_IMAGING_ADF_CONNECT':PROFILE}


def test_typed_fields_pin_type3_full_sids_ten_adf_pins_and_zero_side_effects():
    expected={
        'profile':PROFILE,'source_pin':[3,2,0,0x90050004],'peer_pin':[3,1,0,0x9058003f],
        'source_registry_count':6,'source_registry_slot':4,
        'sink_registry_count':10,'sink_registry_slot':4,
        'request_bytes':64,'reply_bytes':56,'reply_command':0x8001,'unique_reply_count':1,
        'source_state_path':[1,2,0],'sink_state_path':[1,0],
        'internal_commands':[0x100,0x8100],'internal_message_bytes':[64,72],
        'sink_callback_guard_type':5,'sink_callback_guard_direction':1,'sink_callback_guard_index':0,
        'sink_callback_guard_checked':True,'sink_callback_selected':False,
        'sink_connected_marker_write_count':0,'dmm_allocation_count':0,'ssyn_notice_count':0,
        'pcm_consumption_count':0,'new_b0_command_count':0,'source7_event_count':0,
        'avio_job_count':0,'format_cache_write_count':0,
        'first_edge_profile':backup.IMAGING_CONNECT_PROFILE,
        'control_edge_profile':backup.IMAGING_CONTROL_CONNECT_PROFILE,
        'first_edge_requires_ap_consumed':True,'first_edge_requires_clean':True,
        'first_edge_requires_marker_known':True,'first_edge_marker_value':1,
        'first_edge_requires_data_Free':True,'first_edge_requires_pool_released':True,
        'control_edge_requires_ap_consumed':True,'control_edge_requires_clean':True,
        'control_edge_requires_marker_known':True,'control_edge_marker_value':1,
        'predecessors_require_no_outstanding':True,'predecessor_histories_unchanged':True,
        'first_edge_config_after':[0,1,1920,1080,0],
        'completion_scope':'two-edge-prerequisites-and-zero-audio-format-effects',
        'source_state_source':'public-InfraImaging-image-constructor',
        'sink_state_source':'public-InfraADF-image-constructor',
        'mapping_profile':'virtual-pin-control-reserved-ram-v1',
        'internal_control_policy':'native-provider-consumption-not-original-CP-tasks',
    }
    fields=backup.imaging_adf_connection_profile_fields(PROFILE)
    for name,value in expected.items():
        actual=fields['imaging_adf_connection_'+name]
        assert type(actual) is type(value) and json.dumps(actual)==json.dumps(value)
    false_fields={'imaging_adf_connection_'+name for name in (
        'original_cp_executed','original_cp_ram_mapping_verified','live_cp_ram_read',
        'original_task_scheduler_verified','original_semaphore_timing_verified','hardware_verified',
        'ap_consumed','runtime_consumed','control_consumed','connection_verified',
        'callback_guard_verified','pcm_verified','audio_output_verified','frames_verified','capture_verified')}
    assert set(fields)=={'imaging_adf_connection_'+name for name in expected}|false_fields
    assert all(fields[name] is False for name in false_fields)
    off=backup.imaging_adf_connection_profile_fields('')
    assert all(value is (False if name in false_fields else None) for name,value in off.items())
    with pytest.raises(ValueError):backup.imaging_adf_connection_profile_fields('unknown')


def test_launcher_default_off_and_complete_second_chain_required(tmp_path):
    launcher=load_script('adf_connection_start_menu','start-menu.py')
    control=control_environment(tmp_path)
    for env in ({},control,{**control,'MENU_IMAGING_ADF_CONNECT':PROFILE}):
        assert 'MENU_IMAGING_ADF_CONNECT' not in launcher.profile_environment(env,natural_boot=True)
    env=host_environment(tmp_path)
    selected=launcher.profile_environment(env,natural_boot=True)
    assert selected['MENU_IMAGING_ADF_CONNECT']==PROFILE
    assert selected['MENU_IMAGING_CONTROL_CONNECT']==backup.IMAGING_CONTROL_CONNECT_PROFILE
    assert selected['MENU_IMAGING_CONNECT']==backup.IMAGING_CONNECT_PROFILE
    with pytest.raises(ValueError):launcher.profile_environment(env,natural_boot=False)
    for name in ('A7C2_IMAGING_CONTROL_CONNECT','A7C2_IMAGING_CONNECT','A7C2_BB_SET_MODE',
                 'A7C2_BACKUP_SYNC','A7C2_BACKUP_BUILD','A7C2_DIRECTORY_SD','A7C2_CP_BACKGROUND',
                 'A7C2_UDATE_DISTRIBUTION','A7C2_TOUCH_PANEL','A7C2_TCIN_DETECT','A7C2_DFS_SELECTOR',
                 'A7C2_VEF_PATH','A7C2_ADF_PROC_PATH','A7C2_ADF_SET_INPUT','A7C2_ADF_SET_OUTPUT'):
        bad=dict(env);bad.pop(name)
        with pytest.raises(ValueError):launcher.profile_environment(bad,natural_boot=True)
    for name,value in [('A7C2_IMAGING_ADF_CONNECT','unknown'),('A7C2_IMAGING_CONTROL_CONNECT','unknown'),
                       ('SEED_BACKUP','private'),('SEED_BACKUP','full'),('MENU_USB_NET','1'),
                       ('A7C2_HOST_SD','256gb'),('A7C2_SD_SPARSE','10g-empty'),
                       *[(key,'1') for key in backup.BB_MODE_CONFLICTS]]:
        with pytest.raises(ValueError):launcher.profile_environment({**env,name:value},natural_boot=True)


def qemu_adf_guard():
    tree=ast.parse((HERE/'qemu-menu-probe.py').read_text())
    return next(node for node in tree.body if isinstance(node,ast.If) and any(
        isinstance(call,ast.Call) and isinstance(call.func,ast.Attribute) and
        ast.unparse(call.func)=='parser.error' and call.args and isinstance(call.args[0],ast.Constant) and
        str(call.args[0].value).startswith('Imaging ADF connection requires') for call in ast.walk(node)))


def test_qemu_requires_exact_host_third_profile_and_all_prior_guards():
    code=compile(ast.Module(body=[qemu_bb_guard(),qemu_imaging_guard(),qemu_control_guard(),qemu_adf_guard()],
                            type_ignores=[]),'<adf-connection-pre-vm-guards>','exec')
    def run(env,**changes):
        scope={**guard_scope(),'IMAGING_CONNECT_PROFILE':backup.IMAGING_CONNECT_PROFILE,
               'IMAGING_CONTROL_CONNECT_PROFILE':backup.IMAGING_CONTROL_CONNECT_PROFILE,
               'IMAGING_ADF_CONNECT_PROFILE':PROFILE,
               'imaging_pin_connection_profile':backup.IMAGING_CONNECT_PROFILE,
               'imaging_control_connection_profile':backup.IMAGING_CONTROL_CONNECT_PROFILE,
               'imaging_adf_connection_profile':PROFILE,**changes}
        with mock.patch.dict(os.environ,env,clear=True):exec(code,scope)
    valid={'A7C2_IMAGING_ADF_CONNECT':PROFILE,'A7C2_IMAGING_CONTROL_CONNECT':backup.IMAGING_CONTROL_CONNECT_PROFILE,
           'A7C2_IMAGING_CONNECT':backup.IMAGING_CONNECT_PROFILE,'A7C2_BB_SET_MODE':backup.BB_SET_MODE_PROFILE,
           'SEED_BACKUP':'alllang','A7C2_DIRECTORY_SD_PROFILE':'directory-vvfat-256gb-v1',
           'MENU_PIN_REGISTRY':'1','MENU_PIN_CONTROL_MEMORY':'1','MENU_PIN_CONNECTION':'cold'}
    run(valid)
    run({},bb_set_mode_profile='',imaging_pin_connection_profile='',imaging_control_connection_profile='',
        imaging_adf_connection_profile='')
    run({key:value for key,value in valid.items() if key!='A7C2_IMAGING_ADF_CONNECT'},imaging_adf_connection_profile='')
    for name in ('imaging_control_connection_profile','imaging_pin_connection_profile','bb_set_mode_profile',
                 'backup_sync','cp_background','udate_distribution','touch_panel','tcin_detect',
                 'dfs_selector','vef_path_profile','adf_proc_path_profile','adf_set_input_profile','adf_set_output_profile'):
        with pytest.raises(SystemExit):run(valid,**{name:''})
    with pytest.raises(SystemExit):run(valid,imaging_adf_connection_profile='unknown')
    for name in valid:
        bad=dict(valid);bad.pop(name)
        with pytest.raises(SystemExit):run(bad)
        with pytest.raises(SystemExit):run({**valid,name:'unknown'})
    for name in backup.BB_MODE_CONFLICTS:
        with pytest.raises(SystemExit):run({**valid,name:'1'})


def test_prepare_invalid_profiles_reject_before_candidate_or_files(tmp_path,monkeypatch):
    launcher=load_script('adf_connection_prepare_menu','start-menu.py')
    env=launcher.profile_environment(host_environment(tmp_path),natural_boot=True)
    env.update(SEED_BACKUP='alllang',A7C2_DIRECTORY_SD_PROFILE='directory-vvfat-256gb-v1')
    def no_build(*args):raise AssertionError('invalid third profile reached candidate/filesystem work')
    monkeypatch.setattr(backup,'validate_build',no_build)
    for name,value in [('MENU_IMAGING_ADF_CONNECT','unknown'),('A7C2_IMAGING_ADF_CONNECT',''),
                       ('A7C2_IMAGING_ADF_CONNECT','unknown'),('MENU_IMAGING_CONTROL_CONNECT',''),
                       ('A7C2_IMAGING_CONTROL_CONNECT',''),('MENU_IMAGING_CONNECT',''),
                       ('A7C2_IMAGING_CONNECT',''),('MENU_BB_SET_MODE',''),('MENU_PIN_REGISTRY',''),
                       ('MENU_PIN_CONTROL_MEMORY',''),('MENU_PIN_CONNECTION',''),('SEED_BACKUP','private'),
                       ('A7C2_DIRECTORY_SD_PROFILE',''),*[(key,'1') for key in backup.BB_MODE_CONFLICTS]]:
        with pytest.raises(ValueError):backup.prepare_profile(HERE,{**env,name:value})


@pytest.mark.parametrize('enabled',[False,True])
def test_public_receipt_manifest_and_exact_guest_exports(tmp_path,enabled):
    build=build_fixture(tmp_path)[0]
    env=host_environment(tmp_path,build)
    if not enabled:env.pop('A7C2_IMAGING_ADF_CONNECT')
    launcher=load_script('adf_connection_receipt_menu','start-menu.py')
    host=launcher.profile_environment(env,natural_boot=True)
    with directory_lease(Path(env['A7C2_DIRECTORY_SD'])) as lease:
        host.update(directory_profile(HERE,lease,tmp_path/'directory-profile'))
        host.update(backup.prepare_profile(HERE,host))
    expected=backup.imaging_adf_connection_profile_fields(PROFILE if enabled else '')
    receipt=json.loads(Path(host['MENU_BACKUP_PROFILE_RECEIPT']).read_text())
    for fields in (expected,backup.imaging_control_connection_profile_fields(backup.IMAGING_CONTROL_CONNECT_PROFILE),
                   backup.imaging_pin_connection_profile_fields(backup.IMAGING_CONNECT_PROFILE)):
        assert all(type(receipt[name]) is type(value) and json.dumps(receipt[name])==json.dumps(value)
                   for name,value in fields.items())
    setup=menu_probe_setup(host)
    guest=clean_guest_environment(setup)
    assert guest.get('MENU_IMAGING_ADF_CONNECT')==(PROFILE if enabled else None)
    assert guest['MENU_IMAGING_CONTROL_CONNECT']==backup.IMAGING_CONTROL_CONNECT_PROFILE
    assert guest['MENU_IMAGING_CONNECT']==backup.IMAGING_CONNECT_PROFILE
    assert 'A7C2_IMAGING_ADF_CONNECT' not in guest
    assert sum(line.startswith('export MENU_IMAGING_ADF_CONNECT=') for line in setup)==int(enabled)
    if enabled:
        for change in ({'A7C2_IMAGING_ADF_CONNECT':''},{'MENU_IMAGING_ADF_CONNECT':'unknown'},
                       {'MENU_IMAGING_CONTROL_CONNECT':''},{'A7C2_IMAGING_CONTROL_CONNECT':''},
                       {'MENU_IMAGING_CONNECT':''},{'A7C2_IMAGING_CONNECT':''},{'MENU_BB_SET_MODE':''}):
            assert 'MENU_IMAGING_ADF_CONNECT' not in clean_guest_environment(menu_probe_setup({**host,**change}))
    tree=ast.parse((HERE/'qemu-menu-probe.py').read_text())
    manifest=next(node.value for node in tree.body if isinstance(node,ast.Assign) and
                  isinstance(node.targets[0],ast.Name) and node.targets[0].id=='manifest')
    spread=next(value for key,value in zip(manifest.keys,manifest.values) if key is None and
                isinstance(value,ast.Call) and isinstance(value.func,ast.Name) and
                value.func.id=='imaging_adf_connection_profile_fields')
    scope={'imaging_adf_connection_profile':PROFILE if enabled else '',
           'imaging_adf_connection_profile_fields':backup.imaging_adf_connection_profile_fields}
    actual=eval(compile(ast.Expression(spread),'<actual-third-manifest-spread>','eval'),scope)
    assert actual==expected


def test_gtk_rejects_missing_chain_mismatched_candidate_directory_and_unsafe_flow(tmp_path):
    driver=load_script('adf_connection_gtk_driver','check-natural-gtk-input.py')
    build=make_candidate(tmp_path)
    card=tmp_path/'card';card.mkdir()
    env=host_environment(tmp_path,build)
    safe=['check-natural-gtk-input.py','--new-ui','--firstboot','--simplified-chinese',
          '--natural-shutter','--export-sd','--host-sd-dir',str(card),'--candidate-build',str(build)]
    cases=[([item for item in safe if item!=flag],env) for flag in (
        '--new-ui','--firstboot','--simplified-chinese','--natural-shutter','--export-sd','--candidate-build')]
    cases.extend((safe,{**env,name:value}) for name,value in (
        ('A7C2_IMAGING_ADF_CONNECT','unknown'),('A7C2_IMAGING_CONTROL_CONNECT',''),
        ('A7C2_IMAGING_CONNECT',''),('A7C2_BB_SET_MODE',''),('A7C2_BACKUP_BUILD',str(tmp_path/'other')),
        ('A7C2_DIRECTORY_SD',str(tmp_path/'other-card')),('SEED_BACKUP','private'),('SEED_BACKUP','full'),
        *[(key,'1') for key in backup.BB_MODE_CONFLICTS]))
    for argv,values in cases:
        with mock.patch.object(driver.sys,'argv',argv),mock.patch.dict(driver.os.environ,values,clear=True), \
             mock.patch.object(driver.subprocess,'Popen',side_effect=AssertionError('must reject before Xvfb')):
            with pytest.raises(ValueError):driver.main()
    with mock.patch.object(driver.sys,'argv',safe),mock.patch.dict(driver.os.environ,env,clear=True), \
         mock.patch.object(driver.subprocess,'Popen',side_effect=RuntimeError('accepted-before-Xvfb')):
        with pytest.raises(RuntimeError,match='accepted-before-Xvfb'):driver.main()


def test_qemu_rejects_missing_changed_and_untyped_third_receipt_fields(tmp_path):
    build=build_fixture(tmp_path)[0]
    launcher=load_script('adf_connection_typed_receipt_menu','start-menu.py')
    env=host_environment(tmp_path,build)
    host=launcher.profile_environment(env,natural_boot=True)
    with directory_lease(Path(env['A7C2_DIRECTORY_SD'])) as lease:
        host.update(directory_profile(HERE,lease,tmp_path/'receipt-profile'))
        host.update(backup.prepare_profile(HERE,host))
    tree=ast.parse((HERE/'qemu-menu-probe.py').read_text())
    validator=next(node for node in tree.body if isinstance(node,ast.If) and
        isinstance(node.test,ast.Name) and node.test.id=='backup_sync' and any(
            isinstance(call,ast.Call) and isinstance(call.func,ast.Name) and call.func.id=='validate_build'
            for call in ast.walk(node)))
    code=compile(ast.Module(body=[validator],type_ignores=[]),'<real-qemu-third-receipt-validator>','exec')
    scope={'os':os,'json':json,'Path':Path,'base':HERE,'sha256_file':backup.sha,
           'backup_sync':backup.PROFILE,'env':host,
           'kernel_script':Path(host['MENU_KERNEL_SCRIPT']),'board_dtb':Path(host['MENU_DTB']),
           'adf_proc_path_profile':backup.ADF_PROFILE,'adf_set_input_profile':backup.INPUT_PROFILE,
           'adf_set_output_profile':backup.OUTPUT_PROFILE,'bb_set_mode_profile':backup.BB_SET_MODE_PROFILE,
           'imaging_pin_connection_profile':backup.IMAGING_CONNECT_PROFILE,
           'imaging_control_connection_profile':backup.IMAGING_CONTROL_CONNECT_PROFILE,
           'imaging_adf_connection_profile':PROFILE,'infrabb_vef_connection_profile':'',
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
        for name,value in backup.imaging_adf_connection_profile_fields(PROFILE).items():
            changed=copy.deepcopy(original);changed.pop(name)
            path.write_text(json.dumps(changed))
            with pytest.raises(ValueError,match='identity/admission mismatch'):exec(code,scope)
            changed[name]=(int(not value) if type(value) is bool else float(value) if type(value) is int else 'wrong')
            path.write_text(json.dumps(changed))
            with pytest.raises(ValueError,match='identity/admission mismatch'):exec(code,scope)
        for name in ('source_pin','peer_pin','source_state_path','first_edge_config_after'):
            changed=copy.deepcopy(original)
            changed['imaging_adf_connection_'+name][0]=float(changed['imaging_adf_connection_'+name][0])
            path.write_text(json.dumps(changed))
            with pytest.raises(ValueError,match='identity/admission mismatch'):exec(code,scope)
        path.write_text(json.dumps(original));exec(code,scope)


def test_complete_guest_exports_execute_actual_third_constructor_and_owner_failures(tmp_path,bb_constructor):
    source=(HERE/'menu-observe.c').read_text()
    start=source.index('    const char *output_profile=getenv("MENU_ADF_SET_OUTPUT");')
    end=source.index('    software_gpe =',start)
    assert 'same_name(imaging_adf_profile,FULL_IMAGING_ADF_CONNECTION_PROFILE)' in source[start:end]
    launcher=load_script('adf_connection_constructor_menu','start-menu.py')
    host=launcher.profile_environment(host_environment(tmp_path),natural_boot=True)
    host.update(MENU_BACKUP_SYNC=backup.PROFILE,SEED_BACKUP='alllang',
                A7C2_DIRECTORY_SD_PROFILE='directory-vvfat-256gb-v1')
    guest=clean_guest_environment(menu_probe_setup(host))
    assert guest['MENU_IMAGING_ADF_CONNECT']==PROFILE
    assert 'A7C2_IMAGING_ADF_CONNECT' not in guest and 'MENU_OBSERVE_SELFTEST' not in guest
    log=bb_constructor(guest)
    assert 'imaging=1 imaging_init=1 control=1 control_init=1 adf=1 adf_init=1' in log
    assert 'FULL_IMAGING_ADF_CONNECT_PROFILE requested='+PROFILE+' enabled=1 first_missing=none ' in log
    assert 'no_format_checked=0 before_any_input=1 connection_verified=0 capture_verified=0' in log
    for name in ('MENU_IMAGING_CONTROL_CONNECT','MENU_IMAGING_CONNECT','MENU_BB_SET_MODE','MENU_ADF_SET_OUTPUT',
                 'MENU_BACKUP_SYNC','MENU_CP_BACKGROUND','MENU_UDATE_DISTRIBUTION','MENU_TOUCH_PANEL',
                 'MENU_TCIN_DETECT','MENU_DFS_SELECTOR','MENU_AUDIO_BOOT_CONFIG','MENU_PIN_REGISTRY',
                 'MENU_PIN_CONTROL_MEMORY','MENU_PIN_CONNECTION'):
        bad=dict(guest);bad.pop(name)
        assert ' adf=0 adf_init=0' in bb_constructor(bad)
    for change in ({'MENU_IMAGING_ADF_CONNECT':'unknown'},{'MENU_IMAGING_ADF_CONNECT':''},
                   {'MENU_IMAGING_CONTROL_CONNECT':'unknown'},{'MENU_OBSERVE_SELFTEST':'1'}):
        assert ' adf=0 adf_init=0' in bb_constructor({**guest,**change})
    for options in ({'input_enabled':False},{'owner_rc':-1021},{'imaging_owner_rc':-1021},
                    {'control_owner_rc':-1021}):
        assert ' adf=0 adf_init=0' in bb_constructor(guest,**options)
    failure=bb_constructor(guest,adf_owner_rc=-1021)
    assert 'imaging=1 imaging_init=1 control=1 control_init=1 adf=0 adf_init=1' in failure
    assert 'enabled=0 first_missing=owner-init ' in failure
    host.pop('MENU_IMAGING_ADF_CONNECT');host.pop('A7C2_IMAGING_ADF_CONNECT')
    default_guest=clean_guest_environment(menu_probe_setup(host))
    assert 'MENU_IMAGING_ADF_CONNECT' not in default_guest
    default_log=bb_constructor(default_guest)
    assert 'imaging=1 imaging_init=1 control=1 control_init=1 adf=0 adf_init=0' in default_log
    assert 'FULL_IMAGING_ADF_CONNECT_PROFILE ' not in default_log


def test_gtk_requires_typed_third_intent_in_both_receipts():
    tree=ast.parse((HERE/'check-natural-gtk-input.py').read_text())
    admission=next(node for node in ast.walk(tree) if isinstance(node,ast.If) and
        isinstance(node.test,ast.Name) and node.test.id=='requested_imaging_adf_connect' and
        isinstance(node.body[0],ast.Assign) and isinstance(node.body[0].targets[0],ast.Name) and
        node.body[0].targets[0].id=='expected_imaging_adf')
    code=compile(ast.Module(body=[admission],type_ignores=[]),'<third-runtime-admission>','exec')
    fields=backup.imaging_adf_connection_profile_fields(PROFILE)
    actual={**fields,'backup_transport':copy.deepcopy(fields),'selected_observer_matches_build':True}
    scope={'requested_imaging_adf_connect':'','actual':actual,'proof':{},'json':json,
           'imaging_adf_connection_profile_fields':backup.imaging_adf_connection_profile_fields}
    exec(code,scope);assert not scope['proof']
    scope['requested_imaging_adf_connect']=PROFILE
    exec(code,scope);assert scope['proof']['imaging_adf_connection_admission']==fields
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
        for name in ('source_pin','peer_pin','source_state_path','first_edge_config_after'):
            bad=copy.deepcopy(actual)
            target=bad if section=='top' else bad['backup_transport']
            target['imaging_adf_connection_'+name][0]=float(target['imaging_adf_connection_'+name][0])
            scope.update(actual=bad,proof={})
            with pytest.raises(RuntimeError):exec(code,scope)
    scope.update(actual={**actual,'selected_observer_matches_build':False},proof={})
    with pytest.raises(RuntimeError):exec(code,scope)
