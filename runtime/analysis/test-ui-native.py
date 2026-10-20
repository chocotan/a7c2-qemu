#!/usr/bin/env python3
"""GTK host assertions on a private Xvfb. No VM is started, not even a mock VM."""
import os
import runpy
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
from unittest.mock import patch


def check():
    from menu_control import VM
    class ReachedStart(Exception):
        pass
    def stop_before_vm(self):
        raise ReachedStart()
    # The public CLI must leave controls inside QEMU, without a second GTK panel.
    with patch.object(sys, 'argv', ['menu-native.py', '--natural-boot', '--display', 'gtk']), \
         patch.object(VM, 'start', stop_before_vm):
        try:
            runpy.run_path(str(Path(__file__).with_name('menu-native.py')), run_name='__main__')
        except ReachedStart:
            pass
    import gi
    gi.require_version('Gtk','3.0')
    from gi.repository import Gtk
    created = Gtk.Window.list_toplevels()
    assert not created, 'Public launcher created a second window'
    for window in created:
        window.destroy()
    from menu_live import KEY_DEFINITIONS
    from menu_ui import NativeControls
    vm = VM(natural_boot=True)
    panel = NativeControls(vm)
    try:
        panel.pump()
        assert set(panel.buttons) == set(KEY_DEFINITIONS)
        assert panel.on.get_sensitive() and not panel.off.get_sensitive()
        assert not any(button.get_sensitive() for button in panel.buttons.values())
        with patch.object(vm, 'start') as start, patch.object(vm, 'stop') as stop:
            panel.on.clicked(); start.assert_called_once()
            vm.state = 'running'; panel.update(vm.status())
            panel.off.clicked(); stop.assert_called_once()
        assert panel.buttons['ENTER'].get_sensitive()
        for name in ('C1','EXPOSURE_COMP'):
            button = panel.buttons[name]
            assert not button.get_sensitive(), name
            assert '未验证' in button.get_label(), name
            assert '未验证' in button.get_tooltip_text(), name
        assert not panel.buttons['MODE'].get_sensitive()
        assert '新版单窗口' in panel.buttons['MODE'].get_tooltip_text()
        for name in ('AF_ON','FN','PLAYBACK','REC','SHUTTER','CONTROL_LEFT'):
            assert panel.buttons[name].get_sensitive(),name
            assert '未验证' in panel.buttons[name].get_label(),name
        panel.buttons['ENTER'].clicked()
        assert vm.commands.get_nowait() == {'action':'key', 'key':'ENTER'}
        vm.natural_boot = False; panel.update(vm.status()); panel.pump()
        assert panel.buttons['CONTROL_LEFT'].get_sensitive()
        panel.buttons['FRONT_RIGHT'].clicked()
        assert vm.commands.get_nowait() == {'action':'key', 'key':'FRONT_RIGHT'}
        panel.update(vm.status())
        box = panel.ring.get_allocation(); cx, cy = box.width / 2, box.height / 2
        assert panel._drag_start(panel.ring, SimpleNamespace(button=1, x=cx + 105, y=cy))
        panel._drag_move(panel.ring, SimpleNamespace(x=cx, y=cy + 105))
        panel._drag_end(panel.ring, SimpleNamespace(button=1))
        assert vm.commands.get_nowait() == {'action':'key', 'key':'CONTROL_RIGHT'}
        panel.update(vm.status())
        assert panel._drag_start(panel.ring, SimpleNamespace(button=1, x=cx + 105, y=cy))
        panel._drag_move(panel.ring, SimpleNamespace(x=cx, y=cy - 105))
        panel._drag_end(panel.ring, SimpleNamespace(button=1))
        assert vm.commands.get_nowait() == {'action':'key', 'key':'CONTROL_LEFT'}
        vm.state, vm.error = 'error', 'HOST ASSERTION: firmware unavailable'
        panel.update(vm.status())
        assert panel.error.get_visible() and 'HOST ASSERTION' in panel.error.get_text()
        assert not any(button.get_sensitive() for button in panel.buttons.values())
        assert panel.power_state.get_text() == 'error'
        vm.state = 'exited'; panel.update(vm.status())
        assert panel.power_state.get_text() == 'disconnected'
        assert panel.on.get_sensitive() and not panel.off.get_sensitive()
        assert vm.thread is None, 'Host assertions must never launch VM.start'
        print('UI_NATIVE_PASS: GTK construction, complete keys, availability, ON/OFF delegates, errors, bidirectional drag; no VM')
    finally:
        panel.window.destroy(); panel.pump()


if __name__ == '__main__':
    if '--inner' in sys.argv:
        check()
    else:
        with subprocess.Popen(['Xvfb', '-displayfd', '1', '-screen', '0', '2560x1440x24', '-nolisten', 'tcp'],
                              stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True) as display:
            try:
                number = display.stdout.readline().strip()
                if not number: raise RuntimeError('Private Xvfb did not supply a display')
                result = subprocess.run([sys.executable, str(Path(__file__).resolve()), '--inner'],
                                        env=dict(os.environ, DISPLAY=':' + number), timeout=20)
            finally:
                display.terminate(); display.wait(timeout=5)
        raise SystemExit(result.returncode)
