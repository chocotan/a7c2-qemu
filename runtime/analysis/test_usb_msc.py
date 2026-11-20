"""Host contract tests for the ordinary AP MSC driver; no USB/VM execution."""
import importlib.util
import json
from pathlib import Path
import runpy

import pytest
from PIL import Image, ImageDraw
import usb_msc


def test_msc_cold_environment_copies_only_explicit_usb_profile_and_proof(monkeypatch):
    api = runpy.run_path(str(Path(__file__).resolve().parents[2]/'tools/run-original-cold.py'))
    monkeypatch.delenv('A7C2_USB_EE_NORMAL_COLD', raising=False)
    monkeypatch.delenv('A7C2_USB_EE_NORMAL_COLD_INPUT', raising=False)
    monkeypatch.setenv('A7C2_SONY_USB_DEVICE', 'virtual-functional-sony-usb-device-v1')
    monkeypatch.setenv('A7C2_USB_DEVICE_BUILD', '/virtual/candidate.json')
    monkeypatch.setenv('A7C2_USB_SENSER', 'must-not-be-copied')
    environment={'A7C2_USB_EE_NORMAL_COLD':'1','A7C2_USB_EE_NORMAL_COLD_INPUT':'/old/header'}
    api['usb_msc_environment'](environment)
    assert environment == {'A7C2_USB_MSC': '1',
                           'A7C2_SONY_USB_DEVICE': 'virtual-functional-sony-usb-device-v1',
                           'A7C2_USB_DEVICE_BUILD': '/virtual/candidate.json'}
    monkeypatch.delenv('A7C2_USB_DEVICE_BUILD')
    with pytest.raises(ValueError, match='candidate receipt'):
        api['usb_msc_environment']({})


def test_msc_ee_cold_requires_explicit_profile_and_private_input(monkeypatch):
    api = runpy.run_path(str(Path(__file__).resolve().parents[2]/'tools/run-original-cold.py'))
    monkeypatch.setenv('A7C2_SONY_USB_DEVICE', 'virtual-functional-sony-usb-device-v1')
    monkeypatch.setenv('A7C2_USB_DEVICE_BUILD', '/virtual/candidate.json')
    monkeypatch.setenv('A7C2_USB_EE_NORMAL_COLD', '1')
    monkeypatch.delenv('A7C2_USB_EE_NORMAL_COLD_INPUT', raising=False)
    with pytest.raises(ValueError, match='profile 1 and private input'):
        api['usb_msc_environment']({})
    monkeypatch.setenv('A7C2_USB_EE_NORMAL_COLD_INPUT', '/private/prepared.h')
    environment = {}
    api['usb_msc_environment'](environment)
    assert environment['A7C2_USB_EE_NORMAL_COLD'] == '1'
    assert environment['A7C2_USB_EE_NORMAL_COLD_INPUT'] == '/private/prepared.h'
    monkeypatch.setenv('A7C2_USB_EE_NORMAL_COLD', '0')
    with pytest.raises(ValueError, match='profile 1 and private input'):
        api['usb_msc_environment']({})
    monkeypatch.delenv('A7C2_USB_EE_NORMAL_COLD')
    with pytest.raises(ValueError, match='profile 1 and private input'):
        api['usb_msc_environment']({})


def test_original_msc_progress_does_not_claim_storage_or_capture(tmp_path, monkeypatch):
    calls = []
    def action(_run, operation):
        calls.append(operation)
        if operation == 'disconnect':return {'phase': 'disconnected'}
        return {'phase': 'blocked', 'cable_connected': True,
                'host_enumerated': len(calls) > 1}
    after = (b'USB_START DSO_IDENTITY tid=123 path=/usr/lib/libInfraMscServer.so map=/usr/lib/libInfraMscServer.so base=0x1000 bytes=10 sha256=abc pid=123\n'
             b'USB_START MSC_DLOPEN_ENTER name=libInfraMscServer.so flags=0x1 passive=1\n'
             b'USB_START MSC_DLOPEN name=libInfraMscServer.so flags=0x1 handle=0x1 errno=0 passive=1\n'
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
        Image.new('RGB', (640, 480), (1, 2, 3)).save(tmp_path/Path(arguments['filename']).name)
    def tap(_run, _serial, key, _code):
        calls.append(key)
        return b'original enter edges\n', [1, 2]
    monkeypatch.setattr(usb_msc, 'action', action)
    monkeypatch.setattr(usb_msc, 'serial_command', serial)
    monkeypatch.setattr(usb_msc, '_select_msc', lambda *_args: {'selected_row': 1, 'selected_pixels_sha256': '0'*64})
    monkeypatch.setattr(usb_msc, '_tap_original', tap)
    monkeypatch.setattr(usb_msc.time, 'sleep', lambda _seconds: None)
    result = usb_msc.probe(object(), tmp_path, qmp)
    assert result['original_msc_dso_loaded'] and result['original_msc_server_consumed']
    assert len(result['msc_loader_events'])==2 and 'MSC_DLOPEN_ENTER' in result['msc_loader_events'][0]
    assert result['original_start_ioctl_zero'] and result['original_function_bound']
    assert result['host_enumerated'] and result['phase'] == 'original-msc-server-consumed'
    assert not result['msc_verified'] and not result['msc_storage_readback_verified'] and not result['capture_verified']
    assert not result['serial_boundary_lost'] and not result['qmp_boundary_lost']
    assert not result['usb_state_retained'] and not result['persistent_owner_required']
    assert result['disconnect_skipped'] is None and not result['exit_verified']
    assert calls[-1] == 'disconnect'
    assert json.loads((tmp_path/'usb-msc-result.json').read_text()) == result


def test_msc_missing_markers_are_unobserved_not_proven_absent(tmp_path,monkeypatch):
    import ee_entry_snapshot
    def action(_run,operation):
        return {'cable_connected':operation=='connect','host_enumerated':False}
    monkeypatch.setattr(usb_msc,'action',action)
    monkeypatch.setattr(usb_msc,'serial_command',lambda *_a,**_k:b'')
    monkeypatch.setattr(usb_msc,'_select_msc',lambda *_a:{'selected_pixels_sha256':'0'*64})
    monkeypatch.setattr(usb_msc,'_tap_original',lambda *_a:(b'', [1,2]))
    monkeypatch.setattr(usb_msc.time,'sleep',lambda _seconds:None)
    monkeypatch.setattr(ee_entry_snapshot,'collect_passive',lambda *_a,**_k: (_ for _ in ()).throw(ValueError('no snapshot')))
    def qmp(_command,arguments):
        Image.new('RGB',(640,480),(1,2,3)).save(tmp_path/Path(arguments['filename']).name)
    result=usb_msc.probe(object(),tmp_path,qmp)
    assert result['schema']=='a7c2-original-ap-usb-msc-probe-v4'
    assert result['phase']=='original-msc-submission-unobserved'
    assert result['msc_loader_absence_proven'] is False and result['msc_verified'] is False


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


def test_msc_serial_boundary_lost_retains_usb_and_original_error(tmp_path, monkeypatch):
    from types import SimpleNamespace
    process = SimpleNamespace(_menu_serial_desynchronized=False)
    calls = []
    original = RuntimeError('serial output boundary lost')

    def action(_run, operation):
        calls.append(operation)
        return {'cable_connected': True}

    def serial(*_args, **_kwargs):
        process._menu_serial_desynchronized = True
        raise original

    monkeypatch.setattr(usb_msc, 'action', action)
    monkeypatch.setattr(usb_msc, 'serial_command', serial)
    with pytest.raises(RuntimeError, match='^serial output boundary lost$') as captured:
        usb_msc.probe(process, tmp_path, lambda *_args: pytest.fail('no QMP'))
    assert captured.value is original
    assert calls == ['connect']
    result = json.loads((tmp_path/'usb-msc-result.json').read_text())
    assert result['schema'] == 'a7c2-original-ap-usb-msc-probe-v4'
    assert result['phase'] == 'failed-preserved'
    assert result['disconnect_skipped'] == 'serial-boundary-lost'
    assert result['usb_state_retained'] and result['persistent_owner_required']
    assert not result['exit_verified'] and not result['msc_verified']


def test_msc_already_desynchronized_sends_no_usb_actions(tmp_path, monkeypatch):
    from types import SimpleNamespace
    process = SimpleNamespace(_menu_serial_desynchronized=True)
    monkeypatch.setattr(usb_msc, 'action', lambda *_args: pytest.fail('no USB actions'))
    monkeypatch.setattr(usb_msc, 'serial_command', lambda *_args, **_kwargs: pytest.fail('no serial'))
    with pytest.raises(RuntimeError, match='^Serial boundary already lost; preserve USB state$'):
        usb_msc.probe(process, tmp_path, lambda *_args: pytest.fail('no QMP'))
    result = json.loads((tmp_path/'usb-msc-result.json').read_text())
    assert result['disconnect_skipped'] == 'serial-boundary-lost'


@pytest.mark.parametrize(('flag', 'reason'), [
    ('_menu_serial_desynchronized', 'serial-boundary-lost'),
    ('_menu_qmp_desynchronized', 'qmp-boundary-lost'),
])
def test_msc_ee_snapshot_boundary_loss_retains_usb(tmp_path, monkeypatch, flag, reason):
    from types import SimpleNamespace
    import ee_entry_snapshot
    process = SimpleNamespace(_menu_serial_desynchronized=False, _menu_qmp_desynchronized=False)
    calls = []
    original = RuntimeError('EE snapshot boundary lost')
    def action(_run, operation):
        calls.append(operation)
        return {'cable_connected': True, 'host_enumerated': False}
    def lost(*_args, **_kwargs):
        setattr(process, flag, True)
        raise original
    def qmp(_command, arguments):
        Image.new('RGB', (640, 480), (1, 2, 3)).save(tmp_path/Path(arguments['filename']).name)
    monkeypatch.setattr(usb_msc, 'action', action)
    monkeypatch.setattr(usb_msc, 'serial_command', lambda *_args, **_kwargs: b'diagnostic')
    monkeypatch.setattr(usb_msc, '_select_msc', lambda *_args: {'selected_pixels_sha256': '0'*64})
    monkeypatch.setattr(usb_msc, '_tap_original', lambda *_args: (b'enter', [1, 2]))
    monkeypatch.setattr(usb_msc.time, 'sleep', lambda _seconds: None)
    monkeypatch.setattr(ee_entry_snapshot, 'collect_passive', lost)
    with pytest.raises(RuntimeError, match='^EE snapshot boundary lost$') as captured:
        usb_msc.probe(process, tmp_path, qmp)
    assert captured.value is original
    assert calls == ['connect', 'connect']
    result = json.loads((tmp_path/'usb-msc-result.json').read_text())
    assert result['disconnect_skipped'] == reason
    assert result['ee_snapshot_error'] == 'RuntimeError: EE snapshot boundary lost'


@pytest.mark.parametrize('already_lost', [False, True])
def test_msc_qmp_boundary_lost_retains_usb(tmp_path, monkeypatch, already_lost):
    from types import SimpleNamespace
    process = SimpleNamespace(_menu_qmp_desynchronized=already_lost)
    calls = []
    original = RuntimeError('QMP transaction boundary lost')
    def action(_run, operation):
        calls.append(operation)
        return {'cable_connected': True}
    def qmp(*_args):
        process._menu_qmp_desynchronized = True
        raise original
    monkeypatch.setattr(usb_msc, 'action', action)
    monkeypatch.setattr(usb_msc, 'serial_command', lambda *_args, **_kwargs: b'diagnostic')
    if already_lost:
        with pytest.raises(RuntimeError, match='^QMP boundary already lost; preserve USB state$'):
            usb_msc.probe(process, tmp_path, qmp)
        assert calls == []
    else:
        with pytest.raises(RuntimeError, match='^QMP transaction boundary lost$') as captured:
            usb_msc.probe(process, tmp_path, qmp)
        assert captured.value is original
        assert calls == ['connect']
    result = json.loads((tmp_path/'usb-msc-result.json').read_text())
    assert result['qmp_boundary_lost'] and result['persistent_owner_required']
    assert result['disconnect_skipped'] == 'qmp-boundary-lost'
    assert result['usb_state_retained'] and not result['exit_verified']


def test_msc_result_save_failure_keeps_original_serial_error(tmp_path, monkeypatch):
    from types import SimpleNamespace
    process = SimpleNamespace(_menu_serial_desynchronized=False)
    original = RuntimeError('serial boundary lost')
    monkeypatch.setattr(usb_msc, 'action', lambda *_args: {'cable_connected': True})
    def serial(*_args, **_kwargs):
        process._menu_serial_desynchronized = True
        raise original
    monkeypatch.setattr(usb_msc, 'serial_command', serial)
    monkeypatch.setattr(usb_msc, '_save', lambda *_args: (_ for _ in ()).throw(OSError('save failed')))
    with pytest.raises(RuntimeError, match='^serial boundary lost\nMSC result preservation failed: OSError: save failed$') as captured:
        usb_msc.probe(process, tmp_path, lambda *_args: pytest.fail('no QMP'))
    assert captured.value is original
    assert any('save failed' in note for note in captured.value.__notes__)


def test_msc_both_boundaries_lost_are_recorded(tmp_path, monkeypatch):
    from types import SimpleNamespace
    process = SimpleNamespace(_menu_serial_desynchronized=True, _menu_qmp_desynchronized=True)
    monkeypatch.setattr(usb_msc, 'action', lambda *_args: pytest.fail('no USB actions'))
    with pytest.raises(RuntimeError, match='^Serial boundary already lost; preserve USB state$'):
        usb_msc.probe(process, tmp_path, lambda *_args: pytest.fail('no QMP'))
    result = json.loads((tmp_path/'usb-msc-result.json').read_text())
    assert result['serial_boundary_lost'] and result['qmp_boundary_lost']
    assert result['usb_state_retained'] and result['persistent_owner_required']
    assert result['disconnect_skipped'] == 'serial-boundary-lost'


def test_msc_result_save_failure_keeps_original_qmp_error(tmp_path, monkeypatch):
    from types import SimpleNamespace
    process = SimpleNamespace(_menu_qmp_desynchronized=False)
    original = RuntimeError('QMP transaction boundary lost')
    monkeypatch.setattr(usb_msc, 'action', lambda *_args: {'cable_connected': True})
    monkeypatch.setattr(usb_msc, 'serial_command', lambda *_args, **_kwargs: b'diagnostic')
    monkeypatch.setattr(usb_msc, '_save', lambda *_args: (_ for _ in ()).throw(OSError('save failed')))
    def qmp(*_args):
        process._menu_qmp_desynchronized = True
        raise original
    with pytest.raises(RuntimeError, match='^QMP transaction boundary lost\nMSC result preservation failed: OSError: save failed$') as captured:
        usb_msc.probe(process, tmp_path, qmp)
    assert captured.value is original
    assert any('save failed' in note for note in captured.value.__notes__)


def test_cold_launcher_records_msc_preservation_error_note(capsys):
    import ast
    path = Path(__file__).resolve().parents[2]/'tools/run-original-cold.py'
    tree = ast.parse(path.read_text())
    handlers = [handler for node in ast.walk(tree) if isinstance(node, ast.Try)
                for handler in node.handlers if handler.name == 'error' and
                any(isinstance(part, ast.Constant) and part.value == 'ORIGINAL_COLD_ERROR'
                    for part in ast.walk(handler))]
    assert len(handlers) == 1
    error = RuntimeError('serial boundary lost')
    error.add_note('MSC result preservation failed: OSError: save failed')
    scope = {'incoming': error, 'result': {'verified': True}}
    trial = ast.Try(body=[ast.Raise(exc=ast.Name(id='incoming', ctx=ast.Load()), cause=None)],
                    handlers=handlers, orelse=[], finalbody=[])
    exec(compile(ast.fix_missing_locations(ast.Module(body=[trial], type_ignores=[])), str(path), 'exec'), scope)
    assert scope['result']['verified'] is False
    assert scope['result']['error'] == ('RuntimeError: serial boundary lost\n'
                                        'MSC result preservation failed: OSError: save failed')
    assert scope['result']['error'] in capsys.readouterr().out


def test_guest_descriptors_reject_orphan_alternate_and_nested_configuration():
    from usb_control import usbip
    import struct
    metadata = {'busid': 'synthetic-1', 'busnum': 7, 'devnum': 9, 'speed': 3,
                'configuration_value': 1, 'descriptor_source': 'guest-ep0'}
    device = bytes.fromhex('120100020000004034127856000101020301')
    alternate_zero = bytes((9, 4, 0, 0, 0, 0xff, 0, 0, 0))
    msc_alternate = bytes((9, 4, 1, 1, 2, 8, 6, 0x50, 0))
    endpoints = (struct.pack('<BBBBHB', 7, 5, 0x01, 2, 512, 0) +
                 struct.pack('<BBBBHB', 7, 5, 0x81, 2, 512, 0))
    def descriptors(parts):
        config = struct.pack('<BBHBBBBB', 9, 2, 9+len(parts), 1, 1, 0, 0x80, 50)
        return device+config+parts
    with pytest.raises(usbip.ProtocolError, match='interface/endpoint count mismatch'):
        usbip.GuestDevice.parse(metadata, descriptors(alternate_zero+msc_alternate+endpoints))
    nested = struct.pack('<BBHBBBBB', 9, 2, 9, 1, 1, 0, 0x80, 50)
    with pytest.raises(usbip.ProtocolError, match='nested configuration'):
        usbip.GuestDevice.parse(metadata, descriptors(alternate_zero+nested))
    valid_alternate = bytes((9, 4, 0, 1, 2, 8, 6, 0x50, 0))
    usbip.GuestDevice.parse(metadata, descriptors(alternate_zero+valid_alternate+endpoints))


def test_selection_identifies_original_page_and_unambiguous_row():
    image = Image.new('RGB', (640, 480))
    ImageDraw.Draw(image).rectangle((80, 182, 559, 229), fill=(255, 0, 0))
    console = 'CREATE_SCREEN_ARGS call=1 id=0x25b count=1 \n'
    row, _ = usb_msc._selection_row(image, console)
    assert row == 1
    with pytest.raises(ValueError, match='page'):
        usb_msc._selection_row(image, console+'CREATE_SCREEN_ARGS call=2 id=0x30c count=1 \n')
    ImageDraw.Draw(image).rectangle((80, 112, 559, 159), fill=(255, 0, 0))
    with pytest.raises(ValueError, match='ambiguous'):
        usb_msc._selection_row(image, console)


def test_selection_sends_down_and_requires_original_edges(tmp_path):
    console = tmp_path/'console.log'
    console.write_text('CREATE_SCREEN_ARGS call=1 id=0x25b count=1 \n')
    frames = []
    for y in (112, 182):
        image = Image.new('RGB', (640, 480))
        ImageDraw.Draw(image).rectangle((80, y, 559, y+47), fill=(255, 0, 0))
        frames.append(image)
    calls = []
    def qmp(command, arguments):
        assert command == 'screendump'
        frames[min(len(calls), 1)].save(tmp_path/Path(arguments['filename']).name)
        calls.append(command)
    def serial(command):
        assert '/simulation/inject-key' in command
        with console.open('a') as stream:
            stream.write('INPUT_EVENT32 n=1 tid=3 words=[0x30,0,1,0,0,0,0,0]\n')
            stream.write('INPUT_EVENT32 n=2 tid=3 words=[0x30,0,0,0,0,0,0,0]\n')
    result = usb_msc._select_msc(tmp_path, qmp, serial)
    assert result['initial_row'] == 0 and result['selected_row'] == 1
    assert result['down_edges'] == [1, 2]
    assert result['before_pixels_sha256'] != result['selected_pixels_sha256']


def test_selection_keeps_already_selected_msc_row(tmp_path):
    (tmp_path/'console.log').write_text('CREATE_SCREEN_ARGS call=1 id=0x25b count=1 \n')
    image = Image.new('RGB', (640, 480))
    ImageDraw.Draw(image).rectangle((80, 182, 559, 229), fill=(255, 0, 0))
    def qmp(_command, arguments):
        image.save(tmp_path/Path(arguments['filename']).name)
    result = usb_msc._select_msc(tmp_path, qmp, lambda _command: pytest.fail('no DOWN expected'))
    assert result['initial_row'] == result['selected_row'] == 1
    assert result['down_edges'] == []


def test_original_tap_rejects_missing_input_edges(tmp_path, monkeypatch):
    (tmp_path/'console.log').write_text('')
    ticks = iter((0, 11))
    monkeypatch.setattr(usb_msc.time, 'monotonic', lambda: next(ticks))
    with pytest.raises(ValueError, match='press/release'):
        usb_msc._tap_original(tmp_path, lambda _command: b'OK', 'DOWN', 0x30)


def test_msc_refuses_unchanged_selection_after_down(tmp_path, monkeypatch):
    (tmp_path/'console.log').write_text('CREATE_SCREEN_ARGS call=1 id=0x25b count=1 \n')
    image = Image.new('RGB', (640, 480))
    ImageDraw.Draw(image).rectangle((80, 112, 559, 159), fill=(255, 0, 0))
    def qmp(_command, arguments):
        image.save(tmp_path/Path(arguments['filename']).name)
    monkeypatch.setattr(usb_msc, '_tap_original', lambda *_args: (b'', [1, 2]))
    ticks = iter((0, 0, 0, 20))
    monkeypatch.setattr(usb_msc.time, 'monotonic', lambda: next(ticks))
    monkeypatch.setattr(usb_msc.time, 'sleep', lambda _seconds: None)
    with pytest.raises(ValueError, match='did not become selected'):
        usb_msc._select_msc(tmp_path, qmp, lambda _command: b'')


def test_function_read_error_is_not_binding():
    errors, values = usb_msc.udc_functions(b'PRODUCT_USB_FIELD=function\ncat: cannot open function\n')
    assert values == [] and len(errors) == 1
    errors, values = usb_msc.udc_functions(b'PRODUCT_USB_FIELD=function\nMassStorage\n')
    assert (errors, values) == ([], ['MassStorage'])


def test_msc_imdb_restores_only_two_services(tmp_path):
    source = Path(__file__).with_name('prepare-assets.py')
    spec = importlib.util.spec_from_file_location('test_msc_assets', source)
    assets = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(assets)
    original = (Path(__file__).parent/'menu-root/usr/lib/libIMDB.so').read_bytes()
    variant = assets.usb_msc_imdb(original)
    assert assets.sha(variant) == assets.MSC_IMDB_SHA
    with pytest.raises(ValueError):
        assets.usb_msc_imdb(b'wrong')
    import original_cold_boot as cold
    helpers=cold.usb_imdb({'A7C2_USB_MSC':'1'},tmp_path)
    assert set(helpers)=={'libIMDB.so','libIMDB-msc.so'}
    assert helpers['libIMDB.so']==helpers['libIMDB-msc.so'] and helpers['libIMDB.so'].read_bytes()==variant
    assert cold.usb_imdb({},tmp_path)=={}
