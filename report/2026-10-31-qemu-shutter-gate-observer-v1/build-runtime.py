#!/usr/bin/env python3
"""Build a fresh shutter-gate read-only receipt; never launch QEMU or a guest."""
from pathlib import Path
import argparse
import hashlib
import json
import math
import os
import re
import stat
import struct
import subprocess

HERE = Path(__file__).resolve().parent
COMPONENT = '2026-10-31-qemu-shutter-gate-observer-v1'
PROFILE = 'qemu-readonly-shutter-gate-v1'
TRACE_SCHEMA = 'readonly_shutter_gate_v1'
SCHEMA_FILE = 'log-schema-shutter-gate-v1.json'
CONTRACT_FILE = 'source-contract-shutter-gate-v1.json'
SCRATCH = 'runtime/analysis/scratch/functional-shutter-gate-v1-readonly-plugin'
QEMU_SHA256 = '4e85c70ba38774e9439562a7178a65bdbe6b660fdf8dd6bd4ece686fb707a4d4'
HEADER_SHA256 = '335d4e472067e914add598b60d1f7cf0dc029cd48f62f66656d6a88c54d8d9f9'
SOURCES = ('scope-observer.c', 'build-plugin.sh', 'build-runtime.py',
           SCHEMA_FILE, CONTRACT_FILE, 'check_shutter_gate_v1.py',
           'integration/shutter_gate_trace_checks_v1.py')
FIXTURE_SOURCES = ('integration/fixture.S', 'integration/link.ld', 'integration/run_fixture.py',
                   'integration/test_fixture_driver.py', 'integration/test_actual_scope_plugin.py',
                   'integration/test_shutter_gate_trace_checks_v1.py',
                   'integration/shutter_gate_trace_checks_v1.py')
API_CASES = ('original_entry', 'existing_main_stub_entry', 'one_byte_gate_mutation', 'short_tb')
API_ENV = ('A7C2_SHUTTER_GATE_V1_TEST_QEMU', 'A7C2_SHUTTER_GATE_V1_TEST_PLUGIN',
           'A7C2_SHUTTER_GATE_V1_TEST_OUTPUT', 'A7C2_SHUTTER_GATE_V1_TEST_SCHEMA',
           'A7C2_SHUTTER_GATE_V1_TEST_RECEIPT', 'A7C2_SHUTTER_GATE_V1_TEST_FIXTURE_SOURCES')
FORBIDDEN_ALIASES = frozenset(('source_root', 'Source_root', 'root', 'sourceDependencyFrozen',
    'schema_sha256', 'log_schema_sha256', 'v3_schema_sha256'))
ALLOWED_IMPORTS = frozenset(('qemu_plugin_get_registers', 'qemu_plugin_read_register',
    'qemu_plugin_register_vcpu_init_cb', 'qemu_plugin_register_vcpu_tb_trans_cb',
    'qemu_plugin_register_vcpu_insn_exec_cb', 'qemu_plugin_register_atexit_cb',
    'qemu_plugin_tb_n_insns', 'qemu_plugin_tb_get_insn', 'qemu_plugin_insn_vaddr',
    'qemu_plugin_insn_size', 'qemu_plugin_insn_data'))


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def ordinary_file(value):
    path = Path(value)
    if not path.is_absolute() or path.resolve() != path:
        raise ValueError('Builder requires canonical absolute paths: ' + str(path))
    info = path.lstat()
    if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or
            info.st_nlink != 1 or info.st_mode & 0o022):
        raise ValueError('Builder requires owned single-link ordinary files: ' + str(path))
    return path


def ordinary_directory(value):
    path = Path(value)
    if not path.is_absolute() or path.resolve() != path:
        raise ValueError('Builder requires canonical absolute directories: ' + str(path))
    info = path.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o022:
        raise ValueError('Builder requires owned ordinary directories: ' + str(path))
    return path


def object_json(raw):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError('Duplicate build JSON field: ' + key)
            result[key] = value
        return result
    def finite(value):
        number = float(value)
        if not math.isfinite(number):
            raise ValueError('Non-finite build JSON number: ' + value)
        return number
    result = json.loads(raw, object_pairs_hook=unique, parse_float=finite, parse_constant=finite)
    if type(result) is not dict:
        raise ValueError('Build JSON object required')
    return result


def exclusive_json(path, data):
    ordinary_directory(path.parent)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'w', encoding='ascii') as stream:
        json.dump(data, stream, indent=2)
        stream.write('\n')
        stream.flush()
        os.fsync(stream.fileno())
    ordinary_file(path)


def symbols(text):
    return {line.split()[-1].split('@')[0] for line in text.splitlines() if line.split()}


def audit_readonly(imports, exports):
    required = {name for name in imports if name.startswith('qemu_plugin_')}
    if required != ALLOWED_IMPORTS or not required <= exports:
        raise ValueError('Plugin imports or candidate exports differ from the exact read-only API surface')


def source_hashes(names):
    return {name: sha(ordinary_file(HERE / name)) for name in names}


def validate_source_contract(before):
    declaration = object_json((HERE / SCHEMA_FILE).read_bytes())
    contract = object_json((HERE / CONTRACT_FILE).read_bytes())
    if (declaration.get('schema') != TRACE_SCHEMA or declaration.get('profile') != PROFILE or
            contract.get('schema') != 'readonly_shutter_gate_source_contract_v1' or
            contract.get('profile') != PROFILE or contract.get('trace_schema') != TRACE_SCHEMA or
            contract.get('trace_schema_sha256') != before[SCHEMA_FILE] or
            contract.get('actual_build_source_names_required') != list(SOURCES) or
            contract.get('actual_fixture_source_names_required') != list(FIXTURE_SOURCES) or
            contract.get('actualAPI_cases') != list(API_CASES) or
            contract.get('actualAPI_environment_names') != list(API_ENV) or
            'source_contract_sha256' in contract or
            any(FORBIDDEN_ALIASES & data.keys() for data in (declaration, contract))):
        raise ValueError('Actual shutter-gate-v1 schema/source-contract/source7/fixture7/API interface differs')


def build(candidate_audit):
    if HERE.resolve() != HERE or (HERE.parent.name, HERE.name) != ('report', COMPONENT):
        raise ValueError('Builder requires the fixed shutter-gate-v1 component source root')
    ordinary_directory(HERE)
    candidate_audit = ordinary_file(candidate_audit)
    candidate_bytes = candidate_audit.read_bytes()
    candidate = object_json(candidate_bytes)
    qemu = ordinary_file(candidate['binary'])
    if candidate.get('binary_sha256') != QEMU_SHA256 or sha(qemu) != QEMU_SHA256:
        raise ValueError('Candidate QEMU differs from its reviewed static build audit')
    protected = candidate.get('protected_binaries_unchanged')
    if (candidate.get('missing_required_exports') != [] or type(protected) is not dict or
            set(protected) != {'candidate', 'production'} or any(value is not True for value in protected.values()) or
            any(candidate.get(key) is not False for key in
                ('runtime_library_closure_verified', 'plugin_runtime_verified', 'capture_verified',
                 'physical_asic_compatibility_verified'))):
        raise ValueError('Candidate static audit is incomplete or promotes runtime claims')
    header = ordinary_file(HERE.parents[1] / 'source/build/qemu-SRBXNK/qemu-11.1.2/include/plugins/qemu-plugin.h')
    before = source_hashes(SOURCES)
    fixtures_before = source_hashes(FIXTURE_SOURCES)
    validate_source_contract(before)
    header_sha = sha(header)
    if header_sha != HEADER_SHA256 or not re.search(rb'^#define QEMU_PLUGIN_VERSION 7\s*$', header.read_bytes(), re.M):
        raise ValueError('Unreviewed plugin API7 header')
    scratch = HERE.parents[1] / SCRATCH
    ordinary_directory(scratch.parent)
    if scratch.resolve() != scratch:
        raise ValueError('Untrusted shutter-gate-v1 plugin scratch directory')
    scratch.mkdir(mode=0o700, exist_ok=True)
    ordinary_directory(scratch)
    old_work = set(scratch.iterdir())
    command = ['sh', str(HERE / 'build-plugin.sh')]
    result = subprocess.run(command, capture_output=True, text=True, timeout=180)
    lines = result.stdout.splitlines()
    if len(lines) != 1:
        raise ValueError('Plugin builder did not return one new artifact; rc=' + str(result.returncode) +
                         ' stdout=' + repr(result.stdout) + ' stderr=' + repr(result.stderr))
    library = Path(lines[0])
    work = ordinary_directory(library.parent)
    if (library.name != 'scope-observer.so' or work.parent != scratch or
            not work.name.startswith('build-') or work in old_work):
        raise ValueError('Unexpected or reused shutter-gate-v1 plugin build artifact path')
    exclusive_json(work / 'plugin-build-command.json', dict(command=command,
        returncode=result.returncode, stdout=result.stdout, stderr=result.stderr))
    if type(result.returncode) is not int or result.returncode:
        raise RuntimeError('Scope plugin compile failed; rc=' + str(result.returncode) + '; retain ' + str(work))
    ordinary_file(library)
    with library.open('rb') as stream:
        header_bytes = stream.read(20)
    if (len(header_bytes) != 20 or header_bytes[:6] != b'\x7fELF\x02\x01' or
            struct.unpack_from('<HH', header_bytes, 16) != (3, 62)):
        raise ValueError('Scope observer requires an x86-64 host ELF shared plugin')
    library_sha = sha(library)
    receipts = {}
    for name, command in (('imports', ['nm', '-D', '--undefined-only', str(library)]),
                          ('exports', ['nm', '-D', '--defined-only', str(qemu)]),
                          ('needed', ['readelf', '-d', str(library)])):
        proc = subprocess.run(command, capture_output=True, text=True, timeout=20)
        receipts[name] = {'command': command, 'returncode': proc.returncode,
                          'stdout': proc.stdout, 'stderr': proc.stderr}
        if type(proc.returncode) is not int or proc.returncode:
            exclusive_json(work / 'readonly-import-audit.json', receipts)
            raise ValueError('Static plugin symbol inspection failed')
    imports = symbols(receipts['imports']['stdout'])
    receipts.update(qemu_plugin_imports=sorted(name for name in imports if name.startswith('qemu_plugin_')),
                    ordinary_imports=sorted(name for name in imports if not name.startswith('qemu_plugin_')),
                    dt_needed=re.findall(r'\(NEEDED\).*\[([^\]]+)\]', receipts['needed']['stdout']))
    exclusive_json(work / 'readonly-import-audit.json', receipts)
    audit_readonly(imports, symbols(receipts['exports']['stdout']))
    if (before != source_hashes(SOURCES) or fixtures_before != source_hashes(FIXTURE_SOURCES) or
            sha(ordinary_file(header)) != header_sha or sha(ordinary_file(qemu)) != QEMU_SHA256 or
            sha(ordinary_file(library)) != library_sha or
            ordinary_file(candidate_audit).read_bytes() != candidate_bytes):
        raise ValueError('Source/header/candidate/plugin changed during the plugin build')
    receipt = {'schema': PROFILE, 'plugin_api': 7, 'trace_schema': TRACE_SCHEMA,
               'trace_schema_sha256': before[SCHEMA_FILE],
               'source_contract_sha256': before[CONTRACT_FILE],
               'library': str(library), 'library_sha256': library_sha,
               'source_sha256': before, 'fixture_source_sha256': fixtures_before,
               'qemu_header_sha256': header_sha, 'qemu_sha256': QEMU_SHA256, 'qemu': str(qemu),
               'candidate_static_audit_sha256': hashlib.sha256(candidate_bytes).hexdigest(),
               'plugin_build_command_sha256': sha(ordinary_file(work / 'plugin-build-command.json')),
               'readonly_imports_verified': True,
               'readonly_import_audit_sha256': sha(ordinary_file(work / 'readonly-import-audit.json')),
               'runtime_verified': False, 'capture_verified': False,
               'physical_asic_compatibility_verified': False}
    path = work / 'build-receipt.json'
    exclusive_json(path, receipt)
    return path


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--candidate-audit', type=Path, required=True)
    args = parser.parse_args()
    print(build(args.candidate_audit))
