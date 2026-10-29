"""Opt-in owner/lifecycle integration for the functional camera broker.

Only the broker accesses the dedicated guest mailbox. This module validates build
and console evidence, hands off the existing Unix debugger, and gates teardown.
"""
from contextlib import contextmanager
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
import tarfile
import threading
import time

from backup_profile import FUNCTIONAL_CAMERA_PROFILE
import functional_camera_broker as transport
from menu_live import FirmwareFault, FirmwareMonitor

QEMU_SHA256 = 'a0d1bdd8a9aad822efe47f740a104972cac6ec1875265e8174b25349f54fee02'
RECEIPT = 'functional-camera-runner.json'
GDB = 'hdmi-upm-gdb.sock'
QMP = 'hdmi-upm-control.sock'
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


def validate_artifact(base, qemu_binary):
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
    require(digest(checked_read(qemu_binary, 256 * 1024 * 1024)) == QEMU_SHA256,
            'Functional camera requires the accepted unchanged QEMU executable')
    return {'library': str(base / 'functional-camera-model.so'), 'library_sha256': digest(raw),
            'build_receipt': str(metadata_path), 'build_receipt_sha256': digest(metadata_raw),
            'source_archive': str(work / 'functional-model-sources.tar.gz'),
            'source_archive_sha256': digest(archive_raw), 'compile_receipt_sha256': digest(compile_raw),
            'abi_header_sha256': sources['runtime/analysis/functional-camera-abi.h'],
            'abi': check_library_abi(raw), 'qemu_sha256': QEMU_SHA256}


def parse_mailbox(console):
    """Return only a complete actual bridge record; repeated mirrors must agree."""
    # Keep the final newline available as the next adjacent record's boundary.
    records = re.findall(rb'(?:^|\n)(?:OBS )?FUNCTIONAL_CAMERA_MAILBOX ([^\r\n]+)(?=\r?\n)', console)
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


def require_capture_closed(run):
    """A prior clip's Close cannot authorize tearing down the current native clip."""
    console = (Path(run) / 'console.log').read_bytes()
    binding = parse_mailbox(console)
    requests, completed, received, freed = {}, set(), set(), set()
    current = None
    epochs, closed_epochs = set(), set()
    jpeg, jpeg_history = {}, {}
    jpeg_received, jpeg_freed, jpeg_callbacks = {}, set(), set()
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
        'original-maincomp-exec': ('comp_caller comp_exec_entry previous_ack_hex previous_ack_address original_result '
                                   'native_config config_length_offset'),
        'original-maincomp-config': 'native_config config_length_offset actual_length expected_length original_result',
        **{f'original-received-{stage}': reply_fields for stage in ('ack', 'done')},
        **{f'original-freed-{stage}': reply_fields + ' free_rc' for stage in ('ack', 'done')},
        **{f'original-rescmd-{stage}': callback_fields for stage in ('ack', 'done')},
    }
    for match in re.finditer(rb'(?:^|\n)(?:OBS )?FUNCTIONAL_(MPR_(?:REQUEST|OPERATION|EVENT_RECEIVED|EVENT_FREE)|JPEG_CODEC)([^\n]*?)\r?(?=\n|$)', console):
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
        require(all(re.fullmatch(r'[a-z_]+=[^\s=]+', token) for token in tokens), 'Malformed native capture shutdown field')
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


def debugger_handoff(run, owner_pid):
    """Observe closed clients/processes; never stop an observer to steal its lease."""
    root, _ = transport.validate_run(run)
    for entry in Path('/proc').iterdir():
        if not entry.name.isdecimal():
            continue
        try:
            identity = transport.process_identity(int(entry.name))
            if Path(identity['exe']).name not in ('gdb', 'gdb-multiarch'):
                continue
            command = (entry / 'cmdline').read_bytes().split(b'\0')
            if any(os.fsencode(root) in arg for arg in command) or (entry / 'cwd').resolve() == root:
                return None
        except (OSError, ValueError):
            continue
    observer_result = None
    if (root / 'hdmi-upm-watch-config.json').exists():
        result = root / 'hdmi-upm-watch-result.json'
        if not result.exists():
            return None
        observer_result = object_json(checked_read(result))
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
        path = root / name
        info = path.lstat()
        require(stat.S_ISSOCK(info.st_mode) and info.st_uid == os.getuid(), 'Untrusted functional-camera Unix endpoint')
        os.chmod(path, 0o600, follow_symlinks=False)
        try:
            sockets[name] = transport.checked_socket(root, path, qemu['pid'])
        except ValueError as error:
            if str(error) == 'Unix endpoint already has a connected client':
                return None
            raise
    return {'qemu_pid': qemu['pid'], 'qemu_identity': qemu, 'debugger_quiesced': True,
            'sockets': sockets, 'previous_hdmi_observer': observer_result}


def _publish(root, filename, value):
    root, _ = transport.validate_run(root)
    path = root / filename
    require(not path.is_symlink(), 'Runner receipt may not be a symlink')
    pending = root / ('.' + filename + '.tmp')
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


class FunctionalCameraRunner:
    def __init__(self, run, artifact):
        self.run, _ = transport.validate_run(run)
        self.artifact = artifact
        self.owner = transport.process_identity(os.getpid())
        self.coordination_lock = threading.RLock()
        self.done = threading.Event()
        self.thread = self.broker = self.proc = None
        self.binding = self.handoff = self.cleanup = self.error = self.startup_cleanup = None
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

    def _watch(self):
        try:
            monitor = FirmwareMonitor(self.run / 'console.log')
            deadline = None
            while not self.done.is_set():
                self._check_owner()
                monitor.check()
                observed = parse_mailbox((self.run / 'console.log').read_bytes())
                if observed:
                    require(self.binding is None or self.binding['mailbox'] == observed['mailbox'], 'Functional mailbox owner changed')
                    self.binding = observed
                    if deadline is None:
                        deadline = time.monotonic() + 20  # Guest exchange has an actual 30-second deadline.
                        self._publish('waiting-for-debugger-handoff')
                    if self.broker is None:
                        handoff = debugger_handoff(self.run, self.owner['pid'])
                        if handoff is not None:
                            monitor.check()
                            if self.done.is_set():
                                break
                            self.handoff = handoff
                            self.broker = transport.start(self.run, self.owner['pid'], self.binding['mailbox'],
                                self.artifact['library'], qemu_pid=handoff['qemu_pid'],
                                qemu_sha256=self.artifact['qemu_sha256'], library_sha256=self.artifact['library_sha256'],
                                gdb_socket=self.run / GDB, qmp_socket=self.run / QMP,
                                coordination_lock=self.coordination_lock, debugger_quiesced=True,
                                resume_allowed=lambda: self.run_allowed and self.proc.poll() is None,
                                seconds=3600.0, io_timeout=1.0)
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
                  'error': self.error, 'broker_started': self.broker is not None,
                  'capture_verified': False,
                  'physical_ASIC_compatibility_verified': False, 'original_CP_RAM_verified': False,
                  'standalone_host_media_write': False,
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


def prepare(profile, base, run, qemu_binary):
    require(profile in ('', FUNCTIONAL_CAMERA_PROFILE), 'Unknown functional-camera runner profile')
    if not profile:
        return None
    return FunctionalCameraRunner(run, validate_artifact(base, qemu_binary))


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
