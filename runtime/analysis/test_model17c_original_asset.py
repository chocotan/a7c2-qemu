"""Opt-in original-asset window check, separate from the host software-model suite."""
from pathlib import Path
import struct


def test_model17c_first16_matches_same_version_original():
    image = Path(__file__).resolve().parent / 'menu-root/usr/lib/appFw.so'
    assert image.is_file() and not image.is_symlink(), 'Prepare verified official assets before this explicit original-asset test'
    # These closed entry windows are in PT_LOAD 0, where raw offset equals ELF VA.
    with image.open('rb') as stream:
        stream.seek(0x267b698)
        assert stream.read(16) == bytes.fromhex('fd7bbda9840080d2fd030091f35301a9')
        stream.seek(0x2aa31bc)
        restore = stream.read(16)
        stream.seek(0x2aeff5c)
        assert stream.read(16) == bytes.fromhex('fd7bb9a9fd030091f35301a9f30300aa')
    assert restore == bytes.fromhex('fd7bbea9fd030091f30b00f973c502f0')
    assert struct.unpack_from('<I', restore, 12)[0] & 0x9f000000 == 0x90000000
