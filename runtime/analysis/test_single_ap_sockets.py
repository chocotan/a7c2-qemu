"""Prepared host checks; no QEMU, device, socket, signal or lease operation."""
import json
import os
from pathlib import Path
import runpy

import pytest
import single_ap_sockets as ap


def selected(**extra):
    return {ap.PROFILE_ENV: ap.PROFILE,
            ap.ROOT_ENV: '/run/user/1000/single-ap-test', **extra}


def forbidden(*args, **kwargs):
    pytest.fail('runtime resource accessed before the closed gate')


def test_legacy_selection_does_not_allocate(monkeypatch, tmp_path):
    monkeypatch.setattr(ap, 'DiagnosticRoots', forbidden)
    assert ap.admit({}) is False
    assert ap.prepare({}, tmp_path) == {}
    assert ap.roots_for_run(tmp_path, {}) is None
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize('environment', [
    {ap.ROOT_ENV: '/run/user/1000/s'},
    {ap.PROFILE_ENV: ap.PROFILE},
    {ap.PROFILE_ENV: 'unknown', ap.ROOT_ENV: '/run/user/1000/s'},
    {ap.PROFILE_ENV: ap.PROFILE, ap.ROOT_ENV: ''},
    {ap.PROFILE_ENV: '', ap.ROOT_ENV: ''},
])
def test_bad_selection_rejected(environment):
    with pytest.raises(ValueError, match='exact profile'):
        ap.admit(environment)


def test_explicit_selection_blocked_before_resources(monkeypatch):
    monkeypatch.setattr(ap, 'DiagnosticRoots', forbidden)
    monkeypatch.setattr(ap, 'read_binding', forbidden)
    with pytest.raises(RuntimeError, match='single AP disk owner'):
        ap.prepare(selected(), '/does-not-exist')
    with pytest.raises(RuntimeError, match='single AP disk owner'):
        ap.roots_for_run('/does-not-exist', selected())


@pytest.mark.parametrize('flag', ap.EXCLUDED_ROUTES)
@pytest.mark.parametrize('value', ['1', 'profile-or-path', 'invalid'])
def test_frontend_and_backend_unmigrated_routes_rejected(monkeypatch, flag, value):
    monkeypatch.setattr(ap, 'require_runtime_ready', forbidden)
    with pytest.raises(ValueError, match=flag):
        ap.admit(selected(**{flag: value}))


@pytest.mark.parametrize('flag', ap.EXCLUDED_ROUTES)
def test_unselected_legacy_routes_are_untouched(flag):
    assert ap.admit({flag: 'legacy-profile'}) is False


def test_explicit_disabled_flags_still_hit_fixed_gate():
    with pytest.raises(RuntimeError, match='BLOCKED'):
        ap.admit(selected(**{name: '0' for name in ap.EXCLUDED_ROUTES}))


def receipt(tmp_path, value=None, raw=None):
    if value is None:
        value = dict(profile=ap.PROFILE, files=str(tmp_path),
                     sockets='/run/user/1000/s', directories={})
    path = tmp_path / ap.BINDING_NAME
    path.write_text(json.dumps(value) if raw is None else raw)
    path.chmod(0o600)
    return path


def test_receipt_does_not_unlock_run(monkeypatch, tmp_path):
    receipt(tmp_path)
    monkeypatch.setattr(ap, 'DiagnosticRoots', forbidden)
    with pytest.raises(RuntimeError, match='BLOCKED'):
        ap.roots_for_run(tmp_path, {})


@pytest.mark.parametrize('value', [[], None, 'receipt', {},
    dict(profile=ap.PROFILE, files='different-run', sockets='/s', directories={}),
    dict(profile=ap.PROFILE, files='different-run', sockets=1, directories=[]),
])
def test_invalid_receipt_shape_rejected(tmp_path, value):
    receipt(tmp_path, raw=json.dumps(value))
    with pytest.raises(ValueError):
        ap.read_binding(tmp_path)


def test_duplicate_receipt_key_rejected(tmp_path):
    receipt(tmp_path, raw='{"profile":"x","profile":"y"}')
    with pytest.raises(ValueError, match='duplicate'):
        ap.read_binding(tmp_path)


@pytest.mark.parametrize('mode', [0o644, 0o400, 0o700])
def test_unsafe_receipt_permissions_rejected(tmp_path, mode):
    path = receipt(tmp_path)
    path.chmod(mode)
    with pytest.raises(ValueError, match='unsafe'):
        ap.read_binding(tmp_path)


def test_linked_receipts_rejected(tmp_path):
    source = receipt(tmp_path)
    alias = tmp_path / 'alias'
    os.link(source, alias)
    with pytest.raises(ValueError, match='unsafe'):
        ap.read_binding(tmp_path)


def test_symlink_receipt_rejected(tmp_path):
    path = receipt(tmp_path)
    original = tmp_path / 'original'
    path.rename(original)
    path.symlink_to(original)
    with pytest.raises(OSError):
        ap.read_binding(tmp_path)


def test_valid_receipt_readback(tmp_path):
    path = receipt(tmp_path)
    assert ap.read_binding(tmp_path) == json.loads(path.read_text())


def test_cli_default_returns_normally(monkeypatch):
    monkeypatch.delenv(ap.PROFILE_ENV, raising=False)
    monkeypatch.delenv(ap.ROOT_ENV, raising=False)
    runpy.run_path(str(Path(ap.__file__)), run_name='__main__')


@pytest.mark.parametrize('environment,error', [
    ({ap.PROFILE_ENV: ap.PROFILE}, ValueError),
    (selected(), RuntimeError),
])
def test_cli_rejection_propagates_for_nonzero_exit(monkeypatch, environment, error):
    for name in (ap.PROFILE_ENV, ap.ROOT_ENV, *ap.EXCLUDED_ROUTES):
        monkeypatch.delenv(name, raising=False)
    for name, value in environment.items():
        monkeypatch.setenv(name, value)
    with pytest.raises(error):
        runpy.run_path(str(Path(ap.__file__)), run_name='__main__')
