"""Host side of the virtual CMOS source: pick an image, resize to the 640x480
sensor frame, and push it to the guest through the short-line serial channel."""
import base64
import io
from pathlib import Path

WIDTH, HEIGHT = 640, 480
MAX_SOURCE_BYTES = 64 * 1024 * 1024
CHUNK_CHARS = 760  # < 1000-byte physical serial line including the command prefix
PREFIX = '/simulation/cmos-import'


def prepare_jpeg(path):
    """Fit any PNG/JPEG into 640x480 (letterboxed, never stretched) as baseline 4:2:0 JPEG."""
    from PIL import Image, ImageOps
    path = Path(path)
    if not path.is_absolute() or not path.is_file():
        raise ValueError('需要本地图片的绝对路径')
    if path.stat().st_size > MAX_SOURCE_BYTES:
        raise ValueError('图片超过 64 MiB')
    with Image.open(path) as source:
        if source.format not in ('PNG', 'JPEG', 'BMP', 'WEBP', 'GIF'):
            raise ValueError('仅支持 PNG/JPEG/BMP/WEBP/GIF 图片')
        if source.width * source.height > 200_000_000:
            raise ValueError('图片像素过大')
        image = ImageOps.exif_transpose(source).convert('RGB')
    fitted = ImageOps.contain(image, (WIDTH, HEIGHT), Image.LANCZOS)
    canvas = Image.new('RGB', (WIDTH, HEIGHT), (16, 16, 16))
    canvas.paste(fitted, ((WIDTH - fitted.width) // 2, (HEIGHT - fitted.height) // 2))
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
