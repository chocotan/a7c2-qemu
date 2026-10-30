# SPDX-License-Identifier: MIT
"""Dedicated FCM1 transport. Receipts describe model/transport facts, never capture acceptance.

See report/functional-camera-bridge/README.md for ownership and shutdown contracts.
No TCP endpoints, media files, encoders, original-code patches, or logical guest
pointer dereferences are implemented here; actual model work goes through ctypes.
"""
from contextlib import contextmanager
import ctypes
import errno
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import socket
import stat
import struct
import threading
import time

import functional_face_source_snapshot as source_snapshot

BASE = Path(__file__).resolve().parent
RUNS = BASE / 'menu-runs'
PREFIX = 'functional-camera-broker'
PAGE, PAGE_COUNT, HEADER = 4096, 16, 512
MAILBOX_BYTES = PAGE * PAGE_COUNT
DATA = MAILBOX_BYTES - HEADER
MAX_RESULT = 64 * 1024 * 1024
PAYLOAD_DIRECTORY = 'functional-camera-data'
PAYLOAD_BUDGET = 512 * 1024 * 1024
PAYLOAD_FILE_LIMIT = 65536
MAGIC, VERSION = 0x314d4346, 1
IDLE, REQUEST, RESPONSE, CLOSED, DETACHED = range(5)
INIT, STATE, CONFIGURE, AUTOFOCUS, VDF_PATH, VDF_ZEBRA, VDF_LAYOUT, VDF_DISPLAY_CONFIG = 1, 2, 3, 4, 5, 6, 7, 8
BB_STARTUP_CONFIG, HISTOGRAM, AP_SOURCE_SNAPSHOT = 9, 10, source_snapshot.OP
VDF_BIT_WIDTH = 12
BIT_WIDTH_INPUT_BYTES, BIT_WIDTH_RESULT_BYTES = 8, 168
BB_INPUT_BYTES, BB_RESULT_BYTES = 32, 192
BB_0166_OBSERVED_INITIAL_BODY = bytes.fromhex('00010000000000000000000008000000070000000100000001000000')
HIST_INPUT_BYTES, HIST_RESULT_BYTES, HIST_BINS_OFFSET = 8, 1192, 168
LAYOUT_INITIAL_BODY = bytes.fromhex('07010100000000008002e0010000000000000000000000000300000000000000')
STILL, VIDEO_BEGIN, VIDEO_FRAME, VIDEO_END = 16, 32, 33, 34
READ_RESULT, RELEASE_RESULT, CANCEL = 64, 65, 66
OPS = {INIT, STATE, CONFIGURE, AUTOFOCUS, VDF_PATH, VDF_ZEBRA, VDF_LAYOUT, VDF_DISPLAY_CONFIG,
       BB_STARTUP_CONFIG, HISTOGRAM, AP_SOURCE_SNAPSHOT, VDF_BIT_WIDTH, STILL, VIDEO_BEGIN, VIDEO_FRAME,
       VIDEO_END, READ_RESULT, RELEASE_RESULT, CANCEL}
FNV_SEED = 0xcbf29ce484222325


def require(ok, text):
    if not ok:
        raise ValueError(text)


def fnv64(raw, value=FNV_SEED):
    for byte in raw:
        value = ((value ^ byte) * 0x100000001b3) & 0xffffffffffffffff
    return value


def u32(raw, offset):
    return int.from_bytes(raw[offset:offset + 4], 'little')


def u64(raw, offset):
    return int.from_bytes(raw[offset:offset + 8], 'little')


def origin(raw):
    return dict(producer_tid=u32(raw, 96), source=u32(raw, 100), destination=u32(raw, 104),
                command=u32(raw, 108), bytes=u32(raw, 112), fnv1a64=u64(raw, 120))


class PayloadRecords:
    """Exclusive run-local binary chunks, never a media writer or an RGB dump."""
    def __init__(self, root):
        self.root = Path(root).absolute()
        require(self.root.resolve() == self.root, 'Payload run path contains a symlink')
        self.root_fd = self.directory_fd = None
        self.used = self.files = 0
        self.poisoned = False
        try:
            self.root_fd = os.open(self.root, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC | os.O_NOFOLLOW)
            info = os.fstat(self.root_fd)
            require(info.st_uid == os.getuid() and not info.st_mode & 0o022, 'Untrusted payload run owner/mode')
            self.root_identity = (info.st_dev, info.st_ino)
            os.mkdir(PAYLOAD_DIRECTORY, 0o700, dir_fd=self.root_fd)
            self.directory_fd = os.open(PAYLOAD_DIRECTORY, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC | os.O_NOFOLLOW,
                                        dir_fd=self.root_fd)
            info = os.fstat(self.directory_fd)
            self.directory_identity = (info.st_dev, info.st_ino)
            self._check_directory()
        except BaseException:
            self.close()
            raise

    def _check_directory(self):
        root = self.root.lstat()
        require(stat.S_ISDIR(root.st_mode) and root.st_uid == os.getuid() and not root.st_mode & 0o022 and
                (root.st_dev, root.st_ino) == self.root_identity, 'Payload run directory replaced')
        info = os.stat(PAYLOAD_DIRECTORY, dir_fd=self.root_fd, follow_symlinks=False)
        pinned = os.fstat(self.directory_fd)
        require(stat.S_ISDIR(info.st_mode) and info.st_uid == os.getuid() and stat.S_IMODE(info.st_mode) == 0o700 and
                (info.st_dev, info.st_ino) == self.directory_identity == (pinned.st_dev, pinned.st_ino),
                'Payload directory replaced, linked or permissions changed')

    def retain(self, request, direction, raw, *, event, token=0, total=0, offset=0):
        require(not self.poisoned, 'Payload evidence store is poisoned')
        fd = None
        try:
            require(type(raw) is bytes and len(raw) <= MAX_RESULT and direction in ('in', 'out') and
                    type(event) is int and event > 0, 'Invalid payload bytes/direction/event')
            require(len(request) == HEADER and 0 < u64(request, 24) < 2**64 and
                    all(type(v) is int and 0 <= v < 2**64 for v in (token, total, offset)) and
                    (direction == 'in' or offset <= total),
                    'Invalid payload request/result binding')
            self._check_directory()
            require(self.used + len(raw) <= PAYLOAD_BUDGET and self.files < PAYLOAD_FILE_LIMIT,
                    'Payload evidence budget exhausted')
            name = f'{u64(request, 24):020d}-{direction}.bin'
            fd = os.open(name, os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC | os.O_NOFOLLOW,
                         0o600, dir_fd=self.directory_fd)
            self.used += len(raw)
            self.files += 1
            cursor = 0
            while cursor < len(raw):
                used = os.write(fd, raw[cursor:cursor + 1024 * 1024])
                require(0 < used <= min(1024 * 1024, len(raw) - cursor), 'Short/invalid payload write')
                cursor += used
            os.fsync(fd)
            before = os.fstat(fd)
            require(stat.S_ISREG(before.st_mode) and before.st_nlink == 1 and before.st_uid == os.getuid() and
                    stat.S_IMODE(before.st_mode) == 0o600 and before.st_size == len(raw), 'Payload file ownership/size differs')
            digest, value, cursor = hashlib.sha256(), FNV_SEED, 0
            while cursor < len(raw):
                count = min(1024 * 1024, len(raw) - cursor)
                chunk = os.pread(fd, count, cursor)
                require(len(chunk) == count and chunk == raw[cursor:cursor + count], 'Short/corrupt payload writeback')
                digest.update(chunk)
                value = fnv64(chunk, value)
                cursor += count
            require(not os.pread(fd, 1, len(raw)), 'Payload file has an unexpected tail')
            after = os.fstat(fd)
            identity = lambda st: (st.st_dev, st.st_ino, st.st_size, st.st_mtime_ns, st.st_ctime_ns, st.st_nlink)
            named = os.stat(name, dir_fd=self.directory_fd, follow_symlinks=False)
            require(identity(before) == identity(after) == identity(named), 'Payload changed while recording')
            self._check_directory()
            expected = hashlib.sha256(raw).hexdigest()
            require(digest.hexdigest() == expected and value == fnv64(raw), 'Payload writeback digest differs')
            return dict(path=PAYLOAD_DIRECTORY + '/' + name, source_kind='actual_hardware_transfer',
                        producer_event=event, sequence=u64(request, 24), opcode=u32(request, 32),
                        model_instance=u64(request, 16), origin=origin(request), direction=direction,
                        token=token, total=total, offset=offset, bytes=len(raw), sha256=expected,
                        fnv1a64=value, writeback_sha256=digest.hexdigest(), writeback_verified=True,
                        device=after.st_dev, inode=after.st_ino, mtime_ns=after.st_mtime_ns, ctime_ns=after.st_ctime_ns)
        except BaseException:
            self.poisoned = True
            raise
        finally:
            if fd is not None:
                os.close(fd)

    def verify(self, reference, raw):
        require(not self.poisoned, 'Payload evidence store is poisoned')
        fd = None
        try:
            self._check_directory()
            relative = Path(reference['path'])
            require(relative.parent == Path(PAYLOAD_DIRECTORY) and
                    re.fullmatch(r'[0-9]{20}-(?:in|out)\.bin', relative.name) and
                    type(raw) is bytes and len(raw) == reference['bytes'] <= MAX_RESULT,
                    'Invalid payload reference')
            fd = os.open(relative.name, os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW, dir_fd=self.directory_fd)
            before = os.fstat(fd)
            identity = lambda st: (st.st_dev, st.st_ino, st.st_size, st.st_mtime_ns, st.st_ctime_ns)
            expected = tuple(reference[key] for key in ('device', 'inode', 'bytes', 'mtime_ns', 'ctime_ns'))
            require(stat.S_ISREG(before.st_mode) and before.st_nlink == 1 and before.st_uid == os.getuid() and
                    stat.S_IMODE(before.st_mode) == 0o600 and identity(before) == expected,
                    'Retained payload file identity differs')
            actual = os.pread(fd, len(raw) + 1, 0)
            require(actual == raw and hashlib.sha256(actual).hexdigest() == reference['sha256'] ==
                    reference['writeback_sha256'] and fnv64(actual) == reference['fnv1a64'] and
                    identity(os.fstat(fd)) == expected, 'Retained payload short/corrupt readback')
            self._check_directory()
        except BaseException:
            self.poisoned = True
            raise
        finally:
            if fd is not None:
                os.close(fd)

    def close(self):
        for key in ('directory_fd', 'root_fd'):
            fd = getattr(self, key, None)
            if fd is not None:
                os.close(fd)
                setattr(self, key, None)


def validate_mailbox(mailbox):
    require(type(mailbox) is dict and set(mailbox) == {'phys0', 'nonce', 'pid', 'pages'},
            'Exact phys0/nonce/pid/pages mailbox binding required')
    pages = mailbox['pages']
    require(type(pages) in (list, tuple) and len(pages) == PAGE_COUNT and
            all(type(v) is int and 0x400000000 <= v <= 0x540000000 - PAGE and not v % PAGE for v in pages) and
            len(set(pages)) == PAGE_COUNT and mailbox['phys0'] == pages[0], 'Invalid/distinct physical mailbox pages')
    require(type(mailbox['nonce']) is int and 0 < mailbox['nonce'] < 2**64 and
            type(mailbox['pid']) is int and 1 < mailbox['pid'] < 2**31, 'Invalid mailbox nonce/PID')
    return dict(phys0=pages[0], nonce=mailbox['nonce'], pid=mailbox['pid'], pages=list(pages))


def validate_header(raw, mailbox):
    require(len(raw) == HEADER, 'Short mailbox header')
    require(u32(raw, 0) == MAGIC and u32(raw, 4) == VERSION and
            u32(raw, 8) == mailbox['pid'] and u64(raw, 16) == mailbox['nonce'], 'Mailbox magic/version/PID/nonce differs')
    require([u64(raw, 128 + n * 8) for n in range(PAGE_COUNT)] == mailbox['pages'], 'Mailbox PFN list changed')
    flags = u32(raw, 52)
    require(raw[256:] == bytes(256) and raw[116:120] == bytes(4) and flags in (0, 1),
            'Mailbox reserved bytes/flags are nonzero')
    if flags:
        require(u32(raw, 32) in (AP_SOURCE_SNAPSHOT, READ_RESULT, RELEASE_RESULT, CANCEL),
                'API40 source flags are invalid for this opcode')
        source_snapshot.validate_origin(raw)
    require(u32(raw, 12) in (IDLE, REQUEST, RESPONSE, CLOSED, DETACHED), 'Unknown mailbox status')


def bb_startup_input_valid(data):
    if len(data) != BB_INPUT_BYTES:
        return False
    command, count = struct.unpack_from('<2H', data)
    body = data[4:]
    if command == 0x111:
        return count == 28 and body == b'\x00\x00\x0f\x02' + bytes(24)
    if command == 0x166:
        return count == 28 and body in (b'\x00\x01' + bytes(26), BB_0166_OBSERVED_INITIAL_BODY)
    if command == 0x167:
        return count == 2 and body[0] in (0, 1) and body[1:] == bytes(27)
    if command == 0x15f:
        return count == 4 and body == bytes(28)
    if command == 0x128:
        return count == 12 and body[:4] == b'\x00\x01\x00\x00' and body[8:] == bytes(20) and u32(body, 4) in (
            60, 50, 40, 30, 20, 10, 9, 8, 7, 6, 5, 4, 3, 2, 1)
    return False


def validate_request(raw, data, mailbox, previous):
    validate_header(raw, mailbox)
    require(u32(raw, 12) == REQUEST and 0 < u64(raw, 24) == previous + 1 < 2**64,
            'Request sequence is missing, replayed, or reordered')
    op, size, capacity = u32(raw, 32), u32(raw, 36), u32(raw, 40)
    require(op in OPS and size <= DATA and size == len(data) and capacity <= DATA,
            'Unknown opcode or out-of-bounds request/capacity')
    require(raw[44:52] == bytes(8) and raw[64:96] == bytes(32), 'Uncleared response metadata')
    require(0 < u32(raw, 96) < 2**31 and u32(raw, 100) and u32(raw, 104) and u32(raw, 112),
            'Missing original-request origin/producer TID')
    require(fnv64(data) == u64(raw, 56), 'Request FNV differs')
    sizes = {INIT: (0, 48), STATE: (0,), CONFIGURE: (48,), AUTOFOCUS: (32,), VDF_PATH: (16,), VDF_ZEBRA: (8,), VDF_LAYOUT: (32,), VDF_DISPLAY_CONFIG: (16,),
             BB_STARTUP_CONFIG: (BB_INPUT_BYTES,), HISTOGRAM: (HIST_INPUT_BYTES,), VDF_BIT_WIDTH: (BIT_WIDTH_INPUT_BYTES,),
             AP_SOURCE_SNAPSHOT: range(360, 1177, 8), STILL: (16, 144),
             VIDEO_BEGIN: (48,), VIDEO_FRAME: (0,), VIDEO_END: (0,), READ_RESULT: (24,),
             RELEASE_RESULT: (16,), CANCEL: (0,)}
    require(size in sizes[op], 'Opcode request size differs')
    require(op != AP_SOURCE_SNAPSHOT or u32(raw, 52) == 1, 'Snapshot requires actual API40 origin flag')
    if op == READ_RESULT:
        require(u32(data, 20) == 0 and 0 < u32(data, 16) <= capacity and u64(data, 0),
                'Invalid retained-result read request')
    if op == RELEASE_RESULT:
        require(u64(data, 0), 'Zero retained-result token')
    return op, capacity


def validate_run(run):
    root = Path(run).absolute()
    require(root.resolve() == root and root.parent == RUNS.resolve(), 'Run must be a direct nonsymlink menu-runs child')
    info = root.lstat()
    require(stat.S_ISDIR(info.st_mode) and info.st_uid == os.getuid() and not info.st_mode & 0o022,
            'Untrusted run directory')
    return root, (info.st_dev, info.st_ino)


def process_identity(pid):
    require(type(pid) is int and 1 < pid < 2**31, 'Invalid owner/QEMU PID')
    proc = Path('/proc') / str(pid)
    require(proc.stat().st_uid == os.getuid(), 'Process UID differs')
    fields = (proc / 'stat').read_text().rsplit(')', 1)[1].split()
    require(fields[0] != 'Z', 'Process is a zombie')
    return dict(pid=pid, starttime=int(fields[19]), ppid=int(fields[1]), exe=os.readlink(proc / 'exe'))


def checked_socket(root, path, qemu_pid):
    path = Path(path).absolute()
    require(path.parent == root and path.resolve() == path, 'Socket must be a nonsymlink direct run child')
    info = path.lstat()
    require(stat.S_ISSOCK(info.st_mode) and info.st_uid == os.getuid() and stat.S_IMODE(info.st_mode) == 0o600,
            'Socket must be owned and mode 0600')
    proc = Path('/proc') / str(qemu_pid)
    names = (str(path), '/out/' + path.name)
    rows = [line.split() for line in (proc / 'net/unix').read_text().splitlines()[1:]]
    matches = [row for row in rows if len(row) == 8 and row[7] in names and
               int(row[3], 16) & 0x10000 and row[4] == '0001' and row[5] == '01']
    require(len(matches) == 1, 'No unique QEMU Unix listener binding')
    links = set()
    for fd in (proc / 'fd').iterdir():
        try:
            links.add(os.readlink(fd))
        except FileNotFoundError:
            pass
    require('socket:[' + matches[0][6] + ']' in links, 'QEMU does not own this Unix listener')
    # A preceding debugger must finish before this client is allowed to connect.
    require(not any(len(row) == 8 and row[7] in names and row[5] == '03' for row in rows),
            'Unix endpoint already has a connected client')
    if matches[0][7].startswith('/out/'):
        mounted = (proc / 'root/out').stat()
        run_info = root.stat()
        require((mounted.st_dev, mounted.st_ino) == (run_info.st_dev, run_info.st_ino), 'QEMU /out is a different run')
    return dict(path=str(path), device=info.st_dev, inode=info.st_ino, listener_inode=int(matches[0][6]))


def file_digest_fd(fd):
    before = os.fstat(fd)
    require(stat.S_ISREG(before.st_mode) and before.st_uid == os.getuid() and not before.st_mode & 0o022 and
            0 < before.st_size <= 256 * 1024 * 1024, 'Untrusted executable/library')
    digest = hashlib.sha256()
    offset = 0
    while offset < before.st_size:
        data = os.pread(fd, min(1024 * 1024, before.st_size - offset), offset)
        require(data, 'Short executable/library read')
        offset += len(data)
        digest.update(data)
    after = os.fstat(fd)
    identity = lambda st: (st.st_dev, st.st_ino, st.st_size, st.st_mtime_ns, st.st_ctime_ns)
    require(identity(before) == identity(after), 'Executable/library changed while hashing')
    return digest.hexdigest(), identity(after)


def owned_config(run, owner_pid, qemu_pid, qemu_sha256, gdb_socket, qmp_socket):
    root, run_identity = validate_run(run)
    require(isinstance(qemu_sha256, str) and re.fullmatch('[0-9a-f]{64}', qemu_sha256), 'Explicit accepted QEMU SHA256 required')
    owner, qemu = process_identity(owner_pid), process_identity(qemu_pid)
    require(Path(qemu['exe']).name == 'qemu-system-aarch64', 'Actual executable is not qemu-system-aarch64')
    ancestor = qemu
    for _ in range(32):
        if ancestor['ppid'] == owner_pid:
            break
        require(ancestor['ppid'] > 1, 'QEMU is not an owner descendant')
        ancestor = process_identity(ancestor['ppid'])
    else:
        raise ValueError('QEMU owner ancestor bound exceeded')
    fd = os.open(f'/proc/{qemu_pid}/exe', os.O_RDONLY | os.O_CLOEXEC)
    try:
        actual_sha, exe_identity = file_digest_fd(fd)
    finally:
        os.close(fd)
    require(actual_sha == qemu_sha256, 'Running QEMU executable SHA256 differs from accepted build')
    gdb = checked_socket(root, gdb_socket, qemu_pid)
    qmp = checked_socket(root, qmp_socket, qemu_pid)
    require(gdb['inode'] != qmp['inode'], 'GDB and QMP must be separate sockets')
    return dict(run=str(root), run_identity=run_identity, owner=owner, qemu=qemu,
                qemu_sha256=actual_sha, exe_identity=exe_identity, gdb=gdb, qmp=qmp)


def revalidate(config):
    root, identity = validate_run(config['run'])
    require(identity == tuple(config['run_identity']), 'Run directory replaced')
    for key in ('owner', 'qemu'):
        require(process_identity(config[key]['pid']) == config[key], 'Bound process identity changed')
    st = Path(f"/proc/{config['qemu']['pid']}/exe").stat()
    require((st.st_dev, st.st_ino, st.st_size, st.st_mtime_ns, st.st_ctime_ns) == tuple(config['exe_identity']),
            'Running QEMU executable identity changed')
    for key in ('gdb', 'qmp'):
        bound = config[key]
        st = Path(bound['path']).lstat()
        require(stat.S_ISSOCK(st.st_mode) and stat.S_IMODE(st.st_mode) == 0o600 and st.st_uid == os.getuid() and
                (st.st_dev, st.st_ino) == (bound['device'], bound['inode']), 'Bound Unix socket replaced')
    return root


def connect_unix(stream, path):
    path = Path(path)
    require(path.is_absolute(), 'Unix endpoint must be absolute')
    directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC | os.O_NOFOLLOW)
    try:
        address = f'/proc/self/fd/{directory}/{path.name}'
        require(len(os.fsencode(address)) < 108, 'Unix endpoint basename exceeds socket limit')
        stream.connect(address)
    finally:
        os.close(directory)


class RSP:
    """Bounded synchronous Unix RSP; only supported/physical-mode/memory/detach commands."""
    def __init__(self, path, timeout=2.0, *, expected_pid=None):
        self.timeout = timeout
        self.socket = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.socket.settimeout(timeout)
        self.buffer = bytearray()
        self.packet_size = 1024
        self.window_deadline = None
        try:
            connect_unix(self.socket, path)
            if expected_pid is not None:
                peer_pid, peer_uid, _ = struct.unpack('3i', self.socket.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12))
                require(peer_pid == expected_pid and peer_uid == os.getuid(), 'RSP peer process differs from bound QEMU')
            supported = self.request(b'qSupported')
            fields = supported.split(b';')
            values = [int(field.split(b'=', 1)[1], 16) for field in fields if field.startswith(b'PacketSize=')]
            require(len(values) == 1 and 128 <= values[0] <= 1024 * 1024, 'Missing/invalid RSP PacketSize')
            self.packet_size = min(values[0], 65536)
        except BaseException:
            self.close()
            raise

    def _byte(self, deadline):
        if not self.buffer:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError('RSP packet deadline')
            self.socket.settimeout(remaining)
            chunk = self.socket.recv(8192)
            if not chunk:
                raise EOFError('RSP socket closed')
            self.buffer.extend(chunk)
        byte = self.buffer[0]
        del self.buffer[0]
        return byte

    def _receive(self, deadline):
        while True:
            first = self._byte(deadline)
            if first in (ord('+'), ord('-')):
                return bytes((first,))
            require(first == ord('$'), 'Unexpected RSP framing byte')
            encoded = bytearray()
            while True:
                byte = self._byte(deadline)
                if byte == ord('#'):
                    break
                encoded.append(byte)
                require(len(encoded) <= max(self.packet_size, 4096), 'Oversized RSP packet')
            check = bytes((self._byte(deadline), self._byte(deadline)))
            require(re.fullmatch(b'[0-9a-fA-F]{2}', check) and int(check, 16) == sum(encoded) % 256,
                    'RSP checksum mismatch')
            self.socket.sendall(b'+')
            decoded = bytearray()
            index = 0
            while index < len(encoded):
                byte = encoded[index]
                if byte == ord('}'):
                    index += 1
                    require(index < len(encoded), 'Truncated RSP escape')
                    decoded.append(encoded[index] ^ 0x20)
                elif byte == ord('*'):
                    index += 1
                    require(decoded and index < len(encoded) and encoded[index] >= 32, 'Invalid RSP run length')
                    decoded.extend(decoded[-1:] * (encoded[index] - 29))
                else:
                    decoded.append(byte)
                require(len(decoded) <= max(self.packet_size, 4096), 'Expanded RSP packet exceeds bound')
                index += 1
            return bytes(decoded)

    def request(self, payload):
        require(len(payload) <= self.packet_size and not any(c in payload for c in b'$#}*'), 'Invalid/oversized RSP request')
        frame = b'$' + payload + b'#' + f'{sum(payload) % 256:02x}'.encode('ascii')
        deadline = time.monotonic() + self.timeout
        if self.window_deadline is not None and payload != b'Qqemu.PhyMemMode:0':
            deadline = min(deadline, self.window_deadline)
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError('RSP copy-window deadline')
        self.socket.settimeout(remaining)
        self.socket.sendall(frame)
        retries = 0
        while True:
            reply = self._receive(deadline)
            if reply == b'+':
                continue
            if reply == b'-':
                retries += 1
                require(retries <= 2, 'RSP repeatedly rejected packet')
                self.socket.sendall(frame)
                continue
            if reply[:1] in (b'T', b'S') and payload != b'?':
                continue  # QMP stop can generate an asynchronous stop reply.
            require(not (len(reply) == 3 and reply[:1] == b'E'), 'QEMU RSP error: ' + repr(reply))
            return reply

    def mode(self, physical):
        require(self.request(b'Qqemu.PhyMemMode:' + (b'1' if physical else b'0')) == b'OK',
                'QEMU debug physical-mode operation refused')

    def read(self, address, size):
        result = bytearray()
        while len(result) < size:
            amount = min(size - len(result), self.packet_size // 2)
            reply = self.request(f'm{address + len(result):x},{amount:x}'.encode('ascii'))
            require(len(reply) == amount * 2 and re.fullmatch(b'[0-9a-fA-F]*', reply),
                    f'Short/nonhex RSP memory read: expected_bytes={amount} raw={reply[:256]!r}')
            result.extend(bytes.fromhex(reply.decode('ascii')))
        return bytes(result)

    def write(self, address, data):
        offset = 0
        while offset < len(data):
            amount = min(len(data) - offset, (self.packet_size - 48) // 2)
            payload = f'M{address + offset:x},{amount:x}:'.encode('ascii') + data[offset:offset + amount].hex().encode('ascii')
            require(self.request(payload) == b'OK', 'RSP memory write refused')
            offset += amount

    def close(self):
        # D unconditionally resumes some QEMU builds, including a paused SDSTOP.
        # No breakpoints/registers were changed; disconnect preserves stop state.
        try:
            self.socket.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        self.socket.close()


class QMP:
    def __init__(self, path, timeout=2.0, *, expected_pid=None):
        self.timeout, self.serial = timeout, 0
        self.socket = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.socket.settimeout(timeout)
        self.buffer = bytearray()
        try:
            connect_unix(self.socket, path)
            if expected_pid is not None:
                peer_pid, peer_uid, _ = struct.unpack('3i', self.socket.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12))
                require(peer_pid == expected_pid and peer_uid == os.getuid(), 'QMP peer process differs from bound QEMU')
            require('QMP' in self._line(time.monotonic() + timeout), 'Missing QMP greeting')
            self.execute('qmp_capabilities')
        except BaseException:
            self.close()
            raise

    def _line(self, deadline):
        while b'\n' not in self.buffer:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError('QMP response deadline')
            self.socket.settimeout(remaining)
            chunk = self.socket.recv(8192)
            if not chunk:
                raise EOFError('QMP socket closed')
            self.buffer.extend(chunk)
            require(len(self.buffer) <= 4 * 1024 * 1024, 'QMP line exceeds bound')
        line, _, self.buffer = self.buffer.partition(b'\n')
        require(len(line) <= 4 * 1024 * 1024, 'QMP line exceeds bound')
        value = json.loads(line)
        require(type(value) is dict, 'Nonobject QMP message')
        return value

    def execute(self, command, arguments=None):
        require(command in ('qmp_capabilities', 'query-status', 'stop', 'cont', 'human-monitor-command'),
                'Unapproved QMP command')
        if command == 'human-monitor-command':
            require(type(arguments) is dict and set(arguments) == {'command-line'} and
                    type(arguments['command-line']) is str, 'Invalid HMP arguments')
            line = arguments['command-line']
            match = re.fullmatch(r'xp /([1-9][0-9]{0,5})bx 0x([0-9a-f]{1,16})', line)
            require(line in ('cpu 0', 'info mtree -f -o') or match and
                    int(match[1]) <= max(source_snapshot.UNITS.values()) and
                    int(match[2], 16) + int(match[1]) <= 2**64, 'Unapproved HMP command/span')
        else:
            require(arguments is None, 'Unexpected QMP arguments')
        self.serial += 1
        serial = self.serial
        message = dict(execute=command, id=serial)
        if arguments is not None:
            message['arguments'] = arguments
        self.socket.sendall(json.dumps(message).encode('ascii') + b'\n')
        deadline = time.monotonic() + self.timeout
        for _ in range(256):
            value = self._line(deadline)
            if 'event' in value:
                continue
            require(value.get('id') == serial and 'return' in value and 'error' not in value,
                    'QMP command failed/mismatched: ' + repr(value)[:2048])
            return value['return']
        raise ValueError('QMP event flood')

    def status(self):
        value = self.execute('query-status')
        require(type(value) is dict and type(value.get('running')) is bool and value.get('status') in
                ('running', 'paused', 'prelaunch', 'debug', 'suspended'), 'QEMU is not in an operable run state')
        require(value['running'] == (value['status'] == 'running'), 'Contradictory QMP run state')
        return value

    def close(self):
        self.socket.close()


class ExecResult(ctypes.Structure):
    _fields_ = [('token', ctypes.c_uint64), ('total', ctypes.c_uint64),
                ('offset', ctypes.c_uint64), ('used', ctypes.c_size_t)]


class ProofCounts(ctypes.Structure):
    _fields_ = [(key, ctypes.c_uint64) for key in
                ('rendered', 'consumed', 'jpeg_encoded', 'video_encoded', 'retired')]


class FrameProof(ctypes.Structure):
    # Exact fixed-width host-only fcam_frame_proof v1 (376 bytes), no pointers.
    _fields_ = [(key, ctypes.c_uint64) for key in (
        'version', 'struct_bytes', 'serial', 'model_instance', 'model_lifetime', 'owner_pid', 'opcode', 'consumer_kind',
        'config_generation', 'frame_generation', 'lease_generation', 'packet_generation',
        'width', 'height', 'stride', 'active_bytes',
        'source_fnv1a64', 'consumer_before_fnv1a64', 'consumer_after_fnv1a64',
        'render_observed', 'consumer_entered', 'consumer_returned', 'encoder_consumed', 'retired',
        'source_state', 'consumer_before_state', 'consumer_after_state', 'final_state')]
    _fields_ += [(key, ctypes.c_int64) for key in
                 ('render_status', 'consumer_status', 'retire_status', 'operation_status')]
    _fields_ += [('before', ProofCounts), ('after', ProofCounts)]
    _fields_ += [(key, ctypes.c_uint64) for key in
                 ('encoded_bytes', 'encoded_fnv1a64', 'result_bytes', 'result_fnv1a64', 'result_token')]


class Core:
    """Hash-bound actual core library; no independent rendering/codec implementation."""
    def __init__(self, library, expected_sha256):
        path = Path(library).absolute()
        require(path.resolve() == path and re.fullmatch('[0-9a-f]{64}', expected_sha256 or ''), 'Explicit nonsymlink core library and accepted SHA256 required')
        self.fd = os.open(path, os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW)
        self.model = self.instance = self.vdf_route = None
        try:
            digest, identity = file_digest_fd(self.fd)
            require(digest == expected_sha256, 'Actual core library SHA256 differs from accepted build')
            self.library = ctypes.CDLL(f'/proc/self/fd/{self.fd}', mode=os.RTLD_NOW | os.RTLD_LOCAL, use_errno=True)
            require(file_digest_fd(self.fd) == (digest, identity), 'Core library changed while loading')
            self.digest = digest
            lib = self.library
            lib.fcam_model_create.argtypes, lib.fcam_model_create.restype = [ctypes.c_uint64], ctypes.c_void_p
            lib.fcam_model_destroy.argtypes, lib.fcam_model_destroy.restype = [ctypes.c_void_p], None
            lib.fcam_model_request.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_void_p,
                                               ctypes.c_size_t, ctypes.c_void_p, ctypes.c_size_t,
                                               ctypes.POINTER(ExecResult)]
            lib.fcam_model_request.restype = ctypes.c_int
            lib.fcam_model_proof_snapshot.argtypes = [ctypes.c_void_p, ctypes.POINTER(FrameProof), ctypes.c_size_t]
            lib.fcam_model_proof_snapshot.restype = ctypes.c_int
        except BaseException:
            os.close(self.fd)
            raise

    def execute(self, instance, op, data, capacity):
        require(type(instance) is int and 0 < instance < 2**64 and op in OPS and op != AP_SOURCE_SNAPSHOT and type(data) is bytes and
                len(data) <= DATA and type(capacity) is int and 0 <= capacity <= DATA, 'Invalid core call boundary')
        if self.model is None:
            require(op == INIT, 'First actual core request must be INIT')
            ctypes.set_errno(0)
            self.model = self.library.fcam_model_create(instance)
            if not self.model:
                return -(ctypes.get_errno() or errno.EIO), b'', ExecResult()
            self.instance = instance
        require(instance == self.instance, 'Actual C model instance differs from mailbox nonce')
        incoming = ctypes.create_string_buffer(data, max(1, len(data)))
        output = ctypes.create_string_buffer(max(1, capacity))
        result = ExecResult()
        error = self.library.fcam_model_request(self.model, op, incoming, len(data), output, capacity, ctypes.byref(result))
        require(-4095 <= error <= 0, 'Core returned an invalid errno')
        if error:
            require(not any((result.token, result.total, result.offset, result.used)), 'Failed core request returned uncommitted result metadata')
            return error, b'', result
        require(result.used <= capacity and result.total <= MAX_RESULT and result.offset <= result.total,
                'Core returned out-of-bounds result')
        if result.token:
            require(result.token < source_snapshot.TOKEN_BASE, 'Core result overlaps reserved source token namespace')
            chunk_capacity = min(capacity, u32(data, 16)) if op == READ_RESULT else capacity
            require(result.total and result.used and result.used == min(chunk_capacity, result.total - result.offset),
                    'Core retained result has a short chunk or invalid bounds')
        else:
            require(not result.total and not result.offset, 'Core returned tokenless retained bytes')
        actual = bytes(output.raw[:result.used])
        if op in (INIT, STATE, CONFIGURE, VIDEO_BEGIN, CANCEL):
            require(result.used == 128 and not result.token and u32(actual, 0) == VERSION and
                    u64(actual, 48) == instance and actual[120:] == bytes(8), 'Actual core state identity/size differs')
        elif op in (VDF_PATH, VDF_ZEBRA, VDF_LAYOUT, VDF_DISPLAY_CONFIG, BB_STARTUP_CONFIG, HISTOGRAM, VDF_BIT_WIDTH):
            expected_bytes = {VDF_PATH: 160, VDF_ZEBRA: 168, VDF_LAYOUT: 192, VDF_DISPLAY_CONFIG: 176,
                              BB_STARTUP_CONFIG: BB_RESULT_BYTES, HISTOGRAM: HIST_RESULT_BYTES,
                              VDF_BIT_WIDTH: BIT_WIDTH_RESULT_BYTES}[op]
            require(result.used == expected_bytes and not result.token and u32(actual, 0) == VERSION and
                    u32(actual, 4) == expected_bytes and u64(actual, 8) == instance and
                    u64(actual, 40) == fnv64(data) and actual[120:128] == bytes(8),
                    'Actual core VDF identity/config differs')
            route = actual[128:144]
            if op == VDF_PATH:
                require(len(data) == 16 and route == data, 'Actual VDF route readback differs')
            else:
                if op == VDF_BIT_WIDTH:
                    require(data == bytes(BIT_WIDTH_INPUT_BYTES) and actual[160:] == data,
                            'Actual software bit-width0 RGB888 configuration/readback differs')
                elif op == VDF_ZEBRA:
                    require(len(data) == 8 and data[1] == 0 and data[5:] == bytes(3) and actual[160:] == data,
                            'Actual Zebra disabled configuration/readback differs')
                elif op == VDF_LAYOUT:
                    require(data == LAYOUT_INITIAL_BODY and actual[160:] == data and
                            (u32(actual, 72), u32(actual, 76), u32(actual, 80)) == (640, 480, 1920),
                            'Actual layout software policy/configuration/readback differs')
                elif op == BB_STARTUP_CONFIG:
                    require(bb_startup_input_valid(data) and actual[160:] == data,
                            'Actual BB initial/neutral configuration/readback differs')
                elif op == HISTOGRAM:
                    bins = actual[HIST_BINS_OFFSET:]
                    require(data == bytes.fromhex('4801040001010000') and actual[160:168] == data and
                            len(bins) == 1024 and all(max(bins[n:n + 256]) == 255 for n in range(0, 1024, 256)),
                            'Actual first-frame software histogram/readback differs')
                else:
                    require(len(data) == 16 and actual[160:] == data,
                            'Actual display configuration/readback differs')
                    command, body_bytes = struct.unpack_from('<2I', data)
                    body = data[8:]
                    peaking = (command == 0x152 and body_bytes == 8 and body[0] == 3 and body[1] == 0 and
                               body[2] <= 2 and body[3] in (0, 10, 40) and body[4] == 0 and
                               body[5:] in (bytes((81, 90, 240)), bytes((210, 16, 146)),
                                            bytes((29, 255, 83)), bytes((235, 128, 128))))
                    require(peaking or command == 0x162 and body_bytes == 2 and body == bytes(8) or
                            command == 0x141 and body_bytes == 0 and body == bytes(8),
                            'Actual display disabled-feature policy differs')
                committed_route = getattr(self, 'vdf_route', None)
                require(route == (committed_route if committed_route is not None else b'\x00\x01\x01' + bytes(13)),
                        'VDF configuration operation changed the committed VDF route')
                if op in (BB_STARTUP_CONFIG, HISTOGRAM, VDF_BIT_WIDTH):
                    require((u32(actual, 72), u32(actual, 76), u32(actual, 80)) == (640, 480, 1920),
                            'Actual BB/histogram/bit-width supported RGB geometry differs')
                if op in (VDF_LAYOUT, VDF_DISPLAY_CONFIG, BB_STARTUP_CONFIG, HISTOGRAM, VDF_BIT_WIDTH):
                    require(committed_route is not None and route[:3] == b'\x01\x05\x05',
                            'Display configuration requires a committed active VDF route')
            require(route[:3] in (b'\x01\x05\x05', b'\x00\x01\x01') and route[4] <= 2 and
                    route[13:] == bytes(3), 'Actual core accepted an unsupported VDF route')
            active = route[0] == 1
            result_class = 7 if op == VDF_BIT_WIDTH else 5 if op == BB_STARTUP_CONFIG else 6 if op == HISTOGRAM else int(active)
            require(u32(actual, 84) == 0x90590819 and u32(actual, 88) == u32(actual, 92) == 1 and
                    u32(actual, 96) == result_class and u32(actual, 100) == int(active) and
                    u32(actual, 104) == u32(actual, 108) == 1 and
                    u32(actual, 112) == u32(actual, 116) == int(active) and
                    u64(actual, 16) == u64(actual, 152) + 1 and
                    u64(actual, 24) == u64(actual, 144) + int(active), 'Actual core VDF completion differs')
            if active:
                width, height, stride = (u32(actual, offset) for offset in (72, 76, 80))
                require(width > 0 and height > 0 and stride == width * 3 and
                        u64(actual, 64) == width * height * 3 and u64(actual, 32) > 0 and
                        u64(actual, 48) == u64(actual, 56), 'Actual VDF sink content/lease differs')
            else:
                require(actual[32:40] == bytes(8) and actual[48:72] == bytes(24),
                        'Disabled VDF route claimed frame consumption')
            self.vdf_route = route
        elif op == AUTOFOCUS:
            require(result.used == 32 and not result.token and actual[24:] == bytes(8), 'Actual core AF result differs')
        elif op == RELEASE_RESULT:
            require(not result.used and not result.token, 'Actual core release returned unexpected data')
        elif op in (STILL, READ_RESULT):
            require(result.token, 'Actual core encoded/read result lacks a retained token')
        elif op in (VIDEO_FRAME, VIDEO_END):
            require(not result.used or result.token, 'Actual core video result lacks a retained token')
        return 0, actual, result

    def proof_snapshot(self):
        if self.model is None:
            return None
        proof = FrameProof()
        require(ctypes.sizeof(proof) == 376, 'Host proof POD layout differs')
        error = self.library.fcam_model_proof_snapshot(self.model, ctypes.byref(proof), ctypes.sizeof(proof))
        require(error == 0, 'Actual read-only C proof snapshot failed: ' + str(error))
        require(proof.version == 1 and proof.struct_bytes == ctypes.sizeof(proof) and
                proof.model_instance == self.instance and proof.owner_pid == os.getpid() and proof.model_lifetime > 0,
                'Actual C proof identity/layout differs')
        value = {}
        for key, _ in proof._fields_:
            field = getattr(proof, key)
            value[key] = {name: getattr(field, name) for name, _ in field._fields_} if isinstance(field, ProofCounts) else field
        return value

    def destroy_model(self):
        if self.model:
            self.library.fcam_model_destroy(self.model)
            self.model = self.instance = self.vdf_route = None

    def close(self):
        self.destroy_model()
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None


class Broker:
    def __init__(self, run, owner_pid, mailbox, library, *, qemu_pid, qemu_sha256,
                 library_sha256, gdb_socket, qmp_socket, coordination_lock,
                 debugger_quiesced, resume_allowed, seconds=300.0, io_timeout=2.0):
        require(debugger_quiesced is True, 'Parent must finish the old debugger shutdown first')
        require(hasattr(coordination_lock, 'acquire') and hasattr(coordination_lock, 'release') and callable(resume_allowed),
                'Parent stop/resume coordination lock and resume_allowed callback required')
        require(0 < seconds <= 3600 and 0.05 <= io_timeout <= 5.0, 'Invalid broker phase/I/O deadline')
        self.config = owned_config(run, owner_pid, qemu_pid, qemu_sha256, gdb_socket, qmp_socket)
        self.mailbox = validate_mailbox(mailbox)
        self.root = Path(self.config['run'])
        self.lock, self.resume_allowed = coordination_lock, resume_allowed
        self.seconds, self.io_timeout = seconds, io_timeout
        self.done, self.ready = threading.Event(), threading.Event()
        self.cleanup, self.start_error = None, None
        self.rsp = self.qmp = None
        self.phys_restored, self.acknowledged = True, False
        self.sequence, self.event_serial = 0, 0
        self.cleaning, self.log_errors = False, []
        self.last_response = None
        self.pending_payloads = self.transfer = self.last_frame = None
        self.source_provider = source_snapshot.Snapshot(all(os.environ.get(key) == source_snapshot.PROFILE
            for key in ('MENU_FUNCTIONAL_CAMERA', 'A7C2_FUNCTIONAL_CAMERA')))
        self.core = self.events = self.lease = self.payloads = None
        self.thread = None
        try:
            self.lease = os.open(self.root / (PREFIX + '.lock'), os.O_RDWR | os.O_CREAT | os.O_CLOEXEC | os.O_NOFOLLOW, 0o600)
            lease_info = os.fstat(self.lease)
            require(stat.S_ISREG(lease_info.st_mode) and lease_info.st_uid == os.getuid() and stat.S_IMODE(lease_info.st_mode) == 0o600,
                    'Untrusted debugger lease')
            fcntl.flock(self.lease, fcntl.LOCK_EX | fcntl.LOCK_NB)
            self.core = Core(library, library_sha256)
            event_fd = os.open(self.root / (PREFIX + '-receipts.jsonl'), os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC | os.O_NOFOLLOW, 0o600)
            self.events = os.fdopen(event_fd, 'w', encoding='ascii', buffering=1)
            self.payloads = PayloadRecords(self.root)
            self.emit('binding', config=self.config, mailbox=self.mailbox, actual_core_sha256=self.core.digest,
                      payload_policy=dict(directory=PAYLOAD_DIRECTORY, per_file_bytes=MAX_RESULT,
                                          total_bytes=PAYLOAD_BUDGET, max_files=PAYLOAD_FILE_LIMIT,
                                          source_kind='actual_hardware_transfer'), native_acceptance=False)
            self.thread = threading.Thread(target=self._run, name=PREFIX, daemon=True)
            self.thread.start()
            if not self.ready.wait(5 * io_timeout + 2):
                raise TimeoutError('Functional-camera debugger attach deadline')
            if self.start_error:
                raise self.start_error
        except BaseException as error:
            self.done.set()
            if self.thread is None:
                if self.core:
                    self.core.close()
                if self.events:
                    self.events.close()
                if self.payloads:
                    self.payloads.close()
                if self.lease is not None:
                    os.close(self.lease)
                    self.lease = None
            else:
                error.functional_camera_broker = self
                error.functional_camera_cleanup = self.stop()
            raise

    def emit(self, kind, **fields):
        self.event_serial += 1
        value = dict(event=self.event_serial, kind=kind, monotonic_ns=time.monotonic_ns(),
                     model_instance=self.mailbox['nonce'], **fields)
        try:
            line = json.dumps(value, separators=(',', ':'), sort_keys=True) + '\n'
            require(self.events.write(line) == len(line), 'Short broker receipt write')
            self.events.flush()
        except (OSError, ValueError) as error:
            self.log_errors.append(str(error))
            if not self.cleaning:
                raise
        return value

    @contextmanager
    def coordinated(self):
        require(self.lock.acquire(timeout=self.io_timeout), 'Parent QEMU coordination lock is busy')
        try:
            yield
        finally:
            self.lock.release()

    @contextmanager
    def copy_window(self):
        require(not self.acknowledged, 'RAM access after DETACHED acknowledgement refused')
        with self.coordinated():
            revalidate(self.config)
            prior = self.qmp.status()
            trace = dict(prior_status=prior, prior_status_qmp_id=getattr(self.qmp, 'serial', None),
                         stop_reply=None, stop_qmp_id=None, commands=[], window_closed=False)
            stopped = prior
            if prior['running']:
                trace['stop_reply'] = self.qmp.execute('stop')
                trace['stop_qmp_id'] = getattr(self.qmp, 'serial', None)
                stopped = self.qmp.status()
                require(not stopped['running'], 'QEMU did not stop for mailbox copy')
            trace.update(paused_status=stopped, paused_status_qmp_id=getattr(self.qmp, 'serial', None))
            self.copy_trace, self.copy_status = trace, stopped
            self.rsp.window_deadline = time.monotonic() + 5.0
            try:
                yield
            finally:
                self.copy_status = None
                self.rsp.window_deadline = None
                trace['physical_mode_restored_before_exit'] = self.phys_restored
                if prior['running'] and self.phys_restored and self.resume_allowed():
                    trace['resume_reply'] = self.qmp.execute('cont')
                    trace['resume_qmp_id'] = getattr(self.qmp, 'serial', None)
                    resumed = self.qmp.status()
                    require(resumed['running'], 'QEMU did not resume after mailbox copy')
                    trace.update(continuation='resumed', resumed_status=resumed,
                                 resumed_status_qmp_id=getattr(self.qmp, 'serial', None))
                elif prior['running']:
                    trace['continuation'] = 'suppressed'
                    self.emit('resume_suppressed', physical_mode_restored=self.phys_restored)
                else:
                    trace['continuation'] = 'kept_paused'
                trace['window_closed'] = True
                self.copy_trace = None

    @contextmanager
    def physical(self):
        require(not self.acknowledged, 'Physical access after DETACHED refused')
        self.phys_restored = False
        try:
            self.rsp.mode(True)
            yield
        finally:
            self.rsp.mode(False)
            self.phys_restored = True
            self.emit('physical_mode_restored', protocol_physmode_restored=True)

    def spans(self, offset, size):
        require(type(offset) is int and type(size) is int and 0 <= offset <= MAILBOX_BYTES and 0 <= size <= MAILBOX_BYTES - offset,
                'Logical mailbox access exceeds dedicated pages')
        while size:
            page, inside = divmod(offset, PAGE)
            amount = min(size, PAGE - inside)
            yield self.mailbox['pages'][page] + inside, amount
            offset += amount
            size -= amount

    def read(self, offset, size):
        require(not self.acknowledged, 'Mailbox read after DETACHED refused')
        return b''.join(self.rsp.read(address, amount) for address, amount in self.spans(offset, size))

    def write(self, offset, data):
        require(not self.acknowledged, 'Mailbox write after DETACHED refused')
        used = 0
        for address, amount in self.spans(offset, len(data)):
            self.rsp.write(address, data[used:used + amount])
            used += amount

    def validate_observed_header(self, raw):
        try:
            validate_header(raw, self.mailbox)
        except ValueError as error:
            self.emit('header_rejected', raw_header_sha256=hashlib.sha256(raw).hexdigest(),
                      raw_header_hex=raw.hex(), error=str(error))
            raise

    def fetch(self):
        with self.copy_window(), self.physical():
            raw = self.read(0, HEADER)
            self.validate_observed_header(raw)
            status = u32(raw, 12)
            if status == REQUEST:
                data = b''
                try:
                    size = u32(raw, 36)
                    require(size <= DATA, 'Request exceeds mailbox payload')
                    data = self.read(HEADER, size)
                    validate_request(raw, data, self.mailbox, self.sequence)
                except (ValueError, OSError, EOFError, TimeoutError) as error:
                    self.emit('request_rejected', raw_header_sha256=hashlib.sha256(raw).hexdigest(),
                              raw_header_hex=raw.hex(), actual_payload_bytes=len(data),
                              actual_payload_sha256=hashlib.sha256(data).hexdigest(), error=str(error))
                    raise
                return raw, data
            if status == IDLE:
                require(self.sequence == 0 and raw[24:128] == bytes(104), 'Mailbox returned to IDLE or was not pristine')
            elif status == RESPONSE:
                require(raw == self.last_response, 'Unpublished/stale response or guest header mutation')
            elif status == DETACHED:
                raise ValueError('Mailbox already detached by another owner')
            return raw, None

    def observe_transfer(self, request, incoming, data, error, result):
        """Reconstruct actual bytes, not a composition of opaque chunk digests."""
        if error:
            return None
        op, sequence = u32(request, 32), u64(request, 24)
        transfer = self.transfer
        if transfer is not None and transfer.get('provider_kind') == 'source' and op in (READ_RESULT, RELEASE_RESULT):
            require(source_snapshot.binding(request) == transfer['source_binding'], 'Source retained origin changed')
        if op == CANCEL:
            self.transfer = None
            status = 'cancelled'
        elif op == RELEASE_RESULT:
            require(transfer is not None and len(incoming) == 16 and u64(incoming, 0) == transfer['token'] and
                    transfer['cursor'] == transfer['total'] and u64(incoming, 8) == transfer['fnv1a64'] and
                    not data and not any((result.token, result.total, result.offset, result.used)),
                    'Actual released token/whole-byte FNV differs')
            self.transfer = None
            status = 'released'
        elif op == READ_RESULT:
            require(transfer is not None and len(incoming) == 24 and u64(incoming, 0) == transfer['token'] and
                    u64(incoming, 8) == transfer['cursor'] == result.offset and result.token == transfer['token'] and
                    result.total == transfer['total'] and u32(incoming, 20) == 0 and
                    len(data) == result.used == min(u32(incoming, 16), u32(request, 40), transfer['total'] - transfer['cursor']) and
                    len(data) > 0, 'Actual READ_RESULT token/cursor/bytes differs')
            status = 'chunk'
        elif result.token:
            require(op in (STILL, VIDEO_FRAME, VIDEO_END, AP_SOURCE_SNAPSHOT) and transfer is None and result.offset == 0 and
                    0 < len(data) == result.used <= result.total <= MAX_RESULT and
                    (result.token >= source_snapshot.TOKEN_BASE) == (op == AP_SOURCE_SNAPSHOT),
                    'Actual result lease overlaps or has invalid bytes')
            transfer = dict(token=result.token, total=result.total, cursor=0, fnv1a64=FNV_SEED,
                            sha_state=hashlib.sha256(), chunk_count=0, first_sequence=sequence,
                            provider_kind='source' if op == AP_SOURCE_SNAPSHOT else 'core',
                            source_provider_kind=source_snapshot.CLAIMS['source_model'] if op == AP_SOURCE_SNAPSHOT else None,
                            origin=origin(request), source_binding=source_snapshot.binding(request))
            self.transfer = transfer
            status = 'opened'
        else:
            return None
        if transfer is None:
            return None  # CANCEL without any encoded lease.
        if status in ('opened', 'chunk'):
            transfer['fnv1a64'] = fnv64(data, transfer['fnv1a64'])
            transfer['sha_state'].update(data)
            transfer['cursor'] += len(data)
            transfer['chunk_count'] += 1
        return dict(status=status, token=transfer['token'], total=transfer['total'],
                    reconstructed_bytes=transfer['cursor'], fnv1a64=transfer['fnv1a64'],
                    sha256=transfer['sha_state'].hexdigest(), chunk_count=transfer['chunk_count'],
                    first_sequence=transfer['first_sequence'], sequence=sequence,
                    provider_kind=transfer['provider_kind'], source_provider_kind=transfer['source_provider_kind'],
                    origin=transfer['origin'], complete=transfer['cursor'] == transfer['total'])

    def source(self):
        if not hasattr(self, 'source_provider'):
            self.source_provider = source_snapshot.Snapshot(all(os.environ.get(key) == source_snapshot.PROFILE
                for key in ('MENU_FUNCTIONAL_CAMERA', 'A7C2_FUNCTIONAL_CAMERA')))
        return self.source_provider

    def clear_source(self, reason, **fields):
        source = self.source()
        receipt = source.cancel()
        if self.transfer and self.transfer.get('provider_kind') == 'source':
            self.transfer = None
        self.emit('source_cancel', reason=reason, **receipt, **fields)

    def call_source(self, request, incoming, capacity):
        op, source = u32(request, 32), self.source()
        metadata = dict(**source_snapshot.CLAIMS)
        window = None
        try:
            if op == AP_SOURCE_SNAPSHOT:
                if not source.enabled:
                    return -errno.ENOTSUP, b'', ExecResult(), metadata
                if self.transfer is not None or source.active is not None:
                    return -errno.EBUSY, b'', ExecResult(), metadata
                if source.fault is not None:
                    return -errno.EIO, b'', ExecResult(), dict(metadata, sticky_fault=source.fault)
                if not capacity:
                    return -errno.ENOSPC, b'', ExecResult(), metadata
                if self.core.model is None:
                    return -errno.ENODEV, b'', ExecResult(), metadata
                with self.copy_window():
                    window = self.copy_trace
                    window.update(sequence=u64(request, 24), request_header_sha256=hashlib.sha256(request).hexdigest(),
                                  request_payload_sha256=hashlib.sha256(incoming).hexdigest(), origin=origin(request),
                                  model_instance=self.mailbox['nonce'])
                    require(self.copy_status['status'] == 'paused' and not self.done.is_set(),
                            'Source snapshot requires paused live copy window')
                    with self.physical():
                        actual_header, actual_input = self.read(0, HEADER), self.read(HEADER, len(incoming))
                        require(actual_header == request and actual_input == incoming,
                                'Source snapshot request changed before paused read')
                        window.update(observed_header_sha256=hashlib.sha256(actual_header).hexdigest(),
                                      observed_payload_sha256=hashlib.sha256(actual_input).hexdigest())
                    active, metadata = source.open(incoming, request, self.mailbox, self.qmp, window)
                metadata['paused_window'] = window
                output = active['data'][:capacity]
                return 0, output, ExecResult(active['token'], len(active['data']), 0, len(output)), metadata
            if op not in (READ_RESULT, RELEASE_RESULT):
                return -errno.EBUSY, b'', ExecResult(), metadata
            error, output, offset = source.stream(request, incoming, self.transfer)
            active = source.active
            result = ExecResult(active['token'], len(active['data']), offset, len(output)) if not error and output else ExecResult()
            return error, output, result, metadata
        except (ValueError, OSError, EOFError, TimeoutError) as error:
            return -errno.EPROTO, b'', ExecResult(), dict(metadata, error=str(error), sticky_fault=source.fault,
                                                        paused_window=window)

    def call_core(self, request, incoming, capacity):
        op, checked_capacity = validate_request(request, incoming, self.mailbox, self.sequence)
        require(capacity == checked_capacity and self.pending_payloads is None, 'Core call capacity/pending response differs')
        self.sequence = u64(request, 24)
        token = u64(incoming, 0) if op in (READ_RESULT, RELEASE_RESULT) else 0
        transfer = self.transfer if self.transfer and self.transfer['token'] == token else None
        total = transfer['total'] if transfer else 0
        offset = u64(incoming, 8) if op == READ_RESULT else transfer['cursor'] if transfer else 0
        input_ref = self.payloads.retain(request, 'in', incoming, event=self.event_serial + 1,
                                         token=token, total=total, offset=offset)
        self.emit('request', sequence=self.sequence, opcode=op, origin=origin(request),
                  raw_header_sha256=hashlib.sha256(request).hexdigest(), raw_header_hex=request.hex(),
                  request_bytes=len(incoming), request_sha256=hashlib.sha256(incoming).hexdigest(),
                  request_fnv1a64=fnv64(incoming), request_payload=input_ref)
        source = self.source()
        source_call = op != CANCEL and (op == AP_SOURCE_SNAPSHOT or u32(request, 52) == 1 or
            token >= source_snapshot.TOKEN_BASE or source.active is not None)
        if source_call:
            error, data, result, metadata = self.call_source(request, incoming, capacity)
        else:
            try:
                error, data, result = self.core.execute(self.mailbox['nonce'], op, incoming, capacity)
            finally:
                if op == CANCEL:
                    receipt = source.cancel()
                    self.emit('source_cancel', reason='actual_c_cancel', actual_c_result=locals().get('error'), **receipt)
        output_ref = self.payloads.retain(request, 'out', data, event=self.event_serial + 1,
                                          token=result.token, total=result.total, offset=result.offset)
        observed_transfer = self.observe_transfer(request, incoming, data, error, result)
        if op == CANCEL and not source_call and error and self.transfer and self.transfer.get('provider_kind') == 'source':
            self.transfer = None
        result_fields = dict(actual_c_result=None, actual_source_result=error, source_provider_kind='paused-source-snapshot-v1',
                             source_snapshot=metadata) if source_call else dict(actual_c_result=error)
        self.emit('ap_source_result' if source_call else 'core_result', sequence=self.sequence, opcode=op,
                  origin=origin(request), **result_fields,
                  returned_bytes=len(data), returned_sha256=hashlib.sha256(data).hexdigest(), returned_fnv1a64=fnv64(data),
                  token=result.token, total=result.total, offset=result.offset,
                  request_payload=input_ref, output_payload=output_ref, result_transfer=observed_transfer)
        self.pending_payloads = dict(sequence=self.sequence, request=request, incoming=incoming, result_code=error,
                                     result_fields=result_fields,
                                     result=(result.token, result.total, result.offset, result.used),
                                     request_payload=input_ref, output_payload=output_ref, result_transfer=observed_transfer)
        if source_call:
            return error, data, result
        proof = self.core.proof_snapshot()  # Read only, after the one original call, under broker serialization.
        previous = self.last_frame['serial'] if self.last_frame else 0
        if op in (BB_STARTUP_CONFIG, HISTOGRAM, VDF_BIT_WIDTH) and not error:
            require(proof is not None and proof['serial'] == previous + 1 and
                    proof['consumer_kind'] == (4 if op == VDF_BIT_WIDTH else 5 if op == BB_STARTUP_CONFIG else 6),
                    'Actual BB/histogram/bit-width success lacks its own noncodec frame proof')
        if proof is not None:
            require(proof['serial'] in (previous, previous + 1), 'Actual C proof sequence changed unexpectedly')
            if proof['serial'] == previous and self.last_frame is not None:
                require(proof == self.last_frame, 'Read-only operation changed the previous frame proof')
            elif proof['serial']:
                require(proof['opcode'] == op and proof['operation_status'] == error and
                        (self.last_frame is None or proof['model_lifetime'] == self.last_frame['model_lifetime']),
                        'Actual C proof operation/lifetime differs')
                self.emit('model_frame', sequence=self.sequence, opcode=op, origin=origin(request),
                          actual_c_result=error, actual_core_sha256=self.core.digest,
                          request_payload=input_ref, output_payload=output_ref, proof=proof, native_acceptance=False)
                self.last_frame = proof
        return error, data, result

    def publish(self, request, data, error, result):
        require(type(data) is bytes and type(error) is int and -4095 <= error <= 0 and
                len(data) <= u32(request, 40) <= DATA and len(data) == result.used and
                result.offset <= result.total <= MAX_RESULT and
                (not result.token and not result.total and not result.offset or
                 result.token and 0 < result.used <= result.total - result.offset) and
                (not error or not (data or result.token or result.total or result.offset)),
                'Uncommitted/out-of-bounds core output cannot be published')
        evidence = self.pending_payloads
        require(evidence is not None and evidence['sequence'] == u64(request, 24) and evidence['request'] == request and
                evidence.get('result_code', evidence.get('actual_c_result')) == error and
                evidence['result'] == (result.token, result.total, result.offset, result.used),
                'Missing or changed actual retained request/result evidence')
        self.payloads.verify(evidence['request_payload'], evidence['incoming'])
        self.payloads.verify(evidence['output_payload'], data)
        result_fields = evidence.get('result_fields', dict(actual_c_result=error))
        response = bytearray(request)
        struct.pack_into('<Ii', response, 44, len(data), error)
        struct.pack_into('<4Q', response, 64, fnv64(data), result.total, result.offset, result.token)
        with self.copy_window(), self.physical():
            actual = self.read(0, HEADER)
            self.validate_observed_header(actual)
            if u32(actual, 12) == CLOSED:
                self.emit('late_close', sequence=u64(request, 24), opcode=u32(request, 32), **result_fields,
                          discarded_bytes=len(data), discarded_sha256=hashlib.sha256(data).hexdigest())
                if self.source().active is not None:
                    self.clear_source('late_close')
                return False
            require(actual == request, 'Request changed while actual C model executed: raw_header=' + actual.hex())
            if self.done.is_set():
                if self.source().active is not None:
                    self.clear_source('stop_before_publish')
                return False
            if data:
                self.write(HEADER, data)
            self.write(44, response[44:52])
            self.write(64, response[64:96])
            require(self.read(0, HEADER) == response and self.read(HEADER, len(data)) == data,
                    'Staged mailbox data/header readback differs')
            self.write(12, struct.pack('<I', RESPONSE))  # Commit only after exact staged readback.
            struct.pack_into('<I', response, 12, RESPONSE)
            require(self.read(0, HEADER) == response and self.read(HEADER, len(data)) == data,
                    'Committed mailbox data/header readback differs')
            self.last_response = bytes(response)
            self.emit('response', sequence=u64(request, 24), opcode=u32(request, 32),
                      raw_header_sha256=hashlib.sha256(request).hexdigest(), response_header_sha256=hashlib.sha256(response).hexdigest(),
                      origin=origin(request),
                      **result_fields, returned_bytes=len(data), returned_sha256=hashlib.sha256(data).hexdigest(),
                      returned_fnv1a64=fnv64(data), token=result.token, total=result.total, offset=result.offset,
                      request_payload=evidence['request_payload'], output_payload=evidence['output_payload'],
                      result_transfer=evidence['result_transfer'], data_readback=True, native_acceptance=False)
        self.pending_payloads = None
        return True

    def detach_mailbox(self):
        # Model work/cancellation and destruction must already have ended.
        require(self.core.model is None, 'Cannot detach while core owns model storage')
        require(self.source().active is None, 'Cannot detach while host source snapshot owns storage')
        with self.copy_window():
            # The final physical write is the last RAM access. Restoring mode 0
            # afterwards changes the debugger protocol only, never guest RAM.
            with self.physical():
                raw = self.read(0, HEADER)
                self.validate_observed_header(raw)
                require(u32(raw, 12) != DETACHED, 'Unexpected prior DETACHED acknowledgement')
                self.emit('detach_commit', sequence=u64(raw, 24), previous_status=u32(raw, 12),
                          raw_header_sha256=hashlib.sha256(raw).hexdigest(), model_work_stopped=True,
                          no_further_ram_after_ack=True)
                self.write(12, struct.pack('<I', DETACHED))
                self.acknowledged = True  # Absolutely no RAM reads/writes after this status word.
        self.emit('mailbox_detached', cleanup_detach=True, protocol_physmode_restored=self.phys_restored)

    def _run(self):
        errors = []
        connected = False
        try:
            with self.coordinated():
                revalidate(self.config)
                self.qmp = QMP(self.config['qmp']['path'], self.io_timeout, expected_pid=self.config['qemu']['pid'])
                prior = self.qmp.status()
                if prior['running']:
                    self.qmp.execute('stop')
                try:
                    self.rsp = RSP(self.config['gdb']['path'], self.io_timeout, expected_pid=self.config['qemu']['pid'])
                    connected = True
                    self.phys_restored = False
                    self.rsp.mode(False)
                    self.phys_restored = True
                finally:
                    if prior['running'] and self.phys_restored and self.resume_allowed():
                        self.qmp.execute('cont')
            self.emit('attached', model_created=False, connected=True, protocol_physmode_restored=True)
            self.ready.set()
            deadline = time.monotonic() + self.seconds
            while not self.done.is_set():
                if time.monotonic() >= deadline:
                    raise TimeoutError('Functional-camera broker phase lifetime expired')
                raw, data = self.fetch()
                if self.done.is_set() or u32(raw, 12) == CLOSED:
                    break
                if data is None:
                    self.done.wait(0.01)
                    continue
                op, capacity = validate_request(raw, data, self.mailbox, self.sequence)
                # Source reads open their own coordinated paused copy window.
                error, output, result = self.call_core(raw, data, capacity)
                if not self.publish(raw, output, error, result):
                    break
        except BaseException as error:
            errors.append(f'{type(error).__name__}: {error}')
            self.start_error = error
            self.cleaning = True
            if self.events:
                self.emit('failure', error=errors[-1], sequence=self.sequence)
        finally:
            self.cleaning = True
            self.ready.set()
            self.clear_source('broker_cleanup')
            if self.core:
                try:
                    if self.core.model:
                        error, data, result = self.core.execute(self.mailbox['nonce'], CANCEL, b'', 128)
                        self.emit('cancel_cleanup', actual_c_result=error, returned_bytes=len(data),
                                  returned_sha256=hashlib.sha256(data).hexdigest())
                        if error:
                            errors.append(f'Actual C cleanup CANCEL failed: {error}')
                    self.core.destroy_model()
                except BaseException as error:
                    errors.append('model cleanup: ' + str(error))
                    try:
                        self.core.destroy_model()
                    except BaseException as second:
                        errors.append('model destruction: ' + str(second))
            if connected and self.phys_restored and self.core.model is None:
                try:
                    self.detach_mailbox()
                except BaseException as error:
                    errors.append('mailbox detach: ' + str(error))
            disconnected = self.rsp is None
            try:
                if self.rsp is not None:
                    with self.coordinated():
                        prior = self.qmp.status()
                        self.rsp.close()
                        disconnected = True
                        after = self.qmp.status()
                        if prior['running'] != after['running']:
                            if not prior['running']:
                                self.qmp.execute('stop')
                            raise ValueError('QEMU changed run state while debugger disconnected')
                        self.emit('debugger_disconnected', prior_status=prior['status'], final_status=after['status'],
                                  detached=True, protocol_physmode_restored=self.phys_restored)
            except BaseException as error:
                errors.append('debugger disconnect: ' + str(error))
                if self.rsp is not None:
                    self.rsp.close()
                    disconnected = True
            if self.qmp:
                self.qmp.close()
            if self.core:
                self.core.close()
            if self.payloads:
                self.payloads.close()
            errors.extend('receipt I/O: ' + error for error in self.log_errors)
            self.cleanup = dict(worker_stopped=True, debugger_stopped=disconnected, detached=disconnected,
                                mailbox_detached=self.acknowledged, protocol_physmode_restored=self.phys_restored,
                                safe_to_close=disconnected and self.phys_restored and (not connected or self.acknowledged) and not errors,
                                errors=errors)
            if self.events:
                self.emit('cleanup', **self.cleanup)
                self.events.close()
            if self.lease is not None:
                os.close(self.lease)
                self.lease = None

    def stop(self):
        self.done.set()
        if self.thread:
            self.thread.join(timeout=35)
            if self.thread.is_alive():
                return dict(worker_stopped=False, debugger_stopped=False, detached=False, mailbox_detached=False,
                            protocol_physmode_restored=self.phys_restored, safe_to_close=False,
                            errors=['Actual C model/transport still running; resources retained, no forced termination'])
        return self.cleanup

    def read_receipts(self):
        return read_receipts(self.root)


def start(run, owner_pid, mailbox, library, **config):
    """Start one bound broker after parent debugger handoff; see Broker signature."""
    return Broker(run, owner_pid, mailbox, library, **config)


def read_receipts(run):
    root, _ = validate_run(run)
    fd = os.open(root / (PREFIX + '-receipts.jsonl'), os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW)
    try:
        info = os.fstat(fd)
        require(stat.S_ISREG(info.st_mode) and info.st_uid == os.getuid() and stat.S_IMODE(info.st_mode) == 0o600 and
                info.st_size <= 64 * 1024 * 1024, 'Untrusted/oversized broker receipts')
        data = os.pread(fd, info.st_size, 0)
    finally:
        os.close(fd)
    require(len(data) == info.st_size, 'Short broker receipt read')
    # A live writer may be between write calls; expose only committed JSONL lines.
    lines = data.split(b'\n')[:-1]
    values = [json.loads(line) for line in lines]
    require(all(type(value) is dict and value.get('event') == n + 1 for n, value in enumerate(values)),
            'Broker receipt sequence is incomplete/reordered')
    return values
