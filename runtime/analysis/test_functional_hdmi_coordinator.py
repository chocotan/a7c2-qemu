"""HDMI native-consumer handoff must precede the functional camera debugger."""
import json
from pathlib import Path
import sys
import threading
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import functional_camera_runner as runner
import hdmi_upm_watch

ANNOUNCEMENT = (b'OBS FULL_HDMI_UPM_MAILBOX_INIT pid=233 tid=374 user_va=0x7f80006000 '
    b'physical=0x51385d000 bytes=4096 nonce=0xbd1da1f9476b80c8 '
    b'upm_text=0xffffff800095e000 osal_text=0xffffff80004be000 version=1 record_bytes=256 '
    b'lease=4 U=0x7fb05062c0 index=0 raw=170192000000000000009a0000000000 '
    b'effective=170192000000000000009a0000000000\n')


def test_announcement_needs_complete_record_and_one_owner():
    assert runner.parse_hdmi_mailbox(ANNOUNCEMENT[:-1]) is None
    expected = runner.parse_hdmi_mailbox(ANNOUNCEMENT)
    assert runner.parse_hdmi_mailbox(ANNOUNCEMENT * 2) == expected
    assert expected['mailbox'] == dict(phys=0x51385d000, nonce=0xbd1da1f9476b80c8, pid=233)
    with pytest.raises(ValueError, match='owner changed'):
        runner.parse_hdmi_mailbox(ANNOUNCEMENT + ANNOUNCEMENT.replace(b'pid=233', b'pid=234'))
    with pytest.raises(ValueError, match='ABI'):
        runner.parse_hdmi_mailbox(ANNOUNCEMENT.replace(b'record_bytes=256', b'record_bytes=128'))


@pytest.fixture(autouse=True)
def private_run_root(tmp_path, monkeypatch):
    monkeypatch.setattr(runner.transport, 'RUNS', tmp_path.parent)


def instance(tmp_path):
    result = runner.FunctionalCameraRunner.__new__(runner.FunctionalCameraRunner)
    result.run = result.endpoint_root = tmp_path
    (tmp_path / runner.GDB).touch(mode=0o600)
    (tmp_path / 'console.log').write_bytes(ANNOUNCEMENT)
    result.owner = dict(pid=123)
    result.artifact = dict(library='unused')
    result.socket_options = {}
    result.model17c_startup = None
    result.hdmi_watch = result.hdmi_binding = result.hdmi_cleanup = None
    result.broker = result.thread = None
    result.binding = result.handoff = result.cleanup = result.startup_cleanup = None
    result.error = result.final_receipts = None
    result.done = threading.Event()
    result.closed = False
    result._check_owner = lambda: None
    result._publish = lambda phase: {'phase': phase, 'cleanup': result.cleanup}
    return result


def test_native_two_receipts_detach_before_camera_handoff(tmp_path, monkeypatch):
    owner = instance(tmp_path)
    events = []
    state = {'exit': None}
    cleanup = dict(safe_to_close=True, debugger_stopped=True, detached=True, errors=[])
    watcher = SimpleNamespace(process=SimpleNamespace(poll=lambda: state['exit']), stop=lambda: cleanup)
    monkeypatch.setattr(hdmi_upm_watch, 'start', lambda *args, **kwargs: events.append((args, kwargs)) or watcher)
    owner._observe_hdmi(ANNOUNCEMENT)
    assert len(events) == 1 and events[0][0][1] == 123
    assert events[0][0][3]['pid'] == 233
    owner._observe_hdmi(ANNOUNCEMENT)
    assert len(events) == 1 and owner.hdmi_cleanup is None
    (tmp_path / 'hdmi-upm-watch-result.json').write_text(json.dumps(dict(receipts=2, detached=True)))
    state['exit'] = 0
    owner._observe_hdmi(ANNOUNCEMENT)
    assert owner.hdmi_cleanup == cleanup
    assert json.loads((tmp_path / 'hdmi-upm-coordinator.json').read_text())['cleanup'] == cleanup


def test_early_debugger_exit_does_not_claim_native_completion(tmp_path, monkeypatch):
    owner = instance(tmp_path)
    cleanup = dict(safe_to_close=True, debugger_stopped=True, detached=True, errors=[])
    watcher = SimpleNamespace(process=SimpleNamespace(poll=lambda: 0), stop=lambda: cleanup)
    monkeypatch.setattr(hdmi_upm_watch, 'start', lambda *args, **kwargs: watcher)
    (tmp_path / 'hdmi-upm-watch-result.json').write_text(json.dumps(dict(receipts=0, detached=True)))
    with pytest.raises(ValueError, match='both original native lifetimes'):
        owner._observe_hdmi(ANNOUNCEMENT)
    assert owner.hdmi_cleanup['safe_to_close']


def test_unsafe_hdmi_debugger_prevents_vm_close(tmp_path):
    owner = instance(tmp_path)
    cleanup = dict(safe_to_close=False, debugger_stopped=False, detached=False, errors=['still attached'])
    owner.hdmi_watch = SimpleNamespace(stop=lambda: cleanup)
    with pytest.raises(runner.UnsafeCameraClose, match='cleanup unconfirmed'):
        owner.before_close('test-quit')
    assert not owner.closed and not owner.cleanup['safe_to_close']
    assert owner.hdmi_cleanup == cleanup


def test_disabled_hdmi_upm_observer_keeps_binding_without_attach(tmp_path, monkeypatch):
    owner = instance(tmp_path)
    calls = []
    monkeypatch.setattr(hdmi_upm_watch, 'start', lambda *args, **kwargs: calls.append((args, kwargs)))
    monkeypatch.setenv('A7C2_HDMI_UPM_DISABLE', '1')
    owner._observe_hdmi(ANNOUNCEMENT)
    assert owner.hdmi_binding['mailbox']['pid'] == 233
    assert owner.hdmi_watch is None and not calls


def test_existing_camera_debugger_cannot_be_stolen(tmp_path):
    owner = instance(tmp_path)
    owner.broker = object()
    with pytest.raises(ValueError, match='active camera debugger'):
        owner._observe_hdmi(ANNOUNCEMENT)
