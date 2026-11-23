"""Host coordinator for software virtual video recording to the guest virtual SD card."""
import ctypes
import json
from pathlib import Path
import threading
import time

import fast_shm

_BASE = Path(__file__).resolve().parent
_VHOST_LIB = None
_VHOST_LOCK = threading.Lock()

DEFAULT_WIDTH = 640
DEFAULT_HEIGHT = 480
DEFAULT_FPS = 24


def _load_video_host_lib():
    global _VHOST_LIB
    with _VHOST_LOCK:
        if _VHOST_LIB is not None:
            return _VHOST_LIB
        so_path = _BASE / 'virtual-video-host.so'
        if not so_path.is_file():
            return None
        lib = ctypes.CDLL(str(so_path))
        lib.vvh_recorder_create.argtypes = [ctypes.c_uint32, ctypes.c_uint32, ctypes.c_uint32]
        lib.vvh_recorder_create.restype = ctypes.c_void_p
        lib.vvh_recorder_feed_rgb24.argtypes = [
            ctypes.c_void_p, ctypes.c_void_p, ctypes.c_size_t, ctypes.c_int64, ctypes.c_int64,
        ]
        lib.vvh_recorder_feed_rgb24.restype = ctypes.c_int
        lib.vvh_recorder_finish_mp4.argtypes = [
            ctypes.c_void_p,
            ctypes.POINTER(ctypes.c_void_p),
            ctypes.POINTER(ctypes.c_size_t),
            ctypes.POINTER(ctypes.c_uint64),
        ]
        lib.vvh_recorder_finish_mp4.restype = ctypes.c_int
        lib.vvh_recorder_frame_count.argtypes = [ctypes.c_void_p]
        lib.vvh_recorder_frame_count.restype = ctypes.c_size_t
        lib.vvh_recorder_destroy.argtypes = [ctypes.c_void_p]
        lib.vvh_recorder_destroy.restype = None
        _VHOST_LIB = lib
        return lib


class VideoRecordManager:
    """Watches guest REC triggers in fast-shm, encodes live CMOS frames as H.264/MP4,
    and streams finalized MP4 files through guest libInfraFsys onto the virtual SD card."""

    def __init__(self, shm_view, out_dir, *, proc=None, fps=DEFAULT_FPS, on_clip=None):
        self.shm = shm_view
        self.out_dir = Path(out_dir) if out_dir else None
        self.proc = proc
        self.fps = int(fps)
        self.on_clip = on_clip
        self._lib = _load_video_host_lib()
        self._lock = threading.Lock()
        self._cond = threading.Condition(self._lock)
        self._close_ev = threading.Event()
        self._stop_req = threading.Event()
        self._active = False
        self._starting = False
        self._saving = False
        self._frames = 0
        self._elapsed_ms = 0
        self._handled_toggle_seq = 0
        self._handled_stop_seq = 0
        self._last_clip = None
        self._last_error = ''
        self._thread = None

    def start(self):
        if self.shm is None or not self.shm.video_ctrl_ready():
            return self
        with self._lock:
            if self._thread is not None:
                return self
            vstate = self.shm.video_state()
            self._handled_toggle_seq = vstate[1]
            self._handled_stop_seq = vstate[2]
            self._thread = threading.Thread(target=self._run, name='video-record-coordinator', daemon=True)
            self._thread.start()
        return self

    def snapshot(self):
        with self._lock:
            return {
                'active': self._active,
                'saving': self._saving,
                'frames': self._frames,
                'elapsed_ms': self._elapsed_ms,
                'fps': self.fps,
                'toggle_seq': self._handled_toggle_seq,
                'last_clip': dict(self._last_clip) if self._last_clip else None,
                'error': self._last_error,
            }

    def toggle_seq(self):
        if self.shm is None or not self.shm.video_ctrl_ready():
            return 0
        return self.shm.video_state()[1]

    def wait_after_rec_key(self, prev_toggle_seq, *, trigger_timeout=0.5, settle_timeout=30.0):
        """Wait for a just-submitted REC / Movie-shutter key to start or finish saving."""
        if self.shm is None or self._thread is None:
            return self.snapshot()
        deadline = time.monotonic() + trigger_timeout
        seen = prev_toggle_seq
        while time.monotonic() < deadline:
            if self._close_ev.is_set() or (self.proc is not None and self.proc.poll() is not None):
                return self.snapshot()
            cur = self.shm.video_state()[1]
            if cur != prev_toggle_seq:
                seen = cur
                break
            time.sleep(0.01)
        if seen == prev_toggle_seq:
            return self.snapshot()
        end_at = time.monotonic() + settle_timeout
        with self._lock:
            while ((self._handled_toggle_seq != seen or self._starting or self._saving)
                   and not self._close_ev.is_set()):
                rem = end_at - time.monotonic()
                if rem <= 0:
                    break
                self._cond.wait(min(rem, 0.2))
        return self.snapshot()

    def stop_if_recording(self, *, timeout=30.0):
        """If currently recording, cleanly finalize & flush MP4 to virtual SD before export/OFF."""
        if self._thread is None:
            return self.snapshot()
        with self._lock:
            if not self._active and not self._saving and not self._starting:
                return self.snapshot()
            self._stop_req.set()
            end_at = time.monotonic() + timeout
            while (self._active or self._saving or self._starting) and not self._close_ev.is_set():
                rem = end_at - time.monotonic()
                if rem <= 0:
                    break
                self._cond.wait(min(rem, 0.2))
        return self.snapshot()

    def close(self):
        self._close_ev.set()
        self._stop_req.set()
        with self._lock:
            self._cond.notify_all()
        thread = self._thread
        self._thread = None
        if thread is not None and thread.is_alive() and thread is not threading.current_thread():
            thread.join(timeout=5.0)
        if self.shm is not None and not self.shm._closed:
            try:
                self.shm.set_video_status(active=False, saving=False, elapsed_ms=0, frames=0, bump_hud=True)
            except Exception:
                pass

    def _run(self):
        while not self._close_ev.is_set():
            if self.proc is not None and self.proc.poll() is not None:
                return
            vstate = self.shm.video_state()
            toggle_seq = vstate[1]
            stop_seq = vstate[2]
            if toggle_seq != self._handled_toggle_seq:
                with self._lock:
                    self._handled_toggle_seq = toggle_seq
                    self._handled_stop_seq = stop_seq
                    self._last_error = ''
                    self._starting = True
                    self._cond.notify_all()
                self._record_session(start_toggle=toggle_seq, start_stop=stop_seq)
                continue
            with self._lock:
                self._handled_stop_seq = stop_seq
            self._close_ev.wait(0.02)

    def _check_guest_alive(self):
        if self._close_ev.is_set():
            raise RuntimeError('video recorder closing')
        if self.proc is not None and self.proc.poll() is not None:
            raise RuntimeError('guest VM exited during video write')

    def _record_session(self, *, start_toggle, start_stop):
        if self._lib is None:
            with self._lock:
                self._starting = False
                self._last_error = '缺少 virtual-video-host.so（请运行 build-observers.sh）'
                self._cond.notify_all()
            return
        if not self.shm.guest_video_ready():
            with self._lock:
                self._starting = False
                self._last_error = 'guest 视频传输端点未就绪'
                self._cond.notify_all()
            return

        rec = self._lib.vvh_recorder_create(DEFAULT_WIDTH, DEFAULT_HEIGHT, self.fps)
        if not rec:
            with self._lock:
                self._starting = False
                self._last_error = '无法创建 H.264 录像编码器'
                self._cond.notify_all()
            return

        source_kinds = set()
        frames = 0
        started_at = time.monotonic()
        period = 1.0 / self.fps
        last_hud_sec = -1
        with self._lock:
            self._active = True
            self._starting = False
            self._saving = False
            self._frames = 0
            self._elapsed_ms = 0
            self._cond.notify_all()
        self.shm.set_video_status(active=True, saving=False, elapsed_ms=0, frames=0, bump_hud=True)

        should_commit = True
        try:
            while not self._close_ev.is_set():
                if self.proc is not None and self.proc.poll() is not None:
                    should_commit = False
                    break
                if self._stop_req.is_set():
                    break
                vstate = self.shm.video_state()
                if vstate[1] != start_toggle or vstate[2] != start_stop:
                    with self._lock:
                        self._handled_toggle_seq = vstate[1]
                        self._handled_stop_seq = vstate[2]
                        self._active = False
                        self._saving = frames > 0
                        self._cond.notify_all()
                    break

                now = time.monotonic()
                elapsed = max(0.0, now - started_at)
                target_frames = max(1, int(elapsed * self.fps) + 1)
                if frames < target_frames:
                    rgb, kind = self.shm.read_active_cmos_rgb24()
                    source_kinds.add(kind)
                    rgb_buf = (ctypes.c_ubyte * len(rgb)).from_buffer_copy(rgb)
                    steps = min(target_frames - frames, 4)
                    for _ in range(steps):
                        rc = self._lib.vvh_recorder_feed_rgb24(rec, rgb_buf, len(rgb), frames, 1)
                        if rc != 0:
                            raise RuntimeError(f'H.264 帧编码失败 rc={rc}')
                        frames += 1
                    elapsed_ms = int((frames * 1000) // self.fps)
                    sec = elapsed_ms // 1000
                    bump = sec != last_hud_sec
                    if bump:
                        last_hud_sec = sec
                    with self._lock:
                        self._frames = frames
                        self._elapsed_ms = elapsed_ms
                    self.shm.set_video_status(
                        active=True, saving=False, elapsed_ms=elapsed_ms, frames=frames, bump_hud=bump,
                    )

                next_due = started_at + frames * period
                sleep_for = min(max(0.002, next_due - time.monotonic()), 0.025)
                if self._close_ev.wait(sleep_for):
                    should_commit = False
                    break

            if not should_commit or frames <= 0:
                return

            elapsed_ms = int((frames * 1000) // self.fps)
            with self._lock:
                self._active = False
                self._saving = True
                self._frames = frames
                self._elapsed_ms = elapsed_ms
                self._cond.notify_all()
            self.shm.set_video_status(
                active=False, saving=True, elapsed_ms=elapsed_ms, frames=frames, bump_hud=True,
            )

            mp4_ptr = ctypes.c_void_p()
            mp4_len = ctypes.c_size_t()
            fnv_val = ctypes.c_uint64()
            rc = self._lib.vvh_recorder_finish_mp4(
                rec, ctypes.byref(mp4_ptr), ctypes.byref(mp4_len), ctypes.byref(fnv_val),
            )
            if rc != 0 or not mp4_ptr.value or mp4_len.value == 0:
                raise RuntimeError(f'MP4 封装失败 rc={rc}')
            mp4_bytes = ctypes.string_at(mp4_ptr.value, mp4_len.value)
            expected_hash = int(fnv_val.value)
            clip = self._write_mp4_to_guest_sd(
                mp4_bytes, expected_hash, frames=frames, elapsed_ms=elapsed_ms,
                source_kinds=sorted(source_kinds),
            )
            with self._lock:
                self._last_clip = clip
                self._last_error = ''
            if self.on_clip is not None:
                self.on_clip(dict(clip))
        except Exception as error:
            err_text = f'{type(error).__name__}: {error}'
            with self._lock:
                self._last_error = err_text
            self._write_receipt({
                'ok': False,
                'error': err_text,
                'frames': frames,
                'fps': self.fps,
                'software_virtual_video': True,
                'original_CP': False,
            })
        finally:
            self._stop_req.clear()
            self._lib.vvh_recorder_destroy(rec)
            with self._lock:
                self._starting = False
                self._active = False
                self._saving = False
                self._cond.notify_all()
            if not self.shm._closed:
                try:
                    self.shm.set_video_status(
                        active=False, saving=False, elapsed_ms=0, frames=frames, bump_hud=True,
                    )
                except Exception:
                    pass

    def _write_mp4_to_guest_sd(self, mp4_bytes, expected_hash, *, frames, elapsed_ms, source_kinds):
        beg = self.shm.submit_video_xfer(fast_shm.VIDEO_OP_BEGIN, check_fn=self._check_guest_alive)
        if beg['status'] != 0:
            raise RuntimeError(f'guest SD 创建录像文件失败 rc={beg["status"]}')
        try:
            total = len(mp4_bytes)
            for off in range(0, total, fast_shm.VIDEO_BUF_SIZE):
                chunk = mp4_bytes[off:off + fast_shm.VIDEO_BUF_SIZE]
                res = self.shm.submit_video_xfer(
                    fast_shm.VIDEO_OP_CHUNK, chunk, check_fn=self._check_guest_alive,
                )
                if res['status'] != 0:
                    raise RuntimeError(f'guest SD 写入录像块失败 rc={res["status"]}')
            fin = self.shm.submit_video_xfer(
                fast_shm.VIDEO_OP_COMMIT,
                total_bytes=total,
                expected_hash=expected_hash,
                check_fn=self._check_guest_alive,
            )
            if fin['status'] != 0 or not fin['readback_ok']:
                raise RuntimeError(
                    f'guest SD 录像提交读回校验失败 rc={fin["status"]} readback={fin["readback_ok"]}'
                )
            if fin['bytes_written'] != total or fin['guest_hash'] != expected_hash:
                raise RuntimeError('guest SD 录像长度或 FNV-1a 摘要与宿主 MP4 不一致')
        except Exception:
            if not self.shm._closed and self.shm.guest_video_ready():
                try:
                    self.shm.submit_video_xfer(fast_shm.VIDEO_OP_ABORT, timeout=5.0)
                except Exception:
                    pass
            raise

        clip = {
            'ok': True,
            'path': fin['guest_path'],
            'file_number': fin['file_num'],
            'bytes': total,
            'fnv1a64': f'{expected_hash:016x}',
            'frames': frames,
            'fps': self.fps,
            'width': DEFAULT_WIDTH,
            'height': DEFAULT_HEIGHT,
            'elapsed_ms': elapsed_ms,
            'codec': 'h264',
            'source_kinds': source_kinds,
            'readback_verified': True,
            'software_virtual_video': True,
            'original_CP': False,
        }
        self._write_receipt(clip)
        return clip

    def _write_receipt(self, receipt):
        if self.out_dir is None:
            return
        try:
            self.out_dir.mkdir(parents=True, exist_ok=True)
            (self.out_dir / 'last-video-record.json').write_text(
                json.dumps(receipt, indent=2) + '\n'
            )
            with (self.out_dir / 'video-records.jsonl').open('a') as f:
                f.write(json.dumps(receipt) + '\n')
        except OSError:
            pass
