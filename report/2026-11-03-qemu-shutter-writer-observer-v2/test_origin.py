"""Self-owned register/instruction mocks only; original camera execution is separate."""
from pathlib import Path
import importlib.util
import os
import re
import subprocess
import sys
import pytest

HERE = Path(__file__).resolve().parent
NATIVE = HERE.parents[1]
HEADER = NATIVE / 'source/build/qemu-SRBXNK/qemu-11.1.2/include/plugins/qemu-plugin.h'
sys.path.insert(0, str(HERE))
spec = importlib.util.spec_from_file_location('writer_origin_v2_trace', HERE / 'writer_origin_trace.py')
trace = importlib.util.module_from_spec(spec)
spec.loader.exec_module(trace)
FAULTS = {17, 18, 19, 20, 21, 22, 23, 25, 26, 98, 99, 103, 104}
QEMU_IMPORTS = {'qemu_plugin_' + name for name in (
    'get_registers', 'read_register', 'register_vcpu_init_cb', 'register_vcpu_tb_trans_cb',
    'register_atexit_cb', 'tb_n_insns', 'tb_get_insn', 'insn_vaddr', 'insn_size', 'insn_data',
    'register_vcpu_insn_exec_cb')}


def run(command, **kwargs):
    result = subprocess.run(command, capture_output=True, timeout=30, **kwargs)
    assert result.returncode == 0, result.stdout.decode(errors='replace') + result.stderr.decode(errors='replace')
    return result


@pytest.fixture(scope='session', params=(False, True), ids=('strict-C11', 'ASan-UBSan'))
def executable(tmp_path_factory, request):
    directory = tmp_path_factory.mktemp('writer-v2-host-' + str(request.param))
    binary = directory / 'check-writer'
    flags = subprocess.check_output(['pkg-config', '--cflags', '--libs', 'glib-2.0'], text=True).split()
    command = ['cc', '-std=c11', '-Wall', '-Wextra', '-Werror', '-pedantic', '-DHOST_MOCK',
               '-I' + str(HEADER.parent), str(HERE / 'test-writer.c'), '-o', str(binary), *flags]
    if request.param:
        command[1:1] = ['-fsanitize=address,undefined', '-fno-omit-frame-pointer', '-g']
    run(command)
    return binary


@pytest.mark.parametrize('scenario', range(105))
def test_actual_readonly_callback_and_strict_parser(executable, tmp_path, scenario):
    log = tmp_path / 'trace.log'
    run([str(executable), str(scenario), str(log)], env=dict(os.environ,
        ASAN_OPTIONS='detect_leaks=1:halt_on_error=1', UBSAN_OPTIONS='halt_on_error=1'))
    raw = log.read_bytes()
    if scenario in FAULTS:
        with pytest.raises(ValueError):
            trace.parse_trace(raw)
        return
    result = trace.parse_trace(raw)
    assert result['capture_verified'] is False and result['AP_identity_verified'] is False
    assert result['invocation_pairing_verified'] is False and result['store_retirement_verified'] is False
    assert result['original_predecessor_edge_verified'] is False
    if scenario in (28, 102):
        assert [event['site'] for event in result['origins']] == list(trace.ORIGINS)
        assert [event['selector_u32'] for event in result['origins']] == [0x17c, 0x17c]
        assert [event['value_u32'] for event in result['origins']] == [1, 1]
        assert [event['observation_sequence'] for event in result['origins']] == [1, 2]
        assert [event['kind'] for event in result['observation_order']] == ['writer_origin'] * 2 + ['shutter_writer'] * 3
        assert len(result['events']) == 3
        if scenario == 102:
            assert all(value is None for event in result['origins'] for value in event['context'].values())
    elif 29 <= scenario <= 97:
        assert not result['origins'] and result['origin_anchor_mask'] == 0 and not result['candidate_found']
    elif scenario == 100:
        assert not result['origins'] and result['origin_filtered_counts']['dispatch_entry'] == 1
        assert result['origin_suppressed_counts']['dispatch_entry'] == 0
    elif scenario == 101:
        assert len(result['origins']) == 16 and result['origin_suppressed_counts']['dispatch_entry'] == 2
        assert result['truncated_by_quota'] is True
    else:
        assert not result['origins']


def test_parser_rejects_corrupt_order_claims_anchor_filter_and_terminal(executable, tmp_path):
    log = tmp_path / 'good.log'
    run([str(executable), '28', str(log)])
    raw = log.read_bytes()
    assert trace.parse_trace(raw)['origin_site_counts'] == dict.fromkeys(trace.ORIGINS, 1)
    mutations = (
        lambda rows: rows[0].update(schema='readonly_shutter_writer_v1'),
        lambda rows: rows[1].update(selector_u32='0x17d'),
        lambda rows: rows[1].update(anchor_length='0x20'),
        lambda rows: rows[1].update(observation_sequence='0x2'),
        lambda rows: rows[1].update(invocation_pairing_verified='0x1'),
        lambda rows: rows[1].update(x2_read_length='0x7'),
        lambda rows: rows[1].update(x3_api_ok='0x0'),
        lambda rows: rows[1].update(candidate_base='0x5500001000'),
        lambda rows: rows[1].update(capture='0x1'),
        lambda rows: rows[1].update(extra='0x0'),
        lambda rows: rows[2].update(origin_sequence='0x1'),
        lambda rows: rows[3].update(observation_sequence='0x1'),
        lambda rows: rows[-1].update(observation_sequence='0x4'),
        lambda rows: rows[-1].update(origin0_records='0x2'),
        lambda rows: rows[-1].update(origin0_suppressed='0x1'),
        lambda rows: rows[-1].update(origin_anchor_mask='0x2'),
        lambda rows: rows[-1].update(origin_base='0x5500001000'),
    )
    for mutate in mutations:
        rows = trace.fields(raw)
        mutate(rows)
        with pytest.raises(ValueError):
            trace.parse_trace(trace.wire(rows))
    for malformed in (raw[:-1], raw.replace(b'vcpu=0x0', b'vcpu=0x0 vcpu=0x0', 1),
                      raw.replace(b'\n', b'\r\n', 1)):
        with pytest.raises(ValueError):
            trace.parse_trace(malformed)


def test_production_plugin_uses_exact_readonly_eleven_imports(tmp_path):
    library = tmp_path / 'observer.so'
    flags = subprocess.check_output(['pkg-config', '--cflags', '--libs', 'glib-2.0'], text=True).split()
    run(['cc', '-std=c11', '-Wall', '-Wextra', '-Werror', '-pedantic', '-O2', '-fPIC', '-shared',
         '-I' + str(HEADER.parent), str(HERE / 'scope-observer.c'), '-o', str(library), *flags])
    symbols = run(['nm', '-D', '--undefined-only', str(library)]).stdout.decode()
    imports = set(re.findall(r'\b(qemu_plugin_\w+)\b', symbols))
    assert imports == QEMU_IMPORTS
    source = (HERE / 'scope-observer.c').read_text()
    assert 'QEMU_PLUGIN_CB_R_REGS' in source and 'QEMU_PLUGIN_CB_RW_REGS' not in source
