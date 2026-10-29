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
    for key in ('TMPDIR', 'PYTHONDONTWRITEBYTECODE', 'DISPLAY', 'PYTEST_DISABLE_PLUGIN_AUTOLOAD'):
        monkeypatch.setenv(key, 'inherited')
    observed = []

    def run(arguments, plugins):
        temporary = Path(os.environ['TMPDIR'])
        observed.append(temporary)
        info = temporary.lstat()
        assert temporary.parent == Path('/var/tmp')
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
        assert len(os.fsencode(path)) < 108
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as listener:
            listener.bind(str(path))
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
                 ['clang', '-fsanitize=address,undefined', 'test.c'], ['/var/tmp/a7m-test/p/test']):
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
        ('runtime/analysis/test_vef_path_device.py', 'test_observer_resource_wiring_and_pre_vm_rejection'),
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


@pytest.mark.parametrize('name', ['runtime/analysis/test_missing.py', '../test_outside.py', '/test_absolute.py'])
def test_missing_or_escaping_files_remain_errors(tmp_path, monkeypatch, name):
    (tmp_path / 'tools').mkdir()
    (tmp_path / 'tools/public-model-tests.json').write_text(json.dumps([name]))
    monkeypatch.setattr(runner, 'ROOT', tmp_path)
    with pytest.raises(AssertionError):
        runner.main()
