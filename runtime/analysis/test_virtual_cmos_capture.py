#!/usr/bin/env python3
"""Host ASan/UBSan tests for virtual CMOS JPEG+EXIF encoder, decoder, SD write, and Playback."""
import ctypes
from pathlib import Path
import re
import struct
import subprocess
import tempfile

from PIL import Image
import pytest

HERE = Path(__file__).resolve().parent
CAPTURE_C = HERE / 'device-models/virtual-cmos-capture.c'
LENS_C = HERE / 'device-models/virtual-lens-hud.c'
SENSOR_C = HERE.parents[1] / 'report/virtual-sensor/sensor-core.c'


def _build_harness(tmp_dir: Path) -> Path:
    harness = tmp_dir / 'harness.c'
    binary = tmp_dir / 'harness'
    harness.write_text(
        r'''
#include <assert.h>
#include <errno.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <unistd.h>
#include "virtual-cmos-capture.h"

/* Minimal in-memory virtual FAT filesystem implementing Fsys_* ops. */
#define MAX_FILES 32
struct mem_file {
    int used;
    char path[64];
    uint8_t *data;
    size_t len, cap;
};
struct mem_handle {
    int used;
    int file_idx;
    size_t pos;
    int writable;
};
static struct mem_file g_files[MAX_FILES];
static struct mem_handle g_handles[16];
static int g_flushes;

static unsigned int fake_drives(void) { return 1u; } /* 'A' */
static int fake_mkdir(const char *path) { (void)path; return 0; }
static int fake_open(const char *path, uint64_t *handle, unsigned int flags) {
    int found = -1;
    for (int i = 0; i < MAX_FILES; ++i)
        if (g_files[i].used && strcmp(g_files[i].path, path) == 0) { found = i; break; }
    if (flags == 1u) {
        if (found < 0) return -1;
    } else {
        if (found < 0) {
            for (int i = 0; i < MAX_FILES; ++i)
                if (!g_files[i].used) { found = i; break; }
            if (found < 0) return -1;
            g_files[found].used = 1;
            snprintf(g_files[found].path, sizeof g_files[found].path, "%s", path);
            g_files[found].len = 0;
        } else {
            g_files[found].len = 0;
        }
    }
    for (int h = 0; h < 16; ++h) {
        if (!g_handles[h].used) {
            g_handles[h].used = 1;
            g_handles[h].file_idx = found;
            g_handles[h].pos = 0;
            g_handles[h].writable = (flags != 1u);
            *handle = (uint64_t)(h + 1);
            return 0;
        }
    }
    return -1;
}
static int fake_write(uint64_t handle, const void *buf, int len) {
    int h = (int)handle - 1;
    if (h < 0 || h >= 16 || !g_handles[h].used || !g_handles[h].writable || len < 0) return -1;
    struct mem_file *f = &g_files[g_handles[h].file_idx];
    size_t need = g_handles[h].pos + (size_t)len;
    if (need > f->cap) {
        size_t next = f->cap ? f->cap * 2 : 65536;
        while (next < need) next *= 2;
        uint8_t *p = realloc(f->data, next);
        if (!p) return -1;
        f->data = p; f->cap = next;
    }
    memcpy(f->data + g_handles[h].pos, buf, (size_t)len);
    g_handles[h].pos += (size_t)len;
    if (g_handles[h].pos > f->len) f->len = g_handles[h].pos;
    return len;
}
static int fake_read(uint64_t handle, void *buf, int len) {
    int h = (int)handle - 1;
    if (h < 0 || h >= 16 || !g_handles[h].used || len < 0) return -1;
    struct mem_file *f = &g_files[g_handles[h].file_idx];
    if (g_handles[h].pos >= f->len) return 0;
    size_t avail = f->len - g_handles[h].pos;
    if ((size_t)len < avail) avail = (size_t)len;
    memcpy(buf, f->data + g_handles[h].pos, avail);
    g_handles[h].pos += avail;
    return (int)avail;
}
static int fake_flush(uint64_t handle) { (void)handle; return 0; }
static int fake_close(uint64_t handle) {
    int h = (int)handle - 1;
    if (h < 0 || h >= 16 || !g_handles[h].used) return -1;
    g_handles[h].used = 0;
    return 0;
}
static int fake_remove(const char *path) {
    for (int i = 0; i < MAX_FILES; ++i) {
        if (g_files[i].used && strcmp(g_files[i].path, path) == 0) {
            free(g_files[i].data);
            memset(&g_files[i], 0, sizeof g_files[i]);
            return 0;
        }
    }
    return -1;
}
static int fake_flush_volume(unsigned char drive) {
    assert(drive == 'A');
    ++g_flushes;
    return 0;
}

int main(int argc, char **argv) {
    assert(argc == 5);
    const char *out_jpg = argv[1];
    const char *custom_rgb = argv[2];
    const char *pb_frame = argv[3];
    const char *pb_bg = argv[4];

    struct virtual_lens_hud_state hud;
    virtual_lens_hud_init_defaults(&hud);
    assert(virtual_lens_hud_step_aperture(&hud, 2) == 0 && hud.aperture_x100 == 500);
    assert(virtual_lens_hud_step_shutter(&hud, 1) == 0 && hud.shutter_num == 1 && hud.shutter_den == 250);
    assert(virtual_lens_hud_step_iso(&hud, 3) == 0 && virtual_lens_hud_iso_value(hud.iso_cp_byte) == 200);

    const struct virtual_cmos_fsys_ops ops = {
        fake_drives, fake_mkdir, fake_open, fake_write, fake_read,
        fake_flush, fake_close, fake_remove, fake_flush_volume
    };

    /* 1. Capture default color chart -> DSC00001.JPG */
    struct virtual_cmos_capture_result r1;
    assert(virtual_cmos_capture_to_sd(&ops, "/nonexistent/custom.rgb", &hud, &r1) == 0);
    assert(strcmp(r1.path, "A:/DCIM/100MSDCF/DSC00001.JPG") == 0);
    assert(strcmp(r1.source, "chart") == 0);
    assert(r1.readback_verified == 1 && r1.bytes > 4000 && g_flushes == 1);

    /* Save DSC00001.JPG to host file for Pillow verification. */
    FILE *fp = fopen(out_jpg, "wb");
    assert(fp && fwrite(g_files[0].data, 1, g_files[0].len, fp) == g_files[0].len && fclose(fp) == 0);

    /* 1b. Render decoded native-playback background for DSC00001.JPG */
    assert(virtual_cmos_render_playback_bg(&ops, r1.path, pb_bg, 7u) == 0);
    struct stat bg_st;
    assert(stat(pb_bg, &bg_st) == 0 && (size_t)bg_st.st_size == VIRTUAL_PLAYBACK_FRAME_BYTES);
    assert(virtual_cmos_render_playback_bg(&ops, "A:/DCIM/100MSDCF/MISSING.JPG", pb_bg, 8u) != 0);

    /* 2. Capture custom RGB -> DSC00002.JPG */
    struct virtual_cmos_capture_result r2;
    assert(virtual_cmos_capture_to_sd(&ops, custom_rgb, &hud, &r2) == 0);
    assert(strcmp(r2.path, "A:/DCIM/100MSDCF/DSC00002.JPG") == 0);
    assert(strcmp(r2.source, "custom") == 0);
    assert(r2.readback_verified == 1 && r2.bytes > 2000 && g_flushes == 2);

    /* 3. Playback enter (should select newest = DSC00002.JPG), step left/right, delete, exit */
    struct virtual_cmos_playback_state pb;
    memset(&pb, 0, sizeof pb);
    assert(virtual_cmos_playback_enter(&pb, &ops, pb_frame) == 0);
    assert(pb.active == 1 && pb.count == 2 && pb.index == 1);
    struct stat st;
    assert(stat(pb_frame, &st) == 0 && (size_t)st.st_size == VIRTUAL_PLAYBACK_FRAME_BYTES);
    assert(virtual_cmos_playback_step(&pb, &ops, pb_frame, -1) == 0 && pb.index == 0);
    assert(virtual_cmos_playback_step(&pb, &ops, pb_frame, -1) == 0 && pb.index == 1);
    assert(virtual_cmos_playback_delete(&pb, &ops, pb_frame) == 0 && pb.count == 1 && pb.index == 0);
    assert(virtual_cmos_playback_delete(&pb, &ops, pb_frame) == 0 && pb.count == 0);
    virtual_cmos_playback_exit(&pb, pb_frame);
    assert(pb.active == 0 && stat(pb_frame, &st) != 0);

    /* Clean memory for ASan leak check */
    for (int i = 0; i < MAX_FILES; ++i) free(g_files[i].data);
    puts("VIRTUAL_CMOS_CAPTURE_C_PASS");
    return 0;
}
'''
    )
    subprocess.run(
        [
            'clang', '-O1', '-Wall', '-Wextra', '-Werror',
            '-fsanitize=address,undefined',
            '-I', str(HERE / 'device-models'),
            str(harness), str(CAPTURE_C), str(LENS_C), str(SENSOR_C),
            '-o', str(binary),
        ],
        check=True,
    )
    return binary


def test_virtual_cmos_capture_jpeg_exif_and_playback_roundtrip():
    with tempfile.TemporaryDirectory(prefix='vcmos-test-') as tmp:
        tmp_dir = Path(tmp)
        binary = _build_harness(tmp_dir)
        out_jpg = tmp_dir / 'DSC00001.JPG'
        custom_rgb = tmp_dir / 'custom.rgb'
        pb_frame = tmp_dir / 'playback.bin'
        pb_bg = tmp_dir / 'playback-bg.bin'

        # Synthesize a bright blue/orange gradient custom 640x480 RGB image.
        img = Image.new('RGB', (640, 480))
        px = img.load()
        for y in range(480):
            for x in range(640):
                px[x, y] = (x * 255 // 639, y * 255 // 479, 180)
        custom_rgb.write_bytes(img.tobytes())

        out = subprocess.check_output(
            [str(binary), str(out_jpg), str(custom_rgb), str(pb_frame), str(pb_bg)],
            text=True,
        )
        assert 'VIRTUAL_CMOS_CAPTURE_C_PASS' in out

        # Verify native playback decoded background header and RGB payload.
        bg_raw = pb_bg.read_bytes()
        assert len(bg_raw) == 16 + 640 * 480 * 3
        assert bg_raw[:8] == b'VPBG0001'
        seq, bg_w, bg_h = struct.unpack('<IHH', bg_raw[8:16])
        assert (seq, bg_w, bg_h) == (7, 640, 480)
        bg_img = Image.frombytes('RGB', (640, 480), bg_raw[16:])
        assert len(bg_img.getcolors(640 * 480) or []) > 50

        # Verify captured JPEG with independent Pillow decoder + EXIF 2.32 tags.
        with Image.open(out_jpg) as decoded:
            assert decoded.format == 'JPEG'
            assert decoded.size == (640, 480)
            decoded.load()
            exif = decoded.getexif()
            assert exif.get(0x010f) == 'SONY'
            assert exif.get(0x0110) == 'ILCE-7CM2'
            dt = exif.get(0x0132)
            assert isinstance(dt, str) and re.fullmatch(r'\d{4}:\d{2}:\d{2} \d{2}:\d{2}:\d{2}', dt), dt
            exif_ifd = exif.get_ifd(0x8769)
            assert exif_ifd.get(0x9000) == b'0232'
            assert exif_ifd.get(0x9003) == dt
            assert exif_ifd.get(0x9004) == dt
            assert exif_ifd.get(0x8827) == 200
            assert abs(float(exif_ifd.get(0x829d)) - 5.0) < 0.01
            assert abs(float(exif_ifd.get(0x829a)) - (1.0 / 250.0)) < 1e-5
            assert exif_ifd.get(0xa434) == 'Virtual 35mm F4.0'
            # Must not be blank/single-color.
            assert len(decoded.convert('RGB').getcolors(640 * 480) or []) > 50


if __name__ == '__main__':
    test_virtual_cmos_capture_jpeg_exif_and_playback_roundtrip()
    print('TEST_VIRTUAL_CMOS_CAPTURE_PASS')
