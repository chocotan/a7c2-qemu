#!/usr/bin/env python3
"""Coordinate the owned HDMI VM with the native UPM observer and its data mailbox."""
from pathlib import Path
import importlib.util
import json
import os
import re
import socket
import subprocess
import sys
import threading
import time

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE))
import hdmi_upm_watch


def gdbserver(run):
    listener = run / hdmi_upm_watch.SOCKET
    if listener.is_socket() and not listener.is_symlink() and listener.stat().st_uid == os.getuid():
        os.chmod(listener, 0o600)
        return 'dedicated startup Unix GDB listener'
    path = run / 'hdmi-upm-control.sock'
    with socket.socket(socket.AF_UNIX) as client:
        client.settimeout(5)
        directory = os.open(run, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            client.connect(f'/proc/self/fd/{directory}/hdmi-upm-control.sock')
        finally:
            os.close(directory)
        with client.makefile('rwb') as stream:
            def receive():
                raw = stream.readline(65537)
                if len(raw) > 65536 or not raw.endswith(b'\n'):
                    raise ValueError('invalid owned QMP reply')
                return json.loads(raw)
            if 'QMP' not in receive():
                raise ValueError('invalid owned QMP greeting')
            def execute(command, ident, arguments=None):
                request = {'execute': command, 'id': ident}
                if arguments is not None:
                    request['arguments'] = arguments
                stream.write((json.dumps(request) + '\n').encode())
                stream.flush()
                for _ in range(32):
                    response = receive()
                    if 'event' in response:
                        continue
                    if response.get('id') != ident or 'error' in response:
                        raise ValueError(str(response))
                    return response['return']
                raise ValueError('QMP response event limit')
            execute('qmp_capabilities', 1)
            name = run / hdmi_upm_watch.SOCKET
            result = execute('human-monitor-command', 2,
                             {'command-line': 'gdbserver unix:/out/' + hdmi_upm_watch.SOCKET + ',server=on,wait=off'})
            if not name.is_socket():
                raise ValueError('Unix GDB listener was not created: ' + str(result))
            os.chmod(name, 0o600)
            return result


def observe(run, finished, result):
    watcher = None
    try:
        console = run / 'console.log'
        deadline = time.monotonic() + 210
        while not finished.is_set() and time.monotonic() < deadline:
            data = console.read_bytes() if console.exists() else b''
            matches = re.findall(rb'OBS FULL_HDMI_UPM_MAILBOX_INIT ([^\r\n]+)', data)
            bindings = []
            for row in matches:
                fields = dict(item.split(b'=', 1) for item in row.split() if b'=' in item)
                needed = (b'pid', b'physical', b'nonce', b'upm_text', b'osal_text')
                if all(k in fields for k in needed):
                    bindings.append(tuple(int(fields[k], 0) for k in needed))
            if bindings:
                if len(set(bindings)) != 1:
                    raise ValueError('multiple native UPM mailbox identities')
                pid, physical, nonce, upm, osal = bindings[0]
                manifest = json.loads((run / 'runtime-manifest.json').read_text())
                result['GDB_listener'] = gdbserver(run)
                watcher = hdmi_upm_watch.start(run, manifest['host_control_owner_pid'],
                    {'upm': upm, 'osal_uipc': osal}, mailbox={'phys': physical, 'nonce': nonce, 'pid': pid})
                result['armed'] = True
                print('HDMI_UPM_NATIVE_OBSERVER_ARMED', run.name, flush=True)
                break
            finished.wait(.05)
        if watcher is None and not finished.is_set():
            raise TimeoutError('no verified native UPM mailbox appeared')
        while watcher is not None and not finished.wait(.1):
            receipts = hdmi_upm_watch.read_receipts(run)
            result['receipts'] = receipts
            # Receipt JSON precedes its mailbox commit; only normal GDB exit
            # guarantees both data deliveries and the detach path finished.
            if watcher.process.poll() is not None:
                break
    except BaseException as error:
        if getattr(error, 'hdmi_upm_watcher', None) is not None:
            watcher = error.hdmi_upm_watcher
            result['startup_cleanup'] = error.hdmi_upm_cleanup
        result['error'] = str(error)
        print('HDMI_UPM_NATIVE_OBSERVER_ERROR', str(error), flush=True)
    finally:
        if watcher is not None:
            try:
                result['cleanup'] = result.get('startup_cleanup') or watcher.stop()
                if not result['cleanup']['safe_to_close']:
                    result['retained_watcher'] = watcher
                    result['retained_debugger_pid'] = watcher.process.pid if watcher.process else None
            except BaseException as error:
                result['retained_watcher'] = watcher
                result['cleanup_error'] = str(error)
        if run.exists():
            public = {key: value for key, value in result.items() if key != 'retained_watcher'}
            (run / 'hdmi-upm-coordinator.json').write_text(json.dumps(public, indent=2) + '\n')


def main():
    if sys.argv[1:] not in ([], ['--all'], ['--cp-audit'], ['--cp302c'], ['--cp302c-diagnostic'], ['--cp-notification'], ['--cp-capture-format'], ['--cp-startup-controls'], ['--cp-ee-controls'], ['--cp-movie-format']):
        raise ValueError('only --all, --cp-audit, --cp302c, --cp302c-diagnostic, --cp-notification, --cp-capture-format, --cp-startup-controls, --cp-ee-controls or --cp-movie-format is supported')
    target = ('cp-movie-format' if sys.argv[1:] == ['--cp-movie-format'] else
              'cp-ee-controls' if sys.argv[1:] == ['--cp-ee-controls'] else
              'cp-startup-controls' if sys.argv[1:] == ['--cp-startup-controls'] else
              'cp-capture-format' if sys.argv[1:] == ['--cp-capture-format'] else
              'cp-notification' if sys.argv[1:] == ['--cp-notification'] else
              'cp302c-diagnostic' if sys.argv[1:] == ['--cp302c-diagnostic'] else
              'cp302c' if sys.argv[1:] == ['--cp302c'] else
              'cp-audit' if sys.argv[1:] == ['--cp-audit'] else 'all' if sys.argv[1:] else 'hdmi')
    command = ['python3', '-B', str(BASE / 'scratch/run-last-graph.py'), target]
    child = subprocess.Popen(command, cwd=BASE, stdout=subprocess.PIPE, text=True, bufsize=1)
    done, thread, result = threading.Event(), None, {'armed': False, 'capture_verified': False}
    try:
        for line in child.stdout:
            print(line, end='', flush=True)
            if line.startswith('GTK_INPUT_RUN '):
                run = Path(line.split(None, 1)[1].strip())
                if run.parent != BASE / 'menu-runs' or thread is not None:
                    raise ValueError('unexpected owned run identity')
                thread = threading.Thread(target=observe, args=(run, done, result), daemon=False)
                thread.start()
        rc = child.wait()
    finally:
        done.set()
        if thread is not None:
            thread.join(timeout=30)
            if thread.is_alive():
                raise RuntimeError('native observer cleanup did not complete')
    return rc


if __name__ == '__main__':
    raise SystemExit(main())
