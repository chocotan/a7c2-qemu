#!/usr/bin/env python3
"""Host tests for the isolated p1 read-only probe; actual CLI lives in its API."""
from contextlib import contextmanager
import ctypes
import hashlib
import json
import os
from pathlib import Path
import runpy
import stat
import subprocess

import pytest

HERE = Path(__file__).resolve().parent
API = runpy.run_path(str(HERE / 'p1-module-probe.py'))


def manifest():
    nodes = ['pnflasha'] + ['cnflasha' + str(n) for n in API['GEOMETRY']['PARTS']] + ['nflashaB0', 'nflashaB1']
    return dict(schema=API['PROFILE'], status='built', capacities={n: 8192 + i for i, n in enumerate(nodes)},
        samples=[dict(node=n, sector=s, bytes=512, sha256=hashlib.sha256((n + str(s)).encode()).hexdigest())
                 for n in nodes for s in (0, 137)],
        files=[dict(id=i, fs=f, node=n, path=p, bytes=19, sha256='a' * 64)
            for i, f, n, p in [('p7', 'ext2', 'cnflasha7', '/sbin/init2'),
                               ('p11', 'vfat', 'cnflasha11', '/AccessLog.dat')]])


def serial(m):
    rows = ['P1_PROBE_BEGIN', 'P1_CREDENTIAL kind=Uid: values=0,0,0,0',
        'P1_CREDENTIAL kind=Gid: values=0,0,0,0', 'P1_RELEASE value=4.9.186-scel',
        'P1_INSMOD rc=0', 'P1_MODULES_BEGIN', 'sony_persistent_flash 16384 0 - Live 0xffffff8000100000',
        'P1_MODULES_END']
    rows += [f'P1_CAPACITY node={n} expected={s} actual={s}' for n, s in m['capacities'].items()]
    rows += [f'P1_READ node={r["node"]} sector={r["sector"]} bytes=512 sha256={r["sha256"]}' for r in m['samples']]
    for r in m['files']:
        rows += [f'P1_MOUNT id={r["id"]} fs={r["fs"]} node={r["node"]} rc=0',
            f'P1_MOUNTINFO_BEGIN id={r["id"]}',
            f'16 11 250:7 / /mnt/{r["id"]} ro,relatime - {r["fs"]} /dev/{r["node"]} ro',
            f'P1_MOUNTINFO_END id={r["id"]}',
            f'P1_FILE id={r["id"]} bytes={r["bytes"]} sha256={r["sha256"]}',
            f'P1_UNMOUNT id={r["id"]} rc=0']
    rows += ['P1_PROBE_COMPLETE']
    return ('\n'.join(rows) + '\n').encode()


def test_module_generations_are_explicit_and_unknown_hash_rejected():
    assert API['MODULE_SHA'] == '5d069cd2c2eb5fbbd9d933e4768a65b0b71e3505fadcf245d5541a2e99a74383'
    assert API['module_generation'](API['MODULE_SHA']) == 'v5-blk-queue-split'
    assert API['module_generation'](API['LEGACY_MODULE_SHA']) == 'v4-readonly-large-write-bug'
    with pytest.raises(ValueError, match='Unknown'):
        API['module_generation']('a' * 64)


def test_guest_script_ascii_readonly_and_shell_syntax():
    script = HERE / 'guest/p1-module-probe-init'
    text = script.read_bytes().decode('ascii')
    subprocess.run(['sh', '-n', str(script)], check=True)
    assert 'mount -t "$fs" -o ro' in text
    assert 'of=/tmp/block' in text
    assert not any(token in text for token in ('insmod -f', 'of=/dev/', ' -o rw ', 'UdtrMain', 'update_boot'))
    assert 'P1_CREDENTIAL kind=$key values=$a,$b,$c,$d' in text
    assert 'cat /proc/modules' in text


def test_command_line_references_original_p1_and_explicit_adaptations():
    original = 'kemco\ninit=/sbin/init\nconsole=ttynull initrd=0x408000000,0x2000000\nmem=4G\nwdt.mode=0\n*\n'
    command = API['command_line'](original)
    assert 'init=/p1-probe' in command and 'rdinit=/p1-probe' in command
    assert 'console=ttyAMA0' in command and 'wdt.mode=0' in command and 'mem=4G' in command
    assert 'ttynull' not in command and 'initrd=' not in command and 'kemco' not in command
    assert '__boottime_sony_usb_init' in command
    assert '__boottime___udif_init_udif_hwtimer' not in command
    with pytest.raises(ValueError):
        API['command_line']('initcall_blacklist=arbitrary')


def test_evidence_accepts_actual_scope_only():
    m = manifest(); result = API['collect'](serial(m).replace(b'\n', b'\r\n'), m)
    assert result['guest_read_path_verified']
    assert result['capacity_rows'] == 20 and result['sample_rows'] == 40
    assert result['root_verified'] and result['module_loaded']
    assert all(all(v.values()) for v in result['mounts'].values())
    assert result['full_block_abi_verified'] is False and result['updater_executed'] is False


@pytest.mark.parametrize('failure', ['credentials', 'module', 'capacity', 'sample', 'duplicate', 'mount-rw',
    'superblock-rw', 'unmount', 'incomplete', 'panic', 'guest-error', 'missing-status'])
def test_evidence_fails_closed(failure):
    m = manifest(); raw = serial(m)
    if failure == 'credentials': raw = raw.replace(b'0,0,0,0', b'0,1,0,0', 1)
    elif failure == 'module': raw = raw.replace(b'P1_INSMOD rc=0', b'P1_INSMOD rc=1')
    elif failure == 'capacity': raw = raw.replace(b'expected=8192 actual=8192', b'expected=8192 actual=8191')
    elif failure == 'sample': raw = raw.replace(m['samples'][0]['sha256'].encode(), b'b' * 64)
    elif failure == 'duplicate': raw += b'P1_PROBE_COMPLETE\n'
    elif failure == 'mount-rw': raw = raw.replace(b'/mnt/p7 ro,', b'/mnt/p7 rw,')
    elif failure == 'superblock-rw': raw = raw.replace(b'/dev/cnflasha7 ro', b'/dev/cnflasha7 rw')
    elif failure == 'unmount': raw = raw.replace(b'P1_UNMOUNT id=p7 rc=0', b'P1_UNMOUNT id=p7 rc=1')
    elif failure == 'incomplete': raw = raw.replace(b'P1_PROBE_COMPLETE\n', b'')
    elif failure == 'panic': raw += b'Kernel panic - not syncing\n'
    elif failure == 'missing-status': raw = raw.replace(b'P1_CREDENTIAL kind=Gid: values=0,0,0,0\n', b'')
    else: raw += b'P1_FAIL stage=insmod rc=8\n'
    result = API['collect'](raw, m)
    assert not result['guest_read_path_verified']
    if failure == 'guest-error': assert result['first_guest_error'] == dict(stage='insmod', rc='8')


def test_launcher_only_inherits_declared_fd(tmp_path):
    m = manifest(); m.update(output=str(tmp_path), qemu=dict(path=str(tmp_path / 'qemu-system-aarch64')))
    disk = tmp_path / 'camera.emmc'; disk.write_bytes(b'data')
    with disk.open('r+b') as f:
        command = API['launch_command'](m, f.fileno(), tmp_path)
    text = ' '.join(command)
    assert 'QEMU_A7PF_PROFILE persistent-flash-cold-v1' in text
    assert 'cntfrq=2000000' in text and 'gic-version=2' in text
    assert '-m 24576' in text and 'loader,addr=0x400010000,cpu-num=0' in text
    assert '/instance/persistent-geometry.bin' in text
    assert str(disk) not in text
    assert '-kernel' not in command and '-initrd' not in command
    assert not any(x in text for x in ('/dev/sd', '/dev/mmc', 'die-with-parent', 'timeout', 'signal'))


def test_real_dtb_resources(tmp_path):
    runtime = HERE.parents[1] / 'runtime'
    libpath = (runtime / 'sources/qemu-tools/usr/lib/libfdt.so.1').resolve()
    out = tmp_path / 'virt.dtb'
    API['board'](runtime / 'analysis/qemu-virt-board/virt-packed.dtb', libpath, out, 'init=/p1-probe', 12345)
    lib = ctypes.CDLL(str(libpath)); lib.fdt_getprop.restype = ctypes.c_void_p
    buf = ctypes.create_string_buffer(out.read_bytes())
    def get(path, name):
        node = lib.fdt_path_offset(buf, path.encode()); length = ctypes.c_int()
        p = lib.fdt_getprop(buf, node, name.encode(), ctypes.byref(length))
        assert p
        return ctypes.string_at(p, length.value)
    assert get('/chosen', 'bootargs') == b'init=/p1-probe\0'
    assert int.from_bytes(get('/chosen', 'linux,initrd-start'), 'big') == 0x440000000
    assert int.from_bytes(get('/chosen', 'linux,initrd-end'), 'big') == 0x440000000 + 12345
    memory = get('/memory@40000000', 'reg')
    assert int.from_bytes(memory[:8], 'big') == 0x400000000
    assert int.from_bytes(memory[8:], 'big') == 0x200000000
    assert get('/persistent-flash@b000000', 'reg') == (0x0b000000).to_bytes(8, 'big') + (4096).to_bytes(8, 'big')


def test_checked_identity_rejects_same_size_mutation(tmp_path):
    source = tmp_path / 'module'; source.write_bytes(b'original')
    row = API['binding'](source); source.write_bytes(b'changed!')
    with pytest.raises(ValueError, match='Input identity differs'):
        API['checked'](row)


def test_receipts_are_private(tmp_path):
    path = tmp_path / 'private.json'; API['save'](path, dict(raw='private'))
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_actual_passes_fd_holds_lease_and_hashes_after_owner_exit(tmp_path, monkeypatch):
    m = manifest(); raw = serial(m)
    instance = tmp_path / 'instance'; instance.mkdir()
    disk = instance / 'camera.emmc'; disk.write_bytes(b'stable private disk')
    m.update(instance=str(instance), output=str(tmp_path / 'build'), inputs=[], artifacts=[],
        disk_sha256=hashlib.sha256(disk.read_bytes()).hexdigest(), state={}, geometry={})
    flags = dict(leased=False, exited=False)
    @contextmanager
    def lease(path):
        assert path == str(instance)
        flags['leased'] = True
        with disk.open('r+b') as f:
            yield dict(fd=f.fileno())
        assert flags['exited']
        flags['leased'] = False
    class Child:
        pid = 123
        returncode = None
        def poll(self): return self.returncode
        def wait(self, timeout=None):
            assert flags['leased']
            flags['exited'] = True; self.returncode = 0
            return 0
    def popen(argv, **kwargs):
        assert flags['leased'] and os.pread(kwargs['pass_fds'][0], 7, 0) == b'stable '
        kwargs['stdout'].write(raw); kwargs['stdout'].flush()
        return Child()
    class Close:
        def close(self): pass
    def qmp(name, args=None):
        assert flags['leased']
        return {'return': {}}
    original_hash = API['DISK']['hashed']
    calls = []
    def hashed(fd):
        calls.append(flags['exited'])
        return original_hash(fd)
    monkeypatch.setitem(API['DISK'], 'lease', lease)
    monkeypatch.setitem(API['DISK'], 'hashed', hashed)
    monkeypatch.setitem(API, 'checked', lambda row: row)
    monkeypatch.setitem(API['actual'].__globals__, 'checked', lambda row: row)
    monkeypatch.setitem(API['actual'].__globals__, 'launch_command', lambda *args: ['fixture'])
    monkeypatch.setitem(API['OWNER'], 'qmp_connect', lambda path: (Close(), Close(), qmp))
    monkeypatch.setattr(subprocess, 'Popen', popen)
    result = API['actual'](m, tmp_path / 'evidence')
    assert result['verified'] and result['normal_exit_verified'] and result['disk_unchanged']
    assert result['lease_released_after_owner_exit'] and not flags['leased']
    assert calls == [False, True]
    assert stat.S_IMODE((tmp_path / 'evidence/serial.log').stat().st_mode) == 0o600
