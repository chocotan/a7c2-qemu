#!/usr/bin/env python3
"""Synthetic host transport checks, NOT original-AP/QEMU/window FPS evidence.

Run python3 test-lcd-stream.py. The main owned integration run must separately
exercise 2..5 seconds of real AP UI activity and retain lcd-stream-*.jsonl.
"""
import hashlib
import json
import os
from pathlib import Path
import runpy
import shutil
import socket
import struct
import subprocess
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
API = runpy.run_path(str(HERE / 'lcd-stream.py'))


def ppm(epoch):
    return b'P6\n640 480\n255\n' + bytes((epoch % 255, 25, 47)) * (640 * 480)


def metadata(epoch=1, *, revision=None, nonce=b'guest-source-001', sequence=None):
    return API['SOURCE'].pack(b'LCDRAM01', 1, 128, revision or epoch * 2, nonce.ljust(16, b'!'),
        200, sequence or epoch, epoch, 0x43A7B4100,
        0x41E100000 if epoch & 1 else 0x41E300000,
        epoch * 20000000, epoch * 11, epoch * 17, epoch, 0, 0)


def performance_record(sequence=1, *, nonce=b'guest-source-001', pid=200, epoch=None):
    epoch = sequence if epoch is None else epoch
    start = sequence * 1000
    raw = API['PERFORMANCE'].pack(b'LCDPER01', 1, 128, sequence * 2, nonce,
        pid, sequence, epoch, epoch, start, start + 100, start + 200, start + 300,
        0, sequence * 2, 0)
    checksum = 14695981039346656037
    for byte in raw[:104]:
        checksum = ((checksum ^ byte) * 1099511628211) & 0xffffffffffffffff
    return raw[:104] + struct.pack('<Q', checksum) + raw[112:]


def performance_ring(sequences=(1,)):
    ring = bytearray(API['PERFORMANCE_SIZE'])
    for sequence in sequences:
        slot = (sequence - 1) % API['PERFORMANCE_SLOTS']
        ring[slot * 128:(slot + 1) * 128] = performance_record(sequence)
    return bytes(ring)


class FakeQmp:
    """Protocol fixture only; pixels are explicitly synthetic test data."""
    def __init__(self, directory, mode='idle', delay=0):
        self.directory = Path(directory)
        self.mode = mode
        self.delay = delay
        self.epoch = 1
        self.records = []
        self.errors = []
        self.connection = None
        self.query_started = threading.Event()
        self.query_release = threading.Event()
        self.listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.listener.bind(str(self.directory / 'qmp.sock'))
        self.listener.listen(1)
        self.thread = threading.Thread(target=self._run)
        self.thread.start()

    def _run(self):
        try:
            self.connection, _ = self.listener.accept()
            with self.connection.makefile('rwb') as stream:
                stream.write(b'{"QMP":{"version":{}}}\n'); stream.flush()
                for line in stream:
                    request = json.loads(line)
                    name = request['execute']
                    args = request.get('arguments', {})
                    self.records.append((name, request['id'], time.monotonic_ns()))
                    if name == 'pmemsave':
                        path = self.directory / Path(args['filename']).name
                        if str(path) != args['filename']:
                            raise ValueError('Fixture QMP output path escaped its owned directory')
                        if args['val'] == API['PERFORMANCE_ADDRESS']:
                            if args['size'] != API['PERFORMANCE_SIZE']:
                                raise ValueError('Wrong performance dump bounds')
                            raw = performance_ring((self.epoch,))
                            if self.mode == 'bad-performance':
                                raw = raw[:-1]
                            path.write_bytes(raw)
                            reply = ({'error': {'class': 'GenericError', 'desc': 'performance fixture failure'}}
                                     if self.mode == 'performance-qmp-error' else {'return': {}})
                            stream.write(json.dumps(dict(reply, id=request['id'])).encode() + b'\n')
                            stream.flush()
                            continue
                        if args['val'] != API['SOURCE_ADDRESS'] or args['size'] != 128:
                            raise ValueError('Source receipt ABI changed')
                        if path.suffix == '.before' and self.mode in ('active', 'identical-commits'):
                            self.epoch += 1
                        raw = metadata(self.epoch)
                        if self.mode == 'missing':
                            raw = bytes(128)
                        elif self.mode == 'racing' and path.suffix == '.after':
                            raw = metadata(self.epoch + 1)
                        elif self.mode == 'rollback' and path.suffix == '.before':
                            self.epoch -= 1
                            raw = metadata(self.epoch)
                        path.write_bytes(raw)
                    elif name == 'screendump':
                        if self.delay:
                            self.query_release.wait(self.delay)
                        pixels = ppm(1 if self.mode == 'identical-commits' else
                                     self.epoch + 1 if self.mode == 'uncommitted-pixels' else self.epoch)
                        (self.directory / Path(args['filename']).name).write_bytes(pixels)
                    elif name == 'query-status':
                        self.query_started.set()
                        if self.mode == 'blocking-query':
                            self.query_release.wait(3)
                    reply = {'return': {'running': True} if name == 'query-status' else {}, 'id': request['id']}
                    if self.mode == 'wrong-id' and name != 'qmp_capabilities':
                        reply['id'] = 'foreign-response'
                    stream.write(b'{"event":"DISPLAY_TEST_EVENT"}\n')
                    stream.write(json.dumps(reply).encode() + b'\n'); stream.flush()
        except (BrokenPipeError, ConnectionResetError):
            pass
        except BaseException as error:
            self.errors.append(error)

    def close(self):
        self.query_release.set()
        if self.connection is not None:
            try:
                self.connection.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
        self.listener.close()
        self.thread.join(4)
        if self.connection is not None:
            self.connection.close()
        if self.thread.is_alive():
            raise AssertionError('Fixture QMP thread did not join')
        if self.errors:
            raise self.errors[0]


class ProducerTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='lcd-stream-test-')
        self.directory = Path(self.temporary.name)
        self.fake = None
        self.producer = None

    def tearDown(self):
        if self.fake is not None:
            self.fake.query_release.set()
        if self.producer is not None:
            self.producer.stop()
        if self.fake is not None:
            self.fake.close()
        self.temporary.cleanup()

    def start(self, mode='idle', delay=0, **kwargs):
        self.fake = FakeQmp(self.directory, mode, delay)
        peer = dict(pid=os.getpid(), uid=os.getuid(), gid=os.getgid())
        peer.update(kwargs.pop('peer', {}))
        kwargs.setdefault('expected_source_nonce', b'guest-source-001'.ljust(16, b'!').hex())
        self.producer = API['start'](self.directory, 'qmp.sock', expected_peer=peer,
            qmp_output_dir=str(self.directory), **kwargs)
        return self.producer

    def until(self, predicate, seconds=2):
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            value = predicate()
            if value:
                return value
            if self.producer and self.producer.receipt()['error']:
                raise AssertionError(self.producer.receipt()['error'])
            threading.Event().wait(.005)
        self.fail('Host fixture deadline elapsed')

    def test_full_ppm_validation_and_decoded_hash(self):
        raw = ppm(1)
        self.assertEqual(API['decode_ppm'](raw), hashlib.sha256(raw[15:]).hexdigest())
        for invalid in (raw[:-1], raw + b'x', b'P6\n640 480\n256\n' + raw[15:], b'P3\n' + raw):
            with self.assertRaises(ValueError):
                API['decode_ppm'](invalid)

    def test_guest_receipt_schema_and_busy_state(self):
        self.assertEqual(API['decode_source'](metadata())['source_epoch'], 1)
        self.assertIsNone(API['decode_source'](bytes(128)))
        self.assertIsNone(API['decode_source'](metadata(revision=3)))
        for raw in (metadata()[:-1], b'OTHER001' + metadata()[8:], metadata(epoch=3, sequence=2)):
            with self.assertRaises(ValueError):
                API['decode_source'](raw)

    def test_performance_ring_hash_double_generation_wrap_and_source_binding(self):
        decode = lambda raw: API['decode_performance'](raw,
            expected_nonce=b'guest-source-001'.hex(), expected_pid=200)
        result = decode(performance_ring(range(1, 33)))
        self.assertEqual([row['sequence'] for row in result['records']], list(range(17, 33)))
        self.assertEqual(result['latest']['total_ns'], 300)
        self.assertEqual([result['latest'][name] for name in
            ('snapshot_ns', 'convert_dma_ns', 'commit_ns')], [100] * 3)
        self.assertEqual(decode(bytes(API['PERFORMANCE_SIZE']))['sample_count'], 0)
        for offset, value in ((16, 3), (112, 3), (112, 4)):
            raw = bytearray(performance_ring())
            struct.pack_into('<Q', raw, offset, value)
            self.assertEqual(decode(raw)['busy_slots'], [0])
            self.assertEqual(decode(raw)['sample_count'], 0)
        raw = bytearray(performance_ring())
        raw[80] ^= 1
        with self.assertRaisesRegex(ValueError, 'hash'):
            decode(raw)
        for raw in (performance_ring()[:-1], b'OTHER001' + performance_ring()[8:]):
            with self.assertRaises(ValueError):
                decode(raw)
        for nonce, pid in ((b'foreign-source!!'.ljust(16, b'!'), 200), (b'guest-source-001', 201)):
            with self.assertRaisesRegex(ValueError, 'nonce/pid'):
                decode(performance_record(nonce=nonce, pid=pid) + bytes(API['PERFORMANCE_SIZE'] - 128))
        raw = bytearray(performance_ring((1, 2)))
        raw[128:256] = performance_record(2, epoch=1)
        with self.assertRaisesRegex(ValueError, 'rollback'):
            decode(raw)

    def test_stop_exports_performance_once_via_owned_qmp_and_persists_decode(self):
        producer = self.start()
        self.until(lambda: producer.receipt()['transport_frames'] >= 2)
        self.assertFalse((self.directory / 'lcd-guest-performance.bin').exists())
        receipt = producer.stop()
        self.assertTrue(receipt['safe_to_quit'])
        self.assertEqual(receipt['guest_performance']['sample_count'], 1)
        self.assertEqual(receipt['guest_performance']['latest']['total_ns'], 300)
        self.assertEqual((self.directory / 'lcd-guest-performance.bin').read_bytes(), performance_ring())
        self.assertEqual(json.loads((self.directory / 'lcd-guest-performance.json').read_text()),
                         receipt['guest_performance'])
        producer.stop()
        dumps = [row for row in self.fake.records if row[0] == 'pmemsave']
        self.assertEqual(len(dumps), 2 * receipt['transport_frames'] + 1)
        self.assertEqual(self.fake.records[-1][0], 'pmemsave')

    def test_performance_failure_preserves_error_and_does_not_block_join(self):
        producer = self.start(mode='bad-performance')
        self.until(lambda: producer.receipt()['transport_frames'] >= 1)
        receipt = producer.stop()
        self.assertTrue(receipt['safe_to_quit'])
        self.assertIsNone(receipt['error'])
        self.assertIn('Truncated', receipt['guest_performance_error'])
        self.assertTrue((self.directory / 'lcd-guest-performance.bin').exists())

    def test_performance_qmp_error_retains_original_producer_error_and_joins(self):
        producer = self.start(mode='performance-qmp-error')
        self.until(lambda: producer.receipt()['transport_frames'] >= 1)
        receipt = producer.stop()
        self.assertTrue(receipt['safe_to_quit'])
        self.assertIn('QMP error', receipt['error'])
        self.assertIn('performance fixture failure', receipt['guest_performance_error'])
        self.assertEqual(receipt['state'], 'failed')

    def test_performance_json_write_error_does_not_block_release(self):
        producer = self.start()
        self.until(lambda: producer.receipt()['transport_frames'] >= 1)
        atomic = producer._atomic
        def fail_performance(name, data):
            if name == 'lcd-guest-performance.json':
                raise OSError('performance fixture write failure')
            return atomic(name, data)
        producer._atomic = fail_performance
        receipt = producer.stop()
        self.assertTrue(receipt['safe_to_quit'])
        self.assertIsNone(receipt['error'])
        self.assertIn('write failure', receipt['guest_performance_error'])
        self.assertIsNone(producer._dir)
        self.assertEqual(json.loads((self.directory / 'lcd-stream.json').read_text())['guest_performance_error'],
                         receipt['guest_performance_error'])

    def test_unbound_source_does_not_export_performance(self):
        producer = self.start(expected_source_nonce=None)
        self.until(lambda: producer.receipt()['transport_frames'] >= 1)
        receipt = producer.stop()
        self.assertTrue(receipt['safe_to_quit'])
        self.assertFalse((self.directory / 'lcd-guest-performance.bin').exists())

    def test_idle_scheduler_counts_transport_separately_and_does_not_spin(self):
        producer = self.start()
        self.until(lambda: producer.receipt()['transport_frames'] >= 7)
        receipt = producer.stop()
        self.assertGreaterEqual(receipt['interval_ms']['p50'], 40)
        self.assertLessEqual(receipt['transport_frames'], 12)
        self.assertEqual(receipt['unique_original_epochs'], 1)
        self.assertEqual(receipt['changed_original_frames'], 0)
        self.assertFalse(receipt['active_original_gt15fps_observed'])
        self.assertTrue(receipt['safe_to_quit'])
        self.assertEqual(receipt['frames_verified'], receipt['transport_frames'])
        self.assertFalse(receipt['window_presentation_verified'])
        self.assertFalse(receipt['capture_verified'])

    def test_synthetic_two_second_activity_is_transport_only(self):
        producer = self.start(mode='active')
        self.until(lambda: producer.receipt()['observed_seconds'] >= 2.05, seconds=3.5)
        receipt = producer.stop()
        self.assertGreater(receipt['transport_fps'], 15)
        self.assertGreater(receipt['changed_original_fps'], 15)
        self.assertTrue(receipt['active_original_gt15fps_observed'])
        self.assertFalse(receipt['window_presentation_verified'])
        self.assertFalse(receipt['capture_verified'])
        records = [json.loads(line) for line in next(self.directory.glob('lcd-stream-*.jsonl')).read_text().splitlines()]
        self.assertEqual(len(records), receipt['transport_frames'])
        self.assertTrue(all(a['host_verified_ns'] < b['host_verified_ns'] and
            a['source']['source_epoch'] < b['source']['source_epoch'] for a, b in zip(records, records[1:])))

    def test_atomic_latest_sidecar_and_capacity_one_slot(self):
        producer = self.start(mode='active')
        self.until(lambda: producer.receipt()['transport_frames'] >= 4)
        frame, raw = API['read_latest'](self.directory, expected_nonce=producer.nonce)
        self.assertEqual(API['decode_ppm'](raw), frame['decoded_pixel_sha256'])
        latest = producer.latest()
        self.assertIsNotNone(latest)
        self.assertEqual(API['decode_ppm'](latest[1]), latest[0]['decoded_pixel_sha256'])
        self.assertGreaterEqual(producer.receipt()['dropped_consumer_frames'], 2)
        with self.assertRaises(ValueError):
            API['read_latest'](self.directory, expected_nonce='old-stream')
        producer.stop()
        self.assertFalse(list(self.directory.glob('.lcd-*')))
        self.assertTrue((self.directory / 'live-frame.ppm').is_file())

    def test_tampered_latest_pixels_and_symlink_are_rejected(self):
        producer = self.start()
        self.until(lambda: producer.receipt()['transport_frames'] >= 1)
        producer.stop()
        (self.directory / 'live-frame.ppm').write_bytes(ppm(27))
        with self.assertRaises(ValueError):
            API['read_latest'](self.directory, expected_nonce=producer.nonce)
        (self.directory / 'live-frame.ppm').unlink()
        (self.directory / 'live-frame.ppm').symlink_to('live-frame.json')
        with self.assertRaises(OSError):
            API['read_latest'](self.directory, expected_nonce=producer.nonce)

    def test_guest_commit_during_screendump_is_dropped(self):
        producer = self.start(mode='racing')
        self.until(lambda: producer.receipt()['source_races'] >= 3)
        receipt = producer.stop()
        self.assertEqual(receipt['transport_frames'], 0)
        self.assertEqual(receipt['frames_verified'], 0)
        self.assertTrue(receipt['safe_to_quit'])

    def test_missing_guest_helper_never_counts_old_screen(self):
        (self.directory / 'live-frame.ppm').write_bytes(ppm(27))
        producer = self.start(mode='missing')
        self.until(lambda: producer.receipt()['source_not_ready'] >= 3)
        receipt = producer.stop()
        self.assertEqual(receipt['transport_frames'], 0)
        self.assertFalse(receipt['transport_gt15fps_observed'])
        self.assertFalse(any(row[0] == 'screendump' for row in self.fake.records))

    def test_source_rollback_stops_producer(self):
        producer = self.start(mode='active')
        self.until(lambda: producer.receipt()['transport_frames'] >= 3)
        self.fake.mode = 'rollback'
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline and not producer.receipt()['error']:
            threading.Event().wait(.005)
        self.assertIn('rolled back', producer.stop()['error'])

    def test_rpc_id_mismatch_preserves_outstanding_and_blocks_vm_quit(self):
        producer = self.start(mode='wrong-id')
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline and not producer.receipt()['error']:
            threading.Event().wait(.005)
        receipt = producer.stop()
        self.assertIn('ID mismatch', receipt['error'])
        self.assertIsNotNone(receipt['outstanding_qmp'])
        self.assertFalse(receipt['safe_to_quit'])

    def test_owned_rpc_is_serial_and_quit_requires_join(self):
        producer = self.start()
        peer = producer.receipt()['qmp_peer']
        self.assertEqual(peer['pid'], os.getpid())
        self.assertGreater(peer['start_ticks'], 0)
        self.assertEqual(producer.call('query-status'), {'running': True})
        with self.assertRaises(ValueError):
            producer.call('quit')
        receipt = producer.stop()
        self.assertTrue(receipt['safe_to_quit'])
        identifiers = [row[1] for row in self.fake.records]
        self.assertEqual(len(identifiers), len(set(identifiers)))
        with self.assertRaises(RuntimeError):
            producer.call('query-status')

    def test_stop_waits_for_inflight_rpc_and_does_not_disconnect_flush(self):
        producer = self.start(mode='blocking-query')
        answer = []
        caller = threading.Thread(target=lambda: answer.append(producer.call('query-status')))
        caller.start()
        try:
            self.assertTrue(self.fake.query_started.wait(2))
            with self.assertRaises(TimeoutError):
                producer.stop(timeout=.02)
            self.assertFalse(producer.receipt()['safe_to_quit'])
            self.assertEqual(producer.receipt()['outstanding_qmp']['execute'], 'query-status')
        finally:
            self.fake.query_release.set()
            caller.join(2)
        receipt = producer.stop()
        self.assertEqual(answer, [{'running': True}])
        self.assertTrue(receipt['safe_to_quit'])
        self.assertIsNone(receipt['outstanding_qmp'])

    def test_overrun_skips_deadlines_instead_of_accumulating_frames(self):
        producer = self.start(delay=.075)
        self.until(lambda: producer.receipt()['transport_frames'] >= 4)
        receipt = producer.stop()
        self.assertGreaterEqual(receipt['missed_deadlines'], 3)
        self.assertGreaterEqual(receipt['interval_ms']['p50'], 90)
        self.assertLessEqual(receipt['transport_frames'], 6)

    def test_duplicate_owner_is_refused_without_disrupting_first(self):
        producer = self.start()
        with self.assertRaises(BlockingIOError):
            API['start'](self.directory, 'qmp.sock', expected_peer=dict(pid=os.getpid(), uid=os.getuid()),
                         qmp_output_dir=str(self.directory))
        self.until(lambda: producer.receipt()['transport_frames'] >= 2)

    def test_wrong_qmp_peer_is_refused(self):
        with self.assertRaisesRegex(RuntimeError, 'peer credentials'):
            self.start(peer={'pid': os.getpid() + 100000})

    def test_repeated_pixels_with_new_epochs_are_not_active_refresh(self):
        producer = self.start(mode='identical-commits')
        self.until(lambda: producer.receipt()['unique_original_epochs'] >= 4)
        receipt = producer.stop()
        self.assertEqual(receipt['changed_original_frames'], 0)
        self.assertFalse(receipt['active_original_gt15fps_observed'])

    def test_pixels_without_original_commit_are_refused(self):
        producer = self.start()
        self.until(lambda: producer.receipt()['transport_frames'] >= 1)
        self.fake.mode = 'uncommitted-pixels'
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline and not producer.receipt()['error']:
            threading.Event().wait(.005)
        self.assertIn('without an original commit', producer.stop()['error'])

    def test_foreign_guest_startup_nonce_is_refused(self):
        producer = self.start(expected_source_nonce='00' * 16)
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline and not producer.receipt()['error']:
            threading.Event().wait(.005)
        receipt = producer.stop()
        self.assertIn('nonce differs', receipt['error'])
        self.assertEqual(receipt['transport_frames'], 0)

    def test_low_rate_and_unbound_peer_are_refused(self):
        for fps in (0, 15, 19.99, float('nan'), float('inf'), 51):
            with self.assertRaises(ValueError):
                API['start'](self.directory, 'qmp.sock', fps=fps,
                             expected_peer=dict(pid=os.getpid(), uid=os.getuid()))
        with self.assertRaises(ValueError):
            API['start'](self.directory, 'qmp.sock', expected_peer=None)

    def test_forked_owner_and_foreign_socket_are_refused(self):
        producer = self.start()
        owner = producer.owner_pid
        producer.owner_pid = owner + 1
        try:
            with self.assertRaises(RuntimeError):
                producer.receipt()
        finally:
            producer.owner_pid = owner
        with self.assertRaises(ValueError):
            API['start'](self.directory, '/foreign/qmp.sock',
                         expected_peer=dict(pid=os.getpid(), uid=os.getuid()))

    def test_passive_guest_startup_log_waits_for_complete_real_identity(self):
        log = self.directory / 'console.log'
        log.write_bytes(b'original boot\n')
        producer = self.start(source_log='console.log')
        self.until(lambda: producer.receipt()['source_not_ready'] >= 1)
        self.assertEqual(producer.receipt()['transport_frames'], 0)
        identity = ('LCD_STREAM_SOURCE nonce=' + b'guest-source-001'.ljust(16, b'!').hex() +
                    ' pid=200 receipt_phys=0x41e5ff100 period_ns=20000000')
        with log.open('ab') as output:
            output.write(identity.encode())
        self.until(lambda: producer.receipt()['source_not_ready'] >= 3)
        self.assertEqual(producer.receipt()['transport_frames'], 0)
        with log.open('ab') as output:
            output.write(b'\r\n')
        self.until(lambda: producer.receipt()['transport_frames'] >= 2)
        receipt = producer.stop()
        self.assertEqual(receipt['source_log_receipt']['guest_pid'], 200)
        self.assertTrue(receipt['source_binding_verified'])

    def test_prepared_archive_checks_final_replacement_and_refuses_official_runtime(self):
        stage = self.directory / 'stage'
        (stage / 'simulation').mkdir(parents=True)
        helper = stage / 'simulation/ramfb-viewer'
        helper.write_bytes(b'original helper')
        helper.chmod(0o755)
        archive = self.directory / 'test.cpio'
        command = ['cpio', '--null', '-o', '-H', 'newc', '--quiet', '-F', str(archive)]
        subprocess.run(command, cwd=stage, input=b'simulation/ramfb-viewer\0', check=True, timeout=5)
        self.assertEqual(API['archive_helper_digest'](archive), hashlib.sha256(helper.read_bytes()).hexdigest())
        helper.write_bytes(b'replacement LCD helper')
        subprocess.run(command + ['-A'], cwd=stage, input=b'simulation/ramfb-viewer\0', check=True, timeout=5)
        self.assertEqual(API['archive_helper_digest'](archive), hashlib.sha256(helper.read_bytes()).hexdigest())
        with self.assertRaisesRegex(ValueError, 'independent'):
            API['prepare'](HERE / 'runtime')

    def test_guest_conversion_all_65536_random_full_frames_and_ring_with_sanitizers(self):
        compiler = shutil.which('clang')
        self.assertIsNotNone(compiler)
        pinned_id = json.loads((HERE / 'runtime/native-input.json').read_text())['id']
        pinned = HERE / 'runtime/native-source-snapshots' / pinned_id / 'runtime/analysis'
        source = self.directory / 'conversion-check.c'
        source.write_text(r'''#define LCD_STREAM_TEST
#include "lcd-ramfb-stream.c"
#include <assert.h>
static unsigned char input[HOSD_PIXELS+2], expected[XRGB_BYTES+2], actual[XRGB_BYTES+2];
static struct lcd_performance ring[LCD_PERFORMANCE_SLOTS];
int main(int argc, char **argv) {
    assert(argc == 2);
    lcd_init_conversion(); lcd_init_conversion();
    uint32_t random = 0x7312abcd;
    for (unsigned frame=0; frame<5; ++frame) {
        memset(expected, 0xa5, sizeof expected); memset(actual, 0xa5, sizeof actual);
        for (unsigned i=0; i<HOSD_PIXELS/2; ++i) {
            random = random * UINT32_C(1664525) + UINT32_C(1013904223);
            uint16_t v = frame ? random >> 16 : i;
            memcpy(input+1+2*i, &v, sizeof v);
        }
        convert(input+1, expected+1); lcd_fast_convert(input+1, actual+1);
        assert(!memcmp(actual, expected, sizeof actual));
        assert(actual[0] == 0xa5 && actual[sizeof actual-1] == 0xa5);
    }
    struct lcd_receipt receipt = {.pid=200};
    memcpy(receipt.nonce, "guest-source-001", 16);
    for (unsigned seq=1; seq<=20; ++seq) {
        receipt.submissions=seq; receipt.sequence=seq+100; receipt.source_epoch=seq+100;
        lcd_record_performance(ring, &receipt, seq*1000, seq*1000+100, seq*1000+200, seq*1000+300);
    }
    assert(sizeof ring==2048 && LCD_PERFORMANCE_OFFSET==0x4ff200);
    FILE *output=fopen(argv[1], "wb"); assert(output);
    assert(fwrite(ring, 1, sizeof ring, output)==sizeof ring); assert(!fclose(output));
    return 0;
}
''')
        executable = self.directory / 'conversion-check'
        command = [compiler, '-std=gnu11', '-O2', '-Wall', '-Wextra', '-Werror',
            '-Wno-unused-function', '-fsanitize=address,undefined', '-fno-sanitize-recover=all',
            '-I' + str(pinned), '-I' + str(HERE / 'guest'), str(source), '-o', str(executable)]
        result = subprocess.run(command, capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        output = self.directory / 'guest-ring.bin'
        result = subprocess.run([str(executable), str(output)], capture_output=True, text=True, timeout=15,
            env=dict(os.environ, ASAN_OPTIONS='detect_leaks=1:halt_on_error=1', UBSAN_OPTIONS='halt_on_error=1'))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        decoded = API['decode_performance'](output.read_bytes(),
            expected_nonce=b'guest-source-001'.hex(), expected_pid=200)
        self.assertEqual([row['sequence'] for row in decoded['records']], list(range(5, 21)))
        self.assertEqual(decoded['latest']['source_epoch'], 120)
        self.assertEqual(decoded['latest']['total_ns'], 300)

    def test_guest_verified_commit_matches_pinned_and_dma_failure_keeps_owner(self):
        pinned_id = json.loads((HERE / 'runtime/native-input.json').read_text())['id']
        pinned = HERE / 'runtime/native-source-snapshots' / pinned_id / 'runtime/analysis'
        source = self.directory / 'commit-check.c'
        source.write_text(r'''#define LCD_STREAM_TEST
#include "lcd-ramfb-stream.c"
#include <assert.h>
static unsigned char frame[HOSD_BYTES], raw[HOSD_BYTES];
static _Alignas(8) unsigned char pool[RAMFB_SIZE];
struct fake_dma { unsigned mode, kicks, pauses; };
static void kick(void *ctx, uint64_t address) {
    struct fake_dma *dma=ctx; assert(address==RAMFB_BASE+RAMFB_DMA);
    ++dma->kicks; putbe(pool+RAMFB_DMA, dma->mode, 4);
}
static void pause_dma(void *ctx) { ++((struct fake_dma *)ctx)->pauses; }
static void putle(unsigned offset, uint64_t value, unsigned count) {
    for (unsigned i=0; i<count; ++i) frame[offset+i]=value>>(8*i);
}
static void seal(void) { putle(40, fnv(frame, sizeof frame, 1), 8); }
static void make_frame(uint64_t seq, uint64_t epoch, unsigned command) {
    putle(8,seq,8); putle(56,command,4); putle(108,command,4);
    putle(112,command==0x1005?command:0,2); putle(120,epoch,8); seal();
}
static int publish(const char *path) {
    int fd=open(path,O_CREAT|O_TRUNC|O_RDWR,0600); assert(fd>=0);
    size_t offset=0;
    while (offset<sizeof frame) {
        ssize_t n=write(fd,frame+offset,sizeof frame-offset); assert(n>0); offset+=n;
    }
    assert(lseek(fd,0,SEEK_SET)==0); return fd;
}
static void equal_state(const struct consumer *a, const struct consumer *b) {
    assert(!memcmp(&a->st,&b->st,sizeof a->st));
    assert(!memcmp(a->header,b->header,HOSD_HEADER) && a->pixel_hash==b->pixel_hash);
    struct stat x,y; assert(!fstat(a->fd,&x) && !fstat(b->fd,&y));
    assert(x.st_dev==y.st_dev && x.st_ino==y.st_ino);
}
int main(int argc,char **argv) {
    assert(argc==2);
    memcpy(frame,"HOSDAP02",8); putle(16,1,4); putle(20,640,4); putle(24,480,4);
    putle(28,1,4); putle(32,UINT64_C(0x43a7b4100),8); putle(48,HOSD_PIXELS,4);
    putle(52,sizeof(struct hosd_metadata),4); putle(64,0x1003,2); putle(72,1,4);
    putle(84,640,2); putle(86,480,2); putle(100,0x1002,2);
    struct consumer actual={.fd=-1}, expected={.fd=-1};
    struct fake_dma dma={0}; struct bus bus={.ctx=&dma,.kick=kick,.pause=pause_dma};
    struct stat st; const char *error=NULL;
    for (unsigned action=2; action; --action) {
        make_frame(action==2?1:2,1,action==2?0x1003:0x1005);
        int next=publish(argv[1]), reference=dup(next); assert(reference>=0);
        assert(snapshot(&actual,next,raw,&st,&error)==(int)action && !error);
        uint64_t hash=action==2?fnv(raw+HOSD_HEADER+sizeof(struct hosd_metadata),HOSD_PIXELS,0):actual.pixel_hash;
        int old_actual=actual.fd,old_expected=expected.fd;
        if (action==2) {
            uint64_t submitted=0;
            assert(!lcd_submit_commit_verified(&bus,pool,0,0x20,&actual,next,&st,raw,hash,&submitted));
            assert(submitted>0 && dma.kicks==1);
        } else lcd_commit_verified(&actual,next,&st,raw,hash);
        commit(&expected,reference,&st,raw);
        assert(actual.fd==next && expected.fd==reference); equal_state(&actual,&expected);
        if (old_actual>=0) assert(fcntl(old_actual,F_GETFD)==-1 && errno==EBADF);
        if (old_expected>=0) assert(fcntl(old_expected,F_GETFD)==-1 && errno==EBADF);
    }
    struct consumer before=actual;
    int next=open(argv[1],O_RDONLY); assert(next>=0);
    assert(snapshot(&actual,next,raw,&st,&error)==0 && !error);
    assert(!memcmp(&actual,&before,sizeof actual)); close(next);
    make_frame(3,1,0x1005); frame[HOSD_HEADER+sizeof(struct hosd_metadata)]^=1; seal();
    assert(!validate(frame,sizeof frame)); next=publish(argv[1]);
    assert(snapshot(&actual,next,raw,&st,&error)==-1 && !strcmp(error,"retained source changed"));
    assert(!memcmp(&actual,&before,sizeof actual)); close(next);
    make_frame(3,3,0x1003); next=publish(argv[1]);
    assert(snapshot(&actual,next,raw,&st,&error)==2 && !error);
    uint64_t hash=fnv(raw+HOSD_HEADER+sizeof(struct hosd_metadata),HOSD_PIXELS,0);
    for (unsigned mode=1; mode<=2; ++mode) {
        dma.mode=mode; uint64_t submitted=0;
        assert(lcd_submit_commit_verified(&bus,pool,1,0x20,&actual,next,&st,raw,hash,&submitted)==-(int)mode);
        assert(!submitted && !memcmp(&actual,&before,sizeof actual));
        assert(fcntl(actual.fd,F_GETFD)>=0 && fcntl(next,F_GETFD)>=0);
    }
    close(next); close(actual.fd); close(expected.fd); return 0;
}
''')
        executable = self.directory / 'commit-check'
        result = subprocess.run(['clang', '-std=gnu11', '-O2', '-Wall', '-Wextra', '-Werror',
            '-Wno-unused-function', '-fsanitize=address,undefined', '-fno-sanitize-recover=all',
            '-I' + str(pinned), '-I' + str(HERE / 'guest'), str(source), '-o', str(executable)],
            capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        result = subprocess.run([str(executable), str(self.directory / 'snapshot.hosd')],
            capture_output=True, text=True, timeout=15,
            env=dict(os.environ, ASAN_OPTIONS='detect_leaks=1:halt_on_error=1', UBSAN_OPTIONS='halt_on_error=1'))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_guest_receipt_abi_seqlock_and_absolute_deadline(self):
        compiler = shutil.which('cc')
        self.assertIsNotNone(compiler)
        pinned_id = json.loads((HERE / 'runtime/native-input.json').read_text())['id']
        pinned = HERE / 'runtime/native-source-snapshots' / pinned_id / 'runtime/analysis'
        source = self.directory / 'guest-check.c'
        source.write_text('#define LCD_STREAM_TEST\n#include "lcd-ramfb-stream.c"\n#include <assert.h>\n'
            'int main(void) {\n'
            '  struct lcd_receipt output={0}, receipt={.revision=2,.source_epoch=9};\n'
            '  lcd_busy(&output,1); assert(output.revision==1);\n'
            '  lcd_publish(&output,&receipt); assert(output.revision==2 && output.source_epoch==9);\n'
            '  assert(sizeof output==128); assert(LCD_RECEIPT_OFFSET==0x4ff100);\n'
            '  assert(lcd_next_deadline(100000000,100000000)==120000000);\n'
            '  assert(lcd_next_deadline(100000000,165000000)==180000000);\n'
            '  assert(lcd_now()>0); return 0; }\n')
        executable = self.directory / 'guest-check'
        result = subprocess.run([compiler, '-std=gnu11', '-O2', '-Wall', '-Wextra', '-Werror',
            '-Wno-unused-function', '-I' + str(pinned), '-I' + str(HERE / 'guest'), str(source), '-o', str(executable)],
            capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        subprocess.run([str(executable)], check=True, timeout=5)


class RamTransportBinding(unittest.TestCase):
    def test_ram_producer_viewer_and_bootstrap_must_agree(self):
        adapter=runpy.run_path(str(HERE/'lcd-ram-snapshot.py'))
        identity='a'*64
        metadata=dict(profile=API['PROFILE'],host_source_sha256=identity,source_sha256=identity,
            helper_sha256=identity,source_receipt_physical=API['SOURCE_ADDRESS'],
            performance_physical=API['PERFORMANCE_ADDRESS'],performance_bytes=API['PERFORMANCE_SIZE'],
            performance_schema=1,conversion_lookup_bytes=262144,native_snapshot='pinned')
        binding=dict(contract=adapter['receipt'](),adapter_sha256=identity,wrapper_sha256=identity,
                     bootstrap_source_sha256=identity,bootstrap_sha256=identity)
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);(root/'analysis').mkdir();path=root/'analysis/full-system.json'
            manifest={'lcd_stream':metadata,'imaging_observer':{}}
            def store():path.write_text(json.dumps(manifest))
            def load(name):
                return adapter if Path(name).name=='lcd-ram-snapshot.py' else {'resolve':lambda:Path('/pinned')}
            with patch.dict(API['validate_runtime'].__globals__,{
                    'digest':lambda _:identity,'archive_helper_digest':lambda *args:identity,
                    'runpy':type('Loader',(),{'run_path':staticmethod(load)})}):
                store();API['validate_runtime'](root,50)
                metadata['ram_snapshot']=binding;store()
                with self.assertRaisesRegex(ValueError,'producer/viewer'):API['validate_runtime'](root,50)
                manifest['imaging_observer']['lcd_ram_snapshot']=dict(binding);store()
                API['validate_runtime'](root,50)
                manifest['imaging_observer']['lcd_ram_snapshot']['contract']={**adapter['receipt'](),'producer_path':'/tmp/foreign'};store()
                with self.assertRaisesRegex(ValueError,'producer/viewer'):API['validate_runtime'](root,50)
                manifest['imaging_observer']['lcd_ram_snapshot']=dict(binding)
                metadata['ram_snapshot']={**binding,'wrapper_sha256':'b'*64};store()
                with self.assertRaisesRegex(ValueError,'bootstrap'):API['validate_runtime'](root,50)


if __name__ == '__main__':
    unittest.main(verbosity=2)
