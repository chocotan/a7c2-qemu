"""Host-only validation of saved self-owned API evidence; no QEMU or camera launch."""
from pathlib import Path
from types import SimpleNamespace
import copy
import json
import shutil
import sys

import pytest

HERE = Path(__file__).resolve().parent
NATIVE = HERE.parents[1]
ROOT = NATIVE.parents[3] / 'analysis/scratch/functional-gpo-descriptor-observer-v5-draft-20261104'
sys.path.insert(0, str(HERE))
import writer_descriptor_bundle as bundle
import writer_descriptor_runtime as runtime
import writer_descriptor_contract as contract

API = ROOT / 'actual-api/terminal.json'
BUILD = ROOT / 'authority-build/build-receipt.json'


def evidence_arguments(path=API):
    measured = bundle.object_json(API.read_bytes())
    return path, bundle.digest(path.read_bytes()), measured['library_sha256'], measured['commands'][0]['elf_sha256']


def test_measured_five_case_evidence_and_identical_source9_build_are_consumed():
    result = bundle.verify_actual_api(*evidence_arguments())
    assert list(result['cases']) == ['original', 'equivalent-descriptor-mutation', 'equivalent-record-mutation', 'wrong-row', 'foreign-store-entry', 'short-tb']
    assert result['cases']['original']['origin_callbacks'] == 9
    assert result['cases']['original']['record_callbacks'] == 9
    assert result['cases']['original']['descriptor_callbacks'] == 9
    assert result['cases']['equivalent-descriptor-mutation']['descriptor_callbacks'] == 0
    assert all(result['cases'][case]['record_callbacks'] == 0 for case in ('equivalent-record-mutation', 'wrong-row', 'foreign-store-entry', 'short-tb'))
    receipt = bundle.object_json(BUILD.read_bytes())
    verified = bundle.validate_build(HERE, BUILD, bundle.digest(BUILD.read_bytes()), Path(receipt['qemu']))
    assert verified['source_sha256'] == bundle.source_map(HERE)
    assert verified['profile'] == 'qemu-readonly-shutter-writer-v5'
    assert all(verified[name] is False for name in bundle.FALSE)


@pytest.mark.parametrize('mutation', [
    lambda v: v.update(status='PASS_SELF_OWNED_WRITER_ORIGIN_V2_FOUR_ACTUAL_QEMU_CASES_NOT_SONY_RUNTIME'),
    lambda v: v.update(returncode=True),
    lambda v: v.update(authoritative_installed=True),
    lambda v: v.update(Sony_guest_run=True),
    lambda v: v.update(capture_verified=True),
    lambda v: v.update(library_sha256='0' * 64),
    lambda v: v.update(exact_readonly_imports=v['exact_readonly_imports'][:-1]),
    lambda v: v['commands'].pop(),
    lambda v: v['commands'].__setitem__(1, copy.deepcopy(v['commands'][0])),
    lambda v: v['commands'][0].update(returncode=True),
    lambda v: v['commands'][0].update(outer_timeout=True),
    lambda v: v['commands'][0].update(QMP_calls=1),
    lambda v: v['commands'][0].update(signals_sent=1),
    lambda v: v['commands'][0].update(origin_callbacks=6),
    lambda v: v['commands'][0].update(primary_sha256='0' * 64),
    lambda v: v.update(extra_claim=True),
])
def test_corrupt_manifest_is_refused_before_missing_case_files(tmp_path, mutation):
    value = bundle.object_json(API.read_bytes())
    mutation(value)
    if value.get('commands') and value['commands'][0].get('origin_callbacks') == 6:
        directory = tmp_path / 'original'
        directory.mkdir()
        for name in ('content-result.json', 'record.log', 'primary.log', 'console.bin', 'fixture.elf'):
            shutil.copy2(API.parent / 'original' / name, directory / name)
    target = tmp_path / 'terminal.json'
    target.write_text(json.dumps(value))
    with pytest.raises(ValueError):
        bundle.verify_actual_api(*evidence_arguments(target))


@pytest.mark.parametrize('kind', ['wrong_upstream_value', 'wrong_upstream_selector', 'changed_cpu_console', 'wrong_counter_mask'])
def test_saved_actual_case_raw_and_independent_cpu_readback_cannot_be_substituted(tmp_path, kind):
    manifest = bundle.object_json(API.read_bytes())
    for case in manifest['commands']:
        destination = tmp_path / case['case']
        destination.mkdir()
        for name in ('content-result.json', 'record.log', 'primary.log', 'console.bin', 'fixture.elf'):
            shutil.copy2(API.parent / case['case'] / name, destination / name)
    folder = tmp_path / 'original'
    result = json.loads((folder / 'content-result.json').read_bytes())
    if kind == 'changed_cpu_console':
        data = b'HOST_TEST fabricated success text\n'
        (folder / 'console.bin').write_bytes(data)
        result['console_sha256'] = bundle.digest(data)
    else:
        data = (folder / 'record.log').read_bytes()
        import writer_descriptor_trace as trace
        rows = trace.previous.prior.fields(data)
        if kind == 'wrong_counter_mask':
            rows[-1]['origin_anchor_mask'] = '0x3'
        else:
            row = next(row for row in rows if row.get('site') == 'upstream_entry')
            row['x2_raw' if kind == 'wrong_upstream_value' else 'x1_raw'] = '0x17d'
        data = trace.previous.prior.wire(rows)
        (folder / 'record.log').write_bytes(data)
        result['trace_sha256'] = bundle.digest(data)
    (folder / 'content-result.json').write_text(json.dumps(result))
    target = tmp_path / 'terminal.json'
    target.write_text(json.dumps(manifest))
    with pytest.raises(ValueError):
        bundle.verify_actual_api(*evidence_arguments(target))


def test_default_off_and_unpaired_explicit_profile_refuse_before_file_access():
    assert runtime.stage(Path('/missing'), {}, '/missing-run', '/missing-qemu', None) is None
    for settings in ({runtime.PROFILE_ENV: runtime.PROFILE}, {runtime.BUILD_ENV: '/missing'},
                     {runtime.BUILD_SHA_ENV: '0' * 64}, {runtime.CHILD_ENV[0]: '/injected.so'}):
        with pytest.raises(ValueError):
            runtime.stage(HERE, settings, '/missing-run', '/missing-qemu', None)


def metadata_fixture(tmp_path):
    library = tmp_path / runtime.LIBRARY
    library.write_bytes(b'HOST_TEST independent DSO placeholder, never loaded')
    (tmp_path / runtime.TRACE).write_bytes((API.parent / 'original/record.log').read_bytes())
    return dict(profile=runtime.PROFILE, trace_schema=runtime.SCHEMA,
        primary_profile='qemu-readonly-shutter-gate-v2', identity_binding='unverified',
        library=str(library), log=str(tmp_path / runtime.TRACE), library_sha256=bundle.digest(library.read_bytes()),
        build_receipt_sha256='a' * 64, **bundle.FALSE)


def test_only_ended_wrapper_records_v3_exit_and_raw_content_stays_unverified(tmp_path):
    metadata = metadata_fixture(tmp_path)
    with pytest.raises(ValueError, match='ended wrapper'):
        runtime.record_exit(tmp_path, metadata, SimpleNamespace(pid=123, poll=lambda: None))
    exited = runtime.record_exit(tmp_path, metadata, SimpleNamespace(pid=123, poll=lambda: 0))
    assert exited['schema'] == 'readonly_writer_exit_v5' and exited['trace_reader_error'] is None
    parsed = runtime.read_run(tmp_path, metadata)
    assert len(parsed['origins']) == len(parsed['events']) == len(parsed['records']) == 9
    assert parsed['capture_verified'] is False and parsed['AP_identity_verified'] is False
    with pytest.raises(FileExistsError):
        runtime.record_exit(tmp_path, metadata, SimpleNamespace(pid=123, poll=lambda: 0))
    (tmp_path / runtime.TRACE).write_bytes(b'HOST_TEST changed retained trace\n')
    with pytest.raises(ValueError):
        runtime.read_run(tmp_path, metadata)


@pytest.mark.parametrize('plugins', [
    [b'/shutter-writer.so,log=/out/readonly-shutter-writer.log'],
    [b'/shutter-writer.so,log=/out/readonly-shutter-writer.log', b'/scope-observer.so,log=/out/readonly-scope-trace.log'],
    [b'/scope-observer.so,log=/out/readonly-scope-trace.log', b'/shutter-writer.so,log=/out/readonly-shutter-writer.log', b'/extra.so'],
])
def test_original_primary_and_auxiliary_exact_command_cannot_be_replaced(plugins):
    argv = [b'/tools/qemu-system-aarch64']
    for plugin in plugins:
        argv += [b'-plugin', plugin]
    with pytest.raises(ValueError):
        contract.check_plugin_command(b'\0'.join(argv) + b'\0')
