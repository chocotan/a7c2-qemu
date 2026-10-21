"""Only the leased store may supply the controller's settings restore inputs."""
import pytest
import menu_control as control


@pytest.mark.parametrize('bound',[False,True])
def test_empty_instance_and_unbound_vm_scrub_stale_restore(tmp_path,monkeypatch,bound):
    directory=tmp_path/'instance';directory.mkdir(mode=0o700)
    vm=control.VM(instance=directory if bound else None,natural_boot=True)
    if bound:
        lease=vm.instance.run_lease();lease.__enter__();vm.instance_lease=lease
    monkeypatch.setattr(control,'BASE',tmp_path)
    monkeypatch.setenv('A7C2_SETTINGS_PERSIST','1')
    monkeypatch.setenv('A7C2_SETTINGS_RESTORE','/unrelated/generation/backup.bin')
    monkeypatch.setenv('A7C2_SETTINGS_RESTORE_SHA','0'*64)
    captured={}
    def no_child(command,**kwargs):
        captured.update(kwargs['env']);raise OSError('fixture: no actual child')
    monkeypatch.setattr(control.subprocess,'Popen',no_child)
    vm._run()
    assert captured.get('A7C2_SETTINGS_PERSIST')==('1' if bound else None)
    assert 'A7C2_SETTINGS_RESTORE' not in captured
    assert 'A7C2_SETTINGS_RESTORE_SHA' not in captured
    assert vm.instance_lease is None


def test_committed_generation_replaces_inherited_restore(tmp_path,monkeypatch):
    from pathlib import Path
    directory=tmp_path/'instance';directory.mkdir(mode=0o700)
    vm=control.VM(instance=directory,natural_boot=True)
    lease=vm.instance.run_lease();lease.__enter__();vm.instance_lease=lease
    monkeypatch.setattr(control,'BASE',tmp_path)
    monkeypatch.setenv('A7C2_SETTINGS_RESTORE','/unrelated/backup.bin')
    monkeypatch.setenv('A7C2_SETTINGS_RESTORE_SHA','0'*64)
    monkeypatch.setattr('settings_instance.load_for_boot',lambda token,firmware:{
        'state':'backup','generation':'b'*32,'sha256':'a'*64})
    captured={}
    def no_child(command,**kwargs):
        captured.update(kwargs['env']);raise OSError('fixture: no actual child')
    monkeypatch.setattr(control.subprocess,'Popen',no_child)
    vm._run()
    assert captured['A7C2_SETTINGS_RESTORE']==str(Path(directory)/('generation-'+'b'*32)/'backup.bin')
    assert captured['A7C2_SETTINGS_RESTORE_SHA']=='a'*64
    assert vm.instance_lease is None
