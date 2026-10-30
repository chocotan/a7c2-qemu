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
    for word in [os.fsdecode(executable), *words]:
        name = Path(word).name
        if name.startswith('qemu-') or name in ('bwrap', 'start.sh', 'run-menu-probe.sh',
                                               'start-menu.py', 'build-qemu.sh'):
            raise RuntimeError('Public model tests forbid VM execution: ' + name)


def main():
    names = json.loads((ROOT / 'tools/public-model-tests.json').read_text())
    assert isinstance(names, list) and names and len(set(names)) == len(names)
    paths = []
    for name in names:
        path = Path(name)
        assert not path.is_absolute() and '..' not in path.parts and path.name.startswith('test_')
        resolved = (ROOT / path).resolve()
        assert resolved.is_relative_to(ROOT) and resolved.is_file(), name
        paths.append(str(resolved))
    TEMP.mkdir(parents=True, exist_ok=True)
    # pytest adds test names below this root; AF_UNIX paths must fit in 107 bytes.
    with tempfile.TemporaryDirectory(prefix='a7m-', dir='/var/tmp') as temporary:
        os.environ.update(TMPDIR=temporary, PYTHONDONTWRITEBYTECODE='1', DISPLAY='',
                          PYTEST_DISABLE_PLUGIN_AUTOLOAD='1')
        sys.addaudithook(guard)
        import pytest
        print('HOST_SOFTWARE_MODEL_TESTS; no native AP, original CP or capture acceptance', flush=True)
        return pytest.main(['-q', '--color=no', '--import-mode=importlib', '-p', 'no:cacheprovider',
                            '--basetemp', str(Path(temporary) / 'p'),
                            '--junitxml', str(TEMP / 'result.xml'), *paths, *sys.argv[1:]],
                           plugins=[HostScope()])


if __name__ == '__main__':
    raise SystemExit(main())

