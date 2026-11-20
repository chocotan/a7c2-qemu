"""Host-only interoperation of the real Python lease and persistent-flash OFD lock.

The disk, source images, compiler output and child logs all live under tmp_path.
No VM, device node, QEMU process or signal-based cleanup is used.
"""
from contextlib import ExitStack, contextmanager
import errno
import fcntl
import hashlib
import json
import os
from pathlib import Path
import runpy
import select
import struct
import subprocess
import sys
import time
import ctypes

import pytest


HERE = Path(__file__).resolve().parent
DISK = runpy.run_path(str(HERE / 'persistent_disk.py'))
CORE = HERE.parents[1] / 'source' / 'persistent-flash'
CHILD_SECONDS = 5


@pytest.fixture
def camera(tmp_path, monkeypatch):
    """Use create/lease unchanged apart from reducing the synthetic user capacity."""
    source = tmp_path / 'source'
    source.mkdir(mode=0o700)
    rows, records, start = [], [], 128
    for number in range(1, 31):
        sectors = 8 if number in DISK['PARTS'] else 0
        rows.append(f'0x{start:08x},0x{sectors:08x},0x00000004,0xffffffff\n')
        if sectors:
            name = DISK['image_name'](number)
            data = bytes([number]) * (sectors * 512)
            (source / name).write_bytes(data)
            records.append(dict(name=name, bytes=len(data), sha256=hashlib.sha256(data).hexdigest()))
        start += sectors
    for number in ('B0', 'B1'):
        name = f'nflasha{number}.img'
        data = bytes(DISK['BOOT_BYTES'])
        (source / name).write_bytes(data)
        records.append(dict(name=name, bytes=len(data), sha256=hashlib.sha256(data).hexdigest()))
    config = tmp_path / 'partinf.conf'
    config.write_text(''.join(rows))
    (source / 'manifest.json').write_text(json.dumps(dict(source='official-bodydata-derived', images=records)))
    monkeypatch.setitem(DISK['create'].__globals__, 'USER_CAPACITY', 1024 * 1024)
    instance = tmp_path / 'instance'
    DISK['create'](source, config, instance)
    return instance


def disk_digest(instance):
    with (instance / 'camera.emmc').open('rb') as stream:
        return DISK['hashed'](stream.fileno())


def receive_byte(child, expected):
    deadline = time.monotonic() + CHILD_SECONDS
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError(f'child {child.pid} did not send {expected!r}')
        ready, _, _ = select.select([child.stdout], [], [], remaining)
        if ready:
            actual = os.read(child.stdout.fileno(), 1)
            if actual != expected:
                raise RuntimeError(f'child {child.pid}: expected {expected!r}, received {actual!r}')
            return


@contextmanager
def inherited_child(fd, tmp_path):
    """EOF releases the child even when a test fails before its CLOSE command."""
    with (tmp_path / 'ofd-child.stderr').open('xb') as errors:
        child = subprocess.Popen(
            [sys.executable, '-I', '-S', str(HERE / 'persistent_disk_ofd_child.py'),
             str(fd), str(CHILD_SECONDS)],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=errors,
            pass_fds=(fd,), close_fds=True,
            env={**os.environ, 'TMPDIR': str(tmp_path)},
        )
        try:
            receive_byte(child, b'R')
            yield child
        finally:
            # Never use communicate(timeout), a Popen context manager or kill/terminate.
            try:
                child.stdin.close()
            except OSError:
                pass
            try:
                while True:
                    try:
                        child.wait(timeout=CHILD_SECONDS + 2)
                        break
                    except (KeyboardInterrupt, InterruptedError):
                        continue
            except subprocess.TimeoutExpired as error:
                try:
                    (tmp_path / 'ofd-child-blocked.json').write_text(json.dumps(dict(
                        pid=child.pid, state='blocked-not-reaped', signals_sent=False,
                        reason='child exceeded its own nonblocking protocol deadline',
                    )))
                except OSError:
                    pass
                while True:
                    try:
                        child.wait()
                        break
                    except (KeyboardInterrupt, InterruptedError):
                        continue
                raise RuntimeError(f'child {child.pid} exceeded its self-exit guard; no signals sent') from error
            finally:
                child.stdout.close()
        assert child.returncode == 0, (child.returncode, (tmp_path / 'ofd-child.stderr').read_text())


def test_exec_inherited_ofd_outlives_parent_lease(camera, tmp_path):
    before = disk_digest(camera)
    try:
        with ExitStack() as leases:
            parent = leases.enter_context(DISK['lease'](camera))
            with inherited_child(parent['fd'], tmp_path) as child:
                leases.close()
                with pytest.raises(BlockingIOError):
                    with DISK['lease'](camera):
                        pytest.fail('exec-inherited OFD admitted an independent writer')
                assert disk_digest(camera) == before
                assert os.write(child.stdin.fileno(), b'C') == 1
                receive_byte(child, b'C')
        with DISK['lease'](camera) as next_owner:
            assert os.pread(next_owner['fd'], 8, 0) == b'82462.00'
    finally:
        assert disk_digest(camera) == before


@pytest.fixture
def flash_wrapper(tmp_path):
    """Compile the current production core; a missing compiler is a failure, not a skip."""
    library = tmp_path / 'ofd-flash-core.so'
    with (tmp_path / 'ofd-compile.log').open('xb') as log:
        compiler = subprocess.Popen(
            ['cc', '-std=c11', '-Wall', '-Wextra', '-Werror', '-fPIC', '-shared',
             '-I', str(CORE), str(HERE / 'persistent_disk_ofd_core.c'),
             str(CORE / 'flash-core.c'), '-o', str(library)],
            stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
            env={**os.environ, 'TMPDIR': str(tmp_path)}, close_fds=True,
        )
        # Compilation is reaped naturally; subprocess.run(timeout) would send SIGKILL.
        interrupted=False
        while True:
            try:
                result = compiler.wait()
                break
            except KeyboardInterrupt:
                interrupted=True
            except InterruptedError:
                continue
    if interrupted:raise RuntimeError('compiler wait interrupted; compiler was reaped without signals')
    assert result == 0, (tmp_path / 'ofd-compile.log').read_text()
    wrapper = ctypes.CDLL(str(library))
    wrapper.check_ofd.argtypes = [ctypes.c_int, ctypes.c_int]
    wrapper.check_ofd.restype = ctypes.c_int
    return wrapper


def test_real_flash_core_shares_ofd_and_close_retains_parent_lock(camera, tmp_path, flash_wrapper):
    before = disk_digest(camera)
    try:
        with DISK['lease'](camera) as parent:
            geometry = parent['geometry']
            wire = struct.pack('<8sIIQ', b'A7PFGE01', 1, len(geometry['slices']), geometry['user_bytes'])
            for item in geometry['slices']:
                suffix = item['id'].removeprefix('nflasha')
                number = 31 + int(suffix[1:]) if suffix.startswith('B') else int(suffix)
                wire += struct.pack('<IIQQ', number, 0, item['offset'], item['bytes'])
            path = tmp_path / 'geometry.wire'
            path.write_bytes(wire)
            path.chmod(0o600)
            with path.open('rb') as stream:
                assert flash_wrapper.check_ofd(parent['fd'], stream.fileno()) == 0
            # The C helper has closed both contexts. Only the parent's OFD remains.
            independent = os.open(camera / 'camera.emmc', os.O_RDWR | os.O_NOFOLLOW)
            try:
                lock = DISK['_DiskLock'](fcntl.F_WRLCK, os.SEEK_SET, 0, 1, 0)
                with pytest.raises(OSError) as blocked:
                    fcntl.fcntl(independent, fcntl.F_OFD_SETLK, bytes(lock))
                assert blocked.value.errno in (errno.EACCES, errno.EAGAIN)
            finally:
                os.close(independent)
        with DISK['lease'](camera) as next_owner:
            assert os.pread(next_owner['fd'], 8, 0) == b'82462.00'
    finally:
        assert disk_digest(camera) == before
