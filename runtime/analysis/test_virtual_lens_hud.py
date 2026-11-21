#!/usr/bin/env python3
"""Host unit tests for software virtual lens & exposure HUD wire encoders and hooks."""
import ctypes
import importlib.util
from pathlib import Path
import struct
import subprocess
import tempfile

HERE = Path(__file__).resolve().parent
MODEL_C = HERE / 'device-models/virtual-lens-hud.c'
MODEL_H = HERE / 'device-models/virtual-lens-hud.h'
APPFW = HERE / 'menu-root/usr/lib/appFw.so'


def _compile_harness(tmp_dir: Path) -> Path:
    harness = tmp_dir / 'test_virtual_lens_hud.c'
    binary = tmp_dir / 'test_virtual_lens_hud'
    harness.write_text(
        r'''
#include <assert.h>
#include <errno.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include "virtual-lens-hud.h"

static uint16_t u16(const unsigned char *p) {
    return (uint16_t)p[0] | ((uint16_t)p[1] << 8);
}
static uint32_t u32(const unsigned char *p) {
    return (uint32_t)p[0] | ((uint32_t)p[1] << 8) | ((uint32_t)p[2] << 16) | ((uint32_t)p[3] << 24);
}

int main(void) {
    struct virtual_lens_hud_state s;
    virtual_lens_hud_init_defaults(&s);
    assert(s.lens_mounted == 1);
    assert(s.aperture_x100 == 400);
    assert(s.shutter_num == 1 && s.shutter_den == 125);
    assert(s.iso_cp_byte == 0x0b && s.iso_auto == 0);
    assert(strcmp(s.lens_name, "Virtual 35mm F4.0") == 0);

    unsigned char b2044[VIRTUAL_LENS_HUD_2044_BYTES];
    assert(virtual_lens_hud_encode_2044(&s, b2044, sizeof b2044) == (int)sizeof b2044);
    assert(b2044[0] == 6 && u16(b2044 + 2) == 0x2044 && b2044[8] == 1);
    assert(u32(b2044 + 0x18) == 10 && u32(b2044 + 0x24) == 0x40 && u32(b2044 + 0x2c) == 0x160);
    assert(strcmp((const char *)(b2044 + 0x34), "Virtual 35mm F4.0") == 0);
    assert(virtual_lens_hud_encode_2044(&s, b2044, sizeof b2044 - 1) == -EINVAL);

    unsigned char b201b[VIRTUAL_LENS_HUD_201B_BYTES];
    assert(virtual_lens_hud_encode_201b(&s, b201b, sizeof b201b) == (int)sizeof b201b);
    assert(b201b[0] == 6 && u16(b201b + 2) == 0x201b);
    assert(u16(b201b + 8) == 400 && u16(b201b + 0xe) == 400 && u16(b201b + 0x10) == 1600);

    unsigned char b200e[VIRTUAL_LENS_HUD_200E_BYTES];
    assert(virtual_lens_hud_encode_200e(&s, b200e, sizeof b200e) == (int)sizeof b200e);
    assert(b200e[0] == 6 && u16(b200e + 2) == 0x200e);
    assert(u16(b200e + 8) == 1 && u32(b200e + 0xc) == 125);
    assert(u16(b200e + 0x10) == 1 && u32(b200e + 0x14) == 4000);
    assert(u16(b200e + 0x18) == 30 && u32(b200e + 0x1c) == 1);
    assert(b200e[0x24] == 0 && b200e[0x25] == 0);

    unsigned char b2036[VIRTUAL_LENS_HUD_2036_BYTES];
    assert(virtual_lens_hud_encode_2036(&s, b2036, sizeof b2036) == (int)sizeof b2036);
    assert(b2036[0] == 6 && u16(b2036 + 2) == 0x2036 && b2036[8] == 0x0b && b2036[9] == 0);

    /* Stepping & clamping */
    assert(virtual_lens_hud_step_aperture(&s, 3) == 0 && s.aperture_x100 == 560);
    assert(virtual_lens_hud_step_aperture(&s, -100) == 0 && s.aperture_x100 == 400);
    assert(virtual_lens_hud_step_aperture(&s, 100) == 0 && s.aperture_x100 == 1600);

    assert(virtual_lens_hud_step_shutter(&s, 1) == 0 && s.shutter_num == 1 && s.shutter_den == 250);
    assert(virtual_lens_hud_step_shutter(&s, -100) == 0 && s.shutter_num == 30 && s.shutter_den == 1);
    assert(virtual_lens_hud_step_shutter(&s, 100) == 0 && s.shutter_num == 1 && s.shutter_den == 4000);

    assert(virtual_lens_hud_step_iso(&s, 3) == 0 && s.iso_cp_byte == 0x0e);
    assert(virtual_lens_hud_step_iso(&s, -100) == 0 && s.iso_cp_byte == 0x0b);

    /* Detached lens & invalid field rejection */
    s.lens_mounted = 0;
    assert(virtual_lens_hud_encode_2044(&s, b2044, sizeof b2044) == (int)sizeof b2044);
    assert(b2044[8] == 4 && b2044[0x34] == 0);
    assert(virtual_lens_hud_encode_201b(&s, b201b, sizeof b201b) == (int)sizeof b201b);
    assert(u16(b201b + 8) == 0);
    assert(virtual_lens_hud_step_aperture(&s, 1) == -ENODEV);

    s.shutter_den = 0;
    assert(virtual_lens_hud_encode_200e(&s, b200e, sizeof b200e) == -ERANGE);
    s.iso_cp_byte = 0x06;
    assert(virtual_lens_hud_encode_2036(&s, b2036, sizeof b2036) == -ERANGE);
    puts("VIRTUAL_LENS_HUD_C_PASS");
    return 0;
}
'''
    )
    subprocess.run(
        [
            'clang', '-O1', '-Wall', '-Wextra', '-Werror',
            '-fsanitize=address,undefined',
            '-I', str(HERE / 'device-models'),
            str(harness), str(MODEL_C),
            '-o', str(binary),
        ],
        check=True,
    )
    return binary


def test_virtual_lens_hud_c_encoders():
    with tempfile.TemporaryDirectory() as tmp:
        binary = _compile_harness(Path(tmp))
        out = subprocess.check_output([str(binary)], text=True)
        assert 'VIRTUAL_LENS_HUD_C_PASS' in out


def test_virtual_lens_hud_launcher_env_wiring():
    spec = importlib.util.spec_from_file_location('start_menu_lens', HERE / 'start-menu.py')
    start_menu = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(start_menu)
    natural = start_menu.profile_environment({}, natural_boot=True)
    assert natural['MENU_VIRTUAL_LENS_HUD'] == '1'
    disabled = start_menu.profile_environment({'A7C2_VIRTUAL_LENS_HUD': '0'}, natural_boot=True)
    assert 'MENU_VIRTUAL_LENS_HUD' not in disabled

    spec_cold = importlib.util.spec_from_file_location('cold_lens', HERE / 'original_cold_boot.py')
    cold = importlib.util.module_from_spec(spec_cold)
    spec_cold.loader.exec_module(cold)
    assert cold.BASE_GUEST.get('MENU_VIRTUAL_LENS_HUD') == '1'


def test_virtual_lens_hud_appfw_prologue_bytes():
    if not APPFW.is_file():
        return
    data = APPFW.read_bytes()
    expected = {
        0x181b660: (0xa9bc7bfd, 0x910003fd, 0x394a9001, 0xa90153f3),
        0x181d05c: (0xa9bc7bfd, 0x910003fd, 0x394a9002, 0xa90153f3),
        0x181ca04: (0xa9bc7bfd, 0x910003fd, 0x394a9002, 0xa90153f3),
    }
    for va, words in expected.items():
        actual = struct.unpack_from('<4I', data, va)
        assert actual == words, f'appFw {hex(va)} mismatch: {[hex(w) for w in actual]}'


if __name__ == '__main__':
    test_virtual_lens_hud_c_encoders()
    test_virtual_lens_hud_launcher_env_wiring()
    test_virtual_lens_hud_appfw_prologue_bytes()
    print('TEST_VIRTUAL_LENS_HUD_PASS')
