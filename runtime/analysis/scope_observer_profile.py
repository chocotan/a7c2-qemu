"""Stage one reviewed, host-only QEMU scope observer; default is off."""
from pathlib import Path
import hashlib
import json
import os
import shutil
import stat
import struct

PROFILE = 'qemu-readonly-scope-v1'
BUILD_ENV = 'A7C2_SCOPE_OBSERVER_BUILD'
CHILD_ENV = ('QEMU_SCOPE_OBSERVER_PLUGIN', 'QEMU_SCOPE_OBSERVER_SHA256')
SOURCE_NAMES = ('scope-observer.c', 'late-sites.inc', 'build-plugin.sh')
PROFILE_V2 = 'qemu-readonly-scope-v2'
SOURCE_NAMES_V2 = SOURCE_NAMES + ('log-schema-v2.json', 'source-contract-v2.json',
    'check_run_context_v2.py', 'check_run_context.py',
    'integration/scope_trace_checks_v2.py', 'integration/scope_trace_checks.py')
PROFILE_V3 = 'qemu-readonly-scope-v3'
SOURCE_NAMES_V3 = SOURCE_NAMES + ('log-schema-v3.json', 'source-contract-v3.json',
    'check_run_context_v3.py', 'check_run_context.py',
    'integration/scope_trace_checks_v3.py', 'integration/scope_trace_checks.py')
SOURCE_SETS = {PROFILE: SOURCE_NAMES, PROFILE_V2: SOURCE_NAMES_V2, PROFILE_V3: SOURCE_NAMES_V3}
V3_QEMU_SHA256 = '4e85c70ba38774e9439562a7178a65bdbe6b660fdf8dd6bd4ece686fb707a4d4'
V3_HEADER_SHA256 = '335d4e472067e914add598b60d1f7cf0dc029cd48f62f66656d6a88c54d8d9f9'
LEGACY_SCHEMA_SHA256 = '8b6e2bf3576e7e4e5566fa215d2758e088ae8867ed6b3c36ea7b90f38767e50c'


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def ordinary_file(value):
    path = Path(value)
    if not path.is_absolute() or path.is_symlink() or not stat.S_ISREG(path.stat().st_mode):
        raise ValueError('Scope observer requires an absolute ordinary file: ' + str(path))
    return path


def source_root(native, version):
    """Select reviewed source locations by explicit version, never receipt paths."""
    if type(version) is not str or version not in SOURCE_SETS:
        raise ValueError('Unknown scope observer profile')
    component = ('2026-10-31-qemu-M-writer-observer-v3' if version == PROFILE_V3 else
                 '2026-10-30-qemu-readonly-scope-observer')
    return Path(native) / 'report' / component


def v3_file(value):
    path = ordinary_file(value)
    info = path.stat()
    if path.resolve() != path or info.st_uid != os.getuid() or info.st_mode & 0o022:
        raise ValueError('Scope observer v3 requires an owned canonical ordinary file: ' + str(path))
    return path


def validate_build(native, receipt_value, qemu_binary):
    """Read the reviewed build without staging a plugin or starting QEMU."""
    native = Path(native).resolve()
    receipt_path = ordinary_file(receipt_value)
    receipt_bytes = receipt_path.read_bytes()
    receipt = json.loads(receipt_bytes)
    if (not isinstance(receipt, dict) or type(receipt.get('schema')) is not str or receipt['schema'] not in SOURCE_SETS or
            type(receipt.get('plugin_api')) is not int or receipt['plugin_api'] != 7 or
            receipt.get('readonly_imports_verified') is not True):
        raise ValueError('Scope observer build receipt is not a reviewed API7 read-only build')
    version = receipt['schema']
    root = source_root(native, version)
    if version == PROFILE_V3:
        for path in (receipt_path, *(root / name for name in SOURCE_NAMES_V3)):
            v3_file(path)
    expected = {name: sha(root / name) for name in SOURCE_SETS[version]}
    if receipt.get('source_sha256') != expected:
        raise ValueError('Scope observer source identity changed after build')
    if version in (PROFILE_V2, PROFILE_V3) and (receipt.get('trace_schema') !=
            ('readonly_scope_v3' if version == PROFILE_V3 else 'readonly_scope_v2') or
            bool({'schema_sha256', 'log_schema_sha256'} & receipt.keys()) or
            receipt.get('trace_schema_sha256') != expected['log-schema-' + version[-2:] + '.json'] or
            receipt.get('trace_schema_sha256') == LEGACY_SCHEMA_SHA256 or
            receipt.get('source_contract_sha256') != expected['source-contract-' + version[-2:] + '.json'] or
            any(receipt.get(key) is not False for key in
                ('runtime_verified', 'capture_verified', 'physical_asic_compatibility_verified'))):
        raise ValueError('Scope observer ' + version[-2:] + ' schema/source-contract binding differs')
    if version == PROFILE_V3:
        declaration = json.loads((root / 'log-schema-v3.json').read_bytes())
        contract = json.loads((root / 'source-contract-v3.json').read_bytes())
        if (type(declaration) is not dict or declaration.get('schema') != 'readonly_scope_v3' or
                declaration.get('profile') != PROFILE_V3 or type(contract) is not dict or
                contract.get('schema') != 'readonly_scope_source_contract_v3' or
                contract.get('profile') != PROFILE_V3 or contract.get('trace_schema') != 'readonly_scope_v3' or
                contract.get('trace_schema_sha256') != expected['log-schema-v3.json'] or
                contract.get('actual_build_source_names_required') != list(SOURCE_NAMES_V3) or
                bool({'source_root', 'Source_root', 'sourceDependencyFrozen', 'v3_schema_sha256'} & receipt.keys())):
            raise ValueError('Scope observer v3 actual schema/source-contract binding differs')
    header = native / 'source/build/qemu-SRBXNK/qemu-11.1.2/include/plugins/qemu-plugin.h'
    if sha(header) != receipt.get('qemu_header_sha256'):
        raise ValueError('Scope observer QEMU API header identity changed')
    binary = ordinary_file(qemu_binary)
    if sha(binary) != receipt.get('qemu_sha256'):
        raise ValueError('Scope observer requires its matched plugin-enabled QEMU candidate')
    library = ordinary_file(receipt['library'])
    if version == PROFILE_V3:
        for path in (header, binary, library):
            v3_file(path)
        if receipt['qemu_header_sha256'] != V3_HEADER_SHA256 or receipt['qemu_sha256'] != V3_QEMU_SHA256:
            raise ValueError('Scope observer v3 requires the exact reviewed API7 header and QEMU')
    library_sha = sha(library)
    if library_sha != receipt.get('library_sha256'):
        raise ValueError('Scope observer library identity changed after build')
    with library.open('rb') as stream:
        header_bytes = stream.read(20)
    if (len(header_bytes) != 20 or header_bytes[:6] != b'\x7fELF\x02\x01' or
            struct.unpack_from('<HH', header_bytes, 16) != (3, 62)):
        raise ValueError('Scope observer requires the reviewed x86-64 host ELF plugin')
    result = {'profile': version, 'build_receipt': str(receipt_path),
            'build_receipt_sha256': hashlib.sha256(receipt_bytes).hexdigest(),
            'library': str(library), 'library_sha256': library_sha,
            'qemu_sha256': receipt['qemu_sha256'], 'qemu_header_sha256': receipt['qemu_header_sha256'],
            'source_sha256': expected, 'identity_binding': 'unverified', 'capture_verified': False,
            'physical_asic_compatibility_verified': False}
    if version in (PROFILE_V2, PROFILE_V3):
        result.update(trace_schema=receipt['trace_schema'], trace_schema_sha256=receipt['trace_schema_sha256'],
                      source_contract_sha256=receipt['source_contract_sha256'])
    return result


def prepare(native, env, output):
    """Bind the built plugin to the selected QEMU and copy it into a fresh run."""
    if any(env.get(name) for name in CHILD_ENV):
        raise ValueError('Scope observer child environment must be prepared by the host')
    if not env.get(BUILD_ENV):
        return None
    if env.get('MENU_FUNCTIONAL_CAMERA') != 'virtual-functional-camera-v1' or env.get('QEMU_CPU_COUNT', '1') != '1':
        raise ValueError('Scope observer requires the explicit single-vCPU functional profile')
    native, output = Path(native).resolve(), Path(output)
    if output.is_symlink() or not output.is_dir():
        raise ValueError('Scope observer requires an ordinary new run directory')
    binary = Path(env['QEMU_SYSTEM_DIR']) / env.get('QEMU_SYSTEM_BINARY', 'qemu-system-aarch64')
    build = validate_build(native, env[BUILD_ENV], binary)
    if build['profile'] == PROFILE_V3 and (not output.is_absolute() or output.resolve() != output or
            output.stat().st_uid != os.getuid() or output.stat().st_mode & 0o022):
        raise ValueError('Scope observer v3 requires an owned canonical run directory')
    receipt_path = ordinary_file(build['build_receipt'])
    receipt_bytes = receipt_path.read_bytes()
    if hashlib.sha256(receipt_bytes).hexdigest() != build['build_receipt_sha256']:
        raise ValueError('Scope observer build receipt changed before staging')
    library, library_sha = Path(build['library']), build['library_sha256']
    expected = build['source_sha256']
    root = source_root(native, build['profile'])
    destination = output / 'readonly-scope-observer.so'
    log = output / 'readonly-scope-trace.log'
    if os.path.lexists(destination) or os.path.lexists(log):
        raise ValueError('Scope observer refuses an old plugin or trace file in this run')
    with library.open('rb') as reader, destination.open('xb') as writer:
        shutil.copyfileobj(reader, writer)
        writer.flush()
        os.fsync(writer.fileno())
    destination.chmod(0o400)
    if build['profile'] == PROFILE_V3:
        for path in (receipt_path, library, binary, *(root / name for name in expected)):
            v3_file(path)
    if (sha(destination) != library_sha or sha(library) != library_sha or
            receipt_path.read_bytes() != receipt_bytes or sha(binary) != build['qemu_sha256'] or
            {name: sha(root / name) for name in expected} != expected):
        raise ValueError('Scope observer assets changed during staging; retained incomplete run')
    env.update(zip(CHILD_ENV, (str(destination.resolve()), library_sha)))
    return dict(build, library=str(destination.resolve()), log=str(log.resolve()))


def record_exit(output, profile, process):
    """Preserve the actual owned wrapper result; this never signals a process."""
    if profile is None:
        return
    output = Path(output)
    log = output / 'readonly-scope-trace.log'
    present = log.is_file() and not log.is_symlink()
    if profile.get('profile') not in SOURCE_SETS:
        raise ValueError('Scope observer exit requires its actual staged version')
    receipt = {'profile': profile['profile'], 'run': str(output.resolve()), 'owned_wrapper_pid': process.pid,
               'returncode': process.poll(), 'log_available': present,
               'log_sha256': sha(log) if present else None,
               'library_sha256': profile['library_sha256'],
               'capture_verified': False, 'physical_asic_compatibility_verified': False}
    with (output / 'readonly-scope-exit.json').open('x') as stream:
        json.dump(receipt, stream, indent=2)
        stream.write('\n')
