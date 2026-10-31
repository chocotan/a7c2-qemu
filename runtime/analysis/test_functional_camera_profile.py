"""Independent functional-profile intent and actual guest shell exports."""
import ast
import json
from pathlib import Path
from unittest import mock

import pytest

import backup_profile as backup
from test_bb_set_mode_profile import bb_constructor, clean_guest_environment, load_script, menu_probe_setup
from test_cp_capture_format_profile import host_environment

HERE = Path(__file__).resolve().parent
PROFILE = 'virtual-functional-camera-v1'
HOST = 'A7C2_FUNCTIONAL_CAMERA'
GUEST = 'MENU_FUNCTIONAL_CAMERA'
CLAIMS = (
    'physical_ASIC_compatibility_verified', 'original_CP_executed',
    'original_CP_RAM_verified', 'original_VDF_selector_verified', 'original_VDF_CP_FIFO_verified',
    'original_Zebra_gate_verified', 'original_VDF_area_order_verified',
    'original_VDF_layout_hardware_verified', 'original_Peaking_operator_verified',
    'original_0162_feature_verified', 'original_BB_C_configuration_work_verified',
    'original_BB_C_configuration_units_verified', 'original_Histogram_bin_semantics_verified',
    'original_Histogram_physical_callback_verified', 'histogram_UI_applied_verified',
    'original_Xsync_state_producer_verified', 'physical_Xsync_capability_verified',
    'cp_background_start_original_modules_verified',
    'cp_face_dmm_original_AP_consumption_verified', 'cp_face_dmm_physical_bank_verified',
    'cp_face_dmm_native_ap_backend_verified', 'cp_face_dmm_native_birth_complete_verified',
    'cp_face_dmm_functional_source_snapshot_verified', 'cp_face_dmm_original_global_writer_exclusion_verified',
    'backend_readiness_verified',
    'original_AP_consumption_verified', 'frame_consumption_verified',
    'original_MPR_Fsys_write_verified', 'standalone_host_media_write',
    'capture_verified',
)


def environment(tmp_path):
    env = host_environment(tmp_path)
    env['A7C2_CP_CAPTURE_FORMAT'] = backup.FULL_CP_OWNED_STATE_PROFILE
    env[HOST] = PROFILE
    return env


def test_functional_intent_is_software_hardware_not_runtime_acceptance():
    assert backup.FUNCTIONAL_CAMERA_PROFILE == PROFILE
    assert '#define FCAM_PROFILE "' + PROFILE + '"' in (HERE / 'functional-camera-abi.h').read_text()
    selected = backup.functional_camera_profile_fields(PROFILE)
    off = backup.functional_camera_profile_fields('')
    assert selected.keys() == off.keys()
    assert selected['functional_camera_abi_version'] == 1
    assert selected['functional_camera_image_bus'] == 'virtual-RGB888-top-row-first'
    assert selected['functional_camera_cp_background_start_policy'] == 'original-3006-pending-all13-free-model-INIT-STATE-readback-before-independent-reply'
    assert selected['functional_camera_cp_background_start_native_commands'] == [0x3006]
    assert selected['functional_camera_cp_background_start_deferred_until'] == 'same-run-all13-original-free-and-actual-debugger-handoff'
    assert selected['functional_camera_cp_face_dmm_policy'] == 'original-five-callsite-byte-pins-owned-backing-receive-free-before-ledger'
    assert selected['functional_camera_cp_face_dmm_units'] == [0x1d9, 0x1da, 0x1db]
    assert selected['functional_camera_cp_face_dmm_commands'] == [0x20, 0x21, 0x23, 0x24, 0x25]
    assert selected['functional_camera_cp_face_dmm_software_iova'] == [0x70000000, 0x70100000, 0x70200000]
    assert selected['functional_camera_cp_face_dmm_iova_policy'] == 'software-only-no-implicit-AP-physical-translation'
    assert selected['functional_camera_cp_face_dmm_lifecycle'] == 'one-creator-lifecycle-per-unit-per-process-no-wire-wrap'
    assert selected['functional_camera_cp_face_dmm_transfer_content_policy'] == 'saved-AP-lease-disjoint-proof-full-write-independent-readback-release-before-content-complete'
    assert selected['functional_camera_cp_face_dmm_transfer_sdk48_decode'] == 'class1-two-stable-eight-byte-descriptors-preserve-callback-context-result-padding'
    assert selected['functional_camera_cp_face_dmm_ap_observer_policy'] == 'passive-original-code-pinned-send-receive-free-record-no-pin-no-byte-capability'
    assert selected['functional_camera_cp_face_dmm_ap_observer_commands'] == [0x20, 0x21, 0x23, 0x24, 0x25]
    assert selected['functional_camera_cp_face_dmm_ap_observer_units'] == [0x1d9, 0x1da, 0x1db, 0x1dc]
    assert selected['functional_camera_cp_face_dmm_ap_observer_kernel_2a_observed'] is False
    assert selected['functional_camera_cp_face_dmm_sdk_observer_policy'] == 'passive-original-valloc48-sync-enter-return-free-no-callback-no-result-write'
    assert selected['functional_camera_cp_face_dmm_sdk_literal_result_observed'] is False
    assert selected['functional_camera_cp_face_dmm_native_ap_provider_policy'] == 'required-original-owner-open-close-free-tickets-mapping-writer-no-default-backend'
    assert selected['functional_camera_cp_face_dmm_native_birth_proc_policy'] == 'original20-free0-two-complete-proc-reads-diagnostic-no-atomicity'
    assert selected['functional_camera_cp_face_dmm_functional_source_snapshot_policy'] == 'original-owner-open-paused-CPU-AS-full-source-read-retained-readback-no-global-writer-claim'
    assert selected['functional_camera_cp_face_dmm_transfer_source_policy'] == 'required-native-pinned-span-no-default-provider'
    assert not any(selected['functional_camera_cp_face_dmm_' + key] for key in
                   ('segment_query_supported', 'interchip_transfer_supported', 'original_completion_transport_supported',
                    'original_AP_consumption_verified', 'physical_bank_verified'))
    assert selected['functional_camera_vdf_path_policy'] == 'canonical-0138-single-RGB-sink-readback-before-1138'
    assert selected['functional_camera_vdf_virtual_endpoint'] == 0x90590819
    assert type(selected['functional_camera_vdf_virtual_completion_mask']) is int
    assert selected['functional_camera_vdf_virtual_completion_mask'] == 1
    assert selected['functional_camera_zebra_policy'] == 'original-0153-disabled-pass-through-RGB-sink-readback-before-1153'
    assert selected['functional_camera_layout_policy'] == 'original-014c-initial-case0-full-RGB-passthrough-readback-before-114c'
    assert selected['functional_camera_startup_layout_policy'] == 'guest-local-canonical-initial-register-stage-before-active-route'
    assert selected['functional_camera_startup_layout_stage_only'] is True
    assert selected['functional_camera_startup_layout_frame_completion'] is False
    assert selected['functional_camera_layout_virtual_area_order'] == 'x-y-width-height'
    assert selected['functional_camera_layout_virtual_zero_output'] == 'full-frame-pass-through'
    assert selected['functional_camera_layout_supported_rgb_geometry'] == [640, 480, 1920]
    assert bytes.fromhex(selected['functional_camera_layout_initial_body_hex']) == bytes.fromhex('07010100000000008002e0010000000000000000000000000300000000000000')
    assert selected['functional_camera_display_config_policy'] == 'original-0141-refresh-0152-disabled-and-0162-off-RGB-readback-before-independent-reply'
    assert selected['functional_camera_display_bit_width_policy'] == 'original-015e-selector0-virtual-RGB888-readback-before-115e'
    assert selected['functional_camera_display_bit_width_commands'] == [0x15e]
    assert selected['functional_camera_display_bit_width_supported_selectors'] == [0]
    assert selected['functional_camera_display_bit_width_selector_mapping'] == 'explicit-software-only-physical-selector-meaning-unverified'
    assert selected['functional_camera_display_bit_width_physical_mapping_verified'] is False
    assert off['functional_camera_display_bit_width_physical_mapping_verified'] is None
    assert selected['functional_camera_still_format_policy'] == 'original402d-observed-L-Fine-dual-slot-RGB-identity-readback-before-echo-f000'
    assert selected['functional_camera_still_format_commands'] == [0x402d]
    assert selected['functional_camera_still_format_request_bytes'] == 24
    assert selected['functional_camera_still_format_canonical16_hex'] == '02000001000100000001000100000000'
    assert selected['functional_camera_still_format_opaque_tail_policy'] == 'preserve-original22-23-not-consumed-canonical-tail-zero'
    assert selected['functional_camera_still_format_initial_diagnostic_policy'] == 'preserved-one-shot-before-functional-model-active'
    assert selected['functional_camera_still_format_physical_selector_mapping_verified'] is False
    assert off['functional_camera_still_format_physical_selector_mapping_verified'] is None
    startup = {
        'policy': 'original4014-observed-and4057-load-current-virtual-config-before-echo-f000',
        'commands': [0x4014, 0x4057],
        'canonical_layout': 'cmd16-length16-body16-reserved4-current-config40-FNV64',
        'config_fingerprint': 'actual-STATE128-bytes8:48-FNV1a64',
        'settings_policy': 'request0-independent-current-config40-checkpoint-no-MR-profile',
        'initial_diagnostic_policy': 'preserved-one-shot-before-functional-successor',
        'physical_mapping_verified': False,
    }
    prefix = 'functional_camera_startup_control_'
    assert {key: value for key, value in selected.items() if key.startswith(prefix)} == {
        prefix + key: value for key, value in startup.items()}
    assert all(off[prefix + key] is None for key in startup)
    assert selected['functional_camera_display_config_commands'] == [0x141, 0x152, 0x162]
    assert selected['functional_camera_peaking_enabled_supported'] is False
    assert selected['functional_camera_display_flag_enabled_supported'] is False
    assert selected['functional_camera_zebra_enabled_supported'] is False
    assert selected['functional_camera_bb_startup_config_policy'] == 'initial-C-config-banks-RGB-readback-before-independent-reply'
    assert selected['functional_camera_bb_startup_config_commands'] == [0x111, 0x166, 0x167, 0x15f, 0x128]
    assert selected['functional_camera_bb_startup_neutral_only'] is False
    assert selected['functional_camera_bb_startup_other_commands_neutral_only'] is True
    assert selected['functional_camera_bb_startup_0166_observed_initial_body_hex'] == '00010000000000000000000008000000070000000100000001000000'
    assert selected['functional_camera_bb_startup_0166_identity_policy'] == 'explicit-neutral-or-exact-observed-initial-tuple-RGB-identity'
    assert selected['functional_camera_bb_startup_gain_nonzero_supported'] is False
    assert selected['functional_camera_bb_startup_interval_enabled_supported'] is False
    assert selected['functional_camera_histogram_policy'] == 'first-enabled-mode1-RGB-u8-peak-YRGB-before-1148-and-210c'
    assert selected['functional_camera_histogram_commands'] == [0x148]
    assert selected['functional_camera_histogram_channels'] == ['virtual-Y', 'R', 'G', 'B']
    assert selected['functional_camera_histogram_bins_per_channel'] == 256
    assert selected['functional_camera_histogram_value_format'] == 'u8-peak-height-255'
    assert selected['functional_camera_histogram_luma_formula'] == '(77R+150G+29B+128)>>8'
    assert selected['functional_camera_histogram_normalization_formula'] == '(count*255+peak/2)/peak'
    assert selected['functional_camera_histogram_notification_selector'] == 1
    assert selected['functional_camera_histogram_notification_logical_bytes'] == 1034
    assert not any(selected['functional_camera_histogram_' + key + '_supported'] for key in ('mode0', 'reenable', 'continuous'))
    assert selected['functional_camera_xsync_capability_policy'] == 'virtual-one-model-frame-period-from-State128-fps-canonical-AP-pair'
    assert selected['functional_camera_xsync_clock_source'] == 'State128.fps'
    assert selected['functional_camera_xsync_readout_frame_periods'] == 1
    assert selected['functional_camera_xsync_current_exposure_independent'] is True
    assert selected['functional_camera_xsync_noncanonical_clock_policy'] == 'reject-before-mode1-ACK'
    assert selected['functional_camera_xsync_canonical_clock_rates'] == [1, 2, 4, 5, 6, 8, 10, 13, 15, 20, 25, 30, 40, 45, 50, 60, 80, 90, 100]
    assert selected['functional_camera_xsync_flash_trigger_supported'] is False
    assert selected['functional_camera_still_max_geometry'] == [8192, 8192]
    assert selected['functional_camera_video_max_geometry'] == [1920, 1080]
    assert selected['functional_camera_video_codec'] == 'H264'
    assert selected['functional_camera_media_output_policy'] == 'original-MPR-Fsys-only-no-host-media-file'
    assert 'original-MPR-Fsys-write' in selected['functional_camera_capture_requires']
    for claim in CLAIMS:
        assert selected['functional_camera_' + claim] is False
    for key, value in off.items():
        assert value is (False if key[len('functional_camera_'):] in CLAIMS else None)
    json.dumps(selected)
    strict = backup.cp_capture_format_profile_fields(backup.FULL_CP_OWNED_STATE_PROFILE)
    assert strict['cp_capture_format_owned_state_provider_policy'] == 'actual-consumed-inputs-only-no-defaults-no-secondary-fallback'
    assert not strict['cp_capture_format_data_reply_3003_supported']
    assert not strict['cp_capture_format_snapshot_2040_supported']


@pytest.mark.parametrize('profile', ['1', 'true', PROFILE + ' ', 'unknown', None, True, 1])
def test_functional_intent_rejects_unknown_or_untyped_selection(profile):
    with pytest.raises(ValueError):
        backup.functional_camera_profile_fields(profile)


def test_actual_clean_guest_export_requires_explicit_host_selection(tmp_path):
    launcher = load_script('functional_camera_launcher', 'start-menu.py')
    env = environment(tmp_path)
    host = launcher.profile_environment(env, natural_boot=True)
    assert host[HOST] == host[GUEST] == PROFILE
    assert host['MENU_JPEG_REQUEST_TRACE'] == '1'
    assert host['A7C2_FSYS_ASYNC_OBSERVE'] == '1'
    host.update(MENU_BACKUP_SYNC=backup.PROFILE, SEED_BACKUP='alllang',
                A7C2_DIRECTORY_SD_PROFILE='directory-vvfat-256gb-v1')
    setup = menu_probe_setup(host)
    assert setup.count('export ' + GUEST + '=' + PROFILE) == 1
    guest = clean_guest_environment(setup)
    assert guest[GUEST] == PROFILE and HOST not in guest
    assert guest['MENU_CP_CAPTURE_FORMAT'] == backup.FULL_CP_OWNED_STATE_PROFILE
    assert guest['MENU_CP302C_DIAGNOSTIC'] == backup.FULL_CP302C_DIAGNOSTIC_PROFILE
    off = dict(env)
    off.pop(HOST)
    assert GUEST not in launcher.profile_environment(off, natural_boot=True)
    assert GUEST not in launcher.profile_environment({}, natural_boot=True)


@pytest.mark.parametrize('changes', [
    {'A7C2_FUNCTIONAL_CAMERA': '1'},
    {'A7C2_FUNCTIONAL_CAMERA': PROFILE + ' '},
    {'MENU_FUNCTIONAL_CAMERA': 'unknown'},
    {'A7C2_FUNCTIONAL_CAMERA': '', 'MENU_FUNCTIONAL_CAMERA': PROFILE},
    {'A7C2_CP_CAPTURE_FORMAT': backup.FULL_CP_MOVIE_FORMAT_DIAGNOSTIC_PROFILE},
    {'A7C2_DIRECTORY_SD': ''},
    {'A7C2_CP_NOTIFICATION_CONTROL': ''},
    {'A7C2_PINMEM_OSD_CONNECT': ''},
])
def test_launcher_rejects_mismatch_missing_storage_or_predecessor(tmp_path, changes):
    launcher = load_script('functional_camera_reject', 'start-menu.py')
    with pytest.raises(ValueError):
        launcher.profile_environment({**environment(tmp_path), **changes}, natural_boot=True)


def test_functional_profile_rejects_non_natural_boot(tmp_path):
    launcher = load_script('functional_camera_direct_boot', 'start-menu.py')
    with pytest.raises(ValueError):
        launcher.profile_environment(environment(tmp_path), natural_boot=False)


@pytest.mark.parametrize('failure', ['', 'FIXTURE_FUNCTIONAL_OWNER_FAIL', 'FIXTURE_STILL_FORMAT_OWNER_FAIL',
    'FIXTURE_STARTUP_CONTROL_OWNER_FAIL', 'FIXTURE_CP_OWNED_PROVIDER_FAIL', 'FIXTURE_CP_OWNED_INPUTS_FAIL',
    'FIXTURE_CP_MOVIE_FORMAT_OWNER_FAIL', 'profile-off'])
def test_actual_functional_constructor_is_local_only(tmp_path, bb_constructor, failure):
    launcher = load_script('functional_camera_constructor', 'start-menu.py')
    host = launcher.profile_environment(environment(tmp_path), natural_boot=True)
    host.update(MENU_BACKUP_SYNC=backup.PROFILE, SEED_BACKUP='alllang',
                A7C2_DIRECTORY_SD_PROFILE='directory-vvfat-256gb-v1')
    guest = clean_guest_environment(menu_probe_setup(host))
    if failure == 'profile-off':
        guest.pop(GUEST)
    elif failure:
        guest[failure] = '1'
    text = bb_constructor(guest)
    values = dict(part.split('=', 1) for part in next(
        line for line in text.splitlines() if line.startswith('FUNCTIONAL_RESULT ')).split()[1:])
    assert values['enabled'] == ('0' if failure else '1')
    assert values['local_init_calls'] == ('1' if failure in (
        '', 'FIXTURE_FUNCTIONAL_OWNER_FAIL', 'FIXTURE_STILL_FORMAT_OWNER_FAIL', 'FIXTURE_STARTUP_CONTROL_OWNER_FAIL') else '0')
    assert values['startup_init_calls'] == ('1' if failure in ('', 'FIXTURE_STARTUP_CONTROL_OWNER_FAIL') else '0')
    assert values['backend_RPC'] == values['physical_ASIC_verified'] == values['capture_verified'] == '0'
    if failure != 'profile-off':
        line = next(line for line in text.splitlines() if line.startswith('FUNCTIONAL_CAMERA_PROFILE '))
        assert 'backend_initialized=0 constructor_RPC=0 physical_ASIC_verified=0 original_CP=0 capture_verified=0' in line


def test_actual_functional_sdk_library_identity_is_indexed_and_selected():
    tree = ast.parse((HERE / 'qemu-menu-probe.py').read_text())
    blocks = [node for node in ast.walk(tree) if isinstance(node, ast.If)
              and ast.unparse(node.test) == 'functional_camera is not None'
              and any(isinstance(value, ast.Constant) and value.value in
                      ('usr/lib/libInfraAvbbc.so', 'libInfraAvbbc.so', 'menu-root/usr/lib/libInfraAvbbc.so')
                      for value in ast.walk(node))]
    assert len(blocks) == 2
    for enabled in (False, True):
        scope = {'functional_camera': object() if enabled else None, 'base': HERE,
                 'manifest': {'files': {}}, 'expected_guest': {},
                 'sha256_file': lambda path: 'hash:' + str(path)}
        for block in blocks:
            exec(compile(ast.Module(body=[block], type_ignores=[]), '<actual-functional-sdk-identity>', 'exec'), scope)
        for name in ('usr/lib/libInfraAvbbc.so', 'usr/lib/dataflowInfraFramework.so'):
            path = str(HERE / 'menu-root' / name)
            assert (name in scope['expected_guest']) is enabled
            assert (path in scope['manifest']['files']) is enabled
            if enabled:
                assert scope['expected_guest'][name] == scope['manifest']['files'][path] == 'hash:' + path
        for name in ('start-menu.py', 'build-functional-camera-model.py',
                     'functional_camera_broker.py', 'functional_camera_runner.py',
                     'functional_face_source_snapshot.py'):
            path = str(HERE / name)
            assert (path in scope['manifest']['files']) is enabled
            if enabled:
                assert scope['manifest']['files'][path] == 'hash:' + path


def test_actual_runner_guard_is_pair_and_owned_state_specific():
    tree = ast.parse((HERE / 'qemu-menu-probe.py').read_text())
    guard = next(node for node in tree.body if isinstance(node, ast.If) and any(
        isinstance(call, ast.Call) and isinstance(call.func, ast.Attribute)
        and ast.unparse(call.func) == 'parser.error' and call.args
        and isinstance(call.args[0], ast.Constant)
        and str(call.args[0].value).startswith('Functional camera requires')
        for call in ast.walk(node)))

    class Parser:
        @staticmethod
        def error(message):
            raise ValueError(message)

    compiled = compile(ast.Module(body=[guard], type_ignores=[]), '<actual-functional-guard>', 'exec')
    for host, guest, parent, valid in (
        ('', '', '', True),
        (PROFILE, PROFILE, backup.FULL_CP_OWNED_STATE_PROFILE, True),
        (PROFILE, '', backup.FULL_CP_OWNED_STATE_PROFILE, False),
        ('', PROFILE, backup.FULL_CP_OWNED_STATE_PROFILE, False),
        (PROFILE, PROFILE, backup.FULL_CP_MOVIE_FORMAT_DIAGNOSTIC_PROFILE, False),
        (PROFILE + ' ', PROFILE + ' ', backup.FULL_CP_OWNED_STATE_PROFILE, False),
    ):
        scope = {'FUNCTIONAL_CAMERA_PROFILE': PROFILE,
                 'FULL_CP_OWNED_STATE_PROFILE': backup.FULL_CP_OWNED_STATE_PROFILE,
                 'functional_camera_profile': guest, 'cp_capture_format_profile': parent,
                 'parser': Parser, 'os': __import__('os')}
        with mock.patch.dict(scope['os'].environ, {HOST: host, GUEST: guest}, clear=True):
            if valid:
                exec(compiled, scope)
            else:
                with pytest.raises(ValueError):
                    exec(compiled, scope)
