#!/usr/bin/env python3
"""Validate one immutable complete camera-development batch; never starts a VM."""
import ast
import hashlib
import io
import json
import os
from pathlib import Path
import re
import runpy
import subprocess
import sys
import tarfile
import tempfile

BASE = Path(__file__).resolve().parents[1]
REPORT = BASE.parents[1] / 'report'
COMPONENTS = ('virtual-jpeg-engine', 'virtual-jpeg-sos', 'virtual-jpeg-hardware',
              'virtual-optics', 'virtual-optical-frame-owner', 'virtual-video-engine',
              'virtual-imaging-jpeg', 'virtual-camera-pipeline', 'native-jpeg-binding',
              'native-video-binding', 'native-video-paramsets', 'native-video-au-contract',
              'native-video-ring-contract', 'native-video-length-format', 'native-video-producer-contract',
              'camera-input-coverage', 'cp-start-state-data', 'cp-start-state-provider',
              'cp-full-state-snapshot', 'cp-parameter-state', 'cp-state-publication', 'native-card-write',
              'lif-runtime-input-contract', 'rc-pixel-layout-contract', 'rc-destination-layout',
              'cp-override-input-contract', 'cp-parameter-initializer', 'cp-parameter-defaults',
              'lif-bitmap-producer', 'lif-capability-owner', 'cp-property-repository-contract',
              'cp-parameter-publication-contract', 'cp-parameter-snapshot-fragments',
              'yc-cpu-consumer-boundary', 'sa-isa-contract', 'lif-handshake-contract',
              'cp-adj-initialization-contract', 'jpeg-scan-restart-contract',
              'native-video-shared-binding', 'lif-cache-admission-contract',
              'native-video-async-transport', 'native-video-source-record',
              'lif-diagnostic-gate-contract', 'jpeg-aif-layout-contract',
              'lif-enable-input-contract', 'lif-disabled-gate-return', 'lif-gate-command-source',
              'native-video-record-fill', 'native-video-engine-result',
              'native-imola-output-source', 'imola-mcu-firmware-contract',
              'imola-mcu-encoded-source', 'imola-mbp-codec-interface',
              'imola-mbp-mailbox', 'imola-ipsx-isa', 'imola-spu-encode-block',
              'imola-source-frame-binding', 'cpu-jpeg-codec-evidence',
              'imola-original0-vbb-request', 'imola-venc-request-conditioner',
              'imola-vbb-hardware-frontier', 'imola-vbb-normalize', 'imola-avc-sps-grid',
              'imola-header-job-queue', 'imola-header-dispatch', 'imola-vbb-input-configuration',
              'cp3003-ap-failure-contract', 'lif-initialization-prefix', 'lif-input-conditioned-writer',
              'native-video-state-action', 'native-video-packet-coordinates',
              'native-video-receive-logger', 'native-video-pointer-conversion', 'native-video-type0-binding',
              'native-video-open-parameter-producer', 'cp3003-error-producer',
              'cmos-isp-resize-input-source', 'native-video-zero-branch-frame-input',
              'cmos-isp-source-frame-owner', 'functional-camera-core',
              'functional-camera-control', 'functional-camera-bridge',
              'functional-mpr-codec', 'functional-mpr-memory', 'functional-jpeg-codec',
              'functional-camera-evidence', 'functional-graph-evidence',
              'functional-vdf-path', 'functional-vdf-layout-stage', 'native-movie-write-trace', 'functional-cp-zoom',
              'functional-histogram', 'functional-background-start',
              'functional-face-source-snapshot', 'disp-bit-width')
MODEL_TESTS = ('test_cp_start_state_data.py', 'test_cp_full_state_snapshot.py',
               'test_cp_start_state_provider.py', 'test_cp_parameter_state.py',
               'test_cp_state_publication.py', 'test_cp_owned_state_profile.py',
               'test_fsys_write_trace.py', 'test_fsys_async_observer.py', 'test_fsys_sync_wiring.py',
               'test_fsys_flush_barrier.py', 'test_fsys_unmount_trace.py', 'test_fsys_hotplug_generation.py',
               'test_cp_lif_frame.py', 'test_cp_lif_bitmap.py', 'test_cp_property_stage.py',
               'test_cp_property_stage_file.py', 'test_cp_parameter_import.py', 'test_cp_parameter_view.py',
               'test_cp_owned_inputs.py', 'test_functional_camera_profile.py',
               'test_functional_camera_control.py', 'test_functional_camera_bridge.py',
               'test_functional_mpr_codec.py', 'test_functional_mpr_memory.py',
               'test_functional_jpeg_codec.py', 'test_functional_jpeg_free_wiring.py', 'test_functional_camera_runner.py',
               'test_functional_camera_wiring.py', 'test_functional_camera_events.py',
               'test_functional_vdf_path.py', 'test_functional_vdf_layout_stage.py', 'test_functional_vdf_broker.py',
               'test_functional_vdf_wiring.py', 'test_functional_histogram.py', 'test_functional_histogram_wiring.py',
               'test_functional_background_start.py', 'test_functional_background_wiring.py',
               'test_functional_background_integration.py', 'test_virtual_hci.py',
               'test_functional_face_dmm.py', 'test_functional_face_registry.py',
               'test_functional_face_runtime.py', 'test_functional_face_wiring.py', 'test_functional_face_transfer.py',
               'test_functional_face_ap_observer.py', 'test_functional_face_sdk_observer.py',
               'test_functional_face_native_command.py', 'test_functional_face_native_ap.py', 'test_functional_face_proc.py',
               'test_functional_face_proc_birth.py', 'test_functional_face_sdk.py', 'test_functional_face_sdk_origin.py',
               'test_functional_face_source_snapshot.py', 'test_functional_face_source_fault.py', 'test_functional_face_source_main.py',
               'scratch/test_verify_hdmi_edge.py',
               'test_functional_vdf_integration.py', 'test_functional_bit_width_core.py', 'test_functional_vdf_bit_width.py',
               'test_functional_cp_zoom.py',
               'test_natural_gtk_input_receipts.py', 'test_mode_wheel_probe.py',
               'test_menu_control.py', 'test_host_sd_guard.py', 'test_media_initial_write.py')


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def digests(paths):
    return {str(p.resolve()): sha(p) for p in sorted(set(paths))}


def component_files(directory):
    return [p for p in directory.rglob('*') if p.is_file()
            and not any(part.startswith('.') or part == '__pycache__' for part in p.relative_to(directory).parts)
            and p.suffix in ('.c', '.h', '.py', '.sh', '.json', '.md')]


def save(path, value):
    with path.open('x') as stream:
        stream.write(json.dumps(value, indent=2) + '\n')


def main():
    if len(sys.argv) != 1:
        raise ValueError('the unified batch validator has no VM or subset option')
    baseline = json.loads((BASE / 'scratch/cp-movie-format-host-regression.json').read_text())
    old_abi = json.loads((BASE / 'scratch/cp-movie-format-abi.json').read_text())
    modules = list(baseline['modules'])
    missing = [str(BASE / name) for name in MODEL_TESTS if not (BASE / name).is_file()]
    modules += list(MODEL_TESTS)
    extras = [REPORT / 'capture-evidence/check_evidence.py',
              REPORT / '2026-10-27-unified-camera/lif-mode-property-source.json',
              REPORT / '2026-10-27-unified-camera/cp-owned-input-stage.md']
    graph = ast.parse((REPORT / 'functional-graph-evidence/check_graph.py').read_text())
    dependency_node = next(node.value for node in graph.body if isinstance(node, ast.Assign)
                           and any(isinstance(target, ast.Name) and target.id == 'FROZEN_DEPENDENCIES'
                                   for target in node.targets))
    graph_dependencies = ast.literal_eval(dependency_node)
    if not isinstance(graph_dependencies, tuple) or not all(isinstance(name, str) and not Path(name).is_absolute()
            and '..' not in Path(name).parts for name in graph_dependencies):
        raise ValueError('invalid graph content dependency declaration')
    extras += [BASE.parents[1] / name for name in graph_dependencies]
    missing += [str(path) for path in extras if not path.is_file()]
    for name in COMPONENTS:
        directory = REPORT / name
        if not directory.is_dir():
            missing.append(str(directory))
            continue
        files = component_files(directory)
        extras += files
        # Only each component's explicit tests are collected, not private runtime evidence.
        modules += [str(p) for p in files if p.name.startswith('test_') and p.suffix == '.py']
    if missing:
        raise ValueError('batch is incomplete; finish these inputs before validation: ' + ', '.join(missing))
    modules = list(dict.fromkeys(str((BASE / p).resolve()) for p in modules))
    source_api = runpy.run_path(str(BASE / 'snapshot-observer-sources.py'))
    runtime = digests(source_api['source_paths'](BASE))
    host = digests([*(Path(p) for p in baseline['host_profile_sources_before']), BASE / 'camera_ui.py',
                    BASE / 'build-functional-camera-model.py', BASE / 'functional_camera_broker.py',
                    BASE / 'functional_camera_runner.py', BASE / 'functional_face_source_snapshot.py', BASE / 'initramfs_identity.py',
                    BASE / 'check-natural-gtk-input.py'])
    observers = digests([*(Path(p) for p in baseline['observer_sources_before']),
                         BASE / 'snapshot-observer-sources.py', Path(__file__)])
    tests = digests([*(Path(p) for p in baseline['test_sources_before']),
                     *(Path(p) for p in modules), *extras])
    groups = {'production': runtime, 'host': host, 'observer': observers, 'test': tests}
    work = Path(tempfile.mkdtemp(prefix='unified-camera-', dir=BASE / 'scratch'))
    save(work / 'inputs.json', {'scope': 'immutable complete batch; component evidence is separate from native capture',
                              'modules': modules, 'groups': groups, 'capture_verified': False})
    frozen = dict(entry for group in groups.values() for entry in group.items())
    with tarfile.open(work / 'inputs.tar.gz', 'x:gz') as archive:
        for name, expected in sorted(frozen.items()):
            path = Path(name)
            content = path.read_bytes()
            if hashlib.sha256(content).hexdigest() != expected:
                raise RuntimeError('input changed before archive: ' + name)
            member = tarfile.TarInfo(str(path.relative_to(BASE.parents[1])))
            member.size = len(content)
            member.mode = path.stat().st_mode & 0o777
            archive.addfile(member, io.BytesIO(content))
    with tarfile.open(work / 'inputs.tar.gz', 'r:gz') as archive:
        for member in archive:
            content = archive.extractfile(member).read()
            if hashlib.sha256(content).hexdigest() != frozen[str(BASE.parents[1] / member.name)]:
                raise RuntimeError('frozen archive readback mismatch: ' + member.name)
    print('UNIFIED_CAMERA_VALIDATION', work, flush=True)
    log = work / 'host-regression.log'
    with log.open('x') as output:
        result = subprocess.run([sys.executable, '-B', '-m', 'pytest', '-p', 'no:cacheprovider',
                                 '--import-mode=importlib', '--color=no', '-q', '--tb=short', *modules], cwd=BASE,
                                stdout=output, stderr=subprocess.STDOUT, timeout=1200)
    text = log.read_text()
    passed = re.search(r'(\d+) passed', text)
    subtests = re.search(r'(\d+) subtests passed', text)
    changed = {name: [p for p, digest in group.items() if sha(Path(p)) != digest]
               for name, group in groups.items()}
    regression = {'scope': 'unified component/runtime host regression; not original camera products',
                  'returncode': result.returncode, 'tests_passed': int(passed[1]) if passed else 0,
                  'subtests_passed': int(subtests[1]) if subtests else 0, 'log_sha256': sha(log),
                  'inputs_sha256': sha(work / 'inputs.json'), 'changed': changed, 'capture_verified': False}
    save(work / 'host-regression.json', regression)
    print(text[-7000:], flush=True)
    if result.returncode or not passed or any(changed.values()):
        raise RuntimeError('unified regression failed or inputs changed; retained evidence: ' + str(work))
    model_built = subprocess.run([sys.executable, '-B', str(BASE / 'build-functional-camera-model.py')],
                                cwd=BASE, capture_output=True, text=True, timeout=240)
    with (work / 'functional-model-build.log').open('x') as output:
        output.write(model_built.stdout + model_built.stderr)
    save(work / 'functional-model-compile.json', {'returncode': model_built.returncode,
         'log_sha256': sha(work / 'functional-model-build.log'), 'capture_verified': False})
    if model_built.returncode:
        raise RuntimeError('functional model build failed; retained evidence: ' + str(work))
    model_metadata = BASE / 'functional-camera-model-build.json'
    model = json.loads(model_metadata.read_text())
    if (model['profile'] != 'virtual-functional-camera-v1' or not model['sources'] or model['capture_verified'] is not False
            or model['physical_asic_compatibility_verified'] is not False
            or any(frozen.get(str((BASE.parents[1] / name).resolve())) != digest
                   for name, digest in model['sources'].items())):
        raise RuntimeError('host model differs from exact frozen batch or overstates acceptance')
    model_work = (BASE.parents[1] / model['work']).resolve()
    if model_work.parent != (BASE / 'scratch').resolve() or not model_work.name.startswith('functional-model-build-'):
        raise RuntimeError('unexpected host model build directory')
    model_files = ((BASE / 'functional-camera-model.so', 'functional-camera-model.so', model['library_sha256']),
                   (model_work / 'functional-model-sources.tar.gz', 'functional-model-sources.tar.gz', model['source_archive_sha256']),
                   (model_metadata, 'functional-camera-model-build.json', sha(model_metadata)))
    for source, name, expected in model_files:
        content = source.read_bytes()
        if hashlib.sha256(content).hexdigest() != expected:
            raise RuntimeError('host model artifact changed before copying: ' + name)
        with (work / name).open('xb') as output:
            output.write(content)
        if sha(work / name) != expected:
            raise RuntimeError('host model batch artifact readback mismatch: ' + name)
    built = subprocess.run(['bash', str(BASE / 'build-observers.sh')], cwd=BASE,
                           env=dict(os.environ, MENU_RM_FILE='1'),
                           capture_output=True, text=True, timeout=240)
    with (work / 'build.log').open('x') as output:
        output.write(built.stdout + built.stderr)
    if built.returncode:
        raise RuntimeError('observer build failed; retained evidence: ' + str(work))
    build = json.loads((BASE / 'observer-build-inputs.json').read_text())
    if {name: entry['sha256'] for name, entry in build['sources'].items()} != runtime:
        raise RuntimeError('compiled source archive differs from frozen inputs')
    if any(digests(Path(p) for p in group) != group for group in groups.values()):
        raise RuntimeError('frozen inputs changed during build')
    env = {key: value for key, value in os.environ.items()
           if not key.startswith(('MENU_', 'QEMU_', 'SONY_', 'A7C2_'))}
    env['MENU_OBSERVE_SELFTEST'] = '1'
    checked = subprocess.run(old_abi['command'], cwd=BASE, env=env,
                             capture_output=True, text=True, timeout=30)
    abi = {'scope': 'original libc2.25 observer ABI, separate from host codec components',
           'returncode': checked.returncode, 'stdout': checked.stdout, 'stderr': checked.stderr,
           'command': old_abi['command'], 'observer_sha256': build['observer_sha256'],
           'source_archive_sha256': build['source_archive_sha256'], 'source_count': len(runtime),
           'regression_sha256': sha(work / 'host-regression.json'), 'capture_verified': False}
    media = BASE / 'menu-root/simulation/file-media-config.so'
    media_command = [arg.replace('LD_PRELOAD=', 'LD_PRELOAD=' + str(media) + ':')
                     if arg.startswith('LD_PRELOAD=') else arg for arg in old_abi['command']]
    media_checked = subprocess.run(media_command, cwd=BASE, env=dict(env, LD_BIND_NOW='1'),
                                   capture_output=True, text=True, timeout=30)
    abi['media_preload_sha256'] = sha(media)
    abi['media_preload'] = {'command': media_command, 'returncode': media_checked.returncode,
                            'stdout': media_checked.stdout, 'stderr': media_checked.stderr,
                            'bind_now': True}
    save(work / 'abi.json', abi)
    marker = 'PASS: constructor thread and application-init wrapper preserved behavior'
    if checked.returncode or marker not in checked.stdout or media_checked.returncode or marker not in media_checked.stdout:
        raise RuntimeError('original observer/media preload ABI failed; retained evidence: ' + str(work))
    save(work / 'ready.json', {'scope': 'host-tested frozen batch; native end-to-end acceptance still required',
                              'inputs_sha256': sha(work / 'inputs.json'),
                              'regression_sha256': sha(work / 'host-regression.json'),
                              'abi_sha256': sha(work / 'abi.json'),
                              'all_input_archive_sha256': sha(work / 'inputs.tar.gz'),
                              'functional_model_library_sha256': model['library_sha256'],
                              'functional_model_source_archive_sha256': model['source_archive_sha256'],
                              'functional_model_build_receipt_sha256': sha(work / 'functional-camera-model-build.json'),
                              'capture_verified': False})
    print('UNIFIED_CAMERA_TEST_BUILD_ABI_PASS', work, build['observer_sha256'], flush=True)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
