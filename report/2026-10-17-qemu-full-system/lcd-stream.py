#!/usr/bin/env python3
"""Original ramfb -> owned QMP -> one latest, atomic PPM; no camera claims.

start(run_dir, 'qmp.sock', fps=20, expected_peer={'pid': qemu_pid, 'uid': uid})
requires an unoccupied QMP listener and guest/lcd-ramfb-stream.c in place of the
100 ms viewer. Route other QMP requests through producer.call(), then stop()
and check safe_to_quit before reconnecting for normal VM quit. The producer
never sends quit, stop, cont, input, guest ACKs, or filesystem flush commands.
"""
import concurrent.futures
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import queue
import re
import secrets
import shutil
import runpy
import subprocess
import tempfile
import socket
import stat
import struct
import threading
import time
from collections import deque

HERE = Path(__file__).resolve().parent
PROFILE = 'original-ramfb-20ms-v1'
SOURCE_ADDRESS = 0x41E5FF100
SOURCE_SIZE = 128
SOURCE = struct.Struct('<8sIIQ16s11Q')
# Separate from the unchanged 128B source receipt and fw_cfg DMA/config.
# 16 x 128B LE records: magic/version/size/head generation/nonce, then pid,
# sample sequence/source sequence/epoch, four monotonic ns timestamps,
# FNV-1a of bytes [0,104), tail generation, reserved zero. No per-frame QMP.
PERFORMANCE_ADDRESS = 0x41E5FF200
PERFORMANCE_SLOTS = 16
PERFORMANCE = struct.Struct('<8sIIQ16s11Q')
PERFORMANCE_SIZE = PERFORMANCE.size * PERFORMANCE_SLOTS
PPM_HEADER = re.compile(rb'P6\s+(640)\s+(480)\s+(255)(?:\r\n|[ \t\r\n])')
PIXEL_BYTES = 640 * 480 * 3


def decode_ppm(raw):
    """Validate the complete QMP P6 frame, hash decoded RGB, never just mtime."""
    header = PPM_HEADER.match(raw)
    if header is None or len(raw) != header.end() + PIXEL_BYTES:
        raise ValueError('Expected complete 640x480 8-bit QMP P6 pixels')
    return hashlib.sha256(memoryview(raw)[header.end():]).hexdigest()


def decode_source(raw):
    if len(raw) != SOURCE_SIZE:
        raise ValueError('Truncated LCD source receipt')
    magic, version, size, revision, nonce, *values = SOURCE.unpack(raw)
    if raw == bytes(SOURCE_SIZE) or revision & 1:
        return None
    if magic != b'LCDRAM01' or version != 1 or size != SOURCE_SIZE or not any(nonce):
        raise ValueError('Wrong LCD source identity/schema')
    pid, sequence, epoch, physical, scanout, committed, pixel_fnv, container_fnv, commits, rejects, reserved = values
    if (not revision or not pid or not sequence or not epoch or epoch > sequence or
            not committed or not commits or reserved or
            not 0x410000000 <= physical <= 0x500000000 - 640 * 480 * 2 or
            scanout not in (0x41E100000, 0x41E300000)):
        raise ValueError('Invalid original LCD epoch/scanout/bounds')
    return dict(revision=revision, nonce=nonce.hex(), guest_pid=pid,
                sequence=sequence, source_epoch=epoch, source_physical=physical,
                scanout_physical=scanout, guest_committed_ns=committed,
                original_pixel_fnv64=f'{pixel_fnv:016x}',
                original_container_fnv64=f'{container_fnv:016x}',
                guest_submissions=commits, guest_rejections=rejects)


def decode_performance(raw, *, expected_nonce, expected_pid):
    """Decode one bounded live RAM dump; busy slots are not completed samples.

    Head/tail generations and the complete payload hash reject torn slots.
    Only action=2 frames are recorded; retained/idle/rejected frames never add
    samples. This ring measures guest stages, not click-to-LCD/window latency.
    """
    if len(raw) != PERFORMANCE_SIZE:
        raise ValueError('Truncated LCD performance ring')
    if (not isinstance(expected_nonce, str) or not re.fullmatch('[0-9a-f]{32}', expected_nonce) or
            expected_nonce == '00' * 16 or type(expected_pid) is not int or expected_pid <= 0):
        raise ValueError('LCD performance requires bound source nonce/pid')
    records, busy = [], []
    for slot in range(PERFORMANCE_SLOTS):
        data = raw[slot * PERFORMANCE.size:(slot + 1) * PERFORMANCE.size]
        if data == bytes(PERFORMANCE.size):
            continue
        magic, version, size, generation, nonce, *values = PERFORMANCE.unpack(data)
        pid, sequence, source_sequence, epoch, start, snapshot, converted, committed, checksum, end, reserved = values
        if generation & 1 or end & 1 or generation != end:
            busy.append(slot)
            continue
        if (magic != b'LCDPER01' or version != 1 or size != PERFORMANCE.size or reserved or
                not sequence or generation != sequence * 2 or (sequence - 1) % PERFORMANCE_SLOTS != slot or
                not epoch or epoch > source_sequence or not 0 < start <= snapshot <= converted <= committed):
            raise ValueError('Invalid LCD performance schema/generation/timestamps')
        computed = 14695981039346656037
        for byte in data[:104]:
            computed = ((computed ^ byte) * 1099511628211) & 0xffffffffffffffff
        if computed != checksum:
            raise ValueError('LCD performance payload hash differs')
        if nonce.hex() != expected_nonce or pid != expected_pid:
            raise ValueError('LCD performance source nonce/pid differs')
        records.append(dict(sequence=sequence, generation=generation, source_sequence=source_sequence,
            source_epoch=epoch, snapshot_start_ns=start, after_snapshot_ns=snapshot,
            after_convert_dma_ns=converted, after_commit_ns=committed,
            snapshot_ns=snapshot - start, convert_dma_ns=converted - snapshot,
            commit_ns=committed - converted, total_ns=committed - start,
            record_fnv64=f'{checksum:016x}'))
    records.sort(key=lambda record: record['sequence'])
    for previous, current in zip(records, records[1:]):
        if (current['source_sequence'] <= previous['source_sequence'] or
                current['source_epoch'] <= previous['source_epoch'] or
                current['snapshot_start_ns'] < previous['after_commit_ns']):
            raise ValueError('LCD performance source/time rollback')
    return dict(schema=1, guest_nonce=expected_nonce, guest_pid=expected_pid,
        metadata_physical=PERFORMANCE_ADDRESS, bytes=PERFORMANCE_SIZE, capacity=PERFORMANCE_SLOTS,
        clock='guest CLOCK_MONOTONIC', scope='guest new-pixel snapshot/convert-DMA/commit only',
        sample_count=len(records), busy_slots=busy, records=records,
        latest=records[-1] if records else None)


def qmp_identity(sock):
    """Read credentials/start time from an existing socket; caller verifies VM lineage."""
    pid, uid, gid = struct.unpack('3i', sock.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12))
    if pid <= 0:
        raise ValueError('QMP peer has no host process identity')
    fields = Path(f'/proc/{pid}/stat').read_text().rsplit(')', 1)[1].split()
    return dict(pid=pid, uid=uid, gid=gid, start_ticks=int(fields[19]))


def _percentiles(values):
    ordered = sorted(values)
    return {name: ordered[max(0, math.ceil(len(ordered) * fraction) - 1)] if ordered else None
            for name, fraction in (('p50', .5), ('p95', .95))}


def _read_at(directory, name, maximum):
    fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
    try:
        info = os.fstat(fd)
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or
                info.st_nlink != 1 or info.st_size > maximum):
            raise ValueError('Unsafe or oversized LCD file: ' + name)
        parts = bytearray()
        while len(parts) <= maximum:
            chunk = os.read(fd, min(65536, maximum + 1 - len(parts)))
            if not chunk:
                break
            parts.extend(chunk)
        if len(parts) > maximum:
            raise ValueError('Oversized LCD file: ' + name)
        return bytes(parts)
    finally:
        os.close(fd)


def read_latest(run_dir, *, expected_nonce):
    """File consumers verify the sidecar on both sides of the decoded frame."""
    directory = os.open(run_dir, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        first = _read_at(directory, 'live-frame.json', 16384)
        metadata = json.loads(first)
        if metadata['stream_nonce'] != expected_nonce:
            raise ValueError('Frame belongs to another LCD producer')
        raw = _read_at(directory, 'live-frame.ppm', PIXEL_BYTES + 64)
        second = _read_at(directory, 'live-frame.json', 16384)
        if first != second or decode_ppm(raw) != metadata['decoded_pixel_sha256']:
            raise ValueError('LCD publication changed during read; retry latest frame')
        return metadata, raw
    finally:
        os.close(directory)


def digest(path):
    with Path(path).open('rb') as source:
        return hashlib.file_digest(source, 'sha256').hexdigest()


def archive_helper_digest(archive, member='simulation/ramfb-viewer'):
    """Read the last helper entry as the kernel does after an explicit cpio append."""
    found = None
    with Path(archive).open('rb') as stream:
        while True:
            header = stream.read(110)
            if len(header) != 110 or header[:6] != b'070701':
                raise ValueError('Invalid prepared newc archive')
            fields = [int(header[i:i+8], 16) for i in range(6, 110, 8)]
            length, namesize = fields[6], fields[11]
            if not 1 <= namesize <= 4096:
                raise ValueError('Invalid prepared archive name')
            name = stream.read(namesize)
            if len(name) != namesize or name[-1:] != b'\0':
                raise ValueError('Truncated prepared archive name')
            stream.seek(-(110 + namesize) % 4, os.SEEK_CUR)
            if name == b'TRAILER!!!\0':
                break
            if name.rstrip(b'\0').removeprefix(b'./') == member.encode('ascii'):
                if not stat.S_ISREG(fields[1]) or length > 1024 * 1024:
                    raise ValueError('Invalid archived ramfb helper')
                data = stream.read(length)
                if len(data) != length:
                    raise ValueError('Truncated archived ramfb helper')
                found = hashlib.sha256(data).hexdigest()
            else:
                stream.seek(length, os.SEEK_CUR)
            stream.seek(-length % 4, os.SEEK_CUR)
    if found is None:
        raise ValueError('Prepared archive has no ramfb helper')
    return found


def validate_runtime(runtime, fps):
    runtime = Path(runtime)
    if not math.isfinite(fps) or (fps != 0 and not 20 <= fps <= 50):
        raise ValueError('LCD stream fps must be 0 (legacy) or 20..50')
    if fps == 0:
        return None
    manifest = json.loads((runtime / 'analysis/full-system.json').read_text())
    metadata = manifest.get('lcd_stream')
    if not isinstance(metadata, dict) or metadata.get('profile') != PROFILE:
        raise ValueError('LCD streaming requires an independently prepared LCD runtime')
    if (metadata.get('host_source_sha256') != digest(HERE / 'lcd-stream.py') or
            metadata.get('source_sha256') != digest(HERE / 'guest/lcd-ramfb-stream.c') or
            metadata.get('helper_sha256') != digest(runtime / 'analysis/root/simulation/ramfb-viewer') or
            metadata.get('source_receipt_physical') != SOURCE_ADDRESS or
            metadata.get('performance_physical') != PERFORMANCE_ADDRESS or
            metadata.get('performance_bytes') != PERFORMANCE_SIZE or
            metadata.get('performance_schema') != 1 or metadata.get('conversion_lookup_bytes') != 262144 or
            metadata.get('native_snapshot') != runpy.run_path(str(HERE / 'native-input.py'))['resolve']().name):
        raise ValueError('LCD helper/source/pinned ABI identity differs from preparation')
    if metadata['helper_sha256'] != archive_helper_digest(runtime / 'analysis/full-system.cpio'):
        raise ValueError('LCD initramfs contains another ramfb helper')
    ram = metadata.get('ram_snapshot')
    observer_ram = manifest.get('imaging_observer', {}).get('lcd_ram_snapshot')
    if ram is not None or observer_ram is not None:
        adapter = runpy.run_path(str(HERE/'lcd-ram-snapshot.py'))
        expected = adapter['receipt']()
        if (not isinstance(ram, dict) or not isinstance(observer_ram, dict) or
                ram.get('contract') != expected or observer_ram.get('contract') != expected or
                ram.get('adapter_sha256') != digest(HERE/'lcd-ram-snapshot.py') or
                observer_ram.get('adapter_sha256') != ram['adapter_sha256']):
            raise ValueError('LCD RAM producer/viewer paths or adapter identity differ')
        wrapper = runtime/'analysis/root/simulation/bootin-wrapper'
        if (digest(wrapper) != ram.get('wrapper_sha256') or
                archive_helper_digest(runtime/'analysis/full-system.cpio', 'simulation/bootin-wrapper') != ram['wrapper_sha256']):
            raise ValueError('LCD RAM bootstrap differs between root and initramfs')
        if (ram.get('bootstrap_source_sha256') != digest(HERE/'guest/lcd-ram-bootstrap.c') or
                ram.get('bootstrap_sha256') != digest(runtime/'analysis/root/simulation/lcd-ram-bootstrap') or
                archive_helper_digest(runtime/'analysis/full-system.cpio', 'simulation/lcd-ram-bootstrap') != ram['bootstrap_sha256']):
            raise ValueError('LCD RAM native bootstrap program identity differs')
    return metadata


def prepare(runtime, source=HERE, *, ram_snapshot=False):
    """Build into an existing independent scratch copy, including a mailbox copy.

    This never clones or touches the official runtime, boot wrapper, original AP,
    partitions, board adapter or mailbox. Append the replacement to a temporary
    copy of the existing archive, verify its final entry, then publish identities.
    """
    runtime, source = Path(runtime).resolve(strict=True), Path(source).resolve(strict=True)
    scratch = (HERE.parents[1] / 'analysis/scratch').resolve()
    if runtime == scratch or not runtime.is_relative_to(scratch):
        raise ValueError('LCD preparation requires an independent analysis/scratch runtime copy')
    analysis = runtime / 'analysis'
    with runpy.run_path(str(source / 'runtime-lock.py'))['open_runtime_lock'](runtime):
        manifest_path = analysis / 'full-system.json'
        manifest = json.loads(manifest_path.read_text())
        if 'lcd_stream' in manifest:
            raise ValueError('LCD runtime is already prepared')
        archive = analysis / 'full-system.cpio'
        helper = analysis / 'root/simulation/ramfb-viewer'
        if helper.is_symlink() or archive.is_symlink() or helper.stat().st_nlink != 1 or archive.stat().st_nlink != 1:
            raise ValueError('LCD preparation refuses linked/shared writable artifacts')
        if digest(archive) != manifest['initrd_sha256'] or digest(analysis / 'qemu-kernel-probe.sh') != manifest['board_adapter_sha256']:
            raise ValueError('Parent runtime identity differs from its manifest')
        if type(ram_snapshot) is not bool:
            raise ValueError('LCD RAM snapshot selection must be explicit bool')
        ram_api = runpy.run_path(str(source/'lcd-ram-snapshot.py')) if ram_snapshot else None
        observer_ram = manifest.get('imaging_observer', {}).get('lcd_ram_snapshot')
        if ram_snapshot != (observer_ram is not None):
            raise ValueError('LCD RAM viewer requires the same prepared producer path')
        if ram_snapshot and (observer_ram.get('contract') != ram_api['receipt']() or
                observer_ram.get('adapter_sha256') != digest(source/'lcd-ram-snapshot.py')):
            raise ValueError('LCD RAM producer adapter binding differs')
        parent_helper = digest(helper)
        if archive_helper_digest(archive) != parent_helper:
            raise ValueError('Parent ramfb helper differs between root and initramfs')
        native = runpy.run_path(str(source / 'native-input.py'))['resolve']()
        pinned = native / 'runtime/analysis'
        lib = source / 'runtime/analysis/root/lib'
        libraries = [lib / name for name in ('libc-2.25.so', 'libdl-2.25.so', 'libpthread-2.25.so', 'ld-2.25.so')]
        with tempfile.TemporaryDirectory(prefix='lcd-prepare-', dir=analysis) as temporary:
            stage = Path(temporary)
            program = stage / 'simulation/ramfb-viewer'
            program.parent.mkdir()
            guest_source = source/'guest/lcd-ramfb-stream.c'
            wrapper = analysis/'root/simulation/bootin-wrapper'
            if ram_snapshot:
                derived_source = stage/'lcd-ramfb-stream.c'
                derived_source.write_text(ram_api['viewer_source'](guest_source.read_text()))
                guest_source = derived_source
                if (wrapper.is_symlink() or wrapper.stat().st_nlink != 1 or
                        archive_helper_digest(archive, 'simulation/bootin-wrapper') != digest(wrapper)):
                    raise ValueError('LCD RAM wrapper source differs from its archive')
                next_wrapper = stage/'simulation/bootin-wrapper'
                next_wrapper.write_text(ram_api['wrapper_source'](wrapper.read_text()))
                next_wrapper.chmod(0o755)
            command = ['clang', '--target=aarch64-linux-gnu', '--sysroot=/usr/aarch64-linux-gnu',
                '-fuse-ld=lld', '-nostdlib', '-O2', '-mno-outline-atomics', '-Wl,--no-undefined',
                '-Wall', '-Wextra', '-Werror', '-Wno-unused-function', '-Wl,-e,_start',
                '-Wl,--dynamic-linker=/lib/ld-linux-aarch64.so.1', '-I' + str(pinned),
                *([ram_api['COMPILE_DEFINE']] if ram_snapshot else []),
                str(guest_source), *map(str, libraries), '-o', str(program)]
            subprocess.run(command, check=True, timeout=30)
            program.chmod(0o755)
            if ram_snapshot:
                bootstrap_source = source/'guest/lcd-ram-bootstrap.c'
                bootstrap = stage/'simulation/lcd-ram-bootstrap'
                bootstrap_command = [str(bootstrap_source) if arg == str(guest_source) else
                                     str(bootstrap) if arg == str(program) else arg for arg in command]
                bootstrap_command += ['-I'+str(source)]
                subprocess.run(bootstrap_command, check=True, timeout=30)
                bootstrap.chmod(0o755)
            next_archive = stage / 'full-system.cpio'
            subprocess.run(['cp', '--reflink=auto', '--sparse=always', str(archive), str(next_archive)], check=True, timeout=55)
            members = b'simulation/ramfb-viewer\0' + (b'simulation/bootin-wrapper\0simulation/lcd-ram-bootstrap\0' if ram_snapshot else b'')
            subprocess.run(['cpio', '--null', '-o', '-A', '-H', 'newc', '--quiet', '-F', str(next_archive)],
                cwd=stage, input=members, check=True, timeout=30)
            program_sha = digest(program)
            if archive_helper_digest(next_archive) != program_sha:
                raise ValueError('Derived LCD helper readback differs inside initramfs')
            metadata = dict(profile=PROFILE, source_receipt_physical=SOURCE_ADDRESS,
                performance_physical=PERFORMANCE_ADDRESS, performance_bytes=PERFORMANCE_SIZE,
                performance_schema=1, conversion_lookup_bytes=262144,
                guest_period_ns=20000000, source_sha256=digest(source / 'guest/lcd-ramfb-stream.c'),
                host_source_sha256=digest(source / 'lcd-stream.py'), helper_sha256=program_sha,
                parent_helper_sha256=parent_helper, parent_initrd_sha256=manifest['initrd_sha256'],
                native_snapshot=native.name,
                pinned_sources={name: digest(pinned / name) for name in ('ramfb-viewer.c', 'headless-osd.h')},
                libraries={path.name: digest(path) for path in libraries},
                scope='display transport only; original AP, boot wrapper and HOSDAP02 unchanged')
            if ram_snapshot:
                wrapper_sha = digest(next_wrapper)
                if archive_helper_digest(next_archive, 'simulation/bootin-wrapper') != wrapper_sha:
                    raise ValueError('LCD RAM bootstrap readback differs in initramfs')
                bootstrap_sha = digest(bootstrap)
                if archive_helper_digest(next_archive, 'simulation/lcd-ram-bootstrap') != bootstrap_sha:
                    raise ValueError('LCD RAM native bootstrap readback differs in initramfs')
                metadata['ram_snapshot'] = dict(contract=ram_api['receipt'](),
                    bootstrap_source_sha256=digest(bootstrap_source), bootstrap_sha256=bootstrap_sha,
                    adapter_sha256=digest(source/'lcd-ram-snapshot.py'),
                    viewer_derived_source_sha256=digest(guest_source), wrapper_sha256=wrapper_sha,
                    parent_wrapper_sha256=digest(wrapper))
                metadata['scope'] = 'paired guest RAM display transport and diagnostics; original AP and HOSDAP02 unchanged'
                manifest.setdefault('derived_files', {})['simulation/bootin-wrapper'] = wrapper_sha
            manifest['lcd_stream'] = metadata
            manifest['initrd_sha256'] = digest(next_archive)
            manifest.setdefault('derived_files', {})['simulation/ramfb-viewer'] = program_sha
            next_manifest = stage / 'full-system.json'
            next_manifest.write_text(json.dumps(manifest, indent=2) + '\n')
            program.replace(helper)
            if ram_snapshot:
                next_wrapper.replace(wrapper)
                bootstrap.replace(analysis/'root/simulation/lcd-ram-bootstrap')
            next_archive.replace(archive)
            next_manifest.replace(manifest_path)
            return metadata


class Producer:
    def __init__(self, run_dir, qmp_socket, *, fps, expected_peer, expected_source_nonce, source_log, qmp_output_dir, timeout):
        if not math.isfinite(fps) or not 20 <= fps <= 50:
            raise ValueError('LCD transport fps must be in 20..50 (20..50 ms period)')
        if (not isinstance(expected_peer, dict) or type(expected_peer.get('pid')) is not int or
                expected_peer['pid'] <= 0 or type(expected_peer.get('uid')) is not int or
                expected_peer['uid'] != os.getuid()):
            raise ValueError('An explicit QEMU peer pid and current uid are required')
        if not math.isfinite(timeout) or timeout <= 0:
            raise ValueError('QMP timeout must be finite and positive')
        if not isinstance(qmp_output_dir, str) or not qmp_output_dir.startswith('/'):
            raise ValueError('QMP output directory must be absolute inside the QEMU sandbox')
        self.owner_pid = os.getpid()
        self.run_dir = Path(run_dir).absolute()
        path = Path(qmp_socket)
        if path.name in ('', '.', '..') or (path.parent != Path('.') and path.absolute().parent != self.run_dir):
            raise ValueError('QMP socket must belong to the exact run directory')
        self.socket_name = path.name
        self.expected_peer = dict(expected_peer)
        if expected_source_nonce is not None and (not isinstance(expected_source_nonce, str) or
                not re.fullmatch('[0-9a-f]{32}', expected_source_nonce)):
            raise ValueError('Expected guest source nonce must be 16 bytes of lowercase hex')
        self.expected_source_nonce = expected_source_nonce
        if source_log not in (None, 'console.log'):
            raise ValueError('Guest source identity must come from this run console.log')
        self.source_log = source_log
        self._source_log_offset = 0
        self._source_log_tail = b''
        self._source_log_inode = None
        self._expected_guest_pid = None
        self.output_dir = qmp_output_dir.rstrip('/')
        self.timeout = timeout
        self.period = 1 / fps
        self.nonce = secrets.token_hex(16)
        self.prefix = '.lcd-' + self.nonce
        self._mutex = threading.Lock()
        self._wake = threading.Event()
        self._ready = threading.Event()
        self._stopping = False
        self._requests = queue.Queue(maxsize=8)
        self._latest = None
        self._times = deque(maxlen=4096)
        self._latencies = deque(maxlen=4096)
        self._source = None
        self._performance_attempted = False
        self._last_hash = None
        self._first_ns = self._last_ns = None
        self._outstanding = None
        self._socket = None
        self._stream = None
        self._request_id = 0
        self._thread = None
        self._dir = self._lock = self._journal = None
        self._state = dict(schema=1, stream_nonce=self.nonce, owner_pid=self.owner_pid,
            state='starting', target_fps=fps, period_ms=1000 / fps,
            transport_frames=0, unique_original_epochs=0, changed_original_frames=0,
            source_epoch_gaps=0, missed_deadlines=0, source_races=0, source_not_ready=0,
            dropped_consumer_frames=0, frames_verified=0, error=None,
            source_identity=None, qmp_peer=None, producer_joined=False,
            source_binding_verified=False, producer_cpu_seconds=0,
            evidence_scope='display-transport-only',
            window_presentation_verified=False, capture_verified=False)
        try:
            self._dir = os.open(self.run_dir, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            info = os.fstat(self._dir)
            if info.st_uid != os.getuid() or info.st_mode & 0o022:
                raise ValueError('Run directory must be owned and not writable by other users')
            self._state['run_directory_identity'] = dict(device=info.st_dev, inode=info.st_ino)
            self._lock = os.open('lcd-stream.lock', os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW | os.O_NONBLOCK,
                                 0o600, dir_fd=self._dir)
            lock_info = os.fstat(self._lock)
            if (not stat.S_ISREG(lock_info.st_mode) or lock_info.st_uid != os.getuid() or
                    lock_info.st_nlink != 1):
                raise ValueError('Unsafe LCD producer lock')
            fcntl.flock(self._lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            self._journal = os.open('lcd-stream-' + self.nonce + '.jsonl',
                os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600, dir_fd=self._dir)
            for suffix in ('.before', '.after', '.ppm'):
                fd = os.open(self.prefix + suffix, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW,
                             0o600, dir_fd=self._dir)
                os.close(fd)
            self._thread = threading.Thread(target=self._run, name='original-lcd-' + self.nonce[:8], daemon=False)
            self._thread.start()
            if not self._ready.wait(timeout + 1):
                raise TimeoutError('LCD QMP producer did not become ready')
            if self._state['error']:
                raise RuntimeError(self._state['error'])
        except BaseException:
            if self._thread is not None:
                self.stop(timeout=timeout + 1)
            else:
                self._close_files()
            raise

    def _owner(self):
        if os.getpid() != self.owner_pid:
            raise RuntimeError('LCD producer cannot be used by a different/forked owner')

    def _atomic(self, name, data):
        temporary = self.prefix + '.publish'
        fd = os.open(temporary, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW,
                     0o600, dir_fd=self._dir)
        try:
            view = memoryview(data)
            while view:
                count = os.write(fd, view)
                if count <= 0:
                    raise OSError('Short LCD publication write')
                view = view[count:]
        finally:
            os.close(fd)
        os.replace(temporary, name, src_dir_fd=self._dir, dst_dir_fd=self._dir)

    def _connect(self):
        before = os.stat(self.socket_name, dir_fd=self._dir, follow_symlinks=False)
        if not stat.S_ISSOCK(before.st_mode) or before.st_uid != self.expected_peer['uid']:
            raise ValueError('QMP endpoint is not the owned socket')
        self._socket = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self._socket.settimeout(self.timeout)
        self._socket.connect(f'/proc/self/fd/{self._dir}/{self.socket_name}')
        peer = qmp_identity(self._socket)
        if any(peer[key] != self.expected_peer[key] for key in
                ('pid', 'uid', 'gid', 'start_ticks') if key in self.expected_peer):
            raise ValueError('QMP peer credentials differ from the expected VM owner')
        after = os.stat(self.socket_name, dir_fd=self._dir, follow_symlinks=False)
        if (before.st_dev, before.st_ino) != (after.st_dev, after.st_ino):
            raise ValueError('QMP socket changed while connecting')
        self._state['qmp_peer'] = peer
        self._stream = self._socket.makefile('rb')
        if 'QMP' not in self._reply():
            raise ValueError('Invalid QMP greeting')
        self._rpc('qmp_capabilities')

    def _reply(self):
        line = self._stream.readline(1024 * 1024 + 1)
        if not line or len(line) > 1024 * 1024 or not line.endswith(b'\n'):
            raise ValueError('Invalid/truncated QMP reply')
        value = json.loads(line)
        if not isinstance(value, dict):
            raise ValueError('QMP reply must be an object')
        return value

    def _rpc(self, name, arguments=None):
        self._request_id += 1
        request = dict(execute=name, id=self.nonce + '-' + str(self._request_id))
        if arguments is not None:
            request['arguments'] = arguments
        with self._mutex:
            self._outstanding = dict(id=request['id'], execute=name)
        self._socket.sendall(json.dumps(request).encode('ascii') + b'\n')
        deadline = time.monotonic() + self.timeout
        while True:
            self._socket.settimeout(max(.001, deadline - time.monotonic()))
            reply = self._reply()
            if 'event' in reply:
                if time.monotonic() >= deadline:
                    raise TimeoutError('QMP response deadline elapsed')
                continue
            if reply.get('id') != request['id']:
                raise ValueError('QMP response ID mismatch')
            with self._mutex:
                self._outstanding = None
            if 'error' in reply:
                raise RuntimeError('QMP error: ' + json.dumps(reply['error']))
            if 'return' not in reply:
                raise ValueError('QMP response has no return value')
            return reply['return']

    def _metadata(self, suffix):
        name = self.prefix + suffix
        self._rpc('pmemsave', dict(val=SOURCE_ADDRESS, size=SOURCE_SIZE,
                                  filename=self.output_dir + '/' + name))
        raw = _read_at(self._dir, name, SOURCE_SIZE)
        return raw, decode_source(raw)

    def _observe_source(self):
        if self.source_log is None:
            return True
        fd = os.open(self.source_log, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=self._dir)
        try:
            info = os.fstat(fd)
            identity = (info.st_dev, info.st_ino)
            if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_nlink != 1 or
                    (self._source_log_inode is not None and identity != self._source_log_inode) or
                    info.st_size < self._source_log_offset):
                raise ValueError('Guest source console identity changed')
            self._source_log_inode = identity
            chunk = os.pread(fd, 65536, self._source_log_offset)
        finally:
            os.close(fd)
        data = self._source_log_tail + chunk
        self._source_log_offset += len(chunk)
        complete, separator, tail = data.rpartition(b'\n')
        if separator:
            pattern = rb'(?:^|\n)LCD_STREAM_SOURCE nonce=([0-9a-f]{32}) pid=([0-9]+) receipt_phys=0x41e5ff100 period_ns=20000000\r?(?:\n|$)'
            for match in re.finditer(pattern, complete):
                nonce, pid = match[1].decode('ascii'), int(match[2])
                if ((self.expected_source_nonce is not None and nonce != self.expected_source_nonce) or
                        (self._expected_guest_pid is not None and pid != self._expected_guest_pid)):
                    raise ValueError('Guest startup source identity changed')
                self.expected_source_nonce, self._expected_guest_pid = nonce, pid
                with self._mutex:
                    self._state['source_log_receipt'] = dict(nonce=nonce, guest_pid=pid,
                        host_observed_ns=time.monotonic_ns(), raw_hex=match[0].hex())
            self._source_log_tail = tail[-512:]
        else:
            self._source_log_tail = data[-512:]
        return self._expected_guest_pid is not None

    def _capture(self):
        started = time.monotonic_ns()
        if not self._observe_source():
            with self._mutex:
                self._state['source_not_ready'] += 1
            return
        before, source = self._metadata('.before')
        if source is None:
            with self._mutex:
                self._state['source_not_ready'] += 1
            return
        self._rpc('screendump', dict(filename=self.output_dir + '/' + self.prefix + '.ppm'))
        after, second = self._metadata('.after')
        if second is None or before != after:
            with self._mutex:
                self._state['source_races'] += 1
            return
        if ((self.expected_source_nonce is not None and source['nonce'] != self.expected_source_nonce) or
                (self._expected_guest_pid is not None and source['guest_pid'] != self._expected_guest_pid)):
            raise ValueError('Original ramfb nonce differs from the current guest startup receipt')
        raw = _read_at(self._dir, self.prefix + '.ppm', PIXEL_BYTES + 64)
        pixel_hash = decode_ppm(raw)
        identity = dict(kind='original-HOSDAP02-ramfb-DMA', guest_nonce=source['nonce'],
                        guest_pid=source['guest_pid'], metadata_physical=SOURCE_ADDRESS)
        previous = self._source
        if previous is not None:
            if source['nonce'] != previous['nonce'] or source['guest_pid'] != previous['guest_pid']:
                raise ValueError('Original ramfb source restarted; refusing mixed identities')
            for field in ('revision', 'sequence', 'source_epoch', 'guest_committed_ns', 'guest_submissions'):
                if source[field] < previous[field]:
                    raise ValueError('Original ramfb source rolled back: ' + field)
            if source['source_epoch'] == previous['source_epoch']:
                if (pixel_hash != self._last_hash or any(source[k] != previous[k] for k in
                        ('source_physical', 'scanout_physical', 'original_pixel_fnv64'))):
                    raise ValueError('Pixels/source changed without an original commit epoch')
        now = time.monotonic_ns()
        new_epoch = previous is None or source['source_epoch'] > previous['source_epoch']
        new_pixels = previous is not None and new_epoch and pixel_hash != self._last_hash
        with self._mutex:
            sequence = self._state['transport_frames'] + 1
        frame = dict(stream_nonce=self.nonce, transport_sequence=sequence,
            host_capture_started_ns=started, host_verified_ns=now,
            decoded_pixel_sha256=pixel_hash, width=640, height=480, pixel_format='RGB8',
            new_original_epoch=new_epoch, changed_original_pixels=new_pixels,
            source_identity=identity, source=source)
        self._atomic('live-frame.ppm', raw)
        frame['host_published_ns'] = time.monotonic_ns()
        self._atomic('live-frame.json', json.dumps(frame, separators=(',', ':')).encode() + b'\n')
        record = json.dumps(frame, separators=(',', ':')).encode() + b'\n'
        if os.write(self._journal, record) != len(record):
            raise OSError('Short LCD timing journal write')
        with self._mutex:
            if self._latest is not None:
                self._state['dropped_consumer_frames'] += 1
            self._latest = (frame, raw)
            if self._last_ns is not None:
                self._times.append((now - self._last_ns) / 1e6)
            self._latencies.append((now - started) / 1e6)
            self._first_ns = now if self._first_ns is None else self._first_ns
            self._last_ns = now
            self._state['transport_frames'] = sequence
            self._state['frames_verified'] += 1
            self._state['unique_original_epochs'] += int(new_epoch)
            self._state['changed_original_frames'] += int(new_pixels)
            if previous is not None and new_epoch:
                self._state['source_epoch_gaps'] += max(0, source['source_epoch'] - previous['source_epoch'] - 1)
            self._state['source_identity'] = identity
            self._state['source_binding_verified'] = self.expected_source_nonce is not None
            self._state['source_epoch'] = source['source_epoch']
            self._state['decoded_pixel_sha256'] = pixel_hash
            self._source = source
            self._last_hash = pixel_hash

    def _run(self):
        cpu_start = time.thread_time()
        try:
            self._connect()
            with self._mutex:
                self._state['state'] = 'running'
            self._ready.set()
            deadline = time.monotonic()
            while True:
                self._wake.clear()
                try:
                    request = self._requests.get_nowait()
                except queue.Empty:
                    request = None
                if request is not None:
                    name, arguments, future = request
                    try:
                        future.set_result(self._rpc(name, arguments))
                    except BaseException as error:
                        future.set_exception(error)
                        raise
                with self._mutex:
                    stopping = self._stopping
                if stopping and self._requests.empty():
                    break
                now = time.monotonic()
                if now >= deadline:
                    self._capture()
                    deadline += self.period
                    now = time.monotonic()
                    if deadline <= now:
                        missed = math.floor((now - deadline) / self.period) + 1
                        deadline += missed * self.period
                        with self._mutex:
                            self._state['missed_deadlines'] += missed
                with self._mutex:
                    self._state['producer_cpu_seconds'] = time.thread_time() - cpu_start
                if not self._requests.empty():
                    continue
                self._wake.wait(max(0, deadline - time.monotonic()))
        except BaseException as error:
            with self._mutex:
                self._state['error'] = f'{type(error).__name__}: {error}'
                self._state['state'] = 'failed'
        finally:
            with self._mutex:
                self._state['state'] = 'failed' if self._state['error'] else 'stopped'
                self._state['producer_cpu_seconds'] = time.thread_time() - cpu_start
            self._ready.set()
            if self._stream is not None:
                self._stream.close()
            if self._socket is not None:
                self._socket.close()
            while True:
                try:
                    _, _, future = self._requests.get_nowait()
                except queue.Empty:
                    break
                future.set_exception(RuntimeError(self._state['error'] or 'LCD producer stopped'))

    def call(self, name, arguments=None, *, timeout=None):
        """Serialize the runner's other QMP operations on this connection's owner."""
        self._owner()
        if name == 'quit':
            raise ValueError('Join LCD producer and verify no outstanding QMP before VM quit')
        future = concurrent.futures.Future()
        with self._mutex:
            if self._stopping or self._state['state'] != 'running':
                raise RuntimeError('LCD QMP producer is not accepting requests')
            self._requests.put_nowait((name, arguments, future))
        self._wake.set()
        return future.result(timeout)

    def latest(self):
        """Consume the capacity-one slot; slow readers never queue old frames."""
        self._owner()
        with self._mutex:
            frame, self._latest = self._latest, None
            return frame

    def receipt(self):
        self._owner()
        with self._mutex:
            result = dict(self._state)
            duration = (self._last_ns - self._first_ns) / 1e9 if self._first_ns is not None else 0
            result.update(observed_seconds=duration,
                transport_fps=(result['transport_frames'] - 1) / duration if duration else 0,
                original_epoch_fps=(result['unique_original_epochs'] - 1) / duration if duration else 0,
                changed_original_fps=result['changed_original_frames'] / duration if duration else 0,
                interval_ms=_percentiles(self._times), capture_ms=_percentiles(self._latencies),
                timing_sample_window=len(self._latencies),
                outstanding_qmp=dict(self._outstanding) if self._outstanding else None,
                queued_qmp=self._requests.qsize())
        result['transport_gt15fps_observed'] = duration >= 2 and result['transport_fps'] > 15
        result['active_original_gt15fps_observed'] = bool(duration >= 2 and
            result['source_binding_verified'] and result['changed_original_fps'] > 15)
        result['safe_to_quit'] = bool(result['producer_joined'] and result['outstanding_qmp'] is None and not result['queued_qmp'])
        return result

    def _close_files(self):
        if self._dir is not None:
            for suffix in ('.before', '.after', '.ppm', '.publish'):
                try:
                    os.unlink(self.prefix + suffix, dir_fd=self._dir)
                except FileNotFoundError:
                    pass
        for name in ('_journal', '_lock', '_dir'):
            fd = getattr(self, name)
            if fd is not None:
                os.close(fd)
                setattr(self, name, None)

    def stop(self, *, timeout=10):
        """Export stages once on the QMP owner, then join without cancelling RPCs."""
        self._owner()
        with self._mutex:
            performance_source = (dict(self._source) if self._source is not None and
                self._state['source_binding_verified'] and self._state['state'] == 'running' and
                not self._stopping and not self._performance_attempted else None)
            if performance_source is not None:
                self._performance_attempted = True
        if performance_source is not None:
            try:
                name = 'lcd-guest-performance.bin'
                fd = os.open(name, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW,
                             0o600, dir_fd=self._dir)
                os.close(fd)
                self.call('pmemsave', dict(val=PERFORMANCE_ADDRESS, size=PERFORMANCE_SIZE,
                    filename=self.output_dir + '/' + name), timeout=timeout)
                performance = decode_performance(_read_at(self._dir, name, PERFORMANCE_SIZE),
                    expected_nonce=performance_source['nonce'], expected_pid=performance_source['guest_pid'])
                with self._mutex:
                    self._state['guest_performance'] = performance
            except Exception as error:
                with self._mutex:
                    self._state['guest_performance_error'] = f'{type(error).__name__}: {error}'
        with self._mutex:
            self._stopping = True
        self._wake.set()
        if self._thread is not None:
            self._thread.join(timeout)
            if self._thread.is_alive():
                raise TimeoutError('LCD producer has not joined; VM quit is not allowed')
        with self._mutex:
            self._state['producer_joined'] = True
        result = self.receipt()
        if self._dir is not None:
            try:
                if 'guest_performance' in result:
                    try:
                        self._atomic('lcd-guest-performance.json',
                                     json.dumps(result['guest_performance'], indent=2).encode() + b'\n')
                    except Exception as error:
                        result['guest_performance_error'] = f'{type(error).__name__}: {error}'
                        with self._mutex:
                            self._state['guest_performance_error'] = result['guest_performance_error']
                        try:
                            os.unlink(self.prefix + '.publish', dir_fd=self._dir)
                        except FileNotFoundError:
                            pass
                self._atomic('lcd-stream.json', json.dumps(result, indent=2).encode() + b'\n')
            finally:
                self._close_files()
        return result


def start(run_dir, qmp_socket, *, fps=20, expected_peer, expected_source_nonce=None,
          source_log=None, qmp_output_dir='/out', timeout=5):
    return Producer(run_dir, qmp_socket, fps=fps, expected_peer=expected_peer,
                    expected_source_nonce=expected_source_nonce, source_log=source_log,
                    qmp_output_dir=qmp_output_dir, timeout=timeout)


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--prepare-runtime', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(prepare(args.prepare_runtime), indent=2))
