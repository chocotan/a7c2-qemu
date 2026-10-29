import json
import os
from pathlib import Path
import signal
import socket
import struct
import subprocess
import sys

import pytest

import request_queue_watch as watch


def readback(base=0x7f00000000, pid=217):
    return (f'MODE_DIAL\nREADMEM /proc/{pid}/mem address={base + 0x7ee4750:x} bytes=4\n'
            f'MODE_SWITCH\nREADMEM /proc/{pid}/mem address={base + 0x7ee4778:x} bytes=4\n')


def test_readback_must_identify_one_consistent_original_AP():
    assert watch.app_base(readback().replace('\n', '\r\n')) == (217, 0x7f00000000)
    for text in (readback() + readback(), readback().replace('/217/mem', '/1/mem'),
                 readback(base=0x7f00000001), readback().replace('MODE_SWITCH', 'missing')):
        with pytest.raises(ValueError):
            watch.app_base(text)

def test_readback_tolerates_console_lines_between_label_and_result():
    # Kernel UIPC warnings, OBS records and UDIF ioctls are printed on the same
    # console as the diagnostic transaction; they must not break the pairing.
    noisy = ('MODE_DIAL\r\n'
             '[ 2431.863717] UDIF: cdev_ioctl() Line 100: uipc: warning ret = -1022\r\n'
             'READMEM /proc/217/mem address=7f41c2b750 bytes=4\r\n'
             '0000007f41c2b750: 00 00 00 00\r\n'
             'MODE_SWITCH\r\n'
             'OBS OSD_HEADLESS_ACK seq=4096 persisted AP snapshot consumed\r\n'
             'OBS OSD_HEADLESS_PERSISTED seq=4096 pixel_source_seq=4085\r\n'
             'READMEM /proc/217/mem address=7f41c2b778 bytes=4\r\n'
             '0000007f41c2b778: 00 00 00 00\r\n')
    assert watch.app_base(noisy) == (217, 0x7f41c2b750 - 0x7ee4750)
    # Two different candidate results inside one window stay ambiguous.
    with pytest.raises(ValueError):
        watch.app_base(noisy.replace('READMEM /proc/217/mem address=7f41c2b750 bytes=4\r\n',
                                     'READMEM /proc/217/mem address=7f41c2b750 bytes=4\r\n'
                                     'READMEM /proc/217/mem address=7f41c2b760 bytes=4\r\n'))
    # A result far outside the bounded window is not adopted.
    far = 'MODE_SWITCH\r\n' + '\r\n'.join(['filler'] * 8) + '\r\n' + \
          'READMEM /proc/217/mem address=7f41c2b778 bytes=4\r\n' + \
          'MODE_DIAL\r\nREADMEM /proc/217/mem address=7f41c2b750 bytes=4\r\n'
    with pytest.raises(ValueError):
        watch.app_base(far)


@pytest.fixture
def owned_run(tmp_path, monkeypatch):
    runs = tmp_path / 'menu-runs'
    runs.mkdir()
    run = runs / 'run-test'
    run.mkdir(mode=0o700)
    monkeypatch.setattr(watch, 'RUNS', runs)
    manifest = dict(host_control_owner_pid=os.getpid(), overwrite=None,
                    selected_initramfs_verified_files={'usr/lib/appFw.so': watch.AP_SHA},
                    request_queue_gdb=True, power_notice_observe=True,
                    apo_cancel_request_probe=True, mode_state_readback=True)
    (run / 'runtime-manifest.json').write_text(json.dumps(manifest))
    (run / 'mode-state-0001.txt').write_text(readback())
    fd = os.open(run, os.O_RDONLY | os.O_DIRECTORY)
    sock = socket.socket(socket.AF_UNIX)
    try:
        sock.bind(f'/proc/self/fd/{fd}/{watch.SOCKET}')
        yield run, manifest
    finally:
        sock.close()
        os.close(fd)


def test_owned_socket_uses_short_owned_directory_fd(owned_run):
    run, _ = owned_run
    fd, config = watch.owned_config(run, 1, os.getpid())
    try:
        assert config['queue'] == 0x7f00000000 + 0x7e4e5d0
        assert config['publish_pc'] == 0x7f00000000 + 0x24d8774
        assert config['socket'] == f'/proc/self/fd/{fd}/{watch.SOCKET}'
        assert config['run_inode'] == os.fstat(fd).st_ino
    finally:
        os.close(fd)


def test_resize_completion_budget_changes_only_for_explicit_model(owned_run):
    from resize_mmio_watch import KERNEL_SHA
    run,manifest=owned_run
    manifest['resize_mmio_watch']=True
    manifest['selected_initramfs_verified_files']['system/av-cam.bin']=KERNEL_SHA
    for enabled,limit in ((False,16),(True,64)):
        manifest['rc_board_profile']=enabled
        (run/'runtime-manifest.json').write_text(json.dumps(manifest))
        fd,config=watch.owned_config(run,0,os.getpid(),trace_mode='resize')
        try:
            assert config['limit']==limit
            assert config.get('observe_sa_mmu',False) is enabled
        finally:os.close(fd)


def test_media_mode_has_independent_optin_without_weakening_queue_gate(owned_run):
    run, manifest = owned_run
    manifest.update(power_notice_observe=False, apo_cancel_request_probe=False,
                    media_predicate_observe=True)
    (run/'runtime-manifest.json').write_text(json.dumps(manifest))
    fd, config = watch.owned_config(run, 1, os.getpid(), 'media')
    os.close(fd)
    assert config['trace_mode'] == 'media'
    with pytest.raises(ValueError):
        watch.owned_config(run, 1, os.getpid(), 'counter')
    manifest['media_predicate_observe'] = False
    (run/'runtime-manifest.json').write_text(json.dumps(manifest))
    with pytest.raises(ValueError):
        watch.owned_config(run, 1, os.getpid(), 'media')


def test_resize_mode_requires_original_kernel_and_does_not_weaken_queue_gate(owned_run):
    from resize_mmio_watch import KERNEL_SHA
    run, manifest = owned_run
    manifest.update(resize_mmio_watch=True, power_notice_observe=False,
                    apo_cancel_request_probe=False, mode_state_readback=False)
    (run/'runtime-manifest.json').write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match='original verified kernel'):
        watch.owned_config(run, 0, os.getpid(), 'resize')
    manifest['selected_initramfs_verified_files']['system/av-cam.bin'] = KERNEL_SHA
    (run/'runtime-manifest.json').write_text(json.dumps(manifest))
    fd, config = watch.owned_config(run, 0, os.getpid(), 'resize')
    os.close(fd)
    assert config['app_base'] == config['app_pid'] == 0
    with pytest.raises(ValueError):watch.owned_config(run, 1, os.getpid(), 'counter')


def test_preinit_uses_unique_original_gate_and_explicit_manifest(owned_run):
    run, manifest = owned_run
    manifest.update(media_init_watch=True, selected_observer_matches_build=True, power_notice_observe=False, apo_cancel_request_probe=False,
                    mode_state_readback=False)
    (run/'runtime-manifest.json').write_text(json.dumps(manifest))
    gate = b'OBS OBSERVER_READY MEDIA_INIT_GATE pid=217 base=0x7f00000000 wait_us=10000000 gate=0x7e10004000\n'
    (run/'console.log').write_bytes(gate)
    fd, config = watch.owned_config(run, 0, os.getpid(), 'media-init')
    os.close(fd)
    assert config['app_base'] == 0x7f00000000 and config['app_pid'] == 217
    stub = b'OBS OBSERVER_READY MEDIA_INIT_GATE pid=194 base=0x7f9c80010c wait_us=10000000 gate=0x7f9e1be670\n'
    assert watch.preinit_gate(stub) is None
    assert watch.preinit_gate(stub+gate) == (217, 0x7f00000000, 0x7e10004000)
    (run/'console.log').write_bytes(stub+gate)
    fd, config = watch.owned_config(run, 0, os.getpid(), 'media-init')
    os.close(fd)
    assert config['app_pid'] == 217
    (run/'console.log').write_bytes(gate+gate.replace(b'pid=217', b'pid=218'))
    with pytest.raises(ValueError, match='unique'):
        watch.owned_config(run, 0, os.getpid(), 'media-init')
    (run/'console.log').write_bytes(gate)
    manifest['media_init_watch'] = False
    (run/'runtime-manifest.json').write_text(json.dumps(manifest))
    with pytest.raises(ValueError):
        watch.owned_config(run, 0, os.getpid(), 'media-init')


def test_debugger_rederives_addresses_and_refuses_configuration_changes(owned_run):
    run, _ = owned_run
    fd, config = watch.owned_config(run, 1, os.getpid())
    os.close(fd)
    again, actual = watch.revalidate_gdb_config(config)
    os.close(again)
    assert actual['queue'] == config['queue']
    for key in ('app_base', 'queue', 'publish_pc', 'cancel_caller', 'run_inode', 'limit'):
        changed = dict(config)
        changed[key] += 1
        with pytest.raises(ValueError):
            watch.revalidate_gdb_config(changed)


@pytest.mark.parametrize('field,value', [('host_control_owner_pid', 1), ('overwrite', {'entries': []}),
    ('request_queue_gdb', False), ('power_notice_observe', False), ('apo_cancel_request_probe', False),
    ('mode_state_readback', False), ('selected_initramfs_verified_files', {'usr/lib/appFw.so': 'bad'})])
def test_refuses_foreign_owner_custom_firmware_or_incomplete_profile(owned_run, field, value):
    run, manifest = owned_run
    manifest[field] = value
    (run / 'runtime-manifest.json').write_text(json.dumps(manifest))
    with pytest.raises(ValueError):
        watch.owned_config(run, 1, os.getpid())


@pytest.mark.parametrize('name', ['runtime-manifest.json', 'mode-state-0001.txt', watch.SOCKET])
def test_refuses_swapped_symlink_components(owned_run, name):
    run, _ = owned_run
    original = run / name
    target = run / (name + '.original')
    original.rename(target)
    original.symlink_to(target.name)
    with pytest.raises(ValueError):
        watch.owned_config(run, 1, os.getpid())


def test_observes_only_original_caller_owned_batch_without_writes():
    memory = {0x1000: struct.pack('<Q', 0x2000), 0x2000: struct.pack('<3Q', 0x3000, 0x3008, 0x3008),
              0x3000: struct.pack('<Q', 0x4000), 0x4000: struct.pack('<IIQB', 0x100, 1, 0, 0),
              0x4770: b'\0'}
    before = dict(memory)
    class Inferior:
        def read_memory(self, address, size):
            value = memory[address]
            assert len(value) == size
            return value
    result = watch.owned_batch(Inferior(), 0x1000)
    assert result['requests'] == [dict(address=0x4000, id=0x100, raw4=1, raw8=0, raw10=0, raw770=0)]
    assert memory == before
    memory[0x2000] = struct.pack('<3Q', 0x3000, 0x2ff8, 0x3008)
    with pytest.raises(ValueError):
        watch.owned_batch(Inferior(), 0x1000)
    del memory[0x1000]
    with pytest.raises(KeyError):
        watch.owned_batch(Inferior(), 0x1000)


@pytest.mark.parametrize('initial,final,expected', [('running', 'running', ['query-status']),
    ('debug', 'running', ['query-status', 'cont', 'query-status']),
    ('paused', 'running', ['query-status', 'cont', 'query-status'])])
def test_cpu_cleanup_handles_QMP_envelope_without_guest_signals(initial, final, expected):
    calls = []
    def qmp(command):
        calls.append(command)
        if command == 'cont':
            return {'return': {}}
        state = initial if len(calls) == 1 else final
        return {'return': dict(running=state == 'running', status=state)}
    assert watch.resume_debug_cpu(qmp)['cpu_running_verified']
    assert calls == expected


def test_cpu_cleanup_refuses_unknown_or_unconfirmed_state():
    for reply in ({'return': {}}, {'return': dict(running=False, status='shutdown')}, {}):
        with pytest.raises(RuntimeError):
            watch.resume_debug_cpu(lambda _: reply)
    with pytest.raises(RuntimeError):
        watch.resume_debug_cpu(lambda _: {'return': dict(running=False, status='debug')})


def test_stop_only_owned_child_and_closes_descriptors(tmp_path,monkeypatch):
    monkeypatch.setattr(watch,'resume_owned_debug_cpu',lambda fd:{'cpu_running_verified':True})
    proc = subprocess.Popen([sys.executable, '-u', '-c',
                             'import signal; print("READY"); signal.pause()'], stdout=subprocess.PIPE,
                            stderr=subprocess.DEVNULL, text=True)
    assert proc.stdout.readline().strip() == 'READY'
    instance = watch.QueueWatch.__new__(watch.QueueWatch)
    instance.process, instance.log = proc, (tmp_path / 'log').open('wb')
    instance.fd, instance.cleanup = os.open(tmp_path, os.O_RDONLY | os.O_DIRECTORY), None
    old_fd = instance.fd
    try:
        result = instance.stop()
        assert result['debugger_stopped'] and not result['forced_termination']
        assert instance.stop() is result
        with pytest.raises(OSError):
            os.fstat(old_fd)
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait(timeout=5)
        proc.stdout.close()


def test_forced_cleanup_still_uses_only_owned_process(tmp_path,monkeypatch):
    actions = []
    monkeypatch.setattr(watch,'resume_owned_debug_cpu',lambda fd:actions.append(('cpu-resume',)) or {'cpu_running_verified':True})
    class OwnedProcess:
        returncode = None
        def poll(self): return self.returncode
        def send_signal(self, sig): actions.append(('signal', sig))
        def terminate(self): actions.append(('terminate',))
        def kill(self): actions.append(('kill',)); self.returncode = -9
        def wait(self, timeout):
            if self.returncode is None: raise subprocess.TimeoutExpired('owned fixture', timeout)
    instance = watch.QueueWatch.__new__(watch.QueueWatch)
    instance.process, instance.log, instance.fd, instance.cleanup = OwnedProcess(), None, None, None
    result = instance.stop()
    assert result['debugger_stopped'] and result['forced_termination']
    assert actions == [('signal', signal.SIGINT), ('terminate',), ('kill',), ('cpu-resume',)]
    assert result['cpu_running_verified'] and result['safe_to_close']


def test_startup_failure_closes_owned_directory_before_any_debug_connection(owned_run,monkeypatch):
    run, _ = owned_run
    fd,config=watch.owned_config(run,1,os.getpid())
    monkeypatch.setattr(watch,'owned_config',lambda *args:(fd,config))
    monkeypatch.setattr(watch.shutil,'which',lambda name:None)
    with pytest.raises(RuntimeError,match='gdb is unavailable'):
        watch.QueueWatch(run,1,os.getpid())
    with pytest.raises(OSError):os.fstat(fd)


def test_debug_flags_are_rejected_before_VM_or_display_start():
    base=Path(watch.__file__).parent
    env={k:v for k,v in os.environ.items() if not k.startswith(('MENU_','QEMU_','SONY_','A7C2_'))}
    result=subprocess.run(['bash',str(base/'qemu-kernel-probe.sh')],
        env=dict(env,QEMU_REQUEST_QUEUE_GDB='1',MENU_NATIVE_WINDOW='0',QEMU_UI_LIVE='0'),capture_output=True,timeout=10)
    assert result.returncode==2 and b'Queue debug requires an owned live native VM' in result.stderr
    result=subprocess.run([sys.executable,str(base/'qemu-menu-probe.py')],
        env=dict(env,A7C2_QUEUE_WATCH='1'),capture_output=True,timeout=10)
    assert result.returncode==2 and b'Queue watch requires owned native live' in result.stderr
    result=subprocess.run([sys.executable,str(base/'qemu-menu-probe.py')],
        env=dict(env,A7C2_QUEUE_WATCH='1',A7C2_MEDIA_PREDICATE_WATCH='1'),capture_output=True,timeout=10)
    assert result.returncode==2 and b'mutually exclusive' in result.stderr
    result=subprocess.run([sys.executable,str(base/'check-natural-gtk-input.py'),'--queue-watch-probe'],
        env=env,capture_output=True,timeout=10)
    assert result.returncode and b'--queue-watch-probe requires new UI' in result.stderr


def test_handoff_mode_is_rederived_but_unknown_modes_refused(owned_run):
    run,_=owned_run
    fd,config=watch.owned_config(run,1,os.getpid(),'handoff');os.close(fd)
    fd,actual=watch.revalidate_gdb_config(config)
    try:assert actual['trace_mode']=='handoff'
    finally:os.close(fd)
    with pytest.raises(ValueError,match='mode'):watch.owned_config(run,1,os.getpid(),'arbitrary-target')


def test_sequence_is_read_only_after_exact_live_queue_payload_matches():
    base=0x7f00000000;root=0x1000;node=0x2000;target=0x3000
    obj=bytearray(0x28);struct.pack_into('<Q',obj,0,base+0x5b3ace0);struct.pack_into('<5I',obj,0x14,1,2,3,4,5)
    obj[0x19:0x1c]=b'\xaa\xbb\xcc'  # ctor padding must never become snapshot18's value
    memory={root:struct.pack('<3Q',node,node,1),node+0x10:struct.pack('<Q',target),target:bytes(obj)};reads=[]
    class Inferior:
        def read_memory(self,address,size):
            reads.append(address);value=memory[address];assert len(value)==size;return value
    result=watch.queued_sequence(Inferior(),root,target,base)
    assert result['address']==target and result['raw14']==1 and result['raw18']==2 and result['raw1c_24']==[3,4,5]
    assert reads==[root,node+0x10,target]
    reads.clear();memory[node+0x10]=struct.pack('<Q',0x9000)
    with pytest.raises(ValueError,match='same original'):watch.queued_sequence(Inferior(),root,target,base)
    assert target not in reads
    reads.clear();memory[root]=struct.pack('<3Q',node,node,0)
    with pytest.raises(ValueError,match='bounds'):watch.queued_sequence(Inferior(),root,target,base)
    assert reads==[root]
    memory[target]=bytes(0x28)
    with pytest.raises(ValueError,match='pinned original'):watch.sequence_snapshot(Inferior(),target,base)


def test_original_not_ready_gate_stops_before_ctor_or_stale_object_reads():
    from types import SimpleNamespace
    target=0x5000;stops=[];result={'hits':0};events=[];reads=[];bps=[]
    class Breakpoint:
        def __init__(self,*args,**kwargs):self.number=len(bps)+1;self.deleted=False;bps.append(self)
        def delete(self):self.deleted=True
    class Inferior:
        def read_memory(self,address,size):
            reads.append((address,size))
            if address==target and size==0x18:return struct.pack('<I',0x100)+bytes(20)
            if address==target+0x770 and size==1:return b'\0'
            raise AssertionError('Unexpected or stale object read')
    gdb=SimpleNamespace(Breakpoint=Breakpoint,BP_HARDWARE_BREAKPOINT=2,selected_inferior=lambda:Inferior(),
                        execute=lambda *args,**kwargs:stops.append({'breakpoints':[bps[-1].number]}))
    watch.sequence_handoff(gdb,{'app_base':0x7f00000000}, {'requests':[{'address':target}]},
                           lambda kind,**data:events.append(kind),result,stops,lambda:{'x19':target})
    assert events==['same_request_dispatch_gate'] and result['request_not_ready_at_original_gate']
    assert len(bps)==3 and all(bp.deleted for bp in bps) and reads==[(target,0x18),(target+0x770,1)]
