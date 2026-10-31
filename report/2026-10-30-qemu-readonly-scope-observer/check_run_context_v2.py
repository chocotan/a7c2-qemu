"""Bind explicit v2 receipts and unchanged raw context observations from one run.

This checker records context matches, never AP identity, a completed store or return.
"""
from pathlib import Path
import json
import re
import runpy
import stat

HERE = Path(__file__).resolve().parent
FORMAT = runpy.run_path(str(HERE / 'integration/scope_trace_checks_v2.py'))
LEGACY = FORMAT['LEGACY']
require, number, sha = FORMAT['require'], FORMAT['number'], FORMAT['sha']
PROFILE, SCHEMA = FORMAT['PROFILE'], FORMAT['SCHEMA']
RejectedTrace = FORMAT['RejectedTrace']
BUILD_SOURCES = ('scope-observer.c', 'late-sites.inc', 'build-plugin.sh',
                 'log-schema-v2.json', 'source-contract-v2.json', 'check_run_context_v2.py',
                 'check_run_context.py', 'integration/scope_trace_checks_v2.py',
                 'integration/scope_trace_checks.py')
ASSET_FIELDS = ('qemu_sha256', 'library_sha256', 'qemu_header_sha256', 'source_sha256')


def correlate(console, trace, schema):
    """Pure content check. check_run supplies the actual receipt and immutable-run gate."""
    try:
        require(b'scope_observer_host_error' not in console, 'observer reported host I/O or close failure')
        parsed = FORMAT['parse_trace'](trace, schema)
        rows, end = parsed['rows'], parsed['rows'][-1]
        try:
            mains = LEGACY['main_dispatches'](console)
        except ValueError as error:
            if 'TRACE_MISSING original Main dispatch' not in str(error):
                raise
            mains = []
        scope_base = number(end, 'candidate_base') if number(end, 'candidate_found') else None
        contexts, joins = {}, []
        for index, row in enumerate(rows):
            if row['kind'] != 'poweron_context' or number(row, 'candidate_base') != scope_base:
                continue
            matched = [main for main in mains if all(number(main, a) == number(row, b) for a, b in
                       (('base', 'candidate_base'), ('controller', 'controller'),
                        ('caller_raw', 'caller_raw'), ('raw_u32', 'raw_u32')))]
            require(len(matched) <= 1, 'ambiguous original Main correlation')
            context = FORMAT['context_key'](row)
            if not matched or context is None:
                continue
            contexts.setdefault(context, []).append(index)
            joins.append({'poweron_trace_index': index, 'Main_raw_LF_line': matched[0]['raw_LF_line'],
                          'Main_reported_pid': int(matched[0]['pid']), 'Main_reported_tid': int(matched[0]['tid'])})
        observations, uncorrelated = [], []
        producers = {site: [] for site in FORMAT['PRODUCER_SITES']}
        for index, row in enumerate(rows):
            if row['kind'] not in ('entry', 'late', 'M_producer'):
                continue
            context = FORMAT['context_key'](row)
            anchors = contexts.get(context, []) if context is not None else []
            if row['kind'] != 'M_producer':
                if not any(anchor < index for anchor in anchors):
                    uncorrelated.append(index)
                else:
                    observations.append({'trace_index': index, 'kind': row['kind'], 'raw_fields': row.copy(),
                                         'correlation': 'context_match_only'})
                continue
            retrospective = bool(anchors) and (row['scope_anchor_seen'] == '0x0' or
                                               not any(anchor < index for anchor in anchors))
            status = ('retrospective_context_match_only' if retrospective else
                      'context_match_only' if anchors else 'raw_uncorrelated')
            producers[row['site']].append({'trace_index': index, 'raw_fields': row.copy(),
                                          'correlation': status,
                                          'matching_poweron_trace_indices': list(anchors),
                                          'earlier_AP_identity_unknown': True,
                                          'AP_identity_verified': False})
        producer_rows = producers['entry'] + producers['pre_M_store']
        return {'trace_schema': SCHEMA, 'profile': PROFILE,
                'context_correlated': bool(observations) or any(row['correlation'] != 'raw_uncorrelated' for row in producer_rows),
                'poweron_Main_context_bound': bool(joins), 'poweron_Main_joins': joins,
                'observations': observations, 'uncorrelated_observation_indices': uncorrelated,
                'M_producer': producers, 'producer_observation_status': 'observed_raw' if producer_rows else 'unknown',
                'normal_M_producer_call': 'unknown', 'M_business_id': 'unknown', 'M_event_key': 'unknown',
                'entry_pre_store_invocation_pairing': 'unknown',
                'raw_records': parsed['raw_records'], 'trace_sha256': parsed['trace_sha256'],
                'raw_identity': 'unknown', 'raw_binding': 'unbound', 'runtime_receipt_bound': False,
                'cap': False, 'capture': False, 'physical': False,
                'PID_TID_uniqueness_verified': False, 'address_space_uniqueness_verified': False,
                'earlier_AP_identity_verified': False, 'instruction_retirement_verified': False,
                'branchretirement': False, 'storecompletion': False,
                'original_store_or_return_verified': False, 'capture_verified': False,
                'physical_asic_compatibility_verified': False}
    except RejectedTrace:
        raise
    except (ValueError, KeyError, TypeError, UnicodeError) as error:
        raise RejectedTrace(str(error), trace) from error


def ordinary(path):
    path = Path(path)
    require(path.is_absolute() and path.resolve() == path and not path.is_symlink() and
            stat.S_ISREG(path.stat().st_mode), 'missing absolute ordinary artifact ' + str(path))
    return path


def snapshot(paths):
    signatures, contents = {}, {}
    for name, value in paths.items():
        path = ordinary(value)
        before = path.stat()
        raw = path.read_bytes()
        after = path.stat()
        require((before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) ==
                (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns) and len(raw) == before.st_size,
                'artifact changed while reading ' + name)
        signatures[name] = (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, sha(raw))
        contents[name] = raw
    return signatures, contents


def check_run(run, expected):
    """Expected pins must come from this new run's frozen parent ready, never discovery.

    In addition to the legacy business/asset pins, require build_receipt_sha256
    and readonly_import_audit_sha256. source_sha256 is the parent's exact nine-file
    actual build-source map. Receipt and manifest use trace_schema_sha256;
    expected.schema_sha256 remains the parent's ready pin, never a receipt alias.
    """
    trace = b''
    try:
        run = Path(run).absolute()
        require(run.resolve() == run and run.is_dir() and not run.is_symlink(), 'not an ordinary run directory')
        paths = {name: run / name for name in ('console.log', 'runtime-manifest.json', 'readonly-scope-trace.log',
                                              'readonly-scope-observer.so', 'readonly-scope-exit.json')}
        original, contents = snapshot({'readonly-scope-trace.log': paths['readonly-scope-trace.log']})
        trace = contents['readonly-scope-trace.log']
        other_signatures, other_contents = snapshot({name: path for name, path in paths.items()
                                                    if name != 'readonly-scope-trace.log'})
        original.update(other_signatures)
        contents.update(other_contents)
        require(expected['schema_sha256'] != FORMAT['V1_SCHEMA_SHA256'], 'v2 cannot use the v1 schema pin')
        closure = expected['source_sha256']
        require(isinstance(closure, dict) and set(closure) == set(BUILD_SOURCES), 'nine-file build-source closure differs')
        source_paths = {'source:' + name: HERE / name for name in BUILD_SOURCES}
        source_signatures, source_contents = snapshot(source_paths)
        require(all(sha(source_contents['source:' + name]) == closure[name] for name in BUILD_SOURCES),
                'actual build source/schema/reader changed after ready')
        schema_raw = source_contents['source:log-schema-v2.json']
        require(sha(schema_raw) == expected['schema_sha256'], 'unreviewed v2 schema')
        contract = json.loads(source_contents['source:source-contract-v2.json'])
        require(contract['schema'] == 'readonly_scope_source_contract_v2' and contract['profile'] == PROFILE and
                contract['trace_schema'] == SCHEMA and contract['v2_schema_sha256'] == sha(schema_raw),
                'source contract does not bind the actual v2 schema')
        manifest = json.loads(contents['runtime-manifest.json'])
        profile = manifest['readonly_scope_observer']
        require(profile['profile'] == PROFILE and profile['identity_binding'] == 'unverified' and
                profile['trace_schema'] == SCHEMA and profile['trace_schema_sha256'] == expected['schema_sha256'] and
                profile['source_contract_sha256'] == closure['source-contract-v2.json'] and
                not {'schema_sha256', 'log_schema_sha256'} & profile.keys() and
                profile['capture_verified'] is False and profile['physical_asic_compatibility_verified'] is False,
                'explicit v2 profile/schema/source-contract mismatch')
        receipt_path = ordinary(Path(profile['build_receipt']))
        receipt_signatures, receipt_contents = snapshot({'build_receipt': receipt_path})
        receipt_raw = receipt_contents['build_receipt']
        require(sha(receipt_raw) == profile['build_receipt_sha256'] == expected['build_receipt_sha256'],
                'unreviewed actual build receipt')
        receipt = json.loads(receipt_raw)
        require(receipt['schema'] == PROFILE and receipt['trace_schema'] == SCHEMA and
                receipt['trace_schema_sha256'] == expected['schema_sha256'] and
                receipt['source_contract_sha256'] == closure['source-contract-v2.json'] and
                not {'schema_sha256', 'log_schema_sha256'} & receipt.keys() and
                all(receipt[key] is False for key in
                    ('runtime_verified', 'capture_verified', 'physical_asic_compatibility_verified')) and
                type(receipt['plugin_api']) is int and receipt['plugin_api'] == 7 and
                receipt['readonly_imports_verified'] is True and
                receipt['readonly_import_audit_sha256'] == expected['readonly_import_audit_sha256'],
                'receipt does not bind the v2 API/schema/import audit')
        require(isinstance(expected['source_sha256'], dict) and bool(expected['source_sha256']) and
                all(re.fullmatch(r'[0-9a-f]{64}', digest) is not None for digest in expected['source_sha256'].values()),
                'missing real build-source map')
        for field in ASSET_FIELDS:
            require(profile[field] == receipt[field] == expected[field], 'runtime/build asset differs: ' + field)
        require(Path(profile['library']) == paths['readonly-scope-observer.so'] and
                Path(profile['log']) == paths['readonly-scope-trace.log'], 'trace/plugin belongs to another run')
        require(original['readonly-scope-observer.so'][-1] == expected['library_sha256'], 'staged plugin changed')
        compiled = manifest['compiled_observer']
        require(compiled['observer_sha256'] == expected['observer_sha256'], 'Main observer differs')
        main = [row['sha256'] for name, row in compiled['sources'].items() if Path(name).name == 'menu-observe.c']
        require(main == [expected['Main_source_sha256']], 'Main source differs')
        appfw = [digest for name, digest in manifest['files'].items() if Path(name).name == 'appFw.so']
        require(appfw == [expected['original_appfw_sha256']], 'original appFw asset differs')
        exit_record = json.loads(contents['readonly-scope-exit.json'])
        require(exit_record['profile'] == PROFILE and exit_record['run'] == str(run) and
                type(exit_record['owned_wrapper_pid']) is int and exit_record['owned_wrapper_pid'] > 0 and
                type(exit_record['returncode']) is int and exit_record['returncode'] == 0 and
                exit_record['log_available'] is True and exit_record['log_sha256'] == sha(trace) and
                exit_record['library_sha256'] == expected['library_sha256'] and
                exit_record['capture_verified'] is False and exit_record['physical_asic_compatibility_verified'] is False,
                'missing normal owned exit/log readback')
        result = correlate(contents['console.log'], trace, json.loads(schema_raw))
        all_paths = dict(paths, **source_paths, build_receipt=receipt_path)
        before = dict(original, **source_signatures, **receipt_signatures)
        after, _ = snapshot(all_paths)
        require(after == before, 'run/receipt/reader inputs changed during read-only check')
        result.update(run=str(run), artifact_signatures=before, original_artifacts_unchanged=True,
                      runtime_receipt_bound=True, build_source_sha256=receipt['source_sha256'],
                      build_receipt_sha256=sha(receipt_raw), trace_schema_sha256=sha(schema_raw),
                      source_contract_sha256=closure['source-contract-v2.json'])
        return result
    except RejectedTrace:
        raise
    except (ValueError, KeyError, TypeError, OSError, UnicodeError) as error:
        raise RejectedTrace(str(error), trace) from error
