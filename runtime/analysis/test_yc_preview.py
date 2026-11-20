import base64
import hashlib
import io
import json
from pathlib import Path

import pytest
from PIL import Image

from menu_live import serial_command, snapshot_message, verified_yc_preview


def test_preview_requires_guest_readback_and_output_delivery(tmp_path: Path, monkeypatch):
    pixels = bytes([76]) * (1920 * 1080)
    source = tmp_path / 'yc-input.gray'
    source.write_bytes(pixels)
    monkeypatch.setenv('MENU_YC_INPUT_RAW', str(source))
    (tmp_path / 'runtime-manifest.json').write_text(json.dumps({'yc_input_sha256': hashlib.sha256(pixels).hexdigest()}))
    (tmp_path / 'console.log').write_text('')
    assert verified_yc_preview(tmp_path) is None
    value = 0xcbf29ce484222325
    for byte in pixels:
        value = ((value ^ byte) * 0x100000001b3) & ((1 << 64) - 1)
    (tmp_path / 'console.log').write_text(
        f'YCIN_INPUT: PNG luma readback bytes=2073600 fnv64={value:016x}\n'
        'YCIN_VDT_REPLY: OUT1 frame delivery, meta h=0x416\n')
    assert verified_yc_preview(tmp_path) == pixels
    source.write_bytes(bytes([77]) + pixels[1:])
    with pytest.raises(ValueError, match='verified initramfs'):
        verified_yc_preview(tmp_path)


@pytest.mark.parametrize('split_delivery', [False, True])
def test_preview_preserves_console_when_limit_exceeded(tmp_path: Path, monkeypatch, split_delivery):
    pixels = bytes([76]) * (1920 * 1080)
    source = tmp_path / 'yc-input.gray'; source.write_bytes(pixels)
    monkeypatch.setenv('MENU_YC_INPUT_RAW', str(source))
    manifest = json.dumps({'yc_input_sha256': hashlib.sha256(pixels).hexdigest()}).encode()
    (tmp_path / 'runtime-manifest.json').write_bytes(manifest)
    value = 0xcbf29ce484222325
    for byte in pixels:value = ((value ^ byte) * 0x100000001b3) & ((1 << 64) - 1)
    console = tmp_path / 'console.log'
    digest = f'YCIN_INPUT: PNG luma readback bytes=2073600 fnv64={value:016x}\n'.encode()
    delivery = b'YCIN_VDT_REPLY: OUT1 frame delivery\n'
    monkeypatch.setattr('menu_live.MAX_CONSOLE', 128)
    original = digest + (b'' if split_delivery else delivery) + b'x' * 128
    console.write_bytes(original)
    class Process:
        stdin = io.BytesIO()
        def poll(self):return None
    process = Process()
    with pytest.raises(RuntimeError, match='保留原日志'):
        serial_command(process, console, 'true', timeout=.01)
    assert console.read_bytes() == original and process._menu_serial_desynchronized
    if split_delivery:
        assert verified_yc_preview(tmp_path) is None
        with console.open('ab') as stream:stream.write(b'\n'+delivery)
    assert verified_yc_preview(tmp_path) == pixels
    (tmp_path / 'runtime-manifest.json').write_bytes(manifest + b'\n')
    with pytest.raises(ValueError, match='receipt differs'):
        verified_yc_preview(tmp_path)


def test_preview_composes_under_original_osd(tmp_path: Path):
    fixture = Path(__file__).parent / 'fixtures/headless-osd.b64'
    raw = fixture.read_bytes()
    normal = snapshot_message(raw)
    preview = snapshot_message(raw, preview=bytes([76]) * (1920 * 1080))
    with Image.open(io.BytesIO(base64.b64decode(normal['png']))) as osd, \
         Image.open(io.BytesIO(base64.b64decode(preview['png']))) as combined:
        assert osd.size == combined.size == (640, 480)
        assert osd.getpixel((320, 240)) != combined.getpixel((320, 240))
    assert preview['info']['preview_luma_only'] is True
    assert preview['info']['sequence'] == normal['info']['sequence']
    assert preview['info']['sha256'] != preview['info']['osd_container_sha256']
    with pytest.raises(ValueError, match='frame length'):
        snapshot_message(raw, preview=b'bad')
