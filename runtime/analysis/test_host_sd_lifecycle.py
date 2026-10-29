import fcntl
import os
import signal
import subprocess
from types import SimpleNamespace
from unittest.mock import patch
import pytest

from host_sd import card_lease
from menu_control import VM,terminate_host_disk_owner


def test_exited_leader_with_retained_disk_cannot_restart_or_release_lease(tmp_path):
    vm=VM()
    context=card_lease(tmp_path);vm.host_sd_lease=context.__enter__();vm.host_sd_context=context
    inherited=fcntl.fcntl(vm.host_sd_lease['fd'],fcntl.F_DUPFD_CLOEXEC,40)
    vm.host_sd_lease['inherited_fd']=inherited
    vm.owned_process=SimpleNamespace(pid=12345,poll=lambda:0)
    vm.cleanup_error='old process group still alive';vm.state='error'
    try:
        assert not vm.status()['can_start']
        with patch('menu_control.threading.Thread') as launch:
            with pytest.raises(ValueError,match='不得重启'):vm.start()
            launch.assert_not_called()
        assert vm.host_sd_context is context and vm.cleanup_error
        assert os.fstat(inherited).st_size==256000000000
        with pytest.raises(BlockingIOError):
            with card_lease(tmp_path):raise AssertionError('old lock lost')
        with patch('menu_control.os.killpg',return_value=None):
            with pytest.raises(RuntimeError,match='子进程仍运行'):
                vm._release_host_sd_lease(vm.owned_process)
        assert vm.host_sd_context is context
    finally:
        with patch('menu_control.os.killpg',side_effect=ProcessLookupError):
            vm._release_host_sd_lease(vm.owned_process)
    assert vm.host_sd_context is None
    with pytest.raises(OSError):os.fstat(inherited)
    with card_lease(tmp_path):pass


@pytest.mark.parametrize('cleanup_error',['unfinished cleanup',''])
def test_cleanup_guard_never_clears_retained_context(cleanup_error):
    vm=VM();vm.cleanup_error=cleanup_error
    if not cleanup_error:vm.host_sd_context=object()
    with pytest.raises(ValueError,match='不得重启'):vm.start()
    assert vm.cleanup_error==cleanup_error and not vm.status()['can_start']


def test_host_owner_timeout_sends_term_never_kill():
    process=SimpleNamespace(pid=12345,wait=lambda timeout:(_ for _ in ()).throw(
        subprocess.TimeoutExpired('owned process',timeout)))
    with patch('menu_control.os.killpg') as send:
        with pytest.raises(subprocess.TimeoutExpired):terminate_host_disk_owner(process)
    send.assert_called_once_with(process.pid,signal.SIGTERM)


def test_retry_cleanup_does_not_term_unflushed_live_host_disk():
    vm=VM();vm.host_sd_context=object();vm.cleanup_error='save failed'
    vm.owned_process=SimpleNamespace(pid=12345,poll=lambda:None)
    with patch('menu_control.terminate_host_disk_owner') as terminate:
        with pytest.raises(RuntimeError,match='保留VM与租约'):vm.close()
        terminate.assert_not_called()
    assert vm.host_sd_context is not None and vm.cleanup_error and not vm.cancel.is_set()
