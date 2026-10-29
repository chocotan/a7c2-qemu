import hashlib
import importlib.util
import json
from pathlib import Path
import struct

import pytest

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
spec = importlib.util.spec_from_file_location('imola_static_image', HERE/'image.py')
image = importlib.util.module_from_spec(spec)
spec.loader.exec_module(image)
PINS = json.loads((HERE/'source-pins.json').read_text())


@pytest.fixture(scope='session')
def original():
    path = ROOT/PINS['artifact']
    if not path.is_file():
        pytest.skip('prepared public Imola2 firmware is absent')
    return path, image.load_image(path)


def test_original_windows_and_real_instruction_anchors(original):
    _, data = original
    assert len(PINS['windows']) == PINS['window_count'] == 12
    assert sum(r['bytes'] for r in PINS['windows']) == PINS['window_bytes'] == 5448
    for row in PINS['windows']:
        start = int(row['raw_hex'], 16)
        assert hashlib.sha256(data[start:start + row['bytes']]).hexdigest() == row['sha256']
    assert struct.unpack_from('<I', data, 0)[0] == 0x1000000f  # BEQ -> raw40.
    assert struct.unpack_from('<I', data, 0x40)[0] == 0x401a6000  # Actual MFC0.
    for bank, raw in (('ram0', 0x5a4), ('ram1', 0xa6a5a4), ('ram2', 0xa6d5a4)):
        lui, addiu, jalr, delay = struct.unpack_from('<4I', data, raw)
        assert lui >> 26 == 15 and addiu >> 26 == 9
        assert lui >> 16 & 31 == addiu >> 16 & 31 == addiu >> 21 & 31 == 8
        low = addiu & 0xffff
        target = (((lui & 0xffff) << 16) + (low - 0x10000 if low & 0x8000 else low)) & 0xffffffff
        assert target == int(PINS['entry_VA_hex'][bank], 16)
        assert jalr == 0x0100f809 and delay == 0
    for channel in range(8):
        assert struct.unpack_from('<I', data, 0x235cc4 + channel*0x18 + 0xc)[0] == 0xbf044060 + channel*4
    assert struct.unpack_from('<I', data, 0x17defc)[0] == 0xacb20000
    assert not PINS['MCU_executed'] and not PINS['capture_verified']


@pytest.mark.parametrize('bank', tuple(image.REGIONS))
def test_bank_boundaries_and_explicit_aliases(original, bank):
    _, data = original
    start, end, base = image.REGIONS[bank]
    assert list(image.REGIONS[bank]) == PINS['regions'][bank]
    assert image.file_offset(bank, base, end - start) == start
    assert image.read_window(data, bank, base, 16) == data[start:start + 16]
    assert image.read_window(data, bank, base + end - start - 1, 1) == data[end - 1:end]
    if bank.startswith('rom'):
        assert image.read_window(data, bank, base | 0x20000000, 16) == data[start:start + 16]
    for address, size in ((base - 1, 1), (base + end - start, 1), (base, end - start + 1)):
        with pytest.raises(ValueError):
            image.file_offset(bank, address, size)


@pytest.mark.parametrize('bank,address,size', [
    ('unknown', 0x80009000, 1), ('ram0', -1, 1), ('ram0', 0x80009000, 0),
    ('ram0', 0x80009000, -1), ('ram0', 0x80009000, True),
    ('ram0', True, 1), ('ram0', 1 << 100, 1), ('ram0', 0x80009000, 1 << 100),
    ('ram0', 0xa0009000, 1), ('rom0', 0x80009300, 1),
])
def test_unknown_or_unproved_regions_refused(bank, address, size):
    with pytest.raises(ValueError):
        image.file_offset(bank, address, size)


def test_same_rom_address_requires_bank(original):
    _, data = original
    views = [image.read_window(data, name, 0x9fc005a4, 16) for name in ('rom0', 'rom1', 'rom2')]
    assert len(set(views)) == 3
    assert not any(data[0x8cc:0x9000])
    assert not any(data[0xa6a8cc:0xa6d000])


def test_authentication_and_exclusive_export(original, tmp_path):
    path, data = original
    small = tmp_path/'short'
    small.write_bytes(data[:128])
    with pytest.raises(ValueError):
        image.load_image(small)
    changed = tmp_path/'changed'
    altered = bytearray(data)
    altered[0x9300] ^= 1
    changed.write_bytes(altered)
    with pytest.raises(ValueError):
        image.load_image(changed)
    target = tmp_path/'rom1.bin'
    result = image.export_region(path, 'rom1', target)
    expected = data[0xa6a000:0xa6a8cc]
    assert target.read_bytes() == expected
    assert result['bytes'] == len(expected) and not result['firmware_execution']
    assert result['sha256'] == hashlib.sha256(expected).hexdigest()
    before = target.read_bytes()
    with pytest.raises(FileExistsError):
        image.export_region(path, 'rom0', target)
    assert target.read_bytes() == before
    with pytest.raises(ValueError):
        image.read_window(data[:-1], 'rom0', 0x9fc00000, 1)
    assert hashlib.sha256(path.read_bytes()).hexdigest() == image.IMAGE_SHA256
