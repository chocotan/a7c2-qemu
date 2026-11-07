#!/usr/bin/env python3
"""Loopback USB/IP export backed exclusively by a per-run guest endpoint bridge."""
import argparse
import asyncio
from collections import deque
from contextlib import contextmanager
from dataclasses import dataclass
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import signal
import socket
import stat
import struct
import sys
import time

VERSION = 0x0111
DEVLIST, IMPORT = 0x8005, 0x8003
SUBMIT, UNLINK, RET_SUBMIT, RET_UNLINK = 1, 2, 3, 4
COMMON = struct.Struct('!HHI')
BASIC = struct.Struct('!IIIII')
SUBMIT_BODY = struct.Struct('!Iiiii8s')
RETURN_BODY = struct.Struct('!iiiii8x')
DEVICE = struct.Struct('!256s32sIIIHHHBBBBBB')
MAX_HEADER, MAX_PAYLOAD = 16384, 1048576
MAX_PENDING, MAX_RESERVED, MAX_RPCS = 32, 8 * 1048576, 72


class ProtocolError(ValueError):
    pass


class Blocked(RuntimeError):
    pass


class GadgetNotReady(Blocked):
    code = 'gadget_not_ready'


def integer(value, minimum, maximum, label):
    if type(value) is not int or not minimum <= value <= maximum:
        raise ProtocolError('invalid ' + label)
    return value


def _object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ProtocolError('duplicate JSON key')
        result[key] = value
    return result


def decode_header(raw):
    try:
        header = json.loads(raw.decode('utf-8'), object_pairs_hook=_object,
                            parse_constant=lambda _: (_ for _ in ()).throw(ProtocolError('non-finite JSON')))
    except (UnicodeError, ValueError, RecursionError) as error:
        raise ProtocolError('invalid bridge JSON') from error
    if (not isinstance(header, dict) or type(header.get('version')) is not int or
            header['version'] != 1 or not isinstance(header.get('op'), str)):
        raise ProtocolError('invalid bridge envelope')
    integer(header.get('id'), 1, 0xffffffff, 'bridge id')
    return header


def encode_frame(header, payload=b''):
    if not isinstance(payload, bytes):
        raise ProtocolError('payload must be bytes')
    raw = json.dumps(header, ensure_ascii=True, allow_nan=False, separators=(',', ':')).encode('ascii')
    if not 1 <= len(raw) <= MAX_HEADER or len(payload) > MAX_PAYLOAD:
        raise ProtocolError('bridge frame budget exceeded')
    decode_header(raw)
    return struct.pack('!II', len(raw), len(payload)) + raw + payload


async def read_frame(reader, timeout=30):
    async def read():
        size, length = struct.unpack('!II', await reader.readexactly(8))
        if not 1 <= size <= MAX_HEADER or length > MAX_PAYLOAD:
            raise ProtocolError('bridge frame budget exceeded')
        header = decode_header(await reader.readexactly(size))
        return header, await reader.readexactly(length)
    return await asyncio.wait_for(read(), timeout)


@dataclass(frozen=True)
class Context:
    run_dir: Path
    qmp_path: Path
    backend_path: Path
    lease: str
    vm_pid: int
    run_id: str

    @classmethod
    def create(cls, run_dir, qmp_path, backend_path, lease, vm_pid, run_id=None):
        run = Path(run_dir).resolve(strict=True)
        info = run.stat()
        if not run.is_dir() or info.st_uid != os.getuid() or info.st_mode & 0o022:
            raise Blocked('run directory must be owned and not group/world writable')
        paths = []
        for path in (qmp_path, backend_path):
            path = Path(path).absolute()
            resolved = path.resolve()
            if resolved.parent != run or path.is_symlink():
                raise Blocked('QMP/backend must be direct, nonsymlink children of this run')
            paths.append(resolved)
        if (not isinstance(lease, str) or not 32 <= len(lease) <= 128 or
                not lease.isascii() or any(ord(c) < 33 or ord(c) > 126 for c in lease)):
            raise Blocked('lease must be 32..128 printable ASCII characters')
        integer(vm_pid, 2, 0x7fffffff, 'VM PID')
        name = run.name if run_id is None else run_id
        if not isinstance(name, str) or not re.fullmatch(r'[A-Za-z0-9_.-]{1,96}', name):
            raise Blocked('invalid run_id')
        return cls(run, paths[0], paths[1], lease, vm_pid, name)

    def identity(self):
        return {'run_id': self.run_id, 'lease': self.lease,
                'qmp_path': str(self.qmp_path), 'vm_pid': self.vm_pid}

    @property
    def lease_id(self):
        return hashlib.sha256(self.lease.encode('ascii')).hexdigest()


def check_unix(path, private=True):
    info = path.lstat()
    forbidden = 0o077 if private else 0o022
    if not stat.S_ISSOCK(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & forbidden:
        raise Blocked('Unix socket ownership/permissions are unsafe: ' + str(path))


@contextmanager
def unix_path(path, private=True):
    """Connect deep owned run paths without the AF_UNIX sun_path limit."""
    path = Path(path)
    directory = os.open('/', os.O_RDONLY | os.O_DIRECTORY)
    try:
        for component in path.parent.parts[1:]:
            child = os.open(component, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=directory)
            os.close(directory)
            directory = child
        before = os.stat(path.name, dir_fd=directory, follow_symlinks=False)
        check_unix(path, private=private)
        yield '/proc/self/fd/' + str(directory) + '/' + path.name
        after = os.stat(path.name, dir_fd=directory, follow_symlinks=False)
        current = path.lstat()
        if (before.st_dev, before.st_ino) != (after.st_dev, after.st_ino) or (after.st_dev, after.st_ino) != (current.st_dev, current.st_ino):
            raise Blocked('Unix socket replaced while connecting')
    finally:
        os.close(directory)


class Bridge:
    def __init__(self, reader, writer):
        self.reader, self.writer = reader, writer
        self.requests = {}
        self.retired = deque(maxlen=256)
        self.next_id = 1
        self.error = None
        self.task = asyncio.create_task(self._read())

    @classmethod
    async def open(cls, context, role):
        check_unix(context.backend_path)
        writer = None
        try:
            with unix_path(context.backend_path) as path:
                reader, writer = await asyncio.wait_for(asyncio.open_unix_connection(path), 3)
        except BaseException:
            if writer is not None:
                writer.close()
                await writer.wait_closed()
            raise
        peer = struct.unpack('3i', writer.get_extra_info('socket').getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12))
        if peer[0] != context.vm_pid or peer[1] != os.getuid():
            writer.close()
            await writer.wait_closed()
            raise Blocked('backend peer VM PID/UID mismatch')
        bridge = cls(reader, writer)
        try:
            response, data = await bridge.ask('hello', role=role, **context.identity())
            if data or any(response.get(k) != v for k, v in {**context.identity(), 'role': role}.items()):
                raise Blocked('backend run/lease/QMP/PID identity mismatch')
            return bridge
        except BaseException:
            await bridge.close()
            raise

    async def _read(self):
        try:
            while True:
                # Idle imports can wait indefinitely; outstanding RPCs have their own deadlines.
                header, payload = await read_frame(self.reader, timeout=None)
                if header['op'] == 'event':
                    raise Blocked('backend event: ' + str(header.get('kind')))
                request = self.requests.get(header['id'])
                if request is None:
                    if header['id'] in self.retired and header['op'] == 'complete':
                        self.retired.remove(header['id'])
                        continue
                    raise ProtocolError('unsolicited or duplicate backend completion')
                future, expected = request
                if header['op'] != expected or header.get('ok') is not True:
                    raise ProtocolError('backend rejected or mismatched response')
                del self.requests[header['id']]
                if not future.done():
                    future.set_result((header, payload))
        except asyncio.CancelledError:
            raise
        except Exception as error:
            self.error = error
            for future, _ in self.requests.values():
                if not future.done():
                    future.set_exception(error)
            self.requests.clear()
            self.writer.close()

    async def begin(self, op, payload=b'', **fields):
        if self.error or self.writer.is_closing():
            raise Blocked('endpoint bridge disconnected')
        if len(self.requests) >= MAX_RPCS:
            raise ProtocolError('bridge pending budget exceeded')
        request_id = self.next_id
        self.next_id += 1
        integer(request_id, 1, 0xffffffff, 'bridge request counter')
        expected = {'submit': 'complete', 'cancel': 'cancelled'}.get(op, op)
        future = asyncio.get_running_loop().create_future()
        self.requests[request_id] = (future, expected)
        try:
            self.writer.write(encode_frame({'version': 1, 'op': op, 'id': request_id, **fields}, payload))
            await self.writer.drain()
        except BaseException:
            self.requests.pop(request_id, None)
            future.cancel()
            raise
        return request_id, future

    async def ask(self, op, payload=b'', timeout=5, **fields):
        request_id, future = await self.begin(op, payload, **fields)
        try:
            return await asyncio.wait_for(asyncio.shield(future), timeout)
        except BaseException:
            # Keep the id registered until a late response or close; it cannot be reused.
            future.cancel()
            raise

    async def cancel(self, request_id):
        response, payload = await self.ask('cancel', target=request_id)
        if payload or response.get('target') != request_id or type(response.get('status')) is not int or response['status'] != 0:
            raise ProtocolError('backend did not release cancelled URB')
        pending = self.requests.pop(request_id, None)
        if pending:
            pending[0].cancel()
            self.retired.append(request_id)

    async def describe(self):
        response, payload = await self.ask('describe')
        if response.get('ready') is False:
            if payload or 'device' in response:
                raise ProtocolError('unready backend supplied an export')
            raise GadgetNotReady(str(response.get('reason', 'gadget is not ready')))
        if response.get('ready') is not True:
            raise ProtocolError('missing readiness evidence')
        return GuestDevice.parse(response.get('device'), payload)

    async def close(self):
        self.task.cancel()
        self.writer.close()
        try:
            await self.writer.wait_closed()
        except (ConnectionError, OSError):
            pass
        await asyncio.gather(self.task, return_exceptions=True)
        for future, _ in self.requests.values():
            if not future.done():
                future.cancel()
        self.requests.clear()


@dataclass(frozen=True)
class GuestDevice:
    metadata: dict
    descriptors: bytes
    interfaces: tuple
    endpoints: frozenset

    @classmethod
    def parse(cls, metadata, raw):
        if not isinstance(metadata, dict) or metadata.get('descriptor_source') != 'guest-ep0':
            raise ProtocolError('descriptors must come from guest EP0')
        busid = metadata.get('busid')
        if not isinstance(busid, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,30}', busid):
            raise ProtocolError('invalid virtual busid')
        integer(metadata.get('busnum'), 1, 65535, 'busnum')
        integer(metadata.get('devnum'), 1, 65535, 'devnum')
        if type(metadata.get('speed')) is not int or metadata['speed'] not in (1, 2, 3, 5, 6):
            raise ProtocolError('unsupported USB speed')
        integer(metadata.get('configuration_value'), 1, 255, 'configuration value')
        if len(raw) < 27 or raw[:2] != b'\x12\x01' or raw[18:20] != b'\x09\x02':
            raise ProtocolError('invalid guest device/configuration descriptors')
        total = int.from_bytes(raw[20:22], 'little')
        if total < 9 or len(raw) != 18 + total or raw[23] != metadata['configuration_value'] or raw[17] == 0:
            raise ProtocolError('configuration length/value mismatch')
        interfaces, endpoints = {}, set()
        offset = 18
        active_interface = None
        counts = {}
        expected_counts = {}
        while offset < len(raw):
            if offset + 2 > len(raw) or raw[offset] < 2 or offset + raw[offset] > len(raw):
                raise ProtocolError('malformed configuration segment')
            segment = raw[offset:offset + raw[offset]]
            if segment[1] == 4:
                if len(segment) < 9:
                    raise ProtocolError('short interface descriptor')
                number, alternate = segment[2], segment[3]
                active_interface = (number, alternate)
                if active_interface in expected_counts:
                    raise ProtocolError('duplicate interface alternate')
                expected_counts[active_interface], counts[active_interface] = segment[4], 0
                if alternate == 0:
                    interfaces[number] = tuple(segment[5:8])
            elif segment[1] == 5:
                if len(segment) < 7 or active_interface is None or segment[2] & 0x70 or segment[2] & 15 == 0:
                    raise ProtocolError('invalid endpoint descriptor')
                counts[active_interface] += 1
                endpoints.add((int(bool(segment[2] & 0x80)), segment[2] & 15))
            offset += len(segment)
        if (len(interfaces) != raw[22] or sorted(interfaces) != list(range(raw[22])) or
                counts != expected_counts):
            raise ProtocolError('interface/endpoint count mismatch')
        return cls(dict(metadata), raw, tuple(interfaces[i] for i in sorted(interfaces)), frozenset(endpoints))

    @property
    def devid(self):
        return self.metadata['busnum'] << 16 | self.metadata['devnum']

    @property
    def busid(self):
        return self.metadata['busid']

    def wire(self, run_id):
        raw, m = self.descriptors, self.metadata
        return DEVICE.pack(('/virtual/' + run_id + '/' + self.busid).encode(), self.busid.encode(),
                           m['busnum'], m['devnum'], m['speed'],
                           int.from_bytes(raw[8:10], 'little'), int.from_bytes(raw[10:12], 'little'),
                           int.from_bytes(raw[12:14], 'little'), raw[4], raw[5], raw[6],
                           m['configuration_value'], raw[17], len(self.interfaces))


@dataclass
class Pending:
    basic: tuple
    length: int
    request_id: int
    future: object
    task: object = None
    retiring: bool = False
    completed: bool = False


class ImportSession:
    def __init__(self, reader, writer, bridge, device, urb_timeout=30):
        self.reader, self.writer, self.bridge, self.device = reader, writer, bridge, device
        self.urb_timeout = urb_timeout
        self.pending = {}
        self.reserved = 0
        self.recent = deque(maxlen=4096)
        self.tasks = set()
        self.send_lock = asyncio.Lock()
        self.failure = None

    async def send(self, basic, body, payload=b''):
        async with self.send_lock:
            self.writer.write(BASIC.pack(*basic) + body + payload)
            await self.writer.drain()

    async def complete(self, entry):
        seq = entry.basic[1]
        try:
            try:
                response, data = await asyncio.wait_for(asyncio.shield(entry.future), self.urb_timeout)
            except asyncio.TimeoutError:
                if entry.retiring:
                    return
                entry.retiring = True
                await self.bridge.cancel(entry.request_id)
                response, data = {'status': -110, 'actual_length': 0}, b''
            if entry.retiring and response.get('status') != -110:
                return
            status = integer(response.get('status'), -4095, 0, 'completion status')
            actual = integer(response.get('actual_length'), 0, entry.length, 'actual length')
            if (len(data) != (actual if entry.basic[3] else 0) or
                    response.get('num_packets', 0) != 0 or response.get('error_count', 0) != 0):
                raise ProtocolError('invalid completion payload/segments')
            frame = integer(response.get('start_frame', 0), -1, 0x7fffffff, 'completion frame')
            entry.completed = True
            await self.send((RET_SUBMIT, *entry.basic[1:]), RETURN_BODY.pack(status, actual, frame, 0, 0), data)
        except asyncio.CancelledError:
            raise
        except Exception as error:
            self.failure = error
            self.writer.close()
        finally:
            if self.pending.get(seq) is entry:
                del self.pending[seq]
                self.reserved -= entry.length

    async def _watch_backend(self):
        await self.bridge.task
        self.writer.close()

    async def run(self):
        watcher = asyncio.create_task(self._watch_backend())
        try:
            while True:
                raw = await self.reader.readexactly(48)
                basic = BASIC.unpack(raw[:20])
                command, seq, devid, direction, endpoint = basic
                if seq in self.recent or seq in self.pending:
                    raise ProtocolError('duplicate USB/IP seqnum')
                self.recent.append(seq)
                if command not in (SUBMIT, UNLINK) or devid != self.device.devid or direction not in (0, 1) or endpoint > 15:
                    raise ProtocolError('invalid USB/IP command/device/endpoint')
                if command == UNLINK:
                    target = struct.unpack('!I', raw[20:24])[0]
                    if raw[24:] != bytes(24):
                        raise ProtocolError('invalid unlink reserved fields')
                    entry = self.pending.get(target)
                    if entry is None or entry.retiring or entry.completed:
                        result = -2
                    else:
                        entry.retiring = True
                        entry.task.cancel()
                        await asyncio.gather(entry.task, return_exceptions=True)
                        await self.bridge.cancel(entry.request_id)
                        result = -104
                    await self.send((RET_UNLINK, seq, devid, direction, endpoint), struct.pack('!i24x', result))
                    continue
                flags, length, frame, packets, interval, setup = SUBMIT_BODY.unpack(raw[20:])
                integer(length, 0, MAX_PAYLOAD, 'transfer length')
                if packets != 0 or interval < 0 or frame < -1:
                    raise ProtocolError('unsupported isochronous/invalid transfer segments')
                if endpoint == 0:
                    if int.from_bytes(setup[6:8], 'little') != length or (length and setup[0] >> 7 != direction):
                        raise ProtocolError('control setup direction/length mismatch')
                elif setup != bytes(8) or (direction, endpoint) not in self.device.endpoints:
                    raise ProtocolError('unadvertised endpoint or non-control setup')
                if len(self.pending) >= MAX_PENDING or self.reserved + length > MAX_RESERVED:
                    raise ProtocolError('USB/IP pending transfer budget exceeded')
                data = await asyncio.wait_for(self.reader.readexactly(length), 10) if direction == 0 else b''
                request_id, future = await self.bridge.begin('submit', data, seqnum=seq, devid=devid,
                    direction=direction, endpoint=endpoint, transfer_flags=flags, transfer_length=length,
                    start_frame=frame, num_packets=packets, interval=interval, setup=setup.hex())
                entry = Pending(basic, length, request_id, future)
                self.pending[seq] = entry
                self.reserved += length
                entry.task = asyncio.create_task(self.complete(entry))
                self.tasks.add(entry.task)
                entry.task.add_done_callback(self.tasks.discard)
        finally:
            watcher.cancel()
            for entry in tuple(self.pending.values()):
                entry.retiring = True
            for task in tuple(self.tasks):
                task.cancel()
            await asyncio.gather(watcher, *tuple(self.tasks), return_exceptions=True)
            # Bridge close is the owner-scoped cancellation boundary on transport loss.
            await self.bridge.close()


class UsbIpServer:
    def __init__(self, context, *, host='127.0.0.1', port=0, urb_timeout=30):
        if host != '127.0.0.1':
            raise Blocked('USB/IP listener must bind 127.0.0.1')
        self.context, self.host, self.port, self.urb_timeout = context, host, port, urb_timeout
        self.imported = False
        self.connections = set()
        self.handlers = set()
        self.server = None
        self.last_error = None

    async def start(self):
        self.server = await asyncio.start_server(self.handle, self.host, self.port, limit=MAX_HEADER)
        self.port = self.server.sockets[0].getsockname()[1]
        return self

    async def handle(self, reader, writer):
        if len(self.connections) >= 8:
            writer.close()
            await writer.wait_closed()
            return
        self.connections.add(writer)
        handler = asyncio.current_task()
        self.handlers.add(handler)
        bridge = None
        owns_import = False
        try:
            version, op, status = COMMON.unpack(await asyncio.wait_for(reader.readexactly(8), 5))
            if version != VERSION or status != 0 or op not in (DEVLIST, IMPORT):
                raise ProtocolError('invalid USB/IP management header')
            busid = None
            if op == IMPORT:
                raw = await asyncio.wait_for(reader.readexactly(32), 5)
                if b'\0' not in raw or any(raw[raw.index(0):]):
                    raise ProtocolError('invalid import busid padding')
                busid = raw.split(b'\0', 1)[0].decode('ascii')
                if self.imported:
                    writer.write(COMMON.pack(VERSION, op & 0x7fff, 2))
                    await writer.drain()
                    return
                self.imported = owns_import = True
            try:
                bridge = await Bridge.open(self.context, 'usbip' if op == IMPORT else 'discovery')
                device = await bridge.describe()
            except (Blocked, ProtocolError, OSError, asyncio.TimeoutError, asyncio.IncompleteReadError):
                writer.write(COMMON.pack(VERSION, op & 0x7fff, 0 if op == DEVLIST else 1))
                if op == DEVLIST:
                    writer.write(struct.pack('!I', 0))
                await writer.drain()
                return
            if op == DEVLIST:
                writer.write(COMMON.pack(VERSION, op & 0x7fff, 0) + struct.pack('!I', 1) + device.wire(self.context.run_id))
                for interface in device.interfaces:
                    writer.write(struct.pack('!BBBB', *interface, 0))
                await writer.drain()
                return
            if busid != device.busid:
                writer.write(COMMON.pack(VERSION, op & 0x7fff, 1))
                await writer.drain()
                return
            response, payload = await bridge.ask('reset')
            if payload:
                raise ProtocolError('unexpected reset payload')
            writer.write(COMMON.pack(VERSION, op & 0x7fff, 0) + device.wire(self.context.run_id))
            await writer.drain()
            await ImportSession(reader, writer, bridge, device, self.urb_timeout).run()
        except (OSError, UnicodeError, asyncio.TimeoutError, asyncio.IncompleteReadError, Blocked, ProtocolError) as error:
            self.last_error = str(error)
        finally:
            if bridge:
                await bridge.close()
            if owns_import:
                self.imported = False
            self.connections.discard(writer)
            self.handlers.discard(handler)
            writer.close()
            try:
                await writer.wait_closed()
            except (ConnectionError, OSError):
                pass

    async def close(self):
        if self.server:
            self.server.close()
            if hasattr(self.server, 'close_clients'):
                self.server.close_clients()
            await self.server.wait_closed()
        for writer in tuple(self.connections):
            writer.close()
        for handler in tuple(self.handlers):
            handler.cancel()
        await asyncio.gather(*tuple(self.handlers), return_exceptions=True)


def write_owned_json(path, record):
    """Replace only a known owned file inside an owned run directory."""
    path = Path(path)
    if path.exists() or path.is_symlink():
        info = path.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
            raise Blocked('refusing unsafe state file: ' + str(path))
    temporary = path.with_name(path.name + '.' + str(os.getpid()) + '.new')
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        with os.fdopen(fd, 'w') as output:
            json.dump(record, output, allow_nan=False, sort_keys=True)
            output.write('\n')
            output.flush()
            os.fsync(output.fileno())
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


async def serve(args):
    context = Context.create(args.run_dir, args.qmp, args.backend, args.lease, args.vm_pid, args.run_id)
    lock = os.open(context.run_dir / 'usb-server.lock', os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    server = None
    try:
        info = os.fstat(lock)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
            raise Blocked('server lock must be an owned private regular file')
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        server = await UsbIpServer(context, port=args.port).start()
        ready = context.run_dir / 'usb-server.json'
        write_owned_json(ready, {'run_id': context.run_id, 'lease_id': context.lease_id,
                                'pid': os.getpid(), 'port': server.port, 'host': server.host})
        print(json.dumps({'listening': True, 'host': server.host, 'port': server.port,
                          'guest_enumeration_verified': False}), flush=True)
        stop = asyncio.Event()
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(sig, stop.set)
        await stop.wait()
    finally:
        if server:
            await server.close()
        os.close(lock)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('run-dir', 'qmp', 'backend', 'lease'):
        parser.add_argument('--' + name, required=True)
    parser.add_argument('--vm-pid', required=True, type=int)
    parser.add_argument('--run-id')
    parser.add_argument('--port', type=int, default=0)
    args = parser.parse_args()
    try:
        asyncio.run(serve(args))
    except KeyboardInterrupt:
        pass
    except (ValueError, RuntimeError, OSError) as error:
        print(json.dumps({'blocked': True, 'reason': str(error)}), file=sys.stderr)
        return 2
    return 0


if __name__ == '__main__':
    sys.exit(main())
