#!/usr/bin/env python3
"""Recognise a camera screen from a captured frame, so keys follow the screen.

The first-setup walk sends a fixed key every 60 s. That breaks as soon as the stored
configuration changes the page sequence or the guest is slower than usual: the same
key then lands one screen early or late. Recognising the screen first makes the
decision independent of timing.

Screens are matched by a 24x24 (576-bit) difference hash with a bounded Hamming
distance. The map lives in `screens.json`:

    {"screens": [{"name": "language", "key": "ENTER", "hash": "0123456789abcdef"}]}

A frame that matches nothing is reported as unknown instead of being guessed at.
"""
import argparse
import json
from pathlib import Path

from PIL import Image

HERE = Path(__file__).resolve().parent
DEFAULT_MAP = HERE / 'screens.json'


def dhash(path_or_image, size=24):
    """Difference hash (size*size bits): 1 when the left pixel is brighter than the right.

    8x8 was too coarse: the privacy page and the Creators App page collapsed onto the same
    value, so the recognised screen could not be trusted.
    """
    image = path_or_image if isinstance(path_or_image, Image.Image) else Image.open(path_or_image)
    small = image.convert('L').resize((size + 1, size), Image.BILINEAR)
    pixels = list(small.getdata())
    bits = 0
    for row in range(size):
        for column in range(size):
            left = pixels[row * (size + 1) + column]
            right = pixels[row * (size + 1) + column + 1]
            bits = (bits << 1) | (1 if left > right else 0)
    return f'{bits:0{size*size//4}x}'


def hamming(a, b):
    return bin(int(a, 16) ^ int(b, 16)).count('1')


def classify(path, screen_map=None, tolerance=12):
    """Return (name, distance) for the closest known screen, or (None, distance)."""
    data = json.loads(Path(screen_map or DEFAULT_MAP).read_text())
    digest = dhash(path)
    best_name, best_distance = None, 1 << 30
    for entry in data.get('screens', []):
        distance = hamming(digest, entry['hash'])
        if distance < best_distance:
            best_name, best_distance = entry['name'], distance
    if best_distance <= tolerance:
        return best_name, best_distance
    return None, best_distance


def key_for(name, screen_map=None):
    data = json.loads(Path(screen_map or DEFAULT_MAP).read_text())
    for entry in data.get('screens', []):
        if entry['name'] == name:
            return entry.get('key')
    return None


def keys_for(name, screen_map=None):
    """An entry may need more than one key (for example DOWN then ENTER)."""
    data = json.loads(Path(screen_map or DEFAULT_MAP).read_text())
    for entry in data.get('screens', []):
        if entry['name'] == name:
            return entry.get('keys') or ([entry['key']] if entry.get('key') else [])
    return []


def learn(paths, screen_map=None, names=None):
    """Add frames to the map; names are taken from the file stem when not given."""
    target = Path(screen_map or DEFAULT_MAP)
    data = json.loads(target.read_text()) if target.exists() else {'screens': []}
    known = {entry['hash'] for entry in data['screens']}
    added = []
    for index, path in enumerate(sorted(Path().glob(paths))):
        digest = dhash(path)
        if digest in known:
            continue
        name = names[index] if names and index < len(names) else path.stem
        data['screens'].append({'name': name, 'hash': digest, 'sample': str(path)})
        known.add(digest)
        added.append(name)
    target.write_text(json.dumps(data, indent=1) + '\n')
    return added


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--frame', type=Path, nargs='*', default=[],
                        help='frames to classify')
    parser.add_argument('--learn', default=None, help='glob of frames to add to the map')
    parser.add_argument('--names', default='', help='comma separated names for --learn')
    parser.add_argument('--map', type=Path, default=None)
    parser.add_argument('--tolerance', type=int, default=12)
    args = parser.parse_args()
    if args.learn:
        names = [item for item in args.names.split(',') if item] or None
        added = learn(args.learn, args.map, names)
        print('learned', len(added), 'new screens:', added)
    for frame in args.frame:
        name, distance = classify(frame, args.map, args.tolerance)
        print(f'{frame.name}: {name or "unknown"} (distance {distance})')


if __name__ == '__main__':
    main()
