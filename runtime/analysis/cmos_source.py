"""Host side of the virtual CMOS source: pick a local image or MP4 video, fit to
the 640x480 sensor frame, and feed it to fast-shm or the short-line serial channel."""
import base64
from fractions import Fraction
import io
import json
from pathlib import Path
import shutil
import subprocess
import threading
import time

WIDTH, HEIGHT = 640, 480
RGB_BYTES = WIDTH * HEIGHT * 3
MAX_SOURCE_BYTES = 64 * 1024 * 1024
MAX_VIDEO_BYTES = 2 * 1024 * 1024 * 1024
MAX_VIDEO_FPS = 30.0
MIN_VIDEO_FPS = 1.0
CHUNK_CHARS = 760  # < 1000-byte physical serial line including the command prefix
PREFIX = '/simulation/cmos-import'
IMAGE_EXTENSIONS = {'.png', '.jpg', '.jpeg', '.bmp', '.webp', '.gif'}
VIDEO_EXTENSIONS = {'.mp4', '.m4v', '.mov'}
_VIDEO_VF = (
    f'scale={WIDTH}:{HEIGHT}:force_original_aspect_ratio=decrease,'
    f'pad={WIDTH}:{HEIGHT}:(ow-iw)/2:(oh-ih)/2:color=#101010,setsar=1'
)


def is_video_path(path):
    return Path(path).suffix.lower() in VIDEO_EXTENSIONS


def _find_tool(name):
    fixed = Path('/usr/bin') / name
    return str(fixed) if fixed.is_file() else (shutil.which(name) or '')


def _parse_fps(rate_text):
    if not rate_text or rate_text in ('0/0', 'N/A'):
        return None
    try:
        val = float(Fraction(str(rate_text)))
    except (ValueError, ZeroDivisionError):
        return None
    return val if val > 0 else None


def probe_video(path, *, max_fps=MAX_VIDEO_FPS):
    """Validate a local MP4/MOV video file and return stream geometry and playback FPS."""
    path = Path(path)
    if not path.is_absolute() or not path.is_file():
        raise ValueError('需要本地图片或 MP4 视频的绝对路径')
    size = path.stat().st_size
    if size <= 0 or size > MAX_VIDEO_BYTES:
        raise ValueError('视频文件为空或超过 2 GiB')
    ffprobe = _find_tool('ffprobe')
    if not ffprobe or not _find_tool('ffmpeg'):
        raise RuntimeError('缺少 ffmpeg/ffprobe，无法解码本地 MP4 视频')
    proc = subprocess.run(
        [
            ffprobe, '-v', 'error', '-select_streams', 'v:0',
            '-show_entries', 'stream=codec_name,width,height,r_frame_rate,avg_frame_rate,duration,nb_frames',
            '-show_entries', 'format=format_name,duration',
            '-of', 'json', str(path),
        ],
        capture_output=True, text=True, timeout=15,
    )
    if proc.returncode != 0:
        msg = (proc.stderr or '').strip() or 'ffprobe failed'
        raise ValueError(f'无效 MP4 视频：{msg}')
    try:
        meta = json.loads(proc.stdout or '{}')
    except json.JSONDecodeError as err:
        raise ValueError(f'无法解析视频元数据：{err}') from err
    streams = meta.get('streams') or []
    if not streams:
        raise ValueError('视频中未找到可解码的视频流')
    st = streams[0]
    w = int(st.get('width') or 0)
    h = int(st.get('height') or 0)
    if w <= 0 or h <= 0 or w * h > 7680 * 4320:
        raise ValueError('视频分辨率无效或超出支持上限')
    src_fps = _parse_fps(st.get('avg_frame_rate')) or _parse_fps(st.get('r_frame_rate')) or 24.0
    playback_fps = max(MIN_VIDEO_FPS, min(float(max_fps), src_fps))
    fmt = meta.get('format') or {}
    dur = st.get('duration') or fmt.get('duration')
    try:
        duration = float(dur) if dur is not None else None
    except (TypeError, ValueError):
        duration = None
    return {
        'width': w,
        'height': h,
        'codec_name': str(st.get('codec_name') or 'unknown'),
        'format_name': str(fmt.get('format_name') or ''),
        'src_fps': src_fps,
        'playback_fps': playback_fps,
        'duration': duration,
    }


def _read_exact(stream, size):
    buf = bytearray()
    while len(buf) < size:
        chunk = stream.read(size - len(buf))
        if not chunk:
            return None
        buf.extend(chunk)
    return bytes(buf)


def read_first_video_frame_rgb24(path):
    """Decode the first video frame fitted onto a 640x480 RGB24 canvas."""
    meta = probe_video(path)
    ffmpeg = _find_tool('ffmpeg')
    proc = subprocess.run(
        [
            ffmpeg, '-nostdin', '-hide_banner', '-loglevel', 'error',
            '-i', str(path), '-an', '-sn', '-dn', '-vframes', '1',
            '-vf', _VIDEO_VF, '-pix_fmt', 'rgb24', '-f', 'rawvideo', 'pipe:1',
        ],
        capture_output=True, timeout=20,
    )
    if proc.returncode != 0 or len(proc.stdout) != RGB_BYTES:
        err = (proc.stderr or b'').decode('utf-8', 'replace').strip()
        raise ValueError(f'无法解码 MP4 视频首帧：{err or proc.returncode}')
    return proc.stdout, meta


def read_first_video_frame_jpeg(path):
    """Decode first video frame as baseline 4:2:0 JPEG for serial fallback upload."""
    from PIL import Image
    rgb, meta = read_first_video_frame_rgb24(path)
    out = io.BytesIO()
    Image.frombytes('RGB', (WIDTH, HEIGHT), rgb).save(
        out, 'JPEG', quality=85, subsampling=2, optimize=False, progressive=False,
    )
    return out.getvalue(), meta


class VideoCmosStreamer:
    """Decode a local MP4 video and stream 640x480 RGB24 frames continuously into a callback."""

    def __init__(self, path, on_frame, *, loop=True, max_fps=MAX_VIDEO_FPS, on_error=None):
        self.path = Path(path)
        self._on_frame = on_frame
        self._loop = bool(loop)
        self._max_fps = float(max_fps)
        self._on_error = on_error
        self._stop = threading.Event()
        self._proc = None
        self._thread = None
        self.info = None
        self.fps = 24.0
        self.width = WIDTH
        self.height = HEIGHT
        self.frames_emitted = 0
        self.error = ''

    def start(self):
        self.info = probe_video(self.path, max_fps=self._max_fps)
        self.fps = self.info['playback_fps']
        ffmpeg = _find_tool('ffmpeg')
        cmd = [ffmpeg, '-nostdin', '-hide_banner', '-loglevel', 'error']
        if self._loop:
            cmd.extend(['-stream_loop', '-1'])
        cmd.extend([
            '-i', str(self.path), '-an', '-sn', '-dn',
            '-vf', _VIDEO_VF, '-pix_fmt', 'rgb24', '-f', 'rawvideo', 'pipe:1',
        ])
        self._proc = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            stdin=subprocess.DEVNULL,
        )
        try:
            first = _read_exact(self._proc.stdout, RGB_BYTES)
            if first is None:
                err = self._proc.stderr.read().decode('utf-8', 'replace').strip()
                raise ValueError(f'无法解码 MP4 视频首帧：{err or "empty stream"}')
            self.frames_emitted = 1
            self._on_frame(first)
        except Exception:
            self.stop()
            raise
        self._thread = threading.Thread(target=self._run, name='cmos-mp4-feeder', daemon=True)
        self._thread.start()
        return self

    def _run(self):
        period = 1.0 / self.fps
        next_at = time.monotonic() + period
        try:
            while not self._stop.is_set():
                proc = self._proc
                if proc is None or proc.stdout is None:
                    break
                frame = _read_exact(proc.stdout, RGB_BYTES)
                if frame is None:
                    if self._loop and not self._stop.is_set():
                        self.error = 'MP4 播放流提前结束'
                    break
                if self._stop.is_set():
                    break
                now = time.monotonic()
                wait = next_at - now
                if wait > 0:
                    if self._stop.wait(wait):
                        break
                    next_at += period
                else:
                    next_at = now + period
                if not self._stop.is_set():
                    self.frames_emitted += 1
                    self._on_frame(frame)
        except Exception as err:
            if not self._stop.is_set():
                self.error = str(err)
                if self._on_error is not None:
                    self._on_error(self.error)

    def stop(self):
        self._stop.set()
        proc, self._proc = self._proc, None
        if proc is not None:
            for stream in (proc.stdout, proc.stderr):
                if stream is not None:
                    try:
                        stream.close()
                    except OSError:
                        pass
            if proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=2.0)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait(timeout=2.0)
        thread, self._thread = self._thread, None
        if thread is not None and thread.is_alive() and thread is not threading.current_thread():
            thread.join(timeout=3.0)


def _prepare_canvas(path):
    """Validate and letterbox any supported image onto a 640x480 RGB canvas."""
    from PIL import Image, ImageOps
    path = Path(path)
    if not path.is_absolute() or not path.is_file():
        raise ValueError('需要本地图片或 MP4 视频的绝对路径')
    if path.stat().st_size > MAX_SOURCE_BYTES:
        raise ValueError('图片超过 64 MiB')
    with Image.open(path) as source:
        if source.format not in ('PNG', 'JPEG', 'BMP', 'WEBP', 'GIF'):
            raise ValueError('仅支持 PNG/JPEG/BMP/WEBP/GIF 图片或 MP4 视频')
        if source.width * source.height > 200_000_000:
            raise ValueError('图片像素过大')
        image = ImageOps.exif_transpose(source).convert('RGB')
    fitted = ImageOps.contain(image, (WIDTH, HEIGHT), Image.LANCZOS)
    canvas = Image.new('RGB', (WIDTH, HEIGHT), (16, 16, 16))
    canvas.paste(fitted, ((WIDTH - fitted.width) // 2, (HEIGHT - fitted.height) // 2))
    return canvas


def prepare_rgb24(path):
    """Fit any PNG/JPEG into 640x480 raw RGB24 bytes for direct shared-memory CMOS swap."""
    return _prepare_canvas(path).tobytes()


def prepare_jpeg(path):
    """Fit any PNG/JPEG into 640x480 (letterboxed, never stretched) as baseline 4:2:0 JPEG."""
    canvas = _prepare_canvas(path)
    out = io.BytesIO()
    canvas.save(out, 'JPEG', quality=85, subsampling=2, optimize=False, progressive=False)
    return out.getvalue()


def upload_commands(jpeg):
    """Guest commands (each one physical line) that rebuild the JPEG and swap the source."""
    encoded = base64.b64encode(jpeg).decode('ascii')
    commands = [PREFIX + ' --begin']
    commands += [f"{PREFIX} --chunk '{encoded[i:i + CHUNK_CHARS]}'" for i in range(0, len(encoded), CHUNK_CHARS)]
    commands.append(PREFIX + ' --commit')
    return commands


def reset_command():
    return PREFIX + ' --reset'
