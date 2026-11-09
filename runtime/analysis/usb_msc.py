"""Ordinary original-AP MSC selection probe; no synthetic START or storage reply."""
import hashlib
import json
from pathlib import Path
import re
import time

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


def probe(process, run, qmp):
    """Use the real cable and original ENTER; preserve failure and disconnect normally."""
    run = Path(run)
    result = dict(schema='a7c2-original-ap-usb-msc-probe-v1', msc_verified=False,
                  original_msc_dso_loaded=False, original_msc_server_consumed=False,
                  original_start_ioctl_zero=False, original_function_bound=False,
                  host_enumerated=False, msc_storage_readback_verified=False,
                  capture_verified=False, physical_devices_used=False)
    def serial(command):
        return serial_command(process, run/'console.log', command, timeout=30)
    try:
        result['initial_connect'] = action(run, 'connect')
        if not result['initial_connect'].get('cable_connected'):
            raise RuntimeError('Original AP MSC probe could not turn on the virtual cable')
        before = serial(guest_diagnostic())
        (run/'usb-msc-before.raw').write_bytes(before)
        result['before_sha256'] = hashlib.sha256(before).hexdigest()
        # This is the reviewed ordinary InfraInput ENTER route, not app32/Senser.
        entered = serial(key_command('ENTER', False))
        (run/'usb-msc-enter.raw').write_bytes(entered)
        result['enter_sha256'] = hashlib.sha256(entered).hexdigest()
        time.sleep(2)
        qmp('screendump', {'filename': '/out/usb-msc-selected.ppm'})
        after = serial(guest_diagnostic())
        (run/'usb-msc-after.raw').write_bytes(after)
        result['after_sha256'] = hashlib.sha256(after).hexdigest()
        result['original_msc_dso_loaded'] = b'DSO_IDENTITY path=/usr/lib/libInfraMscServer.so' in after
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
        result['phase'] = ('original-msc-server-consumed' if result['original_msc_server_consumed'] else
                           'original-msc-dso-loaded' if result['original_msc_dso_loaded'] else
                           'original-msc-not-submitted')
    except BaseException as error:
        result['error'] = type(error).__name__+': '+str(error)
        result['phase'] = 'failed-preserved'
    finally:
        try:
            result['disconnect'] = action(run, 'disconnect')
        except BaseException as error:
            result['disconnect_error'] = type(error).__name__+': '+str(error)
        _save(run, result)
    return result
