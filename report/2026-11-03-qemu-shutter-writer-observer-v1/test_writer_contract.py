import hashlib
from pathlib import Path
import sys
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import writer_contract as c


def approved_fixture(run):
    source = {str(HERE / 'scope-observer.c'): 'b' * 64}
    approved = dict(profile='qemu-readonly-shutter-writer-v1', trace_schema='readonly_shutter_writer_v1',
        build_receipt=dict(path='/approved/build-receipt.json', sha256='a' * 64),
        library=dict(path='/approved/scope-observer.so', sha256='c' * 64),
        qemu=dict(path='/approved/qemu-system-aarch64', sha256='d' * 64), source_sha256=source,
        relative_source_sha256={'scope-observer.c': 'b' * 64}, actual_API_evidence={'source': 'measured'})
    metadata = dict(profile=approved['profile'], trace_schema=approved['trace_schema'],
        build_receipt=approved['build_receipt']['path'], build_receipt_sha256='a' * 64,
        library=str(run / 'readonly-shutter-writer.so'), library_sha256='c' * 64,
        log=str(run / 'readonly-shutter-writer.log'), qemu=approved['qemu']['path'], qemu_sha256='d' * 64,
        source_sha256=approved['relative_source_sha256'], actual_API_evidence=approved['actual_API_evidence'],
        primary_profile='qemu-readonly-shutter-gate-v2', identity_binding='unverified',
        Sony_runtime_verified=False, profile_attached_to_camera=False, AP_identity_verified=False,
        invocation_pairing_verified=False, store_retirement_verified=False, capture_verified=False,
        physical_asic_compatibility_verified=False)
    manifest = dict(readonly_shutter_writer=metadata,
        files={**source, approved['build_receipt']['path']: 'a' * 64, metadata['library']: 'c' * 64})
    plan = dict(auxiliary_writer_expected=approved, settings=dict(A7C2_SHUTTER_WRITER_BUILD='/approved/build-receipt.json',
        A7C2_SHUTTER_WRITER_BUILD_SHA256='a' * 64))
    return approved, metadata, manifest, plan


def test_missing_source_pins_fail_before_loader_or_receipt_access(monkeypatch):
    loader = Mock(side_effect=AssertionError('must refuse before loading unpinned module'))
    monkeypatch.setattr(c, 'load_api', loader)
    with pytest.raises(ValueError, match='pinned before import'):
        c.bind_approved(HERE, {'path': '/missing', 'sha256': 'a' * 64}, Path('/qemu'), {})
    loader.assert_not_called()


def test_foreign_preloaded_dependency_name_refused_before_loader(monkeypatch, tmp_path):
    sourcepins = {str(HERE / name): hashlib.sha256((HERE / name).read_bytes()).hexdigest()
                  for name in ('writer_bundle.py', 'writer_trace.py')}
    foreign = tmp_path / 'writer_bundle.py'
    foreign.write_text('# foreign module\n')
    monkeypatch.setitem(sys.modules, 'writer_bundle', SimpleNamespace(__file__=str(foreign)))
    loader = Mock(side_effect=AssertionError('must refuse name collision'))
    monkeypatch.setattr(c, 'load_api', loader)
    with pytest.raises(ValueError, match='another source'):
        c.bind_approved(HERE, {'path': '/missing', 'sha256': 'a' * 64}, Path('/qemu'), sourcepins)
    loader.assert_not_called()


def test_explicit_primary_and_writer_plugin_command():
    raw = (b'/tools/qemu-system-aarch64\0-smp\0001\0-plugin\0'
           b'/scope-observer.so,log=/out/readonly-scope-trace.log\0-plugin\0'
           b'/shutter-writer.so,log=/out/readonly-shutter-writer.log\0')
    proof = c.check_plugin_command(raw)
    assert proof['command_sha256'] == hashlib.sha256(raw).hexdigest()
    assert proof['AP_identity_verified'] is False and proof['capture_verified'] is False
    for bad in (raw[:-1], raw + b'-plugin\0/injected.so\0',
                raw.replace(b'-plugin\0', b'--plugin\0', 1),
                raw.replace(b'-plugin\0', b'-plugin=/unknown\0', 1),
                raw.replace(b'/shutter-writer.so', b'/other.so'),
                raw.replace(b'/scope-observer.so', b'/other-primary.so'),
                raw.replace(b'\0-smp', b'\0\0-smp'), b'/qemu\0-plugin\0'):
        with pytest.raises(ValueError):
            c.check_plugin_command(bad)


def test_exact_plan_and_independent_manifest_contract(tmp_path):
    approved, metadata, manifest, plan = approved_fixture(tmp_path)
    c.check_plan(plan, approved)
    assert c.check_manifest(tmp_path, manifest, {'auxiliary_writer_expected': approved}, approved) == metadata
    assert metadata['capture_verified'] is False


@pytest.mark.parametrize('change', ['missing-reference', 'wrong-path', 'wrong-sha', 'injected-child'])
def test_changed_plan_receipt_or_child_configuration_is_refused(tmp_path, change):
    approved, _, _, plan = approved_fixture(tmp_path)
    if change == 'missing-reference':
        plan.pop('auxiliary_writer_expected')
    elif change == 'wrong-path':
        plan['settings']['A7C2_SHUTTER_WRITER_BUILD'] = '/other/build.json'
    elif change == 'wrong-sha':
        plan['settings']['A7C2_SHUTTER_WRITER_BUILD_SHA256'] = '0' * 64
    else:
        plan['settings']['QEMU_SHUTTER_WRITER_PLUGIN'] = '/injected.so'
    with pytest.raises(ValueError):
        c.check_plan(plan, approved)


@pytest.mark.parametrize('change', ['different-run', 'missing-source-index', 'missing-receipt-index',
    'wrong-library', 'wrong-source', 'capture-claim', 'Sony-claim', 'wrong-primary', 'missing-intent'])
def test_manifest_must_match_this_run_and_all_approved_assets(tmp_path, change):
    approved, metadata, manifest, plan = approved_fixture(tmp_path)
    intent = {'auxiliary_writer_expected': approved}
    if change == 'different-run':
        metadata['log'] = '/foreign/readonly-shutter-writer.log'
    elif change == 'missing-source-index':
        manifest['files'].pop(next(iter(approved['source_sha256'])))
    elif change == 'missing-receipt-index':
        manifest['files'].pop(approved['build_receipt']['path'])
    elif change == 'wrong-library':
        metadata['library_sha256'] = '0' * 64
    elif change == 'wrong-source':
        metadata['source_sha256'] = {'scope-observer.c': '0' * 64}
    elif change == 'capture-claim':
        metadata['capture_verified'] = True
    elif change == 'Sony-claim':
        metadata['Sony_runtime_verified'] = True
    elif change == 'wrong-primary':
        metadata['primary_profile'] = 'qemu-readonly-shutter-gate-v1'
    else:
        intent = {}
    with pytest.raises(ValueError):
        c.check_manifest(tmp_path, manifest, intent, approved)
