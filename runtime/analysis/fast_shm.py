"""Host-side zero-temp-file shared-memory virtual CP display & direct App32 input ring.

Maps the guest reserved DDR window [0x41e100000 .. 0x41e5fffff] directly via an
anonymous memfd passed to QEMU's memory-backend-file (share=on). No files are
created on disk, /tmp, or /dev/shm; the kernel reclaims the sparse RAM pages
automatically when all processes exit.
"""
import ctypes
import fcntl
import mmap
import os
from pathlib import Path
import re
import struct
import threading
import time

MAGIC = 0x314D4853  # "SHM1" little-endian
VERSION = 1

PHYS_BASE = 0x41E100000
VIRT_RAM_BASE = 0x40000000
MEMFD_OFFSET = PHYS_BASE - VIRT_RAM_BASE  # 0x3de100000
MAP_SIZE = 0x500000

WIDTH = 640
HEIGHT = 480
RGB_BYTES = WIDTH * HEIGHT * 3  # 921600
OSD_BYTES = WIDTH * HEIGHT * 2  # 614400

PLAYBACK_BG_OFF = 0x130000
CUSTOM_CMOS_OFF = 0x220000
OSD0_OFF = 0x310000
OSD1_OFF = 0x3B0000
CTRL_OFF = 0x450000

FLAG_SHOOTING = 1 << 0
FLAG_PLAYBACK_BG = 1 << 1

RING_SIZE = 64
RING_MASK = RING_SIZE - 1
KEY_OP_EVENT = 1
KEY_OP_TAP = 2

VIDEO_MAGIC = 0x31444956  # "VID1" little-endian
VIDEO_VERSION = 1
VIDEO_CTRL_OFF = 0x451000
VIDEO_BUF_OFF = 0x460000
VIDEO_BUF_SIZE = 512 * 1024

VIDEO_OP_BEGIN = 1
VIDEO_OP_CHUNK = 2
VIDEO_OP_COMMIT = 3
VIDEO_OP_ABORT = 4

# Exact field offsets inside struct fast_shm_ctrl (verified against fast-shm.h).
OFF_MAGIC = 0
OFF_VERSION = 4
OFF_GUEST_DISPLAY_READY = 8
OFF_GUEST_INPUT_READY = 12
OFF_HOST_FEATURES = 16

OFF_OSD_SEQ = 32
OFF_OSD_SLOT = 40
OFF_DISPLAY_FLAGS = 44
OFF_PLAYBACK_BG_SEQ = 48
OFF_BLINK_SEQ = 52
OFF_OSD_PIXEL_SEQ = 56
OFF_OSD_FRAME_PHYS = 64
OFF_OSD_FRAME_ID = 72

OFF_CUSTOM_CMOS_ACTIVE = 96
OFF_CUSTOM_CMOS_SEQ = 100

OFF_KEY_HEAD = 128
OFF_KEY_TAIL = 136
OFF_KEY_ACK_SEQ = 144
OFF_KEY_LAST_RC = 152
OFF_KEY_SENT_COUNT = 156
OFF_RING = 192
RING_CMD_STRUCT = struct.Struct('<QIIIIIIII')  # 40 bytes

# Exact field offsets inside struct fast_shm_video_ctrl (verified against fast-shm.h).
OFF_V_MAGIC = 0
OFF_V_VERSION = 4
OFF_V_GUEST_READY = 8
OFF_V_REC_TOGGLE_SEQ = 16
OFF_V_REC_STOP_SEQ = 20
OFF_V_REC_MODE_SWITCH = 24
OFF_V_REC_ACTIVE = 32
OFF_V_REC_SAVING = 36
OFF_V_REC_ELAPSED_MS = 40
OFF_V_REC_FRAMES = 44
OFF_V_REC_HUD_SEQ = 48
OFF_V_XFER_REQ_SEQ = 64
OFF_V_XFER_OP = 68
OFF_V_XFER_LEN = 72
OFF_V_XFER_FLAGS = 76
OFF_V_XFER_TOTAL_BYTES = 80
OFF_V_XFER_EXPECTED_HASH = 88
OFF_V_XFER_ACK_SEQ = 96
OFF_V_XFER_STATUS = 100
OFF_V_XFER_FILE_NUM = 104
OFF_V_XFER_READBACK_OK = 108
OFF_V_XFER_BYTES_WRITTEN = 112
OFF_V_XFER_GUEST_HASH = 120
OFF_V_XFER_GUEST_PATH = 128

_NUMBER = r'(?:0x[0-9a-fA-F]+|[0-9]+)'
_COMMAND = re.compile(r'/simulation/inject-key --app\s+(' + _NUMBER + r'(?:\s+' + _NUMBER + r'){6})')

_BASE = Path(__file__).resolve().parent
_BLEND_LIB = None
_BLEND_LIB_LOCK = threading.Lock()
_DEFAULT_CHART_CACHE = None


def _load_blend_lib():
    global _BLEND_LIB
    with _BLEND_LIB_LOCK:
        if _BLEND_LIB is not None:
            return _BLEND_LIB
        so_path = _BASE / 'fast-osd-blend.so'
        if not so_path.is_file():
            return None
        lib = ctypes.CDLL(str(so_path))
        lib.fast_blend_rgba4444_over_rgb24.argtypes = [
            ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_int,
        ]
        lib.fast_blend_rgba4444_over_rgb24.restype = None
        if hasattr(lib, 'fast_draw_rec_hud'):
            lib.fast_draw_rec_hud.argtypes = [
                ctypes.c_void_p, ctypes.c_int, ctypes.c_int, ctypes.c_uint32,
            ]
            lib.fast_draw_rec_hud.restype = None
        lib.fast_default_chart_rgb24.argtypes = [ctypes.c_void_p]
        lib.fast_default_chart_rgb24.restype = ctypes.c_int
        lib.fast_atomic_load_u32.argtypes = [ctypes.c_void_p]
        lib.fast_atomic_load_u32.restype = ctypes.c_uint32
        lib.fast_atomic_store_u32.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
        lib.fast_atomic_store_u32.restype = None
        lib.fast_atomic_load_u64.argtypes = [ctypes.c_void_p]
        lib.fast_atomic_load_u64.restype = ctypes.c_uint64
        lib.fast_atomic_store_u64.argtypes = [ctypes.c_void_p, ctypes.c_uint64]
        lib.fast_atomic_store_u64.restype = None
        _BLEND_LIB = lib
        return lib


def default_chart_rgb24():
    """Return the deterministic 640x480 RGB24 default virtual CMOS color chart."""
    global _DEFAULT_CHART_CACHE
    if _DEFAULT_CHART_CACHE is not None:
        return _DEFAULT_CHART_CACHE
    lib = _load_blend_lib()
    if lib is not None:
        buf = (ctypes.c_ubyte * RGB_BYTES)()
        if lib.fast_default_chart_rgb24(buf) == 0:
            _DEFAULT_CHART_CACHE = bytes(buf)
            return _DEFAULT_CHART_CACHE
    # Pure fallback: neutral dark slate if host .so has not been built yet.
    _DEFAULT_CHART_CACHE = bytes((24, 28, 32)) * (WIDTH * HEIGHT)
    return _DEFAULT_CHART_CACHE


def _blend_python_fallback(osd_bytes, bg_bytes):
    out = bytearray(RGB_BYTES)
    mv_osd = memoryview(osd_bytes).cast('H')
    if bg_bytes is None:
        for i in range(WIDTH * HEIGHT):
            v = mv_osd[i]
            a = v & 15
            if a:
                out[3 * i + 0] = ((v >> 12) * 17 * a + 7) // 15
                out[3 * i + 1] = (((v >> 8) & 15) * 17 * a + 7) // 15
                out[3 * i + 2] = (((v >> 4) & 15) * 17 * a + 7) // 15
    else:
        for i in range(WIDTH * HEIGHT):
            v = mv_osd[i]
            a = v & 15
            if a == 0:
                out[3 * i:3 * i + 3] = bg_bytes[3 * i:3 * i + 3]
            elif a == 15:
                out[3 * i + 0] = (v >> 12) * 17
                out[3 * i + 1] = ((v >> 8) & 15) * 17
                out[3 * i + 2] = ((v >> 4) & 15) * 17
            else:
                inv = 15 - a
                out[3 * i + 0] = ((v >> 12) * 17 * a + bg_bytes[3 * i + 0] * inv + 7) // 15
                out[3 * i + 1] = (((v >> 8) & 15) * 17 * a + bg_bytes[3 * i + 1] * inv + 7) // 15
                out[3 * i + 2] = (((v >> 4) & 15) * 17 * a + bg_bytes[3 * i + 2] * inv + 7) // 15
    return bytes(out)


def create_ram_memfd(ram_mb=24576, *, min_fd=60):
    """Create a sparse anonymous memfd for QEMU guest RAM and initialize fast-shm ctrl."""
    if not isinstance(ram_mb, int) or ram_mb * 1024 * 1024 < MEMFD_OFFSET + MAP_SIZE:
        raise ValueError('ram_mb must cover the reserved high-DDR window')
    raw_fd = os.memfd_create('a7c2-guest-ram', 0)
    try:
        os.ftruncate(raw_fd, ram_mb * 1024 * 1024)
        # Initialize only the control pages (4 KiB sparse allocations).
        with mmap.mmap(raw_fd, MAP_SIZE, offset=MEMFD_OFFSET) as view:
            struct.pack_into('<IIIII', view, CTRL_OFF, MAGIC, VERSION, 0, 0, 1)
            struct.pack_into('<IIII', view, VIDEO_CTRL_OFF, VIDEO_MAGIC, VIDEO_VERSION, 0, 0)
        fd = fcntl.fcntl(raw_fd, fcntl.F_DUPFD_CLOEXEC, min_fd)
    finally:
        os.close(raw_fd)
    return fd


def parse_inherited_fd(env=None):
    """Return validated integer FD from A7C2_FAST_SHM_FD, or None if disabled."""
    source = os.environ if env is None else env
    if source.get('A7C2_FAST_SHM') != '1':
        return None
    raw = source.get('A7C2_FAST_SHM_FD', '')
    if not raw or not raw.isdigit():
        return None
    fd = int(raw)
    if fd < 3:
        return None
    try:
        info = os.fstat(fd)
    except OSError:
        return None
    if info.st_size < MEMFD_OFFSET + MAP_SIZE:
        return None
    return fd


class FastShmView:
    """Thread-safe host view over the 5 MiB shared-memory window."""

    def __init__(self, fd, *, offset=MEMFD_OFFSET):
        self._fd = int(fd)
        self._offset = int(offset)
        self._mm = mmap.mmap(self._fd, MAP_SIZE, offset=self._offset)
        self._buf = (ctypes.c_ubyte * MAP_SIZE).from_buffer(self._mm)
        self._base_addr = ctypes.addressof(self._buf)
        self._lib = _load_blend_lib()
        self._out_buf = (ctypes.c_ubyte * RGB_BYTES)()
        self._chart_buf = (ctypes.c_ubyte * RGB_BYTES).from_buffer_copy(default_chart_rgb24())
        self._closed = False
        self._io_lock = threading.Lock()
        self._cmos_lock = threading.Lock()
        self._ring_lock = threading.Lock()
        self._video_xfer_lock = threading.Lock()
        if self._u32(OFF_MAGIC) != MAGIC or self._u32(OFF_VERSION) != VERSION:
            self.close()
            raise ValueError('fast-shm control header magic/version mismatch')

    def _load_u32(self, area_off, off):
        if self._lib is not None:
            return int(self._lib.fast_atomic_load_u32(self._base_addr + area_off + off))
        return struct.unpack_from('<I', self._mm, area_off + off)[0]

    def _store_u32(self, area_off, off, val):
        if self._lib is not None:
            self._lib.fast_atomic_store_u32(self._base_addr + area_off + off, int(val))
        else:
            struct.pack_into('<I', self._mm, area_off + off, int(val))

    def _load_u64(self, area_off, off):
        if self._lib is not None:
            return int(self._lib.fast_atomic_load_u64(self._base_addr + area_off + off))
        return struct.unpack_from('<Q', self._mm, area_off + off)[0]

    def _store_u64(self, area_off, off, val):
        if self._lib is not None:
            self._lib.fast_atomic_store_u64(self._base_addr + area_off + off, int(val))
        else:
            struct.pack_into('<Q', self._mm, area_off + off, int(val))

    def _u32(self, off):
        return self._load_u32(CTRL_OFF, off)

    def _set_u32(self, off, val):
        self._store_u32(CTRL_OFF, off, val)

    def _u64(self, off):
        return self._load_u64(CTRL_OFF, off)

    def _set_u64(self, off, val):
        self._store_u64(CTRL_OFF, off, val)

    def _vu32(self, off):
        return self._load_u32(VIDEO_CTRL_OFF, off)

    def _set_vu32(self, off, val):
        self._store_u32(VIDEO_CTRL_OFF, off, val)

    def _vu64(self, off):
        return self._load_u64(VIDEO_CTRL_OFF, off)

    def _set_vu64(self, off, val):
        self._store_u64(VIDEO_CTRL_OFF, off, val)

    def _i32(self, off):
        v = self._u32(off)
        return v - 0x100000000 if v >= 0x80000000 else v

    def _vi32(self, off):
        v = self._vu32(off)
        return v - 0x100000000 if v >= 0x80000000 else v

    def guest_display_ready(self):
        return not self._closed and self._u32(OFF_GUEST_DISPLAY_READY) == 1

    def guest_input_ready(self):
        return not self._closed and self._u32(OFF_GUEST_INPUT_READY) == 1

    def video_ctrl_ready(self):
        return (not self._closed
                and self._vu32(OFF_V_MAGIC) == VIDEO_MAGIC
                and self._vu32(OFF_V_VERSION) == VIDEO_VERSION)

    def guest_video_ready(self):
        return self.video_ctrl_ready() and self._vu32(OFF_V_GUEST_READY) == 1

    def video_state(self):
        """Return (guest_ready, toggle_seq, stop_seq, mode_switch, rec_active, rec_saving, elapsed_ms, frames, hud_seq)."""
        if not self.video_ctrl_ready():
            return (0, 0, 0, 1, 0, 0, 0, 0, 0)
        return (
            self._vu32(OFF_V_GUEST_READY),
            self._vu32(OFF_V_REC_TOGGLE_SEQ),
            self._vu32(OFF_V_REC_STOP_SEQ),
            self._vu32(OFF_V_REC_MODE_SWITCH) or 1,
            self._vu32(OFF_V_REC_ACTIVE),
            self._vu32(OFF_V_REC_SAVING),
            self._vu32(OFF_V_REC_ELAPSED_MS),
            self._vu32(OFF_V_REC_FRAMES),
            self._vu32(OFF_V_REC_HUD_SEQ),
        )

    def set_video_status(self, *, active, saving, elapsed_ms, frames, bump_hud=False):
        if self._closed or not self.video_ctrl_ready():
            return 0
        self._set_vu32(OFF_V_REC_ACTIVE, 1 if active else 0)
        self._set_vu32(OFF_V_REC_SAVING, 1 if saving else 0)
        self._set_vu32(OFF_V_REC_ELAPSED_MS, int(elapsed_ms) & 0xFFFFFFFF)
        self._set_vu32(OFF_V_REC_FRAMES, int(frames) & 0xFFFFFFFF)
        if bump_hud:
            seq = (self._vu32(OFF_V_REC_HUD_SEQ) + 1) & 0xFFFFFFFF
            self._set_vu32(OFF_V_REC_HUD_SEQ, seq)
            return seq
        return self._vu32(OFF_V_REC_HUD_SEQ)

    def display_state(self):
        """Return (osd_seq, osd_slot, display_flags, playback_bg_seq, blink_seq, custom_cmos_active, custom_cmos_seq, osd_pixel_seq)."""
        osd_seq = self._u64(OFF_OSD_SEQ)
        return (
            osd_seq,
            self._u32(OFF_OSD_SLOT) & 1,
            self._u32(OFF_DISPLAY_FLAGS),
            self._u32(OFF_PLAYBACK_BG_SEQ),
            self._u32(OFF_BLINK_SEQ),
            self._u32(OFF_CUSTOM_CMOS_ACTIVE),
            self._u32(OFF_CUSTOM_CMOS_SEQ),
            self._u64(OFF_OSD_PIXEL_SEQ),
        )

    def render_rgb24(self):
        """Composite current guest OSD RGBA4444 over active background into 640x480 RGB24 bytes."""
        with self._io_lock:
            if self._closed:
                raise RuntimeError('fast-shm view is closed')
            has_rec_hud = self._lib is not None and hasattr(self._lib, 'fast_draw_rec_hud')
            for _ in range(4):
                osd_seq, slot, flags, pb_seq, _blink, custom_active, custom_seq, _pseq = self.display_state()
                _, _, _, _, rec_active, rec_saving, rec_elapsed_ms, _, rec_hud_seq = self.video_state()
                osd_off = OSD1_OFF if slot else OSD0_OFF
                if flags & FLAG_PLAYBACK_BG:
                    bg_addr = self._base_addr + PLAYBACK_BG_OFF
                    bg_off = PLAYBACK_BG_OFF
                    has_bg = 1
                elif flags & FLAG_SHOOTING:
                    if custom_active:
                        bg_addr = self._base_addr + CUSTOM_CMOS_OFF
                        bg_off = CUSTOM_CMOS_OFF
                    else:
                        bg_addr = ctypes.addressof(self._chart_buf)
                        bg_off = -1
                    has_bg = 1
                else:
                    bg_addr = 0
                    bg_off = -1
                    has_bg = 0

                if self._lib is not None:
                    self._lib.fast_blend_rgba4444_over_rgb24(
                        self._base_addr + osd_off,
                        bg_addr,
                        ctypes.addressof(self._out_buf),
                        has_bg,
                    )
                    if (has_rec_hud and (flags & FLAG_SHOOTING) and not (flags & FLAG_PLAYBACK_BG)
                            and (rec_active or rec_saving)):
                        self._lib.fast_draw_rec_hud(
                            ctypes.addressof(self._out_buf),
                            int(rec_active),
                            int(rec_saving),
                            int(rec_elapsed_ms),
                        )
                    frame = bytes(self._out_buf)
                else:
                    osd_raw = bytes(self._mm[osd_off:osd_off + OSD_BYTES])
                    if not has_bg:
                        bg_raw = None
                    elif bg_off >= 0:
                        bg_raw = bytes(self._mm[bg_off:bg_off + RGB_BYTES])
                    else:
                        bg_raw = default_chart_rgb24()
                    frame = _blend_python_fallback(osd_raw, bg_raw)

                # Tear check: verify no concurrent overwrite of background or slot switch occurred.
                osd_seq2, slot2, flags2, pb_seq2, _b2, ca2, cs2, _p2 = self.display_state()
                rec_hud_seq2 = self.video_state()[8]
                if (osd_seq2 == osd_seq and slot2 == slot and flags2 == flags
                        and pb_seq2 == pb_seq and ca2 == custom_active and cs2 == custom_seq
                        and rec_hud_seq2 == rec_hud_seq):
                    return frame, osd_seq
            return frame, osd_seq2

    def read_active_cmos_rgb24(self):
        """Return clean 640x480 RGB24 bytes from active CMOS source (custom video/image or default chart)."""
        with self._cmos_lock:
            if self._closed:
                raise RuntimeError('fast-shm view is closed')
            for _ in range(4):
                if self._u32(OFF_CUSTOM_CMOS_ACTIVE) != 1:
                    return default_chart_rgb24(), 'chart'
                seq1 = self._u32(OFF_CUSTOM_CMOS_SEQ)
                data = bytes(self._mm[CUSTOM_CMOS_OFF:CUSTOM_CMOS_OFF + RGB_BYTES])
                seq2 = self._u32(OFF_CUSTOM_CMOS_SEQ)
                if seq1 == seq2:
                    if self._u32(OFF_CUSTOM_CMOS_ACTIVE) != 1:
                        return default_chart_rgb24(), 'chart'
                    return data, 'custom'
            return bytes(self._mm[CUSTOM_CMOS_OFF:CUSTOM_CMOS_OFF + RGB_BYTES]), 'custom'

    def set_custom_cmos(self, rgb24_bytes):
        """Write 640x480 RGB24 custom CMOS frame (or None to revert to default chart)."""
        with self._cmos_lock:
            if self._closed:
                raise RuntimeError('fast-shm view is closed')
            if rgb24_bytes is None:
                self._set_u32(OFF_CUSTOM_CMOS_ACTIVE, 0)
                seq = (self._u32(OFF_CUSTOM_CMOS_SEQ) + 1) & 0xFFFFFFFF
                self._set_u32(OFF_CUSTOM_CMOS_SEQ, seq)
                return seq
            if not isinstance(rgb24_bytes, (bytes, bytearray, memoryview)) or len(rgb24_bytes) != RGB_BYTES:
                raise ValueError(f'custom CMOS frame must be exactly {RGB_BYTES} bytes of 640x480 RGB24')
            self._mm[CUSTOM_CMOS_OFF:CUSTOM_CMOS_OFF + RGB_BYTES] = rgb24_bytes
            self._set_u32(OFF_CUSTOM_CMOS_ACTIVE, 1)
            seq = (self._u32(OFF_CUSTOM_CMOS_SEQ) + 1) & 0xFFFFFFFF
            self._set_u32(OFF_CUSTOM_CMOS_SEQ, seq)
            return seq

    def submit_video_xfer(self, op, payload=b'', *, total_bytes=0, expected_hash=0, flags=0, timeout=30.0, check_fn=None):
        """Synchronously execute one MP4 Fsys transfer command over the shared 512 KiB staging buffer."""
        with self._video_xfer_lock:
            if self._closed:
                raise RuntimeError('fast-shm view is closed')
            if not self.guest_video_ready():
                raise RuntimeError('fast-shm guest video worker not ready')
            if payload:
                if len(payload) > VIDEO_BUF_SIZE:
                    raise ValueError(f'video xfer payload exceeds {VIDEO_BUF_SIZE} bytes')
                self._mm[VIDEO_BUF_OFF:VIDEO_BUF_OFF + len(payload)] = payload
            seq = (self._vu32(OFF_V_XFER_REQ_SEQ) + 1) & 0xFFFFFFFF
            if seq == 0:
                seq = 1
            self._set_vu32(OFF_V_XFER_OP, int(op))
            self._set_vu32(OFF_V_XFER_LEN, len(payload))
            self._set_vu32(OFF_V_XFER_FLAGS, int(flags))
            self._set_vu64(OFF_V_XFER_TOTAL_BYTES, int(total_bytes))
            self._set_vu64(OFF_V_XFER_EXPECTED_HASH, int(expected_hash))
            self._set_vu32(OFF_V_XFER_REQ_SEQ, seq)

            deadline = time.monotonic() + timeout
            spin = 0
            while time.monotonic() < deadline:
                if self._closed:
                    raise RuntimeError('fast-shm view closed during video xfer')
                if self._vu32(OFF_V_XFER_ACK_SEQ) == seq:
                    raw_path = bytes(self._mm[VIDEO_CTRL_OFF + OFF_V_XFER_GUEST_PATH:
                                              VIDEO_CTRL_OFF + OFF_V_XFER_GUEST_PATH + 64])
                    guest_path = raw_path.split(b'\x00', 1)[0].decode('utf-8', 'replace')
                    return {
                        'seq': seq,
                        'status': self._vi32(OFF_V_XFER_STATUS),
                        'file_num': self._vu32(OFF_V_XFER_FILE_NUM),
                        'readback_ok': self._vu32(OFF_V_XFER_READBACK_OK) == 1,
                        'bytes_written': self._vu64(OFF_V_XFER_BYTES_WRITTEN),
                        'guest_hash': self._vu64(OFF_V_XFER_GUEST_HASH),
                        'guest_path': guest_path,
                    }
                if check_fn is not None:
                    check_fn()
                spin += 1
                time.sleep(0.0005 if spin < 40 else 0.002)
            raise TimeoutError('fast-shm video xfer timed out')

    def submit_key(self, op, key, sub, status, ex, origin, hold_us=0, *, timeout=10.0, check_fn=None):
        """Push one command onto the SPSC ring and wait for guest OSAL send ACK."""
        with self._ring_lock:
            if self._closed:
                raise RuntimeError('fast-shm view is closed')
            if not self.guest_input_ready():
                raise RuntimeError('fast-shm guest input worker not ready')
            head = self._u64(OFF_KEY_HEAD)
            tail = self._u64(OFF_KEY_TAIL)
            if head - tail >= RING_SIZE:
                raise RuntimeError('fast-shm input ring full')
            seq = head + 1
            slot_off = CTRL_OFF + OFF_RING + (head & RING_MASK) * RING_CMD_STRUCT.size
            RING_CMD_STRUCT.pack_into(
                self._mm, slot_off,
                seq, int(op), int(key), int(sub), int(status), int(ex), int(origin), int(hold_us), 0,
            )
            self._set_u64(OFF_KEY_HEAD, seq)

            deadline = time.monotonic() + timeout
            spin = 0
            while time.monotonic() < deadline:
                if self._closed:
                    raise RuntimeError('fast-shm view closed during input wait')
                if self._u64(OFF_KEY_ACK_SEQ) >= seq:
                    rc = self._i32(OFF_KEY_LAST_RC)
                    return seq, rc
                if check_fn is not None:
                    check_fn()
                spin += 1
                time.sleep(0.0005 if spin < 40 else 0.002)
            raise TimeoutError('fast-shm input reply timed out; retain uncertain contact')

    def close(self):
        if self._closed:
            return
        self._closed = True
        with self._io_lock, self._cmos_lock:
            try:
                del self._buf
            except AttributeError:
                pass
            self._mm.close()


class FastShmAppInput:
    """Drop-in replacement for PersistentAppInput backed by shared-memory ring with serial fallback."""

    def __init__(self, shm_view, fallback, proc, monitor):
        self.shm = shm_view
        self.fallback = fallback
        self.proc = proc
        self.monitor = monitor
        self.fast_calls = 0
        self.fallback_calls = 0

    def _check_alive(self):
        if self.monitor is not None:
            self.monitor.check()
        if self.proc is not None and self.proc.poll() is not None:
            raise RuntimeError('Original input owner exited before fast-shm reply')

    def start(self):
        # Do not eagerly start the serial server if guest fast-shm input is already ready!
        if self.shm is not None and self.shm.guest_input_ready():
            return
        if self.fallback is not None:
            self.fallback.start()

    def pause(self):
        if self.fallback is not None:
            self.fallback.pause()

    def __call__(self, command):
        match = _COMMAND.fullmatch(command)
        if match is None:
            raise ValueError('Unsupported original input command; never retry through another channel')
        values = [int(value, 16) if value.startswith('0x') else int(value) for value in match.group(1).split()]
        if values[:2] != [0x5503E0, 0x5503E0] or any(not 0 <= v <= 0xFFFFFFFF for v in values):
            raise ValueError('Fast-SHM sender requires the original App32 route and uint32 fields')
        if self.shm is not None and self.shm.guest_input_ready():
            seq, rc = self.shm.submit_key(
                KEY_OP_EVENT, values[2], values[3], values[4], values[5], values[6], 0,
                check_fn=self._check_alive,
            )
            self.fast_calls += 1
            if rc != 0:
                raise RuntimeError(f'Original App32 fast-shm allocation/send failed rc={rc}')
            return f'FAST_SHM_INPUT_RESULT {seq} 0\n'.encode('ascii')
        self.fallback_calls += 1
        return self.fallback(command)

    def tap(self, key, hold_us=15000):
        if not 0 <= key <= 0xFFFFFFFF or not 0 < hold_us <= 100000:
            raise ValueError('Invalid atomic tap')
        if self.shm is not None and self.shm.guest_input_ready():
            seq, rc = self.shm.submit_key(
                KEY_OP_TAP, key, 0, 0, 0, 0, hold_us,
                check_fn=self._check_alive,
            )
            self.fast_calls += 1
            if rc != 0:
                raise RuntimeError(f'Original App32 fast-shm atomic tap failed rc={rc}')
            return f'FAST_SHM_INPUT_RESULT {seq} 0\n'.encode('ascii')
        self.fallback_calls += 1
        return self.fallback.tap(key, hold_us=hold_us)
