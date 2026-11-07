"""Independent functional-profile intent and actual guest shell exports."""
import ast
import copy
import json
import os
from pathlib import Path
from unittest import mock

import pytest

import backup_profile as backup
from test_backup_profile import build_fixture, directory_lease, directory_profile
from test_bb_set_mode_profile import bb_constructor, clean_guest_environment, load_script, menu_probe_setup
from test_cp_capture_format_profile import host_environment, profile_scope

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
    assert selected['functional_camera_display_config_policy'] == 'original-display-controls-plus-functional-0170-three-boolean-RGB-identity-readback-before-independent-reply'
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
    assert selected['functional_camera_display_config_commands'] == [0x141, 0x152, 0x162, 0x163, 0x170]
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


class TestCPParameterBankProfile:
    POLICY = {
        'policy': 'full190-opaque-bank-4151u32-fps-configure-live-State128-independent-readback-v1',
        'opcode': 20,
        'native_commands': [0x4063],
        'bytes': 2564,
        'slots': 190,
        'result_bytes': 2756,
        'fps_input_offset': 0x86c,
        'reply_policy': 'oneway-original-request-free-no-ACK-no-notification',
        'physical_semantics_verified': False,
    }
    PREFIX = 'functional_camera_cp_parameter_bank_'

    def test_exact_nine_field_policy_is_exported_by_the_real_producer(self):
        fields = backup.functional_camera_profile_fields(PROFILE)
        actual = {key: value for key, value in fields.items() if key.startswith(self.PREFIX)}
        expected = {self.PREFIX + key: value for key, value in self.POLICY.items()}
        assert actual == expected
        for key, value in expected.items():
            assert type(actual[key]) is type(value)
            if isinstance(value, list):
                assert all(type(item) is int for item in actual[key])
        assert actual[self.PREFIX + 'opcode'] == 20
        assert actual[self.PREFIX + 'opcode'] != 11
        assert json.loads(json.dumps(actual)) == expected

    def test_unselected_bank_policy_is_None_and_never_promotes_capture_or_physical_claims(self):
        selected = backup.functional_camera_profile_fields(PROFILE)
        disabled = backup.functional_camera_profile_fields('')
        assert selected.keys() == disabled.keys()
        assert {key for key in disabled if key.startswith(self.PREFIX)} == {
            self.PREFIX + key for key in self.POLICY}
        assert all(disabled[self.PREFIX + key] is None for key in self.POLICY)
        assert selected[self.PREFIX + 'physical_semantics_verified'] is False
        for fields in (selected, disabled):
            for claim in CLAIMS:
                assert fields['functional_camera_' + claim] is False

    def test_parameter_bank_exports_are_independent_of_previous_callers(self):
        selected = backup.functional_camera_profile_fields(PROFILE)
        selected[self.PREFIX + 'native_commands'].append(0x4073)
        selected[self.PREFIX + 'opcode'] = 11
        selected[self.PREFIX + 'physical_semantics_verified'] = True
        fresh = backup.functional_camera_profile_fields(PROFILE)
        assert {key: value for key, value in fresh.items() if key.startswith(self.PREFIX)} == {
            self.PREFIX + key: value for key, value in self.POLICY.items()}
        assert fresh['functional_camera_capture_verified'] is False
        assert fresh['functional_camera_physical_ASIC_compatibility_verified'] is False


class TestCPCrankControlProfile:
    POLICY = {
        'policy': 'active-config-crank-mode0-v1',
        'opcode': 21,
        'native_commands': [0x409d],
        'bytes': 12,
        'result_bytes': 208,
        'supported_modes': [0],
        'input_policy': 'full-original12-byte1-cookie-opaque-body4zero',
        'bank_policy': 'current-committed-instance-bank-generation-once',
        'state_policy': 'live-State128-config-generation-plus-one-all-other-bytes-preserved',
        'reply_policy': 'independent-type1-409d-echo-cookie-f000-original-receive-free',
        'initial_diagnostic_policy': 'preserved-strict-initial409d-before-functional-bank',
        'frame_production_supported': False,
        'physical_semantics_verified': False,
    }
    PREFIX = 'functional_camera_cp_crank_control_'

    def test_only_the_declared_functional_mode0_policy_is_exported(self):
        selected = backup.functional_camera_profile_fields(PROFILE)
        actual = {key: value for key, value in selected.items() if key.startswith(self.PREFIX)}
        expected = {self.PREFIX + key: value for key, value in self.POLICY.items()}
        assert actual == expected
        for key, value in expected.items():
            assert type(actual[key]) is type(value)
            if isinstance(value, list):
                assert all(type(item) is int for item in actual[key])
        assert json.loads(json.dumps(actual)) == expected
        assert selected['functional_camera_cp_parameter_bank_opcode'] == 20
        assert selected['functional_camera_cp_parameter_bank_bytes'] == 2564
        assert selected['functional_camera_capture_verified'] is False
        assert selected['functional_camera_physical_ASIC_compatibility_verified'] is False

    def test_disabled_policy_is_None_and_the_strict_diagnostic_profile_stays_separate(self):
        selected = backup.functional_camera_profile_fields(PROFILE)
        disabled = backup.functional_camera_profile_fields('')
        assert selected.keys() == disabled.keys()
        assert all(disabled[self.PREFIX + key] is None for key in self.POLICY)
        strict = backup.cp_capture_format_profile_fields(backup.FULL_CP_OWNED_STATE_PROFILE)
        assert not any(key.startswith(self.PREFIX) for key in strict)
        assert strict['cp_capture_format_ee_control_commands'][0] == {
            'command': 0x409d, 'request_type': 5, 'request_bytes': 12, 'response_bytes': 12}
        for fields in (selected, disabled):
            assert all(fields['functional_camera_' + claim] is False for claim in CLAIMS)

    def test_callers_cannot_mutate_future_policy_exports(self):
        first = backup.functional_camera_profile_fields(PROFILE)
        first[self.PREFIX + 'supported_modes'].append(1)
        first[self.PREFIX + 'native_commands'].append(0x4063)
        first[self.PREFIX + 'opcode'] = 11
        first[self.PREFIX + 'physical_semantics_verified'] = True
        fresh = backup.functional_camera_profile_fields(PROFILE)
        assert {key: value for key, value in fresh.items() if key.startswith(self.PREFIX)} == {
            self.PREFIX + key: value for key, value in self.POLICY.items()}


class TestCPMovieFormatAndOUCrankProfile:
    MOVIE_POLICY = {
        'cp_movie_format_policy': 'active-config-movie-format5-rate1-0-v1',
        'cp_movie_format_opcode': 22,
        'cp_movie_format_native_commands': [0x4000],
        'cp_movie_format_bytes': 20,
        'cp_movie_format_result_bytes': 240,
        'cp_movie_format_input_policy': 'full-original20-byte1-cookie-byte11-byte19-opaque',
        'cp_movie_format_mapping': 'format5-rate1,0-to-current-Config48-RGB888-H264-bankFPS',
        'cp_movie_format_bank_policy': 'current-committed-instance-bank-crank-pair-once',
        'cp_movie_format_state_policy': 'live-State128-config-generation-plus-one-all-other-bytes-preserved',
        'cp_movie_format_reply_policy': 'independent-type1-4000-echo-cookie-f000-original-receive-free',
        'cp_movie_format_initial_diagnostic_policy': 'preserved-strict-initial4000-before-functional-bank',
        'cp_movie_format_frame_production_supported': False,
        'cp_movie_format_physical_semantics_verified': False,
    }
    OU_POLICY = {
        'cp_ou_crank_control_policy': 'active-config-ou-crank-mode0-v1',
        'cp_ou_crank_control_opcode': 23,
        'cp_ou_crank_control_native_commands': [0x4072],
        'cp_ou_crank_control_bytes': 12,
        'cp_ou_crank_control_result_bytes': 224,
        'cp_ou_crank_control_supported_modes': [0],
        'cp_ou_crank_control_input_policy': 'full-original12-byte1-cookie-opaque-body4zero',
        'cp_ou_crank_control_bank_policy': 'current-committed-instance-bank-crank-movie-tuple-once',
        'cp_ou_crank_control_state_policy': 'live-State128-config-generation-plus-one-all-other-bytes-preserved',
        'cp_ou_crank_control_reply_policy': 'none-oneway-original-sender-request-free-only',
        'cp_ou_crank_control_initial_diagnostic_policy': 'preserved-strict-initial4072-before-functional-bank',
        'cp_ou_crank_control_frame_production_supported': False,
        'cp_ou_crank_control_physical_semantics_verified': False,
    }
    POLICIES = (('cp_movie_format_', MOVIE_POLICY), ('cp_ou_crank_control_', OU_POLICY))

    def test_real_producer_exports_the_exact_two_thirteen_field_contracts(self):
        selected = backup.functional_camera_profile_fields(PROFILE)
        for prefix, policy in self.POLICIES:
            expected = {'functional_camera_' + key: value for key, value in policy.items()}
            actual = {key: value for key, value in selected.items()
                      if key.startswith('functional_camera_' + prefix)}
            assert len(policy) == 13 and actual == expected
            for key, value in expected.items():
                assert type(actual[key]) is type(value)
                if type(value) is list:
                    assert all(type(item) is int for item in actual[key])
            assert json.loads(json.dumps(actual)) == expected
        assert all(selected['functional_camera_' + claim] is False for claim in CLAIMS)

    def test_disabled_and_strict_profiles_keep_policy_and_runtime_claims_separate(self):
        selected = backup.functional_camera_profile_fields(PROFILE)
        disabled = backup.functional_camera_profile_fields('')
        assert selected.keys() == disabled.keys()
        for prefix, policy in self.POLICIES:
            assert all(disabled['functional_camera_' + key] is None for key in policy)
            assert selected['functional_camera_' + prefix + 'frame_production_supported'] is False
            assert selected['functional_camera_' + prefix + 'physical_semantics_verified'] is False
        for fields in (selected, disabled):
            assert all(fields['functional_camera_' + claim] is False for claim in CLAIMS)
        for profile in ('', backup.FULL_CP_CAPTURE_FORMAT_PROFILE,
                        backup.FULL_CP_MOVIE_FORMAT_DIAGNOSTIC_PROFILE, backup.FULL_CP_OWNED_STATE_PROFILE):
            strict = backup.cp_capture_format_profile_fields(profile)
            assert not any(key.startswith('functional_camera_') for key in strict)
            assert strict['cp_capture_format_capture_verified'] is False
            if profile == backup.FULL_CP_OWNED_STATE_PROFILE:
                assert strict['cp_capture_format_owned_state_provider_policy'] == 'actual-consumed-inputs-only-no-defaults-no-secondary-fallback'
                assert strict['cp_capture_format_ee_control_commands'][1] == {
                    'command': 0x4072, 'request_type': 5, 'request_bytes': 12, 'response_bytes': 0}

    def test_mutating_a_previous_export_cannot_change_later_declarations(self):
        first = backup.functional_camera_profile_fields(PROFILE)
        for prefix, policy in self.POLICIES:
            first['functional_camera_' + prefix + 'native_commands'].append(0x3012)
            first['functional_camera_' + prefix + 'physical_semantics_verified'] = True
        first['functional_camera_cp_ou_crank_control_supported_modes'].append(1)
        fresh = backup.functional_camera_profile_fields(PROFILE)
        for prefix, policy in self.POLICIES:
            assert {key: value for key, value in fresh.items()
                    if key.startswith('functional_camera_' + prefix)} == {
                        'functional_camera_' + key: value for key, value in policy.items()}
        assert all(fresh['functional_camera_' + claim] is False for claim in CLAIMS)

    def test_policy_literals_match_the_formal_checker_without_loading_a_model(self):
        tree = ast.parse((HERE.parents[1] / 'report/functional-camera-evidence/check_evidence.py').read_text())
        policies = {node.targets[0].id: ast.literal_eval(node.value) for node in tree.body
                    if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name)
                    and node.targets[0].id in ('CP_CRANK_CONTROL_POLICY', 'CP_MOVIE_FORMAT_POLICY',
                                              'CP_OU_CRANK_CONTROL_POLICY')}
        assert policies == {
            'CP_CRANK_CONTROL_POLICY': {'cp_crank_control_' + key: value
                                        for key, value in TestCPCrankControlProfile.POLICY.items()},
            'CP_MOVIE_FORMAT_POLICY': self.MOVIE_POLICY,
            'CP_OU_CRANK_CONTROL_POLICY': self.OU_POLICY,
        }

    @pytest.mark.parametrize('selection', ['functional', 'strict', 'ordinary'])
    def test_actual_prepare_dict_propagation_and_real_admission_reject_drift(self, tmp_path, selection, synthetic_backup_profile):
        build = build_fixture(tmp_path)[0]
        env = environment(tmp_path)
        env['A7C2_BACKUP_BUILD'] = str(build)
        if selection != 'functional':
            env.pop(HOST)
        if selection == 'ordinary':
            env.pop('A7C2_CP_CAPTURE_FORMAT')
        launcher = load_script('functional_camera_metadata_prepare', 'start-menu.py')
        host = launcher.profile_environment(env, natural_boot=True)
        host.update(MENU_BACKUP_SYNC=backup.PROFILE, SEED_BACKUP='alllang',
                    A7C2_DIRECTORY_SD_PROFILE='directory-vvfat-256gb-v1')
        with directory_lease(tmp_path / 'card') as lease:
            host.update(directory_profile(HERE, lease, tmp_path / 'directory-profile'))
            host.update(synthetic_backup_profile(host))
        receipt_path = Path(host['MENU_BACKUP_PROFILE_RECEIPT'])
        receipt = json.loads(receipt_path.read_text())
        tree = ast.parse((HERE / 'qemu-menu-probe.py').read_text())
        manifest_dict = next(node.value for node in tree.body if isinstance(node, ast.Assign)
                             and isinstance(node.targets[0], ast.Name) and node.targets[0].id == 'manifest')
        pairs = [(key, value) for key, value in zip(manifest_dict.keys, manifest_dict.values)
                 if isinstance(key, ast.Constant) and key.value in
                    ('backup_transport', 'directory_sd_profile', 'rm_file_image_bytes')
                 or key is None and isinstance(value, ast.Call) and isinstance(value.func, ast.Name)
                    and value.func.id == 'functional_camera_profile_fields']
        assert len(pairs) == 4
        scope = profile_scope()
        scope.update(functional_camera_profile=host.get(GUEST, ''),
                     cp_capture_format_profile=host.get('MENU_CP_CAPTURE_FORMAT', ''),
                     backup_profile_receipt=receipt, directory_sd_fd=40, host_sd_fd=None,
                     sd_sparse='', sd_seed=None, sd_seed_bytes=0, base=HERE,
                     rm_file=host.get('MENU_RM_FILE') == '1')
        propagated = ast.Dict(keys=[key for key, _ in pairs], values=[value for _, value in pairs])
        manifest = eval(compile(ast.fix_missing_locations(ast.Expression(propagated)),
                                '<actual-functional-metadata-dict>', 'eval'), scope)
        assert manifest['backup_transport'] is receipt
        for prefix, policy in self.POLICIES:
            expected = {'functional_camera_' + key: value if selection == 'functional' else None
                        for key, value in policy.items()}
            for target in (manifest, manifest['backup_transport']):
                assert {key: value for key, value in target.items()
                        if key.startswith('functional_camera_' + prefix)} == expected
                for key, value in expected.items():
                    assert key in target and type(target[key]) is type(value)
                    assert json.dumps(target[key]) == json.dumps(value)
        for target in (manifest, manifest['backup_transport']):
            assert all(target['functional_camera_' + claim] is False for claim in CLAIMS)
        assert receipt['capture_verified'] is False
        validator = next(node for node in tree.body if isinstance(node, ast.If)
                         and isinstance(node.test, ast.Name) and node.test.id == 'backup_sync'
                         and any(isinstance(call, ast.Call) and isinstance(call.func, ast.Name)
                                 and call.func.id == 'validate_build' for call in ast.walk(node)))
        code = compile(ast.Module(body=[validator], type_ignores=[]), '<actual-functional-receipt-admission>', 'exec')
        scope.update(os=os, json=json, Path=Path, sha256_file=backup.sha, backup_sync=backup.PROFILE,
                     env=host, kernel_script=Path(host['MENU_KERNEL_SCRIPT']), board_dtb=Path(host['MENU_DTB']),
                     udate_kernel_receipt=HERE.parents[1] / 'report/virtual-cp/udate-distribution/verification.json',
                     overwrite_manifest=None, settings_restore_manifest=None)
        with mock.patch.dict(os.environ, host, clear=True):
            try:
                exec(code, scope)
                for _, policy in self.POLICIES:
                    for key in policy:
                        key = 'functional_camera_' + key
                        bad = copy.deepcopy(receipt)
                        value = bad.pop(key)
                        receipt_path.write_text(json.dumps(bad))
                        with pytest.raises(ValueError, match='identity/admission mismatch'):
                            exec(code, scope)
                        bad[key] = int(value) if type(value) is bool else float(value) if type(value) is int else 'wrong'
                        receipt_path.write_text(json.dumps(bad))
                        with pytest.raises(ValueError, match='identity/admission mismatch'):
                            exec(code, scope)
            finally:
                receipt_path.write_text(json.dumps(receipt))
            exec(code, scope)
        if selection == 'functional':
            checker = backup.load_module('functional_profile_metadata_checker',
                HERE.parents[1] / 'report/functional-camera-evidence/check_evidence.py')
            assert checker.check_profile(manifest)['verified'] is True
            for section in ('top', 'backup'):
                for _, policy in self.POLICIES:
                    for key in policy:
                        key = 'functional_camera_' + key
                        bad = copy.deepcopy(manifest)
                        target = bad if section == 'top' else bad['backup_transport']
                        value = target.pop(key)
                        with pytest.raises(ValueError, match='typed functional profile drift'):
                            checker.check_profile(bad)
                        target[key] = int(value) if type(value) is bool else float(value) if type(value) is int else 'wrong'
                        with pytest.raises(ValueError, match='typed functional profile drift'):
                            checker.check_profile(bad)
                        if type(value) is list:
                            target[key] = [float(item) for item in value]
                            with pytest.raises(ValueError, match='typed functional profile drift'):
                                checker.check_profile(bad)
            assert manifest['functional_camera_capture_verified'] is False
            assert manifest['functional_camera_physical_ASIC_compatibility_verified'] is False


class TestBBTimecodeControlProfile:
    POLICY = {
        'bb_timecode_control_policy': 'virtual-bb-timecode-controls-v1',
        'bb_timecode_control_native_commands': [1024, 1025, 1026],
        'bb_timecode_control_request_bytes': 10,
        'bb_timecode_control_reply_bytes': 12,
        'bb_timecode_control_state_bytes': 48,
        'bb_timecode_control_input_policy': 'exact200d10-8001-bool0,1-byte9zero-original-local-source',
        'bb_timecode_control_state_policy': 'owned3bool-knownmask-generation-independent-State48-v1',
        'bb_timecode_control_reply_policy': 'independent200d-command-plus1000-plain0-after-state-readback-and-original-request-free',
        'bb_timecode_control_retirement_policy': 'actual-original-receive-and-same-sender-free-before-next-transaction',
        'bb_timecode_control_fifo_policy': 'explicit-single-pending-actual-source-sender-lease-no-original-RTOS-identity-claim',
        'bb_timecode_control_original_fifo_identity_verified': False,
        'bb_timecode_control_frame_production_supported': False,
        'bb_timecode_control_physical_semantics_verified': False,
    }
    PREFIX = 'functional_camera_bb_timecode_control_'

    def test_real_producer_exports_the_exact_thirteen_typed_timecode_fields(self):
        selected = backup.functional_camera_profile_fields(PROFILE)
        actual = {key: value for key, value in selected.items() if key.startswith(self.PREFIX)}
        expected = {'functional_camera_' + key: value for key, value in self.POLICY.items()}
        assert len(self.POLICY) == 13 and actual == expected
        for key, value in expected.items():
            assert type(actual[key]) is type(value)
            if type(value) is list:
                assert all(type(item) is int for item in actual[key])
        assert json.loads(json.dumps(actual)) == expected
        assert all(selected['functional_camera_' + claim] is False for claim in CLAIMS)

    def test_disabled_and_strict_profiles_do_not_enable_timecode_or_promote_claims(self):
        selected = backup.functional_camera_profile_fields(PROFILE)
        disabled = backup.functional_camera_profile_fields('')
        assert selected.keys() == disabled.keys()
        assert {key: value for key, value in disabled.items() if key.startswith(self.PREFIX)} == {
            'functional_camera_' + key: None for key in self.POLICY}
        for profile in ('', backup.FULL_CP_CAPTURE_FORMAT_PROFILE,
                        backup.FULL_CP_MOVIE_FORMAT_DIAGNOSTIC_PROFILE, backup.FULL_CP_OWNED_STATE_PROFILE):
            strict = backup.cp_capture_format_profile_fields(profile)
            assert not any(key.startswith(self.PREFIX) for key in strict)
            assert strict['cp_capture_format_capture_verified'] is False
        for fields in (selected, disabled):
            assert all(fields['functional_camera_' + claim] is False for claim in CLAIMS)
        for name in ('original_fifo_identity_verified', 'frame_production_supported', 'physical_semantics_verified'):
            assert selected[self.PREFIX + name] is False

    def test_command_list_mutation_does_not_change_later_exports_or_other_policies(self):
        first = backup.functional_camera_profile_fields(PROFILE)
        commands = self.PREFIX + 'native_commands'
        first[commands].append(0x4038)
        first[self.PREFIX + 'policy'] = 'virtual-bb-timecode-controls-v1 '
        first[self.PREFIX + 'original_fifo_identity_verified'] = True
        fresh = backup.functional_camera_profile_fields(PROFILE)
        assert first[commands] is not fresh[commands]
        assert fresh[commands] is not self.POLICY['bb_timecode_control_native_commands']
        assert {key: value for key, value in fresh.items() if key.startswith(self.PREFIX)} == {
            'functional_camera_' + key: value for key, value in self.POLICY.items()}
        assert fresh['functional_camera_cp_ou_crank_control_native_commands'] == [0x4072]
        assert all(fresh['functional_camera_' + claim] is False for claim in CLAIMS)

    @pytest.mark.parametrize('selection', ['functional', 'strict', 'ordinary'])
    def test_actual_prepare_manifest_backup_and_admission_preserve_typed_timecode_policy(self, tmp_path, selection, synthetic_backup_profile):
        build = build_fixture(tmp_path)[0]
        env = environment(tmp_path)
        env['A7C2_BACKUP_BUILD'] = str(build)
        if selection != 'functional':
            env.pop(HOST)
        if selection == 'ordinary':
            env.pop('A7C2_CP_CAPTURE_FORMAT')
        launcher = load_script('functional_timecode_metadata_prepare', 'start-menu.py')
        host = launcher.profile_environment(env, natural_boot=True)
        host.update(MENU_BACKUP_SYNC=backup.PROFILE, SEED_BACKUP='alllang',
                    A7C2_DIRECTORY_SD_PROFILE='directory-vvfat-256gb-v1')
        with directory_lease(tmp_path / 'card') as lease:
            host.update(directory_profile(HERE, lease, tmp_path / 'directory-profile'))
            host.update(synthetic_backup_profile(host))
        receipt_path = Path(host['MENU_BACKUP_PROFILE_RECEIPT'])
        receipt = json.loads(receipt_path.read_text())
        tree = ast.parse((HERE / 'qemu-menu-probe.py').read_text())
        manifest_dict = next(node.value for node in tree.body if isinstance(node, ast.Assign)
                             and isinstance(node.targets[0], ast.Name) and node.targets[0].id == 'manifest')
        pairs = [(key, value) for key, value in zip(manifest_dict.keys, manifest_dict.values)
                 if isinstance(key, ast.Constant) and key.value in
                    ('backup_transport', 'directory_sd_profile', 'rm_file_image_bytes')
                 or key is None and isinstance(value, ast.Call) and isinstance(value.func, ast.Name)
                    and value.func.id == 'functional_camera_profile_fields']
        assert len(pairs) == 4
        scope = profile_scope()
        scope.update(functional_camera_profile=host.get(GUEST, ''),
                     cp_capture_format_profile=host.get('MENU_CP_CAPTURE_FORMAT', ''),
                     backup_profile_receipt=receipt, directory_sd_fd=40, host_sd_fd=None,
                     sd_sparse='', sd_seed=None, sd_seed_bytes=0, base=HERE,
                     rm_file=host.get('MENU_RM_FILE') == '1')
        propagated = ast.Dict(keys=[key for key, _ in pairs], values=[value for _, value in pairs])
        manifest = eval(compile(ast.fix_missing_locations(ast.Expression(propagated)),
                                '<actual-timecode-metadata-dict>', 'eval'), scope)
        assert manifest['backup_transport'] is receipt
        expected = {'functional_camera_' + key: value if selection == 'functional' else None
                    for key, value in self.POLICY.items()}
        for target in (manifest, manifest['backup_transport']):
            assert {key: value for key, value in target.items() if key.startswith(self.PREFIX)} == expected
            for key, value in expected.items():
                assert key in target and type(target[key]) is type(value)
                assert json.dumps(target[key]) == json.dumps(value)
            assert all(target['functional_camera_' + claim] is False for claim in CLAIMS)
        assert receipt['capture_verified'] is False
        validator = next(node for node in tree.body if isinstance(node, ast.If)
                         and isinstance(node.test, ast.Name) and node.test.id == 'backup_sync'
                         and any(isinstance(call, ast.Call) and isinstance(call.func, ast.Name)
                                 and call.func.id == 'validate_build' for call in ast.walk(node)))
        code = compile(ast.Module(body=[validator], type_ignores=[]), '<actual-timecode-receipt-admission>', 'exec')
        scope.update(os=os, json=json, Path=Path, sha256_file=backup.sha, backup_sync=backup.PROFILE,
                     env=host, kernel_script=Path(host['MENU_KERNEL_SCRIPT']), board_dtb=Path(host['MENU_DTB']),
                     udate_kernel_receipt=HERE.parents[1] / 'report/virtual-cp/udate-distribution/verification.json',
                     overwrite_manifest=None, settings_restore_manifest=None)
        with mock.patch.dict(os.environ, host, clear=True):
            try:
                exec(code, scope)
                for key, value in expected.items():
                    bad = copy.deepcopy(receipt)
                    bad.pop(key)
                    receipt_path.write_text(json.dumps(bad))
                    with pytest.raises(ValueError, match='identity/admission mismatch'):
                        exec(code, scope)
                    wrong = ([0, 1] if type(value) is bool else [float(value)] if type(value) is int else
                             [[float(item) for item in value], value + [0x4038]] if type(value) is list else
                             [None, value + ' '] if type(value) is str else [False])
                    for replacement in wrong:
                        bad[key] = replacement
                        receipt_path.write_text(json.dumps(bad))
                        with pytest.raises(ValueError, match='identity/admission mismatch'):
                            exec(code, scope)
            finally:
                receipt_path.write_text(json.dumps(receipt))
            exec(code, scope)
        if selection == 'functional':
            checker = backup.load_module('functional_timecode_profile_metadata_checker',
                HERE.parents[1] / 'report/functional-camera-evidence/check_evidence.py')
            assert checker.check_profile(manifest)['verified'] is True
            for section in ('top', 'backup'):
                for key, value in expected.items():
                    bad = copy.deepcopy(manifest)
                    target = bad if section == 'top' else bad['backup_transport']
                    target.pop(key)
                    with pytest.raises(ValueError, match='typed functional profile drift'):
                        checker.check_profile(bad)
                    wrong = ([0, 1] if type(value) is bool else [float(value)] if type(value) is int else
                             [[float(item) for item in value], value + [0x4038]] if type(value) is list else
                             [None, value + ' '] if type(value) is str else [False])
                    for replacement in wrong:
                        target[key] = replacement
                        with pytest.raises(ValueError, match='typed functional profile drift'):
                            checker.check_profile(bad)
                bad = copy.deepcopy(manifest)
                target = bad if section == 'top' else bad['backup_transport']
                target[self.PREFIX + 'undeclared'] = None
                with pytest.raises(ValueError, match='typed functional profile drift'):
                    checker.check_profile(bad)
                for alias in ('virtual-bb-timecode-controls-v2', 'active-config-ou-crank-mode0-v1'):
                    bad = copy.deepcopy(manifest)
                    target = bad if section == 'top' else bad['backup_transport']
                    target[self.PREFIX + 'policy'] = alias
                    with pytest.raises(ValueError, match='typed functional profile drift'):
                        checker.check_profile(bad)
            commands = self.PREFIX + 'native_commands'
            assert manifest[commands] is not receipt[commands]
            manifest[commands].append(0x4038)
            assert receipt[commands] == self.POLICY['bb_timecode_control_native_commands']
            assert backup.functional_camera_profile_fields(PROFILE)[commands] == receipt[commands]
            manifest[commands].pop()
            assert checker.check_profile(manifest)['verified'] is True


def test_preset_profile_exact_domains_are_independent_and_disabled_by_default():
    selected = backup.functional_camera_profile_fields(PROFILE)
    fresh = backup.functional_camera_profile_fields(PROFILE)
    off = backup.functional_camera_profile_fields('')
    prefix = 'functional_camera_bb_timecode_preset_'
    keys = {key for key in selected if key.startswith(prefix)}
    assert len(keys) == 13 and all(off[key] is None for key in keys)
    assert selected[prefix + 'policy'] == 'virtual-bb-timecode-presets-v1'
    assert selected[prefix + 'native_commands'] == [0x040a, 0x0409]
    assert selected[prefix + 'request_sizes'] == {'0x040a': 12, '0x0409': 10}
    assert selected[prefix + 'reply_bytes'] == 12 and selected[prefix + 'state_bytes'] == 48
    assert selected[prefix + 'native_CP_verified'] is False
    assert selected[prefix + 'frame_production_supported'] is False
    assert selected[prefix + 'physical_semantics_verified'] is False
    selected[prefix + 'native_commands'].append(0x040b)
    selected[prefix + 'request_sizes']['0x040a'] = 10
    assert fresh[prefix + 'native_commands'] == [0x040a, 0x0409]
    assert fresh[prefix + 'request_sizes'] == {'0x040a': 12, '0x0409': 10}
    assert fresh['functional_camera_bb_timecode_control_native_commands'] == [0x0400, 0x0401, 0x0402]

