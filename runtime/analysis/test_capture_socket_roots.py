"""Host-only checks for the capture-specific short socket binding."""
from contextlib import ExitStack
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys

import pytest

import capture_socket_roots as capture
from diagnostic_fs_socket_roots import require_runtime_ready


@pytest.fixture
def run(tmp_path, monkeypatch):
    root = tmp_path / 'menu-runs'
    run = root / 'c35a'
    run.mkdir(parents=True, mode=0o700)
    monkeypatch.setattr(capture, 'RUNS', root)
    return run


@pytest.fixture
def endpoint_root(run):
    root = capture.CaptureSocketRoots.create(run)
    yield root
    with root.directory() as fd:
        for name in os.listdir(fd):
            if name not in {*capture.NAMES, 'extra'}:
                raise ValueError('Unexpected fixture file; retain the directory')
            os.unlink(name, dir_fd=fd)
    root.sockets.rmdir()


def test_capture_root_binds_run_parent_owner_and_128bit_name(endpoint_root):
    root = endpoint_root
    binding = root.binding()
    assert root.sockets.parent == Path('/run/user') / str(os.geteuid())
    assert len(root.sockets.name) == 34 and root.sockets.name.startswith('c-')
    assert binding['owner']['pid'] == os.getpid()
    assert capture.CaptureSocketRoots.open(root.files, binding).binding() == binding
    assert not any(root.files.glob('*.sock'))
    with pytest.raises(FileExistsError, match='already exists'):
        capture.CaptureSocketRoots.create(root.files)
    with pytest.raises(RuntimeError, match='BLOCKED:'):
        require_runtime_ready()


def test_capture_root_preflights_restrictive_umask_before_mkdir(run, monkeypatch):
    monkeypatch.setattr(capture.secrets, 'token_hex', lambda size: pytest.fail('allocated under unusable umask'))
    old = os.umask(0o777)
    try:
        with pytest.raises(ValueError, match='umask'):
            capture.CaptureSocketRoots.create(run)
    finally:
        os.umask(old)
    assert list(run.iterdir()) == []


def test_capture_root_refuses_stale_owner_and_replaced_directory(endpoint_root):
    root = endpoint_root
    binding = root.binding()
    binding['owner']['start_ticks'] += 1
    with pytest.raises(ValueError, match='generation changed'):
        capture.CaptureSocketRoots.open(root.files, binding)
    old = root.sockets.with_name(root.sockets.name + '.fixture-moved')
    root.sockets.rename(old)
    root.sockets.mkdir(mode=0o700)
    try:
        with pytest.raises(ValueError, match='directory changed'):
            root.verify_all()
    finally:
        root.sockets.rmdir()
        old.rename(root.sockets)


def test_capture_root_checks_exact_listener_set_and_connects_on_pinned_dirfd(endpoint_root):
    root = endpoint_root
    with ExitStack() as stack:
        listeners = [stack.enter_context(socket.socket(socket.AF_UNIX)) for _ in capture.NAMES]
        for name, listener in zip(capture.NAMES, listeners, strict=True):
            path = root.sockets / name
            listener.bind(str(path))
            path.chmod(0o600)
            listener.listen(1)
        assert set(root.verify_all()) == set(capture.NAMES)
        with socket.socket(socket.AF_UNIX) as client, root.connect_path(root.sockets / 'qmp.sock') as address:
            client.connect(address)
        (root.sockets / 'extra').touch()
        with pytest.raises(ValueError, match='exact four'):
            root.verify_all()
        (root.sockets / 'qmp.sock').chmod(0o660)
        with pytest.raises(ValueError, match='0600'):
            root.endpoint(root.sockets / 'qmp.sock')


def test_capture_root_launcher_uses_inherited_dirfd_and_direct_owner(endpoint_root):
    root = endpoint_root
    program = ('import os,sys; from pathlib import Path; import capture_socket_roots as c; '
               'c.RUNS = Path(sys.argv[1]); c.launcher_preflight(os.environ)')
    with root.launch() as (launch, fd), ExitStack() as stack:
        wrong = os.open(root.files, capture.DIR)
        stack.callback(os.close, wrong)
        env = dict(os.environ, **launch, QEMU_OUTPUT_DIR=str(root.files),
                   PYTHONPATH=str(Path(capture.__file__).parent), PYTHONDONTWRITEBYTECODE='1')
        args = ['/bin/bash', '-c', '"$@"; rc=$?; exit "$rc"', 'fixture', sys.executable,
                '-B', '-c', program, str(root.files.parent)]
        actual = subprocess.run(args, pass_fds=(fd,), env=env, capture_output=True, timeout=6)
        assert actual.returncode == 0, actual.stderr
        env[capture.FD_ENV] = str(wrong)
        bad = subprocess.run(args, pass_fds=(wrong,), env=env, capture_output=True, timeout=6)
        assert bad.returncode != 0 and b'wrong directory' in bad.stderr


def test_bwrap_exposes_the_same_writable_socket_directory(endpoint_root):
    root = endpoint_root
    bwrap = shutil.which('bwrap')
    if bwrap is None:
        pytest.skip('bwrap is not installed')
    program = ('import os,socket; os.umask(0o177); '
               's=socket.socket(socket.AF_UNIX); s.bind("/sockets/qmp.sock"); s.close(); '
               'print(os.stat("/sockets").st_ino)')
    with root.launch() as (_, fd):
        args = [bwrap, '--unshare-all', '--die-with-parent', '--clearenv', '--ro-bind', '/usr', '/usr',
                '--symlink', 'usr/lib', '/lib', '--symlink', 'usr/lib', '/lib64',
                '--bind-fd', str(fd), '/sockets', '/usr/bin/python3', '-B', '-c', program]
        child = subprocess.run(args, pass_fds=(fd,), capture_output=True, timeout=8)
        assert child.returncode == 0, child.stderr
        assert int(child.stdout) == os.fstat(fd).st_ino
    assert root.endpoint(root.sockets / 'qmp.sock')['mode'] == 0o600


def test_broker_rejects_fallback_and_wrong_root(endpoint_root, monkeypatch):
    import functional_camera_broker as broker

    root = endpoint_root
    options = dict(socket_profile=capture.PROFILE, socket_binding=root.binding(), socket_root=str(root.sockets))
    assert broker.endpoint_roots(root.files, **options).binding() == root.binding()
    with pytest.raises(ValueError, match='bound capture socket route'):
        broker.endpoint_roots(root.files)
    monkeypatch.setitem(options, 'socket_root', str(root.files))
    with pytest.raises(ValueError, match='root differs'):
        broker.endpoint_roots(root.files, **options)
