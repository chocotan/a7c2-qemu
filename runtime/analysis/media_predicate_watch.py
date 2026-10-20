"""Passive original caution predicate tracing, invoked inside owned QEMU GDB.

Only hardware execution breakpoints and memory/register reads. No guest calls,
register writes, software breakpoints or selection/state changes.
"""
import json
from pathlib import Path
import struct
import time

# Entry and post-MOV w0 return sites, each before the original frame is popped.
POINTS = ((0x1875afc, 0x1875b34), (0x1875c9c, 0x1875ce4))
FIELDS = {'still_live': 0x7e6e7f0, 'movie_live': 0x7e6e810,
          'mount_1': 0x7e80dd0, 'mount_2': 0x7e80df0,
          'getter_286cfc8': 0x7e73770, 'getter_2879804': 0x7e81af0}
# Address getters for every field read by the rule that actually fired in
# run-neprf92x (predicate 0x187f130, index 0x223). Labels keep original getter
# VAs: capacity/full/time semantics are NOT established by these reads.
# Resolved property names (dispatch id -> name array at 0x57f99a0):
#   0x804 -> PRM_setting_release_wo_card                  (0x7e73770, in FIELDS)
#   0xf38 -> PRM_still_temperature_level                  (0x7e81af0, in FIELDS)
#   0xef0 -> PRM_HAITA_system_mode_setting_shooting_touch_function
#   0xf06 -> PRM_setting_focus_position_during_touch_operation
#   0xefe -> PRM_HAITA_breathing_correction_lens_type_lens_information
#   0x705 -> _INFRA_PIN_ATOM(IMAGING, RAW, OUT, 0)
#   0x70b -> _INFRA_PIN_ATOM(INFRABB, RAW, OUT, 0)
#   0x1bf4 -> VAL_license_state_LICENSE_STATE_CONFIRMED
# Slots 0x59e/0x59f/0x5a0/0x5c1 hold runtime-filled names, so their meaning
# stays open. An earlier revision of this table listed HAITA/face-AF/HDMI cells
# that this predicate never reads; they are replaced, not merely renamed.
CAPACITY_FIELDS = {'getter_2878cc8': 0x7e811b0, 'getter_2879038': 0x7e81470,
                   'getter_2878ef8': 0x7e81370, 'getter_2867644': 0x7e6e7c8,
                   'getter_288badc': 0x7eddbc8, 'getter_286ae5c': 0x7e71a70,
                   'getter_2867bbc': 0x7e6ecc8, 'getter_286af4c': 0x7e71b50}
# Named original media state cells (property id -> the address its row's getter
# at +0x08 reads). Dispatch rows live in the second PT_LOAD segment, where
# VA = file offset + 0x10000, so rows must be read through the segment map.
# Row layout: +0x00 supported predicate, +0x08 getter, +0x10/+0x18 setters that
# write additional shadow cells.
# An earlier revision of this table used addresses decoded without that segment
# mapping (0x7ead84c and friends); those readings were meaningless and are void.
MEDIA_STATE_FIELDS = {'prm_102d_movie_recordable_slot1': 0x7e83b28,
                      'prm_102e_movie_recordable_slot2': 0x7e83b48,
                      'prm_09e1_media_mount_state_slot1': 0x7e78900,
                      'prm_09e4_media_mount_state_slot2': 0x7e78960,
                      'prm_0a13_filesystem_mount_state_slot1': 0x7e78f40,
                      'prm_0a17_filesystem_mount_state_slot2': 0x7e78fc0,
                      'prm_1052_remaining_capacity_slot1': 0x7e84078,
                      'prm_138e_recordable_movie_slot1': 0x7e8a268,
                      'prm_09f5_full_state_still_slot1': 0x7e78b80,
                      'prm_0a18_full_state_movie_slot1': 0x7e78fe0,
                      'prm_0a20_setting_still_recording_media': 0x7e790e0,
                      'prm_0a3a_setting_movie_recording_media': 0x7e79450}
ENTRY_PREFIX = bytes.fromhex('fd7bbda9fd030091')
POLICY_POINT = (0x18831f4, 0x188331c)
POLICY_PREFIX = bytes.fromhex('fd7bb9a9fd030091')
TABLE_VA, TABLE_COUNT = 0x58f03a8, 876


def selected_record(inferior, base, index):
    """Decode the selected original record, not a string namespace conversion."""
    if index == 0xffff:
        return None
    if not 0 <= index < TABLE_COUNT:
        raise ValueError('Selected original rule index out of bounds')
    if int.from_bytes(bytes(inferior.read_memory(base+0x37766b0, 8)), 'little') != TABLE_COUNT:
        raise ValueError('Original rule count mismatch')
    if int.from_bytes(bytes(inferior.read_memory(base+0x5ba52f8, 8)), 'little') != base+TABLE_VA:
        raise ValueError('Original relocated rule table mismatch')
    address = base+TABLE_VA+index*0xa0
    raw = bytes(inferior.read_memory(address, 0x58))
    predicate, message = struct.unpack_from('<Q', raw, 0x10)[0], struct.unpack_from('<Q', raw, 0x38)[0]
    alternate = struct.unpack_from('<Q', raw, 0x48)[0]
    selector, alternate_selector = struct.unpack_from('<Q', raw, 0x40)[0], struct.unpack_from('<Q', raw, 0x50)[0]

    def first_id(pointer):
        if not pointer:
            return None
        if not base+0x3700000 <= pointer < base+0x51a7700:
            raise ValueError('Rule message list outside pinned original rodata')
        return int.from_bytes(bytes(inferior.read_memory(pointer, 4)), 'little')

    return dict(index=index, record_va=hex(address-base), predicate_va=hex(predicate-base),
                message_list_va=hex(message-base) if message else None, first_message_id=first_id(message),
                alternate_message_list_va=hex(alternate-base) if alternate else None,
                alternate_first_message_id=first_id(alternate),
                message_selector_va=hex(selector-base) if selector else None,
                alternate_selector_va=hex(alternate_selector-base) if alternate_selector else None,
                policy_byte=raw[0x28], priority=struct.unpack_from('<H', raw, 0x2a)[0],
                target_word=struct.unpack_from('<I', raw, 0x2c)[0])


def frame_key(entry, stack, returning=False, frame_bytes=0x30):
    return entry, stack + (frame_bytes if returning else 0)


def observation_error(run, returncode):
    """Host result gate, separate from QMP/SD safety and resource retention."""
    try:
        path = Path(run)/'media-predicate-result.json'
        if path.is_symlink() or path.stat().st_size > 16384:
            raise ValueError('Invalid media result file')
        result = json.loads(path.read_text())
        if not isinstance(result, dict):
            raise ValueError('Media result must be an object')
        if returncode != 0 or result.get('connected') is not True:
            raise ValueError('Media debugger did not complete normally')
        if result.get('error') or result.get('cleanup_errors'):
            raise ValueError(str(result))
    except (OSError, ValueError, TypeError) as error:
        return str(error)
    return None


def gdb_main(config):
    import gdb
    from request_queue_watch import revalidate_gdb_config
    fd, actual = revalidate_gdb_config(config)
    root = Path(actual['run'])
    base = actual['app_base']
    policy = actual['trace_mode'] == 'media-policy'
    sites = (POLICY_POINT,) if policy else POINTS
    frame_bytes = 0x70 if policy else 0x30
    points = []
    pending = {}
    stream = None
    count = 0
    last_signal = []
    result = {'scope': 'passive original predicates, not capture proof',
              'capture_verified': False, 'connected': False, 'events': 0,
              'error': None, 'limit_reached': False}

    def emit(event):
        nonlocal count
        stream.write(json.dumps(event, sort_keys=True)+'\n')
        stream.flush()
        count += 1
        result['events'] = count

    def reg(name):
        return int(gdb.parse_and_eval('$'+name))

    def stopped(event):
        value = getattr(event, 'stop_signal', None)
        if value:
            last_signal.append(value)

    class Observe(gdb.Breakpoint):
        def __init__(self, entry, pc, returning):
            super().__init__('*'+hex(base+pc), type=gdb.BP_HARDWARE_BREAKPOINT, internal=True)
            self.entry = entry
            self.returning = returning

        def stop(self):
            try:
                if count >= 128:
                    result['limit_reached'] = True
                    for point in points:
                        point.enabled = False
                    emit({'kind': 'limit', 'coverage': 'truncated after128 events'})
                    return False
                sp = reg('sp')
                key = frame_key(self.entry, sp, self.returning, frame_bytes)
                if self.returning:
                    call = pending.pop(key, None)
                    event = {'kind': 'return', 'predicate_va': hex(self.entry),
                             'sp': hex(sp), 'original_w0': reg('w0'),
                             'entry': call, 'matched_entry': call is not None,
                             'host_monotonic_ns': time.monotonic_ns()}
                    if policy:
                        event['selected_record'] = selected_record(gdb.selected_inferior(), base, reg('w0'))
                    emit(event)
                else:
                    inf = gdb.selected_inferior()
                    observed_fields = ({**FIELDS, **CAPACITY_FIELDS, **MEDIA_STATE_FIELDS}
                                       if policy else FIELDS)
                    values = {label: int.from_bytes(bytes(inf.read_memory(base+va, 4)), 'little')
                              for label, va in observed_fields.items()}
                    call = {'kind': 'entry', 'predicate_va': hex(self.entry),
                            'sp': hex(sp), 'caller_va': hex(reg('x30')-base),
                            'fields': values, 'host_monotonic_ns': time.monotonic_ns()}
                    if key in pending:
                        raise RuntimeError('Ambiguous nested predicate stack identity')
                    pending[key] = call
                    emit(call)
            except Exception as error:
                result['error'] = str(error)
                return True
            return False

    try:
        stream = (root/'media-predicate-events.jsonl').open('x')
        gdb.execute('target remote '+actual['socket'], to_string=True)
        result['connected'] = True
        gdb.events.stop.connect(stopped)
        inferior = gdb.selected_inferior()
        for entry, returning in sites:
            if bytes(inferior.read_memory(base+entry, 8)) != (POLICY_PREFIX if policy else ENTRY_PREFIX):
                raise ValueError('Original predicate entry instruction mismatch')
            for pc, is_return in ((entry, False), (returning, True)):
                point = Observe(entry, pc, is_return)
                if point.type != gdb.BP_HARDWARE_BREAKPOINT:
                    raise RuntimeError('Hardware predicate breakpoint required')
                points.append(point)
        (root/'queue-watch-ready.json').write_text(json.dumps(
            {'connected': True, 'media_predicate_hardware_only': True}))
        gdb.execute('continue', to_string=True)
        if last_signal and last_signal[-1] == 'SIGINT':
            result['interrupted_for_cleanup'] = True
        elif result['error'] is None:
            result['error'] = 'Unexpected GDB stop outside predicate callbacks'
    except KeyboardInterrupt:
        result['interrupted_for_cleanup'] = True
    except Exception as error:
        result['error'] = str(error)
    finally:
        import os
        cleanup_errors = []
        if result['connected']:
            try:
                gdb.events.stop.disconnect(stopped)
            except Exception as error:
                cleanup_errors.append(str(error))
        for point in points:
            try:
                point.delete()
            except Exception as error:
                cleanup_errors.append(str(error))
        try:
            if result['connected']:
                gdb.execute('detach', to_string=True)
        except Exception as error:
            cleanup_errors.append(str(error))
        if stream is not None:
            stream.close()
        result['unreturned_entries'] = len(pending)
        result['cleanup_errors'] = cleanup_errors
        (root/'media-predicate-result.json').write_text(json.dumps(result, indent=2))
        os.close(fd)
