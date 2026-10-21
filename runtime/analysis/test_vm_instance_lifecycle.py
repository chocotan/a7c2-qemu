"""VM ownership integration with host fixtures; no QEMU or guest configuration."""
import hashlib
from pathlib import Path
import subprocess

import pytest

from instance_lifecycle import Busy, Instance
import menu_control as control
import setting_store as store


class PausedThread:
    def __init__(self, **kwargs):
        self.target=kwargs['target']

    def start(self):
        pass

    def is_alive(self):
        return False


class Process:
    pid=524201

    def poll(self):
        return 0


@pytest.fixture
def vm(tmp_path):
    root=tmp_path/'instance';root.mkdir(mode=0o700)
    return control.VM(instance=root)


def acquire(vm):
    token=vm.instance.run_lease();token.__enter__();vm.instance_lease=token


def missing_group(*args):
    raise ProcessLookupError('fixture group has exited')


def test_start_acquires_before_thread_and_blocks_parallel_start_or_reset(vm,monkeypatch):
    monkeypatch.setattr(control.threading,'Thread',PausedThread)
    other=control.VM(instance=vm.instance.path)
    vm.start()
    try:
        assert vm.instance_lease.check() is vm.instance_lease
        with pytest.raises(Busy):other.start()
        with pytest.raises(ValueError,match='停止'):
            vm.reset_instance(None,confirmed=True)
        with pytest.raises(ValueError,match='生命周期'):
            vm.start()
    finally:
        vm._release_instance_lease()
    with other.instance.run_lease():pass


def test_failed_thread_start_releases_lease(vm,monkeypatch):
    class Failure(PausedThread):
        def start(self):raise RuntimeError('injected thread start failure')
    monkeypatch.setattr(control.threading,'Thread',Failure)
    with pytest.raises(RuntimeError,match='injected'):vm.start()
    assert vm.instance_lease is None and vm.state=='disconnected'
    with vm.instance.run_lease():pass


def test_failed_subprocess_start_releases_lease(vm,tmp_path,monkeypatch):
    acquire(vm)
    monkeypatch.setattr(control,'BASE',tmp_path)
    def fail(*args,**kwargs):raise OSError('injected Popen failure')
    monkeypatch.setattr(control.subprocess,'Popen',fail)
    vm._run()
    assert vm.state=='error' and vm.instance_lease is None and vm.owned_process is None
    with vm.instance.run_lease():pass


@pytest.mark.parametrize('failure',['termination','remaining-group'])
def test_failed_cleanup_keeps_exclusion_until_confirmed_retry(vm,tmp_path,monkeypatch,failure):
    acquire(vm);process=Process()
    monkeypatch.setattr(control,'BASE',tmp_path)
    monkeypatch.setattr(control.subprocess,'Popen',lambda *a,**kw:process)
    def bad_reply(*a,**kw):raise RuntimeError('injected control channel failure')
    monkeypatch.setattr(control,'receive_message',bad_reply)
    if failure=='termination':
        def fail(*a,**kw):raise subprocess.TimeoutExpired('owned fixture',3)
        monkeypatch.setattr(control,'terminate_owned',fail)
    else:
        monkeypatch.setattr(control,'terminate_owned',lambda _:None)
    monkeypatch.setattr(control.os,'killpg',lambda *a:None)
    vm._run()
    assert vm.cleanup_error and vm.instance_lease is not None and vm.owned_process is process
    with pytest.raises(Busy):
        with Instance(vm.instance.path).run_lease():pytest.fail('cleanup still owns instance')
    with pytest.raises(ValueError):vm.reset_instance(None,confirmed=True)
    monkeypatch.setattr(control,'terminate_owned',lambda _:None)
    monkeypatch.setattr(control.os,'killpg',missing_group)
    vm.close()
    assert vm.instance_lease is None and vm.owned_process is None and vm.state=='exited'
    with Instance(vm.instance.path).run_lease():pass


def test_successful_cleanup_releases_after_group_is_gone(vm,tmp_path,monkeypatch):
    acquire(vm);process=Process()
    monkeypatch.setattr(control,'BASE',tmp_path)
    monkeypatch.setattr(control.subprocess,'Popen',lambda *a,**kw:process)
    def reply(*a,**kw):raise RuntimeError('fixture stop before ready')
    monkeypatch.setattr(control,'receive_message',reply)
    def terminate(_):
        with pytest.raises(Busy):
            with Instance(vm.instance.path).run_lease():pytest.fail('released before termination')
    monkeypatch.setattr(control,'terminate_owned',terminate)
    monkeypatch.setattr(control.os,'killpg',missing_group)
    vm._run()
    assert not vm.cleanup_error and vm.instance_lease is None
    with vm.instance.run_lease():pass


def test_host_stopped_reset_preserves_sd_and_cas(vm):
    data=b'L'*store.BACKUP_SIZE;firmware='a'*64
    with vm.instance.run_lease() as token:
        previous=token.commit(data,firmware,None,guest_sha256=hashlib.sha256(data).hexdigest())
    root=Path(vm.instance.path);(root/'card.img').write_bytes(b'virtual SD retained')
    with pytest.raises(store.StoreError):vm.reset_instance(previous['generation'],confirmed=False)
    current=vm.reset_instance(previous['generation'],confirmed=True)
    assert current['state']=='reset' and current['data'] is None
    assert (root/'card.img').read_bytes()==b'virtual SD retained'
    with pytest.raises(store.Conflict):vm.reset_instance(previous['generation'],confirmed=True)


def test_unbound_controller_has_no_reset_interface():
    with pytest.raises(ValueError,match='未绑定'):
        control.VM().reset_instance(None,confirmed=True)
