"""No guest/VM/device/network; JPEG bytes stay in subprocess pipes and BytesIO."""

import hashlib
import io
import json
import os
from pathlib import Path
import shlex
import subprocess

import pytest
from PIL import Image

HERE = Path(__file__).resolve().parent
BASE = HERE.parents[1]


def test_public_source_windows_and_bounded_kuna():
    pins = json.loads((HERE / "source-pins.json").read_text())
    source = (BASE / pins["asset"]["path"]).read_bytes()
    assert len(source) == pins["asset"]["size"] == 13_797_088
    assert hashlib.sha256(source).hexdigest() == pins["asset"]["sha256"] == (
        "90343f5f2edc0393ad8809d907cfe648dfd3a82ce0ef39cf06167929d8955096"
    )
    for pin in pins["windows"]:
        start = int(pin["start"], 16)
        assert hashlib.sha256(source[start : start + pin["size"]]).hexdigest() == pin["sha256"]
    priority = [int.from_bytes(source[i : i + 4], "little") for i in range(0x3EF054, 0x3EF0AC, 4)]
    assert list(zip(priority[::2], priority[1::2])) == [
        (10, 0x1000000), (1, 1), (2, 0x10000), (3, 4), (4, 0x10),
        (5, 0x20), (6, 0x40), (7, 0x20000), (8, 0x40000),
        (9, 0x80000), (13, 0x100000),
    ]
    kuna = json.loads((HERE / "kuna-bounded.json").read_text())
    assert kuna["count"] == 3 and kuna["error"] is None
    assert {f["address_hex"] for f in kuna["functions"]} == {"0x2a4164", "0x2afcf8", "0x2afd30"}
    assert all(f["error"] is None for f in kuna["functions"])


@pytest.fixture(scope="module", params=[False, True], ids=["strict", "asan-ubsan"])
def executable(request, tmp_path_factory):
    folder = tmp_path_factory.mktemp("native-jpeg-binding")
    executable = folder / "selfcheck"
    flags = shlex.split(subprocess.check_output(["pkg-config", "--cflags", "--libs", "libjpeg"], text=True))
    command = [os.environ.get("CC", "cc"), "-std=c11", "-Wall", "-Wextra", "-Werror", "-pedantic", "-g"]
    if request.param:
        command += ["-fsanitize=address,undefined", "-fno-omit-frame-pointer", "-fno-pie", "-no-pie"]
    command += [
        str(HERE / "native-jpeg.c"), str(HERE / "test-native-jpeg.c"),
        str(HERE.parent / "virtual-jpeg-hardware/jpeg-hardware.c"),
        str(HERE.parent / "virtual-jpeg-hardware/jpeg-hardware-codec.c"),
        str(HERE.parent / "virtual-jpeg-sos/jpeg-sos.c"), *flags, "-o", str(executable),
    ]
    subprocess.run(command, check=True, capture_output=True)
    return executable


def run(executable, *args):
    env = dict(os.environ, ASAN_OPTIONS="detect_leaks=1:halt_on_error=1", UBSAN_OPTIONS="halt_on_error=1")
    result = subprocess.run([str(executable), *args], capture_output=True, env=env)
    assert result.returncode == 0, result.stderr.decode(errors="replace")
    return result.stdout


def test_register_sequences_and_verified_completion(executable):
    assert b"checks passed" in run(executable)


@pytest.mark.parametrize("inverse,custom", [(0, 0), (1, 0), (0, 1)])
def test_register_tables_really_configure_codec(executable, inverse, custom):
    jpeg = run(executable, "--emit", str(inverse), str(custom))
    assert jpeg.startswith(b"\xff\xd8\xff\xdb") and jpeg.endswith(b"\xff\xd9")
    assert jpeg[575:577] == b"\xff\xda"
    with (BASE / "runtime/analysis/menu-root/system/av-cam.bin").open("rb") as source:
        for prefix, raw, size in [(140, 0x4512ED, 29), (169, 0x451327, 179),
                                  (348, 0x45130A, 29), (377, 0x4513DA, 179)]:
            source.seek(raw)
            assert jpeg[prefix:prefix+size] == source.read(size)
    image = Image.open(io.BytesIO(jpeg))
    image.load()
    assert image.size == (32, 16) and image.mode == "RGB"
    assert image.layer == [(1, 2, 1, 0), (2, 1, 1, 1), (3, 1, 1, 1)]
    # Pillow reports DQT in natural order, independently checking zigzag binding.
    for table in range(2):
        expected_q = [4 + (i * 3 + table) % 9 if custom else 2 + (i + table) % 3 for i in range(64)]
        assert image.quantization[table] == expected_q
    expected_rgb = []
    for y in range(16):
        for x in range(32):
            pixel = (30 + 4*x, 50 + 5*y, 40 + 2*x + 2*y)
            expected_rgb.extend(255-v if inverse else v for v in pixel)
    errors = [abs(a-b) for a, b in zip(image.tobytes(), expected_rgb)]
    assert sum(errors) / len(errors) < 4 and max(errors) < 15
    reference = run(executable, "--emit", "0", "0")
    if inverse or custom:
        assert jpeg[575:] != reference[575:]
    else:
        assert jpeg == reference


@pytest.mark.parametrize('width,height', [(17, 9), (31, 15), (32, 16)])
def test_original_logical_header_and_rounded_mcu_entropy_decode(executable, width, height):
    jpeg = run(executable, '--emit-geometry', '0', '0', str(width), str(height))
    reference = run(executable, '--emit', '0', '0')
    # The ASIC's entropy covers full W16/H8 MCUs; original SOF carries logical size.
    assert jpeg[575:] == reference[575:]
    with Image.open(io.BytesIO(jpeg)) as image, Image.open(io.BytesIO(reference)) as rounded:
        image.load()
        rounded.load()
        assert image.size == (width, height)
        assert image.tobytes() == rounded.crop((0, 0, width, height)).tobytes()
