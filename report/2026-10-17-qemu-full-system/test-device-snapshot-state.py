"""Pinned source checks plus opt-in independent QEMU/qtest migration readback.

DEVICE_SNAPSHOT_SOURCE overrides the read-only baseline source directory.
DEVICE_SNAPSHOT_QEMU enables the actual 64 MiB model migration experiment.
DEVICE_SNAPSHOT_EVIDENCE selects a NEW directory for its permanent raw evidence.
"""
import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import tempfile
import time
import unittest

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('device_snapshot_state', HERE / 'device-snapshot-state.py')
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
backend_spec = importlib.util.spec_from_file_location('retained_boot', HERE / 'retained-boot.py')
backend = importlib.util.module_from_spec(backend_spec); backend_spec.loader.exec_module(backend)
BASELINE = Path(os.environ.get('DEVICE_SNAPSHOT_SOURCE', str(HERE / 'runtime/usb-build/build-na_pp627/native-input/source/build/qemu-Sr86DQ/qemu-11.1.2')))


class SourceTests(unittest.TestCase):
    def setUp(self):
        if not BASELINE.is_dir():
            self.skipTest('Pinned read-only QEMU source unavailable; set DEVICE_SNAPSHOT_SOURCE')
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name); self.source = self.root / 'source'; self.source.mkdir()
        for name in m.INPUTS:
            target = self.source / name; target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(BASELINE / name, target)

    def generated(self):
        output = self.root / 'overlay'
        receipt = m.generate(self.source, output)
        return output, receipt

    def test_all_inputs_bound_and_originals_unchanged(self):
        output, receipt = self.generated()
        self.assertEqual(receipt['inputs'], m.INPUTS)
        self.assertEqual(set(receipt['outputs']), set(m.INPUTS))
        for name, expected in m.INPUTS.items():
            self.assertEqual(m.sha((self.source / name).read_bytes()), expected)
            self.assertEqual(m.sha((output / name).read_bytes()), receipt['outputs'][name])
        self.assertFalse(receipt['device_migration']['complete'])
        self.assertFalse(receipt['actual_roundtrip_verified'])
        self.assertIn('post_load', (output / 'device-state.patch').read_text())

    def test_source_drift_rejected_before_any_output(self):
        for name in m.INPUTS:
            path = self.source / name; original = path.read_bytes(); path.write_bytes(original + b'\n')
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, 'SHA256 drift'):
                m.generate(self.source, self.root / 'bad')
            self.assertFalse((self.root / 'bad').exists())
            path.write_bytes(original)

    def test_timer_preserves_deadline_epoch_irq_and_every_ack(self):
        output, _ = self.generated(); text = (output / 'hw/timer/sony_hwtimer.c').read_text()
        for field in ('epoch', 'snapshot_clock', 'count', 'control', 'compare', 'irq_level', 'timer'):
            self.assertRegex(text, r'VMSTATE_\w+\(' + field + r', SonyHwtimerState\)')
        self.assertIn('qemu_set_irq(s->irq, s->irq_level)', text)
        self.assertIn('timer_mod(s->timer, timer_expire_time_ns(s->timer) + shift)', text)
        self.assertIn('s->snapshot_clock = qemu_clock_get_ns(QEMU_CLOCK_VIRTUAL)', text)
        self.assertIn('return -EINVAL', text)
        self.assertEqual(text.count('s->irq_level = false;'), 2)
        self.assertEqual(text.count('s->irq_level = true;'), 1)
        self.assertIn('ACK alone preserves the comparator deadline', text)
        post = text[text.index('static int sony_timer_post_load'):text.index('static const VMStateDescription vmstate_sony_timer')]
        self.assertNotIn('reschedule(s)', post)
        self.assertIn('s->epoch += shift;', post)
        self.assertNotIn('s->epoch = qemu_clock_get_ns', post)

    def test_spacc_full_buffer_never_serializes_host_pointer(self):
        output, _ = self.generated(); text = (output / 'hw/misc/sony_spacc_stub.c').read_text()
        self.assertIn('uint32_t ram[0x40000 / 4]', text)
        self.assertIn('VMSTATE_UINT32_ARRAY(ram, SonySpaccStub, 0x40000 / 4)', text)
        self.assertNotIn('g_malloc0', text)
        self.assertNotIn('VMSTATE_POINTER', text)
        self.assertNotIn('uint32_t *ram', text)

    def test_input_held_moves_but_live_endpoints_are_blocked_both_directions(self):
        output, _ = self.generated(); text = (output / 'hw/input/sony-ui-input.c').read_text()
        self.assertIn('VMSTATE_BOOL_ARRAY(held, SonyUIInput, KEY_MAX + 1)', text)
        self.assertIn('.pre_save = sony_input_pre_save', text)
        self.assertIn('.post_load = sony_input_post_load', text)
        self.assertIn('return sony_input_pre_save(opaque)', text)
        self.assertIn('qemu_chr_fe_backend_open(&s->chr)', text)
        self.assertIn('return -EBUSY', text)
        for field in ('chr', 'handler', 'display'):
            self.assertNotRegex(text, r'VMSTATE_\w+\(' + field + ',')

    def test_media_and_mmc_state_registered_with_distinct_instances(self):
        output, _ = self.generated(); text = (output / 'hw/arm/virt.c').read_text()
        for field in ('value', 'reads', 'writes'):
            self.assertRegex(text, r'VMSTATE_UINT\d+\(' + field + r', SonyMediaDetectState\)')
        for field in ('reads', 'writes', 'reset'):
            self.assertRegex(text, r'VMSTATE_UINT\d+\(' + field + r', SonyMmcTraceState\)')
        self.assertIn('VMSTATE_UINT64_EQUAL(base, SonyMmcTraceState)', text)
        self.assertIn('vmstate_register(NULL, 0, &vmstate_sony_media, s)', text)
        self.assertIn('vmstate_register(NULL, i, &vmstate_sony_mmc, s)', text)
        self.assertEqual(text.count('qdev_new("usb_dwc3")'), 1)
        self.assertNotIn('VMSTATE_ULONG', text)

    def test_existing_output_symlinks_and_input_alias_are_rejected(self):
        output, _ = self.generated()
        with self.assertRaises(FileExistsError):
            m.generate(self.source, output)
        with self.assertRaises(ValueError):
            m.generate(self.source, self.source / 'child')
        alias = self.root / 'alias'; alias.symlink_to(self.source, target_is_directory=True)
        with self.assertRaises(ValueError):
            m.generate(alias, self.root / 'alias-result')

    def test_reapplying_to_patched_source_does_not_silently_accept_unknown_version(self):
        output, _ = self.generated()
        with self.assertRaisesRegex(ValueError, 'SHA256 drift'):
            m.generate(output, self.root / 'second')


def bound_identity(binary, *, accel='qtest', input_peer=False, entry=None):
    return dict(run='synthetic-source', generation=0, profile='ram-hotboot', source_class='synthetic-guest',
                machine={'type': 'virt-11.1', 'ram_bytes': 64 * 1024 * 1024, 'cpu': 'cortex-a53', 'cpus': 1,
                         'accel': accel, 'input_peer': input_peer, 'entry': entry},
                qemu={'version': '11.1.2', 'sha256': m.sha(binary.read_bytes())},
                resources={**{k: m.sha(k.encode()) for k in ('kernel', 'dtb', 'ram0', 'ap', 'cp', 'manifest')},
                           'partitions': {'synthetic-ram': m.sha(b'no-firmware-no-disks')}},
                device_migration={'complete': True, 'devices': ['upstream-virt', 'sony-hwtimer', 'sony-spacc-stub',
                    'sony-media-detect', 'sony-mmc-trace', 'stateless-cxd-bus-stub'] + (['sony-ui-input'] if input_peer else []),
                    'audit_sha256': m.sha(Path(__file__).read_bytes()), 'external_state': 'none', 'blockers': []})


class Machine:
    def __init__(self, binary, directory, incoming=False, input_peer=False, accel='qtest', entry=None):
        self.directory = directory; directory.mkdir()
        self.irq_events = []
        self.socket_dir = tempfile.TemporaryDirectory(prefix='a7c2-retain-')
        self.qmp_path = Path(self.socket_dir.name) / 'qmp.sock'
        self.qtest_path = Path(self.socket_dir.name) / 'qtest.sock'
        args = [str(binary), '-machine', 'virt,secure=off,gic-version=2', '-cpu', 'cortex-a53',
                '-m', '64M', '-smp', '1', '-accel', accel, '-S', '-nodefaults', '-display', 'none',
                '-monitor', 'none', '-serial', 'none', '-nic', 'none', '-no-reboot', '-sandbox', 'on',
                '-qmp', 'unix:' + str(self.qmp_path) + ',server=on,wait=off',
                '-qtest', 'unix:' + str(self.qtest_path) + ',server=on,wait=off']
        if entry is not None:
            args += ['-device', f'loader,addr={entry:#x},cpu-num=0']
        if incoming:
            args += ['-incoming', 'defer']
        if input_peer:
            args += ['-device', 'ramfb,id=screen', '-chardev', 'socket,id=keys,path=' + str(Path(self.socket_dir.name) / 'keys.sock') + ',server=on,wait=off',
                     '-device', 'sony-ui-input,id=keysbridge,chardev=keys,display=screen']
        env = {'PATH': os.defpath, 'LC_ALL': 'C', 'QEMU_SONY_TIMERS': '1',
               'QEMU_SONY_MEDIA_DETECT': '0x12345678', 'QEMU_SONY_MMC_TRACE': '0x89abcdef'}
        self.log = (directory / 'qemu.log').open('xb')
        self.proc = subprocess.Popen(args, env=env, stdin=subprocess.DEVNULL, stdout=self.log, stderr=subprocess.STDOUT)
        (directory / 'invocation.json').write_text(json.dumps({'args': args, 'env': env, 'pid': self.proc.pid}, indent=2))
        try:
            self.sock = self.connect(self.qmp_path)
            self.stream = self.sock.makefile('rwb')
            greeting = json.loads(self.stream.readline())
            if 'QMP' not in greeting:
                raise RuntimeError('Missing QMP greeting')
            self.qmp = backend.FDQMP(self.sock, self.stream); self.qmp('qmp_capabilities')
            self.qt = self.connect(self.qtest_path); self.qt_stream = self.qt.makefile('rwb')
        except Exception:
            if self.proc.poll() is not None:
                self.log.close(); self.socket_dir.cleanup()
                (directory / 'exit.json').write_text(json.dumps({'returncode': self.proc.returncode, 'signals_sent': []}))
            else:
                self.socket_dir._finalizer.detach()
                (directory / 'startup-owner-retained.json').write_text(json.dumps({'pid': self.proc.pid, 'socket_dir': self.socket_dir.name}))
            raise

    def connect(self, path):
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM); sock.settimeout(10)
            try:
                sock.connect(str(path)); return sock
            except (FileNotFoundError, ConnectionRefusedError):
                sock.close()
                if self.proc.poll() is not None:
                    raise RuntimeError('Independent QEMU exited; see ' + str(self.directory / 'qemu.log'))
                time.sleep(.02)
        raise TimeoutError('Independent QEMU socket timeout')

    def command(self, command):
        self.qt_stream.write(command.encode() + b'\n'); self.qt_stream.flush()
        while True:
            line = self.qt_stream.readline().decode().strip()
            if line.startswith('OK'):
                return line.split()[1:]
            if line.startswith('IRQ '):
                self.irq_events.append(line)
            else:
                raise RuntimeError('qtest: ' + line)

    def read(self, address):
        return int(self.command(f'readl {address:#x}')[0], 0)

    def write(self, address, value):
        self.command(f'writel {address:#x} {value:#x}')

    def close(self):
        self.qmp('quit')
        self.proc.wait(timeout=10)
        for item in (self.qt_stream, self.qt, self.stream, self.sock, self.log):
            item.close()
        (self.directory / 'exit.json').write_text(json.dumps({'returncode': self.proc.returncode, 'signals_sent': []}))
        self.socket_dir.cleanup()


@unittest.skipUnless(os.environ.get('DEVICE_SNAPSHOT_QEMU'), 'Set DEVICE_SNAPSHOT_QEMU for real independent migration')
class ActualMigrationTests(unittest.TestCase):
    def test_small_machine_cpu_ram_timer_spacc_media_and_mmc_roundtrip(self):
        binary = Path(os.environ['DEVICE_SNAPSHOT_QEMU']).absolute()
        root = Path(os.environ['DEVICE_SNAPSHOT_EVIDENCE']) if os.environ.get('DEVICE_SNAPSHOT_EVIDENCE') else Path(tempfile.mkdtemp(prefix='sony-device-migration-'))
        root.mkdir(exist_ok=True)
        self.assertFalse((root / 'source').exists(), 'Evidence directory must be new')
        source = Machine(binary, root / 'source'); self.addCleanup(source.close)
        target = Machine(binary, root / 'target', incoming=True); self.addCleanup(target.close)
        gic = next(c['name'] for c in target.qmp('qom-list', {'path': '/machine/unattached'})
                   if c['type'] in ('child<arm_gic>', 'child<arm-gic>'))
        target.command('irq_intercept_in /machine/unattached/' + gic)
        # Timer1 is a completed one-shot with a still-high IRQ before migration.
        source.qmp('cont')
        source.write(0xf1043010, 0); source.write(0xf1043008, 11); source.write(0xf1043000, 0x1110)
        source.command('clock_step 2750')
        self.assertEqual(source.read(0xf1043000), 0x110)
        source.qmp('stop')
        ram, timer, spacc = 0x40001000, 0xf1042000, 0xf7fc0000
        source.write(ram, 0x13579bdf)
        offsets = [0, 0x80, 0x1000, 0x3fffc]
        registers = b''.join((0xc0010000 + offset).to_bytes(4, 'little') for offset in range(0, 0x40000, 4))
        source.command(f'write {spacc:#x} {len(registers)} 0x{registers.hex()}')
        expected_registers = bytearray(registers)
        for offset, mask in ((4, (1 << 20) | (1 << 18)), (0x1c, 1 << 20)):
            value = int.from_bytes(expected_registers[offset:offset + 4], 'little') | mask
            expected_registers[offset:offset + 4] = value.to_bytes(4, 'little')
        source.write(timer + 16, 37); source.write(timer + 8, 4037); source.write(timer, 0x1110)
        source.command('clock_step 25000')
        self.assertEqual(source.read(timer + 12), 137)
        # Free-running comparator just fired: the next deadline is a 32-bit wrap.
        source.write(0xf1044010, 0); source.write(0xf1044008, 3); source.write(0xf1044000, 0x1130)
        source.qmp('cont'); source.command('clock_step 750'); source.qmp('stop')
        source.read(0xf1388f44); source.read(0xf1388f44)
        for _ in range(8):
            source.write(0xf1388f44, 0)
        source.read(0xf1388000); source.write(0xf1388000, 7)
        state = bound_identity(binary)
        saved = backend.bind_snapshot(state, source.qmp, root / 'snapshot', timeout=30)
        next_state = copy.deepcopy(state); next_state.update(run='qtest-target', generation=1)
        wrong_identity = copy.deepcopy(next_state); wrong_identity['resources']['cp'] = '0' * 64
        with self.assertRaises(backend.SnapshotError):
            backend.restore_snapshot(root / 'snapshot', wrong_identity, target.qmp, timeout=30)
        self.assertEqual(target.qmp('query-status')['status'], 'inmigrate')
        restored = backend.restore_snapshot(root / 'snapshot', next_state, target.qmp, timeout=30)
        target.qmp('stop')
        self.assertEqual(target.read(ram), 0x13579bdf)
        self.assertEqual(target.read(timer), 0x1110)
        self.assertEqual(target.read(timer + 12), 140)
        self.assertEqual(target.read(0xf1043000), 0x110)
        self.assertIn('IRQ raise 201', target.irq_events)
        target.write(0xf1043004, 1)
        target.read(0xf1043000)
        self.assertIn('IRQ lower 201', target.irq_events)
        self.assertIn('IRQ raise 202', target.irq_events)
        target.write(0xf1044004, 1)
        target.read(0xf1044000)
        target.irq_events.clear()
        self.assertEqual(target.read(timer + 8), 4037)
        for offset in offsets:
            self.assertEqual(target.read(spacc + offset), 0xc0010000 + offset)
        self.assertEqual(bytes.fromhex(target.command(f'read {spacc:#x} 0x40000')[0].removeprefix('0x')), expected_registers)
        self.assertEqual(target.read(0xf1388f44), 0x12345678)
        target.write(0xf1388f44, 0)
        self.assertEqual(target.read(0xf1388000), 0x89abcdef)
        target.write(0xf1388000, 9)
        target.qmp('cont')
        target.command('clock_step 974250')
        target.qmp('stop')
        self.assertEqual(target.read(timer), 0x110)
        self.assertEqual(target.read(timer + 12), 4037)
        self.assertNotIn('IRQ raise 202', target.irq_events)
        source.log.flush(); target.log.flush()
        self.assertIn('SONY_MEDIA_DETECT_READ count=3', (target.directory / 'qemu.log').read_text())
        self.assertIn('SONY_MMC_TRACE_READ base=0xf1388000 n=2 ', (target.directory / 'qemu.log').read_text())
        self.assertIn('SONY_MMC_TRACE_WRITE base=0xf1388000 n=2 ', (target.directory / 'qemu.log').read_text())
        self.assertNotIn('SONY_MEDIA_DETECT_WRITE_IGNORED', (target.directory / 'qemu.log').read_text())
        self.assertTrue(saved['verified']); self.assertTrue(restored['retained_cpu_resumed'])
        (root / 'roundtrip.json').write_text(json.dumps(dict(snapshot=saved, restore=restored,
            model_state_readback=True, spacc_bytes_verified=0x40000, pending_irq_restored=True,
            free_running_wrap_preserved=True, actual_guest_instruction_continuation=False,
            physical_wbi_verified=False, machine_scope='64MiB synthetic qtest, no original AP/CP/firmware'), indent=2))
        print('ACTUAL_DEVICE_MIGRATION_EVIDENCE', root)

    def test_external_input_peer_actually_blocks_migration(self):
        binary = Path(os.environ['DEVICE_SNAPSHOT_QEMU']).absolute()
        base = Path(os.environ['DEVICE_SNAPSHOT_EVIDENCE']) if os.environ.get('DEVICE_SNAPSHOT_EVIDENCE') else Path(tempfile.mkdtemp(prefix='sony-peer-'))
        root = base / 'external-peer'; root.mkdir(parents=True)
        source = Machine(binary, root / 'source', input_peer=True); self.addCleanup(source.close)
        peer = source.connect(Path(source.socket_dir.name) / 'keys.sock'); self.addCleanup(peer.close)
        source.qmp('cont'); source.qmp('stop')
        # Force a connected peer through the host attestation to test the C guard.
        state = bound_identity(binary, input_peer=True)
        with self.assertRaises(backend.SnapshotError) as error:
            backend.bind_snapshot(state, source.qmp, root / 'snapshot', timeout=10)
        self.assertFalse((root / 'snapshot/receipt.json').exists())
        self.assertFalse(error.exception.receipt['verified'])
        source.log.flush()
        self.assertIn('disconnect/quiesce external peer', (source.directory / 'qemu.log').read_text())
        (root / 'blocked.json').write_text(json.dumps(error.exception.receipt, indent=2))

    def test_quiesced_input_preserves_held_and_requires_release_before_new_tap(self):
        binary = Path(os.environ['DEVICE_SNAPSHOT_QEMU']).absolute()
        base = Path(os.environ['DEVICE_SNAPSHOT_EVIDENCE']) if os.environ.get('DEVICE_SNAPSHOT_EVIDENCE') else Path(tempfile.mkdtemp(prefix='sony-held-'))
        root = base / 'input-held'; root.mkdir(parents=True)
        source = Machine(binary, root / 'source', input_peer=True); self.addCleanup(source.close)
        target = Machine(binary, root / 'target', incoming=True, input_peer=True); self.addCleanup(target.close)
        peer = source.connect(Path(source.socket_dir.name) / 'keys.sock')
        source.qmp('cont')

        def key(machine, down):
            return machine.qmp('input-send-event', {'device': 'screen', 'events': [
                {'type': 'key', 'data': {'down': down, 'key': {'type': 'qcode', 'data': 'esc'}}}]})

        key(source, True)
        self.assertEqual(peer.recv(1), b'M')
        source.qmp('stop'); peer.close()
        deadline = time.monotonic() + 5
        while source.qmp('qom-get', {'path': '/machine/peripheral/keysbridge', 'property': 'input-connected'}):
            if time.monotonic() > deadline:
                self.fail('Source input peer did not disconnect')
        state = bound_identity(binary, input_peer=True)
        backend.bind_snapshot(state, source.qmp, root / 'snapshot', timeout=30)
        next_state = copy.deepcopy(state); next_state.update(run='held-target', generation=1)
        restored = backend.restore_snapshot(root / 'snapshot', next_state, target.qmp, timeout=30)
        new_peer = target.connect(Path(target.socket_dir.name) / 'keys.sock'); self.addCleanup(new_peer.close)
        key(target, True)
        new_peer.settimeout(.1)
        with self.assertRaises(TimeoutError):
            new_peer.recv(1)
        key(target, False); key(target, True)
        new_peer.settimeout(5)
        self.assertEqual(new_peer.recv(1), b'M')
        key(target, False)
        (root / 'held-state.json').write_text(json.dumps(dict(restore=restored,
            held_duplicate_suppressed=True, release_then_new_tap=True, host_socket_not_migrated=True), indent=2))

    def test_tcg_resumes_old_guest_stack_and_never_reexecutes_entry(self):
        binary = Path(os.environ['DEVICE_SNAPSHOT_QEMU']).absolute()
        base = Path(os.environ['DEVICE_SNAPSHOT_EVIDENCE']) if os.environ.get('DEVICE_SNAPSHOT_EVIDENCE') else Path(tempfile.mkdtemp(prefix='sony-cpu-'))
        root = base / 'cpu-continuation'; root.mkdir(parents=True)
        assembly = root / 'guest.S'
        assembly.write_text('''.global _start
_start:
    mov x0, #0
    mov x1, #0x40000000
    add x1, x1, #0x2000
    mov x2, #0x40000000
    add x2, x2, #0x3000
    mov sp, x2
loop:
    add x0, x0, #1
    str x0, [x1]
    str x0, [sp]
    b loop
.org 0x100
fatal_entry:
    mov x3, #0x40000000
    add x3, x3, #0x2000
    add x3, x3, #0x10
    mov x4, #0xdead
    str x4, [x3]
halt:
    b halt
''')
        program = root / 'guest.bin'
        compilation = subprocess.run(['clang', '--target=aarch64-none-elf', '-fuse-ld=lld', '-nostdlib',
            '-Wl,--oformat=binary', '-Wl,-Ttext=0x40010000', '-Wl,-e,_start', str(assembly), '-o', str(program)],
            capture_output=True)
        (root / 'guest-build.log').write_bytes(compilation.stdout + compilation.stderr)
        self.assertEqual(compilation.returncode, 0, compilation.stderr.decode(errors='replace'))
        source = Machine(binary, root / 'source', accel='tcg,thread=single', entry=0x40010000); self.addCleanup(source.close)
        target = Machine(binary, root / 'target', incoming=True, accel='tcg,thread=single', entry=0x40010000); self.addCleanup(target.close)
        source.command(f'write 0x40010000 {program.stat().st_size} 0x{program.read_bytes().hex()}')
        source.qmp('cont')
        deadline = time.monotonic() + 5
        while source.read(0x40002000) < 1000:
            if time.monotonic() > deadline:
                self.fail('Synthetic guest did not execute')
        source.qmp('stop')
        counter = source.read(0x40002000)
        self.assertGreater(counter, 0)
        self.assertGreater(source.read(0x40003000), 0)
        before = source.qmp('human-monitor-command', {'command-line': 'info registers'})
        (root / 'registers-before.txt').write_text(before)
        # A fresh CPU starting at entry would take this fatal branch instead of loop.
        source.write(0x40010000, 0x14000040)
        state = bound_identity(binary, accel='tcg,thread=single', entry=0x40010000)
        state['resources']['kernel'] = m.sha(program.read_bytes())
        saved = backend.bind_snapshot(state, source.qmp, root / 'snapshot', timeout=30)
        next_state = copy.deepcopy(state); next_state.update(run='tcg-target', generation=1)
        restored = backend.restore_snapshot(root / 'snapshot', next_state, target.qmp, timeout=30)
        deadline = time.monotonic() + 5
        while target.read(0x40002000) <= counter:
            if time.monotonic() > deadline:
                self.fail('Retained guest CPU did not continue its old loop')
        target.qmp('stop')
        self.assertEqual(target.read(0x40002010), 0)
        self.assertEqual(target.read(0x40010000), 0x14000040)
        self.assertGreater(target.read(0x40003000), counter)
        after = target.qmp('human-monitor-command', {'command-line': 'info registers'})
        (root / 'registers-after.txt').write_text(after)
        self.assertIn('40003000', before); self.assertIn('40003000', after)
        (root / 'continuation.json').write_text(json.dumps(dict(snapshot=saved, restore=restored,
            old_guest_stack_continued=True, fresh_entry_poison_preserved=True,
            physical_wbi_verified=False, machine_scope='64MiB synthetic TCG guest; no original firmware'), indent=2))


if __name__ == '__main__':
    unittest.main()
