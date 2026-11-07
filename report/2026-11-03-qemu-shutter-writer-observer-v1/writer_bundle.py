"""An independent writer DSO receipt; this does not replace any shutter-gate profile."""
from pathlib import Path
import json

from writer_trace import PROFILE, SCHEMA, digest, need, parse_trace, read_file

QEMU_SHA256 = '4e85c70ba38774e9439562a7178a65bdbe6b660fdf8dd6bd4ece686fb707a4d4'
HEADER_SHA256 = '335d4e472067e914add598b60d1f7cf0dc029cd48f62f66656d6a88c54d8d9f9'
SOURCE_NAMES = ('scope-observer.c', 'writer_trace.py', 'writer_bundle.py', 'writer_runtime.py',
                'writer_contract.py', 'build_observer.py', 'integration/fixture.S', 'integration/link.ld')
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
    need(manifest.get('status') == 'PASS_SELF_OWNED_WRITER_ACTUAL_QEMU_API_NOT_SONY_RUNTIME_OR_PROFILE_ADMISSION' and
         type(manifest.get('returncode')) is int and manifest['returncode'] == 0 and
         manifest.get('QEMU_actual_API_run') is True and manifest.get('Sony_guest_run') is False and
         manifest.get('normal_writer_runtime_observed') is False and manifest.get('profile_admitted') is False and
         manifest.get('capture_verified') is False and manifest.get('physical_asic_compatibility_verified') is False,
         'writer fixture manifest scope or outcome differs')
    commands = manifest.get('commands')
    need(type(commands) is list and len(commands) == 3 and [c.get('case') for c in commands] ==
         ['original', 'equivalent-mutation', 'short-tb'], 'writer actual API cases differ')
    evidence, values = {}, [1] * 3 + [0] * 3 + [0xffffffff] * 3
    for command in commands:
        case = command['case']
        need(command.get('qemu_sha256') == QEMU_SHA256 and command.get('plugin_sha256') == library_sha256 and
             type(command.get('returncode')) is int and command['returncode'] == 0 and
             command.get('timed_out') is False and command.get('signals_sent') == command.get('QMP_calls') == 0 and
             command.get('CPU_readback_verified') is True, 'writer actual API used different assets or failed')
        directory = path.parent / case
        result_raw = read_file(directory / 'content-result.json', 64 * 1024)
        result = object_json(result_raw)
        trace = read_file(directory / 'plugin.log', expected_sha256=result.get('trace_sha256'))
        console = read_file(directory / 'console.bin', 4096, result.get('console_sha256'))
        elf = read_file(directory / 'fixture.elf', 1024 * 1024, command.get('elf_sha256'))
        need(console == b'WRITER_CPU_READBACK_PASS values=1,0,ffffffff\n' and
             result.get('CPU_readback_verified') is True and result.get('capture_verified') is False,
             'writer fixture CPU content readback differs')
        observed = parse_trace(trace)
        expected_callbacks = 9 if case == 'original' else 0
        need(command.get('plugin_callbacks') == result.get('plugin_callbacks') == expected_callbacks ==
             len(observed['events']), 'writer actual callback count differs')
        if case == 'original':
            need(digest(elf) == fixture_sha256 and [e['input_w0'] for e in observed['events']] == values and
                 [e['site'] for e in observed['events']] == ['setter_entry', 'store_pre', 'ret_pre'] * 3,
                 'writer original fixture source/input observation differs')
        else:
            need(not observed['candidate_found'], 'writer negative fixture was matched')
        evidence[case] = dict(result_sha256=digest(result_raw), trace_sha256=digest(trace),
            console_sha256=digest(console), elf_sha256=digest(elf), callbacks=expected_callbacks)
    need(read_file(path, 4 * 1024 * 1024) == raw, 'writer API manifest changed during verification')
    return dict(path=str(path), sha256=digest(raw), cases=evidence)


def validate_build(root, receipt_path, expected_sha256, qemu):
    root, receipt_path, qemu = Path(root), Path(receipt_path), Path(qemu)
    raw = read_file(receipt_path, 256 * 1024, expected_sha256)
    receipt = object_json(raw)
    need(receipt.get('schema') == 'readonly_writer_build_v1' and receipt.get('profile') == PROFILE and
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
