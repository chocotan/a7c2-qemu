"""Static public-original byte verification; never execute the module or infer YC packing."""
import hashlib
import json
from pathlib import Path
import struct

HERE = Path(__file__).resolve().parent


def test_original_provider_and_destination_windows():
    pins = json.loads((HERE / 'source-pins.json').read_text())
    raw = (HERE.parents[1] / pins['asset']['path']).read_bytes()
    assert len(raw) == pins['asset']['bytes'] == 13797088
    assert hashlib.sha256(raw).hexdigest() == pins['asset']['sha256']
    count = size = 0
    for window in pins['windows']:
        start, end = int(window['start'], 16), int(window['end'], 16)
        assert 0 <= start < end <= len(raw)
        assert hashlib.sha256(raw[start:end]).hexdigest() == window['sha256']
        count += 1
        size += end - start
    assert count == pins['principal_window_count'] == 7
    assert size == pins['principal_window_bytes'] == 13868
    kva_base = 0xffffffc001000000
    provider = pins['provider']
    table = int(provider['vtable'], 16)
    assert struct.unpack_from('<Q', raw, int(provider['object'], 16))[0] == kva_base + table
    for slot in provider['slots']:
        assert struct.unpack_from('<Q', raw, table + int(slot['offset'], 16))[0] == kva_base + int(slot['function'], 16)
    assert not any(pins[key] for key in ('native_pixel_layout_known', 'native_generation_lease_complete',
                                       'guest_pixel_consumed', 'capture_verified'))
