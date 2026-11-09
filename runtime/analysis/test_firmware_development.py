import hashlib
import os
from pathlib import Path
import stat

import pytest
import firmware_development as development


def request(data=b'camera test'):
    return dict(action='firmware_readback',path='/usr/lib/appFw.so',bytes=len(data),sha256=hashlib.sha256(data).hexdigest())


def transcript(value):
    return ('Uid:\t0\t0\t0\t0\nGid:\t0\t0\t0\t0\nSHA256('+value['path']+')= '+value['sha256']+'\n'+str(value['bytes'])+'\n').encode()


def test_staged_copy_readback_mode_and_source_unchanged(tmp_path):
    source=tmp_path/'candidate.so';source.write_bytes(b'camera test');source.chmod(0o755)
    before=source.read_bytes();value=development.stage_file(tmp_path/'tests',source,'/usr/lib/appFw.so')
    staged=Path(value['overlay'])/'usr/lib/appFw.so'
    assert staged.read_bytes()==before==source.read_bytes()
    assert stat.S_IMODE(staged.stat().st_mode)==0o755
    assert value['sha256']==hashlib.sha256(before).hexdigest()
    assert value['staged_readback_verified'] and not value['guest_readback_verified']
    original=development.original_overlay(tmp_path/'tests')
    assert original.is_dir() and not list(original.iterdir()) and staged.exists()


@pytest.mark.parametrize('bad',['/usr/../etc/a','/usr//lib/a','usr/lib/a','/usr/lib/','/usr/lib/a;true','/proc/1/mem','/usr/lib/a\n'])
def test_unsafe_guest_destinations_refused(tmp_path,bad):
    source=tmp_path/'a';source.write_bytes(b'x')
    with pytest.raises(ValueError):development.stage_file(tmp_path/'tests',source,bad)
    assert not (tmp_path/'tests').exists()


def test_symlink_fifo_and_oversized_source_refused(tmp_path):
    source=tmp_path/'a';source.write_bytes(b'x');link=tmp_path/'link';link.symlink_to(source)
    fifo=tmp_path/'fifo';os.mkfifo(fifo)
    huge=tmp_path/'huge'
    with huge.open('wb') as stream:stream.truncate(development.MAX_FILE_BYTES+1)
    for path in (link,fifo,huge):
        with pytest.raises((ValueError,OSError)):development.stage_file(tmp_path/'tests',path,'/usr/lib/a')


def test_changed_source_never_admitted(tmp_path,monkeypatch):
    source=tmp_path/'a';source.write_bytes(b'123');copy=development._copy
    def changing(*args):
        copy(*args);source.write_bytes(b'456')
    monkeypatch.setattr(development,'_copy',changing)
    with pytest.raises(ValueError,match='变化'):development.stage_file(tmp_path/'tests',source,'/usr/lib/a')


def test_guest_permission_hash_and_length_all_required():
    value=request();raw=transcript(value)
    result=development.parse_readback(raw,value)
    assert result['guest_readback_verified'] and result['root_four_zero_fields']
    assert development.parse_readback(raw.replace(b'SHA256(',b'SHA2-256('),value)['guest_readback_verified']
    assert not development.parse_readback(raw+raw.replace(b'SHA256(',b'SHA2-256('),value)['guest_readback_verified']
    bads=[raw.replace(b'0\t0\t0\t0',b'0\t1\t0\t0'),raw+b'Uid:\t0\t0\t0\t0\n',
          raw.replace(value['sha256'].encode(),b'a'*64),raw.replace(b'\n11\n',b'\n12\n'),
          raw.replace(b'SHA256(',b'echo SHA256('),raw+b'11\n']
    for bad in bads:assert not development.parse_readback(bad,value)['guest_readback_verified']


def test_command_is_readonly_and_request_has_closed_fields():
    value=request();command=development.readback_command(value)
    assert '/usr/bin/openssl dgst -sha256 /usr/lib/appFw.so' in command
    assert '/proc/$$/status' in command and 'wc -c < /usr/lib/appFw.so' in command
    for bad in (dict(value,extra=True),dict(value,bytes=True),dict(value,sha256='g'*64),dict(value,path='/usr/a;echo secret')):
        with pytest.raises(ValueError):development.readback_command(bad)


def test_vm_selection_reuses_owner_gate_and_does_not_mutate_global_environment(tmp_path,monkeypatch):
    import menu_control
    monkeypatch.setattr(menu_control,'BASE',tmp_path)
    vm=menu_control.VM(natural_boot=True)
    source=tmp_path/'a';source.write_bytes(b'test')
    before=os.environ.get('A7C2_OVERWRITE_DIR')
    selected=vm.select_firmware_test(source,'/usr/lib/a')
    assert vm.status()['firmware_selection']==selected
    assert os.environ.get('A7C2_OVERWRITE_DIR')==before and vm.thread is None
    vm.state='running'
    with pytest.raises(ValueError,match='OFF'):vm.select_firmware_test()
    vm.state='disconnected';vm.select_firmware_test()
    assert vm.firmware_selection['original'] and not vm.firmware_verification
    assert vm.firmware_selection['restore_path']=='/usr/lib/a'
    vm.select_firmware_test(destination='/usr/bin/another')
    assert vm.firmware_selection['restore_path']=='/usr/bin/another'


def test_vm_guest_readback_queues_only_real_native_session(tmp_path,monkeypatch):
    import menu_control
    vm=menu_control.VM(natural_boot=True)
    vm.state='running';vm.firmware_selection=dict(guest_path='/usr/lib/a',bytes=4,sha256='a'*64)
    value=vm.check_firmware_test();assert vm.commands.get_nowait()==value
    vm.mock=True
    with pytest.raises(ValueError):vm.check_firmware_test()
