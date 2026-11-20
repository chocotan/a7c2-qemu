"""Native AP selects the real transport and leaves the caller's session alone."""
import importlib.util
import ctypes
import struct
import os
import runpy
import socket
from types import SimpleNamespace
from pathlib import Path

import pytest


def module():
    spec=importlib.util.spec_from_file_location('native_ap',Path(__file__).with_name('run-native-ap.py'))
    result=importlib.util.module_from_spec(spec);spec.loader.exec_module(result)
    return result


def test_clean_real_transport_plan_does_not_change_caller(monkeypatch,tmp_path):
    api=module();pair=tmp_path/'pair';pair.mkdir();binary=tmp_path/'qemu';binary.write_bytes(b'fixture')
    monkeypatch.setenv('MENU_VIRTUAL_CP_SENDER','1')
    monkeypatch.setenv('QEMU_CP_EDMA_DIRECT','1')
    monkeypatch.setenv('A7C2_HOST_SD','/dev/never-open')
    monkeypatch.setenv('A7C2_NATIVE_OBSERVER_BUILD', '/inherited/never-use')
    original=dict(os.environ)
    monkeypatch.setattr(api,'api',lambda:{
        'admit':lambda p,b:{'fixture':True},
        'environment':lambda side,p:{'QEMU_NATIVE_AP_CP_LINK':'virtual-native-ap-cp-link-v1',
            'QEMU_NATIVE_LINK_DIR':str(p),'QEMU_AP_CP_GPIO_SIDE':side}})
    command,environment,proof=api.plan(pair,binary,120)
    assert dict(os.environ)==original
    assert not {'MENU_VIRTUAL_CP_SENDER','QEMU_CP_EDMA_DIRECT','A7C2_HOST_SD'} & environment.keys()
    assert environment['MENU_PCIE_IF']=='1'
    assert environment['QEMU_UI_LIVE']=='1' and environment['QEMU_TIMEOUT_SECONDS']=='0'
    assert environment['QEMU_SYSTEM_DIR']==str(binary.parent)
    assert environment['MENU_SETTLE_SECONDS']=='120'
    assert 'MENU_VIRTUAL_UPM_PROFILE' not in environment
    assert 'MENU_NATIVE_CAPTURE_DIAGNOSTIC' not in environment
    assert 'A7C2_FSYS_ASYNC_OBSERVE' not in environment
    assert 'A7C2_NATIVE_OBSERVER_BUILD' not in environment
    assert 'QEMU_NATIVE_P1_SPI_COMPONENT' not in environment
    _, diagnostic, _ = api.plan(pair, binary, 120, virtual_upm=True, p1_spi_component=True)
    assert diagnostic['QEMU_NATIVE_P1_SPI_COMPONENT']=='virtual-p1-pl022-component-v1'
    assert diagnostic['MENU_VIRTUAL_UPM_PROFILE']=='diagnostic-v1'
    with pytest.raises(ValueError, match='boolean'):
        api.plan(pair, binary, 120, virtual_upm='1')
    assert '--load-ipc' in command and '--bootin' in command and '--bootall' in command
    assert '--headless-osd' not in command and '--dmm-service' not in command
    assert command[2].endswith('qemu-menu-probe.py') and proof=={'fixture':True}
    product=Path(__file__).resolve().parents[2]
    claim_command=runpy.run_path(str(product/'source/cp-boot/native-link.py'))['ap_probe_command']()
    assert command==claim_command


def test_capture_diagnostic_rejects_missing_short_or_symlink_card(monkeypatch, tmp_path):
    api = module()
    pair = tmp_path/'pair'
    pair.mkdir()
    binary = tmp_path/'qemu'
    binary.write_bytes(b'fixture')
    monkeypatch.setattr(api, 'api', lambda: {
        'admit': lambda p, b: {'fixture': True},
        'environment': lambda side, p: {},
    })
    with pytest.raises(ValueError, match='control socket'):
        api.plan(pair, binary, 120, capture_diagnostic=True)
    parent, child = socket.socketpair()
    try:
        child.set_inheritable(True)
        monkeypatch.setattr(api.os, 'getppid', lambda: os.getpid())
        with pytest.raises(ValueError, match='capture-seed'):
            api.plan(pair, binary, 120, capture_diagnostic=True, control_fd=child.fileno())
        card = pair/'capture-seed.img'
        card.write_bytes(b'short')
        with pytest.raises(ValueError, match='1GiB'):
            api.plan(pair, binary, 120, capture_diagnostic=True, control_fd=child.fileno())
        card.unlink()
        card.symlink_to(binary)
        with pytest.raises(ValueError, match='1GiB'):
            api.plan(pair, binary, 120, capture_diagnostic=True, control_fd=child.fileno())
        card.unlink()
        card.write_bytes(b'synthetic')
        original_lstat = type(card).lstat
        def synthetic_size(path, *args, **kwargs):
            info = original_lstat(path, *args, **kwargs)
            if path != card:
                return info
            return SimpleNamespace(st_mode=info.st_mode, st_uid=info.st_uid, st_nlink=1, st_size=1024**3)
        monkeypatch.setattr(type(card), 'lstat', synthetic_size)
        _, env, _ = api.plan(pair, binary, 120, capture_diagnostic=True, control_fd=child.fileno())
        assert env['A7C2_SD_IMAGE'] == str(card) and env['MENU_LIVE_APP_INPUT'] == '1'
        assert env['MENU_RM_FILE'] == env['A7C2_FSYS_ASYNC_OBSERVE'] == '1'
        assert env['MENU_CONTROL_FD'] == str(child.fileno())
        child.set_inheritable(False)
        with pytest.raises(ValueError, match='inheritable'):
            api.plan(pair, binary, 120, capture_diagnostic=True, control_fd=child.fileno())
    finally:
        parent.close()
        child.close()


def test_main_writes_claim_before_exec_and_never_runs_a_second_launcher(monkeypatch,tmp_path):
    api=module();pair=tmp_path/'pair';pair.mkdir();binary=tmp_path/'qemu';binary.write_bytes(b'fixture')
    command=['python3','-B','qemu-menu-probe.py','--initramfs','--bootin']
    environment={'QEMU_NATIVE_AP_CP_LINK':'virtual-native-ap-cp-link-v1'};calls=[]
    monkeypatch.setattr(api,'plan',lambda p,b,s,virtual_upm,capture,control_fd,p1_spi,observer_build:(command,environment,{'admitted':True}))
    monkeypatch.setattr(api,'api',lambda:{'create_ap_admission_claim':
        lambda p,b,c:calls.append(('claim',p,b,c))})
    class ExecRequested(Exception):pass
    def execve(path,argv,env):
        calls.append(('exec',path,argv,env))
        raise ExecRequested
    monkeypatch.setattr(api.os,'execve',execve)
    monkeypatch.setattr(api.os,'umask',lambda value:0o022)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(api.sys,'argv',['run-native-ap.py','--pair','pair','--binary','qemu'])
    with pytest.raises(ExecRequested):api.main()
    assert calls[0]==('claim',pair.resolve(),binary.resolve(),command)
    assert calls[1]==('exec',api.sys.executable,command,environment)


def test_explicit_observer_selection_keeps_fixed_claim_argv(monkeypatch, tmp_path):
    api = module()
    pair = tmp_path/'pair'
    pair.mkdir()
    binary = tmp_path/'qemu'
    binary.write_bytes(b'fixture')
    build = tmp_path/'source/build/diagnostic'
    monkeypatch.setattr(api, 'api', lambda: {
        'admit': lambda p, b: {'admitted': True}, 'environment': lambda side, p: {}})
    default_command, _, _ = api.plan(pair, binary, 120)
    checked = []
    def validate(value):
        checked.append(value)
        return {'build_directory': str(build)}
    monkeypatch.setattr(api.runpy, 'run_path', lambda path: {'validate_observer_build': validate})
    command, environment, _ = api.plan(pair, binary, 120, observer_build=build)
    assert command == default_command and checked == [build]
    assert environment['A7C2_NATIVE_OBSERVER_BUILD'] == str(build)


@pytest.mark.parametrize('capture', [False, True])
def test_main_derives_selected_archive_before_claim(monkeypatch, tmp_path, capture):
    api = module()
    pair, binary, build = tmp_path/'pair', tmp_path/'qemu', tmp_path/'build'
    pair.mkdir()
    binary.write_bytes(b'fixture')
    events = []
    command, environment = ['fixture'], {'fixture': '1'}
    monkeypatch.setattr(api, 'plan', lambda *args: (command, environment, {}))
    monkeypatch.setattr(api, 'api', lambda: {
        'create_ap_admission_claim': lambda *args: events.append('claim')})
    monkeypatch.setattr(api.runpy, 'run_path', lambda path: {
        'prepare': lambda p, b: events.append(('capture', p, b)),
        'prepare_observer': lambda p, b: events.append(('observer', p, b))})
    class Finished(Exception):
        pass
    def execute(*args):
        events.append('exec')
        raise Finished
    monkeypatch.setattr(api.os, 'execve', execute)
    monkeypatch.setattr(api.os, 'umask', lambda value: 0o022)
    argv = ['run-native-ap.py', '--pair', str(pair), '--binary', str(binary), '--observer-build', str(build)]
    if capture:
        argv.append('--capture-diagnostic')
    monkeypatch.setattr(api.sys, 'argv', argv)
    with pytest.raises(Finished):
        api.main()
    assert events == [('capture' if capture else 'observer', pair, build), 'claim', 'exec']


@pytest.mark.parametrize('profile,expected',[(None,6),('virtual-native-ap-cp-link-v1',8),('unknown',6)])
def test_generated_linux_ddr_fits_existing_backing_and_peer_view(monkeypatch,profile,expected):
    product=Path(__file__).resolve().parents[2]
    source=(product/'runtime/analysis/qemu-kernel-probe.sh').read_text()
    assignments=[line.strip() for line in source.splitlines() if line.strip().startswith('ddr_size =')]
    assert len(assignments)==1
    if profile is None:monkeypatch.delenv('QEMU_NATIVE_AP_CP_LINK',raising=False)
    else:monkeypatch.setenv('QEMU_NATIVE_AP_CP_LINK',profile)
    values={'os':os};exec(compile(assignments[0],'<real-DTB-ddr-size>','exec'),values)
    link=runpy.run_path(str(Path(__file__).with_name('native-link.py')))
    size=values['ddr_size']
    assert size==expected*link['GIB']
    assert size<=link['CP_AP_VIEW_SIZE']
    assert link['AP_DDR_OFFSET']+size<=link['AP_SIZE']
    assert 0x504000000<0x580000000<=0x400000000+size


def test_native_qmp_quit_and_unavailable_teardown_are_guarded():
    product=Path(__file__).resolve().parents[2]
    source=(product/'runtime/analysis/qemu-menu-probe.py').read_text()
    wrapper=source.split('def qmp(name,arguments=None):',1)[1].split('qmp("qmp_capabilities")',1)[0]
    assert "with_ap_control_lock" in wrapper and "qmp_unlocked(name,arguments)" in wrapper
    unlocked=source.split('def qmp_unlocked(name, arguments=None):',1)[1].split('def qmp(name,arguments=None):',1)[0]
    marker="native_api['_write_json'](owner_fd,'qmp-quit.json',receipt)"
    assert marker in unlocked
    assert unlocked.index(marker) < unlocked.index('qmp_transaction(proc,stream,name,arguments)')
    teardown=source[source.rfind('if proc.poll() is None:'):]
    assert teardown.index('if qmp is None:') < teardown.index("qmp('quit')")
    assert 'QMP session never established; retain VM and lease' in teardown


@pytest.mark.parametrize('native_pair,expected',[(None,25),(Path('/owned/native-pair'),120)])
def test_native_large_cpio_shell_budget_is_isolated(native_pair,expected):
    product=Path(__file__).resolve().parents[2]
    source=(product/'runtime/analysis/qemu-menu-probe.py').read_text()
    lines=[line.strip() for line in source.splitlines() if line.strip().startswith('deadline = time.monotonic() + (120 if native_pair')]
    assert len(lines)==1
    values={'native_pair':native_pair,'time':SimpleNamespace(monotonic=lambda:1000)}
    exec(compile(lines[0],'<real-native-shell-budget>','exec'),values)
    assert values['deadline']==1000+expected


def native_iomap_board():
    product=Path(__file__).resolve().parents[2]
    library=product/'runtime/sources/qemu-tools/usr/lib/libfdt.so.1'
    fdt=ctypes.CDLL(str(library) if library.is_file() else 'libfdt.so.1')
    fdt.fdt_getprop.restype=ctypes.c_void_p
    buffer=ctypes.create_string_buffer(16384)
    assert fdt.fdt_create_empty_tree(buffer,len(buffer))==0
    for name,properties in (
        (b'memory', {b'reg':struct.pack('>QQ',0x400000000,0x200000000)}),
        (b'chosen', {b'bootargs':b'rdinit=/init earlycon\0'}),
        (b'sony-gic-alias', {b'phys':struct.pack('>Q',0x08000000),b'virt':struct.pack('>Q',0xfffffffff13a1000)}),
    ):
        node=fdt.fdt_add_subnode(buffer,0,name);assert node>=0
        for field,value in properties.items():assert fdt.fdt_setprop(buffer,node,field,value,len(value))==0
    return fdt,buffer,runpy.run_path(str(product/'runtime/analysis/native_pcie_board.py'))


def iomap_property(fdt,buffer,path,field):
    node=fdt.fdt_path_offset(buffer,path.encode());assert node>=0
    length=ctypes.c_int();value=fdt.fdt_getprop(buffer,node,field,ctypes.byref(length))
    assert value and length.value>=0
    return ctypes.string_at(value,length.value)


def test_real_fdt_native_transport_aliases_only_cover_implemented_devices():
    fdt,buffer,api=native_iomap_board()
    kept={(path,field):iomap_property(fdt,buffer,path,field) for path,field in
          (('/memory',b'reg'),('/chosen',b'bootargs'),('/sony-gic-alias',b'phys'),('/sony-gic-alias',b'virt'))}
    api['add_iomaps'](fdt,buffer,api['PROFILE'])
    for name,physical,size in api['WINDOWS']:
        path='/'+name
        assert iomap_property(fdt,buffer,path,b'device_type')==b'iomap\0'
        assert iomap_property(fdt,buffer,path,b'phys')==struct.pack('>Q',physical)
        assert iomap_property(fdt,buffer,path,b'virt')==struct.pack('>Q',0xffffffff00000000|physical)
        assert iomap_property(fdt,buffer,path,b'size')==struct.pack('>Q',size)
        assert iomap_property(fdt,buffer,path,b'memtype')==struct.pack('>I',1)
    assert [(hex(p),n) for _,p,n in api['WINDOWS']]==[('0xf7300000',4096),('0xf7380000',8192)]
    for (path,field),value in kept.items():assert iomap_property(fdt,buffer,path,field)==value
    snapshot=buffer.raw
    with pytest.raises(ValueError,match='already exists'):api['add_iomaps'](fdt,buffer,api['PROFILE'])
    assert buffer.raw==snapshot


@pytest.mark.parametrize('profile',[None,'','unknown'])
def test_native_iomap_profile_rejected_before_any_dtb_change(profile):
    fdt,buffer,api=native_iomap_board();before=buffer.raw
    with pytest.raises(ValueError,match='exact native'):api['add_iomaps'](fdt,buffer,profile)
    assert buffer.raw==before


@pytest.mark.parametrize('seconds',[True,False,0,-1,3601,1.5,'120'])
def test_invalid_window_fails_before_input_or_device_access(monkeypatch,seconds):
    api=module()
    def forbidden():
        raise AssertionError('must reject before admission')
    monkeypatch.setattr(api,'api',forbidden)
    with pytest.raises(ValueError,match='seconds'):
        api.plan('/nonexistent','/nonexistent',seconds)
