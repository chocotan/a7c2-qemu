#!/usr/bin/env python3
"""Read-only functional-camera evidence joins. No VM, model loading, or media creation.

API: evaluate(run, batch) -> {verdict, evidence, missing, products,
                            capture_verified, physical_asic_compatibility_verified}.
`batch` is the completed immutable unified-camera directory or its ready.json.
The checker accepts only complete same-run original-request, RGB consumer,
compressed-content, original MPR/Fsys, SD readback and independent decode joins.
Physical ASIC and original CP/RTOS compatibility are separate, unverified claims.
"""
import argparse
import errno
import hashlib
import io
import json
import math
import os
from pathlib import Path
import re
import stat
import struct
import tarfile
import types

NATIVE = Path(__file__).resolve().parents[2]
RUNTIME = NATIVE / 'runtime/analysis'
PROFILE = 'virtual-functional-camera-v1'
QEMU_SHA256 = 'a0d1bdd8a9aad822efe47f740a104972cac6ec1875265e8174b25349f54fee02'
READONLY_SCOPE_QEMU_SHA256 = '4e85c70ba38774e9439562a7178a65bdbe6b660fdf8dd6bd4ece686fb707a4d4'
MAX_FILE = 256 * 1024**2
MAX_LOG = 64 * 1024**2
MAX_EVENTS = 100000
DATA_BYTES = 65024
OPS = {1: (0, 48), 2: (0,), 3: (48,), 4: (32,), 5: (16,), 6: (8,), 7: (32,), 8: (16,),
       9: (32,), 10: (8,), 11: tuple(360 + 8 * (cp + sdk) for cp in (100, 13, 14) for sdk in (1, 2)),
       12: (8,), 13: (16,), 14: (32,), 16: (16, 144),
       17: (16,), 18: (32, 160), 19: (16,), 20: (2564,), 21: (12,), 22: (20,), 23: (12,),
       32: (48,), 33: (0, 4), 34: (0,), 64: (24,), 65: (16,), 66: (0,)}
VDF_POLICY = {
    'vdf_path_policy': 'canonical-0138-single-RGB-sink-readback-before-1138',
    'vdf_virtual_endpoint': 0x90590819,
    'vdf_virtual_completion_mask': 1,
    'original_VDF_selector_verified': False,
    'original_VDF_CP_FIFO_verified': False,
}
ZEBRA_POLICY = {
    'zebra_policy': 'original-0153-disabled-pass-through-RGB-sink-readback-before-1153',
    'zebra_enabled_supported': False,
    'original_Zebra_gate_verified': False,
}
LAYOUT_POLICY = {
    'layout_policy': 'original-014c-initial-case0-full-RGB-passthrough-readback-before-114c',
    'layout_virtual_area_order': 'x-y-width-height',
    'layout_virtual_zero_output': 'full-frame-pass-through',
    'layout_supported_rgb_geometry': [640, 480, 1920],
    'layout_initial_body_hex': '07010100000000008002e0010000000000000000000000000300000000000000',
    'original_VDF_area_order_verified': False,
    'original_VDF_layout_hardware_verified': False,
}
STARTUP_LAYOUT_POLICY = {
    'startup_layout_policy': 'guest-local-canonical-initial-register-stage-before-active-route',
    'startup_layout_stage_only': True,
    'startup_layout_frame_completion': False,
}
DISPLAY_POLICY = {
    'display_config_policy': 'original-display-controls-plus-functional-0170-three-boolean-RGB-identity-readback-before-independent-reply',
    'display_config_commands': [0x141, 0x152, 0x162, 0x163, 0x170],
    'peaking_enabled_supported': False,
    'display_flag_enabled_supported': False,
    'original_Peaking_operator_verified': False,
    'original_0162_feature_verified': False,
}
ZERO6_DISPLAY_POLICY = {
    **DISPLAY_POLICY,
    'display_config_policy': 'original-0141-refresh-0152-disabled-0162-off-0163-zero6-RGB-readback-before-independent-reply',
    'display_config_commands': [0x141, 0x152, 0x162, 0x163],
}
LEGACY_DISPLAY_POLICY = {
    **DISPLAY_POLICY,
    'display_config_policy': 'original-0141-refresh-0152-disabled-and-0162-off-RGB-readback-before-independent-reply',
    'display_config_commands': [0x141, 0x152, 0x162],
}
BIT_WIDTH_POLICY = {
    'display_bit_width_policy': 'original-015e-selector0-virtual-RGB888-readback-before-115e',
    'display_bit_width_commands': [0x15e],
    'display_bit_width_supported_selectors': [0],
    'display_bit_width_selector_mapping': 'explicit-software-only-physical-selector-meaning-unverified',
    'display_bit_width_physical_mapping_verified': False,
}
STILL_FORMAT_POLICY = {
    'still_format_policy': 'original402d-observed-L-Fine-dual-slot-RGB-identity-readback-before-echo-f000',
    'still_format_commands': [0x402d],
    'still_format_request_bytes': 24,
    'still_format_canonical16_hex': '02000001000100000001000100000000',
    'still_format_opaque_tail_policy': 'preserve-original22-23-not-consumed-canonical-tail-zero',
    'still_format_initial_diagnostic_policy': 'preserved-one-shot-before-functional-model-active',
    'still_format_physical_selector_mapping_verified': False,
}
STILL_FORMAT_CANONICAL = bytes.fromhex(STILL_FORMAT_POLICY['still_format_canonical16_hex'])
STARTUP_CONTROL_POLICY = {
    'startup_control_policy': 'original4014-observed-and4057-load-current-virtual-config-before-echo-f000',
    'startup_control_commands': [0x4014, 0x4057],
    'startup_control_canonical_layout': 'cmd16-length16-body16-reserved4-current-config40-FNV64',
    'startup_control_config_fingerprint': 'actual-STATE128-bytes8:48-FNV1a64',
    'startup_control_settings_policy': 'request0-independent-current-config40-checkpoint-no-MR-profile',
    'startup_control_initial_diagnostic_policy': 'preserved-one-shot-before-functional-successor',
    'startup_control_physical_mapping_verified': False,
}
BB_POLICY = {
    'bb_startup_config_policy': 'initial-C-config-banks-RGB-readback-before-independent-reply',
    'bb_startup_config_commands': [0x111, 0x166, 0x167, 0x15f, 0x128],
    'bb_startup_neutral_only': False,
    'bb_startup_other_commands_neutral_only': True,
    'bb_startup_0166_observed_initial_body_hex': '00010000000000000000000008000000070000000100000001000000',
    'bb_startup_0166_identity_policy': 'explicit-neutral-or-exact-observed-initial-tuple-RGB-identity',
    'bb_startup_gain_nonzero_supported': False,
    'bb_startup_interval_enabled_supported': False,
    'original_BB_C_configuration_work_verified': False,
    'original_BB_C_configuration_units_verified': False,
}
HIST_POLICY = {
    'histogram_policy': 'first-enabled-mode1-RGB-u8-peak-YRGB-before-1148-and-210c',
    'histogram_commands': [0x148],
    'histogram_channels': ['virtual-Y', 'R', 'G', 'B'],
    'histogram_bins_per_channel': 256,
    'histogram_value_format': 'u8-peak-height-255',
    'histogram_luma_formula': '(77R+150G+29B+128)>>8',
    'histogram_normalization_formula': '(count*255+peak/2)/peak',
    'histogram_notification_selector': 1,
    'histogram_notification_logical_bytes': 1034,
    'histogram_mode0_supported': False,
    'histogram_reenable_supported': False,
    'histogram_continuous_supported': False,
    'original_Histogram_bin_semantics_verified': False,
    'original_Histogram_physical_callback_verified': False,
    'histogram_UI_applied_verified': False,
}
XSYNC_POLICY = {
    'xsync_capability_policy': 'virtual-one-model-frame-period-from-State128-fps-canonical-AP-pair',
    'xsync_clock_source': 'State128.fps',
    'xsync_readout_frame_periods': 1,
    'xsync_current_exposure_independent': True,
    'xsync_noncanonical_clock_policy': 'reject-before-mode1-ACK',
    'xsync_canonical_clock_rates': [1, 2, 4, 5, 6, 8, 10, 13, 15, 20, 25, 30, 40, 45, 50, 60, 80, 90, 100],
    'xsync_flash_trigger_supported': False,
    'original_Xsync_state_producer_verified': False,
    'physical_Xsync_capability_verified': False,
}
BACKGROUND_POLICY = {
    'cp_background_start_policy': 'original-3006-pending-all13-free-model-INIT-STATE-readback-before-independent-reply',
    'cp_background_start_native_commands': [0x3006],
    'cp_background_start_deferred_until': 'same-run-all13-original-free-and-actual-debugger-handoff',
    'cp_background_start_original_modules_verified': False,
}
CP_PARAMETER_BANK_POLICY = {
    'cp_parameter_bank_policy': 'full190-opaque-bank-4151u32-fps-configure-live-State128-independent-readback-v1',
    'cp_parameter_bank_opcode': 20,
    'cp_parameter_bank_native_commands': [0x4063],
    'cp_parameter_bank_bytes': 2564,
    'cp_parameter_bank_slots': 190,
    'cp_parameter_bank_result_bytes': 2756,
    'cp_parameter_bank_fps_input_offset': 0x86c,
    'cp_parameter_bank_reply_policy': 'oneway-original-request-free-no-ACK-no-notification',
    'cp_parameter_bank_physical_semantics_verified': False,
}
CP_CRANK_CONTROL_POLICY = {
    'cp_crank_control_policy': 'active-config-crank-mode0-v1',
    'cp_crank_control_opcode': 21,
    'cp_crank_control_native_commands': [0x409d],
    'cp_crank_control_bytes': 12,
    'cp_crank_control_result_bytes': 208,
    'cp_crank_control_supported_modes': [0],
    'cp_crank_control_input_policy': 'full-original12-byte1-cookie-opaque-body4zero',
    'cp_crank_control_bank_policy': 'current-committed-instance-bank-generation-once',
    'cp_crank_control_state_policy': 'live-State128-config-generation-plus-one-all-other-bytes-preserved',
    'cp_crank_control_reply_policy': 'independent-type1-409d-echo-cookie-f000-original-receive-free',
    'cp_crank_control_initial_diagnostic_policy': 'preserved-strict-initial409d-before-functional-bank',
    'cp_crank_control_frame_production_supported': False,
    'cp_crank_control_physical_semantics_verified': False,
}
CP_MOVIE_FORMAT_POLICY = {
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
CP_OU_CRANK_CONTROL_POLICY = {
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
CP_MOVIE_NATIVE_JOINS = (
    'original FUNCTIONAL_CP_MOVIE_FORMAT_EVENT/BYTES exact formatter and complete transaction streams',
    'same-instance current bank/crank actual native request/reply/free completion',
    'independent reply12 type1/4000/cookie/f000 real transport receive and same-sender reply free',
    'resource35 dependencies/TTS144/two idle DMM slots/PIN/VEF/all13/current-mode retirement',
    'unchanged clean early strict4000 history and immutable original event tickets',
)
CP_CRANK_NATIVE_JOINS = (
    'original FUNCTIONAL_CP_CRANK_CONTROL_EVENT/BYTES exact formatter and complete transaction streams',
    'same-transaction resource34 dependencies/TTS/reserved cohort after the completed current bank',
    'actual independent ACK12 type1/409d/cookie/f000 plus source/destination metadata readback',
    'event-bound original request free and matching sender/waiter receive/reply-free tickets',
    'clean strict initial409d and later40f9 stage/free predecessors without history reset',
)
CP_CRANK_EVENT_SCHEMA = (
    'event:crank_event pid:pid tid:tid transaction:u64 sender_tid:tid receiver_tid:tid source:hex32 destination:hex32 '
    'command:hex32 bytes:u32 native_fnv1a:digest cookie:hex32 busy:bit guard:bit faults:u32 error:i32 '
    'before_rc:i32 model_rc:i32 after_rc:i32 model_called:bit model_committed:bit verified:bit owned:bit complete:bit '
    'retained_request:pointer retained_reply:pointer request_pointer:pointer reply_pointer:pointer allocation_pointer:pointer '
    'request_releasing:bit request_freed:bit request_free_rc:i32 request_free_tid:tid reply_releasing:bit reply_inspecting:bit '
    'reply_allocated:bit reply_valid:bit reply_alias:bit allocate_rc:i32 send_started:bit send_inflight:bit send_rc:i32 ACK_sent:bit '
    'reply_received:bit receive_rc:i32 reply_freed:bit reply_cleanup_freed:bit reply_free_rc:i32 reply_free_tid:tid reply_consumed:bit '
    'requests:u64 commits:u64 verified_commits:u64 completions:u64 model_instance:u64 bank_generation:u64 crank_generation:u64 '
    'last_bank_generation:u64 last_crank_generation:u64 before_config_generation:u64 config_generation:u64 frame_generation:u64 '
    'mode:u32 fps:u32 bank_transaction:u64 bank_commits:u64 bank_released:u64 bank_source:hex32 bank_destination:hex32 '
    'bank_command:hex32 bank_bytes:u32 bank_native_fnv1a:digest receipt_fnv1a:digest reply_fnv1a:digest '
    'before_used:u64 before_required:u64 before_token:u64 before_instance:u64 crank_used:u64 crank_required:u64 crank_token:u64 '
    'crank_instance:u64 after_used:u64 after_required:u64 after_token:u64 after_instance:u64 '
    'policy:active-config-crank-mode0-v1 functional_model:1 original_CP:0 physical_ASIC_verified:0 EE:0 frame:0 capture:0 capture_verified:0')
CP_CRANK_BYTES_SCHEMA = (
    'event:crank_event pid:pid tid:tid transaction:u64 kind:crank_kind total:u64 offset:u64 bytes:u64 raw:raw '
    'native_fnv1a:digest content_fnv1a:digest model_instance:u64 bank_generation:u64 crank_generation:u64 '
    'functional_model:1 original_CP:0 physical_ASIC_verified:0 capture_verified:0')
CP_OU_CRANK_EVENT_SCHEMA = (
    'event:ou_event pid:pid tid:tid transaction:u64 sender_tid:tid source:hex32 destination:hex32 command:hex32 bytes:u32 '
    'native_fnv1a:digest cookie:hex32 busy:bit guard:bit guard_fault:bit faults:u32 error:i32 before_rc:i32 model_rc:i32 after_rc:i32 validation_rc:i32 '
    'model_called:bit model_committed:bit verified:bit owned:bit complete:bit retained_request:pointer request_pointer:pointer '
    'releasing:bit request_freed:bit free_rc:i32 free_tid:tid requests:u64 commits:u64 verified_commits:u64 completions:u64 released:u64 '
    'model_instance:u64 bank_generation:u64 crank_generation:u64 movie_generation:u64 ou_generation:u64 '
    'last_bank_generation:u64 last_crank_generation:u64 last_movie_generation:u64 last_ou_generation:u64 '
    'before_config_generation:u64 config_generation:u64 frame_generation:u64 mode:u32 fps:u32 '
    'bank_transaction:u64 bank_commits:u64 bank_released:u64 bank_source:hex32 bank_destination:hex32 bank_command:hex32 bank_bytes:u32 bank_native_fnv1a:digest '
    'crank_transaction:u64 crank_completions:u64 crank_source:hex32 crank_destination:hex32 crank_command:hex32 crank_bytes:u32 crank_native_fnv1a:digest '
    'movie_transaction:u64 movie_completions:u64 movie_source:hex32 movie_destination:hex32 movie_command:hex32 movie_bytes:u32 movie_native_fnv1a:digest '
    'startup_cycle:u64 startup_completed_cycles:u32 startup_config_generation:u64 startup_frame_generation:u64 startup_lease_generation:u64 '
    'startup_result_fnv1a:digest startup_config40_fnv1a:digest startup_source:hex32 startup_destination:hex32 startup_command:hex32 startup_bytes:u32 startup_native_fnv1a:digest '
    'receipt_fnv1a:digest before_used:u64 before_required:u64 before_token:u64 before_instance:u64 '
    'ou_used:u64 ou_required:u64 ou_token:u64 ou_instance:u64 after_used:u64 after_required:u64 after_token:u64 after_instance:u64 '
    'resource:36 policy:active-config-ou-crank-mode0-v1 oneway:1 ACK_sent:0 notification_sent:0 '
    'functional_model:1 original_CP:0 physical_ASIC_verified:0 EE:0 frame:0 capture:0 capture_verified:0')
CP_OU_CRANK_BYTES_SCHEMA = (
    'event:ou_event pid:pid tid:tid transaction:u64 kind:bank_kind total:u64 offset:u64 bytes:u64 raw:raw '
    'native_fnv1a:digest content_fnv1a:digest model_instance:u64 bank_generation:u64 crank_generation:u64 movie_generation:u64 ou_generation:u64 '
    'functional_model:1 original_CP:0 physical_ASIC_verified:0 capture_verified:0')

BACKGROUND_FREE_TAGS = tuple('FULL_' + name + suffix for name, suffix in (
    ('IMAGING_PIN_CONNECT', '_REPLY_FREE'), ('IMAGING_CONTROL_CONNECT', '_REPLY_FREE'),
    ('IMAGING_ADF_CONNECT', '_REPLY_FREE'), ('INFRABB_VEF_CONNECT', '_REPLY_FREE'),
    ('INFRABB_VEF_CONTROL_CONNECT', '_REPLY_FREE'), ('VEF_PINMEM_INPUT_CONNECT', '_REPLY_FREE'),
    ('VEF_PINMEM_CONTROL_CONNECT', '_REPLY_FREE'), ('SCALAR_CONNECT', '_NATIVE_REPLY_FREE'),
    ('ADF_CONNECT', '_NATIVE_REPLY_FREE'), ('PINMEM_DRAWINFO_CONNECT', '_NATIVE_REPLY_FREE'),
    ('PINMEM_HDMI_VIDEO_CONNECT', '_NATIVE_REPLY_FREE'), ('PINMEM_OSD_CONNECT', '_NATIVE_REPLY_FREE'),
    ('ADF_HDMI_AUDIO_CONNECT', '_REPLY_FREE')))
BB_COMMANDS = {0x111: 36, 0x166: 36, 0x167: 10, 0x15f: 12, 0x128: 20}
VDF_OPERATIONS = {5: ({0x138: 24}, 160), 6: ({0x153: 14}, 168), 7: ({0x14c: 40}, 192),
                  8: ({0x141: 8, 0x152: 16, 0x162: 10, 0x163: 14, 0x170: 12}, 176), 9: (BB_COMMANDS, 192),
                  12: ({0x15e: 10}, 168)}
CONFIG_OPERATIONS = {**VDF_OPERATIONS, 10: ({0x148: 12}, 1192), 13: ({0x402d: 24}, 176),
                     14: ({0x4014: 24, 0x4057: 12, 0x403f: 16}, 192)}
STARTUP_CONTROL_MODE_BODY = bytes.fromhex('00000100010000000100000000000000')
FOCUS_RESET_POLICY = 'actual-optical-frame-focus-off-v1'
HIST_CANONICAL = bytes.fromhex('4801040001010000')
PUBLIC_LIBRARIES = {
    'usr/lib/appFw.so': '2ea02f7ecbc5bb917316fe8ef4ce5ffd87eb66efaae78ba2ce11420552df539b',
    'usr/lib/libObj.so': 'c0897d72a40bf0a161fa7f89e9a34eef4d19e0506c7817a5c11a6f53897cdbbc',
    'usr/lib/libmpr.so': '4fb6d886c1ac620399d09c9c2ffc074315968cf0ada764062913c4e0783fc7f9',
    'usr/lib/libInfraFsys.so': '33451a884b65f946ac8aca44b620cd3cec677d05752c52f2ff0e212a01824bfa',
    'usr/lib/libInfraAvbbc.so': '676197567dbbefa54e08f528968efc6ca2aaffe8bee3ee3eae8164382ed5a7e5',
    'usr/lib/dataflowInfraFramework.so': '620e04a9cd51e65bd190ed1d5459b7235ff5a4109bc6498df342972621991d47',
    'usr/lib/libosal_utm.so': 'd9510b4ce1d7e59a0f2e9b5be14624a4cece6f514879e8a6d23ce890a46d25eb',
    'usr/lib/libInfraMediaMount.so': '90571d016f5f80b4c8cb4d9ff80c7600d19e0199a1ab7cfa6e9ee5d79587f612',
    'usr/lib/libInfraMediaCommon.so': 'd7cd602e9348e51703a6d3da396cfda949ea306856df7fa0deb62df1ff4ca974',
    'usr/lib/libbackup.so': '6a3c5f6067620c00d790cbe520844acdbb721fa5d0e7433b00a227f922ab9d0d',
    'usr/lib/libgpe.so': '80fc6236379933f80c2689aa002e0cf39483da8d45e876705d2a427cd1a2a7d1',
    'usr/lib/libosal_uipc.so': '09ebf5980237fc473077dc844763dcb00cba423f431646e3be7c0ca49ea70ff3',
    'usr/lib/libMWF.so': '63104a2506a385144ee4b485357c72cff7420aedc8d705e40124df20e6f97e69',
    'usr/lib/libInfraMediaConfig.so': '756aa62554f970b7fbfd609d2a53008a3ecc80c608a98ef778baa399efcbebaf',
}


def source_module(path):
    module = types.ModuleType('_functional_evidence_' + path.stem.replace('-', '_'))
    module.__file__ = str(path)
    exec(compile(path.read_bytes(), str(path), 'exec'), module.__dict__)
    return module


# Fixed repository reader, not a caller-selected plugin. It imports only stdlib.
writeback = source_module(NATIVE / 'report/native-card-write/check_writeback.py')
require = writeback.require


class MissingEvidence(ValueError):
    pass


class CrankControlRejected(ValueError):
    """Keep the actual rejected C result and bytes available to the report."""
    def __init__(self, event):
        self.event = event
        super().__init__('crank_control_rejected: actual_c_result=' + repr(event.get('actual_c_result')) +
                         '; error=' + repr(event.get('error')))


class MovieFormatRejected(ValueError):
    """Retain an actual C0 commit even when the independent readback later fails."""
    def __init__(self, event):
        self.event = event
        super().__init__('movie_format_rejected: actual_c_result=' + repr(event.get('actual_c_result')) +
                         '; error=' + repr(event.get('error')))


class OuCrankControlRejected(ValueError):
    """Retain the actual OP23 C result independently of a later validation error."""
    def __init__(self, event):
        self.event = event
        super().__init__('ou_crank_control_rejected: actual_c_result=' + repr(event.get('actual_c_result')) +
                         '; validation_error=' + repr(event.get('validation_error')) + '; error=' + repr(event.get('error')))


def needed(ok, detail):
    if not ok:
        raise MissingEvidence(detail)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def fnv(raw):
    return fnv_update(writeback.FNV_INIT, raw)


def fnv_update(value, raw):
    for byte in raw:
        value = ((value ^ byte) * writeback.FNV_PRIME) & ((1 << 64) - 1)
    return value


def number(text):
    # C %#x prints zero as 0; hex()/Python #x replay receipts spell it 0x0.
    require(isinstance(text, str) and re.fullmatch(r'(?:0|[1-9][0-9]*|0x(?:0|[1-9a-fA-F][0-9a-fA-F]{0,15}))', text),
            'noncanonical unsigned decimal/hex field')
    value = int(text, 16 if text.startswith('0x') else 10)
    require(0 <= value < 2**64, 'integer exceeds u64')
    return value


def uint(value, maximum=(1 << 64) - 1):
    return writeback.json_int(value, 0, maximum)


def typed_equal(a, b):
    if type(a) is not type(b):
        return False
    if type(a) is dict:
        return a.keys() == b.keys() and all(typed_equal(a[k], b[k]) for k in a)
    if type(a) is list:
        return len(a) == len(b) and all(typed_equal(x, y) for x, y in zip(a, b))
    return a == b


def read(root, name, limit=MAX_FILE):
    with writeback.open_file(root, name, limit) as stream:
        before = os.fstat(stream.fileno())
        raw = stream.read(limit + 1)
        require(len(raw) <= limit and len(raw) == before.st_size and
                writeback.identity(before) == writeback.identity(os.fstat(stream.fileno())),
                'evidence changed while reading: ' + name)
        return raw


def read_absolute(path, limit=MAX_FILE):
    path = writeback.absolute_path(path)
    return read(path.parent, path.name, limit)


def object_json(raw):
    def finite_number(text):
        value = float(text)
        require(math.isfinite(value), 'nonfinite JSON number')
        return value
    value = json.loads(raw, object_pairs_hook=writeback.unique_object, parse_float=finite_number,
                       parse_constant=lambda _: require(False, 'nonfinite JSON number'))
    require(type(value) is dict, 'JSON object required')
    return value


def json_file(root, name):
    return object_json(read(root, name, writeback.MAX_JSON))


def digest_binding(actual, expected, label):
    require(sha(actual) == writeback.hash_hex(expected, 64), label + ': SHA256 differs')


def archive(raw, expected):
    """Verify exact regular members without extracting; bounded decompression."""
    require(type(expected) is dict and expected, 'empty archive source index')
    seen, total = set(), 0
    with tarfile.open(fileobj=io.BytesIO(raw), mode='r:gz') as stream:
        for member in stream:
            name = member.name.rstrip('/')
            writeback.relative_path(name)
            require(name not in seen, 'duplicate archive member')
            seen.add(name)
            require(len(seen) <= 8192, 'archive member budget exceeded')
            if member.isdir():
                require(member.size == 0, 'archive directory contains payload')
                continue
            require(member.isfile() and name in expected and 0 <= member.size <= 16 * 1024**2,
                    'unlisted/nonregular/oversized archive member')
            total += member.size
            require(total <= MAX_FILE and len(seen) <= 8192, 'archive budget exceeded')
            with stream.extractfile(member) as item:
                content = item.read(member.size + 1)
            require(len(content) == member.size, 'archive short read')
            digest_binding(content, expected[name], 'archive member ' + name)
    require(set(expected) <= seen, 'archive source missing')
    return {'files': len(expected), 'uncompressed_bytes': total, 'sha256': sha(raw)}


def frozen_sources(inputs):
    groups = inputs.get('groups')
    needed(type(groups) is dict and set(groups) == {'production', 'host', 'observer', 'test'},
           'inputs.json: groups.production/host/observer/test')
    frozen = {}
    for group in groups.values():
        require(type(group) is dict and group, 'empty frozen source group')
        for name, digest in group.items():
            path = writeback.absolute_path(name)
            require(path.is_relative_to(NATIVE) and path != NATIVE, 'source outside public native package')
            digest = writeback.hash_hex(digest, 64)
            require(name not in frozen or frozen[name] == digest, 'conflicting frozen source groups')
            frozen[name] = digest
            digest_binding(read_absolute(path, 16 * 1024**2), digest, 'current source ' + name)
    required = (Path(__file__), Path(__file__).with_name('test_evidence.py'),
                NATIVE / 'report/native-card-write/check_writeback.py',
                NATIVE / 'report/capture-evidence/check_evidence.py')
    needed(all(str(path) in frozen for path in required),
           'inputs.json: freeze functional-camera-evidence checker/tests and both reused readers before regression')
    return groups, frozen


FULL_BLOCKS = (
    (0x2000, 0x008, 0x0c), (0x2001, 0x014, 0x0c), (0x2002, 0x020, 0x0c), (0x2003, 0x02c, 0x34),
    (0x2004, 0x060, 0x84), (0x2005, 0x0e4, 0x0c), (0x2006, 0x0f0, 0x0c), (0x2008, 0x0fc, 0x10),
    (0x2009, 0x10c, 0x0c), (0x200d, 0x118, 0x0c), (0x200e, 0x124, 0x28), (0x2012, 0x14c, 0x0c),
    (0x2013, 0x158, 0x20), (0x2014, 0x178, 0x10), (0x2016, 0x188, 0x0c), (0x2017, 0x194, 0x0c),
    (0x2018, 0x1a0, 0x0c), (0x2019, 0x1ac, 0x0c), (0x201a, 0x1b8, 0x0c), (0x201b, 0x1c4, 0x14),
    (0x201d, 0x1d8, 0x10), (0x201e, 0x1e8, 0x30), (0x2020, 0x218, 0x0c), (0x2022, 0x224, 0x0c),
    (0x202d, 0x230, 0x10), (0x202f, 0x240, 0x18), (0x2030, 0x258, 0x0c), (0x2031, 0x264, 0x0c),
    (0x2032, 0x270, 0x0c), (0x2036, 0x27c, 0x0c), (0x2041, 0x288, 0x14), (0x2043, 0x29c, 0x0c),
    (0x2044, 0x2a8, 0xa0), (0x2045, 0x348, 0x0c), (0x204a, 0x354, 0x0c), (0x204c, 0x360, 0x0c),
    (0x204f, 0x36c, 0x0c), (0x2050, 0x378, 0x0c), (0x2053, 0x384, 0x14), (0x2054, 0x398, 0x0c),
    (0x2057, 0x3a4, 0x0c), (0x2058, 0x3b0, 0x0c), (0x2059, 0x3bc, 0x1c), (0x205a, 0x3d8, 0x40),
    (0x205c, 0x418, 0x0c), (0x205d, 0x424, 0x0c), (0x205e, 0x430, 0x0c), (0x2061, 0x43c, 0x0c),
    (0x2062, 0x448, 0x0c), (0x2065, 0x454, 0x0c), (0x2066, 0x460, 0x0c), (0x2067, 0x46c, 0x24),
    (0x2068, 0x490, 0x0c), (0x2069, 0x49c, 0x0c), (0x206a, 0x4a8, 0x0c), (0x206b, 0x4b4, 0x0c),
    (0x206c, 0x4c0, 0x0c), (0x206d, 0x4cc, 0x0c), (0x206e, 0x4d8, 0x0c), (0x206f, 0x4e4, 0x0c),
    (0x2070, 0x4f0, 0x0c), (0x2071, 0x4fc, 0x0c), (0x209e, 0x508, 0x0c), (0x209f, 0x514, 0x84),
    (0x20a0, 0x598, 0x9c), (0x20a1, 0x634, 0x0c), (0x20a2, 0x640, 0x0c), (0x20a4, 0x64c, 0x0c),
    (0x20a5, 0x658, 0x0c), (0x20a6, 0x664, 0x10), (0x20a8, 0x674, 0x0c), (0x20ac, 0x680, 0x10),
    (0x20ad, 0x690, 0x0c), (0x20af, 0x69c, 0x1c), (0x20b0, 0x6b8, 0x0c), (0x20b1, 0x6c4, 0x10),
)
XSYNC_FIELDS = ('xsync_defined', 'xsync_source_fps', 'xsync_word', 'xsync_half', 'xsync_source_generation')


def full_snapshot(state):
    """One immutable, validated source State128 defines all 1748 software bytes."""
    require(isinstance(state, bytes) and len(state) == 128, 'full snapshot requires actual State128')
    abi, caps, width, height, fps, quality, aperture, iso, shutter, focus = struct.unpack_from('<8I2Q', state)
    instance, generation, rendered, consumed, jpeg, video = struct.unpack_from('<6Q', state, 48)
    require(abi == 1 and caps == 15 and instance and 0 < generation <= 0xffffffff and
            0 < width <= 8192 and 0 < height <= 8192 and 0 < fps <= 120 and 0 < quality <= 100 and
            aperture in (400, 800, 1600) and iso and shutter and (focus == 2**64 - 1 or focus >= 100000) and
            0 <= jpeg <= consumed <= rendered and video <= consumed and rendered and
            state[104:112] == bytes(8) and struct.unpack_from('<Q', state, 112)[0] and state[120:] == bytes(8),
            'full snapshot invalid source State128')
    require(fps in XSYNC_POLICY['xsync_canonical_clock_rates'], 'noncanonical source FPS/one-frame AP tuple')
    raw = bytearray(1748)
    struct.pack_into('<HHI', raw, 0, 6, 0x2040, 0)
    for command, offset, size in FULL_BLOCKS:
        struct.pack_into('<HHI', raw, offset, 6, command, 0)
        if command == 0x2012:
            raw[offset:offset + size] = bytes.fromhex('060012200000000000007700')
        elif command == 0x201b:
            struct.pack_into('<H', raw, offset + 8, aperture)
        elif command == 0x20a6:
            struct.pack_into('<IH', raw, offset + 8, fps, 1)
        elif command == 0x2044:
            raw[offset + 8] = 1
            for word_offset, value in ((0x18, 10), (0x20, 10), (0x24, 0x40), (0x28, 10), (0x2c, 0x160), (0x30, 10)):
                struct.pack_into('<I', raw, offset + word_offset, value)
            name = b'Virtual functional fixed optics\x00'
            raw[offset + 0x34:offset + 0x34 + len(name)] = name
    return bytes(raw)


def check_full_snapshot(state, fields, raw=None, known=None):
    """Check a publication against its source, never the latest cached probe."""
    expected = full_snapshot(state)
    fps, generation = struct.unpack_from('<I', state, 16)[0], struct.unpack_from('<Q', state, 56)[0]
    capability = dict(zip(XSYNC_FIELDS, (1, fps, fps, 1, generation)))
    capability.update(defined_blocks=76, projected_blocks=3, zero_policy_blocks=72,
                      full_layout_copied=1, model_defined=1, publication_copied=1, published_generation=generation)
    require(all(fields.get(key) == str(value) for key, value in capability.items()),
            'full snapshot source capability/generation/block counts differ')
    if raw is not None:
        require(raw == expected, 'full snapshot complete1748/padding/source blocks differ')
    if known is not None:
        require(known == b'\x01\x00' + b'\x01' * 1746, 'full snapshot exact known mask differs')
    return expected


def check_control(run, rows, transport):
    """Join control timing records to actual INIT/STATE and full-wire FNV."""
    scoped = [row for row in rows if row['tag'].startswith('FUNCTIONAL_CAMERA_CONTROL_')]
    resource_tags = {'FUNCTIONAL_CAMERA_CONTROL_' + suffix for suffix in
                     ('RESOURCE_DEPENDENCIES', 'RESOURCES_TTS_TABLE', 'RESOURCES_RESERVED')}
    require(not any('diagnostic' in row for row in scoped if row['tag'] in resource_tags),
            'malformed control resource diagnostic')
    records = [row for row in scoped if row['tag'] not in resource_tags]
    result = dict(required=bool(records), verified=False, publications=[], capture_verified=False,
                  physical_asic_compatibility_verified=False, original_CP_executed=False)
    if not records:
        return result
    probes, publications, used = {}, {}, set()
    for row in records:
        f, tag = row['fields'], row['tag'].removeprefix('FUNCTIONAL_CAMERA_CONTROL_')
        require(tag in ('PROBE', 'SENT', 'OWNED_FREE', 'AP_FREE', 'COMMIT', 'RECEIVE') and 'diagnostic' not in row,
                'failed/unknown control timing receipt')
        require(number(f['pid']) == transport['pid'] and f.get('functional_model') == '1' and
                all(f.get(k) == '0' for k in ('original_CP', 'physical_ASIC_verified', 'capture')),
                'control timing owner/scope differs')
        if tag == 'RECEIVE':
            require(f.get('index') in ('1', '3', '4') and f.get('role') == ('3' if f['index'] == '4' else '2') and
                    f.get('result') == '1' and f.get('reason') == 'accepted' and
                    f.get('envelope_checked') == f.get('wire_checked') == '1' and
                    all(number(f[k]) == 0x80020002 for k in ('destination', 'expected_destination')) and
                    all(number(f[k]) == 0x90030001 for k in ('source', 'actual_source', 'expected_source')),
                    'control timing actual receive source/status differs')
            continue
        require(all(k in f for k in XSYNC_FIELDS), 'control timing source fields missing')
        for key in XSYNC_FIELDS:
            require(re.fullmatch(r'(?:0|[1-9][0-9]*)', f[key]) and
                    number(f[key]) < 2**(64 if key == 'xsync_source_generation' else 32),
                    'control timing source field grammar differs')
        require(f.get('faults') == '0' and f.get('bridge_rc') == f.get('probe_rc') == '0',
                'failed control timing probe')
        probe_id = number(f['probe_run_id'])
        if tag == 'PROBE':
            require(probe_id == len(probes) + 1, 'control timing probe sequence differs')
            op = 1 if number(f['init_run_id']) == probe_id else 2
            origin = {key: number(f['native_' + field]) for key, field in
                      (('source', 'source'), ('destination', 'destination'), ('command', 'command'), ('bytes', 'bytes'))}
            origin['fnv1a64'] = int(writeback.hash_hex(f['native_fnv1a'], 16), 16)
            require(origin['source'] == 0x80020002 and origin['destination'] == 0x90030001 and
                    ((op == 1 and origin['command'] in (0x3003, 0x3000) and origin['bytes'] == 24) or
                     (op == 2 and origin['command'] == 0x4073 and origin['bytes'] == 12)),
                    'control timing original command/source differs')
            candidates = [tx for tx in transport['transfers'] if tx['opcode'] == op and tx['first'] not in used and
                          tx['line'] < row['line'] and tx['origin']['producer_tid'] == number(f['tid']) and
                          all(tx['origin'][k] == v for k, v in origin.items())]
            require(len(candidates) == 1, 'control timing actual source probe missing/ambiguous')
            tx = candidates[0]
            source = transfer_output(run, tx)
            require(len(source) == 128 and struct.unpack_from('<Q', source, 48)[0] == transport['model_instance'] ==
                    number(f['model_instance']) and struct.unpack_from('<Q', source, 56)[0] == number(f['config_generation']),
                    'control timing actual source State128 differs')
            if probes:
                previous = probes[probe_id - 1]
                previous_generation = struct.unpack_from('<Q', previous, 56)[0]
                generation = struct.unpack_from('<Q', source, 56)[0]
                require(generation >= previous_generation and
                        (generation != previous_generation or source[:48] == previous[:48]),
                        'control timing same-generation source configuration changed/regressed')
            probes[probe_id] = source
            used.add(tx['first'])
        require(probe_id in probes, 'control timing source probe not joined')
        require(number(f['model_instance']) == transport['model_instance'] and
                number(f['config_generation']) == struct.unpack_from('<Q', probes[probe_id], 56)[0],
                'control timing snapshot/probe identity differs')
        publication = number(f['published_generation'])
        if not publication:
            require(all(number(f[key]) == 0 for key in XSYNC_FIELDS) and
                    all(number(f[key]) == 0 for key in ('defined_blocks', 'projected_blocks', 'zero_policy_blocks',
                        'full_layout_copied', 'model_defined', 'publication_copied')),
                    'control timing undefined capability promoted')
            continue
        if publication not in publications:
            source = probes[probe_id]
            require(struct.unpack_from('<Q', source, 56)[0] == publication and f.get('ack_only') == '0' and
                    (not publications or publication > max(publications)),
                    'control timing source publication generation differs')
            publications[publication] = (source, check_full_snapshot(source, f), number(f['cycle_id']))
        source, full, cycle = publications[publication]
        check_full_snapshot(source, f)
        if number(f['index']) == 4:
            require(number(f['bytes']) == 1748 and writeback.hash_hex(f['wire_fnv1a'], 16) == f'{fnv(full):016x}' and
                    number(f['lease_cycle_id']) == cycle, 'control full1748 FNV/source publication differs')
    require(sum(row['tag'] == 'FUNCTIONAL_CAMERA_CONTROL_RECEIVE' and row['fields'].get('index') == '4'
                for row in records) == len(publications), 'control full receive has no source publication')
    for publication, (source, full, cycle) in publications.items():
        notices = [row['fields'] for row in records if row['tag'] == 'FUNCTIONAL_CAMERA_CONTROL_RECEIVE' and
                   row['fields'].get('index') == '4' and number(row['fields']['lease_cycle']) == cycle]
        require(len(notices) == 1, 'control full publication actual receive missing/duplicate')
        f = notices[0]
        require(f.get('result') == '1' and f.get('reason') == 'accepted' and f.get('envelope_checked') ==
                f.get('wire_checked') == '1' and all(number(f[k]) == 1748 for k in ('bytes', 'actual_bytes', 'expected_bytes')) and
                all(writeback.hash_hex(f[k], 16) == f'{fnv(full):016x}' for k in ('wire_fnv1a', 'expected_fnv1a')),
                'control full1748 actual receive/FNV differs')
        result['publications'].append(dict(source_generation=publication, source_fps=struct.unpack_from('<I', source, 16)[0],
            source_State128_sha256=sha(source), full_sha256=sha(full), full_fnv1a64=f'{fnv(full):016x}',
            projected_blocks=3, zero_policy_blocks=72))
    result['verified'] = True
    return result


def check_background_start(run, manifest, rows, transport=None):
    """A software initialization receipt needs both actual probes and original AP free."""
    prefix = 'FUNCTIONAL_BACKGROUND_START_'
    records = [r for r in rows if r['tag'].startswith(prefix)]
    result = dict(required=bool(records), verified=False, pending=bool(records), cycles=[],
                  content_join_verified=False, causal_trace_verified=False,
                  native_completion_verified=False, missing_native_observations=[],
                  functional_core_initialized=False, AP_consumed=False, hardware_ready=False,
                  image_ready=False, capture_verified=False, business_published=False,
                  physical_asic_compatibility_verified=False, original_CP_executed=False,
                  CP_modules_verified=False, original_masks_verified=False, original_CP_RTOS_verified=False)
    if not records:
        return result
    backup = manifest.get('backup_transport', {})
    require(all(typed_equal(manifest.get('functional_camera_' + k), v) and
                typed_equal(backup.get('functional_camera_' + k), v) for k, v in BACKGROUND_POLICY.items()),
            'background start lacks exact typed functional policy')
    modern = any('snapshot_id' in r['fields'] or r['tag'] in
                 (prefix + 'INIT_BEGIN', prefix + 'STATE_BEGIN') for r in records)
    main_keys = set(('pid tid cycle phase bound source requests pending working guard faults error reserve_rc '
        'predecessor_rc sender_tid producer_tid receiver_tid model_complete functional_core_initialized '
        'state_copied readback request_freed reply_queued reply_received reply_retained live transport_complete '
        'AP_consumed destination command bytes wire_fnv raw24 reply12 source_physical_verified '
        'CP_modules_verified original_masks_verified original_CP_RTOS_verified business_published hardware_ready '
        'image_ready capture_verified').split())
    lease_keys = set(('pid cycle lease pointer source destination bytes fnv queued received freed consumed '
        'inflight releasing faults sender_tid receiver_tid free_tid allocate_rc send_rc free_rc '
        'allocation_returned allocation_alias').split())
    probe_keys = set(('pid cycle stage calls bridge_rc validation_rc used required instance result_token '
        'full_state_fnv cache_fnv readback_fnv config_generation frame_generation rendered consumed '
        'jpeg_encoded video_encoded result_bytes_read actual_state128').split())
    binding_keys = set(('pid tid caller_pc caller_va library_base source reads first second bind_rc '
                        'original_cp_modules_verified capture_verified').split())
    false_keys = ('source_physical_verified CP_modules_verified original_masks_verified original_CP_RTOS_verified '
                  'business_published hardware_ready image_ready capture_verified').split()
    flags = ('bound pending working guard faults model_complete functional_core_initialized state_copied readback '
             'request_freed reply_queued reply_received reply_retained transport_complete AP_consumed').split()
    events = {'ACCEPT', 'PROGRESS', 'REQUEST_FREE', 'ALLOCATE', 'SEND', 'RECEIVE', 'AP_FREE', 'FAULT'}
    if modern:
        main_keys.update(('snapshot_id', 'init_calls', 'state_calls', 'receive_ticket', 'free_ticket'))
        lease_keys.add('snapshot_id')
        probe_keys.update(('snapshot_id', 'cached_state128', 'readback_state128'))
        events.update(('INIT_BEGIN', 'STATE_BEGIN'))
    snapshots = {}
    if modern:
        for row in records:
            name, f = row['tag'][len(prefix):], row['fields']
            if name not in events | {'INIT', 'STATE', 'READBACK', 'LEASE'}:
                continue
            require('snapshot_id' in f and re.fullmatch(r'[1-9][0-9]*', f['snapshot_id']),
                    'background snapshot ID missing/noncanonical')
            snapshot_id = number(f['snapshot_id'])
            bucket = snapshots.setdefault(snapshot_id, [])
            require(not bucket or all(f[k] == bucket[0]['fields'][k] for k in ('pid', 'cycle')),
                    'background snapshot mixed owner/cycle')
            bucket.append(row)
        require(sorted(snapshots) == list(range(1, len(snapshots) + 1)), 'background snapshot ID gap/replay')
        for bucket in snapshots.values():
            owners = [r for r in bucket if r['tag'] != prefix + 'LEASE']
            require(len(owners) == 1, 'background duplicate/missing snapshot owner')
            roles = [r['fields'].get('lease') for r in bucket if r['tag'] == prefix + 'LEASE']
            require(sorted(roles) == (['0', '1'] if owners[0]['tag'][len(prefix):] in events else []),
                    'background snapshot missing/duplicate/foreign lease')
        records = [r for r in records if r['tag'] != prefix + 'LEASE']
    def ptr(text):
        require(text == '(nil)' or re.fullmatch(r'0x[1-9a-f][0-9a-f]{0,15}', text),
                'background pointer grammar differs')
        return 0 if text == '(nil)' else number(text)
    def integer(text):
        require(re.fullmatch(r'(?:0|-?[1-9][0-9]*)', text), 'background signed integer grammar differs')
        value = int(text)
        require(-4095 <= value < 2**31, 'background signed integer outside range')
        return value
    bindings, cycles, pid = [], {}, None
    index = 0
    while index < len(records):
        row = records[index]
        name, f = row['tag'][len(prefix):], row['fields']
        require('diagnostic' not in row, 'malformed background receipt')
        if name in ('RESOURCE_DEPENDENCIES', 'RESOURCES_TTS_TABLE', 'RESOURCES_RESERVED'):
            equivalent = dict(row, tag='FUNCTIONAL_VDF_PATH_' + name)
            require(vdf_resource_diagnostic(equivalent), 'background guard diagnostic differs')
            index += 1
            continue
        if name == 'SOURCE_BOUND':
            require(set(f) == binding_keys and f['reads'] == '4/4' and f['bind_rc'] == '0' and
                    f['original_cp_modules_verified'] == f['capture_verified'] == '0' and
                    number(f['caller_va']) == 0xeda50 and number(f['library_base']) > 0 and
                    number(f['caller_pc']) == number(f['library_base']) + 0xeda50 and
                    number(f['first']) == number(f['second']) == 0x97fdb339 and
                    number(f['source']) < 2**32 and number(f['source']) >> 16 == 0x8102,
                    'background original libObj/dynamic source binding differs')
            bindings.append(row)
        else:
            require(name in events | {'INIT', 'STATE', 'READBACK'}, 'failed/unknown background receipt: ' + name)
            require(set(f) == (main_keys if name in events else probe_keys), 'background typed fields differ: ' + name)
            cycle = number(f['cycle'])
            require(0 < cycle <= 0xffffffff, 'background cycle outside counter domain')
            group = cycles.setdefault(cycle, dict(main=[], probes={}))
            if name in events:
                require(all(f[k] in ('0', '1') for k in flags) and all(f[k] == '0' for k in false_keys),
                        'background functional/physical scope or flag differs')
                require(all(integer(f[k]) == 0 for k in ('error', 'reserve_rc')) and f['faults'] == '0' and name != 'FAULT',
                        'background owner fault/failed reservation')
                require(integer(f['predecessor_rc']) in (0, 1, -61), 'background predecessor failed')
                require(number(f['requests']) == cycle and number(f['live']) <= 2 and number(f['phase']) <= 6 and
                        0 < number(f['sender_tid']) < 2**31 and 0 < number(f['tid']) < 2**31 and
                        all(number(f[k]) < 2**31 for k in ('producer_tid', 'receiver_tid')),
                        'background request counter/phase/thread differs')
                raw, reply = raw_hex(f, 'raw24', 24), raw_hex(f, 'reply12', 12)
                require(raw[0] == 0 and raw[2:4] == bytes.fromhex('0630') and
                        reply == bytes.fromhex('01000630') + raw[4:8] + bytes.fromhex('00f00000') and
                        number(f['destination']) == 0x90030001 and number(f['command']) == 0x3006 and
                        number(f['bytes']) == 24 and writeback.hash_hex(f['wire_fnv'], 16) == f'{fnv(raw):016x}',
                        'background original raw24/independent reply12/opaque/FNV differs')
                if modern:
                    lease_rows = sorted((r for r in snapshots[number(f['snapshot_id'])] if r['tag'] == prefix + 'LEASE'),
                                        key=lambda r: r['fields']['lease'])
                else:
                    require(index + 2 < len(records), 'background incomplete main/lease snapshot')
                    lease_rows = records[index + 1:index + 3]
                leases = []
                for role, lease_row in enumerate(lease_rows):
                    l = lease_row['fields']
                    require(lease_row['tag'] == prefix + 'LEASE' and 'diagnostic' not in lease_row and
                            set(l) == lease_keys and l['pid'] == f['pid'] and l['cycle'] == f['cycle'] and
                            number(l['lease']) == role, 'background missing/interleaved/foreign lease snapshot')
                    require(all(l[k] in ('0', '1') for k in ('queued', 'received', 'freed', 'consumed', 'inflight',
                            'releasing', 'faults', 'allocation_alias')) and l['faults'] == l['allocation_alias'] == '0',
                            'background lease fault/alias/boolean differs')
                    require(number(l['source']) == (number(f['source']) if role == 0 else 0x90030001) and
                            number(l['destination']) == (0x90030001 if role == 0 else number(f['source'])) and
                            number(l['bytes']) == (24 if role == 0 else 12) and l['fnv'] == f'{fnv(raw if role == 0 else reply):016x}' and
                            l['sender_tid'] == f['sender_tid'], 'background lease original wire/queue/sender differs')
                    for key in ('allocate_rc', 'send_rc', 'free_rc'):
                        require(integer(l[key]) in (0, -61), 'background actual transport failed')
                    for key in ('pointer', 'allocation_returned'):
                        ptr(l[key])
                    for key in ('receiver_tid', 'free_tid'):
                        require(number(l[key]) < 2**31, 'background lease thread outside domain')
                    leases.append(l)
                group['main'].append((row, leases))
                if not modern:
                    index += 2
            else:
                require(name not in group['probes'] and f['stage'] == name and
                        all(f[k] == '0' for k in ('bridge_rc', 'validation_rc', 'result_token')) and
                        number(f['used']) == number(f['required']) == 128 and number(f['calls']) == cycle,
                        'background duplicate/failed probe or result dimensions differ')
                raw_hex(f, 'actual_state128', 128)
                if modern:
                    raw_hex(f, 'cached_state128', 128)
                    raw_hex(f, 'readback_state128', 128)
                for key in ('full_state_fnv', 'cache_fnv', 'readback_fnv'):
                    writeback.hash_hex(f[key], 16)
                group['probes'][name] = row
        if 'pid' in f:
            owner = number(f['pid'])
            require(1 < owner < 2**31 and (pid is None or owner == pid), 'background mixed owner PID')
            pid = owner
        index += 1
    require(transport is None or pid == transport['pid'], 'background owner differs from mailbox')
    require(sorted(cycles) == list(range(1, len(cycles) + 1)), 'background missing/old cycle')
    used, previous_end, previous_snapshot = set(), 0, 0
    for cycle, group in sorted(cycles.items()):
        mains, probes = group['main'], group['probes']
        if modern:
            mains.sort(key=lambda item: number(item[0]['fields']['snapshot_id']))
            cycle_ids = [sid for sid, bucket in snapshots.items() if number(bucket[0]['fields']['cycle']) == cycle]
            require(min(cycle_ids) > previous_snapshot, 'background snapshots cross cycles')
            previous_snapshot = max(cycle_ids)
        require(mains and mains[0][0]['tag'] == prefix + 'ACCEPT' and
                sum(r['tag'] == prefix + 'ACCEPT' for r, _ in mains) == 1, 'background original ACCEPT missing/duplicate')
        start, first_leases = mains[0]
        f = start['fields']
        if modern:
            require(number(f['snapshot_id']) == min(cycle_ids), 'background snapshot before original ACCEPT')
        require(start['line'] > previous_end and f['pending'] == f['bound'] == '1' and
                all(f[k] == '0' for k in ('working', 'guard', 'model_complete', 'readback', 'request_freed',
                    'reply_queued', 'reply_received', 'reply_retained', 'transport_complete', 'AP_consumed')) and
                f['live'] == f['phase'] == '1' and f['tid'] == f['sender_tid'] and f['producer_tid'] == '0',
                'background ACCEPT fabricated initialization/ACK or reused cycle')
        bound = [r for r in bindings if previous_end < r['line'] < start['line'] and
                 r['fields']['source'] == f['source'] and r['fields']['tid'] == f['sender_tid']]
        require(len(bound) == 1, 'background original current source binding missing/ambiguous')
        stable = ('pid', 'cycle', 'source', 'sender_tid', 'requests', 'destination', 'command', 'bytes', 'wire_fnv', 'raw24', 'reply12')
        original = ptr(first_leases[0]['pointer'])
        require(original and not ptr(first_leases[1]['pointer']), 'background original lease not retained')
        at, at_lines, allocation, producer, last_flags = {}, {}, 0, None, dict.fromkeys(
            ('model_complete', 'functional_core_initialized', 'state_copied', 'readback', 'request_freed',
             'reply_queued', 'reply_received', 'transport_complete', 'AP_consumed'), 0)
        for row, leases in mains:
            x, name = row['fields'], row['tag'][len(prefix):]
            require(all(x[k] == f[k] for k in stable), 'background snapshot original identity differs')
            position = number(x['snapshot_id']) if modern else row['line']
            if name != 'PROGRESS':
                require(name not in at, 'background duplicate actual lifecycle event')
                at[name], at_lines[name] = position, row['line']
            if modern:
                expected_init = cycle if 'INIT_BEGIN' in at else cycle - 1
                expected_state = cycle if 'STATE_BEGIN' in at else cycle - 1
                require(all(re.fullmatch(r'(?:0|[1-9][0-9]*)', x[k]) for k in
                            ('init_calls', 'state_calls', 'receive_ticket', 'free_ticket')) and
                        number(x['init_calls']) == expected_init and number(x['state_calls']) == expected_state,
                        'background actual probe call counters/order differ')
            if number(x['producer_tid']):
                require(producer in (None, number(x['producer_tid'])), 'background producer changed')
                producer = number(x['producer_tid'])
            for key in last_flags:
                value = number(x[key])
                require(value >= last_flags[key], 'background lifecycle flag regressed')
                last_flags[key] = value
            a, b = leases
            freed, received, queued = (number(b[k]) for k in ('freed', 'received', 'queued'))
            require(a['queued'] == a['received'] == a['consumed'] == a['inflight'] == a['releasing'] == '0' and
                    a['allocate_rc'] == '0' and a['send_rc'] == '-61' and
                    number(a['freed']) == number(x['request_freed']) and
                    ptr(a['pointer']) == (0 if number(a['freed']) else original) and
                    a['free_rc'] == ('0' if number(a['freed']) else '-61'), 'background actual original request-free differs')
            if number(a['freed']):
                require(producer and number(a['receiver_tid']) == number(a['free_tid']) == producer,
                        'background original request freed by wrong producer')
            else:
                require(a['receiver_tid'] == a['free_tid'] == '0', 'background original request prematurely released')
            returned = ptr(b['allocation_returned'])
            require(a['allocation_returned'] == b['allocation_returned'] and
                    (not returned or at.get('REQUEST_FREE', position + 1) < position),
                    'background reply allocated before actual original free')
            if returned:
                require(allocation in (0, returned), 'background response allocation changed')
                allocation = returned
            require(ptr(b['pointer']) == (0 if freed else returned) and number(x['reply_retained']) == bool(ptr(b['pointer'])) and
                    number(x['live']) == bool(ptr(a['pointer'])) + bool(ptr(b['pointer'])) and
                    number(x['reply_queued']) == queued and number(x['reply_received']) == received and
                    b['allocate_rc'] == ('0' if returned else '-61') and b['send_rc'] == ('0' if queued else '-61') and
                    b['free_rc'] == ('0' if freed else '-61') and (not freed or received) and
                    (not received or queued or b['inflight'] == '1'), 'background response lease/actual transport state differs')
            require(number(b['receiver_tid']) == (number(f['sender_tid']) if received else 0) and
                    number(b['free_tid']) == (number(f['sender_tid']) if freed else 0) and
                    number(x['receiver_tid']) == number(b['receiver_tid']), 'background actual receive/free not original sender')
            if modern:
                require(number(x['receive_ticket']) == (cycle if received else 0) and
                        number(x['free_ticket']) == (cycle if freed else 0),
                        'background actual receive/free ticket missing/stale')
            consumed = bool(queued and received and freed and b['inflight'] == b['releasing'] == '0')
            complete = bool(consumed and x['model_complete'] == x['readback'] == x['request_freed'] == '1' and
                            x['working'] == x['guard'] == '0')
            require(number(b['consumed']) == consumed and number(x['AP_consumed']) == number(x['transport_complete']) == complete and
                    number(x['pending']) == (not complete), 'background ACK/ready without actual AP consumption')
            phase = 6 if complete else 5 if received else 4 if queued else 3 if x['model_complete'] == '1' else 2 if x['working'] == '1' else 1
            require(number(x['phase']) == phase and (x['guard'] == '0' or x['working'] == '1') and
                    ('READBACK' in probes or not returned) and (not freed or 'RECEIVE' in at),
                    'background phase/guard/actual receive lifecycle differs')
            require(number(x['model_complete']) == number(x['functional_core_initialized']) ==
                    number(x['state_copied']) == number(x['readback']), 'background model/cache completion differs')
            if name in ('INIT_BEGIN', 'STATE_BEGIN', 'REQUEST_FREE', 'ALLOCATE', 'SEND'):
                require(number(x['tid']) == producer and x['working'] == x['guard'] == '1' and
                        x['predecessor_rc'] == '1' and
                        x['model_complete'] == ('0' if name.endswith('_BEGIN') else '1'),
                        'background model IO before accepted predecessor/guard')
            if name in ('INIT_BEGIN', 'STATE_BEGIN'):
                require(not number(x['request_freed']) and not returned and not received and not queued and
                        x['state_copied'] == x['readback'] == '0', 'background BEGIN after release/cache/response')
            if name == 'REQUEST_FREE':
                require(a['freed'] == '1' and not returned and not ptr(b['pointer']), 'background request-free event missing actual free0')
            if name == 'ALLOCATE':
                require(returned and ptr(b['pointer']) == returned and not queued and not received and not freed,
                        'background independent allocation missing')
            if name == 'SEND':
                require(queued and b['inflight'] == '0', 'background actual send0 missing')
            if name in ('RECEIVE', 'AP_FREE'):
                require(number(x['tid']) == number(f['sender_tid']) and received and
                        (freed if name == 'AP_FREE' else not freed and ptr(b['pointer']) == allocation),
                        'background missing actual receive/free event')
            if x['model_complete'] == '1':
                require('READBACK' in probes and (number(probes['READBACK']['fields']['snapshot_id']) < position
                        if modern else probes['READBACK']['line'] < row['line']),
                        'background ACK/free precedes both probes and actual readback')
        done = last_flags['AP_consumed'] == 1
        if done:
            require(transport is not None and transport.get('safe_cleanup') is True and
                    all(k in at for k in ('REQUEST_FREE', 'ALLOCATE', 'SEND', 'RECEIVE', 'AP_FREE')) and
                    set(probes) == {'INIT', 'STATE', 'READBACK'}, 'background completed claim lacks real transport/cleanup/events')
            final = mains[-1][0]['fields']
            require(final['phase'] == '6' and all(final[k] == '0' for k in ('working', 'guard', 'faults', 'live',
                    'pending', 'reply_retained')) and final['reply_queued'] == final['reply_received'] == '1',
                    'background final owner/lease/guard not retired')
        joined, outputs = [], []
        for name, op in (('INIT', 1), ('STATE', 2)):
            if name not in probes:
                continue
            needed(transport is not None, 'background pending: actual Core transport unavailable')
            row, p = probes[name], probes[name]['fields']
            candidates = [tx for tx in transport['transfers'] if tx['opcode'] == op and tx['first'] not in used and
                start['line'] < tx['line'] < row['line'] and tx['origin'] == dict(producer_tid=producer,
                source=number(f['source']), destination=0x90030001, command=0x3006, bytes=24,
                fnv1a64=int(f['wire_fnv'], 16))]
            require(len(candidates) == 1, 'background actual original Core probe missing/ambiguous')
            tx = candidates[0]
            if modern:
                begin = name + '_BEGIN'
                require(begin in at and at_lines[begin] < tx['line'] and
                        at[begin] < number(p['snapshot_id']), 'background pre-RPC BEGIN missing/late')
            source = transfer_output(run, tx)
            require(tx['model_instance'] == transport['model_instance'] and
                    payload_read(run, tx['request_payload']) == b'' and tx['first'] == tx['last'] and tx['token'] == 0 and
                    source == raw_hex(p, 'actual_state128', 128) and p['full_state_fnv'] == f'{fnv(source):016x}' and
                    number(p['instance']) == transport['model_instance'] == struct.unpack_from('<Q', source, 48)[0],
                    'background full actual Core State128/nonce/sequence/FNV differs')
            abi, caps, width, height, fps, quality, aperture, iso, shutter, focus = struct.unpack_from('<8I2Q', source)
            config, rendered, consumed, jpeg, video, read_bytes = struct.unpack_from('<6Q', source, 56)
            frame = struct.unpack_from('<Q', source, 112)[0]
            require(abi == 1 and caps == 15 and config and rendered and frame and 0 < width <= 8192 and
                    0 < height <= 8192 and 0 < fps <= 120 and 0 < quality <= 100 and aperture in (400, 800, 1600) and
                    iso and shutter and (focus == 2**64 - 1 or focus >= 100000) and jpeg + video <= consumed <= rendered and
                    source[104:112] == bytes(8) and source[120:] == bytes(8), 'background invalid actual State128')
            require(p['cache_fnv'] == p['readback_fnv'] == '0000000000000000' and all(p[k] == '0' for k in
                    ('config_generation', 'frame_generation', 'rendered', 'consumed', 'jpeg_encoded', 'video_encoded', 'result_bytes_read')) and
                    (not modern or raw_hex(p, 'cached_state128', 128) == raw_hex(p, 'readback_state128', 128) == bytes(128)),
                    'background probe prematurely claimed cached state')
            joined.append(tx)
            outputs.append(source)
            used.add(tx['first'])
        if outputs:
            require(len(outputs) == 1 or outputs[0] == outputs[1] and joined[1]['first'] == joined[0]['last'] + 1,
                    'background INIT/STATE full content/transaction order differs')
            reservations = [r for r in records if r['tag'] == prefix + 'RESOURCES_RESERVED' and
                            start['line'] < r['line'] < (at_lines.get('INIT_BEGIN', 0) if modern else joined[0]['line']) and
                            number(r['fields']['tid']) == producer]
            require(len(reservations) == 1, 'background actual guard29 accepted reservation missing/late')
            reserve = reservations[0]
            dependencies = [r for r in records if r['tag'] == prefix + 'RESOURCE_DEPENDENCIES' and
                            start['line'] < r['line'] < reserve['line'] and r['fields']['pid'] == f['pid'] and
                            number(r['fields']['tid']) == producer]
            tables = [r for r in records if r['tag'] == prefix + 'RESOURCES_TTS_TABLE' and
                      start['line'] < r['line'] < reserve['line'] and r['fields']['pid'] == f['pid'] and
                      number(r['fields']['tid']) == producer]
            require(len(dependencies) == len(tables) == 1 and dependencies[0]['line'] < tables[0]['line'],
                    'background actual guard dependencies/readback missing')
            frees = []
            for tag in BACKGROUND_FREE_TAGS:
                found = [r for r in rows if r['tag'] == tag and r['line'] < dependencies[0]['line']]
                require(len(found) == 1, 'background actual all13 original AP free missing/ambiguous: ' + tag)
                x = found[0]['fields']
                require('diagnostic' not in found[0] and x.get('pid') == f['pid'] and x.get('bytes') == '56' and
                        x.get('rc') == x.get('faults') == x.get('capture_verified') == '0' and x.get('ap_consumed') == '1' and
                        0 < number(x['tid']) < 2**31 and number(x['destination']) == number(x['expected']) and
                        number(x['destination']) >> 28 == 8 and number(x['destination']) & 0x0fffffff and
                        ptr(x.get('reply', x.get('pointer', '(nil)'))) and
                        ('sender' not in x or x['sender'] == x['tid'] and x.get('waiter') == '1') and
                        ('command' not in x or number(x['command']) == 0x8001), 'background actual all13 AP free0 identity differs')
                free_keys = set('pid tid destination expected bytes rc faults ap_consumed capture_verified'.split())
                free_keys.add('reply' if tag.endswith('_NATIVE_REPLY_FREE') else 'pointer')
                if tag.endswith('_NATIVE_REPLY_FREE') or tag in ('FULL_VEF_PINMEM_CONTROL_CONNECT_REPLY_FREE',
                                                               'FULL_ADF_HDMI_AUDIO_CONNECT_REPLY_FREE'):
                    free_keys.update(('sender', 'waiter'))
                if tag.endswith('_NATIVE_REPLY_FREE'):
                    free_keys.add('command')
                else:
                    if tag != 'FULL_ADF_HDMI_AUDIO_CONNECT_REPLY_FREE':
                        free_keys.add('frames_verified')
                    if tag == 'FULL_IMAGING_ADF_CONNECT_REPLY_FREE':
                        free_keys.add('pcm_verified')
                if tag == 'FULL_PINMEM_HDMI_VIDEO_CONNECT_NATIVE_REPLY_FREE':
                    free_keys.add('producer_tid')
                require(set(x) == free_keys and all(x[k] == '0' for k in ('frames_verified', 'pcm_verified') if k in x),
                        'background actual all13 free typed fields differ')
                frees.append(found[0]['line'])
            all13 = [r for r in rows if r['tag'] in ('NATIVE_CP302C_DIAGNOSTIC_ALL13_READBACK',
                    'NATIVE_CP302C_NOCONVERT_ALL13_READBACK') and max(frees) < r['line'] < reserve['line'] and
                    r['fields'].get('pid') == f['pid'] and number(r['fields']['tid']) == producer]
            require(all13 and all(all(r['fields'].get(k) == '1' for k in ('accepted', 'video_AP_consumed',
                'OSD_AP_consumed', 'audio_AP_consumed')) and r['fields'].get('OSD_live') == '16' and
                r['fields'].get('OSD_owners_each') == r['fields'].get('OSD_opens_each') == '2' and
                r['fields'].get('global_DMM_idle_claimed') == r['fields'].get('capture_verified') == '0' for r in all13),
                'background same-run last13 readback missing/before actual AP frees')
        if 'READBACK' in probes:
            p, row = probes['READBACK']['fields'], probes['READBACK']
            require(len(outputs) == 2 and joined[0]['line'] < probes['INIT']['line'] < joined[1]['line'] <
                    probes['STATE']['line'] < row['line'] < at_lines.get('REQUEST_FREE', row['line'] + 1),
                    'background actual probe/readback/request-free order differs')
            raw = outputs[1]
            require(raw_hex(p, 'actual_state128', 128) == raw and all(p[k] == f'{fnv(raw):016x}' for k in
                    ('full_state_fnv', 'cache_fnv', 'readback_fnv')) and number(p['instance']) == transport['model_instance'] and
                    all(number(p[k]) == struct.unpack_from('<Q', raw, offset)[0] for k, offset in
                        (('config_generation', 56), ('frame_generation', 112), ('rendered', 64), ('consumed', 72),
                         ('jpeg_encoded', 80), ('video_encoded', 88), ('result_bytes_read', 96))),
                    'background complete copied cache/readback differs from actual Core State128')
            if modern:
                require(number(probes['INIT']['fields']['snapshot_id']) < at.get('STATE_BEGIN', 0) <
                        number(probes['STATE']['fields']['snapshot_id']) < number(p['snapshot_id']) and
                        probes['INIT']['line'] < at_lines['STATE_BEGIN'] < joined[1]['line'] and
                        raw_hex(p, 'cached_state128', 128) == raw_hex(p, 'readback_state128', 128) == raw,
                        'background independent complete cache/readback or probe order differs')
            # Uses the existing complete proof/history validator; later media remains a separate gate.
            check_frames(run, transport, require_media=False)
        if done:
            require(at['REQUEST_FREE'] < at['ALLOCATE'] < min(at['SEND'], at['RECEIVE']) and
                    at['RECEIVE'] < at['AP_FREE'], 'background actual response lifecycle order differs')
        native = done and modern and manifest.get('evidence_class') != 'HOST_TEST'
        result['cycles'].append(dict(cycle=cycle, verified=native, native_completion_verified=native,
            content_join_verified=done, causal_trace_verified=done and modern, pending=not native, source=number(f['source']),
            sender_tid=number(f['sender_tid']), producer_tid=producer, original_request_fnv1a64=f['wire_fnv'],
            actual_State128_sha256=sha(outputs[0]) if len(outputs) == 2 else None,
            INIT_sequence=joined[0]['first'] if joined else None, STATE_sequence=joined[1]['first'] if len(joined) == 2 else None,
            native_response_AP_free=native,
            response_free_recorded=done, functional_core_initialized='READBACK' in probes))
        previous_end = start['line']
        require(done or cycle == len(cycles), 'background next cycle while original request pending')
    require(len(bindings) == len(cycles) or not cycles and len(bindings) == 1, 'background unmatched source binding')
    result['content_join_verified'] = bool(cycles) and all(c['content_join_verified'] for c in result['cycles'])
    if result['content_join_verified'] and not modern:
        result['missing_native_observations'] = ['pre-RPC BEGIN after actual guard29',
            'unique main/lease snapshot identity', 'immutable receive/free ticket',
            'independent complete cache128/readback128 bytes']
    if manifest.get('evidence_class') == 'HOST_TEST':
        result['missing_native_observations'].append('HOST_TEST support does not prove native AP/SDK/all13 execution')
    result['causal_trace_verified'] = bool(cycles) and all(c['causal_trace_verified'] for c in result['cycles'])
    result['native_completion_verified'] = bool(cycles) and all(c['native_completion_verified'] for c in result['cycles'])
    result['verified'] = result['native_completion_verified']
    result['pending'] = not result['verified']
    result['functional_core_initialized'] = bool(cycles) and all(c['functional_core_initialized'] for c in result['cycles'])
    result['AP_consumed'] = result['verified']
    return result


def check_profile(manifest):
    expected = {
        'profile': PROFILE, 'abi_version': 1,
        'hardware_policy': 'explicit-software-model-not-Sony-physical-ASIC',
        'image_bus': 'virtual-RGB888-top-row-first',
        'transport': 'owned-pagemap-16-page-mailbox-private-Unix-GDB-v1',
        'backend_initialization': 'actual-original-request-INIT-before-start-reply',
        'control_predecessor': 'virtual-cp-owned-state-v1',
        'still_max_geometry': [8192, 8192], 'video_max_geometry': [1920, 1080],
        'video_codec': 'H264', 'first_video_acceptance_audio': 'original-AudioRecording-Off',
        'media_output_policy': 'original-MPR-Fsys-only-no-host-media-file',
        'strict_profile_policy': 'separate-and-unchanged',
        'capture_requires': ['original-AP-request', 'actual-virtual-CMOS-frame',
                             'actual-encoder-consumption', 'original-MPR-Fsys-write',
                             'virtual-SD-readback', 'independent-decode'],
    }
    expected.update({key: False for key in (
        'physical_ASIC_compatibility_verified', 'original_CP_executed', 'original_CP_RAM_verified',
        'backend_readiness_verified', 'original_AP_consumption_verified', 'frame_consumption_verified',
        'original_MPR_Fsys_write_verified', 'standalone_host_media_write', 'capture_verified',
        'original_BB_C_configuration_work_verified', 'original_BB_C_configuration_units_verified',
        'original_Histogram_bin_semantics_verified', 'original_Histogram_physical_callback_verified',
        'histogram_UI_applied_verified', 'original_Xsync_state_producer_verified',
        'physical_Xsync_capability_verified')})
    backup = manifest.get('backup_transport')
    needed(type(backup) is dict, 'runtime-manifest.json: backup_transport')
    if any(value is not None for target in (manifest, backup) for key, value in target.items()
           if key.startswith('functional_camera_bb_timecode_control_')):
        check_bb_timecode_policy(manifest)
    check_bb_timecode_presets_policy(manifest)
    crank_keys = {'functional_camera_' + key for key in CP_CRANK_CONTROL_POLICY}
    require(all(not key.startswith('functional_camera_cp_crank_control_') or key in crank_keys
                for target in (manifest, backup) for key in target),
            'typed functional profile drift: undeclared crank control policy field')
    movie_keys = {'functional_camera_' + key for key in CP_MOVIE_FORMAT_POLICY}
    require(all(not key.startswith('functional_camera_cp_movie_format_') or key in movie_keys
                for target in (manifest, backup) for key in target),
            'typed functional profile drift: undeclared movie format policy field')
    ou_keys = {'functional_camera_' + key for key in CP_OU_CRANK_CONTROL_POLICY}
    require(all(not key.startswith('functional_camera_cp_ou_crank_control_') or key in ou_keys
                for target in (manifest, backup) for key in target),
            'typed functional profile drift: undeclared OU crank control policy field')
    for policy in (VDF_POLICY, ZEBRA_POLICY, LAYOUT_POLICY, BIT_WIDTH_POLICY, STILL_FORMAT_POLICY,
                   STARTUP_CONTROL_POLICY, BB_POLICY, HIST_POLICY, XSYNC_POLICY, BACKGROUND_POLICY,
                   CP_PARAMETER_BANK_POLICY, CP_CRANK_CONTROL_POLICY, CP_MOVIE_FORMAT_POLICY, CP_OU_CRANK_CONTROL_POLICY):
        if any('functional_camera_' + key in manifest or 'functional_camera_' + key in backup for key in policy):
            expected.update(policy)
    if any('functional_camera_' + key in manifest or 'functional_camera_' + key in backup for key in DISPLAY_POLICY):
        matching = [policy for policy in (DISPLAY_POLICY, ZERO6_DISPLAY_POLICY, LEGACY_DISPLAY_POLICY) if all(
            typed_equal(manifest.get('functional_camera_' + key), value) and
            typed_equal(backup.get('functional_camera_' + key), value) for key, value in policy.items())]
        require(len(matching) == 1, 'typed functional profile drift: display policy')
        expected.update(matching[0])
    for key, value in expected.items():
        key = 'functional_camera_' + key
        require(key in manifest and key in backup and typed_equal(manifest[key], value) and
                typed_equal(backup[key], value), 'typed functional profile drift: ' + key)
    require(manifest.get('directory_sd_profile') == 'directory-vvfat-256gb-v1' and
            type(manifest.get('rm_file_image_bytes')) is int and
            manifest['rm_file_image_bytes'] == writeback.CARD_BYTES,
            'functional capture requires the explicit 256GB directory SD')
    return {'verified': True, 'profile': PROFILE, 'image_bus': expected['image_bus'],
            'physical_asic_compatibility_verified': False, 'original_CP_executed': False}


def check_readonly_scope_observer(manifest, qemu_sha256, frozen=None):
    """Bind the explicit observer assets; the launch gate owns the import audit."""
    scope, files = manifest.get('readonly_scope_observer'), manifest.get('files')
    require(qemu_sha256 == READONLY_SCOPE_QEMU_SHA256 and type(scope) is dict and
            scope.get('profile') in ('qemu-readonly-scope-v1', 'qemu-readonly-scope-v2', 'qemu-readonly-scope-v3') and
            scope.get('identity_binding') == 'unverified' and
            scope.get('qemu_sha256') == qemu_sha256 and scope.get('capture_verified') is False and
            scope.get('physical_asic_compatibility_verified') is False and type(files) is dict,
            'readonly scope requires its exact candidate/profile and unverified claims')
    version = {'qemu-readonly-scope-v1': 1, 'qemu-readonly-scope-v2': 2,
               'qemu-readonly-scope-v3': 3}[scope['profile']]
    source_root = NATIVE / ('report/2026-10-31-qemu-M-writer-observer-v3' if version == 3 else
                            'report/2026-10-30-qemu-readonly-scope-observer')
    sources = scope.get('source_sha256')
    source_names = ('scope-observer.c', 'late-sites.inc', 'build-plugin.sh')
    if version in (2, 3):
        source_names += (f'log-schema-v{version}.json', f'source-contract-v{version}.json',
            f'check_run_context_v{version}.py', 'check_run_context.py',
            f'integration/scope_trace_checks_v{version}.py', 'integration/scope_trace_checks.py')
    require(type(sources) is dict and set(sources) == set(source_names),
            'readonly scope complete versioned source set required')
    if version in (2, 3):
        require(scope.get('trace_schema') == f'readonly_scope_v{version}' and
                not {'schema_sha256', 'log_schema_sha256'} & scope.keys() and
                scope.get('trace_schema_sha256') == sources[f'log-schema-v{version}.json'] and
                scope.get('trace_schema_sha256') != '8b6e2bf3576e7e4e5566fa215d2758e088ae8867ed6b3c36ea7b90f38767e50c' and
                scope.get('source_contract_sha256') == sources[f'source-contract-v{version}.json'],
                f'readonly scope v{version} schema/source-contract binding differs')
    for name, expected in sources.items():
        expected = writeback.hash_hex(expected, 64)
        path = str(source_root / name)
        require(files.get(path) == expected and (frozen is None or frozen.get(path) == expected),
                'readonly scope source not indexed/frozen: ' + name)
        digest_binding(read_absolute(path, 16 * 1024**2), expected, 'readonly scope source ' + name)
    assets = {}
    for key, limit in (('library', MAX_FILE), ('build_receipt', writeback.MAX_JSON)):
        path = writeback.absolute_path(scope.get(key))
        expected = writeback.hash_hex(scope.get(key + '_sha256'), 64)
        require(files.get(str(path)) == expected, 'readonly scope asset not indexed: ' + key)
        assets[key] = read_absolute(path, limit)
        digest_binding(assets[key], expected, 'readonly scope actual ' + key)
    writeback.absolute_path(scope.get('log'))
    header_sha256 = writeback.hash_hex(scope.get('qemu_header_sha256'), 64)
    header = NATIVE / 'source/build/qemu-SRBXNK/qemu-11.1.2/include/plugins/qemu-plugin.h'
    digest_binding(read_absolute(header, 16 * 1024**2), header_sha256, 'readonly scope actual QEMU API header')
    receipt = object_json(assets['build_receipt'])
    require(receipt.get('schema') == scope['profile'] and type(receipt.get('plugin_api')) is int and
            receipt['plugin_api'] == 7 and receipt.get('readonly_imports_verified') is True and
            receipt.get('runtime_verified') is False and receipt.get('capture_verified') is False and
            receipt.get('physical_asic_compatibility_verified') is False and
            receipt.get('library_sha256') == scope['library_sha256'] and
            receipt.get('qemu_sha256') == qemu_sha256 and receipt.get('qemu_header_sha256') == header_sha256 and
            typed_equal(receipt.get('source_sha256'), sources),
            'readonly scope build receipt/profile/source/asset binding differs')
    if version in (2, 3):
        require(not {'schema_sha256', 'log_schema_sha256'} & receipt.keys() and
                all(typed_equal(receipt.get(name), scope.get(name)) for name in
                    ('trace_schema', 'trace_schema_sha256', 'source_contract_sha256')),
                f'readonly scope v{version} receipt schema binding differs')


def check_qemu_files(manifest, frozen=None):
    backup, files = manifest['backup_transport'], manifest['files']
    selected = backup.get('binary_sha256')
    require(selected in (QEMU_SHA256, READONLY_SCOPE_QEMU_SHA256) and files.get(backup.get('binary')) == selected,
            'manifest QEMU differs from accepted unchanged executable or exact readonly candidate')
    digest_binding(read_absolute(backup['binary']), selected, 'actual accepted QEMU')
    if selected == READONLY_SCOPE_QEMU_SHA256 or manifest.get('readonly_scope_observer') is not None:
        check_readonly_scope_observer(manifest, selected, frozen)
    return selected


def check_batch(run, batch, manifest):
    batch = writeback.absolute_path(batch)
    if batch.name == 'ready.json':
        batch = batch.parent
    batch = writeback.directory(batch)
    require(not batch.is_relative_to(run) and not run.is_relative_to(batch), 'run and frozen batch must be separate directories')
    ready_raw = read(batch, 'ready.json', writeback.MAX_JSON)
    ready = object_json(ready_raw)
    require(ready.get('capture_verified') is False, 'batch scope promoted capture')
    names = {'inputs.json': 'inputs_sha256', 'host-regression.json': 'regression_sha256',
             'abi.json': 'abi_sha256', 'inputs.tar.gz': 'all_input_archive_sha256',
             'functional-camera-model.so': 'functional_model_library_sha256',
             'functional-model-sources.tar.gz': 'functional_model_source_archive_sha256',
             'functional-camera-model-build.json': 'functional_model_build_receipt_sha256'}
    raw = {}
    for name, field in names.items():
        needed(field in ready, 'ready.json: ' + field)
        raw[name] = read(batch, name)
        digest_binding(raw[name], ready[field], name)
    inputs, regression, abi, model = (object_json(raw[name]) for name in
        ('inputs.json', 'host-regression.json', 'abi.json', 'functional-camera-model-build.json'))
    groups, frozen = frozen_sources(inputs)
    archive(raw['inputs.tar.gz'], {str(Path(name).relative_to(NATIVE)): digest for name, digest in frozen.items()})
    require(regression.get('returncode') == 0 and type(regression.get('returncode')) is int and
            regression.get('capture_verified') is False and
            typed_equal(regression.get('changed'), {name: [] for name in groups}) and
            regression.get('inputs_sha256') == sha(raw['inputs.json']), 'failed/changed frozen host regression')
    tests = uint(regression.get('tests_passed'), 1000000)
    require(tests > 0, 'empty regression pass count')
    log = read(batch, 'host-regression.log', MAX_LOG)
    digest_binding(log, regression.get('log_sha256'), 'host regression log')
    require(re.search(rb'\b' + str(tests).encode() + rb' passed\b', log), 'actual regression count/log differs')
    require(abi.get('regression_sha256') == sha(raw['host-regression.json']) and
            type(abi.get('returncode')) is int and abi['returncode'] == 0 and abi.get('capture_verified') is False,
            'original-libc ABI/regression binding failed')
    marker = 'PASS: constructor thread and application-init wrapper preserved behavior'
    media = abi.get('media_preload')
    require(marker in abi.get('stdout', '') and type(media) is dict and
            type(media.get('returncode')) is int and media['returncode'] == 0 and
            marker in media.get('stdout', '') and media.get('bind_now') is True,
            'both actual original-libc observer/media ABI executions required')
    build_raw = read(run, 'observer-build-inputs.json', writeback.MAX_JSON)
    build = object_json(build_raw)
    require(typed_equal(build, manifest.get('compiled_observer')) and
            manifest.get('selected_observer_matches_build') is True, 'same-run observer build mismatch')
    sources = build.get('sources')
    require(type(sources) is dict and {name: row['sha256'] for name, row in sources.items()} == groups['production'] and
            type(abi.get('source_count')) is int and abi['source_count'] == len(sources) and
            abi.get('observer_sha256') == build.get('observer_sha256') and
            abi.get('source_archive_sha256') == build.get('source_archive_sha256'),
            'observer differs from exactly tested/ABI-bound source set')
    observed_archive = read(run, 'observer-build-sources.tar.gz')
    digest_binding(observed_archive, build.get('source_archive_sha256'), 'observer source archive')
    index = {row['archive_path']: row['sha256'] for row in sources.values()}
    require(len(index) == len(sources), 'duplicate observer source archive paths')
    with tarfile.open(fileobj=io.BytesIO(observed_archive), mode='r:gz') as stream:
        members = [member for member in stream if member.name == 'source-inputs.json']
        require(len(members) == 1 and members[0].isfile() and members[0].size <= writeback.MAX_JSON,
                'observer archive source index missing/ambiguous')
        with stream.extractfile(members[0]) as item:
            index_raw = item.read(writeback.MAX_JSON + 1)
    require(typed_equal(object_json(index_raw), sources), 'archived observer index differs')
    index['source-inputs.json'] = sha(index_raw)
    archive(observed_archive, index)
    selected, files = manifest.get('selected_initramfs_verified_files'), manifest.get('files')
    require(type(selected) is dict and type(files) is dict and manifest.get('original_libraries_unchanged') is True,
            'original selected library identity missing')
    expected = dict(PUBLIC_LIBRARIES, **{'simulation/menu-observe.so': abi['observer_sha256'],
                    'simulation/file-media-config.so': abi['media_preload_sha256']})
    for name, digest in expected.items():
        require(selected.get(name) == digest, 'selected public original/observer differs: ' + name)
        digest_binding(read(RUNTIME / 'menu-root', name), digest, 'current guest asset ' + name)
    digest_binding(read(RUNTIME, 'menu-observe.so'), abi['observer_sha256'], 'current observer')
    host_index_omissions = []
    for name, digest in groups['host'].items():
        if name in files:
            require(files[name] == digest, 'run host implementation differs: ' + name)
        else:
            require(Path(name).name == 'build-functional-camera-model.py', 'run host implementation not indexed: ' + name)
            host_index_omissions.append(name)
    if any(value is not None for target in (manifest, manifest.get('backup_transport', {}))
           if type(target) is dict for key, value in target.items()
           if key.startswith('functional_camera_bb_timecode_control_')):
        bb_timecode_module().source_bindings(manifest, types.SimpleNamespace(**globals()), frozen)
    if any(value is not None for target in (manifest, manifest.get('backup_transport', {}))
           if type(target) is dict for key, value in target.items()
           if key.startswith('functional_camera_bb_timecode_preset_')):
        bb_timecode_presets_module().source_bindings(manifest, types.SimpleNamespace(**globals()), frozen)
    for name, digest in files.items():
        if name in frozen:
            require(digest == frozen[name], 'manifest frozen source drift: ' + name)
    qemu_sha256 = check_qemu_files(manifest, frozen)
    require(model.get('profile') == PROFILE and model.get('capture_verified') is False and
            model.get('physical_asic_compatibility_verified') is False and model.get('sources'), 'host-model scope differs')
    for name, digest in model['sources'].items():
        require(frozen.get(str(NATIVE / writeback.relative_path(name))) == digest, 'model source not exactly frozen: ' + name)
    archive(raw['functional-model-sources.tar.gz'], model['sources'])
    digest_binding(raw['functional-camera-model.so'], model['library_sha256'], 'actual model bytes')
    library = raw['functional-camera-model.so']
    require(library[:7] == b'\x7fELF\x02\x01\x01' and len(library) >= 64 and
            struct.unpack_from('<H', library, 16)[0] == 3 and
            struct.unpack_from('<H', library, 18)[0] in (62, 183), 'model is not a supported host ELF64 shared library')
    for name in ('functional-camera-model.so', 'functional-camera-model-build.json'):
        require(read(RUNTIME, name) == raw[name], 'published runtime model/build differs from batch: ' + name)
    work = NATIVE / writeback.relative_path(model['work'])
    require(work.parent == RUNTIME / 'scratch' and work.name.startswith('functional-model-build-'), 'untrusted model work')
    compile_raw = read(work, 'compile.json', writeback.MAX_JSON)
    digest_binding(compile_raw, model['compile_receipt_sha256'], 'actual model compile receipt')
    compiled = object_json(compile_raw)
    require(type(compiled.get('returncode')) is int and compiled['returncode'] == 0 and
            {'-shared', '-fPIC', '-Wl,--no-undefined'} <= set(compiled.get('command', [])), 'actual model build failed')
    digest_binding(read(work, 'build.log'), compiled.get('log_sha256'), 'actual model compiler log')
    digest_binding(raw['functional-model-sources.tar.gz'], model['source_archive_sha256'], 'model archive')
    needed(str(RUNTIME / 'initramfs_identity.py') in frozen,
           'inputs.json: current read-only initramfs_identity.py helper')
    image = source_module(RUNTIME / 'initramfs_identity.py')
    image_path = run / 'selected-initramfs.cpio'
    needed(image_path.exists(), 'selected-initramfs.cpio: retain complete same-run selected image')
    source = manifest.get('probe_args', {}).get('initramfs_file') or str(RUNTIME / 'menu-initramfs.cpio')
    # Hash and parse the same private snapshot, never a second live image path.
    with writeback.open_file(run, image_path.name, 1024**3) as stream, writeback.tempfile.TemporaryFile() as snapshot:
        before = os.fstat(stream.fileno())
        space = os.fstatvfs(snapshot.fileno())
        require(space.f_bavail * space.f_frsize >= before.st_size + 1024**2, 'insufficient initramfs snapshot space')
        digest, count = hashlib.sha256(), 0
        for part in iter(lambda: stream.read(1024**2), b''):
            count += len(part)
            require(count <= before.st_size and snapshot.write(part) == len(part), 'changed image/short snapshot')
            digest.update(part)
        require(count == before.st_size and writeback.identity(before) == writeback.identity(os.fstat(stream.fileno())) and
                digest.hexdigest() == files.get(source), 'same-run complete selected initramfs digest differs')
        snapshot.flush()
        image.verify_image(Path('/proc/self/fd/' + str(snapshot.fileno())), selected)
    return {'ready_sha256': sha(ready_raw), 'batch': str(batch), 'tests_passed': tests,
            'observer_sha256': abi['observer_sha256'], 'source_count': len(sources),
            'model_sha256': model['library_sha256'], 'model_build_sha256': sha(raw['functional-camera-model-build.json']),
            'model_source_archive_sha256': model['source_archive_sha256'], 'qemu_sha256': qemu_sha256,
            'public_original_libraries': PUBLIC_LIBRARIES, 'host_build_source_index_omissions': host_index_omissions,
            'current_frozen_sources_equal': True}, frozen


def payload_read(run, reference, budget=None):
    """Read the broker's actual immutable binary chunk, including inode binding."""
    needed(type(reference) is dict, 'broker: actual request_payload/output_payload reference')
    path = reference.get('path', '')
    require(re.fullmatch(r'functional-camera-data/[0-9]{20}-(?:in|out)\.bin', path) and
            reference.get('source_kind') == 'actual_hardware_transfer' and
            reference.get('writeback_verified') is True, 'invalid actual payload reference')
    directory = writeback.directory(run / 'functional-camera-data')
    require(stat.S_IMODE(directory.stat().st_mode) == 0o700, 'payload directory permissions differ')
    size = uint(reference.get('bytes'), 64 * 1024**2)
    if budget is not None:
        require(budget[0] >= size and budget[1] > 0, 'payload aggregate/file budget exceeded')
        budget[0] -= size
        budget[1] -= 1
    with writeback.open_file(run, path, 64 * 1024**2) as stream:
        before = os.fstat(stream.fileno())
        expected = tuple(uint(reference.get(key)) for key in ('device', 'inode', 'bytes', 'mtime_ns', 'ctime_ns'))
        identity = lambda s: (s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns, s.st_ctime_ns)
        require(stat.S_IMODE(before.st_mode) == 0o600 and identity(before) == expected,
                'retained payload identity/permissions differ')
        raw = stream.read(size + 1)
        require(len(raw) == size and identity(os.fstat(stream.fileno())) == expected,
                'retained payload changed/short read')
    require(sha(raw) == writeback.hash_hex(reference.get('sha256'), 64) ==
            reference.get('writeback_sha256') and fnv(raw) == uint(reference.get('fnv1a64')),
            'retained payload SHA/FNV differs')
    return raw


def transfer_output(run, transfer):
    needed(run is not None, 'run required for actual immutable encoded payloads')
    raw = b''.join(payload_read(run, ref) for ref in transfer['output_payloads'])
    require(len(raw) == transfer['bytes'] and sha(raw) == transfer['sha256'] and
            f'{fnv(raw):016x}' == transfer['fnv1a64'], 'aggregate encoded result changed')
    return raw


def raw_hex(fields, key, length):
    needed(key in fields, 'actual trace bytes missing: ' + key)
    text = fields[key]
    require(type(text) is str and re.fullmatch(r'[0-9a-f]{' + str(length * 2) + '}', text),
            'noncanonical/incorrect raw trace bytes: ' + key)
    return bytes.fromhex(text)


def annex_nals(raw):
    """Exact producer Annex-B grammar; preserve every byte within each NAL."""
    starts = list(re.finditer(b'\x00\x00(?:\x00)?\x01', raw))
    require(starts and starts[0].start() == 0 and len(starts) <= 100000, 'invalid Annex-B delimiters')
    values = [raw[m.end():starts[i + 1].start() if i + 1 < len(starts) else len(raw)]
              for i, m in enumerate(starts)]
    require(all(n and not n[0] & 0x80 and 0 < n[0] & 31 < 24 for n in values), 'empty/invalid AVC NAL')
    return values


def avcc_nals(raw, length_size=4):
    require(length_size in (1, 2, 4), 'invalid AVC sample NAL length size')
    cursor, values = 0, []
    while cursor < len(raw):
        require(cursor + length_size <= len(raw) and len(values) < 100000, 'truncated/excess AVC NAL lengths')
        size = int.from_bytes(raw[cursor:cursor + length_size], 'big')
        cursor += length_size
        require(size and size <= len(raw) - cursor, 'AVC NAL range outside sample')
        values.append(raw[cursor:cursor + size])
        require(not values[-1][0] & 0x80 and 0 < values[-1][0] & 31 < 24, 'invalid AVC NAL header')
        cursor += size
    require(values, 'empty AVC sample')
    return values


def avcc_bytes(values):
    return b''.join(struct.pack('>I', len(value)) + value for value in values)


def jpeg_parts(raw):
    """Bounded single-scan JPEG; metadata may change, coding tables/scan may not."""
    writeback._reader.jpeg_structure(raw)
    cursor, coding, geometry = 2, [], None
    while cursor < len(raw):
        start = cursor
        while raw[cursor] == 255:
            cursor += 1
        marker = raw[cursor]
        cursor += 1
        size = int.from_bytes(raw[cursor:cursor + 2], 'big')
        end = cursor + size
        if marker == 0xda:
            return {'coding': coding, 'scan': raw[start:], 'scan_offset': start, 'geometry': geometry}
        if not 0xe0 <= marker <= 0xef and marker != 0xfe:
            coding.append(raw[start:end])
        if marker in (0xc0, 0xc1, 0xc2):
            geometry = (int.from_bytes(raw[cursor + 5:cursor + 7], 'big'),
                        int.from_bytes(raw[cursor + 3:cursor + 5], 'big'))
        cursor = end
    raise ValueError('JPEG actual scan missing')


def exif_thumbnail(raw):
    """One bounded EXIF TIFF IFD1 JPEG; offsets are TIFF-relative, never searched."""
    jpeg_parts(raw)
    cursor, exifs = 2, []
    while cursor < len(raw):
        while raw[cursor] == 255:
            cursor += 1
        marker = raw[cursor]
        cursor += 1
        size = int.from_bytes(raw[cursor:cursor + 2], 'big')
        end = cursor + size
        if marker == 0xda:
            break
        if marker == 0xe1 and raw[cursor + 2:cursor + 8] == b'Exif\0\0':
            exifs.append((cursor + 8, end))
        cursor = end
    needed(exifs, 'JPEG Thumb requires EXIF TIFF IFD1 layout in original file')
    require(len(exifs) == 1, 'JPEG duplicate EXIF/IFD1 ranges')
    start, end = exifs[0]
    tiff = raw[start:end]
    require(len(tiff) >= 8 and tiff[:2] in (b'II', b'MM'), 'EXIF TIFF endian/header')
    order = '<' if tiff[:2] == b'II' else '>'
    def integer(offset, kind):
        size = struct.calcsize(kind)
        require(0 <= offset <= len(tiff) - size, 'EXIF TIFF integer span')
        return struct.unpack_from(order + kind, tiff, offset)[0]
    require(integer(2, 'H') == 42, 'EXIF TIFF magic')
    def directory(offset):
        require(8 <= offset <= len(tiff) - 6, 'EXIF IFD offset')
        count = integer(offset, 'H')
        stop = offset + 2 + 12 * count + 4
        require(stop <= len(tiff), 'EXIF IFD count/span')
        tags = {}
        for entry in range(offset + 2, stop - 4, 12):
            tag, kind = integer(entry, 'H'), integer(entry + 2, 'H')
            require(tag not in tags, 'EXIF duplicate IFD tag')
            tags[tag] = (kind, integer(entry + 4, 'I'), entry + 8)
        return tags, integer(stop - 4, 'I'), (offset, stop)
    _, next_ifd, first_span = directory(integer(4, 'I'))
    needed(next_ifd, 'JPEG Thumb missing EXIF IFD1')
    tags, following, second_span = directory(next_ifd)
    require(not following and (first_span[1] <= second_span[0] or second_span[1] <= first_span[0]),
            'EXIF duplicate/overlapping IFD1 range')
    needed(0x201 in tags and 0x202 in tags, 'EXIF IFD1 JPEG offset/length tags')
    for tag in (0x201, 0x202):
        require(tags[tag][:2] == (4, 1), 'EXIF IFD1 JPEG tag type/count')
    if 0x103 in tags:
        kind, count, offset = tags[0x103]
        require((kind, count) == (3, 1) and integer(offset, 'H') == 6, 'EXIF IFD1 compression')
    offset, size = (integer(tags[tag][2], 'I') for tag in (0x201, 0x202))
    require(size > 4 and 8 <= offset <= len(tiff) - size and
            all(offset + size <= lo or hi <= offset for lo, hi in (first_span, second_span)),
            'EXIF IFD1 JPEG offset/length overflow/span')
    jpeg = tiff[offset:offset + size]
    return {'bytes': jpeg, 'offset': start + offset, 'length': size, 'parts': jpeg_parts(jpeg)}


def mp4_samples(raw):
    """Read one AVC video track's actual sample tables; no marker/mdat search."""
    require(len(raw) <= writeback.MAX_SOURCE, 'MP4 exceeds snapshot bound')
    budget = [0]
    def boxes(start, end):
        cursor, found = start, []
        while cursor < end:
            require(cursor + 8 <= end and budget[0] < 100000, 'MP4 box header/budget')
            size, kind = struct.unpack_from('>I4s', raw, cursor)
            header = 8
            if size == 1:
                require(cursor + 16 <= end, 'MP4 extended header truncated')
                size, header = struct.unpack_from('>Q', raw, cursor + 8)[0], 16
            if size == 0:
                size = end - cursor
            require(size >= header and size <= end - cursor, 'MP4 box range')
            found.append((kind, cursor + header, cursor + size))
            cursor += size
            budget[0] += 1
        return found
    def one(items, kind):
        found = [item for item in items if item[0] == kind]
        require(len(found) == 1, 'MP4 missing/duplicate box ' + repr(kind))
        return found[0][1:]
    top = boxes(0, len(raw))
    one(top, b'ftyp')
    moov = boxes(*one(top, b'moov'))
    mdats = [(a, b) for kind, a, b in top if kind == b'mdat']
    tracks = []
    for kind, a, b in moov:
        if kind != b'trak':
            continue
        mdia = boxes(*one(boxes(a, b), b'mdia'))
        h, e = one(mdia, b'hdlr')
        require(e - h >= 12, 'MP4 short handler')
        if raw[h + 8:h + 12] == b'vide':
            tracks.append(boxes(*one(boxes(*one(mdia, b'minf')), b'stbl')))
    require(len(tracks) == 1, 'MP4 must have exactly one video track')
    table = tracks[0]
    a, b = one(table, b'stsd')
    require(b - a >= 8 and raw[a:a + 4] == bytes(4) and struct.unpack_from('>I', raw, a + 4)[0] == 1,
            'MP4 single sample description required')
    entry = boxes(a + 8, b)
    require(len(entry) == 1 and entry[0][0] == b'avc1', 'MP4 requires actual avc1 description')
    _, a, b = entry[0]
    require(b - a >= 78, 'MP4 short visual sample entry')
    width, height = struct.unpack_from('>2H', raw, a + 24)
    a, b = one(boxes(a + 78, b), b'avcC')
    config = raw[a:b]
    require(len(config) >= 7 and config[0] == 1 and config[4] & 0xfc == 0xfc and config[5] & 0xe0 == 0xe0,
            'invalid avcC configuration')
    length_size, cursor, parameters = (config[4] & 3) + 1, 6, []
    for count, kind in ((config[5] & 31, 7), (None, 8)):
        if count is None:
            require(cursor < len(config), 'avcC missing PPS count')
            count, cursor = config[cursor], cursor + 1
        require(count > 0, 'avcC missing parameter sets')
        for _ in range(count):
            require(cursor + 2 <= len(config), 'avcC truncated parameter length')
            size = int.from_bytes(config[cursor:cursor + 2], 'big')
            cursor += 2
            require(size and cursor + size <= len(config), 'avcC parameter range')
            value = config[cursor:cursor + size]
            require(value[0] & 31 == kind, 'avcC wrong parameter type')
            parameters.append(value)
            cursor += size
    require(cursor == len(config), 'unsupported avcC extension/trailing bytes')
    a, b = one(table, b'stsz')
    require(b - a >= 12 and raw[a:a + 4] == bytes(4), 'invalid stsz header')
    default, count = struct.unpack_from('>2I', raw, a + 4)
    require(2 <= count <= 100000 and b - a == 12 + (0 if default else count * 4), 'stsz size/count')
    sizes = [default] * count if default else list(struct.unpack_from('>' + str(count) + 'I', raw, a + 12))
    require(all(sizes), 'empty MP4 media sample')
    offsets = [item for item in table if item[0] in (b'stco', b'co64')]
    require(len(offsets) == 1, 'MP4 chunk offset table missing/ambiguous')
    kind, a, b = offsets[0]
    require(b - a >= 8 and raw[a:a + 4] == bytes(4), 'invalid chunk table')
    chunks = struct.unpack_from('>I', raw, a + 4)[0]
    unit = 4 if kind == b'stco' else 8
    require(0 < chunks <= count and b - a == 8 + chunks * unit, 'chunk table size/count')
    offsets = struct.unpack_from('>' + str(chunks) + ('I' if unit == 4 else 'Q'), raw, a + 8)
    a, b = one(table, b'stsc')
    require(b - a >= 8 and raw[a:a + 4] == bytes(4), 'invalid stsc header')
    n = struct.unpack_from('>I', raw, a + 4)[0]
    require(0 < n <= chunks and b - a == 8 + n * 12, 'stsc size/count')
    mapping = [struct.unpack_from('>3I', raw, a + 8 + i * 12) for i in range(n)]
    require(mapping[0][0] == 1 and all(0 < first <= chunks and per > 0 and desc == 1 for first, per, desc in mapping) and
            all(x[0] < y[0] for x, y in zip(mapping, mapping[1:])), 'invalid stsc mapping')
    samples, extents, index, active = [], [], 0, 0
    for chunk, offset in enumerate(offsets, 1):
        if active + 1 < len(mapping) and mapping[active + 1][0] == chunk:
            active += 1
        for _ in range(mapping[active][1]):
            require(index < len(sizes), 'stsc exceeds actual samples')
            end = offset + sizes[index]
            require(any(a <= offset < end <= b for a, b in mdats), 'MP4 sample outside actual mdat')
            extents.append((offset, end))
            samples.append(avcc_nals(raw[offset:end], length_size))
            index, offset = index + 1, end
    require(index == count and all(a[1] <= b[0] for a, b in zip(sorted(extents), sorted(extents)[1:])),
            'missing/overlapping MP4 sample extents')
    return {'parameters': parameters, 'samples': samples, 'extents': extents, 'geometry': (width, height)}


def frame_console_kernel(item, byte_offset, raw_lf_line):
    """Split only approved C producer grammars and their paired exact UIPC trailers."""
    joined = re.fullmatch(
        rb'((?:FUNCTIONAL_CAMERA_CONTROL_COMMIT|FUNCTIONAL_CAMERA_CONTROL_RESOURCES_(?:TTS_TABLE|RESERVED)|'
        rb'FUNCTIONAL_CAMERA_TRANSFER|FUNCTIONAL_STARTUP_CONTROL_PREDECESSORS|'
        rb'FUNCTIONAL_FACE_DMM_SOURCE_BOUND|NATIVE_CP_BACKGROUND_INPUT_AUDIT_BYTES|'
        rb'FULL_HDMI_VIDEO_STATE_NATIVE_FREE|'
        rb'FUNCTIONAL_CP_PARAMETER_BANK_(?:EVENT|BYTES|RESOURCE_DEPENDENCIES|RESOURCES_(?:TTS_TABLE|RESERVED))|'
        rb'FUNCTIONAL_CP_CRANK_CONTROL_(?:EVENT|BYTES|RESOURCE_DEPENDENCIES|RESOURCES_(?:TTS_TABLE|RESERVED))|'
        rb'FUNCTIONAL_CP_MOVIE_FORMAT_(?:EVENT|BYTES|RESOURCE_DEPENDENCIES|RESOURCES_(?:TTS_TABLE|RESERVED))|'
        rb'FUNCTIONAL_CP_OU_CRANK_CONTROL_(?:EVENT|BYTES|RESOURCE_DEPENDENCIES|RESOURCES_(?:TTS_TABLE|RESERVED))|'
        rb'FUNCTIONAL_BB_TIMECODE_(?:EVENT|BYTES|RESOURCE_DEPENDENCIES|RESOURCES_(?:TTS_TABLE|RESERVED))|'
        rb'FUNCTIONAL_BB_TIMECODE_PRESET_(?:EVENT|BYTES|RESOURCE_DEPENDENCIES|RESOURCES_(?:TTS_TABLE|RESERVED))|'
        rb'NATIVE_BB_TIMECODE_INPUT_AUDIT|NATIVE_BB_TIMECODE_PRESET_INPUT_AUDIT|'
        rb'FUNCTIONAL_VDF_PATH_(?:REQUEST_FREE|SEND|COMPLETE|RECEIVE|AP_FREE)) [^\r\n]*)'
        rb'(\[ (?:0|[1-9][0-9]{0,9})\.[0-9]{6}\] (?:'
        rb'UDIF: cdev_ioctl\(\) Line 100: uipc: warning ret = -1022|'
        rb'\[K\]\*\*UIPC ERROR\*\* free_dynamic_msgq_id: QID\[[0-9a-f]{8}\] M=1 C=0 S=0 A=1))(\r?\n)', item)
    if joined is None:
        return item, None
    payload, kernel, ending = joined.groups()
    dynamic = b'] [K]**UIPC ERROR** free_dynamic_msgq_id:' in kernel
    dynamic_only = payload.startswith((b'FUNCTIONAL_CAMERA_CONTROL_RESOURCES_TTS_TABLE ',
                                       b'FUNCTIONAL_CAMERA_CONTROL_RESOURCES_RESERVED '))
    either_trailer = payload.startswith((b'FUNCTIONAL_CAMERA_CONTROL_COMMIT ', b'FUNCTIONAL_VDF_PATH_',
                                         b'FUNCTIONAL_CP_PARAMETER_BANK_', b'FUNCTIONAL_CP_CRANK_CONTROL_',
                                         b'FUNCTIONAL_CP_MOVIE_FORMAT_', b'FUNCTIONAL_CP_OU_CRANK_CONTROL_',
                                         b'FULL_HDMI_VIDEO_STATE_NATIVE_FREE ', b'FUNCTIONAL_BB_TIMECODE_',
                                         b'NATIVE_BB_TIMECODE_INPUT_AUDIT ', b'NATIVE_BB_TIMECODE_PRESET_INPUT_AUDIT '))
    if ((not either_trailer and dynamic_only != dynamic)
            or console_producer_fields(payload) is None):
        return item, None
    return payload + ending, dict(raw=kernel.decode('ascii'), bytes=len(kernel), sha256=sha(kernel),
        byte_offset=byte_offset + len(payload), raw_lf_line=raw_lf_line, cause='unknown',
        line_ending=ending.decode('ascii'), payload=dict(raw=payload.decode('ascii'), bytes=len(payload),
            sha256=sha(payload), byte_offset=byte_offset))


def bb_timecode_module():
    """Fixed stdlib-only reader, loaded lazily for this exact producer family."""
    return source_module(Path(__file__).with_name('check_bb_timecode.py'))


def bb_timecode_presets_module():
    """Fixed independent preset reader; the old six-API owner is unchanged."""
    return source_module(Path(__file__).with_name('check_bb_timecode_presets.py'))


def console_producer_fields(payload):
    """Exact formatter fields only; actual broker/content/lifecycle joins remain separate."""
    tag, *parts = payload.decode('ascii', 'strict').split(' ')
    if not all(re.fullmatch(r'[A-Za-z_][A-Za-z_0-9]*=[!-~]+', part) for part in parts):
        return None
    fields = writeback.unique_object(part.split('=', 1) for part in parts)
    if tag.startswith(('FUNCTIONAL_BB_TIMECODE_PRESET_', 'NATIVE_BB_TIMECODE_PRESET_')):
        return bb_timecode_presets_module().producer_fields(tag, fields, types.SimpleNamespace(**globals()))
    if tag.startswith('FUNCTIONAL_BB_TIMECODE_') or tag == 'NATIVE_BB_TIMECODE_INPUT_AUDIT':
        return bb_timecode_module().producer_fields(tag, fields, types.SimpleNamespace(**globals()))
    bank_resources = {
        '_RESOURCE_DEPENDENCIES': 'pid tid accepted proc_ap_consumed input_ap_consumed output_ap_consumed output_faults current_request_retained_expected capture_verified',
        '_RESOURCES_TTS_TABLE': 'pid tid appfw_base table_va address bytes reads unchanged atomic_snapshot raw_before raw_after ownership_verified',
        '_RESOURCES_RESERVED': ('tid accepted dmm_enabled dmm_bound dmm_slots dmm_opens dmm_handles dmm_generations dmm_epochs '
            'dmm_creators dmm_allocation_count dmm_lifecycle_changed dmm_domain foreign_speech_kept data_frozen control_bound '
            'control_live control_faults allocations releases connection_started connections format_pending blocked format_consumed '
            'buffer_released connection_reply_frees connection_faults vef_init vef_owner vef_objects vef_pending vef_live '
            'vef_retained vef_faults pinmem_init pinmem_owner pinmem_objects pinmem_pending pinmem_live pinmem_retained '
            'pinmem_faults global_dmm_idle_verified original_cp_executed capture_verified'),
    }
    for suffix, order in bank_resources.items():
        if (tag in ('FUNCTIONAL_CP_PARAMETER_BANK' + suffix, 'FUNCTIONAL_CP_CRANK_CONTROL' + suffix,
                    'FUNCTIONAL_CP_MOVIE_FORMAT' + suffix, 'FUNCTIONAL_CP_OU_CRANK_CONTROL' + suffix) or
                tag == 'FUNCTIONAL_CAMERA_CONTROL_RESOURCES_RESERVED' and suffix == '_RESOURCES_RESERVED'):
            if list(fields) != order.split():
                return None
            try:
                return fields if vdf_resource_diagnostic(dict(tag='FUNCTIONAL_VDF_PATH' + suffix, fields=fields)) else None
            except ValueError:
                return None
    vdf = tag in {'FUNCTIONAL_VDF_PATH_' + name for name in ('REQUEST_FREE', 'SEND', 'COMPLETE', 'RECEIVE', 'AP_FREE')}
    if vdf:
        schema = ('pid:pid tid:tid phase:u32 cycle:u64 requests:u32 completed_cycles:u32 busy:u32 guard:u32 faults:u32 '
            'source:hex32 destination:hex32 command:hex32 bytes:u32 original_fnv1a:digest '
            'refresh_queue_bound:u32 refresh_queue_source:hex32 model_instance:u64 config_generation:u64 '
            'before_config_generation:u64 frame_generation:u64 before_frame_generation:u64 lease_generation:u64 '
            'init_rc:i32 bridge_rc:i32 validation_rc:i32 request_owned:u32 request_retained:pointer request_freed:u32 '
            'ack_retained:pointer queued:u32 received:u32 AP_consumed:u32 send_inflight:u32 releasing:u32 '
            'sender_tid:tid receiver_tid:tid free_tid:tid allocate_rc:i32 allocation_returned:pointer allocation_alias:u32 '
            'request_free_rc:i32 send_rc:i32 free_rc:i32 model_complete:u32 functional_model:1 original_CP_FIFO_verified:0 '
            'physical_CP_RTOS_verified:0 original_selector_verified:0 physical_ASIC_verified:0 capture_verified:0 '
            'raw:raw ack_wire:raw12 canonical_config:raw16 canonical_zebra8:raw8 canonical_layout32:raw32 '
            'canonical_display16:raw16 canonical_bb32:raw32 canonical_bit_width8:raw8 model_result_bytes:u32 '
            'realresultbytes:u32 model_result_fnv1a64:digest model_result_hex:raw')
    elif tag == 'FUNCTIONAL_CP_OU_CRANK_CONTROL_EVENT':
        schema = CP_OU_CRANK_EVENT_SCHEMA
    elif tag == 'FUNCTIONAL_CP_OU_CRANK_CONTROL_BYTES':
        schema = CP_OU_CRANK_BYTES_SCHEMA
    elif tag == 'FUNCTIONAL_CP_MOVIE_FORMAT_EVENT':
        schema = CP_MOVIE_EVENT_SCHEMA
    elif tag == 'FUNCTIONAL_CP_MOVIE_FORMAT_BYTES':
        schema = CP_MOVIE_BYTES_SCHEMA
    elif tag == 'FUNCTIONAL_CP_CRANK_CONTROL_EVENT':
        schema = CP_CRANK_EVENT_SCHEMA
    elif tag == 'FUNCTIONAL_CP_CRANK_CONTROL_BYTES':
        schema = CP_CRANK_BYTES_SCHEMA
    elif tag == 'FUNCTIONAL_CP_PARAMETER_BANK_EVENT':
        schema = ('event:bank_event pid:pid tid:tid transaction:u64 sender_tid:tid source:hex32 destination:hex32 '
            'command:hex32 bytes:u32 native_fnv1a:digest cookie:hex32 busy:bit guard:bit faults:u32 error:i32 model_rc:i32 '
            'model_called:bit model_committed:bit verified:bit owned:bit retained:pointer releasing:bit request_freed:bit '
            'free_rc:i32 free_tid:tid commits:u64 released:u64 model_instance:u64 bank_generation:u64 '
            'before_config_generation:u64 config_generation:u64 fps:u32 before_used:u64 before_required:u64 '
            'before_token:u64 before_instance:u64 bank_used:u64 bank_required:u64 bank_token:u64 bank_instance:u64 '
            'after_used:u64 after_required:u64 after_token:u64 after_instance:u64 policy:full-190-slot-bank-fps4151-v1 '
            'oneway:1 ACK_sent:0 notification_sent:0 functional_model:1 original_CP:0 physical_ASIC_verified:0 capture_verified:0')
    elif tag == 'FUNCTIONAL_CP_PARAMETER_BANK_BYTES':
        schema = ('pid:pid tid:tid transaction:u64 kind:bank_kind total:u32 offset:u32 bytes:u32 raw:raw '
            'native_fnv1a:digest model_instance:u64 bank_generation:u64 capture_verified:0')
    elif tag == 'FUNCTIONAL_CAMERA_CONTROL_RESOURCES_TTS_TABLE':
        # menu-observe.c:tracked_native_reserve_resources; only complete unchanged reads are framed.
        schema = ('pid:pid tid:tid appfw_base:hex64 table_va:0x5f66b08 address:hex64 bytes:144 '
            'reads:144/144 unchanged:1 atomic_snapshot:0 raw_before:raw144 raw_after:raw144 ownership_verified:0')
    elif tag == 'FUNCTIONAL_STARTUP_CONTROL_PREDECESSORS':
        schema = ('pid:pid tid:tid accepted:bit initial_mode_requests:u32 initial_mode_AP_consumed:u32 '
            'initial_settings_requests:u32 initial_settings_AP_consumed:u32 all13_AP_consumed:bit VDF_AP_consumed:u32 '
            'still_format_AP_consumed:u32 still_format_cycle:u64 model_instance:u64 source_business_equivalent:0 '
            'physical_ASIC_verified:0 capture_verified:0')
    elif tag == 'NATIVE_CP_BACKGROUND_INPUT_AUDIT_BYTES':
        # menu-observe.c:audit_cp_background_input emits at most128 bytes per chunk.
        schema = 'pid:pid tid:tid sequence:u32 offset:u32 bytes:u32 raw:raw'
    elif tag == 'FUNCTIONAL_FACE_DMM_SOURCE_BOUND':
        # menu-observe.c:functional_face_original_caller preserves failed reads/rc too.
        schema = ('pid:pid tid:tid op:hex32 caller_pc:pointer caller_va:hex64 library_base:pointer '
            'source:hex32 reads:reads first:hex32 second:hex32 rc:i32 '
            'producer:process-local-software-owner original_cp_verified:0 capture_verified:0')
    elif tag == 'FULL_HDMI_VIDEO_STATE_NATIVE_FREE':
        # hdmi-video-state.c:full_hdmi_video_state_release; only its complete rc=0 formatter.
        schema = ('tid:pid receiver:u32 sender:pid destination:hex32 pointer:pointer lease:u64 kind:u32 '
            'bytes:u32 rc:0 received:bit consumed:1 original_cp_executed:0 hardware_verified:0 capture_verified:0')
    elif tag == 'FULL_SCALAR_CONNECT_NATIVE_REPLY_FREE':
        # pin-peer-connection.inc:376; same complete successful Scalar subset as Graph.
        schema = ('pid:pid tid:pid sender:pid waiter:1 destination:hex32 expected:hex32 reply:pointer '
            'bytes:56 command:0x8001 rc:0 faults:0 ap_consumed:1 capture_verified:0')
    elif tag == 'FUNCTIONAL_CAMERA_TRANSFER':
        schema = ('seq:interval op:u32 source:hex32 destination:hex32 command:hex32 bytes:u32 native_fnv:hex64 '
            'request_bytes:u64 request_fnv:hex64 returned_bytes:u64 returned_fnv:hex64 required:u64 '
            'destination_written_bytes:u64 destination_fnv:hex64 model_instance:hex64 token:hex64 '
            'readback_closed:bit error:i32 origin_kind:origin')
    elif tag == 'FUNCTIONAL_CAMERA_CONTROL_COMMIT':
        schema = ('pid:pid tid:tid phase:u32 index:u32 role:u32 bytes:u32 destination:hex32 source:hex32 '
            'wire_fnv1a:digest queued:u32 received:u32 freed:u32 consumed:u32 send_inflight:u32 releasing:u32 '
            'lease_cycle_id:u64 sender_tid:tid receiver_tid:tid free_tid:tid allocate_rc:i32 send_rc:i32 free_rc:i32 '
            'retained:pointer faults:u32 busy:u32 guard:u32 probe_run_id:u64 init_run_id:u64 state_run_id:u64 '
            'bridge_rc:i32 probe_rc:i32 native_source:hex32 native_destination:hex32 native_command:hex32 '
            'native_bytes:u32 native_fnv1a:digest model_initialized:u32 probe_attempts:u32 probe_successes:u32 '
            'probe_refusals:u32 model_instance:u64 config_generation:u64 rendered:u64 frame_generation:u64 '
            'start_complete:u32 mode1_complete:u32 defined_mask:u32 full_layout_copied:u32 model_defined:u32 '
            'defined_blocks:u32 projected_blocks:u32 zero_policy_blocks:u32 publication_copied:u32 '
            'xsync_defined:u32 xsync_source_fps:u32 xsync_word:u32 xsync_half:u32 xsync_source_generation:u64 '
            'published_generation:u32 shadow_generation:u32 notification_queued:u32 notification_received:u32 '
            'notification_AP_consumed:u32 cycle_id:u64 cycle_generation:u32 ack_only:u32 mode1_requests:u32 '
            'cycles_completed:u32 ack_only_requests:u32 ack_only_completed:u32 full_queued:u32 full_consumed:u32 '
            'notification_mode:u32 business_ready:u32 functional_model:1 original_CP:0 physical_ASIC_verified:0 '
            'fixed_optics_policy:integrated-noneLIF LIF_tuple:0,0,0 cache4:0 original_getters_executed:0 '
            'original_source_proof:0 EE:0 frame:0 capture:0')
        if 'mode_selector' in fields:
            schema = schema.replace('notification_mode:u32 business_ready:u32',
                'notification_mode:u32 mode_selector:bit mode_complete:bit mode0_requests:u32 '
                'mode0_complete:bit mode0_cycles_completed:u32 mode1_cycle_id:u64 '
                'mode1_cycle_generation:u32 selector_policy:opaque-state-refresh-v1 business_ready:u32')
    else:
        return None
    schema = [part.split(':', 1) for part in schema.split()]
    if list(fields) != [key for key, _ in schema]:
        return None
    for key, kind in schema:
        text = fields[key]
        if kind in ('u32', 'u64', 'pid', 'tid', 'i32', 'hex32', 'hex64'):
            pattern = (r'(?:0|0x[1-9a-f][0-9a-f]{0,15})' if kind.startswith('hex') else
                       r'(?:0|-?[1-9][0-9]{0,18})' if kind in ('tid', 'i32') else r'(?:0|[1-9][0-9]{0,19})')
            if not re.fullmatch(pattern, text):
                return None
            value = int(text, 16 if text.startswith('0x') else 10)
            bits = 64 if kind in ('u64', 'tid', 'hex64') else 32
            lower, upper = (-(1 << (bits - 1)), 1 << (bits - 1)) if kind in ('tid', 'i32', 'pid') else (0, 1 << bits)
            if not lower <= value < upper or kind == 'pid' and value <= 0:
                return None
        elif kind == 'raw':
            if not re.fullmatch(r'(?:[0-9a-f]{2})+', text):
                return None
        elif kind.startswith('raw'):
            if not re.fullmatch(r'[0-9a-f]{' + str(2 * int(kind[3:])) + '}', text):
                return None
        elif kind == 'digest':
            if not re.fullmatch(r'[0-9a-f]{16}', text):
                return None
        elif kind == 'pointer':
            if text != '(nil)' and not re.fullmatch(r'0x[1-9a-f][0-9a-f]{0,15}', text):
                return None
        elif kind == 'interval':
            interval = re.fullmatch(r'([1-9][0-9]{0,19})\.\.([1-9][0-9]{0,19})', text)
            if interval is None or not 0 < int(interval[1]) <= int(interval[2]) < 2**64:
                return None
        elif kind == 'bit':
            if text not in ('0', '1'):
                return None
        elif kind == 'ou_event':
            if text not in ('BEGIN', 'BEFORE', 'MODEL', 'AFTER', 'VERIFIED', 'REQUEST_FREE', 'COMMIT', 'REFUSED', 'FAULT'):
                return None
        elif kind == 'crank_event':
            if text not in ('BEGIN', 'BEFORE', 'MODEL', 'AFTER', 'VERIFIED', 'REPLY', 'ALLOCATED', 'SENT',
                            'REQUEST_FREE', 'COMMIT', 'RECEIVE', 'REPLY_FREE', 'REFUSED', 'FAULT', 'CLEANUP_FREE'):
                return None
        elif kind == 'crank_kind':
            if text not in ('request', 'before_state', 'receipt', 'after_state', 'reply'):
                return None
        elif kind == 'bank_event':
            if text not in ('BEGIN', 'BEFORE', 'MODEL', 'AFTER', 'VERIFIED', 'OWNED_FREE', 'COMMIT', 'REFUSED'):
                return None
        elif kind == 'bank_kind':
            if text not in ('request', 'before_state', 'receipt', 'after_state'):
                return None
        elif kind == 'origin':
            if text not in ('native-osal', 'api40-source-snapshot'):
                return None
        elif kind == 'reads':
            if not re.fullmatch(r'(?:0|-?[1-9][0-9]{0,18})/(?:0|-?[1-9][0-9]{0,18})', text) or any(
                    not -2**63 <= int(part) < 2**63 for part in text.split('/')):
                return None
        elif text != kind:
            return None
    if vdf:
        commands = {command: (size, result_bytes) for mapping, result_bytes in VDF_OPERATIONS.values()
                    for command, size in mapping.items()}
        command = number(fields['command'])
        if command not in commands:
            return None
        native_bytes, result_bytes = commands[command]
        if (number(fields['bytes']) != native_bytes or len(fields['raw']) != 2 * native_bytes or
                number(fields['model_result_bytes']) != result_bytes or number(fields['realresultbytes']) != result_bytes or
                len(fields['model_result_hex']) != 2 * result_bytes):
            return None
    elif tag == 'FUNCTIONAL_CAMERA_CONTROL_RESOURCES_TTS_TABLE':
        base = number(fields['appfw_base'])
        if (not 0x10000 <= base < 0x7ff0000000 or number(fields['address']) != base + 0x5f66b08 or
                fields['raw_before'] != fields['raw_after']):
            return None
    elif tag == 'FUNCTIONAL_CP_PARAMETER_BANK_BYTES':
        total = {'request': 2564, 'before_state': 128, 'receipt': 2756, 'after_state': 128}[fields['kind']]
        offset, count = number(fields['offset']), number(fields['bytes'])
        if (not number(fields['transaction']) or number(fields['total']) != total or offset % 128 or
                offset >= total or count != min(128, total - offset) or len(fields['raw']) != 2 * count):
            return None
    elif tag == 'FUNCTIONAL_CP_OU_CRANK_CONTROL_BYTES':
        total, event = {'request': (12, 'BEGIN'), 'before_state': (128, 'BEFORE'),
                        'receipt': (224, 'MODEL'), 'after_state': (128, 'AFTER')}[fields['kind']]
        offset, count = number(fields['offset']), number(fields['bytes'])
        if (not number(fields['transaction']) or fields['event'] != event or number(fields['total']) != total or
                offset % 128 or offset >= total or count != min(128, total - offset) or len(fields['raw']) != 2 * count):
            return None
    elif tag == 'FUNCTIONAL_CP_MOVIE_FORMAT_BYTES':
        total, event = {'request': (20, 'BEGIN'), 'before_state': (128, 'BEFORE'), 'receipt': (240, 'MODEL'),
                        'after_state': (128, 'AFTER'), 'reply': (12, 'REPLY')}[fields['kind']]
        offset, count = number(fields['offset']), number(fields['bytes'])
        if (not number(fields['transaction']) or fields['event'] != event or number(fields['total']) != total or
                offset % 128 or offset >= total or count != min(128, total - offset) or len(fields['raw']) != 2 * count):
            return None
    elif tag == 'FUNCTIONAL_CP_CRANK_CONTROL_BYTES':
        total, event = {'request': (12, 'BEGIN'), 'before_state': (128, 'BEFORE'), 'receipt': (208, 'MODEL'),
                        'after_state': (128, 'AFTER'), 'reply': (12, 'REPLY')}[fields['kind']]
        offset, count = number(fields['offset']), number(fields['bytes'])
        if (not number(fields['transaction']) or fields['event'] != event or number(fields['total']) != total or
                offset % 128 or offset >= total or count != min(128, total - offset) or len(fields['raw']) != 2 * count):
            return None
    elif tag == 'NATIVE_CP_BACKGROUND_INPUT_AUDIT_BYTES':
        count, offset = number(fields['bytes']), number(fields['offset'])
        if not (number(fields['sequence']) and 0 < count <= 128 and offset % 128 == 0 and
                offset + count <= 4096 and len(fields['raw']) == 2 * count):
            return None
    elif tag == 'FUNCTIONAL_FACE_DMM_SOURCE_BOUND':
        callsites = {0x20: 0x35522a4, 0x21: 0x3552c60, 0x23: 0x35524a8, 0x24: 0x3552694, 0x25: 0x35528ac}
        if callsites.get(number(fields['op'])) != number(fields['caller_va']):
            return None
    elif tag == 'FULL_HDMI_VIDEO_STATE_NATIVE_FREE':
        kind, destination, receiver = (number(fields[key]) for key in ('kind', 'destination', 'receiver'))
        if (kind not in (1, 2, 3) or number(fields['bytes']) != {1: 12, 2: 20, 3: 16}[kind] or
                destination >> 28 != 8 or not destination & 0x0fffffff or
                fields['pointer'] == '(nil)' or not number(fields['lease']) or receiver >= 2**31):
            return None
        if kind == 1:
            if (fields['received'] == '1') != (receiver > 0):
                return None
        elif fields['received'] != '1' or fields['receiver'] != fields['tid']:
            return None
        if kind == 3 and destination != 0x80920572:
            return None
    elif tag == 'FULL_SCALAR_CONNECT_NATIVE_REPLY_FREE':
        destination = number(fields['destination'])
        if (fields['tid'] != fields['sender'] or fields['destination'] != fields['expected'] or
                destination >> 28 != 8 or not destination & 0x0fffffff or fields['reply'] == '(nil)'):
            return None
    elif tag == 'FUNCTIONAL_CAMERA_TRANSFER':
        op = int(fields['op'])
        if op not in OPS or op in (64, 65) or int(fields['request_bytes']) not in OPS[op] or any(
                number(fields[key]) == 0 for key in ('source', 'destination', 'bytes', 'model_instance')) or (
                fields['origin_kind'] == 'api40-source-snapshot') != (op == 11) or (
                fields['readback_closed'] == '1') != (fields['error'] == '0'):
            return None
        if op == 11 and (number(fields['command']) != 0x2820746 or fields['bytes'] != '40'):
            return None
    return fields


def frame_console_transfer_echo(item, byte_offset, raw_lf_line):
    """Frame only the three observed exact prefixes; retain the prefix as unknown-cause evidence."""
    prefixes = (b"'; elOBS ", b"/OBS ", b"AND_DONE_e86OBS ")
    prefix = next((p for p in prefixes if item.startswith(p + b'FUNCTIONAL_CAMERA_TRANSFER ')), None)
    if prefix is None:
        return item, None
    require(item.endswith(b'\n'), 'truncated evidence trace')
    joined = re.fullmatch(rb'([^\r\n]*)(\r?\n)', item[len(prefix):])
    if joined is None or console_producer_fields(joined[1]) is None:
        return item, None
    payload, ending = joined.groups()
    return payload + ending, dict(raw=prefix.decode('ascii'), bytes=len(prefix), sha256=sha(prefix),
        byte_offset=byte_offset, raw_lf_line=raw_lf_line, cause='unknown', line_ending=ending.decode('ascii'),
        payload=dict(raw=payload.decode('ascii'), bytes=len(payload), sha256=sha(payload),
                     byte_offset=byte_offset + len(prefix)))


# pin-peer-connection.inc:317, with EDGE_TAG="ADF" in adf-connection.c.
ADF_NATIVE_FREE_PAYLOAD = re.compile(
    rb'FULL_ADF_CONNECT_NATIVE_REPLY_FREE pid=[1-9][0-9]{0,9} tid=(?:0|-?[1-9][0-9]{0,18}) '
    rb'sender=(?:0|-?[1-9][0-9]{0,18}) waiter=[01] destination=(?:0|0x[1-9a-f][0-9a-f]{0,7}) '
    rb'expected=(?:0|0x[1-9a-f][0-9a-f]{0,7}) reply=(?:\(nil\)|0x[1-9a-f][0-9a-f]{0,15}) '
    rb'bytes=56 command=0x8001 rc=(?:0|-?[1-9][0-9]{0,9}) faults=(?:0|[1-9][0-9]{0,9}) '
    rb'ap_consumed=[01] capture_verified=0')
ADF_HOST_WARNINGS = tuple(b'qemu-system-aarch64: warning: vvfat: host directory commit ' + state + b'\n'
                          for state in (b'pending', b'complete'))


def frame_console_adf_host(item, byte_offset, raw_lf_line, following):
    warning = next((w for w in ADF_HOST_WARNINGS if item.endswith(w)), None)
    if warning is None:
        return item, None
    payload = item[:-len(warning)]
    if ADF_NATIVE_FREE_PAYLOAD.fullmatch(payload) is None:
        return item, None
    fields = dict(part.split('=', 1) for part in payload.decode('ascii').split(' ')[1:])
    bounds = {'pid': (1, 2**31), 'tid': (-2**63, 2**63), 'sender': (-2**63, 2**63),
              'rc': (-2**31, 2**31), 'faults': (0, 2**32)}
    if any(not lower <= int(fields[key]) < upper for key, (lower, upper) in bounds.items()):
        return item, None
    needed(following is not None, 'ADF/vvfat boundary lacks the original guest ending')
    require(following == b'\r\n', 'ADF/vvfat boundary has an unproved guest ending')
    return payload + following, dict(raw=warning.decode('ascii'), bytes=len(warning), sha256=sha(warning),
        byte_offset=byte_offset + len(payload), raw_lf_line=raw_lf_line, cause='unknown',
        line_ending='\r\n', line_ending_byte_offset=byte_offset + len(item), ending_raw_lf_line=raw_lf_line + 1,
        guest_bytes_invented=False, payload=dict(raw=payload.decode('ascii'), bytes=len(payload),
            sha256=sha(payload), byte_offset=byte_offset))


def frame_console_scalar_host(item, byte_offset, raw_lf_line, following):
    """Rejoin only a Scalar tag interrupted by one exact warning; preserve both raw spans."""
    tag = b'OBS FULL_SCALAR_CONNECT_NATIVE_REPLY_FREE '
    warning = next((w for w in ADF_HOST_WARNINGS if item.endswith(w)), None)
    if warning is None:
        return item, None
    prefix = item[:-len(warning)]
    if not len(b'OBS ') < len(prefix) < len(tag) or not tag.startswith(prefix):
        return item, None
    needed(following is not None, 'Scalar/vvfat boundary lacks the original guest continuation')
    record = prefix + following
    if not record.startswith(tag):
        return item, None
    require(len(record) <= 8192, 'Scalar/vvfat reconstructed record exceeds budget')
    joined = re.fullmatch(rb'(OBS [^\r\n]+)(\r?\n)', record)
    require(joined is not None and console_producer_fields(joined[1][4:]) is not None,
            'unproved complete Scalar connect native-free producer after tag repair')
    payload, ending = joined.groups()
    original = item + following
    return record, dict(raw=warning.decode('ascii'), bytes=len(warning), sha256=sha(warning),
        byte_offset=byte_offset + len(prefix), raw_lf_line=raw_lf_line, raw_lf_end=raw_lf_line + 1,
        cause='unknown', guest_bytes_invented=False, line_ending=ending.decode('ascii'),
        raw_record_start=byte_offset, raw_record_end=byte_offset + len(original),
        raw_record_hex=original.hex(), raw_record_sha256=sha(original),
        payload=dict(raw=record.decode('ascii'), bytes=len(record), sha256=sha(record),
            spans=[dict(byte_offset=byte_offset, bytes=len(prefix)),
                   dict(byte_offset=byte_offset + len(item), bytes=len(following))]))


def parse_console(raw):
    require(len(raw) <= MAX_LOG, 'console exceeds budget')
    rows, byte_offset, raw_lf_line = [], 0, 1
    fragments, skip_host_ending = raw.splitlines(keepends=True), False
    timecode_observed = any(re.match(
        rb'(?:/ # )?(?:OBS )?(?:FUNCTIONAL_BB_TIMECODE_(?:PRESET_)?(?:EVENT|BYTES)|NATIVE_BB_TIMECODE_(?:PRESET_)?INPUT_AUDIT) ',
        item) for item in fragments)
    for line, item in enumerate(fragments, 1):
        require(len(item) <= 8192, 'console line exceeds budget')
        start, physical_line = byte_offset, raw_lf_line
        byte_offset += len(item)
        raw_lf_line += item.count(b'\n')
        if skip_host_ending:
            skip_host_ending = False
            continue
        item, scalar_diagnostic = frame_console_scalar_host(item, start, physical_line,
            fragments[line] if line < len(fragments) else None)
        item, echo_diagnostic = frame_console_transfer_echo(item, start, physical_line)
        if echo_diagnostic is not None:
            start = echo_diagnostic['payload']['byte_offset']
        if item.startswith(b'/ # OBS '):
            item, start = item[4:], start + 4  # Interactive ash can leave its prompt before an observer record.
        if item.startswith(b'OBS '):
            item, start = item[4:], start + 4
        item, host_diagnostic = frame_console_adf_host(item, start, physical_line,
                                                      fragments[line] if line < len(fragments) else None)
        skip_host_ending = host_diagnostic is not None or scalar_diagnostic is not None
        item, kernel_diagnostic = frame_console_kernel(item, start, physical_line)
        tag = item.split(b' ', 1)[0].rstrip(b'\r\n')
        if not timecode_observed and tag in (b'FULL_BB_SET_MODE_REPLY_QUEUED', b'FULL_BB_SET_MODE_COMMIT',
                b'FULL_BB_SET_MODE_REPLY_FREE', b'FULL_BB_SET_MODE_FAULT', b'FULL_BB_SET_MODE_RECOVERY_FREE'):
            continue
        if not tag.startswith((b'FUNCTIONAL_', b'FSYS_WRITE_', b'MPR_WRITE_', b'NATIVE_BB_TIMECODE_')) and tag.decode('ascii', 'ignore') not in (
                *BACKGROUND_FREE_TAGS, 'FULL_HDMI_VIDEO_STATE_NATIVE_FREE',
                'NATIVE_BB_TIMECODE_INPUT_AUDIT', 'FULL_BB_SET_MODE_REPLY_QUEUED',
                'FULL_BB_SET_MODE_COMMIT', 'FULL_BB_SET_MODE_REPLY_FREE',
                'FULL_BB_SET_MODE_FAULT', 'FULL_BB_SET_MODE_RECOVERY_FREE',
                'NATIVE_CP302C_DIAGNOSTIC_ALL13_READBACK', 'NATIVE_CP302C_NOCONVERT_ALL13_READBACK',
                'NATIVE_CP_BACKGROUND_INPUT_AUDIT', 'NATIVE_CP_BACKGROUND_INPUT_AUDIT_BYTES',
                'NATIVE_CP_CAPTURE_FORMAT_DIAGNOSTIC_REPLY_FREE', 'NATIVE_CP_STARTUP_DIAGNOSTIC_REPLY_FREE',
                'NATIVE_CP_OUTPUT_POLICY_CONSUMED', 'NATIVE_CP_EE_DIAGNOSTIC_REQUEST_FREE',
                'NATIVE_CP_EE_DIAGNOSTIC_REPLY_FREE', 'NATIVE_CP_EE_DIAGNOSTIC_COMPLETE',
                'NATIVE_CP_EE_DIAGNOSTIC_FAULT', 'NATIVE_CP_EE_DIAGNOSTIC_REFUSED',
                'NATIVE_CP_EE_DIAGNOSTIC_CLEANUP_FREE',
                'NATIVE_CP_MOVIE_FORMAT_DIAGNOSTIC_REQUEST_FREE', 'NATIVE_CP_MOVIE_FORMAT_DIAGNOSTIC_REPLY_FREE',
                'NATIVE_CP_MOVIE_FORMAT_DIAGNOSTIC_COMPLETE', 'NATIVE_CP_MOVIE_FORMAT_DIAGNOSTIC_FAULT',
                'NATIVE_CP_MOVIE_FORMAT_DIAGNOSTIC_REFUSED', 'NATIVE_CP_MOVIE_FORMAT_DIAGNOSTIC_CLEANUP_FREE'):
            continue
        require(item.endswith(b'\n'), 'truncated evidence trace')
        parts = item.decode('ascii', 'strict').rstrip('\r\n').split(' ')
        # Diagnostic failure prose is retained, never parsed as a successful record.
        if (not all(re.fullmatch(r'[A-Za-z_][A-Za-z_0-9]*=[!-~]+', part) for part in parts[1:]) or
                parts[0] == 'FUNCTIONAL_CAMERA_CONTROL_RESOURCES_RESERVED' and
                console_producer_fields(item.rstrip(b'\r\n')) is None or
                parts[0].startswith(('FUNCTIONAL_BB_TIMECODE_PRESET_', 'NATIVE_BB_TIMECODE_PRESET_')) and
                console_producer_fields(item.rstrip(b'\r\n')) is None):
            rows.append({'tag': parts[0], 'line': line, 'fields': {}, 'diagnostic': ' '.join(parts[1:])})
            if kernel_diagnostic is not None:
                rows[-1]['kernel_diagnostic'] = kernel_diagnostic
            continue
        rows.append({'tag': parts[0], 'line': line,
                     'fields': writeback.unique_object(part.split('=', 1) for part in parts[1:])})
        if kernel_diagnostic is not None:
            rows[-1]['kernel_diagnostic'] = kernel_diagnostic
        if host_diagnostic is not None:
            rows[-1]['host_diagnostic'] = host_diagnostic
        if scalar_diagnostic is not None:
            rows[-1]['host_diagnostic'] = scalar_diagnostic
        if echo_diagnostic is not None:
            rows[-1]['console_prefix_diagnostic'] = echo_diagnostic
        require(len(rows) <= MAX_EVENTS, 'trace record budget exceeded')
    return rows


def bounded_control_witness(row):
    """The large-line allowance is for complete typed C buffers, never arbitrary prose."""
    require(type(row) is dict, 'oversized control witness envelope differs')
    expected = set(('actual_c_result actual_core_sha256 event kind model_called model_committed model_instance '
                    'monotonic_ns native_acceptance observation opcode origin output_payload request_payload sequence').split())
    if type(row.get('opcode')) is int and row['opcode'] in (22, 23):
        expected.update(('admission_error', 'input_hex', 'request_fnv1a64', 'error'))
        if row['opcode'] == 23:
            expected.add('validation_error')
    require(set(row) == expected, 'oversized control witness envelope differs')
    op = row['opcode']
    require(type(op) is int and (op, row['kind']) in ((21, 'model_crank_control'), (22, 'model_movie_format'),
                                                   (23, 'model_ou_crank_control')) and
            type(row['actual_c_result']) is int and row['actual_c_result'] == 0 and
            row['model_called'] is True and row['model_committed'] is True and row['native_acceptance'] is False and
            type(row['model_instance']) is int and 0 < row['model_instance'] < 2**64 and
            type(row['sequence']) is int and 0 < row['sequence'] < 2**64,
            'oversized control witness kind/opcode/C-call types differ')
    writeback.hash_hex(row['actual_core_sha256'], 64)
    observed, origin = row['observation'], row['origin']
    require(type(observed) is dict and type(origin) is dict and set(origin) ==
            set('producer_tid source destination command bytes fnv1a64'.split()),
            'oversized control witness original schema differs')
    input_bytes, output_bytes, command = {21: (12, 208, 0x409d), 22: (20, 240, 0x4000),
                                          23: (12, 224, 0x4072)}[op]
    require(all(type(origin[k]) is int and origin[k] == expected for k, expected in
                dict(source=0x80020002, destination=0x90030001, command=command, bytes=input_bytes).items()) and
            type(origin['producer_tid']) is int and 0 < origin['producer_tid'] < 2**31 and
            type(origin['fnv1a64']) is int and 0 <= origin['fnv1a64'] < 2**64,
            'oversized control witness native input/source/destination differs')
    for key, size, direction in (('request_payload', input_bytes, 'in'), ('output_payload', output_bytes, 'out')):
        reference = row[key]
        require(type(reference) is dict and type(reference.get('bytes')) is int and reference['bytes'] == size and
                reference.get('direction') == direction and type(reference.get('opcode')) is int and reference['opcode'] == op and
                type(reference.get('sequence')) is int and reference['sequence'] == row['sequence'] and
                type(reference.get('model_instance')) is int and reference['model_instance'] == row['model_instance'] and
                typed_equal(reference.get('origin'), origin), 'oversized control witness payload identity/length differs')
    packet = raw_hex(observed, 'request_hex', input_bytes)
    raw = raw_hex(observed, 'returned_hex', output_bytes)
    prior = raw_hex(observed, 'before_state_hex', 128)
    buffer = observed.get('output_buffer_hex')
    require(type(buffer) is str and len(buffer) % 2 == 0 and 2 * output_bytes <= len(buffer) <= 2 * DATA_BYTES,
            'oversized control witness C buffer capacity differs')
    capacity = len(buffer) // 2
    require(origin['fnv1a64'] == fnv(packet), 'oversized control witness whole original input differs')
    if op == 21:
        cp_crank_control_observation(observed, raw, packet, row['model_instance'], prior,
                                     observed.get('bank_generation'), capacity)
    elif op == 22:
        require(row['admission_error'] is None and type(row['error']) is int and row['error'] == 0 and
                raw_hex(row, 'input_hex', 20) == packet and type(row['request_fnv1a64']) is int and
                row['request_fnv1a64'] == fnv(packet), 'movie format broker original input/error binding differs')
        cp_movie_format_observation(observed, raw, packet, row['model_instance'], prior,
                                    observed.get('bank_generation'), observed.get('crank_generation'), capacity)
    else:
        require(row['admission_error'] is None and row['validation_error'] is None and
                type(row['error']) is int and row['error'] == 0 and raw_hex(row, 'input_hex', 12) == packet and
                type(row['request_fnv1a64']) is int and row['request_fnv1a64'] == fnv(packet),
                'OU crank broker original input/error binding differs')
        cp_ou_crank_control_observation(observed, raw, packet, row['model_instance'], prior,
            observed.get('bank_generation'), observed.get('crank_generation'), observed.get('movie_generation'), capacity)
    return True


def jsonl(raw):
    require(raw and len(raw) <= MAX_LOG and raw.endswith(b'\n'), 'empty/truncated broker JSONL')
    rows = []
    last_time = 0
    for index, line in enumerate(raw.splitlines(), 1):
        require(index <= MAX_EVENTS and len(line) <= 2 * 1024**2, 'broker event/line budget exceeded')
        row = object_json(line)
        source = (row.get('kind') in ('ap_source_result', 'response') and row.get('opcode') == 11 and
                  row.get('actual_c_result', 1) is None and
                  row.get('source_provider_kind') == 'paused-source-snapshot-v1')
        control = (type(row.get('opcode')) is int and
                   (row.get('opcode'), row.get('kind')) in ((21, 'model_crank_control'), (22, 'model_movie_format'),
                                                           (23, 'model_ou_crank_control')))
        require(len(line) <= 16384 or source or len(line) <= 192 * 1024 and control and bounded_control_witness(row),
                'oversized non-source broker event')
        require(type(row.get('event')) is int and row['event'] == index and
                uint(row.get('monotonic_ns')) >= last_time, 'broker event sequence/time differs')
        last_time = row['monotonic_ns']
        rows.append(row)
    return rows


def vdf_resource_diagnostic(row):
    """Validate only the three tracked_native_reserve_resources grammars; no claims."""
    tag, f = row['tag'], row['fields']
    if tag == 'FUNCTIONAL_VDF_PATH_RESOURCE_DEPENDENCIES':
        schema = dict(pid='tid', tid='tid', accepted='1', proc_ap_consumed='1', input_ap_consumed='1',
                      output_ap_consumed='1', output_faults='0', current_request_retained_expected='1', capture_verified='0')
    elif tag == 'FUNCTIONAL_VDF_PATH_RESOURCES_TTS_TABLE':
        schema = dict(pid='tid', tid='tid', appfw_base='hex64', table_va='0x5f66b08', address='hex64',
                      bytes='144', reads='144/144', unchanged='1', atomic_snapshot='0',
                      raw_before='raw144', raw_after='raw144', ownership_verified='0')
    elif tag == 'FUNCTIONAL_VDF_PATH_RESOURCES_RESERVED':
        schema = dict.fromkeys(('dmm_allocation_count allocations releases connections connection_reply_frees').split(), 'u64')
        schema.update(dict.fromkeys(('dmm_domain vef_objects pinmem_objects').split(), 'u32'))
        schema.update(dict.fromkeys(('dmm_enabled dmm_bound dmm_lifecycle_changed foreign_speech_kept control_bound '
                                     'connection_started format_consumed buffer_released vef_init pinmem_init').split(), 'bit'))
        schema.update(dict.fromkeys(('data_frozen control_live control_faults format_pending blocked connection_faults '
                                     'vef_pending vef_live vef_retained vef_faults pinmem_pending pinmem_live '
                                     'pinmem_retained pinmem_faults global_dmm_idle_verified original_cp_executed capture_verified').split(), '0'))
        schema.update(dict(tid='tid', accepted='1', dmm_slots='bit/bit', dmm_opens='u32/u32',
                           dmm_handles='hex32/hex32', dmm_generations='u32/u32', dmm_epochs='u64/u64',
                           dmm_creators='u32/u32', vef_owner='hex32', pinmem_owner='hex32'))
    else:
        return False
    require(set(f) == set(schema) and 'diagnostic' not in row, 'VDF resource diagnostic fields differ')
    for key, grammar in schema.items():
        parts, kinds = f[key].split('/'), grammar.split('/')
        require(len(parts) == len(kinds), 'VDF resource diagnostic tuple differs: ' + key)
        for text, kind in zip(parts, kinds):
            if kind in ('tid', 'u32', 'u64', 'hex32', 'hex64'):
                pattern = r'(?:0|0x[1-9a-f][0-9a-f]*)' if kind.startswith('hex') else r'(?:0|[1-9][0-9]*)'
                require(re.fullmatch(pattern, text), 'VDF resource diagnostic number grammar differs: ' + key)
                value = number(text)
                require(value < 2**(64 if kind in ('u64', 'hex64') else 31 if kind == 'tid' else 32) and
                        (kind != 'tid' or value > 0), 'VDF resource diagnostic number range differs: ' + key)
            elif kind == 'bit':
                require(text in ('0', '1'), 'VDF resource diagnostic boolean differs: ' + key)
            elif kind == 'raw144':
                raw_hex(f, key, 144)
            else:
                require(text == kind, 'VDF resource diagnostic literal differs: ' + key)
    if tag == 'FUNCTIONAL_VDF_PATH_RESOURCES_TTS_TABLE':
        base = number(f['appfw_base'])
        require(0x10000 <= base < 0x7ff0000000 and number(f['address']) == base + 0x5f66b08 and
                f['raw_before'] == f['raw_after'], 'VDF TTS diagnostic address/read observations differ')
    return True


def bb_config(canonical):
    require(len(canonical) == 32, 'BB typed envelope must be exactly32 bytes')
    command, size = struct.unpack_from('<2H', canonical)
    body = canonical[4:]
    require(command in BB_COMMANDS and size == BB_COMMANDS[command] - 8 and body[size:] == bytes(28 - size),
            'BB original command/body count/virtual padding differs')
    if command == 0x111:
        valid = body == bytes.fromhex('00000f02') + bytes(24)
    elif command == 0x166:
        valid = body in (b'\x00\x01' + bytes(26), bytes.fromhex(BB_POLICY['bb_startup_0166_observed_initial_body_hex']))
    elif command == 0x167:
        valid = struct.unpack_from('<H', body)[0] in (0, 1)
    elif command == 0x15f:
        valid = body == bytes(28)
    else:
        valid = (body[:4] == b'\x00\x01\x00\x00' and
                 struct.unpack_from('<I', body, 4)[0] in (60, 50, 40, 30, 20, 10, 9, 8, 7, 6, 5, 4, 3, 2, 1) and
                 body[8:] == bytes(20))
    require(valid, 'BB unsupported enabled/nonneutral software configuration')
    return command


def startup_control_config(canonical):
    require(len(canonical) == 32, 'Startup control canonical must be exactly32 bytes')
    command, size = struct.unpack_from('<2H', canonical)
    require((command == 0x4014 and size == 16 and canonical[4:20] == STARTUP_CONTROL_MODE_BODY or
             command == 0x4057 and size == 4 and canonical[4:20] == bytes(16) or
             command == 0x403f and size == 8 and canonical[4:20] == bytes(16)) and
            canonical[20:24] == bytes(4), 'Startup control unsupported command/body/reserved bytes')
    return command


def vdf_result(raw, canonical, instance, opcode=5, route=None):
    """Parse the exact opcode-specific configuration result and current RGB route."""
    require(opcode in CONFIG_OPERATIONS, 'unknown VDF/BB/histogram configuration opcode')
    size = CONFIG_OPERATIONS[opcode][1]
    require(len(raw) == size and struct.unpack_from('<2I', raw) == (1, size),
            'VDF result size differs from its actual opcode')
    if opcode in (6, 7, 8, 9, 10, 12, 13, 14):
        if opcode == 14:
            startup_control_config(canonical)
            require(raw[160:] == canonical, 'Startup control independent canonical32/save/readback differs')
        elif opcode == 13:
            require(canonical == STILL_FORMAT_CANONICAL and raw[160:] == canonical,
                    'Still format canonical16/independent saved readback differs')
        elif opcode == 12:
            require(canonical == bytes(8) and raw[160:] == canonical,
                    'Bit width selector0 canonical8/independent saved readback differs')
        elif opcode == 9:
            bb_config(canonical)
            require(raw[160:] == canonical, 'BB independent canonical32/save/readback differs')
        elif opcode == 10:
            require(canonical == HIST_CANONICAL and raw[160:168] == canonical,
                    'Histogram first enable1/mode1 canonical8/readback differs')
            require(all(max(raw[168 + c * 256:424 + c * 256]) == 255 for c in range(4)),
                    'Histogram empty/non-peak-normalized software channel')
        elif opcode == 6:
            require(len(canonical) == 8 and canonical[1] == 0 and canonical[5:] == bytes(3) and
                    raw[160:] == canonical, 'Zebra disabled canonical8/save/readback differs')
        elif opcode == 7:
            require(canonical == bytes.fromhex(LAYOUT_POLICY['layout_initial_body_hex']) and
                    raw[160:] == canonical, 'Layout initial canonical32/save/readback differs')
        else:
            require(len(canonical) == 16, 'Display typed envelope must be exactly16 bytes')
            command, body_bytes = struct.unpack_from('<2I', canonical)
            body = canonical[8:]
            require((command == 0x141 and body_bytes == 0 and body == bytes(8)) or
                    (command == 0x152 and body_bytes == 8 and body[0] == 3 and body[1] == 0 and
                     body[2] <= 2 and body[3] in (0, 10, 40) and body[4] == 0 and
                     tuple(body[5:]) in ((81, 90, 240), (210, 16, 146), (29, 255, 83), (235, 128, 128))) or
                    (command == 0x162 and body_bytes == 2 and body == bytes(8)) or
                    (command == 0x163 and body_bytes == 6 and body == bytes(8)) or
                    (command == 0x170 and body_bytes == 4 and all(value <= 1 for value in body[:3]) and
                     body[3:] == bytes(5)),
                    'Display unsupported command/body/enabled feature')
            require(raw[160:] == canonical, 'Display independent canonical16/save/readback differs')
        require(route is not None and raw[128:144] == route, 'Zebra/layout/display changed the current committed VDF route')
    else:
        route = canonical
    require(len(route) == 16 and route[:3] in (b'\x01\x05\x05', b'\x00\x01\x01') and
            route[4] <= 2 and route[13:] == bytes(3), 'VDF canonical configuration differs')
    names = ('model_instance', 'config_generation', 'frame_generation', 'lease_generation',
             'input_fnv', 'source_fnv', 'sink_fnv', 'active_bytes')
    value = dict(zip(names, struct.unpack_from('<8Q', raw, 8)))
    names = ('width', 'height', 'stride', 'endpoint', 'selected_mask', 'completed_mask', 'class',
             'enabled', 'config_readback', 'committed', 'frame_consumed', 'retired', 'status', 'reserved')
    value.update(zip(names, struct.unpack_from('<14I', raw, 72)))
    value['before_frame_generation'], value['before_config_generation'] = struct.unpack_from('<2Q', raw, 144)
    active = route[0]
    require(value['model_instance'] == instance and instance > 0 and value['input_fnv'] == fnv(canonical) and
            raw[128:144] == route and value['endpoint'] == 0x90590819 and
            value['selected_mask'] == value['completed_mask'] == value['config_readback'] == value['committed'] == 1 and
            value['class'] == ({9: 5, 10: 6, 12: 7, 13: 8, 14: 9}.get(opcode, active)) and
            value['enabled'] == value['frame_consumed'] == value['retired'] == active and
            value['status'] == value['reserved'] == 0, 'VDF configuration readback/endpoint/commit differs')
    require(0 < value['before_config_generation'] < 2**64 - 1 and
            value['config_generation'] == value['before_config_generation'] + 1 and
            value['frame_generation'] == value['before_frame_generation'] + active and
            0 < value['width'] <= 8192 and 0 < value['height'] <= 8192 and
            value['stride'] == value['width'] * 3, 'VDF configuration/frame generation or geometry differs')
    if opcode in (7, 9, 10, 12, 13, 14):
        require(active == 1 and (value['width'], value['height'], value['stride']) == (640, 480, 1920) and
                value['active_bytes'] == 921600, 'Layout/BB/histogram/bit width requires the active full 640x480 RGB software route')
    if opcode == 8:
        require(active == 1, 'Display refresh/disabled features require a committed active RGB route')
    if active:
        require(value['active_bytes'] == value['width'] * value['height'] * 3 and
                value['source_fnv'] == value['sink_fnv'] != 0 and value['lease_generation'] > 0,
                'VDF active source/sink copy/readback differs')
    else:
        require(all(value[key] == 0 for key in ('active_bytes', 'source_fnv', 'sink_fnv', 'lease_generation')),
                'VDF disabled path invented a consumed frame/lease')
    return value


def cp_parameter_bank_result(raw, packet, instance, prior):
    """Read the functional opaque bank and its actual Config48 FPS projection."""
    require(len(packet) == 2564 and packet[0] == 5 and struct.unpack_from('<H', packet, 2)[0] == 0x4063,
            'parameter bank requires the complete original4063 packet')
    table = (NATIVE / 'runtime/analysis/device-models/cp-parameter-batch.c').read_bytes()
    require(sha(table) == '8f627e77d94d63434e4be7de3d398a1e3865946c44c7244f2b2553a483409a2e',
            'parameter bank strict source layout drift')
    slots = [tuple(int(word, 16) for word in item) for item in re.findall(
        rb'\{(0x[0-9a-f]+),(0x[0-9a-f]+),(0x[0-9a-f]+)\}', table)]
    require(len(slots) == 190, 'parameter bank fixed190 slot table differs')
    end = 8
    for command, offset, size in slots:
        require(offset == end and 8 <= size <= len(packet) - end and packet[offset] == 5 and
                struct.unpack_from('<H', packet, offset + 2)[0] == command,
                'parameter bank original fixed slot header/extent differs')
        end += size
    require(end == len(packet) and len(raw) == 2756 and struct.unpack_from('<2I', raw) == (1, 2756),
            'parameter bank full result size/version differs')
    keys = ('model_instance', 'bank_generation', 'before_config_generation', 'config_generation',
            'input_fnv', 'fps', 'slots', 'raw_bytes', 'reserved')
    value = dict(zip(keys, struct.unpack_from('<5Q4I', raw, 8)))
    state = raw[64:192]
    require(len(prior) == 128 and struct.unpack_from('<I', prior)[0] == 1 and
            prior[104:112] == bytes(8) and prior[120:] == bytes(8) and
            struct.unpack_from('<Q', prior, 48)[0] == instance and
            value['model_instance'] == instance > 0 and 0 < value['bank_generation'] < 2**64 and
            value['before_config_generation'] == struct.unpack_from('<Q', prior, 56)[0] and
            0 < value['before_config_generation'] < 2**64 - 1 and
            value['config_generation'] == value['before_config_generation'] + 1 and
            value['input_fnv'] == fnv(packet) and value['slots'] == 190 and
            value['raw_bytes'] == 2564 and value['reserved'] == 0 and
            value['fps'] == struct.unpack_from('<I', packet, 0x86c)[0] and 0 < value['fps'] <= 120,
            'parameter bank actual identity/generation/input/FPS projection differs')
    expected_state = bytearray(prior)
    struct.pack_into('<I', expected_state, 16, value['fps'])
    struct.pack_into('<Q', expected_state, 56, value['config_generation'])
    require(state == bytes(expected_state) and raw[192:] == packet,
            'parameter bank independent full readback/State128/config/frame differs')
    value['frame_generation'] = struct.unpack_from('<Q', state, 112)[0]
    return value


def cp_crank_control_result(raw, packet, instance, prior, expected_bank_generation):
    """Decode software mode0 against a caller-supplied current legal bank generation."""
    require(isinstance(packet, bytes) and len(packet) == 12 and packet[0] == 5 and
            packet[2:4] == b'\x9d\x40' and packet[8:] == bytes(4),
            'crank control requires full original12 type5/409d mode0')
    require(isinstance(raw, bytes) and len(raw) == 208 and struct.unpack_from('<2I', raw) == (1, 208),
            'crank control full208 result size/version differs')
    require(type(instance) is int and 0 < instance < 2**64 and
            type(expected_bank_generation) is int and 0 < expected_bank_generation < 2**64,
            'crank control needs the current legal instance/bank generation')
    require(isinstance(prior, bytes) and len(prior) == 128,
            'crank control needs the complete live prior State128')
    abi, caps, width, height, fps, quality, aperture, iso, shutter, focus = struct.unpack_from('<8I2Q', prior)
    before = struct.unpack_from('<Q', prior, 56)[0]
    require(abi == 1 and caps == 15 and struct.unpack_from('<Q', prior, 48)[0] == instance and
            0 < before < 2**64 - 1 and prior[104:112] == bytes(8) and prior[120:] == bytes(8) and
            0 < width <= 8192 and 0 < height <= 8192 and 0 < fps <= 120 and 0 < quality <= 100 and
            aperture in (400, 800, 1600) and iso and shutter and (focus == 2**64 - 1 or focus >= 100000) and
            struct.unpack_from('<Q', prior, 64)[0] > 0 and struct.unpack_from('<Q', prior, 112)[0] > 0,
            'crank control prior State128 is uninitialized/busy/streaming/invalid')
    keys = ('model_instance', 'crank_generation', 'bank_generation', 'before_config_generation',
            'config_generation', 'input_fnv', 'mode', 'fps')
    value = dict(zip(keys, struct.unpack_from('<6Q2I', raw, 8)))
    require(value['model_instance'] == instance and value['crank_generation'] > 0 and
            value['bank_generation'] == expected_bank_generation and
            value['before_config_generation'] == before and value['config_generation'] == before + 1 and
            value['input_fnv'] == fnv(packet) and value['mode'] == 0 and value['fps'] == fps,
            'crank control instance/current bank/crank/config generation/input/FPS differs')
    expected = bytearray(prior)
    struct.pack_into('<Q', expected, 56, before + 1)
    require(raw[64:192] == bytes(expected) and raw[192:204] == packet and raw[204:] == bytes(4),
            'crank control full12 readback/reserved/State128/config/frame/counters differs')
    value['frame_generation'] = struct.unpack_from('<Q', prior, 112)[0]
    return value


def cp_crank_control_observation(observed, raw, packet, instance, prior, expected_bank_generation, capacity):
    """The actual C output, independent getter and both live STATE queries must agree."""
    keys = {'actual_c_result', 'returned_hex', 'readback_verified', 'model_called', 'model_committed',
            'request_hex', 'before_state_c_result', 'before_state_hex', 'result', 'output_buffer_hex',
            'after_state_c_result', 'after_state_hex', 'query_c_result', 'crank_generation',
            'bank_generation', 'snapshot_hex'}
    require(type(observed) is dict and set(observed) == keys and observed['readback_verified'] is True and
            observed['model_called'] is True and observed['model_committed'] is True and
            all(type(observed[k]) is int and observed[k] == 0 for k in
                ('actual_c_result', 'query_c_result', 'before_state_c_result', 'after_state_c_result')) and
            typed_equal(observed['result'], dict(token=0, total=0, offset=0, used=208)),
            'crank control independent actual C query/readback missing or failed')
    require(type(capacity) is int and 208 <= capacity <= DATA_BYTES and
            raw_hex(observed, 'returned_hex', 208) == raw_hex(observed, 'snapshot_hex', 208) == raw and
            raw_hex(observed, 'request_hex', 12) == packet and
            raw_hex(observed, 'before_state_hex', 128) == prior and
            raw_hex(observed, 'after_state_hex', 128) == raw[64:192] and
            raw_hex(observed, 'output_buffer_hex', capacity) == raw + bytes(capacity - 208),
            'crank control independent request/full208/fullSTATE/output buffer bytes differ')
    value = cp_crank_control_result(raw, packet, instance, prior, expected_bank_generation)
    require(all(type(observed[k]) is int and observed[k] == value[k] for k in
                ('crank_generation', 'bank_generation')),
            'crank control independent query generation differs')
    return value


def cp_movie_format_result(raw, packet, instance, prior, expected_bank_generation, expected_crank_generation):
    """Decode the declared format5/rate1,0 software route; opaque bytes remain exact."""
    require(type(packet) is bytes and len(packet) == 20 and packet[0] == 5 and packet[2:4] == b'\x00\x40' and
            packet[8:11] == b'\x05\x01\0' and packet[12:18] == bytes(6) and packet[18] == 1,
            'movie format requires full original20 type5/4000 supported selectors')
    require(type(raw) is bytes and len(raw) == 240 and struct.unpack_from('<2I', raw) == (1, 240),
            'movie format full240 result size/version differs')
    require(all(type(value) is int and 0 < value < 2**64 for value in
                (instance, expected_bank_generation, expected_crank_generation)),
            'movie format needs the current legal instance/bank/crank generation')
    require(type(prior) is bytes and len(prior) == 128, 'movie format needs the complete live prior State128')
    abi, caps, width, height, fps, quality, aperture, iso, shutter, focus = struct.unpack_from('<8I2Q', prior)
    before = struct.unpack_from('<Q', prior, 56)[0]
    require(abi == 1 and caps == 15 and struct.unpack_from('<Q', prior, 48)[0] == instance and
            0 < before < 2**64 - 1 and prior[104:112] == bytes(8) and prior[120:] == bytes(8) and
            0 < width <= 8192 and 0 < height <= 8192 and 0 < fps <= 120 and 0 < quality <= 100 and
            aperture in (400, 800, 1600) and iso and shutter and (focus == 2**64 - 1 or focus >= 100000) and
            struct.unpack_from('<Q', prior, 64)[0] > 0 and struct.unpack_from('<Q', prior, 112)[0] > 0,
            'movie format prior State128 is uninitialized/busy/streaming/invalid')
    keys = ('model_instance', 'movie_generation', 'bank_generation', 'crank_generation',
            'before_config_generation', 'config_generation', 'input_fnv', 'format', 'rate', 'fps', 'codec')
    value = dict(zip(keys, struct.unpack_from('<7Q4I', raw, 8)))
    require(value['model_instance'] == instance and value['movie_generation'] > 0 and
            value['bank_generation'] == expected_bank_generation and value['crank_generation'] == expected_crank_generation and
            value['before_config_generation'] == before and value['config_generation'] == before + 1 and
            value['input_fnv'] == fnv(packet) and (value['format'], value['rate'], value['fps'], value['codec']) == (5, 0, fps, 1),
            'movie format instance/current bank/crank/config generation/input/FPS/software mapping differs')
    expected = bytearray(prior)
    struct.pack_into('<Q', expected, 56, before + 1)
    require(raw[80:208] == bytes(expected) and raw[208:228] == packet and raw[228:] == bytes(12),
            'movie format full20 readback/reserved/State128/config/frame/counters differs')
    value['frame_generation'] = struct.unpack_from('<Q', prior, 112)[0]
    return value


def cp_movie_format_observation(observed, raw, packet, instance, prior,
                                expected_bank_generation, expected_crank_generation, capacity):
    keys = {'actual_c_result', 'returned_hex', 'readback_verified', 'model_called', 'model_committed',
            'request_hex', 'before_state_c_result', 'before_state_hex', 'result', 'output_buffer_hex',
            'after_state_c_result', 'after_state_hex', 'query_c_result', 'movie_generation',
            'bank_generation', 'crank_generation', 'snapshot_hex', 'input_hex', 'input_fnv1a64',
            'returned_bytes', 'returned_fnv1a64'}
    require(type(observed) is dict and set(observed) == keys and observed['readback_verified'] is True and
            observed['model_called'] is True and observed['model_committed'] is True and
            all(type(observed[k]) is int and observed[k] == 0 for k in
                ('actual_c_result', 'query_c_result', 'before_state_c_result', 'after_state_c_result')) and
            typed_equal(observed['result'], dict(token=0, total=0, offset=0, used=240)),
            'movie format independent actual C query/readback missing or failed')
    require(type(capacity) is int and 240 <= capacity <= DATA_BYTES and
            raw_hex(observed, 'returned_hex', 240) == raw_hex(observed, 'snapshot_hex', 240) == raw and
            raw_hex(observed, 'request_hex', 20) == raw_hex(observed, 'input_hex', 20) == packet and
            type(observed['input_fnv1a64']) is int and observed['input_fnv1a64'] == fnv(packet) and
            type(observed['returned_bytes']) is int and observed['returned_bytes'] == 240 and
            type(observed['returned_fnv1a64']) is int and observed['returned_fnv1a64'] == fnv(raw) and
            raw_hex(observed, 'before_state_hex', 128) == prior and
            raw_hex(observed, 'after_state_hex', 128) == raw[80:208] and
            raw_hex(observed, 'output_buffer_hex', capacity) == raw + bytes(capacity - 240),
            'movie format independent request/full240/fullSTATE/output buffer bytes differ')
    value = cp_movie_format_result(raw, packet, instance, prior, expected_bank_generation, expected_crank_generation)
    require(all(type(observed[k]) is int and observed[k] == value[k] for k in
                ('movie_generation', 'bank_generation', 'crank_generation')),
            'movie format independent query generation differs')
    return value


def cp_ou_crank_control_result(raw, packet, instance, prior, expected_bank_generation,
                               expected_crank_generation, expected_movie_generation):
    """Decode exact OuCrank224; the current tuple and all State128 bytes are binding."""
    require(type(packet) is bytes and len(packet) == 12 and packet[0] == 5 and
            packet[2:4] == b'\x72\x40' and packet[8:] == bytes(4),
            'OU crank requires full original12 type5/4072 mode0')
    require(type(raw) is bytes and len(raw) == 224 and struct.unpack_from('<2I', raw) == (1, 224),
            'OU crank full224 result size/version differs')
    require(all(type(value) is int and 0 < value < 2**64 for value in
                (instance, expected_bank_generation, expected_crank_generation, expected_movie_generation)),
            'OU crank needs the current legal instance/bank/crank/movie tuple')
    require(type(prior) is bytes and len(prior) == 128, 'OU crank needs the complete live prior State128')
    abi, caps, width, height, fps, quality, aperture, iso, shutter, focus = struct.unpack_from('<8I2Q', prior)
    before = struct.unpack_from('<Q', prior, 56)[0]
    require(abi == 1 and caps == 15 and struct.unpack_from('<Q', prior, 48)[0] == instance and
            0 < before < 2**64 - 1 and prior[104:112] == bytes(8) and prior[120:] == bytes(8) and
            0 < width <= 8192 and 0 < height <= 8192 and 0 < fps <= 120 and 0 < quality <= 100 and
            aperture in (400, 800, 1600) and iso and shutter and (focus == 2**64 - 1 or focus >= 100000) and
            struct.unpack_from('<Q', prior, 64)[0] > 0 and struct.unpack_from('<Q', prior, 112)[0] > 0,
            'OU crank prior State128 is uninitialized/busy/streaming/invalid')
    keys = ('model_instance', 'ou_generation', 'bank_generation', 'crank_generation', 'movie_generation',
            'before_config_generation', 'config_generation', 'input_fnv', 'mode', 'fps')
    value = dict(zip(keys, struct.unpack_from('<8Q2I', raw, 8)))
    require(value['model_instance'] == instance and value['ou_generation'] > 0 and
            value['bank_generation'] == expected_bank_generation and value['crank_generation'] == expected_crank_generation and
            value['movie_generation'] == expected_movie_generation and value['before_config_generation'] == before and
            value['config_generation'] == before + 1 and value['input_fnv'] == fnv(packet) and
            value['mode'] == 0 and value['fps'] == fps, 'OU crank current tuple/config generation/input/FPS differs')
    expected = bytearray(prior)
    struct.pack_into('<Q', expected, 56, before + 1)
    require(raw[80:208] == bytes(expected) and raw[208:220] == packet and raw[220:] == bytes(4),
            'OU crank full12 readback/reserved/State128/config/frame/counters differs')
    value['frame_generation'] = struct.unpack_from('<Q', prior, 112)[0]
    return value


def cp_ou_crank_control_observation(observed, raw, packet, instance, prior,
                                    expected_bank_generation, expected_crank_generation, expected_movie_generation, capacity):
    # functional_camera_broker.Core.execute keeps actual C0 separate from postvalidation.
    keys = {'actual_c_result', 'returned_hex', 'readback_verified', 'model_called', 'model_committed',
            'input_hex', 'request_hex', 'input_fnv1a64', 'software_mode', 'validation_error', 'ou_generation',
            'bank_generation', 'crank_generation', 'movie_generation', 'predecessor_proof',
            'before_state_c_result', 'before_state_hex', 'c_call_succeeded', 'returned_bytes', 'returned_fnv1a64',
            'output_buffer_hex', 'result', 'after_state_c_result', 'after_state_hex', 'query_c_result', 'snapshot_hex',
            'state_delta_verified'}
    require(type(observed) is dict and set(observed) == keys and all(observed[key] is True for key in
                ('readback_verified', 'model_called', 'model_committed', 'c_call_succeeded', 'state_delta_verified')) and
            observed['software_mode'] == 'ou_crank_mode0' and observed['validation_error'] is None and
            type(observed['predecessor_proof']) is dict and
            all(type(observed[key]) is int and observed[key] == 0 for key in
                ('actual_c_result', 'query_c_result', 'before_state_c_result', 'after_state_c_result')) and
            typed_equal(observed['result'], dict(token=0, total=0, offset=0, used=224)),
            'OU crank independent actual C query/readback missing or failed')
    require(type(capacity) is int and 224 <= capacity <= DATA_BYTES and
            raw_hex(observed, 'returned_hex', 224) == raw_hex(observed, 'snapshot_hex', 224) == raw and
            raw_hex(observed, 'request_hex', 12) == raw_hex(observed, 'input_hex', 12) == packet and
            type(observed['input_fnv1a64']) is int and observed['input_fnv1a64'] == fnv(packet) and
            type(observed['returned_bytes']) is int and observed['returned_bytes'] == 224 and
            type(observed['returned_fnv1a64']) is int and observed['returned_fnv1a64'] == fnv(raw) and
            raw_hex(observed, 'before_state_hex', 128) == prior and raw_hex(observed, 'after_state_hex', 128) == raw[80:208] and
            raw_hex(observed, 'output_buffer_hex', capacity) == raw + bytes(capacity - 224),
            'OU crank independent request/full224/fullSTATE/output buffer bytes differ')
    value = cp_ou_crank_control_result(raw, packet, instance, prior,
        expected_bank_generation, expected_crank_generation, expected_movie_generation)
    require(all(type(observed[key]) is int and observed[key] == value[key] for key in
                ('ou_generation', 'bank_generation', 'crank_generation', 'movie_generation')),
            'OU crank independent query tuple/generation differs')
    return value


def vdf_history(run, transport):
    """Join display commits to the actual latest state/job and unchanged route."""
    route, config, generation, geometry = b'\x00\x01\x01' + bytes(13), None, None, None
    parameters, preserve_parameters, last_lease, last_state = None, False, 0, None
    current_bank, last_crank, consumed_bank = None, 0, 0
    current_crank, last_movie, movie_pairs = None, 0, set()
    current_movie, current_settings, last_ou, ou_tuples = None, None, 0, set()
    optical_retained = False
    values = {}
    for tx in transport['transfers']:
        op = tx['opcode']
        if op in (1, 2, 3, 32, 66):
            raw = transfer_output(run, tx)
            require(len(raw) == 128 and struct.unpack_from('<I', raw)[0] == 1 and
                    struct.unpack_from('<Q', raw, 48)[0] == transport['model_instance'],
                    'VDF history State128 identity/size differs')
            changed_config = op in (3, 32) or op == 1 and tx['request_payload']['bytes'] == 48
            if preserve_parameters and not changed_config:
                require(raw[8:48] == parameters and struct.unpack_from('<Q', raw, 56)[0] == config,
                        'Zebra/layout/repeated INIT changed Config48 camera parameters or configuration generation')
            if changed_config:
                preserve_parameters = False
            parameters = raw[8:48]
            config, generation = struct.unpack_from('<Q', raw, 56)[0], struct.unpack_from('<Q', raw, 112)[0]
            geometry = struct.unpack_from('<2I', raw, 8)
            last_state = raw
        elif op == 20:
            raw = transfer_output(run, tx)
            packet = payload_read(run, tx['request_payload'])
            value = cp_parameter_bank_result(raw, packet, transport['model_instance'], last_state or b'')
            require(value['before_config_generation'] == config and value['frame_generation'] == generation and
                    tx['token'] == 0 and tx.get('frame') is None,
                    'parameter bank lacks latest STATE or borrowed a frame/retained result')
            last_state, config = raw[64:192], value['config_generation']
            parameters, preserve_parameters = last_state[8:48], False
            current_bank = value
            values[tx['first']] = value
        elif op == 21:
            require(current_bank is not None, 'crank control has no decoded current parameter bank')
            raw = transfer_output(run, tx)
            packet = payload_read(run, tx['request_payload'])
            value = cp_crank_control_result(raw, packet, transport['model_instance'], last_state or b'',
                                            current_bank['bank_generation'])
            require(value['before_config_generation'] == config and value['frame_generation'] == generation and
                    value['fps'] == current_bank['fps'] and value['crank_generation'] == last_crank + 1 and
                    value['bank_generation'] != consumed_bank and tx['token'] == 0 and tx.get('frame') is None,
                    'crank control current bank/FPS/once-only history or no-frame binding differs')
            last_crank, consumed_bank = value['crank_generation'], value['bank_generation']
            last_state, config = raw[64:192], value['config_generation']
            parameters = last_state[8:48]
            current_crank = value
            values[tx['first']] = value
        elif op == 22:
            require(current_bank is not None and current_crank is not None and
                    current_crank['bank_generation'] == current_bank['bank_generation'],
                    'movie format has no decoded current parameter bank/crank pair')
            require(tx.get('frame') is None and tx['token'] == 0 and not optical_retained,
                    'movie format borrowed a frame proof or retained result/optical frame')
            raw, packet = transfer_output(run, tx), payload_read(run, tx['request_payload'])
            value = cp_movie_format_result(raw, packet, transport['model_instance'], last_state or b'',
                current_bank['bank_generation'], current_crank['crank_generation'])
            pair = (value['bank_generation'], value['crank_generation'])
            require(value['before_config_generation'] == config and value['frame_generation'] == generation and
                    value['fps'] == current_bank['fps'] and value['movie_generation'] == last_movie + 1 and
                    pair not in movie_pairs, 'movie format current bank/crank/FPS/once-only history differs')
            movie_pairs.add(pair)
            last_movie = value['movie_generation']
            last_state, config = raw[80:208], value['config_generation']
            parameters = last_state[8:48]
            current_movie = value
            values[tx['first']] = value
        elif op == 23:
            require(current_bank is not None and current_crank is not None and current_movie is not None and
                    current_crank['bank_generation'] == current_movie['bank_generation'] == current_bank['bank_generation'] and
                    current_movie['crank_generation'] == current_crank['crank_generation'],
                    'OU crank has no decoded current bank/crank/movie tuple')
            require(tx.get('frame') is None and tx['token'] == 0 and not optical_retained,
                    'OU crank borrowed a frame proof or retained result/optical frame')
            raw, packet = transfer_output(run, tx), payload_read(run, tx['request_payload'])
            value = cp_ou_crank_control_result(raw, packet, transport['model_instance'], last_state or b'',
                current_bank['bank_generation'], current_crank['crank_generation'], current_movie['movie_generation'])
            identity = (value['bank_generation'], value['crank_generation'], value['movie_generation'])
            require(current_settings is not None and current_settings['config_generation'] == config and
                    current_settings['config_generation'] > current_movie['config_generation'] and
                    current_settings['frame_generation'] == generation,
                    'OU crank requires the current committed4057 configuration/frame checkpoint')
            require(value['before_config_generation'] == config and value['frame_generation'] == generation and
                    value['fps'] == current_bank['fps'] and value['ou_generation'] == last_ou + 1 and
                    identity not in ou_tuples, 'OU crank current tuple/FPS/once-only history differs')
            ou_tuples.add(identity)
            last_ou, last_state, config = value['ou_generation'], raw[80:208], value['config_generation']
            parameters = last_state[8:48]
            values[tx['first']] = value
        elif op in CONFIG_OPERATIONS:
            raw = transfer_output(run, tx)
            canonical = payload_read(run, tx['request_payload'])
            value = vdf_result(raw, canonical, transport['model_instance'], op, route)
            if op == 14:
                require(parameters is not None and struct.unpack_from('<Q', canonical, 24)[0] == fnv(parameters),
                        'Startup control fingerprint differs from actual State128 config40')
            require(value['before_config_generation'] == config and value['before_frame_generation'] == generation and
                    (value['width'], value['height']) == geometry and tx['token'] == 0,
                    'VDF before generations/geometry differ from actual model history')
            require(not value['enabled'] or value['lease_generation'] > last_lease,
                    'VDF reused an old rendered RGB lease')
            values[tx['first']] = value
            config, generation, route = value['config_generation'], value['frame_generation'], raw[128:144]
            if op == 14 and startup_control_config(canonical) == 0x4057:
                current_settings = value
            preserve_parameters = preserve_parameters or op in (6, 7, 8, 9, 10, 12, 13, 14)
        elif op == 4:
            preserve_parameters = False
        elif op not in (18, 19) and tx.get('frame') is not None:
            proof = tx['frame']['proof']
            config, generation = proof['config_generation'], proof['frame_generation']
        if op == 17:
            optical_retained = True
        elif op in (19, 66):
            optical_retained = False
        if op != 17 and tx.get('frame') is not None and tx['frame']['proof']['render_observed']:
            last_lease = tx['frame']['proof']['lease_generation']
    return values


def noncodec_proof(tx, value, transport, output):
    """Kinds4/5/6 are explicit RGB configuration/data work, never codecs."""
    event = tx.get('frame')
    needed(type(event) is dict and type(event.get('proof')) is dict, 'actual noncodec RGB proof required')
    p, active = event['proof'], value['enabled']
    kind = {5: 4, 6: 4, 7: 4, 8: 4, 9: 5, 10: 6, 12: 4, 13: 4, 14: 4}.get(tx['opcode'])
    # OP12/13/14 use VDF kind4 but cache the complete typed configuration receipt.
    result = output if tx['opcode'] in (9, 10, 12, 13, 14) else b''
    require(kind is not None and p['version'] == 1 and p['struct_bytes'] == 376 and
            p['operation_status'] == 0 and p['model_lifetime'] > 0 and p['opcode'] == tx['opcode'] and
            p['consumer_kind'] == kind and p['model_instance'] == transport['model_instance'] and
            p['owner_pid'] == transport['owner_pid'] and p['config_generation'] == value['config_generation'] and
            p['frame_generation'] == value['frame_generation'] and p['lease_generation'] == value['lease_generation'] and
            p['source_fnv1a64'] == p['consumer_before_fnv1a64'] == value['source_fnv'] and
            p['consumer_after_fnv1a64'] == value['sink_fnv'] and p['active_bytes'] == value['active_bytes'] and
            p['render_observed'] == p['consumer_entered'] == p['consumer_returned'] == p['retired'] == active and
            p['encoder_consumed'] == p['encoded_bytes'] == p['result_token'] == 0 and
            p['encoded_fnv1a64'] == fnv(b'') and p['result_bytes'] == len(result) and
            p['result_fnv1a64'] == fnv(result) and tx['token'] == 0 and
            {key: p['after'][key] - p['before'][key] for key in p['before']} ==
            dict(rendered=active, consumed=active, retired=active, jpeg_encoded=0, video_encoded=0),
            'actual noncodec source/sink/frame/result/counters differ')
    require(p['final_state'] == 1 and
            p['render_status'] == p['consumer_status'] == p['retire_status'] == (0 if active else -61),
            'actual noncodec render/copy/retire status differs')
    if active:
        require((p['width'], p['height'], p['stride']) == (value['width'], value['height'], value['stride']) and
                p['source_state'] == 3 and p['consumer_before_state'] == p['consumer_after_state'] == 4,
                'actual noncodec reading lease/geometry differs')
    else:
        require(all(p[key] == 0 for key in ('width', 'height', 'stride', 'source_state',
                    'consumer_before_state', 'consumer_after_state')), 'idle configuration invented a frame')
    return p


def vdf_refresh_queue_binding(row, transport, origin, *, histogram=False):
    """Only the two source-defined global queues can authorize non81cf sources."""
    f = row['fields']
    fields = ('pid tid caller_pc global_va global_address source read_before read_after first second '
              'bind_rc source_match readback_verified capture_verified').split()
    require(set(f) == set(fields) and 'diagnostic' not in row, 'VDF refresh binding producer grammar differs')
    n = {}
    for key in ('pid', 'tid', 'caller_pc', 'global_va', 'global_address', 'source', 'first', 'second'):
        pattern = r'[1-9][0-9]*' if key in ('pid', 'tid') else r'(?:0|0x[1-9a-f][0-9a-f]*)'
        require(re.fullmatch(pattern, f[key]), 'VDF refresh binding number grammar differs: ' + key)
        n[key] = number(f[key])
        maximum = 2**31 if key in ('pid', 'tid') else 2**32 if key in ('source', 'first', 'second') else 2**64
        require(n[key] < maximum, 'VDF refresh binding number range differs: ' + key)
    caller_va, global_va = (0x34e53ac, 0x910fa20) if histogram else (0x34e4f3c, 0x910fa30)
    base = n['caller_pc'] - caller_va
    require(0x10000 <= base < 0x7ff0000000 and n['global_va'] == global_va and
            n['global_address'] == base + global_va, 'VDF/histogram original caller/global offsets differ')
    require(n['pid'] == transport['pid'] and n['tid'] == origin['producer_tid'] and
            0 < n['source'] < 2**32 - 1 and n['source'] != 0x92840747 and
            n['first'] == n['second'] == n['source'] == origin['source'],
            'VDF refresh original owner/global/request source differs')
    require(all(f[key] == value for key, value in dict(read_before='4', read_after='4', bind_rc='0',
            source_match='1', readback_verified='1', capture_verified='0').items()),
            'VDF refresh short/failed global read or bind/scope promotion')
    return n['source']


def check_vdf_path(run, rows, transport):
    """Join all display commits to their exact original command and actual ACK receive/free."""
    transfers = [tx for tx in transport['transfers'] if tx['opcode'] in VDF_OPERATIONS]
    records, diagnostics, bindings = [], [], []
    binding_tag = 'FUNCTIONAL_VDF_REFRESH_QUEUE_BOUND'
    tags = {name: 'FUNCTIONAL_VDF_PATH_' + name for name in ('REQUEST_FREE', 'SEND', 'COMPLETE', 'RECEIVE', 'AP_FREE')}
    for row in rows:
        if row['tag'] == binding_tag:
            bindings.append(row)
        elif row['tag'].startswith('FUNCTIONAL_VDF_'):
            if vdf_resource_diagnostic(row):
                diagnostics.append(row)
            else:
                require(row['tag'] in tags.values(), 'failed/unknown VDF native receipt')
                records.append(row)
    native_opcodes = {command: op for op, (commands, _) in VDF_OPERATIONS.items() for command in commands}
    require(all(type(tx['opcode']) is int and tx['opcode'] in (1, 12) for tx in transport['transfers']
                if tx['origin']['destination'] == 0x92840747 and tx['origin']['command'] == 0x15e),
            'VDF original015e was relabelled as a media/configuration operation')
    original = any(tx['origin']['destination'] == 0x92840747 and tx['origin']['command'] in native_opcodes
                   for tx in transport['transfers'])
    if not (transfers or records or original or bindings):
        return {'required': False, 'verified': False, 'cycles': [], 'diagnostics': diagnostics}
    needed(transfers and records, 'VDF op5/op6/op7/op8/BB9/op12 and their original receive/free receipts required together')
    refreshes = [tx for tx in transfers if tx['origin']['command'] == 0x141]
    needed(len(bindings) >= len(refreshes), 'VDF each original0141 requires its own refresh queue binding receipt')
    require(len(bindings) == len(refreshes), 'VDF refresh binding/original0141 census differs')
    required = set(('pid tid phase cycle requests completed_cycles busy guard source destination command bytes '
        'model_instance config_generation before_config_generation frame_generation before_frame_generation '
        'lease_generation ack_retained queued received AP_consumed send_inflight sender_tid receiver_tid free_tid').split())
    groups = {}
    for row in records:
        missing = sorted(required - row['fields'].keys())
        needed('diagnostic' not in row and not missing,
               f'VDF {row["tag"]} line {row["line"]}: missing ' + (','.join(missing) or 'complete original formatter') +
               ('; diagnostic=' + row['diagnostic'] if 'diagnostic' in row else ''))
        cycle = number(row['fields']['cycle'])
        group = groups.setdefault(cycle, {})
        require(cycle > 0 and row['tag'] not in group, 'VDF duplicate/zero/old cycle receipt')
        group[row['tag']] = row
    require(list(groups) == list(range(1, len(groups) + 1)) and len(groups) == len(transfers),
            'VDF original cycle/op5/op6/op7/op8/BB9/op12 census differs')
    history = vdf_history(run, transport)
    previous_line, checked, refresh_source = 0, [], None
    refresh_bindings = iter(bindings)
    for (cycle, group), tx in zip(groups.items(), transfers):
        needed(set(group) == set(tags.values()), 'VDF REQUEST_FREE/SEND/COMPLETE/RECEIVE/AP_FREE required')
        r = {name: group[tag] for name, tag in tags.items()}
        at = {name: row['line'] for name, row in r.items()}
        require(previous_line < tx['line'] < min(at.values()) and
                at['REQUEST_FREE'] < at['SEND'] < at['COMPLETE'] and
                at['REQUEST_FREE'] < at['RECEIVE'] < at['AP_FREE'], 'VDF native request/send/receive/free order differs')
        canonical = payload_read(run, tx['request_payload'])
        output = transfer_output(run, tx)
        require(tx['token'] == 0 and tx['first'] == tx['last'], 'VDF config result acquired an encoded lease')
        value = history[tx['first']]
        zebra, layout, display, bb, bit_width = (tx['opcode'] == op for op in (6, 7, 8, 9, 12))
        commands, result_bytes = VDF_OPERATIONS[tx['opcode']]
        command = tx['origin']['command']
        require(command in commands, 'VDF configuration opcode/native command mapping differs')
        native_bytes = commands[command]
        route = output[128:144]
        event = tx.get('frame')
        needed(type(event) is dict and type(event.get('proof')) is dict, 'VDF/BB actual kind4/kind5 RGB/config proof required')
        p, active = noncodec_proof(tx, value, transport, output), value['enabled']
        origin = tx['origin']
        if bb or bit_width:
            require(type(origin['source']) is int and 0 < origin['source'] < 2**32,
                    'BB/bit width source must be the complete native u32 without truncation')
        binding = None
        if command == 0x141:
            binding = next(refresh_bindings)
            source = vdf_refresh_queue_binding(binding, transport, origin)
            require(refresh_source is None or source == refresh_source, 'VDF refresh immutable global source changed')
            refresh_source = source
            first_model_line = min(item['line'] for item in transport['transfers']
                                   if previous_line < item['line'] <= tx['line'] and item['origin'] == origin)
            require(previous_line < binding['line'] < first_model_line,
                    'VDF refresh binding must precede its own first model/owned record')
        else:
            require(origin['source'] & 0xffff0000 == 0x81cf0000, 'VDF actual original caller/SID/command differs')
        require(origin['destination'] == 0x92840747 and origin['command'] == command and origin['bytes'] == native_bytes,
                'VDF actual original caller/SID/command differs')
        if cycle == 1:
            needed(any(item['opcode'] == 1 and item['line'] < tx['line'] and item['origin'] == origin
                       for item in transport['transfers']), 'VDF original-bound INIT before first display commit required')
        # RECEIVE observes the live lease even when inline free precedes the SEND log.
        text = r['RECEIVE']['fields']['ack_retained']
        ack_pointer = 0 if text == '(nil)' else number(text)
        require(0 < ack_pointer <= 2**64 - 12, 'VDF independent live ACK allocation missing')
        allocate_after_free = layout or display or bb or bit_width
        for name, row in r.items():
            f, line = row['fields'], row['line']
            wire = raw_hex(f, 'raw', native_bytes)
            if bit_width:
                converted = wire[8:] + bytes(6)
            elif bb:
                converted = struct.pack('<2H', command, native_bytes - 8) + wire[8:] + bytes(36 - native_bytes)
            elif display:
                converted = struct.pack('<2I', command, native_bytes - 8) + wire[8:] + bytes(16 - native_bytes)
            else:
                converted = wire[8:] if layout else wire[8:13] + bytes(3) if zebra else wire[8:21] + bytes(3)
            require(wire[:8] == struct.pack('<4H', 0x200d, command, native_bytes, 0x8001) and
                    converted == canonical and fnv(wire) == origin['fnv1a64'] ==
                    int(writeback.hash_hex(f.get('original_fnv1a'), 16), 16) and
                    raw_hex(f, 'ack_wire', 12) == (bytes.fromhex('0d205e110c00018000005900') if bit_width else
                        struct.pack('<4HI', 0x200d, command + 0x1000, 12, 0x8001, 0 if zebra or bb else 0x590000)) and
                    raw_hex(f, 'canonical_config', 16) == route and
                    raw_hex(f, 'model_result_hex', result_bytes) == output and
                    int(writeback.hash_hex(f.get('model_result_fnv1a64'), 16), 16) == fnv(output),
                    'VDF raw request/ACK/config/result bytes differ')
            if zebra or layout or display or bb or bit_width:
                key, count = ('canonical_bit_width8', 8) if bit_width else ('canonical_bb32', 32) if bb else ('canonical_display16', 16) if display else ('canonical_layout32', 32) if layout else ('canonical_zebra8', 8)
                needed('model_result_bytes' in f, 'VDF typed result byte count missing')
                require(raw_hex(f, key, count) == canonical and number(f['model_result_bytes']) == result_bytes,
                        'Zebra/layout/display/bit width canonical/result native receipt differs')
            elif 'model_result_bytes' in f:
                require(number(f['model_result_bytes']) == 160, 'VDF native result160 size differs')
            if 'realresultbytes' in f:
                require(number(f['realresultbytes']) == result_bytes, 'VDF actual result size differs')
            for key in ('pid', 'model_instance', 'source', 'destination', 'command', 'bytes', 'sender_tid'):
                expected = {'pid': transport['pid'], 'model_instance': transport['model_instance'],
                            'sender_tid': origin['producer_tid'], **origin}[key]
                require(number(f[key]) == expected, 'VDF original owner/instance/worker differs: ' + key)
            if command == 0x141:
                needed('refresh_queue_bound' in f and 'refresh_queue_source' in f,
                       'VDF original0141 exact refresh queue snapshot required')
                require(f['refresh_queue_bound'] == '1' and number(f['refresh_queue_source']) == origin['source'],
                        'VDF original0141 is not bound to its exact refresh queue source')
            if 'refresh_queue_bound' in f or 'refresh_queue_source' in f:
                require(f.get('refresh_queue_bound') in ('0', '1') and
                        re.fullmatch(r'(?:0|0x[1-9a-f][0-9a-f]*)', f.get('refresh_queue_source', '')),
                        'VDF refresh queue snapshot grammar differs')
                source = number(f['refresh_queue_source'])
                require((f['refresh_queue_bound'] == '0' and source == 0) or
                        (f['refresh_queue_bound'] == '1' and 0 < source < 2**32 - 1 and source != 0x92840747),
                        'VDF refresh queue snapshot range/bound state differs')
            for key in ('config_generation', 'before_config_generation', 'frame_generation',
                        'before_frame_generation', 'lease_generation'):
                require(number(f[key]) == value[key], 'VDF native/model generation differs: ' + key)
            require(all(f.get(key) == '0' for key in ('init_rc', 'bridge_rc', 'validation_rc', 'faults',
                    'allocate_rc', 'send_rc', 'free_rc', 'releasing', 'original_CP_FIFO_verified',
                    'physical_CP_RTOS_verified', 'original_selector_verified', 'physical_ASIC_verified', 'capture_verified')) and
                    all(f.get(key) == '1' for key in ('functional_model', 'model_complete', 'request_owned', 'request_freed')) and
                    f.get('request_retained') in ('(nil)', '0', '0x0'), 'VDF failed native work or scope promotion')
            for key in ('allocation_alias', 'request_free_rc'):
                if allocate_after_free:
                    needed(key in f, 'VDF post-request-free ACK allocation receipt missing: ' + key)
                if key in f:
                    require(f[key] == '0', 'VDF ACK allocation alias/original request free failed: ' + key)
            not_allocated = allocate_after_free and name == 'REQUEST_FREE'
            if allocate_after_free:
                needed('allocation_returned' in f, 'VDF actual ACK allocation receipt missing')
            if 'allocation_returned' in f:
                allocated = 0 if f['allocation_returned'] == '(nil)' else number(f['allocation_returned'])
                require(allocated == (0 if not_allocated else ack_pointer),
                        'VDF actual ACK allocation pointer/timing differs')
            queued, received, freed = (int(line >= at[key]) for key in ('SEND', 'RECEIVE', 'AP_FREE'))
            busy = int(line < at['COMPLETE'])
            consumed = int(queued and received and freed and not busy)
            expected = dict(cycle=cycle, requests=cycle, completed_cycles=cycle - 1 + consumed,
                            queued=queued, received=received, AP_consumed=consumed, busy=busy, guard=busy,
                            send_inflight=int(name in ('RECEIVE', 'AP_FREE') and line < at['SEND']),
                            receiver_tid=origin['producer_tid'] if received else 0,
                            free_tid=origin['producer_tid'] if freed else 0,
                            tid=origin['producer_tid'], phase=5 if consumed else 4 if received else 3 if queued else 2)
            for key, expected_value in expected.items():
                require(number(f[key]) == expected_value, 'VDF immutable cycle/receive/free state differs: ' + key)
            pointer = 0 if f['ack_retained'] == '(nil)' else number(f['ack_retained'])
            require(pointer == (0 if freed or not_allocated else ack_pointer),
                    'VDF ACK lease changed/reused before original free')
        previous_line = max(at.values())
        checked.append(dict(cycle=cycle, first=tx['first'], opcode=tx['opcode'], native_command=command,
                            model_instance=transport['model_instance'],
                            config_generation=value['config_generation'], frame_generation=value['frame_generation'],
                            active=bool(value['enabled']), original_request_fnv1a64=f'{origin["fnv1a64"]:016x}',
                            AP_consumed=True, receive_line=at['RECEIVE'], free_line=at['AP_FREE']))
        if binding is not None:
            checked[-1]['refresh_queue_binding'] = binding
    require(all(tx['opcode'] in (1, native_opcodes[tx['origin']['command']])
                for tx in transport['transfers'] if tx['origin']['destination'] == 0x92840747 and
                tx['origin']['command'] in native_opcodes),
            'VDF original0138/0153/014c/0141/0152/0162/0163/015e was relabelled as a media/configuration operation')
    if any(tx['opcode'] == 12 for tx in transfers):
        check_frames(run, transport, require_codecs=False)
    return {'required': True, 'verified': True, 'cycles': checked, 'diagnostics': diagnostics,
            'physical_asic_compatibility_verified': False,
            'original_selector_verified': False, 'original_CP_FIFO_verified': False, 'original_RTOS_verified': False,
            'original_Zebra_gate_verified': False, 'original_VDF_area_order_verified': False,
            'original_VDF_layout_hardware_verified': False,
            'original_Peaking_operator_verified': False, 'original_0162_feature_verified': False,
            'display_bit_width_physical_mapping_verified': False,
            'original_BB_C_configuration_work_verified': False, 'original_BB_C_configuration_units_verified': False}


def check_startup_control_diagnostics(rows, transfers, pid):
    result = {hex(command): 'not_observed' for command in (0x4014, 0x4057)}
    observed = [r for r in rows if r['tag'] == 'NATIVE_CP_STARTUP_DIAGNOSTIC_REPLY_FREE' and
                r['fields'].get('opcode') in result]
    required = set(('pid opcode sender_tid waiter_tid requests busy guard faults source request_destination destination bytes '
        'request cookie wire_fnv1a32 source_byte1_known reply freed_reply reply_free_destination reply_free_source reply_free_bytes '
        'allocate_rc send_rc request_free_rc reply_free_rc queued request_freed reply_freed clean_completion ap_consumed '
        'retained_request live_reply retained_cleanup diagnostic_only virtual_padding business_applied source_dependencies_closed '
        'configured published generation native_cp EE frame capture').split())
    seen = set()
    for row in observed:
        f = row['fields']
        needed(required <= f.keys(), 'Startup initial diagnostic complete actual free receipt')
        command = number(f['opcode'])
        require(command not in seen and (not transfers or row['line'] < transfers[0]['line']),
                'Startup initial diagnostic repeated/late')
        seen.add(command)
        size = 24 if command == 0x4014 else 12
        wire = raw_hex(f, 'request', size)
        ack = b'\x01\0' + struct.pack('<H', command) + wire[4:8] + struct.pack('<I', 0xf000)
        sender = number(f['sender_tid'])
        digest32 = 2166136261
        for byte in wire:
            digest32 = ((digest32 ^ byte) * 16777619) & 0xffffffff
        require(wire[0] == 5 and struct.unpack_from('<H', wire, 2)[0] == command and
                wire[8:] == (STARTUP_CONTROL_MODE_BODY if command == 0x4014 else bytes(4)) and
                raw_hex(f, 'reply', 12) == raw_hex(f, 'freed_reply', 12) == ack and 0 < sender < 2**31 and
                all(number(f[k]) == v for k, v in dict(pid=pid, waiter_tid=sender, requests=1, source=0x80020002,
                    request_destination=0x90030001, destination=0x80020002, bytes=size,
                    cookie=struct.unpack_from('<I', wire, 4)[0], wire_fnv1a32=digest32,
                    source_byte1_known=int(command == 0x4057), reply_free_destination=0x80020002,
                    reply_free_source=0x90030001, reply_free_bytes=12).items()) and
                all(f[k] == '1' for k in ('queued', 'request_freed', 'reply_freed', 'clean_completion',
                                         'ap_consumed', 'diagnostic_only', 'virtual_padding')) and
                all(f[k] == '0' for k in ('busy', 'guard', 'faults', 'allocate_rc', 'send_rc', 'request_free_rc', 'reply_free_rc',
                    'business_applied', 'source_dependencies_closed', 'configured', 'published', 'generation', 'native_cp', 'EE', 'frame', 'capture')) and
                all(f[k] == '(nil)' for k in ('retained_request', 'live_reply', 'retained_cleanup')),
                'Startup initial diagnostic raw wire/cookie/free truth must remain clean and transport-only')
        result[hex(command)] = dict(status='transport_only', format_applied=False, mode_applied=False,
                                    settings_checkpoint_loaded=False, line=row['line'])
    return result


def check_still_format(run, manifest, rows, transport):
    return _check_cp_configuration(run, manifest, rows, transport)


def check_focus_reset(run, manifest, rows, transport):
    """Exact original403f(0,0), real RGB transaction, then original reply ownership."""
    family = 'FUNCTIONAL_CAMERA_FOCUS_MAGNIFICATION_'
    tags = {family + suffix for suffix in ('RESET_REQUEST', 'BACKEND', 'APPLIED',
        'APPLIED_REPLY_RECEIVED', 'APPLIED_REPLY_FREE')}
    legacy = {family + suffix for suffix in ('UNAVAILABLE', 'REPLY_RECEIVED', 'REPLY_FREE')}
    require(all(r['tag'] in tags | legacy for r in rows if r['tag'].startswith(family)),
            'Focus reset unknown original producer')
    selected = [r for r in rows if r['tag'] in tags or r['tag'] == 'FUNCTIONAL_FOCUS_RESET_MODEL']
    transfers = [tx for tx in transport['transfers'] if tx['opcode'] == 14 and tx['origin']['command'] == 0x403f]
    result = dict(required=bool(selected or transfers), verified=False, status='not_observed', cycles=[],
                  missing=[], magnification_disabled=False, AP_consumed=False, capture_verified=False,
                  physical_asic_compatibility_verified=False, original_CP_executed=False)
    if not result['required']:
        return result
    backup = manifest.get('backup_transport')
    require(type(backup) is dict and all(typed_equal(manifest.get('functional_camera_' + k), v) and
            typed_equal(backup.get('functional_camera_' + k), v) for k, v in STARTUP_CONTROL_POLICY.items()),
            'Focus reset lacks explicit actual RGB software policy')
    requests, identities = [], set()
    for row in selected:
        needed('diagnostic' not in row, 'Focus reset incomplete original formatter')
        if row['tag'] != family + 'RESET_REQUEST':
            continue
        f = row['fields']
        wire = raw_hex(f, 'raw', 16)
        sender, cookie, fingerprint = number(f['tid']), number(f['token']), fnv(wire)
        require(set(f) == set('pid tid source destination cmd token request_bytes raw native_fnv policy capture_verified'.split()) and
                0 < sender < 2**31 and number(f['pid']) == transport['pid'] and
                wire[:4] == b'\x05\0\x3f\x40' and wire[8:] == bytes(8) and
                struct.unpack_from('<I', wire, 4)[0] == cookie and 0 <= cookie < 2**32 and
                all(number(f[k]) == v for k, v in dict(source=0x80020002, destination=0x90040193,
                    cmd=0x403f, request_bytes=16, native_fnv=fingerprint, capture_verified=0).items()) and
                f.get('policy') == FOCUS_RESET_POLICY and (sender, cookie) not in identities,
                'Focus reset original16/source/neutral body/cookie/fingerprint differs or repeats')
        identities.add((sender, cookie))
        requests.append((row, sender, cookie, fingerprint))
    require(not any(r['tag'] == family + 'APPLIED' for r in selected) or transfers,
            'Focus reset success ACK without actual Core RGB operation')
    result['status'] = 'incomplete'
    if not transfers:
        result['missing'].append('actual successful original-bound OP14/403f full192 RGB transaction')
        return result
    history, claimed = vdf_history(run, transport), set()
    for tx in transfers:
        origin = tx['origin']
        require(type(tx['opcode']) is int and tx['provider_kind'] == 'core' and tx['token'] == 0 and
                tx['first'] == tx['last'] and all(type(origin[k]) is int and origin[k] == v for k, v in
                    dict(source=0x80020002, destination=0x90040193, command=0x403f, bytes=16).items()) and
                type(origin['producer_tid']) is int and 0 < origin['producer_tid'] < 2**31 and
                type(origin['fnv1a64']) is int and 0 <= origin['fnv1a64'] < 2**64,
                'Focus reset actual opcode/Core provider/original source tuple differs')
        matches = [(r, tid, cookie, fingerprint) for r, tid, cookie, fingerprint in requests
                   if tid == origin['producer_tid'] and fingerprint == origin['fnv1a64']]
        require(len(matches) == 1, 'Focus reset needs its unique original16 request')
        request, sender, cookie, fingerprint = matches[0]
        require((sender, cookie) not in claimed, 'Focus reset reused one original request for multiple Core operations')
        claimed.add((sender, cookie))
        index = transport['transfers'].index(tx)
        require(index > 0, 'Focus reset missing preceding State128')
        before = transport['transfers'][index - 1]
        require(before['opcode'] == 2 and before['origin'] == origin and
                request['line'] < before['line'] < tx['line'], 'Focus reset STATE origin/order differs')
        state, output = transfer_output(run, before), transfer_output(run, tx)
        canonical, value = payload_read(run, tx['request_payload']), history[tx['first']]
        require(len(state) == 128 and struct.unpack_from('<2I', state) == (1, 15) and
                struct.unpack_from('<2I', state, 8) == (640, 480) and state[104:112] == bytes(8) and
                state[120:] == bytes(8) and startup_control_config(canonical) == 0x403f and
                struct.unpack_from('<Q', state, 48)[0] == transport['model_instance'] and
                struct.unpack_from('<Q', canonical, 24)[0] == fnv(state[8:48]) and
                struct.unpack_from('<Q', state, 56)[0] == value['before_config_generation'] and
                struct.unpack_from('<Q', state, 112)[0] == value['before_frame_generation'],
                'Focus reset actual State128/current optics fingerprint differs')
        noncodec_proof(tx, value, transport, output)
        def one(tag, predicate):
            found = [r for r in selected if r['tag'] == tag and predicate(r['fields'])]
            require(len(found) <= 1, 'Focus reset duplicate original ' + tag)
            if not found and tag != 'FUNCTIONAL_FOCUS_RESET_MODEL':
                require(not any(r['tag'] == tag and number(r['fields']['token']) == cookie for r in selected),
                        'Focus reset recorded reply/backend has wrong original sender')
            return found[0] if found else None
        by_cookie = lambda f: number(f['token']) == cookie and number(f.get('sender_tid', f.get('tid'))) == sender
        by_origin = lambda f: number(f['native_fnv']) == fingerprint and number(f['tid']) == sender
        model = one('FUNCTIONAL_FOCUS_RESET_MODEL', by_origin)
        backend = one(family + 'BACKEND', by_cookie)
        applied = one(family + 'APPLIED', by_cookie)
        received = one(family + 'APPLIED_REPLY_RECEIVED', by_cookie)
        freed = one(family + 'APPLIED_REPLY_FREE', by_cookie)
        if any(r is None for r in (model, backend, applied, received, freed)):
            result['missing'].append('complete MODEL/BACKEND/APPLIED/original RECEIVE/sender FREE for ' + str(cookie))
            continue
        common = dict(pid=transport['pid'], tid=sender, model_instance=transport['model_instance'],
                      native_fnv=fingerprint, capture_verified=0)
        expected_model = dict(common, rc=0, state_used=128, state_required=128, result_used=192,
                              result_required=192, result_token=0, result_fnv=fnv(output), physical_ASIC_verified=0)
        expected_backend = dict(common, cmd=0x403f, token=cookie, backend_rc=0,
            cfg_before=value['before_config_generation'], cfg=value['config_generation'],
            frame_before=value['before_frame_generation'], frame=value['frame_generation'],
            canonical_fnv=fnv(canonical), model_fnv=fnv(output))
        expected_applied = dict(common, source=0x80020002, destination=0x90040193, cmd=0x403f,
            token=cookie, request_bytes=16, reply_bytes=12, status=0xf000, request_free_rc=0,
            cfg=value['config_generation'], frame=value['frame_generation'], model_fnv=fnv(output),
            rgb_bytes=921600, frame_consumed=1, frame_retired=1, magnification_disabled=1)
        for row, expected in ((model, expected_model), (backend, expected_backend), (applied, expected_applied)):
            f = row['fields']
            string_fields = {'policy'} if row is not backend else set()
            require(set(f) == set(expected) | string_fields and
                    all(number(f[k]) == v for k, v in expected.items()) and
                    (not string_fields or f['policy'] == FOCUS_RESET_POLICY),
                    'Focus reset original actual model/192/backend/applied content differs')
        receiver = number(received['fields']['tid'])
        require(0 < receiver < 2**31 and tx['line'] < model['line'] <
                min(backend['line'], applied['line'], received['line'], freed['line']) and
                received['line'] < freed['line'], 'Focus reset model/send/receive/sender-free order differs')
        for row, expected in ((received, dict(tid=receiver, sender_tid=sender)),
                              (freed, dict(tid=sender, sender_tid=sender, receiver_tid=receiver))):
            expected.update(source=0x90040193, destination=0x80020002, cmd=0x403f, token=cookie,
                            bytes=12, status=0xf000, rc=0, magnification_disabled=1, capture_verified=0)
            require(set(row['fields']) == set(expected) and all(number(row['fields'][k]) == v for k, v in expected.items()),
                    'Focus reset original12 reply receiver/sender-free roles or content differs')
        result['cycles'].append(dict(first=tx['first'], sender_tid=sender, receiver_tid=receiver, cookie=cookie,
            native_fnv=fingerprint, model_instance=transport['model_instance'], cfg=value['config_generation'],
            frame=value['frame_generation'], result_fnv=fnv(output), rgb_bytes=value['active_bytes'],
            AP_consumed=True, capture_verified=False))
    applied_rows = [r for r in selected if r['tag'] == family + 'APPLIED']
    require(len(applied_rows) <= len(transfers), 'Focus reset orphan/duplicate success ACK')
    if len(claimed) != len(requests):
        result['missing'].append('every original reset request must have its own actual Core result')
    if not result['missing'] and len(result['cycles']) == len(transfers):
        require(len(selected) == 6 * len(transfers), 'Focus reset unclaimed original producer records')
        result.update(verified=True, status='verified', magnification_disabled=True, AP_consumed=True)
    return result


def check_startup_control(run, manifest, rows, transport):
    return _check_cp_configuration(run, manifest, rows, transport, startup=True)


def _check_cp_configuration(run, manifest, rows, transport, *, startup=False):
    """Independent CP promises share ownership rules, never the dynamic VDF queues."""
    opcode = 14 if startup else 13
    commands, size = CONFIG_OPERATIONS[opcode]
    if startup:
        commands = {key: value for key, value in commands.items() if key != 0x403f}
    prefix = 'FUNCTIONAL_STARTUP_CONTROL' if startup else 'FUNCTIONAL_STILL_FORMAT'
    label = 'Startup control' if startup else 'Still format'
    transfers = [tx for tx in transport['transfers'] if tx['opcode'] == opcode and
                 not (startup and tx['origin']['command'] == 0x403f)]
    native = [tx for tx in transport['transfers'] if tx['origin']['destination'] == 0x90030001 and
              tx['origin']['command'] in commands]
    records = [r for r in rows if r['tag'].startswith(prefix)]
    result = dict(required=bool(transfers or native or records), verified=False, status='not_observed',
                  format_applied=False, AP_consumed=False, cycles=[], missing=[],
                  initial_diagnostic='not_observed', capture_verified=False,
                  physical_asic_compatibility_verified=False, original_CP_executed=False,
                  original_CP_RAM_verified=False, original_RTOS_verified=False,
                  still_format_physical_selector_mapping_verified=False)
    if startup:
        result.update(mode_applied=False, settings_checkpoint_loaded=False, startup_control_applied=False,
                      startup_control_physical_mapping_verified=False)
    if not result['required']:
        return result
    policy = STARTUP_CONTROL_POLICY if startup else STILL_FORMAT_POLICY
    backup = manifest.get('backup_transport')
    require(type(backup) is dict and all(typed_equal(manifest.get('functional_camera_' + k), v) and
            typed_equal(backup.get('functional_camera_' + k), v) for k, v in policy.items()),
            label + ' operation lacks its exact typed software policy')
    require(all(type(tx['opcode']) is int and tx['opcode'] in (2, opcode) for tx in native),
            label + ' original CP request was relabelled as another operation')
    for tx in transfers:
        origin = tx['origin']
        require(all(type(origin[k]) is int and origin[k] == v for k, v in
                    (('source', 0x80020002), ('destination', 0x90030001))) and
                type(origin['command']) is int and origin['command'] in commands and
                type(origin['bytes']) is int and origin['bytes'] == commands[origin['command']] and
                type(origin['producer_tid']) is int and 0 < origin['producer_tid'] < 2**31 and
                type(origin['fnv1a64']) is int and 0 <= origin['fnv1a64'] < 2**64,
                label + ' requires the complete original CP origin, never a general ACK')
    history = vdf_history(run, transport)
    if transfers:
        check_frames(run, transport, require_media=False)
    groups, tickets, predecessors, resources = {}, {}, [], []
    for row in records:
        tag, f = row['tag'], row['fields']
        needed('diagnostic' not in row, f'{label} {tag} line {row["line"]}: missing complete original formatter' +
               ('; diagnostic=' + row['diagnostic'] if 'diagnostic' in row else ''))
        if tag == prefix:
            cycle = number(f['cycle'])
            require(cycle > 0 and f.get('event') in ('REQUEST_FREE', 'RECEIVE', 'SENDER_FREE', 'CYCLE', 'REFUSED'),
                    'Still format unknown/zero-cycle owner event')
            group = groups.setdefault(cycle, {})
            require(f['event'] not in group, 'Still format duplicate cycle receipt')
            group[f['event']] = row
        elif tag == prefix + '_TICKET_BOUND':
            cycle = number(f['cycle'])
            require(cycle > 0 and cycle not in tickets, 'Still format duplicate/zero immutable ticket')
            tickets[cycle] = row
        elif tag == prefix + '_PREDECESSORS':
            predecessors.append(row)
        elif tag in (prefix + '_RESOURCE_DEPENDENCIES', prefix + '_RESOURCES_TTS_TABLE',
                     prefix + '_RESOURCES_RESERVED'):
            equivalent = dict(row, tag=tag.replace(prefix + '_', 'FUNCTIONAL_VDF_PATH_', 1))
            require(vdf_resource_diagnostic(equivalent), 'Still format resource receipt differs')
            resources.append(row)
        else:
            require(False, 'Still format failed/unknown native receipt: ' + tag)
    result['status'] = 'incomplete'
    diagnostic = [] if startup else [r for r in rows if r['tag'] == 'NATIVE_CP_CAPTURE_FORMAT_DIAGNOSTIC_REPLY_FREE']
    if startup:
        result['initial_diagnostic'] = check_startup_control_diagnostics(rows, transfers, transport['pid'])
    if transfers and diagnostic:
        require(len(diagnostic) == 1 and diagnostic[0]['line'] < transfers[0]['line'],
                'Still format initial diagnostic is repeated/late')
        d = diagnostic[0]['fields']
        required = set(('pid sender_tid waiter_tid requests source destination bytes request cookie reply freed_reply '
            'reply_free_destination reply_free_source reply_free_bytes busy guard faults allocate_rc send_rc request_free_rc '
            'reply_free_rc queued request_freed reply_freed clean_completion ap_consumed retained_request live_reply '
            'retained_cleanup diagnostic_only no_publication source_business_applied generation native_verified native_cp '
            'CP_history_verified EE frame capture').split())
        if not required <= d.keys():
            result['missing'].append('complete original one-shot diagnostic free receipt')
            return result
        wire = raw_hex(d, 'request', 24)
        first_m = bytes.fromhex('05002d402600008002000101010101000101010101000000')
        ack = b'\x01\x00\x2d\x40' + wire[4:8] + struct.pack('<I', 0xf000)
        require(wire[0] == 5 and wire[2:4] == b'\x2d\x40' and wire[8:22] == first_m[8:22] and
                raw_hex(d, 'reply', 12) == raw_hex(d, 'freed_reply', 12) == ack and
                all(number(d[k]) == v for k, v in dict(pid=transport['pid'], sender_tid=transfers[0]['origin']['producer_tid'],
                    waiter_tid=transfers[0]['origin']['producer_tid'], requests=1, source=0x80020002, destination=0x90030001,
                    bytes=24, cookie=struct.unpack_from('<I', wire, 4)[0], reply_free_destination=0x80020002,
                    reply_free_source=0x90030001, reply_free_bytes=12).items()) and
                all(d[k] == '1' for k in ('queued', 'request_freed', 'reply_freed', 'clean_completion', 'ap_consumed',
                                         'diagnostic_only', 'no_publication')) and
                all(d[k] == '0' for k in ('busy', 'guard', 'faults', 'allocate_rc', 'send_rc', 'request_free_rc', 'reply_free_rc',
                    'source_business_applied', 'generation', 'native_verified', 'native_cp', 'CP_history_verified', 'EE', 'frame', 'capture')) and
                all(d[k] == '(nil)' for k in ('retained_request', 'live_reply', 'retained_cleanup')),
                'Still format initial M diagnostic must remain one-shot transport-only and clean/AP-free')
        result['initial_diagnostic'] = dict(status='transport_only', format_applied=False, line=diagnostic[0]['line'])
    if not transfers:
        require(not tickets and all(set(g) <= {'REFUSED'} for g in groups.values()),
                'Still format ACK/ownership without an actual typed OP13')
        result['missing'].append('actual successful OP13/176 and original request/ACK lifecycle')
        return result
    require(not any('REFUSED' in g for g in groups.values()), 'Still format refused Core operation must not ACK')
    if len(groups) != len(transfers) or len(tickets) != len(transfers):
        result['missing'].append('one owner cycle and before-send immutable ticket for every OP13')
        return result
    require(list(groups) == list(range(1, len(transfers) + 1)) and set(tickets) == set(groups),
            'Still format cycle/ticket census differs')
    format_cycles, format_transfers = {}, []
    if startup:
        # Recheck the raw lifecycle; a caller's cached still_format summary is not evidence.
        format_stage = check_still_format(run, manifest, rows, transport)
        if not format_stage['verified']:
            result['missing'].append('Startup control same-run complete OP13 lifecycle before predecessors')
        else:
            format_cycles = {c['first']: (c, max(r['line'] for r in rows if
                r['tag'] == 'FUNCTIONAL_STILL_FORMAT' and number(r['fields']['cycle']) == c['cycle']))
                for c in format_stage['cycles']}
        format_transfers = [t for t in transport['transfers'] if t['opcode'] == 13]
    owner_fields = set(('event pid tid cycle requests completed busy guard faults retained model_instance before_cfg cfg '
        'before_frame frame lease state_rc state_validation_rc bridge_rc validation_rc transport_rc attempted model_complete '
        'origin_fnv result_fnv used required token request reply req_free_rc alloc_rc send_rc reply_free_rc queued received '
        'freed send_inflight sender_tid receiver_tid free_tid AP_consumed functional_only original_AP_verified original_CP '
        'physical_ASIC_verified physical_CP_RTOS_verified capture_verified').split())
    if startup:
        owner_fields.update(('command', 'command_requests', 'command_completed', 'mode_applied', 'config40_fnv',
                             'source_dependencies_closed', 'native_CP', 'EE'))
    previous_line, command_counts, completed_counts, used_predecessors = 0, [0, 0], [0, 0], 0
    for cycle, tx in enumerate(transfers, 1):
        group, ticket = groups[cycle], tickets[cycle]
        ticket_fields = set(('pid tid cycle pointer destination source bytes cookie reply before_actual_send '
                             'physical_ASIC_verified capture_verified').split())
        if (set(group) != {'REQUEST_FREE', 'RECEIVE', 'SENDER_FREE', 'CYCLE'} or
                not ticket_fields <= ticket['fields'].keys() or any(
                not owner_fields <= r['fields'].keys() for r in group.values())):
            result['missing'].append('REQUEST_FREE/RECEIVE/SENDER_FREE/CYCLE with complete actual owner fields')
            return result
        at = {k: r['line'] for k, r in group.items()}
        require(previous_line < tx['line'] < at['REQUEST_FREE'] < ticket['line'] <
                min(at['RECEIVE'], at['SENDER_FREE'], at['CYCLE']) and at['RECEIVE'] < at['SENDER_FREE'],
                'Still format typed result/request-free/ticket/receive/sender-free order differs')
        origin, value = tx['origin'], history[tx['first']]
        output, canonical = transfer_output(run, tx), payload_read(run, tx['request_payload'])
        require(tx['first'] == tx['last'] and tx['token'] == 0 and tx.get('provider_kind') == 'core',
                label + ' acquired a codec/source lease')
        slot = int(origin['command'] == 0x4057)
        if startup:
            require(origin['command'] != 0x4057 or completed_counts[0] > 0,
                    'Startup settings requires preceding functional4014 actual AP consumption')
            command_counts[slot] += 1
        before = transport['transfers'][transport['transfers'].index(tx) - 1]
        require(before['opcode'] == 2 and before['origin'] == origin and previous_line < before['line'] < tx['line'],
                'Still format requires its own preceding original-bound STATE128')
        state = transfer_output(run, before)
        require(struct.unpack_from('<Q', state, 56)[0] == value['before_config_generation'] and
                struct.unpack_from('<Q', state, 112)[0] == value['before_frame_generation'] and
                value['lease_generation'] >= struct.unpack_from('<Q', state, 64)[0] + 1 and
                value['lease_generation'] >= value['frame_generation'],
                'Still format STATE/config/frame/rendered lease history differs')
        if startup:
            require(len(state) == 128 and state[104:112] == bytes(8) and
                    struct.unpack_from('<Q', canonical, 24)[0] == fnv(state[8:48]),
                    'Startup control requires its actual preceding State128 config40 fingerprint')
        audits = [r for r in rows if r['tag'] == 'NATIVE_CP_BACKGROUND_INPUT_AUDIT' and
                  previous_line < r['line'] < before['line'] and r['fields'].get('destination') == '0x90030001' and
                  r['fields'].get('bytes') == str(origin['bytes']) and r['fields'].get('tid') == str(origin['producer_tid'])]
        candidates = []
        for audit in audits:
            f = audit['fields']
            require(number(f['pid']) == transport['pid'], 'Still format original audit PID differs from this run')
            chunks = [r for r in rows if r['tag'] == 'NATIVE_CP_BACKGROUND_INPUT_AUDIT_BYTES' and
                      audit['line'] < r['line'] < before['line'] and all(r['fields'].get(k) == f.get(k)
                      for k in ('pid', 'tid', 'sequence'))]
            if len(chunks) == 1 and chunks[0]['fields'].get('offset') == '0' and chunks[0]['fields'].get('bytes') == str(origin['bytes']):
                wire = raw_hex(chunks[0]['fields'], 'raw', origin['bytes'])
                if fnv(wire) == origin['fnv1a64']:
                    candidates.append((audit, wire))
        if not candidates:
            result['missing'].append(label + ' same-cycle original CP audit and complete raw request/FNV')
            return result
        require(len(candidates) == 1, 'Still format duplicated original raw24 audit')
        audit, wire = candidates[0]
        if diagnostic:
            require(diagnostic[0]['line'] < audit['line'], 'Still format request preceded initial diagnostic AP-free')
        f = audit['fields']
        require(number(f['pid']) == transport['pid'] and number(f['source']) == origin['source'] and f['entry'] == 'async' and
                all(f.get(k) == '1' for k in ('size_known', 'source_known', 'bytes_complete', 'complete')) and
                all(f.get(k) == '0' for k in ('consumed', 'state_verified', 'capture_verified')) and
                wire[0] == 5 and struct.unpack_from('<H', wire, 2)[0] == origin['command'] and
                (wire[8:] == canonical[4:origin['bytes'] - 4] if startup else wire[8:22] + bytes(2) == canonical),
                label + ' original wire/body/source/destination differs')
        cookie = struct.unpack_from('<I', wire, 4)[0]
        ack = b'\x01\x00' + struct.pack('<H', origin['command']) + wire[4:8] + struct.pack('<I', 0xf000)
        t = ticket['fields']
        require(all(number(t[k]) == v for k, v in dict(pid=transport['pid'], tid=origin['producer_tid'], cycle=cycle,
                destination=origin['source'], source=origin['destination'], bytes=12, cookie=cookie).items()) and
                number(t['cookie']) < 2**32 and raw_hex(t, 'reply', 12) == ack and
                t.get('before_actual_send') == '1' and t.get('physical_ASIC_verified') == t.get('capture_verified') == '0',
                'Still format immutable ticket/full ACK/cookie/before-send binding differs')
        pointer = number(t['pointer'])
        require(0 < pointer <= 2**64 - 12, 'Still format missing independent live ACK pointer')
        preds = [r for r in predecessors if audit['line'] < r['line'] < at['REQUEST_FREE']]
        if startup:
            require(len(preds) <= 3, 'Startup control duplicate predecessor checks')
            used_predecessors += len(preds)
        if not (any(r['line'] < before['line'] for r in preds) and
                any(before['line'] < r['line'] < tx['line'] for r in preds) and
                any(tx['line'] < r['line'] for r in preds)):
            result['missing'].append(label + ' predecessor checks before STATE, after STATE and after typed result')
        for pred in preds:
            if startup:
                expected = dict(pid=transport['pid'], tid=origin['producer_tid'], accepted=1,
                    initial_mode_requests=1, initial_mode_AP_consumed=1, initial_settings_requests=1,
                    initial_settings_AP_consumed=1, all13_AP_consumed=1, VDF_AP_consumed=1,
                    still_format_AP_consumed=1, model_instance=transport['model_instance'],
                    source_business_equivalent=0, physical_ASIC_verified=0, capture_verified=0)
                fields = pred['fields']
                schema = set(expected) | {'still_format_cycle'}
                if not schema <= fields.keys():
                    result['missing'].append('Startup control complete Main predecessor receipt')
                    continue
                require(set(fields) == schema and all(number(fields[k]) == v for k, v in expected.items()) and
                        number(fields['still_format_cycle']) > 0,
                        'Startup control prior diagnostics/all13/current VDF/format identity or scope differs')
                latest = next((t for t in reversed(format_transfers) if t['line'] < pred['line']), None)
                if latest is None or latest['first'] not in format_cycles:
                    result['missing'].append('Startup control predecessor lacks its current complete OP13 lifecycle')
                    continue
                current, completion_line = format_cycles[latest['first']]
                require(number(fields['still_format_cycle']) == current['cycle'] and
                        current['model_instance'] == transport['model_instance'] and current['AP_consumed'] and
                        completion_line < pred['line'],
                        'Startup control current still_format_cycle/AP consumption not complete before predecessor')
            else:
                require(all(number(pred['fields'][k]) == v for k, v in dict(pid=transport['pid'], tid=origin['producer_tid'],
                        accepted=1, initial_diagnostic_requests=1, initial_diagnostic_AP_consumed=1,
                        VDF_AP_consumed=1, model_instance=transport['model_instance'], source_business_equivalent=0,
                        physical_ASIC_verified=0, capture_verified=0).items()), 'Still format prior diagnostic/current VDF differs')
        held_resources = [r for r in resources if audit['line'] < r['line'] < before['line']]
        needed_resources = {r['tag'] for r in held_resources}
        require(all(number(r['fields']['tid']) == origin['producer_tid'] and
                    ('pid' not in r['fields'] or number(r['fields']['pid']) == transport['pid']) for r in held_resources),
                'Still format resource guard30 owner differs')
        if len(held_resources) != 3 or needed_resources != {prefix + '_' + n for n in
                               ('RESOURCE_DEPENDENCIES', 'RESOURCES_TTS_TABLE', 'RESOURCES_RESERVED')}:
            result['missing'].append(label + ' actual guard dependency/table/reserved receipts before STATE')
            return result
        table = next(r['fields'] for r in held_resources if r['tag'] == prefix + '_RESOURCES_TTS_TABLE')
        require(number(audit['fields']['producer_return']) == number(table['appfw_base']) + 0x3535a68 and
                0 < number(audit['fields']['pointer']) <= 2**64 - origin['bytes'],
                'Still format original audited sender callsite/request pointer differs')
        for name, row in group.items():
            f, line = row['fields'], row['line']
            require(all(f.get(k) == '0' for k in ('state_rc', 'state_validation_rc', 'bridge_rc', 'validation_rc',
                    'transport_rc', 'faults', 'req_free_rc', 'alloc_rc', 'send_rc', 'reply_free_rc', 'token',
                    'original_AP_verified', 'original_CP', 'physical_ASIC_verified', 'physical_CP_RTOS_verified',
                    'capture_verified')) and all(f.get(k) == '1' for k in ('attempted', 'model_complete', 'functional_only')),
                    'Still format failed/sticky native work or scope promotion')
            require(all(number(f[k]) == v for k, v in dict(pid=transport['pid'], cycle=cycle, requests=cycle,
                    model_instance=transport['model_instance'], before_cfg=value['before_config_generation'],
                    cfg=value['config_generation'], before_frame=value['before_frame_generation'], frame=value['frame_generation'],
                    lease=value['lease_generation'], used=size, required=size).items()) and
                    int(writeback.hash_hex(f['origin_fnv'], 16), 16) == origin['fnv1a64'] and
                    int(writeback.hash_hex(f['result_fnv'], 16), 16) == fnv(output),
                    'Still format owner/origin/full176/generations differ')
            queued, inflight, busy, guard = (number(f[k]) for k in ('queued', 'send_inflight', 'busy', 'guard'))
            received, freed = int(line >= at['RECEIVE']), int(line >= at['SENDER_FREE'])
            require(f['request'] == '(nil)' and all(v in (0, 1) for v in (queued, inflight, busy, guard)) and busy == guard,
                    'Still format request free/guard/queue flags differ')
            if name == 'REQUEST_FREE':
                require(f['reply'] == '(nil)' and queued == inflight == 0 and busy == 1 and f['sender_tid'] == '0',
                        'Still format ACK allocated before actual request free')
            else:
                require(queued + inflight == 1 and number(f['sender_tid']) == origin['producer_tid'] and
                        f['reply'] == ('(nil)' if freed else t['pointer']), 'Still format ACK lease/actual send differs')
            if line >= at['CYCLE']:
                require(queued == 1 and inflight == busy == guard == 0, 'Still format CYCLE remains send-inflight/busy')
            consumed = int(queued and received and freed and not inflight and not busy and not guard)
            require(all(number(f[k]) == v for k, v in dict(received=received, freed=freed, AP_consumed=consumed,
                    completed=cycle - 1 + consumed, retained=int(name != 'REQUEST_FREE' and not freed),
                    free_tid=origin['producer_tid'] if freed else 0).items()), 'Still format receive/free/consumption state differs')
            receiver = number(f['receiver_tid'])
            if startup:
                expected_completed = completed_counts.copy()
                expected_completed[slot] += consumed
                require(number(f['command']) == origin['command'] and f['mode_applied'] == '1' and
                        [number(v) for v in f['command_requests'].split(',')] == command_counts and
                        [number(v) for v in f['command_completed'].split(',')] == expected_completed and
                        int(writeback.hash_hex(f['config40_fnv'], 16), 16) == fnv(state[8:48]) and
                        all(f[k] == '0' for k in ('source_dependencies_closed', 'native_CP', 'EE')),
                        'Startup control command/counters/actual config40 fingerprint or scope differs')
            require((0 < receiver < 2**31 if received else receiver == 0) and
                    number(f['tid']) == (receiver if name == 'RECEIVE' else origin['producer_tid']),
                    'Still format original receiver/sender-free thread differs')
        final = max(group.values(), key=lambda r: r['line'])
        require(final['fields']['AP_consumed'] == '1', 'Still format actual original sender free not complete')
        result['cycles'].append(dict(cycle=cycle, first=tx['first'], cookie=cookie, original_wire=wire.hex(),
            original_fnv1a64=f'{origin["fnv1a64"]:016x}', result_fnv1a64=f'{fnv(output):016x}',
            model_instance=transport['model_instance'], config_generation=value['config_generation'],
            frame_generation=value['frame_generation'], lease_generation=value['lease_generation'],
            receiver_tid=number(group['RECEIVE']['fields']['receiver_tid']), sender_tid=origin['producer_tid'],
            ticket_line=ticket['line'], receive_line=at['RECEIVE'], free_line=at['SENDER_FREE'], AP_consumed=True))
        if startup:
            completed_counts[slot] += 1
            result['cycles'][-1].update(command=origin['command'], config40_fnv1a64=f'{fnv(state[8:48]):016x}')
        previous_line = final['line']
    if startup and used_predecessors != len(predecessors):
        result['missing'].append('Startup control predecessor receipt outside its original request/STATE/OP14 window')
    if result['missing']:
        return result
    result.update(verified=True, status='complete', format_applied=not startup, AP_consumed=True)
    if startup:
        result.update(mode_applied=bool(completed_counts[0]), settings_checkpoint_loaded=bool(completed_counts[1]),
                      startup_control_applied=True)
    return result


def check_histogram(run, rows, transport):
    """One first-frame sample with separate future ACK and notification ownership."""
    records = [row for row in rows if row['tag'].startswith('FUNCTIONAL_HISTOGRAM_')]
    transfers = [tx for tx in transport['transfers'] if tx['opcode'] == 10]
    native = [tx for tx in transport['transfers'] if tx['origin']['destination'] == 0x92840747 and
              tx['origin']['command'] == 0x148]
    result = dict(required=bool(records or transfers or native), verified=False, first_frame_verified=False,
                  readback_verified=False, native_ACK_and_notification_AP_free=False, AP_consumed=False,
                  UI_applied=False, continuous_histogram=False, capture_verified=False,
                  physical_asic_compatibility_verified=False, original_CP_FIFO_verified=False,
                  original_RTOS_verified=False, original_CP_executed=False, original_CP_RAM_verified=False,
                  original_Histogram_bin_semantics_verified=False,
                  original_Histogram_physical_callback_verified=False)
    if not result['required']:
        return result
    needed(len(transfers) == 1 and records, 'Histogram exactly one actual first op10 and native receipts required')
    require(all(tx['opcode'] in (1, 10) for tx in native), 'Histogram original0148 relabelled as another operation')
    tx = transfers[0]
    origin = tx['origin']
    require(origin['destination'] == 0x92840747 and origin['command'] == 0x148 and origin['bytes'] == 12 and
            origin['fnv1a64'] == fnv(bytes.fromhex('0d2048010c00018001010000')),
            'Histogram actual original0148 origin/wire differs')
    canonical = payload_read(run, tx['request_payload'])
    output = transfer_output(run, tx)
    value = vdf_history(run, transport)[tx['first']]
    noncodec_proof(tx, value, transport, output)
    # Full serial/lifetime/counter history also applies when no JPEG/MP4 exists.
    check_frames(run, transport, require_codecs=False)
    require(canonical == HIST_CANONICAL and tx['first'] == tx['last'] and tx['token'] == 0,
            'Histogram canonical8 or tokenless1192 transfer differs')
    bindings = [row for row in records if row['tag'] == 'FUNCTIONAL_HISTOGRAM_QUEUE_BOUND']
    needed(len(bindings) == 1, 'Histogram exact original global queue binding required')
    source = vdf_refresh_queue_binding(bindings[0], transport, origin, histogram=True)
    first_line = min(item['line'] for item in native)
    require(bindings[0]['line'] < first_line, 'Histogram queue binding must precede its original model work')
    bins = output[168:]
    notification = bytes.fromhex('0d200c210a0401800100') + bins
    ack = bytes.fromhex('0d2048110c00018000005900')
    wire = bytes.fromhex('0d2048010c00018001010000')
    main_schema = set(('pid tid cycle snapshot_id event_role source destination command bytes original_request raw original_fnv1a64 canonical8 queue_bound '
        'queue_source bridge_rc validation_rc used required model_result_bytes model_result_fnv1a64 model_instance '
        'config_generation before_config_generation frame_generation before_frame_generation lease_generation '
        'notification_bytes notification_fnv1a64 selector Y_fnv1a64 R_fnv1a64 G_fnv1a64 B_fnv1a64 request_owned '
        'model_complete ACK_AP_consumed notification_AP_consumed AP_consumed busy guard faults functional_model '
        'physical_ASIC_verified original_CP_FIFO_verified physical_CP_RTOS_verified UI_applied continuous_histogram '
        'capture_verified').split())
    lease_schema = set(('pid cycle snapshot_id role destination source bytes pointer retained allocate_attempted allocation_returned '
        'allocation_alias allocate_rc send_started send_inflight queued send_rc received sender_tid receiver_tid '
        'free_tid free_attempted free_rc freed consumed releasing faults wire_fnv1a64').split())
    main_tags = {'FUNCTIONAL_HISTOGRAM_' + name: name for name in ('REQUEST_FREE', 'SEND', 'COMPLETE', 'RECEIVE', 'AP_FREE')}
    records = [row for row in records if row['tag'] != 'FUNCTIONAL_HISTOGRAM_QUEUE_BOUND']
    groups = {}
    for row in records:
        f = row['fields']
        is_lease = row['tag'] == 'FUNCTIONAL_HISTOGRAM_LEASE'
        require((is_lease or row['tag'] in main_tags) and 'diagnostic' not in row and
                set(f) == (lease_schema if is_lease else main_schema),
                'failed/unknown/malformed Histogram producer record')
        for key in ('pid', 'cycle', 'snapshot_id', 'role' if is_lease else 'event_role'):
            require(re.fullmatch(r'(?:0|[1-9][0-9]*)', f[key]), 'Histogram identity/role grammar differs')
        snapshot_id = number(f['snapshot_id'])
        require(snapshot_id > 0 and number(f['pid']) == transport['pid'] and number(f['cycle']) == 1,
                'Histogram snapshot ID/PID/cycle differs')
        group = groups.setdefault(snapshot_id, {'leases': {}})
        if not is_lease:
            require('row' not in group, 'Histogram duplicate snapshot main record')
            group['row'] = row
            continue
        n = {}
        for key, text in f.items():
            if key in ('pointer', 'allocation_returned'):
                require(text == '(nil)' or re.fullmatch(r'0x[1-9a-f][0-9a-f]{0,15}', text),
                        'Histogram lease pointer grammar differs')
                n[key] = 0 if text == '(nil)' else number(text)
            elif key == 'wire_fnv1a64':
                n[key] = int(writeback.hash_hex(text, 16), 16)
            else:
                pattern = r'(?:0|0x[1-9a-f][0-9a-f]{0,7})' if key in ('source', 'destination') else r'(?:0|[1-9][0-9]*)'
                require(re.fullmatch(pattern, text), 'Histogram lease numeric grammar differs: ' + key)
                n[key] = number(text)
        role = n['role']
        require(role in (1, 2, 3) and role not in group['leases'], 'Histogram duplicate/unknown lease role')
        group['leases'][role] = (row, n)
    needed(set(groups) == set(range(1, 9)), 'Histogram complete increasing snapshot IDs1..8 required')
    snapshots = []
    for snapshot_id, group in sorted(groups.items()):
        needed('row' in group and set(group['leases']) == {1, 2, 3},
               'Histogram complete main and three-role lease snapshot required')
        row = group['row']
        lease_rows = [group['leases'][role][0] for role in (1, 2, 3)]
        require(all(a['line'] < b['line'] for a, b in zip([row] + lease_rows, lease_rows)),
                'Histogram own snapshot logger order differs')
        snapshots.append((row, main_tags[row['tag']], [group['leases'][role][1] for role in (1, 2, 3)]))
    names = [name for _, name, _ in snapshots]
    needed(all(names.count(name) == count for name, count in dict(REQUEST_FREE=1, SEND=2, COMPLETE=1,
           RECEIVE=2, AP_FREE=2).items()), 'Histogram request/ACK/notification actual send/receive/free census required')
    require(names[0] == 'REQUEST_FREE' and len(snapshots) == 8 and tx['line'] < snapshots[0][0]['line'],
            'Histogram original request/model/lifecycle order differs')
    complete = names.index('COMPLETE')
    require(complete > max(i for i, name in enumerate(names) if name == 'SEND'),
            'Histogram dispatch completed before both real sends')
    event_at = {}
    for index, (row, name, _) in enumerate(snapshots):
        role = number(row['fields']['event_role'])
        require(role in ({'REQUEST_FREE': (1,), 'COMPLETE': (0,)}.get(name, (2, 3))) and
                (name, role) not in event_at, 'Histogram duplicate/wrong actual event role')
        event_at[name, role] = index
    require(set(event_at) == {('REQUEST_FREE', 1), ('COMPLETE', 0),
            *((name, role) for name in ('SEND', 'RECEIVE', 'AP_FREE') for role in (2, 3))},
            'Histogram each actual role must send/receive/free exactly once')
    at_role = {role: {key: event_at[name, role] for name, key in
               (('SEND', 'queued'), ('RECEIVE', 'received'), ('AP_FREE', 'freed'))} for role in (2, 3)}
    require(at_role[2]['queued'] < min(at_role[3]['queued'], at_role[3]['received']),
            'Histogram ACK-first independent sends missing')
    pointers, receivers = {}, {}
    for role in (2, 3):
        at = at_role[role]
        require(0 < at['received'] < at['freed'], 'Histogram native receive/free order differs')
        live = snapshots[at['received']][2][role - 1]
        pointers[role], receivers[role] = live['pointer'], live['receiver_tid']
        length = 12 if role == 2 else 1034
        require(0 < pointers[role] <= 2**64 - length and 0 < receivers[role] < 2**31,
                'Histogram independent live receive allocation/receiver missing')
    require(pointers[2] + 12 <= pointers[3] or pointers[3] + 1034 <= pointers[2],
            'Histogram ACK/notification live allocations alias')
    original_request = snapshots[0][0]['fields']['original_request']
    require(re.fullmatch(r'0x[1-9a-f][0-9a-f]{0,15}', original_request) and
            0 < number(original_request) <= 2**64 - 12, 'Histogram original request address missing')
    previous = {role: dict.fromkeys(('send_started', 'queued', 'received', 'free_attempted', 'freed'), 0)
                for role in (2, 3)}
    previous_busy = previous_guard = 1
    for index, (row, name, leases) in enumerate(snapshots):
        f = row['fields']
        event_role = number(f['event_role'])
        busy, guard = number(f['busy']), number(f['guard'])
        require(0 <= guard <= busy <= 1 and busy <= previous_busy and guard <= previous_guard and
                (index > at_role[3]['queued'] or busy == guard == 1) and
                (index < complete or busy == guard == 0), 'Histogram actual busy/guard lifecycle differs')
        previous_busy, previous_guard = busy, guard
        require(f['original_request'] == original_request, 'Histogram retired original request identity changed')
        immutable = dict(pid=transport['pid'], cycle=1, source=source, destination=0x92840747,
            command=0x148, bytes=12, queue_bound=1, queue_source=source, bridge_rc=0, validation_rc=0,
            used=1192, required=1192, model_result_bytes=1192, notification_bytes=1034, selector=1,
            request_owned=1, model_complete=1, faults=0,
            functional_model=1, physical_ASIC_verified=0, original_CP_FIFO_verified=0, physical_CP_RTOS_verified=0,
            UI_applied=0, continuous_histogram=0, capture_verified=0, model_instance=transport['model_instance'])
        immutable.update({key: value[key] for key in ('config_generation', 'before_config_generation',
            'frame_generation', 'before_frame_generation', 'lease_generation')})
        for key, expected in immutable.items():
            require(number(f[key]) == expected, 'Histogram native model/origin/scope differs: ' + key)
        require(raw_hex(f, 'raw', 12) == wire and raw_hex(f, 'canonical8', 8) == canonical and
                int(writeback.hash_hex(f['original_fnv1a64'], 16), 16) == fnv(wire) and
                int(writeback.hash_hex(f['model_result_fnv1a64'], 16), 16) == fnv(output) and
                int(writeback.hash_hex(f['notification_fnv1a64'], 16), 16) == fnv(notification) and
                all(int(writeback.hash_hex(f[channel + '_fnv1a64'], 16), 16) == fnv(bins[c * 256:(c + 1) * 256])
                    for c, channel in enumerate(('Y', 'R', 'G', 'B'))),
                'Histogram complete result1192/notification1034/channel bytes or FNV differs')
        caller = origin['producer_tid']
        expected_tid = caller
        for role, lease in enumerate(leases, 1):
            expected = dict(pid=transport['pid'], cycle=1, snapshot_id=index + 1, role=role,
                destination=0x92840747 if role == 1 else source,
                source=source if role == 1 else 0x92840747, bytes=1034 if role == 3 else 12,
                allocation_alias=0, allocate_rc=0, send_rc=0, free_rc=0, faults=0,
                sender_tid=caller, wire_fnv1a64=fnv(wire if role == 1 else ack if role == 2 else notification))
            if role == 1:
                expected.update(pointer=0, retained=0, allocate_attempted=0, allocation_returned=0,
                    send_started=0, send_inflight=0, queued=0, received=0, receiver_tid=0,
                    free_tid=caller, free_attempted=1, freed=1, consumed=0, releasing=0)
            else:
                at = at_role[role]
                flags = ('send_started', 'send_inflight', 'queued', 'received', 'free_attempted', 'freed', 'releasing', 'consumed')
                require(all(lease[key] in (0, 1) for key in flags), 'Histogram lease boolean differs')
                for key in previous[role]:
                    require(lease[key] >= previous[role][key], 'Histogram lease state regressed')
                    previous[role][key] = lease[key]
                started, inflight, queued, received, attempted, freed, releasing, consumed = (lease[key] for key in flags)
                require(started == int(queued or inflight) and not (queued and inflight) and
                        received <= started and freed <= attempted <= received and
                        (not releasing or not freed) and (not attempted or freed or releasing) and
                        (not attempted or index > at['received']) and
                        (index < at['queued'] or queued) and (index < at['received'] or received) and
                        (index < at['freed'] or freed) and
                        (role != 3 or index > at_role[2]['queued'] or not started),
                        'Histogram actual send/receive/free flags contradict their events')
                if event_role == role:
                    require((name == 'SEND' or not releasing) and
                            (name != 'SEND' or queued and not inflight) and
                            (name != 'RECEIVE' or received and not attempted and not freed) and
                            (name != 'AP_FREE' or attempted and freed),
                            'Histogram event role lacks its actual send/live receive/real free')
                    expected_tid = receivers[role] if name == 'RECEIVE' or name == 'AP_FREE' and role == 3 else caller
                not_allocated = index == 0
                require(not not_allocated or not any(lease[key] for key in flags),
                        'Histogram output used before request free/allocation')
                expected.update(pointer=0 if freed or not_allocated else pointers[role],
                    retained=int(not freed and not not_allocated), allocate_attempted=int(not not_allocated),
                    allocation_returned=0 if not_allocated else pointers[role], queued=queued, received=received,
                    send_started=started, send_inflight=inflight,
                    receiver_tid=receivers[role] if received else 0,
                    free_tid=(caller if role == 2 else receivers[role]) if freed else 0,
                    free_attempted=attempted, freed=freed, releasing=releasing,
                    consumed=int(queued and received and freed and not inflight and not releasing))
            require(lease == expected, 'Histogram immutable role/actual source/send/ticket/receive/free state differs')
        require(number(f['tid']) == expected_tid and
                number(f['ACK_AP_consumed']) == leases[1]['consumed'] and
                number(f['notification_AP_consumed']) == leases[2]['consumed'] and
                number(f['AP_consumed']) == int(leases[1]['consumed'] and leases[2]['consumed'] and not busy),
                'Histogram future sender-free/notification receiver-free or overall consumption differs')
    needed(snapshots[-1][0]['fields']['AP_consumed'] == '1', 'Histogram both original AP frees and dispatch completion required')
    result.update(verified=True, first_frame_verified=True, readback_verified=True,
        native_ACK_and_notification_AP_free=True, AP_consumed=True, first=tx['first'],
        queue_binding=bindings[0], model_instance=transport['model_instance'],
        config_generation=value['config_generation'], frame_generation=value['frame_generation'],
        lease_generation=value['lease_generation'], result1192_hex=output.hex(), notification1034_hex=notification.hex(),
        bins_fnv1a64=f'{fnv(bins):016x}', channel_fnv1a64={channel: f'{fnv(bins[c * 256:(c + 1) * 256]):016x}'
            for c, channel in enumerate(('virtual-Y', 'R', 'G', 'B'))},
        request_payload=tx['request_payload'], output_payloads=tx['output_payloads'],
        ACK_receiver_tid=receivers[2], ACK_free_tid=origin['producer_tid'],
        notification_receiver_tid=receivers[3], notification_free_tid=receivers[3])
    return result


def check_layout_stage(run, manifest, rows, transport=None):
    """Guest-local register copy/ACK only; a late op7 has its own model and ACK cycle."""
    records = [row for row in rows if row['tag'].startswith('FUNCTIONAL_LAYOUT_STAGE')]
    result = dict(required=bool(records), verified=False, cycles=[], applied_receipts=[],
                  stage_only=True, semantic_applied=False, frame_consumed=False, model_initialized=False,
                  hardware_ready=False, capture_verified=False, physical_asic_compatibility_verified=False,
                  original_CP_FIFO_verified=False, original_RTOS_verified=False,
                  late_application_verified=False, status='absent')
    if not records:
        return result
    backup = manifest.get('backup_transport')
    require(type(backup) is dict and all(
        typed_equal(manifest.get('functional_camera_' + key), value) and
        typed_equal(backup.get('functional_camera_' + key), value) for key, value in STARTUP_LAYOUT_POLICY.items()),
        'startup layout stage lacks the exact typed guest-local policy')
    names = ('READBACK', 'REQUEST_FREE', 'SEND', 'COMPLETE', 'RECEIVE', 'AP_FREE')
    tags = {'FUNCTIONAL_LAYOUT_STAGE_' + name: name for name in names + ('APPLIED_RECEIPT',)}
    schema = dict.fromkeys(('cycle stage_generation requests completed_cycles busy faults bytes bank_written '
                           'readback_verified request_owned request_freed queued received AP_consumed sender_tid '
                           'receiver_tid free_tid send_inflight releasing allocate_rc send_rc free_rc validation_rc '
                           'request_free_rc allocation_alias stage_only semantic_applied frame_consumed hardware_ready '
                           'capture_verified physical_ASIC_verified original_CP_FIFO_verified physical_CP_RTOS_verified '
                           'applied_receipt_verified applied_stage_generation applied_model_instance '
                           'applied_config_generation applied_frame_generation').split(), 'u64')
    schema.update(pid='tid', tid='tid', source='hex32', destination='hex32', command='hex32',
                  original_fnv1a64='digest', bank_fnv1a64='digest', readback_fnv1a64='digest',
                  applied_result_fnv1a64='digest', request_retained='pointer', ack_retained='pointer',
                  allocation_returned='pointer', raw='raw40', bank32='raw32', copied_readback32='raw32', ack_wire='raw12')
    groups, applied, owner = {}, [], None
    canonical = bytes.fromhex(LAYOUT_POLICY['layout_initial_body_hex'])
    wire, ack = bytes.fromhex('0d204c0128000180') + canonical, bytes.fromhex('0d204c110c00018000005900')
    zero = ('faults releasing allocate_rc send_rc free_rc validation_rc request_free_rc allocation_alias '
            'semantic_applied frame_consumed hardware_ready capture_verified physical_ASIC_verified '
            'original_CP_FIFO_verified physical_CP_RTOS_verified').split()
    for row in records:
        f, n = row['fields'], {}
        require(row['tag'] in tags and 'diagnostic' not in row and set(f) == set(schema),
                'failed/unknown/malformed startup layout producer grammar')
        name = tags[row['tag']]
        for key, kind in schema.items():
            text = f[key]
            if kind.startswith('raw'):
                raw_hex(f, key, int(kind[3:]))
            elif kind == 'digest':
                n[key] = int(writeback.hash_hex(text, 16), 16)
            elif kind == 'pointer':
                require(text == '(nil)' or re.fullmatch(r'0x[1-9a-f][0-9a-f]{0,15}', text),
                        'startup layout pointer grammar differs: ' + key)
                n[key] = 0 if text == '(nil)' else number(text)
            else:
                require(re.fullmatch(r'0x[1-9a-f][0-9a-f]*' if kind == 'hex32' else r'(?:0|[1-9][0-9]*)', text),
                        'startup layout number grammar differs: ' + key)
                n[key] = number(text)
                maximum = 2**31 if kind == 'tid' else 2**32 if kind == 'hex32' or key in (
                    'requests', 'completed_cycles', 'bytes') else 2**64
                require(n[key] < maximum and (kind != 'tid' or n[key] > 1),
                        'startup layout number range differs: ' + key)
        owner = n['pid'] if owner is None else owner
        require(n['pid'] == owner and n['source'] & 0xffff0000 == 0x81cf0000 and
                n['destination'] == 0x92840747 and n['command'] == 0x14c and n['bytes'] == 40 and
                f['raw'] == wire.hex() and f['bank32'] == f['copied_readback32'] == canonical.hex() and
                f['ack_wire'] == ack.hex() and n['original_fnv1a64'] == fnv(wire) and
                n['bank_fnv1a64'] == n['readback_fnv1a64'] == fnv(canonical),
                'startup layout original wire/source/D/bank/readback digest differs')
        require(all(n[key] == 0 for key in zero) and
                all(n[key] == 1 for key in ('bank_written', 'readback_verified', 'request_owned', 'stage_only')),
                'startup layout failed register copy or promoted semantic/frame/ready/physical claim')
        require(n['cycle'] == n['stage_generation'] == n['requests'] > 0 and
                1 < n['sender_tid'] < 2**31 and (name == 'APPLIED_RECEIPT' or n['sender_tid'] == n['tid']),
                'startup layout immutable generation/sender differs')
        if name == 'APPLIED_RECEIPT':
            require(n['applied_receipt_verified'] == 1 and n['applied_stage_generation'] == n['stage_generation'] and
                    all(n[key] > 0 for key in ('applied_model_instance', 'applied_config_generation',
                                             'applied_frame_generation', 'applied_result_fnv1a64')),
                    'startup layout late application receipt identity differs')
            applied.append((row, n))
        else:
            require(all(n[key] == 0 for key in ('applied_receipt_verified', 'applied_stage_generation',
                        'applied_model_instance', 'applied_config_generation', 'applied_frame_generation',
                        'applied_result_fnv1a64')), 'startup layout premature late application claim')
        group = groups.setdefault(n['cycle'], {})
        if name != 'APPLIED_RECEIPT':
            require(name not in group, 'duplicate startup layout lifecycle receipt')
            group[name] = (row, n)
    require(list(groups) == list(range(1, len(groups) + 1)), 'startup layout cycle/generation gap or reuse')
    previous = 0
    for cycle, group in groups.items():
        needed(set(group) == set(names), 'startup layout READBACK/request free/send/complete/receive/AP free required')
        at = {name: row['line'] for name, (row, _) in group.items()}
        require(previous < at['READBACK'] < at['REQUEST_FREE'] < at['SEND'] < at['COMPLETE'] and
                at['REQUEST_FREE'] < at['RECEIVE'] < at['AP_FREE'], 'startup layout lifecycle order differs')
        first = group['READBACK'][1]
        pointer = group['REQUEST_FREE'][1]['ack_retained']
        request = first['request_retained']
        require(request > 0 and pointer > 0 and request <= 2**64 - 40 and pointer <= 2**64 - 12 and
                (pointer + 12 <= request or request + 40 <= pointer), 'startup layout independent ACK/request lease missing or aliased')
        for name, (row, n) in group.items():
            line = row['line']
            queued, received, freed = (int(line >= at[key]) for key in ('SEND', 'RECEIVE', 'AP_FREE'))
            busy = int(line < at['COMPLETE'])
            consumed = int(queued and received and freed and not busy)
            expected = dict(busy=busy, queued=queued, received=received, AP_consumed=consumed,
                            completed_cycles=cycle - 1 + consumed, request_freed=int(name != 'READBACK'),
                            request_retained=request if name == 'READBACK' else 0,
                            ack_retained=0 if freed or name == 'READBACK' else pointer,
                            allocation_returned=0 if name == 'READBACK' else pointer,
                            send_inflight=int(name in ('RECEIVE', 'AP_FREE') and line < at['SEND']),
                            receiver_tid=first['tid'] if received else 0, free_tid=first['tid'] if freed else 0,
                            source=first['source'], pid=owner, tid=first['tid'], sender_tid=first['tid'])
            require(all(n[key] == value for key, value in expected.items()),
                    'startup layout original owner/cycle/receive/free state differs')
        previous = max(at.values())
        result['cycles'].append(dict(cycle=cycle, stage_generation=cycle, pid=owner, sender_tid=first['tid'],
            source=first['source'], destination=first['destination'], original_request_fnv1a64=f'{fnv(wire):016x}',
            bank_fnv1a64=f'{fnv(canonical):016x}', readback_verified=True, AP_consumed=True,
            receive_line=at['RECEIVE'], free_line=at['AP_FREE'], complete_line=previous))
    path_tags = {'FUNCTIONAL_VDF_PATH_' + name for name in names[1:]}
    require(all(previous < row['line'] for row in rows if row['tag'] in path_tags),
            'startup layout register stage occurred after display route work')
    for row in rows:
        if row['tag'] != 'FUNCTIONAL_CAMERA_TRANSFER':
            continue
        f = row['fields']
        needed('op' in f, f'startup layout transfer line {row["line"]}: missing op; diagnostic={row.get("diagnostic")!r}')
        require('diagnostic' not in row and f.get('error') == '0' and f.get('readback_closed') == '1',
                f'startup layout malformed/failed actual bridge transfer line {row["line"]}')
        require(number(f['op']) not in VDF_OPERATIONS or previous < row['line'],
                'startup layout register stage occurred after display route work')
    result.update(verified=True, status='staged-unapplied', owner_pid=owner, owner_bound_to_mailbox=False)
    seen, previous_application = set(), None
    for row, n in applied:
        last = groups[len(groups)]['AP_FREE'][1]
        require(n['cycle'] == len(groups) and row['line'] > previous and all(n[key] == last[key] for key in
                ('pid', 'source', 'destination', 'command', 'bytes', 'sender_tid', 'receiver_tid', 'free_tid')) and
                all(n[key] == value for key, value in dict(busy=0, request_freed=1, request_retained=0,
                    ack_retained=0, allocation_returned=last['allocation_returned'], queued=1, received=1,
                    AP_consumed=1, completed_cycles=len(groups), send_inflight=0).items()),
                'startup layout late receipt has stale stage or unfinished original free')
        identity = tuple(n[key] for key in ('applied_model_instance', 'applied_config_generation', 'applied_frame_generation'))
        require(identity not in seen and (previous_application is None or
                row['line'] > previous_application[0] and identity[0] == previous_application[1][0] and
                all(current > old for current, old in zip(identity[1:], previous_application[1][1:]))),
                'duplicate/regressed startup layout late application receipt')
        seen.add(identity)
        previous_application = (row['line'], identity)
        result['applied_receipts'].append(row)
    if applied:
        result['status'] = 'staged-late-application-unverified'
    if transport is not None:
        require(owner == transport['pid'] and all(previous < tx['line'] for tx in transport['transfers']
                if tx['opcode'] in VDF_OPERATIONS), 'startup layout owner/phase differs from actual mailbox/display')
        result['owner_bound_to_mailbox'] = True
        if applied:
            display = check_vdf_path(run, rows, transport)
            candidates = [tx for tx in transport['transfers'] if tx['opcode'] == 7]
            used, applications, previous_lease = set(), [], 0
            for row, n in applied:
                matches = [tx for tx in candidates if tx['line'] < row['line'] and
                    tx['model_instance'] == n['applied_model_instance'] and
                    tx['origin']['producer_tid'] == n['tid'] and
                    fnv(transfer_output(run, tx)) == n['applied_result_fnv1a64']]
                require(len(matches) == 1 and matches[0]['first'] not in used,
                        'startup layout late receipt lacks its own actual original014c/op7 result192')
                tx = matches[0]
                output = transfer_output(run, tx)
                value = vdf_result(output, canonical, transport['model_instance'], 7, output[128:144])
                require(payload_read(run, tx['request_payload']) == canonical and output[160:] == canonical and
                        value['config_generation'] == n['applied_config_generation'] and
                        value['frame_generation'] == n['applied_frame_generation'] and
                        value['lease_generation'] > previous_lease and
                        any(c['first'] == tx['first'] and c['opcode'] == 7 for c in display['cycles']),
                        'startup layout bank/result192 tail/model/config/frame differs')
                used.add(tx['first'])
                previous_lease = value['lease_generation']
                applications.append(dict(first=tx['first'], stage_generation=n['stage_generation'],
                    model_instance=transport['model_instance'], config_generation=value['config_generation'],
                    frame_generation=value['frame_generation'], result_fnv1a64=f'{fnv(output):016x}',
                    actual_RGB_consumer_retired=True))
            result.update(late_application_verified=True, status='staged-with-separate-late-op7', applications=applications)
    return result


def mailbox_header(row, mailbox):
    raw = bytes.fromhex(row['raw_header_hex'])
    require(len(raw) == 512 and raw.hex() == row['raw_header_hex'] and sha(raw) == row['raw_header_sha256'],
            'raw broker request header digest/size differs')
    get32 = lambda n: struct.unpack_from('<I', raw, n)[0]
    get64 = lambda n: struct.unpack_from('<Q', raw, n)[0]
    require((get32(0), get32(4), get32(8), get32(12), get64(16)) ==
            (0x314d4346, 1, mailbox['pid'], 1, mailbox['nonce']) and
            list(struct.unpack_from('<16Q', raw, 128)) == mailbox['pages'], 'broker PID/instance/pages differ')
    require(raw[44:52] == bytes(8) and raw[64:96] == bytes(32) and raw[116:120] == bytes(4) and
            raw[256:] == bytes(256), 'broker request reserved/response fields not pristine')
    op, count, capacity = get32(32), get32(36), get32(40)
    flags = get32(52)
    require(flags in (0, 1) and (not flags or op in (11, 64, 65, 66)) and (op != 11 or flags == 1),
            'broker actual request origin flags differ')
    require(type(row.get('opcode')) is int and get64(24) == row['sequence'] and op == row['opcode'] and
            op in OPS and count in OPS[op] and
            count == row['request_bytes'] and capacity <= DATA_BYTES and get64(56) == row['request_fnv1a64'],
            'broker actual request header/opcode/size differs')
    origin = dict(producer_tid=get32(96), source=get32(100), destination=get32(104),
                  command=get32(108), bytes=get32(112), fnv1a64=get64(120))
    require(0 < origin['producer_tid'] < 2**31 and origin['source'] and origin['destination'] and origin['bytes'],
            'missing original producer/TID/SID')
    return raw, origin, capacity


def check_transport(run, manifest, rows, events, build):
    require(build.get('qemu_sha256') in (QEMU_SHA256, READONLY_SCOPE_QEMU_SHA256),
            'transport QEMU is not an admitted batch executable')
    runner = json_file(run, 'functional-camera-runner.json')
    require(runner.get('schema') == 'functional-camera-runner-v1' and runner.get('profile') == PROFILE and
            runner.get('phase') == 'closed' and runner.get('error') is None and runner.get('broker_started') is True and
            typed_equal(runner, manifest.get('functional_camera_runtime')), 'runner not safely closed/same manifest')
    for key in ('capture_verified', 'physical_ASIC_compatibility_verified', 'original_CP_RAM_verified',
                'standalone_host_media_write'):
        require(runner.get(key) is False, 'runner scope promoted: ' + key)
    close = ('safe_to_close', 'mailbox_detached', 'debugger_stopped', 'protocol_physmode_restored', 'worker_stopped')
    require(type(runner.get('cleanup')) is dict and all(runner['cleanup'].get(key) is True for key in close) and
            runner['cleanup'].get('errors') == [] and runner.get('console_sha256_at_close') == sha(read(run, 'console.log', MAX_LOG)),
            'unsafe/failed cleanup or console changed after runner close')
    artifact = runner.get('artifact', {})
    for key, expected in (('library_sha256', build['model_sha256']), ('build_receipt_sha256', build['model_build_sha256']),
                          ('source_archive_sha256', build['model_source_archive_sha256']), ('qemu_sha256', build['qemu_sha256'])):
        require(artifact.get(key) == expected, 'runner artifact differs from frozen batch: ' + key)
    require(artifact.get('library') == str(RUNTIME / 'functional-camera-model.so') and
            artifact.get('abi_header_sha256') == manifest.get('files', {}).get(str(RUNTIME / 'functional-camera-abi.h')) and
            type(artifact.get('abi')) is dict and artifact['abi'].get('version') == 1 and
            artifact['abi'].get('entry_points') == ['fcam_model_create', 'fcam_model_destroy', 'fcam_model_request'],
            'runner host-model library/ABI binding missing')
    needed(events and events[0].get('kind') == 'binding', 'broker: initial binding event')
    binding, mailbox = events[0], runner.get('mailbox_evidence', {}).get('mailbox', {})
    require(typed_equal(binding.get('mailbox'), mailbox) and binding.get('actual_core_sha256') == build['model_sha256'],
            'broker actual C library/mailbox differs')
    require(type(mailbox.get('pid')) is int and 1 < mailbox['pid'] < 2**31 and
            type(mailbox.get('nonce')) is int and 0 < mailbox['nonce'] < 2**64 and
            type(mailbox.get('pages')) is list and len(mailbox['pages']) == 16 and
            all(type(page) is int and 0x400000000 <= page <= 0x53ffff000 and page % 4096 == 0 for page in mailbox['pages']) and
            len(set(mailbox['pages'])) == 16 and mailbox.get('phys0') == mailbox['pages'][0], 'invalid actual guest mailbox')
    config = binding.get('config', {})
    needed(type(binding.get('payload_policy')) is dict, 'binding: actual immutable payload_policy')
    require(typed_equal(binding['payload_policy'], dict(directory='functional-camera-data', per_file_bytes=64 * 1024**2,
                        total_bytes=512 * 1024**2, max_files=65536, source_kind='actual_hardware_transfer')),
            'broker immutable payload policy differs')
    info = run.stat()
    require(config.get('run') == str(run) and config.get('run_identity') == [info.st_dev, info.st_ino] and
            config.get('qemu_sha256') == build['qemu_sha256'] and
            typed_equal(config.get('owner'), runner.get('owner')) and
            typed_equal(config.get('qemu'), runner.get('debugger_handoff', {}).get('qemu_identity')),
            'mixed-run/owner/QEMU transport binding')
    require(Path(config.get('qemu', {}).get('exe', '')).name == 'qemu-system-aarch64' and
            config['qemu']['pid'] == runner['debugger_handoff']['qemu_pid'], 'original QEMU process identity differs')
    counts, transactions, pending = {}, {}, None
    current_bank, last_crank, consumed_bank = None, 0, 0
    current_crank, last_movie, movie_pairs = None, 0, set()
    current_movie, last_ou, ou_tuples = None, 0, set()
    payload_budget, paths, payload_inodes = [512 * 1024**2, 65536], set(), set()
    def actual_payload(event, direction, tx, token, total, offset):
        key = 'request_payload' if direction == 'in' else 'output_payload'
        reference = event.get(key)
        needed(type(reference) is dict, 'broker ' + event['kind'] + ': ' + key)
        seq, op = tx['request']['sequence'], tx['request']['opcode']
        require(reference.get('path') == f'functional-camera-data/{seq:020d}-{direction}.bin' and
                reference.get('direction') == direction and reference.get('producer_event') == event['event'] and
                reference.get('sequence') == seq and reference.get('opcode') == op and
                reference.get('model_instance') == mailbox['nonce'] and typed_equal(reference.get('origin'), tx['origin']) and
                all(type(reference.get(k)) is int and reference[k] == v for k, v in
                    (('token', token), ('total', total), ('offset', offset))), 'payload original request/result binding differs')
        raw = payload_read(run, reference, payload_budget)
        inode = (reference['device'], reference['inode'])
        require(reference['path'] not in paths and inode not in payload_inodes, 'payload file/inode reused')
        paths.add(reference['path'])
        payload_inodes.add(inode)
        return raw
    active_result, source_cleanup = None, None
    for event in events:
        require(type(event.get('model_instance')) is int and event['model_instance'] == mailbox['nonce'], 'mixed model instance')
        kind = event.get('kind')
        require(kind in ('binding', 'attached', 'request', 'core_result', 'ap_source_result', 'source_cancel',
                         'response', 'physical_mode_restored',
                         'resume_suppressed', 'detach_commit', 'mailbox_detached', 'cancel_cleanup',
                         'debugger_disconnected', 'cleanup', 'model_frame', 'model_parameter_bank',
                         'model_crank_control', 'crank_control_rejected', 'model_movie_format',
                         'movie_format_rejected', 'model_ou_crank_control',
                         'ou_crank_control_rejected'), 'failed/rejected/unknown broker event')
        counts[kind] = counts.get(kind, 0) + 1
        if counts.get('detach_commit'):
            require(kind in ('detach_commit', 'physical_mode_restored', 'mailbox_detached',
                             'debugger_disconnected', 'cleanup'), 'model/source access after detach')
        if kind == 'request':
            require(source_cleanup is None, 'model/source request after source finalizer')
            seq = uint(event.get('sequence'))
            require(pending is None and seq == len(transactions) + 1, 'request gap/replay/interleaving')
            header, origin, capacity = mailbox_header(event, mailbox)
            writeback.hash_hex(event.get('request_sha256'), 64)
            if event['request_bytes'] == 0:
                require(event['request_sha256'] == sha(b'') and event['request_fnv1a64'] == fnv(b''),
                        'empty model request has different actual byte digest')
            source_call = event['opcode'] != 66 and (event['opcode'] == 11 or struct.unpack_from('<I', header, 52)[0] == 1)
            if event['opcode'] in (64, 65):
                require(active_result is not None and source_call == active_result['source_call'] and
                        (not source_call or header[8:12] + header[16:24] + header[52:56] + header[96:116] + header[120:128] ==
                         active_result['source_binding']), 'retained source/core provider or API40 binding changed')
            pending = {'request': event, 'origin': origin, 'capacity': capacity, 'raw_header': header,
                       'source_call': source_call}
            require(typed_equal(event.get('origin'), origin), 'raw/header request origin differs')
            token = active_result['token'] if active_result and event['opcode'] in (64, 65) else 0
            total = active_result['total'] if token else 0
            offset = active_result['cursor'] if token else 0
            incoming = actual_payload(event, 'in', pending, token, total, offset)
            require(len(incoming) == event['request_bytes'] and sha(incoming) == event['request_sha256'] and
                    fnv(incoming) == event['request_fnv1a64'], 'actual request bytes/header digest differs')
            if event['opcode'] == 64:
                require(active_result is not None and struct.unpack_from('<2Q', incoming) == (token, offset) and
                        0 < struct.unpack_from('<I', incoming, 16)[0] <= capacity and incoming[20:] == bytes(4),
                        'actual READ_RESULT24 token/cursor/capacity differs')
            elif event['opcode'] == 65:
                require(active_result is not None and active_result['cursor'] == total and
                        struct.unpack('<2Q', incoming) == (token, active_result['fnv']),
                        'actual RELEASE_RESULT16 token/whole-output FNV differs')
            elif event['opcode'] != 66:
                require(active_result is None or event['opcode'] == 2, 'new operation overlaps retained result')
            if event['opcode'] == 33:
                require(not incoming or incoming == b'\x01\x00\x00\x00',
                        'actual video frame force-IDR flags differ')
            if event['opcode'] == 17:
                require(incoming[:4] == b'\x05\x00\x38\x40' and incoming[8] in (2, 10, 12, 8, 9, 3) and
                        incoming[9:12] == bytes(3) and origin['source'] == 0x80020002 and
                        origin['destination'] == 0x90040193 and origin['command'] == 0x4038 and
                        origin['bytes'] == 16 and origin['fnv1a64'] == fnv(incoming),
                        'actual retained capture lacks exact4038 origin')
            pending['request_data'] = incoming
            transactions[seq] = pending
        elif kind in ('core_result', 'ap_source_result', 'response'):
            result_kind = 'ap_source_result' if pending is not None and pending['source_call'] else 'core_result'
            require(pending is not None and event.get('sequence') == pending['request']['sequence'] and
                    event.get('opcode') == pending['request']['opcode'] and kind not in pending and
                    kind in (result_kind, 'response'), 'unmatched/duplicate/wrong provider result/response')
            if (kind == 'core_result' and pending['request']['opcode'] == 23 and
                    event.get('actual_c_result') is None and type(event.get('admission_error')) is int and
                    event['admission_error'] == -errno.EBUSY):
                require(event.get('actual_core_sha256') == build['model_sha256'] and
                        typed_equal(event.get('origin'), pending['origin']) and
                        typed_equal(event.get('request_payload'), pending['request'].get('request_payload')),
                        'OU crank rejected admission original call/library binding differs')
                pending[kind] = event
                continue
            if (kind == 'core_result' and pending['request']['opcode'] in (21, 22, 23) and
                    type(event.get('actual_c_result')) is int and -4095 <= event['actual_c_result'] < 0):
                require(event.get('actual_core_sha256') == build['model_sha256'] and
                        typed_equal(event.get('origin'), pending['origin']) and
                        typed_equal(event.get('request_payload'), pending['request'].get('request_payload')),
                        'rejected crank control actual C call binding differs')
                pending[kind] = event
                continue
            if pending['source_call']:
                require(event.get('actual_c_result', 1) is None and type(event.get('actual_source_result')) is int and
                        event['actual_source_result'] == 0 and event.get('source_provider_kind') == 'paused-source-snapshot-v1',
                        'actual AP source execution failed/disguised as C')
            else:
                require(type(event.get('actual_c_result')) is int and event['actual_c_result'] == 0 and
                        'actual_source_result' not in event, 'actual model C execution failed')
            if pending['request']['opcode'] == 20:
                require(event.get('actual_core_sha256') == build['model_sha256'],
                        'parameter bank actual C result/library binding differs')
            elif pending['request']['opcode'] in (21, 22, 23):
                require(event.get('actual_core_sha256') == build['model_sha256'],
                        'crank control actual C result/library binding differs')
            count, token, total, offset = (uint(event.get(key)) for key in ('returned_bytes', 'token', 'total', 'offset'))
            require(count <= pending['capacity'] and total <= 64 * 1024**2 and offset <= total and
                    (token and 0 < count <= total - offset or not token and not total and not offset), 'actual C result bounds')
            writeback.hash_hex(event.get('returned_sha256'), 64)
            pending[kind] = event
            if kind == result_kind:
                require(typed_equal(event.get('origin'), pending['origin']) and
                        typed_equal(event.get('request_payload'), pending['request'].get('request_payload')),
                        'actual C request reference/origin differs')
                output = actual_payload(event, 'out', pending, token, total, offset)
                require(len(output) == count and sha(output) == event['returned_sha256'] and
                        fnv(output) == uint(event.get('returned_fnv1a64')), 'actual C returned byte digest differs')
                op = pending['request']['opcode']
                if op == 65:
                    require(not output and not token, 'actual release returned bytes/token')
                    active_result = None
                elif op == 66:
                    active_result = None
                elif token:
                    if op == 64:
                        require(active_result is not None and (token, total, offset) ==
                                (active_result['token'], active_result['total'], active_result['cursor']),
                                'actual result chunk ownership differs')
                        capacity = struct.unpack_from('<I', pending['request_data'], 16)[0]
                    else:
                        require(op in (11, 16, 17, 18, 33, 34) and active_result is None and offset == 0 and
                                (token >= 1 << 63) == (op == 11),
                                'actual encoded/source lease overlaps/has invalid origin')
                        header = pending['raw_header']
                        active_result = dict(token=token, total=total, cursor=0, fnv=writeback.FNV_INIT,
                                             digest=hashlib.sha256(), chunks=0, first=pending['request']['sequence'],
                                             source_call=pending['source_call'], source_binding=
                                             header[8:12] + header[16:24] + header[52:56] + header[96:116] + header[120:128])
                        capacity = pending['capacity']
                    require(count == min(capacity, total - offset), 'short actual retained result chunk')
                    active_result['cursor'] += count
                    active_result['fnv'] = fnv_update(active_result['fnv'], output)
                    active_result['digest'].update(output)
                    active_result['chunks'] += 1
                pending['aggregate'] = None if active_result is None else {
                    'bytes': active_result['cursor'], 'sha256': active_result['digest'].hexdigest(),
                    'fnv1a64': active_result['fnv']}
            if kind == 'response':
                require(result_kind in pending and all(typed_equal(pending[result_kind].get(key), event.get(key)) for key in
                        ('actual_c_result', 'actual_source_result', 'source_provider_kind', 'source_snapshot',
                         'returned_bytes', 'returned_sha256', 'returned_fnv1a64', 'token', 'total', 'offset',
                         'request_payload', 'output_payload', 'result_transfer')) and
                        typed_equal(event.get('origin'), pending['origin']) and event.get('data_readback') is True and
                        event.get('raw_header_sha256') == pending['request']['raw_header_sha256'],
                        'actual C output/staged mailbox readback/origin differs')
                response = bytearray(pending['raw_header'])
                struct.pack_into('<I', response, 12, 2)
                struct.pack_into('<Ii', response, 44, count, 0)
                struct.pack_into('<4Q', response, 64, uint(event.get('returned_fnv1a64')), total, offset, token)
                require(sha(response) == event.get('response_header_sha256'), 'committed response header differs')
                pending = None
        elif kind == 'model_parameter_bank':
            require(pending is not None and pending['request']['opcode'] == 20 and 'core_result' in pending and
                    'parameter_bank' not in pending and event.get('opcode') == 20 and
                    event.get('sequence') == pending['request']['sequence'] and
                    type(event.get('actual_c_result')) is int and event['actual_c_result'] == 0 and
                    event.get('actual_core_sha256') == build['model_sha256'] and event.get('native_acceptance') is False and
                    typed_equal(event.get('origin'), pending['origin']) and
                    typed_equal(event.get('request_payload'), pending['request'].get('request_payload')) and
                    typed_equal(event.get('output_payload'), pending['core_result'].get('output_payload')),
                    'parameter bank query differs from the actual original C call')
            observed = event.get('observation')
            require(type(observed) is dict and set(observed) == {'actual_c_result', 'returned_hex', 'readback_verified',
                    'before_state_c_result', 'before_state_hex', 'result', 'query_c_result', 'bank_generation',
                    'snapshot_hex', 'after_state_c_result', 'after_state_hex'} and observed['readback_verified'] is True and
                    all(type(observed[k]) is int and observed[k] == 0 for k in
                        ('actual_c_result', 'query_c_result', 'before_state_c_result', 'after_state_c_result')) and
                    typed_equal(observed['result'], dict(token=0, total=0, offset=0, used=2756)),
                    'parameter bank independent actual C query/readback missing or failed')
            bank_output = payload_read(run, pending['core_result']['output_payload'])
            require(raw_hex(observed, 'returned_hex', 2756) == raw_hex(observed, 'snapshot_hex', 2756) == bank_output,
                    'parameter bank independently queried full2756 differs from actual C output')
            bank_value = cp_parameter_bank_result(bank_output, pending['request_data'], mailbox['nonce'],
                                                  raw_hex(observed, 'before_state_hex', 128))
            require(raw_hex(observed, 'after_state_hex', 128) == bank_output[64:192] and
                    type(observed['bank_generation']) is int and observed['bank_generation'] == bank_value['bank_generation'],
                    'parameter bank independent actual post-STATE differs')
            pending['parameter_bank'] = event
            current_bank = bank_value
        elif kind == 'model_crank_control':
            require(pending is not None and pending['request']['opcode'] == 21 and 'core_result' in pending and
                    'crank_control' not in pending and event.get('opcode') == 21 and
                    event.get('sequence') == pending['request']['sequence'] and
                    type(event.get('actual_c_result')) is int and event['actual_c_result'] == 0 and
                    event.get('actual_core_sha256') == build['model_sha256'] and event.get('native_acceptance') is False and
                    event.get('model_called') is True and event.get('model_committed') is True and
                    typed_equal(event.get('origin'), pending['origin']) and
                    typed_equal(event.get('request_payload'), pending['request'].get('request_payload')) and
                    typed_equal(event.get('output_payload'), pending['core_result'].get('output_payload')),
                    'crank control query differs from the actual original C call')
            origin = pending['origin']
            require(current_bank is not None and origin['source'] == 0x80020002 and
                    origin['destination'] == 0x90030001 and origin['command'] == 0x409d and
                    origin['bytes'] == 12 and origin['fnv1a64'] == fnv(pending['request_data']) and
                    struct.unpack_from('<I', pending['raw_header'], 52)[0] == 0,
                    'crank control current bank/original409d/source/destination/full12 origin differs')
            observed = event.get('observation')
            output = payload_read(run, pending['core_result']['output_payload'])
            value = cp_crank_control_observation(observed, output, pending['request_data'], mailbox['nonce'],
                raw_hex(observed, 'before_state_hex', 128) if type(observed) is dict else b'',
                current_bank['bank_generation'], pending['capacity'])
            require(value['fps'] == current_bank['fps'] and value['crank_generation'] == last_crank + 1 and
                    value['bank_generation'] != consumed_bank,
                    'crank control current bank/FPS/monotonic crank/once-only query differs')
            last_crank, consumed_bank = value['crank_generation'], value['bank_generation']
            pending['crank_control'] = event
            current_crank = value
        elif kind == 'model_movie_format':
            bounded_control_witness(event)
            require(pending is not None and pending['request']['opcode'] == 22 and 'core_result' in pending and
                    'movie_format' not in pending and type(event.get('opcode')) is int and event['opcode'] == 22 and
                    type(event.get('sequence')) is int and event['sequence'] == pending['request']['sequence'] and
                    type(event.get('actual_c_result')) is int and event['actual_c_result'] == 0 and
                    event.get('actual_core_sha256') == build['model_sha256'] and event.get('native_acceptance') is False and
                    event.get('model_called') is True and event.get('model_committed') is True and
                    typed_equal(event.get('origin'), pending['origin']) and
                    typed_equal(event.get('request_payload'), pending['request'].get('request_payload')) and
                    typed_equal(event.get('output_payload'), pending['core_result'].get('output_payload')),
                    'movie format query differs from the actual original C call')
            origin = pending['origin']
            require(current_bank is not None and current_crank is not None and
                    current_crank['bank_generation'] == current_bank['bank_generation'] and
                    origin['source'] == 0x80020002 and origin['destination'] == 0x90030001 and
                    origin['command'] == 0x4000 and origin['bytes'] == 20 and origin['fnv1a64'] == fnv(pending['request_data']) and
                    struct.unpack_from('<I', pending['raw_header'], 52)[0] == 0,
                    'movie format current bank/crank/original4000/source/destination/full20 origin differs')
            observed = event.get('observation')
            output = payload_read(run, pending['core_result']['output_payload'])
            value = cp_movie_format_observation(observed, output, pending['request_data'], mailbox['nonce'],
                raw_hex(observed, 'before_state_hex', 128) if type(observed) is dict else b'',
                current_bank['bank_generation'], current_crank['crank_generation'], pending['capacity'])
            pair = (value['bank_generation'], value['crank_generation'])
            require(value['fps'] == current_bank['fps'] and value['movie_generation'] == last_movie + 1 and
                    pair not in movie_pairs, 'movie format current bank/crank/FPS/monotonic/once-only query differs')
            last_movie = value['movie_generation']
            movie_pairs.add(pair)
            pending['movie_format'] = event
            current_movie = value
        elif kind == 'model_ou_crank_control':
            bounded_control_witness(event)
            require(pending is not None and pending['request']['opcode'] == 23 and 'core_result' in pending and
                    'ou_crank_control' not in pending and event['sequence'] == pending['request']['sequence'] and
                    event['actual_core_sha256'] == build['model_sha256'] and
                    typed_equal(event['origin'], pending['origin']) and
                    typed_equal(event['request_payload'], pending['request'].get('request_payload')) and
                    typed_equal(event['output_payload'], pending['core_result'].get('output_payload')),
                    'OU crank query differs from the actual original C call')
            origin = pending['origin']
            require(current_bank is not None and current_crank is not None and current_movie is not None and
                    current_crank['bank_generation'] == current_movie['bank_generation'] == current_bank['bank_generation'] and
                    current_movie['crank_generation'] == current_crank['crank_generation'] and
                    struct.unpack_from('<I', pending['raw_header'], 52)[0] == 0,
                    'OU crank original source/current tuple/flags differ')
            observed = event['observation']
            output = payload_read(run, pending['core_result']['output_payload'])
            value = cp_ou_crank_control_observation(observed, output, pending['request_data'], mailbox['nonce'],
                raw_hex(observed, 'before_state_hex', 128), current_bank['bank_generation'],
                current_crank['crank_generation'], current_movie['movie_generation'], pending['capacity'])
            identity = (value['bank_generation'], value['crank_generation'], value['movie_generation'])
            require(value['fps'] == current_bank['fps'] and value['ou_generation'] == last_ou + 1 and
                    identity not in ou_tuples, 'OU crank current tuple/FPS/monotonic/once-only query differs')
            last_ou = value['ou_generation']
            ou_tuples.add(identity)
            pending['ou_crank_control'] = event
        elif kind == 'ou_crank_control_rejected':
            require(pending is not None and type(event.get('opcode')) is int and
                    pending['request']['opcode'] == event['opcode'] == 23 and
                    type(event.get('sequence')) is int and event['sequence'] == pending['request']['sequence'] and
                    event.get('actual_core_sha256') == build['model_sha256'] and
                    typed_equal(event.get('origin'), pending['origin']) and
                    typed_equal(event.get('request_payload'), pending['request'].get('request_payload')) and
                    event.get('native_acceptance') is False and
                    (event.get('actual_c_result') is None and event.get('admission_error') == -errno.EBUSY or
                     type(event.get('actual_c_result')) is int and -4095 <= event['actual_c_result'] <= 0),
                    'OU crank rejection lacks its actual original C request/library')
            rejected = payload_read(run, event.get('output_payload'))
            if 'core_result' in pending:
                core = pending['core_result']
                require(typed_equal(event.get('actual_c_result'), core.get('actual_c_result')) and
                        typed_equal(event.get('output_payload'), core.get('output_payload')) and
                        len(rejected) == core.get('returned_bytes') and sha(rejected) == core.get('returned_sha256') and
                        fnv(rejected) == core.get('returned_fnv1a64'),
                        'OU crank rejection differs from original actual C rc/output')
            observed = event.get('observation')
            require(type(observed) is dict and raw_hex(event, 'input_hex', 12) == pending['request_data'] and
                    type(event.get('request_fnv1a64')) is int and event['request_fnv1a64'] == fnv(pending['request_data']) and
                    ('returned_hex' not in observed or raw_hex(observed, 'returned_hex', len(rejected)) == rejected) and
                    ('actual_c_result' not in observed or typed_equal(observed['actual_c_result'], event['actual_c_result'])),
                    'OU crank rejection actual C0/negative result or output differs')
            raise OuCrankControlRejected(event)
        elif kind == 'movie_format_rejected':
            require(pending is not None and pending['request']['opcode'] == event.get('opcode') == 22 and
                    type(event.get('opcode')) is int and event.get('sequence') == pending['request']['sequence'] and
                    event.get('actual_core_sha256') == build['model_sha256'] and
                    typed_equal(event.get('origin'), pending['origin']) and
                    typed_equal(event.get('request_payload'), pending['request'].get('request_payload')) and
                    event.get('native_acceptance') is False and type(event.get('actual_c_result')) is int and
                    -4095 <= event['actual_c_result'] <= 0, 'movie format rejection lacks its actual original C request/library')
            rejected = payload_read(run, event.get('output_payload'))
            if 'core_result' in pending:
                core = pending['core_result']
                require(typed_equal(event.get('actual_c_result'), core.get('actual_c_result')) and
                        typed_equal(event.get('output_payload'), core.get('output_payload')) and
                        len(rejected) == core.get('returned_bytes') and sha(rejected) == core.get('returned_sha256') and
                        fnv(rejected) == core.get('returned_fnv1a64'),
                        'movie format rejection differs from the original actual C rc/output')
            observed = event.get('observation')
            require(type(observed) is dict and
                    ('returned_hex' not in observed or raw_hex(observed, 'returned_hex', len(rejected)) == rejected) and
                    ('actual_c_result' not in observed or typed_equal(observed['actual_c_result'], event['actual_c_result'])),
                    'movie format rejection actual C0/negative result or output differs')
            raise MovieFormatRejected(event)
        elif kind == 'crank_control_rejected':
            require(pending is not None and pending['request']['opcode'] == event.get('opcode') == 21 and
                    event.get('sequence') == pending['request']['sequence'] and
                    event.get('actual_core_sha256') == build['model_sha256'] and
                    typed_equal(event.get('origin'), pending['origin']) and
                    typed_equal(event.get('request_payload'), pending['request'].get('request_payload')) and
                    event.get('native_acceptance') is False,
                    'crank control rejection lacks its actual original request/library')
            rejected = payload_read(run, event.get('output_payload'))
            if 'core_result' in pending:
                core = pending['core_result']
                require(typed_equal(event.get('actual_c_result'), core.get('actual_c_result')) and
                        typed_equal(event.get('output_payload'), core.get('output_payload')) and
                        len(rejected) == core.get('returned_bytes') and sha(rejected) == core.get('returned_sha256') and
                        fnv(rejected) == core.get('returned_fnv1a64'),
                        'crank control rejection differs from the original actual C rc/output')
            observed = event.get('observation')
            require(type(observed) is dict and
                    ('returned_hex' not in observed or raw_hex(observed, 'returned_hex', len(rejected)) == rejected),
                    'crank control rejection actual output differs')
            raise CrankControlRejected(event)
        elif kind == 'model_frame':
            require(pending is not None and pending['request']['opcode'] not in (21, 22, 23) and
                    'core_result' in pending and 'frame' not in pending and
                    event.get('sequence') == pending['request']['sequence'] and
                    event.get('opcode') == pending['request']['opcode'] and
                    event.get('actual_c_result') == 0 and event.get('actual_core_sha256') == build['model_sha256'] and
                    typed_equal(event.get('origin'), pending['origin']) and
                    typed_equal(event.get('request_payload'), pending['request'].get('request_payload')) and
                    typed_equal(event.get('output_payload'), pending['core_result'].get('output_payload')),
                    'frame proof differs from actual original C call')
            pending['frame'] = event
        elif kind == 'source_cancel':
            require(active_result is None and event.get('host_snapshot_cleared') is True and
                    uint(event.get('token')) == 0 and uint(event.get('discarded_bytes')) == 0 and
                    event.get('source_model') == 'paused-source-snapshot-v1' and all(event.get(k) is False for k in
                        ('capture', 'capture_verified', 'native_global_writer_exclusion_verified', 'physical_ASIC',
                         'physicalBackingObjectVerified', 'source_writer_completion_verified',
                         'native_source_atomicity_verified', 'physical_asic_compatibility_verified')),
                    'source cleanup retains source storage or promotes scope')
            if event.get('reason') == 'broker_cleanup':
                # Host Snapshot.cancel precedes the separate actual C cleanup CANCEL.
                require(source_cleanup is None and pending is None and 'actual_c_result' not in event,
                        'source finalizer duplicate/in-flight or disguised as C CANCEL')
                source_cleanup = event
            else:
                require(event.get('reason') == 'actual_c_cancel' and pending is not None and
                        pending['request']['opcode'] == 66 and not pending['source_call'] and
                        'core_result' not in pending and type(event.get('actual_c_result')) is int and
                        event['actual_c_result'] == 0, 'source cleanup lacks its actual in-band C CANCEL')
    require(active_result is None, 'actual retained output not released before final cleanup')
    require(pending is None and transactions and transactions[1]['request']['opcode'] == 1 and
            events[-1].get('kind') == 'cleanup' and
            all(events[-1].get(key) is True for key in close) and events[-1].get('errors') == [],
            'partial model work or unsafe final broker cleanup')
    require(typed_equal(counts, runner.get('broker_event_counts')), 'runner broker event census differs')
    op_counts = {str(op): sum(tx['request']['opcode'] == op for tx in transactions.values())
                 for op in sorted({tx['request']['opcode'] for tx in transactions.values()})}
    require(typed_equal(op_counts, runner.get('model_response_counts_by_opcode')), 'runner actual opcode census differs')
    transfers = [row for row in rows if row['tag'] == 'FUNCTIONAL_CAMERA_TRANSFER']
    covered, checked, used_tokens = set(), [], set()
    for row in transfers:
        f = row['fields']
        require(f.get('error') == '0' and f.get('readback_closed') == '1', 'failed actual bridge transfer')
        interval = re.fullmatch(r'([1-9][0-9]*)\.\.([1-9][0-9]*)', f.get('seq', ''))
        require(interval is not None, 'invalid bridge transaction interval')
        first, last = map(int, interval.groups())
        require(0 < first <= last <= len(transactions), 'bridge interval outside actual request sequence')
        ids = set(range(first, last + 1))
        require(not covered & ids, 'duplicate/overlapping bridge transfer')
        covered |= ids
        tx = transactions[first]
        require('origin_kind' not in f or f['origin_kind'] == (
                    'api40-source-snapshot' if tx['source_call'] else 'native-osal'),
                'bridge origin_kind differs from actual broker provider')
        require(number(f['model_instance']) == mailbox['nonce'] and number(f['op']) == tx['request']['opcode'] and
                number(f['request_bytes']) == tx['request']['request_bytes'] and
                number(f['request_fnv']) == tx['request']['request_fnv1a64'], 'bridge initial request differs from broker')
        for seq in ids:
            origin = transactions[seq]['origin']
            require(origin['producer_tid'] == tx['origin']['producer_tid'] and
                    all(number(f[guest]) == origin[host] for guest, host in
                        (('source', 'source'), ('destination', 'destination'), ('command', 'command'),
                         ('bytes', 'bytes'), ('native_fnv', 'fnv1a64'))), 'bridge original native origin differs')
        produced = tx['response']
        token, total, cursor = produced['token'], produced['total'] or produced['returned_bytes'], 0
        chunks = list(range(first, last)) if token else [first]
        require(not token or token not in used_tokens, 'retained result token reused')
        if token:
            used_tokens.add(token)
            require(transactions[last]['request']['opcode'] == 65 and last > first and
                    transactions[last]['response']['returned_bytes'] == 0, 'missing actual retained-result release')
        else:
            require(first == last, 'tokenless transfer contains extra operations')
        for seq in chunks:
            part = transactions[seq]
            require(part['request']['opcode'] == (tx['request']['opcode'] if seq == first else 64) and
                    part['response']['token'] == token and part['response']['offset'] == cursor and
                    (not token or part['response']['total'] == total), 'retained result chunk/cursor differs')
            cursor += part['response']['returned_bytes']
        require(cursor == total == number(f['returned_bytes']) == number(f['required']) == number(f['destination_written_bytes']) and
                number(f['returned_fnv']) == number(f['destination_fnv']) and number(f['token']) == token,
                'bridge actual destination readback length/hash differs')
        if len(chunks) == 1:
            require(number(f['returned_fnv']) == produced['returned_fnv1a64'], 'single chunk broker/destination bytes differ')
        digest, value, size = hashlib.sha256(), writeback.FNV_INIT, 0
        output_payloads = []
        for seq in chunks:
            reference = transactions[seq]['response']['output_payload']
            data = payload_read(run, reference, payload_budget)
            digest.update(data)
            value = fnv_update(value, data)
            size += len(data)
            output_payloads.append(reference)
            aggregate = transactions[seq].get('aggregate')
            if token:
                require(aggregate == {'bytes': size, 'sha256': digest.hexdigest(), 'fnv1a64': value},
                        'actual retained prefix aggregate differs')
        require(size == total and value == number(f['returned_fnv']), 'aggregate actual output/guest destination differs')
        if token:
            require(struct.unpack('<2Q', transactions[last]['request_data']) == (token, value),
                    'actual release is not for complete guest-consumed output')
        checked.append({'line': row['line'], 'first': first, 'last': last, 'opcode': tx['request']['opcode'],
                        'origin': tx['origin'], 'bytes': total, 'sha256': digest.hexdigest(),
                        'fnv1a64': f'{value:016x}', 'request_payload': tx['request']['request_payload'],
                        'output_payloads': output_payloads, 'frame': tx.get('frame'),
                        'token': token, 'model_instance': mailbox['nonce'],
                        'provider_kind': 'source' if tx['source_call'] else 'core',
                        **({'parameter_bank': tx['parameter_bank']} if 'parameter_bank' in tx else {}),
                        **({'crank_control': tx['crank_control'], 'capacity': tx['capacity']}
                           if 'crank_control' in tx else {}),
                        **({'movie_format': tx['movie_format'], 'capacity': tx['capacity']}
                           if 'movie_format' in tx else {}),
                        **({'ou_crank_control': tx['ou_crank_control'], 'capacity': tx['capacity']}
                           if 'ou_crank_control' in tx else {})})
    require(covered == set(transactions), 'broker responses not fully consumed by actual guest bridge')
    needed(all(counts.get(key) == 1 for key in ('binding', 'attached', 'cancel_cleanup', 'cleanup',
                                              'detach_commit', 'mailbox_detached', 'debugger_disconnected')),
           'broker: one binding/attach/actual cancel/detach/disconnect/cleanup lifecycle')
    lifecycle = {event['kind']: event for event in events if event['kind'] in
                 ('detach_commit', 'mailbox_detached', 'debugger_disconnected', 'cleanup')}
    require(type(lifecycle['detach_commit'].get('sequence')) is int and
            lifecycle['detach_commit']['sequence'] == len(transactions) and
            lifecycle['detach_commit'].get('model_work_stopped') is True and
            lifecycle['detach_commit'].get('no_further_ram_after_ack') is True and
            lifecycle['mailbox_detached'].get('cleanup_detach') is True and
            lifecycle['debugger_disconnected'].get('detached') is True and
            [lifecycle[k]['event'] for k in ('detach_commit', 'mailbox_detached', 'debugger_disconnected', 'cleanup')] ==
            sorted(lifecycle[k]['event'] for k in ('detach_commit', 'mailbox_detached', 'debugger_disconnected', 'cleanup')) and
            max(tx['response']['event'] for tx in transactions.values()) < lifecycle['detach_commit']['event'],
            'detach precedes committed work or cleanup lifecycle is unsafe')
    needed(not any(tx['source_call'] for tx in transactions.values()) or source_cleanup is not None,
           'broker: source finalizer after actual source RELEASE required')
    for event in events:
        if event['kind'] == 'cancel_cleanup':
            require(type(event.get('actual_c_result')) is int and event['actual_c_result'] == 0 and
                    type(event.get('returned_bytes')) is int and event['returned_bytes'] == 128 and
                    max(tx['response']['event'] for tx in transactions.values()) < event['event'] <
                    lifecycle['detach_commit']['event'], 'actual model cleanup cancel failed/late')
            if source_cleanup is not None:
                require(max(tx['response']['event'] for tx in transactions.values()) < source_cleanup['event'] <
                        event['event'], 'source finalizer not before actual C cleanup CANCEL/after completed work')
    result = {'verified': True, 'pid': mailbox['pid'], 'model_instance': mailbox['nonce'],
              'requests': len(transactions), 'opcodes': op_counts, 'transfers': checked,
              'safe_cleanup': True, 'raw_payload_bytes_verified': True, 'owner_pid': config['owner']['pid'],
              'payload_files': len(paths), 'payload_read_budget_remaining': payload_budget[0]}
    result['VDF_path'] = check_vdf_path(run, rows, result)
    result['startup_layout_stage'] = check_layout_stage(run, manifest, rows, result)
    if result['VDF_path']['required']:
        backup = manifest.get('backup_transport')
        require(type(backup) is dict and all(
            typed_equal(manifest.get('functional_camera_' + key), value) and
            typed_equal(backup.get('functional_camera_' + key), value) for key, value in VDF_POLICY.items()),
            'VDF operation lacks the explicit software endpoint/mask policy')
    if any(tx['opcode'] == 6 for tx in checked):
        backup = manifest.get('backup_transport')
        require(type(backup) is dict and all(
            typed_equal(manifest.get('functional_camera_' + key), value) and
            typed_equal(backup.get('functional_camera_' + key), value) for key, value in ZEBRA_POLICY.items()),
            'Zebra operation lacks the explicit disabled/pass-through software policy')
    if any(tx['opcode'] == 7 for tx in checked):
        backup = manifest.get('backup_transport')
        require(type(backup) is dict and all(
            typed_equal(manifest.get('functional_camera_' + key), value) and
            typed_equal(backup.get('functional_camera_' + key), value) for key, value in LAYOUT_POLICY.items()),
            'Layout operation lacks the explicit initial-case0 software policy')
    if any(tx['opcode'] == 8 for tx in checked):
        backup = manifest.get('backup_transport')
        display_policies = (DISPLAY_POLICY,)
        if all(tx['origin']['command'] in (0x141, 0x152, 0x162, 0x163) for tx in checked if tx['opcode'] == 8):
            display_policies += (ZERO6_DISPLAY_POLICY,)
        if all(tx['origin']['command'] in (0x141, 0x152, 0x162) for tx in checked if tx['opcode'] == 8):
            display_policies += (LEGACY_DISPLAY_POLICY,)
        require(type(backup) is dict and any(all(
            typed_equal(manifest.get('functional_camera_' + key), value) and
            typed_equal(backup.get('functional_camera_' + key), value) for key, value in policy.items())
            for policy in display_policies),
            'Display operation lacks the explicit disabled/off software policy')
    for opcode, policy in ((9, BB_POLICY), (10, HIST_POLICY), (12, BIT_WIDTH_POLICY),
                           (13, STILL_FORMAT_POLICY), (14, STARTUP_CONTROL_POLICY)):
        if any(tx['opcode'] == opcode for tx in checked):
            backup = manifest.get('backup_transport')
            require(type(backup) is dict and all(
                typed_equal(manifest.get('functional_camera_' + key), value) and
                typed_equal(backup.get('functional_camera_' + key), value) for key, value in policy.items()),
                'BB/histogram/bit width operation lacks its exact typed software policy')
    result['still_format'] = check_still_format(run, manifest, rows, result)
    if result['still_format']['required'] and not result['still_format']['verified']:
        result['verified'] = False
    result['startup_control'] = check_startup_control(run, manifest, rows, result)
    if result['startup_control']['required'] and not result['startup_control']['verified']:
        result['verified'] = False
    result['focus_reset'] = check_focus_reset(run, manifest, rows, result)
    if result['focus_reset']['required'] and not result['focus_reset']['verified']:
        result['verified'] = False
    result['histogram'] = check_histogram(run, rows, result)
    result['control'] = check_control(run, rows, result)
    if result['control']['required']:
        backup = manifest.get('backup_transport')
        require(type(backup) is dict and all(typed_equal(manifest.get('functional_camera_' + key), value) and
                typed_equal(backup.get('functional_camera_' + key), value) for key, value in XSYNC_POLICY.items()),
                'control timing lacks the exact typed software clock policy')
    result['parameter_bank'] = check_cp_parameter_bank(run, manifest, rows, result)
    result['crank_control_content'] = check_cp_crank_control_content(run, manifest, rows, result)
    if result['crank_control_content']['required'] and not result['crank_control_content']['verified']:
        result['verified'] = False
    result['movie_format_content'] = check_cp_movie_format_content(run, manifest, rows, result)
    if result['movie_format_content']['required'] and not result['movie_format_content']['verified']:
        result['verified'] = False
    result['ou_crank_control_content'] = check_cp_ou_crank_control_content(run, manifest, rows, result)
    if result['ou_crank_control_content']['required'] and not result['ou_crank_control_content']['verified']:
        result['verified'] = False
    result['background_start'] = check_background_start(run, manifest, rows, result)
    if result['background_start']['required'] and not result['background_start']['verified']:
        result['verified'] = False
    timecode_rows = [row for row in rows if not row['tag'].startswith(
        ('FUNCTIONAL_BB_TIMECODE_PRESET_', 'NATIVE_BB_TIMECODE_PRESET_'))]
    result['bb_timecode_control'] = check_bb_timecode_control(run, manifest, timecode_rows, result)
    if result['bb_timecode_control']['required'] and not result['bb_timecode_control']['verified']:
        result['verified'] = False
    result['bb_timecode_presets'] = check_bb_timecode_presets(run, manifest, rows, result)
    if result['bb_timecode_presets']['required'] and not result['bb_timecode_presets']['verified']:
        result['verified'] = False
    return result


def check_bb_timecode_policy(manifest, observed=False):
    """Return whether exact typed TC policy is selected; OFF/strict None stays absent."""
    if not observed and not any(value is not None for target in (manifest, manifest.get('backup_transport', {}))
            if type(target) is dict for key, value in target.items()
            if key.startswith('functional_camera_bb_timecode_control_')):
        return False
    return bb_timecode_module().policy(manifest, types.SimpleNamespace(**globals()), observed)


def check_bb_timecode_control(run, manifest, rows, transport):
    """Keep old runs absent; require source and content closure for observed TC."""
    seen = any(row['tag'].startswith(('FUNCTIONAL_BB_TIMECODE_', 'NATIVE_BB_TIMECODE_')) for row in rows)
    if not seen and not any(value is not None for target in (manifest, manifest.get('backup_transport', {}))
            if type(target) is dict for key, value in target.items()
            if key.startswith('functional_camera_bb_timecode_control_')):
        return dict(status='not_observed', required=False, verified=False, transactions=[],
                    content_join_verified=False, native_completion_verified=False,
                    native_virtual_controls_verified=False, commands_observed=[], all_three_complete=False,
                    frame_consumed=False, capture_verified=False, physical_asic_compatibility_verified=False,
                    original_CP_executed=False, original_CP_RAM_verified=False, original_RTOS_verified=False,
                    original_fifo_identity_verified=False, minimal_business_patch=None)
    return bb_timecode_module().check(run, manifest, rows, transport, types.SimpleNamespace(**globals()))


def check_bb_timecode_presets_policy(manifest, observed=False):
    """Absent/strict None stays absent; selected preset policy is exact and typed."""
    if not observed and not any(value is not None for target in (manifest, manifest.get('backup_transport', {}))
            if type(target) is dict for key, value in target.items()
            if key.startswith('functional_camera_bb_timecode_preset_')):
        return False
    return bb_timecode_presets_module().policy(manifest, types.SimpleNamespace(**globals()), observed)


def check_bb_timecode_presets(run, manifest, rows, transport):
    """Require actual old TC content closure; preset names never enter the old reader."""
    seen = any(row['tag'].startswith(('FUNCTIONAL_BB_TIMECODE_PRESET_', 'NATIVE_BB_TIMECODE_PRESET_')) for row in rows)
    if not seen and not any(value is not None for target in (manifest, manifest.get('backup_transport', {}))
            if type(target) is dict for key, value in target.items()
            if key.startswith('functional_camera_bb_timecode_preset_')):
        return dict(status='not_observed', required=False, verified=False, transactions=[],
                    content_join_verified=False, native_completion_verified=False,
                    native_virtual_controls_verified=False, commands_observed=[], all_two_complete=False,
                    frame_consumed=False, capture_verified=False, physical_asic_compatibility_verified=False,
                    original_CP_executed=False, original_CP_RAM_verified=False, original_RTOS_verified=False,
                    original_fifo_identity_verified=False, minimal_business_patch=None)
    return bb_timecode_presets_module().check(run, manifest, rows, transport, types.SimpleNamespace(**globals()))


def cp_crank_original_audit(rows, packet, pid, sender, lower, upper, pointer=None):
    """An API-entry audit is a byte/source witness, never an IPC completion."""
    found = []
    for row in rows:
        f = row['fields']
        if (row['tag'] == 'NATIVE_CP_BACKGROUND_INPUT_AUDIT' and lower < row['line'] < upper and
                f.get('bytes') == str(len(packet)) and f.get('pid') == str(pid) and f.get('tid') == str(sender) and
                (pointer is None or f.get('pointer') == pointer)):
            selected = [r for r in rows if r['tag'] == 'NATIVE_CP_BACKGROUND_INPUT_AUDIT_BYTES' and
                row['line'] < r['line'] < upper and all(r['fields'].get(k) == f.get(k) for k in ('pid', 'tid', 'sequence'))]
            data = bytearray()
            for chunk in selected:
                c = chunk['fields']
                require('diagnostic' not in chunk and set(c) == set('pid tid sequence offset bytes raw'.split()),
                        'crank original audit chunk formatter incomplete')
                require(number(c['offset']) == len(data) and number(c['bytes']) == min(128, len(packet) - len(data)),
                        'crank original audit chunk gap/overlap/size differs')
                data.extend(raw_hex(c, 'raw', number(c['bytes'])))
            if bytes(data) == packet:
                found.append(row)
    require(len(found) == 1, 'crank original complete audit missing/ambiguous')
    row = found[0]; f = row['fields']
    require('diagnostic' not in row and set(f) == set(('pid tid sequence entry pointer destination bytes source '
            'size_known source_known bytes_complete complete producer_return consumed state_verified capture_verified').split()) and
            f['entry'] == 'async' and f['pointer'] != '(nil)' and number(f['sequence']) > 0 and
            number(f['destination']) == 0x90030001 and number(f['source']) == 0x80020002 and
            all(f[k] == '1' for k in ('size_known', 'source_known', 'bytes_complete', 'complete')) and
            all(f[k] == '0' for k in ('consumed', 'state_verified', 'capture_verified')),
            'crank original audit source/metadata/scope differs')
    return row


def cp_crank_predecessors(run, rows, transport, begin, reservation, bank, bank_tx, prior):
    """Resource34 accepted=1 cannot replace the original predecessor contents."""
    pid, sender = transport['pid'], number(begin['fields']['sender_tid'])
    held = [r for r in rows if r['tag'].startswith('FUNCTIONAL_CP_CRANK_CONTROL_RESOURCE') and
            begin['line'] < r['line'] <= reservation['line']]
    table, reserved = held[1]['fields'], held[2]['fields']
    require(number(held[0]['fields']['pid']) == number(table['pid']) == pid and
            all(number(r['fields']['tid']) == sender for r in held), 'crank resource34 original PID/TID differs')
    fixed = dict(dmm_enabled='1', dmm_bound='1', dmm_slots='1/1', dmm_opens='1/1',
        dmm_handles='0x8400/0x8401', dmm_generations='1/1', dmm_epochs='1/2', dmm_creators='1/1',
        dmm_allocation_count='2', dmm_lifecycle_changed='0', dmm_domain='2', foreign_speech_kept='1',
        control_bound='1', connection_started='1', connections='1', format_consumed='1', buffer_released='1',
        connection_reply_frees='1', vef_init='1', vef_owner='0x905a0048', pinmem_init='1', pinmem_owner='0x90590818')
    require(all(reserved[k] == value for k, value in fixed.items()) and
            number(reserved['allocations']) == number(reserved['releases']) > 0 and
            number(reserved['vef_objects']) > 0 and number(reserved['pinmem_objects']) > 0,
            'crank resource34 TTS/DMM/registry domain differs')
    speech = raw_hex(table, 'raw_before', 144)
    require(raw_hex(table, 'raw_after', 144) == speech, 'crank resource34 TTS full readback changed')
    for slot in range(2):
        offset = slot * 0x48
        require(struct.unpack_from('<I', speech, offset)[0] == 0x1a + slot and
                struct.unpack_from('<2I', speech, offset + 0x18) == (0x8400 | slot, 0x80000) and
                struct.unpack_from('<Q', speech, offset + 0x20)[0] == 0x1e000000 + slot * 0x80000,
                'crank resource34 full TTS does not bind both DMM slots')
    bank_end = [r for r in rows if r['tag'] == 'FUNCTIONAL_CP_PARAMETER_BANK_EVENT' and
                r['fields'].get('transaction') == str(bank['transaction']) and r['fields'].get('event') == 'COMMIT']
    require(len(bank_end) == 1 and bank['original_free_line'] < bank_end[0]['line'] < begin['line'] and
            all(bank_end[0]['fields'][k] == '0' for k in ('guard', 'faults', 'error', 'free_rc', 'releasing')) and
            all(bank_end[0]['fields'][k] == '1' for k in ('verified', 'owned', 'model_committed', 'request_freed')) and
            bank_end[0]['fields']['retained'] == '(nil)', 'crank current bank lacks actual clean request free')
    bank_owned = [r for r in rows if r['tag'] == 'FUNCTIONAL_CP_PARAMETER_BANK_EVENT' and
                  r['fields'].get('transaction') == str(bank['transaction']) and r['fields'].get('event') == 'OWNED_FREE']
    require(len(bank_owned) == 1 and bank_owned[0]['line'] == bank['original_free_line'] and
            bank_owned[0]['fields'].get('request_freed') == '1' and bank_owned[0]['fields'].get('free_rc') == '0' and
            bank_owned[0]['fields'].get('retained') == '(nil)' and bank_owned[0]['fields'].get('faults') == '0',
            'crank current bank actual OWNED_FREE receipt missing/differs')
    require(transfer_output(run, bank_tx)[64:192] == prior,
            'crank live before STATE is not the complete current bank after STATE')
    frees = []
    for tag in BACKGROUND_FREE_TAGS:
        found = [r for r in rows if r['tag'] == tag and r['line'] < held[0]['line']]
        require(len(found) == 1, 'crank all13 original free missing/ambiguous: ' + tag)
        row = found[0]; f = row['fields']
        require('diagnostic' not in row and f.get('pid') == str(pid) and f.get('bytes') == '56' and
                all(f.get(k) == '0' for k in ('rc', 'faults', 'capture_verified')) and f.get('ap_consumed') == '1' and
                0 < number(f['tid']) < 2**31 and number(f['destination']) == number(f['expected']) and
                number(f['destination']) >> 28 == 8 and number(f['destination']) & 0x0fffffff and
                f.get('reply', f.get('pointer', '(nil)')) != '(nil)' and
                ('sender' not in f or f['sender'] == f['tid'] and f.get('waiter') == '1') and
                ('command' not in f or number(f['command']) == 0x8001) and
                all(f[k] == '0' for k in ('frames_verified', 'pcm_verified') if k in f),
                'crank all13 original free content differs')
        free_keys = set('pid tid destination expected bytes rc faults ap_consumed capture_verified'.split())
        free_keys.add('reply' if tag.endswith('_NATIVE_REPLY_FREE') else 'pointer')
        if tag.endswith('_NATIVE_REPLY_FREE') or tag in ('FULL_VEF_PINMEM_CONTROL_CONNECT_REPLY_FREE',
                                                       'FULL_ADF_HDMI_AUDIO_CONNECT_REPLY_FREE'):
            free_keys.update(('sender', 'waiter'))
        if tag.endswith('_NATIVE_REPLY_FREE'):
            free_keys.add('command')
        else:
            if tag != 'FULL_ADF_HDMI_AUDIO_CONNECT_REPLY_FREE':
                free_keys.add('frames_verified')
            if tag == 'FULL_IMAGING_ADF_CONNECT_REPLY_FREE':
                free_keys.add('pcm_verified')
        if tag == 'FULL_PINMEM_HDMI_VIDEO_CONNECT_NATIVE_REPLY_FREE':
            free_keys.add('producer_tid')
        require(set(f) == free_keys and re.fullmatch(r'0x[1-9a-f][0-9a-f]{0,15}', f.get('reply', f.get('pointer', ''))),
                'crank all13 original free typed fields/pointer differ')
        frees.append(row['line'])
    all13 = [r for r in rows if r['tag'] in ('NATIVE_CP302C_DIAGNOSTIC_ALL13_READBACK',
            'NATIVE_CP302C_NOCONVERT_ALL13_READBACK') and max(frees) < r['line'] < held[0]['line'] and
            r['fields'].get('pid') == str(pid) and r['fields'].get('tid') == str(sender)]
    require(all13 and all('diagnostic' not in r and all(r['fields'].get(k) == '1' for k in
            ('accepted', 'video_AP_consumed', 'OSD_AP_consumed', 'audio_AP_consumed')) and
            r['fields'].get('OSD_live') == '16' and r['fields'].get('OSD_owners_each') ==
            r['fields'].get('OSD_opens_each') == '2' and r['fields'].get('global_DMM_idle_claimed') ==
            r['fields'].get('capture_verified') == '0' for r in all13), 'crank all13 current retirement readback differs')
    mode_rows = [r for r in rows if r['tag'] in ('FUNCTIONAL_CAMERA_CONTROL_COMMIT', 'FUNCTIONAL_CAMERA_CONTROL_SENT',
                'FUNCTIONAL_CAMERA_CONTROL_AP_FREE', 'FUNCTIONAL_CAMERA_CONTROL_OWNED_FREE') and r['line'] < begin['line']]
    needed(mode_rows, 'crank current mode retirement')
    latest = mode_rows[-1]['fields']; cycle = latest.get('cycle_id')
    require(all(latest.get(k) == '1' for k in ('start_complete', 'mode1_complete', 'mode_complete', 'notification_AP_consumed')) and
            all(latest.get(k) == '0' for k in ('faults', 'busy', 'guard')) and
            number(latest['model_instance']) == transport['model_instance'], 'crank current mode retirement differs')
    leases = {}
    for row in mode_rows:
        f = row['fields']
        if f.get('index') in ('0', '1') or f.get('cycle_id') == cycle:
            leases[number(f['index'])] = f
    require(set(leases) == set(range(5)), 'crank current mode lacks all five retired leases')
    for index, f in leases.items():
        require(f.get('pid') == str(pid) and number(f['model_instance']) == transport['model_instance'] and
                f.get('retained') == '(nil)' and f.get('freed') == '1' and
                all(f.get(k) == '0' for k in ('faults', 'releasing', 'send_inflight', 'free_rc', 'send_rc', 'allocate_rc')) and
                (index not in (1, 3, 4) or f.get('consumed') == '1') and
                0 < number(f['free_tid']) < 2**31 and number(f['free_tid']) == number(f['receiver_tid'] if index == 4 else f['sender_tid']),
                'crank mode lease is live/faulted/unconsumed or freed by a foreign thread')
    strict = [r for r in rows if r['tag'].startswith('NATIVE_CP_EE_DIAGNOSTIC_') and
              r['fields'].get('opcode') == '0x409d' and r['line'] < begin['line']]
    require(len(strict) == 3 and {r['tag'] for r in strict} == {'NATIVE_CP_EE_DIAGNOSTIC_' + name for name in
            ('REQUEST_FREE', 'REPLY_FREE', 'COMPLETE')}, 'crank strict initial409d independent history missing/replayed')
    initial_fields = set(('pid opcode sender_tid waiter_tid attempts requests busy guard faults source request_destination '
        'destination bytes request cookie wire_fnv1a32 source_byte1_known reply freed_reply reply_free_destination '
        'reply_free_source reply_free_bytes allocate_rc send_rc request_free_rc reply_free_rc queued request_freed '
        'reply_freed clean_completion ap_consumed oneway oneway_consumed virtual_field_mask virtual_fields_readback '
        'virtual_fields_consumed virtual_fields virtual_readback retained_request live_reply retained_cleanup '
        'diagnostic_only virtual_padding business_applied source_dependencies_closed configured published generation '
        'native_cp EE frame capture').split())
    require(all('diagnostic' not in r and set(r['fields']) == initial_fields for r in strict),
            'crank strict initial409d complete formatter missing/extended')
    strict_at = {r['tag']: r['line'] for r in strict}
    require(strict_at['NATIVE_CP_EE_DIAGNOSTIC_REQUEST_FREE'] < strict_at['NATIVE_CP_EE_DIAGNOSTIC_COMPLETE'],
            'crank strict initial409d completed before actual original request free')
    initial = strict[-1]['fields']; wire = raw_hex(initial, 'request', 12)
    ack = b'\x01\0\x9d\x40' + wire[4:8] + struct.pack('<I', 0xf000)
    digest = 2166136261
    for byte in wire:
        digest = ((digest ^ byte) * 16777619) & 0xffffffff
    strict_sender = number(initial['sender_tid'])
    require(wire[0] == 5 and wire[2:4] == b'\x9d\x40' and 0 < strict_sender < 2**31 and
            all(number(initial[k]) == value for k, value in dict(pid=pid, waiter_tid=strict_sender, attempts=1, requests=1,
                source=0x80020002, request_destination=0x90030001, destination=0x80020002, bytes=12,
                cookie=struct.unpack_from('<I', wire, 4)[0], wire_fnv1a32=digest, reply_free_destination=0x80020002,
                reply_free_source=0x90030001, reply_free_bytes=12, virtual_field_mask=15, virtual_fields_consumed=15).items()) and
            raw_hex(initial, 'reply', 12) == raw_hex(initial, 'freed_reply', 12) == ack and
            all(initial[k] == '1' for k in ('queued', 'request_freed', 'reply_freed', 'clean_completion', 'ap_consumed',
                'virtual_fields_readback', 'diagnostic_only', 'virtual_padding')) and
            all(initial[k] == '0' for k in ('busy', 'guard', 'faults', 'allocate_rc', 'send_rc', 'request_free_rc', 'reply_free_rc',
                'oneway', 'oneway_consumed', 'source_byte1_known', 'business_applied', 'source_dependencies_closed', 'configured',
                'published', 'generation', 'native_cp', 'EE', 'frame', 'capture')) and
            all(initial[k] == '(nil)' for k in ('retained_request', 'live_reply', 'retained_cleanup')) and
            initial['virtual_fields'] == initial['virtual_readback'] == ','.join(str(byte) for byte in wire[8:12]),
            'crank strict initial409d full request/reply/free history differs')
    for r in strict:
        require(all(number(r['fields'][k]) == expected for k, expected in
                dict(pid=pid, sender_tid=strict_sender, attempts=1, requests=1, source=0x80020002,
                     request_destination=0x90030001, destination=0x80020002, bytes=12).items()),
                'crank strict initial409d original identity changed')
        require(all(r['fields'][k] == initial[k] for k in ('cookie', 'wire_fnv1a32', 'source_byte1_known', 'reply',
                    'virtual_field_mask', 'virtual_fields_readback', 'virtual_fields_consumed', 'virtual_fields', 'virtual_readback',
                    'diagnostic_only', 'virtual_padding', 'business_applied', 'source_dependencies_closed', 'configured',
                    'published', 'generation', 'native_cp', 'EE', 'frame', 'capture')),
                'crank strict initial409d immutable bytes/virtual fields/scope changed')
    require(all('diagnostic' not in r and r['fields'].get('request') == wire.hex() and r['fields'].get('pid') == str(pid) and
                r['fields'].get('attempts') == r['fields'].get('requests') == '1' and
                all(r['fields'].get(k) == '0' for k in ('faults', 'allocate_rc', 'send_rc', 'request_free_rc', 'reply_free_rc'))
                for r in strict), 'crank strict initial409d was reset/faulted')
    stages = [r for r in rows if r['tag'] == 'NATIVE_CP_OUTPUT_POLICY_CONSUMED' and
              bank_end[0]['line'] < r['line'] < begin['line']]
    require(len(stages) == 1, 'crank later40f9 independent stage/free missing/ambiguous')
    stage = stages[0]; f = stage['fields']; policy_sender = number(f.get('tid', '0'))
    require(0 < policy_sender < 2**31, 'crank later40f9 original producer invalid')
    expected = dict(pid=str(pid), tid=str(policy_sender), bytes='20', slots='0', copied_readback='1', config_fields='4',
        known_mask='15', request_free_rc='0', request_retained='0', stage_only='1', semantic_applied='0', semantic_slots='0',
        generation_advanced='0', published='0', ACK_sent='0', original_CP_executed='0', EE_verified='0', capture_verified='0')
    require('diagnostic' not in stage and set(f) == set(expected) | {'wire_fnv1a'} and
            all(f.get(k) == value for k, value in expected.items()), 'crank later40f9 actual stage/free fields differ')
    audits = [r for r in rows if r['tag'] == 'NATIVE_CP_BACKGROUND_INPUT_AUDIT' and
              bank_end[0]['line'] < r['line'] < stage['line'] and r['fields'].get('bytes') == '20' and
              r['fields'].get('pid') == str(pid) and r['fields'].get('tid') == str(policy_sender)]
    require(len(audits) == 1, 'crank later40f9 original source audit missing/ambiguous')
    chunks = [r for r in rows if r['tag'] == 'NATIVE_CP_BACKGROUND_INPUT_AUDIT_BYTES' and
              audits[0]['line'] < r['line'] < stage['line'] and all(r['fields'].get(k) == audits[0]['fields'].get(k)
              for k in ('pid', 'tid', 'sequence'))]
    require(len(chunks) == 1, 'crank later40f9 full20 original bytes missing')
    policy = raw_hex(chunks[0]['fields'], 'raw', 20)
    cp_crank_original_audit(rows, policy, pid, policy_sender, bank_end[0]['line'], stage['line'], audits[0]['fields']['pointer'])
    require(policy[0] == 5 and policy[2:4] == b'\xf9\x40' and
            policy[4:8] == payload_read(run, bank_tx['request_payload'])[4:8] and
            writeback.hash_hex(f['wire_fnv1a'], 16) == f'{fnv(policy):016x}' and
            max(r['line'] for r in strict) < stage['line'], 'crank later40f9 source/cookie/full20 seal differs')
    base = number(table['appfw_base'])
    require(base <= number(audits[0]['fields']['producer_return']) < base + 0x8000000,
            'crank later40f9 source callsite outside original appFw')
    return dict(bank_free_line=bank['original_free_line'], strict_initial_free_line=max(r['line'] for r in strict),
                output_policy_free_line=stage['line'], output_policy_sender_tid=policy_sender,
                resource_lines=[r['line'] for r in held])


def check_cp_crank_native(run, rows, transport, tx, before, after, bank, bank_tx, value, transaction, previous_end):
    family = 'FUNCTIONAL_CP_CRANK_CONTROL_'
    records = [r for r in rows if r['tag'] == family + 'EVENT' and number(r['fields']['transaction']) == transaction]
    names = ('BEGIN', 'BEFORE', 'MODEL', 'AFTER', 'VERIFIED', 'REPLY', 'ALLOCATED', 'SENT', 'REQUEST_FREE', 'COMMIT', 'RECEIVE', 'REPLY_FREE')
    require(len(records) == len(names) and {r['fields']['event'] for r in records} == set(names),
            'crank failed/replayed/missing original lifecycle')
    at = {r['fields']['event']: r for r in records}
    require([r['line'] for r in records] == sorted({r['line'] for r in records}) and
            [at[name]['line'] for name in names[:10]] == sorted(at[name]['line'] for name in names[:10]) and
            previous_end < at['BEGIN']['line'] < before['line'] < at['BEFORE']['line'] < tx['line'] < at['MODEL']['line'] <
            after['line'] < at['AFTER']['line'] and at['ALLOCATED']['line'] < at['RECEIVE']['line'] < at['REPLY_FREE']['line'],
            'crank original/call/send/receive/free order differs')
    require(max(at['COMMIT']['line'], at['REPLY_FREE']['line']) == records[-1]['line'],
            'crank lacks a final original clean completion')
    chunks = [r for r in rows if r['tag'] == family + 'BYTES' and number(r['fields']['transaction']) == transaction]
    packet, output = payload_read(run, tx['request_payload']), transfer_output(run, tx)
    prior, following = transfer_output(run, before), transfer_output(run, after)
    reply = b'\x01\0\x9d\x40' + packet[4:8] + struct.pack('<I', 0xf000)
    streams = (('request', packet, 'BEGIN'), ('before_state', prior, 'BEFORE'), ('receipt', output, 'MODEL'),
               ('after_state', following, 'AFTER'), ('reply', reply, 'REPLY'))
    require(len(chunks) == 6, 'crank orphan/missing original full byte chunks')
    for kind, raw, event in streams:
        parent = at[event]; boundary = min(r['line'] for r in records if r['line'] > parent['line'])
        selected = [r for r in chunks if r['fields']['kind'] == kind]
        data = bytearray()
        for row in selected:
            f = row['fields']
            require(parent['line'] < row['line'] < boundary and number(f['offset']) == len(data) and
                    all(f[k] == parent['fields'][k] for k in ('event', 'pid', 'tid', 'transaction', 'native_fnv1a',
                                                            'model_instance', 'bank_generation', 'crank_generation')) and
                    number(f['total']) == len(raw) and int(f['content_fnv1a'], 16) == fnv(raw),
                    'crank byte stream stage/transaction/ticket/identity/seal differs')
            data.extend(raw_hex(f, 'raw', number(f['bytes'])))
        require(bytes(data) == raw, 'crank full request12/STATE128/receipt208/reply12 differs')
    resources = [r for r in rows if r['tag'].startswith(family + 'RESOURCE') and
                 at['BEGIN']['line'] < r['line'] < before['line']]
    require([r['tag'] for r in resources] == [family + name for name in
            ('RESOURCE_DEPENDENCIES', 'RESOURCES_TTS_TABLE', 'RESOURCES_RESERVED')],
            'crank independent resource34 cohort missing/reordered')
    predecessors = cp_crank_predecessors(run, rows, transport, at['BEGIN'], resources[-1], bank, bank_tx, prior)
    pid, sender = transport['pid'], tx['origin']['producer_tid']
    request_pointer = at['BEGIN']['fields']['request_pointer']
    reply_pointer = at['ALLOCATED']['fields']['reply_pointer']
    require(request_pointer != '(nil)' and reply_pointer != '(nil)' and
            abs(number(request_pointer) - number(reply_pointer)) >= 12 and
            at['ALLOCATED']['fields']['allocation_pointer'] == reply_pointer,
            'crank independent ACK allocation aliases the original request')
    audit = cp_crank_original_audit(rows, packet, pid, sender, previous_end, at['BEGIN']['line'], request_pointer)
    base = number(resources[1]['fields']['appfw_base'])
    require(base <= number(audit['fields']['producer_return']) < base + 0x8000000,
            'crank request source callsite outside original appFw')
    previous = [r for r in rows if r['tag'] == family + 'EVENT' and r['line'] == previous_end]
    previous_bank = number(previous[0]['fields']['bank_generation']) if previous else 0
    receiver = number(at['RECEIVE']['fields']['tid'])
    require(0 < sender < 2**31 and 0 < receiver < 2**31, 'crank actual sender/transport receiver invalid')
    sender_progress = (0,) * 5
    for row in records:
        name, f = row['fields']['event'], row['fields']; line = row['line']
        # Only synchronous sender stages share log order; RECEIVE carries its own locked snapshot.
        reached = lambda event: line >= at[event]['line']
        require(all(number(f[k]) == expected for k, expected in dict(pid=pid, sender_tid=sender,
            tid=receiver if name == 'RECEIVE' else sender, transaction=transaction, requests=transaction,
            source=0x80020002, destination=0x90030001, command=0x409d, bytes=12,
            cookie=struct.unpack_from('<I', packet, 4)[0], model_instance=value['model_instance'],
            bank_generation=value['bank_generation'], bank_transaction=bank['transaction'],
            bank_commits=bank['bank_generation'], bank_released=bank['bank_generation'],
            bank_source=0x80020002, bank_destination=0x90030001, bank_command=0x4063, bank_bytes=2564).items()) and
            int(f['native_fnv1a'], 16) == fnv(packet) and int(f['bank_native_fnv1a'], 16) == bank_tx['origin']['fnv1a64'] and
            f['request_pointer'] == request_pointer and f['error'] == f['faults'] == '0' and
            all(f[k] == '0' for k in ('reply_releasing', 'reply_inspecting', 'reply_alias', 'reply_cleanup_freed')),
            'crank immutable native transaction/pointer/source/origin/error differs')
        started, inflight, sent, received, freed, request_freed, releasing, busy, guard = (
            number(f[key]) for key in ('send_started', 'send_inflight', 'ACK_sent', 'reply_received',
                'reply_freed', 'request_freed', 'request_releasing', 'busy', 'guard'))
        if name == 'RECEIVE':
            require((started, inflight, sent) in ((1, 1, 0), (1, 0, 1)) and received == 1 and freed == 0 and
                    (busy, guard) in ((1, 1), (1, 0), (0, 0)) and
                    (not (request_freed or releasing) or sent) and not (request_freed and releasing) and
                    (request_freed or (busy, guard) == (1, 1)),
                    'crank RECEIVE locked send/request-free/guard snapshot is invalid')
        else:
            sent_stage = reached('SENT')
            inline = name == 'REPLY_FREE' and not sent_stage
            require((started, inflight, sent) == (int(sent_stage or inline), int(inline), int(sent_stage)) and
                    request_freed == int(reached('REQUEST_FREE')) and freed == int(reached('REPLY_FREE')) and
                    releasing == 0 and (busy, guard) == ((1, 0) if name == 'BEGIN' else
                        (0, 0) if reached('COMMIT') else (1, 1)),
                    'crank synchronous sender send/free/busy/guard phase differs')
        require(received in (0, 1) and (not received or started) and (not freed or received),
                'crank receive/free flags precede the actual send/receive')
        progress = (started, sent, request_freed, received, freed)
        if number(f['tid']) == sender:
            require(all(old <= current for old, current in zip(sender_progress, progress)),
                    'crank same-sender lifecycle snapshot regressed')
            sender_progress = progress
        expected = dict(before_rc=0 if reached('BEFORE') else -61, model_rc=0 if reached('MODEL') else -61,
            after_rc=0 if reached('AFTER') else -61, allocate_rc=0 if reached('ALLOCATED') else -61,
            send_rc=0 if sent else -61, request_free_rc=0 if request_freed else -61,
            receive_rc=0 if received else -61, reply_free_rc=0 if freed else -61,
            model_called=int(reached('MODEL')), model_committed=int(reached('MODEL')), verified=int(reached('VERIFIED')),
            owned=int(reached('VERIFIED')), reply_allocated=int(reached('ALLOCATED')), reply_valid=int(reached('ALLOCATED')),
            receiver_tid=receiver if received else 0, request_free_tid=sender if request_freed else 0,
            reply_free_tid=sender if freed else 0,
            commits=value['crank_generation'] - 1 + int(reached('MODEL')),
            verified_commits=value['crank_generation'] - 1 + int(reached('VERIFIED')),
            last_bank_generation=value['bank_generation'] if reached('VERIFIED') else previous_bank,
            last_crank_generation=value['crank_generation'] if reached('VERIFIED') else value['crank_generation'] - 1,
            crank_generation=value['crank_generation'] if reached('MODEL') else 0,
            before_config_generation=value['before_config_generation'] if reached('BEFORE') else 0,
            config_generation=value['config_generation'] if reached('MODEL') else 0,
            frame_generation=value['frame_generation'] if reached('BEFORE') else 0, fps=value['fps'] if reached('BEFORE') else 0, mode=0)
        require(all(f[k] == str(expected_value) for k, expected_value in expected.items()),
                'crank actual C rc/generation/lifecycle/ticket counters differ')
        for prefix, size, stage in (('before', 128, 'BEFORE'), ('crank', 208, 'MODEL'), ('after', 128, 'AFTER')):
            require(all(number(f[prefix + suffix]) == expected_value for suffix, expected_value in
                (('_used', size if reached(stage) else 0), ('_required', size if reached(stage) else 0),
                 ('_token', 0), ('_instance', value['model_instance'] if reached(stage) else 0))),
                'crank full real bridge result metadata differs')
        require(f['retained_request'] == (request_pointer if reached('VERIFIED') and not request_freed else '(nil)') and
                f['retained_reply'] == (reply_pointer if reached('ALLOCATED') and not freed else '(nil)') and
                all(f[k] == (reply_pointer if reached('ALLOCATED') else '(nil)') for k in ('reply_pointer', 'allocation_pointer')) and
                int(f['receipt_fnv1a'], 16) == (fnv(output) if reached('MODEL') else 0) and
                int(f['reply_fnv1a'], 16) == (fnv(reply) if reached('REPLY') else 0),
                'crank actual retained/allocated/freed pointer or full content seal differs')
        consumed = bool(sent and received and freed and not inflight)
        complete = bool(number(f['owned']) and number(f['verified']) and request_freed and consumed and
                        not busy and not guard and not releasing)
        require(number(f['reply_consumed']) == int(consumed) and number(f['complete']) == int(complete) and
                number(f['completions']) == value['crank_generation'] - 1 + int(complete),
                'crank ACK/COMMIT is not actual original receive/free completion')
    terminal = records[-1]['fields']
    require(terminal['complete'] == terminal['reply_consumed'] == '1' and all(terminal[k] == '0' for k in
            ('busy', 'guard', 'faults', 'request_releasing', 'reply_releasing', 'reply_inspecting', 'send_inflight')) and
            terminal['retained_request'] == terminal['retained_reply'] == '(nil)', 'crank final owner is not idle/clean/consumed')
    return dict(transaction=transaction, sender_tid=sender, receiver_tid=receiver, request_pointer=request_pointer,
        reply_pointer=reply_pointer, reply_sha256=sha(reply), source_audit_sequence=number(audit['fields']['sequence']),
        original_free_line=at['REQUEST_FREE']['line'], reply_receive_line=at['RECEIVE']['line'],
        reply_free_line=at['REPLY_FREE']['line'], complete_line=records[-1]['line'], **predecessors)


def check_cp_crank_control_content(run, manifest, rows, transport):
    """Join complete Core21 consumption to its original native transaction and resources."""
    transfers = transport['transfers']
    jobs = [(index, tx) for index, tx in enumerate(transfers) if tx['opcode'] == 21]
    native = [row for row in rows if row['tag'].startswith('FUNCTIONAL_CP_CRANK_CONTROL_')]
    result = dict(required=bool(jobs), verified=False, content_join_verified=False, transactions=[],
                  native_completion_verified=False, missing_native_observations=[], frame_consumed=False,
                  capture_verified=False, physical_asic_compatibility_verified=False)
    if not jobs:
        require(not native, 'crank control native records lack actual Core21')
        return result
    backup = manifest.get('backup_transport')
    require(type(backup) is dict and manifest.get('functional_camera_profile') == PROFILE and
            backup.get('functional_camera_profile') == PROFILE and all(
                {key for key in target if key.startswith('functional_camera_cp_crank_control_')} ==
                {'functional_camera_' + key for key in CP_CRANK_CONTROL_POLICY} for target in (manifest, backup)) and all(
                typed_equal(manifest.get('functional_camera_' + key), value) and
                typed_equal(backup.get('functional_camera_' + key), value)
                for key, value in CP_CRANK_CONTROL_POLICY.items()),
            'crank control lacks its complete explicit functional mode0 software policy')
    needed(transport.get('parameter_bank', {}).get('verified') is True,
           'crank control needs the completed current original parameter-bank owner')
    for index, _ in jobs:
        require(index > 0 and index + 1 < len(transfers), 'crank control live State128 queries missing')
        require(all(part.get('frame') is None for part in transfers[index - 1:index + 2]),
                'crank control queries/core/no-frame binding differs')
    history = vdf_history(run, transport)
    bank_receipts = transport['parameter_bank']['transactions']
    native_ids, previous_end, covered_resources = [], 0, set()
    if native:
        allowed = {'FUNCTIONAL_CP_CRANK_CONTROL_' + suffix for suffix in
                   ('EVENT', 'BYTES', 'RESOURCE_DEPENDENCIES', 'RESOURCES_TTS_TABLE', 'RESOURCES_RESERVED')}
        for row in native:
            require(row['tag'] in allowed and 'diagnostic' not in row and bool(row['fields']),
                    'crank failed/unknown/incomplete original formatter')
            payload = (row['tag'] + ' ' + ' '.join(k + '=' + v for k, v in row['fields'].items())).encode('ascii')
            require(console_producer_fields(payload) == row['fields'], 'crank original producer grammar differs')
        native_ids = sorted({number(r['fields']['transaction']) for r in native if r['tag'].endswith('_EVENT')})
        require(native_ids == list(range(1, len(jobs) + 1)) and
                {number(r['fields']['transaction']) for r in native if r['tag'].endswith('_BYTES')} == set(native_ids),
                'crank original transaction/event/byte census differs')
    for ordinal, (index, tx) in enumerate(jobs):
        require(index > 0 and index + 1 < len(transfers), 'crank control live State128 queries missing')
        before, after, origin = transfers[index - 1], transfers[index + 1], tx['origin']
        require(before['opcode'] == after['opcode'] == 2 and before['origin'] == after['origin'] == origin and
                before['first'] == before['last'] == tx['first'] - 1 and
                tx['first'] == tx['last'] == after['first'] - 1 and after['first'] == after['last'] and
                before['line'] < tx['line'] < after['line'] and all(part['token'] == 0 and
                    part.get('frame') is None and part.get('provider_kind') == 'core' for part in (before, tx, after)),
                'crank control queries/core/no-frame binding differs')
        needed(type(tx.get('crank_control')) is dict, 'crank control independent actual C query event')
        banks = [part for part in transfers[:index] if part['opcode'] == 20]
        require(banks, 'crank control lacks its current canonical prior bank decode')
        bank = banks[-1]
        bank_value = history[bank['first']]
        completed = [item for item in bank_receipts if item['model_sequence'] == bank['first'] and
                     item['bank_generation'] == bank_value['bank_generation'] and
                     item['model_instance'] == transport['model_instance'] and
                     item['original_free_line'] < before['line']]
        require(len(completed) == 1, 'crank control current bank was not originally freed before live STATE')
        packet, output = payload_read(run, tx['request_payload']), transfer_output(run, tx)
        prior, following = transfer_output(run, before), transfer_output(run, after)
        value = cp_crank_control_observation(tx['crank_control'].get('observation'), output, packet,
            transport['model_instance'], prior, bank_value['bank_generation'], tx['capacity'])
        require(value == history[tx['first']] and following == output[64:192] and
                origin['source'] == 0x80020002 and origin['destination'] == 0x90030001 and
                origin['command'] == 0x409d and origin['bytes'] == 12 and origin['fnv1a64'] == fnv(packet),
                'crank control current canonical bank/original whole input/history/post-STATE differs')
        transaction = dict(model_sequence=tx['first'], bank_model_sequence=bank['first'],
            before_STATE_sequence=before['first'], after_STATE_sequence=after['first'],
            packet_sha256=sha(packet), result_sha256=sha(output), **value)
        if native:
            joined = check_cp_crank_native(run, rows, transport, tx, before, after, completed[0], bank,
                                          value, native_ids[ordinal], previous_end)
            transaction.update(joined)
            previous_end = joined['complete_line']
            covered_resources.update(joined['resource_lines'])
        result['transactions'].append(transaction)
    result['content_join_verified'] = True
    if native:
        require(covered_resources == {r['line'] for r in native if r['tag'].startswith('FUNCTIONAL_CP_CRANK_CONTROL_RESOURCE')},
                'crank orphan/reused resource34 claim')
        result.update(verified=True, native_completion_verified=True)
    else:
        result['missing_native_observations'] = list(CP_CRANK_NATIVE_JOINS)
    return result


# Insert before check_cp_movie_format_content; replace that function with the one below.
# SOURCE_ONLY: exact movie_format_record formatter, distinct from the unchanged crank family.
CP_MOVIE_EVENT_SCHEMA = (
    'event:crank_event pid:pid tid:tid transaction:u64 sender_tid:tid receiver_tid:tid source:hex32 destination:hex32 '
    'command:hex32 bytes:u32 native_fnv1a:digest cookie:hex32 busy:bit guard:bit faults:u32 error:i32 '
    'before_rc:i32 model_rc:i32 after_rc:i32 validation_rc:i32 model_called:bit model_committed:bit verified:bit owned:bit complete:bit '
    'retained_request:pointer retained_reply:pointer request_pointer:pointer reply_pointer:pointer allocation_pointer:pointer '
    'request_releasing:bit request_freed:bit request_free_rc:i32 request_free_tid:tid reply_releasing:bit reply_inspecting:bit '
    'reply_allocated:bit reply_valid:bit reply_alias:bit allocate_rc:i32 send_started:bit send_inflight:bit send_rc:i32 ACK_sent:bit '
    'reply_received:bit receive_rc:i32 reply_freed:bit reply_cleanup_freed:bit reply_free_rc:i32 reply_free_tid:tid reply_consumed:bit '
    'requests:u64 commits:u64 verified_commits:u64 completions:u64 model_instance:u64 bank_generation:u64 crank_generation:u64 movie_generation:u64 '
    'last_bank_generation:u64 last_crank_generation:u64 last_movie_generation:u64 before_config_generation:u64 config_generation:u64 frame_generation:u64 '
    'software_format:u32 software_rate_index:u32 fps:u32 software_codec:u32 '
    'bank_transaction:u64 bank_commits:u64 bank_released:u64 bank_source:hex32 bank_destination:hex32 bank_command:hex32 bank_bytes:u32 bank_native_fnv1a:digest '
    'crank_transaction:u64 crank_completions:u64 crank_source:hex32 crank_destination:hex32 crank_command:hex32 crank_bytes:u32 crank_native_fnv1a:digest '
    'receipt_fnv1a:digest reply_fnv1a:digest before_used:u64 before_required:u64 before_token:u64 before_instance:u64 '
    'movie_used:u64 movie_required:u64 movie_token:u64 movie_instance:u64 after_used:u64 after_required:u64 after_token:u64 after_instance:u64 '
    'policy:active-config-movie-format5-rate1-0-v1 functional_model:1 original_CP:0 physical_ASIC_verified:0 EE:0 frame:0 capture:0 capture_verified:0')
CP_MOVIE_BYTES_SCHEMA = (
    'event:crank_event pid:pid tid:tid transaction:u64 kind:crank_kind total:u64 offset:u64 bytes:u64 raw:raw '
    'native_fnv1a:digest content_fnv1a:digest model_instance:u64 bank_generation:u64 crank_generation:u64 movie_generation:u64 '
    'functional_model:1 original_CP:0 physical_ASIC_verified:0 capture_verified:0')


def cp_movie_format_initial_history(rows, pid, bank_begin):
    """Keep the original single diagnostic4000 separate from the later functional transaction."""
    family = 'NATIVE_CP_MOVIE_FORMAT_DIAGNOSTIC_'
    names = ('REQUEST_FREE', 'REPLY_FREE', 'COMPLETE')
    history = [r for r in rows if r['tag'].startswith(family)]
    allowed = {family + name for name in names +
               ('PREDECESSORS', 'RESOURCE_DEPENDENCIES', 'RESOURCES_TTS_TABLE', 'RESOURCES_RESERVED')}
    require(all(r['tag'] in allowed and 'diagnostic' not in r for r in history),
            'movie initial strict4000 failed/unknown history')
    records = [r for r in history if r['tag'] in {family + name for name in names}]
    require(len(records) == 3 and {r['tag'] for r in records} == {family + name for name in names},
            'movie initial strict4000 missing/repeated lifecycle')
    at = {r['tag'].removeprefix(family): r for r in records}
    require(at['REQUEST_FREE']['line'] < at['COMPLETE']['line'] and
            max(r['line'] for r in records) < bank_begin,
            'movie initial strict4000 must finish before the first functional bank')
    earlier409d = [r for r in rows if r['tag'] == 'NATIVE_CP_EE_DIAGNOSTIC_REPLY_FREE' and
                   r['fields'].get('opcode') == '0x409d']
    require(len(earlier409d) == 1 and earlier409d[0]['line'] < min(r['line'] for r in records),
            'movie initial strict4000 lacks the original preceding strict409d retirement')
    fields = ('pid opcode sender_tid waiter_tid attempts requests busy guard faults source request_destination destination bytes '
        'request cookie wire_fnv1a32 reply freed_reply reply_free_destination reply_free_source reply_free_bytes allocate_rc send_rc '
        'request_free_rc reply_free_rc queued request_freed reply_freed clean_completion ap_consumed known_field_mask '
        'virtual_field_mask virtual_fields_readback virtual_fields_consumed virtual_fields virtual_readback retained_request live_reply '
        'retained_cleanup diagnostic_only no_publication virtual_padding source_byte1_known source_business_applied current_known '
        'source_dependency_closed business_applied source_dependencies_closed configured published pending_complete generation '
        'native_verified native_cp EE frame capture').split()
    final = records[-1]['fields']
    packet = raw_hex(final, 'request', 20)
    require(packet[:4] == b'\x05\0\0\x40' and packet[8:] == bytes.fromhex('050100000000000000000100'),
            'movie initial strict4000 original20 differs from unchanged cold diagnostic')
    reply = b'\x01\0\0\x40' + packet[4:8] + struct.pack('<I', 0xf000)
    digest = 2166136261
    for byte in packet:
        digest = ((digest ^ byte) * 16777619) & 0xffffffff
    sender = number(final['sender_tid'])
    require(0 < sender < 2**31, 'movie initial strict4000 sender invalid')
    for row in records:
        f = row['fields']
        require(set(f) == set(fields) and all(number(f[k]) == value for k, value in dict(
            pid=pid, opcode=0x4000, sender_tid=sender, attempts=1, requests=1, source=0x80020002,
            request_destination=0x90030001, destination=0x80020002, bytes=20,
            cookie=struct.unpack_from('<I', packet, 4)[0], wire_fnv1a32=digest,
            known_field_mask=127, virtual_field_mask=127, virtual_fields_consumed=127).items()) and
            raw_hex(f, 'request', 20) == packet and raw_hex(f, 'reply', 12) == reply and
            f['virtual_fields'] == f['virtual_readback'] == '5,1,0,0,0,0,1' and
            all(f[k] == '1' for k in ('queued', 'virtual_fields_readback',
                'diagnostic_only', 'no_publication', 'virtual_padding')) and
            all(f[k] == '0' for k in ('faults', 'allocate_rc', 'send_rc', 'request_free_rc', 'reply_free_rc',
                'source_byte1_known', 'source_business_applied', 'current_known', 'source_dependency_closed',
                'business_applied', 'source_dependencies_closed', 'configured', 'published', 'pending_complete',
                'generation', 'native_verified', 'native_cp', 'EE', 'frame', 'capture')) and
            f['retained_cleanup'] == '(nil)' and
            all(f[k] in ('0', '1') for k in ('busy', 'guard', 'request_freed', 'reply_freed', 'clean_completion', 'ap_consumed')),
            'movie initial strict4000 immutable input/transport-only scope/attempts differs')
        freed = f['reply_freed'] == '1'
        require((f['retained_request'] == '(nil)' if f['request_freed'] == '1' else
                 bool(re.fullmatch(r'0x[1-9a-f][0-9a-f]{0,15}', f['retained_request']))) and
                number(f['waiter_tid']) == (sender if freed else 0) and
                raw_hex(f, 'freed_reply', 12) == (reply if freed else bytes(12)) and
                all(number(f[k]) == value for k, value in dict(reply_free_destination=0x80020002 if freed else 0,
                    reply_free_source=0x90030001 if freed else 0, reply_free_bytes=12 if freed else 0).items()) and
                (f['live_reply'] == '(nil)' if freed else bool(re.fullmatch(r'0x[1-9a-f][0-9a-f]{0,15}', f['live_reply']))) and
                number(f['clean_completion']) == number(f['ap_consumed']) ==
                    int(freed and f['request_freed'] == '1' and f['busy'] == f['guard'] == '0'),
                'movie initial strict4000 actual same-sender free/readback/completion differs')
    require(at['REPLY_FREE']['fields']['reply_freed'] == at['REQUEST_FREE']['fields']['request_freed'] == '1' and
            at['COMPLETE']['fields']['busy'] == at['COMPLETE']['fields']['guard'] == '0' and
            final['clean_completion'] == final['ap_consumed'] == '1' and final['live_reply'] == '(nil)',
            'movie initial strict4000 is not cleanly retired')
    return dict(strict_initial_sender_tid=sender, strict_initial_free_line=at['REPLY_FREE']['line'],
                strict_initial_complete_line=records[-1]['line'])


def cp_movie_format_predecessors(rows, transport, begin, resources, bank, crank, before_line):
    """Resource35 must carry current contents, not just accepted=1 or older receipts."""
    pid, sender = transport['pid'], number(begin['fields']['sender_tid'])
    require([r['tag'] for r in resources] == ['FUNCTIONAL_CP_MOVIE_FORMAT_' + name for name in
            ('RESOURCE_DEPENDENCIES', 'RESOURCES_TTS_TABLE', 'RESOURCES_RESERVED')],
            'movie resource35 cohort missing/reordered/repeated')
    dependencies, table, reserved = (r['fields'] for r in resources)
    require(number(dependencies['pid']) == number(table['pid']) == pid and
            all(number(r['fields']['tid']) == sender for r in resources), 'movie resource35 PID/TID differs')
    fixed = dict(dmm_enabled='1', dmm_bound='1', dmm_slots='1/1', dmm_opens='1/1',
        dmm_handles='0x8400/0x8401', dmm_generations='1/1', dmm_epochs='1/2', dmm_creators='1/1',
        dmm_allocation_count='2', dmm_lifecycle_changed='0', dmm_domain='2', foreign_speech_kept='1',
        control_bound='1', connection_started='1', connections='1', format_consumed='1', buffer_released='1',
        connection_reply_frees='1', vef_init='1', vef_owner='0x905a0048', pinmem_init='1', pinmem_owner='0x90590818')
    require(all(reserved[k] == value for k, value in fixed.items()) and
            number(reserved['allocations']) == number(reserved['releases']) > 0 and
            number(reserved['vef_objects']) > 0 and number(reserved['pinmem_objects']) > 0,
            'movie resource35 DMM/PIN/VEF allocation domain differs')
    speech = raw_hex(table, 'raw_before', 144)
    require(raw_hex(table, 'raw_after', 144) == speech, 'movie resource35 TTS144 changed')
    for slot in range(2):
        offset = slot * 0x48
        require(struct.unpack_from('<I', speech, offset)[0] == 0x1a + slot and
                struct.unpack_from('<2I', speech, offset + 0x18) == (0x8400 | slot, 0x80000) and
                struct.unpack_from('<Q', speech, offset + 0x20)[0] == 0x1e000000 + slot * 0x80000,
                'movie resource35 complete TTS144 does not bind both DMM slots')
    banks = [r for r in rows if r['tag'] == 'FUNCTIONAL_CP_PARAMETER_BANK_EVENT' and r['line'] < begin['line']]
    cranks = [r for r in rows if r['tag'] == 'FUNCTIONAL_CP_CRANK_CONTROL_EVENT' and r['line'] < begin['line']]
    needed(banks and cranks, 'movie current completed native bank/crank')
    b, k = banks[-1]['fields'], cranks[-1]['fields']
    require(banks[-1]['fields']['event'] == 'COMMIT' and number(b['transaction']) == bank['transaction'] and
            bank['original_free_line'] < banks[-1]['line'] < crank['complete_line'] < begin['line'] and
            all(b[key] == '1' for key in ('model_called', 'model_committed', 'verified', 'owned', 'request_freed')) and
            all(b[key] == '0' for key in ('guard', 'faults', 'error', 'free_rc', 'releasing')) and b['retained'] == '(nil)' and
            number(b['model_instance']) == transport['model_instance'] and
            number(b['bank_generation']) == bank['bank_generation'] == crank['bank_generation'] and
            number(b['commits']) == number(b['released']) == bank['bank_generation'],
            'movie current native bank is not the actual closed predecessor')
    require(cranks[-1]['line'] == crank['complete_line'] and number(k['transaction']) == crank['transaction'] and
            number(k['model_instance']) == transport['model_instance'] and
            all(k[key] == '1' for key in ('model_called', 'model_committed', 'verified', 'owned', 'complete', 'request_freed',
                'reply_allocated', 'reply_valid', 'send_started', 'ACK_sent', 'reply_received', 'reply_freed', 'reply_consumed')) and
            all(k[key] == '0' for key in ('busy', 'guard', 'faults', 'error', 'before_rc', 'model_rc', 'after_rc', 'allocate_rc',
                'send_rc', 'request_free_rc', 'reply_free_rc', 'receive_rc', 'reply_alias', 'reply_cleanup_freed',
                'request_releasing', 'reply_releasing', 'reply_inspecting', 'send_inflight')) and
            k['retained_request'] == k['retained_reply'] == '(nil)' and
            0 < number(k['sender_tid']) < 2**31 and 0 < number(k['receiver_tid']) < 2**31 and
            k['request_free_tid'] == k['reply_free_tid'] == k['sender_tid'] and
            number(k['crank_generation']) == crank['crank_generation'] and
            number(k['commits']) == number(k['verified_commits']) == number(k['completions']) == crank['crank_generation'],
            'movie current native crank lacks real receive/sender frees/idle completion')
    # Reuse the existing all13 parser/content checks through the recomputed crank proof; recheck current readback here.
    frees = []
    for tag in BACKGROUND_FREE_TAGS:
        found = [r for r in rows if r['tag'] == tag and r['line'] < resources[0]['line']]
        require(len(found) == 1 and 'diagnostic' not in found[0] and
                found[0]['fields'].get('pid') == str(pid) and found[0]['fields'].get('rc') == '0' and
                found[0]['fields'].get('faults') == '0' and found[0]['fields'].get('ap_consumed') == '1',
                'movie all13 actual predecessor free missing/faulted: ' + tag)
        frees.append(found[0]['line'])
    all13 = [r for r in rows if r['tag'] in ('NATIVE_CP302C_DIAGNOSTIC_ALL13_READBACK',
        'NATIVE_CP302C_NOCONVERT_ALL13_READBACK') and max(frees) < r['line'] < before_line and
        r['fields'].get('pid') == str(pid) and r['fields'].get('tid') == str(sender)]
    require(all13 and all('diagnostic' not in r and all(r['fields'].get(key) == '1' for key in
            ('accepted', 'video_AP_consumed', 'OSD_AP_consumed', 'audio_AP_consumed')) and
            r['fields'].get('OSD_live') == '16' and r['fields'].get('OSD_owners_each') ==
            r['fields'].get('OSD_opens_each') == '2' and r['fields'].get('global_DMM_idle_claimed') ==
            r['fields'].get('capture_verified') == '0' for r in all13), 'movie current all13 retirement readback differs')
    mode = cp_parameter_mode_retirement(rows, begin['line'], pid, transport['model_instance'])
    leases = {}
    for row in rows:
        f = row['fields']
        if (row['tag'].startswith('FUNCTIONAL_CAMERA_CONTROL_') and row['line'] <= mode['line'] and
                (f.get('index') in ('0', '1') or f.get('cycle_id') == mode['fields']['cycle_id']) and 'index' in f):
            leases[number(f['index'])] = row
    require(set(leases) == set(range(5)), 'movie current mode lacks all five real retired leases')
    for index, row in leases.items():
        f = row['fields']
        require('diagnostic' not in row and f.get('pid') == str(pid) and
                number(f['model_instance']) == transport['model_instance'] and f.get('retained') == '(nil)' and
                f.get('freed') == '1' and all(f.get(key) == '0' for key in
                    ('faults', 'releasing', 'send_inflight', 'free_rc', 'send_rc', 'allocate_rc')) and
                (index not in (1, 3, 4) or f.get('queued') == f.get('received') == f.get('consumed') == '1') and
                (index < 2 or f.get('sender_tid') == mode['fields']['sender_tid'] and
                 f.get('lease_cycle_id') == mode['fields']['cycle_id'] and all(f.get(key) == mode['fields'].get(key)
                 for key in ('cycle_id', 'cycle_generation', 'config_generation', 'frame_generation', 'native_fnv1a'))) and
                0 < number(f['free_tid']) < 2**31 and f['free_tid'] == f['receiver_tid' if index == 4 else 'sender_tid'],
                'movie current mode lease still live/faulted/foreign/unconsumed')
        actual_free = [r for r in rows if r['tag'] == 'FUNCTIONAL_CAMERA_CONTROL_' +
            ('AP_FREE' if index in (1, 3, 4) else 'OWNED_FREE') and r['line'] <= mode['line'] and all(
            r['fields'].get(key) == f.get(key) for key in ('pid', 'index', 'model_instance', 'lease_cycle_id',
                'sender_tid', 'receiver_tid', 'free_tid', 'freed', 'free_rc', 'retained'))]
        require(actual_free, 'movie current mode lacks its actual original free event')
    first_bank = min(r['line'] for r in rows if r['tag'] == 'FUNCTIONAL_CP_PARAMETER_BANK_EVENT' and
                     r['fields'].get('event') == 'BEGIN')
    initial = cp_movie_format_initial_history(rows, pid, first_bank)
    return dict(bank_free_line=bank['original_free_line'], crank_complete_line=crank['complete_line'],
        current_mode_retired_line=mode['line'], resource_lines=[r['line'] for r in resources], **initial)


def check_cp_movie_format_native(run, rows, transport, tx, before, after, bank, bank_tx,
                                 crank, crank_tx, value, transaction, previous_end):
    family = 'FUNCTIONAL_CP_MOVIE_FORMAT_'
    records = [r for r in rows if r['tag'] == family + 'EVENT' and number(r['fields']['transaction']) == transaction]
    names = ('BEGIN', 'BEFORE', 'MODEL', 'AFTER', 'VERIFIED', 'REPLY', 'ALLOCATED', 'SENT',
             'REQUEST_FREE', 'COMMIT', 'RECEIVE', 'REPLY_FREE')
    require(len(records) == len(names) and {r['fields']['event'] for r in records} == set(names),
            'movie failed/replayed/missing original lifecycle')
    at = {r['fields']['event']: r for r in records}
    require([r['line'] for r in records] == sorted({r['line'] for r in records}) and
            [at[name]['line'] for name in names[:10]] == sorted(at[name]['line'] for name in names[:10]) and
            previous_end < at['BEGIN']['line'] < before['line'] < at['BEFORE']['line'] < tx['line'] < at['MODEL']['line'] <
            after['line'] < at['AFTER']['line'] and at['ALLOCATED']['line'] < at['RECEIVE']['line'] < at['REPLY_FREE']['line'] and
            max(at['COMMIT']['line'], at['REPLY_FREE']['line']) == records[-1]['line'],
            'movie original/call/send/real receive/free order differs')
    packet, output = payload_read(run, tx['request_payload']), transfer_output(run, tx)
    prior, following = transfer_output(run, before), transfer_output(run, after)
    require(value == cp_movie_format_observation(tx['movie_format'].get('observation'), output, packet,
            transport['model_instance'], prior, bank['bank_generation'], crank['crank_generation'], tx['capacity']) and
            following == output[80:208], 'movie native receipt/query/full STATE content differs')
    reply = b'\x01\0\0\x40' + packet[4:8] + struct.pack('<I', 0xf000)
    chunks = [r for r in rows if r['tag'] == family + 'BYTES' and number(r['fields']['transaction']) == transaction]
    require(len(chunks) == 6, 'movie orphan/missing original complete byte streams')
    for kind, raw, event in (('request', packet, 'BEGIN'), ('before_state', prior, 'BEFORE'),
            ('receipt', output, 'MODEL'), ('after_state', following, 'AFTER'), ('reply', reply, 'REPLY')):
        parent = at[event]; boundary = min(r['line'] for r in records if r['line'] > parent['line'])
        selected = [r for r in chunks if r['fields']['kind'] == kind]; data = bytearray()
        for row in selected:
            f = row['fields']
            require(parent['line'] < row['line'] < boundary and number(f['offset']) == len(data) and
                    number(f['bytes']) == min(128, len(raw) - len(data)) and number(f['total']) == len(raw) and
                    all(f[key] == parent['fields'][key] for key in ('event', 'pid', 'tid', 'transaction', 'native_fnv1a',
                        'model_instance', 'bank_generation', 'crank_generation', 'movie_generation')) and
                    int(f['content_fnv1a'], 16) == fnv(raw), 'movie byte stream stage/ticket/identity/seal differs')
            data.extend(raw_hex(f, 'raw', number(f['bytes'])))
        require(bytes(data) == raw, 'movie full request20/STATE128/receipt240/after128/reply12 differs')
    resources = [r for r in rows if r['tag'].startswith(family + 'RESOURCE') and at['BEGIN']['line'] < r['line'] < before['line']]
    predecessors = cp_movie_format_predecessors(rows, transport, at['BEGIN'], resources, bank, crank, before['line'])
    pid, sender = transport['pid'], tx['origin']['producer_tid']
    request_pointer, reply_pointer = at['BEGIN']['fields']['request_pointer'], at['ALLOCATED']['fields']['reply_pointer']
    require(request_pointer != '(nil)' and reply_pointer != '(nil)' and
            number(request_pointer) + 20 <= 2**64 and number(reply_pointer) + 12 <= 2**64 and
            (number(reply_pointer) + 12 <= number(request_pointer) or number(request_pointer) + 20 <= number(reply_pointer)) and
            at['ALLOCATED']['fields']['allocation_pointer'] == reply_pointer,
            'movie independent reply allocation aliases the original20 request')
    audit = cp_crank_original_audit(rows, packet, pid, sender,
        max(previous_end, crank['complete_line']), at['BEGIN']['line'], request_pointer)
    base = number(resources[1]['fields']['appfw_base'])
    require(base <= number(audit['fields']['producer_return']) < base + 0x8000000,
            'movie original20 source callsite outside original appFw')
    previous = [r for r in rows if r['tag'] == family + 'EVENT' and r['line'] == previous_end]
    previous_bank = number(previous[0]['fields']['bank_generation']) if previous else 0
    previous_crank = number(previous[0]['fields']['crank_generation']) if previous else 0
    receiver = number(at['RECEIVE']['fields']['tid'])
    require(0 < sender < 2**31 and 0 < receiver < 2**31 and
            transaction == value['movie_generation'] and value['before_config_generation'] >= crank['config_generation'],
            'movie actual sender/receiver/transaction/current config invalid')
    sender_progress = (0,) * 5
    for row in records:
        name, f, line = row['fields']['event'], row['fields'], row['line']
        reached = lambda event: line >= at[event]['line']
        require(all(number(f[key]) == expected for key, expected in dict(pid=pid, sender_tid=sender,
            tid=receiver if name == 'RECEIVE' else sender, transaction=transaction, requests=transaction,
            source=0x80020002, destination=0x90030001, command=0x4000, bytes=20,
            cookie=struct.unpack_from('<I', packet, 4)[0], model_instance=value['model_instance'],
            bank_generation=value['bank_generation'], crank_generation=value['crank_generation'],
            bank_transaction=bank['transaction'], bank_commits=bank['bank_generation'], bank_released=bank['bank_generation'],
            bank_source=0x80020002, bank_destination=0x90030001, bank_command=0x4063, bank_bytes=2564,
            crank_transaction=crank['transaction'], crank_completions=crank['crank_generation'],
            crank_source=0x80020002, crank_destination=0x90030001, crank_command=0x409d, crank_bytes=12).items()) and
            int(f['native_fnv1a'], 16) == fnv(packet) and
            int(f['bank_native_fnv1a'], 16) == bank_tx['origin']['fnv1a64'] and
            int(f['crank_native_fnv1a'], 16) == crank_tx['origin']['fnv1a64'] and
            f['request_pointer'] == request_pointer and f['error'] == f['faults'] == '0' and
            all(f[key] == '0' for key in ('reply_releasing', 'reply_inspecting', 'reply_alias', 'reply_cleanup_freed')),
            'movie immutable native ticket/PID/source/pointer/predecessor/error differs')
        started, inflight, sent, received, freed, request_freed, releasing, busy, guard = (number(f[key]) for key in
            ('send_started', 'send_inflight', 'ACK_sent', 'reply_received', 'reply_freed', 'request_freed',
             'request_releasing', 'busy', 'guard'))
        if name == 'RECEIVE':
            require((started, inflight, sent) in ((1, 1, 0), (1, 0, 1)) and received == 1 and freed == 0 and
                    (busy, guard) in ((1, 1), (1, 0), (0, 0)) and
                    (not (request_freed or releasing) or sent) and not (request_freed and releasing) and
                    (request_freed or (busy, guard) == (1, 1)),
                    'movie RECEIVE locked send/request-free/guard snapshot invalid')
        else:
            sent_stage = reached('SENT'); inline = name == 'REPLY_FREE' and not sent_stage
            require((started, inflight, sent) == (int(sent_stage or inline), int(inline), int(sent_stage)) and
                    request_freed == int(reached('REQUEST_FREE')) and freed == int(reached('REPLY_FREE')) and releasing == 0 and
                    (busy, guard) == ((1, 0) if name == 'BEGIN' else (0, 0) if reached('COMMIT') else (1, 1)),
                    'movie synchronous sender send/free/busy/guard phase differs')
        require(received in (0, 1) and (not received or started) and (not freed or received),
                'movie receive/free flags precede actual send/receive')
        progress = (started, sent, request_freed, received, freed)
        if number(f['tid']) == sender:
            require(all(old <= current for old, current in zip(sender_progress, progress)),
                    'movie same-sender lifecycle snapshot regressed')
            sender_progress = progress
        # Compare canonical signed formatter strings directly; number() is deliberately unsigned.
        expected = dict(before_rc=0 if reached('BEFORE') else -61, model_rc=0 if reached('MODEL') else -61,
            after_rc=0 if reached('AFTER') else -61, validation_rc=0 if reached('MODEL') else -61,
            allocate_rc=0 if reached('ALLOCATED') else -61, send_rc=0 if sent else -61,
            request_free_rc=0 if request_freed else -61, receive_rc=0 if received else -61, reply_free_rc=0 if freed else -61,
            model_called=int(reached('MODEL')), model_committed=int(reached('MODEL')), verified=int(reached('VERIFIED')),
            owned=int(reached('VERIFIED')), reply_allocated=int(reached('ALLOCATED')), reply_valid=int(reached('ALLOCATED')),
            receiver_tid=receiver if received else 0, request_free_tid=sender if request_freed else 0, reply_free_tid=sender if freed else 0,
            commits=value['movie_generation'] - 1 + int(reached('MODEL')),
            verified_commits=value['movie_generation'] - 1 + int(reached('VERIFIED')),
            last_bank_generation=value['bank_generation'] if reached('VERIFIED') else previous_bank,
            last_crank_generation=value['crank_generation'] if reached('VERIFIED') else previous_crank,
            last_movie_generation=value['movie_generation'] if reached('VERIFIED') else value['movie_generation'] - 1,
            movie_generation=value['movie_generation'] if reached('MODEL') else 0,
            before_config_generation=value['before_config_generation'] if reached('BEFORE') else 0,
            config_generation=value['config_generation'] if reached('MODEL') else 0,
            frame_generation=value['frame_generation'] if reached('BEFORE') else 0,
            fps=value['fps'] if reached('BEFORE') else 0, software_format=5 if reached('MODEL') else 0,
            software_rate_index=0, software_codec=1 if reached('MODEL') else 0)
        require(all(f[key] == str(expected_value) for key, expected_value in expected.items()),
                'movie actual C/validation rc/generations/ticket/lifecycle counters differ')
        for prefix, size, stage in (('before', 128, 'BEFORE'), ('movie', 240, 'MODEL'), ('after', 128, 'AFTER')):
            require(all(number(f[prefix + suffix]) == expected_value for suffix, expected_value in
                (('_used', size if reached(stage) else 0), ('_required', size if reached(stage) else 0),
                 ('_token', 0), ('_instance', value['model_instance'] if reached(stage) else 0))),
                'movie full actual bridge source/destination sizes/token/instance differ')
        require(f['retained_request'] == (request_pointer if reached('VERIFIED') and not request_freed else '(nil)') and
                f['retained_reply'] == (reply_pointer if reached('ALLOCATED') and not freed else '(nil)') and
                all(f[key] == (reply_pointer if reached('ALLOCATED') else '(nil)') for key in ('reply_pointer', 'allocation_pointer')) and
                int(f['receipt_fnv1a'], 16) == (fnv(output) if reached('MODEL') else 0) and
                int(f['reply_fnv1a'], 16) == (fnv(reply) if reached('REPLY') else 0),
                'movie retained/allocated/freed pointers or full receipt240/reply12 seal differs')
        consumed = bool(sent and received and freed and not inflight)
        complete = bool(number(f['owned']) and number(f['verified']) and request_freed and consumed and not busy and not guard and not releasing)
        require(number(f['reply_consumed']) == int(consumed) and number(f['complete']) == int(complete) and
                number(f['completions']) == value['movie_generation'] - 1 + int(complete),
                'movie ACK/COMMIT cannot replace actual original receive and sender frees')
    final = records[-1]['fields']
    require(final['complete'] == final['reply_consumed'] == '1' and all(final[key] == '0' for key in
            ('busy', 'guard', 'faults', 'request_releasing', 'reply_releasing', 'reply_inspecting', 'send_inflight')) and
            final['retained_request'] == final['retained_reply'] == '(nil)', 'movie final native owner not idle/clean/consumed')
    return dict(transaction=transaction, sender_tid=sender, receiver_tid=receiver, request_pointer=request_pointer,
        reply_pointer=reply_pointer, reply_sha256=sha(reply), source_audit_sequence=number(audit['fields']['sequence']),
        original_free_line=at['REQUEST_FREE']['line'], reply_receive_line=at['RECEIVE']['line'], reply_free_line=at['REPLY_FREE']['line'],
        complete_line=records[-1]['line'], native_control_transaction_verified=True, **predecessors)


def check_cp_movie_format_content(run, manifest, rows, transport):
    """Join complete Core22/query240 to the actual native movie transaction and resource35."""
    transfers = transport['transfers']
    jobs = [(index, tx) for index, tx in enumerate(transfers) if tx['opcode'] == 22]
    native = [r for r in rows if r['tag'].startswith('FUNCTIONAL_CP_MOVIE_FORMAT_')]
    result = dict(required=bool(jobs), verified=False, content_join_verified=False, transactions=[],
        native_completion_verified=False, native_control_transaction_verified=False, missing_native_observations=[],
        frame_consumed=False, capture_verified=False, physical_asic_compatibility_verified=False)
    if not jobs:
        require(not native, 'movie format native records lack actual Core22')
        return result
    # Reject incomplete/borrowed frame jobs before any predecessor/history scan.
    for index, tx in jobs:
        require(0 < index < len(transfers) - 1 and all(part.get('frame') is None and part.get('token') == 0 and
                part.get('provider_kind') == 'core' for part in transfers[index - 1:index + 2]),
                'movie format queries/core/no-frame binding differs')
        needed(type(tx.get('movie_format')) is dict, 'movie format independent actual C query event')
        witness = tx['movie_format']
        if witness.get('kind') == 'movie_format_rejected':
            raise MovieFormatRejected(witness)
        require(witness.get('kind') == 'model_movie_format' and type(witness.get('opcode')) is int and
                witness['opcode'] == 22 and type(witness.get('actual_c_result')) is int and witness['actual_c_result'] == 0 and
                witness.get('model_called') is True and witness.get('model_committed') is True and
                witness.get('native_acceptance') is False and witness.get('sequence') == tx['first'] and
                witness.get('model_instance') == transport['model_instance'] and witness.get('origin') == tx['origin'],
                'movie format actual typed Core22 success witness differs')
    backup = manifest.get('backup_transport')
    require(type(backup) is dict and manifest.get('functional_camera_profile') == PROFILE and
            backup.get('functional_camera_profile') == PROFILE and all(
                {key for key in target if key.startswith('functional_camera_cp_movie_format_')} ==
                {'functional_camera_' + key for key in CP_MOVIE_FORMAT_POLICY} for target in (manifest, backup)) and all(
                typed_equal(manifest.get('functional_camera_' + key), value) and
                typed_equal(backup.get('functional_camera_' + key), value) for key, value in CP_MOVIE_FORMAT_POLICY.items()),
            'movie format lacks its complete explicit software mapping policy')
    needed(transport.get('parameter_bank', {}).get('verified') is True and
           transport.get('crank_control_content', {}).get('content_join_verified') is True,
           'movie format needs the decoded current original parameter bank and crank')
    history = vdf_history(run, transport)
    native_ids, previous_end, covered_resources = [], 0, set()
    bank_proof, crank_proof = None, None
    if native:
        allowed = {'FUNCTIONAL_CP_MOVIE_FORMAT_' + name for name in
                   ('EVENT', 'BYTES', 'RESOURCE_DEPENDENCIES', 'RESOURCES_TTS_TABLE', 'RESOURCES_RESERVED')}
        for row in native:
            require(row['tag'] in allowed and 'diagnostic' not in row and bool(row['fields']),
                    'movie failed/unknown/incomplete original formatter')
            payload = (row['tag'] + ' ' + ' '.join(key + '=' + value for key, value in row['fields'].items())).encode('ascii')
            require(console_producer_fields(payload) == row['fields'], 'movie original producer grammar differs')
        native_ids = sorted({number(r['fields']['transaction']) for r in native if r['tag'].endswith('_EVENT')})
        require(native_ids == list(range(1, len(jobs) + 1)) and
                {number(r['fields']['transaction']) for r in native if r['tag'].endswith('_BYTES')} == set(native_ids),
                'movie original transaction/event/byte census differs')
        # Recompute predecessor receipts against these rows/transfers; caller booleans cannot establish real native closure.
        bank_proof = check_cp_parameter_bank(run, manifest, rows, transport)
        crank_proof = check_cp_crank_control_content(run, manifest, rows, dict(transport, parameter_bank=bank_proof))
        needed(bank_proof.get('verified') is True and crank_proof.get('verified') is True and
               crank_proof.get('native_completion_verified') is True, 'movie current bank/crank original native completion')
    for ordinal, (index, tx) in enumerate(jobs):
        before, after, origin = transfers[index - 1], transfers[index + 1], tx['origin']
        require(before['opcode'] == after['opcode'] == 2 and before['origin'] == after['origin'] == origin and
                before['first'] == before['last'] == tx['first'] - 1 and
                tx['first'] == tx['last'] == after['first'] - 1 and after['first'] == after['last'] and
                before['line'] < tx['line'] < after['line'], 'movie format live STATE/core query order/binding differs')
        banks = [part for part in transfers[:index] if part['opcode'] == 20]
        cranks = [part for part in transfers[:index] if part['opcode'] == 21]
        require(banks and cranks and banks[-1]['first'] < cranks[-1]['first'],
                'movie format lacks its current bank/crank canonical prior decode')
        bank_tx, crank_tx = banks[-1], cranks[-1]
        bank_value, crank_value = history[bank_tx['first']], history[crank_tx['first']]
        require(crank_value['bank_generation'] == bank_value['bank_generation'], 'movie format crank belongs to a stale parameter bank')
        packet, raw = payload_read(run, tx['request_payload']), transfer_output(run, tx)
        prior, following = transfer_output(run, before), transfer_output(run, after)
        value = cp_movie_format_observation(tx['movie_format'].get('observation'), raw, packet, transport['model_instance'],
            prior, bank_value['bank_generation'], crank_value['crank_generation'], tx['capacity'])
        require(value == history[tx['first']] and following == raw[80:208] and value['fps'] == bank_value['fps'] and
                origin['source'] == 0x80020002 and origin['destination'] == 0x90030001 and
                origin['command'] == 0x4000 and origin['bytes'] == 20 and origin['fnv1a64'] == fnv(packet),
                'movie format actual full original input/current pair/history/post-STATE differs')
        transaction = dict(model_sequence=tx['first'], bank_model_sequence=bank_tx['first'], crank_model_sequence=crank_tx['first'],
            before_STATE_sequence=before['first'], after_STATE_sequence=after['first'], packet_sha256=sha(packet), result_sha256=sha(raw), **value)
        if native:
            banks_done = [item for item in bank_proof['transactions'] if item['model_sequence'] == bank_tx['first'] and
                item['bank_generation'] == bank_value['bank_generation'] and item['model_instance'] == transport['model_instance']]
            cranks_done = [item for item in crank_proof['transactions'] if item['model_sequence'] == crank_tx['first'] and
                item['bank_generation'] == bank_value['bank_generation'] and item['crank_generation'] == crank_value['crank_generation'] and
                item['model_instance'] == transport['model_instance'] and item['complete_line'] < before['line']]
            require(len(banks_done) == len(cranks_done) == 1, 'movie current bank/crank native receipt missing/ambiguous/stale')
            joined = check_cp_movie_format_native(run, rows, transport, tx, before, after, banks_done[0], bank_tx,
                cranks_done[0], crank_tx, value, native_ids[ordinal], previous_end)
            transaction.update(joined); previous_end = joined['complete_line']; covered_resources.update(joined['resource_lines'])
        result['transactions'].append(transaction)
    result['content_join_verified'] = True
    result['native_records_observed'] = len(native)
    if native:
        require(covered_resources == {r['line'] for r in native if r['tag'].startswith('FUNCTIONAL_CP_MOVIE_FORMAT_RESOURCE')},
                'movie orphan/reused resource35 claim')
        result.update(verified=True, native_completion_verified=True, native_control_transaction_verified=True)
    else:
        result['missing_native_observations'] = list(CP_MOVIE_NATIVE_JOINS)
    return result


def cp_ou_crank_initial_history(rows, pid, bank_begin):
    """The already-used strict4072 is immutable one-way history, never a new reply."""
    family = 'NATIVE_CP_EE_DIAGNOSTIC_'
    records = [r for r in rows if r['tag'].startswith(family) and r['fields'].get('opcode') == '0x4072']
    require(len(records) == 2 and [r['tag'] for r in records] == [family + 'REQUEST_FREE', family + 'COMPLETE'] and
            records[0]['line'] < records[1]['line'] < bank_begin,
            'OU crank strict initial4072 missing/repeated/late one-way history')
    keys = set(('pid opcode sender_tid waiter_tid attempts requests busy guard faults source request_destination destination bytes '
        'request cookie wire_fnv1a32 source_byte1_known reply freed_reply reply_free_destination reply_free_source reply_free_bytes '
        'allocate_rc send_rc request_free_rc reply_free_rc queued request_freed reply_freed clean_completion ap_consumed '
        'oneway oneway_consumed virtual_field_mask virtual_fields_readback virtual_fields_consumed virtual_fields virtual_readback '
        'retained_request live_reply retained_cleanup diagnostic_only virtual_padding business_applied source_dependencies_closed '
        'configured published generation native_cp EE frame capture').split())
    final = records[-1]['fields']
    require(all('diagnostic' not in r and set(r['fields']) == keys for r in records),
            'OU crank strict initial4072 complete formatter differs')
    wire = raw_hex(final, 'request', 12)
    require(wire[0] == 5 and wire[2:4] == b'\x72\x40' and wire[8:] == bytes(4),
            'OU crank strict initial4072 original12/bodyzero differs')
    digest = 2166136261
    for byte in wire:
        digest = ((digest ^ byte) * 16777619) & 0xffffffff
    sender = number(final['sender_tid'])
    require(0 < sender < 2**31, 'OU crank strict initial4072 sender invalid')
    for ordinal, row in enumerate(records):
        f = row['fields']
        expected = dict(pid=pid, opcode=0x4072, sender_tid=sender, waiter_tid=0, attempts=1, requests=1,
            busy=1 - ordinal, guard=1 - ordinal, faults=0, source=0x80020002, request_destination=0x90030001,
            destination=0, bytes=12, cookie=struct.unpack_from('<I', wire, 4)[0], wire_fnv1a32=digest,
            source_byte1_known=0, reply_free_destination=0, reply_free_source=0, reply_free_bytes=0,
            allocate_rc=0, send_rc=0, request_free_rc=0, reply_free_rc=0, queued=0, request_freed=1, reply_freed=0,
            clean_completion=ordinal, ap_consumed=0, oneway=1, oneway_consumed=1, virtual_field_mask=3,
            virtual_fields_readback=1, virtual_fields_consumed=3, diagnostic_only=1, virtual_padding=1,
            business_applied=0, source_dependencies_closed=0, configured=0, published=0, generation=0,
            native_cp=0, EE=0, frame=0, capture=0)
        require(all(number(f[key]) == value for key, value in expected.items()) and
                raw_hex(f, 'request', 12) == wire and f['reply'] == f['freed_reply'] == 'none' and
                f['virtual_fields'] == f['virtual_readback'] == '0,0,0,0' and
                all(f[key] == '(nil)' for key in ('retained_request', 'live_reply', 'retained_cleanup')),
                'OU crank strict initial4072 immutable bytes/one-way/free/attempts/scope differs')
    return dict(strict_initial4072_free_line=records[0]['line'], strict_initial4072_complete_line=records[1]['line'])


def cp_ou_crank_predecessors(run, rows, transport, begin, resources, bank, crank, movie,
                            startup, startup_tx, prior, before_line):
    """Check the actual resource36 and current native owners after reservation."""
    family = 'FUNCTIONAL_CP_OU_CRANK_CONTROL_'
    pid, sender = transport['pid'], number(begin['fields']['sender_tid'])
    require([r['tag'] for r in resources] == [family + name for name in
            ('RESOURCE_DEPENDENCIES', 'RESOURCES_TTS_TABLE', 'RESOURCES_RESERVED')],
            'OU crank resource36 cohort missing/reordered/repeated')
    for row in resources:
        payload = (row['tag'] + ' ' + ' '.join(key + '=' + value for key, value in row['fields'].items())).encode('ascii')
        require('diagnostic' not in row and console_producer_fields(payload) == row['fields'],
                'OU crank resource36 original producer grammar differs')
    dependencies, table, reserved = (r['fields'] for r in resources)
    require(number(dependencies['pid']) == number(table['pid']) == pid and
            all(number(r['fields']['tid']) == sender for r in resources), 'OU crank resource36 PID/TID differs')
    fixed = dict(dmm_enabled='1', dmm_bound='1', dmm_slots='1/1', dmm_opens='1/1',
        dmm_handles='0x8400/0x8401', dmm_generations='1/1', dmm_epochs='1/2', dmm_creators='1/1',
        dmm_allocation_count='2', dmm_lifecycle_changed='0', dmm_domain='2', foreign_speech_kept='1',
        control_bound='1', connection_started='1', connections='1', format_consumed='1', buffer_released='1',
        connection_reply_frees='1', vef_init='1', vef_owner='0x905a0048', pinmem_init='1', pinmem_owner='0x90590818')
    require(all(reserved[key] == value for key, value in fixed.items()) and
            number(reserved['allocations']) == number(reserved['releases']) > 0 and
            number(reserved['vef_objects']) > 0 and number(reserved['pinmem_objects']) > 0,
            'OU crank resource36 TTS/DMM/PIN/VEF allocation domain differs')
    speech = raw_hex(table, 'raw_before', 144)
    require(raw_hex(table, 'raw_after', 144) == speech, 'OU crank resource36 TTS144 changed')
    for slot in range(2):
        offset = slot * 0x48
        require(struct.unpack_from('<I', speech, offset)[0] == 0x1a + slot and
                struct.unpack_from('<2I', speech, offset + 0x18) == (0x8400 | slot, 0x80000) and
                struct.unpack_from('<Q', speech, offset + 0x20)[0] == 0x1e000000 + slot * 0x80000,
                'OU crank resource36 full TTS does not bind both DMM slots')
    for prefix, proof, end_key in (('FUNCTIONAL_CP_PARAMETER_BANK_', bank, 'original_free_line'),
            ('FUNCTIONAL_CP_CRANK_CONTROL_', crank, 'complete_line'), ('FUNCTIONAL_CP_MOVIE_FORMAT_', movie, 'complete_line')):
        found = [r for r in rows if r['tag'] == prefix + 'EVENT' and r['line'] < begin['line']]
        require(found and number(found[-1]['fields']['transaction']) == proof['transaction'] and
                number(found[-1]['fields']['model_instance']) == transport['model_instance'] and
                proof[end_key] <= found[-1]['line'] < begin['line'],
                'OU crank latest native bank/crank/movie is not the recomputed closed predecessor')
        if prefix != 'FUNCTIONAL_CP_PARAMETER_BANK_':
            require(found[-1]['line'] == proof[end_key] and found[-1]['fields']['complete'] == '1',
                    'OU crank latest native crank/movie is not idle/complete')
    require(bank['original_free_line'] < crank['complete_line'] < movie['complete_line'] < startup['free_line'] < begin['line'] and
            startup['AP_consumed'] is True and startup['command'] == 0x4057 and
            startup['model_instance'] == transport['model_instance'] and
            startup['config_generation'] == struct.unpack_from('<Q', prior, 56)[0] > movie['config_generation'] and
            startup['frame_generation'] == struct.unpack_from('<Q', prior, 112)[0] and
            startup['config40_fnv1a64'] == f'{fnv(prior[8:48]):016x}',
            'OU crank current4057 actual free/config/frame/config40 checkpoint differs')
    startup_rows = [r for r in rows if r['tag'] == 'FUNCTIONAL_STARTUP_CONTROL' and r['line'] < begin['line']]
    needed(startup_rows, 'OU crank current4057 actual owner records')
    latest = startup_rows[-1]
    require(number(latest['fields']['cycle']) == startup['cycle'] and latest['fields']['AP_consumed'] == '1' and
            latest['line'] >= startup['free_line'] and latest['fields']['retained'] == '0',
            'OU crank newer/incomplete startup owner replaced current4057')
    startup_records = [r for r in startup_rows if r['fields'].get('cycle') == str(startup['cycle'])]
    require(len(startup_records) == 4 and {r['fields']['event'] for r in startup_records} ==
            {'REQUEST_FREE', 'RECEIVE', 'SENDER_FREE', 'CYCLE'}, 'OU crank current4057 original lease lifecycle differs')
    startup_at = {r['fields']['event']: r for r in startup_records}
    tickets = [r for r in rows if r['tag'] == 'FUNCTIONAL_STARTUP_CONTROL_TICKET_BOUND' and
               r['fields'].get('cycle') == str(startup['cycle'])]
    require(len(tickets) == 1 and tickets[0]['line'] == startup['ticket_line'] and
            startup_at['REQUEST_FREE']['line'] < startup['ticket_line'] < startup['receive_line'] < startup['free_line'] and
            startup_at['RECEIVE']['line'] == startup['receive_line'] and startup_at['SENDER_FREE']['line'] == startup['free_line'] and
            startup_at['REQUEST_FREE']['fields']['request'] == latest['fields']['request'] == '(nil)' and
            startup_at['REQUEST_FREE']['fields']['req_free_rc'] == latest['fields']['req_free_rc'] == '0' and
            startup['sender_tid'] > 0 and startup['receiver_tid'] > 0,
            'OU crank current4057 lacks real sender request/reply retirement')
    wire = bytes.fromhex(startup['original_wire'])
    reply = b'\x01\0\x57\x40' + wire[4:8] + struct.pack('<I', 0xf000)
    ticket = tickets[0]['fields']
    require(len(wire) == 12 and wire[0] == 5 and wire[2:4] == b'\x57\x40' and wire[8:] == bytes(4) and
            all(number(ticket[key]) == value for key, value in dict(pid=pid, tid=startup['sender_tid'],
                cycle=startup['cycle'], source=0x90030001, destination=0x80020002, bytes=12,
                cookie=struct.unpack_from('<I', wire, 4)[0]).items()) and raw_hex(ticket, 'reply', 12) == reply and
            ticket.get('before_actual_send') == '1' and ticket.get('physical_ASIC_verified') == ticket.get('capture_verified') == '0',
            'OU crank current4057 original reply ticket/source/cookie/full12 differs')
    canonical, output = payload_read(run, startup_tx['request_payload']), transfer_output(run, startup_tx)
    require(startup_control_config(canonical) == 0x4057 and canonical[4:24] == bytes(20) and
            struct.unpack_from('<Q', canonical, 24)[0] == fnv(prior[8:48]),
            'OU crank current4057 saved settings/config40 seal differs')
    value = vdf_result(output, canonical, transport['model_instance'], 14, output[128:144])
    p = noncodec_proof(startup_tx, value, transport, output)
    require(typed_equal({key: p['after'][key] for key in ('rendered', 'consumed', 'jpeg_encoded', 'video_encoded')},
                dict(zip(('rendered', 'consumed', 'jpeg_encoded', 'video_encoded'), struct.unpack_from('<4Q', prior, 64)))) and
            p['config_generation'] == startup['config_generation'] and p['frame_generation'] == startup['frame_generation'],
            'OU crank current4057 proof/live State128 counters differ')
    frees = []
    for tag in BACKGROUND_FREE_TAGS:
        found = [r for r in rows if r['tag'] == tag and r['line'] < resources[0]['line']]
        require(len(found) == 1 and 'diagnostic' not in found[0] and
                found[0]['fields'].get('pid') == str(pid) and found[0]['fields'].get('rc') == '0' and
                found[0]['fields'].get('faults') == '0' and found[0]['fields'].get('ap_consumed') == '1',
                'OU crank all13 actual free missing/faulted: ' + tag)
        frees.append(found[0]['line'])
    all13 = [r for r in rows if r['tag'] in ('NATIVE_CP302C_DIAGNOSTIC_ALL13_READBACK',
        'NATIVE_CP302C_NOCONVERT_ALL13_READBACK') and max(frees) < r['line'] < before_line and
        r['fields'].get('pid') == str(pid) and r['fields'].get('tid') == str(sender)]
    require(all13 and any(resources[-1]['line'] < r['line'] for r in all13) and all(
            'diagnostic' not in r and all(r['fields'].get(key) == '1' for key in
                ('accepted', 'video_AP_consumed', 'OSD_AP_consumed', 'audio_AP_consumed')) and
            r['fields'].get('OSD_live') == '16' and r['fields'].get('OSD_owners_each') ==
            r['fields'].get('OSD_opens_each') == '2' and r['fields'].get('global_DMM_idle_claimed') ==
            r['fields'].get('capture_verified') == '0' for r in all13),
            'OU crank current post-reservation all13 retirement readback differs')
    mode = cp_parameter_mode_retirement(rows, before_line, pid, transport['model_instance'])
    require(mode['line'] < resources[0]['line'], 'OU crank current mode changed after resource36 reservation')
    first_bank = min(r['line'] for r in rows if r['tag'] == 'FUNCTIONAL_CP_PARAMETER_BANK_EVENT' and
                     r['fields'].get('event') == 'BEGIN')
    initial = cp_ou_crank_initial_history(rows, pid, first_bank)
    return dict(resource_lines=[r['line'] for r in resources], bank_free_line=bank['original_free_line'],
        crank_complete_line=crank['complete_line'], movie_complete_line=movie['complete_line'],
        startup_free_line=startup['free_line'], current_mode_retired_line=mode['line'], **initial)


def check_cp_ou_crank_native(run, rows, transport, tx, before, after, bank, bank_tx, crank, crank_tx,
                             movie, movie_tx, startup, startup_tx, value, transaction, previous_end):
    family = 'FUNCTIONAL_CP_OU_CRANK_CONTROL_'
    records = [r for r in rows if r['tag'] == family + 'EVENT' and number(r['fields']['transaction']) == transaction]
    names = ('BEGIN', 'BEFORE', 'MODEL', 'AFTER', 'VERIFIED', 'REQUEST_FREE', 'COMMIT')
    require(len(records) == len(names) and [r['fields']['event'] for r in records] == list(names) and
            [r['line'] for r in records] == sorted({r['line'] for r in records}),
            'OU crank failed/replayed/missing one-way original lifecycle')
    at = {r['fields']['event']: r for r in records}
    require(previous_end < at['BEGIN']['line'] < before['line'] < at['BEFORE']['line'] < tx['line'] <
            at['MODEL']['line'] < after['line'] < at['AFTER']['line'],
            'OU crank original/STATE/actual Core23/STATE/free order differs')
    packet, output = payload_read(run, tx['request_payload']), transfer_output(run, tx)
    prior, following = transfer_output(run, before), transfer_output(run, after)
    require(following == output[80:208], 'OU crank native full after-State128 differs')
    chunks = [r for r in rows if r['tag'] == family + 'BYTES' and number(r['fields']['transaction']) == transaction]
    require(len(chunks) == 5, 'OU crank orphan/missing original complete byte streams')
    for kind, raw, event in (('request', packet, 'BEGIN'), ('before_state', prior, 'BEFORE'),
                            ('receipt', output, 'MODEL'), ('after_state', following, 'AFTER')):
        parent = at[event]
        boundary = min(r['line'] for r in records if r['line'] > parent['line'])
        data = bytearray()
        for row in [r for r in chunks if r['fields']['kind'] == kind]:
            f = row['fields']
            require(parent['line'] < row['line'] < boundary and number(f['offset']) == len(data) and
                    number(f['bytes']) == min(128, len(raw) - len(data)) and number(f['total']) == len(raw) and
                    all(f[key] == parent['fields'][key] for key in ('event', 'pid', 'tid', 'transaction', 'native_fnv1a',
                        'model_instance', 'bank_generation', 'crank_generation', 'movie_generation', 'ou_generation')) and
                    int(f['content_fnv1a'], 16) == fnv(raw), 'OU crank byte stream stage/ticket/identity/seal differs')
            data.extend(raw_hex(f, 'raw', number(f['bytes'])))
        require(bytes(data) == raw, 'OU crank complete request12/STATE128/receipt224/after128 differs')
    resources = [r for r in rows if r['tag'].startswith(family + 'RESOURCE') and
                 at['BEGIN']['line'] < r['line'] < before['line']]
    predecessors = cp_ou_crank_predecessors(run, rows, transport, at['BEGIN'], resources,
        bank, crank, movie, startup, startup_tx, prior, before['line'])
    pid, sender = transport['pid'], tx['origin']['producer_tid']
    pointer = at['BEGIN']['fields']['request_pointer']
    require(pointer != '(nil)' and 0 < number(pointer) <= 2**64 - 12,
            'OU crank original request pointer missing/overflow')
    audit = cp_crank_original_audit(rows, packet, pid, sender,
        max(previous_end, movie['complete_line'], startup['free_line']), at['BEGIN']['line'], pointer)
    base = number(resources[1]['fields']['appfw_base'])
    require(base <= number(audit['fields']['producer_return']) < base + 0x8000000,
            'OU crank original12 source callsite outside original appFw')
    previous = [r for r in rows if r['tag'] == family + 'EVENT' and r['line'] == previous_end]
    old = previous[0]['fields'] if previous else {}
    require(transaction == value['ou_generation'] and 0 < sender < 2**31,
            'OU crank actual sender/monotonic transaction differs')
    progress = (0,) * 5
    for row in records:
        f, line = row['fields'], row['line']
        reached = lambda event: line >= at[event]['line']
        require(all(number(f[key]) == expected for key, expected in dict(pid=pid, tid=sender, sender_tid=sender,
            transaction=transaction, requests=transaction, source=0x80020002, destination=0x90030001, command=0x4072, bytes=12,
            cookie=struct.unpack_from('<I', packet, 4)[0], model_instance=value['model_instance'],
            bank_generation=value['bank_generation'], crank_generation=value['crank_generation'], movie_generation=value['movie_generation'],
            bank_transaction=bank['transaction'], bank_commits=bank['bank_generation'], bank_released=bank['bank_generation'],
            crank_transaction=crank['transaction'], crank_completions=crank['crank_generation'],
            movie_transaction=movie['transaction'], movie_completions=movie['movie_generation'],
            startup_cycle=startup['cycle'], startup_completed_cycles=startup['cycle'],
            startup_config_generation=startup['config_generation'], startup_frame_generation=startup['frame_generation'],
            startup_lease_generation=startup['lease_generation']).items()) and
            f['request_pointer'] == pointer and all(f[key] == '0' for key in ('guard_fault', 'faults', 'error', 'releasing')) and
            int(f['native_fnv1a'], 16) == fnv(packet) and int(f['startup_result_fnv1a'], 16) == int(startup['result_fnv1a64'], 16) and
            int(f['startup_config40_fnv1a'], 16) == fnv(prior[8:48]),
            'OU crank immutable native ticket/PID/pointer/current predecessor/seal differs')
        for prefix, source_tx in (('bank', bank_tx), ('crank', crank_tx), ('movie', movie_tx), ('startup', startup_tx)):
            origin = source_tx['origin']
            require(all(number(f[prefix + '_' + key]) == origin[key] for key in ('source', 'destination', 'command', 'bytes')) and
                    int(f[prefix + '_native_fnv1a'], 16) == origin['fnv1a64'],
                    'OU crank native predecessor original source/command/full input seal differs')
        expected = dict(busy=int(not reached('COMMIT')), guard=int(reached('BEFORE') and not reached('COMMIT')),
            before_rc=0 if reached('BEFORE') else -61, model_rc=0 if reached('MODEL') else -61,
            after_rc=0 if reached('AFTER') else -61, validation_rc=0 if reached('MODEL') else -61,
            free_rc=0 if reached('REQUEST_FREE') else -61, free_tid=sender if reached('REQUEST_FREE') else 0,
            model_called=int(reached('MODEL')), model_committed=int(reached('MODEL')), verified=int(reached('VERIFIED')),
            owned=int(reached('VERIFIED')), complete=int(reached('COMMIT')), request_freed=int(reached('REQUEST_FREE')),
            commits=value['ou_generation'] - 1 + int(reached('MODEL')),
            verified_commits=value['ou_generation'] - 1 + int(reached('VERIFIED')),
            completions=value['ou_generation'] - 1 + int(reached('COMMIT')),
            released=value['ou_generation'] - 1 + int(reached('REQUEST_FREE')),
            ou_generation=value['ou_generation'] if reached('MODEL') else 0,
            before_config_generation=value['before_config_generation'] if reached('BEFORE') else 0,
            config_generation=value['config_generation'] if reached('MODEL') else 0,
            frame_generation=value['frame_generation'] if reached('BEFORE') else 0,
            mode=0, fps=value['fps'] if reached('BEFORE') else 0)
        for prefix in ('bank', 'crank', 'movie', 'ou'):
            key = prefix + '_generation'
            expected['last_' + key] = value[key] if reached('VERIFIED') else number(old.get(key, '0'))
        require(all(f[key] == str(expected_value) for key, expected_value in expected.items()),
                'OU crank actual C/validation/free result/generation/lifecycle counters differ')
        for prefix, size, stage in (('before', 128, 'BEFORE'), ('ou', 224, 'MODEL'), ('after', 128, 'AFTER')):
            require(all(number(f[prefix + suffix]) == expected_value for suffix, expected_value in
                (('_used', size if reached(stage) else 0), ('_required', size if reached(stage) else 0),
                 ('_token', 0), ('_instance', value['model_instance'] if reached(stage) else 0))),
                'OU crank full actual bridge size/token/instance differs')
        require(f['retained_request'] == (pointer if reached('VERIFIED') and not reached('REQUEST_FREE') else '(nil)') and
                int(f['receipt_fnv1a'], 16) == (fnv(output) if reached('MODEL') else 0),
                'OU crank retained request or complete receipt224 seal differs')
        current = tuple(number(f[key]) for key in ('model_called', 'model_committed', 'verified', 'request_freed', 'complete'))
        require(all(a <= b for a, b in zip(progress, current)), 'OU crank same-sender snapshot regressed')
        progress = current
    return dict(transaction=transaction, sender_tid=sender, request_pointer=pointer,
        source_audit_sequence=number(audit['fields']['sequence']), original_free_line=at['REQUEST_FREE']['line'],
        complete_line=at['COMMIT']['line'], native_control_transaction_verified=True,
        oneway=True, ACK_sent=False, reply_allocated=False, reply_sent=False, reply_received=False, **predecessors)


def check_cp_ou_crank_control_content(run, manifest, rows, transport):
    """Formal OP23 proof requires this run's native one-way retirement and all predecessors."""
    transfers = transport['transfers']
    jobs = [(index, tx) for index, tx in enumerate(transfers) if tx['opcode'] == 23]
    family = 'FUNCTIONAL_CP_OU_CRANK_CONTROL_'
    native = [r for r in rows if r['tag'].startswith(family)]
    result = dict(required=bool(jobs), verified=False, content_join_verified=False, transactions=[],
        native_completion_verified=False, native_control_transaction_verified=False, missing_native_observations=[],
        frame_consumed=False, capture_verified=False, physical_asic_compatibility_verified=False)
    if not jobs:
        require(not native, 'OU crank native records lack actual Core23')
        return result
    for index, tx in jobs:
        require(0 < index < len(transfers) - 1 and all(part.get('frame') is None and part.get('token') == 0 and
                part.get('provider_kind') == 'core' for part in transfers[index - 1:index + 2]),
                'OU crank queries/core/no-frame binding differs')
        needed(type(tx.get('ou_crank_control')) is dict, 'OU crank independent actual C query event')
        witness = tx['ou_crank_control']
        if witness.get('kind') == 'ou_crank_control_rejected':
            raise OuCrankControlRejected(witness)
        bounded_control_witness(witness)
        require(witness['opcode'] == 23 and witness['sequence'] == tx['first'] and
                witness['model_instance'] == transport['model_instance'] and typed_equal(witness['origin'], tx['origin']) and
                typed_equal(witness['request_payload'], tx['request_payload']) and
                len(tx['output_payloads']) == 1 and typed_equal(witness['output_payload'], tx['output_payloads'][0]),
                'OU crank actual typed Core23 success witness differs')
    backup = manifest.get('backup_transport')
    require(type(backup) is dict and manifest.get('functional_camera_profile') == backup.get('functional_camera_profile') == PROFILE and
            all({key for key in target if key.startswith('functional_camera_cp_ou_crank_control_')} ==
                {'functional_camera_' + key for key in CP_OU_CRANK_CONTROL_POLICY} for target in (manifest, backup)) and
            all(typed_equal(manifest.get('functional_camera_' + key), value) and
                typed_equal(backup.get('functional_camera_' + key), value) for key, value in CP_OU_CRANK_CONTROL_POLICY.items()),
            'OU crank lacks its complete explicit one-way mode0 software policy')
    needed(native, 'OU crank original one-way EVENT/BYTES/resource36 records missing')
    allowed = {family + name for name in ('EVENT', 'BYTES', 'RESOURCE_DEPENDENCIES', 'RESOURCES_TTS_TABLE', 'RESOURCES_RESERVED')}
    for row in native:
        require(row['tag'] in allowed and 'diagnostic' not in row and bool(row['fields']),
                'OU crank failed/unknown/incomplete original formatter')
        payload = (row['tag'] + ' ' + ' '.join(key + '=' + value for key, value in row['fields'].items())).encode('ascii')
        require(console_producer_fields(payload) == row['fields'], 'OU crank original producer grammar differs')
    native_ids = sorted({number(r['fields']['transaction']) for r in native if r['tag'] == family + 'EVENT'})
    require(native_ids == list(range(1, len(jobs) + 1)) and
            {number(r['fields']['transaction']) for r in native if r['tag'] == family + 'BYTES'} == set(native_ids),
            'OU crank original transaction/event/byte census differs')
    history = vdf_history(run, transport)
    # These functions parse actual rows/payloads again. Cached caller booleans are never admission.
    bank_proof = check_cp_parameter_bank(run, manifest, rows, transport)
    current = dict(transport, parameter_bank=bank_proof)
    crank_proof = check_cp_crank_control_content(run, manifest, rows, current)
    current['crank_control_content'] = crank_proof
    movie_proof = check_cp_movie_format_content(run, manifest, rows, current)
    startup_proof = check_startup_control(run, manifest, rows, current)
    needed(all(proof.get('verified') is True for proof in (bank_proof, crank_proof, movie_proof, startup_proof)),
           'OU crank current bank/crank/movie/functional4057 actual native completion')
    previous_end, covered = 0, set()
    for ordinal, (index, tx) in enumerate(jobs):
        before, after, origin = transfers[index - 1], transfers[index + 1], tx['origin']
        require(before['opcode'] == after['opcode'] == 2 and typed_equal(before['origin'], origin) and
                typed_equal(after['origin'], origin) and before['first'] == before['last'] == tx['first'] - 1 and
                tx['first'] == tx['last'] == after['first'] - 1 and after['first'] == after['last'] and
                before['line'] < tx['line'] < after['line'], 'OU crank live STATE/Core23 query order/origin differs')
        previous = {}
        for op in (20, 21, 22, 14):
            found = [part for part in transfers[:index] if part['opcode'] == op]
            require(found, 'OU crank lacks current bank/crank/movie/functional4057 canonical prior decode')
            previous[op] = found[-1]
        bank_tx, crank_tx, movie_tx, startup_tx = (previous[op] for op in (20, 21, 22, 14))
        require(bank_tx['first'] < crank_tx['first'] < movie_tx['first'] < startup_tx['first'] < before['first'] and
                startup_tx['origin']['command'] == 0x4057, 'OU crank current tuple/4057 order differs')
        bank_value, crank_value, movie_value = (history[part['first']] for part in (bank_tx, crank_tx, movie_tx))
        packet, raw = payload_read(run, tx['request_payload']), transfer_output(run, tx)
        prior, following = transfer_output(run, before), transfer_output(run, after)
        value = cp_ou_crank_control_observation(tx['ou_crank_control']['observation'], raw, packet,
            transport['model_instance'], prior, bank_value['bank_generation'], crank_value['crank_generation'],
            movie_value['movie_generation'], tx['capacity'])
        require(value == history[tx['first']] and following == raw[80:208] and value['fps'] == bank_value['fps'] and
                origin['source'] == 0x80020002 and origin['destination'] == 0x90030001 and origin['command'] == 0x4072 and
                origin['bytes'] == 12 and origin['fnv1a64'] == fnv(packet), 'OU crank actual whole input/current tuple/history differs')
        proofs = []
        for proof, source_tx in ((bank_proof, bank_tx), (crank_proof, crank_tx), (movie_proof, movie_tx)):
            found = [item for item in proof['transactions'] if item['model_sequence'] == source_tx['first'] and
                     item['model_instance'] == transport['model_instance']]
            require(len(found) == 1, 'OU crank current native predecessor receipt missing/ambiguous/stale')
            proofs.append(found[0])
        settings = [item for item in startup_proof['cycles'] if item['first'] == startup_tx['first']]
        require(len(settings) == 1 and typed_equal(tx['ou_crank_control']['observation']['predecessor_proof'],
                startup_tx['frame']['proof']), 'OU crank predecessor proof is not this actual current4057')
        joined = check_cp_ou_crank_native(run, rows, transport, tx, before, after, proofs[0], bank_tx,
            proofs[1], crank_tx, proofs[2], movie_tx, settings[0], startup_tx, value, native_ids[ordinal], previous_end)
        previous_end = joined['complete_line']
        covered.update(joined['resource_lines'])
        result['transactions'].append(dict(model_sequence=tx['first'], bank_model_sequence=bank_tx['first'],
            crank_model_sequence=crank_tx['first'], movie_model_sequence=movie_tx['first'], startup_model_sequence=startup_tx['first'],
            before_STATE_sequence=before['first'], after_STATE_sequence=after['first'], packet_sha256=sha(packet), result_sha256=sha(raw),
            **value, **joined))
    require(covered == {r['line'] for r in native if r['tag'].startswith(family + 'RESOURCE')},
            'OU crank orphan/reused resource36 claim')
    result.update(verified=True, content_join_verified=True, native_completion_verified=True,
                  native_control_transaction_verified=True, native_records_observed=len(native))
    return result


def cp_parameter_mode_retirement(rows, begin_line, pid, instance):
    """Use the real latest AP_FREE when the notification retires after COMMIT."""
    resource_tags = {'FUNCTIONAL_CAMERA_CONTROL_' + name for name in
                     ('RESOURCE_DEPENDENCIES', 'RESOURCES_TTS_TABLE', 'RESOURCES_RESERVED')}
    history = [r for r in rows if r['tag'].startswith('FUNCTIONAL_CAMERA_CONTROL_') and
               r['tag'] not in resource_tags and r['line'] < begin_line]
    needed(history, 'parameter bank preceding current functional mode retirement')
    require(all(r['tag'].removeprefix('FUNCTIONAL_CAMERA_CONTROL_') in
                ('PROBE', 'SENT', 'AP_FREE', 'OWNED_FREE', 'COMMIT', 'RECEIVE') and 'diagnostic' not in r for r in history),
            'parameter bank preceding mode contains a failed/unknown lifecycle')
    row = history[-1]; mode = row['fields']
    require(row['tag'] in ('FUNCTIONAL_CAMERA_CONTROL_COMMIT', 'FUNCTIONAL_CAMERA_CONTROL_AP_FREE') and
            'diagnostic' not in row and all(mode.get(k) == '1' for k in
                ('start_complete', 'mode1_complete', 'mode_complete', 'notification_AP_consumed')) and
            all(mode.get(k) == '0' for k in ('faults', 'busy', 'guard')) and
            number(mode['model_instance']) == instance and number(mode['pid']) == pid,
            'parameter bank used historical mode1 before current ACK/full retirement')
    if row['tag'] == 'FUNCTIONAL_CAMERA_CONTROL_AP_FREE':
        cycle, sender = mode.get('cycle_id'), mode.get('sender_tid')
        commits = [r for r in history if r['tag'] == 'FUNCTIONAL_CAMERA_CONTROL_COMMIT' and
                   r['fields'].get('cycle_id') == cycle]
        require(commits and commits[-1]['line'] < row['line'] and all(commits[-1]['fields'].get(k) == mode.get(k)
                for k in ('pid', 'sender_tid', 'model_instance', 'config_generation', 'frame_generation',
                          'cycle_generation', 'cycle_id', 'native_fnv1a')) and
                mode.get('index') in ('3', '4') and mode.get('role') == ('3' if mode['index'] == '4' else '2') and
                mode.get('lease_cycle_id') == cycle and mode.get('tid') == mode.get('free_tid') ==
                mode.get('receiver_tid' if mode['index'] == '4' else 'sender_tid'),
                'parameter bank current notification free transaction/generation/receiver differs')
        leases = {}
        for item in history:
            f = item['fields']
            if f.get('index') in ('0', '1') or f.get('cycle_id') == cycle:
                leases[number(f['index'])] = item
        require(set(leases) == set(range(5)), 'parameter bank current mode lacks all five retired leases')
        for index, item in leases.items():
            f = item['fields']
            require('diagnostic' not in item and item['tag'] == 'FUNCTIONAL_CAMERA_CONTROL_' +
                    ('AP_FREE' if index in (1, 3, 4) else 'OWNED_FREE') and f.get('pid') == str(pid) and
                    number(f['model_instance']) == instance and f.get('retained') == '(nil)' and f.get('freed') == '1' and
                    all(f.get(k) == '0' for k in ('faults', 'releasing', 'send_inflight', 'free_rc', 'send_rc', 'allocate_rc')) and
                    (index not in (1, 3, 4) or f.get('queued') == f.get('received') == f.get('consumed') == '1') and
                    (index < 2 or f.get('sender_tid') == sender and f.get('lease_cycle_id') == cycle and
                     all(f.get(k) == mode.get(k) for k in
                         ('cycle_id', 'cycle_generation', 'config_generation', 'frame_generation', 'native_fnv1a'))) and
                    0 < number(f['free_tid']) < 2**31 and f.get('tid') == f.get('free_tid') ==
                    f.get('receiver_tid' if index == 4 else 'sender_tid'),
                    'parameter bank current mode lease is live/faulted/unconsumed/foreign')
    return row


def check_cp_parameter_bank(run, manifest, rows, transport):
    """Join the complete functional bank to its original one-way request/free."""
    transfers = transport['transfers']
    jobs = [(i, tx) for i, tx in enumerate(transfers) if tx['opcode'] == 20]
    events = [r for r in rows if r['tag'] == 'FUNCTIONAL_CP_PARAMETER_BANK_EVENT']
    chunks = [r for r in rows if r['tag'] == 'FUNCTIONAL_CP_PARAMETER_BANK_BYTES']
    resources = [r for r in rows if r['tag'] in {'FUNCTIONAL_CP_PARAMETER_BANK' + suffix for suffix in
                 ('_RESOURCE_DEPENDENCIES', '_RESOURCES_TTS_TABLE', '_RESOURCES_RESERVED')}]
    result = dict(required=bool(jobs), verified=False, transactions=[], frame_consumed=False,
                  capture_verified=False, physical_asic_compatibility_verified=False)
    if not jobs:
        require(not events and not chunks and not resources, 'parameter bank native records lack actual Core20')
        return result
    backup = manifest.get('backup_transport')
    require(type(backup) is dict and all(typed_equal(manifest.get('functional_camera_' + key), value) and
            typed_equal(backup.get('functional_camera_' + key), value) for key, value in CP_PARAMETER_BANK_POLICY.items()),
            'parameter bank lacks its complete explicit software policy')
    for row in events + chunks + resources:
        needed('diagnostic' not in row and bool(row['fields']), 'parameter bank complete original formatter')
        payload = (row['tag'] + ' ' + ' '.join(key + '=' + value for key, value in row['fields'].items())).encode('ascii')
        require(console_producer_fields(payload) == row['fields'], 'parameter bank producer grammar differs')
    ids = sorted({number(r['fields']['transaction']) for r in events})
    needed(len(ids) == len(jobs) and ids and ids[0] > 0, 'parameter bank original transaction/event census')
    require({number(r['fields']['transaction']) for r in chunks} == set(ids),
            'parameter bank orphan or missing complete byte streams')
    previous_bank, previous_line, covered_resources = 0, 0, set()
    names = ('BEGIN', 'BEFORE', 'MODEL', 'AFTER', 'VERIFIED', 'OWNED_FREE', 'COMMIT')
    for transaction, (index, tx) in zip(ids, jobs):
        records = [r for r in events if number(r['fields']['transaction']) == transaction]
        require([r['fields']['event'] for r in records] == list(names),
                'parameter bank failed/replayed/missing original lifecycle')
        at = dict(zip(names, records)); final = at['COMMIT']['fields']; origin = tx['origin']
        require(index > 0 and index + 1 < len(transfers), 'parameter bank live State128 queries missing')
        before, after = transfers[index - 1], transfers[index + 1]
        require(before['opcode'] == after['opcode'] == 2 and before['origin'] == after['origin'] == origin and
                before['first'] == before['last'] == tx['first'] - 1 and
                tx['first'] == tx['last'] == after['first'] - 1 and after['first'] == after['last'] and
                all(part['token'] == 0 and part.get('frame') is None and part.get('provider_kind') == 'core'
                    for part in (before, tx, after)), 'parameter bank queries/core/no-frame binding differs')
        needed(type(tx.get('parameter_bank')) is dict, 'parameter bank independent actual C query event')
        packet, output = payload_read(run, tx['request_payload']), transfer_output(run, tx)
        prior, following = transfer_output(run, before), transfer_output(run, after)
        witness = tx['parameter_bank'].get('observation')
        needed(type(witness) is dict, 'parameter bank independent C State128 observation')
        require(raw_hex(witness, 'before_state_hex', 128) == prior and
                raw_hex(witness, 'after_state_hex', 128) == following,
                'parameter bank independent queries differ from bracketing live State128')
        value = cp_parameter_bank_result(output, packet, transport['model_instance'], prior)
        require(value['bank_generation'] == previous_bank + 1 and following == output[64:192] and
                origin['source'] == 0x80020002 and origin['destination'] == 0x90030001 and
                origin['command'] == 0x4063 and origin['bytes'] == 2564 and origin['fnv1a64'] == fnv(packet),
                'parameter bank actual whole input/history/post-STATE differs')
        previous_bank = value['bank_generation']
        require(previous_line < at['BEGIN']['line'] < before['line'] < at['BEFORE']['line'] < tx['line'] <
                at['MODEL']['line'] < after['line'] < at['AFTER']['line'] < at['VERIFIED']['line'] <
                at['OWNED_FREE']['line'] < at['COMMIT']['line'], 'parameter bank original/call order differs')
        native_streams = {}
        for kind, size, event in (('request', 2564, 'BEGIN'), ('before_state', 128, 'BEFORE'),
                                  ('receipt', 2756, 'MODEL'), ('after_state', 128, 'AFTER')):
            selected = [r for r in chunks if number(r['fields']['transaction']) == transaction and r['fields']['kind'] == kind]
            needed(selected, 'parameter bank full native bytes: ' + kind)
            data = bytearray(); parent = at[event]; boundary = records[names.index(event) + 1]['line']
            for row in selected:
                f = row['fields']
                require(parent['line'] < row['line'] < boundary and number(f['offset']) == len(data) and
                        number(f['total']) == size and all(f[k] == parent['fields'][k] for k in
                        ('pid', 'tid', 'native_fnv1a', 'model_instance', 'bank_generation')),
                        'parameter bank byte chunk offset/identity/stage differs')
                data.extend(raw_hex(f, 'raw', number(f['bytes'])))
            require(len(data) == size, 'parameter bank native bytes truncated')
            native_streams[kind] = bytes(data)
        require(native_streams == dict(request=packet, before_state=prior, receipt=output, after_state=following),
                'parameter bank original bank/result/query bytes differ from actual Core payloads')
        for row in records:
            f = row['fields']
            require(all(number(f[key]) == value for key, value in dict(pid=transport['pid'], tid=origin['producer_tid'],
                    sender_tid=origin['producer_tid'], source=origin['source'], destination=origin['destination'],
                    command=0x4063, bytes=2564, cookie=struct.unpack_from('<I', packet, 4)[0]).items()) and
                    int(f['native_fnv1a'], 16) == origin['fnv1a64'] and f['busy'] == '1' and
                    f['error'] == f['model_rc'] == f['faults'] == '0', 'parameter bank native identity/error differs')
        require(all(final[key] == '1' for key in ('model_called', 'model_committed', 'verified', 'owned', 'request_freed')) and
                all(final[key] == '0' for key in ('guard', 'releasing', 'free_rc')) and final['retained'] == '(nil)' and
                number(final['free_tid']) == origin['producer_tid'] and
                number(final['commits']) == number(final['released']) == value['bank_generation'] and
                all(number(final[key]) == value[key] for key in ('model_instance', 'bank_generation',
                    'before_config_generation', 'config_generation', 'fps')) and
                all(number(final[name + '_used']) == number(final[name + '_required']) == size and
                    number(final[name + '_token']) == 0 and number(final[name + '_instance']) == transport['model_instance']
                    for name, size in (('before', 128), ('bank', 2756), ('after', 128))),
                'parameter bank actual commit/readback/request free is incomplete')
        verified, freed = at['VERIFIED']['fields'], at['OWNED_FREE']['fields']
        require(verified['owned'] == verified['verified'] == '1' and verified['request_freed'] == '0' and
                verified['retained'] != '(nil)' and freed['request_freed'] == '1' and freed['free_rc'] == '0' and
                freed['retained'] == '(nil)' and number(freed['released']) == value['bank_generation'],
                'parameter bank lacked the retained original request before actual free')
        audits = [r for r in rows if r['tag'] == 'NATIVE_CP_BACKGROUND_INPUT_AUDIT' and
                  previous_line < r['line'] < at['BEGIN']['line'] and r['fields'].get('pointer') == verified['retained']]
        require(len(audits) == 1, 'parameter bank missing/duplicate original pointer audit')
        audit = audits[0]; af = audit['fields']; data = bytearray()
        audit_chunks = [r for r in rows if r['tag'] == 'NATIVE_CP_BACKGROUND_INPUT_AUDIT_BYTES' and
                        audit['line'] < r['line'] < at['BEGIN']['line'] and
                        all(r['fields'].get(k) == af.get(k) for k in ('pid', 'tid', 'sequence'))]
        for row in audit_chunks:
            f = row['fields']; require(number(f['offset']) == len(data), 'parameter bank audit chunk gap/overlap')
            data.extend(raw_hex(f, 'raw', number(f['bytes'])))
        require(bytes(data) == packet and af['entry'] == 'async' and all(af.get(k) == '1' for k in
                ('size_known', 'source_known', 'bytes_complete', 'complete')) and all(af.get(k) == '0' for k in
                ('consumed', 'state_verified', 'capture_verified')) and all(number(af[k]) == v for k, v in
                dict(pid=transport['pid'], tid=origin['producer_tid'], source=origin['source'],
                     destination=origin['destination'], bytes=2564).items()), 'parameter bank original full audit differs')
        held = [r for r in resources if at['BEGIN']['line'] < r['line'] < before['line']]
        require([r['tag'] for r in held] == ['FUNCTIONAL_CP_PARAMETER_BANK' + suffix for suffix in
                ('_RESOURCE_DEPENDENCIES', '_RESOURCES_TTS_TABLE', '_RESOURCES_RESERVED')],
                'parameter bank independent resource33 cohort missing/reordered')
        for row in held:
            require(number(row['fields']['tid']) == origin['producer_tid'], 'parameter bank resource owner thread differs')
            covered_resources.add(row['line'])
        table, reserved = held[1]['fields'], held[2]['fields']
        require(number(held[0]['fields']['pid']) == number(table['pid']) == transport['pid'],
                'parameter bank resource33 PID differs from this original process')
        fixed = dict(dmm_enabled='1', dmm_bound='1', dmm_slots='1/1', dmm_opens='1/1',
            dmm_handles='0x8400/0x8401', dmm_generations='1/1', dmm_epochs='1/2', dmm_creators='1/1',
            dmm_allocation_count='2', dmm_lifecycle_changed='0', dmm_domain='2', foreign_speech_kept='1',
            control_bound='1', connection_started='1', connections='1', format_consumed='1', buffer_released='1',
            connection_reply_frees='1', vef_init='1', vef_owner='0x905a0048', pinmem_init='1', pinmem_owner='0x90590818')
        require(all(reserved[k] == expected for k, expected in fixed.items()) and
                number(reserved['allocations']) == number(reserved['releases']) > 0 and
                number(reserved['vef_objects']) > 0 and number(reserved['pinmem_objects']) > 0,
                'parameter bank resource33 is not the admitted speech-initial allocation/idle registry')
        speech = raw_hex(table, 'raw_before', 144)
        require(raw_hex(table, 'raw_after', 144) == speech, 'parameter bank speech table changed during reservation')
        for slot in range(2):
            entry = slot * 0x48
            require(struct.unpack_from('<I', speech, entry)[0] == 0x1a + slot and
                    struct.unpack_from('<2I', speech, entry + 0x18) == (0x8400 | slot, 0x80000) and
                    struct.unpack_from('<Q', speech, entry + 0x20)[0] == 0x1e000000 + slot * 0x80000,
                    'parameter bank resource33 TTS bytes do not bind the two admitted DMM slots')
        require(number(af['producer_return']) == number(table['appfw_base']) + 0x3535a68,
                'parameter bank original one-way sender callsite differs')
        cp_parameter_mode_retirement(rows, at['BEGIN']['line'], transport['pid'], transport['model_instance'])
        result['transactions'].append(dict(transaction=transaction, bank_generation=value['bank_generation'],
            source_audit_sequence=number(af['sequence']), original_free_line=at['OWNED_FREE']['line'],
            model_sequence=tx['first'], before_STATE_sequence=before['first'], after_STATE_sequence=after['first'],
            result_sha256=sha(output), packet_sha256=sha(packet), **{k: value[k] for k in
            ('model_instance', 'before_config_generation', 'config_generation', 'frame_generation', 'fps')}))
        previous_line = at['COMMIT']['line']
    require(covered_resources == {r['line'] for r in resources}, 'parameter bank orphan resource33 claim')
    result['verified'] = True
    return result


def camera_packets(raw):
    """Parse actual Packet96 + config + AU results, including the real EOS."""
    cursor, packets = 0, []
    while cursor < len(raw):
        require(len(raw) - cursor >= 96 and len(packets) < 100000, 'truncated/excess Packet96')
        header = raw[cursor:cursor + 96]
        width, height = struct.unpack_from('<2I', header)
        pts, dts, duration = struct.unpack_from('<3Q', header, 8)
        hz, fps, key, flags = struct.unpack_from('<4I', header, 32)
        count, generation = struct.unpack_from('<2Q', header, 48)
        config, codec = struct.unpack_from('<2I', header, 64)
        require(0 < width <= 1920 and 0 < height <= 1080 and hz == 1 and fps == 30 and
                key in (0, 1) and flags in (0, 1) and codec == 0x61766331 and header[72:] == bytes(24) and
                96 + config + count <= len(raw) - cursor, 'actual Packet96 layout/range differs')
        begin, end = cursor + 96, cursor + 96 + config + count
        require(not flags or end == len(raw), 'actual EOS is not the final packet')
        configuration, packet = raw[begin:begin + config], raw[begin + config:end]
        if count:
            require(pts == dts and duration == 1 and generation > 0 and config > 0, 'actual coded Packet96 metadata')
            params, nals = annex_nals(configuration), annex_nals(packet)
            require([n[0] & 31 for n in params] == [7, 8] and any(1 <= n[0] & 31 <= 5 for n in nals),
                    'actual AVC parameters/VCL missing')
        else:
            require(flags == 1 and not config and not duration and pts == dts, 'empty packet is not drained EOS')
            params, nals = [], []
        packets.append(dict(offset=cursor, config_offset=begin, packet_offset=begin + config,
                            geometry=(width, height), pts=pts, dts=dts, duration=duration,
                            generation=generation, key=key, eos=bool(flags), parameters=params,
                            config=configuration, packet=packet, nals=nals))
        cursor = end
    require(packets, 'empty actual Packet96 result')
    return packets


def retained_frame_proof(op, incoming, output, p, delta, retained, generation, config, result_token, instance):
    expected_kind = {17: 7, 18: 8, 19: 9, 66: 9}[op]
    result_data = output if op in (17, 18) else b''
    require(p['consumer_kind'] == expected_kind and p['result_bytes'] == len(result_data) and
            p['result_fnv1a64'] == fnv(result_data) and p['result_token'] == result_token,
            'retained frame result/proof binding differs')
    if op == 17:
        require(retained is None and len(incoming) == 16 and len(output) >= 96,
                'retained capture overlaps an existing frame or is truncated')
        version, header = struct.unpack_from('<2I', output)
        token, model, lifetime, saved_config, frame_generation = struct.unpack_from('<5Q', output, 8)
        width, height, stride, pixels = struct.unpack_from('<4I', output, 48)
        size, digest = struct.unpack_from('<2Q', output, 64)
        require(version == 1 and header == 96 and token and model == instance and
                lifetime == p['model_lifetime'] and saved_config == config and frame_generation == generation + 1 and
                0 < width <= 8192 and 0 < height <= 8192 and stride == width * 3 and pixels == 1 and
                size == stride * height == len(output) - 96 and digest == fnv(output[96:]) and
                output[80:84] == incoming[4:8] and output[84] == incoming[8] and
                output[85:88] == bytes(3) and struct.unpack_from('<Q', output, 88)[0] == fnv(incoming),
                'retained frame header/pixels/original request differ')
        require(p['render_observed'] == 1 and p['render_status'] == 0 and
                p['frame_generation'] == frame_generation and p['config_generation'] == saved_config and
                p['lease_generation'] > 0 and (p['width'], p['height'], p['stride']) == (width, height, stride) and
                p['active_bytes'] == size and p['source_fnv1a64'] == digest and
                p['source_state'] == p['final_state'] == 3 and not p['retired'] and
                p['retire_status'] == -errno.ENODATA and not p['encoder_consumed'] and
                delta == dict(rendered=1, consumed=1, jpeg_encoded=0, video_encoded=0, retired=0),
                'capture copy was falsely reported as encoding or retirement')
        retained = dict(token=token, config=saved_config, frame=frame_generation,
                        lease=p['lease_generation'], width=width, height=height, stride=stride,
                        size=size, digest=digest, encoded_mask=0)
    else:
        require(retained is not None and len(incoming) in ((32, 160) if op == 18 else (0,) if op == 66 else (16,)) and
                (op == 66 or struct.unpack_from('<Q', incoming)[0] == retained['token']) and
                p['config_generation'] == retained['config'] and p['frame_generation'] == retained['frame'] and
                p['lease_generation'] == retained['lease'] and
                (p['width'], p['height'], p['stride']) == (retained['width'], retained['height'], retained['stride']) and
                p['active_bytes'] == retained['size'] and p['source_fnv1a64'] == retained['digest'] and
                not p['render_observed'] and delta['rendered'] == delta['video_encoded'] == 0,
                'retained frame token/source/lifetime changed across calls')
        if op == 18:
            selector, reserved = struct.unpack_from('<2I', incoming, 8)
            flags, width, height, quality = struct.unpack_from('<4I', incoming, 16)
            require(selector <= 2 and not reserved and not retained['encoded_mask'] & (1 << selector) and
                    flags & 3 in (1, 2) and not flags & ~7 and len(incoming) == (160 if flags & 4 else 32) and
                    0 < width <= 8192 and 0 < height <= 8192 and 0 < quality <= 100 and
                    (not flags & 4 or all(incoming[32:])), 'retained JPEG parameters/selector differ')
            if flags & 2:
                require(output[:2] == b'\xff\xda' and output[-2:] == b'\xff\xd9',
                        'retained scan output lacks actual scan/EOI')
                encoded = output
            else:
                parts = jpeg_parts(output)
                require(parts['geometry'] == (width, height), 'retained JPEG target geometry differs')
                encoded = parts['scan']
            require(p['encoder_consumed'] == 1 and not p['retired'] and p['retire_status'] == -errno.ENODATA and
                    p['final_state'] == 3 and
                    delta == dict(rendered=0, consumed=1, jpeg_encoded=1, video_encoded=0, retired=0) and
                    p['encoded_bytes'] == len(encoded) and p['encoded_fnv1a64'] == fnv(encoded),
                    'retained JPEG was rerendered, retired, or lacks actual encoded bytes')
            retained = dict(retained, encoded_mask=retained['encoded_mask'] | (1 << selector))
        else:
            require(not result_token and p['retired'] == 1 and p['retire_status'] == 0 and
                    p['final_state'] == 1 and not p['encoder_consumed'] and
                    not p['consumer_entered'] and not p['consumer_returned'] and
                    delta == dict(rendered=0, consumed=0, jpeg_encoded=0, video_encoded=0, retired=1),
                    'retained frame release lacks actual optical retirement')
            if op == 19:
                mask, disposition = struct.unpack_from('<2I', incoming, 8)
                require(disposition in (0, 1) and mask == retained['encoded_mask'] and
                        (disposition or mask & 1), 'retained release forged a completed selector')
            return None
    require(p['consumer_entered'] == p['consumer_returned'] == 1 and p['consumer_status'] == 0 and
            p['consumer_before_state'] == p['consumer_after_state'] == 4 and
            p['source_fnv1a64'] == p['consumer_before_fnv1a64'] == p['consumer_after_fnv1a64'],
            'retained source copy/encoder read differs from immutable pixels')
    return retained


def check_frames(run, transport, *, require_media=True, require_codecs=None):
    # Existing component callers use require_codecs; both defaults still require all media jobs.
    require_media = require_media and require_codecs is not False
    jobs, counts, serial, lifetime, generation, config = [], None, 0, None, 0, None
    sensor_initialized, video_geometry, geometry = False, None, None
    retained = None
    for tx in transport['transfers']:
        if tx['opcode'] == 22:
            require(tx.get('frame') is None and tx.get('token') == 0,
                    'movie format borrowed a frame proof or retained result')
        if tx['opcode'] == 23:
            require(tx.get('frame') is None and tx.get('token') == 0,
                    'OU crank borrowed a frame proof or retained result')
    display_history = vdf_history(run, transport)
    for tx in transport['transfers']:
        op, event = tx['opcode'], tx.get('frame')
        if op in (1, 2, 3, 32, 66):
            raw = transfer_output(run, tx)
            require(len(raw) == 128 and struct.unpack_from('<I', raw)[0] == 1 and
                    struct.unpack_from('<Q', raw, 48)[0] == transport['model_instance'] and raw[120:] == bytes(8),
                    'actual State128 identity/reserved bytes differ')
            state_counts = dict(zip(('rendered', 'consumed', 'jpeg_encoded', 'video_encoded'),
                                   struct.unpack_from('<4Q', raw, 64)))
            state_generation = struct.unpack_from('<Q', raw, 112)[0]
            geometry = struct.unpack_from('<2I', raw, 8)
            next_config = struct.unpack_from('<Q', raw, 56)[0]
            require(next_config > 0 and (config is None or next_config >= config), 'state configuration generation regressed')
            config = next_config
            if op == 32:
                incoming = payload_read(run, tx['request_payload'])
                video_geometry = struct.unpack_from('<2I', raw, 8)
                require(len(incoming) == 48 and struct.unpack_from('<3I', incoming) == (*video_geometry, 30) and
                        struct.unpack_from('<I', raw, 16)[0] == 30 and struct.unpack_from('<I', raw, 108)[0] == 1,
                        'actual VIDEO_BEGIN configuration/State128 geometry differs')
        vdf = None
        if op == 21:
            crank = display_history[tx['first']]
            require(event is None and crank['before_config_generation'] == config and
                    crank['frame_generation'] == generation and tx['token'] == 0,
                    'crank control borrowed a frame proof or changed frame/config history')
            config = crank['config_generation']
        if op == 22:
            movie = display_history[tx['first']]
            require(retained is None and movie['before_config_generation'] == config and movie['frame_generation'] == generation,
                    'movie format changed frame/config history or overlaps a retained optical frame')
            config = movie['config_generation']
        if op == 23:
            ou = display_history[tx['first']]
            require(retained is None and event is None and tx['token'] == 0 and
                    ou['before_config_generation'] == config and ou['frame_generation'] == generation,
                    'OU crank changed frame/config history or overlaps a retained optical frame')
            config = ou['config_generation']
        if op in CONFIG_OPERATIONS:
            vdf = display_history[tx['first']]
            require(vdf['before_config_generation'] == config and vdf['before_frame_generation'] == generation and
                    (vdf['width'], vdf['height']) == geometry and tx['token'] == 0,
                    'VDF before generations/geometry differ from actual model history')
            config = vdf['config_generation']
        required = op in CONFIG_OPERATIONS or op in (16, 17, 18, 19, 33, 34) or op == 66 and retained is not None or op == 1 and not sensor_initialized
        needed(not required or type(event) is dict, 'model_frame: actual per-job RGB consumer snapshot for opcode=' + str(op))
        if event is None:
            if op in (1, 2, 3, 32, 66) and counts is not None:
                require(all(state_counts[k] == counts[k] for k in state_counts) and state_generation == generation,
                        'actual State128 counters differ from preceding frame job')
            continue
        p = event.get('proof')
        needed(type(p) is dict, 'model_frame: proof')
        signed = ('render_status', 'consumer_status', 'retire_status', 'operation_status')
        needed(all(k in p for k in ('before', 'after') + signed), 'model_frame: statuses and before/after counters')
        for key, value in p.items():
            if key in ('before', 'after'):
                require(type(value) is dict and set(value) == {'rendered', 'consumed', 'jpeg_encoded', 'video_encoded', 'retired'},
                        'actual frame counter schema differs')
                for number_value in value.values():
                    uint(number_value)
            elif key in signed:
                require(type(value) is int and -4095 <= value <= 0, 'invalid actual consumer status')
            else:
                uint(value)
        require(p['version'] == 1 and p['struct_bytes'] == 376 and p['serial'] == serial + 1 and
                p['model_instance'] == transport['model_instance'] and p['owner_pid'] == transport['owner_pid'] and
                p['model_lifetime'] > 0 and (lifetime is None or p['model_lifetime'] == lifetime) and
                p['opcode'] == op and p['operation_status'] == 0 and
                (op in (18, 19) or op == 66 and retained is not None or p['config_generation'] == config),
                'actual frame instance/lifetime/configuration/operation differs')
        before, after = p['before'], p['after']
        require(counts is None or before == counts, 'actual per-job counter history differs')
        delta = {key: after[key] - before[key] for key in before}
        require(all(value >= 0 for value in delta.values()), 'actual model counters regressed')
        output = transfer_output(run, tx)
        kind = p['consumer_kind']
        if op in (17, 18, 19) or op == 66 and retained is not None:
            incoming = payload_read(run, tx['request_payload'])
            retained = retained_frame_proof(op, incoming, output, p, delta, retained,
                                             generation, config, tx['token'], transport['model_instance'])
            serial, lifetime, counts = p['serial'], p['model_lifetime'], after
            if op == 17:
                generation = p['frame_generation']
            if op == 66:
                require(state_counts == {k: after[k] for k in state_counts} and state_generation == generation,
                        'retained CANCEL State128 differs from actual retirement')
            jobs.append({'first': tx['first'], 'opcode': op, 'proof': p,
                         'retained_frame_operation': True, 'encoded_result_sha256': tx['sha256']})
            continue
        result_data = b'' if kind in (0, 4) and op not in (12, 13, 14) else output
        require(p['result_bytes'] == len(result_data) and p['result_fnv1a64'] == fnv(result_data) and p['result_token'] == tx['token'],
                'actual coded result is not this frame job output')
        require(kind == {1: 0, 5: 4, 6: 4, 7: 4, 8: 4, 9: 5, 10: 6, 12: 4, 13: 4, 14: 4, 16: 1, 33: 2, 34: 3}.get(op), 'actual frame consumer kind differs')
        if kind != 3 and (kind != 4 or vdf['enabled']):
            require(0 < p['width'] <= 8192 and 0 < p['height'] <= 8192 and p['stride'] >= p['width'] * 3 and
                    p['active_bytes'] == p['width'] * p['height'] * 3 and p['lease_generation'] > 0 and
                    p['frame_generation'] == generation + 1 and p['render_observed'] == p['retired'] == 1 and
                    p['render_status'] == p['retire_status'] == 0 and p['source_state'] == 3 and p['final_state'] == 1 and
                    delta['rendered'] == delta['retired'] == 1, 'actual rendered frame geometry/lifetime differs')
        else:
            require(not p['render_observed'] and not p['encoder_consumed'] and not p['retired'] and
                    delta['rendered'] == delta['consumed'] == delta['retired'] == 0 and
                    p['frame_generation'] == generation, 'drain/disabled path fabricated a new consumed frame')
        if kind in (4, 5, 6):
            noncodec_proof(tx, vdf, transport, output)
        elif kind == 0:
            require(not sensor_initialized and not p['consumer_entered'] and not p['consumer_returned'] and
                    not p['encoder_consumed'] and delta['consumed'] == delta['jpeg_encoded'] == delta['video_encoded'] == 0,
                    'INIT probe was promoted to encoder consumption')
            sensor_initialized = True
        else:
            require(p['consumer_entered'] == p['consumer_returned'] == 1 and p['consumer_status'] == 0,
                    'actual encoder call did not return successfully')
            if kind != 3:
                require(p['encoder_consumed'] == delta['consumed'] == 1 and p['consumer_before_state'] ==
                        p['consumer_after_state'] == 4 and p['source_fnv1a64'] ==
                        p['consumer_before_fnv1a64'] == p['consumer_after_fnv1a64'],
                        'actual rendered RGB differs from actual encoder-consumed same frame')
            if kind == 1:
                parts = jpeg_parts(output)
                encoded = parts['scan']
                require(parts['geometry'] == (p['width'], p['height']) and
                        delta['jpeg_encoded'] == 1 and delta['video_encoded'] == 0,
                        'actual JPEG coding geometry/counter differs')
            else:
                packets = camera_packets(output) if output else []
                encoded = b''.join(packet['packet'] for packet in packets)
                require(delta['jpeg_encoded'] == 0 and delta['video_encoded'] == sum(bool(packet['packet']) for packet in packets) and
                        all(packet['generation'] == p['packet_generation'] and
                            (not packet['packet'] or packet['geometry'] == (video_geometry if kind == 3 else (p['width'], p['height'])))
                            for packet in packets),
                        'actual H264 packet generation/counter differs')
                if kind == 3:
                    require(all(not packet['packet'] or any(job['opcode'] == 33 and
                            job['proof']['packet_generation'] == packet['generation'] for job in jobs) for packet in packets),
                            'actual drained packet lacks a prior same-generation encoder consumption')
                require(op != 34 or packets and packets[-1]['eos'], 'actual encoder drain/EOS missing')
                if op == 33:
                    incoming = payload_read(run, tx['request_payload'])
                    require(incoming in (b'', b'\x01\x00\x00\x00'),
                            'actual video frame force-IDR flags differ')
                    if incoming:
                        require(len(packets) == 1 and packets[0]['key'] == 1 and
                                any(nal[0] & 31 == 5 for nal in packets[0]['nals']),
                                'forced video frame lacks actual IDR NAL')
            require(p['encoded_bytes'] == len(encoded) and p['encoded_fnv1a64'] == fnv(encoded),
                    'actual encoder-coded bytes differ from reconstructed result')
        serial, lifetime, generation, counts = p['serial'], p['model_lifetime'], p['frame_generation'], after
        result_key = 'configuration_result_sha256' if kind in (4, 5, 6) else 'encoded_result_sha256'
        jobs.append({'first': tx['first'], 'opcode': op, 'proof': p, result_key: tx['sha256']})
        if op == 1:
            require(state_counts == {k: after[k] for k in state_counts} and state_generation == generation,
                    'actual INIT State128/probe receipt differs')
    needed(retained is None, 'model_frame: retained optical frame has not been retired')
    needed(sensor_initialized, 'model_frame: actual INIT sensor probe')
    needed(not require_media or all(any(job['opcode'] == op for job in jobs) for op in (16, 33, 34)),
           'model_frame: actual INIT, JPEG, H264 and drain jobs')
    return {'verified': True, 'same_frame_RGB_consumer_verified': True, 'model_lifetime': lifetime,
            'jobs': jobs, 'last_counts': counts, 'last_frame_generation': generation}


def stored_bytes(storage, item):
    require(item.get('writeback_verified') is True and item.get('independent_decoded') is True and
            storage.get('writeback_verified') is True and storage.get('independent_decoded') is True,
            'original Fsys completion/readback and both independent decoders required')
    host = writeback.directory(storage['exports']['host_directory'])
    raw = read(host, item['path'], writeback.MAX_SOURCE)
    require(len(raw) == item['bytes'] and sha(raw) == item['sha256'] and f'{fnv(raw):016x}' == item['fnv1a64'],
            'decoded SD product changed before compressed-data join')
    return raw


def check_retained_jpeg_input(run, job, tx, transport, body, selector):
    binding = job['original-input-binding']
    descriptor = job['original-input-descriptor']
    released = job['original-input-release']
    bf, df, rf = binding['fields'], descriptor['fields'], released['fields']
    token = number(bf['frame_token'])
    incoming = payload_read(run, tx['request_payload'])
    require(len(incoming) == 32 and struct.unpack_from('<QII', incoming) == (token, selector, 0),
            'retained native JPEG request token/selector differs')
    sources = [t for t in transport['transfers'] if t['opcode'] == 17 and t['first'] < tx['first'] and
               len(transfer_output(run, t)) >= 96 and struct.unpack_from('<Q', transfer_output(run, t), 8)[0] == token]
    require(len(sources) == 1, 'retained native input lacks unique prior actual CMOS capture')
    source = sources[0]
    frame = transfer_output(run, source)
    original = payload_read(run, source['request_payload'])
    origin = source['origin']
    require(len(original) == 16 and original[:4] == b'\x05\x00\x38\x40' and
            original[8] in (2, 10, 12, 8, 9, 3) and original[9:12] == bytes(3) and
            origin['source'] == 0x80020002 and origin['destination'] == 0x90040193 and
            origin['command'] == 0x4038 and origin['bytes'] == 16 and origin['fnv1a64'] == fnv(original) and
            frame[80:84] == original[4:8] and frame[84] == original[8] and
            struct.unpack_from('<Q', frame, 88)[0] == fnv(original), 'retained input original4038 correlation differs')
    model, lifetime, config, generation = struct.unpack_from('<4Q', frame, 16)
    width, height, stride, pixel_format = struct.unpack_from('<4I', frame, 48)
    size, digest = struct.unpack_from('<2Q', frame, 64)
    require(model == transport['model_instance'] and lifetime == number(bf['frame_lifetime']) and
            config == number(bf['input_cfg']) and generation == number(bf['input_frame']) and
            size == len(frame) - 96 == width * height * 3 == number(bf['source_bytes']) and
            pixel_format == 1 and stride == width * 3 and fnv(frame[96:]) == digest == int(bf['source_fnv'], 16),
            'retained native input changed source RGB or captured identity')
    needed(type(tx.get('frame')) is dict, 'retained native JPEG actual frame proof')
    proof = tx['frame']['proof']
    require(proof['consumer_kind'] == 8 and proof['model_lifetime'] == lifetime and
            proof['config_generation'] == config and proof['frame_generation'] == generation and
            proof['source_fnv1a64'] == proof['consumer_before_fnv1a64'] == proof['consumer_after_fnv1a64'] == digest and
            proof['render_observed'] == proof['retired'] == 0 and proof['encoder_consumed'] == 1,
            'native JPEG rerendered instead of consuming retained source')
    image = raw_hex(df, 'image72', 72)
    metadata_unit, pixel_unit = number(bf['metadata_unit']), number(bf['pixel_unit'])
    require(metadata_unit and pixel_unit and metadata_unit != pixel_unit and
            struct.unpack_from('<3I', body, 0x18) == (0, metadata_unit, 0) and
            struct.unpack_from('<2I', image) == (0, pixel_unit) and image[8:28] == bytes(20) and
            image[0x1c] == 1 and image[0x1d] == 0 and image[0x1f:0x26] == bytes([0, 0, 8, 1, 1, 2, 0]) and
            struct.unpack_from('<2H', image, 0x2e) == (width, height) and
            image[0x32:0x36] == bytes(4) and struct.unpack_from('<2H', image, 0x36) == (width, height) and
            image[0x3a:0x3e] == bytes(4) and struct.unpack_from('<2H', image, 0x3e) == (width, height) and
            struct.unpack_from('<H', image, 0x42)[0] == 0,
            'original typed metadata/pixel descriptor differs from source allocation')
    require(number(df['metadata_address']) and number(df['metadata_bytes']) == 1024 and
            number(df['pixel_address']) and number(df['pixel_bytes']) == size and df['input_readonly'] == '1' and
            re.fullmatch('[0-9a-f]{16}', df['metadata_fnv']) and
            all(number(bf[key]) > 0 and number(rf[key]) == number(bf[key]) for key in ('metadata_token', 'pixel_token')) and
            number(rf['frame_token']) == token and rf['input_release_rc'] == '0' and
            rf['actual_native_terminal'] == rf['input_refs_released'] == '1' and
            tx['line'] < binding['line'] < descriptor['line'] < job['output-readback']['line'] and
            job['original-maincomp-config']['line'] < released['line'] < job['original-rescmd-done']['line'],
            'native input was released before actual MainComp DONE or changed its held ranges')
    return dict(model_instance=model, model_lifetime=lifetime, frame_token=token,
                config_generation=config, frame_generation=generation, source_fnv1a64=f'{digest:016x}',
                source_geometry=(width, height), source_capture_first=source['first'])


def check_jpeg(rows, transport, storage, run=None):
    jobs = {}
    for row in rows:
        if row['tag'] != 'FUNCTIONAL_JPEG_CODEC':
            continue
        f = row['fields']
        require(f.get('rc') == '0' and f.get('physical_asic_compatible') == '0' and f.get('capture_verified') == '0',
                'JPEG adapter failure or scope promotion')
        if f.get('operation') in ('enable', 'shutdown'):
            continue
        needed('sequence' in f, 'FUNCTIONAL_JPEG_CODEC: sequence')
        seq = number(f['sequence'])
        job = jobs.setdefault(seq, {})
        require(seq and f['operation'] not in job, 'JPEG duplicate/zero job event')
        job[f['operation']] = row
    needed(jobs, 'FUNCTIONAL_JPEG_CODEC operation=original-request/output-readback/original-rescmd-done')
    results = []
    for seq, job in jobs.items():
        tags = ('original-request', 'original-request-lease', 'output-readback', 'queued-ack', 'queued-done',
                'original-received-ack', 'original-received-done', 'original-freed-ack', 'original-freed-done',
                'original-rescmd-ack', 'original-rescmd-done')
        needed(all(tag in job for tag in tags), 'FUNCTIONAL_JPEG_CODEC sequence=' + str(seq) + ': ' + ','.join(tag for tag in tags if tag not in job))
        request, output, ack, done = (job[tag] for tag in ('original-request', 'output-readback', 'original-rescmd-ack', 'original-rescmd-done'))
        f = request['fields']
        identity = ('pid', 'producer_tid', 'sequence', 'original_base', 'exec_entry', 'caller',
                    'object', 'manager', 'control', 'context', 'key', 'source', 'destination',
                    'command', 'native_bytes', 'trigger_fnv', 'response_tag', 'kind', 'selector', 'stream_mode')
        needed(all(key in f for key in identity) and 'comp_object' in f, 'JPEG complete common kind/selector identity')
        kind, selector = f['kind'], number(f['selector'])
        require(kind in ('without-pin', 'main') and selector in (0, 1, 2) and
                (kind == 'main' or selector == 0) and f['comp_object'] == '(nil)',
                'JPEG source kind/selector/object schema differs')
        main = kind == 'main'
        if main:
            needed(all(tag in job for tag in ('original-maincomp-exec', 'original-maincomp-config')),
                   'JPEG Main requires actual independent MainComp Exec and original length readback')
        require(number(f['pid']) == transport['pid'] and number(f['native_bytes']) == 104 and
                number(f['destination']) == 0x82830752 and number(f['source']) >> 28 == 8,
                'JPEG original PID/SID/request size differs')
        base = number(f['original_base'])
        require(base and number(f['exec_entry']) == base + (0x1226c4 if main else 0x11b654) and
                number(f['caller']) in (base + 0x13b6ec, base + 0x13b7e0) and
                number(f['producer_tid']) > 0 and number(f['response_tag']) == 0,
                'JPEG original SDK caller/method provenance differs')
        for event in job.values():
            require(all(key in event['fields'] and event['fields'][key] == f[key] for key in identity) and
                    'comp_object' in event['fields'], 'JPEG original request identity drift')
        of = output['fields']
        require(number(of['model_instance']) == transport['model_instance'] and number(of['bytes']) > 0 and
                request['line'] < output['line'] < ack['line'] < done['line'] and
                all(event['fields'].get('output_fnv') == of['output_fnv'] and event['fields'].get('bytes') == of['bytes'] and
                    event['fields'].get('model_instance') == of['model_instance']
                    for tag, event in job.items() if tag not in ('original-request', 'original-request-lease')),
                'JPEG native consumption/readback order/hash differs')
        retained_input = any(tag in job for tag in ('original-input-binding', 'original-input-descriptor', 'original-input-release'))
        if retained_input:
            require(main and all(tag in job for tag in ('original-input-binding', 'original-input-descriptor', 'original-input-release')),
                    'retained JPEG lacks complete native input lifecycle receipts')
        transfers = [tx for tx in transport['transfers'] if tx['opcode'] == (18 if retained_input else 16) and
                     tx['origin']['source'] == number(f['source']) and tx['origin']['destination'] == number(f['destination']) and
                     tx['origin']['command'] == number(f['command']) and
                     tx['origin']['fnv1a64'] == int(f['trigger_fnv'], 16) and
                     tx['origin']['producer_tid'] == number(of['tid'])]
        require(len(transfers) == 1, 'JPEG lacks unique original-request to actual C STILL transfer')
        wire = raw_hex(f, 'request_hex', 104)
        body = wire[24:]
        require(fnv(wire) == int(f['trigger_fnv'], 16) and struct.unpack_from('<I', wire)[0] == number(f['source']) and
                struct.unpack_from('<I', wire, 4)[0] == 0xa0a0a0a0 and struct.unpack_from('<2H', wire, 8) == (1, 104) and
                struct.unpack_from('<2I', wire, 12) == (24, 104) and struct.unpack_from('<H', body, 4)[0] == 80 and
                struct.unpack_from('<H', body, 0)[0] << 16 | struct.unpack_from('<H', body, 2)[0] == number(f['command']) and
                body[0x14:0x18] == bytes(4) and body[0x4b] == number(f['stream_mode']) and
                struct.unpack_from('<H', body, 6)[0] == struct.unpack_from('<H', body, 10)[0] == 0 and
                struct.unpack_from('<H', body, 8)[0] == 7 and
                struct.unpack_from('<4H', body, 12) == (struct.unpack_from('<H', body)[0], 0x8310,
                                                       struct.unpack_from('<H', body)[0], 0x8311) and
                body[0x24:0x28] == body[0x30:0x34] == bytes(4) and not body[0x48] and
                body[0x4c:0x50] == bytes(4),
                'actual original JPEG SDK packet differs from native origin')
        target = struct.unpack_from('<2H', body, 0x40)
        primary = struct.unpack_from('<2H', body, 0x44)
        require(all(v <= 8192 for v in target + primary), 'JPEG source geometry exceeds codec bounds')
        if main:
            require(number(f['key']) == 0 and all(target + primary) and body[0x2c:0x30] == bytes(4) and
                    body[0x4b] == (1 if selector == 1 else 0) and
                    (selector == 0 and target == primary and body[0x49] in (0, 1, 2, 6) or
                     selector == 1 and target == (160, 120) and body[0x49] == 4 or
                     selector == 2 and body[0x49] == 3), 'JPEG Main source selector/geometry/quality/SOI differs')
        else:
            require(body[0x4b] in (0, 1) and body[0x49] == (4 if body[0x4b] else 3),
                    'JPEG Without_Pin source quality/SOI differs')
        lease = job['original-request-lease']['fields']
        needed(all(key in lease for key in ('sds_type', 'sds_handle', 'sds_offset', 'stream_position', 'lease_address',
                                            'lease_capacity', 'lease_offset', 'lease_generation', 'lease_token')),
               'FUNCTIONAL_JPEG_CODEC: actual current SDS lease identity')
        u32 = lambda offset: struct.unpack_from('<I', body, offset)[0]
        require(number(lease['sds_type']) == u32(0x24) == 0 and number(lease['sds_handle']) == u32(0x28) > 0 and
                number(lease['sds_offset']) == u32(0x2c) and number(lease['stream_position']) == u32(0x38) and
                number(lease['lease_offset']) == u32(0x2c) + u32(0x38) and
                number(lease['lease_capacity']) == u32(0x3c) > 0 and
                u32(0x34) == u32(0x38) + u32(0x3c) and number(lease['lease_address']) > 0 and
                number(lease['lease_token']) > 0 and number(lease['lease_generation']) > 0 and
                request['line'] < job['original-request-lease']['line'] < output['line'],
                'actual original JPEG request/current leased destination range differs')
        require(all(number(of[key]) == number(lease[key]) for key in
                    ('lease_address', 'lease_capacity', 'lease_offset', 'lease_generation', 'lease_token')),
                'JPEG output readback switched SDS lease generation/range')
        tx = transfers[0]
        require(request['line'] < tx['line'] < output['line'], 'JPEG encoding transfer is outside original job lifetime')
        encoded = transfer_output(run, tx)
        parts = jpeg_parts(encoded)
        skip = 0 if body[0x4b] else 2
        require(number(of['model_token']) == tx['token'] and number(of['model_bytes']) == len(encoded) and
                int(of['model_fnv'], 16) == fnv(encoded) and number(of['model_offset']) == skip and
                number(of['bytes']) == number(of['readback_bytes']) == len(encoded) - skip <= number(lease['lease_capacity']) and
                int(of['readback_fnv'], 16) == int(of['output_fnv'], 16) == fnv(encoded[skip:]),
                'actual encoder result differs from original leased JPEG readback bytes')
        still = payload_read(run, tx['request_payload'])
        input_identity = None
        if retained_input:
            input_identity = check_retained_jpeg_input(run, job, tx, transport, body, selector)
            still = still[16:]
        if 'original-output-retained' in job:
            copied = job['original-output-retained']
            cf = copied['fields']
            needed(all(key in cf for key in ('frame_token', 'copied_bytes', 'copied_fnv',
                    'original_output_bytes', 'original_output_fnv', 'model_token', 'lease_token', 'actual_native_terminal')),
                   'retained native JPEG output copy missing content/lease fields')
            require(main and retained_input and selector in (0, 1) and
                    job['original-maincomp-config']['line'] < copied['line'] < job['original-input-release']['line'] < done['line'] and
                    number(cf['frame_token']) == number(job['original-input-binding']['fields']['frame_token']) and
                    number(cf['copied_bytes']) == len(encoded) and int(cf['copied_fnv'], 16) == fnv(encoded) and
                    number(cf['original_output_bytes']) == len(encoded) - skip and
                    int(cf['original_output_fnv'], 16) == fnv(encoded[skip:]) and
                    number(cf['model_token']) == tx['token'] and number(cf['lease_token']) == number(lease['lease_token']) and
                    cf.get('actual_native_terminal') == '1',
                    'retained native JPEG output copy lost actual bytes/lease or preceded MainComp DONE')
        require(len(still) == 16 and struct.unpack_from('<4I', still)[:3] == (1, *parts['geometry']) and
                all(a == 0 or a == b for a, b in zip(struct.unpack_from('<2H', body, 0x40), parts['geometry'])),
                'actual original JPEG dimensions differ from encoder job')
        needed(type(tx.get('frame')) is dict, 'JPEG actual same-frame encoder proof')
        proof = tx['frame']['proof']
        require(proof['consumer_kind'] == (8 if retained_input else 1) and proof['model_instance'] == transport['model_instance'] and
                all(proof[key] > 0 for key in ('model_lifetime', 'config_generation', 'frame_generation')),
                'JPEG transfer has wrong actual consumer/instance/generation')
        receivers = []
        for completion, native in ((False, ack), (True, done)):
            recv = job['original-received-done' if completion else 'original-received-ack']
            freed = job['original-freed-done' if completion else 'original-freed-ack']
            rf, nf, ff = recv['fields'], native['fields'], freed['fields']
            response = raw_hex(rf, 'response_hex', 16)
            packet = raw_hex(rf, 'reply_hex', 40)
            require(packet == raw_hex(ff, 'reply_hex', 40) and packet[24:] == response and
                    struct.unpack_from('<I', packet, 4)[0] == 0xa0a0a0a0 and
                    struct.unpack_from('<2H2I', packet, 8) == (1, 40, 24, 40) and
                    ff.get('free_rc') == '0' and
                    all(ff.get(key) == rf.get(key) and key in ff and key in rf for key in
                        ('receiver_pid', 'receiver_tid', 'reply_address', 'response_hex', 'response_source',
                         'response_destination', 'lease_generation', 'lease_token')),
                    'actual original JPEG free result/snapshot/receiver/ownership differs')
            expected = struct.pack('<4H2I', *struct.unpack_from('<2H', body, 0x10 if completion else 0x0c),
                                   16, 0, 0, len(encoded) - skip if completion else seq)
            require(response == expected == raw_hex(nf, 'response_hex', 16) and
                    output['line'] < recv['line'] < freed['line'] < native['line'] and
                    number(rf['receiver_pid']) == number(nf['receiver_pid']) == transport['pid'] and
                    number(rf['receiver_tid']) == number(nf['receiver_tid']) == number(nf['tid']) > 0 and
                    number(rf['reply_address']) > 0 and
                    all(number(v['response_source']) == number(f['destination']) and
                        number(v['response_destination']) == number(f['source']) for v in (rf, nf)) and
                    number(nf['response_mid']) == struct.unpack_from('<H', body, 0x12 if completion else 0x0e)[0] and
                    number(nf['callback_caller']) == base + 0x13b788 and
                    number(nf['res_entry']) == base + ((0x122b44 if completion else 0x120e64) if main else 0x11a9dc) and
                    number(nf['original_result']) == number(nf['expected_result']) == (0 if main or completion else 0x200) and
                    number(nf['response_address']) > 0 and nf['release_rc'] == '0' and
                    nf.get('terminal') == nf.get('lease_released') == str(int(completion)) and
                    all(number(v[key]) == number(lease[key]) for v in (rf, nf) for key in ('lease_generation', 'lease_token')),
                    'actual original JPEG receive/free/ResCmd ownership/body/return/lease differs')
            receivers.append({'pid': number(rf['receiver_pid']), 'tid': number(rf['receiver_tid']),
                              'reply_address': number(rf['reply_address']), 'free_rc': number(ff['free_rc']),
                              'original_result': number(nf['original_result'])})
        comp = None
        if main:
            ce, cc = job['original-maincomp-exec'], job['original-maincomp-config']
            ef, cf = ce['fields'], cc['fields']
            comp = number(ef['comp_object'])
            require(comp > 0 and comp != number(f['object']) and
                    number(ef['comp_exec_entry']) == base + 0x122dfc and number(ef['comp_caller']) == base + 0x13b7e0 and
                    number(ef['original_result']) == 0 and number(ef['tid']) == number(ack['fields']['receiver_tid']) and
                    raw_hex(ef, 'previous_ack_hex', 16) == raw_hex(ack['fields'], 'response_hex', 16) and
                    number(ef['previous_ack_address']) == number(ack['fields']['response_address']) > 0 and
                    number(ef['native_config']) == number(cf['native_config']) > 0 and
                    number(ef['config_length_offset']) == number(cf['config_length_offset']) == 0x5c + 12 * selector and
                    number(cf['actual_length']) == number(cf['expected_length']) == len(encoded) - skip and
                    number(cf['original_result']) == 0 and number(cf['tid']) == number(done['fields']['receiver_tid']) and
                    ack['line'] < ce['line'] < job['original-received-done']['line'] <
                    job['original-freed-done']['line'] < cc['line'] < done['line'] and
                    receivers[0]['pid'] == receivers[1]['pid'] and receivers[0]['tid'] == receivers[1]['tid'],
                    'JPEG independent MainComp Exec/ACK argument/original config readback differs')
            for tag, event in job.items():
                if tag in ('original-maincomp-exec', 'original-maincomp-config', 'original-received-done',
                           'original-freed-done', 'original-rescmd-done', 'original-input-release',
                           'original-output-retained'):
                    require(number(event['fields']['comp_object']) == comp, 'JPEG MainComp object drift')
                else:
                    require(event['fields']['comp_object'] == '(nil)', 'JPEG premature MainComp association')
        else:
            require(all(event['fields']['comp_object'] == '(nil)' for event in job.values()) and
                    not any(tag.startswith('original-maincomp-') for tag in job), 'Without_Pin claimed MainComp')
        needed(not main or selector != 2, 'JPEG Screen selector2 original MPF/layout mapping is unverified')
        matching = []
        for item in storage.get('items', []):
            if item.get('decode', {}).get('format') != 'JPEG' or not item.get('writeback_verified') or not item.get('independent_decoded'):
                continue
            exported = stored_bytes(storage, item)
            if main and selector == 1:
                try:
                    thumb = exif_thumbnail(exported)
                except MissingEvidence:
                    continue
                if thumb['bytes'] == encoded:
                    final = dict(thumb['parts'], scan_offset=thumb['offset'] + thumb['parts']['scan_offset'])
                    matching.append((item, final))
            else:
                final = jpeg_parts(exported)
                if final['scan'] == parts['scan'] and final['coding'] == parts['coding'] and final['geometry'] == parts['geometry']:
                    matching.append((item, final))
        needed(matching, 'JPEG actual leased scan/coding tables absent from original Fsys/SD JPEG')
        require(len(matching) == 1, 'ambiguous original JPEG compressed-content product')
        item, final = matching[0]
        needed(item.get('areas'), 'JPEG original Fsys source contributions missing')
        results.append({'sequence': seq, 'kind': kind, 'selector': selector,
                        'join_identity': {key: f[key] for key in ('pid', 'source', 'destination', 'manager', 'control', 'context')},
                        'primary_geometry': primary, 'native_config': job['original-maincomp-exec']['fields']['native_config'] if main else None,
                        'cross_selector_same_sensor_frame_verified': False,
                        'retained_input_identity': input_identity,
                        'original_method_and_ResCmd_observed': True, 'actual_reply_free_verified': True, 'raw_request_observed': True,
                        'output_readback_bytes': number(of['bytes']), 'output_fnv1a64': of['output_fnv'],
                        'lease': {key: lease[key] for key in lease if key.startswith('lease_')},
                        'bridge': tx, 'receivers': receivers, 'path': item['path'],
                        'scan': {'encoder_offset': parts['scan_offset'], 'file_offset': final['scan_offset'],
                                 'bytes': len(parts['scan']), 'sha256': sha(parts['scan'])},
                        'metadata_transformation': ('EXIF IFD1 complete JPEG exactly equals model and leased Thumb' if main and selector == 1 else
                                                    'APP/COM may differ; ordered coding markers and complete SOS/entropy/EOI equal'),
                        'original_Fsys_contributions': item['areas'], 'storage_join_verified': True, 'capture_verified': True})
    require(len({job['bridge']['first'] for job in results}) == len(results), 'JPEG jobs reused one actual encoder transfer')
    primary_jobs = [job for job in results if job['kind'] == 'without-pin' or job['selector'] == 0]
    require(len({job['path'] for job in primary_jobs}) == len(primary_jobs) and {job['path'] for job in primary_jobs} ==
            {item['path'] for item in storage.get('items', []) if item.get('decode', {}).get('format') == 'JPEG'},
            'original JPEG primary jobs/products are not one-to-one')
    thumbs = [job for job in results if job['kind'] == 'main' and job['selector'] == 1]
    require(len({job['path'] for job in thumbs}) == len(thumbs), 'multiple Thumb jobs reused one native JPEG')
    for thumb in thumbs:
        partners = [job for job in primary_jobs if job['kind'] == 'main' and job['path'] == thumb['path']]
        require(len(partners) == 1, 'EXIF Thumb lacks same-file original Main0 job')
        primary_job = partners[0]
        require(primary_job['join_identity'] == thumb['join_identity'] and
                primary_job['primary_geometry'] == thumb['primary_geometry'] and
                primary_job['native_config'] == thumb['native_config'] and
                all(primary_job['bridge']['frame']['proof'][key] == thumb['bridge']['frame']['proof'][key]
                    for key in ('model_instance', 'model_lifetime', 'config_generation')),
                'Main/Thumb original file/config/model/reference join differs')
        thumb['primary_sequence'] = primary_job['sequence']
    return {'verified': True, 'jobs': results, 'raw_request_observed': True, 'storage_join_verified': True,
            'actual_reply_free_verified': True, 'cross_selector_same_sensor_frame_verified': False,
            'screen_MPF_layout_verified': False, 'capture_verified': True}


def check_video(rows, transport, storage, run=None):
    for row in rows:
        require(row['tag'] not in ('FUNCTIONAL_MPR_RECEIPT_ERROR', 'FUNCTIONAL_MPR_EVENT_FREE_FAILED',
                                  'FUNCTIONAL_MPR_RELEASE_FAILED', 'FUNCTIONAL_MPR_UNSUPPORTED'),
                'actual video failure/unsupported receipt retained: ' + row['tag'])
    packets = [row for row in rows if row['tag'] == 'FUNCTIONAL_MPR_PACKET']
    operations = [row for row in rows if row['tag'] == 'FUNCTIONAL_MPR_OPERATION']
    needed(packets and operations, 'FUNCTIONAL_MPR_PACKET and FUNCTIONAL_MPR_OPERATION')
    opened = [row for row in rows if row['tag'] == 'FUNCTIONAL_MPR_OPEN']
    require(len(opened) == 1, 'first bounded video proof requires exactly one original open epoch')
    previous_generation, previous_pts, es_used, epoch = 0, -3000, 0, None
    for row in packets:
        f = row['fields']
        current_epoch = number(f['epoch'])
        require(current_epoch > 0 and (epoch is None or epoch == current_epoch) and
                number(f['instance']) == transport['model_instance'] and number(f['frame_generation']) > previous_generation and
                number(f['native_hz']) == 90000 and number(f['native_pts']) == previous_pts + 3000 and
                number(f['packet_bytes']) > 0 and number(f['avcc_bytes']) > 0 and
                number(f['es_capacity']) >= number(f['es_used']) > es_used,
                'video actual packet generation/instance/timebase/ES extent differs')
        number(f['avcc_fnv'])
        epoch, previous_generation, previous_pts, es_used = current_epoch, number(f['frame_generation']), number(f['native_pts']), number(f['es_used'])
    require(len({row['fields']['native_start_fnv'] for row in packets}) == 1, 'mixed original video Start')
    by_command = {}
    for row in operations:
        f = row['fields']
        require(f.get('operation_error') == '0' and f.get('event_error') == '0', 'partial/failed original video operation')
        command = number(f['command'])
        require(command not in by_command, 'ambiguous repeated video operation')
        by_command[command] = row
    needed(set(by_command) in ({0, 1, 3, 4}, {0, 1, 2, 3, 4}), 'FUNCTIONAL_MPR_OPERATION: successful original Open/Start/Stop/Close commands 0,1,3,4')
    lifecycle = (0, 1, 2, 3, 4) if 2 in by_command else (0, 1, 3, 4)
    require([by_command[c]['line'] for c in lifecycle] == sorted(by_command[c]['line'] for c in lifecycle),
            'original video operation order differs')
    start_fnv = number(packets[0]['fields']['native_start_fnv'])
    require(start_fnv == number(by_command[1]['fields']['native_fnv']), 'packet has different original Start digest')
    for command, op in ((1, 32), (3, 34), (4, 66)):
        actual = [tx for tx in transport['transfers'] if tx['opcode'] == op and
                  tx['origin']['source'] == 0x80c70047 and tx['origin']['destination'] == 0x8055001f and
                  tx['origin']['command'] == command and tx['origin']['bytes'] == 48 and
                  tx['origin']['fnv1a64'] == number(by_command[command]['fields']['native_fnv'])]
        require(len(actual) == 1, 'original video command lacks actual broker C operation: ' + str(command))
    received = [row for row in rows if row['tag'] == 'FUNCTIONAL_MPR_EVENT_RECEIVED']
    freed = [row for row in rows if row['tag'] == 'FUNCTIONAL_MPR_EVENT_FREE']
    needed(received and freed, 'FUNCTIONAL_MPR_EVENT_RECEIVED/FUNCTIONAL_MPR_EVENT_FREE')
    require(len(received) == len(freed) == len(lifecycle), 'original video event receive/free count differs')
    seen, commands = set(), set()
    for recv in received:
        f = recv['fields']
        seq = number(f['seq'])
        matched = [row for row in freed if row['fields'].get('seq') == f['seq']]
        require(seq and seq not in seen and len(matched) == 1, 'duplicate/unmatched video event sequence')
        seen.add(seq)
        command = number(f['command'])
        require(command not in commands, 'duplicate original video command event')
        commands.add(command)
        free = matched[0]
        require(recv['line'] < free['line'] and all(f.get(key) == free['fields'].get(key) for key in
                ('command', 'wire_fnv', 'src', 'dst')) and f.get('received') == free['fields'].get('received') == '1' and
                f.get('rc') == free['fields'].get('rc') == '0' and number(f['src']) == 0x8055001f and
                number(f['dst']) == 0x80c70047 and number(f['command']) in by_command,
                'original event receive/free SID/body/lifecycle differs')
    require(commands == set(lifecycle), 'missing actual Open/Start/Stop/Close event consumption')
    requests = [row for row in rows if row['tag'] == 'FUNCTIONAL_MPR_REQUEST']
    needed(len(requests) == len(lifecycle), 'FUNCTIONAL_MPR_REQUEST: actual original Open/Start/Stop/Close raw bytes')
    request_jobs, last_request = {}, 0
    opened_fields = opened[0]['fields']
    memory_generation = number(opened_fields['memory_generation'])
    slots = number(opened_fields['pi_slots'])
    require(memory_generation > 0 and slots >= 5 and number(opened_fields['epoch']) == epoch and
            number(opened_fields['instance']) == transport['model_instance'], 'actual original video open memory/instance differs')
    for request in requests:
        f = request['fields']
        wire = raw_hex(f, 'wire_hex', 48)
        command, seq = number(f['command']), number(f['request_seq'])
        require(command in by_command and command not in request_jobs and seq == last_request + 1 and f.get('rc') == '0' and
                number(f['pid']) == transport['pid'] and number(f['producer_tid']) > 0 and
                number(f['src']) == 0x80c70047 and number(f['dst']) == 0x8055001f and
                number(f['native_bytes']) == 48 and number(f['native_fnv']) == fnv(wire) and
                struct.unpack_from('<H', wire, 2)[0] == command and struct.unpack_from('<I', wire, 0x24)[0] == 0x210 and
                number(f['epoch']) == epoch and number(f['memory_generation']) == memory_generation and
                number(f['instance']) in ((0, transport['model_instance']) if command == 0 else (transport['model_instance'],)),
                'actual original video request PID/TID/epoch/memory/raw bytes differ')
        operation = by_command[command]['fields']
        require(request['line'] < by_command[command]['line'] and
                all(number(operation[key]) == number(f[key]) for key in
                    ('request_seq', 'epoch', 'memory_generation', 'pid', 'producer_tid', 'native_fnv')) and
                number(operation['instance']) == transport['model_instance'], 'original video operation/request identity differs')
        request_jobs[command], last_request = request, seq
    force_requests = [row for row in rows if row['tag'] == 'FUNCTIONAL_MPR_FORCE_REQUEST']
    force_done = [row for row in rows if row['tag'] == 'FUNCTIONAL_MPR_FORCE_IDR']
    require(len(force_requests) == len(force_done) == int(2 in by_command),
            'native command2 opaque/waiter/completion receipts missing or extra')
    force_factor = None
    if force_requests:
        request, fr = request_jobs[2], force_requests[0]
        rf, f = request['fields'], fr['fields']
        original, opaque = raw_hex(rf, 'wire_hex', 48), raw_hex(f, 'opaque4', 4)
        force_factor = number(f['expected_factor'])
        require(force_factor in (1, 0x1004) and number(f['expected_result']) >= 4096 and
                request['line'] < fr['line'] < by_command[2]['line'] and
                number(f['request_seq']) == number(rf['request_seq']) and number(f['native_fnv']) == fnv(original) and
                struct.unpack_from('<I', original, 0x10)[0] == number(f['parameter_bytes']) == 4 and
                struct.unpack_from('<Q', original, 8)[0] == number(f['parameter_p']) and
                struct.unpack_from('<Q', original, 0x28)[0] == number(f['parameter_v']) and
                by_command[1]['line'] < request['line'] and
                all(number(f[k]) > 0 for k in ('parameter_generation', 'parameter_token', 'parameter_v')) and
                number(f['parameter_fnv']) == fnv(opaque) and number(f['opaque_word']) == int.from_bytes(opaque, 'little') and
                f.get('software_policy') == 'opaque4-force-this-frame-v1' and
                f.get('original_argument_semantics_verified') == f.get('capture_verified') == '0',
                'native command2 opaque parameter/pin/waiter source differs')
    for recv in received:
        f = recv['fields']
        free = next(row for row in freed if row['fields']['seq'] == f['seq'])
        ff = free['fields']
        command = number(f['command'])
        request = request_jobs[command]
        rf = request['fields']
        original = raw_hex(rf, 'wire_hex', 48)
        event_wire = bytearray(48)
        struct.pack_into('<H', event_wire, 2, (4 if force_factor == 1 else 5) if command == 2 else command * 2 + 1)
        event_wire[0x18], event_wire[0x1c] = original[0x18], original[0x1c]
        event_wire[0x1a:0x1c] = original[0x1a:0x1c]
        struct.pack_into('<I', event_wire, 0x24, 0x4e0)
        identity_keys = ('pid', 'receiver_pid', 'receiver_tid', 'producer_pid', 'producer_tid', 'instance', 'epoch',
                         'memory_generation', 'request_seq', 'native_fnv', 'reply_address', 'operation_error', 'wire_hex', 'request_hex')
        require(all(f.get(key) == ff.get(key) for key in identity_keys) and
                raw_hex(f, 'wire_hex', 48) == event_wire and raw_hex(f, 'request_hex', 48) == original and
                number(f['wire_fnv']) == fnv(event_wire) and number(f['native_fnv']) == fnv(original) and
                number(f['pid']) == number(f['receiver_pid']) == number(f['producer_pid']) == transport['pid'] and
                number(f['receiver_tid']) == number(f['observer_tid']) == number(ff['observer_tid']) > 0 and
                number(f['producer_tid']) == number(rf['producer_tid']) and number(f['request_seq']) == number(rf['request_seq']) and
                number(f['instance']) == transport['model_instance'] and number(f['epoch']) == epoch and
                number(f['memory_generation']) == memory_generation and number(f['reply_address']) > 0 and
                f['operation_error'] == '0' and request['line'] < recv['line'],
                'actual original event request/receiver/lease/raw body/free ownership differs')
    for command, op in ((0, 1), (1, 32), (3, 34), (4, 66)):
        f = request_jobs[command]['fields']
        actual = [tx for tx in transport['transfers'] if tx['opcode'] == op and
                  tx['origin']['source'] == number(f['src']) and tx['origin']['destination'] == number(f['dst']) and
                  tx['origin']['command'] == command and tx['origin']['bytes'] == 48 and
                  tx['origin']['fnv1a64'] == number(f['native_fnv'])]
        require(len(actual) == 1, 'actual original video request/broker operation is not one-to-one')
    video_transfers = [tx for tx in transport['transfers'] if tx['opcode'] in (33, 34)]
    needed(video_transfers, 'actual video encoder result transfer')
    config, actual_samples, actual_packets, sources = None, [], [], []
    forced_transfers = [tx for tx in video_transfers if tx['origin']['command'] == 2]
    require(len(forced_transfers) == int(2 in by_command), 'native command2 forced transfer count differs')
    for tx in video_transfers:
        command = tx['origin']['command']
        require(command in ((3,) if tx['opcode'] == 34 else (1, 2)) and command in request_jobs,
                'actual video frame lost native Start/command2/Stop origin')
        rf = request_jobs[command]['fields']
        require(tx['origin']['fnv1a64'] == number(rf['native_fnv']) and tx['origin']['command'] == command and
                tx['origin']['source'] == 0x80c70047 and tx['origin']['destination'] == 0x8055001f and
                tx['origin']['bytes'] == 48 and type(tx.get('frame')) is dict,
                'actual video frame lost native Start/Stop origin or frame proof')
        raw = transfer_output(run, tx)
        decoded_packets = camera_packets(raw)
        if command == 2:
            require(tx['opcode'] == 33 and payload_read(run, tx['request_payload']) == b'\x01\x00\x00\x00' and
                    len(decoded_packets) == 1 and decoded_packets[0]['packet'] and decoded_packets[0]['key'] == 1 and
                    any(nal[0] & 31 == 5 for nal in decoded_packets[0]['nals']) and
                    force_requests[0]['line'] < tx['line'] < force_done[0]['line'],
                    'native command2 lacks its own actual forced IDR NAL5 transfer')
        for packet in decoded_packets:
            if packet['packet']:
                if config is None:
                    config = packet['parameters']
                    sources.append((tx, packet, True, packet['config_offset'], packet['config'], config))
                require(packet['parameters'] == config and packet['pts'] == len(actual_samples) and
                        packet['geometry'] == (number(opened_fields['width']), number(opened_fields['height'])) and
                        packet['generation'] == tx['frame']['proof']['packet_generation'],
                        'actual video configuration/packet generation/order changed')
                sources.append((tx, packet, False, packet['packet_offset'], packet['packet'], packet['nals']))
                actual_samples.append(packet['nals'])
                actual_packets.append(packet)
    require(video_transfers[-1]['opcode'] == 34 and camera_packets(transfer_output(run, video_transfers[-1]))[-1]['eos'],
            'actual original Stop lacks actual drained encoder EOS')
    needed(len(actual_samples) >= 2, 'actual H264 video requires at least two encoded samples')
    es_rows = [row for row in rows if row['tag'] == 'FUNCTIONAL_MPR_ES']
    publishes = [row for row in rows if row['tag'] == 'FUNCTIONAL_MPR_PI_PUBLISH']
    returns = [row for row in rows if row['tag'] == 'FUNCTIONAL_MPR_PI_RETURN']
    needed(es_rows and publishes and returns, 'FUNCTIONAL_MPR_ES/PI_PUBLISH/PI_RETURN actual original consumer readback')
    require(len(es_rows) == len(sources) and len(publishes) == len(sources) + 1 and len(returns) == len(publishes),
            'actual ES/PI publication and original reader return coverage differs')
    require(len(packets) == len(actual_samples), 'actual native video packet records missing/extra')
    used, write_cursor, slot_generations, published = 0, 0, {}, {}
    for index, publication in enumerate(publishes, 1):
        f = publication['fields']
        slot = number(f['slot'])
        info = raw_hex(f, 'info_hex', 96)
        require(f.get('rc') == '0' and number(f['pid']) == transport['pid'] and number(f['observer_tid']) > 0 and
                number(f['epoch']) == epoch and number(f['instance']) == transport['model_instance'] and
                number(f['memory_generation']) == memory_generation and number(f['native_start_fnv']) == start_fnv and
                number(f['request_seq']) == number(request_jobs[1]['fields']['request_seq']) and
                number(f['ticket']) == index and slot == (write_cursor + 1) % slots and
                number(f['slot_generation']) == slot_generations.get(slot, 0) + 1 and number(f['cycle']) == index // slots and
                number(f['write_before']) == write_cursor and number(f['write_after']) == number(f['observed_write']) == slot and
                0 <= number(f['read_before']) < slots and 0 <= number(f['read_after']) < slots and
                number(f['outstanding_after']) == number(f['outstanding_before']) + 1 < slots and
                number(f['counter_after']) >= number(f['counter_before']) and
                number(f['info_address']) == number(opened_fields['info_address']) + slot * 96 and
                number(f['read_address']) == number(opened_fields['read_address']) and
                all(number(f[key]) > 0 for key in ('pi_token', 'es_token', 'read_token', 'control_token')),
                'actual VideoInfo96 PI publication geometry/generation/cursor/lease differs')
        expected_info = bytearray(96)
        if index <= len(sources):
            es = es_rows[index - 1]
            ef = es['fields']
            tx, packet, is_config, offset, original, nals = sources[index - 1]
            converted = avcc_bytes(nals)
            require(tx['line'] < es['line'] < publication['line'] and ef.get('rc') == '0' and
                    number(ef['pid']) == transport['pid'] and number(ef['epoch']) == epoch and
                    number(ef['instance']) == transport['model_instance'] and number(ef['memory_generation']) == memory_generation and
                    number(ef['native_start_fnv']) == start_fnv and number(ef['request_seq']) == number(f['request_seq']) and
                    number(ef['call_request_seq']) == number(request_jobs[tx['origin']['command']]['fields']['request_seq']) and
                    number(ef['call_native_fnv']) == tx['origin']['fnv1a64'] and
                    number(ef['model_token']) == tx['token'] and number(ef['result_bytes']) == tx['bytes'] and
                    number(ef['source_offset']) == offset and number(ef['source_bytes']) == len(original) and
                    number(ef['source_fnv']) == fnv(original) and number(ef['offset']) == used and
                    number(ef['bytes']) == len(converted) and number(ef['avcc_fnv']) == fnv(converted) and
                    number(ef['nal_count']) == len(nals) and number(ef['nal_payload_fnv']) == fnv(b''.join(nals)) and
                    number(ef['address']) == number(opened_fields['es_address']) + used and
                    number(ef['es_token']) == number(f['es_token']) and number(ef['group']) == number(f['group']) and
                    all(number(ef[k]) == number(f[k]) for k in ('call_request_seq', 'call_native_fnv', 'model_token', 'result_bytes')) and
                    number(ef['frame_generation']) == number(f['frame_generation']) == packet['generation'],
                    'actual Annex-B/AVCC canonical bytes or ES readback extent differs')
            kind = 4 if is_config else 0 if packet['key'] else 1
            require(number(ef['info_type']) == kind and number(ef['packet_sequence']) == packet['pts'] and
                    number(f['es_offset']) == used and number(f['es_bytes']) == len(converted) and
                    number(f['es_fnv']) == fnv(converted), 'actual VideoInfo ES source extent differs')
            expected_info[0] = kind
            struct.pack_into('<Q', expected_info, 8, number(ef['address']) - number(opened_fields['es_correction']))
            struct.pack_into('<I', expected_info, 0x10, len(converted))
            if is_config:
                expected_info[1] = 6
                struct.pack_into('<H', expected_info, 0x2c, len(nals[0]) + 4)
                expected_info[0x2e] = 1
                struct.pack_into('<H', expected_info, 0x30, len(nals[1]) + 4)
                expected_info[0x32] = 1
            else:
                struct.pack_into('<2Q', expected_info, 0x18, packet['pts'] * 3000, packet['pts'] * 3000)
                record = packets[packet['pts']]['fields']
                require(number(record['ticket']) == index and number(record['slot']) == slot and
                        number(record['slot_generation']) == number(f['slot_generation']) and
                        number(record['memory_generation']) == memory_generation and
                        number(record['request_seq']) == number(f['request_seq']) and
                        number(record['model_token']) == tx['token'] and number(record['packet_bytes']) == len(original) and
                        number(record['avcc_bytes']) == len(converted) and number(record['avcc_fnv']) == fnv(converted) and
                        number(record['es_used']) == used + len(converted) and
                        number(record['counter_after']) == packet['pts'] + 1 and
                        number(record['counter_before']) == packet['pts'] and number(record['write_after']) == slot and
                        number(record['es_address']) == number(ef['address']) and number(record['es_offset']) == used and
                        number(record['es_token']) == number(f['es_token']), 'actual packet/PI counter publication differs')
            used += len(converted)
        else:
            stop = video_transfers[-1]
            require(number(f['call_request_seq']) == number(request_jobs[3]['fields']['request_seq']) and
                    number(f['call_native_fnv']) == stop['origin']['fnv1a64'] and number(f['model_token']) == stop['token'] and
                    number(f['result_bytes']) == stop['bytes'] and stop['line'] < publication['line'],
                    'actual PI EOS lost original Stop/encoder-drain association')
            expected_info[0] = 7
            struct.pack_into('<2Q', expected_info, 0x18, len(actual_samples) * 3000, len(actual_samples) * 3000)
            require(not number(f['es_bytes']) and not number(f['es_offset']) and not number(f['es_fnv']) and
                    number(f['frame_generation']) == actual_packets[-1]['generation'], 'actual PI EOS fabricated ES bytes')
        require(info == expected_info, 'actual VideoInfo96 bytes do not describe actual encoded ES extent')
        published[index] = publication
        write_cursor, slot_generations[slot] = slot, number(f['slot_generation'])
    require(used == es_used <= number(opened_fields['es_capacity']), 'actual ES aggregate/capacity differs')
    if forced_transfers:
        tx, done = forced_transfers[0], force_done[0]
        f, rf = done['fields'], force_requests[0]['fields']
        actual_publications = [r for r in publishes if number(r['fields']['call_request_seq']) == number(rf['request_seq'])]
        forced_packets = [r for r in packets if number(r['fields']['model_token']) == tx['token']]
        receive = next(r for r in received if number(r['fields']['command']) == 2)
        require(actual_publications and len(forced_packets) == 1 and
                max(r['line'] for r in actual_publications + forced_packets) < done['line'] < receive['line'] and
                done['line'] < by_command[2]['line'] and
                all(f.get(k) == rf.get(k) for k in ('request_seq', 'native_fnv', 'opaque_word', 'expected_factor', 'expected_result',
                    'software_policy', 'original_argument_semantics_verified', 'capture_verified')) and
                number(f['model_token']) == tx['token'] and number(f['frame_generation']) == tx['frame']['proof']['packet_generation'] and
                f.get('actual_IDR_NAL5') == f.get('publication_complete') == '1',
                'native command2 success preceded actual ES/PI/counter publication or changed waiter')
    returned, prior_read, outstanding = set(), 0, 0
    for row in sorted(publishes + returns, key=lambda row: row['line']):
        f = row['fields']
        if row['tag'] == 'FUNCTIONAL_MPR_PI_PUBLISH':
            outstanding += 1
            continue
        ticket = number(f['ticket'])
        require(ticket not in returned and ticket == len(returned) + 1 and ticket in published and
                published[ticket]['line'] < row['line'] < by_command[4]['line'],
                'original PI reader did not return actual published ticket before Close')
        pf = published[ticket]['fields']
        require(all(f.get(key) == pf.get(key) for key in
                    ('epoch', 'instance', 'native_start_fnv', 'memory_generation', 'group', 'pi_token', 'es_token', 'request_seq',
                     'call_request_seq', 'call_native_fnv', 'model_token', 'result_bytes',
                     'ticket', 'slot', 'slot_generation', 'cycle', 'frame_generation', 'es_offset', 'es_bytes', 'es_fnv',
                     'read_address', 'read_token', 'control_token', 'write_before', 'write_after', 'pid', 'info_address', 'info_hex')) and
                f.get('rc') == '0' and number(f['observer_tid']) > 0 and
                number(f['read_after']) == number(f['read_seen']) and
                0 < (number(f['read_after']) - number(f['read_before'])) % slots <= number(f['outstanding_before']) and
                number(f['outstanding_before']) - number(f['outstanding_after']) ==
                (number(f['read_after']) - number(f['read_before'])) % slots and
                number(f['counter_after']) >= number(f['counter_before']),
                'actual original PI reader advancement/readback/lease differs')
        returned.add(ticket)
        outstanding -= 1
        prior_read = number(f['read_after'])
    return_groups, group = [], []
    for row in sorted(publishes + returns, key=lambda row: row['line']):
        if row['tag'] == 'FUNCTIONAL_MPR_PI_PUBLISH':
            if group:
                return_groups.append(group)
                group = []
            continue
        fields = row['fields']
        signature = tuple(fields[k] for k in ('read_before', 'read_after', 'outstanding_before', 'outstanding_after',
                                               'observed_write', 'counter_before', 'counter_after'))
        if group and signature != group[-1][0]:
            return_groups.append(group)
            group = []
        group.append((signature, row))
    if group:
        return_groups.append(group)
    cursor, returned_tickets = 0, 0
    for group in return_groups:
        f = group[0][1]['fields']
        advance = (number(f['read_after']) - number(f['read_before'])) % slots
        require(number(f['read_before']) == cursor and len(group) == advance > 0 and
                [number(row['fields']['slot']) for _, row in group] == [(cursor + i) % slots for i in range(1, advance + 1)] and
                [number(row['fields']['ticket']) for _, row in group] == list(range(returned_tickets + 1, returned_tickets + advance + 1)),
                'actual original reader cursor does not retire these specific PI slots/tickets')
        cursor, returned_tickets = number(f['read_after']), returned_tickets + advance
    require(not outstanding and returned == set(published) and prior_read == write_cursor == cursor,
            'actual original PI reader left outstanding frames/EOS at Close')
    candidates = []
    for item in storage.get('items', []):
        if item.get('decode', {}).get('format') != 'MP4' or not item.get('writeback_verified') or not item.get('independent_decoded'):
            continue
        movie = mp4_samples(stored_bytes(storage, item))
        if movie['parameters'] == config and movie['samples'] == actual_samples:
            require(movie['geometry'] == actual_packets[0]['geometry'] and
                    item['decode']['frame_count'] == len(actual_samples), 'MP4 actual decoded geometry/frame count differs')
            candidates.append((item, movie))
    needed(candidates, 'actual ordered encoder NALs absent from original Fsys/SD MP4 sample tables')
    require(len(candidates) == 1 and sum(item.get('decode', {}).get('format') == 'MP4' for item in storage.get('items', [])) == 1,
            'bounded first video proof requires one unambiguous actual MP4')
    item, movie = candidates[0]
    return {'verified': True, 'packets_observed': len(packets), 'epoch': epoch,
            'memory_generation': memory_generation, 'last_frame_generation': previous_generation, 'last_es_used': es_used,
            'event_receive_free_pairs': len(seen), 'original_PI_consumer_observed': True,
            'PI_published_and_returned': len(published), 'raw_encoded_NAL_join_verified': True,
            'native_forced_IDR_requests': len(forced_transfers), 'native_force_waiter_factor': force_factor,
            'path': item['path'], 'samples': len(actual_samples),
            'ordered_NAL_payload_sha256': sha(b''.join(nal for sample in actual_samples for nal in sample)),
            'sample_extents': movie['extents'], 'original_Fsys_contributions': item['areas'],
            'storage_join_verified': True, 'capture_verified': True}


def check_face_source(run, manifest, rows, events, transport=None, sources=None):
    """Only observed OP11 runs import the new checker/parser; old runs stay absent."""
    seen = any(row['tag'].startswith('FUNCTIONAL_FACE_SOURCE_') for row in rows) or any(
        event.get('kind') == 'ap_source_result' or event.get('kind') == 'request' and event.get('opcode') == 11
        for event in events)
    if not seen:
        return dict(status='not_observed', required=False, verified=False, capture_verified=False,
                    physical_asic_compatibility_verified=False, transactions=[], missing=[])
    required = (Path(__file__).with_name('check_face_source.py'),
                RUNTIME / 'functional_face_source_snapshot.py', RUNTIME / 'functional-face-source-snapshot-abi.h')
    if sources is not None:
        for path in required:
            needed(str(path) in sources, 'inputs.json: freeze source snapshot dependency ' + str(path))
            digest_binding(read_absolute(path, 16 * 1024**2), sources[str(path)], 'current source checker dependency')
    api = types.SimpleNamespace(**globals())
    return source_module(required[0]).check(run, manifest, rows, events, transport, api)


def check_graph(run, batch, sources):
    path = NATIVE / 'report/functional-graph-evidence/check_graph.py'
    needed(str(path) in sources, 'inputs.json: freeze functional-graph-evidence/check_graph.py and its dependency closure')
    digest_binding(read_absolute(path, 16 * 1024**2), sources[str(path)], 'current graph evaluator')
    graph = source_module(path)
    proof = graph.evaluate(run, batch)
    require(type(proof) is dict and proof.get('schema') == 'functional-graph-evidence-v1' and
            proof.get('capture_verified') is False and proof.get('physical_asic_compatibility_verified') is False and
            proof.get('original_CP_executed') is False and proof.get('original_CP_RAM_verified') is False and
            proof.get('original_RTOS_verified') is False, 'graph evaluator schema/scope differs')
    return proof


def finish_verdict(result, manifest):
    """Acceptance has one gate; HOST_TEST replay can exercise joins, never native acceptance."""
    evidence = result['evidence']
    global_stages = ('profile', 'batch', 'transport', 'CMOS_encoder', 'graph')
    common = all(evidence.get(name, {}).get('verified') is True for name in global_stages)
    for kind in ('JPEG', 'MP4'):
        product = result['products'][kind]
        product['capture_verified'] = bool(common and not result['missing'] and
            evidence.get(kind + '_causality', {}).get('capture_verified') is True and
            product.get('writeback_verified') is True and product.get('independent_decoded') is True and
            product.get('functional_codec_verified') is True)
    if manifest.get('evidence_class') in ('HOST_TEST', 'NATIVE_PARSER_TEST'):
        result['missing'].append({'code': 'TRACE_MISSING', 'stage': 'native_acceptance',
                                  'detail': manifest['evidence_class'] + ' synthetic replay is not actual current-VM capture evidence'})
        for product in result['products'].values():
            product['capture_verified'] = False
    result['capture_verified'] = all(product['capture_verified'] for product in result['products'].values())
    result['verdict'] = 'PASS' if result['capture_verified'] else 'SOURCE/TRACE_MISSING' if result['missing'] and all(
        item['code'] in ('SOURCE_MISSING', 'TRACE_MISSING') for item in result['missing']) else 'FAIL'
    return result


def evaluate(run, batch):
    """Inspect completed local evidence; return a verdict without modifying the run.

    Missing or malformed evidence never raises capture_verified. Individual stage
    successes survive later failures; stage success is not product acceptance.
    Both products require complete original causality and independent decode.
    """
    result = {'schema': 'functional-camera-evidence-v1', 'profile': PROFILE, 'verdict': 'FAIL',
              'capture_verified': False, 'physical_asic_compatibility_verified': False,
              'original_CP_executed': False, 'original_CP_RAM_verified': False,
              'original_RTOS_verified': False, 'evidence_scope': 'plaintext consistency, not cryptographic attestation',
              'evidence': {}, 'missing': [], 'products': {
                  'JPEG': {'capture_verified': False}, 'MP4': {'capture_verified': False}}}
    def stage(name, function, *args):
        try:
            value = function(*args)
            result['evidence'][name] = value
            return value
        except (OSError, ValueError, TypeError, KeyError, AttributeError, IndexError,
                OverflowError, struct.error, tarfile.TarError) as error:
            code = 'TRACE_MISSING' if isinstance(error, (MissingEvidence, FileNotFoundError)) else 'EVIDENCE_INVALID'
            result['missing'].append({'code': code, 'stage': name, 'detail': f'{type(error).__name__}: {error}'})
            result['evidence'][name] = {'verified': False}
            if isinstance(error, CrankControlRejected):
                result['evidence'][name].update(crank_control_rejected=error.event,
                    capture_verified=False, physical_asic_compatibility_verified=False)
            if isinstance(error, MovieFormatRejected):
                result['evidence'][name].update(movie_format_rejected=error.event,
                    capture_verified=False, physical_asic_compatibility_verified=False)
            if isinstance(error, OuCrankControlRejected):
                result['evidence'][name].update(ou_crank_control_rejected=error.event,
                    capture_verified=False, physical_asic_compatibility_verified=False)
            return None
    run = stage('run', writeback.directory, run)
    if run is None:
        result['verdict'] = 'SOURCE/TRACE_MISSING' if all(item['code'] == 'TRACE_MISSING' for item in result['missing']) else 'FAIL'
        return result
    result['run'] = str(run)
    result['evidence']['run'] = {'path': str(run), 'verified': True}
    manifest_raw = stage('manifest_file', read, run, 'runtime-manifest.json', writeback.MAX_JSON)
    manifest = stage('manifest', object_json, manifest_raw) if manifest_raw is not None else None
    if manifest_raw is not None:
        result['evidence']['manifest_file'] = {'sha256': sha(manifest_raw), 'bytes': len(manifest_raw)}
    raw = stage('console', read, run, 'console.log', MAX_LOG)
    events_raw = stage('broker_jsonl', read, run, 'functional-camera-broker-receipts.jsonl', MAX_LOG)
    rows = stage('trace', parse_console, raw) if raw is not None else None
    events = stage('broker_events', jsonl, events_raw) if events_raw is not None else None
    if raw is not None:
        result['evidence']['console'] = {'sha256': sha(raw), 'bytes': len(raw)}
    if events_raw is not None:
        result['evidence']['broker_jsonl'] = {'sha256': sha(events_raw), 'bytes': len(events_raw)}
    profile = stage('profile', check_profile, manifest) if manifest is not None else None
    if rows is not None and manifest is not None and any(row['tag'].startswith('FUNCTIONAL_LAYOUT_STAGE') for row in rows):
        stage('startup_layout_stage', check_layout_stage, run, manifest, rows)
    if rows is not None and manifest is not None and any(row['tag'].startswith('FUNCTIONAL_BACKGROUND_START_') for row in rows):
        # Prefixes survive failed/unattached broker runs; completion still needs the real closed transport.
        stage('background_start', check_background_start, run, manifest, rows)
    frozen = stage('batch', check_batch, run, batch, manifest) if manifest is not None else None
    if frozen is not None:
        value, sources = frozen
        build = dict(value, verified=True)
        result['evidence']['batch'] = build
    else:
        build, sources = None, {}
    storage = stage('writeback', writeback.inspect, run)
    if storage is not None:
        for kind in result['products']:
            items = [item for item in storage.get('items', []) if item.get('decode', {}).get('format') == kind]
            codec_ok = bool(items) and (kind == 'JPEG' or all(item.get('decode', {}).get('codec') == 'h264' for item in items))
            result['products'][kind].update(writeback_verified=bool(items) and all(item.get('writeback_verified') for item in items),
                independent_decoded=bool(items) and all(item.get('independent_decoded') for item in items),
                functional_codec_verified=codec_ok, files=[item.get('path') for item in items])
            if not codec_ok:
                result['missing'].append({'code': 'TRACE_MISSING', 'stage': kind,
                                          'detail': 'actual independently decoded JPEG/H.264 product required by functional profile'})
            if not items or not all(item.get('writeback_verified') and item.get('independent_decoded') for item in items):
                result['missing'].append({'code': 'TRACE_MISSING', 'stage': kind,
                    'detail': 'actual original MPR/Fsys source/callback/readback, both exports and independent decode: ' +
                              storage.get('error', '; '.join(item.get('error', '') for item in items))})
    transport = stage('transport', check_transport, run, manifest, rows, events, build) if all(
        item is not None for item in (profile, build, rows, events)) else None
    if rows is not None and events is not None and manifest is not None:
        source = stage('functional_AP_source_snapshot_consumed', check_face_source,
                       run, manifest, rows, events, transport, sources)
        if source is not None and source['required']:
            result['missing'].extend(dict(item, stage='functional_AP_source_snapshot_consumed')
                                     for item in source.get('missing', []))
    if transport is not None:
        if transport.get('crank_control_content', {}).get('required'):
            result['evidence']['crank_control_content'] = transport['crank_control_content']
            result['missing'].extend(dict(code='TRACE_MISSING', stage='crank_control_native', detail=detail)
                                     for detail in transport['crank_control_content']['missing_native_observations'])
        if transport.get('movie_format_content', {}).get('required'):
            result['evidence']['movie_format_content'] = transport['movie_format_content']
            result['missing'].extend(dict(code='TRACE_MISSING', stage='movie_format_native', detail=detail)
                                     for detail in transport['movie_format_content']['missing_native_observations'])
        if transport.get('ou_crank_control_content', {}).get('required'):
            result['evidence']['ou_crank_control_content'] = transport['ou_crank_control_content']
            result['missing'].extend(dict(code='TRACE_MISSING', stage='ou_crank_control_native', detail=detail)
                                     for detail in transport['ou_crank_control_content']['missing_native_observations'])
        if transport['background_start']['required']:
            result['evidence']['background_start'] = transport['background_start']
            # A successful full transport supersedes the preliminary no-broker pass.
            result['missing'] = [m for m in result['missing'] if m['stage'] != 'background_start']
            if not transport['background_start']['verified']:
                result['missing'].append(dict(code='TRACE_MISSING', stage='background_start',
                    detail='original 3006 remains pending; full actual model/response/AP-free closure required'))
        if transport['startup_layout_stage']['required']:
            result['evidence']['startup_layout_stage'] = transport['startup_layout_stage']
        if transport['still_format']['required']:
            result['evidence']['still_format'] = transport['still_format']
            result['missing'].extend(dict(code='TRACE_MISSING', stage='still_format', detail=detail)
                                     for detail in transport['still_format']['missing'])
        if transport['startup_control']['required']:
            result['evidence']['startup_control'] = transport['startup_control']
            result['missing'].extend(dict(code='TRACE_MISSING', stage='startup_control', detail=detail)
                                     for detail in transport['startup_control']['missing'])
        if transport['focus_reset']['required']:
            result['evidence']['focus_reset'] = transport['focus_reset']
            result['missing'].extend(dict(code='TRACE_MISSING', stage='focus_reset', detail=detail)
                                     for detail in transport['focus_reset']['missing'])
        if transport['histogram']['required']:
            result['evidence']['histogram'] = transport['histogram']
        if transport['control']['required']:
            result['evidence']['control'] = transport['control']
        if storage and storage.get('exports', {}).get('pid') != transport['pid']:
            result['missing'].append({'code': 'EVIDENCE_INVALID', 'stage': 'storage_owner',
                                      'detail': 'original Fsys flush/write PID differs from actual guest mailbox owner'})
        frames = stage('CMOS_encoder', check_frames, run, transport)
        jpeg = stage('JPEG_causality', check_jpeg, rows, transport, storage or {}, run)
        video = stage('MP4_causality', check_video, rows, transport, storage or {}, run)
        if frames is not None:
            result['products']['JPEG']['CMOS_encoder_verified'] = True
            result['products']['MP4']['CMOS_encoder_verified'] = True
        for kind, proof in (('JPEG', jpeg), ('MP4', video)):
            result['products'][kind]['original_request_and_compressed_content_verified'] = bool(
                proof and proof.get('capture_verified') is True)
    graph = stage('graph', check_graph, run, batch, sources) if build is not None else None
    if graph is not None:
        graph['verified'] = graph.get('graph_verified') is True and graph.get('all_13_graph_edges_complete') is True
        if not graph['verified']:
            result['missing'].extend(dict(item, stage='graph.' + item.get('stage', 'content')) for item in graph.get('missing', []))
            if not graph.get('missing'):
                result['missing'].append({'code': 'TRACE_MISSING', 'stage': 'graph', 'detail': 'current-batch thirteen graph edges incomplete'})
        elif transport is not None:
            identity = graph.get('evidence', {}).get('run_binding', {})
            if identity.get('original_AP_pid') != transport['pid']:
                result['missing'].append({'code': 'EVIDENCE_INVALID', 'stage': 'graph', 'detail': 'graph AP PID differs from actual capture owner'})
    # Re-read the exact accepted inputs after decoders and content joins.
    def unchanged():
        require(raw == read(run, 'console.log', MAX_LOG) and
                events_raw == read(run, 'functional-camera-broker-receipts.jsonl', MAX_LOG) and
                manifest_raw == read(run, 'runtime-manifest.json', writeback.MAX_JSON),
                'completed run evidence changed during evaluation')
        if transport is not None:
            require(typed_equal(manifest.get('functional_camera_runtime'), json_file(run, 'functional-camera-runner.json')),
                    'final closed runner receipt changed during evaluation')
            for tx in transport['transfers']:
                transfer_output(run, tx)
        if build is not None:
            root = Path(build['batch'])
            ready_raw = read(root, 'ready.json', writeback.MAX_JSON)
            digest_binding(ready_raw, build['ready_sha256'], 'final frozen ready.json')
            ready = object_json(ready_raw)
            for name, key in (('inputs.json', 'inputs_sha256'), ('inputs.tar.gz', 'all_input_archive_sha256'),
                              ('host-regression.json', 'regression_sha256'), ('abi.json', 'abi_sha256'),
                              ('functional-camera-model.so', 'functional_model_library_sha256'),
                              ('functional-camera-model-build.json', 'functional_model_build_receipt_sha256'),
                              ('functional-model-sources.tar.gz', 'functional_model_source_archive_sha256')):
                digest_binding(read(root, name), ready.get(key), 'final frozen ' + name)
        for name, digest in sources.items():
            digest_binding(read_absolute(Path(name), 16 * 1024**2), digest, 'final current frozen source')
        return {'verified': True}
    stage('final_immutability', unchanged)
    return finish_verdict(result, manifest or {})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('run', help='absolute completed owned run directory')
    parser.add_argument('batch', help='absolute frozen unified batch directory or ready.json')
    parser.add_argument('--output', type=Path, help='optional new JSON directly beside this checker, outside run/batch')
    args = parser.parse_args()
    result = evaluate(args.run, args.batch)
    text = json.dumps(result, indent=2, ensure_ascii=True) + '\n'
    if args.output is None:
        print(text, end='')
    else:
        target = writeback.absolute_path(args.output)
        require(target.parent == Path(__file__).resolve().parent and not target.exists() and not target.is_symlink(),
                'receipt output must be a new direct checker-directory file')
        require(not target.is_relative_to(writeback.absolute_path(args.run)) and
                not target.is_relative_to(writeback.absolute_path(args.batch)), 'output must be outside evidence inputs')
        with target.open('x', encoding='ascii') as stream:
            stream.write(text)
    return 0 if result['capture_verified'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
