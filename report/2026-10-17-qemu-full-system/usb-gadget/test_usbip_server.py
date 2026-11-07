#!/usr/bin/env python3
"""Synthetic bridge tests; no Sony device, host modules or VM are used."""
import asyncio
import json
import os
from pathlib import Path
import struct
import tempfile
import unittest

import usbip_server as usb
from test_support import DESCRIPTORS, METADATA, SyntheticBackend


class UsbIpTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='usbip-synthetic-')
        self.run = Path(self.tmp.name)
        self.context = usb.Context.create(self.run, self.run / 'qmp.sock', self.run / 'endpoint.sock',
                                         't' * 48, os.getpid(), 'synthetic-test')
        self.backend = await SyntheticBackend(self.context).start()
        self.server = await usb.UsbIpServer(self.context, urb_timeout=0.08).start()
        self.clients = []

    async def asyncTearDown(self):
        for _, writer in self.clients:
            writer.close()
        for _, writer in self.clients:
            await writer.wait_closed()
        await self.server.close()
        await self.backend.close()
        await asyncio.sleep(0)
        self.tmp.cleanup()

    async def client(self):
        reader, writer = await asyncio.open_connection('127.0.0.1', self.server.port)
        self.clients.append((reader, writer))
        return reader, writer

    async def imported(self):
        reader, writer = await self.client()
        writer.write(usb.COMMON.pack(usb.VERSION, usb.IMPORT, 0) + b'synthetic-1'.ljust(32, b'\0'))
        await writer.drain()
        self.assertEqual(usb.COMMON.unpack(await reader.readexactly(8)), (usb.VERSION, 3, 0))
        self.assertEqual(await reader.readexactly(usb.DEVICE.size), usb.GuestDevice.parse(METADATA, DESCRIPTORS).wire('synthetic-test'))
        return reader, writer

    def submit(self, seq, direction, length, endpoint=1, data=b'', setup=bytes(8), **overrides):
        device = usb.GuestDevice.parse(METADATA, DESCRIPTORS)
        body = {'flags': 0, 'frame': 0, 'packets': 0, 'interval': 0, **overrides}
        return (usb.BASIC.pack(usb.SUBMIT, seq, device.devid, direction, endpoint) +
                usb.SUBMIT_BODY.pack(body['flags'], length, body['frame'], body['packets'], body['interval'], setup) + data)

    async def reply(self, reader):
        raw = await asyncio.wait_for(reader.readexactly(48), 1)
        basic = usb.BASIC.unpack(raw[:20])
        if basic[0] == usb.RET_UNLINK:
            return basic, struct.unpack('!i', raw[20:24])[0], b''
        status, actual, frame, packets, errors = struct.unpack('!iiiii', raw[20:40])
        data = await reader.readexactly(actual) if basic[3] else b''
        return basic, (status, actual, frame, packets, errors), data

    async def test_discovery_uses_backend_descriptor_bytes(self):
        reader, writer = await self.client()
        writer.write(usb.COMMON.pack(usb.VERSION, usb.DEVLIST, 0))
        self.assertEqual(usb.COMMON.unpack(await reader.readexactly(8)), (usb.VERSION, 5, 0))
        self.assertEqual(await reader.readexactly(4), b'\0\0\0\1')
        wire = usb.DEVICE.unpack(await reader.readexactly(usb.DEVICE.size))
        self.assertEqual(wire[5:8], (0x1234, 0x5678, 0x0100))
        self.assertEqual(await reader.readexactly(4), b'\xff\0\0\0')

    async def test_not_ready_empty_list_and_failed_import(self):
        self.backend.ready = False
        reader, writer = await self.client()
        writer.write(usb.COMMON.pack(usb.VERSION, usb.DEVLIST, 0))
        self.assertEqual(await reader.readexactly(12), usb.COMMON.pack(usb.VERSION, 5, 0) + bytes(4))
        other, tx = await self.client()
        tx.write(usb.COMMON.pack(usb.VERSION, usb.IMPORT, 0) + b'synthetic-1'.ljust(32, b'\0'))
        self.assertEqual(await other.readexactly(8), usb.COMMON.pack(usb.VERSION, 3, 1))

    async def test_identity_mismatch_never_exports(self):
        self.backend.bad_identity = True
        reader, writer = await self.client()
        writer.write(usb.COMMON.pack(usb.VERSION, usb.DEVLIST, 0))
        self.assertEqual(await reader.readexactly(12), usb.COMMON.pack(usb.VERSION, 5, 0) + bytes(4))

    async def test_out_forwarding_and_in_short_packet(self):
        self.backend.fragment = True
        reader, writer = await self.imported()
        data = b'\0\xffasymmetric\x12\x80'
        writer.write(self.submit(11, 0, len(data), data=data))
        basic, response, output = await self.reply(reader)
        self.assertEqual((basic[0], basic[1], response[:2], output), (3, 11, (0, len(data)), b''))
        _, event, actual = await self.backend.submitted.get()
        self.assertEqual(actual, data)
        self.assertEqual((event['direction'], event['endpoint']), (0, 1))
        writer.write(self.submit(12, 1, 512))
        _, response, output = await self.reply(reader)
        self.assertEqual(response[:2], (0, len(self.backend.in_bytes)))
        self.assertEqual(output, self.backend.in_bytes)

    async def test_control_setup_reaches_backend(self):
        reader, writer = await self.imported()
        setup = bytes.fromhex('8006000100001200')
        writer.write(self.submit(19, 1, 18, endpoint=0, setup=setup))
        await self.reply(reader)
        _, header, payload = await self.backend.submitted.get()
        self.assertEqual(header['setup'], setup.hex())
        self.assertEqual(payload, b'')

    async def test_stall_preserves_errno(self):
        self.backend.replies[21] = {'status': -32, 'data': b'', 'actual_length': 0}
        reader, writer = await self.imported()
        writer.write(self.submit(21, 1, 32))
        _, response, payload = await self.reply(reader)
        self.assertEqual((response[:2], payload), ((-32, 0), b''))

    async def test_pending_then_unlink_and_unknown_unlink(self):
        self.backend.hold.add(31)
        reader, writer = await self.imported()
        writer.write(self.submit(31, 1, 512))
        await self.backend.submitted.get()
        writer.write(usb.BASIC.pack(2, 32, 7 << 16 | 9, 0, 0) + struct.pack('!I24x', 31))
        basic, status, data = await self.reply(reader)
        self.assertEqual((basic[0], basic[1], status, data), (4, 32, -104, b''))
        self.assertFalse(self.backend.active)
        writer.write(usb.BASIC.pack(2, 33, 7 << 16 | 9, 0, 0) + struct.pack('!I24x', 31))
        self.assertEqual((await self.reply(reader))[1], -2)

    async def test_timeout_cancels_backend_before_reporting(self):
        self.backend.hold.add(41)
        reader, writer = await self.imported()
        writer.write(self.submit(41, 1, 32))
        _, response, data = await self.reply(reader)
        self.assertEqual((response[:2], data), ((-110, 0), b''))
        self.assertFalse(self.backend.active)
        self.assertTrue(any(event[0] == 'cancel' for event in self.backend.events))

    async def test_invalid_oversize_iso_and_duplicate_close_import(self):
        for name, request, initial in (
            ('oversize', self.submit(51, 1, usb.MAX_PAYLOAD + 1), None),
            ('iso', self.submit(51, 1, 1, packets=1), None),
            ('negative', self.submit(51, 1, -1), None),
            ('unknown_ep', self.submit(51, 1, 1, endpoint=7), None),
            ('control_length', self.submit(51, 1, 5, endpoint=0), None),
            ('duplicate', self.submit(51, 1, 5), self.submit(51, 1, 5)),
        ):
            with self.subTest(name=name):
                self.backend.hold.add(51)
                reader, writer = await self.imported()
                if initial:
                    writer.write(initial)
                    await self.backend.submitted.get()
                writer.write(request)
                self.assertEqual(await asyncio.wait_for(reader.read(1), 1), b'')
                writer.close()
                await writer.wait_closed()
                for _ in range(50):
                    if not self.server.imported:
                        break
                    await asyncio.sleep(0.002)

    async def test_backend_invalid_actual_length_closes_import(self):
        self.backend.replies[61] = {'data': b'123', 'actual_length': 100}
        reader, writer = await self.imported()
        writer.write(self.submit(61, 1, 3))
        self.assertEqual(await asyncio.wait_for(reader.read(1), 1), b'')

    async def test_client_disconnect_releases_backend_owner(self):
        self.backend.hold.add(71)
        _, writer = await self.imported()
        writer.write(self.submit(71, 1, 64))
        await self.backend.submitted.get()
        writer.close()
        await writer.wait_closed()
        for _ in range(50):
            if not self.backend.active:
                break
            await asyncio.sleep(0.002)
        self.assertFalse(self.backend.active)
        self.assertTrue(any(e[0] == 'owner_closed' and e[1]['role'] == 'usbip' for e in self.backend.events))

    async def test_backend_disconnect_closes_host_even_without_pending_urbs(self):
        reader, _ = await self.imported()
        await self.backend.drop_data()
        self.assertEqual(await asyncio.wait_for(reader.read(1), 1), b'')

    async def test_cancel_failure_never_reports_successful_unlink(self):
        self.backend.hold.add(81)
        self.backend.cancel_status = -16
        reader, writer = await self.imported()
        writer.write(self.submit(81, 1, 32))
        await self.backend.submitted.get()
        writer.write(usb.BASIC.pack(2, 82, 7 << 16 | 9, 0, 0) + struct.pack('!I24x', 81))
        self.assertEqual(await asyncio.wait_for(reader.read(1), 1), b'')

    async def test_completed_submit_wins_unlink_race(self):
        reader, writer = await self.imported()
        writer.write(self.submit(83, 1, 32))
        await self.reply(reader)
        writer.write(usb.BASIC.pack(2, 84, 7 << 16 | 9, 0, 0) + struct.pack('!I24x', 83))
        self.assertEqual((await self.reply(reader))[1], -2)

    async def test_pending_count_and_reserved_bytes_bounded(self):
        for count, length in ((usb.MAX_PENDING, 1), (usb.MAX_RESERVED // usb.MAX_PAYLOAD, usb.MAX_PAYLOAD)):
            self.server.urb_timeout = 3
            self.backend.hold.update(range(100, 100 + count))
            reader, writer = await self.imported()
            for seq in range(100, 100 + count):
                writer.write(self.submit(seq, 1, length))
                await self.backend.submitted.get()
            writer.write(self.submit(100 + count, 1, length))
            self.assertEqual(await asyncio.wait_for(reader.read(1), 1), b'')
            for _ in range(50):
                if not self.server.imported:
                    break
                await asyncio.sleep(0.002)

    async def test_cancelled_requests_do_not_leak_rpc_budget(self):
        self.server.urb_timeout = 3
        self.backend.hold.update(range(200, 290, 2))
        reader, writer = await self.imported()
        for seq in range(200, 290, 2):
            writer.write(self.submit(seq, 1, 32))
            await self.backend.submitted.get()
            writer.write(usb.BASIC.pack(2, seq + 1, 7 << 16 | 9, 0, 0) + struct.pack('!I24x', seq))
            self.assertEqual((await self.reply(reader))[1], -104)
        self.assertFalse(self.backend.active)

    async def test_backend_event_invalidates_import(self):
        reader, _ = await self.imported()
        for writer in self.backend.data_writers:
            await self.backend.send(writer, {'version': 1, 'op': 'event', 'id': 1,
                                             'kind': 'device_changed', 'reason': 'synthetic mode switch'})
        self.assertEqual(await asyncio.wait_for(reader.read(1), 1), b'')

    async def test_duplicate_backend_completion_closes_import(self):
        self.backend.duplicate_completion = True
        reader, writer = await self.imported()
        writer.write(self.submit(91, 1, 32))
        # A first completion can already be queued; the duplicate must still close the owner.
        received = await asyncio.wait_for(reader.read(), 1)
        self.assertLessEqual(len(received), 48 + len(self.backend.in_bytes))
        self.assertFalse(self.server.imported)

    async def test_import_is_exclusive(self):
        await self.imported()
        reader, writer = await self.client()
        writer.write(usb.COMMON.pack(usb.VERSION, usb.IMPORT, 0) + b'synthetic-1'.ljust(32, b'\0'))
        self.assertEqual(await reader.readexactly(8), usb.COMMON.pack(usb.VERSION, 3, 2))

    async def test_bridge_lengths_rejected_before_body(self):
        for head, data in ((usb.MAX_HEADER + 1, 0), (1, usb.MAX_PAYLOAD + 1), (0, 0)):
            reader = asyncio.StreamReader()
            reader.feed_data(struct.pack('!II', head, data))
            with self.assertRaises(usb.ProtocolError):
                await usb.read_frame(reader, 0.1)

    async def test_framing_duplicate_keys_and_missing_backend(self):
        with self.assertRaises(usb.ProtocolError):
            usb.decode_header(b'{"version":1,"op":"x","id":1,"id":2}')
        with self.assertRaises(usb.ProtocolError):
            usb.decode_header(b'{"version":true,"op":"x","id":1}')
        with self.assertRaises(usb.ProtocolError):
            usb.decode_header(b'{"version":1,"op":"x","id":1,"x":NaN}')
        await self.backend.close()
        reader, writer = await self.client()
        writer.write(usb.COMMON.pack(usb.VERSION, usb.DEVLIST, 0))
        self.assertEqual(await reader.readexactly(12), usb.COMMON.pack(usb.VERSION, 5, 0) + bytes(4))

    def test_descriptor_boundaries_and_listener_scope(self):
        for raw in (b'', DESCRIPTORS[:-1], DESCRIPTORS + b'\0', DESCRIPTORS[:18] + b'\0' + DESCRIPTORS[19:]):
            with self.assertRaises(usb.ProtocolError):
                usb.GuestDevice.parse(METADATA, raw)
        with self.assertRaises(usb.ProtocolError):
            usb.GuestDevice.parse({**METADATA, 'descriptor_source': 'host-template'}, DESCRIPTORS)
        with self.assertRaises(usb.Blocked):
            usb.UsbIpServer(self.context, host='0.0.0.0')


if __name__ == '__main__':
    unittest.main()
