"""Stage one reviewed, host-only QEMU scope observer; default is off."""
from pathlib import Path
import hashlib
import json
import math
import os
import re
import shutil
import stat
import struct

PUBLIC_NATIVE_ROOT = Path(__file__).resolve().parents[2]

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
PROFILE_SHUTTER_GATE_V1 = 'qemu-readonly-shutter-gate-v1'
SHUTTER_GATE_SCHEMA_FILE = 'log-schema-shutter-gate-v1.json'
SHUTTER_GATE_CONTRACT_FILE = 'source-contract-shutter-gate-v1.json'
SOURCE_NAMES_SHUTTER_GATE_V1 = ('scope-observer.c', 'build-plugin.sh', 'build-runtime.py',
    SHUTTER_GATE_SCHEMA_FILE, SHUTTER_GATE_CONTRACT_FILE, 'check_shutter_gate_v1.py',
    'integration/shutter_gate_trace_checks_v1.py')
FIXTURE_NAMES_SHUTTER_GATE_V1 = ('integration/fixture.S', 'integration/link.ld', 'integration/run_fixture.py',
    'integration/test_fixture_driver.py', 'integration/test_actual_scope_plugin.py',
    'integration/test_shutter_gate_trace_checks_v1.py', 'integration/shutter_gate_trace_checks_v1.py')
SHUTTER_GATE_CASES = ('original_entry', 'existing_main_stub_entry', 'one_byte_gate_mutation', 'short_tb')
SHUTTER_GATE_API_ENV = ('A7C2_SHUTTER_GATE_V1_TEST_QEMU', 'A7C2_SHUTTER_GATE_V1_TEST_PLUGIN',
    'A7C2_SHUTTER_GATE_V1_TEST_OUTPUT', 'A7C2_SHUTTER_GATE_V1_TEST_SCHEMA',
    'A7C2_SHUTTER_GATE_V1_TEST_RECEIPT', 'A7C2_SHUTTER_GATE_V1_TEST_FIXTURE_SOURCES')
PROFILE_SHUTTER_GATE_V2 = 'qemu-readonly-shutter-gate-v2'
SHUTTER_GATE_SCHEMA_FILE_V2 = 'log-schema-shutter-gate-v2.json'
SHUTTER_GATE_CONTRACT_FILE_V2 = 'source-contract-shutter-gate-v2.json'
SOURCE_NAMES_SHUTTER_GATE_V2 = ('scope-observer.c', 'build-plugin.sh', 'build-runtime.py',
    SHUTTER_GATE_SCHEMA_FILE_V2, SHUTTER_GATE_CONTRACT_FILE_V2, 'check_shutter_gate_v2.py',
    'integration/shutter_gate_trace_checks_v2.py')
FIXTURE_NAMES_SHUTTER_GATE_V2 = ('integration/fixture.S', 'integration/link.ld', 'integration/run_fixture.py',
    'integration/test_fixture_driver.py', 'integration/test_actual_scope_plugin.py',
    'integration/test_shutter_gate_trace_checks_v2.py', 'integration/shutter_gate_trace_checks_v2.py')
SHUTTER_GATE_API_ENV_V2 = ('A7C2_SHUTTER_GATE_V2_TEST_QEMU', 'A7C2_SHUTTER_GATE_V2_TEST_PLUGIN',
    'A7C2_SHUTTER_GATE_V2_TEST_OUTPUT', 'A7C2_SHUTTER_GATE_V2_TEST_SCHEMA',
    'A7C2_SHUTTER_GATE_V2_TEST_RECEIPT', 'A7C2_SHUTTER_GATE_V2_TEST_FIXTURE_SOURCES')
SHUTTER_GATE_PROFILES = {
    PROFILE_SHUTTER_GATE_V1: dict(component='2026-10-31-qemu-shutter-gate-observer-v1',
        trace_schema='readonly_shutter_gate_v1', source_contract_schema='readonly_shutter_gate_source_contract_v1',
        schema_file=SHUTTER_GATE_SCHEMA_FILE, contract_file=SHUTTER_GATE_CONTRACT_FILE,
        fixture_names=FIXTURE_NAMES_SHUTTER_GATE_V1, api_env=SHUTTER_GATE_API_ENV,
        build_scratch='functional-shutter-gate-v1-readonly-plugin'),
    PROFILE_SHUTTER_GATE_V2: dict(component='2026-11-02-qemu-shutter-gate-observer-v2',
        trace_schema='readonly_shutter_gate_v2', source_contract_schema='readonly_shutter_gate_source_contract_v2',
        schema_file=SHUTTER_GATE_SCHEMA_FILE_V2, contract_file=SHUTTER_GATE_CONTRACT_FILE_V2,
        fixture_names=FIXTURE_NAMES_SHUTTER_GATE_V2, api_env=SHUTTER_GATE_API_ENV_V2,
        build_scratch='functional-shutter-gate-v2-readonly-plugin'),
}
SHUTTER_GATE_ALIASES = frozenset(('source_root', 'Source_root', 'root', 'sourceDependencyFrozen',
    'schema_sha256', 'log_schema_sha256', 'v3_schema_sha256'))
SHUTTER_GATE_IMPORTS = frozenset(('qemu_plugin_get_registers', 'qemu_plugin_read_register',
    'qemu_plugin_register_vcpu_init_cb', 'qemu_plugin_register_vcpu_tb_trans_cb',
    'qemu_plugin_register_vcpu_insn_exec_cb', 'qemu_plugin_register_atexit_cb',
    'qemu_plugin_tb_n_insns', 'qemu_plugin_tb_get_insn', 'qemu_plugin_insn_vaddr',
    'qemu_plugin_insn_size', 'qemu_plugin_insn_data'))
SOURCE_SETS = {PROFILE: SOURCE_NAMES, PROFILE_V2: SOURCE_NAMES_V2, PROFILE_V3: SOURCE_NAMES_V3,
               PROFILE_SHUTTER_GATE_V1: SOURCE_NAMES_SHUTTER_GATE_V1,
               PROFILE_SHUTTER_GATE_V2: SOURCE_NAMES_SHUTTER_GATE_V2}
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
    if version in SHUTTER_GATE_PROFILES:
        if Path(native).resolve() != PUBLIC_NATIVE_ROOT:
            raise ValueError('Shutter gate requires the fixed public package source root')
        return PUBLIC_NATIVE_ROOT / 'report' / SHUTTER_GATE_PROFILES[version]['component']
    component = ('2026-10-31-qemu-M-writer-observer-v3' if version == PROFILE_V3 else
                 '2026-10-30-qemu-readonly-scope-observer')
    return Path(native) / 'report' / component


def v3_file(value):
    path = ordinary_file(value)
    info = path.stat()
    if path.resolve() != path or info.st_uid != os.getuid() or info.st_mode & 0o022:
        raise ValueError('Scope observer v3 requires an owned canonical ordinary file: ' + str(path))
    return path


def shutter_gate_file(value):
    path = v3_file(value)
    if path.stat().st_nlink != 1:
        raise ValueError('Shutter gate requires a single-link ordinary file: ' + str(path))
    return path


def shutter_gate_directory(value):
    path = Path(value)
    info = path.lstat()
    if (not path.is_absolute() or path.resolve() != path or not stat.S_ISDIR(info.st_mode) or
            info.st_uid != os.getuid() or info.st_mode & 0o022):
        raise ValueError('Shutter gate requires an owned canonical directory: ' + str(path))
    return path


def shutter_gate_json(raw):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError('Duplicate shutter-gate JSON field: ' + key)
            result[key] = value
        return result
    def finite(value):
        number = float(value)
        if not math.isfinite(number):
            raise ValueError('Non-finite shutter-gate JSON number: ' + value)
        return number
    result = json.loads(raw, object_pairs_hook=unique, parse_float=finite, parse_constant=finite)
    if type(result) is not dict:
        raise ValueError('Shutter gate requires a JSON object')
    return result


def validate_shutter_gate_build(native, root, receipt_path, receipt, expected, header, binary, library):
    """A separate fixed source7/fixture7 contract; no legacy schema suffix inference."""
    version = receipt['schema']
    gate = SHUTTER_GATE_PROFILES[version]
    if native != PUBLIC_NATIVE_ROOT or root != source_root(native, version):
        raise ValueError('Shutter gate requires the fixed native/component source root')
    for path in (receipt_path, header, binary, library, *(root / name for name in expected)):
        shutter_gate_file(path)
    scratch = native / 'runtime/analysis/scratch' / gate['build_scratch']
    shutter_gate_directory(scratch)
    work = shutter_gate_directory(library.parent)
    if (work.parent != scratch or not work.name.startswith('build-') or
            library.name != 'scope-observer.so' or receipt_path != work / 'build-receipt.json'):
        raise ValueError('Shutter gate requires its independent fresh build directory')
    fixtures = {name: sha(shutter_gate_file(root / name)) for name in gate['fixture_names']}
    schema_file, contract_file = gate['schema_file'], gate['contract_file']
    if (receipt.get('trace_schema') != gate['trace_schema'] or
            SHUTTER_GATE_ALIASES & receipt.keys() or
            receipt.get('trace_schema_sha256') != expected[schema_file] or
            receipt.get('source_contract_sha256') != expected[contract_file] or
            receipt.get('fixture_source_sha256') != fixtures or
            receipt.get('qemu') != str(binary) or
            receipt.get('qemu_sha256') != V3_QEMU_SHA256 or receipt.get('qemu_header_sha256') != V3_HEADER_SHA256 or
            any(receipt.get(key) is not False for key in
                ('runtime_verified', 'capture_verified', 'physical_asic_compatibility_verified'))):
        raise ValueError('Shutter gate schema/source-contract/fixture7 binding differs')
    declaration = shutter_gate_json((root / schema_file).read_bytes())
    contract = shutter_gate_json((root / contract_file).read_bytes())
    if (declaration.get('schema') != gate['trace_schema'] or
            declaration.get('profile') != version or
            contract.get('schema') != gate['source_contract_schema'] or
            contract.get('profile') != version or
            contract.get('trace_schema') != gate['trace_schema'] or
            contract.get('trace_schema_sha256') != expected[schema_file] or
            contract.get('actual_build_source_names_required') != list(SOURCE_SETS[version]) or
            contract.get('actual_fixture_source_names_required') != list(gate['fixture_names']) or
            contract.get('actualAPI_cases') != list(SHUTTER_GATE_CASES) or
            contract.get('actualAPI_environment_names') != list(gate['api_env']) or
            'source_contract_sha256' in contract or
            any(SHUTTER_GATE_ALIASES & data.keys() for data in (declaration, contract))):
        raise ValueError('Shutter gate actual schema/source-contract/source7/fixture7/API interface differs')
    command_path = shutter_gate_file(work / 'plugin-build-command.json')
    audit_path = shutter_gate_file(work / 'readonly-import-audit.json')
    command = shutter_gate_json(command_path.read_bytes())
    audit = shutter_gate_json(audit_path.read_bytes())
    if (sha(command_path) != receipt.get('plugin_build_command_sha256') or
            sha(audit_path) != receipt.get('readonly_import_audit_sha256') or
            not isinstance(receipt.get('candidate_static_audit_sha256'), str) or
            not re.fullmatch('[0-9a-f]{64}', receipt['candidate_static_audit_sha256']) or
            command.get('command') != ['sh', str(root / 'build-plugin.sh')] or
            type(command.get('returncode')) is not int or command['returncode'] != 0 or
            command.get('stdout') != str(library) + '\n' or type(command.get('stderr')) is not str):
        raise ValueError('Shutter gate actual compile/import audit binding differs')
    for name, argv in (('imports', ['nm', '-D', '--undefined-only', str(library)]),
                       ('exports', ['nm', '-D', '--defined-only', str(binary)]),
                       ('needed', ['readelf', '-d', str(library)])):
        row = audit.get(name)
        if (type(row) is not dict or row.get('command') != argv or
                type(row.get('returncode')) is not int or row['returncode'] != 0 or
                type(row.get('stdout')) is not str or type(row.get('stderr')) is not str):
            raise ValueError('Shutter gate actual nm/readelf result differs')
    imports = {line.split()[-1].split('@')[0] for line in audit['imports']['stdout'].splitlines() if line.split()}
    exports = {line.split()[-1].split('@')[0] for line in audit['exports']['stdout'].splitlines() if line.split()}
    required = {name for name in imports if name.startswith('qemu_plugin_')}
    if (required != SHUTTER_GATE_IMPORTS or not required <= exports or
            audit.get('qemu_plugin_imports') != sorted(required) or
            audit.get('ordinary_imports') != sorted(imports - required) or
            audit.get('dt_needed') != re.findall(r'\(NEEDED\).*\[([^\]]+)\]', audit['needed']['stdout'])):
        raise ValueError('Shutter gate exact eleven QEMU imports/ordinary import audit differs')
    return fixtures


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
    if version in SHUTTER_GATE_PROFILES:
        receipt = shutter_gate_json(receipt_bytes)
    root = source_root(native, version)
    if version == PROFILE_V3:
        for path in (receipt_path, *(root / name for name in SOURCE_NAMES_V3)):
            v3_file(path)
    if version in SHUTTER_GATE_PROFILES:
        for path in (receipt_path, *(root / name for name in SOURCE_SETS[version])):
            shutter_gate_file(path)
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
    if version in SHUTTER_GATE_PROFILES:
        shutter_gate_file(header)
    if sha(header) != receipt.get('qemu_header_sha256'):
        raise ValueError('Scope observer QEMU API header identity changed')
    binary = ordinary_file(qemu_binary)
    if version in SHUTTER_GATE_PROFILES:
        shutter_gate_file(binary)
    if sha(binary) != receipt.get('qemu_sha256'):
        raise ValueError('Scope observer requires its matched plugin-enabled QEMU candidate')
    library = ordinary_file(receipt['library'])
    if version == PROFILE_V3:
        for path in (header, binary, library):
            v3_file(path)
        if receipt['qemu_header_sha256'] != V3_HEADER_SHA256 or receipt['qemu_sha256'] != V3_QEMU_SHA256:
            raise ValueError('Scope observer v3 requires the exact reviewed API7 header and QEMU')
    if version in SHUTTER_GATE_PROFILES:
        fixtures = validate_shutter_gate_build(native, root, receipt_path, receipt, expected, header, binary, library)
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
    if version in SHUTTER_GATE_PROFILES:
        result.update(trace_schema=receipt['trace_schema'], trace_schema_sha256=receipt['trace_schema_sha256'],
                      source_contract_sha256=receipt['source_contract_sha256'], fixture_source_sha256=fixtures,
                      plugin_build_command_sha256=receipt['plugin_build_command_sha256'],
                      readonly_import_audit_sha256=receipt['readonly_import_audit_sha256'],
                      candidate_static_audit_sha256=receipt['candidate_static_audit_sha256'])
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
    if build['profile'] in SHUTTER_GATE_PROFILES:
        shutter_gate_directory(output)
        if any(name in env for name in CHILD_ENV):
            raise ValueError('Shutter gate refuses raw child environment, including empty values')
        if os.path.lexists(output / 'readonly-scope-exit.json'):
            raise ValueError('Shutter gate refuses an old exit receipt in this run')
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
    if build['profile'] in SHUTTER_GATE_PROFILES:
        shutter_gate_file(destination)
        if validate_build(native, receipt_path, binary) != build or sha(destination) != library_sha:
            raise ValueError('Shutter gate assets changed during staging; retained incomplete run')
    env.update(zip(CHILD_ENV, (str(destination.resolve()), library_sha)))
    return dict(build, library=str(destination.resolve()), log=str(log.resolve()))


def record_exit(output, profile, process):
    """Preserve the actual owned wrapper result; this never signals a process."""
    if profile is None:
        return
    output = Path(output)
    log = output / 'readonly-scope-trace.log'
    if profile.get('profile') in SHUTTER_GATE_PROFILES:
        shutter_gate_directory(output)
        if os.path.lexists(log):
            shutter_gate_file(log)
    present = log.is_file() and not log.is_symlink()
    if profile.get('profile') not in SOURCE_SETS:
        raise ValueError('Scope observer exit requires its actual staged version')
    receipt = {'profile': profile['profile'], 'run': str(output.resolve()), 'owned_wrapper_pid': process.pid,
               'returncode': process.poll(), 'log_available': present,
               'log_sha256': sha(log) if present else None,
               'library_sha256': profile['library_sha256'],
               'capture_verified': False, 'physical_asic_compatibility_verified': False}
    with (output / 'readonly-scope-exit.json').open('x') as stream:
        if profile['profile'] in SHUTTER_GATE_PROFILES:
            os.fchmod(stream.fileno(), 0o600)
        json.dump(receipt, stream, indent=2)
        stream.write('\n')
        if profile['profile'] in SHUTTER_GATE_PROFILES:
            stream.flush()
            os.fsync(stream.fileno())
    if profile['profile'] in SHUTTER_GATE_PROFILES:
        shutter_gate_file(output / 'readonly-scope-exit.json')
        if present and sha(shutter_gate_file(log)) != receipt['log_sha256']:
            raise ValueError('Shutter gate trace changed while recording owned exit')
