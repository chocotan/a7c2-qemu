import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import random
import stat
import struct
import tarfile
from types import SimpleNamespace

import pytest

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('capture_initramfs_test', HERE/'capture_initramfs.py')
api = importlib.util.module_from_spec(spec)
spec.loader.exec_module(api)
from firmware_overlay import _write_header
from initramfs_identity import verify_image


def base_archive(path, libraries=None):
    output = io.BytesIO()
    _write_header(output, [1, stat.S_IFDIR|0o755, 0, 0, 2, 0, 0, 0, 0, 0, 0, 0, 0], '.')
    _write_header(output, [2, stat.S_IFDIR|0o755, 0, 0, 2, 0, 0, 0, 0, 0, 0, 0, 0], 'simulation')
    if libraries:
        _write_header(output, [3, stat.S_IFDIR|0o755, 0, 0, 2, 0, 0, 0, 0, 0, 0, 0, 0], 'lib')
        for inode,(name,data) in enumerate(libraries.items(),4):
            _write_header(output, [inode, stat.S_IFREG|0o755, 0, 0, 1, 0, len(data), 0, 0, 0, 0, 0, 0], 'lib/'+name)
            output.write(data)
            output.write(b'\0' * ((-output.tell()) % 4))
    _write_header(output, [32, 0, 0, 0, 1, 0, 0, 0, 0, 0, 0, 0, 0], 'TRAILER!!!')
    path.write_bytes(output.getvalue())


def fat16_seed(path):
    size = 4*1024**2
    boot = bytearray(512)
    struct.pack_into('<H', boot, 11, 512)
    boot[13] = 1
    struct.pack_into('<H', boot, 14, 1)
    boot[16] = 2
    struct.pack_into('<HH', boot, 17, 16, size//512)
    boot[21] = 0xf8
    struct.pack_into('<H', boot, 22, 32)
    boot[510:512] = b'\x55\xaa'
    with path.open('xb') as stream:
        stream.truncate(size)
        stream.seek(0); stream.write(boot)
        for offset in (512, 33*512):
            stream.seek(offset); stream.write(b'\xf8\xff\xff\xff')


def isolated_build(tmp_path, monkeypatch):
    product = tmp_path/'product'
    analysis = product/'runtime/analysis'
    analysis.mkdir(parents=True)
    build = product/'source/build/observer-diagnostic'
    build.mkdir(parents=True, mode=0o700)
    monkeypatch.setattr(api, 'PRODUCT', product)
    monkeypatch.setattr(api, 'ANALYSIS', analysis)
    monkeypatch.setattr(api, 'RESERVE', 4096)
    monkeypatch.setattr(api, 'RAM_PEAK', 4096)
    monkeypatch.setattr(api, 'LOG_PEAK', 4096)
    simulation = analysis/'menu-root/simulation'
    simulation.mkdir(parents=True)
    library_root = analysis/'menu-root/lib'
    library_root.mkdir(parents=True)
    libraries, library_data, library_rows = {}, {}, {}
    private_lib = build/'lib'
    private_lib.mkdir(mode=0o700)
    digest = lambda data: hashlib.sha256(data).hexdigest()
    for name in ('libc-2.25.so', 'libdl-2.25.so', 'libpthread-2.25.so', 'ld-2.25.so'):
        data = ('original library '+name).encode()
        (library_root/name).write_bytes(data)
        (private_lib/name).write_bytes(data)
        libraries[str(private_lib/name)] = digest(data)
        library_data[name] = data
        library_rows['lib/'+name] = dict(sha256=digest(data),source=str(library_root/name),snapshot=str(private_lib/name))
    base_archive(analysis/'menu-initramfs.cpio', library_data)
    sources = {}
    for name in ('menu-observe.c', 'build-observers.sh'):
        path = analysis/name
        path.write_bytes(('source '+name).encode())
        sources[str(path)] = {'archive_path': 'report/runtime/analysis/'+name,
                              'sha256': digest(path.read_bytes())}
    monkeypatch.setattr(api, '_observer_sources', lambda: [Path(name) for name in sources])
    for name in ('pin-control-probe', 'system-sound-owner'):
        (simulation/name).write_bytes(name.encode())
    observer = build/'menu-observe.so'
    observer.write_bytes(b'isolated observer')
    with tarfile.open(build/'observer-build-sources.tar.gz', 'w:gz') as archive:
        for path, entry in sources.items():
            archive.add(path, arcname=entry['archive_path'])
        data = json.dumps(sources).encode()
        member = tarfile.TarInfo('source-inputs.json')
        member.size = len(data)
        archive.addfile(member, io.BytesIO(data))
    inputs = dict(sources=sources, observer_sha256=digest(observer.read_bytes()),
                  source_archive_sha256=digest((build/'observer-build-sources.tar.gz').read_bytes()),
                  pin_control_probe_sha256=digest(b'pin-control-probe'),
                  system_sound_owner_sha256=digest(b'system-sound-owner'))
    raw = json.dumps(inputs).encode()
    (build/'observer-build-inputs.json').write_bytes(raw)
    library_bytes = ''.join(f'{sha}  {path}\n' for path, sha in libraries.items()).encode()
    (build/'library-sha256sums').write_bytes(library_bytes)
    private = dict(schema='a7c2-observer-private-libraries-v1',physical_compatible=False,
                   base_initramfs_sha256=digest((analysis/'menu-initramfs.cpio').read_bytes()),libraries=library_rows)
    private_raw = json.dumps(private).encode()
    (build/'library-inputs.json').write_bytes(private_raw)
    receipt = dict(schema='a7c2-isolated-observer-build-v2', observer_only=True,
                   original_runtime_untouched=True, physical_compatible=False,
                   observer_sha256=inputs['observer_sha256'],
                   source_archive_sha256=inputs['source_archive_sha256'], source_receipt_sha256=digest(raw),
                   recipe_sha256=digest((HERE/'build-observer-diagnostic.sh').read_bytes()),
                   private_input_recipe_sha256=digest((HERE/'observer_private_inputs.py').read_bytes()),
                   private_input_receipt_sha256=digest(private_raw),libraries_sha256=digest(library_bytes),
                   helpers_reused_from=str(simulation))
    (build/'diagnostic-build.json').write_text(json.dumps(receipt))
    return build, analysis


def test_observer_base_path_exchange_during_verification_is_rejected(tmp_path, monkeypatch):
    build, analysis = isolated_build(tmp_path, monkeypatch)
    original = api.verify_image
    def exchange(image, expected):
        base = analysis/'menu-initramfs.cpio'
        saved = analysis/'original-initramfs.cpio'
        base.rename(saved)
        base.write_bytes(saved.read_bytes())
        return original(image, expected)
    monkeypatch.setattr(api, 'verify_image', exchange)
    with pytest.raises(ValueError, match='changed during readback'):
        api.validate_observer_build(build)


def test_isolated_observer_source_and_helper_provenance(tmp_path, monkeypatch):
    build, analysis = isolated_build(tmp_path, monkeypatch)
    proof = api.validate_observer_build(build)
    assert proof['observer_sha256'] == hashlib.sha256(b'isolated observer').hexdigest()
    assert not (analysis/'menu-observe.so').exists()
    (analysis/'menu-root/lib/libc-2.25.so').write_bytes(b'untrusted original changed')
    assert api.validate_observer_build(build) == proof
    (analysis/'menu-root/simulation/pin-control-probe').write_bytes(b'changed helper')
    with pytest.raises(ValueError, match='helper differs'):
        api.validate_observer_build(build)


@pytest.mark.parametrize('changed', ['source', 'observer', 'archive', 'receipt', 'library', 'library_manifest',
                                     'private_receipt', 'base', 'diagnostic'])
def test_isolated_observer_rejects_changed_inputs(tmp_path, monkeypatch, changed):
    build, analysis = isolated_build(tmp_path, monkeypatch)
    paths = {'source': analysis/'menu-observe.c', 'observer': build/'menu-observe.so',
             'archive': build/'observer-build-sources.tar.gz', 'receipt': build/'observer-build-inputs.json',
             'library': build/'lib/libc-2.25.so', 'library_manifest': build/'library-sha256sums',
             'private_receipt': build/'library-inputs.json', 'base': analysis/'menu-initramfs.cpio',
             'diagnostic': build/'diagnostic-build.json'}
    with paths[changed].open('ab') as stream:
        stream.write(b'!' if changed == 'diagnostic' else b' ')
    with pytest.raises(ValueError):
        api.validate_observer_build(build)


def test_isolated_observer_rejects_symlink_and_outside_build(tmp_path, monkeypatch):
    build, analysis = isolated_build(tmp_path, monkeypatch)
    with pytest.raises(ValueError, match='source/build'):
        api.validate_observer_build(analysis)
    alias = build.parent/'alias'
    alias.symlink_to(build, target_is_directory=True)
    with pytest.raises(ValueError, match='source/build'):
        api.validate_observer_build(alias)
    observer = build/'menu-observe.so'
    observer.unlink()
    observer.symlink_to(analysis/'menu-observe.c')
    with pytest.raises(ValueError, match='non-symlink'):
        api.validate_observer_build(build)


def test_observer_derivative_is_pair_owned_and_receipt_bound(tmp_path, monkeypatch):
    build, analysis = isolated_build(tmp_path, monkeypatch)
    pair = tmp_path/'pair'
    pair.mkdir(mode=0o700)
    base_digest = api._hash(analysis/'menu-initramfs.cpio')
    result = api.prepare_observer(pair, build)
    proof = api.validate_observer_build(build)
    verified = api.verify_observer_derivative(pair, pair/'observer-initramfs.cpio', proof)
    assert verified['observer_build'] == proof
    assert api._hash(analysis/'menu-initramfs.cpio') == base_digest
    assert result['base_sha256'] == base_digest
    assert verify_image(pair/'observer-initramfs.cpio',
                        {'simulation/menu-observe.so': proof['observer_sha256'], **proof['libraries_sha256']})
    with pytest.raises(FileExistsError):
        api.prepare_observer(pair, build)
    with pytest.raises(ValueError, match='pair-owned'):
        api.verify_observer_derivative(pair, analysis/'menu-initramfs.cpio', proof)
    receipt_path = pair/'observer-initramfs.json'
    receipt = json.loads(receipt_path.read_text())
    receipt['observer_build']['observer_sha256'] = '0'*64
    receipt_path.write_text(json.dumps(receipt))
    with pytest.raises(ValueError, match='receipt differs'):
        api.verify_observer_derivative(pair, pair/'observer-initramfs.cpio', proof)


def test_capture_derivative_layers_seed_and_observer(tmp_path, monkeypatch):
    build, analysis = isolated_build(tmp_path, monkeypatch)
    # The FAT reader remains the real product reader; only its fixture root is isolated.
    original_product = HERE.parents[1]
    (analysis.parents[1]/'report/capture-evidence').mkdir(parents=True)
    reader_source = original_product/'report/capture-evidence/check_evidence.py'
    (analysis.parents[1]/'report/capture-evidence/check_evidence.py').write_bytes(reader_source.read_bytes())
    pair = tmp_path/'pair'
    pair.mkdir(mode=0o700)
    fat16_seed(pair/'capture-seed.img')
    monkeypatch.setattr(api, 'CARD_BYTES', 4*1024**2)
    monkeypatch.setattr(api.subprocess, 'run', lambda *_args, **_kwargs: SimpleNamespace(returncode=0))
    result = api.prepare(pair, build)
    proof = api.validate_observer_build(build)
    api.verify_observer_derivative(pair, pair/'capture-initramfs.cpio', proof, capture=True)
    assert verify_image(pair/'capture-initramfs.cpio', {
        'simulation/menu-observe.so': proof['observer_sha256'],
        'simulation/sd-card.fat.gz': result['compressed_seed_sha256']})


def test_observer_derivative_space_guard_precedes_staging(tmp_path, monkeypatch):
    build, analysis = isolated_build(tmp_path, monkeypatch)
    pair = tmp_path/'pair'
    pair.mkdir(mode=0o700)
    monkeypatch.setattr(api.os, 'statvfs', lambda path: SimpleNamespace(f_frsize=1, f_bavail=1))
    with pytest.raises(ValueError, match='Insufficient space'):
        api.prepare_observer(pair, build)
    assert list(pair.iterdir()) == []


def test_guest_capture_ready_requires_real_process_and_thread_marker():
    command = api.guest_app_ready_command()
    assert '/usr/lib/appFw.so' in command and 'AppFw' in command
    api.verify_guest_app_ready_result(b'NATIVE_CAPTURE_APPFW_PID=123 TID=/proc/123/task/456\r\n')
    for raw in (b'', b'APP_INPUT_SERVER_READY\n',
                b'NATIVE_CAPTURE_APPFW_PID=123 TID=/proc/999/task/456\n'):
        with pytest.raises(ValueError, match='AppFw'):
            api.verify_guest_app_ready_result(raw)


def test_guest_seed_result_requires_one_exact_digest_marker():
    digest = 'a'*64
    command = api.guest_seed_command(digest)
    assert 'gzip -dc' in command and digest in command and '&&' in command
    marker = f'NATIVE_CAPTURE_SEED_READY bytes=1073741824 sha256={digest}'.encode()
    api.verify_guest_seed_result(b'echoed command\n'+marker+b'\r\n', digest)
    for raw in (b'', marker+b'\n'+marker+b'\n', marker.replace(b'a', b'b')+b'\n'):
        with pytest.raises(ValueError, match='missing or ambiguous'):
            api.verify_guest_seed_result(raw, digest)
    with pytest.raises(ValueError, match='digest'):
        api.guest_seed_command('x; touch /bad')


def test_private_capture_initramfs_has_verified_seed_and_no_overwrite(tmp_path, monkeypatch):
    analysis = tmp_path/'analysis'
    analysis.mkdir()
    base_archive(analysis/'menu-initramfs.cpio')
    pair = tmp_path/'pair'
    pair.mkdir(mode=0o700)
    card = pair/'capture-seed.img'
    fat16_seed(card)
    monkeypatch.setattr(api, 'ANALYSIS', analysis)
    monkeypatch.setattr(api, 'CARD_BYTES', 4*1024**2)
    def fsck(argv, **kwargs):
        assert argv[:2] == ['fsck.fat', '-n']
        kwargs['stdout'].write(b'fsck fixture\n')
        return SimpleNamespace(returncode=0)
    monkeypatch.setattr(api.subprocess, 'run', fsck)
    result = api.prepare(pair)
    with card.open('rb') as stream:
        digest = hashlib.file_digest(stream, 'sha256').hexdigest()
    assert result['seed_sha256'] == digest and result['seed_fsck_rc'] == 0
    assert result['original_image_modified'] is False and result['capture_verified'] is False
    assert verify_image(pair/'capture-initramfs.cpio',
                        {'simulation/sd-card.fat.gz': result['compressed_seed_sha256']})
    assert (pair/'capture-initramfs.json').is_file()
    with pytest.raises(FileExistsError):
        api.prepare(pair)


@pytest.mark.parametrize('incompressible', [False, True])
def test_capture_rejects_initrd_window_overflow_before_output(tmp_path, monkeypatch, incompressible):
    analysis = tmp_path/'analysis'
    analysis.mkdir()
    base_archive(analysis/'menu-initramfs.cpio')
    pair = tmp_path/'pair'
    pair.mkdir(mode=0o700)
    card = pair/'capture-seed.img'
    fat16_seed(card)
    if incompressible:
        # Already compressed JPEG data has the same relevant property: gzip saves little.
        with card.open('r+b') as stream:
            stream.seek(66*512)
            stream.write(random.Random(0).randbytes(4*1024**2-66*512))
    monkeypatch.setattr(api, 'ANALYSIS', analysis)
    monkeypatch.setattr(api, 'CARD_BYTES', 4*1024**2)
    monkeypatch.setattr(api, 'INITRD_WINDOW', 1024**2 if incompressible else 4096)
    monkeypatch.setattr(api.subprocess, 'run', lambda *_args, **_kwargs: SimpleNamespace(returncode=0))
    with pytest.raises(ValueError, match='window expansion is forbidden'):
        api.prepare(pair)
    assert api.INITRD_WINDOW == (1024**2 if incompressible else 4096)
    assert not (pair/'capture-initramfs.cpio').exists()
    assert not (pair/'capture-initramfs.json').exists()
    assert (pair/'capture-overlay/simulation/sd-card.fat.gz').is_file()


def test_capture_rejects_unsupported_fat_geometry_before_fsck(tmp_path, monkeypatch):
    analysis = tmp_path/'analysis'
    analysis.mkdir()
    base_archive(analysis/'menu-initramfs.cpio')
    pair = tmp_path/'pair'
    pair.mkdir(mode=0o700)
    card = pair/'capture-seed.img'
    fat16_seed(card)
    with card.open('r+b') as stream:
        stream.seek(17)
        stream.write(b'\0\0')
    monkeypatch.setattr(api, 'ANALYSIS', analysis)
    monkeypatch.setattr(api, 'CARD_BYTES', 4*1024**2)
    with pytest.raises(ValueError, match='FAT16'):
        api.prepare(pair)
    assert not (pair/'capture-seed-fsck.stdout.raw').exists()


def test_private_capture_refuses_insufficient_space_before_staging(tmp_path, monkeypatch):
    analysis = tmp_path/'analysis'
    analysis.mkdir()
    base_archive(analysis/'menu-initramfs.cpio')
    pair = tmp_path/'pair'
    pair.mkdir(mode=0o700)
    monkeypatch.setattr(api, 'ANALYSIS', analysis)
    monkeypatch.setattr(api.os, 'statvfs', lambda _path: SimpleNamespace(f_frsize=4096, f_bavail=1))
    with pytest.raises(ValueError, match='Insufficient space'):
        api.prepare(pair)
    assert list(pair.iterdir()) == []


def test_private_capture_rejects_symlink_pair(tmp_path):
    actual = tmp_path/'actual'
    actual.mkdir()
    alias = tmp_path/'alias'
    alias.symlink_to(actual, target_is_directory=True)
    with pytest.raises(ValueError, match='non-symlink'):
        api.prepare(alias)
