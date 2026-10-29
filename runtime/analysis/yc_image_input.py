"""Prepare one bounded host PNG for the experimental AP YC input (8-bit luma)."""
import hashlib
import json
from pathlib import Path
import re
import stat
import struct
import sys

from PIL import Image, ImageOps

WIDTH, HEIGHT = 1920, 1080


def uncompressed_proof(run: Path, console: str) -> dict:
    """Verify neutral source bytes and original format selection, never output pixels."""
    expected = bytes([128]) * (WIDTH * HEIGHT * 5 // 2)
    digest = 0xcbf29ce484222325
    for byte in expected:
        digest = ((digest ^ byte) * 0x100000001b3) & 0xffffffffffffffff
    readback = run/'yc-pixel-readback.bin'
    raw = readback.read_bytes() if readback.is_file() and not readback.is_symlink() and readback.stat().st_size == len(expected) else None
    observed = re.findall(r'YCIN_UNCOMPRESSED: bytes=5184000 fnv64=([0-9a-f]{16})',console)
    initialized = bool(('YCIN_INIT_DONE: 3 frames queued' in console or re.search(
                   r'initcall init_module\+0x0/0x[0-9a-f]+ \[yc_inject\] returned 0 after \d+ usecs',console)) and
                   'YCIN_INIT_FAILED:' not in console and
                   re.search(r'^YC_INJECT_MOD_FAIL\r?$',console,re.M) is None)
    log = run/'menu-ulogio.bin'
    allocations = re.findall(r'YCIN_DMM: type=0x431 handle=(0x[0-9a-fA-F]+) addr=(0x[0-9a-fA-F]+) len=(0x[0-9a-fA-F]+)',console)
    source = tuple(int(value,16) for value in allocations[0]) if len(allocations) == 1 else None
    sent = re.findall(r'YCIN_SEND: 1000:0102 frame=(\d+) meta=(0x[0-9a-fA-F]+) pix=(0x[0-9a-fA-F]+) rc=0\b',console)
    frames = [(int(frame),int(meta,16),int(pixel,16)) for frame,meta,pixel in sent]
    source_valid = (source is not None and 0x400000000 <= source[1] <= 0x500000000-len(expected) and
                    source[2] >= len(expected) and len(frames) == 3 and
                    [frame[0] for frame in frames] == [0,1,2] and
                    len({frame[1] for frame in frames}) == 3 and
                    all(frame[2] == source[0] for frame in frames))
    copies = re.findall(rb'\[VDT\]\[RDIMG\s*\]: flow\[1\]CMP\(0x[0-9a-fA-F]+\)'
        rb'in_pin\(h:(0x[0-9a-fA-F]+) a:(0x[0-9a-fA-F]+)\)'
        rb'image\(h:(0x[0-9a-fA-F]+) a:(0x[0-9a-fA-F]+)\)->'
        rb'out_pin\(h:(0x[0-9a-fA-F]+)\)image\(h:(0x[0-9a-fA-F]+) a:(0x[0-9a-fA-F]+)'
        rb'\s+type:0x[0-9a-fA-F]+ size=5184000\) diff=0',log.read_bytes() if log.exists() else b'')
    consumed, rc_addresses = set(), set()
    if source_valid:
        for copy in copies:
            meta,meta_pa,pixel,pa,out_meta,out_pixel,out_pa = (int(value,16) for value in copy)
            metadata = re.search(r'YCIN_DMM: type=0xe0b00 handle=0x%x addr=0x%x len=0x[0-9a-f]+' % (meta,meta_pa),console,re.I)
            if pixel == source[0] and pa == source[1] and out_meta == meta and metadata and meta in {f[1] for f in frames}:
                consumed.add(meta);rc_addresses.add(out_pa)
    delivered = {int(value,16) for value in re.findall(r'YCIN_VDT_REPLY: OUT1 frame delivery, meta h=(0x[0-9a-fA-F]+)',console)}
    capture_path=run/'yc-pixel-readback.json'
    capture=json.loads(capture_path.read_text()) if capture_path.exists() else {}
    capture_matches = bool(source_valid and capture == dict(unit_type=0x431,handle=source[0],
        physical_address=source[1],bytes=len(expected)))
    events_path = run/'resize-watch-events.jsonl'
    formats, requests = [], []
    if events_path.exists():
        for line in events_path.read_text().splitlines():
            event = json.loads(line)
            if event['kind'] == 'resize_enable_gate' and event.get('original_entry_verified') is True:
                parameters = bytes.fromhex(event['parameter_hex'])
                if (len(parameters) == 0x1b4 and event.get('setup_status') == 0 and
                        event.get('enable_mode') in (1,2) and
                        struct.unpack_from('<Q',parameters,0x18)[0] in rc_addresses and
                        struct.unpack_from('<I',parameters,0x20)[0] >= len(expected) and
                        list(struct.unpack_from('<2H',parameters,0x58)) == [WIDTH,HEIGHT]):
                    formats.append(int.from_bytes(parameters[0x84:0x88],'little'))
                    requests.append(dict(input_format=formats[-1],
                        output_format=struct.unpack_from('<I',parameters,0x100)[0],
                        input_canvas=list(struct.unpack_from('<2H',parameters,0x58)),
                        output_canvas=list(struct.unpack_from('<2H',parameters,0xe0))))
    result = dict(module_init_completed=initialized,neutral_frame_logs=len(observed),
                  storage_bytes=len(expected),rc_rectangle_bytes=WIDTH*HEIGHT*2,
                  expected_sha256=hashlib.sha256(expected).hexdigest(),
                  readback_sha256=hashlib.sha256(raw).hexdigest() if raw is not None else None,
                  expected_fnv64=f'{digest:016x}',rdimg_completed=len(consumed),
                  allocation_and_send_identity_verified=source_valid,
                  readback_allocation_identity_verified=capture_matches,
                  out1_deliveries=len(delivered & consumed),
                  original_rc_input_formats=formats,
                  original_rc_requests=requests,
                  same_format_and_canvas_observed=bool(requests) and all(
                      request['input_format'] == request['output_format'] == 0 and
                      request['input_canvas'] == request['output_canvas'] == [WIDTH,HEIGHT]
                      for request in requests),
                  full_byte_readback_verified=raw == expected,
                  pixel_processing_verified=False,completion_verified=False)
    result['verified'] = (initialized and observed == [result['expected_fnv64']]*3 and
                          raw == expected and source_valid and capture_matches and len(consumed) == 3 and
                          len(delivered & consumed) == 3 and
                          bool(formats) and all(value == 0 for value in formats))
    return result


def prepare(source: Path, target: Path) -> str:
    if not stat.S_ISREG(source.stat().st_mode) or source.stat().st_size > 64 * 1024 * 1024:
        raise ValueError('YC input must be a regular PNG of at most 64 MiB')
    with Image.open(source) as image:
        if image.format != 'PNG' or image.width * image.height > 64 * 1024 * 1024:
            raise ValueError('YC input must be a PNG of at most 64 megapixels')
        # 1920x1080 is the experimental UVC work canvas, not the 3:2 sensor.
        fitted = ImageOps.contain(image.convert('RGBA'), (WIDTH, HEIGHT), Image.Resampling.LANCZOS)
        canvas = Image.new('RGBA', (WIDTH, HEIGHT), (0, 0, 0, 255))
        canvas.alpha_composite(fitted, ((WIDTH - fitted.width) // 2, (HEIGHT - fitted.height) // 2))
        raw = canvas.convert('L').tobytes()
    if len(raw) != WIDTH * HEIGHT:
        raise ValueError('YC input size mismatch')
    with target.open('xb') as output:
        output.write(raw)
    return hashlib.sha256(raw).hexdigest()


if __name__ == '__main__':
    print(f'YC_INPUT_SHA256={prepare(Path(sys.argv[1]), Path(sys.argv[2]))} bytes={WIDTH * HEIGHT}', flush=True)
