"""Host capture ownership tests; original AP/codec/Fsys and photos remain unverified."""
from pathlib import Path
import subprocess

import pytest

HERE = Path(__file__).resolve().parent
REPORT = HERE.parents[1] / 'report'
PRODUCT = next((p / 'final/a7c2-qemu' for p in HERE.parents
                if (p / 'final/a7c2-qemu/runtime/analysis').is_dir()), HERE.parents[1])


def source(relative):
    candidate = HERE.parents[1] / relative
    return candidate if candidate.is_file() else PRODUCT / relative


@pytest.fixture(scope='module', params=[False, True], ids=['strict', 'sanitized'])
def capture_binary(request, tmp_path_factory):
    work = tmp_path_factory.mktemp('capture-owner')
    flags = ['-std=c11', '-Wall', '-Wextra', '-Werror', '-pedantic', '-O1', '-g',
             '-pthread', '-fno-pie', '-I', str(HERE),
             '-I', str(PRODUCT / 'runtime/analysis'),
             '-I', str(PRODUCT / 'runtime/analysis/device-models'),
             '-I', str(REPORT / 'functional-capture-output'),
             '-I', str(PRODUCT / 'report/functional-capture-output')]
    if request.param:
        flags += ['-fsanitize=address,undefined', '-fno-omit-frame-pointer']
    provider = work / 'memory-provider.o'
    writer = work / 'raw-writer.o'
    commands = [
        # POSIX dlsym interposition requires function/object pointer casts.
        ['cc', *[f for f in flags if f != '-pedantic'], '-fno-builtin-memset',
         '-c', str(HERE / 'functional-capture-raw-writer.c'), '-o', str(writer)],
        ['cc', *flags, '-Dmain=memory_fixture_unused_main', '-c',
         str(source('runtime/analysis/test-functional-mpr-memory.c')), '-o', str(provider)],
        ['cc', *flags, '-no-pie', str(HERE / 'test-functional-capture.c'), str(provider), str(writer),
         *[str(source('report/' + name)) for name in [
             'functional-capture-input/capture-input.c',
             'functional-capture-output/capture-output-memory.c',
             'functional-capture-output/capture-notifications.c',
             'functional-capture-output/capture-delivery.c',
             'functional-capture-output/capture-save.c',
             'functional-capture-output/capture-dma.c',
             'functional-capture-queue/capture-resize-request.c',
             'virtual-sensor/sensor-core.c']],
         *[str(HERE / name) for name in [
             'functional-capture-raw-blobs.c', 'raw-template.c']],
         '-ldl', '-o', str(work / 'capture')],
    ]
    for argv in commands:
        built = subprocess.run(argv, capture_output=True, text=True, timeout=60)
        assert built.returncode == 0, built.stdout + built.stderr
    return work / 'capture'


@pytest.mark.parametrize('mode', range(56))
def test_capture_ownership_and_real_transport_boundaries(capture_binary, mode):
    ran = subprocess.run([str(capture_binary), str(mode)], capture_output=True,
                         text=True, timeout=20)
    assert ran.returncode == 0, ran.stdout + ran.stderr
    assert 'PASS HOST_ONLY' in ran.stdout
    assert 'original_AP=0 original_codec=0 Fsys_saved=0 capture_verified=0' in ran.stdout
    if mode in (26, 27):
        from functional_camera_runner import require_natural_capture_closed
        lines = [line for line in ran.stdout.splitlines() if line.startswith('OBS FUNCTIONAL_CAMERA_CAPTURE ')]
        assert lines and 'operation=write-retired' in lines[-1]
        pid = int(lines[0].split(' pid=')[1].split()[0])
        binding = {'mailbox': {'pid': pid, 'nonce': 22}}
        console = ('\n'.join(lines) + '\n').encode()
        require_natural_capture_closed(console, binding)
        replay = b'\n'.join(line.removeprefix(b'OBS ') for line in console.splitlines()) + b'\n'
        require_natural_capture_closed(console + replay, binding)
        for damaged in [b'\n'.join(console.splitlines()[:-1]) + b'\n',
                        console.replace(b'resources_released=1', b'resources_released=0'),
                        console.replace(b'operation=write-retired rc=0', b'operation=write-retired rc=-5'),
                        console.replace(b'model_instance=0x16', b'model_instance=0x17'),
                        console + lines[-1].encode() + b'\n']:
            with pytest.raises(ValueError):
                require_natural_capture_closed(damaged, binding)
