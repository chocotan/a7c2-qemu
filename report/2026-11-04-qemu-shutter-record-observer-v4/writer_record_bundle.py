"""Independent record observer build identity; no Sony admission from host API."""
from pathlib import Path
from writer_record_trace import PROFILE, SCHEMA, parse_trace
from writer_record_api import verify_actual_api, object_json, QEMU_SHA256, IMPORTS as QEMU_IMPORTS
from writer_record_upstream_trace_base import digest, need, read_file
HEADER_SHA256 = '335d4e472067e914add598b60d1f7cf0dc029cd48f62f66656d6a88c54d8d9f9'
SOURCE_NAMES = ('scope-observer.c', 'record-taps.inc', 'writer_record_trace.py',
    'writer_record_upstream_trace.py', 'writer_record_upstream_trace_base.py', 'writer_record_api.py',
    'writer_record_bundle.py', 'writer_record_runtime.py', 'writer_record_contract.py',
    'build_record_observer.py', 'integration/fixture.S', 'integration/link.ld')
FALSE = dict(Sony_runtime_verified=False, profile_attached_to_camera=False, AP_identity_verified=False,
    invocation_pairing_verified=False, store_retirement_verified=False, capture_verified=False,
    physical_asic_compatibility_verified=False)

def source_map(root):
    return {name:digest(read_file(root/name,1024*1024)) for name in SOURCE_NAMES}

def validate_build(root, receipt_path, expected_sha256, qemu):
    root, receipt_path, qemu = (Path(root), Path(receipt_path), Path(qemu))
    raw = read_file(receipt_path, 256 * 1024, expected_sha256)
    receipt = object_json(raw)
    need(receipt.get('schema') == 'readonly_writer_build_v4' and receipt.get('profile') == PROFILE and (receipt.get('trace_schema') == SCHEMA) and (receipt.get('source_sha256') == source_map(root)), 'writer build profile or current source identity differs')
    need(all((receipt.get(k) is False for k in FALSE)), 'writer build overstates camera verification')
    need(receipt.get('qemu') == str(qemu) and receipt.get('qemu_sha256') == digest(read_file(qemu, 256 * 1024 * 1024)) == QEMU_SHA256, 'writer build uses unapproved QEMU')
    header = Path(receipt['header'])
    need(receipt.get('header_sha256') == digest(read_file(header, 1024 * 1024)) == HEADER_SHA256, 'writer API7 header differs')
    library = receipt_path.parent / 'scope-observer.so'
    need(receipt.get('library') == str(library) and digest(read_file(library, 1024 * 1024)) == receipt.get('library_sha256') and (receipt.get('qemu_imports') == sorted(QEMU_IMPORTS)), 'writer DSO or import audit differs')
    command_raw = read_file(receipt_path.parent / 'compile.json', 64 * 1024, receipt.get('compile_receipt_sha256'))
    command = object_json(command_raw)
    need(type(command.get('returncode')) is int and command['returncode'] == 0 and (command.get('source_sha256') == receipt['source_sha256']['scope-observer.c']) and (command.get('library_sha256') == receipt['library_sha256']), 'writer compile receipt differs')
    proof = receipt['actual_API_evidence']
    need(verify_actual_api(proof['path'], proof['sha256'], receipt['library_sha256'], receipt['self_owned_fixture_sha256']) == proof and all((receipt['source_sha256'].get(name) == value for name, value in proof['measured_source_sha256'].items())), 'writer actual API evidence or measured source bytes differ')
    need(read_file(receipt_path, 256 * 1024) == raw, 'writer build receipt changed during validation')
    return receipt
