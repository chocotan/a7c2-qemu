"""Focused host guards plus an opt-in real 64 MiB CPU/FD-QMP/disk transaction.

RETAINED_EXECUTION_ACTUAL=1 enables a separate no-OS fixture schema. It never
passes synthetic evidence to CameraExecution.capture. The disk API's console
marker is a clearly labelled host contract fixture, not a guest shell sync.
The CPU actually waits across migration, then consumes a gate and writes a
fresh canary after cont. No original kernel/AP, UI, host module or USB export.
"""
import copy
import hashlib
import json
import os
from pathlib import Path
import runpy
import shutil
import socket
import subprocess
import tempfile
from types import SimpleNamespace
import time

import pytest

HERE = Path(__file__).resolve().parent
API = runpy.run_path(str(HERE/'newretained-camera-execution.py'))
DS, R = API['DS'], API['R']
G = API['CameraExecution'].__init__.__globals__
DT = runpy.run_path(str(HERE/'test-retained-disk-state.py'))
disk_base = DT['disk_base']
HELPER = runpy.run_path(str(HERE/'persistent-flash/flash-migration-qtest.py'))


@pytest.fixture
def instance(disk_base, tmp_path, monkeypatch):
    base, writer = disk_base
    path = tmp_path/'instance'
    shutil.copytree(base, path)
    path.chmod(0o700)
    output = tmp_path/'private-output'
    output.mkdir(mode=0o700)
    monkeypatch.setitem(DS['GEOMETRY'], 'write_camera_wire', writer)
    return path, output


def marker(tx, output):
    path = output/'synthetic-contract-marker.console'
    path.write_text('A7C2_RETAINED_GUEST_SYNC nonce='+tx.guest_sync_nonce+' sync_rc=0\n')
    path.chmod(0o600)
    return path


def test_real_transaction_required_never_bool_or_closed(instance):
    for fake in (True, False, {}, SimpleNamespace(fd=3)):
        with pytest.raises(ValueError, match='real live DiskTransaction'):
            API['_live_tx'](fake)
    path, output = instance
    # A separately loaded official API is valid; runpy class object IDs differ.
    with DT['API']['transaction'](path, output) as tx:
        API['_live_tx'](tx)
    with pytest.raises(ValueError, match='closed'):
        API['_live_tx'](tx)


@pytest.mark.parametrize('mutation', ['disk', 'generation', 'wire', 'partition', 'fd'])
def test_popen_boundary_rechecks_live_state(instance, mutation):
    path, output = instance
    with DS['transaction'](path, output) as tx:
        binding = tx.snapshot_disk(DT['StatusQMP'](), host_run='source', migration_generation=5,
                                  guest_sync_evidence=marker(tx, output))
        API['_disk_now'](tx, binding)
        if mutation == 'disk':
            DT['mutate_byte'](path/'camera.emmc', binding['disk']['size']-1)
        elif mutation == 'partition':
            DT['mutate_byte'](path/'camera.emmc', binding['partition_bindings'][2]['offset']+100)
        elif mutation == 'generation':
            current = path/'instance.json'
            state = json.loads(current.read_text())
            state['generation'] += 1
            DS['DISK']['save'](current, state)
        elif mutation == 'wire':
            DT['mutate_byte'](path/'persistent-geometry.bin', 31)
        else:
            fd = tx.fd
            os.close(fd)
            assert os.open(path/'camera.emmc', os.O_RDWR) == fd
        with pytest.raises(ValueError):
            API['_disk_now'](tx, binding)


def test_sync_evidence_mode_stays_0600(instance):
    path, output = instance
    with DS['transaction'](path, output) as tx:
        evidence = marker(tx, output)
        evidence.chmod(0o644)
        with pytest.raises(DS['DiskStateError'], match='mode 0600'):
            tx.snapshot_disk(DT['StatusQMP'](), host_run='source', migration_generation=1,
                             guest_sync_evidence=evidence)


BASE_COMMAND = ['/tools/qemu-system-aarch64', '-machine', 'virt,secure=off', '-cpu', 'cortex-a35',
                '-accel', 'tcg', '-m', '64M', '-display', 'none', '-nic', 'none',
                '-monitor', 'none', '-serial', 'stdio', '-kernel', '/kernel.img']
BASE_OPTIONS = [['--bind', '/private/instance', '/instance'], ['--bind', '/private/output', '/out']]


@pytest.mark.parametrize('extra', [('-drive', 'file=/dev/sda'), ('-device', 'usb-host,vendorid=1'),
    ('-device', 'sony-ui-input,chardev=keys'), ('-netdev', 'user,id=n'), ('-incoming', 'defer'),
    ('-readconfig', '/host/unsafe'), ('-object', 'memory-backend-file,id=m,mem-path=/dev/mem'),
    ('-qtest', 'unix:/tmp/test'), ('-S',), ('-blockdev', 'driver=raw'), ('-plugin', '/host/inject.so')])
def test_source_passthrough_or_unreviewed_command_refuses(extra):
    with pytest.raises(ValueError, match='Unreviewed'):
        API['_validate_command'](BASE_OPTIONS, BASE_COMMAND+list(extra))


def test_existing_envelope_has_no_shell_or_arbitrary_token():
    argv = ['bwrap', '--unshare-all', '--die-with-parent', '--clearenv', '--ro-bind', '/usr', '/usr']+BASE_COMMAND
    options, command = API['envelope'](argv)
    assert command == BASE_COMMAND and options[-1] == ['--ro-bind', '/usr', '/usr']
    for bad in (['bash', '-c', 'true'], ['bwrap', '--share-net']+BASE_COMMAND,
                ['bwrap', '--unshare-all', '--clearenv']+BASE_COMMAND):
        with pytest.raises(ValueError):
            API['envelope'](bad)


def test_mtree_order_only_normalization_preserves_parent_and_address():
    first = 'address-space: cpu\naddress-space: memory\n  0000-ffff: system\n    0010-001f: child\n'
    alias_order = 'address-space: memory\naddress-space: cpu\n  0000-ffff: system\n    0010-001f: child\n'
    second = 'memory-region: mmio\n  0020-002f: device\n'
    digest = API['_mtree_digest']
    assert digest(first+'\n'+second) == digest(second+'\n'+alias_order)
    assert digest(first+'\n'+second) != digest(first.replace('    0010', '  0010')+'\n'+second)
    assert digest(first+'\n'+second) != digest(first.replace('0010-001f', '0011-001f')+'\n'+second)


class TopologyQMP:
    def __init__(self, *, usb='', flash=True, extra=None, blocks=None):
        self.usb, self.flash, self.extra, self.blocks = usb, flash, extra, blocks or []
    def __call__(self, command, arguments=None):
        if command == 'qom-list':
            if arguments['path'] == '/machine':
                rows = [dict(name='usb', type='child<usb_dwc3>'), dict(name='flash', type='child<sony-persistent-flash>')]
                return rows+([dict(name='bad', type='child<'+self.extra+'>')] if self.extra else [])
            return []
        if command == 'human-monitor-command':
            return self.usb if arguments['command-line'] == 'info usb' else 'address-space: memory\n  0000-ffff (prio 0, i/o): upstream dwc3\n'
        if command == 'qom-get':
            return self.flash
        if command == 'query-block':
            return self.blocks
        if command in ('query-block-jobs', 'query-migrate-capabilities'):
            return []
        raise AssertionError(command)


@pytest.mark.parametrize('options', [dict(usb='Device 0.1, usb-host'), dict(flash=False),
    dict(extra='sony-dwc3'), dict(extra='sony-dwc3-bridge'), dict(extra='usb-host'),
    dict(extra='sony-ui-input'), dict(extra='vfio-pci'), dict(blocks=[{'device':'external'}])])
def test_actual_topology_guard_rejects_foreign_state(options):
    with pytest.raises(ValueError):
        API['topology'](TopologyQMP(**options))


def test_audit_kind_and_external_contract_cannot_be_relabelled():
    launch = dict(combo_binding=dict(source_tree_sha256=API['LAUNCH']['UPSTREAM_SOURCE_SHA']),
                  source_class='diagnostic-derived-retained-camera')
    rows = [dict(path='/machine/'+str(i)+'/'+str(j), type=kind)
            for i, (kind, count) in enumerate(API['SOURCE_COUNTS'].items()) for j in range(count)]
    actual = dict(objects=rows, inventory_sha256=R['_digest'](rows))
    review = API['source_audit'](launch, actual)
    API['audit_contract'](review, actual, launch)
    for key, value in (('external_state', 'none'), ('kind', 'synthetic-no-os'), ('profile', 'other'),
                       ('qemu_sha256', 'f'*64), ('inventory_sha256', '0'*64)):
        with pytest.raises(ValueError):
            API['audit_contract'](dict(review, **{key:value}), actual, launch)
    for bad in (rows[:-1], rows+[dict(path='/machine/foreign', type='child<unknown>')]):
        with pytest.raises(ValueError, match='type/count'):
            API['source_audit'](launch, dict(actual, objects=bad))
    with pytest.raises(ValueError):
        API['audit_contract'](True, actual, launch)


def test_source_binary_and_assets_checked_before_popen(tmp_path):
    binary, script, dtb = [tmp_path/name for name in ('qemu', 'launch.sh', 'virt.dtb')]
    for p in (binary, script, dtb):
        p.write_bytes(p.name.encode())
    launch = dict(profile=API['PROFILE'], qemu_sha256=API['QEMU_SHA'], incoming=False,
        schema=API['LAUNCH']['SCHEMA'], qemu_binary=str(binary), script=str(script),
        script_sha256=hashlib.sha256(script.read_bytes()).hexdigest(),
        dtb=str(dtb), dtb_sha256=hashlib.sha256(dtb.read_bytes()).hexdigest(),
        template_inputs=[], launch_inputs=[])
    with pytest.raises(ValueError, match='source QEMU bytes'):
        API['_assets'](launch)


def test_transfer_does_not_cancel_failed_or_completed_migrations():
    class QMP:
        def __init__(self, state):
            self.state, self.calls = state, []
        def getfd(self, name, fd):
            raise RuntimeError('injected getfd failure')
        def __call__(self, cmd, arguments=None):
            self.calls.append(cmd)
            return dict(status=self.state)
    import tempfile
    for state in ('none', 'failed', 'completed', 'cancelled', 'active'):
        qmp = QMP(state)
        with tempfile.TemporaryFile() as stream, pytest.raises(RuntimeError, match='getfd'):
            API['transfer'](qmp, dict(qmp=[]), stream, outgoing=True)
        assert ('migrate_cancel' in qmp.calls) is (state == 'active')


def test_both_migration_directions_remain_in_later_receipts():
    payload=b'QEVM\x00\x00\x00\x03bounded-stream'
    class QMP:
        direction = None
        def getfd(self, name, fd):
            self.fd=os.dup(fd)
        def __call__(self, command, arguments=None):
            if command in ('migrate','migrate-incoming'):
                self.direction='outgoing' if command=='migrate' else 'incoming'
                with socket.socket(fileno=self.fd) as peer:
                    if self.direction=='outgoing':
                        peer.sendall(payload)
                    else:
                        received=bytearray()
                        while data:=peer.recv(1024):
                            received.extend(data)
                        assert bytes(received)==payload
                return {}
            assert command=='query-migrate'
            return {'status':'completed','direction':self.direction}
    qmp=QMP();receipt={'qmp':[]}
    with tempfile.TemporaryFile() as stream:
        first=API['transfer'](qmp,receipt,stream,outgoing=True)
        second=API['transfer'](qmp,receipt,stream,outgoing=False)
    assert first==second==(hashlib.sha256(payload).hexdigest(),len(payload))
    assert receipt['migration_outgoing']=={'status':'completed','direction':'outgoing'}
    assert receipt['migration_incoming']==receipt['migration']=={'status':'completed','direction':'incoming'}


def test_production_capture_rejects_synthetic_schema(instance):
    path, output = instance
    with DS['transaction'](path, output) as tx:
        obj = object.__new__(API['CameraExecution'])
        obj.tx, obj.captured, obj.target, obj.failed = tx, False, None, False
        obj.run, obj.source, obj.identity = 'source', SimpleNamespace(pid=123), {'peer': {'pid':456}}
        obj.receipt = {'qmp':[], 'original_ap_restore_verified':False}
        with pytest.raises(ValueError, match='Real caller-console'):
            obj.capture(dict(schema='a7c2-retained-no-os-fixture-v1', kind='no-os-no-filesystem'))
        assert not (output/'snapshot.partial').exists() and obj.failed
        assert next(output.glob('execution-failure-*.json')).stat().st_mode & 0o777 == 0o600


@pytest.mark.parametrize('state', ['running', 'postmigrate', 'inmigrate'])
def test_wrong_paused_state_is_not_a_boolean(state):
    with pytest.raises(ValueError, match='must remain paused'):
        API['_status'](DT['StatusQMP'](state), 'paused')


def test_stream_corruption_rejected_before_restore(instance):
    path, output = instance
    with DS['transaction'](path, output) as tx:
        binding = tx.snapshot_disk(DT['StatusQMP'](), host_run='s', migration_generation=1,
                                  guest_sync_evidence=marker(tx, output))
        for phase, state in (('pre-migration', 'paused'), ('post-migration', 'postmigrate')):
            tx.verify(binding, DT['StatusQMP'](state), phase=phase, host_run='s', migration_generation=1)
        stream = output/'snapshot.partial'
        stream.write_bytes(b'QEVM\x00\x00\x00\x03original-content')
        stream.chmod(0o600)
        with stream.open('rb') as f:
            identity = R['_hash'](f)
            record = DS['_record'](f.fileno())
        with stream.open('ab') as f:
            f.write(b'corrupt')
        with pytest.raises(ValueError, match='stream file identity'):
            API['load_paused'](tx, DT['StatusQMP']('inmigrate'), binding, identity,
                               run='t', generation=2, receipt={'qmp':[], 'snapshot_file_record':record})


class FixtureVM(HELPER['Qemu']):
    def __init__(self, tx, output, binary, program, label, *, incoming=False):
        self.out, self.label, self.events, self.transcript = output, label, [], []
        run = Path(tempfile.mkdtemp(prefix='a7rex-'))
        self.temp = SimpleNamespace(cleanup=lambda: None)
        self.owner_socket_dir = str(run)
        self.log = (output/(label+'.log')).open('xb')
        info = os.fstat(tx.fd)
        env = dict(API['LAUNCH']['UPSTREAM_USB'], QEMU_A7PF_PROFILE=API['PROFILE'],
            QEMU_A7PF_RETAINED_STATE='1', QEMU_A7PF_FD=str(tx.fd), QEMU_A7PF_DEV=str(info.st_dev),
            QEMU_A7PF_INO=str(info.st_ino), QEMU_SONY_TIMERS='1', LC_ALL='C')
        command = ['bwrap', '--unshare-all', '--die-with-parent', '--new-session', '--clearenv',
            '--bind', str(tx._leased['path']), '/instance', '--bind', str(run), '/out',
            '--ro-bind', '/usr', '/usr', '--symlink', 'usr/lib', '/lib', '--symlink', 'usr/lib', '/lib64',
            '--proc', '/proc', '--dev', '/dev', '--tmpfs', '/tmp',
            '--ro-bind', str(binary.parent), '/tools', '--ro-bind', str(program), '/kernel.img']
        for key, value in env.items():
            command += ['--setenv', key, value]
        command += ['/tools/qemu-system-aarch64', '-machine', 'virt,secure=off,gic-version=2',
            '-cpu', 'cortex-a53', '-accel', 'tcg', '-m', '64M', '-nodefaults', '-display', 'none',
            '-nic', 'none', '-monitor', 'none', '-serial', 'none', '-kernel', '/kernel.img',
            '-S', '-name', label, '-qmp', 'unix:/out/qmp.sock,server=on,wait=off',
            '-qtest', 'unix:/out/test.sock,server=on,wait=off']
        if incoming:
            command += ['-incoming', 'defer']
        self.process = subprocess.Popen(command, pass_fds=tx.pass_fds, env={'PATH': os.defpath},
                                        stdin=subprocess.DEVNULL, stdout=self.log, stderr=subprocess.STDOUT)
        tx.children.append(self.process)
        self.owner = dict(pid=self.process.pid, command=command, signals_sent=[], fixture_only=True,
                          socket_directory=self.owner_socket_dir)
        self.qmp_api = API['_connect'](run/'qmp.sock', self.process)
        self.qmp, self.qmpfile = self.qmp_api.sock, self.qmp_api.stream
        self.socket = self.connect(run/'test.sock')
        self.file = self.socket.makefile('rwb', buffering=0)

    def qmpcommand(self, name, arguments=None):
        return self.qmp_api(name, arguments)

    def normal_close(self):
        result = API['_quit'](self.process, self.qmp_api)
        for stream in (self.file, self.socket, self.qmpfile, self.qmp, self.log):
            stream.close()
        self.owner.update(result)
        return self.owner


def wait_word(vm, address, expected):
    deadline = time.monotonic()+10
    while time.monotonic() < deadline:
        if int(vm.cmd('readq '+hex(address)), 0) == expected:
            return
        time.sleep(.01)
    raise AssertionError('Actual guest CPU canary did not reach '+str(expected))


@pytest.mark.skipif(os.environ.get('RETAINED_EXECUTION_ACTUAL') != '1', reason='explicit opt-in for real small QEMU')
def test_actual_same_lease_disk_ram_cpu_canary(instance):
    path, output = instance
    result = dict(schema='a7c2-retained-no-os-fixture-v1', kind='no-os-no-filesystem',
        synthetic=True, guest_shell_sync_verified=False, marker_kind='host-only-disk-API-contract-fixture',
        original_ap_restore_verified=False, whole_machine_verified=False, capture_verified=False,
        production_capture_executed=False, external_state=API['EXTERNAL'], qmp=[], owners=[])
    stage = API['LAUNCH']['UPSTREAM_COMBO'].parent
    binary = stage/'build/qemu-system-aarch64'
    assert API['COLD']['digest'](binary) == API['QEMU_SHA']
    source = target = None
    old_umask = os.umask(0o077)
    try:
        assembly = output/'canary.S'
        assembly.write_text('''.global _start
_start:
    movz x0, #0x3000
    movk x0, #0x4000, lsl #16
    mov x1, #0x42
    str x1, [x0]
1:  ldr x1, [x0, #8]
    cbz x1, 1b
    ldr x2, [x0, #16]
    add x2, x2, #1
    str x2, [x0, #16]
    mov x3, #0x5a
    str x3, [x0, #24]
2:  b 2b
''')
        subprocess.run(['aarch64-linux-gnu-as', '-o', str(output/'canary.o'), str(assembly)], check=True)
        program = output/'canary.bin'
        subprocess.run(['aarch64-linux-gnu-objcopy', '-O', 'binary', str(output/'canary.o'), str(program)], check=True)
        with DS['transaction'](path, output) as tx:
            try:
                source = FixtureVM(tx, output, binary, program, 'source')
                source.qmpcommand('cont')
                wait_word(source, 0x40003000, 0x42)
                source.qmpcommand('stop')
                API['_status'](source.qmp_api, 'paused')
                before = API['topology'](source.qmp_api)
                result['source_mtree'] = source.qmpcommand('human-monitor-command', {'command-line':'info mtree'})
                source_identity = API['_owned_identity'](tx, {}, source.process, source.qmp_api)
                assert source_identity['qmp_name'] == dict(name='source')
                # Actual flash DMA read consumes current p7 bytes into guest RAM.
                for offset, value in ((0x10, 7), (0x18, 0), (0x20, 1), (0x24, 0x40004000), (0x14, 2)):
                    source.reg(offset, value)
                assert source.reg(0x2c) == 1
                part = next(r for r in tx._leased['geometry']['slices'] if r['id'] == 'nflasha7')
                dma = os.pread(tx.fd, 512, part['offset'])
                assert source.memory(0x40004000, 512) == dma
                binding, identity = API['save_paused'](tx, source.qmp_api, run='fixture-source', generation=7,
                    evidence_path=marker(tx, output), receipt=result)
                assert binding['whole_disk_sha256'] == DS['DISK']['hashed'](tx.fd)
                assert binding['disk_generation'] == 0
                result['owners'].append(source.normal_close())
                assert source.process.poll() == 0
                source = None
                API['_disk_now'](tx, binding)
                with pytest.raises(BlockingIOError):
                    with DS['DISK']['lease'](path):
                        pytest.fail('second lease acquired during incoming transaction')
                target = FixtureVM(tx, output, binary, program, 'target', incoming=True)
                API['_status'](target.qmp_api, 'inmigrate')
                target_identity = API['_owned_identity'](tx, {}, target.process, target.qmp_api)
                assert source_identity['peer']['pid'] != target_identity['peer']['pid']
                API['load_paused'](tx, target.qmp_api, binding, identity, run='fixture-target', generation=8, receipt=result)
                result['target_mtree'] = target.qmpcommand('human-monitor-command', {'command-line':'info mtree'})
                assert API['topology'](target.qmp_api) == before
                assert target.memory(0x40004000, 512) == dma
                assert int(target.cmd('readq 0x40003000'), 0) == 0x42
                assert int(target.cmd('readq 0x40003010'), 0) == 0
                API['_disk_now'](tx, binding)
                # Only the resumed guest CPU writes counter=1 and canary=0x5a.
                target.cmd('writeq 0x40003008 1')
                target.qmpcommand('cont')
                wait_word(target, 0x40003018, 0x5a)
                assert int(target.cmd('readq 0x40003010'), 0) == 1
                target.qmpcommand('stop')
                assert DS['DISK']['hashed'](tx.fd) == binding['whole_disk_sha256']
                result['owners'].append(target.normal_close())
                target = None
                assert tx._next_phase == 4
                with pytest.raises(BlockingIOError):
                    with DS['DISK']['lease'](path):
                        pytest.fail('lease released before context exit')
                result.update(status='passed', actual_ram_stream=True, same_lease_held_through_both_exits=True,
                    source_postmigrate=True, target_loaded_paused=True, actual_cpu_cont_canary=True,
                    dma_ram_readback_exact=True, disk_generation=0, source_migration_generation=7,
                    target_migration_generation=8, stream_sha256=identity[0], stream_bytes=identity[1],
                    disk_sha256=binding['whole_disk_sha256'], source_topology=before,
                    qemu_sha256=API['QEMU_SHA'], source_identity=source_identity,
                    target_identity=target_identity)
            finally:
                for vm in (source, target):
                    if vm is not None:
                        result['owners'].append(vm.normal_close())
    except BaseException as error:
        result.update(status='failed', error=repr(error))
        raise
    finally:
        evidence = Path(os.environ.get('RETAINED_EXECUTION_EVIDENCE', str(output/'actual-result.json')))
        evidence.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(evidence, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, 'w') as stream:
            json.dump(result, stream, indent=2)
            stream.write('\n')
            stream.flush()
            os.fsync(stream.fileno())
        os.umask(old_umask)
    assert len(result['owners']) == 2
    assert all(o['returncode'] == 0 and o['signals_sent'] == [] and 'quit_response' in o for o in result['owners'])
    with DS['DISK']['lease'](path):
        pass
