"""Tests for configurable cold-boot flags, opt-out startup SHA checks, and fast caches."""
import importlib.util
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys

import pytest

ANALYSIS = Path(__file__).resolve().parent
sys.path.insert(0, str(ANALYSIS))

import original_cold_boot as cold
import sparse_seed
import virtual_loader


def _load_bodydata_launch():
    spec = importlib.util.spec_from_file_location('bodydata_launch', ANALYSIS / 'bodydata-launch.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_virtual_loader_cold_flag_force_and_clear(tmp_path, monkeypatch):
    disk_file = tmp_path / 'virtual-disk.bin'
    fd = os.open(disk_file, os.O_RDWR | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        os.ftruncate(fd, 8192)
        os.pwrite(fd, virtual_loader.WBI2_MAGIC, 4096)
        geometry = {
            'slices': [
                {'id': 'nflasha2', 'offset': 0, 'bytes': 4096},
                {'id': 'nflasha3', 'offset': 0, 'bytes': 4096},
                {'id': 'nflasha5', 'offset': 4096, 'bytes': 4096},
            ]
        }
        monkeypatch.setattr(virtual_loader, 'read_updater_mode', lambda _fd, _g: (False, None))

        strict = virtual_loader.evaluate_fd(fd, geometry, force_cold=False)
        assert strict['route']['mode'] == 11
        assert strict['resolve']['path'] == 'wbi-resume'
        assert 'forced_cold_override' not in strict

        forced = virtual_loader.evaluate_fd(fd, geometry, force_cold=True)
        assert forced['route']['mode'] == 1
        assert forced['resolve']['path'] == 'cold'
        assert forced['forced_cold_override'] is True
        assert forced['cold_flag_mode'] == 'force'

        hot = virtual_loader.evaluate_fd(fd, geometry, retained_ram=True, force_cold=True)
        assert hot['route']['mode'] == 2

        monkeypatch.setattr(virtual_loader, 'read_updater_mode', lambda _fd, _g: (True, 'UPDT'))
        updater = virtual_loader.evaluate_fd(fd, geometry, force_cold=True)
        assert updater['route']['mode'] == 3

        backup = tmp_path / 'bak/wbi2.bin'
        cleared = virtual_loader.clear_wbi2_fd(fd, geometry, backup_path=backup)
        assert cleared['changed'] is True
        assert backup.read_bytes() == virtual_loader.WBI2_MAGIC
        assert stat.S_IMODE(backup.stat().st_mode) == 0o600
        assert os.pread(fd, 4, 4096) == b'\x00' * 4

        monkeypatch.setattr(virtual_loader, 'read_updater_mode', lambda _fd, _g: (False, None))
        after_clear = virtual_loader.evaluate_fd(fd, geometry, force_cold=False)
        assert after_clear['route']['mode'] == 1
        assert after_clear['resolve']['path'] == 'cold'

        second = virtual_loader.clear_wbi2_fd(fd, geometry, backup_path=backup)
        assert second['changed'] is False
    finally:
        os.close(fd)


def test_cold_audit_copyfast(tmp_path):
    compiler = shutil.which('clang') or shutil.which('gcc')
    if not compiler:
        pytest.skip('Host C compiler unavailable')
    binary = tmp_path / 'audit-host'
    subprocess.run(
        [compiler, '-DCOLD_AUDIT_HOST', '-Wall', '-Werror', str(ANALYSIS / 'cold/cold-start-audit.c'), '-o', str(binary)],
        check=True,
    )
    src = tmp_path / 'src.bin'
    dst = tmp_path / 'dst.bin'
    payload = b'A7C2-COPYFAST-TEST-' * 2048
    src.write_bytes(payload)

    res = subprocess.run([str(binary), 'copyfast', str(src), str(dst), str(len(payload)), '644'],
                         capture_output=True, text=True, check=True)
    assert 'COLD_COPYFAST' in res.stdout and 'verified=1' in res.stdout
    assert dst.read_bytes() == payload
    assert stat.S_IMODE(dst.stat().st_mode) == 0o644

    bad_dst = tmp_path / 'bad.bin'
    bad = subprocess.run([str(binary), 'copyfast', str(src), str(bad_dst), str(len(payload) + 1), '644'],
                         capture_output=True, text=True)
    assert bad.returncode == 7


def test_sparse_seed_verify_sha_modes(tmp_path):
    if shutil.disk_usage(tmp_path).free < sparse_seed.TOTAL + 64 * 1024**3:
        pytest.skip('Sparse seed reserve requirement not met')
    img = tmp_path / 'card.fat'
    fd = os.open(img, os.O_RDWR | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        os.ftruncate(fd, sparse_seed.TOTAL)
        os.pwrite(fd, b'HDR!' * 1024, 0)
        os.pwrite(fd, b'TAIL' * 1024, 8 * 1024 * 1024)
    finally:
        os.close(fd)

    fast = sparse_seed.build(img, tmp_path / 'seed-fast', verify_sha=False)
    assert fast['sha_verified'] is False
    assert fast['sha256'] is None
    assert len(fast['chunks']) == 2
    assert (tmp_path / 'seed-fast/identity.txt').read_text().strip() == f"{sparse_seed.TOTAL} {'0' * 64}"

    # Second call with verify_sha=False hits cache cleanly without altering source/dest
    fast2 = sparse_seed.build(img, tmp_path / 'seed-fast-2', verify_sha=False)
    assert fast2['chunks'] == fast['chunks']
    assert fast2['sha_verified'] is False

    strict = sparse_seed.build(img, tmp_path / 'seed-strict', verify_sha=True)
    assert strict['sha_verified'] is True
    assert len(strict['sha256']) == 64


def test_parse_helpers_and_no_sha_scripts(tmp_path):
    assert cold.parse_cold_flag({}) == 'strict'
    assert cold.parse_cold_flag({'A7C2_COLD_FLAG': 'force'}) == 'force'
    assert cold.parse_cold_flag({'A7C2_COLD_FLAG': '1'}) == 'force'
    assert cold.parse_cold_flag({'A7C2_COLD_FLAG': 'clear'}) == 'clear'
    assert cold.parse_cold_flag({'A7C2_COLD_FLAG': '0'}) == 'strict'
    with pytest.raises(ValueError):
        cold.parse_cold_flag({'A7C2_COLD_FLAG': 'bogus'})

    assert cold.parse_verify_sha({}) is True
    assert cold.parse_verify_sha({'A7C2_VERIFY_SHA': '0'}) is False
    assert cold.parse_verify_sha({'A7C2_VERIFY_SHA': '1'}) is True
    with pytest.raises(ValueError):
        cold.parse_verify_sha({'A7C2_VERIFY_SHA': 'maybe'})

    ident = cold.guest_identity_script({}, verify_sha=False)
    assert 'openssl' not in ident
    assert '[ -f /usr/bin/im.elf ]' in ident

    fnt = tmp_path / 'font.ttf'
    fnt.write_bytes(b'123456')
    fonts_sh = cold.font_install_script({'font.ttf': fnt}, verify_sha=False)
    assert 'openssl' not in fonts_sh
    assert 'wc -c' in fonts_sh


def test_bodydata_launch_cli_env_and_quick_cache(tmp_path, monkeypatch):
    bl = _load_bodydata_launch()
    runtime = tmp_path / 'rt'
    kit = runtime / 'analysis'
    kit.mkdir(parents=True)
    (kit / 'camera_ui.py').write_text('# stub\n')
    (kit / 'prepare-assets.py').write_text('# stub\n')
    fonts_dir = kit / 'menu-root/simulation/language-fonts'
    fonts_dir.mkdir(parents=True)
    for i in range(3):
        (fonts_dir / f'f{i}.ttf').write_bytes(b'x')
    (kit / 'native-assets.json').write_text('{}\n')

    pkg = tmp_path / 'BODYDATA.DAT'
    pkg.write_bytes(b'BODYDATA-CONTENT-V1')
    cache = tmp_path / 'cache'

    def fake_unpack(package, stage, sdk, expected_sha):
        (stage / 'firmware.fdat').write_bytes(b'fdat')
        (stage / 'firmware-root').mkdir()
        return {'model': 0x20030014, 'version': '2.01', 'region': 0}

    entry1 = bl.cache_package(pkg, cache, kit, unpacker=fake_unpack, verify_sha=False)
    assert (cache / 'quick-cache.json').is_file()

    # Subsequent call with verify_sha=False must not call digest()
    monkeypatch.setattr(bl, 'digest', lambda _p: (_ for _ in ()).throw(AssertionError('digest called unexpectedly')))
    entry2 = bl.cache_package(pkg, cache, kit, unpacker=fake_unpack, verify_sha=False)
    assert entry2 == entry1

    # CLI & env resolution
    recorded = []
    monkeypatch.setattr(bl, 'discover', lambda *_a: pkg)
    monkeypatch.setattr(bl, 'cache_package', lambda *_a, **kw: (recorded.append(('cache', kw.get('verify_sha'))), entry1)[1])
    monkeypatch.setattr(bl, 'prepare', lambda *_a, **kw: recorded.append(('prepare', kw.get('verify_sha'))))
    monkeypatch.setattr(bl.subprocess, 'run', lambda cmd, check=False, env=None: (
        recorded.append(('ui', env['A7C2_COLD_FLAG'], env['A7C2_VERIFY_SHA'])),
        type('R', (), {'returncode': 0})(),
    )[1])

    monkeypatch.setenv('A7C2_RUNTIME_DIR', str(runtime))
    monkeypatch.setenv('A7C2_RUNTIME_ANALYSIS_DIR', str(kit))
    monkeypatch.delenv('A7C2_COLD_FLAG', raising=False)
    monkeypatch.delenv('A7C2_VERIFY_SHA', raising=False)
    monkeypatch.delenv('A7C2_PREPARE_ONLY', raising=False)
    rc = bl.main([])
    assert rc == 0
    assert recorded == [('cache', False), ('prepare', False), ('ui', 'force', '0')]

    recorded.clear()
    monkeypatch.setenv('A7C2_COLD_FLAG', 'clear')
    monkeypatch.setenv('A7C2_VERIFY_SHA', '1')
    rc = bl.main([])
    assert rc == 0
    assert recorded == [('cache', True), ('prepare', True), ('ui', 'clear', '1')]

    # CLI flags are rejected cleanly in favor of a7c2.env / environment variables
    recorded.clear()
    rc = bl.main(['--cold-flag', 'strict', '--no-verify-sha'])
    assert rc == 2
    assert recorded == []
