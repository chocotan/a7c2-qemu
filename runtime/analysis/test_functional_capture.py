"""Host capture ownership tests; original AP/codec/Fsys and photos remain unverified."""
from pathlib import Path
import subprocess

import pytest

HERE = Path(__file__).resolve().parent
REPORT = HERE.parents[1] / 'report'


@pytest.fixture(scope='module', params=[False, True], ids=['strict', 'sanitized'])
def capture_binary(request, tmp_path_factory):
    work = tmp_path_factory.mktemp('capture-owner')
    flags = ['-std=c11', '-Wall', '-Wextra', '-Werror', '-pedantic', '-O1', '-g',
             '-pthread', '-fno-pie', '-I', str(HERE)]
    if request.param:
        flags += ['-fsanitize=address,undefined', '-fno-omit-frame-pointer']
    provider = work / 'memory-provider.o'
    commands = [
        ['cc', *flags, '-Dmain=memory_fixture_unused_main', '-c',
         str(HERE / 'test-functional-mpr-memory.c'), '-o', str(provider)],
        ['cc', *flags, '-no-pie', str(HERE / 'test-functional-capture.c'), str(provider),
         str(REPORT / 'functional-capture-input/capture-input.c'),
         str(REPORT / 'functional-capture-output/capture-output-memory.c'),
         str(REPORT / 'functional-capture-output/capture-notifications.c'),
         str(REPORT / 'functional-capture-output/capture-delivery.c'),
         str(REPORT / 'functional-capture-output/capture-save.c'),
         str(REPORT / 'functional-capture-output/capture-dma.c'),
         str(REPORT / 'functional-capture-queue/capture-resize-request.c'),
         '-ldl', '-o', str(work / 'capture')],
    ]
    for argv in commands:
        built = subprocess.run(argv, capture_output=True, text=True, timeout=60)
        assert built.returncode == 0, built.stdout + built.stderr
    return work / 'capture'


@pytest.mark.parametrize('mode', range(28))
def test_capture_ownership_and_real_transport_boundaries(capture_binary, mode):
    ran = subprocess.run([str(capture_binary), str(mode)], capture_output=True,
                         text=True, timeout=20)
    assert ran.returncode == 0, ran.stdout + ran.stderr
    assert 'PASS HOST_ONLY' in ran.stdout
    assert 'original_AP=0 original_codec=0 Fsys_saved=0 capture_verified=0' in ran.stdout
    if mode >= 26:
        from functional_camera_runner import require_natural_capture_closed
        lines = [line for line in ran.stdout.splitlines() if line.startswith('OBS FUNCTIONAL_CAMERA_CAPTURE ')]
        assert lines and 'operation=write-retired' in lines[-1]
        pid = int(lines[0].split(' pid=')[1].split()[0])
        binding = {'mailbox': {'pid': pid, 'nonce': 22}}
        console = ('\n'.join(lines) + '\n').encode()
        require_natural_capture_closed(console, binding)
        for damaged in [b'\n'.join(console.splitlines()[:-1]) + b'\n',
                        console.replace(b'resources_released=1', b'resources_released=0'),
                        console.replace(b'operation=write-retired rc=0', b'operation=write-retired rc=-5'),
                        console.replace(b'model_instance=0x16', b'model_instance=0x17'),
                        console + lines[-1].encode() + b'\n']:
            with pytest.raises(ValueError):
                require_natural_capture_closed(damaged, binding)
