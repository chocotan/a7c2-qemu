"""Asset-free checks for the relocated public package adapters."""
import ast
import importlib.util
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
ANALYSIS = ROOT / 'runtime/analysis'
sys.path.insert(0, str(ANALYSIS))


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


launcher = load('package_adapter_launcher', ANALYSIS / 'start-menu.py')


def test_package_root_and_default_profile():
    assert launcher.ROOT == ROOT
    env = launcher.profile_environment({}, natural_boot=True)
    assert env['A7C2_SD_HOTPLUG'] == '1'
    assert env['MENU_RM_FILE'] == '1'
    assert not any(name in env for name in ('MENU_FUNCTIONAL_CAMERA', 'MENU_YC_INJECT',
                                           'MENU_BB_READY_INJECT', 'MENU_CP_CAPTURE_FORMAT'))
    assert 'A7C2_SD_HOTPLUG' not in launcher.profile_environment({})
    assert launcher.profile_environment({'A7C2_SD_HOTPLUG': ''}, natural_boot=True)['A7C2_SD_HOTPLUG'] == ''


@pytest.mark.parametrize('selection', [
    {'A7C2_DIRECTORY_SD': '/tmp/public-adapter-card'},
    {'A7C2_HOST_SD': '256gb'},
    {'A7C2_SD_SPARSE': '10g-empty'},
    {'MENU_RM_SLOT1': '1'},
])
def test_default_hotplug_stays_out_of_other_backends(selection):
    assert 'A7C2_SD_HOTPLUG' not in launcher.profile_environment(selection, natural_boot=True)


@pytest.mark.parametrize('name', '''IMAGING_CONNECT IMAGING_CONTROL_CONNECT IMAGING_ADF_CONNECT
INFRABB_VEF_CONNECT INFRABB_VEF_CONTROL_CONNECT VEF_PINMEM_INPUT_CONNECT
VEF_PINMEM_CONTROL_CONNECT PINMEM_PEER_CONNECT ADF_HDMI_AUDIO_CONNECT
PINMEM_HDMI_VIDEO_CONNECT PINMEM_OSD_CONNECT CP_CAPTURE_FORMAT FUNCTIONAL_CAMERA'''.split())
@pytest.mark.parametrize('value', ['unknown', True, 1])
def test_unknown_or_untyped_profiles_still_fail_closed(name, value):
    with pytest.raises(ValueError):
        launcher.profile_environment({'A7C2_' + name: value}, natural_boot=True)


def test_seed_and_http_route_stay_package_local():
    seed = (ANALYSIS / 'prepare-menu-initramfs.sh').read_text()
    assert 'qemu-boot-research' not in seed and 'real_setting' not in seed
    assert 'CX89701_ALLLANG.bin' in seed and 'native-assets.json' in seed
    assert 'MENU_YC_INPUT_RAW' in seed and 'simulation/yc-input.gray' in seed
    controller = (ANALYSIS / 'menu_control.py').read_text()
    assert '/history.png' not in controller and 'qemu-boot-research' not in controller
    assert 'require_capture_closed' in controller and 'wait_functional_camera_owner' in controller


def test_three_patch_order_and_hardware_staging():
    check_source = load('package_adapter_check_source', ROOT / 'tools/check-source.py')
    assert [patch for _, patch in check_source.PATCH_STAGES] == [
        'qemu-sony-native.patch', 'qemu-directory-sd.patch', 'qemu-sony-usb.patch']
    script = (ROOT / 'build-qemu.sh').read_text()
    stages = [script.index('< "$here/source/' + patch + '"') for _, patch in check_source.PATCH_STAGES]
    assert stages == sorted(stages)
    assert stages[-1] < script.index('"$here/report/virtual-pcidma/stage_hardware.py"')
    assert '--disable-download' in script and '--unshare-net' in script
    assert '--enable-vvfat' in script and '--enable-qcow1' in script


def test_build_help_and_missing_archive_need_no_assets(tmp_path):
    script = tmp_path / 'offline-help.sh'
    script.write_bytes((ROOT / 'build-qemu.sh').read_bytes())
    for args in (['--help'], ['--stage-only', '--help']):
        result = subprocess.run(['bash', str(script), *args], capture_output=True, text=True)
        assert result.returncode == 0 and 'Offline' in result.stdout and '--stage-only' in result.stdout
    result = subprocess.run(['bash', str(script)], capture_output=True, text=True)
    assert result.returncode == 2 and 'Missing QEMU source' in result.stderr
    assert not (tmp_path / 'source').exists() and not (tmp_path / 'runtime').exists()


def test_reference_resolver_uses_package_receipt_and_validates_explicit_stage(tmp_path):
    package = tmp_path / 'package with spaces'
    analysis = package / 'runtime/analysis'
    analysis.mkdir(parents=True)
    stage = package / 'source/build/qemu-current'
    required = ('build/build.ninja', 'qemu-11.1.2/hw/arm/virt.c', 'qemu-11.1.2/hw/misc/meson.build',
                'qemu-11.1.2/hw/intc/arm_gic_common.c', 'qemu-11.1.2/include/hw/intc/arm_gic_common.h',
                'qemu-11.1.2/hw/misc/sony-pcidma/sony_regfile.c')
    for name in required:
        path = stage / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('synthetic reference source prerequisite\n')
    receipt = package / 'source/pci-hardware-build.json'
    receipt.write_text(json.dumps({'build_directory': 'source/build/qemu-current'}))
    text = (ANALYSIS / 'build-rc-reference.sh').read_text()
    resolver = text[text.index('stage="$(python3'):text.index('src="$stage/qemu-11.1.2"')]
    command = 'set -euo pipefail\nanalysis_dir=$1\nshift\n' + resolver + '\nprintf "%s\\n" "$stage"\n'

    def resolve(*args):
        return subprocess.run(['bash', '-c', command, 'reference-resolver', str(analysis), *args],
                              capture_output=True, text=True)

    for args in ((), (str(stage),)):
        result = resolve(*args)
        assert result.returncode == 0 and result.stdout.strip() == str(stage)
    receipt.write_text(json.dumps({'build_directory': '../outside'}))
    result = resolve()
    assert result.returncode != 0 and 'relative build directory' in result.stderr
    (stage / required[-1]).unlink()
    result = resolve(str(stage))
    assert result.returncode != 0 and 'prerequisite missing' in result.stderr
    assert not (analysis / '.menu-probe.lock').exists()


def test_host_guard_treats_python_code_as_code_not_executable_name():
    tree = ast.parse((ROOT / 'tools/test-host.py').read_text())
    definition = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == 'guard')
    scope = {'os': os, 'Path': Path, 'shlex': shlex}
    exec(compile(ast.Module(body=[definition], type_ignores=[]), '<public-host-guard>', 'exec'), scope)
    guard = scope['guard']
    guard('subprocess.Popen', (sys.executable, [sys.executable, '-u', '-c',
          "from pathlib import Path; Path('qemu-menu-probe.py').read_text()", 'runtime/analysis']))
    for executable, argv in [('/usr/bin/qemu-system-aarch64', ['qemu-system-aarch64']),
                             ('cc', ['cc', 'test.c']), ('clang', ['clang', 'test.c']),
                             ('bash', ['bash', '-c', 'qemu-system-aarch64'])]:
        with pytest.raises(RuntimeError, match='forbids'):
            guard('subprocess.Popen', (executable, argv))
