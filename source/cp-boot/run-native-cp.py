#!/usr/bin/env python3
"""Run only the original CP in an admitted native AP/CP pair (Linux, local files only)."""
import argparse
from contextlib import contextmanager
from functools import lru_cache
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import resource
import runpy
import select
import stat
import struct
import subprocess
import sys
import time
import traceback
from types import ModuleType, SimpleNamespace

HERE = Path(__file__).absolute().parent
PRODUCT = HERE.parent.parent
MIB, GIB = 1024 ** 2, 1024 ** 3
CP_SIZE = 0x1140b80
QEMU_RSP_PACKET_LIMIT = 131104  # QEMU 11.1.2 gdbstub/internals.h MAX_PACKET_LENGTH
# The full identity, not an instruction scan, selects this CP revision.
CP_SHA = 'f5a477588698ef965748903b8959a39ce4f59ffd4aee4d4234ef1670f56a1428'
TOMCO_SIZE = 741
TOMCO_SHA = '02b202a9b4fbf7bdcbe93d032bfe475a21859019a3c02d1766ac133a779650d3'
CP_ADDRESS, TOMCO_ADDRESS, BACKUP_ADDRESS = 0x108000, 0x100000, 0x04000000
CP_RAM_SIZE = 128 * MIB
ABORT, RECEIVER = 0x128190, 0x4b3a7c
BREAKPOINTS = {ABORT: 4, RECEIVER: 2}
PROFILE = 'virtual-native-ap-cp-link-v1'
CLAIM = 'cp-admission.claim'
READ_FLAGS = os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW | os.O_NONBLOCK
DIR_FLAGS = os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW | os.O_DIRECTORY
NEW_FLAGS = os.O_RDWR | os.O_CLOEXEC | os.O_NOFOLLOW | os.O_CREAT | os.O_EXCL
RETAINED = []  # Live owners/clients stay reachable for an importing coordinator.


def require(ok, message):
    if not ok:
        raise ValueError(message)


def checked_rsp_packet_size(supported):
    values = [int(field.split(b'=', 1)[1], 16) for field in supported.split(b';')
              if field.startswith(b'PacketSize=')]
    require(len(values) == 1 and 128 <= values[0] <= 1024 * 1024,
            'Missing/invalid RSP PacketSize')
    return min(values[0], QEMU_RSP_PACKET_LIMIT)


def canonical(path):
    raw = os.fspath(path)
    require(isinstance(raw, str) and raw.startswith('/') and '\0' not in raw
            and raw == os.path.normpath(raw) and not raw.startswith('//'),
            'An already canonical absolute path is required: ' + repr(raw))
    require(not any(raw == prefix or raw.startswith(prefix + '/')
                    for prefix in ('/dev', '/proc', '/sys', '/tmp')),
            'Physical/device/proc/sys and host /tmp paths are forbidden')
    return Path(raw)


@contextmanager
def directory(path):
    path = canonical(path)
    fd = os.open('/', DIR_FLAGS)
    try:
        for part in path.parts[1:]:
            next_fd = os.open(part, DIR_FLAGS, dir_fd=fd)
            os.close(fd)
            fd = next_fd
        yield fd
    finally:
        os.close(fd)


def identity(info):
    return {key: getattr(info, 'st_' + key) for key in
            ('dev', 'ino', 'mode', 'uid', 'nlink', 'size', 'mtime_ns', 'ctime_ns')}


def regular(info):
    require(stat.S_ISREG(info.st_mode) and info.st_uid == os.geteuid()
            and info.st_nlink == 1 and not info.st_mode & 0o022,
            'Input must be an owned single-link regular file without other writers')
    return identity(info)


def input_record(path, size=None, sha256=None, *, keep=False, maximum=256 * MIB):
    """Open read-only/no-follow and bind the complete SHA to both inode and pathname."""
    path = canonical(path)
    with directory(path.parent) as parent:
        before = regular(os.stat(path.name, dir_fd=parent, follow_symlinks=False))
        require(0 < before['size'] <= maximum and (size is None or before['size'] == size),
                'Input length differs or exceeds its hard limit: ' + str(path))
        fd = os.open(path.name, READ_FLAGS, dir_fd=parent)
        try:
            require(regular(os.fstat(fd)) == before, 'Input replaced while opening: ' + str(path))
            digest, chunks, offset = hashlib.sha256(), [], 0
            while offset < before['size']:
                data = os.pread(fd, min(MIB, before['size'] - offset), offset)
                require(data, 'Short input read: ' + str(path))
                offset += len(data)
                digest.update(data)
                if keep:
                    chunks.append(data)
            require(not os.pread(fd, 1, offset) and regular(os.fstat(fd)) == before
                    == regular(os.stat(path.name, dir_fd=parent, follow_symlinks=False)),
                    'Input changed during complete SHA256: ' + str(path))
            actual = digest.hexdigest()
            require(sha256 is None or actual == sha256,
                    f'Input SHA256 differs: {path}; expected={sha256} actual={actual}')
            return dict(path=str(path), sha256=actual, **before), b''.join(chunks) if keep else None
        finally:
            os.close(fd)


def stack_descriptors(data):
    require(len(data) == CP_SIZE, 'CP length differs before stack descriptor validation')
    result = []
    for core in range(4):
        entries = []
        for offset in range(4, 0x4c, 12):
            at = 0x20000 + core * 0x48 + offset
            start, size, sp = struct.unpack_from('<3I', data, at)
            require(CP_ADDRESS <= start < sp <= 0x2000000 and sp == start + size,
                    f'Original CP stack descriptor differs: core={core} offset={offset:#x}')
            entries.append(dict(offset=at, start=start, bytes=size, sp=sp))
        result.append(dict(core=core, entries=entries))
    return result


@lru_cache(maxsize=1)
def products():
    return (SimpleNamespace(**runpy.run_path(str(HERE / 'native-link.py'))),
            SimpleNamespace(**runpy.run_path(str(HERE / 'official-backup.py'))))


def limits(seconds):
    require(type(seconds) is int and 1 <= seconds <= 3600, 'seconds must be in 1..3600')
    cpu = max(250, 4 * (seconds + 60))
    file_size = max(512 * MIB, (seconds + 60) * 2 * MIB)
    return dict(cpu_soft=cpu, cpu_hard=cpu + 10, address_space=16 * GIB,
                file_size=file_size, log_budget=7 * file_size + 64 * MIB, reserve=64 * GIB)


def child_limits(budget):
    os.umask(0o077)
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    resource.setrlimit(resource.RLIMIT_CPU, (budget['cpu_soft'], budget['cpu_hard']))
    resource.setrlimit(resource.RLIMIT_AS, (budget['address_space'], budget['address_space']))
    resource.setrlimit(resource.RLIMIT_FSIZE, (budget['file_size'], budget['file_size']))


def environment(link, pair, inherited):
    require(all(isinstance(key, str) and isinstance(value, str) for key, value in inherited.items()),
            'Environment must map strings to strings')
    prefixes = ('QEMU_CP_', 'QEMU_SONY_', 'QEMU_AP_CP_', 'QEMU_NATIVE_',
                'SONY_', 'AP_CP_', 'NATIVE_')
    env = {key: value for key, value in inherited.items() if not key.startswith(prefixes)}
    delta = link.environment('cp', pair)
    required = dict(QEMU_NATIVE_AP_CP_LINK=PROFILE, QEMU_NATIVE_LINK_DIR=str(pair),
                    QEMU_AP_CP_GPIO_LINES='virtual-ap-cp-gpio-lines-v1', QEMU_AP_CP_GPIO_SIDE='cp',
                    QEMU_CP_BOOT_PERIPHERALS='virtual-cp-boot-peripherals-v1',
                    QEMU_CP_KEY_GPIO_PROFILE='virtual-cp-key-gpio-v1',
                    **{'QEMU_CP_' + name: '1' for name in ('GIC', 'TIMERS', 'WATCHDOG', 'EDMA_GATE', 'UIPC_RAM')})
    require(delta == required, 'Native CP environment/profile contract differs')
    env.update(delta)
    env['QEMU_CP_HYPOTHESIS_SEC_TIMER30'] = '1'
    for key, value in env.items():
        require(isinstance(key, str) and isinstance(value, str), 'Environment must map strings to strings')
        conflict = key.startswith(('QEMU_RAM_', 'QEMU_WBI_', 'QEMU_SD_', 'QEMU_INCOMING',
                                  'QEMU_MIGRAT', 'QEMU_LOADVM', 'QEMU_HOST_SD', 'QEMU_DIRECTORY_SD',
                                  'A7C2_HOST_SD', 'A7C2_DIRECTORY_SD', 'QEMU_ORIGINAL_RAM', 'A7C2_ORIGINAL_RAM'))
        conflict |= key in ('QEMU_USB_DEVICE', 'MENU_CP_EMULATION', 'A7C2_CP_EMULATION',
                            'QEMU_PLUGIN', 'LD_PRELOAD', 'LD_AUDIT')
        conflict |= any(word in key for word in ('VIRTUAL_CP', 'CP_SENDER', 'VPANEL',
                                                 'TRANSPORT_ERROR', 'BB_READY_INJECT', 'BB_READY_LATE'))
        require(not conflict or value in ('', '0'), 'Conflicting inherited profile/input: ' + key)
        require('transport-errors' not in value, 'Transport error injection conflicts: ' + key)
        require(not (key.startswith('QEMU_') and ('TEST' in key or 'DIRECT_DMA' in key)),
                'Test peer/direct DMA environment conflicts: ' + key)
    return env


def owned_socket(path):
    path = canonical(path)
    with directory(path.parent) as parent:
        info = os.stat(path.name, dir_fd=parent, follow_symlinks=False)
    require(stat.S_ISSOCK(info.st_mode) and info.st_uid == os.geteuid()
            and not info.st_mode & 0o022, 'Expected an owned Unix socket without other writers: ' + str(path))
    return dict(path=str(path), dev=info.st_dev, ino=info.st_ino, uid=info.st_uid)


def new_file(path, raw=b''):
    with directory(path.parent) as parent:
        fd = os.open(path.name, NEW_FLAGS, 0o600, dir_fd=parent)
        try:
            os.fchmod(fd, 0o600)
            offset = 0
            while offset < len(raw):
                amount = os.write(fd, raw[offset:])
                require(amount > 0, 'Output write made no progress')
                offset += amount
            os.fsync(fd)
            require(os.pread(fd, len(raw) + 1, 0) == raw, 'Output byte-for-byte readback differs')
            os.fsync(parent)
            return fd
        except BaseException:
            os.close(fd)
            raise


def write_json(path, value):
    raw = (json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + '\n').encode('utf-8')
    fd = new_file(path, raw)
    os.close(fd)


def storage_budget(pair, output, manifest, budget):
    """Reserve worst-case RAM growth and all seven raw log files, grouped by filesystem."""
    groups = {}
    for name, record in manifest['files'].items():
        info = (pair / name).lstat()
        group = groups.setdefault(info.st_dev, dict(path=str(pair), peak_bytes=0))
        group['peak_bytes'] += max(0, record['size'] - info.st_blocks * 512)
    info = output.lstat()
    groups.setdefault(info.st_dev, dict(path=str(output), peak_bytes=0))['peak_bytes'] += budget['log_budget'] + 2 * MIB
    for group in groups.values():
        with directory(group['path']) as fd:
            space = os.fstatvfs(fd)
        require(space.f_frsize > 0 and space.f_bavail >= 0, 'Cannot determine filesystem space')
        group.update(available_bytes=space.f_frsize * space.f_bavail, reserve_bytes=budget['reserve'])
        group['required_bytes'] = group['peak_bytes'] + budget['reserve']
        group['fits'] = group['available_bytes'] >= group['required_bytes']
        require(group['fits'], 'Insufficient space for native RAM/log peak + 64 GiB reserve: ' + group['path'])
    return list(groups.values())


def argv(binary, pair, output, cp, tomco, backup, ram):
    for path in (binary, pair, output, cp, tomco, backup):
        canonical(path)
    require(len(ram) == 6 and all(ram[index] == '-object' for index in (0, 2, 4)),
            'Native RAM contract must return only three -object arguments')
    expected = [('native-local-ram', 'cp-ram.bin', 128 * MIB, 0),
                ('native-peer-ram', 'ap-ram.bin', 8 * GIB, 15 * GIB),
                ('native-local-oom', 'cp-oom.bin', 0x101000, 0)]
    for index, (name, filename, size, offset) in enumerate(expected):
        require(json.loads(ram[index * 2 + 1]) == {
            'qom-type': 'memory-backend-file', 'id': name, 'mem-path': str(pair / filename),
            'size': size, 'offset': offset, 'share': True, 'discard-data': False},
            'Native CP RAM geometry/profile differs')
    result = [str(binary), '-M', 'none,memory-backend=native-local-ram', *ram,
              '-accel', 'tcg,thread=multi', '-m', '128M', '-smp', '4',
              '-cpu', 'cortex-a53,aarch64=off,cntfrq=2000000', '-S', '-nodefaults',
              '-nic', 'none', '-display', 'none', '-audio', 'none', '-monitor', 'none',
              '-serial', 'none', '-sandbox', 'on', '-d', 'guest_errors',
              '-qmp', 'unix:cp-qmp.sock,server=on,wait=off',
              '-chardev', 'socket,id=cp-gdb,path=cp-gdb.sock,server=on,wait=off', '-gdb', 'chardev:cp-gdb',
              '-chardev', 'socket,id=notify-peer,path=notify.sock,server=off']
    devices = [dict(driver='loader', file=str(cp), addr=CP_ADDRESS, **{'cpu-num': 0, 'force-raw': True})]
    devices += [dict(driver='loader', addr=CP_ADDRESS, **{'cpu-num': core}) for core in range(1, 4)]
    devices += [dict(driver='loader', file=str(path), addr=address, **{'force-raw': True})
                for path, address in ((tomco, TOMCO_ADDRESS), (backup, BACKUP_ADDRESS))]
    for device in devices:
        result += ['-device', json.dumps(device, separators=(',', ':'))]
    for uart in range(5):
        # Chardev uses QemuOpts, whose literal comma escape is a doubled comma.
        path = str(output / f'uart{uart}.log').replace(',', ',,')
        result += ['-chardev', f'file,id=cp-uart{uart},path={path}']
    return result


def protocol_classes(records):
    """Load the shipped broker without adding research paths or changing the caller cwd."""
    base = PRODUCT / 'runtime' / 'analysis'
    name = 'functional_face_source_snapshot'
    snapshot = ModuleType(name)
    snapshot.__dict__.update(runpy.run_path(str(base / (name + '.py'))))
    previous = sys.modules.get(name)
    sys.modules[name] = snapshot
    try:
        broker = runpy.run_path(str(base / 'functional_camera_broker.py'))
    finally:
        if previous is None:
            del sys.modules[name]
        else:
            sys.modules[name] = previous

    class RSP(broker['RSP']):
        def __init__(self, path, timeout=2.0, *, expected_pid=None):
            super().__init__(path, timeout=timeout, expected_pid=expected_pid)
            self.packet_size = checked_rsp_packet_size(self.request(b'qSupported'))

        def _byte(self, deadline):
            byte = super()._byte(deadline)
            self.wire.append(byte)
            return byte

        def _receive(self, deadline):
            self.wire = bytearray()
            try:
                packet = super()._receive(deadline)
            except BaseException as error:
                records.append(dict(rsp_error=repr(error), raw_wire_hex=self.wire.hex(), at=time.monotonic()))
                raise
            if packet[:1] in (b'T', b'S', b'W', b'X'):
                records.append(dict(rsp_stop_hex=packet.hex(), raw_wire_hex=self.wire.hex(), at=time.monotonic()))
            return packet

        def receive_stop(self, deadline):
            while True:
                packet = self._receive(deadline)
                if packet in (b'+', b'-'):
                    continue
                require(packet[:1] in (b'T', b'S', b'W', b'X'), 'Unexpected asynchronous RSP packet: ' + repr(packet))
                return packet

    class QMP(broker['QMP']):
        def _line(self, deadline):
            value = super()._line(deadline)
            records.append(dict(qmp=value, at=time.monotonic()))
            return value

        def execute(self, command, arguments=None):
            require(command in ('qmp_capabilities', 'query-status', 'cont', 'stop', 'quit')
                    and arguments is None, 'Unapproved native CP QMP command/arguments')
            self.serial += 1
            serial = self.serial
            records.append(dict(qmp_execute=command, id=serial, at=time.monotonic()))
            self.socket.settimeout(self.timeout)
            self.socket.sendall(json.dumps(dict(execute=command, id=serial)).encode('ascii') + b'\n')
            deadline = time.monotonic() + self.timeout
            for _ in range(256):
                value = self._line(deadline)
                if 'event' in value:
                    continue
                require(value.get('id') == serial and 'return' in value and 'error' not in value,
                        'QMP command failed/mismatched: ' + repr(value))
                return value['return']
            raise ValueError('QMP event flood')

        def drain_after_exit(self):
            deadline = time.monotonic() + self.timeout
            for _ in range(256):
                try:
                    value = self._line(deadline)
                except (EOFError, ConnectionResetError) as error:
                    require(not self.buffer, 'Partial final QMP line at close: ' + self.buffer.hex())
                    terminal = 'eof' if isinstance(error, EOFError) else 'peer-reset-after-exit'
                    records.append(dict(qmp_transport_terminal=terminal, at=time.monotonic()))
                    return terminal
                require('event' in value, 'Unexpected QMP reply after quit: ' + repr(value))
            raise ValueError('Final QMP event flood')

    return RSP, QMP


def connect_client(cls, path, process, *, seconds=15):
    deadline = time.monotonic() + seconds
    while True:
        try:
            require(process.poll() is None, 'Owned CP exited before control connection')
            owned_socket(path)
            return cls(path, timeout=3.0, expected_pid=process.pid)
        except (FileNotFoundError, ConnectionRefusedError):
            require(process.poll() is None and time.monotonic() < deadline, 'Owned CP startup failed at ' + str(path))
            time.sleep(0.02)


def registers(rsp):
    raw = rsp.request(b'g')
    require(len(raw) == 136 and re.fullmatch(b'[0-9a-fA-F]{136}', raw),
            'Strict A32 g must be exactly 68 bytes: ' + repr(raw))
    words = struct.unpack('<17I', bytes.fromhex(raw.decode('ascii')))
    return dict(raw_g_hex=raw.decode('ascii'), registers={
        **{'r' + str(index): value for index, value in enumerate(words[:16])}, 'cpsr': words[16]})


def threads(rsp):
    result = []
    command = b'qfThreadInfo'
    for _ in range(8):
        raw = rsp.request(command)
        if raw == b'l':
            break
        require(raw.startswith(b'm'), 'Invalid RSP thread list: ' + repr(raw))
        result.extend(raw[1:].split(b','))
        command = b'qsThreadInfo'
    else:
        raise ValueError('RSP thread list exceeded bound')
    require(len(result) == len(set(result)) == 4 and all(re.fullmatch(br'(?:p[0-9a-fA-F]+\.)?[0-9a-fA-F]+', t) for t in result),
            'Expected exactly four distinct CP CPU threads')
    return result


def stop_thread(packet, cpu_threads):
    tags = b';' + packet[3:]
    explicit = re.findall(br'(?:^|;)thread:([^;]+)(?=;)', tags)
    cores = re.findall(br'(?:^|;)core:([^;]+)(?=;)', tags)
    require(len(explicit) <= 1 and len(cores) <= 1 and (explicit or cores), 'Stop has no unique CP identity tag')
    if explicit:
        require(explicit[0] in cpu_threads, 'Stop thread is not an enumerated CP CPU')
        thread = explicit[0]
    else:
        require(re.fullmatch(br'[0-9a-fA-F]+', cores[0]) is not None, 'Invalid stop core id')
        # QEMU system.c uses gdb_get_cpu_index() for both core and thread IDs.
        candidates = [t for t in cpu_threads if int(t.rsplit(b'.', 1)[-1], 16) == int(cores[0], 16)]
        require(len(candidates) == 1, 'Stop core is absent or ambiguous in enumerated CP CPUs')
        thread = candidates[0]
    if cores:
        require(re.fullmatch(br'[0-9a-fA-F]+', cores[0]) is not None and
                int(thread.rsplit(b'.', 1)[-1], 16) == int(cores[0], 16), 'Stop thread/core identities disagree')
    return thread


def select_thread(rsp, thread):
    require(rsp.request(b'Hg' + thread) == b'OK', 'RSP CPU selection refused')


def verify_loaded(rsp, inputs, result):
    result['loaded_input_readback'] = []
    rsp.mode(True)
    for name, address, proof in inputs:
        digest, offset = hashlib.sha256(), 0
        item = dict(name=name, address=address, bytes=proof['size'], expected_sha256=proof['sha256'], verified=False)
        result['loaded_input_readback'].append(item)
        while offset < proof['size']:
            amount = min(64 * 1024, proof['size'] - offset)
            data = rsp.read(address + offset, amount)
            require(len(data) == amount, 'Short complete loaded-input readback: ' + name)
            digest.update(data)
            offset += amount
        item.update(read_bytes=offset, actual_sha256=digest.hexdigest())
        require(item['actual_sha256'] == proof['sha256'], 'Full RSP input SHA256 differs: ' + name)
        item['verified'] = True
    result['loaded_inputs_verified'] = True


def snapshot(rsp, cpu_threads, destination):
    destination.update(cpus=[], rings=[], observer_writes=False)
    for thread in cpu_threads:
        item = dict(thread=thread.decode('ascii'))
        destination['cpus'].append(item)
        try:
            select_thread(rsp, thread)
            item.update(registers(rsp))
            regs = item['registers']
            item.update(pc=regs['r15'], lr=regs['r14'], sp=regs['r13'])
            sp = regs['r13']
            if CP_ADDRESS <= sp <= CP_RAM_SIZE - 128 and not sp % 4:
                item['stack_hex'] = rsp.read(sp, 128).hex()
            else:
                item['stack_unread_reason'] = 'SP outside bounded CP RAM or unaligned'
        except Exception as error:
            item['error'] = repr(error)
    for group in range(4):
        base = 0x03f80000 + group * 0x20000
        for offset, length in ((0, 32), (0x1ce0, 12), (0x2000, 32), (0x3ce0, 12)):
            item = dict(group=group, address=base + offset, bytes=length)
            destination['rings'].append(item)
            try:
                item['raw_hex'] = rsp.read(base + offset, length).hex()
            except Exception as error:
                item['error'] = repr(error)
    destination['complete'] = not any('error' in item for item in destination['cpus'] + destination['rings'])


def _strict_json(raw,link):
    return json.loads(raw,object_pairs_hook=link._unique_object)


def _host_process(pid):
    try:
        process=Path('/proc')/str(pid)
        tail=(process/'stat').read_text().rsplit(')',1)[1].split()
        require(len(tail)>19 and tail[0] not in ('Z','X'),'External AP/QEMU process already exited')
        command=(process/'cmdline').read_bytes()
        require(command and command.endswith(b'\0'),'External AP/QEMU argv is unavailable')
        exe_path=os.readlink(process/'exe')
        require(not exe_path.endswith(' (deleted)'),'External AP/QEMU executable was deleted')
        exe=(process/'exe').stat();process_stat=process.stat()
        return dict(pid=pid,start_ticks=tail[19],state=tail[0],uid=process_stat.st_uid,gid=process_stat.st_gid,
                    command=command,command_sha256=hashlib.sha256(command).hexdigest(),exe_path=exe_path,
                    exe_dev=exe.st_dev,exe_ino=exe.st_ino,exe_size=exe.st_size,exe_mode=exe.st_mode)
    except OSError as error:
        raise ValueError('External AP/QEMU process identity is inaccessible') from error


def _host_boot_id():
    value=(Path('/proc/sys/kernel/random/boot_id')).read_text().strip()
    require(len(value)==36 and all(c in '0123456789abcdef-' for c in value),'Host boot identity unavailable')
    return value


def pidfd_exited(fd):
    poller=select.poll();poller.register(fd,select.POLLIN|select.POLLHUP|select.POLLERR)
    return bool(poller.poll(0))


def open_external_ap_pidfds(record):
    opened={}
    expected=(('owner',record['owner_pid'],record['start_ticks'],os.getuid(),record['argv_sha256']),
              ('qemu',record['qemu_pid'],record['qemu_start_ticks'],record['qemu_uid'],record['qemu_command_sha256']))
    try:
        require(_host_boot_id()==record['host_boot_id'],'Host boot generation changed before pidfd pin')
        for role,pid,start_ticks,uid,command_sha in expected:
            try:fd=os.pidfd_open(pid,0)
            except (AttributeError,OSError) as error:raise ValueError('Cannot pin AP '+role+' process with pidfd') from error
            opened[role]=fd;current=_host_process(pid)
            require(current['start_ticks']==start_ticks and current['uid']==uid and
                    current['command_sha256']==command_sha and not pidfd_exited(fd),
                    'AP '+role+' process generation changed before pidfd pin')
            if role=='qemu':
                require(current['gid']==record['qemu_gid'] and current['exe_dev']==record['qemu_exe_dev'] and
                        current['exe_ino']==record['qemu_exe_ino'] and current['exe_size']==record['qemu_exe_size'] and
                        current['exe_mode']==record['qemu_exe_mode'],'AP QEMU executable changed before pidfd pin')
        return opened
    except BaseException:
        for fd in opened.values():os.close(fd)
        raise


def external_ap_owner_exited(pidfds):
    if isinstance(pidfds,dict):return any(pidfd_exited(fd) for fd in pidfds.values())
    return pidfd_exited(pidfds)


def close_external_ap_pidfds(pidfds):
    if isinstance(pidfds,dict):
        for fd in pidfds.values():os.close(fd)
    elif pidfds is not None:os.close(pidfds)



@contextmanager
def external_ap_cont_lock(owner):
    run=canonical(owner['ap_run']);expected=owner['control_lock'];fd=None
    with directory(run) as run_fd:
        info=os.stat('ap-cp-control.lock',dir_fd=run_fd,follow_symlinks=False)
        require(stat.S_ISREG(info.st_mode) and info.st_uid==os.getuid() and info.st_nlink==1 and
                stat.S_IMODE(info.st_mode)==0o600 and
                (info.st_dev,info.st_ino,info.st_size,info.st_mode,info.st_uid,info.st_nlink,
                 info.st_mtime_ns,info.st_ctime_ns)==
                tuple(expected[k] for k in ('dev','ino','size','mode','uid','nlink','mtime_ns','ctime_ns')),
                'AP quit/cont lock identity differs')
        fd=os.open('ap-cp-control.lock',os.O_RDWR|os.O_NOFOLLOW|os.O_NONBLOCK|os.O_CLOEXEC,dir_fd=run_fd)
    try:
        opened=os.fstat(fd)
        require(stat.S_ISREG(opened.st_mode) and opened.st_uid==os.getuid() and opened.st_nlink==1 and
                stat.S_IMODE(opened.st_mode)==0o600 and
                all(getattr(opened,'st_'+key)==expected.get(key) for key in
                    ('dev','ino','size','mode','uid','nlink','mtime_ns','ctime_ns')),
                'AP control lock changed while opening')
        try:fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError as error:raise ValueError('AP shutdown owns the run lock; CP cont refused') from error
        yield
    finally:
        if fd is not None:
            try:fcntl.flock(fd,fcntl.LOCK_UN)
            finally:os.close(fd)


def check_external_ap_owner(result):
    link,_=products();pair=canonical(result['pair'])
    admission=link.admit(pair,canonical(result['pair_admission']['binary']['path']))
    require(admission==result['pair_admission'],'Native AP/CP pair admission changed')
    claim_proof,claim_raw=input_record(pair/'ap-admission.claim',keep=True,maximum=256*1024)
    claim=_strict_json(claim_raw,link)
    command=link.ap_probe_command();command_raw=b'\0'.join(os.fsencode(word) for word in command)+b'\0'
    require(type(claim) is dict and claim.get('schema')=='a7c2-native-ap-admission-v2' and
            claim.get('profile')==PROFILE and claim.get('pair')==str(pair) and
            claim.get('pair_admission')==admission and claim.get('binary_sha256')==admission['binary']['sha256'] and
            claim.get('command')==command and claim.get('command_sha256')==hashlib.sha256(command_raw).hexdigest() and
            type(claim.get('owner_pid')) is int and claim['owner_pid']>1 and
            type(claim.get('owner_start_ticks')) is str and type(claim.get('host_boot_id')) is str and
            type(claim.get('run_nonce')) is str and len(claim['run_nonce'])==32 and
            all(c in '0123456789abcdef' for c in claim['run_nonce']),
            'External AP claim schema/generation does not belong to this pair/binary')
    owner=_host_process(claim['owner_pid'])
    require(owner['uid']==os.getuid() and owner['start_ticks']==claim['owner_start_ticks'] and
            owner['command']==command_raw and owner['command_sha256']==claim['command_sha256'] and
            _host_boot_id()==claim['host_boot_id'],'External AP owner was replaced/exited or differs from creation-time generation')
    environment=(Path('/proc')/str(claim['owner_pid'])/'environ').read_bytes().split(b'\0')
    require(os.fsencode('QEMU_NATIVE_LINK_DIR='+str(pair)) in environment and
            os.fsencode('QEMU_NATIVE_AP_CP_LINK='+PROFILE) in environment,'External AP owner pair environment differs')
    pointer_proof,pointer=input_record(pair/'latest-ap-run.txt',keep=True,maximum=4096)
    require(pointer.endswith(b'\n') and pointer.count(b'\n')==1,'External AP latest-run pointer framing differs')
    ap_run=canonical(pointer[:-1].decode('utf-8'))
    require(ap_run.parent==pair/'ap-runs' and ap_run.name.startswith('run-') and ap_run.is_dir(),
            'External AP pointer must identify one exact direct-child run')
    run_stat=ap_run.lstat();pair_stat=pair.lstat();root=admission['root_identity']
    require(stat.S_ISDIR(run_stat.st_mode) and run_stat.st_uid==os.getuid() and
            stat.S_IMODE(run_stat.st_mode)==0o700 and
            (pair_stat.st_dev,pair_stat.st_ino,pair_stat.st_mode,pair_stat.st_uid)==
            (root['dev'],root['ino'],root['mode'],root['uid']),'External AP pair/run directory identity differs')
    vm_proof,vm_raw=input_record(ap_run/'native-ap-vm.json',keep=True,maximum=256*1024)
    vm=_strict_json(vm_raw,link)
    require(vm.get('schema')=='a7c2-native-ap-vm-owner-v1' and vm.get('ready') is True and
            vm.get('profile')==PROFILE and vm.get('pair')==str(pair) and vm.get('ap_run')==str(ap_run) and
            vm.get('run_nonce')==claim['run_nonce'] and vm.get('claim_sha256')==claim_proof['sha256'] and
            vm.get('owner_pid')==claim['owner_pid'] and vm.get('owner_start_ticks')==claim['owner_start_ticks'] and
            vm.get('host_boot_id')==claim['host_boot_id'] and
            vm.get('owner_command_sha256')==claim['command_sha256'] and
            vm.get('binary_path')==admission['binary']['path'] and
            vm.get('binary_sha256')==admission['binary']['sha256'] and
            vm.get('run_pointer_sha256')==pointer_proof['sha256'],'Actual AP VM owner record is not bound to this claim/run')
    require(vm.get('pair_root_identity')==root and
            vm.get('run_root_identity')==dict(dev=run_stat.st_dev,ino=run_stat.st_ino,
                                              mode=run_stat.st_mode,uid=run_stat.st_uid),
            'External AP pair/run directory generation differs')
    qmp_peer=vm.get('qmp_peer');require(type(qmp_peer) is dict,'Missing QMP SO_PEERCRED')
    require(type(qmp_peer.get('pid')) is int and qmp_peer['pid']>1 and
            type(qmp_peer.get('uid')) is int and type(qmp_peer.get('gid')) is int,
            'Invalid AP QMP SO_PEERCRED identity')
    qemu=_host_process(qmp_peer['pid'])
    binary=admission['binary']
    require(qmp_peer.get('pid')==vm.get('qemu_pid') and qmp_peer.get('uid')==qemu['uid']==vm.get('qemu_uid') and
            qmp_peer.get('gid')==qemu['gid']==vm.get('qemu_gid') and
            qmp_peer.get('dev')==os.stat(ap_run/'qmp.sock',follow_symlinks=False).st_dev and
            qmp_peer.get('ino')==os.stat(ap_run/'qmp.sock',follow_symlinks=False).st_ino and
            stat.S_ISSOCK(os.stat(ap_run/'qmp.sock',follow_symlinks=False).st_mode) and
            qemu['start_ticks']==vm.get('qemu_start_ticks') and qemu['command_sha256']==vm.get('qemu_command_sha256') and
            qemu['exe_path']==vm.get('qemu_exe_path') and qemu['exe_dev']==vm.get('qemu_exe_dev')==binary['dev'] and
            qemu['exe_ino']==vm.get('qemu_exe_ino')==binary['ino'] and qemu['exe_size']==vm.get('qemu_exe_size')==binary['size'] and
            qemu['exe_mode']==vm.get('qemu_exe_mode')==binary['mode'] and
            vm.get('binary_sha256')==binary['sha256'],'Actual AP QMP peer is not the admitted QEMU binary generation')
    lock=vm.get('control_lock');require(type(lock) is dict and lock.get('path')==str(ap_run/'ap-cp-control.lock'),
                                         'AP control lock record missing')
    try:
        with directory(ap_run) as run_fd:
            info=os.stat('ap-cp-control.lock',dir_fd=run_fd,follow_symlinks=False)
            require(stat.S_ISREG(info.st_mode) and info.st_uid==os.getuid() and info.st_nlink==1 and
                    stat.S_IMODE(info.st_mode)==0o600 and
                    all(getattr(info,'st_'+key)==lock.get(key) for key in
                        ('dev','ino','size','mode','uid','nlink','mtime_ns','ctime_ns')),
                    'AP control lock identity differs')
            try:os.stat('qmp-quit.json',dir_fd=run_fd,follow_symlinks=False)
            except FileNotFoundError:pass
            else:raise ValueError('External AP QMP quit has started')
    except OSError as error:raise ValueError('External AP run/lock record is inaccessible') from error
    # Re-read identities after the cross-process checks; process state is deliberately not equality-bound.
    require(input_record(pair/'ap-admission.claim')[0]==claim_proof and
            input_record(pair/'latest-ap-run.txt')[0]==pointer_proof and
            input_record(ap_run/'native-ap-vm.json')[0]==vm_proof and
            _host_process(claim['owner_pid'])['start_ticks']==claim['owner_start_ticks'] and
            _host_process(qmp_peer['pid'])['start_ticks']==vm['qemu_start_ticks'] and
            _host_boot_id()==claim['host_boot_id'],'External AP identity changed during validation')
    record=dict(owner_pid=claim['owner_pid'],start_ticks=claim['owner_start_ticks'],host_boot_id=claim['host_boot_id'],
                claim_sha256=claim_proof['sha256'],argv_sha256=claim['command_sha256'],run_nonce=claim['run_nonce'],
                ap_run=str(ap_run),run_pointer_sha256=pointer_proof['sha256'],run_owner_sha256=vm_proof['sha256'],
                qemu_pid=vm['qemu_pid'],qemu_start_ticks=vm['qemu_start_ticks'],qemu_uid=vm['qemu_uid'],qemu_gid=vm['qemu_gid'],
                qemu_exe_dev=vm['qemu_exe_dev'],qemu_exe_ino=vm['qemu_exe_ino'],qemu_exe_size=vm['qemu_exe_size'],
                qemu_exe_mode=vm['qemu_exe_mode'],qemu_command_sha256=vm['qemu_command_sha256'],qmp_socket_dev=qmp_peer['dev'],qmp_socket_ino=qmp_peer['ino'],
                control_lock=dict(lock))
    previous=result.get('external_ap_before_inputs')
    require(previous is None or previous==record,'External AP generation was replaced during CP verification')
    return record




def continue_cp(qmp,result,ap_vm_pidfd,phase):
    boundary=qmp.execute('query-status')
    require(boundary.get('running') is False,'CP must be paused before guarded continuation')
    owner=check_external_ap_owner(result)
    baseline=result.get('external_ap_before_inputs')
    if baseline is None:
        result['external_ap_before_inputs']=baseline=owner
    require(owner==baseline,'AP owner differs from the admitted pre-input generation')
    if phase=='initial':result['external_ap_before_cont']=owner
    require(ap_vm_pidfd is not None and not external_ap_owner_exited(ap_vm_pidfd),
            'External AP probe owner or QEMU exited before continuation')
    with external_ap_cont_lock(owner):
        require(check_external_ap_owner(result)==owner and not external_ap_owner_exited(ap_vm_pidfd),
                'AP owner/quit state changed at the CP cont boundary')
        try:qmp.execute('cont')
        except BaseException:
            try:qmp.execute('stop')
            except Exception as error:result.setdefault('errors',[]).append(dict(cp_stop_after_cont_error=repr(error)))
            raise
        if external_ap_owner_exited(ap_vm_pidfd):
            try:qmp.execute('stop')
            except Exception as error:result.setdefault('errors',[]).append(dict(cp_stop_after_ap_exit_error=repr(error)))
            raise ValueError('External AP owner/QEMU exited during CP cont; owned CP stop requested')
        result.setdefault('external_ap_cont_attempts',[]).append(dict(
            phase=phase,owner_pid=owner['owner_pid'],owner_start_ticks=owner['start_ticks'],
            qemu_pid=owner['qemu_pid'],qemu_start_ticks=owner['qemu_start_ticks'],
            claim_sha256=owner['claim_sha256'],run_owner_sha256=owner['run_owner_sha256']))
    return boundary


def observe(rsp,qmp,process,seconds,result,ap_vm_pidfd=None):
    initial_stop = rsp.request(b'?')
    result['initial_stop_hex'] = initial_stop.hex()
    require(initial_stop[:1] in (b'T', b'S'), 'Initial CP stop reply missing')
    cpu_threads = threads(rsp)
    result['initial_cpus'] = []
    for thread in cpu_threads:
        select_thread(rsp, thread)
        sample = registers(rsp)
        result['initial_cpus'].append(dict(thread=thread.decode('ascii'), **sample))
        require(sample['registers']['r15'] == CP_ADDRESS and not sample['registers']['cpsr'] & 0x20,
                'Initial original CP PC/A32 state differs')
    verify_loaded(rsp, [(name, address, result['inputs'][name]) for name, address in
                       (('cp', CP_ADDRESS), ('tomco', TOMCO_ADDRESS), ('backup', BACKUP_ADDRESS))], result)
    for address, length in BREAKPOINTS.items():
        require(rsp.request(f'Z1,{address:x},{length:x}'.encode('ascii')) == b'OK', 'Hardware breakpoint refused')
    result['breakpoints'] = [dict(type='Z1', address=address, bytes=length) for address, length in BREAKPOINTS.items()]
    result['start_boundary']=continue_cp(qmp,result,ap_vm_pidfd,'initial')
    result['continued_at'] = started = time.monotonic()
    deadline = started + seconds
    result['observations'] = []
    receiver_armed = True
    try:
        while time.monotonic() < deadline:
            require(process.poll() is None, 'Owned CP exited during observation')
            require(ap_vm_pidfd is not None and not external_ap_owner_exited(ap_vm_pidfd),
                    'External AP probe owner or QEMU exited while original CP was running')
            state = result['last_poll_boundary'] = qmp.execute('query-status')
            require(type(state.get('running')) is bool, 'Invalid QMP running boundary')
            packet = None
            if not state['running']:
                # A QMP-driven continue need not arm unsolicited GDB stop replies.
                packet = rsp.request(b'?')
            elif rsp.buffer or select.select([rsp.socket], [], [], min(0.25, max(0, deadline - time.monotonic())))[0]:
                packet = rsp.receive_stop(min(deadline + 3, time.monotonic() + 3))
            if packet is not None:
                require(packet[:3] in (b'T05', b'S05'), 'Unexpected CP stop/exit: ' + repr(packet))
                qmp.execute('stop')
                state = qmp.execute('query-status')
                require(state.get('running') is False, 'Breakpoint did not stop all CP CPUs')
                item = dict(stop_hex=packet.hex(), at=time.monotonic(), boundary=state)
                result['observations'].append(item)
                snapshot(rsp, cpu_threads, item)
                if not item['complete']:
                    result.setdefault('errors', []).append(dict(observation_snapshot_incomplete=True, at=item['at']))
                bound_thread = stop_thread(packet, cpu_threads)
                item['bound_thread'] = bound_thread.decode('ascii')
                hit = next(cpu for cpu in item['cpus'] if cpu['thread'] == item['bound_thread'])
                require('error' not in hit, 'Stopped CPU register/stack read failed')
                if hit['pc'] == ABORT and not hit['registers']['cpsr'] & 0x20:
                    item['kind'] = 'first-data-abort'
                    item['fault_pc_lr_minus_8'] = (hit['lr'] - 8) & 0xffffffff
                    result['original_cp_execution_observed'] = True
                    result['first_data_abort_observed'] = True
                    break
                require(receiver_armed and hit['pc'] == RECEIVER and hit['registers']['cpsr'] & 0x20,
                        'Stop does not match an armed original CP hardware breakpoint')
                item['kind'] = 'original-receiver-entry'
                result['original_cp_execution_observed'] = result['receiver_entry_observed'] = True
                require(rsp.request(f'z1,{RECEIVER:x},2'.encode('ascii')) == b'OK', 'Receiver breakpoint removal refused')
                receiver_armed = False
                continue_cp(qmp,result,ap_vm_pidfd,'receiver')
        else:
            require(ap_vm_pidfd is not None and not external_ap_owner_exited(ap_vm_pidfd),
                    'External AP probe owner or QEMU exited at the end of CP observation')
            result['window_completed'] = True
    finally:
        primary_error=sys.exc_info()[1]
        try:
            qmp.execute('stop')
            result['end_boundary'] = qmp.execute('query-status')
            require(result['end_boundary'].get('running') is False, 'Final CP stop boundary missing')
            result['observed_wall_seconds'] = time.monotonic() - started
            result['final_state'] = {}
            snapshot(rsp, cpu_threads, result['final_state'])
            result['final_read_boundary'] = qmp.execute('query-status')
            require(result['final_read_boundary'].get('running') is False, 'CP resumed during final read-only snapshot')
            final_cpus = result['final_state']['cpus']
            if any('pc' in cpu and CP_ADDRESS < cpu['pc'] < CP_ADDRESS + CP_SIZE for cpu in final_cpus):
                result['original_cp_execution_observed'] = True
            for cpu in final_cpus:
                if 'pc' not in cpu:
                    continue
                thumb = bool(cpu['registers']['cpsr'] & 0x20)
                if (cpu['pc'] == ABORT and not thumb) or (cpu['pc'] == RECEIVER and thumb):
                    result.setdefault('boundary_entry_samples', []).append(dict(
                        thread=cpu['thread'], pc=cpu['pc'], lr=cpu['lr'],
                        source='Final stopped PC sample; not a decoded asynchronous breakpoint reply'))
                    result['first_data_abort_observed' if cpu['pc'] == ABORT else 'receiver_entry_observed'] = True
            require(result['final_state']['complete'],
                    'Final CP CPU/stack/ring snapshot incomplete; see original per-read errors')
        except BaseException as cleanup_error:
            result.setdefault('errors',[]).append(dict(observe_finalization_error=repr(cleanup_error)))
            if primary_error is None:raise


def shutdown(process, qmp, rsp, streams, result):
    """Never signal or discard a live owner after a failed QMP transaction."""
    receipt = result['shutdown'] = dict(pid=process.pid, signals=[], qmp_quit_confirmed=False,
                                        cp_process_released=False, pair_lease_released=False)
    try:
        require(process.poll() is None and qmp is not None, 'CP is already exited or QMP is unavailable')
        receipt['quit_response'] = qmp.execute('quit')
        receipt['qmp_quit_confirmed'] = True
        receipt['returncode'] = process.wait(timeout=15)
        require(receipt['returncode'] == 0, 'Owned CP did not exit with rc=0 after QMP quit')
        terminal = qmp.drain_after_exit()
        require(terminal in ('eof', 'peer-reset-after-exit'), 'Unverified final QMP close boundary')
        receipt['qmp_transport_terminal'] = terminal
        receipt['qmp_eof_observed'] = terminal == 'eof'
        receipt['cp_process_released'] = True
    except BaseException as error:
        receipt['error'] = repr(error)
    receipt.update(alive=process.poll() is None, returncode=process.returncode)
    if receipt['alive']:
        receipt['retained'] = True
        RETAINED.append(dict(process=process, qmp=qmp, rsp=rsp, streams=streams, result=result))
        print(f"retained: CP pid={process.pid}; QMP/GDB handles, pair lease and all RAM retained; no signals sent", file=sys.stderr)
    else:
        for client in (rsp, qmp):
            if client is not None:
                try:
                    client.close()
                except Exception as error:
                    receipt.setdefault('close_errors', []).append(repr(error))
        for stream in streams:
            stream.close()
    return receipt['cp_process_released']


def run(args):
    output = canonical(args.output)
    with directory(output.parent) as parent:
        os.mkdir(output.name, 0o700, dir_fd=parent)
    with directory(output) as fd:
        os.fchmod(fd, 0o700)
    result = dict(schema='a7c2-native-cp-launch-v1', profile=PROFILE, output=str(output),
                  loaded_inputs_verified=False, original_cp_execution_observed=False,
                  receiver_entry_observed=False, first_data_abort_observed=False, window_completed=False,
                  full_boot=False, original_ap_consumption=False, capture=False, signals=[], records=[], inputs={},
                  functional_model=dict(model='Functional timer hypotheses', secure_physical_timer_ppi=30, cntfrq_hz=2000000,
                                        ppi30_physical_calibrated=False, cntfrq_physical_calibrated=False,
                                        physical_calibrated=False), pair_lease_released=False, errors=[])
    process = qmp = rsp = ap_vm_pidfd = None
    streams, originals = [], []
    pair = None
    QMP = None
    try:
        budget = result['limits'] = limits(args.seconds)
        pair, binary = canonical(args.pair), canonical(args.binary)
        result.update(pair=str(pair), qmp_socket=str(pair / 'cp-qmp.sock'), gdb_socket=str(pair / 'cp-gdb.sock'))
        link, backup_loader = products()
        binary_proof, _ = input_record(binary)
        require(binary_proof['mode'] & 0o111, 'QEMU binary is not executable')
        originals.append(binary_proof)
        result['pair_admission'] = link.admit(pair, binary)
        require(result['pair_admission']['profile'] == PROFILE, 'Native pair profile differs')
        try:
            result['notify_peer'] = owned_socket(pair / 'notify.sock')
        except FileNotFoundError as error:
            raise ValueError('External AP notify socket missing: ' + str(pair / 'notify.sock')) from error
        result['external_ap_before_inputs']=check_external_ap_owner(result)
        ap_vm_pidfd=open_external_ap_pidfds(result['external_ap_before_inputs'])
        result['external_ap_pidfd_pinned']=True
        for name in ('cp-qmp.sock', 'cp-gdb.sock'):
            require(not os.path.lexists(pair / name), 'Fresh CP endpoint already exists: ' + name)
        cp, tomco, pp = (canonical(getattr(args, name)) for name in ('cp_image', 'tomco', 'pp'))
        cp_proof, cp_bytes = input_record(cp, CP_SIZE, CP_SHA, keep=True)
        tomco_proof, _ = input_record(tomco, TOMCO_SIZE, TOMCO_SHA)
        pp_proof, _ = input_record(pp, backup_loader.PP_BYTES, backup_loader.PP_SHA)
        originals.extend((cp_proof, tomco_proof, pp_proof))
        result['inputs'].update(cp=cp_proof, tomco=tomco_proof, pp=pp_proof)
        result['original_stack_descriptors'] = stack_descriptors(cp_bytes)
        del cp_bytes
        record, proof = backup_loader.load_record(pp, args.backup)
        require(input_record(pp, pp_proof['size'], pp_proof['sha256'])[0] == pp_proof,
                'Official PP changed during record extraction')
        result['backup_selection'] = proof
        result['storage_budget'] = storage_budget(pair, output, result['pair_admission'], budget)
        env = environment(link, pair, os.environ)
        result['environment_delta'] = {key: value for key, value in env.items()
                                       if key.startswith(('QEMU_CP_', 'QEMU_NATIVE_', 'QEMU_AP_CP_'))}
        ram = link.ram_arguments(pair, 'cp')
        staged = output / ('official-' + args.backup + '.bin')
        command = argv(binary, pair, output, cp, tomco, staged, ram)
        result['argv'] = command
        RSP, QMP = protocol_classes(result['records'])
        write_json(pair / CLAIM, dict(schema='a7c2-native-cp-claim-v1', owner_pid=os.getpid(),
                                     pair=str(pair), output=str(output), binary_sha256=binary_proof['sha256'],
                                     created_ns=time.time_ns(), replay_allowed=False, coordinator_owns_pair_release=True))
        result['claim'] = str(pair / CLAIM)
        fd = new_file(staged, record)
        os.close(fd)
        staged_proof, _ = input_record(staged, len(record), proof['sha256'])
        result['inputs']['backup'] = staged_proof
        originals.append(staged_proof)
        for name in ('cp.stdout.raw', 'cp.stderr.raw', *(f'uart{uart}.log' for uart in range(5))):
            fd = new_file(output / name)
            if name in ('cp.stdout.raw', 'cp.stderr.raw'):
                streams.append(os.fdopen(fd, 'wb', buffering=0))
            else:
                os.close(fd)
        require(owned_socket(pair / 'notify.sock') == result['notify_peer'], 'External AP notify socket changed')
        require(link.admit(pair, binary) == result['pair_admission'], 'Pair/binary/stage changed before launch')
        process = subprocess.Popen(command, cwd=pair, env=env, stdin=subprocess.DEVNULL,
                                   stdout=streams[0], stderr=streams[1], start_new_session=True,
                                   preexec_fn=lambda: child_limits(budget))
        result['pid'] = process.pid
        write_json(output / 'owner.json', dict(pid=process.pid, owner_pid=os.getpid(), pair=str(pair),
                                             claim=str(pair / CLAIM), qmp_socket=str(pair / 'cp-qmp.sock'),
                                             gdb_socket=str(pair / 'cp-gdb.sock'), owns_external_ap=False,
                                             pair_lease_released=False, argv=command))
        qmp = connect_client(QMP, pair / 'cp-qmp.sock', process)
        rsp = connect_client(RSP, pair / 'cp-gdb.sock', process)
        observe(rsp,qmp,process,args.seconds,result,ap_vm_pidfd)
    except BaseException as error:
        result['errors'].append(dict(error=repr(error), traceback=traceback.format_exc()))
    finally:
        if process is not None:
            if qmp is None and process.poll() is None and QMP is not None:
                try:
                    qmp = connect_client(QMP, pair / 'cp-qmp.sock', process, seconds=3)
                except BaseException as error:
                    result['errors'].append(dict(shutdown_connect_error=repr(error)))
            shutdown(process,qmp,rsp,streams,result)
        else:
            for stream in streams:
                stream.close()
        if ap_vm_pidfd is not None:
            if result.get('shutdown',{}).get('alive'):
                RETAINED[-1]['ap_vm_pidfd']=ap_vm_pidfd
            else:
                close_external_ap_pidfds(ap_vm_pidfd)
        for proof in originals:
            try:
                require(input_record(proof['path'], proof['size'], proof['sha256'])[0] == proof,
                        'Original input identity changed: ' + proof['path'])
            except BaseException as error:
                result['errors'].append(dict(input_recheck_error=repr(error), path=proof['path']))
        result['reset_events'] = [entry['qmp'] for entry in result['records']
                                  if entry.get('qmp', {}).get('event') == 'RESET']
        result['event_boundary_complete'] = all(key in result for key in
                                                ('start_boundary', 'end_boundary', 'final_read_boundary')) and not result['errors']
        result['no_reset_observed_between_boundaries'] = (result['event_boundary_complete'] and not result['reset_events'])
        result['reset_assessment_scope'] = 'Recorded QMP events bracketed by query-status; no claim outside those boundaries'
        result['ok'] = bool(result['window_completed'] and result['loaded_inputs_verified']
                            and not result['first_data_abort_observed'] and not result['errors']
                            and result.get('shutdown', {}).get('cp_process_released'))
        result['retention'] = dict(ram_files_removed=[], reclaimed_bytes=0, owns_external_ap=False,
                                   pair_lease_released=False, next_consumer='Parent AP/CP coordinator',
                                   release_condition='Coordinator verifies both owners and detach; this tool never releases the pair')
        try:
            result['output_allocated_bytes_before_receipt'] = sum(path.lstat().st_blocks * 512 for path in output.iterdir())
            space = os.statvfs(output)
            result['filesystem_available_bytes'] = space.f_bavail * space.f_frsize
        except OSError as error:
            result['errors'].append(dict(storage_receipt_error=repr(error)))
            result['ok'] = False
        write_json(output / 'result.json', result)
    return result


def main(arguments=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for option in ('cp-image', 'tomco', 'pp', 'binary', 'pair', 'output'):
        parser.add_argument('--' + option, required=True, type=Path, help='Canonical absolute nonsymlink local path')
    parser.add_argument('--backup', choices=('rec0', 'ed000', 'full'), required=True,
                        help='Explicit official PP record selection; original loader choice remains unknown')
    parser.add_argument('--seconds', type=int, default=180, help='Wall observation window, 1..3600 (default 180)')
    args = parser.parse_args(arguments)
    try:
        result = run(args)
    except BaseException as error:
        print('Native CP launch failed before a result could be retained: ' + repr(error), file=sys.stderr)
        return 2
    print(json.dumps(dict(ok=result['ok'], output=result['output'], pid=result.get('pid'),
                          retained=result.get('shutdown', {}).get('alive', False),
                          loaded_inputs_verified=result['loaded_inputs_verified'],
                          original_cp_execution_observed=result['original_cp_execution_observed'],
                          receiver_entry_observed=result['receiver_entry_observed'],
                          full_boot=False, original_ap_consumption=False, capture=False)))
    return 0 if result['ok'] else 2


if __name__ == '__main__':
    sys.exit(main())
