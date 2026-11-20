"""Host-only contracts. Run only when authorized, with --basetemp inside the project."""
import hashlib
import importlib.util
import json
import os
import fcntl
from pathlib import Path
import stat
from types import SimpleNamespace

import pytest

spec = importlib.util.spec_from_file_location('cp_native_link', Path(__file__).with_name('native-link.py'))
link = importlib.util.module_from_spec(spec)
spec.loader.exec_module(link)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def write_json(path, value):
    path.write_text(json.dumps(value, sort_keys=True) + '\n', encoding='utf-8')


def rewrite_manifest(directory, mutate):
    path = directory / link.MANIFEST
    value = json.loads(path.read_bytes())
    mutate(value)
    write_json(path, value)


@pytest.fixture
def inputs(tmp_path, monkeypatch):
    tree = tmp_path / 'source'
    build = tree / 'build'
    build.mkdir(parents=True)
    binary = build / 'qemu-system-aarch64'
    binary.write_bytes(b'native host contract fixture; never execute\n')
    binary.chmod(0o755)
    source = tree / 'hw' / 'board.c'
    source.parent.mkdir()
    source.write_bytes(b'fixture native board source\n')
    outputs = {'hw/board.c': sha(source.read_bytes())}
    notify = dict(profile=link.GPIO_PROFILE, default_off=True, inherited_sources={}, outputs=outputs)
    peripherals = dict(schema='a7c2-cp-peripherals-stage-v6', profile=link.PERIPHERALS_PROFILE,
                       default_off=True, inherited_sources={}, outputs=outputs,
                       native_link_profile=link.PROFILE, native_link_default_off=True)
    write_json(tree / 'cp-notify-stage.json', notify)
    write_json(tree / 'cp-peripherals-stage.json', peripherals)
    proof = dict(profile=link.GPIO_PROFILE, binary_sha256=sha(binary.read_bytes()),
                 stage_sha256=sha((tree / 'cp-notify-stage.json').read_bytes()),
                 peripherals_stage_sha256=sha((tree / 'cp-peripherals-stage.json').read_bytes()),
                 complete_contract_fixture=True)
    write_json(build / 'cp-notify-build.json', proof)
    calls = []

    def mock_contract(candidate, require_peripherals=False):
        calls.append((candidate, require_peripherals))
        assert candidate == binary and require_peripherals is True
        return json.loads((build / 'cp-notify-build.json').read_bytes())

    def mock_run_path(path):
        assert Path(path) == link.HERE / 'check-notify-qemu.py'
        return {'contract': mock_contract}

    # Only tests replace the existing binary contract; production has no bypass flag.
    monkeypatch.setattr(link.runpy, 'run_path', mock_run_path)
    monkeypatch.setattr(link.os, 'fstatvfs', lambda fd: SimpleNamespace(f_bavail=1024 ** 4, f_frsize=1))
    return SimpleNamespace(tree=tree, build=build, binary=binary, source=source,
                           directory=tmp_path / 'pair', calls=calls)


@pytest.fixture
def pair(inputs):
    inputs.manifest = link.prepare(inputs.directory, inputs.binary)
    return inputs


def ap_environment(directory):
    return dict(link.environment('ap', directory), QEMU_UI_LIVE='1', QEMU_TIMEOUT_SECONDS='0')


def test_prepare_sparse_geometry_full_identity_and_no_claim(inputs, monkeypatch):
    real_digest = link._digest

    def no_ram_hash(path):
        assert Path(path).name not in link.FILE_SIZES, 'Dynamic RAM must never be SHA256 input'
        return real_digest(path)

    monkeypatch.setattr(link, '_digest', no_ram_hash)
    manifest = link.prepare(inputs.directory, inputs.binary)
    assert link.PROFILE == 'virtual-native-ap-cp-link-v1'
    assert manifest['status'] == 'prepared' and manifest['schema'] == link.SCHEMA
    assert manifest['directory'] == str(inputs.directory)
    assert stat.S_IMODE(inputs.directory.stat().st_mode) == 0o700
    assert (inputs.directory / link.MANIFEST).stat().st_mode == stat.S_IFREG | 0o600
    assert manifest['binary']['sha256'] == sha(inputs.binary.read_bytes())
    assert manifest['binary']['path'] == str(inputs.binary)
    assert inputs.binary.stat().st_mode == stat.S_IFREG | 0o755
    assert set(manifest['files']) == {'ap-ram.bin', 'cp-ram.bin', 'cp-oom.bin'}
    assert [manifest['files'][name]['size'] for name in link.FILE_SIZES] == [24 * 1024 ** 3, 128 * 1024 ** 2, 0x101000]
    inodes = set()
    for name, record in manifest['files'].items():
        value = (inputs.directory / name).stat()
        assert record == dict(dev=value.st_dev, ino=value.st_ino, size=value.st_size,
                              mode=stat.S_IFREG | 0o600, uid=os.geteuid(), nlink=1)
        assert value.st_blocks * 512 < 1024 ** 2
        inodes.add((record['dev'], record['ino']))
    assert len(inodes) == 3
    budget = manifest['storage']
    assert link.RESERVE == 64 * 1024 ** 3
    assert budget['required_bytes'] == 24 * 1024 ** 3 + 128 * 1024 ** 2 + 0x101000 + 512 * 1024 ** 2 + 64 * 1024 ** 3
    assert budget['fits'] is True
    assert not any(manifest[name] for name in ('physical_hardware_verified', 'fullboot_verified', 'original_ap_consumed'))
    assert link.admit(inputs.directory, inputs.binary) == manifest
    assert len(inputs.calls) == 2 and all(required for _, required in inputs.calls)
    assert not (inputs.directory / 'ap-admission.claim').exists()
    assert not (inputs.directory / link.FAILURE_MANIFEST).exists()


def test_admission_preserves_old_evidence_and_claim(pair):
    receipt = pair.directory / link.MANIFEST
    before = receipt.read_bytes(), receipt.stat().st_mtime_ns
    claim = pair.directory / 'ap-admission.claim'
    claim.write_bytes(b'parent owns this lease\n')
    claim.chmod(0o600)
    claim_before = claim.read_bytes(), link._identity(claim.stat()), claim.stat().st_mtime_ns
    assert link.admit(pair.directory, pair.binary) == pair.manifest
    assert link.admit_ap(pair.directory, pair.binary, 24576, ap_environment(pair.directory)) == pair.manifest
    assert (receipt.read_bytes(), receipt.stat().st_mtime_ns) == before
    assert (claim.read_bytes(), link._identity(claim.stat()), claim.stat().st_mtime_ns) == claim_before
    with pytest.raises(ValueError):
        link.prepare(pair.directory, pair.binary)
    assert (receipt.read_bytes(), receipt.stat().st_mtime_ns) == before
    assert (claim.read_bytes(), link._identity(claim.stat()), claim.stat().st_mtime_ns) == claim_before


def test_dynamic_ram_content_is_mutable(pair):
    ram = pair.directory / 'ap-ram.bin'
    with ram.open('r+b') as stream:
        stream.seek(15 * 1024 ** 3 + 128)
        stream.write(b'AP/CP live state')
    assert link.admit(pair.directory, pair.binary) == pair.manifest


@pytest.mark.parametrize('side,sandbox', [('ap', False), ('cp', False), ('ap', True), ('cp', True)])
def test_json_objects_express_paths_and_role_offsets(inputs, side, sandbox):
    inputs.directory = inputs.directory.with_name('pair,with:comma"quote\\unicode-雪')
    link.prepare(inputs.directory, inputs.binary)
    arguments = link.ram_arguments(inputs.directory, side, sandbox=sandbox)
    assert len(arguments) == 6 and arguments[::2] == ['-object'] * 3
    assert not any(argument in ('-M', '-machine') for argument in arguments)
    objects = {value['id']: value for value in map(json.loads, arguments[1::2])}
    root = Path('/native-link') if sandbox else inputs.directory
    local = objects['native-local-ram']
    peer = objects['native-peer-ram']
    if side == 'ap':
        assert (local['mem-path'], local['size'], local['offset']) == (str(root / 'ap-ram.bin'), 25769803776, 0)
        assert (peer['mem-path'], peer['size'], peer['offset']) == (str(root / 'cp-ram.bin'), 134217728, 0)
        oom = objects['native-peer-oom']
    else:
        assert (local['mem-path'], local['size'], local['offset']) == (str(root / 'cp-ram.bin'), 134217728, 0)
        assert (peer['mem-path'], peer['size'], peer['offset']) == (str(root / 'ap-ram.bin'), 8589934592, 16106127360)
        oom = objects['native-local-oom']
    assert (oom['mem-path'], oom['size'], oom['offset']) == (str(root / 'cp-oom.bin'), 0x101000, 0)
    for value in objects.values():
        assert value['qom-type'] == 'memory-backend-file'
        assert value['share'] is True and value['discard-data'] is False


def test_environment_exact_roles(pair):
    common = dict(QEMU_NATIVE_AP_CP_LINK=link.PROFILE, QEMU_NATIVE_LINK_DIR=str(pair.directory),
                  QEMU_AP_CP_GPIO_LINES='virtual-ap-cp-gpio-lines-v1')
    assert link.environment('ap', pair.directory) == dict(common, QEMU_AP_CP_GPIO_SIDE='ap',
                                                       QEMU_SONY_TIMERS='1', QEMU_SONY_PCIDMA='1')
    assert link.environment('cp', pair.directory) == dict(common, QEMU_AP_CP_GPIO_SIDE='cp',
        QEMU_CP_GIC='1', QEMU_CP_TIMERS='1', QEMU_CP_WATCHDOG='1', QEMU_CP_EDMA_GATE='1', QEMU_CP_UIPC_RAM='1',
        QEMU_CP_BOOT_PERIPHERALS='virtual-cp-boot-peripherals-v1',
        QEMU_CP_KEY_GPIO_PROFILE='virtual-cp-key-gpio-v1')
    for side in ('AP', '', 'both', None):
        with pytest.raises(ValueError):
            link.environment(side, pair.directory)
        with pytest.raises(ValueError):
            link.ram_arguments(pair.directory, side)
    with pytest.raises(ValueError):
        link.ram_arguments(pair.directory, 'ap', sandbox='1')


@pytest.mark.parametrize('kind', ['short', 'unknown', 'invalid'])
def test_unknown_or_insufficient_space_preserves_failed_root(inputs, monkeypatch, kind):
    required = sum(link.FILE_SIZES.values()) + link.LOG_BUDGET + link.RESERVE

    def space(fd):
        if kind == 'unknown':
            raise OSError('space unavailable')
        return SimpleNamespace(f_bavail=required - 1, f_frsize=1 if kind == 'short' else 0)

    monkeypatch.setattr(link.os, 'fstatvfs', space)
    with pytest.raises(ValueError, match='space'):
        link.prepare(inputs.directory, inputs.binary)
    failure = json.loads((inputs.directory / link.FAILURE_MANIFEST).read_bytes())
    assert failure['status'] == 'failed'
    assert failure['storage']['fits'] is (False if kind == 'short' else None)
    assert not failure['partial_files_retained']
    assert not inputs.calls
    assert not any((inputs.directory / name).exists() for name in link.FILE_SIZES)
    original = (inputs.directory / link.FAILURE_MANIFEST).read_bytes()
    with pytest.raises(ValueError):
        link.prepare(inputs.directory, inputs.binary)
    assert (inputs.directory / link.FAILURE_MANIFEST).read_bytes() == original
    with pytest.raises(ValueError):
        link.admit(inputs.directory, inputs.binary)


def test_exact_worst_case_space_is_accepted(inputs, monkeypatch):
    required = sum(link.FILE_SIZES.values()) + link.LOG_BUDGET + link.RESERVE
    monkeypatch.setattr(link.os, 'fstatvfs', lambda fd: SimpleNamespace(f_bavail=required, f_frsize=1))
    assert link.prepare(inputs.directory, inputs.binary)['storage']['fits'] is True


def test_partial_ftruncate_failure_is_retained_with_identity(inputs, monkeypatch):
    original = link.os.ftruncate
    calls = []

    def fail_second(fd, size):
        calls.append(size)
        if len(calls) == 2:
            raise OSError('controlled ftruncate failure')
        return original(fd, size)

    monkeypatch.setattr(link.os, 'ftruncate', fail_second)
    with pytest.raises(ValueError, match='partial|retained'):
        link.prepare(inputs.directory, inputs.binary)
    failure = json.loads((inputs.directory / link.FAILURE_MANIFEST).read_bytes())
    assert failure['status'] == 'failed' and 'controlled ftruncate' in failure['error']
    assert (inputs.directory / 'ap-ram.bin').stat().st_size == 24 * 1024 ** 3
    assert (inputs.directory / 'cp-ram.bin').stat().st_size == 0
    assert not (inputs.directory / 'cp-oom.bin').exists()
    assert set(failure['partial_files_retained']) == {'ap-ram.bin', 'cp-ram.bin'}
    for name, value in failure['partial_files_retained'].items():
        current = (inputs.directory / name).stat()
        assert (value['dev'], value['ino'], value['size'], value['mode'], value['uid'], value['nlink']) == (
            current.st_dev, current.st_ino, current.st_size, stat.S_IFREG | 0o600, os.geteuid(), 1)
    with pytest.raises(ValueError, match='failure manifest'):
        link.admit(inputs.directory, inputs.binary)


def test_exclusive_no_follow_creation_flags(pair):
    required = os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW
    assert link.CREATE_FLAGS & required == required
    assert link.READ_FLAGS & os.O_NOFOLLOW and link.DIR_FLAGS & os.O_NOFOLLOW
    target = pair.directory / 'cp-ram.bin'
    before = link._identity(target.stat())
    with link._directory(pair.directory) as fd:
        with pytest.raises(FileExistsError):
            link._new_file(fd, target.name)
    assert link._identity(target.stat()) == before


@pytest.mark.parametrize('target', ['file', 'root', 'parent', 'binary', 'binary-parent', 'stage-parent', 'manifest'])
def test_symlinks_are_refused_without_following(pair, tmp_path, target):
    if target in ('root', 'parent'):
        alias = tmp_path / 'alias'
        alias.symlink_to(pair.directory if target == 'root' else tmp_path, target_is_directory=True)
        candidate = alias if target == 'root' else alias / pair.directory.name
        with pytest.raises(ValueError):
            link.admit(candidate, pair.binary)
        with pytest.raises(ValueError):
            link.ram_arguments(candidate, 'ap')
        with pytest.raises(ValueError):
            link.prepare(alias / 'new-pair', pair.binary)
        assert not (pair.directory / 'new-pair').exists()
        assert not (tmp_path / 'new-pair').exists()
        return
    if target == 'binary-parent':
        alias = tmp_path / 'alias-build'
        alias.symlink_to(pair.build, target_is_directory=True)
        with pytest.raises(ValueError):
            link.admit(pair.directory, alias / pair.binary.name)
        return
    if target == 'stage-parent':
        original = pair.tree / 'hw'
        original.rename(pair.tree / 'hw-retained')
        original.symlink_to(pair.tree / 'hw-retained', target_is_directory=True)
    else:
        original = (pair.binary if target == 'binary' else pair.directory / (
            link.MANIFEST if target == 'manifest' else 'cp-ram.bin'))
        retained = original.with_name(original.name + '.retained')
        original.rename(retained)
        original.symlink_to(retained)
    with pytest.raises(ValueError):
        link.admit(pair.directory, pair.binary)


@pytest.mark.parametrize('target', ['cp-ram.bin', 'native-link.json', 'binary'])
def test_hardlinks_are_refused(pair, tmp_path, target):
    original = pair.binary if target == 'binary' else pair.directory / target
    os.link(original, tmp_path / 'extra-hardlink')
    assert original.stat().st_nlink == 2
    with pytest.raises(ValueError, match='hard link'):
        link.admit(pair.directory, pair.binary)


def test_ap_and_cp_local_ram_cannot_share_inode(pair):
    cp = pair.directory / 'cp-ram.bin'
    cp.rename(pair.directory / 'cp-ram.retained')
    os.link(pair.directory / 'ap-ram.bin', cp)
    assert cp.stat().st_ino == (pair.directory / 'ap-ram.bin').stat().st_ino
    with pytest.raises(ValueError):
        link.admit(pair.directory, pair.binary)


@pytest.mark.parametrize('kind', ['replacement', 'size', 'mode', 'root-mode', 'root-replacement', 'owner'])
def test_file_and_root_identity_drift(pair, monkeypatch, kind):
    cp = pair.directory / 'cp-ram.bin'
    if kind == 'replacement':
        cp.rename(pair.directory / 'cp-ram.retained')
        with cp.open('xb') as stream:
            stream.truncate(128 * 1024 ** 2)
        cp.chmod(0o600)
    elif kind == 'size':
        with cp.open('r+b') as stream:
            stream.truncate(128 * 1024 ** 2 - 1)
    elif kind == 'mode':
        cp.chmod(0o644)
    elif kind == 'root-mode':
        pair.directory.chmod(0o755)
    elif kind == 'root-replacement':
        pair.directory.rename(pair.directory.with_name('original-retained'))
        pair.directory.mkdir(mode=0o700)
        path = pair.directory / link.MANIFEST
        path.write_bytes((pair.directory.with_name('original-retained') / link.MANIFEST).read_bytes())
        path.chmod(0o600)
    else:
        uid = os.geteuid()
        monkeypatch.setattr(link.os, 'geteuid', lambda: uid + 1)
    with pytest.raises(ValueError):
        link.admit(pair.directory, pair.binary)


@pytest.mark.parametrize('kind', ['fifo', 'directory', 'socket'])
def test_nonregular_ram_is_refused_without_blocking(pair, kind):
    import socket
    cp = pair.directory / 'cp-ram.bin'
    cp.rename(pair.directory / 'cp-ram.retained')
    endpoint = None
    directory_fd = None
    try:
        if kind == 'fifo':
            os.mkfifo(cp, 0o600)
        elif kind == 'directory':
            cp.mkdir(mode=0o700)
        else:
            endpoint = socket.socket(socket.AF_UNIX)
            directory_fd = os.open(pair.directory, os.O_RDONLY | os.O_DIRECTORY)
            endpoint.bind('/proc/self/fd/' + str(directory_fd) + '/cp-ram.bin')
        with pytest.raises(ValueError, match='S_IFREG'):
            link.admit(pair.directory, pair.binary)
    finally:
        if endpoint is not None:
            endpoint.close()
        if directory_fd is not None:
            os.close(directory_fd)


@pytest.mark.parametrize('name', ['/dev/mem', '../outside', 'sub/../ap-ram.bin', '/absolute/file'])
def test_manifest_never_selects_arbitrary_paths(pair, name):
    rewrite_manifest(pair.directory, lambda value: value['files'].__setitem__(name, value['files'].pop('ap-ram.bin')))
    before = (pair.directory / link.MANIFEST).read_bytes()
    with pytest.raises(ValueError, match='fixed basenames'):
        link.admit(pair.directory, pair.binary)
    assert (pair.directory / link.MANIFEST).read_bytes() == before


@pytest.mark.parametrize('kind', ['profile', 'status', 'forged-inode', 'hardware', 'duplicate-key'])
def test_manifest_profile_identity_and_truthfulness(pair, kind):
    if kind == 'duplicate-key':
        path = pair.directory / link.MANIFEST
        raw = path.read_text()
        path.write_text(raw.replace('"profile":', '"profile":"old-profile", "profile":', 1))
    else:
        def change(value):
            if kind == 'profile':
                value['profile'] = 'virtual-shared-test-peer-v0'
            elif kind == 'status':
                value['status'] = 'failed'
            elif kind == 'forged-inode':
                value['files']['cp-ram.bin']['ino'] = value['files']['ap-ram.bin']['ino']
            else:
                value['original_ap_consumed'] = True
        rewrite_manifest(pair.directory, change)
    with pytest.raises(ValueError):
        link.admit(pair.directory, pair.binary)


@pytest.mark.parametrize('path', ['relative/pair', '/dev/mem', '/proc/self/fd/0', '/sys/block', '/a/../b', '//host/pair'])
def test_noncanonical_and_device_paths_are_refused(inputs, path):
    with pytest.raises(ValueError):
        link.prepare(path, inputs.binary)
    with pytest.raises(ValueError):
        link.admit(path, inputs.binary)


def test_binary_path_mismatch_is_refused_without_hashing_ram(pair, monkeypatch):
    def never_hash(path):
        raise AssertionError('Wrong binary path must be rejected before full SHA')

    monkeypatch.setattr(link, '_digest', never_hash)
    with pytest.raises(ValueError, match='binary path'):
        link.admit(pair.directory, pair.directory / 'ap-ram.bin')


def test_full_binary_sha_includes_bytes_past_first_megabyte(inputs):
    payload = b'x' * (2 * 1024 ** 2) + b'first-last-byte'
    inputs.binary.write_bytes(payload)
    proof_path = inputs.build / 'cp-notify-build.json'
    proof = json.loads(proof_path.read_bytes())
    proof['binary_sha256'] = sha(payload)
    write_json(proof_path, proof)
    manifest = link.prepare(inputs.directory, inputs.binary)
    assert manifest['binary']['sha256'] == sha(payload)
    with inputs.binary.open('r+b') as stream:
        stream.seek(-1, os.SEEK_END)
        stream.write(b'!')
    assert inputs.binary.stat().st_size == len(payload)
    with pytest.raises(ValueError, match='binary|Binary'):
        link.admit(inputs.directory, inputs.binary)


def test_same_content_binary_replacement_is_identity_drift(pair):
    retained = pair.binary.with_name('original-binary-retained')
    pair.binary.rename(retained)
    pair.binary.write_bytes(retained.read_bytes())
    pair.binary.chmod(0o755)
    assert sha(pair.binary.read_bytes()) == pair.manifest['binary']['sha256']
    with pytest.raises(ValueError, match='binary/full stage identity'):
        link.admit(pair.directory, pair.binary)


def test_failed_final_readback_blocks_success_looking_manifest(inputs, monkeypatch):
    original = link._load

    def reject_readback(fd, directory):
        raise ValueError('controlled final readback failure')

    monkeypatch.setattr(link, '_load', reject_readback)
    with pytest.raises(ValueError, match='readback failure'):
        link.prepare(inputs.directory, inputs.binary)
    assert json.loads((inputs.directory / link.MANIFEST).read_bytes())['status'] == 'prepared'
    assert json.loads((inputs.directory / link.FAILURE_MANIFEST).read_bytes())['status'] == 'failed'
    monkeypatch.setattr(link, '_load', original)
    with pytest.raises(ValueError, match='failure manifest'):
        link.admit(inputs.directory, inputs.binary)


def test_stage_receipt_drift_and_no_legacy_stage_promotion(pair):
    child_path = pair.tree / 'cp-peripherals-stage.json'
    child = json.loads(child_path.read_bytes())
    child['additional_identity_field'] = 'changed'
    write_json(child_path, child)
    proof_path = pair.build / 'cp-notify-build.json'
    proof = json.loads(proof_path.read_bytes())
    proof['peripherals_stage_sha256'] = sha(child_path.read_bytes())
    write_json(proof_path, proof)
    with pytest.raises(ValueError, match='full stage'):
        link.admit(pair.directory, pair.binary)
    child['native_link_profile'] = 'virtual-test-peer-v0'
    write_json(child_path, child)
    proof['peripherals_stage_sha256'] = sha(child_path.read_bytes())
    write_json(proof_path, proof)
    with pytest.raises(ValueError, match='native link profile'):
        link.admit(pair.directory, pair.binary)


@pytest.mark.parametrize('name', ['../outside.c', '/absolute.c', 'hw/../board.c', 'hw//board.c'])
def test_stage_source_path_traversal_is_refused_before_contract(inputs, name):
    child_path = inputs.tree / 'cp-peripherals-stage.json'
    child = json.loads(child_path.read_bytes())
    child['outputs'] = {name: sha(b'unsafe')}
    write_json(child_path, child)
    proof_path = inputs.build / 'cp-notify-build.json'
    proof = json.loads(proof_path.read_bytes())
    proof['peripherals_stage_sha256'] = sha(child_path.read_bytes())
    write_json(proof_path, proof)
    with pytest.raises(ValueError, match='Unsafe stage'):
        link.prepare(inputs.directory, inputs.binary)
    assert not inputs.calls
    assert (inputs.directory / link.FAILURE_MANIFEST).exists()


def test_source_drift_and_contract_refusal_are_value_errors(pair, monkeypatch):
    original = pair.source.read_bytes()
    pair.source.write_bytes(b'changed source\n')
    with pytest.raises(ValueError, match='Stage source identity'):
        link.admit(pair.directory, pair.binary)
    pair.source.write_bytes(original)

    def refused(binary, require_peripherals=False):
        assert require_peripherals is True
        raise KeyError('missing complete peripheral contract')

    monkeypatch.setattr(link.runpy, 'run_path', lambda path: {'contract': refused})
    with pytest.raises(ValueError, match='complete peripheral'):
        link.admit(pair.directory, pair.binary)


@pytest.mark.parametrize('memory', [0, 128, 8192, 24575, 24577, '24576', True, None])
def test_ap_requires_exact_memory(pair, memory):
    with pytest.raises(ValueError, match='24576'):
        link.admit_ap(pair.directory, pair.binary, memory, ap_environment(pair.directory))


@pytest.mark.parametrize('name,value', [
    ('QEMU_NATIVE_AP_CP_LINK', 'virtual-ap-cp-gpio-lines-v1'), ('QEMU_NATIVE_LINK_DIR', '/different/pair'),
    ('QEMU_AP_CP_GPIO_LINES', 'old-profile'), ('QEMU_AP_CP_GPIO_SIDE', 'cp'),
    ('QEMU_SONY_TIMERS', '0'), ('QEMU_SONY_PCIDMA', '0'), ('QEMU_UI_LIVE', '0'), ('QEMU_TIMEOUT_SECONDS', '15'),
    ('QEMU_RAM_SESSION', '1'), ('QEMU_RAM_INCOMING', 'defer'), ('QEMU_RAM_IMAGE', '0'),
    ('QEMU_WBI_RESUME', '1'), ('QEMU_WBI_RAM', '/old/ram'), ('QEMU_USB_DEVICE', '1'), ('QEMU_SONY_USB_DEVICE', '1'),
    ('QEMU_SONY_USB_BACKEND_SOCKET', '/host/socket'), ('A7C2_HOST_SD', '/dev/sdb'), ('A7C2_DIRECTORY_SD', '/host/photos'),
    ('QEMU_HOST_SD_DEVICE', '/dev/sdb'), ('QEMU_DIRECTORY_SD', '/host/photos'), ('QEMU_SD_IMAGE', '/host/card'),
    ('QEMU_ORIGINAL_RAM', '/old/ram'), ('A7C2_ORIGINAL_RAM', '/old/ram'), ('QEMU_INCOMING', 'defer'),
    ('QEMU_LOADVM', 'old-snapshot'), ('QEMU_MIGRATION_URI', 'file:old'),
    ('MENU_VIRTUAL_CP_SENDER', '1'), ('MENU_VPANEL', '1'), ('MENU_CP_EMULATION', '1'), ('A7C2_CP_EMULATION', '1'),
    ('MENU_TRANSPORT_ERRORS', '1'), ('MENU_EXTRA_ARGS', '--transport-errors'), ('MENU_BB_READY_INJECT', '1'),
    ('QEMU_CP_GIC', '1'), ('QEMU_CP_EDMA_DIRECT', '0'), ('QEMU_CP_GPIO18_PROFILE', ''),
    ('QEMU_SONY_ATU_TEST', ''), ('QEMU_SONY_PCIDMA_TEST', '0'), ('QEMU_SONY_PCIE_PEER_TEST', '1'),
    ('QEMU_NEW_TEST_PEER', '0'), ('QEMU_DIRECT_DMA', '0'),
    ('QEMU_NATIVE_P1_SPI_COMPONENT', 'wrong'),
])
def test_ap_refuses_env_conflicts_and_keeps_manifest(pair, name, value):
    env = ap_environment(pair.directory)
    env[name] = value
    receipt = pair.directory / link.MANIFEST
    original = receipt.read_bytes(), receipt.stat().st_mtime_ns
    with pytest.raises(ValueError):
        link.admit_ap(pair.directory, pair.binary, 24576, env)
    assert (receipt.read_bytes(), receipt.stat().st_mtime_ns) == original
    assert not (pair.directory / 'ap-admission.claim').exists()


def test_admit_ap_uses_supplied_or_current_environment(pair, monkeypatch):
    env = ap_environment(pair.directory)
    monkeypatch.setattr(link.os, 'environ', env)
    assert link.admit_ap(pair.directory, pair.binary, 24576) == pair.manifest
    assert link.admit_ap(pair.directory, pair.binary, 24576, dict(env)) == pair.manifest
    assert link.admit_ap(pair.directory, pair.binary, 24576,
                         dict(env, QEMU_NATIVE_P1_SPI_COMPONENT='virtual-p1-pl022-component-v1')) == pair.manifest
    with pytest.raises(ValueError):
        link.admit_ap(pair.directory, pair.binary, 24576, {})
    with pytest.raises(ValueError):
        link.admit_ap(pair.directory, pair.binary, 24576, dict(env, QEMU_UI_LIVE=1))


def test_harmless_environment_path_text_is_not_a_transport_option(inputs):
    inputs.directory = inputs.directory.with_name('pair,transport-errors-text')
    manifest = link.prepare(inputs.directory, inputs.binary)
    env = dict(ap_environment(inputs.directory), PATH='/example/transport-errors/bin')
    assert link.admit_ap(inputs.directory, inputs.binary, 24576, env) == manifest



def test_cli_prepare_and_admit_ap_json_only(inputs, monkeypatch, capsys):
    assert link.main(['prepare', str(inputs.directory), '--binary', str(inputs.binary)]) == 0
    stdout = capsys.readouterr()
    assert not stdout.err and json.loads(stdout.out)['status'] == 'prepared'
    monkeypatch.setattr(link.os, 'environ', ap_environment(inputs.directory))
    assert link.main(['admit-ap', str(inputs.directory), '--binary', str(inputs.binary), '--memory-mib', '24576']) == 0
    stdout = capsys.readouterr()
    assert not stdout.err and json.loads(stdout.out)['profile'] == link.PROFILE
    assert link.main(['admit-ap', str(inputs.directory), '--binary', str(inputs.binary), '--memory-mib', '128']) == 2
    stderr = capsys.readouterr()
    assert not stderr.out and json.loads(stderr.err)['admitted'] is False


def test_ap_claim_binds_generation_nonce_and_is_not_replayable(pair):
    command=link.ap_probe_command()
    claim,claim_sha=link.create_ap_admission_claim(pair.directory,pair.binary,command)
    loaded,loaded_sha=link.read_ap_admission_claim(pair.directory)
    assert loaded==claim and loaded_sha==claim_sha
    assert claim['schema']=='a7c2-native-ap-admission-v2'
    assert claim['owner_pid']==os.getpid() and claim['owner_start_ticks']==link._proc_record(os.getpid())['start_ticks']
    assert claim['host_boot_id']==link._boot_id() and claim['command']==command
    assert len(claim['run_nonce'])==32 and claim['pair_admission']==pair.manifest
    with pytest.raises(FileExistsError):link.create_ap_admission_claim(pair.directory,pair.binary,command)
    assert link.read_ap_admission_claim(pair.directory)==(claim,claim_sha)


def test_ap_claim_validator_rejects_reused_pid_generation(pair,monkeypatch):
    command=link.ap_probe_command()
    claim,claim_sha=link.create_ap_admission_claim(pair.directory,pair.binary,command)
    monkeypatch.setattr(link,'_proc_record',lambda pid,proc_root=Path('/proc'):
        dict(start_ticks=claim['owner_start_ticks'],command_sha256=claim['command_sha256']))
    assert link.validate_ap_admission_claim(pair.directory,pair.binary,pair.manifest,claim)==(claim,claim_sha)
    monkeypatch.setattr(link,'_proc_record',lambda pid,proc_root=Path('/proc'):
        dict(start_ticks='reused-pid',command_sha256=claim['command_sha256']))
    with pytest.raises(ValueError,match='owner generation'):
        link.validate_ap_admission_claim(pair.directory,pair.binary,pair.manifest,claim)


def test_ap_run_pointer_and_control_lock_are_exclusive(pair):
    run=pair.directory/'ap-runs'/'run-fixture'
    run.mkdir(parents=True,mode=0o700)
    link.write_ap_run_pointer(pair.directory,run)
    assert (pair.directory/'latest-ap-run.txt').read_bytes()==(str(run)+'\n').encode()
    fd,identity=link.create_ap_control_lock(run)
    try:
        assert identity['size']==0 and identity['mode']==stat.S_IFREG|0o600 and identity['nlink']==1
        with pytest.raises(FileExistsError):link.create_ap_control_lock(run)
    finally:os.close(fd)


def test_ap_control_quit_transaction_holds_and_releases_lock(tmp_path):
    run=tmp_path/'ap-run';run.mkdir(mode=0o700)
    control,_=link.create_ap_control_lock(run)
    peer=os.open(run/'ap-cp-control.lock',os.O_RDWR)
    events=[]
    def action():
        events.append('marker')
        with pytest.raises(BlockingIOError):fcntl.flock(peer,fcntl.LOCK_EX|fcntl.LOCK_NB)
        events.append('qmp-quit')
        return 'reply'
    try:
        assert link.with_ap_control_lock(control,action)=='reply'
        assert events==['marker','qmp-quit']
        fcntl.flock(peer,fcntl.LOCK_EX|fcntl.LOCK_NB);fcntl.flock(peer,fcntl.LOCK_UN)
        with pytest.raises(RuntimeError,match='synthetic'):
            link.with_ap_control_lock(control,lambda:(_ for _ in ()).throw(RuntimeError('synthetic')))
        fcntl.flock(peer,fcntl.LOCK_EX|fcntl.LOCK_NB);fcntl.flock(peer,fcntl.LOCK_UN)
    finally:
        os.close(peer);os.close(control)


@pytest.mark.parametrize('socket_mode',[stat.S_IFSOCK|0o600,stat.S_IFREG|0o600])
def test_ap_qmp_owner_record_binds_peer_binary_and_lock(pair,monkeypatch,socket_mode):
    command=link.ap_probe_command()
    claim,claim_sha=link.create_ap_admission_claim(pair.directory,pair.binary,command)
    run=pair.directory/'ap-runs'/'run-owner-test'
    run.mkdir(parents=True,mode=0o700)
    link.write_ap_run_pointer(pair.directory,run)
    lock_fd,_=link.create_ap_control_lock(run)
    binary=pair.binary.stat();peer_pid=os.getpid()+1000000
    owner=dict(pid=os.getpid(),start_ticks=claim['owner_start_ticks'],state='S',uid=os.getuid(),gid=os.getgid(),
               command_sha256=claim['command_sha256'],exe_path=str(pair.binary),exe_dev=binary.st_dev,
               exe_ino=binary.st_ino,exe_size=binary.st_size,exe_mode=binary.st_mode)
    peer=dict(pid=peer_pid,start_ticks='777',state='S',uid=os.getuid(),gid=os.getgid(),command_sha256='c'*64,
              exe_path=str(pair.binary),exe_dev=binary.st_dev,exe_ino=binary.st_ino,
              exe_size=binary.st_size,exe_mode=binary.st_mode)
    monkeypatch.setattr(link,'_proc_record',lambda pid,proc_root=Path('/proc'):owner if pid==os.getpid() else peer)
    original_stat=link.os.stat
    def fake_stat(path,*args,**kwargs):
        if path=='qmp.sock' and kwargs.get('dir_fd') is not None:
            return SimpleNamespace(st_mode=socket_mode,st_uid=os.getuid(),st_dev=41,st_ino=42)
        return original_stat(path,*args,**kwargs)
    monkeypatch.setattr(link.os,'stat',fake_stat)
    try:
        if stat.S_ISSOCK(socket_mode):
            record,record_sha=link.bind_ap_vm_owner(pair.directory,run,pair.binary,pair.manifest,
                claim,claim_sha,peer_pid,os.getuid(),os.getgid(),lock_fd)
            loaded=json.loads((run/'native-ap-vm.json').read_bytes())
            assert loaded==record and loaded['ready'] is True
            assert loaded['qemu_pid']==peer_pid and loaded['run_nonce']==claim['run_nonce']
            assert loaded['qmp_peer']['ino']==42 and loaded['claim_sha256']==claim_sha
            assert record_sha==link._digest(run/'native-ap-vm.json')['sha256']
        else:
            with pytest.raises(ValueError,match='QMP socket'):
                link.bind_ap_vm_owner(pair.directory,run,pair.binary,pair.manifest,
                    claim,claim_sha,peer_pid,os.getuid(),os.getgid(),lock_fd)
            assert not (run/'native-ap-vm.json').exists()
    finally:os.close(lock_fd)
