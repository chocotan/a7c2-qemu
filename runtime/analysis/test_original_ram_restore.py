"""Host-only RAM transport/contract tests; no QEMU or firmware execution."""
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import runpy
import socket

import pytest

import original_ram_restore as ram


PAYLOAD = ram.MAGIC + bytes(range(256))*4096


def fake_qmp(outgoing, consumed):
    link = None
    def call(command, arguments=None, pass_fd=None):
        nonlocal link
        if command == 'getfd':
            assert pass_fd is not None
            link = socket.socket(fileno=os.dup(pass_fd))
            link.setblocking(True)
        elif command == 'migrate':
            link.sendall(PAYLOAD)
            link.shutdown(socket.SHUT_WR)
        elif command == 'migrate-incoming':
            while data := link.recv(65536):
                consumed.extend(data)
        elif command == 'query-migrate':
            return {'return': {'status': 'completed'}}
        elif command == 'query-status':
            return {'return': {'status': 'postmigrate' if outgoing else 'paused', 'running': False}}
        return {'return': {}}
    return call, lambda: link.close()


def test_fd_transport_actually_writes_and_reads_the_qevm_stream(tmp_path):
    outgoing = tmp_path/'outgoing.qevm'
    call, close = fake_qmp(True, bytearray())
    try:
        result = ram.transfer(call, outgoing, outgoing=True)
        assert result['completed'] and outgoing.read_bytes() == PAYLOAD
        assert result['stream']['sha256'] == hashlib.sha256(PAYLOAD).hexdigest()
    finally:
        close()
    consumed = bytearray()
    call, close = fake_qmp(False, consumed)
    try:
        result = ram.transfer(call, outgoing, outgoing=False)
        assert result['completed'] and consumed == PAYLOAD
    finally:
        close()


def test_identity_requires_same_parseable_guest_fields():
    raw = (b'A7C2_RAM_ID_BEGIN\r\n12345678-1234-1234-1234-123456789abc\r\n'
           b'27.63 12.00\r\nA7C2_RAM_ID_END\r\n')
    assert ram._identity(raw) == {'boot_id': '12345678-1234-1234-1234-123456789abc',
                                  'uptime_seconds': 27.63}
    for bad in (raw.replace(b'27.63', b'invalid'), raw.replace(b'A7C2_RAM_ID_END', b'missing')):
        with pytest.raises(ValueError):
            ram._identity(bad)


def test_restored_storage_thaw_requires_actual_zero_state(tmp_path):
    raw = b'A7C2_RAM_THAW_BEGIN\r\n0 0\r\nA7C2_RAM_THAW_END\r\n'
    result = ram._thaw(lambda command: raw, tmp_path)
    assert result['state'] == result['count'] == 0
    assert (tmp_path/'ram-restored-thaw.raw').read_bytes() == raw
    with pytest.raises(ValueError, match='did not thaw'):
        ram._thaw(lambda command: raw.replace(b'0 0', b'1 19'), tmp_path)


def test_capture_receipt_binds_stream_disk_and_guest_identity(tmp_path):
    stream = tmp_path/'snapshot.qevm';stream.write_bytes(PAYLOAD);stream.chmod(0o600)
    instance = tmp_path/'instance';instance.mkdir()
    disk = instance/'camera.emmc';disk.write_bytes(b'virtual disk content')
    fd = os.open(disk, os.O_RDWR)
    try:
        leased = {'fd': fd, 'path': instance}
        built = {'ram0_sha256': 'a'*64, 'kernel_sha256': 'b'*64}
        contract = {'schema': 'a7c2-original-ram-capture-v1',
                    'stream_bytes': len(PAYLOAD), 'stream_sha256': hashlib.sha256(PAYLOAD).hexdigest(),
                    'disk': ram._disk(leased), 'instance': str(instance),
                    'ram0_sha256': built['ram0_sha256'], 'kernel_sha256': built['kernel_sha256'],
                    'qemu_sha256': 'c'*64, 'migration': {'completed': True},
                    'original_ap_retained_verified': False, 'sony_wbi_resume_executed': False,
                    'full_boot_verified': False, 'capture_verified': False}
        ram.receipt_path(stream).write_text(json.dumps(contract))
        assert ram.load_capture(stream, leased, built, 'c'*64) == contract
        with pytest.raises(ValueError, match='QEMU identity'):
            ram.load_capture(stream, leased, built, 'd'*64)
        with stream.open('r+b') as changed:
            changed.seek(len(ram.MAGIC));changed.write(b'X')
        with pytest.raises(ValueError, match='stream differs'):
            ram.load_capture(stream, leased, built, 'c'*64)
    finally:
        os.close(fd)


def test_persistent_stage_enables_migration_only_for_explicit_ram_session(tmp_path):
    source = tmp_path/'qemu';board = source/'hw/arm/virt.c';board.parent.mkdir(parents=True)
    board.write_text('static void machvirt_init(MachineState *machine)\n{\n}\n')
    api = runpy.run_path(str(Path(__file__).resolve().parents[2]/'source/persistent-flash/stage.py'))
    result = api['stage'](source)
    text = board.read_text()
    assert result['default_enabled'] is False
    assert 'qdev_prop_set_bit(pf, "retained-state", pf_retained != NULL);' in text
    assert 'invalid retained-state flag/profile' in text
    assert 'bool pf_any = pf_profile != NULL || pf_retained != NULL;' in text


def test_ram_device_stage_preserves_three_state_owners(tmp_path, monkeypatch):
    fixtures = {
        'hw/timer/sony_hwtimer.c': b'''#include "qemu/osdep.h"
    int64_t epoch;
    uint32_t count, control, compare;
        qemu_irq_raise(s->irq);
            qemu_irq_lower(s->irq);
            qemu_irq_lower(s->irq);
        break;
    case 8: s->compare = value; break;
static void timer_class_init(
    DEVICE_CLASS(klass)->realize = timer_realize;
''',
        'hw/misc/sony_spacc_stub.c': b'''#include "qemu/osdep.h"
    uint32_t *ram;
    s->ram = g_malloc0(0x40000);
static void spacc_class_init(
    dc->realize = spacc_realize;
''',
        'hw/input/sony-ui-input.c': b'''#include "qemu/osdep.h"
static void sony_input_class_init(
    dc->realize = sony_input_realize;
''',
    }
    api = runpy.run_path(str(Path(__file__).resolve().parents[2]/'source/ram-state/stage.py'))
    scope = api['stage'].__globals__
    monkeypatch.setitem(scope, 'INPUTS', {name: hashlib.sha256(data).hexdigest()
                                          for name, data in fixtures.items()})
    for name, data in fixtures.items():
        path = tmp_path/name;path.parent.mkdir(parents=True, exist_ok=True);path.write_bytes(data)
    result = api['stage'](tmp_path)
    for name in fixtures:
        text = (tmp_path/name).read_text()
        assert '#include "migration/vmstate.h"' in text and 'vmsd' in text
    assert set(result['outputs']) == set(fixtures)
    assert result['fields']['sony-spacc-stub'] == ['ram[65536]']
    assert not result['actual_roundtrip_verified'] and not result['physical_wbi_verified']
    with pytest.raises(ValueError, match='SHA256 drift'):
        api['transform']('hw/input/sony-ui-input.c', b'changed')


def test_roundtrip_source_failure_never_starts_target(tmp_path, monkeypatch):
    api = runpy.run_path(str(Path(__file__).resolve().parents[2]/'tools/run-original-cold.py'))
    scope = api['ram_roundtrip'].__globals__
    calls = []
    monkeypatch.setitem(scope, 'cold_environment', lambda: {})
    monkeypatch.setitem(scope, 'prepare', lambda *_args: {'ram0': 'unused'})
    @contextmanager
    def lease(_instance):
        yield {'leased': True}
    monkeypatch.setattr(scope['storage'], 'instance_lease', lease)
    def source_only(_instance, output, _seconds, **kwargs):
        calls.append(kwargs)
        (output/'result.json').write_text('{"verified": false}\n')
        return {'verified': False}
    monkeypatch.setitem(scope, 'run', source_only)
    result = api['ram_roundtrip'](tmp_path/'instance', tmp_path, 30)
    assert not result['actual_ram_roundtrip_verified'] and len(calls) == 1
    assert 'ram_capture' in calls[0] and not (tmp_path/'target').exists()


def test_window_ram_registration_validates_owned_candidate_before_use(tmp_path,monkeypatch):
    import persistent_storage as storage
    monkeypatch.setattr(storage,'PRODUCT',tmp_path);monkeypatch.delenv('A7C2_RAM_QEMU',raising=False)
    binary=tmp_path/'source/build/candidate/build/qemu-system-aarch64';binary.parent.mkdir(parents=True);binary.write_bytes(b'host candidate fixture')
    called=[]
    monkeypatch.setattr(storage,'binary_environment',lambda value,ram_state:called.append((value,ram_state)) or {})
    registration=tmp_path/'source/ram-state-build.json'
    registration.write_text(json.dumps(dict(schema='a7c2-product-ram-window-build-v1',binary=str(binary.relative_to(tmp_path)),binary_sha256=storage.sha(binary))))
    assert ram.window_binary()==binary and called==[(binary,True)]
    binary.write_bytes(b'changed')
    with pytest.raises(ValueError,match='binary changed'):ram.window_binary()
    monkeypatch.setenv('A7C2_RAM_QEMU',str(tmp_path/'outside'))
    with pytest.raises(ValueError,match='ordinary product build'):ram.window_binary()


def test_window_ram_reuses_capture_build_and_rejects_changed_or_foreign_metadata(tmp_path,monkeypatch):
    import persistent_storage as storage
    monkeypatch.setattr(storage,'ANALYSIS',tmp_path)
    source=tmp_path/'menu-runs/run-source';(source/'build').mkdir(parents=True)
    build=source/'build/result.json';built=dict(ram0=str(source/'build/ram0.ext2'),kernel_sha256='a'*64);build.write_text(json.dumps(built))
    target=tmp_path/'menu-runs/run-restored';target.mkdir();stream=target/'ram.qevm'
    value=dict(schema='a7c2-original-ram-capture-v1',build_result=str(build),build_result_sha256=storage.sha(build))
    ram.receipt_path(stream).write_text(json.dumps(value))
    assert ram.live_build(stream)==built
    build.write_text('{}')
    with pytest.raises(ValueError,match='build changed'):ram.live_build(stream)
    with pytest.raises(ValueError,match='owned product runs'):ram.live_build(tmp_path/'foreign/ram.qevm')


def test_live_window_ram_capture_follows_current_save_and_freeze(tmp_path,monkeypatch):
    import menu_live,original_cold_live as live,sd_export_lifecycle
    from types import SimpleNamespace
    (tmp_path/'build').mkdir();(tmp_path/'build/result.json').write_text('{}')
    binary=tmp_path/'qemu';binary.write_bytes(b'bound host fixture')
    monkeypatch.setenv('QEMU_SYSTEM_DIR',str(tmp_path));monkeypatch.setenv('QEMU_SYSTEM_BINARY','qemu')
    monkeypatch.setenv('MENU_CONTROL_FD','99');monkeypatch.delenv('A7C2_SETTINGS_PERSIST',raising=False)
    monkeypatch.setattr(live.os,'statvfs',lambda _:SimpleNamespace(f_bavail=80,f_frsize=1024**3))
    events=[]
    def export(_once,_serial,_sequence,publish):
        events.append('export');(tmp_path/'SD').mkdir();row=dict(ok=True,card_published=True,sha256='a'*64,flush_lifecycle=dict(ok=True));publish(row);return row
    monkeypatch.setattr(sd_export_lifecycle,'export_with_flush_lifecycle',export)
    def freeze(_serial,run):
        events.append('freeze');(run/'persistent-shutdown.raw').write_bytes(b'frozen')
        value=dict(frozen_verified=True,frozen_partitions=19,original_freeze_bdev_used=True,raw_sha256=hashlib.sha256(b'frozen').hexdigest());(run/'persistent-shutdown.json').write_text(json.dumps(value));return value
    monkeypatch.setattr(live.storage,'prepare_shutdown',freeze)
    def captured(_qmp,stream,_runtime,lease,_serial,_built,_qemu):
        events.append('capture');assert lease=={'owned':True};stream.write_bytes(PAYLOAD)
        return dict(stream=str(stream),stream_bytes=len(PAYLOAD),stream_sha256=hashlib.sha256(PAYLOAD).hexdigest(),source_identity={'boot_id':'host-fixture'})
    monkeypatch.setattr(ram,'capture',captured)
    def protocol(_proc,run,_fd,**callbacks):
        with pytest.raises(ValueError,match='current verified'):callbacks['ram_capture']()
        assert events==[]
        callbacks['sd_export']();callbacks['storage_shutdown'](lambda _:b'',run)
        value=callbacks['ram_capture']();assert value['completed'] is True
        assert live.saved_for_close(run)
        raise RuntimeError('VM 控制通道已关闭')
    monkeypatch.setattr(menu_live,'run_live',protocol)
    built=dict(helper_sources={'media-camera.fat':{'bytes':4096}},sd_card={'bytes':4096},ram0_sha256='a'*64,kernel_sha256='b'*64,overwrite={'entries':[]})
    result=live.live_session(None,tmp_path,None,built,leased={'owned':True},ram_enabled=True)
    assert events==['export','freeze','capture'] and result['save_verified'] and result['ram_capture']['completed']


def test_controller_ram_save_waits_for_owned_normal_exit_and_restore_requests_same_snapshot(tmp_path,monkeypatch):
    import threading
    from types import SimpleNamespace
    from menu_control import VM
    vm=VM(natural_boot=True,boot_profile='original-init-cold');vm.state='running';vm.ram_enabled=True;vm.ram_qemu=str(tmp_path/'qemu');vm.run_dir=str(tmp_path)
    monkeypatch.setattr(os,'statvfs',lambda _:SimpleNamespace(f_bavail=80,f_frsize=1024**3))
    def owner():
        request=vm.commands.get(timeout=5)
        assert request==dict(action='export_sd',_shutdown=True,_ram_capture=True)
        with vm.lock:
            (tmp_path/'result.json').write_text(json.dumps(dict(verified=True,ram_capture_verified=True,owner_group_exited=True,qmp_exit={'returncode':0})))
            vm.ram_snapshot={'stream':str(tmp_path/'ram.qevm'),'completed':True};vm.state='exited';vm.shutdown_done.set()
    vm.thread=threading.Thread(target=owner);vm.thread.start()
    captured=vm.save_ram();assert captured['completed'] and not vm.thread.is_alive()
    requests=[];monkeypatch.setattr(vm,'start',lambda:requests.append(vm._ram_restore))
    vm.restore_ram();assert requests==[captured['stream']]
    vm.state='running';monkeypatch.setattr(os,'statvfs',lambda _:SimpleNamespace(f_bavail=1,f_frsize=1024**3))
    with pytest.raises(ValueError,match='64GiB'):vm.save_ram()
    assert vm.commands.empty() and vm.state=='running'


@pytest.mark.parametrize('enabled',[False,True])
def test_live_control_ram_request_requires_capability_and_export_freeze_order(tmp_path,monkeypatch,enabled):
    import threading,menu_live
    from types import SimpleNamespace
    (tmp_path/'console.log').write_bytes(b'')
    monkeypatch.setenv('MENU_LIVE_KEY_FILE','host-fixture');monkeypatch.setenv('A7C2_STORAGE_PROFILE','product-single-disk-v1')
    monkeypatch.setattr(menu_live,'serial_command',lambda *args,**kwargs:b'')
    events=[];errors=[];parent,child=socket.socketpair()
    def export():events.append('export');return {'ok':True}
    def freeze(*args):events.append('freeze');return {'frozen_verified':True,'frozen_partitions':19}
    def capture():events.append('capture');return {'completed':True}
    def worker():
        try:menu_live.run_live(SimpleNamespace(poll=lambda:None),tmp_path,child.detach(),sd_export=export,storage_shutdown=freeze,ram_capture=capture if enabled else None)
        except (RuntimeError,ValueError) as error:errors.append(error)
    thread=threading.Thread(target=worker);thread.start()
    try:
        assert menu_live.receive_message(parent,timeout=3)['type']=='ready'
        menu_live.send_message(parent,dict(action='export_sd',shutdown_storage=True,capture_ram=True))
        if enabled:
            reply=menu_live.receive_message(parent,timeout=3)
            assert reply['ok'] is True and reply['ram_capture']['completed'] is True
            assert events==['export','freeze','capture']
    finally:parent.close();thread.join(3)
    assert not thread.is_alive()
    if not enabled:
        assert events==[] and len(errors)==1 and isinstance(errors[0],ValueError)


def test_restored_window_can_start_with_original_menu_already_open(tmp_path,monkeypatch):
    from types import SimpleNamespace
    import original_cold_boot
    raw=(b'A7C2_RAM_ID_BEGIN\n12345678-1234-1234-1234-123456789abc\n27.63 12.00\nA7C2_RAM_ID_END\n')
    (tmp_path/'console.log').write_bytes(b'')
    monkeypatch.setattr(ram,'_thaw',lambda *_:dict(state=0,count=0))
    monkeypatch.setattr(ram,'_lcd',lambda *_:dict(image=object(),sha256='source-menu',colors=8))
    monkeypatch.setattr(original_cold_boot,'original_menu_pixels',lambda _:True)
    seen=[]
    def settled(_qmp,_process,_runtime,**request):
        seen.append((request['menu'],request['previous']))
        return dict(sha256='menu' if request['menu'] else 'hud'),dict(press=1,release=1)
    monkeypatch.setattr(ram,'_settled_menu',settled)
    contract=dict(source_identity=dict(boot_id='12345678-1234-1234-1234-123456789abc',uptime_seconds=20),source_lcd_sha256='source-menu')
    result=ram.verify_restored(None,SimpleNamespace(poll=lambda:None),tmp_path,lambda _:raw,contract)
    assert seen==[(False,'source-menu'),(True,'hud')]
    assert result['source_menu_open'] and result['restored_scene_matches_source'] and not result['sony_wbi_resume_executed']
