from pathlib import Path
import hashlib
import json
import struct

import pytest

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]


def test_original_sos_marker_paths_and_control_windows():
    pins = json.loads((HERE/'source-pins.json').read_text())
    original = ROOT/pins['artifact']
    if not original.is_file():
        pytest.skip('prepared public ALLLANG av-cam asset is absent')
    image = original.read_bytes()
    assert len(image) == pins['bytes'] == 13797088
    assert hashlib.sha256(image).hexdigest() == pins['sha256']
    assert len(pins['windows']) == pins['window_count'] == 10
    assert sum(row['bytes'] for row in pins['windows']) == pins['window_bytes'] == 2376
    for row in pins['windows']:
        start = int(row['raw_hex'], 16)
        data = image[start:start + row['bytes']]
        assert len(data) == row['bytes']
        assert hashlib.sha256(data).hexdigest() == row['sha256'], row['name']
    assert image[0x30a0e0:0x30a0ec] == bytes.fromhex('000c03010002110311003f00')
    table = 0x3862c8
    assert struct.unpack_from('<Q', image, table + (0xda - 0xc0)*8)[0] == 0xffffffc0012aafe4
    assert struct.unpack_from('<Q', image, table + (0xdd - 0xc0)*8)[0] == 0xffffffc0012aadd8
    assert not pins['whole_branch_closed'] and pins['scan_restart_gap_retained'] == 2
    assert not pins['native_capture'] and not pins['original_consumed']
