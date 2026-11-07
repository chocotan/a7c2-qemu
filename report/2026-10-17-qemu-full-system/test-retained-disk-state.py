"""Real regular-file/FD/fsync/hash transactions; QMP status/migration responses are stubbed.

No VM, physical device, host module or current user instance is opened. The only
fixture adjustment is the original wire writer's production capacity allowlist;
its validation and encoder run unchanged on a real 24+4+4 MiB camera-disk instance.
"""
import copy
import fcntl
import hashlib
import json
import os
from pathlib import Path
import runpy
import shutil
import subprocess
import sys
from types import FunctionType

import pytest

HERE = Path(__file__).resolve().parent
API = runpy.run_path(str(HERE/'retained-disk-state.py'))
DISK, BOOT = API['DISK'], API['BOOT']
FIXTURE = runpy.run_path(str(HERE/'test-camera-disk.py'))


class StatusQMP:
    def __init__(self, status='paused', migration='completed'):
        self.status, self.migration, self.calls = status, migration, []

    def __call__(self, command, arguments=None):
        assert command in ('query-status','query-migrate') and arguments is None
        self.calls.append(command)
        if command == 'query-migrate':
            return dict(status=self.migration)
        return dict(status=self.status, running=self.status == 'running')


@pytest.fixture(scope='module')
def disk_base():
    fixture = FIXTURE['CameraDiskTests'](methodName='runTest')
    fixture.setUp()
    try:
        rows, extent = DISK['parse_layout'](fixture.config.read_bytes())
        capacity = 24*1024**2
        caps = dict(pnflasha=capacity, nflashaB0=DISK['BOOT_BYTES'], nflashaB1=DISK['BOOT_BYTES'])
        caps.update({'pnflasha'+str(r['part']):r['bytes'] for r in rows if r['bytes']})
        record = fixture.root/'capacity.json'
        record.write_text(json.dumps(dict(block_devices_bytes=caps)))
        fixture.create(record)
        geometry = json.loads((fixture.output/'geometry.json').read_text())
        assert (fixture.output/'camera.emmc').stat().st_size == 32*1024**2
        writer = API['GEOMETRY']['write_camera_wire']
        with pytest.raises(ValueError, match='Unknown user extent'):
            writer(geometry, fixture.root/'production-writer-refuses-small.bin')
        # Test-only capacity allowlist substitution; use the shipped writer, not a parallel encoder.
        assert writer.__code__.co_consts.count(1922039808) == 1
        code = writer.__code__.replace(co_consts=tuple(extent if v == 1922039808 else v for v in writer.__code__.co_consts))
        fixture_writer = FunctionType(code, dict(writer.__globals__, CAPACITY=capacity), writer.__name__)
        fixture_writer(geometry, fixture.output/'persistent-geometry.bin')
        yield fixture.output, fixture_writer
    finally:
        fixture.doCleanups()


@pytest.fixture
def instance(disk_base, tmp_path, monkeypatch):
    source, writer = disk_base
    path = tmp_path/'instance'
    shutil.copytree(source, path)
    path.chmod(0o700)
    monkeypatch.setitem(API['GEOMETRY'], 'write_camera_wire', writer)
    output = tmp_path/'private-output'
    output.mkdir(mode=0o700)
    return path, output


def guest_evidence(tx, output, *, nonce=None):
    path = output/'guest-sync.console'
    path.write_bytes(('A7C2_RETAINED_GUEST_SYNC nonce='+(nonce or tx.guest_sync_nonce)+' sync_rc=0\n').encode())
    path.chmod(0o600)
    return path


def capture(tx, output, qmp=None):
    return tx.snapshot_disk(qmp or StatusQMP(), host_run='source-run', migration_generation=10,
                            guest_sync_evidence=guest_evidence(tx, output))


def verify(tx, binding, phase='pre-migration', qmp=None, **identity):
    run = 'target-run' if phase in ('pre-restore','post-restore') else 'source-run'
    generation = 11 if run == 'target-run' else 10
    status={'post-migration':'postmigrate','pre-restore':'inmigrate'}.get(phase,'paused')
    return tx.verify(binding, qmp or StatusQMP(status),
        phase=phase, **dict(dict(host_run=run, migration_generation=generation), **identity))


@pytest.mark.parametrize('status,migration', [('paused','completed'),('postmigrate','active'),('postmigrate','failed')])
def test_post_migration_requires_real_source_state_and_completion(instance,status,migration):
    path,output=instance
    with API['transaction'](path,output) as tx:
        binding=capture(tx,output)
        verify(tx,binding)
        with pytest.raises(API['DiskStateError'],match='postmigrate|migration must report completed'):
            verify(tx,binding,'post-migration',qmp=StatusQMP(status,migration))
    assert failures(output)


def mutate_byte(path, offset):
    fd = os.open(path, os.O_RDWR)
    try:
        old = os.pread(fd, 1, offset)
        assert len(old) == 1 and os.pwrite(fd, bytes([old[0] ^ 1]), offset) == 1
        os.fsync(fd)
    finally:
        os.close(fd)


def failures(output):
    paths = list(output.glob('disk-failure-*.json'))
    assert paths
    for path in paths:
        assert path.stat().st_mode & 0o777 == 0o600
        receipt = json.loads(path.read_text())
        assert receipt['status'] == 'failed' and receipt['whole_machine_verified'] is False
    return paths


def test_same_lease_all_phases_json_roundtrip_and_exact_whole_hash(instance):
    path, output = instance
    qmp = StatusQMP()
    with API['transaction'](path, output) as tx:
        assert tx.pass_fds == (tx.fd,)
        with pytest.raises(BlockingIOError):
            with DISK['lease'](path):
                pytest.fail('second writer obtained lease')
        binding = capture(tx, output, qmp)
        loaded = json.loads((output/'disk-binding.json').read_text())
        assert loaded == binding
        API['_validate'](loaded, API['BINDING_SCHEMA'])
        assert qmp.calls == ['query-status','query-status']
        assert binding['whole_disk_sha256'] == hashlib.sha256((path/'camera.emmc').read_bytes()).hexdigest()
        assert binding['whole_machine_verified'] is False
        assert binding['wire']['hex'] == binding['canonical_wire']['hex']
        for row in binding['partition_bindings']:
            view = BOOT['part'](dict(fd=tx.fd, geometry=binding['geometry']), row['id'])
            assert row['sha256'] == hashlib.sha256(os.pread(tx.fd, view.length, view.offset)).hexdigest()
        for phase in API['PHASES']:
            result = verify(tx, loaded, phase)
            assert result['disk_binding_verified'] and result['whole_machine_verified'] is False
            assert result['disk_generation'] == binding['disk_generation'] == 0
        assert json.loads((output/'disk-post-restore.json').read_text())['migration_generation'] == 11
    with DISK['lease'](path):
        pass
    assert not list(output.glob('disk-failure-*.json'))
    assert all(p.stat().st_mode & 0o777 == 0o600 for p in output.glob('*.json'))


@pytest.mark.parametrize('region', ['log','unused-tail','B0-last','B1-last','current-p15'])
def test_any_current_disk_region_mutation_is_rejected(instance, region):
    path, output = instance
    with API['transaction'](path, output) as tx:
        binding = capture(tx, output)
        geometry = binding['geometry']
        selected = {'log':'nflasha11','current-p15':'nflasha15','B0-last':'nflashaB0','B1-last':'nflashaB1'}
        if region == 'unused-tail':
            offset = geometry['user_bytes']-1
        else:
            row = next(r for r in geometry['slices'] if r['id'] == selected[region])
            offset = row['offset']+row['bytes']-1
        mutate_byte(path/'camera.emmc', offset)
        assert DISK['hashed'](tx.fd) != binding['whole_disk_sha256']
        with pytest.raises(API['DiskStateError'], match='same current disk binding'):
            verify(tx, binding)
        assert json.loads((output/'disk-binding.json').read_text()) == binding
        failures(output)


def test_capture_uses_current_p15_not_old_build_or_source_hashes(instance):
    path, output = instance
    geometry = json.loads((path/'geometry.json').read_text())
    row = next(r for r in geometry['slices'] if r['id'] == 'nflasha15')
    mutate_byte(path/'camera.emmc', row['offset']+512)
    with API['transaction'](path, output) as tx:
        binding = capture(tx, output)
        current = next(r for r in binding['partition_bindings'] if r['id'] == 'nflasha15')
        assert current['sha256'] != row['source_sha256']
        verify(tx, binding)


@pytest.mark.parametrize('drift', ['same-bytes-new-inode','readonly','hardlink','truncate','symlink',
    'generation','manifest','unknown-source','wire','geometry','metadata-new-inode','metadata-permission'])
def test_identity_and_metadata_drift_fails_and_preserves_binding(instance, drift):
    path, output = instance
    with API['transaction'](path, output) as tx:
        binding = capture(tx, output)
        disk = path/'camera.emmc'
        if drift == 'same-bytes-new-inode':
            other = output/'other.emmc'
            shutil.copyfile(disk, other)
            other.chmod(0o600)
            os.replace(other, disk)
        elif drift == 'readonly':
            disk.chmod(0o400)
        elif drift == 'hardlink':
            os.link(disk, output/'alias.emmc')
        elif drift == 'truncate':
            with disk.open('r+b') as stream:
                stream.truncate(binding['disk']['size']-1)
                os.fsync(stream.fileno())
        elif drift == 'symlink':
            saved = output/'saved.emmc'
            disk.rename(saved)
            disk.symlink_to(saved)
        elif drift in ('generation','manifest','unknown-source'):
            target = path/'instance.json'
            state = json.loads(target.read_text())
            state[{'generation':'generation','manifest':'source_manifest_sha256','unknown-source':'source_class'}[drift]] = {
                'generation':1,'manifest':'f'*64,'unknown-source':'guessed'}[drift]
            DISK['save'](target, state)
        elif drift == 'wire':
            mutate_byte(path/'persistent-geometry.bin', 31)
        elif drift == 'geometry':
            target = path/'geometry.json'
            value = json.loads(target.read_text())
            value['area_mapping'] += ' changed'
            DISK['save'](target, value)
            state_path = path/'instance.json'
            state = json.loads(state_path.read_text())
            state['geometry_sha256'] = hashlib.sha256(target.read_bytes()).hexdigest()
            DISK['save'](state_path, state)
        elif drift == 'metadata-new-inode':
            target = path/'instance.json'
            DISK['save'](target, json.loads(target.read_text()))
        else:
            (path/'instance.json').chmod(0o644)
        with pytest.raises(API['DiskStateError']):
            verify(tx, binding)
        assert json.loads((output/'disk-binding.json').read_text()) == binding
        failures(output)


def test_closing_and_reopening_same_inode_is_not_same_open_file_description(instance):
    path, output = instance
    with API['transaction'](path, output) as tx:
        binding = capture(tx, output)
        fd = tx.fd
        os.close(fd)
        replacement = os.open(path/'camera.emmc', os.O_RDWR)
        assert replacement == fd
        with pytest.raises(API['DiskStateError'], match='open file description'):
            verify(tx, binding)
        failures(output)


def test_secure_reread_does_not_use_lease_initial_state_dictionary(instance):
    path, output = instance
    with API['transaction'](path, output) as tx:
        state_path = path/'instance.json'
        state = json.loads(state_path.read_text())
        state['generation'] = 9
        DISK['save'](state_path, state)
        assert tx._leased['state']['generation'] == 0
        binding = capture(tx, output)
        assert binding['disk_generation'] == 9
        verify(tx, binding)


@pytest.mark.parametrize('status', ['running','inmigrate','postmigrate','shutdown'])
def test_capture_requires_actual_qmp_paused(instance, status):
    path, output = instance
    with API['transaction'](path, output) as tx:
        with pytest.raises(API['DiskStateError'], match='query-status must report paused'):
            capture(tx, output, StatusQMP(status))
        assert not (output/'disk-binding.json').exists()
        failures(output)


@pytest.mark.parametrize('bad', ['missing-whole','missing-generation','bool-generation','unknown-field','bad-nested-mode','bad-range-type'])
def test_complete_json_schema_rejects_omitted_or_wrongly_typed_fields(instance, bad):
    path, output = instance
    with API['transaction'](path, output) as tx:
        binding = capture(tx, output)
        changed = copy.deepcopy(binding)
        if bad == 'missing-whole':
            del changed['whole_disk_sha256']
        elif bad == 'missing-generation':
            del changed['disk_generation']
        elif bad == 'bool-generation':
            changed['disk_generation'] = False
        elif bad == 'unknown-field':
            changed['external_state'] = 'none'
        elif bad == 'bad-nested-mode':
            changed['disk']['mode'] = '0600'
        else:
            changed['partition_bindings'][2]['bytes'] = True
        with pytest.raises(API['DiskStateError']):
            verify(tx, changed)
        failures(output)


def test_failed_fdatasync_does_not_publish_disk_binding(instance, monkeypatch):
    path, output = instance
    with API['transaction'](path, output) as tx:
        evidence = guest_evidence(tx, output)
        def fail_sync(fd):
            assert fd == tx.fd
            raise OSError('injected fdatasync EIO')
        monkeypatch.setattr(os, 'fdatasync', fail_sync)
        with pytest.raises(API['DiskStateError'], match='fdatasync EIO'):
            tx.snapshot_disk(StatusQMP(), host_run='source-run', migration_generation=10, guest_sync_evidence=evidence)
        assert not (output/'disk-binding.json').exists()
        failures(output)


@pytest.mark.parametrize('target', ['disk','geometry','metadata','wire'])
def test_mutation_during_complete_hash_is_rejected(instance, monkeypatch, target):
    path, output = instance
    original = DISK['hashed']
    with API['transaction'](path, output) as tx:
        changed = False
        def hash_with_real_mutation(fd, offset=0, count=None):
            nonlocal changed
            result = original(fd, offset, count)
            if fd == tx.fd and offset == 0 and count is None and not changed:
                changed = True
                victim = path/{'disk':'camera.emmc','geometry':'geometry.json','metadata':'instance.json','wire':'persistent-geometry.bin'}[target]
                # Preserve bytes and mtime; ctime must still expose the write during this read window.
                data = victim.read_bytes() if target != 'disk' else os.pread(fd, 1, 2048)
                info = victim.stat()
                writable = os.open(victim, os.O_RDWR)
                try:
                    assert os.pwrite(writable, data, 2048 if target == 'disk' else 0) == len(data)
                    os.fsync(writable)
                finally:
                    os.close(writable)
                os.utime(victim, ns=(info.st_atime_ns, info.st_mtime_ns))
            return result
        monkeypatch.setitem(DISK, 'hashed', hash_with_real_mutation)
        with pytest.raises(API['DiskStateError'], match='changed during'):
            capture(tx, output)
        assert changed and not (output/'disk-binding.json').exists()
        failures(output)


def test_real_fresh_guest_marker_required_before_host_sync(instance):
    path, output = instance
    with API['transaction'](path, output) as tx:
        evidence = guest_evidence(tx, output, nonce='0'*32)
        with pytest.raises(API['DiskStateError'], match='fresh guest-sync nonce'):
            tx.snapshot_disk(StatusQMP(), host_run='source-run', migration_generation=10, guest_sync_evidence=evidence)
        failures(output)


@pytest.mark.parametrize('failure', ['phase-order','wrong-target-state','same-host-run','wrong-migration-generation'])
def test_restore_phase_and_run_generation_guards(instance, failure):
    path, output = instance
    with API['transaction'](path, output) as tx:
        binding = capture(tx, output)
        if failure != 'phase-order':
            verify(tx, binding)
            verify(tx, binding, 'post-migration')
        with pytest.raises(API['DiskStateError']):
            if failure == 'wrong-target-state':
                verify(tx, binding, 'pre-restore', qmp=StatusQMP('paused'))
            elif failure == 'same-host-run':
                verify(tx, binding, 'pre-restore', host_run='source-run')
            elif failure == 'wrong-migration-generation':
                verify(tx, binding, 'pre-restore', migration_generation=1)
            else:
                verify(tx, binding, 'post-restore')
        failures(output)


def test_changed_target_after_restore_is_rejected(instance):
    path, output = instance
    with API['transaction'](path, output) as tx:
        binding = capture(tx, output)
        for phase in API['PHASES'][:3]:
            verify(tx, binding, phase)
        mutate_byte(path/'camera.emmc', binding['disk']['size']-1)
        with pytest.raises(API['DiskStateError']):
            verify(tx, binding, 'post-restore')
        assert not (output/'disk-post-restore.json').exists()
        failures(output)


def test_existing_snapshot_and_binding_are_never_overwritten(instance):
    path, output = instance
    old = output/'snapshot.bin'
    old.write_bytes(b'preserve RAM evidence')
    old.chmod(0o600)
    (output/'disk-binding.json').write_bytes(b'older disk receipt')
    (output/'disk-binding.json').chmod(0o600)
    with API['transaction'](path, output) as tx:
        with pytest.raises(API['DiskStateError'], match='File exists'):
            capture(tx, output)
        assert old.read_bytes() == b'preserve RAM evidence'
        assert (output/'disk-binding.json').read_bytes() == b'older disk receipt'
        failures(output)


def test_lease_remains_through_registered_process_normal_exit_on_failure(instance):
    path, output = instance
    program = '''import fcntl,os,sys
fd=int(sys.argv[1]);lock=os.open(sys.argv[2],os.O_RDWR)
assert os.pread(fd,8,0)==b'82462.00'
try:
    fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
except BlockingIOError:
    os.write(int(sys.argv[3]),b'lease-held')
else:
    raise AssertionError('lease released before registered child exit')
'''
    read_end, write_end = os.pipe()
    try:
        with pytest.raises(API['DiskStateError'], match='caller RAM transfer failed'):
            with API['transaction'](path, output) as tx:
                child = subprocess.Popen([sys.executable,'-I','-c',program,str(tx.fd),str(path/'.disk.lock'),str(write_end)],
                                         pass_fds=tx.pass_fds+(write_end,))
                tx.children.append(child)
                raise RuntimeError('caller RAM transfer failed')
        assert child.poll() == 0
        assert os.read(read_end, 10) == b'lease-held'
        with DISK['lease'](path):
            pass
        failures(output)
    finally:
        os.close(read_end)
        os.close(write_end)


def test_unreachable_qmp_records_retained_owner_without_releasing_lease(instance):
    path, output = instance
    read_end, write_end = os.pipe()
    process = subprocess.Popen([sys.executable, '-I', '-c',
        'import os,sys; os.read(int(sys.argv[1]),1)', str(read_end)], pass_fds=(read_end,))
    os.close(read_end)
    class RecoveringOwner:
        pid, args = process.pid, process.args
        attempts = 0
        def poll(self):
            return process.poll()
        def wait(self, timeout=None):
            self.attempts += 1
            if self.attempts == 1:
                raise subprocess.TimeoutExpired(self.args, timeout)
            try:
                records = list(output.glob('owner-retained-*.json'))
                assert len(records) == 1
                state = json.loads(records[0].read_text())
                assert state['owner_pid'] == self.pid and state['lease_held'] is True
                assert state['vm_signals_sent'] == [] and records[0].stat().st_mode & 0o777 == 0o600
                with pytest.raises(BlockingIOError):
                    with DISK['lease'](path):
                        pass
            finally:
                os.write(write_end, b'normal-exit')
            return process.wait(timeout=timeout)
    try:
        with pytest.raises(API['DiskStateError'], match='QMP unreachable'):
            with API['transaction'](path, output) as tx:
                tx.children.append(RecoveringOwner())
                raise RuntimeError('QMP unreachable after registering owner')
        assert process.poll() == 0
        with DISK['lease'](path):
            pass
    finally:
        os.close(write_end)


@pytest.mark.parametrize('name', ['geometry.json','instance.json','persistent-geometry.bin','guest-sync.console'])
def test_file_mutation_during_pread_is_rejected(instance, monkeypatch, name):
    path, output = instance
    with API['transaction'](path, output) as tx:
        evidence = guest_evidence(tx, output)
        victim = evidence if name == 'guest-sync.console' else path/name
        inode = victim.stat().st_ino
        pread = os.pread
        changed = False
        def changing_pread(fd, count, offset):
            nonlocal changed
            data = pread(fd, count, offset)
            if not changed and os.fstat(fd).st_ino == inode:
                changed = True
                writable = os.open(victim, os.O_RDWR)
                try:
                    assert os.pwrite(writable, data, offset) == len(data)
                    os.fsync(writable)
                finally:
                    os.close(writable)
            return data
        monkeypatch.setattr(os, 'pread', changing_pread)
        with pytest.raises(API['DiskStateError'], match='file read stamp'):
            tx.snapshot_disk(StatusQMP(), host_run='source-run', migration_generation=10, guest_sync_evidence=evidence)
        assert changed
        failures(output)


@pytest.mark.parametrize('victim_name', ['geometry.json','guest-sync.console'])
def test_late_hash_mutation_cannot_escape_earlier_file_checks(instance, monkeypatch, victim_name):
    path, output = instance
    original = DISK['hashed']
    with API['transaction'](path, output) as tx:
        evidence = guest_evidence(tx, output)
        wire_inode = (path/'persistent-geometry.bin').stat().st_ino
        changed = False
        def hash_with_late_mutation(fd, offset=0, count=None):
            nonlocal changed
            result = original(fd, offset, count)
            if not changed and os.fstat(fd).st_ino == wire_inode:
                changed = True
                victim = evidence if victim_name == 'guest-sync.console' else path/victim_name
                data = victim.read_bytes()
                writable = os.open(victim, os.O_RDWR)
                try:
                    assert os.pwrite(writable, data, 0) == len(data)
                    os.fsync(writable)
                finally:
                    os.close(writable)
            return result
        monkeypatch.setitem(DISK, 'hashed', hash_with_late_mutation)
        with pytest.raises(API['DiskStateError'], match='changed during'):
            tx.snapshot_disk(StatusQMP(), host_run='source-run', migration_generation=10, guest_sync_evidence=evidence)
        assert changed and not (output/'disk-binding.json').exists()
        failures(output)


def test_binding_cannot_move_to_a_new_lease_or_transaction(instance):
    path, output = instance
    with API['transaction'](path, output) as tx:
        binding = capture(tx, output)
    other = output/'new-run'
    other.mkdir(mode=0o700)
    with API['transaction'](path, other) as tx:
        with pytest.raises(API['DiskStateError'], match='same transaction'):
            verify(tx, binding)
        failures(other)


def test_output_path_swap_fails_but_retains_failure_in_original_private_directory(instance):
    path, output = instance
    saved = output.with_name('preserved-private-output')
    with API['transaction'](path, output) as tx:
        evidence = guest_evidence(tx, output)
        output.rename(saved)
        output.mkdir(mode=0o700)
        evidence = saved/evidence.name
        with pytest.raises(API['DiskStateError'], match='current path'):
            tx.snapshot_disk(StatusQMP(), host_run='source-run', migration_generation=10, guest_sync_evidence=evidence)
        failures(saved)
        assert not list(output.iterdir())


def test_qmp_resume_during_hash_is_rejected(instance, monkeypatch):
    path, output = instance
    original = DISK['hashed']
    qmp = StatusQMP()
    with API['transaction'](path, output) as tx:
        def resume_while_hashing(fd, offset=0, count=None):
            result = original(fd, offset, count)
            if fd == tx.fd and count is None:
                qmp.status = 'running'
            return result
        monkeypatch.setitem(DISK, 'hashed', resume_while_hashing)
        with pytest.raises(API['DiskStateError'], match='query-status must report paused'):
            capture(tx, output, qmp)
        assert len(qmp.calls) == 2
        failures(output)
