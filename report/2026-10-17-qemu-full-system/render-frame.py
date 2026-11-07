#!/usr/bin/env python3
"""Render a run's screen exports to PNG.

Two independent sources are rendered so neither can stand in for the other:

* ramfb-screen.ppm - what QEMU itself put on the emulated display
* osd-ap-pixels.bin / osd-fb-end.bin - the guest AP framebuffer, RGBA4444

A frame only counts as visible when its pixels are non-zero. Emitting a PNG is
not itself evidence; the report prints the measured pixel statistics.
"""
import argparse
import hashlib
import json
from pathlib import Path
import struct

from PIL import Image

GEOMETRY = (640, 480)
ZERO_FNV = '4f2d9f141eeda325'


def decode_rgba4444(raw, geometry=GEOMETRY):
    """Expand the firmware's AP RGBA4444 words to straight RGB."""
    width, height = geometry
    if len(raw) != width * height * 2:
        raise ValueError('pixel export is %d bytes, expected %d' % (len(raw), width * height * 2))
    pixels = bytearray()
    for (value,) in struct.iter_unpack('<H', raw):
        alpha = value & 15
        pixels.extend((((value >> 12) * 17 * alpha + 7) // 15,
                       (((value >> 8) & 15) * 17 * alpha + 7) // 15,
                       (((value >> 4) & 15) * 17 * alpha + 7) // 15))
    return Image.frombytes('RGB', geometry, bytes(pixels)), sum(1 for byte in raw if byte)


def stats(image):
    colors = image.getcolors(640 * 480) or []
    return {'distinct_colors': len(colors),
            'top_colors': sorted(colors, reverse=True)[:5],
            'rgb_sha256': hashlib.sha256(image.tobytes()).hexdigest()}


def render(run):
    report = {'run': str(run), 'frames': {}, 'visible_pixels_verified': False}
    for name, source in (('ap_snapshot', 'osd-ap-pixels.bin'),
                         ('ap_framebuffer', 'osd-fb-end.bin')):
        path = run / source
        if not path.exists():
            report['frames'][name] = {'export': source, 'present': False}
            continue
        image, nonzero = decode_rgba4444(path.read_bytes())
        out = run / (source.replace('.bin', '.png'))
        image.save(out)
        report['frames'][name] = {'export': source, 'present': True, 'png': out.name,
                                  'nonzero_bytes': nonzero,
                                  'fnv1a64': ('%016x' % _fnv(path.read_bytes())),
                                  **stats(image)}
    screen = run / 'ramfb-screen.ppm'
    if screen.exists():
        with Image.open(screen) as opened:
            image = opened.convert('RGB')
        out = run / 'ramfb-screen.png'
        image.save(out)
        report['frames']['ramfb_screen'] = {'export': screen.name, 'present': True,
                                           'png': out.name,
                                           'size': list(image.size), **stats(image)}
        # QEMU's own output is the authoritative "what the display shows".
        expected = [f for f in report['frames'].values()
                    if f.get('png', '').startswith('osd-ap')]
        if expected:
            report['ramfb_matches_ap_framebuffer'] = (
                report['frames']['ramfb_screen']['rgb_sha256'] == expected[0]['rgb_sha256'])

    visible = [f for f in report['frames'].values()
               if f.get('nonzero_bytes', 0) > 0 or f.get('distinct_colors', 0) > 1]
    report['visible_pixels_verified'] = bool(visible)
    report['zero_reference_fnv1a64'] = ZERO_FNV
    if not visible:
        report['note'] = 'Every export is uniform; no drawn pixels in this run.'
    return report


def _fnv(data):
    value = 0xcbf29ce484222325
    for byte in data:
        value = ((value ^ byte) * 0x100000001b3) & 0xFFFFFFFFFFFFFFFF
    return value


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('run', type=Path)
    args = parser.parse_args()
    report = render(args.run)
    (args.run / 'frame-render.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))
    return 0 if report['visible_pixels_verified'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
