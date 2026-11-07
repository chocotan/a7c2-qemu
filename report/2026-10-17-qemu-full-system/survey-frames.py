#!/usr/bin/env python3
"""Turn a run's captured frames into a labelled contact sheet.

The probe stores `input-NNN-before.ppm` / `input-NNN-after.ppm` for every injected
key. Reading them one by one is slow, and many are identical, so this collapses the
sequence into one grid image with the frame name drawn in the corner.
"""
import argparse
from pathlib import Path

from PIL import Image, ImageDraw


def load(path):
    return Image.open(path).convert('RGB')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', type=Path, required=True)
    parser.add_argument('--out', type=Path, default=None)
    parser.add_argument('--columns', type=int, default=4)
    parser.add_argument('--thumb-width', type=int, default=320)
    parser.add_argument('--first', default='input-020', help='only frames at or after this name')
    parser.add_argument('--keep-identical', action='store_true')
    args = parser.parse_args()
    frames = sorted(args.run.glob('input-*.ppm'))
    frames = [frame for frame in frames if frame.name >= args.first]
    chosen, previous = [], None
    for frame in frames:
        digest = frame.read_bytes()
        if not args.keep_identical and digest == previous:
            continue
        previous = digest
        chosen.append(frame)
    if not chosen:
        raise SystemExit('no frames matched')
    width = args.thumb_width
    first = load(chosen[0])
    height = max(1, round(first.height * width / first.width))
    rows = (len(chosen) + args.columns - 1) // args.columns
    label = 16
    sheet = Image.new('RGB', (args.columns * width, rows * (height + label)), 'black')
    draw = ImageDraw.Draw(sheet)
    for index, frame in enumerate(chosen):
        column, row = index % args.columns, index // args.columns
        x, y = column * width, row * (height + label)
        sheet.paste(load(frame).resize((width, height)), (x, y + label))
        draw.text((x + 4, y + 2), frame.name.replace('input-', '').replace('.ppm', ''), fill='white')
    out = args.out or (args.run / 'contact-sheet.png')
    sheet.save(out)
    print(f'{len(chosen)} frames from {len(frames)} -> {out}')


if __name__ == '__main__':
    main()
