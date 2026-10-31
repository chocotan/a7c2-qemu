"""Default-off, bounded BB set_mode host-to-guest admission contract."""
import argparse
import ast
import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import struct
import subprocess
from types import SimpleNamespace
from unittest import mock

import pytest

import backup_profile as backup
from language_fonts import FONT_GUEST, FONT_SPECS
from test_backup_profile import (HERE, adf_host_environment, build_fixture,
                                 directory_lease, directory_profile)

PROFILE=backup.BB_SET_MODE_PROFILE


def host_environment(tmp_path, build=None):
    return {**adf_host_environment(tmp_path),
            'A7C2_ADF_SET_INPUT':backup.INPUT_PROFILE,
            'A7C2_ADF_SET_OUTPUT':backup.OUTPUT_PROFILE,
            'A7C2_BB_SET_MODE':PROFILE,
            'A7C2_BACKUP_BUILD':str(build or tmp_path/'candidate'),
            'A7C2_DIRECTORY_SD':str(tmp_path/'card'),
            'SEED_BACKUP':'alllang'}


def load_script(name, filename):
    spec=importlib.util.spec_from_file_location(name,HERE/filename)
    module=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def menu_probe_setup(host):
    source=(HERE/'qemu-menu-probe.py').read_text()
    tree=ast.parse(source)
    parser_start=next(i for i,node in enumerate(tree.body) if isinstance(node,ast.Assign) and
                      isinstance(node.targets[0],ast.Name) and node.targets[0].id=='parser')
    args_index=next(i for i,node in enumerate(tree.body) if isinstance(node,ast.Assign) and
                    isinstance(node.targets[0],ast.Name) and node.targets[0].id=='args')
    base_index=next(i for i,node in enumerate(tree.body) if isinstance(node,ast.Assign) and
                    isinstance(node.targets[0],ast.Name) and node.targets[0].id=='base')
    globals_code=ast.Module(body=tree.body[parser_start:args_index]+[
        node for node in tree.body[args_index+1:base_index] if isinstance(node,ast.Assign)],
        type_ignores=[])
    setup_body=next(node.body for node in ast.walk(tree) if isinstance(node,ast.With) and any(
        isinstance(item,ast.Assign) and isinstance(item.targets[0],ast.Name) and
        item.targets[0].id=='setup' for item in node.body))
    start=next(i for i,node in enumerate(setup_body) if isinstance(node,ast.Assign) and
               isinstance(node.targets[0],ast.Name) and node.targets[0].id=='setup')
    end=next(i for i,node in enumerate(setup_body) if isinstance(node,ast.Expr) and
             isinstance(node.value,ast.Call) and isinstance(node.value.func,ast.Attribute) and
             ast.unparse(node.value.func)=='proc.stdin.write')
    scope={'argparse':argparse,'__doc__':'BB guest setup export regression','os':os,'Path':Path,
           '__file__':str(HERE/'qemu-menu-probe.py'),'manifest':{'qemu_cpu_count':1},
           'live_fd':False,'host_sd_fd':None,'directory_sd_fd':40,'sd_seed':None,
           'FONT_GUEST':FONT_GUEST,'FONT_SPECS':FONT_SPECS,
           'ADF_PROFILE':backup.ADF_PROFILE,'INPUT_PROFILE':backup.INPUT_PROFILE,
           'OUTPUT_PROFILE':backup.OUTPUT_PROFILE,'BB_SET_MODE_PROFILE':PROFILE,
           'IMAGING_CONNECT_PROFILE':backup.IMAGING_CONNECT_PROFILE,
           'IMAGING_CONTROL_CONNECT_PROFILE':backup.IMAGING_CONTROL_CONNECT_PROFILE,
           'IMAGING_ADF_CONNECT_PROFILE':backup.IMAGING_ADF_CONNECT_PROFILE,
           'INFRABB_VEF_CONNECT_PROFILE':backup.INFRABB_VEF_CONNECT_PROFILE,
           'FULL_INFRABB_VEF_CONTROL_CONNECTION_PROFILE':backup.FULL_INFRABB_VEF_CONTROL_CONNECTION_PROFILE,
           'FULL_VEF_PINMEM_INPUT_CONNECTION_PROFILE':backup.FULL_VEF_PINMEM_INPUT_CONNECTION_PROFILE,
           'FULL_VEF_PINMEM_CONTROL_CONNECTION_PROFILE':backup.FULL_VEF_PINMEM_CONTROL_CONNECTION_PROFILE,
           'FULL_PINMEM_PEER_CONNECTIONS_PROFILE':backup.FULL_PINMEM_PEER_CONNECTIONS_PROFILE,
           'FULL_ADF_HDMI_AUDIO_CONNECTION_PROFILE':backup.FULL_ADF_HDMI_AUDIO_CONNECTION_PROFILE,
           'FULL_PINMEM_HDMI_VIDEO_CONNECTION_PROFILE':backup.FULL_PINMEM_HDMI_VIDEO_CONNECTION_PROFILE,
           'FULL_PINMEM_OSD_CONNECTION_PROFILE':backup.FULL_PINMEM_OSD_CONNECTION_PROFILE,
           'FULL_CP302C_NO_TRANSITION_PROFILE':backup.FULL_CP302C_NO_TRANSITION_PROFILE,
           'FULL_CP_OWNED_STATE_PROFILE':backup.FULL_CP_OWNED_STATE_PROFILE,
           'FUNCTIONAL_CAMERA_PROFILE':backup.FUNCTIONAL_CAMERA_PROFILE,
           'ADF_CONFLICTS':backup.ADF_CONFLICTS,'BB_MODE_CONFLICTS':backup.BB_MODE_CONFLICTS,
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
           'cp302c_no_transition_profile_fields':backup.cp302c_no_transition_profile_fields}
    with mock.patch.dict(os.environ,host,clear=True):
        exec(compile(globals_code,'<qemu-setup-globals>','exec'),scope)
        scope['args']=scope['parser'].parse_args([
            '--initramfs','--observe','--sony-timers','--load-ipc','--seed-backup',
            '--load-dmm','--dmm-service','--software-gpe','--headless-osd',
            '--native-display','none','--bootin'])
        scope['directory_sd_fd']=40
        exec(compile(ast.Module(body=setup_body[start:end],type_ignores=[]),
                     '<complete-profile-guest-setup>','exec'),scope)
    return scope['setup']


def clean_guest_environment(setup):
    exports=[line for line in setup if line.startswith('export ')]
    assert exports
    assert all(re.fullmatch(
        r'export [A-Za-z_][A-Za-z0-9_]*=[A-Za-z0-9_./:,=-]*',line) for line in exports)
    result=subprocess.run(['/bin/sh','-eu','-c','\n'.join([*exports,'/usr/bin/env -0'])],
                          env={},check=True,capture_output=True,timeout=5)
    return dict(item.decode().split('=',1) for item in result.stdout.split(b'\0') if item)


def make_candidate(directory):
    build=directory/'candidate'
    binary=build/'build/qemu-system-aarch64'
    binary.parent.mkdir(parents=True)
    binary.write_bytes(b'BB profile candidate identity fixture; never executed')
    (build/'pci-hardware-build.json').write_text(json.dumps({
        'scope':'default-off PCI/ATU hardware in native GTK/USB/directory-SD build',
        'binary_sha256':hashlib.sha256(binary.read_bytes()).hexdigest()}))
    return build


def test_profile_fields_pin_request_virtual_policy_work_and_false_claims():
    fields=backup.bb_set_mode_profile_fields(PROFILE)
    assert fields['bb_set_mode_profile']==PROFILE
    assert fields['bb_set_mode_request_bytes']==10
    raw=bytes.fromhex(fields['bb_set_mode_request_hex'])
    assert raw==bytes.fromhex('0d2010010a0001800000') and len(raw)==10
    assert fields['bb_set_mode_ap_input_u32']==[2,0]
    assert fields['bb_set_mode_operation_mode']==0
    assert fields['bb_set_mode_initial_state_bytes']==(
        '0100000000000000000000000000000000000000000000000100000000000000')
    initial=bytes.fromhex(fields['bb_set_mode_initial_state_bytes'])
    assert len(initial)==32 and list(struct.unpack('<8I',initial))==[1,0,0,0,0,0,1,0]
    assert fields['bb_set_mode_state_source']=='virtual public CP image initializer'
    assert fields['bb_set_mode_state_word0']==fields['bb_set_mode_state_word6']==1
    assert fields['bb_set_mode_state_policy']=='virtual-public-cp-image-initializer-prefix-audit-v1'
    assert fields['bb_set_mode_target_selection_policy']=='state-word-1-operation-mode-0-first-generation-only'
    assert fields['bb_set_mode_target']==3
    assert fields['bb_set_mode_config_copy_bytes']==1760
    assert fields['bb_set_mode_config_initial_known_bytes']==1565
    assert fields['bb_set_mode_config_initial_unknown_bytes']==195
    assert fields['bb_set_mode_config_postprefix_known_bytes']==4
    assert fields['bb_set_mode_config_postprefix_unknown_bytes']==1756
    assert fields['bb_set_mode_work_queues']==['queue3','queue4']
    assert fields['bb_set_mode_outer_consumer_task']==30
    assert fields['bb_set_mode_inner_consumer_task']==31
    assert fields['bb_set_mode_internal_completion_events']==[0x21a,0x21a]
    assert fields['bb_set_mode_unique_1110_reply_count']==1
    assert fields['bb_set_mode_tasklocal_consumer_policy']=='virtual-tasklocal-generation1-only-v1'
    for name in ('state_is_original_cp_live_state','original_cp_executed','live_cp_ram_read',
                 'hardware_verified','hardware_mode_change_verified','native_mode_change_verified',
                 'original_task_scheduler_verified','ap_consumed','frames_verified','capture_verified'):
        assert fields['bb_set_mode_'+name] is False
    off=backup.bb_set_mode_profile_fields('')
    assert all(value is None for name,value in off.items() if name not in {
        'bb_set_mode_state_is_original_cp_live_state','bb_set_mode_original_cp_executed',
        'bb_set_mode_live_cp_ram_read','bb_set_mode_hardware_verified',
        'bb_set_mode_hardware_mode_change_verified','bb_set_mode_native_mode_change_verified',
        'bb_set_mode_original_task_scheduler_verified','bb_set_mode_ap_consumed',
        'bb_set_mode_frames_verified','bb_set_mode_capture_verified'})
    assert all(value is False for name,value in off.items() if name.endswith((
        'state_is_original_cp_live_state','original_cp_executed','live_cp_ram_read',
        'hardware_verified','hardware_mode_change_verified','native_mode_change_verified',
        'original_task_scheduler_verified','ap_consumed','frames_verified','capture_verified')))
    with pytest.raises(ValueError):backup.bb_set_mode_profile_fields('unknown')


def test_host_launcher_default_off_exact_forwarding_and_prerequisite_rejection(tmp_path):
    launcher=load_script('bb_start_menu', 'start-menu.py')
    assert 'MENU_BB_SET_MODE' not in launcher.profile_environment({},natural_boot=True)
    env=host_environment(tmp_path)
    selected=launcher.profile_environment(env,natural_boot=True)
    assert selected['MENU_BB_SET_MODE']==PROFILE
    assert selected['MENU_ADF_SET_OUTPUT']==backup.OUTPUT_PROFILE
    assert selected['MENU_ADF_SET_INPUT']==backup.INPUT_PROFILE
    assert selected['MENU_ADF_PROC_PATH']==backup.ADF_PROFILE
    for name in backup.BB_MODE_CONFLICTS:
        assert not selected.get(name)
    with pytest.raises(ValueError):launcher.profile_environment(env,natural_boot=False)
    with pytest.raises(ValueError):launcher.profile_environment({**env,'A7C2_BB_SET_MODE':'unknown'},natural_boot=True)
    for name in ('A7C2_BACKUP_SYNC','A7C2_BACKUP_BUILD','A7C2_DIRECTORY_SD',
                 'A7C2_CP_BACKGROUND','A7C2_UDATE_DISTRIBUTION','A7C2_TOUCH_PANEL',
                 'A7C2_TCIN_DETECT','A7C2_DFS_SELECTOR','A7C2_VEF_PATH',
                 'A7C2_ADF_PROC_PATH','A7C2_ADF_SET_INPUT','A7C2_ADF_SET_OUTPUT'):
        bad=dict(env);bad.pop(name)
        with pytest.raises(ValueError):
            launcher.profile_environment(bad,natural_boot=True)
    for name,value in [('SEED_BACKUP','private'),('SEED_BACKUP','full'),
                       *[(key,'1') for key in backup.BB_MODE_CONFLICTS]]:
        with pytest.raises(ValueError):
            launcher.profile_environment({**env,name:value},natural_boot=True)


def qemu_bb_guard():
    tree=ast.parse((HERE/'qemu-menu-probe.py').read_text())
    return next(node for node in tree.body if isinstance(node,ast.If) and any(
        isinstance(call,ast.Call) and isinstance(call.func,ast.Attribute) and
        ast.unparse(call.func)=='parser.error' and call.args and isinstance(call.args[0],ast.Constant) and
        str(call.args[0].value).startswith('BB set mode requires') for call in ast.walk(node)))


def guard_scope(profile=PROFILE):
    return {'parser':argparse.ArgumentParser(), 'os':os,
            'bb_set_mode_profile':profile,'BB_SET_MODE_PROFILE':PROFILE,
            'BB_MODE_CONFLICTS':backup.BB_MODE_CONFLICTS,
            'ADF_PROFILE':backup.ADF_PROFILE,'INPUT_PROFILE':backup.INPUT_PROFILE,
            'OUTPUT_PROFILE':backup.OUTPUT_PROFILE,
            'backup_sync':'virtual-primary-v1','cp_background':'virtual-mode3-cold-v1',
            'udate_distribution':'virtual-roundtrip-v1','touch_panel':'virtual-config-v1',
            'tcin_detect':'virtual-inactive-v1','dfs_selector':'virtual-selector-v1',
            'vef_path_profile':'virtual-nomem-v1','adf_proc_path_profile':backup.ADF_PROFILE,
            'adf_set_input_profile':backup.INPUT_PROFILE,'adf_set_output_profile':backup.OUTPUT_PROFILE,
            'args':SimpleNamespace(initramfs=True,observe=True,load_ipc=True,seed_backup=True,
                load_dmm=True,dmm_service=True,sony_timers=True,native_display='none')}


def run_guard(scope, env):
    with mock.patch.dict(os.environ,env,clear=True):
        exec(compile(ast.Module(body=[qemu_bb_guard()],type_ignores=[]),'<qemu-bb-prevm-guard>','exec'),scope)


def test_qemu_guard_is_default_off_and_rejects_missing_chain_and_conflicts(monkeypatch):
    guard=qemu_bb_guard()
    scope=guard_scope('')
    run_guard(scope,{})
    assert guard is not None
    with pytest.raises(SystemExit):run_guard(guard_scope('unsupported'),{})
    valid={'A7C2_BB_SET_MODE':PROFILE,'SEED_BACKUP':'alllang',
           'A7C2_DIRECTORY_SD_PROFILE':'directory-vvfat-256gb-v1','MENU_USB_NET':'1'}
    run_guard(guard_scope(),valid)
    for name in ('backup_sync','cp_background','udate_distribution','touch_panel','tcin_detect',
                 'dfs_selector','vef_path_profile','adf_proc_path_profile','adf_set_input_profile',
                 'adf_set_output_profile'):
        bad=guard_scope();bad[name]=''
        with pytest.raises(SystemExit):run_guard(bad,valid)
    for name in ('initramfs','observe','load_ipc','seed_backup','load_dmm','dmm_service','sony_timers'):
        bad=guard_scope();setattr(bad['args'],name,False)
        with pytest.raises(SystemExit):run_guard(bad,valid)
    bad=guard_scope();bad['args'].native_display=None
    with pytest.raises(SystemExit):run_guard(bad,valid)
    for name in ('A7C2_BB_SET_MODE','SEED_BACKUP','A7C2_DIRECTORY_SD_PROFILE'):
        bad=dict(valid);bad.pop(name)
        with pytest.raises(SystemExit):run_guard(guard_scope(),bad)
    for key in backup.BB_MODE_CONFLICTS:
        with pytest.raises(SystemExit):run_guard(guard_scope(),{**valid,key:'1'})


def test_public_backup_receipt_and_complete_clean_guest_exports(tmp_path):
    build=build_fixture(tmp_path)[0]
    env=host_environment(tmp_path,build)
    launcher=load_script('bb_receipt_start_menu','start-menu.py')
    host=launcher.profile_environment(env,natural_boot=True)
    card=Path(env['A7C2_DIRECTORY_SD'])
    with directory_lease(card) as lease:
        host.update(directory_profile(HERE,lease,tmp_path/'directory-profile'))
        host.update(backup.prepare_profile(HERE,host))
    receipt=json.loads(Path(host['MENU_BACKUP_PROFILE_RECEIPT']).read_text())
    expected=backup.bb_set_mode_profile_fields(PROFILE)
    assert all(type(receipt[name]) is type(value) and receipt[name]==value
               for name,value in expected.items())
    exports=clean_guest_environment(menu_probe_setup(host))
    assert exports['MENU_BB_SET_MODE']==PROFILE
    for key,value in {
        'MENU_BACKUP_SYNC':backup.PROFILE,'MENU_CP_BACKGROUND':'virtual-mode3-cold-v1',
        'MENU_UDATE_DISTRIBUTION':'virtual-roundtrip-v1','MENU_TOUCH_PANEL':'virtual-config-v1',
        'MENU_TCIN_DETECT':'virtual-inactive-v1','MENU_DFS_SELECTOR':'virtual-selector-v1',
        'MENU_VEF_PATH':'virtual-nomem-v1','MENU_ADF_PROC_PATH':backup.ADF_PROFILE,
        'MENU_ADF_SET_INPUT':backup.INPUT_PROFILE,'MENU_ADF_SET_OUTPUT':backup.OUTPUT_PROFILE,
    }.items():
        assert exports[key]==value
    source=(HERE/'qemu-menu-probe.py').read_text()
    assert '**bb_set_mode_profile_fields(bb_set_mode_profile)' in source
    assert 'bb_set_mode_profile_fields(bb_set_mode_profile).items()' in source
    assert "setup += ['export MENU_BB_SET_MODE=virtual-bb-still-target3-op0-v1']" in source


def test_gtk_admission_requires_same_candidate_directory_firstboot_export_and_chain(tmp_path,monkeypatch):
    driver=load_script('bb_gtk_driver','check-natural-gtk-input.py')
    build=make_candidate(tmp_path)
    card=tmp_path/'card';card.mkdir()
    env=host_environment(tmp_path,build)
    env['A7C2_DIRECTORY_SD']=str(card)
    safe=['check-natural-gtk-input.py','--new-ui','--firstboot','--export-sd',
          '--host-sd-dir',str(card),'--candidate-build',str(build)]
    bad_cases=[([v for v in safe if v!='--new-ui'],env),
               ([v for v in safe if v!='--firstboot'],env),
               ([v for v in safe if v!='--export-sd'],env),
               ([v for v in safe if v!='--candidate-build'],env),
               (safe,{**env,'A7C2_DIRECTORY_SD':str(tmp_path/'other')}),
               (safe,{**env,'A7C2_BACKUP_BUILD':str(tmp_path/'other-build')}),
               (safe,{**env,'SEED_BACKUP':'private'}),
               (safe,{**env,'MENU_YC_INJECT':'1'}),
               (safe,{**env,'A7C2_BB_SET_MODE':'unsupported'})]
    for argv,values in bad_cases:
        with mock.patch.object(driver.sys,'argv',argv),mock.patch.dict(driver.os.environ,values,clear=True), \
             mock.patch.object(driver.subprocess,'Popen',side_effect=AssertionError('must reject before Xvfb')):
            with pytest.raises(ValueError):driver.main()


def test_gtk_actual_runtime_manifest_requires_typed_values_in_both_receipts():
    tree=ast.parse((HERE/'check-natural-gtk-input.py').read_text())
    main=next(node for node in tree.body if isinstance(node,ast.FunctionDef) and node.name=='main')
    admission=next(node for node in ast.walk(main) if isinstance(node,ast.If) and
        isinstance(node.test,ast.Name) and node.test.id=='requested_bb_set_mode' and
        isinstance(node.body[0],ast.Assign) and isinstance(node.body[0].targets[0],ast.Name) and
        node.body[0].targets[0].id=='expected_bb')
    fields=backup.bb_set_mode_profile_fields(PROFILE)
    code=compile(ast.Module(body=[admission],type_ignores=[]),'<bb-actual-runtime-admission>','exec')
    actual={**fields,'backup_transport':dict(fields),'selected_observer_matches_build':True}
    scope={'requested_bb_set_mode':'','actual':actual,'proof':{},'json':json,
           'bb_set_mode_profile_fields':backup.bb_set_mode_profile_fields}
    exec(code,scope)
    assert not scope['proof']
    scope['requested_bb_set_mode']=PROFILE
    exec(code,scope)
    assert scope['proof']['bb_set_mode_admission']==fields
    for section in ('top','transport'):
        for name,value in fields.items():
            changed=copy.deepcopy(actual)
            target=changed if section=='top' else changed['backup_transport']
            target.pop(name)
            scope.update(actual=changed,proof={})
            with pytest.raises(RuntimeError):exec(code,scope)
            target[name]=(0 if value is True else 1 if value is False else
                          float(value) if type(value) is int else tuple(value) if isinstance(value,list) else 'wrong')
            scope.update(proof={})
            with pytest.raises(RuntimeError):exec(code,scope)
    for section in ('top','transport'):
        for name in ('bb_set_mode_ap_input_u32','bb_set_mode_internal_completion_events'):
            changed=copy.deepcopy(actual)
            target=changed if section=='top' else changed['backup_transport']
            target[name][0]=float(target[name][0])
            scope.update(actual=changed,proof={})
            with pytest.raises(RuntimeError):exec(code,scope)
    scope.update(actual={**actual,'selected_observer_matches_build':False},proof={})
    with pytest.raises(RuntimeError):exec(code,scope)


def test_bb_default_off_receipt_is_part_of_existing_backup_profile(tmp_path):
    build=build_fixture(tmp_path)[0]
    env=host_environment(tmp_path,build)
    env.pop('A7C2_BB_SET_MODE')
    env['MENU_BB_SET_MODE']=''
    launcher=load_script('bb_default_start_menu','start-menu.py')
    host=launcher.profile_environment(env,natural_boot=True)
    with directory_lease(Path(env['A7C2_DIRECTORY_SD'])) as lease:
        host.update(directory_profile(HERE,lease,tmp_path/'default-directory-profile'))
        host.update(backup.prepare_profile(HERE,host))
    receipt=json.loads(Path(host['MENU_BACKUP_PROFILE_RECEIPT']).read_text())
    fields=backup.bb_set_mode_profile_fields('')
    assert all(type(receipt[name]) is type(value) and receipt[name]==value
               for name,value in fields.items())
    exports=clean_guest_environment(menu_probe_setup(host))
    assert 'MENU_BB_SET_MODE' not in exports


def test_bb_runtime_trace_prefixes_are_console_mirrored():
    source=(HERE/'menu-observe.c').read_text()
    start=source.index('static const char *mirrored[]')
    end=source.index('};',start)
    prefixes=re.findall(r'"([^"\n]+)"',source[start:end])
    for tag in ('FULL_BB_SET_MODE_OWNER_INIT ','FULL_BB_SET_MODE_PREFIX_UNKNOWN ',
                'FULL_BB_SET_MODE_PENDING ','FULL_BB_SET_MODE_REPLY_FREE ',
                'FULL_BB_MODE_FIRST_COMPLETION ','FULL_BB_MODE_OUTER_WORK ',
                'FULL_BB_MODE_SECOND_COMPLETION '):
        assert any(tag.startswith(prefix) for prefix in prefixes),tag


@pytest.fixture(scope='module')
def bb_constructor(tmp_path_factory):
    source=(HERE/'menu-observe.c').read_text()
    start=source.index('    const char *output_profile=getenv("MENU_ADF_SET_OUTPUT");')
    end=source.index('    software_gpe =',start)
    macro=re.search(r'^#define FULL_BB_SET_MODE_PROFILE .+$',
        (HERE/'device-models/bb-set-mode-device.h').read_text(),re.MULTILINE)
    imaging_macro=re.search(r'^#define FULL_IMAGING_PIN_CONNECTION_PROFILE .+$',
        (HERE/'device-models/imaging-pin-connection.h').read_text(),re.MULTILINE)
    control_macro=re.search(r'^#define FULL_IMAGING_CONTROL_CONNECTION_PROFILE .+$',
        (HERE/'device-models/imaging-control-connection.h').read_text(),re.MULTILINE)
    adf_macro=re.search(r'^#define FULL_IMAGING_ADF_CONNECTION_PROFILE .+$',
        (HERE/'device-models/imaging-adf-connection.h').read_text(),re.MULTILINE)
    vef_macro=re.search(r'^#define FULL_INFRABB_VEF_CONNECTION_PROFILE .+$',
        (HERE/'device-models/infrabb-vef-connection.h').read_text(),re.MULTILINE)
    vef_control_macro=re.search(r'^#define FULL_INFRABB_VEF_CONTROL_CONNECTION_PROFILE .+$',
        (HERE/'device-models/infrabb-vef-control-connection.h').read_text(),re.MULTILINE)
    pinmem_input_macro=re.search(r'^#define FULL_VEF_PINMEM_INPUT_CONNECTION_PROFILE .+$',
        (HERE/'device-models/vef-pinmem-input-connection.h').read_text(),re.MULTILINE)
    pinmem_control_macro=re.search(r'^#define FULL_VEF_PINMEM_CONTROL_CONNECTION_PROFILE .+$',
        (HERE/'device-models/vef-pinmem-control-connection.h').read_text(),re.MULTILINE)
    pinmem_peers_macro=re.search(r'^#define FULL_PINMEM_PEER_CONNECTIONS_PROFILE .+$',
        (HERE/'device-models/scalar-connection.h').read_text(),re.MULTILINE)
    hdmi_audio_macro=re.search(r'^#define FULL_ADF_HDMI_AUDIO_CONNECTION_PROFILE .+$',
        (HERE/'device-models/adf-hdmi-audio-connection.h').read_text(),re.MULTILINE)
    video_macro=re.search(r'^#define FULL_PINMEM_HDMI_VIDEO_CONNECTION_PROFILE .+$',
        (HERE/'device-models/pinmem-hdmi-video-connection.h').read_text(),re.MULTILINE)
    osd_macro=re.search(r'^#define FULL_PINMEM_OSD_CONNECTION_PROFILE .+$',
        (HERE/'device-models/pinmem-osd-connection.h').read_text(),re.MULTILINE)
    assert all((macro,imaging_macro,control_macro,adf_macro,vef_macro,vef_control_macro,
                pinmem_input_macro,pinmem_control_macro,pinmem_peers_macro,hdmi_audio_macro,
                video_macro,osd_macro))
    directory=tmp_path_factory.mktemp('bb-constructor-gate')
    code=directory/'constructor.c'
    code.write_text(r'''
#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include "device-models/cp302c-no-transition.h"
#include "device-models/cp-notification-control.h"
#include "device-models/cp-parameter-batch.h"
#include "device-models/cp-capture-format.h"
#include "device-models/cp-output-policy.h"
#include "device-models/cp-startup-controls-diagnostic.h"
#include "device-models/cp-ee-controls-diagnostic.h"
#include "device-models/cp-movie-format-diagnostic.h"
#include "device-models/cp-start-state-provider.h"
#include "device-models/cp-parameter-state.h"
#include "device-models/cp-state-publication.h"
#include "functional-camera-abi.h"
#include "device-models/functional-startup-control.h"
static int functional_camera_enabled,functional_camera_init_calls;
static unsigned int still_format_ticket_pid,startup_control_ticket_pid;
static unsigned int still_format_init_calls,startup_control_init_calls;
int functional_still_format_owner_init(void) {
 assert(functional_camera_init_calls==1);still_format_init_calls++;
 return getenv("FIXTURE_STILL_FORMAT_OWNER_FAIL")?-ENODATA:0;
}
int functional_startup_control_owner_init(void) {
 assert(functional_camera_init_calls==1 && still_format_init_calls==1);
 assert(!getenv("FIXTURE_FUNCTIONAL_OWNER_FAIL") && !getenv("FIXTURE_STILL_FORMAT_OWNER_FAIL"));
 startup_control_init_calls++;return getenv("FIXTURE_STARTUP_CONTROL_OWNER_FAIL")?-ENODATA:0;
}
int native_functional_camera_control_owner_init(void) {
 functional_camera_init_calls++;return getenv("FIXTURE_FUNCTIONAL_OWNER_FAIL")?-ENODATA:0;
}
static int cp_owned_state_enabled,cp_owned_state_calls;
static struct cp_start_state_provider cp_owned_start_state;
static struct cp_parameter_state cp_owned_parameters;
int cp_start_state_provider_init(struct cp_start_state_provider *p) {
 memset(p,0,sizeof *p);return getenv("FIXTURE_CP_OWNED_PROVIDER_FAIL")?-ENODATA:0;
}
int cp_parameter_state_init(struct cp_parameter_state *p,bool enabled) {
 memset(p,0,sizeof *p);(void)enabled;return getenv("FIXTURE_CP_OWNED_PARAMETER_FAIL")?-ENODATA:0;
}
int cp_parameter_state_consume_reset_store(struct cp_parameter_state *p) {
 (void)p;return getenv("FIXTURE_CP_OWNED_RESET_FAIL")?-ENODATA:0;
}
int cp_parameter_state_consume_common_stores(struct cp_parameter_state *p) {
 (void)p;return (getenv("FIXTURE_CP_OWNED_RESET_FAIL") || getenv("FIXTURE_CP_OWNED_COMMON_FAIL"))?-ENODATA:0;
}
static int cp_owned_bootstrap_inputs(void) {
 return getenv("FIXTURE_CP_OWNED_INPUTS_FAIL")?-ENODATA:0;
}
int native_cp_state_publication_owner_init(void) {
 cp_owned_state_calls++;return getenv("FIXTURE_CP_OWNED_PUBLICATION_FAIL")?-ENODATA:0;
}
static int cp_movie_format_enabled,cp_movie_format_calls;
int native_cp_movie_format_diagnostic_owner_init(void) {
 cp_movie_format_calls++;return getenv("FIXTURE_CP_MOVIE_FORMAT_OWNER_FAIL")?-1021:0;
}
static int cp_ee_controls_enabled,cp_ee_controls_calls;
int native_cp_ee_controls_diagnostic_owner_init(void) {
 cp_ee_controls_calls++;return getenv("FIXTURE_CP_EE_OWNER_FAIL")?-1021:0;
}
static int cp_startup_controls_enabled,cp_startup_controls_calls;
int native_cp_startup_controls_diagnostic_owner_init(void) {
 cp_startup_controls_calls++;return getenv("FIXTURE_CP_STARTUP_OWNER_FAIL")?-1021:0;
}
static struct cp_output_policy cp_output_policy_state;
int cp_output_policy_init(struct cp_output_policy *out,bool enabled) {
 memset(out,0,sizeof(*out));out->owner_pid=getpid();out->enabled=enabled;return 0;
}
static int cp_capture_format_enabled,cp_capture_format_calls;
int native_cp_capture_format_diagnostic_owner_init(void) {
 cp_capture_format_calls++;return getenv("FIXTURE_CP_CAPTURE_FORMAT_OWNER_FAIL")?-1021:0;
}
void native_cp_capture_format_diagnostic_snapshot(struct native_cp_capture_format_diagnostic_snapshot *out) {
 memset(out,0,sizeof(*out));out->owner_pid=getpid();
 out->initialized=out->diagnostic_only=out->no_publication=cp_capture_format_calls && !getenv("FIXTURE_CP_CAPTURE_FORMAT_OWNER_FAIL");
}
static struct cp_parameter_batch cp_parameter_batch_state;
int cp_parameter_batch_init(struct cp_parameter_batch *out,bool enabled) {
 memset(out,0,sizeof(*out));out->owner_pid=getpid();out->enabled=enabled;return 0;
}
static int cp_notification_control_enabled,cp_notification_calls;
static int adf_set_input_enabled,full_adf_set_output_enabled,full_bb_set_mode_enabled;
static int imaging_pin_connection_enabled,imaging_control_connection_enabled,imaging_adf_connection_enabled,infrabb_vef_connection_enabled;
static int infrabb_vef_control_connection_enabled,vef_pinmem_input_connection_enabled;
static int vef_pinmem_control_connection_enabled,pinmem_peer_connections_enabled,adf_hdmi_audio_connection_enabled;
static int pinmem_hdmi_video_connection_enabled,pinmem_osd_connection_enabled;
static int cp302c_no_transition_enabled,cp302c_diagnostic_enabled,cp302c_calls,cp302c_rc,cp302c_diagnostic_calls;
static int hdmi_state_calls,hdmi_state_rc,video_calls,video_rc,osd_calls,osd_rc;
static int pinmem_control_calls,pinmem_control_rc,scalar_calls,scalar_rc,adf_connection_calls,adf_connection_rc,drawinfo_calls,drawinfo_rc,hdmi_audio_calls,hdmi_audio_rc;
static int output_calls,bb_calls,bb_rc,imaging_calls,imaging_rc,control_calls,control_rc,adf_calls,adf_rc,vef_calls,vef_rc,vef_control_calls,vef_control_rc,pinmem_input_calls,pinmem_input_rc;
static int same_name(const char *a,const char *b) {return a && b && !strcmp(a,b);}
static int full_adf_set_output_owner_init(void) {output_calls++;return 0;}
static int full_bb_set_mode_owner_init(void) {bb_calls++;return bb_rc;}
static int full_imaging_pin_connection_owner_init(void) {imaging_calls++;return imaging_rc;}
static int full_imaging_control_connection_owner_init(void) {control_calls++;return control_rc;}
static int full_imaging_adf_connection_owner_init(void) {adf_calls++;return adf_rc;}
static int full_infrabb_vef_connection_owner_init(void) {vef_calls++;return vef_rc;}
int full_infrabb_vef_control_connection_owner_init(void) {vef_control_calls++;return vef_control_rc;}
int full_vef_pinmem_input_connection_owner_init(void) {pinmem_input_calls++;return pinmem_input_rc;}
int full_vef_pinmem_control_connection_owner_init(void) {pinmem_control_calls++;return pinmem_control_rc;}
int full_scalar_connection_owner_init(void) {scalar_calls++;return scalar_rc;}
int full_adf_connection_owner_init(void) {adf_connection_calls++;return adf_connection_rc;}
int full_pinmem_drawinfo_connection_owner_init(void) {drawinfo_calls++;return drawinfo_rc;}
int full_adf_hdmi_audio_connection_owner_init(void) {hdmi_audio_calls++;return hdmi_audio_rc;}
int full_hdmi_video_state_owner_init(void) {hdmi_state_calls++;return hdmi_state_rc;}
int full_pinmem_hdmi_video_connection_owner_init(void) {
 video_calls++;return hdmi_state_calls && !hdmi_state_rc?video_rc:-1021;
}
int full_pinmem_osd_connection_owner_init(void) {osd_calls++;return osd_rc;}
int native_cp302c_owner_init(void) {cp302c_calls++;return cp302c_rc;}
int native_cp302c_diagnostic_owner_init(void) {cp302c_calls++;cp302c_diagnostic_calls++;return cp302c_rc;}
int native_cp_notification_owner_init(void) {cp_notification_calls++;return getenv("FIXTURE_CP_NOTIFICATION_OWNER_FAIL")?-1021:0;}
void native_cp_notification_snapshot(struct native_cp_notification_snapshot *out) {
 memset(out,0,sizeof(*out));out->owner_pid=getpid();
 out->initialized=out->virtual_mode_policy=cp_notification_calls && !getenv("FIXTURE_CP_NOTIFICATION_OWNER_FAIL");
}
static void observe_cp302c_3007_free(unsigned int destination,const unsigned char wire[12]) {
 (void)destination;(void)wire;
}
static int native_cp_background_bind_free_observer(void (*observer)(unsigned int,const unsigned char[12])) {
 return observer==observe_cp302c_3007_free && !getenv("FIXTURE_CP302C_BIND_FAIL")?0:-1021;
}
void native_cp302c_snapshot(struct native_cp302c_snapshot *out) {
 memset(out,0,sizeof(*out));out->owner_pid=getpid();
 out->initialized=cp302c_calls && !cp302c_rc;
 out->history_valid=out->current_known=out->initialized && !cp302c_diagnostic_calls;
}
/* This fixture executes the constructor, not Backup reads. */
static int backup_api_stub() {return 0;}
#define real_dlsym(handle,name) ((void)(handle),(void)(name),backup_api_stub)
static int (*real_backup_get_datasize)(unsigned int);
static int (*real_backup_nread)(unsigned int,void *,unsigned int);
static int hdmi_video_backup_read(unsigned int key,void *out,unsigned int cap,unsigned int *length) {
 (void)key;(void)out;(void)cap;(void)length;return -1021;
}
int full_hdmi_video_state_bind_backup(int (*reader)(unsigned int,void *,unsigned int,unsigned int *)) {
 return reader==hdmi_video_backup_read?0:-1021;
}
static int full_hdmi_upm_receipt(unsigned int stage,unsigned long long lease,void *pointer,
 const unsigned char raw[16],const unsigned char effective[16],void (*record)(const char *,const char *)) {
 (void)stage;(void)lease;(void)pointer;(void)raw;(void)effective;(void)record;return -1021;
}
int full_hdmi_video_state_bind_kernel_observer(int (*observer)(unsigned int,unsigned long long,void *,
 const unsigned char[16],const unsigned char[16],void (*)(const char *,const char *))) {
 return observer==full_hdmi_upm_receipt?0:-1021;
}
struct full_vef_pinmem_control_connection_snapshot {int owner_pid;unsigned int initialized,unadmitted_count;};
void full_vef_pinmem_control_connection_snapshot(struct full_vef_pinmem_control_connection_snapshot *out) {
 out->owner_pid=getpid();out->initialized=pinmem_control_calls && !pinmem_control_rc;out->unadmitted_count=0;
}
struct scalar_connection_snapshot {int owner_pid;unsigned int initialized;};
void full_scalar_connection_snapshot(struct scalar_connection_snapshot *out) {
 out->owner_pid=getpid();out->initialized=scalar_calls && !scalar_rc;
}
void full_adf_connection_snapshot(struct scalar_connection_snapshot *out) {
 out->owner_pid=getpid();out->initialized=adf_connection_calls && !adf_connection_rc;
}
void full_pinmem_drawinfo_connection_snapshot(struct scalar_connection_snapshot *out) {
 out->owner_pid=getpid();out->initialized=drawinfo_calls && !drawinfo_rc;
}
struct full_adf_hdmi_audio_connection_snapshot {int owner_pid;unsigned int initialized;};
void full_adf_hdmi_audio_connection_snapshot(struct full_adf_hdmi_audio_connection_snapshot *out) {
 out->owner_pid=getpid();out->initialized=hdmi_audio_calls && !hdmi_audio_rc;
}
struct full_pinmem_hdmi_video_connection_snapshot {
 struct scalar_connection_snapshot connection;
 unsigned int source_gate_known,source_gate,source_history_known;
};
void full_pinmem_hdmi_video_connection_snapshot(struct full_pinmem_hdmi_video_connection_snapshot *out) {
 memset(out,0,sizeof(*out));out->connection.owner_pid=getpid();
 out->connection.initialized=video_calls && !video_rc && hdmi_state_calls && !hdmi_state_rc;
 out->source_gate_known=out->source_history_known=out->connection.initialized;
}
struct full_hdmi_video_state_snapshot {int owner_pid;unsigned int initialized,state_id,current_initializing,history_known;};
void full_hdmi_video_state_snapshot(struct full_hdmi_video_state_snapshot *out) {
 memset(out,0,sizeof(*out));out->owner_pid=getpid();out->initialized=hdmi_state_calls && !hdmi_state_rc;
 out->state_id=out->current_initializing=out->history_known=out->initialized;
}
struct full_pinmem_osd_connection_snapshot {int owner_pid;unsigned int initialized;};
void full_pinmem_osd_connection_snapshot(struct full_pinmem_osd_connection_snapshot *out) {
 out->owner_pid=getpid();out->initialized=osd_calls && !osd_rc;
}
struct full_vef_pinmem_input_connection_snapshot {int owner_pid;unsigned int initialized,unadmitted_count,record_bound;};
void full_vef_pinmem_input_connection_snapshot(struct full_vef_pinmem_input_connection_snapshot *out) {
 out->owner_pid=getpid();out->initialized=pinmem_input_calls && !pinmem_input_rc;out->unadmitted_count=0;out->record_bound=out->initialized;
}
struct full_infrabb_vef_control_connection_snapshot {int owner_pid;unsigned int initialized,unadmitted_count;};
void full_infrabb_vef_control_connection_snapshot(struct full_infrabb_vef_control_connection_snapshot *out) {
 out->owner_pid=getpid();out->initialized=vef_control_calls && !vef_control_rc;out->unadmitted_count=0;
}
struct full_infrabb_vef_connection_snapshot {int owner_pid;unsigned int initialized,unadmitted_count;};
static void full_infrabb_vef_connection_snapshot(struct full_infrabb_vef_connection_snapshot *out) {
 out->owner_pid=getpid();out->initialized=vef_calls && !vef_rc;out->unadmitted_count=0;
}
struct full_imaging_adf_connection_snapshot {int owner_pid;unsigned int initialized,no_format_checked;};
static void full_imaging_adf_connection_snapshot(struct full_imaging_adf_connection_snapshot *out) {
 out->owner_pid=getpid();out->initialized=adf_calls && !adf_rc;out->no_format_checked=0;
}
struct full_imaging_control_connection_snapshot {int owner_pid;unsigned int initialized,peer_marker_known;};
static void full_imaging_control_connection_snapshot(struct full_imaging_control_connection_snapshot *out) {
 out->owner_pid=getpid();out->initialized=control_calls && !control_rc;out->peer_marker_known=0;
}
struct full_imaging_pin_connection_snapshot {int owner_pid;unsigned int initialized;struct {unsigned int cache[5];} format;};
static void full_imaging_pin_connection_snapshot(struct full_imaging_pin_connection_snapshot *out) {
 out->owner_pid=getpid();out->initialized=1;out->format.cache[0]=1;
}
struct full_bb_set_mode_snapshot {int owner_pid;unsigned int initialized,state_word,state_epoch,prefix_messages,config_initialized;};
static void full_bb_set_mode_snapshot(struct full_bb_set_mode_snapshot *out) {
 out->owner_pid=getpid();out->initialized=out->state_word=out->state_epoch=out->config_initialized=1;
 out->prefix_messages=0;
}
static void record(const char *tag,const char *text) {printf("%s%s\n",tag,text);}
'''+macro[0]+'\n'+imaging_macro[0]+'\n'+control_macro[0]+'\n'+adf_macro[0]+'\n'+vef_macro[0]+'\n'+vef_control_macro[0]+'\n'+pinmem_input_macro[0]+'\n'+pinmem_control_macro[0]+'\n'+pinmem_peers_macro[0]+'\n'+hdmi_audio_macro[0]+'\n'+video_macro[0]+'\n'+osd_macro[0]+r'''
static void constructor_gate(void) {
'''+source[start:end]+r'''
}
int main(int argc,char **argv) {
    if(argc!=18)return 2;
    adf_set_input_enabled=atoi(argv[1]);bb_rc=atoi(argv[2]);imaging_rc=atoi(argv[3]);control_rc=atoi(argv[4]);adf_rc=atoi(argv[5]);vef_rc=atoi(argv[6]);vef_control_rc=atoi(argv[7]);pinmem_input_rc=atoi(argv[8]);
    pinmem_control_rc=atoi(argv[9]);scalar_rc=atoi(argv[10]);adf_connection_rc=atoi(argv[11]);drawinfo_rc=atoi(argv[12]);hdmi_audio_rc=atoi(argv[13]);
    hdmi_state_rc=atoi(argv[14]);video_rc=atoi(argv[15]);osd_rc=atoi(argv[16]);cp302c_rc=atoi(argv[17]);constructor_gate();
    assert(still_format_ticket_pid==(unsigned int)getpid() && startup_control_ticket_pid==(unsigned int)getpid());
    printf("FUNCTIONAL_RESULT enabled=%u local_init_calls=%u startup_init_calls=%u backend_RPC=0 physical_ASIC_verified=0 capture_verified=0\n",
           (unsigned int)functional_camera_enabled,(unsigned int)functional_camera_init_calls,startup_control_init_calls);
    printf("RESULT output=%d bb=%d output_init=%d bb_init=%d imaging=%d imaging_init=%d control=%d control_init=%d adf=%d adf_init=%d vef=%d vef_init=%d vef_control=%d vef_control_init=%d pinmem_input=%d pinmem_input_init=%d pinmem_control=%d pinmem_control_init=%d pinmem_peers=%d scalar_init=%d pinmem_adf_init=%d drawinfo_init=%d hdmi_audio=%d hdmi_audio_init=%d video=%d video_init=%d hdmi_state_init=%d osd=%d osd_init=%d cp302c=%d cp302c_init=%d diagnostic=%d diagnostic_init=%d notification=%d notification_init=%d capture_format=%d capture_format_init=%d startup=%d startup_init=%d ee_controls=%d ee_controls_init=%d movie_format=%d movie_format_init=%d owned_state=%d owned_state_init=%d\n",
        full_adf_set_output_enabled,full_bb_set_mode_enabled,output_calls,bb_calls,
        imaging_pin_connection_enabled,imaging_calls,imaging_control_connection_enabled,control_calls,
        imaging_adf_connection_enabled,adf_calls,infrabb_vef_connection_enabled,vef_calls,
        infrabb_vef_control_connection_enabled,vef_control_calls,vef_pinmem_input_connection_enabled,pinmem_input_calls,
        vef_pinmem_control_connection_enabled,pinmem_control_calls,pinmem_peer_connections_enabled,
        scalar_calls,adf_connection_calls,drawinfo_calls,adf_hdmi_audio_connection_enabled,hdmi_audio_calls,
        pinmem_hdmi_video_connection_enabled,video_calls,hdmi_state_calls,pinmem_osd_connection_enabled,osd_calls,
        cp302c_no_transition_enabled,cp302c_calls,cp302c_diagnostic_enabled,cp302c_diagnostic_calls,
        cp_notification_control_enabled,cp_notification_calls,cp_capture_format_enabled,cp_capture_format_calls,
        cp_startup_controls_enabled,cp_startup_controls_calls,cp_ee_controls_enabled,cp_ee_controls_calls,
        cp_movie_format_enabled,cp_movie_format_calls,cp_owned_state_enabled,cp_owned_state_calls);
    return 0;
}
''')
    binary=directory/'constructor'
    subprocess.run(['cc','-std=c11','-Wall','-Wextra','-Werror','-pedantic',
        '-I',str(HERE),str(code),'-o',str(binary)],check=True,capture_output=True,text=True,timeout=15)
    def run(env,input_enabled=True,owner_rc=0,imaging_owner_rc=0,control_owner_rc=0,adf_owner_rc=0,vef_owner_rc=0,vef_control_owner_rc=0,pinmem_input_owner_rc=0,pinmem_control_owner_rc=0,scalar_owner_rc=0,adf_connection_owner_rc=0,drawinfo_owner_rc=0,hdmi_audio_owner_rc=0,hdmi_state_owner_rc=0,video_owner_rc=0,osd_owner_rc=0,cp302c_owner_rc=0):
        return subprocess.run([str(binary),str(int(input_enabled)),str(owner_rc),str(imaging_owner_rc),str(control_owner_rc),str(adf_owner_rc),str(vef_owner_rc),str(vef_control_owner_rc),str(pinmem_input_owner_rc),str(pinmem_control_owner_rc),str(scalar_owner_rc),str(adf_connection_owner_rc),str(drawinfo_owner_rc),str(hdmi_audio_owner_rc),str(hdmi_state_owner_rc),str(video_owner_rc),str(osd_owner_rc),str(cp302c_owner_rc)],
            env=env,check=True,capture_output=True,text=True,timeout=5).stdout
    return run


def test_complete_clean_guest_exports_reach_actual_bb_constructor(tmp_path,bb_constructor):
    launcher=load_script('bb_complete_ctor_start_menu','start-menu.py')
    host=launcher.profile_environment(host_environment(tmp_path),natural_boot=True)
    host.update(MENU_BACKUP_SYNC=backup.PROFILE,SEED_BACKUP='alllang',
        A7C2_DIRECTORY_SD_PROFILE='directory-vvfat-256gb-v1')
    guest=clean_guest_environment(menu_probe_setup(host))
    assert 'A7C2_BB_SET_MODE' not in guest and 'MENU_OBSERVE_SELFTEST' not in guest
    log=bb_constructor(guest)
    assert 'RESULT output=1 bb=1 output_init=1 bb_init=1' in log
    assert 'FULL_BB_SET_MODE_PROFILE requested='+PROFILE+' enabled=1 first_missing=none ' in log
    assert 'not_live_CP_RAM_read=1 capture_verified=0' in log
    assert 'FULL_BB_SET_MODE_OWNER_INIT ' in log and 'before_any_BB_input=1' in log
    for name in ('MENU_BACKUP_SYNC','MENU_CP_BACKGROUND','MENU_UDATE_DISTRIBUTION',
                 'MENU_TOUCH_PANEL','MENU_TCIN_DETECT','MENU_DFS_SELECTOR',
                 'MENU_AUDIO_BOOT_CONFIG','MENU_PIN_REGISTRY','MENU_PIN_CONTROL_MEMORY',
                 'MENU_PIN_CONNECTION'):
        bad=dict(guest);bad.pop(name)
        assert 'RESULT output=0 bb=0 output_init=0 bb_init=0' in bb_constructor(bad)
    assert 'RESULT output=0 bb=0 output_init=0 bb_init=0' in bb_constructor(guest,input_enabled=False)
    assert 'RESULT output=1 bb=0 output_init=1 bb_init=1' in bb_constructor(guest,owner_rc=-1021)
    for change in ({'MENU_BB_SET_MODE':'unknown'},{'MENU_BB_SET_MODE':''},
                   {'MENU_OBSERVE_SELFTEST':'1'}):
        assert ' bb=0 ' in bb_constructor({**guest,**change})
    host.pop('MENU_BB_SET_MODE');host.pop('A7C2_BB_SET_MODE')
    default_guest=clean_guest_environment(menu_probe_setup(host))
    assert 'MENU_BB_SET_MODE' not in default_guest
    assert 'RESULT output=1 bb=0 output_init=1 bb_init=0' in bb_constructor(default_guest)


def test_bb_backup_admission_rejects_before_candidate_or_outputs(tmp_path,monkeypatch):
    launcher=load_script('bb_prepare_start_menu','start-menu.py')
    env=launcher.profile_environment(host_environment(tmp_path),natural_boot=True)
    env.update(MENU_BACKUP_SYNC=backup.PROFILE,SEED_BACKUP='alllang',
        A7C2_DIRECTORY_SD_PROFILE='directory-vvfat-256gb-v1',MENU_USB_NET='1')
    def no_build(*args):raise AssertionError('invalid BB profile reached candidate/filesystem work')
    monkeypatch.setattr(backup,'validate_build',no_build)
    for name,value in [('MENU_BB_SET_MODE','unknown'),('A7C2_BB_SET_MODE',''),
                       ('A7C2_DIRECTORY_SD_PROFILE',''),('MENU_ADF_SET_OUTPUT',''),
                       ('SEED_BACKUP','private'),('QEMU_CPU_COUNT','2'),
                       *[(key,'1') for key in backup.BB_MODE_CONFLICTS]]:
        with pytest.raises(ValueError):backup.prepare_profile(HERE,{**env,name:value})
