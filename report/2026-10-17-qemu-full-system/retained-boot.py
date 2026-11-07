"""Bound QEMU migration sessions; never a Sony WBI or physical hotboot claim.

qmp is a negotiated, exclusively owned callable returning unwrapped QMP results,
with getfd(name, fd) using SCM_RIGHTS (FDQMP adapts an existing Unix connection).
Only audited machines without external block/host-service state are admitted.
Snapshots leave the source stopped. Restore requires -S -incoming defer and a
new run/generation; no kernel launch, reset, cold fallback or old execution pass.
Collectors must attest the complete device inventory and resource identities;
QMP completion alone cannot detect an unregistered device VMState.
"""
import array
import copy
import hashlib
import json
import os
from pathlib import Path
import shutil
import socket
import stat
import threading
import time

SCOPE = 'functional-qemu-retained-session'
RESERVE = 1024 ** 3
SOURCE_REVIEW = {
    'evidence_kind': 'source-only', 'qemu_version': '11.1.2',
    'program_sha256': '1e2e2f60753efa021cecef14fdcb87f98824b9962233b3cefebb82880354e915',
    'build_manifest': 'runtime/usb-qemu/manifest.json',
    'whole_machine_migration_supported': False,
    'actual_snapshot_roundtrip_verified': False,
    'facts': [
        {'path': 'migration/fd.c', 'line': 40, 'finding': 'fd transport accepts sockets/pipes, rejects regular files'},
        {'path': 'migration/file.c', 'line': 96, 'finding': 'core supports file migration'},
        {'path': 'migration/migration.c', 'line': 1833, 'finding': 'incoming requires -incoming defer'},
        {'path': 'hw/timer/sony_hwtimer.c', 'line': 141, 'finding': 'timer/epoch/count/control/compare have no VMState registration'},
        {'path': 'hw/misc/sony_spacc_stub.c', 'line': 49, 'finding': 'malloc register buffer has no VMState registration'},
        {'path': 'hw/input/sony-ui-input.c', 'line': 124, 'finding': 'held-key state has no VMState registration'},
        {'path': 'hw/arm/virt.c', 'line': 3306, 'finding': 'Sony media/MMC custom state has no VMState registration'},
        {'path': 'hw/usb/hcd-dwc3.c', 'line': 653, 'finding': 'DWC3 has VMState; this does not cover the Sony additions'},
    ],
}


class SnapshotError(RuntimeError):
    def __init__(self, message, receipt):
        super().__init__(message)
        self.receipt = receipt


class Unsupported(SnapshotError):
    pass


class FDQMP:
    """Use only on an already negotiated, exclusively owned AF_UNIX QMP socket."""
    def __init__(self, sock, stream=None):
        if sock.family != socket.AF_UNIX or sock.getsockopt(socket.SOL_SOCKET, socket.SO_TYPE) != socket.SOCK_STREAM:
            raise ValueError('A local Unix stream QMP connection is required')
        self.sock, self.stream = sock, stream if stream is not None else sock.makefile('rwb')

    def _request(self, command, arguments=None, fd=None):
        request = {'execute': command}
        if arguments is not None:
            request['arguments'] = arguments
        data = json.dumps(request).encode() + b'\n'
        if fd is None:
            self.stream.write(data)
            self.stream.flush()
        else:
            self.stream.flush()
            sent = self.sock.sendmsg([data], [(socket.SOL_SOCKET, socket.SCM_RIGHTS, array.array('i', [fd]))])
            self.sock.sendall(data[sent:])
        while True:
            line = self.stream.readline()
            if not line:
                raise RuntimeError('QMP connection closed')
            reply = json.loads(line)
            if 'event' in reply:
                continue
            if 'return' not in reply:
                raise RuntimeError('QMP error: ' + json.dumps(reply))
            return reply['return']

    def __call__(self, command, arguments=None):
        return self._request(command, arguments)

    def getfd(self, name, fd):
        return self._request('getfd', {'fdname': name}, fd)


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def _sha(value):
    if not isinstance(value, str) or len(value) != 64 or any(c not in '0123456789abcdef' for c in value):
        raise ValueError('Expected lowercase SHA256')


def _identity(value):
    result = copy.deepcopy(value)
    if not isinstance(result, dict) or not isinstance(result.get('run'), str) or not result['run'].strip():
        raise ValueError('A unique run is required')
    if type(result.get('generation')) is not int or result['generation'] < 0:
        raise ValueError('A nonnegative generation is required')
    for name in ('profile', 'source_class'):
        if not isinstance(result.get(name), str) or not result[name].strip():
            raise ValueError(name + ' is required')
    machine, qemu, resources = (result.get(k) for k in ('machine', 'qemu', 'resources'))
    if (not isinstance(machine, dict) or not isinstance(machine.get('type'), str) or not machine['type'].strip() or
            type(machine.get('ram_bytes')) is not int or machine['ram_bytes'] <= 0):
        raise ValueError('machine type, ram_bytes and complete topology are required')
    if not isinstance(qemu, dict) or not isinstance(qemu.get('version'), str):
        raise ValueError('qemu version and program SHA256 are required')
    _sha(qemu.get('sha256'))
    if not isinstance(resources, dict) or not isinstance(resources.get('partitions'), dict) or not resources['partitions']:
        raise ValueError('Partition identities are required, including RAM-backed partitions')
    for key in ('kernel', 'dtb', 'ram0', 'ap', 'cp', 'manifest'):
        _sha(resources.get(key))
    for value in resources['partitions'].values():
        _sha(value)
    _digest(result)
    return result


def _compatible(identity):
    return {k: v for k, v in identity.items() if k not in ('run', 'generation')}


def _receipt(identity, operation):
    return dict(schema=1, scope=SCOPE, operation=operation, identity=identity,
                binding_digest=_digest(identity), status='pending', verified=False,
                physical_hotboot_verified=False, sony_wbi_resume_verified=False,
                whole_machine_verified=False, previous_execution_evidence_reusable=False,
                cold_fallback_allowed=False, guest_execution_verified=False, qmp=[], blockers=[])


def _admit(receipt, qmp):
    identity = receipt['identity']
    blockers = []
    if identity['profile'] == 'wbi-resume':
        blockers.append('Sony WBI restore needs original loader/RAM/CPU/device context; QEMU migration is not Sony WBI')
    if identity['qemu']['sha256'] == SOURCE_REVIEW['program_sha256']:
        blockers.append('Known Sony QEMU build has unregistered device state')
        receipt['source_review'] = copy.deepcopy(SOURCE_REVIEW)
    audit = identity.get('device_migration', {})
    if (not isinstance(audit, dict) or audit.get('complete') is not True or
            audit.get('external_state') != 'none' or audit.get('blockers') != [] or
            not isinstance(audit.get('devices'), list) or not audit['devices']):
        blockers.append('Complete device inventory/VMState audit and absence of external state are required')
    else:
        if any(not isinstance(d, str) or not d.strip() for d in audit['devices']) or len(set(audit['devices'])) != len(audit['devices']):
            blockers.append('Device inventory must contain unique names')
        try:
            _sha(audit.get('audit_sha256'))
        except ValueError:
            blockers.append('Device migration audit SHA256 is required')
    if not callable(getattr(qmp, 'getfd', None)):
        blockers.append('QMP SCM_RIGHTS getfd transport is required')
    if blockers:
        receipt.update(status='unsupported', blockers=blockers)
        raise Unsupported('; '.join(blockers), receipt)


def _call(qmp, receipt, command, arguments=None):
    entry = {'command': command, 'arguments': arguments}
    receipt['qmp'].append(entry)
    try:
        entry['response'] = copy.deepcopy(qmp(command, arguments))
        return entry['response']
    except Exception as error:
        entry['error'] = str(error)
        raise


def _preflight(qmp, receipt):
    version = _call(qmp, receipt, 'query-version')['qemu']
    actual = '.'.join(str(version[k]) for k in ('major', 'minor', 'micro'))
    if actual != receipt['identity']['qemu']['version']:
        raise ValueError('Actual QEMU version differs from binding')
    if _call(qmp, receipt, 'query-block'):
        raise Unsupported('External block state is not included; no disk fallback', receipt)
    caps = _call(qmp, receipt, 'query-migrate-capabilities')
    if any(c.get('state') and c.get('capability') != 'events' for c in caps):
        raise Unsupported('Only single-channel complete-state migration is supported', receipt)


def _wait(qmp, receipt, deadline):
    while time.monotonic() < deadline:
        result = _call(qmp, receipt, 'query-migrate')
        status = result.get('status')
        if status == 'completed':
            return result
        if status not in ('setup', 'active', 'device', 'wait-unplug'):
            raise RuntimeError('Migration did not complete: ' + json.dumps(result))
        time.sleep(0.02)
    raise TimeoutError('Migration completion timeout; no cold fallback')


def _path(value):
    path = Path(os.path.abspath(value))
    if any(p.is_symlink() for p in (*reversed(path.parents), path)):
        raise ValueError('Symlink snapshot path forbidden')
    return path


def _regular(path):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    if not stat.S_ISREG(os.fstat(fd).st_mode):
        os.close(fd)
        raise ValueError('Snapshot must be a regular file')
    return os.fdopen(fd, 'rb')


def _hash(stream):
    stream.seek(0)
    before = os.fstat(stream.fileno())
    if stream.read(8) != b'QEVM\x00\x00\x00\x03' or before.st_size <= 8:
        raise ValueError('Incomplete QEMU migration stream')
    stream.seek(0)
    sha = hashlib.file_digest(stream, 'sha256').hexdigest()
    after = os.fstat(stream.fileno())
    if (before.st_size, before.st_mtime_ns, before.st_ctime_ns) != (after.st_size, after.st_mtime_ns, after.st_ctime_ns):
        raise ValueError('Migration stream changed during read')
    return sha, after.st_size


def _json(dirfd, name, value):
    temporary = '.' + name + '.partial'
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=dirfd)
    with os.fdopen(fd, 'w') as stream:
        json.dump(value, stream, sort_keys=True, indent=2)
        stream.write('\n')
        stream.flush()
        os.fsync(stream.fileno())
    os.link(temporary, name, src_dir_fd=dirfd, dst_dir_fd=dirfd, follow_symlinks=False)
    os.unlink(temporary, dir_fd=dirfd)
    os.fsync(dirfd)


def _transfer(sock, stream, outgoing, errors):
    try:
        if outgoing:
            while data := sock.recv(1024 * 1024):
                stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        else:
            stream.seek(0)
            while data := stream.read(1024 * 1024):
                sock.sendall(data)
            sock.shutdown(socket.SHUT_WR)
    except Exception as error:
        errors.append(str(error))


def bind_snapshot(run_identity, qmp, output, *, timeout=60):
    """Create a new owned directory; receipt.json is published only after completion.

    Failure preserves snapshot.partial + failure.json and raises SnapshotError
    (Unsupported for admission failures). The source is never resumed implicitly.
    """
    identity = _identity(run_identity)
    receipt = _receipt(identity, 'snapshot')
    _admit(receipt, qmp)
    output = _path(output)
    output.mkdir(mode=0o700)
    dirfd = os.open(output, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    local = remote = worker = stream = None
    started = False
    try:
        if timeout <= 0 or shutil.disk_usage(output).free < identity['machine']['ram_bytes'] + RESERVE:
            raise ValueError('Invalid timeout or insufficient snapshot space')
        _preflight(qmp, receipt)
        before = _call(qmp, receipt, 'query-status')
        if before.get('status') not in ('running', 'paused'):
            raise ValueError('Source must be running or paused')
        prior = _call(qmp, receipt, 'query-migrate').get('status', 'none')
        if prior not in ('none', 'failed', 'cancelled'):
            raise ValueError('Another migration or previous postmigrate state is present')
        _call(qmp, receipt, 'stop')
        stopped = _call(qmp, receipt, 'query-status')
        if stopped.get('running') is not False or stopped.get('status') != 'paused':
            raise RuntimeError('QMP stop was not confirmed')
        receipt['source_stopped'] = True
        fd = os.open('snapshot.partial', os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=dirfd)
        stream = os.fdopen(fd, 'r+b')
        local, remote = socket.socketpair()
        errors = []
        qmp.getfd('retained-output', remote.fileno())
        remote.close()
        worker = threading.Thread(target=_transfer, args=(local, stream, True, errors), daemon=True)
        worker.start()
        deadline = time.monotonic() + timeout
        started = True
        _call(qmp, receipt, 'migrate', {'uri': 'fd:retained-output'})
        receipt['migration'] = _wait(qmp, receipt, deadline)
        worker.join(max(0, deadline - time.monotonic()))
        if worker.is_alive() or errors:
            raise RuntimeError('Migration stream incomplete: ' + str(errors))
        receipt['snapshot_sha256'], receipt['snapshot_bytes'] = _hash(stream)
        stopped = _call(qmp, receipt, 'query-status')
        if stopped.get('running') is not False:
            raise RuntimeError('Source resumed during snapshot')
        anchored, current = os.fstat(dirfd), os.stat(output, follow_symlinks=False)
        if (current.st_dev, current.st_ino) != (anchored.st_dev, anchored.st_ino):
            raise RuntimeError('Snapshot directory changed')
        os.link('snapshot.partial', 'snapshot.bin', src_dir_fd=dirfd, dst_dir_fd=dirfd, follow_symlinks=False)
        os.unlink('snapshot.partial', dir_fd=dirfd)
        receipt.update(status='completed', verified=True, snapshot_file='snapshot.bin', source_stopped=True)
        _json(dirfd, 'receipt.json', receipt)
        return receipt
    except Exception as error:
        if started:
            try:
                _call(qmp, receipt, 'migrate_cancel')
            except Exception as cancel_error:
                receipt['cancel_error'] = str(cancel_error)
        # A failure after stream completion must not leave a success marker.
        try:
            os.unlink('receipt.json', dir_fd=dirfd)
        except FileNotFoundError:
            pass
        if stream is not None:
            try:
                published = os.stat('snapshot.bin', dir_fd=dirfd, follow_symlinks=False)
                pinned = os.fstat(stream.fileno())
                if (published.st_dev, published.st_ino) == (pinned.st_dev, pinned.st_ino):
                    os.rename('snapshot.bin', 'snapshot.partial', src_dir_fd=dirfd, dst_dir_fd=dirfd)
            except FileNotFoundError:
                pass
        receipt.update(status='unsupported' if isinstance(error, Unsupported) else 'failed', verified=False,
                       error=str(error), partial_file='snapshot.partial')
        if isinstance(error, Unsupported):
            receipt['blockers'].append(str(error))
        try:
            _json(dirfd, 'failure.json', receipt)
        except OSError as write_error:
            receipt['failure_receipt_error'] = str(write_error)
        raise (Unsupported if isinstance(error, Unsupported) else SnapshotError)(str(error), receipt) from error
    finally:
        if local is not None:
            try:
                local.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
        if worker is not None:
            worker.join(1)
        for item in (local, remote, stream):
            if item is not None:
                item.close()
        os.close(dirfd)


def restore_snapshot(snapshot, run_identity, qmp, *, timeout=60):
    """Load into an already owned -S -incoming defer target, then cont.

    Caller writes the returned receipt into the NEW run. Its stages list is empty;
    old guest/AP execution evidence cannot be transferred to the new generation.
    """
    identity = _identity(run_identity)
    receipt = _receipt(identity, 'restore')
    _admit(receipt, qmp)
    snapshot = _path(snapshot)
    local = remote = worker = None
    try:
        if os.path.lexists(snapshot / 'failure.json'):
            raise ValueError('Snapshot has a failure receipt')
        with _regular(snapshot / 'receipt.json') as source:
            saved = json.load(source)
        previous = _identity(saved['identity'])
        if (saved.get('schema') != 1 or saved.get('operation') != 'snapshot' or
                saved.get('status') != 'completed' or saved.get('verified') is not True or
                saved.get('scope') != SCOPE or saved.get('binding_digest') != _digest(previous) or
                saved.get('migration', {}).get('status') != 'completed' or saved.get('snapshot_file') != 'snapshot.bin'):
            raise ValueError('Incomplete or unbound snapshot receipt')
        if _compatible(identity) != _compatible(previous):
            raise ValueError('Machine/profile/version/resources/device binding changed')
        if identity['run'] == previous['run'] or identity['generation'] != previous['generation'] + 1:
            raise ValueError('Restore requires a new run and the next generation')
        if timeout <= 0:
            raise ValueError('Invalid timeout')
        with _regular(snapshot / 'snapshot.bin') as stream:
            actual = _hash(stream)
            if actual != (saved.get('snapshot_sha256'), saved.get('snapshot_bytes')):
                raise ValueError('Snapshot stream identity differs')
            _preflight(qmp, receipt)
            state = _call(qmp, receipt, 'query-status')
            if state.get('status') != 'inmigrate' or state.get('running') is not False:
                raise Unsupported('Destination must wait in -S -incoming defer; cold fallback forbidden', receipt)
            local, remote = socket.socketpair()
            qmp.getfd('retained-input', remote.fileno())
            remote.close()
            errors = []
            worker = threading.Thread(target=_transfer, args=(local, stream, False, errors), daemon=True)
            deadline = time.monotonic() + timeout
            worker.start()
            _call(qmp, receipt, 'migrate-incoming', {'uri': 'fd:retained-input', 'exit-on-error': False})
            receipt['migration'] = _wait(qmp, receipt, deadline)
            worker.join(max(0, deadline - time.monotonic()))
            if worker.is_alive() or errors:
                raise RuntimeError('Incoming stream incomplete: ' + str(errors))
            if _hash(stream) != actual:
                raise ValueError('Snapshot changed during restore')
            loaded = _call(qmp, receipt, 'query-status')
            if loaded.get('running') is not False or loaded.get('status') != 'paused':
                raise RuntimeError('Restored target must remain paused until verified')
            _call(qmp, receipt, 'cont')
            if _call(qmp, receipt, 'query-status').get('running') is not True:
                raise RuntimeError('Retained CPU continuation unconfirmed')
        receipt.update(status='completed', verified=True, retained_cpu_resumed=True, stages=[],
                       parent_binding_digest=saved['binding_digest'], snapshot_sha256=actual[0],
                       snapshot_generation=previous['generation'])
        return receipt
    except Exception as error:
        receipt.update(status='unsupported' if isinstance(error, Unsupported) else 'failed',
                       verified=False, error=str(error))
        if isinstance(error, Unsupported):
            receipt['blockers'].append(str(error))
        raise (Unsupported if isinstance(error, Unsupported) else SnapshotError)(str(error), receipt) from error
    finally:
        if local is not None:
            try:
                local.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
        if worker is not None:
            worker.join(1)
        for item in (local, remote):
            if item is not None:
                item.close()
