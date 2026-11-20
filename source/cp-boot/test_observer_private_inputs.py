"""Synthetic private-library checks; use project TMPDIR, never firmware assets.

These tests intentionally do not invoke a compiler, QEMU or the shell builder.
"""
import fcntl
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import stat
import tempfile

import pytest

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('observer_private_inputs_test', HERE / 'observer_private_inputs.py')
private = importlib.util.module_from_spec(spec)
spec.loader.exec_module(private)


def _newc(files):
    archive = bytearray()
    for number, (name, data) in enumerate([*files.items(), ('TRAILER!!!', b'')], 1):
        encoded = name.encode() + b'\0'
        fields = (number, stat.S_IFREG | 0o755, 0, 0, 1, 0, len(data),
                  0, 0, 0, 0, len(encoded), 0)
        archive.extend(b'070701' + ''.join(f'{field:08x}' for field in fields).encode())
        archive.extend(encoded)
        archive.extend(b'\0' * (-len(archive) % 4))
        archive.extend(data)
        archive.extend(b'\0' * (-len(archive) % 4))
    return bytes(archive)


@pytest.fixture
def case():
    # The API rejects /tmp even when pytest's default basetemp would use it.
    parent = private._canonical(os.environ.get('TMPDIR', str(HERE.parent / 'build')))
    with tempfile.TemporaryDirectory(prefix='observer-private-test-', dir=parent) as temp:
        root = Path(temp)
        analysis, output = root / 'analysis', root / 'build'
        lib = analysis / 'menu-root/lib'
        lib.mkdir(parents=True, mode=0o700)
        output.mkdir(mode=0o700)
        files = {}
        for name in private.LIBRARIES:
            data = (name.encode() + b'\0firmware library\n') * 17
            (lib / name).write_bytes(data)
            (lib / name).chmod(0o777)
            files['lib/' + name] = data
        image = analysis / 'menu-initramfs.cpio'
        image.write_bytes(_newc(files))
        image.chmod(0o600)
        yield analysis, output, files


def test_original_0777_libraries_are_copied_and_bound_to_base(case):
    analysis, output, files = case
    originals = {name: private._identity((analysis / 'menu-root' / name).stat()) for name in files}
    image_before = private._identity((analysis / 'menu-initramfs.cpio').stat())
    receipt = private.snapshot_libraries(str(analysis), str(output))
    assert receipt == json.loads((output / 'library-inputs.json').read_bytes())
    assert set(receipt) == {'schema', 'base_initramfs_sha256', 'libraries', 'physical_compatible'}
    assert receipt['schema'] == 'a7c2-observer-private-libraries-v1'
    assert receipt['physical_compatible'] is False
    assert receipt['base_initramfs_sha256'] == hashlib.sha256(_newc(files)).hexdigest()
    assert stat.S_IMODE((output / 'lib').stat().st_mode) == 0o700
    assert stat.S_IMODE((output / 'library-inputs.json').stat().st_mode) == 0o600
    assert set(receipt['libraries']) == set(files)
    for name, data in files.items():
        source, target = analysis / 'menu-root' / name, output / name
        assert receipt['libraries'][name] == dict(
            sha256=hashlib.sha256(data).hexdigest(), source=str(source), snapshot=str(target))
        assert target.read_bytes() == data == source.read_bytes()
        assert stat.S_IMODE(target.stat().st_mode) == 0o600
        assert target.stat().st_nlink == 1
        assert (target.stat().st_dev, target.stat().st_ino) != (source.stat().st_dev, source.stat().st_ino)
        assert private._identity(source.stat()) == originals[name]
    assert private._identity((analysis / 'menu-initramfs.cpio').stat()) == image_before


def test_link_uses_sealed_libraries_and_pinned_tmpdir(case, monkeypatch):
    analysis, output, files = case
    private.snapshot_libraries(analysis, output)
    (output / 'tmp').mkdir(mode=0o700)
    (output / 'snapshot').mkdir(mode=0o700)
    source = output / 'snapshot/menu-observe.c'
    source.touch()
    calls = []

    def compiler(argv, *, pass_fds, check, env):
        calls.append(argv)
        tmp_fd, *library_fds = pass_fds
        assert check and len(library_fds) == len(private.LIBRARIES)
        assert env['TMPDIR'] == f'/proc/self/fd/{tmp_fd}'
        assert os.path.samestat(os.fstat(tmp_fd), (output / 'tmp').stat())
        seals = fcntl.F_SEAL_SEAL | fcntl.F_SEAL_SHRINK | fcntl.F_SEAL_GROW | fcntl.F_SEAL_WRITE
        for name, fd in zip(private.LIBRARIES, library_fds, strict=True):
            assert f'/proc/self/fd/{fd}' in argv
            assert str(output / 'lib' / name) not in argv
            assert fcntl.fcntl(fd, fcntl.F_GET_SEALS) == seals
            assert os.pread(fd, private.MAX_LIBRARY_BYTES, 0) == files['lib/' + name]
        with (output / 'menu-observe.so').open('xb') as artifact:
            artifact.write(b'\x7fELF\x02\x01' + b'\x00' * 10 + b'\x03\x00\xb7\x00')

    monkeypatch.setattr(private.subprocess, 'run', compiler)
    private.link_observer(output, [source])
    assert len(calls) == 1
    with pytest.raises(ValueError, match='output already exists'):
        private.link_observer(output, [source])
    assert len(calls) == 1


def test_oversized_library_is_rejected_before_copy(case):
    analysis, output, _ = case
    source = analysis / 'menu-root/lib' / private.LIBRARIES[0]
    with source.open('r+b') as stream:
        stream.truncate(private.MAX_LIBRARY_BYTES + 1)
    with pytest.raises(ValueError, match='bounded input size'):
        private.snapshot_libraries(analysis, output)
    assert not (output / 'lib').exists()


def test_copy_itself_enforces_the_size_bound(case, monkeypatch):
    analysis, output, _ = case
    source = analysis / 'menu-root/lib' / private.LIBRARIES[0]
    monkeypatch.setattr(private, 'MAX_LIBRARY_BYTES', 32)
    parent = os.open(output, private.DIR_FLAGS)
    try:
        with source.open('rb') as stream:
            with pytest.raises(ValueError, match='grew beyond'):
                private._copy(stream.fileno(), parent, 'bounded')
            with pytest.raises(ValueError, match='bounded read'):
                private._digest(stream.fileno(), limit=32)
        assert (output/'bounded').stat().st_size <= 32
    finally:
        os.close(parent)


def test_cli_fixed_arguments_and_receipt_path(case, capsys):
    analysis, output, _ = case
    private.main(['--analysis', str(analysis), '--output', str(output)])
    assert capsys.readouterr().out.strip() == str(output / 'library-inputs.json')


def test_self_selected_library_not_in_anchor_is_rejected_with_partial_files(case):
    analysis, output, _ = case
    (analysis / 'menu-root/lib' / private.LIBRARIES[0]).write_bytes(b'self-selected replacement')
    with pytest.raises(ValueError, match='content differs'):
        private.snapshot_libraries(analysis, output)
    assert (output / 'lib' / private.LIBRARIES[0]).exists()
    assert not (output / 'library-inputs.json').exists()


@pytest.mark.parametrize('target', ['source', 'image'])
@pytest.mark.parametrize('kind', ['symlink', 'hardlink', 'fifo'])
def test_nonregular_or_linked_inputs_rejected(case, target, kind):
    analysis, output, _ = case
    path = (analysis / 'menu-initramfs.cpio' if target == 'image'
            else analysis / 'menu-root/lib' / private.LIBRARIES[0])
    other = analysis / 'keeper'
    path.rename(other)
    if kind == 'symlink':
        path.symlink_to(other)
    elif kind == 'hardlink':
        os.link(other, path)
    else:
        os.mkfifo(path)
    with pytest.raises((ValueError, OSError)):
        private.snapshot_libraries(analysis, output)
    assert other.exists()
    assert not (output / 'library-inputs.json').exists()


@pytest.mark.parametrize('kind', ['source', 'image', 'source-metadata', 'source-parent', 'image-content'])
def test_mutation_or_exchange_while_copying_fails_before_receipt(case, monkeypatch, kind):
    analysis, output, _ = case
    original_copy = private._copy
    changed = False

    def copy_then_exchange(*args):
        nonlocal changed
        result = original_copy(*args)
        if not changed:
            changed = True
            source = analysis / 'menu-root/lib' / private.LIBRARIES[0]
            if kind == 'source-metadata':
                source.chmod(0o700)
            elif kind == 'source-parent':
                source.parent.rename(source.parent.with_name('original-lib'))
                source.parent.mkdir(mode=0o700)
            elif kind == 'image-content':
                image = analysis / 'menu-initramfs.cpio'
                with image.open('r+b') as stream:
                    stream.write(b'broken')
            else:
                path = source if kind == 'source' else analysis / 'menu-initramfs.cpio'
                replacement = path.with_name('replacement')
                replacement.write_bytes(path.read_bytes())
                replacement.chmod(stat.S_IMODE(path.stat().st_mode))
                replacement.replace(path)
        return result

    monkeypatch.setattr(private, '_copy', copy_then_exchange)
    with pytest.raises((ValueError, OSError)):
        private.snapshot_libraries(analysis, output)
    assert (output / 'lib').exists()
    assert not (output / 'library-inputs.json').exists()


def test_source_exchange_between_stat_and_open_rejected(case, monkeypatch):
    analysis, output, _ = case
    original_open = os.open
    source = analysis / 'menu-root/lib' / private.LIBRARIES[0]
    changed = False

    def exchange_before_open(path, flags, *args, **kwargs):
        nonlocal changed
        if path == private.LIBRARIES[0] and flags == private.READ_FLAGS and not changed:
            changed = True
            replacement = source.with_name('replacement')
            replacement.write_bytes(source.read_bytes())
            replacement.chmod(0o777)
            replacement.replace(source)
        return original_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(private.os, 'open', exchange_before_open)
    with pytest.raises(ValueError, match='changed'):
        private.snapshot_libraries(analysis, output)
    assert changed
    assert not (output / 'library-inputs.json').exists()


def test_corrupt_private_snapshot_detected_after_anchor_verification(case, monkeypatch):
    analysis, output, _ = case
    verify = private.verify_image

    def verify_then_corrupt(*args):
        result = verify(*args)
        path = output / 'lib' / private.LIBRARIES[0]
        path.write_bytes(b'changed after verification')
        return result

    monkeypatch.setattr(private, 'verify_image', verify_then_corrupt)
    with pytest.raises(ValueError, match='Private library'):
        private.snapshot_libraries(analysis, output)
    assert not (output / 'library-inputs.json').exists()


@pytest.mark.parametrize('target', ['analysis', 'menu-root', 'source-lib', 'build', 'ancestor'])
def test_unsafe_directories_rejected(case, target):
    analysis, output, _ = case
    paths = {'analysis': analysis, 'menu-root': analysis / 'menu-root',
             'source-lib': analysis / 'menu-root/lib', 'build': output, 'ancestor': analysis.parent}
    paths[target].chmod(0o777)
    with pytest.raises(ValueError, match='directory|Directory'):
        private.snapshot_libraries(analysis, output)
    assert not (output / 'lib').exists()


@pytest.mark.parametrize('target', ['menu-root', 'source-lib', 'build'])
def test_symlinked_directories_rejected(case, target):
    analysis, output, _ = case
    path = {'menu-root': analysis / 'menu-root', 'source-lib': analysis / 'menu-root/lib',
            'build': output}[target]
    other = path.with_name(path.name + '-keeper')
    path.rename(other)
    path.symlink_to(other, target_is_directory=True)
    with pytest.raises((ValueError, OSError)):
        private.snapshot_libraries(analysis, output)
    assert not (output / 'library-inputs.json').exists()


@pytest.mark.parametrize('mode', [0o644, 0o755])
def test_build_directory_must_be_0700(case, mode):
    analysis, output, _ = case
    output.chmod(mode)
    with pytest.raises(ValueError, match='0700'):
        private.snapshot_libraries(analysis, output)


def test_anchor_cannot_be_group_or_world_writable(case):
    analysis, output, _ = case
    (analysis / 'menu-initramfs.cpio').chmod(0o666)
    with pytest.raises(ValueError, match='Base initramfs'):
        private.snapshot_libraries(analysis, output)
    assert not (output / 'lib').exists()


@pytest.mark.parametrize('name', ['lib', 'library-inputs.json'])
def test_output_is_exclusive_and_existing_files_unchanged(case, name):
    analysis, output, _ = case
    if name == 'lib':
        (output / name).mkdir(mode=0o700)
        keeper = output / name / 'keeper'
    else:
        keeper = output / name
    keeper.write_bytes(b'keep original')
    with pytest.raises((ValueError, OSError)):
        private.snapshot_libraries(analysis, output)
    assert keeper.read_bytes() == b'keep original'


@pytest.mark.parametrize('path', ['/tmp/observer', '/dev/shm/observer', '/proc/self/fd/1',
                                 '/sys/observer', '/run/user/observer', '/var/tmp/observer',
                                 'relative', '/home/../tmp/observer', '//home/observer'])
def test_forbidden_or_noncanonical_paths_rejected(path):
    with pytest.raises(ValueError):
        private.snapshot_libraries(path, path)


def test_same_or_nested_paths_rejected(case):
    analysis, output, _ = case
    for destination in (analysis, analysis / 'nested', analysis.parent):
        with pytest.raises(ValueError, match='separate'):
            private.snapshot_libraries(analysis, destination)


def test_missing_output_not_created(case):
    analysis, output, _ = case
    output.rmdir()
    with pytest.raises(OSError):
        private.snapshot_libraries(analysis, output)
    assert not output.exists()
