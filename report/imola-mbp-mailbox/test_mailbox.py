"""HOST_TEST only: bounded mailbox C core and public static firmware anchors."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess

import pytest

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
PINS = json.loads((HERE / 'source-pins.json').read_text())
SPEC = importlib.util.spec_from_file_location(
    'mbp_authenticated_image', HERE.parent / 'imola-mcu-firmware-contract/image.py')
image = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(image)
CASES = (
    'constructor', 'spu0-to-mbp', 'mbp0-to-spu', 'spu1-to-mbp', 'mbp1-to-spu',
    'full-duplex', 'channel-independence', 'partial-stage', 'fresh-stage',
    'busy-retention', 'ack-empty', 'ack-unread', 'ack-one-word', 'repeat-peek',
    'unsupported-access', 'invalid-addressing', 'null-pointers',
    'owner-output-alias', 'wrapped-unaligned-pointers', 'snapshot-passive',
)


@pytest.fixture(scope='module', params=('strict', 'asan-ubsan'))
def mailbox_binary(request, tmp_path_factory):
    compiler = shutil.which('cc')
    if compiler is None:
        pytest.fail('a C11 compiler is required for the mailbox transport checks')
    binary = tmp_path_factory.mktemp('mbp-mailbox') / request.param
    flags = ['-std=c11', '-Wall', '-Wextra', '-Werror', '-pedantic', '-g']
    if request.param == 'asan-ubsan':
        flags += ['-fsanitize=address,undefined', '-fno-omit-frame-pointer',
                  '-fno-pie', '-no-pie']
    subprocess.run([compiler, *flags, str(HERE / 'mbp-mailbox.c'),
                    str(HERE / 'test-mbp-mailbox.c'), '-o', str(binary)],
                   check=True, capture_output=True, text=True, timeout=30)
    return binary


@pytest.mark.parametrize('case', CASES)
def test_host_transport(mailbox_binary, case):
    env = dict(os.environ, ASAN_OPTIONS='detect_leaks=1:halt_on_error=1',
               UBSAN_OPTIONS='halt_on_error=1:print_stacktrace=1')
    result = subprocess.run([str(mailbox_binary), case], env=env, check=True,
                            capture_output=True, text=True, timeout=5)
    assert result.stdout == 'HOST_TEST diagnostic_only=1 original_mcu_executed=0\n'
    assert result.stderr == ''


def test_all_modes_with_original_aarch64_libc(tmp_path):
    guest = ROOT / 'runtime/analysis/menu-root'
    qemu = ROOT / 'runtime/sources/qemu-11.1.2/build-user/qemu-aarch64'
    if not shutil.which('clang') or not qemu.is_file():
        pytest.skip('original-libc execution needs clang and prepared QEMU user mode')
    binary = tmp_path / 'mailbox-original-libc'
    sources = [HERE.parent / 'lif-capability-owner/original-abi-entry.c',
               HERE / 'mbp-mailbox.c', HERE / 'test-mbp-mailbox.c']
    libraries = [guest / 'lib' / name for name in (
        'libc-2.25.so', 'libdl-2.25.so', 'libpthread-2.25.so', 'ld-2.25.so')]
    subprocess.run(['clang', '--target=aarch64-linux-gnu', '-fuse-ld=lld', '-nostdlib',
                    '-std=c11', '-O2', '-mno-outline-atomics', '-ffunction-sections',
                    '-fdata-sections', '-Wall', '-Wextra', '-Werror', '-pedantic',
                    '-Wl,--no-undefined', '-Wl,--gc-sections',
                    '-isystem', '/usr/aarch64-linux-gnu/include', '-Wl,-e,_start',
                    '-Wl,--dynamic-linker=/lib/ld-linux-aarch64.so.1',
                    *(str(path) for path in sources + libraries), '-o', str(binary)],
                   check=True, capture_output=True, text=True, timeout=30)
    env = {key: value for key, value in os.environ.items()
           if not key.startswith(('MENU_', 'QEMU_', 'SONY_', 'A7C2_', 'LD_'))}
    for case in CASES:
        result = subprocess.run([str(qemu), '-L', str(guest), str(binary), case],
                                check=True, capture_output=True, text=True,
                                env=env, timeout=30)
        assert result.stdout == 'HOST_TEST diagnostic_only=1 original_mcu_executed=0\n'
        assert result.stderr == '', case


@pytest.fixture(scope='module')
def original():
    path = ROOT / PINS['artifact']
    if not path.is_file():
        pytest.skip('prepared public ALLLANG Imola2 image is absent; source not checked')
    data = image.load_image(path)
    assert type(data) is bytes
    assert len(data) == PINS['artifact_bytes'] == image.IMAGE_BYTES
    assert hashlib.sha256(data).hexdigest() == PINS['artifact_sha256'] == image.IMAGE_SHA256
    return data


@pytest.fixture(scope='module')
def windows(original):
    return {row['id']: (int(row['VA_hex'], 16), image.read_window(
        original, row['bank'], int(row['VA_hex'], 16), row['bytes']))
        for row in PINS['windows']}


@pytest.mark.parametrize('row', PINS['windows'], ids=lambda row: row['id'])
def test_actual_public_source_pin(original, row):
    address, raw = int(row['VA_hex'], 16), int(row['raw_hex'], 16)
    assert image.file_offset(row['bank'], address, row['bytes']) == raw
    window = image.read_window(original, row['bank'], address, row['bytes'])
    assert window == original[raw:raw + row['bytes']]
    assert hashlib.sha256(window).hexdigest() == row['sha256']


def word(window, address):
    base, data = window
    assert base <= address <= base + len(data) - 4 and (address - base) % 4 == 0
    return struct.unpack_from('<I', data, address - base)[0]


def expect_words(window, expected):
    for address, encoding in expected.items():
        assert word(window, address) == encoding, hex(address)


def branch_target(window, address):
    encoded = word(window, address)
    displacement = encoded & 0xffff
    if displacement & 0x8000:
        displacement -= 0x10000
    return address + 4 + displacement * 4


def jump_target(window, address):
    return ((address + 4) & 0xf0000000) | ((word(window, address) & 0x3ffffff) << 2)


def test_source_spu_table_submit_mask_branch_store_order(windows):
    assert struct.unpack('<2I', windows['spu_port_table'][1]) == (0xbf062000, 0xbf072000)
    submit = windows['spu_submit']
    expect_words(submit, {
        0x80175c34: 0x3c028025,  # LUI v0,8025; ADDIU v1,v0,-7a38 -> table 802485c8.
        0x80175c38: 0x244385c8,
        0x80175c4c: 0x309000ff,  # Original input truncation; adapter rejects instead.
        0x80175c5c: 0x2e020002,  # SLTIU s0,2, after truncation.
        0x80175c7c: 0x8e020010,  # LW status +10.
        0x80175c80: 0x24840001,  # Increment attempt count.
        0x80175c84: 0x30420002,  # ANDI v0,2.
        0x80175c88: 0x14400005,  # BNEZ -> submit, not a busy branch.
        0x80175c8c: 0x28830100,  # Delay slot: SLTI attempts,100.
        0x80175c90: 0x1460fffa,  # BNEZ -> status poll.
        0x80175ca0: 0x24020001,
        0x80175ca4: 0xae110000,  # SW command +0.
        0x80175cac: 0xae120004,  # SW argument +4.
        0x80175cb4: 0xae020010,  # Final SW 1 +10.
    })
    assert branch_target(submit, 0x80175c88) == 0x80175ca0
    assert branch_target(submit, 0x80175c90) == 0x80175c7c
    assert 0x80175ca4 < 0x80175cac < 0x80175cb4


def test_source_assert_can_return_and_continue_submit(windows):
    submit, tail = windows['spu_submit'], windows['spu_submit_full']
    expect_words(submit, {0x80175c98: 0x5040000b, 0x80175c9c: 0x3c048025})
    expect_words(tail, {
        0x80175cd8: 0x0c002b94,  # JAL assertion, not an error return instruction.
        0x80175cdc: 0x24060038,  # Delay slot: assertion line argument.
        0x80175ce0: 0x0805d729,  # J -> first actual command SW.
        0x80175ce4: 0x24020001,  # Delay slot: submitted value =1.
    })
    assert branch_target(submit, 0x80175c98) == 0x80175cc8
    assert jump_target(tail, 0x80175cd8) == 0x8000ae50
    assert jump_target(tail, 0x80175ce0) == 0x80175ca4


def test_source_spu_receive_reads_then_dispatch_then_ack(windows):
    receive = windows['spu_receive']
    expect_words(receive, {
        0x8000b27c: 0x3c02bf06,
        0x8000b280: 0x8c422010,
        0x8000b284: 0x30420008,  # ANDI status,8.
        0x8000b288: 0x104001d7,  # BEQZ -> no-result path outside this pin.
        0x8000b290: 0x3c03bf06,
        0x8000b294: 0x8c632008,
        0x8000b298: 0x3c02bf06,
        0x8000b29c: 0x8c42200c,
        0x8000b328: 0x0c002b94,  # Actual intervening dispatch/assert call path.
        0x8000b340: 0x24020004,
        0x8000b344: 0x3c01bf06,
        0x8000b348: 0xac222010,  # SW 4 status after the reads/call path.
    })
    assert branch_target(receive, 0x8000b288) == 0x8000b9e8
    assert 0x8000b294 < 0x8000b29c < 0x8000b328 < 0x8000b348


def test_source_ram1_two_words_and_ack_delay_slot(windows):
    receive = windows['ram1_receive']
    expect_words(receive, {
        0x80746fcc: 0x3c0abe00,
        0x80746fd0: 0x8d4a0010,
        0x80746fd8: 0x31490008,
        0x80746fdc: 0x15200005,
        0x80746fe0: 0x00c5182b,  # BNEZ delay slot, SLTU bookkeeping.
        0x80746ff4: 0x3c05be00,
        0x80746ff8: 0x8ca50008,
        0x80747000: 0x24030004,
        0x80747008: 0xac850000,  # Actual output command SW +0(a0).
        0x8074700c: 0x3c02be00,
        0x80747010: 0x8c42000c,
        0x80747014: 0xac820004,  # Actual output argument SW +4(a0).
        0x80747018: 0x3c01be00,
        0x8074701c: 0x03e00008,  # JR ra.
        0x80747020: 0xac230010,  # SW 4 +10 in that return's delay slot.
    })
    assert branch_target(receive, 0x80746fdc) == 0x80746ff4
    assert 0x80747008 < 0x80747014 < 0x80747020


def test_source_ram1_reverse_send_final_store_in_jal_delay_slot(windows):
    send = windows['ram1_send']
    expect_words(send, {
        0x80747128: 0x3c09be00,
        0x8074712c: 0x8d290010,
        0x80747134: 0x31280002,
        0x80747138: 0x15000005,
        0x8074713c: 0x00a4182b,  # BNEZ delay slot, SLTU bookkeeping.
        0x80747150: 0x24030001,
        0x80747158: 0x3c01be00,
        0x8074715c: 0xac300000,
        0x80747164: 0x3c01be00,
        0x80747168: 0xac310004,
        0x80747170: 0x3c01be00,
        0x80747174: 0x0c1e70b2,
        0x80747178: 0xac230010,  # Final SW 1 +10 in JAL delay slot.
    })
    assert branch_target(send, 0x80747138) == 0x80747150
    assert jump_target(send, 0x80747174) == 0x8079c2c8
    assert 0x8074715c < 0x80747168 < 0x80747178


def test_pin_scope_and_loader_rejects_unproved_banks(original):
    assert len(PINS['windows']) == PINS['window_count'] == 6
    assert sum(row['bytes'] for row in PINS['windows']) == PINS['window_bytes'] == 880
    assert PINS['component'] == {
        'diagnostic_only': True, 'owned_data_transport': True,
        'original_MCU_executed': False, 'capture_verified': False,
        'scalar_CPU_MMIO_enabled': False,
    }
    for bank, address, size in (('unknown', 0x80175c2c, 4),
                                ('ram0', 0x80746fbc, 4),
                                ('ram1', 0x80175c2c, 4),
                                ('ram0', 0x80175c2c, 0),
                                ('ram1', 0x808bf000, 4),
                                ('ram0', 0x80713fff, 2)):
        with pytest.raises(ValueError):
            image.read_window(original, bank, address, size)
