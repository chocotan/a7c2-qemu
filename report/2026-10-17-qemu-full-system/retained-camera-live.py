#!/usr/bin/env python3
"""One persistent original owner, one typed hot request, then typed normal close.

serve(context_path, new_output) starts the explicitly bound sequence source ONCE.
request(owner_binding, instance_identity, 'hot'|'close') never starts a source.
The descriptor is NOT a UI capability. Optional frontend transport shares this
owner's QMP/stdin; active and closed receipts have separate strict lifecycle
checks. GUI window consumption and hot capability still require actual review.
"""
import argparse
import base64
from contextlib import contextmanager, nullcontext
import hashlib
import json
import os
from pathlib import Path
import re
import runpy
import secrets
import socket
import stat
import struct
import subprocess
import time

HERE = Path(__file__).resolve().parent
R = runpy.run_path(str(HERE / 'retained-camera-test.py'))
DEV = runpy.run_path(str(HERE / 'firmware-development.py'))
C, L, DS, P, E, COLD = (R[k] for k in ('C', 'L', 'DS', 'P', 'E', 'COLD'))
SCHEMA = 'a7c2-retained-camera-live-v1'
WIRE_LIMIT = 65536
SOURCE_BINDINGS = R['SOURCE_BINDINGS'] + [COLD['binding'](HERE / name, 'live-owner-source')
    for name in ('retained-camera-live.py', 'firmware-development.py', 'firmware-boot-request.py',
                 'retained-camera-frontend.py', 'low-latency-input.py', 'run-retained-camera.py')]
LIMITS = dict(full_boot_verified=False, full_device_audit_complete=False, sony_wbi_verified=False,
              hardware_hotboot_verified=False, hardware_ram_hotboot_verified=False,
              capture_verified=False, ui_hot_enabled=False, gui_owner_switch_verified=False,
              state_and_qmp_images_zero_race_coherent=False, display_under_one_second_verified=False,
              free_return_code_verified=False, vm_signals_sent=[])


def check(condition, message):
    if not condition:
        raise ValueError(message)


class LiveRequestRefused(ValueError):
    def __init__(self, message, state=None):
        super().__init__('Live owner refused: ' + message)
        self.state = state


def process(pid):
    check(type(pid) is int and pid > 0, 'Invalid process PID')
    return C['_proc_identity'](pid)


def identity(info):
    return dict(dev=info.st_dev, ino=info.st_ino)


def socket_identity(path):
    info = path.lstat()
    check(stat.S_ISSOCK(info.st_mode) and info.st_uid == os.getuid() and
          stat.S_IMODE(info.st_mode) == 0o600 and info.st_nlink == 1,
          'Expected an owned mode 0600 single-link Unix socket')
    return identity(info)


def peer(connection):
    pid, uid, _ = struct.unpack('3i', connection.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12))
    result = process(pid)
    check(uid == os.getuid() == result['uid'], 'Unix peer UID differs')
    return result


def receive(connection):
    raw = bytearray()
    while len(raw) <= WIRE_LIMIT:
        part = connection.recv(min(4096, WIRE_LIMIT + 1 - len(raw)))
        check(bool(part), 'Incomplete live request/response')
        raw.extend(part)
        check(len(raw) <= WIRE_LIMIT, 'Live request/response exceeds budget')
        if b'\n' in raw:
            check(raw.endswith(b'\n') and raw.count(b'\n') == 1, 'One bounded JSON record required')
            value = json.loads(raw, object_pairs_hook=DEV['_pairs'],
                               parse_constant=lambda _: check(False, 'Nonfinite wire number'))
            check(type(value) is dict, 'Wire object required')
            return value
    raise ValueError('Live request/response exceeds budget')


def send(connection, value):
    raw = json.dumps(value, allow_nan=False, separators=(',', ':')).encode() + b'\n'
    check(len(raw) <= WIRE_LIMIT, 'Live response exceeds budget')
    connection.sendall(raw)


def binding(path):
    row = COLD['binding'](path, 'live-private-artifact')
    return dict(path=row['path'], sha256=row['sha256'])


# Embedded into L; no new runtime source binding.
STATE_DOMAIN = 'a7c2-retained-live-state-proof-v1'
STATE_LIMIT = 65536


class StateTransportSyntax(ValueError):
    """Only intact META/END/DONE with missing/interrupted chunk syntax is retryable."""
    def __init__(self, anchor):
        super().__init__('State transport chunk syntax incomplete; original file retained')
        self.anchor = anchor


def state_spec(phase, token, nonce, create=False):
    check(phase in ('ready', 'source', 'restored', 'menu', 'shooting') and
          type(create) is bool and create is (phase == 'ready'), 'Invalid live sampling phase/create')
    check(all(type(v) is str and re.fullmatch('[0-9a-f]{32}', v) for v in (token, nonce)) and
          nonce != token, 'Independent state transport nonce required')
    code = R['state_script'](phase, token, create)
    return dict(domain=STATE_DOMAIN, phase=phase, token=token, nonce=nonce, create=create,
        guest_file='/dev/qemu-simulation/retained-live-state-' + nonce + '-' + phase + '.proof',
        code_sha256=hashlib.sha256(code.encode('ascii')).hexdigest(), sourceap_sha256=E['APPFW_SHA256'])


def state_identity(spec):
    return 'nonce=' + spec['nonce'] + ' phase=' + spec['phase'] + ' file=' + spec['guest_file']


def state_file_markers(spec):
    identity = state_identity(spec)
    begin = ('RETAINED_LIVE_STATE_FILE domain=' + STATE_DOMAIN + ' ' + identity +
        ' code_sha256=' + spec['code_sha256'] + ' sourceap_sha256=' + spec['sourceap_sha256'])
    return begin, 'RETAINED_LIVE_STATE_FILE_END ' + identity


def state_done(spec, attempt):
    return 'RETAINED_LIVE_DONE nonce=' + spec['nonce'] + ' phase=' + spec['phase'] + ' attempt=' + str(attempt) + ' rc=0'


def state_transfer_script(spec, attempt):
    """Read ONLY an already generated file. Same 192-byte canonical codec as coldproof."""
    identity = state_identity(spec)
    body = f'''set -e
proof={spec['guest_file']}
test -f "$proof"
test ! -L "$proof"
set -- $(busybox ls -l "$proof")
bytes=$5
bytes=$((bytes+0))
test "$bytes" -gt 0
test "$bytes" -le {STATE_LIMIT}
before=$(/usr/bin/openssl dgst -sha256 "$proof")
before=${{before##* }}
echo RETAINED_LIVE_META {identity} bytes=$bytes sha256=$before
/usr/bin/openssl enc -base64 -in "$proof" | {{
 offset=0
 chunk=
 while IFS= read -r line; do
  chunk=$chunk$line
  if test "${{#chunk}}" -eq 256; then
   echo RETAINED_LIVE_CHUNK nonce={spec['nonce']} offset=$offset data=$chunk
   offset=$((offset+192))
   chunk=
  fi
 done
 if test -n "$chunk"; then
  echo RETAINED_LIVE_CHUNK nonce={spec['nonce']} offset=$offset data=$chunk
 fi
}}
after=$(/usr/bin/openssl dgst -sha256 "$proof")
after=${{after##* }}
test "$before" = "$after"
echo RETAINED_LIVE_END {identity} bytes=$bytes sha256=$after
'''
    return body


def state_sample_script(spec):
    begin, end = state_file_markers(spec)
    phase = spec['phase']
    prefix = R['MENU'] if phase in ('menu', 'shooting') else 'busybox sleep 1\n' if phase in ('source', 'restored') else ''
    return f'''set -e
umask 077
set -C
proof={spec['guest_file']}
exec 3>"$proof"
{prefix}(
echo '{begin}'
/usr/bin/openssl dgst -sha256 /usr/lib/appFw.so
{R['state_script'](phase, spec['token'], spec['create'])}echo '{end}'
) >&3 2>&3
exec 3>&-
busybox chmod 400 "$proof"
''' + state_transfer_script(spec, 0)


def state_cleanup_script(spec, digest):
    check(type(digest) is str and re.fullmatch('[0-9a-f]{64}', digest), 'Invalid cleanup digest')
    marker = 'RETAINED_LIVE_CLEAN ' + state_identity(spec) + ' sha256=' + digest
    return (f'set -e\nproof={spec["guest_file"]}\n'
        'actual=$(/usr/bin/openssl dgst -sha256 "$proof")\nactual=${actual##* }\n'
        f'test "$actual" = {digest}\nbusybox rm -f "$proof"\ntest ! -e "$proof"\necho \'{marker}\'\n'), marker


def protocol_lines(raw):
    # CRLF terminates a record; an embedded CR is never removed or repaired.
    return [line[:-1] if line.endswith(b'\r') else line for line in raw.split(b'\n')]


def decode_state_transfer(raw, spec, attempt):
    check(type(raw) is bytes and 0 < len(raw) <= R['COLD_TRACE_LIMIT'], 'State trace budget differs')
    records = [line for line in protocol_lines(raw) if line.startswith(b'RETAINED_LIVE_')]
    identity = state_identity(spec).encode('ascii')
    meta_re = rb'RETAINED_LIVE_META ' + re.escape(identity) + rb' bytes=([1-9][0-9]{0,4}) sha256=([0-9a-f]{64})'
    meta = re.fullmatch(meta_re, records[0] if records else b'')
    check(meta is not None, 'State metadata/nonce/phase/file identity differs')
    size, digest = int(meta[1]), meta[2].decode('ascii')
    check(size <= STATE_LIMIT, 'State sample size exceeds budget')
    anchor = (size, digest)
    end = b'RETAINED_LIVE_END ' + identity + b' bytes=' + meta[1] + b' sha256=' + meta[2]
    done = state_done(spec, attempt).encode('ascii')
    check(len(records) >= 3 and records[-2:] == [end, done], 'State END/hash/completion identity differs')
    check(sum(line.startswith(b'RETAINED_LIVE_META ') for line in records) == 1 and
          sum(line.startswith(b'RETAINED_LIVE_END ') for line in records) == 1 and
          sum(line.startswith(b'RETAINED_LIVE_DONE ') for line in records) == 1,
          'Repeated state envelope/completion rejected')
    chunks, syntax = [], False
    for line in records[1:-2]:
        check(line.startswith(b'RETAINED_LIVE_CHUNK '), 'Unknown state protocol record')
        nonce = re.match(rb'RETAINED_LIVE_CHUNK nonce=([^ ]+) ', line)
        check(nonce is not None and nonce[1] == spec['nonce'].encode('ascii'), 'State chunk nonce differs')
        match = re.fullmatch(rb'RETAINED_LIVE_CHUNK nonce=[0-9a-f]{32} offset=(0|[1-9][0-9]{0,4}) data=([A-Za-z0-9+/=]{1,256})', line)
        if match is None:
            syntax = True
            continue
        offset = int(match[1])
        try:
            payload = base64.b64decode(match[2], validate=True)
        except ValueError as error:
            raise ValueError('State base64 differs') from error
        check(base64.b64encode(payload) == match[2] and 0 <= offset < size and offset % 192 == 0 and
              len(payload) == min(192, size-offset), 'State chunk offset/length/canonical code differs')
        chunks.append((offset, payload))
    offsets = [row[0] for row in chunks]
    check(offsets == sorted(set(offsets)), 'Repeated/reordered state chunk offset')
    count = (size+191)//192
    check(len(records[1:-2]) <= count, 'Repeated state chunk record')
    if syntax or len(chunks) < count:
        raise StateTransportSyntax(anchor)
    check(offsets == list(range(0, size, 192)), 'State continuous offsets differ')
    proof = b''.join(payload for _, payload in chunks)
    check(len(proof) == size and hashlib.sha256(proof).hexdigest() == digest, 'State complete SHA256 differs')
    return proof


def review_state_file(proof, spec):
    begin, end = (line.encode('ascii') for line in state_file_markers(spec))
    lines = proof.splitlines()
    check(proof.startswith(begin+b'\n') and proof.endswith(end+b'\n') and
          lines.count(begin) == lines.count(end) == 1, 'State code/sourceapsha/domain/file identity differs')
    text = proof.decode('ascii')
    expected = r'^(?:SHA256|SHA2-256)\(/usr/lib/appFw\.so\)= ' + spec['sourceap_sha256'] + r'$'
    check(len(re.findall(expected, text, re.M)) == 1 and
          len(re.findall(r'^(?:SHA256|SHA2-256)\(/usr/lib/appFw\.so\)= .*$', text, re.M)) == 1,
          'Actual source AP SHA differs')
    check(text.splitlines().count('RETAINED_DONE_' + spec['phase'] + '=' + spec['token']) == 1,
          'State receipt must contain one original completion')
    value = R['parse_state'](text, spec['phase'])
    R['frame_review'](value)
    check(value['canary'] == spec['token'], 'State RAM canary differs')
    return value


def state_command(script, spec, attempt):
    done = state_done(spec, attempt).removesuffix('0')
    # Keep recovery outside the original subshell's errexit context and preserve its status.
    definition, recovery = '', ''
    if attempt == 0:
        transfer = state_transfer_script(spec, 0)
        check(script.endswith(transfer) and script.count(transfer) == 1, 'State sample transfer suffix differs')
        script = script[:-len(transfer)] + 'a7c2_state_transfer\n'
        definition = 'a7c2_state_transfer() (\n' + transfer + '\n)\n'
        recovery = 'if test "$a7c2_state_rc" -ne 0; then\na7c2_state_transfer\nfi\n'
    # Keep literal protocol prefixes out of TTY input echo; shell concatenation preserves stdout.
    return (definition + '(\n' + script + '\n)\na7c2_state_rc=$?\n' + recovery +
            'echo \'' + done + '\'"$a7c2_state_rc"\n').replace('RETAINED_LIVE_', "RETAINED_''LIVE_")


def sample_live_state(session, owner, qmp, log, phase, create=False):
    """Never resample/replay input. Only chunk syntax may retry the immutable file once."""
    spec = state_spec(phase, session.token, secrets.token_hex(16), create)
    start = log.stat().st_size
    state_cursor = start
    attempts, anchor, proof = [], None, None
    deadline = getattr(session, 'state_deadline', time.monotonic()+60)

    def exchange(script, number, marker):
        nonlocal state_cursor
        check(time.monotonic() < deadline, 'Live state transaction deadline expired')
        session.unchanged()
        R['authenticate_owner'](session.tx, owner, qmp)
        check(owner.poll() is None, 'State transport owner exited')
        before = log.read_bytes()
        begin = state_cursor
        command = state_command(script, spec, number)
        E['write_console'](owner.stdin, E['diagnostic_envelope'](command,
            'A7C2_STATE_SCRIPT_' + spec['nonce'] + '_' + str(number)).encode('ascii'))
        R['wait_for'](owner, log, lambda text: any(line.startswith(marker) for line in text[len(before.decode('utf-8', errors='replace').replace('\r', '')):].split('\n')[:-1]),
                      max(.001, deadline-time.monotonic()))
        after = log.read_bytes()
        check(after.startswith(before), 'State transport console is not append-only')
        segment = after[begin:]
        # Nonzero or repeated completion never falls into the syntax retry path.
        expected = state_done(spec, number).encode('ascii')
        completions = [line for line in protocol_lines(segment) if line.startswith(marker.encode('ascii'))]
        failed = re.fullmatch(re.escape(marker.encode('ascii')) + rb'([1-9][0-9]*)',
                              completions[0]) if len(completions) == 1 else None
        if number == 0 and failed is not None:
            error = ValueError('State command completion/code differs')
            try:
                stem = phase + '-state-failed-diagnostic'
                R['save_bytes'](session.output / (stem + '.raw'), segment)
                R['save'](session.output / (stem + '.json'), dict(schema=STATE_DOMAIN,
                    spec=spec, owner_pid=owner.pid, begin=begin, end=len(after), original_rc=int(failed[1]),
                    valid_for_state=False, actual_content_verified=False,
                    trace=binding(session.output / (stem + '.raw'))))
            except (OSError, ValueError) as diagnostic_error:
                error.add_note('Failed state diagnostic save: ' + str(diagnostic_error))
            raise error
        check(completions == [expected], 'State command completion/code differs')
        state_cursor = len(after)
        return begin, state_cursor, segment

    for number in range(2):
        script = state_sample_script(spec) if number == 0 else state_transfer_script(spec, number)
        marker = state_done(spec, number).rsplit('=', 1)[0] + '='
        begin, end, segment = exchange(script, number, marker)
        attempts.append(dict(begin=begin, end=end, command_sha256=hashlib.sha256(state_command(script, spec, number).encode('ascii')).hexdigest()))
        try:
            proof = decode_state_transfer(segment, spec, number)
        except StateTransportSyntax as error:
            if number or time.monotonic() >= deadline:
                raise
            anchor = error.anchor
            continue
        if anchor is not None:
            check((len(proof), hashlib.sha256(proof).hexdigest()) == anchor, 'Retry file Content differs')
        break
    value = review_state_file(proof, spec)
    observed = log.read_bytes()[start:attempts[-1]['end']].decode('utf-8', errors='replace').replace('\r', '')
    if phase in ('menu', 'shooting'):
        R['review_input'](observed, phase)
    cleanup, clean_marker = state_cleanup_script(spec, hashlib.sha256(proof).hexdigest())
    begin, end, segment = exchange(cleanup, 2, state_done(spec, 2).rsplit('=', 1)[0] + '=')
    check(protocol_lines(segment).count(clean_marker.encode('ascii')) == 1, 'State cleanup receipt differs')
    trace = log.read_bytes()[start:end]
    stem = phase + '-state-transport'
    R['save_bytes'](session.output / (stem + '.raw'), trace)
    R['save_bytes'](session.output / (stem + '.proof'), proof)
    receipt = dict(schema=STATE_DOMAIN, spec=spec, owner_pid=owner.pid,
        log='transaction/source-console.log' if phase in ('ready', 'source') else 'transaction/target/console.log',
        begin=start, end=end, attempts=attempts, cleanup_begin=begin,
        trace=binding(session.output / (stem + '.raw')), sample=binding(session.output / (stem + '.proof')))
    R['save'](session.output / (stem + '.json'), receipt)
    session.state_transports[phase] = binding(session.output / (stem + '.json'))
    return value, observed


def replay_live_state(output, phase, token, full, owner_pid, bound, raw):
    """The same exact decoder and semantic gates are mandatory for CLOSED and active."""
    stem = phase + '-state-transport'
    receipt_raw = raw(stem + '.json')
    check(bound == dict(path=str(output / (stem + '.json')), sha256=hashlib.sha256(receipt_raw).hexdigest()), 'State receipt binding differs')
    receipt = json.loads(receipt_raw, object_pairs_hook=DEV['_pairs'])
    check(set(receipt) == {'schema', 'spec', 'owner_pid', 'log', 'begin', 'end', 'attempts', 'cleanup_begin', 'trace', 'sample'} and
          receipt['schema'] == STATE_DOMAIN and type(receipt['owner_pid']) is int and receipt['owner_pid'] == owner_pid,
          'State receipt owner/schema differs')
    spec = receipt['spec']
    check(spec == state_spec(phase, token, spec['nonce'], phase == 'ready'), 'State receipt code/domain/sourceapsha differs')
    check(receipt['log'] == ('transaction/source-console.log' if phase in ('ready', 'source') else 'transaction/target/console.log'), 'State receipt source log differs')
    begin, end = receipt['begin'], receipt['end']
    check(type(begin) is type(end) is int and 0 <= begin < end <= len(full), 'State raw offsets differ')
    trace, sample = raw(stem + '.raw'), raw(stem + '.proof')
    for suffix, value, key in (('.raw', trace, 'trace'), ('.proof', sample, 'sample')):
        check(receipt[key] == dict(path=str(output / (stem + suffix)), sha256=hashlib.sha256(value).hexdigest()), 'State artifact binding differs')
    check(trace == full[begin:end], 'State raw console slice differs')
    # A second DONE outside the bound interval is still a repeated completion.
    def scoped(data):
        return [line for line in protocol_lines(data) if line.startswith(b'RETAINED_LIVE_') and
                b'nonce=' + spec['nonce'].encode('ascii') in line]
    check(scoped(full) == scoped(trace), 'State receipt repeated/foreign transport completion')
    check(not any(line == ('RETAINED_DONE_' + phase + '=' + token).encode('ascii') for line in protocol_lines(full)),
          'State receipt has legacy/unbound completion')
    attempts = receipt['attempts']
    check(type(attempts) is list and len(attempts) in (1, 2), 'State transport attempt count differs')
    cursor, anchor, decoded = begin, None, None
    for number, row in enumerate(attempts):
        check(set(row) == {'begin', 'end', 'command_sha256'} and type(row['begin']) is type(row['end']) is int and
              row['begin'] == cursor < row['end'] <= end, 'State attempt offsets differ')
        script = state_sample_script(spec) if number == 0 else state_transfer_script(spec, number)
        check(row['command_sha256'] == hashlib.sha256(state_command(script, spec, number).encode('ascii')).hexdigest(), 'State command code differs')
        try:
            decoded = decode_state_transfer(full[row['begin']:row['end']], spec, number)
        except StateTransportSyntax as error:
            check(number == 0 and len(attempts) == 2, 'State syntax failure has no bounded file retry')
            anchor = error.anchor
        else:
            check(number == len(attempts)-1, 'Successful state transport must not be retried')
        cursor = row['end']
    check(decoded == sample and (anchor is None or anchor == (len(sample), hashlib.sha256(sample).hexdigest())), 'Retry file Content differs')
    check(receipt['cleanup_begin'] == cursor, 'State cleanup offsets differ')
    cleanup = full[cursor:end]
    _, clean_marker = state_cleanup_script(spec, hashlib.sha256(sample).hexdigest())
    check([line for line in protocol_lines(cleanup) if line.startswith(b'RETAINED_LIVE_')] ==
          [clean_marker.encode('ascii'), state_done(spec, 2).encode('ascii')], 'State cleanup/completion differs')
    value = review_state_file(sample, spec)
    observed = full[begin:cursor].decode('utf-8', errors='replace').replace('\r', '')
    if phase in ('menu', 'shooting'):
        R['review_input'](observed, phase)
    return value, observed


@contextmanager
def endpoint(owner_binding, instance, *, require_alive=True):
    """Pin the private directory and socket inode, not just their path names."""
    path = DEV['checked_binding'](owner_binding, private=True)
    directory = DEV['path_checked'](path.parent, directory=True, private=True)
    descriptor = DEV['read_json'](path)
    fields = {'schema', 'nonce', 'instance_identity', 'controller_identity', 'directory_identity',
              'socket_identity', 'source_bindings', 'profile', 'qemu_sha256', 'gui_owner_switch_verified',
              'frontend_enabled'}
    check(path.name == 'live-owner.json' and set(descriptor) == fields and descriptor['schema'] == SCHEMA,
          'Unknown live owner descriptor')
    check(descriptor['instance_identity'] == instance and descriptor['profile'] == L['UPSTREAM_PROFILE'] and
          descriptor['qemu_sha256'] == L['UPSTREAM_BINARY_SHA'] and descriptor['gui_owner_switch_verified'] is False and
          type(descriptor['frontend_enabled']) is bool,
          'Live owner instance/profile differs')
    check(type(descriptor['nonce']) is str and re.fullmatch('[0-9a-f]{64}', descriptor['nonce']), 'Invalid live nonce')
    check(descriptor['source_bindings'] == SOURCE_BINDINGS, 'Loaded live backend source differs')
    COLD['recheck'](SOURCE_BINDINGS)
    fd = DS['DISK']['SECURE_OPEN'](directory, directory=True)
    try:
        check(identity(os.fstat(fd)) == descriptor['directory_identity'] == identity(directory.stat()),
              'Live owner directory inode changed')
        sockpath = Path('/proc/self/fd') / str(fd) / 'control.sock'
        check(socket_identity(sockpath) == descriptor['socket_identity'], 'Live socket inode changed')
        if require_alive:
            check(process(descriptor['controller_identity']['pid']) == descriptor['controller_identity'],
                  'Controller PID/start ticks/UID changed')
        yield descriptor, sockpath
        check(identity(directory.stat()) == descriptor['directory_identity'] and
              socket_identity(sockpath) == descriptor['socket_identity'], 'Live endpoint changed during request')
        DEV['checked_binding'](owner_binding, private=True)
    finally:
        os.close(fd)


def inspect_owner(owner_binding, instance):
    with endpoint(owner_binding, instance) as (descriptor, _):
        return descriptor


def request(owner_binding, instance, action):
    """No command, output path, timeout, signals, reconnect or cold fallback."""
    check(action in ('hot', 'close'), 'Only typed hot/close are supported')
    refusal = None
    with endpoint(owner_binding, instance) as (descriptor, path), socket.socket(socket.AF_UNIX) as connection:
        connection.connect(str(path))
        controller = peer(connection)
        check(controller == descriptor['controller_identity'], 'Socket peer is not the declared live controller')
        message = dict(schema=SCHEMA, action=action, nonce=descriptor['nonce'], instance_identity=instance,
                       socket_identity=descriptor['socket_identity'], client_identity=process(os.getpid()),
                       frontend_enabled=descriptor['frontend_enabled'])
        send(connection, message)
        response = receive(connection)
        check(set(response) == {'schema', 'request', 'controller_identity', 'status', 'result'} and
              response['schema'] == SCHEMA and response['request'] == message and
              response['controller_identity'] == controller == peer(connection),
              'Response/controller identity changed')
        if action == 'hot':
            check(process(controller['pid']) == controller, 'Live controller exited or PID was reused')
        if response['status'] == 'refused':
            result = response['result']
            check(type(result) is dict and set(result) in ({'error'}, {'error', 'state'}) and
                  type(result['error']) is str, 'Unknown refusal response')
            state = result.get('state')
            check(state is None or (type(state) is dict and type(state.get('live_owner_pids')) is list and
                  all(type(pid) is int and pid > 0 for pid in state['live_owner_pids']) and
                  len(set(state['live_owner_pids'])) == len(state['live_owner_pids'])), 'Unknown refused owner state')
            refusal = (result['error'], state)
        else:
            check(response['status'] == 'completed', 'Unknown live owner status')
            result = response['result']
            check(type(result) is dict and set(result) == {'artifact', 'state'}, 'Unknown typed response')
            check(Path(result['artifact']['path']) == Path(owner_binding['path']).parent /
                  ('hot-result.json' if action == 'hot' else 'result.json'), 'Foreign live result path')
            DEV['checked_binding'](result['artifact'], private=True)
    # Authenticate the endpoint's exit checks before exposing refusal state.
    if refusal is not None:
        raise LiveRequestRefused(*refusal)
    return response


class OwnerControl:
    """Serialized Unix endpoint, kept in the SAME process as Popen and DiskTransaction."""
    def __init__(self, session, frontend=None):
        self.session, self.frontend = session, frontend
        self.directory = DEV['path_checked'](session.output, directory=True, private=True)
        self.fd = DS['DISK']['SECURE_OPEN'](self.directory, directory=True)
        self.connection = socket.socket(socket.AF_UNIX)
        self.closed = False
        try:
            path = Path('/proc/self/fd') / str(self.fd) / 'control.sock'
            self.connection.bind(str(path))
            path.chmod(0o600)
            self.descriptor = dict(schema=SCHEMA, nonce=secrets.token_hex(32), instance_identity=session.instance,
                controller_identity=process(os.getpid()), directory_identity=identity(os.fstat(self.fd)),
                socket_identity=socket_identity(path), source_bindings=SOURCE_BINDINGS,
                profile=L['UPSTREAM_PROFILE'], qemu_sha256=L['UPSTREAM_BINARY_SHA'], gui_owner_switch_verified=False,
                frontend_enabled=frontend is not None)
            R['save'](self.directory / 'live-owner.json', self.descriptor)
            self.connection.listen(4)
        except BaseException:
            self.close_socket()
            raise

    def close_socket(self):
        self.connection.close()
        os.close(self.fd)

    def handle(self, connection):
        message = None
        authenticated = False
        try:
            client = peer(connection)
            connection.settimeout(3)  # Only the untrusted request read, never an owner/VM lifetime.
            message = receive(connection)
            check(set(message) == {'schema', 'action', 'nonce', 'instance_identity', 'socket_identity', 'client_identity',
                                   'frontend_enabled'},
                  'Only typed hot/close fields are accepted')
            check(message['schema'] == SCHEMA and message['action'] in ('hot', 'close') and
                  message['nonce'] == self.descriptor['nonce'] and
                  message['instance_identity'] == self.descriptor['instance_identity'] and
                  message['socket_identity'] == self.descriptor['socket_identity'] and
                  type(message['frontend_enabled']) is bool and
                  message['frontend_enabled'] == self.descriptor['frontend_enabled'] and
                  message['client_identity'] == client == process(client['pid']), 'Request credentials/nonce/instance differ')
            check(process(os.getpid()) == self.descriptor['controller_identity'] and
                  identity(self.directory.stat()) == self.descriptor['directory_identity'] and
                  socket_identity(self.directory / 'control.sock') == self.descriptor['socket_identity'],
                  'Controller directory/socket/process identity changed')
            connection.settimeout(None)
            authenticated = True
            with self.frontend.transition(message['action']) if self.frontend is not None else nullcontext():
                value = self.session.hot() if message['action'] == 'hot' else self.session.close()
            if message['action'] == 'hot' and self.frontend is not None:
                owner, qmp, directory, log, side = self.frontend.current()
                check(side == 'target' and owner is self.session.execution.target and
                      qmp is self.session.execution.target_qmp, 'Frontend did not select the restored target')
                R['authenticate_owner'](self.session.tx, owner, qmp)
                self.frontend.pump()
                check(not self.frontend.fault, 'Frontend target transport failed: ' + self.frontend.fault)
                R['save'](self.directory / 'frontend-hot.json', dict(owner_pid=owner.pid, input_owner_pid=owner.pid,
                    source_directory=str(directory), source_log=str(log), frame=str(self.frontend.frame),
                    input_dir=str(self.frontend.input_dir),
                    status=DEV['read_json'](self.frontend.output / 'status.json')))
                value['state']['frontend'] = binding(self.directory / 'frontend-hot.json')
            self.closed = message['action'] == 'close'
            response = dict(schema=SCHEMA, request=message, controller_identity=self.descriptor['controller_identity'],
                            status='completed', result=value)
        except Exception as error:
            if authenticated and message['action'] == 'close' and self.session.closed:
                self.closed = True
            result = dict(error=type(error).__name__ + ': ' + str(error))
            if authenticated:
                result['state'] = self.session.state()
            response = dict(schema=SCHEMA, request=message, controller_identity=self.descriptor['controller_identity'],
                            status='refused', result=result)
        connection.settimeout(None)
        send(connection, response)
        if self.closed:
            # Retain this PID through the client's authenticated response read.
            connection.settimeout(3)
            check(connection.recv(1) == b'', 'No additional close payload is accepted')

    def serve(self):
        try:
            if self.frontend is not None:
                self.connection.settimeout(.01)
            while not self.closed:
                try:
                    connection, _ = self.connection.accept()
                except socket.timeout:
                    self.frontend.pump()
                    continue
                with connection:
                    try:
                        self.handle(connection)
                    except (OSError, ValueError):
                        # A disconnected client never authorizes owner close or lease release.
                        pass
                if self.frontend is not None and not self.closed:
                    self.frontend.pump()
        finally:
            self.close_socket()
            if self.frontend is not None:
                self.frontend.dispose()


class LiveSession:
    def __init__(self, context_path, context, cap, output, tx, launch, cold, cold_row, private, originals):
        self.context_path, self.context, self.cap = context_path, context, cap
        self.output, self.tx, self.launch, self.cold = output, tx, launch, cold
        self.instance = context['instance_identity']
        self.cold_row, self.private, self.originals = cold_row, private, originals
        self.owner = self.execution = self.qmp = self.connection = self.stream = None
        self.used = self.closed = self.capture_returned = False
        self.content = None
        self.state_transports = {}
        self.token = secrets.token_hex(16)
        self.source_run, self.target_run = 'retained-source-' + self.token, 'retained-target-' + self.token
        self.log = tx._output / 'source-console.log'

    def unchanged(self):
        current = DEV['load_context'](self.context_path)
        # Main may explicitly publish hot later; startup source bindings stay pinned.
        for key in ('runtime', 'workspace', 'instance_identity', 'routes'):
            check(current.get(key) == self.context.get(key), 'Current source context changed: ' + key)
        check(DEV['sequence_capability'](current, self.instance) == self.cap, 'Source capability changed')
        target = self.execution.target if self.execution is not None else None
        owner, qmp = (target, self.execution.target_qmp) if target is not None else (self.owner, self.qmp)
        quiesce = (R['paused'](qmp, self.output / ('anchor-identity-quiesce-' + secrets.token_hex(8) + '.jsonl'),
                              tx=self.tx, owner=owner, resume=True)
                    if owner is not None and owner.poll() is None and qmp is not None else nullcontext())
        with quiesce:
            DEV['bind_instance'](current)
            self.tx._check_anchor()
            COLD['recheck'](SOURCE_BINDINGS)

    def start(self, timeout):
        self.unchanged()
        P['identical']('metadata before original owner', self.private, R['metadata'](Path(self.launch['instance']), self.tx))
        P['verify_firmware'](self.tx._leased, self.launch)
        COLD['recheck']([self.cold_row] + SOURCE_BINDINGS + self.launch['template_inputs'] + self.launch['launch_inputs'])
        info = os.fstat(self.tx.fd)
        env = dict(self.launch['env'], PERSISTENT_INSTANCE=str(self.tx._leased['path']), PERSISTENT_DISK_FD=str(self.tx.fd),
                   PERSISTENT_DISK_DEV=str(info.st_dev), PERSISTENT_DISK_INO=str(info.st_ino))
        with os.fdopen(os.open(self.log, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600), 'wb', buffering=0) as out:
            self.owner = subprocess.Popen(self.launch['command'], env=env, stdin=subprocess.PIPE,
                stdout=out, stderr=subprocess.STDOUT, pass_fds=self.tx.pass_fds)
            self.tx.children.append(self.owner)
        R['save'](self.output / 'source-owner-start.json', dict(pid=self.owner.pid, command=self.launch['command']))
        R['wait_for'](self.owner, self.log, lambda s: 'OBS OSD_HEADLESS_PERSISTED ' in s and bool(re.search(
            r'^OBS CREATE_SCREEN_ARGS [^\n]* id=0 count=565 ', s, re.M)), timeout)
        self.connection, self.stream, _ = E['qmp_connect'](self.launch['qmp_socket'], timeout=15)
        self.qmp = C['R']['FDQMP'](self.connection, self.stream)
        R['shell'](self.owner, self.log, R['diagnostic_script'](self.token), 'diag', self.token)
        collector = R['retain_cold_proof'](self.output, self.log, self.token)
        receipt = E['new_receipt']('original-init-cold', bindings=dict(run=self.source_run, source_class=self.cold['source']),
                                 kernel_cmdline=self.launch['cmdline'])
        coverage = E['collect'](collector, receipt)
        R['save'](self.output / 'source-cold-evidence.json', coverage)
        check(coverage['ap_verified'] and coverage['cold_guest_chain_verified'], 'Original cold guest chain/AP not verified')
        with R['paused'](self.qmp, self.output / 'source-constructor-quiesce.jsonl', tx=self.tx, owner=self.owner, resume=True):
            self.execution = C['CameraExecution'](self.tx, self.launch, self.owner, self.qmp, source_run=self.source_run, generation=0)
            check(self.execution.identity['owner']['parent_pid'] == os.getpid(), 'Source parent must be this controller')
        state, _ = sample_live_state(self, self.owner, self.qmp, self.log, 'ready', True)
        R['frame_review'](state)
        check(state['canary'] == self.token, 'New original source canary differs')
        self.ready_state = state
        R['save'](self.output / 'ready-state.json', state)
        self.running(self.owner, self.qmp)
        ready, page = self.shooting_source('ready')
        if ready:
            R['save'](self.output / 'source-ready.json', dict(schema=SCHEMA, controller_identity=process(os.getpid()),
                source_identity=self.execution.identity, source_run=self.source_run, instance_identity=self.instance,
                state='source-running', current_page=page, display='QMP original LCD; no GUI transport attached',
                input='owned source stdin; no GUI transport attached', **LIMITS))
        return ready

    def shooting_source(self, phase):
        raw = self.log.read_bytes()
        rows = [line for line in raw.splitlines(keepends=True) if b'OBS CREATE_SCREEN_ARGS' in line]
        latest = rows[-1] if rows else b''
        line = R['native_records'](latest.rstrip(b'\r\n').decode('ascii', errors='replace'))
        match = re.fullmatch(r'OBS CREATE_SCREEN_ARGS call=([1-9][0-9]*) id=(0|0x[0-9a-f]+) '
            r'count=([0-9]+) orientation=([0-9]+)(?: this=0x[0-9a-f]+ kinds=\[[0-9,]*\])?', line)
        ready = bool(latest.endswith(b'\n') and match and match.groups()[1:] == ('0', '565', '0'))
        page = dict(latest_create_screen=line or None, original_shooting_main=ready,
            source_console=dict(path=str(self.log), bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest()))
        if not ready:
            R['save'](self.output / ('source-unready-' + secrets.token_hex(8) + '.json'),
                dict(schema=SCHEMA, status='source-unready', phase=phase, current_page=page, state=self.state(),
                     reason='Latest original CREATE_SCREEN_ARGS must be shooting main id=0 count=565 orientation=0',
                     lease_retained_until_owner_exit=True, actual_content_verified=False, **LIMITS))
        return ready, page

    def running(self, owner, qmp):
        check(owner.poll() is None, 'Existing owned source/target must be alive')
        R['authenticate_owner'](self.tx, owner, qmp)
        status = qmp('query-status')
        check(status.get('running') is True and status.get('status') == 'running', 'Existing owned source/target must be running')
        with R['paused'](qmp, self.output / ('owner-identity-quiesce-' + secrets.token_hex(8) + '.jsonl'),
                         tx=self.tx, owner=owner, resume=True):
            self.unchanged()
            actual = C['_owned_identity'](self.tx, self.launch, owner, qmp)
            if owner is self.owner:
                C['same']('same live source owner', self.execution.identity, actual)
            return actual

    def state(self):
        target = self.execution.target if self.execution is not None else None
        side = 'target' if target is not None else 'source'
        owner = target if target is not None else self.owner
        live = {child.pid for child in self.tx.children if child.poll() is None}
        owner_alive = owner is not None and owner.poll() is None
        if owner_alive:
            live.add(owner.pid)
        available = owner_alive and not self.closed
        if available:
            phase = side + '-owned'
        elif live:
            phase = 'transition-owned'
        elif self.closed:
            phase = 'closed'
        elif target is not None:
            phase = 'target-exited'
        elif self.owner is not None:
            phase = ('captured-' if self.capture_returned else '') + 'source-exited'
        else:
            phase = 'not-started'
        return dict(phase=phase, owner_pid=owner.pid if available else None, live_owner_pids=sorted(live),
                    capture_returned=self.capture_returned, controller_pid=os.getpid(), hot_consumed=self.used,
                    gui_owner_switch_verified=False, display='QMP at ' + side if available else 'none',
                    input='owned ' + side + ' stdin' if available else 'none')

    def hot(self):
        check(not self.used and not self.closed, 'This test-session permits exactly one hot request')
        ready, _ = self.shooting_source('hot')
        check(ready, 'Source unready: latest original page is not shooting main id=0 count=565')
        self.used = True  # shortcut: one hot per DiskTransaction; open a new session for another cycle.
        try:
            self.state_deadline = time.monotonic() + 60
            self.running(self.owner, self.qmp)
            state, _ = sample_live_state(self, self.owner, self.qmp, self.log, 'source')
            states = dict(source=state)
            R['frame_review'](states['source'])
            for field in ('canary', 'boot_id', 'ap_pids', 'viewer_pids', 'claim_sha256', 'flocks'):
                check(states['source'][field] == self.ready_state[field], 'Running source identity changed since ready: ' + field)
            ready, _ = self.shooting_source('capture')
            check(ready, 'Source unready before capture: latest original page is not shooting main')
            R['save'](self.output / 'source-state.json', states['source'])
            frames = dict(source=R['snapshot'](self.qmp, Path(self.launch['dtb']).parent, 'source'))
            marker = 'A7C2_RETAINED_GUEST_SYNC nonce=' + self.tx.guest_sync_nonce + ' sync_rc=0'
            command = "/bin/busybox sync && echo '" + marker + "'"
            E['write_console'](self.owner.stdin, (command + '\n').encode('ascii'))
            R['wait_for'](self.owner, self.log, lambda s: s.splitlines().count(marker) == 1, 30)
            evidence = self.tx._output / 'guest-sync.console'
            R['save_bytes'](evidence, self.log.read_bytes())
            with R['paused'](self.qmp, self.output / 'source-capture-quiesce.jsonl', tx=self.tx, owner=self.owner):
                captured = self.execution.capture(dict(schema='a7c2-retained-guest-sync-v1', kind='guest-console-sync',
                    run=self.source_run, nonce=self.tx.guest_sync_nonce, owner_pid=self.owner.pid,
                    peer_pid=self.execution.identity['peer']['pid'], path=str(evidence), command=command), timeout=self.transfer_timeout)
            self.capture_returned = True
            R['save'](self.output / 'capture-result.json', captured)
            target, qmp, restored = self.execution.restore(target_run=self.target_run, timeout=self.transfer_timeout)
            R['save'](self.output / 'restore-paused-result.json', restored)
            self.execution.continue_target()
            target_log = self.tx._output / 'target/console.log'
            states['restored'], _ = sample_live_state(self, target, qmp, target_log, 'restored')
            R['save'](self.output / 'restored-state.json', states['restored'])
            frames['restored'] = R['snapshot'](qmp, self.tx._output / 'target', 'restored')
            for phase in ('menu', 'shooting'):
                states[phase], observed = sample_live_state(self, target, qmp, target_log, phase)
                R['save'](self.output / (phase + '-state.json'), states[phase])
                R['save'](self.output / (phase + '-input.json'), R['review_input'](observed, phase))
                frames[phase] = R['snapshot'](qmp, self.tx._output / 'target', phase)
            R['save'](self.output / 'frame-state-observations.json', states)
            R['save'](self.output / 'frame-pixels.json', frames)
            headers = R['review_states'](states, frames, self.token)
            check(not re.search(r'^(?:Linux version |COLD_BEFORE_ORIGINAL_INIT)', R['console'](target_log), re.M),
                  'Target unexpectedly cold booted')
            self.running(target, qmp)
            self.content = dict(schema=SCHEMA, status='restored-live', instance_identity=self.instance,
                controller_identity=process(os.getpid()), actual_content_verified=True, owners_closed=False,
                source_run=self.source_run, target_run=self.target_run, source_bindings=SOURCE_BINDINGS,
                profile=self.launch['profile'], qemu_sha256=self.launch['qemu_sha256'],
                source_tree_sha256=self.launch['combo_binding']['source_tree_sha256'],
                cold_manifest=self.cold_row, headers=headers, frames=frames, state_transports=self.state_transports, **LIMITS)
            R['save'](self.output / 'hot-result.json', self.content)
            return dict(artifact=binding(self.output / 'hot-result.json'), state=self.state())
        except BaseException as error:
            R['save'](self.output / 'hot-failure.json', dict(schema=SCHEMA, error=type(error).__name__ + ': ' + str(error),
                state=self.state(), lease_retained_until_owner_exit=True, actual_content_verified=False, **LIMITS))
            raise

    def close(self):
        check(not self.closed, 'Live owner already closed')
        try:
            closed = self.execution.close() if self.execution is not None else (
                R['close_source'](self.tx, self.launch, self.owner, self.qmp) if self.owner is not None else None)
            check(all(child.poll() is not None for child in self.tx.children), 'Live owner retains its lease')
            for child in self.tx.children:
                check(child.returncode == 0, 'Owned process did not normally exit')
            if self.stream is not None:
                self.stream.close()
                self.connection.close()
            if self.owner is not None:
                self.owner.stdin.close()
            self.closed = True
            R['save'](self.output / 'normal-close.json', closed)
            result = dict(self.content or dict(schema=SCHEMA, actual_content_verified=False,
                instance_identity=self.instance, controller_identity=process(os.getpid()), source_bindings=SOURCE_BINDINGS,
                profile=L['UPSTREAM_PROFILE'], qemu_sha256=L['UPSTREAM_BINARY_SHA'], **LIMITS))
            result.update(status='passed' if self.content else 'closed-without-hot', owners_closed=True,
                          hot_consumed=self.used, closed=closed)
            R['save'](self.output / 'result.json', result)
            if self.content:
                try:
                    verify_result(binding(self.output / 'result.json'), self.instance, process(os.getpid()))
                except BaseException:
                    (self.output / 'result.json').rename(self.output / 'unverified-result.json')
                    raise
            return dict(artifact=binding(self.output / 'result.json'), state=self.state())
        except BaseException as error:
            state = self.state()
            R['save'](self.output / ('owner-retained-' + secrets.token_hex(8) + '.json'),
                dict(error=type(error).__name__ + ': ' + str(error), state=state,
                     live_owner_pids=state['live_owner_pids'],
                     lease_retained_until_owner_exit=True, actual_content_verified=False, **LIMITS))
            raise


def verify_result(result_binding, instance, controller):
    """Offline CLOSED content review; active results never satisfy this API."""
    return _verify_result(result_binding, instance, controller)


def _verify_result(result_binding, instance, controller, *, active=False):
    """Shared original content gates, with an explicit internal lifecycle selection."""
    result_path = DEV['checked_binding'](result_binding, private=True)
    output = DEV['path_checked'](result_path.parent, directory=True, private=True)
    check(result_path.name == ('hot-result.json' if active else 'result.json'), 'Unexpected live result lifecycle path')
    result = DEV['read_json'](result_path)
    check(result.get('schema') == SCHEMA and result.get('status') == ('restored-live' if active else 'passed') and
          result.get('actual_content_verified') is True and result.get('owners_closed') is (not active) and
          result.get('instance_identity') == instance and result.get('controller_identity') == controller and
          result.get('source_bindings') == SOURCE_BINDINGS and result.get('profile') == L['UPSTREAM_PROFILE'] and
          result.get('qemu_sha256') == L['UPSTREAM_BINARY_SHA'] and
          result.get('source_tree_sha256') == L['UPSTREAM_SOURCE_SHA'], 'Incomplete or foreign live result')
    check(all(result.get(k) == v for k, v in LIMITS.items()), 'Live result exceeds verified scope')
    COLD['recheck'](SOURCE_BINDINGS)
    refs = []
    def raw(relative, *, budget=R['COLD_TRACE_LIMIT']):
        path = DEV['path_checked'](output / relative, private=True)
        fd = DS['DISK']['SECURE_OPEN'](path)
        try:
            before = DS['_record'](fd)
            check(before['size'] <= budget, 'Evidence exceeds budget: ' + relative)
            data = os.pread(fd, before['size'] + 1, 0)
            check(len(data) == before['size'] and before == DS['_record'](fd), 'Evidence changed during read')
            check(identity(path.stat()) == {k: before[k] for k in ('dev', 'ino')}, 'Evidence inode replaced')
            refs.append(dict(path=str(path), sha256=hashlib.sha256(data).hexdigest(), file_record=before))
            return data
        finally:
            os.close(fd)
    def data(relative):
        return json.loads(raw(relative), object_pairs_hook=DEV['_pairs'])
    source, target = raw('transaction/source-console.log'), raw('transaction/target/console.log')
    token = result['source_run'].removeprefix('retained-source-')
    check(re.fullmatch('[0-9a-f]{32}', token) and result['source_run'] == 'retained-source-' + token and
          result['target_run'] == 'retained-target-' + token,
          'Live source/target run mismatch')
    trace = raw('source-cold-trace.log')
    proof = R['decode_cold_proof'](trace, token)
    check(source.startswith(trace) and raw('source-cold-proof.txt') == proof and
          raw('source-cold-collector.log') == trace + b'\n' + proof and
          data('source-cold-proof.json') == R['cold_proof_binding'](output, token, trace, proof), 'Cold proof differs')
    cold_receipt = E['new_receipt']('original-init-cold', bindings=dict(run=result['source_run'],
        source_class=data('launch/launch.json')['disk_source_class']), kernel_cmdline=data('launch/launch.json')['cmdline'])
    coverage = E['collect'](output / 'source-cold-collector.log', cold_receipt)
    check(coverage == data('source-cold-evidence.json') and coverage['ap_verified'] and coverage['cold_guest_chain_verified'],
          'Strong original cold collector failed')
    check(not re.search(rb'^(?:Linux version |COLD_BEFORE_ORIGINAL_INIT)', target, re.M), 'Target cold boot rejected')
    states, frames = {}, {}
    captured, restored = data('capture-result.json'), data('restore-paused-result.json')
    check(type(result.get('state_transports')) is dict and set(result['state_transports']) ==
          {'ready', 'source', 'restored', 'menu', 'shooting'}, 'Missing exact live state transports')
    ready, _ = replay_live_state(output, 'ready', token, source, captured['source_identity']['owner']['pid'],
        result['state_transports']['ready'], raw)
    check(data('ready-state.json') == ready, 'Ready state receipt differs')
    for phase in ('source', 'restored', 'menu', 'shooting'):
        states[phase], observed = replay_live_state(output, phase, token, source if phase == 'source' else target,
            (captured['source_identity'] if phase == 'source' else restored['target_identity'])['owner']['pid'],
            result['state_transports'][phase], raw)
        check(data(phase + '-state.json') == states[phase], 'Guest state receipt differs')
        if phase == 'source':
            for field in ('canary', 'boot_id', 'ap_pids', 'viewer_pids', 'claim_sha256', 'flocks'):
                check(states[phase][field] == ready[field], 'Ready/source identity differs: ' + field)
        base = 'launch/run/' if phase == 'source' else 'transaction/target/'
        frames[phase] = R['pixel_review'](raw(base + phase + '.ppm'), raw(base + phase + '-scanout-pool.bin'))
        pixels = R['LCD']['decode_ppm'](raw(base + phase + '.ppm'))
        check(pixels == frames[phase]['pixels_sha256'], 'LCD decode differs')
        if phase in ('menu', 'shooting'):
            # Each MENU section has its own original edge and new screen evidence.
            start = 0 if phase == 'menu' else data('menu-state-transport.json')['end']
            end = data(phase + '-state-transport.json')['end']
            check(type(start) is type(end) is int and 0 <= start < end <= len(target), 'Original input window differs')
            observed = target[start:end].decode('utf-8', errors='replace').replace('\r', '')
            check(data(phase + '-input.json') == R['review_input'](observed, phase), 'Original input edges differ')
    mapped = re.findall(rb'^COLD_AP_MAP pid=([1-9][0-9]*) sha256=' + E['APPFW_SHA256'].encode() + rb'$', proof, re.M)
    check(states['source']['ap_pids'] == [p.decode() for p in mapped], 'Retained AP PID differs from actual original AP mapping')
    check(data('frame-state-observations.json') == states and data('frame-pixels.json') == frames == result['frames'] and
          R['review_states'](states, frames, token) == result['headers'], 'Original identity or fresh LCD differs')
    disk = data('transaction/disk-binding.json')
    DS['_validate'](disk, DS['BINDING_SCHEMA'])
    check(disk['transaction']['parent_pid'] == controller['pid'] and
          all(disk['disk'][k] == instance[v] for k, v in (('dev', 'dev'), ('ino', 'ino'), ('size', 'bytes'))) and
          disk['disk_generation'] == instance['generation'], 'Live disk/parent binding differs')
    digest = C['R']['_digest'](disk)
    for index, phase in enumerate(DS['PHASES']):
        row = data('transaction/disk-' + phase + '.json')
        queries = row.get('qmp', [])
        statuses = [r['response'] for r in queries if r['command'] == 'query-status']
        check(row['phase'] == phase and row['disk_binding_verified'] is True and row['binding_sha256'] == digest and
              row['host_run'] == result['source_run' if index < 2 else 'target_run'] and
              row['migration_generation'] == (0 if index < 2 else 1) and row['disk_generation'] == instance['generation'] and
              len(statuses) >= 2 and all(r.get('running') is False and r.get('status') == DS['STATES'][index] for r in statuses),
              'Four disk phases not verified')
        if index == 1:
            migrations = [r['response'] for r in queries if r['command'] == 'query-migrate']
            check(len(migrations) >= 2 and all(r.get('status') == 'completed' for r in migrations), 'Outgoing completion differs')
    captured, restored = data('capture-result.json'), data('restore-paused-result.json')
    continued = data('transaction/continued.json')
    check(captured['status'] == 'captured-source-postmigrate' and restored['status'] == 'restored-paused' and
          continued['status'] == 'continued-awaiting-new-guest-evidence' and continued['retained_cpu_resumed'] is True,
          'Capture/restore/cont not complete')
    check(all(row['source_run'] == result['source_run'] for row in (captured, restored, continued)) and
          restored['target_run'] == continued['target_run'] == result['target_run'], 'Execution run differs')
    if active:
        closed = continued  # Stream/audit anchor; no target close is inferred or written.
        owners = captured['owners']
        check(len(owners) == 1 and owners == restored['owners'] == continued['owners'] and
              continued.get('owners_closed', False) is False, 'Active target was already closed')
        admission = data('transaction/target-admission.json')
        check(admission['transaction'] == disk['transaction'] and admission['disk_binding_sha256'] == digest and
              admission['run'] == result['target_run'] and admission['disk_generation'] == instance['generation'] and
              admission['migration_generation'] == 1 and admission['snapshot_sha256'] == continued['snapshot_sha256'],
              'Target not registered to this transaction')
    else:
        closed = data('normal-close.json')
        check(closed == result['closed'] == data('transaction/execution-closed.json') and closed['owners_closed'] is True,
              'Normal close not complete')
        owners = closed['owners']
        check(len(owners) == 2 and captured['owners'] == restored['owners'] == [owners[0]],
              'Both owners must normally close')
    check(all(r.get('returncode') == 0 and r.get('signals_sent') == [] and 'quit_response' in r for r in owners),
          'Source must normally quit before restore; closed owners must normally exit')
    pids = []
    for side in ('source', 'target'):
        proc = closed[side + '_identity']
        check(proc['owner']['parent_pid'] == controller['pid'] and proc['memory']['base-memory'] == 24576 * 1024 ** 2,
              'Owned parent/RAM differs')
        check(proc['environment'].get('QEMU_A7PF_PROFILE') == L['UPSTREAM_PROFILE'] and
              all(proc['environment'].get(k) == v for k, v in L['UPSTREAM_USB'].items()), 'USB profile differs')
        for kind in ('owner', 'peer'):
            saved = proc[kind]
            pids.append(saved['pid'])
            check(saved['uid'] == os.getuid() and saved['start_ticks'] > 0, 'Owned PID identity invalid')
            if active and side == 'target':
                check(process(saved['pid']) == saved, 'Target PID/start ticks/UID changed')
                continue
            try:
                now = process(saved['pid'])
            except FileNotFoundError:
                continue
            check(now['start_ticks'] != saved['start_ticks'], 'Original owner/peer is still alive')
    check(len(set(pids)) == 4 and [r['pid'] for r in owners] == ([pids[0]] if active else [pids[0], pids[2]]),
          'Target must have new owner/peer')
    check(captured['source_identity'] == closed['source_identity'] and
          restored['target_identity'] == continued['target_identity'] == closed['target_identity'], 'Process identity changed')
    for row in (captured, restored, continued, closed):
        check(row['disk_binding_sha256'] == digest and row['migration_outgoing']['status'] == 'completed' and
              row['device_audit']['type_counts'] == C['SOURCE_COUNTS'] and row['device_audit']['profile'] == L['UPSTREAM_PROFILE'] and
              all(row[k] == closed[k] for k in ('snapshot_sha256', 'snapshot_bytes', 'snapshot_file_record')),
              'Migration/audit/stream bindings differ')
    check(restored['migration_incoming']['status'] == closed['migration_incoming']['status'] == 'completed', 'Incoming completion differs')
    stream = DEV['path_checked'](output / 'transaction/snapshot.partial', private=True)
    with os.fdopen(DS['DISK']['SECURE_OPEN'](stream), 'rb') as f:
        check(DS['_record'](f.fileno()) == closed['snapshot_file_record'], 'RAM stream inode differs')
        check(C['R']['_hash'](f) == (closed['snapshot_sha256'], closed['snapshot_bytes']), 'Complete RAM stream hash differs')
        check(DS['_record'](f.fileno()) == closed['snapshot_file_record'] and identity(stream.stat()) ==
              {k: closed['snapshot_file_record'][k] for k in ('dev', 'ino')}, 'RAM stream replaced during review')
    sync = raw('transaction/guest-sync.console')
    marker = 'A7C2_RETAINED_GUEST_SYNC nonce=' + captured['guest_sync']['nonce'] + ' sync_rc=0'
    check(sync.splitlines().count(marker.encode()) == 1 and source.startswith(sync), 'Actual guest sync evidence differs')
    DEV['checked_binding'](result_binding, private=True)
    return dict(result=result_binding, evidence=refs, actual_content_verified=True, owners_closed=not active,
                **(dict(target_identity=continued['target_identity'], disk_transaction=disk['transaction']) if active else {}),
                **LIMITS)


def verify_active_result(owner_binding, instance, response):
    """Strong hot content plus authenticated, still-owned target/frontend transport.

    This does not validate the visible host window. Failure never closes an owner.
    """
    with endpoint(owner_binding, instance) as (descriptor, _):
        check(descriptor['frontend_enabled'] is True, 'Active review requires an explicit frontend')
        expected = dict(schema=SCHEMA, action='hot', nonce=descriptor['nonce'], instance_identity=instance,
            socket_identity=descriptor['socket_identity'], client_identity=process(os.getpid()), frontend_enabled=True)
        check(set(response) == {'schema', 'request', 'controller_identity', 'status', 'result'} and
              response['schema'] == SCHEMA and response['request'] == expected and response['status'] == 'completed' and
              response['controller_identity'] == descriptor['controller_identity'], 'Active response authentication differs')
        value = response['result']
        check(set(value) == {'artifact', 'state'} and Path(value['artifact']['path']) ==
              Path(owner_binding['path']).parent / 'hot-result.json', 'Foreign active artifact')
        reviewed = _verify_result(value['artifact'], instance, descriptor['controller_identity'], active=True)
        target = reviewed.pop('target_identity')
        transaction = reviewed.pop('disk_transaction')
        output = Path(value['artifact']['path']).parent
        state = value['state']
        expected_state = dict(phase='target-owned', owner_pid=target['owner']['pid'],
            live_owner_pids=[target['owner']['pid']], capture_returned=True,
            controller_pid=descriptor['controller_identity']['pid'], hot_consumed=True,
            gui_owner_switch_verified=False, display='QMP at target', input='owned target stdin')
        check(set(state) == set(expected_state) | {'frontend'} and
              all(state[k] == v for k, v in expected_state.items()), 'Authenticated target-owned state differs')
        frontend_path = DEV['checked_binding'](state['frontend'], private=True)
        check(frontend_path == output / 'frontend-hot.json', 'Foreign frontend switch evidence')
        selected = DEV['read_json'](frontend_path)
        directory = output / 'transaction/target'
        frame, input_dir = output / 'frontend/live-frame.ppm', output / 'frontend/input'
        check(selected['owner_pid'] == selected['input_owner_pid'] == target['owner']['pid'] and
              selected['source_directory'] == str(directory) and selected['source_log'] == str(directory / 'console.log') and
              selected['frame'] == str(frame) and selected['input_dir'] == str(input_dir), 'Frontend selected a foreign owner/transport')
        DEV['path_checked'](frame, private=True)
        DEV['path_checked'](input_dir, directory=True, private=True)
        current = DEV['read_json'](DEV['path_checked'](output / 'frontend/status.json', private=True))
        for status in (selected['status'], current):
            check(status['phase'] == 'target-running' and status['error'] == '' and
                  status['frame'] == str(frame) and status['input_dir'] == str(input_dir) and
                  status['source_directory'] == str(directory) and status['owner_pid'] == target['owner']['pid'] and
                  status['state'] == expected_state and status['gui_owner_switch_verified'] is False and
                  re.fullmatch('[0-9a-f]{64}', status['pixels_sha256']), 'Frontend target status is unverified')
        for kind in ('owner', 'peer'):
            check(process(target[kind]['pid']) == target[kind], 'Target changed during active review')
        cursor = target['peer']['pid']
        for _ in range(12):
            if cursor == target['owner']['pid']:
                break
            cursor = process(cursor)['parent_pid']
        else:
            raise ValueError('Target peer is not descended from its registered owner')
        for pid in (descriptor['controller_identity']['pid'], target['peer']['pid']):
            disk_fd = Path('/proc') / str(pid) / 'fd' / str(transaction['fd'])
            info = disk_fd.stat()
            check((info.st_dev, info.st_ino, info.st_size) == (instance['dev'], instance['ino'], instance['bytes']),
                  'Live inherited disk/lease FD differs')
        DEV['checked_binding'](value['artifact'], private=True)
        DEV['checked_binding'](state['frontend'], private=True)
        reviewed.update(lifecycle='live-target-owned', owner_retained=True, live_state=state,
            frontend=state['frontend'], runtime_transport_verified=True, lease_retained_until_owner_exit=True)
        return reviewed


def serve(context_path, output, *, source_timeout=180, transfer_timeout=360, frontend=False):
    check(type(frontend) is bool, 'Frontend selection must be explicit bool')
    for value in (source_timeout, transfer_timeout):
        check(type(value) in (int, float) and 0 < value <= 3600, 'Invalid bounded evidence/transfer timeout')
    context_path = DEV['path_checked'](context_path, private=True)
    context = DEV['load_context'](context_path)
    instance = DEV['bind_instance'](context)
    cap = DEV['sequence_capability'](context, instance)
    output = Path(os.path.abspath(output))
    check(not os.path.lexists(output), 'Output must be a new private directory')
    DEV['path_checked'](output.parent, directory=True)
    cold_row = COLD['binding'](cap['cold_manifest']['path'], 'retained-live-cold-manifest')
    check(all(cold_row[k] == cap['cold_manifest'][k] for k in ('path', 'sha256')), 'Cold capability changed before source preparation')
    cold = DEV['read_json'](cold_row['path'])
    source = COLD['plain'](cold['instance'], directory=True)
    check(cold.get('profile') == P['PROFILE'] and cold.get('build_verified') is True and
          cold.get('instance_generation') == instance['generation'] and cold.get('source') in DS['SOURCES'] and
          cold.get('prepared_runtime_analysis') == cap['runtime_analysis'] and cold.get('partition_images_in_ram0') == 0 and
          cold.get('block_module', {}).get('sha256') == cap['persistent_module']['sha256'],
          'Cold source manifest does not preserve the fixed source contract')
    P['firmware_contract'](cold)
    P['current_kernel_binding'](cold['actual_kernel'])
    check(Path(instance['manifest']).parent == source and Path(instance['disk']) == source / 'camera.emmc', 'Live source instance differs')
    for path in (source, Path(cap['runtime_analysis'])):
        check(not output.is_relative_to(path) and not path.is_relative_to(output), 'Output overlaps source assets')
    output.mkdir(mode=0o700)
    old_umask = os.umask(0o077)
    try:
        with P['DISK']['lease'](source) as leased:
            private = R['metadata'](source)
            P['identical']('source class', cold['source'], leased['state']['source_class'])
            P['verify_firmware'](leased, cold)
            originals = P['ext2_identities'](P['part'](leased, 'nflasha15'), ['/bin/bootin.elf', '/lib/appFw.so'])
            for name, expected in (('/bin/bootin.elf', E['BOOTIN_SHA256']), ('/lib/appFw.so', E['APPFW_SHA256'])):
                P['identical']('stock disk ' + name, expected, originals[name]['sha256'])
        R['save'](output / 'preflight.json', dict(metadata=private, original_elfs=originals,
            cold_manifest=cold_row, source_bindings=SOURCE_BINDINGS))
        launch = L['prepare_launch'](Path(cap['runtime_analysis']), Path(cold_row['path']), output / 'launch', upstream_host=True,
            combo_manifest=Path(cap['combo_manifest']['path']), origin_qemu_build=Path(cap['origin_qemu_build']))
        transaction = output / 'transaction'
        transaction.mkdir(mode=0o700)
        with DS['transaction'](source, transaction) as tx:
            session = LiveSession(context_path, context, cap, output, tx, launch, cold, cold_row, private, originals)
            session.transfer_timeout = transfer_timeout
            try:
                ready = session.start(source_timeout)
                transport = (runpy.run_path(str(HERE / 'retained-camera-frontend.py'))['Frontend'](session, R, DEV)
                             if frontend and ready else None)
                # An unready endpoint permits typed close; it never publishes source-ready or attaches a GUI.
                control = OwnerControl(session, transport)
                print(json.dumps(dict(schema=SCHEMA, status='source-running' if ready else 'source-unready',
                    owner=binding(output / 'live-owner.json'), state=session.state(), **LIMITS)), flush=True)
                control.serve()
            except BaseException as error:
                R['save'](output / 'failure.json', dict(schema=SCHEMA, error=type(error).__name__ + ': ' + str(error),
                    state=session.state(), actual_content_verified=False, **LIMITS))
                raise
            finally:
                if not session.closed:
                    session.close()  # Frozen transaction waits without releasing a live owner's OFD lease.
    finally:
        os.umask(old_umask)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='action', required=True)
    start = sub.add_parser('serve')
    start.add_argument('--context', type=Path, required=True)
    start.add_argument('--output', type=Path, required=True)
    start.add_argument('--frontend', action='store_true', help='same-owner serialized Rust GUI LCD/input transport')
    for name in ('hot', 'close'):
        command = sub.add_parser(name)
        command.add_argument('--owner', type=Path, required=True, help='exact live-owner.json')
        command.add_argument('--owner-sha256', required=True)
        command.add_argument('--context', type=Path, required=True)
    args = parser.parse_args(argv)
    if args.action == 'serve':
        serve(args.context, args.output, frontend=args.frontend)
    else:
        context = DEV['load_context'](args.context)
        print(json.dumps(request(dict(path=str(args.owner), sha256=args.owner_sha256), DEV['bind_instance'](context), args.action)))


if __name__ == '__main__':
    main()
