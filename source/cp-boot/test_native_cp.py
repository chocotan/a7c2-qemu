"""Host contract tests only; written here without execution. Use a project-local --basetemp."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import struct
import stat
import time
from contextlib import contextmanager, nullcontext
from types import SimpleNamespace

import pytest

spec = importlib.util.spec_from_file_location('native_cp_launcher', Path(__file__).with_name('run-native-cp.py'))
cp = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cp)


def digest(data):
    return hashlib.sha256(data).hexdigest()


@pytest.fixture
def local(tmp_path):
    assert not str(tmp_path).startswith('/tmp/'), 'Use --basetemp in the project, per AGENTS.md'
    return tmp_path


def test_fixed_official_identities_and_stack_contract():
    assert cp.CP_SIZE == 18090880
    assert cp.CP_SHA == 'f5a477588698ef965748903b8959a39ce4f59ffd4aee4d4234ef1670f56a1428'
    assert cp.TOMCO_SIZE == 741
    assert cp.TOMCO_SHA == '02b202a9b4fbf7bdcbe93d032bfe475a21859019a3c02d1766ac133a779650d3'
    image = bytearray(cp.CP_SIZE)
    for core in range(4):
        for offset in range(4, 0x4c, 12):
            struct.pack_into('<3I', image, 0x20000 + core * 0x48 + offset, 0x1800000, 0x1000, 0x1801000)
    stacks = cp.stack_descriptors(image)
    assert len(stacks) == 4 and all(len(core['entries']) == 6 for core in stacks)
    struct.pack_into('<3I', image, 0x20004, 0x1800000, 0x1000, 0x1801004)
    with pytest.raises(ValueError, match='stack descriptor'):
        cp.stack_descriptors(image)
    with pytest.raises(ValueError, match='length'):
        cp.stack_descriptors(image[:-1])


@pytest.mark.parametrize('start,size,sp', [(0x100000, 16, 0x100010), (0x1800000, 0, 0x1800000),
                                         (0x1ffffff, 2, 0x2000001)])
def test_reject_invalid_stack_bounds(start, size, sp):
    image = bytearray(cp.CP_SIZE)
    struct.pack_into('<3I', image, 0x20004, start, size, sp)
    with pytest.raises(ValueError, match='stack descriptor'):
        cp.stack_descriptors(image)


@pytest.mark.parametrize('seconds', [1, 180, 3600])
def test_cpu_as_and_log_budgets_cover_the_window(seconds):
    budget = cp.limits(seconds)
    assert budget['cpu_soft'] == max(250, 4 * (seconds + 60))
    assert budget['cpu_hard'] == budget['cpu_soft'] + 10
    assert budget['address_space'] >= 12 * cp.GIB
    assert budget['file_size'] >= (seconds + 60) * 2 * cp.MIB
    assert budget['log_budget'] >= 7 * budget['file_size']
    assert budget['reserve'] == 64 * cp.GIB


@pytest.mark.parametrize('seconds', [0, -1, 3601, True, 1.5])
def test_reject_unbounded_or_noninteger_window(seconds):
    with pytest.raises(ValueError, match='seconds'):
        cp.limits(seconds)


def test_child_hard_limits_without_mutating_test_process(monkeypatch):
    calls = []
    monkeypatch.setattr(cp.os, 'umask', lambda value: calls.append(('umask', value)))
    monkeypatch.setattr(cp.resource, 'setrlimit', lambda kind, values: calls.append((kind, values)))
    budget = cp.limits(3600)
    cp.child_limits(budget)
    assert ('umask', 0o077) in calls
    assert (cp.resource.RLIMIT_CORE, (0, 0)) in calls
    assert (cp.resource.RLIMIT_CPU, (14640, 14650)) in calls
    assert (cp.resource.RLIMIT_AS, (16 * cp.GIB, 16 * cp.GIB)) in calls


def test_input_readonly_hash_identity_and_rejections(local):
    source = local / 'original.bin'
    source.write_bytes(b'original exported bytes')
    source.chmod(0o600)
    before = cp.identity(source.stat())
    proof, data = cp.input_record(source, source.stat().st_size, digest(source.read_bytes()), keep=True)
    assert data == b'original exported bytes' and proof['sha256'] == digest(data)
    assert cp.identity(source.stat()) == before
    with pytest.raises(ValueError, match='SHA256'):
        cp.input_record(source, sha256='0' * 64)
    with pytest.raises(ValueError, match='length'):
        cp.input_record(source, size=source.stat().st_size + 1)
    alias = local / 'alias.bin'
    alias.symlink_to(source)
    with pytest.raises(ValueError, match='regular'):
        cp.input_record(alias)
    linked_parent = local / 'linked-parent'
    linked_parent.symlink_to(local, target_is_directory=True)
    with pytest.raises(OSError):
        cp.input_record(linked_parent / source.name)
    hardlink = local / 'hardlink.bin'
    os.link(source, hardlink)
    with pytest.raises(ValueError, match='single-link'):
        cp.input_record(source)
    with pytest.raises(ValueError, match='forbidden'):
        cp.input_record('/dev/null')


def test_no_replay_and_verbatim_slice_output(local):
    claim = local / cp.CLAIM
    cp.write_json(claim, dict(owner_pid=os.getpid(), replay_allowed=False))
    previous = claim.read_bytes()
    with pytest.raises(FileExistsError):
        cp.write_json(claim, dict(owner_pid=-1))
    assert claim.read_bytes() == previous
    record = b'\x00BK4\x00\xff\n' * 50
    fd = cp.new_file(local / 'slice.bin', record)
    os.close(fd)
    assert (local / 'slice.bin').read_bytes() == record
    assert (local / 'slice.bin').stat().st_mode & 0o777 == 0o600


def ram_arguments(pair):
    result = []
    for name, filename, size, offset in [('native-local-ram', 'cp-ram.bin', 128 * cp.MIB, 0),
                                         ('native-peer-ram', 'ap-ram.bin', 8 * cp.GIB, 15 * cp.GIB),
                                         ('native-local-oom', 'cp-oom.bin', 0x101000, 0)]:
        result += ['-object', json.dumps({'qom-type': 'memory-backend-file', 'id': name,
                    'mem-path': str(pair / filename), 'size': size, 'offset': offset,
                    'share': True, 'discard-data': False})]
    return result


def test_argv_is_product_only_with_json_loaders_and_real_uart_files(local):
    pair = local / 'pair,with-comma'
    output = local / 'output,with-comma'
    image = local / 'cp,addr=0,cpu-num=3.bin'
    command = cp.argv(local / 'qemu-system-aarch64', pair, output, image, local / 'tomco.txt',
                      output / 'official-ed000.bin', ram_arguments(pair))
    devices = [json.loads(command[index + 1]) for index, value in enumerate(command) if value == '-device']
    assert len(devices) == 6
    assert devices[0] == {'driver': 'loader', 'file': str(image), 'addr': 0x108000,
                           'cpu-num': 0, 'force-raw': True}
    assert [device['cpu-num'] for device in devices[:4]] == [0, 1, 2, 3]
    assert all(device['addr'] == 0x108000 for device in devices[:4])
    assert [device['addr'] for device in devices[4:]] == [0x100000, 0x04000000]
    assert command[command.index('-M') + 1] == 'none,memory-backend=native-local-ram'
    assert command[command.index('-cpu') + 1] == 'cortex-a53,aarch64=off,cntfrq=2000000'
    assert command[command.index('-sandbox') + 1] == 'on'
    assert command[command.index('-d') + 1] == 'guest_errors'
    assert '-machine' not in command and '-drive' not in command and '-kernel' not in command
    assert 'socket,id=notify-peer,path=notify.sock,server=off' in command
    assert all(f'file,id=cp-uart{uart},path=' + str(output / f'uart{uart}.log').replace(',', ',,') in command
               for uart in range(5))
    source = Path(cp.__file__).read_text()
    assert "PRODUCT / 'runtime' / 'analysis'" in source
    assert 'analysis/cp-boot-probe' not in source and 'research/' not in source
    assert 'os.chdir(' not in source and 'sys.path.insert(' not in source
    assert 'terminate(' not in source and '.kill(' not in source
    with pytest.raises(ValueError, match='only three'):
        cp.argv(local / 'qemu', pair, output, image, local / 'tomco', output / 'bk4', ['-machine', 'none'])
    wrong = ram_arguments(pair)
    obj = json.loads(wrong[3])
    obj['offset'] = 0
    wrong[3] = json.dumps(obj)
    with pytest.raises(ValueError, match='geometry'):
        cp.argv(local / 'qemu', pair, output, image, local / 'tomco', output / 'bk4', wrong)


def cp_delta(pair):
    return dict(QEMU_NATIVE_AP_CP_LINK=cp.PROFILE, QEMU_NATIVE_LINK_DIR=str(pair),
                QEMU_AP_CP_GPIO_LINES='virtual-ap-cp-gpio-lines-v1', QEMU_AP_CP_GPIO_SIDE='cp',
                QEMU_CP_BOOT_PERIPHERALS='virtual-cp-boot-peripherals-v1',
                QEMU_CP_KEY_GPIO_PROFILE='virtual-cp-key-gpio-v1',
                **{'QEMU_CP_' + name: '1' for name in ('GIC', 'TIMERS', 'WATCHDOG', 'EDMA_GATE', 'UIPC_RAM')})


def test_environment_strips_old_gates_and_rejects_other_profiles(local):
    link = SimpleNamespace(environment=lambda side, pair: cp_delta(pair))
    env = cp.environment(link, local, {'PATH': '/usr/bin', 'QEMU_CP_EDMA_DIRECT': '1',
                                     'QEMU_SONY_PCIDMA_TEST': '1', 'QEMU_NATIVE_AP_CP_LINK': 'old',
                                     'QEMU_AP_CP_GPIO_SIDE': 'ap', 'NATIVE_TEST': '1'})
    assert env['QEMU_AP_CP_GPIO_SIDE'] == 'cp' and env['QEMU_CP_HYPOTHESIS_SEC_TIMER30'] == '1'
    assert 'QEMU_CP_EDMA_DIRECT' not in env and 'QEMU_SONY_PCIDMA_TEST' not in env
    assert 'NATIVE_TEST' not in env
    for name in ('QEMU_RAM_SESSION', 'QEMU_HOST_SD', 'MENU_CP_EMULATION', 'MY_VIRTUAL_CP_SENDER'):
        with pytest.raises(ValueError, match='Conflicting'):
            cp.environment(link, local, {name: '1'})
    bad = SimpleNamespace(environment=lambda side, pair: dict(cp_delta(pair), QEMU_AP_CP_GPIO_SIDE='ap'))
    with pytest.raises(ValueError, match='contract'):
        cp.environment(bad, local, {})


def test_all_loaded_bytes_are_read_and_a_tail_mismatch_refuses_verification():
    data = b'cp bytes\0' * 14000 + b'unique final tail'
    proof = dict(size=len(data), sha256=digest(data))
    calls = []
    rsp = SimpleNamespace(mode=lambda physical: calls.append(('physical', physical)),
                          read=lambda address, size: data[address - 0x108000:address - 0x108000 + size])
    result = dict(loaded_inputs_verified=False)
    cp.verify_loaded(rsp, [('cp', 0x108000, proof)], result)
    assert calls == [('physical', True)] and result['loaded_inputs_verified']
    assert result['loaded_input_readback'][0]['read_bytes'] == len(data)
    wrong = data[:-1] + bytes([data[-1] ^ 1])
    rsp.read = lambda address, size: wrong[address - 0x108000:address - 0x108000 + size]
    result = dict(loaded_inputs_verified=False)
    with pytest.raises(ValueError, match='Full RSP'):
        cp.verify_loaded(rsp, [('cp', 0x108000, proof)], result)
    assert not result['loaded_inputs_verified'] and not result['loaded_input_readback'][0]['verified']


def test_missing_external_ap_socket_never_starts_any_process(local, monkeypatch):
    binary = local / 'qemu'
    binary.write_bytes(b'fixture; never execute')
    binary.chmod(0o700)
    pair = local / 'pair'
    pair.mkdir(mode=0o700)
    link = SimpleNamespace(admit=lambda pair, binary: dict(profile=cp.PROFILE))
    monkeypatch.setattr(cp, 'products', lambda: (link, SimpleNamespace()))
    calls = []
    monkeypatch.setattr(cp.subprocess, 'Popen', lambda *args, **kwargs: calls.append((args, kwargs)))
    args = SimpleNamespace(seconds=1, binary=binary, pair=pair, output=local / 'fresh-output')
    result = cp.run(args)
    assert not calls and not result['ok'] and 'pid' not in result
    assert 'notify.sock' in result['errors'][0]['error']
    assert (args.output / 'result.json').is_file() and not (pair / cp.CLAIM).exists()


@pytest.fixture
def ap_owner(local,monkeypatch):
    pair=local/'ap-pair';pair.mkdir(mode=0o700)
    binary=local/'qemu-fixture';binary.write_bytes(b'fake admitted qemu executable');binary.chmod(0o700)
    run=pair/'ap-runs'/'run-fixture';run.mkdir(parents=True,mode=0o700)
    lock=run/'ap-cp-control.lock';fd=cp.new_file(lock);os.close(fd)
    lock_identity=cp.identity(lock.stat())
    pointer=pair/'latest-ap-run.txt';fd=cp.new_file(pointer,(str(run)+'\n').encode());os.close(fd)
    owner_pid,qemu_pid=2468,2469;boot='00112233-4455-6677-8899-aabbccddeeff'
    command=['/usr/bin/python3','-B','qemu-menu-probe.py','--initramfs','--bootin']
    command_raw=b'\0'.join(word.encode() for word in command)+b'\0'
    qemu_raw=b'/fixture/qemu-system-aarch64\0-native-pair\0'
    pair_stat=pair.stat();run_stat=run.stat();binary_stat=binary.stat()
    root_identity=lambda value:dict(dev=value.st_dev,ino=value.st_ino,mode=value.st_mode,uid=value.st_uid)
    binary_record=dict(path=str(binary),sha256=digest(binary.read_bytes()),**cp.identity(binary_stat))
    admission=dict(schema='a7c2-native-ap-cp-pair-v1',profile=cp.PROFILE,directory=str(pair),
                   root_identity=root_identity(pair_stat),binary=binary_record)
    fake_proc=local/'fake-proc';fake_proc.mkdir()
    owner=fake_proc/str(owner_pid);qemu=fake_proc/str(qemu_pid)
    for process in (owner,qemu):process.mkdir(mode=0o700)
    boot_file=fake_proc/'sys/kernel/random/boot_id';boot_file.parent.mkdir(parents=True);boot_file.write_text(boot)
    def status(process,pid,ticks,state='S',name='owned-process'):
        (process/'stat').write_text(f'{pid} ({name}) '+' '.join([state]+['0']*18+[str(ticks)])+'\n')
    def owner_status(ticks='123',state='S'):status(owner,owner_pid,ticks,state,'owned-ap-probe')
    def qemu_status(ticks='456',state='S'):status(qemu,qemu_pid,ticks,state,'owned-qemu')
    owner_status();qemu_status()
    (owner/'cmdline').write_bytes(command_raw)
    (owner/'environ').write_bytes((f'QEMU_NATIVE_LINK_DIR={pair}\0QEMU_NATIVE_AP_CP_LINK={cp.PROFILE}\0SECRET=never-return\0').encode())
    (qemu/'cmdline').write_bytes(qemu_raw)
    for process in (owner,qemu):(process/'exe').symlink_to(binary)
    command_sha=hashlib.sha256(command_raw).hexdigest();qemu_sha=hashlib.sha256(qemu_raw).hexdigest()
    nonce='a1'*16
    claim=dict(schema='a7c2-native-ap-admission-v2',profile=cp.PROFILE,pair=str(pair),owner_pid=owner_pid,
               owner_start_ticks='123',host_boot_id=boot,command=command,command_sha256=command_sha,
               run_nonce=nonce,binary_sha256=binary_record['sha256'],pair_admission=admission,
               replay_allowed=False,coordinator_owns_pair_release=True)
    cp.write_json(pair/'ap-admission.claim',claim)
    claim_proof=cp.input_record(pair/'ap-admission.claim')[0]
    pointer_proof=cp.input_record(pointer)[0]
    qmp_stat=SimpleNamespace(st_mode=stat.S_IFSOCK|0o600,st_uid=os.getuid(),st_dev=701,st_ino=702)
    vm=dict(schema='a7c2-native-ap-vm-owner-v1',profile=cp.PROFILE,pair=str(pair),ap_run=str(run),ready=True,
            run_nonce=nonce,claim_sha256=claim_proof['sha256'],pair_root_identity=admission['root_identity'],
            run_root_identity=root_identity(run_stat),owner_pid=owner_pid,owner_start_ticks='123',
            host_boot_id=boot,owner_command_sha256=command_sha,qemu_pid=qemu_pid,qemu_start_ticks='456',
            qemu_uid=os.getuid(),qemu_gid=os.getgid(),qemu_exe_path=str(binary),qemu_exe_dev=binary_stat.st_dev,
            qemu_exe_ino=binary_stat.st_ino,qemu_exe_size=binary_stat.st_size,qemu_exe_mode=binary_stat.st_mode,
            qemu_command_sha256=qemu_sha,binary_path=str(binary),binary_sha256=binary_record['sha256'],
            qmp_peer=dict(pid=qemu_pid,uid=os.getuid(),gid=os.getgid(),dev=qmp_stat.st_dev,ino=qmp_stat.st_ino),
            control_lock=dict(path=str(lock),**lock_identity),run_pointer_sha256=pointer_proof['sha256'])
    cp.write_json(run/'native-ap-vm.json',vm)
    original_path=cp.Path
    def redirect(value):
        raw=os.fspath(value)
        if raw=='/proc':return fake_proc
        if raw.startswith('/proc/'):return fake_proc/raw[len('/proc/'):]
        return original_path(value)
    monkeypatch.setattr(cp,'Path',redirect)
    fake_link=SimpleNamespace(admit=lambda candidate,candidate_binary:admission,
        ap_probe_command=lambda:command,_unique_object=lambda pairs:_json_unique(pairs))
    monkeypatch.setattr(cp,'products',lambda:(fake_link,SimpleNamespace()))
    original_stat=os.stat
    def stat_redirect(path,*args,**kwargs):
        if os.fspath(path)==str(run/'qmp.sock') and kwargs.get('follow_symlinks') is False:return qmp_stat
        return original_stat(path,*args,**kwargs)
    monkeypatch.setattr(cp.os,'stat',stat_redirect)
    result={'pair':str(pair),'pair_admission':admission}
    return SimpleNamespace(pair=pair,run=run,process=owner,owner=owner,qemu=qemu,lock=lock,command=command,
                           result=result,status=owner_status,qemu_status=qemu_status,qmp_stat=qmp_stat,binary=binary)


def _json_unique(pairs):
    result={}
    for key,value in pairs:
        if key in result:raise ValueError('duplicate JSON key')
        result[key]=value
    return result



def test_external_ap_owner_is_bound_and_secrets_are_not_reported(ap_owner):
    first=cp.check_external_ap_owner(ap_owner.result)
    ap_owner.result['external_ap_before_inputs']=first
    assert cp.check_external_ap_owner(ap_owner.result)==first
    assert first['owner_pid']==2468 and first['start_ticks']=='123'
    assert 'SECRET' not in repr(first) and 'never-return' not in repr(first)
    ap_owner.status(ticks='124')
    with pytest.raises(ValueError,match='replaced'):cp.check_external_ap_owner(ap_owner.result)


@pytest.mark.parametrize('kind',['gone','zombie','argv','pair_environment','claim','quitting','escaped_run',
                                'qemu_gone','qemu_replaced','qemu_exe','qmp_socket','wrong_nonce',
                                'lock_replaced','duplicate_json'])
def test_external_ap_dead_or_mismatched_owner_fails_closed(ap_owner,kind):
    if kind=='gone':(ap_owner.process/'stat').unlink()
    elif kind=='zombie':ap_owner.status(state='Z')
    elif kind=='argv':(ap_owner.process/'cmdline').write_bytes(b'other-process\0')
    elif kind=='pair_environment':(ap_owner.process/'environ').write_bytes(b'QEMU_NATIVE_LINK_DIR=/another-pair\0')
    elif kind=='quitting':cp.write_json(ap_owner.run/'qmp-quit.json',{'attempted':True})
    elif kind=='escaped_run':(ap_owner.pair/'latest-ap-run.txt').write_text('/owned/some-other-pair/run\n')
    elif kind=='qemu_gone':(ap_owner.qemu/'stat').unlink()
    elif kind=='qemu_replaced':ap_owner.qemu_status(ticks='457')
    elif kind=='qemu_exe':
        other=ap_owner.binary.with_name('replaced-qemu');other.write_bytes(b'different executable');other.chmod(0o700)
        (ap_owner.qemu/'exe').unlink();(ap_owner.qemu/'exe').symlink_to(other)
    elif kind=='qmp_socket':ap_owner.qmp_stat.st_ino+=1
    elif kind=='wrong_nonce':
        path=ap_owner.run/'native-ap-vm.json';record=json.loads(path.read_bytes());record['run_nonce']='b2'*16
        path.write_text(json.dumps(record)+'\n')
    elif kind=='lock_replaced':
        old=ap_owner.lock.with_name('ap-cp-control.lock-retained');ap_owner.lock.rename(old)
        fd=cp.new_file(ap_owner.lock);os.close(fd)
    elif kind=='duplicate_json':
        path=ap_owner.pair/'ap-admission.claim';path.write_text('{"schema":"a7c2-native-ap-admission-v2","schema":"duplicate"}\n')
    else:
        path=ap_owner.pair/'ap-admission.claim';claim=json.loads(path.read_bytes());claim['binary_sha256']='b'*64;path.write_text(json.dumps(claim))
    with pytest.raises(ValueError):cp.check_external_ap_owner(ap_owner.result)


def test_external_ap_control_lock_is_exclusive_and_inode_bound(ap_owner):
    owner=cp.check_external_ap_owner(ap_owner.result)
    with cp.external_ap_cont_lock(owner):pass
    fd=os.open(ap_owner.lock,os.O_RDWR)
    try:
        cp.fcntl.flock(fd,cp.fcntl.LOCK_EX|cp.fcntl.LOCK_NB)
        with pytest.raises(ValueError,match='AP shutdown owns'):
            with cp.external_ap_cont_lock(owner):pass
    finally:
        cp.fcntl.flock(fd,cp.fcntl.LOCK_UN);os.close(fd)

def test_pidfds_pin_both_ap_owner_and_qmp_peer_qemu(ap_owner,monkeypatch):
    owner=cp.check_external_ap_owner(ap_owner.result)
    fds=os.pipe();handles=iter(fds)
    monkeypatch.setattr(cp.os,'pidfd_open',lambda pid,flags:next(handles))
    monkeypatch.setattr(cp,'pidfd_exited',lambda fd:False)
    pinned=cp.open_external_ap_pidfds(owner)
    assert set(pinned)=={'owner','qemu'} and pinned['owner']!=pinned['qemu']
    monkeypatch.setattr(cp,'pidfd_exited',lambda fd:fd==pinned['qemu'])
    assert cp.external_ap_owner_exited(pinned)
    cp.close_external_ap_pidfds(pinned)


def test_failed_full_readback_never_continues_original_cp():
    words = [0] * 17
    words[15], words[16] = cp.CP_ADDRESS, 0x13
    replies = {b'?': b'T05thread:1;', b'qfThreadInfo': b'm1,2,3,4', b'qsThreadInfo': b'l',
               b'g': struct.pack('<17I', *words).hex().encode('ascii')}
    rsp = SimpleNamespace(request=lambda request: b'OK' if request.startswith(b'Hg') else replies[request],
                          mode=lambda physical: None, read=lambda address, size: b'bad'[:size])
    qmp = FakeClient()
    proof = dict(size=3, sha256=digest(b'yes'))
    result = dict(loaded_inputs_verified=False, inputs=dict(cp=proof, tomco=proof, backup=proof))
    with pytest.raises(ValueError, match='Full RSP'):
        cp.observe(rsp, qmp, FakeProcess(), 1, result)
    assert qmp.commands == [] and not result['loaded_inputs_verified']


@pytest.mark.parametrize('packet,expected',[
    (b'T05core:04;',b'04'),(b'T05thread:02;',b'02'),
    (b'T05thread:03;core:03;',b'03'),
])
def test_real_qemu_stop_identity_binds_only_enumerated_cpu(packet,expected):
    assert cp.stop_thread(packet,[b'01',b'02',b'03',b'04'])==expected


@pytest.mark.parametrize('packet',[
    b'T05core:00;',b'T05core:05;',b'T05core:zz;',b'S05',
    b'T05thread:01;core:04;',b'T05core:01;core:02;',
    b'T05thread:01;thread:02;',b'T05thread:ff;',
])
def test_stop_identity_unknown_conflicting_or_duplicate_is_rejected(packet):
    with pytest.raises(ValueError):cp.stop_thread(packet,[b'01',b'02',b'03',b'04'])


def test_stop_core_ambiguity_is_not_guessed_by_pc():
    with pytest.raises(ValueError,match='ambiguous'):
        cp.stop_thread(b'T05core:04;',[b'p1.04',b'p2.04',b'02',b'03'])


@pytest.mark.parametrize('stop_packet',[b'T05thread:1;',b'T05core:01;'])
def test_qmp_paused_boundary_finds_first_abort_without_async_rsp(stop_packet,monkeypatch):
    owner=dict(owner_pid=2468,start_ticks='123',qemu_pid=2469,qemu_start_ticks='456',
               claim_sha256='a'*64,run_owner_sha256='b'*64)
    monkeypatch.setattr(cp,'check_external_ap_owner',lambda result:owner)
    monkeypatch.setattr(cp,'external_ap_cont_lock',lambda owner:nullcontext())
    monkeypatch.setattr(cp,'pidfd_exited',lambda fd:False)
    running = {'continued': False}
    commands = []

    def request(payload):
        if payload == b'?':
            return stop_packet
        if payload == b'qfThreadInfo':
            return b'm1,2,3,4'
        if payload == b'qsThreadInfo':
            return b'l'
        if payload == b'g':
            words = [0] * 17
            words[13:17] = [0x1800000, 0xbef432, cp.ABORT if running['continued'] else cp.CP_ADDRESS, 0x13]
            return struct.pack('<17I', *words).hex().encode('ascii')
        assert payload.startswith((b'Hg', b'Z1'))
        return b'OK'

    def execute(command):
        commands.append(command)
        if command == 'cont':
            running['continued'] = True
        return dict(running=False, status='debug') if command == 'query-status' else {}

    rsp = SimpleNamespace(request=request, mode=lambda physical: None,
                          read=lambda address, size: b'yes' if size == 3 else bytes(size))
    proof = dict(size=3, sha256=digest(b'yes'))
    result = dict(loaded_inputs_verified=False, original_cp_execution_observed=False,
                  receiver_entry_observed=False, first_data_abort_observed=False, window_completed=False,
                  inputs=dict(cp=proof, tomco=proof, backup=proof))
    cp.observe(rsp,SimpleNamespace(execute=execute),FakeProcess(),1,result,
               ap_vm_pidfd={'owner':986,'qemu':987})
    assert result['loaded_inputs_verified'] and result['first_data_abort_observed']
    assert result['original_cp_execution_observed'] and not result['window_completed']
    assert result['observations'][0]['kind'] == 'first-data-abort'
    assert result['final_state']['complete'] and commands.count('cont') == 1


def test_guarded_cp_cont_order_and_ap_exit_stop(monkeypatch):
    owner=dict(owner_pid=2468,start_ticks='123',qemu_pid=2469,qemu_start_ticks='456',
               claim_sha256='a'*64,run_owner_sha256='b'*64)
    events=[];result={'external_ap_before_inputs':owner}
    class QMP:
        def execute(self,command):
            events.append(('qmp',command))
            return {'running':False} if command=='query-status' else {}
    checks=iter((owner,owner))
    monkeypatch.setattr(cp,'check_external_ap_owner',lambda result:(events.append('owner-check'),next(checks))[1])
    @contextmanager
    def lock(value):
        assert value==owner;events.append('lock-enter')
        try:yield
        finally:events.append('lock-exit')
    monkeypatch.setattr(cp,'external_ap_cont_lock',lock)
    readiness=iter((False,False,False,False,False,False))
    monkeypatch.setattr(cp,'pidfd_exited',lambda fd:(events.append(('pidfd-check',fd)),next(readiness))[1])
    fds={'owner':123,'qemu':124}
    cp.continue_cp(QMP(),result,fds,'initial')
    assert events==[('qmp','query-status'),'owner-check',('pidfd-check',123),('pidfd-check',124),'lock-enter',
                    'owner-check',('pidfd-check',123),('pidfd-check',124),('qmp','cont'),
                    ('pidfd-check',123),('pidfd-check',124),'lock-exit']
    assert len(result['external_ap_cont_attempts'])==1


def test_guarded_cp_cont_refuses_lock_held_or_ap_qemu_exit(monkeypatch):
    owner=dict(owner_pid=2468,start_ticks='123',qemu_pid=2469,qemu_start_ticks='456',
               claim_sha256='a'*64,run_owner_sha256='b'*64)
    result={'external_ap_before_inputs':owner};commands=[]
    qmp=SimpleNamespace(execute=lambda command:(commands.append(command) or {'running':False}))
    monkeypatch.setattr(cp,'check_external_ap_owner',lambda result:owner)
    monkeypatch.setattr(cp,'pidfd_exited',lambda fd:False)
    @contextmanager
    def busy_lock(value):
        raise ValueError('AP shutdown owns the run lock')
        yield
    monkeypatch.setattr(cp,'external_ap_cont_lock',busy_lock)
    fds={'owner':123,'qemu':124}
    with pytest.raises(ValueError,match='run lock'):cp.continue_cp(qmp,result,fds,'initial')
    assert commands==['query-status']
    commands.clear()
    @contextmanager
    def free_lock(value):yield
    monkeypatch.setattr(cp,'external_ap_cont_lock',free_lock)
    readings=iter((False,False,False,False,False,True))
    monkeypatch.setattr(cp,'pidfd_exited',lambda fd:next(readings))
    with pytest.raises(ValueError,match='exited during CP cont'):cp.continue_cp(qmp,result,fds,'initial')
    assert commands==['query-status','cont','stop']


def test_observe_finalization_error_does_not_mask_ap_owner_exit(monkeypatch):
    owner=dict(owner_pid=2468,start_ticks='123',qemu_pid=2469,qemu_start_ticks='456',
               claim_sha256='a'*64,run_owner_sha256='b'*64)
    monkeypatch.setattr(cp,'check_external_ap_owner',lambda result:owner)
    monkeypatch.setattr(cp,'external_ap_cont_lock',lambda value:nullcontext())
    pidfd_checks={'count':0}
    def exited(fd):
        pidfd_checks['count']+=1
        return pidfd_checks['count']==7
    monkeypatch.setattr(cp,'pidfd_exited',exited)
    words=[0]*17;words[13:17]=[0x1800000,0x1801000,cp.CP_ADDRESS,0x13]
    replies={b'?':b'T05thread:1;',b'qfThreadInfo':b'm1,2,3,4',b'qsThreadInfo':b'l',
             b'g':struct.pack('<17I',*words).hex().encode()}
    def request(packet):
        if packet in replies:return replies[packet]
        return b'OK'
    rsp=SimpleNamespace(request=request,mode=lambda physical:None,
                        read=lambda address,size:b'yes' if size==3 else bytes(size))
    commands=[]
    def execute(command):
        commands.append(command)
        if command=='stop':raise EOFError('CP QMP lost during final stop')
        return {'running':False} if command=='query-status' else {}
    proof={'size':3,'sha256':digest(b'yes')}
    result={'external_ap_before_inputs':owner,'inputs':dict(cp=proof,tomco=proof,backup=proof),
            'loaded_inputs_verified':False,'errors':[]}
    with pytest.raises(ValueError,match='owner or QEMU exited while original CP was running'):
        cp.observe(rsp,SimpleNamespace(execute=execute),FakeProcess(),1,result,{'owner':12,'qemu':13})
    assert commands==['query-status','cont','stop']
    assert 'CP QMP lost' in result['errors'][0]['observe_finalization_error']


def test_external_ap_exit_after_full_readback_never_continues_cp(monkeypatch):
    words=[0]*17;words[15],words[16]=cp.CP_ADDRESS,0x13
    replies={b'?':b'T05core:01;',b'qfThreadInfo':b'm1,2,3,4',b'qsThreadInfo':b'l',
             b'g':struct.pack('<17I',*words).hex().encode()}
    rsp=SimpleNamespace(request=lambda packet:b'OK' if packet.startswith((b'Hg',b'Z1')) else replies[packet],
                        mode=lambda physical:None,read=lambda address,size:b'yes')
    def dead(result):raise ValueError('External AP owner exited during full CP verification')
    monkeypatch.setattr(cp,'check_external_ap_owner',dead)
    proof={'size':3,'sha256':digest(b'yes')};result={'inputs':dict(cp=proof,tomco=proof,backup=proof),'loaded_inputs_verified':False}
    commands=[];qmp=SimpleNamespace(execute=lambda command:(commands.append(command) or {'running':False}))
    with pytest.raises(ValueError,match='External AP owner exited'):cp.observe(rsp,qmp,FakeProcess(),1,result)
    assert result['loaded_inputs_verified'] and commands==['query-status']


class FakeSocket:
    def __init__(self, data=b''):
        self.data, self.sent = data, []

    def settimeout(self, timeout):
        pass

    def recv(self, amount):
        data, self.data = self.data[:amount], self.data[amount:]
        return data

    def sendall(self, raw):
        self.sent.append(raw)


def rsp_frame(raw):
    return b'$' + raw + b'#' + f'{sum(raw) % 256:02x}'.encode('ascii')


def test_broker_rsp_keeps_asynchronous_stop_wire_and_original_checksum_validation():
    records = []
    RSP, _ = cp.protocol_classes(records)
    rsp = RSP.__new__(RSP)
    packet = b'T05thread:1;'
    wire = rsp_frame(packet)
    rsp.socket = FakeSocket(b'+' + wire)
    rsp.buffer, rsp.packet_size = bytearray(), 1024
    assert rsp.receive_stop(time.monotonic() + 3) == packet
    assert records[-1]['rsp_stop_hex'] == packet.hex() and records[-1]['raw_wire_hex'] == wire.hex()
    assert rsp.socket.sent == [b'+']
    rsp.socket = FakeSocket(b'$T05thread:1;#00')
    with pytest.raises(ValueError, match='checksum'):
        rsp.receive_stop(time.monotonic() + 3)
    assert records[-1]['raw_wire_hex'] == b'$T05thread:1;#00'.hex()


@pytest.mark.parametrize(('supported', 'expected'), [
    (b'PacketSize=20020;Qqemu.PhyMemMode+', 131104),
    (b'PacketSize=10000;Qqemu.PhyMemMode+', 65536),
    (b'PacketSize=40000;Qqemu.PhyMemMode+', 131104),
])
def test_cp_rsp_packet_size_respects_qemu_limit(supported, expected):
    assert cp.checked_rsp_packet_size(supported) == expected


@pytest.mark.parametrize('supported', [
    b'Qqemu.PhyMemMode+', b'PacketSize=20020;PacketSize=20020',
    b'PacketSize=7f', b'PacketSize=100001', b'PacketSize=not-hex',
])
def test_cp_rsp_packet_size_rejects_invalid_negotiation(supported):
    with pytest.raises(ValueError):
        cp.checked_rsp_packet_size(supported)


def test_cp_rsp_uses_negotiated_limit_for_one_complete_64k_read(monkeypatch):
    records=[];RSP,_=cp.protocol_classes(records);base=RSP.__mro__[1]
    requests=[]

    def request(payload):
        requests.append(payload)
        if payload==b'qSupported':
            return b'PacketSize=20020;Qqemu.PhyMemMode+'
        address,size=(int(value,16) for value in payload[1:].split(b','))
        return (b'Z'*size).hex().encode('ascii')

    def init(self,path,timeout=2.0,*,expected_pid=None):
        self.packet_size=65536
        self.request=request

    monkeypatch.setattr(base,'__init__',init)
    rsp=RSP('unused')
    data=rsp.read(0x108000,64*1024)
    assert data==b'Z'*(64*1024)
    assert requests==[b'qSupported',b'm108000,10000']


def test_broker_qmp_quit_whitelist_retains_every_original_event():
    records = []
    _, QMP = cp.protocol_classes(records)
    qmp = QMP.__new__(QMP)
    event = dict(event='RESET', data={'guest': True}, timestamp={'seconds': 1, 'microseconds': 2})
    shutdown_event = dict(event='SHUTDOWN', data={'guest': False})
    qmp.socket = FakeSocket((json.dumps(event) + '\n' + json.dumps(dict(id=1, **{'return': {}})) + '\n'
                            + json.dumps(shutdown_event) + '\n').encode())
    qmp.buffer, qmp.serial, qmp.timeout = bytearray(), 0, 3
    assert qmp.execute('quit') == {}
    assert records[1]['qmp'] == event
    assert qmp.drain_after_exit()=='eof'
    assert records[-2]['qmp'] == shutdown_event
    assert records[-1]['qmp_transport_terminal']=='eof'
    assert json.loads(qmp.socket.sent[0]) == dict(execute='quit', id=1)
    with pytest.raises(ValueError, match='Unapproved'):
        qmp.execute('human-monitor-command', {'command-line': 'quit'})


class FakeResetSocket(FakeSocket):
    def recv(self,amount):
        if not self.data:raise ConnectionResetError(104,'owned peer closed after quit')
        return super().recv(amount)


@pytest.mark.parametrize('partial',[b'',b'{"event":'])
def test_post_exit_qmp_reset_is_terminal_only_without_partial_json(partial):
    records=[];_,QMP=cp.protocol_classes(records);qmp=QMP.__new__(QMP)
    qmp.socket=FakeResetSocket();qmp.buffer=bytearray(partial);qmp.timeout=3
    if partial:
        with pytest.raises(ValueError,match='Partial final QMP'):qmp.drain_after_exit()
        assert qmp.buffer==partial
    else:
        assert qmp.drain_after_exit()=='peer-reset-after-exit'
        assert records[-1]['qmp_transport_terminal']=='peer-reset-after-exit'


class FakeProcess:
    pid = 987654
    returncode = None

    def poll(self):
        return self.returncode

    def wait(self, timeout):
        self.returncode = 0
        return 0


class FakeClient:
    def __init__(self, fail=False):
        self.fail, self.closed, self.commands = fail, False, []

    def execute(self, command):
        self.commands.append(command)
        if self.fail:
            raise EOFError('original quit response missing')
        return {}

    def drain_after_exit(self):
        return 'eof'

    def close(self):
        self.closed = True


def test_quit_failure_retains_live_pid_clients_and_pair_lease(monkeypatch, capsys):
    monkeypatch.setattr(cp, 'RETAINED', [])
    process, qmp, rsp, stream, result = FakeProcess(), FakeClient(True), FakeClient(), FakeClient(), {}
    assert cp.shutdown(process, qmp, rsp, [stream], result) is False
    receipt = result['shutdown']
    assert receipt['alive'] and receipt['retained'] and not receipt['qmp_quit_confirmed']
    assert not receipt['cp_process_released'] and not receipt['pair_lease_released'] and receipt['signals'] == []
    assert 'original quit response missing' in receipt['error']
    assert not qmp.closed and not rsp.closed and not stream.closed
    assert cp.RETAINED[0]['process'] is process and cp.RETAINED[0]['qmp'] is qmp
    assert 'retained' in capsys.readouterr().err and qmp.commands == ['quit']


def test_quit_ack_and_rc_zero_release_only_cp_process():
    process, qmp, rsp, stream, result = FakeProcess(), FakeClient(), FakeClient(), FakeClient(), {}
    assert cp.shutdown(process, qmp, rsp, [stream], result) is True
    receipt = result['shutdown']
    assert receipt['qmp_quit_confirmed'] and receipt['returncode'] == 0 and receipt['cp_process_released']
    assert not receipt['alive'] and not receipt['pair_lease_released'] and receipt['signals'] == []
    assert qmp.closed and rsp.closed and stream.closed


def test_quit_ack_rc0_and_clean_peer_reset_records_reset_not_eof():
    process,qmp,result=FakeProcess(),FakeClient(),{}
    qmp.drain_after_exit=lambda:'peer-reset-after-exit'
    assert cp.shutdown(process,qmp,None,[],result)
    assert result['shutdown']['qmp_transport_terminal']=='peer-reset-after-exit'
    assert not result['shutdown']['qmp_eof_observed']
    assert not result['shutdown']['pair_lease_released']


def test_quit_ack_but_wait_timeout_keeps_live_handles(monkeypatch):
    monkeypatch.setattr(cp, 'RETAINED', [])
    process, qmp, result = FakeProcess(), FakeClient(), {}

    def timeout_wait(timeout):
        raise cp.subprocess.TimeoutExpired('owned-cp', timeout)

    process.wait = timeout_wait
    assert not cp.shutdown(process, qmp, None, [], result)
    receipt = result['shutdown']
    assert receipt['qmp_quit_confirmed'] and receipt['alive'] and receipt['retained']
    assert not receipt['cp_process_released'] and not receipt['pair_lease_released']
    assert not qmp.closed and cp.RETAINED[0]['process'] is process and receipt['signals'] == []


def test_exit_zero_without_quit_ack_cannot_be_called_released():
    process, result = FakeProcess(), {}
    process.returncode = 0
    assert not cp.shutdown(process, None, None, [], result)
    assert not result['shutdown']['cp_process_released'] and not result['shutdown']['pair_lease_released']
