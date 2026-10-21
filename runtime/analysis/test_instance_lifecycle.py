"""Host lifetime lease/store tests; synthetic state, no guest persistence claim."""
import hashlib
import os
from pathlib import Path
import subprocess
import sys

import pytest

import instance_lifecycle as lifecycle
import setting_store as store

FIRMWARE = 'a' * 64
DATA = b'B' * store.BACKUP_SIZE
DIGEST = hashlib.sha256(DATA).hexdigest()


@pytest.fixture
def instance(tmp_path):
    path = tmp_path / 'stable'
    path.mkdir(mode=0o700)
    return lifecycle.Instance(path)


def save(instance, expected=None):
    with instance.run_lease() as lease:
        return lease.commit(DATA, FIRMWARE, expected, guest_sha256=DIGEST)


def child_attempt(instance):
    script = '''
import sys
import instance_lifecycle as lifecycle
instance = lifecycle.Instance(sys.argv[1])
try:
    with instance.run_lease():
        print('acquired')
except lifecycle.Busy:
    print('busy')
'''
    env = {**os.environ, 'PYTHONPATH': str(Path(lifecycle.__file__).resolve().parent)}
    result = subprocess.run([sys.executable, '-B', '-c', script, instance.path],
                            check=True, capture_output=True, text=True, timeout=10, env=env)
    return result.stdout.strip()


def test_same_process_and_cross_process_exclusion(instance):
    other = lifecycle.Instance(instance.path)
    with instance.run_lease() as lease:
        assert lease.check() is lease and lease.pid == os.getpid()
        with pytest.raises(lifecycle.Busy):
            with other.run_lease():
                pytest.fail('parallel same-process run')
        with pytest.raises(lifecycle.Busy):
            with other.offline_lease(other.path):
                pytest.fail('parallel offline lease')
        assert child_attempt(instance) == 'busy'
    assert child_attempt(instance) == 'acquired'


def test_exception_closes_fd_and_releases(instance):
    with pytest.raises(RuntimeError, match='controller failure'):
        with instance.run_lease() as lease:
            fd = lease._fd
            raise RuntimeError('controller failure')
    with pytest.raises(OSError):
        os.fstat(fd)
    assert child_attempt(instance) == 'acquired'
    with pytest.raises(lifecycle.LeaseError):
        lease.load(FIRMWARE)


def test_reentrant_repeated_and_boolean_tokens_fail_closed(instance):
    token = instance.run_lease()
    with token:
        with pytest.raises(TypeError, match='boolean'):
            bool(token)
        with pytest.raises(lifecycle.LeaseError, match='single-use'):
            with token:
                pytest.fail('reentered')
        assert child_attempt(instance) == 'busy'
        assert token.check() is token
    with pytest.raises(lifecycle.LeaseError, match='single-use'):
        token.__enter__()
    with pytest.raises(lifecycle.LeaseError, match='inactive'):
        token.__exit__(None, None, None)
    with pytest.raises(lifecycle.LeaseError):
        token.commit(DATA, FIRMWARE, None, guest_sha256=DIGEST)


def test_fork_child_cannot_release_parent(instance):
    read_fd, write_fd = os.pipe()
    with instance.run_lease() as token:
        pid = os.fork()
        if pid == 0:
            os.close(read_fd)
            try:
                for operation in (token.check, lambda: token.__exit__(None, None, None)):
                    try:
                        operation()
                    except lifecycle.LeaseError:
                        continue
                    raise AssertionError('child accepted parent capability')
                os.write(write_fd, b'ok')
                os._exit(0)
            except BaseException:
                os._exit(1)
        os.close(write_fd)
        try:
            assert os.read(read_fd, 2) == b'ok'
            assert os.waitpid(pid, 0)[1] == 0
        finally:
            os.close(read_fd)
        assert token.check() is token
        assert child_attempt(instance) == 'busy'
    assert child_attempt(instance) == 'acquired'


def test_live_reset_refused_and_stopped_reset_preserves_history_sd(instance, tmp_path, monkeypatch):
    first = save(instance)
    root = Path(instance.path)
    (root / 'SD').mkdir(mode=0o700)
    (root / 'SD' / 'card.img').write_bytes(b'arbitrary virtual SD')
    external = tmp_path / 'arbitrary-SD.img'
    external.write_bytes(b'external virtual SD')
    old = {p: p.read_bytes() for p in root.rglob('*') if p.is_file()}
    with instance.run_lease():
        with pytest.raises(lifecycle.Busy):
            instance.reset(first['generation'], confirmed=True)
    assert (root / 'current.json').read_bytes() == old[root / 'current.json']
    real_publish = store._publish

    def publish(*args):
        assert child_attempt(instance) == 'busy'
        return real_publish(*args)

    with monkeypatch.context() as patch:
        patch.setattr(store, '_publish', publish)
        result = instance.reset(first['generation'], confirmed=True)
    assert result['state'] == 'reset' and result['data'] is None
    assert result['generation'] != first['generation']
    with instance.run_lease() as token:
        assert token.load(FIRMWARE) == result
    for path, data in old.items():
        if path.name != 'current.json':
            assert path.read_bytes() == data
    assert external.read_bytes() == b'external virtual SD'


def test_confirmation_cas_and_factory_errors(instance):
    first = save(instance)
    for confirmed in (False, None, 1, 'yes'):
        with pytest.raises(store.StoreError, match='confirmation'):
            instance.reset(first['generation'], confirmed=confirmed)
    with pytest.raises(store.Conflict):
        instance.reset('0' * 32, confirmed=True)
    with pytest.raises(lifecycle.LeaseError, match='path mismatch'):
        instance.offline_lease(instance.path + '-other')
    with pytest.raises(store.StoreError, match='lease'):
        store.reset(instance.path, first['generation'], True, offline_lease=True)
    with pytest.raises(TypeError):
        store.reset(instance.path, first['generation'], True, offline_lease=lambda _: True)
    with instance.run_lease() as token:
        assert token.load(FIRMWARE)['generation'] == first['generation']


@pytest.mark.parametrize('replacement', ['missing', 'directory', 'symlink'])
def test_directory_swap_rejected_before_store_call(instance, monkeypatch, replacement):
    save(instance)
    root = Path(instance.path)
    with instance.run_lease() as token:
        root.rename(root.with_name('moved'))
        if replacement == 'directory':
            root.mkdir(mode=0o700)
        elif replacement == 'symlink':
            root.symlink_to(root.with_name('moved'), target_is_directory=True)

        def forbidden(*args, **kwargs):
            pytest.fail('store operation after directory swap')

        with monkeypatch.context() as patch:
            patch.setattr(store, 'load', forbidden)
            patch.setattr(store, 'commit', forbidden)
            for operation in (token.check, lambda: token.load(FIRMWARE),
                              lambda: token.commit(DATA, FIRMWARE, None,
                                                   guest_sha256=DIGEST)):
                with pytest.raises((OSError, store.StoreError)):
                    operation()
        with pytest.raises((OSError, store.StoreError)):
            instance.reset(None, confirmed=True)
    if replacement != 'symlink':
        assert not root.exists() or list(root.iterdir()) == []


def test_lock_swap_refused(instance):
    root = Path(instance.path)
    with instance.run_lease() as token:
        (root / lifecycle.LOCK).rename(root / 'old-lock')
        (root / lifecycle.LOCK).touch(mode=0o600)
        with pytest.raises(lifecycle.LeaseError, match='lock identity'):
            token.check()


@pytest.mark.parametrize('unsafe', ['permissions', 'symlink', 'hardlink'])
def test_lifecycle_lock_validation(instance, unsafe):
    root = Path(instance.path)
    with instance.run_lease():
        pass
    lock = root / lifecycle.LOCK
    if unsafe == 'permissions':
        lock.chmod(0o644)
    elif unsafe == 'symlink':
        lock.rename(root / 'old-lock')
        lock.symlink_to(root / 'old-lock')
    else:
        os.link(lock, root / 'lock-hardlink')
    with pytest.raises((OSError, store.StoreError)):
        with instance.run_lease():
            pytest.fail('unsafe lock accepted')


@pytest.mark.parametrize('unsafe', ['permissions', 'symlink', 'ancestor', 'traversal', 'missing'])
def test_reuses_private_directory_validation(tmp_path, unsafe):
    root = tmp_path / 'stable'
    root.mkdir(mode=0o700)
    path = root
    if unsafe == 'permissions':
        root.chmod(0o755)
    elif unsafe == 'symlink':
        path = tmp_path / 'alias'
        path.symlink_to(root, target_is_directory=True)
    elif unsafe == 'ancestor':
        tmp_path.chmod(0o777)
    elif unsafe == 'traversal':
        path = root / '..' / 'stable'
    else:
        path = tmp_path / 'absent'
    with pytest.raises((OSError, store.StoreError)):
        lifecycle.Instance(path)


def test_publication_uncertain_propagates_and_releases(instance, monkeypatch):
    first = save(instance)
    real_fsync = os.fsync
    published = False
    real_replace = os.replace

    def replace(*args, **kwargs):
        nonlocal published
        result = real_replace(*args, **kwargs)
        published = True
        return result

    def fsync(fd):
        if published:
            raise OSError('injected post-publication durability failure')
        return real_fsync(fd)

    with monkeypatch.context() as patch:
        patch.setattr(os, 'replace', replace)
        patch.setattr(os, 'fsync', fsync)
        with pytest.raises(store.PublicationUncertain):
            instance.reset(first['generation'], confirmed=True)
    with instance.run_lease() as token:
        loaded = token.load(FIRMWARE)
        assert loaded['state'] == 'reset'
        assert loaded['generation'] != first['generation']
    with pytest.raises(store.Conflict):
        instance.reset(first['generation'], confirmed=True)
