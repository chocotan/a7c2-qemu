"""Bounded QEMU RAM migration for the original-init-cold product route.

This is QEMU migration, not execution of Sony's WBI loader. Capture and restore
use the same persistent disk lease and prove original AP input/LCD continuity.
"""
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import socket
import stat
import threading
import time


MAGIC = b'QEVM\x00\x00\x00\x03'
MAX_STREAM_BYTES = 5 * 1024 ** 3
ACTIVE = ('setup', 'active', 'device', 'wait-unplug')
IDENTITY_COMMAND = ("echo A7C2_RAM_ID_BEGIN; /bin/busybox cat /proc/sys/kernel/random/boot_id; "
                    "/bin/busybox cat /proc/uptime; echo A7C2_RAM_ID_END")


def receipt_path(stream):
    return Path(str(Path(stream).absolute()) + '.json')


def window_binary():
    from persistent_storage import PRODUCT, binary_environment, sha
    selected = os.environ.get('A7C2_RAM_QEMU')
    if selected:
        binary = Path(selected).absolute()
    else:
        registration = PRODUCT/'source/ram-state-build.json'
        if not registration.is_file() or registration.is_symlink():
            raise ValueError('请先运行 ./build-qemu.sh --stage-only --sony-device --ram-state')
        row = json.loads(registration.read_bytes(), object_pairs_hook=_object)
        if row.get('schema') != 'a7c2-product-ram-window-build-v1':
            raise ValueError('Unknown registered RAM build')
        binary = PRODUCT/row['binary']
    if (not binary.is_relative_to(PRODUCT/'source/build') or
            '..' in binary.parts or any(p.is_symlink() for p in (binary, *binary.parents))):
        raise ValueError('RAM window requires an ordinary product build')
    if not selected and row.get('binary_sha256') != sha(binary):
        raise ValueError('Registered RAM binary changed')
    binary_environment(binary, ram_state=True)
    return binary


def live_build(stream):
    """Restore the captured build; preparing a new RAM0 would change its identity."""
    from persistent_storage import ANALYSIS, sha
    stream = Path(stream).absolute()
    if stream.parent.parent != ANALYSIS/'menu-runs' or stream.name != 'ram.qevm':
        raise ValueError('Window RAM capture is outside the owned product runs')
    paths = [receipt_path(stream)]
    rows = []
    for index in range(2):
        path = paths[index]
        if any(p.is_symlink() for p in (path, *path.parents)):
            raise ValueError('Symlink in window RAM capture')
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
        with os.fdopen(fd, 'rb') as source:
            before = os.fstat(source.fileno())
            if (not stat.S_ISREG(before.st_mode) or before.st_uid != os.geteuid()
                    or not 0 < before.st_size <= 262144):
                raise ValueError('Invalid window RAM metadata')
            raw = source.read(262145)
            after = os.fstat(source.fileno())
        if ((before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns) !=
                (after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns)):
            raise ValueError('Window RAM metadata changed while reading')
        row = json.loads(raw, object_pairs_hook=_object); rows.append(row)
        if index == 0:
            if row.get('schema') != 'a7c2-original-ram-capture-v1':
                raise ValueError('Unknown window RAM capture')
            build = Path(row['build_result'])
            if (build.name != 'result.json' or build.parent.name != 'build'
                    or build.parents[2] != ANALYSIS/'menu-runs'
                    or any(p.is_symlink() for p in (build, *build.parents))):
                raise ValueError('Captured cold build is outside the owned runs')
            if sha(build) != row.get('build_result_sha256'):
                raise ValueError('Captured cold build changed')
            paths.append(build)
    return rows[1]


def hash_stream(stream):
    before = os.fstat(stream.fileno())
    if not stat.S_ISREG(before.st_mode) or not 8 < before.st_size <= MAX_STREAM_BYTES:
        raise ValueError('Invalid QEMU migration stream size/type')
    stream.seek(0)
    if stream.read(len(MAGIC)) != MAGIC:
        raise ValueError('Incomplete or unsupported QEMU migration stream')
    stream.seek(0)
    digest = hashlib.file_digest(stream, 'sha256').hexdigest()
    after = os.fstat(stream.fileno())
    if (before.st_size, before.st_mtime_ns, before.st_ctime_ns) != (after.st_size, after.st_mtime_ns, after.st_ctime_ns):
        raise ValueError('QEMU migration stream changed while reading')
    return {'bytes': before.st_size, 'sha256': digest}


def _copy(sock, stream, outgoing, errors):
    try:
        total = 0
        if outgoing:
            while data := sock.recv(1024 * 1024):
                total += len(data)
                if total > MAX_STREAM_BYTES:
                    raise ValueError('QEMU migration stream exceeds the bounded budget')
                stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        else:
            stream.seek(0)
            while data := stream.read(1024 * 1024):
                sock.sendall(data)
            sock.shutdown(socket.SHUT_WR)
    except Exception as error:
        errors.append(str(error))


def transfer(qmp, path, *, outgoing, timeout=300):
    """Run one actual fd: migration; getfd must use SCM_RIGHTS, never exec:."""
    if type(timeout) not in (int, float) or not 0 < timeout <= 1800:
        raise ValueError('Invalid RAM migration timeout')
    path = Path(path).absolute()
    if any(part.is_symlink() for part in (path, *path.parents)):
        raise ValueError('RAM migration path must not contain symlinks')
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    flags = os.O_RDWR | os.O_CREAT | os.O_EXCL if outgoing else os.O_RDONLY
    fd = os.open(path, flags | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'r+b' if outgoing else 'rb') as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid() or info.st_mode & 0o077:
            raise ValueError('RAM stream must be an owned private regular file')
        local, remote = socket.socketpair()
        worker = None
        name = 'a7c2-ram-' + secrets.token_hex(12)
        receipt = {'direction': 'outgoing' if outgoing else 'incoming', 'qmp': []}
        if not outgoing:
            receipt['stream'] = hash_stream(stream)
        try:
            local.settimeout(timeout)
            remote.settimeout(timeout)
            qmp('getfd', {'fdname': name}, pass_fd=remote.fileno())
            remote.close()
            errors = []
            worker = threading.Thread(target=_copy, args=(local, stream, outgoing, errors))
            worker.start()
            command = 'migrate' if outgoing else 'migrate-incoming'
            arguments = {'uri': 'fd:' + name}
            if not outgoing:
                arguments['exit-on-error'] = False
            qmp(command, arguments)
            deadline = time.monotonic() + timeout
            while True:
                reply = qmp('query-migrate')
                result = reply['return']
                status = result.get('status')
                if not receipt['qmp'] or receipt['qmp'][-1].get('status') != status:
                    receipt['qmp'].append(result)
                if status == 'completed':
                    break
                if status not in ACTIVE:
                    raise RuntimeError('RAM migration did not complete: ' + repr(result))
                if time.monotonic() >= deadline:
                    raise TimeoutError('RAM migration completion timeout')
                time.sleep(.02)
            worker.join(max(0, deadline - time.monotonic()))
            if worker.is_alive() or errors:
                raise RuntimeError('Incomplete RAM stream: ' + repr(errors))
            receipt['stream'] = hash_stream(stream)
            expected = 'postmigrate' if outgoing else 'paused'
            status = qmp('query-status')['return']
            if status.get('status') != expected or status.get('running') is not False:
                raise RuntimeError('Unexpected post-migration status: ' + repr(status))
            receipt.update(completed=True, status=status['status'],
                           sony_wbi_resume_executed=False, full_boot_verified=False)
            return receipt
        except BaseException:
            if outgoing:
                try:
                    current = qmp('query-migrate')['return']
                    if current.get('status') in ACTIVE:
                        qmp('migrate_cancel')
                        receipt['cancelled'] = True
                except Exception as error:
                    receipt['cancel_error'] = str(error)
            try:
                local.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            if worker is not None:
                worker.join(5)
                if worker.is_alive():
                    receipt['stream_worker_unjoined'] = True
            raise
        finally:
            local.close()
            remote.close()


def _identity(raw):
    match = re.search(rb'A7C2_RAM_ID_BEGIN\r?\n(.*?)\r?\nA7C2_RAM_ID_END', raw, re.S)
    if not match:
        raise ValueError('Guest RAM identity response is incomplete')
    body = match.group(1)
    boot = re.search(rb'(?m)^([0-9a-f-]{36})\r?$', body)
    uptime = re.search(rb'(?m)^([0-9]+\.[0-9]+) [0-9]+\.[0-9]+\r?$', body)
    if not boot or not uptime:
        raise ValueError('Guest boot_id/uptime missing')
    return {'boot_id': boot.group(1).decode(), 'uptime_seconds': float(uptime.group(1))}


def _thaw(serial, runtime):
    parameter = '/sys/module/sony_persistent_flash/parameters/quiesce'
    raw = serial('( echo 0 > ' + parameter + ' && echo A7C2_RAM_THAW_BEGIN && /bin/busybox cat ' + parameter + ' && echo A7C2_RAM_THAW_END )')
    (runtime/'ram-restored-thaw.raw').write_bytes(raw)
    match = re.search(rb'A7C2_RAM_THAW_BEGIN\r?\n([0-9]+) ([0-9]+)\r?\n(?:[ \t]*\r?\n)*A7C2_RAM_THAW_END', raw)
    if not match or match.groups() != (b'0', b'0'):
        raise ValueError('Restored guest did not thaw all nineteen internal volumes')
    return {'state': 0, 'count': 0, 'raw_sha256': hashlib.sha256(raw).hexdigest()}


def _disk(leased):
    import persistent_disk as disk
    info = os.fstat(leased['fd'])
    return {'dev': info.st_dev, 'ino': info.st_ino, 'bytes': info.st_size,
            'mtime_ns': info.st_mtime_ns, 'ctime_ns': info.st_ctime_ns,
            'sha256': disk.hashed(leased['fd'])}


def _lcd(qmp, runtime, name):
    from PIL import Image
    qmp('screendump', {'filename': '/out/' + name + '.ppm'})
    with Image.open(runtime/(name + '.ppm')) as opened:
        if opened.size != (640, 480):
            raise ValueError('Restored LCD geometry differs')
        image = opened.convert('RGB')
    image.save(runtime/(name + '.png'))
    return {'image': image, 'sha256': hashlib.sha256(image.tobytes()).hexdigest(),
            'colors': len(image.getcolors(640 * 480) or [])}


def capture(qmp, stream, runtime, leased, serial, built, qemu_sha256):
    """Pause a saved source, preserve RAM and bind the unchanged whole disk."""
    from original_cold_boot import sha
    runtime = Path(runtime)
    identity_raw = serial(IDENTITY_COMMAND)
    (runtime/'ram-source-identity.raw').write_bytes(identity_raw)
    identity = _identity(identity_raw)
    source_lcd = _lcd(qmp, runtime, 'ram-source')
    qmp('stop')
    stopped = qmp('query-status')['return']
    if stopped.get('status') != 'paused' or stopped.get('running') is not False:
        raise ValueError('Source did not pause before RAM capture')
    os.fdatasync(leased['fd'])
    before = _disk(leased)
    migration = transfer(qmp, stream, outgoing=True)
    after = _disk(leased)
    if before != after:
        raise ValueError('Persistent disk changed across source RAM capture')
    return {'schema': 'a7c2-original-ram-capture-v1', 'stream': str(Path(stream).absolute()),
            'stream_bytes': migration['stream']['bytes'], 'stream_sha256': migration['stream']['sha256'],
            'source_identity': identity, 'source_lcd_sha256': source_lcd['sha256'],
            'disk': after, 'instance': str(Path(leased['path']).absolute()),
            'ram0_sha256': built['ram0_sha256'], 'kernel_sha256': built['kernel_sha256'],
            'qemu_sha256': qemu_sha256, 'migration': migration,
            'original_ap_retained_verified': False, 'sony_wbi_resume_executed': False,
            'full_boot_verified': False, 'capture_verified': False}


def _object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('Duplicate RAM receipt key')
        result[key] = value
    return result


def load_capture(stream, leased, built, qemu_sha256):
    """Validate the private capture receipt and current stream before target launch."""
    stream = Path(stream).absolute()
    receipt = receipt_path(stream)
    if any(part.is_symlink() for part in (stream, receipt, *stream.parents)):
        raise ValueError('RAM capture path must not contain symlinks')
    info = receipt.stat()
    if not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid() or not 0 < info.st_size <= 262144:
        raise ValueError('Invalid RAM capture receipt')
    with receipt.open('rb') as source:
        contract = json.load(source, object_pairs_hook=_object)
    if contract.get('schema') != 'a7c2-original-ram-capture-v1':
        raise ValueError('Unknown RAM capture receipt')
    if contract.get('migration', {}).get('completed') is not True:
        raise ValueError('RAM capture migration did not complete')
    for key in ('original_ap_retained_verified', 'sony_wbi_resume_executed', 'full_boot_verified', 'capture_verified'):
        if contract.get(key) is not False:
            raise ValueError('Capture receipt contains an unearned claim')
    with stream.open('rb') as source:
        actual = hash_stream(source)
    if (actual['bytes'] != contract.get('stream_bytes') or
            actual['sha256'] != contract.get('stream_sha256')):
        raise ValueError('RAM stream differs from capture receipt')
    if contract.get('disk') != _disk(leased):
        raise ValueError('Target is not the unchanged captured persistent disk')
    if (contract.get('instance') != str(Path(leased['path']).absolute()) or
            contract.get('ram0_sha256') != built['ram0_sha256'] or
            contract.get('kernel_sha256') != built['kernel_sha256'] or
            contract.get('qemu_sha256') != qemu_sha256):
        raise ValueError('RAM source/target guest or QEMU identity differs')
    return contract


def restore(qmp, stream, leased, contract):
    if contract['disk'] != _disk(leased):
        raise ValueError('Disk changed before incoming RAM restore')
    migration = transfer(qmp, stream, outgoing=False)
    if contract['disk'] != _disk(leased):
        raise ValueError('Disk changed across incoming RAM restore')
    qmp('cont')
    running = qmp('query-status')['return']
    if running.get('status') != 'running' or running.get('running') is not True:
        raise ValueError('Target did not continue the restored guest')
    return {'migration': migration, 'continued': running,
            'disk_before_sha256': contract['disk']['sha256'],
            'disk_after_sha256': contract['disk']['sha256'],
            'sony_wbi_resume_executed': False, 'full_boot_verified': False}


def _input_edges(console, offset):
    text = console.read_bytes()[offset:]
    pressed = b'words=[0x1ab,0,0x1,0,0,0,0,0]'
    released = b'words=[0x1ab,0,0,0,0,0,0,0]'
    return text.count(pressed), text.count(released)


def _settled_menu(qmp, process, runtime, *, menu, previous, offset, timeout=30):
    from original_cold_boot import original_menu_pixels
    deadline = time.monotonic() + timeout
    last = None
    while True:
        frame = _lcd(qmp, runtime, 'ram-restored-menu' if menu else 'ram-restored-shooting')
        changed = frame['sha256'] != previous
        content = original_menu_pixels(frame['image']) if menu else frame['colors'] > 5 and not original_menu_pixels(frame['image'])
        pressed, released = _input_edges(runtime/'console.log', offset)
        if changed and content and pressed and released and frame['sha256'] == last:
            return frame, {'press': pressed, 'release': released}
        if process.poll() is not None or time.monotonic() >= deadline:
            raise TimeoutError('Restored original MENU/LCD did not settle')
        last = frame['sha256']
        time.sleep(.1)


def verify_restored(qmp, process, runtime, serial, contract):
    """Require the same guest and fresh original MENU/HUD content after cont."""
    from menu_live import key_command
    runtime = Path(runtime)
    thawed = _thaw(serial, runtime)
    raw = serial(IDENTITY_COMMAND)
    (runtime/'ram-restored-identity.raw').write_bytes(raw)
    identity = _identity(raw)
    if identity['boot_id'] != contract['source_identity']['boot_id']:
        raise ValueError('Target boot_id differs: this is not the captured guest')
    if identity['uptime_seconds'] < contract['source_identity']['uptime_seconds']:
        raise ValueError('Guest uptime regressed across RAM restore')
    initial = _lcd(qmp, runtime, 'ram-restored-initial')
    if initial['colors'] <= 5:
        raise ValueError('Restored original LCD has no meaningful content')
    console = runtime/'console.log'
    if any(token in console.read_bytes() for token in (b'PRODUCT_COLD_BEFORE_ORIGINAL_INIT', b'PRODUCT_COLD_BOOTIN pid=')):
        raise ValueError('Target repeated the original cold boot instead of restoring RAM')
    from original_cold_boot import original_menu_pixels
    source_menu_open = original_menu_pixels(initial['image'])
    proofs = []
    for menu in (not source_menu_open, source_menu_open):
        offset = console.stat().st_size
        raw = serial(key_command('MENU', True))
        (runtime/('ram-restored-menu-input.raw' if menu else 'ram-restored-menu-return-input.raw')).write_bytes(raw)
        previous = proofs[-1]['lcd_sha256'] if proofs else initial['sha256']
        frame, edges = _settled_menu(qmp, process, runtime, menu=menu, previous=previous, offset=offset)
        proofs.append({'menu': menu, 'lcd_sha256': frame['sha256'], 'input_edges': edges})
    return {'original_ap_retained_verified': True,
            'new_original_menu_and_shooting_pixels_verified': True,
            'same_boot_id': True, 'uptime_seconds': identity['uptime_seconds'],
            'source_lcd_sha256': contract['source_lcd_sha256'],
            'restored_initial_lcd_sha256': initial['sha256'],
            'source_lcd_byte_identical': initial['sha256'] == contract['source_lcd_sha256'],
            'cold_boot_repeated': False, 'menu_proof': proofs, 'storage_thaw': thawed,
            'source_menu_open': source_menu_open, 'restored_scene_matches_source': True,
            'sony_wbi_resume_executed': False, 'full_boot_verified': False,
            'capture_verified': False}
