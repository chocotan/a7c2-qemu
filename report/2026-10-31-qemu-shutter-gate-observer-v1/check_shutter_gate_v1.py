# SPDX-License-Identifier: MIT
"""Bind same-run shutter raw candidates to frozen source7 and a normal owned exit.

No original appFw ELF is opened. Numerical Main/FLOW/frame matches never identify
an AP invocation, an observed predecessor edge, retirement, or captured media.
"""
from pathlib import Path
import importlib.util
import io
import os
import re
import stat

HERE = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location(
    'shutter_gate_trace_checks_v1', HERE / 'integration/shutter_gate_trace_checks_v1.py')
FORMAT = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(FORMAT)
require, sha, number = FORMAT.require, FORMAT.sha, FORMAT.number
object_json = FORMAT.object_json
PROFILE, SCHEMA = FORMAT.PROFILE, FORMAT.SCHEMA
RejectedTrace = FORMAT.RejectedTrace
COMPONENT = '2026-10-31-qemu-shutter-gate-observer-v1'
SOURCE_SUFFIX = ('final', 'a7c2-re', 'report', '2026-10-17-qemu-native-camera', 'report', COMPONENT)
BUILD_SOURCES = ('scope-observer.c', 'build-plugin.sh', 'build-runtime.py',
                 'log-schema-shutter-gate-v1.json', 'source-contract-shutter-gate-v1.json',
                 'check_shutter_gate_v1.py', 'integration/shutter_gate_trace_checks_v1.py')
FIXTURE_SOURCES = ('integration/fixture.S', 'integration/link.ld', 'integration/run_fixture.py',
                   'integration/test_fixture_driver.py', 'integration/test_actual_scope_plugin.py',
                   'integration/test_shutter_gate_trace_checks_v1.py',
                   'integration/shutter_gate_trace_checks_v1.py')
API_ENV = tuple('A7C2_SHUTTER_GATE_V1_TEST_' + name for name in
                ('QEMU', 'PLUGIN', 'OUTPUT', 'SCHEMA', 'RECEIPT', 'FIXTURE_SOURCES'))
QEMU_SHA256 = '4e85c70ba38774e9439562a7178a65bdbe6b660fdf8dd6bd4ece686fb707a4d4'
HEADER_SHA256 = '335d4e472067e914add598b60d1f7cf0dc029cd48f62f66656d6a88c54d8d9f9'
QEMU_IMPORTS = frozenset('qemu_plugin_' + name for name in (
    'get_registers', 'read_register', 'register_vcpu_init_cb', 'register_vcpu_tb_trans_cb',
    'register_vcpu_insn_exec_cb', 'register_atexit_cb', 'tb_n_insns', 'tb_get_insn',
    'insn_vaddr', 'insn_size', 'insn_data'))
ALIASES = {'source_root', 'Source_root', 'sourceDependencyFrozen', 'schema_sha256',
           'log_schema_sha256', 'v3_schema_sha256'}
MAIN_KEYS = ('site n pid tid base controller caller_raw caller_app raw_u32 raw_known numeric_route_match '
             'vptr field300 field302 field303 current17c model_m model_k open_rc open_errno reads read_errno '
             'close_rc close_errno quota observation_only atomic_snapshot phase original_branch_observed '
             'original_store_observed original_return_observed event_id_unverified producer_unknown capture_verified').split()
FLOW_KEYS = ('site n tid a0 a1 a2 a3 code id state_d428 state_d498 state_c408 reads press_local '
             'transition_67fc8 inhibit_83337e3 duplicate_d570 gate_reads observation_only atomic_snapshot '
             'original_branch_observed').split()


def digest(value):
    require(type(value) is str and re.fullmatch(r'[0-9a-f]{64}', value) is not None,
            'missing real SHA256 pin')
    return value


def owned(path, directory=False):
    path = Path(path)
    require(path.is_absolute() and path.resolve() == path, 'noncanonical absolute artifact ' + str(path))
    info = path.lstat()
    require((stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode) and info.st_nlink == 1) and
            info.st_uid == os.getuid() and not info.st_mode & 0o022,
            'artifact is not an owned ordinary file/directory ' + str(path))
    return path


def snapshot(paths):
    signatures, contents = {}, {}
    for name, value in paths.items():
        path = owned(value)
        flags = os.O_RDONLY | os.O_NOFOLLOW
        with os.fdopen(os.open(path, flags), 'rb') as stream:
            before = os.fstat(stream.fileno())
            raw = stream.read()
            after = os.fstat(stream.fileno())
        final = path.lstat()
        signature = lambda s: (s.st_dev, s.st_ino, s.st_mode, s.st_uid, s.st_size,
                               s.st_mtime_ns, s.st_ctime_ns)
        require(signature(before) == signature(after) == signature(final) and len(raw) == before.st_size,
                'artifact changed while reading ' + name)
        signatures[name] = (*signature(before), sha(raw))
        contents[name] = raw
    return signatures, contents


def console_fields(raw, prefix, keys):
    text = raw[len(prefix):].decode('ascii')
    row = {}
    for token in text.split(' '):
        require(token.count('=') == 1, 'malformed original console record')
        key, value = token.split('=')
        require(key not in row and value and re.fullmatch(r'[A-Za-z0-9_+/#.=-]+', value),
                'duplicate/invalid original console field')
        row[key] = value
    require(list(row) == keys, 'original console formatter fields/order differ')
    return row


def console_hex(row, name, bits=64):
    value = row[name]
    require(re.fullmatch(r'(?:0|0x[1-9a-f][0-9a-f]*)', value) is not None,
            'noncanonical original hex ' + name)
    result = int(value, 16)
    require(result < 1 << bits, 'original hex overflow ' + name)
    return result


def console_decimal(row, name, positive=False):
    require(re.fullmatch(r'0|[1-9][0-9]*', row[name]) is not None, 'invalid console integer ' + name)
    value = int(row[name])
    require(not positive or value > 0, 'nonpositive console owner/counter')
    return value


def console_records(console):
    mains, flows, offset = [], [], 0
    for line_number, line in enumerate(io.BytesIO(console).readlines(), 1):
        body = line.removesuffix(b'\n').removesuffix(b'\r')
        main_prefix, flow_prefix = b'OBS SHUTTER_DETAIL_POWERON ', b'OBS SHUTTER_FLOW '
        if body.startswith(main_prefix):
            require(line.endswith(b'\n'), 'truncated original Main line')
            row = console_fields(body, main_prefix, MAIN_KEYS)
            if row['site'] != 'dispatch':
                require(row['site'] == 'callback', 'unexpected original Main site')
                offset += len(line)
                continue
            fixed = {'raw_known': '1', 'numeric_route_match': '1', 'observation_only': '1',
                     'atomic_snapshot': '0', 'phase': 'entry', 'original_branch_observed': '0',
                     'original_store_observed': '0', 'original_return_observed': '0', 'event_id_unverified': '1',
                     'producer_unknown': '1', 'capture_verified': '0', 'quota': 'poweron_entry16',
                     'open_errno': '0', 'close_rc': '0', 'close_errno': '0', 'reads': '8/2/1/1/4/4/4',
                     'read_errno': '0/0/0/0/0/0/0'}
            require(all(row[k] == v for k, v in fixed.items()), 'original Main incomplete/error flags')
            require(1 <= console_decimal(row, 'n', True) <= 16, 'Main quota differs')
            for name in ('pid', 'tid'):
                console_decimal(row, name, True)
            console_decimal(row, 'open_rc')
            for name in ('base', 'controller', 'caller_raw', 'caller_app', 'vptr'):
                console_hex(row, name)
            for name, bits in (('raw_u32', 32), ('field300', 16), ('field302', 8), ('field303', 8),
                               ('current17c', 32), ('model_m', 32), ('model_k', 32)):
                console_hex(row, name, bits)
            require(console_hex(row, 'base') > 0 and console_hex(row, 'base') & 0xfff == 0 and
                    console_hex(row, 'caller_raw') - console_hex(row, 'base') == console_hex(row, 'caller_app') and
                    console_hex(row, 'raw_u32', 32) & 0xff000fff == 0x01000090,
                    'Main raw route/base/caller differs')
            mains.append(dict(row, raw_LF_line=line_number, byte_offset=offset,
                              raw_hex=line.hex(), sha256=sha(line), byte_length=len(line)))
        elif body.startswith(flow_prefix):
            require(line.endswith(b'\n'), 'truncated original FLOW line')
            row = console_fields(body, flow_prefix, FLOW_KEYS)
            if row['site'] == 'final':
                require(1 <= console_decimal(row, 'n', True) <= 32, 'FLOW quota differs')
                console_decimal(row, 'tid', True)
                for name in ('a0', 'a1', 'a2', 'a3'):
                    console_hex(row, name)
                for name in ('code', 'id', 'state_d428', 'state_d498', 'state_c408', 'press_local',
                             'transition_67fc8', 'inhibit_83337e3', 'duplicate_d570'):
                    console_hex(row, name, 8 if name == 'inhibit_83337e3' else 32)
                require(row['reads'] == '4/-1/4/4/4' and
                        row['observation_only'] == '1' and row['atomic_snapshot'] == '0' and
                        row['original_branch_observed'] == '0', 'FLOW read/observation fields differ')
                if console_hex(row, 'code', 32) == 0x02070000:
                    require(row['gate_reads'] == '4/4/1/4', 'FLOW fullpress snapshot incomplete')
                    flows.append(dict(row, raw_LF_line=line_number, byte_offset=offset,
                                      raw_hex=line.hex(), sha256=sha(line), byte_length=len(line)))
        offset += len(line)
    return mains, flows


def context_key(row):
    tokens = [FORMAT.optional(row, name) for name in ('ttbr0_el1', 'tpidr_el0')]
    if FORMAT.mode_fields(row) != 0 or any(token is None for token in tokens):
        return None
    return (number(row, 'candidate_base'), number(row, 'vcpu'), *tokens)


def correlate(console, trace, declaration):
    try:
        require(b'scope_observer_host_error' not in console, 'observer reported host write/flush/close failure')
        parsed = FORMAT.parse_trace(trace, declaration)
        mains, flows = console_records(console)
        indexed = [(i, row) for i, row in enumerate(parsed['rows']) if row['kind'] == 'shutter_gate']
        entries = [(i, row) for i, row in indexed if row['site'] == 'final_entry']
        base = number(parsed['end'], 'candidate_base') if number(parsed['end'], 'candidate_found') else None
        matching_mains = [row for row in mains if console_hex(row, 'base') == base]
        flow_candidates = []
        if matching_mains:
            for index, row in entries:
                matching = [flow for flow in flows if all(number(row, 'x%d_raw' % r) ==
                            console_hex(flow, 'a%d' % r) for r in range(4))]
                flow_candidates.append({'entry_trace_index': index, 'matching_FLOW_records': matching,
                                        'correlation': 'FLOW_entry_raw_candidate_match' if len(matching) == 1
                                                       else 'raw_uncorrelated',
                                        'matching_Main_records': matching_mains})
        candidates = []
        for entry_index, entry in entries:
            entry_key = context_key(entry)
            if entry_key is None:
                continue
            for internal_index, internal in indexed:
                if internal['site'] == 'final_entry' or context_key(internal) != entry_key:
                    continue
                frame = number(internal, 'x29_raw')
                if (number(internal, 'x23_raw') != number(entry, 'x0_raw') or
                        number(internal, 'x22_raw') & 0xffffffff != number(entry, 'x1_raw') & 0xffffffff or
                        frame > FORMAT.U64_MAX - 0x48 or number(internal, 'x19_raw') != frame + 0x48):
                    continue
                entry_sp, internal_sp = FORMAT.optional(entry, 'sp'), FORMAT.optional(internal, 'sp')
                frame_checked = entry_sp is not None or internal_sp is not None
                if frame_checked and (entry_sp is None or internal_sp is None or entry_sp < 0x50 or
                                      entry_sp - 0x50 != internal_sp or internal_sp != frame):
                    continue
                candidates.append({'entry_trace_index': entry_index, 'internal_trace_index': internal_index,
                                   'correlation': 'raw_context_candidate_match', 'SP_frame_checked': frame_checked,
                                   'LR_source_path_numeric_match_only': number(internal, 'x30_raw') == base + 0x1af1830,
                                   'invocation_pairing': 'unknown'})
        participating = {item[key] for item in candidates for key in ('entry_trace_index', 'internal_trace_index')}
        return {'profile': PROFILE, 'trace_schema': SCHEMA, 'begin': parsed['begin'], 'end': parsed['end'],
                'rows': parsed['rows'], 'raw_ledger': parsed['raw_ledger'], 'trace_sha256': parsed['trace_sha256'],
                'Main_records': mains, 'Main_base_numeric_matches_only': matching_mains,
                'FLOW_entry_candidates': flow_candidates, 'raw_context_candidates': candidates,
                'uncorrelated_trace_indices': [i for i, _ in indexed if i not in participating],
                'raw_context_candidate_status': 'raw_context_candidate_match' if len(candidates) == 1
                                                 else 'raw_uncorrelated',
                'invocation_pairing': 'unknown', 'raw_identity': 'unknown', 'raw_binding': 'unbound',
                'runtime_receipt_bound': False, 'observation_status': 'observed_raw' if indexed else 'unknown',
                **FORMAT.FALSE_FLAGS}
    except RejectedTrace:
        raise
    except (ValueError, KeyError, TypeError, UnicodeError, OverflowError) as error:
        raise RejectedTrace(str(error), trace) from error


def check_contract(contract, schema_sha256):
    FORMAT.validate_json_value(contract)
    digest(schema_sha256)
    require(type(contract) is dict and
            contract.get('schema') == FORMAT.CONTRACT_SCHEMA and contract.get('profile') == PROFILE and
            contract.get('trace_schema') == SCHEMA and contract.get('component') == COMPONENT and
            contract.get('actual_build_source_names_required') == list(BUILD_SOURCES) and
            contract.get('actual_fixture_source_names_required') == list(FIXTURE_SOURCES) and
            contract.get('actualAPI_cases') == list(FORMAT.CASES) and
            contract.get('actualAPI_environment_names') == list(API_ENV) and
            contract.get('exact_qemu_imports') is not None and
            set(contract['exact_qemu_imports']) == QEMU_IMPORTS and len(contract['exact_qemu_imports']) == 11 and
            contract.get('qemu_plugin_api') == 7 and
            contract.get('qemu_sha256_inherited_only') == QEMU_SHA256 and
            contract.get('qemu_header_sha256') == HEADER_SHA256 and
            contract.get('trace_schema_sha256') == schema_sha256 and
            not ALIASES.intersection(contract) and 'source_contract_sha256' not in contract,
            'semantic source7/fixture7/4case/6env/11API contract differs')


def audit_imports(audit, library, qemu):
    expected_commands = {'imports': ['nm', '-D', '--undefined-only', str(library)],
                         'exports': ['nm', '-D', '--defined-only', str(qemu)],
                         'needed': ['readelf', '-d', str(library)]}
    def symbols(role):
        record = audit[role]
        require(type(record) is dict and record.get('command') == expected_commands[role] and
                type(record.get('returncode')) is int and record['returncode'] == 0 and
                type(record.get('stdout')) is str and type(record.get('stderr')) is str,
                'failed/missing import audit command')
        return {line.split()[-1].split('@')[0] for line in record['stdout'].splitlines() if line.split()}
    require(set(audit) == {'imports', 'exports', 'needed', 'qemu_plugin_imports',
                           'ordinary_imports', 'dt_needed'}, 'import audit record roles differ')
    imports, exports = symbols('imports'), symbols('exports')
    symbols('needed')
    required = {name for name in imports if name.startswith('qemu_plugin_')}
    ordinary = sorted(imports - required)
    needed = re.findall(r'\(NEEDED\).*\[([^\]]+)\]', audit['needed']['stdout'])
    require(required == QEMU_IMPORTS and QEMU_IMPORTS <= exports and
            audit['qemu_plugin_imports'] == sorted(required) and
            audit['ordinary_imports'] == ordinary and audit['dt_needed'] == needed,
            'QEMU API import/export or ordinary dependency audit differs from exact11')
    return {'qemu_imports': sorted(QEMU_IMPORTS), 'ordinary_libc_glib_imports': ordinary,
            'DT_NEEDED_raw': audit['needed']['stdout']}


def check_run(run, expected):
    """expected contains newly frozen source/fixture/build/Main pins, never discovered pins.

    schema digest uses trace_schema_sha256. No source-root argument, legacy loader,
    original ELF read, process signalling, or execution is used by this checker.
    """
    trace = b''
    try:
        require(HERE.parts[-6:] == SOURCE_SUFFIX, 'reader requires the fixed shutter component source root')
        run = owned(Path(run), directory=True)
        require(type(expected) is dict and not ALIASES.intersection(expected), 'legacy pin alias or root override')
        FORMAT.validate_json_value(expected)
        closure = expected['source_sha256']
        fixtures = expected['fixture_source_sha256']
        require(type(closure) is dict and set(closure) == set(BUILD_SOURCES) and
                type(fixtures) is dict and set(fixtures) == set(FIXTURE_SOURCES), 'source7/fixture7 pin roles differ')
        for value in (*closure.values(), *fixtures.values()):
            digest(value)
        for key in ('trace_schema_sha256', 'library_sha256', 'build_receipt_sha256',
                    'readonly_import_audit_sha256', 'observer_sha256', 'Main_source_sha256', 'original_appfw_sha256'):
            digest(expected[key])
        require(expected['qemu_sha256'] == QEMU_SHA256 and expected['qemu_header_sha256'] == HEADER_SHA256,
                'unreviewed QEMU/header pins')
        paths = {name: run / name for name in ('console.log', 'runtime-manifest.json',
                 'readonly-scope-trace.log', 'readonly-scope-observer.so', 'readonly-scope-exit.json')}
        before, contents = snapshot({'readonly-scope-trace.log': paths['readonly-scope-trace.log']})
        trace = contents['readonly-scope-trace.log']
        sigs, other = snapshot({name: path for name, path in paths.items() if name not in contents})
        before.update(sigs)
        contents.update(other)
        source_paths = {'source:' + name: HERE / name for name in BUILD_SOURCES}
        fixture_paths = {'fixture:' + name: HERE / name for name in FIXTURE_SOURCES}
        source_sigs, source_data = snapshot(source_paths | fixture_paths)
        require(all(sha(source_data['source:' + name]) == value for name, value in closure.items()) and
                all(sha(source_data['fixture:' + name]) == value for name, value in fixtures.items()),
                'actual integrated sources changed after freeze')
        schema_raw = source_data['source:log-schema-shutter-gate-v1.json']
        require(sha(schema_raw) == expected['trace_schema_sha256'], 'actual trace schema pin differs')
        declaration = object_json(schema_raw)
        FORMAT.validate_declaration(declaration)
        check_contract(object_json(source_data['source:source-contract-shutter-gate-v1.json']), sha(schema_raw))
        manifest = object_json(contents['runtime-manifest.json'])
        profile = manifest['readonly_scope_observer']
        require(type(profile) is dict and not ALIASES.intersection(profile) and
                profile['profile'] == PROFILE and profile['trace_schema'] == SCHEMA and
                profile['trace_schema_sha256'] == expected['trace_schema_sha256'] and
                profile['source_contract_sha256'] == closure['source-contract-shutter-gate-v1.json'] and
                profile['identity_binding'] == 'unverified' and
                all(profile[key] is False for key in ('capture_verified', 'physical_asic_compatibility_verified')),
                'manifest profile/schema/claims differ')
        for key in ('qemu_sha256', 'qemu_header_sha256', 'library_sha256', 'source_sha256'):
            require(profile[key] == expected[key], 'manifest asset differs ' + key)
        require(Path(profile['library']) == paths['readonly-scope-observer.so'] and
                Path(profile['log']) == paths['readonly-scope-trace.log'] and
                before['readonly-scope-observer.so'][-1] == expected['library_sha256'], 'staged paths/hash differ')
        files = manifest['files']
        require(type(files) is dict, 'manifest files map missing')
        for key in ('readonly-scope-observer.so',):
            require(files.get(str(paths[key])) == sha(contents[key]), 'staged plugin absent from manifest files')
        receipt_path = owned(profile['build_receipt'])
        receipt_sigs, receipt_data = snapshot({'build_receipt': receipt_path})
        receipt_raw = receipt_data['build_receipt']
        require(sha(receipt_raw) == profile['build_receipt_sha256'] == expected['build_receipt_sha256'],
                'build receipt changed or belongs to a different run')
        require(files.get(str(receipt_path)) == sha(receipt_raw) and
                all(files.get(str(HERE / name)) == value for name, value in closure.items()),
                'manifest build receipt/source7 staged binding differs')
        receipt = object_json(receipt_raw)
        require(not ALIASES.intersection(receipt) and receipt['schema'] == PROFILE and
                receipt['trace_schema'] == SCHEMA and receipt['trace_schema_sha256'] == expected['trace_schema_sha256'] and
                receipt['source_contract_sha256'] == closure['source-contract-shutter-gate-v1.json'] and
                type(receipt['plugin_api']) is int and receipt['plugin_api'] == 7 and
                receipt['readonly_imports_verified'] is True and
                all(receipt[key] is False for key in ('runtime_verified', 'capture_verified',
                                                     'physical_asic_compatibility_verified')),
                'receipt API/schema/source/claim mismatch')
        for key in ('qemu_sha256', 'qemu_header_sha256', 'library_sha256', 'source_sha256', 'fixture_source_sha256'):
            require(receipt[key] == expected[key], 'build receipt asset differs ' + key)
        import_path = owned(receipt_path.parent / 'readonly-import-audit.json')
        import_sigs, import_data = snapshot({'readonly_import_audit': import_path})
        audit_raw = import_data['readonly_import_audit']
        require(sha(audit_raw) == receipt['readonly_import_audit_sha256'] == expected['readonly_import_audit_sha256'],
                'actual import audit differs')
        import_summary = audit_imports(object_json(audit_raw), receipt['library'], receipt['qemu'])
        compiled = manifest['compiled_observer']
        require(type(compiled) is dict and type(compiled.get('sources')) is dict and
                compiled.get('observer_sha256') == expected['observer_sha256'],
                'Main observer library/source manifest differs')
        mains = [item.get('sha256') if type(item) is dict else None
                 for name, item in compiled['sources'].items() if Path(name).name == 'menu-observe.c']
        require(mains == [expected['Main_source_sha256']], 'frozen Main source manifest differs')
        appfw = [value for name, value in files.items() if Path(name).name == 'appFw.so']
        require(appfw == [expected['original_appfw_sha256']], 'original appFw manifest pin differs')
        exit_record = object_json(contents['readonly-scope-exit.json'])
        require(exit_record['profile'] == PROFILE and exit_record['run'] == str(run) and
                type(exit_record['owned_wrapper_pid']) is int and exit_record['owned_wrapper_pid'] > 0 and
                type(exit_record['returncode']) is int and exit_record['returncode'] == 0 and
                exit_record['log_available'] is True and exit_record['log_sha256'] == sha(trace) and
                exit_record['library_sha256'] == expected['library_sha256'] and
                all(exit_record[key] is False for key in ('capture_verified', 'physical_asic_compatibility_verified')),
                'missing actual normal owned wrapper exit/readback')
        result = correlate(contents['console.log'], trace, declaration)
        all_paths = paths | source_paths | fixture_paths | {'build_receipt': receipt_path,
                                                          'readonly_import_audit': import_path}
        before.update(source_sigs | receipt_sigs | import_sigs)
        after, _ = snapshot(all_paths)
        require(after == before, 'run/source/receipt/audit changed during read-only check')
        result.update(run=str(run), runtime_receipt_bound=True, original_artifacts_unchanged=True,
                      artifact_signatures=before, build_source_sha256=closure, fixture_source_sha256=fixtures,
                      build_receipt_sha256=sha(receipt_raw), trace_schema_sha256=sha(schema_raw),
                      source_contract_sha256=closure['source-contract-shutter-gate-v1.json'],
                      import_audit=import_summary)
        return result
    except RejectedTrace:
        raise
    except (ValueError, KeyError, TypeError, OSError, UnicodeError, OverflowError, RuntimeError) as error:
        raise RejectedTrace(str(error), trace) from error
