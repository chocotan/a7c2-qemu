#!/usr/bin/env python3
"""Watchpoint state machine: original store executes, no debugger memory write."""
import json
from pathlib import Path
import runpy
import tempfile
import unittest

Probe=runpy.run_path(str(Path(__file__).with_name('shutdown-watch.py')))['ShutdownWriteProbe']


class WatchStore(unittest.TestCase):
    def make(self, directory, factor, writes=0):
        p=Probe.__new__(Probe)
        p.run=Path(directory);p.base=0x10000000;p.pid=123
        p.target=p.base+p.OFFSET;p.finished=False;p.captured=False;p.writes=writes
        p.pending=f'T05watch:{p.target:x};thread:p1.2;'
        p.stepped=False;p.commands=[]
        regs=bytearray(268)
        regs[256:264]=(p.base+0x100).to_bytes(8,'little')

        def request(command):
            p.commands.append(command)
            if command=='g':return regs.hex()
            if command==f'm{p.target:x},c':
                value=factor if p.stepped else 0
                return b''.join(x.to_bytes(4,'little') for x in (value,3,2)).hex()
            if command==f'm{p.base+0x100:x},4':return '200000b9'
            if command.startswith(('z2,','Z2,','Hg','Hc')):return 'OK'
            raise AssertionError(command)

        def send(command):
            p.commands.append(command)
            if command=='s':p.stepped=True
        p.request=request;p.send=send;p.receive=lambda timeout:'T05thread:p1.2;'
        return p

    def test_original_store_capture_and_resume(self):
        with tempfile.TemporaryDirectory() as directory:
            p=self.make(directory,0x15);p.check()
            self.assertTrue(p.finished and p.captured)
            result=json.loads((p.run/'shutdown-factor-15.json').read_text())
            self.assertEqual(result['model_before_hex'][:8],'00000000')
            self.assertEqual(result['model_after_hex'][:8],'15000000')
            self.assertFalse(any(c.startswith(('M','X')) for c in p.commands))
            self.assertEqual(p.commands[-1],'c')
            self.assertNotIn(f'Z2,{p.target:x},4',p.commands)

    def test_non_target_store_rearms(self):
        with tempfile.TemporaryDirectory() as directory:
            p=self.make(directory,4);p.check()
            self.assertFalse(p.finished or p.captured)
            self.assertIn(f'Z2,{p.target:x},4',p.commands)
            self.assertEqual(p.commands[-1],'c')

    def test_limit_never_claims_a_cause(self):
        with tempfile.TemporaryDirectory() as directory:
            p=self.make(directory,4,writes=127);p.check()
            self.assertTrue(p.finished);self.assertFalse(p.captured)
            result=json.loads((p.run/'shutdown-watch-limit.json').read_text())
            self.assertFalse(result['cause_verified'])
            self.assertEqual(p.commands[-1],'c')

    def test_end_removes_watch_before_qmp_readbacks(self):
        with tempfile.TemporaryDirectory() as directory:
            p=self.make(directory,4)
            p.stop_vm=lambda:p.commands.append('interrupt')
            p.close=lambda:p.commands.append('close')
            p.end_observation()
            self.assertTrue(p.finished);self.assertFalse(p.captured)
            self.assertEqual(p.commands,['interrupt',f'z2,{p.target:x},4','Hc-1','c','close'])

    def test_captures_original_main_event_from_proven_frame(self):
        with tempfile.TemporaryDirectory() as directory:
            p=self.make(directory,0x15);original=p.memory
            p.frames=lambda fp:[{'appfw_lr':'0x179a250','parent':'0x200000'}]
            event=bytearray(0x178);event[:4]=(5).to_bytes(4,'little');event[8:12]=(0x1234).to_bytes(4,'little')
            def memory(address,size):
                if (address,size)==(0x2000e8,0x170):return bytes(0x170)
                if (address,size)==(0x200258,0x178):return bytes(event)
                return original(address,size)
            p.memory=memory;p.check()
            result=json.loads((p.run/'shutdown-factor-15.json').read_text())
            self.assertEqual(result['original_app_event']['ds_event_type'],5)
            self.assertEqual(result['original_app_event']['ds_event_word2'],'0x1234')

    def test_unmapped_initial_cpu_context_still_arms_virtual_watch(self):
        with tempfile.TemporaryDirectory() as directory:
            p=self.make(directory,0x15);p.target=None;p.pending=None
            (p.run/'console.log').write_text('OBS OBSERVER_READY pid=123 base=0x10000000\n')
            p.stop_vm=lambda:None
            def memory(address,size):raise RuntimeError('QEMU fatal-probe RSP error: E14')
            p.memory=memory;p.receive=lambda timeout:None
            p.check()
            armed=json.loads((p.run/'shutdown-watch-armed.json').read_text())
            self.assertIsNone(armed['initial_model_hex'])
            self.assertIn('E14',armed['initial_read_error'])
            self.assertIn(f'Z2,{p.target:x},4',p.commands)
            self.assertFalse(p.captured)


if __name__=='__main__':unittest.main()
