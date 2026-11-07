#!/usr/bin/env python3
"""Synthetic guest integration: real QEMU RAM/TRBs/IRQ and real Unix/TCP bridge.

Only an isolated binary with the generated board fragment and explicit test
VBUS loopback is accepted. No host module, VHCI attach or Sony claim is made.
By default QEMU runs in bwrap's user/PID/network namespace to test host PID binding.
"""
import argparse
import asyncio
import contextlib
import importlib.util
import json
import os
from pathlib import Path
import secrets
import shutil
import socket
import struct
import subprocess
import sys
import tempfile

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('dwc3_usbip', HERE / 'usbip_server.py')
usbip = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = usbip
spec.loader.exec_module(usbip)

DEVICE = bytes.fromhex('1201000200000040feca0140000101020301')
CONFIG = bytes.fromhex('0902300001010080320904000002ff0000000705810240000007050202400000'
                       '0904000101ff00000007058302400000')
assert len(DEVICE) == 18 and len(CONFIG) == 48


def frame(d, payload=b''):
    raw = json.dumps(d, separators=(',', ':')).encode()
    return struct.pack('!II', len(raw), len(payload)) + raw + payload


class VM:
    def __init__(self, binary, output, namespace=True, loopback=True):
        self.binary, self.output, self.namespace, self.loopback = binary, output, namespace, loopback
        self.replacement = False
        self.temporary = tempfile.TemporaryDirectory(prefix='sdwc-bridge-')
        self.run = Path(self.temporary.name)
        self.backend = self.run / 'usb-endpoint.sock'
        self.lease = secrets.token_hex(32)
        self.lock = asyncio.Lock()
        self.qmp_lock = asyncio.Lock()
        self.owner_pid = None
        self.process = None
        self.sockets = []
        self.qt = None

    async def start(self):
        self.output.mkdir(parents=True, exist_ok=True)
        for name in ('qtest', 'qmp'):
            listener = socket.socket(socket.AF_UNIX)
            listener.bind(str(self.run / name))
            listener.listen(1)
            listener.setblocking(False)
            self.sockets.append(listener)
        inside_run = Path('/out') if self.namespace else self.run
        env = {'QEMU_SONY_DWC3_CORE_TEST': '1', 'QEMU_SONY_DWC3_BRIDGE_TEST_LOOPBACK': '1',
               'QEMU_SONY_USB_RUN_ID': self.run.name, 'QEMU_SONY_USB_LEASE': self.lease,
               'QEMU_SONY_USB_QMP_HOST_PATH': str(self.run / 'qmp-host-identity.sock'),
               'QEMU_SONY_USB_BACKEND_SOCKET': str(inside_run / 'usb-endpoint.sock')}
        if not self.loopback:
            env.pop('QEMU_SONY_DWC3_BRIDGE_TEST_LOOPBACK')
        command = [str(self.binary), '-machine', 'virt,gic-version=3', '-cpu', 'cortex-a53',
                   '-m', '64M', '-S', '-nodefaults', '-display', 'none', '-serial', 'none',
                   '-monitor', 'none', '-qtest', f'unix:{inside_run}/qtest',
                   '-qmp', f'unix:{inside_run}/qmp', '-qtest-log', str(self.output / 'qtest-wire.log')]
        if self.namespace:
            assert shutil.which('bwrap'), 'bwrap required for namespace test'
            prefix = ['bwrap', '--unshare-user', '--unshare-pid', '--unshare-net',
                      '--die-with-parent', '--tmpfs', '/', '--ro-bind', '/usr', '/usr',
                      '--ro-bind', '/etc', '/etc', '--symlink', 'usr/bin', '/bin',
                      '--symlink', 'usr/lib', '/lib', '--symlink', 'usr/lib', '/lib64',
                      '--ro-bind', str(self.binary.parent), str(self.binary.parent),
                      '--bind', str(self.run), str(inside_run),
                      '--bind', str(self.output), str(self.output), '--proc', '/proc', '--dev', '/dev', '--clearenv',
                      '--setenv', 'PATH', '/usr/bin:/bin', '--setenv', 'LC_ALL', 'C']
            for key, value in env.items():
                prefix += ['--setenv', key, value]
            command = prefix + command
        self.stderr = (self.output / 'qemu-stderr.log').open('wb')
        self.process = subprocess.Popen(command, env={**os.environ, **env}, stderr=self.stderr)
        loop = asyncio.get_running_loop()
        qt, _ = await asyncio.wait_for(loop.sock_accept(self.sockets[0]), 10)
        qmp, _ = await asyncio.wait_for(loop.sock_accept(self.sockets[1]), 10)
        self.owner_pid = struct.unpack('3i', qmp.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12))[0]
        self.qtr, self.qtw = await asyncio.open_unix_connection(sock=qt, limit=3 * 1048576)
        self.qmr, self.qmw = await asyncio.open_unix_connection(sock=qmp)
        assert json.loads(await self.qmr.readline())['QMP']
        await self.qmp('qmp_capabilities')
        status = Path(f'/proc/{self.owner_pid}/status').read_text()
        self.nspid = next((line.split()[1:] for line in status.splitlines() if line.startswith('NSpid:')), [])
        if self.namespace:
            assert len(self.nspid) >= 2 and int(self.nspid[-1]) != self.owner_pid, self.nspid
        children = await self.qmp('qom-list', {'path': '/machine/unattached'})
        self.gadget = '/machine/unattached/' + next(x['name'] for x in children if x['type'] == 'child<sony-dwc3-gadget>')
        self.gic = '/machine/unattached/' + next(x['name'] for x in children if x['type'] == 'child<arm-gicv3>')
        self.edges = []
        await self.qt_call(f'irq_intercept_in {self.gic}')
        self.identity = {'run_id': self.run.name, 'lease': self.lease,
                         'qmp_path': env['QEMU_SONY_USB_QMP_HOST_PATH'], 'vm_pid': self.owner_pid}
        self.backend = self.run / 'usb-endpoint.sock'
        assert self.backend.stat().st_mode & 0o777 == 0o600

    async def qmp(self, op, arguments=None):
        async with self.qmp_lock:
            self.qmw.write(json.dumps({'execute': op, 'arguments': arguments or {}}).encode() + b'\n')
            await self.qmw.drain()
            while True:
                result = json.loads(await asyncio.wait_for(self.qmr.readline(), 5))
                if 'event' not in result:
                    assert 'return' in result, result
                    return result['return']

    async def qt_call(self, command):
        async with self.lock:
            self.qtw.write(command.encode() + b'\n')
            await self.qtw.drain()
            while True:
                reply = (await asyncio.wait_for(self.qtr.readline(), 5)).decode().strip()
                if reply.startswith('IRQ '):
                    self.edges.append(reply)
                    continue
                assert reply.startswith('OK'), (command[:100], reply)
                return reply[2:].strip()

    async def wr(self, offset, value):
        await self.qt_call(f'writel {0xf10c0000 + offset:#x} {value:#x}')

    async def rd(self, offset):
        return int(await self.qt_call(f'readl {0xf10c0000 + offset:#x}'), 0)

    async def write(self, address, data):
        for offset in range(0, len(data), 4096):
            part = data[offset:offset + 4096]
            await self.qt_call(f'write {address + offset:#x} {len(part)} 0x{part.hex()}')

    async def read(self, address, length):
        return bytes.fromhex((await self.qt_call(f'read {address:#x} {length}')).removeprefix('0x'))

    async def raw(self, role='control', **changes):
        reader, writer = await asyncio.open_unix_connection(self.backend)
        hello = {'version': 1, 'op': 'hello', 'id': 1, **self.identity, 'role': role, **changes}
        writer.write(frame(hello)); await writer.drain()
        return reader, writer

    async def client(self, role='control'):
        reader, writer = await self.raw(role)
        header, payload = await usbip.read_frame(reader)
        assert header['ok'] is True and not payload
        assert all(header[k] == v for k, v in self.identity.items())
        return reader, writer

    async def stop(self):
        if self.process is not None and self.process.poll() is None:
            await self.qmp('quit')
            assert await asyncio.to_thread(self.process.wait, 10) == 0
        for listener in self.sockets:
            listener.close()
        if hasattr(self, 'stderr'):
            self.stderr.close()
        if self.backend.exists() and not self.replacement:
            raise AssertionError('owned endpoint socket was not cleaned at QMP quit')
        if self.replacement:
            assert self.backend.read_bytes() == b'foreign replacement preserved\n'
        self.temporary.cleanup()


class Guest:
    def __init__(self, vm):
        self.vm = vm
        self.event_position = 0
        self.phase = 'setup'
        self.setup = b''
        self.control_requests = []
        self.running = True
        self.bulk_events = 0
        self.device_descriptor = DEVICE

    async def command(self, ep, op, p0=0, p1=0):
        await self.vm.wr(0xc800 + ep * 16 + 8, p0)
        await self.vm.wr(0xc800 + ep * 16 + 4, p1)
        await self.vm.wr(0xc800 + ep * 16 + 12, 0x400 | op)

    async def trb(self, ep, address, buffer, length, kind, flags=0x803):
        await self.vm.write(address, struct.pack('<IIII', buffer, 0, length, kind << 4 | flags))
        await self.command(ep, 6, 0, address)

    async def setup_start(self):
        self.phase = 'setup'
        await self.trb(0, 0x40004000, 0x40005000, 8, 2)

    async def init(self):
        await self.vm.wr(0xc400, 0x40001000)
        await self.vm.wr(0xc404, 0)
        await self.vm.wr(0xc408, 0x1000)
        await self.vm.wr(0xc708, 7)
        for ep in (0, 1, 2, 3, 4):
            await self.command(ep, 1, (64 << 3) | (0 if ep < 2 else 4), (ep << 25) | 0x700)
            await self.command(ep, 2, 1)
        await self.vm.wr(0xc720, 31)
        await self.setup_start()
        await self.vm.wr(0xc704, 1 << 31)

    async def loop(self):
        while self.running:
            count = await self.vm.rd(0xc40c)
            if not count:
                await asyncio.sleep(.002)
                continue
            events = []
            for _ in range(count // 4):
                events.append(struct.unpack('<I', await self.vm.read(0x40001000 + self.event_position, 4))[0])
                self.event_position = (self.event_position + 4) % 0x1000
            await self.vm.wr(0xc40c, count)
            for event in events:
                if event & 1:
                    continue
                ep, kind, status = event >> 1 & 31, event >> 6 & 15, event >> 12 & 15
                if ep >= 2:
                    self.bulk_events += 1
                    continue
                if kind == 1 and self.phase == 'setup':
                    self.setup = await self.vm.read(0x40005000, 8)
                    self.control_requests.append(self.setup.hex())
                    length = int.from_bytes(self.setup[6:8], 'little')
                    if length:
                        if self.setup[1] == 6:
                            answer = self.device_descriptor if self.setup[3] == 1 else CONFIG
                        elif self.setup[1] == 0x5a:
                            answer = b'guest-ep0-roundtrip'
                        else:
                            raise AssertionError(('unexpected synthetic setup', self.setup.hex()))
                        answer = answer[:length]
                        self.phase = 'data'
                        await self.vm.write(0x40006000, answer)
                        await self.trb(1, 0x40004010, 0x40006000, len(answer), 5)
                    else:
                        self.phase = 'status'
                elif kind == 1 and self.phase == 'data':
                    self.phase = 'status'
                elif kind == 3 and status == 2:
                    self.phase = 'status'
                    length = int.from_bytes(self.setup[6:8], 'little')
                    await self.trb(ep, 0x40004020, 0, 0, 4 if length else 3)
                elif kind == 1 and self.phase == 'status':
                    await self.setup_start()


async def rpc(reader, writer, request, payload=b''):
    writer.write(frame({'version': 1, **request}, payload)); await writer.drain()
    return await asyncio.wait_for(usbip.read_frame(reader), 5)


def submit(request_id, *, ep=1, direction=1, length=8, flags=0, setup='0000000000000000'):
    return {'version': 1, 'op': 'submit', 'id': request_id, 'seqnum': request_id,
            'devid': 0x10001, 'direction': direction, 'endpoint': ep,
            'transfer_flags': flags, 'transfer_length': length, 'start_frame': 0,
            'num_packets': 0, 'interval': 0, 'setup': setup}


async def run(binary, output, namespace):
    vm = VM(binary, output, namespace)
    guest_task = None
    server = None
    try:
        await vm.start()
        # Identity is prebound; malformed handshakes never become clients.
        for changes in ({'lease': 'x' * 64}, {'run_id': 'foreign'}, {'vm_pid': vm.owner_pid + 10}):
            if 'vm_pid' in changes:
                continue  # Establish the legitimate host PID before mismatch testing.
            r, w = await vm.raw(**changes)
            assert await asyncio.wait_for(r.read(), 2) == b''
            w.close(); await w.wait_closed()
        cr, cw = await vm.client()
        r, w = await vm.raw(vm_pid=vm.owner_pid + 10)
        assert await asyncio.wait_for(r.read(), 2) == b''
        w.close(); await w.wait_closed()
        reply, raw = await rpc(cr, cw, {'op': 'describe', 'id': 2})
        assert reply['ready'] is False and not raw and 'device' not in reply
        guest = Guest(vm)
        await guest.init()
        reply, raw = await rpc(cr, cw, {'op': 'vbus', 'id': 3, 'present': True})
        assert reply['ok'] is True and reply['present'] is True
        guest_task = asyncio.create_task(guest.loop())
        for request_id in range(4, 200):
            reply, raw = await rpc(cr, cw, {'op': 'describe', 'id': request_id})
            if reply['ready']:
                break
            if guest_task.done():
                await guest_task
            await asyncio.sleep(.01)
        assert reply['ready'] is True and raw == DEVICE + CONFIG, (reply, raw.hex())
        assert guest.control_requests[:3] == ['8006000100001200', '8006000200000900', '8006000200003000']
        assert 'IRQ raise 184' in vm.edges
        # These are actual existing Python USB/IP components, over real Unix/TCP.
        context = usbip.Context.create(vm.run, vm.identity['qmp_path'], vm.backend, vm.lease, vm.owner_pid, vm.run.name)
        server = usbip.UsbIpServer(context, port=0)
        await server.start()
        port = server.server.sockets[0].getsockname()[1]
        tr, tw = await asyncio.open_connection('127.0.0.1', port)
        tw.write(struct.pack('!HHI', 0x111, 0x8005, 0)); await tw.drain()
        management = await tr.readexactly(12)
        assert struct.unpack('!HHII', management) == (0x111, 5, 0, 1)
        wire = await tr.readexactly(usbip.DEVICE.size + 4)
        assert usbip.DEVICE.unpack(wire[:usbip.DEVICE.size])[5:7] == (0xcafe, 0x4001)
        tw.close(); await tw.wait_closed()
        tr, tw = await asyncio.open_connection('127.0.0.1', port)
        tw.write(struct.pack('!HHI', 0x111, 0x8003, 0) + b'dwc3-1'.ljust(32, b'\0'))
        await tw.drain()
        assert struct.unpack('!HHI', await tr.readexactly(8)) == (0x111, 3, 0)
        await tr.readexactly(usbip.DEVICE.size)
        setup = bytes.fromhex('c05a000000004000')
        urb = struct.pack('!IIIII', 1, 700, 0x10001, 1, 0) + struct.pack('!Iiiii8s', 0x204, 64, 0, 0, 0, setup)
        tw.write(urb); await tw.drain()
        returned = await asyncio.wait_for(tr.readexactly(48), 5)
        cmd, seq, devid, direction, ep = struct.unpack('!IIIII', returned[:20])
        status, actual = struct.unpack('!ii', returned[20:28])
        assert (cmd, seq, devid, direction, ep, status, actual) == (3, 700, 0x10001, 1, 0, 0, 19), returned.hex()
        assert await tr.readexactly(actual) == b'guest-ep0-roundtrip'
        tw.close(); await tw.wait_closed()
        # Wait for the import owner to release; unrelated control stayed alive.
        await asyncio.sleep(.03)
        r, w = await vm.client('usbip')
        reply, _ = await rpc(r, w, {'op': 'reset', 'id': 2})
        assert reply['ok'] is True
        w.write(frame(submit(3))); await w.drain()
        await asyncio.sleep(.02)
        reply, raw = await rpc(r, w, {'op': 'cancel', 'id': 4, 'target': 3})
        assert reply['op'] == 'cancelled' and reply['status'] == 0 and not raw
        # Canceled host request cannot DMA even when the guest posts a transfer.
        await guest.trb(3, 0x40008000, 0x40009000, 5, 1)
        assert struct.unpack('<I', await vm.read(0x4000800c, 4))[0] & 1
        reply, raw = await rpc(r, w, submit(5, length=8, flags=0x2004))
        assert reply['status'] == -95 and not raw
        await vm.write(0x40009000, b'bulk!')
        reply, raw = await rpc(r, w, submit(6, length=8, flags=0x204))
        assert reply['actual_length'] == 5 and raw == b'bulk!'
        await guest.trb(4, 0x40008010, 0x4000a000, 64, 1)
        out = submit(7, ep=2, direction=0, length=7, flags=0x104)
        out['start_frame'] = -1
        encoded = frame(out, b'out-dma')
        w.write(encoded[:-4]); await w.drain(); await asyncio.sleep(.003)
        w.write(encoded[-4:]); await w.drain()
        reply, raw = await usbip.read_frame(r)
        assert reply['actual_length'] == 7 and not raw
        assert await vm.read(0x4000a000, 7) == b'out-dma'
        assert struct.unpack('<I', await vm.read(0x40008018, 4))[0] == 57
        # An advertised alternate endpoint passes framing, but disabled guest
        # hardware retains its URB as pending until canceled, never empty success.
        w.write(frame(submit(8, ep=3, length=0))); await w.drain()
        await asyncio.sleep(.01)
        reply, _ = await rpc(r, w, {'op': 'cancel', 'id': 9, 'target': 8})
        assert reply['op'] == 'cancelled'
        w.close(); await w.wait_closed(); await asyncio.sleep(.02)
        # Duplicate keys, wrong JSON types, invalid setup and oversized frames.
        bad = [b'{"version":1,"op":"describe","id":9,"id":10}',
               b'{"version":1,"op":"describe","id":true}',
               b'{"version":1,"op":"describe","id":9.0}',
               b"{'version':1,'op':'describe','id':9}",
               b'{"version":1,"op":"describe","id":NaN}']
        for raw in bad:
            rr, ww = await vm.client()
            ww.write(struct.pack('!II', len(raw), 0) + raw); await ww.drain()
            assert await asyncio.wait_for(rr.read(), 2) == b''
            ww.close(); await ww.wait_closed()
        rr, ww = await vm.client()
        ww.write(struct.pack('!II', 16385, 0)); await ww.drain()
        assert await asyncio.wait_for(rr.read(), 2) == b''
        ww.close(); await ww.wait_closed()
        rr, ww = await vm.client()
        encoded = frame({'version': 1, 'op': 'describe', 'id': 22})
        for fragment in (encoded[:3], encoded[3:9], encoded[9:]):
            ww.write(fragment); await ww.drain(); await asyncio.sleep(.003)
        fragmented, raw = await usbip.read_frame(rr)
        assert fragmented['ready'] is True and raw == DEVICE + CONFIG
        ww.close(); await ww.wait_closed()
        # A discovery owner closing does not affect a data owner's queued URB.
        rr, ww = await vm.client('usbip')
        ww.write(frame(submit(8))); await ww.drain()
        xr, xw = await vm.client('discovery')
        xw.close(); await xw.wait_closed(); await asyncio.sleep(.01)
        await vm.write(0x40009000, b'owned')
        await guest.trb(3, 0x40008000, 0x40009000, 5, 1)
        ownership, raw = await usbip.read_frame(rr)
        assert ownership['id'] == 8 and raw == b'owned'
        # Same live RPC id is rejected, and its owner's URBs are canceled.
        duplicate = frame(submit(9))
        ww.write(duplicate + duplicate); await ww.drain()
        assert await asyncio.wait_for(rr.read(), 2) == b''
        ww.close(); await ww.wait_closed(); await asyncio.sleep(.02)
        # Inconsistent EP0 length rejected before waiting for an OUT payload.
        rr, ww = await vm.client('usbip')
        wrong = submit(10, ep=0, direction=0, length=8, setup='0000000000000400')
        raw = json.dumps(wrong).encode()
        ww.write(struct.pack('!II', len(raw), 8) + raw); await ww.drain()
        assert await asyncio.wait_for(rr.read(), 2) == b''
        ww.close(); await ww.wait_closed(); await asyncio.sleep(.02)
        # A 9MiB aggregate reservation is rejected before payload allocation.
        rr, ww = await vm.client('usbip')
        ww.write(b''.join(frame(submit(i, length=1048576)) for i in range(2, 11)))
        await ww.drain()
        assert await asyncio.wait_for(rr.read(), 2) == b''
        ww.close(); await ww.wait_closed(); await asyncio.sleep(.02)
        # All 32 owner URBs are canceled on budget rejection/connection loss.
        rr, ww = await vm.client('usbip')
        ww.write(b''.join(frame(submit(i, length=0)) for i in range(2, 35)))
        await ww.drain()
        assert await asyncio.wait_for(rr.read(), 2) == b''
        ww.close(); await ww.wait_closed(); await asyncio.sleep(.02)
        rr, ww = await vm.client('usbip')
        # Three 1MiB IN completions cannot grow an unread send queue indefinitely.
        await vm.write(0x40100000, b'Z' * 1048576)
        for i in range(3):
            await vm.write(0x40008000 + i * 16, struct.pack('<IIII', 0x40100000, 0, 1048576, 0x811))
        await guest.command(3, 6, 0, 0x40008000)
        ww.write(b''.join(frame(submit(i, length=1048576)) for i in range(2, 5)))
        await ww.drain(); await asyncio.sleep(.05)
        consumed = await asyncio.wait_for(rr.read(4 * 1048576), 3)
        while consumed:
            consumed = await asyncio.wait_for(rr.read(4 * 1048576), 3)
        ww.close(); await ww.wait_closed(); await asyncio.sleep(.02)
        rr, ww = await vm.client('usbip')
        reply, _ = await rpc(cr, cw, {'op': 'vbus', 'id': 1000, 'present': False})
        assert reply['ok'] is True
        event, _ = await usbip.read_frame(rr)
        assert event['op'] == 'event' and event['kind'] == 'disconnect'
        ww.close(); await ww.wait_closed()
        reply, raw = await rpc(cr, cw, {'op': 'describe', 'id': 1001})
        assert reply['ready'] is False and not raw
        # An invalid descriptor produced by guest RAM must never be exported.
        guest.device_descriptor = b'\x11' + DEVICE[1:]
        reply, _ = await rpc(cr, cw, {'op': 'vbus', 'id': 1002, 'present': True})
        assert reply['ok'] is True
        await guest.setup_start()
        for request_id in range(1003, 1009):
            reply, raw = await rpc(cr, cw, {'op': 'describe', 'id': request_id})
            assert reply['ready'] is False and not raw
            await asyncio.sleep(.015)
        assert 'descriptor' in reply['reason']
        await rpc(cr, cw, {'op': 'vbus', 'id': 1009, 'present': False})
        guest.device_descriptor = DEVICE
        # Guest drops/re-enables the pull-up while connected: cached bytes expire.
        reply, _ = await rpc(cr, cw, {'op': 'vbus', 'id': 1010, 'present': True})
        assert reply['ok'] is True
        await guest.setup_start()
        for request_id in range(1011, 1200):
            reply, raw = await rpc(cr, cw, {'op': 'describe', 'id': request_id})
            if reply['ready']:
                break
            await asyncio.sleep(.01)
        assert reply['ready'] is True and raw == DEVICE + CONFIG
        rr, ww = await vm.client('usbip')
        await vm.wr(0xc704, 0)
        event, _ = await usbip.read_frame(rr)
        assert event['kind'] == 'disconnect'
        ww.close(); await ww.wait_closed()
        reply, raw = await rpc(cr, cw, {'op': 'describe', 'id': 1201})
        assert reply['ready'] is False and not raw
        cw.close(); await cw.wait_closed()
        guest.running = False
        await guest_task; guest_task = None
        await server.close(); server = None
        result = {'schema': 'a7c2.dwc3-bridge-test.v1', 'synthetic_guest_only': True,
                  'namespace': namespace, 'namespace_socket': '/out/usb-endpoint.sock' if namespace else str(vm.backend),
                  'host_pid': vm.owner_pid, 'namespace_pid': vm.nspid[-1],
                  'descriptor_source': 'guest-ep0', 'descriptors_sha256': __import__('hashlib').sha256(DEVICE + CONFIG).hexdigest(),
                  'real_unix_and_usbip_tcp_roundtrip': True, 'core_urb_dma_and_irq': True,
                  'identity_types_budget_cancel_disconnect_pass': True, 'irq_edges': len(vm.edges),
                  'guest_setup_requests': guest.control_requests, 'original_sony_enumerated': False,
                  'host_vhci_attached': False, 'jiritsu_authenticated': False}
        (output / 'bridge-result.json').write_text(json.dumps(result, indent=2) + '\n')
        print(json.dumps(result, indent=2))
    finally:
        if guest_task:
            guest_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await guest_task
        if server:
            await server.close()
        await vm.stop()


async def blocked_checks(binary, output, namespace):
    vm = VM(binary, output, namespace, loopback=False)
    try:
        await vm.start()
        reader, writer = await vm.client()
        reply, payload = await rpc(reader, writer, {'op': 'vbus', 'id': 2, 'present': True})
        assert reply['ok'] is False and reply['status'] == -95 and not payload
        reply, payload = await rpc(reader, writer, {'op': 'describe', 'id': 3})
        assert reply['ready'] is False and not payload
        writer.close(); await writer.wait_closed()
        # Cleanup only the inode created by this bridge, never a replacement.
        vm.backend.unlink()
        vm.backend.write_bytes(b'foreign replacement preserved\n')
        vm.replacement = True
    finally:
        await vm.stop()
    # Failed bind must preserve an already existing foreign file as well.
    with tempfile.TemporaryDirectory(prefix='sdwc-foreign-') as temp:
        run_dir = Path(temp)
        path = run_dir / 'endpoint'
        path.write_bytes(b'foreign existing preserved\n')
        command = [str(binary), '-machine', 'virt,gic-version=3', '-S', '-nodefaults',
                   '-display', 'none', '-serial', 'none', '-monitor', 'none']
        env = {**os.environ, 'QEMU_SONY_DWC3_CORE_TEST': '1',
               'QEMU_SONY_USB_RUN_ID': run_dir.name, 'QEMU_SONY_USB_LEASE': secrets.token_hex(32),
               'QEMU_SONY_USB_QMP_HOST_PATH': str(run_dir / 'qmp'), 'QEMU_SONY_USB_BACKEND_SOCKET': str(path)}
        result = await asyncio.to_thread(subprocess.run, command, env=env, capture_output=True, timeout=10)
        assert result.returncode != 0 and path.read_bytes() == b'foreign existing preserved\n'
        (output / 'foreign-bind-stderr.log').write_bytes(result.stderr)
    (output / 'blocked-result.json').write_text(json.dumps({
        'unwired_vbus_rejected': True, 'unready_device_not_exported': True,
        'socket_replacement_preserved': True, 'foreign_existing_file_preserved': True}) + '\n')


async def all_tests(binary, output, namespace):
    await run(binary, output / 'functional', namespace)
    await blocked_checks(binary, output / 'blocked', namespace)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('binary', type=Path)
    parser.add_argument('output', type=Path)
    parser.add_argument('--without-namespace', action='store_true')
    args = parser.parse_args()
    asyncio.run(all_tests(args.binary.resolve(), args.output.resolve(), not args.without_namespace))
