# SPDX-License-Identifier: MIT
"""Synthetic HOST TEST records only; these tests provide no native-kernel proof."""
import ctypes
from pathlib import Path
import shutil
import struct
import subprocess

import pytest

MODELS = Path(__file__).resolve().parent / 'device-models'
SOURCE = MODELS / 'hdmi-upm-receipt.c'
FLAGS = ['-std=c11', '-Wall', '-Wextra', '-Werror', '-pedantic', '-pthread']
TEST = '-DFULL_HDMI_UPM_RECEIPT_TEST'
ERROR = -1021


def seal(record):
    value = 0xcbf29ce484222325
    for octet in record[:20] + record[24:152] + record[160:]:
        value = ((value ^ octet) * 0x100000001b3) & ((1 << 64) - 1)
    struct.pack_into('<Q', record, 152, value)
    return bytes(record)


def host_test_record(index=0, allocator=0x4720):
    data = bytearray(256)
    upm, osal = 0xffffff8001000000, 0xffffff8001100000
    fields = {
        0: ('IIQIIQQ', (0x4d505548, 1, 0x123456789abcdef0, 321, 3, 4 + index, 0x7f001018)),
        40: ('4I', (0x00920117, index * 2, 0x009a0000, 0)),
        56: ('4I', (0x00920117, index * 3, 0x009a0000, 0)),
        72: ('QQIiIIII', (0xffffff8002001018, 0xffffff800a00b000, 83, 0, 1, 1, 0x7f, index)),
        112: ('4QII', (upm + 0x126e8, upm + 0x14c, 0x7f000000, 0xffffff8002000000, 321, 0)),
        160: ('QQ4I4Q', (upm, osal, 0x909a015a, 0x80920572, 16, 0x009a0000,
                               osal + allocator, 2 + index * 20, 12 + index * 20, 0xffffff800b00a000)),
    }
    for offset, (fmt, values) in fields.items():
        struct.pack_into('<' + fmt, data, offset, *values)
    return seal(data)


@pytest.fixture(scope='module')
def validator(tmp_path_factory):
    directory = tmp_path_factory.mktemp('hdmi-upm-receipt')
    library = directory / 'receipt.so'
    subprocess.run(['cc', *FLAGS, TEST, '-shared', '-fPIC', str(SOURCE), '-o', str(library)], check=True)
    function = ctypes.CDLL(str(library)).full_hdmi_upm_receipt_validate
    function.argtypes = (ctypes.c_void_p, ctypes.c_size_t, ctypes.c_void_p)
    function.restype = ctypes.c_int

    def validate(record, expected=None):
        snapshot = None if record is None else ctypes.create_string_buffer(record)
        expectation = ctypes.create_string_buffer(expected if expected is not None else host_test_record())
        return function(snapshot, 0 if record is None else len(record), expectation)
    return validate


@pytest.mark.parametrize('index', [0, 1])
@pytest.mark.parametrize('allocator', [0x4720, 0x4768, 0x478c])
def test_positive_host_records(validator, index, allocator):
    record = host_test_record(index, allocator)
    assert validator(record, record) == 0


@pytest.mark.parametrize('offset,fmt,value', [
    (0, 'I', 0), (4, 'I', 2), (8, 'Q', 1), (16, 'I', 322), (20, 'I', 2),
    (24, 'Q', 3), (32, 'Q', 0x7f001020), (40, 'I', 0x920116), (44, 'I', 2),
    (48, 'I', 0), (52, 'I', 1), (56, 'I', 0), (60, 'I', 3), (64, 'I', 0), (68, 'I', 1),
    (72, 'Q', 0xffffff8002001020), (72, 'Q', 0x1234), (80, 'Q', 0),
    (80, 'Q', 0xffffff800b00a000), (88, 'I', 0), (88, 'I', 321), (88, 'I', 0x80000000),
    (92, 'i', -1), (96, 'I', 0), (96, 'I', 2), (100, 'I', 0), (100, 'I', 2),
    (104, 'I', 0x3f), (104, 'I', 0xff), (108, 'I', 1), (108, 'I', 2),
    (112, 'Q', 0xffffff80010126ec), (120, 'Q', 0xffffff8001000148),
    (128, 'Q', 0x7f001020), (128, 'Q', 0x7f001018), (128, 'Q', 0x7edff018),
    (128, 'Q', 0x7f000001), (136, 'Q', 0), (136, 'Q', 0xffffff8002000008),
    (144, 'I', 322), (148, 'I', 1), (160, 'Q', 0xffffff8001001000), (168, 'Q', 0),
    (176, 'I', 0), (180, 'I', 0), (184, 'I', 0), (184, 'I', 15), (188, 'I', 0),
    (192, 'Q', 0xffffff8001104650), (200, 'Q', 0), (200, 'Q', 12), (208, 'Q', 2),
    (216, 'Q', 0), (216, 'Q', 0xffffff800a00b000), (224, 'Q', 1), (255, 'B', 1),
])
def test_rejects_invalid_proof_even_with_recomputed_digest(validator, offset, fmt, value):
    bad = bytearray(host_test_record())
    struct.pack_into('<' + fmt, bad, offset, value)
    assert validator(seal(bad)) == ERROR


@pytest.mark.parametrize('length', [0, 1, 20, 152, 255, 257, 4096])
def test_rejects_wrong_snapshot_capacity(validator, length):
    assert validator((host_test_record() + bytes(4096))[:length]) == ERROR


def test_rejects_null_corrupt_digest_and_old_transaction(validator):
    assert validator(None) == ERROR
    bad = bytearray(host_test_record())
    bad[152] ^= 1
    assert validator(bytes(bad)) == ERROR
    assert validator(host_test_record(0), host_test_record(1)) == ERROR
    assert validator(host_test_record(1), host_test_record(0)) == ERROR


def test_c11_sanitizers_and_production_symbols(tmp_path):
    # The executable consumes exactly the independent Python wire fixture.
    fixture = tmp_path / 'host-test.bin'
    fixture.write_bytes(host_test_record())
    main = tmp_path / 'host-test.c'
    main.write_text('''#include "hdmi-upm-receipt.h"
#include <assert.h>
#include <stdio.h>
#include <string.h>
int main(int argc,char **argv) {
    struct full_hdmi_upm_mailbox r; unsigned char short_record[1]={0};
    assert(argc==2); FILE *f=fopen(argv[1],"rb"); assert(f);
    assert(fread(&r,1,sizeof r,f)==sizeof r); assert(!fclose(f));
    assert(!full_hdmi_upm_receipt_validate(&r,sizeof r,&r));
    assert(full_hdmi_upm_receipt_validate(short_record,1,&r)==-1021);
    assert(full_hdmi_upm_receipt_validate(NULL,sizeof r,&r)==-1021);
    assert(full_hdmi_upm_receipt_validate(&r,sizeof r,NULL)==-1021);
    struct full_hdmi_upm_mailbox bad=r; bad.free_rc=-1;
    assert(full_hdmi_upm_receipt_validate(&bad,sizeof bad,&r)==-1021);
    puts("synthetic HOST TEST only: C11 ASan/UBSan receipt reader passed");
    return 0;
}
''', encoding='ascii')
    binary = tmp_path / 'host-test'
    subprocess.run(['cc', *FLAGS, TEST, '-fsanitize=address,undefined', '-fno-omit-frame-pointer',
                    '-fno-pie', '-no-pie', '-I', str(MODELS), str(SOURCE), str(main), '-o', str(binary)], check=True)
    subprocess.run([str(binary), str(fixture)], check=True, timeout=5)
    production = tmp_path / 'production.o'
    subprocess.run(['cc', *FLAGS, '-c', str(SOURCE), '-o', str(production)], check=True)
    symbols = subprocess.run(['nm', '-g', str(production)], check=True, capture_output=True, text=True).stdout
    assert 'full_hdmi_upm_receipt_validate' not in symbols
    assert not any(name in symbols for name in [' munmap', ' free', 'observe_receive', 'video_state'])


def test_aarch64_strict_compile(tmp_path):
    compiler = shutil.which('aarch64-linux-gnu-gcc')
    if compiler is None:
        pytest.skip('AArch64 compiler unavailable')
    subprocess.run([compiler, *FLAGS, '-c', str(SOURCE), '-o', str(tmp_path / 'guest.o')], check=True)
