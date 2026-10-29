import hashlib
import importlib.util
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
spec = importlib.util.spec_from_file_location('imola_image', HERE.parent/'imola-mcu-firmware-contract/image.py')
image = importlib.util.module_from_spec(spec)
spec.loader.exec_module(image)
PINS = json.loads((HERE/'source-pins.json').read_text())


def test_original_bank_windows_and_exact_control_function():
    data = image.load_image(ROOT/PINS['artifact'])
    assert len(PINS['windows']) == PINS['window_count'] == 8
    assert sum(row['bytes'] for row in PINS['windows']) == PINS['window_bytes'] == 4256
    for row in PINS['windows']:
        window = image.read_window(data, row['bank'], int(row['VA_hex'], 16), row['bytes'])
        assert hashlib.sha256(window).hexdigest() == row['sha256']
    fn = PINS['exact_function']
    assert int(fn['end_VA_hex'], 16) - int(fn['VA_hex'], 16) == fn['bytes'] == 156
    window = image.read_window(data, 'ram1', int(fn['VA_hex'], 16), fn['bytes'])
    assert hashlib.sha256(window).hexdigest() == fn['sha256']
    for address, word in ((0x807482c0, 0x68e50400), (0x807482f8, 0xb0e20d00),
                          (0x80748304, 0xb0e20d01), (0x80748310, 0xb0e20d03),
                          (0x8074831c, 0xb0e20d04)):
        assert int.from_bytes(image.read_window(data, 'ram1', address, 4), 'little') == word
    assert not PINS['GPR_width_known'] and not PINS['MCU_executed']


def test_conditional_standard_LDL_merge_cannot_poll_bit0():
    # This tests the standard-ISA hypothesis, not vendor opcode execution.
    branch = PINS['conditional_predecessor']
    a3, old = (int(branch[key], 16) for key in ('a3_canonical_hex', 'a1_canonical_hex'))
    address = a3 + 0x400
    assert address == int(branch['EA_canonical_hex'], 16)
    assert address & 7 == branch['alignment'] == 4
    shift = (7 - (address & 7)) * 8
    assert shift == branch['LDL_preserved_low_bits'] == 24
    mask = (1 << 64) - 1
    preserve = (1 << shift) - 1
    for incoming in (old, old | 1):
        for memory in (0, mask, *(1 << bit for bit in range(64))):
            merged = ((memory << shift) & mask) | (incoming & preserve)
            assert merged & preserve == incoming & preserve
            assert merged & 1 == incoming & 1
    assert old & 1 == branch['old_a1_bit0'] == 0
    assert not branch['runtime_branch_observed'] and not branch['field4_helpers_closed']
