"""Draft host tests only; synthetic 8KiB cards do not establish FAT16/fsck/guest success.

Run in a fresh interpreter with project-local TMPDIR and --basetemp. No VM,
physical device, signal or subprocess execution belongs to this draft.
"""
from contextlib import ExitStack
import fcntl
import hashlib
import os
from pathlib import Path
import sys
from unittest import mock

import pytest

HERE = Path(__file__).absolute().parent
if not (HERE / 'sd_transport.py').is_file():
    repository = next(parent for parent in HERE.parents
                      if (parent / 'final/a7c2-qemu/runtime/analysis/sd_transport.py').is_file())
    sys.path.insert(0, str(repository / 'final/a7c2-qemu/runtime/analysis'))
sys.path.insert(0, str(HERE))
import backup_profile as backup
import functional_ram_initramfs as ram
import sparse_seed

if any(Path(module.__file__).absolute().parent != HERE
       for module in (backup, ram, sparse_seed)):
    raise RuntimeError('Draft requires a fresh interpreter loading all three candidate modules')


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


@pytest.fixture
def output(tmp_path, monkeypatch):
    # Only host contract tests bypass this gate. No creation-isolation proof is inferred.
    monkeypatch.setattr(backup, '_RAM_DIRECTORY_CREATION_BLOCKED', None)
    with ExitStack() as stack:
        yield backup._RamProfileOutput(stack, tmp_path / 'profiles')


@pytest.fixture
def synthetic_seed(tmp_path, monkeypatch):
    monkeypatch.setattr(backup, 'FUNCTIONAL_CAMERA_RAM_BYTES', 8192)
    monkeypatch.setattr(sparse_seed, 'TOTAL', 8192)
    # Deliberate test double: file copy/FD binding only, never FAT16 acceptance.
    monkeypatch.setattr(ram, 'fat16', lambda fd, size: {'synthetic_layout_only': True})
    path = tmp_path / 'source.fat'
    path.write_bytes(b'S' * 4096 + bytes(4096))
    path.chmod(0o600)
    proof, _ = backup._bound_profile_input(path, expected_bytes=8192, single_link=True)
    return path, proof


def prepare_handoff(output, proof, consumer_stack):
    cloned, sparse = output.copy_seed(proof, parallel_peak_bytes=0)
    output.write('kernel-ram-backup.sh', b'# synthetic, never executed\n')
    output.write('board-ram-backup.dtb', b'synthetic, never consumed\n')
    output.publish('{"synthetic":true,"capture_verified":false}\n')
    owner = backup._RamProfileLease(consumer_stack, 0)
    env = {'A7C2_SD_IMAGE': cloned['path'],
           'MENU_KERNEL_SCRIPT': str(output.output / 'kernel-ram-backup.sh'),
           'MENU_DTB': str(output.output / 'board-ram-backup.dtb'),
           'MENU_BACKUP_PROFILE_RECEIPT': str(output.output / 'backup-profile.json')}
    return owner, output.consumer_environment(output, env, owner), cloned, sparse


def test_creation_gate_is_fixed_and_environment_cannot_disable_it(tmp_path, monkeypatch):
    monkeypatch.setenv('A7C2_RAM_DIRECTORY_CREATION_BLOCKED', '')
    assert backup._RAM_DIRECTORY_CREATION_BLOCKED is None
    monkeypatch.setattr(backup, '_RAM_DIRECTORY_CREATION_BLOCKED', 'synthetic creation refusal')
    with backup.directory(tmp_path) as parent:
        with pytest.raises(ValueError, match='synthetic creation refusal'):
            backup._RamProfileOutput._create_directory(parent)
    assert not list(tmp_path.iterdir())


def test_existing_path_only_handoff_refusal_is_unchanged():
    with pytest.raises(ValueError, match='consumer handoff refused: no caller-held exact FD binding'):
        backup._RamProfileOutput.consumer_environment()


def test_gated_creation_pins_private_empty_directory(output):
    named, held = output.output.stat(), os.fstat(output.fd)
    assert named.st_mode & 0o777 == held.st_mode & 0o777 == 0o700
    assert (named.st_dev, named.st_ino) == (held.st_dev, held.st_ino)
    assert not os.listdir(output.fd)
    output.check()


@pytest.mark.parametrize('mode', [0o755, 0o770, 0o777])
def test_gated_creation_refuses_nonprivate_parent(tmp_path, monkeypatch, mode):
    monkeypatch.setattr(backup, '_RAM_DIRECTORY_CREATION_BLOCKED', None)
    tmp_path.chmod(mode)
    parent = os.open(tmp_path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        with pytest.raises(ValueError, match='0700 directory FD'):
            backup._RamProfileOutput._create_directory(parent)
    finally:
        os.close(parent)
        tmp_path.chmod(0o700)
    assert not list(tmp_path.iterdir())


def test_seed_is_independent_single_link_private_and_sparse_verified(output, synthetic_seed):
    source, proof = synthetic_seed
    before = source.stat(), sha(source)
    cloned, sparse = output.copy_seed(proof, parallel_peak_bytes=0)
    target = Path(cloned['path'])
    assert target.stat().st_ino != source.stat().st_ino
    assert target.stat().st_nlink == 1 and target.stat().st_mode & 0o777 == 0o600
    assert cloned['sha256'] == sha(target) == proof['sha256']
    assert cloned['identity'] == list(backup.identity(target.stat()))
    assert sparse['source_sha256'] == proof['sha256']
    assert sha(Path(sparse['path']) / 'manifest.json') == sparse['manifest_sha256']
    assert sparse['representation_only'] is True
    assert sparse['fsck_verified'] is sparse['guest_consumption_verified'] is False
    assert source.stat().st_ino == before[0].st_ino and sha(source) == before[1]
    output.check()


def test_consumer_receives_exact_readonly_fd_triple(output, synthetic_seed):
    _, proof = synthetic_seed
    with ExitStack() as consumer_stack:
        owner, binding, cloned, _ = prepare_handoff(output, proof, consumer_stack)
        triple = binding['fd'], binding['dir_fd'], binding['receipt_fd']
        assert binding['pass_fds'] == triple
        assert binding['environment']['A7C2_RAM_CARD_SEED_FD'] == str(triple[0])
        assert binding['environment']['A7C2_RAM_CARD_DIRECTORY_FD'] == str(triple[1])
        assert binding['environment']['A7C2_RAM_CARD_RECEIPT_FD'] == str(triple[2])
        assert list(backup.identity(os.fstat(triple[0]))) == cloned['identity']
        for fd in (triple[0], triple[2]):
            assert fcntl.fcntl(fd, fcntl.F_GETFL) & os.O_ACCMODE == os.O_RDONLY
        assert owner.verify()['host_fd_binding_verified'] is True
        assert binding['consumer_endpoint_verified'] is binding['guest_consumption_verified'] is False
    owner.active = False
    for fd in triple:
        with pytest.raises(OSError):
            os.fstat(fd)
    with pytest.raises(ValueError, match='closed or unbound'):
        binding['verify']()


def test_consumer_cannot_close_and_reopen_same_fd_number(output, synthetic_seed):
    _, proof = synthetic_seed
    with ExitStack() as consumer_stack:
        owner, binding, cloned, _ = prepare_handoff(output, proof, consumer_stack)
        fd = binding['fd']
        saved = os.dup(fd)
        os.close(fd)
        replacement = os.open(cloned['path'], os.O_RDONLY | os.O_NOFOLLOW)
        try:
            if replacement != fd:
                os.dup2(replacement, fd)
                os.close(replacement)
            with pytest.raises(BlockingIOError):
                owner.verify()
        finally:
            os.dup2(saved, fd)
            os.close(saved)
        assert owner.verify()['host_fd_binding_verified'] is True


def test_consumer_rejects_changed_environment_without_path_fallback(output, synthetic_seed):
    _, proof = synthetic_seed
    with ExitStack() as consumer_stack:
        owner, binding, _, _ = prepare_handoff(output, proof, consumer_stack)
        binding['environment']['A7C2_SD_IMAGE'] = '/unrelated/path.fat'
        with pytest.raises(ValueError, match='FD/environment handoff changed'):
            owner.verify()


@pytest.mark.parametrize('change', ['rewrite', 'replace', 'hardlink', 'chmod'])
def test_source_identity_drift_is_rejected_before_clone(output, synthetic_seed, change):
    path, proof = synthetic_seed
    raw = path.read_bytes()
    if change == 'replace':
        path.rename(path.with_suffix('.original'))
        path.write_bytes(raw)
        path.chmod(0o600)
    elif change == 'rewrite':
        path.write_bytes(raw)
        os.utime(path, ns=(path.stat().st_atime_ns, path.stat().st_mtime_ns + 1))
    elif change == 'hardlink':
        os.link(path, path.with_suffix('.alias'))
    else:
        path.chmod(0o660)
    with pytest.raises(ValueError, match='seed identity changed before copy'):
        output.copy_seed(proof, parallel_peak_bytes=0)
    assert not (output.output / 'media-camera.fat').exists()
    assert (output.output / 'storage.json').is_file()


def test_midcopy_source_mutation_keeps_original_error_and_evidence(output, synthetic_seed, monkeypatch):
    path, proof = synthetic_seed
    original_pread = os.pread
    changed = False

    def mutate(fd, count, offset):
        nonlocal changed
        raw = original_pread(fd, count, offset)
        if not changed and os.fstat(fd).st_ino == path.stat().st_ino:
            changed = True
            with path.open('r+b') as stream:
                stream.write(b'M')
        return raw

    monkeypatch.setattr(os, 'pread', mutate)
    with pytest.raises(ValueError, match='source/clone readback differs'):
        output.copy_seed(proof, parallel_peak_bytes=0)
    assert changed and (output.output / 'media-camera.fat').is_file()
    assert (output.output / 'storage.json').is_file()


def test_storage_failure_adds_note_without_replacing_seed_error(output, synthetic_seed, monkeypatch):
    path, proof = synthetic_seed
    path.chmod(0o660)
    original_write = output.write

    def fail_storage(name, raw):
        if name == 'storage.json':
            raise OSError('synthetic receipt failure')
        return original_write(name, raw)

    monkeypatch.setattr(output, 'write', fail_storage)
    with pytest.raises(ValueError, match='seed identity changed before copy') as caught:
        output.copy_seed(proof, parallel_peak_bytes=0)
    assert any('synthetic receipt failure' in note for note in caught.value.__notes__)


def test_sparse_packaging_uses_held_readonly_seed_not_descriptive_path(tmp_path, synthetic_seed):
    source, proof = synthetic_seed
    fd = os.open(source, os.O_RDONLY)
    try:
        result = sparse_seed.build(tmp_path / 'nonexistent-label.fat', tmp_path / 'packed', source_fd=fd)
    finally:
        os.close(fd)
    assert result['sha256'] == proof['sha256']
    assert not (tmp_path / 'nonexistent-label.fat').exists()


def test_sparse_packaging_rejects_writable_seed_fd(tmp_path, synthetic_seed):
    source, _ = synthetic_seed
    fd = os.open(source, os.O_RDWR)
    try:
        with pytest.raises(ValueError, match='0600 read-only input'):
            sparse_seed.build(source, tmp_path / 'packed', source_fd=fd)
    finally:
        os.close(fd)


def test_fsck_gate_uses_host_acceptance_and_environment_cannot_disable_it(monkeypatch):
    monkeypatch.setenv('A7C2_FSCK_EXECUTION_BLOCKED', '')
    assert ram._FSCK_EXECUTION_BLOCKED is None
    monkeypatch.setattr(ram, '_FSCK_EXECUTION_BLOCKED', 'synthetic closed gate')
    with mock.patch.object(ram.subprocess, 'Popen') as popen:
        with pytest.raises(ValueError, match='synthetic closed gate'):
            ram.fsck_readonly(-1, -1, -1, {})
        popen.assert_not_called()
    requirements = '\n'.join(ram.FSCK_UNBLOCK_REQUIREMENTS)
    for term in ('Independent owner', 'BaseException', 'Parent death/reload', 'root-owned',
                 'Two-thread'):
        assert term in requirements
    assert 'QEMU' not in requirements and 'guest' not in requirements
    handoff = '\n'.join(ram.RAM_CONSUMER_HANDOFF_REQUIREMENTS)
    assert 'Host fsck completes' in handoff and 'QEMU' in handoff
    assert 'guest whole-card SHA' not in handoff
    acceptance = '\n'.join(ram.RAM_GUEST_ACCEPTANCE_REQUIREMENTS)
    for term in ('handed-off FD lease', 'sealed memfd', 'guest whole-card SHA', 'Confirmed VM exit'):
        assert term in acceptance


@pytest.mark.parametrize('failure', [False, True])
def test_public_lease_keeps_producer_fds_and_preserves_consumer_error(
        tmp_path, synthetic_seed, monkeypatch, failure):
    source, _ = synthetic_seed
    native = tmp_path / 'product/runtime/analysis'
    native.mkdir(parents=True)
    card = native / 'source.fat'
    card.write_bytes(source.read_bytes())
    card.chmod(0o600)
    proof, _ = backup._bound_profile_input(card, expected_bytes=8192, single_link=True)
    monkeypatch.setattr(backup, '_RAM_DIRECTORY_CREATION_BLOCKED', None)
    monkeypatch.setattr(backup, 'validate_functional_camera_media',
                        lambda env: backup.FUNCTIONAL_CAMERA_RAM_MEDIA_CANDIDATE)

    def prepare(native_path, env, output_parent, *, _consumer_owner):
        # Synthetic producer exercises the real ownership transfer, never real build admission.
        with ExitStack() as producer_stack:
            output = backup._RamProfileOutput(producer_stack, output_parent)
            cloned, _ = output.copy_seed(proof, parallel_peak_bytes=0)
            output.publish('{"synthetic":true,"capture_verified":false}\n')
            return output.consumer_environment(output, {'A7C2_SD_IMAGE': cloned['path']}, _consumer_owner)

    monkeypatch.setattr(backup, 'prepare_profile', prepare)
    held = None
    try:
        with backup.ram_profile_lease(native, {'A7C2_SD_IMAGE': str(card)}, native / 'profiles',
                                     parallel_peak_bytes=0) as binding:
            held = binding
            assert binding['verify']()['host_fd_binding_verified'] is True
            for fd in binding['pass_fds']:
                os.fstat(fd)  # Producer's local ExitStack has already exited.
            if failure:
                binding['environment']['A7C2_SD_IMAGE'] = '/wrong/path.fat'
                raise KeyboardInterrupt('synthetic original consumer error')
    except KeyboardInterrupt as error:
        assert failure and str(error) == 'synthetic original consumer error'
        assert any('FD/environment handoff changed' in note for note in error.__notes__)
    else:
        assert not failure
    assert held is not None
    with pytest.raises(ValueError, match='closed or unbound'):
        held['verify']()
    for fd in held['pass_fds']:
        with pytest.raises(OSError):
            os.fstat(fd)


@pytest.mark.parametrize('index', [0, 1, 2])
@pytest.mark.parametrize('change', ['closed', 'different-inode', 'same-inode-new-ofd'])
@pytest.mark.parametrize('first_error', [False, True])
def test_cleanup_never_closes_unknown_public_fd_or_replaces_first_error(
        output, synthetic_seed, tmp_path, index, change, first_error):
    _, proof = synthetic_seed
    unrelated = tmp_path / 'unrelated.txt'
    unrelated.write_bytes(b'unrelated descriptor remains valid')
    replacement_fd = None
    original = KeyboardInterrupt('original consumer exception')
    # Open before invalidation so this unrelated FD cannot reuse the closed number.
    with unrelated.open('rb') as untouched:
        try:
            expected_error = KeyboardInterrupt if first_error else ValueError
            with pytest.raises(expected_error) as caught:
                with ExitStack() as consumer_stack:
                    owner, binding, cloned, _ = prepare_handoff(output, proof, consumer_stack)
                    fd = binding['pass_fds'][index]
                    anchors = [anchor for _, anchor, _ in owner.public_fds]
                    os.close(fd)
                    if change != 'closed':
                        source = (unrelated if change == 'different-inode' else
                                  (Path(cloned['path']), output.output,
                                   output.output / 'backup-profile.json')[index])
                        replacement_fd = os.open(source, os.O_RDONLY | os.O_NOFOLLOW)
                        if replacement_fd != fd:
                            os.dup2(replacement_fd, fd)
                            os.close(replacement_fd)
                            replacement_fd = fd
                    if first_error:
                        raise original
            if first_error:
                assert caught.value is original
                assert any('cleanup refused' in note for note in original.__notes__)
            else:
                assert 'cleanup refused' in str(caught.value)
            assert len(binding['cleanup_errors']) == 1
            assert f'public FD {fd} cleanup refused' in binding['cleanup_errors'][0]
            assert untouched.read() == b'unrelated descriptor remains valid'
            if replacement_fd is not None:
                os.fstat(replacement_fd)
                if change == 'different-inode':
                    assert os.read(replacement_fd, 100) == b'unrelated descriptor remains valid'
            else:
                with pytest.raises(OSError):
                    os.fstat(fd)
            for public in binding['pass_fds']:
                if public != fd:
                    with pytest.raises(OSError):
                        os.fstat(public)
            for anchor in anchors:
                with pytest.raises(OSError):
                    os.fstat(anchor)
        finally:
            # Replacements are owned by this test, never by the public lease.
            if replacement_fd is not None:
                os.close(replacement_fd)


def test_receipt_normal_read_after_handoff_returns_complete_receipt(output, synthetic_seed):
    _, proof = synthetic_seed
    with ExitStack() as consumer_stack:
        _, binding, _, _ = prepare_handoff(output, proof, consumer_stack)
        expected = (output.output / 'backup-profile.json').read_bytes()
        assert os.read(binding['receipt_fd'], len(expected) + 1) == expected


def test_verify_preserves_preset_receipt_offset(output, synthetic_seed):
    _, proof = synthetic_seed
    with ExitStack() as consumer_stack:
        owner, binding, _, _ = prepare_handoff(output, proof, consumer_stack)
        receipt = binding['receipt_fd']
        expected = (output.output / 'backup-profile.json').read_bytes()
        os.lseek(receipt, 3, os.SEEK_SET)
        assert owner.verify()['host_fd_binding_verified'] is True
        assert os.lseek(receipt, 0, os.SEEK_CUR) == 3
        assert os.read(receipt, len(expected)) == expected[3:]


def test_outer_except_cannot_swallow_successful_copy_storage_failure(
        output, synthetic_seed, monkeypatch):
    _, proof = synthetic_seed
    original_write = output.write

    def fail_storage(name, raw):
        if name == 'storage.json':
            raise OSError('successful copy receipt failure')
        return original_write(name, raw)

    monkeypatch.setattr(output, 'write', fail_storage)
    try:
        raise RuntimeError('unrelated caller exception')
    except RuntimeError as outer:
        with pytest.raises(OSError, match='successful copy receipt failure'):
            output.copy_seed(proof, parallel_peak_bytes=0)
        assert not getattr(outer, '__notes__', [])
    assert (output.output / 'media-camera.fat').is_file()
    assert (output.output / 'ram-card-sparse/manifest.json').is_file()


def test_no_parallel_budget_no_seed_creation(output, synthetic_seed):
    _, proof = synthetic_seed
    with pytest.raises(ValueError, match='declared parallel peak bytes'):
        output.copy_seed(proof)
    assert not list(output.output.iterdir())
