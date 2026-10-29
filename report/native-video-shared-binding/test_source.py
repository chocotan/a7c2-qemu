from pathlib import Path
import hashlib
import json
import struct

import pytest

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]


def test_original_shared_video_fields_and_setup_calls():
    pins = json.loads((HERE/'source-pins.json').read_text())
    images = {}
    for name, row in pins['artifacts'].items():
        path = ROOT/'runtime/analysis/menu-root'/row['path']
        if not path.is_file():
            pytest.skip('prepared public ALLLANG assets are absent')
        image = path.read_bytes()
        assert len(image) == row['bytes']
        assert hashlib.sha256(image).hexdigest() == row['sha256']
        images[name] = image
    assert len(pins['windows']) == pins['window_count'] == 10
    assert sum(row['bytes'] for row in pins['windows']) == pins['window_bytes'] == 4040
    for row in pins['windows']:
        start = int(row['file_offset_hex'], 16)
        data = images[row['artifact']][start:start + row['bytes']]
        assert len(data) == row['bytes']
        assert hashlib.sha256(data).hexdigest() == row['sha256']
    for caller, target, kind in pins['kernel_setup_calls']:
        address = int(caller, 16)
        word = struct.unpack_from('<I', images['K'], address)[0]
        assert kind in ('B', 'BL')
        assert word >> 26 == (0b100101 if kind == 'BL' else 0b000101)
        displacement = word & 0x3ffffff
        if displacement & 0x2000000:
            displacement -= 0x4000000
        assert address + 4*displacement == int(target, 16)
    assert pins['descriptor_prefix_bytes'] == 0x28
    assert pins['inline_parameter_bytes'] == 0x98
    assert pins['read_control_parameter_offset'] == 0x50
    assert pins['write_control_parameter_offset'] == 0x58
    assert pins['write_index_offset_in_write_control'] == 4
    assert not pins['same_control_base_assumed']
    assert not pins['asynchronous_pointer_transport_verified']
    assert pins['native_gap_mask'] == 63 and not pins['capture_verified']
