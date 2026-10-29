"""BB0110 with actual 0323/0336/032d host owners; no original AP/capture claim."""
from pathlib import Path
import os
import subprocess
import pytest
from test_adf_set_output_device import BACKENDS
from test_adf_set_input_device import public_adf_input_seed
HERE=Path(__file__).resolve().parent
MODEL=HERE/'device-models'
CASES=['normal','dynamic-caller','disabled','invalid','uninitialized','fork','no-prior',
       'unknown-prefix','plane-prefix','unknown-large-prefix','reserve-fail','alloc-rc','alloc-null','alloc-size','alloc-alias',
       'set-source','prefix-during-source','send-fail','request-free-fail','inline-free',
       'wrong-owner','reply-free-fail','in-flight-send-fail','in-flight-free-fail']
@pytest.fixture(scope='module')
def bb_binary(tmp_path_factory):
    binary=tmp_path_factory.mktemp('bb-mode-composed')/'model'
    built=subprocess.run(['cc','-std=c11','-Wall','-Wextra','-Werror','-pedantic','-g','-pthread',
        '-fsanitize=address,undefined','-fno-omit-frame-pointer','-no-pie',
        '-DFULL_ADF_PROC_TEST','-DFULL_ADF_SET_INPUT_TEST','-DFULL_ADF_SET_OUTPUT_TEST',
        '-Wl,--wrap=full_adf_set_input_claim_output',
        *[str(MODEL/(name+'.c')) for name in BACKENDS],str(MODEL/'test-bb-set-mode-device.c'),
        '-o',str(binary)],capture_output=True,text=True,timeout=40)
    assert built.returncode==0,built.stdout+built.stderr
    return binary
@pytest.mark.parametrize('case',CASES)
def test_bb_mode_composed(bb_binary,public_adf_input_seed,case):
    if public_adf_input_seed is None:pytest.skip('pinned official ALLLANG seed required')
    result=subprocess.run([str(bb_binary),case,str(public_adf_input_seed)],
        capture_output=True,text=True,timeout=15,env=dict(os.environ,
        ASAN_OPTIONS='detect_leaks=1:abort_on_error=1',UBSAN_OPTIONS='halt_on_error=1'))
    assert result.returncode==0,result.stdout+result.stderr
    if case not in ('disabled','invalid','uninitialized','fork','unknown-prefix','unknown-large-prefix'):
        assert 'BB_SET_MODE_HOST_TEST_PASS' in result.stdout
    if case in ('in-flight-send-fail','in-flight-free-fail'):
        first_rc,attempts=(-49,2) if case=='in-flight-free-fail' else (0,1)
        assert (f'BB_SET_MODE_IN_FLIGHT_PASS: dispatch_rc=0 first_free_rc={first_rc} '
                f'attempts={attempts} ap_consumed=1 clean_completion=0 '
                'owned_request_recovered=1') in result.stdout
        assert 'FULL_BB_SET_MODE_REPLY_QUEUED ' not in result.stdout
        assert 'FULL_BB_SET_MODE_COMMIT ' not in result.stdout
        assert 'FULL_BB_SET_MODE_RECOVERY_FREE ' in result.stdout
    if case in ('normal','dynamic-caller','inline-free','plane-prefix'):
        assert 'FULL_ADF_SET_OUTPUT_REPLY_FREE ' in result.stdout
        assert 'FULL_BB_SET_MODE_REPLY_FREE ' in result.stdout
