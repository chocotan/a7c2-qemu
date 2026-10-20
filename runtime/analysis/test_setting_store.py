from contextlib import contextmanager
import fcntl
import hashlib
import json
import multiprocessing
import os
from pathlib import Path
import stat
import subprocess
import sys
from types import SimpleNamespace

import pytest

import setting_store as store

FIRMWARE = 'a' * 64
DATA = b'B' * store.BACKUP_SIZE
DIGEST = hashlib.sha256(DATA).hexdigest()


def save(instance, expected=None, data=DATA):
    return store.commit(instance, data, FIRMWARE, expected,
                        guest_sha256=hashlib.sha256(data).hexdigest())


@contextmanager
def controller_test_lease(instance):
    # Test adapter only: this is not production VM/offline safety evidence.
    assert Path(instance).is_absolute()
    yield


def test_missing_empty_and_cross_process_load(tmp_path):
    instance = tmp_path / 'stable'
    assert store.load(instance, FIRMWARE) is None
    assert not instance.exists()
    instance.mkdir(mode=0o700)
    assert store.load(instance, FIRMWARE) is None
    current = save(instance)
    script = '''
import hashlib, json, sys
import setting_store
state = setting_store.load(sys.argv[1], sys.argv[2])
state['data'] = hashlib.sha256(state['data']).hexdigest()
print(json.dumps(state))
'''
    result = subprocess.run([sys.executable, '-c', script, str(instance), FIRMWARE],
                            cwd=Path(store.__file__).parent, text=True,
                            capture_output=True, check=True, timeout=10)
    loaded = json.loads(result.stdout)
    assert loaded['generation'] == current['generation']
    assert loaded['data'] == DIGEST
    assert stat.S_IMODE(instance.stat().st_mode) == 0o700
    for path in instance.rglob('*'):
        assert stat.S_IMODE(path.stat().st_mode) == (0o700 if path.is_dir() else 0o600)


def test_bytes_fd_and_immutable_generations(tmp_path):
    instance = tmp_path / 'instance'
    first = save(instance)
    old_payload = instance / ('generation-' + first['generation']) / 'backup.bin'
    source = tmp_path / 'explicit-input'
    second_data = b'C' * store.BACKUP_SIZE
    source.write_bytes(second_data)
    with source.open('rb') as stream:
        stream.seek(71)
        second = store.commit(instance, stream.fileno(), FIRMWARE.upper(), first['generation'],
                              guest_sha256=hashlib.sha256(second_data).hexdigest())
        assert stream.tell() == 71
    assert second['generation'] != first['generation']
    assert store.load(instance, FIRMWARE)['data'] == second_data
    assert old_payload.read_bytes() == DATA


@pytest.mark.parametrize('change', ['short', 'long', 'digest', 'firmware', 'path', 'boolean', 'pipe'])
def test_input_contract_rejects_without_writes(tmp_path, change):
    instance = tmp_path / 'instance'
    data, firmware, digest = DATA, FIRMWARE, DIGEST
    read_fd = write_fd = None
    if change == 'short':
        data = DATA[:-1]
    elif change == 'long':
        data = DATA + b'x'
    elif change == 'digest':
        digest = '0' * 64
    elif change == 'firmware':
        firmware = 'not-original-firmware-sha'
    elif change == 'path':
        data = tmp_path / 'Backup'
    elif change == 'boolean':
        data = True
    elif change == 'pipe':
        read_fd, write_fd = os.pipe()
        data = read_fd
    try:
        with pytest.raises(store.StoreError):
            store.commit(instance, data, firmware, None, guest_sha256=digest)
    finally:
        if read_fd is not None:
            os.close(read_fd)
            os.close(write_fd)
    assert not instance.exists()


def test_independent_digest_required(tmp_path):
    with pytest.raises(TypeError):
        store.commit(tmp_path / 'instance', DATA, FIRMWARE, None)


def test_cas_commit_reset_and_firmware_mismatch(tmp_path):
    instance = tmp_path / 'instance'
    first = save(instance)
    second = save(instance, first['generation'])
    with pytest.raises(store.Conflict):
        save(instance, first['generation'])
    with pytest.raises(store.Conflict):
        store.reset(instance, first['generation'], True, offline_lease=controller_test_lease)
    with pytest.raises(store.StoreError, match='firmware mismatch'):
        store.load(instance, 'b' * 64)
    with pytest.raises(store.StoreError, match='firmware mismatch'):
        store.commit(instance, DATA, 'b' * 64, second['generation'], guest_sha256=DIGEST)
    assert store.load(instance, FIRMWARE)['generation'] == second['generation']


@pytest.mark.parametrize('target', ['root', 'ancestor', 'manifest', 'payload', 'lock', 'generation'])
def test_symlinks_refused(tmp_path, target):
    real = tmp_path / 'real'
    current = save(real)
    if target == 'root':
        instance = tmp_path / 'alias'
        instance.symlink_to(real, target_is_directory=True)
    elif target == 'ancestor':
        alias = tmp_path / 'alias'
        alias.symlink_to(tmp_path, target_is_directory=True)
        instance = alias / 'real'
    else:
        instance = real
        generation = real / ('generation-' + current['generation'])
        victim = {'manifest': real / 'current.json', 'payload': generation / 'backup.bin',
                  'lock': real / '.setting-store.lock', 'generation': generation}[target]
        moved = tmp_path / 'external'
        victim.rename(moved)
        victim.symlink_to(moved, target_is_directory=target == 'generation')
    with pytest.raises((OSError, store.StoreError)):
        store.load(instance, FIRMWARE)
    with pytest.raises((OSError, store.StoreError)):
        save(instance, current['generation'])


@pytest.mark.parametrize('target', ['root', 'manifest', 'payload', 'hardlink', 'fifo'])
def test_permissions_and_regular_files(tmp_path, target):
    instance = tmp_path / 'instance'
    first = save(instance)
    payload = instance / ('generation-' + first['generation']) / 'backup.bin'
    if target == 'root':
        instance.chmod(0o755)
    elif target == 'manifest':
        (instance / 'current.json').chmod(0o644)
    elif target == 'payload':
        payload.chmod(0o644)
    elif target == 'hardlink':
        os.link(payload, tmp_path / 'hardlink')
    else:
        payload.rename(tmp_path / 'old-payload')
        os.mkfifo(payload, 0o600)
    with pytest.raises(store.StoreError):
        store.load(instance, FIRMWARE)


@pytest.mark.parametrize('damage', ['bitflip', 'missing-payload', 'missing-manifest',
                                     'bad-manifest', 'bad-record', 'duplicate-manifest'])
def test_corruption_never_falls_back(tmp_path, damage):
    instance = tmp_path / 'instance'
    first = save(instance)
    generation = instance / ('generation-' + first['generation'])
    if damage == 'bitflip':
        with (generation / 'backup.bin').open('r+b') as stream:
            stream.seek(91)
            stream.write(b'X')
    elif damage == 'missing-payload':
        (generation / 'backup.bin').rename(tmp_path / 'removed-payload')
    elif damage == 'missing-manifest':
        (instance / 'current.json').rename(tmp_path / 'removed-manifest')
    elif damage == 'bad-manifest':
        (instance / 'current.json').write_bytes(b'garbage')
    elif damage == 'duplicate-manifest':
        (instance / 'current.json').write_text('{"generation":"x","generation":"y"}')
    else:
        (generation / 'record.json').write_text('{}')
    with pytest.raises((store.StoreError, OSError)):
        store.load(instance, FIRMWARE)
    with pytest.raises((store.StoreError, OSError)):
        save(instance, first['generation'])


def test_reset_requires_confirmation_and_controller_capability(tmp_path):
    instance = tmp_path / 'instance'
    first = save(instance)
    manifest = (instance / 'current.json').read_bytes()
    for confirmation in (False, None, 1, 'yes'):
        with pytest.raises(store.StoreError, match='confirmation'):
            store.reset(instance, first['generation'], confirmation,
                        offline_lease=controller_test_lease)
    for capability in (None, True, False, 'offline'):
        with pytest.raises(store.StoreError, match='lease'):
            store.reset(instance, first['generation'], True, offline_lease=capability)
    with pytest.raises(TypeError):
        store.reset(instance, first['generation'], True)
    with pytest.raises(TypeError):
        store.reset(instance, first['generation'], True, offline_lease=lambda _: True)
    assert (instance / 'current.json').read_bytes() == manifest


def test_controller_refuses_reset_before_store_mutation(tmp_path):
    instance = tmp_path / 'instance'
    first = save(instance)
    previous = set(instance.rglob('*'))

    @contextmanager
    def refused(instance_path):
        raise RuntimeError('controller cannot establish exclusive offline state')
        yield

    with pytest.raises(RuntimeError, match='offline'):
        store.reset(instance, first['generation'], True, offline_lease=refused)
    assert set(instance.rglob('*')) == previous
    assert store.load(instance, FIRMWARE)['generation'] == first['generation']


def test_reset_new_instance_does_not_create_state(tmp_path):
    instance = tmp_path / 'instance'
    with pytest.raises(store.StoreError, match='confirmation'):
        store.reset(instance, None, False, offline_lease=controller_test_lease)
    assert not instance.exists()
    with pytest.raises(FileNotFoundError):
        store.reset(instance, None, True, offline_lease=controller_test_lease)
    assert not instance.exists()


def test_reset_tombstone_lease_scope_and_no_sd_delete(tmp_path, monkeypatch):
    instance = tmp_path / 'instance'
    first = save(instance)
    sd = instance / 'SD'
    sd.mkdir(mode=0o700)
    card = sd / 'card.img'
    card.write_bytes(b'virtual SD untouched')
    external = tmp_path / 'external'
    external.write_bytes(b'external untouched')
    old = {p: p.read_bytes() for p in instance.rglob('*') if p.is_file()}
    held = []

    @contextmanager
    def lease(path):
        assert path == str(instance)
        held.append(True)
        try:
            yield
        finally:
            held.pop()

    real_publish = store._publish

    def guarded_publish(*args):
        assert held == [True]
        return real_publish(*args)

    def no_delete(*args, **kwargs):
        pytest.fail('store must not delete anything')

    monkeypatch.setattr(store, '_publish', guarded_publish)
    monkeypatch.setattr(os, 'unlink', no_delete)
    monkeypatch.setattr(os, 'remove', no_delete)
    monkeypatch.setattr(os, 'rmdir', no_delete)
    reset = store.reset(instance, first['generation'], True, offline_lease=lease)
    assert not held
    assert reset['state'] == 'reset' and reset['data'] is None
    assert reset['generation'] != first['generation']
    assert store.load(instance, FIRMWARE) == reset
    for path, data in old.items():
        if path.name != 'current.json':
            assert path.read_bytes() == data
    assert external.read_bytes() == b'external untouched'
    assert card.read_bytes() == b'virtual SD untouched'
    monkeypatch.setattr(store, '_publish', real_publish)
    restored = save(instance, reset['generation'])
    assert restored['state'] == 'backup'


@pytest.mark.parametrize('space', ['unknown', 'negative', 'zero-block', 'full'])
def test_space_fail_closed(tmp_path, monkeypatch, space):
    instance = tmp_path / 'instance'
    first = save(instance)
    if space == 'unknown':
        def fail(fd):
            raise OSError('space query failed')
        monkeypatch.setattr(os, 'fstatvfs', fail)
    else:
        info = SimpleNamespace(f_bavail=-1 if space == 'negative' else 0,
                               f_frsize=0 if space == 'zero-block' else 4096)
        monkeypatch.setattr(os, 'fstatvfs', lambda fd: info)
    with pytest.raises(store.StoreError):
        save(instance, first['generation'])
    assert store.load(instance, FIRMWARE)['generation'] == first['generation']


@pytest.mark.parametrize('failure', ['payload-fsync', 'generation-fsync', 'parent-fsync',
                                    'manifest-fsync', 'prepublish-dir-fsync', 'publish'])
def test_prepublication_failure_keeps_old_current(tmp_path, monkeypatch, failure):
    instance = tmp_path / 'instance'
    first = save(instance)
    old = (instance / 'current.json').read_bytes()
    original_fsync = os.fsync
    calls = []

    def fsync(fd):
        calls.append(os.readlink('/proc/self/fd/' + str(fd)))
        count = {'payload-fsync': 1, 'generation-fsync': 3, 'parent-fsync': 4,
                 'manifest-fsync': 5, 'prepublish-dir-fsync': 6}.get(failure)
        if len(calls) == count:
            raise OSError('injected fsync failure')
        return original_fsync(fd)

    monkeypatch.setattr(os, 'fsync', fsync)
    if failure == 'publish':
        def fail_publish(*args, **kwargs):
            raise OSError('injected rename failure')
        monkeypatch.setattr(os, 'replace', fail_publish)
    with pytest.raises(OSError):
        save(instance, first['generation'])
    assert (instance / 'current.json').read_bytes() == old
    assert store.load(instance, FIRMWARE)['generation'] == first['generation']
    assert len(list(instance.glob('generation-*'))) == 2


def test_final_fsync_failure_is_explicitly_uncertain(tmp_path, monkeypatch):
    instance = tmp_path / 'instance'
    first = save(instance)
    real_fsync = os.fsync
    count = 0

    def fsync(fd):
        nonlocal count
        count += 1
        if count == 7:
            raise OSError('injected post-rename fsync failure')
        real_fsync(fd)

    monkeypatch.setattr(os, 'fsync', fsync)
    with pytest.raises(store.PublicationUncertain):
        save(instance, first['generation'])
    assert store.load(instance, FIRMWARE)['generation'] != first['generation']


def test_interrupted_first_publish_is_not_unseeded(tmp_path, monkeypatch):
    instance = tmp_path / 'instance'

    def fail_publish(*args, **kwargs):
        raise OSError('injected first publish failure')

    monkeypatch.setattr(os, 'replace', fail_publish)
    with pytest.raises(OSError, match='first publish'):
        save(instance)
    assert list(instance.glob('generation-*'))
    with pytest.raises(store.StoreError, match='missing manifest'):
        store.load(instance, FIRMWARE)
    with pytest.raises(store.StoreError, match='missing manifest'):
        save(instance)


def _child_commit(instance, expected, connection):
    connection.send('started')
    try:
        result = save(instance, expected)
        connection.send(('ok', result['generation']))
    except store.Conflict:
        connection.send(('conflict', None))
    finally:
        connection.close()


def test_cross_process_flock_and_cas(tmp_path):
    instance = tmp_path / 'instance'
    first = save(instance)
    ctx = multiprocessing.get_context('spawn')
    lock = os.open(instance / '.setting-store.lock', os.O_RDWR)
    children = []
    try:
        fcntl.flock(lock, fcntl.LOCK_EX)
        for _ in range(2):
            receiver, sender = ctx.Pipe(duplex=False)
            child = ctx.Process(target=_child_commit,
                                args=(str(instance), first['generation'], sender))
            child.start()
            sender.close()
            children.append((child, receiver))
        for child, receiver in children:
            assert receiver.poll(10)
            assert receiver.recv() == 'started'
            assert not receiver.poll(0.2), 'writer bypassed flock'
        fcntl.flock(lock, fcntl.LOCK_UN)
        results = []
        for child, receiver in children:
            assert receiver.poll(10)
            results.append(receiver.recv())
            child.join(10)
            assert child.exitcode == 0
        assert sorted(result[0] for result in results) == ['conflict', 'ok']
        assert store.load(instance, FIRMWARE)['generation'] == next(
            token for status, token in results if status == 'ok')
    finally:
        os.close(lock)
        for child, receiver in children:
            if child.is_alive():
                child.terminate()
                child.join(10)
            receiver.close()


@pytest.mark.parametrize('damaged', ['record', 'pointer'])
def test_metadata_and_pointer_readback_precede_publication(tmp_path, monkeypatch, damaged):
    instance = tmp_path/'instance'
    first = save(instance)
    old_pointer = (instance/'current.json').read_bytes()
    original_write = store._write

    def corrupt(parent, name, data):
        if (damaged == 'record' and name == 'record.json' or
                damaged == 'pointer' and name.startswith('.current-')):
            data = b'{}'
        return original_write(parent, name, data)

    with monkeypatch.context() as patch:
        patch.setattr(store, '_write', corrupt)
        with pytest.raises(store.StoreError, match='readback mismatch'):
            save(instance, first['generation'])
    assert (instance/'current.json').read_bytes() == old_pointer
    assert store.load(instance, FIRMWARE)['data'] == DATA


def test_suppressing_lease_cannot_make_reset_failure_look_successful(tmp_path, monkeypatch):
    instance = tmp_path/'instance'
    first = save(instance)
    old_pointer = (instance/'current.json').read_bytes()

    class Suppress:
        def __enter__(self):
            return self

        def __exit__(self, *error):
            return True

    def fail(*args):
        raise OSError('injected reset publication failure')

    with monkeypatch.context() as patch:
        patch.setattr(store, '_publish', fail)
        with pytest.raises(store.StoreError, match='suppressed reset failure'):
            store.reset(instance, first['generation'], True, offline_lease=lambda _: Suppress())
    assert (instance/'current.json').read_bytes() == old_pointer
    assert store.load(instance, FIRMWARE)['generation'] == first['generation']
