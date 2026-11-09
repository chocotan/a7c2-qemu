"""Host-only regression checks for the public model test runner itself."""
import importlib.util
import json
import os
from pathlib import Path
import socket
import stat
import subprocess
import sys
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('public_models_runner', ROOT / 'tools/test-public-models.py')
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)


@pytest.mark.parametrize('raises', [False, True])
def test_short_private_root_supports_host_sockets_and_is_cleaned(tmp_path, monkeypatch, raises):
    package = tmp_path / 'package'
    (package / 'tools').mkdir(parents=True)
    case = package / 'runtime/analysis/test_example.py'
    case.parent.mkdir(parents=True)
    case.write_text('def test_example(): pass\n')
    (package / 'tools/public-model-tests.json').write_text(json.dumps(['runtime/analysis/test_example.py']))
    monkeypatch.setattr(runner, 'ROOT', package)
    monkeypatch.setattr(runner, 'TEMP', package / 'validation/tmp/public-models')
    monkeypatch.setattr(sys, 'argv', ['test-public-models.py'])
    hooks = []
    monkeypatch.setattr(sys, 'addaudithook', hooks.append)
    temporary_parent = Path(os.environ.get('TMPDIR') or '/var/tmp')
    monkeypatch.setenv('TMPDIR', str(temporary_parent))
    for key in ('PYTHONDONTWRITEBYTECODE', 'DISPLAY', 'PYTEST_DISABLE_PLUGIN_AUTOLOAD'):
        monkeypatch.setenv(key, 'inherited')
    observed = []

    def run(arguments, plugins):
        temporary = Path(os.environ['TMPDIR'])
        observed.append(temporary)
        info = temporary.lstat()
        assert temporary.parent == temporary_parent
        assert stat.S_ISDIR(info.st_mode) and stat.S_IMODE(info.st_mode) == 0o700
        assert info.st_uid == os.getuid() and not temporary.is_symlink()
        base = Path(arguments[arguments.index('--basetemp') + 1])
        assert base == temporary / 'p'
        assert arguments[arguments.index('--junitxml') + 1] == str(runner.TEMP / 'result.xml')
        assert str(case) in arguments and isinstance(plugins[0], runner.HostScope)
        assert os.environ['PYTEST_DISABLE_PLUGIN_AUTOLOAD'] == '1'
        assert os.environ['PYTHONDONTWRITEBYTECODE'] == '1' and os.environ['DISPLAY'] == ''
        directory = base / ('test_' + 'x' * 25 + '0')
        directory.mkdir(parents=True)
        path = directory / 'gdb.sock'
        fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
        try:
            endpoint = f'/proc/self/fd/{fd}/{path.name}'
            assert len(os.fsencode(endpoint)) < 108
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as listener:
                listener.bind(endpoint)
            assert path.is_socket()
        finally:
            os.close(fd)
        if raises:
            raise RuntimeError('intentional pytest failure')
        return 7

    monkeypatch.setattr(pytest, 'main', run)
    if raises:
        with pytest.raises(RuntimeError, match='intentional pytest failure'):
            runner.main()
    else:
        assert runner.main() == 7
    assert hooks == [runner.guard]
    assert len(observed) == 1 and not observed[0].exists()


@pytest.mark.parametrize('argv', [
    ['qemu-system-aarch64', '--version'],
    ['/somewhere/qemu-aarch64', '-L', '/guest', '/test'],
    ['bwrap', '--unshare-net', '/bin/true'],
    ['bash', 'start.sh'],
    ['bash', 'run-menu-probe.sh'],
    ['python3', 'start-menu.py'],
    ['python3', 'qemu-menu-probe.py'],
    ['bash', 'build-qemu.sh'],
])
def test_no_vm_guard_still_rejects_entrypoints(argv):
    with pytest.raises(RuntimeError, match='forbid VM execution'):
        runner.guard('subprocess.Popen', (argv[0], argv))


def test_guard_allows_host_compilation_and_execution():
    for argv in (['cc', '-Wall', '-Werror', 'test.c', '-o', 'test'],
                 ['clang', '-fsanitize=address,undefined', 'test.c'], ['/var/tmp/a7m-test/p/test'],
                 ['debugfs', '-R', 'dump /bin/qemu-packaged-system-check-v1 output', 'copied.ext2'],
                 ['bash', '-n', 'qemu-kernel-probe.sh']):
        runner.guard('subprocess.Popen', (argv[0], argv))


def test_real_audit_hook_blocks_execution_in_a_child_interpreter():
    code = '''
import importlib.util, subprocess, sys
spec = importlib.util.spec_from_file_location('guarded_public_models', sys.argv[1])
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)
sys.addaudithook(runner.guard)
for name in ('qemu-system-aarch64', 'qemu-aarch64', 'bwrap', 'start.sh'):
    try:
        subprocess.run(['/a7c2-do-not-execute/' + name], check=True)
    except RuntimeError as error:
        assert 'forbid VM execution' in str(error)
    else:
        raise AssertionError('subprocess audit did not reject ' + name)
print('all execution attempts rejected before exec')
'''
    result = subprocess.run([sys.executable, '-c', code, str(ROOT / 'tools/test-public-models.py')],
                            check=True, capture_output=True, text=True, timeout=10)
    assert result.stdout.strip() == 'all execution attempts rejected before exec'


def test_scope_skips_only_declared_asset_and_launcher_integrations():
    expected = {
        ('report/functional-capture-input/test_capture_input.py','test_original_ssyc_writer_and_typed_reader'),
        ('report/functional-capture-queue/test_capture_queue.py','test_original_router_ack_main_and_comp_consume_same_retained_frame'),
        ('report/functional-capture-queue/test_capture_queue.py','test_original_sender_wait_ack_callback_and_real_P128_store'),
        ('runtime/analysis/test_shutter_route_trace.py', 'test_gate_is_fail_closed'),
        ('runtime/analysis/test_vef_path_device.py', 'test_observer_resource_wiring_and_pre_vm_rejection'),
        ('runtime/analysis/test_natural_start_trace.py', 'test_gate_is_validated_and_does_not_enable_legacy_entry_bundle'),
        ('runtime/analysis/test_request_queue_watch.py', 'test_debug_flags_are_rejected_before_VM_or_display_start'),
        ('runtime/analysis/test_tcin_device.py', 'test_explicit_profile_and_binding'),
        ('runtime/analysis/test_touch_panel.py', 'test_observer_and_profile_gates'),
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
        ('runtime/analysis/test_cp_property_stage_file.py', 'test_public_stage_file_loader_with_original_aarch64_libc'),
        ('runtime/analysis/test_fsys_async_observer.py', 'test_async_write_observer_is_explicit_passthrough_and_profile_gated'),
        ('report/native-video-producer-contract/test_producer.py', 'test_all_modes_with_original_aarch64_libc'),
        ('report/lif-capability-owner/test_capabilities.py', 'test_all_behaviors_with_original_aarch64_libc'),
        ('report/lif-cache-admission-contract/test_cache.py', 'test_all_behaviors_with_original_aarch64_libc'),
        ('report/native-video-record-fill/test_fill.py', 'test_all_modes_with_original_aarch64_libc'),
        ('report/imola-mbp-mailbox/test_mailbox.py', 'test_all_modes_with_original_aarch64_libc'),
        ('report/imola-vbb-normalize/test_normalize.py', 'test_all_modes_with_original_aarch64_libc'),
    }
    assert set(runner.OUTSIDE_HOST_SCOPE) == expected
    items = []
    for file, name in [*expected,
                       *((file, name + '_host') for file, name in expected),
                       *((('report/unlisted/' + Path(file).name), name) for file, name in expected),
                       ('runtime/analysis/other.py', 'test_observer_resource_wiring_and_pre_vm_rejection'),
                       ('runtime/analysis/test_cp_property_stage_file.py', 'test_missing_public_evidence'),
                       ('report/unlisted/test_other.py', 'test_all_modes_with_original_aarch64_libc')]:
        markers = []
        items.append(SimpleNamespace(path=runner.ROOT / file, name=name, markers=markers,
                                     add_marker=markers.append))
    runner.HostScope().pytest_collection_modifyitems(items)
    for item in items:
        excluded = (item.path.relative_to(runner.ROOT).as_posix(), item.name) in expected
        assert len(item.markers) == int(excluded)
        if excluded:
            assert item.markers[0].name == 'skip'
            assert 'outside public host software-model scope' in item.markers[0].kwargs['reason']


def test_model_list_preserves_host_callers_and_explicit_external_stages():
    names = json.loads((ROOT / 'tools/public-model-tests.json').read_text())
    assert isinstance(names, list) and len(names) == len(set(names)) == 253
    assert {'source/persistent-flash/test_freeze.py','runtime/analysis/test_factory_images.py','runtime/analysis/test_observer_process_scope.py','runtime/analysis/test_original_cold_boot.py'} <= set(names)
    assert {
        'runtime/analysis/test-menu-control.py',
        'runtime/analysis/test_key_injection.py',
        'runtime/analysis/test_natural_start_trace.py',
        'runtime/analysis/test_reader_boot_wait.py',
        'runtime/analysis/test_request_queue_watch.py',
        'runtime/analysis/test_tcin_device.py',
        'runtime/analysis/test_touch_panel.py',
        'runtime/analysis/test_udate_distribution.py',
        'runtime/analysis/test_shutter_gate_batch_inventory.py',
        'report/2026-10-31-qemu-shutter-gate-observer-v1/test_build_runtime.py',
        'report/2026-10-31-qemu-shutter-gate-observer-v1/integration/test_fixture_driver.py',
        'report/2026-10-31-qemu-shutter-gate-observer-v1/integration/test_shutter_gate_trace_checks_v1.py',
        'runtime/analysis/test_menu_control.py',
        'runtime/analysis/test_natural_gtk_input_receipts.py',
        'runtime/analysis/test_functional_camera_runner.py',
        'runtime/analysis/test_scope_observer_profile.py',
        'report/2026-10-30-qemu-readonly-scope-observer/test_run_context.py',
        'report/2026-10-31-qemu-M-writer-observer-v3/test_run_context.py',
    } <= set(names)
    assert not {
        'runtime/analysis/test_body_control_probe.py',
        'runtime/analysis/test_focus_controls_probe.py',
        'runtime/analysis/test_media_predicate_watch.py',
        'report/2026-10-31-qemu-shutter-gate-observer-v1/test_scope_observer.py',
        'report/2026-10-31-qemu-shutter-gate-observer-v1/test_run_context.py',
        'report/2026-10-31-qemu-shutter-gate-observer-v1/integration/test_actual_scope_plugin.py',
    } & set(names)


@pytest.mark.parametrize('name', [
    'runtime/analysis/test-menu-control.py',
    'runtime/analysis/test_menu_control.py',
    'report/2026-10-30-qemu-readonly-scope-observer/integration/test_actual_scope_plugin.py',
    'report/2026-10-31-qemu-M-writer-observer-v3/integration/test_actual_scope_plugin.py',
    'report/2026-10-31-qemu-shutter-gate-observer-v1/integration/test_actual_scope_plugin.py',
])
def test_explicit_paths_reach_collection_without_basename_exclusions(tmp_path, monkeypatch, name):
    (tmp_path / 'tools').mkdir()
    case = tmp_path / name
    case.parent.mkdir(parents=True)
    case.write_text('raise AssertionError("synthetic module must not execute")\n')
    (tmp_path / 'tools/public-model-tests.json').write_text(json.dumps([name]))
    monkeypatch.setattr(runner, 'ROOT', tmp_path)
    monkeypatch.setattr(runner, 'TEMP', tmp_path / 'validation/tmp/public-models')
    monkeypatch.setattr(sys, 'argv', ['test-public-models.py'])
    hooks = []
    monkeypatch.setattr(sys, 'addaudithook', hooks.append)
    monkeypatch.setenv('TMPDIR', os.environ.get('TMPDIR') or '/var/tmp')
    for key in ('PYTHONDONTWRITEBYTECODE', 'DISPLAY', 'PYTEST_DISABLE_PLUGIN_AUTOLOAD'):
        monkeypatch.setenv(key, 'inherited')
    collected = []

    def collect(arguments, plugins):
        assert arguments.count(str(case.resolve())) == 1
        assert len(plugins) == 2 and isinstance(plugins[0], runner.HostScope)
        markers = []
        item = SimpleNamespace(path=case, name='test_real_qemu_shutter_gate_v1_direct_raw_and_independent_operands',
                               add_marker=markers.append)
        plugins[0].pytest_collection_modifyitems([item])
        assert markers == []
        collected.append(str(case.resolve()))
        return 7

    monkeypatch.setattr(pytest, 'main', collect)
    assert runner.main() == 7
    assert hooks == [runner.guard] and collected == [str(case.resolve())]


@pytest.mark.parametrize('name', [
    'runtime/analysis/test-other.py',
    'runtime/analysis/test-menu-control-extra.py',
    'report/other/test-menu-control.py',
    'runtime/analysis/./test-menu-control.py',
    'runtime/analysis/../analysis/test-menu-control.py',
    pytest.param(None, id='existing-absolute-path'),
])
def test_existing_other_dash_or_escaping_paths_remain_errors(tmp_path, monkeypatch, name):
    (tmp_path / 'tools').mkdir()
    case = (tmp_path / (name or 'runtime/analysis/test_example.py')).resolve()
    case.parent.mkdir(parents=True)
    case.write_text('raise AssertionError("invalid path must not execute")\n')
    if name is None:
        name = str(case)
    (tmp_path / 'tools/public-model-tests.json').write_text(json.dumps([name]))
    monkeypatch.setattr(runner, 'ROOT', tmp_path)
    monkeypatch.setattr(runner, 'TEMP', tmp_path / 'validation/tmp/public-models')
    hooks = []
    monkeypatch.setattr(sys, 'addaudithook', hooks.append)
    monkeypatch.setattr(pytest, 'main', lambda *args, **kwargs: pytest.fail('invalid path reached collection'))
    with pytest.raises(ValueError):
        runner.main()
    assert hooks == [] and not runner.TEMP.exists()


@pytest.mark.parametrize('name', ['runtime/analysis/test_missing.py', '../test_outside.py', '/test_absolute.py'])
def test_missing_or_escaping_files_remain_errors(tmp_path, monkeypatch, name):
    (tmp_path / 'tools').mkdir()
    (tmp_path / 'tools/public-model-tests.json').write_text(json.dumps([name]))
    monkeypatch.setattr(runner, 'ROOT', tmp_path)
    with pytest.raises(ValueError):
        runner.main()
