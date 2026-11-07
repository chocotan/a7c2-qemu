# SPDX-License-Identifier: MIT
"""SOURCE-ONLY candidate: actual Main slices + real owner, external IO/snapshots LAB.

The parent executes strict/SAN checks. This suite supplies no original AP proof.
"""
from pathlib import Path
import hashlib
import subprocess

import pytest

from test_final_graph_observer_wiring import function

HERE = Path(__file__).resolve().parent
CASES = (
    'success', 'input-rejections', 'receive-failure', 'receive-metadata',
    'receive-thread', 'allocator-reuse', 'allocator-return',
    'allocator-live-alias', 'resource-predecessors', 'shared-guard', 'constructor',
    'preset-pair', 'preset-audit-rejections',
)


def main_timecode_source(source):
    """Keep actual bodies; only the host caller-PC value is supplied by the LAB."""
    sent = function(source, 'osal_snd_msg')
    start = sent.index('    if(functional_camera_enabled && id==FULL_BB_TIMECODE_CONTROL_CP && message && real_msg_size)')
    end = sent.index('    if(id==0x92840747u && full_bb_set_mode_enabled && message)', start)
    route = sent[start:end]
    assert route.count('__builtin_return_address(0)') == 1
    freed = function(source, 'osal_free_msg')
    start = freed.index('    if (__atomic_load_n(&functional_bb_timecode_control_used,')
    end = freed.index('    if (__atomic_load_n(&tcin_config_used,', start)
    receive = function(source, 'native_cp_state_received')
    receive = receive[:receive.index('    if((!cp_owned_state_enabled')] + '}\n'
    start_init = source.index('    functional_camera_enabled=same_name(functional_profile,FCAM_PROFILE)')
    end_init = source.index('    if(functional_profile){', start_init)
    hash_start = source.index('static uint64_t native_ou_crank_hash(')
    hash_end = source.index('\n}', hash_start) + 2
    shared = function(source, 'tracked_native_reserve_resources')
    shared = shared[shared.index('    static const char *const prefixes[]='):shared.index('    if(adf!=36 && __atomic_load_n(&functional_cp_ou_crank_control_used,')]
    snippets = {
        '/* ACTUAL_MAIN_TC_SHARED_GUARD */': shared,
        '/* ACTUAL_MAIN_HELPERS */': '\n'.join((
            source[hash_start:hash_end],
            function(source, 'functional_bb_timecode_reserve_resources'),
            function(source, 'functional_bb_timecode_predecessors_ready'),
            function(source, 'native_bb_timecode_input_audit'),
            function(source, 'native_bb_timecode_preset_input_audit'),
            function(source, 'native_tracked_allocate_msg'), receive,
        )),
        '/* ACTUAL_MAIN_ROUTE */': route.replace('__builtin_return_address(0)', 'fixture_caller'),
        '/* ACTUAL_MAIN_FREE */': freed[start:end],
        '/* ACTUAL_MAIN_INIT */': source[start_init:end_init],
    }
    initial = ('    native_real_allocate_msg = real_dlsym((void *)-1, "osal_valloc_msg_wait");\n'
               '    real_allocate_msg = native_real_allocate_msg ? native_tracked_allocate_msg : 0;')
    dynamic = ('    if (symbol && same_name(name, "osal_valloc_msg_wait")) {\n'
               '        native_real_allocate_msg = symbol;\n'
               '        real_allocate_msg = native_tracked_allocate_msg;\n'
               '        return osal_valloc_msg_wait;\n'
               '    }')
    assert function(source, 'initialize').count(initial) == 1
    assert source.count(dynamic) == 1
    snippets['/* ACTUAL_INITIAL_ALLOCATOR_BINDING */'] = initial.splitlines()[1]
    snippets['/* ACTUAL_DYNAMIC_ALLOCATOR_BINDING */'] = dynamic.splitlines()[2]
    code = (HERE / 'test-main-bb-timecode-wiring.c').read_text()
    provenance = ['Main SHA256: ' + hashlib.sha256(source.encode()).hexdigest(),
                  'LAB normalization: route return PC replaced by fixture_caller; external IO/snapshots mocked',
                  'LAB slices: TC receive prefix, TC+old-BB free blocks, full TC predicates/resource37 wrapper',
                  'Full shared resource guard and original AP are outside this harness']
    for marker, snippet in snippets.items():
        assert code.count(marker) == 1 and snippet, marker
        provenance.append(marker.strip('/* ') + ' SHA256: ' + hashlib.sha256(snippet.encode()).hexdigest())
        code = code.replace(marker, snippet)
    return '/* ' + '\n * '.join(provenance) + ' */\n' + code


@pytest.fixture(scope='module', params=['strict', 'asan-ubsan'])
def main_timecode_binary(tmp_path_factory, request):
    code = main_timecode_source((HERE / 'menu-observe.c').read_text())
    folder = tmp_path_factory.mktemp('actual-main-timecode-' + request.param)
    path, binary = folder / 'actual.c', folder / 'actual'
    path.write_text(code)
    flags = ['-std=c11', '-O1', '-g', '-Wall', '-Wextra', '-Werror', '-pedantic', '-pthread']
    if request.param == 'asan-ubsan':
        flags += ['-fsanitize=address,undefined', '-fno-sanitize-recover=all',
                  '-fno-omit-frame-pointer', '-fno-pie', '-no-pie']
    result = subprocess.run(['cc', *flags, '-I', str(HERE), str(path),
                             str(HERE / 'device-models/bb-timecode-control.c'), '-o', str(binary)],
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
    return binary


@pytest.mark.parametrize('case', CASES)
def test_actual_main_timecode_paths(main_timecode_binary, case):
    result = subprocess.run([str(main_timecode_binary), case], capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, f'{case}: {result.stdout}\n{result.stderr}'
    assert result.stdout == 'PASS actual Main timecode slices + real owner LAB; original AP/CP/physical/capture unverified\n'
    assert not result.stderr
