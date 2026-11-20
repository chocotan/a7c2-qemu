"""Small offline fixtures; no QEMU, physical devices, formatter, or fsck execution.

Intentionally not run as part of the delegated implementation. Production-size
I/O and the installed fsck must be checked by the owning integration task.
"""
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import stat
import struct
from types import SimpleNamespace

import pytest

import functional_ram_initramfs as ram


class FakeFsck:
    """Small pipe-backed test double; no subprocess or filesystem tool executes."""
    def __init__(self, *, returncode=0, stdout=b'', stderr=b''):
        self.pid = 12345
        self.returncode = returncode
        self.waited = False
        for name, raw in (('stdout', stdout), ('stderr', stderr)):
            assert len(raw) <= 4096
            read, write = os.pipe()
            with os.fdopen(write, 'wb') as stream:
                stream.write(raw)
            setattr(self, name, os.fdopen(read, 'rb'))

    def wait(self):
        assert not self.stdout.closed and not self.stderr.closed
        self.waited = True
        return self.returncode

    def poll(self):
        return self.returncode

    def kill(self):
        pytest.fail('fsck must never be killed')

    def terminate(self):
        pytest.fail('fsck must never be terminated')

    def send_signal(self, signal):
        pytest.fail('fsck must never receive a signal')


def record(name, data=b'', mode=stat.S_IFREG | 0o644, *, links=1, inode=1):
    name = ('./' + name).encode() + b'\0'
    fields = (inode, mode, 0, 0, links, 0, len(data), 0, 0, 0, 0, len(name), 0)
    raw = b'070701' + ''.join(f'{v:08x}' for v in fields).encode() + name
    raw += b'\0' * (-len(raw) % 4)
    raw += data + b'\0' * (-len(data) % 4)
    return raw


def archive(*extra):
    return (record('.', mode=stat.S_IFDIR | 0o755) +
            record('simulation', mode=stat.S_IFDIR | 0o755, inode=2) +
            record('keep', b'unchanged firmware bytes', inode=3) + b''.join(extra) +
            record('TRAILER!!!'))


def fat_image(size):
    raw = bytearray(size)
    struct.pack_into('<H', raw, 11, 512)
    raw[13] = 1
    struct.pack_into('<H', raw, 14, 1)
    raw[16] = 2
    struct.pack_into('<H', raw, 17, 512)
    raw[21] = 0xf8
    struct.pack_into('<H', raw, 22, 32)
    struct.pack_into('<I', raw, 32, size // 512)
    raw[54:62] = b'FAT16   '
    raw[510:512] = b'\x55\xaa'
    return raw


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.fixture
def system_tree(tmp_path, monkeypatch):
    """Redirect the fixed absolute system root to owned synthetic files; never exec."""
    root = tmp_path / 'system'
    binary = root / 'usr/bin/fsck.fat'
    binary.parent.mkdir(parents=True)
    binary.write_bytes(b'synthetic full executable contents')
    binary.chmod(0o755)
    original_open, original_stat, original_fstat = os.open, os.stat, os.fstat
    owners = {}

    def root_owned(st):
        values = {name: getattr(st, name) for name in dir(st) if name.startswith('st_')}
        values['st_uid'] = owners.get((st.st_dev, st.st_ino), 0)
        return SimpleNamespace(**values)

    def opened(path, flags, mode=0o777, *, dir_fd=None):
        assert flags & os.O_NOFOLLOW and flags & os.O_CLOEXEC
        return original_open(root if path == '/' else path, flags, mode, dir_fd=dir_fd)

    def stated(path, **kwargs):
        return root_owned(original_stat(root if path == '/' else path, **kwargs))

    monkeypatch.setattr(ram.os, 'open', opened)
    monkeypatch.setattr(ram.os, 'stat', stated)
    monkeypatch.setattr(ram.os, 'fstat', lambda fd: root_owned(original_fstat(fd)))
    return SimpleNamespace(root=root, binary=binary, owners=owners)


def test_system_fsck_pins_full_hash_and_inode(system_tree):
    proof = {}
    with ram.system_fsck(proof) as fd:
        assert os.pread(fd, 4096, 0) == system_tree.binary.read_bytes()
        assert proof['path'] == '/usr/bin/fsck.fat'
        assert proof['identity']['uid'] == 0
        assert proof['sha256'] == sha(system_tree.binary)
    assert proof['after_sha256'] == proof['sha256']
    with pytest.raises(OSError):
        os.fstat(fd)


@pytest.mark.parametrize('kind', ['directory-writable', 'file-writable', 'foreign-owner',
                                 'symlink', 'not-executable', 'fifo', 'missing'])
def test_system_fsck_rejects_unsafe_or_missing_tools(system_tree, kind):
    binary = system_tree.binary
    if kind == 'directory-writable':
        binary.parent.chmod(0o775)
    elif kind == 'file-writable':
        binary.chmod(0o777)
    elif kind == 'foreign-owner':
        st = binary.stat()
        system_tree.owners[st.st_dev, st.st_ino] = 1001
    elif kind == 'not-executable':
        binary.chmod(0o644)
    else:
        binary.unlink()
        if kind == 'symlink':
            binary.symlink_to('another-fsck')
        elif kind == 'fifo':
            os.mkfifo(binary)
    with pytest.raises((ValueError, OSError)):
        with ram.system_fsck({}):
            pytest.fail('unsafe or missing tool was accepted')


@pytest.mark.parametrize('change', ['bytes', 'inode', 'mode'])
def test_system_fsck_detects_postexecution_changes(system_tree, change):
    proof = {}
    with pytest.raises(ValueError, match='System fsck'):
        with ram.system_fsck(proof):
            binary = system_tree.binary
            if change == 'bytes':
                binary.write_bytes(b'changed full executable contents')
            elif change == 'inode':
                raw = binary.read_bytes()
                binary.rename(binary.with_name('original'))
                binary.write_bytes(raw)
                binary.chmod(0o755)
            else:
                binary.chmod(0o700)


def test_system_fsck_preserves_first_error_when_posthash_also_fails(system_tree):
    original = OSError('original child failure')
    proof = {}
    with pytest.raises(OSError) as caught:
        with ram.system_fsck(proof):
            system_tree.binary.write_bytes(b'changed executable')
            raise original
    assert caught.value is original
    assert 'full SHA256 changed' in proof['verification_error']


@pytest.fixture
def inputs(tmp_path, monkeypatch):
    # This bypass exists only in synthetic tests; production has no env/CLI unlock.
    monkeypatch.setattr(ram, '_FSCK_EXECUTION_BLOCKED', None)
    # Fine-grained stream failures stay in-process; real recovery is tested separately.
    monkeypatch.setattr(ram, 'fsck_readonly', ram._fsck_owned_body)
    monkeypatch.setattr(ram, 'PROJECT', tmp_path)
    monkeypatch.setattr(ram, 'SEED_BYTES', 4 * 1024**2)
    executable = tmp_path / 'synthetic-fsck'
    executable.write_bytes(b'synthetic executable; never executed')

    @contextmanager
    def system_fsck(proof):
        fd = os.open(executable, os.O_RDONLY | os.O_NOFOLLOW)
        digest = sha(executable)
        proof.update(path='/usr/bin/fsck.fat', identity=dict(ram.metadata(os.fstat(fd)), uid=0),
                     sha256=digest, after_sha256=digest)
        try:
            yield fd
        finally:
            os.close(fd)

    monkeypatch.setattr(ram, 'system_fsck', system_fsck)
    budgets, calls = [], []
    monkeypatch.setattr(ram, 'check_space', lambda fd, required: budgets.append(required))
    def fsck(command, **kwargs):
        calls.append((command, kwargs))
        seed_fd = int(command[-1].rsplit('/', 1)[1])
        import fcntl
        assert fcntl.fcntl(seed_fd, fcntl.F_GETFL) & os.O_ACCMODE == os.O_RDONLY
        tool_fd = int(command[0].rsplit('/', 1)[1])
        assert command[0].startswith('/proc/self/fd/') and command[1] == '-n'
        assert os.pread(tool_fd, 1024, 0) == executable.read_bytes()
        assert tool_fd in kwargs['pass_fds']
        assert seed_fd in kwargs['pass_fds']
        assert set(kwargs['env']) == {'PATH', 'TMPDIR', 'TMP', 'TEMP', 'LC_ALL'}
        assert kwargs['env']['PATH'] == '/usr/bin:/usr/sbin'
        assert kwargs['stdin'] is ram.subprocess.DEVNULL and kwargs['close_fds'] is True
        tmpfd = int(kwargs['env']['TMPDIR'].rsplit('/', 1)[1])
        assert stat.S_ISDIR(os.fstat(tmpfd).st_mode)
        assert stat.S_IMODE(os.fstat(tmpfd).st_mode) == 0o700
        assert kwargs['env']['TMP'] == kwargs['env']['TEMP'] == kwargs['env']['TMPDIR']
        assert kwargs['stdout'] is kwargs['stderr'] is ram.subprocess.PIPE
        assert 'timeout' not in kwargs
        return FakeFsck(returncode=0, stdout=b'read-only check passed\n', stderr=b'')
    monkeypatch.setattr(ram.subprocess, 'Popen', fsck)
    base, seed = tmp_path / 'base.cpio', tmp_path / 'seed.fat'
    base.write_bytes(archive())
    seed.write_bytes(fat_image(ram.SEED_BYTES))
    return SimpleNamespace(root=tmp_path, base=base, seed=seed, calls=calls, budgets=budgets)


def derive(inputs, output='new', **options):
    args = dict(base_sha256=sha(inputs.base), seed_sha256=sha(inputs.seed), functional_camera=True,
                parallel_peak_bytes=0)
    args.update(options)
    return ram.derive(inputs.base, inputs.seed, inputs.root / output, **args)


def test_production_fsck_gate_uses_reviewed_host_acceptance(monkeypatch):
    monkeypatch.setenv('A7C2_FSCK_EXECUTION_BLOCKED', 'untrusted override')
    assert ram._FSCK_EXECUTION_BLOCKED is None
    monkeypatch.setattr(ram, '_FSCK_EXECUTION_BLOCKED', 'synthetic closed gate')
    monkeypatch.setattr(ram.subprocess, 'Popen', lambda *a, **kw: pytest.fail('must remain blocked'))
    with pytest.raises(ValueError, match='synthetic closed gate'):
        ram.fsck_readonly(-1, -1, -1, {'storage': {}})


def test_fsck_environment_does_not_inherit_loader_or_user_options(inputs, monkeypatch):
    for key in ('LD_PRELOAD', 'LD_LIBRARY_PATH', 'LD_AUDIT', 'FSCK_OPTIONS', 'HOME', 'BASH_ENV'):
        monkeypatch.setenv(key, '/untrusted')
    derive(inputs)
    assert inputs.calls
    assert not set(inputs.calls[0][1]['env']) & {
        'LD_PRELOAD', 'LD_LIBRARY_PATH', 'LD_AUDIT', 'FSCK_OPTIONS', 'HOME', 'BASH_ENV'}


def test_fsck_rejects_writable_seed_before_start(inputs, monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail('writable seed must not reach a child process')
    monkeypatch.setattr(ram.subprocess, 'Popen', forbidden)
    result = {'storage': {}}
    fd = os.open(inputs.seed, os.O_RDWR)
    try:
        with pytest.raises(ValueError, match='pinned read-only regular seed'):
            ram.fsck_readonly(fd, -1, -1, result)
    finally:
        os.close(fd)
    assert result['fsck']['returncode'] is None
    assert 'pid' not in result['fsck']


def test_deployment_boundary_is_product_not_repository_or_root():
    assert ram.PROJECT == Path(ram.__file__).resolve().parents[2]
    assert ram.PROJECT != Path('/')


@pytest.mark.parametrize('external', ['/tmp/seed.fat', '/var/tmp/seed.fat', '/dev/seed.fat',
                                     '/proc/seed.fat', '/sys/seed.fat', '/run/seed.fat'])
def test_all_external_seed_paths_are_refused(inputs, external):
    with pytest.raises(ValueError, match='inside the product'):
        ram.derive(inputs.base, Path(external), inputs.root / 'new',
                   base_sha256=sha(inputs.base), seed_sha256='0' * 64,
                   functional_camera=True, parallel_peak_bytes=0)
    assert not (inputs.root / 'new').exists()
    assert not inputs.calls


def test_output_cannot_leave_product(inputs):
    outside = inputs.root.parent / 'outside-functional-ram-output'
    with pytest.raises(ValueError, match='inside the product'):
        ram.derive(inputs.base, inputs.seed, outside,
                   base_sha256=sha(inputs.base), seed_sha256=sha(inputs.seed),
                   functional_camera=True, parallel_peak_bytes=0)
    assert not outside.exists()
    assert not inputs.calls


def test_output_symlink_ancestor_is_refused(inputs):
    real = inputs.root / 'real-output-parent'
    real.mkdir()
    alias = inputs.root / 'alias-output-parent'
    alias.symlink_to(real, target_is_directory=True)
    with pytest.raises((ValueError, OSError)):
        derive(inputs, output='alias-output-parent/new')
    assert not (real / 'new').exists()
    assert not inputs.calls


def test_root_product_boundary_is_never_allowed(inputs, monkeypatch):
    monkeypatch.setattr(ram, 'PROJECT', Path('/'))
    with pytest.raises(ValueError, match='inside the product'):
        ram.project_path(inputs.seed)


@pytest.mark.parametrize('stream', ['stdout', 'stderr', 'both'])
def test_fsck_logs_are_bounded_and_overflow_waits_for_natural_exit(inputs, monkeypatch, stream):
    monkeypatch.setattr(ram, 'FSCK_LOG_LIMIT', 8)
    stdout = b'0123456789abcdef' if stream in ('stdout', 'both') else b'ok\n'
    stderr = b'fedcba9876543210' if stream in ('stderr', 'both') else b''
    process = FakeFsck(stdout=stdout, stderr=stderr)
    monkeypatch.setattr(ram.subprocess, 'Popen', lambda *a, **kw: process)
    with pytest.raises(ValueError, match='fsck log limit exceeded'):
        derive(inputs)
    assert process.waited
    assert process.stdout.closed and process.stderr.closed
    out = inputs.root / 'new'
    result = json.loads((out / 'derivation.json').read_bytes())
    assert result['ok'] is False
    assert result['fsck']['returncode'] == 0
    assert result['fsck']['log_limit_bytes'] == 8
    assert result['storage']['reserved_fsck_log_bytes'] == 16
    assert result['storage']['fsck_log_bytes'] == min(8, len(stdout)) + min(8, len(stderr))
    for name, raw in (('fsck.stdout', stdout), ('fsck.stderr', stderr)):
        prefix = raw[:8]
        assert (out / name).read_bytes() == prefix
        assert result['fsck'][name] == dict(bytes=len(prefix), observed_bytes=len(raw),
                                            truncated=len(raw) > len(prefix),
                                            sha256=hashlib.sha256(prefix).hexdigest())
    assert not (out / 'functional-ram-initramfs.cpio').exists()
    with pytest.raises(ValueError, match='opt-in derivation binding'):
        ram.verify_for_consumer(result)


@pytest.mark.parametrize('exception_type', [OSError, KeyboardInterrupt])
@pytest.mark.parametrize('stage', ['create', 'register', 'select', 'unregister', 'close'])
def test_fsck_selector_errors_drain_both_pipes_and_keep_original_error(
        inputs, monkeypatch, stage, exception_type):
    original = exception_type('synthetic selector ' + stage)
    selector_factory = ram.selectors.DefaultSelector
    process = FakeFsck(returncode=7, stdout=b'original stdout\n', stderr=b'original stderr\n')
    monkeypatch.setattr(ram.subprocess, 'Popen', lambda *a, **kw: process)

    class BrokenSelector:
        def __init__(self):
            if stage == 'create':
                raise original
            self.actual = selector_factory()

        def register(self, *args):
            if stage == 'register':
                raise original
            return self.actual.register(*args)

        def select(self):
            if stage == 'select':
                raise original
            return self.actual.select()

        def unregister(self, *args):
            if stage == 'unregister':
                raise original
            return self.actual.unregister(*args)

        def close(self):
            self.actual.close()
            if stage == 'close':
                raise original

    monkeypatch.setattr(ram.selectors, 'DefaultSelector', BrokenSelector)
    with pytest.raises(exception_type) as caught:
        derive(inputs)
    assert caught.value is original
    assert process.waited and process.stdout.closed and process.stderr.closed
    assert id(process) not in ram._FSCK_OWNERS
    out = inputs.root / 'new'
    proof = json.loads((out / 'derivation.json').read_bytes())['fsck']
    assert proof['returncode'] == 7
    assert proof['pipes_drained'] and not proof['owner_retained']
    assert proof['errors'][0]['error'] == exception_type.__name__ + ': ' + str(original)
    assert (out / 'fsck.stdout').read_bytes() == b'original stdout\n'
    assert (out / 'fsck.stderr').read_bytes() == b'original stderr\n'


def test_fsck_read_error_uses_single_read_fallback_then_natural_wait(inputs, monkeypatch):
    process = FakeFsck(returncode=3, stdout=b'raw stdout\n', stderr=b'raw stderr\n')
    original = OSError('synthetic raw read failure')
    raw_read = ram.os.read
    failed = False

    def read(fd, size):
        nonlocal failed
        if fd == process.stdout.fileno() and not failed:
            failed = True
            raise original
        return raw_read(fd, size)

    monkeypatch.setattr(ram.os, 'read', read)
    monkeypatch.setattr(ram.subprocess, 'Popen', lambda *a, **kw: process)
    with pytest.raises(OSError) as caught:
        derive(inputs)
    assert caught.value is original
    assert process.waited and process.stdout.closed and process.stderr.closed
    out = inputs.root / 'new'
    proof = json.loads((out / 'derivation.json').read_bytes())['fsck']
    assert proof['returncode'] == 3 and proof['pipes_drained']
    assert proof['errors'][0]['stage'] == 'fsck.stdout.read'
    assert (out / 'fsck.stdout').read_bytes() == b'raw stdout\n'
    assert (out / 'fsck.stderr').read_bytes() == b'raw stderr\n'


def test_fsck_unreadable_pipe_waits_with_owner_until_natural_exit(inputs, monkeypatch):
    process = FakeFsck(stderr=b'other stream survives\n')
    process.stdout.close()
    reader, writer = os.pipe()
    os.write(writer, b'unread original output')
    stream = os.fdopen(reader, 'rb')
    original = OSError('synthetic persistent read failure')
    raw_read = ram.os.read

    class UnreadablePipe:
        closed = False

        def fileno(self):
            return stream.fileno()

        def read1(self, size):
            raise OSError('synthetic fallback read failure')

        def close(self):
            self.closed = True
            stream.close()

    process.stdout = UnreadablePipe()

    def read(fd, size):
        if fd == reader:
            raise original
        return raw_read(fd, size)

    monkeypatch.setattr(ram.os, 'read', read)
    monkeypatch.setattr(ram.subprocess, 'Popen', lambda *a, **kw: process)
    polls = []

    def poll():
        assert ram._FSCK_OWNERS[id(process)] is process
        assert not process.stdout.closed and not process.stderr.closed
        polls.append(None)
        assert os.write(writer, b'writer still owned') == len(b'writer still owned')
        return 0 if len(polls) == 3 else None

    monkeypatch.setattr(process, 'poll', poll)
    monkeypatch.setattr(ram.time, 'sleep', lambda _: None)
    try:
        with pytest.raises(OSError) as caught:
            derive(inputs)
        assert caught.value is original
        assert len(polls) == 3 and not process.waited
        assert process.stdout.closed and process.stderr.closed
        assert id(process) not in ram._FSCK_OWNERS
        out = inputs.root / 'new'
        proof = json.loads((out / 'derivation.json').read_bytes())['fsck']
        assert proof['returncode'] == 0
        assert not proof['owner_retained'] and not proof['pipes_drained']
        assert proof['fsck.stdout']['truncated']
        assert proof['errors'][0]['error'] == 'OSError: ' + str(original)
        assert (out / 'fsck.stderr').read_bytes() == b'other stream survives\n'
    finally:
        os.close(writer)
        process.stdout.close()
        process.stderr.close()
        ram._FSCK_OWNERS.pop(id(process), None)


@pytest.mark.parametrize('stage', ['Popen', 'wait', 'write'])
def test_fsck_process_and_write_errors_keep_original_evidence(inputs, monkeypatch, stage):
    process = FakeFsck(stdout=b'original output\n', stderr=b'original error\n')
    original = OSError('synthetic ' + stage + ' failure')
    real_put = ram.put

    def popen(*args, **kwargs):
        if stage == 'Popen':
            raise original
        return process

    def wait():
        process.waited = True
        raise original

    def put(fd, raw):
        if raw == b'original output\n':
            os.write(fd, raw[:4])
            raise original
        return real_put(fd, raw)

    monkeypatch.setattr(ram.subprocess, 'Popen', popen)
    if stage == 'wait':
        monkeypatch.setattr(process, 'wait', wait)
    if stage == 'write':
        monkeypatch.setattr(ram, 'put', put)
    try:
        with pytest.raises(OSError) as caught:
            derive(inputs)
        assert caught.value is original
        out = inputs.root / 'new'
        proof = json.loads((out / 'derivation.json').read_bytes())['fsck']
        assert proof['errors'][0]['error'] == 'OSError: ' + str(original)
        if stage == 'Popen':
            assert not process.waited
        else:
            assert process.waited and proof['pipes_drained']
            assert (out / 'fsck.stderr').read_bytes() == b'original error\n'
            if stage == 'wait':
                assert proof['returncode'] == 0 and not proof['owner_retained']
                assert id(process) not in ram._FSCK_OWNERS
                assert process.stdout.closed and process.stderr.closed
            else:
                assert proof['returncode'] == 0 and not proof['owner_retained']
                assert proof['fsck.stdout']['truncated']
                assert proof['fsck.stdout']['write_error'] == str(original)
                assert (out / 'fsck.stdout').read_bytes() == b'orig'
                assert proof['fsck.stdout']['sha256'] == hashlib.sha256(b'orig').hexdigest()
    finally:
        process.stdout.close()
        process.stderr.close()
        ram._FSCK_OWNERS.pop(id(process), None)


def test_fsck_both_selectors_fail_but_owner_drains_and_waits(inputs, monkeypatch):
    process = FakeFsck(stdout=b'original output', stderr=b'original error')
    original = OSError('synthetic primary selector failure')

    def selector():
        raise original

    def select(*args):
        raise OSError('synthetic fallback selector failure')

    monkeypatch.setattr(ram.subprocess, 'Popen', lambda *a, **kw: process)
    monkeypatch.setattr(ram.selectors, 'DefaultSelector', selector)
    monkeypatch.setattr(ram.select, 'select', select)
    try:
        with pytest.raises(OSError) as caught:
            derive(inputs)
        assert caught.value is original
        assert not process.waited
        assert process.stdout.closed and process.stderr.closed
        assert id(process) not in ram._FSCK_OWNERS
        proof = json.loads((inputs.root / 'new/derivation.json').read_bytes())['fsck']
        assert proof['returncode'] == 0 and not proof['owner_retained']
        assert not proof['pipes_drained']
        assert [item['stage'] for item in proof['errors']] == ['selector.setup', 'select']
        assert (inputs.root / 'new/fsck.stdout').read_bytes() == b'original output'
        assert (inputs.root / 'new/fsck.stderr').read_bytes() == b'original error'
    finally:
        process.stdout.close()
        process.stderr.close()
        ram._FSCK_OWNERS.pop(id(process), None)


def test_owner_does_not_return_on_persistent_control_errors(inputs, monkeypatch):
    process = FakeFsck(stdout=b'original output', stderr=b'original error')
    original = OSError('primary transport error')
    polls = []

    def broken(*args, **kwargs):
        raise original

    def poll():
        assert ram._FSCK_OWNERS[id(process)] is process
        assert not process.stdout.closed and not process.stderr.closed
        polls.append(None)
        return 0 if len(polls) > ram.FSCK_ERROR_LIMIT + 4 else None

    monkeypatch.setattr(ram.subprocess, 'Popen', lambda *a, **kw: process)
    monkeypatch.setattr(ram.selectors, 'DefaultSelector', broken)
    monkeypatch.setattr(ram.select, 'select', broken)
    monkeypatch.setattr(ram.select, 'poll', broken)
    monkeypatch.setattr(ram.time, 'sleep', lambda _: None)
    monkeypatch.setattr(process, 'poll', poll)
    with pytest.raises(OSError) as caught:
        derive(inputs)
    assert caught.value is original
    assert len(polls) > ram.FSCK_ERROR_LIMIT
    assert process.stdout.closed and process.stderr.closed
    assert id(process) not in ram._FSCK_OWNERS
    proof = json.loads((inputs.root / 'new/derivation.json').read_bytes())['fsck']
    assert proof['returncode'] == 0 and proof['owner_retained'] is False
    assert len(proof['errors']) == ram.FSCK_ERROR_LIMIT and proof['suppressed_errors'] > 0


def test_fsck_exact_log_limit_is_accepted_with_full_readback(inputs, monkeypatch):
    monkeypatch.setattr(ram, 'FSCK_LOG_LIMIT', 8)
    process = FakeFsck(stdout=b'12345678', stderr=b'abcdefgh')
    monkeypatch.setattr(ram.subprocess, 'Popen', lambda *a, **kw: process)
    result = derive(inputs)
    assert process.waited
    assert result['storage']['fsck_log_bytes'] == 16
    assert all(result['fsck'][name]['truncated'] is False for name in ('fsck.stdout', 'fsck.stderr'))
    assert ram.verify_for_consumer(result)['host_readback_verified'] is True


def test_consumer_rechecks_persisted_fsck_logs(inputs):
    result = derive(inputs)
    log = inputs.root / 'new/fsck.stdout'
    log.write_bytes(b'changed original fsck evidence\n')
    with pytest.raises(ValueError, match='fsck log readback differs'):
        ram.verify_for_consumer(result)


def test_consumer_refuses_truncated_fsck_claim(inputs):
    result = derive(inputs)
    result['fsck']['fsck.stderr']['truncated'] = True
    with pytest.raises(ValueError, match='fsck log binding differs'):
        ram.verify_for_consumer(result)


def test_complete_readback_binds_inputs_and_only_adds_seed(inputs):
    base, seed = inputs.base.read_bytes(), inputs.seed.read_bytes()
    result = derive(inputs)
    assert result['ok'] and result['capture_verified'] is result['runtime_verified'] is False
    assert result['schema'] == 'a7c2-functional-ram-initramfs-v3'
    assert result['physical_compatible'] is False
    assert result['removed_members'] == {}
    output = Path(result['output']['path'])
    assert sha(output) == result['output']['sha256']
    assert result['output']['identity'] == ram.metadata(output.stat())
    assert result['base']['sha256'] == sha(inputs.base)
    assert result['seed']['sha256'] == sha(inputs.seed)
    assert inputs.base.read_bytes() == base and inputs.seed.read_bytes() == seed
    assert stat.S_IMODE(output.stat().st_mode) == 0o600
    assert stat.S_IMODE(output.parent.stat().st_mode) == 0o700
    fd = os.open(output, os.O_RDONLY)
    try:
        members, _ = ram.scan(fd)
    finally:
        os.close(fd)
    assert members[ram.GUEST]['bytes'] == ram.SEED_BYTES
    assert members[ram.GUEST]['sha256'] == sha(inputs.seed)
    assert members['keep']['sha256'] == hashlib.sha256(b'unchanged firmware bytes').hexdigest()
    assert len(inputs.calls) == 1
    assert all(n >= ram.FREE_SPACE_FLOOR + len(base) + ram.SEED_BYTES for n in inputs.budgets)
    receipt = json.loads((output.parent / 'derivation.json').read_bytes())
    assert receipt == result
    consumer = ram.verify_for_consumer(result)
    assert consumer['host_readback_verified'] is True
    assert consumer['guest_consumption_verified'] is False
    assert result['owner']['uid'] == os.geteuid()
    assert result['storage']['actual_input_copy_bytes'] == 0
    assert result['storage']['reserved_base_copy_bytes'] == len(base)
    assert result['storage']['reserved_seed_copy_bytes'] == ram.SEED_BYTES
    assert all(item['next_consumer'] and item['reclaim_when'] and 'allocated_bytes' in item
               for item in result['retained_files'].values())


def test_explicit_opt_in_and_hash_bindings_required(inputs):
    with pytest.raises(ValueError, match='off'):
        derive(inputs, functional_camera=False)
    assert not (inputs.root / 'new').exists()
    with pytest.raises(ValueError, match='SHA256'):
        derive(inputs, base_sha256='not-a-hash')
    assert not (inputs.root / 'new').exists()
    with pytest.raises(ValueError, match='SHA256 differs'):
        derive(inputs, seed_sha256='0' * 64)
    assert not inputs.calls
    assert json.loads((inputs.root / 'new/derivation.json').read_bytes())['ok'] is False


def test_no_existing_output_or_receipt_is_overwritten(inputs):
    out = inputs.root / 'current'
    out.mkdir(mode=0o700)
    old = out / 'derivation.json'
    old.write_bytes(b'old failure evidence\n')
    with pytest.raises(FileExistsError):
        derive(inputs, output='current')
    assert old.read_bytes() == b'old failure evidence\n'
    assert not inputs.calls


@pytest.mark.parametrize('kind', ['symlink', 'hardlink', 'fifo', 'writable', 'ancestor'])
def test_unsafe_seed_rejected_without_fsck(inputs, kind):
    original = inputs.seed
    if kind == 'symlink':
        inputs.seed = inputs.root / 'alias.fat'
        inputs.seed.symlink_to(original)
    elif kind == 'hardlink':
        os.link(original, inputs.root / 'alias.fat')
    elif kind == 'fifo':
        inputs.seed = inputs.root / 'fifo'
        os.mkfifo(inputs.seed)
    elif kind == 'writable':
        original.chmod(0o666)
    else:
        nested = inputs.root / 'real'
        nested.mkdir()
        original.rename(nested / original.name)
        alias = inputs.root / 'alias'
        alias.symlink_to(nested, target_is_directory=True)
        inputs.seed = alias / original.name
    # Bind a placeholder digest: opening/identity validation precedes hashing.
    with pytest.raises((ValueError, OSError)):
        ram.derive(inputs.base, inputs.seed, inputs.root / 'new', base_sha256=sha(inputs.base),
                   seed_sha256='0' * 64, functional_camera=True, parallel_peak_bytes=0)
    assert not inputs.calls
    assert not (inputs.root / 'new/functional-ram-initramfs.cpio').exists()


@pytest.mark.parametrize('offset,value', [(54, b'FAT32   '), (510, b'\0\0'), (13, b'\x80'),
                                         (22, b'\x01\0'), (19, b'\x01\0')])
def test_fat16_geometry_and_not_just_label_required(inputs, offset, value):
    with inputs.seed.open('r+b') as stream:
        stream.seek(offset)
        stream.write(value)
    with pytest.raises(ValueError, match='FAT16|FAT'):
        derive(inputs)
    assert not inputs.calls


def test_fsck_failure_keeps_original_logs_and_no_output(inputs, monkeypatch):
    monkeypatch.setattr(ram.subprocess, 'Popen', lambda *a, **kw:
                        FakeFsck(returncode=1, stdout=b'bad FAT\n', stderr=b'read-only\n'))
    with pytest.raises(ValueError, match='fsck.fat failed'):
        derive(inputs)
    out = inputs.root / 'new'
    assert (out / 'fsck.stdout').read_bytes() == b'bad FAT\n'
    assert (out / 'fsck.stderr').read_bytes() == b'read-only\n'
    assert not (out / 'functional-ram-initramfs.cpio').exists()
    assert json.loads((out / 'derivation.json').read_bytes())['fsck']['returncode'] == 1


def test_space_floor_rejects_before_large_writes(inputs, monkeypatch):
    def low_space(*args):
        raise ValueError('insufficient free space')
    monkeypatch.setattr(ram, 'check_space', low_space)
    with pytest.raises(ValueError, match='insufficient free space'):
        derive(inputs)
    assert not inputs.calls
    assert not (inputs.root / 'new/functional-ram-initramfs.cpio').exists()


def test_load_window_rejects_before_fsck_or_large_writes(inputs, monkeypatch):
    monkeypatch.setattr(ram, 'MAX_INITRD_BYTES', ram.SEED_BYTES)
    with pytest.raises(ValueError, match='load window'):
        derive(inputs)
    assert not inputs.calls
    assert not (inputs.root / 'new/functional-ram-initramfs.cpio').exists()
    receipt = json.loads((inputs.root / 'new/derivation.json').read_bytes())
    assert receipt['planned_output_bytes'] > ram.SEED_BYTES


def test_existing_guest_seed_is_rejected_without_implicit_replacement(inputs):
    original = archive(record(ram.GUEST, b'old seed', inode=4))
    inputs.base.write_bytes(original)
    with pytest.raises(ValueError, match='implicit replacement refused'):
        derive(inputs)
    assert inputs.base.read_bytes() == original
    assert not inputs.calls
    out = inputs.root / 'new'
    assert not (out / 'functional-ram-initramfs.cpio').exists()
    assert json.loads((out / 'derivation.json').read_bytes())['ok'] is False


@pytest.mark.parametrize('extra', [record('keep', b'duplicate'),
    record('simulation/sd-card.fat.gz', b'conflicting compressed seed'),
    record(ram.GUEST, b'unsafe hardlink', links=2),
    record(ram.GUEST, b'keep', mode=stat.S_IFLNK | 0o777),
    record('../escape', b'nonlocal')])
def test_ambiguous_archive_paths_rejected(inputs, extra):
    inputs.base.write_bytes(archive(extra))
    with pytest.raises(ValueError):
        derive(inputs)
    assert not inputs.calls
    assert not (inputs.root / 'new/functional-ram-initramfs.cpio').exists()


def test_partial_output_failure_preserved_and_never_accepted(inputs, monkeypatch):
    original = ram.new_member
    def fail_after_seed_header(output, seed, inode):
        os.write(output, b'partial-cpio')
        raise OSError('synthetic write failure')
    monkeypatch.setattr(ram, 'new_member', fail_after_seed_header)
    with pytest.raises(OSError, match='synthetic write failure'):
        derive(inputs)
    out = inputs.root / 'new'
    partial = (out / 'functional-ram-initramfs.cpio').read_bytes()
    old_receipt = (out / 'derivation.json').read_bytes()
    assert partial.endswith(b'partial-cpio')
    assert json.loads(old_receipt)['ok'] is False
    monkeypatch.setattr(ram, 'new_member', original)
    with pytest.raises(FileExistsError):
        derive(inputs)
    assert (out / 'derivation.json').read_bytes() == old_receipt
    assert (out / 'functional-ram-initramfs.cpio').read_bytes() == partial


def test_consumer_rejects_changed_output(inputs):
    result = derive(inputs)
    output = Path(result['output']['path'])
    with output.open('r+b') as stream:
        stream.seek(120)
        stream.write(b'changed')
    with pytest.raises(ValueError, match='Consumer readback differs'):
        ram.verify_for_consumer(result)


def test_removes_only_fallback_from_derived_archive_and_fits_load_window(inputs, monkeypatch):
    old = b'original fallback bytes\0' * 100
    keep = record('simulation/media-camera.fat.bak', b'preserve similarly named member', inode=5)
    fallback = record(ram.FALLBACK, old, mode=stat.S_IFREG | 0o640, inode=40)
    base = archive(keep, fallback)
    inputs.base.write_bytes(base)
    seed = inputs.seed.read_bytes()
    expected = archive(keep, record(ram.GUEST, seed, mode=stat.S_IFREG | 0o600, inode=41))
    # This window admits the replacement, but not the old fallback plus the seed.
    monkeypatch.setattr(ram, 'MAX_INITRD_BYTES', len(expected))
    result = derive(inputs, parallel_peak_bytes=12345)
    assert result['removed_members'] == {ram.FALLBACK: dict(
        bytes=len(old), sha256=hashlib.sha256(old).hexdigest(),
        mode=stat.S_IFREG | 0o640, links=1, reason=ram.REPLACEMENT_REASON,
        replacement_guest_path='/' + ram.GUEST)}
    output = Path(result['output']['path'])
    assert output.read_bytes() == expected
    assert inputs.base.read_bytes() == base and inputs.seed.read_bytes() == seed
    assert result['planned_output_bytes'] == len(expected)
    assert result['storage']['final_cpio_bytes'] == len(expected)
    assert result['storage']['parallel_peak_bytes'] == 12345
    assert result['storage']['peak_new_bytes'] >= len(base) + len(seed) + len(expected) + 12345
    assert all(required >= ram.FREE_SPACE_FLOOR + len(base) + len(seed) + len(expected) + 12345
               for required in inputs.budgets)
    inventory = json.loads((output.parent / 'members.json').read_bytes())
    assert ram.FALLBACK not in inventory
    assert 'simulation/media-camera.fat.bak' in inventory
    assert json.loads((output.parent / 'derivation.json').read_bytes()) == result
    assert ram.verify_for_consumer(result)['host_readback_verified'] is True


def test_fallback_member_is_untouched_without_explicit_opt_in(inputs):
    inputs.base.write_bytes(archive(record(ram.FALLBACK, b'keep original fallback')))
    original = inputs.base.read_bytes()
    with pytest.raises(ValueError, match='explicit opt-in'):
        derive(inputs, functional_camera=False)
    assert inputs.base.read_bytes() == original
    assert not (inputs.root / 'new').exists()
    assert not inputs.calls


@pytest.mark.parametrize('fallback', [
    record(ram.FALLBACK, b'/other/card', mode=stat.S_IFLNK | 0o777),
    record(ram.FALLBACK, b'hardlinked card', links=2),
    record(ram.FALLBACK, mode=stat.S_IFDIR | 0o700),
    record(ram.FALLBACK, mode=stat.S_IFIFO | 0o600),
    record(ram.FALLBACK, b'first') + record(ram.FALLBACK, b'duplicate'),
    record(ram.FALLBACK + '/child', b'descendant'),
])
def test_invalid_fallback_is_not_silently_removed(inputs, fallback):
    inputs.base.write_bytes(archive(fallback))
    original = inputs.base.read_bytes()
    with pytest.raises(ValueError):
        derive(inputs)
    assert inputs.base.read_bytes() == original
    assert not inputs.calls
    out = inputs.root / 'new'
    assert not (out / 'functional-ram-initramfs.cpio').exists()
    assert json.loads((out / 'derivation.json').read_bytes())['ok'] is False


def test_fallback_removal_plan_retained_on_fsck_failure(inputs, monkeypatch):
    original = b'original fallback survives failed derivation'
    inputs.base.write_bytes(archive(record(ram.FALLBACK, original)))
    base = inputs.base.read_bytes()
    monkeypatch.setattr(ram.subprocess, 'Popen', lambda *a, **kw:
                        FakeFsck(returncode=1, stdout=b'bad FAT\n', stderr=b'details\n'))
    with pytest.raises(ValueError, match='fsck.fat failed'):
        derive(inputs)
    out = inputs.root / 'new'
    proof = json.loads((out / 'derivation.json').read_bytes())
    assert proof['ok'] is False
    assert proof['removed_members'][ram.FALLBACK]['sha256'] == hashlib.sha256(original).hexdigest()
    assert proof['removed_members'][ram.FALLBACK]['bytes'] == len(original)
    assert (out / 'fsck.stdout').read_bytes() == b'bad FAT\n'
    assert (out / 'fsck.stderr').read_bytes() == b'details\n'
    assert inputs.base.read_bytes() == base
    assert not (out / 'functional-ram-initramfs.cpio').exists()


@pytest.mark.parametrize('field,value', [('bytes', 0), ('sha256', '0' * 64),
                                       ('reason', 'unspecified'), ('replacement_guest_path', '/other')])
def test_consumer_rechecks_fallback_removal_evidence(inputs, field, value):
    inputs.base.write_bytes(archive(record(ram.FALLBACK, b'full original fallback')))
    result = derive(inputs)
    result['removed_members'][ram.FALLBACK][field] = value
    with pytest.raises(ValueError, match='removal binding differs'):
        ram.verify_for_consumer(result)


@pytest.mark.parametrize('kind', ['missing', 'invented'])
def test_consumer_rejects_missing_or_invented_removal_bindings(inputs, kind):
    result = derive(inputs)
    if kind == 'missing':
        del result['removed_members']
    else:
        result['removed_members'][ram.FALLBACK] = dict(bytes=123, sha256='0' * 64)
    with pytest.raises(ValueError, match='removal binding differs'):
        ram.verify_for_consumer(result)


@pytest.mark.parametrize('schema', ['a7c2-functional-ram-initramfs-v1',
                                  'a7c2-functional-ram-initramfs-v2'])
def test_consumer_rejects_legacy_receipt_schema(inputs, schema):
    result = derive(inputs)
    result['schema'] = schema
    with pytest.raises(ValueError, match='opt-in derivation binding'):
        ram.verify_for_consumer(result)


@pytest.mark.parametrize('field', ['physical_compatible', 'capture_verified', 'runtime_verified'])
@pytest.mark.parametrize('value', [None, True, 0, 'false'])
def test_consumer_requires_explicit_false_safety_fields(inputs, field, value):
    result = derive(inputs)
    if value is None:
        del result[field]
    else:
        result[field] = value
    with pytest.raises(ValueError, match='opt-in derivation binding'):
        ram.verify_for_consumer(result)


def test_consumer_safety_flags_remain_false(inputs):
    result = derive(inputs)
    consumer = ram.verify_for_consumer(result)
    for field in ('physical_compatible', 'capture_verified', 'runtime_verified'):
        assert result[field] is consumer[field] is False


def test_consumer_rechecks_member_inventory_file(inputs):
    result = derive(inputs)
    inventory = inputs.root / 'new/members.json'
    inventory.write_bytes(b'!' + inventory.read_bytes()[1:])
    with pytest.raises(ValueError, match='member inventory differs'):
        ram.verify_for_consumer(result)


def test_consumer_requires_fallback_to_be_absent_from_output(inputs):
    old = b'old fallback'
    inputs.base.write_bytes(archive(record(ram.FALLBACK, old, inode=40)))
    result = derive(inputs)
    output = Path(result['output']['path'])
    output.write_bytes(archive(record(ram.FALLBACK, old, inode=40),
                              record(ram.GUEST, inputs.seed.read_bytes(),
                                     mode=stat.S_IFREG | 0o600, inode=41)))
    result['output']['sha256'] = sha(output)
    result['output']['identity'] = ram.metadata(output.stat())
    result['planned_output_bytes'] = output.stat().st_size
    with pytest.raises(ValueError, match='Output inventory differs'):
        ram.verify_for_consumer(result)


def test_consumer_rechecks_preserved_record_metadata_even_with_rebound_output(inputs):
    result = derive(inputs)
    output = Path(result['output']['path'])
    with output.open('r+b') as stream:
        # First raw newc member uid changes; payload hashes and inventory stay identical.
        stream.seek(22)
        stream.write(b'00000001')
    result['output']['sha256'] = sha(output)
    result['output']['identity'] = ram.metadata(output.stat())
    with pytest.raises(ValueError, match='Unrequested newc record change'):
        ram.verify_for_consumer(result)


def test_parallel_peak_must_be_declared(inputs):
    with pytest.raises(ValueError, match='parallel peak'):
        derive(inputs, parallel_peak_bytes=None)
    assert not (inputs.root / 'new').exists()
    result = derive(inputs, parallel_peak_bytes=12345)
    assert result['storage']['parallel_peak_bytes'] == 12345


def test_input_change_during_fsck_fails_without_publication(inputs, monkeypatch):
    def mutate(*args, **kwargs):
        with inputs.seed.open('r+b') as stream:
            stream.seek(1024)
            stream.write(b'changed')
        return FakeFsck(returncode=0, stdout=b'ok\n', stderr=b'')
    monkeypatch.setattr(ram.subprocess, 'Popen', mutate)
    with pytest.raises(ValueError, match='identity changed'):
        derive(inputs)
    assert not (inputs.root / 'new/functional-ram-initramfs.cpio').exists()
