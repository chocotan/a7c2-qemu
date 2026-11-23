"""Host integration tests for local MP4 virtual CMOS input and H.264/MP4 SD video recording."""
import hashlib
import json
import mmap
import os
from pathlib import Path
import struct
import subprocess
import tempfile
import threading
import time
from types import SimpleNamespace

import pytest

import cmos_source
from continuous_lcd import ContinuousLCD
import fast_shm
from video_recorder import VideoRecordManager


def _make_sample_mp4(path: Path, *, width=800, height=400, fps=24, seconds=2):
    """Synthesize a genuine animated MP4 clip (moving color sweep + color bars) with ffmpeg."""
    subprocess.run(
        [
            '/usr/bin/ffmpeg', '-y', '-nostdin', '-hide_banner', '-loglevel', 'error',
            '-f', 'lavfi', '-i', f'testsrc2=size={width}x{height}:rate={fps}:duration={seconds}',
            '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-crf', '20',
            str(path),
        ],
        check=True,
    )


def test_cmos_source_mp4_probe_letterbox_streaming_and_lcd_integration(tmp_path):
    mp4 = tmp_path / 'sample_wide.mp4'
    _make_sample_mp4(mp4, width=800, height=400, fps=24, seconds=2)

    assert cmos_source.is_video_path(mp4)
    assert not cmos_source.is_video_path(tmp_path / 'still.png')
    meta = cmos_source.probe_video(mp4)
    assert meta['width'] == 800 and meta['height'] == 400
    assert abs(meta['src_fps'] - 24.0) < 0.2

    jpeg0, _ = cmos_source.read_first_video_frame_jpeg(mp4)
    assert jpeg0.startswith(b'\xff\xd8')

    with pytest.raises(ValueError, match='绝对路径'):
        cmos_source.probe_video('relative.mp4')
    bad_mp4 = tmp_path / 'corrupt.mp4'
    bad_mp4.write_bytes(b'not-an-mp4')
    with pytest.raises(ValueError):
        cmos_source.probe_video(bad_mp4)

    fd = fast_shm.create_ram_memfd()
    raw = mmap.mmap(fd, fast_shm.MAP_SIZE, offset=fast_shm.MEMFD_OFFSET)
    published_hashes = []
    lcd_event = threading.Event()

    def on_lcd(payload, info):
        published_hashes.append(info['sha256'])
        if len(published_hashes) >= 4:
            lcd_event.set()

    owner = SimpleNamespace(pid=os.getpid(), poll=lambda: None)
    shm = fast_shm.FastShmView(fd)
    lcd = ContinuousLCD(tmp_path, owner, on_lcd, encode_png=False, fast_shm_fd=fd).start()
    streamer = None
    try:
        raw[fast_shm.OSD0_OFF:fast_shm.OSD0_OFF + fast_shm.OSD_BYTES] = b'\x00\x00' * (fast_shm.WIDTH * fast_shm.HEIGHT)
        struct.pack_into('<I', raw, fast_shm.CTRL_OFF + fast_shm.OFF_GUEST_DISPLAY_READY, 1)
        struct.pack_into('<QII', raw, fast_shm.CTRL_OFF + fast_shm.OFF_OSD_SEQ, 1, 0, fast_shm.FLAG_SHOOTING)

        frame_digests = []
        streamer = cmos_source.VideoCmosStreamer(
            mp4,
            lambda rgb: (frame_digests.append(hashlib.sha256(rgb).hexdigest()), shm.set_custom_cmos(rgb)),
        ).start()
        assert streamer.frames_emitted >= 1
        assert lcd_event.wait(3.0), f'expected animated LCD updates, got {len(published_hashes)}'

        # Verify letterboxing top bar (800x400 -> 640x320 centered vertically -> row 10 is #101010 pad bar).
        active_rgb, kind = shm.read_active_cmos_rgb24()
        assert kind == 'custom' and len(active_rgb) == fast_shm.RGB_BYTES
        bar_px = tuple(active_rgb[(10 * 640 + 320) * 3:(10 * 640 + 320) * 3 + 3])
        assert max(abs(c - 16) for c in bar_px) <= 2, f'expected dark letterbox bar, got {bar_px}'

        # Confirm frames actually advance (multiple unique frame hashes over time).
        deadline = time.monotonic() + 1.5
        while len(set(frame_digests)) < 6 and time.monotonic() < deadline:
            time.sleep(0.02)
        assert len(set(frame_digests)) >= 6
        assert len(set(published_hashes)) >= 4
    finally:
        if streamer is not None:
            streamer.stop()
        lcd.stop()
        shm.close()
        raw.close()
        os.close(fd)


def test_video_record_manager_captures_mp4_cmos_to_playable_sd_clip(tmp_path):
    src_mp4 = tmp_path / 'input_source.mp4'
    _make_sample_mp4(src_mp4, width=640, height=480, fps=24, seconds=2)

    fd = fast_shm.create_ram_memfd()
    raw = mmap.mmap(fd, fast_shm.MAP_SIZE, offset=fast_shm.MEMFD_OFFSET)
    stop = threading.Event()
    sd_clip_file = tmp_path / 'C0001.MP4'
    written_data = bytearray()
    shm = fast_shm.FastShmView(fd)
    rec_mgr = VideoRecordManager(shm, tmp_path / 'run').start()
    streamer = None

    def fnv64(data: bytes) -> int:
        h = 14695981039346656037
        for b in data:
            h = ((h ^ b) * 1099511628211) & 0xFFFFFFFFFFFFFFFF
        return h

    def guest_fsys_worker():
        struct.pack_into('<I', raw, fast_shm.VIDEO_CTRL_OFF + fast_shm.OFF_V_GUEST_READY, 1)
        handled = 0
        while not stop.is_set():
            req_seq = struct.unpack_from('<I', raw, fast_shm.VIDEO_CTRL_OFF + fast_shm.OFF_V_XFER_REQ_SEQ)[0]
            if req_seq == handled:
                time.sleep(0.002)
                continue
            op, length, _, total, exp_hash = struct.unpack_from(
                '<IIIQQ', raw, fast_shm.VIDEO_CTRL_OFF + fast_shm.OFF_V_XFER_OP,
            )
            if op == fast_shm.VIDEO_OP_BEGIN:
                written_data.clear()
                p = b'A:/PRIVATE/M4ROOT/CLIP/C0001.MP4\x00'
                raw[fast_shm.VIDEO_CTRL_OFF + fast_shm.OFF_V_XFER_GUEST_PATH:
                    fast_shm.VIDEO_CTRL_OFF + fast_shm.OFF_V_XFER_GUEST_PATH + len(p)] = p
                struct.pack_into('<i', raw, fast_shm.VIDEO_CTRL_OFF + fast_shm.OFF_V_XFER_STATUS, 0)
            elif op == fast_shm.VIDEO_OP_CHUNK:
                written_data.extend(raw[fast_shm.VIDEO_BUF_OFF:fast_shm.VIDEO_BUF_OFF + length])
                struct.pack_into('<i', raw, fast_shm.VIDEO_CTRL_OFF + fast_shm.OFF_V_XFER_STATUS, 0)
            elif op == fast_shm.VIDEO_OP_COMMIT:
                got_hash = fnv64(bytes(written_data))
                ok = 1 if len(written_data) == total and got_hash == exp_hash else 0
                if ok:
                    sd_clip_file.write_bytes(written_data)
                struct.pack_into('<iIIQQ', raw, fast_shm.VIDEO_CTRL_OFF + fast_shm.OFF_V_XFER_STATUS,
                                 0 if ok else -5, 1, ok, len(written_data), got_hash)
            handled = req_seq
            struct.pack_into('<I', raw, fast_shm.VIDEO_CTRL_OFF + fast_shm.OFF_V_XFER_ACK_SEQ, req_seq)

    gw = threading.Thread(target=guest_fsys_worker, daemon=True)
    gw.start()
    try:
        deadline = time.monotonic() + 2.0
        while not shm.guest_video_ready() and time.monotonic() < deadline:
            time.sleep(0.002)
        assert shm.guest_video_ready()

        # Stream animated local MP4 into CMOS while recording!
        streamer = cmos_source.VideoCmosStreamer(src_mp4, shm.set_custom_cmos).start()
        time.sleep(0.15)

        # Simulate REC #1 press.
        struct.pack_into('<I', raw, fast_shm.VIDEO_CTRL_OFF + fast_shm.OFF_V_REC_TOGGLE_SEQ, 1)
        snap1 = rec_mgr.wait_after_rec_key(0)
        assert snap1['active'] is True and not snap1['saving']

        # Record ~1.2 seconds of animated CMOS frames.
        time.sleep(1.2)
        assert rec_mgr.snapshot()['frames'] >= 20

        # Simulate REC #2 press -> stop, encode/mux H.264 MP4, stream chunks to guest SD!
        struct.pack_into('<I', raw, fast_shm.VIDEO_CTRL_OFF + fast_shm.OFF_V_REC_TOGGLE_SEQ, 2)
        snap2 = rec_mgr.wait_after_rec_key(1)
        assert snap2['active'] is False and snap2['saving'] is False
        assert snap2['error'] == ''
        clip = snap2['last_clip']
        assert clip is not None and clip['ok'] is True
        assert clip['path'] == 'A:/PRIVATE/M4ROOT/CLIP/C0001.MP4'
        assert clip['readback_verified'] is True
        assert clip['frames'] >= 20
        assert sd_clip_file.is_file() and sd_clip_file.stat().st_size == clip['bytes']

        # Verify written SD MP4 with ffprobe & real frame decoding!
        probe = json.loads(subprocess.check_output([
            '/usr/bin/ffprobe', '-v', 'error', '-select_streams', 'v:0',
            '-show_entries', 'stream=codec_name,width,height,nb_frames,duration',
            '-show_entries', 'format=format_name,size',
            '-of', 'json', str(sd_clip_file),
        ], text=True))
        st = probe['streams'][0]
        assert st['codec_name'] == 'h264'
        assert st['width'] == 640 and st['height'] == 480
        assert float(st['duration']) >= 0.8

        decoded = subprocess.check_output([
            '/usr/bin/ffmpeg', '-nostdin', '-hide_banner', '-loglevel', 'error',
            '-i', str(sd_clip_file), '-pix_fmt', 'rgb24', '-f', 'rawvideo', 'pipe:1',
        ])
        n_decoded = len(decoded) // fast_shm.RGB_BYTES
        assert n_decoded >= 20
        frame_hashes = {
            hashlib.sha256(decoded[i * fast_shm.RGB_BYTES:(i + 1) * fast_shm.RGB_BYTES]).hexdigest()
            for i in range(n_decoded)
        }
        assert len(frame_hashes) >= 5, f'recorded MP4 frames should visibly animate, got {len(frame_hashes)}'

        receipt = json.loads((tmp_path / 'run/last-video-record.json').read_text())
        assert receipt['ok'] is True and receipt['path'] == 'A:/PRIVATE/M4ROOT/CLIP/C0001.MP4'
    finally:
        if streamer is not None:
            streamer.stop()
        rec_mgr.close()
        stop.set()
        shm.close()
        raw.close()
        os.close(fd)
