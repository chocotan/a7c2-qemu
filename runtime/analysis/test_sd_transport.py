import hashlib
import json
import os
from pathlib import Path
import subprocess
from types import SimpleNamespace

import pytest

import sd_transport as sd


HERE = Path(__file__).resolve().parent


@pytest.fixture(scope='session')
def fat(tmp_path_factory):
    image = tmp_path_factory.mktemp('fixture') / 'fat.img'
    with image.open('wb') as stream:
        stream.truncate(5 * 1024 * 1024)
    subprocess.run(['mkfs.fat', str(image)], check=True, capture_output=True)
    raw = image.read_bytes()
    assert raw[510:512] == b'\x55\xaa'
    return raw


class VM:
    def __init__(self, raw, mode=None):
        self.raw = raw
        self.mode = mode
        self.window = b''
        self.commands = []
        self.qmp_calls = []

    def serial(self, command):
        self.commands.append(command)
        words = command.split()
        assert words[0] == '/simulation/sd-window-export' and len(words) == 4
        offset, length, total = map(int, words[1:])
        assert total == len(self.raw) and 0 < length <= sd.CAP and offset+length <= total
        self.window = self.raw[offset:offset+length]
        inode = 7 + (self.mode == 'identity' and len(self.commands) > 1)
        mtime = '100.000000002' if not (self.mode == 'writing' and len(self.commands) > 1) else '100.000000003'
        if self.mode == 'error':
            return b'SD_EXPORT_ERROR rc=6\n'
        marker = (f'SD_EXPORT_READY offset={offset + (self.mode == "offset")} len={length} '
                  f'total={total} dev=1 inode={inode} mtime={mtime} '
                  f'ctime=101.000000003 fnv64={sd.fnv64(self.window)} rc=0\n').encode()
        return marker+marker if self.mode == 'duplicate' else marker

    def qmp(self, command):
        self.qmp_calls.append(command)
        assert command['execute'] == 'pmemsave'
        args = command['arguments']
        assert args['val'] == sd.PHYS and args['size'] == len(self.window)
        assert args['filename'].startswith(f'/proc/{os.getpid()}/fd/')
        if self.mode == 'qmp':
            return {'error': {'class': 'GenericError', 'desc': 'injected'}}
        raw = self.window
        if self.mode == 'truncate':
            raw = raw[:-1]
        if self.mode == 'hash':
            raw = bytes([raw[0] ^ 1])+raw[1:]
        Path(args['filename']).write_bytes(raw)
        return {'return': {}}


def run(tmp_path, raw, mode=None, **kwargs):
    vm = VM(raw, mode)
    result = sd.export_card(tmp_path, len(raw), serial_command=vm.serial, qmp=vm.qmp, **kwargs)
    assert json.loads((tmp_path / 'SD/export.json').read_text()) == result
    return result, vm


def test_core(tmp_path):
    binary = tmp_path / 'core'
    subprocess.run(['clang', '-std=c11', '-O2', '-Wall', '-Wextra', '-Werror',
                    str(HERE / 'test_sd_export_core.c'), '-o', str(binary)], check=True,
                   env={**os.environ, 'TMPDIR': str(tmp_path)})
    checked = subprocess.run([str(binary)], check=True, capture_output=True, text=True)
    assert 'PASS' in checked.stdout


def test_card_source_pins_regular_inode_and_rejects_changes(tmp_path):
    card=tmp_path/'card.img'
    with card.open('wb') as stream:stream.truncate(0x400000)
    with pytest.raises(ValueError,match='changed'):
        with sd.card_source(card) as fd:
            card.rename(tmp_path/'original.img');card.write_bytes(b'replacement')
            assert os.fstat(fd).st_size==0x400000
    with pytest.raises(ValueError,match='changed'):
        with sd.card_source(tmp_path/'original.img'):
            with (tmp_path/'original.img').open('r+b') as stream:stream.write(b'changed')


def test_card_source_rejects_symlink_ancestor_and_special_file(tmp_path):
    target=tmp_path/'secure';target.mkdir();(target/'card.img').write_bytes(b'bad size')
    alias=tmp_path/'alias';alias.symlink_to(target,target_is_directory=True)
    with pytest.raises(OSError):
        with sd.card_source(alias/'card.img'):pass
    special=tmp_path/'fifo';os.mkfifo(special)
    with pytest.raises(ValueError,match='regular'):
        with sd.card_source(special):pass
    with pytest.raises(ValueError,match='4 MiB'):
        with sd.card_source(target/'card.img'):pass


def test_guest_source_refuses_native_build(tmp_path):
    checked = subprocess.run(['clang', '-c', str(HERE / 'sd-window-export.c'), '-o', str(tmp_path/'bad.o')],
                             capture_output=True, text=True, env={**os.environ, 'TMPDIR': str(tmp_path)})
    assert checked.returncode and 'Guest only' in checked.stderr


def test_real_fat_multichunk(tmp_path, fat):
    result, vm = run(tmp_path, fat)
    assert result['ok'] and result['fsck_rc'] == 0
    assert result['sha256'] == hashlib.sha256(fat).hexdigest()
    assert (tmp_path/'SD/card.img').read_bytes() == fat
    assert len(vm.qmp_calls) == 2 and len(vm.commands) == 5
    assert len(result['chunks']) == 2
    assert (tmp_path/'SD'/result['evidence']/'fsck.txt').is_file()


def test_overall_success_waits_for_recovery_even_when_final_report_cannot_be_written(tmp_path,fat):
    from unittest.mock import patch
    from sd_export_lifecycle import export_with_flush_lifecycle
    vm=VM(fat)
    def export_once(barrier):
        return sd.export_card(tmp_path,len(fat),serial_command=vm.serial,qmp=vm.qmp,quiesce=barrier)
    def failed_publish(result):
        assert result['ok'] is False and result['export_data_ok'] is True
        assert result['card_published'] is True
        raise OSError('injected ENOSPC final report')
    with patch('sd_export_lifecycle.quiesce',return_value={'owner_stopped':True}),\
         patch('sd_export_lifecycle.cancel_resume',side_effect=RuntimeError('owner recovery failed')):
        with pytest.raises(OSError,match='ENOSPC'):
            export_with_flush_lifecycle(export_once,None,123,failed_publish)
    saved=json.loads((tmp_path/'SD/export.json').read_text())
    assert saved['ok'] is False and saved['export_data_ok'] is True
    assert saved['error']=='owner recovery pending'
    assert (tmp_path/'SD/card.img').read_bytes()==fat


def test_data_publication_is_remembered_despite_report_failure(tmp_path,fat,monkeypatch):
    original=sd.report;calls=[]
    def report(parent,result):
        calls.append(dict(result))
        if len(calls)==2:raise OSError('injected report failure after card publication')
        original(parent,result)
    monkeypatch.setattr(sd,'report',report)
    vm=VM(fat);result=sd.export_card(tmp_path,len(fat),serial_command=vm.serial,qmp=vm.qmp,quiesce=lambda:None)
    assert result['ok'] is False and result['card_published'] is True
    assert result['sha256']==hashlib.sha256(fat).hexdigest()
    assert json.loads((tmp_path/'SD/export.json').read_text())['ok'] is False
    monkeypatch.setattr(sd,'report',original)
    retry=sd.export_card(tmp_path,len(fat),serial_command=vm.serial,qmp=vm.qmp,expected_old_sha256=result['sha256'])
    assert retry['ok'] is True


@pytest.mark.parametrize('mode', ['offset', 'error', 'duplicate', 'truncate', 'hash', 'identity', 'writing', 'qmp'])
def test_failures_keep_evidence(tmp_path, fat, mode):
    result, _ = run(tmp_path, fat, mode)
    assert not result['ok'] and result['error']
    assert not (tmp_path/'SD/card.img').exists()
    evidence = tmp_path/'SD'/result['evidence']
    assert list(evidence.glob('serial-*.txt'))
    assert (evidence/'candidate.img').exists()


def test_invalid_fat(tmp_path):
    result, _ = run(tmp_path, b'\0'*1024)
    assert not result['ok'] and result['fsck_rc'] != 0
    assert not (tmp_path/'SD/card.img').exists()


def test_failure_replaces_old_success(tmp_path):
    (tmp_path/'SD').mkdir()
    (tmp_path/'SD/export.json').write_text('{"ok": true}')
    result, vm = run(tmp_path, b'\0'*1024, 'error')
    assert not result['ok'] and vm.commands
    assert json.loads((tmp_path/'SD/export.json').read_text())['ok'] is False


def test_quiesce_failure_invalidates_old_success_before_guest_io(tmp_path):
    (tmp_path/'SD').mkdir()
    (tmp_path/'SD/export.json').write_text('{"ok": true}')
    vm=VM(b'\0'*1024)
    def fail_flush():
        assert json.loads((tmp_path/'SD/export.json').read_text())['ok'] is False
        raise RuntimeError('original flush failed')
    result=sd.export_card(tmp_path,1024,serial_command=vm.serial,qmp=vm.qmp,quiesce=fail_flush)
    assert not result['ok'] and 'original flush failed' in result['error'] and not vm.commands
    assert json.loads((tmp_path/'SD/export.json').read_text())==result


def test_invalid_arguments_never_quiesce_guest(tmp_path):
    def unexpected():raise AssertionError('invalid request touched guest')
    result=sd.export_card(tmp_path,-1,serial_command=unexpected,qmp=unexpected,quiesce=unexpected)
    assert not result['ok'] and 'expected_total' in result['error']


def test_unknown_old_card(tmp_path):
    (tmp_path/'SD').mkdir()
    card = tmp_path/'SD/card.img'
    card.write_bytes(b'precious')
    result, vm = run(tmp_path, b'\0'*1024)
    assert not result['ok'] and 'unknown old card' in result['error']
    assert card.read_bytes() == b'precious' and not vm.commands


def test_expected_old_replace(tmp_path, fat):
    (tmp_path/'SD').mkdir()
    (tmp_path/'SD/card.img').write_bytes(b'old card')
    expected = hashlib.sha256(b'old card').hexdigest()
    result, _ = run(tmp_path, fat, expected_old_sha256=expected)
    assert result['ok'] and (tmp_path/'SD/card.img').read_bytes() == fat
    assert (tmp_path/'SD'/result['evidence']/'previous-card.img').read_bytes() == b'old card'


def test_bad_expected_old(tmp_path):
    (tmp_path/'SD').mkdir()
    (tmp_path/'SD/card.img').write_bytes(b'old card')
    result, vm = run(tmp_path, b'\0'*1024, expected_old_sha256='0'*64)
    assert not result['ok'] and not vm.commands
    assert (tmp_path/'SD/card.img').read_bytes() == b'old card'


def test_known_old_preserved_on_failure(tmp_path):
    (tmp_path/'SD').mkdir()
    (tmp_path/'SD/card.img').write_bytes(b'old card')
    (tmp_path/'SD/export.json').write_text('{"ok":true}')
    result, _ = run(tmp_path, b'\0'*1024, 'error',
                    expected_old_sha256=hashlib.sha256(b'old card').hexdigest())
    assert not result['ok']
    assert (tmp_path/'SD/card.img').read_bytes() == b'old card'


def test_fsck_timeout_evidence(tmp_path, monkeypatch):
    def timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired(args[0], 60, output=b'partial fsck output', stderr=b'err')
    monkeypatch.setattr(sd.subprocess, 'run', timeout)
    result, _ = run(tmp_path, b'\0'*1024)
    assert not result['ok'] and result['fsck_rc'] is None
    assert (tmp_path/'SD'/result['evidence']/'fsck.txt').read_bytes() == b'partial fsck outputerr'


def test_old_changes_before_publish(tmp_path, fat):
    (tmp_path/'SD').mkdir()
    (tmp_path/'SD/card.img').write_bytes(b'old card')
    expected = hashlib.sha256(b'old card').hexdigest()
    vm = VM(fat)
    def serial(command):
        if len(vm.commands) == 4:
            (tmp_path/'SD/card.img').write_bytes(b'changed card')
        return vm.serial(command)
    result = sd.export_card(tmp_path, len(fat), serial_command=serial, qmp=vm.qmp,
                            expected_old_sha256=expected)
    assert not result['ok'] and 'old card changed' in result['error']
    assert (tmp_path/'SD/card.img').read_bytes() == b'changed card'


def test_final_guest_identity_check(tmp_path, fat):
    vm = VM(fat)
    def serial(command):
        if len(vm.commands) == 4:
            vm.mode = 'writing'
        return vm.serial(command)
    result = sd.export_card(tmp_path, len(fat), serial_command=serial, qmp=vm.qmp)
    assert not result['ok'] and 'guest identity changed' in result['error']
    assert not (tmp_path/'SD/card.img').exists()


def test_guest_hash_changes_without_metadata_change(tmp_path):
    vm = VM(b'\0'*1024)
    def serial(command):
        if vm.commands:
            vm.raw = b'\1'*1024
        return vm.serial(command)
    result = sd.export_card(tmp_path, 1024, serial_command=serial, qmp=vm.qmp)
    assert not result['ok'] and 'guest bytes changed' in result['error']


def test_fnv_known_vector():
    assert sd.fnv64(b'') == 'cbf29ce484222325'
    assert sd.fnv64(b'hello') == 'a430d84680aabd0b'


def test_no_replace_on_publish_race(tmp_path, fat):
    vm = VM(fat)
    def serial(command):
        if len(vm.commands) == 4:
            (tmp_path/'SD/card.img').write_bytes(b'raced card')
        return vm.serial(command)
    result = sd.export_card(tmp_path, len(fat), serial_command=serial, qmp=vm.qmp)
    assert not result['ok'] and (tmp_path/'SD/card.img').read_bytes() == b'raced card'
    assert not json.loads((tmp_path/'SD/export.json').read_text())['ok']


@pytest.mark.parametrize('space', ['low', 'unknown', 'error'])
def test_space_refusal(tmp_path, monkeypatch, space):
    def stats(fd):
        if space == 'error':
            raise OSError('injected statvfs failure')
        return SimpleNamespace(f_bavail=0 if space == 'low' else 1000000,
                               f_frsize=4096 if space == 'low' else 0)
    monkeypatch.setattr(sd.os, 'fstatvfs', stats)
    result, vm = run(tmp_path, b'\0'*1024)
    assert not result['ok'] and not vm.commands
    assert not (tmp_path/'SD/card.img').exists()


@pytest.mark.parametrize('where', ['run', 'SD', 'card', 'report', 'fifo'])
def test_unsafe_paths(tmp_path, where):
    target = tmp_path/'target'
    target.mkdir()
    run_dir = tmp_path/'run'
    if where == 'run':
        run_dir.symlink_to(target, target_is_directory=True)
    else:
        run_dir.mkdir()
        if where == 'SD':
            (run_dir/'SD').symlink_to(target, target_is_directory=True)
        else:
            (run_dir/'SD').mkdir()
            name = 'export.json' if where == 'report' else 'card.img'
            if where == 'fifo':
                os.mkfifo(run_dir/'SD'/name)
            else:
                (run_dir/'SD'/name).symlink_to(target/'untouched')
    vm = VM(b'\0'*1024)
    result = sd.export_card(run_dir, 1024, serial_command=vm.serial, qmp=vm.qmp)
    assert not result['ok'] and not vm.commands
    assert not (target/'untouched').exists()


@pytest.mark.parametrize('total', [0, -512, 513, True, '1024', b'1024', 1 << 63])
def test_total_range(tmp_path, total):
    vm = VM(b'\0'*1024)
    result = sd.export_card(tmp_path, total, serial_command=vm.serial, qmp=vm.qmp)
    assert not result['ok'] and not vm.commands
    assert not json.loads((tmp_path/'SD/export.json').read_text())['ok']
