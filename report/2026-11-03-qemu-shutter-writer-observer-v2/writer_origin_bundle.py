"""An independent writer DSO receipt; this does not replace any shutter-gate profile."""
from pathlib import Path
import json

from writer_origin_trace import PROFILE, SCHEMA, digest, need, parse_trace, read_file

QEMU_SHA256 = '4e85c70ba38774e9439562a7178a65bdbe6b660fdf8dd6bd4ece686fb707a4d4'
HEADER_SHA256 = '335d4e472067e914add598b60d1f7cf0dc029cd48f62f66656d6a88c54d8d9f9'
SOURCE_NAMES = ('scope-observer.c', 'writer_origin_trace.py', 'writer_origin_trace_base.py',
                'writer_origin_bundle.py', 'writer_origin_runtime.py', 'writer_origin_contract.py',
                'build_origin_observer.py', 'integration/fixture.S', 'integration/link.ld')
QEMU_IMPORTS = frozenset('qemu_plugin_' + name for name in (
    'get_registers', 'read_register', 'register_vcpu_init_cb', 'register_vcpu_tb_trans_cb',
    'register_atexit_cb', 'tb_n_insns', 'tb_get_insn', 'insn_vaddr', 'insn_size', 'insn_data',
    'register_vcpu_insn_exec_cb'))
FALSE = dict(Sony_runtime_verified=False, profile_attached_to_camera=False, AP_identity_verified=False,
             invocation_pairing_verified=False, store_retirement_verified=False,
             capture_verified=False, physical_asic_compatibility_verified=False)


def object_json(raw):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            need(key not in result, 'duplicate writer JSON field')
            result[key] = value
        return result
    def invalid(value):
        raise ValueError('nonfinite writer JSON value: ' + value)
    value = json.loads(raw, object_pairs_hook=unique, parse_constant=invalid)
    need(type(value) is dict, 'writer JSON object required')
    return value


def source_map(root):
    return {name: digest(read_file(root / name, 1024 * 1024)) for name in SOURCE_NAMES}


def verify_actual_api(path, expected_sha256, library_sha256, fixture_sha256):
    """Consume all three measured results for the identical DSO, including CPU readback."""
    path = Path(path)
    raw = read_file(path, 4 * 1024 * 1024, expected_sha256)
    manifest = object_json(raw)
    need(manifest.get('status') == 'PASS_SELF_OWNED_WRITER_ORIGIN_V2_FOUR_ACTUAL_QEMU_CASES_NOT_SONY_RUNTIME' and
         type(manifest.get('returncode')) is int and manifest['returncode'] == 0 and
         manifest.get('QEMU_actual_API_run') is True and manifest.get('Sony_guest_run') is False and
         all(manifest.get(key) is False for key in ('normal_writer_runtime_observed', 'AP_identity_verified',
             'invocation_pairing_verified', 'store_retirement_verified', 'capture_verified',
             'physical_asic_compatibility_verified')) and manifest.get('library_sha256') == library_sha256,
         'writer-v2 actual fixture scope or outcome differs')
    commands = manifest.get('commands')
    cases = ['original', 'equivalent-setter-mutation', 'origin-mutation', 'short-tb']
    need(type(commands) is list and len(commands) == 4 and [c.get('case') for c in commands] == cases,
         'writer-v2 actual API cases differ')
    evidence, values = {}, [1] * 3 + [0] * 3 + [0xffffffff] * 3
    for command in commands:
        case = command['case']
        need(command.get('qemu_sha256') == QEMU_SHA256 and command.get('plugin_sha256') == library_sha256 and
             command.get('primary_sha256') == 'c8ad5719d5620b65451bfe09a0d0a0f6c59ca527f1876ba525c29f873aa9d2a0' and
             type(command.get('returncode')) is int and command['returncode'] == 0 and
             command.get('timed_out') is False and command.get('CPU_readback_verified') is True and
             all(type(command.get(key)) is int and command[key] == 0 for key in ('signals_sent', 'QMP_calls')),
             'writer-v2 actual API failed or used different assets')
        directory = path.parent / case
        result_raw = read_file(directory / 'content-result.json', 192 * 1024)
        result = object_json(result_raw)
        trace = read_file(directory / 'readonly-shutter-writer.log', expected_sha256=result.get('writer_trace_sha256'))
        primary = read_file(directory / 'readonly-scope-trace.log', expected_sha256=result.get('primary_trace_sha256'))
        console = read_file(directory / 'console.bin', 4096, result.get('console_sha256'))
        elf = read_file(directory / 'fixture.elf', 1024 * 1024, command.get('elf_sha256'))
        need(console == b'ORIGIN_V2_CPU_READBACK_PASS values=1,0,ffffffff flags=0,1,0\n' and
             result.get('CPU_readback_verified') is True and result.get('capture_verified') is False,
             'writer-v2 CPU independent readback differs')
        observed = parse_trace(trace)
        need(json.dumps(observed, sort_keys=True) == json.dumps(result.get('observed'), sort_keys=True),
             'writer-v2 recorded parsed content differs from raw trace')
        expected_writer = 0 if case in ('equivalent-setter-mutation', 'short-tb') else 9
        expected_origins = 0 if case == 'short-tb' else 3 if case == 'origin-mutation' else 6
        for record, field, expected in ((command, 'writer_callbacks', expected_writer),
                (result, 'writer_callbacks', expected_writer), (command, 'origin_callbacks', expected_origins),
                (result, 'origin_callbacks', expected_origins)):
            need(type(record.get(field)) is int and record[field] == expected, 'writer-v2 measured count differs')
        expected_mask = 0 if case == 'short-tb' else 2 if case == 'origin-mutation' else 3
        need(observed['candidate_found'] is bool(expected_writer) and observed['origin_anchor_mask'] == expected_mask,
             'writer-v2 negative fixture was matched or required anchor was absent')
        need(len(observed['events']) == expected_writer and len(observed['origins']) == expected_origins and
             observed['truncated_by_quota'] is False and
             all(value == 0 for value in observed['origin_filtered_counts'].values()),
             'writer-v2 actual callback content incomplete')
        if expected_writer:
            need([e['input_w0'] for e in observed['events']] == values, 'writer-v2 measured setter values differ')
        if case == 'original':
            need(digest(elf) == fixture_sha256, 'writer-v2 original fixture differs')
        if expected_origins:
            table = [e for e in observed['origins'] if e['site'] == 'table_setter_entry']
            dispatch = [e for e in observed['origins'] if e['site'] == 'dispatch_entry']
            need([e['value_u32'] for e in table] == [1, 0, 0xffffffff], 'writer-v2 original table inputs differ')
            if case == 'origin-mutation':
                need(not dispatch, 'writer-v2 changed origin anchor was matched')
            else:
                need([e['value_u32'] for e in dispatch] == [1, 0, 0xffffffff] and
                     [e['registers']['x2'] for e in dispatch] == [0, 1, 0] and
                     [e['registers']['x3'] for e in dispatch] == [3, 4, 5] and
                     [e['registers']['x4'] for e in dispatch] == [10, 11, 12],
                     'writer-v2 actual dispatch registers differ')
        evidence[case] = dict(result_sha256=digest(result_raw), trace_sha256=digest(trace),
            primary_trace_sha256=digest(primary), console_sha256=digest(console), elf_sha256=digest(elf),
            writer_callbacks=expected_writer, origin_callbacks=expected_origins)
    need(read_file(path, 4 * 1024 * 1024) == raw, 'writer-v2 API manifest changed during verification')
    return dict(path=str(path), sha256=digest(raw), cases=evidence)


def validate_build(root, receipt_path, expected_sha256, qemu):
    root, receipt_path, qemu = Path(root), Path(receipt_path), Path(qemu)
    raw = read_file(receipt_path, 256 * 1024, expected_sha256)
    receipt = object_json(raw)
    need(receipt.get('schema') == 'readonly_writer_build_v2' and receipt.get('profile') == PROFILE and
         receipt.get('trace_schema') == SCHEMA and receipt.get('source_sha256') == source_map(root),
         'writer build profile or current source identity differs')
    need(all(receipt.get(k) is False for k in FALSE), 'writer build overstates camera verification')
    need(receipt.get('qemu') == str(qemu) and receipt.get('qemu_sha256') ==
         digest(read_file(qemu, 256 * 1024 * 1024)) == QEMU_SHA256, 'writer build uses unapproved QEMU')
    header = Path(receipt['header'])
    need(receipt.get('header_sha256') == digest(read_file(header, 1024 * 1024)) == HEADER_SHA256,
         'writer API7 header differs')
    library = receipt_path.parent / 'scope-observer.so'
    need(receipt.get('library') == str(library) and digest(read_file(library, 1024 * 1024)) ==
         receipt.get('library_sha256') and receipt.get('qemu_imports') == sorted(QEMU_IMPORTS),
         'writer DSO or import audit differs')
    command_raw = read_file(receipt_path.parent / 'compile.json', 64 * 1024,
                            receipt.get('compile_receipt_sha256'))
    command = object_json(command_raw)
    need(type(command.get('returncode')) is int and command['returncode'] == 0 and
         command.get('source_sha256') == receipt['source_sha256']['scope-observer.c'] and
         command.get('library_sha256') == receipt['library_sha256'], 'writer compile receipt differs')
    proof = receipt['actual_API_evidence']
    need(verify_actual_api(proof['path'], proof['sha256'], receipt['library_sha256'],
                           receipt['self_owned_fixture_sha256']) == proof,
         'writer actual API evidence differs')
    need(read_file(receipt_path, 256 * 1024) == raw, 'writer build receipt changed during validation')
    return receipt
