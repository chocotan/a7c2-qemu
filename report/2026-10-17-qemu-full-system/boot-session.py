#!/usr/bin/env python3
"""Run explicitly selected boot-chain experiments on isolated complete images."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import runpy
import secrets
import subprocess
import sys

FIRMWARE_DEVELOPMENT_API = 1
HERE = Path(__file__).resolve().parent
NATIVE = HERE.parents[1] / 'runtime/analysis'
sys.path.insert(0, str(NATIVE))
from boot_flow import PROFILES, evaluate, new_receipt, record_stage, select_route
from sony_wbi import compare_cache, inspect_wbi


def ordinary(path, directory=False):
    path = Path(os.path.abspath(path))
    for component in (*reversed(path.parents), path):
        if component.is_symlink():
            raise ValueError('Symlink is not an input: ' + str(component))
    if not (path.is_dir() if directory else path.is_file()):
        raise ValueError('Expected ordinary ' + ('directory: ' if directory else 'file: ') + str(path))
    return path


def digest(path):
    with ordinary(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def save(path, value):
    temporary = path.with_suffix(path.suffix + '.new')
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + '\n')
    temporary.chmod(0o600)
    temporary.replace(path)


def verified_runtime(runtime):
    analysis = ordinary(Path(runtime) / 'analysis', directory=True)
    manifest_path = ordinary(analysis / 'full-system.json')
    manifest = json.loads(manifest_path.read_text())
    if manifest.get('source') not in ('private-device-dump', 'official-bodydata-derived'):
        raise ValueError('Unknown complete-image provenance')
    expected = {'a7c2-rootfs.img', 'a7c2-usr.img'} | {
        f'nflasha{part}.img' for part in (1,2,3,4,5,6,8,10,11,12,13,18,22,23,30,'B0','B1')}
    records = manifest.get('images', [])
    if len(records) != 19 or {row.get('name') for row in records} != expected:
        raise ValueError('Complete 19-image inventory is required')
    for row in records:
        path = ordinary(analysis / 'root/partitions' / row['name'])
        if path.stat().st_size != row['bytes'] or digest(path) != row['sha256']:
            raise ValueError('Partition binding changed: ' + row['name'])
    return analysis, manifest


def inspect_inputs(analysis, output):
    partitions = analysis / 'root/partitions'
    wbi = inspect_wbi(partitions / 'nflasha5.img')
    ap = output / 'selected-appFw.so'
    result = subprocess.run(['debugfs', '-R', 'dump /lib/appFw.so ' + str(ap),
                             str(partitions / 'a7c2-usr.img')], capture_output=True, text=True)
    (output / 'appfw-readback.log').write_text(result.stdout + result.stderr)
    if result.returncode or not ap.is_file() or not ap.stat().st_size:
        raise ValueError('Cannot read selected AP from the bound p15 image')
    compatibility = compare_cache(partitions / 'nflasha5.img', ap)
    return {'wbi': wbi, 'ap_sha256': digest(ap), 'wbi_ap_compatibility': compatibility}


def prepare(args, runner=subprocess.run):
    output = Path(os.path.abspath(args.output))
    if os.path.lexists(output):
        raise ValueError('Boot output must be fresh; retain old runs as evidence')
    ordinary(output.parent, directory=True)
    output.mkdir(mode=0o700)
    state = {'schema': 1, 'profile': args.profile, 'state': 'preparing',
             'physical_devices_used': False, 'full_boot_verified': False}
    save(output / 'session.json', state)
    try:
        if args.dump is not None:
            source = ordinary(args.dump, directory=True)
            runtime = output / 'prepared-runtime'
            command = [sys.executable, '-B', str(HERE / 'prepare-full-system.py'),
                       '--dump', str(source), '--runtime', str(runtime)]
            with (output / 'prepare.log').open('x') as log:
                runner(command, stdout=log, stderr=subprocess.STDOUT, check=True)
        else:
            runtime = ordinary(args.runtime, directory=True)
        persistent = getattr(args, 'instance', None)
        camera_profile = getattr(args, 'camera_profile', 'strict')
        persistent_build = None
        if persistent is not None:
            if args.profile != 'original-init-cold' or args.dump is not None:
                raise ValueError('Persistent instance requires original-init-cold and an explicit helper runtime')
            if camera_profile not in ('strict','virtual-functional-camera-v1'):
                raise ValueError('Unknown persistent camera profile')
            persistent_api = runpy.run_path(str(HERE/'persistent-boot.py'))
            options = {}
            if getattr(args, 'persistent_module', None) is not None:
                options['module'] = ordinary(args.persistent_module)
            persistent_build = persistent_api['build'](ordinary(persistent, directory=True),
                                                       ordinary(runtime/'analysis', directory=True),
                                                       output/'cold-chain', **options)
            analysis = runtime/'analysis'
            manifest = {'source':persistent_build['source'], 'images':[]}
            inspection = {'source':'leased-persistent-instance',
                          'native_elf_identity':persistent_build['native_elf_identity'],
                          'wbi_ap_compatibility':{'status':'unknown', 'resume_executed':False,
                              'reason':'This explicit original cold route does not validate or execute WBI restoration'}}
        else:
            analysis, manifest = verified_runtime(runtime)
            inspection = inspect_inputs(analysis, output)
        save(output / 'input-inspection.json', inspection)
        predicates = {}
        if args.predicates is not None:
            predicates = json.loads(ordinary(args.predicates).read_text())
        route = select_route(predicates)
        receipt = new_receipt(args.profile, bindings={
            'run': output.name, 'source_class': manifest['source'],
            'complete_image_manifest_sha256': digest(analysis / 'full-system.json'),
            'images': manifest['images'], 'requested_predicates': predicates,
            'route_input_kind': 'explicit_functional_inputs' if args.predicates else 'unobserved',
        })
        if persistent_build is not None:
            receipt['bindings']['persistent_instance'] = persistent_build['instance']
            receipt['bindings']['instance_geometry'] = persistent_build['instance_geometry']
            receipt['bindings']['native_elf_identity'] = persistent_build['native_elf_identity']
            # Recompute the immutable binding digest after including the actual disk.
            receipt = new_receipt(args.profile, bindings=receipt['bindings'])
        state.update(runtime=str(runtime), source_class=manifest['source'], camera_profile=camera_profile,
                     route_model=route, route_model_is_original_loader_execution=False,
                     input_inspection='input-inspection.json', receipt=receipt)
        if args.profile == 'original-init-cold':
            if persistent_build is not None:
                build = persistent_build
                backend = 'original-init-with-persistent-device'
            else:
                cold = runpy.run_path(str(HERE / 'cold-init-chain.py'))
                build = cold['build'](analysis, output / 'cold-chain')
                backend = 'original-init-with-explicit-storage-adapter'
            state.update(state='prepared', cold_chain=build, backend=backend,
                         cold_selection='explicit QEMU experiment, not observed Sony loader selection')
        elif args.profile == 'sd-update' and args.functional_install:
            if args.sd_image is None:
                raise ValueError('A functional SD installation requires --sd-image')
            command = [str(args.import_python or sys.executable), '-B', str(HERE/'virtual-update.py'),
                       '--sd-image', str(ordinary(args.sd_image)),
                       '--images-manifest', str(analysis/'full-system.json'),
                       '--output-dir', str(output/'installed'), '--fwtool-dir', str(ordinary(args.fwtool, directory=True))]
            if args.mtools_dir is not None:
                command += ['--mtools-dir', str(ordinary(args.mtools_dir, directory=True))]
            with (output/'install.log').open('x') as log:
                result = runner(command, stdout=log, stderr=subprocess.STDOUT, check=False)
            installed = output/'installed/receipt.json'
            if not installed.is_file():
                raise RuntimeError('Virtual install produced no durable receipt; inspect install.log')
            installation = json.loads(ordinary(installed).read_text())
            state.update(state='functional-install-finished' if result.returncode == 0 else 'failed',
                         functional_install=installation, functional_install_returncode=result.returncode,
                         backend='host_functional', guest_original_install_verified=False)
            if result.returncode == 0 and installation.get('partition_stream_verified'):
                record_stage(receipt, 'sd_install', execution_kind='host_functional', status='passed', evidence={
                    'run': receipt['bindings']['run'], 'generation': receipt['generation'],
                    'binding_digest': receipt['binding_digest'], 'source': 'host',
                    'source_class': manifest['source'], 'artifacts':[{'path':str(installed),'sha256':digest(installed)}]})
        elif args.profile == 'direct-bootin':
            raise ValueError('Use the native product entry for direct-bootin diagnostics')
        else:
            state.update(state='blocked', backend=None,
                         blockers=[args.profile + ': original execution backend is not yet connected; no cold-start fallback'])
        state['coverage'] = evaluate(receipt)
        save(output / 'session.json', state)
        return output, state
    except BaseException as error:
        state.update(state='failed', error=type(error).__name__ + ': ' + str(error))
        save(output / 'session.json', state)
        raise


def main(argv=None):
    argv=list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0]=='--firmware-development-request':
        if len(argv)!=2:raise ValueError('Expected exactly one private firmware-development request')
        result=runpy.run_path(str(HERE/'firmware-boot-request.py'))['execute'](Path(argv[1]))
        print(json.dumps(result),flush=True)
        return 0 if result.get('status')=='completed' else 2
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--profile', choices=PROFILES, required=True)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument('--dump', type=Path, help='read-only complete camera image inventory')
    source.add_argument('--runtime', type=Path, help='prepared complete-image runtime; original inputs stay unchanged')
    parser.add_argument('--output', type=Path, required=True, help='new isolated session directory')
    parser.add_argument('--instance', type=Path, help='reuse this single persistent virtual disk; original-init-cold only')
    parser.add_argument('--persistent-module', type=Path, help='matching original-kernel virtual block module')
    parser.add_argument('--qemu-build', type=Path, help='validated production persistent-board build directory')
    parser.add_argument('--usb-device', action='store_true', help='explicit original-Sony-device profile; requires the validated persistent/USB production build')
    parser.add_argument('--camera-profile', choices=('strict','virtual-functional-camera-v1'), default='strict',
                        help='explicit local functional-provider contract for persistent cold boot')
    parser.add_argument('--predicates', type=Path, help='explicit three-state loader model inputs, not actual hardware observations')
    parser.add_argument('--sd-image', type=Path, help='regular virtual FAT card; never a physical device')
    parser.add_argument('--seconds', type=int, default=90)
    parser.add_argument('--functional-install', action='store_true',
                        help='explicit host virtual-partition model; never a fallback for the original SD receiver')
    parser.add_argument('--fwtool', type=Path, default=NATIVE/'vendor/fwtool-sdk')
    parser.add_argument('--mtools-dir', type=Path)
    parser.add_argument('--import-python', type=Path, help='existing Python with fwtool crypto dependencies')
    parser.add_argument('--prepare-only', action='store_true')
    parser.add_argument('--validation-script', type=Path, help='explicit ASCII guest check after original AP startup; source SHA and actual RC retained')
    parser.add_argument('--require-full-boot', action='store_true')
    args = parser.parse_args(argv)
    if not 1 <= args.seconds <= 3600:
        parser.error('--seconds must be between 1 and 3600')
    if args.instance is not None and (args.profile != 'original-init-cold' or args.runtime is None or args.functional_install):
        parser.error('--instance requires original-init-cold, --runtime and no functional installer')
    if args.usb_device and (args.instance is None or args.qemu_build is None):
        parser.error('--usb-device requires --instance and a matching --qemu-build')
    if args.instance is None and (args.persistent_module is not None or args.qemu_build is not None or args.camera_profile!='strict'):
        parser.error('--persistent-module, --qemu-build and a functional camera profile require --instance')
    if args.sd_image is not None:
        ordinary(args.sd_image)
    if args.functional_install and (args.profile != 'sd-update' or args.sd_image is None or args.prepare_only):
        parser.error('--functional-install requires sd-update plus --sd-image, and executes a write experiment')
    if args.import_python is not None:
        ordinary(args.import_python)
    if args.validation_script is not None:
        ordinary(args.validation_script)
        if args.profile!='original-init-cold' or args.prepare_only:parser.error('--validation-script requires an executing original-init-cold session')
    output, state = prepare(args)
    print('BOOT_SESSION ' + str(output), flush=True)
    if state['state'] == 'blocked':
        print(json.dumps(state['blockers']), file=sys.stderr)
        return 2
    if state['state'] in ('functional-install-finished', 'failed'):
        if args.require_full_boot or state['state'] == 'failed':
            return 2
        return 0
    if args.prepare_only:
        return 0
    persistent = state['backend'] == 'original-init-with-persistent-device'
    cold = runpy.run_path(str(HERE / ('persistent-boot.py' if persistent else 'cold-init-chain.py')))
    options = {'qemu_build':args.qemu_build} if persistent and args.qemu_build is not None else {}
    if persistent:options['camera_profile'] = args.camera_profile
    launch = cold['prepare_launch'](Path(state['runtime'])/'analysis', state['cold_chain'], output/'launch', **options)
    if args.usb_device:
        launch=runpy.run_path(str(HERE/'usb-device-profile.py'))['prepare_launch'](launch,lease=secrets.token_urlsafe(32))
    saved_launch=dict(launch,env={key:value for key,value in launch['env'].items() if key!='QEMU_SONY_USB_LEASE'})
    state.update(state='running', launch=saved_launch)
    save(output / 'session.json', state)
    executor = runpy.run_path(str(HERE / 'boot-execution.py'))
    try:
        if persistent:
            with cold['leased_launch'](launch) as bound:
                validation={'validation_script':args.validation_script} if args.validation_script else {}
                result = executor['run'](bound, state['cold_chain'], output/'evidence', seconds=args.seconds, **validation)
        else:
            validation={'validation_script':args.validation_script} if args.validation_script else {}
            result = executor['run'](launch, state['cold_chain'], output / 'evidence', seconds=args.seconds, **validation)
    except BaseException as error:
        state.update(state='failed', error=type(error).__name__ + ': ' + str(error),
                     execution_evidence=str(output/'evidence/boot-flow.json'))
        save(output / 'session.json', state)
        raise
    state.update(state='finished', execution=result)
    save(output / 'session.json', state)
    if args.require_full_boot and not result.get('full_boot_verified', False):
        return 2
    return 0 if result.get('cold_guest_chain_verified', False) else 2


if __name__ == '__main__':
    raise SystemExit(main())
