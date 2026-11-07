#!/usr/bin/env python3
"""Probe original AP VBUS/UDC causality in one exclusively leased local VM.

Use an independent persistent instance. This owner never attaches/exports USB,
loads host modules, changes gadget sysfs or fabricates original AP events.
"""
import argparse
import asyncio
import hashlib
import json
import os
from pathlib import Path
import re
import runpy
import secrets
import select
import socket
import stat
import struct
import subprocess
import sys
import time

HERE = Path(__file__).resolve().parent
PERSISTENT = runpy.run_path(str(HERE / 'persistent-boot.py'))
USB = runpy.run_path(str(HERE / 'usb-device-profile.py'))
EXECUTOR_PATH = HERE / 'boot-execution.py'
EXECUTOR_SHA256 = hashlib.sha256(EXECUTOR_PATH.read_bytes()).hexdigest()
EXECUTOR = runpy.run_path(str(EXECUTOR_PATH))
if hashlib.sha256(EXECUTOR_PATH.read_bytes()).hexdigest() != EXECUTOR_SHA256:
    raise ValueError('Boot collector changed while loading; restart fresh probe')
sys.path.insert(0, str(HERE / 'usb-gadget'))
import usbip_server as protocol

PHASES = ('baseline', 'vbus_on', 'vbus_off')
MSC_PHASES = ('baseline', 'vbus_on', 'msc_selected', 'vbus_off')
FUNCTIONAL_MODE = 'ee-normal-wake-cold-functional-v1'
ZERO_MODE = 'ee-zero-publication-passive-v1'
REGISTERS = (0xf102e000, 0xf102e010, 0xf102e020, 0xf102e030,
             0xf102e040, 0xf1030000, 0xf1030010, 0xf1030020,
             0xf1030030)


def save(path, value):
    path = Path(path)
    temporary = path.with_name(path.name + '.' + secrets.token_hex(6) + '.new')
    with temporary.open('x') as stream:
        os.fchmod(stream.fileno(), 0o600)
        json.dump(value, stream, indent=2, sort_keys=True)
        stream.write('\n')
    temporary.replace(path)


def capture_script(phase, nonce, *, observe_start=False):
    if phase not in MSC_PHASES or not re.fullmatch('[0-9a-f]{24}', nonce):
        raise ValueError('Invalid probe phase/nonce')
    # Fixed quoted marker arguments prevent the shell echo from becoming evidence.
    script = '''echo 'USB_AP_BEGIN_@NONCE@_@PHASE@'
bb=/bin/busybox
$bb grep -E '^(Uid|Gid):' /proc/$$/status
echo USB_AP_INTERRUPTS
cat /proc/interrupts
echo USB_AP_GIC_ENABLE_BEGIN
$bb devmem 0x0800010c 32
echo USB_AP_GIC_ENABLE_RC=$?
echo USB_AP_MODULES
cat /proc/modules
for field in initstate refcnt coresize parameters/circuit_type parameters/buspw_ic_enable parameters/update_type; do
  echo USB_AP_MONITOR_FIELD=$field
  cat "/sys/module/usb_portMonitor/$field"
  echo USB_AP_MONITOR_RC=$?
done
for base in /sys/class/udc /sys/class/extcon /sys/class/android_usb /sys/kernel/config/usb_gadget /sys/bus/gadget/drivers /sys/bus/platform/drivers/g_android; do
  echo USB_AP_DIRECTORY=$base
  ls -la "$base"
  echo USB_AP_DIRECTORY_RC=$?
done
for p in /sys/class/udc/*; do
  [ -e "$p" ] || continue
  echo USB_AP_UDC=$p
  for field in state function uevent current_speed maximum_speed; do
    echo USB_AP_UDC_FIELD=$field
    cat "$p/$field"
    echo USB_AP_FIELD_RC=$?
  done
  echo USB_AP_UDC_CLASS_LINK
  $bb readlink "$p"
  echo USB_AP_UDC_CLASS_LINK_RC=$?
  ls -la "$p/device/driver" "$p/device/gadget" "$p/device/gadget/driver"
  echo USB_AP_GADGET_UEVENT
  cat "$p/device/gadget/uevent"
  echo USB_AP_GADGET_UEVENT_RC=$?
  echo USB_AP_GADGET_DRIVER
  $bb readlink "$p/device/gadget/driver"
  echo USB_AP_GADGET_DRIVER_RC=$?
done
echo USB_AP_SERVICE_POWER_CONTROL
cat /sys/devices/platform/soc/f1080000.usbs/f10c0000.usb/power/control
echo USB_AP_SERVICE_POWER_CONTROL_RC=$?
echo USB_AP_SERVICE_SYSFS_MOUNT
$bb grep -E '^[^ ]+ /sys sysfs [^ ]+ 0 0$' /proc/mounts
echo USB_AP_SERVICE_SYSFS_MOUNT_RC=$?
for p in /sys/class/extcon/*; do
  [ -e "$p" ] || continue
  echo USB_AP_EXTCON=$p
  cat "$p/name" "$p/state" "$p/uevent"
  echo USB_AP_EXTCON_RC=$?
done
for p in /proc/udm/fusb; do
  echo USB_AP_PROC=$p
  cat "$p"
  echo USB_AP_PROC_RC=$?
done
echo USB_AP_DEVICES
ls -l /dev/*usb* /dev/*USB* /dev/*otg* /dev/usb/*
echo USB_AP_DEVICE_RC=$?
echo USB_AP_OPEN_USB_FILES
for p in /proc/[0-9]*/fd/*; do
  target=$($bb readlink "$p")
  case "$target" in *usb*|*USB*|*otg*) echo USB_AP_FD=$p:$target;; esac
done
echo USB_AP_USB_CONTROL_MAPS
for p in /proc/[0-9]*/maps; do
  $bb grep -E 'lib(UsbControl|InfraUsbCmn|InfraMscServer)[.]so|usb-start-observe[.]so' "$p" && echo USB_AP_MAPS_PID=${p%/maps}
done
echo USB_AP_PROCESSES
ps
echo 'USB_AP_END_@NONCE@_@PHASE@'
'''.replace('@NONCE@', nonce).replace('@PHASE@', phase)
    if phase == 'msc_selected':
        # Original InfraInput ENTER contact, including its real 50ms release.
        keys = '''/simulation/inject-key 0x807a0020 0x92840747 0x1ac 0 1 0 1
pressed=$?
sleep 0.05
/simulation/inject-key 0x807a0020 0x92840747 0x1ac 0 0 0 1
released=$?
echo USB_AP_ENTER_PRESS_RC=$pressed
echo USB_AP_ENTER_RELEASE_RC=$released
sleep 2
'''
        if observe_start:
            snapshot = '''usb_sender_pid=
for p in /proc/[0-9]*; do
  if $bb grep -q /usr/lib/appFw.so "$p/maps"; then
    [ -z "$usb_sender_pid" ] || { echo USB_SENDER_AMBIGUOUS_PID; exit 79; }
    usb_sender_pid=${p##*/}
  fi
done
[ -n "$usb_sender_pid" ] || { echo USB_SENDER_MISSING_PID; exit 79; }
echo USB_SENDER_SNAPSHOT_BEFORE_BEGIN
/simulation/usb-sender-snapshot "$usb_sender_pid" before-enter
echo USB_SENDER_SNAPSHOT_BEFORE_RC=$?
echo USB_SENDER_SNAPSHOT_BEFORE_END
'''
            keys = snapshot + keys + '''echo USB_SENDER_SNAPSHOT_AFTER_BEGIN
/simulation/usb-sender-snapshot "$usb_sender_pid" after-enter
echo USB_SENDER_SNAPSHOT_AFTER_RC=$?
echo USB_SENDER_SNAPSHOT_AFTER_END
'''
        script = script.replace('bb=/bin/busybox\n', 'bb=/bin/busybox\n' + keys, 1)
    if phase == 'baseline':
        identity = '''echo COLD_KERNEL_CMDLINE_BEGIN
cat /proc/cmdline
echo COLD_KERNEL_CMDLINE_END
for p in /proc/[0-9]*; do
  e=$($bb readlink "$p/exe")
  case "$e" in
    /usr/bin/im.elf)
      echo COLD_EXECUTABLE=$e
      if $bb grep -q /usr/lib/appFw.so "$p/maps"; then
        echo COLD_AP_MAPS_BEGIN pid=${p##*/}
        cat "$p/maps"
        echo COLD_AP_MAPS_END pid=${p##*/}
        app_sha=$(/usr/bin/openssl dgst -sha256 /usr/lib/appFw.so)
        echo "$app_sha"
        case "$app_sha" in
          *"= @AP_SHA@") echo COLD_AP_MAP pid=${p##*/} sha256=@AP_SHA@;;
        esac
      fi;;
  esac
done
'''.replace('@AP_SHA@', EXECUTOR['APPFW_SHA256'])
        script = script.replace('echo USB_AP_INTERRUPTS\n', identity + 'echo USB_AP_INTERRUPTS\n', 1)
    if observe_start:
        observations = '''echo USB_AP_START_TRACE_SHA_BEFORE
/usr/bin/openssl dgst -sha256 /dev/qemu-simulation/usb-start-observe.log
echo USB_AP_START_TRACE_SHA_BEFORE_RC=$?
echo USB_AP_START_TRACE_BEGIN
cat /dev/qemu-simulation/usb-start-observe.log
echo USB_AP_START_TRACE_RC=$?
echo USB_AP_START_TRACE_END
echo USB_AP_START_TRACE_SHA_AFTER
/usr/bin/openssl dgst -sha256 /dev/qemu-simulation/usb-start-observe.log
echo USB_AP_START_TRACE_SHA_AFTER_RC=$?
echo USB_AP_REAL_USB_NODES
ls -l /dev/usb/sen /dev/usb/ter /dev/usb/gadgetcore /dev/usb/scsi
for p in /sys/dev/char/242:1 /sys/dev/char/242:4 /sys/dev/char/248:4 /sys/dev/char/248:5; do
  echo USB_AP_REAL_CHAR=$p
  $bb readlink "$p"
  cat "$p/uevent"
done
echo USB_AP_DEV_MOUNT
$bb grep -E '^[^ ]+ /dev devtmpfs [^ ]+ 0 0$' /proc/mounts
'''
        if phase == 'msc_selected':
            observations += '''echo USB_AP_WAITERS_BEGIN
for p in /proc/[0-9]*; do
  $bb grep -q /usr/lib/libUsbControl.so "$p/maps" || continue
  echo USB_AP_WAIT_PID=${p##*/}
  n=0
  for t in "$p"/task/*; do
    n=$((n+1))
    [ "$n" -le 160 ] || break
    echo USB_AP_WAIT_TID=${t##*/}
    cat "$t/comm" "$t/wchan" "$t/stack"
  done
done
echo USB_AP_WAITERS_END
'''
        script = script.replace("echo 'USB_AP_END_", observations + "echo 'USB_AP_END_", 1)
    return script


def capture_failure_observer(owner, console, output):
    result = {'diagnostic_only': True, 'received': False, 'budget_seconds': 5,
              'diagnostic_skipped_monitor': False}
    try:
        returncode = owner.poll() if owner is not None else None
        result['owner_state'] = dict(pid=getattr(owner, 'pid', None), returncode=returncode,
                                    process_still_running=owner is not None and returncode is None)
        data = console.read_bytes()
        result.update(console_sha256=hashlib.sha256(data).hexdigest(), console_bytes=len(data))
        positions = [(data.find(marker), marker) for marker in (b'Entering exception monitor', b'Exception>')]
        positions = [(offset, marker) for offset, marker in positions if offset >= 0]
        if positions:
            offset, marker = min(positions)
            result.update(diagnostic_skipped_monitor=True,
                          first_monitor=dict(marker=marker.decode('ascii'), byte_offset=offset,
                                             line=data.count(b'\n', 0, offset) + 1),
                          capture_error='Sony exception monitor; Linux shell diagnostic skipped')
            save(output / 'observer-failure-skipped-monitor.json', result)
            return result
        if not result['owner_state']['process_still_running']:
            return result
        nonce = secrets.token_hex(12)
        script = capture_script('baseline', nonce, observe_start=True)
        wire = EXECUTOR['diagnostic_envelope'](script, 'USB_FAILURE_' + nonce)
        EXECUTOR['write_console'](owner.stdin, wire.encode('ascii'))
        deadline = time.monotonic() + 5
        while owner.poll() is None and time.monotonic() < deadline:
            raw = phase_bytes(console.read_bytes(), 'baseline', nonce)
            if raw is not None:
                path = output / 'observer-failure.log'
                with path.open('xb') as stream:
                    os.fchmod(stream.fileno(), 0o600)
                    stream.write(raw)
                    stream.flush()
                    os.fsync(stream.fileno())
                result.update(received=True, path=str(path), bytes=len(raw),
                              sha256=hashlib.sha256(raw).hexdigest())
                return result
            time.sleep(.05)
        result['capture_error'] = 'Owner exited or failure diagnostic deadline reached'
    except Exception as error:
        result['capture_error'] = type(error).__name__ + ': ' + str(error)
    return result


def classify_usb_message(source, size, raw):
    """Classify exact known wire shapes; length alone never identifies an EE reply."""
    if type(source) is not int or type(size) is not int or not isinstance(raw, str):
        return 'unknown'
    if not re.fullmatch(r'[0-9a-f]{20}|[0-9a-f]{24}', raw):
        return 'unknown'
    wire = bytes.fromhex(raw)
    if size != len(wire):
        return 'unknown'
    if source == 0x90bf0274 and size == 12 and wire[:8] == bytes.fromhex('0600a32000000000') and wire[9:] == b'\0\0\0':
        return 'ee-capability'
    if source == 0x92840747 and size == 12 and wire[:8] == bytes.fromhex('0d2046110c000180'):
        return 'touch-config-reply'
    if source == 0x92840747 and size == 12 and wire[:8] == bytes.fromhex('0d2029140c000180'):
        return 'tcin-config-reply'
    if source >> 28 == 8 and source & 0xfffffff and size == 10 and wire[8] <= 1 and wire[9] == 0:
        if wire[:8] == bytes.fromhex('0d2046010a000180'):
            return 'touch-config-request'
        if wire[:8] == bytes.fromhex('0d2029040a000180'):
            return 'tcin-config-request'
    return 'unknown'


def resource_trace_summary(trace, virtual_backend_trace=None, *, virtual_touch_profile=None):
    """Bounded receipts; caller binds both inputs to one run. No original/EE proof from model frees."""
    result = dict(available=False, trace_integrity=False, capped=False, records=[],
                  touch_rpc=[], tcin_rpc=[], original_touch_rpc_complete=False,
                  original_tcin_rpc_complete=False, virtual_backend_touch_rpc_complete=False,
                  original_function_bound=False, descriptor_verified=False,
                  configuration_verified=False, bulk_verified=False,
                  host_enumerated=False, authentication_verified=False,
                  guest_root_over_usb_verified=False, original_cp_history_verified=False)
    try:
        text = trace.decode('ascii') if isinstance(trace, bytes) else trace
        candidates = [(index, line) for index, line in enumerate(text.splitlines())
                      if line.startswith('USB_START RESOURCE_')]
        if not candidates:
            return result
        result['available'] = True
        if len(candidates) > 65:
            raise ValueError('Resource record budget exceeded')
        identities = re.findall(r'^USB_START DSO_IDENTITY tid=\d+ path=/usr/lib/appFw[.]so map=/usr/lib/appFw[.]so base=(0x[0-9a-f]+) bytes=99960744 sha256=2ea02f7ecbc5bb917316fe8ef4ce5ffd87eb66efaae78ba2ce11420552df539b pid=([1-9]\d*)$', text, re.M)
        bases = {}
        for base, pid in identities:
            if int(pid) in bases:
                raise ValueError('Duplicate original AP resource identity')
            bases[int(pid)] = int(base, 16)
        def fields(body):
            values = {}
            for token in body.split():
                key, value = token.split('=', 1)
                if not value or key in values:
                    raise ValueError('Duplicate or empty resource field')
                values[key] = value
            return values
        def number(values, key):
            return int(values[key], 0)
        model_by_tid = {}
        if virtual_backend_trace is not None:
            if virtual_touch_profile not in (None, 'virtual-config-v1', 'virtual-config-tcin-inactive-v1'):
                raise ValueError('Unknown virtual helper selection')
            config_count = 0
            model_text = virtual_backend_trace.decode('ascii') if isinstance(virtual_backend_trace, bytes) else virtual_backend_trace
            model_lines = [line.removeprefix('OBS ') for line in model_text.splitlines()
                           if line.startswith(('FULL_TOUCH_PANEL_', 'OBS FULL_TOUCH_PANEL_'))]
            if len(model_lines) > 128 or len(bases) != 1:
                raise ValueError('Ambiguous virtual touch source/budget')
            for line in model_lines:
                if len(line.encode('ascii')) + 1 > 1024:
                    raise ValueError('Truncated virtual touch record')
                match = re.fullmatch(r'FULL_TOUCH_PANEL_([A-Z_]+) (.+)', line)
                if not match or match[1] not in ('REQUEST', 'CONFIG', 'REPLY_QUEUED', 'DEVPANEL', 'COMMIT', 'REPLY_FREE'):
                    raise ValueError('Virtual touch fault or unknown lifecycle')
                values = fields(match[2])
                if match[1] == 'CONFIG':
                    config_count += 1
                    expected = dict(enabled='1', profile='virtual-config-v1',
                                    original_cp_executed='0', hardware_touch_verified='0')
                    if values != expected or config_count != 1:
                        raise ValueError('Unknown or duplicate touch provider configuration')
                    continue
                model_by_tid.setdefault(number(values, 'tid'), []).append((match[1], values))
            if config_count != 1:
                raise ValueError('Missing touch provider configuration')
            result['virtual_touch_provider_profile'] = 'virtual-config-v1'
            result['selected_virtual_helper_profile'] = virtual_touch_profile
        groups = {}
        for index, line in candidates:
            if line == 'USB_START RESOURCE_CAP records=64':
                if result['capped']:
                    raise ValueError('Duplicate resource cap')
                result['capped'] = True
                continue
            if result['capped'] or len(line.encode('ascii')) + 1 > 512:
                raise ValueError('Truncated or post-cap resource record')
            match = re.fullmatch(r'USB_START RESOURCE_([A-Z_]+) pid=([1-9]\d*) tid=([1-9]\d*) (.+)', line)
            if not match:
                raise ValueError('Malformed original resource boundary')
            values = fields(match[4])
            row = dict(event=match[1], pid=int(match[2]), tid=int(match[3]),
                       index=index, fields=values, raw=line)
            result['records'].append(row)
            if match[1].startswith('RPC_'):
                if match[1] not in ('RPC_ENTER', 'RPC_FREE_ENTER', 'RPC_FREE_RETURN', 'RPC_RETURN'):
                    raise ValueError('Unknown RPC boundary')
                serial = number(values, 'serial')
                if not 0 < serial <= 0xffffffff:
                    raise ValueError('Invalid RPC serial')
                groups.setdefault((row['pid'], row['tid'], serial), []).append(row)
        if len(result['records']) > 64 or result['capped'] and len(result['records']) != 64:
            raise ValueError('Resource cap/count mismatch')
        leases = set()
        for (pid, tid, serial), rows in groups.items():
            events = [row['event'] for row in rows]
            if events not in (['RPC_ENTER', 'RPC_RETURN'], ['RPC_ENTER', 'RPC_FREE_ENTER', 'RPC_FREE_RETURN', 'RPC_RETURN']):
                raise ValueError('Incomplete or overlapping original RPC boundary')
            enter, returned = rows[0]['fields'], rows[-1]['fields']
            request, reply = enter['raw'], returned['raw']
            request_wire = bytes.fromhex(request)
            kind = {'0d2046010a000180': 'touch-config', '0d2029040a000180': 'tcin-config'}.get(request[:16])
            if kind is None or len(request_wire) != 10 or request_wire[8] > 1 or request_wire[9] != 0:
                raise ValueError('Unknown original RPC envelope')
            observation = dict(pid=pid, tid=tid, serial=serial, complete=False,
                               trace_lines=[row['index'] + 1 for row in rows],
                               request_raw=request, reply_raw=reply,
                               original_pre_free_observed=False, release_provenance='unobserved',
                               copied_reply_matches_pre_free=False, virtual_backend_consumption_verified=False)
            result['touch_rpc' if kind == 'touch-config' else 'tcin_rpc'].append(observation)
            app = bases.get(pid, 0)
            caller = 0x34e8b68 if kind == 'touch-config' else 0x34ef634
            if not (app > 0 and number(enter, 'destination') == 0x92840747 and
                    number(enter, 'request') > 0 and number(enter, 'response') > 0 and
                    number(enter, 'bytes') == 10 and number(enter, 'reply_bytes') == 12 and
                    number(enter, 'caller') == app + caller and
                    number(returned, 'response') == number(enter, 'response') and
                    number(returned, 'bytes') == 12 and number(returned, 'read') == 1 and
                    classify_usb_message(0x92840747, 12, reply) == kind + '-reply' and
                    returned['return_type'] == 'void' and number(returned, 'errno') >= 0):
                raise ValueError('Mismatched original RPC wire/caller/copy')
            observation['reply_status'] = int.from_bytes(bytes.fromhex(reply)[8:], 'little')
            if len(rows) == 4:
                before, after = rows[1]['fields'], rows[2]['fields']
                owner = number(before, 'owner')
                if not (owner != 0x80020002 and owner >> 28 == 8 and owner & 0xfffffff and
                        number(before, 'message') > 0 and number(before, 'source') == 0x92840747 and
                        number(before, 'bytes') == 12 and before['raw'] == reply and
                        number(before, 'caller') == app + 0x34e57a8 and
                        number(after, 'owner') == owner and number(after, 'message') == number(before, 'message') and
                        number(after, 'rc') == 0 and number(after, 'errno') >= 0):
                    raise ValueError('Mismatched original RPC owner/free/pre-free copy')
                observation.update(complete=True, owner=hex(owner), message=before['message'],
                                   original_free_rc=0, copied_reply_matches_pre_free=True,
                                   original_pre_free_observed=True, release_provenance='original-pre-free')
            elif kind == 'touch-config' and virtual_backend_trace is not None:
                model = model_by_tid.get(tid, [])
                chunk = model[:5]
                if [event for event, _ in chunk] != ['REQUEST', 'REPLY_QUEUED', 'DEVPANEL', 'COMMIT', 'REPLY_FREE']:
                    raise ValueError('Incomplete virtual touch direct-release lifecycle')
                requested, queued, devpanel, commit, freed = [values for _, values in chunk]
                owner, pointer, lease = number(requested, 'source'), number(queued, 'reply'), number(queued, 'lease')
                enable = bytes.fromhex(request)[8]
                if not (owner != 0x80020002 and owner >> 28 == 8 and owner & 0xfffffff and
                        pointer > 0 and lease > 0 and lease not in leases and
                        number(requested, 'destination') == 0x92840747 and number(requested, 'bytes') == 10 and
                        requested['raw'] == request and requested['virtual_config_only'] == '1' and
                        number(queued, 'destination') == owner and number(queued, 'source') == 0x92840747 and
                        number(queued, 'bytes') == 12 and queued['raw'] == reply and number(queued, 'raw_status') == 0x590000 and
                        number(devpanel, 'cache') == number(devpanel, 'readback') == enable and
                        devpanel['f02f'] == '01202ff00c000100' + enable.to_bytes(4, 'little').hex() and
                        number(devpanel, 'f02f_destination') == 0x90590819 and number(devpanel, 'vdf_reply_sid') == 0x9059000e and
                        number(devpanel, 'control_gate_virtual') == 0 and devpanel['control'] == '03000000' + enable.to_bytes(4, 'little').hex() and
                        number(devpanel, 'control_submissions') > 0 and
                        all(devpanel[key] == '0' for key in ('control_result_verified', 'f02f_transport_verified', 'original_cp_executed', 'hardware_touch_verified')) and
                        number(commit, 'enable') == number(commit, 'cache') == number(commit, 'readback') == enable and
                        number(commit, 'outer_status') == 0x590000 and number(commit, 'applied') == number(commit, 'queued') > 0 and
                        commit['request_free_rc'] == commit['request_retained'] == '0' and commit['clean_completion'] == '1' and
                        all(commit[key] == '0' for key in ('f02f_transport_verified', 'control_result_verified', 'hardware_touch_verified', 'camera_capture_verified')) and
                        number(freed, 'destination') == owner and number(freed, 'reply') == pointer and number(freed, 'lease') == lease and freed['rc'] == '0'):
                    raise ValueError('Mismatched virtual touch lease/state/RPC response')
                leases.add(lease)
                del model[:5]
                observation.update(complete=True, owner=hex(owner), message=queued['reply'], lease=lease,
                                   model_request_free_rc=0, model_direct_reply_free_rc=0,
                                   release_provenance='virtual_backend-direct',
                                   virtual_backend_consumption_verified=True)
        if any(model_by_tid.values()):
            raise ValueError('Unmatched virtual touch lifecycle')
        result['trace_integrity'] = not result['capped']
        for key, complete_key in (('touch_rpc', 'original_touch_rpc_complete'), ('tcin_rpc', 'original_tcin_rpc_complete')):
            result[complete_key] = bool(result[key]) and result['trace_integrity'] and all(row['original_pre_free_observed'] for row in result[key])
        result['virtual_backend_touch_rpc_complete'] = bool(result['touch_rpc']) and result['trace_integrity'] and all(row['virtual_backend_consumption_verified'] for row in result['touch_rpc'])
    except (ValueError, KeyError, TypeError, UnicodeError) as error:
        result['error'] = str(error)
    return result


def start_trace_summary(raw):
    text = raw.decode('utf-8', errors='replace')
    blocks = re.findall(r'^USB_AP_START_TRACE_BEGIN\n(.*?)^USB_AP_START_TRACE_RC=(\d+)\nUSB_AP_START_TRACE_END$', text, re.M | re.S)
    if len(blocks) != 1 or blocks[0][1] != '0':
        return dict(available=False, installed_before_init=False, start_syscall_actual_zero=False)
    trace = blocks[0][0]
    installed = re.findall(r'^USB_START INSTALLED tid=\d+ dso=([^ ]+) before_init=1$', trace, re.M)
    starts = re.findall(r'^USB_START IOCTL_RETURN tid=\d+ fd=(-?\d+) req=0x4018e203 rc=(-?\d+) errno=(\d+)$', trace, re.M)
    app_preinit = re.findall(r'^USB_START AP_PREINIT_CONFIRMED tid=\d+ pid=(\d+) base=(0x[0-9a-f]+) resolved=(0x[0-9a-f]+) both_entries=1$', trace, re.M)
    entries = re.findall(r'^USB_START ENTRY_ARMED tid=\d+ base=(0x[0-9a-f]+) offset=(0x[0-9a-f]+) ', trace, re.M)
    app_ok = (len(app_preinit) == 1 and all((app_preinit[0][1], offset) in entries for offset in ('0x34796b0', '0x354db04')))
    return dict(available=True, installed_before_init=all(installed.count(name)==1 for name in ('libInfraUsbCmn.so','libUsbControl.so')),
                app_taps_preinit=app_ok, app_preinit=app_preinit,
                msc_loaded='libInfraMscServer.so' in installed,
                sender_events=re.findall(r'^USB_START (?:AP_MSC|MSC_)[^\n]*$', trace, re.M),
                openSvc_returns=re.findall(r'^USB_START OPEN_SVC_RETURN [^\n]+$', trace, re.M),
                start_syscalls=[dict(fd=int(fd), rc=int(rc), errno=int(error)) for fd, rc, error in starts],
                start_syscall_actual_zero=any(int(rc)==0 for _,rc,_ in starts),
                first_errors=re.findall(r'^USB_START (?:GUARD_FAILED|READ_FAILED|IOCTL_RETURN|OPEN_SVC_RETURN|INFRA_RETURN|CREATE_RETURN) [^\n]*(?:rc=-[1-9][0-9]*|reason=[^\n]+)[^\n]*$', trace, re.M)[:16],
                resource_trace=resource_trace_summary(trace),
                capped='USB_START CAP bounded=1' in trace)


def observer_mode(contract, *, observe_start, camera_profile, seconds):
    ee = contract.get('ee_observer') if contract else None
    private = contract.get('ee_normal_cold') if contract else None
    if not observe_start:
        if ee is not None or private is not None:
            raise ValueError('EE mode requires explicit observe_start')
        return 'off'
    start = runpy.run_path(str(HERE / 'usb-start-observe.py'))
    if camera_profile != start['PROFILE']:
        raise ValueError('Original USB observer requires its explicit service profile')
    if ee is None:
        if private is not None:
            raise ValueError('Functional private inputs require an explicit EE profile')
        return 'passive'
    if not isinstance(ee, dict) or ee.get('profile') not in (ZERO_MODE, FUNCTIONAL_MODE):
        raise ValueError('Unknown explicit EE observer mode')
    if not 10 <= seconds <= 120:
        raise ValueError('EE observer is limited to 10..120 seconds')
    mode = ee['profile']
    if mode == FUNCTIONAL_MODE:
        if not isinstance(private, dict) or private.get('profile') != mode:
            raise ValueError('Functional EE requires its private input contract')
        api = runpy.run_path(str(HERE / 'usb-ee-normal-cold.py'))
        expected = api['CONTRACT']
    else:
        if private is not None:
            raise ValueError('Zero-publication EE excludes functional private inputs')
        expected = start['EE_CONTRACT']
    source = hashlib.sha256((HERE / 'usb-ee-zero-observe.inc').read_bytes()).hexdigest()
    if ee != dict(expected, source_sha256=source):
        raise ValueError('EE observer explicit mode/contract drift')
    return mode


def verified_observer(analysis, *, observe_start, camera_profile, seconds):
    analysis = Path(analysis)
    path = analysis / 'full-system.json'
    before = PERSISTENT['COLD']['binding'](path, 'usb-start-manifest')
    contract = json.loads(path.read_text()).get('usb_start_observe')
    mode = observer_mode(contract, observe_start=observe_start, camera_profile=camera_profile, seconds=seconds)
    bindings = []
    if observe_start:
        start = runpy.run_path(str(HERE / 'usb-start-observe.py'))
        for row in start['validate'](analysis):
            current = PERSISTENT['COLD']['binding'](row['path'], row['role'])
            if current['sha256'] != row['sha256'] or ('bytes' in row and current['bytes'] != row['bytes']):
                raise ValueError('USB observer binding changed during validation: ' + row['role'])
            bindings.append(current)
        if PERSISTENT['COLD']['binding'](path, before['role']) != before:
            raise ValueError('USB observer manifest changed during validation')
        bindings.append(before)
    return mode, contract if observe_start else None, bindings


def functional_trace_summary(raw, contract, *, diagnostic_only=False, virtual_backend_trace=None):
    result = dict(mode=FUNCTIONAL_MODE, generation=contract['ee_normal_cold']['generation'],
                  diagnostic_only=diagnostic_only, trace_integrity=False, capped=False,
                  native_message_released=False, no_allocation_proven=False,
                  resource_safe_to_close=False, native_content_verified=False, business_complete=False,
                  strict_can_publish=0, stage_actual=False, original_cp_history_verified=False,
                  physical_compatibility_verified=False, full_boot_verified=False, capture_verified=False,
                  host_enumerated=False, authentication_verified=False, guest_root_over_usb_verified=False)
    source_class = contract['ee_normal_cold'].get('admission_source', 'callback')
    kernel = source_class == 'kerneldefault'
    result['source_class'] = source_class
    checks = result['checks'] = {}
    blocks = re.findall(rb'^USB_AP_START_TRACE_BEGIN\n(.*?)^USB_AP_START_TRACE_RC=(\d+)\nUSB_AP_START_TRACE_END$', raw, re.M | re.S)
    if len(blocks) != 1 or blocks[0][1] != b'0':
        result['error'] = 'Missing, duplicate or failed native trace readback'
        return result
    trace = blocks[0][0]
    sha = hashlib.sha256(trace).hexdigest()
    result['trace_sha256'] = sha
    for when in ('BEFORE', 'AFTER'):
        marker = ('USB_AP_START_TRACE_SHA_' + when).encode()
        rows = re.findall(rb'^' + marker + rb'\n(?:SHA256|SHA2-256)\(/dev/qemu-simulation/usb-start-observe[.]log\)= ([0-9a-f]{64})\n' + marker + rb'_RC=(\d+)$', raw, re.M)
        if rows != [(sha.encode(), b'0')]:
            result['error'] = 'Native trace changed, truncated or lacks successful ' + when.lower() + ' SHA readback'
            return result
    result['trace_integrity'] = True
    result['resource_trace'] = resource_trace_summary(trace, virtual_backend_trace,
        virtual_touch_profile=((contract.get('native_forwarder') or {}).get('usb_touch') or {}).get('profile'))
    result['capped'] = b'USB_EE CAP ' in trace or b'USB_START CAP ' in trace
    if result['capped']:
        result['error'] = 'Capped native trace cannot prove a complete lease'
        return result
    records = []
    diagnostics = result['diagnostics'] = []
    try:
        if source_class not in ('callback', 'kerneldefault'):
            raise ValueError('Unknown prepared functional source class')
        if kernel and (type(contract['ee_normal_cold'].get('admission_version')) is not int or
                       contract['ee_normal_cold']['admission_version'] != 1 or
                       contract['ee_normal_cold'].get('kernel_uipc') != runpy.run_path(str(HERE / 'usb-ee-normal-cold.py'))['KERNEL_UIPC']):
            raise ValueError('Missing explicit prepared kerneldefault contract')
        text = trace.decode('ascii')
        for index, line in enumerate(text.splitlines()):
            if line.startswith('USB_EE_DIAG '):
                match = re.fullmatch(r'USB_EE_DIAG (READ_INIT|WAIT_ADMISSION|RECV_SLOT|FREE_RETURN) pid=([1-9]\d*) tid=([1-9]\d*) write_failures=(\d+) cap_mask=(\d+) (.+)', line)
                if (match is None or len(line) >= 1024 or len(diagnostics) >= 4 or
                        any(row['event'] == match[1] for row in diagnostics)):
                    raise ValueError('Malformed or duplicate bounded EE diagnostic')
                diagnostics.append(dict(event=match[1], pid=int(match[2]), raw=line,
                    write_failures=int(match[4]), cap_mask=int(match[5])))
                continue
            if not line.startswith(('USB_START ', 'USB_EE ')):
                raise ValueError('Unknown or damaged native trace line')
            if not line.startswith('USB_EE '):
                continue
            match = re.fullmatch(r'USB_EE ([A-Z_]+) tid=(\d+) mono=(\d+\.\d{9}) clock_ok=1 (.+)', line)
            if not match:
                raise ValueError('Malformed native EE record')
            fields = {}
            for token in match[4].split():
                key, value = token.split('=', 1)
                if not value or key in fields:
                    raise ValueError('Duplicate or incomplete native EE field')
                fields[key] = value
            records.append(dict(event=match[1], tid=int(match[2]), index=index, fields=fields))
        result['wire_observations'] = [dict(trace_line=row['index'] + 1,
            message=row['fields'].get('message'), raw=row['fields'].get('raw'),
            classification=(classify_usb_message(int(row['fields'].get('source', '0'), 0),
                int(row['fields'].get('size', '0'), 0), row['fields'].get('raw', 'unavailable'))
                if row['fields'].get('source_known') == row['fields'].get('copy12') == '1' else 'unknown'))
            for row in records if row['event'] == 'SIZE']
        def rows(event):
            return [r for r in records if r['event'] == event]
        def number(row, name):
            value = row['fields'][name]
            return int(value, 16 if value.startswith('0x') else 10)
        def one(event):
            values = rows(event)
            if len(values) != 1:
                raise ValueError('Expected one ' + event)
            return values[0]
        def fields(row, **wanted):
            return all(row['fields'].get(key) == str(value) for key, value in wanted.items())
        required = {
            'GOT_ARMED': 'slot name old chosen raw verified_cached_pointer native_sha256',
            'PREINIT': 'app_base uipc_base installed ee_can_publish functional_model mode',
            'QUEUE_ENTER': 'queue handle_out callback context caller',
            'QUEUE_RETURN': 'queue handle_out handle handle_read callback context caller rc errno',
            'RECV_ENTER': 'queue output timeout caller',
            'RECV_RETURN': 'queue output message message_read caller rc errno',
            'SOURCE': 'queue message source caller',
            'SIZE': 'queue message source source_known size copy12 raw caller',
            'FREE_ENTER': 'owner message recv_match source source_known size size_known caller',
            'FREE_RETURN': 'owner message recv_match caller rc errno',
            'PROMISE_REGISTER': 'id id_source map key caller return_x0 return_x1 deferred_until_unlock',
            'WAIT_ENTER': 'id future caller first after_original_unlock',
            'WAIT_RETURN': 'id future caller return_x0 errno',
            'FUNCTIONAL_GATE': 'mode handle callback context receiver_tid promise reader registration_event unlock_event original_rc original_20a3_return original_wait_unlocked envelope_sha256 model_sha256',
            'FUNCTIONAL_ALLOCATE_ENTER': 'mode generation destination bytes flags',
            'FUNCTIONAL_ALLOCATE_RETURN': 'mode generation destination message rc errno',
            'FUNCTIONAL_SEND_ENTER': 'mode generation destination message',
            'FUNCTIONAL_SEND_RETURN': 'mode generation destination message rc errno',
            'FUNCTIONAL_COPY': 'mode generation source_class method message message_generation receive_event receiver_tid source bytes rc',
        }
        if kernel:
            required.update({
                'FUNCTIONAL_GATE': 'mode generation source_class registration receiver_tid waiter_tid promise reader registration_event unlock_event original_rc original_20a3_return original_wait_unlocked envelope_sha256 model_sha256',
                'FUNCTIONAL_INIT': 'mode generation source_class fd map bytes allocator pool0 pool1 dynamic_id abi_verified fd_verified map_verified',
                'FUNCTIONAL_PRIME': 'mode generation source_class message message_generation receive_event free_event receiver_tid free_actor_tid source size source_known size_known receive_rc free_rc free_returned',
                'FUNCTIONAL_FREE_TICKET': 'mode generation source_class message message_generation receive_event slot owner receiver_tid free_actor_tid source size observed state',
            })
        snapshot_events = {'FUNCTIONAL_TRIGGER', 'FUNCTIONAL_RECEIVE', 'FUNCTIONAL_READER', 'FUNCTIONAL_FREE', 'FUNCTIONAL_CREATE', 'FUNCTIONAL_ARM', 'FUNCTIONAL_CLOCK'}
        if kernel:
            snapshot_events.add('FUNCTIONAL_WAIT_RETURN')
        for row in records:
            event = row['event']
            if event not in required and event not in snapshot_events:
                raise ValueError('Unknown native EE event')
            if not {'pid', *required.get(event, 'mode generation').split()} <= row['fields'].keys():
                raise ValueError('Incomplete native EE record')
            if not re.fullmatch(r'[1-9]\d*', row['fields']['pid']):
                raise ValueError('Invalid native EE PID')
            if 'generation' in row['fields'] and number(row, 'generation') != result['generation']:
                raise ValueError('Mixed functional epoch')
        initialized = []
        for line in text.splitlines():
            if re.match(r'USB_START INITIALIZED(?: |$)', line):
                match = re.fullmatch(r'USB_START INITIALIZED tid=(\d+) pid=([1-9]\d*) passive=([01])(?: functional_model=([01]) mode=([a-z0-9-]+))?', line)
                if not match:
                    raise ValueError('Malformed original observer initialization')
                initialized.append(match.groups())
        functional = [r for r in records if r['event'].startswith('FUNCTIONAL_')]
        snapshots = [r for r in functional if r['event'] in snapshot_events]
        allowed = snapshot_events | {name for name in required if name.startswith('FUNCTIONAL_')}
        for row in functional:
            if (row['event'] not in allowed or not fields(row, mode=FUNCTIONAL_MODE) or
                    (kernel and not fields(row, source_class=source_class)) or
                    row['fields'].get('source_class', source_class) != source_class):
                raise ValueError('Unknown functional record/mode/source class')
            if row['event'] != 'FUNCTIONAL_GATE' and number(row, 'generation') != result['generation']:
                raise ValueError('Mixed functional epoch')
        for row in snapshots:
            required = {'rc', 'attempted', 'allocated', 'send_called', 'send_returned', 'send_rc', 'received', 'reader', 'output', 'free', 'free_rc', 'retired', 'pending', 'fault', 'strict_can_publish', 'functional_model', 'message', 'current', 'reason', 'raw', 'actual_wire', 'actual_source', 'actual_bytes', 'actual_consumer', 'free_owner', 'stage_actual'}
            if kernel:
                required |= {'owned_copy', 'wait_returned', 'message_generation', 'lease_pid', 'lease_generation', 'free_actor_tid'}
            if not required <= row['fields'].keys() or not fields(row, strict_can_publish=0, functional_model=1, stage_actual=0):
                raise ValueError('Incomplete or elevated functional snapshot')
        pre = rows('PREINIT')
        preinit = pre[0] if len(pre) == 1 else None
        app_lines = [line for line in text.splitlines() if re.match(r'USB_START AP_PREINIT_CONFIRMED(?: |$)', line)]
        app = [re.fullmatch(r'USB_START AP_PREINIT_CONFIRMED tid=\d+ pid=([1-9]\d*) base=(0x[0-9a-f]+) resolved=0x[0-9a-f]+ both_entries=1', line) for line in app_lines]
        early_guard = (not pre and not functional and not app_lines and re.search(r'^USB_START GUARD_FAILED tid=\d+ reason=EE (?:UIPC original path/size/SHA256|UIPC entry bytes|promise entry bytes|reader 3549218 (?:complete mapped entry differs from SHA-bound original ELF|bytes/ABI drift)|(?:lookup|lookup-path|lookup-entry|bytes|GOT-slot) api=[^\n]+)$', text, re.M) is not None)
        if preinit:
            pid = preinit['fields']['pid']
            if (len(app) != 1 or app[0] is None or app[0].groups() != (pid, preinit['fields']['app_base'])
                    or not fields(preinit, installed=8, ee_can_publish=0, functional_model=1, mode=FUNCTIONAL_MODE)
                    or number(preinit, 'app_base') <= 0 or number(preinit, 'uipc_base') <= 0
                    or text.index('USB_EE PREINIT ') >= text.index('USB_START AP_PREINIT_CONFIRMED ')):
                raise ValueError('Missing or mismatched original AP preinit')
            result['target_actor'] = dict(pid=int(pid), app_base=preinit['fields']['app_base'])
        elif early_guard and len(initialized) == 1:
            pid = initialized[0][1]
        else:
            raise ValueError('Expected one PREINIT and original AP confirmation, or unique early guard actor')
        if any(row['fields']['pid'] != pid for row in records) or any(row['pid'] != int(pid) for row in diagnostics):
            raise ValueError('Mixed native EE target PID')
        selected = [row for row in initialized if row[1] == pid]
        result['initializations'] = dict(total=len(initialized), target=len(selected),
            unselected=len(initialized) - len(selected),
            unselected_pids=sorted({int(row[1]) for row in initialized if row[1] != pid}),
            records=[dict(tid=int(row[0]), pid=int(row[1]), passive=int(row[2]),
                          functional_model=int(row[3]) if row[3] is not None else None,
                          mode=row[4], selected=row[1] == pid) for row in initialized])
        if len(selected) != 1 or selected[0][2:] != ('0', '1', FUNCTIONAL_MODE):
            raise ValueError('Missing, duplicate or mismatched target functional observer initialization')
        checks['preinit'] = preinit is not None
        if not rows('FUNCTIONAL_ALLOCATE_ENTER'):
            if not functional and (checks['preinit'] or early_guard):
                api = runpy.run_path(str(HERE / 'usb-ee-normal-cold.py'))
                proven = api['allocation_log_commit_proven'](contract)
                if proven and (early_guard or fields(preinit, native_allocation_log_commit_required=1, native_allocation_log_commit_version=1)):
                    result.update(no_allocation_proven=True, resource_safe_to_close=True, resource_proof='complete-trace-no-allocation',
                                  native_allocation_log_commit_required=True, allocation_log_acknowledgement='full-write')
                else:
                    result['error'] = 'Unknown native allocation reachability: source/header/DSO full-write contract is unproven'
            else:
                result['error'] = 'No complete source-bound proof that native allocation was unreachable or absent'
            return result
        allocate_enter, allocate_return = one('FUNCTIONAL_ALLOCATE_ENTER'), one('FUNCTIONAL_ALLOCATE_RETURN')
        message = number(allocate_return, 'message')
        checks['allocation'] = (message > 0 and fields(allocate_enter, destination='0x80020002', bytes=12, flags=1) and fields(allocate_return, destination='0x80020002', rc=0) and (not kernel or fields(allocate_return, resources_valid=1)) and allocate_enter['tid'] == allocate_return['tid'] and allocate_enter['index'] < allocate_return['index'])
        result['message'] = hex(message)
        if not checks['allocation']:
            raise ValueError('Native allocation lease is incomplete')
        if any(number(r, 'message') != message for r in functional if 'message' in r['fields'] and r['event'] != 'FUNCTIONAL_PRIME'):
            raise ValueError('Mixed functional message pointers')
        matching = [r for r in records if 'message' in r['fields'] and number(r, 'message') == message and (not kernel or r['index'] > allocate_return['index'])]
        def native(event):
            values = [r for r in matching if r['event'] == event]
            if len(values) != 1:
                raise ValueError('Expected one native ' + event)
            return values[0]
        free_enter, free_return = native('FREE_ENTER'), native('FREE_RETURN')
        checks['native_free'] = (fields(free_enter, owner='0x80020002') and fields(free_return, owner='0x80020002', rc=0) and (kernel or fields(free_enter, recv_match=1) and fields(free_return, recv_match=1)) and free_enter['tid'] == free_return['tid'] and allocate_return['index'] < free_enter['index'] < free_return['index'])
        if checks['native_free'] and not kernel:
            result.update(native_message_released=True, resource_safe_to_close=True, resource_proof='same-pointer-native-free-zero')
        gate = one('FUNCTIONAL_GATE')
        private_rows = contract['ee_normal_cold']['private_inputs']
        private = {p['role']: p for p in private_rows}
        if len(private) != len(private_rows) or any(re.fullmatch(r'[0-9a-f]{64}', private[role]['sha256']) is None for role in ('ee-private-envelope', 'ee-private-model')):
            raise ValueError('Missing or duplicate prepared SHA256 identity')
        receiver = number(gate, 'receiver_tid')
        checks['gate'] = (receiver > 0 and 0 < number(gate, 'registration_event') < number(gate, 'unlock_event') and number(gate, 'promise') > 0 and fields(gate, original_rc=0, original_20a3_return=1, original_wait_unlocked=1, envelope_sha256=private['ee-private-envelope']['sha256'], model_sha256=private['ee-private-model']['sha256']) and gate['index'] < allocate_enter['index'] and gate['tid'] == allocate_enter['tid'])
        queue_enter = [r for r in rows('QUEUE_ENTER') if fields(r, queue='0x80020002')]
        queue = [r for r in rows('QUEUE_RETURN') if fields(r, queue='0x80020002')]
        if kernel:
            if number(gate, 'registration_event') or queue_enter or queue:
                raise ValueError('Kerneldefault cannot replace an original target registration event')
            checks['gate'] = (receiver > 0 and number(gate, 'waiter_tid') == gate['tid'] != receiver and
                number(gate, 'promise') > 0 and fields(gate, registration='not_applicable', original_rc=5,
                    original_20a3_return=1, original_wait_unlocked=1,
                    envelope_sha256=private['ee-private-envelope']['sha256'], model_sha256=private['ee-private-model']['sha256']) and
                gate['index'] < allocate_enter['index'] and gate['tid'] == allocate_enter['tid'])
            checks['registration'] = True
            result['kernel_registration'] = 'not_applicable'
            init, prime = one('FUNCTIONAL_INIT'), one('FUNCTIONAL_PRIME')
            mapping, capacity = number(init, 'map'), number(init, 'bytes')
            def span(pointer, size):
                return mapping > 0 and capacity > 0 and 0 <= pointer - mapping <= capacity - size and size > 0
            checks['kernel_init'] = (fields(init, abi_verified=1, fd_verified=1, map_verified=1) and
                number(init, 'fd') >= 0 and number(init, 'pool0') == 0x80000 and number(init, 'pool1') == 0x20000 and
                capacity == 0x200000 and mapping <= 2**64 - capacity and
                number(init, 'dynamic_id') > 0 and number(init, 'allocator') > 0 and span(message - 24, 36) and
                init['tid'] == prime['tid'] == gate['tid'] and preinit['index'] < init['index'] < prime['index'] < gate['index'])
            prime_message = number(prime, 'message')
            prime_events = ('RECV_RETURN', 'SOURCE', 'SIZE', 'FREE_ENTER', 'FREE_RETURN')
            prime_lifecycles, lifecycle = [], {}
            for row in records:
                if row['event'] not in prime_events or number(row, 'message') != prime_message:
                    continue
                if row['index'] > prime['index']:
                    # The allocated model lease may reuse the freed prime pointer; its own gates remain below.
                    if prime_message == message and row['index'] > allocate_return['index']:
                        continue
                    raise ValueError('Prime native pointer reused after FUNCTIONAL_PRIME')
                event = row['event']
                if event in lifecycle or (not lifecycle and event != 'RECV_RETURN'):
                    raise ValueError('Overlapping or partial prime native lifecycle')
                lifecycle[event] = row
                if event != 'FREE_RETURN':
                    continue
                if set(lifecycle) != set(prime_events):
                    raise ValueError('Incomplete prime native lifecycle')
                pr, ps, pz, pfe, pfr = (lifecycle[event] for event in prime_events)
                previous = max((r['index'] for r in rows('RECV_RETURN') if r['tid'] == pr['tid'] and
                    fields(r, queue='0x80020002') and number(r, 'output') == number(pr, 'output') and
                    r['index'] < pr['index']), default=preinit['index'])
                entries = [r for r in rows('RECV_ENTER') if r['tid'] == pr['tid'] and
                    fields(r, queue='0x80020002') and number(r, 'output') == number(pr, 'output') and
                    previous < r['index'] < pr['index'] and number(r, 'caller') == number(pr, 'caller')]
                size_source = (fields(pz, source_known=1) and number(pz, 'source') == number(ps, 'source') or
                    fields(pz, source_known=0, source=0) and pz['index'] < ps['index'])
                free_metadata = (fields(pfe, recv_match=0, source=0, source_known=0, size=0, size_known=0) or
                    fields(pfe, recv_match=1, source_known=1, size_known=1) and
                    number(pfe, 'source') == number(ps, 'source') and number(pfe, 'size') == number(pz, 'size'))
                if not (len(entries) == 1 and pr['tid'] == ps['tid'] == pz['tid'] == receiver and
                    fields(pr, queue='0x80020002', message_read=1, rc=0) and fields(ps, queue='0x80020002') and
                    fields(pz, queue='0x80020002') and number(ps, 'source') > 0 and
                    span(prime_message, number(pz, 'size')) and size_source and free_metadata and
                    fields(pfe, owner='0x80020002') and fields(pfr, owner='0x80020002', rc=0) and
                    pfe['tid'] == pfr['tid'] and number(pfe, 'caller') == number(pfr, 'caller') and
                    pfe['fields']['recv_match'] == pfr['fields']['recv_match'] and
                    preinit['index'] < pr['index'] < min(ps['index'], pz['index']) <= max(ps['index'], pz['index']) < pfe['index'] < pfr['index'] < prime['index']):
                    raise ValueError('Mismatched prime native lifecycle')
                prime_lifecycles.append(lifecycle)
                lifecycle = {}
            if lifecycle or not prime_lifecycles:
                raise ValueError('Incomplete prime native lifecycle before FUNCTIONAL_PRIME')
            # Validate every historical use, then bind the prime snapshot to the most recent completed use.
            pr, ps, pz, pfe, pfr = (prime_lifecycles[-1][event] for event in prime_events)
            result['prime_native_lifecycles'] = [dict(
                trace_lines={event: row['index'] + 1 for event, row in cycle.items()},
                receiver_tid=cycle['RECV_RETURN']['tid'], free_actor_tid=cycle['FREE_RETURN']['tid'],
                source=cycle['SOURCE']['fields']['source'], size=number(cycle['SIZE'], 'size'),
                selected=index == len(prime_lifecycles) - 1) for index, cycle in enumerate(prime_lifecycles)]
            checks['kernel_prime'] = (fields(prime, source_known=1, size_known=1, receive_rc=0, free_rc=0, free_returned=1) and
                number(prime, 'source') > 0 and span(prime_message, number(prime, 'size')) and
                0 < number(prime, 'message_generation') == number(prime, 'receive_event') < number(prime, 'free_event') < number(gate, 'unlock_event') and
                number(prime, 'receiver_tid') == pr['tid'] == ps['tid'] == pz['tid'] == receiver and
                number(prime, 'free_actor_tid') == pfe['tid'] == pfr['tid'] and
                fields(pr, queue='0x80020002', message_read=1, rc=0) and fields(ps, queue='0x80020002') and fields(pz, queue='0x80020002') and
                number(ps, 'source') == number(prime, 'source') and number(pz, 'size') == number(prime, 'size') and
                fields(pfe, owner='0x80020002') and fields(pfr, owner='0x80020002', rc=0) and
                pr['index'] < min(ps['index'], pz['index']) <= max(ps['index'], pz['index']) < pfe['index'] < pfr['index'] < prime['index'] and
                any(r['tid'] == receiver and fields(r, queue='0x80020002') and number(r, 'output') == number(pr, 'output') and r['index'] < pr['index'] for r in rows('RECV_ENTER')))
            if not checks['kernel_prime']:
                raise ValueError('Mismatched selected prime native snapshot')
        else:
            checks['registration'] = (len(queue_enter) == len(queue) == 1 and fields(queue[0], rc=0) and (fields(queue[0], handle_read=1) or number(queue[0], 'handle_out') == 0) and all(number(queue[0], k) == number(gate, k) for k in ('handle', 'callback', 'context')) and queue_enter[0]['tid'] == queue[0]['tid'] and all(number(queue_enter[0], k) == number(queue[0], k) for k in ('handle_out', 'callback', 'context')) and queue_enter[0]['index'] < queue[0]['index'] < gate['index'])
        send_enter, send_return = one('FUNCTIONAL_SEND_ENTER'), one('FUNCTIONAL_SEND_RETURN')
        checks['send'] = (fields(send_enter, destination='0x80020002') and fields(send_return, destination='0x80020002', rc=0) and allocate_enter['tid'] == send_enter['tid'] == send_return['tid'] and allocate_return['index'] < send_enter['index'] < send_return['index'])
        receive, source, size = native('RECV_RETURN'), native('SOURCE'), native('SIZE')
        received, reader, freed, trigger = (one('FUNCTIONAL_' + event) for event in ('RECEIVE', 'READER', 'FREE', 'TRIGGER'))
        checks['receiver_entry'] = any(r['tid'] == receiver and fields(r, queue='0x80020002') and number(r, 'output') == number(receive, 'output') and r['index'] < receive['index'] for r in rows('RECV_ENTER'))
        size_copied = fields(size, copy12=1, source_known=1, source='0x90bf0274', raw='0600a3200000000000000000')
        size_first = fields(size, copy12=0, source_known=0, source=0, raw='unavailable') and size['index'] < source['index']
        owned_unknown = kernel and fields(size, copy12=0, source_known=1, source='0x90bf0274', raw='unavailable')
        checks['receive'] = (fields(receive, queue='0x80020002', message_read=1, rc=0) and fields(source, queue='0x80020002', source='0x90bf0274') and fields(size, queue='0x80020002', size=12) and (size_copied or size_first or owned_unknown) and receive['tid'] == source['tid'] == size['tid'] == received['tid'] == receiver and (kernel or free_enter['tid'] == receiver) and send_enter['index'] < receive['index'] < min(source['index'], size['index']) <= max(source['index'], size['index']) < received['index'] < free_enter['index'])
        checks['wire'] = fields(received, rc=0, received=1, actual_wire='0600a3200000000000000000', actual_source='0x90bf0274', actual_bytes=12) and number(received, 'actual_consumer') == receiver
        checks['snapshot_lease'] = all(fields(r, rc=0, fault=0) and (not fields(r, received=1) or (fields(r, actual_wire='0600a3200000000000000000', actual_source='0x90bf0274', actual_bytes=12) and number(r, 'actual_consumer') == receiver)) for r in snapshots)
        checks['reader'] = fields(reader, rc=0, reader=1, output=1, raw=0) and reader['tid'] == gate['tid'] and send_return['index'] < reader['index']
        checks['free_snapshot'] = fields(freed, rc=0, free=1, free_rc=0, free_owner='0x80020002') and (kernel or fields(free_enter, source='0x90bf0274', source_known=1, size=12, size_known=1)) and free_return['index'] < freed['index']
        checks['retirement'] = any(fields(r, retired=1, pending=0, fault=0, output=1, send_returned=1, send_rc=0, free=1, free_rc=0) and (not kernel or fields(r, owned_copy=1, wait_returned=1, reader=1)) for r in snapshots)
        checks['trigger'] = fields(trigger, attempted=1, allocated=1, send_called=1, send_returned=1, send_rc=0) and send_return['index'] < trigger['index']
        checks['init_before_gate'] = checks['preinit'] and preinit['index'] < gate['index']
        if checks['preinit']:
            base = number(preinit, 'app_base')
            promise, wait_enter, wait_return = one('PROMISE_REGISTER'), one('WAIT_ENTER'), one('WAIT_RETURN')
            checks['original_reader_wait'] = (number(gate, 'reader') == base + 0x3549218 and fields(promise, id='0x20a3', id_source='guarded_caller', deferred_until_unlock=1) and number(promise, 'caller') == base + 0x35492bc and fields(wait_enter, id='0x20a3', first=1, after_original_unlock=1) and fields(wait_return, id='0x20a3') and number(wait_enter, 'caller') == number(wait_return, 'caller') == base + 0x35492cc and number(wait_enter, 'future') == number(wait_return, 'future') == number(gate, 'promise') and promise['tid'] == wait_enter['tid'] == wait_return['tid'] == reader['tid'] and trigger['index'] < promise['index'] < wait_enter['index'] < wait_return['index'] < reader['index'])
        if kernel:
            copied, ticket, waited = one('FUNCTIONAL_COPY'), one('FUNCTIONAL_FREE_TICKET'), one('FUNCTIONAL_WAIT_RETURN')
            checks['owned_copy'] = (fields(copied, method='model-owned-native-cpu-copy', source='0x90bf0274', bytes=12, rc=0) and
                copied['tid'] == number(copied, 'receiver_tid') == receiver and
                number(copied, 'message_generation') == number(gate, 'unlock_event') < number(copied, 'receive_event') and
                max(source['index'], size['index']) < copied['index'] < received['index'] and fields(received, owned_copy=1))
            checks['free_ticket'] = (fields(ticket, owner='0x80020002', source='0x90bf0274', size=12, observed=1, state=2) and
                0 <= number(ticket, 'slot') < 8 and
                number(ticket, 'message_generation') == number(copied, 'message_generation') and
                number(ticket, 'receive_event') == number(copied, 'receive_event') and number(ticket, 'receiver_tid') == receiver and
                number(ticket, 'free_actor_tid') == ticket['tid'] == free_enter['tid'] == free_return['tid'] == freed['tid'] == number(freed, 'free_actor_tid') and
                (fields(free_enter, recv_match=1, source='0x90bf0274', source_known=1, size=12, size_known=1) or
                 fields(free_enter, recv_match=0, source=0, source_known=0, size=0, size_known=0)) and
                free_enter['fields']['recv_match'] == free_return['fields']['recv_match'] and
                free_enter['index'] < ticket['index'] < free_return['index'])
            checks['kernel_lease'] = all(number(r, 'message_generation') == number(gate, 'unlock_event') and
                number(r, 'lease_pid') == int(pid) and number(r, 'lease_generation') == result['generation'] and
                (not fields(r, received=1) or fields(r, owned_copy=1)) for r in snapshots if fields(r, allocated=1))
            checks['native_wait_return'] = (fields(waited, rc=0, wait_returned=1) and waited['tid'] == gate['tid'] and
                wait_enter['index'] < waited['index'] < wait_return['index'] < reader['index'])
            # Only the immutable pre-free ledger ticket can bind a cross-thread native return.
            if all(checks[key] for key in ('native_free', 'owned_copy', 'free_ticket', 'kernel_lease')):
                result.update(native_message_released=True, resource_safe_to_close=True, resource_proof='pre-free-generation-ticket-native-free-zero')
        result['native_content_verified'] = all(checks.values())
        result['business_complete'] = result['native_content_verified'] and not diagnostic_only
    except (ValueError, KeyError, TypeError, UnicodeError) as error:
        result['error'] = str(error)
    return result


def process_identity(pid):
    try:
        root = Path('/proc', str(pid))
        stat = (root / 'stat').read_text().rsplit(')', 1)[1].split()
        return dict(pid=pid, start_ticks=int(stat[19]), cmdline_sha256=hashlib.sha256((root / 'cmdline').read_bytes()).hexdigest())
    except (OSError, ValueError, IndexError) as error:
        return dict(pid=pid, identity_error=type(error).__name__ + ': ' + str(error))


def hold_functional_owner(owner, launch, terminal, result, output, handles):
    terminal.update(owner_retained=True, process_still_running=owner.poll() is None,
                    owner_identity=process_identity(owner.pid),
                    qmp_peer_identity=process_identity(terminal['qmp_peer_pid']) if terminal['qmp_peer_pid'] else None,
                    qmp_socket=launch['qmp_socket'], disk_lease_held=True)
    if 'fd' in launch:
        st = os.fstat(launch['fd'])
        terminal['disk_fd_identity'] = dict(fd=launch['fd'], dev=st.st_dev, ino=st.st_ino)
    result['owner'] = terminal
    save(output / 'owner-retained.json', dict(owner=terminal, error=result.get('error'),
        functional_trace=result.get('failure_functional_trace', result.get('functional_trace'))))
    save(output / 'result.json', result)
    peer_fd = None
    peer = terminal['qmp_peer_pid']
    if peer is not None:
        try:
            peer_fd = os.pidfd_open(peer)
        except ProcessLookupError:
            terminal['retained_peer_exited'] = True
        except OSError as caught:
            terminal['peer_pidfd_error'] = type(caught).__name__ + ': ' + str(caught)
    # Closing only our host connection lets the coordinator preserve this exact owner.
    for handle in handles:
        if handle is not None:
            try:
                handle.close()
            except OSError as caught:
                terminal.setdefault('host_connection_close_errors', []).append(type(caught).__name__ + ': ' + str(caught))
    while owner.poll() is None:
        try:
            owner.wait()
        except BaseException as caught:
            terminal.setdefault('retained_wait_errors', []).append(type(caught).__name__ + ': ' + str(caught))
            save(output / 'owner-retained-wait.json', terminal)
    if peer is not None:
        poller = select.poll()
        if peer_fd is not None:
            poller.register(peer_fd, select.POLLIN)
        try:
            while True:
                try:
                    if peer_fd is not None:
                        poller.poll()
                        terminal['retained_peer_exited'] = True
                        break
                    if not Path('/proc', str(peer)).exists():
                        terminal['retained_peer_exited'] = True
                        break
                    # A missing pidfd cannot justify releasing a live peer's disk lease.
                    time.sleep(.1)
                except BaseException as caught:
                    terminal.setdefault('retained_wait_errors', []).append(type(caught).__name__ + ': ' + str(caught))
                    save(output / 'owner-retained-wait.json', terminal)
        finally:
            if peer_fd is not None:
                os.close(peer_fd)
    save(output / 'external-owner-close.json', dict(owner_identity=terminal['owner_identity'],
        qmp_peer_identity=terminal['qmp_peer_identity'], peer_exited=terminal.get('retained_peer_exited'),
        returncode=owner.returncode, dispatch_success=False, qmp_quit_confirmed=False,
        external_quit_receipt_verified=False, signals_sent=[]))


def phase_bytes(data, phase, nonce):
    text = data.replace(b'\r', b'')
    begin = ('USB_AP_BEGIN_' + nonce + '_' + phase).encode()
    end = ('USB_AP_END_' + nonce + '_' + phase).encode()
    lines = text.splitlines(keepends=True)
    starts = [i for i, line in enumerate(lines) if line.rstrip(b'\n') == begin]
    stops = [i for i, line in enumerate(lines) if line.rstrip(b'\n') == end]
    if len(starts) > 1 or len(stops) > 1:
        raise ValueError('Duplicate original guest probe marker')
    if not starts or not stops:
        return None
    if stops[0] <= starts[0]:
        raise ValueError('Reversed original guest probe markers')
    return b''.join(lines[starts[0]:stops[0] + 1])


def inspect_phase(raw):
    text = raw.decode('utf-8', errors='replace')
    irqs = {}
    for match in re.finditer(r'^\s*(\d+):\s+((?:\d+\s+)+)GIC[^\n]*\b(vbus[01])\s*$', text, re.M):
        irqs[match[3]] = dict(linux_irq=int(match[1]), counts=[int(v) for v in match[2].split()])
    fields = re.findall(r'^USB_AP_UDC_FIELD=(\w+)\n(.*?)^USB_AP_FIELD_RC=(\d+)$', text, re.M | re.S)
    udc_uevents = [(value, rc) for name, value, rc in fields if name == 'uevent']
    bound = (re.findall(r'^USB_UDC_DRIVER=([^\n]+)$', udc_uevents[0][0], re.M)
             if len(udc_uevents) == 1 and udc_uevents[0][1] == '0' else [])
    uevents = re.findall(r'^USB_AP_GADGET_UEVENT\n(.*?)^USB_AP_GADGET_UEVENT_RC=(\d+)$', text, re.M | re.S)
    drivers = re.findall(r'^USB_AP_GADGET_DRIVER\n(.*?)^USB_AP_GADGET_DRIVER_RC=(\d+)$', text, re.M | re.S)
    if (len(uevents) == len(drivers) == 1 and uevents[0][1] == drivers[0][1] == '0' and
            re.findall(r'^DRIVER=([^\n]+)$', uevents[0][0], re.M) == ['usb_gadgetcore'] and
            re.fullmatch(r'(?:\.\./)+bus/gadget/drivers/usb_gadgetcore\n?', drivers[0][0]) is not None):
        if bound != ['usb_gadgetcore']:
            bound.append('usb_gadgetcore')
    fusb = re.findall(r'USB_AP_PROC=/proc/udm/fusb\n(.*?)^USB_AP_PROC_RC=(\d+)$', text, re.M | re.S)
    monitor = re.findall(r'^USB_AP_MONITOR_FIELD=([^\n]+)\n(.*?)^USB_AP_MONITOR_RC=(\d+)$', text, re.M | re.S)
    fds = re.findall(r'^USB_AP_FD=/proc/(\d+)/fd/(\d+):([^\n]+)$', text, re.M)
    power = {}
    for field, marker in (('value', 'USB_AP_SERVICE_POWER_CONTROL'),
                          ('path', 'USB_AP_SERVICE_POWER_CONTROL_PATH'),
                          ('filesystem', 'USB_AP_SERVICE_POWER_CONTROL_FS'),
                          ('udc_device', 'USB_AP_UDC_DEVICE_PATH'),
                          ('sysfs_mount', 'USB_AP_SERVICE_SYSFS_MOUNT'),
                          ('udc_class_link', 'USB_AP_UDC_CLASS_LINK')):
        rows = re.findall(r'^' + marker + r'\n(.*?)^' + marker + r'_RC=(\d+)$', text, re.M | re.S)
        power[field] = [dict(value=value.rstrip('\n'), rc=int(rc)) for value, rc in rows]
    return dict(irq=irqs, service_power_control=power, udc_fields={name: dict(value=value.rstrip('\n'), rc=int(rc)) for name, value, rc in fields},
                monitor_fields={name: dict(value=value.rstrip('\n'), rc=int(rc)) for name, value, rc in monitor},
                monitor_module_loaded=re.search(r'^usb_portMonitor\s+\d+\s+\d+\s', text, re.M) is not None,
                usb_fds=[dict(pid=int(pid), fd=int(fd), target=target) for pid, fd, target in fds],
                gadget_uevent_readbacks=[dict(raw=value, rc=int(rc)) for value, rc in uevents],
                gadget_driver_readbacks=[dict(raw=value, rc=int(rc)) for value, rc in drivers],
                bound_driver=bound[0] if len(bound) == 1 else None,
                fusb_proc=[dict(raw=value, rc=int(rc)) for value, rc in fusb],
                extcon_states=re.findall(r'^USB(?:_HOST)?=[01]$', text, re.M))


def service_pm_path_verified(phase):
    power = phase.get('service_power_control', {})
    link = '../../devices/platform/soc/f1080000.usbs/f10c0000.usb/udc/f10c0000.usb'
    mounts = power.get('sysfs_mount', [])
    return (power.get('value') == [dict(value='auto', rc=0)] and
            power.get('udc_class_link') == [dict(value=link, rc=0)] and
            len(mounts) == 1 and mounts[0]['rc'] == 0 and
            re.fullmatch(r'[^ ]+ /sys sysfs [^ ]+ 0 0', mounts[0]['value']) is not None)


def original_function_bound(phase):
    function = phase['udc_fields'].get('function', {})
    # Original g_core_driver.function and driver.name are both USBGADGETCORE_NAME.
    return (function.get('rc') == 0 and function.get('value') == 'usb_gadgetcore' and
            phase.get('bound_driver') == 'usb_gadgetcore')


def peer_pid(connection):
    pid, uid, _ = struct.unpack('3i', connection.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12))
    if pid < 2 or uid != os.getuid():
        raise ValueError('QMP owner PID/UID mismatch')
    return pid


async def bridge_request(context, present=None, *, descriptor_path=None):
    bridge = await protocol.Bridge.open(context, 'control')
    try:
        operation = 'describe' if present is None else 'vbus'
        response, payload = await bridge.ask(operation, **({} if present is None else {'present': present}))
        if present is not None and (payload or response.get('present') is not present):
            raise protocol.ProtocolError('VBUS response did not echo the applied signal')
        if present is None:
            if response.get('ready') is False:
                if payload or 'device' in response:
                    raise protocol.ProtocolError('Unready backend supplied descriptors')
            elif response.get('ready') is True:
                protocol.GuestDevice.parse(response.get('device'), payload)
            else:
                raise protocol.ProtocolError('Missing descriptor readiness')
        if descriptor_path is not None and payload:
            Path(descriptor_path).write_bytes(payload)
        return dict(response=response, payload_bytes=len(payload), payload_sha256=hashlib.sha256(payload).hexdigest())
    finally:
        await bridge.close()


def capture_native_observer_log(command, connection, launch, phase, expected_peer):
    """Read the native observer's private RAM log without changing guest state."""
    result = dict(diagnostic_only=True, atomic=False, resource_safe_to_close=False,
                  business_complete=False, raw_log_private=True, received=False,
                  physical=0x4102d0000, requested_bytes=65536, qmp_reply=None)
    fd = None
    try:
        if phase not in (*MSC_PHASES, 'failure'):
            raise ValueError('Invalid native observer snapshot phase')
        if command is None or connection is None:
            raise ValueError('No existing verified QMP connection')
        pid = peer_pid(connection)
        identity = process_identity(pid)
        if not isinstance(expected_peer, dict) or 'identity_error' in identity or identity != expected_peer:
            raise ValueError('Native observer snapshot QMP owner mismatch')
        result['qmp_peer_identity'] = identity
        run = Path(launch['qmp_socket']).parent
        if (not run.is_absolute() or run.resolve() != run or run.name != 'run' or run.parent.name != 'launch'
                or run.parts[1] in ('dev', 'proc', 'sys') or launch['qmp_socket'] != str(run / 'qmp.sock')
                or launch.get('qmp_parent') != str(run) or launch['env'].get('QEMU_OUTPUT_DIR') != str(run)):
            raise ValueError('Native observer snapshot requires this launch/run /out mapping')
        info = run.stat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o022:
            raise ValueError('Native observer snapshot run directory is not exclusively owned')
        target = run / (phase + '-native-observer-log.bin')
        result.update(path=str(target), qmp_path='/out/' + target.name)
        # Reserve only a fresh owned inode; QMP may truncate our empty reservation, never an old snapshot.
        fd = os.open(target, os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        result['qmp_arguments'] = dict(val=0x4102d0000, size=65536, filename=result['qmp_path'])
        reply = command('pmemsave', result['qmp_arguments'])
        result['qmp_reply'] = reply
        if reply != {'return': {}}:
            raise ValueError('Native observer pmemsave did not return the original empty success reply')
        result['qmp_succeeded'] = True
    except Exception as error:
        result['error'] = type(error).__name__ + ': ' + str(error)
    finally:
        if fd is not None:
            try:
                original = os.fstat(fd)
                current = os.stat(result['path'], follow_symlinks=False)
                if not stat.S_ISREG(current.st_mode) or (original.st_dev, original.st_ino) != (current.st_dev, current.st_ino):
                    raise ValueError('Native observer snapshot inode changed')
                result['file_bytes'] = original.st_size
                if original.st_size > 65536:
                    raise ValueError('Native observer snapshot exceeds the fixed 65536-byte readback bound')
                os.lseek(fd, 0, os.SEEK_SET)
                data = os.read(fd, 65537)
                result.update(bytes=len(data), sha256=hashlib.sha256(data).hexdigest())
                if result.get('qmp_succeeded') and len(data) == 65536:
                    result['received'] = True
                elif 'error' not in result:
                    result['error'] = 'Native observer snapshot is not exactly 65536 bytes'
            except Exception as error:
                result['readback_error'] = type(error).__name__ + ': ' + str(error)
            finally:
                os.close(fd)
    return result


def hardware_snapshot(command):
    return {hex(address): command('human-monitor-command', {'command-line': 'xp /1wx ' + hex(address)})['return']
            for address in REGISTERS}


async def descriptor_readback(context, output, *, timeout=6):
    attempts = []
    deadline = time.monotonic() + timeout
    while True:
        result = await bridge_request(context, descriptor_path=Path(output) / 'guest-ep0-descriptors.bin')
        attempts.append(result)
        if result['response'].get('ready') is True or time.monotonic() >= deadline:
            return dict(attempts=attempts, guest_ep0_bytes_verified=result['response'].get('ready') is True,
                        export_allowed=False)
        await asyncio.sleep(.2)


def execute(launch, cold, output, *, seconds=120, select_msc=False, observe_start=False,
            observer_mode_verified=None, observer_contract=None, host_version=False):
    if type(host_version) is not bool or (host_version and (not select_msc or not observe_start)):
        raise ValueError('Host version chain requires explicit original MSC/observer selection')
    if observe_start and observer_mode_verified is None:
        raise ValueError('Explicit validated observer mode/contract required by execute')
    actual_mode = observer_mode(observer_contract, observe_start=observe_start,
                                camera_profile=launch.get('camera_profile'), seconds=seconds)
    if observer_mode_verified not in (None, actual_mode):
        raise ValueError('Validated observer mode differs from execution contract')
    functional = actual_mode == FUNCTIONAL_MODE
    phases = MSC_PHASES if select_msc else PHASES
    output = Path(output)
    if hashlib.sha256(EXECUTOR_PATH.read_bytes()).hexdigest() != EXECUTOR_SHA256:
        raise ValueError('Boot collector changed after preparation; rebuild fresh probe')
    output.mkdir(mode=0o700)
    nonce = secrets.token_hex(12)
    console = output / 'console.log'
    terminal = dict(owner_pid=None, qmp_peer_pid=None, qmp_quit_confirmed=False,
                    signals_sent=[], returncode=None)
    result = dict(schema='a7c2.usb-ap-probe.v1', phases={}, bridge={}, hardware={},
                  observer_mode=actual_mode, functional_model=functional, strict_can_publish=0,
                  stage_actual=False, original_cp_history_verified=False,
                  physical_compatibility_verified=False, full_boot_verified=False, capture_verified=False,
                  msc_selection_requested=select_msc, descriptor_verified=False,
                  original_openSvc_return_observed=False, service_pm_path_verified=False,
                  physical_devices_used=False, export_allowed=False, host_enumerated=False,
                  authentication_verified=False, guest_root_over_usb_verified=False)
    owner = connection = stream = command = context = None
    sent = None
    next_phase = 0
    ready_at = None
    error = None
    resource_safe = not functional
    host_owner_safe = True
    model_trace_proof = None
    model_trace_phase = None
    with console.open('xb') as log:
        try:
            owner = subprocess.Popen(['/bin/bash', '-c', '"$@" <&0 & child=$!; wait "$child"',
                                      'usb-ap-owner', *launch['command']], env=launch['env'],
                                     stdin=subprocess.PIPE, stdout=log, stderr=subprocess.STDOUT,
                                     start_new_session=True, pass_fds=launch.get('pass_fds', ()))
            launch['children'].append(owner)
            terminal['owner_pid'] = owner.pid
            save(output / 'owner-start.json', terminal)
            started = time.monotonic()
            while owner.poll() is None and time.monotonic() - started < seconds:
                if command is None and Path(launch['qmp_socket']).is_socket():
                    connection, stream, command = EXECUTOR['qmp_connect'](launch['qmp_socket'])
                    terminal['qmp_peer_pid'] = peer_pid(connection)
                    terminal['qmp_peer_identity'] = process_identity(terminal['qmp_peer_pid'])
                    context = protocol.Context.create(Path(launch['qmp_socket']).parent, launch['qmp_socket'],
                        Path(launch['qmp_socket']).with_name('usb-endpoint.sock'),
                        launch['env']['QEMU_SONY_USB_LEASE'], terminal['qmp_peer_pid'])
                    save(output / 'owner-start.json', terminal)
                data = console.read_bytes()
                if any(marker in data for marker in (b'Kernel panic - not syncing:', b'Entering exception monitor',
                        b'COLD_BOOTSTRAP_FAILED ', b'PERSISTENT_BOOTSTRAP_FAILED ', b'PERSISTENT_BOOTIN_BIND_FAILED_SHA',
                        b'USB_START_GUARD_FAILED reason=')):
                    raise RuntimeError('Original guest failure; preserve raw console and owner')
                ap_ready = (re.search(rb'OBS CREATE_SCREEN_ARGS [^\r\n]* id=0 count=565 ', data) is not None
                            and b'OBS OSD_HEADLESS_PERSISTED ' in data and (b'/ #' in data or b'~ #' in data))
                if ap_ready and ready_at is None:
                    ready_at = time.monotonic() + 2
                if sent is not None:
                    raw = phase_bytes(data, sent, nonce)
                    if raw is not None:
                        (output / (sent + '.log')).write_bytes(raw)
                        result['phases'][sent] = inspect_phase(raw)
                        if observe_start:
                            snapshot = capture_native_observer_log(command, connection, launch, sent,
                                                                   terminal.get('qmp_peer_identity'))
                            result.setdefault('native_observer_logs', {})[sent] = snapshot
                            save(output / (sent + '-native-observer-log.json'), snapshot)
                            observed = start_trace_summary(raw)
                            result['phases'][sent]['start_trace'] = observed
                            result['start_trace'] = observed
                            result['original_openSvc_return_observed'] = bool(observed.get('openSvc_returns'))
                            if functional:
                                candidate = raw if b'FULL_TOUCH_PANEL_REQUEST ' in raw and b'FULL_TOUCH_PANEL_REPLY_FREE ' in raw else None
                                summary = functional_trace_summary(raw, observer_contract,
                                    virtual_backend_trace=candidate or model_trace_proof)
                                if candidate is not None and summary['resource_trace'].get('virtual_backend_touch_rpc_complete') is True:
                                    model_trace_proof, model_trace_phase = candidate, sent
                                summary['virtual_backend_proof_phase'] = model_trace_phase
                                result['phases'][sent]['functional_trace'] = summary
                                result['functional_trace'] = summary
                                resource_safe = summary['resource_safe_to_close']
                            if not observed['installed_before_init'] or not observed.get('app_taps_preinit'):
                                raise RuntimeError('Passive USB/AP observer was not installed before original Init')
                        result['hardware'][sent]['after'] = hardware_snapshot(command)
                        result['bridge'][sent + '_describe'] = asyncio.run(bridge_request(context))
                        command('screendump', {'filename': '/out/usb-ap-' + sent + '.ppm'})
                        if sent == 'msc_selected':
                            result['descriptor'] = asyncio.run(descriptor_readback(context, output))
                            result['descriptor_verified'] = result['descriptor']['guest_ep0_bytes_verified']
                            if host_version:
                                original = dict(original_function_bound=original_function_bound(result['phases'][sent]),
                                                descriptor_verified=result['descriptor_verified'])
                                if (not all(original.values()) or
                                        result.get('start_trace', {}).get('start_syscall_actual_zero') is not True):
                                    raise RuntimeError('Original function/EP0/START was not verified; host chain refused')
                                if os.path.lexists(context.run_dir / 'usb-context.json'):
                                    raise RuntimeError('Host context must be fresh for this owned run')
                                protocol.write_owned_json(context.run_dir / 'usb-context.json', dict(
                                    run_id=context.run_id, qmp_path=str(context.qmp_path),
                                    backend_path=str(context.backend_path), lease=context.lease, vm_pid=context.vm_pid))
                                host_owner_safe = False
                                host_result = runpy.run_path(str(HERE / 'usb-full-chain.py'))['run'](context.run_dir, original)
                                result['host_chain'] = host_result
                                result['host_enumerated'] = host_result.get('host_enumerated') is True
                                result['authentication_verified'] = host_result.get('authentication_verified') is True
                                host_owner_safe = host_result.get('host_resources_released') is True
                                if host_result.get('phase') != 'complete' or not host_owner_safe:
                                    raise RuntimeError('Read-only host USB chain failed; retain original evidence')
                        sent = None
                        next_phase += 1
                        if next_phase == len(phases):
                            break
                        if phases[next_phase] in ('vbus_on', 'vbus_off'):
                            present = phases[next_phase] == 'vbus_on'
                            result['bridge'][phases[next_phase] + '_request'] = asyncio.run(bridge_request(context, present))
                        ready_at = time.monotonic() + 2
                        save(output / 'probe-progress.json', result)
                if sent is None and ready_at is not None and time.monotonic() >= ready_at and command is not None:
                    sent = phases[next_phase]
                    result['hardware'][sent] = {'before': hardware_snapshot(command)}
                    script = capture_script(sent, nonce, observe_start=observe_start)
                    (output / (sent + '.sh')).write_text(script, encoding='ascii')
                    wire = EXECUTOR['diagnostic_envelope'](script, 'USB_AP_SCRIPT_' + nonce + '_' + sent)
                    EXECUTOR['write_console'](owner.stdin, wire.encode('ascii'))
                time.sleep(.1)
            if len(result['phases']) != len(phases):
                raise RuntimeError('Original AP probe timed out or owner exited before all phase readbacks')
            if functional and not result.get('functional_trace', {}).get('business_complete'):
                raise RuntimeError('Functional EE native allocation/content/reader/free chain did not complete')
        except BaseException as caught:
            error = caught
            result['error'] = type(caught).__name__ + ': ' + str(caught)
            if observe_start:
                snapshot = capture_native_observer_log(command, connection, launch, 'failure',
                                                       terminal.get('qmp_peer_identity'))
                result.setdefault('native_observer_logs', {})['failure'] = snapshot
                save(output / 'failure-native-observer-log.json', snapshot)
                diagnostic = result['failure_observer_capture'] = capture_failure_observer(owner, console, output)
                if functional:
                    # A prior positive free is durable; an old empty trace is not a new no-allocation proof.
                    resource_safe = result.get('functional_trace', {}).get('native_message_released', False)
                    if diagnostic['received']:
                        try:
                            summary = functional_trace_summary(Path(diagnostic['path']).read_bytes(), observer_contract,
                                diagnostic_only=True, virtual_backend_trace=model_trace_proof)
                            summary['virtual_backend_proof_phase'] = model_trace_phase
                            result['failure_functional_trace'] = summary
                            resource_safe = summary['resource_safe_to_close']
                        except Exception as caught:
                            result['failure_functional_trace_error'] = type(caught).__name__ + ': ' + str(caught)
        finally:
            try:
                if owner is not None and (owner.poll() is None or ((not host_owner_safe or functional and not resource_safe) and
                        terminal['qmp_peer_pid'] is not None and Path('/proc', str(terminal['qmp_peer_pid'])).exists())):
                    if not host_owner_safe or (functional and not resource_safe):
                        result['console_sha256'] = hashlib.sha256(console.read_bytes()).hexdigest()
                        result['complete_readbacks'] = len(result['phases']) == len(phases)
                        hold_functional_owner(owner, launch, terminal, result, output, (stream, connection))
                        stream = connection = command = None
                    elif command is None:
                        connection, stream, command = EXECUTOR['qmp_connect'](launch['qmp_socket'])
                        terminal['qmp_peer_pid'] = peer_pid(connection)
                    if terminal.get('owner_retained'):
                        pass
                    elif context is not None:
                        # Request real removal even if the ON phase failed; no export was admitted.
                        try:
                            result['bridge']['cleanup_vbus_off'] = asyncio.run(bridge_request(context, False))
                        except Exception as caught:
                            result['cleanup_vbus_error'] = type(caught).__name__ + ': ' + str(caught)
                    if not terminal.get('owner_retained'):
                        save(output / 'qmp-quit.json', command('quit'))
                        terminal['qmp_quit_confirmed'] = True
                        owner.wait(timeout=30)
            except BaseException as caught:
                terminal['cleanup_error'] = type(caught).__name__ + ': ' + str(caught)
                error = error or caught
            finally:
                terminal['process_still_running'] = owner is not None and owner.poll() is None
                terminal['returncode'] = owner.returncode if owner is not None else None
                terminal['qmp_peer_proc_present_after_wait'] = (Path('/proc', str(terminal['qmp_peer_pid'])).exists()
                    if terminal['qmp_peer_pid'] is not None else None)
                if owner is not None and not terminal['process_still_running']:
                    owner.stdin.close()
                for handle in (stream, connection):
                    if handle is not None:
                        handle.close()
                result['owner'] = terminal
                if terminal['process_still_running']:
                    save(output / 'owner-retained.json', terminal)
                save(output / 'owner-exit.json', terminal)
                result['console_sha256'] = hashlib.sha256(console.read_bytes()).hexdigest()
                result['complete_readbacks'] = len(result['phases']) == len(phases)
                result['service_pm_path_verified'] = any(service_pm_path_verified(phase)
                    for phase in result['phases'].values())
                result['original_function_bound'] = any(original_function_bound(phase)
                    for phase in result['phases'].values())
                result['vbus_irq_increased'] = False
                if result['complete_readbacks']:
                    values = [result['phases'][phase]['irq'].get('vbus0') for phase in PHASES]
                    if all(values):
                        counts = [sum(value['counts']) for value in values]
                        result['vbus_irq_counts'] = counts
                        result['vbus_irq_increased'] = counts[0] < counts[1] < counts[2]
                save(output / 'result.json', result)
    receipt = EXECUTOR['new_receipt']('original-init-cold', bindings={
        'run': output.name, 'source_class': cold['source'], 'ram0_sha256': cold['ram0_sha256'],
        'script_identity': cold['script_identity'], 'launch_script_sha256': launch['script_sha256'],
        'dtb_sha256': launch['dtb_sha256']}, kernel_cmdline=launch['cmdline'])
    save(output / 'boot-flow.json', dict(receipt=receipt, coverage=EXECUTOR['collect'](console, receipt)))
    if error is not None:
        raise RuntimeError('USB AP probe failed; original evidence at ' + str(output)) from error
    return result


def main(argv=None, *, camera_profile='virtual-functional-camera-v1', select_msc=False, observe_start=False,
         host_version=False):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--instance', type=Path, required=True, help='independent exclusively leased local probe instance')
    parser.add_argument('--runtime', type=Path, required=True, help='existing functional helper runtime, without rebuilding partition images')
    parser.add_argument('--module', type=Path, required=True)
    parser.add_argument('--qemu-build', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--seconds', type=int, default=120)
    args = parser.parse_args(argv)
    if not 10 <= args.seconds <= 3600:
        parser.error('--seconds must be 10..3600')
    try:
        mode, observer, observer_bindings = verified_observer(args.runtime / 'analysis', observe_start=observe_start,
            camera_profile=camera_profile, seconds=args.seconds)
    except ValueError as error:
        parser.error(str(error))
    output = Path(os.path.abspath(args.output))
    if os.path.lexists(output):
        raise ValueError('Probe output must be fresh')
    output.mkdir(mode=0o700)
    save(output / 'probe-source.json', dict(path=str(Path(__file__).resolve()),
        sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        provider_sha256=hashlib.sha256(USB['PLATFORM_C'].encode()).hexdigest(),
        collector_sha256=EXECUTOR_SHA256,
        raw_logs_private=True, measurement_completion_is_usb_success=False))
    if observe_start:
        start = runpy.run_path(str(HERE / 'usb-start-observe.py'))
        if camera_profile != start['PROFILE']:
            raise ValueError('Passive original USB observer requires its explicit service profile')
        cold = start['build_cold'](PERSISTENT, args.instance, args.runtime / 'analysis', output / 'cold-chain', module=args.module)
    else:
        cold = PERSISTENT['build'](args.instance, args.runtime / 'analysis', output / 'cold-chain', module=args.module)
    launch = PERSISTENT['prepare_launch'](args.runtime / 'analysis', cold, output / 'launch',
        qemu_build=args.qemu_build, camera_profile=camera_profile)
    diagnostics = bool(observer and observer.get('ee_normal_cold', {}).get('diagnostic_checkpoints') is True)
    launch = USB['prepare_launch'](launch, lease=secrets.token_hex(32),
                                  **({'observe_generation': True} if diagnostics else {}))
    launch['template_inputs'].extend(observer_bindings)
    if host_version:
        launch['template_inputs'].extend(PERSISTENT['COLD']['binding'](HERE/name,'host-usb-readonly-source')
            for name in ('usb-full-chain.py','usb_control.py','usb_jiritsu.py','usb-gadget/usbip_server.py'))
    save(output / 'launch.json', dict(launch, env={key: value for key, value in launch['env'].items()
                                                if key != 'QEMU_SONY_USB_LEASE'}))
    with PERSISTENT['leased_launch'](launch) as bound:
        result = execute(bound, cold, output / 'evidence', seconds=args.seconds, select_msc=select_msc,
                         observe_start=observe_start, observer_mode_verified=mode, observer_contract=observer,
                         **({'host_version': True} if host_version else {}))
        p15 = next(row for row in cold['partition_bindings'] if row['id'] == 'nflasha15')
        after = PERSISTENT['DISK']['hashed'](bound['fd'], p15['offset'], p15['bytes'])
        result['p15_readback'] = dict(before_sha256=p15['sha256'], after_sha256=after,
                                     unchanged=after == p15['sha256'])
        save(output / 'evidence/result.json', result)
    print(json.dumps(result, indent=2))
    if select_msc and not (result['original_function_bound'] and result['descriptor_verified'] and
                           (not observe_start or result.get('start_trace', {}).get('start_syscall_actual_zero') is True)):
        return 1
    return 0 if result['complete_readbacks'] and result['owner']['returncode'] == 0 else 2


if __name__ == '__main__':
    raise SystemExit(main())
