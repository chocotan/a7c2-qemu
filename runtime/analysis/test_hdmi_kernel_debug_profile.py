from pathlib import Path
import os
import subprocess

import pytest

HERE = Path(__file__).resolve().parent
PROFILE = 'virtual-pinmem-video0-hdmi-video0-initializing-v1'


@pytest.mark.parametrize('changes,accepted', [
    ({}, True),
    ({'QEMU_HDMI_UPM_GDB': '0'}, True),
    ({'QEMU_HDMI_UPM_GDB': '2'}, False),
    ({'MENU_PINMEM_HDMI_VIDEO_CONNECT': ''}, False),
    ({'MENU_PINMEM_HDMI_VIDEO_CONNECT': 'wrong'}, False),
    ({'QEMU_UI_LIVE': '0'}, False),
    ({'MENU_NATIVE_WINDOW': '0'}, False),
    ({'QEMU_REQUEST_QUEUE_GDB': '1'}, False),
])
def test_actual_shell_debug_channel_admission(tmp_path, changes, accepted):
    source = (HERE / 'qemu-kernel-probe.sh').read_text()
    end = source.index('if [[ "$native_window" == 1 ]]; then\n  display_args=')
    script = tmp_path / 'debug-gate.sh'
    script.write_text(source[:end] + '\ndeclare -p debug_args\n')
    env = {k: v for k, v in os.environ.items() if not k.startswith(('MENU_', 'QEMU_', 'SONY_'))}
    env.update(QEMU_HDMI_UPM_GDB='1', MENU_NATIVE_WINDOW='1', QEMU_UI_LIVE='1',
               MENU_PINMEM_HDMI_VIDEO_CONNECT=PROFILE)
    env.update(changes)
    result = subprocess.run(['bash', str(script)], env=env, capture_output=True, text=True, timeout=5)
    assert (result.returncode == 0) is accepted, result.stdout + result.stderr
    if accepted and env['QEMU_HDMI_UPM_GDB'] == '1':
        assert 'unix:/out/hdmi-upm-gdb.sock,server=on,wait=off' in result.stdout
        assert 'unix:/out/hdmi-upm-control.sock,server=on,wait=off' in result.stdout
        assert 'request-queue-' not in result.stdout and 'tcp:' not in result.stdout
    if accepted and env['QEMU_HDMI_UPM_GDB'] == '0':
        assert result.stdout.strip() == 'declare -a debug_args=()'
