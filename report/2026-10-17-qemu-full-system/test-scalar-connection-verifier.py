#!/usr/bin/env python3
"""C-produced second-edge records. Predecessor/DTB checks are explicit mocks."""
import hashlib
import json
import os
from pathlib import Path
import re
import runpy
import subprocess
import tempfile
import unittest
from unittest.mock import patch

HERE=Path(__file__).resolve().parent
VERIFY=runpy.run_path(str(HERE/'verify-scalar-connection.py'))['verify_connection']


class SecondEdgeEvidence(unittest.TestCase):
    family='SCALAR'
    profile='scalar_connection'
    producer_test='test-scalar-connection.c'
    producer_env='SCALAR_CONNECTION_HOST_FIXTURE'
    predecessor='verify-scalar-pin.py'
    proof_key='scalar_control_connection_verified'
    next_key='next_out2_get_free_verified'
    next_slot=5
    token='fullsystem.scalar-connect=control'
    @classmethod
    def setUpClass(cls):
        cls.work=tempfile.TemporaryDirectory(prefix='second-edge-host-only-')
        cls.binary=Path(cls.work.name)/'producer'
        sources=('pin-registry-core.c','vef-device.c','pinmem-device.c','scalar-device.c','adf-device.c','pin-buffer-owner.c','pin-buffer-wire.c','pin-connection.c','pin-format.c','scalar-connection.c','adf-connection.c',cls.producer_test)
        subprocess.run(['clang','-std=c11','-O2','-Wall','-Wextra','-Werror','-pthread','-DFULL_VEF_TEST','-DPIN_CONTROL_TEST','-DFULL_PIN_CONNECTION_TEST',*[str(HERE/name) for name in sources],'-o',str(cls.binary)],check=True)

    @classmethod
    def tearDownClass(cls):cls.work.cleanup()

    def fixture(self,path):
        result=subprocess.run([str(self.binary)],env={**os.environ,self.producer_env:str(path/'backing.bin')},capture_output=True,check=True)
        self.assertTrue(result.stdout.startswith(b'HOST_FIXTURE_ONLY_NO_VM\n'))
        (path/'console.log').write_bytes(result.stdout)
        (path/'inputs.json').write_text(json.dumps({'experiment':{self.profile:'control'}}))
        return result.stdout

    def check(self,path):
        original=runpy.run_path
        console=(path/'console.log').read_bytes()
        tid=int(re.search(('OBS FULL_'+self.family+'_CONNECT_REQUEST tid=(\\d+)').encode(),console)[1])
        def dependency(name,*args,**kwargs):
            if Path(name).name==self.predecessor:
                return {'verify':lambda run:{'caller_tid':tid,'console_sha256':hashlib.sha256(console).hexdigest()}}
            if Path(name).name=='verify-pin-control.py':
                return {'verify_reservation':lambda *unused:self.token}
            return original(name,*args,**kwargs)
        with patch.object(VERIFY.__globals__['runpy'],'run_path',dependency):
            return VERIFY(path,self.family)

    def test_c_producer_second_edge_records(self):
        with tempfile.TemporaryDirectory() as temporary:
            path=Path(temporary);self.fixture(path)
            proof=self.check(path)
            self.assertTrue(proof[self.proof_key])
            self.assertTrue(proof[self.next_key])
            self.assertFalse(proof['camera_startup_verified'])

    def test_required_events_cannot_be_omitted(self):
        for event in ('PEER_REPLY','EVENT6_CONSUMED','YC_DIRECTION_CHECK','NATIVE_REPLY_FREE','STATE_READBACK'):
            with self.subTest(event=event), tempfile.TemporaryDirectory() as temporary:
                path=Path(temporary);data=self.fixture(path);prefix=('OBS FULL_'+self.family+'_CONNECT_'+event+' ').encode()
                (path/'console.log').write_bytes(b'\n'.join(line for line in data.splitlines() if not line.startswith(prefix))+b'\n')
                with self.assertRaises((ValueError,StopIteration)):self.check(path)

    def test_peer_nonzero_status_and_wrong_direction_rejected(self):
        for kind in ('status','direction'):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as temporary:
                path=Path(temporary);data=self.fixture(path)
                if kind=='direction':data=data.replace(b'selected_group=source type=0 dir=2',b'selected_group=source type=0 dir=1')
                else:
                    row=re.search(('OBS FULL_'+self.family+'_CONNECT_PEER_REPLY [^\\n]+').encode(),data)[0]
                    raw=re.search(rb'raw=([0-9a-f]+)',row)[1];wire=bytearray.fromhex(raw.decode());wire[64]=1
                    data=data.replace(row,row.replace(raw,wire.hex().encode()))
                (path/'console.log').write_bytes(data)
                with self.assertRaises(ValueError):self.check(path)

    def test_next_get_state_owner_status_and_free_identity_rejected(self):
        for old,new in ((b'pin_state=1',b'pin_state=2'),(b'owner=0x90590818',b'owner=0x9058003f'),
                        (b'status=0',b'status=57346'),(b'bytes=56',b'bytes=72'),
                        (b'destination=',b'destination=0x90000000 ignored=')):
            with self.subTest(field=old), tempfile.TemporaryDirectory() as temporary:
                path=Path(temporary);data=self.fixture(path)
                commit=re.search(rb'OBS FULL_PINMEM_COMMIT [^\n]*slot='+str(self.next_slot).encode()+rb' [^\n]+',data)[0]
                if old in (b'bytes=56',b'destination='):
                    reply=re.search(rb'reply=([^ ]+)',commit)[1];lease=re.search(rb'lease=(\d+)',commit)[1]
                    row=re.search(rb'OBS FULL_PINMEM_NATIVE_REPLY_FREE [^\n]*reply='+re.escape(reply)+rb' lease='+lease+rb' [^\n]+',data)[0]
                else:row=commit
                self.assertIn(old,row);(path/'console.log').write_bytes(data.replace(row,row.replace(old,new,1),1))
                with self.assertRaises((ValueError,StopIteration)):self.check(path)


if __name__=='__main__':unittest.main()
