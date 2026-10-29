import ast
import argparse
import importlib.util
import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

import backup_profile as backup
from directory_sd import directory_lease
from directory_sd_profile import prepare_profile as directory_profile

HERE=Path(__file__).resolve().parent
HARDWARE=HERE.parents[1]/'report/virtual-pcidma'


@pytest.fixture(autouse=True)
def output_profile_off(monkeypatch):
    monkeypatch.setenv('A7C2_ADF_SET_OUTPUT','')
    monkeypatch.setenv('MENU_ADF_SET_OUTPUT','')
    monkeypatch.setenv('A7C2_BB_SET_MODE','')
    monkeypatch.setenv('MENU_BB_SET_MODE','')


def build_fixture(tmp_path):
    stage=backup.load_module('backup_stage_test',HARDWARE/'stage_hardware.py')
    build=tmp_path/'candidate'
    binary=build/'build/qemu-system-aarch64'
    binary.parent.mkdir(parents=True)
    binary.write_bytes(b'combined build identity fixture, never executed')
    receipt={'scope':'default-off PCI/ATU hardware in native GTK/USB/directory-SD build',
             'binary_sha256':backup.sha(binary),
             'model_source_sha256':{n:backup.sha(HARDWARE/'hardware'/n) for n in stage.MODEL_FILES},
             'board_source_sha256':{n:backup.sha(HARDWARE/'hardware'/n) for n in stage.FRAGMENTS},
             'atu_source_sha256':{n:backup.sha(HARDWARE.parent/'virtual-atu/hardware'/n) for n in stage.ATU_FILES}}
    (build/'pci-hardware-build.json').write_text(json.dumps(receipt))
    return build,receipt


def required(build):
    return {'A7C2_BACKUP_SYNC':backup.PROFILE,'A7C2_BACKUP_BUILD':str(build),
            'MENU_CP_BACKGROUND':'virtual-mode3-cold-v1',
            'MENU_UDATE_DISTRIBUTION':'virtual-roundtrip-v1',
            'MENU_TOUCH_PANEL':'virtual-config-v1',
            'A7C2_DIRECTORY_SD_PROFILE':'directory-vvfat-256gb-v1'}


@pytest.mark.parametrize('dfs,vef,adf,adf_input,adf_output',[(False,False,False,False,False),
                                        (True,False,False,False,False),(True,True,False,False,False),
                                        (True,True,True,False,False),(True,True,True,True,False),
                                        (True,True,True,True,True)])
def test_composes_directory_usb_and_pci_without_replacing_original(tmp_path,dfs,vef,adf,adf_input,adf_output):
    build,_=build_fixture(tmp_path)
    before=backup.sha(HERE/'qemu-virt-board/virt-packed.dtb')
    with directory_lease(tmp_path/'card') as lease:
        env=directory_profile(HERE,lease,tmp_path/'profiles')
        env.update(required(build))
        if dfs:env.update(MENU_TCIN_DETECT='virtual-inactive-v1',MENU_DFS_SELECTOR='virtual-selector-v1')
        if vef:env['MENU_VEF_PATH']='virtual-nomem-v1'
        if adf:env.update(MENU_ADF_PROC_PATH='virtual-source7-idle-v1',MENU_AUDIO_BOOT_CONFIG='1',
                          MENU_PIN_REGISTRY='1',MENU_PIN_CONTROL_MEMORY='1',MENU_PIN_CONNECTION='cold')
        if adf_input:env['MENU_ADF_SET_INPUT']=backup.INPUT_PROFILE
        if adf_output:env['MENU_ADF_SET_OUTPUT']=backup.OUTPUT_PROFILE
        selected=backup.prepare_profile(HERE,env)
    script=Path(selected['MENU_KERNEL_SCRIPT']).read_text()
    assert 'driver=vvfat' in script and 'total-sectors=500000000' in script
    assert '--setenv QEMU_SONY_USB_NET 1' in script
    assert '--setenv QEMU_SONY_BACKUP_TEST 1' in script
    assert '--setenv QEMU_SONY_PHY_INIT_TEST 1' in script
    assert ('--setenv QEMU_SONY_DFS_TEST 1' in script)==dfs
    assert '--setenv QEMU_SONY_BACKUP_FILE /backup-primary.bin' in script
    assert selected['QEMU_SONY_PCIDMA']=='1' and selected['SEED_BACKUP']=='alllang'
    proof=json.loads(Path(selected['MENU_BACKUP_PROFILE_RECEIPT']).read_text())
    assert proof['dfs_selector_profile']==('virtual-selector-v1' if dfs else None)
    assert proof['vef_path_profile']==('virtual-nomem-v1' if vef else None)
    for name,value in backup.adf_proc_profile_fields('virtual-source7-idle-v1' if adf else '').items():
        assert proof[name]==value
    for name,value in backup.adf_set_input_profile_fields(backup.INPUT_PROFILE if adf_input else '').items():
        assert type(proof[name]) is type(value) and proof[name]==value
    for name,value in backup.adf_set_output_profile_fields(backup.OUTPUT_PROFILE if adf_output else '').items():
        assert type(proof[name]) is type(value) and proof[name]==value
    assert proof['dfs_actual_clock_changes'] is False
    assert backup.sha(proof['fixture'])==backup.PRIMARY_SHA
    assert Path(proof['fixture']).stat().st_size==backup.PRIMARY_BYTES
    parser=backup.load_module('backup_dtb_test',HARDWARE/'verifiers/verify_enumeration.py')
    nodes=parser.fdt_nodes(Path(selected['MENU_DTB']).read_bytes())
    assert '/usb@b000000' in nodes and '/sony-test-pcie0' in nodes
    assert backup.sha(HERE/'qemu-virt-board/virt-packed.dtb')==before
    assert not proof['original_cp_executed'] and not proof['capture_verified']


def test_old_or_changed_build_is_rejected(tmp_path):
    build,receipt=build_fixture(tmp_path)
    backup.validate_build(HERE,build)
    receipt['model_source_sha256']['test_pcie_peer.c']='0'*64
    (build/'pci-hardware-build.json').write_text(json.dumps(receipt))
    with pytest.raises(ValueError,match='current reviewed sources'):
        backup.validate_build(HERE,build)


def test_missing_or_conflicting_profiles_rejected_before_output(tmp_path):
    build,_=build_fixture(tmp_path)
    env=required(build)
    for extra in ({'MENU_DFS_SELECTOR':'virtual-selector-v1'},
                  {'MENU_DFS_SELECTOR':'unsupported','MENU_TCIN_DETECT':'virtual-inactive-v1'}):
        with pytest.raises(ValueError,match='DFS selector'):
            backup.prepare_profile(HERE,{**env,**extra})
    for extra in ({'MENU_VEF_PATH':'virtual-nomem-v1'},{'MENU_VEF_PATH':'unsupported'}):
        with pytest.raises(ValueError,match='VEF NoMem'):
            backup.prepare_profile(HERE,{**env,**extra})
    for name in ('MENU_CP_BACKGROUND','MENU_UDATE_DISTRIBUTION','MENU_TOUCH_PANEL',
                 'A7C2_DIRECTORY_SD_PROFILE'):
        bad=dict(env);bad.pop(name)
        with pytest.raises(ValueError,match='complete natural'):
            backup.prepare_profile(HERE,bad)
    for key,value in (('MENU_PCIDMA_XFER','1'),('QEMU_CPU_COUNT','2'),
                      ('A7C2_NATURAL_IMAGING_PROFILE','1')):
        with pytest.raises(ValueError,match='conflicts'):
            backup.prepare_profile(HERE,{**env,key:value})


def test_natural_entry_requires_all_predecessors_and_explicit_build(tmp_path):
    spec=importlib.util.spec_from_file_location('backup_start_menu',HERE/'start-menu.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    env={'A7C2_BACKUP_SYNC':backup.PROFILE,'A7C2_BACKUP_BUILD':str(tmp_path),
         'A7C2_DIRECTORY_SD':str(tmp_path),'A7C2_CP_BACKGROUND':'virtual-mode3-cold-v1',
         'A7C2_UDATE_DISTRIBUTION':'virtual-roundtrip-v1','A7C2_TOUCH_PANEL':'virtual-config-v1'}
    selected=module.profile_environment(env,natural_boot=True)
    assert selected['A7C2_BACKUP_SYNC']==backup.PROFILE
    assert 'MENU_DFS_SELECTOR' not in selected
    dfs_env={**env,'A7C2_TCIN_DETECT':'virtual-inactive-v1','A7C2_DFS_SELECTOR':'virtual-selector-v1'}
    assert module.profile_environment(dfs_env,natural_boot=True)['MENU_DFS_SELECTOR']=='virtual-selector-v1'
    assert 'MENU_VEF_PATH' not in module.profile_environment(dfs_env,natural_boot=True)
    assert module.profile_environment({**dfs_env,'A7C2_VEF_PATH':'virtual-nomem-v1'},natural_boot=True)['MENU_VEF_PATH']=='virtual-nomem-v1'
    for bad in ({**env,'A7C2_VEF_PATH':'virtual-nomem-v1'},
                {**dfs_env,'A7C2_VEF_PATH':'unsupported'}):
        with pytest.raises(ValueError,match='VEF'):
            module.profile_environment(bad,natural_boot=True)
    for bad in ({**env,'A7C2_DFS_SELECTOR':'virtual-selector-v1'},
                {**dfs_env,'A7C2_DFS_SELECTOR':'unsupported'}):
        with pytest.raises(ValueError,match='DFS'):
            module.profile_environment(bad,natural_boot=True)
    for name in ('A7C2_CP_BACKGROUND','A7C2_UDATE_DISTRIBUTION','A7C2_TOUCH_PANEL',
                 'A7C2_BACKUP_BUILD','A7C2_DIRECTORY_SD'):
        bad=dict(env);bad.pop(name)
        with pytest.raises(ValueError):module.profile_environment(bad,natural_boot=True)


def adf_host_environment(tmp_path):
    return {'A7C2_BACKUP_SYNC':backup.PROFILE,'A7C2_BACKUP_BUILD':str(tmp_path),
            'A7C2_DIRECTORY_SD':str(tmp_path),'A7C2_CP_BACKGROUND':'virtual-mode3-cold-v1',
            'A7C2_UDATE_DISTRIBUTION':'virtual-roundtrip-v1','A7C2_TOUCH_PANEL':'virtual-config-v1',
            'A7C2_TCIN_DETECT':'virtual-inactive-v1','A7C2_DFS_SELECTOR':'virtual-selector-v1',
            'A7C2_VEF_PATH':'virtual-nomem-v1','A7C2_ADF_PROC_PATH':'virtual-source7-idle-v1',
            'A7C2_ADF_SET_OUTPUT':''}


def test_adf_host_profile_is_explicit_scrubs_stale_and_retains_native_resources(tmp_path):
    module=backup.load_module('adf_start_menu',HERE/'start-menu.py')
    assert 'MENU_ADF_PROC_PATH' not in module.profile_environment(
        {'MENU_ADF_PROC_PATH':'virtual-source7-idle-v1'},natural_boot=True)
    env=adf_host_environment(tmp_path)
    selected=module.profile_environment(env,natural_boot=True)
    assert selected['MENU_ADF_PROC_PATH']=='virtual-source7-idle-v1'
    assert selected['MENU_VEF_PATH']=='virtual-nomem-v1'
    assert selected['MENU_AUDIO_BOOT_CONFIG']=='1'
    assert selected['MENU_PIN_CONNECTION']=='cold'
    assert not any(selected.get(name) for name in backup.ADF_CONFLICTS)
    with pytest.raises(ValueError):module.profile_environment(env,natural_boot=False)


@pytest.mark.parametrize('adf_input',[False,True])
@pytest.mark.parametrize('name,value',[
    ('A7C2_ADF_PROC_PATH','unsupported'),('A7C2_VEF_PATH',''),
    ('A7C2_VEF_PATH','unsupported'),('A7C2_DFS_SELECTOR',''),('A7C2_TCIN_DETECT',''),
    ('A7C2_TOUCH_PANEL',''),('A7C2_UDATE_DISTRIBUTION',''),('A7C2_CP_BACKGROUND',''),
    ('A7C2_BACKUP_SYNC',''),('A7C2_BACKUP_BUILD',''),('A7C2_DIRECTORY_SD',''),
    ('A7C2_HOST_SD','256gb'),('A7C2_SD_SPARSE','10g-empty'),
    ('A7C2_DIRECTORY_SD','relative'),('SEED_BACKUP','private'),
    ('A7C2_NATURAL_IMAGING_PROFILE','1'),('A7C2_PREVIEW_PNG','/tmp/preview.png'),
    ('MENU_YC_INJECT','1'),('MENU_YC_INPUT_RAW','/tmp/input.gray'),
    ('MENU_BB_READY_INJECT','1'),('MENU_BB_READY_LATE','1'),
    ('MENU_ACTIVATE_MODE','1'),('MENU_FORCE_SET','1'),('MENU_PIPELINE_ENDPOINT','1'),
    ('MENU_APPLY_MENU','1'),('MENU_CP_EVENT_INJECT','0x1118'),
])
def test_adf_host_rejects_unknown_missing_predecessors_and_injection(tmp_path,name,value,adf_input):
    module=backup.load_module('adf_start_menu_bad',HERE/'start-menu.py')
    env=adf_host_environment(tmp_path)
    if adf_input:env['A7C2_ADF_SET_INPUT']=backup.INPUT_PROFILE
    with pytest.raises(ValueError):
        module.profile_environment({**env,name:value},natural_boot=True)


@pytest.mark.parametrize('adf_input',[False,True])
def test_adf_backup_admission_fails_before_outputs_or_candidate_validation(tmp_path,monkeypatch,adf_input):
    env={**required(tmp_path),'MENU_TCIN_DETECT':'virtual-inactive-v1',
         'MENU_DFS_SELECTOR':'virtual-selector-v1','MENU_VEF_PATH':'virtual-nomem-v1',
         'MENU_ADF_PROC_PATH':'virtual-source7-idle-v1','MENU_AUDIO_BOOT_CONFIG':'1',
         'MENU_PIN_REGISTRY':'1','MENU_PIN_CONTROL_MEMORY':'1','MENU_PIN_CONNECTION':'cold'}
    if adf_input:env['MENU_ADF_SET_INPUT']=backup.INPUT_PROFILE
    def no_candidate(*args):raise AssertionError('invalid ADF profile reached candidate/filesystem work')
    monkeypatch.setattr(backup,'validate_build',no_candidate)
    for name,value in [('MENU_ADF_PROC_PATH','bad'),('MENU_VEF_PATH',''),
                       ('MENU_PIN_CONNECTION',''),('MENU_AUDIO_BOOT_CONFIG',''),
                       ('MENU_CP_BACKGROUND','wrong'),('A7C2_DIRECTORY_SD_PROFILE','wrong'),
                       *[(key,'1') for key in backup.ADF_CONFLICTS]]:
        with pytest.raises(ValueError):backup.prepare_profile(HERE,{**env,name:value})


@pytest.mark.parametrize('profile',['','virtual-source7-idle-v1'])
def test_adf_receipt_clock_scope_and_always_false_claims(profile):
    fields=backup.adf_proc_profile_fields(profile)
    selected=bool(profile)
    assert fields['adf_proc_path_profile']==(profile or None)
    assert fields['adf_proc_path_protocol']==('AP0323-path0-source7-idle-control-v1' if selected else None)
    assert fields['adf_proc_clock_policy']==('virtual-source7-control-events-v1' if selected else None)
    assert fields['adf_proc_clock_period_ns']==(1000000 if selected else None)
    for name in ('original_cp_executed','hardware_verified','native_frequency_verified',
                 'original_event_identity_verified','frames_verified','pcm_verified',
                 'audio_output_verified','capture_verified'):
        assert fields['adf_proc_'+name] is False
    source=(HERE/'qemu-menu-probe.py').read_text()
    assert '**adf_proc_profile_fields(adf_proc_path_profile)' in source
    assert 'export MENU_ADF_PROC_PATH=virtual-source7-idle-v1' in source


@pytest.mark.parametrize('adf_input',[False,True])
def test_adf_probe_validation_is_pre_vm_and_rejects_resource_or_injection_mix(monkeypatch,adf_input):
    tree=ast.parse((HERE/'qemu-menu-probe.py').read_text())
    first=next(i for i,n in enumerate(tree.body) if isinstance(n,ast.Assign) and
               isinstance(n.targets[0],ast.Name) and n.targets[0].id=='vef_path_profile')
    last=next(i for i,n in enumerate(tree.body) if isinstance(n,ast.Assign) and
              isinstance(n.targets[0],ast.Name) and n.targets[0].id=='font_option')
    code=compile(ast.Module(body=tree.body[first:last],type_ignores=[]),'<pre-vm-profiles>','exec')
    env={'MENU_VEF_PATH':'virtual-nomem-v1','MENU_ADF_PROC_PATH':'virtual-source7-idle-v1',
         'MENU_PIN_REGISTRY':'1','MENU_PIN_CONTROL_MEMORY':'1','MENU_PIN_CONNECTION':'cold',
         'MENU_AUDIO_BOOT_CONFIG':'1','SEED_BACKUP':'alllang'}
    if adf_input:env['MENU_ADF_SET_INPUT']=backup.INPUT_PROFILE
    args=SimpleNamespace(dmm_service=True,sony_timers=True,native_display='none')
    def run(values):
        monkeypatch.setattr(os,'environ',values)
        scope={'os':os,'args':args,'dfs_selector':'virtual-selector-v1',
               'parser':argparse.ArgumentParser(),'ADF_PROFILE':backup.ADF_PROFILE,
               'INPUT_PROFILE':backup.INPUT_PROFILE,'OUTPUT_PROFILE':backup.OUTPUT_PROFILE,
               'ADF_CONFLICTS':backup.ADF_CONFLICTS}
        exec(code,scope)
        return scope
    assert run(env)['adf_proc_path_profile']=='virtual-source7-idle-v1'
    assert run(env)['adf_set_input_profile']==(backup.INPUT_PROFILE if adf_input else '')
    if not adf_input:
        assert not run({k:v for k,v in env.items() if k!='MENU_ADF_PROC_PATH'})['adf_proc_path_profile']
    else:
        with pytest.raises(SystemExit):run({k:v for k,v in env.items() if k!='MENU_ADF_PROC_PATH'})
    for name,value in [('MENU_ADF_SET_INPUT','wrong'),('MENU_ADF_PROC_PATH','wrong'),('MENU_VEF_PATH',''),
                       ('MENU_AUDIO_BOOT_CONFIG',''),('SEED_BACKUP','private'),
                       *[(key,'1') for key in backup.ADF_CONFLICTS]]:
        with pytest.raises(SystemExit) as failure:run({**env,name:value})
        assert failure.value.code==2
    for name,value in [('dmm_service',False),('sony_timers',False),('native_display',None)]:
        original=getattr(args,name)
        setattr(args,name,value)
        with pytest.raises(SystemExit) as failure:run(env)
        assert failure.value.code==2
        setattr(args,name,original)


def test_adf_set_input_host_to_guest_forwarding_and_default_off(tmp_path):
    import menu_control
    env=adf_host_environment(tmp_path)
    for natural in (False,True):
        selected=menu_control.launcher.profile_environment(
            {'MENU_ADF_SET_INPUT':backup.INPUT_PROFILE},natural_boot=natural)
        assert 'MENU_ADF_SET_INPUT' not in selected
    assert 'MENU_ADF_SET_INPUT' not in menu_control.launcher.profile_environment(env,natural_boot=True)
    selected=menu_control.launcher.profile_environment(
        {**env,'A7C2_ADF_SET_INPUT':backup.INPUT_PROFILE},natural_boot=True)
    menu_control.native_display_environment(selected,'none')
    assert selected['MENU_ADF_SET_INPUT']==backup.INPUT_PROFILE
    assert selected['MENU_ADF_PROC_PATH']==backup.ADF_PROFILE
    tree=ast.parse((HERE/'qemu-menu-probe.py').read_text())
    export=next(node for node in ast.walk(tree) if isinstance(node,ast.If) and
                isinstance(node.test,ast.Name) and node.test.id=='adf_set_input_profile')
    code=compile(ast.Module(body=[export],type_ignores=[]),'<guest-adf-input-export>','exec')
    scope={'adf_set_input_profile':'','setup':[]}
    exec(code,scope)
    assert not scope['setup']
    scope['adf_set_input_profile']=selected['MENU_ADF_SET_INPUT']
    exec(code,scope)
    assert scope['setup']==['export MENU_ADF_SET_INPUT=virtual-input-s0-v1']
    with pytest.raises(ValueError):
        menu_control.launcher.profile_environment({**env,'A7C2_ADF_SET_INPUT':backup.INPUT_PROFILE},natural_boot=False)
    for bad in ({**env,'A7C2_ADF_SET_INPUT':'wrong'},
                {**env,'A7C2_ADF_SET_INPUT':backup.INPUT_PROFILE,'A7C2_ADF_PROC_PATH':''}):
        with pytest.raises(ValueError):menu_control.launcher.profile_environment(bad,natural_boot=True)


def test_adf_set_input_prepare_rejects_without_build_or_output_work(tmp_path,monkeypatch):
    env={**required(tmp_path),'MENU_TCIN_DETECT':'virtual-inactive-v1',
         'MENU_DFS_SELECTOR':'virtual-selector-v1','MENU_VEF_PATH':'virtual-nomem-v1',
         'MENU_ADF_PROC_PATH':backup.ADF_PROFILE,'MENU_ADF_SET_INPUT':backup.INPUT_PROFILE,
         'MENU_AUDIO_BOOT_CONFIG':'1','MENU_PIN_REGISTRY':'1',
         'MENU_PIN_CONTROL_MEMORY':'1','MENU_PIN_CONNECTION':'cold'}
    def no_candidate(*args):raise AssertionError('invalid input profile reached build/filesystem work')
    monkeypatch.setattr(backup,'validate_build',no_candidate)
    for name,value in [('MENU_ADF_SET_INPUT','wrong'),('MENU_ADF_PROC_PATH','')]:
        with pytest.raises(ValueError,match='ADF set input'):
            backup.prepare_profile(HERE,{**env,name:value})
    for name in ('MENU_DFS_SELECTOR','MENU_TCIN_DETECT','MENU_CP_BACKGROUND',
                 'MENU_UDATE_DISTRIBUTION','MENU_TOUCH_PANEL','A7C2_BACKUP_SYNC'):
        with pytest.raises(ValueError):
            backup.prepare_profile(HERE,{k:v for k,v in env.items() if k!=name})


@pytest.mark.parametrize('profile',['',backup.INPUT_PROFILE])
def test_adf_set_input_receipt_retains_s0_task_failure_and_metadata_completion(profile):
    fields=backup.adf_set_input_profile_fields(profile)
    selected=bool(profile)
    assert fields['adf_set_input_profile']==(profile or None)
    for name,value in {
            'protocol':'AP0336-type0-input-config-S0-v1',
            'clock_policy':'virtual-source7-control-events-v1','clock_period_ns':1000000,
            'clock_generation':2,'clock_sequence_start':5,'clock_sequence_end':8,
            'engine_state':0,'ab_opcode':0xab,'ab_status':1,'aip_task_error':0x1004,
            'glee_callback_metadata':0,'completion_scope':'metadata-configuration-only',
            'kikilog_padding_policy':'virtual-zero-last2'}.items():
        assert fields['adf_set_input_'+name]==(value if selected else None)
    for name in ('original_cp_executed','hardware_verified','native_frequency_verified',
                 'original_event_identity_verified','pcm_verified','frames_verified',
                 'ap_consumed','capture_verified','clock_counter_reset'):
        assert fields['adf_set_input_'+name] is False
    with pytest.raises(ValueError):backup.adf_set_input_profile_fields('unknown')
    source=(HERE/'qemu-menu-probe.py').read_text()
    assert '**adf_set_input_profile_fields(adf_set_input_profile)' in source
    assert 'adf_set_input_profile_fields(adf_set_input_profile).items()' in source

