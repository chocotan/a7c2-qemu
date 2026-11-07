"""Synthetic endpoint fixture only: never a production device or authentication implementation."""
import asyncio
import os
import struct

from usbip_server import encode_frame, read_frame

DEVICE_BYTES = bytes.fromhex('120100020000004034127856000101020301')
CONFIG_BYTES = (struct.pack('<BBHBBBBB', 9, 2, 32, 1, 1, 0, 0x80, 50) +
                bytes((9, 4, 0, 0, 2, 0xff, 0, 0, 0)) +
                struct.pack('<BBBBHB', 7, 5, 0x01, 2, 512, 0) +
                struct.pack('<BBBBHB', 7, 5, 0x81, 2, 512, 0))
DESCRIPTORS = DEVICE_BYTES + CONFIG_BYTES
METADATA = {'busid': 'synthetic-1', 'busnum': 7, 'devnum': 9, 'speed': 3,
            'configuration_value': 1, 'descriptor_source': 'guest-ep0'}


class SyntheticBackend:
    def __init__(self, context):
        self.context = context
        self.ready = True
        self.bad_identity = False
        self.hold = set()
        self.replies = {}
        self.in_bytes = b'\x00\xff\x17\x80\x01\xa5\x5a\x13'
        self.events = []
        self.submitted = asyncio.Queue()
        self.active = {}
        self.writers = set()
        self.data_writers = set()
        self.tasks = set()
        self.fragment = False
        self.cancel_status = 0
        self.duplicate_completion = False
        self.server = None
        self.connection_number = 0

    async def start(self):
        self.server = await asyncio.start_unix_server(self.handle, self.context.backend_path)
        os.chmod(self.context.backend_path, 0o600)
        return self

    async def send(self, writer, header, payload=b''):
        data = encode_frame(header, payload)
        if self.fragment:
            for offset in range(0, len(data), 3):
                writer.write(data[offset:offset + 3])
                await writer.drain()
                await asyncio.sleep(0)
        else:
            writer.write(data)
            await writer.drain()

    async def handle(self, reader, writer):
        task = asyncio.current_task()
        self.tasks.add(task)
        self.writers.add(writer)
        self.connection_number += 1
        owner = self.connection_number
        role = None
        try:
            while True:
                header, payload = await read_frame(reader, timeout=None)
                op = header['op']
                self.events.append((op, dict(header), payload))
                answer = {'version': 1, 'op': op, 'id': header['id'], 'ok': True}
                if op == 'hello':
                    role = header['role']
                    if role == 'usbip':
                        self.data_writers.add(writer)
                    answer.update(self.context.identity(), role=role)
                    if self.bad_identity:
                        answer['lease'] = 'wrong-lease'
                elif op == 'describe':
                    if self.ready:
                        answer.update(ready=True, device=dict(METADATA))
                        await self.send(writer, answer, DESCRIPTORS)
                        continue
                    answer.update(ready=False, reason='synthetic fixture explicitly not ready')
                elif op == 'vbus':
                    answer['present'] = header['present']
                elif op == 'reset':
                    pass
                elif op == 'submit':
                    self.active[owner, header['id']] = (writer, header, payload)
                    await self.submitted.put((owner, header, payload))
                    if header['seqnum'] in self.hold:
                        continue
                    await self.complete(owner, header['id'])
                    continue
                elif op == 'cancel':
                    if self.cancel_status == 0:
                        self.active.pop((owner, header['target']), None)
                    answer.update(op='cancelled', target=header['target'], status=self.cancel_status)
                else:
                    answer['ok'] = False
                await self.send(writer, answer)
        except (asyncio.IncompleteReadError, ConnectionError, OSError):
            pass
        finally:
            for key in list(self.active):
                if key[0] == owner:
                    del self.active[key]
            self.events.append(('owner_closed', {'owner': owner, 'role': role}, b''))
            self.data_writers.discard(writer)
            self.writers.discard(writer)
            writer.close()
            try:
                await writer.wait_closed()
            except (OSError, ConnectionError):
                pass
            self.tasks.discard(task)

    async def complete(self, owner, request_id):
        writer, header, _ = self.active.pop((owner, request_id))
        options = self.replies.get(header['seqnum'], {})
        data = options.get('data', self.in_bytes[:header['transfer_length']]) if header['direction'] else b''
        actual = options.get('actual_length', len(data) if header['direction'] else header['transfer_length'])
        answer = {'version': 1, 'op': 'complete', 'id': request_id, 'ok': True,
                  'status': options.get('status', 0), 'actual_length': actual,
                  'start_frame': 0, 'num_packets': 0, 'error_count': 0}
        await self.send(writer, answer, data)
        if self.duplicate_completion:
            await self.send(writer, answer, data)

    async def drop_data(self):
        for writer in tuple(self.data_writers):
            writer.close()
        await asyncio.sleep(0)

    async def close(self):
        if self.server:
            self.server.close()
            await self.server.wait_closed()
        for writer in tuple(self.writers):
            writer.close()
        if self.tasks:
            await asyncio.gather(*tuple(self.tasks), return_exceptions=True)
        self.context.backend_path.unlink(missing_ok=True)
