"""Stdlib fixtures for the actual runner helper; no VM, C model or media request."""
import ast
import copy
import io
import json
import os
from pathlib import Path
import platform
import signal
import struct
import subprocess
import sys
import tarfile
import tempfile
import time
import unittest
from unittest import mock

import functional_camera_runner as runner

HERE = Path(__file__).resolve().parent
PROFILE = runner.FUNCTIONAL_CAMERA_PROFILE
PAGES = [0x410000000 + 4096 * index for index in range(16)]
MAILBOX = {'phys0': PAGES[0], 'nonce': 0xa123, 'pid': 123, 'pages': PAGES}
MAILBOX_REPLACEMENTS = ({'pid': 124}, {'nonce': 0xa124},
                        {'pages': list(reversed(PAGES)), 'phys0': PAGES[-1]})
SAFE = {**dict.fromkeys(runner.CLOSE_FIELDS, True), 'errors': []}


def mailbox_line(mailbox=None):
    value = MAILBOX if mailbox is None else mailbox
    return ('OBS FUNCTIONAL_CAMERA_MAILBOX phys0=%#x nonce=%#x pid=%d ABI=%s version=1 pages=%s\n' %
            (value['phys0'], value['nonce'], value['pid'], PROFILE,
             ','.join(hex(page) for page in value['pages']))).encode()


def fake_elf():
    """An ELF metadata fixture, never dlopened or executed."""
    names = b'\0fcam_model_create\0fcam_model_destroy\0fcam_model_request\0'
    raw = bytearray(352 + len(names))
    machine = {'x86_64': 62, 'aarch64': 183}[platform.machine()]
    struct.pack_into('<16sHHIQQQIHHHHHH', raw, 0, b'\x7fELF\x02\x01\x01' + bytes(9),
                     3, machine, 1, 0, 0, 64, 0, 64, 0, 0, 64, 3, 0)
    struct.pack_into('<IIQQQQIIQQ', raw, 128, 0, 11, 0, 0, 256, 96, 2, 0, 8, 24)
    struct.pack_into('<IIQQQQIIQQ', raw, 192, 0, 3, 0, 0, 352, len(names), 0, 0, 1, 0)
    for index, name in enumerate((b'fcam_model_create', b'fcam_model_destroy', b'fcam_model_request'), 1):
        struct.pack_into('<IBBHQQ', raw, 256 + index * 24, names.index(name), 0x12, 0, 1, 0, 1)
    raw[352:] = names
    return bytes(raw)


class ArtifactFixture:
    def __init__(self, root):
        self.root = root
        self.base = root / 'runtime/analysis'
        self.work = self.base / 'scratch/functional-model-build-fixture'
        self.work.mkdir(parents=True)
        sources = {
            'runtime/analysis/functional-camera-abi.h': ('#define FCAM_PROFILE "' + PROFILE + '"\n'
                '#define FCAM_ABI_VERSION 1u\n#define FCAM_PAGE_BYTES 4096u\n'
                '#define FCAM_MAILBOX_PAGES 16u\n#define FCAM_HEADER_BYTES 512u\n').encode(),
            'report/functional-camera-core/functional-camera-core.c': b'/* metadata fixture only */\n',
        }
        for name, raw in sources.items():
            path = root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(raw)
        self.library = self.base / 'functional-camera-model.so'
        self.library.write_bytes(fake_elf())
        (self.work / self.library.name).write_bytes(self.library.read_bytes())
        (self.work / 'build.log').write_bytes(b'')
        compile_data = {'command': ['/fixture/cc', '-shared', '-fPIC', '-Wl,--no-undefined'],
                        'returncode': 0, 'log_sha256': runner.digest(b'')}
        (self.work / 'compile.json').write_text(json.dumps(compile_data))
        with tarfile.open(self.work / 'functional-model-sources.tar.gz', 'w:gz') as archive:
            for name, raw in sources.items():
                entry = tarfile.TarInfo(name)
                entry.size = len(raw)
                archive.addfile(entry, io.BytesIO(raw))
        self.metadata = {'profile': PROFILE, 'work': str(self.work.relative_to(root)),
            'sources': {name: runner.digest(raw) for name, raw in sources.items()},
            'source_archive_sha256': runner.digest((self.work / 'functional-model-sources.tar.gz').read_bytes()),
            'compile_receipt_sha256': runner.digest((self.work / 'compile.json').read_bytes()),
            'library_sha256': runner.digest(self.library.read_bytes()), 'compiler': '/fixture/cc',
            'capture_verified': False, 'physical_asic_compatibility_verified': False}
        self.publish()
        self.qemu = self.base / 'qemu-system-aarch64'
        self.qemu.write_bytes(b'Accepted executable hash fixture; never executed')

    def publish(self):
        for path in (self.work / 'build.json', self.base / 'functional-camera-model-build.json'):
            path.write_text(json.dumps(self.metadata))

    def validate(self):
        with mock.patch.object(runner, 'QEMU_SHA256', runner.digest(self.qemu.read_bytes())):
            return runner.validate_artifact(self.base, self.qemu)


class MailboxTests(unittest.TestCase):
    def test_actual_record_roundtrip_and_repeated_mirror(self):
        line = mailbox_line()
        binding = runner.parse_mailbox(b'kernel boot\n' + line + line)
        self.assertEqual(binding['mailbox'], MAILBOX)
        self.assertEqual(binding['console_record_sha256'], runner.digest(line.split(b' ', 2)[2].rstrip(b'\n')))
        self.assertIsNone(runner.parse_mailbox(line[:-1]))

    def test_malformed_nonce_pages_fields_and_abi(self):
        for raw in (
            mailbox_line().replace(b'nonce=0xa123', b'nonce=nope'),
            mailbox_line().replace(b'nonce=0xa123', b'nonce=0'),
            mailbox_line().replace(b'pid=123', b'pid=True'),
            mailbox_line().replace(b'nonce=0xa123', b'nonce=0xa123 nonce=0xa123'),
            mailbox_line().replace(b'version=1', b'version=2'),
            mailbox_line({**MAILBOX, 'pages': PAGES[:-1]}),
            mailbox_line({**MAILBOX, 'pages': PAGES[:-1] + [PAGES[0]]}),
            mailbox_line({**MAILBOX, 'pages': [PAGES[0] + 1] + PAGES[1:]}),
            mailbox_line({**MAILBOX, 'phys0': PAGES[1]}),
        ):
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                runner.parse_mailbox(raw)

    def test_duplicate_owner_or_fork_cannot_rebind(self):
        for replacement in MAILBOX_REPLACEMENTS:
            for mirrors in (1, 2):
                for ending in (b'\n', b'\r\n'):
                    with self.subTest(replacement=replacement, mirrors=mirrors, ending=ending):
                        raw = mailbox_line() * mirrors + mailbox_line({**MAILBOX, **replacement})
                        with self.assertRaisesRegex(ValueError, 'Multiple functional mailbox owners/identities'):
                            runner.parse_mailbox(raw.replace(b'\n', ending))


class ArtifactTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.fixture = ArtifactFixture(Path(self.directory.name))

    def test_complete_receipts_archive_and_elf_are_inspected_without_loading(self):
        with mock.patch.object(runner.transport, 'Core', side_effect=AssertionError('must not load the library')):
            accepted = self.fixture.validate()
        self.assertEqual(accepted['library_sha256'], self.fixture.metadata['library_sha256'])
        self.assertEqual(accepted['abi']['version'], 1)
        self.assertEqual(len(accepted['abi']['entry_points']), 3)
        self.assertEqual(accepted['build_receipt_sha256'], runner.digest(
            (self.fixture.base / 'functional-camera-model-build.json').read_bytes()))

    def test_library_hash_mismatch_and_unsafe_symlink_rejected(self):
        path = self.fixture.library
        raw = path.read_bytes()
        path.write_bytes(raw + b'mutation')
        with self.assertRaisesRegex(ValueError, 'digest differs'):
            self.fixture.validate()
        path.unlink()
        path.symlink_to(self.fixture.work / path.name)
        with self.assertRaisesRegex(ValueError, 'symlink'):
            self.fixture.validate()

    def test_source_or_build_receipt_mismatch_rejected(self):
        path = self.fixture.base / 'functional-camera-abi.h'
        path.write_bytes(path.read_bytes() + b'/* changed source */')
        with self.assertRaisesRegex(ValueError, 'source differs'):
            self.fixture.validate()
        self.fixture.metadata['capture_verified'] = True
        self.fixture.publish()
        with self.assertRaisesRegex(ValueError, 'profile/claim'):
            self.fixture.validate()

    def test_unsafe_permissions_archive_mismatch_and_qemu_mismatch(self):
        library = self.fixture.library
        library.chmod(0o666)
        with self.assertRaisesRegex(ValueError, 'Untrusted'):
            self.fixture.validate()
        library.chmod(0o644)
        archive = self.fixture.work / 'functional-model-sources.tar.gz'
        raw = archive.read_bytes()
        archive.write_bytes(raw + b'extra')
        with self.assertRaisesRegex(ValueError, 'archive digest'):
            self.fixture.validate()
        archive.write_bytes(raw)
        with mock.patch.object(runner, 'QEMU_SHA256', '0' * 64), self.assertRaisesRegex(ValueError, 'unchanged QEMU'):
            runner.validate_artifact(self.fixture.base, self.fixture.qemu)

    def test_missing_model_abi_export_is_rejected(self):
        raw = fake_elf().replace(b'fcam_model_request', b'fcam_wrong_request')
        with self.assertRaisesRegex(ValueError, 'entry points'):
            runner.check_library_abi(raw)

    def test_strict_profile_never_preflights_or_starts_a_broker(self):
        with mock.patch.object(runner, 'validate_artifact') as validate, mock.patch.object(runner.transport, 'start') as start:
            self.assertIsNone(runner.prepare('', Path('/missing'), Path('/missing'), Path('/missing')))
            validate.assert_not_called()
            start.assert_not_called()
        with self.assertRaises(ValueError):
            runner.prepare('strict', None, None, None)


class LifecycleTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.run = Path(self.directory.name) / 'menu-runs/run-fixture'
        self.run.mkdir(parents=True, mode=0o700)
        (self.run / 'console.log').write_bytes(b'')
        self.manifest = {'full_connection_proof': {'original_chain': True}, 'capture_verified': False}
        (self.run / 'runtime-manifest.json').write_text(json.dumps(self.manifest))
        self.owner = {'pid': os.getpid(), 'starttime': 1, 'ppid': os.getppid(), 'exe': 'runner-fixture'}
        for patcher in (mock.patch.object(runner.transport, 'RUNS', self.run.parent),
                        mock.patch.object(runner.transport, 'process_identity', return_value=self.owner)):
            patcher.start()
            self.addCleanup(patcher.stop)
        self.artifact = {'library': '/owned/functional-camera-model.so', 'library_sha256': '1' * 64,
                         'qemu_sha256': runner.QEMU_SHA256, 'build_receipt_sha256': '2' * 64,
                         'source_archive_sha256': '3' * 64}
        self.instance = runner.FunctionalCameraRunner(self.run, self.artifact)
        self.proc = mock.Mock()
        self.proc.poll.return_value = None

    def broker(self, cleanup=None):
        result = mock.Mock(start_error=None)
        result.stop.return_value = dict(SAFE if cleanup is None else cleanup)
        self.instance.broker = result
        self.instance.binding = runner.parse_mailbox(mailbox_line())
        self.instance.handoff = {'qemu_identity': {'pid': 456, 'starttime': 2, 'exe': 'owned-vm'}}
        return result

    def receipts(self):
        mailbox = self.instance.binding['mailbox']
        events = [{'kind': 'binding', 'mailbox': mailbox, 'config': {'owner': self.owner,
                   'qemu': self.instance.handoff['qemu_identity']}},
                  {'kind': 'attached'}, {'kind': 'request', 'sequence': 1, 'opcode': 1},
                  {'kind': 'response', 'sequence': 1, 'opcode': 1, 'actual_c_result': 0,
                   'origin': {'source': 0x80020002, 'destination': 0x81cf0000, 'command': 0x3003, 'bytes': 24},
                   'returned_bytes': 128, 'token': 0},
                  {'kind': 'cancel_cleanup', 'actual_c_result': 0, 'returned_bytes': 128},
                  {'kind': 'detach_commit', 'model_work_stopped': True, 'no_further_ram_after_ack': True},
                  {'kind': 'mailbox_detached', 'cleanup_detach': True, 'protocol_physmode_restored': True},
                  {'kind': 'debugger_disconnected', 'detached': True, 'protocol_physmode_restored': True},
                  {'kind': 'cleanup', **SAFE}]
        return [{**event, 'event': index, 'model_instance': mailbox['nonce']} for index, event in enumerate(events, 1)]

    def init_evidence(self, vdf_first=True, later_init=False):
        """Reduced HOST_TEST run-q2w2q6v8 transcript; actual wire origins/State128 bytes, no VM/model."""
        self.broker()
        mailbox = {**MAILBOX, 'pid': 258, 'nonce': 6225410929072990342}
        self.instance.binding = runner.parse_mailbox(mailbox_line(mailbox))
        tail = self.receipts()[-5:]
        events = self.receipts()[:2]
        native = dict(source=0x81cf61c4, destination=0x92840747, command=0x138,
                      bytes=24, fnv1a64=0xe39cfe6ede356b69, producer_tid=381)
        cp = dict(source=0x80020002, destination=0x90030001, command=0x3003,
                  bytes=24, fnv1a64=0x855a2708cad3e099, producer_tid=379)
        state1 = bytes.fromhex(
            '010000000f00000080020000e00100001e0000005a0000009001000064000000'
            '1b41000000000000c0c62d000000000086e83aa0411a65560100000000000000'
            '0100000000000000000000000000000000000000000000000000000000000000'
            '0000000000000000000000000000000001000000000000000000000000000000')
        state3 = bytearray(state1)
        struct.pack_into('<3Q', state3, 56, 2, 2, 1)
        struct.pack_into('<Q', state3, 112, 2)
        vdf = bytes.fromhex(
            '01000000a000000086e83aa0411a655602000000000000000200000000000000'
            '02000000000000007eedd048d9ddc6d725d8b8043b81193025d8b8043b811930'
            '00100e000000000080020000e001000080070000190859900100000001000000'
            '0100000001000000010000000100000001000000010000000000000000000000'
            '0105050000000000000000000000000001000000000000000100000000000000')
        canonical = bytes.fromhex('01050500000000000000000000000000')

        def emit(kind, **fields):
            event = dict(kind=kind, event=len(events) + 1, model_instance=mailbox['nonce'], **fields)
            events.append(event)
            return event

        transactions = [(1, native, b'', state1), (5, native, canonical, vdf), (1, cp, b'', bytes(state3))] if vdf_first else [
                        (1, cp, b'', state1)]
        if later_init:
            transactions.append((1, native, b'', bytes(state3)))
        with_payloads = runner.transport.PayloadRecords(self.run)
        try:
            for seq, (op, origin, incoming, output) in enumerate(transactions, 1):
                header = bytearray(512)
                struct.pack_into('<4I2Q3I', header, 0, runner.transport.MAGIC, 1, mailbox['pid'], 1,
                                 mailbox['nonce'], seq, op, len(incoming), runner.transport.DATA)
                struct.pack_into('<Q', header, 56, runner.transport.fnv64(incoming))
                struct.pack_into('<5I', header, 96, origin['producer_tid'], origin['source'], origin['destination'],
                                 origin['command'], origin['bytes'])
                struct.pack_into('<Q', header, 120, origin['fnv1a64'])
                struct.pack_into('<16Q', header, 128, *mailbox['pages'])
                request_payload = with_payloads.retain(header, 'in', incoming, event=len(events) + 1)
                emit('request', sequence=seq, opcode=op, origin=origin, raw_header_hex=header.hex(),
                     raw_header_sha256=runner.digest(header), request_bytes=len(incoming),
                     request_sha256=runner.digest(incoming), request_fnv1a64=runner.transport.fnv64(incoming),
                     request_payload=request_payload)
                output_payload = with_payloads.retain(header, 'out', output, event=len(events) + 1)
                fields = dict(sequence=seq, opcode=op, origin=origin, actual_c_result=0, returned_bytes=len(output),
                              returned_sha256=runner.digest(output), returned_fnv1a64=runner.transport.fnv64(output),
                              token=0, total=0, offset=0, request_payload=request_payload,
                              output_payload=output_payload, result_transfer=None)
                emit('core_result', **fields)
                if seq < 3:
                    emit('model_frame', sequence=seq, opcode=op, origin=origin, proof=dict(
                        model_instance=mailbox['nonce'], config_generation=seq, frame_generation=seq,
                        after=dict(rendered=seq, consumed=seq - 1, jpeg_encoded=0, video_encoded=0, retired=seq)))
                committed = bytearray(header)
                struct.pack_into('<I', committed, 12, 2)
                struct.pack_into('<Ii', committed, 44, len(output), 0)
                struct.pack_into('<4Q', committed, 64, runner.transport.fnv64(output), 0, 0, 0)
                emit('response', **fields, raw_header_sha256=runner.digest(header),
                     response_header_sha256=runner.digest(committed), data_readback=True)
        finally:
            with_payloads.close()
        for event in tail:
            emit(event['kind'], **{key: value for key, value in event.items() if key not in ('kind', 'event', 'model_instance')})
        generation = 2 if vdf_first else 1
        probe = (f'OBS FUNCTIONAL_CAMERA_CONTROL_PROBE pid=258 tid=379 index=0 '
                 f'probe_run_id=1 init_run_id=1 state_run_id=0 bridge_rc=0 probe_rc=0 faults=0 '
                 f'native_source=0x80020002 native_destination=0x90030001 native_command=0x3003 native_bytes=24 '
                 f'native_fnv1a=855a2708cad3e099 model_initialized=1 probe_attempts=1 probe_successes=1 probe_refusals=0 '
                 f'model_instance=6225410929072990342 config_generation={generation} rendered={generation} '
                 f'frame_generation={generation}\n').encode()
        console = mailbox_line(mailbox) + probe
        (self.run / 'console.log').write_bytes(console)
        return events, console

    def close_evidence(self, events):
        with mock.patch.object(runner.transport, 'read_receipts', return_value=events):
            return self.instance.before_close('sd-export')

    def test_handoff_waits_before_start_and_uses_only_console_pages(self):
        (self.run / 'console.log').write_bytes(mailbox_line())
        handoff = {'qemu_pid': 456, 'debugger_quiesced': True}
        calls = []
        broker = mock.Mock(start_error=None)

        def observe(*args):
            calls.append('handoff')
            if calls.count('handoff') == 1:
                start.assert_not_called()
                return None
            return handoff

        def attach(*args, **config):
            calls.append('start')
            self.assertEqual(args[1:3], (self.owner['pid'], MAILBOX))
            self.assertTrue(config['debugger_quiesced'])
            self.assertIs(config['coordination_lock'], self.instance.coordination_lock)
            self.assertEqual(config['gdb_socket'], self.run / runner.GDB)
            self.assertTrue(config['resume_allowed']())
            self.instance.done.set()
            return broker

        with mock.patch.object(runner, 'debugger_handoff', side_effect=observe), \
                mock.patch.object(runner.transport, 'start', side_effect=attach) as start:
            self.instance.proc = self.proc
            self.instance._watch()
        self.assertIsNone(self.instance.error)
        self.assertEqual(calls, ['handoff', 'handoff', 'start'])
        self.assertIs(self.instance.broker, broker)

    def test_firmware_fault_after_attach_checks_capture_then_stops_and_stays_failed(self):
        broker = self.broker()
        cleanup = {**SAFE, 'detached': True}
        broker.stop.return_value = cleanup
        self.instance.proc = self.proc
        console = self.run / 'console.log'
        console.write_bytes(mailbox_line() + JPEG_ENABLE_HOST + PCIE_WARNING_HOST + b'\n' +
                            b''.join(native_clip() + jpeg_lifecycle(kind='main')) + b'Entering exception mon')

        def finish_fault():
            with console.open('ab') as stream:
                stream.write(b'itor.\r\n')

        self.proc.poll.side_effect = finish_fault
        events = []
        capture_closed, publish = runner.require_capture_closed, self.instance._publish

        def checked_capture(run):
            events.append('capture-closed')
            capture_closed(run)

        def stopped():
            events.append('stop')
            self.assertTrue(self.instance.done.is_set())
            self.assertTrue(self.instance.error.startswith('FirmwareFault:'))
            self.assertFalse(self.instance.coordination_lock._is_owned())
            return cleanup

        def published(phase):
            events.append(phase)
            return publish(phase)

        broker.stop.side_effect = stopped
        with mock.patch.object(runner, 'require_capture_closed', side_effect=checked_capture), \
                mock.patch.object(self.instance, '_publish', side_effect=published), \
                mock.patch.object(self.instance, 'before_close') as close, \
                mock.patch.object(self.instance.done, 'wait', return_value=False):
            self.instance._watch()
        self.assertEqual(events, ['waiting-for-debugger-handoff', 'capture-closed', 'stop', 'failed'])
        close.assert_not_called()
        broker.stop.assert_called_once_with()
        self.assertIs(self.instance.cleanup, cleanup)
        self.assertFalse(self.instance.closed)
        self.assertIsNone(self.instance.final_receipts)
        final = json.loads((self.run / runner.RECEIPT).read_text())
        self.assertEqual(final['phase'], 'failed')
        self.assertEqual(final['cleanup'], cleanup)
        self.assertFalse(final['capture_verified'])
        with self.assertRaisesRegex(RuntimeError, 'FirmwareFault:'):
            self.instance.check()
        with self.assertRaisesRegex(ValueError, 'orderly close'):
            runner.read_receipts(self.run)
        # A failed worker cannot restart handoff when called again.
        with mock.patch.object(runner, 'debugger_handoff') as handoff, mock.patch.object(runner.transport, 'start') as start:
            self.instance._watch()
        handoff.assert_not_called()
        start.assert_not_called()
        self.proc.wait.assert_not_called()
        self.proc.terminate.assert_not_called()
        self.proc.kill.assert_not_called()

    def test_firmware_fault_cannot_stop_active_pending_or_malformed_capture(self):
        broker = self.broker()
        self.instance.proc = self.proc
        still = jpeg_lifecycle()[0]
        for evidence in (native_clip()[:1], native_clip()[:-1], [still],
                         [b'OBS FUNCTIONAL_JPEG_CODEC operation=request-lease-release-failed\n'],
                         [b'OBS FUNCTIONAL_MPR_REQUEST command=invalid\n']):
            with self.subTest(evidence=evidence):
                self.instance.done.clear()
                (self.run / 'console.log').write_bytes(mailbox_line() + b''.join(evidence) + b'Exception>\n')
                self.instance._watch()
                broker.stop.assert_not_called()
                self.assertTrue(self.instance.done.is_set())
                self.assertTrue(self.instance.error.startswith('FirmwareFault:'))
                self.assertFalse(self.instance.cleanup['safe_to_close'])
                self.assertIn('cleanup blocked:', self.instance.cleanup['errors'][0])
                self.assertFalse(self.instance.closed)
                self.assertEqual(json.loads((self.run / runner.RECEIPT).read_text())['phase'], 'failed')

    def test_firmware_fault_before_attach_never_hands_off_or_starts_broker(self):
        self.instance.proc = self.proc
        for fatal in (b'Entering exception monitor.\n', b'Exception>\n', b'OBS GUI_MODEL_FAILED reason=model-failed\n'):
            with self.subTest(fatal=fatal):
                self.instance.done.clear()
                (self.run / 'console.log').write_bytes(mailbox_line() + fatal)
                with mock.patch.object(runner, 'debugger_handoff') as handoff, \
                        mock.patch.object(runner.transport, 'start') as start:
                    self.instance._watch()
                handoff.assert_not_called()
                start.assert_not_called()
                self.assertIsNone(self.instance.broker)
                self.assertIsNone(self.instance.cleanup)
                self.assertTrue(self.instance.done.is_set())
                self.assertTrue(self.instance.error.startswith('FirmwareFault:'))

    def test_firmware_fault_during_handoff_cannot_start_broker(self):
        self.instance.proc = self.proc
        console = self.run / 'console.log'
        console.write_bytes(mailbox_line())

        def handoff(*args):
            console.write_bytes(console.read_bytes() + b'Exception>\n')
            return {'qemu_pid': 456}

        with mock.patch.object(runner, 'debugger_handoff', side_effect=handoff), \
                mock.patch.object(runner.transport, 'start') as start:
            self.instance._watch()
        start.assert_not_called()
        self.assertIsNone(self.instance.broker)
        self.assertTrue(self.instance.done.is_set())
        self.assertTrue(self.instance.error.startswith('FirmwareFault:'))

    def test_firmware_diagnostics_and_non_line_start_strings_do_not_stop_broker(self):
        broker = self.broker()
        self.instance.proc = self.proc
        self.proc.poll.side_effect = lambda: self.instance.done.set()
        for diagnostic in (b'log Entering exception monitor.\n', b'log Exception>\n',
                           b'log OBS GUI_MODEL_FAILED reason=diagnostic\n',
                           b'Entering exception mon\n', b'Exception\n', b'OBS GUI_MODEL_FAILED\n'):
            with self.subTest(diagnostic=diagnostic):
                self.instance.done.clear()
                (self.run / 'console.log').write_bytes(mailbox_line() + diagnostic)
                self.instance._watch()
                broker.stop.assert_not_called()
                self.assertIsNone(self.instance.error)
                self.assertIsNone(self.instance.cleanup)
                self.instance.check()

    def test_firmware_fault_keeps_actual_stop_failure_fields_and_primary_error(self):
        broker = self.broker()
        self.instance.proc = self.proc
        cleanup = {**SAFE, 'safe_to_close': False, 'mailbox_detached': False,
                   'errors': ['actual mailbox detach failed']}
        broker.cleanup = cleanup
        for failure in (None, RuntimeError('actual stop failed')):
            with self.subTest(failure=failure):
                self.instance.done.clear()
                (self.run / 'console.log').write_bytes(mailbox_line() + b'Exception>\n')
                broker.stop.return_value, broker.stop.side_effect = cleanup, failure
                self.instance._watch()
                expected = cleanup if failure is None else {
                    **cleanup, 'errors': [*cleanup['errors'], 'RuntimeError: actual stop failed']}
                self.assertEqual(self.instance.cleanup, expected)
                self.assertTrue(self.instance.error.startswith('FirmwareFault:'))
                self.assertNotIn('actual stop failed', self.instance.error)
                self.assertTrue(self.instance.cleanup['debugger_stopped'])
                self.assertFalse(self.instance.closed)
                final = json.loads((self.run / runner.RECEIPT).read_text())
                self.assertEqual(final['phase'], 'failed')
                self.assertEqual(final['cleanup'], expected)

    def test_explicit_close_joins_fault_worker_before_reusing_broker_stop(self):
        broker = self.broker()
        (self.run / 'console.log').write_bytes(mailbox_line() + b'Exception>\n')
        entered, release = runner.threading.Event(), runner.threading.Event()

        def stopped():
            self.assertFalse(self.instance.coordination_lock._is_owned())
            entered.set()
            self.assertTrue(release.wait(2))
            return dict(SAFE)

        broker.stop.side_effect = stopped
        self.addCleanup(lambda: self.instance.thread.join(timeout=3))
        self.addCleanup(release.set)
        self.instance.start(self.proc)
        self.assertTrue(entered.wait(2))
        join = self.instance.thread.join

        def joined(timeout):
            release.set()
            join(timeout=timeout)

        with mock.patch.object(self.instance.thread, 'join', side_effect=joined), \
                mock.patch.object(runner.transport, 'read_receipts', return_value=self.receipts()):
            result = self.instance.before_close('explicit-close')
            self.instance.before_close('explicit-close-again')
        self.assertFalse(self.instance.thread.is_alive())
        self.assertEqual(broker.stop.call_count, 2)
        self.assertEqual(result['phase'], 'closed')
        self.assertTrue(self.instance.error.startswith('FirmwareFault:'))
        self.assertFalse(result['capture_verified'])

    def test_conflicting_bindings_fail_before_debugger_or_model_access(self):
        self.instance.proc = self.proc
        for replacement in MAILBOX_REPLACEMENTS:
            for previously_bound in (False, True):
                with self.subTest(replacement=replacement, previously_bound=previously_bound):
                    original = runner.parse_mailbox(mailbox_line()) if previously_bound else None
                    self.instance.binding = original
                    self.instance.error = None
                    (self.run / 'console.log').write_bytes(
                        (b'' if previously_bound else mailbox_line()) + mailbox_line({**MAILBOX, **replacement}))
                    with mock.patch.object(runner, 'debugger_handoff') as handoff, \
                            mock.patch.object(runner.transport, 'start') as start, \
                            mock.patch.object(runner.transport, 'Core') as core:
                        self.instance._watch()
                    handoff.assert_not_called()
                    start.assert_not_called()
                    core.assert_not_called()
                    message = ('Functional mailbox owner changed' if previously_bound else
                               'Multiple functional mailbox owners/identities')
                    self.assertEqual(self.instance.error, 'ValueError: ' + message)
                    self.assertEqual(self.instance.binding, original)
                    self.assertIsNone(self.instance.broker)
                    self.assertEqual(json.loads((self.run / runner.RECEIPT).read_text())['phase'], 'failed')

    def test_busy_debugger_deadline_never_starts_broker(self):
        (self.run / 'console.log').write_bytes(mailbox_line())
        self.instance.proc = self.proc
        with mock.patch.object(runner, 'debugger_handoff', return_value=None), \
                mock.patch.object(runner.time, 'monotonic', side_effect=[0, 21]), \
                mock.patch.object(runner.transport, 'start') as start:
            self.instance._watch()
        start.assert_not_called()
        self.assertIn('previous debugger lease did not close', self.instance.error)
        self.assertEqual(json.loads((self.run / runner.RECEIPT).read_text())['phase'], 'failed')

    def test_failed_attach_retains_actual_broker_and_startup_cleanup(self):
        (self.run / 'console.log').write_bytes(mailbox_line())
        self.instance.proc = self.proc
        broker = mock.Mock(start_error=None)
        cleanup = {**SAFE, 'safe_to_close': False, 'worker_stopped': False, 'errors': ['startup blocked']}
        broker.stop.return_value = cleanup
        error = RuntimeError('actual broker attach failed')
        error.functional_camera_broker = broker
        error.functional_camera_cleanup = cleanup
        with mock.patch.object(runner, 'debugger_handoff', return_value={'qemu_pid': 456}), \
                mock.patch.object(runner.transport, 'start', side_effect=error):
            self.instance._watch()
        self.assertIs(self.instance.broker, broker)
        self.assertIs(self.instance.startup_cleanup, cleanup)
        with self.assertRaises(runner.UnsafeCameraClose):
            self.instance.before_close('vm-shutdown')

    def test_early_stop_cannot_attach_or_publish_detached_guest_status(self):
        self.instance.done.set()
        self.instance.proc = self.proc
        with mock.patch.object(runner.transport, 'start') as start:
            self.instance._watch()
            value = self.instance.before_close('early-stop')
        start.assert_not_called()
        self.assertTrue(value['cleanup']['broker_never_attached'])
        self.assertNotIn('mailbox_detached', value['cleanup'])

    def test_owner_mismatch_and_duplicate_start_refused(self):
        with mock.patch.object(runner.os, 'getpid', return_value=os.getpid() + 1), self.assertRaisesRegex(ValueError, 'owner changed'):
            self.instance.start(self.proc)
        self.instance.thread = mock.Mock()
        with self.assertRaisesRegex(ValueError, 'already started'):
            self.instance.start(self.proc)

    def test_qmp_preserves_pause_intent_and_does_not_resume_on_failed_cont(self):
        with self.instance.qmp_command('stop'):
            pass
        self.assertFalse(self.instance.run_allowed)
        with self.assertRaises(RuntimeError):
            with self.instance.qmp_command('cont'):
                raise RuntimeError('QMP rejected continue')
        self.assertFalse(self.instance.run_allowed)
        with self.instance.qmp_command('cont'):
            pass
        self.assertTrue(self.instance.run_allowed)

    def test_HOST_close_checks_capture_before_runner_or_broker_done(self):
        broker = self.broker()
        broker.done = runner.threading.Event()
        capture = runner.require_capture_closed
        calls = []

        def check(run):
            calls.append('capture')
            self.assertFalse(self.instance.done.is_set())
            self.assertFalse(broker.done.is_set())
            return capture(run)

        def stop():
            calls.append('stop')
            self.assertTrue(self.instance.done.is_set())
            broker.done.set()
            return dict(SAFE)

        broker.stop.side_effect = stop
        pending = jpeg_lifecycle()[:1]
        (self.run / 'console.log').write_bytes(mailbox_line() + b''.join(pending))
        with mock.patch.object(runner, 'require_capture_closed', side_effect=check):
            with self.assertRaises(runner.UnsafeCameraClose):
                self.instance.before_close('HOST-pending')
            self.assertEqual(calls, ['capture'])
            self.assertFalse(self.instance.done.is_set())
            self.assertFalse(broker.done.is_set())
            (self.run / 'console.log').write_bytes(mailbox_line() + JPEG_ENABLE_HOST + PCIE_WARNING_HOST + b'\n')
            with mock.patch.object(runner.transport, 'read_receipts', return_value=self.receipts()):
                self.instance.before_close('HOST-closed')
        self.assertEqual(calls, ['capture', 'capture', 'stop'])
        self.assertTrue(broker.done.is_set())

    def test_stop_precedes_read_and_final_receipt_preserves_other_manifest_fields(self):
        events = []
        broker = self.broker()
        broker.stop.side_effect = lambda: events.append('stop') or dict(SAFE)
        publish = self.instance._publish

        def observed_publish(phase):
            if phase == 'closed':
                self.assertFalse(self.instance.closed)
            events.append('publish-' + phase)
            return publish(phase)

        with mock.patch.object(runner.transport, 'read_receipts', side_effect=lambda run: events.append('read') or self.receipts()), \
                mock.patch.object(self.instance, '_publish', side_effect=observed_publish):
            value = self.instance.before_close('sd-export')
            self.instance.before_close('vm-shutdown')
        self.assertEqual(events, ['stop', 'read', 'publish-closed'])
        self.assertEqual(value['broker_event_counts'], {event['kind']: 1 for event in self.receipts()})
        self.assertEqual(value['initialization']['source']['command'], 0x3003)
        self.assertIsNone(value['initialization']['rendered'])
        self.assertFalse(value['initialization']['encoder_output_from_INIT'])
        self.assertFalse(value['capture_verified'])
        self.assertFalse(value['physical_ASIC_compatibility_verified'])
        actual = json.loads((self.run / 'runtime-manifest.json').read_text())
        self.assertEqual(actual['full_connection_proof'], self.manifest['full_connection_proof'])
        self.assertEqual(actual['functional_camera_runtime']['phase'], 'closed')
        with mock.patch.object(runner.transport, 'read_receipts', return_value=self.receipts()):
            self.assertEqual(runner.read_receipts(self.run), self.receipts())

    def test_actual_init_render_counters_require_matching_pid_nonce_and_source(self):
        events, console = self.init_evidence(vdf_first=False)
        result = self.close_evidence(events)
        initial = result['initialization']
        self.assertEqual(initial['response']['sequence'], 1)
        self.assertEqual(initial['rendered'], 1)
        self.assertEqual(initial['frame_generation'], 1)
        self.assertTrue(initial['probe_receipt_correlated'])
        self.assertFalse(initial['encoder_output_from_INIT'])
        self.assertFalse(result['capture_verified'])
        (self.run / 'console.log').write_bytes(console.replace(b'native_command=0x3003', b'native_command=0x3000'))
        with self.assertRaisesRegex(ValueError, 'unique broker INIT origin'):
            self.instance.receipt('closed')

    def test_HOST_TEST_actual_VDF_first_matches_CP_INIT_and_current_checkpoint(self):
        events, _ = self.init_evidence()
        result = self.close_evidence(events)
        initial = result['initialization']
        self.assertEqual(initial['response']['sequence'], 3)
        self.assertEqual(initial['probe_run_id'], 1)
        self.assertEqual(initial['source']['producer_tid'], 379)
        self.assertEqual(initial['source']['fnv1a64'], 0x855a2708cad3e099)
        self.assertEqual([initial[key] for key in ('config_generation', 'rendered', 'consumed', 'frame_generation')], [2, 2, 1, 2])
        self.assertTrue(initial['probe_receipt_correlated'])
        self.assertEqual(result['model_response_counts_by_opcode'], {'1': 2, '5': 1})
        self.assertEqual(result['broker_event_counts']['model_frame'], 2)
        self.assertFalse(initial['encoder_output_from_INIT'])
        self.assertFalse(result['capture_verified'])
        self.assertTrue(all(result['cleanup'][key] is True for key in runner.CLOSE_FIELDS))
        self.assertEqual(json.loads((self.run / runner.RECEIPT).read_text())['phase'], 'closed')
        self.assertEqual(json.loads((self.run / 'runtime-manifest.json').read_text())['functional_camera_runtime'], result)
        with mock.patch.object(runner.transport, 'read_receipts', return_value=events):
            self.assertEqual(runner.read_receipts(self.run), events)
        self.instance.check()
        with self.instance.qmp_command('quit'):
            pass
        self.instance.guard_shutdown(self.proc)
        self.proc.wait.assert_not_called()
        self.proc.terminate.assert_not_called()
        self.proc.kill.assert_not_called()

    def test_later_STATE_probe_keeps_original_INIT_identity_and_counter_domain(self):
        events, console = self.init_evidence()
        state_probe = console.split(b'\n', 1)[1]
        for old, new in ((b'index=0', b'index=2'), (b'native_command=0x3003', b'native_command=0x4073'),
                         (b'probe_run_id=1', b'probe_run_id=2'), (b'state_run_id=0', b'state_run_id=2'),
                         (b'probe_attempts=1', b'probe_attempts=2'), (b'probe_successes=1', b'probe_successes=2')):
            state_probe = state_probe.replace(old, new)
        (self.run / 'console.log').write_bytes(console + state_probe)
        initial = self.close_evidence(events)['initialization']
        self.assertEqual(initial['response']['sequence'], 3)
        self.assertEqual(initial['probe_run_id'], 1)
        self.assertIn('index=0', initial['console_probe_record'])

    def test_VDF_or_missing_attempt_cannot_increment_original_AP_probe_census(self):
        events, console = self.init_evidence()
        for successes, refusals in ((2, 0), (1, 1)):
            changed = console
            for old, new in ((b'probe_run_id=1', b'probe_run_id=2'), (b'init_run_id=1', b'init_run_id=2'),
                             (b'probe_attempts=1', b'probe_attempts=2'),
                             (b'probe_successes=1', f'probe_successes={successes}'.encode()),
                             (b'probe_refusals=0', f'probe_refusals={refusals}'.encode())):
                changed = changed.replace(old, new)
            (self.run / 'console.log').write_bytes(changed)
            with self.subTest(successes=successes, refusals=refusals), self.assertRaisesRegex(
                    runner.UnsafeCameraClose, 'native probe ledger'):
                self.close_evidence(events)
            self.assertFalse(self.instance.cleanup['safe_to_close'])

    def test_later_unrelated_INIT_cannot_replace_the_CP_probe_transaction(self):
        events, _ = self.init_evidence(later_init=True)
        result = self.close_evidence(events)
        self.assertEqual(result['initialization']['response']['sequence'], 3)
        self.assertEqual([e for e in events if e['kind'] == 'response'][-1]['sequence'], 4)
        self.assertEqual(result['model_response_counts_by_opcode'], {'1': 3, '5': 1})
        self.assertEqual(result['broker_event_counts']['model_frame'], 2)

    def test_VDF_INIT_without_new_AP_probe_is_not_counted_as_correlated(self):
        events, console = self.init_evidence()
        events = [e for e in events if e.get('sequence') != 3]
        for index, event in enumerate(events, 1): event['event'] = index
        (self.run / 'console.log').write_bytes(console.split(b'OBS FUNCTIONAL_CAMERA_CONTROL_PROBE')[0])
        result = self.close_evidence(events)
        self.assertFalse(result['initialization']['probe_receipt_correlated'])
        self.assertNotIn('probe_run_id', result['initialization'])
        self.assertEqual(result['initialization']['response']['sequence'], 1)
        self.assertEqual(result['model_response_counts_by_opcode'], {'1': 1, '5': 1})
        self.assertEqual(result['broker_event_counts']['model_frame'], 2)

    def test_rehashed_State128_cannot_change_actual_checkpoint_counters_or_identity(self):
        events, _ = self.init_evidence()
        path = self.run / 'functional-camera-data/00000000000000000003-out.bin'
        original = path.read_bytes()
        for offset in (0, 4, 48, 56, 64, 72, 80, 88, 104, 108, 112, 120):
            changed = copy.deepcopy(events)
            raw = bytearray(original)
            raw[offset] ^= 1
            path.write_bytes(raw)
            info = path.stat()
            for event in changed:
                if event['kind'] not in ('core_result', 'response') or event['sequence'] != 3:
                    continue
                event.update(returned_sha256=runner.digest(raw), returned_fnv1a64=runner.transport.fnv64(raw))
                event['output_payload'].update(sha256=runner.digest(raw), writeback_sha256=runner.digest(raw),
                    fnv1a64=runner.transport.fnv64(raw), mtime_ns=info.st_mtime_ns, ctime_ns=info.st_ctime_ns)
                if event['kind'] == 'response':
                    request = next(e for e in changed if e['kind'] == 'request' and e['sequence'] == 3)
                    committed = bytearray.fromhex(request['raw_header_hex'])
                    struct.pack_into('<I', committed, 12, 2)
                    struct.pack_into('<Ii', committed, 44, 128, 0)
                    struct.pack_into('<4Q', committed, 64, runner.transport.fnv64(raw), 0, 0, 0)
                    event['response_header_sha256'] = runner.digest(committed)
            with self.subTest(offset=offset), self.assertRaisesRegex(runner.UnsafeCameraClose, 'State128'):
                self.close_evidence(changed)
            self.assertFalse(self.instance.closed)
            self.assertFalse(self.instance.cleanup['safe_to_close'])

    def test_selected_INIT_payload_requires_exact_provenance_types_and_retained_bytes(self):
        events, _ = self.init_evidence()
        for key, value in (('source_kind', 'HOST_TEST_claim_only'), ('producer_event', 1), ('sequence', 1),
                           ('opcode', True), ('model_instance', 1), ('direction', 'in'), ('token', False),
                           ('writeback_verified', 1), ('path', '../outside.bin'), ('fnv1a64', 0),
                           ('sha256', '0' * 64), ('writeback_sha256', '0' * 64), ('inode', 1), ('bytes', 128.0)):
            changed = copy.deepcopy(events)
            core = next(e for e in changed if e['kind'] == 'core_result' and e['sequence'] == 3)
            response = next(e for e in changed if e['kind'] == 'response' and e['sequence'] == 3)
            core['output_payload'][key] = value
            response['output_payload'] = copy.deepcopy(core['output_payload'])
            with self.subTest(key=key), self.assertRaises(runner.UnsafeCameraClose):
                self.close_evidence(changed)
            self.assertFalse(self.instance.cleanup['safe_to_close'])
        path = self.run / 'functional-camera-data/00000000000000000003-out.bin'
        path.write_bytes(bytes(128))
        with self.assertRaisesRegex(runner.UnsafeCameraClose, 'payload identity/digest'):
            self.close_evidence(events)

    def test_probe_original_numeric_origin_identity_and_counts_cannot_be_relabelled(self):
        events, console = self.init_evidence()
        for old, new in (
            (b'pid=258', b'pid=259'), (b'tid=379', b'tid=381'),
            (b'model_instance=6225410929072990342', b'model_instance=6225410929072990343'),
            (b'native_fnv1a=855a2708cad3e099', b'native_fnv1a=e39cfe6ede356b69'),
            (b'native_source=0x80020002', b'native_source=0x81cf61c4'),
            (b'native_destination=0x90030001', b'native_destination=0x92840747'),
            (b'native_command=0x3003', b'native_command=0x138'), (b'native_bytes=24', b'native_bytes=16'),
            (b'config_generation=2', b'config_generation=1'), (b'rendered=2', b'rendered=1'),
            (b'frame_generation=2', b'frame_generation=1'), (b'probe_run_id=1', b'probe_run_id=3'),
            (b'init_run_id=1', b'init_run_id=3'), (b'probe_attempts=1', b'probe_attempts=2'),
            (b'probe_successes=1', b'probe_successes=2'), (b'state_run_id=0', b'state_run_id=1'),
            (b'bridge_rc=0', b'bridge_rc=1'), (b'probe_rc=0', b'probe_rc=1'), (b'faults=0', b'faults=1'),
            (b'model_initialized=1', b'model_initialized=0'), (b'rendered=2', b'rendered=True'),
            (b'index=0', b'index=2'),
        ):
            with self.subTest(old=old, new=new):
                (self.run / 'console.log').write_bytes(console.replace(old, new))
                with self.assertRaises(runner.UnsafeCameraClose):
                    self.close_evidence(copy.deepcopy(events))
                self.assertFalse(self.instance.closed)
                self.assertFalse(self.instance.cleanup['safe_to_close'])
                blocked = json.loads((self.run / runner.RECEIPT).read_text())
                self.assertEqual(blocked['phase'], 'blocked-sd-export')
                self.assertTrue(blocked['cleanup']['errors'])
                with self.assertRaises(ValueError):
                    runner.read_receipts(self.run)
        # A correct numeric origin with another native request's wire hash still cannot match.
        (self.run / 'console.log').write_bytes(console)
        self.assertEqual(self.close_evidence(events)['initialization']['response']['sequence'], 3)

    def test_ambiguous_probe_or_broker_INIT_incomplete_response_and_sequence_are_rejected(self):
        events, console = self.init_evidence()
        for mutation in ('wrong-first-origin', 'duplicate-candidate', 'missing-response', 'missing-core',
                         'duplicate-response', 'wrong-sequence', 'wrong-raw-sequence', 'wrong-pid', 'wrong-tid',
                         'wrong-nonce', 'core-origin', 'response-origin', 'response-FNV', 'response-size',
                         'response-token', 'response-hash', 'response-header', 'readback', 'typed-result',
                         'typed-origin', 'typed-reference', 'typed-generation', 'invented-render', 'duplicate-probe'):
            changed = copy.deepcopy(events)
            cp_request = next(e for e in changed if e['kind'] == 'request' and e['sequence'] == 3)
            cp_core = next(e for e in changed if e['kind'] == 'core_result' and e['sequence'] == 3)
            cp_response = next(e for e in changed if e['kind'] == 'response' and e['sequence'] == 3)
            if mutation == 'wrong-first-origin':
                for e in changed:
                    if e.get('sequence') in (1, 3) and 'origin' in e:
                        e['origin'] = copy.deepcopy(cp_request['origin']) if e['sequence'] == 1 else dict(cp_request['origin'], source=1)
            elif mutation == 'duplicate-candidate':
                first = next(e for e in changed if e['kind'] == 'request')
                first['origin'] = copy.deepcopy(cp_request['origin'])
            elif mutation == 'missing-response': changed.remove(cp_response)
            elif mutation == 'missing-core': changed.remove(cp_core)
            elif mutation == 'duplicate-response': changed.insert(changed.index(cp_response), copy.deepcopy(cp_response))
            elif mutation == 'wrong-sequence': cp_response['sequence'] = 1
            elif mutation in ('wrong-raw-sequence', 'wrong-pid', 'wrong-tid'):
                raw = bytearray.fromhex(cp_request['raw_header_hex'])
                struct.pack_into('<Q' if mutation == 'wrong-raw-sequence' else '<I', raw,
                                 {'wrong-raw-sequence': 24, 'wrong-pid': 8, 'wrong-tid': 96}[mutation], 1)
                cp_request['raw_header_hex'], cp_request['raw_header_sha256'] = raw.hex(), runner.digest(raw)
            elif mutation == 'wrong-nonce': cp_response['model_instance'] += 1
            elif mutation == 'core-origin': cp_core['origin'] = dict(cp_core['origin'], producer_tid=381)
            elif mutation == 'response-origin': cp_response['origin'] = dict(cp_response['origin'], fnv1a64=0)
            elif mutation == 'response-FNV': cp_response['returned_fnv1a64'] ^= 1
            elif mutation == 'response-size': cp_response['returned_bytes'] = 127
            elif mutation == 'response-token': cp_response['token'] = 1
            elif mutation == 'response-hash': cp_response['returned_sha256'] = '0' * 64
            elif mutation == 'response-header': cp_response['response_header_sha256'] = '0' * 64
            elif mutation == 'readback': cp_response['data_readback'] = False
            elif mutation == 'typed-result': cp_response['actual_c_result'] = False
            elif mutation == 'typed-origin': cp_request['origin'] = dict(cp_request['origin'], bytes=24.0)
            elif mutation == 'typed-reference': cp_response['output_payload'] = dict(cp_response['output_payload'], token=False)
            elif mutation == 'typed-generation':
                next(e for e in changed if e['kind'] == 'model_frame')['proof']['config_generation'] = True
                last = [e for e in changed if e['kind'] == 'model_frame'][-1]
                last['proof']['frame_generation'] = 2.0
            elif mutation == 'invented-render':
                frame = copy.deepcopy(next(e for e in changed if e['kind'] == 'model_frame'))
                frame.update(sequence=3, origin=copy.deepcopy(cp_request['origin']))
                changed.insert(changed.index(cp_response), frame)
            probe_console = console + console.split(b'\n', 1)[1] if mutation == 'duplicate-probe' else console
            (self.run / 'console.log').write_bytes(probe_console)
            for index, e in enumerate(changed, 1): e['event'] = index
            with self.subTest(mutation=mutation), self.assertRaises(runner.UnsafeCameraClose):
                with mock.patch.object(runner.transport, 'read_receipts', return_value=changed):
                    with self.instance.qmp_command('quit'):
                        self.fail('invalid content may not authorize quit')
            self.assertFalse(self.instance.closed)
            self.assertFalse(self.instance.cleanup['safe_to_close'])

    def test_read_receipt_failure_cannot_be_published_or_treated_as_safe(self):
        self.broker()
        for error in (ValueError('bad receipts'), OSError('receipt read failed')):
            with self.subTest(error=error), mock.patch.object(runner.transport, 'read_receipts', side_effect=error):
                with self.assertRaises(runner.UnsafeCameraClose):
                    self.instance.before_close('sd-export')
                self.assertFalse(self.instance.closed)
                self.assertFalse(self.instance.cleanup['safe_to_close'])
                self.assertIn(str(error), self.instance.cleanup['errors'])
                final = json.loads((self.run / runner.RECEIPT).read_text())
                self.assertEqual(final['phase'], 'blocked-sd-export')
                with self.assertRaises(ValueError): runner.read_receipts(self.run)
        self.proc.wait.side_effect = lambda: setattr(self.proc.poll, 'return_value', 0)
        with mock.patch.object(runner.transport, 'read_receipts', side_effect=ValueError('invalid final receipt')), \
                mock.patch.object(runner.signal, 'signal', return_value=None):
            self.instance.guard_shutdown(self.proc, RuntimeError('original scenario failed'))
        self.proc.wait.assert_called_once_with()
        self.proc.terminate.assert_not_called()
        self.proc.kill.assert_not_called()
        retained = json.loads((self.run / 'functional-camera-retained-owner.json').read_text())
        self.assertFalse(retained['cleanup']['safe_to_close'])
        self.assertFalse(retained['quit_sent'])
        self.assertFalse(retained['terminate_sent'])
        self.assertFalse(retained['force_kill_authorized'])

    def test_unsafe_stop_blocks_quit_export_and_receipt_reads(self):
        self.broker({**SAFE, 'worker_stopped': False, 'safe_to_close': False,
                     'errors': ['Actual encoder still owns resources']})
        with mock.patch.object(runner.transport, 'read_receipts') as read:
            with self.assertRaises(runner.UnsafeCameraClose):
                with self.instance.qmp_command('quit'):
                    self.fail('quit must not be sent')
            with self.assertRaises(runner.UnsafeCameraClose):
                self.instance.before_close('sd-export')
            with self.assertRaises(ValueError):
                runner.read_receipts(self.run)
        read.assert_not_called()
        self.assertFalse(self.instance.closed)
        value = json.loads((self.run / runner.RECEIPT).read_text())
        self.assertEqual(value['phase'], 'blocked-sd-export')

    def test_each_required_teardown_fact_and_final_receipt_are_required(self):
        for key in runner.CLOSE_FIELDS[1:]:
            with self.subTest(key=key), mock.patch.object(runner.transport, 'read_receipts') as read:
                self.broker({**SAFE, key: False})
                with self.assertRaises(runner.UnsafeCameraClose):
                    self.instance.before_close('sd-export')
                read.assert_not_called()
        self.broker()
        with mock.patch.object(runner.transport, 'read_receipts', return_value=[{'event': 1, 'kind': 'request'}]), \
                self.assertRaisesRegex(runner.UnsafeCameraClose, 'Final broker cleanup'):
            self.instance.before_close('sd-export')
        self.assertFalse(self.instance.closed)

    def test_blocked_startup_worker_prevents_cleanup_even_without_a_broker(self):
        self.instance.thread = mock.Mock()
        self.instance.thread.is_alive.return_value = True
        with self.assertRaises(runner.UnsafeCameraClose):
            self.instance.before_close('vm-shutdown')
        self.assertFalse(self.instance.cleanup['safe_to_close'])

    def test_guard_retains_owner_and_original_exception_until_external_vm_exit(self):
        self.broker({**SAFE, 'safe_to_close': False, 'worker_stopped': False, 'errors': ['blocked encoder']})
        original = RuntimeError('original AP scenario failure')
        self.proc.wait.side_effect = lambda: setattr(self.proc.poll, 'return_value', 0)
        with mock.patch.object(runner.signal, 'signal', return_value=None):
            try:
                try:
                    raise original
                finally:
                    self.instance.guard_shutdown(self.proc, original)
            except RuntimeError as error:
                self.assertIs(error, original)
        self.proc.wait.assert_called_once_with()
        self.proc.terminate.assert_not_called()
        self.proc.kill.assert_not_called()
        value = json.loads((self.run / 'functional-camera-retained-owner.json').read_text())
        self.assertIn('original AP scenario failure', value['original_error'])
        self.assertFalse(value['quit_sent'])
        self.assertFalse(value['force_kill_authorized'])

    def test_failed_retention_receipt_cannot_skip_waiting_for_vm(self):
        self.broker({**SAFE, 'safe_to_close': False, 'errors': ['blocked encoder']})
        self.proc.wait.side_effect = lambda: setattr(self.proc.poll, 'return_value', 0)
        original = RuntimeError('original scenario failure')
        with mock.patch.object(runner, '_publish', side_effect=OSError('output disk full')), \
                mock.patch.object(runner.signal, 'signal', return_value=None):
            self.instance.guard_shutdown(self.proc, original)
        self.proc.wait.assert_called_once_with()
        self.proc.terminate.assert_not_called()
        self.proc.kill.assert_not_called()
        self.assertIn('retention receipt failed', self.instance.error)

    def test_actual_os_term_keeps_owner_and_guest_until_blocked_cleanup_guest_exits(self):
        script = r'''
import ast,json,os,signal,subprocess,sys
from pathlib import Path
sys.path.insert(0,sys.argv[1])
import functional_camera_runner as runner
run=Path(sys.argv[2]);runner.transport.RUNS=run.parent
child=subprocess.Popen([sys.executable,'-c',
    'import sys,time; from pathlib import Path; p=Path(sys.argv[1]);\nwhile not p.exists(): time.sleep(.01)',str(run/'allow-host-double-exit')])
instance=runner.FunctionalCameraRunner(run,{'library':'host-signal-double'})
class Broker:
    start_error=None
    def stop(self):
        assert child.poll() is None, 'guest was signalled before broker cleanup'
        return {**dict.fromkeys(runner.CLOSE_FIELDS,False),'debugger_stopped':True,
                'worker_stopped':True,'protocol_physmode_restored':True,'errors':['held actual cleanup double']}
instance.broker=Broker()
functional_camera_profile=runner.FUNCTIONAL_CAMERA_PROFILE
resize_mmio_watch=False
probe=ast.parse((Path(sys.argv[1])/'qemu-menu-probe.py').read_text())
term=next(node for node in probe.body if isinstance(node,ast.If) and
    any(isinstance(item,ast.FunctionDef) and item.name=='stop_live' for item in node.body))
exec(compile(ast.Module(body=[term],type_ignores=[]),'<actual-term>','exec'))
print(json.dumps({'pid':child.pid}),flush=True)
try:signal.pause()
finally:instance.guard_shutdown(child,sys.exc_info()[1])
'''
        process = subprocess.Popen([sys.executable, '-u', '-c', script, str(HERE), str(self.run)],
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True, text=True)
        try:
            ready = json.loads(process.stdout.readline())
            process.send_signal(signal.SIGTERM)
            retained = self.run/'functional-camera-retained-owner.json'
            deadline = time.monotonic()+5
            while not retained.exists() and time.monotonic()<deadline:
                time.sleep(.01)
            self.assertTrue(retained.exists())
            self.assertIsNone(process.poll())
            os.kill(ready['pid'], 0)
            process.send_signal(signal.SIGTERM)
            self.assertIsNone(process.poll())
            value = json.loads(retained.read_text())
            self.assertFalse(value['cleanup']['safe_to_close'])
            self.assertFalse(value['cleanup']['mailbox_detached'])
            self.assertFalse(value['quit_sent'])
            self.assertFalse(value['terminate_sent'])
            self.assertIn('SystemExit: 0', value['original_error'])
        finally:
            (self.run/'allow-host-double-exit').write_text('external host double exit')
            stdout, stderr = process.communicate(timeout=5)
        self.assertEqual(process.returncode, 0, stderr)
        final = json.loads((self.run/runner.RECEIPT).read_text())
        self.assertEqual(final['phase'], 'blocked-vm-shutdown')
        self.assertFalse(final['cleanup']['safe_to_close'])

    def test_actual_term_handler_is_opt_in_and_enters_python_cleanup(self):
        tree = ast.parse((HERE / 'qemu-menu-probe.py').read_text())
        guard = next(node for node in tree.body if isinstance(node, ast.If) and
                     any(isinstance(item, ast.FunctionDef) and item.name == 'stop_live' for item in node.body))
        for profile in ('', PROFILE):
            with self.subTest(profile=profile):
                signals = mock.Mock(SIGTERM=15)
                scope = {'resize_mmio_watch': False, 'functional_camera_profile': profile, 'signal': signals}
                exec(compile(ast.Module(body=[guard], type_ignores=[]), '<actual-term-guard>', 'exec'), scope)
                if profile:
                    signals.signal.assert_called_once_with(15, scope['stop_live'])
                    with self.assertRaises(SystemExit):
                        scope['stop_live'](15, None)
                else:
                    signals.signal.assert_not_called()

    def test_actual_shutdown_finally_retains_vm_before_other_cleanup(self):
        tree = ast.parse((HERE / 'qemu-menu-probe.py').read_text())
        block = next(node.finalbody for node in ast.walk(tree) if isinstance(node, ast.Try) and node.finalbody
            and any(isinstance(call, ast.Call) and ast.unparse(call.func) == 'functional_camera.guard_shutdown'
                    for call in ast.walk(node.finalbody[0]))
            and any(isinstance(call, ast.Call) and ast.unparse(call.func) == 'proc.kill'
                    for item in node.finalbody for call in ast.walk(item)))
        self.broker({**SAFE, 'safe_to_close': False, 'errors': ['encoder owns memory']})
        early = mock.Mock()
        scope = {'functional_camera': self.instance, 'proc': self.proc, 'sys': __import__('sys'),
                 'early_media_watch': early, 'host_sd_fd': None, 'directory_sd_fd': 40,
                 'host_sd_export_verified': [False], 'out': self.run, 'subprocess': __import__('subprocess')}
        with mock.patch.object(runner.signal, 'signal', return_value=None), self.assertRaises(runner.UnsafeCameraClose):
            exec(compile(ast.Module(body=block, type_ignores=[]), '<actual-finally-guard>', 'exec'), scope)
        self.proc.wait.assert_called_once_with()
        self.proc.terminate.assert_not_called()
        self.proc.kill.assert_not_called()
        early.stop.assert_not_called()

    def test_actual_export_entry_point_blocks_before_settings_or_sd_mutation(self):
        tree = ast.parse((HERE / 'qemu-menu-probe.py').read_text())
        node = next(node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef) and node.name == 'export_with_settings')
        self.broker()
        self.instance.error = 'actual broker transport failed'
        export = mock.Mock(side_effect=AssertionError('export must remain unreachable'))
        scope = {'functional_camera': self.instance, 'yc_ownership_observe': False,
                 'settings_persist': False, 'export_virtual_sd': export}
        exec(compile(ast.Module(body=[node], type_ignores=[]), '<actual-export-guard>', 'exec'), scope)
        with self.assertRaisesRegex(RuntimeError, 'actual broker transport failed'):
            scope['export_with_settings']()
        export.assert_not_called()

    def test_cleanup_cannot_borrow_another_vm_or_reorder_detach(self):
        self.broker()
        for mutation in ('nonce', 'owner', 'qemu', 'order', 'missing-ack', 'late-work', 'cancel-error'):
            events = copy.deepcopy(self.receipts())
            if mutation == 'nonce': events[-1]['model_instance'] += 1
            elif mutation == 'owner': events[0]['config']['owner']['starttime'] += 1
            elif mutation == 'qemu': events[0]['config']['qemu']['pid'] += 1
            elif mutation == 'order': events[5], events[6] = events[6], events[5]
            elif mutation == 'missing-ack': events.pop(6)
            elif mutation == 'late-work': events[3], events[4] = events[4], events[3]
            elif mutation == 'cancel-error': events[4]['actual_c_result'] = -5
            for index, event in enumerate(events, 1): event['event'] = index
            with self.subTest(mutation=mutation), mock.patch.object(runner.transport, 'read_receipts', return_value=events):
                with self.assertRaises(runner.UnsafeCameraClose):
                    with self.instance.qmp_command('quit'):
                        self.fail('unsafe receipt may not authorize quit')
                self.assertFalse(self.instance.closed)
                self.assertFalse(self.instance.cleanup['safe_to_close'])

    def test_attached_without_init_can_detach_without_claiming_c_cancellation(self):
        self.broker()
        events = [event for event in self.receipts() if event['kind'] not in ('request', 'response', 'cancel_cleanup')]
        for index, event in enumerate(events, 1): event['event'] = index
        with mock.patch.object(runner.transport, 'read_receipts', return_value=events):
            self.instance.before_close('vm-shutdown')
        self.assertTrue(self.instance.closed)
        self.assertNotIn('cancel_cleanup', self.instance.receipt('closed')['broker_event_counts'])

    def test_dead_vm_retains_actual_failed_detach_facts_without_force_termination(self):
        self.proc.poll.return_value = 0
        cleanup = {**SAFE, 'safe_to_close': False, 'mailbox_detached': False,
                   'errors': ['mailbox detach: Process is a zombie']}
        self.broker(cleanup)
        with mock.patch.object(runner.signal, 'signal', return_value=None):
            with self.assertRaises(runner.UnsafeCameraClose):
                self.instance.guard_shutdown(self.proc)
        self.proc.wait.assert_not_called()
        self.proc.terminate.assert_not_called()
        self.proc.kill.assert_not_called()
        self.assertEqual(self.instance.cleanup, cleanup)
        final = json.loads((self.run / runner.RECEIPT).read_text())
        self.assertEqual(final['phase'], 'blocked-vm-shutdown')
        self.assertFalse(final['cleanup']['mailbox_detached'])

    def test_current_clip_must_finish_original_close_before_broker_stop_or_quit(self):
        broker = self.broker()
        lines = native_clip(epoch=1, first=1)
        (self.run / 'console.log').write_bytes(mailbox_line() + b''.join(lines))
        with mock.patch.object(runner.transport, 'read_receipts', return_value=self.receipts()):
            with self.instance.qmp_command('quit'):
                pass
        broker.stop.assert_called_once()
        self.instance.closed = False
        self.instance.done.clear()
        broker.stop.reset_mock()
        # A fresh Open must not inherit the preceding clip's successful Close.
        (self.run / 'console.log').write_bytes(mailbox_line() + b''.join(lines + native_clip(epoch=2, first=4)[:1]))
        with self.assertRaisesRegex(runner.UnsafeCameraClose, 'REC Stop/Close'):
            with self.instance.qmp_command('quit'):
                self.fail('active original clip cannot be cancelled into a clean exit')
        broker.stop.assert_not_called()
        self.assertFalse(self.instance.done.is_set())

    def test_actual_temporary_export_keeps_camera_available(self):
        tree = ast.parse((HERE / 'qemu-menu-probe.py').read_text())
        node = next(node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef) and node.name == 'export_with_settings')
        self.broker()
        export = mock.Mock(return_value={'ok': True})
        scope = {'functional_camera': self.instance, 'yc_ownership_observe': False,
                 'settings_persist': False, 'export_virtual_sd': export}
        exec(compile(ast.Module(body=[node], type_ignores=[]), '<actual-export-keeps-model>', 'exec'), scope)
        self.assertEqual(scope['export_with_settings'](), {'ok': True})
        self.instance.broker.stop.assert_not_called()
        self.assertFalse(self.instance.closed)
        self.instance.check()


# HOST fixtures follow functional-jpeg-codec.c note_detail; no guest/model is run.
JPEG_ENABLE_HOST = (
    b'OBS FUNCTIONAL_JPEG_CODEC operation=enable rc=0 pid=259 tid=259 producer_tid=0 sequence=0 '
    b'original_base=0x10000000 exec_entry=0x1011b654 caller=0 object=(nil) manager=(nil) control=(nil) '
    b'context=0 key=0 source=0 destination=0 command=0 native_bytes=0 trigger_fnv=0000000000000000 '
    b'response_tag=0 model_instance=0 bytes=0 output_fnv=0000000000000000 stream_mode=0 '
    b'kind=without-pin selector=0 comp_object=(nil) physical_asic_compatible=0 capture_verified=0')
# Exact reported glued suffix (console raw offset 145230, line 1894); remaining values above are HOST fixtures.
PCIE_WARNING_HOST = (b'[  258.849384] ERROR:pcie_set_link: current Link Speed does not match the target: '
                     b'ch=0, current=1, target=3')


def jpeg_record(operation, sequence=1, kind='without-pin', **changes):
    """Current public receipt schema, generated only as HOST parser input."""
    fields = dict(operation=operation, rc=0, pid=123, tid=456, producer_tid=456, sequence=sequence,
                  original_base='0x10000000', exec_entry='0x1011b654' if kind == 'without-pin' else '0x101226c4',
                  caller='0x1013b6ec', object='0x100', manager='0x200', control='0x300', context=1,
                  key=2, source=3, destination=4, command=5, native_bytes=104,
                  trigger_fnv='000000000000abcd', response_tag=0, model_instance=0 if operation == 'original-request' else 41251,
                  bytes=0 if operation == 'original-request' else 1024, output_fnv='000000000000abcd',
                  stream_mode=0, kind=kind, selector=0,
                  comp_object='0x400' if kind == 'main' and operation in
                  ('original-maincomp-exec', 'original-maincomp-config', 'original-rescmd-done') else '(nil)',
                  physical_asic_compatible=0, capture_verified=0)
    if operation == 'original-request':
        fields.update(request_hex='00' * 104)
    elif operation == 'original-request-lease':
        fields.update(model_instance=0, sds_type=0, sds_handle='0x10', sds_offset=0, stream_position=0,
                      lease_offset=0, lease_address='0x8000', lease_capacity=2048, lease_generation=1,
                      lease_token='0xa5', lease_group=1, lease_unit=16, lease_area=0, lease_unit_type=0)
    elif operation == 'output-readback':
        fields.update(lease_generation=1, lease_token='0xa5', lease_address='0x8000', lease_offset=0,
                      lease_capacity=2048, model_token='0xb5', model_bytes=1024, model_fnv='000000000000abcd',
                      model_offset=0, readback_bytes=1024, readback_fnv='000000000000abcd')
    elif operation == 'original-maincomp-exec':
        fields.update(comp_caller='0x1013b7e0', comp_exec_entry='0x10122dfc', previous_ack_hex='00' * 16,
                      previous_ack_address='0x518', original_result=0, native_config='0x600', config_length_offset=92)
    elif operation == 'original-maincomp-config':
        fields.update(native_config='0x600', config_length_offset=92, actual_length=1024,
                      expected_length=1024, original_result=0)
    elif operation not in ('queued-ack', 'queued-done'):
        fields.update(receiver_pid=123, receiver_tid=456, response_hex='00' * 16,
                      response_source='0x123', response_destination='0x456', lease_generation=1, lease_token='0xa5')
        if operation.startswith(('original-received-', 'original-freed-')):
            fields.update(reply_address='0x500', reply_hex='00' * 40)
            if operation.startswith('original-freed-'):
                fields.update(free_rc=0)
        else:
            done = operation == 'original-rescmd-done'
            fields.update(callback_caller='0x1013b788',
                          res_entry=hex(0x10000000 + (0x122b44 if kind == 'main' and done else
                                                     0x120e64 if kind == 'main' else 0x11a9dc)),
                          response_address='0x518', response_mid='0x8311' if done else '0x8310',
                          original_result=0 if done or kind == 'main' else '0x200',
                          expected_result=0 if done or kind == 'main' else '0x200', original_errno=0,
                          release_rc=0, terminal=int(done), lease_released=int(done))
    fields.update(changes)
    return ('OBS FUNCTIONAL_JPEG_CODEC ' + ' '.join(f'{key}={value}' for key, value in fields.items()) + '\n').encode()


def jpeg_lifecycle(sequence=1, kind='without-pin'):
    return [jpeg_record(operation, sequence, kind) for operation in
            ('original-request', 'original-received-done', 'original-freed-done', 'original-rescmd-done')]


def native_clip(epoch=1, first=1):
    lines = []
    for offset, command in enumerate((0, 1, 4)):
        seq = first + offset
        fields = f'command={command} request_seq={seq} epoch={epoch} memory_generation={epoch} native_fnv={seq} pid=123 instance=0xa123'
        lines.append(f'OBS FUNCTIONAL_MPR_REQUEST {fields} rc=0\n'.encode())
        lines.append(f'OBS FUNCTIONAL_MPR_OPERATION {fields} operation_error=0 event_error=0\n'.encode())
        lines.append(f'OBS FUNCTIONAL_MPR_EVENT_RECEIVED {fields} received=1 rc=0\n'.encode())
        lines.append(f'OBS FUNCTIONAL_MPR_EVENT_FREE {fields} received=1 rc=0 operation_error=0\n'.encode())
    return lines


class CaptureCloseTests(unittest.TestCase):
    def test_next_open_can_be_logged_before_prior_close_send_returns(self):
        first, second = native_clip(), native_clip(epoch=2, first=4)
        # The original receiver frees Close and opens again before send_event() logs OPERATION.
        lines = first[:9] + first[10:] + second[:1] + first[9:10] + second[1:]
        with tempfile.TemporaryDirectory() as temporary:
            run = Path(temporary)
            (run/'console.log').write_bytes(mailbox_line() + b''.join(lines))
            runner.require_capture_closed(run)

    def test_HOST_setup_enable_with_reported_glued_kernel_record_equals_separate_records(self):
        with tempfile.TemporaryDirectory() as temporary:
            run = Path(temporary)
            for tail in (JPEG_ENABLE_HOST + PCIE_WARNING_HOST + b'\n',
                         JPEG_ENABLE_HOST + b'\n' + PCIE_WARNING_HOST + b'\n',
                         JPEG_ENABLE_HOST + b'\n', JPEG_ENABLE_HOST + PCIE_WARNING_HOST + b'\r\n',
                         JPEG_ENABLE_HOST.replace(b'operation=enable', b'operation=shutdown') + b'\n'):
                with self.subTest(tail=tail):
                    (run / 'console.log').write_bytes(mailbox_line() + tail)
                    runner.require_capture_closed(run)

    def test_HOST_setup_never_hides_pending_still_or_video(self):
        with tempfile.TemporaryDirectory() as temporary:
            run = Path(temporary)
            for records in (jpeg_lifecycle()[:1], jpeg_lifecycle()[:-1], native_clip()[:1], native_clip()[:-1]):
                (run / 'console.log').write_bytes(mailbox_line() + JPEG_ENABLE_HOST + PCIE_WARNING_HOST + b'\n' + b''.join(records))
                with self.subTest(records=records), self.assertRaises(ValueError):
                    runner.require_capture_closed(run)

    def test_HOST_ambiguous_setup_duplicate_fake_operation_or_hidden_lifecycle_fails_closed(self):
        request = jpeg_lifecycle()[0].rstrip(b'\n')
        bad = (JPEG_ENABLE_HOST + b' operation=original-request',
               JPEG_ENABLE_HOST.replace(b'operation=enable', b'fake_operation=enable'),
               JPEG_ENABLE_HOST.replace(b'operation=enable', b'operation=enable operation=enable'),
               JPEG_ENABLE_HOST + b' requested_operation=original-request',
               JPEG_ENABLE_HOST + b' retained=1',
               JPEG_ENABLE_HOST + PCIE_WARNING_HOST + b' retained=1',
               JPEG_ENABLE_HOST + b' sequence=1',
               JPEG_ENABLE_HOST.replace(b'sequence=0', b'sequence=1'),
               JPEG_ENABLE_HOST + b' ' + request,
               JPEG_ENABLE_HOST + request,
               JPEG_ENABLE_HOST + b'\r' + request,
               b'OBS FUNCTIONAL_JPEG_CODEC',
               JPEG_ENABLE_HOST + b' ' + native_clip()[0].rstrip(b'\n'),
               JPEG_ENABLE_HOST + b' original-request sequence=1',
               JPEG_ENABLE_HOST.replace(b'operation=enable', b'operation=unknown'),
               b'operation=receipt-format-error rc=-75 pid=123 sequence=1 requested_operation=original-request',
               b'operation=request-lease-release-failed',
               b'', b'operation=enable', b'operation=callback-rejected rc=-71',
               jpeg_record('original-request-lease').split(b' ', 2)[2].rstrip(b'\n'),
               jpeg_record('queued-done').split(b' ', 2)[2].rstrip(b'\n'))
        with tempfile.TemporaryDirectory() as temporary:
            run = Path(temporary)
            for raw in bad:
                if not raw.startswith(b'OBS '):
                    raw = b'OBS FUNCTIONAL_JPEG_CODEC ' + raw
                (run / 'console.log').write_bytes(mailbox_line() + raw + b'\n')
                with self.subTest(raw=raw), self.assertRaises(ValueError):
                    runner.require_capture_closed(run)

    def test_HOST_full_source_shaped_ACK_and_late_send_receipts_cannot_close_early(self):
        with tempfile.TemporaryDirectory() as temporary:
            run = Path(temporary)
            for kind in ('without-pin', 'main'):
                operations = ['original-request', 'original-request-lease', 'output-readback',
                              'original-received-ack', 'original-freed-ack', 'original-rescmd-ack', 'queued-ack']
                if kind == 'main': operations.append('original-maincomp-exec')
                operations.extend(['original-received-done', 'original-freed-done'])
                if kind == 'main': operations.append('original-maincomp-config')
                operations.extend(['original-rescmd-done', 'queued-done'])
                lines = [jpeg_record(operation, kind=kind) for operation in operations]
                for end in range(1, len(lines) + 1):
                    (run / 'console.log').write_bytes(mailbox_line() + b''.join(lines[:end]))
                    with self.subTest(kind=kind, end=end):
                        if end >= len(lines) - 1: runner.require_capture_closed(run)
                        else:
                            with self.assertRaises(ValueError): runner.require_capture_closed(run)
                duplicate_ack = lines[:6] + lines[5:6] + lines[6:]
                (run / 'console.log').write_bytes(mailbox_line() + b''.join(duplicate_ack))
                with self.subTest(kind=kind, duplicate_ack=True), self.assertRaises(ValueError):
                    runner.require_capture_closed(run)

    def test_HOST_actual_lifecycle_glued_kernel_or_malformed_fields_never_authorizes_close(self):
        with tempfile.TemporaryDirectory() as temporary:
            run = Path(temporary)
            for index in range(4):
                for mutation in ('glued', 'bare-token', 'duplicate', 'fake-operation', 'missing-operation', 'two-OBS',
                                 'CR-two-OBS', 'missing-newline', 'invalid-wire'):
                    lines = jpeg_lifecycle()
                    if mutation == 'glued': lines[index] = lines[index].rstrip(b'\n') + PCIE_WARNING_HOST + b'\n'
                    elif mutation == 'bare-token': lines[index] = lines[index].rstrip(b'\n') + b' malformed\n'
                    elif mutation == 'duplicate': lines[index] = lines[index].replace(b'pid=123', b'pid=123 pid=123', 1)
                    elif mutation == 'fake-operation': lines[index] = lines[index].replace(b'operation=', b'fake_operation=', 1)
                    elif mutation == 'missing-operation': lines[index] = lines[index].replace(lines[index].split(b' ', 3)[2] + b' ', b'', 1)
                    elif mutation == 'two-OBS': lines[index] = lines[index].rstrip(b'\n') + b' ' + JPEG_ENABLE_HOST + b'\n'
                    elif mutation == 'CR-two-OBS': lines[index] = lines[index].rstrip(b'\n') + b'\r' + JPEG_ENABLE_HOST + b'\n'
                    elif mutation == 'invalid-wire':
                        key = b'request_hex=' if index == 0 else b'response_hex='
                        lines[index] = lines[index].replace(key, key + b'bad-wire', 1)
                    else: lines = lines[:index] + [lines[index].rstrip(b'\n')]
                    (run / 'console.log').write_bytes(mailbox_line() + b''.join(lines))
                    with self.subTest(index=index, mutation=mutation), self.assertRaises(ValueError):
                        runner.require_capture_closed(run)

    def test_HOST_Main_done_requires_receive_free_and_actual_terminal_callback(self):
        with tempfile.TemporaryDirectory() as temporary:
            run = Path(temporary)
            for mutation in ('none', 'no-free', 'free-failed', 'no-receive', 'terminal', 'lease-released',
                             'release-failed', 'wrong-callback', 'main-ack-return-zero', 'wrong-receiver', 'wrong-lease',
                             'wrong-pid', 'wrong-kind', 'wrong-instance', 'wrong-order', 'missing-terminal', 'missing-lease-released'):
                lines = jpeg_lifecycle(kind='main')
                if mutation == 'no-free': lines.pop(2)
                elif mutation == 'free-failed': lines[2] = lines[2].replace(b'free_rc=0', b'free_rc=-5')
                elif mutation == 'no-receive': lines.pop(1)
                elif mutation == 'terminal': lines[-1] = lines[-1].replace(b'terminal=1', b'terminal=0')
                elif mutation == 'lease-released': lines[-1] = lines[-1].replace(b'lease_released=1', b'lease_released=0')
                elif mutation == 'release-failed': lines[-1] = lines[-1].replace(b'release_rc=0', b'release_rc=-5')
                elif mutation == 'wrong-callback': lines[-1] = lines[-1].replace(b'res_entry=0x10122b44', b'res_entry=0x10120e64')
                elif mutation == 'main-ack-return-zero': lines[-1] = jpeg_record('original-rescmd-ack', kind='main')
                elif mutation == 'wrong-receiver': lines[2] = lines[2].replace(b'receiver_tid=456', b'receiver_tid=457')
                elif mutation == 'wrong-lease': lines[-1] = lines[-1].replace(b'lease_token=0xa5', b'lease_token=0xa6')
                elif mutation == 'wrong-pid': lines[-1] = lines[-1].replace(b'pid=123', b'pid=124', 1)
                elif mutation == 'wrong-kind': lines[-1] = lines[-1].replace(b'kind=main', b'kind=without-pin')
                elif mutation == 'wrong-instance': lines[-1] = lines[-1].replace(b'model_instance=41251', b'model_instance=41252')
                elif mutation == 'wrong-order': lines[1], lines[2] = lines[2], lines[1]
                elif mutation == 'missing-terminal': lines[-1] = lines[-1].replace(b' terminal=1', b'')
                elif mutation == 'missing-lease-released': lines[-1] = lines[-1].replace(b' lease_released=1', b'')
                (run / 'console.log').write_bytes(mailbox_line() + b''.join(lines))
                with self.subTest(mutation=mutation):
                    if mutation == 'none': runner.require_capture_closed(run)
                    else:
                        with self.assertRaises(ValueError): runner.require_capture_closed(run)

    def test_still_requires_current_native_done_and_actual_output_lease_release(self):
        lines = jpeg_lifecycle()
        with tempfile.TemporaryDirectory() as temporary:
            run = Path(temporary)
            for mutation in ('none', 'pending', 'wrong-sequence', 'wrong-instance', 'lease-release-failed', 'no-receive', 'new-capture', 'missing-result'):
                changed = list(lines)
                if mutation == 'pending': changed.pop()
                elif mutation == 'wrong-sequence': changed[-1] = changed[-1].replace(b'sequence=1', b'sequence=2')
                elif mutation == 'wrong-instance': changed[-1] = changed[-1].replace(b'model_instance=41251', b'model_instance=41252')
                elif mutation == 'lease-release-failed': changed[-1] = changed[-1].replace(b'release_rc=0', b'release_rc=-5')
                elif mutation == 'no-receive': changed.pop(1)
                elif mutation == 'new-capture': changed.append(changed[0].replace(b'sequence=1', b'sequence=2'))
                elif mutation == 'missing-result': changed[-1] = changed[-1].replace(b'original_result=0 expected_result=0', b'')
                (run/'console.log').write_bytes(mailbox_line() + b''.join(changed))
                with self.subTest(mutation=mutation):
                    if mutation == 'none': runner.require_capture_closed(run)
                    else:
                        with self.assertRaises(ValueError): runner.require_capture_closed(run)
            second = [line.replace(b'sequence=1', b'sequence=2') for line in lines]
            # Pending clears before the old native callback publishes its final receipt.
            interleaved = lines[:3] + second[:1] + lines[3:] + second[1:]
            (run/'console.log').write_bytes(mailbox_line() + b''.join(interleaved))
            runner.require_capture_closed(run)

    def test_current_close_receive_free_and_native_operation_are_all_required(self):
        with tempfile.TemporaryDirectory() as temporary:
            run = Path(temporary)
            for mutation in ('none', 'no-free', 'no-operation', 'wrong-epoch', 'wrong-instance', 'wrong-pid', 'wrong-request', 'failed-close', 'reversed', 'duplicate'):
                lines = native_clip()
                if mutation == 'no-free': lines.pop()
                elif mutation == 'no-operation': lines.pop(-3)
                elif mutation == 'wrong-epoch': lines[-1] = lines[-1].replace(b'epoch=1', b'epoch=2')
                elif mutation == 'wrong-instance': lines[-1] = lines[-1].replace(b'instance=0xa123', b'instance=0xa124')
                elif mutation == 'wrong-pid': lines[-1] = lines[-1].replace(b'pid=123', b'pid=124')
                elif mutation == 'wrong-request': lines[-1] = lines[-1].replace(b'request_seq=3', b'request_seq=2')
                elif mutation == 'failed-close': lines[-3] = lines[-3].replace(b'operation_error=0', b'operation_error=-5')
                elif mutation == 'reversed': lines[-1], lines[-2] = lines[-2], lines[-1]
                elif mutation == 'duplicate': lines.append(lines[-1])
                (run / 'console.log').write_bytes(mailbox_line() + b''.join(lines))
                with self.subTest(mutation=mutation):
                    if mutation == 'none': runner.require_capture_closed(run)
                    else:
                        with self.assertRaises(ValueError): runner.require_capture_closed(run)


if __name__ == '__main__':
    unittest.main()
