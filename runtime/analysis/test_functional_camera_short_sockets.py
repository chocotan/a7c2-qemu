"""Synthetic functional-camera F/S wiring only; no QEMU, model or capture run."""
from contextlib import contextmanager
import copy
import os
from pathlib import Path
import stat
import struct
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

import functional_camera_broker as broker
import functional_camera_runner as runner


class SyntheticRoots:
    def __init__(self, files, sockets):
        self.files, self.sockets = files, sockets
        self.generation = 1
        self.connections = []

    def binding(self):
        return dict(profile=broker.diagnostic_fs.DIAGNOSTIC_FS_PROFILE,
                    files=str(self.files), sockets=str(self.sockets),
                    directories={str(self.sockets): dict(ino=self.generation)})

    def endpoint(self, path):
        if path.parent != self.sockets:
            raise ValueError('foreign endpoint')

    @contextmanager
    def connect_path(self, path):
        self.endpoint(path)
        self.connections.append(path)
        yield 'synthetic-fd/' + path.name


class FunctionalShortSocketTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='functional-short-consumer-')
        self.addCleanup(self.tmp.cleanup)
        self.run = Path(self.tmp.name) / 'menu-runs/run'
        self.run.mkdir(parents=True, mode=0o700)
        self.sockets = Path(self.tmp.name) / 'sockets'
        self.sockets.mkdir(mode=0o700)
        self.roots = SyntheticRoots(self.run, self.sockets)
        self.options = dict(socket_root=str(self.sockets),
                            socket_profile=broker.diagnostic_fs.DIAGNOSTIC_FS_PROFILE,
                            socket_binding=self.roots.binding())
        self.artifact = dict(library='/synthetic/model.so', library_sha256='1' * 64,
                             qemu_sha256=runner.QEMU_SHA256)
        (self.run / 'console.log').write_bytes(b'')

    @contextmanager
    def synthetic_contract(self):
        # Fixture replacements exercise consumers without granting runtime admission.
        with mock.patch.object(broker.diagnostic_fs, 'require_runtime_ready'), \
                mock.patch.object(broker.diagnostic_fs, 'DiagnosticRoots', return_value=self.roots), \
                mock.patch.object(broker.single_ap_sockets, 'read_binding', return_value=self.options['socket_binding']):
            yield

    @contextmanager
    def synthetic_socket_mode(self):
        original=stat.S_ISSOCK
        with mock.patch.object(broker.stat,'S_ISSOCK',side_effect=lambda mode:stat.S_ISREG(mode) or original(mode)):
            yield

    def instance(self):
        with self.synthetic_contract(), mock.patch.object(broker, 'RUNS', self.run.parent):
            return runner.FunctionalCameraRunner(self.run, self.artifact, **self.options)

    def test_legacy_has_no_new_route_or_options(self):
        self.assertIsNone(broker.endpoint_roots(self.run))
        self.assertEqual(broker.endpoint_options(None), {})

    def test_partial_contract_and_wrong_profile_are_refused(self):
        keys = tuple(self.options)
        for mask in range(1, 7):
            options = {key: self.options[key] for bit, key in enumerate(keys) if mask & (1 << bit)}
            with self.subTest(mask=mask), self.assertRaisesRegex(ValueError, 'complete explicit F/S'):
                broker.endpoint_roots(self.run, **options)
        with self.assertRaisesRegex(ValueError, 'complete explicit F/S'):
            broker.endpoint_roots(self.run, **dict(self.options, socket_profile='auto'))

    def test_existing_single_ap_binding_cannot_fall_back_to_legacy(self):
        binding = self.run / 'single-ap-socket-binding.json'
        binding.write_text('{}')
        with self.assertRaisesRegex(ValueError, 'explicit F/S parameters'):
            broker.endpoint_roots(self.run)
        binding.unlink()
        binding.symlink_to(self.run / 'missing')
        with self.assertRaisesRegex(ValueError, 'explicit F/S parameters'):
            broker.endpoint_roots(self.run)

    def test_real_gate_stays_closed_before_artifact_or_endpoint_access(self):
        with mock.patch.object(runner, 'validate_artifact') as artifact, \
                mock.patch.object(broker, 'Core') as core, \
                mock.patch.object(broker, 'connect_unix') as connect, \
                mock.patch.object(broker.diagnostic_fs, 'DiagnosticRoots') as roots:
            with self.assertRaisesRegex(RuntimeError, 'BLOCKED:'):
                runner.prepare(runner.FUNCTIONAL_CAMERA_PROFILE, '/unused', self.run, '/unused', **self.options)
            artifact.assert_not_called()
            core.assert_not_called()
            connect.assert_not_called()
            roots.assert_not_called()

    def test_new_route_requires_functional_profile_too(self):
        with self.assertRaisesRegex(ValueError, 'explicit functional profile'):
            runner.prepare('', '/unused', self.run, '/unused', **self.options)

    def test_prepare_forwards_explicit_contract_and_scope_receipt(self):
        with self.synthetic_contract(), \
                mock.patch.object(runner, 'validate_artifact', return_value=self.artifact) as artifact, \
                mock.patch.object(runner, 'FunctionalCameraRunner') as factory:
            result = runner.prepare(runner.FUNCTIONAL_CAMERA_PROFILE, '/base', self.run, '/qemu',
                                    scope_build_receipt='/scope', **self.options)
        artifact.assert_called_once_with('/base', '/qemu', scope_build_receipt='/scope')
        factory.assert_called_once_with(self.run, self.artifact, **self.options)
        self.assertIs(result, factory.return_value)

    def test_directory_binding_changes_are_refused(self):
        with self.synthetic_contract():
            self.assertIs(broker.endpoint_roots(self.run, **self.options), self.roots)
            self.roots.generation += 1
            with self.assertRaisesRegex(ValueError, 'binding differs'):
                broker.endpoint_roots(self.run, **self.options)
            with mock.patch.object(broker, 'RUNS', self.run.parent), \
                    mock.patch.object(runner.Path, 'iterdir') as processes:
                with self.assertRaisesRegex(ValueError, 'binding differs'):
                    runner.debugger_handoff(self.run, os.getpid(), **self.options)
                processes.assert_not_called()

    def test_explicit_contract_cannot_override_producer_receipt(self):
        with self.synthetic_contract(), \
                mock.patch.object(broker.single_ap_sockets, 'read_binding', return_value={}):
            with self.assertRaisesRegex(ValueError, 'producer receipt'):
                broker.endpoint_roots(self.run, **self.options)

    def test_watch_forwards_roots_without_changing_coordination_or_claims(self):
        instance = self.instance()
        mailbox = dict(phys0=0x410000000, nonce=123, pid=123,
                       pages=[0x410000000 + 4096 * index for index in range(16)])
        line = ('OBS FUNCTIONAL_CAMERA_MAILBOX phys0=%#x nonce=%#x pid=%d ABI=%s version=1 pages=%s\n' %
                (mailbox['phys0'], mailbox['nonce'], mailbox['pid'], runner.FUNCTIONAL_CAMERA_PROFILE,
                 ','.join(hex(page) for page in mailbox['pages']))).encode()
        (self.run / 'console.log').write_bytes(line)
        instance.proc = mock.Mock()
        instance.proc.poll.return_value = None
        attached = mock.Mock(start_error=None)
        handoff = dict(qemu_pid=456, debugger_quiesced=True)

        def start(*args, **options):
            self.assertEqual(args[2], mailbox)
            self.assertIs(options['coordination_lock'], instance.coordination_lock)
            self.assertTrue(options['debugger_quiesced'])
            self.assertTrue(options['resume_allowed']())
            self.assertEqual(options['gdb_socket'], self.sockets / runner.GDB)
            self.assertEqual(options['qmp_socket'], self.sockets / runner.QMP)
            for key, value in self.options.items():
                self.assertEqual(options[key], value)
            instance.done.set()
            return attached

        with mock.patch.object(broker, 'RUNS', self.run.parent), \
                mock.patch.object(runner, 'debugger_handoff', return_value=handoff) as observe, \
                mock.patch.object(broker, 'start', side_effect=start):
            instance._watch()
        observe.assert_called_once_with(self.run, os.getpid(), **self.options)
        self.assertIs(instance.broker, attached)
        self.assertIsNone(instance.error)
        receipt = instance.receipt('attached')
        self.assertEqual(receipt['socket_binding'], self.options['socket_binding'])
        for key in ('capture_verified', 'physical_ASIC_compatibility_verified', 'original_CP_RAM_verified'):
            self.assertIs(receipt[key], False)

    def test_before_close_requires_the_same_fs_contract_in_broker_receipts(self):
        for changed in (False, True):
            with self.subTest(changed=changed):
                instance = self.instance()
                instance.binding = dict(mailbox=dict(nonce=123))
                instance.handoff = dict(qemu_identity=dict(pid=456, starttime=10))
                cleanup = {**dict.fromkeys(runner.CLOSE_FIELDS, True), 'errors': []}
                instance.broker = mock.Mock()
                instance.broker.stop.return_value = cleanup
                config = dict(owner=instance.owner, qemu=instance.handoff['qemu_identity'], **self.options)
                if changed:
                    config = dict(config, socket_binding={})
                events = [dict(kind='binding', mailbox=instance.binding['mailbox'], config=config),
                          dict(kind='detach_commit', model_work_stopped=True, no_further_ram_after_ack=True),
                          dict(kind='mailbox_detached', cleanup_detach=True, protocol_physmode_restored=True),
                          dict(kind='debugger_disconnected', detached=True, protocol_physmode_restored=True),
                          dict(kind='cleanup', **cleanup)]
                events = [dict(event, event=index, model_instance=123) for index, event in enumerate(events, 1)]
                with mock.patch.object(broker, 'RUNS', self.run.parent), \
                        mock.patch.object(broker, 'read_receipts', return_value=events):
                    if changed:
                        with self.assertRaisesRegex(runner.UnsafeCameraClose, 'binding/sequence differs'):
                            instance.before_close('test-close')
                        self.assertFalse(instance.closed)
                        self.assertFalse(instance.cleanup['safe_to_close'])
                    else:
                        result = instance.before_close('test-close')
                        self.assertTrue(instance.closed)
                        self.assertFalse(result['capture_verified'])
                instance.broker.stop.assert_called_once_with()

    def test_short_connection_requires_fixed_gate_and_uses_pinned_path(self):
        stream = mock.Mock()
        path = self.sockets / runner.QMP
        with self.assertRaisesRegex(RuntimeError, 'BLOCKED:'):
            broker.connect_unix(stream, path, socket_roots=self.roots)
        stream.connect.assert_not_called()
        with self.synthetic_contract():
            broker.connect_unix(stream, path, socket_roots=self.roots)
        stream.connect.assert_called_once_with('synthetic-fd/' + runner.QMP)
        self.assertEqual(self.roots.connections, [path])

    def test_short_rsp_and_qmp_keep_peer_process_validation(self):
        for protocol in (broker.RSP, broker.QMP):
            with self.subTest(protocol=protocol.__name__):
                peer = mock.Mock()
                peer.getsockopt.return_value = struct.pack('3i', os.getpid() + 1, os.getuid(), os.getgid())
                with self.synthetic_contract(), mock.patch.object(broker.socket, 'socket', return_value=peer):
                    with self.assertRaisesRegex(ValueError, 'peer process differs'):
                        protocol(self.sockets / 'debug.sock', expected_pid=os.getpid(), socket_roots=self.roots)
                peer.connect.assert_called_once_with('synthetic-fd/debug.sock')
                peer.sendall.assert_not_called()
                peer.close.assert_called_once_with()

    def test_owned_config_keeps_original_qemu_digest_and_start_generation(self):
        owner = dict(pid=os.getpid() + 1, starttime=10, ppid=1, exe='/synthetic/owner')
        qemu = dict(pid=os.getpid(), starttime=20, ppid=owner['pid'], exe='/synthetic/qemu-system-aarch64')
        identities = {owner['pid']: owner, qemu['pid']: qemu}
        endpoints = [dict(path=str(self.sockets / runner.GDB), inode=1),
                     dict(path=str(self.sockets / runner.QMP), inode=2)]
        with self.synthetic_contract(), mock.patch.object(broker, 'RUNS', self.run.parent), \
                mock.patch.object(broker, 'process_identity', side_effect=identities.__getitem__), \
                mock.patch.object(broker, 'file_digest_fd', return_value=(runner.QEMU_SHA256, (1, 2, 3, 4, 5))), \
                mock.patch.object(broker, 'checked_socket', side_effect=endpoints) as endpoint:
            config = broker.owned_config(self.run, owner['pid'], qemu['pid'], runner.QEMU_SHA256,
                                        self.sockets / runner.GDB, self.sockets / runner.QMP, **self.options)
            self.assertEqual(config['owner'], owner)
            self.assertEqual(config['qemu'], qemu)
            self.assertEqual(config['qemu_sha256'], runner.QEMU_SHA256)
            self.assertEqual(config['socket_binding'], self.options['socket_binding'])
            self.assertTrue(all(call.kwargs == dict(socket_roots=self.roots) for call in endpoint.call_args_list))
            endpoint.reset_mock()
            with self.assertRaisesRegex(ValueError, 'SHA256 differs'):
                broker.owned_config(self.run, owner['pid'], qemu['pid'], '0' * 64,
                                    self.sockets / runner.GDB, self.sockets / runner.QMP, **self.options)
            endpoint.assert_not_called()

    def test_short_listener_requires_qemu_fd_same_mount_and_no_client(self):
        path = self.sockets / runner.GDB
        path.touch(mode=0o600)
        os.chmod(path, 0o600)
        rows = ['header\n0: 00000002 00000000 00010000 0001 01 777 /sockets/' + path.name + '\n']
        mounted = [self.sockets]
        fd_path = Path('/synthetic/qemu-fd')
        proc_root, proc = mock.MagicMock(), mock.MagicMock()
        proc_root.__truediv__.return_value = proc
        proc.__truediv__.side_effect = lambda name: {
            'net/unix': SimpleNamespace(read_text=lambda: rows[0]),
            'fd': SimpleNamespace(iterdir=lambda: [fd_path]),
            'root/sockets': SimpleNamespace(stat=lambda: mounted[0].stat()),
        }[name]
        path_lookup = lambda value: proc_root if value == '/proc' else Path(value)
        real_readlink = os.readlink
        link = ['socket:[777]']
        def readlink(value, *args, **kwargs):
            return link[0] if value == fd_path else real_readlink(value, *args, **kwargs)
        with self.synthetic_contract(), self.synthetic_socket_mode(), mock.patch.object(broker, 'Path', side_effect=path_lookup), \
                mock.patch.object(broker.os, 'readlink', side_effect=readlink):
            result = broker.checked_socket(self.run, path, 456, socket_roots=self.roots)
            self.assertEqual(result['listener_inode'], 777)
            self.assertEqual(result['inode'], path.lstat().st_ino)
            self.assertEqual(stat.S_IMODE(path.lstat().st_mode), 0o600)
            rows[0] += '1: 00000002 00000000 00000000 0001 03 778 /sockets/' + path.name + '\n'
            with self.assertRaisesRegex(ValueError, 'connected client'):
                broker.checked_socket(self.run, path, 456, socket_roots=self.roots)
            rows[0] = rows[0].split('1: ')[0]
            link[0] = 'socket:[888]'
            with self.assertRaisesRegex(ValueError, 'does not own'):
                broker.checked_socket(self.run, path, 456, socket_roots=self.roots)
            link[0] = 'socket:[777]'
            mounted[0] = self.run
            with self.assertRaisesRegex(ValueError, 'different directory'):
                broker.checked_socket(self.run, path, 456, socket_roots=self.roots)
            with self.assertRaisesRegex(ValueError, 'endpoint-root child'):
                broker.checked_socket(self.run, self.run / runner.GDB, 456, socket_roots=self.roots)

    def test_revalidate_rejects_new_directory_process_or_endpoint_generation(self):
        identity = broker.process_identity(os.getpid())
        executable = Path('/proc') / str(os.getpid()) / 'exe'
        st = executable.stat()
        config = dict(run=str(self.run), run_identity=(self.run.stat().st_dev, self.run.stat().st_ino),
                      owner=identity, qemu=identity,
                      exe_identity=(st.st_dev, st.st_ino, st.st_size, st.st_mtime_ns, st.st_ctime_ns), **self.options)
        for key, name in (('gdb', runner.GDB), ('qmp', runner.QMP)):
            path = self.sockets / name
            path.touch(mode=0o600)
            os.chmod(path, 0o600)
            st = path.lstat()
            config[key] = dict(path=str(path), device=st.st_dev, inode=st.st_ino)
        with self.synthetic_contract(), self.synthetic_socket_mode(), mock.patch.object(broker, 'RUNS', self.run.parent):
            self.assertEqual(broker.revalidate(config), self.run)
            changed = copy.deepcopy(config)
            changed['qemu']['starttime'] += 1
            with self.assertRaisesRegex(ValueError, 'process identity changed'):
                broker.revalidate(changed)
            changed = copy.deepcopy(config)
            changed['gdb']['inode'] += 1
            with self.assertRaisesRegex(ValueError, 'socket replaced'):
                broker.revalidate(changed)
            self.roots.generation += 1
            with self.assertRaisesRegex(ValueError, 'binding differs'):
                broker.revalidate(config)


if __name__ == '__main__':
    unittest.main()
