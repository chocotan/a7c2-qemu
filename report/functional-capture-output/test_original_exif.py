# SPDX-License-Identifier: MIT
"""Real CMOS/model18 -> original Exif writer component; AP/Fsys remain separate."""
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import struct
import subprocess
import shlex

import pytest
from PIL import Image

HERE = Path(__file__).resolve().parent
NATIVE = HERE.parent.parent
BASE = NATIVE / 'runtime/analysis'
GUEST = BASE / 'menu-root'
INPUT_TEST = NATIVE / 'report/functional-capture-input/test_capture_input.py'
spec = importlib.util.spec_from_file_location('original_exif_capture_fixture', INPUT_TEST)
capture_fixture = importlib.util.module_from_spec(spec)
spec.loader.exec_module(capture_fixture)
actual_frame = capture_fixture.actual_frame
ASSETS = {
    'libmpr.so': '4fb6d886c1ac620399d09c9c2ffc074315968cf0ada764062913c4e0783fc7f9',
    'libosal_uipc.so': '09ebf5980237fc473077dc844763dcb00cba423f431646e3be7c0ca49ea70ff3',
    'libcrypto.so.3': '893a37bd6f5a19069362e7c54c023ac9b93eb5d3c976dc45a82502fb4317a8d4',
}


def thumbnail_from_original_prefix(prefix):
    assert prefix[:4] == b'\xff\xd8\xff\xe1' and prefix[6:12] == b'Exif\0\0'
    assert struct.unpack_from('>H', prefix, 4)[0] + 4 == len(prefix)
    tiff = prefix[12:]
    assert tiff[:2] in (b'II', b'MM')
    order = '<' if tiff[:2] == b'II' else '>'
    assert struct.unpack_from(order + 'H', tiff, 2)[0] == 42
    first = struct.unpack_from(order + 'I', tiff, 4)[0]
    count = struct.unpack_from(order + 'H', tiff, first)[0]
    second = struct.unpack_from(order + 'I', tiff, first + 2 + 12 * count)[0]
    assert second
    count = struct.unpack_from(order + 'H', tiff, second)[0]
    tags = {}
    for index in range(count):
        tag, kind, number, value = struct.unpack_from(order + 'HHII', tiff, second + 2 + 12 * index)
        assert tag not in tags
        tags[tag] = (kind, number, value)
    assert tags[0x201][:2] == tags[0x202][:2] == (4, 1)
    offset, size = tags[0x201][2], tags[0x202][2]
    assert size and offset < len(tiff) and size <= len(tiff) - offset
    return tiff[offset:offset + size], offset


@pytest.fixture(scope='module')
def encoded_frame(actual_frame):
    frame = actual_frame['frame']
    frame_token = struct.unpack_from('<Q', frame, 8)[0]
    request = actual_frame['request']
    encoded = []
    for selector, geometry in enumerate(((128, 64), (160, 120))):
        data, result = request(18, struct.pack('<QII4I', frame_token, selector, 0, 1, *geometry, 90))
        assert len(data) == result.total == result.used
        request(65, struct.pack('<QQ', result.token, capture_fixture.fnv(data)), 0)
        image = Image.open(io.BytesIO(data)); image.load()
        assert image.format == 'JPEG' and image.size == geometry
        encoded.append(data)
    main, thumbnail = encoded
    request(19, struct.pack('<QII', frame_token, 3, 0), 0)
    return frame, main, thumbnail


@pytest.mark.parametrize('sanitize', [False, True], ids=['c11', 'asan-ubsan'])
@pytest.mark.parametrize('component', ['output-memory', 'capture-delivery'])
def test_real_input_output_owner_lifetime(encoded_frame, tmp_path, sanitize, component):
    names = ('frame.bin', 'main.jpg', 'thumbnail.jpg')
    for name, data in zip(names, encoded_frame):
        (tmp_path / name).write_bytes(data)
    executable = tmp_path / 'test-output-memory'
    command = shlex.split(os.environ.get('CC', 'cc')) + [
        '-std=c11', '-O1', '-g', '-Wall', '-Wextra', '-Werror', '-pedantic',
        '-I' + str(NATIVE / 'report/functional-capture-input'),
        str(HERE / ('test-' + component + '.c')), str(HERE / 'capture-output-memory.c'),
        str(HERE / 'capture-notifications.c'), str(NATIVE / 'report/functional-capture-input/capture-input.c'), '-o', str(executable)]
    if component == 'capture-delivery':
        command += ['-pthread', str(HERE / 'capture-delivery.c')]
    if sanitize:
        command += ['-fsanitize=address,undefined', '-fno-sanitize-recover=all',
                    '-fno-omit-frame-pointer', '-fno-pie', '-no-pie']
    subprocess.run(command, check=True, capture_output=True, timeout=30)
    env = dict(os.environ, ASAN_OPTIONS='detect_leaks=1:halt_on_error=1',
               UBSAN_OPTIONS='halt_on_error=1:print_stacktrace=1')
    result = subprocess.run([str(executable), *[str(tmp_path / name) for name in names]],
                            capture_output=True, env=env, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
    expected = (b'PASS real-input output-owner page-capacity-native-refs-export-refs-stale-handle-fork\n'
                if component == 'output-memory' else
                b'PASS original-consumer notification-transport inline-async-receiver-failed-send-cleanup-owned-output\n')
    assert result.stdout == expected
    assert not result.stderr


def test_actual_original_exif_consumes_same_frame_thumbnail(encoded_frame, tmp_path):
    qemu = NATIVE / 'runtime/sources/qemu-11.1.2/build-user/qemu-aarch64'
    if not qemu.is_file() or not all((GUEST / 'usr/lib' / name).is_file() for name in ASSETS):
        pytest.skip('requires prepared public ALLLANG libraries and local AArch64 user emulator')
    for name, digest in ASSETS.items():
        assert hashlib.sha256((GUEST / 'usr/lib' / name).read_bytes()).hexdigest() == digest
    frame, main, thumbnail = encoded_frame
    (tmp_path / 'frame.bin').write_bytes(frame)
    (tmp_path / 'thumbnail.jpg').write_bytes(thumbnail)
    (tmp_path / 'main.jpg').write_bytes(main)
    executable = tmp_path / 'check-original-exif'
    libraries = [GUEST / 'lib' / name for name in
                 ('libc-2.25.so', 'libdl-2.25.so', 'libpthread-2.25.so', 'ld-2.25.so')]
    command = ['clang', '--target=aarch64-linux-gnu', '-fuse-ld=lld', '-nostdlib', '-O2',
        '-mno-outline-atomics', '-std=c11', '-Wall', '-Wextra', '-Werror', '-pedantic',
        '-isystem', '/usr/aarch64-linux-gnu/include', '-Wl,--no-undefined', '-Wl,--export-dynamic',
        '-Wl,-e,_start', '-Wl,--dynamic-linker=/lib/ld-linux-aarch64.so.1',
        '-I' + str(NATIVE / 'report/functional-capture-input'),
        str(HERE / 'check-original-exif.c'), str(HERE / 'capture-output-memory.c'), str(HERE / 'capture-dma.c'),
        str(HERE / 'capture-notifications.c'), str(NATIVE / 'report/functional-capture-input/capture-input.c'),
        *map(str, libraries), '-o', str(executable)]
    subprocess.run(command, check=True, capture_output=True, timeout=30)
    payload = [str(qemu), '-L', str(GUEST), '-E',
        'LD_LIBRARY_PATH=' + str(GUEST / 'usr/lib') + ':' + str(GUEST / 'lib'),
        '/tmp/exif-check/check-original-exif', '/tmp/exif-check/thumbnail.jpg',
        *[str(GUEST / 'usr/lib' / name) for name in ASSETS], '/tmp/exif-check/main.jpg', '/tmp/exif-check/frame.bin']
    command = ['/usr/bin/bwrap', '--unshare-all', '--die-with-parent', '--new-session',
        '--ro-bind', '/', '/', '--tmpfs', '/tmp', '--dir', '/tmp/exif-check',
        '--bind', str(tmp_path), '/tmp/exif-check', '--proc', '/proc', '--dev', '/dev',
        '--chdir', '/tmp/exif-check', '--', *payload]
    env = {k: v for k, v in os.environ.items() if not k.startswith(('LD_', 'QEMU_', 'MENU_', 'SONY_'))}
    result = subprocess.run(command, capture_output=True, env=env, timeout=30)
    assert result.returncode == 0, result.stderr.decode(errors='replace')
    lines = result.stdout.splitlines()
    receipts = [line for line in lines if line.startswith(b'PASS original-libjpeg-add-finish-output-list ')]
    assert len(receipts) == 1 and b'software_DMA_copies=1' in receipts[0]
    assert b'original_AP=0 native_DMM_registered=0 Fsys_saved=0 capture_verified=0' in receipts[0]
    assert b'original_DMM_helper=1 software_owned_registry=1 production_output_owner=1 exports_checked=1 notification_lease_checked=1 notifications_sent=0 native_shares=4 native_queries=4 native_frees=4' in receipts[0]
    diagnostics = [line.decode(errors='replace') for line in lines if line != receipts[0]]
    output = (tmp_path / 'original-jpeg-output-list.bin').read_bytes()
    records = (tmp_path / 'original-output-records.bin').read_bytes()
    assert len(records) == 2 * 48
    start = (tmp_path / 'notification-start.bin').read_bytes()
    entry = (tmp_path / 'notification-entry.bin').read_bytes()
    info_wire = (tmp_path / 'notification-info.bin').read_bytes()
    assert len(start) == 24 and len(entry) == 52 and len(info_wire) == 0x2e8
    cookie = struct.unpack_from('<I', frame, 80)[0]
    assert all(wire[0] == 4 and struct.unpack_from('<I', wire, 4)[0] == cookie
               for wire in (start, entry, info_wire))
    assert [struct.unpack_from('<H', wire, 2)[0] for wire in (start, entry, info_wire)] == [0x1000, 0x1017, 0x1006]
    assert struct.unpack_from('<I', entry, 8)[0] == struct.unpack_from('<I', info_wire, 0x0c)[0] > 0
    assert struct.unpack_from('<I', info_wire, 0xb8)[0] == 1 and struct.unpack_from('<I', info_wire, 0x218)[0] == 0
    # Actual original DMM/typed mapper consumed these packet descriptors, not separate fixture handles.
    assert struct.unpack_from('<I', info_wire, 0x158)[0] == struct.unpack_from('<I', records, 48)[0]
    assert struct.unpack_from('<I', info_wire, 0x160)[0] == len(main) - 2
    assert struct.unpack_from('<I', info_wire, 0x170)[0] == len(thumbnail)
    sizes = [struct.unpack_from('<I', records, index * 48 + 8)[0] for index in range(2)]
    addresses = [struct.unpack_from('<Q', records, index * 48 + 16)[0] for index in range(2)]
    assert all(address and address % 4096 == 0 for address in addresses)
    assert sizes[0] % 4096 == 0 and sizes[1] == len(main) - 2 and sum(sizes) == len(output)
    assert output[sizes[0]:] == main[2:]
    # Use the original writer's records; do not construct a replacement JPEG stream.
    spans = [output[:sizes[0]], output[sizes[0]:]]
    projected = b''.join(span + bytes((-len(span)) % 4096) for span in spans)[:len(output)]
    assert projected == output
    exif_bytes = struct.unpack_from('>H', output, 4)[0] + 4
    prefix = output[:exif_bytes]
    embedded, offset = thumbnail_from_original_prefix(prefix)
    assert embedded == thumbnail
    decoded_thumb = Image.open(io.BytesIO(embedded)); decoded_thumb.load()
    assert decoded_thumb.size == (160, 120)
    decoded_main = Image.open(io.BytesIO(output)); decoded_main.load()
    assert decoded_main.size == (128, 64)
    expected = frame[96:]
    actual = decoded_main.convert('RGB').tobytes()
    assert sum(abs(a - b) for a, b in zip(actual, expected)) / len(expected) < 20
    (tmp_path / 'readback.json').write_text(json.dumps({
        'status': 'PASS_ORIGINAL_JPEG_ADD_FINISH_OUTPUT_RECORDS_AND_SAME_FRAME_THUMBNAIL',
        'output_bytes': len(output), 'output_sha256': hashlib.sha256(output).hexdigest(),
        'original_output_records': 2, 'original_record_bytes': sizes,
        'output_CPU_addresses_page_aligned': True, 'Fsys_page_projection_matches_original_bytes': True,
        'prefix_bytes': len(prefix), 'prefix_sha256': hashlib.sha256(prefix).hexdigest(),
        'thumbnail_bytes': len(embedded), 'thumbnail_sha256': hashlib.sha256(embedded).hexdigest(),
        'TIFF_201_thumbnail_offset': offset, 'TIFF_202_thumbnail_length': len(embedded),
        'embedded_complete_bytes_equal': True, 'main_and_thumbnail_independently_decoded': True,
        'software_DMA_and_CPU_domains_explicit': True,
        'software_alias_formula': 'owned CPU minus actual original mapping base; values may coincide',
        'metadata': 'explicit synthetic -1 sentinel',
        'original_diagnostics': diagnostics, 'XMP_metadata_verified': False,
        'original_libjpeg_factory_add_finish_executed': True, 'native_DMM_registered': False,
        'original_DMM_share_query_AreaInfo_close_consumed': True,
        'original_DMM_share_count': 4, 'original_DMM_query_count': 4, 'original_DMM_close_free_count': 4,
        'original_AreaInfo_metadata_mapping_consumed': True,
        'software_registry_keeps_owner_references_after_original_close': True,
        'reusable_output_owner_queried_by_original_helpers': True,
        'export_reference_prevents_early_output_destroy': True,
        'input_owner_held_until_output_owner_destroy': True,
        'notification_policy': 'original-consumer-virtual-cp-jpeg-v1',
        'notification_descriptors_consumed_by_original_mapper': True,
        'notification_lease_independent_from_export_lease': True,
        'notification_time_is_explicit_component_fixture': True,
        'notifications_sent': False,
        'original_mapping_base_read_without_mutation': True,
        'original_AP_executed': False, 'original_MPR_Fsys_saved': False,
        'capture_verified': False, 'physical_asic_compatibility_verified': False}, indent=2) + '\n')
    for name, digest in ASSETS.items():
        assert hashlib.sha256((GUEST / 'usr/lib' / name).read_bytes()).hexdigest() == digest
