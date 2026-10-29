"""Authenticated, bank-explicit static views of the public Imola MCU image."""
import argparse
import hashlib
from pathlib import Path

IMAGE_BYTES = 10934476
IMAGE_SHA256 = '15e75a9732e2f9904ada1c919c631dac0da57e605ce3daa4c6fb2ebe98982b5b'
# (raw begin, raw end, linked VA begin). These are static linked regions,
# not proof that the original loader copied or executed the entire extent.
REGIONS = {
    'rom0': (0, 0x8cc, 0x9fc00000),
    'ram0': (0x9000, 0x714000, 0x80009000),
    'ram1': (0x714000, 0x8bf000, 0x80714000),
    'ram2': (0x8bf000, 0xa6a000, 0x808bf000),
    'rom1': (0xa6a000, 0xa6a8cc, 0x9fc00000),
    'rom2': (0xa6d000, 0xa6d8cc, 0x9fc00000),
}


def load_image(path):
    image = Path(path).read_bytes()
    if len(image) != IMAGE_BYTES or hashlib.sha256(image).hexdigest() != IMAGE_SHA256:
        raise ValueError('expected the complete authenticated public Imola2 image')
    return image


def file_offset(bank, address, size):
    if bank not in REGIONS:
        raise ValueError('select one explicit ROM/RAM bank')
    if type(address) is not int or type(size) is not int or size <= 0:
        raise ValueError('address and positive byte count must be integers')
    start, end, base = REGIONS[bank]
    if bank.startswith('rom') and 0xbfc00000 <= address < 0xc0000000:
        address &= 0xdfffffff  # Actual ROM startup changes BFC to 9FC this way.
    offset = address - base
    if offset < 0 or offset >= end - start or size > end - start - offset:
        raise ValueError('window is outside the selected linked region')
    return start + offset


def read_window(image, bank, address, size):
    # The immutable image must come from load_image; this is a static file view.
    if len(image) != IMAGE_BYTES:
        raise ValueError('incomplete image')
    offset = file_offset(bank, address, size)
    return image[offset:offset + size]


def export_region(image_path, bank, output_path):
    image = load_image(image_path)
    if bank not in REGIONS:
        raise ValueError('select one explicit ROM/RAM bank')
    start, end, base = REGIONS[bank]
    data = read_window(image, bank, base, end - start)
    target = Path(output_path)
    with target.open('xb') as stream:
        if stream.write(data) != len(data):
            raise OSError('short region write; partial output retained: ' + str(target))
    if target.read_bytes() != data:
        raise OSError('region readback mismatch; output retained: ' + str(target))
    return {'bank': bank, 'linked_base': hex(base), 'raw_start': hex(start),
            'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest(),
            'firmware_execution': False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('public_image', type=Path)
    parser.add_argument('bank', choices=REGIONS)
    parser.add_argument('new_output', type=Path)
    args = parser.parse_args()
    print(export_region(args.public_image, args.bank, args.new_output))


if __name__ == '__main__':
    main()
