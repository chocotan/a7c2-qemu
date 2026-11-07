#!/usr/bin/env python3
"""Bind the existing AP functional providers to an original persistent cold boot.

This expands an explicit local virtual-hardware profile. It never selects the
Sony loader route, replaces init, loads an unsupported CP module or opens a disk.
"""
import hashlib
import json
from pathlib import Path
import re
import runpy

HERE=Path(__file__).resolve().parent
PROFILE='virtual-functional-camera-v1'
USB_MONITOR_PROFILE='virtual-functional-camera-usb-monitor-v1'
USB_SERVICE_PROFILE='virtual-functional-camera-usb-service-v1'
TOKENS=(
    'persistent.camera-profile='+PROFILE,
    'fullsystem.imaging=release-inhibit','fullsystem.vdf=timecode',
    'fullsystem.dig-level=virtual','fullsystem.dmm=unit-size',
    'fullsystem.audio=boot','fullsystem.audio-caps=inputless','fullsystem.hdmi=boot',
    'fullsystem.sound-owner=1','fullsystem.vef=registry','fullsystem.pinmem=registry',
    'fullsystem.pin-connect=control','fullsystem.pin-format=cold','fullsystem.pin-control-memory=1',
    'fullsystem.scalar=registry','fullsystem.scalar-connect=control',
    'fullsystem.adf=registry','fullsystem.adf-connect=control',
    'fullsystem.hdmi-pin=registry','fullsystem.hdmi-connect=control','fullsystem.adf-audio-connect=control',
    'fullsystem.gui-models=capture','fullsystem.remote-state=capture','fullsystem.gpio-c1=virtual',
    'fullsystem.bluetooth=off','fullsystem.input-observe=1','fullsystem.backup-log=sampled',
)
REQUIRED_MODELS={
    'imaging-device.c','vdf-device.c','audio-device.c','hdmi-device.c','system-sound-owner.c',
    'pin-connection.c','pin-buffer-owner.c','pin-format.c','vef-device.c','pinmem-device.c',
    'scalar-device.c','scalar-connection.c','adf-device.c','adf-connection.c','hdmi-pin-device.c',
    'gui-models.c','remote-state.c',
}


def plain(value):
    path=Path(value).absolute()
    if any(p.is_symlink() for p in (path,*path.parents)) or not path.is_file():
        raise ValueError('Expected an ordinary functional-profile input: '+str(path))
    return path


def digest(value):
    with plain(value).open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()


def expand(profile, analysis):
    if profile=='strict':
        return {'profile':'strict','cmdline':[],'environment':{},'source_bindings':[],
                'original_loader_selected':False,'functional_providers_requested':False}
    if profile not in (PROFILE,USB_MONITOR_PROFILE,USB_SERVICE_PROFILE):raise ValueError('Unknown persistent camera profile; no fallback')
    analysis=Path(analysis).absolute()
    manifest_path=plain(analysis/'full-system.json')
    manifest=json.loads(manifest_path.read_text())
    observer=manifest.get('imaging_observer',{})
    models=observer.get('device_sources',{})
    touch_receipt=None
    if observer.get('usb_touch') is not None:
        touch_source=plain(HERE/'usb-touch-scope.py')
        if manifest.get('adapter_sources',{}).get('usb-touch-scope.py')!=digest(touch_source):
            raise ValueError('USB touch scope adapter differs; rebuild helpers')
        touch_receipt=runpy.run_path(str(touch_source))['validate'](observer,profile)
    display=observer.get('persistent_display_claim',{})
    if (display.get('path')!='/dev/qemu-simulation/headless-osd.claim' or
            display.get('snapshot_path')!='/dev/qemu-simulation/headless-osd-frame.bin'):
        raise ValueError('Persistent functional display requires bound per-boot RAM claim and snapshot')
    viewer=plain(analysis/'root/simulation/ramfb-viewer')
    if digest(viewer)!=display.get('viewer_sha256'):
        raise ValueError('Persistent RAM display viewer differs from the producer binding')
    if not isinstance(models,dict) or not REQUIRED_MODELS.issubset(models):
        raise ValueError('Prepared observer lacks the required original-AP functional providers')
    bindings=[{'role':'helper-manifest','path':str(manifest_path),'sha256':digest(manifest_path)}]
    for name,expected in sorted(models.items()):
        if not re.fullmatch(r'[a-z0-9_-]+\.(?:c|h|inc)',name) or not re.fullmatch(r'[0-9a-f]{64}',str(expected)):
            raise ValueError('Invalid functional provider source binding')
        path=plain(HERE/name)
        actual=digest(path)
        if actual!=expected:raise ValueError('Functional provider source changed; rebuild observer: '+name)
        bindings.append({'role':'functional-provider-source','path':str(path),'sha256':actual})
    program=plain(analysis/'root/simulation/menu-observe.so')
    if digest(program)!=observer.get('observer_sha256'):
        raise ValueError('Prepared observer program differs from its bound sources')
    bindings.append({'role':'functional-observer','path':str(program),'sha256':digest(program)})
    bindings.append({'role':'persistent-ram-viewer','path':str(viewer),'sha256':digest(viewer)})
    workspace=plain(analysis/'unpacked/firmware.tar_unpacked/0800_appli/setting/kemco.txt')
    text=workspace.read_text()
    bindings.append({'role':'workspace','path':str(workspace),'sha256':digest(workspace)})
    reservations=[]
    for name in ('system-sound-region.py','pin-buffer-region.py'):
        path=plain(HERE/name)
        if manifest.get('adapter_sources',{}).get(name)!=digest(path):
            raise ValueError('RAM reservation adapter differs; rebuild prepared helpers: '+name)
        region=runpy.run_path(str(path))
        reservations.append(region['validate_reservation'](text))
        bindings.append({'role':'reservation-adapter','path':str(path),'sha256':digest(path)})
    for name in ('system-sound-owner','bluetooth-policy'):
        path=plain(analysis/'root/simulation'/name)
        bindings.append({'role':'guest-profile-helper','path':str(path),'sha256':digest(path)})
    if touch_receipt is not None:
        bindings.append({'role':'usb-touch-scope-source','path':str(touch_source),'sha256':digest(touch_source)})
        bindings.extend(dict(row,role='usb-touch-original-asset') for row in touch_receipt['assets'].values())
        bindings.extend(dict(row,role='usb-touch-model-source') for row in touch_receipt['model_sources'].values())
    monitor=profile in (USB_MONITOR_PROFILE,USB_SERVICE_PROFILE)
    service=profile==USB_SERVICE_PROFILE
    if service:
        adapter=runpy.run_path(str(HERE/'usb-start-observe.py'))
        bindings.extend(adapter['validate'](analysis))
    if monitor:
        house=plain(analysis/'root/sbin/insmod')
        source=plain(HERE/'guest/insmod')
        if digest(house)!=digest(source) or digest(house)!=manifest.get('derived_files',{}).get('sbin/insmod'):
            raise ValueError('Original USB monitor requires a fresh source-bound insmod helper')
        bindings.extend({'role':'usb-monitor-insmod','path':str(path),'sha256':digest(path)} for path in (house,source))
    return {'profile':profile,'cmdline':[*TOKENS,*reservations,*(['fullsystem.usb-monitor=original'] if monitor else []),
                                        *(['fullsystem.usb-service=original-sen-observe-v1'] if service else []),
                                        *(['fullsystem.usb-touch='+touch_receipt['profile']] if touch_receipt is not None else [])],
            'environment':{'QEMU_TCG_THREAD':'multi','QEMU_FULL_USB_INIT':'original',
                           'QEMU_FULL_USB_PLATFORM':'full','QEMU_FULL_USB_CONTROLLER':'upstream-host'},
            'insmod_policy':'media-rm','usb_monitor':'original' if monitor else 'blocked',
            'usb_sen':'original-exact' if service else 'blocked','usb_start_observe':service,'source_bindings':bindings,
            'functional_providers_requested':True,'original_loader_selected':False,
            'contracts':{'imaging':'explicit release-inhibit/VDF model; no capture acceptance',
                         'sound':'VM-lifetime software RAM owner; original allocator unverified',
                         'pin':'finite software owner; original CP task and pool policy unverified',
                         'connections':'bounded original-AP provider interfaces, not physical ASIC evidence',
                         'bluetooth':'explicit offline preference through original Backup read/write/readback'},
            'actual_persistent_ap_consumed':False,'capture_verified':False}
