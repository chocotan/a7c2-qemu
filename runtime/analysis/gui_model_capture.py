"""Read actual inline model packets; local generations are not CP versions."""
import base64
import hashlib
import struct
from headless_osd_capture import clean_export_transport

TYPES = ((0x10, 0x274), (0x15, 12), (0x16, 20), (0x19, 12), (0x1a, 4), (0x1b, 16))
PREFIX_BYTES = 852
MAX_PACKET_BYTES = 4096


def fnv64(raw):
    value = 14695981039346656037
    for byte in raw:
        value = ((value ^ byte) * 1099511628211) & ((1 << 64) - 1)
    return value


def decode_packet(raw):
    if not 8 <= len(raw) <= MAX_PACKET_BYTES or struct.unpack_from('<II', raw) != (0, len(raw) - 8):
        raise ValueError('invalid inline packet command/size')
    models, seen, offset = [], set(), 8
    while offset < len(raw):
        if len(raw) - offset < 8 or len(models) == 64:
            raise ValueError('truncated/oversized inline model table')
        kind, size = struct.unpack_from('<II', raw, offset)
        offset += 8
        if kind in seen or size > len(raw) - offset:
            raise ValueError('duplicate/truncated inline model')
        seen.add(kind)
        body = raw[offset:offset + size]
        models.append({'type': kind, 'bytes': size, 'sha256': hashlib.sha256(body).hexdigest(),
                       'raw_hex': body.hex()})
        offset += size
    return models


def decode_model_export(console):
    lines = console.replace(b'\r', b'').splitlines()
    start = lines.index(b'GUI_MODEL_BEGIN') + 1
    end = lines.index(b'GUI_MODEL_END', start)
    transport, _, _, _ = clean_export_transport(b'\n'.join(lines[start:end]) + b'\n')
    raw = b''.join(base64.b64decode(line, validate=True) for line in transport.splitlines() if line)
    if not 868 <= len(raw) <= 860 + MAX_PACKET_BYTES or raw[:8] != b'GMDL0003':
        raise ValueError('virtual model snapshot size/magic mismatch')
    if fnv64(raw[:-8]) != struct.unpack_from('<Q', raw, len(raw) - 8)[0]:
        raise ValueError('virtual model snapshot checksum mismatch')
    packets, input_fnv = struct.unpack_from('<QQ', raw, 8)
    present, changed = struct.unpack_from('<II', raw, 24)
    profile = struct.unpack_from('<8I', raw, 32)
    if (not packets or present & ~63 or changed & ~present or
            profile != (4, 1, 1, 125, 100, 1, 6, len(raw))):
        raise ValueError('invalid virtual model snapshot header')
    values, offset = [], 64
    for i, (expected_type, expected_size) in enumerate(TYPES):
        kind, size, generation = struct.unpack_from('<IIQ', raw, offset)
        offset += 16
        if present & (1 << i):
            if kind != expected_type or size != expected_size or not 0 < generation <= packets:
                raise ValueError('invalid named model cache')
            body = raw[offset:offset + size]
            values.append({'type': kind, 'bytes': size, 'local_generation': generation,
                           'sha256': hashlib.sha256(body).hexdigest(), 'raw_hex': body.hex()})
            offset += size
        elif kind or size or generation:
            raise ValueError('unavailable named cache has nonzero record')
    if offset > PREFIX_BYTES or any(raw[offset:PREFIX_BYTES]):
        raise ValueError('invalid named cache padding')
    packet = raw[PREFIX_BYTES:-8]
    if fnv64(packet) != input_fnv:
        raise ValueError('original inline packet digest mismatch')
    models = decode_packet(packet)
    return raw, {'ok': True, 'profile': 'virtual-inline-v1', 'packets': packets,
                 'input_fnv64': f'{input_fnv:016x}', 'present': present, 'changed': changed,
                 'sha256': hashlib.sha256(raw).hexdigest(), 'models': models,
                 'original_packet_sha256': hashlib.sha256(packet).hexdigest(),
                 'named_model_cache': values,
                 'fixed_exposure': {'f_number': [4, 1], 'seconds': [1, 125], 'iso': 100},
                 'guest_exposure_queries_implemented': False,
                 'cp_subscriptions_implemented': False, 'cp_composition_implemented': False}
