#!/usr/bin/env python3
"""Private original-AP retained roundtrip controller; uses the fixed production core.

run(runtime_analysis, cold_manifest, output, *, combo_manifest=...,
    origin_qemu_build=..., source_timeout=180, transfer_timeout=360) -> dict

Blocking owner/lease scope, suitable for a panel worker process. Never build,
reseed, signal a VM, release a live owner's lease, or fall back to a cold target.
"""
import argparse
import base64
from contextlib import ExitStack, contextmanager
import hashlib
import json
import os
from pathlib import Path
import re
import runpy
import secrets
import socket
import struct
import subprocess
import time

HERE = Path(__file__).resolve().parent
C = runpy.run_path(str(HERE/'newretained-camera-execution.py'))
L, DS = C['LAUNCH'], C['DS']
P, COLD = L['PERSISTENT'], L['COLD']
E = runpy.run_path(str(HERE/'boot-execution.py'))
LCD = runpy.run_path(str(HERE/'lcd-stream.py'))
SOURCE_BINDINGS = [COLD['binding'](HERE/name, 'retained-test-loaded-source') for name in (
    'retained-camera-test.py', 'newretained-camera-execution.py', 'retained-disk-state.py',
    'retained-camera-launch.py', 'retained-boot.py', 'persistent-boot.py', 'boot-execution.py', 'lcd-stream.py')]
SCAN_BASE, SCAN_BYTES, SCAN_SLOT = 0x41E100000, 0x500000, 0x200000
IM_SHA256 = '5171f576d8b76cfbf15581389183b390c445bd6ff9dd97fd6668c5f64e77dc91'
COLD_PROOF_CHUNK = 192
COLD_PROOF_LIMIT = 1024**2
COLD_TRACE_LIMIT = 64*1024**2


def save(path, value):
    """Private, exclusive publication; never replace a successful old receipt."""
    with os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600), 'w') as f:
        json.dump(value, f, indent=2)
        f.write('\n')
        f.flush()
        os.fsync(f.fileno())


def authenticate_owner(tx, owner, qmp):
    """Authenticate the connected peer without sampling the active disk."""
    if not any(child is owner for child in tx.children) or owner.poll() is not None:
        raise ValueError('QMP is not owned: live owner must be registered in this transaction')
    pid, uid, _ = struct.unpack('3i', qmp.sock.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12))
    if uid != os.getuid():
        raise ValueError('QMP is not owned: peer UID differs')
    peer, parent = C['_proc_identity'](pid), C['_proc_identity'](owner.pid)
    if peer['uid'] != os.getuid() or parent['uid'] != os.getuid():
        raise ValueError('QMP is not owned: process UID differs')
    if parent['parent_pid'] != os.getpid():
        raise ValueError('QMP is not owned: owner parent is not this controller')
    cursor = pid
    for _ in range(12):
        if cursor == owner.pid:
            break
        if cursor <= 1:
            raise ValueError('QMP is not owned: peer is not descended from registered owner')
        cursor = C['_proc_identity'](cursor)['parent_pid']
    else:
        raise ValueError('QMP is not owned: peer is not descended from registered owner')
    if owner.poll() is not None:
        raise ValueError('QMP is not owned: registered owner exited during authentication')


@contextmanager
def paused(qmp, evidence, *, tx, owner, resume=False):
    """Authenticate, then quiesce writes before strict FD/path checks."""
    with os.fdopen(os.open(evidence, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600), 'w') as stream:
        def record(value):
            stream.write(json.dumps(value, allow_nan=False)+'\n')
            stream.flush()
            os.fsync(stream.fileno())

        def call(command):
            record(dict(command=command, event='request'))
            response = qmp(command)
            record(dict(command=command, event='response', response=response))
            return response

        def status(value, name):
            if type(value) is not dict or value.get('status') != name or value.get('running') is not (name == 'running'):
                raise ValueError('Actual QMP must report '+name+' with matching running state')

        try:
            authenticate_owner(tx, owner, qmp)
            record(dict(event='owner-authenticated', owner_pid=owner.pid))
            before = call('query-status')
            if type(before) is not dict or before.get('status') not in ('running', 'paused'):
                raise ValueError('Source must actually be running or paused before quiesce')
            status(before, before['status'])
            call('stop')
            status(call('query-status'), 'paused')
            yield
            if resume and before['running']:
                status(call('query-status'), 'paused')
                call('cont')
                status(call('query-status'), 'running')
            record(dict(event='completed'))
        except BaseException as error:
            record(dict(event='failed', error=type(error).__name__+': '+str(error)))
            raise


def console(path):
    return path.read_bytes().decode('utf-8', errors='replace').replace('\r', '')


def wait_for(owner, path, condition, seconds):
    deadline = time.monotonic()+seconds
    while time.monotonic() < deadline:
        text = console(path)
        if 'Internal error: Oops:' in text or 'Kernel panic - not syncing:' in text:
            raise RuntimeError('Original kernel fault; console retained')
        if owner.poll() is not None:
            raise RuntimeError('Owned VM exited before evidence: '+str(owner.returncode))
        if condition(text):
            return text
        time.sleep(.2)
    raise TimeoutError('Guest evidence timeout; no cold fallback or VM signal')


def shell(owner, log, script, phase, token):
    # Exact stdout lines exclude the shell's echoed heredoc/echo commands.
    marker = 'RETAINED_DONE_'+phase+'='+token
    offset = len(console(log))
    envelope = E['diagnostic_envelope'](script, 'RETAINED_SCRIPT_'+token+'_'+phase)
    E['write_console'](owner.stdin, envelope.encode('ascii'))
    text = wait_for(owner, log, lambda s: marker in s[offset:].splitlines(), 100)[offset:]
    if text.splitlines().count(marker) != 1:
        raise ValueError('Guest completion marker must be unique')
    return text


def section(text, begin, end):
    lines = text.splitlines()
    if lines.count(begin) != 1 or lines.count(end) != 1:
        raise ValueError('Missing or repeated exact guest section marker')
    first, last = lines.index(begin), lines.index(end)
    if first >= last:
        raise ValueError('Guest section markers out of order')
    return '\n'.join(lines[first+1:last])+'\n'


def parse_state(text, phase):
    part = section(text, 'RETAINED_STATE_BEGIN='+phase, 'RETAINED_STATE_END='+phase)

    def one(pattern):
        matches = re.findall(pattern, part, re.M)
        if len(matches) != 1:
            raise ValueError('Expected one state field: '+pattern)
        return matches[0]

    for field in ('Uid', 'Gid'):
        one(r'^'+field+r':\s+0\s+0\s+0\s+0$')
    pids = {key: re.findall(r'^RETAINED_'+label+r'_PID=([1-9][0-9]*)$', part, re.M)
            for key, label in (('ap_pids', 'APP'), ('viewer_pids', 'VIEWER'))}
    if any(len(value) != 1 for value in pids.values()):
        raise ValueError('Exactly one original AP and viewer required')
    flocks = [line.split()[1:] for line in part.splitlines() if re.fullmatch(
        r'\d+: FLOCK\s+ADVISORY\s+WRITE\s+[1-9][0-9]*\s+[0-9a-f]+:[0-9a-f]+:\d+\s+0\s+EOF', line)]
    if len(flocks) != 2 or {row[3] for row in flocks} != set(pids['ap_pids']+pids['viewer_pids']):
        raise ValueError('Original AP/viewer FLOCK owner and inode evidence required')
    return dict(canary=one(r'^RETAINED_CANARY=([0-9a-f]{32})$'),
        boot_id=one(r'^RETAINED_BOOT_ID=([0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12})$'),
        uptime=float(one(r'^RETAINED_UPTIME=([0-9]+\.[0-9]+) [0-9]+\.[0-9]+$')),
        claim_sha256=one(r'^(?:SHA256|SHA2-256)\(/dev/qemu-simulation/headless-osd\.claim\)= ([0-9a-f]{64})$'),
        flocks=sorted(flocks), frame_header_base64=one(r'^RETAINED_FRAME_HEADER=([A-Za-z0-9+/=]+)$'),
        viewer_status=section(part, 'RETAINED_VIEWER_STATUS_BEGIN', 'RETAINED_VIEWER_STATUS_END'), **pids)


def frame_review(state):
    raw = base64.b64decode(state['frame_header_base64'], validate=True)
    if len(raw) != 128 or raw[:8] != b'HOSDAP02':
        raise ValueError('Expected complete original HOSDAP02 header')
    def le(offset, size):
        return int.from_bytes(raw[offset:offset+size], 'little')
    seq, pixels, physical, cmd = le(8, 8), le(120, 8), le(32, 8), le(56, 4)
    fixed = {20: (4, 640), 24: (4, 480), 28: (4, 1), 48: (4, 614400), 52: (4, 24930),
             64: (2, 0x1003), 80: (2, 0), 84: (2, 640), 86: (2, 480), 100: (2, 0x1002)}
    if (any(le(offset, size) != value for offset, (size, value) in fixed.items()) or
            not 0 < pixels <= seq or cmd not in (0x1003, 0x1005) or
            (cmd == 0x1003 and pixels != seq) or not 0x410000000 <= physical <= 0x500000000-614400 or
            le(72, 4) != le(16, 4) or le(108, 4) != cmd or (cmd == 0x1005 and le(112, 2) != cmd)):
        raise ValueError('Original frame identity, descriptor or bounds differ')
    rows = re.findall(r'^RAMFB_(SUBMITTED|RETAINED) reason=DMA is not screenshot proof errno=\d+ '
        r'seq=(\d+) pixel_source=(\d+) source_phys=(0x[0-9a-f]+) hash=([0-9a-f]{16}) '
        r'scanout=(0x[0-9a-f]+)$', state['viewer_status'], re.M)
    if len(rows) != 1:
        raise ValueError('Expected one exact viewer status line; noise retained separately')
    action, vseq, vpix, vphys, digest, scanout = rows[0]
    if (not 0 < int(vpix) <= int(vseq) or not 0x410000000 <= int(vphys, 16) <= 0x500000000-614400 or
            int(scanout, 16) not in (SCAN_BASE, SCAN_BASE+SCAN_SLOT)):
        raise ValueError('Viewer frame bounds differ')
    return dict(seq=seq, pixel_source_seq=pixels, header_sha256=hashlib.sha256(raw).hexdigest(),
                viewer=dict(action=action, seq=int(vseq), pixel_source_seq=int(vpix), scanout=scanout))


def pixel_review(ppm, pool):
    ppm_sha = LCD['decode_ppm'](ppm)
    if len(pool) != SCAN_BYTES:
        raise ValueError('Incomplete scanout RAM pool')
    address, fourcc, flags, width, height, stride = struct.unpack_from('>Q5I', pool, SCAN_BYTES-0x1000+64)
    if ((fourcc, flags, width, height, stride) != (0x34325258, 0, 640, 480, 2560) or
            address not in (SCAN_BASE, SCAN_BASE+SCAN_SLOT)):
        raise ValueError('Original published scanout configuration/bounds differ')
    offset = address-SCAN_BASE
    bgrx = pool[offset:offset+height*stride]
    rgb = bytearray(640*480*3)
    rgb[0::3], rgb[1::3], rgb[2::3] = bgrx[2::4], bgrx[1::4], bgrx[0::4]
    if hashlib.sha256(rgb).hexdigest() != ppm_sha:
        raise ValueError('QMP pixels differ from published BGRX scanout RAM')
    return dict(pixels_sha256=ppm_sha, scanout_address=hex(address), published_scanout_pixels_equal=True)


def review_states(states, frames, token):
    baseline = states['source']
    if baseline['canary'] != token:
        raise ValueError('Source RAM canary differs')
    reviewed = {}
    previous = None
    for phase in ('source', 'restored', 'menu', 'shooting'):
        current = states[phase]
        for field in ('canary', 'boot_id', 'ap_pids', 'viewer_pids', 'claim_sha256', 'flocks'):
            if current[field] != baseline[field]:
                raise ValueError('Retained guest identity differs: '+field)
        row = frame_review(current)
        if previous is not None:
            if (current['uptime'] < previous[0]['uptime'] or any(
                    row[key] <= previous[1][key] for key in ('seq', 'pixel_source_seq')) or any(
                    row['viewer'][key] <= previous[1]['viewer'][key] for key in ('seq', 'pixel_source_seq'))):
                raise ValueError('Fresh original frame/uptime required; retained old pixels rejected')
        reviewed[phase] = row
        previous = current, row
    if frames['menu']['pixels_sha256'] == frames['shooting']['pixels_sha256']:
        raise ValueError('MENU and returned original page must have different QMP pixels')
    if frames['source']['pixels_sha256'] == frames['menu']['pixels_sha256']:
        raise ValueError('MENU still shows old source pixels')
    return reviewed


def native_records(text):
    return re.sub(r'^/ # (?=OBS (?:FULL_INPUT_RECEIVE|FULL_INPUT_FREE_ENTER|CREATE_SCREEN_ARGS) )', '', text, flags=re.M)


def review_input(text, phase):
    text = native_records(text)
    sent = re.findall(r'^INJECT_KEY_SEND queue=0x807a0020 src=0x92840747 key_code=0x1ab '
        r'sub=0 status=(0x1|0) ex=0 from=0x1 result=0$', text, re.M)
    if sent != ['0x1', '0']:
        raise ValueError('Two successful original MENU send edges required')
    fields = r'tid=\d+ queue=0x[0-9a-f]+ message=0x[0-9a-f]+ code=0x1ab status=[01] prev=\d+'
    received = re.findall(r'^OBS FULL_INPUT_RECEIVE ('+fields+r') repeat=0 from=1 inh=0$', text, re.M)
    freed = re.findall(r'^OBS FULL_INPUT_FREE_ENTER ('+fields+r')$', text, re.M)
    if (len(received) != 2 or received != freed or
            [re.search(r' status=([01]) ', line)[1] for line in received] != ['1', '0']):
        raise ValueError('Original receive/free-enter message identities and edges differ')
    screen, count = ('0x2c9', 46) if phase == 'menu' else ('0', 565)
    if not re.search(r'^OBS CREATE_SCREEN_ARGS call=\d+ id='+screen+r' count='+str(count)+r' orientation=0 .+$', text, re.M):
        raise ValueError('Expected newly created original '+phase+' page')
    return dict(received_edges=2, free_enter_edges=2, free_return_code_verified=False)


def state_script(phase, token, create=False):
    return f'''set -e
{'test ! -e /dev/qemu-simulation/retained-canary' if create else ''}
{'echo '+token+' > /dev/qemu-simulation/retained-canary' if create else ''}
echo RETAINED_STATE_BEGIN={phase}
busybox grep -E '^(Uid|Gid):' /proc/$$/status
echo RETAINED_CANARY=$(cat /dev/qemu-simulation/retained-canary)
echo RETAINED_BOOT_ID=$(cat /proc/sys/kernel/random/boot_id)
echo RETAINED_UPTIME=$(cat /proc/uptime)
cat /proc/locks
frame_header=$(busybox dd if=/dev/qemu-simulation/headless-osd-frame.bin bs=128 count=1 2>/dev/null | /usr/bin/openssl enc -base64 -A)
echo RETAINED_FRAME_HEADER=$frame_header
echo RETAINED_VIEWER_STATUS_BEGIN
cat /tmp/ramfb-viewer.status
echo RETAINED_VIEWER_STATUS_END
/usr/bin/openssl dgst -sha256 /dev/qemu-simulation/headless-osd.claim
for p in /proc/[0-9]*; do
 e=$(busybox readlink "$p/exe" 2>/dev/null) || continue
 case "$e" in */ramfb-viewer)
 echo RETAINED_VIEWER_PID=${{p##*/}}
 cat "$p/wchan" "$p/stack"
 ls -l "$p/fd"
 ;; esac
 if busybox grep -q /usr/lib/appFw.so "$p/maps"; then
  echo RETAINED_APP_PID=${{p##*/}}
 fi
done
echo RETAINED_STATE_END={phase}
echo RETAINED_DONE_{phase}={token}
'''


def cold_proof_path(token):
    if not isinstance(token, str) or not re.fullmatch(r'[0-9a-f]{32}', token):
        raise ValueError('Cold proof nonce must be 32 lowercase hex digits')
    return '/dev/qemu-simulation/retained-cold-'+token+'.proof'


def decode_cold_proof(raw, token):
    """Decode only intact nonce/offset records; never repair an interrupted line."""
    guest_path = cold_proof_path(token).encode('ascii')
    if not raw or len(raw) > COLD_TRACE_LIMIT:
        raise ValueError('Cold proof trace exceeds read budget or is empty')
    # Console CRLF is a line terminator; an embedded CR remains a protocol error.
    lines = [line[:-1] if line.endswith(b'\r') else line for line in raw.split(b'\n')]
    records = [line for line in lines if line.startswith(b'RETAINED_COLD_')]
    identity = b' nonce='+token.encode('ascii')+b' file='+guest_path
    meta = re.fullmatch(rb'RETAINED_COLD_META'+re.escape(identity)+rb' bytes=([1-9][0-9]{0,6}) sha256=([0-9a-f]{64})',
                        records[0] if records else b'')
    if meta is None:
        raise ValueError('Missing or invalid cold proof metadata/nonce/file identity')
    size, digest = int(meta[1]), meta[2].decode('ascii')
    if size > COLD_PROOF_LIMIT:
        raise ValueError('Cold proof exceeds size budget')
    if len(records) != (size+COLD_PROOF_CHUNK-1)//COLD_PROOF_CHUNK+2:
        raise ValueError('Missing or repeated cold proof records')
    expected_end = b'RETAINED_COLD_END'+identity+b' bytes='+meta[1]+b' sha256='+meta[2]
    if records[-1] != expected_end:
        raise ValueError('Cold proof final guest hash/nonce/file differs')
    decoded = bytearray()
    for record in records[1:-1]:
        chunk = re.fullmatch(rb'RETAINED_COLD_CHUNK nonce='+token.encode('ascii')+
                            rb' offset=(0|[1-9][0-9]{0,6}) data=([A-Za-z0-9+/=]{1,256})', record)
        if chunk is None or int(chunk[1]) != len(decoded):
            raise ValueError('Cold proof chunk base64/nonce/continuous offset differs')
        try:
            payload = base64.b64decode(chunk[2], validate=True)
        except ValueError as error:
            raise ValueError('Invalid cold proof base64') from error
        if (base64.b64encode(payload) != chunk[2] or
                len(payload) != min(COLD_PROOF_CHUNK, size-len(decoded))):
            raise ValueError('Cold proof chunk length or canonical base64 differs')
        decoded.extend(payload)
    proof = bytes(decoded)
    if len(proof) != size or hashlib.sha256(proof).hexdigest() != digest:
        raise ValueError('Cold proof complete length/SHA256 differs')
    begin = b'RETAINED_COLD_FILE'+identity+b'\n'
    end = b'RETAINED_COLD_FILE_END'+identity+b'\n'
    if not proof.startswith(begin) or not proof.endswith(end) or proof.count(begin) != 1 or proof.count(end) != 1:
        raise ValueError('Cold proof decoded file identity differs')
    im = re.findall(rb'^COLD_NATIVE_IM pid=([1-9][0-9]*) exe=(/usr/bin/im\.elf|/bin/im\.elf) sha256='+
                    IM_SHA256.encode('ascii')+rb'$', proof, re.M)
    if len(im) != 1 or proof.splitlines().count(b'COLD_EXECUTABLE=/usr/bin/im.elf') != 1:
        raise ValueError('Cold proof requires one actual IM PID/exe/SHA256 identity')
    pid, executable = im[0]
    actual = (rb'^COLD_PROCESS pid='+pid+rb' exe='+re.escape(executable)+rb'\n(?:SHA256|SHA2-256)\(/proc/'+
              pid+rb'/exe\)= '+IM_SHA256.encode('ascii')+rb'\nCOLD_NATIVE_IM pid='+pid+rb' exe='+
              re.escape(executable)+rb' sha256='+IM_SHA256.encode('ascii')+rb'\nCOLD_EXECUTABLE=/usr/bin/im\.elf\n')
    if len(re.findall(actual, proof, re.M)) != 1:
        raise ValueError('Cold proof IM marker lacks actual proc executable hash readback')
    return proof


def cold_proof_binding(output, token, trace, proof):
    def bound(name, raw):
        return dict(path=str(output/name), bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest())
    return dict(schema='a7c2-retained-cold-proof-v1', nonce=token, guest_file=cold_proof_path(token),
        chunk_bytes=COLD_PROOF_CHUNK, source_console_snapshot=bound('transaction/source-console.log', trace),
        trace=bound('source-cold-trace.log', trace), proof=bound('source-cold-proof.txt', proof),
        collector=bound('source-cold-collector.log', trace+b'\n'+proof))


def save_bytes(path, raw):
    with os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600), 'wb') as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())


def retain_cold_proof(output, log, token):
    trace = log.read_bytes()
    save_bytes(output/'source-cold-trace.log', trace)
    proof = decode_cold_proof(trace, token)
    if not log.read_bytes().startswith(trace):
        raise ValueError('Source console is not append-only after cold proof snapshot')
    save_bytes(output/'source-cold-proof.txt', proof)
    collector = output/'source-cold-collector.log'
    save_bytes(collector, trace+b'\n'+proof)
    save(output/'source-cold-proof.json', cold_proof_binding(output, token, trace, proof))
    return collector


def diagnostic_script(token):
    proof = cold_proof_path(token)
    return f'''set -e
umask 077
set -C
proof={proof}
exec 3>"$proof"
{{
echo RETAINED_COLD_FILE nonce={token} file=$proof
echo COLD_KERNEL_CMDLINE_BEGIN
cat /proc/cmdline
echo COLD_KERNEL_CMDLINE_END
cat /proc/1/cmdline /proc/1/status /proc/1/mountinfo
if test ! -e /initrd/sbin/init; then absent_rc=0; else absent_rc=$?; fi
echo COLD_OLD_INITRD_PATH_ABSENT=$absent_rc
for p in /proc/[0-9]*; do
 e=$(busybox readlink "$p/exe" 2>/dev/null) || continue
 case "$e" in */im.elf|*/bootin-original|*/bootin.elf)
  image_sha=$(/usr/bin/openssl dgst -sha256 "$p/exe")
  echo COLD_PROCESS pid=${{p##*/}} exe=$e
  echo "$image_sha"
  case "$e" in /usr/bin/im.elf|/bin/im.elf)
   case "$image_sha" in *"= {IM_SHA256}")
    echo COLD_NATIVE_IM pid=${{p##*/}} exe=$e sha256={IM_SHA256}
    echo COLD_EXECUTABLE=/usr/bin/im.elf;;
   esac;;
  esac
  case "$image_sha" in *"= {E['BOOTIN_SHA256']}") echo COLD_NATIVE_BOOTIN pid=${{p##*/}} sha256={E['BOOTIN_SHA256']};; esac
  if busybox grep -q /usr/lib/appFw.so "$p/maps"; then
   app_sha=$(/usr/bin/openssl dgst -sha256 /usr/lib/appFw.so)
   echo "$app_sha"
   case "$app_sha" in *"= {E['APPFW_SHA256']}") echo COLD_AP_MAP pid=${{p##*/}} sha256={E['APPFW_SHA256']};; esac
  fi
  cat "$p/cmdline" "$p/status" "$p/maps";;
 esac
done
echo RETAINED_COLD_FILE_END nonce={token} file=$proof
}} >&3
exec 3>&-
set -- $(busybox ls -l "$proof")
bytes=$5
bytes=$((bytes+0))
test "$bytes" -gt 0
test "$bytes" -le {COLD_PROOF_LIMIT}
before=$(/usr/bin/openssl dgst -sha256 "$proof")
before=${{before##* }}
echo RETAINED_COLD_META nonce={token} file={proof} bytes=$bytes sha256=$before
/usr/bin/openssl enc -base64 -in "$proof" | {{
 offset=0
 chunk=
 while IFS= read -r line; do
  chunk=$chunk$line
  if test "${{#chunk}}" -eq 256; then
   echo RETAINED_COLD_CHUNK nonce={token} offset=$offset data=$chunk
   offset=$((offset+{COLD_PROOF_CHUNK}))
   chunk=
  fi
 done
 if test -n "$chunk"; then
  echo RETAINED_COLD_CHUNK nonce={token} offset=$offset data=$chunk
 fi
}}
after=$(/usr/bin/openssl dgst -sha256 "$proof")
after=${{after##* }}
test "$before" = "$after"
echo RETAINED_COLD_END nonce={token} file={proof} bytes=$bytes sha256=$after
echo RETAINED_DONE_diag={token}
'''


MENU = '''set -e
/simulation/inject-key 0x807a0020 0x92840747 0x1ab 0 1 0 1
busybox sleep 0.05
/simulation/inject-key 0x807a0020 0x92840747 0x1ab 0 0 0 1
busybox sleep 1
'''


def metadata(instance, tx=None):
    """Read-only 0600 preflight, repeated under the executing transaction's lease."""
    names = sorted({'geometry.json', 'instance.json', 'persistent-geometry.bin',
                    *[p.name for p in instance.glob('*.json')]})
    rows = {}
    try:
        with ExitStack() as stack:
            for name in names:
                if tx is not None:
                    rows[name] = tx._read_file(stack, instance/name)[1]
                else:
                    fd = DS['DISK']['SECURE_OPEN'](instance/name)
                    stack.callback(os.close, fd)
                    before = DS['_record'](fd)
                    if before['size'] > 1024**2:
                        raise ValueError('Metadata exceeds read budget')
                    raw = os.pread(fd, before['size']+1, 0)
                    if len(raw) != before['size'] or before != DS['_record'](fd):
                        raise ValueError('Metadata changed during preflight')
                    rows[name] = dict(before, sha256=hashlib.sha256(raw).hexdigest())
    except ValueError as error:
        raise ValueError('Private metadata must be owned/single-link/mode 0600; repair and read back '
                         'only within your own independent instance lease. No chmod performed: '+str(instance/name)+': '+str(error)) from error
    return rows


def snapshot(qmp, directory, phase):
    paths = [directory/(phase+suffix) for suffix in ('.ppm', '-scanout-pool.bin')]
    if any(path.exists() for path in paths):
        raise ValueError('Snapshot output already exists')
    qmp('screendump', {'filename': '/out/'+paths[0].name})
    qmp('pmemsave', {'val': SCAN_BASE, 'size': SCAN_BYTES, 'filename': '/out/'+paths[1].name})
    for path in paths:
        with os.fdopen(DS['DISK']['SECURE_OPEN'](path), 'rb') as f:
            DS['_record'](f.fileno())
    return pixel_review(paths[0].read_bytes(), paths[1].read_bytes())


def close_source(tx, launch, owner, qmp):
    """Constructor-failure path: a socket name alone never authorizes quit."""
    connection = stream = None
    try:
        if owner.poll() is None:
            if qmp is None:
                connection, stream, _ = E['qmp_connect'](launch['qmp_socket'], timeout=15)
                qmp = C['R']['FDQMP'](connection, stream)
            with paused(qmp, tx._output/'close-source-quiesce.jsonl', tx=tx, owner=owner):
                C['_owned_identity'](tx, launch, owner, qmp)
        return C['_quit'](owner, qmp)
    finally:
        if stream is not None:
            stream.close()
            connection.close()


def run(runtime_analysis, cold_manifest, output, *, combo_manifest=L['UPSTREAM_COMBO'],
        origin_qemu_build=L['DEFAULT_ORIGIN'], source_timeout=180, transfer_timeout=360):
    for value in (source_timeout, transfer_timeout):
        if type(value) not in (int, float) or not 0 < value <= 3600:
            raise ValueError('Timeout must be finite and within (0, 3600] seconds')
    output = Path(os.path.abspath(output))
    if output.exists() or output.is_symlink():
        raise ValueError('Output must be a new explicit private directory')
    COLD['plain'](output.parent, directory=True)
    cold_row = COLD['binding'](cold_manifest, 'retained-test-cold-manifest')
    cold = json.loads(Path(cold_row['path']).read_text())
    if cold.get('source') not in DS['SOURCES']:
        raise ValueError('Unknown cold instance source class')
    instance = COLD['plain'](cold['instance'], directory=True)
    for source in (instance, Path(runtime_analysis).resolve()):
        if output.is_relative_to(source) or source.is_relative_to(output):
            raise ValueError('Output overlaps source runtime or instance')
    output.mkdir(mode=0o700)
    old_umask = os.umask(0o077)
    phase = 'preflight'
    try:
        with P['DISK']['lease'](instance) as leased:
            directory_fd = DS['DISK']['SECURE_OPEN'](instance, directory=True)
            try:
                DS['_directory'](directory_fd)
            finally:
                os.close(directory_fd)
            private = metadata(instance)
            P['identical']('instance source class', cold['source'], leased['state']['source_class'])
            P['verify_firmware'](leased, cold)
            originals = P['ext2_identities'](P['part'](leased, 'nflasha15'), ['/bin/bootin.elf', '/lib/appFw.so'])
            for name, expected in (('/bin/bootin.elf', E['BOOTIN_SHA256']), ('/lib/appFw.so', E['APPFW_SHA256'])):
                P['identical']('stock disk '+name, expected, originals[name]['sha256'])
        save(output/'preflight.json', dict(metadata=private, original_elfs=originals,
            cold_manifest=cold_row, source_bindings=SOURCE_BINDINGS))
        COLD['recheck']([cold_row]+SOURCE_BINDINGS)
        launch = L['prepare_launch'](runtime_analysis, cold_manifest, output/'launch',
            upstream_host=True, combo_manifest=combo_manifest, origin_qemu_build=origin_qemu_build)
        transaction = output/'transaction'
        transaction.mkdir(mode=0o700)
        with DS['transaction'](instance, transaction) as tx:
            execution = owner = qmp = connection = stream = None
            try:
                phase = 'source'
                P['identical']('same prepared instance', str(instance), launch['instance'])
                P['identical']('bound source class', cold['source'], launch['disk_source_class'])
                P['identical']('metadata unchanged before Popen', private, metadata(instance, tx))
                P['verify_firmware'](tx._leased, launch)
                COLD['recheck']([cold_row]+SOURCE_BINDINGS+launch['template_inputs']+launch['launch_inputs'])
                st = os.fstat(tx.fd)
                env = {**launch['env'], 'PERSISTENT_INSTANCE': str(tx._leased['path']),
                       'PERSISTENT_DISK_FD': str(tx.fd), 'PERSISTENT_DISK_DEV': str(st.st_dev),
                       'PERSISTENT_DISK_INO': str(st.st_ino)}
                log = transaction/'source-console.log'
                with os.fdopen(os.open(log, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600), 'wb', buffering=0) as out:
                    owner = subprocess.Popen(launch['command'], env=env, stdin=subprocess.PIPE,
                        stdout=out, stderr=subprocess.STDOUT, pass_fds=tx.pass_fds)
                    tx.children.append(owner)
                    save(output/'source-owner-start.json', dict(pid=owner.pid, command=launch['command']))
                    wait_for(owner, log, lambda s: 'OBS OSD_HEADLESS_PERSISTED ' in s and bool(re.search(
                        r'^OBS CREATE_SCREEN_ARGS [^\n]* id=0 count=565 ', s, re.M)), source_timeout)
                    connection, stream, _ = E['qmp_connect'](launch['qmp_socket'], timeout=15)
                    qmp = C['R']['FDQMP'](connection, stream)
                    token = secrets.token_hex(16)
                    source_run, target_run = 'retained-source-'+token, 'retained-target-'+token
                    shell(owner, log, diagnostic_script(token), 'diag', token)
                    collector = retain_cold_proof(output, log, token)
                    receipt = E['new_receipt']('original-init-cold', bindings=dict(run=source_run,
                        source_class=cold['source']), kernel_cmdline=launch['cmdline'])
                    coverage = E['collect'](collector, receipt)
                    save(output/'source-cold-evidence.json', coverage)
                    if not coverage['ap_verified'] or not coverage['cold_guest_chain_verified']:
                        raise ValueError('Original cold guest chain and live bootin/AP SHA, observer and LCD not verified')
                    with paused(qmp, output/'source-constructor-quiesce.jsonl', tx=tx, owner=owner, resume=True):
                        execution = C['CameraExecution'](tx, launch, owner, qmp, source_run=source_run, generation=0)
                    states = dict(source=parse_state(shell(owner, log,
                        'busybox sleep 1\n'+state_script('source', token, True), 'source', token), 'source'))
                    frame_review(states['source'])
                    if states['source']['canary'] != token:
                        raise ValueError('New source canary differs')
                    save(output/'source-state.json', states['source'])
                    frames = dict(source=snapshot(qmp, Path(launch['dtb']).parent, 'source'))
                    phase = 'capture'
                    marker = 'A7C2_RETAINED_GUEST_SYNC nonce='+tx.guest_sync_nonce+' sync_rc=0'
                    command = "/bin/busybox sync && echo '"+marker+"'"
                    E['write_console'](owner.stdin, (command+'\n').encode('ascii'))
                    wait_for(owner, log, lambda s: s.splitlines().count(marker) == 1, 30)
                    evidence = transaction/'guest-sync.console'
                    with os.fdopen(os.open(evidence, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600), 'wb') as f:
                        f.write(log.read_bytes())
                    with paused(qmp, output/'source-capture-quiesce.jsonl', tx=tx, owner=owner):
                        captured = execution.capture(dict(schema='a7c2-retained-guest-sync-v1', kind='guest-console-sync',
                            run=source_run, nonce=tx.guest_sync_nonce, owner_pid=owner.pid,
                            peer_pid=execution.identity['peer']['pid'], path=str(evidence), command=command), timeout=transfer_timeout)
                    save(output/'capture-result.json', captured)
                    phase = 'restore'
                    target, target_qmp, restored = execution.restore(target_run=target_run, timeout=transfer_timeout)
                    save(output/'restore-paused-result.json', restored)
                    execution.continue_target()
                    target_log = transaction/'target/console.log'
                    phase = 'content'
                    states['restored'] = parse_state(shell(target, target_log,
                        'busybox sleep 1\n'+state_script('restored', token), 'restored', token), 'restored')
                    save(output/'restored-state.json', states['restored'])
                    frames['restored'] = snapshot(target_qmp, transaction/'target', 'restored')
                    for label in ('menu', 'shooting'):
                        observed = shell(target, target_log, MENU+state_script(label, token), label, token)
                        states[label] = parse_state(observed, label)
                        save(output/(label+'-state.json'), states[label])
                        save(output/(label+'-input.json'), review_input(observed, label))
                        frames[label] = snapshot(target_qmp, transaction/'target', label)
                    save(output/'frame-state-observations.json', states)
                    save(output/'frame-pixels.json', frames)
                    headers = review_states(states, frames, token)
                    if re.search(r'^(?:Linux version |COLD_BEFORE_ORIGINAL_INIT)', console(target_log), re.M):
                        raise ValueError('Target unexpectedly executed a new cold boot')
                    result = dict(schema='a7c2-retained-camera-test-v1', status='passed', actual_content_verified=True,
                        scope='fixed upstream-host original AP QEMU RAM roundtrip', profile=launch['profile'],
                        runtime_analysis=str(Path(runtime_analysis).resolve()), cold_manifest=cold_row,
                        qemu_sha256=launch['qemu_sha256'], source_tree_sha256=launch['combo_binding']['source_tree_sha256'],
                        metadata=private, source_bindings=SOURCE_BINDINGS, headers=headers, frames=frames,
                        source_run=source_run, target_run=target_run,
                        same_kernel_ram_canary_ap_viewer_pid_and_flocks=True, normal_input_received_edges=4,
                        normal_input_free_enter_edges=4, free_return_code_verified=False,
                        whole_device_audit_scope='declared fixed source-v4 topology only', full_device_audit_complete=False,
                        state_and_qmp_images_zero_race_coherent=False, display_under_one_second_verified=False,
                        full_boot_verified=False, sony_wbi_verified=False, hardware_ram_hotboot_verified=False,
                        capture_verified=False, ui_hot_enabled=False, vm_signals_sent=[])
            except BaseException as error:
                save(output/'failure.json', dict(phase=phase, error=type(error).__name__+': '+str(error),
                    actual_content_verified=False, capture_verified=False, vm_signals_sent=[]))
                raise
            finally:
                try:
                    closed = execution.close() if execution is not None else (
                        close_source(tx, launch, owner, qmp) if owner is not None else None)
                    save(output/'normal-close.json', closed)
                except BaseException as error:
                    save(output/'owner-retained.json', dict(error=type(error).__name__+': '+str(error),
                        live_owner_pids=[child.pid for child in tx.children if child.poll() is None],
                        lease_retained_until_owner_exit=True, vm_signals_sent=[], actual_content_verified=False))
                    raise
                finally:
                    if all(child.poll() is not None for child in tx.children):
                        if stream is not None:
                            stream.close()
                            connection.close()
                        if owner is not None:
                            owner.stdin.close()
        result['owners_closed'] = True
        save(output/'result.json', result)
        return result
    except BaseException as error:
        if not (output/'failure.json').exists():
            save(output/'failure.json', dict(phase=phase, error=type(error).__name__+': '+str(error),
                actual_content_verified=False, capture_verified=False, vm_signals_sent=[]))
        raise
    finally:
        os.umask(old_umask)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--runtime-analysis', type=Path, required=True)
    parser.add_argument('--cold-manifest', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True, help='new private directory; existing paths refused')
    parser.add_argument('--combo-manifest', type=Path, required=True, help='existing verified upstream-host combo; never builds')
    parser.add_argument('--origin-qemu-build', type=Path, default=L['DEFAULT_ORIGIN'])
    args = parser.parse_args()
    result = run(args.runtime_analysis, args.cold_manifest, args.output,
                 combo_manifest=args.combo_manifest, origin_qemu_build=args.origin_qemu_build)
    print(json.dumps(dict(status=result['status'], actual_content_verified=result['actual_content_verified'],
                         capture_verified=result['capture_verified'], output=str(args.output))))


if __name__ == '__main__':
    main()
