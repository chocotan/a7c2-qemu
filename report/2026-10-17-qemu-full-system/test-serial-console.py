from pathlib import Path
import re
import runpy
import tempfile
import unittest

API=runpy.run_path(str(Path(__file__).resolve().parent/'serial-console.py'))


class SerialCompletionTest(unittest.TestCase):
    marker=b'MENU_DIAG_COMMAND_DONE_0123456789abcdef01234567'
    suffix=b':END_0123456789abcdef01234567'

    def test_kernel_prefix_and_trailing_space_do_not_erase_real_tag(self):
        raw=b'[K] Skip snd'+self.marker+b':0'+self.suffix+b'o\nto 0x83f\n'
        result=API['completion'](raw,self.marker)
        self.assertIsNotNone(result)
        self.assertEqual(result[0],self.marker+b':0'+self.suffix)

    def test_command_echo_is_not_completion(self):
        self.assertIsNone(API['completion'](b"printf '\\n"+self.marker+b":%s\\n' \"$rc\"\n",self.marker))

    def test_other_nonce_is_not_this_command(self):
        self.assertIsNone(API['completion'](self.marker+b'9:0\n',self.marker))

    def test_nonzero_status_is_preserved(self):
        self.assertEqual(API['completion'](self.marker+b':17'+self.suffix+b'\n',self.marker)[1],b'17')

    def test_fragment_without_boundary_waits_for_more_bytes(self):
        self.assertIsNone(API['completion'](self.marker+b':0',self.marker))

    def test_interleaved_status_is_not_treated_as_success(self):
        self.assertIsNone(API['completion'](self.marker+b':0o'+self.suffix,self.marker))

    def test_command_preserves_raw_bytes_and_copies_only_observed_receipt(self):
        with tempfile.TemporaryDirectory() as directory:
            console=Path(directory)/'console.log';console.write_bytes(b'previous command\n')
            class Input:
                def write(self,data):self.data=data
                def flush(self):
                    marker=re.search(rb'MENU_DIAG_COMMAND_DONE_[0-9a-f]{24}',self.data)[0]
                    self.reply=b'[K] Skip snd'+marker+b':0:END_'+marker.rsplit(b'_',1)[-1]+b'o\nto 0x83f\n'
                    with console.open('ab') as stream:stream.write(self.data+self.reply)
            class Process:
                stdin=Input()
                def poll(self):return None
            class Monitor:
                def check(self):pass
            process=Process()
            output=API['serial_command'](process,console,'true',timeout=1,monitor=Monitor())
            self.assertIn(b"printf '\\nMENU_DIAG_COMMAND_DONE_",process.stdin.data)
            self.assertIn(process.stdin.reply,output)
            self.assertRegex(output,rb'\nMENU_DIAG_COMMAND_DONE_[0-9a-f]{24}:0\n$')

    def test_cleanup_bypasses_fault_monitor_and_accepts_no_deadline(self):
        with tempfile.TemporaryDirectory() as directory:
            console=Path(directory)/'console.log';console.write_bytes(b'')
            class Input:
                def write(self,data):self.data=data
                def flush(self):
                    marker=re.search(rb'MENU_DIAG_COMMAND_DONE_[0-9a-f]{24}',self.data)[0]
                    with console.open('ab') as stream:
                        stream.write(marker+b':0:END_'+marker.rsplit(b'_',1)[-1])
            class Process:
                stdin=Input()
                def poll(self):return None
            class FaultedMonitor:
                def check(self):raise RuntimeError('camera faulted')
            output=API['serial_command'](Process(),console,'echo cleanup',timeout=None,
                                         monitor=FaultedMonitor(),cleanup=True)
            self.assertIn(b':0:END_',output)

    def test_normal_command_still_refuses_faulted_guest(self):
        class FaultedMonitor:
            def check(self):raise RuntimeError('camera faulted')
        with self.assertRaisesRegex(RuntimeError,'camera faulted'):
            API['serial_command'](None,None,'true',monitor=FaultedMonitor())


if __name__=='__main__':unittest.main()
