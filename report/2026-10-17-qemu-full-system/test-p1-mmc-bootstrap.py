#!/usr/bin/env python3
"""Host/core/DTB tests; optional real QEMU bus test, never kernel/module init."""
import ctypes
import json
import os
from pathlib import Path
import runpy
import socket
import subprocess
import time

import pytest

HERE = Path(__file__).resolve().parent
API = runpy.run_path(str(HERE / 'p1-mmc-bootstrap.py'))


class State(ctypes.Structure):
    _fields_ = [(n, ctypes.c_uint64) for n in ('reads', 'rejections', 'first_address', 'first_value')] + [
        (n, ctypes.c_uint32) for n in ('phase', 'first_error', 'first_width')]


@pytest.fixture(scope='module')
def core(tmp_path_factory):
    out = tmp_path_factory.mktemp('mmc-core')
    result = subprocess.run(['cc', '-std=c11', '-O2', '-Wall', '-Wextra', '-Werror', '-pedantic',
        '-fPIC', '-shared', str(HERE / 'p1-mmc-model.c'), '-o', str(out / 'core.so')], capture_output=True)
    assert result.returncode == 0, result.stderr.decode()
    lib = ctypes.CDLL(str(out / 'core.so'))
    lib.p1_mmc_reset.argtypes = [ctypes.POINTER(State)]
    lib.p1_mmc_read.argtypes = [ctypes.POINTER(State), ctypes.c_uint64, ctypes.c_uint, ctypes.POINTER(ctypes.c_uint64)]
    lib.p1_mmc_write.argtypes = [ctypes.POINTER(State), ctypes.c_uint64, ctypes.c_uint, ctypes.c_uint64]
    return lib


def test_identification_and_independent_reset(core):
    a, b, value = State(), State(), ctypes.c_uint64(0x123456789abcdef0)
    core.p1_mmc_reset(ctypes.byref(a)); core.p1_mmc_reset(ctypes.byref(b))
    for _ in range(3):
        assert core.p1_mmc_read(ctypes.byref(a), 0xf13b8000, 4, ctypes.byref(value)) == 0
        assert value.value == 0x1000 and (value.value >> 12) & 15 == 1
    assert a.phase == 1 and a.reads == 3 and a.rejections == 0
    assert bytes(b) == bytes(State())
    core.p1_mmc_reset(ctypes.byref(a)); assert bytes(a) == bytes(b)


@pytest.mark.parametrize('width', [0, 1, 2, 3, 5, 8, 16, 0xffffffff])
def test_width_rejected_no_output_or_ready(core, width):
    state, value = State(), ctypes.c_uint64(0xaabbccdd)
    assert core.p1_mmc_read(ctypes.byref(state), 0xf13b8000, width, ctypes.byref(value)) == 1
    assert value.value == 0xaabbccdd
    assert state.phase == 2 and state.first_width == width and state.first_error == 1
    assert core.p1_mmc_read(ctypes.byref(state), 0xf13b8000, 4, ctypes.byref(value)) == 4
    assert state.reads == 0 and state.rejections == 2 and state.first_width == width


def test_unknown_addresses_never_fall_through_to_ram(core):
    addresses = [0, 0xffffffffffffffff, 0xf1388000, 0xf13a1000, 0xf13b7ffc, 0xf13b9000]
    addresses += list(range(0xf13b8001, 0xf13b9000))
    for address in addresses:
        state, value = State(), ctypes.c_uint64(0xdeadbeef)
        assert core.p1_mmc_read(ctypes.byref(state), address, 4, ctypes.byref(value)) == 2
        assert state.first_address == address and state.reads == 0 and value.value == 0xdeadbeef


def test_writes_including_zero_are_faults_and_first_error_survives(core):
    for value in (0, 1, 0x1000, 0xffffffff, 0xffffffffffffffff):
        state = State()
        assert core.p1_mmc_write(ctypes.byref(state), 0xf13b8000, 4, value) == 3
        assert state.first_value == value and state.first_error == 3
        assert core.p1_mmc_write(ctypes.byref(state), 0xf13b8004, 8, value ^ 1) == 4
        assert state.first_address == 0xf13b8000 and state.first_value == value
        assert state.first_width == 4 and state.first_error == 3
    assert core.p1_mmc_write(ctypes.byref(State()), 0xf13b8004, 4, 0) == 2
    assert core.p1_mmc_write(ctypes.byref(State()), 0xf13b8000, 1, 0) == 1


def test_null_argument_rejects_without_mutation(core):
    state, value = State(), ctypes.c_uint64(0x1234)
    assert core.p1_mmc_read(None, 0xf13b8000, 4, ctypes.byref(value)) == 5
    assert core.p1_mmc_read(ctypes.byref(state), 0xf13b8000, 4, None) == 5
    assert core.p1_mmc_write(None, 0xf13b8000, 4, 0) == 5
    assert bytes(state) == bytes(State()) and value.value == 0x1234


def dtb(tmp_path, enabled=True):
    runtime = HERE.parents[1] / 'runtime'
    lib = (runtime / 'sources/qemu-tools/usr/lib/libfdt.so.1').resolve()
    out = tmp_path / ('mmc.dtb' if enabled else 'default.dtb')
    API['PROBE']['board'](runtime / 'analysis/qemu-virt-board/virt-packed.dtb', lib, out,
        'init=/p1-probe', 12345, mmc_iomap=enabled)
    return out, lib


def test_dtb_adds_single_page_and_reads_back_unchanged_gic_and_scu(tmp_path):
    out, lib = dtb(tmp_path)
    rows = API['iomaps'](out, lib)
    assert rows['sony-gic-alias'] == dict(phys=0x08000000, virt=0xfffffffff13a1000, size=4096)
    assert rows['sony-mmc-identification-map']['size'] == 4096
    default, lib = dtb(tmp_path, False)
    with pytest.raises(ValueError, match='Missing required iomap'):
        API['iomaps'](default, lib)
    with pytest.raises(ValueError, match='explicit bool'):
        API['PROBE']['board'](default, lib, tmp_path / 'bad.dtb', '', 1, mmc_iomap=1)


@pytest.mark.parametrize('node,key,value', [
    ('sony-gic-alias', 'phys', 0xf13a1000),
    ('sony-gic-alias', 'virt', 0xfffffffff13b8000),
    ('sony-gic-alias', 'size', 0x2000),
    ('sony-scu-map', 'size', 0x33000),
    ('sony-mmc-identification-map', 'size', 0x3000),
    ('sony-mmc-identification-map', 'virt', 0xfffffffff13a1000),
])
def test_changed_alias_or_overlarge_mapping_is_rejected(tmp_path, node, key, value):
    out, libpath = dtb(tmp_path)
    lib = ctypes.CDLL(str(libpath)); buffer = ctypes.create_string_buffer(out.read_bytes())
    offset = lib.fdt_path_offset(buffer, ('/' + node).encode()); assert offset >= 0
    assert lib.fdt_setprop(buffer, offset, key.encode(), value.to_bytes(8, 'big'), 8) == 0
    out.write_bytes(buffer.raw[:int.from_bytes(buffer.raw[4:8], 'big')])
    with pytest.raises(ValueError):
        API['iomaps'](out, libpath)


@pytest.mark.parametrize('axis', ['phys', 'virt'])
def test_extra_iomap_cannot_hide_overlap_with_preserved_alias(tmp_path, axis):
    out, libpath = dtb(tmp_path)
    lib = ctypes.CDLL(str(libpath)); source = ctypes.create_string_buffer(out.read_bytes())
    buffer = ctypes.create_string_buffer(65536)
    assert lib.fdt_open_into(source, buffer, len(buffer)) == 0
    node = lib.fdt_add_subnode(buffer, 0, b'extra-alias'); assert node >= 0
    fields = dict(phys=0x12345000, virt=0xffffffff12345000, size=4096)
    fields[axis] = 0x08000000 if axis == 'phys' else 0xfffffffff13a1000
    assert lib.fdt_setprop(buffer, node, b'device_type', b'iomap\0', 6) == 0
    for key, value in fields.items():
        assert lib.fdt_setprop(buffer, node, key.encode(), value.to_bytes(8, 'big'), 8) == 0
    assert lib.fdt_pack(buffer) == 0
    out.write_bytes(buffer.raw[:int.from_bytes(buffer.raw[4:8], 'big')])
    with pytest.raises(ValueError, match='Overlapping iomaps'):
        API['iomaps'](out, libpath)


def test_receipt_cannot_promote_identification_to_module_init(tmp_path):
    row = dict(schema='a7c2.p1-mmc-bootstrap-source.v1', status='source-verified', profile=API['PROFILE'],
        register_contract=API['ID_CONTRACT'], blockers=API['BLOCKERS'], identification_slice_closed=True,
        initialization_contract_closed=True, original_module_load_allowed=True, inputs=[], modules=[])
    path = tmp_path / 'forged.json'; path.write_text(json.dumps(row))
    with pytest.raises(ValueError, match='Only the source-bound identification slice'):
        API['check_source'](path)
    row.update(initialization_contract_closed=False, original_module_load_allowed=False)
    path.write_text(json.dumps(row))
    with pytest.raises(ValueError, match='bindings missing'):
        API['check_source'](path)


def test_core_cross_compiles_aarch64(tmp_path):
    subprocess.run(['aarch64-linux-gnu-gcc', '-std=c11', '-O2', '-Wall', '-Wextra', '-Werror',
        '-pedantic', '-c', str(HERE / 'p1-mmc-model.c'), '-o', str(tmp_path / 'core-aarch64.o')], check=True)


def test_private_qemu_profile_rejects_empty_unknown_and_legacy_conflicts(tmp_path):
    receipt_path = os.environ.get('P1_MMC_QEMU_RECEIPT')
    if not receipt_path:
        pytest.skip('Set P1_MMC_QEMU_RECEIPT for private compiled profile rejection checks')
    receipt = json.loads(Path(receipt_path).read_text())
    assert receipt['status'] == 'compiled' and receipt['original_module_load_allowed'] is False
    binary = receipt['qemu']; API['exact'](binary['path'], binary['sha256'])
    cases = [dict(QEMU_P1_MMC_BOOTSTRAP=''), dict(QEMU_P1_MMC_BOOTSTRAP='unknown'),
        dict(QEMU_P1_MMC_BOOTSTRAP=API['PROFILE'], QEMU_SONY_MMC_TRACE='0'),
        dict(QEMU_P1_MMC_BOOTSTRAP=API['PROFILE'], QEMU_SONY_MEDIA_DETECT='')]
    owners = []
    for index, flags in enumerate(cases):
        directory = tmp_path / str(index); directory.mkdir(mode=0o700)
        argv = [binary['path'], '-machine', 'virt,secure=off,gic-version=2', '-cpu', 'cortex-a53',
            '-m', '64M', '-accel', 'qtest', '-nodefaults', '-display', 'none', '-monitor', 'none',
            '-serial', 'none', '-nic', 'none', '-S', '-qmp', 'unix:qmp,server=on,wait=off']
        with (directory / 'qemu.log').open('xb') as log:
            process = subprocess.Popen(argv, cwd=directory, env=dict(PATH=os.defpath, LC_ALL='C', **flags),
                stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT)
        try:
            rc = process.wait(timeout=10)
            assert rc == 1 and b'invalid/conflicting P1 MMC identification profile' in (directory / 'qemu.log').read_bytes()
            owners.append(dict(pid=process.pid, returncode=rc, vm_signals=[],
                               owner_absent=not Path('/proc/' + str(process.pid)).exists(), rejected_environment=flags))
            API['save'](directory / 'owner.json', owners[-1])
        finally:
            if process.poll() is None:
                connection, stream, qmp = API['PROBE']['OWNER']['qmp_connect'](directory / 'qmp')
                try:
                    qmp('quit'); process.wait(timeout=10)
                finally:
                    stream.close(); connection.close()
    API['save'](tmp_path / 'profile-rejections.json', dict(qemu=binary, owners=owners,
        scope='host startup rejection; no original kernel/module execution'))


def test_private_build_real_qemu_bus_and_normal_quit(tmp_path):
    receipt_path = os.environ.get('P1_MMC_QEMU_RECEIPT')
    if not receipt_path:
        pytest.skip('Set P1_MMC_QEMU_RECEIPT to the private built identification-only receipt')
    receipt = json.loads(Path(receipt_path).read_text())
    assert receipt['status'] == 'compiled' and receipt['original_module_load_allowed'] is False
    binary = receipt['qemu']; API['exact'](binary['path'], binary['sha256'])
    owners = []
    for label, commands, enabled in [
        ('default', [], False),
        ('id-read', ['readl 0xf13b8000', 'readl 0xf13b8000'], True),
        ('unknown', ['readl 0xf13b8004', 'readl 0xf13b8000'], True),
        ('width', ['readb 0xf13b8000', 'readl 0xf13b8000'], True),
        ('write', ['writel 0xf13b8000 0x1000', 'readl 0xf13b8000'], True),
    ]:
        logpath = tmp_path / (label + '.log')
        short = tmp_path / label
        short.mkdir(mode=0o700)
        env = dict(PATH=os.defpath, LC_ALL='C')
        if enabled:
            env['QEMU_P1_MMC_BOOTSTRAP'] = API['PROFILE']
        # qtest is not TCG; virt admits cortex-a35 only with the TCG accelerator.
        argv = [binary['path'], '-machine', 'virt,secure=off,gic-version=2', '-cpu', 'cortex-a53',
            '-m', '64M', '-smp', '1', '-accel', 'qtest', '-nodefaults', '-display', 'none',
            '-monitor', 'none', '-serial', 'none', '-nic', 'none', '-S',
            '-qtest', 'unix:test,server=on,wait=off',
            '-qmp', 'unix:qmp,server=on,wait=off']
        with logpath.open('xb') as log:
            process = subprocess.Popen(argv, cwd=short, env=env, stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT)
        API['save'](short / 'owner.json', dict(pid=process.pid, command=argv, vm_signals=[], status='starting'))
        connection = stream = None
        try:
            deadline = time.monotonic() + 10
            while True:
                assert process.poll() is None and time.monotonic() < deadline, logpath.read_text()
                if (short / 'qmp').exists():
                    try:
                        connection, stream, qmp = API['PROBE']['OWNER']['qmp_connect'](short / 'qmp')
                        break
                    except ConnectionRefusedError:
                        pass
                time.sleep(.01)
            tree = qmp('human-monitor-command', {'command-line': 'info mtree'})['return']
            assert ('p1-mmc-identification-only' in tree) == enabled
            with socket.socket(socket.AF_UNIX) as wire:
                wire.settimeout(5)
                directory = os.open(short, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
                try:
                    wire.connect('/proc/self/fd/' + str(directory) + '/test')
                finally:
                    os.close(directory)
                with wire.makefile('rb') as reader:
                    for command in commands:
                        wire.sendall((command + '\n').encode())
                        response = reader.readline().decode().strip()
                        assert response.startswith('OK'), response
                        if label == 'id-read':
                            assert int(response.split()[1], 0) == 0x1000
            result = qmp('quit')
            assert result == {'return': {}}
            process.wait(timeout=10)
            assert process.returncode == 0
            owners.append(dict(case=label, pid=process.pid, returncode=process.returncode,
                               qmp_quit=result, vm_signals=[], owner_absent=not Path('/proc/' + str(process.pid)).exists()))
            API['save'](short / 'owner.json', owners[-1])
        finally:
            if process.poll() is None and connection is not None:
                qmp('quit'); process.wait(timeout=10)
            if stream: stream.close()
            if connection: connection.close()
        raw = logpath.read_text()
        if enabled:
            assert 'P1_MMC_CREATED' in raw
        if label == 'id-read':
            assert raw.count('rc=0 value=0x1000') == 2
        if label == 'unknown':
            assert 'width=4 rc=2' in raw and 'width=4 rc=4' in raw
        if label == 'width':
            assert 'width=1 rc=1' in raw and 'width=4 rc=4' in raw
        if label == 'write':
            assert 'P1_MMC_WRITE address=0xf13b8000 width=4 rc=3' in raw and 'width=4 rc=4' in raw
        for name in ('test', 'qmp'):
            (short / name).unlink(missing_ok=True)
    API['save'](tmp_path / 'qtest-receipt.json', dict(scope='host QEMU bus only; no original kernel/modules',
        qemu=binary, owners=owners, original_module_init_verified=False, physical_compatibility=False))
