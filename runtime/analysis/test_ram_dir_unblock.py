"""Host-only directory candidate tests; no seed, fsck, guest or capture claim."""
from contextlib import ExitStack
import errno
import fcntl
import importlib.util
import os
from pathlib import Path
import re
import stat
import sys

import pytest

HERE = Path(__file__).absolute().parent
ROOT = next(p for p in HERE.parents if (p / 'final/a7c2-qemu/runtime/analysis/sd_transport.py').is_file())
sys.path.insert(0, str(ROOT / 'final/a7c2-qemu/runtime/analysis'))
SPEC = importlib.util.spec_from_file_location('ram_directory_candidate', HERE / 'backup_profile.py')
backup = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(backup)


def create(parent):
    return backup._RamProfileOutput._create_directory(
        parent, candidate=backup._RAM_DIRECTORY_CREATION_CANDIDATE)


@pytest.fixture
def parent(tmp_path):
    tmp_path.chmod(0o700)
    fd = os.open(tmp_path, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
    try:
        yield fd
    finally:
        os.close(fd)


class TestCreation:
    def test_production_uses_reviewed_creation(self, parent):
        assert backup._RAM_DIRECTORY_CREATION_BLOCKED is None
        name, fd = backup._RamProfileOutput._create_directory(parent)
        try:
            assert os.stat(name, dir_fd=parent).st_ino == os.fstat(fd).st_ino
        finally:
            os.close(fd)

    def test_candidate_requires_exact_selection(self, parent):
        with pytest.raises(ValueError, match='candidate differs'):
            backup._RamProfileOutput._create_directory(parent, candidate='unreviewed')
        assert not os.listdir(parent)

    def test_random_names_are_unique_128_bit_and_fd_is_private(self, parent, monkeypatch):
        actual = backup.secrets.token_hex
        requests = []

        def token(count):
            requests.append(count)
            return actual(count)

        monkeypatch.setattr(backup.secrets, 'token_hex', token)
        names = set()
        for _ in range(32):
            name, fd = create(parent)
            try:
                assert re.fullmatch(r'profile-[0-9a-f]{32}', name)
                assert name not in names
                names.add(name)
                held = os.fstat(fd)
                assert held.st_uid == os.geteuid()
                assert stat.S_IMODE(held.st_mode) == 0o700
                assert fcntl.fcntl(fd, fcntl.F_GETFD) & fcntl.FD_CLOEXEC
                assert (held.st_dev, held.st_ino) == (os.stat(name, dir_fd=parent).st_dev,
                                                        os.stat(name, dir_fd=parent).st_ino)
                assert not os.listdir(fd)
            finally:
                os.close(fd)
        assert requests == [16] * 32

    def test_eexist_retries_fresh_random_name(self, parent, monkeypatch):
        existing = 'profile-' + 'a' * 32
        os.mkdir(existing, 0o700, dir_fd=parent)
        held = os.stat(existing, dir_fd=parent)
        choices = iter(['a' * 32, 'b' * 32])
        monkeypatch.setattr(backup.secrets, 'token_hex', lambda count: next(choices))
        name, fd = create(parent)
        try:
            assert name == 'profile-' + 'b' * 32
            assert os.stat(existing, dir_fd=parent).st_ino == held.st_ino
        finally:
            os.close(fd)

    def test_collision_retries_are_bounded(self, parent, monkeypatch):
        os.mkdir('profile-' + 'a' * 32, 0o700, dir_fd=parent)
        requests = []

        def token(count):
            requests.append(count)
            return 'a' * 32

        monkeypatch.setattr(backup.secrets, 'token_hex', token)
        with pytest.raises(ValueError, match='exhausted collision retries'):
            create(parent)
        assert requests == [16] * 8
        assert len(os.listdir(parent)) == 1

    @pytest.mark.parametrize('mode', [0o755, 0o770, 0o777])
    def test_nonprivate_parent_is_rejected(self, parent, mode):
        os.fchmod(parent, mode)
        try:
            with pytest.raises(ValueError, match='owned 0700 directory FD'):
                create(parent)
            assert not os.listdir(parent)
        finally:
            os.fchmod(parent, 0o700)

    def test_nondirectory_parent_is_rejected(self, tmp_path):
        source = tmp_path / 'regular'
        source.write_bytes(b'input')
        fd = os.open(source, os.O_RDONLY)
        try:
            with pytest.raises(ValueError, match='owned 0700 directory FD'):
                create(fd)
        finally:
            os.close(fd)

    @pytest.mark.parametrize('replacement', ['directory', 'symlink'])
    def test_replacement_between_stat_and_open_is_rejected(self, parent, monkeypatch, replacement):
        actual_open = os.open
        opened = []

        def swap(name, flags, *args, **kwargs):
            if isinstance(name, str) and name.startswith('profile-') and kwargs.get('dir_fd') == parent:
                os.rename(name, 'original', src_dir_fd=parent, dst_dir_fd=parent)
                if replacement == 'directory':
                    os.mkdir(name, 0o700, dir_fd=parent)
                else:
                    os.symlink('original', name, dir_fd=parent)
                fd = actual_open(name, flags, *args, **kwargs)
                opened.append(fd)
                return fd
            return actual_open(name, flags, *args, **kwargs)

        monkeypatch.setattr(os, 'open', swap)
        if replacement == 'directory':
            with pytest.raises(ValueError, match='newly opened directory identity differs'):
                create(parent)
        else:
            with pytest.raises(OSError) as failure:
                create(parent)
            assert failure.value.errno in (errno.ENOTDIR, errno.ELOOP)
        assert 'original' in os.listdir(parent)
        for fd in opened:
            with pytest.raises(OSError) as closed:
                os.fstat(fd)
            assert closed.value.errno == errno.EBADF

    def test_replacement_after_open_is_rejected(self, parent, monkeypatch):
        actual_stat = os.stat
        calls = 0

        def swap(name, *args, **kwargs):
            nonlocal calls
            if isinstance(name, str) and name.startswith('profile-') and kwargs.get('dir_fd') == parent:
                calls += 1
                if calls == 2:
                    os.rename(name, 'original', src_dir_fd=parent, dst_dir_fd=parent)
                    os.mkdir(name, 0o700, dir_fd=parent)
            return actual_stat(name, *args, **kwargs)

        monkeypatch.setattr(os, 'stat', swap)
        with pytest.raises(ValueError, match='newly opened directory identity differs'):
            create(parent)
        assert calls == 2

    def test_same_uid_swap_before_first_stat_is_outside_contract(self, parent, monkeypatch):
        # This documents the real limitation rather than claiming atomic mkdir identity.
        actual_mkdir = os.mkdir

        def swap(name, mode=0o777, *, dir_fd=None):
            actual_mkdir(name, mode, dir_fd=dir_fd)
            if name.startswith('profile-'):
                os.rename(name, 'original', src_dir_fd=parent, dst_dir_fd=parent)
                actual_mkdir(name, mode, dir_fd=dir_fd)

        monkeypatch.setattr(os, 'mkdir', swap)
        name, fd = create(parent)
        try:
            assert os.fstat(fd).st_ino == os.stat(name, dir_fd=parent).st_ino
            assert os.fstat(fd).st_ino != os.stat('original', dir_fd=parent).st_ino
        finally:
            os.close(fd)

    def test_mkdir_permission_failure_is_not_retried(self, parent, monkeypatch):
        attempts = []

        def denied(*args, **kwargs):
            attempts.append(args)
            raise PermissionError(errno.EACCES, 'synthetic mkdir denial')

        monkeypatch.setattr(os, 'mkdir', denied)
        with pytest.raises(PermissionError, match='synthetic mkdir denial'):
            create(parent)
        assert len(attempts) == 1

    def test_parent_mode_change_is_rejected_and_fd_closed(self, parent, monkeypatch):
        actual_open = os.open
        opened = []

        def change(name, flags, *args, **kwargs):
            fd = actual_open(name, flags, *args, **kwargs)
            if isinstance(name, str) and name.startswith('profile-') and kwargs.get('dir_fd') == parent:
                opened.append(fd)
                os.fchmod(parent, 0o755)
            return fd

        monkeypatch.setattr(os, 'open', change)
        try:
            with pytest.raises(ValueError, match='creation parent changed'):
                create(parent)
            for fd in opened:
                with pytest.raises(OSError) as closed:
                    os.fstat(fd)
                assert closed.value.errno == errno.EBADF
        finally:
            os.fchmod(parent, 0o700)

    def test_fsync_failure_closes_fd_and_preserves_directory(self, parent, monkeypatch):
        actual_open = os.open
        opened = []

        def record(*args, **kwargs):
            fd = actual_open(*args, **kwargs)
            opened.append(fd)
            return fd

        def failed(fd):
            raise OSError(errno.EIO, 'synthetic fsync failure')

        monkeypatch.setattr(os, 'open', record)
        monkeypatch.setattr(os, 'fsync', failed)
        with pytest.raises(OSError, match='synthetic fsync failure'):
            create(parent)
        assert len(os.listdir(parent)) == 1
        assert len(opened) == 1
        with pytest.raises(OSError) as closed:
            os.fstat(opened[0])
        assert closed.value.errno == errno.EBADF


class TestLeaseChecks:
    @pytest.fixture
    def output(self, tmp_path, monkeypatch):
        # The candidate tests alone simulate the owner's eventual reviewed gate change.
        monkeypatch.setattr(backup, '_RAM_DIRECTORY_CREATION_BLOCKED', None)
        with ExitStack() as stack:
            yield backup._RamProfileOutput(stack, tmp_path / 'profiles')

    def test_fd_relative_write_readback_and_check(self, output, monkeypatch):
        output.write('source-board.dtb', b'synthetic board bytes')
        assert output.read('source-board.dtb') == b'synthetic board bytes'
        actual_open = os.open
        forbidden = str(output.output)

        def checked(name, *args, **kwargs):
            if str(name) == forbidden or name == output.output.name:
                raise AssertionError('output directory must not be reopened for file I/O')
            return actual_open(name, *args, **kwargs)

        monkeypatch.setattr(os, 'open', checked)
        output.check()

    def test_directory_replacement_is_rejected(self, output):
        original = output.output.with_name('original')
        output.output.rename(original)
        output.output.mkdir(mode=0o700)
        with pytest.raises(ValueError, match='output directory changed'):
            output.check()

    def test_parent_replacement_is_rejected(self, output):
        output.parent.rename(output.parent.with_name('original-parent'))
        output.parent.mkdir(mode=0o700)
        with pytest.raises(ValueError, match='output parent changed'):
            output.check()

    @pytest.mark.parametrize('target', ['parent', 'output'])
    def test_permission_drift_is_rejected(self, output, target):
        path = output.parent if target == 'parent' else output.output
        path.chmod(0o750)
        try:
            with pytest.raises(ValueError, match='output (parent|directory) changed'):
                output.check()
        finally:
            path.chmod(0o700)

    def test_replaced_file_rejected_through_held_directory(self, output):
        output.write('source-board.dtb', b'synthetic board bytes')
        path = output.output / 'source-board.dtb'
        path.rename(path.with_suffix('.original'))
        path.write_bytes(b'synthetic board bytes')
        with pytest.raises(ValueError, match='derived file identity changed'):
            output.check()
