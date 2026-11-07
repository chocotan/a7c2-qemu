"""Host protocol tests only: fake QMP streams do not prove a QEMU round trip."""
import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import socket
import tempfile
import threading
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('retained_boot', Path(__file__).with_name('retained-boot.py'))
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
STREAM = b'QEVM\x00\x00\x00\x03' + b'CPU RAM devices mock payload'


def identity():
    return dict(run='capture-run', generation=0, profile='ram-hotboot', source_class='private-device-dump',
                machine={'type': 'virt-11.1', 'ram_bytes': 1024, 'cpus': 1, 'cpu': 'cortex-a35'},
                qemu={'version': '11.1.2', 'sha256': '1' * 64},
                resources={**{k: hashlib.sha256(k.encode()).hexdigest() for k in ('kernel', 'dtb', 'ram0', 'ap', 'cp', 'manifest')},
                           'partitions': {'nflasha7': '2' * 64, 'nflasha15': '3' * 64}},
                device_migration={'complete': True, 'audit_sha256': '4' * 64,
                                  'devices': ['cpu', 'ram', 'gic', 'pl011'], 'external_state': 'none', 'blockers': []})


class FakeQMP:
    def __init__(self, *, incoming=False, fail=False, payload=STREAM, eof=True, never_complete=False):
        self.state = 'inmigrate' if incoming else 'running'
        self.migration = 'none'
        self.commands, self.fds = [], {}
        self.fail, self.payload, self.eof, self.never_complete = fail, payload, eof, never_complete
        self.version, self.blocks, self.caps = '11.1.2', [], []
        self.received = b''
        self.stop_works = True

    def getfd(self, name, fd):
        self.commands.append(('getfd', {'fdname': name}))
        self.fds[name] = socket.socket(fileno=os.dup(fd))

    def __call__(self, name, arguments=None):
        self.commands.append((name, copy.deepcopy(arguments)))
        if name == 'query-version':
            a, b, c = map(int, self.version.split('.'))
            return {'qemu': dict(major=a, minor=b, micro=c)}
        if name == 'query-block':
            return self.blocks
        if name == 'query-migrate-capabilities':
            return self.caps
        if name == 'query-status':
            return {'status': self.state, 'running': self.state == 'running'}
        if name == 'query-migrate':
            return {'status': self.migration, 'error-desc': 'test error' if self.fail else ''}
        if name == 'stop':
            if self.stop_works:
                self.state = 'paused'
        elif name == 'migrate':
            self.assert_uri(arguments, 'retained-output')
            connection = self.fds['retained-output']
            connection.sendall(self.payload)
            if self.eof:
                connection.close()
            self.migration = 'failed' if self.fail else 'active' if self.never_complete else 'completed'
            self.state = 'postmigrate'
        elif name == 'migrate-incoming':
            self.assert_uri(arguments, 'retained-input')
            connection = self.fds['retained-input']
            while data := connection.recv(4096):
                self.received += data
            connection.close()
            self.migration = 'failed' if self.fail else 'completed'
            self.state = 'paused'
        elif name == 'migrate_cancel':
            self.migration = 'cancelled'
            for connection in self.fds.values():
                connection.close()
        elif name == 'cont':
            self.state = 'running'
        else:
            raise AssertionError('Unexpected command: ' + name)
        return {}

    def assert_uri(self, arguments, fdname):
        if arguments['uri'] != 'fd:' + fdname:
            raise AssertionError('Only bound fd migration is allowed')

    def close(self):
        for connection in self.fds.values():
            connection.close()


class SnapshotTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.bound = identity()

    def qmp(self, **kwargs):
        result = FakeQMP(**kwargs)
        self.addCleanup(result.close)
        return result

    def snapshot(self, **kwargs):
        output = self.root / 'snapshot'
        qmp = self.qmp(**kwargs)
        receipt = m.bind_snapshot(self.bound, qmp, output, timeout=.3)
        return output, receipt, qmp

    def next_identity(self):
        bound = copy.deepcopy(self.bound)
        bound.update(run='restore-run', generation=1)
        return bound

    def test_known_sony_build_refused_before_qmp_or_output(self):
        self.bound['qemu']['sha256'] = m.SOURCE_REVIEW['program_sha256']
        qmp = self.qmp()
        with self.assertRaises(m.Unsupported) as error:
            m.bind_snapshot(self.bound, qmp, self.root / 'blocked')
        self.assertFalse((self.root / 'blocked').exists())
        self.assertEqual(qmp.commands, [])
        receipt = error.exception.receipt
        self.assertFalse(receipt['verified'])
        self.assertFalse(receipt['source_review']['actual_snapshot_roundtrip_verified'])
        self.assertTrue(any('unregistered' in b for b in receipt['blockers']))

    def test_unreviewed_device_or_external_state_cannot_be_overridden(self):
        for field, value in [('complete', False), ('external_state', 'host-service'), ('devices', []),
                             ('audit_sha256', 'bad'), ('blockers', ['missing timer'])]:
            with self.subTest(field=field):
                bound = copy.deepcopy(self.bound); bound['device_migration'][field] = value
                with self.assertRaises(m.Unsupported):
                    m.bind_snapshot(bound, self.qmp(), self.root / field)

    def test_sony_wbi_and_missing_fd_transport_refused(self):
        self.bound['profile'] = 'wbi-resume'
        with self.assertRaises(m.Unsupported) as error:
            m.bind_snapshot(self.bound, self.qmp(), self.root / 'wbi')
        self.assertIn('not Sony WBI', str(error.exception))
        self.bound['profile'] = 'ram-hotboot'
        with self.assertRaises(m.Unsupported):
            m.bind_snapshot(self.bound, lambda *a: {}, self.root / 'no-fds')

    def test_capture_requires_completed_and_eof_then_publishes_hash(self):
        output, receipt, qmp = self.snapshot()
        self.assertTrue(receipt['verified'])
        self.assertEqual(receipt['snapshot_sha256'], hashlib.sha256(STREAM).hexdigest())
        self.assertEqual((output / 'snapshot.bin').read_bytes(), STREAM)
        self.assertEqual(json.loads((output / 'receipt.json').read_text()), receipt)
        self.assertFalse((output / 'snapshot.partial').exists())
        names = [name for name, _ in qmp.commands]
        self.assertLess(names.index('stop'), names.index('migrate'))
        self.assertNotIn('cont', names)
        self.assertFalse(receipt['physical_hotboot_verified'])
        self.assertFalse(receipt['sony_wbi_resume_verified'])
        self.assertFalse(receipt['whole_machine_verified'])

    def test_failed_partial_incomplete_header_and_missing_eof_do_not_publish(self):
        cases = [dict(fail=True), dict(payload=b'QEVM'), dict(eof=False), dict(never_complete=True)]
        for index, kwargs in enumerate(cases):
            with self.subTest(kwargs=kwargs):
                output = self.root / str(index)
                qmp = self.qmp(**kwargs)
                with self.assertRaises(m.SnapshotError) as error:
                    m.bind_snapshot(self.bound, qmp, output, timeout=.05)
                self.assertFalse(error.exception.receipt['verified'])
                self.assertFalse((output / 'receipt.json').exists())
                self.assertFalse((output / 'snapshot.bin').exists())
                self.assertTrue((output / 'failure.json').is_file())
                self.assertTrue((output / 'snapshot.partial').is_file())
                self.assertNotIn('cont', [name for name, _ in qmp.commands])

    def test_readonly_preflight_rejects_blocks_version_and_unsafe_migration(self):
        for key, value in [('version', '11.1.1'), ('blocks', [{'device': 'disk'}]),
                           ('caps', [{'capability': 'release-ram', 'state': True}])]:
            with self.subTest(key=key):
                qmp = self.qmp(); setattr(qmp, key, value)
                with self.assertRaises(m.SnapshotError):
                    m.bind_snapshot(self.bound, qmp, self.root / key)
                self.assertNotIn('stop', [name for name, _ in qmp.commands])

    def test_publication_failure_retains_partial_and_never_leaves_success_marker(self):
        output = self.root / 'publish-error'
        original_json = m._json

        def publish(dirfd, name, value):
            if name == 'receipt.json':
                raise OSError('injected publication failure')
            return original_json(dirfd, name, value)

        with patch.object(m, '_json', side_effect=publish), self.assertRaises(m.SnapshotError):
            m.bind_snapshot(self.bound, self.qmp(), output, timeout=.3)
        self.assertFalse((output / 'receipt.json').exists())
        self.assertFalse((output / 'snapshot.bin').exists())
        self.assertEqual((output / 'snapshot.partial').read_bytes(), STREAM)
        self.assertTrue((output / 'failure.json').is_file())

    def test_space_refusal_precedes_stop_and_preserves_original_error(self):
        from types import SimpleNamespace
        output = self.root / 'no-space'
        qmp = self.qmp()
        with patch.object(m.shutil, 'disk_usage', return_value=SimpleNamespace(free=0)), self.assertRaises(m.SnapshotError):
            m.bind_snapshot(self.bound, qmp, output)
        self.assertEqual(qmp.commands, [])
        self.assertFalse((output / 'snapshot.bin').exists())
        output = self.root / 'failure-write-error'
        with patch.object(m, '_json', side_effect=OSError('disk full')), self.assertRaises(m.SnapshotError) as error:
            m.bind_snapshot(self.bound, self.qmp(fail=True), output, timeout=.3)
        self.assertIn('Migration did not complete', str(error.exception))
        self.assertIn('disk full', error.exception.receipt['failure_receipt_error'])

    def test_failure_marker_prevents_restoring_even_a_former_completed_capture(self):
        output, _, _ = self.snapshot()
        (output / 'failure.json').write_text('{}')
        target = self.qmp(incoming=True)
        with self.assertRaises(m.SnapshotError):
            m.restore_snapshot(output, self.next_identity(), target)
        self.assertEqual(target.commands, [])

    def test_unconfirmed_stop_cannot_capture(self):
        qmp = self.qmp(); qmp.stop_works = False
        with self.assertRaises(m.SnapshotError):
            m.bind_snapshot(self.bound, qmp, self.root / 'unpaused')
        self.assertNotIn('migrate', [name for name, _ in qmp.commands])

    def test_restore_loads_saved_stream_then_resumes_retained_cpu(self):
        output, saved, _ = self.snapshot()
        target = self.qmp(incoming=True)
        result = m.restore_snapshot(output, self.next_identity(), target, timeout=.3)
        self.assertEqual(target.received, STREAM)
        self.assertTrue(result['verified'])
        self.assertTrue(result['retained_cpu_resumed'])
        self.assertEqual(result['stages'], [])
        self.assertEqual(result['parent_binding_digest'], saved['binding_digest'])
        self.assertEqual(result['identity']['generation'], 1)
        self.assertFalse(result['previous_execution_evidence_reusable'])
        self.assertFalse(result['sony_wbi_resume_verified'])
        names = [name for name, _ in target.commands]
        self.assertLess(names.index('migrate-incoming'), names.index('cont'))
        self.assertNotIn('system_reset', names)

    def test_changed_resources_machine_profile_version_or_source_class_rejected(self):
        output, _, _ = self.snapshot()
        changes = [(['resources', 'kernel'], '5' * 64), (['resources', 'dtb'], '5' * 64),
                   (['resources', 'ram0'], '5' * 64), (['resources', 'ap'], '5' * 64),
                   (['resources', 'cp'], '5' * 64), (['resources', 'manifest'], '5' * 64),
                   (['resources', 'partitions', 'nflasha15'], '5' * 64),
                   (['machine', 'cpus'], 2), (['profile'], 'original-init-cold'),
                   (['source_class'], 'sony_original'), (['qemu', 'sha256'], '5' * 64),
                   (['qemu', 'version'], '11.1.1'), (['device_migration', 'audit_sha256'], '5' * 64)]
        for keys, value in changes:
            with self.subTest(keys=keys):
                bound = self.next_identity(); cursor = bound
                for key in keys[:-1]:
                    cursor = cursor[key]
                cursor[keys[-1]] = value
                target = self.qmp(incoming=True)
                with self.assertRaises(m.SnapshotError):
                    m.restore_snapshot(output, bound, target)
                self.assertEqual(target.commands, [])

    def test_generation_and_run_must_advance_no_old_execution_reuse(self):
        output, _, _ = self.snapshot()
        for run, generation in [('capture-run', 1), ('restore-run', 0), ('restore-run', 2)]:
            with self.subTest(run=run, generation=generation):
                bound = self.next_identity(); bound.update(run=run, generation=generation)
                with self.assertRaises(m.SnapshotError):
                    m.restore_snapshot(output, bound, self.qmp(incoming=True))

    def test_running_or_fresh_paused_target_never_falls_back(self):
        output, _, _ = self.snapshot()
        for state in ('running', 'paused', 'prelaunch'):
            with self.subTest(state=state):
                target = self.qmp(); target.state = state
                with self.assertRaises(m.Unsupported):
                    m.restore_snapshot(output, self.next_identity(), target)
                self.assertFalse(any(name in ('cont', 'system_reset', 'migrate-incoming', 'stop') for name, _ in target.commands))

    def test_failed_incoming_never_continues_cpu(self):
        output, _, _ = self.snapshot()
        target = self.qmp(incoming=True, fail=True)
        with self.assertRaises(m.SnapshotError) as error:
            m.restore_snapshot(output, self.next_identity(), target, timeout=.3)
        self.assertFalse(error.exception.receipt['verified'])
        self.assertNotIn('cont', [name for name, _ in target.commands])

    def test_tampered_or_partial_snapshot_rejected_before_incoming(self):
        output, _, _ = self.snapshot()
        saved = json.loads((output / 'receipt.json').read_text())
        for changes in [dict(status='failed'), dict(verified=False), dict(migration={'status': 'active'}),
                        dict(binding_digest='0' * 64), dict(snapshot_file='../other')]:
            (output / 'receipt.json').write_text(json.dumps({**saved, **changes}))
            target = self.qmp(incoming=True)
            with self.assertRaises(m.SnapshotError):
                m.restore_snapshot(output, self.next_identity(), target)
            self.assertEqual(target.commands, [])
        (output / 'receipt.json').write_text(json.dumps(saved))
        (output / 'snapshot.bin').write_bytes(STREAM + b'tampered')
        with self.assertRaises(m.SnapshotError):
            m.restore_snapshot(output, self.next_identity(), self.qmp(incoming=True))

    def test_snapshot_path_cannot_clobber_existing_or_follow_symlink(self):
        output, _, _ = self.snapshot()
        with self.assertRaises(FileExistsError):
            m.bind_snapshot(self.bound, self.qmp(), output)
        alias = self.root / 'alias'; alias.symlink_to(self.root, target_is_directory=True)
        with self.assertRaises(ValueError):
            m.bind_snapshot(self.bound, self.qmp(), alias / 'snapshot2')
        original = output / 'snapshot.bin'; original.unlink(); original.symlink_to('/dev/null')
        with self.assertRaises(m.SnapshotError):
            m.restore_snapshot(output, self.next_identity(), self.qmp(incoming=True))

    def test_missing_binding_fields_and_nonregular_snapshot_are_rejected(self):
        for key in ('kernel', 'ram0', 'ap', 'cp', 'manifest', 'partitions'):
            bound = identity(); del bound['resources'][key]
            with self.subTest(key=key), self.assertRaises(ValueError):
                m.bind_snapshot(bound, self.qmp(), self.root / key)
        output, _, _ = self.snapshot()
        path = output / 'snapshot.bin'; path.unlink(); path.mkdir()
        with self.assertRaises(m.SnapshotError):
            m.restore_snapshot(output, self.next_identity(), self.qmp(incoming=True))


class FDTransportTests(unittest.TestCase):
    def test_scm_rights_uses_actual_local_fd_and_skips_qmp_events(self):
        left, right = socket.socketpair()
        payload, receiver = socket.socketpair()
        errors = []

        def peer():
            try:
                import array
                raw, ancillary, _, _ = right.recvmsg(4096, socket.CMSG_SPACE(array.array('i').itemsize))
                self.assertEqual(json.loads(raw)['execute'], 'getfd')
                fds = array.array('i'); fds.frombytes(ancillary[0][2][:fds.itemsize])
                passed = socket.socket(fileno=fds[0])
                passed.sendall(b'actual-fd'); passed.close()
                right.sendall(b'{"event":"STOP"}\n{"return":{}}\n')
            except Exception as error:
                errors.append(error)

        worker = threading.Thread(target=peer)
        worker.start()
        client = m.FDQMP(left)
        try:
            self.assertEqual(client.getfd('owned', payload.fileno()), {})
            self.assertEqual(receiver.recv(32), b'actual-fd')
            worker.join(1)
            self.assertFalse(worker.is_alive())
            self.assertEqual(errors, [])
        finally:
            client.stream.close()
            for connection in (left, right, payload, receiver):
                connection.close()

    def test_network_qmp_transport_is_not_accepted(self):
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            with self.assertRaises(ValueError):
                m.FDQMP(sock)
        finally:
            sock.close()


if __name__ == '__main__':
    unittest.main()
