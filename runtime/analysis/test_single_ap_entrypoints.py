"""Host-only guards for the disabled single-AP socket profile."""
import ast
import os
from pathlib import Path
import runpy
import sys
from types import SimpleNamespace

import pytest

import menu_control
import menu_live
import single_ap_sockets as sockets


HERE=Path(__file__).resolve().parent
PRODUCT=HERE.parents[1]


@pytest.fixture
def selected(monkeypatch):
    monkeypatch.setenv(sockets.PROFILE_ENV,sockets.PROFILE)
    monkeypatch.setenv(sockets.ROOT_ENV,'/run/user/%d/not-allocated' % os.geteuid())
    for name in sockets.EXCLUDED_ROUTES:monkeypatch.delenv(name,raising=False)


def test_connector_default_and_fixed_gate(tmp_path,selected,monkeypatch):
    calls=[];peer=SimpleNamespace(connect=calls.append)
    with pytest.raises(RuntimeError,match='BLOCKED'):
        menu_live.connect_in_run(peer,tmp_path,'qmp.sock')
    assert not calls
    monkeypatch.delenv(sockets.PROFILE_ENV);monkeypatch.delenv(sockets.ROOT_ENV)
    menu_live.connect_in_run(peer,tmp_path,'qmp.sock')
    assert len(calls)==1 and calls[0].startswith('/proc/self/fd/') and calls[0].endswith('/qmp.sock')


def test_broken_binding_cannot_fall_back_to_legacy(tmp_path):
    (tmp_path/sockets.BINDING_NAME).symlink_to(tmp_path/'missing')
    calls=[];peer=SimpleNamespace(connect=calls.append)
    with pytest.raises(OSError):menu_live.connect_in_run(peer,tmp_path,'qmp.sock')
    assert not calls


def test_ui_start_rejects_before_instance_lease(selected):
    vm=menu_control.VM()
    vm.instance=SimpleNamespace(run_lease=lambda:pytest.fail('lease acquired'))
    with pytest.raises(RuntimeError,match='BLOCKED'):vm.start()
    assert vm.instance_lease is None and vm.thread is None


def test_ui_worker_rechecks_gate_before_socketpair(selected,monkeypatch):
    vm=menu_control.VM();released=[]
    vm.instance_lease=SimpleNamespace(__exit__=lambda *_:released.append(True))
    monkeypatch.setattr(menu_control.socket,'socketpair',lambda:pytest.fail('socketpair created'))
    vm._run()
    assert released==[True] and vm.instance_lease is None and vm.state=='error'
    assert 'BLOCKED' in vm.error and vm.owned_process is None


def test_cold_cli_rejects_before_open_or_instance_creation(selected,tmp_path,monkeypatch):
    target=PRODUCT/'tools/run-original-cold.py'
    scope=runpy.run_path(str(target))
    main=scope['main']
    calls=[]
    fake_os=SimpleNamespace(environ=os.environ,open=lambda *args,**kwargs:calls.append(args))
    monkeypatch.setitem(main.__globals__,'os',fake_os)
    monkeypatch.setattr(sys,'argv',[str(target),'--new-instance','--output',str(tmp_path/'output')])
    with pytest.raises(RuntimeError,match='BLOCKED'):main()
    assert not calls and not (tmp_path/'output').exists()


def test_shell_gates_precede_lock_and_qemu_resources():
    menu=(HERE/'run-menu-probe.sh').read_text()
    kernel=(HERE/'qemu-kernel-probe.sh').read_text()
    assert menu.index('single_ap_sockets.py')<menu.index('exec 9>>')
    assert kernel.index('single_ap_sockets.py')<kernel.index('mkdir -p "$output_dir"')
    assert "qemu_prefix=(/usr/bin/sh -c 'umask 0177; exec \"$@\"' sh)" in kernel
    assert '"${qemu_prefix[@]}" "/tools/$binary_relative"' in kernel
    assert 'runner=(exec)' in kernel and 'timeout --signal=TERM' not in kernel


def test_host_entry_registers_safe_single_ap_checks():
    tree=ast.parse((PRODUCT/'tools/test-host.py').read_text())
    assignment=next(node for node in tree.body if isinstance(node,ast.Assign) and
                    any(isinstance(target,ast.Name) and target.id=='FILES' for target in node.targets))
    names=ast.literal_eval(assignment.value.func.value).split()
    assert {'test_single_ap_sockets.py','test_diagnostic_fs_socket_roots.py',
            'test_single_ap_entrypoints.py','test_usb_short_sockets.py'}<=set(names)


def test_entrypoint_gates_are_before_startup_work():
    for file,marker in [('qemu-menu-probe.py','native_link_profile ='),
                        ('original_cold_live.py','validate_control(os.environ)'),
                        ('camera_ui.py','Gtk.init_check()'),
                        ('bodydata-launch.py','package = discover('),
                        ('start-menu.py',"for command in ('bash'"),
                        ('menu-native.py',"for command in ('bash'")]:
        text=(HERE/file).read_text()
        assert text.index('from single_ap_sockets import admit')<text.index(marker)
        ast.parse(text)
