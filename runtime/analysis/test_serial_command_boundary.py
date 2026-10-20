from pathlib import Path
import subprocess
from types import SimpleNamespace

import pytest

import menu_live as live
from media_state_readback import CELLS, command, parse


def test_long_line_rejected_before_writing_even_cleanup(tmp_path):
    console = tmp_path/'console'
    console.write_bytes(b'')
    writes = []
    proc = SimpleNamespace(stdin=SimpleNamespace(write=writes.append, flush=lambda: None))
    with pytest.raises(ValueError, match='1000-byte'):
        live.serial_command(proc, console, 'x'*1001, allow_faulted_cleanup=True)
    assert not writes


def test_timeout_blocks_all_followups_including_cleanup(tmp_path):
    console = tmp_path/'console'
    console.write_bytes(b'')
    writes = []
    proc = SimpleNamespace(stdin=SimpleNamespace(write=writes.append, flush=lambda: None), poll=lambda: None)
    with pytest.raises(TimeoutError):
        live.serial_command(proc, console, 'true', timeout=0, allow_faulted_cleanup=True)
    assert len(writes) == 1 and proc._menu_serial_desynchronized
    with pytest.raises(RuntimeError, match='boundary lost'):
        live.serial_command(proc, console, 'cleanup must not be sent', allow_faulted_cleanup=True)
    assert len(writes) == 1


def test_multiline_actual_readback_finishes_each_field_and_real_sentinel(tmp_path):
    console = tmp_path/'console'
    console.write_bytes(b'')
    generated = command(b'OBS FRAME_DRAW_ENTER call=1 tid=302 x=1\n')
    # Host adapters only replace the guest mapping check and guest executable.
    generated = generated.replace('/bin/busybox grep -q /usr/lib/appFw.so /proc/302/maps', 'true')
    generated = generated.replace('/simulation/menu-readmem', 'echo HOST_READ_ONLY_STUB')
    writes = []

    def execute(wire):
        writes.append(wire)
        result = subprocess.run(['sh'], input=wire, capture_output=True, timeout=5)
        assert result.returncode == 0, result.stderr
        with console.open('ab') as stream:
            stream.write(result.stdout)

    proc = SimpleNamespace(stdin=SimpleNamespace(write=execute, flush=lambda: None), poll=lambda: None)
    data = live.serial_command(proc, console, generated, timeout=5, allow_faulted_cleanup=True)
    assert len(writes) == 1
    assert max(map(len, writes[0].splitlines())) < 200
    result = parse(data)
    assert len(result['reads']) == len(CELLS) == 8
    assert all(row['returncode'] == 0 for row in result['reads'])
    assert b'MENU_DIAG_COMMAND_DONE_' in data


def test_early_debug_readiness_requires_actual_model_commit(tmp_path, monkeypatch):
    console = tmp_path/'console'
    console.write_bytes(b'/ #\nOBS GUI_MODEL_COMMITTED packets=0 types=0\n')
    monkeypatch.setattr(live, 'FirmwareMonitor', lambda path: SimpleNamespace(check=lambda: None))
    calls = []
    def publish(delay):
        calls.append('wait')
        with console.open('ab') as stream:
            stream.write(b'OBS GUI_MODEL_COMMITTED packets=1 types=0x3f changed=1\n')
    monkeypatch.setattr(live.time, 'sleep', publish)
    live.wait_initial_model_commit(SimpleNamespace(poll=lambda: None), console, timeout=1)
    assert calls == ['wait']
    console.write_bytes(b'/ #\n')
    with pytest.raises(TimeoutError, match='publication missing'):
        live.wait_initial_model_commit(SimpleNamespace(poll=lambda: None), console, timeout=0)
