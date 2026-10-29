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
MAX_FILE = 256 * 1024**2
MAX_LOG = 64 * 1024**2
MAX_EVENTS = 100000
DATA_BYTES = 65024
OPS = {1: (0, 48), 2: (0,), 3: (48,), 4: (32,), 5: (16,), 6: (8,), 7: (32,), 8: (16,),
       9: (32,), 10: (8,), 16: (16, 144),
       32: (48,), 33: (0,), 34: (0,), 64: (24,), 65: (16,), 66: (0,)}
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
    'display_config_policy': 'original-0141-refresh-0152-disabled-and-0162-off-RGB-readback-before-independent-reply',
    'display_config_commands': [0x141, 0x152, 0x162],
    'peaking_enabled_supported': False,
    'display_flag_enabled_supported': False,
    'original_Peaking_operator_verified': False,
    'original_0162_feature_verified': False,
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
                  8: ({0x141: 8, 0x152: 16, 0x162: 10}, 176), 9: (BB_COMMANDS, 192)}
CONFIG_OPERATIONS = {**VDF_OPERATIONS, 10: ({0x148: 12}, 1192)}
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
    records = [row for row in rows if row['tag'].startswith('FUNCTIONAL_CAMERA_CONTROL_')]
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
                        number(x['destination']) >> 16 == 0x8002 and ptr(x.get('reply', x.get('pointer', '(nil)'))) and
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
    for policy in (VDF_POLICY, ZEBRA_POLICY, LAYOUT_POLICY, DISPLAY_POLICY, BB_POLICY, HIST_POLICY, XSYNC_POLICY, BACKGROUND_POLICY):
        if any('functional_camera_' + key in manifest or 'functional_camera_' + key in backup for key in policy):
            expected.update(policy)
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
    for name, digest in files.items():
        if name in frozen:
            require(digest == frozen[name], 'manifest frozen source drift: ' + name)
    backup = manifest['backup_transport']
    require(backup.get('binary_sha256') == QEMU_SHA256 and files.get(backup.get('binary')) == QEMU_SHA256,
            'manifest QEMU differs from accepted unchanged executable')
    digest_binding(read_absolute(backup['binary']), QEMU_SHA256, 'actual accepted QEMU')
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
            'model_source_archive_sha256': model['source_archive_sha256'], 'qemu_sha256': QEMU_SHA256,
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


def parse_console(raw):
    require(len(raw) <= MAX_LOG, 'console exceeds budget')
    rows = []
    for line, item in enumerate(raw.splitlines(keepends=True), 1):
        require(len(item) <= 8192, 'console line exceeds budget')
        item = item[4:] if item.startswith(b'OBS ') else item
        tag = item.split(b' ', 1)[0].rstrip(b'\r\n')
        if not tag.startswith((b'FUNCTIONAL_', b'FSYS_WRITE_', b'MPR_WRITE_')) and tag.decode('ascii', 'ignore') not in (
                *BACKGROUND_FREE_TAGS, 'NATIVE_CP302C_DIAGNOSTIC_ALL13_READBACK', 'NATIVE_CP302C_NOCONVERT_ALL13_READBACK'):
            continue
        require(item.endswith(b'\n'), 'truncated evidence trace')
        parts = item.decode('ascii', 'strict').rstrip('\r\n').split(' ')
        # Diagnostic failure prose is retained, never parsed as a successful record.
        if not all(re.fullmatch(r'[A-Za-z_][A-Za-z_0-9]*=[!-~]+', part) for part in parts[1:]):
            rows.append({'tag': parts[0], 'line': line, 'fields': {}, 'diagnostic': ' '.join(parts[1:])})
            continue
        rows.append({'tag': parts[0], 'line': line,
                     'fields': writeback.unique_object(part.split('=', 1) for part in parts[1:])})
        require(len(rows) <= MAX_EVENTS, 'trace record budget exceeded')
    return rows


def jsonl(raw):
    require(raw and len(raw) <= MAX_LOG and raw.endswith(b'\n'), 'empty/truncated broker JSONL')
    rows = []
    last_time = 0
    for index, line in enumerate(raw.splitlines(), 1):
        require(index <= MAX_EVENTS and len(line) <= 16384, 'broker event/line budget exceeded')
        row = object_json(line)
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


def vdf_result(raw, canonical, instance, opcode=5, route=None):
    """Parse the exact opcode-specific configuration result and current RGB route."""
    require(opcode in CONFIG_OPERATIONS, 'unknown VDF/BB/histogram configuration opcode')
    size = CONFIG_OPERATIONS[opcode][1]
    require(len(raw) == size and struct.unpack_from('<2I', raw) == (1, size),
            'VDF result size differs from its actual opcode')
    if opcode in (6, 7, 8, 9, 10):
        if opcode == 9:
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
                    (command == 0x162 and body_bytes == 2 and body == bytes(8)),
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
            value['class'] == ({9: 5, 10: 6}.get(opcode, active)) and
            value['enabled'] == value['frame_consumed'] == value['retired'] == active and
            value['status'] == value['reserved'] == 0, 'VDF configuration readback/endpoint/commit differs')
    require(0 < value['before_config_generation'] < 2**64 - 1 and
            value['config_generation'] == value['before_config_generation'] + 1 and
            value['frame_generation'] == value['before_frame_generation'] + active and
            0 < value['width'] <= 8192 and 0 < value['height'] <= 8192 and
            value['stride'] == value['width'] * 3, 'VDF configuration/frame generation or geometry differs')
    if opcode in (7, 9, 10):
        require(active == 1 and (value['width'], value['height'], value['stride']) == (640, 480, 1920) and
                value['active_bytes'] == 921600, 'Layout/BB/histogram requires the active full 640x480 RGB software route')
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


def vdf_history(run, transport):
    """Join display commits to the actual latest state/job and unchanged route."""
    route, config, generation, geometry = b'\x00\x01\x01' + bytes(13), None, None, None
    parameters, preserve_parameters, last_lease = None, False, 0
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
        elif op in CONFIG_OPERATIONS:
            raw = transfer_output(run, tx)
            value = vdf_result(raw, payload_read(run, tx['request_payload']), transport['model_instance'], op, route)
            require(value['before_config_generation'] == config and value['before_frame_generation'] == generation and
                    (value['width'], value['height']) == geometry and tx['token'] == 0,
                    'VDF before generations/geometry differ from actual model history')
            require(not value['enabled'] or value['lease_generation'] > last_lease,
                    'VDF reused an old rendered RGB lease')
            values[tx['first']] = value
            config, generation, route = value['config_generation'], value['frame_generation'], raw[128:144]
            preserve_parameters = preserve_parameters or op in (6, 7, 8, 9, 10)
        elif op == 4:
            preserve_parameters = False
        elif tx.get('frame') is not None:
            proof = tx['frame']['proof']
            config, generation = proof['config_generation'], proof['frame_generation']
        if tx.get('frame') is not None and tx['frame']['proof']['render_observed']:
            last_lease = tx['frame']['proof']['lease_generation']
    return values


def noncodec_proof(tx, value, transport, output):
    """Kinds4/5/6 are explicit RGB configuration/data work, never codecs."""
    event = tx.get('frame')
    needed(type(event) is dict and type(event.get('proof')) is dict, 'actual noncodec RGB proof required')
    p, active = event['proof'], value['enabled']
    kind = {5: 4, 6: 4, 7: 4, 8: 4, 9: 5, 10: 6}.get(tx['opcode'])
    result = output if tx['opcode'] in (9, 10) else b''
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
    original = any(tx['origin']['destination'] == 0x92840747 and tx['origin']['command'] in native_opcodes
                   for tx in transport['transfers'])
    if not (transfers or records or original or bindings):
        return {'required': False, 'verified': False, 'cycles': [], 'diagnostics': diagnostics}
    needed(transfers and records, 'VDF op5/op6/op7/op8/BB9 and their original receive/free receipts required together')
    refreshes = [tx for tx in transfers if tx['origin']['command'] == 0x141]
    needed(len(bindings) >= len(refreshes), 'VDF each original0141 requires its own refresh queue binding receipt')
    require(len(bindings) == len(refreshes), 'VDF refresh binding/original0141 census differs')
    history = vdf_history(run, transport)
    groups = {}
    for row in records:
        cycle = number(row['fields']['cycle'])
        group = groups.setdefault(cycle, {})
        require(cycle > 0 and row['tag'] not in group, 'VDF duplicate/zero/old cycle receipt')
        group[row['tag']] = row
    require(list(groups) == list(range(1, len(groups) + 1)) and len(groups) == len(transfers),
            'VDF original cycle/op5/op6/op7/op8/BB9 census differs')
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
        zebra, layout, display, bb = (tx['opcode'] == op for op in (6, 7, 8, 9))
        commands, result_bytes = VDF_OPERATIONS[tx['opcode']]
        command = tx['origin']['command']
        require(command in commands, 'VDF configuration opcode/native command mapping differs')
        native_bytes = commands[command]
        route = output[128:144]
        event = tx.get('frame')
        needed(type(event) is dict and type(event.get('proof')) is dict, 'VDF/BB actual kind4/kind5 RGB/config proof required')
        p, active = noncodec_proof(tx, value, transport, output), value['enabled']
        origin = tx['origin']
        if bb:
            require(type(origin['source']) is int and 0 < origin['source'] < 2**32,
                    'BB source must be the complete native u32 without truncation')
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
        allocate_after_free = layout or display or bb
        for name, row in r.items():
            f, line = row['fields'], row['line']
            wire = raw_hex(f, 'raw', native_bytes)
            if bb:
                converted = struct.pack('<2H', command, native_bytes - 8) + wire[8:] + bytes(36 - native_bytes)
            elif display:
                converted = struct.pack('<2I', command, native_bytes - 8) + wire[8:] + bytes(16 - native_bytes)
            else:
                converted = wire[8:] if layout else wire[8:13] + bytes(3) if zebra else wire[8:21] + bytes(3)
            require(wire[:8] == struct.pack('<4H', 0x200d, command, native_bytes, 0x8001) and
                    converted == canonical and fnv(wire) == origin['fnv1a64'] ==
                    int(writeback.hash_hex(f.get('original_fnv1a'), 16), 16) and
                    raw_hex(f, 'ack_wire', 12) == struct.pack('<4HI', 0x200d, command + 0x1000, 12, 0x8001,
                                                            0 if zebra or bb else 0x590000) and
                    raw_hex(f, 'canonical_config', 16) == route and
                    raw_hex(f, 'model_result_hex', result_bytes) == output and
                    int(writeback.hash_hex(f.get('model_result_fnv1a64'), 16), 16) == fnv(output),
                    'VDF raw request/ACK/config/result bytes differ')
            if zebra or layout or display or bb:
                key, count = ('canonical_bb32', 32) if bb else ('canonical_display16', 16) if display else ('canonical_layout32', 32) if layout else ('canonical_zebra8', 8)
                require(raw_hex(f, key, count) == canonical and number(f['model_result_bytes']) == result_bytes,
                        'Zebra/layout/display canonical/result native receipt differs')
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
            'VDF original0138/0153/014c/0141/0152/0162 was relabelled as a media/configuration operation')
    return {'required': True, 'verified': True, 'cycles': checked, 'diagnostics': diagnostics,
            'physical_asic_compatibility_verified': False,
            'original_selector_verified': False, 'original_CP_FIFO_verified': False, 'original_RTOS_verified': False,
            'original_Zebra_gate_verified': False, 'original_VDF_area_order_verified': False,
            'original_VDF_layout_hardware_verified': False,
            'original_Peaking_operator_verified': False, 'original_0162_feature_verified': False,
            'original_BB_C_configuration_work_verified': False, 'original_BB_C_configuration_units_verified': False}


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
    require(all(previous < row['line'] for row in rows if row['tag'] in path_tags or
                row['tag'] == 'FUNCTIONAL_CAMERA_TRANSFER' and number(row['fields']['op']) in VDF_OPERATIONS),
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
    require(raw[44:56] == bytes(12) and raw[64:96] == bytes(32) and raw[116:120] == bytes(4) and
            raw[256:] == bytes(256), 'broker request reserved/response fields not pristine')
    op, count, capacity = get32(32), get32(36), get32(40)
    require(get64(24) == row['sequence'] and op == row['opcode'] and op in OPS and count in OPS[op] and
            count == row['request_bytes'] and capacity <= DATA_BYTES and get64(56) == row['request_fnv1a64'],
            'broker actual request header/opcode/size differs')
    origin = dict(producer_tid=get32(96), source=get32(100), destination=get32(104),
                  command=get32(108), bytes=get32(112), fnv1a64=get64(120))
    require(0 < origin['producer_tid'] < 2**31 and origin['source'] and origin['destination'] and origin['bytes'],
            'missing original producer/TID/SID')
    return raw, origin, capacity


def check_transport(run, manifest, rows, events, build):
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
                          ('source_archive_sha256', build['model_source_archive_sha256']), ('qemu_sha256', QEMU_SHA256)):
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
            config.get('qemu_sha256') == QEMU_SHA256 and
            typed_equal(config.get('owner'), runner.get('owner')) and
            typed_equal(config.get('qemu'), runner.get('debugger_handoff', {}).get('qemu_identity')),
            'mixed-run/owner/QEMU transport binding')
    require(Path(config.get('qemu', {}).get('exe', '')).name == 'qemu-system-aarch64' and
            config['qemu']['pid'] == runner['debugger_handoff']['qemu_pid'], 'original QEMU process identity differs')
    counts, transactions, pending = {}, {}, None
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
    active_result = None
    for event in events:
        require(type(event.get('model_instance')) is int and event['model_instance'] == mailbox['nonce'], 'mixed model instance')
        kind = event.get('kind')
        require(kind in ('binding', 'attached', 'request', 'core_result', 'response', 'physical_mode_restored',
                         'resume_suppressed', 'detach_commit', 'mailbox_detached', 'cancel_cleanup',
                         'debugger_disconnected', 'cleanup', 'model_frame'), 'failed/rejected/unknown broker event')
        counts[kind] = counts.get(kind, 0) + 1
        if kind == 'request':
            seq = uint(event.get('sequence'))
            require(pending is None and seq == len(transactions) + 1, 'request gap/replay/interleaving')
            header, origin, capacity = mailbox_header(event, mailbox)
            writeback.hash_hex(event.get('request_sha256'), 64)
            if event['request_bytes'] == 0:
                require(event['request_sha256'] == sha(b'') and event['request_fnv1a64'] == fnv(b''),
                        'empty model request has different actual byte digest')
            pending = {'request': event, 'origin': origin, 'capacity': capacity, 'raw_header': header}
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
            pending['request_data'] = incoming
            transactions[seq] = pending
        elif kind in ('core_result', 'response'):
            require(pending is not None and event.get('sequence') == pending['request']['sequence'] and
                    event.get('opcode') == pending['request']['opcode'] and kind not in pending,
                    'unmatched/duplicate actual C result/response')
            require(type(event.get('actual_c_result')) is int and event['actual_c_result'] == 0,
                    'actual model C execution failed')
            count, token, total, offset = (uint(event.get(key)) for key in ('returned_bytes', 'token', 'total', 'offset'))
            require(count <= pending['capacity'] and total <= 64 * 1024**2 and offset <= total and
                    (token and 0 < count <= total - offset or not token and not total and not offset), 'actual C result bounds')
            writeback.hash_hex(event.get('returned_sha256'), 64)
            pending[kind] = event
            if kind == 'core_result':
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
                        require(op in (16, 33, 34) and active_result is None and offset == 0,
                                'actual encoded lease overlaps/has invalid origin')
                        active_result = dict(token=token, total=total, cursor=0, fnv=writeback.FNV_INIT,
                                             digest=hashlib.sha256(), chunks=0, first=pending['request']['sequence'])
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
                require('core_result' in pending and all(typed_equal(pending['core_result'].get(key), event.get(key)) for key in
                        ('actual_c_result', 'returned_bytes', 'returned_sha256', 'returned_fnv1a64', 'token', 'total', 'offset',
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
        elif kind == 'model_frame':
            require(pending is not None and 'core_result' in pending and 'frame' not in pending and
                    event.get('sequence') == pending['request']['sequence'] and
                    event.get('opcode') == pending['request']['opcode'] and
                    event.get('actual_c_result') == 0 and event.get('actual_core_sha256') == build['model_sha256'] and
                    typed_equal(event.get('origin'), pending['origin']) and
                    typed_equal(event.get('request_payload'), pending['request'].get('request_payload')) and
                    typed_equal(event.get('output_payload'), pending['core_result'].get('output_payload')),
                    'frame proof differs from actual original C call')
            pending['frame'] = event
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
        require(number(f['model_instance']) == mailbox['nonce'] and number(f['op']) == tx['request']['opcode'] and
                number(f['request_bytes']) == tx['request']['request_bytes'] and
                number(f['request_fnv']) == tx['request']['request_fnv1a64'], 'bridge initial request differs from broker')
        for seq in ids:
            origin = transactions[seq]['origin']
            require(all(number(f[guest]) == origin[host] for guest, host in
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
                        'token': token, 'model_instance': mailbox['nonce']})
    require(covered == set(transactions), 'broker responses not fully consumed by actual guest bridge')
    needed(all(counts.get(key) == 1 for key in ('binding', 'attached', 'cancel_cleanup', 'cleanup',
                                              'detach_commit', 'mailbox_detached', 'debugger_disconnected')),
           'broker: one binding/attach/actual cancel/detach/disconnect/cleanup lifecycle')
    lifecycle = {event['kind']: event for event in events if event['kind'] in
                 ('detach_commit', 'mailbox_detached', 'debugger_disconnected', 'cleanup')}
    require(lifecycle['detach_commit'].get('model_work_stopped') is True and
            lifecycle['detach_commit'].get('no_further_ram_after_ack') is True and
            lifecycle['mailbox_detached'].get('cleanup_detach') is True and
            lifecycle['debugger_disconnected'].get('detached') is True and
            [lifecycle[k]['event'] for k in ('detach_commit', 'mailbox_detached', 'debugger_disconnected', 'cleanup')] ==
            sorted(lifecycle[k]['event'] for k in ('detach_commit', 'mailbox_detached', 'debugger_disconnected', 'cleanup')) and
            max(tx['response']['event'] for tx in transactions.values()) < lifecycle['detach_commit']['event'],
            'detach precedes committed work or cleanup lifecycle is unsafe')
    for event in events:
        if event['kind'] == 'cancel_cleanup':
            require(type(event.get('actual_c_result')) is int and event['actual_c_result'] == 0 and
                    event.get('returned_bytes') == 128 and max(tx['response']['event'] for tx in transactions.values()) <
                    event['event'] < lifecycle['detach_commit']['event'],
                    'actual model cleanup cancel failed/late')
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
        require(type(backup) is dict and all(
            typed_equal(manifest.get('functional_camera_' + key), value) and
            typed_equal(backup.get('functional_camera_' + key), value) for key, value in DISPLAY_POLICY.items()),
            'Display operation lacks the explicit disabled/off software policy')
    for opcode, policy in ((9, BB_POLICY), (10, HIST_POLICY)):
        if any(tx['opcode'] == opcode for tx in checked):
            backup = manifest.get('backup_transport')
            require(type(backup) is dict and all(
                typed_equal(manifest.get('functional_camera_' + key), value) and
                typed_equal(backup.get('functional_camera_' + key), value) for key, value in policy.items()),
                'BB/histogram operation lacks its exact typed software policy')
    result['histogram'] = check_histogram(run, rows, result)
    result['control'] = check_control(run, rows, result)
    if result['control']['required']:
        backup = manifest.get('backup_transport')
        require(type(backup) is dict and all(typed_equal(manifest.get('functional_camera_' + key), value) and
                typed_equal(backup.get('functional_camera_' + key), value) for key, value in XSYNC_POLICY.items()),
                'control timing lacks the exact typed software clock policy')
    result['background_start'] = check_background_start(run, manifest, rows, result)
    if result['background_start']['required'] and not result['background_start']['verified']:
        result['verified'] = False
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


def check_frames(run, transport, *, require_media=True, require_codecs=None):
    # Existing component callers use require_codecs; both defaults still require all media jobs.
    require_media = require_media and require_codecs is not False
    jobs, counts, serial, lifetime, generation, config = [], None, 0, None, 0, None
    sensor_initialized, video_geometry, geometry = False, None, None
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
        if op in CONFIG_OPERATIONS:
            vdf = display_history[tx['first']]
            require(vdf['before_config_generation'] == config and vdf['before_frame_generation'] == generation and
                    (vdf['width'], vdf['height']) == geometry and tx['token'] == 0,
                    'VDF before generations/geometry differ from actual model history')
            config = vdf['config_generation']
        required = op in CONFIG_OPERATIONS or op in (16, 33, 34) or op == 1 and not sensor_initialized
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
                p['opcode'] == op and p['operation_status'] == 0 and p['config_generation'] == config,
                'actual frame instance/lifetime/configuration/operation differs')
        before, after = p['before'], p['after']
        require(counts is None or before == counts, 'actual per-job counter history differs')
        delta = {key: after[key] - before[key] for key in before}
        require(all(value >= 0 for value in delta.values()), 'actual model counters regressed')
        output = transfer_output(run, tx)
        kind = p['consumer_kind']
        result_data = b'' if kind in (0, 4) else output
        require(p['result_bytes'] == len(result_data) and p['result_fnv1a64'] == fnv(result_data) and p['result_token'] == tx['token'],
                'actual coded result is not this frame job output')
        require(kind == {1: 0, 5: 4, 6: 4, 7: 4, 8: 4, 9: 5, 10: 6, 16: 1, 33: 2, 34: 3}.get(op), 'actual frame consumer kind differs')
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
            require(p['encoded_bytes'] == len(encoded) and p['encoded_fnv1a64'] == fnv(encoded),
                    'actual encoder-coded bytes differ from reconstructed result')
        serial, lifetime, generation, counts = p['serial'], p['model_lifetime'], p['frame_generation'], after
        result_key = 'configuration_result_sha256' if kind in (4, 5, 6) else 'encoded_result_sha256'
        jobs.append({'first': tx['first'], 'opcode': op, 'proof': p, result_key: tx['sha256']})
        if op == 1:
            require(state_counts == {k: after[k] for k in state_counts} and state_generation == generation,
                    'actual INIT State128/probe receipt differs')
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
        transfers = [tx for tx in transport['transfers'] if tx['opcode'] == 16 and
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
        require(len(still) == 16 and struct.unpack_from('<4I', still)[:3] == (1, *parts['geometry']) and
                all(a == 0 or a == b for a, b in zip(struct.unpack_from('<2H', body, 0x40), parts['geometry'])),
                'actual original JPEG dimensions differ from encoder job')
        needed(type(tx.get('frame')) is dict, 'JPEG actual same-frame encoder proof')
        proof = tx['frame']['proof']
        require(proof['consumer_kind'] == 1 and proof['model_instance'] == transport['model_instance'] and
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
                           'original-freed-done', 'original-rescmd-done'):
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
    needed(set(by_command) == {0, 1, 3, 4}, 'FUNCTIONAL_MPR_OPERATION: successful original Open/Start/Stop/Close commands 0,1,3,4')
    require([by_command[c]['line'] for c in (0, 1, 3, 4)] == sorted(by_command[c]['line'] for c in (0, 1, 3, 4)),
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
    require(len(received) == len(freed) == 4, 'original video event receive/free count differs')
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
    require(commands == {0, 1, 3, 4}, 'missing actual Open/Start/Stop/Close event consumption')
    requests = [row for row in rows if row['tag'] == 'FUNCTIONAL_MPR_REQUEST']
    needed(len(requests) == 4, 'FUNCTIONAL_MPR_REQUEST: actual original Open/Start/Stop/Close raw bytes')
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
    for recv in received:
        f = recv['fields']
        free = next(row for row in freed if row['fields']['seq'] == f['seq'])
        ff = free['fields']
        command = number(f['command'])
        request = request_jobs[command]
        rf = request['fields']
        original = raw_hex(rf, 'wire_hex', 48)
        event_wire = bytearray(48)
        struct.pack_into('<H', event_wire, 2, command * 2 + 1)
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
    for tx in video_transfers:
        command = 3 if tx['opcode'] == 34 else 1
        rf = request_jobs[command]['fields']
        require(tx['origin']['fnv1a64'] == number(rf['native_fnv']) and tx['origin']['command'] == command and
                tx['origin']['source'] == 0x80c70047 and tx['origin']['destination'] == 0x8055001f and
                tx['origin']['bytes'] == 48 and type(tx.get('frame')) is dict,
                'actual video frame lost native Start/Stop origin or frame proof')
        raw = transfer_output(run, tx)
        for packet in camera_packets(raw):
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
                    number(ef['call_request_seq']) == number(request_jobs[3 if tx['opcode'] == 34 else 1]['fields']['request_seq']) and
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
            'path': item['path'], 'samples': len(actual_samples),
            'ordered_NAL_payload_sha256': sha(b''.join(nal for sample in actual_samples for nal in sample)),
            'sample_extents': movie['extents'], 'original_Fsys_contributions': item['areas'],
            'storage_join_verified': True, 'capture_verified': True}


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
    if transport is not None:
        if transport['background_start']['required']:
            result['evidence']['background_start'] = transport['background_start']
            # A successful full transport supersedes the preliminary no-broker pass.
            result['missing'] = [m for m in result['missing'] if m['stage'] != 'background_start']
            if not transport['background_start']['verified']:
                result['missing'].append(dict(code='TRACE_MISSING', stage='background_start',
                    detail='original 3006 remains pending; full actual model/response/AP-free closure required'))
        if transport['startup_layout_stage']['required']:
            result['evidence']['startup_layout_stage'] = transport['startup_layout_stage']
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
