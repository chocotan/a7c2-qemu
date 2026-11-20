#!/usr/bin/env python3
"""Prepare/admit an isolated native AP/CP RAM pair; never launch QEMU."""
import argparse
from collections.abc import Mapping
from contextlib import contextmanager
import fcntl
import hashlib
import json
import os
from pathlib import Path
import runpy
import stat
import sys
import time

PROFILE = 'virtual-native-ap-cp-link-v1'
SCHEMA = 'a7c2-native-ap-cp-link-v1'
GPIO_PROFILE = 'virtual-ap-cp-gpio-lines-v1'
PERIPHERALS_PROFILE = 'virtual-cp-boot-peripherals-v1'
GIB = 1024 ** 3
MIB = 1024 ** 2
AP_SIZE = 24 * GIB
CP_SIZE = 128 * MIB
OOM_SIZE = 0x101000
AP_DDR_OFFSET = 15 * GIB
CP_AP_VIEW_SIZE = 8 * GIB
FILE_SIZES = {'ap-ram.bin': AP_SIZE, 'cp-ram.bin': CP_SIZE, 'cp-oom.bin': OOM_SIZE}
MANIFEST = 'native-link.json'
FAILURE_MANIFEST = 'native-link-failure.json'
LOG_BUDGET = 512 * MIB
RESERVE = 64 * GIB
JSON_LIMIT = 8 * MIB
HERE = Path(__file__).absolute().parent
PRODUCT = HERE.parents[1]
DIR_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
READ_FLAGS = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC
CREATE_FLAGS = os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC


def _require(condition, message):
    if not condition:
        raise ValueError(message)


@contextmanager
def _validation():
    try:
        yield
    except ValueError:
        raise
    except Exception as error:
        raise ValueError(str(error)) from error


def _canonical(path):
    raw = os.fspath(path)
    _require(isinstance(raw, str) and raw.startswith('/') and '\0' not in raw,
             'Expected a canonical absolute path')
    _require(raw == os.path.normpath(raw) and not raw.startswith('//'),
             'Path must already be canonical: ' + raw)
    _require(not any(raw == prefix or raw.startswith(prefix + '/')
                     for prefix in ('/dev', '/proc', '/sys', '/tmp')),
             'Device/proc/sys and host /tmp paths are forbidden')
    return Path(raw)


@contextmanager
def _directory(path):
    path = _canonical(path)
    fd = os.open('/', DIR_FLAGS)
    try:
        for component in path.parts[1:]:
            next_fd = os.open(component, DIR_FLAGS, dir_fd=fd)
            os.close(fd)
            fd = next_fd
        yield fd
    finally:
        os.close(fd)


def _identity(value):
    return dict(dev=value.st_dev, ino=value.st_ino, size=value.st_size,
                mode=value.st_mode, uid=value.st_uid, nlink=value.st_nlink)


def _root_identity(value):
    return {key: _identity(value)[key] for key in ('dev', 'ino', 'mode', 'uid')}


def _regular(value, *, private=False):
    _require(stat.S_ISREG(value.st_mode), 'Expected S_IFREG, never a device/FIFO/socket')
    _require(value.st_uid == os.geteuid() and value.st_nlink == 1,
             'File must be owned and have exactly one hard link')
    if private:
        _require(stat.S_IMODE(value.st_mode) == 0o600, 'Pair file must have mode 0600')
    return _identity(value)


def _root(value):
    _require(stat.S_ISDIR(value.st_mode) and stat.S_IMODE(value.st_mode) == 0o700
             and value.st_uid == os.geteuid(), 'Pair root must be owned and mode 0700')
    return _root_identity(value)


@contextmanager
def _file(parent_fd, name, *, private=False):
    before = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
    _regular(before, private=private)
    fd = os.open(name, READ_FLAGS, dir_fd=parent_fd)
    try:
        _require(_regular(os.fstat(fd), private=private) == _identity(before),
                 'File changed while opening: ' + name)
        yield fd
        _require(_regular(os.fstat(fd), private=private) == _identity(before)
                 == _identity(os.stat(name, dir_fd=parent_fd, follow_symlinks=False)),
                 'File identity changed while reading: ' + name)
    finally:
        os.close(fd)


def _new_file(parent_fd, name):
    fd = os.open(name, CREATE_FLAGS, 0o600, dir_fd=parent_fd)
    try:
        os.fchmod(fd, 0o600)
        _regular(os.fstat(fd), private=True)
        return fd
    except BaseException:
        os.close(fd)
        raise


def _unique_object(items):
    result = {}
    for key, value in items:
        _require(key not in result, 'Duplicate JSON key: ' + key)
        result[key] = value
    return result


def _read_json(parent_fd, name, *, private=False):
    with _file(parent_fd, name, private=private) as fd:
        _require(os.fstat(fd).st_size <= JSON_LIMIT, 'JSON file exceeds size limit')
        with os.fdopen(os.dup(fd), 'rb') as stream:
            raw = stream.read(JSON_LIMIT + 1)
        _require(len(raw) <= JSON_LIMIT, 'JSON file exceeds size limit')
        value = json.loads(raw, object_pairs_hook=_unique_object)
        _require(isinstance(value, dict), 'JSON document must be an object')
        return value, hashlib.sha256(raw).hexdigest()


def _write_json(parent_fd, name, value):
    raw = (json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + '\n').encode('utf-8')
    _require(len(raw) <= JSON_LIMIT, 'Generated manifest exceeds size limit')
    fd = _new_file(parent_fd, name)
    try:
        remaining = memoryview(raw)
        while remaining:
            written = os.write(fd, remaining)
            _require(written > 0, 'Manifest write made no progress')
            remaining = remaining[written:]
        os.fsync(fd)
        os.lseek(fd, 0, os.SEEK_SET)
        with os.fdopen(os.dup(fd), 'rb') as stream:
            _require(stream.read(len(raw) + 1) == raw, 'Manifest readback differs')
        current = _regular(os.fstat(fd), private=True)
        _require(current['size'] == len(raw)
                 and current == _identity(os.stat(name, dir_fd=parent_fd, follow_symlinks=False)),
                 'Manifest identity changed during readback')
        os.fsync(parent_fd)
    finally:
        os.close(fd)


def _digest(path):
    path = _canonical(path)
    with _directory(path.parent) as parent_fd, _file(parent_fd, path.name) as fd:
        before = os.fstat(fd)
        digest = hashlib.sha256()
        with os.fdopen(os.dup(fd), 'rb') as stream:
            for chunk in iter(lambda: stream.read(MIB), b''):
                digest.update(chunk)
        after = os.fstat(fd)
        _require((before.st_mtime_ns, before.st_ctime_ns) == (after.st_mtime_ns, after.st_ctime_ns),
                 'Input changed during full SHA256: ' + str(path))
        return dict(path=str(path), sha256=digest.hexdigest(), **_regular(after))
def ap_probe_command():
    return [sys.executable,'-B',str(PRODUCT/'runtime/analysis/qemu-menu-probe.py'),
            '--initramfs','--load-ipc','--load-dmm','--sony-timers','--observe','--bootin','--bootall',
            '--seed-backup','--load-kikilog','--seed-power-on']


def _proc_record(pid,proc_root=Path('/proc')):
    _require(type(pid) is int and pid>1,'Expected a host process PID')
    proc=proc_root/str(pid)
    fields=(proc/'stat').read_text().rsplit(')',1)[1].split()
    _require(len(fields)>19 and fields[0] not in ('Z','X'),'Host process is not live')
    command=(proc/'cmdline').read_bytes();_require(command and command[-1:]==b'\0','Host process argv unavailable')
    exe_path=os.readlink(proc/'exe');exe_stat=(proc/'exe').stat();process_stat=proc.stat()
    _require(not exe_path.endswith(' (deleted)'),'Host process executable was deleted')
    return dict(pid=pid,start_ticks=fields[19],state=fields[0],uid=process_stat.st_uid,gid=process_stat.st_gid,
                command_sha256=hashlib.sha256(command).hexdigest(),exe_path=exe_path,
                exe_dev=exe_stat.st_dev,exe_ino=exe_stat.st_ino,exe_size=exe_stat.st_size,exe_mode=exe_stat.st_mode)


def _boot_id():
    value=Path('/proc/sys/kernel/random/boot_id').read_text().strip()
    _require(len(value)==36 and all(c in '0123456789abcdef-' for c in value),'Host boot identity unavailable')
    return value


def create_ap_admission_claim(directory,binary,command):
    directory=_canonical(directory);binary=_canonical(binary)
    _require(command==ap_probe_command(),'AP probe argv differs from the fixed original native route')
    admission=admit(directory,binary)
    owner=_proc_record(os.getpid())
    nonce=os.urandom(16).hex()
    claim=dict(schema='a7c2-native-ap-admission-v2',profile=PROFILE,pair=str(directory),owner_pid=os.getpid(),
               owner_start_ticks=owner['start_ticks'],host_boot_id=_boot_id(),command=command,
               command_sha256=hashlib.sha256(b'\0'.join(os.fsencode(x) for x in command)+b'\0').hexdigest(),
               run_nonce=nonce,binary_sha256=admission['binary']['sha256'],pair_admission=admission,
               created_ns=time.time_ns(),replay_allowed=False,coordinator_owns_pair_release=True)
    with _directory(directory) as fd:
        _root(os.fstat(fd));_write_json(fd,'ap-admission.claim',claim)
        actual,digest=_read_json(fd,'ap-admission.claim',private=True)
        _require(actual==claim,'AP claim readback differs')
    return claim,digest


def read_ap_admission_claim(directory):
    directory=_canonical(directory)
    with _directory(directory) as fd:return _read_json(fd,'ap-admission.claim',private=True)


def validate_ap_admission_claim(directory,binary,admission,claim=None):
    directory=_canonical(directory);binary=_canonical(binary)
    actual,claim_sha=read_ap_admission_claim(directory)
    if claim is not None:_require(actual==claim,'AP admission claim changed')
    owner=actual.get('owner_pid');command=actual.get('command');nonce=actual.get('run_nonce')
    _require(actual.get('schema')=='a7c2-native-ap-admission-v2' and actual.get('profile')==PROFILE and
             actual.get('pair')==str(directory) and type(owner) is int and owner==os.getpid() and
             type(command) is list and command==ap_probe_command() and type(nonce) is str and len(nonce)==32 and
             all(c in '0123456789abcdef' for c in nonce),'AP claim identity/schema differs')
    info=_proc_record(owner)
    _require(info['start_ticks']==actual.get('owner_start_ticks') and _boot_id()==actual.get('host_boot_id') and
             info['command_sha256']==actual.get('command_sha256'),'AP owner generation/argv differs from creation claim')
    _require(admission.get('binary',{}).get('path')==str(binary) and
             admission.get('binary',{}).get('sha256')==actual.get('binary_sha256') and
             actual.get('pair_admission')==admission,'AP pair/binary admission differs from claim')
    return actual,claim_sha


def write_ap_run_pointer(directory,run_directory):
    directory=_canonical(directory);run_directory=_canonical(run_directory)
    _require(run_directory.parent==directory/'ap-runs' and run_directory.name.startswith('run-'),
             'AP pointer must identify one direct child of this pair ap-runs')
    raw=(str(run_directory)+'\n').encode('utf-8')
    with _directory(directory) as parent:
        _root(os.fstat(parent));fd=_new_file(parent,'latest-ap-run.txt')
        try:
            view=memoryview(raw)
            while view:
                n=os.write(fd,view);_require(n>0,'AP pointer write made no progress');view=view[n:]
            os.fsync(fd);_require(os.pread(fd,len(raw)+1,0)==raw,'AP pointer readback differs');os.fsync(parent)
        finally:os.close(fd)
    return hashlib.sha256(raw).hexdigest()


def create_ap_control_lock(run_directory):
    run_directory=_canonical(run_directory)
    with _directory(run_directory) as parent:
        _root(os.fstat(parent));fd=_new_file(parent,'ap-cp-control.lock')
        info=_regular(os.fstat(fd),private=True);current=os.fstat(fd)
        info.update(mtime_ns=current.st_mtime_ns,ctime_ns=current.st_ctime_ns)
        os.fsync(fd);os.fsync(parent)
        return fd,info


def with_ap_control_lock(control_fd,action):
    _require(type(control_fd) is int and control_fd>=0 and callable(action),'Invalid AP QMP control-lock transaction')
    fcntl.flock(control_fd,fcntl.LOCK_EX)
    try:return action()
    finally:fcntl.flock(control_fd,fcntl.LOCK_UN)


def bind_ap_vm_owner(directory,run_directory,binary,admission,claim,claim_sha256,peer_pid,peer_uid,peer_gid,control_fd):
    directory=_canonical(directory);run_directory=_canonical(run_directory);binary=_canonical(binary)
    _require(run_directory.parent==directory/'ap-runs' and run_directory.name.startswith('run-'),
             'AP run must be one direct child of this pair ap-runs')
    _require(type(peer_pid) is int and peer_pid>1 and type(peer_uid) is int and type(peer_gid) is int,
             'Invalid QMP SO_PEERCRED')
    with _directory(directory) as pair_fd:
        pair_root=_root(os.fstat(pair_fd))
        current_claim,current_sha=_read_json(pair_fd,'ap-admission.claim',private=True)
        with _file(pair_fd,'latest-ap-run.txt',private=True) as pointer_fd:
            pointer=os.read(pointer_fd,4097)
    _require(current_claim==claim and current_sha==claim_sha256,'AP claim changed before VM owner publication')
    _require(pointer==str(run_directory).encode('utf-8')+b'\n','AP latest-run pointer differs from this exact run')
    owner=_proc_record(os.getpid());vm=_proc_record(peer_pid)
    _require(owner['pid']==claim['owner_pid'] and owner['start_ticks']==claim['owner_start_ticks'] and
             _boot_id()==claim['host_boot_id'] and owner['command_sha256']==claim['command_sha256'],
             'AP Python owner differs from creation-time claim')
    binary_record=_digest(binary)
    _require(admission['binary']==binary_record and claim['binary_sha256']==binary_record['sha256'],
             'AP QEMU binary identity changed')
    _require(peer_uid==os.getuid()==vm['uid'] and peer_gid==vm['gid'] and vm['exe_dev']==binary_record['dev'] and
             vm['exe_ino']==binary_record['ino'] and vm['exe_size']==binary_record['size'] and
             vm['state'] not in ('Z','X'),'QMP peer is not the admitted live QEMU binary')
    with _directory(run_directory) as run_fd:
        run_root=_root(os.fstat(run_fd))
        qmp=os.stat('qmp.sock',dir_fd=run_fd,follow_symlinks=False)
        _require(stat.S_ISSOCK(qmp.st_mode) and qmp.st_uid==os.getuid(),'Native AP QMP socket identity differs')
        lock_stat=os.fstat(control_fd);lock=_regular(lock_stat,private=True)
        lock.update(mtime_ns=lock_stat.st_mtime_ns,ctime_ns=lock_stat.st_ctime_ns)
        path_stat=os.stat('ap-cp-control.lock',dir_fd=run_fd,follow_symlinks=False)
        lock_path=_regular(path_stat,private=True)
        lock_path.update(mtime_ns=path_stat.st_mtime_ns,ctime_ns=path_stat.st_ctime_ns)
        _require(lock==lock_path,'AP quit/cont lock path differs from owner descriptor')
        pointer_sha=hashlib.sha256(pointer).hexdigest()
        record=dict(schema='a7c2-native-ap-vm-owner-v1',profile=PROFILE,pair=str(directory),ap_run=str(run_directory),
                    run_nonce=claim['run_nonce'],claim_sha256=claim_sha256,pair_root_identity=pair_root,
                    run_root_identity=run_root,owner_pid=owner['pid'],
                    owner_start_ticks=owner['start_ticks'],host_boot_id=claim['host_boot_id'],
                    owner_command_sha256=owner['command_sha256'],qemu_pid=vm['pid'],qemu_start_ticks=vm['start_ticks'],
                    qemu_uid=vm['uid'],qemu_gid=vm['gid'],qemu_exe_path=vm['exe_path'],qemu_exe_dev=vm['exe_dev'],
                    qemu_exe_ino=vm['exe_ino'],qemu_exe_size=vm['exe_size'],qemu_exe_mode=vm['exe_mode'],
                    qemu_command_sha256=vm['command_sha256'],binary_path=str(binary),binary_sha256=binary_record['sha256'],
                    qmp_peer=dict(pid=peer_pid,uid=peer_uid,gid=peer_gid,dev=qmp.st_dev,ino=qmp.st_ino),
                    control_lock=dict(path=str(run_directory/'ap-cp-control.lock'),**lock),
                    run_pointer_sha256=pointer_sha,ready=True)
        _write_json(run_fd,'native-ap-vm.json',record)
        written,digest=_read_json(run_fd,'native-ap-vm.json',private=True)
        _require(written==record,'Native AP VM owner record readback differs')
    return record,digest


def _relative(name):
    _require(isinstance(name, str) and name and '\0' not in name
             and not name.startswith('/') and all(part not in ('', '.', '..') for part in name.split('/')),
             'Unsafe stage source path: ' + repr(name))
    return name


def _stage_contract(binary, binary_sha256):
    """Preflight no-follow paths, then invoke the complete accepted stage checker."""
    tree = binary.parent.parent
    with _directory(binary.parent) as fd:
        proof, proof_sha = _read_json(fd, 'cp-notify-build.json')
    with _directory(tree) as fd:
        notify, notify_sha = _read_json(fd, 'cp-notify-stage.json')
        peripherals, peripherals_sha = _read_json(fd, 'cp-peripherals-stage.json')
    _require(proof.get('binary_sha256') == binary_sha256
             and proof.get('stage_sha256') == notify_sha
             and proof.get('peripherals_stage_sha256') == peripherals_sha,
             'Full binary/peripheral stage identity differs')
    _require(peripherals.get('native_link_profile') == PROFILE
             and peripherals.get('native_link_default_off') is True,
             'Peripheral stage lacks the default-off native link profile')
    outputs = {}
    for document in (notify, peripherals):
        for field in ('inherited_sources', 'outputs'):
            table = document.get(field)
            _require(isinstance(table, dict), 'Stage source table missing: ' + field)
            for name, digest in table.items():
                _relative(name)
                _require(isinstance(digest, str) and len(digest) == 64
                         and all(char in '0123456789abcdef' for char in digest), 'Invalid source SHA256')
                outputs[name] = digest
    for name, digest in outputs.items():
        _require(_digest(tree / name)['sha256'] == digest, 'Stage source identity differs: ' + name)
    checker = runpy.run_path(str(HERE / 'check-notify-qemu.py'))
    checked = checker['contract'](binary, require_peripherals=True)
    _require(isinstance(checked, dict) and checked == proof, 'Stage contract result differs')
    # The existing checker resolves paths itself; recheck its inputs after it returns.
    for path, digest in ((binary.parent / 'cp-notify-build.json', proof_sha),
                         (tree / 'cp-notify-stage.json', notify_sha),
                         (tree / 'cp-peripherals-stage.json', peripherals_sha)):
        _require(_digest(path)['sha256'] == digest, 'Stage receipt changed during admission')
    for name, digest in outputs.items():
        _require(_digest(tree / name)['sha256'] == digest, 'Stage source changed during admission: ' + name)
    return checked


def _binary_contract(binary):
    binary = _canonical(binary)
    _require(binary.name not in FILE_SIZES, 'A dynamic RAM file cannot be the QEMU binary')
    before = _digest(binary)
    stage = _stage_contract(binary, before['sha256'])
    _require(_digest(binary) == before, 'Binary identity changed during admission')
    return before, stage


def _space(parent_fd):
    result = dict(ram_logical_bytes=sum(FILE_SIZES.values()), log_budget_bytes=LOG_BUDGET,
                  reserve_bytes=RESERVE, available_bytes=None, fits=None)
    result['required_bytes'] = result['ram_logical_bytes'] + LOG_BUDGET + RESERVE
    try:
        space = os.fstatvfs(parent_fd)
        _require(isinstance(space.f_bavail, int) and space.f_bavail >= 0
                 and isinstance(space.f_frsize, int) and space.f_frsize > 0,
                 'Filesystem space cannot be determined')
        result['available_bytes'] = space.f_bavail * space.f_frsize
        result['fits'] = result['available_bytes'] >= result['required_bytes']
    except (OSError, ValueError, AttributeError, TypeError):
        pass
    return result


def _same_root_path(directory, identity):
    with _directory(directory) as fd:
        _require(_root(os.fstat(fd)) == identity, 'Pair root path identity changed')


def _verify_files(fd, files):
    _require(isinstance(files, dict) and set(files) == set(FILE_SIZES),
             'Manifest RAM names must be the exact fixed basenames')
    seen = set()
    for name, size in FILE_SIZES.items():
        with _file(fd, name, private=True) as ram_fd:
            current = _regular(os.fstat(ram_fd), private=True)
            _require(current['size'] == size and current == files[name],
                     'RAM file identity/geometry differs: ' + name)
            inode = (current['dev'], current['ino'])
            _require(inode not in seen, 'Local/peer RAM must use different inodes')
            seen.add(inode)


def _load(fd, directory):
    _require(FAILURE_MANIFEST not in os.listdir(fd), 'Pair has a retained failure manifest')
    manifest, _ = _read_json(fd, MANIFEST, private=True)
    _require(manifest.get('schema') == SCHEMA and manifest.get('profile') == PROFILE
             and manifest.get('status') == 'prepared', 'Unknown or unprepared native link manifest/profile')
    _require(manifest.get('directory') == str(directory)
             and manifest.get('root_identity') == _root(os.fstat(fd)), 'Pair root identity differs')
    for field in ('physical_hardware_verified', 'fullboot_verified', 'original_ap_consumed'):
        _require(manifest.get(field) is False, 'Host manifest cannot claim hardware/fullboot/AP consumption')
    _verify_files(fd, manifest.get('files'))
    _same_root_path(directory, manifest['root_identity'])
    return manifest


def prepare(directory, binary) -> dict:
    """Create a fresh sparse pair, retaining all partial files on failure."""
    with _validation():
        directory = _canonical(directory)
        _require(directory != Path('/'), 'Pair root must be a new child directory')
        with _directory(directory.parent) as parent_fd:
            os.mkdir(directory.name, 0o700, dir_fd=parent_fd)
            fd = os.open(directory.name, DIR_FLAGS, dir_fd=parent_fd)
        try:
            os.fchmod(fd, 0o700)
            identity = _root(os.fstat(fd))
            manifest = dict(schema=SCHEMA, profile=PROFILE, directory=str(directory), status='preparing',
                            root_identity=identity, binary=None, stage=None, files={}, storage={},
                            physical_hardware_verified=False, fullboot_verified=False, original_ap_consumed=False)
            try:
                _same_root_path(directory, identity)
                storage = manifest['storage'] = _space(fd)
                _require(storage['fits'] is True, 'Insufficient or unknown space for all logical RAM + logs + reserve')
                manifest['binary'], manifest['stage'] = _binary_contract(binary)
                for name, size in FILE_SIZES.items():
                    ram_fd = _new_file(fd, name)
                    try:
                        os.ftruncate(ram_fd, size)
                        os.fsync(ram_fd)
                        manifest['files'][name] = _regular(os.fstat(ram_fd), private=True)
                        _require(manifest['files'][name]['size'] == size, 'Sparse ftruncate readback differs: ' + name)
                    finally:
                        os.close(ram_fd)
                _verify_files(fd, manifest['files'])
                _same_root_path(directory, identity)
                storage['allocated_bytes_at_prepare'] = sum(
                    os.stat(name, dir_fd=fd, follow_symlinks=False).st_blocks * 512 for name in FILE_SIZES)
                manifest['status'] = 'prepared'
                _write_json(fd, MANIFEST, manifest)
                _require(_load(fd, directory) == manifest, 'Prepared manifest readback differs')
                return manifest
            except Exception as error:
                manifest['status'] = 'failed'
                manifest['error'] = repr(error)
                manifest['partial_files_retained'] = {}
                for name in (*FILE_SIZES, MANIFEST):
                    try:
                        value = os.stat(name, dir_fd=fd, follow_symlinks=False)
                        manifest['partial_files_retained'][name] = dict(
                            **_identity(value), allocated_bytes=value.st_blocks * 512)
                    except FileNotFoundError:
                        pass
                    except OSError as scan_error:
                        manifest['partial_files_retained'][name] = dict(inspect_error=repr(scan_error))
                manifest['cleanup'] = 'No files removed; parent owns lease and retention lifecycle'
                try:
                    _write_json(fd, FAILURE_MANIFEST, manifest)
                    detail = 'failure manifest retained: ' + str(directory / FAILURE_MANIFEST)
                except Exception as receipt_error:
                    detail = 'failure manifest write failed: ' + repr(receipt_error) + '; partial files retained in ' + str(directory)
                raise ValueError(str(error) + '; ' + detail) from error
        finally:
            os.close(fd)


def admit(directory, binary) -> dict:
    """Read-only admission; does not create a replay claim or mutate old evidence."""
    with _validation():
        directory = _canonical(directory)
        with _directory(directory) as fd:
            manifest = _load(fd, directory)
            binary = _canonical(binary)
            recorded_binary = manifest.get('binary')
            _require(isinstance(recorded_binary, dict) and recorded_binary.get('path') == str(binary),
                     'Manifest binary path differs')
            binary_identity, stage = _binary_contract(binary)
            _require(binary_identity == manifest.get('binary') and stage == manifest.get('stage'),
                     'Manifest binary/full stage identity differs')
            _verify_files(fd, manifest['files'])
            _same_root_path(directory, manifest['root_identity'])
            return manifest


def _side(side):
    _require(isinstance(side, str) and side in ('ap', 'cp'), 'Side must be ap or cp')


def ram_arguments(directory, side, *, sandbox=False) -> list[str]:
    """Return JSON -object arguments only; caller supplies machine memory-backend."""
    with _validation():
        _side(side)
        _require(type(sandbox) is bool, 'sandbox must be bool')
        directory = _canonical(directory)
        with _directory(directory) as fd:
            _load(fd, directory)
        root = Path('/native-link') if sandbox else directory
        if side == 'ap':
            views = [('native-local-ram', 'ap-ram.bin', AP_SIZE, 0),
                     ('native-peer-ram', 'cp-ram.bin', CP_SIZE, 0),
                     ('native-peer-oom', 'cp-oom.bin', OOM_SIZE, 0)]
        else:
            views = [('native-local-ram', 'cp-ram.bin', CP_SIZE, 0),
                     ('native-peer-ram', 'ap-ram.bin', CP_AP_VIEW_SIZE, AP_DDR_OFFSET),
                     ('native-local-oom', 'cp-oom.bin', OOM_SIZE, 0)]
        arguments = []
        for name, filename, size, offset in views:
            backend = {'qom-type': 'memory-backend-file', 'id': name, 'mem-path': str(root / filename),
                       'size': size, 'offset': offset, 'share': True, 'discard-data': False}
            arguments.extend(('-object', json.dumps(backend, separators=(',', ':'))))
        return arguments


def environment(side, directory) -> dict:
    """Explicit role environment delta, with no virtual sender or legacy test peer."""
    with _validation():
        _side(side)
        directory = _canonical(directory)
        with _directory(directory) as fd:
            _load(fd, directory)
        result = dict(QEMU_NATIVE_AP_CP_LINK=PROFILE, QEMU_NATIVE_LINK_DIR=str(directory),
                      QEMU_AP_CP_GPIO_LINES=GPIO_PROFILE, QEMU_AP_CP_GPIO_SIDE=side)
        if side == 'cp':
            result.update({'QEMU_CP_' + name: '1' for name in ('GIC', 'TIMERS', 'WATCHDOG', 'EDMA_GATE', 'UIPC_RAM')})
            result['QEMU_CP_BOOT_PERIPHERALS'] = PERIPHERALS_PROFILE
            result['QEMU_CP_KEY_GPIO_PROFILE'] = 'virtual-cp-key-gpio-v1'
        else:
            result.update(QEMU_SONY_TIMERS='1', QEMU_SONY_PCIDMA='1')
        return result


def _admit_environment(env, directory):
    _require(isinstance(env, Mapping) and all(isinstance(key, str) and isinstance(value, str)
                                            for key, value in env.items()), 'Environment must map strings to strings')
    required = dict(QEMU_NATIVE_AP_CP_LINK=PROFILE, QEMU_NATIVE_LINK_DIR=str(directory),
                    QEMU_AP_CP_GPIO_LINES=GPIO_PROFILE, QEMU_AP_CP_GPIO_SIDE='ap',
                    QEMU_SONY_TIMERS='1', QEMU_SONY_PCIDMA='1', QEMU_UI_LIVE='1', QEMU_TIMEOUT_SECONDS='0')
    for name, value in required.items():
        _require(env.get(name) == value, 'AP admission requires ' + name + '=' + value)
    legacy_presence = {'QEMU_CP_EDMA_DIRECT', 'QEMU_CP_GPIO18_PROFILE', 'QEMU_SONY_ATU_TEST',
                       'QEMU_SONY_PCIDMA_TEST', 'QEMU_SONY_PCIE_PEER_TEST'}
    for name, value in env.items():
        _require(name not in legacy_presence, 'Legacy peer/direct DMA variable must be absent: ' + name)
        if name == 'QEMU_NATIVE_P1_SPI_COMPONENT':
            _require(value == 'virtual-p1-pl022-component-v1', 'Unknown P1 SPI component profile')
        if name.startswith(('QEMU_CP_', 'QEMU_AP_CP_')) and name not in required:
            raise ValueError('Unexpected CP/peer environment on AP side: ' + name)
        if name in ('QEMU_RAM_SESSION', 'QEMU_RAM_INCOMING', 'QEMU_WBI_RESUME',
                    'QEMU_USB_DEVICE', 'QEMU_SONY_USB_DEVICE'):
            _require(value in ('', '0'), 'RAM restore/session or USB device conflicts: ' + name)
        elif name.startswith(('QEMU_RAM_', 'QEMU_WBI_')):
            _require(not value, 'Original RAM/WBI input conflicts: ' + name)
        if name.startswith(('A7C2_HOST_SD', 'A7C2_DIRECTORY_SD', 'QEMU_HOST_SD', 'QEMU_DIRECTORY_SD',
                            'QEMU_ORIGINAL_RAM', 'A7C2_ORIGINAL_RAM', 'QEMU_SONY_USB_')) and name != 'QEMU_SONY_USB_DEVICE':
            _require(not value, 'External storage/USB/original RAM input conflicts: ' + name)
        if name.startswith(('QEMU_SD_', 'QEMU_INCOMING', 'QEMU_MIGRATION', 'QEMU_MIGRATE', 'QEMU_LOADVM')):
            _require(not value, 'External SD or migration input conflicts: ' + name)
        if name in ('MENU_CP_EMULATION', 'A7C2_CP_EMULATION'):
            _require(not value, 'Retired CP emulation conflicts: ' + name)
        if any(token in name for token in ('VIRTUAL_CP', 'CP_SENDER', 'VPANEL', 'TRANSPORT_ERROR',
                                           'BB_READY_INJECT', 'BB_READY_LATE')):
            _require(value in ('', '0'), 'Virtual sender/Vpanel/transport error conflicts: ' + name)
        if name.endswith(('_ARGS', '_OPTIONS', '_MODULE')):
            _require('transport-errors' not in value, 'Transport-errors module/option conflicts: ' + name)
        if name.startswith('QEMU_') and ('TEST' in name or 'DIRECT_DMA' in name):
            raise ValueError('TEST peer/direct DMA variable must be absent: ' + name)


def admit_ap(directory, binary, memory_mib, env=None) -> dict:
    """AP shell preflight; caller owns the exclusive ap-admission.claim lifecycle."""
    with _validation():
        _require(type(memory_mib) is int and memory_mib == 24576, 'Native AP requires memory_mib == 24576')
        directory = _canonical(directory)
        _admit_environment(os.environ if env is None else env, directory)
        return admit(directory, binary)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    for name in ('prepare', 'admit-ap'):
        command = commands.add_parser(name)
        command.add_argument('directory')
        command.add_argument('--binary', required=True)
        if name == 'admit-ap':
            command.add_argument('--memory-mib', type=int, required=True)
    args = parser.parse_args(argv)
    try:
        result = (prepare(args.directory, args.binary) if args.command == 'prepare'
                  else admit_ap(args.directory, args.binary, args.memory_mib))
    except ValueError as error:
        print(json.dumps(dict(profile=PROFILE, admitted=False, error=str(error))), file=sys.stderr)
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == '__main__':
    sys.exit(main())
