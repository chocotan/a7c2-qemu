#!/usr/bin/env python3
"""Wiring checks for the explicit virtual media insert-detect register.

The retail driver reads one 4-byte register at 0xF1388F44 and tests bit 24, while the
generic catch-all answers 0xFFFFFFFF there. This overlay exists only to state that
value explicitly for an experiment; it must stay opt-in and must never be described
as a card-insert ACK.
"""
from pathlib import Path
import os
import re
import runpy
import selectors
import shutil
import subprocess
import time
import unittest

HERE = Path(__file__).resolve().parent


class MediaDetectOverlay(unittest.TestCase):
    def test_read_log_can_be_joined_to_the_guest_prompt(self):
        extract=runpy.run_path(str(HERE/'probe-media-detect.py'))['detect_reads']
        log=b'/ # SONY_MEDIA_DETECT_READ count=1 offset=0 size=4 value=0x00000000\n'
        self.assertEqual(extract(log),['SONY_MEDIA_DETECT_READ count=1 offset=0 size=4 value=0x00000000'])
    def test_patcher_adds_a_four_byte_register_at_the_driver_address(self):
        text = (HERE / 'usb-qemu-board.py').read_text()
        self.assertIn('QEMU_SONY_MEDIA_DETECT', text)
        self.assertIn('0xf1388f44', text)
        self.assertIn('"sony-media-detect", 4', text)
        # read-only: the write callback must not store anything
        write = re.search(r'static void sony_media_detect_write\([^)]*\)\s*\{(.*?)\}', text, re.S)
        self.assertIsNotNone(write, 'write callback missing')
        self.assertNotRegex(write.group(1),r's->value\s*=')
        self.assertIn('WRITE_IGNORED',text)

    def test_overlay_is_opt_in_and_explicitly_not_an_ack(self):
        runner = (HERE / 'run-full-system.py').read_text()
        self.assertIn("'--media-detect'", runner)
        self.assertIn("env['QEMU_SONY_MEDIA_DETECT']=f'{args.media_detect:#010x}'", runner)
        # None, rather than truthiness: zero is a valid explicit register value.
        self.assertIn("type=lambda value:int(value,0),default=None", runner)
        patcher = (HERE / 'usb-qemu-board.py').read_text()
        self.assertIn('never a fake ACK', patcher)

    def test_generic_catch_all_still_answers_all_ones_by_default(self):
        stub = HERE.parents[1] / 'sources/qemu-11.1.2/hw/misc/sony_cxd_bus_stub.c'
        if not stub.is_file():
            self.skipTest('base QEMU source not present')
        text = stub.read_text()
        self.assertIn('return 0xFFFFFFFF;', text)

    def test_definitions_are_inserted_before_their_use(self):
        """A previous revision appended the callbacks at the end of virt.c, which does
        not compile: the use site in machvirt_init comes first."""
        text = (HERE / 'usb-qemu-board.py').read_text()
        self.assertIn("static void machvirt_init(MachineState *machine)", text)
        # Every definition block must be spliced in before machvirt_init rather
        # than appended at the end. The exact concatenation expression is an
        # implementation detail, so require the structural property instead.
        self.assertIn("define_anchor='static void machvirt_init(MachineState *machine)'", text)
        spliced = re.search(r"text\.replace\(define_anchor,([^,]+),1\)", text)
        self.assertIsNotNone(spliced, "definitions are no longer spliced before machvirt_init")
        operands = spliced.group(1)
        for name in ('detect', 'mmc_trace'):
            with self.subTest(definition=name):
                self.assertIn(name, operands)
                self.assertIn(f"    {name}=", text)
        self.assertNotIn("+'\\n\\n'+detect", text)


@unittest.skipUnless(shutil.which('bwrap'),'bwrap required')
class MediaDetectSandbox(unittest.TestCase):
    def test_built_adapter_delivers_explicit_zero_to_clearenv_sandbox(self):
        adapter=HERE/'runtime/official-demo/.a7c2/sessions/session-ijc2cbdf/runtime/analysis/qemu-kernel-probe.sh'
        if not adapter.is_file():self.skipTest('built official runtime required')
        text=adapter.read_text()
        fragment=text.split('# FULLSYSTEM_MEDIA_DETECT_ENV:',1)[1].split('\nbootfs=',1)[0]
        for value in (None,'0x00000000','0x01000000'):
            with self.subTest(value=value):
                env={k:v for k,v in os.environ.items() if k!='QEMU_SONY_MEDIA_DETECT'}
                if value is not None:env['QEMU_SONY_MEDIA_DETECT']=value
                script='timer_environment=()\n#'+fragment+'''\nexec bwrap --unshare-net --die-with-parent --clearenv \\
                  --ro-bind / / --dev /dev --proc /proc "${timer_environment[@]}" /usr/bin/env
'''
                result=subprocess.run(['bash','-c',script],env=env,capture_output=True,text=True,timeout=10)
                self.assertEqual(result.returncode,0,result.stderr)
                values=[l.partition('=')[2] for l in result.stdout.splitlines() if l.startswith('QEMU_SONY_MEDIA_DETECT=')]
                self.assertEqual(values,[] if value is None else [value])


def qtest_register(value):
    binary=Path(os.environ.get('QEMU_MEDIA_TEST_BINARY',HERE/'runtime/usb-qemu/qemu-system-aarch64'))
    env={k:v for k,v in os.environ.items() if not k.startswith(('QEMU_','SONY_','MENU_'))}
    env['QEMU_SONY_TIMERS']='1'
    if value is not None:env['QEMU_SONY_MEDIA_DETECT']=hex(value)
    process=subprocess.Popen([str(binary),'-machine','virt,secure=off','-cpu','cortex-a35',
        '-m','4096','-accel','tcg','-S','-nodefaults','-display','none','-monitor','none',
        '-serial','none','-nic','none','-qtest','stdio','-qtest-log','/dev/null'],
        stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,env=env)
    selector=selectors.DefaultSelector()
    try:
        selector.register(process.stdout,selectors.EVENT_READ)
        # Read-only overlay must survive a write, and must not alter adjacent MMIO.
        process.stdin.write(b'readl 0xf1388f44\nwritel 0xf1388f44 0x12345678\n'
                            b'readl 0xf1388f44\nreadl 0xf1388f40\nreadl 0xf1388f48\n')
        process.stdin.flush()
        pending=b'';responses=[];deadline=time.monotonic()+15
        while len(responses)<5:
            remaining=deadline-time.monotonic()
            if remaining<=0 or not selector.select(remaining):
                raise RuntimeError('QEMU media-register readback timed out')
            chunk=os.read(process.stdout.fileno(),4096)
            if not chunk:raise RuntimeError('QEMU terminated during register readback')
            pending+=chunk
            while b'\n' in pending:
                line,pending=pending.split(b'\n',1)
                if line.startswith(b'OK'):responses.append(line)
                elif line.startswith(b'FAIL'):raise RuntimeError(line.decode())
        return [int(line.split()[1],16) for line in responses if line.startswith(b'OK 0x')]
    finally:
        selector.close()
        if process.poll() is None:process.kill()
        process.wait(timeout=5)
        for stream in (process.stdin,process.stdout,process.stderr):stream.close()


@unittest.skipUnless((HERE/'runtime/usb-qemu/qemu-system-aarch64').is_file(),'built dedicated QEMU required')
class MediaDetectActualQemu(unittest.TestCase):
    def test_word_readback_and_readonly_overlay_preserve_adjacent_registers(self):
        # With this virt RAM geometry, RAM shadows the low-priority catch-all.
        baseline=qtest_register(None)
        self.assertEqual(baseline,[0,0x12345678,0,0])
        for value in (0,0xffffffff,0xfeffffff,0x01000000):
            with self.subTest(value=value):
                self.assertEqual(qtest_register(value),[value,value,*baseline[2:]])
