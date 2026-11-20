"""Ordinary original-AP MSC selection probe; no synthetic START or storage reply."""
import hashlib
import json
from pathlib import Path
import re
import time

from PIL import Image

from menu_live import key_command, serial_command
from sony_usb_device import guest_diagnostic
from usb_ui import action


def _save(run, result):
    (Path(run)/'usb-msc-result.json').write_text(json.dumps(result, indent=2, allow_nan=False)+'\n')


def udc_functions(diagnostic):
    raw = re.findall(rb'PRODUCT_USB_FIELD=function\r?\n([^\r\n]+)', diagnostic)
    errors = [value.decode(errors='replace') for value in raw if value.startswith(b'cat:')]
    values = [value.decode(errors='replace') for value in raw if not value.startswith(b'cat:')]
    return errors, values


def _selection_row(image, console):
    screens = re.findall(r'CREATE_SCREEN_ARGS call=\d+ id=(0x[0-9a-f]+|0) count=\d+ ', console)
    if not screens or int(screens[-1], 0) != 0x25b or image.size != (640, 480):
        raise ValueError('Original USB function selection page is not confirmed')
    rgb = image.convert('RGB')
    scores = [sum(r > 120 and r > 1.4*g and g >= 1.5*b
                  for r, g, b in rgb.crop((80, y, 560, y+48)).getdata())
              for y in (112, 182, 251, 320)]
    ordered = sorted(scores, reverse=True)
    if ordered[0] <= 10000 or ordered[0] <= 2*ordered[1]:
        raise ValueError('Original USB selection focus is ambiguous')
    return scores.index(ordered[0]), hashlib.sha256(rgb.tobytes()).hexdigest()


def _input_edges(console, code):
    pressed = None
    for number, words in re.findall(r'INPUT_EVENT32 n=(\d+) tid=\d+ words=\[([^]\r\n]+)\]', console):
        try:
            values = [int(word, 0) for word in words.split(',')]
        except ValueError:
            continue
        if values == [code, 0, 1, 0, 0, 0, 0, 0]:
            pressed = int(number)
        elif pressed is not None and values == [code, 0, 0, 0, 0, 0, 0, 0] and int(number) > pressed:
            return [pressed, int(number)]
    return []


def _tap_original(run, serial, key, code):
    console = run/'console.log'
    offset = console.stat().st_size
    raw_command = serial(key_command(key, False))
    deadline = time.monotonic()+10
    while time.monotonic() < deadline:
        raw = console.read_bytes()
        edges = _input_edges(raw[offset:].decode(errors='replace'), code) if len(raw) >= offset else []
        if edges:
            return raw_command, edges
        time.sleep(.1)
    raise ValueError('Original '+key+' press/release not observed')


def _select_msc(run, qmp, serial):
    console = run/'console.log'
    image_path = run/'usb-msc-selection.ppm'
    if image_path.exists() or image_path.is_symlink():
        raise ValueError('USB selection snapshot path already exists')

    def frame():
        qmp('screendump', {'filename': '/out/usb-msc-selection.ppm'})
        with Image.open(image_path) as image:
            return _selection_row(image, console.read_text(errors='replace'))

    deadline = time.monotonic()+30
    while True:
        try:
            row, before = frame()
            break
        except ValueError:
            if time.monotonic() >= deadline:
                raise
            time.sleep(.2)
    edges = []
    if row == 0:
        _, edges = _tap_original(run, serial, 'DOWN', 0x30)
        deadline = time.monotonic()+10
        while time.monotonic() < deadline:
            selected, after = frame()
            if selected == 1 and after != before:
                return dict(initial_row=row, selected_row=selected, down_edges=edges,
                            before_pixels_sha256=before, selected_pixels_sha256=after)
            time.sleep(.1)
        raise ValueError('MSC row did not become selected on a changed frame')
    if row != 1:
        raise ValueError('MSC selection would require unverified navigation')
    return dict(initial_row=row, selected_row=row, down_edges=[], selected_pixels_sha256=before)


def probe(process, run, qmp, *, scheduler_contract=None):
    """Use the real cable and original ENTER; preserve failure and disconnect normally."""
    if scheduler_contract is not None:
        from usb_scheduler import require_runtime_owner
        require_runtime_owner()
    run = Path(run)
    result = dict(schema='a7c2-original-ap-usb-msc-probe-v4', msc_verified=False,
                  original_msc_dso_loaded=False, original_msc_server_consumed=False,
                  original_start_ioctl_zero=False, original_function_bound=False,
                  host_enumerated=False, msc_storage_readback_verified=False,
                  capture_verified=False, physical_devices_used=False,
                  exit_verified=False, serial_boundary_lost=False, qmp_boundary_lost=False,
                  persistent_owner_required=False, usb_state_retained=False, disconnect_skipped=None)
    original_error = None
    def serial(command):
        if getattr(process, '_menu_serial_desynchronized', False):
            raise RuntimeError('Serial boundary already lost; preserve USB state')
        return serial_command(process, run/'console.log', command, timeout=30)
    try:
        if getattr(process, '_menu_serial_desynchronized', False):
            raise RuntimeError('Serial boundary already lost; preserve USB state')
        if getattr(process, '_menu_qmp_desynchronized', False):
            raise RuntimeError('QMP boundary already lost; preserve USB state')
        result['initial_connect'] = action(run, 'connect')
        if not result['initial_connect'].get('cable_connected'):
            raise RuntimeError('Original AP MSC probe could not turn on the virtual cable')
        before = serial(guest_diagnostic())
        (run/'usb-msc-before.raw').write_bytes(before)
        result['before_sha256'] = hashlib.sha256(before).hexdigest()
        result['selection'] = _select_msc(run, qmp, serial)
        if scheduler_contract is not None:
            result['scheduler_observation_status'] = 'unobserved'
            result['msc_submission_absence_proven'] = False
            from usb_scheduler import collect, SchedulerSerial
            scheduler_serial = SchedulerSerial(process, run/'console.log')
            result['scheduler_before'] = collect(scheduler_serial, run, 'before-enter', scheduler_contract)
        # This is the reviewed ordinary InfraInput ENTER route, not app32/Senser.
        entered, result['enter_edges'] = _tap_original(run, serial, 'ENTER', 0x1ac)
        (run/'usb-msc-enter.raw').write_bytes(entered)
        result['enter_sha256'] = hashlib.sha256(entered).hexdigest()
        if scheduler_contract is not None:
            result['scheduler_after'] = collect(scheduler_serial, run, 'after-enter', scheduler_contract,
                                                result['scheduler_before'])
            result['scheduler_observation_status'] = 'complete-read-only-samples'
        time.sleep(2)
        selected_path = run/'usb-msc-selected.ppm'
        if selected_path.exists() or selected_path.is_symlink():
            raise ValueError('MSC selected snapshot path already exists')
        qmp('screendump', {'filename': '/out/usb-msc-selected.ppm'})
        with Image.open(selected_path) as image:
            if image.size != (640, 480):
                raise ValueError('MSC selected snapshot geometry differs')
            selected_pixels = hashlib.sha256(image.convert('RGB').tobytes()).hexdigest()
        if selected_pixels == result['selection']['selected_pixels_sha256']:
            raise ValueError('MSC ENTER did not produce a changed current frame')
        result['after_enter_pixels_sha256'] = selected_pixels
        after = serial(guest_diagnostic())
        (run/'usb-msc-after.raw').write_bytes(after)
        result['after_sha256'] = hashlib.sha256(after).hexdigest()
        result['original_msc_dso_loaded'] = re.search(
            rb'(?m)^USB_START DSO_IDENTITY tid=[1-9][0-9]* path=/usr/lib/libInfraMscServer\.so(?:\s|$)', after) is not None
        result['msc_mapping_observed'] = re.search(
            rb'(?m)^[0-9a-f]+-[0-9a-f]+\s+[-rwxps]+\s+[^\r\n]*\s/usr/lib/libInfraMscServer\.so\r?$', after) is not None
        result['msc_loader_events'] = [line.decode('utf-8', 'replace') for line in after.splitlines()
                                       if line.startswith((b'USB_START MSC_DLOPEN ',
                                                           b'USB_START MSC_DLOPEN_ENTER '))][:32]
        result['msc_loader_absence_proven'] = False
        result['original_msc_server_consumed'] = any(token in after for token in (
            b'MSC_PROCESS_ENTER', b'MSC_CONFIGURE_ENTER', b'MSC_CONNECT_ENTER', b'MSC_LOWER_ENTER'))
        result['original_start_ioctl_zero'] = re.search(
            rb'IOCTL_RETURN[^\r\n]*req=0x4018e203[^\r\n]*rc=0(?:\s|$)', after) is not None
        errors, functions = udc_functions(after)
        result['udc_function_read_errors'] = errors
        result['udc_functions'] = functions
        result['original_function_bound'] = any(value not in ('', '(none)', 'not attached') for value in functions)
        # A second ordinary connect may attach only if the original function now provides descriptors.
        result['selected_connect'] = action(run, 'connect')
        result['host_enumerated'] = result['selected_connect'].get('host_enumerated') is True
        if not result['host_enumerated']:
            try:
                from ee_entry_snapshot import collect_group0, collect_passive
                snapshot = collect_passive(serial, run, common_only=True)
                result['ee_passive'] = snapshot
                result['ee_group0'] = collect_group0(serial, run, snapshot)
            except Exception as error:
                result['ee_snapshot_error'] = type(error).__name__+': '+str(error)
                if (getattr(process, '_menu_serial_desynchronized', False) or
                        getattr(process, '_menu_qmp_desynchronized', False)):
                    raise
        result['phase'] = ('original-msc-server-consumed' if result['original_msc_server_consumed'] else
                           'original-msc-dso-loaded' if result['original_msc_dso_loaded'] else
                           'original-msc-submission-unobserved')
    except BaseException as error:
        original_error = error
        result['error'] = type(error).__name__+': '+str(error)
        result['phase'] = 'failed-preserved'
        if (getattr(process, '_menu_serial_desynchronized', False) or
                getattr(process, '_menu_qmp_desynchronized', False)):
            raise
    finally:
        serial_lost = bool(getattr(process, '_menu_serial_desynchronized', False))
        qmp_lost = bool(getattr(process, '_menu_qmp_desynchronized', False))
        if serial_lost or qmp_lost:
            result.update(exit_verified=False, serial_boundary_lost=serial_lost, qmp_boundary_lost=qmp_lost,
                          persistent_owner_required=True, usb_state_retained=True,
                          disconnect_skipped='serial-boundary-lost' if serial_lost else 'qmp-boundary-lost')
        else:
            try:
                result['disconnect'] = action(run, 'disconnect')
            except BaseException as error:
                result['disconnect_error'] = type(error).__name__+': '+str(error)
        try:
            _save(run, result)
        except BaseException as error:
            if original_error is None or not (
                    getattr(process, '_menu_serial_desynchronized', False) or
                    getattr(process, '_menu_qmp_desynchronized', False)):
                raise
            original_error.add_note('MSC result preservation failed: '+type(error).__name__+': '+str(error))
    return result
