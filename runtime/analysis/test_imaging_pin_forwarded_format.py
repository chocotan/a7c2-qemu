"""Same first owner accepts only mapped forwarded format; no VM/frame evidence."""
# SPDX-License-Identifier: MIT
from pathlib import Path
import os
import subprocess

import pytest

from test_adf_set_output_device import BACKENDS as BB_BACKENDS
from test_adf_set_input_device import public_adf_input_seed

HERE = Path(__file__).resolve().parent
MODEL = HERE / 'device-models'


@pytest.fixture(scope='module')
def forwarded_format_binary(tmp_path_factory):
    binary = tmp_path_factory.mktemp('imaging-pin-forwarded-format') / 'model'
    backends = [*BB_BACKENDS, 'pin-buffer-owner', 'pin-registry-core',
                'infraimaging-format', 'imaging-pin-connection']
    result = subprocess.run([
        'cc', '-std=c11', '-Wall', '-Wextra', '-Werror', '-pedantic', '-g', '-pthread',
        '-fsanitize=address,undefined', '-fno-omit-frame-pointer', '-no-pie',
        '-DFULL_ADF_PROC_TEST', '-DFULL_ADF_SET_INPUT_TEST', '-DFULL_ADF_SET_OUTPUT_TEST',
        '-DPIN_CONTROL_TEST', '-Wl,--wrap=full_adf_set_input_claim_output',
        *[str(MODEL / (name + '.c')) for name in backends],
        str(HERE / 'infrabb-registry.c'),
        str(MODEL / 'test-imaging-pin-forwarded-format.c'), '-o', str(binary),
    ], capture_output=True, text=True, timeout=45)
    assert result.returncode == 0, result.stdout + result.stderr
    return binary


@pytest.mark.parametrize('case', ('uninitialized', 'first-fault', 'not-ap-consumed', 'normal'))
def test_same_first_owner_mapped_forwarded_format(
        forwarded_format_binary, public_adf_input_seed, tmp_path, case):
    if case != 'uninitialized' and public_adf_input_seed is None:
        pytest.skip('provision the pinned public ALLLANG seed first')
    seed = public_adf_input_seed if case != 'uninitialized' else tmp_path / 'absent-seed.bin'
    result = subprocess.run([str(forwarded_format_binary), case, str(seed)],
        capture_output=True, text=True, timeout=25,
        env=dict(os.environ, ASAN_OPTIONS='detect_leaks=1:abort_on_error=1',
                 UBSAN_OPTIONS='halt_on_error=1:print_stacktrace=1'))
    assert result.returncode == 0, result.stdout + result.stderr
    assert not result.stderr, result.stderr
    if case == 'uninitialized':
        assert 'IMAGING_FORWARD_FORMAT_UNINITIALIZED_PASS' in result.stdout
    elif case in ('first-fault', 'not-ap-consumed'):
        assert f'IMAGING_FORWARD_FORMAT_REJECT_{case}_PASS' in result.stdout
        assert 'FULL_IMAGING_PIN_CONNECT_FORWARD_FORMAT_CONSUMED ' not in result.stdout
    else:
        for suffix in ('ACTUAL_MAPPED_READ_SAME_CACHE_FIRST_HISTORY',
                       'REFERENCE_AUTHORITY_DUPLICATE_AND_FORK_PRELOCK',
                       'MALFORMED_BACKING_AND_OLD_VARIANT_PRESERVE_OWNER',
                       'FULL_FLAGS_UNUSED_WORD_CALLER_FREE_NO_RESET'):
            assert f'IMAGING_FORWARD_FORMAT_{suffix}_PASS' in result.stdout
        lines = result.stdout.splitlines()
        assert sum(line.startswith('FULL_IMAGING_PIN_CONNECT_FORMAT_CONSUMED ') for line in lines) == 1
        assert sum(line.startswith('FULL_IMAGING_PIN_CONNECT_COMMIT ') for line in lines) == 1
        forwards = [line for line in lines
                    if line.startswith('FULL_IMAGING_PIN_CONNECT_FORWARD_FORMAT_CONSUMED ')]
        assert len(forwards) == 2
        assert 'cache=1,1,1920,1080,3 payload_fnv64=37228cd728b41c0d consumed=2 forwarded_formats=1' in forwards[0]
        assert 'mapped_backing_read=1 original_cp_executed=0' in forwards[0]
        assert 'frames_verified=0 capture_verified=0' in forwards[0]
