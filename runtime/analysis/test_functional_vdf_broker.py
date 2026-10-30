"""VDF broker wire boundaries; synthetic replies are HOST_TEST, not camera proof."""
import ctypes
import importlib.util
from pathlib import Path
import struct

import pytest

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('vdf_broker_boundary_test', HERE / 'functional_camera_broker.py')
b = importlib.util.module_from_spec(spec)
spec.loader.exec_module(b)
INSTANCE = 0x123456789abcdef0


def response(active=True):
    body = bytes((1, 5, 5) if active else (0, 1, 1)) + bytes(13)
    raw = bytearray(160)
    for offset, value in ((0, 1), (4, 160), (84, 0x90590819), (88, 1), (92, 1),
                          (96, int(active)), (100, int(active)), (104, 1), (108, 1),
                          (112, int(active)), (116, int(active))):
        struct.pack_into('<I', raw, offset, value)
    for offset, value in ((8, INSTANCE), (16, 8), (24, 4 + int(active)),
                          (40, b.fnv64(body)), (144, 4), (152, 7)):
        struct.pack_into('<Q', raw, offset, value)
    if active:
        struct.pack_into('<Q', raw, 32, 9)
        struct.pack_into('<3Q', raw, 48, 0x1234, 0x1234, 640 * 480 * 3)
        struct.pack_into('<3I', raw, 72, 640, 480, 640 * 3)
    raw[128:144] = body
    return body, bytes(raw)


def zebra_response(active=True):
    route, base = response(active)
    data = bytes((3, 0, 0x20, 75, 65, 0, 0, 0))
    raw = bytearray(base + data)
    struct.pack_into('<I', raw, 4, 168)
    struct.pack_into('<Q', raw, 40, b.fnv64(data))
    return data, route, bytes(raw)


def layout_response():
    route, base = response()
    raw = bytearray(base + b.LAYOUT_INITIAL_BODY)
    struct.pack_into('<I', raw, 4, 192)
    struct.pack_into('<Q', raw, 40, b.fnv64(b.LAYOUT_INITIAL_BODY))
    return b.LAYOUT_INITIAL_BODY, route, bytes(raw)


def display_response(command):
    route, base = response()
    body = bytes.fromhex('0300010000eb8080') if command == 0x152 else bytes(8)
    data = struct.pack('<2I', command, 8 if command == 0x152 else 2 if command == 0x162 else 0) + body
    raw = bytearray(base + data)
    struct.pack_into('<I', raw, 4, 176)
    struct.pack_into('<Q', raw, 40, b.fnv64(data))
    return data, route, bytes(raw)


def bb_response(command, body=None):
    examples = {
        0x111: (28, bytes.fromhex('00000f02') + bytes(24)),
        0x166: (28, bytes.fromhex('0001') + bytes(26)),
        0x167: (2, bytes.fromhex('0100')),
        0x15f: (4, bytes(4)),
        0x128: (12, bytes.fromhex('000100001e00000000000000')),
    }
    count, default = examples[command]
    body = default if body is None else body
    data = struct.pack('<2H', command, count) + body + bytes(28 - count)
    route, base = response()
    raw = bytearray(base + data)
    struct.pack_into('<I', raw, 4, 192)
    struct.pack_into('<I', raw, 96, 5)
    struct.pack_into('<Q', raw, 40, b.fnv64(data))
    return data, route, bytes(raw)


def histogram_response():
    data = bytes.fromhex('4801040001010000')
    bins = b''.join(bytes((value + channel * 37) & 255 for value in range(256)) for channel in range(4))
    route, base = response()
    raw = bytearray(base + data + bins)
    struct.pack_into('<I', raw, 4, 1192)
    struct.pack_into('<I', raw, 96, 6)
    struct.pack_into('<Q', raw, 40, b.fnv64(data))
    return data, route, bytes(raw)


def bit_width_response():
    data, (route, base) = bytes(8), response()
    raw = bytearray(base + data)
    struct.pack_into('<I', raw, 4, 168)
    struct.pack_into('<I', raw, 96, 7)
    struct.pack_into('<Q', raw, 40, b.fnv64(data))
    return data, route, bytes(raw)


def core_with_reply(raw):
    class Library:
        def fcam_model_request(self, model, opcode, incoming, size, outgoing, capacity, result):
            assert opcode in (b.VDF_PATH, b.VDF_ZEBRA, b.VDF_LAYOUT, b.VDF_DISPLAY_CONFIG,
                              b.BB_STARTUP_CONFIG, b.HISTOGRAM, b.VDF_BIT_WIDTH) and capacity >= len(raw)
            assert size == {b.VDF_PATH: 16, b.VDF_ZEBRA: 8, b.VDF_LAYOUT: 32, b.VDF_DISPLAY_CONFIG: 16,
                            b.BB_STARTUP_CONFIG: 32, b.HISTOGRAM: 8, b.VDF_BIT_WIDTH: 8}[opcode]
            ctypes.memmove(outgoing, raw, len(raw))
            result._obj.used = len(raw)
            return 0
    core = b.Core.__new__(b.Core)
    core.model, core.instance, core.library = object(), INSTANCE, Library()
    return core


@pytest.mark.parametrize('command', [0x111, 0x166, 0x167, 0x15f, 0x128])
def test_bb_neutral_readback_uses_its_exact_canonical_bank(command):
    data, route, raw = bb_response(command)
    assert b.bb_startup_input_valid(data)
    core = core_with_reply(raw)
    core.vdf_route = route
    code, copied, result = core.execute(INSTANCE, b.BB_STARTUP_CONFIG, data, 192)
    assert code == 0 and copied[160:] == data and result.used == 192 and not result.token
    assert core.vdf_route == route


@pytest.mark.parametrize('body', [bytes.fromhex('0001') + bytes(26),
                                bytes.fromhex('00010000000000000000000008000000070000000100000001000000')])
def test_bb0166_only_complete_identity_tokens_pass_consistent_receipt(body):
    data, route, raw = bb_response(0x166, body)
    core = core_with_reply(raw)
    core.vdf_route = route
    assert core.execute(INSTANCE, b.BB_STARTUP_CONFIG, data, 192)[1] == raw
    for offset in range(28):
        for value in range(256):
            if value == body[offset]:
                continue
            changed = bytearray(data)
            changed[offset + 4] = value
            assert not b.bb_startup_input_valid(changed)
        changed = bytearray(data)
        changed[offset + 4] ^= 1
        forged = bytearray(raw)
        forged[160:] = changed
        struct.pack_into('<Q', forged, 40, b.fnv64(changed))
        core = core_with_reply(bytes(forged))
        core.vdf_route = route
        with pytest.raises(ValueError, match='BB initial/neutral'):
            core.execute(INSTANCE, b.BB_STARTUP_CONFIG, bytes(changed), 192)
    for malformed in (data[:-1], data + b'\x7f', bytes(32),
                      data[:2] + b'\x20\x00' + data[4:]):
        assert not b.bb_startup_input_valid(malformed)


@pytest.mark.parametrize('command,offset', [(0x111, 8), (0x166, 5), (0x167, 4), (0x15f, 4), (0x128, 4)])
def test_bb_semantic_scope_cannot_be_bypassed_with_a_consistent_echo(command, offset):
    data, route, raw = bb_response(command)
    data = bytearray(data)
    data[offset] = 2 if command == 0x167 else 1 if command != 0x166 else 2
    changed = bytearray(raw)
    changed[160:] = data
    struct.pack_into('<Q', changed, 40, b.fnv64(data))
    core = core_with_reply(bytes(changed))
    core.vdf_route = route
    with pytest.raises(ValueError, match='BB initial/neutral'):
        core.execute(INSTANCE, b.BB_STARTUP_CONFIG, bytes(data), 192)


@pytest.mark.parametrize('operation', [b.BB_STARTUP_CONFIG, b.HISTOGRAM])
@pytest.mark.parametrize('offset', [0, 4, 8, 16, 24, 40, 56, 72, 80, 84, 92, 96, 104, 108, 112, 116, 120, 124, 128, 160])
def test_bb_histogram_reply_metadata_or_canonical_mutation_is_rejected(operation, offset):
    data, route, raw = bb_response(0x111) if operation == b.BB_STARTUP_CONFIG else histogram_response()
    changed = bytearray(raw)
    changed[offset] ^= 1
    core = core_with_reply(bytes(changed))
    core.vdf_route = route
    with pytest.raises(ValueError):
        core.execute(INSTANCE, operation, data, len(raw))


@pytest.mark.parametrize('operation', [b.BB_STARTUP_CONFIG, b.HISTOGRAM])
def test_bb_histogram_require_the_committed_fixed_rgb_geometry(operation):
    data, route, raw = bb_response(0x111) if operation == b.BB_STARTUP_CONFIG else histogram_response()
    with pytest.raises(ValueError, match='committed VDF route'):
        core_with_reply(raw).execute(INSTANCE, operation, data, len(raw))
    changed = bytearray(raw)
    struct.pack_into('<3I', changed, 72, 320, 480, 960)
    struct.pack_into('<Q', changed, 64, 320 * 480 * 3)
    core = core_with_reply(bytes(changed))
    core.vdf_route = route
    with pytest.raises(ValueError, match='RGB geometry'):
        core.execute(INSTANCE, operation, data, len(raw))


def test_first_histogram_retains_all_four_software_segments():
    data, route, raw = histogram_response()
    core = core_with_reply(raw)
    core.vdf_route = route
    code, copied, result = core.execute(INSTANCE, b.HISTOGRAM, data, 1192)
    assert code == 0 and copied == raw and result.used == 1192 and copied[160:168] == data
    assert len(copied[168:]) == 1024 and len({copied[n:n + 256] for n in range(168, 1192, 256)}) == 4
    changed = bytearray(raw)
    changed[168:424] = bytes(256)
    core = core_with_reply(bytes(changed))
    core.vdf_route = route
    with pytest.raises(ValueError, match='software histogram'):
        core.execute(INSTANCE, b.HISTOGRAM, data, 1192)
    changed = bytearray(raw)
    bad_input = data[:-1] + b'\x01'
    changed[160:168] = bad_input
    struct.pack_into('<Q', changed, 40, b.fnv64(bad_input))
    core = core_with_reply(bytes(changed))
    core.vdf_route = route
    with pytest.raises(ValueError, match='software histogram'):
        core.execute(INSTANCE, b.HISTOGRAM, bad_input, 1192)


@pytest.mark.parametrize('active', [True, False])
def test_vdf_response_passes_actual_core_execute_boundary(active):
    body, raw = response(active)
    code, copied, result = core_with_reply(raw).execute(INSTANCE, b.VDF_PATH, body, 160)
    assert code == 0 and copied == raw and result.used == 160 and not result.token


@pytest.mark.parametrize('offset', [8, 16, 40, 56, 84, 92, 112, 116, 124, 128])
def test_vdf_response_mutations_cannot_claim_model_or_sink_completion(offset):
    body, raw = response()
    corrupt = bytearray(raw)
    corrupt[offset] ^= 1
    with pytest.raises(ValueError):
        core_with_reply(bytes(corrupt)).execute(INSTANCE, b.VDF_PATH, body, 160)


def test_disabled_vdf_cannot_claim_a_consumed_frame():
    body, raw = response(False)
    corrupt = bytearray(raw)
    struct.pack_into('<Q', corrupt, 64, 1)
    with pytest.raises(ValueError, match='Disabled VDF'):
        core_with_reply(bytes(corrupt)).execute(INSTANCE, b.VDF_PATH, body, 160)


@pytest.mark.parametrize('active', [True, False])
def test_zebra_copies_configuration_without_changing_committed_route(active):
    data, route, raw = zebra_response(active)
    core = core_with_reply(raw)
    core.vdf_route = route
    code, copied, result = core.execute(INSTANCE, b.VDF_ZEBRA, data, 168)
    assert code == 0 and copied == raw and copied[160:] == data and result.used == 168
    assert core.vdf_route == route


@pytest.mark.parametrize('offset', [4, 40, 128, 160, 167])
def test_zebra_reply_shape_route_and_config_mutations_are_rejected(offset):
    data, route, raw = zebra_response()
    corrupt = bytearray(raw)
    corrupt[offset] ^= 1
    core = core_with_reply(bytes(corrupt))
    core.vdf_route = route
    with pytest.raises(ValueError):
        core.execute(INSTANCE, b.VDF_ZEBRA, data, 168)
    assert core.vdf_route == route


def test_zebra_requires_existing_route_and_disabled_scope():
    data, route, raw = zebra_response()
    core = core_with_reply(raw)
    with pytest.raises(ValueError, match='committed VDF route'):
        core.execute(INSTANCE, b.VDF_ZEBRA, data, 168)
    enabled = bytearray(data)
    enabled[1] = 1
    corrupt = bytearray(raw)
    corrupt[160:] = enabled
    struct.pack_into('<Q', corrupt, 40, b.fnv64(enabled))
    core = core_with_reply(bytes(corrupt))
    core.vdf_route = route
    with pytest.raises(ValueError, match='Zebra disabled'):
        core.execute(INSTANCE, b.VDF_ZEBRA, bytes(enabled), 168)


def test_layout_reads_all_configuration_after_active_rgb_completion():
    data, route, raw = layout_response()
    core = core_with_reply(raw)
    core.vdf_route = route
    code, copied, result = core.execute(INSTANCE, b.VDF_LAYOUT, data, 192)
    assert code == 0 and copied == raw and copied[160:] == data and result.used == 192
    assert core.vdf_route == route


@pytest.mark.parametrize('offset', [4, 32, 40, 56, 72, 80, 128, 160, 184, 191])
def test_layout_corrupted_identity_geometry_or_readback_cannot_complete(offset):
    data, route, raw = layout_response()
    corrupt = bytearray(raw)
    corrupt[offset] ^= 1
    if offset == 32:
        corrupt[32:40] = bytes(8)
    core = core_with_reply(bytes(corrupt))
    core.vdf_route = route
    with pytest.raises(ValueError):
        core.execute(INSTANCE, b.VDF_LAYOUT, data, 192)
    assert core.vdf_route == route


@pytest.mark.parametrize('offset', [0, 3, 4, 12, 22, 24, 28, 31])
def test_layout_has_no_unmodelled_selector_padding_or_rectangle_defaults(offset):
    data, route, raw = layout_response()
    data = bytearray(data)
    data[offset] ^= 1
    corrupt = bytearray(raw)
    corrupt[160:] = data
    struct.pack_into('<Q', corrupt, 40, b.fnv64(data))
    core = core_with_reply(bytes(corrupt))
    core.vdf_route = route
    with pytest.raises(ValueError, match='layout software policy'):
        core.execute(INSTANCE, b.VDF_LAYOUT, bytes(data), 192)


def test_layout_requires_an_existing_active_route():
    data, route, raw = layout_response()
    core = core_with_reply(raw)
    with pytest.raises(ValueError, match='committed VDF route'):
        core.execute(INSTANCE, b.VDF_LAYOUT, data, 192)
    core.vdf_route = bytes((0, 1, 1)) + bytes(13)
    with pytest.raises(ValueError, match='committed VDF route'):
        core.execute(INSTANCE, b.VDF_LAYOUT, data, 192)


@pytest.mark.parametrize('command', [0x141, 0x152, 0x162])
def test_display_typed_configuration_reads_back_without_changing_route(command):
    data, route, raw = display_response(command)
    core = core_with_reply(raw)
    core.vdf_route = route
    code, copied, result = core.execute(INSTANCE, b.VDF_DISPLAY_CONFIG, data, 176)
    assert code == 0 and copied == raw and copied[160:] == data and result.used == 176
    assert core.vdf_route == route
    corrupt = bytearray(raw)
    corrupt[175] ^= 1
    core = core_with_reply(bytes(corrupt))
    core.vdf_route = route
    with pytest.raises(ValueError, match='display configuration/readback'):
        core.execute(INSTANCE, b.VDF_DISPLAY_CONFIG, data, 176)


@pytest.mark.parametrize('command,offset,value', [(0x152, 0, 0x53), (0x152, 4, 7),
    (0x152, 8, 4), (0x152, 9, 1), (0x152, 10, 3), (0x152, 11, 1),
    (0x152, 12, 1), (0x152, 13, 0), (0x162, 8, 1), (0x162, 10, 1),
    (0x141, 4, 1), (0x141, 8, 1)])
def test_display_rejects_unmodelled_features_even_with_consistent_mock_readback(command, offset, value):
    data, route, raw = display_response(command)
    data = bytearray(data)
    data[offset] = value
    corrupt = bytearray(raw)
    corrupt[160:] = data
    struct.pack_into('<Q', corrupt, 40, b.fnv64(data))
    core = core_with_reply(bytes(corrupt))
    core.vdf_route = route
    with pytest.raises(ValueError, match='disabled-feature policy'):
        core.execute(INSTANCE, b.VDF_DISPLAY_CONFIG, bytes(data), 176)


def test_bit_width0_requires_independent_readback_and_fixed_committed_rgb_route():
    data, route, raw = bit_width_response()
    core = core_with_reply(raw)
    with pytest.raises(ValueError, match='committed VDF route'):
        core.execute(INSTANCE, b.VDF_BIT_WIDTH, data, 168)
    core.vdf_route = route
    code, copied, result = core.execute(INSTANCE, b.VDF_BIT_WIDTH, data, 168)
    assert code == 0 and copied == raw and result.used == 168 and not result.token
    assert copied[160:] == bytes(8) and core.vdf_route == route
    changed = bytearray(raw)
    struct.pack_into('<3I', changed, 72, 320, 480, 960)
    struct.pack_into('<Q', changed, 64, 320 * 480 * 3)
    core = core_with_reply(bytes(changed))
    core.vdf_route = route
    with pytest.raises(ValueError, match='RGB geometry'):
        core.execute(INSTANCE, b.VDF_BIT_WIDTH, data, 168)


@pytest.mark.parametrize('offset', [0, 4, 8, 16, 24, 32, 40, 56, 84, 92, 96, 104, 108, 112, 116, 120, 128, 160, 167])
def test_bit_width_corrupt_class_tail_or_copy_proof_is_rejected(offset):
    data, route, raw = bit_width_response()
    changed = bytearray(raw)
    changed[offset] ^= 1
    if offset == 32:
        changed[32:40] = bytes(8)
    core = core_with_reply(bytes(changed))
    core.vdf_route = route
    with pytest.raises(ValueError):
        core.execute(INSTANCE, b.VDF_BIT_WIDTH, data, 168)
    assert core.vdf_route == route


@pytest.mark.parametrize('offset,value', [(0, 1), (0, 2), (0, 3), (0, 255), *((i, 1) for i in range(1, 8))])
def test_bit_width_consistent_echo_does_not_authorize_another_software_domain(offset, value):
    data, route, raw = bit_width_response()
    data, changed = bytearray(data), bytearray(raw)
    data[offset] = value
    changed[160:] = data
    struct.pack_into('<Q', changed, 40, b.fnv64(data))
    core = core_with_reply(bytes(changed))
    core.vdf_route = route
    with pytest.raises(ValueError, match='bit-width0 RGB888'):
        core.execute(INSTANCE, b.VDF_BIT_WIDTH, bytes(data), 168)


@pytest.mark.parametrize('opcode,data,capacity', [
    (b.VDF_BIT_WIDTH, bytes(8), 168),
    (b.VDF_PATH, bytes((1, 5, 5)) + bytes(13), 160),
    (b.VDF_ZEBRA, bytes((3, 0, 0x20, 75, 65)) + bytes(3), 168),
    (b.VDF_LAYOUT, b.LAYOUT_INITIAL_BODY, 192),
    (b.VDF_DISPLAY_CONFIG, display_response(0x152)[0], 176),
    (b.VDF_DISPLAY_CONFIG, display_response(0x162)[0], 176),
    (b.VDF_DISPLAY_CONFIG, display_response(0x141)[0], 176),
])
def test_vdf_request_requires_exact_body(opcode, data, capacity):
    mailbox = dict(pid=1234, nonce=INSTANCE, pages=[0x400021000 + n * b.PAGE for n in range(16)])
    raw = bytearray(b.HEADER)
    struct.pack_into('<4I', raw, 0, b.MAGIC, b.VERSION, mailbox['pid'], b.REQUEST)
    struct.pack_into('<QQIII', raw, 16, INSTANCE, 1, opcode, len(data), capacity)
    struct.pack_into('<Q', raw, 56, b.fnv64(data))
    if opcode == b.VDF_DISPLAY_CONFIG:
        command, body_bytes = struct.unpack_from('<2I', data)
        native_bytes = 8 + body_bytes
    else:
        command, native_bytes = {b.VDF_PATH: (0x138, 24), b.VDF_ZEBRA: (0x153, 14), b.VDF_LAYOUT: (0x14c, 40),
                                 b.VDF_BIT_WIDTH: (0x15e, 10)}[opcode]
    struct.pack_into('<5I', raw, 96, 1235, 0x81cf61c4, 0x92840747, command, native_bytes)
    struct.pack_into('<16Q', raw, 128, *mailbox['pages'])
    assert b.validate_request(bytes(raw), data, mailbox, 0) == (opcode, capacity)
    struct.pack_into('<I', raw, 36, len(data) - 1)
    struct.pack_into('<Q', raw, 56, b.fnv64(data[:-1]))
    with pytest.raises(ValueError, match='request size'):
        b.validate_request(bytes(raw), data[:-1], mailbox, 0)
