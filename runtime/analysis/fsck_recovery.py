"""Linux fsck owner: exact pidfd handoff, natural waits, persistent recovery proof."""
import array
import builtins
import ctypes
import json
import os
from pathlib import Path
import secrets
import select
import socket
import stat


def require(condition, message):
    if not condition:
        raise ValueError(message)


def process_identity(pid):
    raw = Path(f'/proc/{pid}/stat').read_bytes()
    fields = raw.rsplit(b') ', 1)[1].split()
    require(int(raw.split(b' ', 1)[0]) == pid, 'Process identity PID differs')
    return dict(pid=pid, start_ticks=int(fields[19]),
                boot_id=Path('/proc/sys/kernel/random/boot_id').read_text().strip())


def verify_identity(pidfd, expected):
    require(type(expected) is dict and set(expected) == {'pid', 'start_ticks', 'boot_id'} and
            type(expected['pid']) is int and expected['pid'] > 1 and
            type(expected['start_ticks']) is int and expected['start_ticks'] > 0 and
            type(expected['boot_id']) is str and bool(expected['boot_id']),
            'PID-only/incomplete generation refused')
    before = process_identity(expected['pid'])
    rows = Path(f'/proc/self/fdinfo/{pidfd}').read_text().splitlines()
    pids = [int(row.split(':', 1)[1]) for row in rows if row.startswith('Pid:')]
    require(pids == [expected['pid']], 'Transferred pidfd belongs to another process')
    require(before == expected == process_identity(expected['pid']),
            'PID/start_ticks/boot_id generation mismatch')


def send_handle(channel, pidfd, payload):
    raw = json.dumps(payload, sort_keys=True).encode()
    require(len(raw) <= 16384, 'Oversized pidfd handoff')
    require(channel.sendmsg([raw], [(socket.SOL_SOCKET, socket.SCM_RIGHTS,
                                   array.array('i', [pidfd]))]) == len(raw),
            'Short pidfd handoff')


def receive_handle(channel):
    size = array.array('i').itemsize
    raw, ancillary, flags, _ = channel.recvmsg(16384, socket.CMSG_SPACE(size), socket.MSG_CMSG_CLOEXEC)
    received = []
    try:
        for level, kind, data in ancillary:
            if level == socket.SOL_SOCKET and kind == socket.SCM_RIGHTS:
                values = array.array('i')
                values.frombytes(data[:len(data) - len(data) % size])
                received.extend(values)
        require(not flags & (socket.MSG_TRUNC | socket.MSG_CTRUNC) and len(received) == 1 and raw,
                'Exactly one complete pidfd handoff required')
        payload = json.loads(raw)
        return received.pop(), payload
    finally:
        for fd in received:
            os.close(fd)


def wait_pidfd(pidfd, expected, *, nonblocking=False):
    verify_identity(pidfd, expected)
    while True:
        try:
            status = os.waitid(os.P_PIDFD, pidfd, os.WEXITED | (os.WNOHANG if nonblocking else 0))
            break
        except InterruptedError:
            continue
    if status is None:
        return None
    require(status.si_pid == expected['pid'], 'pidfd wait returned another process')
    return dict(pid=status.si_pid, si_code=status.si_code,
                returncode=status.si_status if status.si_code == os.CLD_EXITED else -status.si_status,
                wait_api='waitid(P_PIDFD, WEXITED)')


class PidfdProcess:
    """Preserve the existing stream drainer while collecting status only by pidfd."""
    def __init__(self, process):
        self.original = process
        self.pid = process.pid
        self.stdout, self.stderr = process.stdout, process.stderr
        self.pidfd = os.pidfd_open(self.pid, 0)
        self.status = None
        try:
            self.identity = process_identity(self.pid)
            verify_identity(self.pidfd, self.identity)
        except BaseException:
            os.close(self.pidfd)
            raise

    def poll(self):
        if self.status is None:
            self.status = wait_pidfd(self.pidfd, self.identity, nonblocking=True)
            if self.status is not None:
                self.original.returncode = self.status['returncode']
        return None if self.status is None else self.status['returncode']

    def wait(self):
        if self.status is None:
            self.status = wait_pidfd(self.pidfd, self.identity)
            self.original.returncode = self.status['returncode']
        return self.status['returncode']

    def close(self):
        os.close(self.pidfd)


def _subreaper():
    libc = ctypes.CDLL(None, use_errno=True)
    if libc.prctl(36, 1, 0, 0, 0) != 0:
        raise OSError(ctypes.get_errno(), 'PR_SET_CHILD_SUBREAPER failed')
    enabled = ctypes.c_int()
    require(libc.prctl(37, ctypes.byref(enabled), 0, 0, 0) == 0 and enabled.value == 1,
            'Recovery owner subreaper verification failed')


def _recover(channel, generation, caller_pidfd, caller, seed, tmp, work, body, write_json):
    """This dedicated parent owns fsck even if the caller disappears or reloads."""
    result = {'storage': {}}
    envelope = dict(schema='a7c2-fsck-recovery-v1', generation=generation,
                    recovery=process_identity(os.getpid()), caller=caller,
                    subreaper=False, first_error=None, signals_sent=[])
    handles = []
    try:
        _subreaper()
        envelope['subreaper'] = True

        def handoff(process, proof):
            wrapped = PidfdProcess(process)
            handles.append(wrapped)
            proof['process_identity'] = wrapped.identity
            envelope['child'] = wrapped.identity
            try:
                send_handle(channel, wrapped.pidfd, dict(generation=generation, child=wrapped.identity,
                            recovery=envelope['recovery']))
                require(channel.recv(64) == generation.encode(), 'Caller did not acknowledge verified pidfd')
                envelope['handoff_acknowledged'] = True
            except BaseException as error:
                # The exact child remains owned here; finish draining before rejecting acceptance.
                envelope['handoff_error'] = f'{type(error).__name__}: {error}'
            return wrapped

        body(seed, tmp, work, result, _handoff=handoff)
        require('handoff_error' not in envelope, envelope.get('handoff_error'))
        envelope['ok'] = True
    except BaseException as error:
        envelope.update(ok=False, first_error=dict(type=type(error).__name__, message=str(error)))
    finally:
        # The body owns draining on all errors; this also covers a handoff error after Popen.
        for process in handles:
            if process.status is None:
                process.wait()
            envelope['child_wait'] = process.status
            process.close()
        poller = select.poll()
        poller.register(caller_pidfd, select.POLLIN)
        envelope['caller_exited'] = bool(poller.poll(0))
        envelope['result'] = result
        envelope['zero_live_fsck_children'] = all(p.status is not None for p in handles)
        write_json(work, 'fsck-recovery.json', envelope)
        channel.close()
        os.close(caller_pidfd)
    return 0 if envelope.get('ok') else 1


def run(seed, tmp, work, result, *, body, write_json):
    """Wait for the independent owner; a lost caller cannot release its child's FDs."""
    left, right = socket.socketpair(socket.AF_UNIX, socket.SOCK_SEQPACKET)
    generation = secrets.token_hex(16)
    caller = process_identity(os.getpid())
    caller_pidfd = os.pidfd_open(caller['pid'], 0)
    verify_identity(caller_pidfd, caller)
    recovery = None
    recovery_pidfd = child_pidfd = None
    first_error = None
    status = None
    try:
        recovery = os.fork()
        if recovery == 0:
            left.close()
            code = 125
            try:
                code = _recover(right, generation, caller_pidfd, caller, seed, tmp, work, body, write_json)
            finally:
                os._exit(code)
        right.close()
        os.close(caller_pidfd)
        caller_pidfd = None
        recovery_identity = process_identity(recovery)
        recovery_pidfd = os.pidfd_open(recovery, 0)
        verify_identity(recovery_pidfd, recovery_identity)
        try:
            child_pidfd, payload = receive_handle(left)
            require(type(payload) is dict and payload.get('generation') == generation and
                    payload.get('recovery') == recovery_identity, 'Recovery generation mismatch')
            verify_identity(child_pidfd, payload.get('child'))
            require(left.send(generation.encode()) == len(generation), 'Short recovery acknowledgement')
        except BaseException as error:
            first_error = error
        finally:
            # EOF permits recovery to finish even if validation or acknowledgement fails.
            left.close()
        while status is None:
            try:
                status = wait_pidfd(recovery_pidfd, recovery_identity)
            except (KeyboardInterrupt, InterruptedError) as error:
                if first_error is None:
                    first_error = error
        try:
            fd = os.open('fsck-recovery.json', os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC |
                         os.O_NONBLOCK, dir_fd=work)
            try:
                before = os.fstat(fd)
                require(stat.S_ISREG(before.st_mode) and before.st_uid == os.geteuid() and
                        before.st_nlink == 1 and not before.st_mode & 0o077 and
                        before.st_size <= 1024**2, 'Unsafe/oversized fsck recovery receipt')
                raw = os.pread(fd, before.st_size + 1, 0)
                require(len(raw) == before.st_size and before == os.fstat(fd) == os.stat(
                        'fsck-recovery.json', dir_fd=work, follow_symlinks=False),
                        'Recovery receipt changed during readback')
                envelope = json.loads(raw)
            finally:
                os.close(fd)
            require(envelope.get('schema') == 'a7c2-fsck-recovery-v1' and
                    envelope.get('generation') == generation and
                    envelope.get('recovery') == recovery_identity, 'Recovery receipt identity differs')
        except BaseException as error:
            if first_error is not None:
                first_error.add_note('Recovery receipt unavailable: ' + repr(error))
                raise first_error
            raise
        result['fsck'] = envelope['result'].get('fsck', {})
        result.setdefault('storage', {}).update(envelope['result'].get('storage', {}))
        result['fsck']['recovery'] = {key: envelope[key] for key in (
            'generation', 'recovery', 'caller', 'subreaper', 'caller_exited', 'zero_live_fsck_children')}
        if first_error is not None and 'child' in envelope:
            if envelope.get('first_error'):
                first_error.add_note('Recovery owner: ' + str(envelope['first_error']))
            raise first_error
        require(status['si_code'] == os.CLD_EXITED, 'Recovery owner did not exit naturally')
        if not envelope.get('ok'):
            error = envelope.get('first_error') or dict(type='ValueError', message='fsck recovery failed')
            kind = getattr(builtins, error['type'], ValueError)
            if not isinstance(kind, type) or not issubclass(kind, BaseException):
                kind = ValueError
            raise kind(error['message'])
        if first_error is not None:
            raise first_error
        require(status['returncode'] == 0 and envelope['zero_live_fsck_children'],
                'fsck recovery status incomplete')
    finally:
        left.close()
        right.close()
        if recovery is not None and recovery != 0 and status is None:
            # Only the fork creator may use this fallback to reap its direct child when
            # pidfd setup itself failed; this never admits a PID-only recovery claim.
            while True:
                try:
                    os.waitpid(recovery, 0)
                    break
                except InterruptedError:
                    continue
        for fd in (recovery_pidfd, child_pidfd, caller_pidfd):
            if fd is not None:
                os.close(fd)
