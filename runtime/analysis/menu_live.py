"""Private live-control transport and serial commands; no caller-supplied shell."""
import base64
import io
import json
import os
import re
import secrets
import select
import socket
import time
import hashlib

from pathlib import Path

from headless_osd_capture import decode_export, HEADER, METADATA

MAX_MESSAGE = 2 * 1024 * 1024
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
    'REAR_LEFT': dict(label='后拨轮左转', code='0x10000013', status='0xfffffc00',
                      native='<', shortcuts=['PageUp'], note='单次 -1024；原P档HUD已见曝光补偿0.0→-0.3，其它上下文待验'),
    'REAR_RIGHT': dict(label='后拨轮右转', code='0x10000013', status='0x400',
                       native='>', shortcuts=['PageDown'], note='单次 +1024；原P档HUD已见曝光补偿-0.3→0.0，其它上下文待验'),
    'CONTROL_LEFT': dict(label='控制轮左转',code='0x1000001d',status='0xfffffc00',note='原始码→UIBIZ 2f6已核；拍摄上下文功能未实测'),
    'CONTROL_RIGHT': dict(label='控制轮右转',code='0x1000001d',status='0x400',note='原始码→UIBIZ 2f6已核；拍摄上下文功能未实测'),
    'FRONT_LEFT': dict(label='前拨轮左转',code='0x1000001c',status='0xfffffc00',note='原始码→UIBIZ 2f5已核；拍摄上下文功能未实测'),
    'FRONT_RIGHT': dict(label='前拨轮右转',code='0x1000001c',status='0x400',note='原始码→UIBIZ 2f5已核；拍摄上下文功能未实测'),
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
    'REC': dict(label='REC',code='0x1f0',note='原始码→UIBIZ 1c→02150012已核；录像及文件输出待实现'),
    'MODE_STILL':dict(label='照片档',code='0x71c9',status='1',note='原2240002→switch0合法位置已核；实际照片档切换待验'),
    'MODE_MOVIE':dict(label='录像档',code='0x71c9',status='2',note='原2240002→switch1合法位置已核；不是开始录像，功能待验'),
    'MODE_SQ':dict(label='S&Q档',code='0x71c9',status='3',note='原2240002→switch2合法位置已核；不是编码或慢动作已完成'),
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


class FirmwareFault(RuntimeError):
    pass


class FirmwareMonitor:
    """Follow the complete console, including faults between two commands."""
    def __init__(self, console):
        self.console = console
        self.offset = 0
        self.tail = b''
        self.failed = False

    def check(self):
        if self.failed:
            raise FirmwareFault('相机固件发生异常，已停止接收按键；详情见 console.log')
        with self.console.open('rb') as reader:
            if os.fstat(reader.fileno()).st_size < self.offset:
                self.offset, self.tail = 0, b''
            reader.seek(self.offset)
            while chunk := reader.read(65536):
                self.offset += len(chunk)
                data = self.tail + chunk.replace(b'\r', b'')
                if re.search(rb'(?:^|\n)(?:Entering exception monitor\.|Exception>|OBS GUI_MODEL_FAILED )', data):
                    self.failed = True
                    raise FirmwareFault('相机固件发生异常，已停止接收按键；详情见 console.log')
                self.tail = data[-128:]


def connect_in_run(sock, directory, name):
    # Linux AF_UNIX paths are short; the run directory may live in a long checkout.
    fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
    try:
        sock.connect(f'/proc/self/fd/{fd}/{name}')
    finally:
        os.close(fd)


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
    alias = Path('/var/tmp')/f'a7c2-usb-{out.name[-8:]}'
    if alias.exists() or alias.is_symlink():
        if not alias.is_symlink() or alias.lstat().st_uid != os.getuid() or alias.readlink() != out:
            raise ValueError(f'Refusing unrelated socket alias: {alias}')
        alias.unlink()
    alias.symlink_to(out)
    return alias/'ethernet.sock', alias


def serial_command(proc, console, command, timeout=90, monitor=None,allow_faulted_cleanup=False):
    """Ignore echoed commands/prompts and require this command's exact RC sentinel."""
    if getattr(proc, '_menu_serial_desynchronized', False):
        raise RuntimeError('Serial transaction boundary lost; retain VM for explicit recovery, no further commands')
    monitor = None if allow_faulted_cleanup else (monitor or FirmwareMonitor(console))
    if monitor:monitor.check()
    marker = 'MENU_DIAG_COMMAND_DONE_' + secrets.token_hex(12)
    wire = (command + "; rc=$?; printf '\\n" + marker + ":%s\\n' \"$rc\"\n").encode()
    if any(len(line) > 1000 for line in wire.split(b'\n')):
        raise ValueError('Guest serial physical command line exceeds safe1000-byte bound; split the command')
    # Live console writers use O_APPEND; discard old exports only between commands.
    if console.stat().st_size > 16 * 1024 * 1024:
        with console.open('r+b') as old:
            old.truncate(0)
    with console.open('rb') as reader:
        reader.seek(0, 2)
        proc.stdin.write(wire)
        proc.stdin.flush()
        data = bytearray()
        deadline = None if timeout is None else time.monotonic() + timeout
        while deadline is None or time.monotonic() < deadline:
            if monitor:monitor.check()
            data.extend(reader.read(65536))
            if len(data) > 8 * 1024 * 1024:
                raise RuntimeError('单次串口输出超过限制')
            clean = clean_console(bytes(data))
            if not allow_faulted_cleanup and b'Exception>' in clean:
                raise RuntimeError('固件进入异常监视器')
            match = re.search(rb'\n' + marker.encode() + rb':([0-9]+)\n', clean)
            if match:
                if int(match[1]):
                    raise RuntimeError('guest 命令失败，返回码 ' + match[1].decode())
                return bytes(data)
            if proc.poll() is not None:
                raise RuntimeError('VM 进程提前退出')
            time.sleep(.05)
    proc._menu_serial_desynchronized = True
    raise TimeoutError('串口命令缺少完成标记；停止 VM 以避免后续命令交错')


def snapshot_message(console):
    from PIL import Image
    raw, info = decode_export(console)
    pixels = raw[HEADER + METADATA:]
    rgba = bytearray(640 * 480 * 4)
    for i in range(640 * 480):
        value = pixels[i * 2] | pixels[i * 2 + 1] << 8
        rgba[i * 4:i * 4 + 4] = bytes((value >> 12, value >> 8 & 15, value >> 4 & 15, value & 15))
    rgba = bytes(channel * 17 for channel in rgba)
    image = Image.frombytes('RGBA', (640, 480), rgba)
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


def run_live(proc, out, descriptor, display_capture=None, sd_export=None, network=None, sd_card=None):
    monitor = FirmwareMonitor(out / 'console.log')
    input_stack_captured = False
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
    with socket.socket(fileno=descriptor) as control:
        # Barrier follows the entire queued setup, not a shell prompt or stdout "ready".
        serial_command(proc, out / 'console.log', 'true', monitor=monitor)
        if os.environ.get('A7C2_MEDIA_INIT_WATCH') == '1' and os.environ.get('MENU_GUI_MODELS') == 'virtual-inline-v1':
            wait_initial_model_commit(proc, out/'console.log')
        card_state=sd_card.status() if sd_card is not None else None
        send_message(control, {'type': 'ready', 'run': str(out), 'sd_card': card_state})
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
            if not select.select([control], [], [], .5)[0]:
                continue
            request = receive_message(control, timeout=5)
            action = request.get('action')
            if fault and action!='export_sd':
                send_message(control,{'type':'error','error':fault});continue
            if sd_card is not None and sd_card.input_blocked() and action not in ('sd_card','snapshot','export_sd'):
                raise ValueError('SD transition has no terminal observation; camera input is paused')
            if (action=='sd_card' and set(request)=={'action','present'}
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
            elif action=='export_sd' and set(request)=={'action'}:
                if sd_export is None:raise ValueError('This session has no virtual SD export profile')
                try:result={'type':'sd_export',**sd_export()}
                except Exception as error:result={'type':'sd_export','ok':False,'error':f'{type(error).__name__}: {error}'}
            elif action == 'snapshot' and set(request) == {'action'}:
                try:
                    if display_capture is not None:
                        result=display_capture()
                    else:
                        data = live_serial('/simulation/headless-osd-export')
                        result = snapshot_message(data)
                    if sd_card is not None:
                        result['sd_card'] = sd_card.status()
                    if os.environ.get('MENU_GUI_MODELS')=='virtual-inline-v1':
                        from gui_model_capture import decode_model_export
                        exported=live_serial('/simulation/gui-model-export')
                        try:
                            raw,models=decode_model_export(exported)
                        except (ValueError,IndexError) as error:
                            (out/'gui-model-latest.json').write_text(json.dumps({'ok':False,'error':str(error)})+'\n')
                            if display_capture is None:raise
                        else:
                            (out/'gui-model-latest.bin').write_bytes(raw)
                            (out/'gui-model-latest.json').write_text(json.dumps(models,indent=2)+'\n')
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
            elif action == 'key' and set(request) == {'action', 'key'} and request['key'] in KEYS:
                # Release is always attempted, even if press fails. The result covers both sends.
                command = (live_key_command(request['key']) if os.environ.get('MENU_LIVE_KEY_FILE')
                           else key_command(request['key'],os.environ.get('MENU_LIVE_APP_INPUT')=='1'))
                if command is None:
                    raise ValueError('该控件在当前输入通道未实现')
                result=submit_input(command,{'type':'key','key':request['key']})
                if result.get('type')=='error':send_message(control,result);continue
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
