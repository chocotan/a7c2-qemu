#!/usr/bin/env python3
"""Define original AppFw read-only sampler fields and validate its framed output."""
import re

# ELF VAs, resolved by menu-readmem against the module's offset-zero mapping.
FIELDS = {
    'system_mode': (0x7e5d428, 4),
    'system_mode_option': (0x7e5d498, 4),
    'mode_transition': (0x7e67fc8, 4),
    'ee_status': (0x7e67700, 4),
    'capture_inhibit': (0x83337e3, 1),
    'capture_inhibit_count': (0x7e1c00c, 4),
    'focus_mode': (0x7e706c0, 4),
}

# Main-session instruction checks: u32 scalar getters and HAITA engine +8 slot.
SOURCE_FIELDS = {
    'usb_streaming_mode': (0x7eddbc8, 4),
    'network_streaming_mode': (0x7e71a70, 4),
    'lens_retracted_status': (0x7e59cf0, 4),
    'focus_init_error': (0x7e67478, 4),
    'zoom_init_error': (0x7e67498, 4),
    'built_in_steady_shot_error': (0x7e5bc18, 4),
    'date_time_set_status': (0x7e5df40, 4),
    'two_slot_still_recording_inhibit': (0x7eae2b0, 4),
    'setting_release_wo_card': (0x7e6f2c8, 4),
    'haita_release_without_lens': (0x7e35440, 4),
    'haita_steady_shot_self_timer': (0x7e400d8, 4),
    'haita_release_without_media': (0x7e411d0, 4),
    'haita_recording_destination': (0x7e426e8, 4),
}

# Destination/volume models differ from the media_mount_state model enums.
DESTINATION_FIELDS = {
    'remote_still_save_destination': (0x7e71570, 4),
    'pc_remote_connection_state': (0x7e81ef0, 4),
    'general_shooting_mode': (0x7e81af0, 4),
    'control_with_smartphone_state': (0x7e5c478, 4),
    'setting_relay_rec': (0x7e6e810, 4),
    'setting_still_recording_media': (0x7e6e7c8, 4),
    'media_mount_state_slot1': (0x7e80dd0, 4),
    'media_mount_state_slot2': (0x7e80df0, 4),
    'media_filesystem_mount_state_slot1': (0x7e81470, 4),
    'media_filesystem_mount_state_slot2': (0x7e81490, 4),
    'haita_smartphone_save': (0x7e411b8, 4),
    'haita_pc_save': (0x7e408e8, 4),
    'haita_recordable_slot1': (0x7e426b8, 4),
    'haita_recordable_slot2': (0x7e426d0, 4),
}

CONTEXT_END_FIELDS = {
    'system_mode_end': FIELDS['system_mode'],
    'system_mode_option_end': FIELDS['system_mode_option'],
    'mode_transition_end': FIELDS['mode_transition'],
}


def field_header():
    rows=[]
    for scope,fields in ((0,FIELDS),(1,SOURCE_FIELDS),(2,DESTINATION_FIELDS),(0,CONTEXT_END_FIELDS)):
        for name,(address,size) in fields.items():
            rows.append(f'    {{"{name}",{address:#x}UL,{size},{scope}}},')
    return ('/* Generated from capture-gates.py; ELF VAs, not file offsets. */\n'
            'static const struct gate_field gate_fields[]={\n'+'\n'.join(rows)+'\n};\n')


def still_capture_context(snapshot):
    if not snapshot.get('verified'):return False
    fields=snapshot.get('fields',{})
    return all(fields.get(name,{}).get('value')==value and
               fields.get(name+'_end',{}).get('value')==value for name,value in
               (('system_mode',2),('system_mode_option',0),('mode_transition',0)))


def command(include_sources=False,include_destination=False):
    scope=2 if include_destination else 1 if include_sources else 0
    lines = ['set -- $(busybox pidof im.elf)', 'if [ "$#" = 1 ]', 'then',
             f'/simulation/capture-gates-reader "$1" {scope}',
             'else', 'echo CAPTURE_GATE_AMBIGUOUS_PROCESS', 'false', 'fi']
    return '\n'.join(lines)


def parse(text,include_sources=False,include_destination=False,include_context_end=None):
    """Accept only complete, unambiguous, correctly sized helper readbacks."""
    result = {}
    fields={**FIELDS,**SOURCE_FIELDS} if include_sources or include_destination else FIELDS
    if include_destination:fields={**fields,**DESTINATION_FIELDS}
    if include_context_end is None:
        include_context_end=bool(re.search(r'^CAPTURE_GATE_BEGIN_(?:system_mode|system_mode_option|mode_transition)_end\r?$',text,re.M))
    if include_context_end:fields={**fields,**CONTEXT_END_FIELDS}
    for name, (_, size) in fields.items():
        blocks = re.findall(rf'(?m)^CAPTURE_GATE_BEGIN_{name}\r?$\n(.*?)'
                            rf'^CAPTURE_GATE_END_{name}\r?$', text, re.S | re.M)
        values = set()
        for block in blocks:
            records = re.findall(r'READMEM /proc/(\d+)/mem address=([0-9a-f]+) bytes=(\d+)', block)
            rows = re.findall(r'(?m)^([0-9a-f]{16}):((?: [0-9a-f]{2})+)\r?$', block)
            if len(records) != 1 or len(rows) != 1:
                continue
            pid, address, actual = records[0]
            row_address, raw = rows[0]
            data = bytes.fromhex(raw)
            if int(actual) == size == len(data) and int(address, 16) == int(row_address, 16):
                values.add((int(pid), int(address, 16), int.from_bytes(data, 'little')))
        if len(values) != 1:
            raise ValueError(f'capture gate {name}: missing, corrupt or conflicting readback')
        pid, address, value = values.pop()
        result[name] = {'pid': pid, 'address': hex(address), 'value': value, 'bytes': size}
    if len({field['pid'] for field in result.values()}) != 1:
        raise ValueError('capture gates belong to different processes')
    if len({int(field['address'],16)-fields[name][0] for name,field in result.items()}) != 1:
        raise ValueError('capture gate addresses do not share one AppFw load bias')
    return result
