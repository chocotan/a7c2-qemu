#!/usr/bin/env python3
"""Compile and test public software models on the host; never start a camera VM."""
import json
import os
from pathlib import Path
import shlex
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
TEMP = ROOT / 'validation/tmp/public-models'
sys.dont_write_bytecode = True
sys.path.insert(0, str(ROOT / 'runtime/analysis'))
sys.path.insert(0, str(ROOT / 'tools'))

OUTSIDE_HOST_SCOPE = {
    ('runtime/analysis/test_shutter_route_trace.py', 'test_gate_is_fail_closed'):
        'launcher rejection integration; host byte/width/error-preservation tests run separately',
    ('runtime/analysis/test_vef_path_device.py',
     'test_observer_resource_wiring_and_pre_vm_rejection'):
        'launcher rejection integration; validate with package adapters/native opt-in suite',
    ('runtime/analysis/test_cp_property_stage_file.py',
     'test_public_stage_file_loader_with_original_aarch64_libc'):
        'original Sony glibc and QEMU-user integration; validate with native asset opt-in suite',
    ('runtime/analysis/test_fsys_async_observer.py',
     'test_async_write_observer_is_explicit_passthrough_and_profile_gated'):
        'launcher rejection integration; validate with package adapters/native opt-in suite',
    ('runtime/analysis/test_natural_start_trace.py',
     'test_gate_is_validated_and_does_not_enable_legacy_entry_bundle'):
        'launcher rejection integration; validate with package adapters/native opt-in suite',
    ('runtime/analysis/test_request_queue_watch.py',
     'test_debug_flags_are_rejected_before_VM_or_display_start'):
        'launcher rejection integration; validate with package adapters/native opt-in suite',
    ('runtime/analysis/test_tcin_device.py', 'test_explicit_profile_and_binding'):
        'launcher rejection integration; other host C/sanitizer and optional asset pin tests remain enabled',
    ('runtime/analysis/test_touch_panel.py', 'test_observer_and_profile_gates'):
        'launcher rejection integration; other host C/sanitizer tests remain enabled',
    **{(path, test): 'original Sony assets or ABI integration; outside host software-model publication'
       for path, test in (
           ('runtime/analysis/test_functional_face_dmm.py', 'test_final_wire_source_pins'),
           ('runtime/analysis/test_functional_face_dmm.py', 'test_inherited_original_source_and_config_pins'),
           ('runtime/analysis/test_functional_face_dmm.py', 'test_aarch64_hand_declared_guest_libc_225'),
           ('runtime/analysis/test_functional_face_registry.py', 'test_aarch64_hand_declared_guest_libc_225'),
           ('runtime/analysis/test_functional_face_runtime.py', 'test_aarch64_guest_libc_225_no_undefined'),
           ('runtime/analysis/test_functional_face_transfer.py', 'test_aarch64_guest_libc_225_link_only'),
           ('runtime/analysis/test_functional_face_ap_observer.py', 'test_aarch64_original_libc225_link_only'),
           ('runtime/analysis/test_functional_face_native_ap.py', 'test_aarch64_guest_libc_225_link_only'),
           ('runtime/analysis/test_functional_face_sdk.py', 'test_aarch64_guest_libc_225_link_only'),
           ('runtime/analysis/test_functional_face_source_snapshot.py', 'test_source_snapshot_guest_aarch64_libc_225_link_only'),
       )},
    **{(path, test): 'original Sony glibc and QEMU-user integration; validate with native asset opt-in suite'
       for path, test in (
           ('report/native-video-producer-contract/test_producer.py', 'test_all_modes_with_original_aarch64_libc'),
           ('report/lif-capability-owner/test_capabilities.py', 'test_all_behaviors_with_original_aarch64_libc'),
           ('report/lif-cache-admission-contract/test_cache.py', 'test_all_behaviors_with_original_aarch64_libc'),
           ('report/native-video-record-fill/test_fill.py', 'test_all_modes_with_original_aarch64_libc'),
           ('report/imola-mbp-mailbox/test_mailbox.py', 'test_all_modes_with_original_aarch64_libc'),
           ('report/imola-vbb-normalize/test_normalize.py', 'test_all_modes_with_original_aarch64_libc'),
       )},
}


class HostScope:
    def pytest_collection_modifyitems(self, items):
        import pytest
        for item in items:
            key = (item.path.relative_to(ROOT).as_posix(), item.name)
            if key in OUTSIDE_HOST_SCOPE:
                item.add_marker(pytest.mark.skip(reason='outside public host software-model scope: '
                                                + OUTSIDE_HOST_SCOPE[key]))



def guard(event, args):
    if event != 'subprocess.Popen':
        return
    executable, argv = args[:2]
    words = shlex.split(argv) if isinstance(argv, str) else [os.fsdecode(x) for x in argv]
    program = Path(os.fsdecode(executable)).name
    commands = [program]
    if program in ('bash', 'sh', 'dash'):
        if '-n' not in words:
            if '-c' in words:
                commands.extend(shlex.split(words[words.index('-c') + 1]))
            else:
                commands.extend(word for word in words[1:] if not word.startswith('-'))
    elif program.startswith('python') and '-c' not in words and '-m' not in words:
        commands.extend(word for word in words[1:] if not word.startswith('-'))
    for word in commands:
        name = Path(word).name
        if name.startswith('qemu-') or name in ('bwrap', 'start.sh', 'run-menu-probe.sh',
                                               'start-menu.py', 'build-qemu.sh'):
            raise RuntimeError('Public model tests forbid VM execution: ' + name)


def main():
    names = json.loads((ROOT / 'tools/public-model-tests.json').read_text())
    if (not isinstance(names, list) or not names or any(type(name) is not str for name in names)
            or len(set(names)) != len(names)):
        raise ValueError('Expected a nonempty unique list of relative test paths')
    paths = []
    for name in names:
        path = Path(name)
        if (path.is_absolute() or '..' in path.parts or path.as_posix() != name or
                not (path.name.startswith('test_') or name == 'runtime/analysis/test-menu-control.py')):
            raise ValueError('Invalid public test path: ' + name)
        resolved = (ROOT / path).resolve()
        if not resolved.is_relative_to(ROOT) or not resolved.is_file():
            raise ValueError('Missing or escaping public test path: ' + name)
        paths.append(str(resolved))
    TEMP.mkdir(parents=True, exist_ok=True)
    # Respect the caller's isolated temp root; socket fixtures use directory FDs for long paths.
    with tempfile.TemporaryDirectory(prefix='a7m-', dir=os.environ.get('TMPDIR') or '/var/tmp') as temporary:
        os.environ.update(TMPDIR=temporary, PYTHONDONTWRITEBYTECODE='1', DISPLAY='',
                          PYTEST_DISABLE_PLUGIN_AUTOLOAD='1')
        sys.addaudithook(guard)
        import pytest
        import public_asset_tests
        print('HOST_SOFTWARE_MODEL_TESTS; no native AP, original CP or capture acceptance', flush=True)
        return pytest.main(['-q', '--color=no', '--import-mode=importlib', '-p', 'no:cacheprovider',
                            '--basetemp', str(Path(temporary) / 'p'),
                            '--junitxml', str(TEMP / 'result.xml'), *paths, *sys.argv[1:]],
                           plugins=[HostScope(), public_asset_tests])


if __name__ == '__main__':
    raise SystemExit(main())

