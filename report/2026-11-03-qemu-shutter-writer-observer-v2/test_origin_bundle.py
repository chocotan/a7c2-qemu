from pathlib import Path
import json
import sys
import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import writer_origin_bundle as bundle
import writer_origin_trace as trace
from origin_fixtures import seed_evidence


def verify(path, manifest):
    path.write_text(json.dumps(manifest))
    return bundle.verify_actual_api(path, bundle.digest(path.read_bytes()), 'a' * 64,
                                   manifest['commands'][0]['elf_sha256'])


def test_all_four_cases_require_matching_dso_origin_and_writer_content(tmp_path):
    path, manifest = seed_evidence(tmp_path / 'evidence')
    result = verify(path, manifest)
    assert [(row['writer_callbacks'], row['origin_callbacks']) for row in result['cases'].values()] == [
        (9, 6), (0, 6), (9, 3), (0, 0)]


@pytest.mark.parametrize('field,value', [('qemu_sha256', 'b' * 64), ('plugin_sha256', 'b' * 64),
    ('primary_sha256', 'b' * 64), ('returncode', 1), ('returncode', False), ('timed_out', True),
    ('signals_sent', 15), ('QMP_calls', 2), ('QMP_calls', False), ('CPU_readback_verified', False),
    ('writer_callbacks', 0), ('origin_callbacks', 0), ('origin_callbacks', True), ('elf_sha256', 'c' * 64)])
def test_failed_or_substituted_actual_api_command_refused(tmp_path, field, value):
    path, manifest = seed_evidence(tmp_path / 'evidence')
    manifest['commands'][0][field] = value
    with pytest.raises(ValueError):
        verify(path, manifest)


@pytest.mark.parametrize('field', ['Sony_guest_run', 'normal_writer_runtime_observed', 'AP_identity_verified',
    'invocation_pairing_verified', 'store_retirement_verified', 'capture_verified', 'physical_asic_compatibility_verified'])
def test_api_manifest_cannot_promote_camera_identity_or_capture(tmp_path, field):
    path, manifest = seed_evidence(tmp_path / 'evidence')
    manifest[field] = True
    with pytest.raises(ValueError):
        verify(path, manifest)


def test_missing_case_duplicate_json_digest_and_cpu_content_refused(tmp_path):
    path, manifest = seed_evidence(tmp_path / 'evidence')
    for commands in (manifest['commands'][:-1], manifest['commands'] + [manifest['commands'][0]]):
        with pytest.raises(ValueError):
            verify(path, dict(manifest, commands=commands))
    path.write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match='digest differs'):
        bundle.verify_actual_api(path, '0' * 64, 'a' * 64, manifest['commands'][0]['elf_sha256'])
    raw = json.dumps(manifest).replace('"returncode": 0', '"returncode": 0, "returncode": 0', 1).encode()
    path.write_bytes(raw)
    with pytest.raises(ValueError, match='duplicate'):
        bundle.verify_actual_api(path, bundle.digest(raw), 'a' * 64, manifest['commands'][0]['elf_sha256'])
    console = path.parent / 'original/console.bin'
    console.write_bytes(b'ORIGIN_V2_CPU_READBACK_FAIL\n')
    result_path = console.with_name('content-result.json')
    result = json.loads(result_path.read_text())
    result['console_sha256'] = bundle.digest(console.read_bytes())
    result_path.write_text(json.dumps(result))
    with pytest.raises(ValueError, match='CPU independent readback'):
        verify(path, manifest)


def test_control_cannot_add_a_matched_candidate_or_relabel_parsed_flags(tmp_path):
    path, manifest = seed_evidence(tmp_path / 'evidence')
    folder = path.parent / 'short-tb'
    log = folder / 'readonly-shutter-writer.log'
    rows = trace.fields(log.read_bytes())
    rows[-1].update(candidate_found='0x1', candidate_base='0x40000000')
    raw = trace.wire(rows)
    log.write_bytes(raw)
    result_path = folder / 'content-result.json'
    result = json.loads(result_path.read_text())
    result.update(writer_trace_sha256=bundle.digest(raw), observed=trace.parse_trace(raw))
    result_path.write_text(json.dumps(result))
    with pytest.raises(ValueError, match='negative fixture was matched'):
        verify(path, manifest)


def test_parsed_origin_values_and_boolean_claims_must_equal_raw_trace(tmp_path):
    path, manifest = seed_evidence(tmp_path / 'evidence')
    result_path = path.parent / 'original/content-result.json'
    original = json.loads(result_path.read_text())
    for mutate in (lambda row: row['observed']['origins'][0]['registers'].update(x2=99),
                   lambda row: row['observed'].update(capture_verified=0)):
        changed = json.loads(json.dumps(original))
        mutate(changed)
        result_path.write_text(json.dumps(changed))
        with pytest.raises(ValueError, match='parsed content differs'):
            verify(path, manifest)
