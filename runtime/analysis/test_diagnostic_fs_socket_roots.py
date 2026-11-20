"""Prepared identity/gate checks; these never create a socket or launch a VM."""
import os
import stat
from types import SimpleNamespace

import pytest
import diagnostic_fs_socket_roots as fs


def forbidden(*args, **kwargs):
    pytest.fail('runtime operation before fixed gate')


def test_runtime_gate_is_unconditional_even_with_empty_status(monkeypatch):
    monkeypatch.setattr(fs, 'FS_RUNTIME_BLOCKERS', ())
    monkeypatch.setenv('A7C2_SINGLE_AP_RUNTIME_READY', '1')
    monkeypatch.setenv('A7C2_SINGLE_AP_OWNER_VERIFIED', '1')
    with pytest.raises(RuntimeError, match='BLOCKED'):
        fs.require_runtime_ready()


def test_runtime_blockers_record_single_ap_requirements():
    reasons = '; '.join(fs.FS_RUNTIME_BLOCKERS)
    assert 'continuous lease' in reasons
    assert 'parent-death' in reasons
    assert 'real QEMU' in reasons
    assert 'detach' in reasons
    assert 'CP' not in reasons


def test_roots_gate_precedes_any_filesystem_or_process_access(monkeypatch):
    monkeypatch.setattr(fs, 'open_directory', forbidden)
    monkeypatch.setattr(fs, 'process_identity', forbidden)
    with pytest.raises(RuntimeError, match='BLOCKED'):
        fs.DiagnosticRoots('/unused', '/run/user/1000/unused', fs.DIAGNOSTIC_FS_PROFILE)


def test_listener_constructor_is_closed_before_root_access():
    with pytest.raises(RuntimeError, match='BLOCKED'):
        fs.DiagnosticListener(None, 'unused.sock')


@pytest.mark.parametrize('method', ['bind', 'close_untransferred'])
def test_uninitialized_listener_cannot_allocate_or_close(monkeypatch, method):
    monkeypatch.setattr(fs.socket, 'socket', forbidden)
    listener = object.__new__(fs.DiagnosticListener)
    with pytest.raises(RuntimeError, match='BLOCKED'):
        getattr(listener, method)()


def test_uninitialized_roots_cannot_connect_or_discover():
    roots = object.__new__(fs.DiagnosticRoots)
    for call in (roots.revalidate, roots.binding,
                 lambda: roots.child('unused.sock'),
                 lambda: roots.endpoint('unused.sock')):
        with pytest.raises(RuntimeError, match='BLOCKED'):
            call()
    with pytest.raises(RuntimeError, match='BLOCKED'):
        with roots.connect_path('unused.sock'):
            pytest.fail('connection path was exposed')


def test_identity_records_inode_owner_permissions_and_kind():
    info = SimpleNamespace(st_dev=11, st_ino=22, st_uid=33, st_mode=stat.S_IFDIR | 0o700)
    assert fs.identity(info) == dict(dev=11, ino=22, uid=33, mode=0o700, kind=stat.S_IFDIR)


def test_process_identity_has_generation():
    current = fs.process_identity(os.getpid())
    assert current['pid'] == os.getpid()
    assert current['start_ticks'] > 0
    assert len(current['boot_id']) == 36
    assert current == fs.process_identity(os.getpid())


@pytest.mark.parametrize('pid', [0, -1, True, None, '1'])
def test_process_identity_rejects_invalid_pid(pid):
    with pytest.raises(ValueError, match='positive PID'):
        fs.process_identity(pid)


def test_open_directory_pins_existing_directory(tmp_path):
    fd = fs.open_directory(tmp_path)
    try:
        assert fs.identity(os.fstat(fd)) == fs.identity(tmp_path.lstat())
    finally:
        os.close(fd)


def test_open_directory_rejects_symlink(tmp_path):
    target = tmp_path / 'target'
    target.mkdir()
    alias = tmp_path / 'alias'
    alias.symlink_to(target, target_is_directory=True)
    with pytest.raises(ValueError, match='canonical'):
        fs.open_directory(alias)


def test_open_directory_rejects_dotdot_and_relative(tmp_path):
    with pytest.raises(ValueError, match='canonical'):
        fs.open_directory(tmp_path / '..' / tmp_path.name)
    with pytest.raises(ValueError, match='absolute'):
        fs.open_directory('relative-directory')
