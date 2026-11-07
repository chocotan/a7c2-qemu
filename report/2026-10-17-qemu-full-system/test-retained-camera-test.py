"""Host orchestration/negative guards only. No VM or original-AP execution claim."""
import base64
import hashlib
from contextlib import contextmanager
import inspect
import io
import json
import os
from pathlib import Path
import runpy
import shlex
import shutil
import stat
import struct
from types import SimpleNamespace

import pytest

HERE = Path(__file__).resolve().parent
API = runpy.run_path(str(HERE/'retained-camera-test.py'))
G = API['run'].__globals__
C, E, P, DS = API['C'], API['E'], API['P'], API['DS']
# Original v3 128-byte HOSDAP02 header; no token, PID, boot_id or private settings.
HEADER = base64.b64decode('SE9TREFQMDKbAAAAAAAAAAIEAACAAgAA4AEAAAEAAAAAQXs6BAAAAAsmmUIlXLxKAGAJAGJhAAAFEAAAAAAAAAMQAAAAAAAAAgQAAAEAAAAAAAAAgALgAQAAAACAAuABAAAAAAIQAAAAAAAABRAAAAUQAAAAAAAAfwAAAAAAAAA=')
SEQUENCES = dict(source=(155, 127), restored=(314, 312), menu=(397, 373), shooting=(516, 475))


def cold_proof_bytes(token='a'*32, cmdline='original', diagnostic=b''):
    path = API['cold_proof_path'](token)
    return (f'RETAINED_COLD_FILE nonce={token} file={path}\n'
            f'COLD_KERNEL_CMDLINE_BEGIN\n{cmdline}\nCOLD_KERNEL_CMDLINE_END\n'
            'COLD_PROCESS pid=621 exe=/usr/bin/im.elf\n'
            f'SHA256(/proc/621/exe)= {API["IM_SHA256"]}\n'
            f'COLD_NATIVE_IM pid=621 exe=/usr/bin/im.elf sha256={API["IM_SHA256"]}\n'
            'COLD_EXECUTABLE=/usr/bin/im.elf\n').encode() + diagnostic + (
            f'RETAINED_COLD_FILE_END nonce={token} file={path}\n').encode()


def cold_transfer(proof=None, token='a'*32):
    proof = cold_proof_bytes(token) if proof is None else proof
    identity = f'nonce={token} file={API["cold_proof_path"](token)}'
    meta = f'{identity} bytes={len(proof)} sha256={hashlib.sha256(proof).hexdigest()}\n'
    rows = ['RETAINED_COLD_META '+meta]
    for offset in range(0, len(proof), API['COLD_PROOF_CHUNK']):
        payload = base64.b64encode(proof[offset:offset+API['COLD_PROOF_CHUNK']]).decode('ascii')
        rows.append(f'RETAINED_COLD_CHUNK nonce={token} offset={offset} data={payload}\n')
    return (''.join(rows)+'RETAINED_COLD_END '+meta+f'RETAINED_DONE_diag={token}\n').encode('ascii')


@pytest.mark.parametrize('size', [1, 191, 192, 193, 90433])
def test_generated_transport_real_openssl_once_at_chunk_boundaries(tmp_path, record_property, size):
    """Host shell/real OpenSSL only; never run the guest /proc diagnostic or write /dev."""
    token = 'a'*32
    if size == 90433:
        cmdline = 'root=/dev/ram0 ' + 'x'*1637
        base = cold_proof_bytes(token, cmdline)
        proof = cold_proof_bytes(token, cmdline, b'X'*(size-len(base)-1)+b'\n')
    else:
        proof = bytes(index % 256 for index in range(size))
    assert len(proof) == size
    path = tmp_path/'proof.input'
    path.write_bytes(proof)
    busybox = shutil.which('busybox')
    shell = [busybox, 'ash'] if busybox else ['/bin/sh']
    # Only the host without BusyBox needs the existing ls command spelled through a function.
    compat = '' if busybox else 'busybox() { "$@"; }\n'
    fragment = API['diagnostic_script'](token).split('exec 3>&-\n', 1)[1]
    script = compat+'proof='+shlex.quote(str(path))+'\n'+fragment
    completed = API['subprocess'].run(shell+['-ex'], input=script, text=True, capture_output=True, timeout=15)
    record_property('host_transport_shell', ' '.join(shell))
    record_property('host_transport_bytes', size)
    assert completed.returncode == 0, completed.stderr
    # -x observes commands actually executed, including the pipeline child, rather than counting source text.
    assert completed.stderr.count('/usr/bin/openssl enc -base64 -in ') == 1
    assert completed.stderr.count('/usr/bin/openssl dgst -sha256 ') == 2
    record_property('executed_openssl_base64', 1)
    wire = completed.stdout.encode('ascii')
    assert wire == cold_transfer(proof, token)
    assert max(map(len, wire.splitlines())) <= 512
    chunks = [line.split(b' data=')[1] for line in wire.splitlines() if line.startswith(b'RETAINED_COLD_CHUNK ')]
    assert b''.join(base64.b64decode(chunk, validate=True) for chunk in chunks) == proof
    assert len(chunks) == (size+191)//192
    if size == 90433:
        assert len(chunks) == 472
        assert API['decode_cold_proof'](wire, token) == proof
        missing = wire.splitlines(keepends=True)
        del missing[3]
        for damaged in (b''.join(missing), wire.replace(hashlib.sha256(proof).hexdigest().encode(), b'0'*64)):
            with pytest.raises(ValueError, match='[Cc]old proof'):
                API['decode_cold_proof'](damaged, token)
    else:
        with pytest.raises(ValueError, match='decoded file identity'):
            API['decode_cold_proof'](wire, token)


def test_cold_proof_complete_long_cmdline_and_separate_console_noise():
    cmdline = 'root=/dev/ram0 ' + 'x'*1637
    assert len(cmdline) == 1652
    proof = cold_proof_bytes(cmdline=cmdline)
    wire = cold_transfer(proof).replace(b'\n', b'\r\n')
    # Whole unrelated trace lines stay raw; they never become decoded proof bytes.
    wire = b'echo RETAINED_COLD_META nonce=$token\r\n'+wire.replace(
        b'RETAINED_COLD_CHUNK', b'[kernel] asynchronous noise\r\nRETAINED_COLD_CHUNK')
    assert API['decode_cold_proof'](wire, 'a'*32) == proof
    assert max(map(len, wire.splitlines())) <= 512


@pytest.mark.parametrize('damage', ['hash', 'after-hash', 'base64', 'base64-padding', 'offset', 'duplicate',
                                  'reorder', 'nonce', 'meta-nonce', 'end-nonce', 'file', 'length',
                                  'truncated', 'oversize', 'noise', 'embedded-cr', 'unknown-record'])
def test_cold_proof_transport_corruption_is_rejected(damage):
    wire = cold_transfer()
    lines = wire.splitlines(keepends=True)
    if damage == 'hash':
        wire = wire.replace(hashlib.sha256(cold_proof_bytes()).hexdigest().encode(), b'0'*64)
    elif damage == 'after-hash':
        lines[-2] = lines[-2].replace(b'sha256=', b'sha256=0')
        wire = b''.join(lines)
    elif damage in ('base64', 'base64-padding', 'noise', 'embedded-cr'):
        prefix, payload = lines[1].split(b' data=')
        payload = {'base64': b'!', 'base64-padding': b'A===',
                   'noise': payload.rstrip()+b'[kernel] log', 'embedded-cr': payload.rstrip()+b'\rX'}[damage]
        lines[1] = prefix+b' data='+payload.rstrip(b'\n')+b'\n'
        wire = b''.join(lines)
    elif damage == 'offset':
        wire = wire.replace(b'offset=0 ', b'offset=1 ', 1)
    elif damage == 'duplicate':
        wire = b''.join(lines[:2]+[lines[1]]+lines[2:])
    elif damage == 'reorder':
        lines[1], lines[2] = lines[2], lines[1]
        wire = b''.join(lines)
    elif damage in ('nonce', 'meta-nonce', 'end-nonce'):
        index = {'nonce': 1, 'meta-nonce': 0, 'end-nonce': -2}[damage]
        lines[index] = lines[index].replace(b'a'*32, b'b'*32)
        wire = b''.join(lines)
    elif damage == 'file':
        wire = wire.replace(b'.proof bytes=', b'Xproof bytes=')
    elif damage in ('length', 'oversize'):
        size = str(len(cold_proof_bytes())).encode()
        replacement = str(len(cold_proof_bytes())+1 if damage == 'length' else API['COLD_PROOF_LIMIT']+1).encode()
        wire = wire.replace(b'bytes='+size+b' ', b'bytes='+replacement+b' ')
    elif damage == 'truncated':
        wire = b''.join(lines[:-2])
    else:
        wire += b'RETAINED_COLD_UNEXPECTED nonce='+b'a'*32+b'\n'
    with pytest.raises(ValueError, match='[Cc]old proof'):
        API['decode_cold_proof'](wire, 'a'*32)


@pytest.mark.parametrize('damage', ['file-token', 'im-hash', 'im-pid', 'im-exe', 'im-readback', 'im-marker'])
def test_even_rehashed_proof_requires_guest_file_and_actual_im_identity(damage):
    proof = cold_proof_bytes()
    if damage == 'file-token':
        proof = proof.replace(b'RETAINED_COLD_FILE nonce='+b'a'*32, b'RETAINED_COLD_FILE nonce='+b'b'*32)
    elif damage == 'im-hash':
        proof = proof.replace(API['IM_SHA256'].encode(), b'0'*64)
    elif damage == 'im-pid':
        proof = proof.replace(b'COLD_PROCESS pid=621', b'COLD_PROCESS pid=622')
    elif damage == 'im-exe':
        proof = proof.replace(b'exe=/usr/bin/im.elf', b'exe=/usr/bin/bootin.elf')
    elif damage == 'im-readback':
        proof = proof.replace(b'SHA256(/proc/621/exe)= ', b'SHA256(/usr/bin/im.elf)= ')
    else:
        proof = proof.replace(b'COLD_NATIVE_IM ', b'NOT_ACTUAL_IM ')
    with pytest.raises(ValueError, match='[Cc]old proof'):
        API['decode_cold_proof'](cold_transfer(proof), 'a'*32)


def test_cold_proof_trace_budget_and_script_nonce(monkeypatch):
    wire = cold_transfer()
    monkeypatch.setitem(G, 'COLD_TRACE_LIMIT', len(wire)-1)
    with pytest.raises(ValueError, match='budget'):
        API['decode_cold_proof'](wire, 'a'*32)
    for token in ('a'*31, 'A'*32, '../'+'a'*32, 'a'*32+';echo'):
        with pytest.raises(ValueError, match='nonce'):
            API['diagnostic_script'](token)


def test_cold_proof_private_exclusive_snapshot_and_no_raw_rewrite(tmp_path):
    output = tmp_path/'retained'
    (output/'transaction').mkdir(parents=True)
    log = output/'transaction/source-console.log'
    trace = b'original trace\n'+cold_transfer()
    log.write_bytes(trace)
    collector = API['retain_cold_proof'](output, log, 'a'*32)
    assert log.read_bytes() == trace
    proof = cold_proof_bytes()
    assert collector.read_bytes() == trace+b'\n'+proof
    assert json.loads((output/'source-cold-proof.json').read_text()) == API['cold_proof_binding'](output, 'a'*32, trace, proof)
    for name in ('source-cold-trace.log', 'source-cold-proof.txt', 'source-cold-proof.json', 'source-cold-collector.log'):
        assert stat.S_IMODE((output/name).stat().st_mode) == 0o600
    with log.open('ab') as stream:
        stream.write(b'later original trace\n')
    with pytest.raises(FileExistsError):
        API['retain_cold_proof'](output, log, 'a'*32)
    assert (output/'source-cold-trace.log').read_bytes() == trace
    assert collector.read_bytes() == trace+b'\n'+proof


def test_cold_proof_decode_failure_keeps_original_trace_without_collector(tmp_path):
    (tmp_path/'transaction').mkdir()
    log = tmp_path/'transaction/source-console.log'
    raw = cold_transfer().replace(b'offset=0 ', b'offset=1 ', 1)
    log.write_bytes(raw)
    with pytest.raises(ValueError, match='offset'):
        API['retain_cold_proof'](tmp_path, log, 'a'*32)
    assert log.read_bytes() == (tmp_path/'source-cold-trace.log').read_bytes() == raw
    assert not (tmp_path/'source-cold-proof.txt').exists()
    assert not (tmp_path/'source-cold-collector.log').exists()
    assert not (tmp_path/'source-cold-proof.json').exists()


def state_text(phase, token='a'*32):
    seq, pixels = SEQUENCES[phase]
    header = bytearray(HEADER)
    struct.pack_into('<Q', header, 8, seq)
    struct.pack_into('<Q', header, 120, pixels)
    return f'''echo RETAINED_STATE_BEGIN={phase}
RETAINED_STATE_BEGIN={phase}
Uid: 0 0 0 0
Gid: 0 0 0 0
RETAINED_CANARY={token}
RETAINED_BOOT_ID=00000000-0000-0000-0000-000000000001
RETAINED_UPTIME=40.00 20.00
1: FLOCK  ADVISORY  WRITE 31 00:0e:111 0 EOF
2: FLOCK  ADVISORY  WRITE 32 00:0e:222 0 EOF
RETAINED_FRAME_HEADER={base64.b64encode(header).decode()}
RETAINED_VIEWER_STATUS_BEGIN
[36.61] [K]**UIPC ERROR** retained original noise
RAMFB_RETAINED reason=DMA is not screenshot proof errno=2 seq={seq} pixel_source={pixels} source_phys=0x43a7b4100 hash=fdb76222ac3171e6 scanout=0x41e100000
RETAINED_VIEWER_STATUS_END
SHA256(/dev/qemu-simulation/headless-osd.claim)= {'0'*64}
RETAINED_APP_PID=31
RETAINED_VIEWER_PID=32
RETAINED_STATE_END={phase}
'''


def input_text(phase):
    screen, count = ('0x2c9', 46) if phase == 'menu' else ('0', 565)
    result = ''
    for status, prev, message in ((1, 0, '0x100'), (0, 1, '0x200')):
        fields = f'tid=7 queue=0x5503e0 message={message} code=0x1ab status={status} prev={prev}'
        result += (f'INJECT_KEY_SEND queue=0x807a0020 src=0x92840747 key_code=0x1ab sub=0 '
                   f'status={"0x1" if status else "0"} ex=0 from=0x1 result=0\n'
                   f'OBS FULL_INPUT_RECEIVE {fields} repeat=0 from=1 inh=0\n'
                   f'OBS FULL_INPUT_FREE_ENTER {fields}\n')
    return result+f'OBS CREATE_SCREEN_ARGS call=6 id={screen} count={count} orientation=0 this=0x111 kinds=[]\n'


def pixels(phase, *, mismatch=False):
    color = {'source': b'\x10\x20\x30', 'restored': b'\x10\x20\x30',
             'menu': b'\x40\x50\x60', 'shooting': b'\x70\x80\x90'}[phase]
    ppm = b'P6\n640 480\n255\n'+color*(640*480)
    pool = bytearray(API['SCAN_BYTES'])
    pool[:640*480*4] = (color[::-1]+b'\0')*(640*480)
    struct.pack_into('>Q5I', pool, API['SCAN_BYTES']-0x1000+64,
                     API['SCAN_BASE'], 0x34325258, 0, 640, 480, 2560)
    if mismatch:
        pool[0] ^= 1
    return ppm, pool


def test_frozen_production_interfaces():
    signature = inspect.signature(C['CameraExecution'])
    assert tuple(signature.parameters) == ('tx', 'launch', 'owner', 'qmp', 'source_run', 'generation', 'device_audit')
    for name, parameters in {'capture': ('self', 'guest_sync_evidence', 'timeout'),
                             'restore': ('self', 'target_run', 'timeout'),
                             'continue_target': ('self',), 'close': ('self',)}.items():
        assert tuple(inspect.signature(getattr(C['CameraExecution'], name)).parameters) == parameters
    assert tuple(inspect.signature(API['run']).parameters) == (
        'runtime_analysis', 'cold_manifest', 'output', 'combo_manifest', 'origin_qemu_build',
        'source_timeout', 'transfer_timeout')


def test_exact_guest_sections_reject_echo_only_and_duplicates():
    state = API['parse_state'](state_text('source'), 'source')
    assert 'UIPC ERROR' in state['viewer_status']
    assert API['frame_review'](state)['seq'] == 155
    for text in (state_text('source').replace('\nRETAINED_STATE_BEGIN=source\n', '\n'),
                 state_text('source')+'RETAINED_STATE_END=source\n'):
        with pytest.raises(ValueError, match='exact guest section'):
            API['parse_state'](text, 'source')


@pytest.mark.parametrize('mutation', ['old-seq', 'old-pixels', 'viewer-old', 'boot', 'pid', 'flock', 'canary'])
def test_fresh_frames_and_retained_identity(mutation):
    states = {phase: API['parse_state'](state_text(phase), phase) for phase in SEQUENCES}
    frames = {phase: API['pixel_review'](*pixels(phase)) for phase in ('source', 'menu', 'shooting')}
    API['review_states'](states, frames, 'a'*32)
    target = states['restored']
    if mutation in ('old-seq', 'old-pixels'):
        raw = bytearray(base64.b64decode(target['frame_header_base64']))
        struct.pack_into('<Q', raw, 8 if mutation == 'old-seq' else 120, 155 if mutation == 'old-seq' else 127)
        target['frame_header_base64'] = base64.b64encode(raw).decode()
    elif mutation == 'viewer-old':
        target['viewer_status'] = states['source']['viewer_status']
    elif mutation == 'boot':
        target['boot_id'] = '00000000-0000-0000-0000-000000000002'
    elif mutation == 'pid':
        target['ap_pids'] = ['999']
    elif mutation == 'flock':
        target['flocks'] = []
    else:
        target['canary'] = 'b'*32
    with pytest.raises(ValueError):
        API['review_states'](states, frames, 'a'*32)


@pytest.mark.parametrize('offset,value,size', [(120, 0, 8), (120, 156, 8), (32, 0, 8), (52, 0, 4), (108, 0, 4)])
def test_original_frame_bounds(offset, value, size):
    state = API['parse_state'](state_text('source'), 'source')
    raw = bytearray(HEADER)
    raw[offset:offset+size] = value.to_bytes(size, 'little')
    state['frame_header_base64'] = base64.b64encode(raw).decode()
    with pytest.raises(ValueError, match='bounds'):
        API['frame_review'](state)


def test_scanout_mismatch_and_old_menu_pixels_fail():
    with pytest.raises(ValueError, match='BGRX'):
        API['pixel_review'](*pixels('menu', mismatch=True))
    ppm, pool = pixels('menu')
    struct.pack_into('>Q', pool, API['SCAN_BYTES']-0x1000+64, API['SCAN_BASE']+1)
    with pytest.raises(ValueError, match='configuration/bounds'):
        API['pixel_review'](ppm, pool)
    states = {phase: API['parse_state'](state_text(phase), phase) for phase in SEQUENCES}
    frames = {phase: API['pixel_review'](*pixels('source')) for phase in ('source', 'menu', 'shooting')}
    with pytest.raises(ValueError, match='different QMP pixels'):
        API['review_states'](states, frames, 'a'*32)


def test_original_receive_matches_free_enter_without_claiming_free_return():
    assert API['review_input'](input_text('menu'), 'menu')['free_return_code_verified'] is False
    for bad in (input_text('menu').replace('FREE_ENTER tid=7', 'FREE_ENTER tid=8', 1),
                input_text('menu').replace('result=0', 'result=1', 1),
                input_text('menu').replace('id=0x2c9', 'id=0x309')):
        with pytest.raises(ValueError):
            API['review_input'](bad, 'menu')


@pytest.mark.parametrize('phase', ['menu', 'shooting'])
def test_busybox_prompt_before_input_record_preserves_strict_message_pairing(phase):
    text = input_text(phase)
    for kind in ('FULL_INPUT_RECEIVE', 'FULL_INPUT_FREE_ENTER', 'CREATE_SCREEN_ARGS'):
        prefixed = text.replace('OBS '+kind+' ', '/ # OBS '+kind+' ', 1)
        assert API['review_input'](prefixed, phase) == API['review_input'](text, phase)
        for damaged in (prefixed.replace('/ # OBS ', 'untrusted OBS ', 1),
                        prefixed.replace('FREE_ENTER tid=7', 'FREE_ENTER tid=8', 1),
                        prefixed.replace('FREE_ENTER', 'NOT_FREE', 1)):
            with pytest.raises(ValueError):
                API['review_input'](damaged, phase)


def test_guest_script_ascii_budget_and_delimiter():
    for label in (*SEQUENCES, 'diag'):
        script = API['diagnostic_script']('a'*32) if label == 'diag' else API['MENU']+API['state_script'](label, 'a'*32, label == 'source')
        envelope = E['diagnostic_envelope'](script, 'TEST_SCRIPT')
        assert envelope.encode('ascii') and max(map(len, envelope.splitlines())) <= 512
        checked = API['subprocess'].run(['/bin/sh', '-n'], input=envelope, text=True, capture_output=True)
        assert checked.returncode == 0, checked.stderr
    diagnostic = API['diagnostic_script']('a'*32)
    assert 'umask 077\nset -C\nproof=/dev/qemu-simulation/' in diagnostic
    assert 'exec 3>"$proof"' in diagnostic and 'test ! -e /initrd/sbin/init' in diagnostic
    assert 'openssl dgst -sha256 "$p/exe"' in diagnostic
    assert 'test "$before" = "$after"' in diagnostic
    assert 'busybox sleep 0.05\n' in API['MENU']
    with pytest.raises(ValueError, match='delimiter'):
        E['diagnostic_envelope']('TEST_SCRIPT\necho no', 'TEST_SCRIPT')


class ActiveDiskQMP:
    """Host-only QMP: a running CPU changes the real file stamp between FD/path reads."""
    def __init__(self, disk, fd, events):
        self.disk, self.fd, self.events = disk, fd, events
        self.running = True
        self.samples = []

    def check_identity(self):
        before = DS['_record'](self.fd)
        if self.running:
            info = os.fstat(self.fd)
            os.utime(self.disk, ns=(info.st_atime_ns, info.st_mtime_ns+1_000_000))
        opened = DS['DISK']['SECURE_OPEN'](self.disk)
        try:
            after = DS['_record'](opened)
        finally:
            os.close(opened)
        self.samples.append(dict(running=self.running, before=before, after=after))
        if before != after:
            raise ValueError('Disk FD/path identity stamp drift')
        return dict(host_only=True)

    def __call__(self, command, arguments=None):
        self.events.append(command)
        if command == 'query-status':
            return dict(status='running' if self.running else 'paused', running=self.running)
        if command == 'stop':
            self.running = False
            return {}
        if command == 'cont':
            self.running = True
            return {}
        raise AssertionError(command)


class Owner:
    def __init__(self, pid):
        self.pid, self.returncode, self.stdin = pid, None, io.BytesIO()
    def poll(self):
        return self.returncode
    def wait(self, timeout=None):
        assert self.returncode is not None, 'Host test never waits for a live owner'
        return self.returncode


@pytest.fixture(params=['direct', 'descendant'])
def owned_peer(tmp_path, request):
    """Real same-UID Popen and connected Unix peer; no VM or QMP server."""
    import socket
    import subprocess
    import sys
    address = str(tmp_path/'peer.sock')
    child = 'import socket,sys; s=socket.socket(socket.AF_UNIX); s.connect(sys.argv[1]); s.recv(1); s.close()'
    if request.param == 'descendant':
        child = 'import subprocess,sys; subprocess.run([sys.executable,"-c",'+repr(child)+',sys.argv[1]],check=True)'
    with socket.socket(socket.AF_UNIX) as listener:
        listener.settimeout(5)
        listener.bind(address)
        listener.listen(1)
        owner = subprocess.Popen([sys.executable, '-c', child, address])
        connection = None
        try:
            connection, _ = listener.accept()
            tx = SimpleNamespace(children=[owner])
            qmp = ActiveDiskQMP(tmp_path/'unused', -1, [])
            qmp.sock = connection
            yield SimpleNamespace(tx=tx, owner=owner, qmp=qmp, sock=connection)
        finally:
            if connection is not None:
                connection.close()
            assert owner.wait(timeout=5) == 0


@pytest.fixture
def host(tmp_path, monkeypatch):
    """Small fake transport/owners; real controller, parsing and file permissions."""
    instance, runtime = tmp_path/'instance', tmp_path/'runtime/analysis'
    instance.mkdir(mode=0o700)
    runtime.mkdir(parents=True)
    for name in ('geometry.json', 'instance.json', 'persistent-geometry.bin', 'camera.emmc'):
        (instance/name).write_text('{}')
        (instance/name).chmod(0o600)
    cold = tmp_path/'cold.json'
    cold.write_text(json.dumps(dict(source='official-bodydata-derived', instance=str(instance))))
    fd = os.open(instance/'camera.emmc', os.O_RDWR)
    leased = dict(path=instance, fd=fd, state=dict(source_class='official-bodydata-derived'))
    events, owners = [], []
    failure = SimpleNamespace(start=False, ap=False, cold=False, proof=False, target_boot=False, mismatch=False,
                              construct=False, capture=False)
    output = tmp_path/'private-run'
    closing = []

    @contextmanager
    def lease(path):
        assert path == instance
        yield leased

    class Tx:
        _leased = leased
        _output = output/'transaction'
        guest_sync_nonce = 'f'*32
        pass_fds = (fd,)
        def __init__(self):
            self.fd, self.children = fd, []
        def _read_file(self, stack, path):
            opened = DS['DISK']['SECURE_OPEN'](path)
            stack.callback(os.close, opened)
            raw = path.read_bytes()
            return raw, dict(DS['_record'](opened), sha256=__import__('hashlib').sha256(raw).hexdigest()), opened
    tx = Tx()

    @contextmanager
    def transaction(path, directory):
        events.append('lease-enter')
        yield tx
        assert all(child.poll() == 0 for child in tx.children)
        events.append('lease-exit')

    class QMP(ActiveDiskQMP):
        def __init__(self, owner, directory):
            super().__init__(instance/'camera.emmc', fd, events)
            self.owner, self.directory = owner, directory
        def __call__(self, command, arguments=None):
            if command in ('query-status', 'stop', 'cont'):
                return super().__call__(command, arguments)
            events.append(command)
            if command == 'quit':
                self.owner.returncode = 0
                return {}
            assert command in ('screendump', 'pmemsave'), command
            name = Path(arguments['filename']).name
            phase = name.split('.')[0].split('-')[0]
            raw = pixels(phase, mismatch=failure.mismatch)[0 if command == 'screendump' else 1]
            with (self.directory/name).open('xb') as f:
                f.write(raw)
            (self.directory/name).chmod(0o600)
            return {}

    source_qmp = None
    def prepare(runtime_arg, cold_arg, directory, *, upstream_host, combo_manifest, origin_qemu_build):
        assert upstream_host is True and runtime_arg == runtime and cold_arg == cold
        events.append('prepare')
        (directory/'run').mkdir(parents=True)
        (directory/'runtime/analysis').mkdir(parents=True)
        return dict(command=['existing-prepared-launcher'], env={}, instance=str(instance),
            runtime_analysis=str(directory/'runtime/analysis'),
            disk_source_class='official-bodydata-derived', dtb=str(directory/'run/virt.dtb'),
            qmp_socket=str(directory/'run/qmp.sock'), template_inputs=[], launch_inputs=[],
            cmdline='original', profile='fixed-host', qemu_sha256='0'*64,
            combo_binding=dict(source_tree_sha256='1'*64))

    def popen(command, *, env, stdin, stdout, stderr, pass_fds):
        nonlocal source_qmp
        assert command == ['existing-prepared-launcher'] and pass_fds == (fd,)
        assert env['PERSISTENT_DISK_FD'] == str(fd)
        owner = Owner(101)
        owners.append(owner)
        source_qmp = QMP(owner, output/'launch/run')
        events.append('source-popen')
        return owner

    class Execution:
        def __init__(self, transaction, launch, owner, qmp, *, source_run, generation):
            assert tx.children == [owner] and qmp.owner is owner and generation == 0
            assert 'collect' in events
            qmp.check_identity()
            events.append('construct')
            if failure.construct:
                raise RuntimeError('constructor failed while paused')
            self.qmp = qmp
            self.identity = dict(peer=dict(pid=102))
            self.source, self.source_run, self.target = owner, source_run, None
        def capture(self, evidence, *, timeout):
            assert evidence['run'] == self.source_run and evidence['nonce'] == tx.guest_sync_nonce
            assert evidence['owner_pid'] == self.source.pid and evidence['peer_pid'] == 102
            assert evidence['command'] in (output/'transaction/guest-sync.console').read_text()
            assert 'screendump' in events
            self.qmp.check_identity()
            events.append('capture')
            if failure.capture:
                raise RuntimeError('capture failed while paused')
            self.source.returncode = 0
            return dict(capture_verified=False)
        def restore(self, *, target_run, timeout):
            assert self.source.poll() == 0 and target_run != self.source_run
            events.append('restore')
            self.target = Owner(201)
            tx.children.append(self.target)
            owners.append(self.target)
            directory = output/'transaction/target'
            directory.mkdir(mode=0o700)
            (directory/'console.log').write_text('Linux version unexpected\n' if failure.target_boot else '')
            (directory/'console.log').chmod(0o600)
            return self.target, QMP(self.target, directory), {}
        def continue_target(self):
            events.append('cont')
        def close(self):
            closing.append(dict(source_alive=self.source.poll() is None, running=self.qmp.running))
            events.append('close')
            for owner in tx.children:
                owner.returncode = 0
            return dict(owners_closed=True)

    def collect(log, receipt):
        assert log == output/'source-cold-collector.log'
        assert log.read_bytes() == (output/'source-cold-trace.log').read_bytes()+b'\n'+(output/'source-cold-proof.txt').read_bytes()
        events.append('collect')
        return dict(ap_verified=not failure.ap, cold_guest_chain_verified=not failure.cold)
    def shell(owner, log, script, phase, token):
        assert owner in tx.children
        if owner.pid == 101:
            assert source_qmp.running, 'Never issue guest shell commands while paused'
        events.append(phase)
        if phase == 'diag':
            proof = cold_proof_bytes(token).replace(b'pid=621', b'pid=31').replace(b'/proc/621/', b'/proc/31/')
            wire = (f'COLD_EXPECTED_IM version={E["IM_VERSION"]} sha256={API["IM_SHA256"]}\n'
                    f'COLD_AP_MAP pid=31 sha256={E["APPFW_SHA256"]}\n'
                    'OBS OBSERVER_READY pid=31 base=0x7f12340000 mode=original\n').encode() + cold_transfer(proof, token)
            if failure.proof:
                wire = wire.replace(b'offset=0 ', b'offset=1 ', 1)
            with log.open('ab') as stream:
                stream.write(wire)
            return ''
        return (input_text(phase) if phase in ('menu', 'shooting') else '')+state_text(phase, token)
    def write_console(stream, raw):
        assert source_qmp.running, 'Guest sync must run before outer stop'
        events.append('guest-sync')
        assert raw.decode().startswith('/bin/busybox sync && echo ')
        with (output/'transaction/source-console.log').open('ab') as f:
            f.write(raw+raw.split(b"'")[1]+b'\n')
    def wait_for(owner, log, condition, seconds):
        assert owner in tx.children
        if failure.start:
            raise RuntimeError('source failed before AP')
        return API['console'](log)

    monkeypatch.setitem(P['DISK'], 'lease', lease)
    monkeypatch.setitem(P, 'verify_firmware', lambda *args: None)
    monkeypatch.setitem(P, 'part', lambda *args: None)
    monkeypatch.setitem(P, 'ext2_identities', lambda *args: {
        '/bin/bootin.elf': dict(sha256=E['BOOTIN_SHA256']), '/lib/appFw.so': dict(sha256=E['APPFW_SHA256'])})
    monkeypatch.setitem(API['L'], 'prepare_launch', prepare)
    monkeypatch.setitem(DS, 'transaction', transaction)
    monkeypatch.setattr(API['subprocess'], 'Popen', popen)
    monkeypatch.setitem(C, 'CameraExecution', Execution)
    def authenticate_owner(transaction, owner, qmp):
        assert transaction is tx and any(child is owner for child in tx.children) and owner.poll() is None
        assert qmp.owner is owner
        events.append('preauth')
    monkeypatch.setitem(G, 'authenticate_owner', authenticate_owner)
    def owned_identity(tx, launch, owner, qmp):
        if qmp.owner is not owner:
            raise ValueError('QMP is not owned')
        events.append('full-owned-identity')
        return qmp.check_identity()
    monkeypatch.setitem(C, '_owned_identity', owned_identity)
    monkeypatch.setitem(C['R'], 'FDQMP', lambda connection, stream: source_qmp)
    monkeypatch.setitem(E, 'qmp_connect', lambda *args, **kwargs: (io.BytesIO(), io.BytesIO(), None))
    monkeypatch.setitem(E, 'collect', collect)
    monkeypatch.setitem(E, 'new_receipt', lambda *args, **kwargs: {})
    monkeypatch.setitem(E, 'write_console', write_console)
    monkeypatch.setitem(G, 'shell', shell)
    monkeypatch.setitem(G, 'wait_for', wait_for)
    try:
        yield SimpleNamespace(instance=instance, runtime=runtime, cold=cold, output=output,
                              events=events, owners=owners, failure=failure, tx=tx, closing=closing,
                              source_qmp=lambda: source_qmp)
    finally:
        os.close(fd)


def invoke(host):
    return API['run'](host.runtime, host.cold, host.output, combo_manifest=host.cold, origin_qemu_build=host.runtime)


def test_orchestration_normal_close_under_same_lease_private_outputs(host):
    result = invoke(host)
    assert result['actual_content_verified'] and not result['capture_verified']
    assert host.events.index('collect') < host.events.index('capture') < host.events.index('restore')
    assert host.events.index('cont') < host.events.index('menu') < host.events.index('shooting')
    assert host.events[-2:] == ['close', 'lease-exit']
    assert [owner.poll() for owner in host.owners] == [0, 0]
    for path in host.output.rglob('*'):
        assert stat.S_IMODE(path.stat().st_mode) == (0o700 if path.is_dir() else 0o600)
    assert json.loads((host.output/'result.json').read_text())['ui_hot_enabled'] is False


def test_output_exists_rejected_without_prepare_or_popen(host):
    host.output.mkdir()
    with pytest.raises(ValueError, match='new explicit private'):
        invoke(host)
    assert host.events == []


@pytest.mark.parametrize('name', ['geometry.json', 'instance.json', 'persistent-geometry.bin', 'adapter.json'])
def test_metadata_mode_0600_pre_popen_no_automatic_chmod(host, name):
    path = host.instance/name
    path.write_text('{}')
    path.chmod(0o644)
    before = path.read_bytes()
    with pytest.raises(ValueError, match='No chmod performed'):
        invoke(host)
    assert stat.S_IMODE(path.stat().st_mode) == 0o644 and path.read_bytes() == before
    assert 'prepare' not in host.events and not host.owners
    assert (host.output/'failure.json').is_file()


@pytest.mark.parametrize('failure', ['start', 'ap', 'cold', 'proof'])
def test_source_failure_never_starts_target_and_normally_quits_source(host, failure):
    setattr(host.failure, failure, True)
    with pytest.raises((ValueError, RuntimeError)):
        invoke(host)
    assert 'restore' not in host.events and 'capture' not in host.events and 'construct' not in host.events
    assert len(host.owners) == 1 and host.owners[0].poll() == 0
    assert host.events[-1] == 'quit'
    assert not (host.output/'result.json').exists()


@pytest.mark.parametrize('failure', ['target_boot', 'mismatch'])
def test_target_new_cold_boot_or_scanout_mismatch_preserves_failure(host, failure):
    setattr(host.failure, failure, True)
    with pytest.raises(ValueError):
        invoke(host)
    assert 'close' in host.events
    assert (host.output/'failure.json').exists() and not (host.output/'result.json').exists()


def test_unowned_qmp_keeps_owner_without_quit_or_signals(monkeypatch, tmp_path):
    owner = Owner(99)
    calls = []
    qmp = ActiveDiskQMP(tmp_path/'unused', -1, calls)
    def refused(*args, **kwargs):
        raise ValueError('QMP is not owned')
    monkeypatch.setitem(C, '_owned_identity', refused)
    with pytest.raises(ValueError, match='not owned'):
        API['close_source'](SimpleNamespace(_output=tmp_path, children=[]), {}, owner, qmp)
    assert owner.poll() is None and calls == []
    assert qmp.running


def test_metadata_changed_after_prepare_is_still_rejected_before_popen(host, monkeypatch):
    original = API['L']['prepare_launch']
    def changed(*args, **kwargs):
        launch = original(*args, **kwargs)
        (host.instance/'geometry.json').chmod(0o644)
        return launch
    monkeypatch.setitem(API['L'], 'prepare_launch', changed)
    with pytest.raises(ValueError, match='No chmod performed'):
        invoke(host)
    assert not host.owners and (host.output/'failure.json').is_file()


def test_unowned_source_socket_records_live_owner_and_original_failure(host, monkeypatch):
    host.failure.start = True
    def refused(*args):
        raise ValueError('QMP is not owned')
    monkeypatch.setitem(C, '_owned_identity', refused)
    monkeypatch.setitem(G, 'authenticate_owner', refused)
    with pytest.raises(ValueError, match='not owned'):
        invoke(host)
    report = json.loads((host.output/'owner-retained.json').read_text())
    assert report['live_owner_pids'] == [101] and report['lease_retained_until_owner_exit']
    assert report['vm_signals_sent'] == [] and host.owners[0].poll() is None
    assert not {'query-status', 'stop', 'cont', 'quit', 'restore'}.intersection(host.events)
    assert 'source failed' in json.loads((host.output/'failure.json').read_text())['error']


@pytest.mark.parametrize('completed', [False, True])
def test_completion_echo_and_old_marker_are_not_new_guest_completion(monkeypatch, tmp_path, completed):
    marker = 'RETAINED_DONE_source='+'a'*32
    log = tmp_path/'console'
    log.write_text(marker+'\nold output\n')
    owner = Owner(77)
    def write(stream, raw):
        with log.open('a') as f:
            f.write('> echo '+marker+'\n'+(marker+'\n' if completed else ''))
    def wait(owner, path, condition, seconds):
        text = API['console'](path)
        if not condition(text):
            raise TimeoutError('echo rejected')
        return text
    monkeypatch.setitem(E, 'write_console', write)
    monkeypatch.setitem(G, 'wait_for', wait)
    if completed:
        assert API['shell'](owner, log, 'echo '+marker, 'source', 'a'*32).splitlines().count(marker) == 1
    else:
        with pytest.raises(TimeoutError, match='echo rejected'):
            API['shell'](owner, log, 'echo '+marker, 'source', 'a'*32)


def test_active_disk_fake_reproduces_real_timestamp_only_identity_failure(tmp_path, owned_peer):
    disk = tmp_path/'camera.emmc'
    disk.write_bytes(b'unchanged disk content')
    disk.chmod(0o600)
    fd = os.open(disk, os.O_RDWR)
    try:
        qmp = ActiveDiskQMP(disk, fd, [])
        qmp.sock = owned_peer.sock
        with pytest.raises(ValueError, match='stamp drift'):
            qmp.check_identity()
        sample, = qmp.samples
        assert sample['running']
        assert {k: v for k, v in sample['before'].items() if k != 'stamp'} == {
            k: v for k, v in sample['after'].items() if k != 'stamp'}
        assert sample['before']['stamp'] != sample['after']['stamp']
        assert disk.read_bytes() == b'unchanged disk content'
        evidence = tmp_path/'quiesce.jsonl'
        with API['paused'](qmp, evidence, tx=owned_peer.tx, owner=owned_peer.owner, resume=True):
            qmp.check_identity()
        assert qmp.running and not qmp.samples[-1]['running']
        rows = [json.loads(line) for line in evidence.read_text().splitlines()]
        responses = [row for row in rows if row['event'] == 'response']
        assert [row['command'] for row in responses] == ['query-status', 'stop', 'query-status', 'query-status', 'cont', 'query-status']
        assert [row['response'] for row in responses if row['command'] == 'query-status'] == [
            dict(status='running', running=True), dict(status='paused', running=False),
            dict(status='paused', running=False), dict(status='running', running=True)]
        assert stat.S_IMODE(evidence.stat().st_mode) == 0o600
    finally:
        os.close(fd)


@pytest.mark.parametrize('failure', ['before', 'stop', 'paused', 'body', 'cont', 'running-after'])
def test_quiesce_never_resumes_unknown_or_failed_operation(tmp_path, failure, owned_peer):
    base = ActiveDiskQMP(tmp_path/'unused', -1, [])
    queries = 0
    def qmp(command):
        nonlocal queries
        if command == 'query-status':
            queries += 1
        if command == failure or (failure == 'body' and command == 'unused'):
            base.events.append(command)
            raise RuntimeError('original '+failure+' error')
        response = base(command)
        if command == 'query-status' and ((failure == 'before' and queries == 1) or
                (failure == 'paused' and queries == 2) or (failure == 'running-after' and queries == 4)):
            return dict(status='unknown', running=False)
        return response
    qmp.sock = owned_peer.sock
    evidence = tmp_path/'quiesce.jsonl'
    with pytest.raises((ValueError, RuntimeError)):
        with API['paused'](qmp, evidence, tx=owned_peer.tx, owner=owned_peer.owner, resume=True):
            assert failure not in ('before', 'stop', 'paused')
            if failure == 'body':
                raise RuntimeError('original body error')
    assert base.events.count('cont') == (1 if failure in ('cont', 'running-after') else 0)
    rows = [json.loads(line) for line in evidence.read_text().splitlines()]
    assert rows[-1]['event'] == 'failed' and 'completed' not in [row['event'] for row in rows]
    assert stat.S_IMODE(evidence.stat().st_mode) == 0o600


@pytest.mark.parametrize('already_paused', [False, True])
def test_quiesce_exclusive_evidence_and_original_paused_state(tmp_path, already_paused, owned_peer):
    qmp = ActiveDiskQMP(tmp_path/'unused', -1, [])
    qmp.sock = owned_peer.sock
    qmp.running = not already_paused
    evidence = tmp_path/'quiesce.jsonl'
    with API['paused'](qmp, evidence, tx=owned_peer.tx, owner=owned_peer.owner, resume=True):
        assert not qmp.running
    assert qmp.running is (not already_paused)
    before, calls = evidence.read_bytes(), list(qmp.events)
    with pytest.raises(FileExistsError):
        with API['paused'](qmp, evidence, tx=owned_peer.tx, owner=owned_peer.owner, resume=True):
            raise AssertionError('Existing evidence must be rejected before QMP')
    assert evidence.read_bytes() == before and qmp.events == calls


def test_run_constructor_and_capture_only_compare_quiescent_identity(host):
    invoke(host)
    qmp = host.source_qmp()
    assert len(qmp.samples) == 2 and all(not row['running'] and row['before'] == row['after'] for row in qmp.samples)
    events = host.events
    construct, capture = events.index('construct'), events.index('capture')
    assert events.index('preauth') < events.index('stop') < construct < events.index('cont') < events.index('source')
    sync = events.index('guest-sync')
    assert sync < events.index('preauth', sync) < events.index('stop', sync) < capture
    assert 'guest-sync' not in events[capture:] and not qmp.running
    rows = [json.loads(line) for line in (host.output/'source-capture-quiesce.jsonl').read_text().splitlines()]
    assert [row['command'] for row in rows if row['event'] == 'response'] == ['query-status', 'stop', 'query-status']


@pytest.mark.parametrize('failure', ['construct', 'capture'])
def test_run_failed_quiescent_operation_never_resumes_before_normal_close(host, failure):
    setattr(host.failure, failure, True)
    with pytest.raises(RuntimeError, match='failed while paused'):
        invoke(host)
    qmp = host.source_qmp()
    failed_at = host.events.index(failure)
    assert 'cont' not in host.events[failed_at:] and 'restore' not in host.events
    assert all(not row['running'] for row in qmp.samples)
    if failure == 'capture':
        assert host.closing == [dict(source_alive=True, running=False)]
    assert host.owners[0].poll() == 0
    if failure == 'construct':
        assert 'quit' in host.events
    assert (host.output/'failure.json').exists() and not (host.output/'result.json').exists()


def test_real_peer_authentication_never_reads_active_disk(owned_peer, monkeypatch):
    def live_tx(*args):
        raise AssertionError('Preauthentication must not sample the live disk')
    monkeypatch.setitem(C, '_live_tx', live_tx)
    API['authenticate_owner'](owned_peer.tx, owned_peer.owner, owned_peer.qmp)
    assert owned_peer.qmp.events == []
    pid, uid, _ = API['struct'].unpack('3i', owned_peer.sock.getsockopt(
        API['socket'].SOL_SOCKET, API['socket'].SO_PEERCRED, 12))
    assert uid == os.getuid()
    assert (pid == owned_peer.owner.pid) is (C['_proc_identity'](pid)['parent_pid'] == os.getpid())


@pytest.mark.parametrize('damage', ['foreign-uid', 'not-in-tx', 'same-pid-unregistered', 'stale-owner',
                                  'wrong-ancestor', 'peer-uid', 'owner-uid', 'owner-parent'])
def test_quiesce_rejects_unauthenticated_peer_before_first_qmp(owned_peer, monkeypatch, tmp_path, damage):
    peer = owned_peer
    foreign = None
    if damage == 'foreign-uid':
        uid = os.getuid()
        monkeypatch.setattr(API['os'], 'getuid', lambda: uid+1)
    elif damage == 'not-in-tx':
        peer.tx.children.clear()
    elif damage == 'same-pid-unregistered':
        peer.tx.children[:] = [Owner(peer.owner.pid)]
    elif damage == 'stale-owner':
        peer.sock.close()
        assert peer.owner.wait(timeout=5) == 0
    elif damage == 'wrong-ancestor':
        foreign = API['socket'].socketpair()
        peer.qmp.sock = foreign[0]  # Real peer is this controller, outside the registered child's ancestry.
    else:
        original = C['_proc_identity']
        pid = API['struct'].unpack('3i', peer.sock.getsockopt(
            API['socket'].SOL_SOCKET, API['socket'].SO_PEERCRED, 12))[0]
        def identity(current):
            value = original(current)
            if current == (pid if damage == 'peer-uid' else peer.owner.pid):
                key = 'parent_pid' if damage == 'owner-parent' else 'uid'
                value[key] += 1
            return value
        monkeypatch.setitem(C, '_proc_identity', identity)
    evidence = tmp_path/'rejected.jsonl'
    try:
        with pytest.raises(ValueError, match='not owned'):
            with API['paused'](peer.qmp, evidence, tx=peer.tx, owner=peer.owner, resume=True):
                raise AssertionError('Unauthenticated peer entered the paused body')
        assert peer.qmp.events == [] and peer.qmp.running
        rows = [json.loads(line) for line in evidence.read_text().splitlines()]
        assert [row['event'] for row in rows] == ['failed']
    finally:
        if foreign is not None:
            for sock in foreign:
                sock.close()


def test_preauth_bounds_ancestor_walk_before_first_qmp(owned_peer, monkeypatch, tmp_path):
    local, remote = API['socket'].socketpair()
    with local as foreign, remote:
        calls = []
        original = C['_proc_identity']
        def identity(pid):
            calls.append(pid)
            if pid == owned_peer.owner.pid:
                return original(pid)
            return dict(pid=pid, uid=os.getuid(), parent_pid=max(pid+1, 0x70000000))
        monkeypatch.setitem(C, '_proc_identity', identity)
        owned_peer.qmp.sock = foreign
        with pytest.raises(ValueError, match='not descended'):
            with API['paused'](owned_peer.qmp, tmp_path/'bounded.jsonl', tx=owned_peer.tx, owner=owned_peer.owner):
                raise AssertionError('Unbounded ancestor chain was admitted')
        assert len(calls) == 14  # Two endpoint identities plus twelve ancestor reads.
        assert owned_peer.qmp.events == [] and owned_peer.qmp.running


def test_close_source_full_identity_after_authenticated_pause(host):
    host.failure.start = True
    with pytest.raises(RuntimeError, match='source failed'):
        invoke(host)
    events = host.events
    assert events.index('preauth') < events.index('stop') < events.index('full-owned-identity') < events.index('quit')
    assert host.owners[0].poll() == 0
    assert all(not row['running'] and row['before'] == row['after'] for row in host.source_qmp().samples)
