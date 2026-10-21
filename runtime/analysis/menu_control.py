"""Loopback-only UI and one owned VM. Python stdlib HTTP, existing Pillow decoder."""
import argparse
import base64
from collections import deque
import fcntl
import importlib.util
import io
import json
import os
from pathlib import Path
import queue
import secrets
import signal
import socket
import subprocess
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from menu_live import KEYS, FirmwareFault,FirmwareMonitor, control_catalog, receive_message, send_message

BASE = Path(__file__).resolve().parent
ROOT = BASE.parents[1]
UI = ROOT / 'analysis/qemu-control'
SETTINGS_FIRMWARE_SHA='2ea02f7ecbc5bb917316fe8ef4ce5ffd87eb66efaae78ba2ce11420552df539b'
spec = importlib.util.spec_from_file_location('start_menu', BASE / 'start-menu.py')
launcher = importlib.util.module_from_spec(spec)
spec.loader.exec_module(launcher)


def native_display_environment(env, native_display):
    """Configure the native window without choosing the QEMU build.

    An isolated USB-Ethernet run names a candidate build that carries the sysbus
    xHCI controller. Overwriting that choice here makes `-device usb-net` fail
    with "No 'usb-bus' bus found", so an explicit build survives.
    """
    env.update(MENU_NATIVE_WINDOW='1', QEMU_NATIVE_DISPLAY=native_display,
               QEMU_NATIVE_INPUT='1')
    env.setdefault('QEMU_SYSTEM_DIR',
                   str(BASE.parent / 'sources/qemu-11.1.2/build-sony-ui'))
    return env


def terminate_owned(process):
    """Only a Popen created with start_new_session=True is passed here."""
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    try:
        process.wait(timeout=6)
    except subprocess.TimeoutExpired:
        pass
    # Descendants can outlive their leader; this group was allocated by our Popen.
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    process.wait(timeout=3)


class VM:
    def __init__(self, command=None, native_display=None,natural_boot=False,usb_net=False,instance=None):
        if native_display not in (None, 'none', 'gtk', 'sdl'):
            raise ValueError('不支持的原生显示后端')
        self.command = command or ['bash', str(BASE / 'run-menu-probe.sh')]
        self.mock = command is not None
        self.native_display = native_display
        # The isolated USB-Ethernet switch only exists when this run launched with
        # the candidate build and the derived launcher/DTB.
        self.usb_net = bool(usb_net)
        self.wifi = None
        self.natural_boot=natural_boot
        self.run_dir = ''
        self.custom_firmware=False
        self.sd_export=None
        self.card_seed=None
        self.shutdown_done=threading.Event()
        self.lock = threading.RLock()
        self.state = 'disconnected'
        self.error = ''
        self.firmware_fault=''
        self.cleanup_error=''
        self.owned_process=None
        self.snapshot = None
        self.png = None
        self.stale = True
        self.events = deque(maxlen=12)
        self.event_id = 0
        self.thread = None
        self.cancel = threading.Event()
        self.commands = queue.Queue(maxsize=8)
        self.busy = ''
        self.log_path = ''
        if instance is not None:
            from instance_lifecycle import Instance
            self.instance = Instance(instance)
        else:
            self.instance = None
        self.instance_lease = None
        self.settings_generation = None
        self.settings_saved = None

    def _release_instance_lease(self, process=None):
        if self.instance_lease is None:
            return
        if process is not None:
            if process.poll() is None:
                raise RuntimeError('实例仍有运行进程；保留生命周期租约')
            try:
                os.killpg(process.pid, 0)
            except ProcessLookupError:
                pass
            else:
                raise RuntimeError('实例进程组仍未退出；保留生命周期租约')
        self.instance_lease.__exit__(None, None, None)
        self.instance_lease = None

    def reset_instance(self, expected_generation, *, confirmed):
        """Host-only logical reset; guest Backup export/restore is separate."""
        with self.lock:
            if self.instance is None:
                raise ValueError('本控制器未绑定持久实例')
            if (self.instance_lease is not None or self.cleanup_error or self.owned_process is not None
                    or (self.thread and self.thread.is_alive())):
                raise ValueError('实例尚未完成停止和清理；不能重置')
            return self.instance.reset(expected_generation, confirmed=confirmed)

    def reset_configuration(self, *, confirmed):
        """Stopped-instance logical reinitialization; preserve virtual SD/history."""
        with self.lock:
            if self.instance is None:raise ValueError('本控制器未绑定持久实例')
            if (self.instance_lease is not None or self.cleanup_error or self.owned_process is not None
                    or (self.thread and self.thread.is_alive())):
                raise ValueError('请先 OFF 并等待相机保存与退出完成')
            from settings_instance import load_for_boot
            with self.instance.run_lease() as token:
                current=load_for_boot(token,SETTINGS_FIRMWARE_SHA)
            if current['generation'] is None:raise ValueError('当前相机尚无保存的配置')
            result=self.instance.reset(current['generation'],confirmed=confirmed)
            self.settings_generation=result['generation']
            self.settings_saved={k:v for k,v in result.items() if k!='data'}
            self.stale=True
            self.event('当前相机配置已重新初始化；虚拟SD与历史运行资料保留',kind='storage')
            return self.settings_saved

    def event(self, message, kind='status'):
        self.event_id += 1
        self.events.appendleft({'id': self.event_id, 'time': time.time(), 'message': message, 'kind': kind})

    def status(self):
        with self.lock:
            return dict(state=self.state, error=self.error, snapshot=self.snapshot, stale=self.stale,
                        busy=self.busy, pending=self.commands.qsize(), events=list(self.events),
                        keys=list(KEYS), controls=control_catalog(),
                        power_state='disconnected' if self.state == 'exited' else self.state,
                        can_start=not (self.thread and self.thread.is_alive()) and not (self.owned_process and self.owned_process.poll() is None),
                        can_stop=self.state in ('starting','running','faulted'),
                        native_display=self.native_display, mock=self.mock, custom_firmware=self.custom_firmware,sd_export=self.sd_export,
                        wifi=self.wifi, usb_net=self.usb_net,
                        settings_persistent=self.instance is not None,settings_generation=self.settings_generation,
                        log=self.log_path, run=self.run_dir)

    def start(self):
        with self.lock:
            if self.thread and self.thread.is_alive():
                raise ValueError('已有 VM 正在启动、运行或停止')
            if self.owned_process and self.owned_process.poll() is None:raise ValueError('上一VM尚未清理，请先重试关闭')
            if self.instance_lease is not None:
                raise ValueError('上次实例生命周期尚未结束；请先清理')
            if self.instance is not None:
                token = self.instance.run_lease()
                token.__enter__()
                self.instance_lease = token
            self.firmware_fault=self.cleanup_error=''
            self.wifi = None
            self.state, self.error, self.stale = 'starting', '', True
            self.run_dir = ''
            self.custom_firmware=False
            self.sd_export=None
            self.shutdown_done.clear()
            self.cancel.clear()
            self.commands = queue.Queue(maxsize=8)
            self.event('启动请求已接受；等待构建、锁与串口初始化完成')
            self.thread = threading.Thread(target=self._run, daemon=True)
            try:
                self.thread.start()
            except BaseException:
                self._release_instance_lease()
                self.state = 'disconnected'
                raise

    def enqueue(self, command):
        with self.lock:
            if self.state != 'running' and not (self.state=='faulted' and command=={'action':'export_sd'}):
                raise ValueError('VM 尚未运行')
            if command == {'action': 'snapshot'}:
                pass
            elif command=={'action':'export_sd'} and self.natural_boot and not self.mock:
                pass
            elif (isinstance(command,dict) and set(command)=={'action','enabled'}
                  and command['action']=='wifi' and type(command['enabled']) is bool):
                if not self.usb_net:
                    raise ValueError('本次运行未启用隔离网络')
            elif (isinstance(command,dict) and set(command)=={'action','key','position'}
                  and command['action']=='position' and isinstance(command['key'],str)
                  and isinstance(command['position'],str)):
                entry=control_catalog().get(command['key'],{})
                if not entry.get('available') or command['position'] not in entry.get('positions',{}):
                    raise ValueError('未知或不可用的拨盘位置')
            elif (isinstance(command, dict) and set(command) == {'action', 'key'}
                  and command['action'] == 'key' and isinstance(command['key'], str)
                  and command['key'] in KEYS):
                entry = control_catalog()[command['key']]
                if entry.get('positions'):raise ValueError('位置拨盘必须提供选择值')
                if not entry['available']:
                    raise ValueError(entry['unavailable_reason'])
            else:
                raise ValueError('未知按键或控制命令')
            try:
                self.commands.put_nowait(command)
            except queue.Full:
                raise ValueError('命令队列已满，请稍后重试') from None

    def stop(self):
        with self.lock:
            if self.state not in ('starting','running','faulted','stopping'):
                raise ValueError('没有本控制台正在运行的 VM')
            if self.state=='stopping':return
            if self.state in ('running','faulted') and self.natural_boot and not self.mock:
                try:self.commands.put_nowait({'action':'export_sd','_shutdown':True})
                except queue.Full:raise ValueError('命令队列已满；尚未关机，请稍后重试') from None
                self.shutdown_done.clear()
                self.state='stopping'
                self.event('正在刷新并保存虚拟SD；保存成功后关闭VM')
                return
            self.state, self.stale = 'stopping', True
            self.cancel.set()
            self.event('停止请求已接受；正在清理本控制台创建的 VM')

    def close(self):
        with self.lock:
            retry_cleanup=self.cleanup_error
            owned=self.owned_process
        if retry_cleanup:
            try:
                if owned is not None:terminate_owned(owned)
                with self.lock:self._release_instance_lease(owned)
            except (OSError,subprocess.TimeoutExpired) as error:
                raise RuntimeError('VM清理仍失败：'+str(error)) from error
            with self.lock:
                self.cleanup_error='';self.owned_process=None;self.state='exited'
                self.event('本控制台的VM重试清理完成')
            return
        with self.lock:
            save=self.natural_boot and not self.mock and self.state in ('running','faulted','stopping')
        if save:
            self.stop()
            if not self.shutdown_done.wait(timeout=180):
                raise RuntimeError('SD保存尚未完成；VM保留运行，请稍后重试')
            with self.lock:
                if self.state in ('running','faulted'):raise RuntimeError('SD保存失败；VM保留运行：'+self.error)
                if self.cleanup_error:raise RuntimeError('VM清理失败：'+self.cleanup_error)
                if self.state!='exited':raise RuntimeError('SD保存/关闭未完成：'+self.error)
        with self.lock:
            self.cancel.set()
        if self.thread:
            self.thread.join(timeout=12)
            if self.thread.is_alive():raise RuntimeError('VM尚未完成退出；窗口保留')
        with self.lock:
            if self.cleanup_error:raise RuntimeError('VM清理失败：'+self.cleanup_error)

    def _run(self):
        process = None
        monitor = None
        parent, child = socket.socketpair()
        # run-menu-probe.sh reserves fd9 for its build/runtime flock.
        inherited = socket.socket(fileno=fcntl.fcntl(child.fileno(), fcntl.F_DUPFD_CLOEXEC, 20))
        child.close()
        child = inherited
        log = None
        try:
            import tempfile
            logs = BASE / 'ui-runs'
            logs.mkdir(exist_ok=True)
            fd, name = tempfile.mkstemp(prefix='ui-', suffix='.log', dir=logs)
            log = os.fdopen(fd, 'wb')
            with self.lock:
                self.log_path = name
            env = launcher.profile_environment(os.environ,natural_boot=self.natural_boot)
            if self.instance_lease is not None and not self.mock and self.natural_boot:
                from settings_instance import load_for_boot
                current=load_for_boot(self.instance_lease,SETTINGS_FIRMWARE_SHA)
                self.settings_generation=current['generation']
                env['A7C2_SETTINGS_PERSIST']='1'
                if current['state']=='backup':
                    env['A7C2_SETTINGS_RESTORE']=str(Path(self.instance.path)/('generation-'+current['generation'])/'backup.bin')
                    env['A7C2_SETTINGS_RESTORE_SHA']=current['sha256']
            if self.usb_net and not self.mock and env.get('MENU_USB_NET') != '1':
                from usb_network import prepare_profile
                env.pop('A7C2_USB_NET_SELFTEST', None)
                env.update(prepare_profile(BASE))
            if self.card_seed:env['A7C2_SD_IMAGE']=str(self.card_seed)
            if self.native_display is not None:
                native_display_environment(env, self.native_display)
            env['MENU_CONTROL_FD'] = str(child.fileno())
            env['MENU_CONTROL_OWNER_PID']=str(os.getpid())
            process = subprocess.Popen(self.command, env=env, cwd=BASE.parent,
                                       stdout=log, stderr=subprocess.STDOUT,
                                       start_new_session=True, pass_fds=(child.fileno(),))
            with self.lock:self.owned_process=process
            child.close()
            reply = receive_message(parent, timeout=300, cancelled=self.cancel.is_set)
            if reply.get('type') != 'ready':
                raise RuntimeError('VM 初始化确认无效')
            if not self.mock:
                run = Path(reply.get('run', '')).resolve()
                if run.parent != (BASE / 'menu-runs').resolve():
                    raise RuntimeError('VM 返回的运行目录不合法')
                runtime_identity=json.loads((run/'runtime-manifest.json').read_text())
                self.custom_firmware=bool((runtime_identity.get('overwrite') or {}).get('entries'))
                monitor = FirmwareMonitor(run / 'console.log')

            def cancelled():
                if self.cancel.is_set():
                    return True
                if monitor:
                    try:monitor.check()
                    except FirmwareFault as error:
                        if not self.natural_boot:raise
                        with self.lock:
                            if self.firmware_fault!=str(error):self.event('固件异常；VM保留，仅允许保存/关闭：'+str(error))
                            self.firmware_fault=self.error=str(error);self.stale=True
                            if self.state!='stopping':self.state='faulted'
                return False

            cancelled()
            with self.lock:
                if self.cancel.is_set():
                    return
                self.state = 'faulted' if self.firmware_fault else 'running'
                self.run_dir = reply.get('run', '')
                self.event('串口初始化已完成；' + ('等待本次已校验快照' if self.native_display is None else '原生画面由 ramfb 更新'))
                if self.native_display is None:
                    self.commands.put_nowait({'action': 'snapshot'})
            while not cancelled():
                if process.poll() is not None:
                    if process.returncode == 0:
                        with self.lock:
                            self.state, self.stale = 'exited', True
                            self.event('QEMU 窗口已关闭，VM 已退出')
                        break
                    raise RuntimeError('VM 进程意外退出，返回码 ' + str(process.returncode))
                try:
                    command = self.commands.get(timeout=.2)
                except queue.Empty:
                    continue
                with self.lock:
                    self.busy = command['action']
                shutdown=bool(command.pop('_shutdown',False))
                send_message(parent, command)
                saving=command['action']=='export_sd'
                reply=receive_message(parent,timeout=None if saving else 120,cancelled=None if saving else cancelled)
                with self.lock:
                    if reply.get('type') == 'error':
                        self.error = str(reply.get('error', 'VM 操作失败'))
                        self.stale = True
                        self.event(self.error)
                    elif command['action'] == 'snapshot' and reply.get('type') == 'snapshot':
                        from PIL import Image
                        png = base64.b64decode(reply['png'], validate=True)
                        with Image.open(io.BytesIO(png)) as image:
                            if image.format != 'PNG' or image.size != (640, 480):
                                raise ValueError('快照 PNG 格式错误')
                            image.verify()
                        info = reply['info']
                        self.png = png
                        self.snapshot = {'sequence': info['sequence'], 'pixel_source_seq': info['pixel_source_seq'],
                                         'sha256': info['sha256'], 'captured_at': reply['captured_at'],
                                         'number': (self.snapshot or {}).get('number', 0) + 1}
                        if 'source' in info:self.snapshot['source']=info['source']
                        self.stale, self.error = False, ''
                        self.event(f'快照 #{self.snapshot["number"]} 已校验；事务 {info["sequence"]}')
                    elif command['action'] == 'key' and reply == {'type': 'key', 'key': command['key']}:
                        self.event(command['key'] + '：输入已提交', kind='input')
                    elif command['action']=='position' and reply=={'type':'position','key':command['key'],'position':command['position']}:
                        self.event(command['key']+' '+command['position']+'：位置输入已提交',kind='input')
                    elif command['action']=='wifi' and reply.get('type')=='wifi':
                        self.wifi = {key: value for key, value in reply.items() if key != 'type'}
                        if reply.get('ok'):
                            self.event('Wi-Fi 已开启；宿主 ping 通' if reply.get('enabled')
                                       else 'Wi-Fi 已关闭；宿主 ping 不通', kind='network')
                        else:
                            self.error = str(reply.get('error', 'unknown'))
                            self.event('Wi-Fi 切换未完成：' + self.error, kind='network')
                    elif command['action']=='export_sd' and reply.get('type')=='sd_export':
                        if reply.get('ok') and self.instance_lease is not None and not self.mock:
                            try:
                                from settings_instance import publish_snapshot
                                self.settings_saved=publish_snapshot(self.instance_lease,self.run_dir,
                                    reply.get('settings') or {},SETTINGS_FIRMWARE_SHA,self.settings_generation)
                                self.settings_generation=self.settings_saved['generation']
                            except (OSError,ValueError,RuntimeError) as error:
                                reply={**reply,'ok':False,'error':'配置发布失败；VM保留：'+str(error)}
                        self.sd_export=reply
                        if reply.get('ok'):self.card_seed=Path(self.run_dir)/'SD/card.img'
                        self.event('虚拟SD已保存' if reply.get('ok') else '虚拟SD导出失败：'+str(reply.get('error','unknown')),
                                   kind='storage')
                    else:
                        raise RuntimeError('VM 返回不匹配，未将操作视为成功')
                    if shutdown:
                        if reply.get('type')=='sd_export' and reply.get('ok'):
                            self.cancel.set()
                        else:
                            self.state='faulted' if self.firmware_fault else 'running'
                            self.error='SD保存失败；VM未关闭：'+str(reply.get('error','unknown'))
                            self.event(self.error,kind='storage')
                            self.shutdown_done.set()
                    self.busy = ''
        except Exception as error:
            if monitor and not self.cancel.is_set():
                try:
                    monitor.check()
                except (OSError, RuntimeError) as fault:
                    error = fault
            with self.lock:
                if not self.cancel.is_set():
                    self.error = str(error)
                    self.state = 'error'
                    self.event('VM 错误：' + self.error)
        finally:
            parent.close()
            child.close()
            cleanup_error = None
            if process is not None:
                try:
                    terminate_owned(process)
                    with self.lock:self._release_instance_lease(process)
                except (OSError, subprocess.TimeoutExpired) as error:
                    cleanup_error = str(error)
                except RuntimeError as error:
                    cleanup_error = str(error)
            else:
                with self.lock:self._release_instance_lease()
            if log is not None:
                log.close()
            with self.lock:
                self.busy, self.stale = '', True
                while not self.commands.empty():
                    self.commands.get_nowait()
                if cleanup_error:
                    self.cleanup_error=cleanup_error
                    self.state, self.error = 'error', 'VM 清理失败：' + cleanup_error
                    self.event(self.error)
                elif self.cancel.is_set():
                    self.owned_process=None
                    self.state = 'exited'
                    self.event('本控制台的 VM 已退出')
                else:self.owned_process=None
                self.shutdown_done.set()


class Server(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, vm, port=0):
        self.vm, self.token = vm, secrets.token_urlsafe(32)
        super().__init__(('127.0.0.1', port), Handler)
        self.host = '127.0.0.1:' + str(self.server_port)
        self.origin = 'http://' + self.host


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def setup(self):
        super().setup()
        self.connection.settimeout(5)

    def respond(self, status, body, kind='application/json; charset=utf-8', download=False, number=None):
        if not isinstance(body, bytes):
            body = json.dumps(body, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header('Content-Type', kind)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Referrer-Policy', 'no-referrer')
        self.send_header('Cross-Origin-Resource-Policy', 'same-origin')
        self.send_header('Content-Security-Policy', "default-src 'none'; img-src 'self' blob:; style-src 'self'; script-src 'self'; connect-src 'self'; base-uri 'none'; frame-ancestors 'none'; form-action 'none'")
        if download:
            self.send_header('Content-Disposition', 'attachment; filename="a7c2-snapshot.png"')
        if number is not None:
            self.send_header('X-Snapshot-Number', str(number))
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def authorized(self, api=False, mutation=False):
        if self.headers.get_all('Host') != [self.server.host]:
            return False
        origins = self.headers.get_all('Origin')
        if origins is not None and origins != [self.server.origin]:
            return False
        if mutation and origins != [self.server.origin]:
            return False
        if self.headers.get('Sec-Fetch-Site') == 'cross-site':
            return False
        return not api or secrets.compare_digest(self.headers.get('X-Session-Token', '').encode(), self.server.token.encode())

    def do_GET(self):
        api = self.path.startswith('/api/')
        if not self.authorized(api=api):
            return self.respond(403, {'error': '拒绝无效 Host、Origin 或会话令牌'})
        if self.path == '/api/state':
            return self.respond(200, self.server.vm.status())
        if self.path in ('/api/snapshot', '/api/save'):
            with self.server.vm.lock:
                png = self.server.vm.png
                number = (self.server.vm.snapshot or {}).get('number')
            if png is None:
                return self.respond(409, {'error': '尚无本次控制台已校验快照'})
            return self.respond(200, png, 'image/png', self.path == '/api/save', number)
        files = {'/': (UI / 'index.html', 'text/html; charset=utf-8'),
                 '/app.js': (UI / 'app.js', 'text/javascript; charset=utf-8'),
                 '/style.css': (UI / 'style.css', 'text/css; charset=utf-8')}
        if self.path not in files:
            return self.respond(404, {'error': '接口不存在'})
        path, kind = files[self.path]
        try:
            return self.respond(200, path.read_bytes(), kind)
        except OSError:
            return self.respond(404, {'error': '资源不可用'})

    def do_POST(self):
        if not self.authorized(api=True, mutation=True):
            return self.respond(403, {'error': '拒绝无效 Host、Origin 或会话令牌'})
        if self.path not in ('/api/start', '/api/stop', '/api/snapshot', '/api/key'):
            return self.respond(404, {'error': '接口不存在'})
        lengths = self.headers.get_all('Content-Length') or []
        if self.headers.get('Transfer-Encoding') or len(lengths) != 1 or not lengths[0].isdigit() or int(lengths[0]) > 256:
            return self.respond(413, {'error': '请求长度无效或超过 256 字节'})
        if self.headers.get('Content-Type') != 'application/json':
            return self.respond(415, {'error': '仅接受 application/json'})
        try:
            payload = json.loads(self.rfile.read(int(lengths[0])))
            if self.path == '/api/key':
                if not isinstance(payload, dict) or set(payload) != {'key'} or not isinstance(payload['key'], str) or payload['key'] not in KEYS:
                    raise ValueError('未知或尚无键码的按键，或参数无效')
                self.server.vm.enqueue({'action': 'key', 'key': payload['key']})
            else:
                if payload != {}:
                    raise ValueError('该接口不接受参数')
                if self.path == '/api/start':
                    self.server.vm.start()
                elif self.path == '/api/stop':
                    self.server.vm.stop()
                else:
                    self.server.vm.enqueue({'action': 'snapshot'})
        except (ValueError, UnicodeError) as error:
            return self.respond(400, {'error': str(error)})
        return self.respond(202, {'accepted': True})


def main():
    parser = argparse.ArgumentParser(description='本机 QEMU 常驻控制台；关闭此进程即停止其 VM')
    parser.add_argument('--no-open', action='store_true')
    parser.add_argument('--port', type=int, default=0)
    parser.add_argument('--natural-boot',action='store_true',help='自然首设+R M2文件服务；不强制菜单')
    args = parser.parse_args()
    vm = VM(natural_boot=args.natural_boot)
    server = Server(vm, args.port)
    url = server.origin + '/#' + server.token
    print('控制台地址（含本次会话令牌，请勿分享）：' + url, flush=True)
    print('按 Ctrl+C 退出服务并清理本控制台的 VM。', flush=True)
    def stop(signum, frame):
        raise KeyboardInterrupt
    signal.signal(signal.SIGTERM, stop)
    try:
        if not args.no_open:
            webbrowser.open(url)
        server.serve_forever(poll_interval=.2)
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        vm.close()


if __name__ == '__main__':
    main()
