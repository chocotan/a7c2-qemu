"""Default-off sixth VEF OUT2 -> PinMem IN0 format-forwarding profile admission."""
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
from test_infrabb_vef_connection_profile import qemu_vef_guard
from test_infrabb_vef_control_connection_profile import (
    PREDECESSORS as FIFTH_PREDECESSORS, PROFILE_NAMES, host_environment as fifth_environment,
    qemu_fifth_guard)

PROFILE=backup.FULL_VEF_PINMEM_INPUT_CONNECTION_PROFILE
PREFIX='vef_pinmem_input_connection_'
HOST='A7C2_VEF_PINMEM_INPUT_CONNECT'
GUEST='MENU_VEF_PINMEM_INPUT_CONNECT'
PREDECESSORS=('A7C2_INFRABB_VEF_CONTROL_CONNECT',*FIFTH_PREDECESSORS,'SEED_BACKUP')


def host_environment(tmp_path,build=None):
    return {**fifth_environment(tmp_path,build),HOST:PROFILE}


def test_fields_fix_same_handle_three_hop_contract_without_runtime_claims():
    fields=backup.vef_pinmem_input_connection_profile_fields(PROFILE)
    expected={
        'profile':PROFILE,'source_pin':[0,2,2,0x905a0048],'peer_pin':[0,1,0,0x90590818],
        'source_registry_count':16,'source_registry_slot':9,'sink_registry_count':13,'sink_registry_slot':0,
        'request_bytes':64,'reply_bytes':56,'reply_command':0x8001,'unique_reply_count':1,
        'source_state_path':[1,2,0],'sink_state_path':[1,0],
        'internal_commands':[0x100,0x8100],'internal_message_bytes':[64,72],
        'pinmem_record_index':0,'pinmem_record_raw_flags':3,'pinmem_record_code':1,
        'pinmem_record_component':1,'pinmem_record_width':1920,'pinmem_record_height':1080,
        'pinmem_record_source':'virtual-public-PinMem-constructor-projection',
        'buffer_bytes':80,'ssyn_header_hex':'01000000','ssyn_entry_type':0,'ssyn_key':0,
        'format_payload_bytes':16,'format_payload_hex':'01010300000000008007000038040000',
        'format_payload_fnv64':'37228cd728b41c0d','dmm_unit':0x404,
        'dmm_operations':[0x20,0x21,0x23,0x24,0x25,0x24,0x25,0x24,0x23],
        'dmm_message_bytes':[152]*5+[216]*4,'dmm_share_count':1,'dmm_consumer_token':0x55,
        'dmm_allocate_option':1,'dmm_allocate_wait':0xffffffff,
        'dmm_creator_release_option':2,'dmm_free_option':2,
        'dmm_vef_open_wait':0,'dmm_bb_open_wait':0xffffffff,'dmm_imaging_open_wait':0,
        'references_owner_open':[[1,1],[2,1],[1,0],[1,1],[1,0],[1,1],[1,0],[1,1],[0,0]],
        'format_notice_count':3,'format_notice_bytes':80,'format_notice_command':[0x1000,0x104,0x38,1],
        'format_notice_edges':[
            [[0,1,0,0x90590818],[0,2,2,0x905a0048]],
            [[0,1,1,0x905a0048],[0,2,1,0x9284074a]],
            [[0,1,1,0x9284074a],[0,2,1,0x90050004]]],
        'vef_current_after_hex':'0100000000000000010103008007000038040000',
        'bb_expected_after_hex':'01010300000000008007000038040000',
        'imaging_config_after':[1,1,1920,1080,3],
        'runtime_status22_required':1,'runtime_status22_known_required':1,
        'runtime_status22_writer_generation_required':1,'runtime_status22_writes_required':1,
        'runtime_status22_source':'earlier-SetPath1-completion-writer-not-NoMem-state2',
        'buffer_physical_base':0x500000000,'buffer_cp_virtual_base':0x80000000,
        'buffer_pool_policy':'same-existing-pool-without-reset',
        'predecessors_require_ap_consumed':True,'predecessors_require_clean':True,
        'predecessors_require_no_outstanding':True,'predecessors_require_pool_retired':True,
        'historical_first_fourth_commands_Free_AP_preserved':True,
        'nomem_history_preserved':True,'s0_ab_failure_history_preserved':True,
        'old_ordinal1_preserved':True,'foreign_speech_live_preserved':True,
        'precondition_refusal_policy':'unadmitted-only-no-request-or-fault-until-predecessors-ready',
        'partial_failure_policy':'fault-and-hold-live-buffer-and-current-cache-without-rollback',
        'dispatch_policy':'exact-edge-before-legacy-VEF-send-enter-other-traffic-falls-through',
        'completion_scope':'five-edge-prerequisites-and-three-hop-format-metadata-only',
    }
    for name,value in expected.items():
        assert type(fields[PREFIX+name]) is type(value)
        assert json.dumps(fields[PREFIX+name])==json.dumps(value)
    false_names=(
        'original_cp_executed','original_cp_ram_mapping_verified','original_cp_page_tables_verified',
        'live_cp_ram_read','original_task_scheduler_verified','original_RTOS_timing_verified',
        'original_semaphore_timing_verified','hardware_verified','ap_consumed','runtime_consumed',
        'runtime_status22_verified','native_verified','connection_verified','format_consumed',
        'format_propagation_verified','general_format_ready','cmos_verified','frames_verified','capture_verified')
    assert all(fields[PREFIX+name] is False for name in false_names)
    off=backup.vef_pinmem_input_connection_profile_fields('')
    assert fields.keys()==off.keys()
    assert all(value is (False if name in {PREFIX+key for key in false_names} else None)
               for name,value in off.items())
    payload=bytes.fromhex(fields[PREFIX+'format_payload_hex']);assert len(payload)==16
    digest=0xcbf29ce484222325
    for byte in payload:digest=((digest^byte)*0x100000001b3)&0xffffffffffffffff
    assert '%016x'%digest==fields[PREFIX+'format_payload_fnv64']
    with pytest.raises(ValueError):backup.vef_pinmem_input_connection_profile_fields('unknown')
    assert '#define FULL_VEF_PINMEM_INPUT_CONNECTION_PROFILE "'+PROFILE+'"' in (
        HERE/'device-models/vef-pinmem-input-connection.h').read_text()


def test_launcher_default_off_exact_sixth_switch_and_complete_chain(tmp_path):
    launcher=load_script('pinmem_input_start_menu','start-menu.py')
    fifth=fifth_environment(tmp_path)
    for env in ({},fifth,{**fifth,GUEST:PROFILE}):
        assert GUEST not in launcher.profile_environment(env,natural_boot=True)
    env=host_environment(tmp_path)
    selected=launcher.profile_environment(env,natural_boot=True)
    assert selected[GUEST]==PROFILE
    assert selected['MENU_INFRABB_VEF_CONTROL_CONNECT']==backup.FULL_INFRABB_VEF_CONTROL_CONNECTION_PROFILE
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


def qemu_sixth_guard():
    tree=ast.parse((HERE/'qemu-menu-probe.py').read_text())
    return next(node for node in tree.body if isinstance(node,ast.If) and any(
        isinstance(call,ast.Call) and isinstance(call.func,ast.Attribute) and
        ast.unparse(call.func)=='parser.error' and call.args and isinstance(call.args[0],ast.Constant) and
        str(call.args[0].value).startswith('VEF PinMem input connection requires') for call in ast.walk(node)))


def test_qemu_guard_requires_five_predecessors_and_exact_host_switch(tmp_path):
    code=compile(ast.Module(body=[qemu_bb_guard(),qemu_imaging_guard(),qemu_control_guard(),
        qemu_adf_guard(),qemu_vef_guard(),qemu_fifth_guard(),qemu_sixth_guard()],type_ignores=[]),'<sixth-guards>','exec')
    scope={**guard_scope(),**{name:getattr(backup,name) for name in (
        'IMAGING_CONNECT_PROFILE','IMAGING_CONTROL_CONNECT_PROFILE','IMAGING_ADF_CONNECT_PROFILE',
        'INFRABB_VEF_CONNECT_PROFILE','FULL_INFRABB_VEF_CONTROL_CONNECTION_PROFILE',
        'FULL_VEF_PINMEM_INPUT_CONNECTION_PROFILE')},
        'imaging_pin_connection_profile':backup.IMAGING_CONNECT_PROFILE,
        'imaging_control_connection_profile':backup.IMAGING_CONTROL_CONNECT_PROFILE,
        'imaging_adf_connection_profile':backup.IMAGING_ADF_CONNECT_PROFILE,
        'infrabb_vef_connection_profile':backup.INFRABB_VEF_CONNECT_PROFILE,
        'infrabb_vef_control_connection_profile':backup.FULL_INFRABB_VEF_CONTROL_CONNECTION_PROFILE,
        'vef_pinmem_input_connection_profile':PROFILE}
    valid={**host_environment(tmp_path),'A7C2_DIRECTORY_SD_PROFILE':'directory-vvfat-256gb-v1',
           'MENU_PIN_REGISTRY':'1','MENU_PIN_CONTROL_MEMORY':'1','MENU_PIN_CONNECTION':'cold'}
    def run(env,**changes):
        with mock.patch.dict(os.environ,env,clear=True):exec(code,{**scope,**changes})
    run(valid)
    run({},bb_set_mode_profile='',imaging_pin_connection_profile='',imaging_control_connection_profile='',
        imaging_adf_connection_profile='',infrabb_vef_connection_profile='',
        infrabb_vef_control_connection_profile='',vef_pinmem_input_connection_profile='')
    run({name:value for name,value in valid.items() if name!=HOST},vef_pinmem_input_connection_profile='')
    for name in ('infrabb_vef_control_connection_profile','infrabb_vef_connection_profile',
                 'imaging_adf_connection_profile','imaging_control_connection_profile',
                 'imaging_pin_connection_profile','bb_set_mode_profile','backup_sync','cp_background',
                 'udate_distribution','touch_panel','tcin_detect','dfs_selector','vef_path_profile',
                 'adf_proc_path_profile','adf_set_input_profile','adf_set_output_profile'):
        with pytest.raises(SystemExit):run(valid,**{name:''})
    for name in (HOST,'A7C2_INFRABB_VEF_CONTROL_CONNECT','A7C2_INFRABB_VEF_CONNECT',
                 'A7C2_IMAGING_ADF_CONNECT','A7C2_IMAGING_CONTROL_CONNECT','A7C2_IMAGING_CONNECT',
                 'A7C2_BB_SET_MODE','A7C2_DIRECTORY_SD_PROFILE','SEED_BACKUP',
                 'MENU_PIN_REGISTRY','MENU_PIN_CONTROL_MEMORY','MENU_PIN_CONNECTION'):
        bad=dict(valid);bad.pop(name)
        with pytest.raises(SystemExit):run(bad)
        with pytest.raises(SystemExit):run({**valid,name:'unknown'})
    with pytest.raises(SystemExit):run(valid,vef_pinmem_input_connection_profile='unknown')
    for name in backup.BB_MODE_CONFLICTS:
        with pytest.raises(SystemExit):run({**valid,name:'1'})


def test_prepare_rejects_invalid_sixth_before_candidate_or_files(tmp_path,monkeypatch):
    launcher=load_script('pinmem_input_prepare_menu','start-menu.py')
    env=launcher.profile_environment(host_environment(tmp_path),natural_boot=True)
    env.update(SEED_BACKUP='alllang',A7C2_DIRECTORY_SD_PROFILE='directory-vvfat-256gb-v1')
    def no_build(*args):raise AssertionError('invalid sixth profile reached candidate/filesystem work')
    monkeypatch.setattr(backup,'validate_build',no_build)
    for name,value in [(GUEST,'unknown'),(HOST,''),(HOST,'unknown'),('MENU_INFRABB_VEF_CONTROL_CONNECT',''),
                       ('A7C2_INFRABB_VEF_CONTROL_CONNECT',''),('MENU_INFRABB_VEF_CONNECT',''),
                       ('MENU_IMAGING_ADF_CONNECT',''),('MENU_IMAGING_CONTROL_CONNECT',''),
                       ('MENU_IMAGING_CONNECT',''),('MENU_BB_SET_MODE',''),('MENU_ADF_SET_OUTPUT',''),
                       ('MENU_PIN_REGISTRY',''),('MENU_PIN_CONTROL_MEMORY',''),('MENU_PIN_CONNECTION',''),
                       ('SEED_BACKUP',''),('SEED_BACKUP','private'),('A7C2_DIRECTORY_SD_PROFILE',''),
                       *[(key,'1') for key in backup.BB_MODE_CONFLICTS]]:
        with pytest.raises(ValueError):backup.prepare_profile(HERE,{**env,name:value})
    bad=dict(env);bad.pop('SEED_BACKUP')
    with pytest.raises(ValueError):backup.prepare_profile(HERE,bad)


@pytest.mark.parametrize('enabled',[False,True])
def test_receipt_manifest_exports_and_typed_validator_preserve_five_profiles(tmp_path,enabled):
    build=build_fixture(tmp_path)[0];env=host_environment(tmp_path,build)
    if not enabled:env.pop(HOST)
    launcher=load_script('pinmem_input_receipt_menu','start-menu.py')
    host=launcher.profile_environment(env,natural_boot=True)
    with directory_lease(Path(env['A7C2_DIRECTORY_SD'])) as lease:
        host.update(directory_profile(HERE,lease,tmp_path/'directory-profile'))
        host.update(backup.prepare_profile(HERE,host))
    fields=backup.vef_pinmem_input_connection_profile_fields(PROFILE if enabled else '')
    receipt=json.loads(Path(host['MENU_BACKUP_PROFILE_RECEIPT']).read_text())
    for expected in (fields,
            backup.infrabb_vef_control_connection_profile_fields(backup.FULL_INFRABB_VEF_CONTROL_CONNECTION_PROFILE),
            backup.infrabb_vef_connection_profile_fields(backup.INFRABB_VEF_CONNECT_PROFILE),
            backup.imaging_adf_connection_profile_fields(backup.IMAGING_ADF_CONNECT_PROFILE),
            backup.imaging_control_connection_profile_fields(backup.IMAGING_CONTROL_CONNECT_PROFILE),
            backup.imaging_pin_connection_profile_fields(backup.IMAGING_CONNECT_PROFILE)):
        assert all(name in receipt and type(receipt[name]) is type(value) and
                   json.dumps(receipt[name])==json.dumps(value) for name,value in expected.items())
    setup=menu_probe_setup(host);guest=clean_guest_environment(setup)
    assert guest.get(GUEST)==(PROFILE if enabled else None)
    assert guest['MENU_INFRABB_VEF_CONTROL_CONNECT']==backup.FULL_INFRABB_VEF_CONTROL_CONNECTION_PROFILE
    assert HOST not in guest
    assert sum(line.startswith('export '+GUEST+'=') for line in setup)==int(enabled)
    if enabled:
        for name in (HOST,GUEST,'MENU_INFRABB_VEF_CONTROL_CONNECT','A7C2_INFRABB_VEF_CONTROL_CONNECT',
                     'MENU_INFRABB_VEF_CONNECT','A7C2_INFRABB_VEF_CONNECT','MENU_IMAGING_ADF_CONNECT',
                     'A7C2_IMAGING_ADF_CONNECT','MENU_IMAGING_CONTROL_CONNECT','A7C2_IMAGING_CONTROL_CONNECT',
                     'MENU_IMAGING_CONNECT','A7C2_IMAGING_CONNECT','MENU_BB_SET_MODE'):
            assert GUEST not in clean_guest_environment(menu_probe_setup({**host,name:''}))
    tree=ast.parse((HERE/'qemu-menu-probe.py').read_text())
    manifest=next(node.value for node in tree.body if isinstance(node,ast.Assign) and
                  isinstance(node.targets[0],ast.Name) and node.targets[0].id=='manifest')
    spread=next(value for key,value in zip(manifest.keys,manifest.values) if key is None and
                isinstance(value,ast.Call) and isinstance(value.func,ast.Name) and
                value.func.id=='vef_pinmem_input_connection_profile_fields')
    scope={'vef_pinmem_input_connection_profile':PROFILE if enabled else '',
           'vef_pinmem_input_connection_profile_fields':backup.vef_pinmem_input_connection_profile_fields}
    assert eval(compile(ast.Expression(spread),'<sixth-manifest>','eval'),scope)==fields
    validator=next(node for node in tree.body if isinstance(node,ast.If) and
        isinstance(node.test,ast.Name) and node.test.id=='backup_sync' and any(
            isinstance(call,ast.Call) and isinstance(call.func,ast.Name) and call.func.id=='validate_build'
            for call in ast.walk(node)))
    code=compile(ast.Module(body=[validator],type_ignores=[]),'<real-sixth-receipt-validator>','exec')
    scope.update(os=os,json=json,Path=Path,base=HERE,sha256_file=backup.sha,
        backup_sync=backup.PROFILE,env=host,kernel_script=Path(host['MENU_KERNEL_SCRIPT']),
        board_dtb=Path(host['MENU_DTB']),adf_proc_path_profile=backup.ADF_PROFILE,
        adf_set_input_profile=backup.INPUT_PROFILE,adf_set_output_profile=backup.OUTPUT_PROFILE,
        bb_set_mode_profile=backup.BB_SET_MODE_PROFILE,imaging_pin_connection_profile=backup.IMAGING_CONNECT_PROFILE,
        imaging_control_connection_profile=backup.IMAGING_CONTROL_CONNECT_PROFILE,
        imaging_adf_connection_profile=backup.IMAGING_ADF_CONNECT_PROFILE,
        infrabb_vef_connection_profile=backup.INFRABB_VEF_CONNECT_PROFILE,
        infrabb_vef_control_connection_profile=backup.FULL_INFRABB_VEF_CONTROL_CONNECTION_PROFILE,
        vef_pinmem_control_connection_profile='',pinmem_peer_connections_profile='',
        adf_hdmi_audio_connection_profile='',
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
            for name,indices in (('source_pin',[0]),('peer_pin',[0]),('source_state_path',[2]),
                                 ('dmm_operations',[0]),('references_owner_open',[8,0]),
                                 ('format_notice_edges',[0,0,0]),('imaging_config_after',[0])):
                for replacement in (0.0,False):
                    bad=copy.deepcopy(receipt);target=bad[PREFIX+name]
                    for index in indices[:-1]:target=target[index]
                    target[indices[-1]]=replacement;path.write_text(json.dumps(bad))
                    with pytest.raises(ValueError,match='identity/admission mismatch'):exec(code,scope)
        path.write_text(json.dumps(receipt));exec(code,scope)


def test_gtk_rejects_unsafe_sixth_flow_before_xvfb(tmp_path):
    driver=load_script('pinmem_input_gtk_driver','check-natural-gtk-input.py')
    build=make_candidate(tmp_path);card=tmp_path/'card';card.mkdir()
    env=host_environment(tmp_path,build)
    safe=['check-natural-gtk-input.py','--new-ui','--firstboot','--simplified-chinese',
          '--natural-shutter','--export-sd','--host-sd-dir',str(card),'--candidate-build',str(build)]
    cases=[([item for item in safe if item!=flag],env) for flag in (
        '--new-ui','--firstboot','--simplified-chinese','--natural-shutter','--export-sd','--candidate-build')]
    cases.extend((safe,{name:value for name,value in env.items() if name!=missing})
                 for missing in PREDECESSORS if missing!='A7C2_DIRECTORY_SD')
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


def test_actual_exports_execute_entire_c_constructor_and_all_owner_failures(tmp_path,bb_constructor):
    launcher=load_script('pinmem_input_ctor_menu','start-menu.py')
    host=launcher.profile_environment(host_environment(tmp_path),natural_boot=True)
    host.update(MENU_BACKUP_SYNC=backup.PROFILE,SEED_BACKUP='alllang',
                A7C2_DIRECTORY_SD_PROFILE='directory-vvfat-256gb-v1')
    guest=clean_guest_environment(menu_probe_setup(host))
    assert guest[GUEST]==PROFILE and HOST not in guest and 'MENU_OBSERVE_SELFTEST' not in guest
    log=bb_constructor(guest)
    assert ('imaging=1 imaging_init=1 control=1 control_init=1 adf=1 adf_init=1 vef=1 vef_init=1 '
            'vef_control=1 vef_control_init=1 pinmem_input=1 pinmem_input_init=1') in log
    assert 'FULL_VEF_PINMEM_INPUT_CONNECT_PROFILE requested='+PROFILE+' enabled=1 first_missing=none ' in log
    assert 'initialized=1 unadmitted_count=0 record_bound=1 before_any_input=1 connection_verified=0 capture_verified=0' in log
    for name in ('MENU_INFRABB_VEF_CONTROL_CONNECT','MENU_INFRABB_VEF_CONNECT','MENU_IMAGING_ADF_CONNECT',
                 'MENU_IMAGING_CONTROL_CONNECT','MENU_IMAGING_CONNECT','MENU_BB_SET_MODE','MENU_ADF_SET_OUTPUT',
                 'MENU_BACKUP_SYNC','MENU_CP_BACKGROUND','MENU_UDATE_DISTRIBUTION','MENU_TOUCH_PANEL',
                 'MENU_TCIN_DETECT','MENU_DFS_SELECTOR','MENU_AUDIO_BOOT_CONFIG','MENU_PIN_REGISTRY',
                 'MENU_PIN_CONTROL_MEMORY','MENU_PIN_CONNECTION'):
        for value in (None,'unknown'):
            bad=dict(guest)
            if value is None:bad.pop(name)
            else:bad[name]=value
            assert ' pinmem_input=0 pinmem_input_init=0' in bb_constructor(bad)
    for change in ({GUEST:'unknown'},{GUEST:''},{'MENU_OBSERVE_SELFTEST':'1'}):
        assert ' pinmem_input=0 pinmem_input_init=0' in bb_constructor({**guest,**change})
    for options in ({'input_enabled':False},{'owner_rc':-1021},{'imaging_owner_rc':-1021},
                    {'control_owner_rc':-1021},{'adf_owner_rc':-1021},{'vef_owner_rc':-1021},
                    {'vef_control_owner_rc':-1021}):
        assert ' pinmem_input=0 pinmem_input_init=0' in bb_constructor(guest,**options)
    failure=bb_constructor(guest,pinmem_input_owner_rc=-1021)
    assert ' vef_control=1 vef_control_init=1 pinmem_input=0 pinmem_input_init=1' in failure
    assert ('FULL_VEF_PINMEM_INPUT_CONNECT_PROFILE requested='+PROFILE+' enabled=0 first_missing=owner-init ') in failure
    assert 'initialized=0 unadmitted_count=0 record_bound=0 ' in failure
    host.pop(HOST);host.pop(GUEST)
    default_guest=clean_guest_environment(menu_probe_setup(host))
    assert GUEST not in default_guest
    default_log=bb_constructor(default_guest)
    assert ' vef_control=1 vef_control_init=1 pinmem_input=0 pinmem_input_init=0' in default_log
    assert 'FULL_VEF_PINMEM_INPUT_CONNECT_PROFILE ' not in default_log


def test_gtk_typed_sixth_admission_checks_both_receipts_and_nested_zero_types():
    tree=ast.parse((HERE/'check-natural-gtk-input.py').read_text())
    admission=next(node for node in ast.walk(tree) if isinstance(node,ast.If) and
        isinstance(node.test,ast.Name) and node.test.id=='requested_vef_pinmem_input_connect' and
        isinstance(node.body[0],ast.Assign) and isinstance(node.body[0].targets[0],ast.Name) and
        node.body[0].targets[0].id=='expected_vef_pinmem_input')
    code=compile(ast.Module(body=[admission],type_ignores=[]),'<sixth-runtime-admission>','exec')
    fields=backup.vef_pinmem_input_connection_profile_fields(PROFILE)
    actual={**fields,'backup_transport':copy.deepcopy(fields),'selected_observer_matches_build':True}
    scope={'requested_vef_pinmem_input_connect':'','actual':actual,'proof':{},'json':json,
           'vef_pinmem_input_connection_profile_fields':backup.vef_pinmem_input_connection_profile_fields}
    exec(code,scope);assert not scope['proof']
    scope['requested_vef_pinmem_input_connect']=PROFILE
    exec(code,scope);assert scope['proof']['vef_pinmem_input_connection_admission']==fields
    for section in ('top','transport'):
        for name,value in fields.items():
            bad=copy.deepcopy(actual);target=bad if section=='top' else bad['backup_transport'];target.pop(name)
            scope.update(actual=bad,proof={})
            with pytest.raises(RuntimeError):exec(code,scope)
            target[name]=(int(not value) if type(value) is bool else float(value) if type(value) is int else
                          tuple(value) if isinstance(value,list) else 'wrong')
            with pytest.raises(RuntimeError):exec(code,scope)
        for name,indices in (('source_pin',[0]),('peer_pin',[0]),('source_state_path',[2]),
                             ('references_owner_open',[8,0]),('format_notice_edges',[0,0,0])):
            for replacement in (0.0,False):
                bad=copy.deepcopy(actual);target=bad if section=='top' else bad['backup_transport']
                value=target[PREFIX+name]
                for index in indices[:-1]:value=value[index]
                value[indices[-1]]=replacement;scope.update(actual=bad,proof={})
                with pytest.raises(RuntimeError):exec(code,scope)
    scope.update(actual={**actual,'selected_observer_matches_build':False},proof={})
    with pytest.raises(RuntimeError):exec(code,scope)
