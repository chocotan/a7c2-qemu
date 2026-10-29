#!/usr/bin/env python3
"""Read-only source checks; never execute firmware or claim post-boot current."""
from pathlib import Path
import hashlib
import json
import struct

HERE = Path(__file__).resolve().parent


def verify():
    manifest = json.loads((HERE / 'cp-central-startup-origin-bytepins.json').read_text())
    blob = (HERE.parent / 'runtime/analysis/menu-root/cp/cpapp-b.bin').read_bytes()
    base = int(manifest['raw_base'], 16)
    assert len(blob) == manifest['cp_bytes']
    assert hashlib.sha256(blob).hexdigest() == manifest['cp_sha256']
    assert len(manifest['pins']) == 20
    for address, size, expected in manifest['pins']:
        offset = int(address, 16) - base
        assert 0 <= offset <= len(blob) - size
        assert hashlib.sha256(blob[offset:offset + size]).hexdigest() == expected, address
    regions = struct.unpack_from('<13I', blob, 0x128148 - base)
    assert regions[:3] == (0x10e2000, 0x97bf5c, 0x120a000) and regions[9] == 0x128000
    assert regions[0] + regions[9] == regions[2]
    assert regions[2] + regions[1] == 0x1b85f5c
    clear = manifest['explicit_clear']
    start, end, current = (int(clear[key], 16) for key in ('start', 'end_exclusive', 'current_address'))
    assert start == 0x120a418 and end == 0x1b85f5c and current == 0x1a52ad4
    assert start <= current and current + 4 <= end and end - start == 0x97bb44
    # The source STRD loop writes the zero r3 word at +0x3c of this iteration.
    delta = current - start
    assert delta == 0x8486bc and (delta & ~0x7f) == 0x848680 and delta % 128 == 0x3c
    array = list(struct.unpack_from('<1112I', blob, 0xffe444 - base))
    assert all(array[:-1]) and array[-1] == 0 and array[1013] == 0xb1f329
    assert 0xffe444 + 4 * 1013 == 0xfff418 and 0xffe444 + 4 * 1111 == 0xfff5a0
    assert hashlib.sha256(blob[0xffe444 - base:0xfff5a4 - base]).hexdigest() == manifest['constructors']['array_including_zero_sha256']
    assert struct.unpack_from('<4I', blob, 0xffe434 - base) == (0x61057c, 0x619ddc, 0, 0)
    assert clear['source_initial_current_at_clear_return'] == 0
    assert manifest['source_post_constructor_current_known'] is False
    assert manifest['runtime_current_before_302c_known'] is False
    return {'source_windows_verified': 20, 'initialization_clear_covers_current': True,
            'source_initial_current_at_clear_return': 0, 'constructor_entries': 1111,
            'central_constructor_index': 1013, 'post_constructor_current_known': False,
            'runtime_current_before_302c_known': False, '302c_native_verified': False, 'capture_verified': False}


if __name__ == '__main__':
    print(json.dumps(verify(), indent=2))
