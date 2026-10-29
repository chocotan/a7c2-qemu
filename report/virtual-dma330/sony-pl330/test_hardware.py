#!/usr/bin/env python3
"""qtest actual PL330 instructions/bytes/IRQs; no Sony firmware or host memcpy."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import socket
import struct
import subprocess
import tempfile
import time

HERE = Path(__file__).resolve().parent


def mov(register, value):
    return bytes((0xbc, register))+struct.pack('<I', value)


def microcode(source, destination, event):
    ccr = 1 | (2 << 1) | (15 << 4) | (1 << 14) | (2 << 15) | (15 << 18)
    return (mov(0, source)+mov(1, ccr)+mov(2, destination)
            + b'\x04\x08'*4 + bytes((0x13, 0x34, event << 3, 0)))


class Machine:
    def __init__(self, binary, root, enabled, atu_test=False, edma_test=False,
                 pci_peer_test=False, low_ecam=False, dbi_test=False, scu_test=False, ccf_test=False, phy_sram_test=False, phy_init_test=False,
                 backup_test=False, backup_image=None, dfs_test=False):
        self.root = root
        self.proc = self.qmp_socket = self.qtest_socket = self.qmp_file = self.qtest_file = None
        self.log = (root/'qemu.log').open('wb')
        command = ['bwrap', '--unshare-all', '--die-with-parent', '--clearenv',
                   '--ro-bind', '/usr', '/usr', '--symlink', 'usr/lib', '/lib',
                   '--symlink', 'usr/lib', '/lib64', '--ro-bind', str(binary), '/qemu',
                   '--bind', str(root), '/out', '--dev', '/dev', '--proc', '/proc']
        if enabled:
            command += ['--setenv', 'QEMU_SONY_DMA330', '1']
        if atu_test:
            command += ['--setenv', 'QEMU_SONY_ATU_TEST', '1']
        if edma_test:
            command += ['--setenv', 'QEMU_SONY_PCIDMA_TEST', '1']
        if pci_peer_test:
            command += ['--setenv', 'QEMU_SONY_PCIE_PEER_TEST', '1']
        if backup_test:
            command += ['--setenv', 'QEMU_SONY_BACKUP_TEST', '1']
        if backup_image is not None:
            image=Path(backup_image)
            if not backup_test or image.is_symlink() or not image.is_file():
                raise ValueError('Backup fixture requires an enabled model and a regular file')
            command += ['--ro-bind', str(image.resolve()), '/backup-initial.bin',
                        '--setenv', 'QEMU_SONY_BACKUP_FILE', '/backup-initial.bin']
        if dbi_test:
            command += ['--setenv', 'QEMU_SONY_PCIE_DBI_TEST', '1']
        if scu_test:
            command += ['--setenv', 'QEMU_SONY_PCIE_SCU_TEST', '1']
        if ccf_test:
            command += ['--setenv', 'QEMU_SONY_CCF_TEST', '1']
        if phy_sram_test:
            command += ['--setenv', 'QEMU_SONY_PHY_SRAM_TEST', '1']
        if phy_init_test:
            command += ['--setenv', 'QEMU_SONY_PHY_INIT_TEST', '1']
        if dfs_test:
            command += ['--setenv', 'QEMU_SONY_DFS_TEST', '1']
        machine = 'virt,accel=qtest'+(',highmem-ecam=off' if low_ecam else '')
        command += ['/qemu', '-machine', machine, '-cpu', 'cortex-a53',
                    '-m', '24G', '-nodefaults', '-nic', 'none', '-display', 'none',
                    '-monitor', 'none', '-serial', 'none', '-sandbox', 'on',
                    '-qmp', 'unix:/out/qmp.sock,server=on,wait=off',
                    '-qtest', 'unix:/out/qtest.sock,server=on,wait=off', '-S']
        self.proc = subprocess.Popen(command, stdout=self.log, stderr=subprocess.STDOUT)

    def connect(self):
        for name in ('qmp', 'qtest'):
            deadline = time.monotonic()+10
            while not (self.root/(name+'.sock')).exists():
                if self.proc.poll() is not None or time.monotonic() > deadline:
                    raise RuntimeError((self.root/'qemu.log').read_text())
                time.sleep(.02)
            connection = socket.socket(socket.AF_UNIX)
            connection.settimeout(10)
            while True:
                try:
                    connection.connect(str(self.root/(name+'.sock')))
                    break
                except (FileNotFoundError, ConnectionRefusedError):
                    if self.proc.poll() is not None or time.monotonic() > deadline:
                        connection.close()
                        raise RuntimeError((self.root/'qemu.log').read_text())
                    time.sleep(.02)
            setattr(self, name+'_socket', connection)
            setattr(self, name+'_file', connection.makefile('rwb', buffering=0))
            if name == 'qmp':
                assert 'QMP' in json.loads(self.qmp_file.readline())
                self.qmp('qmp_capabilities')

    def qmp(self, name, arguments=None):
        request = {'execute': name}
        if arguments is not None:
            request['arguments'] = arguments
        self.qmp_file.write((json.dumps(request)+'\n').encode())
        while True:
            response = json.loads(self.qmp_file.readline())
            if 'event' not in response:
                assert 'return' in response, response
                return response['return']

    def qtest(self, command):
        self.qtest_file.write((command+'\n').encode())
        response = self.qtest_file.readline().decode().strip()
        assert response.startswith('OK'), response
        return response[2:].strip()

    def write(self, address, data):
        self.qtest(f'write 0x{address:x} 0x{len(data):x} 0x{data.hex()}')

    def read(self, address, length):
        result = self.qtest(f'read 0x{address:x} 0x{length:x}')
        return bytes.fromhex(result.removeprefix('0x'))

    def writel(self, address, value):
        self.qtest(f'writel 0x{address:x} 0x{value:x}')

    def readl(self, address):
        return int(self.qtest(f'readl 0x{address:x}'), 0)

    def close(self):
        if self.proc is not None and self.proc.poll() is None:
            if self.qmp_file is None:
                raise RuntimeError('Owned construction failure retained: no QMP, no force-kill')
            self.qmp('quit')
            assert self.proc.wait(timeout=10) == 0
        for file in (self.qmp_file, self.qtest_file, self.qmp_socket, self.qtest_socket):
            if file:
                file.close()
        self.log.close()


def exercise(machine, controller, channel):
    base = (0xf1056000, 0xf1057000)[controller]
    irq = (112, 145)[controller]+channel
    bus_source, bus_destination, bus_code = 0x10001000, 0x10002000, 0x102e4000
    physical = lambda p: p | 0x400000000
    source = bytes((i*29+controller*71+channel*13) & 255 for i in range(256))
    guard = b'\xa5'*288
    machine.write(physical(bus_source), source)
    machine.write(physical(bus_destination)-16, guard)
    machine.write(physical(bus_code), microcode(bus_source, bus_destination, channel))
    machine.writel(0x08000000, 1)
    machine.writel(0x08000100+4*(irq//32), 1 << (irq % 32))
    machine.writel(base+0x20, 1 << channel)
    assert machine.readl(base+0xe0c) == 0xff, 'non-secure event resources'
    machine.writel(base+0xd08, (0xa2 << 16) | (channel << 24))
    machine.writel(base+0xd0c, bus_code)
    machine.writel(base+0xd04, 0)
    for _ in range(100):
        machine.qtest('clock_step 10000')
        if machine.readl(base+0x28) & (1 << channel) and machine.readl(base+0x100+channel*8)&15 == 0:
            break
    destination = machine.read(physical(bus_destination)-16, 288)
    assert destination == b'\xa5'*16+source+b'\xa5'*16, (controller, channel, 'bytes/guard')
    assert machine.read(physical(bus_source), 256) == source
    assert machine.readl(base+0x28) == 1 << channel
    assert machine.readl(base+0x34) == 0, 'unexpected channel fault'
    assert machine.readl(base+0x100+channel*8)&15 == 0, 'program not stopped at END'
    assert machine.readl(0x08000200+4*(irq//32)) & (1 << (irq % 32)), 'GIC pending missing'
    machine.writel(base+0x2c, 1 << channel)
    assert machine.readl(base+0x28) == 0
    return {'controller': controller, 'channel': channel, 'gic_irq': irq,
            'bytes': 256, 'destination_sha256': hashlib.sha256(source).hexdigest(),
            'source_unchanged': True, 'outside_guards_unchanged': True, 'event_cleared': True}


def exercise_surplus_and_other_tag(machine):
    base, physical = 0xf1056000, lambda p: p | 0x400000000
    ccr = 1 | (2 << 1) | (15 << 4) | (1 << 14) | (2 << 15) | (15 << 18)
    source0, destination0, code0 = 0x10004000, 0x10005000, 0x102f4000
    source1, destination1, code1 = 0x10006000, 0x10007000, 0x102f5000
    a, b = bytes(range(128)), bytes(255-i for i in range(64))
    for address, payload in ((source0, a), (source1, b)):
        machine.write(physical(address), payload)
    for address in (destination0, destination1):
        machine.write(physical(address)-16, b'\xa5'*160)
    # ch0 prefetches first, then ch1 holds its own bytes behind tag0. Retire
    # ch0 before releasing ch1: flush must neither leave tag0 nor drop tag1.
    waiting = (mov(0, source1)+mov(1, ccr)+mov(2, destination1)
               +bytes((4, 0x36, 6 << 3, 8, 0x13, 0x34, 1 << 3, 0)))
    surplus = (mov(0, source0)+mov(1, ccr)+mov(2, destination0)
               +bytes((4, 4, 0x36, 7 << 3, 8, 0x13, 0x34, 0, 0)))
    machine.write(physical(code1), waiting); machine.write(physical(code0), surplus)
    machine.writel(base+0x20, 3)
    for channel, code in ((0, code0), (1, code1)):
        machine.writel(base+0xd08, (0xa2 << 16) | (channel << 24))
        machine.writel(base+0xd0c, code); machine.writel(base+0xd04, 0)
        machine.qtest('clock_step 10000')
    machine.writel(base+0xd08, (0x34 << 16) | ((7 << 3) << 24))
    machine.writel(base+0xd0c, 0); machine.writel(base+0xd04, 0)
    machine.qtest('clock_step 10000')
    assert machine.readl(base+0x100)&15 == 0, 'surplus prevents END'
    assert machine.readl(base+0x34) == 0, 'surplus lockup/fault'
    assert machine.read(physical(destination0)-16, 160) == b'\xa5'*16+a[:64]+b'\xa5'*80
    assert machine.read(physical(destination1)-16, 160) == b'\xa5'*160
    machine.writel(base+0xd08, (0x34 << 16) | ((6 << 3) << 24))
    machine.writel(base+0xd0c, 0); machine.writel(base+0xd04, 0)
    machine.qtest('clock_step 10000')
    assert machine.readl(base+0x108)&15 == 0 and machine.readl(base+0x34) == 0
    assert machine.read(physical(destination1)-16, 160) == b'\xa5'*16+b+b'\xa5'*80
    assert machine.read(physical(source0), 128) == a and machine.read(physical(source1), 64) == b
    machine.writel(base+0x2c, 3)
    return {'surplus_prefetch_flushed_after_queues_drained': True, 'programs_stopped': True,
            'waiting_other_tag_preserved_and_consumed': True, 'outside_guards_unchanged': True}


def exercise_fault(machine, kind):
    base, channel = 0xf1056000, 2
    source, destination, code = 0x10001000, 0x10002000, 0x102e4000
    physical = lambda p: p | 0x400000000
    content = bytes((i*17+11) & 255 for i in range(256))
    machine.write(physical(source), content)
    machine.write(physical(destination)-16, b'\xa5'*288)
    program_source = 0xff000000 if kind == 'read' else source
    program_destination = 0xff000000 if kind == 'write' else destination
    machine.write(physical(code), microcode(program_source, program_destination, channel))
    machine.writel(0x08000000, 1)
    machine.writel(0x08000100+4*(144//32), 1 << (144 % 32))
    machine.writel(base+0x20, 1 << channel)
    machine.writel(base+0xd08, (0xa2 << 16) | (channel << 24))
    machine.writel(base+0xd0c, 0xff000000 if kind == 'fetch' else code)
    machine.writel(base+0xd04, 0)
    for _ in range(100):
        machine.qtest('clock_step 10000')
        if machine.readl(base+0x34):
            break
    flag = 1 << {'read': 18, 'write': 17, 'fetch': 16}[kind]
    assert machine.readl(base+0x34) == 1 << channel, (kind, 'no channel fault')
    assert machine.readl(base+0x40+channel*4) == flag, (kind, 'wrong fault type')
    assert machine.readl(base+0x28) == 0, (kind, 'false success event')
    assert machine.readl(0x08000200+4*(144//32)) & (1 << (144 % 32)), 'abort GIC missing'
    assert machine.read(physical(destination)-16, 288) == b'\xa5'*288
    assert machine.read(physical(source), 256) == content
    return {'fault': kind, 'fault_flag': flag, 'normal_event_absent': True,
            'abort_irq_pending': True, 'valid_destination_and_guards_unchanged': True}


def exercise_original_fixture(machine, run):
    original = json.loads((run/'result.json').read_text())
    descriptor, source, destination = [int(v, 16) for v in original['dma_buffer_addresses']]
    program = (run/'output/original-channel0-microcode.bin').read_bytes()
    assert len(program) == 0xc440 and program[0x4510:0x4512] == b'\xa2\x00'
    pc = struct.unpack_from('<I', program, 0x4512)[0]
    assert pc == 0x102e8518 and program[0x4550] == 0
    source_page = (run/'output/source-page.bin').read_bytes()
    expected = (run/'output/destination-page.bin').read_bytes()
    machine.write(0x4102e4000, program)
    machine.write(source, source_page); machine.write(destination, b'\xa5'*4096)
    machine.writel(0x08000000, 1)
    machine.writel(0x0800010c, 1 << 16)
    machine.writel(0x08000110, 1 << 16)
    machine.writel(0xf1056020, 1)
    machine.writel(0xf1056d08, 0xa2 << 16)
    machine.writel(0xf1056d0c, pc); machine.writel(0xf1056d04, 0)
    for _ in range(100):
        machine.qtest('clock_step 10000')
        if machine.readl(0xf1056028) == 1 and machine.readl(0xf1056100)&15 == 0:
            break
    assert machine.readl(0xf1056100)&15 == 0 and machine.readl(0xf1056034) == 0
    assert machine.readl(0x0800020c)&(1 << 16)
    assert not machine.readl(0x08000210)&(1 << 16), 'original replay abort'
    assert machine.read(source, 4096) == source_page
    assert machine.read(destination, 4096) == expected
    return {'original_runtime_microcode_sha256': hashlib.sha256(program).hexdigest(),
            'entry': hex(pc), 'stopped_without_kill': True, 'normal_event': True,
            'abort_absent': True, 'entire_source_destination_guards_verified': True}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('binary', type=Path)
    parser.add_argument('--original-fixture', type=Path)
    args = parser.parse_args()
    root = Path(tempfile.mkdtemp(prefix='pl330-qtest-', dir='/var/tmp'))
    print('PL330_QTEST_OUTPUT', root, flush=True)
    result = {'scope': 'stock PL330 hardware microcode only; no original driver or CMOS',
              'binary_sha256': hashlib.sha256(args.binary.read_bytes()).hexdigest(),
              'original_driver_verified': False, 'capture_verified': False, 'runs': [], 'faults': []}
    try:
        for enabled in (False, True):
            run = root/('enabled' if enabled else 'disabled')
            run.mkdir()
            machine = Machine(args.binary.resolve(), run, enabled)
            try:
                machine.connect()
                if not enabled:
                    assert machine.readl(0xf1056fe0) != 0x30, 'opt-in device unexpectedly present'
                    result['default_disabled_verified'] = True
                else:
                    assert machine.readl(0xf1056fe0) == 0x30
                    assert machine.readl(0xf1057fe0) == 0x30
                    for controller in range(2):
                        for channel in range(8):
                            result['runs'].append(exercise(machine, controller, channel))
                    result['surplus_and_other_tag'] = exercise_surplus_and_other_tag(machine)
            finally:
                machine.close()
        # Each error starts from cold hardware; QMP system_reset completion and
        # stock PL330 reset-state behaviour are separate, unverified contracts.
        for kind in ('read', 'write', 'fetch'):
            run = root/('fault_'+kind)
            run.mkdir()
            machine = Machine(args.binary.resolve(), run, True)
            try:
                machine.connect()
                result['faults'].append(exercise_fault(machine, kind))
            finally:
                machine.close()
        if args.original_fixture:
            run = root/'original_replay'; run.mkdir()
            machine = Machine(args.binary.resolve(), run, True)
            try:
                machine.connect()
                result['original_program_replay'] = exercise_original_fixture(machine, args.original_fixture)
            finally:
                machine.close()
        result['microcode_copy_and_event_verified'] = True
        print('PL330_HARDWARE_COPY_PASS', len(result['runs']), flush=True)
    finally:
        (root/'result.json').write_text(json.dumps(result, indent=2)+'\n')


if __name__ == '__main__':
    import importlib.util
    spec = importlib.util.spec_from_file_location('admission', HERE.parent/'admission.py')
    gate = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(gate)
    with gate.idle_lock(HERE.parents[2]/'runtime/analysis/.menu-probe.lock'):
        main()
