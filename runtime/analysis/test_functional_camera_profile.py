"""Independent functional-profile intent and actual guest shell exports."""
import ast
import copy
import json
import os
import tempfile
from pathlib import Path
from unittest import mock

import pytest

import backup_profile as backup
import functional_camera_runner as runner
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


def test_functional_card_seed_rejects_hardlinks_and_shared_write(tmp_path):
    source=tmp_path/'card.img';source.write_bytes(b'synthetic-card');source.chmod(0o600)
    alias=tmp_path/'alias.img';os.link(source,alias)
    with pytest.raises(ValueError,match='one link'):
        backup._bound_profile_input(source,single_link=True)
    alias.unlink();source.chmod(0o620)
    with pytest.raises(ValueError,match='private write permissions'):
        backup._bound_profile_input(source,single_link=True)


def test_ram_media_candidate_unset_keeps_directory_profile_unchanged(tmp_path):
    launcher = load_script('functional_camera_default_media', 'start-menu.py')
    original = environment(tmp_path)
    before = copy.deepcopy(original)
    default = launcher.profile_environment(original, natural_boot=True)
    explicit_unset = launcher.profile_environment(
        {**original, 'A7C2_FUNCTIONAL_CAMERA_MEDIA': ''}, natural_boot=True)
    explicit_unset.pop('A7C2_FUNCTIONAL_CAMERA_MEDIA')
    assert explicit_unset == default
    assert original == before
    assert default['A7C2_DIRECTORY_SD'] == original['A7C2_DIRECTORY_SD']
    assert default[HOST] == default[GUEST] == PROFILE
    assert default['MENU_CP_CAPTURE_FORMAT'] == backup.FULL_CP_OWNED_STATE_PROFILE
    assert 'A7C2_FUNCTIONAL_CAMERA_MEDIA' not in default
    assert backup.validate_functional_camera_media({}) is None


@pytest.mark.parametrize('selection', ['1', 'true', 'unknown',
    backup.FUNCTIONAL_CAMERA_RAM_MEDIA_CANDIDATE + ' ', None, True, 1])
def test_ram_media_candidate_rejects_unknown_or_untyped_selection(tmp_path, selection):
    launcher = load_script('functional_camera_bad_media', 'start-menu.py')
    env = {**environment(tmp_path), 'A7C2_FUNCTIONAL_CAMERA_MEDIA': selection}
    with pytest.raises(ValueError, match='A7C2_FUNCTIONAL_CAMERA_MEDIA must be'):
        launcher.profile_environment(env, natural_boot=True)
    with mock.patch.object(backup, 'validate_build') as build:
        with pytest.raises(ValueError, match='A7C2_FUNCTIONAL_CAMERA_MEDIA must be'):
            backup.prepare_profile(HERE, env)
        build.assert_not_called()


def ram_environment(tmp_path):
    return {**environment(tmp_path), 'A7C2_DIRECTORY_SD': '',
            'A7C2_BOOT_PROFILE': 'direct-bootin',
            'A7C2_FUNCTIONAL_CAMERA_MEDIA': backup.FUNCTIONAL_CAMERA_RAM_MEDIA_CANDIDATE}


def test_ram_media_intent_keeps_all_predecessors_and_disables_automatic_hotplug(tmp_path):
    launcher = load_script('functional_camera_ram_intent', 'start-menu.py')
    selected = launcher.profile_environment(ram_environment(tmp_path), natural_boot=True)
    assert selected['A7C2_FUNCTIONAL_CAMERA_MEDIA'] == backup.FUNCTIONAL_CAMERA_RAM_MEDIA_CANDIDATE
    assert selected[HOST] == selected[GUEST] == PROFILE
    assert selected['MENU_CP_CAPTURE_FORMAT'] == backup.FULL_CP_OWNED_STATE_PROFILE
    assert selected['MENU_PINMEM_OSD_CONNECT'] == backup.FULL_PINMEM_OSD_CONNECTION_PROFILE
    assert not selected.get('MENU_USB_NET')
    assert not selected.get('A7C2_SD_HOTPLUG')
    assert not selected.get('A7C2_DIRECTORY_SD')
    # Intent is not a consumer admission receipt or a verified seed capability.
    assert not selected.get('MENU_BACKUP_PROFILE_RECEIPT')
    assert not selected.get('MENU_KERNEL_SCRIPT')
    with pytest.raises(ValueError):
        launcher.profile_environment(ram_environment(tmp_path), natural_boot=False)


@pytest.mark.parametrize('changes', [
    {'A7C2_DIRECTORY_SD': '/still-a-directory-card'},
    {'A7C2_HOST_SD': '256gb'},
    {'A7C2_SD_SPARSE': '10g-empty'},
    {'A7C2_SD_HOTPLUG': '1'},
    {'MENU_USB_NET': '1'},
    {'A7C2_USB_NET': '1'},
    {'QEMU_SONY_USB_NET': '1'},
    {'A7C2_USB_NET_SELFTEST': '1'},
    {'QEMU_NATIVE_AP_CP_LINK': 'virtual-native-ap-cp-link-v1'},
    {'QEMU_NATIVE_LINK_DIR': '/forged-link'},
    {'MENU_KERNEL_SCRIPT': '/forged-kernel.sh'},
    {'MENU_DTB': '/forged-board.dtb'},
    {'QEMU_SYSTEM_DIR': '/forged-qemu'},
    {'A7C2_BOOT_PROFILE': 'full-system-cold'},
    {'A7C2_RAM_RESTORE_STREAM': '/forged-ram'},
    {'A7C2_CP_EMULATION': '1'},
    {'SEED_BACKUP': 'private'},
    {HOST: ''},
    {'A7C2_CP_CAPTURE_FORMAT': backup.FULL_CP_MOVIE_FORMAT_DIAGNOSTIC_PROFILE},
])
def test_ram_media_conflicts_fail_before_real_binding_or_output(tmp_path, changes):
    launcher = load_script('functional_camera_blocked_ram_media', 'start-menu.py')
    env = {**ram_environment(tmp_path), **changes}
    before = copy.deepcopy(env)
    with pytest.raises(ValueError):
        launcher.profile_environment(env, natural_boot=True)
    with mock.patch.object(backup, 'validate_build') as build:
        with pytest.raises(ValueError):
            backup.prepare_profile(HERE, env)
        build.assert_not_called()
    assert env == before
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize('host_key', [
    'A7C2_CP_BACKGROUND', 'A7C2_UDATE_DISTRIBUTION', 'A7C2_TOUCH_PANEL',
    'A7C2_TCIN_DETECT', 'A7C2_DFS_SELECTOR', 'A7C2_VEF_PATH', 'A7C2_ADF_PROC_PATH',
    'A7C2_ADF_SET_INPUT', 'A7C2_ADF_SET_OUTPUT', 'A7C2_BB_SET_MODE',
    'A7C2_IMAGING_CONNECT', 'A7C2_IMAGING_CONTROL_CONNECT', 'A7C2_IMAGING_ADF_CONNECT',
    'A7C2_INFRABB_VEF_CONNECT', 'A7C2_INFRABB_VEF_CONTROL_CONNECT',
    'A7C2_VEF_PINMEM_INPUT_CONNECT', 'A7C2_VEF_PINMEM_CONTROL_CONNECT',
    'A7C2_PINMEM_PEER_CONNECT', 'A7C2_PINMEM_HDMI_VIDEO_CONNECT',
    'A7C2_PINMEM_OSD_CONNECT', 'A7C2_ADF_HDMI_AUDIO_CONNECT',
    'A7C2_CP302C_DIAGNOSTIC', 'A7C2_CP_NOTIFICATION_CONTROL',
])
def test_ram_media_does_not_relax_any_host_predecessor(tmp_path, host_key):
    launcher = load_script('functional_camera_ram_predecessors', 'start-menu.py')
    env = ram_environment(tmp_path)
    assert env[host_key]
    env.pop(host_key)
    with pytest.raises(ValueError):
        launcher.profile_environment(env, natural_boot=True)


@pytest.fixture
def ram_artifact_validator(monkeypatch):
    """Synthetic derivation tests admit no real binary/model; runner owns that boundary."""
    actual = runner.validate_artifact
    validator = mock.Mock(return_value={})
    monkeypatch.setattr(runner, 'validate_artifact', validator)
    return validator, actual


@pytest.fixture
def synthetic_ram_directory_creation(monkeypatch):
    """Exercise downstream derivation only; this is not same-UID-safe creation."""
    def create(parent_fd):
        created = Path(tempfile.mkdtemp(prefix='profile-', dir=f'/proc/self/fd/{parent_fd}'))
        fd = os.open(created.name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                     dir_fd=parent_fd)
        return created.name, fd

    monkeypatch.setattr(backup._RamProfileOutput, '_create_directory', staticmethod(create))


@pytest.fixture
def ram_profile_inputs(tmp_path, monkeypatch, ram_artifact_validator):
    """Small synthetic assets exercise binding only; no QEMU or 1GiB image creation."""
    native = tmp_path/'runtime/analysis'
    seed = native/'menu-root/seed-backup.bin'
    seed.parent.mkdir(parents=True)
    seed.write_bytes(b'S' * 2390264)
    monkeypatch.setattr(backup, 'SEED_SHA', backup.sha(seed))
    monkeypatch.setattr(backup, 'PRIMARY_SHA', backup.hashlib.sha256(seed.read_bytes()[0xed000:]).hexdigest())
    (tmp_path/'report').symlink_to(HERE.parents[1]/'report', target_is_directory=True)
    launcher = native/'qemu-kernel-probe.sh'
    launcher.write_bytes((HERE/'qemu-kernel-probe.sh').read_bytes())
    board = native/'qemu-virt-board/virt-packed.dtb'
    board.parent.mkdir()
    board.write_bytes((HERE/'qemu-virt-board/virt-packed.dtb').read_bytes())
    official = native/'unpacked/firmware.tar_unpacked/0800_appli/setting/cxd90057.dtb'
    official.parent.mkdir(parents=True)
    official.write_bytes(b'synthetic official-board input; never booted')
    card = native/'menu-root/simulation/media-camera.fat'
    card.parent.mkdir()
    card.write_bytes(b'RAM test card' * 4096)
    monkeypatch.setattr(backup, 'FUNCTIONAL_CAMERA_RAM_BYTES', card.stat().st_size)
    original_load = backup.load_module

    def synthetic_board(base, output, official_source, **flags):
        base, output, official_source = map(iomap_module.Path, (base, output, official_source))
        assert base.parent == output.parent == official_source.parent
        assert str(output.parent).startswith('/proc/self/fd/')
        assert base.read_bytes() == board.read_bytes()
        assert official_source.read_bytes() == official.read_bytes()
        assert flags == dict(all_pcie_wrappers=True, ccf_provider=True,
                             phy_upload=True, dma_window=True, backup_control=True)
        # Exercise the production iomap Path contract without booting any assets.
        assert not output.exists() and base.resolve() != output.resolve()
        output.write_bytes(base.read_bytes() + b'SYNTHETIC-DERIVATION')
        (output.parent/'iomap-board-proof.json').write_text('{"synthetic": true}\n')
        return output

    iomap_module = mock.Mock(Path=Path, prepare=synthetic_board)

    def load(name, path):
        if name == 'backup_iomap_board':
            return iomap_module
        return original_load(name, path)

    monkeypatch.setattr(backup, 'load_module', load)
    build, _ = build_fixture(tmp_path)
    selected = load_script('functional_camera_ram_prepare', 'start-menu.py').profile_environment(
        {**ram_environment(tmp_path), 'A7C2_BACKUP_BUILD': str(build)}, natural_boot=True)
    return native, selected, card, tmp_path/'profiles'


@pytest.mark.parametrize('scope', ['', '/explicit/reviewed-scope-build.json'])
def test_ram_profile_runner_artifact_refusal_precedes_all_input_hashing(
        ram_profile_inputs, ram_artifact_validator, scope):
    native, env, card, output_parent = ram_profile_inputs
    validator, _ = ram_artifact_validator
    env['A7C2_SCOPE_OBSERVER_BUILD'] = scope
    validator.side_effect = ValueError('Functional camera artifact identity rejected')
    with mock.patch.object(backup, '_bound_profile_input') as bound:
        with pytest.raises(ValueError, match='artifact identity rejected'):
            backup.prepare_profile(native, env, output_parent)
        bound.assert_not_called()
    validator.assert_called_once_with(native, Path(env['A7C2_BACKUP_BUILD'])/'build/qemu-system-aarch64',
                                      scope_build_receipt=scope or None)
    assert not output_parent.exists()


def test_ram_lease_forwards_explicit_model_before_card_hashing(ram_profile_inputs, ram_artifact_validator):
    native, env, _, output_parent = ram_profile_inputs
    validator, _ = ram_artifact_validator
    candidate = native.parents[1] / 'isolated-model/runtime/analysis'
    with pytest.raises(ValueError, match='live RAM-card lease'):
        backup.prepare_profile(native, env, output_parent, _model_base=candidate)
    validator.assert_not_called()
    validator.side_effect = ValueError('Candidate model rejected')
    with mock.patch.object(backup, '_bound_profile_input') as bound:
        with pytest.raises(ValueError, match='Candidate model rejected'):
            with backup.ram_profile_lease(native, env, output_parent, parallel_peak_bytes=0, model_base=candidate):
                pytest.fail('Failed model verification must not admit a lease')
        bound.assert_not_called()
    validator.assert_called_once_with(candidate, Path(env['A7C2_BACKUP_BUILD'])/'build/qemu-system-aarch64',
                                      scope_build_receipt=None)
    assert not output_parent.exists()


def test_ram_profile_missing_real_model_artifact_fails_before_card_hashing(
        ram_profile_inputs, ram_artifact_validator):
    native, env, card, output_parent = ram_profile_inputs
    validator, actual = ram_artifact_validator
    validator.side_effect = actual
    with mock.patch.object(backup, '_bound_profile_input') as bound:
        with pytest.raises(FileNotFoundError, match='functional-camera-model-build.json'):
            backup.prepare_profile(native, env, output_parent)
        bound.assert_not_called()
    assert not output_parent.exists()


def test_ram_profile_creation_has_no_path_based_fallback(ram_profile_inputs):
    native, env, card, output_parent = ram_profile_inputs
    with mock.patch.object(tempfile, 'mkdtemp', side_effect=AssertionError('path creation must not run')) as create:
        with pytest.raises(ValueError, match='directory creation refused: no atomic creation identity'):
            backup.prepare_profile(native, env, output_parent)
    create.assert_not_called()
    assert not list(output_parent.iterdir())


def test_ram_profile_consumer_handoff_is_fixed_refusal():
    with pytest.raises(ValueError, match='consumer handoff refused: no caller-held exact FD binding'):
        backup._RamProfileOutput.consumer_environment()


def test_ram_profile_derives_local_evidence_but_refuses_path_only_consumer_handoff(
        ram_profile_inputs, synthetic_ram_directory_creation):
    native, env, card, output_parent = ram_profile_inputs
    before = copy.deepcopy(env)
    originals = {path: backup.sha(path) for path in (
        native/'qemu-kernel-probe.sh', native/'qemu-virt-board/virt-packed.dtb', card)}
    with pytest.raises(ValueError, match='consumer handoff refused: no caller-held exact FD binding'):
        backup.prepare_profile(native, env, output_parent)
    output, = output_parent.glob('profile-*')
    selected = {'MENU_BACKUP_PROFILE_RECEIPT': str(output/'backup-profile.json'),
                'MENU_KERNEL_SCRIPT': str(output/'kernel-ram-backup.sh'),
                'MENU_DTB': str(output/'board-ram-backup.dtb')}
    proof = json.loads(Path(selected['MENU_BACKUP_PROFILE_RECEIPT']).read_text())
    script = Path(selected['MENU_KERNEL_SCRIPT']).read_text()
    assert proof['consumer_handoff'] == 'refused-path-only-no-caller-held-fds'
    assert proof['consumer_binding_verified'] is False
    assert 'driver=vvfat' not in script and '-device usb-net' not in script
    assert '--setenv QEMU_SONY_USB_NET 1' not in script
    assert '--setenv QEMU_SONY_BACKUP_TEST 1' in script
    assert '--setenv QEMU_SONY_DFS_TEST 1' in script
    assert 'project_dir=' + str(native.parent) in script
    assert proof['schema'] == 'a7c2-functional-camera-ram-media-v1'
    assert proof['physical_compatible'] is False
    assert proof['media_profile'] == backup.FUNCTIONAL_CAMERA_RAM_MEDIA_CANDIDATE
    assert proof['media_seed_source'] == str(card)
    assert proof['media_seed_sha256'] == backup.sha(card)
    assert proof['media_seed_bytes'] == card.stat().st_size
    assert proof['media_seed_identity'] == list(backup.identity(card.stat()))
    for field in ('source_backup_seed', 'source_script', 'source_board', 'official_board', 'source_binary'):
        source = proof[field]
        assert set(source) == {'path', 'bytes', 'sha256', 'identity'}
        assert source['sha256'] == backup.sha(source['path'])
        assert source['identity'] == list(backup.identity(Path(source['path']).stat()))
    assert proof['derived_script_sha256'] == backup.sha(selected['MENU_KERNEL_SCRIPT'])
    assert proof['derived_board_sha256'] == backup.sha(selected['MENU_DTB'])
    assert proof['source_binary']['sha256'] == proof['binary_sha256']
    assert not proof['directory_sd_added'] and not proof['usb_ethernet_added']
    assert not proof['capture_verified'] and not proof['original_cp_executed']
    assert all(proof['functional_camera_' + claim] is False for claim in CLAIMS)
    assert env == before
    assert {path: backup.sha(path) for path in originals} == originals
    for key in ('MENU_KERNEL_SCRIPT', 'MENU_DTB', 'MENU_BACKUP_PROFILE_RECEIPT'):
        assert Path(selected[key]).is_file() and not selected[key].startswith('/proc/')
    output = Path(selected['MENU_BACKUP_PROFILE_RECEIPT']).parent
    assert (output/'.backup-profile.pending.json').read_bytes() == (output/'backup-profile.json').read_bytes()
    assert json.loads((output/'iomap-board-proof.json').read_text()) == {'synthetic': True}
    with pytest.raises(ValueError, match='consumer handoff refused: no caller-held exact FD binding'):
        backup.prepare_profile(native, env, output_parent)
    assert len(list(output_parent.glob('profile-*'))) == 2


@pytest.mark.parametrize('replacement', ['rename', 'symlink', 'directory'])
def test_ram_profile_rejects_directory_rebinding_immediately_after_creation(ram_profile_inputs, replacement):
    native, env, card, output_parent = ram_profile_inputs
    external = output_parent.parent/'external'
    external.mkdir(mode=0o700)
    sentinel = external/'source-board.dtb'
    sentinel.write_bytes(b'never overwrite this unrelated file')
    before = {path.name: backup._bound_profile_input(path)[0] for path in external.iterdir()}
    create = backup._RamProfileOutput._create_directory
    retained = []
    replacements = []

    def replace_created(parent_fd):
        # A real renamed/replaced directory cannot supply an atomic creation proof.
        created = Path(tempfile.mkdtemp(prefix='profile-', dir=f'/proc/self/fd/{parent_fd}'))
        saved = created.with_name(created.name + '-retained')
        created.rename(saved)
        retained.append(output_parent/saved.name)
        if replacement == 'symlink':
            created.symlink_to(external, target_is_directory=True)
        elif replacement == 'directory':
            created.mkdir(mode=0o700)
            replacements.append(output_parent/created.name)
        return create(parent_fd)

    with mock.patch.object(backup._RamProfileOutput, '_create_directory', side_effect=replace_created):
        with pytest.raises(ValueError, match='directory creation refused: no atomic creation identity'):
            backup.prepare_profile(native, env, output_parent)
    assert retained and all(path.is_dir() and not list(path.iterdir()) for path in retained)
    assert all(path.is_dir() and not list(path.iterdir()) for path in replacements)
    assert {path.name: backup._bound_profile_input(path)[0] for path in external.iterdir()} == before
    assert not list(output_parent.glob('profile-*/backup-profile.json'))


@pytest.mark.parametrize('scope', ['profile', 'parent'])
@pytest.mark.parametrize('replacement', ['symlink', 'directory'])
def test_ram_profile_iomap_stays_on_held_directory_after_public_rebinding(
        ram_profile_inputs, synthetic_ram_directory_creation, scope, replacement):
    native, env, card, output_parent = ram_profile_inputs
    external = output_parent.parent/'external'
    external.mkdir(mode=0o700)
    for name in ('source-board.dtb', 'board-ram-backup.dtb', 'iomap-board-proof.json'):
        (external/name).write_bytes(b'unrelated content: ' + name.encode())
    before = {path.name: backup._bound_profile_input(path)[0] for path in external.iterdir()}
    load = backup.load_module
    retained = []

    def rebinding_load(name, path):
        module = load(name, path)
        if name == 'backup_iomap_board':
            prepare = module.prepare

            def rebind(*args, **kwargs):
                profile, = output_parent.glob('profile-*')
                public = profile if scope == 'profile' else output_parent
                saved = public.with_name(public.name + '-retained')
                public.rename(saved)
                retained.append(saved if scope == 'profile' else saved/profile.name)
                if replacement == 'symlink':
                    public.symlink_to(external, target_is_directory=True)
                else:
                    public.mkdir(mode=0o700)
                return prepare(*args, **kwargs)

            module.prepare = rebind
        return module

    with mock.patch.object(backup, 'load_module', side_effect=rebinding_load):
        with pytest.raises((OSError, ValueError)):
            backup.prepare_profile(native, env, output_parent)
    assert {path.name: backup._bound_profile_input(path)[0] for path in external.iterdir()} == before
    assert retained and (retained[0]/'board-ram-backup.dtb').is_file()
    assert (retained[0]/'kernel-ram-backup.sh').is_file()
    assert not (retained[0]/'backup-profile.json').exists()
    if replacement == 'directory':
        public = output_parent if scope == 'parent' else output_parent/retained[0].name.removesuffix('-retained')
        assert not list(public.iterdir())


@pytest.mark.parametrize('target', ['source-board.dtb', 'official-board.dtb', 'backup-primary.bin',
                                    'board-ram-backup.dtb', 'iomap-board-proof.json',
                                    'kernel-ram-backup.sh', '.backup-profile.pending.json'])
def test_ram_profile_every_derived_write_refuses_existing_symlink(
        ram_profile_inputs, synthetic_ram_directory_creation, target):
    native, env, card, output_parent = ram_profile_inputs
    victim = output_parent.parent/'unrelated.bin'
    victim.write_bytes(b'keep original bytes')
    before = backup._bound_profile_input(victim)[0]
    regular = backup.regular
    injected = False

    def inject(parent_fd, name, flags=os.O_RDONLY):
        nonlocal injected
        if name == target and flags & os.O_CREAT and not injected:
            os.symlink(victim, name, dir_fd=parent_fd)
            injected = True
        return regular(parent_fd, name, flags)

    with mock.patch.object(backup, 'regular', side_effect=inject):
        with pytest.raises(FileExistsError):
            backup.prepare_profile(native, env, output_parent)
    assert injected and backup._bound_profile_input(victim)[0] == before
    assert not list(output_parent.glob('profile-*/backup-profile.json'))


def test_ram_profile_retracts_receipt_and_preserves_staging_if_publication_path_changes(
        ram_profile_inputs, synthetic_ram_directory_creation):
    native, env, card, output_parent = ram_profile_inputs
    external = output_parent.parent/'external'
    external.mkdir(mode=0o700)
    sentinel = external/'backup-profile.json'
    sentinel.write_bytes(b'unrelated receipt')
    before = backup._bound_profile_input(sentinel)[0]
    link = backup.os.link
    retained = []

    def rebind_after_link(*args, **kwargs):
        result = link(*args, **kwargs)
        profile, = output_parent.glob('profile-*')
        saved = profile.with_name(profile.name + '-retained')
        profile.rename(saved)
        profile.symlink_to(external, target_is_directory=True)
        retained.append(saved)
        return result

    with mock.patch.object(backup.os, 'link', side_effect=rebind_after_link):
        with pytest.raises(ValueError, match='output directory changed'):
            backup.prepare_profile(native, env, output_parent)
    assert backup._bound_profile_input(sentinel)[0] == before
    assert retained and (retained[0]/'.backup-profile.pending.json').is_file()
    assert not (retained[0]/'backup-profile.json').exists()


@pytest.mark.parametrize('change', ['rewrite', 'replace'])
def test_ram_profile_rejects_derived_identity_drift_even_with_identical_bytes(
        ram_profile_inputs, synthetic_ram_directory_creation, change):
    native, env, card, output_parent = ram_profile_inputs
    load = backup.load_module

    def drifting_load(name, path):
        module = load(name, path)
        if name == 'backup_iomap_board':
            prepare = module.prepare

            def derive(*args, **kwargs):
                result = prepare(*args, **kwargs)
                output = Path(result)
                raw = output.read_bytes()
                before = output.stat()
                if change == 'replace':
                    output.rename(output.with_name('retained-original-board.dtb'))
                output.write_bytes(raw)
                os.utime(output, ns=(before.st_atime_ns, before.st_mtime_ns + 1))
                return result

            module.prepare = derive
        return module

    with mock.patch.object(backup, 'load_module', side_effect=drifting_load):
        with pytest.raises(ValueError, match='derived file identity changed'):
            backup.prepare_profile(native, env, output_parent)
    assert not list(output_parent.glob('profile-*/backup-profile.json'))


def test_ram_profile_rejects_iomap_returning_an_unbound_path(
        ram_profile_inputs, synthetic_ram_directory_creation):
    native, env, card, output_parent = ram_profile_inputs
    load = backup.load_module

    def wrong_return(name, path):
        module = load(name, path)
        if name == 'backup_iomap_board':
            prepare = module.prepare

            def derive(*args, **kwargs):
                prepare(*args, **kwargs)
                return output_parent/'different-board.dtb'

            module.prepare = derive
        return module

    with mock.patch.object(backup, 'load_module', side_effect=wrong_return):
        with pytest.raises(ValueError, match='unexpected output path'):
            backup.prepare_profile(native, env, output_parent)
    assert not list(output_parent.glob('profile-*/backup-profile.json'))


@pytest.mark.parametrize('change', ['missing', 'small', 'symlink', 'relative'])
def test_ram_profile_real_source_binding_fails_before_output(ram_profile_inputs, change):
    native, env, card, output_parent = ram_profile_inputs
    if change == 'missing':
        env['A7C2_SD_IMAGE'] = str(card.with_name('missing.fat'))
    elif change == 'small':
        card.write_bytes(b'wrong size')
    elif change == 'symlink':
        link = card.with_name('link.fat')
        link.symlink_to(card)
        env['A7C2_SD_IMAGE'] = str(link)
    else:
        env['A7C2_SD_IMAGE'] = 'relative-card.fat'
    with pytest.raises((OSError, ValueError)):
        backup.prepare_profile(native, env, output_parent)
    assert not output_parent.exists()


def test_ram_binding_rejects_non_1g_before_hashing(tmp_path):
    path = tmp_path/'small.fat'
    path.write_bytes(b'too small')
    assert backup.FUNCTIONAL_CAMERA_RAM_BYTES == 1024**3
    with mock.patch.object(backup, 'digest_fd') as digest:
        with pytest.raises(ValueError, match='expected 1073741824 bytes'):
            backup._bound_profile_input(path, expected_bytes=backup.FUNCTIONAL_CAMERA_RAM_BYTES)
        digest.assert_not_called()


def test_ram_profile_source_drift_never_publishes_receipt(
        ram_profile_inputs, synthetic_ram_directory_creation):
    native, env, card, output_parent = ram_profile_inputs
    original_read = backup._bound_profile_input
    seen = 0

    def drifting(path, **options):
        nonlocal seen
        if Path(path) == card:
            seen += 1
            if seen == 2:
                card.write_bytes(b'X' * card.stat().st_size)
        return original_read(path, **options)

    with mock.patch.object(backup, '_bound_profile_input', side_effect=drifting):
        with pytest.raises(ValueError, match='source changed during derivation'):
            backup.prepare_profile(native, env, output_parent)
    assert not list(output_parent.glob('profile-*/backup-profile.json'))


def test_ram_media_candidate_rejects_guest_only_override(tmp_path):
    launcher = load_script('functional_camera_guest_media', 'start-menu.py')
    env = {**environment(tmp_path),
           'MENU_FUNCTIONAL_CAMERA_MEDIA': backup.FUNCTIONAL_CAMERA_RAM_MEDIA_CANDIDATE}
    with pytest.raises(ValueError, match='not a supported guest override'):
        launcher.profile_environment(env, natural_boot=True)
    with mock.patch.object(backup, 'validate_build') as build:
        with pytest.raises(ValueError, match='not a supported guest override'):
            backup.prepare_profile(HERE, env)
        build.assert_not_called()


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
        with directory_lease(tmp_path / 'card') as lease, mock.patch.object(
                runner, 'validate_artifact', side_effect=AssertionError('directory profile must keep its existing admission')) as artifact:
            host.update(directory_profile(HERE, lease, tmp_path / 'directory-profile'))
            host.update(synthetic_backup_profile(host))
        artifact.assert_not_called()
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

