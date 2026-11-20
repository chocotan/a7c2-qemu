"""UNEXECUTED fake-only draft; native/compile checks are in an explicit separate file."""
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest
import sony_usb_device as device
import usb_scheduler as scheduler
from test_usb_scheduler import sample, CONTRACT, HEAD


def test_group6_empty_head_and_group0_rejection():
    assert HEAD == 0x400000+0x910a778+0x10
    raw = sample()
    result = scheduler.parse(raw, 'before-enter', CONTRACT)
    assert result['scheduler_group'] == 6
    lines = raw.splitlines(keepends=True)
    index = next(i for i, line in enumerate(lines)
                 if line.startswith(b'SNAPSHOT_SCHED_HEADER_BYTES ') and b'offset=0 ' in line)
    prefix, value = lines[index].split(b'hex=')
    header = bytearray.fromhex(value.decode())
    header[8:12] = bytes(4)
    lines[index] = prefix+b'hex='+header.hex().encode()+b'\n'
    with pytest.raises(ValueError, match='0x90-byte header'):
        scheduler.parse(b''.join(lines), 'before-enter', CONTRACT)


def test_qmp_loss_sends_no_scheduler_command(tmp_path):
    process = SimpleNamespace(_menu_qmp_desynchronized=True)
    # No stdin or console exists: the boundary guard must reject before touching either.
    with pytest.raises(RuntimeError, match='QMP boundary already lost'):
        scheduler.SchedulerSerial(process, tmp_path/'absent')('never send')
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize('enabled', [False, True])
def test_observer_compiler_define_only_for_exclusive_opt_in(tmp_path, monkeypatch, enabled):
    calls = []
    environment = {'A7C2_SONY_USB_DEVICE': device.PROFILE, 'A7C2_USB_MSC': '1'}
    if enabled:
        environment['A7C2_USB_MSC_SCHEDULER'] = '1'
    monkeypatch.setattr(device, 'ee_normal_cold', lambda *_args: None)
    monkeypatch.setattr(device, 'sha', lambda _path: 'a'*64)
    monkeypatch.setattr(device, 'verify_private_libraries', lambda _inputs: None)
    @contextmanager
    def libraries(_inputs):
        yield [], ()
    @contextmanager
    def tool_environment(_inputs):
        yield {'TMPDIR': str(tmp_path)}, 123
    def compiler(command, **kwargs):
        calls.append(command)
        assert kwargs['env']['TMPDIR'] == str(tmp_path)
        assert kwargs['pass_fds'] == (123,)
        Path(command[command.index('-o')+1]).write_bytes(b'synthetic observer, never executed')
        return SimpleNamespace(returncode=0, stdout=b'fake compiler only\n', stderr=b'')
    monkeypatch.setattr(device, 'sealed_link_libraries', libraries)
    monkeypatch.setattr(device, 'private_tool_environment', tool_environment)
    monkeypatch.setattr(device.subprocess, 'run', compiler)
    result = device.prepare_observer(environment, tmp_path, private_inputs=('synthetic', {}))
    assert set(result) == {'usb-start-observe.so'} and len(calls) == 1
    assert ('-DUSB_MSC_SCHEDULER_OBSERVE=1' in calls[0]) == enabled
    assert '-DUSB_RESOURCE_OBSERVE=1' in calls[0]


@pytest.mark.parametrize('environment', [
    {'A7C2_USB_MSC_SCHEDULER': '1'},
    {'A7C2_USB_MSC_SCHEDULER': '0', 'A7C2_USB_MSC': '1', 'A7C2_SONY_USB_DEVICE': device.PROFILE},
    {'A7C2_USB_MSC_SCHEDULER': '1', 'A7C2_SONY_USB_DEVICE': device.PROFILE},
    {'A7C2_USB_MSC_SCHEDULER': '1', 'A7C2_USB_MSC': '1', 'A7C2_SONY_USB_DEVICE': device.PROFILE,
     'A7C2_USB_SENSER': 'original-init2-v1'},
])
def test_observer_rejects_nonexclusive_opt_in_before_preparation(tmp_path, monkeypatch, environment):
    monkeypatch.setattr(device, 'ee_normal_cold', lambda *_a: pytest.fail('no preparation'))
    monkeypatch.setattr(device.subprocess, 'run', lambda *_a, **_k: pytest.fail('no compiler'))
    with pytest.raises(ValueError):
        device.prepare_observer(environment, tmp_path)
    assert not list(tmp_path.iterdir())


def test_default_observer_stays_off_without_profile(tmp_path, monkeypatch):
    monkeypatch.setattr(device.subprocess, 'run', lambda *_a, **_k: pytest.fail('no compiler'))
    assert device.prepare_observer({}, tmp_path) == {}
    assert not list(tmp_path.iterdir())
