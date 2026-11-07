from pathlib import Path
import copy
import json
import sys

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import writer_bundle as bundle
from test_writer_trace import encode, fixture_rows


def seed_evidence(root):
    root.mkdir()
    commands = []
    for case in ('original', 'equivalent-mutation', 'short-tb'):
        path = root / case
        path.mkdir()
        if case == 'original':
            rows = fixture_rows()
            events = []
            for invocation, value in enumerate((1, 0, 0xffffffff), 1):
                for site in range(3):
                    row = dict(rows[site + 1], ordinal=hex(invocation), writer_sequence=hex(len(events) + 1),
                               x0_raw=hex(value), input_w0=hex(value))
                    events.append(row)
            end = dict(rows[-1], site0_records='0x3', site1_records='0x3', site2_records='0x3', writer_sequence='0x9')
            trace = encode([rows[0], *events, end])
        else:
            rows = fixture_rows()
            end = dict(rows[-1], candidate_found='0x0', candidate_base='0x0', anchor_seen_mask='0x0',
                       site0_records='0x0', site1_records='0x0', site2_records='0x0', writer_sequence='0x0')
            trace = encode([rows[0], end])
        console = b'WRITER_CPU_READBACK_PASS values=1,0,ffffffff\n'
        elf = b'self-owned ELF fixture bytes: ' + case.encode()
        for name, raw in (('plugin.log', trace), ('console.bin', console), ('fixture.elf', elf)):
            (path / name).write_bytes(raw)
        count = 9 if case == 'original' else 0
        result = dict(CPU_readback_verified=True, plugin_callbacks=count, trace_sha256=bundle.digest(trace),
                      console_sha256=bundle.digest(console), capture_verified=False)
        (path / 'content-result.json').write_text(json.dumps(result))
        commands.append(dict(case=case, qemu_sha256=bundle.QEMU_SHA256, plugin_sha256='a' * 64,
            returncode=0, timed_out=False, signals_sent=0, QMP_calls=0, CPU_readback_verified=True,
            plugin_callbacks=count, elf_sha256=bundle.digest(elf)))
    manifest = dict(status='PASS_SELF_OWNED_WRITER_ACTUAL_QEMU_API_NOT_SONY_RUNTIME_OR_PROFILE_ADMISSION',
        returncode=0, QEMU_actual_API_run=True, Sony_guest_run=False, normal_writer_runtime_observed=False,
        profile_admitted=False, capture_verified=False, physical_asic_compatibility_verified=False, commands=commands)
    path = root / 'terminal.json'
    path.write_text(json.dumps(manifest))
    return path, manifest


def verify(path, manifest):
    path.write_text(json.dumps(manifest))
    fixture_sha = manifest['commands'][0]['elf_sha256']
    return bundle.verify_actual_api(path, bundle.digest(path.read_bytes()), 'a' * 64, fixture_sha)


def test_all_three_fixtures_require_matching_dso_content_and_real_counter_shapes(tmp_path):
    path, manifest = seed_evidence(tmp_path / 'evidence')
    result = verify(path, manifest)
    assert set(result['cases']) == {'original', 'equivalent-mutation', 'short-tb'}
    assert result['cases']['original']['callbacks'] == 9
    assert result['cases']['short-tb']['callbacks'] == 0


@pytest.mark.parametrize('field,value', [('qemu_sha256', 'b' * 64), ('plugin_sha256', 'b' * 64),
    ('returncode', 1), ('returncode', False), ('timed_out', True), ('signals_sent', 15),
    ('QMP_calls', 2), ('CPU_readback_verified', False), ('plugin_callbacks', 0), ('elf_sha256', 'c' * 64)])
def test_failed_or_substituted_actual_api_command_is_refused(tmp_path, field, value):
    path, manifest = seed_evidence(tmp_path / 'evidence')
    manifest['commands'][0][field] = value
    with pytest.raises(ValueError):
        verify(path, manifest)


@pytest.mark.parametrize('field', ['Sony_guest_run', 'normal_writer_runtime_observed',
                                 'profile_admitted', 'capture_verified', 'physical_asic_compatibility_verified'])
def test_actual_api_manifest_cannot_promote_camera_identity_or_capture(tmp_path, field):
    path, manifest = seed_evidence(tmp_path / 'evidence')
    manifest[field] = True
    with pytest.raises(ValueError):
        verify(path, manifest)


def test_missing_case_duplicate_key_digest_and_cpu_readback_mismatch_refused(tmp_path):
    path, manifest = seed_evidence(tmp_path / 'evidence')
    for commands in (manifest['commands'][:-1], manifest['commands'] + [manifest['commands'][0]]):
        wrong = dict(manifest, commands=commands)
        with pytest.raises(ValueError):
            verify(path, wrong)
    path.write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match='digest differs'):
        bundle.verify_actual_api(path, '0' * 64, 'a' * 64, manifest['commands'][0]['elf_sha256'])
    raw = json.dumps(manifest).replace('"returncode": 0', '"returncode": 0, "returncode": 0', 1).encode()
    path.write_bytes(raw)
    with pytest.raises(ValueError, match='duplicate'):
        bundle.verify_actual_api(path, bundle.digest(raw), 'a' * 64, manifest['commands'][0]['elf_sha256'])
    console = path.parent / 'original/console.bin'
    console.write_bytes(b'WRITER_CPU_READBACK_FAIL\n')
    result_path = console.with_name('content-result.json')
    result = json.loads(result_path.read_text())
    result['console_sha256'] = bundle.digest(console.read_bytes())
    result_path.write_text(json.dumps(result))
    with pytest.raises(ValueError, match='CPU content readback'):
        verify(path, manifest)


def test_negative_trace_cannot_add_a_matched_candidate(tmp_path):
    path, manifest = seed_evidence(tmp_path / 'evidence')
    trace_path = path.parent / 'short-tb/plugin.log'
    raw = trace_path.read_bytes().replace(b'candidate_found=0x0 candidate_base=0x0',
                                         b'candidate_found=0x1 candidate_base=0x40000000')
    trace_path.write_bytes(raw)
    result_path = trace_path.with_name('content-result.json')
    result = json.loads(result_path.read_text())
    result['trace_sha256'] = bundle.digest(raw)
    result_path.write_text(json.dumps(result))
    with pytest.raises(ValueError, match='negative fixture was matched'):
        verify(path, manifest)
