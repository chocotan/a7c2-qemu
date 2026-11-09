"""Host contract tests for the ordinary AP MSC driver; no USB/VM execution."""
import importlib.util
import json
from pathlib import Path
import runpy

import pytest
import usb_msc


def test_msc_cold_environment_copies_only_explicit_usb_profile_and_proof(monkeypatch):
    api = runpy.run_path(str(Path(__file__).resolve().parents[2]/'tools/run-original-cold.py'))
    monkeypatch.setenv('A7C2_SONY_USB_DEVICE', 'virtual-functional-sony-usb-device-v1')
    monkeypatch.setenv('A7C2_USB_DEVICE_BUILD', '/virtual/candidate.json')
    monkeypatch.setenv('A7C2_USB_SENSER', 'must-not-be-copied')
    environment = {}
    api['usb_msc_environment'](environment)
    assert environment == {'A7C2_USB_MSC': '1',
                           'A7C2_SONY_USB_DEVICE': 'virtual-functional-sony-usb-device-v1',
                           'A7C2_USB_DEVICE_BUILD': '/virtual/candidate.json'}
    monkeypatch.delenv('A7C2_USB_DEVICE_BUILD')
    with pytest.raises(ValueError, match='candidate receipt'):
        api['usb_msc_environment']({})


def test_original_msc_progress_does_not_claim_storage_or_capture(tmp_path, monkeypatch):
    calls = []
    def action(_run, operation):
        calls.append(operation)
        if operation == 'disconnect':return {'phase': 'disconnected'}
        return {'phase': 'blocked', 'cable_connected': True,
                'host_enumerated': len(calls) > 1}
    after = (b'DSO_IDENTITY path=/usr/lib/libInfraMscServer.so\n'
             b'MSC_PROCESS_ENTER self=0x1\n'
             b'IOCTL_RETURN fd=3 req=0x4018e203 rc=0 errno=0\n'
             b'PRODUCT_USB_FIELD=function\nMassStorage\n')
    def serial(_process, _console, command, timeout):
        assert timeout == 30
        if 'PRODUCT_USB_STATUS_BEGIN' in command:
            return after if any(call == 'ENTER' for call in calls) else b'not loaded\n'
        calls.append('ENTER')
        return b'original enter edges\n'
    def qmp(command, arguments):
        assert command == 'screendump'
        (tmp_path/Path(arguments['filename']).name).write_bytes(b'PPM fixture')
    monkeypatch.setattr(usb_msc, 'action', action)
    monkeypatch.setattr(usb_msc, 'serial_command', serial)
    monkeypatch.setattr(usb_msc.time, 'sleep', lambda _seconds: None)
    result = usb_msc.probe(object(), tmp_path, qmp)
    assert result['original_msc_dso_loaded'] and result['original_msc_server_consumed']
    assert result['original_start_ioctl_zero'] and result['original_function_bound']
    assert result['host_enumerated'] and result['phase'] == 'original-msc-server-consumed'
    assert not result['msc_verified'] and not result['msc_storage_readback_verified'] and not result['capture_verified']
    assert calls[-1] == 'disconnect'
    assert json.loads((tmp_path/'usb-msc-result.json').read_text()) == result


def test_msc_without_cable_never_injects_or_claims_success(tmp_path, monkeypatch):
    calls = []
    def action(_run, operation):
        calls.append(operation)
        return {'phase': 'disconnected' if operation == 'disconnect' else 'blocked',
                'cable_connected': False}
    monkeypatch.setattr(usb_msc, 'action', action)
    monkeypatch.setattr(usb_msc, 'serial_command', lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError('no guest input')))
    result = usb_msc.probe(object(), tmp_path, lambda *_args: None)
    assert result['phase'] == 'failed-preserved' and not result['msc_verified']
    assert calls == ['connect', 'disconnect']
    assert not (tmp_path/'usb-msc-enter.raw').exists()


def test_function_read_error_is_not_binding():
    errors, values = usb_msc.udc_functions(b'PRODUCT_USB_FIELD=function\ncat: cannot open function\n')
    assert values == [] and len(errors) == 1
    errors, values = usb_msc.udc_functions(b'PRODUCT_USB_FIELD=function\nMassStorage\n')
    assert (errors, values) == ([], ['MassStorage'])


def test_msc_imdb_restores_only_two_services():
    source = Path(__file__).with_name('prepare-assets.py')
    spec = importlib.util.spec_from_file_location('test_msc_assets', source)
    assets = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(assets)
    original = (Path(__file__).parent/'menu-root/usr/lib/libIMDB.so').read_bytes()
    variant = assets.usb_msc_imdb(original)
    assert assets.sha(variant) == assets.MSC_IMDB_SHA
    with pytest.raises(ValueError):
        assets.usb_msc_imdb(b'wrong')
