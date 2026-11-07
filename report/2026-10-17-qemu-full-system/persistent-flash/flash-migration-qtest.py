#!/usr/bin/env python3
"""Fixture-only flash migration board and QMP/qtest owner; never a boot profile."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import runpy
import socket
import subprocess
import tempfile
import time

HERE = Path(__file__).resolve().parent
BASE, RAM = 0x0b000000, 0x40000000


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(131072), b''):
            h.update(chunk)
    return h.hexdigest()


def build(template, stage):
    template, stage = Path(template).resolve(strict=True), Path(stage).resolve()
    if (stage == Path('/') or stage.is_relative_to(HERE.parents[2]) or
            stage.is_relative_to(template) or template.is_relative_to(stage)):
        raise ValueError('Separate scratch source/build required')
    stage.mkdir(parents=True, exist_ok=True)
    api = runpy.run_path(str(HERE/'build.py'))
    before = {name: api['tree_files'](template/name) for name in ('qemu-11.1.2', 'build')}
    for name in before:
        if (stage/name).exists() or (stage/name).is_symlink():
            raise ValueError('Fresh isolated QEMU source/build required')
    for name in before:
        api['run'](['cp', '-a', '--reflink=auto', template/name, stage/name])
    installer = runpy.run_path(str(HERE.parent/'persistent-flash-model.py'))
    installer['patch'](stage/'qemu-11.1.2', stage)
    board = stage/'qemu-11.1.2/hw/arm/virt.c'
    text = board.read_text().replace(installer['INCLUDE'], '')
    anchor = 'static void machvirt_init(MachineState *machine)\n{'
    include = '#include "qemu/osdep.h"\n'
    if text.count(anchor) != 1 or text.count(include) != 1:
        raise ValueError('Unknown virt fixture source')
    fixture = '''
    /* Test-only: all other properties are explicit -global qdev options. */
    if (!machine->dtb) {
        error_report("flash migration fixture requires -dtb geometry"); exit(1);
    }
    DeviceState *pf = qdev_new("sony-persistent-flash");
    qdev_prop_set_string(pf, "geometry", machine->dtb);
    sysbus_realize_and_unref(SYS_BUS_DEVICE(pf), &error_fatal);
    sysbus_mmio_map(SYS_BUS_DEVICE(pf), 0, 0x0b000000);
    machine->dtb = NULL;
'''
    text = text.replace(include, include + installer['INCLUDE']).replace(anchor, anchor + fixture)
    board.write_text(text)
    ninja = (stage/'build/build.ninja').read_text().replace(str(template), str(stage))
    for original in set(re.findall(r'/[^\s\'\"]+/qemu-11\.1\.2(?=/|\s|$)', ninja)):
        ninja = ninja.replace(original, str(stage/'qemu-11.1.2'))
    lines = ninja.splitlines(True)
    header = ''.join(lines[:next(i for i, line in enumerate(lines) if line.startswith('build '))])

    def block(target):
        hits = [i for i, line in enumerate(lines) if line.startswith('build ' + target + ':')]
        if len(hits) != 1:
            raise ValueError('Unknown frozen build target ' + target)
        begin, end = hits[0], hits[0] + 1
        while end < len(lines) and (lines[end].startswith(' ') or not lines[end].strip()):
            end += 1
        return ''.join(lines[begin:end])

    frozen = stage/'build/flash-migration.ninja'
    frozen.write_text(header + '\n' + block('libsystem_arm.a.p/hw_arm_virt.c.o') + '\n' +
                      block('qemu-system-aarch64'))
    command = ['bwrap', '--unshare-all', '--die-with-parent', '--ro-bind', '/', '/',
               '--dev-bind', '/dev', '/dev', '--proc', '/proc', '--tmpfs', '/tmp',
               '--bind', str(stage), str(stage), '--chdir', str(stage/'build'),
               'ninja', '-f', frozen.name, '-j2', 'qemu-system-aarch64']
    result = dict(schema='a7c2.flash-migration.fixture-build.v1', status='started',
                  fixture_only=True, production_profile_changed=False,
                  model_sha256=sha(HERE/'flash-qemu.c'))
    try:
        api['run'](command, stage/'build')
        result.update(status='compiled', binary=str(stage/'build/qemu-system-aarch64'),
                      qemu_binary_sha256=sha(stage/'build/qemu-system-aarch64'),
                      board_sha256=sha(board), frozen_ninja_sha256=sha(frozen))
    finally:
        result['original_source_and_build_unchanged'] = all(
            api['tree_files'](template/name) == files for name, files in before.items())
        result['template_tree_sha256'] = {n: api['tree_digest'](v) for n, v in before.items()}
        (stage/'migration-build.json').write_text(json.dumps(result, indent=2) + '\n')
    if not result['original_source_and_build_unchanged']:
        raise ValueError('Original source/build changed')
    return result


class Qemu:
    def __init__(self, binary, fd, geometry, out, label, *, retained=True, incoming=False):
        self.out, self.label, self.events, self.transcript = out, label, [], []
        self.temp = tempfile.TemporaryDirectory(prefix='a7pf-mig-')
        short = Path(self.temp.name)
        self.log = (out/(label+'.log')).open('x')
        loop = out/'loop.bin'
        if not loop.exists():
            loop.write_bytes(bytes.fromhex('00000014'))  # AArch64 B .
        st = os.fstat(fd)
        command = [str(binary), '-machine', 'virt,gic-version=2', '-cpu', 'cortex-a53',
                   '-accel', 'tcg', '-m', '64M', '-nodefaults', '-display', 'none',
                   '-nic', 'none', '-S', '-kernel', str(loop), '-dtb', str(geometry),
                   '-qtest', 'unix:'+str(short/'test')+',server=on,wait=off',
                   '-qmp', 'unix:'+str(short/'qmp')+',server=on,wait=off']
        for key, value in [('backend-fd', fd), ('expected-dev', st.st_dev),
                           ('expected-ino', st.st_ino)]:
            command += ['-global', f'sony-persistent-flash.{key}={value}']
        if retained:
            command += ['-global', 'sony-persistent-flash.retained-state=on']
        if incoming:
            command += ['-incoming', 'defer']
        env = {k: v for k, v in os.environ.items() if not k.startswith(('QEMU_', 'MENU_', 'SONY_'))}
        self.process = subprocess.Popen(command, pass_fds=(fd,), stdout=self.log,
                                        stderr=subprocess.STDOUT, env=env)
        self.owner = dict(pid=self.process.pid, command=command, signals_sent=[],
                          fd_identity=dict(dev=st.st_dev, ino=st.st_ino, bytes=st.st_size))
        self.qmp = self.qmpfile = self.socket = self.file = None
        try:
            self.qmp = self.connect(short/'qmp')
            self.qmpfile = self.qmp.makefile('rwb', buffering=0)
            assert 'QMP' in json.loads(self.qmpfile.readline())
            self.qmpcommand('qmp_capabilities')
            self.socket = self.connect(short/'test')
            self.file = self.socket.makefile('rwb', buffering=0)
        except BaseException:
            if self.process.poll() is None and self.qmpfile is not None:
                try:
                    self.owner['quit_response'] = self.qmpcommand('quit')
                except (EOFError, BrokenPipeError, ConnectionResetError):
                    pass
            self.process.wait(timeout=15)
            self.owner['returncode'] = self.process.returncode
            (out/(label+'-owner.json')).write_text(json.dumps(self.owner, indent=2)+'\n')
            for stream in (self.file, self.socket, self.qmpfile, self.qmp, self.log):
                if stream is not None:
                    stream.close()
            self.temp.cleanup()
            raise
        (out/(label+'-owner.json')).write_text(json.dumps(self.owner, indent=2)+'\n')

    def connect(self, path):
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            sock.settimeout(10)
            try:
                sock.connect(str(path))
                return sock
            except (FileNotFoundError, ConnectionRefusedError):
                sock.close()
                if self.process.poll() is not None:
                    self.log.flush()
                    raise RuntimeError('QEMU exited '+str(self.process.returncode)+': '+self.label)
                time.sleep(.02)
        raise TimeoutError('QEMU socket not ready')

    def qmpcommand(self, name, arguments=None):
        request = dict(execute=name)
        if arguments is not None:
            request['arguments'] = arguments
        self.qmpfile.write((json.dumps(request)+'\n').encode())
        while True:
            raw = self.qmpfile.readline()
            if not raw:
                raise EOFError('QMP disconnected: '+self.label)
            response = json.loads(raw)
            if 'event' in response:
                self.events.append(response)
                continue
            self.transcript.append(dict(request=request, response=response))
            if 'error' in response:
                raise RuntimeError(response)
            return response['return']

    def cmd(self, command):
        self.file.write((command+'\n').encode())
        while True:
            response = self.file.readline().decode().strip()
            if response.startswith('IRQ '):
                continue
            assert response.startswith('OK'), (command, response)
            self.transcript.append(dict(qtest=command, response=response))
            return response[2:].strip()

    def reg(self, offset, value=None):
        if value is None:
            return int(self.cmd(f'readl {BASE+offset:#x}'), 0)
        self.cmd(f'writel {BASE+offset:#x} {value:#x}')

    def memory(self, address, size, data=None):
        if data is not None:
            assert len(data) == size
            self.cmd(f'write {address:#x} {size:#x} 0x'+data.hex())
            return None
        return bytes.fromhex(self.cmd(f'read {address:#x} {size:#x}')[2:])

    def wait_migration(self):
        deadline = time.monotonic()+30
        while time.monotonic() < deadline:
            status = self.qmpcommand('query-migrate')
            if status.get('status') in ('completed', 'failed', 'cancelled'):
                return status
            time.sleep(.02)
        raise TimeoutError('Migration did not reach a terminal state')

    def close(self):
        if self.process.poll() is None:
            try:
                self.owner['quit_response'] = self.qmpcommand('quit')
            except (EOFError, BrokenPipeError, ConnectionResetError):
                # Failed incoming migration can exit itself before servicing quit.
                pass
        self.process.wait(timeout=15)
        self.owner.update(returncode=self.process.returncode, events=self.events)
        for stream in (self.file, self.socket, self.qmpfile, self.qmp, self.log):
            stream.close()
        self.temp.cleanup()
        (self.out/(self.label+'-owner.json')).write_text(json.dumps(self.owner, indent=2)+'\n')
        (self.out/(self.label+'-transcript.json')).write_text(json.dumps(self.transcript, indent=2)+'\n')
        assert self.process.returncode >= 0, 'QEMU exited by signal'
        return self.owner


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--template', required=True, type=Path)
    parser.add_argument('--stage', required=True, type=Path)
    args = parser.parse_args()
    print(json.dumps(build(args.template, args.stage), indent=2))
