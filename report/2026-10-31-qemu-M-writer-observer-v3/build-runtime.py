#!/usr/bin/env python3
"""Build a fresh v3 read-only observer receipt; never launch QEMU or a guest."""
from pathlib import Path
import argparse
import hashlib
import json
import os
import re
import stat
import struct
import subprocess

HERE = Path(__file__).resolve().parent
COMPONENT = '2026-10-31-qemu-M-writer-observer-v3'
PROFILE = 'qemu-readonly-scope-v3'
TRACE_SCHEMA = 'readonly_scope_v3'
QEMU_SHA256 = '4e85c70ba38774e9439562a7178a65bdbe6b660fdf8dd6bd4ece686fb707a4d4'
HEADER_SHA256 = '335d4e472067e914add598b60d1f7cf0dc029cd48f62f66656d6a88c54d8d9f9'
SOURCES = ('scope-observer.c', 'late-sites.inc', 'build-plugin.sh',
           'log-schema-v3.json', 'source-contract-v3.json',
           'check_run_context_v3.py', 'check_run_context.py',
           'integration/scope_trace_checks_v3.py', 'integration/scope_trace_checks.py')
FIXTURE_SOURCES = ('integration/fixture.S', 'integration/link.ld', 'integration/run_fixture.py',
                   'integration/test_fixture_driver.py', 'integration/test_actual_scope_plugin.py',
                   'integration/scope_trace_checks.py', 'integration/test_scope_trace_checks.py',
                   'integration/scope_trace_checks_v3.py')
API_CASES = ('anchor', 'one_byte_mutation', 'wrong_lr_only', 'producer',
             'producer_reverse_order', 'producer_corrupt', 'producer_short_tb')
API_ENV = ('A7C2_SCOPE_V3_TEST_QEMU', 'A7C2_SCOPE_V3_TEST_PLUGIN', 'A7C2_SCOPE_V3_TEST_OUTPUT',
           'A7C2_SCOPE_V3_TEST_SCHEMA', 'A7C2_SCOPE_V3_TEST_RECEIPT', 'A7C2_SCOPE_V3_TEST_FIXTURE_SOURCES')
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
    if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o022:
        raise ValueError('Builder requires owned ordinary files: ' + str(path))
    return path


def object_json(raw):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError('Duplicate build JSON field: ' + key)
            result[key] = value
        return result
    result = json.loads(raw, object_pairs_hook=unique)
    if type(result) is not dict:
        raise ValueError('Build JSON object required')
    return result


def symbols(text):
    return {line.split()[-1].split('@')[0] for line in text.splitlines() if line.split()}


def audit_readonly(imports, exports):
    required = {name for name in imports if name.startswith('qemu_plugin_')}
    if required != ALLOWED_IMPORTS or not required <= exports:
        raise ValueError('Plugin imports or candidate exports differ from the exact read-only API surface')


def source_hashes(names):
    return {name: sha(ordinary_file(HERE / name)) for name in names}


def validate_source_contract(before):
    declaration = object_json((HERE / 'log-schema-v3.json').read_bytes())
    contract = object_json((HERE / 'source-contract-v3.json').read_bytes())
    if (declaration.get('schema') != TRACE_SCHEMA or declaration.get('profile') != PROFILE or
            contract.get('schema') != 'readonly_scope_source_contract_v3' or
            contract.get('profile') != PROFILE or contract.get('trace_schema') != TRACE_SCHEMA or
            contract.get('trace_schema_sha256') != before['log-schema-v3.json'] or
            contract.get('actual_build_source_names_required') != list(SOURCES) or
            contract.get('actual_fixture_source_names_required') != list(FIXTURE_SOURCES) or
            contract.get('actualAPI_cases') != list(API_CASES) or
            contract.get('actualAPI_environment_names') != list(API_ENV) or
            any(key in contract for key in ('schema_sha256', 'log_schema_sha256', 'sourceDependencyFrozen'))):
        raise ValueError('Actual v3 schema/source-contract/runtime9/fixture8/API interface differs')


def build(candidate_audit):
    if HERE.resolve() != HERE or (HERE.parent.name, HERE.name) != ('report', COMPONENT):
        raise ValueError('Builder requires the fixed v3 component source root')
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
    scratch = HERE.parents[1] / 'runtime/analysis/scratch/functional-M-writer-v3-readonly-scope-plugin'
    if scratch.exists() and (scratch.resolve() != scratch or not scratch.is_dir() or
            scratch.stat().st_uid != os.getuid() or scratch.stat().st_mode & 0o022):
        raise ValueError('Untrusted v3 plugin scratch directory')
    old_work = set(scratch.iterdir()) if scratch.exists() else set()
    command = ['sh', str(HERE / 'build-plugin.sh')]
    result = subprocess.run(command, capture_output=True, text=True, timeout=180)
    if type(result.returncode) is not int or result.returncode:
        raise RuntimeError('Scope plugin compile failed; retain build log: ' + result.stdout + result.stderr)
    lines = result.stdout.splitlines()
    if len(lines) != 1:
        raise ValueError('Plugin builder did not return one new artifact')
    library = ordinary_file(lines[0])
    if (library.name != 'scope-observer.so' or library.parent.parent != scratch or
            not library.parent.name.startswith('build-') or library.parent in old_work or
            library.parent.stat().st_uid != os.getuid() or library.parent.stat().st_mode & 0o022):
        raise ValueError('Unexpected or reused v3 plugin build artifact path')
    with library.open('rb') as stream:
        header_bytes = stream.read(20)
    if (len(header_bytes) != 20 or header_bytes[:6] != b'\x7fELF\x02\x01' or
            struct.unpack_from('<HH', header_bytes, 16) != (3, 62)):
        raise ValueError('Scope observer requires an x86-64 host ELF shared plugin')
    library_sha = sha(library)
    with (library.parent / 'plugin-build-command.json').open('x') as stream:
        json.dump(dict(command=command, returncode=result.returncode, stdout=result.stdout, stderr=result.stderr), stream, indent=2)
        stream.write('\n')
    receipts = {}
    for name, command in (('imports', ['nm', '-D', '--undefined-only', str(library)]),
                          ('exports', ['nm', '-D', '--defined-only', str(qemu)]),
                          ('needed', ['readelf', '-d', str(library)])):
        proc = subprocess.run(command, capture_output=True, text=True, timeout=20)
        receipts[name] = {'command': command, 'returncode': proc.returncode,
                          'stdout': proc.stdout, 'stderr': proc.stderr}
        if type(proc.returncode) is not int or proc.returncode:
            with (library.parent / 'readonly-import-audit.json').open('x') as stream:
                json.dump(receipts, stream, indent=2)
            raise ValueError('Static plugin symbol inspection failed')
    with (library.parent / 'readonly-import-audit.json').open('x') as stream:
        json.dump(receipts, stream, indent=2)
        stream.write('\n')
    audit_readonly(symbols(receipts['imports']['stdout']), symbols(receipts['exports']['stdout']))
    if (before != source_hashes(SOURCES) or fixtures_before != source_hashes(FIXTURE_SOURCES) or
            sha(header) != header_sha or sha(qemu) != QEMU_SHA256 or sha(library) != library_sha or
            candidate_audit.read_bytes() != candidate_bytes):
        raise ValueError('Source/header/candidate/plugin changed during the plugin build')
    receipt = {'schema': PROFILE, 'plugin_api': 7, 'trace_schema': TRACE_SCHEMA,
               'trace_schema_sha256': before['log-schema-v3.json'],
               'source_contract_sha256': before['source-contract-v3.json'],
               'library': str(library), 'library_sha256': library_sha,
               'source_sha256': before, 'fixture_source_sha256': fixtures_before,
               'qemu_header_sha256': header_sha, 'qemu_sha256': QEMU_SHA256, 'qemu': str(qemu),
               'candidate_static_audit_sha256': hashlib.sha256(candidate_bytes).hexdigest(),
               'plugin_build_command_sha256': sha(library.parent / 'plugin-build-command.json'),
               'readonly_imports_verified': True,
               'readonly_import_audit_sha256': sha(library.parent / 'readonly-import-audit.json'),
               'runtime_verified': False, 'capture_verified': False,
               'physical_asic_compatibility_verified': False}
    path = library.parent / 'build-receipt.json'
    with path.open('x') as stream:
        json.dump(receipt, stream, indent=2)
        stream.write('\n')
    return path


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--candidate-audit', type=Path, required=True)
    args = parser.parse_args()
    print(build(args.candidate_audit))
