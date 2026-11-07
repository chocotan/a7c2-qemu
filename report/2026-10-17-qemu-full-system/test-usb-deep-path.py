import asyncio
import os
from pathlib import Path
import socket
import struct
import tempfile
import threading
import unittest
from unittest.mock import patch

import usb_control as control
usbip=control.usbip


class DeepSocketTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.run=self.root/('a'*65)/('b'*65)
        self.run.mkdir(parents=True,mode=0o700)
        self.assertGreater(len(str(self.run/'qmp.sock')),108)

    def listener(self,name):
        path=self.run/name
        fd=os.open(self.run,os.O_RDONLY|os.O_DIRECTORY)
        server=socket.socket(socket.AF_UNIX)
        try:server.bind('/proc/self/fd/'+str(fd)+'/'+name)
        finally:os.close(fd)
        path.chmod(0o600);server.listen();self.addCleanup(server.close)
        return path,server

    def test_real_unix_connection_under_deep_directory_preserves_peer(self):
        path,server=self.listener('qmp.sock')
        with socket.socket(socket.AF_UNIX) as client:
            with usbip.unix_path(path) as short:client.connect(short)
            peer,_=server.accept()
            with peer:
                pid,uid,_=struct.unpack('3i',client.getsockopt(socket.SOL_SOCKET,socket.SO_PEERCRED,12))
                self.assertEqual((pid,uid),(os.getpid(),os.getuid()))
                peer.sendall(b'actual stream')
                self.assertEqual(client.recv(64),b'actual stream')

    def test_async_backend_connection_uses_live_directory_fd(self):
        path,server=self.listener('usb-endpoint.sock')
        async def connect():
            with usbip.unix_path(path) as short:
                reader,writer=await asyncio.open_unix_connection(short)
            peer,_=server.accept()
            with peer:peer.sendall(b'guest')
            self.assertEqual(await reader.readexactly(5),b'guest')
            writer.close();await writer.wait_closed()
        asyncio.run(connect())

    def test_parent_alias_and_socket_replacement_are_rejected(self):
        path,server=self.listener('backend.sock')
        alias=self.root/'alias';alias.symlink_to(self.run,target_is_directory=True)
        with self.assertRaises(OSError):
            with usbip.unix_path(alias/path.name):pass
        with self.assertRaises(usbip.Blocked):
            with usbip.unix_path(path):
                path.unlink()
                fd=os.open(self.run,os.O_RDONLY|os.O_DIRECTORY)
                replacement=socket.socket(socket.AF_UNIX)
                try:replacement.bind('/proc/self/fd/'+str(fd)+'/'+path.name)
                finally:os.close(fd);replacement.close()
                path.chmod(0o600)

    def test_recovery_only_reuses_verified_owned_target(self):
        target=self.root/'virtual-device';target.mkdir()
        obj=object.__new__(control.UsbControl)
        obj.context=type('Context',(),{'run_id':'run','lease_id':'digest'})()
        state={'host_enumerated':True,'phase':'recovery_required','preload_recovery_required':True,
               'blocked_reason':{'code':'preload_recovery_required'},'target':{'sysfs_path':str(target)}}
        with patch.object(obj,'status',return_value=state):
            with self.assertRaises(control.ControlBlocked):obj.jiritsu_target(target)
            self.assertEqual(obj.jiritsu_target(target,allow_recovery=True)['run_id'],'run')
            with self.assertRaises(control.ControlBlocked):obj.jiritsu_target(self.root,allow_recovery=True)
            state['blocked_reason']={'code':'server_owner_lost'}
            with self.assertRaises(control.ControlBlocked):obj.jiritsu_target(target,allow_recovery=True)


if __name__=='__main__':unittest.main()
