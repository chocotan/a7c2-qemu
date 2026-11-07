#!/usr/bin/env python3
from pathlib import Path
import json
import runpy
import socket
import tempfile
import unittest

M=runpy.run_path(str(Path(__file__).with_name('upm-message-probe.py')))


def frame(selector=2):
    body=lambda s:b''.join(v.to_bytes(4,'little') for v in (0x920117,s,0x9a0000,0))
    node=lambda a,s:{'address':hex(a),'qid':0x9a0000,'selector':s}
    before=[node(1,0),node(2,3),node(3,3)]
    return dict(received_raw=body(selector).hex(),processed_raw=body(3 if selector==2 else selector).hex(),
        config_after=1,free_rc=0,message_refs_before_free=1,receive_frame='0xffffff8000001000',process_frame='0xffffff8000001000',
        free_frame='0xffffff8000001000',received_pointer='0xffffffc001000000',
        processed_pointer='0xffffffc001000000',freed_pointer='0xffffffc001000000',
        ng_before=before,ng_after=before[:1]+before[2:] if selector==2 else before[1:])


class Verify(unittest.TestCase):
    def test_only_arm_after_real_same_waiter_target_boundary(self):
        self.assertIsNone(M['target_boundary'](b'UPM_PROBE_SECTIONS text=0x1 bss=0x2 data=0x3\n'))
        line=b'OBS FULL_HDMIPIN_NATIVE_REPLY_FREE tid=523 sender=523 waiter=1 destination=0x81cf61c2 expected=0x81cf61c2 reply=0x100 bytes=56 rc=0\n'
        self.assertIsNotNone(M['target_boundary'](line))
        for invalid in (line.replace(b'sender=523',b'sender=524'),line.replace(b'rc=0',b'rc=1'),line.replace(b'waiter=1',b'waiter=0')):
            with self.subTest(invalid=invalid):self.assertIsNone(M['target_boundary'](invalid))

    def test_first_matching_only(self):
        self.assertTrue(M['verified_effect'](frame()))
        self.assertTrue(M['verified_effect'](frame(0)))

    def test_no_match_is_no_change(self):
        r=frame();r['ng_before']=[];r['ng_after']=[]
        self.assertTrue(M['verified_effect'](r))

    def test_config_zero_does_not_rewrite(self):
        r=frame();r['config_after']=0;r['processed_raw']=r['received_raw'];r['ng_after']=r['ng_before']
        self.assertTrue(M['verified_effect'](r))

    def test_foreign_frame_pointer_wrong_free_and_over_removal(self):
        for key,value in [('process_frame','0xffffff8000002000'),('freed_pointer','0xffffffc002000000'),
                          ('free_rc',-1),('message_refs_before_free',0),('ng_after',[]),('config_after',0),('processed_raw','00')]:
            r=frame();r[key]=value
            with self.subTest(key=key):self.assertFalse(M['verified_effect'](r))

    def test_ng_walk_real_backlinks_and_cycle_rejection(self):
        p=M['UpmMessageProbe'].__new__(M['UpmMessageProbe']);p.sections={'bss':0xffffff8000100000}
        head=p.sections['bss']+0x860;node=head+0x100;memory={}
        put=lambda a,values:memory.update({a:b''.join(v.to_bytes(n,'little') for v,n in values)})
        put(head,[(node,8)]);put(head+8,[(node,8)])
        put(node,[(head,8),(head,8),(0x9a0000,4),(3,4)])
        p.memory=lambda a,n:memory[a][:n]
        self.assertEqual(p.ng(),[{'address':hex(node),'qid':0x9a0000,'selector':3}])
        put(node,[(node,8),(head,8),(0x9a0000,4),(3,4)])
        with self.assertRaisesRegex(ValueError,'invalid'):p.ng()

    def test_rsp_single_step_exact_successors_and_fail_closed(self):
        base=0xffffff8000100000;frame=0xffffffc002000000
        for offset,successor in ((0x138,0x13c),(0x140,0x144),(0x14c,0xf4)):
            for failure in (None,'signal','pc','frame','sid'):
                p=M['UpmMessageProbe'].__new__(M['UpmMessageProbe']);p.sections={'text':base};calls=[]
                registers=[0]*33;registers[19]=0x80920572;registers[29]=frame;registers[32]=base+successor
                if failure=='pc':registers[32]+=4
                if failure=='frame':registers[29]+=16
                if failure=='sid':registers[19]=0
                p.request=lambda text:(calls.append(text) or 'OK')
                p.send=lambda text:calls.append(text)
                p.receive=lambda timeout:'T11thread:2;' if failure=='signal' else 'T05thread:2;'
                p.stop_registers=lambda reason:registers
                with self.subTest(offset=offset,failure=failure):
                    if failure:
                        with self.assertRaises((ValueError,RuntimeError)):p.resume_hit(base+offset,frame)
                        self.assertNotIn('c',calls)
                    else:
                        p.resume_hit(base+offset,frame)
                        self.assertEqual(calls,[f'z0,{base+offset:x},4','s',f'Z0,{base+offset:x},4','c'])

    def test_rsp_wire_recording_checksum_and_fragmented_memory_reply(self):
        left,right=socket.socketpair()
        try:
            left.settimeout(1);right.settimeout(1)
            with tempfile.TemporaryDirectory() as d:
                p=M['UpmMessageProbe'].__new__(M['UpmMessageProbe']);p.buffer=b''
                trace=Path(d)/'wire.jsonl';p.socket=M['RecordingSocket'](left,trace)
                command='mffffff80008f60e0,10';p.send(command)
                wire=right.recv(1024)
                self.assertEqual(wire,b'$'+command.encode()+b'#'+f'{sum(command.encode())&255:02x}'.encode())
                payload=b'fd7bbda9fd030091f30b00f953ae8052'
                packet=b'$'+payload+b'#'+f'{sum(payload)&255:02x}'.encode()
                # An invalid earlier packet must be NACKed; valid buffered
                # bytes still decode, with complete private raw trace.
                right.sendall(b'+$fd#00'+packet[:12]);right.sendall(packet[12:])
                self.assertEqual(p.receive(1),payload.decode())
                ack=right.recv(1024)
                if len(ack)<2:ack+=right.recv(1024)
                self.assertEqual(ack,b'-+')
                records=[json.loads(line) for line in trace.read_text().splitlines()]
                self.assertEqual(records[0]['head_hex'],wire.hex())
                received=b''.join(bytes.fromhex(r['head_hex']) for r in records if r['direction']=='receive')
                self.assertEqual(received,b'+$fd#00'+packet)
        finally:left.close();right.close()


if __name__=='__main__':unittest.main()
