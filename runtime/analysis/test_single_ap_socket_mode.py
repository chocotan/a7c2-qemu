"""OS AF_UNIX permissions only; does not execute QEMU or validate its sockets."""
import json
import os
from pathlib import Path
import secrets
import stat
import subprocess
import sys

import pytest


DIRECTORY_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
LISTENER = Path(__file__).with_name('single_ap_socket_mode_listener.py')


def identity(value):
    return (value.st_dev, value.st_ino, value.st_uid, value.st_mode, value.st_nlink)


def check_directory(value, uid, mode=None):
    assert stat.S_ISDIR(value.st_mode), 'not a directory'
    assert value.st_uid == uid, 'directory owner changed'
    if mode is None:
        assert not value.st_mode & 0o022, 'directory permits foreign writes'
    else:
        assert stat.S_IMODE(value.st_mode) == mode, 'directory permissions changed'


@pytest.mark.parametrize(('mask', 'expected_mode'), [('0177', 0o600), ('077', 0o700)])
def test_shell_umask_controls_real_unix_socket(mask, expected_mode, tmp_path):
    """A real bind under sh establishes permissions, without a QEMU claim."""
    uid = os.geteuid()
    descriptors = []
    directory_name = None
    directory_identity = None
    endpoint_identity = None
    process = None
    try:
        descriptors.append(os.open('/run', DIRECTORY_FLAGS))
        check_directory(os.fstat(descriptors[-1]), 0)
        descriptors.append(os.open('user', DIRECTORY_FLAGS, dir_fd=descriptors[-1]))
        check_directory(os.fstat(descriptors[-1]), 0)
        descriptors.append(os.open(str(uid), DIRECTORY_FLAGS, dir_fd=descriptors[-1]))
        user_fd = descriptors[-1]
        user_identity = identity(os.fstat(user_fd))[:4]
        check_directory(os.fstat(user_fd), uid, 0o700)
        # mkdir is exclusive; do not adopt or remove a colliding directory.
        name = 'as-' + secrets.token_hex(4)
        os.mkdir(name, 0o700, dir_fd=user_fd)
        directory_name = name
        created = os.stat(name, dir_fd=user_fd, follow_symlinks=False)
        directory_identity = identity(created)
        check_directory(created, uid, 0o700)
        descriptors.append(os.open(name, DIRECTORY_FLAGS, dir_fd=user_fd))
        work_fd = descriptors[-1]
        assert identity(os.fstat(work_fd)) == directory_identity
        assert len(os.fsencode(f'/run/user/{uid}/{name}/s')) < 108
        process = subprocess.Popen(
            ['/usr/bin/sh', '-c', f'umask {mask}; exec "$@"', 'socket-mode-test',
             sys.executable, '-B', str(LISTENER), str(work_fd),
             str(created.st_dev), str(created.st_ino), str(uid)],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            pass_fds=(work_fd,),
        )
        line = process.stdout.readline()
        assert line, 'listener exited before reporting bind identity'
        reported = tuple(json.loads(line))
        endpoint = os.stat('s', dir_fd=work_fd, follow_symlinks=False)
        assert stat.S_ISSOCK(endpoint.st_mode), 'endpoint is not an AF_UNIX socket'
        assert endpoint.st_uid == uid and endpoint.st_nlink == 1
        assert identity(endpoint) == reported, 'bound socket identity changed'
        endpoint_identity = reported
        assert stat.S_IMODE(endpoint.st_mode) == expected_mode
    finally:
        try:
            if process is not None:
                # EOF closes the listener naturally; no timeout kill or signals.
                output, errors = process.communicate()
                assert process.returncode == 0, errors.decode(errors='replace')
                assert output == b'', 'unexpected listener output after bind'
        finally:
            try:
                if directory_identity is not None:
                    if process is not None and process.poll() is None:
                        raise AssertionError('listener still live; retaining owned directory')
                    assert identity(os.fstat(user_fd))[:4] == user_identity
                    assert identity(os.stat(str(uid), dir_fd=descriptors[1],
                                            follow_symlinks=False))[:4] == user_identity
                    assert identity(os.stat(directory_name, dir_fd=user_fd,
                                            follow_symlinks=False)) == directory_identity
                    if endpoint_identity is not None:
                        assert identity(os.fstat(work_fd)) == directory_identity
                        assert identity(os.stat('s', dir_fd=work_fd,
                                                follow_symlinks=False)) == endpoint_identity
                    receipt = {
                        'directory': f'/run/user/{uid}/{directory_name}',
                        'directory_identity': directory_identity,
                        'socket_identity': endpoint_identity,
                        'owner_pid': process.pid if process is not None else None,
                        'owner_exit_observed': process is None or process.poll() is not None,
                        'cleanup': 'blocked until complete reference audit',
                        'next_consumer': 'main session ownership audit',
                    }
                    path=tmp_path/'retained-socket.json'
                    raw=(json.dumps(receipt,sort_keys=True)+'\n').encode()
                    with path.open('xb') as stream:
                        stream.write(raw);stream.flush();os.fsync(stream.fileno())
                    assert path.read_bytes()==raw
                elif directory_name is not None:
                    path=tmp_path/'retained-socket.json'
                    raw=(json.dumps({'directory':f'/run/user/{uid}/{directory_name}',
                                     'cleanup':'blocked: directory identity unknown',
                                     'next_consumer':'main session ownership audit'},sort_keys=True)+'\n').encode()
                    with path.open('xb') as stream:
                        stream.write(raw);stream.flush();os.fsync(stream.fileno())
                    assert path.read_bytes()==raw
                    raise AssertionError('directory identity unknown; retaining it')
            finally:
                for descriptor in reversed(descriptors):
                    os.close(descriptor)
