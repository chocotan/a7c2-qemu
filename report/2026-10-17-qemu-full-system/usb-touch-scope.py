#!/usr/bin/env python3
"""Source-bound opt-in to finite USB touch / inactive TCIN providers.

No launch, disk, CP3007, UDATE, sequence/promise changes or menu registration.
"""
import hashlib
from pathlib import Path
import re

HERE = Path(__file__).resolve().parent
MODEL_ROOT = HERE.parents[1] / 'runtime/analysis/device-models'
PROFILE = 'virtual-config-v1'
TCIN_PROFILE = 'virtual-config-tcin-inactive-v1'
ASSETS = {
    'ap': (99960744, '2ea02f7ecbc5bb917316fe8ef4ce5ffd87eb66efaae78ba2ce11420552df539b'),
    'cp': (18090880, 'f5a477588698ef965748903b8959a39ce4f59ffd4aee4d4234ef1670f56a1428'),
}
MODELS = {
    'touch-panel-device.c': (10396, 'f6f229243566cc0e7228a7454d68495aa6012a60e8018b7b84243d93ebc178a9'),
    'touch-panel-device.h': (1509, '1a1a60c4592295dcd8805e0064c2780ce015125c6e3cbee48fe9886c6eb28000'),
    'imaging-device.h': (5392, '761f4ab03eb89e57ac2aea2e46beb41d80e269f44fe1c17e30e9a3c98d5e013a'),
}
TCIN_MODELS = {
    'tcin-device.c': (9941, '898b3378e91af94c1653f77e87857fb696914c145532112b3539f6d5189a2cee'),
    'tcin-device.h': (1104, '5c6cf780d703463a8866f1e296bce8e0395aa53bd65ba5864a9d2311b75931ea'),
}


def binding(path, expected):
    path = Path(path).absolute()
    if any(p.is_symlink() for p in (path, *path.parents)) or not path.is_file():
        raise ValueError('USB touch requires ordinary read-only source assets: '+str(path))
    with path.open('rb') as stream:
        digest = hashlib.file_digest(stream, 'sha256').hexdigest()
    if (path.stat().st_size, digest) != expected:
        raise ValueError('USB touch original/source asset identity drift: '+str(path))
    return {'path': str(path), 'bytes': expected[0], 'sha256': digest}


def prepare(profile=None, ap=None, cp=None):
    if profile is None:
        if ap is not None or cp is not None:
            raise ValueError('USB touch assets require an explicit profile')
        return None
    if profile not in (PROFILE, TCIN_PROFILE) or ap is None or cp is None:
        raise ValueError('USB touch requires an explicit supported profile and original AP/CP assets')
    assets = {'ap': binding(ap, ASSETS['ap']), 'cp': binding(cp, ASSETS['cp'])}
    selected = {**MODELS, **(TCIN_MODELS if profile == TCIN_PROFILE else {})}
    models = {name: binding(MODEL_ROOT/name, pin) for name, pin in selected.items()}
    # Both translation units share precisely this callback ABI; other layouts stay opaque.
    local = (HERE/'imaging-device.h').read_text()
    native = (MODEL_ROOT/'imaging-device.h').read_text()
    def io(text):
        matches = re.findall(r'struct full_imaging_io\s*\{(.*?)\};', text, re.S)
        if len(matches) != 1:
            raise ValueError('USB touch transport ABI unavailable')
        return re.sub(r'\s+', '', matches[0])
    if io(local) != io(native):
        raise ValueError('USB touch transport callback ABI drift')
    return {'schema': 'a7c2.usb-touch-scope.v1', 'profile': profile,
            **({'tcin': {'profile': 'virtual-inactive-v1', 'destination': 0x92840747,
                        'request_raw': '0d2029040a0001800000',
                        'reply_raw': '0d2029140c00018000000000',
                        'condition_virtual': 0, 'active_virtual': 0, 'connected_virtual': 0,
                        'original_cp_executed': False, 'hardware_tcin_verified': False}}
               if profile == TCIN_PROFILE else {}),
            'assets': assets, 'model_sources': models,
            'contract': {'destination': 0x92840747, 'request_bytes': 10,
                         'command': 0x146, 'enable': [0, 1], 'reply_bytes': 12,
                         'reply_command': 0x1146, 'status': 0x590000,
                         'original_cp_history_verified': False,
                         'f02f_transport_verified': False, 'hardware_touch_verified': False,
                         'capture_verified': False}}


def validate(observer, profile):
    receipt = observer.get('usb_touch')
    if receipt is None:
        return None
    if profile != 'virtual-functional-camera-usb-service-v1':
        raise ValueError('USB touch requires explicit existing USB service profile')
    if not isinstance(receipt, dict):
        raise ValueError('Invalid USB touch receipt')
    try:
        expected = prepare(receipt['profile'], receipt['assets']['ap']['path'], receipt['assets']['cp']['path'])
    except (KeyError, TypeError) as error:
        raise ValueError('Invalid USB touch asset receipt') from error
    if receipt != expected:
        raise ValueError('USB touch source/resource contract drift')
    return receipt


def derive(source, receipt):
    if receipt is None:
        return source
    if receipt.get('schema') != 'a7c2.usb-touch-scope.v1' or receipt.get('profile') not in (PROFILE, TCIN_PROFILE):
        raise ValueError('Invalid USB touch source plan')
    if '#include "touch-panel-device.h"' in source:
        raise ValueError('USB touch helper hook ambiguous or already applied')
    changes = [
        ('static const char *mirrored[] = {',
         'static const char *mirrored[] = { "FULL_TOUCH_PANEL_",'),
        ('int osal_free_msg(unsigned int id, void *message) {\n',
         'int osal_free_msg(unsigned int id, void *message) {\n'
         '    { int result;\n'
         '      if (full_touch_panel_release_reply(id,message,real_free_msg,record,&result)) return result; }\n'),
        ('    full_file_media_before_send(id,real_dlsym,record);\n',
         '    full_file_media_before_send(id,real_dlsym,record);\n'
         '    if (id==FULL_TOUCH_PANEL_INPUT && getenv("FULLSYSTEM_USB_TOUCH") &&\n'
         f'        !strcmp(getenv("FULLSYSTEM_USB_TOUCH"),"{receipt["profile"]}")) {{\n'
         '        const struct full_imaging_io io={real_allocate_msg,real_free_msg,real_set_source,\n'
         '            real_send_msg,real_msg_size,real_get_source,record};\n'
         '        int result;\n'
         '        if(full_touch_panel_dispatch(id,message,&io,1,&result)) return result;\n'
         '    }\n'),
    ]
    if receipt['profile'] == TCIN_PROFILE:
        changes += [
            ('static const char *mirrored[] = {',
             'static const char *mirrored[] = { "FULL_TCIN_",'),
            ('int osal_free_msg(unsigned int id, void *message) {\n',
             'int osal_free_msg(unsigned int id, void *message) {\n'
             '    { int result;\n'
             '      if (full_tcin_release_reply(id,message,real_free_msg,record,&result)) return result; }\n'),
            ('    full_file_media_before_send(id,real_dlsym,record);\n',
             '    full_file_media_before_send(id,real_dlsym,record);\n'
             '    if (id==FULL_TCIN_INPUT && getenv("FULLSYSTEM_USB_TOUCH") &&\n'
             f'        !strcmp(getenv("FULLSYSTEM_USB_TOUCH"),"{TCIN_PROFILE}")) {{\n'
             '        const struct full_imaging_io io={real_allocate_msg,real_free_msg,real_set_source,\n'
             '            real_send_msg,real_msg_size,real_get_source,record};\n'
             '        int result;\n'
             '        if(full_tcin_dispatch(id,message,&io,1,&result)) return result;\n'
             '    }\n'),
        ]
    for before, after in changes:
        if source.count(before) != 1:
            raise ValueError('USB touch helper hook ambiguous or already applied')
        source = source.replace(before, after, 1)
    includes = '#include "imaging-device.h"\n#include "touch-panel-device.h"\n'
    if receipt['profile'] == TCIN_PROFILE:
        includes += '#include "tcin-device.h"\n'
    return includes+source
