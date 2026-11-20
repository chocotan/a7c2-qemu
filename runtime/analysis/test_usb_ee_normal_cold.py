"""Explicit EE NormalWake cold observer wiring: host build/gating only.

No VM, no disk and no private input ever enters the public tree; the enabled
build below consumes a clearly labeled synthetic host fixture, never a real
prepared private header. Nothing here proves original AP consumption.
"""
import fcntl
import importlib.util
import json
import os
from pathlib import Path
import pytest
import subprocess
from types import SimpleNamespace
import sony_usb_device as device

USB=Path(device.PRODUCT)/'source/usb-device'
ROOT=Path(device.PRODUCT).parents[1]
RESEARCH=ROOT/'final/a7c2-re/report/2026-10-17-qemu-full-system'

SYNTHETIC_INPUT='''/* Host-test synthetic input; never a private launch input. */
#include "ee-normal-wake-cold.h"
static const uint8_t ee_nwc_prepared_rows[128]={0};
static const struct ee_nwc_assets ee_nwc_prepared_assets={
 .pid=0,.generation=UINT64_C(7),
 .backup_sha256=EE_NWC_BACKUP_SHA,.cp_bank_sha256=EE_NWC_BANK_SHA,.cp_sha256=EE_NWC_CP_SHA,
 .cp_bank_offset=970752,.verified=1,.keymap_group=1,
 .rows=ee_nwc_prepared_rows,.rows_bytes=sizeof ee_nwc_prepared_rows,
 .backup_00030162={0},.policy_00030a01={0},.config_0092001c={0}};
static const uint8_t ee_cold_adc[48]={0};
static const uint8_t ee_cold_state[32]={0};
static const uint8_t ee_cold_force=0,ee_cold_be9=0;
static const char ee_cold_input_sha256[]="host-fixture-only";
static const char ee_cold_model_sha256[]="host-fixture-only";
#define EE_COLD_ADMISSION_SOURCE EE_NWC_CALLBACK
#define EE_COLD_DIAGNOSTICS 0
#define EE_COLD_ALLOCATION_LOG_COMMIT_VERSION 1
'''


@pytest.fixture
def outside_product(tmp_path):
    """Synthetic inputs stay in the project test root, never in the product tree."""
    base=tmp_path.resolve()
    if base==Path(device.PRODUCT) or base.is_relative_to(device.PRODUCT) or base.is_relative_to('/tmp'):
        pytest.fail('pytest basetemp must be project-local and outside the product tree')
    scratch=base/'external-input';scratch.mkdir(mode=0o700)
    return scratch


def symbols(path,names):
    text=subprocess.run(['readelf','-Ws',str(path)],capture_output=True,text=True,check=True).stdout
    return {name for name in names if (' '+name+'\n') in text}


def test_private_tool_temp_rejects_symlink_and_bad_receipt(tmp_path,monkeypatch):
    with pytest.raises(ValueError,match='Invalid observer private input receipt'):
        device.verify_private_libraries((tmp_path,{'base_initramfs_sha256':None},[],''))
    monkeypatch.setattr(device,'verify_private_libraries',lambda _value:None)
    target=tmp_path/'other';target.mkdir(mode=0o700)
    (tmp_path/'tool-tmp').symlink_to(target,target_is_directory=True)
    with pytest.raises(ValueError,match='temporary directory is not private'):
        with device.private_tool_environment((tmp_path,{},[],'')):
            pytest.fail('symlinked directory must not be admitted')


def test_pinned_tool_tmp_ignores_path_replacement(tmp_path):
    parent=tmp_path/'private';parent.mkdir(mode=0o700)
    other=tmp_path/'other';other.mkdir(mode=0o700)
    with device.pinned_tool_environment(parent,'tool-tmp') as (environment,directory_fd):
        assert environment['TMPDIR']=='/proc/self/fd/'+str(directory_fd)
        directory=parent/'tool-tmp';saved=parent/'saved-tool-tmp'
        directory.rename(saved);directory.symlink_to(other,target_is_directory=True)
        fd=os.open('marker',os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600,dir_fd=directory_fd)
        with os.fdopen(fd,'wb') as output:output.write(b'owned')
        assert (saved/'marker').read_bytes()==b'owned' and not (other/'marker').exists()
    with pytest.raises(OSError):os.fstat(directory_fd)


def test_unselected_usb_never_snapshots_or_compiles(tmp_path,monkeypatch):
    monkeypatch.setattr(device.subprocess,'run',lambda *_a,**_k: pytest.fail('compiler must not run'))
    assert device.prepare_observer({},tmp_path)=={}
    assert not list(tmp_path.iterdir())


def test_usb_observer_snapshot_rejection_precedes_compiler(tmp_path,monkeypatch):
    fake=SimpleNamespace(snapshot_libraries=lambda *_a: (_ for _ in ()).throw(ValueError('snapshot rejected')))
    spec=SimpleNamespace(loader=SimpleNamespace(exec_module=lambda _module: None))
    monkeypatch.setattr(device.importlib.util,'spec_from_file_location',lambda *_a:spec)
    monkeypatch.setattr(device.importlib.util,'module_from_spec',lambda _spec:fake)
    monkeypatch.setattr(device.subprocess,'run',lambda *_a,**_k: pytest.fail('compiler must not run'))
    with pytest.raises(ValueError,match='snapshot rejected'):
        device.prepare_observer({'A7C2_SONY_USB_DEVICE':device.PROFILE},tmp_path)
    assert (tmp_path/'observer-inputs-intent.json').is_file()


@pytest.mark.parametrize('replacement',['content','parent'])
def test_usb_observer_sealed_libraries_resist_mutation(tmp_path,monkeypatch,replacement):
    names=('libc-2.25.so','libdl-2.25.so','libpthread-2.25.so','ld-2.25.so')
    def snapshot(_analysis,private):
        library=private/'lib';library.mkdir(mode=0o700)
        rows={}
        for name in names:
            path=library/name;path.write_bytes(name.encode());path.chmod(0o600)
            rows['lib/'+name]={'sha256':device.sha(path)}
        receipt={'schema':'a7c2-observer-private-libraries-v1','physical_compatible':False,
                 'base_initramfs_sha256':'a'*64,'libraries':rows}
        proof=private/'library-inputs.json';proof.write_text(json.dumps(receipt));proof.chmod(0o600)
        return receipt
    fake=SimpleNamespace(LIBRARIES=names,snapshot_libraries=snapshot)
    spec=SimpleNamespace(loader=SimpleNamespace(exec_module=lambda _module: None))
    monkeypatch.setattr(device.importlib.util,'spec_from_file_location',lambda *_a:spec)
    monkeypatch.setattr(device.importlib.util,'module_from_spec',lambda _spec:fake)
    def compiler(command,**kwargs):
        passed=kwargs['pass_fds'];assert len(passed)==5
        descriptors=passed[:4];temp_fd=passed[4]
        assert kwargs['env']['TMPDIR']=='/proc/self/fd/'+str(temp_fd)
        assert os.fstat(temp_fd).st_ino==(tmp_path/'observer-inputs/tool-tmp').stat().st_ino
        for name,descriptor in zip(names,descriptors):
            assert '/proc/self/fd/'+str(descriptor) in command
            assert os.pread(descriptor,1024,0)==name.encode()
            seals=fcntl.F_SEAL_SEAL|fcntl.F_SEAL_SHRINK|fcntl.F_SEAL_GROW|fcntl.F_SEAL_WRITE
            assert fcntl.fcntl(descriptor,fcntl.F_GET_SEALS)&seals==seals
            with pytest.raises(PermissionError):os.pwrite(descriptor,b'x',0)
            with pytest.raises(PermissionError):os.ftruncate(descriptor,1)
        assert all(str(device.ANALYSIS/'menu-root/lib'/name) not in command for name in names)
        directory=tmp_path/'observer-inputs/lib'
        if replacement=='content':
            (directory/names[0]).write_bytes(b'tampered')
        else:
            saved=directory.with_name('original-lib');alternate=directory.with_name('alternate-lib')
            directory.rename(saved);directory.mkdir(mode=0o700)
            for name in names:(directory/name).write_bytes(b'substituted')
            assert all(os.pread(fd,1024,0)==name.encode() for name,fd in zip(names,descriptors))
            directory.rename(alternate);saved.rename(directory)
            Path(command[-1]).write_bytes(b'synthetic observer')
        return SimpleNamespace(returncode=0,stdout=b'',stderr=b'')
    monkeypatch.setattr(device.subprocess,'run',compiler)
    if replacement=='content':
        with pytest.raises(ValueError,match='private library changed'):
            device.prepare_observer({'A7C2_SONY_USB_DEVICE':device.PROFILE},tmp_path)
    else:
        assert 'usb-start-observe.so' in device.prepare_observer({'A7C2_SONY_USB_DEVICE':device.PROFILE},tmp_path)
    assert (tmp_path/'observer-inputs-proof.json').is_file()


def test_live_usb_snapshot_stays_outside_analysis(tmp_path,monkeypatch):
    product=tmp_path/'product';runtime=product/'runtime';analysis=runtime/'analysis'
    payload=analysis/'menu-runs/run-1/build/payload';payload.mkdir(parents=True)
    source=product/'source/usb-device';source.mkdir(parents=True)
    for name in ('usb-start-observe.c','usb-msc-sender.inc','usb-resources-observe.inc','usb-start-observe.map'):
        (source/name).write_bytes(b'synthetic source')
    names=('libc-2.25.so','libdl-2.25.so','libpthread-2.25.so','ld-2.25.so')
    def snapshot(_analysis,private):
        assert _analysis==analysis and not private.is_relative_to(analysis)
        library=private/'lib';library.mkdir(mode=0o700);rows={}
        for name in names:
            path=library/name;path.write_bytes(name.encode());path.chmod(0o600)
            rows['lib/'+name]={'sha256':device.sha(path)}
        receipt={'schema':'a7c2-observer-private-libraries-v1','physical_compatible':False,
                 'base_initramfs_sha256':'a'*64,'libraries':rows}
        proof=private/'library-inputs.json';proof.write_text(json.dumps(receipt));proof.chmod(0o600)
        return receipt
    fake=SimpleNamespace(LIBRARIES=names,snapshot_libraries=snapshot)
    spec=SimpleNamespace(loader=SimpleNamespace(exec_module=lambda _module: None))
    monkeypatch.setattr(device,'ANALYSIS',analysis)
    monkeypatch.setattr(device,'PRODUCT',product)
    monkeypatch.setattr(device.importlib.util,'spec_from_file_location',lambda *_a:spec)
    monkeypatch.setattr(device.importlib.util,'module_from_spec',lambda _spec:fake)
    def compiler(command,**_kwargs):
        Path(command[-1]).write_bytes(b'synthetic observer')
        return SimpleNamespace(returncode=0,stdout=b'',stderr=b'')
    monkeypatch.setattr(device.subprocess,'run',compiler)
    helpers=device.prepare_observer({'A7C2_SONY_USB_DEVICE':device.PROFILE},payload)
    proof=json.loads((payload/'observer-inputs-proof.json').read_text())
    private=Path(proof['private_input_receipt']).parent
    assert private.is_relative_to(runtime/'observer-private-inputs') and not private.is_relative_to(analysis)
    assert private.stat().st_mode & 0o777==0o700
    assert proof['sha256']==device.sha(private/'library-inputs.json')
    assert set(helpers)=={'usb-start-observe.so'}


def test_default_off_build_links_no_ee_code(tmp_path):
    helpers=device.prepare_observer({'A7C2_SONY_USB_DEVICE':device.PROFILE},tmp_path)
    observer=helpers['usb-start-observe.so']
    assert 'usb-ee-native-pins.h' not in helpers
    image=observer.read_bytes()
    assert b'ee-normal-wake-cold-functional-v1' not in image
    assert b'native_allocation_log_commit_required=1' not in image
    assert not symbols(observer,('ee_nwc_create','ee_adc_consume','ee_cold_wait'))
    assert not list(tmp_path.glob('usb-ee-native-pins.h'))
    private=tmp_path/'observer-inputs'
    receipt=json.loads((private/'library-inputs.json').read_text())
    assert receipt['schema']=='a7c2-observer-private-libraries-v1'
    assert receipt['physical_compatible'] is False
    assert set(receipt['libraries'])=={'lib/'+name for name in
            ('libc-2.25.so','libdl-2.25.so','libpthread-2.25.so','ld-2.25.so')}
    for name,row in receipt['libraries'].items():
        copied=private/name
        assert copied.stat().st_mode & 0o777==0o600 and copied.stat().st_nlink==1
        assert device.sha(copied)==row['sha256']==device.sha(row['source'])
    import original_cold_boot as cold
    ordered=[private/'lib'/name for name in ('libc-2.25.so','libdl-2.25.so','libpthread-2.25.so','ld-2.25.so')]
    audit=cold.build_audit(tmp_path,tmp_path,(private,receipt,ordered,device.sha(private/'library-inputs.json')))
    assert audit.read_bytes()[:6]==b'\x7fELF\x02\x01'


def test_ee_cold_profile_fails_closed_without_external_private_input(tmp_path,monkeypatch):
    header=tmp_path/'input.h';header.write_text(SYNTHETIC_INPUT)
    profile={'A7C2_SONY_USB_DEVICE':device.PROFILE}
    for current in ({**profile,'A7C2_USB_EE_NORMAL_COLD':'1'},
                    {**profile,'A7C2_USB_EE_NORMAL_COLD':'2','A7C2_USB_EE_NORMAL_COLD_INPUT':str(header)},
                    {**profile,'A7C2_USB_EE_NORMAL_COLD':'1','A7C2_USB_EE_NORMAL_COLD_INPUT':str(tmp_path/'absent.h')}):
        with pytest.raises(ValueError):device.prepare_observer(current,tmp_path/'gate')
    # A declared input without the explicit profile and an in-tree input are both refused.
    with pytest.raises(ValueError,match='without the explicit profile'):
        device.prepare_observer({**profile,'A7C2_USB_EE_NORMAL_COLD_INPUT':str(header)},tmp_path/'gate')
    product=tmp_path/'synthetic-product';product.mkdir(mode=0o700)
    inside=product/'ee-cold-private-input.h';inside.write_text(SYNTHETIC_INPUT)
    with monkeypatch.context() as patch:
        patch.setattr(device,'PRODUCT',product)
        with pytest.raises(ValueError,match='outside the public product tree'):
            device.prepare_observer({**profile,'A7C2_USB_EE_NORMAL_COLD':'1','A7C2_USB_EE_NORMAL_COLD_INPUT':str(inside)},tmp_path/'gate')
    link=tmp_path/'symlink-input.h';link.symlink_to(inside)
    with pytest.raises(ValueError,match='regular non-symlink'):
        device.prepare_observer({**profile,'A7C2_USB_EE_NORMAL_COLD':'1','A7C2_USB_EE_NORMAL_COLD_INPUT':str(link)},tmp_path/'gate')


def test_ee_cold_private_input_rejects_unsafe_identity(tmp_path, monkeypatch):
    header=tmp_path/'input.h';header.write_text(SYNTHETIC_INPUT);header.chmod(0o644)
    profile={'A7C2_SONY_USB_DEVICE':device.PROFILE,'A7C2_USB_EE_NORMAL_COLD':'1',
             'A7C2_USB_EE_NORMAL_COLD_INPUT':str(header)}
    monkeypatch.setattr(device,'ee_native_pins',lambda _payload: pytest.fail('no compiler input admitted'))
    with pytest.raises(ValueError,match='single-link 0600'):
        device.ee_normal_cold(profile,tmp_path)
    header.chmod(0o600)
    alias=tmp_path/'alias.h';os.link(header,alias)
    with pytest.raises(ValueError,match='single-link 0600'):
        device.ee_normal_cold(profile,tmp_path)
    link=tmp_path/'linked';link.symlink_to(tmp_path,target_is_directory=True)
    with pytest.raises(ValueError,match='non-symlink'):
        device.ee_normal_cold({**profile,'A7C2_USB_EE_NORMAL_COLD_INPUT':str(link/'input.h')},tmp_path)


@pytest.mark.parametrize('replacement',['content','parent','pins'])
def test_ee_cold_header_snapshot_survives_concurrent_change(tmp_path,monkeypatch,replacement):
    directory=tmp_path/'header-dir';directory.mkdir(mode=0o700)
    header=directory/'input.h';header.write_text(SYNTHETIC_INPUT);header.chmod(0o600)
    payload=tmp_path/'payload';payload.mkdir(mode=0o700)
    def pins(directory):
        path=directory/'usb-ee-native-pins.h';data=b'/* synthetic */'
        path.write_bytes(data);path.chmod(0o600);return path,data
    monkeypatch.setattr(device,'ee_native_pins',pins)
    names=('libc-2.25.so','libdl-2.25.so','libpthread-2.25.so','ld-2.25.so')
    def snapshot(_analysis,private):
        library=private/'lib';library.mkdir(mode=0o700);rows={}
        for name in names:
            path=library/name;path.write_bytes(name.encode());path.chmod(0o600)
            rows['lib/'+name]={'sha256':device.sha(path)}
        receipt={'schema':'a7c2-observer-private-libraries-v1','physical_compatible':False,
                 'base_initramfs_sha256':'a'*64,'libraries':rows}
        proof=private/'library-inputs.json';proof.write_text(json.dumps(receipt));proof.chmod(0o600)
        return receipt
    fake=SimpleNamespace(LIBRARIES=names,snapshot_libraries=snapshot)
    spec=SimpleNamespace(loader=SimpleNamespace(exec_module=lambda _module: None))
    monkeypatch.setattr(device.importlib.util,'spec_from_file_location',lambda *_a:spec)
    monkeypatch.setattr(device.importlib.util,'module_from_spec',lambda _spec:fake)
    observed=[]
    def compiler(command,**kwargs):
        descriptor,pins_descriptor=kwargs['pass_fds'][-2:];observed.extend((descriptor,pins_descriptor))
        assert len(kwargs['pass_fds'])==7
        assert '-DUSB_EE_NORMAL_COLD_INPUT="/proc/self/fd/'+str(descriptor)+'"' in command
        assert '-DUSB_EE_NATIVE_INPUT="/proc/self/fd/'+str(pins_descriptor)+'"' in command
        seals=fcntl.F_SEAL_SEAL|fcntl.F_SEAL_SHRINK|fcntl.F_SEAL_GROW|fcntl.F_SEAL_WRITE
        for fd in (descriptor,pins_descriptor):
            assert fcntl.fcntl(fd,fcntl.F_GET_SEALS)&seals==seals
            with pytest.raises(PermissionError):os.pwrite(fd,b'x',0)
            with pytest.raises(PermissionError):os.ftruncate(fd,1)
        assert os.pread(pins_descriptor,1024,0)==b'/* synthetic */'
        os.lseek(descriptor,0,os.SEEK_SET)
        assert os.read(descriptor,1024**2)==SYNTHETIC_INPUT.encode()
        if replacement=='content':
            header.write_text(SYNTHETIC_INPUT+'/* changed */\n')
        elif replacement=='pins':
            (payload/'usb-ee-native-pins.h').write_bytes(b'/* changed */')
        else:
            saved=tmp_path/'header-original';alternate=tmp_path/'header-alternate'
            directory.rename(saved);directory.mkdir(mode=0o700)
            header.write_text('/* substituted input */');header.chmod(0o600)
            os.lseek(descriptor,0,os.SEEK_SET)
            assert os.read(descriptor,1024**2)==SYNTHETIC_INPUT.encode()
            directory.rename(alternate);saved.rename(directory)
            Path(command[-1]).write_bytes(b'synthetic observer')
        return SimpleNamespace(returncode=0,stdout=b'',stderr=b'')
    monkeypatch.setattr(device.subprocess,'run',compiler)
    profile={'A7C2_SONY_USB_DEVICE':device.PROFILE,'A7C2_USB_EE_NORMAL_COLD':'1',
             'A7C2_USB_EE_NORMAL_COLD_INPUT':str(header)}
    if replacement in ('content','pins'):
        reason='private input changed' if replacement=='content' else 'native pins changed'
        with pytest.raises(ValueError,match=reason):device.prepare_observer(profile,payload)
    else:
        assert 'usb-start-observe.so' in device.prepare_observer(profile,payload)
    assert len(observed)==2
    for fd in observed:
        with pytest.raises(OSError):os.fstat(fd)


def test_ee_cold_enabled_build_binds_input_path_and_links_symbols(tmp_path,outside_product):
    header=outside_product/'input.h';header.write_text(SYNTHETIC_INPUT);header.chmod(0o600)
    payload=tmp_path/'payload';payload.mkdir(exist_ok=True)
    helpers=device.prepare_observer({'A7C2_SONY_USB_DEVICE':device.PROFILE,'A7C2_USB_EE_NORMAL_COLD':'1',
                                     'A7C2_USB_EE_NORMAL_COLD_INPUT':str(header)},payload)
    observer=helpers['usb-start-observe.so'];pins=helpers['usb-ee-native-pins.h']
    assert observer.is_file() and pins.is_file()
    image=observer.read_bytes()
    assert b'ee-normal-wake-cold-functional-v1' in image
    assert b'native_allocation_log_commit_required=1 native_allocation_log_commit_version=1' in image
    assert image[:6]==b'\x7fELF\x02\x01' and image[18:20]==b'\xb7\x00'
    # ee_nwc_*/ee_adc_* are the linked global service entry points; the static
    # adapter helpers (e.g. ee_cold_wait) are inlined at -O2 and need no symbol.
    assert {'ee_nwc_create','ee_nwc_destroy','ee_adc_consume'} <= symbols(observer,('ee_nwc_create','ee_nwc_destroy','ee_adc_consume','ee_cold_wait'))
    # The pins header binds the actual product native forwarder, not a fixture value.
    native=device.ANALYSIS/'menu-observe.so'
    assert ('"'+device.sha(native)+'"') in pins.read_text() and 'osal_free_msg' in pins.read_text()
    # A tampered synthetic contract marker is refused before any compiler runs.
    header.write_text(SYNTHETIC_INPUT.replace('#define EE_COLD_ALLOCATION_LOG_COMMIT_VERSION 1','#define EE_COLD_ALLOCATION_LOG_COMMIT_VERSION 2'))
    with pytest.raises(ValueError,match='hash-bound adapter contract'):
        device.prepare_observer({'A7C2_SONY_USB_DEVICE':device.PROFILE,'A7C2_USB_EE_NORMAL_COLD':'1',
                                 'A7C2_USB_EE_NORMAL_COLD_INPUT':str(header)},tmp_path/'refused')


def test_ee_observer_modes_are_mutually_exclusive(tmp_path):
    """clang AArch64 syntax check only; the source #error fires before any input is read."""
    result=subprocess.run(['clang','--target=aarch64-linux-gnu','--sysroot=/usr/aarch64-linux-gnu','-fsyntax-only',
                           '-DUSB_EE_ZERO_OBSERVER=1','-DUSB_EE_NORMAL_COLD=1',str(USB/'usb-start-observe.c')],
                          capture_output=True,text=True)
    assert result.returncode!=0 and 'mutually exclusive' in result.stderr


def test_source_origins_records_research_lineage():
    entry=json.loads((Path(device.PRODUCT)/'SOURCE-ORIGINS.json').read_text()).get('ee_normal_cold_observer_wiring_20261110')
    if entry is None:pytest.fail('SOURCE-ORIGINS lacks the EE cold wiring entry')
    if not RESEARCH.is_dir():pytest.skip('Research tree absent in this checkout')
    files=entry['files']
    for name,record in files.items():
        origin=ROOT/record['source']
        assert origin.is_file() and device.sha(origin)==record['original_sha256']
        product=USB/name
        assert product.is_file() and device.sha(product)==record['sha256']
        assert record.get('adapted') or device.sha(product)==record['original_sha256']
    assert entry['profile']==device.EE_COLD_MODE
    assert entry['default_off'] is True and entry['private_inputs_in_public_tree'] is False
    assert entry['original_ap_consumption_verified'] is False
