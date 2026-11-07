# SPDX-License-Identifier: MIT
"""Actual model17 RGB -> owned native input -> original SSYC component ABI.

This never runs the camera app/Main Exec, sends OSAL messages, or claims capture.
"""
import ctypes
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import select
import shlex
import struct
import subprocess

import pytest
from PIL import Image

HERE = Path(__file__).resolve().parent
NATIVE = HERE.parent.parent
BASE = NATIVE / 'runtime/analysis'
GUEST = BASE / 'menu-root'
ASSETS = {
    'libInfraAvbbc.so': '676197567dbbefa54e08f528968efc6ca2aaffe8bee3ee3eae8164382ed5a7e5',
    'dataflowInfraFramework.so': '620e04a9cd51e65bd190ed1d5459b7235ff5a4109bc6498df342972621991d47',
    'libosal_uipc.so': '09ebf5980237fc473077dc844763dcb00cba423f431646e3be7c0ca49ea70ff3',
}
FLAGS = ['-std=c11', '-Wall', '-Wextra', '-Werror', '-pedantic']


def fnv(raw):
    value = 0xcbf29ce484222325
    for byte in raw:
        value = ((value ^ byte) * 0x100000001b3) & 0xffffffffffffffff
    return value


class Result(ctypes.Structure):
    _fields_ = [('token', ctypes.c_uint64), ('total', ctypes.c_uint64),
                ('offset', ctypes.c_uint64), ('used', ctypes.c_size_t)]


@pytest.fixture(scope='module')
def actual_frame(tmp_path_factory):
    work = tmp_path_factory.mktemp('capture-input-actual-core')
    spec = importlib.util.spec_from_file_location('capture_input_model_builder', BASE / 'build-functional-camera-model.py')
    builder = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(builder)
    sources = [NATIVE / 'report' / name for name in builder.SOURCES] + [BASE / 'device-models/cp-parameter-batch.c']
    library = work / 'core.so'
    libraries = shlex.split(subprocess.check_output([
        'pkg-config', '--cflags', '--libs', 'libjpeg', 'libavcodec', 'libavformat',
        'libavutil', 'libswscale'], text=True, timeout=15))
    command = shlex.split(os.environ.get('CC', 'cc')) + FLAGS + ['-O2', '-fPIC', '-shared', '-Wl,-z,defs',
        *map(str, sources), *libraries, '-lm', '-o', str(library)]
    subprocess.run(command, check=True, capture_output=True, timeout=90)
    lib = ctypes.CDLL(str(library))
    lib.fcam_model_create.argtypes = [ctypes.c_uint64]
    lib.fcam_model_create.restype = ctypes.c_void_p
    lib.fcam_model_destroy.argtypes = [ctypes.c_void_p]
    lib.fcam_model_destroy.restype = None
    lib.fcam_model_request.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_void_p, ctypes.c_size_t,
        ctypes.c_void_p, ctypes.c_size_t, ctypes.POINTER(Result)]
    lib.fcam_model_request.restype = ctypes.c_int
    model = lib.fcam_model_create(0x1234123412341234)
    assert model

    def request(op, data=b'', capacity=65024):
        incoming = ctypes.create_string_buffer(data, max(1, len(data)))
        output = ctypes.create_string_buffer(max(1, capacity))
        result = Result()
        assert lib.fcam_model_request(model, op, incoming, len(data), output, capacity, ctypes.byref(result)) == 0
        return bytes(output.raw[:result.used]), result

    try:
        request(1, capacity=128)
        request(3, struct.pack('<IIIIIIQQII', 128, 64, 30, 95, 400, 100, 2500, 1000000, 0, 0), 128)
        frame, result = request(17, struct.pack('<IIB3xI', 0x40380005, 29, 2, 0))
        assert result.offset == 0 and result.used == result.total == len(frame) == 96 + 128 * 64 * 3
        assert fnv(frame[96:]) == struct.unpack_from('<Q', frame, 72)[0]
        request(65, struct.pack('<QQ', result.token, fnv(frame)), 0)
        yield dict(frame=frame, request=request, library=lib)
    finally:
        request(66, capacity=128)
        lib.fcam_model_destroy(model)


@pytest.mark.parametrize('sanitize', [False, True], ids=['c11', 'asan-ubsan'])
def test_input_storage_and_reference_lifetime(actual_frame, tmp_path, sanitize):
    frame_path = tmp_path / 'frame.bin'
    frame_path.write_bytes(actual_frame['frame'])
    flags = ['-O1', '-g', '-fsanitize=address,undefined', '-fno-sanitize-recover=all',
             '-fno-omit-frame-pointer', '-fno-pie', '-no-pie'] if sanitize else ['-O2']
    executable = tmp_path / 'input-check'
    command = shlex.split(os.environ.get('CC', 'cc')) + FLAGS + flags + [
        str(HERE / 'test-capture-input.c'), '-o', str(executable)]
    subprocess.run(command, check=True, capture_output=True, timeout=30)
    env = dict(os.environ, ASAN_OPTIONS='detect_leaks=1:halt_on_error=1',
               UBSAN_OPTIONS='halt_on_error=1:print_stacktrace=1')
    result = subprocess.run([str(executable), str(frame_path)], capture_output=True,
                            env=env, timeout=30)
    assert result.returncode == 0, result.stderr.decode(errors='replace')
    assert result.stdout == b'PASS actual-model17-RGB native-input-owner mapping-and-lifetime\n'
    assert not result.stderr


def test_original_ssyc_writer_and_typed_reader(actual_frame, tmp_path):
    qemu = NATIVE / 'runtime/sources/qemu-11.1.2/build-user/qemu-aarch64'
    assets = {GUEST / 'usr/lib' / name: digest for name, digest in ASSETS.items()}
    if not qemu.is_file() or not all(path.is_file() for path in assets):
        pytest.skip('requires the prepared public ALLLANG libraries and local AArch64 user emulator')
    for path, digest in assets.items():
        assert hashlib.sha256(path.read_bytes()).hexdigest() == digest
    libraries = [GUEST / 'lib' / name for name in
                 ('libc-2.25.so', 'libdl-2.25.so', 'libpthread-2.25.so', 'ld-2.25.so')]
    executable = tmp_path / 'check-original-serializer'
    command = ['clang', '--target=aarch64-linux-gnu', '-fuse-ld=lld', '-nostdlib', '-O2',
        '-mno-outline-atomics', *FLAGS, '-isystem', '/usr/aarch64-linux-gnu/include',
        '-Wl,--no-undefined', '-Wl,--export-dynamic', '-Wl,-e,_start',
        '-Wl,--dynamic-linker=/lib/ld-linux-aarch64.so.1', str(HERE / 'check-original-serializer.c'),
        str(HERE / 'capture-mapper.c'), str(HERE / 'capture-jpeg-input.c'),
        *map(str, libraries), '-o', str(executable)]
    subprocess.run(command, check=True, capture_output=True, timeout=30)
    (tmp_path / 'frame.bin').write_bytes(actual_frame['frame'])
    payload = [str(qemu), '-L', str(GUEST), '-E',
        'LD_LIBRARY_PATH=' + str(GUEST / 'usr/lib') + ':' + str(GUEST / 'lib'),
        '/tmp/capture-input/check-original-serializer', '/tmp/capture-input/frame.bin',
        *[str(GUEST / 'usr/lib' / name) for name in ASSETS]]
    command = ['/usr/bin/bwrap', '--unshare-all', '--die-with-parent', '--new-session',
        '--ro-bind', '/', '/', '--tmpfs', '/tmp', '--dir', '/tmp/capture-input',
        '--bind', str(tmp_path), '/tmp/capture-input',
        '--proc', '/proc', '--dev', '/dev', '--chdir', '/tmp/capture-input', '--', *payload]
    env = {key: value for key, value in os.environ.items() if not key.startswith(('LD_', 'QEMU_', 'MENU_', 'SONY_'))}
    with subprocess.Popen(command, env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                          stderr=subprocess.PIPE) as process:
        try:
            assert select.select([process.stdout], [], [], 30)[0], 'original typed reader did not publish input lease'
            assert process.stdout.readline() == b'MODEL18_INPUT_READY native_input_references_held=1\n'
            model_input = (tmp_path / 'actual-frame-still32.bin').read_bytes()
            assert len(model_input) == 32 and struct.unpack_from('<Q', model_input)[0] == struct.unpack_from('<Q', actual_frame['frame'], 8)[0]
            request = actual_frame['request']
            encoded, result = request(18, model_input)
            encoded = bytearray(encoded)
            token, total = result.token, result.total
            while len(encoded) < total:
                chunk, result = request(64, struct.pack('<QQII', token, len(encoded), 65024, 0))
                encoded.extend(chunk)
            request(65, struct.pack('<QQ', token, fnv(encoded)), 0)
            image = Image.open(io.BytesIO(encoded)); image.load()
            assert image.size == (128, 64) and image.format == 'JPEG'
            rgb = image.convert('RGB').tobytes()
            expected = actual_frame['frame'][96:]
            assert sum(abs(a - b) for a, b in zip(rgb, expected)) / len(expected) < 20
            # Native metadata/pixel reader references stay held until actual model encode/readback returns.
            stdout, stderr = process.communicate(b'\x01', timeout=30)
        finally:
            if process.poll() is None:
                process.stdin.close()
                process.wait(timeout=15)
    assert process.returncode == 0, stderr.decode(errors='replace')
    assert stdout == (b'PASS original-SSYC-serializer-and-typed-reader get_entry_rc=0 '
                       b'caller=0x29 original_main_exec=0 capture_verified=0\n')
    # No UIPC device is supplied: pure serializers run, queue operations remain untested.
    assert stderr in (b'', b'open /dev/uipc error: : No such file or directory\n')
    metadata = (tmp_path / 'actual-ssyc1024.bin').read_bytes()
    parameters = (tmp_path / 'actual-parameter128.bin').read_bytes()
    image = (tmp_path / 'actual-imagesize72.bin').read_bytes()
    assert len(metadata) == 1024 and len(parameters) == 128 and len(image) == 72 and any(metadata)
    assert struct.unpack_from('<II', image) == (0, struct.unpack_from('<I', parameters, 0x34)[0])
    assert struct.unpack_from('<HH', image, 0x2e) == (128, 64)
    assert image[0x21] == 8 and image[0x24] == 2
    assert struct.unpack_from('<Q', parameters, 0x18)[0] >= 0x1000000000000000
    (tmp_path / 'readback.json').write_text(json.dumps({
        'status': 'PASS_ORIGINAL_SERIALIZER_WITH_SOFTWARE_INPUT_MAPPING',
        'artifacts': {name: {'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()}
                      for name, raw in [('metadata1024', metadata), ('parameters128', parameters), ('image72', image)]},
        'source_pinned_scoped_mapper_used': True,
        'original_typed_metadata_to_same_retained_frame_model18': True,
        'native_input_references_held_until_actual_encode_and_result_readback': True,
        'encoded_JPEG_independently_decoded': True,
        'encoded_bytes': len(encoded), 'encoded_sha256': hashlib.sha256(encoded).hexdigest(),
        'original_Main_Exec': False, 'original_OSAL_queue_used': False,
        'capture_verified': False, 'physical_asic_compatibility_verified': False}, indent=2) + '\n')
    for path, digest in assets.items():
        assert hashlib.sha256(path.read_bytes()).hexdigest() == digest
