# SPDX-License-Identifier: MIT
"""Functional Q48 producer and original-library consumer component, no AP/Fsys."""
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
from elftools.elf.elffile import ELFFile

HERE = Path(__file__).resolve().parent
NATIVE = HERE.parent.parent
BASE = NATIVE / 'runtime/analysis'
GUEST = BASE / 'menu-root'
spec = importlib.util.spec_from_file_location('capture_queue_shared_frame', HERE.parent / 'functional-capture-input/test_capture_input.py')
shared = importlib.util.module_from_spec(spec)
spec.loader.exec_module(shared)
actual_frame = shared.actual_frame
FLAGS = shared.FLAGS
ASSETS = {**shared.ASSETS,
          'libmpr.so': '4fb6d886c1ac620399d09c9c2ffc074315968cf0ada764062913c4e0783fc7f9',
          'libcrypto.so.3': '893a37bd6f5a19069362e7c54c023ac9b93eb5d3c976dc45a82502fb4317a8d4'}


def verify_original_parameter_sources():
    pins = json.loads((HERE / 'native-parameter-source-pins.json').read_text())
    path = GUEST / 'usr/lib' / pins['artifact']
    assert path.stat().st_size == pins['artifact_bytes']
    assert hashlib.sha256(path.read_bytes()).hexdigest() == pins['artifact_sha256']
    with path.open('rb') as stream:
        elf = ELFFile(stream)
        loads = [segment for segment in elf.iter_segments() if segment['p_type'] == 'PT_LOAD']
        for role in ('caller', 'constructor', 'native_table'):
            span = pins[role]
            mapped = [segment for segment in loads if segment['p_vaddr'] <= span['va'] and
                      span['bytes'] <= segment['p_filesz'] - (span['va'] - segment['p_vaddr'])]
            assert len(mapped) == 1
            segment = mapped[0]
            assert bool(segment['p_flags'] & 1) == (role != 'native_table')
            offset = segment['p_offset'] + span['va'] - segment['p_vaddr']
            assert offset == span['file_offset']
            stream.seek(offset)
            raw = stream.read(span['bytes'])
            assert len(raw) == span['bytes'] and hashlib.sha256(raw).hexdigest() == span['sha256']
            if role == 'native_table':
                rows = list(struct.iter_unpack('<3I', raw))
                assert len(rows) == 30 and rows[-1][0] == 0x1000 and all(row[0] != 0x1000 for row in rows[:-1])
                for key, expected in span['consumer_roles'].items():
                    assert [row[1:] for row in rows if row[0] == int(key, 0)] == [(expected['type'], expected['bytes'])]


@pytest.mark.parametrize('sanitize', [False, True], ids=['c11', 'asan-ubsan'])
def test_functional_request_preserves_original_identity_and_input_hold(actual_frame, tmp_path, sanitize):
    (tmp_path / 'frame.bin').write_bytes(actual_frame['frame'])
    flags = ['-O1', '-g', '-fsanitize=address,undefined', '-fno-sanitize-recover=all',
             '-fno-omit-frame-pointer', '-fno-pie', '-no-pie'] if sanitize else ['-O2']
    executable = tmp_path / 'queue-check'
    command = shlex.split(os.environ.get('CC', 'cc')) + FLAGS + flags + [
        str(HERE / 'test-resize-request.c'), str(HERE / 'capture-resize-request.c'), '-o', str(executable)]
    subprocess.run(command, check=True, capture_output=True, timeout=30)
    result = subprocess.run([str(executable), str(tmp_path / 'frame.bin')], capture_output=True,
        env=dict(os.environ, ASAN_OPTIONS='detect_leaks=1:halt_on_error=1', UBSAN_OPTIONS='halt_on_error=1:print_stacktrace=1'), timeout=30)
    assert result.returncode == 0, result.stderr.decode(errors='replace')
    assert result.stdout == b'PASS functional-Q48-real-P128-request-identity-and-hold no-send no-ACK capture_verified=0\n'
    assert not result.stderr


def test_original_router_ack_main_and_comp_consume_same_retained_frame(actual_frame, tmp_path):
    qemu = NATIVE / 'runtime/sources/qemu-11.1.2/build-user/qemu-aarch64'
    assets = {GUEST / 'usr/lib' / name: digest for name, digest in ASSETS.items()}
    if not qemu.is_file() or not all(path.is_file() for path in assets):
        pytest.skip('requires prepared public ALLLANG libraries and local AArch64 user emulator')
    for path, digest in assets.items():
        assert hashlib.sha256(path.read_bytes()).hexdigest() == digest
    verify_original_parameter_sources()
    executable = tmp_path / 'check-original-queue'
    libraries = [GUEST / 'lib' / name for name in ('libc-2.25.so', 'libdl-2.25.so', 'libpthread-2.25.so', 'ld-2.25.so')]
    command = ['clang', '--target=aarch64-linux-gnu', '-fuse-ld=lld', '-nostdlib', '-O2',
        '-mno-outline-atomics', *FLAGS, '-isystem', '/usr/aarch64-linux-gnu/include',
        '-Wl,--no-undefined', '-Wl,--export-dynamic', '-Wl,-e,_start',
        '-Wl,--dynamic-linker=/lib/ld-linux-aarch64.so.1', str(HERE / 'check-original-queue.c'),
        str(HERE / 'capture-resize-request.c'), str(BASE / 'functional-mpr-memory.c'),
        str(HERE.parent / 'functional-capture-input/capture-mapper.c'),
        str(HERE.parent / 'functional-capture-input/capture-jpeg-input.c'),
        *map(str, libraries), '-o', str(executable)]
    subprocess.run(command, check=True, capture_output=True, timeout=30)
    exports = subprocess.check_output(['nm', '-D', '--defined-only', str(executable)], text=True, timeout=15)
    for symbol in ('_ZN12InfraAvbbcIf4MainEv', '_ZN20ExecCmd_ResizeEncAck7ExecCmdEPKh',
                   '_ZN26ExecCmd_SDF_EncodeJpegMain7ExecCmdEPKh',
                   '_ZN30ExecCmd_SDF_EncodeJpegMainComp6ResCmdEPKht'):
        assert not any(line.split()[-1] == symbol for line in exports.splitlines())
    (tmp_path / 'frame.bin').write_bytes(actual_frame['frame'])
    payload = [str(qemu), '-L', str(GUEST), '-E',
        'LD_LIBRARY_PATH=' + str(GUEST / 'usr/lib') + ':' + str(GUEST / 'lib'),
        '/tmp/capture-queue/check-original-queue', '/tmp/capture-queue/frame.bin',
        *[str(GUEST / 'usr/lib' / name) for name in ASSETS]]
    command = ['/usr/bin/bwrap', '--unshare-all', '--die-with-parent', '--new-session',
        '--ro-bind', '/', '/', '--tmpfs', '/tmp', '--dir', '/tmp/capture-queue',
        '--bind', str(tmp_path), '/tmp/capture-queue', '--proc', '/proc', '--dev', '/dev',
        '--chdir', '/tmp/capture-queue', '--', *payload]
    env = {k: v for k, v in os.environ.items() if not k.startswith(('LD_', 'QEMU_', 'MENU_', 'SONY_'))}
    outputs = []
    with subprocess.Popen(command, env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE) as process:
        try:
            for selector, name in enumerate(('main', 'thumb')):
                assert select.select([process.stdout], [], [], 30)[0], 'original Main did not publish actual typed input'
                line = process.stdout.readline()
                if not line:
                    remaining, failed_stderr = process.communicate(timeout=15)
                    (tmp_path / 'native-early.stdout').write_bytes(remaining)
                    (tmp_path / 'native-early.stderr').write_bytes(failed_stderr)
                    pytest.fail(f'original native component exited {process.returncode}: {failed_stderr.decode(errors="replace")}')
                assert line == f'MODEL18_ORIGINAL_MAIN_READY selector={selector} native_input_references_held=1\n'.encode(), (line, process.poll())
                model_input = (tmp_path / f'actual-{name}32.bin').read_bytes()
                body = (tmp_path / f'actual-{name}80.bin').read_bytes()
                assert len(model_input) == 32 and len(body) == 80
                assert struct.unpack_from('<Q', model_input)[0] == struct.unpack_from('<Q', actual_frame['frame'], 8)[0]
                assert struct.unpack_from('<I', model_input, 8)[0] == selector
                assert struct.unpack_from('<I', model_input, 28)[0] == (95 if not selector else 75)
                assert struct.unpack_from('<HH', body, 0x40) == ((128, 64) if not selector else (160, 120))
                assert body[0x4b] == selector and body[0x49] == (2 if not selector else 4)
                encoded, result = actual_frame['request'](18, model_input)
                encoded = bytearray(encoded)
                token, total = result.token, result.total
                while len(encoded) < total:
                    chunk, result = actual_frame['request'](64, struct.pack('<QQII', token, len(encoded), 65024, 0))
                    encoded.extend(chunk)
                actual_frame['request'](65, struct.pack('<QQ', token, shared.fnv(encoded)), 0)
                image = Image.open(io.BytesIO(encoded)); image.load()
                assert image.format == 'JPEG' and image.size == ((128, 64) if not selector else (160, 120))
                source = Image.frombytes('RGB', (128, 64), actual_frame['frame'][96:])
                if selector:
                    source = source.resize((160, 120), Image.Resampling.NEAREST)
                decoded = image.convert('RGB').tobytes()
                assert sum(abs(a - b) for a, b in zip(decoded, source.tobytes())) / len(decoded) < 25
                (tmp_path / f'encoded-{name}.jpg').write_bytes(encoded)
                outputs.append(bytes(encoded))
                process.stdin.write(b'\x01'); process.stdin.flush()
            stdout, stderr = process.communicate(timeout=30)
        finally:
            if process.poll() is None:
                process.stdin.close()
                process.wait(timeout=15)
    assert process.returncode == 0, stderr.decode(errors='replace')
    assert stdout == (b'PASS original-router-ResizeEncAck-Main-MainComp same_frame=1 ACK_before_Pcopy=1 selectors=2 '
                      b'original_SetMemTbl=1 original_GetStillBufConfig=1 production_SDS=1 '
                      b'original_ParameterControl=1 IO_fixture=1 ParameterControl_fixture=0 original_AP=0 Fsys_saved=0 capture_verified=0\n')
    assert stderr in (b'', b'open /dev/uipc error: : No such file or directory\n')
    assert (tmp_path / 'native-main-no-soi.bin').read_bytes() == outputs[0][2:]
    assert (tmp_path / 'native-thumb.bin').read_bytes() == outputs[1]
    request = (tmp_path / 'actual-request16.bin').read_bytes()
    queue = (tmp_path / 'actual-queue48.bin').read_bytes()
    route = (tmp_path / 'actual-route64.bin').read_bytes()
    parameter = (tmp_path / 'actual-parameter-copy128.bin').read_bytes()
    order = struct.unpack('<6Q', (tmp_path / 'actual-order48.bin').read_bytes())
    assert request == struct.pack('<IIB3xI', 0x40380005, 29, 2, 0)
    assert len(queue) == 48 and struct.unpack_from('<H', queue, 2)[0] == 2
    assert struct.unpack_from('<I', queue, 0x10)[0] == 128 and struct.unpack_from('<I', queue, 0x24)[0] == 0x1500
    assert struct.unpack_from('<Q', queue, 0x28)[0] and len(parameter) == 128
    assert len(route) == 64 and route[16:] == queue
    assert struct.unpack_from('<I', route)[0] == 0x80c70047 and struct.unpack_from('<3H', route, 8) == (0x7000, 0x9000, 56)
    assert struct.unpack_from('<Q', route, 0x38)[0] == struct.unpack_from('<Q', queue, 0x28)[0]
    assert all(a < b for a, b in zip(order[:4], order[1:5]))
    assert order[5] == struct.unpack_from('<Q', actual_frame['frame'], 8)[0]
    config = (tmp_path / 'actual-config120.bin').read_bytes()
    config_before = (tmp_path / 'actual-config-before120.bin').read_bytes()
    table = (tmp_path / 'actual-buffer-table.bin').read_bytes()
    assert len(table) == 0x760 and len(config) == len(config_before) == 120
    assert struct.unpack_from('<I', config, 0x5c)[0] == len(outputs[0]) - 2
    assert struct.unpack_from('<I', config, 0x68)[0] == len(outputs[1])
    assert struct.unpack_from('<I', config_before, 0x68)[0] == 0x2ffc
    assert struct.unpack_from('<I', config, 0x54)[0] == struct.unpack_from('<I', config, 0x60)[0] != 0
    for offset, raw in ((0x54, outputs[0][2:]), (0x60, outputs[1])):
        handle, position, capacity = struct.unpack_from('<3I', config_before, offset)
        assert handle and position and 0 < len(raw) <= capacity
        request = (tmp_path / ('actual-main80.bin' if offset == 0x54 else 'actual-thumb80.bin')).read_bytes()
        assert struct.unpack_from('<I', request, 0x28)[0] == handle
        assert struct.unpack_from('<I', request, 0x38)[0] == position
        assert struct.unpack_from('<I', request, 0x3c)[0] == capacity
    for path, digest in assets.items():
        assert hashlib.sha256(path.read_bytes()).hexdigest() == digest
    (tmp_path / 'readback.json').write_text(json.dumps(dict(
        status='PASS_ORIGINAL_ROUTER_ACK_MAIN_COMP_WITH_EXPLICIT_IO_AND_PARAMETER_FIXTURES',
        real_model17_frame=True, actual_original_router=True, actual_original_resize_ack=True,
        actual_original_main_exec=True, actual_original_main_comp=True, ACK_before_P128_copy=True,
        original_SetMemTbl=True, original_GetStillBufConfig=True, production_memory_provider=True,
        production_SDS_actual_write_and_readback=True, original_Table_writer_replaced=False,
        original_codec_config_send_fixture=True, explicit_functional_allocation_mode=16,
        software_thumbnail_quality_ceiling=75, main_model_quality=95,
        original_Sony_quality_semantics_verified=False, original_output_capacity_guard_preserved=True,
        original_native_methods_replaced=False, IO_delivery_fixture=True, ParameterControl_storage_fixture=False,
        original_ParameterControl_ctor_and_table=True, original_struct_and_pointer_values_verified=True,
        actual_model18_consumed_same_frame=True, independent_JPEG_decode=True, native_output_lengths_readback=True,
        actual_original_queue_or_AP_received=False, original_MPR_Fsys_saved=False,
        output_sha256=[hashlib.sha256(raw).hexdigest() for raw in outputs],
        artifacts={path.name: dict(bytes=path.stat().st_size, sha256=hashlib.sha256(path.read_bytes()).hexdigest())
                   for path in sorted(tmp_path.glob('*')) if path.suffix in ('.bin', '.jpg')},
        capture_verified=False, physical_asic_compatibility_verified=False), indent=2) + '\n')


def test_original_sender_wait_ack_callback_and_real_P128_store(actual_frame, tmp_path):
    qemu = NATIVE / 'runtime/sources/qemu-11.1.2/build-user/qemu-aarch64'
    names = ('libmpr.so', 'libInfraAvbbc.so', 'libcrypto.so.3', 'libosal_uipc.so')
    if not qemu.is_file() or not all((GUEST / 'usr/lib' / name).is_file() for name in names):
        pytest.skip('requires prepared public ALLLANG libraries and local AArch64 user emulator')
    for name in names:
        assert hashlib.sha256((GUEST / 'usr/lib' / name).read_bytes()).hexdigest() == ASSETS[name]
    verify_original_parameter_sources()
    executable = tmp_path / 'check-original-sender'
    libraries = [GUEST / 'lib' / name for name in ('libc-2.25.so', 'libdl-2.25.so', 'libpthread-2.25.so', 'ld-2.25.so')]
    subprocess.run(['clang', '--target=aarch64-linux-gnu', '-fuse-ld=lld', '-nostdlib', '-O2',
        '-mno-outline-atomics', *FLAGS, '-isystem', '/usr/aarch64-linux-gnu/include',
        '-Wl,--no-undefined', '-Wl,--export-dynamic', '-Wl,-e,_start',
        '-Wl,--dynamic-linker=/lib/ld-linux-aarch64.so.1', str(HERE / 'check-original-sender.c'),
        str(HERE / 'capture-resize-request.c'), *map(str, libraries), '-o', str(executable)],
        check=True, capture_output=True, timeout=30)
    exports = subprocess.check_output(['nm', '-D', '--defined-only', str(executable)], text=True, timeout=15)
    assert not any(name in exports for name in ('SendMsgToAvbbc', 'CallbackFromAvbbc', 'GetExpectedCodecEvent',
                   'ResizeEncAck7ExecCmd', 'InfraAvbbcIf4Main', 'ParameterControl8SetValue', 'ParameterControl8GetValue'))
    (tmp_path / 'frame.bin').write_bytes(actual_frame['frame'])
    payload = [str(qemu), '-L', str(GUEST), '-E',
        'LD_LIBRARY_PATH=' + str(GUEST / 'usr/lib') + ':' + str(GUEST / 'lib'),
        '/tmp/capture-sender/check-original-sender', '/tmp/capture-sender/frame.bin',
        *[str(GUEST / 'usr/lib' / name) for name in names]]
    command = ['/usr/bin/bwrap', '--unshare-all', '--die-with-parent', '--new-session',
        '--ro-bind', '/', '/', '--tmpfs', '/tmp', '--dir', '/tmp/capture-sender',
        '--bind', str(tmp_path), '/tmp/capture-sender', '--proc', '/proc', '--dev', '/dev',
        '--chdir', '/tmp/capture-sender', '--', *payload]
    env = {k: v for k, v in os.environ.items() if not k.startswith(('LD_', 'QEMU_', 'MENU_', 'SONY_'))}
    result = subprocess.run(command, env=env, capture_output=True, timeout=40)
    assert result.returncode == 0, result.stderr.decode(errors='replace')
    assert result.stdout == (b'PASS actual-original-SendMsgToAvbbc-ResizeEncAck-CallbackFromAvbbc ACK1_wait_reset2 '
        b'original_ParameterControl=1 deep_copy128=1 request_free=1 reply_free=1 input_hold=1 '
        b'IO_fixture=1 ParameterControl_fixture=0 original_AP=0 capture_verified=0\n')
    assert result.stderr in (b'', b'open /dev/uipc error: : No such file or directory\n')
    q = (tmp_path / 'actual-original-sender-Q48.bin').read_bytes()
    routed = (tmp_path / 'actual-original-route-S64.bin').read_bytes()
    copied = (tmp_path / 'actual-original-copy-P128.bin').read_bytes()
    order = struct.unpack('<3Q', (tmp_path / 'actual-original-order24.bin').read_bytes())
    assert len(q) == 48 and len(routed) == 64 and routed[16:] == q and len(copied) == 128
    assert struct.unpack_from('<I', routed)[0] == 0x80c70047
    assert struct.unpack_from('<H', q, 2)[0] == 2 and struct.unpack_from('<I', q, 0x24)[0] == 0x1500
    assert struct.unpack_from('<Q', q, 0x28)[0] == struct.unpack_from('<Q', routed, 0x38)[0] > 0
    assert 0 < order[0] < order[1] and order[0] < order[2]
    assert copied[0x63] == 8 and struct.unpack_from('<HH', copied, 0x68) == (128, 64)
    for name in names:
        assert hashlib.sha256((GUEST / 'usr/lib' / name).read_bytes()).hexdigest() == ASSETS[name]
    (tmp_path / 'sender-readback.json').write_text(json.dumps(dict(
        status='PASS_ACTUAL_ORIGINAL_SENDER_WAIT_ACK_CALLBACK_AND_PARAMETERCONTROL',
        actual_original_SendMsgToAvbbc=True, actual_original_CallbackFromAvbbc=True,
        original_cond_wait_and_signal=True, original_ParameterControl=True, actual_deep_P128_copy=True,
        request_freed=1, reply_freed=1, ACK_senderreturn_copy_ordinals=list(order),
        OSAL_message_backing_and_delivery_fixture=True, ParameterControl_fixture=False,
        artifacts={path.name: dict(bytes=path.stat().st_size, sha256=hashlib.sha256(path.read_bytes()).hexdigest())
                   for path in sorted(tmp_path.glob('actual-original-*.bin'))},
        new_original_VM=False, original_AP=False, original_MPR_Fsys_saved=False,
        capture_verified=False, physical_asic_compatibility_verified=False), indent=2) + '\n')
