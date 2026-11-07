#!/usr/bin/env python3
"""Opt-in original usb_portMonitor init2 load and passive original-AP USB probe.

Creates a fresh private helper overlay, binds its house insmod to current source,
then uses the existing leased persistent cold boot and three VBUS readbacks.
No direct USB control ioctl, AP event injection, host attachment or QEMU rebuild.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import runpy
import subprocess

HERE = Path(__file__).resolve().parent
AP = runpy.run_path(str(HERE / 'usb-ap-probe.py'))
CAMERA = runpy.run_path(str(HERE / 'persistent-camera-profile.py'))
START = runpy.run_path(str(HERE / 'usb-start-observe.py'))
SOURCE_CONTRACT = {
    'schema': 'a7c2.usb-control-start.v1',
    'module': {'path': '/usr/kmod/usb_portMonitor.ko', 'bytes': 44872,
               'sha256': '792cbc38576efba8e33faf730514f9ac694883b2668019ced0581abeb4b6f73d',
               'vermagic': '4.9.337-scel+ SMP preempt mod_unload aarch64',
               'responsibility': 'OTG listener, OSAL port-status and Type-C/CP services; not start_control'},
    'original_methods': [
        {'file': 'libUsbControl.so', 'address': '0x13d3c', 'method': 'UsbControl_Init',
         'next': 'PreInit plus original OSAL thread'},
        {'file': 'libUsbControl.so', 'address': '0x15654', 'method': 'UsbControl::Init',
         'next': 'createUsbCtrlResource/acquireUsbResource'},
        {'file': 'libUsbControl.so', 'address': '0x18e5c', 'method': 'UsbIfWrapper::doInitialize',
         'next': 'entryPortStatusThread -> usbif_initialize -> original interface virtual method'},
        {'file': 'libInfraUsbCmn.so', 'address': '0x17da4', 'method': 'usbif_initialize',
         'next': 'original USB service; actual AP control start remains an observation'},
    ],
    'kernel_control': 'usb_otgcore.c:transition_to_idle -> usb_otg_control_start_control -> fusb_try_start_notify',
    'dependencies': {'kernel': 'original OSAL UTM/UIPC, mutex, Backup, GPIO and timer services',
                     'unverified': 'later CP replies, Type-C I2C/mux operation and resource acquisition'},
    'direct_ioctl_requested': False, 'original_ap_control_start_verified': False,
    'usb_menu_verified': False, 'host_enumerated': False,
}


def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def prepare_helpers(runtime, output, *, observe_start=False, observe_ee=False, ee_normal_cold=None,
                    usb_touch_profile=None, usb_touch_ap=None, usb_touch_cp=None):
    if ee_normal_cold is not None and (not observe_start or observe_ee):
        raise ValueError('EE functional mode requires explicit --observe-start and excludes --observe-ee')
    if observe_ee and not observe_start:
        raise ValueError('EE observer requires explicit --observe-start')
    cold = AP['PERSISTENT']['COLD']
    source = cold['plain'](Path(runtime) / 'analysis', directory=True)
    output = AP['PERSISTENT']['fresh_output'](output, runtime)
    analysis = output / 'analysis'
    analysis.mkdir(mode=0o700)
    source_manifest = source / 'full-system.json'
    before = digest(source_manifest)
    # Reuse unchanged source-bound observer/assets; the new insmod is never installed in the old runtime.
    paths = ('full-system.json', 'qemu-kernel-probe.sh', 'boot-handoff.bin', 'boards/virt-four.dtb',
             'qemu-virt-board/virt-packed.dtb', AP['PERSISTENT']['KERNEL_ASSET'],
             'unpacked/firmware.tar_unpacked/0800_appli/setting/kemco.txt', 'root/simulation', 'root/lib')
    for relative in paths:
        target = analysis / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(['cp', '-a', '--reflink=auto', '--sparse=always', str(source / relative), str(target)],
                       check=True, timeout=55)
    (output / 'sources').symlink_to((source.parent / 'sources').resolve(strict=True), target_is_directory=True)
    house = analysis / 'root/sbin/insmod'
    house_sha = digest(HERE / 'guest/insmod')
    cold['clone'](HERE / 'guest/insmod', house, house_sha)
    house.chmod(0o755)
    manifest_path = analysis / 'full-system.json'
    if digest(manifest_path) != before:
        raise ValueError('Copied helper manifest differs from source')
    manifest = json.loads(manifest_path.read_text())
    topology_source = cold['plain'](HERE / 'usb-device-profile.py')
    touch_scope = runpy.run_path(str(HERE / 'usb-touch-scope.py'))
    touch = touch_scope['prepare'](usb_touch_profile, usb_touch_ap, usb_touch_cp)
    if touch is not None and (not observe_start or observe_ee or ee_normal_cold is None):
        raise ValueError('USB touch requires the current explicit original-service/EE functional preparation')
    if touch is not None:
        native_root = runpy.run_path(str(HERE / 'native-input.py'))['resolve']() / 'runtime/analysis'
        build = runpy.run_path(str(HERE / 'build-imaging.py'))['build'](
            native_root, analysis / 'root', analysis / 'usb-touch-observer', persistent_claim=True,
            usb_touch_profile=usb_touch_profile, usb_touch_ap=usb_touch_ap, usb_touch_cp=usb_touch_cp)
        manifest['imaging_observer'] = build
        manifest['native_dependency_snapshot'] = native_root.parents[1].name
        manifest.setdefault('adapter_sources', {})['usb-touch-scope.py'] = digest(HERE / 'usb-touch-scope.py')
        native = analysis / 'root/simulation/menu-observe.so'
        if (build['usb_touch'] != touch or
                build['observer_sha256'] != digest(native) or
                build['derived_source_sha256'] != digest(analysis / 'usb-touch-observer/menu-observe.c')):
            raise ValueError('Fresh USB touch native observer source/ELF readback differs')
        manifest['imaging_observer']['observer_bytes'] = native.stat().st_size
        # START.prepare reads the manifest afresh; publish the selected generation first.
        if build['usb_touch']['contract']['original_cp_history_verified']:
            raise ValueError('USB touch must not promote original CP history')
    topology_sha = digest(topology_source)
    cold['clone'](topology_source, analysis / 'usb-device-profile.py', topology_sha)
    manifest.setdefault('derived_files', {})['sbin/insmod'] = house_sha
    manifest.setdefault('adapter_sources', {})['guest/insmod'] = house_sha
    manifest['adapter_sources']['usb-device-profile.py'] = topology_sha
    manifest_path.write_text(json.dumps(manifest, indent=2) + '\n')
    observer_contract = (START['prepare'](analysis, **({'observe_ee': True} if observe_ee else {}),
                         **({'ee_normal_cold': ee_normal_cold} if ee_normal_cold is not None else {}))
                         if observe_start else None)
    if observer_contract is not None:
        manifest['usb_start_observe'] = observer_contract
    manifest_path.write_text(json.dumps(manifest, indent=2) + '\n')
    profile = CAMERA['USB_SERVICE_PROFILE'] if observe_start else CAMERA['USB_MONITOR_PROFILE']
    contract = CAMERA['expand'](profile, analysis)
    if (digest(source_manifest) != before or digest(HERE / 'guest/insmod') != house_sha or
            digest(topology_source) != topology_sha or digest(analysis / 'usb-device-profile.py') != topology_sha):
        raise ValueError('Helper inputs changed during private overlay preparation')
    AP['save'](output / 'helper-receipt.json', dict(source_runtime=str(source), source_manifest_sha256=before,
        manifest_sha256=digest(manifest_path), source_manifest_unchanged=True, partition_images_copied=False,
        insmod_sha256=house_sha, topology_source_sha256=topology_sha,
        topology_source_copy=str(analysis / 'usb-device-profile.py'),
        observer_rebuilt=touch is not None, usb_start_observer=observer_contract, camera_profile=contract))
    return output


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('instance', 'runtime', 'module', 'qemu-build', 'output'):
        parser.add_argument('--' + name, type=Path, required=True)
    parser.add_argument('--seconds', type=int, default=150)
    parser.add_argument('--select-msc', action='store_true', help='press original ENTER on the reviewed default MSC row and read guest EP0 bytes')
    parser.add_argument('--observe-start', action='store_true', help='explicit exact original Sen module plus passive USB service observer')
    parser.add_argument('--observe-ee', action='store_true', help='explicit zero-publication EE observer; requires --observe-start and --seconds <= 120')
    parser.add_argument('--ee-normal-cold-model', type=Path, help='explicit functional model JSON; private ADC/state/force/be9 plus launch generation')
    parser.add_argument('--ee-backup', type=Path)
    parser.add_argument('--ee-vendor', type=Path)
    parser.add_argument('--ee-cp', type=Path)
    parser.add_argument('--host-version', action='store_true', help='after original MSC/EP0, enumerate owned host USB and read the original version; no host permission helper')
    parser.add_argument('--prepare-only', action='store_true', help='fresh helper build and manifest preflight only; never launch a VM')
    parser.add_argument('--usb-touch-profile', choices=['virtual-config-v1', 'virtual-config-tcin-inactive-v1'], help='explicit finite original-request touch / inactive TCIN model; default off')
    parser.add_argument('--usb-touch-ap', type=Path)
    parser.add_argument('--usb-touch-cp', type=Path)
    args = parser.parse_args(argv)
    if args.host_version and (not args.select_msc or not args.observe_start or args.prepare_only):
        parser.error('--host-version requires --select-msc and --observe-start and excludes --prepare-only')
    private_args = (args.ee_normal_cold_model, args.ee_backup, args.ee_vendor, args.ee_cp)
    functional = None
    if any(value is not None for value in private_args):
        if (not all(value is not None for value in private_args) or not args.observe_start or
                args.observe_ee or args.seconds > 120):
            parser.error('functional EE requires --observe-start, --ee-normal-cold-model/--ee-backup/--ee-vendor/--ee-cp, excludes --observe-ee, and --seconds <= 120')
        functional = dict(model=args.ee_normal_cold_model, backup=args.ee_backup, vendor=args.ee_vendor, cp=args.ee_cp)
    if args.observe_ee and (not args.observe_start or args.seconds > 120):
        parser.error('--observe-ee requires --observe-start and --seconds <= 120')
    if not 10 <= args.seconds <= 3600:
        parser.error('--seconds must be 10..3600')
    output = AP['PERSISTENT']['fresh_output'](args.output, args.runtime, args.instance)
    AP['save'](output / 'source-contract.json', dict(SOURCE_CONTRACT, probe_source_sha256=digest(__file__)))
    helpers = prepare_helpers(args.runtime, output / 'helpers', observe_start=args.observe_start, observe_ee=args.observe_ee,
                              **({'ee_normal_cold': functional} if functional is not None else {}),
                              **(dict(usb_touch_profile=args.usb_touch_profile, usb_touch_ap=args.usb_touch_ap,
                                      usb_touch_cp=args.usb_touch_cp)
                                 if any(value is not None for value in (args.usb_touch_profile,args.usb_touch_ap,args.usb_touch_cp)) else {}))
    if args.prepare_only:
        return 0
    return AP['main'](['--instance', str(args.instance), '--runtime', str(helpers), '--module', str(args.module),
                       '--qemu-build', str(args.qemu_build), '--output', str(output / 'probe'),
                       '--seconds', str(args.seconds)], camera_profile=(CAMERA['USB_SERVICE_PROFILE'] if args.observe_start else CAMERA['USB_MONITOR_PROFILE']),
                      select_msc=args.select_msc, observe_start=args.observe_start,
                      **({'host_version': True} if args.host_version else {}))


if __name__ == '__main__':
    raise SystemExit(main())
