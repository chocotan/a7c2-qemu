"""Prepare an auxiliary writer DSO. Probe/shell integration is deliberately separate."""
from pathlib import Path
import json
import os
import stat

from writer_bundle import FALSE, QEMU_SHA256, validate_build
from writer_trace import PROFILE, SCHEMA, digest, need, parse_trace, read_file

BUILD_ENV = 'A7C2_SHUTTER_WRITER_BUILD'
BUILD_SHA_ENV = 'A7C2_SHUTTER_WRITER_BUILD_SHA256'
CHILD_ENV = ('QEMU_SHUTTER_WRITER_PLUGIN', 'QEMU_SHUTTER_WRITER_SHA256')
LIBRARY = 'readonly-shutter-writer.so'
TRACE = 'readonly-shutter-writer.log'


def directory(value):
    path = Path(value)
    need(path.is_absolute() and '..' not in path.parts and path.resolve(strict=True) == path and
         not any(p.is_symlink() for p in (path, *path.parents)), 'writer run directory must be canonical')
    info = path.stat()
    need(stat.S_ISDIR(info.st_mode) and info.st_uid == os.geteuid() and not info.st_mode & 0o022,
         'writer run directory must be owned and private')
    return path


def stage(component, env, run, qemu, primary_scope):
    """No plugin executes here. Caller must bind returned metadata before QEMU launch."""
    need(not any(key in env for key in CHILD_ENV), 'writer child environment must not be injected')
    requested, expected = env.get(BUILD_ENV), env.get(BUILD_SHA_ENV)
    if requested is None and expected is None:
        return None
    need(type(requested) is str and requested and type(expected) is str and expected,
         'writer build and explicit receipt SHA256 are required together')
    need(type(primary_scope) is dict and primary_scope.get('profile') == 'qemu-readonly-shutter-gate-v2' and
         primary_scope.get('qemu_sha256') == QEMU_SHA256 and
         primary_scope.get('capture_verified') is False and
         primary_scope.get('physical_asic_compatibility_verified') is False,
         'auxiliary writer requires the independently bound strict gate-v2 primary')
    run = directory(run)
    library, log = run / LIBRARY, run / TRACE
    need(not os.path.lexists(library) and not os.path.lexists(log), 'writer run assets cannot be reused')
    receipt = validate_build(Path(component), Path(requested), expected, Path(qemu))
    raw = read_file(receipt['library'], 1024 * 1024, receipt['library_sha256'])
    with library.open('xb') as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    library.chmod(0o400)
    need(read_file(library, expected_sha256=receipt['library_sha256']) == raw,
         'staged writer DSO differs')
    metadata = dict(profile=PROFILE, trace_schema=SCHEMA, build_receipt=requested,
        build_receipt_sha256=expected, library=str(library), library_sha256=receipt['library_sha256'],
        log=str(log), qemu=str(qemu), qemu_sha256=QEMU_SHA256,
        source_sha256=receipt['source_sha256'], actual_API_evidence=receipt['actual_API_evidence'],
        primary_profile='qemu-readonly-shutter-gate-v2', identity_binding='unverified', **FALSE)
    env.update(zip(CHILD_ENV, (str(library), receipt['library_sha256'])))
    return metadata


def record_exit(run, metadata, process):
    """Record only an already-ended owned wrapper; never stop or signal it."""
    run = directory(run)
    returncode = process.poll()
    need(type(returncode) is int and type(process.pid) is int and process.pid > 0,
         'writer exit requires the actual ended wrapper')
    need(type(metadata) is dict and metadata.get('profile') == PROFILE and
         metadata.get('library') == str(run / LIBRARY) and metadata.get('log') == str(run / TRACE) and
         all(metadata.get(key) is False for key in FALSE), 'writer exit metadata differs')
    read_file(run / LIBRARY, 1024 * 1024, metadata['library_sha256'])
    receipt = dict(schema='readonly_writer_exit_v1', profile=PROFILE, run=str(run),
        owned_wrapper_pid=process.pid, returncode=returncode, build_receipt_sha256=metadata['build_receipt_sha256'],
        library_sha256=metadata['library_sha256'], metadata_sha256=digest(json.dumps(metadata,
            sort_keys=True, separators=(',', ':')).encode()), log_available=False, log_sha256=None,
        trace_reader_error=None, **FALSE)
    try:
        raw = read_file(run / TRACE)
        receipt.update(log_available=True, log_sha256=digest(raw))
        parse_trace(raw)
    except (OSError, ValueError, UnicodeError) as error:
        receipt['trace_reader_error'] = type(error).__name__ + ': ' + str(error)
    with (run / 'readonly-shutter-writer-exit.json').open('x') as stream:
        json.dump(receipt, stream, indent=2)
        stream.write('\n')
        stream.flush()
        os.fsync(stream.fileno())
    return receipt


def read_run(run, metadata):
    """Read a closed writer receipt; camera lineage still needs independent proof."""
    run = directory(run)
    need(type(metadata) is dict and metadata.get('profile') == PROFILE and metadata.get('trace_schema') == SCHEMA and
         metadata.get('primary_profile') == 'qemu-readonly-shutter-gate-v2' and
         metadata.get('identity_binding') == 'unverified' and all(metadata.get(k) is False for k in FALSE),
         'writer metadata scope differs')
    library, trace = run / LIBRARY, run / TRACE
    need(metadata.get('library') == str(library) and metadata.get('log') == str(trace),
         'writer trace or DSO belongs to another run')
    read_file(library, 1024 * 1024, metadata['library_sha256'])
    from writer_bundle import object_json
    exited = object_json(read_file(run / 'readonly-shutter-writer-exit.json', 64 * 1024))
    need(exited.get('schema') == 'readonly_writer_exit_v1' and exited.get('profile') == PROFILE and
         exited.get('run') == str(run) and type(exited.get('owned_wrapper_pid')) is int and
         exited['owned_wrapper_pid'] > 0 and type(exited.get('returncode')) is int and exited['returncode'] == 0 and
         exited.get('library_sha256') == metadata['library_sha256'] and
         exited.get('build_receipt_sha256') == metadata['build_receipt_sha256'] and
         exited.get('metadata_sha256') == digest(json.dumps(metadata, sort_keys=True, separators=(',', ':')).encode()) and
         exited.get('log_available') is True and exited.get('trace_reader_error') is None and
         all(exited.get(key) is False for key in FALSE), 'writer exit receipt or scope differs')
    result = parse_trace(read_file(trace, expected_sha256=exited['log_sha256']))
    return dict(result, profile=PROFILE, run=str(run), build_receipt_sha256=metadata['build_receipt_sha256'],
                writer_exit_receipt_bound=True, runtime_receipt_bound=False,
                original_camera_exit_independently_required=True)
