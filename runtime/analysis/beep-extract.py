#!/usr/bin/env python3
"""Extract original camera beep audio to WAV, using the firmware's own index.

Facts this relies on (all verified against the shipped files):

* `/usr/share/avsystemsound/beeplist.txt` lists, per beep, the BeepID number, the
  memory type, the file name, the size and the offset inside `SysSound.bin`.
* Each per-beep `.bin` is byte-identical to `SysSound.bin[offset:offset+size]`.
* A slice starts with a 128-byte preamble (four 32-byte records: 0x17, 0x16,
  0x15, 0) and the payload after it is 16-bit little-endian PCM.

Nothing here synthesises audio: it only slices bytes the firmware itself ships.
The sample rate is NOT in the index; it is a required argument so a wrong rate
cannot be silently assumed.
"""
import argparse
import json
import re
import struct
import sys
import wave
from pathlib import Path

PREAMBLE = 128
ROW = re.compile(
    r'^(BEEP_ID_[A-Z0-9_]+),\s*(0x[0-9A-Fa-f]+),\s*([A-Z]+),\s*([^,]*?),\s*'
    r'([^,]*?),\s*([^,]*?),\s*([A-Z_]+),\s*(\d+),\s*(\d+),\s*(\d+),\s*(\d+),\s*(\d+)')


def parse_index(text):
    """Return {id: {...}} for rows that name a file; N/A offsets stay explicit."""
    rows = {}
    for line in text.splitlines():
        match = ROW.match(line.strip())
        if not match:
            continue
        (name, number, memory, filename, size_text, offset_text, rsrc,
         priority, kind, continuous, cont_length, cont_first) = match.groups()
        beep = int(number, 16)
        filename = filename.strip()
        if filename in ('None', ''):
            continue
        size = None if size_text.strip() in ('N/A', '') else int(size_text, 16)
        offset = None if offset_text.strip() in ('N/A', '') else int(offset_text, 16)
        rows[beep] = dict(name=name, beep=beep, memory=memory, file=filename,
                          size=size, offset=offset, rsrc=rsrc, priority=int(priority),
                          kind=int(kind), continuous=int(continuous),
                          cont_length=int(cont_length), cont_first=int(cont_first))
    return rows


def slice_beep(sound, beep):
    """Return the raw audio for one beep from the packed container.

    Rows with N/A size/offset are not in the container; callers must fall back to
    the standalone file (see resolve_beep).
    """
    if beep['size'] is None or beep['offset'] is None:
        raise ValueError(f"{beep['name']} has no size/offset in the index")
    end = beep['offset'] + beep['size']
    if end > len(sound):
        raise ValueError(f"{beep['name']} slice {end:#x} exceeds SysSound.bin")
    return sound[beep['offset']:end]


def resolve_beep(root, sound, beep):
    """Return (raw, source). Container slice wins; standalone file is the fallback.

    Both carry the same 128-byte preamble and 16-bit PCM payload, and when a beep
    exists in both places the bytes must agree, otherwise the row is refused.
    """
    container = None
    if beep['size'] is not None and beep['offset'] is not None:
        container = slice_beep(sound, beep)
    standalone = root/beep['file'] if beep['file'] else None
    file_bytes = standalone.read_bytes() if standalone and standalone.is_file() else None
    if container is not None and file_bytes is not None and container != file_bytes:
        raise ValueError(f"{beep['name']}: container slice differs from {beep['file']}")
    if container is not None:
        return container, 'container'
    if file_bytes is not None:
        return file_bytes, 'standalone'
    raise ValueError(f"{beep['name']} has neither a container slice nor a standalone file")


def pcm_samples(raw):
    """16-bit LE PCM after the 128-byte preamble."""
    if len(raw) <= PREAMBLE:
        return b''
    payload = raw[PREAMBLE:]
    payload = payload[:len(payload)//2*2]
    return payload


def write_wav(path, raw, rate):
    payload = pcm_samples(raw)
    with wave.open(str(path), 'wb') as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(rate)
        out.writeframes(payload)
    return len(payload)//2


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', default=str(Path(__file__).resolve().parent/'menu-root/usr/share/avsystemsound'))
    parser.add_argument('--rate', type=int, required=True, help='PCM sample rate (not stored in the index)')
    parser.add_argument('--beep', type=lambda v: int(v, 0), default=0x0000)
    parser.add_argument('--output', required=True)
    parser.add_argument('--json', action='store_true')
    args = parser.parse_args(argv)

    root = Path(args.root)
    index = parse_index((root/'beeplist.txt').read_text(errors='replace'))
    if args.beep not in index:
        print(f'no beep {args.beep:#06x} in the index', file=sys.stderr)
        return 2
    beep = index[args.beep]
    sound = (root/'SysSound.bin').read_bytes()
    raw, source = resolve_beep(root, sound, beep)
    frames = write_wav(Path(args.output), raw, args.rate)
    standalone = root/beep['file']
    report = dict(beep=beep, rate=args.rate, source=source, bytes=len(raw), frames=frames,
                  seconds=round(frames/args.rate, 3), output=args.output,
                  slice_matches_standalone=(standalone.is_file() and
                                            standalone.read_bytes() == raw))
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print(f"{beep['name']} {beep['beep']:#06x} [{source}]: {frames} frames @ {args.rate} Hz "
              f"= {report['seconds']}s -> {args.output}")
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
