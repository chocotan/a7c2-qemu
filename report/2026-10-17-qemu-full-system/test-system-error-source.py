#!/usr/bin/env python3
import json
from pathlib import Path
import runpy
import tempfile
import unittest

Probe=runpy.run_path(str(Path(__file__).with_name('system-error-source.py')))['SystemErrorSourceProbe']


class OriginalEventSource(unittest.TestCase):
    def make(self,directory,code):
        p=Probe.__new__(Probe);p.run=Path(directory);p.base=0x10000000;p.pid=123
        p.target=p.base+p.OFFSET;p.finished=p.captured=False;p.writes=0;p.pending='T05thread:01;'
        p.commands=[];regs={f'x{i}':0 for i in range(31)}
        regs.update(pc=p.target,x0=0x200000,x20=0x300000,x30=p.base+0x2dbf438)
        p.registers=lambda:regs;p.frames=lambda fp:[]
        def memory(address,size):
            if (address,size)==(0x200000,28):return code.to_bytes(4,'little')+bytes(24)
            if (address,size)==(0x300000,4):return (0x30).to_bytes(4,'little')
            raise AssertionError((address,size))
        p.memory=memory
        p.request=lambda command:(p.commands.append(command) or 'OK')
        p.send=lambda command:p.commands.append(command)
        p.receive=lambda timeout:'T05thread:01;'
        return p

    def test_target_records_original_sender_without_injecting_event(self):
        with tempfile.TemporaryDirectory() as directory:
            p=self.make(directory,0x0100012e);p.check()
            self.assertTrue(p.captured and p.finished)
            result=json.loads((p.run/'original-system-error-source.json').read_text())
            self.assertEqual(result['caller_elf'],'0x2dbf438')
            self.assertEqual(result['infra_notification_first_u32'],'0x30')
            self.assertFalse(any(c.startswith(('M','X')) for c in p.commands))
            self.assertNotIn('s',p.commands)
            self.assertEqual(p.commands[-1],'c')

    def test_unrelated_original_event_steps_and_rearms(self):
        with tempfile.TemporaryDirectory() as directory:
            p=self.make(directory,0x01000090);p.check()
            self.assertFalse(p.captured or p.finished)
            self.assertIn('s',p.commands);self.assertIn(f'Z0,{p.target:x},4',p.commands)
            self.assertFalse((p.run/'original-system-error-source.json').exists())


if __name__=='__main__':unittest.main()
