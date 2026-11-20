"""Opt-in owner/lifecycle integration for the functional camera broker.

Only the broker accesses the dedicated guest mailbox. This module validates build
and console evidence, hands off the existing Unix debugger, and gates teardown.
"""
from contextlib import contextmanager, nullcontext
import hashlib
import io
import json
import os
from pathlib import Path
import platform
import re
import signal
import stat
import struct
import subprocess
import tarfile
import threading
import time

import backup_profile
import capture_socket_roots as capture_sockets
from backup_profile import FUNCTIONAL_CAMERA_PROFILE
import functional_ram_initramfs as ram_initramfs
import functional_camera_broker as transport
import scope_observer_profile
from menu_live import FirmwareFault, FirmwareMonitor

QEMU_SHA256 = 'b36998138a65b1bd2645ca24bf0dde0c0801d868d1291ec6f9e83ff707d64bad'
WRITEBACK_FLUSH_QEMU_SHA256 = 'df6144a095f8cfbde49c454a9872129811ee9c831051417639e7129a4ddeb4b9'
READONLY_SCOPE_QEMU_SHA256 = '4e85c70ba38774e9439562a7178a65bdbe6b660fdf8dd6bd4ece686fb707a4d4'
RECEIPT = 'functional-camera-runner.json'
GDB = 'hdmi-upm-gdb.sock'
QMP = 'hdmi-upm-control.sock'
RAM_CONSUMER_PROFILE = 'inherited-ram-card-fds-v1'
SETTINGS_RESTART_PROFILE = 'functional-ram-card-independent-internal-v1'
RAM_CONSUMER_RECEIPT = 'functional-camera-ram-consumer.json'
CLOSE_FIELDS = ('safe_to_close', 'mailbox_detached', 'debugger_stopped',
                'protocol_physmode_restored', 'worker_stopped')


def require(condition, message):
    if not condition:
        raise ValueError(message)


def checked_read(path, limit=16 * 1024 * 1024, *, allow_empty=False):
    path = Path(path).absolute()
    require(path.resolve() == path, 'Artifact path contains a symlink: ' + str(path))
    fd = os.open(path, os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        before = os.fstat(fd)
        require(stat.S_ISREG(before.st_mode) and before.st_uid == os.getuid() and
                not before.st_mode & 0o022 and (0 if allow_empty else 1) <= before.st_size <= limit,
                'Untrusted/oversized regular artifact: ' + str(path))
        raw = bytearray()
        while len(raw) < before.st_size:
            part = os.read(fd, min(1024 * 1024, before.st_size - len(raw)))
            require(part, 'Short artifact read: ' + str(path))
            raw.extend(part)
        after = os.fstat(fd)
        identity = lambda st: (st.st_dev, st.st_ino, st.st_size, st.st_mtime_ns, st.st_ctime_ns)
        require(identity(before) == identity(after), 'Artifact changed during read: ' + str(path))
        return bytes(raw)
    finally:
        os.close(fd)


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def object_json(raw):
    def pairs(values):
        result = {}
        for key, value in values:
            require(key not in result, 'Duplicate JSON field: ' + key)
            result[key] = value
        return result
    value = json.loads(raw, object_pairs_hook=pairs)
    require(type(value) is dict, 'JSON object required')
    return value


def check_library_abi(raw):
    """Inspect ELF metadata without loading or calling the model."""
    require(len(raw) >= 64 and raw[:7] == b'\x7fELF\x02\x01\x01', 'Model must be little-endian ELF64')
    kind, machine = struct.unpack_from('<HH', raw, 16)
    expected = {'x86_64': 62, 'aarch64': 183}.get(platform.machine())
    require(kind == 3 and machine == expected, 'Model ELF architecture/type differs from this host')
    offset = struct.unpack_from('<Q', raw, 40)[0]
    stride, count = struct.unpack_from('<HH', raw, 58)
    require(stride == 64 and 0 < count < 65535 and offset + count * stride <= len(raw), 'Invalid ELF section table')
    sections = [struct.unpack_from('<IIQQQQIIQQ', raw, offset + n * stride) for n in range(count)]
    exports = set()
    for section in sections:
        if section[1] != 11:  # SHT_DYNSYM
            continue
        start, size, linked, entry = section[4], section[5], section[6], section[9]
        require(entry == 24 and not size % entry and start + size <= len(raw) and linked < count, 'Invalid ELF symbols')
        names = sections[linked]
        require(names[1] == 3 and names[4] + names[5] <= len(raw), 'Invalid ELF symbol strings')
        strings = raw[names[4]:names[4] + names[5]]
        for item in range(start, start + size, entry):
            name, info, visibility, defined = struct.unpack_from('<IBBH', raw, item)
            require(name < len(strings), 'ELF symbol name exceeds string table')
            end = strings.find(b'\0', name)
            require(end >= name, 'Unterminated ELF symbol')
            if info >> 4 in (1, 2) and info & 15 == 2 and visibility & 3 == 0 and defined:
                exports.add(strings[name:end])
    require({b'fcam_model_create', b'fcam_model_destroy', b'fcam_model_request'} <= exports,
            'Model does not export the three functional-camera ABI entry points')
    return {'version': 1, 'elf_machine': machine, 'entry_points': sorted(name.decode() for name in exports
            if name in {b'fcam_model_create', b'fcam_model_destroy', b'fcam_model_request'})}


def validate_artifact(base, qemu_binary, *, scope_build_receipt=None):
    base = Path(base).absolute()
    root = base.parents[1]
    metadata_path = base / 'functional-camera-model-build.json'
    metadata_raw = checked_read(metadata_path)
    metadata = object_json(metadata_raw)
    require(metadata.get('profile') == FUNCTIONAL_CAMERA_PROFILE and
            metadata.get('capture_verified') is False and
            metadata.get('physical_asic_compatibility_verified') is False, 'Model build profile/claim mismatch')
    work_name = metadata.get('work')
    require(type(work_name) is str, 'Model build work directory missing')
    work = root / work_name
    require(work.is_absolute() and work.resolve() == work and work.parent == base / 'scratch' and
            work.name.startswith('functional-model-build-'), 'Untrusted model build directory')
    require(object_json(checked_read(work / 'build.json')) == metadata, 'Published model receipt differs from build receipt')
    raw = checked_read(base / 'functional-camera-model.so', 256 * 1024 * 1024)
    require(digest(raw) == metadata.get('library_sha256') and
            digest(checked_read(work / 'functional-camera-model.so', 256 * 1024 * 1024)) == digest(raw),
            'Functional model library digest differs from actual build')
    compile_raw = checked_read(work / 'compile.json')
    compiled = object_json(compile_raw)
    require(digest(compile_raw) == metadata.get('compile_receipt_sha256') and
            type(compiled.get('returncode')) is int and compiled['returncode'] == 0 and
            compiled.get('log_sha256') == digest(checked_read(work / 'build.log', allow_empty=True)),
            'Model compiler receipt/log mismatch')
    command = compiled.get('command')
    require(type(command) is list and all(type(part) is str for part in command) and
            '-shared' in command and '-fPIC' in command and '-Wl,--no-undefined' in command and
            command[0] == metadata.get('compiler'), 'Model compiler ABI flags differ')
    sources = metadata.get('sources')
    require(type(sources) is dict and sources and
            'runtime/analysis/functional-camera-abi.h' in sources and
            'report/functional-camera-core/functional-camera-core.c' in sources, 'Model sources/ABI receipt missing')
    for name, sha in sources.items():
        require(type(name) is str and not Path(name).is_absolute() and '..' not in Path(name).parts and
                type(sha) is str and re.fullmatch('[0-9a-f]{64}', sha), 'Invalid model source binding')
        require(digest(checked_read(root / name)) == sha, 'Model source differs from built archive: ' + name)
    abi_header = checked_read(base / 'functional-camera-abi.h').decode('ascii')
    for name, value in (('FCAM_PROFILE', '"' + FUNCTIONAL_CAMERA_PROFILE + '"'),
                        ('FCAM_ABI_VERSION', '1u'), ('FCAM_PAGE_BYTES', '4096u'),
                        ('FCAM_MAILBOX_PAGES', '16u'), ('FCAM_HEADER_BYTES', '512u')):
        require(re.search(r'^#define ' + name + r'\s+' + re.escape(value) + r'\s*$', abi_header, re.M),
                'Unsupported functional-camera ABI: ' + name)
    archive_raw = checked_read(work / 'functional-model-sources.tar.gz', 64 * 1024 * 1024)
    require(digest(archive_raw) == metadata.get('source_archive_sha256'), 'Model source archive digest mismatch')
    with tarfile.open(fileobj=io.BytesIO(archive_raw), mode='r:gz') as archive:
        seen = set()
        total = 0
        for member in archive:
            require(member.isfile() and member.name in sources and member.name not in seen and
                    0 <= member.size <= 16 * 1024 * 1024, 'Unsafe/duplicate/unlisted model archive member')
            total += member.size
            require(total <= 64 * 1024 * 1024, 'Oversized model source archive')
            seen.add(member.name)
            with archive.extractfile(member) as stream:
                require(digest(stream.read(member.size + 1)) == sources[member.name], 'Model archived source differs')
        require(seen == set(sources), 'Model archive omits a source/ABI file')
    qemu_sha256 = digest(checked_read(qemu_binary, 256 * 1024 * 1024))
    if os.environ.get('QEMU_A7PF_WRITEBACK_FLUSH') == '1':
        require(scope_build_receipt is None, 'Writeback-flush QEMU cannot use the scope observer profile')
        require(qemu_sha256 == WRITEBACK_FLUSH_QEMU_SHA256,
                'Writeback-flush profile requires its exact isolated QEMU executable')
    elif scope_build_receipt is None:
        require(qemu_sha256 == QEMU_SHA256,
                'Functional camera requires the accepted unchanged QEMU executable')
    else:
        require(qemu_sha256 == READONLY_SCOPE_QEMU_SHA256,
                'Scope functional camera requires the exact reviewed plugin-enabled QEMU')
        scope_observer_profile.validate_build(root, scope_build_receipt, qemu_binary)
    return {'library': str(base / 'functional-camera-model.so'), 'library_sha256': digest(raw),
            'build_receipt': str(metadata_path), 'build_receipt_sha256': digest(metadata_raw),
            'source_archive': str(work / 'functional-model-sources.tar.gz'),
            'source_archive_sha256': digest(archive_raw), 'compile_receipt_sha256': digest(compile_raw),
            'abi_header_sha256': sources['runtime/analysis/functional-camera-abi.h'],
            'abi': check_library_abi(raw), 'qemu_sha256': qemu_sha256}


def verify_ram_card_inherited(environment):
    """Check inherited host FDs before bwrap preserves them or binds their inodes.

    Read-only sandbox paths are an alternative to raw descriptor inheritance;
    neither transport is QEMU/guest readback.
    """
    require(environment.get('A7C2_RAM_CARD_LAUNCH_PROFILE') == RAM_CONSUMER_PROFILE,
            'Unknown inherited RAM-card launch profile')
    names = ('SEED', 'DIRECTORY', 'RECEIPT', 'INITRAMFS', 'QEMU')
    fds = []
    for name in names:
        raw = environment.get('A7C2_RAM_CARD_' + name + '_FD', '')
        require(re.fullmatch('[1-9][0-9]*', raw) and int(raw) >= 3, 'Invalid inherited RAM-card FD')
        fds.append(int(raw))
    require(len(set(fds)) == len(fds), 'Inherited RAM-card FD aliases')
    import fcntl
    for name, fd in zip(names, fds):
        before = os.fstat(fd)
        require(before.st_uid == os.geteuid() and not before.st_mode & 0o022,
                'Untrusted inherited RAM-card input')
        require(fcntl.fcntl(fd, fcntl.F_GETFL) & os.O_ACCMODE == os.O_RDONLY,
                'Inherited RAM-card input must be read-only')
        if name == 'DIRECTORY':
            require(stat.S_ISDIR(before.st_mode) and stat.S_IMODE(before.st_mode) == 0o700,
                    'Inherited RAM-card directory must be private')
            continue
        links = 2 if name == 'RECEIPT' else 1
        require(stat.S_ISREG(before.st_mode) and before.st_nlink == links and before.st_size > 0,
                'Inherited RAM-card input link count/type differs: ' + name)
        if name == 'SEED':
            ram_initramfs.fat16(fd, before.st_size)
        elif name == 'INITRAMFS':
            require(before.st_size <= ram_initramfs.MAX_INITRD_BYTES, 'Inherited initramfs exceeds load window')
        elif name == 'QEMU':
            require(before.st_mode & 0o111, 'Inherited QEMU is not executable')
        expected = environment.get('A7C2_RAM_CARD_' + name + '_SHA256', '')
        require(re.fullmatch('[0-9a-f]{64}', expected) and
                ram_initramfs.sha_range(fd, 0, before.st_size) == expected and
                ram_initramfs.metadata(before) == ram_initramfs.metadata(os.fstat(fd)),
                'Inherited RAM-card readback differs: ' + name)
        if name == 'RECEIPT':
            # The producer retains both publication names for this exact receipt inode.
            for published in ('.backup-profile.pending.json', 'backup-profile.json'):
                named_fd = os.open(published, os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW | os.O_NONBLOCK,
                                   dir_fd=fds[1])
                try:
                    named = os.fstat(named_fd)
                    require(ram_initramfs.metadata(named) == ram_initramfs.metadata(before) and
                            ram_initramfs.sha_range(named_fd, 0, named.st_size) == expected and
                            ram_initramfs.metadata(os.fstat(named_fd)) == ram_initramfs.metadata(before) and
                            ram_initramfs.metadata(os.fstat(fd)) == ram_initramfs.metadata(before) and
                            ram_initramfs.metadata(os.stat(published, dir_fd=fds[1], follow_symlinks=False)) ==
                            ram_initramfs.metadata(before),
                            'Inherited RAM-card receipt publication differs: ' + published)
                finally:
                    os.close(named_fd)
    accepted_qemu = (WRITEBACK_FLUSH_QEMU_SHA256,) if environment.get(
        'QEMU_A7PF_WRITEBACK_FLUSH') == '1' else (QEMU_SHA256, READONLY_SCOPE_QEMU_SHA256)
    require(environment['A7C2_RAM_CARD_QEMU_SHA256'] in accepted_qemu,
            'Inherited QEMU is not an accepted functional-camera build')
    for name, fd in (('media-camera.fat', fds[0]), ('.backup-profile.pending.json', fds[2]),
                     ('backup-profile.json', fds[2])):
        held = os.fstat(fd)
        named = os.stat(name, dir_fd=fds[1], follow_symlinks=False)
        require(ram_initramfs.metadata(held) == ram_initramfs.metadata(named),
                'Inherited RAM-card directory binding differs: ' + name)
    return max(fds)


def parse_mailbox(console):
    """Return only a complete actual bridge record; repeated mirrors must agree."""
    # Async bridge output can follow the exact guest prompt; keep the newline for adjacent records.
    records = re.findall(rb'(?:^|\n)(?:(?:/ # )?OBS )?FUNCTIONAL_CAMERA_MAILBOX ([^\r\n]+)(?=\r?\n)', console)
    binding = None
    for raw in records:
        tokens = raw.decode('ascii').split()
        require(all(token.count('=') == 1 for token in tokens), 'Malformed mailbox console record')
        fields = dict(token.split('=', 1) for token in tokens)
        require(len(fields) == len(tokens) and set(fields) == {'phys0', 'nonce', 'pid', 'ABI', 'version', 'pages'},
                'Missing/duplicate/unrecognized mailbox console field')
        require(fields['ABI'] == FUNCTIONAL_CAMERA_PROFILE and fields['version'] == '1', 'Mailbox profile/ABI mismatch')
        def number(text):
            require(re.fullmatch(r'(?:0x[0-9a-f]+|[0-9]+)', text), 'Nonnumeric mailbox field')
            return int(text, 16 if text.startswith('0x') else 10)
        mailbox = transport.validate_mailbox({'phys0': number(fields['phys0']), 'nonce': number(fields['nonce']),
                    'pid': number(fields['pid']), 'pages': [number(value) for value in fields['pages'].split(',')]})
        require(binding is None or binding['mailbox'] == mailbox, 'Multiple functional mailbox owners/identities')
        binding = {'mailbox': mailbox, 'console_record': raw.decode('ascii'), 'console_record_sha256': digest(raw),
                   'profile': fields['ABI'], 'abi_version': 1}
    return binding


def _natural_capture_state(console, binding):
    """Parse the same strict capture lifecycle for readiness and final retirement."""
    require(b'FUNCTIONAL_CAPTURE ' not in console, 'Natural still capture owner is active or unsaved; legacy receipt')
    prefix = b'OBS FUNCTIONAL_CAMERA_CAPTURE'
    rows = list(re.finditer(rb'(?:^|\n)OBS FUNCTIONAL_CAMERA_CAPTURE ([^\r\n]*)\r?(?=\n|$)', console))
    require(console.count(prefix) == len(rows), 'Natural still capture owner is active or unsaved; incomplete framing')
    expected = set(('operation rc pid job phase request_fnv cookie frame_token model_instance request_freed '
                    'encoded frame_released notification_consumed write_verified resources_released write_token '
                    'write_bytes write_fnv policy original_AP_saved capture_verified physical_ASIC_verified').split())
    pending, last_job, frames, completed = None, 0, set(), None
    for row in rows:
        require(row.end() < len(console), 'Natural still capture owner is active or unsaved; truncated receipt')
        tokens = row[1].decode('ascii').split()
        require(all(token.count('=') == 1 for token in tokens), 'Natural capture malformed field')
        fields = dict(token.split('=', 1) for token in tokens)
        require(len(fields) == len(tokens) and set(fields) == expected, 'Natural capture incomplete/duplicate fields')
        def number(key):
            text = fields[key]
            require(re.fullmatch(r'(?:0x[0-9a-f]+|0|[1-9][0-9]*)', text), 'Natural capture invalid number: ' + key)
            return int(text, 16 if text.startswith('0x') else 10)
        require(binding is not None and number('pid') == binding['mailbox']['pid'] and fields['rc'] == '0' and
                fields['policy'] == 'original-consumer-natural4038-software-jpeg-v1' and
                fields['original_AP_saved'] == fields['capture_verified'] == fields['physical_ASIC_verified'] == '0' and
                all(re.fullmatch('[0-9a-f]{16}', fields[key]) for key in ('request_fnv', 'write_fnv')),
                'Natural still capture owner is active or unsaved; failed or promoted receipt')
        identity = tuple(fields[key] for key in ('pid', 'job', 'request_fnv', 'cookie', 'policy'))
        operation = fields['operation']
        if operation == 'natural-request-owned':
            require(pending is None and number('job') > last_job and fields['request_freed'] == '1' and
                    not any(number(key) for key in ('frame_token', 'model_instance', 'encoded', 'frame_released',
                        'write_verified', 'resources_released', 'write_token', 'write_bytes')),
                    'Natural capture repeated/overlapping job')
            pending = dict(identity=identity, frame=None, write=None, queued=False, consumed=False, matched=False)
            last_job = number('job')
            continue
        require(pending is not None and pending['identity'] == identity and fields['request_freed'] == '1' and
                fields['encoded'] == fields['frame_released'] == '1' and 0 <= number('notification_consumed') <= 3 and
                number('model_instance') == binding['mailbox']['nonce'] and number('frame_token') > 0,
                'Natural capture changed request/frame identity')
        frame = (number('frame_token'), number('model_instance'))
        require(pending['frame'] in (None, frame) and (pending['frame'] is not None or frame not in frames),
                'Natural capture reused or changed frame')
        pending['frame'] = frame
        if operation == 'notifications-queued-unsaved':
            require(not pending['queued'], 'Natural capture notifications queued twice')
            pending['queued'] = True
        elif operation == 'notifications-consumed-unsaved':
            require(pending['queued'] and not pending['consumed'] and number('notification_consumed') == 3,
                    'Natural capture notifications are not drained')
            pending['consumed'] = True
        elif operation == 'write-source-matched':
            require(not pending['matched'] and number('write_token') > 0, 'Natural capture duplicate write source')
            pending['matched'] = True
        elif operation == 'write-lifecycle':
            require(pending['matched'] and number('write_token') > 0 and number('write_bytes') > 0,
                    'Natural capture write lacks matching source')
            write = (number('write_token'), number('write_bytes'), fields['write_fnv'])
            require(pending['write'] in (None, write), 'Natural capture native write identity changed')
            pending['write'] = write
        elif operation == 'write-retired':
            require(pending['queued'] and pending['consumed'] and pending['matched'] and
                    pending['write'] == (number('write_token'), number('write_bytes'), fields['write_fnv']) and
                    fields['write_verified'] == fields['resources_released'] == '1' and number('notification_consumed') == 3,
                    'Natural still capture owner is active or unsaved; native write/resources not retired')
            frames.add(frame)
            completed = pending
            pending = None
        else:
            raise ValueError('Natural still capture owner is active or unsaved; unknown operation: ' + operation)
    return pending, completed


def require_natural_capture_closed(console, binding):
    """Resource retirement after real native write/readback is distinct from capture acceptance."""
    pending, _ = _natural_capture_state(console, binding)
    require(pending is None, 'Natural still capture owner is active or unsaved; retain VM, card and owner resources')


def require_natural_capture_write_ready(console, binding):
    """Permit the original flush after matching write completion, never teardown or capture success."""
    pending, completed = _natural_capture_state(console, binding)
    current = pending if pending is not None else completed
    require(current is not None and current['queued'] and current['consumed'] and current['matched'] and
            current['write'] is not None, 'Natural capture native write is not complete for flush')
    pid, job, request_fnv, _, _ = current['identity']
    token, size, file_fnv = current['write']
    require(0 < size < 2**32, 'Natural capture write size outside native range')
    tags = ('FSYS_WRITE_REQUEST', 'FSYS_WRITE_SUBMIT', 'MPR_WRITE_CALLBACK',
            'MPR_WRITE_FINISHED', 'MPR_WRITE_CALLBACK_RETURN')
    records = {}
    pattern = rb'^(?:OBS )?(' + b'|'.join(tag.encode() for tag in tags) + rb') ([^\r\n]+)\r?\n'
    for row in re.finditer(pattern, console, re.M):
        parts = row[2].decode('ascii').split()
        require(all(part.count('=') == 1 for part in parts), 'Malformed original write lifecycle')
        fields = dict(part.split('=', 1) for part in parts)
        require(len(fields) == len(parts), 'Duplicate original write fields')
        if fields.get('pid') != pid or fields.get('token') != str(token):
            continue
        tag = row[1].decode('ascii')
        require(tag not in records, 'Duplicate original write lifecycle: ' + tag)
        records[tag] = fields, row.start()
    require(set(records) == set(tags), 'Original write submit/callback/finished is incomplete for flush')
    request, request_at = records['FSYS_WRITE_REQUEST']
    require(request.get('bytes') == '1288' and request.get('observation_rc') == '0' and
            request.get('payload_complete') == '1' and request.get('expected_bytes') == str(size) and
            request.get('address_mode') == '1' and re.fullmatch(r'0x[0-9a-f]+', request.get('cookie', '')) and
            int(request['cookie'], 16) > 0, 'Original write request does not match capture')
    require(all(request_at < position for tag, (_, position) in records.items() if tag != 'FSYS_WRITE_REQUEST'),
            'Original write lifecycle precedes its request')
    submit = records['FSYS_WRITE_SUBMIT'][0]
    callback = records['MPR_WRITE_CALLBACK'][0]
    finished = records['MPR_WRITE_FINISHED'][0]
    returned = records['MPR_WRITE_CALLBACK_RETURN'][0]
    require(submit.get('rc') == '0' and submit.get('callback_seen') in ('0', '1') and
            callback.get('rc') == '0' and callback.get('result_copied') == '1' and
            callback.get('duplicate') == '0' and callback.get('result_bytes') == '1240' and
            callback.get('cookie') == request['cookie'] and finished.get('cookie') == request['cookie'] and
            finished.get('rc') == '0' and finished.get('input_copied') == '1' and
            finished.get('returned') == returned.get('returned') == '1' and finished.get('duplicate') == '0' and
            records['MPR_WRITE_CALLBACK'][1] < records['MPR_WRITE_CALLBACK_RETURN'][1],
            'Original write completion failed or changed callback identity')
    return dict(pid=int(pid), job=int(job), request_fnv=request_fnv, token=token,
                bytes=size, file_fnv=file_fnv, write_complete=True, capture_verified=False)


def require_capture_closed(run):
    """A prior clip's Close cannot authorize tearing down the current native clip."""
    console = (Path(run) / 'console.log').read_bytes()
    binding = parse_mailbox(console)
    require_natural_capture_closed(console, binding)
    requests, completed, received, freed = {}, set(), set(), set()
    current = None
    epochs, closed_epochs = set(), set()
    jpeg, jpeg_history = {}, {}
    jpeg_received, jpeg_freed, jpeg_callbacks = {}, set(), set()
    jpeg_inputs, jpeg_configured, jpeg_outputs = {}, set(), {}
    last_jpeg = 0
    jpeg_common = set(('operation rc pid tid producer_tid sequence original_base exec_entry caller object manager control '
                       'context key source destination command native_bytes trigger_fnv response_tag model_instance bytes '
                       'output_fnv stream_mode kind selector comp_object physical_asic_compatible capture_verified').split())
    reply_fields = 'receiver_pid receiver_tid reply_address response_hex reply_hex response_source response_destination lease_generation lease_token'
    callback_fields = ('receiver_pid receiver_tid callback_caller res_entry response_hex response_address response_source '
                       'response_destination response_mid original_result expected_result original_errno '
                       'lease_generation lease_token release_rc terminal lease_released')
    jpeg_details = {
        'original-request': 'request_hex',
        'original-request-lease': ('sds_type sds_handle sds_offset stream_position lease_offset lease_address lease_capacity '
                                   'lease_generation lease_token lease_group lease_unit lease_area lease_unit_type'),
        'output-readback': ('lease_generation lease_token lease_address lease_offset lease_capacity model_token model_bytes '
                            'model_fnv model_offset readback_bytes readback_fnv'),
        'queued-ack': '', 'queued-done': '',
        'original-input-binding': ('frame_token frame_lifetime input_cfg input_frame source_fnv source_bytes '
                                   'metadata_unit pixel_unit metadata_token pixel_token'),
        'original-input-descriptor': 'metadata_address metadata_bytes metadata_fnv pixel_address pixel_bytes input_readonly image72',
        'original-output-retained': ('frame_token copied_bytes copied_fnv original_output_bytes original_output_fnv '
                                     'model_token lease_token actual_native_terminal'),
        'original-input-release': 'frame_token metadata_token pixel_token input_release_rc actual_native_terminal input_refs_released',
        'original-maincomp-exec': ('comp_caller comp_exec_entry previous_ack_hex previous_ack_address original_result '
                                   'native_config config_length_offset'),
        'original-maincomp-config': 'native_config config_length_offset actual_length expected_length original_result',
        **{f'original-received-{stage}': reply_fields for stage in ('ack', 'done')},
        **{f'original-freed-{stage}': reply_fields + ' free_rc' for stage in ('ack', 'done')},
        **{f'original-rescmd-{stage}': callback_fields for stage in ('ack', 'done')},
    }
    for match in re.finditer(rb'(?:^|\n)(?:/ # )?(?:OBS )?FUNCTIONAL_(MPR_(?:REQUEST|OPERATION|EVENT_RECEIVED|EVENT_FREE)|JPEG_CODEC)([^\n]*?)\r?(?=\n|$)', console):
        kind, raw = match.groups()
        require(raw.startswith(b' '), 'Malformed native capture shutdown record framing')
        raw = raw[1:]
        require(match.end() < len(console), 'Incomplete native capture shutdown record')
        require(b'OBS ' not in raw and b'FUNCTIONAL_' not in raw, 'Concatenated native capture shutdown records')
        if kind == b'JPEG_CODEC':
            operation_match = re.match(rb'operation=([a-z][a-z-]*)(?= |$)', raw)
            require(operation_match is not None and raw.count(b'operation=') == 1, 'Missing/ambiguous native still operation')
            operation = operation_match[1].decode('ascii')
            if operation in ('enable', 'shutdown'):
                # Only note(NULL-job) setup plus this exact kernel diagnostic grammar is non-lifecycle.
                # No lifecycle record is split, truncated, or supplied with recovered guest fields.
                require(re.fullmatch(
                    rb'operation=(?:enable|shutdown) rc=0 pid=[1-9][0-9]* tid=[1-9][0-9]* producer_tid=0 sequence=0 '
                    rb'original_base=(?:0x[0-9a-f]+|0) exec_entry=(?:0x[0-9a-f]+|0) caller=0 '
                    rb'object=\(nil\) manager=\(nil\) control=\(nil\) context=0 key=0 source=0 destination=0 '
                    rb'command=0 native_bytes=0 trigger_fnv=0000000000000000 response_tag=0 model_instance=0 '
                    rb'bytes=0 output_fnv=0000000000000000 stream_mode=0 kind=without-pin selector=0 '
                    rb'comp_object=\(nil\) physical_asic_compatible=0 capture_verified=0'
                    rb'(?:\[ *[0-9]+\.[0-9]+\] ERROR:pcie_set_link: current Link Speed does not match the target: '
                    rb'ch=[0-9]+, current=[0-9]+, target=[0-9]+)?', raw), 'Malformed/retained native still setup record')
                continue
            if operation == 'request-lease-release-failed':
                raise ValueError('Original still request retains an unreleased output lease')
            require(operation in jpeg_details, 'Unknown/failed native still operation: ' + operation)
        tokens = raw.decode('ascii').split()
        require(all(re.fullmatch(r'[a-z_][a-z_0-9]*=[^\s=]+', token) for token in tokens), 'Malformed native capture shutdown field')
        fields = dict(token.split('=', 1) for token in tokens)
        require(len(fields) == len(tokens), 'Duplicate native clip shutdown field')
        def number(key):
            value = fields.get(key, '')
            require(re.fullmatch(r'(?:0x[0-9a-f]+|[0-9]+)', value), 'Invalid native clip shutdown field: ' + key)
            return int(value, 16 if value.startswith('0x') else 10)
        if kind == b'JPEG_CODEC':
            require(set(fields) == jpeg_common | set(jpeg_details[operation].split()), 'Incomplete/unrecognized native still fields')
            require(binding is not None and number('pid') == binding['mailbox']['pid'], 'Native still owner differs from mailbox')
            seq = number('sequence')
            identity = tuple(fields[key] for key in ('sequence', 'producer_tid', 'object', 'manager', 'control',
                             'context', 'key', 'source', 'destination', 'command', 'native_bytes', 'trigger_fnv',
                             'kind', 'selector', 'original_base'))
            require(fields['rc'] == '0' and fields['kind'] in ('without-pin', 'main') and number('selector') <= 2 and
                    fields['physical_asic_compatible'] == fields['capture_verified'] == '0' and
                    all(re.fullmatch('[0-9a-f]{16}', fields[key]) for key in ('trigger_fnv', 'output_fnv')),
                    'Incomplete/failed native still completion')
            if operation == 'original-request':
                require(re.fullmatch('[0-9a-f]{208}', fields['request_hex']), 'Incomplete native still request wire')
                require(seq > last_jpeg and number('model_instance') in (0, binding['mailbox']['nonce']),
                        'Native still request is stale or repeated')
                jpeg[seq] = jpeg_history[seq] = identity
                last_jpeg = seq
            else:
                require(jpeg_history.get(seq) == identity and
                        (number('model_instance') in (0, binding['mailbox']['nonce']) if operation == 'original-request-lease'
                         else number('model_instance') == binding['mailbox']['nonce']),
                        'Native still completion differs from current request')
                if operation == 'output-readback':
                    require(seq in jpeg and seq not in jpeg_outputs and
                            (seq not in jpeg_inputs or jpeg_inputs[seq]['descriptor']),
                            'Native JPEG readback preceded input descriptor or repeated')
                    jpeg_outputs[seq] = fields
                elif operation == 'original-input-binding':
                    require(seq in jpeg and fields['kind'] == 'main' and seq not in jpeg_inputs and
                            all(number(key) > 0 for key in ('frame_token', 'frame_lifetime', 'input_cfg', 'input_frame',
                                'source_bytes', 'metadata_unit', 'pixel_unit', 'metadata_token', 'pixel_token')) and
                            number('metadata_unit') != number('pixel_unit') and re.fullmatch('[0-9a-f]{16}', fields['source_fnv']),
                            'Native attached JPEG input identity is incomplete')
                    jpeg_inputs[seq] = dict(binding=fields, descriptor=False, retained=False, released=False)
                elif operation == 'original-input-descriptor':
                    attached = jpeg_inputs.get(seq)
                    require(seq in jpeg and attached and not attached['descriptor'] and number('metadata_address') > 0 and
                            number('metadata_bytes') == 1024 and number('pixel_address') > 0 and
                            number('pixel_bytes') == int(attached['binding']['source_bytes'], 0) and fields['input_readonly'] == '1' and
                            re.fullmatch('[0-9a-f]{16}', fields['metadata_fnv']) and re.fullmatch('[0-9a-f]{144}', fields['image72']),
                            'Native attached JPEG descriptor is incomplete or repeated')
                    attached['descriptor'] = True
                elif operation == 'original-maincomp-config':
                    require(seq in jpeg and number('actual_length') == number('expected_length') == number('bytes') and
                            number('original_result') == 0 and seq not in jpeg_configured,
                            'Native MainComp output length is incomplete')
                    jpeg_configured.add(seq)
                elif operation == 'original-output-retained':
                    attached = jpeg_inputs.get(seq)
                    require(seq in jpeg and attached and attached['descriptor'] and not attached['retained'] and
                            seq in jpeg_configured and (seq, 'done') in jpeg_freed and
                            number('frame_token') == int(attached['binding']['frame_token'], 0) and
                            number('original_output_bytes') == number('bytes') and fields['original_output_fnv'] == fields['output_fnv'] and
                            number('copied_bytes') == number('bytes') + (2 if number('selector') == 0 else 0) and
                            re.fullmatch('[0-9a-f]{16}', fields['copied_fnv']) and seq in jpeg_outputs and
                            number('model_token') == int(jpeg_outputs[seq]['model_token'], 0) and
                            number('copied_bytes') == int(jpeg_outputs[seq]['model_bytes'], 0) and
                            number('lease_token') == int(jpeg_received[(seq, 'done')][0][-1], 0) and
                            fields['actual_native_terminal'] == '1',
                            'Native retained JPEG output lacks actual MainComp/free completion')
                    attached['retained'] = True
                elif operation == 'original-input-release':
                    attached = jpeg_inputs.get(seq)
                    require(seq in jpeg and attached and attached['retained'] and not attached['released'] and
                            all(number(key) == int(attached['binding'][key], 0) for key in ('frame_token', 'metadata_token', 'pixel_token')) and
                            fields['input_release_rc'] == '0' and fields['actual_native_terminal'] == fields['input_refs_released'] == '1',
                            'Native attached JPEG input was not retired after retained output')
                    attached['released'] = True
                if operation.startswith(('original-received-', 'original-freed-', 'original-rescmd-')):
                    require(re.fullmatch('[0-9a-f]{32}', fields['response_hex']) and
                            (operation.startswith('original-rescmd-') or re.fullmatch('[0-9a-f]{80}', fields['reply_hex'])),
                            'Incomplete native still response wire')
                    stage = (seq, operation.rsplit('-', 1)[1])
                    response_keys = ('receiver_pid', 'receiver_tid', 'response_hex', 'response_source',
                                     'response_destination', 'lease_generation', 'lease_token')
                    response = tuple(fields[key] for key in response_keys)
                    require(number('receiver_pid') == binding['mailbox']['pid'] and number('receiver_tid') > 0 and
                            number('lease_generation') > 0 and number('lease_token') > 0, 'Native still receive/lease identity invalid')
                    if operation.startswith('original-received-'):
                        require(seq in jpeg and stage not in jpeg_received, 'Native still completion received twice/after terminal')
                        jpeg_received[stage] = (response, fields['reply_address'], fields['reply_hex'])
                    else:
                        observed = jpeg_received.get(stage)
                        require(seq in jpeg and observed is not None and observed[0] == response,
                                'Native still completion lacks matching receive')
                        if operation.startswith('original-freed-'):
                            require(stage not in jpeg_freed and fields['free_rc'] == '0' and
                                    observed[1:] == (fields['reply_address'], fields['reply_hex']),
                                    'Native still free failed/repeated/differs from receive')
                            jpeg_freed.add(stage)
                        else:
                            done = stage[1] == 'done'
                            entry = 0x122b44 if fields['kind'] == 'main' and done else 0x120e64 if fields['kind'] == 'main' else 0x11a9dc
                            require(stage in jpeg_freed and stage not in jpeg_callbacks and
                                    number('res_entry') == number('original_base') + entry and
                                    number('callback_caller') == number('original_base') + 0x13b788 and
                                    number('response_mid') == (0x8311 if done else 0x8310) and
                                    fields['original_result'] == fields['expected_result'] and fields['release_rc'] == '0' and
                                    fields['terminal'] == fields['lease_released'] == ('1' if done else '0'),
                                    'Original still callback/output release is incomplete')
                            jpeg_callbacks.add(stage)
                            if done:
                                require(seq not in jpeg_inputs or jpeg_inputs[seq]['released'],
                                        'Native MainComp callback retains its captured input')
                                require(number('original_result') == 0 and
                                        (fields['kind'] != 'main' or number('comp_object') > 0),
                                        'Original MainComp terminal callback is incomplete')
                                del jpeg[seq]
            continue
        kind = kind.removeprefix(b'MPR_')
        require(binding is not None and number('pid') == binding['mailbox']['pid'], 'Native clip owner differs from mailbox')
        command, seq, epoch = number('command'), number('request_seq'), number('epoch')
        instance = number('instance')
        require(instance == binding['mailbox']['nonce'] or kind == b'REQUEST' and command == 0 and instance == 0,
                'Native clip instance differs from current mailbox')
        if kind == b'REQUEST':
            require(command in (0, 1, 3, 4) and seq not in requests and seq == len(requests) + 1 and fields.get('rc') == '0',
                    'Native clip request failed/reordered')
            if command == 0:
                require(epoch > 0 and (current is None or epoch > current), 'Native clip Open epoch is stale/repeated')
                current = epoch
                epochs.add(epoch)
            require(current == epoch and epoch not in closed_epochs, 'Native clip epoch changed before Close')
            requests[seq] = {key: number(key) for key in ('command', 'epoch', 'memory_generation', 'native_fnv')}
        else:
            request = requests.get(seq)
            require(request is not None and all(number(key) == request[key] for key in request),
                    'Native clip completion is stale/out of order')
            if kind == b'OPERATION':
                require(seq not in completed and fields.get('operation_error') == fields.get('event_error') == '0',
                        'Native clip operation/Close failed')
                completed.add(seq)
            elif kind == b'EVENT_RECEIVED':
                require(seq not in received and fields.get('received') == '1' and fields.get('rc') == '0',
                        'Native clip receive failed/repeated')
                received.add(seq)
            else:
                require(seq in received and seq not in freed and fields.get('received') == '1' and
                        fields.get('rc') == fields.get('operation_error') == '0', 'Native clip free lacks matching receive')
                freed.add(seq)
            if command == 4 and seq in completed and seq in freed:
                closed_epochs.add(epoch)
    require(epochs == closed_epochs and all(seq in completed and seq in freed for seq in requests),
            'Original recording is not closed; use REC Stop/Close and retry shutdown')
    require(not jpeg, 'Original still callback/output lease is not drained; retry shutdown after completion')


def _owned_descendant(identity, owner_pid):
    for _ in range(32):
        if identity['ppid'] == owner_pid:
            return True
        if identity['ppid'] <= 1:
            return False
        identity = transport.process_identity(identity['ppid'])
    return False


def debugger_handoff(run, owner_pid, *, socket_root=None, socket_profile=None, socket_binding=None):
    """Observe closed clients/processes; never stop an observer to steal its lease."""
    root, _ = transport.validate_run(run)
    roots = transport.endpoint_roots(root, socket_root=socket_root,
        socket_profile=socket_profile, socket_binding=socket_binding)
    endpoint_root = root if roots is None else roots.sockets
    for entry in Path('/proc').iterdir():
        if not entry.name.isdecimal():
            continue
        try:
            identity = transport.process_identity(int(entry.name))
            if Path(identity['exe']).name not in ('gdb', 'gdb-multiarch'):
                continue
            command = (entry / 'cmdline').read_bytes().split(b'\0')
            if (any(os.fsencode(root) in arg or os.fsencode(endpoint_root) in arg for arg in command) or
                    (entry / 'cwd').resolve() in (root, endpoint_root)):
                return None
        except (OSError, ValueError):
            continue
    observer_result = None
    if (root / 'hdmi-upm-watch-config.json').exists():
        result = root / 'hdmi-upm-watch-result.json'
        if not result.exists():
            return None
        observer_result = object_json(checked_read(result))
        import hdmi_upm_watch
        observer_config = hdmi_upm_watch.read_config(root / 'hdmi-upm-watch-config.json')
        if observer_config.get('model17c_runtime') is not None:
            require(observer_result.get('model17c_runtime') == observer_config['model17c_runtime'],
                    'model17c result/config binding differs')
            if observer_config.get('mailbox') is None:
                hdmi_upm_watch.model17c_handoff(observer_result)
        require(observer_result.get('detached') is True and not observer_result.get('detach_error') and
                not observer_result.get('breakpoint_cleanup_error'), 'HDMI observer detach is unconfirmed')
    coordinator = root / 'hdmi-upm-coordinator.json'
    if coordinator.exists():
        raw = checked_read(coordinator, allow_empty=True)
        if not raw.endswith(b'}\n'):
            return None
        evidence = object_json(raw)
        cleanup = evidence.get('cleanup', {})
        require(all(cleanup.get(key) is True for key in ('safe_to_close', 'debugger_stopped', 'detached')),
                'HDMI observer coordinator still owns an unsafe debugger')
    candidates = []
    for entry in Path('/proc').iterdir():
        if not entry.name.isdecimal():
            continue
        try:
            identity = transport.process_identity(int(entry.name))
            if Path(identity['exe']).name != 'qemu-system-aarch64' or not _owned_descendant(identity, owner_pid):
                continue
            mounted, actual = (entry / 'root/out').stat(), root.stat()
            if (mounted.st_dev, mounted.st_ino) == (actual.st_dev, actual.st_ino):
                candidates.append(identity)
        except (OSError, ValueError):
            continue
    require(len(candidates) == 1, 'No unique original owner/QEMU run binding')
    qemu = candidates[0]
    sockets = {}
    for name in (GDB, QMP):
        path = endpoint_root / name
        info = path.lstat()
        require(stat.S_ISSOCK(info.st_mode) and info.st_uid == os.getuid(), 'Untrusted functional-camera Unix endpoint')
        if roots is None:
            os.chmod(path, 0o600, follow_symlinks=False)
        try:
            options = {} if roots is None else dict(socket_roots=roots)
            sockets[name] = transport.checked_socket(root, path, qemu['pid'], **options)
        except ValueError as error:
            if str(error) == 'Unix endpoint already has a connected client':
                return None
            raise
    return {'qemu_pid': qemu['pid'], 'qemu_identity': qemu, 'debugger_quiesced': True,
            'sockets': sockets, 'previous_hdmi_observer': observer_result, **transport.endpoint_options(roots)}


def _publish(root, filename, value):
    root, _ = transport.validate_run(root)
    path = root / filename
    require(not path.is_symlink(), 'Runner receipt may not be a symlink')
    pending = root / ('.' + filename + f'.{os.getpid():x}.{threading.get_ident():x}.{os.urandom(8).hex()}.tmp')
    fd = os.open(pending, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC | os.O_NOFOLLOW, 0o600)
    try:
        with os.fdopen(fd, 'w', encoding='ascii') as stream:
            json.dump(value, stream, indent=2, sort_keys=True)
            stream.write('\n')
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(pending, path)
    finally:
        pending.unlink(missing_ok=True)


def _typed_equal(left, right):
    if type(left) is not type(right):
        return False
    if type(left) is dict:
        return left.keys() == right.keys() and all(_typed_equal(left[key], right[key]) for key in left)
    if type(left) is list:
        return len(left) == len(right) and all(_typed_equal(a, b) for a, b in zip(left, right))
    return left == right


def _init_payload(run, reference, event, direction, mailbox, origin, size):
    require(type(reference) is dict, 'Initialization actual payload reference missing')
    expected = dict(path=f'{transport.PAYLOAD_DIRECTORY}/{event["sequence"]:020d}-{direction}.bin',
                    source_kind='actual_hardware_transfer', producer_event=event['event'],
                    sequence=event['sequence'], opcode=transport.INIT, model_instance=mailbox['nonce'],
                    origin=origin, direction=direction, token=0, total=0, offset=0,
                    bytes=size, writeback_verified=True)
    require(all(_typed_equal(reference.get(key), value) for key, value in expected.items()),
            'Initialization payload provenance differs')
    directory = run / transport.PAYLOAD_DIRECTORY
    info = directory.lstat()
    require(stat.S_ISDIR(info.st_mode) and info.st_uid == os.getuid() and stat.S_IMODE(info.st_mode) == 0o700,
            'Initialization payload directory is untrusted')
    path = run / reference['path']
    raw = checked_read(path, 128, allow_empty=True)
    info = path.lstat()
    require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1 and stat.S_IMODE(info.st_mode) == 0o600 and
            all(type(reference.get(key)) is int and reference[key] == value for key, value in
                (('device', info.st_dev), ('inode', info.st_ino), ('bytes', info.st_size),
                 ('mtime_ns', info.st_mtime_ns), ('ctime_ns', info.st_ctime_ns))) and len(raw) == size and
            digest(raw) == reference.get('sha256') == reference.get('writeback_sha256') and
            type(reference.get('fnv1a64')) is int and transport.fnv64(raw) == reference['fnv1a64'],
            'Initialization retained payload identity/digest differs')
    return raw


def initialization_receipt(run, events, mailbox, console):
    responses = [event for event in events if event['kind'] == 'response' and event.get('opcode') == transport.INIT]
    initial = next(iter(responses), None)
    result = {'response': initial, 'sensor_probe_only': True, 'encoder_output_from_INIT': False,
              'rendered': None, 'frame_generation': None, 'source': initial.get('origin') if initial else None,
              'probe_receipt_correlated': False}
    probes = []
    attempts = successes = refusals = 0
    for kind, raw in re.findall(rb'(?:^|\n)OBS FUNCTIONAL_CAMERA_CONTROL_(PROBE(?:_REFUSED)?) ([^\r\n]+)(?=\r?\n)', console):
        tokens = raw.decode('ascii').split()
        require(all(token.count('=') == 1 for token in tokens), 'Malformed initialization probe record')
        fields = dict(token.split('=', 1) for token in tokens)
        require(len(fields) == len(tokens), 'Duplicate initialization probe field')
        def number(key, fields=fields):
            text = fields.get(key, '')
            require(re.fullmatch(r'(?:0x[0-9a-f]+|[0-9]+)', text), 'Nonnumeric initialization probe field: ' + key)
            value = int(text, 16 if text.startswith('0x') else 10)
            require(value < 2**64, 'Initialization probe value exceeds u64: ' + key)
            return value
        require(mailbox is not None and number('pid') == mailbox['pid'], 'Initialization probe PID differs')
        attempts += 1
        refused = kind == b'PROBE_REFUSED'
        refusals += int(refused)
        successes += int(not refused)
        require(number('probe_run_id') == number('probe_attempts') == attempts and
                number('probe_successes') == successes and number('probe_refusals') == refusals,
                'Initialization native probe ledger/counters differ')
        if refused:
            require(number('model_instance') in (0, mailbox['nonce']), 'Initialization refused probe nonce differs')
            continue
        require(number('model_instance') == mailbox['nonce'], 'Initialization probe nonce differs')
        index, command = number('index'), number('native_command')
        require(index in (0, 2) and command in ((0x3000, 0x3003) if index == 0 else (0x4073,)),
                'Initialization probe command/index differs')
        if index == 2:  # MODE probes have their own STATE transaction and counter domain.
            require(probes, 'STATE probe lacks the original control initialization probe')
            continue
        probes.append((raw, fields, number))
    require(len(probes) <= 1, 'Multiple initialization probe records')
    if not probes:
        return result
    raw, fields, number = probes[0]
    probe_id = number('probe_run_id')
    require(0 < probe_id == number('init_run_id') == number('probe_attempts') and number('state_run_id') == 0 and
            number('probe_successes') + number('probe_refusals') == number('probe_attempts') and
            number('probe_successes') == 1 and all(number(key) == 0 for key in ('bridge_rc', 'probe_rc', 'faults')) and
            number('model_initialized') == 1, 'Initialization probe result/counters differ')
    native_fnv = fields.get('native_fnv1a', '')
    require(re.fullmatch('[0-9a-f]{16}', native_fnv), 'Invalid initialization native wire FNV')
    origin = dict(producer_tid=number('tid'), source=number('native_source'),
                  destination=number('native_destination'), command=number('native_command'),
                  bytes=number('native_bytes'), fnv1a64=int(native_fnv, 16))
    requests = [event for event in events if event['kind'] == 'request']
    require(all(type(event.get('sequence')) is int and event['sequence'] == index for index, event in enumerate(requests, 1)),
            'Initialization broker request sequence differs')
    candidates = [event for event in requests if type(event.get('opcode')) is int and
                  event['opcode'] == transport.INIT and _typed_equal(event.get('origin'), origin)]
    require(len(candidates) == 1, 'Initialization probe has no unique broker INIT origin')
    request = candidates[0]
    seq = request['sequence']  # Native probe_run_id is not the mailbox sequence.
    transaction = {}
    for kind in ('core_result', 'response'):
        matches = [event for event in events if event['kind'] == kind and event.get('sequence') == seq]
        require(len(matches) == 1, 'Initialization broker ' + kind + ' missing/ambiguous')
        transaction[kind] = matches[0]
    core, response = transaction['core_result'], transaction['response']
    require(request['event'] < core['event'] < response['event'] and
            all(type(event.get('sequence')) is int and event['sequence'] == seq and
                type(event.get('opcode')) is int and event['opcode'] == transport.INIT and
                type(event.get('model_instance')) is int and event['model_instance'] == mailbox['nonce'] and
                _typed_equal(event.get('origin'), origin) for event in (request, core, response)),
            'Initialization transaction identity/order differs')
    header_hex = request.get('raw_header_hex', '')
    require(type(header_hex) is str and re.fullmatch('[0-9a-f]{1024}', header_hex),
            'Initialization raw request header missing/invalid')
    header = bytes.fromhex(header_hex)
    incoming = _init_payload(run, request.get('request_payload'), request, 'in', mailbox, origin, 0)
    require(transport.validate_request(header, incoming, mailbox, seq - 1)[0] == transport.INIT and
            transport.u64(header, 24) == seq and transport.u32(header, 40) >= 128 and
            _typed_equal(transport.origin(header), origin) and digest(header) == request.get('raw_header_sha256') and
            type(request.get('request_bytes')) is int and request['request_bytes'] == 0 and
            type(request.get('request_fnv1a64')) is int and request['request_fnv1a64'] == transport.fnv64(incoming) and
            request.get('request_sha256') == digest(incoming), 'Initialization raw request differs')
    state = _init_payload(run, core.get('output_payload'), core, 'out', mailbox, origin, 128)
    expected = dict(actual_c_result=0, returned_bytes=128, returned_sha256=digest(state),
                    returned_fnv1a64=transport.fnv64(state), token=0, total=0, offset=0,
                    request_payload=request['request_payload'], output_payload=core['output_payload'], result_transfer=None)
    require(all(_typed_equal(event.get(key), value) for event in (core, response) for key, value in expected.items()) and
            response.get('data_readback') is True and response.get('raw_header_sha256') == digest(header),
            'Initialization actual response/readback differs')
    committed = bytearray(header)
    struct.pack_into('<I', committed, 12, transport.RESPONSE)
    struct.pack_into('<Ii', committed, 44, 128, 0)
    struct.pack_into('<4Q', committed, 64, transport.fnv64(state), 0, 0, 0)
    require(response.get('response_header_sha256') == digest(committed), 'Initialization committed response differs')
    require(struct.unpack_from('<2I', state) == (1, 15) and transport.u64(state, 48) == mailbox['nonce'] and
            state[104:112] == bytes(8) and state[120:] == bytes(8), 'Initialization State128 identity/reserved differs')
    counters = {key: transport.u64(state, offset) for key, offset in
                (('config_generation', 56), ('rendered', 64), ('consumed', 72), ('jpeg_encoded', 80),
                 ('video_encoded', 88), ('frame_generation', 112))}
    require(all(counters[key] > 0 for key in ('config_generation', 'rendered', 'frame_generation')) and
            all(number(key) == counters[key] for key in ('config_generation', 'rendered', 'frame_generation')),
            'Initialization probe State128 counters differ')
    frames = [event for event in events if event['kind'] == 'model_frame' and event['event'] < response['event']]
    repeated = any(event['event'] < request['event'] and event.get('actual_c_result') == 0 for event in responses)
    require(frames and sum(event.get('sequence') == seq for event in frames) == (0 if repeated else 1),
            'Initialization repeated INIT invented/missing render probe')
    frame = frames[-1]
    proof = frame.get('proof', {})
    require(type(proof) is dict and type(proof.get('after')) is dict and
            type(frame.get('sequence')) is int and type(frame.get('opcode')) is int and
            any(event['sequence'] == frame['sequence'] and event['opcode'] == frame['opcode'] and
                _typed_equal(event.get('origin'), frame.get('origin')) for event in requests) and
            _typed_equal(proof.get('model_instance'), mailbox['nonce']) and
            _typed_equal(proof.get('config_generation'), counters['config_generation']) and
            _typed_equal(proof.get('frame_generation'), counters['frame_generation']) and
            all(_typed_equal(proof.get('after', {}).get(key), counters[key]) for key in
                ('rendered', 'consumed', 'jpeg_encoded', 'video_encoded')),
            'Initialization State128 differs from actual frame checkpoint')
    result.update(response=response, source=origin, rendered=counters['rendered'], frame_generation=counters['frame_generation'],
                  config_generation=counters['config_generation'], consumed=counters['consumed'],
                  console_probe_record=raw.decode('ascii'), probe_run_id=probe_id, probe_receipt_correlated=True)
    return result


class UnsafeCameraClose(RuntimeError):
    """The owning process must remain alive until the retained VM exits."""


def parse_hdmi_mailbox(console):
    """Bind only complete original observer records; repeated serial readback is harmless."""
    found = None
    for line in console.splitlines(keepends=True):
        if not line.endswith(b'\n'):
            continue
        match = re.fullmatch(rb'(?:OBS )?FULL_HDMI_UPM_MAILBOX_INIT (.+)\r?\n', line)
        if match is None:
            continue
        fields = dict(item.split(b'=', 1) for item in match[1].split())
        required = {b'pid', b'tid', b'user_va', b'physical', b'bytes', b'nonce', b'upm_text',
                    b'osal_text', b'version', b'record_bytes', b'lease', b'U', b'index', b'raw', b'effective'}
        require(set(fields) == required, 'Incomplete HDMI/UPM mailbox announcement')
        require(all(fields[k] == value for k, value in ((b'bytes', b'4096'), (b'version', b'1'),
                    (b'record_bytes', b'256'), (b'index', b'0'),
                    (b'raw', b'170192000000000000009a0000000000'),
                    (b'effective', b'170192000000000000009a0000000000'))),
                'HDMI/UPM mailbox ABI or first native message differs')
        value = dict(mailbox={k: int(fields[f], 0) for k, f in
                     (('phys', b'physical'), ('nonce', b'nonce'), ('pid', b'pid'))},
                     module_texts={k: int(fields[f], 0) for k, f in
                     (('upm', b'upm_text'), ('osal_uipc', b'osal_text'))})
        require(found is None or found == value, 'HDMI/UPM mailbox owner changed')
        found = value
    return found


class FunctionalCameraRunner:
    def __init__(self, run, artifact, *, socket_root=None, socket_profile=None, socket_binding=None):
        self.run, _ = transport.validate_run(run)
        roots = transport.endpoint_roots(self.run, socket_root=socket_root,
            socket_profile=socket_profile, socket_binding=socket_binding)
        self.socket_options = transport.endpoint_options(roots)
        self.endpoint_root = self.run if roots is None else roots.sockets
        self.artifact = artifact
        self.owner = transport.process_identity(os.getpid())
        self.coordination_lock = threading.RLock()
        self.done = threading.Event()
        self.thread = self.broker = self.proc = None
        self.binding = self.handoff = self.cleanup = self.error = self.startup_cleanup = None
        self.hdmi_watch = self.hdmi_binding = self.hdmi_cleanup = None
        self.model17c_startup = self.model17c_events_size = None
        self.model17c_identity = None
        self.model17c_identity_only = False
        self.model17c_startup_deadline = None
        self.model17c_console_base = 0
        self.model17c_handed_off = False
        self.run_allowed = True
        self.closed = False
        self.final_receipts = None
        self._publish('preflight')

    def _check_owner(self):
        require(os.getpid() == self.owner['pid'], 'Functional-camera runner owner changed/forked')
        actual = transport.process_identity(os.getpid())
        require(all(actual[key] == self.owner[key] for key in ('pid', 'starttime', 'exe')),
                'Functional-camera runner owner changed/forked')

    def start(self, proc):
        self._check_owner()
        require(self.thread is None and not self.closed, 'Functional-camera runner already started/closed')
        self.proc = proc
        self.thread = threading.Thread(target=self._watch, name='functional-camera-runner', daemon=True)
        self.thread.start()

    @contextmanager
    def ram_card_process(self, native, environment, initramfs_binding, qemu_binary, *,
                         parallel_peak_bytes, stdout, stderr, output_parent=None,
                         scope_build_receipt=None, internal=None, model_base=None):
        """Borrow the exact producer FDs until confirmed exit; caller owns QMP/serial.

        initramfs_binding must be a trusted derive() return or independently
        SHA-verified v3 receipt. The launcher verifies host FDs before bwrap
        preserves them, binds their read-only inodes, or hands the leased
        internal disk over SCM_RIGHTS (same OFD, never a reopened path).
        No sandbox transport alone is guest acceptance.
        internal carries the sixth, independently leased internal-disk descriptor of
        the explicit settings-restart profile; it is never a pathname fallback.
        The existing probe does not call this candidate entry point.
        """
        self._check_owner()
        require(environment.get('A7C2_FUNCTIONAL_RAM_CONSUMER') == RAM_CONSUMER_PROFILE,
                'Functional RAM consumer is off; explicit opt-in required')
        require(self.proc is None and self.thread is None and not self.closed,
                'Functional RAM consumer requires an unused runner')
        if capture_sockets.PROFILE == self.socket_options.get('socket_profile'):
            require(internal is not None, 'Capture short sockets require the separately leased settings disk')
            capture_roots = transport.endpoint_roots(self.run, **self.socket_options)
            socket_launch = capture_roots.launch()
        else:
            socket_launch = nullcontext(({}, None))
        require(not set(environment).intersection((capture_sockets.PROFILE_ENV, capture_sockets.ROOT_ENV, capture_sockets.FD_ENV)),
                'Only the runner supplies capture socket launch parameters')
        from menu_live import owner_signal_guard, retain_running_owner
        result = dict(schema='a7c2-functional-ram-consumer-v1', profile=RAM_CONSUMER_PROFILE,
                      host_fd_binding_verified=False, fd_inheritance_requested=False,
                      consumer_endpoint_verified=False, guest_consumption_verified=False,
                      sealed_memfd_verified=False, capture_verified=False, runtime_verified=False,
                      physical_compatible=False, process_exit_observed=False)
        try:
            # Keep both accepted-build guards, including the scope build receipt.
            result['actual_qemu_sha256'] = digest(checked_read(qemu_binary, 256 * 1024 * 1024))
            if model_base is not None:
                require(internal is not None and capture_sockets.PROFILE == self.socket_options.get('socket_profile'),
                        'Alternate model requires the isolated capture route')
                model_base = Path(model_base)
                require(model_base.is_absolute() and model_base.resolve(strict=True) == model_base and
                        checked_read(model_base / 'functional-camera-abi.h') == checked_read(Path(native) / 'functional-camera-abi.h'),
                        'Isolated model path or ABI differs')
            artifact = validate_artifact(native if model_base is None else model_base, qemu_binary,
                                         scope_build_receipt=scope_build_receipt)
            require(artifact == self.artifact, 'RAM consumer differs from prepared model/QEMU artifact')
            ram_initramfs.verify_for_consumer(initramfs_binding)
            model_options = {} if model_base is None else {'model_base': model_base}
            with owner_signal_guard(), socket_launch as (socket_env, socket_fd), backup_profile.ram_profile_lease(
                    native, environment, output_parent, parallel_peak_bytes=parallel_peak_bytes,
                    **model_options) as lease:
                merged = {**environment, **lease['environment'], **socket_env}
                selected_qemu = Path(merged['QEMU_SYSTEM_DIR']) / merged['QEMU_SYSTEM_BINARY']
                require(selected_qemu == Path(qemu_binary), 'RAM profile selected a different QEMU executable')
                lease['verify']()
                seed_fd, directory_fd, receipt_fd = lease['pass_fds']
                receipt_raw = os.pread(receipt_fd, 16 * 1024 * 1024 + 1, 0)
                require(len(receipt_raw) <= 16 * 1024 * 1024, 'Oversized RAM profile receipt')
                receipt = object_json(receipt_raw)
                seed_sha = ram_initramfs.sha_range(seed_fd, 0, os.fstat(seed_fd).st_size)
                require(seed_sha == receipt.get('media_seed_sha256') == initramfs_binding['seed']['sha256'],
                        'Leased seed differs from the derived initramfs payload')
                launcher = Path(merged['MENU_KERNEL_SCRIPT'])
                launcher_raw = checked_read(launcher)
                require(digest(launcher_raw) == receipt.get('derived_script_sha256') and
                        b'A7C2_RAM_CARD_LAUNCH_PROFILE' in launcher_raw,
                        'RAM launcher lacks the reviewed inherited-FD sandbox protocol')
                if internal is not None:
                    # Reuse the product identity/OFD/quarantine checks, never a bare path.
                    require(environment.get('A7C2_SETTINGS_RESTART_PROFILE') == SETTINGS_RESTART_PROFILE,
                            'Internal settings disk requires the exact explicit profile')
                    from persistent_storage import inherited_fd as persistent_inherited_fd
                    require(persistent_inherited_fd(merged) == internal['fd'],
                            'Inherited internal descriptor differs from its identity')
                    require(b'A7C2_SETTINGS_RESTART_PROFILE' in launcher_raw and
                            b'--preserve-fds' in launcher_raw and
                            b'ram_card_fd_receiver.py' in launcher_raw,
                            'launcher lacks the combined internal-disk handoff protocol')
                with ram_initramfs.source(Path(initramfs_binding['output']['path'])) as (archive_fd, info, unchanged), \
                        ram_initramfs.source(Path(qemu_binary)) as (qemu_fd, qinfo, qcheck):
                    require(ram_initramfs.metadata(info) == initramfs_binding['output']['identity'] and
                            ram_initramfs.sha_range(archive_fd, 0, info.st_size) == initramfs_binding['output']['sha256'],
                            'Inherited initramfs differs from trusted derivation')
                    require(ram_initramfs.sha_range(qemu_fd, 0, qinfo.st_size) == artifact['qemu_sha256'],
                            'Inherited executable differs from accepted QEMU')
                    pass_fds = (*lease['pass_fds'], archive_fd, qemu_fd)
                    if internal is not None:
                        require(len(set(pass_fds)) == 5 and internal['fd'] not in pass_fds,
                                'Internal descriptor aliases a RAM input')
                        pass_fds = (*pass_fds, internal['fd'])
                        require(len(set(pass_fds)) == 6, 'Combined consumer descriptor aliases')
                    else:
                        require(len(set(pass_fds)) == 5, 'RAM consumer descriptor aliases')
                    if socket_fd is not None:
                        require(socket_fd not in pass_fds and b'A7C2_CAPTURE_SOCKET_FD' in launcher_raw,
                                'Capture short-socket directory handoff missing or overlaps an owned input')
                        pass_fds = (*pass_fds, socket_fd)
                        result.update(schema='a7c2-functional-ram-consumer-v2', capture_socket_dirfd=socket_fd,
                                      capture_socket_binding=self.socket_options['socket_binding'])
                    merged.update(A7C2_RAM_CARD_LAUNCH_PROFILE=RAM_CONSUMER_PROFILE,
                                  A7C2_RAM_CARD_INITRAMFS_FD=str(archive_fd),
                                  A7C2_RAM_CARD_QEMU_FD=str(qemu_fd),
                                  A7C2_RAM_CARD_INITRAMFS_SHA256=initramfs_binding['output']['sha256'],
                                  A7C2_RAM_CARD_SEED_SHA256=seed_sha,
                                  A7C2_RAM_CARD_RECEIPT_SHA256=digest(receipt_raw),
                                  A7C2_RAM_CARD_QEMU_SHA256=artifact['qemu_sha256'],
                                  QEMU_OUTPUT_DIR=str(self.run))
                    command = ['bash', str(launcher), '4096', merged['MENU_DTB'], '1', '1',
                               initramfs_binding['output']['path']]
                    result.update(host_fd_binding_verified=True, pass_fds=list(pass_fds),
                                  seed_sha256=seed_sha, initramfs_sha256=initramfs_binding['output']['sha256'],
                                  settings_restart_profile=None if internal is None else SETTINGS_RESTART_PROFILE,
                                  internal_fd=None if internal is None else internal['fd'])
                    lease['verify'](); unchanged(); qcheck()
                    _publish(self.run, RAM_CONSUMER_RECEIPT, result)
                    proc = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=stdout, stderr=stderr,
                                            env=merged, pass_fds=pass_fds)
                    result.update(fd_inheritance_requested=True, process_pid=proc.pid)
                    original = None
                    try:
                        self.start(proc)
                        _publish(self.run, RAM_CONSUMER_RECEIPT, result)
                        yield proc
                    except BaseException as error:
                        original = error
                        raise
                    finally:
                        try:
                            self.guard_shutdown(proc, original)
                        except BaseException as cleanup_error:
                            if original is None:
                                raise
                            original.add_note('RAM consumer shutdown failed: ' + repr(cleanup_error))
                        finally:
                            # No quit/signal/kill: never release FDs while exit is unknown.
                            retain_running_owner(proc, self.run, original, reason='qmp-exit')
                            result.update(process_exit_observed=True, returncode=proc.returncode)
                    lease['verify'](); unchanged(); qcheck()
        except BaseException as error:
            result['error'] = f'{type(error).__name__}: {error}'
            result['error_notes'] = list(getattr(error, '__notes__', ()))
            try:
                _publish(self.run, RAM_CONSUMER_RECEIPT, result)
            except BaseException as save_error:
                error.add_note('RAM consumer receipt save failed: ' + repr(save_error))
            raise
        else:
            _publish(self.run, RAM_CONSUMER_RECEIPT, result)

    def arm_model17c(self, raw):
        """Called by the serial owner before its original AP launch command."""
        self._check_owner()
        require(self.proc is not None and self.broker is None and self.hdmi_watch is None and
                self.model17c_startup is None, 'Early model17c requires the unused debugger owner')
        import hdmi_upm_watch
        import model17c_startup
        startup = model17c_startup.metadata(raw, Path(__file__).resolve().parent)
        if not self.socket_options:
            os.chmod(self.endpoint_root / GDB, 0o600, follow_symlinks=False)
        for attempt in (1, 2):
            # The early GDB↔QEMU remote channel is intermittently flaky (internal
            # crash, wedge, broken pipe). A dead early GDB is a host process:
            # retry once with a fresh GDB instead of burning a full guest boot.
            try:
                self.hdmi_watch = hdmi_upm_watch.start(self.run, self.owner['pid'], startup['module_texts'],
                    None, self.artifact.get('scope_build_receipt'), model17c_startup=startup, **self.socket_options)
                break
            except BaseException as error:
                failed = getattr(error, 'hdmi_upm_watcher', None)
                cleanup = getattr(error, 'hdmi_upm_cleanup', None)
                if failed is not None:
                    try:
                        failed.stop()
                    except BaseException:
                        pass
                retryable = attempt == 1 and isinstance(error, (TimeoutError, RuntimeError, ValueError))
                if not retryable:
                    self.hdmi_watch = failed
                    self.hdmi_cleanup = cleanup
                    raise
                for path in sorted(self.run.glob('model17c-startup-*')):
                    archive = self.run / (path.name + '-retry1')
                    if not archive.exists():
                        path.rename(archive)
                _publish(self.run, 'model17c-startup-retry.json', dict(
                    attempt=2, original_error=f'{type(error).__name__}: {error}', vm_signalled=False))
        self._publish('model17c-early-breakpoint-armed')
        # Bounded startup phase: the mmap window self-bounds at 300s inside the
        # GDB script; a wedged GDB (e.g. descriptor exhaustion) must fail the
        # run honestly instead of holding the owner forever.
        self.model17c_startup_deadline = time.monotonic() + 900
        console = self.run / 'console.log'
        self.model17c_console_base = console.stat().st_size if console.exists() else 0
        # Publish the model17c route last: the worker must never observe a live
        # hdmi_watch with a None startup deadline while this method is arming.
        self.model17c_startup = startup

    def _guest_exception_recovery(self, context):
        """A guest crash during the armed startup phase: prove QMP responsive,
        issue one quit, then close only this runner's exact GDB pid. The VM
        itself is never signalled."""
        import socket as _socket
        receipt = dict(schema='a7c2-guest-crash-recovery-v1', context=context[:512],
                       signals_to_vm=[], ts=time.strftime('%Y-%m-%dT%H:%M:%SZ'))
        for name in ('lcd-qmp.sock', 'hdmi-upm-control.sock'):
            endpoint = self.endpoint_root / name if not self.socket_options else None
            if endpoint is None:
                continue
            try:
                client = _socket.socket(_socket.AF_UNIX, _socket.SOCK_STREAM)
                client.settimeout(8)
                client.connect(str(endpoint))
                stream = client.makefile('rw')
                json.loads(stream.readline())
                client.sendall(json.dumps({'execute': 'qmp_capabilities'}).encode() + b'\n')
                json.loads(stream.readline())
                client.sendall(json.dumps({'execute': 'query-status'}).encode() + b'\n')
                receipt['last_status'] = json.loads(stream.readline()).get('return')
                client.sendall(json.dumps({'execute': 'quit', 'id': 'guest-crash-1'}).encode() + b'\n')
                try:
                    stream.readline()
                except OSError:
                    pass
                client.close()
                receipt['quit_via'] = name
                break
            except OSError as error:
                receipt.setdefault('probe_errors', []).append(f'{name}: {error}')
        self._publish('model17c-guest-crash.json', receipt)
        if self.hdmi_watch is not None and self.hdmi_watch.process is not None:
            pid = self.hdmi_watch.process.pid
            if self.hdmi_watch.process.poll() is None:
                import signal as _signal
                for sig in (_signal.SIGTERM, _signal.SIGKILL):
                    try:
                        os.kill(pid, sig)
                    except OSError:
                        break
                    for _ in range(25):
                        time.sleep(0.2)
                        try:
                            os.kill(pid, 0)
                        except OSError:
                            break
                    else:
                        continue
                    break
            receipt['gdb_pid'] = pid
        with (self.run / 'model17c-guest-crash-recovery.json').open('x') as out:
            json.dump(receipt, out, indent=2)

    def _handoff_model17c_startup(self):
        """Replace the exited early GDB with a fresh runtime observer process."""
        import hdmi_upm_watch as h
        early = self.hdmi_watch
        require(early is not None and early.process.poll() == 0 and not self.model17c_handed_off,
                'Early model17c GDB did not exit cleanly for separate-process handoff')
        stop = object_json(checked_read(self.run / 'model17c-startup-stop.json', 128 * 1024))
        result = object_json(checked_read(self.run / 'model17c-startup-result.json', 16 * 1024))
        require(stop.get('schema') == 'a7c2-model17c-startup-stop-v2' and
                stop.get('handoff') == 'separate-gdb-process-v1' and
                stop.get('early_breakpoints_deleted') is True,
                'Early model17c stop receipt is incomplete')
        runtime_binding = h.model17c_binding(stop['binding'], None)
        require(runtime_binding == stop.get('runtime_binding'),
                'Early model17c runtime binding differs at handoff')
        binding_sha = hashlib.sha256(json.dumps(runtime_binding, sort_keys=True).encode('ascii')).hexdigest()
        require(result == dict(schema='a7c2-model17c-startup-detached-v1', detached=True,
                               separate_process_handoff=True, early_breakpoints_remaining=[],
                               runtime_binding_sha256=binding_sha),
                'Early model17c did not prove detach and breakpoint cleanup')
        if early.log is not None:
            early.log.close()
            early.log = None
        _publish(self.run, 'model17c-startup-coordinator.json', result)
        if getattr(self, 'model17c_identity_only', False):
            # Keep the detached early AP identity, but do not stop the guest on
            # runtime model17c probes before the UPM mailbox announcement.
            # The normal mailbox route reuses this identity for native task/TID
            # evidence and takes the GDB socket directly, with no yield race.
            self.model17c_identity = stop['binding']
            self.hdmi_watch = self.hdmi_cleanup = self.hdmi_binding = None
            self.model17c_startup = None
            self.model17c_events_size = None
            self.model17c_handed_off = True
            return
        try:
            runtime = h.start(self.run, self.owner['pid'], self.model17c_startup['module_texts'],
                              None, self.artifact.get('scope_build_receipt'),
                              model17c_runtime=stop['binding'], **self.socket_options)
        except BaseException as error:
            self.hdmi_watch = getattr(error, 'hdmi_upm_watcher', early)
            self.hdmi_cleanup = getattr(error, 'hdmi_upm_cleanup', None)
            raise
        self.hdmi_watch = runtime
        self.hdmi_binding = dict(model17c_runtime=runtime.config['model17c_runtime'])
        self.model17c_events_size = None
        self.model17c_handed_off = True

    def _observe_model17c(self):
        import hdmi_upm_watch as h
        error_path = self.run / 'model17c-startup-error.json'
        require(not error_path.exists(), 'Early model17c failed; GDB/VM owner retained without signals')
        if self.hdmi_watch is not None and self.hdmi_watch.process.poll() is None:
            # Only the short-lived early process has a startup deadline. Its
            # fresh runtime successor may observe the entire capture lifecycle.
            if not self.model17c_handed_off:
                require(time.monotonic() < self.model17c_startup_deadline,
                        'model17c startup observer did not complete within its bounded window')
            # Active abort: a guest crash into the exception monitor while the
            # startup observer waits for the appFw mmap can never complete;
            # raise immediately with the crash context instead of idling.
            console = self.run / 'console.log'
            if console.exists():
                base = getattr(self, 'model17c_console_base', 0)
                size = console.stat().st_size
                if size > base:
                    with console.open('rb') as stream:
                        stream.seek(max(0, base))
                        appended = stream.read(min(size - base, 256 * 1024))
                    if b'Exception> ' in appended:
                        head = appended[appended.index(b'Exception>') - 400:appended.index(b'Exception>')]
                        self._guest_exception_recovery(
                            'guest exception monitor while model17c startup armed: ' +
                            head.decode('ascii', 'replace'))
                        raise ValueError('Guest crashed into the exception monitor during the '
                                         'model17c startup window (see model17c-guest-crash.json)')
        if not self.model17c_handed_off and self.hdmi_watch.process.poll() is not None:
            try:
                self._handoff_model17c_startup()
            except BaseException as error:
                import traceback
                _publish(self.run, 'model17c-handoff-error.json', dict(
                    error=f'{type(error).__name__}: {error}', traceback=traceback.format_exc()))
                raise
            if self.hdmi_watch is None:
                return
        if self.model17c_handed_off and self.hdmi_watch is not None and self.hdmi_watch.process.poll() is None:
            # The guest's FULL_HDMI_UPM mailbox needs a HOST watch carrying that
            # exact mailbox binding; the read-only model17c observer must yield
            # so the functional mailbox watch can take the single GDB socket.
            console_bytes = (self.run / 'console.log').read_bytes()
            upm = parse_hdmi_mailbox(console_bytes)
            if upm is not None:
                # Capture the yielded observer's AP identity before it stops:
                # the mailbox watch needs it for native producer task/TID evidence.
                runtime_identity = self.hdmi_watch.config.get('model17c_runtime')
                if runtime_identity is not None:
                    # The runtime binding carries archival digest keys the exact
                    # mailbox contract rejects; pass the identity subset only.
                    runtime_identity = {key: value for key, value in runtime_identity.items()
                                        if key not in ('asset_sha256', 'maps_sha256')}
                _publish(self.run, 'model17c-yield.json', dict(
                    reason='upm-mailbox-announcement', upm_mailbox=upm['mailbox']))
                import signal as _signal
                pid = self.hdmi_watch.process.pid
                os.kill(pid, _signal.SIGINT)
                grace = time.monotonic() + 10
                while self.hdmi_watch.process.poll() is None and time.monotonic() < grace:
                    time.sleep(.2)
                forced = None
                if self.hdmi_watch.process.poll() is None:
                    # The embedded-Python signal path can wedge; this is our own
                    # host observer process (never the VM). QEMU clears all GDB
                    # breakpoints when the client socket closes.
                    forced = 'SIGTERM'
                    os.kill(pid, _signal.SIGTERM)
                    grace = time.monotonic() + 5
                    while self.hdmi_watch.process.poll() is None and time.monotonic() < grace:
                        time.sleep(.2)
                if self.hdmi_watch.process.poll() is None:
                    forced = 'SIGKILL'
                    os.kill(pid, _signal.SIGKILL)
                deadline = time.monotonic() + 10
                while self.hdmi_watch.process.poll() is None and time.monotonic() < deadline:
                    time.sleep(.2)
                require(self.hdmi_watch.process.poll() is not None,
                        'model17c runtime observer did not yield to the UPM mailbox watch')
                if forced is not None:
                    _publish(self.run, 'model17c-yield-force.json', dict(
                        pid=pid, final_signal=forced, reason='observer cleanup wedged after SIGINT',
                        vm_signalled=False))
                    self.hdmi_cleanup = dict(debugger_stopped=True, detached=False,
                                             safe_to_close=True, forced_yield=True,
                                             errors=['yield-forced: ' + forced])
                else:
                    self._close_hdmi()
                # Archive the read-only phase under its own names so the mailbox
                # watch can create the canonical config/events/result files.
                # Archive every canonical watch artifact of the read-only phase
                # so the mailbox watch can exclusively create the same names.
                for path in sorted(self.run.glob(h.PREFIX + '*')):
                    archive = self.run / ('model17c-watch' + path.name[len(h.PREFIX):])
                    if not archive.exists():
                        path.rename(archive)
                _publish(self.run, 'model17c-phase-complete.json', dict(
                    phase='model17c-readonly-observer', yielded_to='functional-mailbox-watch',
                    receipts_required_from='mailbox-watch'))
                # Continue in the normal functional path: mailbox watch + broker.
                import hdmi_upm_watch
                self.hdmi_watch = self.hdmi_cleanup = None
                self.model17c_events_size = None
                self.hdmi_binding = upm
                self.model17c_startup = None  # mailbox route owns the socket from here
                self.binding = None
                # Keep the early binding as identity-only evidence: mailbox mode
                # does not install model17c probes, but needs per-cpu symbols to
                # resolve the actual native producer task/TID for UPM receipts.
                runtime_identity = runtime_identity  # captured at yield start
                require(runtime_identity is not None, 'Yielded mailbox watch lost the AP identity binding')
                try:
                    self.hdmi_watch = hdmi_upm_watch.start(self.run, self.owner['pid'],
                        upm['module_texts'], upm['mailbox'],
                        self.artifact.get('scope_build_receipt'), seconds=2700,
                        model17c_runtime=runtime_identity, **self.socket_options)
                except BaseException as error:
                    self.hdmi_watch = getattr(error, 'hdmi_upm_watcher', None)
                    self.hdmi_cleanup = getattr(error, 'hdmi_upm_cleanup', None)
                    raise
                self._publish('hdmi-upm-observer-armed')
                return
        config_path = self.run / 'hdmi-upm-watch-config.json'
        if config_path.exists():
            config = h.read_config(config_path)
            require(config.get('model17c_runtime') is not None, 'Actual model17c binding missing')
            self.hdmi_watch.config = config
            self.hdmi_binding = dict(model17c_runtime=config['model17c_runtime'])
            events = self.run / 'hdmi-upm-watch-events.jsonl'
            size = events.stat().st_size if events.exists() else None
            if size is not None and size != self.model17c_events_size:
                self.model17c_events_size = size
                try:
                    receipts = h.read_receipts(self.run)
                except ValueError as error:
                    if str(error) != 'Incomplete published event line':
                        raise
                else:
                    for receipt in receipts:
                        if not (self.run / ('hdmi-upm-watch-ack-' + str(receipt['bridge_seq']) + '.json')).exists():
                            h.ack_receipt(self.run, receipt['bridge_seq'])
        if self.hdmi_watch.process.poll() is not None and self.hdmi_cleanup is None:
            self._close_hdmi()
            result = object_json(checked_read(self.run / 'hdmi-upm-watch-result.json'))
            mailbox_route = isinstance(self.hdmi_binding, dict) and self.hdmi_binding.get('mailbox') is not None
            if not mailbox_route:
                h.model17c_handoff(result)
            require(not result.get('error') and result.get('receipts') == 2,
                    'model17c H observer did not prove both original native lifetimes')

    def _close_hdmi(self):
        if self.hdmi_watch is None:
            return
        self.hdmi_cleanup = self.hdmi_watch.stop()
        _publish(self.run, 'hdmi-upm-coordinator.json',
                 dict(owner=self.owner, binding=self.hdmi_binding, cleanup=self.hdmi_cleanup))
        require(self.hdmi_cleanup.get('safe_to_close') is True and
                self.hdmi_cleanup.get('errors') == [], 'HDMI/UPM debugger detach unconfirmed')

    def _observe_hdmi(self, console):
        if self.model17c_startup is not None:
            if self.hdmi_watch is not None:
                self._observe_model17c()
            return
        binding = parse_hdmi_mailbox(console)
        if binding is None:
            return
        require(self.hdmi_binding is None or self.hdmi_binding == binding,
                'HDMI/UPM producer changed after observer startup')
        if os.environ.get('A7C2_HDMI_UPM_DISABLE') == '1':
            self.hdmi_binding = binding
            return
        if self.hdmi_watch is None and not (self.run / 'hdmi-upm-watch-config.json').exists():
            require(self.broker is None, 'HDMI observer cannot acquire the active camera debugger')
            import hdmi_upm_watch
            if not self.socket_options:
                os.chmod(self.endpoint_root / GDB, 0o600, follow_symlinks=False)
            self.hdmi_binding = binding
            identity = getattr(self, 'model17c_identity', None)
            try:
                self.hdmi_watch = hdmi_upm_watch.start(self.run, self.owner['pid'],
                    binding['module_texts'], binding['mailbox'],
                    self.artifact.get('scope_build_receipt'),
                    seconds=2700 if identity is not None else None,
                    model17c_runtime=identity, **self.socket_options)
            except BaseException as error:
                self.hdmi_watch = getattr(error, 'hdmi_upm_watcher', None)
                self.hdmi_cleanup = getattr(error, 'hdmi_upm_cleanup', None)
                raise
            self._publish('hdmi-upm-observer-armed')
        if self.hdmi_watch is not None and self.hdmi_watch.process.poll() is not None and self.hdmi_cleanup is None:
            self._close_hdmi()
            result = object_json(checked_read(self.run / 'hdmi-upm-watch-result.json'))
            require(not result.get('error') and result.get('receipts') == 2,
                    'HDMI/UPM observer did not prove both original native lifetimes')

    def _watch(self):
        try:
            monitor = FirmwareMonitor(self.run / 'console.log')
            deadline = None
            while not self.done.is_set():
                self._check_owner()
                monitor.check()
                console = (self.run / 'console.log').read_bytes()
                self._observe_hdmi(console)
                observed = parse_mailbox(console)
                if observed:
                    require(self.binding is None or self.binding['mailbox'] == observed['mailbox'], 'Functional mailbox owner changed')
                    self.binding = observed
                    hdmi_pid = (None if self.hdmi_binding is None else
                        self.hdmi_binding['model17c_runtime']['pid'] if self.model17c_startup is not None else
                        self.hdmi_binding['mailbox']['pid'])
                    require(hdmi_pid is None or observed['mailbox']['pid'] == hdmi_pid,
                            'Functional camera and HDMI/UPM belong to different AP processes')
                    if deadline is None:
                        deadline = time.monotonic() + 20  # Guest exchange has an actual 30-second deadline.
                        self._publish('waiting-for-debugger-handoff')
                    if self.broker is None:
                        handoff = debugger_handoff(self.run, self.owner['pid'], **self.socket_options)
                        if handoff is not None:
                            monitor.check()
                            if self.done.is_set():
                                break
                            self.handoff = handoff
                            self.broker = transport.start(self.run, self.owner['pid'], self.binding['mailbox'],
                                self.artifact['library'], qemu_pid=handoff['qemu_pid'],
                                qemu_sha256=self.artifact['qemu_sha256'], library_sha256=self.artifact['library_sha256'],
                                gdb_socket=self.endpoint_root / GDB, qmp_socket=self.endpoint_root / QMP,
                                coordination_lock=self.coordination_lock, debugger_quiesced=True,
                                resume_allowed=lambda: self.run_allowed and self.proc.poll() is None,
                                seconds=3600.0, io_timeout=1.0, **self.socket_options)
                            self._publish('attached')
                        elif time.monotonic() >= deadline:
                            raise TimeoutError('Functional mailbox guest deadline: previous debugger lease did not close')
                if self.broker is not None and self.broker.start_error is not None:
                    raise self.broker.start_error
                if self.proc.poll() is not None:
                    raise RuntimeError('Owned VM exited while functional-camera runner was active')
                self.done.wait(.05)
        except BaseException as error:
            if getattr(error, 'functional_camera_broker', None) is not None:
                self.broker = error.functional_camera_broker
                self.startup_cleanup = getattr(error, 'functional_camera_cleanup', None)
            self.error = f'{type(error).__name__}: {error}'
            if isinstance(error, FirmwareFault):
                self.done.set()
                if self.broker is not None:
                    try:
                        require_capture_closed(self.run)
                    except BaseException as capture_error:
                        self.cleanup = {**dict.fromkeys(CLOSE_FIELDS, False),
                            'errors': [f'Firmware fault cleanup blocked: {type(capture_error).__name__}: {capture_error}']}
                    else:
                        self._stop_broker()
            self._publish('failed')

    def _stop_broker(self):
        try:
            self.cleanup = self.broker.stop()
        except BaseException as error:
            actual = getattr(self.broker, 'cleanup', None)
            actual = actual if type(actual) is dict else {}
            self.cleanup = {**dict.fromkeys(CLOSE_FIELDS, False), **actual, 'safe_to_close': False,
                            'errors': [*actual.get('errors', []), f'{type(error).__name__}: {error}']}

    def check(self):
        self._check_owner()
        if self.error:
            raise RuntimeError(self.error)
        if self.broker is not None and self.broker.start_error is not None:
            raise RuntimeError('Functional-camera broker failed') from self.broker.start_error

    @contextmanager
    def qmp_command(self, name):
        self._check_owner()
        if name == 'quit':
            self.before_close('qmp-quit')
        with self.coordination_lock:
            yield
            if name in ('stop', 'quit'):
                self.run_allowed = False
            elif name == 'cont':
                self.run_allowed = True

    def receipt(self, phase):
        result = {'schema': 'functional-camera-runner-v1', 'profile': FUNCTIONAL_CAMERA_PROFILE,
                  'phase': phase, 'owner': self.owner, 'artifact': self.artifact,
                  'mailbox_evidence': self.binding, 'debugger_handoff': self.handoff,
                  'cleanup': self.cleanup, 'startup_cleanup': self.startup_cleanup,
                  'hdmi_upm_binding': self.hdmi_binding, 'hdmi_upm_cleanup': self.hdmi_cleanup,
                  'error': self.error, 'broker_started': self.broker is not None,
                  'capture_verified': False,
                  'physical_ASIC_compatibility_verified': False, 'original_CP_RAM_verified': False,
                  'standalone_host_media_write': False, **self.socket_options,
                  'acceptance_requires': 'original AP -> actual CMOS -> encoder -> original MPR/Fsys -> directory SD -> independent decode'}
        if self.final_receipts is not None:
            result['broker_event_counts'] = {}
            for event in self.final_receipts:
                kind = event['kind']
                result['broker_event_counts'][kind] = result['broker_event_counts'].get(kind, 0) + 1
            responses = [event for event in self.final_receipts if event['kind'] == 'response']
            result['model_response_counts_by_opcode'] = {str(op): sum(event['opcode'] == op for event in responses)
                                                        for op in sorted({event['opcode'] for event in responses})}
            console = (self.run / 'console.log').read_bytes()
            result['console_sha256_at_close'] = digest(console)
            if phase == 'closed':
                result['initialization'] = initialization_receipt(self.run, self.final_receipts,
                    self.binding['mailbox'] if self.binding else None, console)
            result['broker_receipts'] = str(self.run / (transport.PREFIX + '-receipts.jsonl'))
        return result

    def _publish(self, phase):
        value = self.receipt(phase)
        _publish(self.run, RECEIPT, value)
        manifest_path = self.run / 'runtime-manifest.json'
        if manifest_path.exists():
            manifest = object_json(checked_read(manifest_path))
            manifest['functional_camera_runtime'] = value
            _publish(self.run, manifest_path.name, manifest)
        return value

    def before_close(self, reason):
        self._check_owner()
        if self.closed:
            return self.receipt('closed')
        try:
            require_capture_closed(self.run)
        except (OSError, ValueError) as error:
            self.cleanup = {**dict.fromkeys(CLOSE_FIELDS, False), 'errors': [str(error)]}
            self._publish('blocked-' + reason)
            raise UnsafeCameraClose(str(error)) from error
        self.done.set()
        if self.thread is not None:
            self.thread.join(timeout=15)
        if self.thread is not None and self.thread.is_alive():
            self.cleanup = {key: False for key in CLOSE_FIELDS}
            self.cleanup['errors'] = ['Broker startup/runner worker still active; owner/resources retained']
        elif self.broker is not None:
            self._stop_broker()
        else:
            self.cleanup = {'safe_to_close': True, 'broker_never_attached': True,
                            'worker_stopped': True, 'errors': []}
        safe = type(self.cleanup) is dict and self.cleanup.get('safe_to_close') is True and self.cleanup.get('errors') == []
        if self.broker is not None:
            safe = safe and all(self.cleanup.get(key) is True for key in CLOSE_FIELDS)
        if safe and self.hdmi_watch is not None:
            try:
                self._close_hdmi()
            except BaseException as error:
                self.cleanup = {**self.cleanup, 'safe_to_close': False,
                                'errors': [*self.cleanup['errors'], str(error)]}
                safe = False
        if not safe:
            self._publish('blocked-' + reason)
            raise UnsafeCameraClose('Functional-camera cleanup unconfirmed; retain VM, disk and owner locks: ' + repr(self.cleanup))
        if self.broker is not None:
            try:
                self.final_receipts = transport.read_receipts(self.run)
                events = self.final_receipts
                require(events and events[-1]['kind'] == 'cleanup' and
                        all(events[-1].get(key) is True for key in CLOSE_FIELDS) and
                        events[-1].get('errors') == [], 'Final broker cleanup receipt differs from stop result')
                binding = events[0]
                require(self.binding is not None and self.handoff is not None and binding.get('kind') == 'binding' and
                        binding.get('mailbox') == self.binding['mailbox'] and
                        binding.get('config', {}).get('owner') == self.owner and
                        binding.get('config', {}).get('qemu') == self.handoff['qemu_identity'] and
                        all(_typed_equal(binding.get('config', {}).get(key), value)
                            for key, value in self.socket_options.items()) and
                        all(type(event.get('model_instance')) is int and event['model_instance'] == self.binding['mailbox']['nonce'] and
                            type(event.get('event')) is int and event['event'] == index for index, event in enumerate(events, 1)),
                        'Broker cleanup binding/sequence differs from current VM')
                lifecycle = [event for event in events if event['kind'] in
                             ('cancel_cleanup', 'detach_commit', 'mailbox_detached', 'debugger_disconnected', 'cleanup')]
                needs_cancel = any(event['kind'] in ('core_result', 'response') and event.get('opcode') == transport.INIT and
                                   event.get('actual_c_result') == 0 for event in events)
                has_cancel = lifecycle and lifecycle[0]['kind'] == 'cancel_cleanup'
                boundary = lifecycle[0]['event'] if lifecycle else 0
                require(not needs_cancel or has_cancel, 'Actual model cancellation receipt missing')
                if has_cancel:
                    cancellation = lifecycle.pop(0)
                    require(type(cancellation.get('actual_c_result')) is int and cancellation['actual_c_result'] == 0 and
                            cancellation.get('returned_bytes') == 128, 'Actual model cancellation failed')
                require([event['kind'] for event in lifecycle] ==
                        ['detach_commit', 'mailbox_detached', 'debugger_disconnected', 'cleanup'] and
                        lifecycle[0].get('model_work_stopped') is True and lifecycle[0].get('no_further_ram_after_ack') is True and
                        lifecycle[1].get('cleanup_detach') is True and lifecycle[1].get('protocol_physmode_restored') is True and
                        lifecycle[2].get('detached') is True and lifecycle[2].get('protocol_physmode_restored') is True and
                        all(event['event'] < boundary for event in events if event['kind'] in ('request', 'response', 'core_result', 'model_frame')),
                        'Broker cleanup lifecycle is incomplete/out of order')
                value = self._publish('closed')
            except (OSError, ValueError, KeyError, TypeError) as error:
                self.cleanup = {**self.cleanup, 'safe_to_close': False,
                                'errors': [*self.cleanup['errors'], str(error)]}
                self._publish('blocked-' + reason)
                raise UnsafeCameraClose(str(error)) from error
        else:
            value = self._publish('closed')
        self.closed = True
        return value

    def guard_shutdown(self, proc, original_error=None):
        """Keep bwrap's die-with-parent owner and inherited disk locks on unsafe stop."""
        handlers = {number: signal.signal(number, signal.SIG_IGN) for number in (signal.SIGTERM, signal.SIGINT)}
        try:
            self._check_owner()
            try:
                self.before_close('vm-shutdown')
                return
            except BaseException as error:
                evidence = {'reason': f'{type(error).__name__}: {error}',
                            'original_error': None if original_error is None else f'{type(original_error).__name__}: {original_error}',
                            'cleanup': self.cleanup, 'retain_parent_until_vm_exit': True,
                            'quit_sent': False, 'terminate_sent': False, 'force_kill_authorized': False,
                            'capture_verified': False}
                try:
                    _publish(self.run, 'functional-camera-retained-owner.json', evidence)
                except BaseException as receipt_error:
                    # A full output filesystem must never release the die-with-parent owner.
                    self.error = evidence['reason'] + '; retention receipt failed: ' + repr(receipt_error)
                if proc.poll() is None:
                    proc.wait()
                if proc.poll() is None or original_error is None:
                    raise
        finally:
            for number, previous in handlers.items():
                signal.signal(number, previous)


def prepare(profile, base, run, qemu_binary, *, scope_build_receipt=None,
            socket_root=None, socket_profile=None, socket_binding=None):
    require(profile in ('', FUNCTIONAL_CAMERA_PROFILE), 'Unknown functional-camera runner profile')
    selected = any(value is not None for value in (socket_root, socket_profile, socket_binding))
    if not profile:
        require(not selected, 'F/S functional camera requires explicit functional profile')
        return None
    roots = transport.endpoint_roots(run, socket_root=socket_root,
        socket_profile=socket_profile, socket_binding=socket_binding)
    return FunctionalCameraRunner(run, validate_artifact(base, qemu_binary,
        scope_build_receipt=scope_build_receipt), **transport.endpoint_options(roots))


def read_receipts(run):
    """Expose committed transport facts only after the runner's safe close."""
    root, _ = transport.validate_run(run)
    final = object_json(checked_read(root / RECEIPT))
    require(final.get('phase') == 'closed' and final.get('cleanup', {}).get('safe_to_close') is True,
            'Functional-camera receipts require orderly close first')
    if final['cleanup'].get('broker_never_attached'):
        return []
    require(all(final['cleanup'].get(key) is True for key in CLOSE_FIELDS), 'Incomplete debugger/model shutdown')
    return transport.read_receipts(root)
