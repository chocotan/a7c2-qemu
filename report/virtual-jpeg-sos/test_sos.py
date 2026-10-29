"""Host-memory suffix provenance checks; JPEG bytes never go to disk."""

import ctypes
import io
import os
from pathlib import Path
import shlex
import subprocess

from PIL import Image
import pytest

ROOT = Path(__file__).resolve().parent
ENGINE = ROOT.parent / "virtual-jpeg-engine"


class EngineResult(ctypes.Structure):
    _fields_ = [("status", ctypes.c_int), ("used", ctypes.c_size_t)]


class View(ctypes.Structure):
    _fields_ = [("status", ctypes.c_int), ("data", ctypes.c_void_p),
                ("offset", ctypes.c_size_t), ("length", ctypes.c_size_t)]


@pytest.fixture(scope="session")
def builds(tmp_path_factory):
    directory = tmp_path_factory.mktemp("host-jpeg-sos")
    compiler = shlex.split(os.environ.get("CC", "cc"))
    strict = ["-std=c11", "-Wall", "-Wextra", "-Werror", "-pedantic"]
    libraries = shlex.split(subprocess.check_output(
        ["pkg-config", "--cflags", "--libs", "libjpeg"], text=True))
    source = str(ROOT / "jpeg-sos.c")
    engine = str(ENGINE / "jpeg-engine.c")
    includes = ["-I", str(ENGINE)]
    subprocess.run(compiler + strict + ["-O2", "-c", source, "-o",
                   str(directory / "jpeg-sos.o")], check=True)
    for name, flags in (
        ("normal", ["-O2"]),
        ("sanitized", ["-O1", "-g", "-fsanitize=address,undefined",
                       "-fno-sanitize-recover=all", "-fno-omit-frame-pointer",
                       "-fno-pie", "-no-pie"]),
    ):
        subprocess.run(compiler + strict + flags + includes + [
            source, engine, str(ROOT / "test-jpeg-sos.c"), "-o",
            str(directory / name)] + libraries, check=True)
    shared = directory / "jpeg-sos.so"
    subprocess.run(compiler + strict + ["-O2", "-fPIC", "-shared", source,
                   engine, "-o", str(shared)] + libraries, check=True)
    library = ctypes.CDLL(str(shared))
    suffix = library.jpeg_sos_suffix
    suffix.argtypes = [ctypes.c_void_p, ctypes.c_size_t,
                       ctypes.c_void_p, ctypes.c_size_t]
    suffix.restype = View
    encode = library.jpeg_engine_encode_rgb888
    encode.argtypes = [ctypes.c_void_p, ctypes.c_size_t, ctypes.c_size_t,
                       ctypes.c_size_t, ctypes.c_size_t, ctypes.c_int,
                       ctypes.c_void_p, ctypes.c_size_t]
    encode.restype = EngineResult
    return directory, suffix, encode


def generated(builds, width=17, height=19, quality=95):
    pixels = bytes(c for y in range(height) for x in range(width)
                   for c in (32 + 160 * x // width, 32 + 160 * y // height,
                             48 + 100 * (x + y) // (width + height)))
    source = ctypes.create_string_buffer(pixels, len(pixels))
    output = ctypes.create_string_buffer(65536)
    result = builds[2](source, len(pixels), width, height, width * 3,
                       quality, output, len(output))
    assert result.status == 0 and source.raw == pixels
    return output.raw[:result.used]


def segments(payload):
    assert payload[:2] == b"\xff\xd8"
    position = 2
    while position < len(payload):
        assert len(payload) - position >= 4 and payload[position] == 0xFF
        marker = payload[position + 1]
        length = int.from_bytes(payload[position + 2:position + 4], "big")
        end = position + 2 + length
        assert length >= 2 and end <= len(payload)
        yield marker, position, end
        if marker == 0xDA:
            return
        position = end


def location(payload, marker):
    return next((start, end) for value, start, end in segments(payload)
                if value == marker)


def prefix(payload):
    return payload[:location(payload, 0xDA)[0]]


def segment(marker, data):
    return bytes([0xFF, marker]) + (len(data) + 2).to_bytes(2, "big") + data


def adapt(builds, candidate, reference, *, accepted=False):
    c = ctypes.create_string_buffer(candidate, max(1, len(candidate)))
    r = ctypes.create_string_buffer(reference, max(1, len(reference)))
    view = builds[1](c, len(candidate), r, len(reference))
    assert c.raw[:len(candidate)] == candidate
    assert r.raw[:len(reference)] == reference
    if accepted:
        assert view.status == 0
        assert view.data == ctypes.addressof(c) + view.offset
        assert 0 < view.offset < len(candidate)
        assert view.length == len(candidate) - view.offset
        suffix = ctypes.string_at(view.data, view.length)
        assert suffix[:2] == b"\xff\xda" and suffix[-2:] == b"\xff\xd9"
        return suffix, view.offset
    assert view.status == 1 and view.data is None
    assert view.offset == view.length == 0


def decoded(payload):
    with Image.open(io.BytesIO(payload)) as image:
        assert image.format == "JPEG" and image.mode == "RGB"
        image.load()
        return image.size, image.tobytes()


def test_actual_engine_zero_copy_and_pillow_reassembly(builds):
    for width, height, quality in ((1, 1, 1), (3, 5, 100), (17, 19, 95),
                                   (31, 23, 50), (64, 33, 95)):
        jpeg = generated(builds, width, height, quality)
        reference = prefix(jpeg)
        suffix, offset = adapt(builds, jpeg, reference, accepted=True)
        assert offset == len(reference) and reference + suffix == jpeg
        rebuilt = decoded(reference + suffix)
        assert rebuilt == decoded(jpeg)
        assert rebuilt[0] == (width, height)
        if width * height > 1:
            assert len(set(rebuilt[1])) > 3


def test_metadata_lengths_and_embedded_sos_are_not_coding(builds):
    jpeg = generated(builds)
    reference = prefix(jpeg)
    extra = b"".join(segment(marker, b"metadata\xff\xda\xff\xd9")
                     for marker in (*range(0xE0, 0xF0), 0xFE))
    candidate = jpeg[:2] + extra + jpeg[2:]
    reference = reference[:2] + segment(0xFE, b"other") + reference[2:]
    suffix, _ = adapt(builds, candidate, reference, accepted=True)
    assert decoded(reference + suffix) == decoded(jpeg)
    for malformed in (b"\xff\xe1", b"\xff\xfe\x00\x01",
                      b"\xff\xe0\xff\xffshort"):
        adapt(builds, jpeg[:2] + malformed + jpeg[2:], prefix(jpeg))
        adapt(builds, jpeg, reference[:2] + malformed + reference[2:])


def test_every_frame_control_byte_must_match(builds):
    jpeg = generated(builds)
    reference = prefix(jpeg)
    start, end = location(jpeg, 0xC0)
    for position in range(start + 4, end):
        changed = bytearray(reference)
        changed[position] ^= 1
        adapt(builds, jpeg, bytes(changed))
    adapt(builds, generated(builds, width=18), reference)


def test_every_quantization_and_huffman_byte_must_match(builds):
    jpeg = generated(builds)
    reference = prefix(jpeg)
    for marker, start, end in segments(reference):
        if marker in (0xDB, 0xC4):
            for position in range(start + 4, end):
                changed = bytearray(reference)
                changed[position] ^= 1
                adapt(builds, jpeg, bytes(changed))
    adapt(builds, generated(builds, quality=50), reference)


def test_restart_presence_interval_and_marker_policy(builds):
    jpeg = generated(builds)
    reference = prefix(jpeg)
    offset = len(reference)
    dri0, dri7, dri8 = (segment(0xDD, value.to_bytes(2, "big"))
                        for value in (0, 7, 8))
    adapt(builds, jpeg, reference + dri0)
    adapt(builds, reference + dri0 + jpeg[offset:], reference)
    adapt(builds, reference + dri7 + jpeg[offset:], reference + dri8)
    for interval in (0, 7, 65535):
        # These intervals do not require a restart in this four-MCU scene.
        dri = segment(0xDD, interval.to_bytes(2, "big"))
        suffix, _ = adapt(builds, reference + dri + jpeg[offset:],
                          reference + dri, accepted=True)
        assert decoded(reference + dri + suffix) == decoded(jpeg)
    for payload in (b"", b"\x00", b"\x00\x00\x00"):
        malformed = reference + segment(0xDD, payload)
        adapt(builds, malformed + jpeg[offset:], malformed)
    adapt(builds, reference + dri0 + dri0 + jpeg[offset:], reference + dri0 + dri0)
    adapt(builds, jpeg[:-2] + b"\xff\xd0\x01\xff\xd9", reference)
    # These are marker-policy probes, not independent entropy decode claims.
    with_dri = reference + dri7
    entropy = jpeg[location(jpeg, 0xDA)[1]:-2]
    sos = jpeg[offset:location(jpeg, 0xDA)[1]]
    adapt(builds, with_dri + sos + entropy + b"\xff\xd1\x01\xff\xd9", with_dri)
    adapt(builds, with_dri + sos + entropy + b"\xff\xd0\xff\xd9", with_dri)


def test_sos_component_table_and_spectral_constraints(builds):
    jpeg = generated(builds)
    start, _ = location(jpeg, 0xDA)
    for index, value in ((0, 2), (1, 99), (2, 0x22), (3, 1),
                         (4, 0xF0), (5, 2), (6, 0x0F), (7, 1), (8, 62), (9, 1)):
        changed = bytearray(jpeg)
        changed[start + 4 + index] = value
        adapt(builds, bytes(changed), prefix(jpeg))
    for length in (0, 1, 2, 11, 13, 65535):
        changed = jpeg[:start + 2] + length.to_bytes(2, "big") + jpeg[start + 4:]
        adapt(builds, changed, prefix(jpeg))


def test_reference_ends_exactly_before_sos_without_defaults(builds):
    jpeg = generated(builds)
    offset = len(prefix(jpeg))
    for length in range(len(jpeg) + 1):
        if length != offset:
            adapt(builds, jpeg, jpeg[:length])
    for reference in (b"", b"\xff\xd8", b"\xff\xda", b"\xff\xd8\xff\xda",
                      jpeg[2:offset], jpeg[:offset - 1]):
        adapt(builds, jpeg, reference)


def test_malformed_unknown_duplicate_and_missing_controls(builds):
    jpeg = generated(builds)
    reference = prefix(jpeg)
    soa, _ = location(jpeg, 0xDA)
    sof, _ = location(jpeg, 0xC0)
    dqt, _ = location(jpeg, 0xDB)
    dht, _ = location(jpeg, 0xC4)
    malformed = []
    for marker, start, end in segments(reference):
        if marker not in (0xDB, 0xC4, 0xC0):
            continue
        malformed.append(reference[:start] + reference[end:])
        malformed.append(reference[:end] + reference[start:end] + reference[end:])
        for length in (0, 1, 2, 65535):
            malformed.append(reference[:start + 2] + length.to_bytes(2, "big") +
                             reference[start + 4:])
    for replacement in (0xC1, 0xC2, 0xC3, 0xC9, 0xCC, 0xD8, 0xD9, 0, 0xFF):
        malformed.append(reference[:sof + 1] + bytes([replacement]) + reference[sof + 2:])
    for position, value in ((dqt + 4, 0x10), (dqt + 5, 0),
                            (sof + 4, 12), (sof + 6, 0),
                            (sof + 10, 99), (sof + 11, 0), (sof + 11, 0x55),
                            (sof + 12, 3), (sof + 13, 1),
                            (dht + 4, 2), (dht + 4, 0x20),
                            (dht + 5, 255), (dht + 21, 12)):
        changed = bytearray(reference)
        changed[position] = value
        malformed.append(bytes(changed))
    # AC invalid run/size and duplicate symbols, DC empty/short definitions.
    for marker, start, end in segments(reference):
        if marker != 0xC4:
            continue
        changed = bytearray(reference)
        if reference[start + 4] & 0x10:
            changed[start + 21] = 0x10
        else:
            changed[start + 5:start + 21] = b"\x00" * 16
        malformed.append(bytes(changed))
        changed = bytearray(reference)
        changed[start + 22] = changed[start + 21]
        malformed.append(bytes(changed))
    coding = [reference[start:end] for marker, start, end in segments(reference)
              if marker in (0xDB, 0xC0, 0xC4)]
    malformed.append(b"\xff\xd8" + b"".join(reversed(coding)))
    malformed.append(b"\xff\xd8" + jpeg[soa:location(jpeg, 0xDA)[1]])
    for bad in malformed:
        adapt(builds, bad + jpeg[soa:], bad)
    # Independently well-formed table order still must match the reference.
    huff = [(start, end) for marker, start, end in segments(reference) if marker == 0xC4]
    first, second = huff[:2]
    reordered = (reference[:first[0]] + reference[second[0]:second[1]] +
                 reference[first[0]:first[1]] + reference[second[1]:])
    adapt(builds, reordered + jpeg[soa:], reference)


def test_candidate_truncation_multiscan_and_final_eoi(builds):
    jpeg = generated(builds)
    reference = prefix(jpeg)
    sos, entropy = location(jpeg, 0xDA)
    for length in range(len(jpeg)):
        adapt(builds, jpeg[:length], reference)
    for candidate in (jpeg + b"junk", jpeg + b"\xff\xd9", jpeg[:-1] + b"\xff",
                      jpeg[:entropy] + b"\xff\xd9", jpeg[:-2] + b"\xff",
                      jpeg[:entropy] + b"\xff\xd9" + jpeg[entropy:],
                      jpeg[:-2] + jpeg[sos:entropy] + b"\x01\xff\xd9",
                      jpeg[:-2] + b"\xff\xc2\xff\xd9",
                      jpeg[:-2] + b"\xff\xff\xd9"):
        adapt(builds, candidate, reference)


@pytest.mark.parametrize("name", ["normal", "sanitized"])
def test_c_selfchecks(builds, name):
    environment = os.environ.copy()
    environment["ASAN_OPTIONS"] = "detect_leaks=1:halt_on_error=1"
    environment["UBSAN_OPTIONS"] = "halt_on_error=1:print_stacktrace=1"
    completed = subprocess.run([str(builds[0] / name)], env=environment,
                               capture_output=True, text=True, check=True)
    assert "4 C self-check groups passed" in completed.stdout
