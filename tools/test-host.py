#!/usr/bin/env python3
"""Bounded host-only suite: no VM, compilers, guest helpers or original firmware required."""
import os
from pathlib import Path
import shlex
import sys

ROOT = Path(__file__).resolve().parents[1]
ANALYSIS = ROOT / 'runtime/analysis'
TEMP = Path(os.environ['TMPDIR']) if os.environ.get('TMPDIR') not in (None, '', '/tmp') else ROOT / 'validation/tmp'
TEMP.mkdir(parents=True, exist_ok=True)
os.environ.update(TMPDIR=str(TEMP), PYTHONDONTWRITEBYTECODE='1', DISPLAY='',
                  PYTEST_DISABLE_PLUGIN_AUTOLOAD='1')
sys.dont_write_bytecode = True
sys.path.insert(0, str(ANALYSIS))


def guard(event, args):
    if event != 'subprocess.Popen':
        return
    executable, argv = args[:2]
    words = shlex.split(argv) if isinstance(argv, str) else [os.fsdecode(x) for x in argv]
    if Path(os.fsdecode(executable)).name.startswith('python') and '-c' in words:
        code = words.index('-c') + 1
        words = words[:code] + words[code + 1:]
    forbidden = ('qemu-', 'clang', 'gcc', 'g++', 'ninja', 'make', 'build-observers', 'build-qemu')
    if any(any(mark in Path(word).name for mark in forbidden) or Path(word).name == 'cc'
           for word in [os.fsdecode(executable), *words]):
        raise RuntimeError(f'Host-only suite forbids VM/build command: {words}')


sys.addaudithook(guard)
import pytest

FILES = '''test-assets.py test_bodydata_launch.py test_display_snapshot.py
test_firmware_overlay.py test_initramfs_identity.py test_source_snapshot.py
test_menu_control.py test_usb_network.py test_ethernet_peer.py test_wifi_toggle.py
test_wifi_regressions.py test_camera_ui.py test_sd_export_lifecycle.py
test_sd_flush_barrier.py test_sd_hotplug.py test_sd_retired_export.py test_setting_store.py test_capture_gate_readback.py
test_handoff_lifecycle.py test_live_transport_retention.py test_media_initial_write.py
test_media_predicate_watch.py test_sd_session_retry.py test_ee_entry_snapshot.py
test_startup_caution_compare.py test_body_control_probe.py test_mode_wheel_probe.py
test_focus_controls_probe.py test_settings_checkpoint.py test_settings_instance.py
test_instance_lifecycle.py test_vm_instance_lifecycle.py test_settings_environment.py'''.split()


class HostScope:
    def pytest_collection_modifyitems(self, items):
        # These three integration checks need build products or original firmware.
        integration = {
            'test_profile_is_relocatable_and_does_not_enable_the_guest_interface',
            'test_generated_board_has_the_verified_xhci_geometry',
            'test_gate_cells_match_the_original_getters',
        }
        for item in items:
            if item.name in integration:
                item.add_marker(pytest.mark.skip(reason='outside asset-free/build-free host scope; run full suite after build/import'))


if __name__ == '__main__':
    raise SystemExit(pytest.main(['-q', '--color=no', '-p', 'no:cacheprovider', '--basetemp', str(TEMP / 'pytest'),
                                 *[str(ANALYSIS / name) for name in FILES], *sys.argv[1:]],
                                plugins=[HostScope()]))
