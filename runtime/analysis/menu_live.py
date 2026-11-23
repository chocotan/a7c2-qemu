"""Private live-control transport and serial commands; no caller-supplied shell."""
from contextlib import contextmanager
import base64
import io
import json
import os
import re
import secrets
import select
import signal
import socket
import stat
import subprocess
import time
import threading
import hashlib

from pathlib import Path

from headless_osd_capture import decode_export, HEADER, METADATA

MAX_MESSAGE = 2 * 1024 * 1024
MAX_SERIAL_OUTPUT = 8 * 1024 * 1024
MAX_CONSOLE = 16 * 1024 * 1024
# One declaration for both UIs and command generation. Unknown codes stay unavailable.
KEY_DEFINITIONS = {
    'MENU': dict(label='MENU', code='0x1ab', verified=True, native='M', shortcuts=['m', 'Escape']),
    'ENTER': dict(label='ENTER', code='0x1ac', verified=True, native='E', shortcuts=['Enter']),
    'UP': dict(label='上', code='0x3', verified=True, native='U', shortcuts=['ArrowUp']),
    'DOWN': dict(label='下', code='0x30', verified=True, native='D', shortcuts=['ArrowDown']),
    'LEFT': dict(label='左', code='0x15', verified=True, native='L', shortcuts=['ArrowLeft']),
    'RIGHT': dict(label='右', code='0x1af', verified=True, native='R', shortcuts=['ArrowRight']),
    'DELETE': dict(label='删除', code='0x1f8', verified=True, native='X', shortcuts=['Delete'],
                   note='已验证菜单帮助页；照片删除未验证'),
    'REAR_LEFT': dict(label='后拨轮左转', code='0x10000016', status='0xffffffe2',
                      native='<', shortcuts=['PageUp'], note='A7C II 单步 -30；原码→UIBIZ 2ea；拍摄 HUD 由虚拟镜头响应'),
    'REAR_RIGHT': dict(label='后拨轮右转', code='0x10000016', status='0x1e',
                       native='>', shortcuts=['PageDown'], note='A7C II 单步 +30；原码→UIBIZ 2ea；拍摄 HUD 由虚拟镜头响应'),
    'TOP_LEFT': dict(label='右上拨轮左转', code='0x10000013', status='0xfffffc00',
                     note='A7C II 单步 -1024；原码→UIBIZ 2ef；P档曝光补偿已见'),
    'TOP_RIGHT': dict(label='右上拨轮右转', code='0x10000013', status='0x400',
                      note='A7C II 单步 +1024；原码→UIBIZ 2ef；P档曝光补偿已见'),
    'CONTROL_LEFT': dict(label='控制轮左转',code='0x1000001d',status='0xffffffe8',note='A7C II 单步 -24；原码→UIBIZ 2f6'),
    'CONTROL_RIGHT': dict(label='控制轮右转',code='0x1000001d',status='0x18',note='A7C II 单步 +24；原码→UIBIZ 2f6'),
    'FRONT_LEFT': dict(label='前拨轮左转',code='0x1000001c',status='0xffffffea',note='A7C II 单步 -22；原码→UIBIZ 2f5'),
    'FRONT_RIGHT': dict(label='前拨轮右转',code='0x1000001c',status='0x16',note='A7C II 单步 +22；原码→UIBIZ 2f5'),
    'C2': dict(label='C2', alias='DELETE', note='与删除键共用；自定义 C2 功能未验证'),
    'DISP': dict(label='DISP', alias='UP', note='与上方向键共用；显示切换功能未验证'),
    'ISO': dict(label='ISO', alias='RIGHT', note='与右方向键共用；ISO 功能未验证'),
    'C1': dict(label='C1',code='0x66',
               note='原始码→UIBIZ e CUSTOM已核；当前自定义功能与原LCD响应待验'),
    'PLAYBACK': dict(label='播放',code='0x1f7',note='原始码→UIBIZ 22→02020003已核；原播放页待验'),
    'AF_ON': dict(label='AF-ON',code='0x0f000004',note='原始码→UIBIZ 2d7已核；原AF状态与对焦待验'),
    'FN': dict(label='Fn',code='0x7095',note='原始码→UIBIZ 8d→02020000已核；原Fn页面待验'),
    'EXPOSURE_COMP': dict(label='曝光补偿'),
    'SHUTTER_HALF': dict(label='半按',code='0x1f1',
                         note='原始码→UIBIZ 1d LOCK已核；仅点按半按触点，不持续保持；AF/AE功能待验'),
    'SHUTTER': dict(label='全按快门',code='0xa7',note='原始码→UIBIZ f全按事件已核；仅点按全按触点，成像与文件输出尚未恢复'),
    'REC': dict(label='REC',code='0x1f0',note='原始码→UIBIZ 1c→02150012已核；软件虚拟录像经 Libx264/MP4 写入虚拟 SD 卡 /PRIVATE/M4ROOT/CLIP/'),
    'MODE_STILL':dict(label='照片档',code='0x71c9',status='1',note='原2240002→switch0合法位置已核；实际照片档切换待验'),
    'MODE_MOVIE':dict(label='录像档',code='0x71c9',status='2',note='原2240002→switch1合法位置已核；全按/REC 可启停软件虚拟录像写卡'),
    'MODE_SQ':dict(label='S&Q档',code='0x71c9',status='3',note='原2240002→switch2合法位置已核；不是硬件高速编码完成'),
    'MODE': dict(label='模式拨盘',code='0x7025',
                 # Original ID1c75 entries declare AUTO0/P1/A2/S3/M4; name-array order differs.
                 positions={'P':3,'A':5,'S':4,'M':6,'AUTO':1,'MR1':7,'MR2':19,'MR3':20},
                 note='P/A/S/M/AUTO及MR1/MR2/MR3原HUD限定通过；完整参数回载及曝光消费待验'),
}


def key_definition(name):
    entry = KEY_DEFINITIONS[name]
    target = KEY_DEFINITIONS[entry.get('alias', name)]
    return dict(name=name, label=entry['label'], code=target.get('code'), status=target.get('status'),
                verified=entry.get('verified', False), native=entry.get('native'),
                shortcuts=entry.get('shortcuts', []),
                positions=entry.get('positions',{}),
                note=entry.get('note', '' if entry.get('verified') else '原生键码未验证，尚不能发送'))


# Compatibility projections for replay scripts; codes/statuses are never redeclared.
KEYS = {name: key_definition(name)['code'] for name in KEY_DEFINITIONS if key_definition(name)['code']}
SINGLE_STATUS = {name: key_definition(name)['status'] for name in KEYS if key_definition(name)['status']}
NATIVE_BUTTONS = {ord(entry['native']): name for name in KEY_DEFINITIONS
                  if (entry := key_definition(name))['native']}


def control_catalog(live_file=False):
    result = {}
    for name in KEY_DEFINITIONS:
        entry = key_definition(name)
        reason = ''
        if not entry['code']:
            reason = '未验证：原生键码未知，尚不能发送'
        elif live_file and (entry['status'] is not None or entry['positions']):
            reason = '未验证：当前 live 文件通道不支持拨轮单次增量'
        entry.update(available=not reason, unavailable_reason=reason,
                     verification='已验证' if entry['verified'] else '未验证')
        result[name] = entry
    return result


def camera_input_module():
    """Load the delivered bindings without adding a second runtime source copy."""
    import importlib.util
    import sys
    name = 'a7c2_camera_input_bindings'
    if name not in sys.modules:
        path = Path(__file__).resolve().parents[2] / 'report/camera-input-coverage/input_bindings.py'
        spec = importlib.util.spec_from_file_location(name, path)
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        try:
            spec.loader.exec_module(module)
        except BaseException:
            sys.modules.pop(name, None)
            raise
    return sys.modules[name]


class FirmwareFault(RuntimeError):
    pass


class FirmwareMonitor:
    """Follow the complete console, including faults between two commands."""
    def __init__(self, console):
        self.console = console
        self.offset = 0
        self.tail = b''
        self.failed = False
        self.failure_message = '相机固件发生异常，已停止接收按键；详情见 console.log'

    def check(self):
        if self.failed:
            raise FirmwareFault(self.failure_message)
        with self.console.open('rb') as reader:
            if os.fstat(reader.fileno()).st_size < self.offset:
                self.offset, self.tail = 0, b''
            reader.seek(self.offset)
            while chunk := reader.read(65536):
                self.offset += len(chunk)
                data = self.tail + chunk.replace(b'\r', b'')
                if re.search(rb'(?:^|\n)OBS FUNCTIONAL_FACE_SOURCE_RETAINED_FAULT ', data):
                    self.failed = True
                    self.failure_message = '功能源快照发生集成故障，原调用栈和资源已保留；详情见 console.log'
                    raise FirmwareFault(self.failure_message)
                if re.search(rb'(?:^|\n)OBS FUNCTIONAL_STILL_FORMAT_INTEGRATION_FAULT ', data):
                    self.failed = True
                    self.failure_message = '功能照片格式发生集成故障，原调用和资源状态已保留；详情见 console.log'
                    raise FirmwareFault(self.failure_message)
                if re.search(rb'(?:^|\n)OBS FUNCTIONAL_STARTUP_CONTROL_INTEGRATION_FAULT ', data):
                    self.failed = True
                    self.failure_message = '功能启动配置发生集成故障，原调用和资源状态已保留；详情见 console.log'
                    raise FirmwareFault(self.failure_message)
                if re.search(rb'(?:^|\n)(?:Entering exception monitor\.|Exception>|OBS GUI_MODEL_FAILED )', data):
                    self.failed = True
                    raise FirmwareFault(self.failure_message)
                self.tail = data[-128:]


def connect_in_run(sock, directory, name, *, socket_environment=None):
    selected=os.environ if socket_environment is None else socket_environment
    if ('A7C2_SINGLE_AP_SOCKETS' in selected or 'A7C2_SINGLE_AP_SOCKET_ROOT' in selected or
            os.path.lexists(Path(directory)/'single-ap-socket-binding.json')):
        from single_ap_sockets import roots_for_run
        roots=roots_for_run(directory,selected)
        if roots is not None:
            with roots.connect_path(roots.sockets/name) as address:sock.connect(address)
            return
    # Linux AF_UNIX paths are short; the run directory may live in a long checkout.
    fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
    try:
        sock.connect(f'/proc/self/fd/{fd}/{name}')
    finally:
        os.close(fd)


def inject_key_tool(queue, source, app32=False):
    if not app32:
        return '/simulation/inject-key'
    if int(queue, 0) != 0x5503e0 or int(source, 0) != 0x5503e0:
        raise ValueError('App32 injection requires queue/source 0x5503e0')
    return '/simulation/inject-key --app'


def key_command(key,app_input=False,position=None):
    code = KEYS[key]
    route='--app 0x005503e0 0x005503e0' if app_input else '0x807a0020 0x92840747'
    prefix = f'/simulation/inject-key {route} {code} 0'
    source_type = 0 if app_input else 1
    positions=key_definition(key)['positions']
    if positions:
        if not isinstance(position,str) or position not in positions:raise ValueError('该拨盘需要选择已识别的位置')
        return f'{prefix} {positions[position]} 0 {source_type}'
    if position is not None:raise ValueError('普通按键不能提供位置')
    if key in SINGLE_STATUS:
        return f'{prefix} {SINGLE_STATUS[key]} 0 {source_type}'
    # The native UI expects 1/0. A 50 ms guest tap avoids firmware auto-repeat.
    return (f'{prefix} 1 0 {source_type}; pressed=$?; sleep 0.05; '
            f'{prefix} 0 0 {source_type}; released=$?; test "$pressed" = 0 && test "$released" = 0')


def key_status_command(key, status, app_input=False):
    if status not in (0, 1):
        raise ValueError('普通按键状态必须为0或1')
    route = '--app 0x005503e0 0x005503e0' if app_input else '0x807a0020 0x92840747'
    source_type = 0 if app_input else 1
    return f'/simulation/inject-key {route} {KEYS[key]} 0 {status} 0 {source_type}'


def touch_command(phase, x, y):
    """Original App::main 0x179a0d0/0x179a1dc: x high16, y low16, finger 0."""
    if (phase not in ('begin', 'move', 'end') or type(x) is not int or not 0 <= x < 640
            or type(y) is not int or not 0 <= y < 480):
        raise ValueError('Invalid original LCD touch event')
    status = {'begin': 1, 'move': 2, 'end': 0}[phase]
    return f'/simulation/inject-key --app 0x005503e0 0x005503e0 0x270 {(x << 16) | y} {status} 0 0'


def shutter_cycle_command():
    """Original app32 input only; a response does not prove consumer or capture."""
    hold_ms = os.environ.get('A7C2_SHUTTER_HOLD_MS', '50')
    try:
        hold_ms = int(hold_ms)
    except ValueError:
        raise ValueError('A7C2_SHUTTER_HOLD_MS must be an integer in 50..5000') from None
    if not 50 <= hold_ms <= 5000:
        raise ValueError('A7C2_SHUTTER_HOLD_MS must be within 50..5000')
    hold = f'{hold_ms / 1000:.3f}'
    half = key_status_command('SHUTTER_HALF', 1, True)
    full = key_status_command('SHUTTER', 1, True)
    full_release = key_status_command('SHUTTER', 0, True)
    half_release = key_status_command('SHUTTER_HALF', 0, True)
    return (f'{half}; half_pressed=$?; sleep {hold}; '
            f'{full}; full_pressed=$?; sleep {hold}; '
            f'{full_release}; full_released=$?; {half_release}; half_released=$?; '
            'test "$half_pressed" = 0 && test "$full_pressed" = 0 && '
            'test "$full_released" = 0 && test "$half_released" = 0')


def live_key_command(key):
    code = KEYS[key]
    if key in SINGLE_STATUS or key_definition(key)['positions']:
        return None
    seq = time.monotonic_ns()
    def submit(status, number):
        return (f"printf '%x %x %u\\n' {code} {status} {number} "
                "> /tmp/menu-key.tmp && mv /tmp/menu-key.tmp /tmp/menu-key.request")
    return (f'{submit(1, seq)}; pressed=$?; sleep 0.05; '
            f'{submit(0, seq + 1)}; released=$?; '
            'test "$pressed" = 0 && test "$released" = 0')


def send_message(sock, value):
    sock.sendall(json.dumps(value, ensure_ascii=True).encode() + b'\n')


def receive_message(sock, timeout=120, cancelled=lambda: False):
    deadline = None if timeout is None else time.monotonic() + timeout
    data = bytearray()
    while deadline is None or time.monotonic()<deadline:
        if cancelled is not None and cancelled():
            raise RuntimeError('操作已取消')
        delay=.2 if deadline is None else min(.2,max(0,deadline-time.monotonic()))
        if not select.select([sock], [], [], delay)[0]:
            continue
        chunk = sock.recv(65536)
        if not chunk:
            raise RuntimeError('VM 控制通道已关闭')
        data.extend(chunk)
        if len(data) > MAX_MESSAGE:
            raise ValueError('控制消息过大')
        if b'\n' in data:
            if not data.endswith(b'\n') or data.count(b'\n') != 1:
                raise ValueError('控制消息边界错误')
            value = json.loads(data)
            if not isinstance(value, dict):
                raise ValueError('控制消息类型错误')
            return value
    raise TimeoutError('等待 VM 命令完成超时')


def clean_console(data):
    return re.sub(rb'\[\s*\d+\.\d+\] (?:UDIF:|\[K\])[^\n]*\n', b'', data.replace(b'\r\n', b'\n'))


def wait_initial_model_commit(proc, console, timeout=30):
    """Explicit early-debug startup: require real model publication, not RC1 retry."""
    deadline = time.monotonic()+timeout
    while time.monotonic() < deadline:
        monitor = FirmwareMonitor(console)
        monitor.check()
        data = console.read_bytes()
        if re.search(rb'(?:^|\n)OBS GUI_MODEL_COMMITTED packets=[1-9]\d* ', data):
            return
        if proc.poll() is not None:
            raise RuntimeError('VM ended before original GUI model publication')
        time.sleep(.05)
    raise TimeoutError('Original GUI model publication missing during early-debug startup')


def netdev_socket_alias(out):
    """Short host path to the isolated-netdev socket of one run.

    The launcher binds the run directory at /out inside bwrap, so QEMU creates
    <run>/ethernet.sock. A run directory under menu-runs is longer than the
    108-byte AF_UNIX limit, so the host peer connects through a short symlink
    instead of the full path. Returns (socket path, alias to remove).
    """
    out = Path(out)
    alias = Path('/tmp')/f'a7c2-usb-{out.name[-8:]}'
    alias.unlink(missing_ok=True)
    alias.symlink_to(out)
    return alias/'ethernet.sock', alias


class QMPStrictStream:
    """Synthetic-only opt-in transport; owns a private RX duplicate until close()."""
    def __init__(self, sock, rx_fd, check_generation, *, synthetic_only=False):
        if synthetic_only is not True:
            raise RuntimeError('Strict QMP real owner adapter unavailable; synthetic-only candidate')
        if not isinstance(sock,socket.socket) or sock.family!=socket.AF_UNIX or sock.type!=socket.SOCK_STREAM:
            raise ValueError('Strict QMP requires its exclusive raw Unix stream socket')
        if sock.gettimeout() is None or sock.gettimeout()<=0:
            raise ValueError('Strict QMP requires a finite positive socket timeout')
        if not callable(check_generation):raise TypeError('Real generation checker required')
        original=os.fstat(rx_fd)
        private_fd=os.dup(rx_fd)
        try:
            info=os.fstat(private_fd)
            identity=lambda value:(value.st_dev,value.st_ino,value.st_mode,value.st_uid,value.st_nlink)
            if identity(original)!=identity(info):
                raise ValueError('Strict QMP RX evidence changed during duplication')
            if not stat.S_ISREG(info.st_mode) or info.st_uid!=os.geteuid() or stat.S_IMODE(info.st_mode)!=0o600 or info.st_nlink!=1 or info.st_size:
                raise ValueError('Strict QMP requires a fresh owned private regular RX evidence file')
            os.pread(private_fd,1,0)
        except BaseException:
            try:os.close(private_fd)
            except OSError:pass
            raise
        self.sock,self.check_generation=sock,check_generation
        # dup pins caller-close lifetime, not immutable content: the original shares this inode.
        self._rx_fd=private_fd
        self._rx_identity=identity(info)
        self._closed=False
        self._close_error=None
        self._received=0
        self._buffer=bytearray()
        self._state=threading.Lock()
        self._inflight=threading.Lock()
        self._failure_requested=threading.Event()
        self._failed=self._greeted=self._acknowledged=self._recording=False
        self._proc=None

    def _healthy(self):
        with self._state:
            if self._closed or self._failed or self._failure_requested.is_set():
                raise RuntimeError('Strict QMP failure latched or closed; no further commands')

    def _fail(self,proc):
        # Announce before waiting for state, so an ACK cannot hide a queued failure.
        self._failure_requested.set()
        with self._state:
            self._failed=True
            if proc is not None:proc._menu_qmp_desynchronized=True
            if self._proc is not None:self._proc._menu_qmp_desynchronized=True

    def _check(self,stage):
        self._healthy()
        self.check_generation(stage)
        self._healthy()

    @contextmanager
    def transaction(self,proc,*,greeting=False):
        if not self._inflight.acquire(blocking=False):
            self._fail(proc)
            raise RuntimeError('Strict QMP concurrent/reentrant request; failure latched')
        try:
            with self._state:
                self._acknowledged=False
                if (self._failed or self._failure_requested.is_set() or
                        (self._proc is not None and self._proc is not proc) or
                        getattr(proc,'_menu_qmp_desynchronized',False) or
                        (greeting and self._greeted) or (not greeting and not self._greeted)):
                    raise RuntimeError('Strict QMP boundary unavailable; failure latched')
                self._proc=proc
            self._check('transaction')
            yield
            self._healthy()
        except BaseException:
            if not self._acknowledged:self._fail(proc)
            raise
        finally:
            self._inflight.release()

    def _evidence_info(self,size=None):
        if self._closed:raise RuntimeError('Strict QMP RX evidence is closed')
        info=os.fstat(self._rx_fd)
        identity=(info.st_dev,info.st_ino,info.st_mode,info.st_uid,info.st_nlink)
        if identity!=self._rx_identity or (size is not None and info.st_size!=size):
            raise ValueError('Strict QMP RX evidence identity or length changed')
        return info

    def close(self):
        """Close only the adapter-owned duplicate; never close the socket or source FD."""
        if not self._inflight.acquire(blocking=False):
            self._fail(self._proc)
            raise RuntimeError('Strict QMP close during active transaction; failure latched')
        try:
            if self._closed:
                if self._close_error is not None:raise self._close_error
                return
            with self._state:
                recording=self._recording
            if recording:raise RuntimeError('Strict QMP close during RX evidence recording')
            # Ignore length on teardown, but never close a replaced foreign descriptor.
            try:self._evidence_info()
            except BaseException as error:
                # Unknown FD lifetime: retire the number without closing or checking it again.
                self._rx_fd=None
                self._closed=True
                self._close_error=error
                raise
            private_fd,self._rx_fd=self._rx_fd,None
            # Retire before close: an error may still have released and reused its FD number.
            self._closed=True
            try:os.close(private_fd)
            except BaseException as error:
                self._close_error=error
                raise
        except BaseException:
            self._fail(self._proc)
            raise
        finally:
            self._inflight.release()

    def _record(self,raw):
        # Consumed bytes are evidence even after another transaction has poisoned QMP.
        with self._state:
            reentrant=self._recording
            if not reentrant:self._recording=True
        if reentrant:
            self._fail(self._proc)
            raise RuntimeError('Strict QMP reentrant RX evidence; failure latched')
        try:
            start=self._received
            self._evidence_info(start)
            if start+len(raw)>8*1024*1024:raise ValueError('Strict QMP RX evidence budget exceeded')
            written=os.pwrite(self._rx_fd,raw,start)
            self._evidence_info(start+written)
            if written!=len(raw):raise OSError('Short strict QMP evidence write')
            os.fsync(self._rx_fd)
            self._evidence_info(start+len(raw))
            readback=os.pread(self._rx_fd,len(raw),start)
            self._evidence_info(start+len(raw))
            if readback!=raw:raise ValueError('Strict QMP RX evidence readback differs')
            with self._state:self._received=start+len(raw)
        except BaseException:
            self._fail(self._proc)
            raise
        finally:
            with self._state:self._recording=False

    def readline(self,limit):
        while True:
            end=self._buffer.find(b'\n')+1
            if end or len(self._buffer)>=limit:
                end=min(end or limit,limit)
                raw=bytes(self._buffer[:end]);del self._buffer[:end]
                return raw
            self._check('recv')
            raw=self.sock.recv(min(4096,limit-len(self._buffer)))
            self._proc._menu_qmp_last_raw=raw
            if raw:self._record(raw)
            # Record before checking: even a generation failure must retain received bytes.
            self._check('recv-complete')
            if not raw:
                raw=bytes(self._buffer);self._buffer.clear()
                return raw
            self._buffer.extend(raw)

    def write(self,raw):return self.sock.send(raw)
    def flush(self):pass  # Raw socket writes have no userspace output buffer.

    def _ack(self,*,greeting=False):
        self._check('ack')
        with self._state:
            if self._failed or self._failure_requested.is_set():
                raise RuntimeError('Strict QMP failure latched before ACK')
            self._acknowledged=True
            if greeting:self._greeted=True
            self._proc._menu_qmp_desynchronized=False

    def greeting(self,proc):
        with self.transaction(proc,greeting=True):
            proc._menu_qmp_desynchronized=True
            raw=self.readline(65537)
            proc._menu_qmp_last_raw=raw
            self._check('frame')
            reply=_qmp_decode_frame(raw)
            if set(reply)!={'QMP'} or not isinstance(reply['QMP'],dict):
                raise ValueError('Unexpected strict QMP greeting')
            self._ack(greeting=True)
            return reply


def _qmp_decode_frame(raw):
    if not raw or len(raw)>=65537 or not raw.endswith(b'\n'):raise OSError('Incomplete QMP reply')
    def unique(pairs):
        result={}
        for key,value in pairs:
            if key in result:raise ValueError('Duplicate QMP JSON field')
            result[key]=value
        return result
    reply=json.loads(raw,object_pairs_hook=unique)
    if not isinstance(reply,dict):raise ValueError('QMP reply must be an object')
    return reply


def qmp_transaction(proc,stream,name,arguments=None,*,send=None):
    """One QMP request; strict transport is opt-in, with the same return/send contract."""
    if isinstance(stream,QMPStrictStream):
        with stream.transaction(proc):
            return _qmp_transaction(proc,stream,name,arguments,send=send)
    return _qmp_transaction(proc,stream,name,arguments,send=send)


def _qmp_transaction(proc,stream,name,arguments=None,*,send=None):
    if getattr(proc,'_menu_qmp_desynchronized',False):
        raise RuntimeError('QMP transaction boundary lost; no further commands')
    request_id=secrets.token_hex(16)
    message={'execute':name,'id':request_id}
    if arguments is not None:message['arguments']=arguments
    encoded=(json.dumps(message)+'\n').encode()
    proc._menu_qmp_request_id=request_id
    proc._menu_qmp_last_raw=None
    proc._menu_qmp_desynchronized=True
    if isinstance(stream,QMPStrictStream):stream._check('send')
    if send is None:
        if stream.write(encoded)!=len(encoded):raise OSError('Short QMP command write')
        stream.flush()
    else:
        if send(encoded)!=len(encoded):raise OSError('Short QMP descriptor command write')
    for _ in range(1024):
        raw=stream.readline(65537)
        proc._menu_qmp_last_raw=raw
        if isinstance(stream,QMPStrictStream):stream._check('frame')
        reply=_qmp_decode_frame(raw)
        if 'event' in reply and not any(key in reply for key in ('id','return','error')):
            continue
        if reply.get('id')!=request_id or ('return' in reply)==('error' in reply):
            raise ValueError('QMP reply does not match the current request')
        if isinstance(stream,QMPStrictStream):stream._ack()
        else:proc._menu_qmp_desynchronized=False
        if 'error' in reply:raise RuntimeError(str(reply['error']))
        del reply['id']
        return reply
    raise RuntimeError('QMP event budget exceeded; no response received')


def serial_command(proc, console, command, timeout=90, monitor=None,allow_faulted_cleanup=False):
    """Ignore echoed commands/prompts and require this command's exact RC sentinel."""
    if getattr(proc, '_menu_serial_desynchronized', False):
        raise RuntimeError('Serial transaction boundary lost; retain VM for explicit recovery, no further commands')
    marker = 'MENU_DIAG_COMMAND_DONE_' + secrets.token_hex(12)
    wire = (command + "; rc=$?; printf '\\n" + marker + ":%s\\n' \"$rc\"\n").encode()
    if any(len(line) > 1000 for line in wire.split(b'\n')):
        raise ValueError('Guest serial physical command line exceeds safe1000-byte bound; split the command')
    # A running writer may still hold this inode; truncating it destroys evidence.
    if console.stat().st_size > MAX_CONSOLE:
        proc._menu_serial_desynchronized = True
        raise RuntimeError('串口日志超过安全上限；保留原日志及 VM，禁止继续发送命令')
    transport = getattr(proc, '_app_input_transport', None)
    if transport is not None:
        transport.pause()
    monitor = None if allow_faulted_cleanup else (monitor or FirmwareMonitor(console))
    if monitor:monitor.check()
    from console_wakeup import ConsoleWakeup
    with ConsoleWakeup(console) as wakeup, console.open('rb') as reader:
        reader.seek(0, 2)
        proc._menu_serial_desynchronized = True
        proc.stdin.write(wire)
        proc.stdin.flush()
        data = bytearray()
        deadline = None if timeout is None else time.monotonic() + timeout
        while deadline is None or time.monotonic() < deadline:
            if monitor:monitor.check()
            data.extend(reader.read(65536))
            if len(data) > MAX_SERIAL_OUTPUT:
                raise RuntimeError('单次串口输出超过限制；命令边界未知，保留 VM 和日志')
            clean = clean_console(bytes(data))
            if not allow_faulted_cleanup and b'Exception>' in clean:
                raise RuntimeError('固件进入异常监视器')
            match = re.search(rb'\n' + marker.encode() + rb':([0-9]+)\n', clean)
            if match:
                proc._menu_serial_desynchronized = False
                if int(match[1]):
                    raise RuntimeError('guest 命令失败，返回码 ' + match[1].decode())
                return bytes(data)
            if proc.poll() is not None:
                raise RuntimeError('VM 进程提前退出')
            wakeup.wait(.05 if deadline is None else min(.05, max(0, deadline - time.monotonic())))
    proc._menu_serial_desynchronized = True
    raise TimeoutError('串口命令缺少完成标记；停止 VM 以避免后续命令交错')


@contextmanager
def owner_signal_guard():
    """Keep cooperative signals from dropping a live VM owner."""
    previous={}
    try:
        for number in (signal.SIGTERM,signal.SIGINT):
            previous[number]=signal.signal(number,lambda _number,_frame:None)
        yield
    finally:
        for number,handler in previous.items():signal.signal(number,handler)


def retain_running_owner(proc, run, cause=None, *, reason):
    with owner_signal_guard():
        return _retain_running_owner(proc,run,cause,reason=reason)


def _retain_running_owner(proc, run, cause=None, *, reason):
    """Keep the current owner alive while VM exit is not confirmed."""
    if reason not in ('serial-boundary','qmp-exit'):
        raise ValueError('Unknown owner-retention reason')
    try:exited=proc.poll() is not None
    except BaseException:exited=False
    try:
        receipt={'schema':'a7c2-unknown-owner-v3','pid':proc.pid,'reason':reason,
                 'serial_boundary_known':False if getattr(proc,'_menu_serial_desynchronized',False) else None,
                 'signals_sent':[],'owner_retention_intent':not exited,'process_exit_observed':exited,
                 'cause':str(cause)[:2048] if cause else None}
        filename=reason+'-unknown.json'
        directory=os.open(run,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW|os.O_CLOEXEC)
        try:
            folder=os.fstat(directory)
            if not stat.S_ISDIR(folder.st_mode) or folder.st_uid!=os.geteuid() or folder.st_mode&0o022:
                raise ValueError('Serial owner receipt directory is not owned')
            last=getattr(proc,'_menu_qmp_last_raw',None) if reason=='qmp-exit' else None
            receipt['qmp_request_id']=getattr(proc,'_menu_qmp_request_id',None) if reason=='qmp-exit' else None
            receipt['qmp_last_wire_frame_available']=isinstance(last,bytes)
            if isinstance(last,bytes):
                raw_fd=os.open('qmp-unknown-last-frame.raw',os.O_RDWR|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW|os.O_CLOEXEC,0o600,dir_fd=directory)
                try:
                    if os.write(raw_fd,last)!=len(last):raise OSError('Short QMP evidence write')
                    os.fsync(raw_fd)
                    if os.pread(raw_fd,len(last)+1,0)!=last:raise ValueError('QMP evidence readback differs')
                finally:os.close(raw_fd)
                receipt['qmp_last_wire_frame_sha256']=hashlib.sha256(last).hexdigest()
            fd=os.open(filename,os.O_RDWR|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW|os.O_CLOEXEC,0o600,dir_fd=directory)
            try:
                raw=(json.dumps(receipt,indent=2,allow_nan=False)+'\n').encode()
                if os.write(fd,raw)!=len(raw):raise OSError('Short serial owner receipt write')
                os.fsync(fd)
                info=os.fstat(fd);named=os.stat(filename,dir_fd=directory,follow_symlinks=False)
                if (info.st_dev,info.st_ino,info.st_size)!=(named.st_dev,named.st_ino,len(raw)) or os.pread(fd,len(raw)+1,0)!=raw:
                    raise ValueError('Serial owner receipt readback differs')
                os.fsync(directory)
            finally:os.close(fd)
        finally:os.close(directory)
    except BaseException as error:
        try:print('SERIAL_OWNER_RECEIPT_FAILED '+repr(error),flush=True)
        except BaseException:pass
    if exited:return False
    try:print('SERIAL_OWNER_RETAINED pid='+str(proc.pid)+' no-signals',flush=True)
    except BaseException:pass
    reported=False
    while True:
        try:
            if proc.poll() is not None:break
            proc.wait()
        except (InterruptedError,KeyboardInterrupt):continue
        except Exception as error:
            if not reported:
                try:print('SERIAL_OWNER_WAIT_FAILED '+repr(error),flush=True)
                except BaseException:pass
                reported=True
            try:time.sleep(.2)
            except KeyboardInterrupt:pass
    return True


@contextmanager
def guard_live_owner(proc,run):
    try:yield
    except BaseException as error:
        retain_running_owner(proc,run,error,reason='qmp-exit')
        raise


def retain_process_group(proc):
    with owner_signal_guard():
        return _retain_process_group(proc)


def _retain_process_group(proc):
    reported=False
    while True:
        try:
            os.killpg(proc.pid,0)
        except ProcessLookupError:break
        except BaseException as probe_error:
            if not reported:
                try:print('OWNER_GROUP_IDENTITY_UNKNOWN '+repr(probe_error),flush=True)
                except BaseException:pass
                reported=True
        try:time.sleep(.5)
        except (KeyboardInterrupt,InterruptedError):continue


@contextmanager
def guard_process_group(proc,run):
    try:yield
    except BaseException as error:
        retain_running_owner(proc,run,error,reason='qmp-exit')
        retain_process_group(proc)
        raise


def retain_serial_owner(proc,run,cause=None):
    if not getattr(proc,'_menu_serial_desynchronized',False):return False
    return retain_running_owner(proc,run,cause,reason='serial-boundary')


def verified_yc_preview(run):
    """Return staged luma only after the original AP has delivered that DMM frame."""
    path = os.environ.get('MENU_YC_INPUT_RAW')
    if not path:
        return None
    source = Path(path)
    if source.is_symlink() or not source.is_file() or source.stat().st_size != 1920 * 1080:
        raise ValueError('YC preview source is missing or changed')
    raw = source.read_bytes()
    manifest = (run / 'runtime-manifest.json').read_bytes()
    expected = json.loads(manifest).get('yc_input_sha256')
    manifest_sha256 = hashlib.sha256(manifest).hexdigest()
    if hashlib.sha256(raw).hexdigest() != expected:
        raise ValueError('YC preview source differs from the verified initramfs')
    receipt = run / 'yc-preview-admission.json'
    proof = None
    if receipt.exists():
        proof = json.loads(receipt.read_text())
        if (proof.get('source_sha256') != expected or type(proof.get('out1_delivered')) is not bool or
                proof.get('manifest_sha256') != manifest_sha256 or proof.get('run') != str(run.resolve())):
            raise ValueError('YC preview receipt differs from the verified input')
        if proof['out1_delivered']:return raw
    log = (run / 'console.log').read_bytes()
    marker = re.search(rb'YCIN_INPUT: PNG luma readback bytes=2073600 fnv64=([0-9a-f]{16})', log)
    if not marker and proof is None:
        return None
    if marker:
        value = 0xcbf29ce484222325
        for byte in raw:
            value = ((value ^ byte) * 0x100000001b3) & ((1 << 64) - 1)
        if marker.group(1).decode() != f'{value:016x}':
            raise ValueError('YC preview source differs from the guest DMM readback')
        proof = dict(source_sha256=expected, guest_fnv64=f'{value:016x}',
                     manifest_sha256=manifest_sha256, run=str(run.resolve()),
                     scope='AP DMM luma readback and OUT1 delivery; not CP display or encoded capture')
    # Preserve the validated digest even if OUT1 arrives after this console is rotated.
    proof['out1_delivered'] = b'YCIN_VDT_REPLY: OUT1 frame delivery' in log
    temporary = receipt.with_suffix('.tmp')
    temporary.write_text(json.dumps(proof, indent=2) + '\n')
    temporary.replace(receipt)
    return raw if proof['out1_delivered'] else None


def snapshot_message(console, preview=None):
    from PIL import Image
    raw, info = decode_export(console)
    pixels = raw[HEADER + METADATA:]
    rgba = bytearray(640 * 480 * 4)
    for i in range(640 * 480):
        value = pixels[i * 2] | pixels[i * 2 + 1] << 8
        rgba[i * 4:i * 4 + 4] = bytes((value >> 12, value >> 8 & 15, value >> 4 & 15, value & 15))
    rgba = bytes(channel * 17 for channel in rgba)
    image = Image.frombytes('RGBA', (640, 480), rgba)
    if preview is not None:
        if len(preview) != 1920 * 1080:
            raise ValueError('YC preview frame length differs')
        # This is an AP-consumed luma mirror under the original AP OSD, not a
        # claim that CP VDF/VPH produced the panel's native preview pixels.
        luma = Image.frombytes('L', (1920, 1080), preview).resize((640, 360), Image.Resampling.BILINEAR)
        background = Image.new('RGBA', (640, 480), (0, 0, 0, 255))
        background.paste(luma.convert('RGBA'), (0, 60))
        image = Image.alpha_composite(background, image)
        info.update(source='AP VDT luma mirror + original AP OSD; CP VDF/VPH not restored',
                    preview_sha256=hashlib.sha256(preview).hexdigest(),
                    osd_container_sha256=info['sha256'],
                    sha256=hashlib.sha256(image.convert('RGB').tobytes()).hexdigest(),
                    preview_luma_only=True)
    buffer = io.BytesIO()
    image.save(buffer, format='PNG')
    return {'type': 'snapshot', 'info': info, 'captured_at': time.time(),
            'png': base64.b64encode(buffer.getvalue()).decode()}


def display_snapshot_message(path,number):
    from PIL import Image
    if path.is_symlink() or not path.is_file() or path.stat().st_size>2*1024*1024:
        raise ValueError('QMP display file is not a bounded regular image')
    with Image.open(path) as image:
        if image.format!='PPM' or image.size!=(640,480):
            raise ValueError('QMP display geometry/format mismatch')
        image=image.convert('RGB');pixels=image.tobytes();output=io.BytesIO();image.save(output,format='PNG')
    return {'type':'snapshot','captured_at':time.time(),
            'png':base64.b64encode(output.getvalue()).decode(),
            'info':{'sequence':number,'pixel_source_seq':None,'sha256':hashlib.sha256(pixels).hexdigest(),
                    'source':'QMP ramfb display','mode':'AP software display; not a captured photograph'}}


def run_live(proc, out, descriptor, display_capture=None, sd_export=None, network=None, sd_card=None, storage_shutdown=None, ram_capture=None, fast_shm_view=None):
    monitor = FirmwareMonitor(out / 'console.log')
    input_stack_captured = False
    shutter_submitted = False
    late_passive = None
    still_entry_observed = False
    session_fault = None
    def live_serial(command):
        nonlocal session_fault
        try:
            return serial_command(proc,out/'console.log',command,monitor=monitor)
        except (OSError,RuntimeError) as error:
            if sd_export is None:raise
            # A timed-out command may still be in flight. Keep the SD-owning VM,
            # reject further ordinary commands, and retain only recovery/export.
            session_fault=f'{type(error).__name__}: {error}'
            raise FirmwareFault(session_fault) from error
    def submit_input(command,result):
        try:live_serial(command)
        except FirmwareFault as error:
            if sd_export is None:raise
            return {'type':'error','error':str(error)}
        return result
    cmos_video_streamer = None
    def _stop_cmos_streamer():
        nonlocal cmos_video_streamer
        streamer, cmos_video_streamer = cmos_video_streamer, None
        if streamer is not None:
            streamer.stop()

    video_recorder = None
    if fast_shm_view is not None and fast_shm_view.video_ctrl_ready():
        from video_recorder import VideoRecordManager
        video_recorder = VideoRecordManager(fast_shm_view, out, proc=proc).start()

    input_session = (None if os.environ.get('MENU_LIVE_KEY_FILE') else
                     camera_input_module().InputSession(live_serial,
                         app_input=os.environ.get('MENU_LIVE_APP_INPUT') == '1'))
    with socket.socket(fileno=descriptor) as control:
      try:
        # Barrier follows the entire queued setup, not a shell prompt or stdout "ready".
        serial_command(proc, out / 'console.log', 'true', monitor=monitor)
        if os.environ.get('A7C2_MEDIA_INIT_WATCH') == '1' and os.environ.get('MENU_GUI_MODELS') == 'virtual-inline-v1':
            wait_initial_model_commit(proc, out/'console.log')
        transport_label = 'original-infra20-or-menu-mailbox'
        if input_session is not None and input_session.app_input:
            from persistent_app_input import PersistentAppInput
            serial_app = PersistentAppInput(proc, out/'console.log', monitor)
            if fast_shm_view is not None:
                from fast_shm import FastShmAppInput
                deadline = time.monotonic() + 2.0
                while not fast_shm_view.guest_input_ready() and time.monotonic() < deadline:
                    if proc.poll() is not None:
                        break
                    time.sleep(0.005)
                fast_app = FastShmAppInput(fast_shm_view, serial_app, proc, monitor)
                input_session.input_fn = fast_app
                proc._app_input_transport = fast_app
                transport_label = ('fast-shm-app32-ring' if fast_shm_view.guest_input_ready()
                                   else 'original-app32-persistent-serial')
            else:
                input_session.input_fn = serial_app
                transport_label = 'original-app32-persistent-serial'
        card_state=sd_card.status() if sd_card is not None else None
        if input_session is not None and input_session.app_input:
            input_session.input_fn.start()
        send_message(control, {'type': 'ready', 'run': str(out), 'sd_card': card_state,
                               'input_lifecycle': input_session is not None,
                               'touch_input': input_session is not None and input_session.app_input,
                               'input_transport': transport_label,
                               'input_state': input_session.status() if input_session else None})
        while True:
            fault=session_fault
            try:monitor.check()
            except FirmwareFault as error:
                if sd_export is None:raise
                fault=str(error)
            if proc.poll() is not None:
                if proc.returncode == 0:
                    return
                (out/'vm-unexpected-exit.json').write_text(json.dumps(
                    {'scope': 'guest launcher process', 'returncode': proc.returncode,
                     'capture_verified': False}, indent=2)+'\n')
                raise RuntimeError(f'VM 已退出，guest 启动器返回码 {proc.returncode}')
            if (not still_entry_observed and not fault and
                    os.environ.get('A7C2_EE_PASSIVE_ON_STILL_ENTRY')=='1' and
                    re.search(rb'OBS ENTER_REC_STILL n=\d+ ',(out/'console.log').read_bytes())):
                still_entry_observed=True
                observed={'ok':False,'phase':'after observed Still entry, before next live command',
                          'threads_not_stopped':True,'current_blocker_proven':False,'capture_verified':False}
                try:
                    from ee_entry_snapshot import collect_passive,collect_group0
                    snapshot=collect_passive(live_serial,out,common_only=True)
                    group0=collect_group0(live_serial,out,snapshot)
                    (Path(snapshot['snapshot_dir'])/'group0.json').write_text(json.dumps(group0,indent=2)+'\n')
                    observed.update(ok=snapshot.get('available',False),snapshot_dir=snapshot['snapshot_dir'],group0=group0)
                except Exception as error:
                    observed['error']=f'{type(error).__name__}: {error}'
                    fault=session_fault
                (out/'ee-still-entry.json').write_text(json.dumps(observed,indent=2)+'\n')
            if not select.select([control], [], [], .5)[0]:
                continue
            request = receive_message(control, timeout=5)
            action = request.get('action')
            releasing = camera_input_module().is_release(request)
            if fault and action!='export_sd' and not releasing:
                send_message(control,{'type':'error','error':fault});continue
            if sd_card is not None and sd_card.input_blocked() and action not in ('sd_card','snapshot','export_sd','video_status') and not releasing:
                raise ValueError('SD transition has no terminal observation; camera input is paused')
            if (action in ('key', 'position', 'shutter_cycle') and input_session is not None
                    and (input_session.held or input_session.uncertain or input_session.touch_contact is not None)):
                send_message(control, {'type': 'error', 'error': 'Release held camera inputs before using the legacy tap route'})
                continue
            if action == 'camera_input':
                if input_session is None:
                    raise ValueError('Legacy input mailbox does not support held contacts')
                prev_vtoggle = video_recorder.toggle_seq() if video_recorder is not None else 0
                result = input_session.handle(request)
                if (result.get('ok') is True and request.get('op') in ('press', 'tap')
                        and request.get('key') == 'SHUTTER'):
                    shutter_submitted = True
                if (result.get('ok') is True and video_recorder is not None
                        and request.get('op') in ('press', 'tap')
                        and (request.get('key') == 'REC'
                             or (request.get('key') == 'SHUTTER' and fast_shm_view.video_state()[3] != 1))):
                    result['video_recording'] = video_recorder.wait_after_rec_key(prev_vtoggle)
            elif action=='firmware_readback':
                from firmware_development import readback_command, parse_readback
                data=live_serial(readback_command(request))
                result=parse_readback(data,request)
                (out/'firmware-readback.raw').write_bytes(data)
                (out/'firmware-readback.json').write_text(json.dumps(result,indent=2)+'\n')
            elif (action=='sd_card' and set(request)=={'action','present'}
                    and type(request['present']) is bool):
                if sd_card is None:raise ValueError('This run has no SD hotplug profile')
                try:result=sd_card.set_present(request['present'])
                except (OSError,RuntimeError,ValueError) as error:
                    result={'type':'sd_card','ok':False,'state':'uncertain',
                            'error':f'{type(error).__name__}: {error}'}
            elif (action=='wifi' and set(request)=={'action','enabled'}
                    and type(request['enabled']) is bool):
                if network is None:
                    raise ValueError('本次运行未启用隔离网络')
                try:
                    result=network.set_enabled(request['enabled'])
                except (OSError,RuntimeError,ValueError) as error:
                    result={'type':'error','action':'wifi','error':f'{type(error).__name__}: {error}'}
                result={'type':'wifi',**{key:value for key,value in result.items() if key!='action'}}
                try:(out/'wifi-state.json').write_text(json.dumps(result,indent=2)+'\n')
                except OSError:pass
                with (out/'wifi-events.jsonl').open('a') as events:
                    events.write(json.dumps({'requested': request['enabled'], **result})+'\n')
            elif action=='cmos_source' and set(request) in ({'action','path'},{'action','default'}):
                import cmos_source
                try:
                    _stop_cmos_streamer()
                    if fast_shm_view is not None and fast_shm_view.guest_display_ready():
                        if 'path' in request:
                            req_path = request['path']
                            if cmos_source.is_video_path(req_path):
                                cmos_video_streamer = cmos_source.VideoCmosStreamer(
                                    req_path, fast_shm_view.set_custom_cmos,
                                ).start()
                                result={'type':'cmos_source','ok':True,'source':'custom','kind':'video',
                                        'name':Path(req_path).name,'fps':cmos_video_streamer.fps,
                                        'width':cmos_video_streamer.width,'height':cmos_video_streamer.height}
                            else:
                                rgb24=cmos_source.prepare_rgb24(req_path)
                                fast_shm_view.set_custom_cmos(rgb24)
                                result={'type':'cmos_source','ok':True,'source':'custom','kind':'image',
                                        'name':Path(req_path).name}
                        elif request['default'] is True:
                            fast_shm_view.set_custom_cmos(None)
                            result={'type':'cmos_source','ok':True,'source':'default-color-chart','name':'色卡'}
                        else:raise ValueError('default 必须为 true')
                    elif 'path' in request:
                        req_path = request['path']
                        if cmos_source.is_video_path(req_path):
                            jpeg, meta = cmos_source.read_first_video_frame_jpeg(req_path)
                            kind = 'video'
                        else:
                            jpeg = cmos_source.prepare_jpeg(req_path)
                            kind = 'image'
                        for guest_command in cmos_source.upload_commands(jpeg):live_serial(guest_command)
                        result={'type':'cmos_source','ok':True,'source':'custom','kind':kind,'name':Path(req_path).name}
                    elif request['default'] is True:
                        live_serial(cmos_source.reset_command())
                        result={'type':'cmos_source','ok':True,'source':'default-color-chart','name':'色卡'}
                    else:raise ValueError('default 必须为 true')
                except (OSError,RuntimeError,ValueError,subprocess.SubprocessError) as error:
                    _stop_cmos_streamer()
                    result={'type':'cmos_source','ok':False,'error':f'{type(error).__name__}: {error}'}
            elif action=='video_status' and set(request)=={'action'}:
                if video_recorder is not None:
                    result={'type':'video_status','ok':True,**video_recorder.snapshot()}
                else:
                    result={'type':'video_status','ok':True,'active':False,'saving':False,'frames':0,'elapsed_ms':0,'last_clip':None}
            elif action=='export_sd' and (set(request)=={'action'} or set(request)=={'action','shutdown_storage'} and request['shutdown_storage'] is True or set(request)=={'action','shutdown_storage','capture_ram'} and request['shutdown_storage'] is True and request['capture_ram'] is True):
                if sd_export is None:raise ValueError('This session has no virtual SD export profile')
                if request.get('capture_ram') and ram_capture is None:
                    raise ValueError('This session has no verified RAM migration build')
                if request.get('shutdown_storage') and os.environ.get('A7C2_STORAGE_PROFILE')!='product-single-disk-v1':
                    raise ValueError('Internal storage shutdown requires the active persistent profile')
                if input_session is not None:
                    released = input_session.handle({'action': 'camera_input', 'op': 'cleanup'})
                    if not released['ok']:
                        send_message(control, {'type': 'sd_export', 'ok': False,
                            'error': 'Camera contacts were not released: ' + released['input_state']['error'],
                            'input_state': released['input_state']})
                        continue
                if video_recorder is not None:
                    video_recorder.stop_if_recording()
                if shutter_submitted and late_passive is None and os.environ.get('A7C2_EE_PASSIVE_AFTER_SHUTTER')=='1':
                    try:
                        from ee_entry_snapshot import collect_passive,collect_group0
                        observed=collect_passive(live_serial,out)
                        group0=collect_group0(live_serial,out,observed)
                        (Path(observed['snapshot_dir'])/'group0.json').write_text(json.dumps(group0,indent=2)+'\n')
                        late_passive={'ok':observed.get('available',False),
                            'phase':'after natural shutter, before export quiesce',
                            'snapshot_dir':observed['snapshot_dir'],'group0':group0,
                            'threads_not_stopped':True,'current_blocker_proven':False}
                    except Exception as error:
                        late_passive={'ok':False,'phase':'after natural shutter, before export quiesce',
                                      'error':f'{type(error).__name__}: {error}','current_blocker_proven':False}
                    (out/'ee-post-shutter.json').write_text(json.dumps(late_passive,indent=2)+'\n')
                try:
                    result={'type':'sd_export',**sd_export()}
                    if result.get('ok') and request.get('shutdown_storage'):
                        from persistent_storage import prepare_shutdown
                        result['internal_storage']=(storage_shutdown or prepare_shutdown)(live_serial,out)
                        if request.get('capture_ram'):
                            result['ram_capture']=ram_capture()
                except Exception as error:result={'type':'sd_export','ok':False,'error':f'{type(error).__name__}: {error}'}
                if input_session is not None:result['input_state']=input_session.status()
                if late_passive is not None:result['post_shutter_observation']=late_passive
            elif action == 'snapshot' and set(request) == {'action'}:
                try:
                    if display_capture is not None:
                        result=display_capture()
                    else:
                        data = live_serial('/simulation/headless-osd-export')
                        result = snapshot_message(data, preview=verified_yc_preview(out))
                    if sd_card is not None:
                        result['sd_card'] = sd_card.status()
                    if os.environ.get('MENU_GUI_MODELS')=='virtual-inline-v1':
                        from gui_model_capture import decode_model_export
                        # A missing optional model snapshot must not hide the real LCD.
                        # Existing files still require the original export and strict decode.
                        presence=live_serial(
                            "if [ -e /tmp/gui-model-state.bin ]; then printf '\\nGUI_MODEL_STATE_PRESENT\\n'; "
                            "else printf '\\nGUI_MODEL_STATE_ABSENT\\n'; fi")
                        if re.search(rb'^GUI_MODEL_STATE_ABSENT\r?$',presence,re.M):
                            unavailable={'ok':False,'available':False,'publication_verified':False,
                                'reason':'no virtual GUI model snapshot has been published',
                                'scope':'optional auxiliary model only; original LCD evidence is preserved'}
                            (out/'gui-model-latest.json').write_text(json.dumps(unavailable,indent=2)+'\n')
                            result['gui_model_available']=False
                            result['gui_model_publication_verified']=False
                        else:
                            exported=live_serial('/simulation/gui-model-export')
                            try:
                                raw,models=decode_model_export(exported)
                            except (ValueError,IndexError) as error:
                                (out/'gui-model-latest.json').write_text(json.dumps({'ok':False,'error':str(error)})+'\n')
                                if display_capture is None:raise
                            else:
                                (out/'gui-model-latest.bin').write_bytes(raw)
                                (out/'gui-model-latest.json').write_text(json.dumps(models,indent=2)+'\n')
                                result['gui_model_available']=True
                                result['gui_model_publication_verified']=True
                except FirmwareFault as error:
                    if sd_export is None:raise
                    result={'type':'error','error':str(error)}
                except Exception as error:
                    if sd_export is None and not isinstance(error,(ValueError,IndexError)):raise
                    result = {'type': 'error', 'error': '快照校验失败：' + str(error)}
            elif (action=='position' and set(request)=={'action','key','position'}
                  and isinstance(request['key'],str) and request['key'] in KEYS
                  and isinstance(request['position'],str)):
                if os.environ.get('MENU_LIVE_KEY_FILE'):raise ValueError('旧邮箱不支持位置拨盘')
                command=key_command(request['key'],os.environ.get('MENU_LIVE_APP_INPUT')=='1',request['position'])
                result=submit_input(command,{'type':'position','key':request['key'],'position':request['position']})
            elif action == 'shutter_cycle' and set(request) == {'action'}:
                if os.environ.get('MENU_LIVE_KEY_FILE') or os.environ.get('MENU_LIVE_APP_INPUT') != '1':
                    raise ValueError('自然半按/全按序列仅已在app32输入通道验证')
                proof_path = out/'natural-shutter-request.json'
                proof = {'input_route': 'app32',
                         'records': [{'key': 'SHUTTER_HALF', 'status': 1},
                                     {'key': 'SHUTTER', 'status': 1},
                                     {'key': 'SHUTTER', 'status': 0},
                                     {'key': 'SHUTTER_HALF', 'status': 0}],
                         'submission_completed': False, 'input_submission_accepted': False,
                         'consumer_verified': False, 'still_capture_verified': False}
                proof_path.write_text(json.dumps(proof, indent=2)+'\n')
                result = submit_input(shutter_cycle_command(), {'type': 'shutter_cycle'})
                proof['submission_completed'] = True
                proof['input_submission_accepted'] = result.get('type') == 'shutter_cycle'
                shutter_submitted = shutter_submitted or proof['input_submission_accepted']
                if result.get('type') == 'error':
                    proof['error'] = result.get('error')
                proof_path.write_text(json.dumps(proof, indent=2)+'\n')
            elif action == 'key' and set(request) == {'action', 'key'} and request['key'] in KEYS:
                # Release is always attempted, even if press fails. The result covers both sends.
                command = (live_key_command(request['key']) if os.environ.get('MENU_LIVE_KEY_FILE')
                           else key_command(request['key'],os.environ.get('MENU_LIVE_APP_INPUT')=='1'))
                if command is None:
                    raise ValueError('该控件在当前输入通道未实现')
                prev_vtoggle = video_recorder.toggle_seq() if video_recorder is not None else 0
                result=submit_input(command,{'type':'key','key':request['key']})
                if result.get('type')=='error':send_message(control,result);continue
                if (video_recorder is not None and
                        (request['key'] == 'REC'
                         or (request['key'] == 'SHUTTER' and fast_shm_view.video_state()[3] != 1))):
                    result['video_recording'] = video_recorder.wait_after_rec_key(prev_vtoggle)
                if os.environ.get('MENU_INPUT_STACK_DIAG')=='1' and not input_stack_captured:
                    diagnostic = ('for p in /proc/[0-9]*; do '
                                  'if /bin/busybox grep -q /usr/lib/appFw.so "$p/maps" 2>/dev/null; then '
                                  'echo LIVE_APP_MAPS; /bin/busybox grep -E "appFw.so|libObj.so|libpthread|libosal" "$p/maps"; '
                                  'for t in "$p"/task/[0-9]*; do '
                                  'if /bin/busybox grep -qx AppFw "$t/comm" 2>/dev/null; then '
                                  'echo LIVE_INPUT_STACK_TID=${t##*/}; /simulation/menu-regs "${t##*/}"; fi; done; fi; done')
                    try:
                        data=live_serial(diagnostic)
                        (out / 'live-input-stack.txt').write_bytes(data)
                    except (FirmwareFault,OSError) as error:
                        if sd_export is None:raise
                        session_fault=str(error)
                        send_message(control,{'type':'error','error':str(error)});continue
                    input_stack_captured = True
            else:
                raise ValueError('非法私有控制命令')
            send_message(control, result)
      finally:
        _stop_cmos_streamer()
        if video_recorder is not None:
            video_recorder.close()
