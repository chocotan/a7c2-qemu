#!/usr/bin/env python3
"""Host checks; opt in with RETAINED_PERSISTENT_STAGE for the NEW combined binary.

No historical VM or retained-boot API is used. Actual checks launch 64 MiB qtest
machines, a synthetic 32 MiB disk, and a disconnected input bridge. This does not
admit original AP restore or implement the production external-state transaction.
"""
import fcntl
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import runpy
import shlex
import socket
import subprocess
import tempfile
import time
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('retained_persistent_build', HERE / 'retained-persistent-build.py')
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
BASELINE = HERE.parents[1] / 'analysis/scratch/a7c2-persistent-usb-gpio-20261106/production'


class HostTests(unittest.TestCase):
    def test_exact_production_sources_and_historical_overlay_stay_bound(self):
        original, changed = m.transformed(BASELINE / 'qemu-11.1.2')
        for name, expected in m.INPUTS.items():
            self.assertEqual(m.sha(original[name]), expected)
            self.assertNotEqual(original[name], changed[name])
        for name, expected in m.FLASH.items():
            self.assertEqual(m.sha(changed['hw/block/a7c2-persistent/' + name]), expected)
        historical = runpy.run_path(str(HERE / 'device-snapshot-state.py'))
        self.assertEqual(historical['INPUTS']['hw/arm/virt.c'], m.OLD_VIRT_SHA)
        self.assertEqual(m.digest(HERE / 'device-snapshot-state.py'), m.OVERLAY_SHA)

    def test_source_drift_refuses_every_file_before_any_install(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            for name in (*m.INPUTS, *('hw/block/a7c2-persistent/' + n for n in m.FLASH)):
                dest = root / name
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes((BASELINE / 'qemu-11.1.2' / name).read_bytes())
            for name in m.INPUTS:
                p = root / name
                original = p.read_bytes()
                p.write_bytes(original + b'\n')
                with self.subTest(source=name), self.assertRaisesRegex(ValueError, 'SHA256 drift'):
                    m.transformed(root)
                p.write_bytes(original)
            with patch.dict(m.FLASH, {'flash-qemu.c': '0' * 64}):
                with self.assertRaisesRegex(ValueError, 'SHA256 drift'):
                    m.transformed(root)

    def test_same_surgical_anchors_and_no_usb_state_omission(self):
        original, changed = m.transformed(BASELINE / 'qemu-11.1.2')
        board = changed['hw/arm/virt.c'].decode()
        for name in ('vmstate_sony_media', 'vmstate_sony_mmc'):
            self.assertIn('&' + name, board)
        for name, marker in [('hw/timer/sony_hwtimer.c', '&vmstate_sony_timer'),
                             ('hw/misc/sony_spacc_stub.c', '&vmstate_sony_spacc'),
                             ('hw/input/sony-ui-input.c', '&vmstate_sony_input')]:
            self.assertIn(marker, changed[name].decode())
        self.assertIn('VMSTATE_TIMER_PTR(timer, SonyHwtimerState)', changed['hw/timer/sony_hwtimer.c'].decode())
        self.assertIn('VMSTATE_UINT32_ARRAY(ram, SonySpaccStub, 0x40000 / 4)', changed['hw/misc/sony_spacc_stub.c'].decode())
        self.assertIn('qemu_chr_fe_backend_open', changed['hw/input/sony-ui-input.c'].decode())
        self.assertIn('VMSTATE_UINT64_EQUAL(base, SonyMmcTraceState)', board)
        section = board[board.index('    /* Full-dump-only upstream DWC3'):board.index('    create_msi_controller(vms);')]
        section = section.replace('            vmstate_register(NULL, 0, &vmstate_sony_media, s);\n', '')
        section = section.replace('                vmstate_register(NULL, i, &vmstate_sony_mmc, s);\n', '')
        old = original['hw/arm/virt.c'].decode()
        self.assertEqual(section, old[old.index('    /* Full-dump-only upstream DWC3'):old.index('    create_msi_controller(vms);')])
        flash = changed['hw/block/a7c2-persistent/flash-qemu.c'].decode()
        self.assertIn('DEFINE_PROP_BOOL("retained-state", A7PFDevice, retained_state, false)', flash)
        self.assertIn('dc->vmsd=&a7pf_vmstate;', flash)
        self.assertIn('VMSTATE_UINT8_ARRAY(migration.disk_sha256, A7PFDevice, 32)', flash)
        self.assertIn('qdev_prop_set_bit(pf,"retained-state",true)', board)
        self.assertIn(m.GUARD, board)
        with self.assertRaisesRegex(ValueError, 'anchor drift'):
            m.replace(board, 'missing reviewed anchor', '')

    def test_environment_rejects_all_usb_even_empty_and_unknown_flags(self):
        for name in ('QEMU_SONY_USB_DEVICE', 'QEMU_SONY_USB_DWC3', 'QEMU_SONY_DWC3_CORE_TEST',
                     'QEMU_SONY_USB_BACKEND_SOCKET', 'QEMU_SONY_USB_NEW_OPTION'):
            for value in ('', '0', '1'):
                with self.subTest(name=name, value=value), self.assertRaisesRegex(ValueError, 'USB'):
                    m.validate_environment({name: value})
        for controller in ('', 'upstream-host', 'sony-device', '1'):
            with self.subTest(controller=controller), self.assertRaisesRegex(ValueError, 'controller must be off'):
                m.validate_environment({'QEMU_FULL_USB_CONTROLLER': controller})
        for flag in ('', '0', 'true', '2', ' 1'):
            with self.subTest(flag=flag), self.assertRaisesRegex(ValueError, 'flag/profile'):
                m.validate_environment({'QEMU_A7PF_PROFILE': m.PROFILE, 'QEMU_A7PF_RETAINED_STATE': flag})
        for env in ({'QEMU_A7PF_RETAINED_STATE': '1'},
                    {'QEMU_A7PF_PROFILE': m.ORIGIN_PROFILE, 'QEMU_A7PF_RETAINED_STATE': '1'},
                    {'QEMU_A7PF_PROFILE': m.PROFILE}, {'QEMU_A7PF_PROFILE': 'unknown'},
                    {'QEMU_A7PF_NEW': '1'}, {'QEMU_A7PF_FD': '3'}):
            with self.subTest(env=env), self.assertRaises(ValueError):
                m.validate_environment(env)

    def test_explicit_and_cold_launcher_binding(self):
        with tempfile.TemporaryFile() as disk:
            for retained in (False, True):
                env = m.profile_environment(disk.fileno(), inherited={}, retained=retained)
                self.assertEqual(env['QEMU_A7PF_PROFILE'], m.PROFILE if retained else m.ORIGIN_PROFILE)
                self.assertEqual(env['QEMU_FULL_USB_CONTROLLER'], 'off')
                self.assertEqual(env.get('QEMU_A7PF_RETAINED_STATE'), '1' if retained else None)
                self.assertFalse(any(k.startswith(m.USB_PREFIXES) for k in env))
                for bad in ('0', '-1', '2147483648', '3x', '３'):
                    with self.subTest(fd=bad), self.assertRaises(ValueError):
                        m.validate_environment(dict(env, QEMU_A7PF_FD=bad))
                with self.assertRaisesRegex(ValueError, 'overwritten'):
                    m.profile_environment(disk.fileno(), inherited=env)
            with self.assertRaises(ValueError):
                m.profile_environment(disk.fileno(), inherited={}, retained='1')

    def test_frozen_compile_preserves_usb_links_and_four_independent_units(self):
        text = m.frozen_ninja(BASELINE, Path('/independent/retained'))
        for obj in m.OBJECTS:
            self.assertIn(' ARGS = -Werror ', m.block(text, obj))
        link = m.block(text, 'qemu-system-aarch64')
        self.assertIn('hw_usb_sony-dwc3.c.o', link)
        self.assertIn('hw_usb_sony-dwc3-bridge.c.o', link)
        self.assertNotIn(str(BASELINE), text)
        self.assertNotIn('runtime/usb-build', text)
        with self.assertRaises(ValueError):
            m.block(text, 'unreviewed.o')

    def test_upstream_variant_changes_only_board_guard_and_declares_standard_usb(self):
        _, old = m.transformed(BASELINE / 'qemu-11.1.2')
        _, new = m.transformed(BASELINE / 'qemu-11.1.2', upstream_host=True)
        self.assertEqual({n for n in old if old[n] != new[n]}, {'hw/arm/virt.c'})
        self.assertIn(m.UPSTREAM_GUARD, new['hw/arm/virt.c'].decode())
        self.assertIn('.unmigratable = 1', (BASELINE / 'qemu-11.1.2/hw/usb/sony-dwc3.c').read_text())
        standard = (BASELINE / 'qemu-11.1.2/hw/usb/hcd-dwc3.c').read_text()
        self.assertIn('dc->vmsd = &vmstate_usb_dwc3', standard)
        self.assertTrue(m.UPSTREAM_TOPOLOGY['sony_usb_unmigratable_preserved'])
        with tempfile.TemporaryFile() as disk:
            env = m.profile_environment(disk.fileno(), inherited={}, retained=True, upstream_host=True)
            self.assertEqual(env['QEMU_A7PF_PROFILE'], m.UPSTREAM_PROFILE)
            for key, value in m.UPSTREAM_USB.items():
                self.assertEqual(env[key], value)
                for bad in ('', '0', 'sony-device', 'fullplatform'):
                    with self.subTest(key=key, bad=bad), self.assertRaises(ValueError):
                        m.validate_environment(dict(env, **{key: bad}))
                missing = dict(env)
                missing.pop(key)
                with self.assertRaises(ValueError):
                    m.validate_environment(missing)
            for key in ('QEMU_SONY_USB_DEVICE', 'QEMU_SONY_USB_BACKEND_SOCKET', 'QEMU_SONY_USB_RUN_ID',
                        'QEMU_SONY_USB_LEASE', 'QEMU_SONY_DWC3_CORE_TEST', 'QEMU_SONY_DWC3_BRIDGE'):
                for value in ('', '0', '1'):
                    with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                        m.validate_environment(dict(env, **{key: value}))
            for changed in ({'QEMU_A7PF_RETAINED_STATE': ''}, {'QEMU_A7PF_RETAINED_STATE': '0'},
                            {'QEMU_A7PF_PROFILE': m.PROFILE}, {'QEMU_A7PF_PROFILE': m.ORIGIN_PROFILE}):
                with self.assertRaises(ValueError):
                    m.validate_environment(dict(env, **changed))
            env.pop('QEMU_A7PF_RETAINED_STATE')
            with self.assertRaises(ValueError):
                m.validate_environment(env)

    def test_unsafe_output_and_unknown_template_refuse_before_copy(self):
        with self.assertRaisesRegex(ValueError, 'Separate scratch'):
            m.build(BASELINE, BASELINE / 'child')
        with tempfile.TemporaryDirectory() as root:
            with self.assertRaisesRegex(ValueError, 'Fresh stage'):
                m.build(BASELINE, Path(root))
        with tempfile.TemporaryDirectory() as root:
            with self.assertRaisesRegex(ValueError, 'Unknown production tree'):
                m.build(Path(root) / 'missing', Path(root) / 'new-stage')
            self.assertFalse((Path(root) / 'new-stage').exists())


@unittest.skipUnless(os.environ.get('RETAINED_PERSISTENT_STAGE'), 'Set RETAINED_PERSISTENT_STAGE for the new combined binary')
class CombinedQtest(unittest.TestCase):
    def test_binary_rejects_invalid_retained_and_legacy_usb_environment(self):
        stage = Path(os.environ['RETAINED_PERSISTENT_STAGE']).resolve(strict=True)
        receipt = json.loads((stage / 'manifest.json').read_text())
        binary = Path(receipt['binary'])
        self.assertEqual(m.digest(binary), receipt['qemu_binary_sha256'])
        upstream = receipt['profile'] == m.UPSTREAM_PROFILE
        profile = receipt['profile']
        results = []
        cases = [
                ({'QEMU_A7PF_RETAINED_STATE': '0'}, 'invalid retained-state flag/profile'),
                ({'QEMU_A7PF_RETAINED_STATE': 'true'}, 'invalid retained-state flag/profile'),
                ({'QEMU_A7PF_PROFILE': m.ORIGIN_PROFILE}, 'invalid retained-state flag/profile'),
                ({'QEMU_SONY_USB_DWC3': ''}, 'forbids every USB environment value'),
                ({'QEMU_SONY_DWC3_CORE_TEST': '0'}, 'forbids every USB environment value'),
                ({'QEMU_SONY_USB_DEVICE': '1'}, 'forbids every USB environment value')]
        if upstream:
            cases = [({'QEMU_A7PF_RETAINED_STATE': value}, 'invalid retained-state flag/profile')
                     for value in ('', '0', 'true')]
            cases += [({'QEMU_SONY_USB_DWC3': value}, 'forbids USB environment value') for value in ('', '0', '2')]
            cases += [({key: value}, 'forbids USB environment value')
                      for key in ('QEMU_SONY_USB_BACKEND_SOCKET', 'QEMU_SONY_USB_RUN_ID', 'QEMU_SONY_USB_LEASE',
                                  'QEMU_SONY_DWC3_BRIDGE', 'QEMU_SONY_DWC3_CORE_TEST') for value in ('', '0', '1')]
            cases += [({'QEMU_FULL_USB_CONTROLLER': 'off'}, 'requires upstream-host/full/original'),
                      ({'QEMU_FULL_USB_PLATFORM': 'off'}, 'requires upstream-host/full/original'),
                      ({'QEMU_FULL_USB_INIT': 'skipped'}, 'requires upstream-host/full/original'),
                      ({'QEMU_A7PF_PROFILE': m.PROFILE}, 'forbids USB environment value'),
                      ({'QEMU_A7PF_PROFILE': m.ORIGIN_PROFILE}, 'invalid retained-state flag/profile'),
                      ({'QEMU_A7PF_RETAINED_STATE': None}, 'invalid retained-state flag/profile')]
        for extra, error in cases:
            env = dict(PATH=os.defpath, LC_ALL='C', QEMU_A7PF_PROFILE=profile, QEMU_A7PF_RETAINED_STATE='1')
            if upstream:
                env.update(m.UPSTREAM_USB)
            env.update(extra)
            env = {k: v for k, v in env.items() if v is not None}
            command = ['bwrap', '--unshare-all', '--ro-bind', '/', '/', '--dev', '/dev',
                       '--proc', '/proc', '--tmpfs', '/tmp', str(binary), '-machine', 'virt',
                       '-accel', 'qtest', '-m', '64M', '-nodefaults', '-display', 'none', '-S']
            rejected = subprocess.run(command, env=env, capture_output=True)
            results.append(dict(extra=extra, returncode=rejected.returncode,
                                stdout_hex=rejected.stdout.hex(), stderr_hex=rejected.stderr.hex(), signals_sent=[]))
            self.assertEqual(rejected.returncode, 1, rejected.stderr)
            self.assertIn(error.encode(), rejected.stderr)
        evidence = Path(os.environ.get('RETAINED_PERSISTENT_EVIDENCE', str(stage / 'actual-combined-v1')))
        m.save_json(evidence.with_name(evidence.name + '-admission.json'), results)

    def test_current_combination_default_reject_and_explicit_roundtrip(self):
        stage = Path(os.environ['RETAINED_PERSISTENT_STAGE']).resolve(strict=True)
        receipt = json.loads((stage / 'manifest.json').read_text())
        binary = Path(receipt['binary'])
        self.assertTrue(receipt['compiled'])
        profile = receipt['profile']
        upstream = profile == m.UPSTREAM_PROFILE
        self.assertIn(profile, (m.PROFILE, m.UPSTREAM_PROFILE))
        self.assertEqual(m.digest(binary), receipt['qemu_binary_sha256'])
        self.assertNotEqual(receipt['qemu_binary_sha256'], m.PRODUCTION_SHA)
        for name, info in receipt['files'].items():
            self.assertEqual(m.digest(stage / 'qemu-11.1.2' / name), info['new'])
        helper_path = HERE / 'persistent-flash/flash-migration-qtest.py'
        test_path = HERE / 'persistent-flash/test-flash-migration.py'
        m.exact(helper_path, '309aa8bdcc5c650efd3295ceba75c0a16d847d85706a32466198a5a327d48e06')
        m.exact(test_path, '5ce76e59bc2fac3885b839b25f1a2db6c87b7bae1f19d297bf60262b518cc9ae')
        # Shared owner/QMP transport and synthetic format, no fixture board build.
        helper = runpy.run_path(str(helper_path))
        fixture = runpy.run_path(str(test_path))
        Base = helper['Qemu']
        out = Path(os.environ.get('RETAINED_PERSISTENT_EVIDENCE', str(stage / 'actual-combined-v1'))).absolute()
        out.mkdir(mode=0o700)
        disk, geometry, _ = fixture['synthetic'](out / 'synthetic')
        fd = os.open(disk, os.O_RDWR)
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        owners = []
        results = dict(profile=profile, qemu_binary_sha256=m.digest(binary),
                       synthetic_disk=True, original_ap_restore_verified=False,
                       physical_wbi_verified=False, external_transaction_implemented=False)

        class Qemu(Base):
            def __init__(self, label, *, retained, incoming=False):
                self.out, self.label, self.events, self.transcript = out, label, [], []
                self.temp = tempfile.TemporaryDirectory(prefix='a7rp-')
                short = Path(self.temp.name)
                self.log = (out / (label + '.log')).open('x')
                self.qmp = self.qmpfile = self.socket = self.file = None
                self.env = m.profile_environment(fd, retained=retained, upstream_host=upstream and retained)
                self.keys = short / 'keys'
                command = ['bwrap', '--unshare-all', '--tmpfs', '/']
                for path in ('/usr', '/lib', '/lib64', '/bin', '/etc', str(stage)):
                    command += ['--ro-bind', path, path]
                command += ['--dev', '/dev', '--proc', '/proc', '--tmpfs', '/tmp', '--bind', str(out), str(out),
                            '--bind', str(short), str(short),
                            '--ro-bind', str(geometry), '/instance/persistent-geometry.bin', '--clearenv']
                for key, value in self.env.items():
                    command += ['--setenv', key, value]
                command += [str(binary), '-machine', 'virt,secure=off,gic-version=2', '-cpu', 'cortex-a53',
                            '-accel', 'qtest', '-m', '64M', '-nodefaults', '-display', 'none',
                            '-nic', 'none', '-serial', 'none', '-monitor', 'none', '-S',
                            '-qtest', 'unix:' + str(short / 'test') + ',server=on,wait=off',
                            '-qmp', 'unix:' + str(short / 'qmp') + ',server=on,wait=off',
                            '-device', 'ramfb,id=screen',
                            '-chardev', 'socket,id=keys,path=' + str(self.keys) + ',server=on,wait=off',
                            '-device', 'sony-ui-input,id=keysbridge,chardev=keys,display=screen']
                if incoming:
                    command += ['-incoming', 'defer']
                self.process = subprocess.Popen(command, pass_fds=(fd,), stdout=self.log, stderr=subprocess.STDOUT,
                                                env={'PATH': os.defpath, 'LC_ALL': 'C'})
                st = os.fstat(fd)
                self.owner = dict(pid=self.process.pid, command=command, environment=self.env, signals_sent=[],
                                  fd_identity=dict(dev=st.st_dev, ino=st.st_ino, bytes=st.st_size),
                                  geometry_sha256=m.digest(geometry), usb_ever_connected=False)
                m.save_json(out / (label + '-owner.json'), self.owner)
                try:
                    self.qmp = self.connect(short / 'qmp')
                    self.qmpfile = self.qmp.makefile('rwb', buffering=0)
                    assert 'QMP' in json.loads(self.qmpfile.readline())
                    self.qmpcommand('qmp_capabilities')
                    self.socket = self.connect(short / 'test')
                    self.file = self.socket.makefile('rb')
                except BaseException:
                    if self.process.poll() is None and self.qmpfile is not None:
                        self.qmpcommand('quit')
                    if self.process.poll() is None:
                        # Preserve owner/socket for recovery, never signal a VM.
                        self.temp._finalizer.detach()
                    else:
                        self.owner['returncode'] = self.process.returncode
                        m.save_json(out / (label + '-owner.json'), self.owner)
                    raise

            def cmd(self, command):
                # Raw unbuffered file.write may accept only part of a full SPAcc command.
                self.socket.sendall((command + '\n').encode())
                while True:
                    response = self.file.readline().decode().strip()
                    if response.startswith('IRQ '):
                        continue
                    assert response.startswith('OK'), (command, response)
                    self.transcript.append(dict(qtest=command, response=response))
                    return response[2:].strip()

            def qom_inventory(self):
                inventory = []

                def visit(path):
                    for child in self.qmpcommand('qom-list', {'path': path}):
                        if child['type'].startswith('child<'):
                            full = path.rstrip('/') + '/' + child['name']
                            inventory.append(dict(path=full, type=child['type']))
                            visit(full)
                visit('/machine')
                return inventory

        source = target = default = None
        try:
            default = Qemu('default', retained=False)
            inventory = default.qom_inventory()
            self.assertFalse(any('usb' in i['type'].lower() or 'dwc3' in i['type'].lower() for i in inventory))
            flash = next(i['path'] for i in inventory if i['type'] == 'child<sony-persistent-flash>')
            self.assertFalse(default.qmpcommand('qom-get', dict(path=flash, property='retained-state')))
            fixture['prepare'](default, 'failed')
            expected = fixture['registers'](default)
            default.qmpcommand('cont')
            rejected = fixture['save'](default, out / 'default-refused.bin', success=False)
            self.assertTrue(default.qmpcommand('query-status')['running'])
            self.assertEqual(fixture['registers'](default), expected)
            results['default'] = dict(migration=rejected, retained_state=False, registers_unchanged=True,
                                      qom_inventory=inventory)
            owners.append(default.close())
            default = None
            source = Qemu('source', retained=True)
            target = Qemu('target', retained=True, incoming=True)
            for vm in (source, target):
                inventory = vm.qom_inventory()
                self.assertEqual(any(i['type'] == 'child<usb_dwc3>' for i in inventory), upstream)
                self.assertFalse(any('sony-dwc3' in i['type'].lower() for i in inventory))
                if not upstream:
                    self.assertFalse(any('usb' in i['type'].lower() or 'dwc3' in i['type'].lower() for i in inventory))
                self.assertEqual(sum(i['type'] == 'child<sony-hwtimer>' for i in inventory), 4)
                self.assertTrue(any('sony-spacc' in i['type'] for i in inventory))
                self.assertTrue(any('sony-ui-input' in i['type'] for i in inventory))
                flash = next(i['path'] for i in inventory if i['type'] == 'child<sony-persistent-flash>')
                self.assertTrue(vm.qmpcommand('qom-get', dict(path=flash, property='retained-state')))
                m.save_json(out / (vm.label + '-qom.json'), inventory)
                mtree = vm.qmpcommand('human-monitor-command', {'command-line': 'info mtree'})
                self.assertNotIn('sony-usb-', mtree)
                self.assertEqual('dwc3' in mtree.lower(), upstream)
                self.assertIn('sony-media-detect', mtree)
                self.assertIn('sony-mmc-trace', mtree)
                (out / (vm.label + '-mtree.txt')).write_text(mtree)
            upstream_regs = {}
            if upstream:
                for address, value, mask in ((0xf10cc100, 0x00a5000f, 0xffff0cff),
                                             (0xf10cc104, 0x1200, 0x1f00)):
                    before = int(source.cmd(f'readl {address:#x}'), 0)
                    source.cmd(f'writel {address:#x} {value:#x}')
                    actual = int(source.cmd(f'readl {address:#x}'), 0)
                    self.assertEqual(actual, (before & ~mask) | (value & mask))
                    self.assertNotEqual(actual, before)
                    self.assertNotEqual(actual, 0xffffffff)
                    upstream_regs[address] = actual
            payload, canary = fixture['prepare'](source, 'done')
            expected = fixture['registers'](source)
            timer, spacc, media, mmc = 0xf1042000, 0xf7fc0000, 0xf1388f44, 0xf1388000
            source.cmd(f'writel {timer + 16:#x} 37')
            source.cmd(f'writel {timer + 8:#x} 4037')
            source.cmd(f'writel {timer:#x} 0x1110')
            spacc_data = bytes(range(256)) * 1024
            source.memory(spacc, len(spacc_data), spacc_data)
            expected_spacc = source.memory(spacc, len(spacc_data))
            source.cmd(f'readl {media:#x}')
            source.cmd(f'readl {mmc:#x}')
            key = lambda vm, down: vm.qmpcommand('input-send-event', {'device': 'screen', 'events': [
                {'type': 'key', 'data': {'down': down, 'key': {'type': 'qcode', 'data': 'esc'}}}]})
            peer = source.connect(source.keys)
            source.qmpcommand('cont')
            key(source, True)
            self.assertEqual(peer.recv(1), b'M')
            source.qmpcommand('stop')
            peer.close()
            deadline = time.monotonic() + 5
            while source.qmpcommand('qom-get', dict(path='/machine/peripheral/keysbridge', property='input-connected')):
                self.assertLess(time.monotonic(), deadline)
                time.sleep(.01)
            disk_before = m.digest(disk)
            state = out / 'combined-state.bin'
            results['source_migration'] = fixture['save'](source, state)
            self.assertIn(bytes.fromhex(disk_before), state.read_bytes())
            target.qmpcommand('migrate-incoming', dict(uri='exec:cat ' + shlex.quote(str(state))))
            deadline = time.monotonic() + 30
            while target.qmpcommand('query-status')['status'] == 'inmigrate':
                self.assertLess(time.monotonic(), deadline)
                time.sleep(.02)
            self.assertFalse(target.qmpcommand('query-status')['running'])
            for address, value in upstream_regs.items():
                self.assertEqual(int(target.cmd(f'readl {address:#x}'), 0), value)
            self.assertEqual(fixture['registers'](target), expected)
            self.assertEqual(target.memory(0x40001000, len(payload)), payload)
            self.assertEqual(target.memory(0x40002000, len(canary)), canary)
            self.assertEqual(target.memory(spacc, len(expected_spacc)), expected_spacc)
            self.assertEqual(int(target.cmd(f'readl {timer:#x}'), 0), 0x1110)
            self.assertEqual(int(target.cmd(f'readl {timer + 12:#x}'), 0), 37)
            self.assertEqual(int(target.cmd(f'readl {timer + 8:#x}'), 0), 4037)
            self.assertEqual(int(target.cmd(f'readl {media:#x}'), 0), 0x12345678)
            self.assertEqual(int(target.cmd(f'readl {mmc:#x}'), 0), 0x89abcdef)
            peer = target.connect(target.keys)
            try:
                target.qmpcommand('cont')
                key(target, True)
                peer.settimeout(.1)
                with self.assertRaises(TimeoutError):
                    peer.recv(1)
                key(target, False)
                key(target, True)
                peer.settimeout(5)
                self.assertEqual(peer.recv(1), b'M')
                key(target, False)
                target.qmpcommand('stop')
            finally:
                peer.close()
            self.assertEqual(m.digest(disk), disk_before)
            self.assertTrue(fixture['held'](fd, disk))
            results.update(actual_combined_roundtrip_verified=True, exact_flash_registers=expected,
                           dma_ram_and_canary_exact=True, full_spacc_bytes=len(expected_spacc),
                           timer_count_compare_control_exact=True, input_held_release_consumed=True,
                           usb_qdev_absent=not upstream, usb_fields_saved_or_restored=False,
                           upstream_usb_registers_exact=upstream, upstream_usb_registers=upstream_regs,
                           sony_usb_qdev_and_provider_absent=True,
                           physical_host_usb_devices=False, host_attach_verified=False, guest_gadget_verified=False,
                           disk_sha256=disk_before, geometry_sha256=m.digest(geometry), state_sha256=m.digest(state))
        finally:
            for vm in (default, source, target):
                if vm is not None:
                    owners.append(vm.close())
            results['owners'] = owners
            self.assertTrue(fixture['held'](fd, disk))
            results['synthetic_parent_flock_held_through_exits'] = True
            os.close(fd)
            m.save_json(out / 'result.json', results)
        self.assertEqual(len(owners), 3)
        for owner in owners:
            self.assertEqual(owner['returncode'], 0)
            self.assertIn('quit_response', owner)
            self.assertEqual(owner['signals_sent'], [])
        for label in ('source', 'target'):
            log = (out / (label + '.log')).read_text()
            self.assertNotIn('SONY_USB', log)
            self.assertIn('SONY_MEDIA_DETECT_CREATED', log)
        self.assertIn('SONY_MEDIA_DETECT_READ count=2', (out / 'target.log').read_text())
        self.assertIn('SONY_MMC_TRACE_READ base=0xf1388000 n=2 ', (out / 'target.log').read_text())
        receipt['actual_combined_roundtrip_verified'] = True
        if upstream:
            receipt['upstream_usb_actual_roundtrip_verified'] = True
        receipt['actual_evidence'] = dict(result=str(out / 'result.json'), sha256=m.digest(out / 'result.json'),
                                        test_sha256=m.digest(Path(__file__)), scope='64MiB qtest; synthetic disk; no AP/kernel')
        m.save_json(stage / 'manifest.json', receipt)


if __name__ == '__main__':
    unittest.main()
