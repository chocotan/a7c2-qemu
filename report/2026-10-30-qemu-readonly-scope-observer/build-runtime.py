#!/usr/bin/env python3
"""Build once and bind a read-only host plugin to an independently built QEMU."""
from pathlib import Path
import argparse
import hashlib
import json
import re
import subprocess

HERE = Path(__file__).resolve().parent
SOURCES = ('scope-observer.c', 'late-sites.inc', 'build-plugin.sh',
           'log-schema-v2.json', 'source-contract-v2.json',
           'check_run_context_v2.py', 'check_run_context.py',
           'integration/scope_trace_checks_v2.py', 'integration/scope_trace_checks.py')
ALLOWED_IMPORTS = frozenset(('qemu_plugin_get_registers', 'qemu_plugin_read_register',
    'qemu_plugin_register_vcpu_init_cb', 'qemu_plugin_register_vcpu_tb_trans_cb',
    'qemu_plugin_register_vcpu_insn_exec_cb', 'qemu_plugin_register_atexit_cb',
    'qemu_plugin_tb_n_insns', 'qemu_plugin_tb_get_insn', 'qemu_plugin_insn_vaddr',
    'qemu_plugin_insn_size', 'qemu_plugin_insn_data'))


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def symbols(text):
    return {line.split()[-1].split('@')[0] for line in text.splitlines() if line.split()}


def audit_readonly(imports, exports):
    required = {name for name in imports if name.startswith('qemu_plugin_')}
    if required != ALLOWED_IMPORTS or not required <= exports:
        raise ValueError('Plugin imports or candidate exports differ from the exact read-only API surface')


def build(candidate_audit):
    candidate_audit = Path(candidate_audit).resolve()
    candidate_bytes = candidate_audit.read_bytes()
    candidate = json.loads(candidate_bytes)
    qemu = Path(candidate['binary'])
    if not qemu.is_absolute() or qemu.is_symlink() or sha(qemu) != candidate['binary_sha256']:
        raise ValueError('Candidate QEMU differs from its static build audit')
    if candidate['missing_required_exports'] or not all(candidate['protected_binaries_unchanged'].values()):
        raise ValueError('Candidate static audit is incomplete')
    header = HERE.parents[1] / 'source/build/qemu-SRBXNK/qemu-11.1.2/include/plugins/qemu-plugin.h'
    before = {name: sha(HERE / name) for name in SOURCES}
    header_sha = sha(header)
    if not re.search(rb'^#define QEMU_PLUGIN_VERSION 7\s*$', header.read_bytes(), re.M):
        raise ValueError('Unreviewed plugin API header')
    result = subprocess.run(['sh', str(HERE / 'build-plugin.sh')], capture_output=True, text=True, timeout=180)
    if result.returncode:
        raise RuntimeError('Scope plugin compile failed; retain build log: ' + result.stdout + result.stderr)
    lines = result.stdout.splitlines()
    if len(lines) != 1:
        raise ValueError('Plugin builder did not return one new artifact')
    library = Path(lines[0])
    scratch = HERE.parents[1] / 'runtime/analysis/scratch/functional-M-v2-readonly-scope-plugin'
    if (not library.is_absolute() or library.is_symlink() or library.name != 'scope-observer.so' or
            library.parent.parent != scratch or not library.parent.name.startswith('build-')):
        raise ValueError('Unexpected plugin build artifact path')
    receipts = {}
    for name, command in (('imports', ['nm', '-D', '--undefined-only', str(library)]),
                          ('exports', ['nm', '-D', '--defined-only', str(qemu)]),
                          ('needed', ['readelf', '-d', str(library)])):
        proc = subprocess.run(command, capture_output=True, text=True, timeout=20)
        receipts[name] = {'command': command, 'returncode': proc.returncode,
                          'stdout': proc.stdout, 'stderr': proc.stderr}
        if proc.returncode:
            with (library.parent / 'readonly-import-audit.json').open('x') as stream:
                json.dump(receipts, stream, indent=2)
            raise ValueError('Static plugin symbol inspection failed')
    with (library.parent / 'readonly-import-audit.json').open('x') as stream:
        json.dump(receipts, stream, indent=2)
        stream.write('\n')
    audit_readonly(symbols(receipts['imports']['stdout']), symbols(receipts['exports']['stdout']))
    if (before != {name: sha(HERE / name) for name in SOURCES} or sha(header) != header_sha or
            sha(qemu) != candidate['binary_sha256'] or candidate_audit.read_bytes() != candidate_bytes):
        raise ValueError('Source/header/candidate changed during the plugin build')
    receipt = {'schema': 'qemu-readonly-scope-v2', 'plugin_api': 7,
               'trace_schema': 'readonly_scope_v2',
               'trace_schema_sha256': before['log-schema-v2.json'],
               'source_contract_sha256': before['source-contract-v2.json'],
               'library': str(library), 'library_sha256': sha(library),
               'source_sha256': before, 'qemu_header_sha256': header_sha,
               'qemu_sha256': candidate['binary_sha256'], 'qemu': str(qemu),
               'candidate_static_audit_sha256': hashlib.sha256(candidate_bytes).hexdigest(),
               'readonly_imports_verified': True, 'readonly_import_audit_sha256': sha(library.parent / 'readonly-import-audit.json'),
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
