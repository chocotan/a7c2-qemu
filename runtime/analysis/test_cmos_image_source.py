#!/usr/bin/env python3
"""Host checks for the custom CMOS image path: Pillow JPEG -> serial chunks -> C decoder."""
import base64
from pathlib import Path
import re
import subprocess
import sys
import tempfile

from PIL import Image

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import cmos_source  # noqa: E402

DRIVER = r'''
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include "virtual-cmos-capture.h"
int main(int argc, char **argv) {
    (void)argc;
    FILE *f = fopen(argv[1], "rb"); static uint8_t jpeg[1 << 22]; size_t n = fread(jpeg, 1, sizeof jpeg, f); fclose(f);
    static uint8_t rgb[VIRTUAL_CMOS_RGB_BYTES]; unsigned w = 0, h = 0;
    if (virtual_cmos_decode_jpeg(jpeg, n, rgb, &w, &h, 0, 0)) return 3;
    f = fopen(argv[2], "wb"); fwrite(rgb, 1, sizeof rgb, f); fclose(f);
    printf("%u %u\n", w, h); return 0;
}
'''


def test_prepare_chunks_and_c_decoder_roundtrip():
    with tempfile.TemporaryDirectory(dir=HERE.parents[1] / 'runtime/tmp') as tmp:
        tmp = Path(tmp)
        source = Image.new('RGB', (900, 300))
        source.putdata([(x * 255 // 900, y * 255 // 300, 128) for y in range(300) for x in range(900)])
        png = tmp / 'wide.png'
        source.save(png)
        jpeg = cmos_source.prepare_jpeg(png)
        commands = cmos_source.upload_commands(jpeg)
        assert commands[0].endswith('--begin') and commands[-1].endswith('--commit')
        assert all(len(c) < 900 for c in commands)
        joined = b''.join(base64.b64decode(re.search(r"'([^']+)'", c).group(1)) for c in commands[1:-1])
        assert joined == jpeg
        (tmp / 'in.jpg').write_bytes(jpeg)
        (tmp / 'driver.c').write_text(DRIVER)
        dm = HERE / 'device-models'
        subprocess.run(['clang', '-O1', '-fsanitize=address,undefined', '-I', str(dm), str(tmp / 'driver.c'),
                        str(dm / 'virtual-cmos-capture.c'), str(dm / 'virtual-lens-hud.c'),
                        str(HERE.parents[1] / 'report/virtual-sensor/sensor-core.c'), '-o', str(tmp / 'driver')], check=True)
        out = subprocess.run([str(tmp / 'driver'), str(tmp / 'in.jpg'), str(tmp / 'out.rgb')], check=True,
                             capture_output=True, text=True).stdout.split()
        assert out == ['640', '480']
        decoded = Image.frombytes('RGB', (640, 480), (tmp / 'out.rgb').read_bytes())
        reference = Image.open(tmp / 'in.jpg').convert('RGB')
        a, b = decoded.resize((64, 48)), reference.resize((64, 48))
        diff = max(abs(p - q) for pa, pb in zip(a.getdata(), b.getdata()) for p, q in zip(pa, pb))
        assert diff <= 12, diff
        assert max(decoded.getpixel((5, 5))) < 40  # letterbox bar
        assert decoded.getpixel((320, 240)) != (16, 16, 16)
