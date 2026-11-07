#!/usr/bin/env python3
"""Real callback fault tests and isolated two-owner persistent-flash migration."""
import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import runpy
import shlex
import struct
import subprocess
import time

HERE = Path(__file__).resolve().parent
HELPER = runpy.run_path(str(HERE/'flash-migration-qtest.py'))
Qemu, RAM, sha = HELPER['Qemu'], HELPER['RAM'], HELPER['sha']
REGS = (0x0c, 0x10, 0x18, 0x1c, 0x20, 0x24, 0x28, 0x2c, 0x30,
        0x34, 0x38, 0x3c, 0x40, 0x44, 0x48)


def synthetic(out, size=32*1024*1024):
    out.mkdir(parents=True, exist_ok=False)
    disk, geometry, wrong = (out/name for name in ('disk.raw', 'geometry.bin', 'wrong-geometry.bin'))
    capacity = size-8388608
    with disk.open('xb') as stream:
        stream.truncate(size)
        stream.seek(1048576)
        stream.write(hashlib.sha256(b'a7pf synthetic user area').digest()*16)
        for i in (0, 1):
            stream.seek(capacity+i*4194304+512)
            stream.write(hashlib.sha256(bytes([i])).digest()*16)
    rows = [(1, 65536, 131072), (7, 262144, 262144),
            (31, capacity, 4194304), (32, capacity+4194304, 4194304)]
    for path, shift in ((geometry, 0), (wrong, 512)):
        path.write_bytes(struct.pack('<8sIIQ', b'A7PFGE01', 1, len(rows), capacity)+
                         b''.join(struct.pack('<IIQQ', n, 0, off+(shift if n == 7 else 0), length)
                                  for n, off, length in rows))
        path.chmod(0o600)
    disk.chmod(0o600)
    return disk, geometry, wrong


def callbacks(out):
    disk, geometry, wrong = synthetic(out)
    other = out/'new-inode.raw'
    subprocess.run(['cp', '--reflink=auto', str(disk), str(other)], check=True)
    other.chmod(0o600)
    flags = subprocess.check_output(['pkg-config', '--cflags', '--libs', 'glib-2.0'], text=True).split()
    binary = out/'callback-test'
    command = ['cc', '-std=gnu11', '-O1', '-g', '-Wall', '-Wextra', '-Werror',
               '-fsanitize=address,undefined', '-fno-omit-frame-pointer', '-I'+str(HERE),
               str(HERE/'flash-migration-test.c'), '-Wl,--wrap=fdatasync', '-Wl,--wrap=pread',
               '-o', str(binary)] + flags
    compiled = subprocess.run(command, capture_output=True, text=True)
    (out/'compile.log').write_text(compiled.stdout+compiled.stderr)
    assert compiled.returncode == 0, compiled.stderr
    tested = subprocess.run([str(binary), str(disk), str(geometry), str(wrong), str(other)],
                            capture_output=True, text=True)
    (out/'callbacks.log').write_text(tested.stdout+tested.stderr)
    assert tested.returncode == 0, tested.stdout+tested.stderr
    assert 'callbacks=production disk_and_syscalls=real' in tested.stdout
    result = dict(status='passed', checks=int(tested.stdout.split('RESULT checks=')[1].split()[0]),
                  production_callbacks=True, real_files=True, asan_ubsan=True,
                  syscall_faults=['fdatasync ENOSPC', 'pread EACCES', 'short pread',
                                  'futimens during streamed pread'],
                  compile_command=command, model_sha256=sha(HERE/'flash-qemu.c'))
    (out/'result.json').write_text(json.dumps(result, indent=2)+'\n')
    return result


def test_real_callbacks(tmp_path):
    assert callbacks(tmp_path/'callbacks')['checks'] >= 40


def registers(qemu):
    return {hex(offset): qemu.reg(offset) for offset in REGS}


def prepare(qemu, phase):
    payload = hashlib.sha256(b'actual flash DMA retained RAM').digest()*32
    canary = hashlib.sha256(b'QEMU migrated RAM canary').digest()*32
    qemu.memory(RAM+4096, len(payload), payload)
    for offset, value in ((0x10, 7), (0x18, 5), (0x20, 2), (0x24, RAM+4096), (0x14, 3)):
        qemu.reg(offset, value)
    qemu.memory(RAM+4096, len(payload), bytes(len(payload)))
    qemu.reg(0x14, 2)
    assert qemu.memory(RAM+4096, len(payload)) == payload
    qemu.memory(RAM+8192, len(canary), canary)
    if phase == 'geometry':
        qemu.reg(0x10, 31)
        qemu.reg(0x14, 1)
        assert qemu.reg(0x38) == 8192 and qemu.reg(0x40) > 0
    if phase == 'failed':
        qemu.reg(0x14, 99)
        assert qemu.reg(0x2c) == 2 and qemu.reg(0x34) == 95
    else:
        assert qemu.reg(0x2c) == 1
    # Writable configuration need not describe the last completed command.
    for offset, value in ((0x10, 32), (0x18, 0x13579bdf), (0x1c, 3),
                          (0x20, 17), (0x24, RAM+4096), (0x28, 7)):
        qemu.reg(offset, value)
    return payload, canary


def save(qemu, path, success=True):
    qemu.qmpcommand('migrate', dict(uri='exec:cat > '+shlex.quote(str(path))))
    result = qemu.wait_migration()
    assert result['status'] == ('completed' if success else 'failed'), result
    return result


def held(fd, path):
    other = os.open(path, os.O_RDWR)
    try:
        try:
            fcntl.flock(other, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return True
        raise AssertionError('parent disk lease was not held')
    finally:
        os.close(other)


def roundtrip(binary, out, *, phase='done', mismatch=None, size=32*1024*1024):
    disk, geometry, wrong = synthetic(out, size)
    fd = os.open(disk, os.O_RDWR)
    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    source = target = None
    targetfd = None
    result = dict(phase=phase, mismatch=mismatch, container_bytes=size)
    try:
        source = Qemu(binary, fd, geometry, out, 'source')
        payload, canary = prepare(source, phase)
        expected = registers(source)
        before = sha(disk)
        state = out/'state.bin'
        result.update(source_registers=expected, source_migration=save(source, state),
                      disk_sha256_before=before)
        assert bytes.fromhex(before) in state.read_bytes()
        result['stream_contains_independent_full_disk_sha256'] = True
        destgeometry = geometry
        if mismatch == 'byte':
            last = os.fstat(fd).st_size-1
            os.pwrite(fd, bytes([os.pread(fd, 1, last)[0] ^ 1]), last)
        if mismatch == 'geometry':
            destgeometry = wrong
        if mismatch == 'inode':
            new = out/'new-inode.raw'
            subprocess.run(['cp', '--reflink=auto', str(disk), str(new)], check=True)
            new.chmod(0o600)
            targetfd = os.open(new, os.O_RDWR)
            fcntl.flock(targetfd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        target = Qemu(binary, targetfd if targetfd is not None else fd,
                      destgeometry, out, 'target', incoming=True)
        assert not target.qmpcommand('query-status')['running']
        result['target_initial_registers'] = registers(target)
        target.qmpcommand('migrate-set-capabilities',
                          dict(capabilities=[dict(capability='pause-before-switchover', state=False)]))
        try:
            target.qmpcommand('migrate-incoming', dict(uri='exec:cat '+shlex.quote(str(out/'state.bin'))))
            if mismatch:
                deadline = time.monotonic()+15
                while target.process.poll() is None and time.monotonic() < deadline:
                    try:
                        status = target.qmpcommand('query-status')
                        assert not status['running'], status
                    except (EOFError, ConnectionResetError):
                        break
                    time.sleep(.02)
                target.process.wait(timeout=10)
                assert target.process.returncode == 1
                result.update(destination_rejected=True, destination_cpu_resumed=False)
            else:
                deadline = time.monotonic()+30
                while time.monotonic() < deadline:
                    status = target.qmpcommand('query-status')
                    if status['status'] != 'inmigrate':
                        break
                    time.sleep(.02)
                assert not status['running'], status
                actual = registers(target)
                assert actual == expected, (actual, expected)
                assert target.memory(RAM+4096, len(payload)) == payload
                assert target.memory(RAM+8192, len(canary)) == canary
                assert sha(disk) == before
                result.update(target_registers=actual, exact_register_readback=True,
                              dma_ram_and_canary_verified=True, disk_unchanged=True)
        except (EOFError, ConnectionResetError):
            if not mismatch:
                raise
            target.process.wait(timeout=10)
            assert target.process.returncode == 1
            result.update(destination_rejected=True, destination_cpu_resumed=False)
        assert held(fd, disk)
    finally:
        owners = []
        for qemu in (source, target):
            if qemu is not None:
                owners.append(qemu.close())
        result['owners'] = owners
        assert held(fd, disk)
        result['parent_lease_held_through_both_owner_exits'] = True
        os.close(fd)
        if targetfd is not None:
            os.close(targetfd)
        (out/'result.json').write_text(json.dumps(result, indent=2)+'\n')
    assert len(owners) == 2
    assert owners[0]['returncode'] == 0 and 'quit_response' in owners[0]
    if not mismatch:
        assert owners[1]['returncode'] == 0 and 'quit_response' in owners[1]
    else:
        assert owners[1]['returncode'] == 1
        assert 'sony-persistent-flash' in (out/'target.log').read_text()
    return result


def default_refusal(binary, out):
    disk, geometry, _ = synthetic(out)
    fd = os.open(disk, os.O_RDWR)
    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    qemu = None
    try:
        qemu = Qemu(binary, fd, geometry, out, 'default', retained=False)
        prepare(qemu, 'failed')
        before = registers(qemu)
        qemu.qmpcommand('cont')
        assert qemu.qmpcommand('query-status')['running']
        migration = save(qemu, out/'refused.bin', success=False)
        assert migration.get('error-desc')
        assert qemu.qmpcommand('query-status')['running']
        assert registers(qemu) == before
        result = dict(default_false_actual_qmp_rejected=True, migration=migration,
                      source_still_running=True, registers_unchanged=True)
    finally:
        if qemu is not None:
            owner = qemu.close()
            assert owner['returncode'] == 0
        assert held(fd, disk)
        os.close(fd)
    (out/'result.json').write_text(json.dumps(result, indent=2)+'\n')
    return result


def invalid_backend(binary, out, kind):
    disk, geometry, _ = synthetic(out)
    fd = os.open(disk, os.O_RDWR)
    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    candidate = fd
    try:
        if kind == 'readonly':
            candidate = os.open(disk, os.O_RDONLY)
        elif kind == 'short':
            os.ftruncate(fd, os.fstat(fd).st_size-512)
        else:
            raise ValueError(kind)
        try:
            qemu = Qemu(binary, candidate, geometry, out, 'rejected', incoming=True)
        except (RuntimeError, EOFError, ValueError, BrokenPipeError, ConnectionResetError):
            owner = json.loads((out/'rejected-owner.json').read_text())
            assert owner['returncode'] == 1 and not owner['signals_sent']
            assert 'persistent flash backend/geometry rejected' in (out/'rejected.log').read_text()
        else:
            qemu.close()
            raise AssertionError('Invalid backend was realized')
        assert held(fd, disk)
        result = dict(kind=kind, rejected_at_realize=True, destination_cpu_resumed=False,
                      owner=owner, parent_lease_held_through_owner_exit=True)
    finally:
        if candidate != fd:
            os.close(candidate)
        os.close(fd)
    (out/'result.json').write_text(json.dumps(result, indent=2)+'\n')
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--qemu', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=False)
    result = dict(schema='a7c2.flash-migration.validation.v1', status='started',
                  scope='synthetic virt board; flash and upstream devices only',
                  original_ap_verified=False, sony_wbi_verified=False,
                  hardware_ram_hotboot_verified=False, capture_verified=False,
                  external_retained_transaction_integrated=False, hot_api_allowed=False,
                  model_sha256=sha(HERE/'flash-qemu.c'))
    try:
        result['callbacks'] = callbacks(out/'callbacks')
        if args.qemu:
            binary = args.qemu.resolve(strict=True)
            result['qemu_binary_sha256'] = sha(binary)
            result['default_refusal'] = default_refusal(binary, out/'default')
            result['positive'] = [roundtrip(binary, out/phase, phase=phase,
                                           size=(64 if phase == 'geometry' else 32)*1024*1024)
                                  for phase in ('done', 'failed', 'geometry')]
            result['negative'] = [roundtrip(binary, out/('wrong-'+kind), mismatch=kind)
                                  for kind in ('byte', 'inode', 'geometry')]
            result['invalid_backend'] = [invalid_backend(binary, out/('invalid-'+kind), kind)
                                         for kind in ('readonly', 'short')]
        result['status'] = 'passed'
    except BaseException as exc:
        result.update(status='failed', error=repr(exc))
        raise
    finally:
        (out/'result.json').write_text(json.dumps(result, indent=2)+'\n')
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
