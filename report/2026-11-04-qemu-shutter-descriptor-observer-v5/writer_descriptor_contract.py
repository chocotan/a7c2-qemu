"""Draft contract for the next independent once variant; not imported by active tools."""
from pathlib import Path
import hashlib
import importlib.util
import sys


def need(ok, message):
    if not ok:
        raise ValueError(message)


def load_api(component):
    component = Path(component)
    need(component.is_absolute() and component.resolve(strict=True) == component,
         'fixed canonical writer component required')
    sys.path.insert(0, str(component))
    spec = importlib.util.spec_from_file_location('next_once_descriptor_writer_build', component / 'writer_descriptor_bundle.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def bind_approved(component, receipt_ref, qemu, frozen):
    """The once source approval must pin receipt_ref as a literal external input."""
    component = Path(component)
    for name in ('writer_descriptor_bundle.py', 'writer_descriptor_trace.py', 'writer_descriptor_record_trace.py', 'writer_descriptor_upstream_trace.py', 'writer_descriptor_upstream_trace_base.py', 'writer_descriptor_api.py'):
        path = component / name
        need(path.is_absolute() and path.resolve(strict=True) == path and
             not any(item.is_symlink() for item in (path, *path.parents)) and
             frozen.get(str(path)) == hashlib.sha256(path.read_bytes()).hexdigest(),
             'writer dependency is not pinned before import: ' + name)
        existing = sys.modules.get(path.stem)
        need(existing is None or Path(existing.__file__).resolve(strict=True) == path,
             'writer dependency module name belongs to another source')
    api = load_api(component)
    need(type(receipt_ref) is dict and set(receipt_ref) == {'path', 'sha256'}, 'explicit writer receipt reference required')
    receipt = api.validate_build(component, receipt_ref['path'], receipt_ref['sha256'], qemu)
    source_pins = {str(Path(component) / name): value for name, value in receipt['source_sha256'].items()}
    need(all(frozen.get(path) == digest for path, digest in source_pins.items()),
         'writer sources are absent from the approved complete batch')
    return dict(profile=receipt['profile'], trace_schema=receipt['trace_schema'], build_receipt=dict(receipt_ref),
        library=dict(path=receipt['library'], sha256=receipt['library_sha256']), qemu=dict(path=str(qemu),
        sha256=receipt['qemu_sha256']), source_sha256=source_pins,
        relative_source_sha256=dict(receipt['source_sha256']),
        actual_API_evidence=receipt['actual_API_evidence'], source_contract='auxiliary-writer-with-strict-gate2-v5',
        Sony_runtime_verified=False, capture_verified=False, physical_asic_compatibility_verified=False)


def check_plugin_command(raw):
    """Validate already-read host /proc argv bytes; never read guest memory."""
    need(type(raw) is bytes and 0 < len(raw) <= 32768 and raw.endswith(b'\0'),
         'complete bounded writer QEMU command required')
    arguments = raw[:-1].split(b'\0')
    need(arguments and all(arguments) and arguments[0].startswith(b'/'), 'invalid writer QEMU argv')
    plugins = []
    for index, argument in enumerate(arguments):
        if argument == b'-plugin':
            need(index + 1 < len(arguments), 'writer plugin argument missing')
            plugins.append(arguments[index + 1])
        elif argument.startswith((b'-plugin=', b'--plugin')):
            need(False, 'writer plugin alias is not admitted')
    need(plugins == [b'/scope-observer.so,log=/out/readonly-scope-trace.log',
                     b'/shutter-writer.so,log=/out/readonly-shutter-writer.log'],
         'writer/primary plugin command differs or contains an extra plugin')
    return dict(command_sha256=hashlib.sha256(raw).hexdigest(),
                primary_plugin=plugins[0].decode(), writer_plugin=plugins[1].decode(),
                AP_identity_verified=False, capture_verified=False)


def check_plan(plan, approved):
    settings = plan['settings']
    need(plan.get('auxiliary_writer_expected') == approved and
         settings.get('A7C2_SHUTTER_WRITER_PROFILE') == approved['profile'] and
         settings.get('A7C2_SHUTTER_WRITER_BUILD') == approved['build_receipt']['path'] and
         settings.get('A7C2_SHUTTER_WRITER_BUILD_SHA256') == approved['build_receipt']['sha256'],
         'writer plan/configuration differs from approved auxiliary receipt')
    need(not any(name in settings for name in ('QEMU_SHUTTER_WRITER_PLUGIN', 'QEMU_SHUTTER_WRITER_SHA256')),
         'writer staged-child environment cannot be supplied by plan')
    need(all(plan['auxiliary_writer_expected'].get(key) is False for key in
         ('Sony_runtime_verified', 'capture_verified', 'physical_asic_compatibility_verified')),
         'writer-v5 plan claims must be exact false booleans')


def check_manifest(run, manifest, intent, approved):
    """Primary scope keeps its exact gate-v2 metadata; writer gets an independent field."""
    run = Path(run)
    metadata = manifest.get('readonly_shutter_writer')
    need(type(metadata) is dict and intent.get('auxiliary_writer_expected') == approved,
         'missing writer manifest or same-generation intent binding')
    expected = dict(profile=approved['profile'], trace_schema=approved['trace_schema'],
        build_receipt=approved['build_receipt']['path'], build_receipt_sha256=approved['build_receipt']['sha256'],
        library=str(run / 'readonly-shutter-writer.so'), library_sha256=approved['library']['sha256'],
        log=str(run / 'readonly-shutter-writer.log'), qemu=approved['qemu']['path'],
        qemu_sha256=approved['qemu']['sha256'],
        source_sha256=approved['relative_source_sha256'],
        actual_API_evidence=approved['actual_API_evidence'], primary_profile='qemu-readonly-shutter-gate-v2',
        identity_binding='unverified', Sony_runtime_verified=False, profile_attached_to_camera=False,
        AP_identity_verified=False, invocation_pairing_verified=False, store_retirement_verified=False,
        capture_verified=False, physical_asic_compatibility_verified=False)
    need(metadata == expected and all(metadata.get(key) is False for key in
         ('Sony_runtime_verified', 'profile_attached_to_camera', 'AP_identity_verified',
          'invocation_pairing_verified', 'store_retirement_verified', 'capture_verified',
          'physical_asic_compatibility_verified')),
         'writer manifest metadata differs from approved run paths and source closure')
    files = manifest['files']
    need(files.get(approved['build_receipt']['path']) == approved['build_receipt']['sha256'] and
         files.get(expected['library']) == expected['library_sha256'] and
         all(files.get(path) == value for path, value in approved['source_sha256'].items()),
         'writer runtime assets or implementation absent from manifest')
    return metadata
