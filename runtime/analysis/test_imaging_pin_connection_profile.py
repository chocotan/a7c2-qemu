"""Default-off first InfraImaging OUT1 -> InfraBB IN1 control/format profile."""
import argparse
import ast
import copy
import json
import os
from pathlib import Path
import struct
from unittest import mock

import pytest

import backup_profile as backup
from test_backup_profile import HERE, build_fixture, directory_lease, directory_profile
from test_bb_set_mode_profile import (bb_constructor, clean_guest_environment, guard_scope, host_environment as bb_environment,
                                      load_script, make_candidate, menu_probe_setup, qemu_bb_guard)

PROFILE=backup.IMAGING_CONNECT_PROFILE


def host_environment(tmp_path,build=None):
    return {**bb_environment(tmp_path,build),'A7C2_IMAGING_CONNECT':PROFILE}


def test_fields_pin_exact_edge_format_references_and_virtual_limits():
    fields=backup.imaging_pin_connection_profile_fields(PROFILE)
    expected={
        'profile':PROFILE,'source_pin':[0,2,1,0x90050004],'peer_pin':[0,1,1,0x9284074a],
        'request_bytes':64,'reply_bytes':56,'reply_command':0x8001,'unique_reply_count':1,
        'source_state_path':[1,2,0],'sink_state_path':[1,0],
        'sink_connected_marker_CP_VA':0x01acad10,'sink_connected_marker_value':1,
        'sink_connected_marker_initial_value_known':False,
        'internal_commands':[0x100,0x8100],'internal_message_bytes':[64,72],
        'dmm_unit':0x404,'dmm_owner_code':0x284,
        'dmm_owner_policy':'original-semantic-owner-code-not-service-SID',
        'dmm_allocate_message_bytes':216,'dmm_allocate_option':1,
        'dmm_operations':[0x20,0x25,0x24,0x23],'dmm_free_option':2,
        'buffer_bytes':80,'ssyn_header_hex':'06000000','ssyn_key':0,
        'format_payload_bytes':16,'format_payload_hex':'01000000000000008007000038040000',
        'format_notice_bytes':80,'format_notice_command':[0x1000,0x104,0x38,1],
        'config_after':[0,1,1920,1080,0],'config_semaphore':0x21,
        'config_lock_policy':'local-pthread-exclusion-not-original-semaphore-timing',
        'references_owner_open':[[1,0],[1,0],[1,1],[0,0]],
        'reference_stages':['creator-close','same-owner-transfer','consumer-open','consumer-Free'],
        'reference_policy':'same-owner-transfer-without-command21-share',
        'source_state_source':'public-InfraImaging-image-constructor',
        'mapping_profile':'virtual-pin-control-reserved-ram-v1',
        'completion_scope':'first-edge-control-and-SSYN-config-only',
        'internal_control_policy':'native-provider-consumption-not-original-CP-tasks',
    }
    assert len(bytes.fromhex(fields['imaging_pin_connection_format_payload_hex']))==16
    assert struct.unpack('<4I',bytes.fromhex(fields['imaging_pin_connection_format_payload_hex']))==(1,0,1920,1080)
    for name,value in expected.items():
        actual=fields['imaging_pin_connection_'+name]
        assert type(actual) is type(value) and actual==value
    false_fields={name for name in fields if name.removeprefix('imaging_pin_connection_') not in expected}
    assert false_fields=={'imaging_pin_connection_'+name for name in (
        'original_cp_executed','original_cp_ram_mapping_verified','original_task_scheduler_verified',
        'original_semaphore_timing_verified','hardware_verified','ap_consumed','runtime_consumed',
        'connection_verified','format_consumed','frames_verified','capture_verified')}
    assert all(fields[name] is False for name in false_fields)
    off=backup.imaging_pin_connection_profile_fields('')
    assert all(value is (False if name in false_fields else None) for name,value in off.items())
    with pytest.raises(ValueError):backup.imaging_pin_connection_profile_fields('unknown')


def test_launcher_default_off_and_requires_exact_complete_bb_chain(tmp_path):
    launcher=load_script('imaging_start_menu','start-menu.py')
    assert 'MENU_IMAGING_CONNECT' not in launcher.profile_environment({},natural_boot=True)
    bb=bb_environment(tmp_path)
    assert 'MENU_IMAGING_CONNECT' not in launcher.profile_environment(
        {**bb,'MENU_IMAGING_CONNECT':PROFILE},natural_boot=True)
    env=host_environment(tmp_path)
    selected=launcher.profile_environment(env,natural_boot=True)
    assert selected['MENU_IMAGING_CONNECT']==PROFILE
    assert selected['MENU_BB_SET_MODE']==backup.BB_SET_MODE_PROFILE
    assert selected['MENU_PIN_REGISTRY']=='1' and selected['MENU_PIN_CONNECTION']=='cold'
    with pytest.raises(ValueError):launcher.profile_environment(env,natural_boot=False)
    for name in ('A7C2_BB_SET_MODE','A7C2_BACKUP_SYNC','A7C2_BACKUP_BUILD','A7C2_DIRECTORY_SD',
                 'A7C2_CP_BACKGROUND','A7C2_UDATE_DISTRIBUTION','A7C2_TOUCH_PANEL','A7C2_TCIN_DETECT',
                 'A7C2_DFS_SELECTOR','A7C2_VEF_PATH','A7C2_ADF_PROC_PATH','A7C2_ADF_SET_INPUT','A7C2_ADF_SET_OUTPUT'):
        bad=dict(env);bad.pop(name)
        with pytest.raises(ValueError):launcher.profile_environment(bad,natural_boot=True)
    for name,value in [('A7C2_IMAGING_CONNECT','unknown'),('A7C2_BB_SET_MODE','unknown'),
                       ('SEED_BACKUP','private'),('SEED_BACKUP','full'),('MENU_USB_NET','1'),
                       ('A7C2_HOST_SD','256gb'),('A7C2_SD_SPARSE','10g-empty'),
                       *[(key,'1') for key in backup.BB_MODE_CONFLICTS]]:
        with pytest.raises(ValueError):launcher.profile_environment({**env,name:value},natural_boot=True)


def qemu_imaging_guard():
    tree=ast.parse((HERE/'qemu-menu-probe.py').read_text())
    return next(node for node in tree.body if isinstance(node,ast.If) and any(
        isinstance(call,ast.Call) and isinstance(call.func,ast.Attribute) and
        ast.unparse(call.func)=='parser.error' and call.args and isinstance(call.args[0],ast.Constant) and
        str(call.args[0].value).startswith('Imaging connection requires') for call in ast.walk(node)))


def test_qemu_admission_reuses_bb_chain_and_requires_exact_host_and_pins():
    code=compile(ast.Module(body=[qemu_bb_guard(),qemu_imaging_guard()],type_ignores=[]),
                 '<imaging-combined-pre-vm-guard>','exec')
    def run(env,**changes):
        scope={**guard_scope(),'IMAGING_CONNECT_PROFILE':PROFILE,
               'imaging_pin_connection_profile':PROFILE,**changes}
        with mock.patch.dict(os.environ,env,clear=True):exec(code,scope)
    valid={'A7C2_IMAGING_CONNECT':PROFILE,'A7C2_BB_SET_MODE':backup.BB_SET_MODE_PROFILE,
           'SEED_BACKUP':'alllang','A7C2_DIRECTORY_SD_PROFILE':'directory-vvfat-256gb-v1',
           'MENU_PIN_REGISTRY':'1','MENU_PIN_CONTROL_MEMORY':'1','MENU_PIN_CONNECTION':'cold'}
    run(valid)
    run({},bb_set_mode_profile='',imaging_pin_connection_profile='')
    with pytest.raises(SystemExit):run(valid,imaging_pin_connection_profile='unknown')
    with pytest.raises(SystemExit):run(valid,bb_set_mode_profile='')
    for key in valid:
        bad=dict(valid);bad.pop(key)
        with pytest.raises(SystemExit):run(bad)
        with pytest.raises(SystemExit):run({**valid,key:'unknown'})
    for name in ('backup_sync','cp_background','udate_distribution','touch_panel','tcin_detect',
                 'dfs_selector','vef_path_profile','adf_proc_path_profile','adf_set_input_profile',
                 'adf_set_output_profile'):
        with pytest.raises(SystemExit):run(valid,**{name:''})
    for key in backup.BB_MODE_CONFLICTS:
        with pytest.raises(SystemExit):run({**valid,key:'1'})


def test_prepare_rejects_invalid_profile_before_candidate_or_output(tmp_path,monkeypatch):
    launcher=load_script('imaging_prepare_menu','start-menu.py')
    env=launcher.profile_environment(host_environment(tmp_path),natural_boot=True)
    env.update(SEED_BACKUP='alllang',A7C2_DIRECTORY_SD_PROFILE='directory-vvfat-256gb-v1')
    def no_build(*args):raise AssertionError('invalid imaging profile reached candidate or filesystem work')
    monkeypatch.setattr(backup,'validate_build',no_build)
    for name,value in [('MENU_IMAGING_CONNECT','unknown'),('A7C2_IMAGING_CONNECT',''),
                       ('A7C2_IMAGING_CONNECT','unknown'),('MENU_BB_SET_MODE',''),
                       ('A7C2_BB_SET_MODE',''),('MENU_PIN_REGISTRY',''),('MENU_PIN_CONTROL_MEMORY',''),
                       ('MENU_PIN_CONNECTION',''),('SEED_BACKUP','private'),
                       ('A7C2_DIRECTORY_SD_PROFILE',''),*[(key,'1') for key in backup.BB_MODE_CONFLICTS]]:
        with pytest.raises(ValueError):backup.prepare_profile(HERE,{**env,name:value})


@pytest.mark.parametrize('enabled',[False,True])
def test_public_receipt_and_complete_guest_exports(tmp_path,enabled,bb_constructor):
    build=build_fixture(tmp_path)[0]
    env=host_environment(tmp_path,build)
    if not enabled:env.pop('A7C2_IMAGING_CONNECT')
    launcher=load_script('imaging_receipt_menu','start-menu.py')
    host=launcher.profile_environment(env,natural_boot=True)
    with directory_lease(Path(env['A7C2_DIRECTORY_SD'])) as lease:
        host.update(directory_profile(HERE,lease,tmp_path/'directory-profile'))
        host.update(backup.prepare_profile(HERE,host))
    expected=backup.imaging_pin_connection_profile_fields(PROFILE if enabled else '')
    receipt=json.loads(Path(host['MENU_BACKUP_PROFILE_RECEIPT']).read_text())
    assert all(type(receipt[name]) is type(value) and json.dumps(receipt[name])==json.dumps(value)
               for name,value in expected.items())
    setup=menu_probe_setup(host)
    guest=clean_guest_environment(setup)
    assert guest.get('MENU_IMAGING_CONNECT')==(PROFILE if enabled else None)
    for key,value in {
        'MENU_BB_SET_MODE':backup.BB_SET_MODE_PROFILE,'MENU_BACKUP_SYNC':backup.PROFILE,
        'MENU_CP_BACKGROUND':'virtual-mode3-cold-v1','MENU_UDATE_DISTRIBUTION':'virtual-roundtrip-v1',
        'MENU_TOUCH_PANEL':'virtual-config-v1','MENU_TCIN_DETECT':'virtual-inactive-v1',
        'MENU_DFS_SELECTOR':'virtual-selector-v1','MENU_VEF_PATH':'virtual-nomem-v1',
        'MENU_ADF_PROC_PATH':backup.ADF_PROFILE,'MENU_ADF_SET_INPUT':backup.INPUT_PROFILE,
        'MENU_ADF_SET_OUTPUT':backup.OUTPUT_PROFILE,'MENU_PIN_REGISTRY':'1',
        'MENU_PIN_CONTROL_MEMORY':'1','MENU_PIN_CONNECTION':'cold','MENU_DMM_UNIT_CONFIG':'1',
        'MENU_AUDIO_BOOT_CONFIG':'1',
    }.items():assert guest[key]==value
    assert 'A7C2_IMAGING_CONNECT' not in guest
    assert sum(line.startswith('export MENU_IMAGING_CONNECT=') for line in setup)==int(enabled)
    log=bb_constructor(guest)
    assert f'imaging={int(enabled)} imaging_init={int(enabled)}' in log
    if enabled:
        assert 'FULL_IMAGING_PIN_CONNECT_PROFILE requested='+PROFILE+' enabled=1 first_missing=none ' in log
        assert 'cache=1,0,0,0,0 before_any_input=1 connection_verified=0 capture_verified=0' in log
        for key in ('MENU_BB_SET_MODE','MENU_PIN_REGISTRY','MENU_PIN_CONTROL_MEMORY','MENU_PIN_CONNECTION'):
            bad=dict(guest);bad.pop(key)
            assert 'imaging=0 imaging_init=0' in bb_constructor(bad)
        for value in ('unknown',''):
            assert 'imaging=0 imaging_init=0' in bb_constructor({**guest,'MENU_IMAGING_CONNECT':value})
        assert 'imaging=0 imaging_init=1' in bb_constructor(guest,imaging_owner_rc=-1021)
        for change in ({'A7C2_IMAGING_CONNECT':''},{'MENU_IMAGING_CONNECT':'unknown'},
                       {'MENU_BB_SET_MODE':''}):
            assert 'MENU_IMAGING_CONNECT' not in clean_guest_environment(menu_probe_setup({**host,**change}))
    source=(HERE/'qemu-menu-probe.py').read_text()
    assert '**imaging_pin_connection_profile_fields(imaging_pin_connection_profile)' in source
    assert 'imaging_pin_connection_profile_fields(imaging_pin_connection_profile).items()' in source


def test_gtk_rejects_missing_natural_shutter_boundaries_before_process(tmp_path):
    driver=load_script('imaging_gtk_driver','check-natural-gtk-input.py')
    build=make_candidate(tmp_path)
    card=tmp_path/'card';card.mkdir()
    env=host_environment(tmp_path,build)
    safe=['check-natural-gtk-input.py','--new-ui','--firstboot','--simplified-chinese',
          '--natural-shutter','--export-sd','--host-sd-dir',str(card),'--candidate-build',str(build)]
    bad_cases=[([item for item in safe if item!=flag],env) for flag in (
        '--new-ui','--firstboot','--simplified-chinese','--natural-shutter','--export-sd','--candidate-build')]
    bad_cases.extend((safe,{**env,name:value}) for name,value in (
        ('A7C2_IMAGING_CONNECT','unknown'),('A7C2_BB_SET_MODE',''),('A7C2_BACKUP_BUILD',str(tmp_path/'other')),
        ('A7C2_DIRECTORY_SD',str(tmp_path/'other-card')),('SEED_BACKUP','private'),
        *[(key,'1') for key in backup.BB_MODE_CONFLICTS]))
    for argv,values in bad_cases:
        with mock.patch.object(driver.sys,'argv',argv),mock.patch.dict(driver.os.environ,values,clear=True), \
             mock.patch.object(driver.subprocess,'Popen',side_effect=AssertionError('must reject before Xvfb')):
            with pytest.raises(ValueError):driver.main()
    with mock.patch.object(driver.sys,'argv',safe),mock.patch.dict(driver.os.environ,env,clear=True), \
         mock.patch.object(driver.subprocess,'Popen',side_effect=RuntimeError('accepted-before-Xvfb')):
        with pytest.raises(RuntimeError,match='accepted-before-Xvfb'):driver.main()


def test_qemu_receipt_validator_rejects_changed_or_untyped_imaging_intent(tmp_path):
    build=build_fixture(tmp_path)[0]
    launcher=load_script('imaging_typed_receipt_menu','start-menu.py')
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
    code=compile(ast.Module(body=[validator],type_ignores=[]),'<real-qemu-backup-receipt-validator>','exec')
    scope={'os':os,'json':json,'Path':Path,'base':HERE,'sha256_file':backup.sha,
           'backup_sync':backup.PROFILE,'env':host,
           'kernel_script':Path(host['MENU_KERNEL_SCRIPT']),'board_dtb':Path(host['MENU_DTB']),
           'adf_proc_path_profile':backup.ADF_PROFILE,'adf_set_input_profile':backup.INPUT_PROFILE,
           'adf_set_output_profile':backup.OUTPUT_PROFILE,'bb_set_mode_profile':backup.BB_SET_MODE_PROFILE,
           'imaging_pin_connection_profile':PROFILE,'imaging_control_connection_profile':'',
           'imaging_adf_connection_profile':'','infrabb_vef_connection_profile':'',
           'infrabb_vef_control_connection_profile':'','vef_pinmem_input_connection_profile':'',
           'vef_pinmem_control_connection_profile':'','pinmem_peer_connections_profile':'',
           'adf_hdmi_audio_connection_profile':'',
           'pinmem_hdmi_video_connection_profile':'','pinmem_osd_connection_profile':'','cp302c_no_transition_profile':'',
           'adf_proc_profile_fields':backup.adf_proc_profile_fields,
           'adf_set_input_profile_fields':backup.adf_set_input_profile_fields,
           'adf_set_output_profile_fields':backup.adf_set_output_profile_fields,
           'bb_set_mode_profile_fields':backup.bb_set_mode_profile_fields,
           'imaging_pin_connection_profile_fields':backup.imaging_pin_connection_profile_fields,
           'imaging_control_connection_profile_fields':backup.imaging_control_connection_profile_fields,
           'imaging_adf_connection_profile_fields':backup.imaging_adf_connection_profile_fields,
           'infrabb_vef_connection_profile_fields':backup.infrabb_vef_connection_profile_fields,
           'infrabb_vef_control_connection_profile_fields':backup.infrabb_vef_control_connection_profile_fields,
           'vef_pinmem_input_connection_profile_fields':backup.vef_pinmem_input_connection_profile_fields,
           'vef_pinmem_control_connection_profile_fields':backup.vef_pinmem_control_connection_profile_fields,
           'pinmem_peer_connections_profile_fields':backup.pinmem_peer_connections_profile_fields,
           'adf_hdmi_audio_connection_profile_fields':backup.adf_hdmi_audio_connection_profile_fields,
           'pinmem_hdmi_video_connection_profile_fields':backup.pinmem_hdmi_video_connection_profile_fields,
           'pinmem_osd_connection_profile_fields':backup.pinmem_osd_connection_profile_fields,
           'cp302c_no_transition_profile_fields':backup.cp302c_no_transition_profile_fields,
           'udate_kernel_receipt':HERE.parents[1]/'report/virtual-cp/udate-distribution/verification.json',
           'overwrite_manifest':None,'settings_restore_manifest':None}
    path=Path(host['MENU_BACKUP_PROFILE_RECEIPT'])
    original=json.loads(path.read_text())
    with mock.patch.dict(os.environ,host,clear=True):
        exec(code,scope)
        fields=backup.imaging_pin_connection_profile_fields(PROFILE)
        for name,value in fields.items():
            changed=copy.deepcopy(original);changed.pop(name)
            path.write_text(json.dumps(changed))
            with pytest.raises(ValueError,match='identity/admission mismatch'):exec(code,scope)
            changed[name]=(0 if value is False else float(value) if type(value) is int else 'wrong')
            path.write_text(json.dumps(changed))
            with pytest.raises(ValueError,match='identity/admission mismatch'):exec(code,scope)
        changed=copy.deepcopy(original)
        changed['imaging_pin_connection_references_owner_open'][2][1]=1.0
        path.write_text(json.dumps(changed))
        with pytest.raises(ValueError,match='identity/admission mismatch'):exec(code,scope)
        path.write_text(json.dumps(original))
        exec(code,scope)


def test_gtk_requires_typed_manifest_in_both_receipts_before_admission():
    tree=ast.parse((HERE/'check-natural-gtk-input.py').read_text())
    admission=next(node for node in ast.walk(tree) if isinstance(node,ast.If) and
        isinstance(node.test,ast.Name) and node.test.id=='requested_imaging_connect' and
        isinstance(node.body[0],ast.Assign) and isinstance(node.body[0].targets[0],ast.Name) and
        node.body[0].targets[0].id=='expected_imaging')
    code=compile(ast.Module(body=[admission],type_ignores=[]),'<imaging-runtime-admission>','exec')
    fields=backup.imaging_pin_connection_profile_fields(PROFILE)
    actual={**fields,'backup_transport':copy.deepcopy(fields),'selected_observer_matches_build':True}
    scope={'requested_imaging_connect':'','actual':actual,'proof':{},'json':json,
           'imaging_pin_connection_profile_fields':backup.imaging_pin_connection_profile_fields}
    exec(code,scope);assert not scope['proof']
    scope['requested_imaging_connect']=PROFILE
    exec(code,scope);assert scope['proof']['imaging_pin_connection_admission']==fields
    for section in ('top','transport'):
        for name,value in fields.items():
            bad=copy.deepcopy(actual)
            target=bad if section=='top' else bad['backup_transport']
            target.pop(name)
            scope.update(actual=bad,proof={})
            with pytest.raises(RuntimeError):exec(code,scope)
            target[name]=(0 if value is False else float(value) if type(value) is int else
                          tuple(value) if isinstance(value,list) else 'wrong')
            with pytest.raises(RuntimeError):exec(code,scope)
        for name in ('source_pin','peer_pin','references_owner_open'):
            bad=copy.deepcopy(actual)
            target=bad if section=='top' else bad['backup_transport']
            target['imaging_pin_connection_'+name][0]=([1.0,0] if name=='references_owner_open' else 0.0)
            scope.update(actual=bad,proof={})
            with pytest.raises(RuntimeError):exec(code,scope)
    scope.update(actual={**actual,'selected_observer_matches_build':False},proof={})
    with pytest.raises(RuntimeError):exec(code,scope)
