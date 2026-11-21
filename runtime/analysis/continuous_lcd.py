"""Read the owned QEMU ramfb independently of camera input and serial diagnostics."""
import hashlib
import io
import json
import os
from pathlib import Path
import socket
import stat
import struct
import threading
import time

from PIL import Image


class ContinuousLCD:
    def __init__(self, run, owner, publish, *, fps=120, encode_png=True):
        self.run = Path(run).resolve(strict=True)
        if self.run.is_symlink() or not 15 < fps <= 120:
            raise ValueError('Invalid LCD run or refresh rate')
        self.owner, self.publish, self.period = owner, publish, 1 / fps
        self.encode_png = bool(encode_png)
        from single_ap_sockets import roots_for_run
        self.roots = roots_for_run(run)
        if self.roots is not None:
            from diagnostic_fs_socket_roots import process_identity
            self.owner_identity = process_identity(owner.pid)
        self.cancel = threading.Event()
        self.wake = threading.Event()
        self.thread = None
        self.error = ''
        self.samples = self.changes = 0
        self.last_hash = None
        self.last_raw = None
        self.boost_until = time.monotonic() + 3.0
        self.started = time.monotonic()
        self.peer = None

    IDLE_PERIOD = 1 / 15      # nothing is changing: screendump contends with the single-vCPU TCG guest
    BOOST_PERIOD = 1 / 60     # right after input or a changed frame
    BOOST_SECONDS = 1.5

    def nudge(self):
        """Input was just accepted: sample at the fast rate immediately until the screen settles."""
        self.boost_until = time.monotonic() + self.BOOST_SECONDS
        self.wake.set()

    def _pace(self):
        return max(self.period, self.BOOST_PERIOD) if time.monotonic() < self.boost_until else self.IDLE_PERIOD

    @staticmethod
    def _descendant(pid, ancestor):
        for _ in range(32):
            if pid == ancestor:
                return True
            try:
                fields = Path('/proc', str(pid), 'stat').read_text().rsplit(')', 1)[1].split()
                pid = int(fields[1])
            except (OSError, ValueError, IndexError):
                return False
            if pid <= 1:
                return False
        return False

    def start(self):
        if self.thread is not None:
            raise ValueError('LCD consumer already started')
        self.thread = threading.Thread(target=self._run, name='camera-continuous-lcd', daemon=True)
        self.thread.start()
        return self

    def _run(self):
        from menu_live import connect_in_run
        try:
            root = self.run if self.roots is None else self.roots.sockets
            path = root / 'lcd-qmp.sock'
            if self.roots is not None:
                from diagnostic_fs_socket_roots import process_identity
                self.roots.endpoint(path)
            info = path.lstat()
            if not stat.S_ISSOCK(info.st_mode) or info.st_uid != os.geteuid():
                raise ValueError('LCD QMP socket is not owned by this user')
            with socket.socket(socket.AF_UNIX) as sock:
                sock.settimeout(3)
                if self.roots is None:
                    connect_in_run(sock, self.run, 'lcd-qmp.sock')
                else:
                    with self.roots.connect_path(path) as address:
                        sock.connect(address)
                    if process_identity(self.owner.pid) != self.owner_identity:
                        raise ValueError('LCD VM owner start identity changed')
                pid, uid, _ = struct.unpack('3i', sock.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12))
                if uid != os.geteuid() or self.owner.poll() is not None or not self._descendant(pid, self.owner.pid):
                    raise ValueError('LCD QMP peer is not the current VM owner descendant')
                self.peer = pid
                if self.roots is not None:
                    peer_identity = process_identity(pid)
                    self.roots.endpoint(path)
                    if (process_identity(self.owner.pid) != self.owner_identity or
                            process_identity(pid) != peer_identity):
                        raise ValueError('LCD peer/owner changed during connect')
                with sock.makefile('rwb') as stream:
                    if 'QMP' not in json.loads(stream.readline(65537)):
                        raise ValueError('LCD QMP greeting missing')
                    self._command(stream, 'qmp_capabilities')
                    deadline = time.monotonic()
                    while not self.cancel.is_set():
                        if self.owner.poll() is not None:
                            return
                        if self.roots is not None:
                            self.roots.endpoint(path)
                            if (process_identity(self.owner.pid) != self.owner_identity or
                                    process_identity(pid) != peer_identity or not self._descendant(pid, self.owner.pid)):
                                raise ValueError('LCD peer/owner identity changed')
                        self._command(stream, 'screendump', {'filename': '/out/lcd-continuous.ppm'})
                        self._frame(self.run / 'lcd-continuous.ppm')
                        deadline += self._pace()
                        now = time.monotonic()
                        if deadline < now:
                            deadline = now
                        delay = max(0, deadline - now)
                        if delay > 0 and not self.cancel.is_set():
                            self.wake.wait(delay)
                            self.wake.clear()
        except (OSError, ValueError, RuntimeError, EOFError) as error:
            if not self.cancel.is_set():
                self.error = str(error)
        finally:
            report = dict(samples=self.samples, changed_pixels=self.changes, error=self.error,
                          elapsed_seconds=time.monotonic() - self.started, qmp_peer=self.peer,
                          source='owned QEMU ramfb', capture_verified=False)
            (self.run / 'lcd-continuous-result.json').write_text(json.dumps(report, indent=2) + '\n')

    @staticmethod
    def _command(stream, command, arguments=None):
        message = {'execute': command}
        if arguments is not None:
            message['arguments'] = arguments
        stream.write((json.dumps(message) + '\n').encode('ascii')); stream.flush()
        for _ in range(128):
            line = stream.readline(65537)
            if not line or len(line) > 65536:
                raise EOFError('LCD QMP response incomplete')
            response = json.loads(line)
            if 'error' in response:
                raise RuntimeError('LCD QMP error: ' + str(response['error']))
            if 'return' in response:
                return response['return']
        raise ValueError('LCD QMP event budget exceeded')

    def _frame(self, path):
        fd = os.open(path, os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW)
        try:
            before = os.fstat(fd)
            if not stat.S_ISREG(before.st_mode) or not 0 < before.st_size < 2 * 1024**2:
                raise ValueError('LCD surface exceeds expected bounds')
            with os.fdopen(fd, 'rb', closefd=False) as source:
                raw = source.read(before.st_size + 1)
            after = os.fstat(fd)
            if (before.st_ino, before.st_size, before.st_mtime_ns) != (after.st_ino, after.st_size, after.st_mtime_ns):
                raise ValueError('LCD frame changed before its QMP completion')
        finally:
            os.close(fd)
        header = b'P6\n640 480\n255\n'
        if raw.startswith(header) and len(raw) == len(header) + 640 * 480 * 3:
            # QEMU's own PPM: skip decode/hash entirely while the screen is unchanged.
            self.samples += 1
            if raw == self.last_raw:
                return
            pixels = raw[len(header):]
            digest = hashlib.sha256(pixels).hexdigest()
            if self.encode_png:
                image = Image.frombytes('RGB', (640, 480), pixels)
                buffer = io.BytesIO(); image.save(buffer, format='PNG', compress_level=1)
                payload = buffer.getvalue()
            else:
                payload = pixels
        else:
            with Image.open(io.BytesIO(raw)) as source:
                if source.format != 'PPM' or source.size != (640, 480):
                    raise ValueError('LCD is not a 640x480 QEMU surface')
                image = source.convert('RGB')
            pixels = image.tobytes()
            digest = hashlib.sha256(pixels).hexdigest()
            self.samples += 1
            if digest == self.last_hash:
                return
            if self.encode_png:
                buffer = io.BytesIO(); image.save(buffer, format='PNG', compress_level=1)
                payload = buffer.getvalue()
            else:
                payload = pixels
        self.last_raw = raw
        self.boost_until = max(self.boost_until, time.monotonic() + self.BOOST_SECONDS)
        self.changes += 1
        info = dict(sequence=self.samples, pixel_source_seq=self.changes, sha256=digest,
                    captured_at=time.time(), number=self.changes, source='continuous QEMU ramfb',
                    transport_samples=self.samples, changed_frames=self.changes)
        self.publish(payload, info)
        self.last_hash = digest

    def stop(self):
        self.cancel.set()
        self.wake.set()
        if self.thread is not None:
            self.thread.join(timeout=5)
            if self.thread.is_alive():
                raise RuntimeError('LCD QMP consumer has not released its connection')
