from pathlib import Path
import json
import sys
from types import SimpleNamespace

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import writer_origin_runtime as runtime


def test_default_off_does_not_read_missing_paths_or_change_environment():
    env = {}
    assert runtime.stage(Path('/missing-component'), env, '/missing-run', '/missing-qemu', None) is None
    assert env == {}


@pytest.mark.parametrize('env', [
    {runtime.CHILD_ENV[0]: '/injected.so'}, {runtime.CHILD_ENV[1]: ''},
    {runtime.BUILD_ENV: '/receipt'}, {runtime.BUILD_SHA_ENV: 'a' * 64},
    {runtime.BUILD_ENV: '', runtime.BUILD_SHA_ENV: ''}, {runtime.PROFILE_ENV: runtime.PROFILE}])
def test_injected_child_or_partial_request_refused_before_file_access(env):
    with pytest.raises(ValueError):
        runtime.stage(HERE, env, '/missing-run', '/missing-qemu', None)


@pytest.mark.parametrize('primary', [None, {}, {'profile': 'qemu-readonly-shutter-gate-v1'},
    {'profile': 'qemu-readonly-shutter-gate-v2', 'qemu_sha256': '0' * 64,
     'capture_verified': False, 'physical_asic_compatibility_verified': False}])
def test_primary_scope_must_bind_reviewed_gate_v2(primary):
    with pytest.raises(ValueError, match='strict gate-v2'):
        runtime.stage(HERE, {runtime.BUILD_ENV: '/receipt', runtime.BUILD_SHA_ENV: 'a' * 64},
                      '/missing-run', '/missing-qemu', primary)


def test_reused_writer_library_and_trace_refused_before_build_validation(tmp_path):
    primary = dict(profile='qemu-readonly-shutter-gate-v2', qemu_sha256=runtime.QEMU_SHA256,
                   capture_verified=False, physical_asic_compatibility_verified=False)
    env = {runtime.BUILD_ENV: '/missing-receipt', runtime.BUILD_SHA_ENV: 'a' * 64,
           runtime.PROFILE_ENV: runtime.PROFILE}
    for name in (runtime.LIBRARY, runtime.TRACE):
        path = tmp_path / name
        path.write_bytes(b'old generation')
        with pytest.raises(ValueError, match='cannot be reused'):
            runtime.stage(HERE, dict(env), tmp_path, '/missing-qemu', primary)
        path.unlink()
    assert set(env) == {runtime.BUILD_ENV, runtime.BUILD_SHA_ENV, runtime.PROFILE_ENV}


def exit_fixture(tmp_path):
    from writer_origin_bundle import FALSE
    from origin_fixtures import encode, fixture_rows
    library = tmp_path / runtime.LIBRARY
    library.write_bytes(b'actual independent DSO fixture')
    metadata = dict(profile=runtime.PROFILE, trace_schema=runtime.SCHEMA,
        primary_profile='qemu-readonly-shutter-gate-v2', identity_binding='unverified',
        library=str(library), log=str(tmp_path / runtime.TRACE),
        library_sha256=runtime.digest(library.read_bytes()), build_receipt_sha256='a' * 64, **FALSE)
    (tmp_path / runtime.TRACE).write_bytes(encode(fixture_rows()))
    return metadata


def test_exit_and_trace_are_bound_without_promoting_original_camera_identity(tmp_path):
    metadata = exit_fixture(tmp_path)
    receipt = runtime.record_exit(tmp_path, metadata, SimpleNamespace(pid=123, poll=lambda: 0))
    assert receipt['returncode'] == 0 and receipt['log_available'] is True and receipt['trace_reader_error'] is None
    observed = runtime.read_run(tmp_path, metadata)
    assert observed['writer_exit_receipt_bound'] is True and observed['runtime_receipt_bound'] is False
    assert len(observed['events']) == 3 and observed['capture_verified'] is False
    with pytest.raises(FileExistsError):
        runtime.record_exit(tmp_path, metadata, SimpleNamespace(pid=123, poll=lambda: 0))
    path = tmp_path / runtime.TRACE
    path.write_bytes(path.read_bytes().replace(b'x30_raw=0x40200014', b'x30_raw=0x40200018'))
    with pytest.raises(ValueError, match='digest differs'):
        runtime.read_run(tmp_path, metadata)


def test_active_wrapper_cannot_emit_exit_receipt(tmp_path):
    metadata = exit_fixture(tmp_path)
    with pytest.raises(ValueError, match='ended wrapper'):
        runtime.record_exit(tmp_path, metadata, SimpleNamespace(pid=123, poll=lambda: None))
    assert not (tmp_path / 'readonly-shutter-writer-exit.json').exists()


def test_missing_or_malformed_trace_preserves_original_returncode_in_failed_receipt(tmp_path):
    metadata = exit_fixture(tmp_path)
    (tmp_path / runtime.TRACE).unlink()
    receipt = runtime.record_exit(tmp_path, metadata, SimpleNamespace(pid=123, poll=lambda: 7))
    assert receipt['returncode'] == 7 and receipt['log_available'] is False
    assert receipt['trace_reader_error'].startswith('FileNotFoundError:')
    with pytest.raises(ValueError, match='exit receipt'):
        runtime.read_run(tmp_path, metadata)


@pytest.mark.parametrize('field,value', [('owned_wrapper_pid', 0), ('returncode', True),
    ('run', '/foreign/run'), ('library_sha256', 'b' * 64), ('build_receipt_sha256', 'b' * 64),
    ('metadata_sha256', 'b' * 64), ('log_available', False), ('capture_verified', True)])
def test_changed_exit_scope_or_binding_is_refused(tmp_path, field, value):
    metadata = exit_fixture(tmp_path)
    receipt = runtime.record_exit(tmp_path, metadata, SimpleNamespace(pid=123, poll=lambda: 0))
    receipt[field] = value
    (tmp_path / 'readonly-shutter-writer-exit.json').write_text(json.dumps(receipt))
    with pytest.raises(ValueError, match='exit receipt'):
        runtime.read_run(tmp_path, metadata)


def test_run_directory_symlink_traversal_and_public_write_are_refused(tmp_path):
    assert runtime.directory(tmp_path) == tmp_path
    alias = tmp_path / 'alias'
    alias.symlink_to(tmp_path, target_is_directory=True)
    with pytest.raises(ValueError, match='canonical'):
        runtime.directory(alias)
    with pytest.raises(ValueError, match='canonical'):
        runtime.directory(tmp_path / '..' / tmp_path.name)
    tmp_path.chmod(0o777)
    with pytest.raises(ValueError, match='owned and private'):
        runtime.directory(tmp_path)
