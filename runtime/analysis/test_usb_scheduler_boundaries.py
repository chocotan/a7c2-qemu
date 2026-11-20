"""Unexecuted host-only draft: synthetic bytes and fail-before-resource sentinels."""
import json
from pathlib import Path
import runpy
from types import SimpleNamespace

import pytest
from PIL import Image

import usb_msc
import usb_scheduler as scheduler
from sony_usb_device import PROFILE
from test_usb_scheduler import fake_transport


@pytest.mark.parametrize('fault', ['old-current', 'current-old', 'duplicate', 'malformed',
                                    'nonzero', 'embedded', 'unterminated', 'partial-prefix',
                                    'malformed-after-completion', 'filtered-line'])
@pytest.mark.parametrize('fragmented', [False, True])
def test_every_received_completion_is_checked_and_failure_is_sticky(fake_transport, fault, fragmented):
    process, serial, original = fake_transport
    def response(marker, _wire):
        good = b'\n'+marker+b':0\n'
        old = b'MSC_SCHED_DONE_old:0\n'
        variants = {
            'old-current': b'\n'+old+good,
            'current-old': good+old,
            'duplicate': good+good,
            'malformed': b'\n'+marker+b':0 extra\n',
            'nonzero': b'\n'+marker+b':1\n',
            'embedded': b'noise '+marker+b':0\n',
            'unterminated': b'\n'+marker+b':0',
            'partial-prefix': good+b'MSC_SCHED_',
            'malformed-after-completion': good+marker+b':',
            'filtered-line': good+b'[ 1.000] UDIF: '+old,
        }
        value = variants[fault]
        if not fragmented:
            return value
        # Keep the first complete record uncommitted while a later prefix is in flight.
        cut = value.find(b'MSC_SCHED_DONE_', len(good))
        cut = cut+8 if cut >= 0 else max(1, len(value)//2)
        return [value[:cut], value[cut:]]
    process.stdin.response = response
    with pytest.raises(scheduler.SerialBoundaryLost) as caught:
        serial('echo harmless')
    wire = process.stdin.getvalue()
    observed = serial.console.read_bytes()[len(original):]
    assert caught.value.raw == observed
    assert serial.poisoned and process._menu_serial_desynchronized and process._msc_scheduler_owner_required
    assert serial.console.read_bytes() == original+observed
    with pytest.raises(scheduler.SerialBoundaryLost, match='no further guest commands'):
        serial('echo must-never-be-sent')
    assert process.stdin.getvalue() == wire


def test_completion_does_not_hide_invalid_data_in_a_later_read_chunk(fake_transport):
    process, serial, original = fake_transport
    process.stdin.response = lambda marker, _wire: b'\n'+marker+b':0\n'+b'x'*65536+b'\nMSC_SCHED_DONE_old:0\n'
    with pytest.raises(scheduler.SerialBoundaryLost) as caught:
        serial('echo harmless')
    assert caught.value.raw.endswith(b'MSC_SCHED_DONE_old:0\n')
    assert len(caught.value.raw) > 65536
    assert serial.console.read_bytes() == original+caught.value.raw


@pytest.mark.parametrize('fragment', ['token', 'crlf', 'newline', 'echo'])
def test_complete_current_record_can_arrive_in_fragments(fake_transport, fragment):
    process, serial, original = fake_transport
    def response(marker, wire):
        if fragment == 'token':return [b'\n'+marker[:20], marker[20:]+b':0\n']
        if fragment == 'crlf':return [b'\r\n'+marker+b':0\r', b'\n']
        if fragment == 'newline':return [b'\n'+marker+b':0', b'\n']
        return [wire+b'\n'+marker[:20], marker[20:]+b':0\n']
    process.stdin.response = response
    raw = serial('echo harmless')
    assert raw.endswith(b':0\n') or raw.endswith(b':0\r\n')
    assert serial.console.read_bytes() == original+raw and not serial.poisoned


@pytest.mark.parametrize('suffix', [b'MSC_SCHED_DONE_', b'MSC_SCHED_DONE_a', b'MSC_SCHED_', b'noise'])
def test_valid_record_followed_by_unfinished_line_is_not_committed(fake_transport, suffix):
    process, serial, _original = fake_transport
    process.stdin.response = lambda marker, _wire: b'\n'+marker+b':0\n'+suffix
    with pytest.raises(scheduler.SerialBoundaryLost):
        serial('echo harmless')
    assert serial.poisoned


@pytest.fixture
def resource_sentinels(monkeypatch):
    import original_cold_boot as cold
    import persistent_storage as storage
    import subprocess
    import fcntl
    import os
    def forbidden(*_args, **_kwargs):
        pytest.fail('resource action before scheduler refusal')
    def install():
        monkeypatch.setattr(cold, 'product_input_bindings', forbidden)
        monkeypatch.setattr(storage, 'ensure_instance', forbidden)
        monkeypatch.setattr(storage, 'instance_lease', forbidden)
        monkeypatch.setattr(subprocess, 'Popen', forbidden)
        monkeypatch.setattr(subprocess, 'run', forbidden)
        monkeypatch.setattr(fcntl, 'flock', forbidden)
        monkeypatch.setattr(os, 'open', forbidden)
        monkeypatch.setattr(Path, 'mkdir', forbidden)
        monkeypatch.setattr(usb_msc, 'action', forbidden)
        monkeypatch.setattr(usb_msc, 'serial_command', forbidden)
    return install, forbidden


@pytest.mark.parametrize('entry', ['run', 'ram_roundtrip', 'cli', 'gui', 'prepare', 'probe'])
@pytest.mark.parametrize('value', ['1', '0', ''])
def test_explicit_request_refuses_before_storage_lease_compiler_or_cable(monkeypatch, tmp_path, resource_sentinels, entry, value):
    import original_cold_boot as cold
    import original_cold_live as gui
    api = runpy.run_path(str(Path(__file__).resolve().parents[2]/'tools/run-original-cold.py'))
    install, forbidden = resource_sentinels
    monkeypatch.setenv('A7C2_USB_MSC_SCHEDULER', value)
    monkeypatch.setenv('A7C2_USB_MSC', '1')
    monkeypatch.setenv('A7C2_SONY_USB_DEVICE', PROFILE)
    monkeypatch.delenv('A7C2_USB_SENSER', raising=False)
    monkeypatch.setattr(gui, 'validate_control', forbidden)
    monkeypatch.setitem(api['run'].__globals__, 'cold_environment', forbidden)
    monkeypatch.setitem(api['run'].__globals__, 'prepare', forbidden)
    calls = {
        'run': lambda: api['run'](object(), tmp_path/'run', 30),
        'ram_roundtrip': lambda: api['ram_roundtrip'](object(), tmp_path/'ram', 30),
        'cli': api['main'],
        'gui': gui.main,
        'prepare': lambda: cold.prepare(object(), tmp_path/'prepare', dict(__import__('os').environ)),
        'probe': lambda: usb_msc.probe(object(), tmp_path/'probe', forbidden, scheduler_contract={}),
    }
    install()
    with pytest.raises((RuntimeError, ValueError)):
        calls[entry]()
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize('entry', ['run', 'ram_roundtrip'])
def test_derived_environment_is_checked_even_when_raw_environment_is_clean(monkeypatch, tmp_path, resource_sentinels, entry):
    api = runpy.run_path(str(Path(__file__).resolve().parents[2]/'tools/run-original-cold.py'))
    for name in ('A7C2_USB_MSC_SCHEDULER', 'A7C2_SINGLE_AP_SOCKETS', 'A7C2_SINGLE_AP_SOCKET_ROOT'):
        monkeypatch.delenv(name, raising=False)
    profile = {'A7C2_USB_MSC_SCHEDULER': '1', 'A7C2_USB_MSC': '1', 'A7C2_SONY_USB_DEVICE': PROFILE}
    install, forbidden = resource_sentinels
    monkeypatch.setitem(api[entry].__globals__, 'cold_environment', lambda *_a: dict(profile))
    monkeypatch.setitem(api[entry].__globals__, 'prepare', forbidden)
    install()
    with pytest.raises(RuntimeError, match='persistent disk owner'):
        api[entry](object(), tmp_path/'derived', 30)
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize('failure', ['already-lost', 'initial-diagnostic', 'selection', 'enter', 'after-diagnostic', 'ee-snapshot'])
@pytest.mark.parametrize('save_failure', [False, True])
def test_shared_serial_loss_retains_usb_without_masking_original_error(monkeypatch, tmp_path, failure, save_failure):
    import ee_entry_snapshot
    process = SimpleNamespace(_menu_serial_desynchronized=failure == 'already-lost')
    original = RuntimeError('original shared serial failure')
    actions, after_loss_actions = [], []
    diagnostic_count = 0
    def lose():
        process._menu_serial_desynchronized = True
        raise original
    def action(_run, operation):
        actions.append(operation)
        if process._menu_serial_desynchronized:after_loss_actions.append(operation)
        return dict(cable_connected=True, host_enumerated=False)
    def serial(*_a, **_k):
        nonlocal diagnostic_count
        diagnostic_count += 1
        if failure == 'initial-diagnostic' or (failure == 'after-diagnostic' and diagnostic_count == 2):lose()
        return b'original diagnostic\n'
    def selection(*_a):
        if failure == 'selection':lose()
        return {'selected_pixels_sha256': '0'*64}
    def tap(*_a):
        if failure == 'enter':lose()
        return b'original ENTER', [1, 2]
    def qmp(_command, arguments):
        Image.new('RGB', (640, 480), (1, 2, 3)).save(tmp_path/Path(arguments['filename']).name)
    monkeypatch.setattr(usb_msc, 'action', action)
    monkeypatch.setattr(usb_msc, 'serial_command', serial)
    monkeypatch.setattr(usb_msc, '_select_msc', selection)
    monkeypatch.setattr(usb_msc, '_tap_original', tap)
    monkeypatch.setattr(usb_msc.time, 'sleep', lambda *_a: None)
    monkeypatch.setattr(ee_entry_snapshot, 'collect_passive', lambda *_a, **_k: lose())
    if save_failure:
        monkeypatch.setattr(usb_msc, '_save', lambda *_a: (_ for _ in ()).throw(OSError('receipt unavailable')))
    with pytest.raises(RuntimeError) as caught:
        usb_msc.probe(process, tmp_path, qmp)
    if failure != 'already-lost':assert caught.value is original
    assert not after_loss_actions and 'disconnect' not in actions
    if failure == 'already-lost':assert actions == []
    if save_failure:
        assert any('receipt unavailable' in note for note in caught.value.__notes__)
    else:
        result = json.loads((tmp_path/'usb-msc-result.json').read_text())
        assert result['usb_state_retained'] and result['disconnect_skipped'] == 'serial-boundary-lost'
        assert result['serial_boundary_lost'] and result['persistent_owner_required']
        assert result['exit_verified'] is False and result['phase'] == 'failed-preserved'
        assert 'disconnect' not in result and 'disconnect_error' not in result
        assert result['error'].endswith(str(caught.value))


@pytest.mark.parametrize('disconnect_fails', [False, True])
def test_ordinary_error_still_disconnects_and_keeps_primary_error(monkeypatch, tmp_path, disconnect_fails):
    actions = []
    def action(_run, operation):
        actions.append(operation)
        if operation == 'disconnect' and disconnect_fails:raise OSError('disconnect failed')
        return dict(cable_connected=False)
    monkeypatch.setattr(usb_msc, 'action', action)
    result = usb_msc.probe(SimpleNamespace(), tmp_path, lambda *_a: pytest.fail('no QMP'))
    assert actions == ['connect', 'disconnect']
    assert result['error'] == 'RuntimeError: Original AP MSC probe could not turn on the virtual cable'
    assert ('disconnect_error' in result) == disconnect_fails
    assert 'usb_state_retained' not in result
