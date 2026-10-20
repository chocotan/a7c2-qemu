#!/usr/bin/env python3
"""Bare QEMU GTK smoke check on a private Xvfb, never the user's desktop."""
import argparse
import json
import os
import re
from pathlib import Path
import socket
import subprocess
import tempfile
import time

SOURCE = Path(__file__).resolve().parent
BASE = SOURCE / 'native-controls-check'
BASE.mkdir(exist_ok=True)
BINARY = Path(os.environ.get('QEMU_TEST_BINARY', str(SOURCE.parent / 'sources/qemu-11.1.2/build-sony-ui/qemu-system-aarch64')))


def await_file(path, process):
    deadline = time.monotonic() + 5
    while not path.exists():
        assert process.poll() is None, 'child exited before socket appeared'
        assert time.monotonic() < deadline, path
        time.sleep(.02)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--capture-only', action='store_true')
    parser.add_argument('--ordinary', action='store_true')
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix='sony-gtk-check-') as temp:
        out = Path(temp)
        read_fd, write_fd = os.pipe()
        xvfb = subprocess.Popen(['Xvfb', '-displayfd', str(write_fd), '-screen',
                                 '0', '2560x1440x24', '-nolisten', 'tcp'],
                                pass_fds=(write_fd,), stderr=subprocess.DEVNULL)
        os.close(write_fd)
        with os.fdopen(read_fd) as stream:
            display = ':' + stream.readline().strip()
        env = dict(os.environ, DISPLAY=display, GDK_BACKEND='x11',
                   NO_AT_BRIDGE='1')

        def xdo(*items):
            return subprocess.check_output(['xdotool', *map(str, items)],
                                           env=env, text=True).strip()

        command = [str(BINARY), '-machine', 'virt', '-cpu', 'cortex-a35',
                   '-m', '128M', '-nodefaults', '-nic', 'none',
                   '-display', 'gtk,gl=off,show-cursor=on',
                   '-monitor', 'none', '-serial', 'none',
                   '-device', 'loader,addr=0x40000000,data=0x14000000,data-len=4,cpu-num=0',
                   '-device', 'ramfb,id=a7c2-screen',
                   '-qmp', f'unix:{out}/qmp.sock,server=on,wait=off', '-S']
        if not args.ordinary:
            command += ['-chardev', f'socket,id=keys,path={out}/keys.sock,server=on,wait=off',
                        '-device', 'sony-ui-input,id=sony-controls,chardev=keys,display=a7c2-screen']
        qemu = None
        keys = socket.socket(socket.AF_UNIX)
        try:
            log_name = 'ordinary-gtk.log' if args.ordinary else 'bare-gtk.log'
            with (BASE / log_name).open('wb') as log:
                qemu = subprocess.Popen(command, env=env, stdout=log,
                                        stderr=subprocess.STDOUT)
                await_file(out / 'qmp.sock', qemu)
                if not args.ordinary:
                    await_file(out / 'keys.sock', qemu)
                    keys.connect(str(out / 'keys.sock'))
                    keys.settimeout(.3)
                with socket.socket(socket.AF_UNIX) as qmp:
                    qmp.settimeout(3)
                    qmp.connect(str(out / 'qmp.sock'))
                    with qmp.makefile('rwb') as stream:
                        assert 'QMP' in json.loads(stream.readline())

                        def execute(name, arguments=None):
                            message = {'execute': name}
                            if arguments:
                                message['arguments'] = arguments
                            stream.write(json.dumps(message).encode() + b'\n')
                            stream.flush()
                            while True:
                                reply = json.loads(stream.readline())
                                if 'event' not in reply:
                                    assert 'return' in reply, reply
                                    return reply['return']

                        execute('qmp_capabilities')
                        execute('cont')
                        # Window creation can follow the QMP socket by a few frames.
                        window = xdo('search', '--sync', '--onlyvisible', '--class', 'qemu').splitlines()[0]
                        xdo('windowfocus', '--sync', window)
                        time.sleep(.2)
                        print('window', xdo('getwindowgeometry', '--shell', window))

                        def capture(name):
                            subprocess.run(['import', '-window', window,
                                            str(BASE / name)], env=env, check=True)

                        capture('ordinary-qemu.png' if args.ordinary else 'native-controls.png')
                        if not args.capture_only and not args.ordinary:
                            # Find the native shell's GDK surface, independent of
                            # menubar/font heights and the window's screen position.
                            tree = subprocess.check_output(['xwininfo', '-tree', '-id', window], env=env, text=True)
                            surfaces = re.findall(r'^\s*(0x[0-9a-f]+).*?\b1040x754\b', tree, re.M)
                            assert len(surfaces) == 1, tree
                            def geometry(identifier):
                                return dict(line.split('=', 1) for line in xdo('getwindowgeometry', '--shell', identifier).splitlines())
                            shell_geometry, window_geometry = geometry(surfaces[0]), geometry(window)
                            origin_x = int(shell_geometry['X']) - int(window_geometry['X'])
                            origin_y = int(shell_geometry['Y']) - int(window_geometry['Y'])
                            print('CAMERA_ORIGIN', origin_x, origin_y)

                            def click(x, y):
                                xdo('mousemove', '--window', window, origin_x + x, origin_y + y)
                                xdo('click', 1)

                            def no_command():
                                try:
                                    unexpected = keys.recv(1)
                                except socket.timeout:
                                    return
                                raise AssertionError(('unexpected wire command', unexpected))

                            for key, wire in [('m', b'M'), ('Escape', b'M'),
                                              ('Return', b'E'), ('Up', b'U'),
                                              ('Down', b'D'), ('Left', b'L'),
                                              ('Right', b'R'), ('Delete', b'X'),
                                              ('Prior', b'<'), ('Next', b'>'), ('F12', b'S')]:
                                xdo('key', key)
                                assert keys.recv(1) == wire, key
                            for x, y, wire in [(866, 450, b'U'), (866, 586, b'D'),
                                               (798, 518, b'L'), (934, 518, b'R'),
                                               (866, 518, b'E'), (609, 200, b'M'), (940, 680, b'X'),
                                               (915, 138, b'<'), (973, 138, b'>')]:
                                click(x, y)
                                assert keys.recv(1) == wire, (x, y)
                                xdo('key', 'Down')
                                assert keys.recv(1) == b'D', 'focus after click'
                            # Click every unverified control; none may send bytes.
                            for x, y in [(722, 77), (861, 72), (934, 72), (991, 58),
                                         (726, 161), (704, 200), (828, 291), (828, 360), (830, 680),
                                         (774, 200), (830, 200), (892, 16), (944, 16)]:
                                click(x, y)
                            no_command()
                            # Canvas clicks focus without trapping the pointer.
                            click(396, 484)
                            click(609, 200)
                            assert keys.recv(1) == b'M', 'sidebar reachable after canvas click'
                            xdo('keydown', 'm')
                            assert keys.recv(1) == b'M'
                            xdo('keydown', 'm')
                            no_command()
                            xdo('keyup', 'm')
                            xdo('key', 'Tab')
                            capture('native-controls-tab-focus.png')
                            # A focused native button must not swallow arrow keys.
                            xdo('key', 'Right')
                            assert keys.recv(1) == b'R', 'arrow while control focused'
                            xdo('keydown', 'm')
                            assert keys.recv(1) == b'M'
                            # A real release after focus movement must not leave M stuck.
                            click(396, 484)
                            xdo('keyup', 'm')
                            xdo('keydown', 'm')
                            assert keys.recv(1) == b'M', 'new press after button focus-out'
                            xdo('keyup', 'm')
                            xdo('key', 'Tab')
                            xdo('key', 'space')
                            assert keys.recv(1) == b'<', 'keyboard button activation'
                            xdo('key', 'F12')
                            assert keys.recv(1) == b'S', 'focus restored after activation'
                            assert execute('qom-get', {'path': '/machine/peripheral/sony-controls',
                                                       'property': 'input-connected'}) is True
                            execute('stop')
                            click(609, 200)
                            no_command()
                            capture('native-controls-paused.png')
                            execute('cont')
                            keys.close()
                            time.sleep(.1)
                            assert execute('qom-get', {'path': '/machine/peripheral/sony-controls',
                                                       'property': 'input-connected'}) is False
                            click(609, 200)
                            capture('native-controls-disconnected.png')
                            print('PASS: GTK keyboard, nine clicks, focus restore, Tab/Space, arrows on button,')
                            print('      held suppression, 13 unavailable controls, pause/disconnect guards')
                        xdo('windowsize', window, 2560, 1440)
                        time.sleep(.2)
                        capture('ordinary-qemu-large.png' if args.ordinary else 'native-controls-large.png')
                        if args.capture_only or args.ordinary:
                            execute('quit')
                        else:
                            xdo('key', 'ctrl+alt+q')
                            print('PASS: standard GTK Quit accelerator')
                assert qemu.wait(timeout=5) == 0
        finally:
            keys.close()
            if qemu and qemu.poll() is None:
                qemu.terminate()
                qemu.wait(timeout=5)
            xvfb.terminate()
            xvfb.wait(timeout=5)


if __name__ == '__main__':
    main()
