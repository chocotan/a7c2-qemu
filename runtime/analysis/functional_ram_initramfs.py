#!/usr/bin/env python3
"""Opt-in, offline 1 GiB functional RAM-card initramfs derivation.

Integration: derive(base, seed, output_dir, base_sha256=..., seed_sha256=...,
functional_camera=True, parallel_peak_bytes=0) returns a receipt. The caller must
explicitly declare the other concurrent generation peak (zero when serialized).
Call verify_for_consumer(receipt) immediately before handing off the archive.
Pass receipt['output']['path'] as the
existing probe's --initramfs --initramfs-file, with A7C2_SD_IMAGE set to the original
seed and its existing functional RAM-card options explicitly enabled; verify both
hashes again before launch. Explicit seeded RAM-card mode uses only sd-card.fat;
the derived archive omits media-camera.fat if present, without changing the base.
The v3 receipt retains v2 removal evidence and requires physical_compatible=false.
Consumers must use verify_for_consumer on a trusted v3 receipt, retain
A7C2_SD_IMAGE and the explicit functional RAM-card options, and never reuse this
archive for the unseeded fallback mode. No guest consumption is inferred here.
This module never enables the model or starts a VM. All inputs, outputs and
persistent temporaries must be within the deployable product root (parents[2]);
external seeds are refused. A base already carrying sd-card.fat is rejected.
fsck streams are capped at 1 MiB each; overflow is drained until natural exit,
retained as failure evidence, and never accepted. No timeout or kill is used.
No current asset, firmware tree, or old receipt is modified.
"""
import argparse
from contextlib import ExitStack, contextmanager
import fcntl
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import select
import selectors
import stat
import struct
import subprocess
import time

from sd_transport import directory, identity, check_space, FREE_SPACE_FLOOR

PROJECT = Path(__file__).resolve().parents[2]
SEED_BYTES = 1024**3
CHUNK = 1024**2
FSCK_LOG_LIMIT = CHUNK
# Diagnostic index only; the synchronous finalizer also holds every live process.
_FSCK_OWNERS = {}
FSCK_SYSTEM_PATHS = ('/usr/bin/fsck.fat', '/usr/sbin/fsck.fat')
FSCK_ERROR_LIMIT = 64
# Admission: run-7_7exap7 + run-p8sw_b0h; product integration acceptance is retained in
# scratch/a7c2-gate-unblock-integration-20261115/ (host only; top-level probe stays gated).
_FSCK_EXECUTION_BLOCKED = None
# Stage 1: host owner acceptance alone admits fsck execution; no VM result is required.
# These are review requirements, never environment-controlled admission switches.
FSCK_UNBLOCK_REQUIREMENTS = (
    'Independent owner retains exact executable/seed/work FDs until original wait status is collected',
    'Exception, BaseException, pipe/log/selector/wait failure and overflow regressions preserve the first error and child evidence',
    'Parent death/reload has an independent recovery owner with verified process identity; PID alone is insufficient',
    'Pinned root-owned fsck executable full SHA and directory chain verified before/after execution',
    'Two-thread host acceptance pins current sources and records raw exits, bounded logs, retained failures and zero live children',
)
# Stage 2 follows successful host fsck/readback; future guest evidence cannot gate this handoff.
RAM_CONSUMER_HANDOFF_REQUIREMENTS = (
    'Host fsck completes under the accepted owner; seed/derived archive identity and readback remain verified',
    'Consumer binds the exact inherited FD triple and actual QEMU executable/owner/QMP/serial endpoints before launch',
)
# Stage 3 follows handoff and launch; only observed guest consumption and exit admit success/release.
RAM_GUEST_ACCEPTANCE_REQUIREMENTS = (
    'Consumer retains the handed-off FD lease and proves sealed memfd identity and guest whole-card SHA readback',
    'Confirmed VM exit and owner resource accounting precede lease release; capture success needs separate writeback evidence',
)
GUEST = 'simulation/sd-card.fat'
FALLBACK = 'simulation/media-camera.fat'
REPLACEMENT_REASON = 'Explicit functional RAM-card mode consumes simulation/sd-card.fat instead of the unseeded fallback'
SCHEMA = 'a7c2-functional-ram-initramfs-v3'
OVERHEAD = 16 * CHUNK
MAX_INITRD_BYTES = 0x580000000 - 0x504000000


def require(condition, message):
    if not condition:
        raise ValueError(message)


def project_path(value):
    path = Path(value).absolute()
    require(PROJECT != Path('/') and '..' not in path.parts and path.is_relative_to(PROJECT),
            'Input/output must be inside the product, without parent traversal')
    return path


def metadata(st):
    return dict(device=st.st_dev, inode=st.st_ino, bytes=st.st_size,
                mtime_ns=st.st_mtime_ns, ctime_ns=st.st_ctime_ns,
                mode=stat.S_IMODE(st.st_mode), uid=st.st_uid, links=st.st_nlink,
                allocated_bytes=st.st_blocks * 512)


@contextmanager
def source(path):
    with directory(path.parent) as parent:
        fd = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC,
                     dir_fd=parent)
        try:
            before = os.fstat(fd)
            require(stat.S_ISREG(before.st_mode) and before.st_uid == os.geteuid() and
                    before.st_nlink == 1 and not before.st_mode & 0o022,
                    'Input must be an owned, single-link, non-shared-writable regular file')
            def unchanged():
                current = os.fstat(fd)
                named = os.stat(path.name, dir_fd=parent, follow_symlinks=False)
                require(metadata(before) == metadata(current) == metadata(named),
                        'Input identity changed: ' + str(path))
                # Rewalk all ancestors as well as checking the pinned descriptor.
                with directory(path.parent) as fresh:
                    require(identity(os.fstat(parent)) == identity(os.fstat(fresh)),
                            'Input parent changed')
            yield fd, before, unchanged
            unchanged()
        finally:
            os.close(fd)


def blocks(fd, offset, length):
    while length:
        raw = os.pread(fd, min(CHUNK, length), offset)
        require(raw, 'Truncated input')
        yield raw
        offset += len(raw)
        length -= len(raw)


def sha_range(fd, offset, length):
    sha = hashlib.sha256()
    for raw in blocks(fd, offset, length):
        sha.update(raw)
    return sha.hexdigest()


def fat16(fd, size):
    require(size == SEED_BYTES, 'RAM card seed must be exactly 1 GiB')
    raw = os.pread(fd, 512, 0)
    require(len(raw) == 512, 'Truncated FAT boot sector')
    u16 = lambda n: struct.unpack_from('<H', raw, n)[0]
    total16, total32 = u16(19), struct.unpack_from('<I', raw, 32)[0]
    sector, cluster, reserved, fats = u16(11), raw[13], u16(14), raw[16]
    root_entries, fat_sectors = u16(17), u16(22)
    total = total16 or total32
    require(raw[510:] == b'\x55\xaa' and raw[54:62] == b'FAT16   ' and
            sector == 512 and total * sector == size and not (total16 and total32) and
            0 < cluster <= 128 and not cluster & (cluster - 1) and
            reserved > 0 and fats in (1, 2) and root_entries > 0 and fat_sectors > 0 and
            raw[21] in (0xf0, *range(0xf8, 0x100)), 'Invalid FAT16 BPB/signature')
    data = total - reserved - fats * fat_sectors - (root_entries * 32 + 511) // 512
    clusters = data // cluster
    require(data > 0 and 4085 <= clusters < 65525 and
            fat_sectors * sector >= (clusters + 2) * 2, 'Not FAT16 or undersized FAT')
    return dict(fat_bits=16, sector_bytes=sector, cluster_sectors=cluster,
                total_sectors=total, clusters=clusters)


def scan(fd):
    """Read every member payload, reject ambiguous paths and preserve raw records."""
    size, offset, entries, parents = os.fstat(fd).st_size, 0, {}, set()
    require(0 < size <= 0xffffffff, 'Base/output raw newc size is unsupported')
    while True:
        start = offset
        header = os.pread(fd, 110, offset)
        require(len(header) == 110 and header[:6] == b'070701' and
                re.fullmatch(b'[0-9a-fA-F]{104}', header[6:]), 'Unsupported/truncated raw newc')
        fields = [int(header[n:n+8], 16) for n in range(6, 110, 8)]
        inode, mode, _, _, links, _, length, _, _, _, _, namesize, checksum = fields
        require(1 < namesize <= 4096 and checksum == 0, 'Invalid newc name/checksum')
        raw = os.pread(fd, namesize, offset + 110)
        require(len(raw) == namesize and raw[-1:] == b'\0' and b'\0' not in raw[:-1],
                'Ambiguous newc filename')
        path = PurePosixPath(raw[:-1].decode('utf-8'))
        require(not path.is_absolute() and '..' not in path.parts, 'Nonlocal newc path')
        name = str(path)
        data = (offset + 110 + namesize + 3) & ~3
        end = (data + length + 3) & ~3
        require(end <= size, 'Truncated newc payload/padding')
        if name == 'TRAILER!!!':
            require(length == 0, 'Invalid newc trailer')
            for tail in blocks(fd, end, size - end):
                require(not any(tail), 'Concatenated/nonzero newc trailer data')
            return entries, (start, end)
        require(len(entries) < 200000 and name not in entries, 'Duplicate/oversized newc inventory')
        ancestors = [str(p) for p in path.parents if str(p) != '.']
        require(not any(p in entries and not stat.S_ISDIR(entries[p]['mode']) for p in ancestors)
                and not (name in parents and not stat.S_ISDIR(mode)), 'Nondirectory newc ancestor')
        require(name != '.' or stat.S_ISDIR(mode), 'Invalid newc root')
        entries[name] = dict(start=start, end=end, data=data, bytes=length, inode=inode,
                             mode=mode, links=links, sha256=sha_range(fd, data, length))
        parents.update(ancestors)
        offset = end


def member_plan(entries):
    """Only the opt-in seeded route may omit the validated unseeded fallback."""
    require('simulation' in entries and stat.S_ISDIR(entries['simulation']['mode']),
            'Base must already contain a real simulation directory')
    require('simulation/sd-card.fat.gz' not in entries, 'Compressed seed route is incompatible')
    require(GUEST not in entries, 'Base already contains explicit guest seed; implicit replacement refused')
    for name in (GUEST, FALLBACK):
        old = entries.get(name)
        require(old is None or (stat.S_ISREG(old['mode']) and old['links'] == 1),
                'Existing guest card must be a unique regular member: ' + name)
        require(not any(n.startswith(name + '/') for n in entries),
                'Guest card has descendants: ' + name)
    removed = {}
    if FALLBACK in entries:
        old = entries[FALLBACK]
        removed[FALLBACK] = dict(bytes=old['bytes'], sha256=old['sha256'],
                                 mode=old['mode'], links=old['links'],
                                 reason=REPLACEMENT_REASON, replacement_guest_path='/' + GUEST)
    return {n: e for n, e in entries.items() if n != FALLBACK}, removed


def verify_members(base_fd, output_fd, preserved, seed_sha256):
    """Read all output payloads and compare every preserved raw newc record."""
    actual, _ = scan(output_fd)
    require(set(actual) == set(preserved) | {GUEST}, 'Output inventory differs')
    for name, entry in preserved.items():
        got = actual[name]
        require(got['bytes'] == entry['bytes'] and got['sha256'] == entry['sha256'] and
                got['end'] - got['start'] == entry['end'] - entry['start'] and
                sha_range(output_fd, got['start'], got['end'] - got['start']) ==
                sha_range(base_fd, entry['start'], entry['end'] - entry['start']),
                'Unrequested newc record change: ' + name)
    require(actual[GUEST]['bytes'] == SEED_BYTES and actual[GUEST]['sha256'] == seed_sha256 and
            actual[GUEST]['mode'] == (stat.S_IFREG | 0o600) and actual[GUEST]['links'] == 1,
            'Output seed full readback differs')
    return {n: {k: e[k] for k in ('bytes', 'mode', 'links', 'sha256')}
            for n, e in actual.items()}


def put(fd, raw):
    while raw:
        count = os.write(fd, raw)
        require(count > 0, 'Short output write')
        raw = raw[count:]


def copy_range(source_fd, output_fd, offset, length):
    for raw in blocks(source_fd, offset, length):
        put(output_fd, raw)


def new_member(fd, seed, inode):
    name = ('./' + GUEST).encode() + b'\0'
    fields = [inode, stat.S_IFREG | 0o600, 0, 0, 1, 0, SEED_BYTES, 0, 0, 0, 0, len(name), 0]
    require(all(0 <= n <= 0xffffffff for n in fields), 'newc metadata overflow')
    header = b'070701' + ''.join(f'{n:08x}' for n in fields).encode()
    put(fd, header + name + b'\0' * (-(len(header) + len(name)) % 4))
    copy_range(seed, fd, 0, SEED_BYTES)
    put(fd, b'\0' * (-SEED_BYTES % 4))


def write_json(parent, name, value):
    raw = (json.dumps(value, sort_keys=True, indent=2) + '\n').encode()
    fd = os.open(name, os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=parent)
    try:
        put(fd, raw)
        os.fsync(fd)
        require(os.pread(fd, len(raw) + 1, 0) == raw, 'Receipt readback differs')
    finally:
        os.close(fd)
    os.fsync(parent)
    return dict(sha256=hashlib.sha256(raw).hexdigest(), bytes=len(raw))


@contextmanager
def system_fsck(proof):
    """Only fixed, root-owned, non-shared-writable directory/inode chains qualify."""
    with ExitStack() as stack:
        chain = []

        def opened(name, parent=None, *, directory=False):
            flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC
            if directory:
                flags |= os.O_DIRECTORY
            fd = os.open(name, flags, dir_fd=parent)
            stack.callback(os.close, fd)
            before = os.fstat(fd)
            require(before.st_uid == 0 and not before.st_mode & 0o022 and
                    (stat.S_ISDIR(before.st_mode) if directory else
                     stat.S_ISREG(before.st_mode) and before.st_mode & stat.S_IXUSR and
                     not before.st_mode & (stat.S_ISUID | stat.S_ISGID)),
                    'Unsafe system fsck directory/executable: ' + name)
            chain.append((fd, before, name, parent))
            return fd

        root = opened('/', directory=True)
        usr = opened('usr', root, directory=True)
        executable = None
        for path in FSCK_SYSTEM_PATHS:
            # Only absence permits considering the other fixed system location.
            # A symlink, permission error, or unsafe inode fails without substitution.
            try:
                parent = opened(Path(path).parent.name, usr, directory=True)
                executable = opened('fsck.fat', parent)
            except FileNotFoundError:
                continue
            break
        require(executable is not None, 'fsck.fat is required; no filesystem check bypass')
        before = os.fstat(executable)
        digest = sha_range(executable, 0, before.st_size)
        proof.update(path=path, identity=metadata(before), sha256=digest)

        def verify():
            current = os.fstat(executable)
            after_sha = sha_range(executable, 0, current.st_size)
            proof['after_sha256'] = after_sha
            require(after_sha == digest, 'System fsck full SHA256 changed')
            for fd, original, name, parent in chain:
                require(metadata(original) == metadata(os.fstat(fd)) == metadata(
                    os.stat(name, dir_fd=parent, follow_symlinks=False)),
                    'System fsck directory/executable identity changed: ' + name)

        verify()
        try:
            yield executable
        except BaseException:
            try:
                verify()
            except BaseException as error:
                proof['verification_error'] = f'{type(error).__name__}: {error}'
            raise
        else:
            verify()


def fsck_readonly(seed, tmp, work, result):
    """A dedicated recovery parent retains all FDs through fsck's natural exit."""
    from fsck_recovery import run
    require(_FSCK_EXECUTION_BLOCKED is None, str(_FSCK_EXECUTION_BLOCKED))
    require(stat.S_ISREG(os.fstat(seed).st_mode) and
            fcntl.fcntl(seed, fcntl.F_GETFL) & os.O_ACCMODE == os.O_RDONLY,
            'fsck requires a pinned read-only regular seed')
    return run(seed, tmp, work, result, body=_fsck_owned_body, write_json=write_json)


def _fsck_owned_body(seed, tmp, work, result, *, _handoff=None):
    """Persist bounded streams in the recovery owner; preserve the first failure."""
    proof = result['fsck'] = dict(command=['pinned-system-fsck-fd', '-n', 'pinned-readonly-seed-fd'],
                                  returncode=None, log_limit_bytes=FSCK_LOG_LIMIT)
    if _FSCK_EXECUTION_BLOCKED is not None:
        proof['blocked_reason'] = _FSCK_EXECUTION_BLOCKED
        require(False, _FSCK_EXECUTION_BLOCKED)
    errors = []

    def failed(stage, error):
        if not errors:
            errors.append(error)
        recorded = proof.setdefault('errors', [])
        if len(recorded) < FSCK_ERROR_LIMIT:
            recorded.append(dict(stage=stage, error=f'{type(error).__name__}: {error}'))
        else:
            proof['suppressed_errors'] = proof.get('suppressed_errors', 0) + 1

    require(stat.S_ISREG(os.fstat(seed).st_mode) and
            fcntl.fcntl(seed, fcntl.F_GETFL) & os.O_ACCMODE == os.O_RDONLY,
            'fsck requires a pinned read-only regular seed')
    with ExitStack() as stack:
        executable = stack.enter_context(system_fsck(proof.setdefault('executable', {})))
        logs = {}
        for name in ('fsck.stdout', 'fsck.stderr'):
            fd = os.open(name, os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                         0o600, dir_fd=work)
            stack.callback(os.close, fd)
            proof[name] = dict(bytes=0, observed_bytes=0, truncated=False)
            logs[name] = dict(fd=fd, sha=hashlib.sha256(), error=None)

        def save(name, raw):
            item, log = proof[name], logs[name]
            item['observed_bytes'] += len(raw)
            kept = raw[:max(0, FSCK_LOG_LIMIT - item['bytes'])]
            if log['error'] is None:
                try:
                    put(log['fd'], kept)
                    log['sha'].update(kept)
                    item['bytes'] += len(kept)
                except BaseException as error:
                    log['error'] = str(error)
                    item['write_error'] = str(error)
                    failed(name + '.write', error)
            item['truncated'] = item['observed_bytes'] > item['bytes']

        env = dict(PATH='/usr/bin:/usr/sbin', TMPDIR=f'/proc/self/fd/{tmp}',
                   TMP=f'/proc/self/fd/{tmp}', TEMP=f'/proc/self/fd/{tmp}', LC_ALL='C')
        try:
            process = subprocess.Popen([f'/proc/self/fd/{executable}', '-n', f'/proc/self/fd/{seed}'],
                                       pass_fds=(executable, seed, tmp, work), env=env,
                                       cwd=f'/proc/self/fd/{work}', stdin=subprocess.DEVNULL,
                                       close_fds=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        except BaseException as error:
            failed('Popen', error)
            raise

        def finish():
            # This runs before closing logs, executable or seed, including on BaseException.
            # Persistent drain/poll errors deliberately keep this owner on the stack.
            if proof.get('owner_retained') is False:
                return
            unread = {pipe: name for pipe, name in
                      ((process.stdout, 'fsck.stdout'), (process.stderr, 'fsck.stderr'))
                      if not pipe.closed}
            while True:
                try:
                    code = process.poll()
                except BaseException as error:
                    failed('owner.poll', error)
                    code = None
                try:
                    if proof.get('pipes_drained'):
                        unread.clear()
                    ready = []
                    if unread:
                        poller = select.poll()
                        by_fd = {}
                        for pipe in unread:
                            by_fd[pipe.fileno()] = pipe
                            poller.register(pipe, select.POLLIN | select.POLLHUP | select.POLLERR)
                        ready = poller.poll(100 if code is None else 0)
                        read_failed = False
                        for fd, _ in ready:
                            pipe = by_fd[fd]
                            try:
                                raw = os.read(fd, 65536)
                                if raw:
                                    save(unread[pipe], raw)
                                else:
                                    del unread[pipe]
                            except BaseException as error:
                                failed('owner.drain', error)
                                proof[unread[pipe]]['truncated'] = True
                                read_failed = True
                        if code is not None and read_failed:
                            break
                    if code is not None and (not unread or not ready):
                        break
                except BaseException as error:
                    failed('owner.drain', error)
                    if code is not None:
                        break
                try:
                    time.sleep(0.05)
                except BaseException as error:
                    failed('owner.pause', error)
            proof['returncode'] = code
            if unread:
                proof['pipes_drained'] = False
                for name in unread.values():
                    proof[name]['truncated'] = True
            elif not proof.get('errors'):
                proof['pipes_drained'] = True
            for pipe in (process.stdout, process.stderr):
                try:
                    pipe.close()
                except BaseException as error:
                    failed('pipe.close', error)
            proof['owner_retained'] = False
            _FSCK_OWNERS.pop(id(process), None)

        stack.callback(finish)
        if _handoff is not None:
            try:
                process = _handoff(process, proof)
            except BaseException as error:
                failed('recovery.handoff', error)
        _FSCK_OWNERS[id(process)] = process
        proof.update(pid=process.pid, owner_retained=True, pipes_drained=False)
        pending = {process.stdout: 'fsck.stdout', process.stderr: 'fsck.stderr'}
        selector, incomplete = None, False
        try:
            selector = selectors.DefaultSelector()
            for pipe, name in pending.items():
                selector.register(pipe, selectors.EVENT_READ, name)
        except BaseException as error:
            failed('selector.setup', error)
            if selector is not None:
                try:
                    selector.close()
                except BaseException as close_error:
                    failed('selector.close', close_error)
            selector = None
        while pending:
            try:
                if selector is None:
                    ready, _, _ = select.select(list(pending), [], [], 0 if incomplete else None)
                else:
                    ready = [key.fileobj for key, _ in selector.select()]
            except BaseException as error:
                failed('selector.select' if selector is not None else 'select', error)
                if selector is None:
                    incomplete = True
                    for name in pending.values():
                        proof[name]['truncated'] = True
                        proof[name]['read_error'] = proof['errors'][-1]['error']
                    break
                try:
                    selector.close()
                except BaseException as close_error:
                    failed('selector.close', close_error)
                selector = None
                continue
            if not ready:
                if incomplete:
                    break
                continue
            for pipe in ready:
                name = pending[pipe]
                try:
                    raw = os.read(pipe.fileno(), 65536)
                except BaseException as error:
                    failed(name + '.read', error)
                    try:
                        # One raw read avoids waiting to fill a buffered read request.
                        raw = pipe.read1(65536)
                    except BaseException as fallback_error:
                        failed(name + '.read1', fallback_error)
                        proof[name]['read_error'] = proof['errors'][-1]['error']
                        proof[name]['truncated'] = True
                        incomplete = True
                        del pending[pipe]
                        continue
                if not raw:
                    del pending[pipe]
                    if selector is not None:
                        try:
                            selector.unregister(pipe)
                        except BaseException as error:
                            failed('selector.unregister', error)
                            try:
                                selector.close()
                            except BaseException as close_error:
                                failed('selector.close', close_error)
                            selector = None
                    continue
                save(name, raw)
            if incomplete and selector is not None:
                try:
                    selector.close()
                except BaseException as error:
                    failed('selector.close', error)
                selector = None
        if selector is not None:
            try:
                selector.close()
            except BaseException as error:
                failed('selector.close', error)
        proof['pipes_drained'] = not incomplete and not pending
        if proof['pipes_drained']:
            try:
                proof['returncode'] = process.wait()
            except BaseException as error:
                failed('wait', error)
            if proof['returncode'] is not None:
                proof['owner_retained'] = False
                _FSCK_OWNERS.pop(id(process))
                for pipe in (process.stdout, process.stderr):
                    try:
                        pipe.close()
                    except BaseException as error:
                        failed('pipe.close', error)
        else:
            proof['wait_blocked_reason'] = 'Pipe drain incomplete; readers and process owner retained'
            for name in pending.values():
                proof[name]['truncated'] = True
                proof[name].setdefault('read_error', proof['wait_blocked_reason'])
        finish()
        result['storage']['fsck_log_bytes'] = 0
        for name, log in logs.items():
            try:
                size = os.fstat(log['fd']).st_size
                result['storage']['fsck_log_bytes'] += size
                os.fsync(log['fd'])
                item = proof[name]
                item['sha256'] = sha_range(log['fd'], 0, size)
                require(log['error'] is None and size == item['bytes'] and
                        item['sha256'] == log['sha'].hexdigest(), 'fsck log readback differs: ' + name)
            except BaseException as error:
                failed(name + '.readback', error)
        try:
            os.fsync(work)
        except BaseException as error:
            failed('work.fsync', error)
        if errors:
            raise errors[0]
    require(proof['pipes_drained'] and not proof['owner_retained'], 'fsck exit is unconfirmed')
    require(not any(proof[name]['truncated'] for name in logs), 'fsck log limit exceeded')
    require(proof['returncode'] == 0, 'Read-only fsck.fat failed')


def derive(base, seed, output_dir, *, base_sha256, seed_sha256, functional_camera=False,
           parallel_peak_bytes=None):
    """Fail closed; output_dir must not exist. Failure leaves only new evidence."""
    require(functional_camera is True, 'Functional camera is off; explicit opt-in required')
    require(type(parallel_peak_bytes) is int and parallel_peak_bytes >= 0,
            'Declare other parallel peak bytes explicitly, including zero when serialized')
    for expected in (base_sha256, seed_sha256):
        require(isinstance(expected, str) and re.fullmatch('[0-9a-f]{64}', expected),
                'Caller must bind both input SHA256 values')
    base, seed, out = map(project_path, (base, seed, output_dir))
    require(out != PROJECT and not base.is_relative_to(out) and not seed.is_relative_to(out),
            'Output must be independent of input/current directories')
    with directory(out.parent) as parent:
        os.mkdir(out.name, 0o700, dir_fd=parent)  # Never reuse a current or failed run.
        with directory(out) as work:
            require(stat.S_IMODE(os.fstat(work).st_mode) == 0o700, 'Output must be private')
            result = dict(schema=SCHEMA, ok=False,
                          functional_camera=True, output_dir=str(out), guest_path='/' + GUEST,
                          physical_compatible=False, capture_verified=False, runtime_verified=False,
                          owner=dict(uid=os.geteuid(), pid=os.getpid(), tool=str(Path(__file__).absolute())),
                          retained_reason='Controlled offline derivation or original failure evidence',
                          next_consumer='Explicit functional RAM-card launch after verify_for_consumer',
                          reclaim_when='Owner confirms next consumer complete, no active references, and failure evidence retained',
                          reclaimed_bytes=0)
            try:
                with ExitStack() as stack:
                    bfd, bst, bcheck = stack.enter_context(source(base))
                    sfd, sst, scheck = stack.enter_context(source(seed))
                    require((bst.st_dev, bst.st_ino) != (sst.st_dev, sst.st_ino), 'Input aliases')
                    result['base'] = dict(path=str(base), identity=metadata(bst), expected_sha256=base_sha256)
                    result['seed'] = dict(path=str(seed), identity=metadata(sst), expected_sha256=seed_sha256)
                    peak = (bst.st_size + SEED_BYTES + MAX_INITRD_BYTES + OVERHEAD +
                            2 * FSCK_LOG_LIMIT + parallel_peak_bytes)
                    result['storage'] = dict(peak_new_bytes=peak, reserve_bytes=FREE_SPACE_FLOOR,
                                             reserved_base_copy_bytes=bst.st_size, reserved_seed_copy_bytes=SEED_BYTES,
                                             reserved_fsck_log_bytes=2 * FSCK_LOG_LIMIT,
                                             actual_input_copy_bytes=0, parallel_peak_bytes=parallel_peak_bytes,
                                             available_before=os.fstatvfs(work).f_bavail * os.fstatvfs(work).f_frsize,
                                             existing_task_allocated_bytes=os.fstat(work).st_blocks * 512)
                    check_space(work, FREE_SPACE_FLOOR + peak)
                    result['fat16'] = fat16(sfd, sst.st_size)
                    require(sha_range(bfd, 0, bst.st_size) == base_sha256 and
                            sha_range(sfd, 0, sst.st_size) == seed_sha256, 'Input SHA256 differs')
                    result['base']['sha256'] = base_sha256
                    result['seed']['sha256'] = seed_sha256
                    bcheck(); scheck()
                    entries, trailer = scan(bfd)
                    preserved, result['removed_members'] = member_plan(entries)
                    member_prefix = (110 + len(('./' + GUEST).encode()) + 1 + 3) & ~3
                    output_bytes = (sum(e['end'] - e['start'] for e in preserved.values())
                                    + member_prefix + SEED_BYTES + (-SEED_BYTES % 4) + trailer[1] - trailer[0])
                    result['planned_output_bytes'] = output_bytes
                    require(output_bytes <= MAX_INITRD_BYTES,
                            'Derived raw initramfs exceeds the existing probe load window')
                    inventory = {n: {k: e[k] for k in ('bytes', 'mode', 'links', 'sha256')}
                                 for n, e in preserved.items()}
                    inventory[GUEST] = dict(bytes=SEED_BYTES, mode=stat.S_IFREG | 0o600,
                                            links=1, sha256=seed_sha256)
                    inventory_bytes = len((json.dumps(inventory, sort_keys=True, indent=2) + '\n').encode())
                    peak = (bst.st_size + SEED_BYTES + output_bytes + inventory_bytes + OVERHEAD +
                            2 * FSCK_LOG_LIMIT + parallel_peak_bytes)
                    result['storage']['peak_new_bytes'] = peak
                    result['storage']['final_cpio_bytes'] = output_bytes
                    result['storage']['inventory_bytes'] = inventory_bytes
                    check_space(work, FREE_SPACE_FLOOR + peak)
                    os.mkdir('tmp', 0o700, dir_fd=work)
                    tmp = os.open('tmp', os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=work)
                    stack.callback(os.close, tmp)
                    fsck_readonly(sfd, tmp, work, result)
                    scheck(); bcheck()
                    check_space(work, FREE_SPACE_FLOOR + peak)
                    output = os.open('functional-ram-initramfs.cpio', os.O_RDWR | os.O_CREAT |
                                     os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=work)
                    try:
                        for entry in preserved.values():
                            copy_range(bfd, output, entry['start'], entry['end'] - entry['start'])
                        new_member(output, sfd, max(e['inode'] for e in entries.values()) + 1)
                        copy_range(bfd, output, trailer[0], trailer[1] - trailer[0])
                        os.fsync(output)
                        ost = os.fstat(output)
                        require(ost.st_size == output_bytes, 'Output length differs from budgeted archive')
                        actual_inventory = verify_members(bfd, output, preserved, seed_sha256)
                        output_sha = sha_range(output, 0, ost.st_size)
                        require(metadata(ost) == metadata(os.fstat(output)) == metadata(os.stat(
                            'functional-ram-initramfs.cpio', dir_fd=work, follow_symlinks=False)),
                            'Output identity changed')
                        require(sha_range(bfd, 0, bst.st_size) == base_sha256 and
                                sha_range(sfd, 0, sst.st_size) == seed_sha256, 'Input changed during derivation')
                        bcheck(); scheck()
                        require(actual_inventory == inventory, 'Output metadata inventory differs')
                        result['members'] = write_json(work, 'members.json', inventory)
                        result['output'] = dict(path=str(out / 'functional-ram-initramfs.cpio'),
                                                sha256=output_sha, identity=metadata(ost))
                    finally:
                        os.close(output)
                with directory(out) as named_work:
                    pinned, named = os.fstat(work), os.fstat(named_work)
                    require((pinned.st_dev, pinned.st_ino) == (named.st_dev, named.st_ino) and
                            stat.S_IMODE(named.st_mode) == 0o700, 'Output directory replaced')
                result['ok'] = True
            except Exception as error:
                result['error'] = f'{type(error).__name__}: {error}'
                raise
            finally:
                files = {}
                for name in os.listdir(work):
                    st = os.stat(name, dir_fd=work, follow_symlinks=False)
                    files[name] = dict(metadata(st), owner=result['owner'],
                                       retained_reason=result['retained_reason'],
                                       next_consumer=result['next_consumer'], reclaim_when=result['reclaim_when'])
                result['output_directory_identity'] = metadata(os.fstat(work))
                result['retained_files'] = files
                result['retained_payload_bytes'] = sum(item['allocated_bytes'] for item in files.values())
                result['ledger_allocation'] = 'derivation.json itself is excluded from retained_payload_bytes'
                result['available_after'] = os.fstatvfs(work).f_bavail * os.fstatvfs(work).f_frsize
                write_json(work, 'derivation.json', result)
    return result


def verify_for_consumer(binding):
    """Re-read all bound inputs/output; a host readback is not guest consumption.

    binding must be the trusted return value of derive, or an externally
    SHA-verified copy of its v3 receipt. This verifies removal evidence, every
    preserved raw record, seed payload and members.json, as well as all full file
    hashes. The caller owns serialization until launch and must retain the seeded
    functional RAM-card route; this archive is unsuitable for unseeded fallback.
    """
    require(type(binding) is dict and binding.get('ok') is True and
            binding.get('schema') == SCHEMA and
            binding.get('physical_compatible') is False and
            binding.get('capture_verified') is False and binding.get('runtime_verified') is False and
            binding.get('functional_camera') is True, 'No successful opt-in derivation binding')
    out = project_path(binding['output_dir'])
    require(project_path(binding['output']['path']) == out / 'functional-ram-initramfs.cpio' and
            binding.get('guest_path') == '/' + GUEST, 'Consumer route differs')
    with ExitStack() as stack:
        sources = {}
        for key in ('base', 'seed', 'output'):
            proof = binding[key]
            fd, before, unchanged = stack.enter_context(source(project_path(proof['path'])))
            require(metadata(before) == proof['identity'] and
                    sha_range(fd, 0, before.st_size) == proof['sha256'],
                    'Consumer readback differs: ' + key)
            if key == 'seed':
                require(proof['sha256'] == proof['expected_sha256'], 'Seed SHA256 binding differs')
                fat16(fd, before.st_size)
            elif key == 'base':
                require(proof['sha256'] == proof['expected_sha256'], 'Base SHA256 binding differs')
            else:
                require(before.st_size == binding['planned_output_bytes'] <= MAX_INITRD_BYTES,
                        'Consumer archive load window/length differs')
            sources[key] = fd, unchanged
        entries, _ = scan(sources['base'][0])
        preserved, removed = member_plan(entries)
        require(binding.get('removed_members') == removed, 'Consumer removal binding differs')
        inventory = verify_members(sources['base'][0], sources['output'][0], preserved,
                                   binding['seed']['sha256'])
        mfd, mst, mcheck = stack.enter_context(source(out / 'members.json'))
        expected_inventory = (json.dumps(inventory, sort_keys=True, indent=2) + '\n').encode()
        require(mst.st_size == binding['members']['bytes'] == len(expected_inventory) and
                sha_range(mfd, 0, mst.st_size) == binding['members']['sha256'] ==
                hashlib.sha256(expected_inventory).hexdigest(), 'Consumer member inventory differs')
        mcheck()
        fsck = binding['fsck']
        require(type(fsck.get('returncode')) is int and fsck['returncode'] == 0 and
                fsck.get('log_limit_bytes') == FSCK_LOG_LIMIT and
                fsck.get('pipes_drained') is True and fsck.get('owner_retained') is False and
                not fsck.get('errors'), 'Consumer fsck binding differs')
        tool = fsck.get('executable', {})
        require(tool.get('path') in FSCK_SYSTEM_PATHS and
                isinstance(tool.get('sha256'), str) and
                re.fullmatch('[0-9a-f]{64}', tool['sha256']) and
                tool.get('after_sha256') == tool['sha256'] and
                tool.get('identity', {}).get('uid') == 0 and
                not tool.get('verification_error'), 'Consumer system fsck identity differs')
        for name in ('fsck.stdout', 'fsck.stderr'):
            proof = fsck[name]
            require(proof.get('truncated') is False and type(proof.get('bytes')) is int and
                    0 <= proof['bytes'] <= FSCK_LOG_LIMIT and
                    proof.get('observed_bytes') == proof['bytes'] and 'write_error' not in proof,
                    'Consumer fsck log binding differs')
            fd, before, unchanged = stack.enter_context(source(out / name))
            require(before.st_size == proof['bytes'] and
                    sha_range(fd, 0, before.st_size) == proof['sha256'],
                    'Consumer fsck log readback differs')
            unchanged()
        for _, unchanged in sources.values():
            unchanged()
    return dict(path=binding['output']['path'], sha256=binding['output']['sha256'],
                host_readback_verified=True, guest_consumption_verified=False,
                physical_compatible=False, capture_verified=False, runtime_verified=False)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--functional-camera', action='store_true')
    parser.add_argument('--base', required=True, type=Path)
    parser.add_argument('--seed', required=True, type=Path)
    parser.add_argument('--output-dir', required=True, type=Path)
    parser.add_argument('--base-sha256', required=True)
    parser.add_argument('--seed-sha256', required=True)
    parser.add_argument('--parallel-peak-bytes', required=True, type=int,
                        help='Other concurrent generation bytes, explicitly 0 for a serialized run')
    args = parser.parse_args()
    result = derive(args.base, args.seed, args.output_dir, base_sha256=args.base_sha256,
                    seed_sha256=args.seed_sha256, functional_camera=args.functional_camera,
                    parallel_peak_bytes=args.parallel_peak_bytes)
    print(json.dumps(result, sort_keys=True))


if __name__ == '__main__':
    main()
