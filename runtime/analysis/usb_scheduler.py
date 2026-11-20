"""Opt-in, read-only original AP scheduler observations; no MSC state inference."""
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import struct
import subprocess
import secrets
import time

APP_SHA = '2ea02f7ecbc5bb917316fe8ef4ce5ffd87eb66efaae78ba2ce11420552df539b'
EXE_SHA = '5171f576d8b76cfbf15581389183b390c445bd6ff9dd97fd6668c5f64e77dc91'
BINARY = 'usb-sender-snapshot'
RECEIPT = 'usb-scheduler-build.json'
TOOL_OUTPUT_LIMIT = 4*1024**2
SERIAL_LIMIT = 8*1024**2
RUNTIME_BLOCK_REASON = ('MSC scheduler runtime blocked: no verified persistent disk owner '
                        'and serial-desynchronization recovery; no VM launch permitted')


def runtime_preflight(environment):
    if enabled(environment):
        raise RuntimeError(RUNTIME_BLOCK_REASON)


def require_runtime_owner():
    # No opt-in override: only a separately reviewed owner implementation can remove this gate.
    raise RuntimeError(RUNTIME_BLOCK_REASON)


class SerialBoundaryLost(RuntimeError):
    def __init__(self, message, raw):
        super().__init__(message)
        self.raw = raw


def _completion(raw, marker):
    """Validate every marker at the observed EOF; partial lines must finish first."""
    data = raw.replace(b'\r\n', b'\n')
    prefix = b'MSC_SCHED_DONE_'
    expected = marker.encode('ascii')+b':0'
    count = 0
    for match in re.finditer(re.escape(prefix), data):
        start = match.start()
        if start and data[start-1] != 10:
            raise RuntimeError('Scheduler completion is not a complete standalone record')
        end = data.find(b'\n', start)
        if end < 0:
            if not expected.startswith(data[start:]):
                raise RuntimeError('Malformed or foreign scheduler completion')
            return False
        if data[start:end] != expected:
            raise RuntimeError('Malformed, foreign or failed scheduler completion')
        count += 1
        if count > 1:
            raise RuntimeError('Duplicated scheduler completion')
    # Do not commit a preceding valid record while another line/prefix is unfinished.
    return count == 1 and data.endswith(b'\n')


class SchedulerSerial:
    """Dedicated non-rotating console reader; never retries an uncertain transaction."""
    def __init__(self, process, console, timeout=180):
        self.process, self.console, self.timeout = process, Path(console), timeout
        self.poisoned = False

    def __call__(self, command):
        from menu_live import FirmwareMonitor
        from console_wakeup import ConsoleWakeup
        if self.poisoned or getattr(self.process, '_menu_serial_desynchronized', False):
            raise SerialBoundaryLost('Serial boundary already lost; no further guest commands', b'')
        if getattr(self.process, '_menu_qmp_desynchronized', False):
            raise RuntimeError('QMP boundary already lost; no further guest commands')
        marker = 'MSC_SCHED_DONE_'+secrets.token_hex(12)
        # Split the literal so a tty echo cannot masquerade as a completion record.
        wire = (command+"; rc=$?; printf '\\nMSC_SCHED_''DONE_"+marker[len('MSC_SCHED_DONE_'):]+":%s\\n' \"$rc\"\n").encode('ascii')
        if any(len(line) > 1000 for line in wire.split(b'\n')):
            raise ValueError('Scheduler physical command line exceeds 1000 bytes')
        data = bytearray()
        sent = False
        transport = getattr(self.process, '_app_input_transport', None)
        if transport is not None:
            transport.pause()
        try:
            monitor = FirmwareMonitor(self.console)
            monitor.check()
            with ConsoleWakeup(self.console) as wakeup, self.console.open('rb') as reader:
                reader.seek(0, 2)
                # A short write or flush error is also an unknown guest execution state.
                sent = True
                if self.process.stdin.write(wire) != len(wire):
                    raise RuntimeError('Partial scheduler command write')
                self.process.stdin.flush()
                deadline = time.monotonic()+self.timeout
                while time.monotonic() < deadline:
                    monitor.check()
                    # Drain to this read's EOF before accepting any completion in a chunk.
                    while True:
                        chunk = reader.read(min(65536, SERIAL_LIMIT+1-len(data)))
                        if not chunk:
                            break
                        data.extend(chunk)
                        if len(data) > SERIAL_LIMIT:
                            raise RuntimeError('Scheduler serial output exceeds 8 MiB; boundary unknown')
                    if _completion(bytes(data), marker):
                        return bytes(data)
                    if self.process.poll() is not None:
                        raise RuntimeError('Scheduler VM exited before command completion')
                    wakeup.wait(min(.05, max(0, deadline-time.monotonic())))
                raise TimeoutError('Scheduler command completion not observed')
        except BaseException as error:
            if not sent:
                raise
            self.poisoned = True
            self.process._menu_serial_desynchronized = True
            self.process._msc_scheduler_owner_required = True
            # Console is append-only here, never rotated, truncated, retried or cleaned up.
            raise SerialBoundaryLost(type(error).__name__+': '+str(error), bytes(data)) from error


def enabled(environment):
    value = environment.get('A7C2_USB_MSC_SCHEDULER')
    if value is None:
        return False
    from sony_usb_device import selected
    if value != '1' or environment.get('A7C2_USB_MSC') != '1' or not selected(environment) or environment.get('A7C2_USB_SENSER') is not None:
        raise ValueError('Scheduler requires explicit 1 and the exclusive original MSC profile')
    return True


def _reserve(path):
    return os.open(path, os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600)


def _write_readback(fd, path, content):
    before = os.fstat(fd)
    if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1 or before.st_uid != os.geteuid() or before.st_size != 0:
        raise ValueError('Scheduler output reservation changed')
    with os.fdopen(fd, 'wb', closefd=False) as stream:
        stream.write(content)
        stream.flush()
        os.fsync(fd)
    after, linked = os.fstat(fd), Path(path).lstat()
    if (not stat.S_ISREG(linked.st_mode) or after.st_dev != linked.st_dev or after.st_ino != linked.st_ino or
            after.st_nlink != 1 or after.st_size != len(content) or os.pread(fd, len(content)+1, 0) != content):
        raise ValueError('Scheduler output identity/readback differs: '+str(path))


def _exclusive(path, content):
    fd = _reserve(path)
    try:
        _write_readback(fd, path, content)
    finally:
        os.close(fd)


def _json(path, value):
    _exclusive(path, (json.dumps(value, indent=2, allow_nan=False)+'\n').encode())


def _read_regular(path):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK)
    try:
        before = os.fstat(fd)
        if not stat.S_ISREG(before.st_mode) or before.st_mode & 0o022 or before.st_size > 16*1024**2:
            raise ValueError('Unsafe scheduler build input: '+str(path))
        with os.fdopen(fd, 'rb', closefd=False) as stream:
            data = stream.read(16*1024**2+1)
        after = os.fstat(fd)
        identity = lambda s: (s.st_dev, s.st_ino, s.st_size, s.st_mode, s.st_uid, s.st_mtime_ns, s.st_ctime_ns)
        if len(data) != before.st_size or identity(before) != identity(after):
            raise ValueError('Scheduler input changed during read')
        return data
    finally:
        os.close(fd)


def static_aarch64(data):
    if len(data) < 64 or data[:7] != b'\x7fELF\x02\x01\x01':
        raise ValueError('Scheduler output is not ELF64 little-endian')
    kind, machine = struct.unpack_from('<HH', data, 16)
    offset = struct.unpack_from('<Q', data, 32)[0]
    size, count = struct.unpack_from('<HH', data, 54)
    if kind != 2 or machine != 183 or size != 56 or not count or count > 128 or offset+size*count > len(data):
        raise ValueError('Scheduler requires a real AArch64 static executable')
    headers = [struct.unpack_from('<IIQQQQQQ', data, offset+i*size) for i in range(count)]
    if any(h[0] in (2, 3) for h in headers) or not any(h[0] == 1 and h[1] & 1 for h in headers):
        raise ValueError('Scheduler output has an interpreter/dynamic loader or no executable load')


def prepare(environment, payload, *, private_inputs=None):
    if not enabled(environment):
        return {}
    from sony_usb_device import PRODUCT, sealed_snapshot, prepare_private_libraries, private_tool_environment
    payload = Path(payload)
    directory = payload.lstat()
    if not stat.S_ISDIR(directory.st_mode) or directory.st_uid != os.geteuid() or directory.st_mode & 0o022 or any(p.is_symlink() for p in (payload, *payload.parents)):
        raise ValueError('Scheduler build requires an owned ordinary payload directory')
    if private_inputs is None:
        private_inputs = prepare_private_libraries(payload)
    source = PRODUCT/'source/usb-device/usb-sender-snapshot.c'
    content = _read_regular(source)
    source_sha = hashlib.sha256(content).hexdigest()
    compiler = shutil.which('aarch64-linux-gnu-gcc')
    if not compiler:
        raise RuntimeError('Real AArch64 static compiler is unavailable; scheduler remains blocked')
    compiler = Path(compiler).resolve(strict=True)
    compiler_before = _read_regular(compiler)
    target = payload/BINARY
    log = payload/'usb-scheduler-build.log'
    target_fd = _reserve(target)
    try:
        log_fd = _reserve(log)
        try:
            descriptor = sealed_snapshot(content, 'a7c2-msc-scheduler-source')
            command = [str(compiler), '-static', '-std=c11', '-O2', '-pipe', '-Wall', '-Wextra',
                       '-Werror', '-Wno-misleading-indentation', '-fno-omit-frame-pointer',
                       '-DSNAPSHOT_SOURCE_SHA256="'+source_sha+'"', '-x', 'c',
                       '/proc/self/fd/'+str(descriptor), '-o', '/proc/self/fd/'+str(target_fd)]
            try:
                _json(payload/'usb-scheduler-build-plan.json', dict(command=command, source_sha256=source_sha,
                      compiler_sha256=hashlib.sha256(compiler_before).hexdigest(), guest_executed=False))
                with private_tool_environment(private_inputs) as (environment, temp_fd):
                    tool_tmpdir = environment['TMPDIR']
                    temporary = os.fstat(temp_fd)
                    tool_tmp_identity = dict(device=temporary.st_dev, inode=temporary.st_ino,
                                             path=str(private_inputs[0]/'tool-tmp'))
                    checked = subprocess.run(command, capture_output=True,
                                             pass_fds=(descriptor, target_fd, temp_fd),
                                             env={**environment, 'LC_ALL': 'C'})
            except BaseException as error:
                _write_readback(log_fd, log, (type(error).__name__+': '+str(error)+'\n').encode())
                raise
            finally:
                os.close(descriptor)
            build_log = checked.stdout+checked.stderr
            _write_readback(log_fd, log, build_log)
            _json(payload/'usb-scheduler-build-command.json', dict(returncode=checked.returncode,
                  log_sha256=hashlib.sha256(build_log).hexdigest(), command=command))
            if checked.returncode:
                raise RuntimeError('Scheduler static cross-build failed; original output preserved')
            output = os.fstat(target_fd)
            linked = target.lstat()
            if (not stat.S_ISREG(linked.st_mode) or linked.st_dev != output.st_dev or linked.st_ino != output.st_ino or
                    output.st_uid != os.geteuid() or output.st_nlink != 1 or not 0 < output.st_size <= 16*1024**2):
                raise ValueError('Scheduler compiler output reservation changed')
            binary = os.pread(target_fd, output.st_size+1, 0)
            if len(binary) != output.st_size or _read_regular(target) != binary:
                raise ValueError('Scheduler compiled binary readback differs')
            static_aarch64(binary)
            os.fchmod(target_fd, 0o755)
        finally:
            os.close(log_fd)
    finally:
        os.close(target_fd)
    if _read_regular(source) != content or _read_regular(compiler) != compiler_before:
        raise ValueError('Scheduler source or compiler identity changed during compilation')
    receipt = dict(schema='a7c2-original-ap-scheduler-build-v1', source_sha256=source_sha,
                   compiler=str(compiler), compiler_sha256=hashlib.sha256(compiler_before).hexdigest(),
                   tool_tmpdir=tool_tmpdir, tool_tmp_identity=tool_tmp_identity,
                   command=command, binary_sha256=hashlib.sha256(binary).hexdigest(),
                   binary_bytes=len(binary), build_log_sha256=hashlib.sha256(build_log).hexdigest(),
                   app_sha256=APP_SHA, exe_sha256=EXE_SHA, static_aarch64_verified=True,
                   guest_executed=False, read_only=True)
    _json(payload/RECEIPT, receipt)
    return {BINARY: target, RECEIPT: payload/RECEIPT}


def load_contract(built):
    payload = Path(built['ram0']).parent/'payload'
    for name in (BINARY, RECEIPT):
        expected = built['helper_sources'][name]
        data = _read_regular(payload/name)
        if len(data) != expected['bytes'] or hashlib.sha256(data).hexdigest() != expected['sha256']:
            raise ValueError('Prepared scheduler helper differs: '+name)
    receipt = json.loads(_read_regular(payload/RECEIPT))
    if (receipt.get('schema') != 'a7c2-original-ap-scheduler-build-v1' or
            receipt.get('binary_sha256') != built['helper_sources'][BINARY]['sha256'] or
            receipt.get('app_sha256') != APP_SHA or receipt.get('exe_sha256') != EXE_SHA or
            receipt.get('static_aarch64_verified') is not True or
            re.fullmatch('[0-9a-f]{64}', receipt.get('source_sha256', '')) is None):
        raise ValueError('Scheduler build receipt identity differs')
    return receipt


def parse(raw, phase, contract, previous=None):
    if len(raw) > SERIAL_LIMIT:
        raise ValueError('Scheduler serial output exceeds the host budget; incomplete')
    text = raw.decode('utf-8', errors='strict').replace('\r', '')
    records = [line for line in text.splitlines()
               if line.startswith(('SNAPSHOT_', 'PRODUCT_MSC_SCHEDULER_RC='))]
    if sum(len(line.encode('utf-8'))+1 for line in records if line.startswith('SNAPSHOT_')) > TOOL_OUTPUT_LIMIT:
        raise ValueError('Scheduler tool output exceeds 4 MiB; incomplete')
    position = 0

    def take(kind, keys):
        nonlocal position
        if position >= len(records) or not records[position].startswith('SNAPSHOT_'+kind+' '):
            raise ValueError('Missing, duplicated or reordered scheduler record: '+kind)
        line = records[position][len('SNAPSHOT_'+kind+' '):]
        position += 1
        words = line.split(' ')
        pairs = [word.split('=', 1) for word in words]
        if (any(len(pair) != 2 or not pair[1] for pair in pairs) or
                [pair[0] for pair in pairs] != keys.split()):
            raise ValueError('Invalid scheduler fields: '+kind)
        return dict(pairs)

    def number(value):
        if re.fullmatch(r'(?:0x[0-9a-f]+|[0-9]+)', value) is None:
            raise ValueError('Invalid scheduler integer')
        return int(value, 16 if value.startswith('0x') else 10)

    def chunks(kind, identifier, size):
        result = bytearray()
        while len(result) < size:
            item = take(kind, 'id offset bytes hex')
            expected_size = min(64, size-len(result))
            if (number(item['id']) != identifier or number(item['offset']) != len(result) or
                    number(item['bytes']) != expected_size or
                    re.fullmatch('[0-9a-f]{'+str(expected_size*2)+'}', item['hex']) is None):
                raise ValueError('Scheduler raw evidence missing, duplicated or reordered: '+kind)
            result.extend(bytes.fromhex(item['hex']))
        return result

    start = take('BEGIN', 'phase pid start base source_sha256 app_sha256 exe_sha256 monotonic')
    if (start['phase'] != phase or start['source_sha256'] != contract['source_sha256'] or
            start['app_sha256'] != APP_SHA or start['exe_sha256'] != EXE_SHA or
            not start['pid'].isdigit() or number(start['pid']) < 2 or
            not start['start'].isdigit() or number(start['start']) < 1 or
            re.fullmatch('0x[0-9a-f]+', start['base']) is None or
            re.fullmatch(r'[0-9]+\.[0-9]+', start['monotonic']) is None):
        raise ValueError('Scheduler source/AP/process identity differs')
    if previous and any(start[key] != previous[key] for key in ('pid', 'start', 'base')):
        raise ValueError('AP process generation differs across original ENTER')
    base = number(start['base'])
    maps = take('MAPS', 'sha256 bytes device inode')
    maps_size = number(maps['bytes'])
    if not 0 < maps_size < 1024**2:
        raise ValueError('Scheduler maps exceed the observation bound')
    recovered = chunks('MAPS_BYTES', 0, maps_size)
    if hashlib.sha256(recovered).hexdigest() != maps['sha256']:
        raise ValueError('Scheduler maps raw content digest differs')
    if re.fullmatch('[0-9]+:[0-9]+', maps['device']) is None or number(maps['inode']) < 1:
        raise ValueError('Invalid scheduler mapped file identity')
    header = take('SCHED_HEADER', 'base first last pending active no_lock')
    pending, active = number(header['pending']), number(header['active'])
    head = base+0x910a108+0x310+6*0x90+0x10
    if number(header['base']) != base or header['no_lock'] != '1' or not 0 <= pending <= 256:
        raise ValueError('Invalid scheduler header/count')
    node, last = number(header['first']), number(header['last'])
    previous_node = head
    if pending == 0 and (node != head or last != head):
        raise ValueError('Empty scheduler list does not close')

    def scheduled(index, object_address):
        readable = take('SCHEDULED_READ', 'index object_readable control_readable run_readable token_readable')
        if number(readable['index']) != index or any(readable[k] != '1' for k in
                ('object_readable', 'control_readable', 'run_readable', 'token_readable')):
            raise ValueError('Pending/active reads incomplete')
        item = take('SCHEDULED', 'role index object control id token run stable msc_run')
        if (number(item['index']) != index or item['role'] != ('pending' if index else 'active') or
                number(item['object']) != object_address or not object_address or item['stable'] != '1'):
            raise ValueError('Pending/active scheduler identity differs')
        vtable, control_address = struct.unpack('<QQ', chunks('OBJECT', index, 16))
        if not vtable or not control_address or control_address != number(item['control']):
            raise ValueError('Scheduler object/control raw bytes differ')
        control = chunks('CONTROL', index, 0x1b8)
        if (struct.unpack_from('<I', control, 8)[0] != number(item['id']) or
                struct.unpack_from('<Q', control, 0x10)[0] != number(item['token']) or
                item['msc_run'] != str(int(number(item['run']) == 0x34796b0))):
            raise ValueError('Scheduled control/token/run raw evidence differs')
        if index:
            return
        first, end, capacity = struct.unpack_from('<QQQ', control, 0x1a0)
        if end < first or capacity < end or end-first > 256*24 or (end-first) % 24:
            raise ValueError('Active scheduler dependency vector is invalid')
        for dependency in range((end-first)//24):
            value = take('DEPENDENCY_STATE', 'index future status status_readable stable identity_unverified')
            if (number(value['index']) != dependency or value['status_readable'] != '1' or
                    value['stable'] != '1' or value['identity_unverified'] != '1' or
                    not 0 <= number(value['status']) <= 0xffffffff):
                raise ValueError('Scheduler dependency reads incomplete or reordered')
            entry = chunks('DEPENDENCY', dependency, 24)
            if not number(value['future']) or struct.unpack_from('<Q', entry)[0] != number(value['future']):
                raise ValueError('Scheduler dependency raw bytes differ')

    if active:
        scheduled(0, active)
    seen_nodes = set()
    for index in range(1, pending+1):
        if not node or node == head or node in seen_nodes:
            raise ValueError('Pending scheduler list is cyclic or incomplete')
        seen_nodes.add(node)
        next_node, back, object_address = struct.unpack('<QQQ', chunks('NODE', index, 24))
        if back != previous_node:
            raise ValueError('Pending scheduler backlink differs')
        scheduled(index, object_address)
        previous_node, node = node, next_node
    if node != head or previous_node != last:
        raise ValueError('Pending scheduler list does not close')
    stability = take('SCHED_STABILITY', 'header_equal visited pending complete stable atomic')
    if (any(stability[k] != '1' for k in ('header_equal', 'complete', 'stable')) or
            number(stability['visited']) != pending or number(stability['pending']) != pending or
            stability['atomic'] != '0'):
        raise ValueError('Scheduler observation incomplete or unstable')
    original = chunks('SCHED_HEADER_BYTES', 0, 0x90)
    if (struct.unpack_from('<Q', original)[0] != base+0x910a108 or
            struct.unpack_from('<I', original, 8)[0] != 6 or
            struct.unpack_from('<QQQ', original, 0x10) !=
                (number(header['first']), last, pending) or
            struct.unpack_from('<Q', original, 0x88)[0] != active):
        raise ValueError('Scheduler 0x90-byte header raw content differs')
    tids = []
    while position < len(records) and records[position].startswith('SNAPSHOT_THREAD '):
        tid, generation = None, None
        syscall_raw = None
        for field in ('comm', 'wchan', 'stack', 'syscall'):
            item = take('THREAD', 'tid start start_readable field readable bytes errno')
            current_tid = number(item['tid'])
            if tid is None:
                tid, generation = current_tid, item['start']
            if (current_tid != tid or item['start'] != generation or item['field'] != field or
                    item['readable'] != '1' or item['start_readable'] != '1' or item['errno'] != '0' or
                    not generation.isdigit() or number(generation) < 1 or
                    not 0 <= number(item['bytes']) < 4096):
                raise ValueError('Thread observations incomplete or reordered')
            value = chunks('THREAD_'+field.upper()+'_BYTES', tid, number(item['bytes']))
            if field == 'syscall':
                syscall_raw = value.decode('ascii', 'strict').strip()
        # /proc/.../syscall reports a running thread without SP/PC; no invented stack follows.
        words = syscall_raw.split()
        if len(words) == 9:
            try:
                syscall_number = int(words[0], 10)
                syscall_values = [int(word, 16) for word in words[1:]]
            except ValueError as error:
                raise ValueError('Invalid syscall raw evidence') from error
            user = take('THREAD_USER_STACK', 'tid sp pc syscall raw_candidates_only')
            if (number(user['tid']) != tid or number(user['sp']) != syscall_values[-2] or
                    number(user['pc']) != syscall_values[-1] or
                    user['syscall'] != str(syscall_number) or user['raw_candidates_only'] != '1'):
                raise ValueError('User stack declaration differs from syscall raw evidence')
            chunks('THREAD_USER_STACK_BYTES', tid, 512)
        elif syscall_raw != 'running' and not re.fullmatch(r'-1\s+(?:0x)?[0-9a-f]+\s+(?:0x)?[0-9a-f]+', syscall_raw):
            raise ValueError('Unknown syscall shape; no complete user-stack claim permitted')
        thread_end = take('THREAD_END', 'tid generation_equal')
        if (number(thread_end['tid']) != tid or thread_end['generation_equal'] != '1' or
                not tid or (tids and tid <= tids[-1])):
            raise ValueError('Thread generation missing, duplicated or reordered')
        tids.append(tid)
        if len(tids) > 512:
            raise ValueError('Thread count exceeds the observation bound')
    thread_end = take('THREADS_END', 'visited complete limit atomic')
    if (not tids or number(thread_end['visited']) != len(tids) or thread_end['complete'] != '1' or
            thread_end['limit'] != '512' or thread_end['atomic'] != '0'):
        raise ValueError('Thread summary incomplete')
    end = take('END', 'phase pid start generation_equal maps_equal file_identity_equal pending_complete scheduler_stable threads_complete reads_complete atomic')
    if (any(end[key] != start[key] for key in ('phase', 'pid', 'start')) or
            any(end[key] != '1' for key in ('generation_equal', 'maps_equal', 'file_identity_equal',
                'pending_complete', 'scheduler_stable', 'threads_complete', 'reads_complete')) or
            end['atomic'] != '0' or records[position:] != ['PRODUCT_MSC_SCHEDULER_RC=0']):
        raise ValueError('Scheduler receipt incomplete, duplicated or failed')
    return dict(phase=phase, **{key: start[key] for key in ('pid', 'start', 'base')},
                source_sha256=contract['source_sha256'], maps_sha256=maps['sha256'], scheduler_group=6,
                process_identity_verified=True, pending_complete=True, scheduler_stable=True,
                threads_complete=True, reads_complete=True, atomic=False, submission_absence_proven=False)


def collect(serial, run, phase, contract, previous=None):
    if phase not in ('before-enter', 'after-enter') or (phase == 'after-enter') != (previous is not None):
        raise ValueError('Scheduler phases require the same AP before/after original ENTER')
    if re.fullmatch('[0-9a-f]{64}', contract['binary_sha256']) is None:
        raise ValueError('Unsafe scheduler binary digest')
    pid, start = (previous['pid'], previous['start']) if previous else ('0', '0')
    if not pid.isdigit() or not start.isdigit():
        raise ValueError('Unsafe scheduler process identity')
    path = Path(run)/('usb-msc-scheduler-'+phase+'.raw')
    # Reserve evidence before issuing a guest command; existing evidence rejects the action.
    descriptor = _reserve(path)
    command = ('/simulation/'+BINARY+' '+phase+' '+pid+' '+start+' '+contract['binary_sha256']+
               '; scheduler_rc=$?; echo PRODUCT_MSC_SCHEDULER_RC=$scheduler_rc; true')
    try:
        try:
            raw = serial(command)
        except BaseException as error:
            partial = error.raw if isinstance(error, SerialBoundaryLost) else b''
            try:
                _write_readback(descriptor, path, partial)
                _json(path.with_suffix('.error.json'), dict(error=type(error).__name__+': '+str(error),
                      phase=phase, raw_sha256=hashlib.sha256(partial).hexdigest(), raw_bytes=len(partial),
                      original_console_path=str(serial.console) if isinstance(serial, SchedulerSerial) else None,
                      console_rotation_performed=False, exit_verified=False,
                      serial_boundary_lost=isinstance(error, SerialBoundaryLost),
                      persistent_owner_required=isinstance(error, SerialBoundaryLost),
                      observation_status='unobserved', submission_absence_proven=False))
            except BaseException as save_error:
                error.add_note('Scheduler evidence preservation failed: '+type(save_error).__name__+': '+str(save_error))
            raise
        _write_readback(descriptor, path, raw)
    finally:
        os.close(descriptor)
    try:
        result = parse(raw, phase, contract, previous)
    except BaseException as error:
        try:
            _json(path.with_suffix('.error.json'), dict(error=type(error).__name__+': '+str(error),
                                                      raw_sha256=hashlib.sha256(raw).hexdigest(), phase=phase,
                                                      observation_status='unobserved', submission_absence_proven=False))
        except BaseException as save_error:
            error.add_note('Scheduler evidence preservation failed: '+type(save_error).__name__+': '+str(save_error))
        raise
    result.update(raw_sha256=hashlib.sha256(raw).hexdigest(), raw_bytes=len(raw))
    _json(path.with_suffix('.json'), result)
    return result
