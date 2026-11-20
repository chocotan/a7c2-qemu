"""Host-only product protocol acceptance; real fsck uses an 8 MiB synthetic FAT."""
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import signal
import struct
import traceback

import pytest

import fsck_recovery as recovery
import functional_ram_initramfs as ram


def fat_image(corrupt=False):
    size, sectors = 8 * 1024**2, 64
    raw = bytearray(size)
    raw[:11] = b'\xeb\x3c\x90SYNTHFAT'
    struct.pack_into('<H', raw, 11, 512)
    raw[13] = 1
    struct.pack_into('<H', raw, 14, 1)
    raw[16] = 2
    struct.pack_into('<HH', raw, 17, 512, size // 512)
    raw[21] = 0xf8
    struct.pack_into('<HHH', raw, 22, sectors, 32, 64)
    raw[36], raw[38] = 0x80, 0x29
    struct.pack_into('<I', raw, 39, 0x73594e54)
    raw[43:54], raw[54:62] = b'NO NAME    ', b'FAT16   '
    raw[510:512] = b'\x55\xaa'
    for start in (512, (1 + sectors) * 512):
        struct.pack_into('<HH', raw, start, 0xfff8, 0xffff)
        if corrupt:
            struct.pack_into('<H', raw, start + 4, 0xffff)
    return bytes(raw)


@pytest.fixture
def case(tmp_path, monkeypatch):
    def forbidden(*args, **kwargs):
        raise ValueError('Signals are forbidden in fsck recovery acceptance')
    monkeypatch.setattr(os, 'kill', forbidden)
    monkeypatch.setattr(os, 'killpg', forbidden)
    monkeypatch.setattr(signal, 'pidfd_send_signal', forbidden)
    tmp_path.chmod(0o700)
    work = os.open(tmp_path, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
    try:
        yield tmp_path, work
    finally:
        os.close(work)


def wait_child(pid):
    while True:
        try:
            found, status = os.waitpid(pid, 0)
            assert found == pid and os.WIFEXITED(status)
            return os.WEXITSTATUS(status)
        except InterruptedError:
            continue


@pytest.mark.parametrize('corrupt', [False, True], ids=['valid', 'lost-cluster'])
def test_product_fsck_collects_real_status_and_readback(case, corrupt):
    root, work = case
    path = root / 'seed.fat'
    before = fat_image(corrupt)
    path.write_bytes(before)
    seed = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
    result = {'storage': {}}
    try:
        if corrupt:
            with pytest.raises(ValueError, match='Read-only fsck.fat failed'):
                ram.fsck_readonly(seed, work, work, result)
        else:
            ram.fsck_readonly(seed, work, work, result)
    finally:
        os.close(seed)
    envelope = json.loads((root / 'fsck-recovery.json').read_text())
    assert envelope['ok'] is (not corrupt)
    assert envelope['subreaper'] and envelope['handoff_acknowledged']
    assert envelope['zero_live_fsck_children'] and not envelope['caller_exited']
    assert envelope['child_wait']['wait_api'] == 'waitid(P_PIDFD, WEXITED)'
    assert envelope['child_wait']['si_code'] == os.CLD_EXITED
    assert envelope['child_wait']['returncode'] == (1 if corrupt else 0)
    assert result['fsck']['returncode'] == (1 if corrupt else 0)
    assert path.read_bytes() == before
    assert result['fsck']['executable']['sha256'] == result['fsck']['executable']['after_sha256']
    for name in ('fsck.stdout', 'fsck.stderr'):
        raw = (root / name).read_bytes()
        assert result['fsck'][name]['sha256'] == hashlib.sha256(raw).hexdigest()
    assert envelope['signals_sent'] == []


def test_product_recovery_finishes_after_caller_exits(case):
    root, work = case
    path = root / 'seed.fat'
    before = fat_image()
    path.write_bytes(before)
    seed = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
    supervisor = os.fork()
    if supervisor == 0:
        code = 125
        try:
            # Confine orphan adoption to this test-owned supervisor process.
            recovery._subreaper()
            owner = os.fork()
            if owner == 0:
                receive = recovery.receive_handle
                def die_after_handoff(channel):
                    handle, payload = receive(channel)
                    recovery.verify_identity(handle, payload['child'])
                    os._exit(0)  # Abrupt owner exit, no signals and no acknowledgement.
                recovery.receive_handle = die_after_handoff
                ram.fsck_readonly(seed, work, work, {'storage': {}})
                os._exit(126)
            assert wait_child(owner) == 0
            adopted = []
            while True:
                try:
                    pid, status = os.waitpid(-1, 0)
                    assert os.WIFEXITED(status)
                    adopted.append(dict(pid=pid, exitcode=os.WEXITSTATUS(status)))
                except InterruptedError:
                    continue
                except ChildProcessError:
                    break
            assert len(adopted) == 1 and adopted[0]['exitcode'] == 1
            ram.write_json(work, 'supervisor.json', dict(adopted=adopted, zero_live_children=True))
            code = 0
        except BaseException:
            os.write(2, traceback.format_exc().encode())
        os._exit(code)
    try:
        assert wait_child(supervisor) == 0
    finally:
        os.close(seed)
    envelope = json.loads((root / 'fsck-recovery.json').read_text())
    assert envelope['caller_exited'] and envelope['zero_live_fsck_children']
    assert envelope['child_wait']['si_code'] == os.CLD_EXITED
    assert envelope['child_wait']['returncode'] == 0
    assert envelope['result']['fsck']['returncode'] == 0
    assert envelope['first_error']['type'] == 'ValueError'
    assert 'acknowledge' in envelope['handoff_error']
    assert path.read_bytes() == before
    assert json.loads((root / 'supervisor.json').read_text())['zero_live_children']


def test_product_rejects_corrupt_handoff_and_still_collects_child(case, monkeypatch):
    root, work = case
    seed_path = root / 'seed.fat'
    seed_path.write_bytes(fat_image())
    seed = os.open(seed_path, os.O_RDONLY | os.O_CLOEXEC)
    receive = recovery.receive_handle
    def corrupt(channel):
        handle, payload = receive(channel)
        payload['child']['start_ticks'] += 1
        return handle, payload
    monkeypatch.setattr(recovery, 'receive_handle', corrupt)
    try:
        with pytest.raises(ValueError, match='generation mismatch'):
            ram.fsck_readonly(seed, work, work, {'storage': {}})
    finally:
        os.close(seed)
    envelope = json.loads((root / 'fsck-recovery.json').read_text())
    assert not envelope['ok'] and envelope['zero_live_fsck_children']
    assert envelope['child_wait']['returncode'] == 0
    assert 'handoff_error' in envelope


@pytest.mark.parametrize('kind', [OSError, KeyboardInterrupt])
def test_product_preserves_error_before_handoff(case, monkeypatch, kind):
    root, work = case
    seed_path = root / 'seed.fat'
    seed_path.write_bytes(fat_image())
    seed = os.open(seed_path, os.O_RDONLY | os.O_CLOEXEC)
    @contextmanager
    def failed_tool(proof):
        raise kind('original tool pin failure')
        yield  # pragma: no cover
    monkeypatch.setattr(ram, 'system_fsck', failed_tool)
    try:
        with pytest.raises(kind, match='original tool pin failure'):
            ram.fsck_readonly(seed, work, work, {'storage': {}})
    finally:
        os.close(seed)
    envelope = json.loads((root / 'fsck-recovery.json').read_text())
    assert envelope['first_error']['type'] == kind.__name__
    assert envelope['zero_live_fsck_children'] and 'child' not in envelope


@pytest.mark.parametrize('mode', ['pid-only', 'start-mismatch', 'boot-mismatch', 'wrong-pidfd'])
def test_product_identity_rejects_incomplete_or_stale_claim(case, mode):
    expected = recovery.process_identity(os.getpid())
    pidfd = os.pidfd_open(os.getpid(), 0)
    child = None
    try:
        if mode == 'pid-only':
            expected = dict(pid=expected['pid'])
        elif mode == 'start-mismatch':
            expected['start_ticks'] += 1
        elif mode == 'boot-mismatch':
            expected['boot_id'] = '00000000-0000-0000-0000-000000000000'
        else:
            child = os.fork()
            if child == 0:
                os._exit(0)
            expected = recovery.process_identity(child)
        with pytest.raises(ValueError):
            recovery.verify_identity(pidfd, expected)
    finally:
        if child is not None:
            assert wait_child(child) == 0
        os.close(pidfd)
