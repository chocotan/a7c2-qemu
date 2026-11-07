#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""SOURCE_ONLY / NOT_RUN: parent driver for four self-owned shutter-gate-v2 cases.

Importing never builds, starts a process, or loads the peer reader. The direct
reader is required only after the parent has integrated/frozen both source7 roles.
"""
import argparse
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import re
import shutil
import signal
import stat
import struct
import subprocess
import sys

BASE = 0x40000000
STACK = BASE + 0x200000
RECORD = BASE + 0x100000
SOURCE_WORD = BASE + 0x102000
ENTRY = BASE + 0x1AF16DC
SOURCE_PC = BASE + 0x1AF1830
GATE = BASE + 0x1AF1834
TARGET = BASE + 0x1AF1724
FALLTHROUGH = BASE + 0x1AF1838
ENTRY_RETURN = BASE + 0x90100
BL_RETURN = BASE + 0x1AF1840
TTBR = 0x0001000040081000
MMU_L1 = BASE + 0x81000
MMU_L2 = BASE + 0x82000
VECTORS = BASE + 0x83000
TPIDR = 0x89ABCDEF01234567
RECORD_BYTES = 408
FRAME_BYTES = 4 * RECORD_BYTES
ROUNDS = 41
QUOTA = 16
W0_INPUTS = (0, 1, 0, 0xFFFFFFFF, 0, 0x80000000, 0, 1)
NZCV_INPUTS = (0xA0000000, 0x60000000, 0x30000000, 0x90000000)
# The copied guest bytes retain their original V1 console marker.
HEADER = b'SHUTTER_GATE_FIXTURE_V1\n'
RECORDS_MARKER = b'\nSHUTTER_GATE_RECORDS_OK\n'
TRAILER = b'\nSHUTTER_GATE_FIXTURE_OK warmup=1 entries=40 gates=41\n'
ORIGINAL16 = bytes.fromhex('fd7bbba9fd030091f55b02a9f603012a')
STUB8 = bytes.fromhex('5000005800021fd6')
GATE8 = bytes.fromhex('000040b980f7ff35')
TARGET8 = bytes.fromhex('b3230191e00313aa')
FALLTHROUGH8 = bytes.fromhex('e00313aa44b12894')
SITES = ('final_entry', 'd570_cbnz_pre', 'successor_1724_pre', 'successor_1838_pre', 'd570_ldr_pre')
ENTRY_REGS = ('x0', 'x1', 'x2', 'x3', 'x30')
INTERNAL_REGS = ('x0', 'x19', 'x22', 'x23', 'x29', 'x30')
CODE_SECTIONS = ('.boot', '.replay', '.resume', '.entry', '.target', '.gate', '.sink')
COMPONENT = '2026-11-02-qemu-shutter-gate-observer-v2'
NATIVE_COMPONENT = '2026-10-17-qemu-native-camera'
COMPONENT_RELATIVE = Path('final/a7c2-re/report') / NATIVE_COMPONENT / 'report' / COMPONENT
PROFILE = 'qemu-readonly-shutter-gate-v2'
SCHEMA = 'readonly_shutter_gate_v2'
SCHEMA_FILE = 'log-schema-shutter-gate-v2.json'
CONTRACT_FILE = 'source-contract-shutter-gate-v2.json'
CONTRACT_SCHEMA = 'readonly_shutter_gate_source_contract_v2'
QEMU_SHA256 = '4e85c70ba38774e9439562a7178a65bdbe6b660fdf8dd6bd4ece686fb707a4d4'
HEADER_SHA256 = '335d4e472067e914add598b60d1f7cf0dc029cd48f62f66656d6a88c54d8d9f9'
API_CASES = ('original_entry', 'existing_main_stub_entry', 'one_byte_gate_mutation', 'short_tb')
API_ENV = tuple('A7C2_SHUTTER_GATE_V2_TEST_' + suffix for suffix in
                ('QEMU', 'PLUGIN', 'OUTPUT', 'SCHEMA', 'RECEIPT', 'FIXTURE_SOURCES'))
FIXTURE_SOURCES = ('fixture.S', 'link.ld', 'run_fixture.py', 'test_fixture_driver.py',
                   'test_actual_scope_plugin.py', 'test_shutter_gate_trace_checks_v2.py',
                   'shutter_gate_trace_checks_v2.py')
FIXTURE_SOURCE_NAMES = frozenset('integration/' + name for name in FIXTURE_SOURCES)
RUNTIME_SOURCES = ('scope-observer.c', 'build-plugin.sh', 'build-runtime.py', SCHEMA_FILE,
                   CONTRACT_FILE, 'check_shutter_gate_v2.py', 'integration/shutter_gate_trace_checks_v2.py')
QEMU_IMPORTS = frozenset('qemu_plugin_' + name for name in
    ('get_registers', 'read_register', 'register_vcpu_init_cb', 'register_vcpu_tb_trans_cb',
     'register_vcpu_insn_exec_cb', 'register_atexit_cb', 'tb_n_insns', 'tb_get_insn',
     'insn_vaddr', 'insn_size', 'insn_data'))
FORBIDDEN_ALIASES = frozenset(('source_root', 'Source_root', 'root', 'sourceDependencyFrozen',
                              'schema_sha256', 'log_schema_sha256', 'v3_schema_sha256'))
SOURCE = Path(__file__).absolute().parent
LIMIT = 2 * 1024 * 1024


class FixtureError(ValueError):
    pass


def require(condition, message):
    if not condition:
        raise FixtureError(message)


def object_json(raw):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            require(key not in result, 'duplicate JSON field: ' + key)
            result[key] = value
        return result
    def finite(value):
        result = float(value)
        require(math.isfinite(result), 'nonfinite JSON number')
        return result
    result = json.loads(raw, object_pairs_hook=unique, parse_float=finite, parse_constant=finite)
    require(type(result) is dict, 'JSON object required')
    return result


def ordinary_file(value):
    path = Path(value)
    require(path.is_absolute() and path.resolve() == path, 'canonical absolute file required: ' + str(path))
    info = path.lstat()
    require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1 and
            info.st_uid == os.getuid() and not info.st_mode & 0o022,
            'owned ordinary file required: ' + str(path))
    return path


def file_stamp(info):
    return (info.st_dev, info.st_ino, info.st_mode, info.st_uid, info.st_nlink,
            info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def sha256(value):
    path = ordinary_file(value)
    before = file_stamp(path.stat())
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(65536), b''):
            digest.update(block)
    require(before == file_stamp(path.stat()), 'artifact changed while hashing: ' + str(path))
    return digest.hexdigest()


def read_small(value):
    path = ordinary_file(value)
    before = path.stat()
    require(before.st_size <= LIMIT, 'artifact exceeds size limit: ' + str(path))
    raw = path.read_bytes()
    require(file_stamp(before) == file_stamp(path.stat()) and len(raw) == before.st_size,
            'artifact changed while reading: ' + str(path))
    return raw


def project_root():
    for parent in SOURCE.parents:
        if (parent / 'AGENTS.md').is_file() and (parent / 'final/a7c2-re/AGENTS.md').is_file():
            return parent
    raise FixtureError('cannot locate project root; integrate the draft before execution')


def private_root():
    return project_root() / 'analysis/scratch/functional-shutter-gate-v2-actualapi-fixture'


def validate_paths(qemu, plugin, output):
    paths = [Path(value) for value in (qemu, plugin, output)]
    require(all(path.is_absolute() and path.resolve() == path for path in paths),
            'explicit canonical absolute QEMU/plugin/output paths required')
    qemu, plugin, output = paths
    ordinary_file(qemu)
    ordinary_file(plugin)
    require(os.access(qemu, os.X_OK | os.R_OK) and qemu.stat().st_size > 0 and plugin.stat().st_size > 0,
            'explicit nonempty executable QEMU/readable plugin required')
    root = private_root()
    require(root.resolve() == root and output != root and root in output.parents,
            'output must be a new child of ' + str(root))
    for parent in (output, *output.parents):
        if parent == root.parent:
            break
        if parent.exists():
            info = parent.lstat()
            require(stat.S_ISDIR(info.st_mode) and info.st_uid == os.getuid() and not info.st_mode & 0o022,
                    'untrusted private output ancestor: ' + str(parent))
    require(not output.exists(), 'refusing to reuse output: ' + str(output))
    return qemu, plugin, output


def validate_digest_map(value, names, description):
    require(type(value) is dict and set(value) == set(names), description + ' exact source set differs')
    require(all(type(digest) is str and re.fullmatch('[0-9a-f]{64}', digest) for digest in value.values()),
            description + ' invalid source digest')


def symbols(text):
    require(type(text) is str, 'symbol audit output must be text')
    return {line.split()[-1].split('@')[0] for line in text.splitlines() if line.split()}


def validate_assets(qemu, plugin, schema, receipt, fixture_source_sha256):
    """Consume new builder receipt without invoking it or selecting a source root."""
    root = SOURCE.parent
    require(root == project_root() / COMPONENT_RELATIVE and root.resolve() == root,
            'fixed shutter-gate component root required; draft is not runnable in place')
    schema, receipt = ordinary_file(schema), ordinary_file(receipt)
    schema_bytes, receipt_bytes = read_small(schema), read_small(receipt)
    build, declaration = object_json(receipt_bytes), object_json(schema_bytes)
    require(not FORBIDDEN_ALIASES & build.keys(), 'forbidden receipt root/schema alias')
    require(build.get('schema') == PROFILE and build.get('trace_schema') == SCHEMA and
            type(build.get('plugin_api')) is int and build['plugin_api'] == 7 and
            build.get('readonly_imports_verified') is True, 'new shutter-gate API7 receipt required')
    require(all(build.get(key) is False for key in
                ('runtime_verified', 'capture_verified', 'physical_asic_compatibility_verified')),
            'build receipt promotes runtime/capture/physical claims')
    schema_digest = hashlib.sha256(schema_bytes).hexdigest()
    require(schema == root / SCHEMA_FILE and build.get('trace_schema_sha256') == schema_digest and
            declaration.get('schema') == SCHEMA and declaration.get('profile') == PROFILE,
            'actual new schema/root/digest differs')
    require(build.get('qemu') == str(qemu) and build.get('qemu_sha256') == QEMU_SHA256 == sha256(qemu),
            'QEMU is not the unchanged 4e85 candidate')
    require(build.get('library') == str(plugin) and build.get('library_sha256') == sha256(plugin),
            'plugin differs from build receipt')
    sources = build.get('source_sha256')
    validate_digest_map(sources, RUNTIME_SOURCES, 'runtime7')
    validate_digest_map(fixture_source_sha256, FIXTURE_SOURCE_NAMES, 'parent fixture7')
    validate_digest_map(build.get('fixture_source_sha256'), FIXTURE_SOURCE_NAMES, 'build fixture7')
    require(build['fixture_source_sha256'] == fixture_source_sha256, 'parent/build fixture7 differ')
    inputs = {'qemu': {'path': str(qemu), 'sha256': QEMU_SHA256},
              'plugin': {'path': str(plugin), 'sha256': build['library_sha256']},
              'schema': {'path': str(schema), 'sha256': schema_digest},
              'receipt': {'path': str(receipt), 'sha256': hashlib.sha256(receipt_bytes).hexdigest()}}
    for prefix, closure in (('source:', sources), ('fixture-source:', fixture_source_sha256)):
        for name, digest in closure.items():
            original = root / name
            require(hashlib.sha256(read_small(original)).hexdigest() == digest, 'source changed: ' + name)
            inputs[prefix + name] = {'path': str(original), 'sha256': digest}
    require(sources[SCHEMA_FILE] == schema_digest and
            build.get('source_contract_sha256') == sources[CONTRACT_FILE], 'schema/contract closure differs')
    contract = object_json(read_small(root / CONTRACT_FILE))
    require(not (FORBIDDEN_ALIASES | {'source_contract_sha256'}) & contract.keys(),
            'contract has forbidden alias or recursive self hash')
    require(contract.get('schema') == CONTRACT_SCHEMA and contract.get('profile') == PROFILE and
            contract.get('trace_schema') == SCHEMA and contract.get('trace_schema_sha256') == schema_digest and
            contract.get('actual_build_source_names_required') == list(RUNTIME_SOURCES) and
            contract.get('actual_fixture_source_names_required') == ['integration/' + name for name in FIXTURE_SOURCES] and
            contract.get('actualAPI_cases') == list(API_CASES) and
            contract.get('actualAPI_environment_names') == list(API_ENV),
            'source7/fixture7/cases/env contract differs')
    header = root.parents[1] / 'source/build/qemu-SRBXNK/qemu-11.1.2/include/plugins/qemu-plugin.h'
    header_bytes = read_small(header)
    require(hashlib.sha256(header_bytes).hexdigest() == HEADER_SHA256 == build.get('qemu_header_sha256') and
            re.search(rb'^#define QEMU_PLUGIN_VERSION 7\s*$', header_bytes, re.M), 'reviewed API7 header differs')
    inputs['qemu_header'] = {'path': str(header), 'sha256': HEADER_SHA256}
    audit = receipt.with_name('readonly-import-audit.json')
    audit_bytes = read_small(audit)
    require(hashlib.sha256(audit_bytes).hexdigest() == build.get('readonly_import_audit_sha256'),
            'read-only import audit differs')
    audit_data = object_json(audit_bytes)
    commands = {'imports': ['nm', '-D', '--undefined-only', str(plugin)],
                'exports': ['nm', '-D', '--defined-only', str(qemu)],
                'needed': ['readelf', '-d', str(plugin)]}
    require(set(audit_data) == {'imports', 'exports', 'needed', 'qemu_plugin_imports',
                                'ordinary_imports', 'dt_needed'}, 'incomplete static import audit')
    for role, command in commands.items():
        item = audit_data[role]
        require(type(item) is dict and item.get('command') == command and
                type(item.get('returncode')) is int and item['returncode'] == 0 and
                type(item.get('stdout')) is str and type(item.get('stderr')) is str,
                'incomplete static import audit command')
    all_imports = symbols(audit_data['imports']['stdout'])
    imports = {name for name in all_imports if name.startswith('qemu_plugin_')}
    require(imports == QEMU_IMPORTS and imports <= symbols(audit_data['exports']['stdout']) and
            audit_data['qemu_plugin_imports'] == sorted(imports) and
            audit_data['ordinary_imports'] == sorted(all_imports - imports) and
            audit_data['dt_needed'] == re.findall(r'\(NEEDED\).*\[([^\]]+)\]', audit_data['needed']['stdout']),
            'exact11 imports/candidate exports or ordinary dependency audit differ')
    inputs['readonly_import_audit'] = {'path': str(audit), 'sha256': hashlib.sha256(audit_bytes).hexdigest()}
    return inputs, declaration


def verify_fixture_snapshots(output, expected):
    validate_digest_map(expected, FIXTURE_SOURCE_NAMES, 'fixture7 snapshot')
    snapshots = {}
    for name in FIXTURE_SOURCES:
        key = 'integration/' + name
        original, copied = SOURCE / name, output / 'inputs' / name
        raw, staged = read_small(original), read_small(copied)
        require(hashlib.sha256(raw).hexdigest() == expected[key] and raw == staged,
                'fixture source/snapshot changed: ' + key)
        snapshots[key] = {'source_path': str(original), 'snapshot_path': str(copied),
                          'sha256': expected[key], 'bytes': len(staged)}
    return snapshots


def load_checks():
    """Only the integrated, newly frozen direct reader; no legacy raw conversion."""
    path = ordinary_file(SOURCE / 'shutter_gate_trace_checks_v2.py')
    spec = importlib.util.spec_from_file_location('selfowned_shutter_gate_trace_checks_v2', path)
    checks = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(checks)
    require(callable(getattr(checks, 'parse_trace', None)) and
            callable(getattr(checks, 'assert_shutter_gate_trace_v2', None)), 'direct reader API missing')
    return checks


def tool(name):
    found = shutil.which(name)
    require(found is not None, 'required tool unavailable; no skip/fallback: ' + name)
    path = Path(found).resolve()
    require(Path('/usr') in path.parents, 'tool must be in read-only /usr: ' + str(path))
    return str(path)


def sandbox(output, mounts):
    command = [tool('bwrap'), '--unshare-all', '--die-with-parent', '--new-session', '--clearenv',
               '--cap-drop', 'ALL', '--ro-bind', '/usr', '/usr', '--symlink', 'usr/bin', '/bin',
               '--symlink', 'usr/lib', '/lib', '--symlink', 'usr/lib', '/lib64',
               '--proc', '/proc', '--dev', '/dev', '--tmpfs', '/tmp', '--dir', '/in',
               '--dir', '/work', '--chdir', '/work', '--setenv', 'HOME', '/tmp',
               '--setenv', 'TMPDIR', '/tmp', '--setenv', 'LANG', 'C',
               '--setenv', 'PATH', '/usr/bin:/bin', '--bind', str(output), '/out']
    for host, guest in mounts:
        command += ['--ro-bind', str(host), guest]
    return command


def launch(output, relative, payload, mounts, commands, seconds, existing_log=None):
    """Retain exact argv/raw return and byte outputs, including all failures."""
    directory = output / relative
    directory.mkdir(parents=True, exist_ok=False, mode=0o700)
    if existing_log is not None:
        with (directory / 'plugin.log').open('xb') as stream:
            stream.write(existing_log)
    command = sandbox(directory, mounts) + [tool('timeout'), '--signal=TERM', '--verbose', f'{seconds}s'] + payload
    record = {'command': command, 'payload_argv': payload, 'directory': relative, 'limit_seconds': seconds,
              'returncode': None, 'outer_timeout': False, 'owned_pid_unreaped': None}
    commands.append(record)
    with (directory / 'stdout.bin').open('xb') as stdout, (directory / 'stderr.bin').open('xb') as stderr:
        process = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=stdout, stderr=stderr,
                                   env={'PATH': '/usr/bin:/bin', 'LANG': 'C'}, start_new_session=True)
        try:
            record['returncode'] = process.wait(timeout=seconds + 10)
        except BaseException as error:
            record['outer_timeout'] = isinstance(error, subprocess.TimeoutExpired)
            record['wait_error'] = {'type': type(error).__name__, 'message': str(error)}
            if process.poll() is None:
                # Reuse v3's owned-Popen cleanup; never discover or signal other PIDs.
                process.send_signal(signal.SIGTERM)
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    record['owned_pid_unreaped'] = process.pid
            record['returncode'] = process.poll()
            raise
    return record


def vm_command(plugin_arguments, short_tb=False):
    command = ['/qemu', '-no-user-config', '-machine', 'virt,secure=off,virtualization=off,gic-version=2',
               '-accel', 'tcg,thread=single' + (',one-insn-per-tb=on' if short_tb else ''),
               '-cpu', 'cortex-a35', '-smp', 'cpus=1,maxcpus=1', '-m', '64M',
               '-nodefaults', '-nographic', '-display', 'none', '-serial', 'none', '-monitor', 'none',
               '-nic', 'none', '-no-reboot', '-kernel', '/in/fixture.elf',
               '-chardev', 'file,id=semi,path=/out/console.bin',
               '-semihosting-config', 'enable=on,target=native,chardev=semi']
    if plugin_arguments is not None:
        command += ['-plugin', '/observer.so' + (',' + ','.join(plugin_arguments) if plugin_arguments else '')]
    return command


def branch_target(word, pc, opcode):
    require(word >> 26 == opcode, f'unexpected branch at {pc:#x}')
    immediate = word & 0x03FFFFFF
    if immediate & 0x02000000:
        immediate -= 0x04000000
    return pc + immediate * 4


def elf_layout(blob, case):
    """Bounded ELF parsing is restricted to the newly built self-owned guest."""
    require(case in API_CASES, 'unknown fixture case')
    def unpack(fmt, offset):
        require(0 <= offset <= len(blob) - struct.calcsize(fmt), 'truncated ELF table')
        return struct.unpack_from(fmt, blob, offset)
    require(len(blob) <= LIMIT, 'sparse fixture ELF unexpectedly large')
    h = unpack('<16sHHIQQQIHHHHHH', 0)
    require(h[0][:7] == b'\x7fELF\x02\x01\x01' and h[1:4] == (2, 183, 1), 'AArch64 LE ET_EXEC required')
    require(h[4] == BASE + 0x80000 and h[8] == 64 and h[9] == 56 and h[10] == 10 and
            h[11] == 64 and 1 <= h[12] <= 64 and h[13] < h[12], 'unexpected ELF tables/entry')
    loads = []
    for i in range(h[10]):
        p = unpack('<IIQQQQQQ', h[5] + 56 * i)
        require(p[0] == 1, 'only private LOAD segments permitted')
        _, flags, offset, address, physical, filesz, memsz, alignment = p
        require(physical == address and BASE <= address < address + memsz <= BASE + 0x4000000 and
                filesz <= memsz and offset <= len(blob) and filesz <= len(blob) - offset and
                flags in (5, 6) and alignment == 4096, 'invalid private LOAD')
        loads.append((address, memsz, offset, filesz, flags))
    for left, right in zip(sorted(loads), sorted(loads)[1:]):
        require(left[0] + left[1] <= right[0], 'overlapping private LOADs')
    headers = [unpack('<IIQQQQIIQQ', h[6] + 64 * i) for i in range(h[12])]
    names_header = headers[h[13]]
    require(names_header[4] <= len(blob) and names_header[5] <= len(blob) - names_header[4], 'bad ELF names')
    names = blob[names_header[4]:names_header[4] + names_header[5]]
    sections = {}
    for sh in headers:
        require(sh[0] < len(names), 'invalid section name')
        end = names.find(b'\0', sh[0])
        require(end >= 0, 'unterminated section name')
        name = names[sh[0]:end].decode('ascii')
        require(name not in sections, 'duplicate ELF section')
        if sh[1] == 8:
            data = b''
        else:
            require(sh[4] <= len(blob) and sh[5] <= len(blob) - sh[4], 'invalid section range')
            data = blob[sh[4]:sh[4] + sh[5]]
        require(not (sh[2] & 4 and sh[5] and name not in CODE_SECTIONS), 'unexpected executable section')
        if sh[2] & 2:
            empty_default_text = name == '.text' and sh[1] == 1 and sh[2] == 6 and sh[5] == 0
            require(name in (*CODE_SECTIONS, '.fixturedata', '.source', '.stack') or empty_default_text,
                    'unexpected allocated section')
            require(any(address <= sh[3] and sh[3] + sh[5] <= address + memsz and
                        (sh[1] == 8 or (sh[3] + sh[5] <= address + filesz and
                         sh[4] - offset == sh[3] - address))
                        for address, memsz, offset, filesz, _ in loads), 'section not in private LOAD')
        sections[name] = (sh[3], data)
    fixed = {'.boot': (BASE + 0x80000, None), '.replay': (BASE + 0x90000, 20),
             '.resume': (ENTRY_RETURN, 4), '.fixturedata': (RECORD, None), '.source': (SOURCE_WORD, 8),
             '.stack': (STACK - 0x4000, 0), '.entry': (ENTRY, 20), '.target': (TARGET, 12),
             '.gate': (GATE - 4, 20), '.sink': (BASE + 0x251DD4C, 4)}
    for name, (address, length) in fixed.items():
        require(name in sections and sections[name][0] == address and
                (length is None or len(sections[name][1]) == length), 'section layout differs: ' + name)
    boot = sections['.boot'][1]
    require(len(boot) >= 0x3800, 'private normal-memory tables/vectors missing')
    l1 = struct.unpack_from('<512Q', boot, MMU_L1 - sections['.boot'][0])
    l2 = struct.unpack_from('<512Q', boot, MMU_L2 - sections['.boot'][0])
    require(l1 == (0, MMU_L2 + 3, *([0] * 510)), 'private L1 table differs')
    require(l2 == tuple(BASE + index * 0x200000 + 0x701 for index in range(32)) + (0,) * 480,
            'private 64MiB Normal memory L2 differs')
    vector_targets = []
    for index in range(16):
        address = VECTORS + index * 128
        offset = address - sections['.boot'][0]
        word = struct.unpack_from('<I', boot, offset)[0]
        vector_targets.append(branch_target(word, address, 5))
        require(boot[offset + 4:offset + 128] == bytes(124), 'unexpected vector padding')
    require(len(set(vector_targets)) == 1 and sections['.boot'][0] <= vector_targets[0] < MMU_L1,
            'private exception vectors do not reach owned boot handler')
    entry = sections['.entry'][1]
    if case == 'existing_main_stub_entry':
        require(entry[:8] == STUB8 and int.from_bytes(entry[8:16], 'little') == BASE + 0x90000 and
                entry[16:] == bytes.fromhex('1f2003d5'), 'prebuilt stub/literal differs')
    else:
        require(entry[:16] == ORIGINAL16, 'original16 differs')
        require(branch_target(int.from_bytes(entry[16:], 'little'), ENTRY + 16, 5) == ENTRY_RETURN,
                'owned entry continuation differs')
    replay = sections['.replay'][1]
    require(replay[:16] == ORIGINAL16 and
            branch_target(int.from_bytes(replay[16:], 'little'), BASE + 0x90010, 5) == ENTRY_RETURN,
            'owned replay does not replay original16')
    gate8 = bytearray(GATE8)
    if case == 'one_byte_gate_mutation':
        gate8[4] ^= 1
    require(sections['.gate'][1][:8] == gate8 and sections['.gate'][1][8:16] == FALLTHROUGH8 and
            sections['.target'][1][:8] == TARGET8, 'gate/successor snippets differ')
    require(sections['.source'][1] == bytes(8), 'unexpected source seed')
    for name, offset in (('.resume', 0), ('.target', 8), ('.sink', 0)):
        address, code = sections[name]
        target = branch_target(int.from_bytes(code[offset:offset + 4], 'little'), address + offset, 5)
        require(sections['.boot'][0] <= target < sections['.boot'][0] + len(sections['.boot'][1]),
                'snippet continuation escapes owned boot')
    require(branch_target(int.from_bytes(FALLTHROUGH8[4:], 'little'), FALLTHROUGH + 4, 0x25) ==
            sections['.sink'][0], 'fixed BL does not reach owned sink')
    return sections


def source_value(number):
    return 0x7ABCDEFF00000000 | (1 if number == 0 else W0_INPUTS[(number - 1) % len(W0_INPUTS)])


def taken(number, case):
    return bool(number if case == 'one_byte_gate_mutation' else source_value(number) & 0xFFFFFFFF)


def boundary_words(number, phase, case):
    """Host's independent whole-record model, never a source of trace operands."""
    require(type(number) is int and 0 <= number < ROUNDS and phase in range(4) and case in API_CASES,
            'invalid boundary model arguments')
    values = list(range(31))
    values[0:4] = [seed | number for seed in
                   (0xA0B0C0D0E0F00000, 0x1122334400000000, 0x2233445566770000, 0x3344556677880000)]
    values[16] = RECORD + phase * RECORD_BYTES
    values[19] = 0x191A1B1C1D1E0000 | number
    values[20] = number
    values[21] = 0x2122232425260000 | number
    values[22] = 0x2223242526270000 | number
    values[23] = 0x2324252627280000 | number
    values[24] = 0x2425262728292A2B
    values[27] = STACK
    values[29], values[30] = 0x292A2B2C2D2E2F30, ENTRY_RETURN
    stack = [0x6677889900000000 + i for i in range(14)]
    if phase:
        if number:
            stack[2:4] = values[29:31]
            stack[6:8] = values[21:23]
        values[29], values[22] = STACK - 80, number
    if phase >= 2:
        values[23], values[0] = values[0], SOURCE_WORD
    if phase == 3:
        if taken(number, case):
            values[19] = STACK - 8
        else:
            values[30] = BL_RETURN
        values[0] = values[19]
    flags = NZCV_INPUTS[number % len(NZCV_INPUTS)]
    return (*values, STACK - (80 if phase else 0), flags, flags | 0x3C5, TTBR, TPIDR,
            source_value(number), *stack)


def require_bytes(actual, expected, description):
    if actual != expected:
        offset = next((i for i, pair in enumerate(zip(actual, expected)) if pair[0] != pair[1]),
                      min(len(actual), len(expected)))
        raise FixtureError(f'{description}: byte {offset:#x}, length {len(actual)}/{len(expected)}, '
                           f'actual={actual[offset:offset + 16].hex()} expected={expected[offset:offset + 16].hex()}')


def check_console(console, sections, case):
    """Validate every baseline dump first, then extract full64 operands from it.

    Internal before-instruction values use the pre-LDR dump plus its independently
    dumped source word. Post-snippet dumps check the LDR/CBNZ and both own snippets.
    """
    require(case in API_CASES and console.startswith(HEADER), 'missing self-owned guest header/known case')
    offset = len(HEADER)
    boundaries = []
    for number in range(ROUNDS):
        frame = []
        for phase in range(4):
            raw = console[offset:offset + RECORD_BYTES]
            require(len(raw) == RECORD_BYTES, 'truncated boundary dump')
            require_bytes(raw, struct.pack('<51Q', *boundary_words(number, phase, case)),
                          f'round{number}/phase{phase} independent GPR/SP/CPSR/token/source/stack dump')
            frame.append(struct.unpack('<51Q', raw))
            offset += RECORD_BYTES
        boundaries.append(frame)
    tail = RECORDS_MARKER + b''.join(sections[name][1] for name in CODE_SECTIONS) + TRAILER
    require_bytes(console[offset:], tail, 'whole owned-code windows/readback and guest selfcheck trailer')
    eligible = {site: [] for site in SITES}
    all_events = []
    anchor = 'existing_main_stub8' if case == 'existing_main_stub_entry' else 'original16'
    for number, frame in enumerate(boundaries):
        def row(site, words, event_pc, registers):
            result = {'event_pc': event_pc, 'registers': {name: words[int(name[1:])] for name in registers},
                      'cpsr': words[33], 'sp': words[31], 'ttbr0_el1': words[34], 'tpidr_el0': words[35],
                      'entry_anchor': anchor if site == SITES[0] else 'not_applicable'}
            return result
        if number:
            all_events.append((SITES[0], row(SITES[0], frame[0], ENTRY, ENTRY_REGS)))
        all_events.append((SITES[4], row(SITES[4], frame[2], SOURCE_PC, INTERNAL_REGS)))
        loaded = list(frame[2])
        loaded[0] = frame[2][36] & 0xFFFFFFFF
        all_events.append((SITES[1], row(SITES[1], loaded, GATE, INTERNAL_REGS)))
        site, pc = ((SITES[3], FALLTHROUGH) if frame[3][30] == BL_RETURN else (SITES[2], TARGET))
        all_events.append((site, row(site, loaded, pc, INTERNAL_REGS)))
    positive = case in API_CASES[:2]
    if positive:
        for site, item in all_events:
            eligible[site].append(item)
    expected = {'case': case, 'site_rows': eligible,
                'minimum_suppressed': {site: max(0, len(rows) - QUOTA) for site, rows in eligible.items()},
                'discriminator_expected': positive}
    metadata = {'snapshot_words': 51, 'record_bytes': RECORD_BYTES, 'rounds': ROUNDS,
                'warmup_rounds': [0], 'measured_entry_calls': 40, 'gate_calls': ROUNDS,
                'executed_site_counts': {site: sum(event == site for event, _ in all_events) for site in SITES},
                'baseline_console_sha256': hashlib.sha256(console).hexdigest(),
                'operands_from': 'checked_baseline_console_only',
                'source_x0_basis': 'checked_baseline_gate_before_frame2_full64_X0_SOURCE_WORD',
                'source_event_pc': SOURCE_PC, 'source_pointer_u64': boundaries[0][2][0],
                'source_pointer_high32_actual_coverage': False,
                'branch_x0_basis': 'independent_source64_low32_and_verified_owned_LDR_W0_effect',
                'successor_basis': 'checked_post_snippet_GPR_and_LR_dump_not_trace',
                'context_mode': 'other_aarch64',
                'memory_policy': 'private64MiB_Normal_NC_identity_EL1_v1',
                'TTBR_is_actual_page_table_with_ASID_raw_only': True,
                'boot_control_and_unaligned_probe_selfchecks_completed': True,
                'lr_high32_actual_coverage': False, 'injected_api_fault_actual_coverage': False}
    return expected, metadata


def check_trace_counters(parsed, expected, metadata):
    """Additional actual callback/quota accounting; the peer owns raw parsing."""
    require(type(parsed) is dict and all(key in parsed for key in ('rows', 'raw_ledger', 'begin', 'end')),
            'direct parser must return rows/raw_ledger/begin/end')
    end = parsed['end']
    rows = [row for row in parsed['rows'] if row['kind'] == 'shutter_gate']
    require(not any(row['kind'] == 'fault' for row in parsed['rows']), 'unexpected actual plugin fault')
    require(int(end['candidate_found'], 16) == int(expected['discriminator_expected']), 'wrong discriminator state')
    require(int(end['ambiguous'], 16) == 0 and int(end['faults'], 16) == 0, 'actual run invalidated')
    require(int(end['candidate_base'], 16) == (BASE if expected['discriminator_expected'] else 0), 'wrong base')
    require(int(end['gate_sequence'], 16) == len(rows), 'global success sequence differs')
    result = {}
    for ordinal, site in enumerate(SITES):
        records = sum(row['site'] == site for row in rows)
        require(records == min(QUOTA, len(expected['site_rows'][site])) == int(end[f'site{ordinal}_records'], 16),
                'wrong actual site records: ' + site)
        suppressed = int(end[f'site{ordinal}_suppressed'], 16)
        unbound = int(end[f'site{ordinal}_unbound_callbacks'], 16)
        require(suppressed == expected['minimum_suppressed'][site], 'wrong actual suppressed count: ' + site)
        callbacks = metadata['executed_site_counts'][site]
        if expected['case'] == 'short_tb':
            callbacks = 0
        elif expected['case'] == 'one_byte_gate_mutation' and site in (SITES[1], SITES[4]):
            callbacks = 0
        require(unbound == (0 if expected['discriminator_expected'] else callbacks), 'wrong unbound count: ' + site)
        require(records + suppressed + unbound == callbacks, 'actual callback count differs: ' + site)
        result[site] = {'records': records, 'suppressed': suppressed, 'unbound_callbacks': unbound,
                        'total_callbacks': callbacks}
    return result


def validate_startup_rejection(output, relative, result, sentinel=None):
    rc = result['returncode']
    require(type(rc) is int and 1 <= rc < 124 and not result['outer_timeout'] and
            result['owned_pid_unreaped'] is None, 'startup rejection was abnormal/timeout')
    stderr = read_small(output / relative / 'stderr.bin')
    require(b'scope_observer_host_error' in stderr and b'timeout: sending signal' not in stderr,
            'plugin startup refusal diagnostic missing or timed out')
    console = output / relative / 'console.bin'
    require(not console.exists() or read_small(console) == b'', 'guest started during startup rejection')
    log = output / relative / 'plugin.log'
    if sentinel is None:
        require(not log.exists(), 'missing-log startup unexpectedly created a log')
    else:
        require_bytes(read_small(log), sentinel, 'exclusive log sentinel changed')
    return {'returncode': rc, 'guest_started': False, 'normal_non_timeout_rejection': True,
            'sentinel_unchanged': sentinel is not None}


def write_json(path, value):
    with path.open('x', encoding='utf-8') as stream:
        json.dump(value, stream, indent=2, sort_keys=True)
        stream.write('\n')


def run_fixture(qemu, plugin, output, *, schema, receipt, fixture_source_sha256, fixture_sources_file):
    """Future explicit parent batch. Any command failure preserves its original bytes."""
    qemu, plugin, output = validate_paths(qemu, plugin, output)
    output.mkdir(parents=True, exist_ok=False, mode=0o700)
    manifest = {'status': 'EXECUTING', 'profile': PROFILE, 'trace_schema': SCHEMA,
                'fixture_source_sha256': fixture_source_sha256, 'fixture_source_snapshots': {},
                'commands': [], 'driver_process_argv': list(sys.argv),
                'requested_paths': {'qemu': str(qemu), 'plugin': str(plugin), 'output': str(output),
                                    'schema': str(schema), 'receipt': str(receipt),
                                    'fixture_sources_file': str(fixture_sources_file)},
                'variants': {}, 'startup_negatives': {}, 'inputs': {}, 'failure': None,
                'shutter_gate_observer_verified': False, 'capture_verified': False, 'capture': False,
                'physical': False, 'physical_asic_compatibility_verified': False,
                'instruction_retirement_verified': False, 'retirement': False, 'branchretirement': False,
                'Main_identity_verified': False, 'AP_identity_verified': False,
                'invocation_pairing_verified': False, 'branch_edge_verified': False,
                'api_fault_injection_verified': False, 'lr_high32_actual_coverage': False,
                'source_pointer_high32_actual_coverage': False}
    try:
        copies = output / 'inputs'
        copies.mkdir(mode=0o700)
        # Preserve explicit JSON bytes before interpreting them, also on refusal.
        for name, path in (('explicit-schema.json', schema), ('explicit-receipt.json', receipt),
                           ('explicit-fixture-sources.json', fixture_sources_file)):
            with (copies / name).open('xb') as stream:
                stream.write(read_small(path))
        frozen = object_json(read_small(fixture_sources_file))
        require(frozen == fixture_source_sha256, 'fixture pinfile differs from the explicit map')
        fixture_source_sha256 = dict(frozen)
        inputs, declaration = validate_assets(qemu, plugin, schema, receipt, fixture_source_sha256)
        inputs['fixture_sources_file'] = {'path': str(ordinary_file(fixture_sources_file)),
                                          'sha256': sha256(fixture_sources_file)}
        manifest['inputs'] = inputs
        manifest['trace_schema_sha256'] = inputs['schema']['sha256']
        checks = load_checks()
        clang = tool('clang')
        tool('bwrap')
        tool('timeout')
        for name in FIXTURE_SOURCES:
            raw = read_small(SOURCE / name)
            require(hashlib.sha256(raw).hexdigest() == frozen['integration/' + name], 'source changed before staging')
            with (copies / name).open('xb') as stream:
                stream.write(raw)
            (copies / name).chmod(0o400)
        manifest['fixture_source_snapshots'] = verify_fixture_snapshots(output, frozen)
        for name in ('readonly_import_audit',):
            with (copies / (name + '.json')).open('xb') as stream:
                stream.write(read_small(inputs[name]['path']))
        for case in API_CASES:
            short_tb = case == 'short_tb'
            build_relative = 'build/original_entry' if short_tb else 'build/' + case
            elf = output / build_relative / 'fixture.elf'
            verify_fixture_snapshots(output, frozen)
            if not short_tb:
                payload = [clang, '--target=aarch64-linux-gnu', '-march=armv8-a', '-fuse-ld=lld', '-nostdlib',
                           '-static', '-no-pie', '-x', 'assembler-with-cpp',
                           f'-DFIXTURE_STUB={int(case == "existing_main_stub_entry")}',
                           f'-DFIXTURE_MUTATED={int(case == "one_byte_gate_mutation")}', '/src/fixture.S',
                           '-Wl,-T,/src/link.ld,-z,max-page-size=4096,--build-id=none',
                           '-Wl,-Map,/out/fixture.map', '-o', '/out/fixture.elf']
                build = launch(output, build_relative, payload, [(copies, '/src')], manifest['commands'], 60)
                require(build['returncode'] == 0 and not build['outer_timeout'], 'fixture compile/link failed: ' + case)
            elf_digest = sha256(elf)
            sections = elf_layout(read_small(elf), case)
            runs, baseline, expected, metadata = {}, None, None, None
            for mode in ('baseline', 'plugin'):
                relative = f'cases/{case}-{mode}'
                payload = vm_command(['log=/out/plugin.log'] if mode == 'plugin' else None, short_tb)
                result = launch(output, relative, payload,
                    [(qemu, '/qemu'), (plugin, '/observer.so'), (elf, '/in/fixture.elf')], manifest['commands'], 30)
                require(result['returncode'] == 0 and not result['outer_timeout'], f'QEMU {case}/{mode} failed')
                console = read_small(output / relative / 'console.bin')
                checked, checked_metadata = check_console(console, sections, case)
                if mode == 'baseline':
                    baseline, expected, metadata = console, checked, checked_metadata
                    # Full row lists include the warmup and callbacks suppressed after quota16.
                    write_json(output / relative / 'independent-operands.json', expected)
                    write_json(output / relative / 'boundary-metadata.json', metadata)
                else:
                    require_bytes(console, baseline, case + ' plugin/baseline whole dump equality')
                    raw_log = read_small(output / relative / 'plugin.log')
                    require(b'scope_observer_host_error' not in read_small(output / relative / 'stderr.bin'),
                            'plugin host I/O/install error')
                    checks.assert_shutter_gate_trace_v2(raw_log, declaration, expected)
                    parsed = checks.parse_trace(raw_log, declaration)
                    counters = check_trace_counters(parsed, expected, metadata)
                runs[mode] = {'console': relative + '/console.bin', 'returncode': result['returncode'],
                              'console_sha256': hashlib.sha256(console).hexdigest(),
                              'plugin_log': relative + '/plugin.log' if mode == 'plugin' else None}
            require(sha256(elf) == elf_digest, 'self-owned ELF changed during run')
            manifest['variants'][case] = {'runs': runs, 'elf': build_relative + '/fixture.elf',
                'elf_sha256': elf_digest, 'program_baseline_equal': True,
                'guest_selfcheck_and_code_readback_exact': True, 'expected_operands':
                f'cases/{case}-baseline/independent-operands.json',
                'expected_operands_sha256': sha256(output / f'cases/{case}-baseline/independent-operands.json'),
                'boundary_metadata': metadata,
                'actual_callback_counts': counters, 'trace_sha256': hashlib.sha256(raw_log).hexdigest(),
                'trace_schema_sha256': inputs['schema']['sha256'], 'short_tb': short_tb,
                'trace_adapter': 'shutter_gate_trace_checks_v2.assert_shutter_gate_trace_v2'}
        elf = output / 'build/original_entry/fixture.elf'
        for name in ('missing_log_argument', 'existing_log'):
            relative = 'cases/' + name
            sentinel = b'exclusive-shutter-gate-log-sentinel\n' if name == 'existing_log' else None
            arguments = ['log=/out/plugin.log'] if sentinel is not None else []
            result = launch(output, relative, vm_command(arguments),
                [(qemu, '/qemu'), (plugin, '/observer.so'), (elf, '/in/fixture.elf')],
                manifest['commands'], 30, existing_log=sentinel)
            manifest['startup_negatives'][name] = validate_startup_rejection(output, relative, result, sentinel)
        manifest['fixture_source_snapshots'] = verify_fixture_snapshots(output, frozen)
        for item in inputs.values():
            require(sha256(item['path']) == item['sha256'], 'input changed during run: ' + item['path'])
        for name, source in (('explicit-schema.json', 'schema'), ('explicit-receipt.json', 'receipt'),
                             ('explicit-fixture-sources.json', 'fixture_sources_file'),
                             ('readonly_import_audit.json', 'readonly_import_audit')):
            require(sha256(copies / name) == inputs[source]['sha256'], 'staged asset changed: ' + name)
        for case, item in manifest['variants'].items():
            require(sha256(output / item['elf']) == item['elf_sha256'], 'fixture ELF changed after case: ' + case)
            for run in item['runs'].values():
                require(sha256(output / run['console']) == run['console_sha256'], 'console changed after case: ' + case)
            require(sha256(output / item['runs']['plugin']['plugin_log']) == item['trace_sha256'],
                    'raw trace changed after case: ' + case)
            require(sha256(output / item['expected_operands']) == item['expected_operands_sha256'],
                    'baseline operands changed after case: ' + case)
        require_bytes(read_small(output / 'cases/existing_log/plugin.log'),
                      b'exclusive-shutter-gate-log-sentinel\n', 'startup sentinel changed after refusal')
        require(not (output / 'cases/missing_log_argument/plugin.log').exists(), 'refused startup gained a log')
        manifest['shutter_gate_observer_verified'] = True
        manifest['status'] = 'PASS_SELF_OWNED_QEMU_SHUTTER_GATE_V2_FIXTURE'
    except BaseException as error:
        manifest['status'] = 'FAILED'
        manifest['failure'] = {'type': type(error).__name__, 'message': str(error)}
        raise
    finally:
        # Hash only owned artifacts; never delete/repair raw bytes after a failure.
        manifest['artifacts'] = {}
        for path in sorted(output.rglob('*')):
            if path.is_file() and not path.is_symlink():
                manifest['artifacts'][str(path.relative_to(output))] = {
                    'sha256': sha256(path), 'bytes': path.stat().st_size}
        write_json(output / 'manifest.json', manifest)
    return manifest


def environment_paths():
    require({key for key in os.environ if key.startswith('A7C2_SHUTTER_GATE_V2_TEST_')} == set(API_ENV),
            'exact six explicit shutter-gate environments required; no fallback/skip')
    require(all(os.environ[key] for key in API_ENV), 'empty explicit shutter-gate input')
    return {name: Path(os.environ[name]) for name in API_ENV}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('qemu', 'plugin', 'output', 'schema', 'receipt', 'fixture-sources'):
        parser.add_argument('--' + name, required=True, type=Path)
    args = parser.parse_args()
    try:
        frozen = object_json(read_small(args.fixture_sources))
        result = run_fixture(args.qemu, args.plugin, args.output, schema=args.schema, receipt=args.receipt,
                             fixture_source_sha256=frozen, fixture_sources_file=args.fixture_sources)
    except (FixtureError, OSError, ValueError, subprocess.TimeoutExpired) as error:
        print('fixture failed: ' + str(error), file=sys.stderr)
        return 1
    print(json.dumps({'status': result['status'], 'capture_verified': False, 'physical': False,
                      'manifest': str(args.output / 'manifest.json')}, sort_keys=True))
    return 0


if __name__ == '__main__':
    sys.exit(main())
