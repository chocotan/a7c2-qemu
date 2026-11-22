"""Unit tests for shared-memory virtual CP display compositor and direct App32 input ring."""
import ctypes
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

import fast_shm
from continuous_lcd import ContinuousLCD

BASE = Path(__file__).resolve().parent


def test_c_header_and_python_abi_offsets_match():
    code = r'''
#include <stdio.h>
#include <stddef.h>
#include "fast-shm.h"
int main(void) {
    printf("%u %u %lu %u %u %u %u %u %u %zu %zu %zu %zu %zu %zu %zu %zu %zu %zu\n",
        FAST_SHM_MAGIC, FAST_SHM_VERSION,
        (unsigned long)FAST_SHM_MEMFD_OFFSET, FAST_SHM_MAP_SIZE,
        FAST_SHM_PLAYBACK_BG_OFF, FAST_SHM_CUSTOM_CMOS_OFF,
        FAST_SHM_OSD0_OFF, FAST_SHM_OSD1_OFF, FAST_SHM_CTRL_OFF,
        offsetof(struct fast_shm_ctrl, guest_display_ready),
        offsetof(struct fast_shm_ctrl, guest_input_ready),
        offsetof(struct fast_shm_ctrl, osd_seq),
        offsetof(struct fast_shm_ctrl, osd_slot),
        offsetof(struct fast_shm_ctrl, display_flags),
        offsetof(struct fast_shm_ctrl, playback_bg_seq),
        offsetof(struct fast_shm_ctrl, blink_seq),
        offsetof(struct fast_shm_ctrl, custom_cmos_active),
        offsetof(struct fast_shm_ctrl, key_head),
        offsetof(struct fast_shm_ctrl, ring));
    return 0;
}
'''
    with tempfile.TemporaryDirectory() as tmp:
        exe = Path(tmp) / 'abi'
        subprocess.run(
            ['cc', '-x', 'c', '-', '-I', str(BASE), '-Wall', '-Wextra', '-Werror', '-o', str(exe)],
            input=code, text=True, check=True, capture_output=True,
        )
        out = subprocess.run([str(exe)], text=True, check=True, capture_output=True).stdout.strip().split()
    vals = [int(x) for x in out]
    expected = [
        fast_shm.MAGIC, fast_shm.VERSION,
        fast_shm.MEMFD_OFFSET, fast_shm.MAP_SIZE,
        fast_shm.PLAYBACK_BG_OFF, fast_shm.CUSTOM_CMOS_OFF,
        fast_shm.OSD0_OFF, fast_shm.OSD1_OFF, fast_shm.CTRL_OFF,
        fast_shm.OFF_GUEST_DISPLAY_READY,
        fast_shm.OFF_GUEST_INPUT_READY,
        fast_shm.OFF_OSD_SEQ,
        fast_shm.OFF_OSD_SLOT,
        fast_shm.OFF_DISPLAY_FLAGS,
        fast_shm.OFF_PLAYBACK_BG_SEQ,
        fast_shm.OFF_BLINK_SEQ,
        fast_shm.OFF_CUSTOM_CMOS_ACTIVE,
        fast_shm.OFF_KEY_HEAD,
        fast_shm.OFF_RING,
    ]
    assert vals == expected


def test_native_c_blender_matches_ramfb_viewer_formula_for_all_65536_rgba4444_values():
    lib = fast_shm._load_blend_lib()
    assert lib is not None, 'fast-osd-blend.so should be built by build-observers.sh'

    # Pack all 65,536 possible RGBA4444 values into the first 65,536 pixels of a 640x480 frame.
    pixels = fast_shm.WIDTH * fast_shm.HEIGHT
    osd = (ctypes.c_uint16 * pixels)()
    bg = (ctypes.c_ubyte * fast_shm.RGB_BYTES)()
    out_nobg = (ctypes.c_ubyte * fast_shm.RGB_BYTES)()
    out_bg = (ctypes.c_ubyte * fast_shm.RGB_BYTES)()

    for i in range(65536):
        osd[i] = i
        bg[3 * i + 0] = (i * 37) & 0xFF
        bg[3 * i + 1] = (i * 73 + 19) & 0xFF
        bg[3 * i + 2] = (i * 113 + 7) & 0xFF

    t0 = time.monotonic()
    lib.fast_blend_rgba4444_over_rgb24(osd, None, out_nobg, 0)
    lib.fast_blend_rgba4444_over_rgb24(osd, bg, out_bg, 1)
    elapsed_ms = (time.monotonic() - t0) * 1000.0
    assert elapsed_ms < 50.0, f'Two native 640x480 blends should be sub-millisecond, got {elapsed_ms:.2f}ms'

    for v in range(65536):
        r = (v >> 12) * 17
        g = ((v >> 8) & 15) * 17
        b = ((v >> 4) & 15) * 17
        a = v & 15
        # Reference formula from ramfb-viewer.c:231-235 & 266-281
        assert out_nobg[3 * v + 0] == (r * a + 7) // 15
        assert out_nobg[3 * v + 1] == (g * a + 7) // 15
        assert out_nobg[3 * v + 2] == (b * a + 7) // 15

        br, bgc, bb = bg[3 * v + 0], bg[3 * v + 1], bg[3 * v + 2]
        if a == 0:
            er, eg, eb = br, bgc, bb
        elif a == 15:
            er, eg, eb = r, g, b
        else:
            inv = 15 - a
            er = (r * a + br * inv + 7) // 15
            eg = (g * a + bgc * inv + 7) // 15
            eb = (b * a + bb * inv + 7) // 15
        assert (out_bg[3 * v + 0], out_bg[3 * v + 1], out_bg[3 * v + 2]) == (er, eg, eb)


def test_fast_shm_view_display_modes_and_clean_close():
    fd = fast_shm.create_ram_memfd()
    try:
        shm = fast_shm.FastShmView(fd)
        raw = mmap.mmap(fd, fast_shm.MAP_SIZE, offset=fast_shm.MEMFD_OFFSET)
        try:
            assert not shm.guest_display_ready()
            struct.pack_into('<I', raw, fast_shm.CTRL_OFF + fast_shm.OFF_GUEST_DISPLAY_READY, 1)
            assert shm.guest_display_ready()

            # Fill slot 0 with fully transparent RGBA4444 (0x0000), slot 1 with opaque red (0xF00F).
            raw[fast_shm.OSD0_OFF:fast_shm.OSD0_OFF + fast_shm.OSD_BYTES] = b'\x00\x00' * (fast_shm.WIDTH * fast_shm.HEIGHT)
            raw[fast_shm.OSD1_OFF:fast_shm.OSD1_OFF + fast_shm.OSD_BYTES] = struct.pack('<H', 0xF00F) * (fast_shm.WIDTH * fast_shm.HEIGHT)

            # 1) Non-shooting transparent slot 0 -> pure black.
            struct.pack_into('<QII', raw, fast_shm.CTRL_OFF + fast_shm.OFF_OSD_SEQ, 1, 0, 0)
            frame, seq = shm.render_rgb24()
            assert seq == 1 and len(frame) == fast_shm.RGB_BYTES
            assert frame[:6] == b'\x00\x00\x00\x00\x00\x00'

            # 2) Shooting HUD with default color chart -> non-black chart pixels.
            struct.pack_into('<QII', raw, fast_shm.CTRL_OFF + fast_shm.OFF_OSD_SEQ, 2, 0, fast_shm.FLAG_SHOOTING)
            frame, seq = shm.render_rgb24()
            assert seq == 2 and frame == fast_shm.default_chart_rgb24()

            # 3) Custom CMOS RGB24 swap -> shows custom pixels immediately.
            custom = bytes((12, 180, 95)) * (fast_shm.WIDTH * fast_shm.HEIGHT)
            shm.set_custom_cmos(custom)
            frame, _ = shm.render_rgb24()
            assert frame[:3] == b'\x0c\xb4\x5f'

            # 4) Playback BG flag overrides shooting/custom CMOS.
            pb = bytes((210, 40, 170)) * (fast_shm.WIDTH * fast_shm.HEIGHT)
            raw[fast_shm.PLAYBACK_BG_OFF:fast_shm.PLAYBACK_BG_OFF + fast_shm.RGB_BYTES] = pb
            struct.pack_into('<QIII', raw, fast_shm.CTRL_OFF + fast_shm.OFF_OSD_SEQ,
                             3, 0, fast_shm.FLAG_SHOOTING | fast_shm.FLAG_PLAYBACK_BG, 1)
            frame, seq = shm.render_rgb24()
            assert seq == 3 and frame[:3] == b'\xd2\x28\xaa'

            # 5) Switch to slot 1 opaque red OSD -> OSD covers BG.
            struct.pack_into('<QII', raw, fast_shm.CTRL_OFF + fast_shm.OFF_OSD_SEQ,
                             4, 1, fast_shm.FLAG_PLAYBACK_BG)
            frame, seq = shm.render_rgb24()
            assert seq == 4 and frame[:3] == b'\xff\x00\x00'

            # 6) Revert custom CMOS to None.
            shm.set_custom_cmos(None)
            assert struct.unpack_from('<I', raw, fast_shm.CTRL_OFF + fast_shm.OFF_CUSTOM_CMOS_ACTIVE)[0] == 0
        finally:
            raw.close()
            shm.close()  # Must not raise BufferError
            shm.close()  # Idempotent
    finally:
        os.close(fd)


def test_continuous_lcd_fast_shm_streams_frames_and_shutter_blink(tmp_path):
    fd = fast_shm.create_ram_memfd()
    received = []
    ev = threading.Event()

    def on_frame(payload, info):
        received.append((payload[:3], info))
        ev.set()

    owner = SimpleNamespace(pid=os.getpid(), poll=lambda: None)
    lcd = ContinuousLCD(tmp_path, owner, on_frame, encode_png=False, fast_shm_fd=fd).start()
    raw = mmap.mmap(fd, fast_shm.MAP_SIZE, offset=fast_shm.MEMFD_OFFSET)
    try:
        raw[fast_shm.OSD0_OFF:fast_shm.OSD0_OFF + fast_shm.OSD_BYTES] = struct.pack('<H', 0x0F0F) * (fast_shm.WIDTH * fast_shm.HEIGHT)
        struct.pack_into('<I', raw, fast_shm.CTRL_OFF + fast_shm.OFF_GUEST_DISPLAY_READY, 1)
        struct.pack_into('<QII', raw, fast_shm.CTRL_OFF + fast_shm.OFF_OSD_SEQ, 1, 0, 0)
        lcd.nudge()
        assert ev.wait(2.0), lcd.error
        assert received[0][0] == b'\x00\xff\x00'
        assert received[0][1]['source'] == 'fast-shm virtual CP display'

        # Trigger shutter blink: should emit black frame then restore green frame.
        before = len(received)
        struct.pack_into('<I', raw, fast_shm.CTRL_OFF + fast_shm.OFF_BLINK_SEQ, 1)
        lcd.nudge()
        deadline = time.monotonic() + 2.0
        while len(received) < before + 2 and time.monotonic() < deadline:
            time.sleep(0.01)
        assert len(received) >= before + 2
        assert received[before][0] == b'\x00\x00\x00'
        assert received[before + 1][0] == b'\x00\xff\x00'

        lcd.stop()
        assert not lcd.thread.is_alive()
        assert not lcd.error
        report = (tmp_path / 'lcd-continuous-result.json').read_text()
        assert 'fast-shm virtual CP display' in report
    finally:
        lcd.stop()
        raw.close()
        os.close(fd)


def test_fast_shm_app_input_ring_and_fallback():
    fd = fast_shm.create_ram_memfd()
    shm = fast_shm.FastShmView(fd)
    raw = mmap.mmap(fd, fast_shm.MAP_SIZE, offset=fast_shm.MEMFD_OFFSET)
    stop = threading.Event()
    consumed = []

    def fake_guest_worker():
        struct.pack_into('<I', raw, fast_shm.CTRL_OFF + fast_shm.OFF_GUEST_INPUT_READY, 1)
        while not stop.is_set():
            tail = struct.unpack_from('<Q', raw, fast_shm.CTRL_OFF + fast_shm.OFF_KEY_TAIL)[0]
            head = struct.unpack_from('<Q', raw, fast_shm.CTRL_OFF + fast_shm.OFF_KEY_HEAD)[0]
            if tail == head:
                time.sleep(0.001)
                continue
            off = fast_shm.CTRL_OFF + fast_shm.OFF_RING + (tail & fast_shm.RING_MASK) * fast_shm.RING_CMD_STRUCT.size
            cmd = fast_shm.RING_CMD_STRUCT.unpack_from(raw, off)
            consumed.append(cmd)
            rc = 4 if cmd[2] == 0x999 else 0
            struct.pack_into('<i', raw, fast_shm.CTRL_OFF + fast_shm.OFF_KEY_LAST_RC, rc)
            struct.pack_into('<Q', raw, fast_shm.CTRL_OFF + fast_shm.OFF_KEY_TAIL, tail + 1)
            struct.pack_into('<Q', raw, fast_shm.CTRL_OFF + fast_shm.OFF_KEY_ACK_SEQ, cmd[0])

    fallback_log = []

    class FakeFallback:
        def start(self): fallback_log.append('start')
        def pause(self): fallback_log.append('pause')
        def __call__(self, cmd): fallback_log.append(('call', cmd)); return b'SERIAL_OK\n'
        def tap(self, key, hold_us=20000): fallback_log.append(('tap', key, hold_us)); return b'SERIAL_TAP\n'

    fb = FakeFallback()
    proc = SimpleNamespace(poll=lambda: None)
    app = fast_shm.FastShmAppInput(shm, fb, proc, SimpleNamespace(check=lambda: None))
    try:
        # Before guest input ready -> falls back cleanly to serial.
        assert app('/simulation/inject-key --app 0x5503e0 0x5503e0 0x1ab 0 1 0 0') == b'SERIAL_OK\n'
        assert app.fallback_calls == 1 and app.fast_calls == 0

        # Start simulated guest fast_input_worker.
        worker = threading.Thread(target=fake_guest_worker, daemon=True)
        worker.start()
        deadline = time.monotonic() + 2.0
        while not shm.guest_input_ready() and time.monotonic() < deadline:
            time.sleep(0.002)
        assert shm.guest_input_ready()

        # start() must NOT start fallback serial server when fast-shm input is ready.
        fallback_log.clear()
        app.start()
        assert fallback_log == []

        t0 = time.monotonic()
        for i in range(10):
            res = app('/simulation/inject-key --app 0x5503e0 0x5503e0 0x1ab 0 1 0 0')
            assert res.startswith(b'FAST_SHM_INPUT_RESULT ')
        elapsed_ms = (time.monotonic() - t0) * 1000.0
        assert elapsed_ms < 200.0, f'10 fast-shm events took {elapsed_ms:.1f}ms'

        tap_res = app.tap(0x30, hold_us=15000)
        assert tap_res.startswith(b'FAST_SHM_INPUT_RESULT ')
        assert consumed[-1][1] == fast_shm.KEY_OP_TAP and consumed[-1][2] == 0x30 and consumed[-1][7] == 15000

        with pytest.raises(RuntimeError, match='rc=4'):
            app('/simulation/inject-key --app 0x5503e0 0x5503e0 0x999 0 1 0 0')
        with pytest.raises(ValueError):
            app('/simulation/inject-key --app 1 1 0x1ab 0 1 0 0')
        assert app.fast_calls == 12
    finally:
        stop.set()
        raw.close()
        shm.close()
        os.close(fd)


def test_gui_model_store_skips_vfat_writes_after_packet_1_in_fast_shm_mode():
    fixture = r'''
#include "gui-model-store.h"
#include <assert.h>
#include <stdlib.h>
#include <string.h>
static unsigned int stop, freed, saved;
static unsigned char packet[748];
static void put(unsigned int at, unsigned int n) { memcpy(packet + at, &n, 4); }
static int receive(unsigned int q, void **p, long t) { (void)q; (void)t; *p = packet; return 0; }
static unsigned int size(void *p) { (void)p; return sizeof packet; }
static int release(unsigned int q, void *p) { (void)q; (void)p; freed++; return 0; }
static int persist(const char *path, const unsigned char *raw, unsigned long n) {
    (void)path; (void)raw; (void)n; saved++; return 0;
}
static void logline(const char *a, const char *b) { (void)a; (void)b; }
int main(void) {
    unsigned int types[]={0x10,0x15,0x16,0x19,0x1a,0x1b}, sizes[]={0x274,12,20,12,4,16}, off=8;
    put(4, sizeof packet - 8);
    for (unsigned int i=0; i<6; i++) { put(off, types[i]); put(off+4, sizes[i]); off += 8 + sizes[i]; }
    struct gui_model_store s = {0};
    struct gui_model_store_ops ops = {receive, size, release, persist, logline, &stop};
    setenv("MENU_FAST_SHM", "1", 1);
    for (int i = 0; i < 10; ++i) assert(gui_model_store_step(&s, &ops, "snap") == 0);
    assert(s.packets == 10 && freed == 10 && saved == 1);
    return 0;
}
'''
    with tempfile.TemporaryDirectory() as tmp:
        exe = Path(tmp) / 'gmdl_fast'
        subprocess.run(
            ['cc', '-x', 'c', '-', str(BASE / 'gui-model-store.c'), str(BASE / 'gui-model-wire.c'),
             '-I', str(BASE), '-Wall', '-Wextra', '-Werror', '-o', str(exe)],
            input=fixture, text=True, check=True, capture_output=True,
        )
        subprocess.run([str(exe)], check=True, timeout=10)


def test_headless_osd_fast_sink_skips_vfat_persist_and_unchanged_1005():
    fixture = r'''
#include "headless-osd.h"
#include <assert.h>
#include <stdlib.h>
#include <string.h>
static unsigned char slot_buf[2][HOSD_PIXELS];
static unsigned int next_slot, publish_calls, capture_calls, last_pixels_updated, ack_sent, stop;
static unsigned char msg_fix[12], msg_desc[36], msg_1005[8], msg_ack[8];
static int step_idx;
static void put16(unsigned char *p, unsigned int v) { p[0] = v & 255; p[1] = v >> 8; }
static void put32(unsigned char *p, unsigned int v) { for (int i=0;i<4;i++) p[i] = (v >> (8*i)) & 255; }
static unsigned char *acquire(unsigned int *slot_out) {
    *slot_out = next_slot & 1u;
    next_slot ^= 1u;
    return slot_buf[*slot_out];
}
static void publish(unsigned int slot, unsigned long seq, unsigned long pseq,
                    unsigned int fid, unsigned long phys, int shooting, int pix_upd) {
    (void)slot; (void)seq; (void)pseq; (void)fid; (void)phys; (void)shooting;
    publish_calls++;
    last_pixels_updated = (unsigned int)pix_upd;
}
static int rcv(unsigned int q, void **m, long t) {
    (void)q; (void)t;
    if (step_idx == 0) { *m = msg_fix; put16(msg_fix, 0x1002); put32(msg_fix + 8, 0x1003); }
    else if (step_idx == 1) {
        *m = msg_desc; memset(msg_desc, 0, sizeof msg_desc);
        put16(msg_desc, 0x1003); put32(msg_desc + 8, 42);
        put16(msg_desc + 0x14, 640); put16(msg_desc + 0x16, 480);
    }
    else if (step_idx == 2) { *m = msg_fix; put16(msg_fix, 0x1002); put32(msg_fix + 8, 0x1005); }
    else { *m = msg_1005; memset(msg_1005, 0, sizeof msg_1005); put16(msg_1005, 0x1005); }
    step_idx++;
    return 0;
}
static unsigned int sz(void *m) { return m == msg_fix ? 12 : m == msg_desc ? 36 : 8; }
static unsigned int src(void *m) { (void)m; return HOSD_AP; }
static int rel(unsigned int q, void *m) { (void)q; (void)m; return 0; }
static int alloc_m(unsigned int q, void **m, unsigned int n, unsigned int c) {
    (void)q; (void)n; (void)c; *m = msg_ack; return 0;
}
static void set_src(void *m, unsigned int s) { (void)m; (void)s; }
static int snd(unsigned int q, void *m) { (void)q; (void)m; ack_sent++; return 0; }
static int frame_cap(struct hosd_frame *f, unsigned char *dst) {
    capture_calls++;
    f->physical = 0x420000000UL;
    memset(dst, 0xAB, HOSD_PIXELS);
    return 0;
}
static void log_fn(const char *a, const char *b) { (void)a; (void)b; }
int main(void) {
    struct hosd_fast_sink sink = {acquire, publish};
    hosd_set_fast_sink(&sink);
    struct hosd_state *st = calloc(1, sizeof *st);
    struct hosd_ops ops = {rcv, sz, src, rel, alloc_m, set_src, snd, frame_cap, log_fn, &stop};
    /* Pass an invalid path: proves hosd_persist was NEVER touched! */
    for (int i = 0; i < 4; ++i) assert(hosd_step(st, &ops, "/nonexistent/dir/should-not-write") == 0);
    assert(capture_calls == 1 && publish_calls == 1 && last_pixels_updated == 1 && ack_sent == 2);
    assert(slot_buf[0][0] == 0xAB && slot_buf[0][HOSD_PIXELS - 1] == 0xAB);
    assert(hosd_is_shooting_scene() == 0);
    hosd_set_screen_liveview(1);
    assert(hosd_is_shooting_scene() == 1);
    hosd_set_screen_liveview(0);
    assert(hosd_is_shooting_scene() == 1); /* retained until next metadata commit */
    free(st);
    return 0;
}
'''
    with tempfile.TemporaryDirectory() as tmp:
        exe = Path(tmp) / 'hosd_fast'
        subprocess.run(
            ['cc', '-x', 'c', '-', str(BASE / 'headless-osd.c'),
             '-I', str(BASE), '-Wall', '-Wextra', '-Werror', '-o', str(exe)],
            input=fixture, text=True, check=True, capture_output=True,
        )
        subprocess.run([str(exe)], check=True, timeout=10)


def test_continuous_lcd_shutter_blink_rereads_post_sleep_state(tmp_path):
    """Frame updates arriving during the 55ms shutter blink must be rendered immediately after."""
    fd = fast_shm.create_ram_memfd()
    received = []
    blink_seen = threading.Event()
    post_blink_blue = threading.Event()

    def on_frame(payload, info):
        px = payload[:3]
        received.append((px, info))
        if px == b'\x00\x00\x00':
            blink_seen.set()
        elif blink_seen.is_set() and px == b'\x00\x00\xff':
            post_blink_blue.set()

    owner = SimpleNamespace(pid=os.getpid(), poll=lambda: None)
    lcd = ContinuousLCD(tmp_path, owner, on_frame, encode_png=False, fast_shm_fd=fd).start()
    raw = mmap.mmap(fd, fast_shm.MAP_SIZE, offset=fast_shm.MEMFD_OFFSET)
    try:
        # Slot 0 = green, Slot 1 = blue.
        raw[fast_shm.OSD0_OFF:fast_shm.OSD0_OFF + fast_shm.OSD_BYTES] = struct.pack('<H', 0x0F0F) * (fast_shm.WIDTH * fast_shm.HEIGHT)
        raw[fast_shm.OSD1_OFF:fast_shm.OSD1_OFF + fast_shm.OSD_BYTES] = struct.pack('<H', 0x00FF) * (fast_shm.WIDTH * fast_shm.HEIGHT)
        struct.pack_into('<I', raw, fast_shm.CTRL_OFF + fast_shm.OFF_GUEST_DISPLAY_READY, 1)
        struct.pack_into('<QII', raw, fast_shm.CTRL_OFF + fast_shm.OFF_OSD_SEQ, 1, 0, 0)
        lcd.nudge()
        deadline = time.monotonic() + 2.0
        while not received and time.monotonic() < deadline:
            time.sleep(0.01)
        assert received and received[0][0] == b'\x00\xff\x00'

        # Trigger blink, then flip to slot 1 (blue) while ContinuousLCD is inside the 55ms blink sleep.
        struct.pack_into('<I', raw, fast_shm.CTRL_OFF + fast_shm.OFF_BLINK_SEQ, 1)
        lcd.nudge()
        assert blink_seen.wait(2.0), 'shutter blink black frame not emitted'
        struct.pack_into('<QII', raw, fast_shm.CTRL_OFF + fast_shm.OFF_OSD_SEQ, 2, 1, 0)
        assert post_blink_blue.wait(2.0), f'expected post-blink blue frame, got {[p for p, _ in received]}'
    finally:
        lcd.stop()
        raw.close()
        os.close(fd)

